from fastapi.testclient import TestClient

from fxtool.main import app


def test_health_is_up():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
