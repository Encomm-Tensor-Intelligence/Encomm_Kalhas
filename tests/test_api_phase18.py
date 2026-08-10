"""Phase 18 API tests: the campaign trajectory matrix endpoint.

Proves ``GET /v1/campaigns/{campaign_id}/trajectory-matrix`` returns the
exact ``CampaignTrajectoryMatrix`` contract JSON of a COMPLETE 2.0.0
campaign directly (no response wrapper); that X-Tenant-ID is required
and authoritative; that unknown/foreign campaigns return the typed 404;
that non-COMPLETE campaigns return the typed 409 ``invalid_state``;
that legacy and unsupported recorded runtimes return the typed 409
``conflict``; that missing or corrupted executions inside a COMPLETE
campaign return the safe typed 409 ``integrity_error`` without leaking
internal reasons, hashes, or state values; that OpenAPI declares the
endpoint with the exact contract response schema; that repeated GETs are
byte-identical; that the GET performs no write and creates no
operational-activity event; and that the existing Phase 16/17 run
endpoints behave unchanged.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.contracts.v1.common import ErrorCode

from tests.phase16_helpers import build_model, build_transition

NOW = "2026-01-01T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"

_CELL_FIELDS = {
    "sequence_position",
    "strategy_position",
    "seed_position",
    "run_id",
    "run_plan_id",
    "strategy_candidate_id",
    "scenario_seed_id",
    "input_hash",
    "trajectory_execution_id",
    "trajectory_execution_content_hash",
    "trajectory_plan_set_hash",
    "result_content_hashes",
}


def scenario_payload(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": "scenario-1",
        "tenant_id": tenant_id,
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
        "time_horizon": {"start": NOW, "end": "2026-01-02T12:00:00Z", "resolution": "step"},
        "metrics": [{"identifier": "m-1", "name": "Primary metric", "unit": "units"}],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {},
    }


def seed_payload(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": "seed-1",
        "tenant_id": tenant_id,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": "v1",
        "metadata": {},
    }


def campaign_payload(
    campaign_id: str, world_version_id: str, tenant_id: str = TENANT
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "campaign_name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": {
            "identifier": "sr-1",
            "tenant_id": tenant_id,
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "required_observations": [
                {"metric_id": "m-1", "description": "observe m-1", "required": True}
            ],
            "requested_at": NOW,
            "metadata": {},
        },
        "seed_ensemble": [seed_payload(tenant_id)],
        "runtime_version": "2.0.0",
        "created_at": NOW,
    }


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _store(client: TestClient) -> InMemoryScenarioStore:
    return cast(InMemoryScenarioStore, _app(client).state.store)


def _scenario_and_world(client: TestClient, tenant_id: str = TENANT) -> str:
    """Register a scenario and compile its world; returns the world id."""
    headers = {"X-Tenant-ID": tenant_id}
    payload = scenario_payload(tenant_id)
    assert client.post("/v1/scenarios", headers=headers, json=payload).status_code == 201
    compiled = client.post(f"/v1/scenarios/{payload['identifier']}/compile", headers=headers)
    assert compiled.status_code == 200
    version = cast(dict[str, Any], compiled.json())["version"]
    return cast(str, version["identifier"])


def _v2_complete_flow(client: TestClient, *, campaign_id: str = "campaign-1") -> None:
    """A complete trajectory-runtime campaign through the HTTP API."""
    store = _store(client)
    model = build_model()
    store.put_domain_state_model(model)
    store.put_domain_state_transition(build_transition(model))
    world_version_id = _scenario_and_world(client)
    assert (
        client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=campaign_payload(campaign_id, world_version_id),
        ).status_code
        == 201
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=cast(MockLegionAdapter, _app(client).state.mock_legion),
        tenant_id=TENANT,
        campaign_id=campaign_id,
    )
    assert (
        client.post(
            f"/v1/campaigns/{campaign_id}/start", headers=HEADERS, json={"changed_at": NOW}
        ).status_code
        == 200
    )
    assert client.post(f"/v1/campaigns/{campaign_id}/execute", headers=HEADERS).status_code == 200


def _v2_running_flow(client: TestClient, *, campaign_id: str = "campaign-1") -> None:
    """A prepared and started (RUNNING) 2.0.0 campaign; never executed."""
    world_version_id = _scenario_and_world(client)
    assert (
        client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=campaign_payload(campaign_id, world_version_id),
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/v1/campaigns/{campaign_id}/start", headers=HEADERS, json={"changed_at": NOW}
        ).status_code
        == 200
    )


def _v2_first_run_id(client: TestClient) -> str:
    plans = _store(client).get_run_plans(TENANT, "campaign-1")
    return run_identifier(plans[0])


class TestMatrixEndpoint:
    def test_returns_exact_matrix_contract_json(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 200
        expected = get_verified_campaign_trajectory_matrix(
            store=_store(client), tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert response.json() == expected.model_dump(mode="json")

    def test_response_is_the_matrix_directly_without_wrapper(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        body = cast(dict[str, Any], response.json())
        assert set(body) == {
            "identifier",
            "tenant_id",
            "schema_version",
            "campaign_id",
            "scenario_id",
            "world_version_id",
            "world_content_hash",
            "runtime_version",
            "comparison_mode",
            "ordered_strategy_candidate_ids",
            "ordered_scenario_seed_ids",
            "cells",
            "content_hash",
            "assembled_at",
        }
        assert body["runtime_version"] == "2.0.0"
        assert body["comparison_mode"] == "identical_conditions"

    def test_cells_carry_references_and_hashes_only(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        body = cast(dict[str, Any], response.json())
        for cell in body["cells"]:
            assert set(cell) == _CELL_FIELDS
        # No state snapshots, guards, targets, policy content, outcomes,
        # evidence, or recommendations anywhere in the response.
        text = response.text
        for forbidden in (
            "initial_state",
            "final_state",
            "attempts",
            "guard_values",
            "target_values",
            "policy",
            "evidence",
            "recommendation",
            "ranking",
            "score",
        ):
            assert forbidden not in text, forbidden

    def test_x_tenant_id_is_required(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix")
        assert response.status_code == 422
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_unknown_campaign_returns_typed_404(self, client: TestClient) -> None:
        response = client.get("/v1/campaigns/campaign-missing/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 404
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.NOT_FOUND.value
        assert body["message"] == "Campaign 'campaign-missing' not found for tenant 'tenant-1'"

    def test_foreign_tenant_indistinguishable_from_missing(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        foreign = client.get(
            "/v1/campaigns/campaign-1/trajectory-matrix", headers={"X-Tenant-ID": OTHER_TENANT}
        )
        assert foreign.status_code == 404
        assert foreign.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_campaign_not_complete_returns_typed_409_invalid_state(
        self, client: TestClient
    ) -> None:
        _v2_running_flow(client)
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.INVALID_STATE.value
        assert "complete" in body["message"]

    def test_legacy_campaign_returns_typed_409_conflict(self, client: TestClient) -> None:
        world_version_id = _scenario_and_world(client)
        payload = campaign_payload("campaign-1", world_version_id)
        payload["runtime_version"] = "1.0.0"
        assert client.post("/v1/campaigns", headers=HEADERS, json=payload).status_code == 201
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW}
            ).status_code
            == 200
        )
        assert client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS).status_code == 200
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.CONFLICT.value
        assert "1.0.0" in body["message"]

    def test_unsupported_runtime_returns_typed_409_conflict(self, client: TestClient) -> None:
        world_version_id = _scenario_and_world(client)
        payload = campaign_payload("campaign-1", world_version_id)
        payload["runtime_version"] = "3.0.0"
        assert client.post("/v1/campaigns", headers=HEADERS, json=payload).status_code == 201
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW}
            ).status_code
            == 200
        )
        store = _store(client)
        status = store.get_campaign_status(TENANT, "campaign-1")
        from kalhas.contracts.v1.campaign import CampaignState

        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.COMPLETE})
        )
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.CONFLICT.value
        assert "3.0.0" in body["message"]

    def test_missing_execution_returns_safe_409_integrity(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        store = _store(client)
        run_id = _v2_first_run_id(client)
        del store._run_trajectory_executions[(TENANT, run_id)]
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.INTEGRITY_ERROR.value
        text = response.text
        assert "reason" not in body
        assert "run_id" not in text
        assert body["message"] == (
            "Campaign 'campaign-1' failed trajectory matrix integrity verification and was rejected"
        )

    def test_corrupted_execution_returns_safe_409_integrity(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        store = _store(client)
        run_id = _v2_first_run_id(client)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        store._run_trajectory_executions[(TENANT, run_id)] = execution.model_copy(
            update={"world_content_hash": "f" * 64}
        )
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.INTEGRITY_ERROR.value
        text = response.text
        assert "f" * 64 not in text
        assert "reason" not in body
        assert "world_content_hash" not in text


class TestReadOnlyGuarantees:
    def test_get_creates_no_operational_activity_events(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        activity_before = client.get("/v1/operational-activity", headers=HEADERS).json()
        response = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert response.status_code == 200
        activity_after = client.get("/v1/operational-activity", headers=HEADERS).json()
        assert activity_after == activity_before

    def test_repeated_get_is_byte_identical(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        first = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        second = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert first.json() == second.json()
        assert first.content == second.content

    def test_existing_phase17_run_endpoint_unchanged(self, client: TestClient) -> None:
        _v2_complete_flow(client)
        run_id = _v2_first_run_id(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 200
        stored = _store(client).get_run_trajectory_execution(TENANT, run_id)
        assert response.json() == stored.model_dump(mode="json")


class TestOpenAPI:
    def test_openapi_declares_endpoint_with_exact_contract_schema(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        paths = openapi["paths"]
        path = paths["/v1/campaigns/{campaign_id}/trajectory-matrix"]
        assert "get" in path
        ok = path["get"]["responses"]["200"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith(
            "CampaignTrajectoryMatrix"
        )
        schemas = openapi["components"]["schemas"]
        assert "CampaignTrajectoryMatrix" in schemas
        assert "CampaignTrajectoryRunCell" in schemas
        # No wrapper contracts: the 200 response is the exact contract.
        assert (
            path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/CampaignTrajectoryMatrix"
        )
