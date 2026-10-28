"""Conflito de escopo, recusado antes de qualquer planejador (tickets 09 e 10; SPEC-001)."""

import math

import pytest

from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

START = {"tb1": (0.0, 0.0), "tb2": (0.0, 2.0), "tb3": (0.0, 4.0)}


async def poses_unchanged(stack: object) -> bool:
    status = (await stack.fleet.get("/api/status")).json()  # type: ignore[attr-defined]
    return all((p["x"], p["y"]) == START[robot] for robot, p in status["poses"].items())


@pytest.mark.parametrize(
    "instruction", ["leve o tb1 até a doca de carga", "leve o robô 1 até a doca de carga"]
)
async def test_instruction_naming_the_scoped_robot_runs_normally(instruction: str) -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission(instruction, robot_id="tb1")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert math.hypot(pose["x"] - 2.0, pose["y"] - 13.5) <= 0.05


@pytest.mark.parametrize(
    ("instruction", "named"),
    [
        ("leve o tb2 até a doca de carga", "tb2"),
        ("leve o robô 2 até a doca de carga", "tb2"),
        ("onde está o tb2?", "tb2"),
        ("pare o tb3", "tb3"),
    ],
)
async def test_instruction_naming_another_robot_conflicts_with_the_scope(
    instruction: str, named: str
) -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission(instruction, robot_id="tb1")
        unchanged = await poses_unchanged(stack)

    assert mission["status"] == "not_understood"
    assert mission["steps"] == []
    assert named in mission["final_text"] and "tb1" in mission["final_text"]
    assert "restrita" in mission["final_text"]
    assert unchanged


async def test_instruction_naming_an_unknown_robot_conflicts_with_the_scope() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("leve o tb9 até a doca de carga", robot_id="tb1")
        unchanged = await poses_unchanged(stack)

    assert mission["status"] == "not_understood"
    assert mission["steps"] == []
    assert "tb9" in mission["final_text"] and "tb1" in mission["final_text"]
    assert unchanged


async def test_instruction_without_a_robot_uses_the_scoped_robot() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("leve até a doca de carga", robot_id="tb1")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert [step["input"].get("robot_id") for step in mission["steps"]] == ["tb1"] * 3
    assert math.hypot(pose["x"] - 2.0, pose["y"] - 13.5) <= 0.05


class SpyPlanner:
    """Planejador de teste: registra as chamadas e não executa nada."""

    name = "spy"

    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        self.calls += 1
        return PlanOutcome("completed", "pt", "executado")


async def test_scope_conflict_is_refused_before_the_planner_is_called() -> None:
    spy = SpyPlanner()
    async with mission_stack(planner=spy) as stack:
        mission = await stack.run_mission("leve o tb2 até a doca de carga", robot_id="tb1")

    assert spy.calls == 0
    assert mission["status"] == "not_understood"
    assert mission["steps"] == []
    assert "tb2" in mission["final_text"] and "tb1" in mission["final_text"]
    assert mission["language"] == "pt"


async def test_no_conflict_reaches_the_planner() -> None:
    spy = SpyPlanner()
    async with mission_stack(planner=spy) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga", robot_id="tb1")

    assert spy.calls == 1
    assert mission["status"] == "completed"
