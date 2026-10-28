"""Planejador LLM: o loop de tool use portado do Fleet UI (ADR-0003, ADR-0004).

Portado de fleet-ui@a57a3b1:backend/agents/planner.py (licença MIT, ver
THIRD_PARTY_NOTICES.md). Mantém as regras de sistema de lá e acrescenta "aguardar
a chegada antes de declarar sucesso" e "responder no idioma da instrução". Fala
com o modelo só pela porta de LLM e age na frota só pelo despachante.
"""

import json
import math
import re
from typing import Any

from fleet_ai.language import Language, detect_language
from fleet_ai.llm import LlmPort, LlmResponse, TextBlock, ToolUseBlock
from fleet_ai.planning import PlanOutcome, PlanStatus
from fleet_ai.tools import Dispatcher

DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_TOOL_CALLS_PER_TURN = 4
DEFAULT_MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "Você orquestra uma frota de robôs TurtleBot4 através de um conjunto fixo de ferramentas. "
    "Nunca invente robôs, rotas ou run_ids que não tenham sido retornados por uma ferramenta. "
    "Sempre confira o estado do robô antes de comandos de movimento, "
    "e resuma o resultado ao final. "
    "Depois de mover um robô, aguarde a chegada com wait_for_arrival antes de declarar sucesso. "
    "Responda no idioma da instrução."
)


_ROBOT = {"robot_id": {"type": "string", "description": "ID do robô."}}

# As cinco ferramentas do MVP no formato de tool use do Fleet UI
# (fleet-ui@a57a3b1:backend/agents/tools.py), sem as de rotas e coleta.
TOOL_SPECS: dict[str, dict[str, Any]] = {
    "list_robots": {
        "description": "Lista os IDs dos robôs conhecidos pela frota.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_robot_status": {
        "description": "Estado atual de um robô: papel, nav_state, pose e último erro.",
        "input_schema": {"type": "object", "properties": _ROBOT, "required": ["robot_id"]},
    },
    "move_robot": {
        "description": "Envia o robô para um ponto (x, y, yaw); a navegação é assíncrona.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_ROBOT,
                "x": {"type": "number"},
                "y": {"type": "number"},
                "yaw": {"type": "number", "default": 0.0},
            },
            "required": ["robot_id", "x", "y"],
        },
    },
    "wait_for_arrival": {
        "description": "Aguarda o fim da navegação do robô e devolve o estado final.",
        "input_schema": {"type": "object", "properties": _ROBOT, "required": ["robot_id"]},
    },
    "cancel_navigation": {
        "description": "Cancela a navegação do robô e verifica o resultado.",
        "input_schema": {"type": "object", "properties": _ROBOT, "required": ["robot_id"]},
    },
}


# Mensagens do Fleet AI para cada recusa: o modelo nunca recebe o texto bruto do
# backend nem uma exceção interna (SPEC-001).
_REFUSAL_MESSAGES = {
    "INVALID_REQUEST": "The fleet rejected the request as invalid.",
    "UNKNOWN_ROBOT": "The robot is not known to the fleet.",
    "ROLE_NOT_ALLOWED": "The robot's role does not allow movement.",
    "ALREADY_NAVIGATING": "The robot is already navigating.",
    "CANCEL_FAILED": "The fleet could not cancel the navigation.",
}


class InvalidLlmResponse(Exception):
    """Resposta fora do contrato da porta de LLM: a missão termina `failed`."""


_STOP_REASONS = {"end_turn", "tool_use", "max_tokens"}


def _check_response(response: LlmResponse) -> None:
    """Valida a resposta antes de executar qualquer ferramenta dela."""
    if response.stop_reason not in _STOP_REASONS:
        raise InvalidLlmResponse(f"unknown stop_reason {response.stop_reason!r}")
    if not all(isinstance(b, TextBlock | ToolUseBlock) for b in response.content):
        raise InvalidLlmResponse("unknown content block")
    calls = [b for b in response.content if isinstance(b, ToolUseBlock)]
    if (response.stop_reason == "tool_use") != bool(calls):
        raise InvalidLlmResponse("tool_use blocks do not match the stop_reason")
    ids = [call.id for call in calls]
    if not all(isinstance(i, str) and i for i in ids) or len(set(ids)) != len(ids):
        raise InvalidLlmResponse("tool_use ids must be unique and non-empty")
    if not all(isinstance(call.name, str) for call in calls):
        raise InvalidLlmResponse("tool_use name must be text")


def _ending(
    dispatcher: Dispatcher, status: PlanStatus, text: str, language: Language
) -> PlanOutcome:
    """Com navegação desta missão ainda ativa, nunca `completed` (SPEC-001).

    Não há cancelamento automático aqui (ADR-0006): o texto avisa que o robô pode
    continuar navegando e que nenhum cancelamento foi confirmado.
    """
    robot = dispatcher.navigating
    if robot is None:
        return PlanOutcome(status, language, text)
    warning = _STILL_NAVIGATING[language].format(robot=robot)
    return PlanOutcome("incomplete", language, f"{warning} {text}".strip())


_STILL_NAVIGATING: dict[Language, str] = {
    "pt": (
        "A missão terminou com a navegação do {robot} ainda ativa: o robô pode continuar "
        "navegando, e não houve cancelamento confirmado."
    ),
    "en": (
        "The mission ended with the navigation of {robot} still active: the robot may keep "
        "navigating, and no cancellation was confirmed."
    ),
}

_TRUNCATED: dict[Language, str] = {
    "pt": "A resposta do planejador foi interrompida pelo limite de tokens; a missão não terminou.",
    "en": "The planner's answer was cut off by the token limit; the mission did not finish.",
}

_TURN_LIMIT: dict[Language, str] = {
    "pt": "A missão atingiu o limite de {turns} turnos do planejador antes de terminar.",
    "en": "The mission reached the planner limit of {turns} turns before ending.",
}


def _refusal(error_code: str) -> dict[str, str]:
    message = _REFUSAL_MESSAGES.get(error_code, "The fleet refused the command.")
    return {
        "error_code": error_code if error_code in _REFUSAL_MESSAGES else "REFUSED",
        "message": message,
    }


# Códigos de `last_error` do contrato (ADR-0005); qualquer outro texto do backend
# vira um código genérico antes de chegar ao modelo.
_KNOWN_LAST_ERRORS = {"", "NAV2_REJECTED", "NAV2_ABORTED"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _for_model(result: dict[str, Any]) -> dict[str, Any]:
    """Resultado de sucesso sem texto livre do backend: só campos do contrato."""
    if "last_error" not in result:
        return result
    view = dict(result)
    if view["last_error"] not in _KNOWN_LAST_ERRORS:
        view["last_error"] = "NAV_ERROR"
    if not _IDENTIFIER.fullmatch(str(view.get("role", ""))):
        view["role"] = "UNKNOWN"
    return view


def _as_message(block: TextBlock | ToolUseBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}


# Erros detectados pelo próprio planejador, antes do despachante.
_PLANNER_ERRORS = {
    "TOO_MANY_TOOL_CALLS": "Too many tool calls in one turn; this call was not executed.",
    "UNKNOWN_TOOL": "Unknown tool; use only the tools provided.",
    "INVALID_INPUT": "Invalid tool input; check the tool's input schema.",
}


def _finite_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _valid_input(tool: str, tool_input: object) -> bool:
    """`input` segue o schema da ferramenta: só os campos dela, com os tipos certos.

    `robot_id` é texto não vazio; coordenadas são números finitos (bool não conta).
    """
    schema = TOOL_SPECS[tool]["input_schema"]
    if not isinstance(tool_input, dict) or not set(tool_input) <= set(schema["properties"]):
        return False
    if not set(schema.get("required", ())) <= set(tool_input):
        return False
    for key, value in tool_input.items():
        if key == "robot_id":
            if not (isinstance(value, str) and value):
                return False
        elif not _finite_number(value):
            return False
    return True


def _tool_error(call_id: str, error_code: str) -> dict[str, Any]:
    error = {"error_code": error_code, "message": _PLANNER_ERRORS[error_code]}
    return _tool_result(call_id, error, is_error=True)


def _tool_result(call_id: str, result: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": json.dumps(result),
        "is_error": is_error,
    }


class LlmPlanner:
    name = "llm"

    def __init__(
        self,
        llm: LlmPort,
        *,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tool_calls_per_turn: int = DEFAULT_MAX_TOOL_CALLS_PER_TURN,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._llm = llm
        self._max_turns = max_turns
        self._max_tool_calls_per_turn = max_tool_calls_per_turn
        self._max_tokens = max_tokens

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        language = detect_language(instruction)
        # Exatamente as ferramentas do despachante, e nenhuma outra (SPEC-001).
        tools = [{"name": name, **TOOL_SPECS[name]} for name in dispatcher.tool_names]
        system = SYSTEM_PROMPT
        if robot_id is not None:
            # Informativo: quem garante o escopo é o despachante.
            system += f" Você está restrito ao robô '{robot_id}' — não pode operar nenhum outro."
        messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
        for _ in range(self._max_turns):
            response = await self._llm.complete(
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=self._max_tokens,
            )
            _check_response(response)
            messages.append(
                {"role": "assistant", "content": [_as_message(b) for b in response.content]}
            )
            text = "".join(b.text for b in response.content if isinstance(b, TextBlock))
            if response.stop_reason == "max_tokens":
                # Resposta truncada: não dá para confiar nela como resultado.
                return _ending(dispatcher, "incomplete", _TRUNCATED[language], language)
            if response.stop_reason == "end_turn":
                return _ending(dispatcher, "completed", text, language)
            results = []
            forwarded = 0  # chamadas entregues ao despachante neste turno, inclusive recusas
            for block in response.content:
                if not isinstance(block, ToolUseBlock):
                    continue
                # Valida antes de executar: inválidas nunca chegam ao despachante e
                # não gastam a cota do turno.
                if block.name not in dispatcher.tool_names:
                    results.append(_tool_error(block.id, "UNKNOWN_TOOL"))
                    continue
                if not _valid_input(block.name, block.input):
                    results.append(_tool_error(block.id, "INVALID_INPUT"))
                    continue
                if forwarded >= self._max_tool_calls_per_turn:
                    # Excedente: responde ao modelo sem nunca chegar ao despachante.
                    results.append(_tool_error(block.id, "TOO_MANY_TOOL_CALLS"))
                    continue
                forwarded += 1
                result, is_error = await dispatcher.call(block.name, block.input)
                result = _refusal(result["error_code"]) if is_error else _for_model(result)
                results.append(_tool_result(block.id, result, is_error=is_error))
            messages.append({"role": "user", "content": results})
        text = _TURN_LIMIT[language].format(turns=self._max_turns)
        return _ending(dispatcher, "incomplete", text, language)
