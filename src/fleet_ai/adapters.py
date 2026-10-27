"""Adaptadores de frota: ligam o Executor a um backend de frota (ADR-0002, ADR-0005).

O adaptador `sim` fala com o SimFleet, que já responde no contrato normalizado.
O adaptador `fleet_ui` é o único lugar que conhece o formato bruto do Fleet UI.
"""

import math
import re
from typing import Any, Protocol, cast

import httpx2

from fleet_ai.contract import (
    COMMAND_ERROR_CODES,
    CommandErrorCode,
    CommandResponse,
    FleetBackendError,
)


class FleetAdapter(Protocol):
    async def list_robots(self) -> list[str]: ...

    async def status(self) -> dict[str, Any]:
        """`GET /api/status`, no mesmo formato nos dois backends."""
        ...

    async def go_to_point(
        self, robot_id: str, x: float, y: float, yaw: float
    ) -> CommandResponse: ...

    async def cancel(self, robot_id: str) -> CommandResponse: ...

    async def aclose(self) -> None: ...


class _HttpAdapter:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, **params: str | float) -> httpx2.Response:
        """Envia a requisição; transporte e 5xx são falhas do backend (ADR-0005)."""
        try:
            response = await self._client.request(method, path, params=params or None)
        except httpx2.HTTPError as exc:
            raise FleetBackendError(f"{method} {path}: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 500:
            raise FleetBackendError(f"{method} {path}: HTTP {response.status_code}")
        return response

    async def _get(self, path: str) -> Any:
        response = await self._send("GET", path)
        if response.status_code != 200:
            raise FleetBackendError(f"GET {path}: HTTP {response.status_code}")
        return _json(response, f"GET {path}")

    async def _post(self, path: str, **params: str | float) -> httpx2.Response:
        return await self._send("POST", path, **params)

    async def list_robots(self) -> list[str]:
        data = await self._get("/api/list_robots")
        robot_ids = data.get("robot_ids") if isinstance(data, dict) else None
        if not isinstance(robot_ids, list) or not all(isinstance(r, str) for r in robot_ids):
            raise FleetBackendError("GET /api/list_robots: body outside the contract")
        return robot_ids

    async def status(self) -> dict[str, Any]:
        data = await self._get("/api/status")
        if not _is_status(data):
            raise FleetBackendError("GET /api/status: body outside the contract")
        status: dict[str, Any] = data
        return status


class SimAdapter(_HttpAdapter):
    """SimFleet: repassa as respostas, que já são normalizadas."""

    async def go_to_point(self, robot_id: str, x: float, y: float, yaw: float) -> CommandResponse:
        return _normalized(
            await self._post("/api/go_to_point", robot_id=robot_id, x=x, y=y, yaw=yaw)
        )

    async def cancel(self, robot_id: str) -> CommandResponse:
        return _normalized(await self._post("/api/cancel", robot_id=robot_id))


class FleetUiAdapter(_HttpAdapter):
    """Fleet UI (fleet-ui@a57a3b1): traduz as respostas brutas para o contrato."""

    async def go_to_point(self, robot_id: str, x: float, y: float, yaw: float) -> CommandResponse:
        if robot_id == "":
            return _UNKNOWN_EMPTY_ID
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            # O Fleet UI aceita nan e inf como float e os repassaria ao Nav2.
            return CommandResponse(
                False, "Invalid request: non-finite coordinate", "INVALID_REQUEST"
            )
        response = await self._post("/api/go_to_point", robot_id=robot_id, x=x, y=y, yaw=yaw)
        return _translate(response)

    async def cancel(self, robot_id: str) -> CommandResponse:
        if robot_id == "":
            return _UNKNOWN_EMPTY_ID
        return _translate(await self._post("/api/cancel", robot_id=robot_id))


def _json(response: httpx2.Response, where: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise FleetBackendError(f"{where}: body is not JSON") from exc


_NAV_STATES = {"idle", "navigating", "failed"}


def _is_status(data: Any) -> bool:
    """O mínimo do formato de `/api/status` que o Executor usa."""
    if not isinstance(data, dict) or not isinstance(data.get("robots"), list):
        return False
    return all(
        isinstance(robot, dict)
        and isinstance(robot.get("robot_id"), str)
        and isinstance(robot.get("role"), str)
        and robot.get("nav_state") in _NAV_STATES
        for robot in data["robots"]
    )


def _normalized(response: httpx2.Response) -> CommandResponse:
    where = str(response.request.url.path)
    data = _json(response, where)
    if not (
        isinstance(data, dict)
        and isinstance(data.get("success"), bool)
        and isinstance(data.get("message"), str)
        and isinstance(data.get("error_code"), str)
    ):
        raise FleetBackendError(f"{where}: body outside the contract")
    code = data["error_code"]
    if data["success"]:
        valid = response.status_code == 200 and code == ""
    else:
        valid = _REFUSAL_STATUS.get(code) == response.status_code
    if not valid:
        raise FleetBackendError(
            f"{where}: HTTP {response.status_code} with {code!r} is not a refusal"
        )
    return CommandResponse(data["success"], data["message"], cast(CommandErrorCode, code))


# HTTP de cada recusa do contrato normalizado (ADR-0005).
_REFUSAL_STATUS = {
    "INVALID_REQUEST": 422,
    "UNKNOWN_ROBOT": 403,
    "ROLE_NOT_ALLOWED": 403,
    "ALREADY_NAVIGATING": 409,
    "CANCEL_FAILED": 409,
}


# No Fleet UI, "" é o robô padrão do modo de robô único; no contrato, não é um robô.
_UNKNOWN_EMPTY_ID = CommandResponse(False, "Unknown robot ''", "UNKNOWN_ROBOT")


# Recusas 403 de `_require_muut` no backend do Fleet UI, antes de chamar o ROS.
_BACKEND_REFUSALS: dict[str, CommandErrorCode] = {
    "não declarado em roles.yaml": "UNKNOWN_ROBOT",
    "não permite movimento": "ROLE_NOT_ALLOWED",
}


def _translate(response: httpx2.Response) -> CommandResponse:
    where = str(response.request.url.path)
    data = _json(response, where)
    if not isinstance(data, dict):
        raise FleetBackendError(f"{where}: body outside the contract")
    if response.status_code == 422:
        return _fastapi_validation_error(data, where)
    if not (isinstance(data.get("success"), bool) and isinstance(data.get("message"), str)):
        raise FleetBackendError(f"{where}: body outside the contract")
    text = data["message"]
    if response.status_code == 403:
        for marker, code in _BACKEND_REFUSALS.items():
            if marker in text:
                return CommandResponse(False, text, code)
        raise FleetBackendError(f"{where}: HTTP 403 that is not a known refusal")
    if response.status_code != 200:
        raise FleetBackendError(f"{where}: unexpected HTTP {response.status_code}")
    service = _service_response(text)
    if service is not None:
        return service
    if data.get("success") is False:
        # O próprio `ros2 service call` falhou (timeout, serviço ausente): não há
        # resposta do orquestrador para traduzir.
        raise FleetBackendError(f"Fleet UI: {text}")
    return CommandResponse(True, text)


def _fastapi_validation_error(data: dict[str, Any], where: str) -> CommandResponse:
    detail = data.get("detail")
    if not (
        isinstance(detail, list)
        and detail
        and all(isinstance(e, dict) and isinstance(e.get("loc"), list) and e["loc"] for e in detail)
    ):
        raise FleetBackendError(f"{where}: HTTP 422 outside the FastAPI format")
    fields = ", ".join(str(error["loc"][-1]) for error in detail)
    return CommandResponse(False, f"Invalid request: {fields}", "INVALID_REQUEST")


def _service_response(text: str) -> CommandResponse | None:
    """Lê `success`, `message` e `error_code` do repr() que o `ros2 service call` imprime
    depois de "response:", por exemplo
    `fleet_msgs.srv.GoToPoint_Response(success=False, message='Already navigating',
    error_code='ALREADY_NAVIGATING')`.
    """
    tail = text[text.rfind("response:") :] if "response:" in text else ""
    success = re.search(r"\bsuccess=(True|False)\b", tail)
    if success is None:
        return None
    message_match = re.search(r"\bmessage='((?:[^'\\]|\\.)*)'", tail)
    code_match = re.search(r"\berror_code='([^']*)'", tail)
    message = message_match.group(1) if message_match else ""
    code = code_match.group(1) if code_match else ""
    if code not in COMMAND_ERROR_CODES:
        # Códigos do orquestrador fora do contrato (por exemplo NAV2_UNAVAILABLE)
        # indicam backend indisponível, não uma recusa que o planejador entenda.
        raise FleetBackendError(f"Fleet UI: {code}: {message}")
    return CommandResponse(success.group(1) == "True", message, cast(CommandErrorCode, code))
