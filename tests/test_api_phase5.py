"""API tests for the Phase 5 input-integrity verification endpoint."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from kalhas.api.app import create_app
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.strategy import PolicyDeclaration

NOW = "2026-01-01T12:00:00Z"
LATER = "2026-01-02T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}


def scenario_payload() -> dict[str, Any]:
    return {
        "identifier": "scenario-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "name": "Reference scenario",
        "created_at": NOW,
        "objectives": [
            {
                "identifier": "obj-1",
                "description": "Maximize the primary metric",
                "direction": "maximize",
                "target": 100.0,
                "weight": 1.0,
            }
        ],
        "constraints": [{"identifier": "c-1", "description": "Stay within declared bounds"}],
        "time_horizon": {"start": NOW, "end": LATER, "resolution": "step"},
        "metrics": [{"identifier": "m-1", "name": "Primary metric", "unit": "units"}],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {},
    }


def seed_payload() -> dict[str, Any]:
    return {
        "identifier": "seed-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": "v1",
        "metadata": {},
    }


def campaign_payload(world_version_id: str) -> dict[str, Any]:
    return {
        "campaign_id": "campaign-1",
        "campaign_name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": {
            "identifier": "sr-1",
            "tenant_id": TENANT,
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "required_observations": [
                {"metric_id": "m-1", "description": "observe m-1", "required": True}
            ],
            "requested_at": NOW,
            "metadata": {},
        },
        "seed_ensemble": [seed_payload()],
        "runtime_version": "1.0.0",
        "created_at": NOW,
    }


def prepare_world(client: TestClient) -> str:
    assert client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code == 201
    compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
    world_id: str = compiled["version"]["identifier"]
    return world_id


def prepare_campaign(client: TestClient, world_id: str) -> None:
    response = client.post("/v1/campaigns", headers=HEADERS, json=campaign_payload(world_id))
    assert response.status_code == 201


def first_run_id(client: TestClient) -> str:
    runs = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()["run_plans"]
    run_id: str = f"run-{runs[0]['identifier']}"
    return run_id


class TestVerifyInputsApi:
    def test_verify_planned_run_returns_exact_manifest(self, client: TestClient) -> None:
        from datetime import UTC, datetime

        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)

        response = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert response.status_code == 200
        manifest = RunInputIntegrityManifest.model_validate(response.json())
        assert manifest.verification_classification == "exact"
        assert manifest.expected_input_hash == manifest.recomputed_input_hash
        # recorded_at is the recorded RunPlan creation time, never the wall clock.
        assert manifest.recorded_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def test_verify_after_execution(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        client.post("/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW})
        client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        run_id = first_run_id(client)
        response = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert response.status_code == 200
        assert RunInputIntegrityManifest.model_validate(response.json()).recomputed_input_hash

    def test_verify_does_not_change_lifecycle_state(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        campaign = client.get("/v1/campaigns/campaign-1", headers=HEADERS).json()
        assert campaign["status"]["state"] == "compiled"  # unchanged
        status = client.get(f"/v1/runs/{run_id}", headers=HEADERS).json()
        assert status["state"] == "planned"  # unchanged

    def test_verify_creates_no_events_or_artifacts(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        response = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert response.status_code == 200
        payload = response.json()
        assert not {"outcome", "evidence", "recommendation", "metrics"}.intersection(payload)
        assert client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).status_code == 404

    def test_foreign_tenant_returns_404(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        response = client.post(
            f"/v1/runs/{run_id}/verify-inputs", headers={"X-Tenant-ID": "tenant-2"}
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_unknown_run_returns_404(self, client: TestClient) -> None:
        response = client.post("/v1/runs/run-ghost/verify-inputs", headers=HEADERS)
        assert response.status_code == 404

    def test_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post("/v1/runs/run-1/verify-inputs")
        assert response.status_code == 422

    def test_tampered_inputs_return_409_integrity_error(self) -> None:
        app = create_app()
        client = TestClient(app)
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        # Tamper the persisted strategy candidates through the app store.
        store = app.state.store
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        store.put_strategy_candidates(
            TENANT,
            "campaign-1",
            tuple(
                candidate.model_copy(
                    update={"policy": PolicyDeclaration(summary="tampered", rules=[])}
                )
                for candidate in candidates
            ),
        )
        response = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR
        assert "tampered policy" not in error.message  # never leaks injected/internal data
        assert "policy" not in error.message
