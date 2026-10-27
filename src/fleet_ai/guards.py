"""Guardas da API de missões: entrada, taxa por IP e concorrência (SPEC-001, ticket 09).

Recusam pedidos antes de qualquer planejamento. Estado em memória, para um processo.
"""

import math
import re
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

# Formato de um robot_id de escopo: o dos ids do cenário (tb1, robot_2, a-1).
_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


@dataclass(frozen=True)
class Limits:
    """Limites das guardas; os padrões são os da tabela de guardas da SPEC-001."""

    max_instruction_chars: int = 300
    missions_per_minute: int = 10
    missions_per_day: int = 100
    max_concurrent: int = 4
    missions_retained: int = 500
    trusted_proxies: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Limits":
        """Limites das variáveis FLEET_AI_*; as ausentes ficam com o padrão."""
        defaults = cls()
        proxies = environ.get("FLEET_AI_TRUSTED_PROXIES", "")
        return cls(
            max_instruction_chars=_positive_int(
                environ, "FLEET_AI_MAX_INSTRUCTION_CHARS", defaults.max_instruction_chars
            ),
            missions_per_minute=_positive_int(
                environ, "FLEET_AI_MISSIONS_PER_MINUTE", defaults.missions_per_minute
            ),
            missions_per_day=_positive_int(
                environ, "FLEET_AI_MISSIONS_PER_DAY", defaults.missions_per_day
            ),
            max_concurrent=_positive_int(
                environ, "FLEET_AI_MAX_CONCURRENT", defaults.max_concurrent
            ),
            missions_retained=_positive_int(
                environ, "FLEET_AI_MISSIONS_RETAINED", defaults.missions_retained
            ),
            trusted_proxies=frozenset(p.strip() for p in proxies.split(",") if p.strip()),
        )


def positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    """Número positivo de uma variável de ambiente, ou o padrão se ela não existe."""
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive number, got {raw!r}") from None
    if not value > 0:
        raise ValueError(f"{name} must be a positive number, got {raw!r}")
    return value


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    if not raw.strip().isdigit() or int(raw) < 1:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return int(raw)


def instruction_error(instruction: str, limits: Limits) -> str | None:
    """Motivo da recusa da instrução, ou None se ela é aceitável."""
    if not instruction.strip():
        return "Instruction is empty."
    if len(instruction) > limits.max_instruction_chars:
        return f"Instruction is longer than {limits.max_instruction_chars} characters."
    return None


def robot_id_error(robot_id: str | None) -> str | None:
    """Motivo da recusa do robot_id de escopo, ou None se ele é aceitável."""
    if robot_id is None or _ROBOT_ID.fullmatch(robot_id):
        return None
    return "robot_id must have 1 to 32 letters, digits, '_' or '-'."


MINUTE = 60.0
DAY = 24 * 60 * 60.0


class RateLimiter:
    """Missões aceitas por IP em janelas deslizantes de um minuto e de um dia."""

    def __init__(self, limits: Limits, clock: Callable[[], float]) -> None:
        self._windows = ((MINUTE, limits.missions_per_minute), (DAY, limits.missions_per_day))
        self._clock = clock
        self._accepted: defaultdict[str, deque[float]] = defaultdict(deque)

    def retry_after(self, ip: str) -> int | None:
        """Segundos até o IP poder criar outra missão, ou None se ele já pode."""
        now = self._clock()
        accepted = self._accepted[ip]
        while accepted and accepted[0] <= now - DAY:
            accepted.popleft()
        waits = []
        for window, limit in self._windows:
            recent = [moment for moment in accepted if moment > now - window]
            if len(recent) >= limit:
                waits.append(recent[-limit] + window - now)
        return max(1, math.ceil(max(waits))) if waits else None

    def record(self, ip: str) -> None:
        self._accepted[ip].append(self._clock())


def client_ip(peer: str, forwarded_for: str | None, trusted_proxies: frozenset[str]) -> str:
    """IP do cliente para as guardas (SPEC-001).

    `X-Forwarded-For` só vale se a conexão vier de um proxy confiável; nesse caso,
    vale o endereço mais à direita que não é de um proxy confiável, porque o que
    está à esquerda pode ter sido escrito pelo próprio cliente.
    """
    if peer not in trusted_proxies or not forwarded_for:
        return peer
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop not in trusted_proxies:
            return hop
    return hops[0] if hops else peer
