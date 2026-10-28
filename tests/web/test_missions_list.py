"""Histórico de missões para a interface web (SPEC-003, ticket 01)."""

import asyncio

import httpx2
import pytest

from fleet_ai.guards import Limits
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import SwitchableTransport, mission_stack

pytestmark = pytest.mark.anyio

SUMMARY_FIELDS = {
    "mission_id",
    "status",
    "instruction",
    "robot_id",
    "planner",
    "created_at",
    "finished_at",
}


async def test_missions_list_includes_running_and_finished_newest_first() -> None:
    options = FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)],
        bounds=(-20.0, -30.0, 20.0, 30.0),
        never_arrives=True,
    )
    async with mission_stack(fake_fleet_ui=options, mission_timeout=1.0) as stack:
        done = await stack.run_mission("onde está o tb1?")
        listed = await stack.run_mission("liste os robôs")
        # No ASGITransport o POST só responde quando a missão acaba: dispara em paralelo.
        moving = asyncio.create_task(
            stack.api.post("/v1/missions", json={"instruction": "leve o tb1 até x 1 y 1"})
        )
        for _ in range(200):
            missions = (await stack.api.get("/v1/missions")).json()["missions"]
            if len(missions) == 3:
                break
            await asyncio.sleep(0.005)
        await moving

    assert [m["mission_id"] for m in missions[1:]] == [listed["mission_id"], done["mission_id"]]
    assert missions[0]["status"] == "running"
    assert missions[0]["instruction"] == "leve o tb1 até x 1 y 1"
    assert missions[0]["finished_at"] is None
    assert missions[2]["status"] == "completed"
    assert all(set(m) == SUMMARY_FIELDS for m in missions)  # passos só no detalhe


async def test_missions_list_limit() -> None:
    async with mission_stack() as stack:
        for _ in range(3):
            await stack.run_mission("liste os robôs")
        two = (await stack.api.get("/v1/missions", params={"limit": 2})).json()["missions"]
        default = (await stack.api.get("/v1/missions")).json()["missions"]
        invalid = [
            await stack.api.get("/v1/missions", params={"limit": value})
            for value in ("0", "51", "abc", "-1")
        ]

    assert len(two) == 2
    assert len(default) == 3
    for response in invalid:
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_request"


async def test_read_endpoints_do_not_use_the_mission_rate_limit() -> None:
    limits = Limits(missions_per_minute=2)
    async with mission_stack(limits=limits) as stack:
        for _ in range(10):
            for path in ("/v1/fleet", "/v1/map", "/v1/missions", "/health", "/health/live", "/"):
                await stack.api.get(path)
        first = await stack.api.post("/v1/missions", json={"instruction": "liste os robôs"})
        second = await stack.api.post("/v1/missions", json={"instruction": "liste os robôs"})
        third = await stack.api.post("/v1/missions", json={"instruction": "liste os robôs"})

    assert [first.status_code, second.status_code, third.status_code] == [202, 202, 429]


async def test_history_stays_available_with_the_backend_down() -> None:
    backend = SwitchableTransport(
        httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    )
    async with mission_stack(transport=backend) as stack:
        finished = await stack.run_mission("liste os robôs")
        backend.down = True
        history = await stack.api.get("/v1/missions")
        detail = await stack.api.get(f"/v1/missions/{finished['mission_id']}")
        fleet = await stack.api.get("/v1/fleet")

    assert fleet.status_code == 503
    assert history.status_code == 200
    assert [m["mission_id"] for m in history.json()["missions"]] == [finished["mission_id"]]
    assert detail.status_code == 200
