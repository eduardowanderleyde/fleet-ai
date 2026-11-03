"""LLM medido: conta turnos, tokens, chamadas de ferramenta pedidas e tempo."""

import time
from typing import Any

from fleet_ai.llm import LlmPort, LlmResponse, ToolUseBlock


class MeteredLlm:
    def __init__(self, inner: LlmPort) -> None:
        self._inner = inner
        self.turns = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.seconds = 0.0

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LlmResponse:
        self.turns += 1
        started = time.perf_counter()
        try:
            response = await self._inner.complete(
                system=system, messages=messages, tools=tools, max_tokens=max_tokens
            )
        finally:
            self.seconds += time.perf_counter() - started
        self.tool_calls += sum(isinstance(block, ToolUseBlock) for block in response.content)
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        return response
