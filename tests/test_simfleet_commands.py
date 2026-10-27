"""Recusas, falhas de navegação e cancelamento no contrato normalizado (ADR-0005)."""

import logging
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.scenarios import OPEN_ROOM, room_scenario
from tests.simfleet_client import drive, room_client


@pytest.mark.parametrize(
    "params",
    [
        {"robot_id": "r1", "y": 1.0},
        {"robot_id": "r1", "x": 1.0},
        {"robot_id": "r1", "x": "abc", "y": 1.0},
        {"robot_id": "r1", "x": 1.0, "y": 1.0, "yaw": "north"},
        {"robot_id": "r1", "x": "inf", "y": 1.0},
        {"robot_id": "r1", "x": 1.0, "y": "nan"},
        {"robot_id": "r1", "x": 1.0, "y": 1.0, "yaw": "-inf"},
        {"x": 1.0, "y": 1.0},
    ],
)
def test_malformed_go_to_point_is_rejected_with_invalid_request(
    tmp_path: Path, params: dict[str, str | float]
) -> None:
    client = room_client(tmp_path)
    before = client.get("/api/status").json()

    response = client.post("/api/go_to_point", params=params)

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "INVALID_REQUEST"
    after = client.get("/api/status").json()
    assert after["robots"] == before["robots"]
    assert after["poses"] == before["poses"]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/go_to_point", {"robot_id": "ghost", "x": 1.0, "y": 1.0}),
        ("/api/cancel", {"robot_id": "ghost"}),
    ],
)
def test_unknown_robot_is_rejected(
    tmp_path: Path, path: str, params: dict[str, str | float]
) -> None:
    client = room_client(tmp_path)

    response = client.post(path, params=params)

    assert response.status_code == 403
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "UNKNOWN_ROBOT"


@pytest.mark.parametrize("role", ["FUUT", "SU"])
def test_fixed_robot_cannot_move(tmp_path: Path, role: str) -> None:
    scenario = room_scenario()
    scenario["robots"][1]["role"] = role
    client = room_client(tmp_path, scenario)

    response = client.post("/api/go_to_point", params={"robot_id": "r2", "x": 1.0, "y": 1.0})

    assert response.status_code == 403
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "ROLE_NOT_ALLOWED"
    status = client.get("/api/status").json()
    assert status["poses"]["r2"] == {"x": 2.5, "y": 2.5, "yaw": 0.0, "valid": True}
    assert status["robots"][1]["nav_state"] == "idle"


def _room_with_closed_box() -> str:
    """Sala de 3 x 3 m (0,1 m/px) com uma caixa fechada em x, y = 1,5..2,2 m."""
    rows = [list(row) for row in OPEN_ROOM.splitlines()]
    for row_from_bottom in range(15, 22):
        for col in range(15, 22):
            if row_from_bottom in (15, 21) or col in (15, 21):
                rows[len(rows) - 1 - row_from_bottom][col] = "#"
    return "\n".join("".join(row) for row in rows)


ROOM_WITH_CLOSED_BOX = _room_with_closed_box()

IMPOSSIBLE_DESTINATIONS = {
    "target_occupied": (1.55, 1.85),  # dentro da parede da caixa
    "target_too_close": (1.0, 0.25),  # 0,15 m da parede de baixo, inflação de 0,2 m
    "target_out_of_map": (10.0, 1.0),
    "no_path": (1.85, 1.85),  # livre, mas dentro da caixa fechada
}


def impossible_client(tmp_path: Path) -> TestClient:
    scenario = room_scenario()
    scenario["map"]["inflate_m"] = 0.2
    return room_client(tmp_path, scenario, ROOM_WITH_CLOSED_BOX)


@pytest.mark.parametrize("cause", IMPOSSIBLE_DESTINATIONS)
def test_impossible_destination_fails_asynchronously_with_nav2_rejected(
    tmp_path: Path, cause: str
) -> None:
    client = impossible_client(tmp_path)
    x, y = IMPOSSIBLE_DESTINATIONS[cause]

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": x, "y": y})

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Navigation started", "error_code": ""}
    status = client.get("/api/status").json()
    assert status["robots"][0]["nav_state"] == "failed"
    assert status["robots"][0]["last_error"] == "NAV2_REJECTED"
    assert status["poses"]["r1"] == {"x": 0.5, "y": 0.5, "yaw": 0.0, "valid": True}


EXPECTED_CAUSE = {
    "target_occupied": "target_occupied",
    "target_too_close": "target_occupied",  # ADR-0005: ocupado ou perto demais
    "target_out_of_map": "target_out_of_map",
    "no_path": "no_path",
}


@pytest.mark.parametrize("case", IMPOSSIBLE_DESTINATIONS)
def test_failed_navigation_logs_the_detailed_cause(
    tmp_path: Path, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    client = impossible_client(tmp_path)
    x, y = IMPOSSIBLE_DESTINATIONS[case]

    with caplog.at_level(logging.WARNING, logger="simfleet"):
        client.post("/api/go_to_point", params={"robot_id": "r1", "x": x, "y": y})

    [record] = [r for r in caplog.records if r.getMessage().startswith("navigation_failed")]
    assert record.__dict__["robot_id"] == "r1"
    assert record.__dict__["destination"] == {"x": x, "y": y}
    assert record.__dict__["error_code"] == "NAV2_REJECTED"
    assert record.__dict__["cause"] == EXPECTED_CAUSE[case]


def test_valid_destination_after_failure_arrives_and_clears_last_error(tmp_path: Path) -> None:
    client = impossible_client(tmp_path)
    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 10.0, "y": 1.0})
    assert client.get("/api/status").json()["robots"][0]["nav_state"] == "failed"

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": 1.0, "y": 1.0})
    robot, poses = drive(client, "r1")

    assert response.json()["success"] is True
    assert robot["nav_state"] == "idle"
    assert robot["last_error"] == ""
    assert math.hypot(poses[-1]["x"] - 1.0, poses[-1]["y"] - 1.0) <= 0.05


def test_cancel_stops_the_robot_where_it_is(tmp_path: Path) -> None:
    client = room_client(tmp_path)
    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    for _ in range(5):
        moving = client.get("/api/status").json()["poses"]["r1"]

    response = client.post("/api/cancel", params={"robot_id": "r1"})
    reads = [client.get("/api/status").json() for _ in range(5)]

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Cancel requested", "error_code": ""}
    assert [read["robots"][0]["nav_state"] for read in reads] == ["idle"] * 5
    stopped = reads[0]["poses"]["r1"]
    assert all(read["poses"]["r1"] == stopped for read in reads)
    # Parou no caminho, logo depois de onde estava: no máximo um passo (0,1 s a 1 m/s).
    assert 0.0 <= stopped["x"] - moving["x"] <= 0.1 + 1e-9
    assert stopped["x"] < 2.0


def test_new_destination_after_accepted_cancel_is_accepted(tmp_path: Path) -> None:
    client = room_client(tmp_path)
    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    client.get("/api/status")
    client.post("/api/cancel", params={"robot_id": "r1"})

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": 0.5, "y": 2.5})
    robot, poses = drive(client, "r1")

    assert response.json() == {"success": True, "message": "Navigation started", "error_code": ""}
    assert robot["nav_state"] == "idle"
    assert math.hypot(poses[-1]["x"] - 0.5, poses[-1]["y"] - 2.5) <= 0.05


@pytest.mark.parametrize("initial_state", ["idle", "failed"])
def test_cancel_without_active_navigation_fails_with_cancel_failed(
    tmp_path: Path, initial_state: str
) -> None:
    client = impossible_client(tmp_path)
    if initial_state == "failed":
        client.post("/api/go_to_point", params={"robot_id": "r1", "x": 10.0, "y": 1.0})
    before = client.get("/api/status").json()
    assert before["robots"][0]["nav_state"] == initial_state

    response = client.post("/api/cancel", params={"robot_id": "r1"})

    assert response.status_code == 409
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "CANCEL_FAILED"
    after = client.get("/api/status").json()
    assert after["robots"] == before["robots"]
    assert after["poses"] == before["poses"]
