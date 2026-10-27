"""Tabela de intenções do planejador determinístico (ticket 07).

É o documento vivo do que o Fleet AI entende: cada caso é uma instrução, o idioma
esperado e o plano esperado, observado nos passos da missão pela API pública.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.fake_fleet_ui import FakeFleetUiOptions, FakeRobot
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

Step = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Case:
    instruction: str
    language: str
    plan: list[Step]
    # Trechos que o texto final precisa conter.
    says: list[str] = field(default_factory=list)


LIST: list[Step] = [("list_robots", {})]


def status(robot: str) -> list[Step]:
    return [("get_robot_status", {"robot_id": robot})]


def cancel(robot: str) -> list[Step]:
    return [("cancel_navigation", {"robot_id": robot})]


def move(robot: str, x: float, y: float, yaw: float = 0.0) -> list[Step]:
    return [
        ("get_robot_status", {"robot_id": robot}),
        ("move_robot", {"robot_id": robot, "x": x, "y": y, "yaw": yaw}),
        ("wait_for_arrival", {"robot_id": robot}),
    ]


CASES = [
    # Listar robôs
    Case("liste os robôs", "pt", LIST, ["tb1, tb2, tb3"]),
    Case("Quais robôs existem?", "pt", LIST, ["tb1, tb2, tb3"]),
    Case("mostre a frota", "pt", LIST),
    Case("quais sao os robos da frota", "pt", LIST),
    Case("list the robots", "en", LIST, ["tb1, tb2, tb3"]),
    Case("Which robots are there?", "en", LIST),
    Case("show me the fleet", "en", LIST),
    Case("what robots do you have", "en", LIST),
    # Estado de um robô (tb1 começa parado em (0, 0) no warehouse)
    Case("onde está o tb1?", "pt", status("tb1"), ["tb1", "parado", "x 0,00 m, y 0,00 m"]),
    Case("Qual o estado do robô 2?", "pt", status("tb2"), ["tb2"]),
    Case("posição do tb3", "pt", status("tb3")),
    Case("STATUS DO TB1", "pt", status("tb1")),
    Case("where is tb1?", "en", status("tb1"), ["tb1", "idle", "x 0.00 m, y 0.00 m"]),
    Case("status of robot 2", "en", status("tb2")),
    Case("what is the position of tb3", "en", status("tb3")),
    Case("How is robot one doing?", "en", status("tb1")),
    # Mover até coordenada; yaw em graus na instrução, radianos no contrato
    Case("mova o tb1 para x 1,5 y 2", "pt", move("tb1", 1.5, 2.0), ["x 1,50 y 2,00"]),
    Case("leve o robô 1 até (1; 2,5)", "pt", move("tb1", 1.0, 2.5)),
    Case("mande o TB2 para x=2 y=1 virado para 90 graus", "pt", move("tb2", 2.0, 1.0, math.pi / 2)),
    Case("mova o tb2 para (2, 1)", "pt", move("tb2", 2.0, 1.0)),
    Case("move tb1 to 2.0, 4.0 facing 90", "en", move("tb1", 2.0, 4.0, math.pi / 2)),
    Case("send robot 2 to (1, 1)", "en", move("tb2", 1.0, 1.0), ["x 1.00 y 1.00"]),
    Case("take tb1 to x 1.5 y -1", "en", move("tb1", 1.5, -1.0)),
    Case(
        "drive robot one to (0.5, 3) heading -90 degrees", "en", move("tb1", 0.5, 3.0, -math.pi / 2)
    ),
    # Mover até lugar nomeado (coordenadas do cenário warehouse)
    Case("leve o tb1 até a doca de carga", "pt", move("tb1", 2.0, 13.5), ["chegou"]),
    Case("Mande o ROBÔ 2 para o corredor central", "pt", move("tb2", 2.0, -12.0)),
    Case("mova o robo 1 ate a base", "pt", move("tb1", 0.0, 1.0)),
    Case("envie o tb2 à doca", "pt", move("tb2", 2.0, 13.5)),
    Case("move tb1 to the loading dock", "en", move("tb1", 2.0, 13.5), ["arrived"]),
    Case("send robot two to the central aisle", "en", move("tb2", 2.0, -12.0)),
    Case("Take ROBOT 1 to the base station", "en", move("tb1", 0.0, 1.0)),
    Case("drive tb2 to the east aisle", "en", move("tb2", 10.0, -9.0)),
    # Cancelar (no SimFleet o robô está parado: o backend responde CANCEL_FAILED)
    Case("pare o tb1", "pt", cancel("tb1"), ["havia navegação ativa"]),
    Case("Cancele a navegação do robô 2", "pt", cancel("tb2")),
    Case("interrompa o TB3", "pt", cancel("tb3")),
    Case("parar robo 1", "pt", cancel("tb1")),
    Case("stop tb1", "en", cancel("tb1"), ["no active navigation"]),
    Case("cancel robot two", "en", cancel("tb2")),
    Case("Abort TB2", "en", cancel("tb2")),
    Case("halt robot 1", "en", cancel("tb1")),
    # Idioma: "a" é artigo nos dois idiomas e não decide nada
    Case("send tb2 to a dock", "en", move("tb2", 2.0, 13.5)),
]


def plan_of(mission: dict[str, Any]) -> list[Step]:
    return [(step["tool"], step["input"]) for step in mission["steps"]]


@pytest.mark.parametrize("case", CASES, ids=[case.instruction for case in CASES])
async def test_intent_table(case: Case) -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission(case.instruction)
        again = await stack.run_mission(case.instruction)

    assert plan_of(again) == plan_of(mission)  # mesma instrução, mesmo plano
    assert mission["status"] == "completed", mission["final_text"]
    assert mission["language"] == case.language
    assert plan_of(mission) == case.plan
    for phrase in case.says:
        assert phrase in mission["final_text"]


DOCK = "leve o tb1 até a doca de carga"


def fleet_ui(**overrides: Any) -> FakeFleetUiOptions:
    options = FakeFleetUiOptions(
        robots=[FakeRobot("tb1", "MUUT", 0.0, 0.0)], bounds=(-20.0, -30.0, 20.0, 30.0)
    )
    for name, value in overrides.items():
        setattr(options, name, value)
    return options


CANCEL_TEXTS = {
    ("confirmed", "pt"): ("pare o tb1", "A navegação do tb1 foi cancelada"),
    ("confirmed", "en"): ("stop tb1", "The navigation of tb1 was cancelled"),
    ("ambiguous", "pt"): ("pare o tb1", "não é possível afirmar que foi pelo cancelamento"),
    ("ambiguous", "en"): ("stop tb1", "it is not possible to say it was the cancellation"),
    ("not_confirmed", "pt"): ("pare o tb1", "continua navegando"),
    ("not_confirmed", "en"): ("stop tb1", "is still navigating"),
}


@pytest.mark.parametrize(("outcome", "language"), CANCEL_TEXTS, ids=lambda value: str(value))
async def test_cancel_text_reflects_the_cancellation_outcome(outcome: str, language: str) -> None:
    instruction, phrase = CANCEL_TEXTS[(outcome, language)]
    if outcome == "confirmed":
        # Uma missão anterior deste Fleet AI deixa o tb1 navegando (prazo curto do Executor).
        options, timeout = fleet_ui(never_arrives=True), 0.05
    elif outcome == "ambiguous":
        options, timeout = fleet_ui(), 5.0
    else:
        options, timeout = fleet_ui(never_arrives=True, cancel_has_no_effect=True), 0.05

    async with mission_stack(fake_fleet_ui=options, executor_timeout=timeout) as stack:
        if outcome == "confirmed":
            assert (await stack.run_mission(DOCK))["status"] == "incomplete"
        else:
            # Outro cliente do Fleet UI manda o destino.
            await stack.fleet.post("/api/go_to_point", params={"robot_id": "tb1", "x": 2, "y": 2})
        mission = await stack.run_mission(instruction)

    assert mission["status"] == "completed"
    assert mission["language"] == language
    assert mission["steps"][-1]["result"] == {"outcome": outcome}
    assert phrase in mission["final_text"]
    if outcome != "confirmed":
        assert "cancelada" not in mission["final_text"]
        assert "was cancelled" not in mission["final_text"]


NOT_UNDERSTOOD = {
    # Robô desconhecido: lista os robôs do cenário.
    "leve o tb9 até a doca": ("pt", ["tb1, tb2, tb3"]),
    "move robot 7 to the loading dock": ("en", ["tb1, tb2, tb3"]),
    "onde está o robô 5?": ("pt", ["tb1, tb2, tb3"]),
    # Lugar desconhecido: lista os lugares do cenário.
    "leve o tb1 até o hangar": ("pt", ["base", "doca de carga", "sala noroeste"]),
    "send tb1 to the garage": ("en", ["base", "doca de carga", "sala noroeste"]),
    # Mais de uma ação por missão.
    "vá até a doca e depois até a base": ("pt", ["uma ação por missão"]),
    "leve o tb1 até a doca e depois para a base": ("pt", ["uma ação por missão"]),
    "move tb1 to the dock then to the base": ("en", ["one action per mission"]),
    "pare o tb1 e mande o tb2 para a base": ("pt", ["uma ação por missão"]),
    "stop tb1 and list the robots": ("en", ["one action per mission"]),
    # Sem nenhuma palavra que indique o idioma: inglês.
    "tb1?": ("en", []),
}


@pytest.mark.parametrize("instruction", NOT_UNDERSTOOD)
async def test_unknown_names_and_multiple_actions_are_not_understood(instruction: str) -> None:
    language, phrases = NOT_UNDERSTOOD[instruction]

    async with mission_stack() as stack:
        mission = await stack.run_mission(instruction)

    assert mission["status"] == "not_understood"
    assert mission["steps"] == []
    assert mission["language"] == language
    for phrase in phrases:
        assert phrase in mission["final_text"]


@pytest.mark.parametrize(
    ("instruction", "language"), [("faça um café para mim", "pt"), ("make me a coffee", "en")]
)
async def test_examples_offered_when_not_understood_are_understood(
    instruction: str, language: str
) -> None:
    async with mission_stack() as stack:
        mission = await stack.run_mission(instruction)
        examples = re.findall(r'"([^"]+)"', mission["final_text"])
        results = [await stack.run_mission(example) for example in examples]

    assert mission["status"] == "not_understood"
    assert mission["language"] == language
    assert len(examples) == 3
    assert [result["status"] for result in results] == ["completed"] * 3
    assert {result["language"] for result in results} == {mission["language"]}
