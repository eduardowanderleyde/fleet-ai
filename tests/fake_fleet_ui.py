"""Fake do backend HTTP do Fleet UI, com as respostas brutas de fleet-ui@a57a3b1.

Reproduz o que o adaptador `fleet_ui` precisa traduzir (ADR-0005):

- backend/main.py: `go_to_point(robot_id="", x=0.0, y=0.0, yaw=0.0)` com padrões
  (sem 422 para x ou y ausentes); recusa 403 de `_require_muut` em português
  antes de chamar o ROS; `""` é o robô padrão (MUUT) do modo de robô único;
  respostas `{"success": <o CLI terminou bem>, "message": <texto do CLI>}`.
- backend/ros_bridge.py: o texto do `ros2 service call` é prosa solta seguida de
  "response:" e do repr() Python da resposta do serviço.
- fleet_orchestrator/main.py: `ALREADY_NAVIGATING`, "Navigation started",
  `UNKNOWN_ROBOT`, "No active goal" / `CANCEL_FAILED`, "Cancel requested" (o
  robô já fica idle); falha do Nav2 depois do aceite (`NAV2_REJECTED`) e
  `NAV2_ABORTED` quando o resultado de um objetivo cancelado chega depois.

O movimento é trivial: o robô chega ao destino depois de `arrive_after_reads`
leituras de status. Destinos fora de `bounds` falham com NAV2_REJECTED.
"""

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse


@dataclass
class FakeRobot:
    robot_id: str
    role: str
    x: float
    y: float
    yaw: float = 0.0
    nav_state: str = "idle"
    last_error: str = ""
    goal: tuple[float, float, float] | None = None
    reads_left: int = 0
    abort_pending: bool = False


@dataclass
class FakeFleetUiOptions:
    arrive_after_reads: int = 3
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 3.0, 3.0)
    # Depois de um cancel aceito, a leitura seguinte mostra failed / NAV2_ABORTED.
    abort_after_cancel: bool = False
    # O cancel é aceito, mas o robô continua navegando (para testar timeout).
    cancel_has_no_effect: bool = False
    # A navegação nunca termina (para testar timeout de espera).
    never_arrives: bool = False
    # Status sem "poses", como versões antigas do backend (só "pose").
    legacy_status: bool = False
    # O `ros2 service call` falha (timeout do CLI).
    service_call_times_out: bool = False
    robots: list[FakeRobot] = field(default_factory=list)


def create_fake_fleet_ui(options: FakeFleetUiOptions) -> FastAPI:
    app = FastAPI(title="Fake Fleet UI")
    robots = {robot.robot_id: robot for robot in options.robots}

    def ros_call(service: str, request: str, response: str) -> dict[str, Any]:
        if options.service_call_times_out:
            return {"success": False, "message": "timeout"}
        text = (
            "waiting for service to become available...\n"
            f"requester: making request: fleet_msgs.srv.{service}_Request({request})\n"
            "\n"
            "response:\n"
            f"fleet_msgs.srv.{service}_Response({response})\n"
        )
        return {"success": True, "message": text}

    def advance(robot: FakeRobot) -> None:
        if robot.abort_pending:
            robot.abort_pending = False
            robot.nav_state, robot.last_error = "failed", "NAV2_ABORTED"
            return
        if robot.nav_state != "navigating" or robot.goal is None:
            return
        x, y, yaw = robot.goal
        x0, y0, x1, y1 = options.bounds
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            robot.nav_state, robot.last_error, robot.goal = "failed", "NAV2_REJECTED", None
            return
        if options.never_arrives:
            return
        robot.reads_left -= 1
        if robot.reads_left <= 0:
            robot.x, robot.y, robot.yaw = x, y, yaw
            robot.nav_state, robot.goal = "idle", None

    @app.get("/api/list_robots")
    def list_robots() -> dict[str, list[str]]:
        return {"robot_ids": list(robots)}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        for robot in robots.values():
            advance(robot)
        poses = {
            r.robot_id: {"x": r.x, "y": r.y, "yaw": r.yaw, "valid": True} for r in robots.values()
        }
        payload: dict[str, Any] = {
            "robots": [
                {
                    "robot_id": r.robot_id,
                    "role": r.role,
                    "nav_state": r.nav_state,
                    "current_route": "",
                    "collection_on": False,
                    "collection_file": "",
                    "last_error": r.last_error,
                    "bytes_written": 0,
                }
                for r in robots.values()
            ],
            "nav2_ready": True,
            "pose": next(iter(poses.values())),
        }
        if not options.legacy_status:
            payload["poses"] = poses
            payload["tf_last_rx"] = {}
        return payload

    @app.post("/api/go_to_point", response_model=None)
    def go_to_point(
        robot_id: str = "", x: float = 0.0, y: float = 0.0, yaw: float = 0.0
    ) -> dict[str, Any] | Any:
        request = f"robot_id={robot_id!r}, x={x}, y={y}, yaw={yaw}"
        role = "MUUT" if robot_id == "" else (robots[robot_id].role if robot_id in robots else None)
        if role != "MUUT":
            reason = (
                f"papel '{role}' não permite movimento"
                if role
                else "robot_id não declarado em roles.yaml"
            )
            return JSONResponse(
                {"success": False, "message": f"{robot_id}: {reason}"}, status_code=403
            )
        robot = robots.get(robot_id)
        if robot is None:
            response = "success=False, message='UNKNOWN_ROBOT', error_code='UNKNOWN_ROBOT'"
        elif robot.nav_state == "navigating":
            response = (
                "success=False, message='Already navigating', error_code='ALREADY_NAVIGATING'"
            )
        else:
            robot.goal, robot.reads_left = (x, y, yaw), options.arrive_after_reads
            robot.nav_state, robot.last_error = "navigating", ""
            response = "success=True, message='Navigation started', error_code=''"
        return ros_call("GoToPoint", request, response)

    @app.post("/api/cancel")
    def cancel(robot_id: str = "") -> dict[str, Any]:
        request = f"robot_id={robot_id!r}"
        robot = robots.get(robot_id)
        if robot is None:
            response = "success=False, message='UNKNOWN_ROBOT', error_code='UNKNOWN_ROBOT'"
        elif robot.nav_state != "navigating":
            response = "success=False, message='No active goal', error_code='CANCEL_FAILED'"
        else:
            if not options.cancel_has_no_effect:
                robot.goal, robot.nav_state = None, "idle"
                robot.abort_pending = options.abort_after_cancel
            response = "success=True, message='Cancel requested', error_code=''"
        return ros_call("Cancel", request, response)

    return app
