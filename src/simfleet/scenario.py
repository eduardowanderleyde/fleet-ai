"""Cenário do SimFleet: mapa de ocupação, robôs e lugares nomeados."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simfleet.occupancy import OccupancyGrid

DEFAULT_SCENARIO = Path(__file__).parent / "scenarios" / "warehouse" / "scenario.toml"


class ScenarioError(ValueError):
    """Cenário inválido: o SimFleet não sobe com ele."""


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class Robot:
    id: str
    role: str
    start: Pose
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Place:
    name: str
    synonyms: tuple[str, ...]
    pose: Pose


@dataclass(frozen=True)
class Scenario:
    robots: tuple[Robot, ...]
    places: tuple[Place, ...]


def load_scenario(path: Path) -> Scenario:
    if not path.is_file():
        raise ScenarioError(f"{path}: arquivo de cenário não encontrado")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ScenarioError(f"{path}: TOML inválido: {exc}") from exc
    try:
        image = path.parent / data["map"]["image"]
        map_params = (data["map"]["resolution"], tuple(data["map"]["origin"]))
        inflate_m = data["map"].get("inflate_m", 0.0)
        scenario = _parse_scenario(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioError(f"{path}: cenário malformado: {exc!r}") from exc
    if not image.is_file():
        raise ScenarioError(f"{path}: imagem do mapa não encontrada: {image}")
    grid = OccupancyGrid(image, *map_params, inflate_m=inflate_m)
    _require_unique(path, "id de robô", [robot.id for robot in scenario.robots])
    _require_unique(path, "nome de lugar", [place.name for place in scenario.places])
    _require_unique(
        path, "apelido", [alias for robot in scenario.robots for alias in robot.aliases]
    )
    for robot in scenario.robots:
        if not grid.is_free(robot.start.x, robot.start.y):
            raise ScenarioError(
                f"{path}: robô {robot.id} começa em célula ocupada ou perto demais de obstáculo"
            )
    for place in scenario.places:
        if not grid.is_free(place.pose.x, place.pose.y):
            raise ScenarioError(
                f"{path}: lugar '{place.name}' está em célula ocupada ou perto demais de obstáculo"
            )
    return scenario


def _require_unique(path: Path, kind: str, names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ScenarioError(f"{path}: {kind} repetido: '{name}'")
        seen.add(name)


def _parse_scenario(data: dict[str, Any]) -> Scenario:
    return Scenario(
        robots=tuple(
            Robot(
                id=robot["id"],
                role=robot["role"],
                start=Pose(*robot["start"]),
                aliases=tuple(robot.get("aliases", ())),
            )
            for robot in data["robots"]
        ),
        places=tuple(
            Place(
                name=place["name"],
                synonyms=tuple(place.get("synonyms", ())),
                pose=Pose(place["x"], place["y"], place.get("yaw", 0.0)),
            )
            for place in data.get("places", ())
        ),
    )
