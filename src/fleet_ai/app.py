"""Aplicação HTTP do Fleet AI."""

import os
import time
from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fleet_ai.adapters import SimAdapter
from fleet_ai.executor import Executor
from fleet_ai.guards import (
    Limits,
    RateLimiter,
    client_ip,
    instruction_error,
    positive_float,
    robot_id_error,
)
from fleet_ai.missions import (
    DEFAULT_CANCEL_GRACE,
    DEFAULT_MISSION_TIMEOUT,
    TERMINAL_STATUSES,
    Mission,
    _execute_mission,
)
from fleet_ai.planning import DeterministicPlanner, Planner
from fleet_ai.scenario import load_names


class MissionRequest(BaseModel):
    instruction: str
    robot_id: str | None = None


def create_app(
    executor: Executor | None = None,
    planner: Planner | None = None,
    *,
    mission_timeout: float | None = None,
    cancel_grace: float | None = None,
    limits: Limits | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """Sem `executor`, fala com o SimFleet em FLEET_AI_FLEET_URL (padrão localhost:8001).

    Sem `planner`, usa o planejador determinístico com os nomes do cenário. Limites,
    tempo máximo e prazo de cancelamento não informados vêm das variáveis FLEET_AI_*
    (ou dos padrões da SPEC-001); um valor inválido impede o serviço de subir.
    """
    fleet = executor or Executor(
        SimAdapter(os.environ.get("FLEET_AI_FLEET_URL", "http://localhost:8001"))
    )
    active_planner = planner or DeterministicPlanner(load_names())
    guard_limits = limits or Limits.from_env(os.environ)
    mission_timeout = mission_timeout or positive_float(
        os.environ, "FLEET_AI_MISSION_TIMEOUT", DEFAULT_MISSION_TIMEOUT
    )
    cancel_grace = cancel_grace or positive_float(
        os.environ, "FLEET_AI_CANCEL_GRACE", DEFAULT_CANCEL_GRACE
    )
    rate = RateLimiter(guard_limits, clock)
    running = 0  # missões em execução agora (limite global de concorrência)
    missions: dict[str, Mission] = {}
    app = FastAPI(title="Fleet AI")

    @app.exception_handler(RequestValidationError)
    def invalid_body(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(str(error["loc"][-1]) for error in exc.errors())
        return _refusal(422, "invalid_request", f"Invalid request: {fields}")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/missions", status_code=202, response_model=None)
    async def create_mission(
        request: MissionRequest, http: Request, background: BackgroundTasks
    ) -> dict[str, str] | JSONResponse:
        nonlocal running
        # Admissão atômica (SPEC-001, ticket 14): daqui até a inserção da missão não
        # há nenhum `await`, então duas requisições nunca se intercalam entre "há vaga"
        # e "ocupei a vaga". Vale para um processo com um event loop.
        problem = instruction_error(request.instruction, guard_limits) or robot_id_error(
            request.robot_id
        )
        if problem is not None:
            return _refusal(422, "invalid_request", problem)
        peer = http.client.host if http.client else "unknown"
        ip = client_ip(peer, http.headers.get("x-forwarded-for"), guard_limits.trusted_proxies)
        wait = rate.retry_after(ip)
        if wait is not None:
            return _retry_later("rate_limited", "Too many missions from this address.", wait)
        if running >= guard_limits.max_concurrent:
            return _retry_later("too_many_missions", "Too many missions running; try again.", 1)
        full = len(missions) >= guard_limits.missions_retained
        if full and not _drop_oldest_terminal(missions):
            return _retry_later(
                "capacity_exhausted",
                "No room for more missions right now; try again later.",
                CAPACITY_RETRY_AFTER,
                status_code=503,
            )
        rate.record(ip)
        mission = Mission(request.instruction, request.robot_id, planner=active_planner.name)
        missions[mission.mission_id] = mission
        running += 1
        background.add_task(run_mission, mission)
        return {"mission_id": mission.mission_id, "status": mission.status}

    async def run_mission(mission: Mission) -> None:
        nonlocal running
        try:
            await _execute_mission(
                mission, active_planner, fleet, timeout=mission_timeout, cancel_grace=cancel_grace
            )
        finally:
            running -= 1

    @app.get("/v1/missions/{mission_id}", response_model=None)
    async def get_mission(mission_id: str) -> dict[str, object] | JSONResponse:
        mission = missions.get(mission_id)
        if mission is None:
            return _refusal(404, "not_found", f"Mission {mission_id} not found")
        return mission.as_dict()

    return app


def _refusal(status_code: int, error: str, message: str) -> JSONResponse:
    """Corpo padronizado das recusas da API (SPEC-001): {"error", "message"}."""
    return JSONResponse({"error": error, "message": message}, status_code=status_code)


# Estimativa, não garantia, de quando haverá capacidade de retenção (SPEC-001).
CAPACITY_RETRY_AFTER = 5


def _retry_later(
    error: str, message: str, retry_after: int, *, status_code: int = 429
) -> JSONResponse:
    """Recusa com o `Retry-After` em segundos (SPEC-001): 429 por padrão, 503 por capacidade."""
    refusal = _refusal(status_code, error, message)
    refusal.headers["Retry-After"] = str(retry_after)
    return refusal


def _drop_oldest_terminal(missions: dict[str, Mission]) -> bool:
    """Tira da memória a missão terminal mais antiga; missões `running` nunca saem."""
    for mission_id, mission in missions.items():
        if mission.status in TERMINAL_STATUSES:
            del missions[mission_id]
            return True
    return False
