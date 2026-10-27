"""Missões: a instrução, os passos executados e o resultado (SPEC-001)."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fleet_ai.contract import ExecutorTimeout, FleetBackendError
from fleet_ai.language import Language, detect_language
from fleet_ai.planning import cancel_text
from fleet_ai.tools import Dispatcher

if TYPE_CHECKING:
    from fleet_ai.executor import Executor
    from fleet_ai.planning import Planner

log = logging.getLogger("fleet_ai.missions")

# Tempo máximo de uma missão e prazo para confirmar o cancelamento depois dele
# (SPEC-001, tabela de guardas).
DEFAULT_MISSION_TIMEOUT = 60.0
DEFAULT_CANCEL_GRACE = 5.0

MissionStatus = Literal[
    "running", "completed", "not_understood", "incomplete", "failed", "rejected"
]


@dataclass
class Mission:
    instruction: str
    robot_id: str | None
    planner: str
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: MissionStatus = "running"
    language: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "instruction": self.instruction,
            "robot_id": self.robot_id,
            "planner": self.planner,
            "language": self.language,
            "steps": self.steps,
            "final_text": self.final_text,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


async def _execute_mission(
    mission: Mission,
    planner: "Planner",
    executor: "Executor",
    *,
    timeout: float = DEFAULT_MISSION_TIMEOUT,
    cancel_grace: float = DEFAULT_CANCEL_GRACE,
) -> None:
    """Executa a missão e garante um status terminal (SPEC-001, encerramento garantido).

    Vale para falhas tratadas com o processo ativo: tempo máximo da missão →
    incomplete, com a navegação em curso cancelada com verificação;
    `ExecutorTimeout` → incomplete; `FleetBackendError` e qualquer outra
    `Exception` → failed; cancelamento da tarefa → failed e repropagado.
    `KeyboardInterrupt` e `SystemExit` não são capturadas. Os passos ficam na
    missão desde o início, então sobrevivem à falha.
    """
    dispatcher = Dispatcher(executor, steps=mission.steps, scope=mission.robot_id)
    deadline = asyncio.timeout(timeout)
    try:
        async with deadline:
            outcome = await planner.run(mission.instruction, mission.robot_id, dispatcher)
    except TimeoutError as exc:
        if not deadline.expired():
            _finish(mission, "failed", "internal_error", f"{type(exc).__name__}: {exc}")
            return
        await _stop_after_timeout(mission, dispatcher, timeout, cancel_grace)
    except ExecutorTimeout as exc:
        _finish(mission, "incomplete", "navigation_timeout", str(exc))
    except FleetBackendError as exc:
        _finish(mission, "failed", "backend_unavailable", str(exc))
    except asyncio.CancelledError:
        _finish(mission, "failed", "cancelled", "mission task cancelled")
        raise
    except Exception as exc:
        _finish(mission, "failed", "internal_error", f"{type(exc).__name__}: {exc}")
        log.exception(
            "mission %s crashed", mission.mission_id, extra={"mission_id": mission.mission_id}
        )
    else:
        mission.language = outcome.language
        mission.final_text = outcome.final_text
        mission.status = outcome.status
        mission.finished_at = datetime.now(UTC)


async def _stop_after_timeout(
    mission: Mission, dispatcher: Dispatcher, timeout: float, cancel_grace: float
) -> None:
    """Tempo máximo estourado: cancela a navegação em curso e relata só o que se sabe."""
    language = detect_language(mission.instruction)
    try:
        cancelled = await dispatcher.cancel_active(cancel_grace)
    except asyncio.CancelledError:
        _finish(mission, "failed", "cancelled", "cancelled while stopping after timeout")
        raise
    except Exception as exc:
        _finish(mission, "failed", "internal_error", f"{type(exc).__name__}: {exc}")
        return
    if cancelled is None:
        stop = _NO_NAVIGATION[language]
    else:
        robot, result = cancelled
        stop = cancel_text(robot, result, language)
    seconds = f"{timeout:g}".replace(".", "," if language == "pt" else ".")
    _finish(
        mission,
        "incomplete",
        "mission_timeout",
        f"{timeout} s; cancel: {cancelled}",
        final_text=f"{_TIMEOUT_TEXT[language].format(seconds=seconds)} {stop}",
    )


_TIMEOUT_TEXT: dict[Language, str] = {
    "pt": "A missão atingiu o tempo máximo de {seconds} s antes de terminar.",
    "en": "The mission reached its time limit of {seconds} s before ending.",
}
_NO_NAVIGATION: dict[Language, str] = {
    "pt": "Nenhuma navegação estava em curso.",
    "en": "No navigation was in progress.",
}


# Textos genéricos de falha, por idioma: nada vindo do backend ou da exceção.
_FAILURE_TEXTS: dict[str, dict[Language, str]] = {
    "navigation_timeout": {
        "pt": (
            "A navegação não terminou dentro do prazo. O robô pode continuar navegando; "
            "confira o estado dele antes de enviar outro destino."
        ),
        "en": (
            "The navigation did not end in time. The robot may still be navigating; "
            "check its state before sending another destination."
        ),
    },
    "backend_unavailable": {
        "pt": "A missão não pôde ser concluída: o backend de frota está indisponível.",
        "en": "The mission could not be completed: the fleet backend is unavailable.",
    },
    "cancelled": {
        "pt": "A missão foi interrompida antes de terminar.",
        "en": "The mission was interrupted before it ended.",
    },
    "internal_error": {
        "pt": "A missão falhou por um erro interno.",
        "en": "The mission failed because of an internal error.",
    },
}


def _finish(
    mission: Mission,
    status: MissionStatus,
    failure: str,
    detail: str,
    *,
    final_text: str | None = None,
) -> None:
    """Encerra a missão com um texto genérico do `failure`, ou com `final_text`."""
    language = detect_language(mission.instruction)
    mission.language = language
    mission.status = status
    mission.final_text = final_text or _FAILURE_TEXTS[failure][language]
    mission.finished_at = datetime.now(UTC)
    log.warning(
        "mission_ended mission_id=%s status=%s failure=%s",
        mission.mission_id,
        status,
        failure,
        extra={
            "mission_id": mission.mission_id,
            "status": status,
            "failure": failure,
            "detail": detail,
        },
    )
