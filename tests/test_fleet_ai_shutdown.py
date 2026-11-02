"""Encerramento do Fleet AI pelo ciclo de vida ASGI, como no `docker compose stop` (ticket 12)."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest

from fleet_ai.adapters import SimAdapter
from fleet_ai.app import create_app
from fleet_ai.executor import Executor
from fleet_ai.health import Readiness
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock

pytestmark = pytest.mark.anyio


class Backend(httpx2.AsyncBaseTransport):
    """Backend de frota de teste: pode segurar a resposta e registra o fechamento."""

    def __init__(self, *, hold: bool = False) -> None:
        self.inner = httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))
        self.hold = hold
        self.calls = 0
        self.cancelled = False
        self.closed = False

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        if self.hold:
            try:
                await asyncio.Event().wait()  # nunca responde
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        self.closed = True


@asynccontextmanager
async def lifespan(app: Any) -> AsyncIterator[None]:
    """Conduz o protocolo de lifespan do ASGI, como o uvicorn ao subir e ao parar."""
    inbox: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}
    server = asyncio.create_task(app(scope, inbox.get, outbox.put))
    await inbox.put({"type": "lifespan.startup"})
    assert (await asyncio.wait_for(outbox.get(), 5))["type"] == "lifespan.startup.complete"
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        message = await asyncio.wait_for(outbox.get(), 5)
        assert message["type"] == "lifespan.shutdown.complete", message
        await asyncio.wait_for(server, 5)


def client(app: Any) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(base_url="http://fleet-ai", transport=httpx2.ASGITransport(app=app))


def probe_tasks() -> list[asyncio.Task[Any]]:
    return [
        task
        for task in asyncio.all_tasks()
        if not task.done() and "_probe_once" in task.get_coro().__qualname__  # type: ignore[union-attr]
    ]


async def until(condition: Any) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condição não atingida")


async def test_shutdown_cancels_a_pending_readiness_probe() -> None:
    backend = Backend(hold=True)
    app = create_app(fleet_transport=backend, health_probe_timeout=60.0)

    async with lifespan(app), client(app) as api:
        request = asyncio.create_task(api.get("/health"))
        await until(lambda: backend.calls == 1)
        assert len(probe_tasks()) == 1

    assert backend.cancelled  # a sondagem foi cancelada, não abandonada
    assert probe_tasks() == []
    # Quem esperava a sondagem não fica pendurado: termina sem corpo interno.
    [outcome] = await asyncio.wait_for(asyncio.gather(request, return_exceptions=True), 2)
    if isinstance(outcome, httpx2.Response):
        assert outcome.status_code == 500
        assert outcome.json() == {"error": "internal_error", "message": "Internal error"}


async def test_shutdown_closes_the_executor_the_app_created() -> None:
    backend = Backend()
    app = create_app(fleet_transport=backend)

    async with lifespan(app), client(app) as api:
        assert (await api.get("/health")).status_code == 200
        assert not backend.closed

    assert backend.closed


async def test_shutdown_leaves_an_injected_executor_open() -> None:
    backend = Backend()
    executor = Executor(SimAdapter("http://fleet", transport=backend), poll_interval=0.0)
    app = create_app(executor=executor)

    async with lifespan(app), client(app) as api:
        assert (await api.get("/health")).status_code == 200

    assert not backend.closed  # o executor é de quem o criou
    assert await executor.list_robots() == ["tb1", "tb2", "tb3"]
    await executor.aclose()
    assert backend.closed


async def test_shutdown_without_any_probe_is_clean() -> None:
    backend = Backend()
    app = create_app(fleet_transport=backend)

    async with lifespan(app):
        pass

    assert backend.calls == 0
    assert backend.closed


async def test_readiness_aclose_returns_only_after_the_probe_ended() -> None:
    started, ended = asyncio.Event(), asyncio.Event()

    async def probe() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    readiness = Readiness(probe, adapter="sim", clock=time.monotonic, timeout=60.0)
    waiter = asyncio.create_task(readiness.reachable())
    await started.wait()

    await readiness.aclose()

    assert ended.is_set()  # já terminou quando o aclose voltou
    assert probe_tasks() == []
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await readiness.aclose()  # sem sondagem em andamento: não faz nada
