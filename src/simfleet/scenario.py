"""Cenário do SimFleet: mapa de ocupação, robôs e lugares nomeados."""

import tomllib
from dataclasses import dataclass, field
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


# Papéis do Fleet UI: só MUUT se move; FUUT e SU são fixos.
ROLES = ("MUUT", "FUUT", "SU")

DEFAULT_SPEED_MPS = 0.3
DEFAULT_PLANNING_RESOLUTION = 0.1


@dataclass(frozen=True)
class Scenario:
    robots: tuple[Robot, ...]
    places: tuple[Place, ...]
    speed_mps: float
    grid: OccupancyGrid = field(compare=False, repr=False)

    @property
    def planning_resolution(self) -> float:
        return self.grid.cell_size


def load_scenario(path: Path) -> Scenario:
    if not path.is_file():
        raise ScenarioError(f"{path}: arquivo de cenário não encontrado")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ScenarioError(f"{path}: TOML inválido: {exc}") from exc
    try:
        image = path.parent / data["map"]["image"]
        resolution = float(data["map"]["resolution"])
        map_params = (resolution, tuple(data["map"]["origin"]))
        inflate_m = data["map"].get("inflate_m", 0.0)
        declared = data["map"].get("planning_resolution")
        robots, places = _parse_robots(data), _parse_places(data)
        speed_mps = float(data.get("simulation", {}).get("speed_mps", DEFAULT_SPEED_MPS))
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioError(f"{path}: cenário malformado: {exc!r}") from exc
    if not image.is_file():
        raise ScenarioError(f"{path}: imagem do mapa não encontrada: {image}")
    factor = _planning_factor(path, resolution, declared)
    grid = OccupancyGrid(image, *map_params, inflate_m=inflate_m, factor=factor)
    scenario = Scenario(robots=robots, places=places, speed_mps=speed_mps, grid=grid)
    _require_unique(path, "id de robô", [robot.id for robot in scenario.robots])
    _require_unique(path, "nome de lugar", [place.name for place in scenario.places])
    _require_unique(
        path, "apelido", [alias for robot in scenario.robots for alias in robot.aliases]
    )
    for robot in scenario.robots:
        if robot.role not in ROLES:
            raise ScenarioError(
                f"{path}: robô {robot.id} tem papel desconhecido '{robot.role}' "
                f"(válidos: {', '.join(ROLES)})"
            )
        if not grid.is_free(robot.start.x, robot.start.y):
            raise ScenarioError(
                f"{path}: robô {robot.id} começa em célula ocupada ou perto demais de obstáculo"
            )
    for place in scenario.places:
        if not grid.is_free(place.pose.x, place.pose.y):
            raise ScenarioError(
                f"{path}: lugar '{place.name}' está em célula ocupada ou perto demais de obstáculo"
            )
        if not grid.is_free_for_planning(place.pose.x, place.pose.y):
            raise ScenarioError(
                f"{path}: lugar '{place.name}' está bloqueado na grade de planejamento "
                f"({grid.cell_size:g} m); afaste-o dos obstáculos"
            )
    return scenario


def _require_unique(path: Path, kind: str, names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ScenarioError(f"{path}: {kind} repetido: '{name}'")
        seen.add(name)


def _parse_robots(data: dict[str, Any]) -> tuple[Robot, ...]:
    return tuple(
        Robot(
            id=robot["id"],
            role=robot["role"],
            start=Pose(*robot["start"]),
            aliases=tuple(robot.get("aliases", ())),
        )
        for robot in data["robots"]
    )


def _parse_places(data: dict[str, Any]) -> tuple[Place, ...]:
    return tuple(
        Place(
            name=place["name"],
            synonyms=tuple(place.get("synonyms", ())),
            pose=Pose(place["x"], place["y"], place.get("yaw", 0.0)),
        )
        for place in data.get("places", ())
    )


def _planning_factor(path: Path, resolution: float, declared: float | None) -> int:
    """Quantos pixels do mapa formam uma célula de planejamento (ADR-0005)."""
    if declared is None:
        return max(1, round(DEFAULT_PLANNING_RESOLUTION / resolution))
    ratio = float(declared) / resolution
    factor = round(ratio)
    if factor < 1 or abs(ratio - factor) > 1e-6:
        raise ScenarioError(
            f"{path}: planning_resolution {declared} não é múltiplo inteiro da resolução "
            f"do mapa ({resolution})"
        )
    return factor
