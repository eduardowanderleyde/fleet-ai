"""Respostas públicas sem texto bruto do backend, do LLM ou de exceções (ticket 15)."""

import json
import logging
import unicodedata
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from fleet_ai.llm import LlmResponse, ScriptedLlm, TextBlock, ToolUseBlock
from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot, create_fake_fleet_ui
from tests.fleet_ai_client import Stack, mission_stack

pytestmark = pytest.mark.anyio

# Textos sensíveis fictícios (ticket 15): nenhum deles pode aparecer numa resposta.
LEAKS = (
    "http://10.0.0.5:8000/internal",
    "postgres://admin:s3cret@db:5432",
    "Authorization: Bearer sk-test-FAKE",
    'Traceback (most recent call last): File "/opt/ros/humble/lib/x.py"',
    "RuntimeError: unexpected",
)
ROLE_MESSAGE = "The robot's role does not allow movement."

Rewrite = Callable[[httpx2.Request, int, Any], tuple[int, Any] | None]


class Rewriting(httpx2.AsyncBaseTransport):
    """Repassa ao backend e deixa o teste trocar o corpo JSON da resposta."""

    def __init__(self, inner: httpx2.AsyncBaseTransport, rewrite: Rewrite) -> None:
        self.inner = inner
        self.rewrite = rewrite

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self.inner.handle_async_request(request)
        content = await response.aread()
        try:
            data = json.loads(content)
        except ValueError:
            return httpx2.Response(response.status_code, content=content)
        changed = self.rewrite(request, response.status_code, data)
        status, body = changed if changed is not None else (response.status_code, data)
        return httpx2.Response(status, json=body)


def fleet_ui_options(**overrides: Any) -> FakeFleetUiOptions:
    robots = [FakeRobot("tb1", "MUUT", 0.0, 0.0), FakeRobot("tb3", "FUUT", 1.0, 1.0)]
    return FakeFleetUiOptions(robots=robots, **overrides)


def poisoned_stack(adapter: str, rewrite: Rewrite, **options: Any) -> Any:
    """Fleet AI com o backend `adapter` (sim ou fleet_ui) respondendo pelo `rewrite`."""
    fake = options.pop("fake_fleet_ui", None)
    if adapter == "fleet_ui":
        fake = fake or fleet_ui_options()
        inner: httpx2.AsyncBaseTransport = httpx2.ASGITransport(app=create_fake_fleet_ui(fake))
        return mission_stack(transport=Rewriting(inner, rewrite), fake_fleet_ui=fake, **options)
    inner = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    return mission_stack(transport=Rewriting(inner, rewrite), **options)


def append_to_messages(leak: str) -> Rewrite:
    """Acrescenta o texto sensível ao `message` de toda resposta de comando."""

    def rewrite(_: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return status, {**data, "message": f"{data['message']} {leak}"}
        return None

    return rewrite


def poison_status(**fields: str) -> Rewrite:
    """Troca campos de todos os robôs de `/api/status` (só quando já têm valor, se `when_set`)."""

    def rewrite(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        if request.url.path != "/api/status":
            return None
        robots = [{**robot, **fields} for robot in data["robots"]]
        return status, {**data, "robots": robots}

    return rewrite


def tool(call_id: str, name: str, **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(call_id, name, tool_input)


def wants(*calls: ToolUseBlock) -> LlmResponse:
    return LlmResponse((*calls,), "tool_use")


def says(text: str) -> LlmResponse:
    return LlmResponse((TextBlock(text),), "end_turn")


def assert_no_leak(*bodies: Any) -> None:
    text = json.dumps(bodies, ensure_ascii=False)
    for leak in LEAKS:
        assert leak not in text, leak
    for fragment in ("10.0.0.5", "s3cret", "sk-test-FAKE", "Traceback", "/opt/ros"):
        assert fragment not in text, fragment


@pytest.mark.parametrize("planner", ["deterministic", "llm"])
@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
@pytest.mark.parametrize("leak", LEAKS)
async def test_refusal_message_is_replaced_by_a_fleet_ai_message(
    monkeypatch: pytest.MonkeyPatch, leak: str, adapter: str, planner: str
) -> None:
    llm = None
    if planner == "llm":
        monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
        llm = ScriptedLlm(
            [wants(tool("m", "move_robot", robot_id="tb3", x=1.0, y=2.0)), says("Recusado.")]
        )
    async with poisoned_stack(adapter, append_to_messages(leak), llm=llm) as stack:
        mission = await stack.run_mission("mova o tb3 para x 1 y 2")

    [refusal] = [step for step in mission["steps"] if step["is_error"]]
    assert refusal["tool"] == "move_robot"
    assert refusal["result"] == {"error_code": "ROLE_NOT_ALLOWED", "message": ROLE_MESSAGE}
    assert_no_leak(mission)
    if llm is not None:
        assert_no_leak(llm.requests[1].messages)


@pytest.mark.parametrize("leak", LEAKS)
async def test_refused_cancel_after_the_time_limit_is_sanitized(leak: str) -> None:
    def refuse_cancel(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        if request.url.path != "/api/cancel":
            return None
        repr_ = f"Cancel_Response(success=False, message='{leak}', error_code='CANCEL_FAILED')"
        return 200, {"success": True, "message": f"requester: ...\nresponse:\n{repr_}"}

    fake = fleet_ui_options(never_arrives=True)
    async with poisoned_stack(
        "fleet_ui",
        refuse_cancel,
        fake_fleet_ui=fake,
        executor_timeout=30.0,
        mission_timeout=0.2,
        cancel_grace=0.5,
    ) as stack:
        mission = await stack.run_mission("mova o tb1 para x 1 y 1")

    assert mission["status"] == "incomplete"
    cancel = mission["steps"][-1]
    assert cancel["tool"] == "cancel_navigation"
    assert cancel["is_error"] is True
    assert cancel["result"]["error_code"] == "CANCEL_FAILED"
    assert_no_leak(mission)


@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
async def test_status_fields_outside_the_contract_are_sanitized(adapter: str) -> None:
    rewrite = poison_status(last_error=LEAKS[1], role=LEAKS[2])
    async with poisoned_stack(adapter, rewrite) as stack:
        mission = await stack.run_mission("qual o status do tb1?")

    [status] = mission["steps"]
    assert status["tool"] == "get_robot_status"
    assert status["result"]["last_error"] == "NAV_ERROR"
    assert status["result"]["role"] == "UNKNOWN"
    assert status["result"]["nav_state"] == "idle"
    assert status["result"]["robot_id"] == "tb1"
    assert_no_leak(mission)


TOO_MANY = [f"r{i}" for i in range(101)]


@pytest.mark.parametrize(
    "robot_ids", [*(["tb1", bad] for bad in (*LEAKS, "", "tb1 ", "x" * 65)), TOO_MANY]
)
async def test_robot_ids_outside_the_contract_are_a_backend_error(robot_ids: list[str]) -> None:
    def rewrite(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        if request.url.path != "/api/list_robots":
            return None
        return status, {"robot_ids": robot_ids}

    async with poisoned_stack("sim", rewrite) as stack:
        mission = await stack.run_mission("liste os robôs")

    assert mission["status"] == "failed"
    assert mission["steps"][0]["result"]["error"] == "backend_unavailable"
    assert_no_leak(mission)


async def test_valid_robot_ids_are_listed_unchanged() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("liste os robôs")

    assert mission["steps"][0]["result"] == {"robot_ids": ["tb1", "tb2", "tb3"]}


@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
async def test_unreached_destination_text_uses_only_contract_codes(adapter: str) -> None:
    def rewrite(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        if request.url.path != "/api/status":
            return None
        robots = [
            {**robot, "last_error": LEAKS[3]} if robot["last_error"] else robot
            for robot in data["robots"]
        ]
        return status, {**data, "robots": robots}

    # Dentro da estante central do warehouse; fora dos limites do fake do Fleet UI.
    instruction = "mova o tb1 para x -2 y -10" if adapter == "sim" else "mova o tb1 para x 9 y 9"
    async with poisoned_stack(adapter, rewrite) as stack:
        mission = await stack.run_mission(instruction)

    assert mission["steps"][-1]["result"]["nav_state"] == "failed"
    assert "(NAV_ERROR)" in mission["final_text"]
    assert_no_leak(mission)


async def test_llm_final_text_is_bounded_and_has_no_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    text = "Linha 1\nLinha 2\r\t\x1b[31mvermelho\x00‮" + "a" * 5000
    async with mission_stack(llm=ScriptedLlm([says(text)])) as stack:
        mission = await stack.run_mission("liste os robôs")

    final = mission["final_text"]
    assert mission["status"] == "completed"
    assert len(final) <= 2000
    assert final.startswith("Linha 1\nLinha 2")
    assert "vermelho" in final
    controls = [c for c in final if c != "\n" and unicodedata.category(c) in {"Cc", "Cf"}]
    assert controls == []


@pytest.mark.parametrize("bad_id", ["tb1/../x", "tb 1", "x" * 65, LEAKS[0], LEAKS[2]])
async def test_llm_robot_id_argument_outside_the_pattern_is_invalid_input(
    monkeypatch: pytest.MonkeyPatch, bad_id: str
) -> None:
    monkeypatch.setenv("FLEET_AI_PLANNER", "llm")
    llm = ScriptedLlm([wants(tool("s", "get_robot_status", robot_id=bad_id)), says("Ok.")])
    async with mission_stack(llm=llm) as stack:
        mission = await stack.run_mission("qual o status?")

    [result] = llm.requests[1].messages[-1]["content"]
    assert result["is_error"] is True
    assert json.loads(result["content"])["error_code"] == "INVALID_INPUT"
    assert mission["steps"] == []  # nunca chegou ao despachante
    assert_no_leak(mission)


class RaisingPlanner:
    name = "deterministic"

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        raise RuntimeError(f"unexpected {LEAKS[1]}")


def explode(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
    raise RuntimeError(f"adapter exploded {LEAKS[1]} {LEAKS[3]}")


async def failing_client(stack: Stack) -> httpx2.AsyncClient:
    # Um cliente que recebe o 500 em vez de relançar a exceção da aplicação.
    transport = httpx2.ASGITransport(
        app=stack.app, client=("127.0.0.1", 50000), raise_app_exceptions=False
    )
    return httpx2.AsyncClient(base_url="http://fleet-ai", transport=transport)


async def test_unexpected_errors_never_reach_public_responses() -> None:
    generic = "A missão falhou por um erro interno."
    async with mission_stack(planner=RaisingPlanner()) as stack:
        from_planner = await stack.run_mission("liste os robôs")
    async with poisoned_stack("sim", explode) as stack:
        from_adapter = await stack.run_mission("liste os robôs")
        async with await failing_client(stack) as client:
            endpoint = await client.get("/v1/fleet")

    for mission in (from_planner, from_adapter):
        assert mission["status"] == "failed"
        assert mission["final_text"] == generic
    assert endpoint.status_code == 500
    assert endpoint.json() == {"error": "internal_error", "message": "Internal error"}
    assert_no_leak(from_planner, from_adapter, endpoint.text)


async def test_unknown_mission_does_not_echo_the_path() -> None:
    probe = "<script>alert(1)"
    async with mission_stack() as stack:
        mission = await stack.api.get(f"/v1/missions/{probe}")
        no_route = await stack.api.get("/v1/<b>nothing</b>/here")
        wrong_method = await stack.api.delete("/v1/missions")

    assert mission.status_code == 404
    assert mission.json() == {"error": "not_found", "message": "Mission not found"}
    assert no_route.status_code == 404
    assert no_route.json() == {"error": "not_found", "message": "Not found"}
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {"error": "method_not_allowed", "message": "Method not allowed"}
    for response in (mission, no_route, wrong_method):
        assert "script" not in response.text and "<b>" not in response.text


async def test_no_sensitive_text_in_any_public_response(monkeypatch: pytest.MonkeyPatch) -> None:
    leak = " ".join(LEAKS)

    def rewrite(request: httpx2.Request, status: int, data: Any) -> tuple[int, Any] | None:
        changed = append_to_messages(leak)(request, status, data)
        if changed is not None:
            return changed
        return poison_status(last_error=leak, role=leak)(request, status, data)

    bodies: list[Any] = []
    async with poisoned_stack("sim", rewrite) as stack:
        for instruction in (
            "mova o tb3 para x 1 y 2",
            "qual o status do tb1?",
            "liste os robôs",
            "leve o tb1 até a doca de carga",
            "cancele a navegação do tb2",
        ):
            created = await stack.api.post("/v1/missions", json={"instruction": instruction})
            bodies.append(created.json())
            mission = await stack.run_mission(instruction)
            bodies.append(mission)
            bodies.append((await stack.api.get(f"/v1/missions/{mission['mission_id']}")).json())
        for path in ("/v1/missions", "/health", "/health/live", "/v1/fleet", "/v1/map"):
            bodies.append((await stack.api.get(path)).text)

    assert_no_leak(*bodies)


async def test_backend_detail_still_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="fleet_ai"):
        async with poisoned_stack("sim", append_to_messages(LEAKS[2])) as stack:
            mission = await stack.run_mission("mova o tb3 para x 1 y 2")

    assert_no_leak(mission)
    refusals = [r for r in caplog.records if r.getMessage().startswith("fleet_refusal")]
    assert refusals, "a recusa do backend precisa ficar nos logs"
    assert LEAKS[2] in refusals[0].__dict__["detail"]
    assert refusals[0].__dict__["error_code"] == "ROLE_NOT_ALLOWED"
