"""O contrato de frota visto pelo Fleet AI (ADR-0005)."""

from dataclasses import dataclass
from typing import Literal, get_args

NavState = Literal["idle", "navigating", "failed"]

# Códigos de recusa de comando do contrato (ADR-0005); "" significa sucesso.
CommandErrorCode = Literal[
    "",
    "INVALID_REQUEST",
    "UNKNOWN_ROBOT",
    "ROLE_NOT_ALLOWED",
    "ALREADY_NAVIGATING",
    "CANCEL_FAILED",
]
COMMAND_ERROR_CODES: frozenset[str] = frozenset(get_args(CommandErrorCode))

# Resultado de um cancelamento, decidido por correlação (ADR-0005).
CancelOutcome = Literal["confirmed", "ambiguous", "not_confirmed"]


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class RobotStatus:
    robot_id: str
    role: str
    nav_state: NavState
    last_error: str
    pose: Pose


@dataclass(frozen=True)
class CommandResponse:
    """Resposta normalizada de um comando: `success`, `message` e `error_code`."""

    success: bool
    message: str
    error_code: CommandErrorCode = ""


class CommandRefused(Exception):
    """O backend recusou o comando; decida pelo `error_code`, não pela mensagem."""

    def __init__(self, error_code: CommandErrorCode, message: str) -> None:
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.message = message


class ExecutorTimeout(Exception):
    """A navegação não terminou dentro do prazo."""


class FleetBackendError(Exception):
    """O backend de frota falhou (indisponível, timeout do serviço); não é uma recusa."""
