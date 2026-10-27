"""Despachante de ferramentas: a única forma de um planejador agir na frota.

Cada chamada vira um passo da missão. Uma recusa do backend (`CommandRefused`)
vira um resultado de erro com o `error_code`; falhas do backend propagam.
"""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from fleet_ai.contract import CommandRefused, RobotStatus
from fleet_ai.executor import Executor


class Dispatcher:
    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self.steps: list[dict[str, Any]] = []
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
        try:
            result, is_error = await self._tools[tool](tool_input), False
        except CommandRefused as refused:
            result, is_error = {"error_code": refused.error_code, "message": refused.message}, True
        self.steps.append(
            {"tool": tool, "input": tool_input, "result": result, "is_error": is_error}
        )
        return result, is_error

    async def _list_robots(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"robot_ids": await self._executor.list_robots()}

    async def _get_robot_status(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return _status_view(await self._executor.robot_status(tool_input["robot_id"]))

    async def _move_robot(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        await self._executor.move_robot(
            tool_input["robot_id"], tool_input["x"], tool_input["y"], tool_input.get("yaw", 0.0)
        )
        return {"accepted": True}

    async def _wait_for_arrival(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return _status_view(await self._executor.wait_for_navigation(tool_input["robot_id"]))

    async def _cancel_navigation(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"outcome": await self._executor.cancel_navigation(tool_input["robot_id"])}


def _status_view(status: RobotStatus) -> dict[str, Any]:
    return asdict(status)
