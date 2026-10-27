"""Toda missão termina (ticket 13; SPEC-001, "Encerramento garantido da missão")."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest

from fleet_ai.adapters import SimAdapter
from fleet_ai.executor import Executor
from fleet_ai.missions import Mission, _execute_mission
from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import SwitchableTransport, mission_stack


def fake_options(**overrides: Any) -> FakeFleetUiOptions:
    """Fake do Fleet UI com o tb1 (MUUT) do warehouse, cujos nomes o planejador conhece."""
    options = FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)], bounds=(-20.0, -30.0, 20.0, 30.0)
    )
    for name, value in overrides.items():
        setattr(options, name, value)
    return options


pytestmark = pytest.mark.anyio

TERMINAL = {"completed", "failed", "incomplete", "not_understood"}


def refuse_connection(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused to http://10.0.0.7:8001", request=request)


async def test_mission_fails_when_the_fleet_backend_is_unreachable() -> None:
    async with mission_stack(transport=httpx2.MockTransport(refuse_connection)) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "failed"
    assert mission["finished_at"] is not None
    assert mission["language"] == "pt"
    assert "backend de frota está indisponível" in mission["final_text"]
    [step] = mission["steps"]
    assert step["tool"] == "get_robot_status"
    assert step["is_error"] is True
    assert step["result"]["error"] == "backend_unavailable"
    # Nada do backend vaza para a missão.
    assert "10.0.0.7" not in str(mission)
    assert "connection refused" not in str(mission)


def answer(status_code: int, **kwargs: Any) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda request: httpx2.Response(status_code, **kwargs))


@pytest.mark.parametrize(
    "transport",
    [
        answer(500, text="<html>Traceback ... /srv/fleet/secret.py</html>"),
        answer(200, text="not json"),
        answer(200, json={"pose": {"x": 0, "y": 0, "yaw": 0}}),
    ],
    ids=["http_500", "not_json", "status_without_robots"],
)
async def test_mission_fails_when_the_backend_answers_garbage(
    transport: httpx2.MockTransport,
) -> None:
    async with mission_stack(transport=transport) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "failed"
    assert mission["finished_at"] is not None
    assert mission["steps"][-1]["result"] == {
        "error": "backend_unavailable",
        "message": "Fleet backend unavailable",
    }
    assert "secret.py" not in str(mission)


async def test_mission_fails_when_the_fleet_ui_service_call_fails() -> None:
    options = fake_options(service_call_times_out=True)
    async with mission_stack(fake_fleet_ui=options) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "failed"
    assert [step["tool"] for step in mission["steps"]] == ["get_robot_status", "move_robot"]
    assert mission["steps"][-1]["result"]["error"] == "backend_unavailable"


@pytest.mark.parametrize(
    ("instruction", "language", "phrase"),
    [
        ("leve o tb1 até a doca de carga", "pt", "O robô pode continuar navegando"),
        ("move tb1 to the loading dock", "en", "The robot may still be navigating"),
    ],
)
async def test_navigation_that_does_not_end_in_time_makes_the_mission_incomplete(
    instruction: str, language: str, phrase: str
) -> None:
    options = fake_options(never_arrives=True)
    async with mission_stack(fake_fleet_ui=options, executor_timeout=0.05) as stack:
        mission = await stack.run_mission(instruction)

    assert mission["status"] == "incomplete"
    assert mission["language"] == language
    assert mission["finished_at"] is not None
    assert [step["tool"] for step in mission["steps"]] == [
        "get_robot_status",
        "move_robot",
        "wait_for_arrival",
    ]
    assert mission["steps"][-1]["is_error"] is True
    assert mission["steps"][-1]["result"]["error"] == "navigation_timeout"
    assert phrase in mission["final_text"]
    assert "chegou" not in mission["final_text"] and "arrived" not in mission["final_text"]
    assert options.cancel_requests == 0  # sem cancelamento automático nesta etapa


class RaisingPlanner:
    """Planejador de teste: um passo real e depois a exceção pedida."""

    name = "test"

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        await dispatcher.call("list_robots", {})
        raise self.error


async def test_unexpected_error_fails_the_mission_without_leaking_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    planner = RaisingPlanner(RuntimeError("segredo interno: token=abc123"))

    with caplog.at_level(logging.WARNING, logger="fleet_ai"):
        async with mission_stack(planner=planner) as stack:
            mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "failed"
    assert mission["finished_at"] is not None
    assert [step["tool"] for step in mission["steps"]] == ["list_robots"]
    assert mission["final_text"] == "A missão falhou por um erro interno."
    assert "segredo" not in str(mission) and "abc123" not in str(mission)
    [ended] = [r for r in caplog.records if r.getMessage().startswith("mission_ended")]
    assert ended.__dict__["mission_id"] == mission["mission_id"]
    assert ended.__dict__["failure"] == "internal_error"
    assert "segredo interno" in ended.__dict__["detail"]  # o diagnóstico fica nos logs


@asynccontextmanager
async def sim_executor() -> AsyncIterator[Executor]:
    transport = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    executor = Executor(SimAdapter("http://fleet", transport=transport), poll_interval=0.0)
    try:
        yield executor
    finally:
        await executor.aclose()


async def test_cancelled_mission_is_failed_and_the_cancellation_propagates() -> None:
    started = asyncio.Event()

    class BlockingPlanner:
        name = "test"

        async def run(
            self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
        ) -> PlanOutcome:
            await dispatcher.call("list_robots", {})
            started.set()
            await asyncio.Event().wait()  # nunca termina sozinho
            raise AssertionError("inalcançável")

    mission = Mission("leve o tb1 até a doca de carga", None, planner="test")
    async with sim_executor() as executor:
        task = asyncio.create_task(_execute_mission(mission, BlockingPlanner(), executor))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert task.cancelled()  # o cancelamento não foi suprimido
    assert mission.status == "failed"
    assert mission.finished_at is not None
    assert [step["tool"] for step in mission.steps] == ["list_robots"]
    assert mission.final_text == "A missão foi interrompida antes de terminar."


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(1)], ids=["ctrl_c", "exit"])
async def test_keyboard_interrupt_and_system_exit_are_not_captured(error: BaseException) -> None:
    mission = Mission("leve o tb1 até a doca de carga", None, planner="test")

    async with sim_executor() as executor:
        with pytest.raises(type(error)):
            await _execute_mission(mission, RaisingPlanner(error), executor)

    # Não houve captura ampla: o processo está saindo, a missão não foi tocada.
    assert mission.status == "running"


async def test_service_keeps_working_after_a_failed_mission() -> None:
    simfleet = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    switch = SwitchableTransport(simfleet)
    async with mission_stack(transport=switch) as stack:
        switch.down = True
        failed = await stack.run_mission("leve o tb1 até a doca de carga")
        switch.down = False
        completed = await stack.run_mission("leve o tb2 até a base")
        health = await stack.api.get("/health")

    assert failed["status"] == "failed"
    assert completed["status"] == "completed"
    assert health.status_code == 200


SCENARIOS: dict[str, tuple[dict[str, Any], str]] = {
    "completed": ({}, "leve o tb1 até a doca de carga"),
    "not_understood": ({}, "faça um café"),
    "unreachable": (
        {"transport": httpx2.MockTransport(refuse_connection)},
        "leve o tb1 até a doca de carga",
    ),
    "http_500": ({"transport": answer(500, text="boom")}, "leve o tb1 até a doca de carga"),
    "fleet_ui_call_fails": (
        {"fake_fleet_ui": fake_options(service_call_times_out=True)},
        "leve o tb1 até a doca de carga",
    ),
    "executor_timeout": (
        {"fake_fleet_ui": fake_options(never_arrives=True), "executor_timeout": 0.05},
        "leve o tb1 até a doca de carga",
    ),
    "unexpected_error": (
        {"planner": RaisingPlanner(ValueError("boom"))},
        "leve o tb1 até a doca de carga",
    ),
}


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_every_mission_reaches_a_terminal_state(scenario: str) -> None:
    options, instruction = SCENARIOS[scenario]

    async with mission_stack(**options) as stack:
        mission = await stack.run_mission(instruction)

    assert mission["status"] in TERMINAL
    assert mission["finished_at"] is not None
