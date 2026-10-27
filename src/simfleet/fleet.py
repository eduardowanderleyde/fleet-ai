"""Estado da frota simulada: poses e estado de navegação de cada robô."""

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from simfleet.clock import Clock
from simfleet.occupancy import OccupancyGrid
from simfleet.planner import Point, plan_path
from simfleet.scenario import Pose, Robot, Scenario

NavState = Literal["idle", "navigating", "failed"]


@dataclass
class Navigation:
    """Um robô percorrendo um caminho a velocidade constante desde `started_at`."""

    path: list[Point]
    goal_yaw: float
    started_at: float
    length: float = field(init=False)

    def __post_init__(self) -> None:
        self.length = sum(math.dist(a, b) for a, b in zip(self.path, self.path[1:], strict=False))

    def pose_after(self, travelled: float) -> Pose:
        for a, b in zip(self.path, self.path[1:], strict=False):
            segment = math.dist(a, b)
            if travelled <= segment and segment > 0:
                t = travelled / segment
                heading = math.atan2(b[1] - a[1], b[0] - a[0])
                return Pose(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, heading)
            travelled -= segment
        end = self.path[-1]
        return Pose(end[0], end[1], self.goal_yaw)


@dataclass
class RobotState:
    robot: Robot
    pose: Pose
    nav_state: NavState = "idle"
    last_error: str = ""
    navigation: Navigation | None = None


@dataclass(frozen=True)
class CommandResult:
    """Resposta normalizada de comando do contrato de frota (ADR-0005)."""

    success: bool
    message: str
    error_code: str = ""

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.error_code, 200)

    def as_dict(self) -> dict[str, Any]:
        return {"success": self.success, "message": self.message, "error_code": self.error_code}


class Fleet:
    def __init__(self, scenario: Scenario, clock: Clock) -> None:
        self._grid: OccupancyGrid = scenario.grid
        self._clock = clock
        self._speed = scenario.speed_mps
        self._robots = {
            robot.id: RobotState(robot=robot, pose=robot.start) for robot in scenario.robots
        }

    def go_to_point(self, robot_id: str, x: float, y: float, yaw: float) -> CommandResult:
        state = self._robots[robot_id]
        now = self._clock.now()
        self._advance(state, now)
        if state.nav_state == "navigating":
            return CommandResult(False, "Already navigating", "ALREADY_NAVIGATING")
        path = plan_path(self._grid, (state.pose.x, state.pose.y), (x, y))
        if path is None:
            # Falha assíncrona (ADR-0005): aparece no status como failed / NAV2_REJECTED.
            # Códigos de causa, log e testes dessa falha são do ticket 04.
            state.navigation = None
            state.nav_state = "failed"
            state.last_error = "NAV2_REJECTED"
        else:
            state.navigation = Navigation(path, yaw, now)
            state.nav_state = "navigating"
            state.last_error = ""
        return CommandResult(success=True, message="Navigation started")

    def robots(self) -> list[RobotState]:
        """Avança a simulação até agora e devolve o estado de cada robô."""
        now = self._clock.now()
        for state in self._robots.values():
            self._advance(state, now)
        return list(self._robots.values())

    def _advance(self, state: RobotState, now: float) -> None:
        navigation = state.navigation
        if navigation is None:
            return
        travelled = (now - navigation.started_at) * self._speed
        state.pose = navigation.pose_after(travelled)
        if travelled >= navigation.length:
            state.navigation = None
            state.nav_state = "idle"


# HTTP de cada recusa do contrato normalizado (ADR-0005).
_HTTP_STATUS = {"ALREADY_NAVIGATING": 409}
