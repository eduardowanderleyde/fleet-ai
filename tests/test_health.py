from fastapi.testclient import TestClient

from fleet_ai.app import create_app
from simfleet.app import create_app as create_simfleet_app


def test_fleet_ai_is_alive() -> None:
    # `/health` virou readiness e sonda o backend (ticket 11); "o serviço está de pé"
    # é a liveness, que não faz chamada de rede.
    client = TestClient(create_app())

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_simfleet_health_reports_ok() -> None:
    client = TestClient(create_simfleet_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
