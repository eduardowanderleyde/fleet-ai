"""Executor: a fronteira única entre o Fleet AI e um backend de frota.

Portado de fleet-ui@a57a3b1:backend/agents/executor.py (licença MIT, ver
THIRD_PARTY_NOTICES.md), reduzido às operações do MVP e reescrito sobre o
contrato normalizado e os adaptadores de frota (ADR-0005).
"""

import asyncio
import time
from typing import Any

from fleet_ai.adapters import FleetAdapter
from fleet_ai.contract import (
    CancelOutcome,
    CommandRefused,
    ExecutorTimeout,
    Pose,
    RobotStatus,
)


class Executor:
    def __init__(
        self, adapter: FleetAdapter, *, poll_interval: float = 0.5, timeout: float = 120.0
    ) -> None:
        self._adapter = adapter
        self._poll_interval = poll_interval
        self._timeout = timeout
        # Robôs cujo destino ativo foi enviado por este Executor: base da correlação
        # de cancelamentos. O robô sai daqui quando é visto fora de `navigating`.
        self._sent: set[str] = set()

    @property
    def adapter_name(self) -> str:
        return self._adapter.name

    async def aclose(self) -> None:
        await self._adapter.aclose()

    async def list_robots(self) -> list[str]:
        return await self._adapter.list_robots()

    async def robot_status(self, robot_id: str) -> RobotStatus:
        status = _robot_status(await self._adapter.status(), robot_id)
        if status.nav_state != "navigating":
            self._sent.discard(robot_id)
        return status

    async def move_robot(self, robot_id: str, x: float, y: float, yaw: float = 0.0) -> None:
        """Envia o destino; a navegação é assíncrona (ADR-0005)."""
        response = await self._adapter.go_to_point(robot_id, x, y, yaw)
        if not response.success:
            raise CommandRefused(response.error_code, response.message)
        self._sent.add(robot_id)

    async def cancel_navigation(
        self, robot_id: str, *, timeout: float | None = None
    ) -> CancelOutcome:
        """Cancela e verifica: `confirmed` só com as três evidências do ADR-0005.

        (1) este Executor enviou o destino ativo e viu o robô em `navigating`;
        (2) o cancel foi aceito; (3) a primeira leitura fora de `navigating` é `idle`.
        """
        before = await self.robot_status(robot_id)
        own = before.nav_state == "navigating" and robot_id in self._sent
        response = await self._adapter.cancel(robot_id)
        if not response.success:
            raise CommandRefused(response.error_code, response.message)
        self._sent.discard(robot_id)
        try:
            after = await self.wait_for_navigation(robot_id, timeout=timeout)
        except ExecutorTimeout:
            return "not_confirmed"
        return "confirmed" if own and after.nav_state == "idle" else "ambiguous"

    async def wait_for_navigation(
        self, robot_id: str, *, timeout: float | None = None
    ) -> RobotStatus:
        """Consulta o status até o robô sair de `navigating` e devolve o estado final.

        `timeout` substitui o prazo do Executor nesta espera.
        """
        limit = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        while True:
            status = await self.robot_status(robot_id)
            if status.nav_state != "navigating":
                return status
            if time.monotonic() > deadline:
                raise ExecutorTimeout(f"{robot_id} still navigating after {limit} s")
            await asyncio.sleep(self._poll_interval)


def _robot_status(status: dict[str, Any], robot_id: str) -> RobotStatus:
    robot = next((r for r in status.get("robots", []) if r.get("robot_id") == robot_id), None)
    if robot is None:
        raise CommandRefused("UNKNOWN_ROBOT", f"Unknown robot {robot_id!r}")
    # Pose deste robô; "pose" (singular) é a do robô padrão, como na referência.
    pose = (status.get("poses") or {}).get(robot_id) or status.get("pose") or {}
    return RobotStatus(
        robot_id=robot_id,
        role=robot.get("role", ""),
        nav_state=robot.get("nav_state", "idle"),
        last_error=robot.get("last_error", ""),
        pose=Pose(
            float(pose.get("x", 0.0)), float(pose.get("y", 0.0)), float(pose.get("yaw", 0.0))
        ),
    )
