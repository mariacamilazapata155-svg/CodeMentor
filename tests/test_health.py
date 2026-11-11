"""Pruebas de la capa HTTP.

No levantan red real ni cargan modelos: usan el TestClient de FastAPI.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """GET /health responde 200 con {"status": "ok"}."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
