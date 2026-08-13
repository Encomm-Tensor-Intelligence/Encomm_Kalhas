"""Phase 21 API tests: the campaign metric-observation matrix endpoint.

``GET /v1/campaigns/{campaign_id}/metric-observation-matrix`` returns
the deterministic campaign metric-observation matrix of a COMPLETE
runtime-2.0.0 campaign (200) only after the entire collection is
verified - the direct ``CampaignMetricObservationMatrix`` contract,
byte-identical on repeated reads. These tests prove the typed error
mappings (404/409 conflict/409 invalid_state/409 integrity_error/422),
tenant isolation, safe no-leak error bodies, the GET-only OpenAPI
surface with no POST/PUT/PATCH/DELETE, no operational-activity changes,
no Colony changes, and a completely unchanged store after GETs.
"""

from __future__ import annotations

import copy
import json
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION, run_identifier
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.run_metric_observation import (
    RunMetricObservationSet,
    RunMetricObservationValue,
)

from tests.phase4_helpers import TENANT, build_store, prepare, start
from tests.phase21_helpers import complete_observation_campaign

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"
MATRIX_PATH = "/v1/campaigns/campaign-1/metric-observation-matrix"


def _store(client: TestClient) -> InMemoryScenarioStore:
    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    cast(FastAPI, client.app).state.store = store


def _setup(client: TestClient, **kwargs: Any) -> tuple[InMemoryScenarioStore, tuple[str, ...]]:
    """Build a COMPLETE 2.0.0 campaign with verified sets on the client's store."""
    store, _world_id, run_ids = complete_observation_campaign(**kwargs)
    _install_store(client, store)
    return store, run_ids


def _snapshot(store: InMemoryScenarioStore) -> object:
    return copy.deepcopy(store.__dict__)


def _run_ids_of(store: InMemoryScenarioStore) -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, "campaign-1"))


def _tamper_set_content_hash(store: InMemoryScenarioStore, run_id: str) -> RunMetricObservationSet:
    stored = store.get_run_metric_observation_set(TENANT, run_id)
    tampered = stored.model_copy(update={"content_hash": "1" * 64})
    store._run_metric_observation_sets[(TENANT, run_id)] = tampered
    return tampered


class TestMatrixApi:
    def test_get_returns_200_with_direct_matrix(self, client: TestClient) -> None:
        store, run_ids = _setup(client)
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["campaign_id"] == "campaign-1"
        assert body["runtime_version"] == "2.0.0"
        assert body["comparison_mode"] == "identical_conditions"
        assert body["identifier"].startswith("metric-observation-matrix-")
        assert len(body["content_hash"]) == 64
        assert len(body["cells"]) == len(run_ids) == 5
        first_observations = body["cells"][0]["observations"]
        assert [o["metric_id"] for o in first_observations] == ["m-1", "m-2"]
        assert first_observations[0]["raw_value"] == 1
        assert type(first_observations[0]["raw_value"]) is int
        assert first_observations[1]["raw_value"] == 1.5
        assert first_observations[0]["metric_unit"] == "units"
        # The matrix is the direct contract: cells match the stored sets.
        for cell, run_id in zip(body["cells"], run_ids, strict=True):
            stored = store.get_run_metric_observation_set(TENANT, run_id)
            assert cell["metric_observation_set_id"] == stored.identifier
            assert cell["metric_observation_set_content_hash"] == stored.content_hash
            assert cell["observations"] == [o.model_dump(mode="json") for o in stored.observations]

    def test_get_repeated_responses_byte_identical(self, client: TestClient) -> None:
        _setup(client)
        first = client.get(MATRIX_PATH, headers=HEADERS)
        assert first.status_code == 200
        second = client.get(MATRIX_PATH, headers=HEADERS)
        assert second.status_code == 200
        assert second.content == first.content

    def test_get_is_strictly_read_only(self, client: TestClient) -> None:
        store, _run_ids = _setup(client)
        before = _snapshot(store)
        for _ in range(2):
            response = client.get(MATRIX_PATH, headers=HEADERS)
            assert response.status_code == 200
        assert _snapshot(store) == before

    def test_requires_tenant_header(self, client: TestClient) -> None:
        _setup(client)
        response = client.get(MATRIX_PATH)
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_unknown_campaign_returns_404(self, client: TestClient) -> None:
        _setup(client)
        response = client.get(
            "/v1/campaigns/campaign-ghost/metric-observation-matrix", headers=HEADERS
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_foreign_tenant_indistinguishable_from_missing(self, client: TestClient) -> None:
        _setup(client)
        response = client.get(MATRIX_PATH, headers={"X-Tenant-ID": OTHER_TENANT})
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_incomplete_campaign_returns_409_invalid_state(self, client: TestClient) -> None:
        _setup(client, execute=False)
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INVALID_STATE

    def test_legacy_runtime_returns_409_conflict(self, client: TestClient) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        _install_store(client, store)
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_unsupported_runtime_returns_409_conflict(self, client: TestClient) -> None:
        from kalhas.contracts.v1.campaign import CampaignState

        from tests.phase25_helpers import inject_unsupported_recorded_runtime

        store, world_id = build_store()
        # Prepare a valid runtime-2 campaign, then simulate corrupted
        # recorded state through private test seams (not an application
        # preparation path): the selected RunPlan and its matching
        # RunStatus are re-stamped with an unsupported recorded runtime.
        prepared = prepare(store, world_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=prepared.run_plans[0]
        )
        start(store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT,
            "campaign-1",
            status.model_copy(update={"state": CampaignState.COMPLETE}),
        )
        _install_store(client, store)
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_missing_phase20_artifact_returns_409_integrity_error(self, client: TestClient) -> None:
        store, run_ids = _setup(client)
        del store._run_metric_observation_sets[(TENANT, run_ids[0])]
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR
        # Never repaired: nothing was recreated by the GET.
        assert (TENANT, run_ids[0]) not in store._run_metric_observation_sets

    def test_corrupted_phase20_artifact_returns_409_integrity_error(
        self, client: TestClient
    ) -> None:
        store, run_ids = _setup(client)
        tampered = _tamper_set_content_hash(store, run_ids[2])
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR
        # The corrupted artifact is never repaired.
        assert store._run_metric_observation_sets[(TENANT, run_ids[2])] == tampered

    def test_tampered_observation_value_returns_409_integrity_error(
        self, client: TestClient
    ) -> None:
        store, run_ids = _setup(client)
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        tampered_value = stored.observations[0].model_copy(update={"raw_value": 99})
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = stored.model_copy(
            update={"observations": (tampered_value,) + stored.observations[1:]}
        )
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR

    def test_validator_bypassed_bool_returns_409_integrity_error(self, client: TestClient) -> None:
        store, run_ids = _setup(client)
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        value_payload = stored.observations[0].model_dump(mode="python")
        value_payload["raw_value"] = True
        tampered_value = RunMetricObservationValue.model_construct(**value_payload)
        set_payload = stored.model_dump(mode="python")
        set_payload["observations"] = (tampered_value,) + stored.observations[1:]
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = (
            RunMetricObservationSet.model_construct(**set_payload)
        )
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INTEGRITY_ERROR

    def test_error_responses_never_leak_sensitive_values(self, client: TestClient) -> None:
        store, run_ids = _setup(client)
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        tampered_value = stored.observations[0].model_copy(update={"raw_value": 99})
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = stored.model_copy(
            update={"observations": (tampered_value,) + stored.observations[1:]}
        )
        response = client.get(MATRIX_PATH, headers=HEADERS)
        assert response.status_code == 409
        body = response.text
        # No raw observation values, state values, hashes, field names,
        # or internal reasons.
        assert "99.0" not in body
        assert "1.5" not in body
        assert "ratio" not in body
        assert "level" not in body
        assert "raw_value" not in body
        assert "input_hash" not in body
        assert "f" * 64 not in body
        assert "1" * 64 not in body
        assert "mismatch" not in body
        assert not any(
            len(token) == 64 and all(c in "0123456789abcdef" for c in token)
            for token in json.loads(body)["message"].split()
        )
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR

    def test_no_operational_activity_changes(self, client: TestClient) -> None:
        _setup(client)
        activity = client.get("/v1/operational-activity", headers=HEADERS).json()
        before = activity["latest_sequence"]
        client.get(MATRIX_PATH, headers=HEADERS)
        after = client.get("/v1/operational-activity", headers=HEADERS).json()
        assert after["latest_sequence"] == before
        assert all(
            "observation" not in json.dumps(event) and "matrix" not in json.dumps(event)
            for event in after["events"]
        )

    def test_colony_unchanged(self, client: TestClient) -> None:
        _setup(client)
        response = client.get("/colony/", headers=HEADERS)
        assert response.status_code == 200


class TestOpenApiSurface:
    def test_matrix_path_is_get_only(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        path = openapi["paths"]["/v1/campaigns/{campaign_id}/metric-observation-matrix"]
        assert set(path) == {"get"}
        for method in ("post", "put", "patch", "delete"):
            assert method not in path

    def test_get_response_references_the_public_matrix_contract(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        path = openapi["paths"]["/v1/campaigns/{campaign_id}/metric-observation-matrix"]
        assert "X-Tenant-ID" in str(path["get"])
        ref = path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("CampaignMetricObservationMatrix")
        schemas = openapi["components"]["schemas"]
        assert "CampaignMetricObservationMatrix" in schemas
        # The nested cell and the Phase 20 value appear only as
        # components, never as path responses.
        assert "CampaignMetricObservationCell" in schemas
        assert "RunMetricObservationValue" in schemas

    def test_no_matrix_write_endpoints_exist(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        for path_name, path in openapi["paths"].items():
            if "metric-observation-matrix" in path_name:
                assert set(path) == {"get"}, path_name
