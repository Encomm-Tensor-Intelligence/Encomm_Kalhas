"""Phase 24 API tests: uncertainty-model and world-realization endpoints.

Proves the three Phase 24 endpoints - POST/GET
``/v1/scenarios/{scenario_id}/uncertainty-model`` and GET
``/v1/campaigns/{campaign_id}/world-realizations`` - return the direct
contracts with the exact status codes (201/200/404/409 conflict/409
integrity_error/422), reject every forged authoritative field at the
request boundary, are tenant-scoped, never record operational activity,
never write during GETs, expose only the typed safe error shape with no
value leakage, and are visible through OpenAPI with the exact methods.
"""

from __future__ import annotations

import copy
import json
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix,
    UniformDistribution,
    WorldUncertaintyModel,
)

from tests.phase4_helpers import TENANT
from tests.phase24_helpers import (
    build_uncertainty_store,
    declare_model,
    prepared_campaign,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"
MODEL_PATH = "/v1/scenarios/scenario-1/uncertainty-model"
REALIZATIONS_PATH = "/v1/campaigns/campaign-1/world-realizations"

VALID_BODY: dict[str, object] = {
    "bindings": [
        {
            "manifest_id": "manifest-1",
            "state_model_id": "sm-1",
            "state_field_id": "level",
            "distribution": {"kind": "uniform", "low": 0.0, "high": 3.0},
            "rounding_policy": "nearest_ties_to_even",
            "lower_bound": None,
            "upper_bound": None,
        },
        {
            "manifest_id": "manifest-1",
            "state_model_id": "sm-1",
            "state_field_id": "ratio",
            "distribution": {
                "kind": "discrete",
                "values": [1, 1.0],
                "probabilities": [0.5, 0.5],
            },
        },
    ],
    "declared_at": "2026-01-04T12:00:00Z",
    "metadata": {},
}


def _store(client: TestClient) -> InMemoryScenarioStore:
    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    cast(FastAPI, client.app).state.store = store


def _fresh_client() -> TestClient:
    from kalhas.api.app import create_app

    client = TestClient(create_app())
    _install_store(client, InMemoryScenarioStore())
    return client


def _assert_error_shape(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    ApiErrorResponse.model_validate(body)
    assert body["code"] == code
    assert body["request_id"]
    if status == 422:
        # 422 validation details carry the standard request path
        # locations (matching the established API behavior); no leak
        # scan applies.
        return
    # The error body must not leak values, parameters, bounds, hashes,
    # state values, metadata, or internal reasons.
    serialized = json.dumps(body)
    for forbidden in (
        "sampled_raw_value",
        "realized_value",
        "distribution",
        "low",
        "high",
        "mean",
        "standard_deviation",
        "probabilities",
        "lower_bound",
        "upper_bound",
        "content_hash",
        "seed_content_hash",
        "state_field_value_kind",
        "metadata",
        "quantization",
        "sampler",
        "reason",
        "validator",
        "internal",
    ):
        assert forbidden not in serialized, f"error body leaked {forbidden!r}"


def _compiled_client() -> TestClient:
    """A client whose store has scenario + pack + state model, no model yet."""
    client = _fresh_client()
    _install_store(client, build_uncertainty_store())
    return client


class TestOpenAPI:
    def test_three_paths_visible(self) -> None:
        client = _fresh_client()
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        assert "/v1/scenarios/{scenario_id}/uncertainty-model" in paths
        assert "/v1/campaigns/{campaign_id}/world-realizations" in paths
        model_ops = paths["/v1/scenarios/{scenario_id}/uncertainty-model"]
        assert "post" in model_ops and "get" in model_ops
        assert "get" in paths["/v1/campaigns/{campaign_id}/world-realizations"]


class TestDeclarationEndpoint:
    def test_valid_declaration_returns_201(self) -> None:
        client = _compiled_client()
        response = client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        assert response.status_code == 201
        model = WorldUncertaintyModel.model_validate(response.json())
        # Canonical binding order: level before ratio.
        assert [b.state_field_id for b in model.bindings] == ["level", "ratio"]
        # Response is byte-identical on re-fetch.
        again = client.get(MODEL_PATH, headers=HEADERS)
        assert again.json() == response.json()

    def test_forged_authoritative_fields_rejected_at_request_boundary(self) -> None:
        client = _compiled_client()
        for key in (
            "identifier",
            "tenant_id",
            "scenario_id",
            "scenario_content_hash",
            "content_hash",
            "binding_id",
            "pack_id",
            "pack_version",
            "manifest_content_hash",
            "state_model_identifier",
            "state_model_id",
            "state_model_content_hash",
            "state_field_value_kind",
            "sampler_version",
            "quantization_policy",
            "quantization_fraction_bits",
        ):
            payload = copy.deepcopy(VALID_BODY)
            bindings = cast(list[dict[str, object]], payload["bindings"])
            payload["bindings"] = [dict(bindings[0])]
            cast(list[dict[str, object]], payload["bindings"])[0][key] = "forged"
            response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
            assert response.status_code == 422, key
            _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    def test_unknown_scenario_returns_404(self) -> None:
        client = _fresh_client()
        response = client.post(
            "/v1/scenarios/scenario-nope/uncertainty-model",
            headers=HEADERS,
            json=VALID_BODY,
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value)

    def test_foreign_tenant_scenario_returns_404(self) -> None:
        client = _compiled_client()
        response = client.post(MODEL_PATH, headers={"X-Tenant-ID": OTHER_TENANT}, json=VALID_BODY)
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value)

    def test_invalid_references_return_422(self) -> None:
        client = _compiled_client()
        cases = (
            {"manifest_id": "manifest-nope", "state_model_id": "sm-1", "state_field_id": "level"},
            {"manifest_id": "manifest-1", "state_model_id": "sm-nope", "state_field_id": "level"},
            {"manifest_id": "manifest-1", "state_model_id": "sm-1", "state_field_id": "nope"},
        )
        for overrides in cases:
            payload = copy.deepcopy(VALID_BODY)
            bindings = cast(list[dict[str, object]], payload["bindings"])
            payload["bindings"] = [dict(bindings[0])]
            cast(list[dict[str, object]], payload["bindings"])[0].update(overrides)
            response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
            assert response.status_code == 422
            _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    def test_unsupported_field_kind_returns_422(self) -> None:
        client = _compiled_client()
        payload = copy.deepcopy(VALID_BODY)
        bindings = cast(list[dict[str, object]], payload["bindings"])
        payload["bindings"] = [dict(bindings[0])]
        cast(list[dict[str, object]], payload["bindings"])[0]["state_field_id"] = "status"
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    def test_rounding_and_bound_rules_return_422(self) -> None:
        client = _compiled_client()
        payload = copy.deepcopy(VALID_BODY)
        bindings = cast(list[dict[str, object]], payload["bindings"])
        payload["bindings"] = [dict(bindings[0])]
        bindings = cast(list[dict[str, object]], payload["bindings"])
        bindings[0]["rounding_policy"] = None
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)
        bindings[0]["rounding_policy"] = "nearest_ties_to_even"
        bindings[0]["lower_bound"] = 5
        bindings[0]["upper_bound"] = 2
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    def test_invalid_distribution_returns_422(self) -> None:
        client = _compiled_client()
        payload = copy.deepcopy(VALID_BODY)
        bindings = cast(list[dict[str, object]], payload["bindings"])
        payload["bindings"] = [dict(bindings[0])]
        bindings = cast(list[dict[str, object]], payload["bindings"])
        bindings[0]["distribution"] = {"kind": "weibull", "shape": 1.0}
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)
        bindings[0]["distribution"] = {
            "kind": "uniform",
            "low": 0.0,
            "high": 1.0,
            "scale": 2.0,
        }
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    def test_duplicate_declaration_returns_409_conflict(self) -> None:
        client = _compiled_client()
        assert client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY).status_code == 201
        response = client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_declaration_after_compilation_returns_409_conflict(self) -> None:
        client = _compiled_client()
        store = _store(client)
        MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        response = client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_independently_optional_bounds_accepted(self) -> None:
        client = _compiled_client()
        payload = copy.deepcopy(VALID_BODY)
        bindings = cast(list[dict[str, object]], payload["bindings"])
        payload["bindings"] = [dict(bindings[0])]
        bindings = cast(list[dict[str, object]], payload["bindings"])
        bindings[0].pop("lower_bound")
        bindings[0]["upper_bound"] = 4
        response = client.post(MODEL_PATH, headers=HEADERS, json=payload)
        assert response.status_code == 201
        assert response.json()["bindings"][0]["upper_bound"] == 4

    def test_discrete_int_float_representation_preserved(self) -> None:
        client = _compiled_client()
        response = client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        assert response.status_code == 201
        bindings = response.json()["bindings"]
        ratio = next(b for b in bindings if b["state_field_id"] == "ratio")
        assert ratio["distribution"]["values"] == [1, 1.0]

    def test_declaration_records_no_activity(self) -> None:
        client = _compiled_client()
        client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        store = _store(client)
        assert store.list_operational_activity(TENANT, limit=100) == ()


class TestGetModelEndpoint:
    def test_valid_read_returns_200(self) -> None:
        client = _compiled_client()
        declared = client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY).json()
        response = client.get(MODEL_PATH, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == declared

    def test_unknown_and_foreign_return_404(self) -> None:
        client = _compiled_client()
        assert client.get(MODEL_PATH, headers=HEADERS).status_code == 404
        client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        response = client.get(MODEL_PATH, headers={"X-Tenant-ID": OTHER_TENANT})
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value)

    def test_tampered_stored_record_returns_409_integrity(self) -> None:
        client = _compiled_client()
        client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        store = _store(client)
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"content_hash": "f" * 64})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        response = client.get(MODEL_PATH, headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_get_records_no_activity(self) -> None:
        client = _compiled_client()
        client.post(MODEL_PATH, headers=HEADERS, json=VALID_BODY)
        client.get(MODEL_PATH, headers=HEADERS)
        assert _store(client).list_operational_activity(TENANT, limit=100) == ()


class TestRealizationsEndpoint:
    def test_valid_present_model_returns_200_with_k_realizations(self) -> None:
        client = _compiled_client()
        store = _store(client)
        model = declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        assert model is not None
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        assert response.status_code == 200
        matrix = CampaignWorldRealizationMatrix.model_validate(response.json())
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert len(matrix.realizations) == len(campaign.seed_ensemble)

    def test_absent_model_returns_200_with_empty_realizations(self) -> None:
        client = _compiled_client()
        store = _store(client)
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        assert response.status_code == 200
        matrix = CampaignWorldRealizationMatrix.model_validate(response.json())
        assert matrix.uncertainty_model_id is None
        assert all(r.sampled_values == () for r in matrix.realizations)

    def test_exactly_k_never_k_times_s(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        seeds = tuple(
            ScenarioSeed(
                identifier=f"seed-{index}",
                tenant_id=TENANT,
                algorithm="deterministic",
                seed_value="v1",
            )
            for index in range(3)
        )
        prepared_campaign(store, world_version_id=compiled.version.identifier, seeds=seeds)
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        matrix = CampaignWorldRealizationMatrix.model_validate(response.json())
        # The mock LEGION ensemble always yields five candidates.
        assert len(matrix.realizations) == 3
        assert len(store.get_campaign(TENANT, "campaign-1").strategy_candidate_ids) == 5

    def test_no_strategy_ids_in_response(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        assert response.status_code == 200
        assert "mock-" not in response.text
        assert "strategy" not in response.text

    def test_repeated_response_byte_identical(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        first = client.get(REALIZATIONS_PATH, headers=HEADERS)
        second = client.get(REALIZATIONS_PATH, headers=HEADERS)
        assert first.json() == second.json()

    def test_no_lifecycle_gate(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        baseline = client.get(REALIZATIONS_PATH, headers=HEADERS).json()
        # Any recorded state returns the same bytes.
        from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
        from kalhas.contracts.v1.shared import AwareDatetime

        from tests.phase4_helpers import NOW

        changed_at: AwareDatetime = NOW
        for state in (
            CampaignState.DRAFT,
            CampaignState.VALIDATED,
            CampaignState.COMPLETE,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        ):
            store.update_campaign_status(
                TENANT,
                "campaign-1",
                CampaignStatus(
                    identifier="status-campaign-1",
                    tenant_id=TENANT,
                    schema_version="1.0.0",
                    campaign_id="campaign-1",
                    state=state,
                    changed_at=changed_at,
                    message="test",
                ),
            )
            assert client.get(REALIZATIONS_PATH, headers=HEADERS).json() == baseline

    def test_unknown_campaign_returns_404(self) -> None:
        client = _compiled_client()
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value)

    def test_deterministic_failing_seed_returns_409_conflict(self) -> None:
        client = _compiled_client()
        store = _store(client)
        store = build_uncertainty_store(level_allowed=(0, 1))
        _install_store(client, store)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        failing_seed = ScenarioSeed(
            identifier="seed-fail-0",
            tenant_id=TENANT,
            algorithm="deterministic",
            seed_value="v1",
        )
        prepared_campaign(
            store,
            world_version_id=compiled.version.identifier,
            seeds=(failing_seed,),
        )
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_missing_world_returns_409_integrity(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._worlds[(TENANT, campaign.world_version_id)]
        response = client.get(REALIZATIONS_PATH, headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_get_performs_no_writes_and_no_activity(self) -> None:
        client = _compiled_client()
        store = _store(client)
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepared_campaign(store, world_version_id=compiled.version.identifier)
        before_worlds = dict(store._worlds)
        before_models = dict(store._world_uncertainty_models)
        client.get(REALIZATIONS_PATH, headers=HEADERS)
        assert store._worlds == before_worlds
        assert store._world_uncertainty_models == before_models
        assert store.list_operational_activity(TENANT, limit=100) == ()
