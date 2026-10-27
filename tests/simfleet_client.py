"""Cliente de teste do SimFleet com relógio manual e leitura do status até o fim."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from simfleet.app import create_app
from simfleet.clock import SteppingClock
from tests.scenarios import OPEN_ROOM, room_scenario, write_scenario

STEP_S = 0.1


def room_client(
    tmp_path: Path, scenario: dict[str, Any] | None = None, drawing: str = OPEN_ROOM
) -> TestClient:
    path = write_scenario(tmp_path, scenario or room_scenario(), drawing)
    return TestClient(create_app(path, clock=SteppingClock(STEP_S)))


def drive(
    client: TestClient, robot_id: str, max_reads: int = 2000
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lê o status até o robô sair de `navigating`; devolve o estado final e as poses vistas."""
    poses = []
    for _ in range(max_reads):
        status = client.get("/api/status").json()
        robot = next(r for r in status["robots"] if r["robot_id"] == robot_id)
        poses.append(status["poses"][robot_id])
        if robot["nav_state"] != "navigating":
            return robot, poses
    raise AssertionError(f"{robot_id} ainda navegando depois de {max_reads} leituras")
