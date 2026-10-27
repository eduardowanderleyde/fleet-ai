"""Fronteira de erro dos adaptadores (ADR-0005): recusas válidas x falhas do backend."""

from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from fleet_ai.adapters import FleetAdapter, FleetUiAdapter, SimAdapter
from fleet_ai.contract import FleetBackendError

pytestmark = pytest.mark.anyio

Handler = Callable[[httpx2.Request], httpx2.Response]


def adapter(kind: str, handler: Handler) -> FleetAdapter:
    transport = httpx2.MockTransport(handler)
    cls = SimAdapter if kind == "sim" else FleetUiAdapter
    return cls("http://fleet", transport=transport)


def respond(status_code: int, body: Any = None, text: str | None = None) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if text is not None:
            return httpx2.Response(status_code, text=text)
        return httpx2.Response(status_code, json=body)

    return handler


def refuse_connection(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


OPERATIONS: dict[str, Callable[[FleetAdapter], Any]] = {
    "list_robots": lambda a: a.list_robots(),
    "status": lambda a: a.status(),
    "go_to_point": lambda a: a.go_to_point("r1", 1.0, 1.0, 0.0),
    "cancel": lambda a: a.cancel("r1"),
}


@pytest.fixture(params=["sim", "fleet_ui"])
def kind(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_unreachable_backend_raises_fleet_backend_error(kind: str, operation: str) -> None:
    fleet = adapter(kind, refuse_connection)

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_server_error_raises_fleet_backend_error(kind: str, operation: str) -> None:
    fleet = adapter(kind, respond(500, text="<html>Internal Server Error</html>"))

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_non_json_body_raises_fleet_backend_error(kind: str, operation: str) -> None:
    fleet = adapter(kind, respond(200, text="<html>proxy login</html>"))

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()


INCOMPLETE_BODIES = [
    ("status", {"pose": {"x": 0, "y": 0, "yaw": 0}}),
    ("status", {"robots": "r1"}),
    ("status", {"robots": [{"robot_id": "r1", "role": "MUUT"}]}),
    ("status", {"robots": [{"robot_id": "r1", "role": "MUUT", "nav_state": "flying"}]}),
    ("list_robots", {}),
    ("list_robots", {"robot_ids": "r1"}),
    ("go_to_point", {"ok": True}),
    ("cancel", {"message": 42}),
]


@pytest.mark.parametrize(("operation", "body"), INCOMPLETE_BODIES)
async def test_incomplete_body_raises_fleet_backend_error(
    kind: str, operation: str, body: dict[str, Any]
) -> None:
    fleet = adapter(kind, respond(200, body))

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()


def refusal(code: str) -> dict[str, Any]:
    return {"success": False, "message": f"refused: {code}", "error_code": code}


VALID_SIM_REFUSALS = [
    (422, "INVALID_REQUEST"),
    (403, "UNKNOWN_ROBOT"),
    (403, "ROLE_NOT_ALLOWED"),
    (409, "ALREADY_NAVIGATING"),
    (409, "CANCEL_FAILED"),
]


@pytest.mark.parametrize(("status_code", "code"), VALID_SIM_REFUSALS)
@pytest.mark.parametrize("operation", ["go_to_point", "cancel"])
async def test_valid_contract_refusals_stay_refusals(
    operation: str, status_code: int, code: str
) -> None:
    fleet = adapter("sim", respond(status_code, refusal(code)))

    response = await OPERATIONS[operation](fleet)

    assert (response.success, response.error_code) == (False, code)
    await fleet.aclose()


UNEXPECTED_4XX = [
    (400, {"detail": "Bad Request"}),
    (401, {"detail": "Not authenticated"}),
    (404, {"detail": "Not Found"}),
    (405, {"detail": "Method Not Allowed"}),
    (409, {"success": False, "message": "conflict"}),
    (403, {"success": False, "message": "blocked by proxy"}),
    (403, refusal("ALREADY_NAVIGATING")),  # código incoerente com o 403
    (409, refusal("UNKNOWN_ROBOT")),  # código incoerente com o 409
    (422, refusal("CANCEL_FAILED")),  # código incoerente com o 422
    (422, {"detail": [{"msg": "no location"}]}),  # 422 malformado
    (400, refusal("INVALID_REQUEST")),  # status fora da tabela
]


@pytest.mark.parametrize(("status_code", "body"), UNEXPECTED_4XX)
@pytest.mark.parametrize("operation", ["go_to_point", "cancel"])
async def test_unexpected_4xx_raises_fleet_backend_error(
    kind: str, operation: str, status_code: int, body: dict[str, Any]
) -> None:
    fleet = adapter(kind, respond(status_code, body))

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()


async def test_sim_success_carrying_an_error_code_is_outside_the_contract() -> None:
    fleet = adapter("sim", respond(200, {"success": True, "message": "ok", "error_code": "X"}))

    with pytest.raises(FleetBackendError):
        await fleet.go_to_point("r1", 1.0, 1.0, 0.0)
    await fleet.aclose()


@pytest.mark.parametrize("status_code", [400, 404, 409])
async def test_fleet_ui_service_text_only_counts_with_http_200(status_code: int) -> None:
    text = (
        "response:\nfleet_msgs.srv.GoToPoint_Response("
        "success=False, message='Already navigating', error_code='ALREADY_NAVIGATING')"
    )
    fleet = adapter("fleet_ui", respond(status_code, {"success": True, "message": text}))

    with pytest.raises(FleetBackendError):
        await fleet.go_to_point("r1", 1.0, 1.0, 0.0)
    await fleet.aclose()


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
@pytest.mark.parametrize("operation", ["list_robots", "status"])
async def test_any_http_error_on_queries_raises_fleet_backend_error(
    kind: str, operation: str, status_code: int
) -> None:
    fleet = adapter(kind, respond(status_code, {"robots": [], "robot_ids": []}))

    with pytest.raises(FleetBackendError):
        await OPERATIONS[operation](fleet)
    await fleet.aclose()
