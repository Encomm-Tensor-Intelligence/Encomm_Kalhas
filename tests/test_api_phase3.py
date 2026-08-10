"""API tests for the Phase 3 campaign endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.run_plan import RunPlan

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


def seed_payload(identifier: str = "seed-1") -> dict[str, Any]:
    return {
        "identifier": identifier,
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": f"value-{identifier}",
        "metadata": {},
    }


def strategy_request_payload(*, tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": "sr-1",
        "tenant_id": tenant_id,
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "required_observations": [
            {"metric_id": "m-1", "description": "observe m-1", "required": True}
        ],
        "requested_at": NOW.isoformat(),
        "metadata": {},
    }


def campaign_payload(
    *,
    world_version_id: str,
    campaign_id: str = "campaign-1",
    tenant_id: str = TENANT,
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "campaign_name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": strategy_request_payload(tenant_id=tenant_id),
        "seed_ensemble": [seed_payload()],
        "runtime_version": "1.0.0",
        "created_at": NOW.isoformat(),
    }


def prepare_world(client: TestClient, *, identifier: str = "scenario-1") -> str:
    """Register + compile a scenario; returns the world version identifier."""
    response = client.post(
        "/v1/scenarios", headers=HEADERS, json=scenario_payload(identifier=identifier)
    )
    assert response.status_code == 201
    compiled = client.post(f"/v1/scenarios/{identifier}/compile", headers=HEADERS).json()
    world_id: str = compiled["version"]["identifier"]
    return world_id


class TestPrepareCampaignApi:
    def test_campaign_created_201_compiled_status(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        response = client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"]["state"] == "compiled"
        assert body["campaign"]["world_version_id"] == world_id
        assert len(body["campaign"]["strategy_candidate_ids"]) == 5

    def test_requires_tenant_header(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        response = client.post("/v1/campaigns", json=campaign_payload(world_version_id=world_id))
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_rejects_strategy_request_tenant_mismatch(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        payload = campaign_payload(world_version_id=world_id, tenant_id="tenant-other")
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert "strategy_request" in body.message

    def test_rejects_foreign_tenant_seed(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        payload = campaign_payload(world_version_id=world_id)
        foreign_seed = seed_payload("seed-foreign")
        foreign_seed["tenant_id"] = "tenant-2"
        payload["seed_ensemble"] = [foreign_seed]
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert "seed" in body.message

    def test_runs_per_strategy_absent_from_openapi(self, client: TestClient) -> None:
        openapi = client.get("/openapi.json").text
        assert "runs_per_strategy" not in openapi

    def test_duplicate_campaign_returns_409(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        payload = campaign_payload(world_version_id=world_id)
        assert client.post("/v1/campaigns", headers=HEADERS, json=payload).status_code == 201
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_unknown_scenario_returns_404(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        payload = campaign_payload(world_version_id=world_id)
        payload["scenario_id"] = "scenario-ghost"
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 404

    def test_unknown_world_returns_404(self, client: TestClient) -> None:
        prepare_world(client)
        response = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=campaign_payload(world_version_id="world-ghost"),
        )
        assert response.status_code == 404

    def test_world_scenario_mismatch_returns_422(self, client: TestClient) -> None:
        world_id = prepare_world(client, identifier="scenario-a")
        client.post(
            "/v1/scenarios", headers=HEADERS, json=scenario_payload(identifier="scenario-b")
        )
        payload = campaign_payload(world_version_id=world_id)
        payload["scenario_id"] = "scenario-b"
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 422
        body = ApiErrorResponse.model_validate(response.json())
        assert body.code == ErrorCode.VALIDATION_ERROR
        assert "not compiled from scenario" in body.message

    def test_empty_seed_ensemble_rejected(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        payload = campaign_payload(world_version_id=world_id)
        payload["seed_ensemble"] = []
        response = client.post("/v1/campaigns", headers=HEADERS, json=payload)
        assert response.status_code == 422


class TestCampaignReads:
    def test_get_campaign_and_runs(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )

        detail = client.get("/v1/campaigns/campaign-1", headers=HEADERS)
        assert detail.status_code == 200
        assert detail.json()["status"]["state"] == "compiled"

        runs = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS)
        assert runs.status_code == 200
        plans = [RunPlan.model_validate(p) for p in runs.json()["run_plans"]]
        assert len(plans) == 5
        assert {p.world_version_id for p in plans} == {world_id}
        assert all(p.planned_state == "planned" for p in plans)

    def test_foreign_tenant_cannot_read_campaign_or_runs(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )
        foreign = {"X-Tenant-ID": "tenant-2"}
        assert client.get("/v1/campaigns/campaign-1", headers=foreign).status_code == 404
        assert client.get("/v1/campaigns/campaign-1/runs", headers=foreign).status_code == 404
        assert client.get("/v1/campaigns/campaign-1").status_code == 422

    def test_unknown_campaign_returns_404(self, client: TestClient) -> None:
        assert client.get("/v1/campaigns/campaign-ghost", headers=HEADERS).status_code == 404
        assert client.get("/v1/campaigns/campaign-ghost/runs", headers=HEADERS).status_code == 404


class TestStartCampaignApi:
    def test_start_compiled_campaign(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )
        response = client.post(
            "/v1/campaigns/campaign-1/start",
            headers=HEADERS,
            json={"changed_at": LATER.isoformat()},
        )
        assert response.status_code == 200
        assert response.json()["state"] == "running"
        status = client.get("/v1/campaigns/campaign-1", headers=HEADERS).json()["status"]
        assert status["state"] == "running"

    def test_start_twice_returns_invalid_state(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )
        body = {"changed_at": LATER.isoformat()}
        assert (
            client.post("/v1/campaigns/campaign-1/start", headers=HEADERS, json=body).status_code
            == 200
        )
        response = client.post("/v1/campaigns/campaign-1/start", headers=HEADERS, json=body)
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INVALID_STATE

    def test_start_unknown_campaign_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/v1/campaigns/campaign-ghost/start",
            headers=HEADERS,
            json={"changed_at": LATER.isoformat()},
        )
        assert response.status_code == 404

    def test_start_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post(
            "/v1/campaigns/campaign-1/start", json={"changed_at": LATER.isoformat()}
        )
        assert response.status_code == 422

    def test_start_does_not_fabricate_outcomes(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        client.post(
            "/v1/campaigns", headers=HEADERS, json=campaign_payload(world_version_id=world_id)
        )
        client.post(
            "/v1/campaigns/campaign-1/start",
            headers=HEADERS,
            json={"changed_at": LATER.isoformat()},
        )
        runs = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()["run_plans"]
        assert all(run["planned_state"] == "planned" for run in runs)
        assert all("outcome" not in run for run in runs)
