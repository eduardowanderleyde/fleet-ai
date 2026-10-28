"""Missões pela API pública do Fleet AI, contra um SimFleet real em processo."""

import math
from pathlib import Path
from typing import Any

import pytest

from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio


async def test_creating_a_mission_returns_its_id_as_running() -> None:
    async with mission_stack() as stack:
        response = await stack.api.post(
            "/v1/missions", json={"instruction": "leve o tb1 até a doca de carga"}
        )

        assert response.status_code == 202
        assert response.json()["status"] == "running"
        assert response.json()["mission_id"]


async def test_unknown_mission_is_not_found() -> None:
    async with mission_stack() as stack:
        response = await stack.api.get("/v1/missions/does-not-exist")

        assert response.status_code == 404


def warehouse_on_fleet_ui() -> FakeFleetUiOptions:
    """Fake do Fleet UI com os robôs do warehouse, para rodar a aceitação no adaptador fleet_ui."""
    return FakeFleetUiOptions(
        robots=[
            FakeRobot("tb1", "MUUT", 0.0, 0.0),
            FakeRobot("tb2", "MUUT", 0.0, 2.0),
            FakeRobot("tb3", "FUUT", 0.0, 4.0),
        ],
        bounds=(-20.0, -30.0, 20.0, 30.0),
    )


@pytest.fixture(params=["sim", "fleet_ui"])
def backend(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Opções do mission_stack para cada adaptador de frota (ticket 11)."""
    return {} if request.param == "sim" else {"fake_fleet_ui": warehouse_on_fleet_ui()}


async def test_move_to_named_place_completes_with_the_robot_there(
    backend: dict[str, Any],
) -> None:
    async with mission_stack(**backend) as stack:
        mission = await stack.run_mission("leve o tb1 até a doca de carga")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert mission["planner"] == "deterministic"
    assert mission["language"] == "pt"
    assert [step["tool"] for step in mission["steps"]] == [
        "get_robot_status",
        "move_robot",
        "wait_for_arrival",
    ]
    assert not any(step["is_error"] for step in mission["steps"])
    assert mission["steps"][1]["input"] == {"robot_id": "tb1", "x": 2.0, "y": 13.5, "yaw": 0.0}
    # Doca de carga no cenário warehouse: (2,0; 13,5).
    assert math.hypot(pose["x"] - 2.0, pose["y"] - 13.5) <= 0.05
    assert "tb1" in mission["final_text"]
    assert "doca de carga" in mission["final_text"]
    assert "chegou" in mission["final_text"]
    assert "x 2,00 m, y 13,50 m" in mission["final_text"]
    assert mission["finished_at"] is not None


async def test_instruction_without_a_known_intent_is_not_understood() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("faça um café para a equipe")

    assert mission["status"] == "not_understood"
    assert mission["steps"] == []
    assert mission["language"] == "pt"
    assert mission["final_text"].count('"') == 6  # três exemplos entre aspas


async def test_moving_a_fixed_robot_stops_at_the_refusal() -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission("leve o tb3 até a doca de carga")

    assert mission["status"] == "completed"
    assert [step["tool"] for step in mission["steps"]] == ["get_robot_status", "move_robot"]
    refusal = mission["steps"][1]
    assert refusal["is_error"] is True
    assert refusal["result"]["error_code"] == "ROLE_NOT_ALLOWED"
    assert "tb3" in mission["final_text"]
    assert "papel" in mission["final_text"]
    assert "não pode se mover" in mission["final_text"]


async def test_moving_a_robot_that_is_already_navigating_suggests_cancelling_first() -> None:
    async with mission_stack() as stack:
        await stack.fleet.post("/api/go_to_point", params={"robot_id": "tb1", "x": 2.0, "y": -12.0})
        mission = await stack.run_mission("leve o tb1 até a doca de carga")
        status = (await stack.fleet.get("/api/status")).json()

    assert mission["status"] == "completed"
    assert [step["tool"] for step in mission["steps"]] == ["get_robot_status", "move_robot"]
    assert mission["steps"][1]["result"]["error_code"] == "ALREADY_NAVIGATING"
    assert "pare o tb1" in mission["final_text"]
    # O planejador não cancelou: o tb1 continua indo para o destino anterior.
    assert status["robots"][0]["nav_state"] == "navigating"


async def test_unreachable_coordinate_is_accepted_and_reported_as_not_reached() -> None:
    async with mission_stack() as stack:
        # Dentro da estante central do warehouse.
        mission = await stack.run_mission("mova o tb1 para x -2 y -10")

    assert mission["status"] == "completed"
    assert [step["tool"] for step in mission["steps"]] == [
        "get_robot_status",
        "move_robot",
        "wait_for_arrival",
    ]
    assert mission["steps"][1]["is_error"] is False
    assert mission["steps"][1]["input"] == {"robot_id": "tb1", "x": -2.0, "y": -10.0, "yaw": 0.0}
    final = mission["steps"][2]["result"]
    assert (final["nav_state"], final["last_error"]) == ("failed", "NAV2_REJECTED")
    assert "não conseguiu chegar" in mission["final_text"]
    assert "não pôde ser alcançado" in mission["final_text"]


async def test_place_names_come_from_the_scenario_the_fleet_ai_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = tmp_path / "names.toml"
    names.write_text(
        'name = "custom"\n\n'
        '[[robots]]\nid = "tb1"\naliases = ["rover"]\n\n'
        '[[places]]\nname = "hangar"\nsynonyms = []\nx = 2.0\ny = -12.0\n'
    )
    monkeypatch.setenv("FLEET_AI_SCENARIO", str(names))

    async with mission_stack() as stack:
        mission = await stack.run_mission("leve o rover até o hangar")
        pose = (await stack.fleet.get("/api/status")).json()["poses"]["tb1"]

    assert mission["status"] == "completed"
    assert mission["steps"][1]["input"] == {"robot_id": "tb1", "x": 2.0, "y": -12.0, "yaw": 0.0}
    assert math.hypot(pose["x"] - 2.0, pose["y"] + 12.0) <= 0.05
