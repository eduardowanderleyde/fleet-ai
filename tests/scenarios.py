"""Cenários pequenos para testes, desenhados como texto.

Cada caractere do mapa é um pixel: '#' é ocupado, '.' é livre. A primeira linha
do texto é o topo do mapa (y máximo), como numa imagem do map_server.
"""

import textwrap
from pathlib import Path
from typing import Any

from PIL import Image

# 12 x 8 pixels de 1 m: paredes na borda e um bloco no meio.
SMALL_MAP = """
    ############
    #..........#
    #..........#
    #....##....#
    #....##....#
    #..........#
    #..........#
    ############
"""


def write_map(directory: Path, drawing: str, name: str = "map.png") -> Path:
    rows = textwrap.dedent(drawing).strip().splitlines()
    image = Image.new("L", (len(rows[0]), len(rows)))
    image.putdata([0 if char == "#" else 254 for row in rows for char in row])
    path = directory / name
    image.save(path)
    return path


def small_scenario() -> dict[str, Any]:
    return {
        "name": "small",
        "map": {"image": "map.png", "resolution": 1.0, "origin": [0.0, 0.0], "inflate_m": 0.0},
        "robots": [
            {"id": "r1", "role": "MUUT", "start": [1.5, 1.5, 0.0], "aliases": ["robot one"]},
            {"id": "r2", "role": "FUUT", "start": [9.5, 5.5, 1.57], "aliases": ["robot two"]},
        ],
        "places": [
            {"name": "dock", "synonyms": ["doca"], "x": 9.5, "y": 1.5, "yaw": 0.0},
        ],
    }


def write_scenario(directory: Path, scenario: dict[str, Any], drawing: str = SMALL_MAP) -> Path:
    write_map(directory, drawing)
    path = directory / "scenario.toml"
    path.write_text(_to_toml(scenario))
    return path


def _to_toml(scenario: dict[str, Any]) -> str:
    lines = [f"name = {_value(scenario['name'])}"]
    for table in ("map", "simulation"):
        if table in scenario:
            lines += ["", f"[{table}]"]
            lines += [f"{key} = {_value(value)}" for key, value in scenario[table].items()]
    for table in ("robots", "places"):
        for item in scenario[table]:
            lines += ["", f"[[{table}]]"]
            lines += [f"{key} = {_value(value)}" for key, value in item.items()]
    return "\n".join(lines) + "\n"


def _value(value: Any) -> str:
    if isinstance(value, str):
        return '"' + value.replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return repr(value)


# Sala aberta de 3 x 3 m em pixels de 0,1 m, com parede na borda.
OPEN_ROOM = "\n".join(["#" * 30] + ["#" + "." * 28 + "#"] * 28 + ["#" * 30])


def room_scenario(**overrides: Any) -> dict[str, Any]:
    """Dois robôs MUUT numa sala aberta, grade de 0,1 m, sem inflação, 1 m/s."""
    scenario: dict[str, Any] = {
        "name": "room",
        "map": {
            "image": "map.png",
            "resolution": 0.1,
            "origin": [0.0, 0.0],
            "inflate_m": 0.0,
            "planning_resolution": 0.1,
        },
        "simulation": {"speed_mps": 1.0},
        "robots": [
            {"id": "r1", "role": "MUUT", "start": [0.5, 0.5, 0.0], "aliases": []},
            {"id": "r2", "role": "MUUT", "start": [2.5, 2.5, 0.0], "aliases": []},
        ],
        "places": [],
    }
    scenario.update(overrides)
    return scenario
