import os

from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"

from main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
