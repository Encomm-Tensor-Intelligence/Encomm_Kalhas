"""API tests for the Phase 2 scenario/world endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.world import WorldVersion

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)

TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}


def scenario_payload(*, identifier: str = "scenario-1", tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "tenant_id": tenant_id,
        "schema_version": "1.0.0",
        "name": "Reference scenario",
        "description": "Domain-neutral scenario",
        "created_at": NOW.isoformat(),
        "objectives": [
            {
                "identifier": "obj-1",
                "description": "Maximize the primary metric",
                "direction": "maximize",
                "target": 100.0,
                "weight": 1.0,
            }
        ],
        "constraints": [
            {"identifier": "c-1", "description": "Stay within declared bounds", "hard": True}
        ],
        "time_horizon": {
            "start": NOW.isoformat(),
            "end": LATER.isoformat(),
            "resolution": "step",
        },
        "metrics": [
            {"identifier": "m-1", "name": "Primary metric", "unit": "units", "aggregation": "mean"}
        ],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {},
    }


def incomplete_payload(*, identifier: str = "scenario-2") -> dict[str, Any]:
    """Structurally valid but semantically incomplete: no objectives/metrics/constraints."""
    payload = scenario_payload(identifier=identifier)
    payload["objectives"] = []
    payload["constraints"] = []
    payload["metrics"] = []
    payload["time_horizon"]["resolution"] = None
    return payload


class TestCreateScenario:
    def test_created_201_with_typed_body(self, client: TestClient) -> None:
        response = client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        assert response.status_code == 201
        body = ScenarioSpec.model_validate(response.json())
        assert body.identifier == "scenario-1"
        assert body.tenant_id == TENANT

    def test_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post("/v1/scenarios", json=scenario_payload())
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert body.details

    def test_rejects_tenant_mismatch(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios",
            headers={"X-Tenant-ID": "tenant-other"},
            json=scenario_payload(tenant_id=TENANT),
        )
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert "X-Tenant-ID" in body.message

    def test_duplicate_returns_409_conflict(self, client: TestClient) -> None:
        payload = scenario_payload()
        assert client.post("/v1/scenarios", headers=HEADERS, json=payload).status_code == 201
        response = client.post("/v1/scenarios", headers=HEADERS, json=payload)
        assert response.status_code == 409
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.CONFLICT

    def test_invalid_body_returns_typed_422(self, client: TestClient) -> None:
        payload = scenario_payload()
        payload["objectives"] = "not-a-list"
        response = client.post("/v1/scenarios", headers=HEADERS, json=payload)
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR


class TestValidateScenario:
    def test_valid_scenario_returns_valid_report(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        response = client.post("/v1/scenarios/scenario-1/validate", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["report"]["valid"] is True
        assert body["questions"] == []

    def test_incomplete_scenario_returns_issues_and_questions(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=incomplete_payload())
        response = client.post("/v1/scenarios/scenario-2/validate", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["report"]["valid"] is False
        codes = {issue["code"] for issue in body["report"]["issues"]}
        assert {"missing_objectives", "missing_success_metrics", "missing_constraints"} <= codes
        question_ids = {question["identifier"] for question in body["questions"]}
        assert "q-missing_objectives" in question_ids

    def test_unknown_scenario_returns_404(self, client: TestClient) -> None:
        response = client.post("/v1/scenarios/nope/validate", headers=HEADERS)
        assert response.status_code == 404
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.NOT_FOUND


class TestCompileScenario:
    def test_compile_success_and_world_fetch(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        response = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        version = WorldVersion.model_validate(body["version"])
        assert version.source_scenario_id == "scenario-1"
        assert version.compiler_version == "1.0.0"
        assert body["manifest"]["world_version_id"] == version.identifier

        fetched = client.get(f"/v1/worlds/{version.identifier}", headers=HEADERS)
        assert fetched.status_code == 200
        assert WorldVersion.model_validate(fetched.json()) == version

    def test_compile_invalid_scenario_returns_typed_422(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=incomplete_payload())
        response = client.post("/v1/scenarios/scenario-2/compile", headers=HEADERS)
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert "semantically invalid" in body.message
        assert body.details
        assert body.details[0].loc

    def test_compile_unknown_scenario_returns_404(self, client: TestClient) -> None:
        response = client.post("/v1/scenarios/nope/compile", headers=HEADERS)
        assert response.status_code == 404

    def test_compile_is_deterministic_via_api(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        first = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        second = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        assert first["version"]["identifier"] == second["version"]["identifier"]
        assert first["version"]["content_hash"] == second["version"]["content_hash"]

    def test_world_lookup_requires_tenant(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        world_id = compiled["version"]["identifier"]
        response = client.get(f"/v1/worlds/{world_id}")
        assert response.status_code == 422
        response = client.get(f"/v1/worlds/{world_id}", headers={"X-Tenant-ID": "tenant-other"})
        assert response.status_code == 404

    def test_world_not_found_returns_404(self, client: TestClient) -> None:
        response = client.get("/v1/worlds/world-0000000000000000", headers=HEADERS)
        assert response.status_code == 404
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.NOT_FOUND


class TestPhase2TenantIsolation:
    def test_tenant_isolation_across_scenarios_and_worlds(self, client: TestClient) -> None:
        client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
        other = client.post(
            "/v1/scenarios",
            headers={"X-Tenant-ID": "tenant-2"},
            json=scenario_payload(identifier="scenario-1", tenant_id="tenant-2"),
        )
        assert other.status_code == 201
        validate_other = client.post(
            "/v1/scenarios/scenario-1/validate", headers={"X-Tenant-ID": "tenant-2"}
        )
        assert validate_other.status_code == 200
        missing = client.post(
            "/v1/scenarios/scenario-1/validate", headers={"X-Tenant-ID": "tenant-3"}
        )
        assert missing.status_code == 404
