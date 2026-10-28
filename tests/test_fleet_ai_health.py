"""Seleção do adaptador de frota, liveness e readiness (ticket 11; SPEC-001)."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import pytest

from fleet_ai.app import create_app
from simfleet.app import create_app as create_simfleet
from simfleet.clock import SteppingClock
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot, create_fake_fleet_ui
from tests.fleet_ai_client import SwitchableTransport

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


class RecordingTransport(httpx2.AsyncBaseTransport):
    """Transporte de teste do backend de frota: registra cada URL chamada."""

    def __init__(
        self, inner: httpx2.AsyncBaseTransport | None = None, handler: Handler | None = None
    ) -> None:
        self.inner = inner
        self.handler = handler
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.urls.append(str(request.url))
        if self.handler is not None:
            return await self.handler(request)
        assert self.inner is not None
        return await self.inner.handle_async_request(request)


async def refuse(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused to fleet.internal:8001", request=request)


@asynccontextmanager
async def fleet_ai(
    transport: httpx2.AsyncBaseTransport,
    *,
    clock: Callable[[], float] = time.monotonic,
    probe_timeout: float = 2.0,
) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(fleet_transport=transport, clock=clock, health_probe_timeout=probe_timeout)
    api = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(base_url="http://fleet-ai", transport=api) as client:
        yield client


async def test_liveness_never_calls_the_backend() -> None:
    backend = RecordingTransport(handler=refuse)

    async with fleet_ai(backend) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert backend.urls == []


def simfleet() -> httpx2.AsyncBaseTransport:
    return httpx2.ASGITransport(app=create_simfleet(clock=SteppingClock(1.0)))


async def test_default_adapter_is_sim_and_ready_when_the_backend_answers() -> None:
    backend = RecordingTransport(simfleet())

    async with fleet_ai(backend) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "fleet_adapter": "sim",
        "fleet_backend_reachable": True,
        "planner": "deterministic",
        "llm_enabled": False,
    }
    assert backend.urls == ["http://localhost:8001/api/list_robots"]


async def test_service_starts_with_the_backend_down() -> None:
    async with fleet_ai(RecordingTransport(handler=refuse)) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["fleet_backend_reachable"] is False


def fake_fleet_ui() -> httpx2.AsyncBaseTransport:
    options = FakeFleetUiOptions(robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)])
    return httpx2.ASGITransport(app=create_fake_fleet_ui(options))


async def test_fleet_ui_adapter_is_selected_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLEET_AI_FLEET_ADAPTER", "fleet_ui")
    monkeypatch.setenv("FLEET_AI_FLEET_URL", "http://fleet-ui.lab:8000")
    backend = RecordingTransport(fake_fleet_ui())

    async with fleet_ai(backend) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["fleet_adapter"] == "fleet_ui"
    assert backend.urls == ["http://fleet-ui.lab:8000/api/list_robots"]


def test_unknown_adapter_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_AI_FLEET_ADAPTER", "ros2")

    with pytest.raises(ValueError, match="FLEET_AI_FLEET_ADAPTER.*sim.*fleet_ui"):
        create_app(fleet_transport=RecordingTransport(handler=refuse))


def test_fleet_ui_without_url_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_AI_FLEET_ADAPTER", "fleet_ui")

    with pytest.raises(ValueError, match="FLEET_AI_FLEET_URL"):
        create_app(fleet_transport=RecordingTransport(handler=refuse))


@pytest.mark.parametrize(
    "url",
    [
        "http://admin:s3cret@fleet-ui.lab:8000",
        "ftp://fleet-ui.lab",
        "http://",
        "http://fleet-ui.lab:99999",
        "http://fleet-ui.lab:0",
        "http://fleet-ui.lab:8000?token=s3cret",
        "http://fleet-ui.lab:8000#s3cret",
        "http://fleet-ui.lab:8000/fleet;s3cret",
    ],
    ids=[
        "credentials",
        "scheme",
        "no_host",
        "bad_port",
        "port_zero",
        "query",
        "fragment",
        "path_params",
    ],
)
@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
def test_invalid_fleet_url_prevents_startup_without_network(
    monkeypatch: pytest.MonkeyPatch, adapter: str, url: str
) -> None:
    monkeypatch.setenv("FLEET_AI_FLEET_ADAPTER", adapter)
    monkeypatch.setenv("FLEET_AI_FLEET_URL", url)
    backend = RecordingTransport(handler=refuse)

    with pytest.raises(ValueError, match="FLEET_AI_FLEET_URL") as error:
        create_app(fleet_transport=backend)

    assert backend.urls == []
    assert "s3cret" not in str(error.value)


async def answer_robot_list(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/api/list_robots"):
        return httpx2.Response(200, json={"robot_ids": ["tb1"]})
    return httpx2.Response(404, json={"detail": "Not Found"})


@pytest.mark.parametrize("url", ["https://host/fleet", "https://host/fleet/"])
@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
async def test_base_path_is_preserved_in_backend_calls(
    monkeypatch: pytest.MonkeyPatch, adapter: str, url: str
) -> None:
    monkeypatch.setenv("FLEET_AI_FLEET_ADAPTER", adapter)
    monkeypatch.setenv("FLEET_AI_FLEET_URL", url)
    backend = RecordingTransport(handler=answer_robot_list)

    async with fleet_ai(backend) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert backend.urls == ["https://host/fleet/api/list_robots"]


async def server_error(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(500, text="Traceback: /srv/fleet.internal:8001 secret")


async def not_json(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, text="<html>fleet.internal login</html>")


async def out_of_contract(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"robots": "fleet.internal"})


FAILURES = {
    "refused": refuse,
    "http_500": server_error,
    "not_json": not_json,
    "contract": out_of_contract,
}


@pytest.mark.parametrize("failure", FAILURES)
async def test_readiness_is_degraded_without_exposing_backend_details(failure: str) -> None:
    async with fleet_ai(RecordingTransport(handler=FAILURES[failure])) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "fleet_adapter": "sim",
        "fleet_backend_reachable": False,
        "planner": "deterministic",
        "llm_enabled": False,
    }
    for secret in ("fleet.internal", "8001", "localhost", "refused", "Traceback", "secret"):
        assert secret not in response.text


async def slow(request: httpx2.Request) -> httpx2.Response:
    await asyncio.sleep(5)
    return httpx2.Response(200, json={"robot_ids": []})


async def test_readiness_answers_within_the_probe_timeout() -> None:
    started = time.monotonic()
    async with fleet_ai(RecordingTransport(handler=slow), probe_timeout=0.1) as client:
        # Limite de segurança do teste: sem o prazo da sondagem, a chamada esperaria 5 s.
        response = await asyncio.wait_for(client.get("/health"), 3)

    assert response.status_code == 503
    assert time.monotonic() - started < 1.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_readiness_is_cached_for_five_seconds() -> None:
    clock = FakeClock()
    backend = RecordingTransport(handler=answer_robot_list)

    async with fleet_ai(backend, clock=clock) as client:
        first = await client.get("/health")
        clock.now += 4.9
        cached = await client.get("/health")
        probes_within_cache = len(backend.urls)
        clock.now += 1.2  # 6,1 s depois da sondagem
        await client.get("/health")

    assert (first.status_code, cached.status_code) == (200, 200)
    assert probes_within_cache == 1
    assert len(backend.urls) == 2


async def test_readiness_recovers_when_the_backend_comes_back() -> None:
    clock = FakeClock()
    backend = SwitchableTransport(simfleet())
    backend.down = True

    async with fleet_ai(backend, clock=clock) as client:
        down = await client.get("/health")
        backend.down = False
        still_cached = await client.get("/health")
        clock.now += 6
        back = await client.get("/health")

    assert down.status_code == 503
    assert still_cached.status_code == 503  # o resultado vale por 5 s
    assert back.status_code == 200
    assert back.json()["status"] == "ok"


class GatedBackend:
    """Backend que só responde quando `gate` abre; conta as sondagens."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.calls = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        await self.gate.wait()
        return httpx2.Response(200, json={"robot_ids": ["tb1"]})


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(1000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condição não ocorreu")


async def test_concurrent_health_checks_share_a_single_probe() -> None:
    gated = GatedBackend()

    async with fleet_ai(RecordingTransport(handler=gated)) as client:
        checks = [asyncio.create_task(client.get("/health")) for _ in range(5)]
        await until(lambda: gated.calls >= 1)
        for _ in range(50):
            await asyncio.sleep(0)  # dá chance de as outras chamadas sondarem também
        checks[0].cancel()  # cancelar uma chamada não cancela a sondagem compartilhada
        gated.gate.set()
        results = await asyncio.gather(*checks[1:])

    assert gated.calls == 1
    assert [response.status_code for response in results] == [200] * 4
    assert checks[0].cancelled()


async def unexpected(request: httpx2.Request) -> httpx2.Response:
    raise RuntimeError("defeito inesperado na sondagem")


@pytest.mark.parametrize(
    "scenario", ["network_failure", "unexpected_exception", "cancelled_caller"]
)
async def test_probe_never_stays_pending_after_failure_or_cancellation(scenario: str) -> None:
    clock = FakeClock()
    gated = GatedBackend()
    calls = {"failing": 0}

    async def first_probe(request: httpx2.Request) -> httpx2.Response:
        calls["failing"] += 1
        if scenario == "network_failure":
            return await refuse(request)
        if scenario == "unexpected_exception":
            return await unexpected(request)
        return await gated(request)

    backend = RecordingTransport(handler=first_probe)
    async with fleet_ai(backend, clock=clock, probe_timeout=0.2) as client:
        if scenario == "cancelled_caller":
            starter = asyncio.create_task(client.get("/health"))
            await until(lambda: gated.calls == 1)
            starter.cancel()  # quem iniciou a sondagem desiste; ela segue até o prazo
            first = await asyncio.wait_for(client.get("/health"), 3)
        else:
            first = await asyncio.wait_for(client.get("/health"), 3)
        clock.now += 6
        backend.handler = answer_robot_list
        second = await asyncio.wait_for(client.get("/health"), 3)

    assert first.status_code == 503
    assert second.status_code == 200  # sondou de novo e respondeu
    assert len(backend.urls) == 2
