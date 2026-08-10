"""Tests for the GET /health endpoint."""

from fastapi.testclient import TestClient
from kalhas.contracts.v1 import API_VERSION
from kalhas.contracts.v1.health import HealthResponse
from kalhas.version import __version__


def test_health_returns_200_and_typed_body(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = HealthResponse.model_validate(response.json())
    assert body.status.value == "ok"
    assert body.service == "kalhas"
    assert body.version == __version__
    assert body.api_version == API_VERSION


def test_health_rejects_unknown_fields(client: TestClient) -> None:
    """The v1 contract is strict: extra fields are forbidden."""
    response = client.get("/health")
    raw = response.json()
    raw["unexpected"] = "x"

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HealthResponse.model_validate(raw)
