"""Tests for the GET /v1/system-info endpoint."""

import pytest
from fastapi.testclient import TestClient
from kalhas.api.app import create_app
from kalhas.contracts.v1 import API_VERSION
from kalhas.contracts.v1.common import RuntimeMode
from kalhas.contracts.v1.system_info import SystemInfoResponse
from kalhas.version import __version__
from pydantic import ValidationError


def test_system_info_returns_expected_metadata(client: TestClient) -> None:
    response = client.get("/v1/system-info")

    assert response.status_code == 200
    body = SystemInfoResponse.model_validate(response.json())
    assert body.service == "kalhas"
    assert body.application_version == __version__
    assert body.api_version == API_VERSION
    assert body.runtime_mode == RuntimeMode.DEVELOPMENT
    assert body.standalone is True
    assert "integration-free" in body.note


def test_system_info_respects_runtime_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KALHAS_RUNTIME_MODE", "test")
    with TestClient(create_app()) as test_client:
        body = SystemInfoResponse.model_validate(test_client.get("/v1/system-info").json())
    assert body.runtime_mode == RuntimeMode.TEST


def test_system_info_contract_rejects_unknown_fields() -> None:
    """The v1 contract is strict: extra fields are forbidden."""
    with pytest.raises(ValidationError):
        SystemInfoResponse.model_validate(
            {
                "application_version": "0.1.0",
                "api_version": "1",
                "runtime_mode": "development",
                "bogus": 1,
            }
        )


def test_openapi_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    openapi = client.get("/openapi.json").json()
    assert "/health" in openapi["paths"]
    assert "/v1/system-info" in openapi["paths"]
