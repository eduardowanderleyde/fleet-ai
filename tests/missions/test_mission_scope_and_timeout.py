"""Escopo de robô e tempo máximo da missão (ticket 08)."""

import asyncio
import math
import time
from typing import Any

import pytest

from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio


async def test_scoped_mission_moves_only_the_scoped_robot() -> None:
    async with mission_stack() as stack:
        # Citar outro robô é conflito de escopo (ticket 09); aqui a instrução cita o tb1.
        mission = await stack.run_mission("leve o tb1 até a doca de carga", robot_id="tb1")
        poses = (await stack.fleet.get("/api/status")).json()["poses"]

    assert mission["status"] == "completed"
    assert mission["robot_id"] == "tb1"
    move = next(step for step in mission["steps"] if step["tool"] == "move_robot")
    assert move["input"]["robot_id"] == "tb1"
    assert all(step["input"].get("robot_id") == "tb1" for step in mission["steps"])
    # Doca de carga do warehouse em (2,0; 13,5); o tb2 continua na pose inicial (0, 2).
    assert math.hypot(poses["tb1"]["x"] - 2.0, poses["tb1"]["y"] - 13.5) <= 0.05
    assert (poses["tb2"]["x"], poses["tb2"]["y"]) == (0.0, 2.0)
    assert "restrita ao tb1" in mission["final_text"]


async def test_list_robots_in_a_scoped_mission_lists_the_whole_fleet() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("liste os robôs", robot_id="tb1")

    assert mission["status"] == "completed"
    assert mission["steps"][0]["tool"] == "list_robots"
    assert mission["steps"][0]["result"] == {"robot_ids": ["tb1", "tb2", "tb3"]}


class AnyRobotPlanner:
    """Planejador de teste que ignora o escopo e pede outros robôs ao despachante."""

    name = "test"

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        await dispatcher.call("get_robot_status", {"robot_id": "tb3"})
        await dispatcher.call("move_robot", {"robot_id": "tb2", "x": 1.0, "y": 1.0, "yaw": 0.0})
        await dispatcher.call("wait_for_arrival", {"robot_id": "tb2"})
        return PlanOutcome("completed", "en", "done")


async def test_scope_is_enforced_by_the_dispatcher_for_any_planner() -> None:
    async with mission_stack(planner=AnyRobotPlanner()) as stack:
        mission = await stack.run_mission("anything", robot_id="tb1")
        poses = (await stack.fleet.get("/api/status")).json()["poses"]

    assert [step["input"]["robot_id"] for step in mission["steps"]] == ["tb1"] * 3
    assert math.hypot(poses["tb1"]["x"] - 1.0, poses["tb1"]["y"] - 1.0) <= 0.05
    assert (poses["tb2"]["x"], poses["tb2"]["y"]) == (0.0, 2.0)


def fleet_ui(**overrides: Any) -> FakeFleetUiOptions:
    options = FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)],
        bounds=(-20.0, -30.0, 20.0, 30.0),
        never_arrives=True,
    )
    for name, value in overrides.items():
        setattr(options, name, value)
    return options


TIMEOUT_CASES = {
    "confirmed": ({}, "A navegação do tb1 foi cancelada"),
    "ambiguous": ({"abort_after_cancel": True}, "não é possível afirmar que foi pelo cancelamento"),
    "not_confirmed": ({"cancel_has_no_effect": True}, "continua navegando"),
}


@pytest.mark.parametrize("outcome", TIMEOUT_CASES)
async def test_mission_timeout_cancels_navigation_and_reports_the_outcome(outcome: str) -> None:
    overrides, phrase = TIMEOUT_CASES[outcome]
    options = fleet_ui(**overrides)

    async with mission_stack(
        fake_fleet_ui=options, executor_timeout=30.0, mission_timeout=0.2, cancel_grace=0.1
    ) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "incomplete"
    assert mission["finished_at"] is not None
    assert "tempo máximo" in mission["final_text"]
    assert phrase in mission["final_text"]
    assert mission["steps"][-1]["tool"] == "cancel_navigation"
    assert mission["steps"][-1]["input"] == {"robot_id": "tb1"}
    assert mission["steps"][-1]["result"] == {"outcome": outcome}
    assert options.cancel_requests == 1
    if outcome != "confirmed":
        assert "foi cancelada" not in mission["final_text"]


async def test_executor_wait_respects_the_remaining_mission_time() -> None:
    options = fleet_ui()
    started = time.monotonic()

    async with mission_stack(
        fake_fleet_ui=options, executor_timeout=3.0, mission_timeout=0.2, cancel_grace=0.1
    ) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    elapsed = time.monotonic() - started
    assert elapsed < 1.5  # terminou pelo tempo da missão, não pelos 3 s do Executor
    assert mission["status"] == "incomplete"
    assert "tempo máximo de 0,2 s" in mission["final_text"]
    assert options.cancel_requests == 1


class SlowPlanner:
    """Planejador de teste que estoura o tempo sem mandar nenhum robô se mover."""

    name = "test"

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        await dispatcher.call("list_robots", {})
        await asyncio.sleep(30)
        return PlanOutcome("completed", "pt", "inalcançável")


async def test_mission_timeout_without_navigation_sends_no_cancel() -> None:
    options = fleet_ui()

    async with mission_stack(
        fake_fleet_ui=options, planner=SlowPlanner(), mission_timeout=0.2
    ) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "incomplete"
    assert [step["tool"] for step in mission["steps"]] == ["list_robots"]
    assert "Nenhuma navegação estava em curso" in mission["final_text"]
    assert options.cancel_requests == 0


async def test_mission_timeout_with_a_failed_cancel_warns_the_robot_may_keep_moving() -> None:
    options = fleet_ui(cancel_service_fails=True)

    async with mission_stack(fake_fleet_ui=options, mission_timeout=0.2, cancel_grace=0.1) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert mission["status"] == "incomplete"
    assert mission["steps"][-1]["tool"] == "cancel_navigation"
    assert mission["steps"][-1]["result"]["error"] == "backend_unavailable"
    assert "pode continuar navegando" in mission["final_text"]
    assert "recusado" not in mission["final_text"]


async def test_cancel_after_the_time_limit_is_bounded_by_the_cancel_grace() -> None:
    options = fleet_ui(cancel_delay=3.0)  # o backend demora 3 s para responder ao cancel
    started = time.monotonic()

    async with mission_stack(fake_fleet_ui=options, mission_timeout=0.2, cancel_grace=0.2) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")

    assert time.monotonic() - started < 2.0
    assert mission["status"] == "incomplete"
    assert mission["steps"][-1] == {
        "tool": "cancel_navigation",
        "input": {"robot_id": "tb1"},
        "result": {"outcome": "not_confirmed"},
        "is_error": False,
    }
    assert "continua navegando" in mission["final_text"]
