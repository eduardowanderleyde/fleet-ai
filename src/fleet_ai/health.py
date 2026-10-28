"""Readiness do Fleet AI: o backend de frota responde de forma válida (ticket 11).

Verifica acessibilidade e o contrato básico; não certifica que um robô físico esteja
apto ou seguro para navegar (SPEC-001, "Seleção do adaptador e health").
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("fleet_ai.health")

PROBE_TIMEOUT = 2.0
CACHE_SECONDS = 5.0


class Readiness:
    """Sonda o backend com prazo e guarda o resultado por `cache_seconds`.

    Uma única sondagem fica em andamento por vez: chamadas simultâneas, inclusive
    logo depois de o cache expirar, aguardam a mesma tarefa (sem bloquear o event
    loop). Cancelar uma chamada não cancela a sondagem compartilhada, e a tarefa em
    andamento é limpa em qualquer desfecho, então nunca fica pendente.
    """

    def __init__(
        self,
        probe: Callable[[], Awaitable[object]],
        *,
        adapter: str,
        clock: Callable[[], float],
        timeout: float = PROBE_TIMEOUT,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._probe = probe
        self._adapter = adapter
        self._clock = clock
        self._timeout = timeout
        self._cache_seconds = cache_seconds
        self._cached: tuple[float, bool] | None = None  # (fim da sondagem, acessível)
        self._inflight: asyncio.Task[bool] | None = None

    async def reachable(self) -> bool:
        if self._cached is not None and self._clock() - self._cached[0] < self._cache_seconds:
            return self._cached[1]
        if self._inflight is None:
            self._inflight = asyncio.create_task(self._probe_once())
            self._inflight.add_done_callback(self._forget)
        return await asyncio.shield(self._inflight)

    def _forget(self, task: "asyncio.Task[bool]") -> None:
        if self._inflight is task:
            self._inflight = None

    async def _probe_once(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout):
                await self._probe()
            reachable = True
        except Exception as exc:
            # O motivo vai para o log, com o tipo do erro; nunca para a resposta.
            log.warning(
                "readiness_probe_failed adapter=%s error_type=%s",
                self._adapter,
                type(exc).__name__,
                extra={"adapter": self._adapter, "error_type": type(exc).__name__},
            )
            reachable = False
        self._cached = (self._clock(), reachable)
        return reachable
