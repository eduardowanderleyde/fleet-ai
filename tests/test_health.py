from fastapi.testclient import TestClient

from fleet_ai.app import create_app
from simfleet.app import create_app as create_simfleet_app


def test_fleet_ai_health_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_simfleet_health_reports_ok() -> None:
    client = TestClient(create_simfleet_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
