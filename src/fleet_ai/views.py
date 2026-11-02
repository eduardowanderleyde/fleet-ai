"""Visões de leitura para a interface web: frota e mapa, validadas e sanitizadas.

Nada do backend chega à resposta sem passar por aqui: identificadores seguem um
padrão, `last_error` só tem códigos do contrato e uma falha vira texto fixo
(SPEC-003, ticket 01; regras do ticket 15).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fleet_ai.contract import FleetBackendError, FleetMap, RobotStatus
from fleet_ai.executor import Executor
from fleet_ai.geometry import Frame, canvas_heading, synthetic_frame
from fleet_ai.sanitize import MAX_ROBOTS, is_identifier, safe_last_error, safe_role
from fleet_ai.scenario import ScenarioNames

log = logging.getLogger("fleet_ai.views")

MAP_CACHE_SECONDS = 300.0


@dataclass(frozen=True)
class MapState:
    frame: Frame
    fleet_map: FleetMap | None  # None: o backend não tem mapa (moldura sintética)


class FleetViews:
    """Lê a frota e o mapa pelo Executor; o mapa fica em cache por alguns minutos."""

    def __init__(
        self, executor: Executor, names: ScenarioNames, clock: Callable[[], float]
    ) -> None:
        self._executor = executor
        self._names = names
        self._clock = clock
        self._map: tuple[float, MapState] | None = None

    async def robots(self) -> list[RobotStatus]:
        statuses = await self._executor.fleet_status()
        if len(statuses) > MAX_ROBOTS or not all(is_identifier(s.robot_id) for s in statuses):
            raise FleetBackendError("GET /api/status: robots outside the contract")
        return statuses

    async def map_state(self) -> MapState:
        if self._map is not None and self._clock() - self._map[0] < MAP_CACHE_SECONDS:
            return self._map[1]
        fleet_map = await self._executor.fleet_map()
        if fleet_map is not None:
            frame = Frame(
                fleet_map.resolution,
                fleet_map.origin_x,
                fleet_map.origin_y,
                fleet_map.width,
                fleet_map.height,
            )
        else:
            points = [(p.x, p.y) for p in self._names.places]
            points += [(s.pose.x, s.pose.y) for s in await self.robots()]
            frame = synthetic_frame(points)
        state = MapState(frame, fleet_map)
        self._map = (self._clock(), state)
        return state

    async def fleet(self) -> dict[str, Any]:
        statuses = await self.robots()
        frame = (await self.map_state()).frame
        return {"robots": [_robot_view(status, frame) for status in statuses]}

    async def map_view(self) -> dict[str, Any]:
        state = await self.map_state()
        frame = state.frame
        return {
            "available": state.fleet_map is not None,
            "resolution": frame.resolution,
            "origin_x": frame.origin_x,
            "origin_y": frame.origin_y,
            "width": frame.width,
            "height": frame.height,
            "image": "/v1/map/image.png" if state.fleet_map is not None else None,
            "places": [
                {"name": p.name, "x": p.x, "y": p.y, "pixel": frame.to_pixel(p.x, p.y)}
                for p in self._names.places
            ],
        }


def _robot_view(status: RobotStatus, frame: Frame) -> dict[str, Any]:
    pose = status.pose
    return {
        "robot_id": status.robot_id,
        "role": safe_role(status.role),
        "nav_state": status.nav_state,
        "last_error": safe_last_error(status.last_error),
        "pose": {"x": pose.x, "y": pose.y, "yaw": pose.yaw},
        "pixel": frame.to_pixel(pose.x, pose.y),
        "heading": canvas_heading(pose.yaw),
    }
