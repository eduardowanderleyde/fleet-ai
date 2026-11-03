"""Roda um caso contra o Fleet AI em processo, com um SimFleet novo, e o avalia."""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx2

from fleet_ai.adapters import SimAdapter
from fleet_ai.app import create_app as create_fleet_ai
from fleet_ai.executor import Executor
from fleet_ai.llm import LlmPort
from fleet_ai.llm_planner import LlmPlanner
from fleet_ai.planning import DeterministicPlanner, Planner
from fleet_ai.scenario import ScenarioNames, load_names
from fleet_eval.cases import Case
from fleet_eval.metered import MeteredLlm
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock

FLEET_URL = "http://simfleet"
TERMINAL = {"completed", "not_understood", "incomplete", "failed", "rejected"}
MOVED_M = 0.05  # deslocamento a partir do qual um robô conta como movido
AT_PLACE_M = 0.1  # distância máxima até o lugar esperado
MISSION_DEADLINE_S = 300.0


@dataclass(frozen=True)
class Contender:
    """Quem planeja: o determinístico (`llm_for` None) ou o planejador LLM.

    `llm_for` devolve um LLM novo para cada caso (o roteirizado tem um roteiro
    por caso; um modelo real pode devolver sempre o mesmo cliente).
    """

    name: str
    llm_for: Callable[[Case], LlmPort] | None = None


DETERMINISTIC = Contender("deterministic")


@dataclass(frozen=True)
class CaseResult:
    case: Case
    status: str
    passed: bool
    failures: tuple[str, ...]
    tools: tuple[str, ...]
    moved: tuple[str, ...]
    seconds: float
    llm_turns: int = 0
    llm_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    rejected_tool_calls: int = 0
    error: str | None = None


def _planner(
    contender: Contender, case: Case, names: ScenarioNames
) -> tuple[Planner, MeteredLlm | None]:
    if contender.llm_for is None:
        return DeterministicPlanner(names), None
    meter = MeteredLlm(contender.llm_for(case))
    return LlmPlanner(meter), meter


async def run_case(case: Case, contender: Contender) -> CaseResult:
    """Uma falha inesperada vira resultado `error`; cancelamento propaga."""
    started = time.perf_counter()
    try:
        return await _run(case, contender)
    except Exception as exc:  # noqa: BLE001 - um caso com erro não para a suíte
        return CaseResult(
            case,
            "error",
            False,
            (f"error: {type(exc).__name__}",),
            (),
            (),
            time.perf_counter() - started,
            error=type(exc).__name__,
        )


async def _run(case: Case, contender: Contender) -> CaseResult:
    names = load_names()
    planner, meter = _planner(contender, case, names)
    simfleet = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    executor = Executor(SimAdapter(FLEET_URL, transport=simfleet), poll_interval=0.0)
    app = create_fleet_ai(executor=executor, planner=planner)
    api_transport = httpx2.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with (
        httpx2.AsyncClient(base_url="http://fleet-ai", transport=api_transport) as api,
        httpx2.AsyncClient(base_url=FLEET_URL, transport=simfleet) as fleet,
    ):
        try:
            before = await _poses(fleet)
            started = time.perf_counter()
            mission = await _mission(api, case)
            seconds = time.perf_counter() - started
            after = await _poses(fleet)
        finally:
            await executor.aclose()
    tools = tuple(step["tool"] for step in mission["steps"])
    moved = tuple(
        robot for robot, pose in after.items() if math.dist(pose, before[robot]) > MOVED_M
    )
    status = mission["status"]
    failures = _grade(case, status, tools, moved, after, names)
    return CaseResult(
        case,
        status,
        not failures,
        failures,
        tools,
        moved,
        seconds,
        llm_turns=meter.turns if meter else 0,
        llm_seconds=meter.seconds if meter else 0.0,
        input_tokens=meter.input_tokens if meter else 0,
        output_tokens=meter.output_tokens if meter else 0,
        rejected_tool_calls=(meter.tool_calls - len(tools)) if meter else 0,
    )


async def _mission(api: httpx2.AsyncClient, case: Case) -> dict[str, Any]:
    body: dict[str, Any] = {"instruction": case.instruction}
    if case.robot_id is not None:
        body["robot_id"] = case.robot_id
    created = await api.post("/v1/missions", json=body)
    created.raise_for_status()
    mission_id = created.json()["mission_id"]
    deadline = time.monotonic() + MISSION_DEADLINE_S
    while time.monotonic() < deadline:
        mission: dict[str, Any] = (await api.get(f"/v1/missions/{mission_id}")).json()
        if mission["status"] in TERMINAL:
            return mission
        await asyncio.sleep(0.001)
    raise TimeoutError("mission still running")


async def _poses(fleet: httpx2.AsyncClient) -> dict[str, tuple[float, float]]:
    status = (await fleet.get("/api/status")).json()
    return {robot: (pose["x"], pose["y"]) for robot, pose in status["poses"].items()}


def _grade(
    case: Case,
    status: str,
    tools: tuple[str, ...],
    moved: tuple[str, ...],
    poses: dict[str, tuple[float, float]],
    names: ScenarioNames,
) -> tuple[str, ...]:
    expect = case.expect
    failures: list[str] = []
    if status not in expect.status:
        failures.append(f"status {status}, expected {'/'.join(expect.status)}")
    if status == "completed":
        missing = [tool for tool in expect.tools if tool not in tools]
        if missing:
            failures.append(f"missing tools: {', '.join(missing)}")
    used = [tool for tool in expect.forbidden if tool in tools]
    if used:
        failures.append(f"forbidden tools: {', '.join(used)}")
    target = _destination(case, names)
    if target is not None and status == "completed":
        label, point = target
        if len(moved) != 1 or moved[0] not in expect.robots:
            failures.append(f"moved {list(moved)}, expected one of {list(expect.robots)}")
        elif math.dist(poses[moved[0]], point) > AT_PLACE_M:
            failures.append(f"{moved[0]} did not reach {label}")
    elif moved:
        failures.append(f"robots moved: {', '.join(moved)}")
    return tuple(failures)


async def run_suite(cases: list[Case], contender: Contender) -> list[CaseResult]:
    """Um caso por vez, cada um com a frota no estado inicial."""
    return [await run_case(case, contender) for case in cases]


def _destination(case: Case, names: ScenarioNames) -> tuple[str, tuple[float, float]] | None:
    expect = case.expect
    if expect.point is not None:
        return f"x {expect.point[0]} y {expect.point[1]}", expect.point
    if expect.place is not None:
        place = next(p for p in names.places if p.name == expect.place)
        return place.name, (place.x, place.y)
    return None
