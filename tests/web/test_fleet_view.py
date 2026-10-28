"""Leituras da interface web validadas e sanitizadas (SPEC-003, ticket 01)."""

import base64
from typing import Any

import httpx2
import pytest

from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot, blank_png
from tests.fleet_ai_client import SwitchableTransport, mission_stack

pytestmark = pytest.mark.anyio

SENSITIVE = [
    "http://10.0.0.5:8000/internal",
    "postgres://admin:s3cret@db:5432",
    "Authorization: Bearer sk-test-FAKE",
    'Traceback (most recent call last): File "/opt/ros/humble/x.py"',
]


@pytest.mark.parametrize("adapter", ["sim", "fleet_ui"])
async def test_fleet_view_lists_robots_with_poses_and_states(adapter: str) -> None:
    options: dict[str, Any] = {}
    if adapter == "fleet_ui":
        options["fake_fleet_ui"] = FakeFleetUiOptions(
            robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0), FakeRobot("tb3", "FUUT", 0.0, 4.0)]
        )
    async with mission_stack(**options) as stack:
        response = await stack.api.get("/v1/fleet")

    robots = {robot["robot_id"]: robot for robot in response.json()["robots"]}
    assert response.status_code == 200
    assert robots["tb1"]["nav_state"] == "idle"
    assert robots["tb1"]["role"] == "MUUT"
    assert robots["tb1"]["pose"] == {"x": 0.0, "y": 0.0, "yaw": 0.0}
    assert robots["tb3"]["role"] == "FUUT"
    assert robots["tb3"]["pose"]["y"] == 4.0
    if adapter == "sim":
        assert set(robots) == {"tb1", "tb2", "tb3"}


@pytest.mark.parametrize("text", SENSITIVE)
async def test_fleet_view_sanitizes_backend_text(text: str) -> None:
    robot = FakeRobot("tb1", text, 0.0, 0.0, nav_state="failed", last_error=text)
    async with mission_stack(fake_fleet_ui=FakeFleetUiOptions(robots=[robot])) as stack:
        response = await stack.api.get("/v1/fleet")

    [view] = response.json()["robots"]
    assert (view["role"], view["last_error"], view["nav_state"]) == (
        "UNKNOWN",
        "NAV_ERROR",
        "failed",
    )
    assert text not in response.text


async def test_fleet_view_is_unavailable_without_leaking_details() -> None:
    async with mission_stack(transport=_down()) as stack:
        responses = [
            await stack.api.get(path) for path in ("/v1/fleet", "/v1/map", "/v1/map/image.png")
        ]

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "error": "fleet_unavailable",
            "message": "The fleet backend is unavailable.",
        }


def _down() -> SwitchableTransport:
    switch = SwitchableTransport(httpx2.MockTransport(lambda request: httpx2.Response(500)))
    switch.down = True
    return switch


def _map_body(png: bytes, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "available": True,
        "resolution": 0.1,
        "origin_x": 0.0,
        "origin_y": 0.0,
        "width": 30,
        "height": 30,
        "png_b64": base64.b64encode(png).decode("ascii"),
    }
    body.update(overrides)
    return body


PNG_30 = blank_png(30, 30)
ENCODED_30 = base64.b64encode(PNG_30).decode("ascii")
BAD_MAPS = {
    # Cabeçalho válido e coerente, só grande demais: apenas o limite de tamanho recusa.
    "oversized": _map_body(PNG_30 + b"\0" * (8 * 1024 * 1024)),
    "too_wide": _map_body(PNG_30, width=5000),
    "ihdr_mismatch": _map_body(PNG_30, width=31),
    # Sem validação estrita, os caracteres inválidos seriam ignorados e o PNG passaria.
    "not_strict_base64": {
        **_map_body(PNG_30),
        "png_b64": ENCODED_30[:20] + "!\n" + ENCODED_30[20:],
    },
    "fake_png": _map_body(b"GIF89a" + b"\0" * 40),
    "bad_resolution": _map_body(PNG_30, resolution=0),
    "not_a_number": _map_body(PNG_30, origin_x="0"),
}


@pytest.mark.parametrize("case", BAD_MAPS)
async def test_read_endpoints_reject_malformed_or_oversized_maps(case: str) -> None:
    options = FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)], map_body=BAD_MAPS[case]
    )
    async with mission_stack(fake_fleet_ui=options) as stack:
        map_view = await stack.api.get("/v1/map")
        image = await stack.api.get("/v1/map/image.png")

    assert map_view.status_code == 503
    assert image.status_code == 503
    assert map_view.json()["error"] == "fleet_unavailable"


async def test_backend_without_a_map_gets_a_synthetic_frame() -> None:
    options = FakeFleetUiOptions(robots=[FakeRobot("tb1", "MUUT", 1.0, 2.0)], map_png=None)
    async with mission_stack(fake_fleet_ui=options) as stack:
        map_view = (await stack.api.get("/v1/map")).json()
        image = await stack.api.get("/v1/map/image.png")
        fleet = (await stack.api.get("/v1/fleet")).json()

    assert map_view["available"] is False
    assert map_view["image"] is None
    assert image.status_code == 404
    assert image.json()["error"] == "map_unavailable"
    assert fleet["robots"][0]["pixel"]["inside"] is True
    assert all(place["pixel"]["inside"] for place in map_view["places"])


@pytest.mark.parametrize(
    "robots",
    [
        [FakeRobot(f"r{n}", "MUUT", 0.0, 0.0) for n in range(101)],
        [FakeRobot("r" * 65, "MUUT", 0.0, 0.0)],
        [FakeRobot("<script>", "MUUT", 0.0, 0.0)],
    ],
    ids=["too_many_robots", "id_too_long", "id_not_an_identifier"],
)
async def test_read_endpoints_reject_robots_outside_the_contract(robots: list[FakeRobot]) -> None:
    async with mission_stack(fake_fleet_ui=FakeFleetUiOptions(robots=robots)) as stack:
        response = await stack.api.get("/v1/fleet")

    assert response.status_code == 503
    assert "<script>" not in response.text
