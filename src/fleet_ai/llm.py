"""Porta de LLM e o LLM roteirizado (ADR-0003, ADR-0004).

O planejador LLM depende só desta porta, nunca de um SDK. Na SPEC-001 a única
implementação é o LLM roteirizado: devolve respostas fixas, registra cada pedido
e falha alto se o roteiro acabar. Não há rede, chave de API nem custo.
"""

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


Block = TextBlock | ToolUseBlock


@dataclass(frozen=True)
class Usage:
    """Uso de tokens fictício: não entra na missão nem em orçamento (ADR-0004)."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class LlmResponse:
    content: tuple[Block, ...]
    stop_reason: str  # "end_turn", "tool_use" ou "max_tokens"; outro valor é inválido
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class LlmRequest:
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int


class LlmPort(Protocol):
    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LlmResponse: ...


class ScriptExhausted(Exception):
    """O roteiro acabou: o planejador pediu mais respostas do que o teste previu."""


class ScriptedLlm:
    """LLM roteirizado: a única implementação da porta na SPEC-001."""

    def __init__(self, responses: Iterable[LlmResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[LlmRequest] = []

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LlmResponse:
        # Cópia: o planejador continua acrescentando mensagens à mesma lista.
        self.requests.append(
            LlmRequest(system, copy.deepcopy(messages), copy.deepcopy(tools), max_tokens)
        )
        if len(self.requests) > len(self._responses):
            raise ScriptExhausted(f"script has {len(self._responses)} responses")
        return self._responses[len(self.requests) - 1]
