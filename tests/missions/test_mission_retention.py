"""Retenção segura e admissão atômica (ticket 14; SPEC-001, Guardas).

O `mission_id` de uma missão presa só chega quando ela termina (a missão roda
depois da resposta, e o transporte de teste espera por ela). Por isso a prova de
que uma missão `running` nunca saiu da memória é o `GET` dela responder 200, e não
404, depois de liberada.
"""

import asyncio
from collections.abc import Callable

import httpx2
import pytest

from fleet_ai.guards import Limits
from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

HOLD = "segure esta missão"
QUICK = "missão rápida"


class HoldPlanner:
    """Segura as missões cuja instrução contém "segure" até `gate` abrir."""

    name = "test"

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = 0
        self.held = 0

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        self.started += 1
        if "segure" in instruction:
            self.held += 1
            await self.gate.wait()
        return PlanOutcome("completed", "pt", "ok")


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(2000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condição não ocorreu")


async def post(client: httpx2.AsyncClient, instruction: str) -> httpx2.Response:
    return await client.post("/v1/missions", json={"instruction": instruction})


async def test_retention_drops_the_oldest_terminal_mission_and_keeps_running_ones() -> None:
    planner = HoldPlanner()
    limits = Limits(missions_retained=2, max_concurrent=4)
    async with mission_stack(planner=planner, limits=limits) as stack:
        held = asyncio.create_task(post(stack.api, HOLD))
        await until(lambda: planner.held == 1)
        older_terminal = (await post(stack.api, QUICK)).json()["mission_id"]
        newer = (await post(stack.api, QUICK)).json()["mission_id"]
        dropped = (await stack.api.get(f"/v1/missions/{older_terminal}")).status_code
        kept = (await stack.api.get(f"/v1/missions/{newer}")).status_code
        planner.gate.set()
        running_id = (await held).json()["mission_id"]
        running_after = (await stack.api.get(f"/v1/missions/{running_id}")).status_code

    assert dropped == 404  # a terminal mais antiga saiu
    assert kept == 200
    assert running_after == 200  # a que estava running nunca saiu


async def test_creation_is_refused_when_no_terminal_mission_can_be_dropped() -> None:
    planner = HoldPlanner()
    limits = Limits(missions_retained=2, max_concurrent=4, missions_per_minute=3)
    async with mission_stack(planner=planner, limits=limits) as stack:
        held = [asyncio.create_task(post(stack.api, HOLD)) for _ in range(2)]
        await until(lambda: planner.held == 2)
        refused = await post(stack.api, QUICK)
        started_before_release = planner.started
        planner.gate.set()
        accepted_ids = [(await task).json()["mission_id"] for task in held]
        after = await post(stack.api, QUICK)  # 3ª aceita: a recusada não gastou cota

    assert refused.status_code == 503
    assert refused.json() == {"error": "capacity_exhausted", "message": refused.json()["message"]}
    assert "mission_id" not in refused.json()
    assert int(refused.headers["Retry-After"]) >= 1
    assert started_before_release == 2  # o planejador não rodou para a recusada
    assert len(set(accepted_ids)) == 2
    assert after.status_code == 202


async def test_concurrent_creations_never_exceed_the_retention_capacity() -> None:
    planner = HoldPlanner()
    limits = Limits(missions_retained=3, max_concurrent=10, missions_per_minute=4)
    async with mission_stack(planner=planner, limits=limits) as stack:
        tasks = [asyncio.create_task(post(stack.api, HOLD)) for _ in range(10)]
        await until(lambda: planner.held == 3 and sum(task.done() for task in tasks) == 7)
        refused_tasks = [task for task in tasks if task.done()]
        refused = [task.result() for task in refused_tasks]
        started_before_release = planner.started
        planner.gate.set()
        accepted = [await task for task in tasks if task not in refused_tasks]
        after = await post(stack.api, QUICK)  # 4ª aceita: as 7 recusadas não gastaram cota

    assert [response.status_code for response in refused] == [503] * 7
    assert all("mission_id" not in response.json() for response in refused)
    assert started_before_release == 3  # só as aceitas chegaram a planejar
    assert [response.status_code for response in accepted] == [202] * 3
    assert len({response.json()["mission_id"] for response in accepted}) == 3
    assert after.status_code == 202


@pytest.mark.parametrize(("retained", "held", "quick"), [(2, 1, 5), (3, 2, 6), (4, 3, 4)])
async def test_running_missions_never_disappear(retained: int, held: int, quick: int) -> None:
    planner = HoldPlanner()
    limits = Limits(missions_retained=retained, max_concurrent=10, missions_per_minute=100)
    async with mission_stack(planner=planner, limits=limits) as stack:
        held_tasks = [asyncio.create_task(post(stack.api, HOLD)) for _ in range(held)]
        await until(lambda: planner.held == held)
        quick_codes = [(await post(stack.api, QUICK)).status_code for _ in range(quick)]
        planner.gate.set()
        held_ids = [(await task).json()["mission_id"] for task in held_tasks]
        codes = [(await stack.api.get(f"/v1/missions/{mid}")).status_code for mid in held_ids]

    assert set(quick_codes) <= {202, 503}
    assert codes == [200] * held
