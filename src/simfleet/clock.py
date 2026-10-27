"""Relógio simulado do SimFleet."""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Segundos simulados desde um instante arbitrário."""
        ...


class ScaledClock:
    """Relógio real multiplicado por um fator de escala (produção)."""

    def __init__(self, scale: float = 1.0) -> None:
        self._scale = scale
        self._start = time.monotonic()

    def now(self) -> float:
        return (time.monotonic() - self._start) * self._scale


class SteppingClock:
    """Relógio de teste: cada leitura avança um passo fixo, sem esperas reais.

    O SimFleet lê o relógio uma vez por requisição, então cada leitura de status
    avança a simulação exatamente um passo.
    """

    def __init__(self, step: float) -> None:
        self._step = step
        self._now = 0.0

    def now(self) -> float:
        self._now += self._step
        return self._now
