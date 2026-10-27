"""Porta de planejador e o planejador determinístico (ADR-0004, SPEC-001).

O planejador determinístico reconhece intenções por regras, sem modelo de
linguagem, monta um plano fixo e o executa pelo despachante.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fleet_ai.scenario import ScenarioNames
from fleet_ai.tools import Dispatcher

Language = Literal["pt", "en"]
PlanStatus = Literal["completed", "not_understood"]


@dataclass(frozen=True)
class Destination:
    """Para onde mandar o robô: um lugar nomeado ou uma coordenada."""

    label: str
    x: float
    y: float
    yaw: float = 0.0


@dataclass(frozen=True)
class PlanOutcome:
    status: PlanStatus
    language: Language
    final_text: str


class Planner(Protocol):
    name: str

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome: ...


_PT_WORDS = {"leve", "levar", "mova", "mande", "envie", "va", "ate", "para", "o", "a", "robo"}
_EN_WORDS = {"move", "send", "take", "go", "drive", "to", "the", "robot"}
_MOVE_VERBS = {
    "leve",
    "levar",
    "mova",
    "mover",
    "mande",
    "envie",
    "va",
    "move",
    "send",
    "take",
    "go",
    "drive",
}

_EXAMPLES: dict[Language, tuple[str, ...]] = {
    "pt": (
        "leve o tb1 até a doca de carga",
        "mande o tb2 para o corredor central",
        "mova o robô 1 até a base",
    ),
    "en": (
        "move tb1 to the loading dock",
        "send tb2 to the central aisle",
        "take robot 1 to the base",
    ),
}


class DeterministicPlanner:
    name = "deterministic"

    def __init__(self, names: ScenarioNames) -> None:
        self._robots = {
            _normalize(alias): robot.robot_id
            for robot in names.robots
            for alias in (robot.robot_id, *robot.aliases)
        }
        self._places = {
            _normalize(alias): Destination(place.name, place.x, place.y, place.yaw)
            for place in names.places
            for alias in (place.name, *place.synonyms)
        }

    async def run(
        self, instruction: str, robot_id: str | None, dispatcher: Dispatcher
    ) -> PlanOutcome:
        text = _normalize(instruction)
        language = _language(text)
        robot = _find(text, self._robots)
        destination = _coordinate(text) or _find(text, self._places)
        if robot is None or destination is None or not (_words(text) & _MOVE_VERBS):
            return PlanOutcome("not_understood", language, _not_understood(language))
        return await _move_to(robot, destination, language, dispatcher)


async def _move_to(
    robot: str, destination: Destination, language: Language, dispatcher: Dispatcher
) -> PlanOutcome:
    await dispatcher.call("get_robot_status", {"robot_id": robot})
    move, refused = await dispatcher.call(
        "move_robot",
        {"robot_id": robot, "x": destination.x, "y": destination.y, "yaw": destination.yaw},
    )
    if refused:
        return PlanOutcome("completed", language, _refused(robot, move["error_code"], language))
    final, _ = await dispatcher.call("wait_for_arrival", {"robot_id": robot})
    if final["nav_state"] == "failed":
        text = _not_reached(robot, destination.label, final["last_error"], language)
    else:
        text = _arrived(robot, destination.label, final, language)
    return PlanOutcome("completed", language, text)


def _arrived(robot: str, label: str, final: dict[str, Any], language: Language) -> str:
    x, y = final["pose"]["x"], final["pose"]["y"]
    if language == "pt":
        return (
            f'O {robot} chegou ao destino "{label}". '
            f"Pose final: x {_decimal(x, ',')} m, y {_decimal(y, ',')} m."
        )
    return f'{robot} arrived at "{label}". Final pose: x {_decimal(x)} m, y {_decimal(y)} m.'


def _not_reached(robot: str, label: str, last_error: str, language: Language) -> str:
    if language == "pt":
        return (
            f'O {robot} não conseguiu chegar a "{label}": '
            f"o destino não pôde ser alcançado ({last_error})."
        )
    return f'{robot} did not reach "{label}": the destination could not be reached ({last_error}).'


_NUMBER = r"(-?\d+(?:[.,]\d+)?)"


def _coordinate(text: str) -> Destination | None:
    """Coordenada na forma "x 3,5 y -1" (as demais formas são do ticket 07)."""
    match = re.search(rf"\bx\s*{_NUMBER}\s*,?\s*y\s*{_NUMBER}", text)
    if match is None:
        return None
    x, y = (float(group.replace(",", ".")) for group in match.groups())
    return Destination(f"x {match.group(1)} y {match.group(2)}", x, y)


# Por que o backend recusou o comando, pelo `error_code` (ADR-0005).
_REFUSALS: dict[str, dict[Language, str]] = {
    "ROLE_NOT_ALLOWED": {
        "pt": "O {robot} não pode se mover: o papel dele na frota não permite movimento.",
        "en": "{robot} cannot move: its role in the fleet does not allow movement.",
    },
    "ALREADY_NAVIGATING": {
        "pt": (
            "O {robot} já está navegando para outro destino. "
            'Para mudar o destino, cancele antes: "pare o {robot}".'
        ),
        "en": (
            "{robot} is already navigating to another destination. "
            'To change it, cancel first: "stop {robot}".'
        ),
    },
}


def _refused(robot: str, error_code: str, language: Language) -> str:
    templates = _REFUSALS.get(error_code)
    if templates is not None:
        return templates[language].format(robot=robot)
    if language == "pt":
        return f"O comando para o {robot} foi recusado ({error_code})."
    return f"The command for {robot} was refused ({error_code})."


def _not_understood(language: Language) -> str:
    examples = "; ".join(f'"{example}"' for example in _EXAMPLES[language])
    if language == "pt":
        return f"Não entendi a instrução. Exemplos do que posso fazer: {examples}."
    return f"I did not understand the instruction. Examples of what I can do: {examples}."


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in stripped if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def _language(text: str) -> Language:
    words = _words(text)
    return "pt" if len(words & _PT_WORDS) > len(words & _EN_WORDS) else "en"


def _find[T](text: str, names: dict[str, T]) -> T | None:
    """O nome mais longo que aparece como palavras inteiras no texto."""
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            return names[name]
    return None


def _decimal(value: float, separator: str = ".") -> str:
    return f"{value:.2f}".replace(".", separator)
