"""Phase 17 API tests: verified trajectory artifact inspection endpoints.

Proves the two new read-only GET endpoints return the exact existing
``RunTrajectoryExecution`` / ``RunTrajectoryReplayManifest`` contract
JSON only after complete verification; that X-Tenant-ID is required and
authoritative; that missing/legacy/not-yet-created artifacts return the
typed 404; that foreign-tenant access is indistinguishable from missing;
that tampered records fail through the existing safe 409 mappings
without leaking internal reasons, hashes, or state values; that OpenAPI
declares both endpoints with the correct response schemas; that the
existing replay endpoint behavior is unchanged; and that retrieval
creates no replay, no operational activity event, and no writes.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import RunNotFoundError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.contracts.v1.common import ErrorCode

from tests.phase16_helpers import (
    build_model,
    build_transition,
)

NOW = "2026-01-01T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"


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


def _v2_executed_flow(client: TestClient, *, with_model: bool = True) -> str:
    """Run a complete trajectory-runtime campaign through the HTTP API.

    Returns the run id of the campaign's first run (COMPLETE with a
    stored trajectory execution artifact). State models/transitions are
    embedded into the compiled world via the store (the sanctioned
    Phase 11/12/16 test path), so with ``with_model`` the world is
    transition-capable and each run stores one result.
    """
    store = _store(client)
    if with_model:
        model = build_model()
        store.put_domain_state_model(model)
        store.put_domain_state_transition(build_transition(model))
    assert client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code == 201
    compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS)
    assert compiled.status_code == 200
    world_version_id = compiled.json()["version"]["identifier"]
    created = client.post(
        "/v1/campaigns", headers=HEADERS, json=campaign_payload("campaign-1", world_version_id)
    )
    assert created.status_code == 201
    prepare_strategy_trajectory_plans(
        store=store,
        legion=cast(MockLegionAdapter, _app(client).state.mock_legion),
        tenant_id=TENANT,
        campaign_id="campaign-1",
    )
    started = client.post(
        "/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW}
    )
    assert started.status_code == 200
    executed = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
    assert executed.status_code == 200
    plans = store.get_run_plans(TENANT, "campaign-1")
    return run_identifier(plans[0])


def _v1_executed_flow(client: TestClient) -> str:
    """A complete legacy 1.0.0 campaign through the HTTP API; returns the run id."""
    assert client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code == 201
    compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS)
    assert compiled.status_code == 200
    world_version_id = compiled.json()["version"]["identifier"]
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
    plans = _store(client).get_run_plans(TENANT, "campaign-1")
    return run_identifier(plans[0])


class TestExecutionEndpoint:
    def test_returns_exact_execution_contract_json(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 200
        stored = _store(client).get_run_trajectory_execution(TENANT, run_id)
        assert response.json() == stored.model_dump(mode="json")
        assert response.json()["results"][0]["final_state"] == {"status": "active"}
        # The response exposes only contract-declared fields: no guards,
        # targets, policy content, evidence, or recommendations.
        assert "guard_values" not in response.text
        assert "target_values" not in response.text
        assert "evidence" not in response.text
        assert "recommendation" not in response.text

    def test_empty_results_world_returns_contract_json(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client, with_model=False)
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_x_tenant_id_is_required(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution")
        assert response.status_code == 422
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_unknown_run_returns_typed_404(self, client: TestClient) -> None:
        response = client.get("/v1/runs/run-missing/trajectory-execution", headers=HEADERS)
        assert response.status_code == 404
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.NOT_FOUND.value
        assert body["message"] == "Run 'run-missing' not found for tenant 'tenant-1'"

    def test_legacy_run_returns_typed_404(self, client: TestClient) -> None:
        run_id = _v1_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_foreign_tenant_indistinguishable_from_missing(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        foreign = client.get(
            f"/v1/runs/{run_id}/trajectory-execution", headers={"X-Tenant-ID": OTHER_TENANT}
        )
        assert foreign.status_code == 404
        assert foreign.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_tampered_execution_safe_409_integrity(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        store = _store(client)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"world_content_hash": "f" * 64})
        store._run_trajectory_executions[(TENANT, run_id)] = tampered
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.INTEGRITY_ERROR.value
        text = response.text
        assert "f" * 64 not in text
        assert "reason" not in body
        assert "world_content_hash" not in text


class TestReplayManifestEndpoint:
    def test_returns_exact_manifest_contract_json_after_replay(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        replayed = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert replayed.status_code == 200
        response = client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS)
        assert response.status_code == 200
        stored = _store(client).get_run_trajectory_replay_manifest(TENANT, run_id)
        assert response.json() == stored.model_dump(mode="json")
        assert response.json()["replay_classification"] == "exact"

    def test_not_yet_replayed_returns_typed_404_and_creates_nothing(
        self, client: TestClient
    ) -> None:
        run_id = _v2_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value
        with pytest.raises(RunNotFoundError):
            _store(client).get_replay_manifest(TENANT, run_id)

    def test_legacy_run_returns_typed_404(self, client: TestClient) -> None:
        run_id = _v1_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_foreign_tenant_indistinguishable_from_missing(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        foreign = client.get(
            f"/v1/runs/{run_id}/trajectory-replay-manifest",
            headers={"X-Tenant-ID": OTHER_TENANT},
        )
        assert foreign.status_code == 404
        assert foreign.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_tampered_manifest_safe_409_conflict(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        store = _store(client)
        manifest = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        tampered = manifest.model_copy(update={"expected_execution_hash": "f" * 64})
        store._run_trajectory_replay_manifests[(TENANT, run_id)] = tampered
        response = client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS)
        assert response.status_code == 409
        body = cast(dict[str, Any], response.json())
        assert body["code"] == ErrorCode.CONFLICT.value
        text = response.text
        assert "f" * 64 not in text
        assert "reason" not in body
        assert "expected_execution_hash" not in text

    def test_tampered_execution_fails_manifest_query_with_integrity_409(
        self, client: TestClient
    ) -> None:
        run_id = _v2_executed_flow(client)
        client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        store = _store(client)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        store._run_trajectory_executions[(TENANT, run_id)] = execution.model_copy(
            update={"world_content_hash": "f" * 64}
        )
        response = client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.INTEGRITY_ERROR.value


class TestReadOnlyGuarantees:
    def test_get_creates_no_replay_manifest_and_no_activity_events(
        self, client: TestClient
    ) -> None:
        run_id = _v2_executed_flow(client)
        store = _store(client)
        activity_before = client.get("/v1/operational-activity", headers=HEADERS).json()
        response = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert response.status_code == 200
        # Still no replay manifest and no legacy replay manifest.
        assert (
            client.get(f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS).status_code
            == 404
        )
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        # The operational activity feed is byte-identical.
        activity_after = client.get("/v1/operational-activity", headers=HEADERS).json()
        assert activity_after == activity_before

    def test_repeated_get_is_byte_identical(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        first = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        second = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert first.json() == second.json()
        first_manifest = client.get(
            f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS
        )
        second_manifest = client.get(
            f"/v1/runs/{run_id}/trajectory-replay-manifest", headers=HEADERS
        )
        assert first_manifest.json() == second_manifest.json()

    def test_existing_replay_endpoint_behavior_unchanged(self, client: TestClient) -> None:
        run_id = _v2_executed_flow(client)
        response = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert response.status_code == 200
        body = cast(dict[str, Any], response.json())
        assert body["replay_classification"] == "exact"
        assert "expected_event_hash" in body
        assert "identifier" in body
        assert body["identifier"] == f"replay-{run_id}"


class TestOpenAPI:
    def test_openapi_declares_both_endpoints_with_contract_schemas(
        self, client: TestClient
    ) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        paths = openapi["paths"]
        execution_path = paths["/v1/runs/{run_id}/trajectory-execution"]
        assert "get" in execution_path
        execution_ok = execution_path["get"]["responses"]["200"]
        assert execution_ok["content"]["application/json"]["schema"]["$ref"].endswith(
            "RunTrajectoryExecution"
        )
        manifest_path = paths["/v1/runs/{run_id}/trajectory-replay-manifest"]
        assert "get" in manifest_path
        manifest_ok = manifest_path["get"]["responses"]["200"]
        assert manifest_ok["content"]["application/json"]["schema"]["$ref"].endswith(
            "RunTrajectoryReplayManifest"
        )
        schemas = openapi["components"]["schemas"]
        assert "RunTrajectoryExecution" in schemas
        assert "RunTrajectoryReplayManifest" in schemas
        # No wrapper contracts: both endpoints respond with the exact
        # existing contracts and declare no new response schemas.
        execution_responses = execution_path["get"]["responses"]
        assert execution_responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "RunTrajectoryExecution"
        )
        manifest_responses = manifest_path["get"]["responses"]
        assert manifest_responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "RunTrajectoryReplayManifest"
        )
