"""Comportamentos que só o adaptador `fleet_ui` tem: tradução do formato bruto."""

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fleet_ai.adapters import FleetUiAdapter
from fleet_ai.contract import CommandResponse, ExecutorTimeout, FleetBackendError
from tests.contract.conftest import Backend, fake_options, make_backend
from tests.fake_fleet_ui import create_fake_fleet_ui

pytestmark = pytest.mark.anyio


async def fleet_ui_backend(timeout: float = 5.0, **options: object) -> AsyncIterator[Backend]:
    app = create_fake_fleet_ui(fake_options(**options))
    async for value in make_backend("fleet_ui", app, timeout=timeout):
        yield value


async def test_status_without_poses_falls_back_to_the_default_pose() -> None:
    async for backend in fleet_ui_backend(legacy_status=True):
        status = await backend.executor.robot_status("r1")

        assert (status.pose.x, status.pose.y) == (0.5, 0.5)


def _service_call(response: str) -> str:
    """Texto real do `ros2 service call` (formato de fleet-ui@a57a3b1, tests/test_ros_bridge.py)."""
    return (
        "waiting for service to become available...\n"
        "requester: making request: "
        "fleet_msgs.srv.GoToPoint_Request(robot_id='r1', x=1.0, y=1.0, yaw=0.0)\n"
        "\n"
        "response:\n"
        f"fleet_msgs.srv.GoToPoint_Response({response})\n"
    )


TRANSLATIONS = [
    (
        200,
        {
            "success": True,
            "message": _service_call("success=True, message='Navigation started', error_code=''"),
        },
        CommandResponse(True, "Navigation started", ""),
    ),
    (
        200,
        {
            "success": True,
            "message": _service_call(
                "success=False, message='Already navigating', error_code='ALREADY_NAVIGATING'"
            ),
        },
        CommandResponse(False, "Already navigating", "ALREADY_NAVIGATING"),
    ),
    (
        200,
        {
            "success": True,
            "message": _service_call(
                "success=False, message='UNKNOWN_ROBOT', error_code='UNKNOWN_ROBOT'"
            ),
        },
        CommandResponse(False, "UNKNOWN_ROBOT", "UNKNOWN_ROBOT"),
    ),
    (
        200,
        {
            "success": True,
            "message": _service_call(
                "success=False, message='No active goal', error_code='CANCEL_FAILED'"
            ),
        },
        CommandResponse(False, "No active goal", "CANCEL_FAILED"),
    ),
    (
        403,
        {"success": False, "message": "r9: robot_id não declarado em roles.yaml"},
        CommandResponse(False, "r9: robot_id não declarado em roles.yaml", "UNKNOWN_ROBOT"),
    ),
    (
        403,
        {"success": False, "message": "r2: papel 'FUUT' não permite movimento"},
        CommandResponse(False, "r2: papel 'FUUT' não permite movimento", "ROLE_NOT_ALLOWED"),
    ),
    (
        422,
        {
            "detail": [
                {
                    "type": "float_parsing",
                    "loc": ["query", "x"],
                    "msg": "Input should be a valid number",
                }
            ]
        },
        CommandResponse(False, "Invalid request: x", "INVALID_REQUEST"),
    ),
]


def _canned_backend(status_code: int, body: dict[str, Any]) -> FleetUiAdapter:
    app = FastAPI()

    @app.post("/api/go_to_point")
    def go_to_point() -> JSONResponse:
        return JSONResponse(body, status_code=status_code)

    return FleetUiAdapter("http://fleet", transport=httpx2.ASGITransport(app=app))


@pytest.mark.parametrize(("status_code", "body", "expected"), TRANSLATIONS)
async def test_fleet_ui_adapter_translates_raw_service_call_output(
    status_code: int, body: dict[str, Any], expected: CommandResponse
) -> None:
    adapter = _canned_backend(status_code, body)

    assert await adapter.go_to_point("r1", 1.0, 1.0, 0.0) == expected
    await adapter.aclose()


@pytest.mark.parametrize("message", ["timeout", "ros2 service call failed"])
async def test_failed_service_call_is_a_backend_error_not_a_refusal(message: str) -> None:
    adapter = _canned_backend(200, {"success": False, "message": message})

    with pytest.raises(FleetBackendError):
        await adapter.go_to_point("r1", 1.0, 1.0, 0.0)
    await adapter.aclose()


async def test_cancel_followed_by_nav2_aborted_is_ambiguous_not_confirmed() -> None:
    async for backend in fleet_ui_backend(abort_after_cancel=True):
        await backend.executor.move_robot("r1", 2.5, 0.5)
        await backend.executor.robot_status("r1")

        assert await backend.executor.cancel_navigation("r1") == "ambiguous"


async def test_cancel_that_never_stops_the_robot_is_not_confirmed() -> None:
    async for backend in fleet_ui_backend(0.05, cancel_has_no_effect=True, never_arrives=True):
        await backend.executor.move_robot("r1", 2.5, 0.5)

        assert await backend.executor.cancel_navigation("r1") == "not_confirmed"


async def test_wait_for_navigation_times_out() -> None:
    async for backend in fleet_ui_backend(0.05, never_arrives=True):
        await backend.executor.move_robot("r1", 2.5, 0.5)

        with pytest.raises(ExecutorTimeout):
            await backend.executor.wait_for_navigation("r1")


async def test_error_code_outside_the_contract_is_a_backend_error() -> None:
    # O orquestrador responde NAV2_UNAVAILABLE quando o servidor do Nav2 não está no ar.
    body = {
        "success": True,
        "message": _service_call(
            "success=False, message='Nav2 navigate_to_pose not available', "
            "error_code='NAV2_UNAVAILABLE'"
        ),
    }
    adapter = _canned_backend(200, body)

    with pytest.raises(FleetBackendError, match="NAV2_UNAVAILABLE"):
        await adapter.go_to_point("r1", 1.0, 1.0, 0.0)
    await adapter.aclose()
