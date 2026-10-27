"""Guardas de entrada, taxa por IP e concorrência (ticket 09; SPEC-001)."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from fleet_ai.adapters import SimAdapter
from fleet_ai.app import create_app as create_fleet_ai
from fleet_ai.executor import Executor
from fleet_ai.guards import Limits
from fleet_ai.planning import PlanOutcome
from fleet_ai.tools import Dispatcher
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio


class CountingPlanner:
    """Planejador de teste: conta quantas missões chegaram a ser planejadas."""

    name = "test"

    def __init__(self) -> None:
        self.runs = 0

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        self.runs += 1
        return PlanOutcome("completed", "en", "ok")


@pytest.mark.parametrize("instruction", ["", "   ", "x" * 301])
async def test_empty_or_too_long_instruction_is_rejected_before_planning(
    instruction: str,
) -> None:
    planner = CountingPlanner()
    async with mission_stack(planner=planner, limits=Limits()) as stack:
        response = await stack.api.post("/v1/missions", json={"instruction": instruction})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert response.json()["message"]
    assert planner.runs == 0


async def test_instruction_at_the_length_limit_is_accepted() -> None:
    planner = CountingPlanner()
    async with mission_stack(planner=planner, limits=Limits()) as stack:
        response = await stack.api.post("/v1/missions", json={"instruction": "x" * 300})

    assert response.status_code == 202
    assert planner.runs == 1


@pytest.mark.parametrize(
    "body",
    [
        {"instruction": "liste os robôs", "robot_id": ""},
        {"instruction": "liste os robôs", "robot_id": "tb 1"},
        {"instruction": "liste os robôs", "robot_id": "t" * 33},
        {"instruction": "liste os robôs", "robot_id": "tb1;drop"},
        {"instruction": "liste os robôs", "robot_id": 5},
        {"robot_id": "tb1"},
        {"instruction": 123},
    ],
    ids=[
        "empty_id",
        "space",
        "too_long",
        "semicolon",
        "number",
        "no_instruction",
        "int_instruction",
    ],
)
async def test_invalid_body_or_robot_id_is_rejected_before_planning(body: dict[str, Any]) -> None:
    planner = CountingPlanner()
    async with mission_stack(planner=planner, limits=Limits()) as stack:
        response = await stack.api.post("/v1/missions", json=body)

    assert response.status_code == 422
    assert set(response.json()) == {"error", "message"}
    assert response.json()["error"] == "invalid_request"
    assert planner.runs == 0


class FakeClock:
    """Relógio de teste para as janelas de taxa, em segundos."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def post(client: httpx2.AsyncClient, instruction: str = "liste os robôs") -> httpx2.Response:
    return await client.post("/v1/missions", json={"instruction": instruction})


async def test_missions_per_minute_are_limited_per_ip() -> None:
    clock = FakeClock()
    limits = Limits(missions_per_minute=2)
    async with mission_stack(planner=CountingPlanner(), limits=limits, clock=clock) as stack:
        first, second = await post(stack.api), await post(stack.api)
        clock.now += 10
        third = await post(stack.api)
        async with stack.client("203.0.113.9") as other_ip:
            other = await post(other_ip)
        clock.now += 51  # 61 s depois da primeira missão
        after_a_minute = await post(stack.api)

    assert (first.status_code, second.status_code) == (202, 202)
    assert third.status_code == 429
    assert third.json()["error"] == "rate_limited"
    assert 1 <= int(third.headers["Retry-After"]) <= 60
    assert other.status_code == 202
    assert after_a_minute.status_code == 202


async def test_missions_per_day_are_limited_per_ip() -> None:
    clock = FakeClock()
    limits = Limits(missions_per_minute=100, missions_per_day=3)
    async with mission_stack(planner=CountingPlanner(), limits=limits, clock=clock) as stack:
        accepted = []
        for _ in range(3):
            accepted.append((await post(stack.api)).status_code)
            clock.now += 3600  # uma hora entre missões: o limite por minuto não conta
        fourth = await post(stack.api)
        clock.now += 24 * 3600
        next_day = await post(stack.api)

    assert accepted == [202, 202, 202]
    assert fourth.status_code == 429
    assert fourth.json()["error"] == "rate_limited"
    assert int(fourth.headers["Retry-After"]) > 60  # espera pela janela do dia, não do minuto
    assert next_day.status_code == 202


class GatePlanner:
    """Planejador de teste que segura cada missão até `gate` abrir."""

    name = "test"

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.running = 0

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        self.running += 1
        await self.gate.wait()
        self.running -= 1
        return PlanOutcome("completed", "en", "ok")


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(1000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condição não ocorreu")


async def test_concurrent_missions_are_limited_and_the_slot_is_released() -> None:
    planner = GatePlanner()
    limits = Limits(max_concurrent=2, missions_per_minute=3)
    async with mission_stack(planner=planner, limits=limits) as stack:
        held = [asyncio.create_task(post(stack.api)) for _ in range(2)]
        await until(lambda: planner.running == 2)
        third = await post(stack.api)
        planner.gate.set()
        finished = [(await task).status_code for task in held]
        after_release = await post(stack.api)

    assert third.status_code == 429
    assert third.json()["error"] == "too_many_missions"
    assert int(third.headers["Retry-After"]) >= 1
    assert finished == [202, 202]
    # A recusa por concorrência não gastou cota: 3 por minuto, e esta é a terceira aceita.
    assert after_release.status_code == 202


async def post_as(client: httpx2.AsyncClient, forwarded_for: str) -> int:
    response = await client.post(
        "/v1/missions",
        json={"instruction": "liste os robôs"},
        headers={"X-Forwarded-For": forwarded_for},
    )
    return response.status_code


async def test_forwarded_for_from_an_untrusted_peer_does_not_escape_the_limit() -> None:
    limits = Limits(missions_per_minute=1)
    async with mission_stack(planner=CountingPlanner(), limits=limits) as stack:
        codes = [await post_as(stack.api, f"198.51.100.{n}") for n in range(3)]

    assert codes == [202, 429, 429]


async def test_forwarded_for_from_a_trusted_proxy_identifies_the_client() -> None:
    limits = Limits(missions_per_minute=1, trusted_proxies=frozenset({"10.0.0.2"}))
    async with (
        mission_stack(planner=CountingPlanner(), limits=limits) as stack,
        stack.client("10.0.0.2") as proxy,
    ):
        alice = await post_as(proxy, "198.51.100.7")
        bob = await post_as(proxy, "198.51.100.8")
        alice_again = await post_as(proxy, "198.51.100.7")
        # O cliente forjou um endereço à esquerda; vale o que o proxy viu (à direita).
        forged = await post_as(proxy, "203.0.113.1, 198.51.100.8")

    assert (alice, bob) == (202, 202)
    assert alice_again == 429
    assert forged == 429


async def test_missions_beyond_the_retention_limit_drop_the_oldest() -> None:
    limits = Limits(missions_retained=2)
    async with mission_stack(planner=CountingPlanner(), limits=limits) as stack:
        ids = [(await post(stack.api)).json()["mission_id"] for _ in range(3)]
        codes = [
            (await stack.api.get(f"/v1/missions/{mission_id}")).status_code for mission_id in ids
        ]

    assert codes == [404, 200, 200]


async def test_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_AI_MAX_INSTRUCTION_CHARS", "20")
    monkeypatch.setenv("FLEET_AI_MISSIONS_PER_MINUTE", "1")
    monkeypatch.setenv("FLEET_AI_TRUSTED_PROXIES", "10.0.0.2, 10.0.0.3")

    async with (
        mission_stack(planner=CountingPlanner()) as stack,
        stack.client("10.0.0.3") as proxy,
    ):
        too_long = await post(stack.api, "liste todos os robôs agora")
        first, second = await post(stack.api), await post(stack.api)
        behind_proxy = await post_as(proxy, "198.51.100.7")

    assert too_long.status_code == 422
    assert (first.status_code, second.status_code) == (202, 429)
    assert behind_proxy == 202  # cota própria do cliente atrás do proxy confiável


async def test_mission_time_limit_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLEET_AI_MISSION_TIMEOUT", "0.2")
    planner = GatePlanner()  # nunca abre: a missão só termina pelo tempo máximo

    async with mission_stack(planner=planner, mission_timeout=None) as stack:
        # Limite de segurança do teste: sem o tempo máximo, a missão nunca terminaria.
        mission = await asyncio.wait_for(stack.run_mission("liste os robôs"), 5)

    assert mission["status"] == "incomplete"
    assert "0,2 s" in mission["final_text"]


@pytest.mark.parametrize(
    ("variable", "value"),
    [("FLEET_AI_MISSIONS_PER_MINUTE", "abc"), ("FLEET_AI_MAX_CONCURRENT", "0")],
)
def test_invalid_limit_in_the_environment_prevents_startup(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=variable):
        create_fleet_ai(executor=Executor(SimAdapter("http://fleet")))


async def test_rate_limits_still_hold_after_cleanup() -> None:
    clock = FakeClock()
    limits = Limits(missions_per_minute=10, missions_per_day=1)
    async with mission_stack(planner=CountingPlanner(), limits=limits, clock=clock) as stack:
        first = await post(stack.api)
        clock.now += 120  # passa da janela de varredura
        async with stack.client("203.0.113.9") as other_ip:
            other = await post(other_ip)  # dispara a limpeza
        again = await post(stack.api)

    assert (first.status_code, other.status_code) == (202, 202)
    assert again.status_code == 429  # a limpeza não zerou a cota do dia
