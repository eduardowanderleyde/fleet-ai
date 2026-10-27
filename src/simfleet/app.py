"""Aplicação HTTP do SimFleet: o contrato de frota sobre um cenário."""

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from simfleet.scenario import DEFAULT_SCENARIO, Pose, Robot, load_scenario


def create_app(scenario_path: Path | None = None) -> FastAPI:
    """Sem `scenario_path`, usa SIMFLEET_SCENARIO ou, na falta dela, o warehouse."""
    scenario = load_scenario(
        scenario_path or Path(os.environ.get("SIMFLEET_SCENARIO", DEFAULT_SCENARIO))
    )
    app = FastAPI(title="SimFleet")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/list_robots")
    def list_robots() -> dict[str, list[str]]:
        return {"robot_ids": [robot.id for robot in scenario.robots]}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        poses = {robot.id: _pose_view(robot.start) for robot in scenario.robots}
        return {
            "robots": [_robot_view(robot) for robot in scenario.robots],
            "pose": next(iter(poses.values()), _EMPTY_POSE),
            "poses": poses,
        }

    return app


# Mesmo formato e valores padrão do status do Fleet UI (fleet-ui@a57a3b1, backend/main.py).
_EMPTY_POSE = {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": False}


def _pose_view(pose: Pose) -> dict[str, Any]:
    return {"x": pose.x, "y": pose.y, "yaw": pose.yaw, "valid": True}


def _robot_view(robot: Robot) -> dict[str, Any]:
    return {
        "robot_id": robot.id,
        "role": robot.role,
        "nav_state": "idle",
        "current_route": "",
        "collection_on": False,
        "collection_file": "",
        "last_error": "",
        "bytes_written": 0,
    }
