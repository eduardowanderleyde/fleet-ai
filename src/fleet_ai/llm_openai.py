"""Adaptador de LLM no formato `/v1/chat/completions` do OpenAI (SPEC-005, ADR-0007).

Usado com o Ollama, um modelo local e gratuito: sem SDK, só `httpx2`, e sem chave
de API. Converte os blocos da porta (texto, `tool_use`, `tool_result`) de e para
o formato de mensagens com `tool_calls`. Uma chamada por vez, porque o modelo roda
na CPU da VPS.
"""

import asyncio
import json
import logging
from typing import Any

import httpx2

from fleet_ai.llm import Block, LlmResponse, TextBlock, ToolUseBlock, Usage

log = logging.getLogger("fleet_ai.llm")

DEFAULT_TIMEOUT_S = 120.0
DEFAULT_BUSY_TIMEOUT_S = 60.0
MAX_RESPONSE_BYTES = 2_000_000


class LlmUnavailable(Exception):
    """O modelo não respondeu de forma utilizável; a missão termina `failed`.

    A mensagem é fixa e curta: URL, corpo e texto do provedor vão só para o log.
    """


class OpenAICompatLlm:
    def __init__(
        self,
        url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        busy_timeout: float = DEFAULT_BUSY_TIMEOUT_S,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._url = url.rstrip("/") + "/chat/completions"
        self._client = httpx2.AsyncClient(timeout=timeout, transport=transport)
        self._busy_timeout = busy_timeout
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LlmResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *_messages(messages)],
            "tools": [_tool(spec) for spec in tools],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        try:
            await asyncio.wait_for(self._lock.acquire(), self._busy_timeout)
        except TimeoutError:
            raise LlmUnavailable("llm busy") from None
        try:
            body = await self._post(payload)
        finally:
            self._lock.release()
        return _response(body)

    async def _post(self, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx2.TimeoutException:
            log.warning("llm_error kind=timeout")
            raise LlmUnavailable("llm timeout") from None
        except httpx2.HTTPError as exc:
            log.warning("llm_error kind=%s", type(exc).__name__)
            raise LlmUnavailable("llm unreachable") from None
        if response.status_code != 200:
            log.warning("llm_error kind=status status=%s", response.status_code)
            raise LlmUnavailable("llm error status")
        if len(response.content) > MAX_RESPONSE_BYTES:
            log.warning("llm_error kind=too_big bytes=%s", len(response.content))
            raise LlmUnavailable("llm response too big")
        try:
            return json.loads(response.content)
        except ValueError:
            log.warning("llm_error kind=not_json")
            raise LlmUnavailable("llm response is not json") from None


def _tool(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec["description"],
            "parameters": spec["input_schema"],
        },
    }


def _messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mensagens da porta (no formato de blocos do planejador) → formato do OpenAI."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
        elif message["role"] == "assistant":
            text = "".join(block["text"] for block in content if block["type"] == "text")
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            calls = [
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                }
                for block in content
                if block["type"] == "tool_use"
            ]
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
        else:
            converted.extend(
                {"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]}
                for block in content
                if block["type"] == "tool_result"
            )
    return converted


def _response(body: Any) -> LlmResponse:
    """Formato do OpenAI → resposta da porta; qualquer coisa fora dele é inválida."""
    try:
        choice = body["choices"][0]
        message = choice["message"]
        finish = choice["finish_reason"]
        usage = body.get("usage") or {}
        blocks: list[Block] = []
        if message.get("content"):
            blocks.append(TextBlock(str(message["content"])))
        for index, call in enumerate(message.get("tool_calls") or ()):
            function = call["function"]
            arguments = function["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            blocks.append(
                ToolUseBlock(call.get("id") or f"call_{index}", function["name"], arguments)
            )
        tokens = Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        log.warning("llm_error kind=malformed")
        raise LlmUnavailable("llm response is malformed") from None
    calls = any(isinstance(block, ToolUseBlock) for block in blocks)
    if finish == "length":
        stop_reason = "max_tokens"
    elif finish in ("stop", "tool_calls"):
        # O Ollama responde `stop` mesmo quando pede ferramentas.
        stop_reason = "tool_use" if calls else "end_turn"
    else:
        log.warning("llm_error kind=finish_reason")
        raise LlmUnavailable("llm finish reason is unknown")
    return LlmResponse(tuple(blocks), stop_reason, tokens)
