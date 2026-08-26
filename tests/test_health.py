"""The only endpoint that exists in Phase 0."""

from fastapi.testclient import TestClient

from main import create_app


def test_health_reports_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_openapi_is_generated() -> None:
    """The web client is generated from this document (Phase 8 gates it in CI)."""
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
