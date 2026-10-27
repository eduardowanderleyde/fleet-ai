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

    async def _get(self, path: str) -> Any:
        response = await self._client.get(path)
        return response.json()

    async def _post(self, path: str, **params: str | float) -> httpx2.Response:
        return await self._client.post(path, params=params)

    async def list_robots(self) -> list[str]:
        data = await self._get("/api/list_robots")
        return list(data.get("robot_ids", []))

    async def status(self) -> dict[str, Any]:
        data: dict[str, Any] = await self._get("/api/status")
        return data


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


def _normalized(response: httpx2.Response) -> CommandResponse:
    data = response.json()
    return CommandResponse(bool(data["success"]), data["message"], data["error_code"])


# No Fleet UI, "" é o robô padrão do modo de robô único; no contrato, não é um robô.
_UNKNOWN_EMPTY_ID = CommandResponse(False, "Unknown robot ''", "UNKNOWN_ROBOT")


# Recusas 403 de `_require_muut` no backend do Fleet UI, antes de chamar o ROS.
_BACKEND_REFUSALS: dict[str, CommandErrorCode] = {
    "não declarado em roles.yaml": "UNKNOWN_ROBOT",
    "não permite movimento": "ROLE_NOT_ALLOWED",
}


def _translate(response: httpx2.Response) -> CommandResponse:
    data = response.json()
    text = str(data.get("message", ""))
    if response.status_code == 403:
        for marker, code in _BACKEND_REFUSALS.items():
            if marker in text:
                return CommandResponse(False, text, code)
    if response.status_code == 422:
        fields = ", ".join(str(error["loc"][-1]) for error in data.get("detail", []))
        return CommandResponse(False, f"Invalid request: {fields}", "INVALID_REQUEST")
    service = _service_response(text)
    if service is not None:
        return service
    if data.get("success") is False:
        # O próprio `ros2 service call` falhou (timeout, serviço ausente): não há
        # resposta do orquestrador para traduzir.
        raise FleetBackendError(f"Fleet UI: {text}")
    return CommandResponse(True, text)


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
