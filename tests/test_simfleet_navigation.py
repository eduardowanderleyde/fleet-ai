import math
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simfleet.app import create_app
from simfleet.clock import SteppingClock
from tests.scenarios import OPEN_ROOM, room_scenario, write_scenario
from tests.simfleet_client import STEP_S, drive, room_client


def test_go_to_point_starts_navigation(tmp_path: Path) -> None:
    app = create_app(write_scenario(tmp_path, room_scenario(), OPEN_ROOM), clock=SteppingClock(0.1))
    client = TestClient(app)

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.0, "y": 0.5})

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Navigation started", "error_code": ""}
    robots = client.get("/api/status").json()["robots"]
    assert robots[0]["nav_state"] == "navigating"


def test_robot_arrives_idle_at_destination_with_requested_yaw(tmp_path: Path) -> None:
    client = room_client(tmp_path)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.0, "y": 1.5, "yaw": 1.2})
    robot, poses = drive(client, "r1")

    assert robot["nav_state"] == "idle"
    assert robot["last_error"] == ""
    final = poses[-1]
    assert math.hypot(final["x"] - 2.0, final["y"] - 1.5) <= 0.05
    assert final["yaw"] == 1.2
    assert len(poses) > 1  # levou tempo simulado, não teletransportou


# Parede vertical em x = 1,5..1,6 m, com porta só no alto (y = 2,5..2,9 m).
WALL_WITH_DOOR = "\n".join(
    ["#" * 30]
    + ["#" + "." * 28 + "#"] * 4
    + ["#" + "." * 14 + "#" + "." * 13 + "#"] * 24
    + ["#" * 30]
)


def pixel(drawing: str, x: float, y: float, resolution: float = 0.1) -> str:
    rows = drawing.splitlines()
    return rows[len(rows) - 1 - math.floor(y / resolution)][math.floor(x / resolution)]


def test_path_goes_around_a_wall_through_the_doorway(tmp_path: Path) -> None:
    client = room_client(tmp_path, drawing=WALL_WITH_DOOR)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    robot, poses = drive(client, "r1")

    assert robot["nav_state"] == "idle"
    assert all(pixel(WALL_WITH_DOOR, p["x"], p["y"]) == "." for p in poses)
    crossing = [p for p in poses if 1.5 <= p["x"] < 1.6]  # coluna da parede
    assert crossing and all(p["y"] >= 2.5 for p in crossing)
    # Reta seria 2 m; pela porta são mais de 4 m. A 1 m/s com passos de 0,1 s:
    assert len(poses) * STEP_S > 4.0


# Sala de 4 x 4 m, parede em x = 2,0..2,1 m com porta de 1 m no alto (y = 2,9..3,9 m).
WIDE_DOOR = "\n".join(
    ["#" * 40]
    + ["#" + "." * 38 + "#"] * 10
    + ["#" + "." * 19 + "#" + "." * 18 + "#"] * 28
    + ["#" * 40]
)


def distance_to_nearest_wall(drawing: str, x: float, y: float, resolution: float = 0.1) -> float:
    rows = drawing.splitlines()
    nearest = math.inf
    for r, row in enumerate(rows):
        for c, char in enumerate(row):
            if char != "#":
                continue
            # Distância do ponto ao quadrado do pixel.
            x0, y0 = c * resolution, (len(rows) - 1 - r) * resolution
            dx = max(x0 - x, 0.0, x - (x0 + resolution))
            dy = max(y0 - y, 0.0, y - (y0 + resolution))
            nearest = min(nearest, math.hypot(dx, dy))
    return nearest


def test_every_observed_pose_is_free_on_the_inflated_map(tmp_path: Path) -> None:
    scenario = room_scenario()
    scenario["map"]["inflate_m"] = 0.3
    scenario["robots"][1]["start"] = [3.5, 0.5, 0.0]
    client = room_client(tmp_path, scenario, WIDE_DOOR)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 3.5, "y": 1.0})
    robot, poses = drive(client, "r1")

    assert robot["nav_state"] == "idle"
    assert min(distance_to_nearest_wall(WIDE_DOOR, p["x"], p["y"]) for p in poses) >= 0.3 - 0.01


def test_open_area_diagonal_is_a_straight_line(tmp_path: Path) -> None:
    client = room_client(tmp_path)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 1.7})
    _, poses = drive(client, "r1")

    # Distância de cada pose à reta de (0,5; 0,5) até (2,5; 1,7).
    (x0, y0), (x1, y1) = (0.5, 0.5), (2.5, 1.7)
    length = math.hypot(x1 - x0, y1 - y0)
    deviation = max(
        abs((x1 - x0) * (y0 - p["y"]) - (x0 - p["x"]) * (y1 - y0)) / length for p in poses
    )
    assert deviation < 1e-6


def _wall_with_narrow_and_wide_gaps() -> str:
    """2 x 2 m em pixels de 0,05 m; parede em x = 1,00..1,05 m.

    Fenda de 1 pixel em y = 0,30..0,35 m (livre no mapa, mais estreita que a
    célula de planejamento de 0,1 m) e passagem larga em y = 1,50..1,90 m.
    """
    rows = []
    for row_from_bottom in reversed(range(40)):
        if row_from_bottom in (0, 39):
            rows.append("#" * 40)
            continue
        gap = row_from_bottom == 6 or 30 <= row_from_bottom < 38
        rows.append("#" + "." * 19 + ("." if gap else "#") + "." * 18 + "#")
    return "\n".join(rows)


NARROW_AND_WIDE_GAPS = _wall_with_narrow_and_wide_gaps()


def test_corridor_narrower_than_a_planning_cell_is_not_used(tmp_path: Path) -> None:
    scenario = room_scenario()
    scenario["map"].update(resolution=0.05, planning_resolution=0.1)
    scenario["robots"] = [{"id": "r1", "role": "MUUT", "start": [0.5, 0.325, 0.0], "aliases": []}]
    client = room_client(tmp_path, scenario, NARROW_AND_WIDE_GAPS)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 1.5, "y": 0.325})
    robot, poses = drive(client, "r1")

    assert robot["nav_state"] == "idle"
    crossing = [p for p in poses if 1.0 <= p["x"] < 1.05]
    assert crossing and all(p["y"] >= 1.5 for p in crossing)


def test_moving_one_robot_leaves_the_others_still(tmp_path: Path) -> None:
    client = room_client(tmp_path)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.0, "y": 0.5})
    drive(client, "r1")

    assert client.get("/api/status").json()["poses"]["r2"] == {
        "x": 2.5,
        "y": 2.5,
        "yaw": 0.0,
        "valid": True,
    }


def test_same_commands_produce_the_same_poses(tmp_path: Path) -> None:
    runs = []
    for attempt in ("a", "b"):
        directory = tmp_path / attempt
        directory.mkdir()
        client = room_client(directory, drawing=WALL_WITH_DOOR)
        client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5, "yaw": 0.3})
        runs.append(drive(client, "r1")[1])

    assert runs[0] == runs[1]


def test_new_destination_while_navigating_is_rejected(tmp_path: Path) -> None:
    client = room_client(tmp_path)
    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": 0.5, "y": 2.5})

    assert response.status_code == 409
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "ALREADY_NAVIGATING"
    _, poses = drive(client, "r1")
    assert math.hypot(poses[-1]["x"] - 2.5, poses[-1]["y"] - 0.5) <= 0.05  # destino original


def test_new_destination_after_arrival_is_accepted(tmp_path: Path) -> None:
    client = room_client(tmp_path)
    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    drive(client, "r1")

    response = client.post("/api/go_to_point", params={"robot_id": "r1", "x": 0.5, "y": 2.5})
    robot, poses = drive(client, "r1")

    assert response.json() == {"success": True, "message": "Navigation started", "error_code": ""}
    assert robot["nav_state"] == "idle"
    assert math.hypot(poses[-1]["x"] - 0.5, poses[-1]["y"] - 2.5) <= 0.05


@pytest.mark.parametrize(("speed", "seconds"), [(0.5, 4.0), (None, 2.0 / 0.3)])
def test_speed_comes_from_the_scenario(tmp_path: Path, speed: float | None, seconds: float) -> None:
    scenario = room_scenario()
    if speed is None:
        del scenario["simulation"]
    else:
        scenario["simulation"]["speed_mps"] = speed
    client = room_client(tmp_path, scenario)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    _, poses = drive(client, "r1")

    # Uma leitura por passo de 0,1 s; o comando também consome um passo.
    assert len(poses) * STEP_S == pytest.approx(seconds, abs=2 * STEP_S)


def test_warehouse_long_route_plans_in_under_a_second() -> None:
    client = TestClient(create_app(clock=SteppingClock(STEP_S)))

    started = time.perf_counter()
    response = client.post("/api/go_to_point", params={"robot_id": "tb1", "x": 2.0, "y": 13.5})
    elapsed = time.perf_counter() - started

    assert response.json()["success"] is True
    robot = client.get("/api/status").json()["robots"][0]
    assert robot["nav_state"] == "navigating"
    assert elapsed < 1.0


def test_time_scale_comes_from_the_service_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIMFLEET_TIME_SCALE", "1000")
    client = TestClient(create_app(write_scenario(tmp_path, room_scenario(), OPEN_ROOM)))

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})
    time.sleep(0.05)  # 50 s simulados; a viagem de 2 m a 1 m/s leva 2 s

    robot = client.get("/api/status").json()["robots"][0]
    assert robot["nav_state"] == "idle"


def test_robot_next_to_an_obstacle_can_still_leave(tmp_path: Path) -> None:
    # Sala de 1,5 m em pixels de 0,05 m, um pixel ocupado em x, y = 0,50..0,55 m, na
    # mesma célula de planejamento (0,1 m) do robô, que está no pixel vizinho.
    rows = OPEN_ROOM.splitlines()
    row = len(rows) - 1 - 10
    rows[row] = rows[row][:10] + "#" + rows[row][11:]
    drawing = "\n".join(rows)
    scenario = room_scenario()
    scenario["map"].update(resolution=0.05, planning_resolution=0.1)
    scenario["robots"] = [{"id": "r1", "role": "MUUT", "start": [0.575, 0.575, 0.0], "aliases": []}]
    client = room_client(tmp_path, scenario, drawing)

    client.post("/api/go_to_point", params={"robot_id": "r1", "x": 0.2, "y": 0.2})
    robot, poses = drive(client, "r1")

    assert robot["nav_state"] == "idle"
    assert all(pixel(drawing, p["x"], p["y"], resolution=0.05) == "." for p in poses)
