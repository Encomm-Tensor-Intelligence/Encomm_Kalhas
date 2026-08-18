"""Tests for the Phase 26 campaign outcome-distribution API surface.

Tests for ``kalhas/api/routes_campaign_outcome.py``, the single
``GET /v1/campaigns/{campaign_id}/outcome-distributions`` operation, its
registration in ``create_app``, the API error mapping of
``CampaignOutcomeDistributionMatrixIntegrityError``, and the additive
public-contract registration at ``PUBLIC_CONTRACTS`` index 46 with its
generated JSON Schema artifact. Proves:

- a real profile-bearing COMPLETE runtime-3 lifecycle returns 200 with
  the exact strategy-major/objective-minor empirical evidence, and the
  response equals the direct verified-query output exactly;
- repeated GETs return identical JSON and change no store state,
  lifecycle, activity, execution, observation, profile, world, or
  upstream artifact;
- required X-Tenant-ID behavior, tenant isolation, and indistinguishable
  unknown/foreign campaigns;
- valid-runtime non-COMPLETE campaigns map to 409 INVALID_STATE;
- empty, legacy, unsupported, and mixed recorded run plans fail 409
  CONFLICT before the outcome query (complete-tuple inspection, no
  first-element dispatch), and query parameters cannot select runtime;
- missing embedded profile maps to 404; missing/corrupted/mismatched
  stored profile, world, uncertainty, execution, or first/middle/last
  observation sources map safely to 409 INTEGRITY_ERROR with no partial
  response and no internal-reason leakage;
- the exact generic 409 INTEGRITY_ERROR body for the outcome integrity
  error; zero query calls on runtime-gate failure and exactly one on
  success; no POST/PUT/PATCH/DELETE on the path; GET records no
  operational activity;
- OpenAPI exposes exactly the new GET with the required X-Tenant-ID
  header, no request body, no runtime selector, and a 200 $ref to
  CampaignOutcomeDistributionMatrix, while the six Phase 25 paths/seven
  operations remain unchanged;
- PUBLIC_CONTRACTS is exactly 50 with unchanged indexes 0-46, the
  matrix at index 46, and the decision contracts at indexes 47-49;
  the two nested value objects stay unregistered;
- exactly 50 schema artifacts exist with all 46 historical byte hashes
  unchanged and the new artifacts matching ``model_json_schema``;
- route/app/error modules carry no ranking/recommendation, NEXUS/LEGION,
  live-action, nondeterministic, network, filesystem, database, or
  provider surface.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import realization_campaign_service
from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    EmpiricalDistributionSummary,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection
from kalhas.contracts.v1.world_realization import DiscreteDistribution
from pydantic import BaseModel

from tests.phase4_helpers import NOW, TENANT, build_request, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import uncertainty_fields
from tests.phase25_helpers import (
    ACCEPTANCE_BRANCH_X,
    ACCEPTANCE_BRANCH_Y,
    ACCEPTANCE_SEEDS,
    ACCEPTANCE_VALUE_X,
    ACCEPTANCE_VALUE_Y,
    acceptance_legion,
    acceptance_observation_store,
    inject_unsupported_recorded_runtime,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"

OUTCOME_PATH = "/v1/campaigns/{campaign_id}/outcome-distributions"

#: The six Phase 25 runtime-3 paths and their exact operations.
REALIZATION_PATHS: dict[str, set[str]] = {
    "/v1/runs/{run_id}/realization-trajectory-execution": {"get"},
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest": {"get"},
    "/v1/runs/{run_id}/realization-metric-observations": {"get", "post"},
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-statistics": {"get"},
}

#: The exact 46 historical public-contract names in registry order.
_HISTORICAL_46_NAMES = (
    "ScenarioSpec",
    "ContextBundle",
    "ClarificationQuestion",
    "ValidationReport",
    "WorldManifest",
    "WorldVersion",
    "UncertaintyDefinition",
    "StrategyRequest",
    "StrategyCandidate",
    "CampaignSpec",
    "CampaignStatus",
    "ScenarioSeed",
    "RunEvent",
    "OutcomeVector",
    "EvidenceReference",
    "DecisionBrief",
    "RunPlan",
    "RunStatus",
    "ReplayManifest",
    "RunInputIntegrityManifest",
    "DomainPackManifest",
    "DomainPackBinding",
    "DomainCapabilityDeclaration",
    "DomainStateModel",
    "DomainStateTransition",
    "OperationalActivityEvent",
    "StrategyTrajectoryPlan",
    "StrategyTrajectoryPlanRequest",
    "RunTrajectoryExecution",
    "RunTrajectoryReplayManifest",
    "CampaignTrajectoryMatrix",
    "DomainMetricObservationBinding",
    "RunMetricObservationSet",
    "CampaignMetricObservationMatrix",
    "CampaignMetricStatisticsMatrix",
    "ScenarioEvaluationProfile",
    "CampaignObjectiveEvaluationMatrix",
    "WorldUncertaintyModel",
    "WorldRealization",
    "CampaignWorldRealizationMatrix",
    "RealizationRunTrajectoryExecution",
    "RealizationRunTrajectoryReplayManifest",
    "RealizationCampaignTrajectoryMatrix",
    "RealizationRunMetricObservationSet",
    "RealizationCampaignMetricObservationMatrix",
    "RealizationCampaignMetricStatisticsMatrix",
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "kalhas" / "api" / "routes_campaign_outcome.py"
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

#: SHA-256 of every historical schema artifact (byte-identity anchor).
_HISTORICAL_SCHEMA_HASHES: dict[str, str] = {}


def _load_historical_schema_hashes() -> dict[str, str]:
    """The 46 historical schema byte hashes, probed once and hard-coded."""
    return {
        "CampaignMetricObservationMatrix.schema.json": (
            "17813be26e7bfb3a944518235f49f3a9554f23b2c8f12a5d63c9ee3480fc4fe7"
        ),
        "CampaignMetricStatisticsMatrix.schema.json": (
            "ef4f7f18ab7dcf5fbee645bb6ccd0ab3969ca4ec88a995919a452650f64af6fa"
        ),
        "CampaignObjectiveEvaluationMatrix.schema.json": (
            "971673f5d994b9bed2e3e6b26a869426252662102df90a61a0c5365579aa0660"
        ),
        "CampaignSpec.schema.json": (
            "e68ce16b61a9d8352a23e1d58d54d2bb305901ba1191de0ac2ed556bd9ca5115"
        ),
        "CampaignStatus.schema.json": (
            "0135ee400b0981416760d0cad956e8bedb80f866b0f1daf2020525dda06536b4"
        ),
        "CampaignTrajectoryMatrix.schema.json": (
            "ed0e5c69dddf11ffc15cfa3642afbb8e708616421a38a378f2f41b7a82b25de8"
        ),
        "CampaignWorldRealizationMatrix.schema.json": (
            "3dc88833cbf50e441a4c2d8554e6dd2172dcb6b91feaeef798df1c23336f5019"
        ),
        "ClarificationQuestion.schema.json": (
            "bd8edd0d1ce5f1617a7c7c02348fe11e7f65603aaba3632418b89b4c8e7fd111"
        ),
        "ContextBundle.schema.json": (
            "65ca52ca02b0dd482a813365133f73a476ffdc0a45d7c0aebf587f53ca68bdca"
        ),
        "DecisionBrief.schema.json": (
            "77f5662535eb1feb98dd01d108226089add5eb778282a7e1c4e1925293397694"
        ),
        "DomainCapabilityDeclaration.schema.json": (
            "99b633fa8cdcccce2f69a45f54d54200ff6946691af7e827457fd5ffafbf421c"
        ),
        "DomainMetricObservationBinding.schema.json": (
            "2af4015aa2321e45eb05d5f21e77fe27c210af22976552f5757396079bf2f406"
        ),
        "DomainPackBinding.schema.json": (
            "1e0778e40558ff4c536b750fda3db602d860ff5da40aea2151d2c79b569a28e5"
        ),
        "DomainPackManifest.schema.json": (
            "38fbe9648c867a9a4f1bbb8740bf55d23d0103d7d3bc9b9aa1d033719f3c954c"
        ),
        "DomainStateModel.schema.json": (
            "0db1493626983d5c736f9705bdc87bd53fa43b1f2baae807d2d490ea51a94fd2"
        ),
        "DomainStateTransition.schema.json": (
            "75fc8312530022e08fb076c0a21b12ee07675a5543f088dc2ddbc208b08974ef"
        ),
        "EvidenceReference.schema.json": (
            "e41283496760ffde289b264be718a3deb67183a51201c0e5eb0788ece06c2187"
        ),
        "OperationalActivityEvent.schema.json": (
            "d5ba27f3a38dd8dcdb041d571dfcd5f720cc1a01a2c876ecffdc36efea664e33"
        ),
        "OutcomeVector.schema.json": (
            "bde3eb81b149bd42ac4d50772619f9f42a5aa5a3b0030dda7e57a75da9c0b188"
        ),
        "RealizationCampaignMetricObservationMatrix.schema.json": (
            "70cfc1f29be0260f4697c2b07a868a9acec9d53461a4f1f376bafb7270bd463d"
        ),
        "RealizationCampaignMetricStatisticsMatrix.schema.json": (
            "24759039fa4f1b6a3287dc7600f35973714fb3070060cabdfc419f0a13988555"
        ),
        "RealizationCampaignTrajectoryMatrix.schema.json": (
            "c7fdfe5207aeaf39c3100715b3dcb90696124cb54f45ba92d4a6fadaf2629e6c"
        ),
        "RealizationRunMetricObservationSet.schema.json": (
            "43f2099b95b486cdad4a632a41f2de51691e36074e25519f4e6e6fd407b67527"
        ),
        "RealizationRunTrajectoryExecution.schema.json": (
            "bac48f1aeb65ea1578c3b0c8b9eb77ed65a0b0982b5b4cf9887eafd9022c8ae6"
        ),
        "RealizationRunTrajectoryReplayManifest.schema.json": (
            "537c8857aebf1453ba912e998e21523a07290acd5fc271335566f44ac19162ca"
        ),
        "ReplayManifest.schema.json": (
            "b831fcd69977755563b4426a197c6362e1f84ed113bd9c1601f70aa3208a0d30"
        ),
        "RunEvent.schema.json": (
            "41b1cd0fac975c1ab909a51f263ea91b8fa6cd3fead578027a561d73f005f3f3"
        ),
        "RunInputIntegrityManifest.schema.json": (
            "518600f95bdc1e5be57479f0f4a67ccb033b3b5b74e471bf1f6571fb426e9641"
        ),
        "RunMetricObservationSet.schema.json": (
            "a5fc9e36e1a3a3c053a0ff5ce2d1bcc28e77c2d8b222f8e65f4c040891be536f"
        ),
        "RunPlan.schema.json": ("389532cd2290423df2246e6400a89e6a11fc82713208163214e4ab9d66d25d6b"),
        "RunStatus.schema.json": (
            "ba7293fad11ba41d92b417536104698af09cabff261b0523920b2a357437ff8e"
        ),
        "RunTrajectoryExecution.schema.json": (
            "c6c720f316f773231460eb82c141cd94a3e6d4a4e7dd69d8e45362b2b48383cd"
        ),
        "RunTrajectoryReplayManifest.schema.json": (
            "df7135d173429d19810b1dbf01fd13474184d00e02d263501f1905534d8dff9d"
        ),
        "ScenarioEvaluationProfile.schema.json": (
            "203f80186d6aca5b4586e994c9df749bfbe0db1a152e0ffe761acbdf41859f95"
        ),
        "ScenarioSeed.schema.json": (
            "c4b7d433258f2bd3aa8d544d9f8815c1d0a30603e54fc3174eff6798d353de8c"
        ),
        "ScenarioSpec.schema.json": (
            "fe0e53ab76371dfb8f502b5074391ea3ba68803503ef91799cbaa9106676502d"
        ),
        "StrategyCandidate.schema.json": (
            "ac501ade1683ec6b3540589c11d9338cbf41d2372ee81f351f4205b28db7efd9"
        ),
        "StrategyRequest.schema.json": (
            "79ce7c69f0314b66fd625f2b0920bc004c9aa645d038bee86137b84dbbff504b"
        ),
        "StrategyTrajectoryPlan.schema.json": (
            "854d465373526a364fe3de9ea58d5c6e657751a55343f229faf8cc510760019a"
        ),
        "StrategyTrajectoryPlanRequest.schema.json": (
            "a9c091880c33545f6c6cb854749b48a3e8e59273ecb0431dfa338930a22f21ef"
        ),
        "UncertaintyDefinition.schema.json": (
            "524f60948c75ac93bc3e065a359574d4b75a60e6ab9390ff22d79885a7780a33"
        ),
        "ValidationReport.schema.json": (
            "cde7fad0019df68a125a1ac8ec1ab9047679d2e91fcfd8b13f91cc0530d07ea8"
        ),
        "WorldManifest.schema.json": (
            "abb778f8b78b1096bd262ad6a8492234e08f26f50a900d898e83f384ef54f697"
        ),
        "WorldRealization.schema.json": (
            "cd0d4b0a9059c78cf44e93f89077602caf18555597e51a579becad56b6e35029"
        ),
        "WorldUncertaintyModel.schema.json": (
            "2a6404a39e4c4bcce3f4b3d7e0f91f4e9fadef33747d7a8b0c68598448920a31"
        ),
        "WorldVersion.schema.json": (
            "d4f9acd67e035d5b2e6ccc8379938c324f71826c7ae57a196092afd9e872b867"
        ),
    }


_HISTORICAL_SCHEMA_HASHES = _load_historical_schema_hashes()

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")

#: The five authoritative scenario objectives of the API fixture.
_ACCEPTANCE_OBJECTIVES = (
    Objective(
        identifier="obj-1",
        description="Minimize the primary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-2",
        description="Maximize the primary metric",
        direction=ObjectiveDirection.MAXIMIZE,
        target=90.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-3",
        description="Reach the primary metric target band",
        direction=ObjectiveDirection.REACH,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-4",
        description="Optimize the primary metric downward",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-5",
        description="Optimize the primary metric upward",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=1.0,
    ),
)

#: The caller-owned profile drafts (every objective bound to metric m-1).
_ACCEPTANCE_PROFILE_DRAFTS = (
    ObjectiveMetricBindingDraft(
        objective_id="obj-1", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-2", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-3",
        metric_id="m-1",
        reach_tolerance=5.0,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-4", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-5", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
)

#: The store collections whose complete state must never change.
_STORE_COLLECTIONS = (
    "_worlds",
    "_manifests",
    "_campaigns",
    "_campaign_statuses",
    "_run_plans",
    "_run_statuses",
    "_evaluation_profiles",
    "_world_uncertainty_models",
    "_operational_activity",
    "_realization_run_trajectory_executions",
    "_realization_run_metric_observation_sets",
)


def _declared_profile_store() -> InMemoryScenarioStore:
    """The real profile-bearing runtime-3 acceptance lifecycle.

    The evaluation profile is declared through the real declaration
    service **before** world compilation, so the compiled world embeds
    the exact profile snapshot; the campaign is prepared (two
    strategies, seeds seed-0/seed-2), planned, started, fully executed,
    and every observation set explicitly extracted through the real
    services. Nothing is patched or injected.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario().model_copy(
        update={"objectives": list(_ACCEPTANCE_OBJECTIVES)}
    )
    store.put_scenario(scenario)
    _register_pack(store)
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=uncertainty_fields(),
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-x",
        description="X branch transition",
        guard_values={"level": ACCEPTANCE_BRANCH_X},
        target_values={"level": ACCEPTANCE_VALUE_X},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-y",
        description="Y branch transition",
        guard_values={"level": ACCEPTANCE_BRANCH_Y},
        target_values={"level": ACCEPTANCE_VALUE_Y},
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-1",
        state_field_id="level",
        declared_at=DECLARED_AT,
    )
    declare_world_uncertainty_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=(
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-1",
                state_field_id="level",
                distribution=DiscreteDistribution(
                    kind="discrete",
                    values=(ACCEPTANCE_BRANCH_X, ACCEPTANCE_BRANCH_Y),
                    probabilities=(0.5, 0.5),
                ),
                rounding_policy="nearest_ties_to_even",
            ),
        ),
        declared_at=DECLARED_AT,
    )
    declare_scenario_evaluation_profile(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=_ACCEPTANCE_PROFILE_DRAFTS,
        declared_at=DECLARED_AT,
        metadata={},
    )
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    with mock.patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 2):
        prepare_realization_campaign(
            store=store,
            legion=acceptance_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-1",
            campaign_name="Outcome API acceptance campaign",
            seed_ensemble=ACCEPTANCE_SEEDS,
            created_at=NOW,
        )
    prepare_strategy_trajectory_plans(
        store=store, legion=acceptance_legion(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store


def _expected_observed_value(store: InMemoryScenarioStore, campaign: Any, seed: Any) -> int:
    """The causally expected observed value of one seed under the fixture world."""
    world = store.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    realization = build_world_realization(
        world=world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
        seed=seed,
        realized_at=campaign.created_at,
    )
    level = next(
        override.value
        for override in realization.realized_initial_state_overrides
        if override.state_field_id == "level"
    )
    assert isinstance(level, int)
    if level == ACCEPTANCE_BRANCH_X:
        return ACCEPTANCE_VALUE_X
    if level == ACCEPTANCE_BRANCH_Y:
        return ACCEPTANCE_VALUE_Y
    raise AssertionError(f"unexpected realized level {level}")


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _store(client: TestClient) -> InMemoryScenarioStore:
    return cast(InMemoryScenarioStore, _app(client).state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    _app(client).state.store = store


def _dump_value(value: object) -> object:
    """One canonical JSON dump of a stored record or record tuple."""
    if isinstance(value, tuple):
        return tuple(_dump_value(item) for item in value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _store_state(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest of the complete store state."""
    payload: dict[str, object] = {}
    for name in _STORE_COLLECTIONS:
        collection = getattr(store, name)
        payload[name] = {repr(key): _dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)


def _assert_error_shape(
    response: Any,
    status: int,
    code: str,
    *,
    leak_scan: bool = True,
) -> None:
    """Assert the typed safe error body and run the no-leak scan."""
    assert response.status_code == status
    body = response.json()
    ApiErrorResponse.model_validate(body)
    assert body["code"] == code
    assert body["request_id"]
    if leak_scan:
        _assert_no_leak(body)


def _assert_no_leak(body: dict[str, Any]) -> None:
    """The error body must not leak hashes, foreign ids, values, or reasons."""
    serialized = json.dumps(body)
    assert not _HASH_PATTERN.search(serialized), "error body leaks a content hash"
    for forbidden in (
        OTHER_TENANT,
        "content_hash",
        "metadata",
        "reason",
        "seed-1",
        "seed-2",
        "level",
        "ratio",
        "target",
        "sampled",
        "realized",
    ):
        assert forbidden not in serialized, f"error body leaks {forbidden!r}: {serialized}"


@pytest.fixture(scope="module")
def outcome_store() -> InMemoryScenarioStore:
    """The real executed profile-bearing acceptance store (built once)."""
    return _declared_profile_store()


@pytest.fixture()
def store(outcome_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the real lifecycle store."""
    return copy.deepcopy(outcome_store)


class TestOpenApiSurface:
    """The OpenAPI contract of the new operation."""

    def test_exactly_one_new_path_and_operation(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        new_paths = {
            path: set(ops) for path, ops in paths.items() if "outcome-distributions" in path
        }
        assert new_paths == {OUTCOME_PATH: {"get"}}

    def test_new_operation_refs_campaign_outcome_matrix(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        operation = spec["paths"][OUTCOME_PATH]["get"]
        ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref == "#/components/schemas/CampaignOutcomeDistributionMatrix"
        assert "CampaignOutcomeDistributionMatrix" in spec["components"]["schemas"]

    def test_required_tenant_header_no_body_no_runtime_selector(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        operation = spec["paths"][OUTCOME_PATH]["get"]
        parameters = operation.get("parameters", [])
        headers = [parameter for parameter in parameters if parameter["in"] == "header"]
        assert headers == [
            {
                "name": "X-Tenant-ID",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "title": "X-Tenant-Id"},
            }
        ]
        queries = [parameter for parameter in parameters if parameter["in"] == "query"]
        assert queries == []
        assert "requestBody" not in operation
        assert all("runtime" not in str(parameter).lower() for parameter in parameters)

    def test_phase25_six_paths_seven_operations_unchanged_plus_one(
        self, client: TestClient
    ) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        realization_paths = {
            path: set(ops) for path, ops in paths.items() if "realization-" in path
        }
        assert realization_paths == REALIZATION_PATHS
        assert sum(len(ops) for ops in REALIZATION_PATHS.values()) == 7
        assert set(paths[OUTCOME_PATH]) == {"get"}

    def test_openapi_components_include_nested_value_objects(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        schemas = spec["components"]["schemas"]
        matrix = schemas["CampaignOutcomeDistributionMatrix"]
        assert matrix["properties"]["outcomes"]["items"]["$ref"] == (
            "#/components/schemas/StrategyObjectiveOutcome"
        )
        assert (
            schemas["StrategyObjectiveOutcome"]["properties"]["empirical_distribution"]["$ref"]
            == "#/components/schemas/EmpiricalDistributionSummary"
        )
        assert "EmpiricalDistributionSummary" in schemas
        assert "StrategyObjectiveOutcome" in schemas


class TestRealLifecycle:
    """The real profile-bearing HTTP proof."""

    def _get(self, client: TestClient, campaign_id: str = "campaign-1") -> Any:
        return client.get(OUTCOME_PATH.format(campaign_id=campaign_id), headers=HEADERS)

    def test_complete_profile_bearing_campaign_returns_200_and_evidence(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._get(client)
        assert response.status_code == 200
        body = response.json()
        matrix = CampaignOutcomeDistributionMatrix.model_validate(body)
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.ordered_strategy_candidate_ids == ("mock-a", "mock-b")
        assert matrix.ordered_scenario_seed_ids == ("seed-0", "seed-2")
        assert matrix.ordered_objective_ids == ("obj-1", "obj-2", "obj-3", "obj-4", "obj-5")
        assert matrix.ordered_metric_ids == ("m-1",)
        assert len(matrix.outcomes) == 10
        campaign = store.get_campaign(TENANT, "campaign-1")
        expected_by_seed = {
            seed.identifier: _expected_observed_value(store, campaign, seed)
            for seed in ACCEPTANCE_SEEDS
        }
        assert set(expected_by_seed.values()) == {84, 103}
        expected_values = tuple(
            expected_by_seed[seed_id] for seed_id in matrix.ordered_scenario_seed_ids
        )
        for strategy_position in range(2):
            for objective_position in range(5):
                outcome = matrix.outcomes[strategy_position * 5 + objective_position]
                assert outcome.ordered_observed_values == expected_values
        targeted = matrix.outcomes[0]
        assert targeted.direction == "minimize"
        assert targeted.target == 100.0
        assert targeted.target_achievement_count == 1
        assert targeted.empirical_target_achievement_probability == 0.5
        assert targeted.worst_normalized_target_violation == 0.03
        assert targeted.target_violation_cvar == 0.03
        assert targeted.adverse_tail_statistic == 103.0
        reach = matrix.outcomes[2]
        assert reach.direction == "reach"
        assert reach.worst_normalized_target_violation == 0.11
        assert reach.adverse_tail_statistic == 16.0
        optimization_only = matrix.outcomes[3]
        assert optimization_only.target is None
        assert optimization_only.target_achievement_count is None
        assert optimization_only.adverse_tail_statistic == 103.0

    def test_response_validates_exactly_as_campaign_outcome_distribution_matrix(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._get(client)
        assert response.status_code == 200
        matrix = CampaignOutcomeDistributionMatrix.model_validate(response.json())
        assert isinstance(matrix, CampaignOutcomeDistributionMatrix)
        assert isinstance(matrix.outcomes[0].empirical_distribution, EmpiricalDistributionSummary)
        assert isinstance(matrix.outcomes[0], StrategyObjectiveOutcome)

    def test_api_response_equals_direct_verified_query_output(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._get(client)
        assert response.status_code == 200
        direct = get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert response.json() == direct.model_dump(mode="json")

    def test_repeated_gets_identical_json_and_store_unchanged(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before = _store_state(store)
        first = self._get(client)
        second = self._get(client)
        third = self._get(client)
        assert first.status_code == 200
        assert second.json() == first.json()
        assert third.json() == first.json()
        assert canonical_json(second.json()) == canonical_json(first.json())
        assert _store_state(store) == before

    def test_get_records_no_operational_activity(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before_activity = store.list_operational_activity(TENANT)
        response = self._get(client)
        assert response.status_code == 200
        assert store.list_operational_activity(TENANT) == before_activity


class TestTenantAndValidation:
    """Tenant isolation and request validation."""

    def test_missing_tenant_header_422(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"))
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_unknown_and_foreign_campaign_are_indistinguishable_404(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        _assert_error_shape(
            client.get(OUTCOME_PATH.format(campaign_id="campaign-ghost"), headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        _assert_error_shape(
            client.get(
                OUTCOME_PATH.format(campaign_id="campaign-1"),
                headers={"X-Tenant-ID": OTHER_TENANT},
            ),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )

    def test_missing_embedded_profile_404(self, client: TestClient) -> None:
        store = acceptance_observation_store()
        _install_store(client, store)
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_valid_runtime_non_complete_campaign_409_invalid_state(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.DRAFT})
        )
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)


class TestRuntimeDispatch:
    """Recorded-runtime dispatch derives only from stored run plans."""

    def test_empty_run_plans_fail_409_conflict_before_query(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        # TEST-ONLY private-store mutation: an existing campaign with no
        # recorded run plans (corrupted/foreign recorded state).
        store._run_plans[(TENANT, "campaign-1")] = ()
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions"
        ) as spy:
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_legacy_runtime_one_fails_409_conflict_before_query(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[0])
        # TEST-ONLY private-store mutation: re-stamp the first plan and
        # its status to recorded legacy runtime 1.0.0.
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            plan.model_copy(update={"runtime_version": "1.0.0"})
            if plan.identifier == plans[0].identifier
            else plan
            for plan in store.get_run_plans(TENANT, "campaign-1")
        )
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(TENANT, run_id, status.model_copy(update={"runtime_version": "1.0.0"}))
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions"
        ) as spy:
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    @pytest.mark.parametrize("index", (0, 1, 3))
    def test_unsupported_runtime_at_first_middle_last_position_fails_before_query(
        self, client: TestClient, store: InMemoryScenarioStore, index: int
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[index])
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions"
        ) as spy:
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_mixed_runtimes_fail_closed_no_first_element_dispatch(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # Two different non-3.0.0 records in later positions: a
        # first-element-only dispatch would wrongly accept this tuple.
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[1])
        inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=plans[2], unsupported_version="1.0.0"
        )
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions"
        ) as spy:
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_query_parameters_cannot_select_or_alter_runtime_dispatch(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = client.get(
            OUTCOME_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            params={"runtime_version": "1.0.0"},
        )
        assert response.status_code == 200
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        response = client.get(
            OUTCOME_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            params={"runtime_version": "3.0.0"},
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)


class TestErrorMapping:
    """Typed API error mapping for the outcome surface."""

    def test_outcome_integrity_error_maps_to_exact_generic_409_body(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        store._evaluation_profiles[(TENANT, "scenario-1")] = stored.model_copy(
            update={"content_hash": "1" * 64}
        )
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)
        body = response.json()
        assert body["message"] == str(CampaignOutcomeDistributionMatrixIntegrityError("campaign-1"))
        assert "campaign-1" in body["message"]
        assert "reason" not in json.dumps(body)

    def test_missing_stored_profile_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_missing_world_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._worlds[(TENANT, campaign.world_version_id)]
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    @pytest.mark.parametrize("index", (0, 1, 3))
    def test_missing_first_middle_last_observation_source_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore, index: int
    ) -> None:
        _install_store(client, store)
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[index])
        del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_corrupted_stored_uncertainty_source_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(
            update={
                "bindings": tuple(
                    binding.model_copy(
                        update={
                            "distribution": binding.distribution.model_copy(
                                update={"probabilities": (0.25, 0.75)}
                            )
                        }
                    )
                    for binding in stored.bindings
                )
            }
        )
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_unsupported_runtime_409_conflict_no_leak(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_failed_queries_never_return_a_partial_matrix(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        before = _store_state(store)
        response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        assert response.status_code == 409
        assert "outcomes" not in response.text
        assert "ordered_strategy_candidate_ids" not in response.text
        assert _store_state(store) == before


class TestReadOnlyAndWiring:
    """Exact call-count wiring and strict read-only behavior."""

    def test_route_invokes_runtime_gate_and_query_exactly_once(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        original = get_verified_campaign_outcome_distributions
        events: list[str] = []

        def counting_query(*args: Any, **kwargs: Any) -> Any:
            events.append("query")
            return original(*args, **kwargs)

        original_get_run_plans = store.get_run_plans

        def counting_get_run_plans(*args: Any, **kwargs: Any) -> Any:
            events.append("plans")
            return original_get_run_plans(*args, **kwargs)

        store.get_run_plans = counting_get_run_plans  # type: ignore[method-assign]
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions",
            side_effect=counting_query,
        ):
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        assert response.status_code == 200
        # The route's recorded-runtime gate reads the run plans first
        # (before the query runs); the verified query internally reads
        # the plans once more through its accepted preflight.
        assert events[0] == "plans"
        assert events.count("query") == 1
        assert events.count("plans") >= 2

    def test_runtime_gate_failure_query_call_count_zero(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        store._run_plans[(TENANT, "campaign-1")] = ()
        with mock.patch(
            "kalhas.api.routes_campaign_outcome.get_verified_campaign_outcome_distributions"
        ) as spy:
            response = client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    @pytest.mark.parametrize("method", ("post", "put", "patch", "delete"))
    def test_no_other_http_methods_introduced(
        self, client: TestClient, store: InMemoryScenarioStore, method: str
    ) -> None:
        _install_store(client, store)
        response = client.request(
            method, OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 405, ErrorCode.METHOD_NOT_ALLOWED.value, leak_scan=False)


class TestContractRegistration:
    """PUBLIC_CONTRACTS indexes 46-49 and the schema artifact set."""

    def test_public_contracts_exactly_50_with_historical_prefix_and_new_tail(
        self,
    ) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) == 50
        assert names[:46] == _HISTORICAL_46_NAMES
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47] == "CampaignDecisionPolicy"
        assert names[48] == "CampaignStrategyComparison"
        assert names[49] == "CampaignDecisionBrief"

    def test_nested_value_objects_remain_unregistered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names
        assert "CampaignOutcomeDistributionMatrix" in names
        assert "ObjectiveMetricBinding" not in names

    def test_exactly_50_schema_artifacts_with_historical_hashes_unchanged(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 50
        by_name = {path.name: path for path in schema_files}
        assert len(_HISTORICAL_SCHEMA_HASHES) == 46
        for name, expected in _HISTORICAL_SCHEMA_HASHES.items():
            assert name in by_name, name
            digest = hashlib.sha256(by_name[name].read_bytes()).hexdigest()
            assert digest == expected, f"{name} changed: {digest}"
        assert "CampaignOutcomeDistributionMatrix.schema.json" in by_name
        assert "EmpiricalDistributionSummary.schema.json" not in by_name
        assert "StrategyObjectiveOutcome.schema.json" not in by_name

    def test_new_schema_matches_model_json_schema_output(self) -> None:
        path = SCHEMA_DIR / "CampaignOutcomeDistributionMatrix.schema.json"
        rendered = json.loads(path.read_text(encoding="utf-8"))
        assert rendered == CampaignOutcomeDistributionMatrix.model_json_schema()
        assert rendered["title"] == "CampaignOutcomeDistributionMatrix"
        assert "EmpiricalDistributionSummary" in rendered["$defs"]
        assert "StrategyObjectiveOutcome" in rendered["$defs"]
        assert rendered["additionalProperties"] is False


class TestModuleBoundaries:
    """The route/app/error modules carry no forbidden surface."""

    def test_route_module_imports_only_allowed_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        paths = _imported_module_paths(tree)
        for path in sorted(paths):
            assert not path.startswith(("kalhas.adapters", "kalhas.domain_packs", "kalhas.api.")), (
                path
            )
        top_level = _imported_modules(tree)
        forbidden_top_level = {
            "socket",
            "random",
            "time",
            "os",
            "subprocess",
            "pathlib",
            "requests",
            "httpx",
            "sqlite3",
            "datetime",
            "dateutil",
        }
        assert not (top_level & forbidden_top_level), sorted(top_level & forbidden_top_level)

    def test_route_module_has_no_store_write_or_activity_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        assert called <= {"get", "get_run_plans"}, f"unexpected method calls: {sorted(called)}"

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        for relative in (
            "api/routes_campaign_outcome.py",
            "api/app.py",
            "api/errors.py",
        ):
            tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
            symbols: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(node.name)
                    symbols.extend(argument.arg for argument in node.args.args)
            for symbol in symbols:
                assert not forbidden.search(symbol), f"{relative}: {symbol!r}"

    def test_no_phase_number_literals_in_new_or_modified_modules(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        for relative in (
            "api/routes_campaign_outcome.py",
            "api/app.py",
            "api/errors.py",
            "contracts/v1/__init__.py",
            "contracts/v1/campaign_outcome.py",
        ):
            source_text = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
            assert not pattern.search(source_text), relative

    def test_route_registered_exactly_once_in_create_app(self) -> None:
        source = (KALHAS_ROOT / "api" / "app.py").read_text(encoding="utf-8")
        assert source.count("campaign_outcome_router") == 2  # import alias + include call
        assert source.count("include_router(campaign_outcome_router)") == 1

    def test_error_mapping_registered_exactly_once(self) -> None:
        source = (KALHAS_ROOT / "api" / "errors.py").read_text(encoding="utf-8")
        assert source.count("CampaignOutcomeDistributionMatrixIntegrityError") == 2
        assert "ErrorCode.INTEGRITY_ERROR" in source


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths
