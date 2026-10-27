"""Estado da frota simulada: poses e estado de navegação de cada robô."""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Literal

from simfleet.clock import Clock
from simfleet.occupancy import OccupancyGrid
from simfleet.planner import PlanningFailed, Point, plan_path
from simfleet.scenario import Pose, Robot, Scenario

NavState = Literal["idle", "navigating", "failed"]

# Códigos de erro do contrato normalizado (ADR-0005); "" significa sucesso.
CommandError = Literal[
    "",
    "INVALID_REQUEST",
    "UNKNOWN_ROBOT",
    "ROLE_NOT_ALLOWED",
    "ALREADY_NAVIGATING",
    "CANCEL_FAILED",
]
NavigationError = Literal["", "NAV2_REJECTED", "NAV2_ABORTED"]

log = logging.getLogger("simfleet.navigation")


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
    last_error: NavigationError = ""
    navigation: Navigation | None = None


@dataclass(frozen=True)
class CommandResult:
    """Resposta normalizada de comando do contrato de frota (ADR-0005)."""

    success: bool
    message: str
    error_code: CommandError = ""

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
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            return CommandResult(False, "Invalid request: non-finite coordinate", "INVALID_REQUEST")
        state = self._robots.get(robot_id)
        if state is None:
            return _unknown_robot(robot_id)
        if state.robot.role != "MUUT":
            return CommandResult(
                False, f"{robot_id}: role {state.robot.role} cannot move", "ROLE_NOT_ALLOWED"
            )
        now = self._clock.now()
        self._advance(state, now)
        if state.nav_state == "navigating":
            return CommandResult(False, "Already navigating", "ALREADY_NAVIGATING")
        try:
            path = plan_path(self._grid, (state.pose.x, state.pose.y), (x, y))
        except PlanningFailed as failure:
            # Falha assíncrona (ADR-0005): o comando é aceito e o status mostra a falha.
            state.navigation = None
            state.nav_state = "failed"
            state.last_error = "NAV2_REJECTED"
            log.warning(
                "navigation_failed robot=%s destination=(%s, %s) error_code=%s cause=%s",
                robot_id,
                x,
                y,
                state.last_error,
                failure.cause,
                extra={
                    "robot_id": robot_id,
                    "destination": {"x": x, "y": y},
                    "error_code": state.last_error,
                    "cause": failure.cause,
                },
            )
        else:
            state.navigation = Navigation(path, yaw, now)
            state.nav_state = "navigating"
            state.last_error = ""
        return CommandResult(success=True, message="Navigation started")

    def cancel(self, robot_id: str) -> CommandResult:
        state = self._robots.get(robot_id)
        if state is None:
            return _unknown_robot(robot_id)
        self._advance(state, self._clock.now())
        if state.nav_state != "navigating":
            return CommandResult(False, "No active goal", "CANCEL_FAILED")
        # O robô para onde estiver agora; como no orquestrador do Fleet UI, já fica idle.
        state.navigation = None
        state.nav_state = "idle"
        return CommandResult(success=True, message="Cancel requested")

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
_HTTP_STATUS: dict[CommandError, int] = {
    "INVALID_REQUEST": 422,
    "UNKNOWN_ROBOT": 403,
    "ROLE_NOT_ALLOWED": 403,
    "CANCEL_FAILED": 409,
    "ALREADY_NAVIGATING": 409,
}


def _unknown_robot(robot_id: str) -> CommandResult:
    return CommandResult(False, f"Unknown robot {robot_id!r}", "UNKNOWN_ROBOT")
