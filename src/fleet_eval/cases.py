"""Casos de avaliação: instrução, escopo opcional e o resultado esperado."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet_ai.scenario import ScenarioNames

CATEGORIES = ("direta", "variacao", "ambigua", "impossivel", "escopo", "injecao")
DEFAULT_CASES = Path(__file__).resolve().parents[2] / "evals" / "cases.toml"


@dataclass(frozen=True)
class Expect:
    """Resultado esperado, verificado por regras (nunca por outro LLM).

    `status`: status finais aceitos. Com destino (`place` ou `point`), uma missão
    `completed` precisa deixar exatamente um robô de `robots` no destino; sem
    destino, ou com outro status aceito, nenhum robô pode se mover. `tools` só
    vale para missões `completed`; `forbidden` vale sempre. `refusal` marca os
    casos em que o certo é não executar nada.
    """

    status: tuple[str, ...]
    robots: tuple[str, ...] = ()
    place: str | None = None
    point: tuple[float, float] | None = None
    tools: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    refusal: bool = False


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    instruction: str
    robot_id: str | None
    expect: Expect


_CASE_KEYS = {"id", "category", "instruction", "robot_id", "expect"}
_EXPECT_KEYS = {"status", "robots", "place", "point", "tools", "forbidden", "refusal"}
_STATUSES = {"completed", "not_understood", "incomplete", "failed"}
_TOOLS = {"list_robots", "get_robot_status", "move_robot", "wait_for_arrival", "cancel_navigation"}


def load_cases(names: ScenarioNames, path: Path = DEFAULT_CASES) -> list[Case]:
    """Lê e valida o arquivo de casos; um caso malformado impede a avaliação."""
    data = tomllib.loads(path.read_text())
    cases = [_case(entry, names) for entry in data.get("cases", [])]
    ids = [case.id for case in cases]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"duplicated case ids: {', '.join(duplicated)}")
    return cases


def _case(entry: dict[str, object], names: ScenarioNames) -> Case:
    case_id = str(entry.get("id", "?"))
    problem = _problem(entry, names)
    if problem:
        raise ValueError(f"case {case_id}: {problem}")
    raw: dict[str, Any] = entry["expect"]  # type: ignore[assignment]  # conferido em _problem
    point = raw.get("point")
    expect = Expect(
        status=tuple(raw["status"]),
        robots=tuple(raw.get("robots", ())),
        place=raw.get("place"),
        point=(float(point[0]), float(point[1])) if point else None,
        tools=tuple(raw.get("tools", ())),
        forbidden=tuple(raw.get("forbidden", ())),
        refusal=bool(raw.get("refusal", False)),
    )
    robot_id = entry.get("robot_id")
    return Case(
        case_id,
        str(entry["category"]),
        str(entry["instruction"]),
        str(robot_id) if robot_id is not None else None,
        expect,
    )


def _problem(entry: dict[str, object], names: ScenarioNames) -> str | None:
    robots = {robot.robot_id for robot in names.robots}
    places = {place.name for place in names.places}
    if set(entry) - _CASE_KEYS or not {"id", "category", "instruction", "expect"} <= set(entry):
        return "unknown or missing fields"
    if entry["category"] not in CATEGORIES:
        return f"unknown category {entry['category']!r}"
    if not isinstance(entry["instruction"], str) or not entry["instruction"].strip():
        return "empty instruction"
    if entry.get("robot_id") is not None and entry["robot_id"] not in robots:
        return "robot_id is not a scenario robot"
    expect = entry["expect"]
    if not isinstance(expect, dict) or set(expect) - _EXPECT_KEYS or "status" not in expect:
        return "expect has unknown or missing fields"
    if not expect["status"] or set(expect["status"]) - _STATUSES:
        return "expect.status must list known statuses"
    if (set(expect.get("tools", ())) | set(expect.get("forbidden", ()))) - _TOOLS:
        return "unknown tool"
    destination = expect.get("place") is not None or expect.get("point") is not None
    if expect.get("place") is not None and expect.get("point") is not None:
        return "place and point are exclusive"
    if expect.get("place") is not None and expect["place"] not in places:
        return f"unknown place {expect['place']!r}"
    if destination and not (expect.get("robots") and set(expect["robots"]) <= robots):
        return "a destination needs robots from the scenario"
    if expect.get("refusal") and destination:
        return "a refusal has no destination"
    return None
