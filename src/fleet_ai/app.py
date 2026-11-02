"""Aplicação HTTP do Fleet AI."""

import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx2
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from fleet_ai.config import fleet_adapter_from_env, planner_from_env
from fleet_ai.contract import FleetBackendError
from fleet_ai.executor import Executor
from fleet_ai.guards import (
    Limits,
    RateLimiter,
    client_ip,
    instruction_error,
    positive_float,
    robot_id_error,
)
from fleet_ai.health import PROBE_TIMEOUT, Readiness
from fleet_ai.llm import LlmPort
from fleet_ai.missions import (
    DEFAULT_CANCEL_GRACE,
    DEFAULT_MISSION_TIMEOUT,
    TERMINAL_STATUSES,
    Mission,
    _execute_mission,
)
from fleet_ai.planning import Planner, ScopeGuard
from fleet_ai.scenario import load_names
from fleet_ai.views import FleetViews

log = logging.getLogger("fleet_ai.app")


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
    fleet_transport: httpx2.AsyncBaseTransport | None = None,
    health_probe_timeout: float = PROBE_TIMEOUT,
    llm: LlmPort | None = None,
) -> FastAPI:
    """Sem `executor`, o adaptador vem de FLEET_AI_FLEET_ADAPTER e FLEET_AI_FLEET_URL.

    Sem `planner`, usa o planejador determinístico com os nomes do cenário. Limites,
    tempo máximo e prazo de cancelamento não informados vêm das variáveis FLEET_AI_*
    (ou dos padrões da SPEC-001); um valor inválido impede o serviço de subir.
    """
    fleet = executor or Executor(fleet_adapter_from_env(os.environ, fleet_transport))
    names = load_names()
    active_planner = planner or planner_from_env(os.environ, names, llm)
    scope_guard = ScopeGuard(names)
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
    readiness = Readiness(
        fleet.list_robots, adapter=fleet.adapter_name, clock=clock, timeout=health_probe_timeout
    )
    app = FastAPI(title="Fleet AI")

    @app.exception_handler(RequestValidationError)
    def invalid_body(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(str(error["loc"][-1]) for error in exc.errors())
        return _refusal(422, "invalid_request", f"Invalid request: {fields}")

    @app.exception_handler(StarletteHTTPException)
    def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Erros do próprio framework (rota ou método inexistente) com corpo fixo,
        # sem repetir o caminho pedido (ticket 15).
        error, message = _HTTP_ERRORS.get(exc.status_code, ("http_error", "Request failed"))
        return JSONResponse(
            {"error": error, "message": message},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Corpo fixo, sem stack trace nem texto da exceção; o detalhe fica no log
        # (ticket 15).
        log.error(
            "endpoint_error path=%s error=%s",
            request.url.path,
            type(exc).__name__,
            exc_info=exc,
        )
        return _refusal(500, "internal_error", "Internal error")

    @app.get("/health", response_model=None)
    async def health() -> JSONResponse:
        """Readiness: o backend de frota responde de forma válida (SPEC-001, ticket 11)."""
        reachable = await readiness.reachable()
        body = {
            "status": "ok" if reachable else "degraded",
            "fleet_adapter": fleet.adapter_name,
            "fleet_backend_reachable": reachable,
            "planner": active_planner.name,
            "llm_enabled": False,
        }
        return JSONResponse(body, status_code=200 if reachable else 503)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        """Liveness: o processo responde; nunca consulta o backend de frota."""
        return {"status": "alive"}

    views = FleetViews(fleet, names, clock)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Interface web local (SPEC-003): só pelo túnel SSH, em 127.0.0.1."""
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    @app.get("/v1/fleet", response_model=None)
    async def fleet_view() -> dict[str, Any] | JSONResponse:
        """Robôs com pose, estado e posição no mapa da interface (SPEC-003)."""
        try:
            return await views.fleet()
        except FleetBackendError as exc:
            return _fleet_unavailable(exc)

    @app.get("/v1/map", response_model=None)
    async def map_view() -> dict[str, Any] | JSONResponse:
        try:
            return await views.map_view()
        except FleetBackendError as exc:
            return _fleet_unavailable(exc)

    @app.get("/v1/map/image.png", response_model=None)
    async def map_image() -> Response:
        try:
            state = await views.map_state()
        except FleetBackendError as exc:
            return _fleet_unavailable(exc)
        if state.fleet_map is None:
            return _refusal(404, "map_unavailable", "No map is available for this fleet.")
        return Response(
            state.fleet_map.png,
            media_type="image/png",
            headers={"Cache-Control": "max-age=300", "X-Content-Type-Options": "nosniff"},
        )

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
                mission,
                active_planner,
                fleet,
                timeout=mission_timeout,
                cancel_grace=cancel_grace,
                scope_guard=scope_guard,
            )
        finally:
            running -= 1

    @app.get("/v1/missions")
    def list_missions(limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
        """Histórico: ativas e encerradas, da mais nova para a mais antiga (SPEC-003).

        Só lê o que a retenção guarda (ticket 14); os detalhes ficam no `GET` por id.
        """
        newest = list(missions.values())[::-1][:limit]
        return {"missions": [mission.summary() for mission in newest]}

    @app.get("/v1/missions/{mission_id}", response_model=None)
    async def get_mission(mission_id: str) -> dict[str, object] | JSONResponse:
        mission = missions.get(mission_id)
        if mission is None:
            # Mensagem fixa: não repete o caminho pedido (ticket 15).
            return _refusal(404, "not_found", "Mission not found")
        return mission.as_dict()

    return app


def _fleet_unavailable(exc: FleetBackendError) -> JSONResponse:
    """Texto fixo para a interface; o detalhe vai só para o log, com o tipo do erro."""
    log.warning("fleet_read_failed error_type=%s", type(exc).__name__, extra={"detail": str(exc)})
    return _refusal(503, "fleet_unavailable", "The fleet backend is unavailable.")


_HTTP_ERRORS = {
    404: ("not_found", "Not found"),
    405: ("method_not_allowed", "Method not allowed"),
}


def _refusal(status_code: int, error: str, message: str) -> JSONResponse:
    """Corpo padronizado das recusas da API (SPEC-001): {"error", "message"}."""
    return JSONResponse({"error": error, "message": message}, status_code=status_code)


WEB_DIR = Path(__file__).parent / "web"

# Página e API: nada de origens externas, scripts inline nem enquadramento (SPEC-003).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


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
