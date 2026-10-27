"""Fleet AI em processo ligado a um backend de frota em processo.

Por padrão, um SimFleet do warehouse (adaptador `sim`). Os testes de encerramento
trocam o transporte (backend fora do ar ou respondendo lixo), usam o fake do Fleet
UI (adaptador `fleet_ui`), um prazo curto do Executor ou um planejador de teste.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2

from fleet_ai.adapters import FleetAdapter, FleetUiAdapter, SimAdapter
from fleet_ai.app import create_app as create_fleet_ai
from fleet_ai.executor import Executor
from fleet_ai.planning import Planner
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, create_fake_fleet_ui

FLEET_URL = "http://fleet"


class SwitchableTransport(httpx2.AsyncBaseTransport):
    """Repassa ao backend real, ou recusa a conexão enquanto `down` for verdadeiro."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self.inner = inner
        self.down = False

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("connection refused", request=request)
        return await self.inner.handle_async_request(request)


@dataclass
class Stack:
    api: httpx2.AsyncClient  # API pública do Fleet AI
    fleet: httpx2.AsyncClient  # outro cliente do backend, para preparar e observar a frota

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
async def mission_stack(
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
    fake_fleet_ui: FakeFleetUiOptions | None = None,
    executor_timeout: float = 120.0,
    planner: Planner | None = None,
) -> AsyncIterator[Stack]:
    if fake_fleet_ui is not None:
        backend: httpx2.AsyncBaseTransport = httpx2.ASGITransport(
            app=create_fake_fleet_ui(fake_fleet_ui)
        )
    else:
        backend = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
    fleet_transport = transport or backend
    adapter: FleetAdapter = (
        FleetUiAdapter(FLEET_URL, transport=fleet_transport)
        if fake_fleet_ui is not None
        else SimAdapter(FLEET_URL, transport=fleet_transport)
    )
    executor = Executor(adapter, poll_interval=0.0, timeout=executor_timeout)
    api = httpx2.ASGITransport(app=create_fleet_ai(executor=executor, planner=planner))
    async with (
        httpx2.AsyncClient(base_url="http://fleet-ai", transport=api) as api_client,
        httpx2.AsyncClient(base_url=FLEET_URL, transport=backend) as fleet_client,
    ):
        try:
            yield Stack(api_client, fleet_client)
        finally:
            await executor.aclose()
