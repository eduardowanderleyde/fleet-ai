"""Adaptador compatível com OpenAI e modelo local no Ollama (SPEC-005, ticket 02).

Seam: `OpenAICompatLlm` contra um servidor falso em processo (`httpx2.MockTransport`)
que registra o pedido e devolve respostas no formato do OpenAI; o planejador LLM e
a API HTTP do Fleet AI com esse adaptador e o SimFleet em processo. Nenhum teste
chama o Ollama de verdade.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from fleet_ai.app import create_app
from fleet_ai.config import llm_from_env
from fleet_ai.llm import TextBlock, ToolUseBlock, Usage
from fleet_ai.llm_openai import LlmUnavailable, OpenAICompatLlm
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

URL = "http://ollama:11434/v1"
TOOLS = [
    {
        "name": "move_robot",
        "description": "Envia o robô para um ponto.",
        "input_schema": {"type": "object", "properties": {"x": {"type": "number"}}},
    }
]


def reply(
    *,
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish: str = "stop",
    usage: tuple[int, int] = (11, 7),
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }


def call(call_id: str, name: str, arguments: Any) -> dict[str, Any]:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class FakeServer:
    """Registra cada pedido e responde com o que o teste preparou."""

    def __init__(self, *bodies: dict[str, Any] | Callable[[], httpx2.Response]) -> None:
        self.bodies = list(bodies)
        self.requests: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.headers: list[httpx2.Headers] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.paths.append(request.url.path)
        self.headers.append(request.headers)
        body = self.bodies.pop(0)
        if callable(body):
            return body()
        return httpx2.Response(200, json=body)

    def llm(self, **options: Any) -> OpenAICompatLlm:
        return OpenAICompatLlm(URL, "qwen2.5:3b", transport=httpx2.MockTransport(self), **options)


async def complete(llm: OpenAICompatLlm, messages: list[dict[str, Any]] | None = None) -> Any:
    return await llm.complete(
        system="Regras.",
        messages=messages or [{"role": "user", "content": "leve o tb1 até a doca"}],
        tools=TOOLS,
        max_tokens=256,
    )


async def test_request_carries_system_tools_and_tool_results_in_openai_format() -> None:
    server = FakeServer(reply(content="Pronto."))
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "leve o tb1 até a doca"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Vou mover."},
                {"type": "tool_use", "id": "c1", "name": "move_robot", "input": {"x": 2.0}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": '{"ok": true}',
                    "is_error": False,
                },
            ],
        },
    ]

    await complete(server.llm(), history)

    [body] = server.requests
    assert server.paths == ["/v1/chat/completions"]
    assert body["model"] == "qwen2.5:3b"
    assert body["max_tokens"] == 256
    assert body["temperature"] == 0
    assert body["stream"] is False
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "move_robot",
                "description": "Envia o robô para um ponto.",
                "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
            },
        }
    ]
    assert body["messages"] == [
        {"role": "system", "content": "Regras."},
        {"role": "user", "content": "leve o tb1 até a doca"},
        {
            "role": "assistant",
            "content": "Vou mover.",
            "tool_calls": [call("c1", "move_robot", {"x": 2.0})],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
    ]
    assert "authorization" not in server.headers[0]


@pytest.mark.parametrize(
    ("body", "content", "stop_reason"),
    [
        (reply(content="Pronto."), (TextBlock("Pronto."),), "end_turn"),
        (
            reply(tool_calls=[call("c1", "move_robot", {"x": 2.0})], finish="tool_calls"),
            (ToolUseBlock("c1", "move_robot", {"x": 2.0}),),
            "tool_use",
        ),
        # O Ollama devolve `stop` mesmo quando pede ferramentas.
        (
            reply(content="", tool_calls=[call("c1", "move_robot", {"x": 2.0})]),
            (ToolUseBlock("c1", "move_robot", {"x": 2.0}),),
            "tool_use",
        ),
        (reply(content="Pron", finish="length"), (TextBlock("Pron"),), "max_tokens"),
        # Argumentos já como objeto e chamada sem id (alguns servidores fazem isso).
        (
            reply(
                tool_calls=[
                    {"type": "function", "function": {"name": "move_robot", "arguments": {"x": 1}}}
                ]
            ),
            (ToolUseBlock("call_0", "move_robot", {"x": 1}),),
            "tool_use",
        ),
    ],
    ids=["text", "tool_calls", "ollama_stop_with_tools", "length", "object_arguments"],
)
async def test_tool_calls_and_finish_reasons_map_to_port_blocks(
    body: dict[str, Any], content: tuple[Any, ...], stop_reason: str
) -> None:
    response = await complete(FakeServer(body).llm())

    assert response.content == content
    assert response.stop_reason == stop_reason
    assert response.usage == Usage(11, 7)


@pytest.mark.parametrize(
    "body",
    [
        reply(tool_calls=[call("c1", "move_robot", "{not json")]),
        reply(tool_calls=[call("c1", "move_robot", "[1, 2]")]),
        reply(content="x", finish="content_filter"),
        {"choices": []},
        {"unexpected": True},
    ],
    ids=["bad_json", "arguments_not_object", "unknown_finish", "no_choices", "no_choices_key"],
)
async def test_malformed_responses_raise(body: dict[str, Any]) -> None:
    with pytest.raises(LlmUnavailable):
        await complete(FakeServer(body).llm())


def status(
    code: int, text: str = "raw provider text http://ollama:11434 secret"
) -> Callable[[], httpx2.Response]:
    return lambda: httpx2.Response(code, text=text)


def timeout() -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out")


def refused() -> httpx2.Response:
    raise httpx2.ConnectError("connection refused to http://ollama:11434")


@pytest.mark.parametrize(
    "body",
    [
        status(500),
        status(404),
        timeout,
        refused,
        status(200, json.dumps(reply(content="x" * 2_000_001))),
        status(200, "<html>"),
    ],
    ids=["500", "404", "timeout", "refused", "too_big", "not_json"],
)
async def test_provider_errors_raise_without_details(body: Callable[[], httpx2.Response]) -> None:
    with pytest.raises(LlmUnavailable) as raised:
        await complete(FakeServer(body).llm())

    assert "ollama" not in str(raised.value) and "secret" not in str(raised.value)
    assert "raw provider" not in repr(raised.value)


class Gate:
    """Servidor que segura cada resposta até `release` e mede a concorrência."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.active = 0
        self.peak = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await self.release.wait()
        self.active -= 1
        return httpx2.Response(200, json=reply(content="Pronto."))

    def llm(self, busy_timeout: float) -> OpenAICompatLlm:
        return OpenAICompatLlm(
            URL, "qwen2.5:3b", transport=httpx2.MockTransport(self), busy_timeout=busy_timeout
        )


async def test_only_one_llm_call_runs_at_a_time() -> None:
    gate = Gate()
    llm = gate.llm(busy_timeout=5.0)
    calls = [asyncio.create_task(complete(llm)) for _ in range(3)]
    await asyncio.sleep(0.01)
    gate.release.set()
    responses = await asyncio.gather(*calls)

    assert gate.peak == 1
    assert [r.stop_reason for r in responses] == ["end_turn"] * 3
    await llm.aclose()


async def test_a_busy_llm_fails_after_the_wait_limit() -> None:
    gate = Gate()
    llm = gate.llm(busy_timeout=0.05)
    first = asyncio.create_task(complete(llm))
    await asyncio.sleep(0.01)

    try:
        # Sem o limite de espera, a segunda chamada ficaria presa no servidor.
        async with asyncio.timeout(2):
            with pytest.raises(LlmUnavailable, match="busy"):
                await complete(llm)
    finally:
        gate.release.set()
    await first
    await llm.aclose()


# --- planejador LLM, configuração e API com o adaptador ------------------------

DOCK = (2.0, 13.5)


async def test_system_prompt_lists_scenario_places_and_robot_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(reply(content="Pronto."))
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    async with mission_stack(llm=server.llm()) as stack:
        await stack.run_mission("onde está o tb1?")

    system = server.requests[0]["messages"][0]["content"]
    # O modelo só conhece coordenadas pelas ferramentas; os lugares vêm do cenário.
    assert "doca de carga (x 2.0, y 13.5)" in system
    assert "base (x 0.0, y 1.0)" in system
    assert "tb1 (robô 1, robot 1, robot one)" in system
    assert "Nunca invente robôs" in system  # as regras de antes continuam


async def test_openai_compat_mission_completes_with_the_fake_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(
        reply(
            tool_calls=[call("c1", "move_robot", {"robot_id": "tb1", "x": DOCK[0], "y": DOCK[1]})],
            usage=(100, 10),
        ),
        reply(tool_calls=[call("c2", "wait_for_arrival", {"robot_id": "tb1"})], usage=(150, 12)),
        reply(content="O tb1 chegou à doca de carga.", usage=(200, 14)),
    )
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    async with mission_stack(llm=server.llm()) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert [step["tool"] for step in mission["steps"]] == ["move_robot", "wait_for_arrival"]
    assert mission["final_text"] == "O tb1 chegou à doca de carga."
    assert mission["llm_usage"] == {"turns": 3, "input_tokens": 450, "output_tokens": 36}
    assert (round(pose["x"], 1), round(pose["y"], 1)) == DOCK
    assert [m["role"] for m in server.requests[2]["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]


async def test_deterministic_missions_have_no_llm_usage() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("onde está o tb1?")

    assert mission["llm_usage"] is None


async def test_provider_errors_fail_the_mission_with_a_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeServer(status(500))
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    async with mission_stack(llm=server.llm()) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "failed"
    assert mission["steps"] == []
    text = json.dumps(mission)
    for leaked in ("ollama", "secret", "raw provider", "LlmUnavailable", "500"):
        assert leaked not in text, leaked


VALID_ENV = {
    "FLEET_AI_PLANNER": "llm",
    "FLEET_AI_LLM_ADAPTER": "openai_compat",
    "FLEET_AI_LLM_URL": "http://ollama:11434/v1",
    "FLEET_AI_LLM_MODEL": "qwen2.5:3b",
}


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"FLEET_AI_LLM_URL": None}, "FLEET_AI_LLM_URL is required"),
        ({"FLEET_AI_LLM_URL": "http://user:pw@ollama:11434/v1"}, "credentials"),
        ({"FLEET_AI_LLM_URL": "ftp://ollama/v1"}, "scheme"),
        ({"FLEET_AI_LLM_MODEL": None}, "FLEET_AI_LLM_MODEL is required"),
        ({"FLEET_AI_LLM_MODEL": "qwen 2.5"}, "FLEET_AI_LLM_MODEL"),
        ({"FLEET_AI_LLM_TIMEOUT_S": "-1"}, "FLEET_AI_LLM_TIMEOUT_S"),
        ({"FLEET_AI_LLM_ADAPTER": "anthropic"}, "FLEET_AI_LLM_ADAPTER"),
    ],
    ids=[
        "no_url",
        "url_credentials",
        "url_scheme",
        "no_model",
        "bad_model",
        "timeout",
        "unknown_adapter",
    ],
)
def test_llm_configuration_fails_explicitly(change: dict[str, str | None], match: str) -> None:
    env = {**VALID_ENV, **change}
    with pytest.raises(ValueError, match=match) as raised:
        llm_from_env({k: v for k, v in env.items() if v is not None})
    assert "pw" not in str(raised.value)


def test_llm_configuration_never_reads_api_keys() -> None:
    class Spy(dict[str, str]):
        read: list[str] = []

        def get(self, key: str, default: Any = None) -> Any:
            self.read.append(key)
            return super().get(key, default)

        def __getitem__(self, key: str) -> str:
            self.read.append(key)
            return super().__getitem__(key)

    env = Spy({**VALID_ENV, "OPENAI_API_KEY": "sk-test", "FLEET_AI_LLM_API_KEY": "x"})
    llm = llm_from_env(env)

    assert isinstance(llm, OpenAICompatLlm) and llm.model == "qwen2.5:3b"
    assert not [key for key in env.read if key.endswith("_API_KEY")]


def test_scripted_adapter_builds_no_client() -> None:
    assert llm_from_env({}) is None
    assert llm_from_env({"FLEET_AI_LLM_ADAPTER": "scripted"}) is None


def offline(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("offline", request=request)


def test_health_reports_model_name_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    app = create_app(fleet_transport=httpx2.MockTransport(offline))
    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["planner"] == "llm"
    assert body["llm_enabled"] is True
    assert body["llm_model"] == "qwen2.5:3b"
    assert "ollama" not in json.dumps(body) and "11434" not in json.dumps(body)


def test_health_without_a_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(fleet_transport=httpx2.MockTransport(offline))
    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["llm_enabled"] is False
    assert body["llm_model"] is None
