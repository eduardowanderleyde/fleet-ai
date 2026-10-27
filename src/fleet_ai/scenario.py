"""Nomes do cenário que o Fleet AI usa para entender instruções.

Lê o mesmo `scenario.toml` do SimFleet, mas só os apelidos dos robôs e os
lugares nomeados; o mapa fica com o SimFleet. Apelidos e lugares não fazem
parte do contrato de frota (ADR-0005).
"""

import os
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

DEFAULT_SCENARIO = Path(str(files("simfleet") / "scenarios" / "warehouse" / "scenario.toml"))


@dataclass(frozen=True)
class RobotNames:
    robot_id: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class PlaceName:
    name: str
    synonyms: tuple[str, ...]
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class ScenarioNames:
    robots: tuple[RobotNames, ...]
    places: tuple[PlaceName, ...]


def load_names(path: Path | None = None) -> ScenarioNames:
    """Sem `path`, usa FLEET_AI_SCENARIO ou, na falta dela, o warehouse."""
    path = path or Path(os.environ.get("FLEET_AI_SCENARIO", DEFAULT_SCENARIO))
    data = tomllib.loads(path.read_text())
    return ScenarioNames(
        robots=tuple(
            RobotNames(robot["id"], tuple(robot.get("aliases", ()))) for robot in data["robots"]
        ),
        places=tuple(
            PlaceName(
                place["name"],
                tuple(place.get("synonyms", ())),
                float(place["x"]),
                float(place["y"]),
                float(place.get("yaw", 0.0)),
            )
            for place in data.get("places", ())
        ),
    )
