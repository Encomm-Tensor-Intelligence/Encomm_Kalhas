"""Tests for the consistent typed API error shape."""

from fastapi.testclient import TestClient
from kalhas.api.app import create_app
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode


def test_unknown_path_returns_typed_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = ApiErrorResponse.model_validate(response.json())
    assert body.code == ErrorCode.NOT_FOUND
    assert body.message
    assert body.details == []
    assert body.request_id is not None
    assert response.headers.get("x-request-id") == body.request_id


def test_wrong_method_returns_typed_405(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    body = ApiErrorResponse.model_validate(response.json())
    assert body.code == ErrorCode.METHOD_NOT_ALLOWED


def test_validation_error_returns_typed_422() -> None:
    """A required query parameter missing triggers the typed validation shape."""
    app = create_app()

    @app.get("/_test/required")
    def _required(value: int) -> dict[str, int]:
        return {"value": value}

    with TestClient(app) as test_client:
        response = test_client.get("/_test/required")

    assert response.status_code == 422
    body = ApiErrorResponse.model_validate(response.json())
    assert body.code == ErrorCode.VALIDATION_ERROR
    assert body.details
    assert body.details[0].loc
    assert body.details[0].message


def test_error_contract_rejects_unknown_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ApiErrorResponse.model_validate({"code": "not_found", "message": "x", "surprise": 1})
