"""Planejador LLM com LLM roteirizado, desligado por padrão (ticket 10; SPEC-001)."""

import asyncio
import json
import math
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from fleet_ai.adapters import SimAdapter
from fleet_ai.app import create_app
from fleet_ai.executor import Executor
from fleet_ai.llm import LlmResponse, ScriptedLlm, TextBlock, ToolUseBlock
from fleet_ai.llm_planner import LlmPlanner
from fleet_ai.missions import Mission, _execute_mission
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot, create_fake_fleet_ui
from tests.fleet_ai_client import Stack, SwitchableTransport, mission_stack

pytestmark = pytest.mark.anyio

DOCK = (2.0, 13.5)  # doca de carga no warehouse


def tool(call_id: str, name: str, **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(call_id, name, tool_input)


def wants(*calls: ToolUseBlock) -> LlmResponse:
    return LlmResponse((*calls,), "tool_use")


def says(text: str) -> LlmResponse:
    return LlmResponse((TextBlock(text),), "end_turn")


@asynccontextmanager
async def llm_stack(
    llm: ScriptedLlm, monkeypatch: pytest.MonkeyPatch, **options: Any
) -> AsyncIterator[Stack]:
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    async with mission_stack(llm=llm, **options) as stack:
        yield stack


async def test_llm_mission_completes_with_four_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedLlm(
        [
            wants(tool("c1", "list_robots")),
            wants(tool("c2", "get_robot_status", robot_id="tb1")),
            wants(tool("c3", "move_robot", robot_id="tb1", x=DOCK[0], y=DOCK[1])),
            wants(tool("c4", "wait_for_arrival", robot_id="tb1")),
            says("O tb1 chegou à doca de carga."),
        ]
    )
    async with llm_stack(llm, monkeypatch) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert mission["planner"] == "llm"
    assert [step["tool"] for step in mission["steps"]] == [
        "list_robots",
        "get_robot_status",
        "move_robot",
        "wait_for_arrival",
    ]
    assert mission["final_text"] == "O tb1 chegou à doca de carga."
    assert mission["language"] == "pt"
    assert math.hypot(pose["x"] - DOCK[0], pose["y"] - DOCK[1]) <= 0.05
    assert len(llm.requests) == 5


def refuse_network(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("offline", request=request)


def offline_app(**options: Any) -> Any:
    return create_app(fleet_transport=httpx2.MockTransport(refuse_network), **options)


def test_default_planner_is_deterministic() -> None:
    app = offline_app(llm=ScriptedLlm([]))
    with TestClient(app) as client:
        assert client.get("/health").json()["planner"] == "deterministic"


@pytest.mark.parametrize(
    ("env", "llm", "match"),
    [
        ({"FLEET_AI_PLANNER": "llm"}, None, "FLEET_AI_PLANNER=llm.*scripted LLM"),
        (
            {"FLEET_AI_PLANNER": "llm", "FLEET_AI_LLM_ADAPTER": "openai"},
            True,
            "FLEET_AI_LLM_ADAPTER",
        ),
        ({"FLEET_AI_LLM_ADAPTER": "anthropic"}, None, "FLEET_AI_LLM_ADAPTER"),
        ({"FLEET_AI_PLANNER": "gpt"}, True, "FLEET_AI_PLANNER.*deterministic.*llm"),
    ],
    ids=["llm_without_injected_llm", "real_adapter", "real_adapter_default_planner", "unknown"],
)
def test_planner_configuration_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], llm: object, match: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=match):
        offline_app(llm=ScriptedLlm([]) if llm else None)


def test_health_reports_llm_planner_without_enabling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    monkeypatch.setenv("FLEET_AI_LLM_ADAPTER", "scripted")
    with TestClient(offline_app(llm=ScriptedLlm([]))) as client:
        body = client.get("/health").json()

    assert body["planner"] == "llm"
    assert body["llm_enabled"] is False


FIVE_TOOLS = [
    "list_robots",
    "get_robot_status",
    "move_robot",
    "wait_for_arrival",
    "cancel_navigation",
]


async def test_llm_receives_system_rules_and_exactly_the_five_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = ScriptedLlm([says("Pronto.")])
    async with llm_stack(llm, monkeypatch) as stack:
        await stack.run_mission("onde está o tb1?", robot_id="tb1")

    request = llm.requests[0]
    assert [spec["name"] for spec in request.tools] == FIVE_TOOLS
    assert all(spec["input_schema"]["type"] == "object" for spec in request.tools)
    for rule in (
        "Nunca invente robôs",
        "confira o estado do robô antes de comandos de movimento",
        "resuma o resultado ao final",
        "aguarde a chegada",
        "idioma da instrução",
        "restrito ao robô 'tb1'",
    ):
        assert rule in request.system
    assert request.messages == [{"role": "user", "content": "onde está o tb1?"}]
    assert request.max_tokens == 1024


def tool_results(llm: ScriptedLlm, turn: int) -> list[dict[str, Any]]:
    """Os `tool_result` que o LLM recebeu no pedido `turn` (a última mensagem)."""
    content: list[dict[str, Any]] = llm.requests[turn].messages[-1]["content"]
    return content


async def test_tool_error_reaches_the_model_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedLlm(
        [
            wants(tool("c1", "move_robot", robot_id="tb3", x=1.0, y=1.0)),
            says("Não consegui mover o tb3."),
        ]
    )
    fleet_ui = FakeFleetUiOptions(robots=[FakeRobot("tb3", "FUUT", 0.0, 0.0)])
    async with llm_stack(llm, monkeypatch, fake_fleet_ui=fleet_ui) as stack:
        mission = await stack.run_mission("mova o tb3 para x 1 y 1")

    [result] = tool_results(llm, 1)
    assert result["tool_use_id"] == "c1"
    assert result["is_error"] is True
    assert json.loads(result["content"]) == {
        "error_code": "ROLE_NOT_ALLOWED",
        "message": "The robot's role does not allow movement.",
    }
    raw = json.dumps(llm.requests[1].messages)
    for leak in ("permite", "roles.yaml", "FUUT", "Traceback"):
        assert leak not in raw
    assert mission["status"] == "completed"


@pytest.mark.parametrize(("configured", "turns"), [(None, 8), ("3", 3)])
async def test_endless_tool_requests_end_incomplete_after_the_turn_limit(
    monkeypatch: pytest.MonkeyPatch, configured: str | None, turns: int
) -> None:
    if configured is not None:
        monkeypatch.setenv("FLEET_AI_LLM_MAX_TURNS", configured)
    llm = ScriptedLlm([wants(tool(f"c{n}", "list_robots")) for n in range(20)])
    async with llm_stack(llm, monkeypatch) as stack:
        mission = await stack.run_mission("quais robôs existem?")

    assert mission["status"] == "incomplete"
    assert len(llm.requests) == turns
    assert [step["tool"] for step in mission["steps"]] == ["list_robots"] * turns
    assert f"limite de {turns} turnos" in mission["final_text"]


class RecordingTransport(httpx2.AsyncBaseTransport):
    """Repassa ao backend de frota e registra cada chamada (método e caminho)."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self.inner = inner
        self.calls: list[str] = []
        self.observe: Callable[[httpx2.Request], Awaitable[None]] | None = None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if self.observe is not None:
            await self.observe(request)
        return await self.inner.handle_async_request(request)


def recording_simfleet() -> RecordingTransport:
    return RecordingTransport(httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0))))


def errors(llm: ScriptedLlm, turn: int) -> list[str]:
    return [
        json.loads(result["content"])["error_code"]
        for result in tool_results(llm, turn)
        if result["is_error"]
    ]


async def test_multiple_tool_calls_in_one_response_run_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = ScriptedLlm(
        [
            wants(
                tool("a", "get_robot_status", robot_id="tb1"),
                tool("b", "get_robot_status", robot_id="tb2"),
                tool("c", "get_robot_status", robot_id="tb3"),
            ),
            says("Estados lidos."),
        ]
    )
    async with llm_stack(llm, monkeypatch) as stack:
        mission = await stack.run_mission("qual o estado dos robôs?")

    assert [step["input"]["robot_id"] for step in mission["steps"]] == ["tb1", "tb2", "tb3"]
    assert [r["tool_use_id"] for r in tool_results(llm, 1)] == ["a", "b", "c"]
    assert mission["status"] == "completed"


@pytest.mark.parametrize(("configured", "limit"), [(None, 4), ("2", 2)])
async def test_tool_calls_beyond_the_turn_limit_never_reach_the_dispatcher(
    monkeypatch: pytest.MonkeyPatch, configured: str | None, limit: int
) -> None:
    if configured is not None:
        monkeypatch.setenv("FLEET_AI_LLM_MAX_TOOL_CALLS_PER_TURN", configured)
    backend = recording_simfleet()
    llm = ScriptedLlm([wants(*[tool(f"c{n}", "list_robots") for n in range(6)]), says("Listei.")])
    async with llm_stack(llm, monkeypatch, transport=backend) as stack:
        mission = await stack.run_mission("quais robôs existem?")

    assert len(mission["steps"]) == limit
    assert backend.calls == ["GET /api/list_robots"] * limit
    assert len(tool_results(llm, 1)) == 6  # todo tool_use recebe resposta
    assert errors(llm, 1) == ["TOO_MANY_TOOL_CALLS"] * (6 - limit)


async def test_refused_calls_count_toward_the_turn_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet_ui = FakeFleetUiOptions(robots=[FakeRobot("tb3", "FUUT", 0.0, 0.0)])
    backend = RecordingTransport(httpx2.ASGITransport(app=create_fake_fleet_ui(fleet_ui)))
    llm = ScriptedLlm(
        [
            wants(*[tool(f"c{n}", "move_robot", robot_id="tb3", x=1.0, y=1.0) for n in range(6)]),
            says("Não foi possível."),
        ]
    )
    async with llm_stack(llm, monkeypatch, transport=backend, fake_fleet_ui=fleet_ui) as stack:
        mission = await stack.run_mission("mova o tb3 para x 1 y 1")

    assert len(mission["steps"]) == 4
    assert backend.calls == ["POST /api/go_to_point"] * 4
    assert errors(llm, 1) == ["ROLE_NOT_ALLOWED"] * 4 + ["TOO_MANY_TOOL_CALLS"] * 2


INVALID_CALLS = [
    (ToolUseBlock("u", "delete_robot", {"robot_id": "tb1"}), "UNKNOWN_TOOL"),
    (tool("m1", "move_robot", robot_id="tb1", x="2", y=1.0), "INVALID_INPUT"),
    (tool("m2", "move_robot", robot_id="tb1", x=True, y=1.0), "INVALID_INPUT"),
    (tool("m3", "move_robot", robot_id="tb1", x=float("nan"), y=1.0), "INVALID_INPUT"),
    (tool("m4", "move_robot", x=1.0, y=1.0), "INVALID_INPUT"),
    (tool("s1", "get_robot_status", robot_id=""), "INVALID_INPUT"),
    (tool("s2", "get_robot_status", robot_id=7), "INVALID_INPUT"),
    (tool("l1", "list_robots", url="http://elsewhere"), "INVALID_INPUT"),
    (tool("w1", "wait_for_arrival", robot_id="tb1", timeout=999), "INVALID_INPUT"),
]


async def test_repeated_invalid_tool_calls_never_reach_the_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = recording_simfleet()
    calls = [call for call, _ in INVALID_CALLS]
    llm = ScriptedLlm([wants(*calls) for _ in range(8)])
    async with llm_stack(llm, monkeypatch, transport=backend) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert backend.calls == []
    assert mission["steps"] == []
    assert mission["status"] == "incomplete"
    for turn in range(1, 8):
        assert errors(llm, turn) == [code for _, code in INVALID_CALLS]


async def test_invalid_calls_do_not_use_the_turn_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = recording_simfleet()
    calls = [call for call, _ in INVALID_CALLS]
    llm = ScriptedLlm([wants(*calls, tool("ok", "list_robots")), says("Listei.")])
    async with llm_stack(llm, monkeypatch, transport=backend) as stack:
        mission = await stack.run_mission("quais robôs existem?")

    assert backend.calls == ["GET /api/list_robots"]
    assert [step["tool"] for step in mission["steps"]] == ["list_robots"]


class BrokenLlm:
    """LLM cuja chamada falha com uma exceção interna."""

    async def complete(self, **_: Any) -> LlmResponse:
        raise RuntimeError("internal secret: sk-not-a-key at /srv/llm")


def never_arrives() -> FakeFleetUiOptions:
    return FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)],
        bounds=(-20.0, -30.0, 20.0, 30.0),
        never_arrives=True,
    )


MOVE_AND_WAIT = [
    wants(tool("m", "move_robot", robot_id="tb1", x=1.0, y=1.0)),
    wants(tool("w", "wait_for_arrival", robot_id="tb1")),
    says("Chegou."),
]

TERMINAL_CASES: dict[str, tuple[Any, dict[str, Any], str]] = {
    "backend_down": (ScriptedLlm([wants(tool("l", "list_robots"))]), {"down": True}, "failed"),
    "executor_timeout": (
        ScriptedLlm(MOVE_AND_WAIT),
        {"fake_fleet_ui": never_arrives(), "executor_timeout": 0.05},
        "incomplete",
    ),
    "llm_exception": (BrokenLlm(), {}, "failed"),
    "script_exhausted": (ScriptedLlm([]), {}, "failed"),
    "tool_use_without_blocks": (
        ScriptedLlm([LlmResponse((TextBlock("vou usar"),), "tool_use"), says("ok")]),
        {},
        "failed",
    ),
    "duplicate_tool_ids": (
        ScriptedLlm([wants(tool("x", "list_robots"), tool("x", "list_robots")), says("ok")]),
        {},
        "failed",
    ),
    "unknown_stop_reason": (
        ScriptedLlm([LlmResponse((TextBlock("..."),), "pause_turn")]),
        {},
        "failed",
    ),
    "max_tokens": (
        ScriptedLlm([LlmResponse((TextBlock("O tb1 est"),), "max_tokens")]),
        {},
        "incomplete",
    ),
}


@pytest.mark.parametrize("case", TERMINAL_CASES)
async def test_llm_mission_terminal_outcomes(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    llm, options, status = TERMINAL_CASES[case]
    down = options.pop("down", False)
    options = dict(options)
    fake = options.get("fake_fleet_ui")
    inner = (
        httpx2.ASGITransport(app=create_fake_fleet_ui(fake))
        if fake is not None
        else httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    )
    backend = RecordingTransport(SwitchableTransport(inner))
    backend.inner.down = down  # type: ignore[attr-defined]
    async with llm_stack(llm, monkeypatch, transport=backend, **options) as stack:
        mission = await stack.run_mission("leve o tb1 até x 1 y 1")

    assert mission["status"] == status
    assert "POST /api/cancel" not in backend.calls  # nunca cancela por conta própria
    for leak in ("secret", "sk-", "/srv", "RuntimeError", "ScriptExhausted", "Traceback"):
        assert leak not in json.dumps(mission)


@pytest.mark.parametrize("ending", ["final_answer", "turn_limit", "max_tokens"])
async def test_final_answer_while_navigating_ends_incomplete_without_cancel(
    monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    monkeypatch.setenv("FLEET_AI_LLM_MAX_TURNS", "2")
    move = wants(tool("m", "move_robot", robot_id="tb1", x=DOCK[0], y=DOCK[1]))
    last = {
        "final_answer": says("O tb1 chegou à doca de carga."),
        "turn_limit": wants(tool("s", "get_robot_status", robot_id="tb1")),
        "max_tokens": LlmResponse((TextBlock("O tb1 cheg"),), "max_tokens"),
    }[ending]
    backend = recording_simfleet()
    llm = ScriptedLlm([move, last])
    async with llm_stack(llm, monkeypatch, transport=backend) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "incomplete"
    assert "pode continuar navegando" in mission["final_text"]
    assert "não houve cancelamento confirmado" in mission["final_text"]
    assert "POST /api/cancel" not in backend.calls


async def test_final_answer_after_arrival_is_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ScriptedLlm(MOVE_AND_WAIT)
    async with llm_stack(llm, monkeypatch) as stack:
        mission = await stack.run_mission("leve o tb1 até x 1 y 1")

    assert mission["status"] == "completed"
    assert "pode continuar" not in mission["final_text"]


class BlockingLlm:
    """LLM que responde uma vez e depois nunca mais responde."""

    def __init__(self, first: LlmResponse) -> None:
        self.first: LlmResponse | None = first
        self.waiting = asyncio.Event()

    async def complete(self, **_: Any) -> LlmResponse:
        if self.first is not None:
            first, self.first = self.first, None
            return first
        self.waiting.set()
        await asyncio.Event().wait()
        raise AssertionError("inalcançável")


async def test_llm_mission_cancelled_error_propagates() -> None:
    llm = BlockingLlm(wants(tool("l", "list_robots")))
    mission = Mission("quais robôs existem?", None, planner="llm")
    adapter = SimAdapter(
        "http://fleet",
        transport=httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0))),
    )
    executor = Executor(adapter, poll_interval=0.0)
    try:
        task = asyncio.create_task(_execute_mission(mission, LlmPlanner(llm), executor))
        await asyncio.wait_for(llm.waiting.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await executor.aclose()

    assert task.cancelled()
    assert mission.status == "failed"
    assert [step["tool"] for step in mission.steps] == ["list_robots"]


async def test_llm_mission_time_limit_cancels_the_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = RecordingTransport(httpx2.ASGITransport(app=create_fake_fleet_ui(never_arrives())))
    llm = ScriptedLlm(MOVE_AND_WAIT)
    async with llm_stack(
        llm, monkeypatch, transport=backend, fake_fleet_ui=never_arrives(), mission_timeout=0.2
    ) as stack:
        mission = await asyncio.wait_for(stack.run_mission("leve o tb1 até x 1 y 1"), 5)

    assert mission["status"] == "incomplete"
    assert "tempo máximo" in mission["final_text"]
    assert "POST /api/cancel" in backend.calls
    assert mission["steps"][-1]["tool"] == "cancel_navigation"


async def test_scope_conflict_is_refused_before_any_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for planner in ("deterministic", "llm"):
        monkeypatch.setenv("FLEET_AI_PLANNER", planner)
        backend = recording_simfleet()
        llm = ScriptedLlm([wants(tool("m", "move_robot", robot_id="tb2", x=1.0, y=1.0))])
        async with mission_stack(llm=llm, transport=backend) as stack:
            mission = await stack.run_mission("leve o tb2 até a doca de carga", robot_id="tb1")

        assert mission["status"] == "not_understood", planner
        assert mission["planner"] == planner
        assert "tb2" in mission["final_text"] and "tb1" in mission["final_text"]
        assert llm.requests == []
        assert backend.calls == []
        assert mission["steps"] == []


async def test_llm_tool_calls_are_rewritten_to_the_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = recording_simfleet()
    seen: list[str] = []

    async def spy(request: httpx2.Request) -> None:
        if request.method == "POST":
            seen.append(request.url.params["robot_id"])

    llm = ScriptedLlm(
        [
            wants(tool("m", "move_robot", robot_id="tb2", x=1.0, y=1.0)),
            wants(tool("w", "wait_for_arrival", robot_id="tb2")),
            says("Pronto."),
        ]
    )
    backend.observe = spy
    async with llm_stack(llm, monkeypatch, transport=backend) as stack:
        mission = await stack.run_mission("leve até x 1 y 1", robot_id="tb1")

    assert [step["input"]["robot_id"] for step in mission["steps"]] == ["tb1", "tb1"]
    assert seen == ["tb1"]
    assert mission["status"] == "completed"


class RecordingEnviron(dict[str, str]):
    """Ambiente que registra cada variável consultada."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.read: set[str] = set()

    def get(self, key: str, default: Any = None) -> Any:
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self.read.add(str(key))
        return super().__contains__(key)


async def test_llm_mission_makes_no_network_calls_besides_the_fleet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ = RecordingEnviron({**os.environ, "FLEET_AI_PLANNER": "llm"})
    monkeypatch.setattr(os, "environ", environ)
    backend = recording_simfleet()
    llm = ScriptedLlm(
        [
            wants(tool("l", "list_robots")),
            wants(tool("m", "move_robot", robot_id="tb1", x=1.0, y=1.0)),
            wants(tool("w", "wait_for_arrival", robot_id="tb1")),
            says("Pronto."),
        ]
    )
    async with mission_stack(llm=llm, transport=backend) as stack:
        mission = await stack.run_mission("leve o tb1 até x 1 y 1")

    assert mission["status"] == "completed"
    assert backend.calls and all(" /api/" in call for call in backend.calls)
    credentials = ("_API_KEY", "_AUTH_TOKEN", "_ACCESS_TOKEN", "_SECRET")
    assert [name for name in environ.read if name.endswith(credentials)] == []
    assert {"anthropic", "openai"} & set(sys.modules) == set()


async def test_status_sent_to_the_model_carries_no_raw_backend_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "Traceback: /opt/ros/humble secret"
    robot = FakeRobot("tb1", "MUUT", 0.0, 0.0)
    robot.nav_state, robot.last_error = "failed", raw
    llm = ScriptedLlm([wants(tool("s", "get_robot_status", robot_id="tb1")), says("Falhou.")])
    fleet_ui = FakeFleetUiOptions(robots=[robot])
    async with llm_stack(llm, monkeypatch, fake_fleet_ui=fleet_ui) as stack:
        await stack.run_mission("onde está o tb1?")

    [result] = tool_results(llm, 1)
    status = json.loads(result["content"])
    assert status["nav_state"] == "failed"
    assert status["last_error"] == "NAV_ERROR"
    assert "Traceback" not in json.dumps(llm.requests[1].messages)
