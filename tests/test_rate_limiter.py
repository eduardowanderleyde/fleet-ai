"""Limpeza oportunista do limitador de taxa (ticket 14; SPEC-001, Guardas).

Os testes observam o estado interno do limitador (`_accepted`), sem API pública
nova de produção (decisão do dono).
"""

from fleet_ai.guards import DAY, Limits, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def tracked(limiter: RateLimiter) -> set[str]:
    return set(limiter._accepted)


def test_querying_an_ip_does_not_track_it() -> None:
    limiter = RateLimiter(Limits(), FakeClock())

    assert limiter.retry_after("198.51.100.1") is None
    assert tracked(limiter) == set()


def test_ips_without_missions_in_the_last_day_are_forgotten() -> None:
    clock = FakeClock()
    limiter = RateLimiter(Limits(), clock)
    limiter.record("198.51.100.1")
    limiter.record("198.51.100.2")

    clock.now += DAY + 1
    limiter.retry_after("203.0.113.9")  # qualquer chamada pode varrer

    assert tracked(limiter) == set()


def test_sweep_runs_at_most_once_per_minute() -> None:
    clock = FakeClock()
    limiter = RateLimiter(Limits(), clock)
    limiter.record("198.51.100.1")  # em t0
    clock.now += 30
    limiter.record("198.51.100.2")  # em t0 + 30 s

    clock.now += DAY - 29  # t0 + 24 h + 1 s: só o primeiro venceu
    limiter.retry_after("203.0.113.9")
    after_first_sweep = tracked(limiter)

    clock.now += 30  # o segundo vence agora, mas faz só 30 s da última varredura
    limiter.retry_after("203.0.113.9")
    within_the_minute = tracked(limiter)

    clock.now += 30  # um minuto depois da última varredura
    limiter.retry_after("203.0.113.9")

    assert after_first_sweep == {"198.51.100.2"}
    assert within_the_minute == {"198.51.100.2"}
    assert tracked(limiter) == set()


def test_cleanup_preserves_minute_and_day_limits() -> None:
    clock = FakeClock()
    limiter = RateLimiter(Limits(missions_per_minute=1, missions_per_day=2), clock)
    limiter.record("198.51.100.1")

    clock.now += 30
    within_the_minute = limiter.retry_after("198.51.100.1")
    clock.now += 31  # passou o minuto; a varredura roda e mantém o IP (tem missão em 24 h)
    limiter.retry_after("203.0.113.9")
    after_the_minute = limiter.retry_after("198.51.100.1")
    limiter.record("198.51.100.1")  # segunda missão do dia
    clock.now += 3600
    limiter.retry_after("203.0.113.9")  # nova varredura

    assert within_the_minute is not None
    assert after_the_minute is None
    assert "198.51.100.1" in tracked(limiter)
    day_wait = limiter.retry_after("198.51.100.1")
    assert day_wait is not None and day_wait > 60  # limite do dia preservado
