"""Despachante de ferramentas: a única forma de um planejador agir na frota.

Cada chamada vira um passo da missão. Uma recusa do backend (`CommandRefused`)
vira um resultado de erro com o `error_code`. Falhas do backend
(`FleetBackendError`) e o prazo do Executor (`ExecutorTimeout`) também ficam
registradas no passo, com uma mensagem genérica, e depois propagam (SPEC-001).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from fleet_ai.contract import (
    CancelOutcome,
    CommandRefused,
    ExecutorTimeout,
    FleetBackendError,
    RobotStatus,
)
from fleet_ai.executor import Executor


class Dispatcher:
    def __init__(
        self,
        executor: Executor,
        steps: list[dict[str, Any]] | None = None,
        *,
        scope: str | None = None,
    ) -> None:
        self._executor = executor
        # Escopo de robô: todo `robot_id` é reescrito à força para ele, qualquer que
        # seja o planejador (SPEC-001). `list_robots` não tem robô e segue igual.
        self._scope = scope
        # Robô com navegação enviada por esta missão e ainda não encerrada: é o que
        # se cancela quando a missão estoura o tempo máximo (ticket 08).
        self.navigating: str | None = None
        # Os passos são da missão: quem cria o despachante pode passar a lista dela.
        self.steps: list[dict[str, Any]] = steps if steps is not None else []
        self._tools: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "list_robots": self._list_robots,
            "get_robot_status": self._get_robot_status,
            "move_robot": self._move_robot,
            "wait_for_arrival": self._wait_for_arrival,
            "cancel_navigation": self._cancel_navigation,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        """As ferramentas do MVP, e nenhuma outra (SPEC-001)."""
        return tuple(self._tools)

    async def call(self, tool: str, tool_input: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Executa a ferramenta, registra o passo e devolve (resultado, is_error)."""
        if tool not in self._tools:
            raise ValueError(f"unknown tool {tool!r}")
        if self._scope is not None and "robot_id" in tool_input:
            tool_input = {**tool_input, "robot_id": self._scope}
        try:
            result, is_error = await self._tools[tool](tool_input), False
        except CommandRefused as refused:
            result, is_error = {"error_code": refused.error_code, "message": refused.message}, True
        except FleetBackendError:
            self._record(tool, tool_input, _BACKEND_UNAVAILABLE, is_error=True)
            raise
        except ExecutorTimeout:
            self._record(tool, tool_input, _NAVIGATION_TIMEOUT, is_error=True)
            raise
        self._record(tool, tool_input, result, is_error=is_error)
        return result, is_error

    async def cancel_active(self, timeout: float) -> tuple[str, str] | None:
        """Cancela, com verificação e prazo, a navegação em curso desta missão.

        Registra o passo `cancel_navigation` e devolve (robô, resultado), em que o
        resultado é `confirmed`, `ambiguous`, `not_confirmed`, o `error_code` de uma
        recusa ou `backend_unavailable`; None se não havia navegação em curso.
        """
        robot = self.navigating
        if robot is None:
            return None
        tool_input = {"robot_id": robot}
        outcome: CancelOutcome
        try:
            # O prazo vale para o cancelamento inteiro (leitura, POST e verificação),
            # não só para a espera: um backend lento não estica a missão.
            async with asyncio.timeout(timeout):
                outcome = await self._executor.cancel_navigation(robot, timeout=timeout)
        except TimeoutError:
            outcome = "not_confirmed"
        except CommandRefused as refused:
            error = {"error_code": refused.error_code, "message": refused.message}
            self._record("cancel_navigation", tool_input, error, is_error=True)
            return robot, refused.error_code
        except FleetBackendError:
            self._record("cancel_navigation", tool_input, _BACKEND_UNAVAILABLE, is_error=True)
            return robot, "backend_unavailable"
        finally:
            self.navigating = None
        self._record("cancel_navigation", tool_input, {"outcome": outcome}, is_error=False)
        return robot, outcome

    def _record(
        self, tool: str, tool_input: dict[str, Any], result: dict[str, Any], *, is_error: bool
    ) -> None:
        self.steps.append(
            {"tool": tool, "input": tool_input, "result": result, "is_error": is_error}
        )

    async def _list_robots(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"robot_ids": await self._executor.list_robots()}

    async def _get_robot_status(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return _status_view(await self._executor.robot_status(tool_input["robot_id"]))

    async def _move_robot(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        await self._executor.move_robot(
            tool_input["robot_id"], tool_input["x"], tool_input["y"], tool_input.get("yaw", 0.0)
        )
        self.navigating = tool_input["robot_id"]
        return {"accepted": True}

    async def _wait_for_arrival(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        status = await self._executor.wait_for_navigation(tool_input["robot_id"])
        self.navigating = None
        return _status_view(status)

    async def _cancel_navigation(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"outcome": await self._executor.cancel_navigation(tool_input["robot_id"])}
        finally:
            self.navigating = None


# Resultados genéricos: a mensagem do backend vai só para os logs (SPEC-001).
_BACKEND_UNAVAILABLE = {"error": "backend_unavailable", "message": "Fleet backend unavailable"}
_NAVIGATION_TIMEOUT = {"error": "navigation_timeout", "message": "Navigation did not end in time"}


def _status_view(status: RobotStatus) -> dict[str, Any]:
    return asdict(status)
