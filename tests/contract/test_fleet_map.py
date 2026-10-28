"""Mapa no contrato de frota: `GET /api/map` no formato do Fleet UI (SPEC-003, ticket 01)."""

import pytest

from tests.contract.conftest import Backend, fake_options, make_backend
from tests.fake_fleet_ui import create_fake_fleet_ui

pytestmark = pytest.mark.anyio

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


async def test_map_endpoint_matches_the_fleet_ui_format(backend: Backend) -> None:
    fleet_map = await backend.executor.fleet_map()

    assert fleet_map is not None
    assert (fleet_map.resolution, fleet_map.origin_x, fleet_map.origin_y) == (0.1, 0.0, 0.0)
    assert (fleet_map.width, fleet_map.height) == (30, 30)
    assert fleet_map.png.startswith(PNG_SIGNATURE)


async def test_backend_without_a_map_reports_it_unavailable() -> None:
    app = create_fake_fleet_ui(fake_options(map_png=None))
    async for backend in make_backend("fleet_ui", app):
        assert await backend.executor.fleet_map() is None
