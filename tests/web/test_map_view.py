"""Mapa da interface web: geometria, lugares e conversão metros → pixels (SPEC-003, ticket 01)."""

import math
from pathlib import Path

import pytest

from simfleet.scenario import DEFAULT_SCENARIO
from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

WAREHOUSE_PNG = Path(DEFAULT_SCENARIO).parent / "warehouse_map.png"


async def test_map_view_has_geometry_and_named_places() -> None:
    async with mission_stack() as stack:
        response = await stack.api.get("/v1/map")

    body = response.json()
    assert response.status_code == 200
    assert body["available"] is True
    assert (body["resolution"], body["origin_x"], body["origin_y"]) == (0.03, -15.1, -25.0)
    assert (body["width"], body["height"]) == (1006, 1674)
    assert body["image"] == "/v1/map/image.png"
    assert len(body["places"]) == 7
    dock = next(place for place in body["places"] if place["name"] == "doca de carga")
    assert (dock["x"], dock["y"]) == (2.0, 13.5)
    # (2,0 + 15,1) / 0,03 = 570; 1674 − (13,5 + 25,0) / 0,03 = 390,67
    assert dock["pixel"]["x"] == pytest.approx(570.0)
    assert dock["pixel"]["y"] == pytest.approx(390.6667, abs=1e-3)
    assert dock["pixel"]["inside"] is True


async def test_map_image_is_the_scenario_png() -> None:
    async with mission_stack() as stack:
        response = await stack.api.get("/v1/map/image.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == WAREHOUSE_PNG.read_bytes()


@pytest.mark.parametrize(
    ("point", "pixel", "inside"),
    [
        ((-15.1, -25.0), (0.0, 1674.0), True),  # origem: canto inferior esquerdo
        ((-15.1 + 1006 * 0.03, -25.0 + 1674 * 0.03), (1006.0, 0.0), True),  # canto superior direito
        ((-15.1, -25.0 + 1674 * 0.03), (0.0, 0.0), True),  # canto superior esquerdo
        ((-16.1, -25.0), (-33.3333, 1674.0), False),  # 1 m a oeste do mapa
        ((0.0, 40.0), (503.3333, -492.6667), False),  # acima do mapa: 1674 − 65 / 0,03
    ],
    ids=["origin", "top_right", "top_left", "west_outside", "north_outside"],
)
async def test_world_to_pixel_known_points_limits_and_outside_points(
    point: tuple[float, float], pixel: tuple[float, float], inside: bool
) -> None:
    robot = FakeRobot("tb1", "MUUT", *point)
    options = FakeFleetUiOptions(
        robots=[robot],
        map_png=WAREHOUSE_PNG.read_bytes(),
        map_resolution=0.03,
        map_origin=(-15.1, -25.0),
    )
    async with mission_stack(fake_fleet_ui=options) as stack:
        fleet = (await stack.api.get("/v1/fleet")).json()

    [view] = fleet["robots"]
    assert view["pixel"]["x"] == pytest.approx(pixel[0], abs=1e-3)
    assert view["pixel"]["y"] == pytest.approx(pixel[1], abs=1e-3)
    assert view["pixel"]["inside"] is inside


@pytest.mark.parametrize(
    ("yaw", "canvas"),
    [(0.0, 0.0), (math.pi / 2, -math.pi / 2), (math.pi, -math.pi), (-math.pi / 2, math.pi / 2)],
    ids=["east", "north", "west", "south"],
)
async def test_heading_rotation_on_the_canvas(yaw: float, canvas: float) -> None:
    # No mundo, yaw cresce no sentido anti-horário a partir de +x; no canvas o eixo y
    # aponta para baixo, então o ângulo de desenho é −yaw (norte = para cima).
    options = FakeFleetUiOptions(robots=[FakeRobot("tb1", "MUUT", 1.0, 1.0, yaw)])
    async with mission_stack(fake_fleet_ui=options) as stack:
        fleet = (await stack.api.get("/v1/fleet")).json()

    assert fleet["robots"][0]["heading"] == pytest.approx(canvas)
