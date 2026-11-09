from fastapi.testclient import TestClient

from airsight.api.main import create_app
from airsight.api.store import MemoryStore


def test_health_returns_ok() -> None:
    client = TestClient(create_app(store=MemoryStore()))

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
