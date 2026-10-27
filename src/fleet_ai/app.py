"""Aplicação HTTP do Fleet AI."""

import os
from datetime import UTC, datetime

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fleet_ai.adapters import SimAdapter
from fleet_ai.executor import Executor
from fleet_ai.missions import Mission
from fleet_ai.planning import DeterministicPlanner, Planner
from fleet_ai.scenario import load_names
from fleet_ai.tools import Dispatcher


class MissionRequest(BaseModel):
    instruction: str
    robot_id: str | None = None


def create_app(executor: Executor | None = None, planner: Planner | None = None) -> FastAPI:
    """Sem `executor`, fala com o SimFleet em FLEET_AI_FLEET_URL (padrão localhost:8001).

    Sem `planner`, usa o planejador determinístico com os nomes do cenário.
    """
    fleet = executor or Executor(
        SimAdapter(os.environ.get("FLEET_AI_FLEET_URL", "http://localhost:8001"))
    )
    active_planner = planner or DeterministicPlanner(load_names())
    missions: dict[str, Mission] = {}
    app = FastAPI(title="Fleet AI")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/missions", status_code=202)
    async def create_mission(
        request: MissionRequest, background: BackgroundTasks
    ) -> dict[str, str]:
        mission = Mission(request.instruction, request.robot_id, planner=active_planner.name)
        missions[mission.mission_id] = mission
        background.add_task(run_mission, mission)
        return {"mission_id": mission.mission_id, "status": mission.status}

    async def run_mission(mission: Mission) -> None:
        dispatcher = Dispatcher(fleet)
        outcome = await active_planner.run(mission.instruction, mission.robot_id, dispatcher)
        mission.steps = dispatcher.steps
        mission.language = outcome.language
        mission.final_text = outcome.final_text
        mission.status = outcome.status
        mission.finished_at = datetime.now(UTC)

    @app.get("/v1/missions/{mission_id}", response_model=None)
    async def get_mission(mission_id: str) -> dict[str, object] | JSONResponse:
        mission = missions.get(mission_id)
        if mission is None:
            return JSONResponse(
                {"error": "not_found", "message": f"Mission {mission_id} not found"},
                status_code=404,
            )
        return mission.as_dict()

    return app
