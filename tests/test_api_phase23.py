"""Phase 23 API tests: the evaluation-profile and objective-evaluation endpoints.

Proves ``POST/GET /v1/scenarios/{scenario_id}/evaluation-profile`` and
``GET /v1/campaigns/{campaign_id}/objective-evaluations`` return the
direct contracts with the exact status codes (201/200/404/409
conflict/409 invalid_state/409 integrity_error/422), reject every
forged authoritative field at the request boundary, are tenant-scoped,
never record operational activity, never store the derived matrix, and
expose only the typed safe error shape with no value leakage.
"""

from __future__ import annotations

import copy
import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode

from tests.phase4_helpers import TENANT
from tests.phase21_helpers import complete_observation_campaign
from tests.phase23_helpers import (
    complete_evaluation_campaign,
    verified_evaluation_campaign,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"
PROFILE_PATH = "/v1/scenarios/scenario-1/evaluation-profile"
EVALUATIONS_PATH = "/v1/campaigns/campaign-1/objective-evaluations"

VALID_BODY: dict[str, object] = {
    "bindings": [
        {
            "objective_id": "obj-c",
            "metric_id": "m-1",
            "reach_tolerance": 5.0,
            "normalization_scale": 50.0,
        },
        {"objective_id": "obj-a", "metric_id": "m-2", "normalization_scale": 20.0},
        {"objective_id": "obj-b", "metric_id": "m-1", "normalization_scale": 100.0},
    ],
    "declared_at": "2026-01-05T12:00:00Z",
    "metadata": {},
}


def _store(client: TestClient) -> InMemoryScenarioStore:
    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    cast(FastAPI, client.app).state.store = store


def _snapshot(store: InMemoryScenarioStore) -> object:
    return copy.deepcopy(store.__dict__)


def _scenario_only_store() -> InMemoryScenarioStore:
    from kalhas.application.in_memory_store import InMemoryScenarioStore as Store

    from tests.phase23_helpers import build_evaluation_scenario

    store = Store()
    store.put_scenario(build_evaluation_scenario())
    return store


def _declare_via_api(client: TestClient, body: dict[str, object] | None = None) -> dict[str, Any]:
    response = client.post(
        PROFILE_PATH, json=body if body is not None else VALID_BODY, headers=HEADERS
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


class TestDeclareProfile:
    def test_post_returns_201_with_direct_profile(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        body = _declare_via_api(client)
        assert body["scenario_id"] == "scenario-1"
        assert body["identifier"].startswith("evaluation-profile-")
        assert len(body["content_hash"]) == 64
        # Bindings canonicalized into exact scenario objective order.
        assert [b["objective_id"] for b in body["bindings"]] == ["obj-b", "obj-a", "obj-c"]
        # Authoritative snapshots copied from the stored scenario.
        assert body["bindings"][0]["direction"] == "minimize"
        assert body["bindings"][0]["target"] == 100.0
        assert body["bindings"][1]["direction"] == "maximize"
        assert body["bindings"][1]["target"] is None
        assert body["bindings"][2]["direction"] == "reach"

    def test_get_returns_200_and_matches_post(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        declared = _declare_via_api(client)
        response = client.get(PROFILE_PATH, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == declared

    def test_get_missing_profile_404(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        response = client.get(PROFILE_PATH, headers=HEADERS)
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == ErrorCode.NOT_FOUND.value

    def test_corrupted_stored_profile_get_409_integrity_error(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        _declare_via_api(client)
        store = _store(client)
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        # Inject a validator-bypassed malformed binding (tolerance on a
        # minimize objective) directly into the private profile store.
        binding = stored.bindings[0].model_copy(update={"reach_tolerance": 5.0})
        corrupted = stored.model_copy(update={"bindings": (binding,) + stored.bindings[1:]})
        store._evaluation_profiles[(TENANT, "scenario-1")] = corrupted
        response = client.get(PROFILE_PATH, headers=HEADERS)
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == ErrorCode.INTEGRITY_ERROR.value
        # The generic safe message leaks no values: no target, tolerance,
        # scale, metadata value, hash, or internal reason.
        message = json.dumps(body)
        assert "5.0" not in message and "100.0" not in message
        assert "reach_tolerance" not in message
        assert "0" * 64 not in message

    def test_corrupted_stored_profile_evaluations_409_integrity_error(
        self, client: TestClient
    ) -> None:
        from tests.phase23_helpers import self_consistent_profile_copy

        store, _matrix, _run_ids = verified_evaluation_campaign()
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        tampered = self_consistent_profile_copy(stored, metadata={"note": "tampered"})
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.INTEGRITY_ERROR.value

    def test_unknown_scenario_404(self, client: TestClient) -> None:
        _install_store(client, InMemoryScenarioStore())
        response = client.post(PROFILE_PATH, json=VALID_BODY, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_duplicate_declaration_409(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        _declare_via_api(client)
        response = client.post(PROFILE_PATH, json=VALID_BODY, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.CONFLICT.value

    def test_declaration_after_compilation_409(self, client: TestClient) -> None:
        from kalhas.application.world_compiler import compile_world

        from tests.phase23_helpers import build_evaluation_scenario

        store = InMemoryScenarioStore()
        scenario = build_evaluation_scenario()
        store.put_scenario(scenario)
        compiled = compile_world(scenario)
        store.put_world(compiled.version, compiled.manifest)
        _install_store(client, store)
        response = client.post(PROFILE_PATH, json=VALID_BODY, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.CONFLICT.value

    def test_reversed_binding_order_identical_profile(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        first = _declare_via_api(client)
        _install_store(client, _scenario_only_store())
        reversed_body = dict(VALID_BODY)
        bindings = cast(list[dict[str, object]], VALID_BODY["bindings"])
        reversed_body["bindings"] = list(reversed(bindings))
        second = _declare_via_api(client, reversed_body)
        assert first == second

    @pytest.mark.parametrize(
        "forged",
        [
            {"direction": "maximize"},
            {"target": 50.0},
            {"weight": 9.0},
            {"metric_unit": "units"},
            {"identifier": "evaluation-profile-123"},
            {"tenant_id": TENANT},
            {"scenario_id": "scenario-1"},
            {"scenario_content_hash": "0" * 64},
            {"schema_version": "1.0.0"},
            {"content_hash": "0" * 64},
        ],
    )
    def test_forged_authoritative_fields_rejected_422(
        self, client: TestClient, forged: dict[str, object]
    ) -> None:
        _install_store(client, _scenario_only_store())
        bindings = cast(list[dict[str, object]], VALID_BODY["bindings"])
        binding = dict(bindings[0])
        binding.update(forged)
        body = dict(VALID_BODY)
        body["bindings"] = [binding] + bindings[1:]
        response = client.post(PROFILE_PATH, json=body, headers=HEADERS)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_unknown_objective_422(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        body = dict(VALID_BODY)
        bindings = cast(list[dict[str, object]], VALID_BODY["bindings"])
        bindings = [dict(bindings[0], objective_id="obj-zzz")] + bindings[1:]
        body["bindings"] = bindings
        response = client.post(PROFILE_PATH, json=body, headers=HEADERS)
        assert response.status_code == 422
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_unknown_metric_422(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        body = dict(VALID_BODY)
        bindings = cast(list[dict[str, object]], VALID_BODY["bindings"])
        bindings = [dict(bindings[0], metric_id="m-zzz")] + bindings[1:]
        body["bindings"] = bindings
        response = client.post(PROFILE_PATH, json=body, headers=HEADERS)
        assert response.status_code == 422
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_incomplete_coverage_422(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        body = dict(VALID_BODY)
        body["bindings"] = cast(list[object], VALID_BODY["bindings"])[:-1]
        response = client.post(PROFILE_PATH, json=body, headers=HEADERS)
        assert response.status_code == 422
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_empty_bindings_422(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        response = client.post(
            PROFILE_PATH,
            json={"bindings": [], "declared_at": "2026-01-05T12:00:00Z"},
            headers=HEADERS,
        )
        assert response.status_code == 422
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_reach_without_target_422(self, client: TestClient) -> None:
        from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection

        from tests.phase23_helpers import build_evaluation_scenario

        objectives = [
            Objective(
                identifier="obj-b",
                description="Minimize",
                direction=ObjectiveDirection.MINIMIZE,
                target=100.0,
                weight=1.0,
            ),
            Objective(
                identifier="obj-a",
                description="Maximize",
                direction=ObjectiveDirection.MAXIMIZE,
                target=None,
                weight=2.0,
            ),
            Objective(
                identifier="obj-c",
                description="Reach without target",
                direction=ObjectiveDirection.REACH,
                target=None,
                weight=3.0,
            ),
        ]
        store = InMemoryScenarioStore()
        store.put_scenario(
            build_evaluation_scenario().model_copy(update={"objectives": objectives})
        )
        _install_store(client, store)
        response = client.post(PROFILE_PATH, json=VALID_BODY, headers=HEADERS)
        assert response.status_code == 422
        assert response.json()["code"] == ErrorCode.VALIDATION_ERROR.value

    def test_bool_and_non_finite_values_422(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        body = dict(VALID_BODY)
        bindings = cast(list[dict[str, object]], VALID_BODY["bindings"])
        bindings = [dict(bindings[0], normalization_scale=True)] + bindings[1:]
        body["bindings"] = bindings
        response = client.post(PROFILE_PATH, json=body, headers=HEADERS)
        assert response.status_code == 422
        # NaN cannot be sent through TestClient json=; send a raw body.
        nan_body = (
            '{"bindings": [{"objective_id": "obj-c", "metric_id": "m-1", '
            '"reach_tolerance": 5.0, "normalization_scale": NaN},'
            '{"objective_id": "obj-a", "metric_id": "m-2", "normalization_scale": 20.0},'
            '{"objective_id": "obj-b", "metric_id": "m-1", "normalization_scale": 100.0}],'
            '"declared_at": "2026-01-05T12:00:00Z", "metadata": {}}'
        )
        response = client.post(
            PROFILE_PATH,
            content=nan_body,
            headers={**HEADERS, "content-type": "application/json"},
        )
        assert response.status_code == 422, response.text

    def test_post_records_no_operational_activity(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        _declare_via_api(client)
        response = client.get("/v1/operational-activity", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["events"] == []

    def test_no_update_or_delete_surface(self, client: TestClient) -> None:
        _install_store(client, _scenario_only_store())
        assert client.put(PROFILE_PATH, json=VALID_BODY, headers=HEADERS).status_code == 405
        assert client.delete(PROFILE_PATH, headers=HEADERS).status_code == 405


class TestObjectiveEvaluationsApi:
    def test_get_returns_200_with_direct_matrix(self, client: TestClient) -> None:
        store, matrix, _run_ids = verified_evaluation_campaign()
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["campaign_id"] == "campaign-1"
        assert body["runtime_version"] == "2.0.0"
        assert body["comparison_mode"] == "identical_conditions"
        assert body["identifier"].startswith("objective-evaluation-matrix-")
        assert len(body["content_hash"]) == 64
        assert body["ordered_objective_ids"] == ["obj-b", "obj-a", "obj-c"]
        assert len(body["cells"]) == 5 * 1 * 3
        assert body["evaluation_profile_id"] == matrix.evaluation_profile_id
        assert body["source_metric_observation_matrix_id"] == (
            matrix.source_metric_observation_matrix_id
        )

    def test_repeated_get_is_byte_identical(self, client: TestClient) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        _install_store(client, store)
        first = client.get(EVALUATIONS_PATH, headers=HEADERS)
        second = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert first.status_code == 200
        assert first.content == second.content

    def test_get_never_stores_or_mutates(self, client: TestClient) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        _install_store(client, store)
        snapshot = _snapshot(store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 200
        assert _snapshot(store) == snapshot
        assert store._campaign_statuses  # campaign still present, untouched

    def test_missing_profile_404(self, client: TestClient) -> None:
        store, _world_id, _run_ids = complete_observation_campaign()
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_non_complete_campaign_409_invalid_state(self, client: TestClient) -> None:
        store, _world_id, _run_ids = complete_evaluation_campaign(execute=False)
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.INVALID_STATE.value

    def test_unknown_campaign_404(self, client: TestClient) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        _install_store(client, store)
        response = client.get(
            "/v1/campaigns/campaign-unknown/objective-evaluations", headers=HEADERS
        )
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_foreign_tenant_404(self, client: TestClient) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers={**HEADERS, "X-Tenant-ID": OTHER_TENANT})
        assert response.status_code == 404
        assert response.json()["code"] == ErrorCode.NOT_FOUND.value

    def test_error_bodies_never_leak_values(self, client: TestClient) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        from tests.phase23_helpers import self_consistent_profile_copy

        tampered = self_consistent_profile_copy(stored, metadata={"note": "tampered"})
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        _install_store(client, store)
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == ErrorCode.INTEGRITY_ERROR.value
        message = json.dumps(response.json())
        # Raw values, targets, tolerances, scales, and hashes never leak.
        assert "91" not in message and "100.0" not in message
        assert "tampered" not in message
        assert "0" * 64 not in message

    def test_error_shape_is_api_error_response(self, client: TestClient) -> None:
        _install_store(client, InMemoryScenarioStore())
        response = client.get(EVALUATIONS_PATH, headers=HEADERS)
        parsed = ApiErrorResponse.model_validate(response.json())
        assert parsed.code is ErrorCode.NOT_FOUND


class TestOpenApi:
    def test_phase23_paths_exposed_with_get_only_campaign_endpoint(
        self, client: TestClient
    ) -> None:
        app = cast(FastAPI, client.app)
        spec = app.openapi()
        profile_path = "/v1/scenarios/{scenario_id}/evaluation-profile"
        evaluations_path = "/v1/campaigns/{campaign_id}/objective-evaluations"
        assert set(spec["paths"][profile_path]) == {"post", "get"}
        assert set(spec["paths"][evaluations_path]) == {"get"}
        assert "CampaignObjectiveEvaluationMatrix" in spec["components"]["schemas"]
        assert "ScenarioEvaluationProfile" in spec["components"]["schemas"]
        assert "ObjectiveEvaluationProfileDeclarationRequest" in (spec["components"]["schemas"])
