"""Fleet AI em processo ligado a um SimFleet do warehouse em processo (adaptador `sim`)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2

from fleet_ai.adapters import SimAdapter
from fleet_ai.app import create_app as create_fleet_ai
from fleet_ai.executor import Executor
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock

SIMFLEET_URL = "http://simfleet"


@dataclass
class Stack:
    api: httpx2.AsyncClient  # API pública do Fleet AI
    fleet: httpx2.AsyncClient  # outro cliente do SimFleet, para preparar e observar a frota

    async def run_mission(self, instruction: str, **body: Any) -> dict[str, Any]:
        """Cria a missão e devolve o estado dela quando sair de `running`."""
        created = await self.api.post("/v1/missions", json={"instruction": instruction, **body})
        mission_id = created.json()["mission_id"]
        for _ in range(100):
            mission: dict[str, Any] = (await self.api.get(f"/v1/missions/{mission_id}")).json()
            if mission["status"] != "running":
                return mission
        raise AssertionError(f"missão {mission_id} ainda em running")


@asynccontextmanager
async def mission_stack() -> AsyncIterator[Stack]:
    simfleet = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    executor = Executor(SimAdapter(SIMFLEET_URL, transport=simfleet), poll_interval=0.0)
    api = httpx2.ASGITransport(app=create_fleet_ai(executor=executor))
    async with (
        httpx2.AsyncClient(base_url="http://fleet-ai", transport=api) as api_client,
        httpx2.AsyncClient(base_url=SIMFLEET_URL, transport=simfleet) as fleet_client,
    ):
        try:
            yield Stack(api_client, fleet_client)
        finally:
            await executor.aclose()
