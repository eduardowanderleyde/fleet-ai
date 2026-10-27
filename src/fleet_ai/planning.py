"""Porta de planejador e o planejador determinístico (ADR-0004, SPEC-001).

O planejador determinístico reconhece intenções por regras, sem modelo de
linguagem, monta um plano fixo e o executa pelo despachante.
"""

import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fleet_ai.language import Language, detect_language, normalize, words
from fleet_ai.scenario import ScenarioNames
from fleet_ai.tools import Dispatcher

PlanStatus = Literal["completed", "not_understood"]


@dataclass(frozen=True)
class Destination:
    """Para onde mandar o robô: um lugar nomeado ou uma coordenada."""

    label: str
    x: float
    y: float
    yaw: float = 0.0
    coordinate: bool = False

    def describe(self, language: Language) -> str:
        """Lugar pelo nome; coordenada com o separador decimal do idioma."""
        if not self.coordinate:
            return self.label
        separator = "," if language == "pt" else "."
        return f"x {_decimal(self.x, separator)} y {_decimal(self.y, separator)}"


@dataclass(frozen=True)
class PlanOutcome:
    status: PlanStatus
    language: Language
    final_text: str


class Planner(Protocol):
    name: str

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome: ...


_MOVE_VERBS = {
    "leve",
    "levar",
    "mova",
    "mover",
    "mande",
    "envie",
    "va",
    "move",
    "send",
    "take",
    "go",
    "drive",
}

_EXAMPLES: dict[Language, tuple[str, ...]] = {
    "pt": (
        "leve o tb1 até a doca de carga",
        "onde está o tb2?",
        "mova o robô 1 para x 1,5 y 2",
    ),
    "en": (
        "move tb1 to the loading dock",
        "where is tb2?",
        "send robot 1 to (1.5, 2)",
    ),
}


class DeterministicPlanner:
    name = "deterministic"

    def __init__(self, names: ScenarioNames) -> None:
        self._robots = {
            normalize(alias): robot.robot_id
            for robot in names.robots
            for alias in (robot.robot_id, *robot.aliases)
        }
        self._places = {
            normalize(alias): Destination(place.name, place.x, place.y, place.yaw)
            for place in names.places
            for alias in (place.name, *place.synonyms)
        }
        self._robot_names = ", ".join(robot.robot_id for robot in names.robots)
        self._place_names = ", ".join(place.name for place in names.places)

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        outcome = await self._plan(instruction, robot_id, dispatcher)
        if robot_id is None or outcome.status != "completed":
            return outcome
        # O despachante já força o robô; o texto deixa o escopo explícito.
        scope = _SCOPE_TEXT[outcome.language].format(robot=robot_id)
        return PlanOutcome(outcome.status, outcome.language, f"{scope} {outcome.final_text}")

    async def _plan(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        text = normalize(instruction)
        language = detect_language(instruction)
        places = _find_all(text, self._places)
        coordinate = _coordinate(text)
        intents = _intents(text)
        if _SEQUENCE.search(text) or len(intents) > 1 or len(places) + bool(coordinate) > 1:
            return self._not_understood("multiple_actions", language)
        named = _find(text, self._robots)
        robot_like = _ROBOT_LIKE.search(text)
        if robot_id is not None:
            # Conflito de escopo: a instrução cita outro robô (SPEC-001). Nada é
            # executado; o despachante continua forçando o escopo para qualquer planejador.
            other = named if named is not None else (robot_like.group(0) if robot_like else None)
            if other is not None and other != robot_id:
                text_ = _SCOPE_CONFLICT[language].format(named=other, scope=robot_id)
                return PlanOutcome("not_understood", language, text_)
        robot = robot_id or named
        if robot is None and robot_like:
            return self._not_understood("unknown_robot", language)
        if intents == {"list"}:
            return await _list_robots(language, dispatcher)
        if robot is not None and intents == {"cancel"}:
            return await _cancel(robot, language, dispatcher)
        if robot is not None and intents == {"status"}:
            return await _robot_status(robot, language, dispatcher)
        if robot is not None and intents == {"move"}:
            destination = coordinate or (places[0] if places else None)
            if destination is None:
                return self._not_understood("unknown_place", language)
            return await _move_to(robot, destination, language, dispatcher)
        return PlanOutcome("not_understood", language, _examples_text(language))

    def _not_understood(self, reason: str, language: Language) -> PlanOutcome:
        names = {"unknown_robot": self._robot_names, "unknown_place": self._place_names}
        text = _NOT_UNDERSTOOD[reason][language].format(names=names.get(reason, ""))
        return PlanOutcome("not_understood", language, text)


_SCOPE_CONFLICT: dict[Language, str] = {
    "pt": (
        "A instrução cita o {named}, mas esta missão está restrita ao {scope}. "
        "Nada foi executado; envie a instrução para o {scope} ou sem escopo."
    ),
    "en": (
        "The instruction names {named}, but this mission is restricted to {scope}. "
        "Nothing was executed; send the instruction for {scope} or without a scope."
    ),
}

_SCOPE_TEXT: dict[Language, str] = {
    "pt": "Missão restrita ao {robot}.",
    "en": "Mission restricted to {robot}.",
}

# Conectores de sequência: duas ações na mesma instrução (só uma por missão).
_SEQUENCE = re.compile(r"\b(?:e depois|depois|em seguida|e entao|then|and then|after that)\b")
# Algo que parece um robô (tb9, robo 5, robot 7) e não está no cenário.
_ROBOT_LIKE = re.compile(r"\b(?:tb|robo|robot)\s*\d+\b")

_NOT_UNDERSTOOD: dict[str, dict[Language, str]] = {
    "multiple_actions": {
        "pt": "Só consigo executar uma ação por missão. Envie uma instrução de cada vez.",
        "en": "I can only do one action per mission. Send one instruction at a time.",
    },
    "unknown_robot": {
        "pt": "Não conheço esse robô. Robôs do cenário: {names}.",
        "en": "I do not know that robot. Robots in the scenario: {names}.",
    },
    "unknown_place": {
        "pt": "Não conheço esse lugar. Lugares do cenário: {names}.",
        "en": "I do not know that place. Places in the scenario: {names}.",
    },
}


def _intents(text: str) -> set[str]:
    """As intenções que a instrução menciona; mais de uma é recusada."""
    found = words(text)
    intents = set()
    if _is_list(text):
        intents.add("list")
    if found & _CANCEL_VERBS:
        intents.add("cancel")
    if _is_status(text):
        intents.add("status")
    if found & _MOVE_VERBS:
        intents.add("move")
    return intents


_LIST_VERBS = {
    "liste",
    "listar",
    "lista",
    "quais",
    "mostre",
    "mostrar",
    "list",
    "which",
    "what",
    "show",
}
_FLEET_WORDS = {"robos", "robo", "frota", "robots", "fleet"}


def _is_list(text: str) -> bool:
    found = words(text)
    return bool(found & _LIST_VERBS) and bool(found & _FLEET_WORDS)


async def _list_robots(language: Language, dispatcher: Dispatcher) -> PlanOutcome:
    result, _ = await dispatcher.call("list_robots", {})
    names = ", ".join(result["robot_ids"])
    text = f"Robôs na frota: {names}." if language == "pt" else f"Robots in the fleet: {names}."
    return PlanOutcome("completed", language, text)


_CANCEL_VERBS = {
    "pare",
    "parar",
    "cancele",
    "cancelar",
    "interrompa",
    "interromper",
    "aborte",
    "stop",
    "cancel",
    "abort",
    "halt",
}

_CANCEL_TEXTS: dict[str, dict[Language, str]] = {
    "confirmed": {
        "pt": "A navegação do {robot} foi cancelada; ele está parado.",
        "en": "The navigation of {robot} was cancelled; it is stopped.",
    },
    "ambiguous": {
        "pt": "O {robot} parou, mas não é possível afirmar que foi pelo cancelamento.",
        "en": "{robot} stopped, but it is not possible to say it was the cancellation.",
    },
    "not_confirmed": {
        "pt": "O cancelamento foi aceito, mas o {robot} continua navegando.",
        "en": "The cancel was accepted, but {robot} is still navigating.",
    },
    "CANCEL_FAILED": {
        "pt": "Não havia navegação ativa do {robot} para cancelar.",
        "en": "There was no active navigation of {robot} to cancel.",
    },
    "backend_unavailable": {
        "pt": "Não foi possível cancelar a navegação do {robot}; ele pode continuar navegando.",
        "en": "The navigation of {robot} could not be cancelled; it may still be navigating.",
    },
}


async def _cancel(robot: str, language: Language, dispatcher: Dispatcher) -> PlanOutcome:
    result, refused = await dispatcher.call("cancel_navigation", {"robot_id": robot})
    key = result["error_code"] if refused else result["outcome"]
    return PlanOutcome("completed", language, cancel_text(robot, key, language))


def cancel_text(robot: str, outcome: str, language: Language) -> str:
    """Texto do resultado de um cancelamento; só `confirmed` diz que cancelou (ADR-0005)."""
    templates = _CANCEL_TEXTS.get(outcome)
    if templates is None:
        return _refused(robot, outcome, language)
    return templates[language].format(robot=robot)


_STATUS_PHRASES = (
    "onde esta",
    "estado",
    "status",
    "posicao",
    "como esta",
    "where is",
    "position",
    "how is",
    "state",
)


def _is_status(text: str) -> bool:
    return any(re.search(rf"\b{phrase}\b", text) for phrase in _STATUS_PHRASES)


_NAV_STATE_TEXT: dict[str, dict[Language, str]] = {
    "idle": {"pt": "parado", "en": "idle"},
    "navigating": {"pt": "navegando", "en": "navigating"},
    "failed": {
        "pt": "parado depois de uma navegação que falhou",
        "en": "stopped after a failed navigation",
    },
}


async def _robot_status(robot: str, language: Language, dispatcher: Dispatcher) -> PlanOutcome:
    status, refused = await dispatcher.call("get_robot_status", {"robot_id": robot})
    if refused:
        return PlanOutcome("completed", language, _refused(robot, status["error_code"], language))
    state = _NAV_STATE_TEXT[status["nav_state"]][language]
    x, y = status["pose"]["x"], status["pose"]["y"]
    if language == "pt":
        text = f"O {robot} está {state} em x {_decimal(x, ',')} m, y {_decimal(y, ',')} m."
    else:
        text = f"{robot} is {state} at x {_decimal(x)} m, y {_decimal(y)} m."
    if status["last_error"]:
        text += f" ({status['last_error']})"
    return PlanOutcome("completed", language, text)


async def _move_to(
    robot: str, destination: Destination, language: Language, dispatcher: Dispatcher
) -> PlanOutcome:
    await dispatcher.call("get_robot_status", {"robot_id": robot})
    move, refused = await dispatcher.call(
        "move_robot",
        {"robot_id": robot, "x": destination.x, "y": destination.y, "yaw": destination.yaw},
    )
    if refused:
        return PlanOutcome("completed", language, _refused(robot, move["error_code"], language))
    final, _ = await dispatcher.call("wait_for_arrival", {"robot_id": robot})
    if final["nav_state"] == "failed":
        text = _not_reached(robot, destination.describe(language), final["last_error"], language)
    else:
        text = _arrived(robot, destination.describe(language), final, language)
    return PlanOutcome("completed", language, text)


def _arrived(robot: str, label: str, final: dict[str, Any], language: Language) -> str:
    x, y = final["pose"]["x"], final["pose"]["y"]
    if language == "pt":
        return (
            f'O {robot} chegou ao destino "{label}". '
            f"Pose final: x {_decimal(x, ',')} m, y {_decimal(y, ',')} m."
        )
    return f'{robot} arrived at "{label}". Final pose: x {_decimal(x)} m, y {_decimal(y)} m.'


def _not_reached(robot: str, label: str, last_error: str, language: Language) -> str:
    if language == "pt":
        return (
            f'O {robot} não conseguiu chegar a "{label}": '
            f"o destino não pôde ser alcançado ({last_error})."
        )
    return f'{robot} did not reach "{label}": the destination could not be reached ({last_error}).'


# Números: vírgula ou ponto decimal; nas formas em que a vírgula separa x de y,
# só ponto decimal.
_NUM = r"-?\d+(?:[.,]\d+)?"
_NUM_DOT = r"-?\d+(?:\.\d+)?"
_COORDINATE_FORMS = (
    rf"\bx\s*[=:]?\s*({_NUM})\s*[,;]?\s*y\s*[=:]?\s*({_NUM})",  # x 3,5 y -1 / x=2 y=1
    rf"\(\s*({_NUM})\s*;\s*({_NUM})\s*\)",  # (1; 2,5)
    rf"\(\s*({_NUM_DOT})\s*,\s*({_NUM_DOT})\s*\)",  # (2, 4)
    rf"\b(?:to|para|ate)\s+({_NUM_DOT})\s*,\s*({_NUM_DOT})\b",  # to 2.0, 4.0
)
_YAW = re.compile(
    rf"\b(?:facing|heading|yaw|virado para|virado a|orientacao|apontando para)\s*({_NUM})"
)


def _coordinate(text: str) -> Destination | None:
    """Coordenada em uma das formas aceitas, com yaw opcional em graus (SPEC-001)."""
    for form in _COORDINATE_FORMS:
        match = re.search(form, text)
        if match is not None:
            x, y = (_number(group) for group in match.groups())
            yaw = _YAW.search(text)
            yaw_rad = math.radians(_number(yaw.group(1))) if yaw else 0.0
            return Destination("", x, y, yaw_rad, coordinate=True)
    return None


def _number(text: str) -> float:
    return float(text.replace(",", "."))


# Por que o backend recusou o comando, pelo `error_code` (ADR-0005).
_REFUSALS: dict[str, dict[Language, str]] = {
    "ROLE_NOT_ALLOWED": {
        "pt": "O {robot} não pode se mover: o papel dele na frota não permite movimento.",
        "en": "{robot} cannot move: its role in the fleet does not allow movement.",
    },
    "ALREADY_NAVIGATING": {
        "pt": (
            "O {robot} já está navegando para outro destino. "
            'Para mudar o destino, cancele antes: "pare o {robot}".'
        ),
        "en": (
            "{robot} is already navigating to another destination. "
            'To change it, cancel first: "stop {robot}".'
        ),
    },
}


def _refused(robot: str, error_code: str, language: Language) -> str:
    templates = _REFUSALS.get(error_code)
    if templates is not None:
        return templates[language].format(robot=robot)
    if language == "pt":
        return f"O comando para o {robot} foi recusado ({error_code})."
    return f"The command for {robot} was refused ({error_code})."


def _examples_text(language: Language) -> str:
    examples = "; ".join(f'"{example}"' for example in _EXAMPLES[language])
    if language == "pt":
        return f"Não entendi a instrução. Exemplos do que posso fazer: {examples}."
    return f"I did not understand the instruction. Examples of what I can do: {examples}."


def _find_all[T](text: str, names: dict[str, T]) -> list[T]:
    """Os nomes que aparecem no texto, sem contar duas vezes trechos sobrepostos
    ("doca de carga" e "doca") nem dois apelidos do mesmo lugar."""
    taken: list[tuple[int, int]] = []
    found: list[T] = []
    for name in sorted(names, key=len, reverse=True):
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            if names[name] not in found:
                found.append(names[name])
    return found


def _find[T](text: str, names: dict[str, T]) -> T | None:
    """O nome mais longo que aparece como palavras inteiras no texto."""
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            return names[name]
    return None


def _decimal(value: float, separator: str = ".") -> str:
    return f"{value:.2f}".replace(".", separator)
