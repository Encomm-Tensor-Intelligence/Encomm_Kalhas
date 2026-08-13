"""Phase 20 API tests: metric-observation extraction endpoints.

``POST /v1/runs/{run_id}/metric-observations`` explicitly extracts and
stores the immutable observation set of a COMPLETE runtime 2.0.0 run
(201), and ``GET /v1/runs/{run_id}/metric-observations`` returns it only
after full regeneration-based verification (200), never creating an
artifact when none exists. These tests prove the typed error mappings
(404/409 conflict/409 invalid_state/409 integrity_error/422), tenant
isolation, safe no-leak error bodies, the OpenAPI surface, GET
read-only byte-identical behavior, and the absence of operational-
activity and Colony changes.
"""

from __future__ import annotations

import copy
import json
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

from tests.phase4_helpers import TENANT, build_store, execute, prepare, start
from tests.phase20_helpers import build_complete_observation_run

HEADERS = {"X-Tenant-ID": TENANT}


def _store(client: TestClient) -> InMemoryScenarioStore:
    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    cast(FastAPI, client.app).state.store = store


def _setup(client: TestClient, **kwargs: Any) -> str:
    """Build a COMPLETE 2.0.0 run on the client's store; returns run_id."""
    store, _world_id, run_id = build_complete_observation_run(**kwargs)
    _install_store(client, store)
    return run_id


def _snapshot(
    client: TestClient,
) -> dict[tuple[str, str], RunMetricObservationSet]:
    return copy.deepcopy(_store(client)._run_metric_observation_sets)


def _extract(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


class TestExtractionApi:
    def test_post_returns_201_with_exact_stored_artifact(self, client: TestClient) -> None:
        run_id = _setup(client)
        artifact = _extract(client, run_id)
        assert artifact["run_id"] == run_id
        assert artifact["runtime_version"] == "2.0.0"
        assert artifact["identifier"].startswith("metric-observation-set-")
        assert len(artifact["content_hash"]) == 64
        observations = artifact["observations"]
        assert [o["metric_id"] for o in observations] == ["m-1", "m-2"]
        assert observations[0]["raw_value"] == 1
        assert observations[1]["raw_value"] == 1.5
        assert observations[0]["metric_unit"] == "units"
        assert observations[1]["metric_unit"] == "percent"
        # The stored artifact is byte-identical to the response.
        stored = _store(client).get_run_metric_observation_set(TENANT, run_id)
        assert stored.model_dump(mode="json") == artifact

    def test_get_returns_200_byte_identical_after_extraction(self, client: TestClient) -> None:
        run_id = _setup(client)
        created = _extract(client, run_id)
        response = client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == created
        # Byte-identical on repeat reads.
        again = client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert again.json() == created
        assert again.content == response.content

    def test_get_before_extraction_returns_404_and_creates_nothing(
        self, client: TestClient
    ) -> None:
        run_id = _setup(client)
        assert _snapshot(client) == {}
        response = client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 404
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.NOT_FOUND
        # Nothing was created by the GET.
        assert _snapshot(client) == {}
        assert (
            client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS).status_code == 404
        )

    def test_get_is_strictly_read_only(self, client: TestClient) -> None:
        run_id = _setup(client)
        _extract(client, run_id)
        before = _snapshot(client)
        for _ in range(2):
            response = client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
            assert response.status_code == 200
        assert _snapshot(client) == before

    def test_duplicate_post_returns_409_and_never_overwrites(self, client: TestClient) -> None:
        run_id = _setup(client)
        first = _extract(client, run_id)
        response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.CONFLICT
        stored = _store(client).get_run_metric_observation_set(TENANT, run_id)
        assert stored.model_dump(mode="json") == first

    def test_unknown_run_returns_404(self, client: TestClient) -> None:
        _setup(client)
        for method in ("post", "get"):
            response = getattr(client, method)(
                "/v1/runs/run-ghost/metric-observations", headers=HEADERS
            )
            assert response.status_code == 404, method
            assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_foreign_tenant_indistinguishable_from_missing(self, client: TestClient) -> None:
        run_id = _setup(client)
        _extract(client, run_id)
        foreign = {"X-Tenant-ID": "tenant-other"}
        response = client.get(f"/v1/runs/{run_id}/metric-observations", headers=foreign)
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND
        response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=foreign)
        assert response.status_code == 404

    def test_requires_tenant_header(self, client: TestClient) -> None:
        run_id = _setup(client)
        for method in ("post", "get"):
            response = getattr(client, method)(f"/v1/runs/{run_id}/metric-observations")
            assert response.status_code == 422
            assert (
                ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR
            )

    def test_legacy_runtime_returns_409_conflict(self, client: TestClient) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        _install_store(client, store)
        from kalhas.application.run_planner import run_identifier

        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        for method in ("post", "get"):
            response = getattr(client, method)(
                f"/v1/runs/{run_id}/metric-observations", headers=HEADERS
            )
            assert response.status_code == 409, method
            assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_unsupported_runtime_returns_409_conflict(self, client: TestClient) -> None:
        _setup(client, execute=False)
        store = _store(client)
        from datetime import UTC, datetime

        from kalhas.adapters.mocks import MockLegionAdapter
        from kalhas.application.campaign_service import prepare_campaign
        from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION

        from tests.phase4_helpers import build_request, build_seed
        from tests.phase25_helpers import inject_unsupported_recorded_runtime

        # Prepare a valid runtime-2 campaign, then simulate corrupted
        # recorded state through private test seams (not an application
        # preparation path): both the stored RunPlan and its matching
        # RunStatus are re-stamped with an unsupported recorded runtime.
        prepared = prepare_campaign(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=store.get_run_plans(TENANT, "campaign-1")[0].world_version_id,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-unsupported",
            campaign_name="Unsupported campaign",
            seed_ensemble=(build_seed(),),
            created_at=datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC),
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        )
        unsupported_run = inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-unsupported", plan=prepared.run_plans[0]
        )
        response = client.post(f"/v1/runs/{unsupported_run}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_incomplete_run_returns_409_invalid_state(self, client: TestClient) -> None:
        run_id = _setup(client, execute=False)
        response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INVALID_STATE
        assert _snapshot(client) == {}

    def test_corrupted_execution_returns_409_integrity_error(self, client: TestClient) -> None:
        run_id = _setup(client)
        store = _store(client)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_state = dict(result.final_state)
        tampered_state["ratio"] = 99.0
        store._run_trajectory_executions[(TENANT, run_id)] = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": tampered_state}),)}
        )
        response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR
        assert _snapshot(client) == {}

    def test_corrupted_stored_artifact_returns_409_integrity_error(
        self, client: TestClient
    ) -> None:
        run_id = _setup(client)
        _extract(client, run_id)
        store = _store(client)
        stored = store.get_run_metric_observation_set(TENANT, run_id)
        tampered = stored.model_copy(update={"content_hash": "1" * 64})
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        response = client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR
        # Never repaired.
        assert store._run_metric_observation_sets[(TENANT, run_id)] == tampered

    def test_error_responses_never_leak_sensitive_values(self, client: TestClient) -> None:
        run_id = _setup(client)
        store = _store(client)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_state = dict(result.final_state)
        tampered_state["ratio"] = 99.0
        store._run_trajectory_executions[(TENANT, run_id)] = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": tampered_state}),)}
        )
        response = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert response.status_code == 409
        body = response.text
        # No raw observed values, state values, hashes, or internal reasons.
        assert "99.0" not in body
        assert "1.5" not in body
        assert "ratio" not in body
        assert "tampered" not in body
        assert "final_state" not in body
        assert not any(
            len(token) == 64 and all(c in "0123456789abcdef" for c in token)
            for token in json.loads(body)["message"].split()
        )
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR

    def test_no_operational_activity_changes(self, client: TestClient) -> None:
        run_id = _setup(client)
        activity = client.get("/v1/operational-activity", headers=HEADERS).json()
        before = activity["latest_sequence"]
        _extract(client, run_id)
        client.get(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        after = client.get("/v1/operational-activity", headers=HEADERS).json()
        assert after["latest_sequence"] == before
        assert all("observation" not in json.dumps(event) for event in after["events"])

    def test_colony_unchanged(self, client: TestClient) -> None:
        run_id = _setup(client)
        _extract(client, run_id)
        response = client.get("/colony/", headers=HEADERS)
        assert response.status_code == 200
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        assert "/v1/runs/{run_id}/metric-observations" in openapi["paths"]


class TestOpenApiSurface:
    def test_metric_observation_paths_in_openapi(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        path = openapi["paths"]["/v1/runs/{run_id}/metric-observations"]
        assert "post" in path and "get" in path
        post_schema = path["post"]
        assert post_schema["responses"]["201"] is not None
        get_schema = path["get"]
        assert get_schema["responses"]["200"] is not None
        assert "X-Tenant-ID" in str(post_schema)
        assert "X-Tenant-ID" in str(get_schema)
        # The response models are the exact public contract.
        post_ref = post_schema["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
        get_ref = get_schema["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert post_ref.endswith("RunMetricObservationSet")
        assert get_ref.endswith("RunMetricObservationSet")
        schemas = openapi["components"]["schemas"]
        assert "RunMetricObservationSet" in schemas
        assert "RunMetricObservationValue" in schemas
        # The value contract appears only as a component, never as a path response.
        assert "observations" in schemas["RunMetricObservationSet"]["properties"]
