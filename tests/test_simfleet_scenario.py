from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from simfleet.app import create_app
from simfleet.scenario import DEFAULT_SCENARIO, ScenarioError, load_scenario
from tests.scenarios import OPEN_ROOM, room_scenario, small_scenario, write_scenario


def test_default_scenario_is_the_warehouse_with_two_mobile_robots_and_one_fixed() -> None:
    client = TestClient(create_app())

    status = client.get("/api/status").json()

    assert client.get("/api/list_robots").json() == {"robot_ids": ["tb1", "tb2", "tb3"]}
    assert [(robot["robot_id"], robot["role"]) for robot in status["robots"]] == [
        ("tb1", "MUUT"),
        ("tb2", "MUUT"),
        ("tb3", "FUUT"),
    ]
    # DEFAULT_POSES do launch multi-robô do fleet-ui (via warehouse.yaml, windows-version@9ca98bf)
    assert status["poses"] == {
        "tb1": {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": True},
        "tb2": {"x": 0.0, "y": 2.0, "yaw": 0.0, "valid": True},
        "tb3": {"x": 0.0, "y": 4.0, "yaw": 0.0, "valid": True},
    }


def test_warehouse_has_named_places_in_portuguese_and_english() -> None:
    scenario = load_scenario(DEFAULT_SCENARIO)

    assert len(scenario.places) >= 5
    for place in scenario.places:
        assert place.synonyms, f"{place.name} sem sinônimos"
    assert any(place.name == "doca de carga" for place in scenario.places)
    assert any("loading dock" in place.synonyms for place in scenario.places)


def test_list_robots_returns_scenario_robots_in_order(tmp_path: Path) -> None:
    client = TestClient(create_app(write_scenario(tmp_path, small_scenario())))

    response = client.get("/api/list_robots")

    assert response.status_code == 200
    assert response.json() == {"robot_ids": ["r1", "r2"]}


def test_status_reports_every_robot_idle_at_its_start_pose(tmp_path: Path) -> None:
    client = TestClient(create_app(write_scenario(tmp_path, small_scenario())))

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "robots": [
            {
                "robot_id": "r1",
                "role": "MUUT",
                "nav_state": "idle",
                "current_route": "",
                "collection_on": False,
                "collection_file": "",
                "last_error": "",
                "bytes_written": 0,
            },
            {
                "robot_id": "r2",
                "role": "FUUT",
                "nav_state": "idle",
                "current_route": "",
                "collection_on": False,
                "collection_file": "",
                "last_error": "",
                "bytes_written": 0,
            },
        ],
        "pose": {"x": 1.5, "y": 1.5, "yaw": 0.0, "valid": True},
        "poses": {
            "r1": {"x": 1.5, "y": 1.5, "yaw": 0.0, "valid": True},
            "r2": {"x": 9.5, "y": 5.5, "yaw": 1.57, "valid": True},
        },
    }


def test_scenario_with_missing_map_image_prevents_startup(tmp_path: Path) -> None:
    path = write_scenario(tmp_path, small_scenario())
    (tmp_path / "map.png").unlink()

    with pytest.raises(ScenarioError, match="map.png"):
        create_app(path)


def test_robot_starting_inside_an_obstacle_prevents_startup(tmp_path: Path) -> None:
    scenario = small_scenario()
    scenario["robots"][0]["start"] = [5.5, 3.5, 0.0]

    with pytest.raises(ScenarioError, match="r1"):
        create_app(write_scenario(tmp_path, scenario))


def test_place_within_the_inflation_radius_prevents_startup(tmp_path: Path) -> None:
    scenario = small_scenario()
    scenario["map"]["inflate_m"] = 1.0
    scenario["robots"][0]["start"] = [2.5, 2.5, 0.0]  # longe da parede com a inflação de 1 m
    scenario["places"][0].update(x=4.5, y=3.5)

    with pytest.raises(ScenarioError, match="dock"):
        create_app(write_scenario(tmp_path, scenario))


def test_same_place_without_inflation_is_accepted(tmp_path: Path) -> None:
    scenario = small_scenario()
    scenario["places"][0].update(x=4.5, y=3.5)

    assert create_app(write_scenario(tmp_path, scenario)) is not None


def _duplicate_robot_id(scenario: dict[str, Any]) -> None:
    scenario["robots"][1]["id"] = "r1"


def _duplicate_place_name(scenario: dict[str, Any]) -> None:
    scenario["places"].append({"name": "dock", "synonyms": [], "x": 2.5, "y": 5.5, "yaw": 0.0})


def _alias_shared_by_two_robots(scenario: dict[str, Any]) -> None:
    scenario["robots"][1]["aliases"] = ["robot one"]


@pytest.mark.parametrize(
    ("break_scenario", "repeated"),
    [
        (_duplicate_robot_id, "r1"),
        (_duplicate_place_name, "dock"),
        (_alias_shared_by_two_robots, "robot one"),
    ],
)
def test_repeated_names_prevent_startup(
    tmp_path: Path, break_scenario: Callable[[dict[str, Any]], None], repeated: str
) -> None:
    scenario = small_scenario()
    break_scenario(scenario)

    with pytest.raises(ScenarioError, match=f"repetido.*{repeated}"):
        create_app(write_scenario(tmp_path, scenario))


def test_scenario_is_chosen_by_the_simfleet_scenario_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIMFLEET_SCENARIO", str(write_scenario(tmp_path, small_scenario())))

    client = TestClient(create_app())

    assert client.get("/api/list_robots").json() == {"robot_ids": ["r1", "r2"]}


def test_aliases_and_places_stay_out_of_the_fleet_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(write_scenario(tmp_path, small_scenario())))

    responses = client.get("/api/list_robots").text + client.get("/api/status").text

    for name in ("robot one", "robot two", "dock", "doca"):
        assert name not in responses


# Só o canto superior esquerdo é ocupado: a primeira linha do desenho é o y máximo.
TOP_LEFT_BLOCK_MAP = """
    ############
    ####.......#
    ####.......#
    #..........#
    #..........#
    #..........#
    #..........#
    ############
"""


@pytest.mark.parametrize(("y", "accepted"), [(1.5, True), (6.5, False)])
def test_map_image_top_row_is_the_largest_y(tmp_path: Path, y: float, accepted: bool) -> None:
    scenario = small_scenario()
    scenario["places"][0].update(x=2.5, y=y)
    path = write_scenario(tmp_path, scenario, TOP_LEFT_BLOCK_MAP)

    if accepted:
        create_app(path)
    else:
        with pytest.raises(ScenarioError, match="dock"):
            create_app(path)


def _remove_role(scenario: dict[str, Any]) -> None:
    del scenario["robots"][0]["role"]


def _start_without_yaw(scenario: dict[str, Any]) -> None:
    scenario["robots"][0]["start"] = [1.5, 1.5]


def _place_without_y(scenario: dict[str, Any]) -> None:
    del scenario["places"][0]["y"]


@pytest.mark.parametrize("break_scenario", [_remove_role, _start_without_yaw, _place_without_y])
def test_malformed_scenario_prevents_startup_with_a_clear_message(
    tmp_path: Path, break_scenario: Callable[[dict[str, Any]], None]
) -> None:
    scenario = small_scenario()
    break_scenario(scenario)

    with pytest.raises(ScenarioError, match="scenario.toml: cenário malformado"):
        create_app(write_scenario(tmp_path, scenario))


def test_scenario_that_is_not_valid_toml_prevents_startup(tmp_path: Path) -> None:
    path = write_scenario(tmp_path, small_scenario())
    path.write_text("name = \n")

    with pytest.raises(ScenarioError, match="TOML"):
        create_app(path)


def test_missing_scenario_file_prevents_startup(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="não encontrado"):
        create_app(tmp_path / "nope.toml")


def _scenario_on_a_3_cm_map(planning_resolution: float | None) -> dict[str, Any]:
    scenario = room_scenario()
    scenario["map"]["resolution"] = 0.03
    if planning_resolution is None:
        del scenario["map"]["planning_resolution"]
    else:
        scenario["map"]["planning_resolution"] = planning_resolution
    scenario["robots"] = [{"id": "r1", "role": "MUUT", "start": [0.45, 0.45, 0.0], "aliases": []}]
    return scenario


@pytest.mark.parametrize(("declared", "expected"), [(0.09, 0.09), (0.06, 0.06), (None, 0.09)])
def test_planning_resolution_is_an_integer_multiple_of_the_map_resolution(
    tmp_path: Path, declared: float | None, expected: float
) -> None:
    scenario = load_scenario(write_scenario(tmp_path, _scenario_on_a_3_cm_map(declared), OPEN_ROOM))

    assert scenario.planning_resolution == pytest.approx(expected)


@pytest.mark.parametrize("declared", [0.1, 0.045, 0.0, -0.03])
def test_planning_resolution_that_is_not_a_multiple_prevents_startup(
    tmp_path: Path, declared: float
) -> None:
    path = write_scenario(tmp_path, _scenario_on_a_3_cm_map(declared), OPEN_ROOM)

    with pytest.raises(ScenarioError, match="planning_resolution"):
        create_app(path)


def test_warehouse_plans_on_a_0_09_m_grid() -> None:
    assert load_scenario(DEFAULT_SCENARIO).planning_resolution == pytest.approx(0.09)


def test_place_blocked_only_on_the_planning_grid_prevents_startup(tmp_path: Path) -> None:
    # Sala de 1,5 m em pixels de 0,05 m com um único pixel ocupado em x, y = 0,50..0,55 m.
    rows = OPEN_ROOM.splitlines()
    row = len(rows) - 1 - 10
    rows[row] = rows[row][:10] + "#" + rows[row][11:]
    scenario = room_scenario()
    scenario["map"].update(resolution=0.05, planning_resolution=0.1)
    scenario["robots"] = [{"id": "r1", "role": "MUUT", "start": [0.25, 0.25, 0.0], "aliases": []}]
    # Pixel vizinho, livre no mapa, mas na mesma célula de planejamento de 0,1 m.
    scenario["places"] = [{"name": "pillar", "synonyms": [], "x": 0.575, "y": 0.575, "yaw": 0.0}]

    with pytest.raises(ScenarioError, match="pillar.*planejamento"):
        create_app(write_scenario(tmp_path, scenario, "\n".join(rows)))
