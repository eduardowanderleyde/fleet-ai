"""Aplicação HTTP do SimFleet: o contrato de frota sobre um cenário."""

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from simfleet.clock import Clock, ScaledClock
from simfleet.fleet import CommandResult, Fleet, RobotState
from simfleet.scenario import DEFAULT_SCENARIO, Pose, load_scenario


def create_app(scenario_path: Path | None = None, clock: Clock | None = None) -> FastAPI:
    """Sem `scenario_path`, usa SIMFLEET_SCENARIO ou, na falta dela, o warehouse.

    Sem `clock`, usa o relógio real com o fator SIMFLEET_TIME_SCALE (padrão 1).
    """
    scenario = load_scenario(
        scenario_path or Path(os.environ.get("SIMFLEET_SCENARIO", DEFAULT_SCENARIO))
    )
    fleet = Fleet(scenario, clock or ScaledClock(float(os.environ.get("SIMFLEET_TIME_SCALE", "1"))))
    app = FastAPI(title="SimFleet")

    @app.exception_handler(RequestValidationError)
    def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(str(error["loc"][-1]) for error in exc.errors())
        return _command_response(
            CommandResult(False, f"Invalid request: {fields}", "INVALID_REQUEST")
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/list_robots")
    def list_robots() -> dict[str, list[str]]:
        return {"robot_ids": [robot.id for robot in scenario.robots]}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        robots = fleet.robots()
        poses = {state.robot.id: _pose_view(state.pose) for state in robots}
        return {
            "robots": [_robot_view(state) for state in robots],
            "pose": next(iter(poses.values()), _EMPTY_POSE),
            "poses": poses,
        }

    @app.post("/api/go_to_point")
    def go_to_point(robot_id: str, x: float, y: float, yaw: float = 0.0) -> JSONResponse:
        return _command_response(fleet.go_to_point(robot_id, x, y, yaw))

    @app.post("/api/cancel")
    def cancel(robot_id: str) -> JSONResponse:
        return _command_response(fleet.cancel(robot_id))

    return app


# Mesmo formato e valores padrão do status do Fleet UI (fleet-ui@a57a3b1, backend/main.py).
_EMPTY_POSE = {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": False}


def _command_response(result: CommandResult) -> JSONResponse:
    return JSONResponse(result.as_dict(), status_code=result.http_status)


def _pose_view(pose: Pose) -> dict[str, Any]:
    return {"x": pose.x, "y": pose.y, "yaw": pose.yaw, "valid": True}


def _robot_view(state: RobotState) -> dict[str, Any]:
    return {
        "robot_id": state.robot.id,
        "role": state.robot.role,
        "nav_state": state.nav_state,
        "current_route": "",
        "collection_on": False,
        "collection_file": "",
        "last_error": state.last_error,
        "bytes_written": 0,
    }
