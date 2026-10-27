"""Backends da suíte de contrato: SimFleet (adaptador `sim`) e fake do Fleet UI
(adaptador `fleet_ui`), com a mesma frota: r1 MUUT em (0,5; 0,5) e r2 FUUT em (2,5; 2,5).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from fleet_ai.adapters import FleetAdapter, FleetUiAdapter, SimAdapter
from fleet_ai.executor import Executor
from simfleet.app import create_app
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot, create_fake_fleet_ui
from tests.scenarios import OPEN_ROOM, room_scenario, write_scenario

BASE_URL = "http://fleet"


@dataclass
class Backend:
    kind: str
    executor: Executor
    raw: httpx2.AsyncClient  # outro cliente do mesmo backend, como a interface web do Fleet UI


def fake_options(**overrides: object) -> FakeFleetUiOptions:
    options = FakeFleetUiOptions(
        robots=[FakeRobot("r1", "MUUT", 0.5, 0.5), FakeRobot("r2", "FUUT", 2.5, 2.5)]
    )
    for name, value in overrides.items():
        setattr(options, name, value)
    return options


def sim_app(tmp_path: Path) -> FastAPI:
    scenario = room_scenario()
    scenario["robots"][1]["role"] = "FUUT"
    return create_app(write_scenario(tmp_path, scenario, OPEN_ROOM), clock=SteppingClock(0.1))


async def make_backend(kind: str, app: FastAPI, timeout: float = 5.0) -> AsyncIterator[Backend]:
    transport = httpx2.ASGITransport(app=app)
    adapter: FleetAdapter = (
        SimAdapter(BASE_URL, transport=transport)
        if kind == "sim"
        else FleetUiAdapter(BASE_URL, transport=transport)
    )
    async with httpx2.AsyncClient(base_url=BASE_URL, transport=transport) as raw:
        executor = Executor(adapter, poll_interval=0.0, timeout=timeout)
        try:
            yield Backend(kind, executor, raw)
        finally:
            await executor.aclose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=["sim", "fleet_ui"])
async def backend(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Backend]:
    app = sim_app(tmp_path) if request.param == "sim" else create_fake_fleet_ui(fake_options())
    async for value in make_backend(request.param, app):
        yield value
