from fastapi.testclient import TestClient

from wsw_brain.app import create_app


def test_health_endpoint_returns_without_external_services() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_endpoint_exposes_product_identity() -> None:
    client = TestClient(create_app())

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "product": "On Record"}


def test_capabilities_endpoint_describes_supported_api_features() -> None:
    client = TestClient(create_app())

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "product": "On Record",
        "api_version": "v1",
        "features": ["status", "documents", "events"],
    }
