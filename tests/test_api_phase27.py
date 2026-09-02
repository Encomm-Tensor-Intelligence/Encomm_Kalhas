"""Tests for the campaign decision API surface (Phase 27, slice 11).

Tests for ``kalhas/api/routes_campaign_decision.py`` - the four
``campaign-decision`` operations (``POST``/``GET`` decision-policy,
``GET`` strategy-comparison, ``GET`` decision-brief) - their
registration in ``create_app``, the API error mapping of
``CampaignDecisionComparisonIntegrityError`` and
``CampaignDecisionBriefIntegrityError``, the request-to-draft
conversion boundary, and the additive public-contract registration at
``PUBLIC_CONTRACTS`` indexes 47-49 with the three generated JSON Schema
artifacts. Proves:

- a real policy-bearing COMPLETE runtime-3 lifecycle: POST returns 201
  with the exact declared policy, GET policy equals the declared
  artifact, GET comparison and GET brief equal the direct verified
  query outputs exactly, every response validates as its exact
  response contract, repeated GETs are byte-identical and change no
  store state, and the comparison and brief are never stored;
- the recorded-runtime gate: empty, legacy, unsupported (first/middle/
  last), and mixed run plans fail 409 CONFLICT before any policy or
  query service call, query parameters cannot select or alter runtime,
  and success invokes exactly one downstream service call per
  operation;
- request validation: global and per-objective valid modes,
  missing/extra/forged authoritative fields, XOR violations, invalid
  thresholds/count/tolerance/bool/metadata, unknown fields, and the
  required X-Tenant-ID header;
- tenant isolation and state: unknown and foreign campaigns 404,
  missing and foreign policies 404, non-COMPLETE declaration/
  comparison/brief 409 INVALID_STATE, and a stored policy remains
  retrievable after the campaign leaves COMPLETE;
- the exact typed error mapping with generic no-leak bodies: policy
  not found 404, duplicate 409 CONFLICT, policy validation 422,
  policy/outcome/comparison/brief integrity 409 INTEGRITY_ERROR,
  campaign incomplete 409 INVALID_STATE, unsupported runtime 409
  CONFLICT;
- read-only and atomicity: a failed POST performs zero policy writes,
  GETs perform zero writes/activity, repeated GETs leave the complete
  store digest unchanged, and no comparison/brief collections or put
  methods exist;
- OpenAPI: exactly four operations on three new paths with the exact
  request/response ``$ref`` contracts, POST 201 / GET 200, required
  X-Tenant-ID on all four, no GET body, no runtime selector, no extra
  methods, and every earlier path unchanged;
- registration: PUBLIC_CONTRACTS carries the accepted 50-contract
  prefix with unchanged indexes 0-46 (matrix still at 46) and the exact
  tail 47 CampaignDecisionPolicy, 48 CampaignStrategyComparison, 49
  CampaignDecisionBrief, and later additive contracts are allowed;
  schema artifact count follows ``PUBLIC_CONTRACTS`` with all 47
  historical byte hashes unchanged and each new artifact matching
  ``model_json_schema``; nested decision records stay unregistered;
- route/app/error modules carry no NEXUS/LEGION, live-action,
  nondeterministic, network, filesystem, database, provider, or
  phase-literal surface.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import realization_campaign_service
from kalhas.application.campaign_decision_errors import (
    CampaignDecisionBriefIntegrityError,
    CampaignDecisionComparisonIntegrityError,
)
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
    get_verified_campaign_decision_policy,
)
from kalhas.application.campaign_decision_query_service import (
    get_verified_campaign_decision_brief,
    get_verified_campaign_strategy_comparison,
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
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    ObjectiveTargetRequirement,
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
    inject_unsupported_recorded_runtime,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"

DECISION_POLICY_PATH = "/v1/campaigns/{campaign_id}/decision-policy"
STRATEGY_COMPARISON_PATH = "/v1/campaigns/{campaign_id}/strategy-comparison"
DECISION_BRIEF_PATH = "/v1/campaigns/{campaign_id}/decision-brief"

OUTCOME_PATH = "/v1/campaigns/{campaign_id}/outcome-distributions"

#: The exact four new operations on the three new paths.
DECISION_PATHS: dict[str, set[str]] = {
    "/v1/campaigns/{campaign_id}/decision-policy": {"get", "post"},
    "/v1/campaigns/{campaign_id}/strategy-comparison": {"get"},
    "/v1/campaigns/{campaign_id}/decision-brief": {"get"},
}

#: The six Phase 25 runtime-3 paths and their exact operations.
REALIZATION_PATHS: dict[str, set[str]] = {
    "/v1/runs/{run_id}/realization-trajectory-execution": {"get"},
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest": {"get"},
    "/v1/runs/{run_id}/realization-metric-observations": {"get", "post"},
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-statistics": {"get"},
}

#: The exact 47 pre-Phase-27 public-contract names in registry order.
_HISTORICAL_47_NAMES = (
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
    "CampaignOutcomeDistributionMatrix",
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "kalhas" / "api" / "routes_campaign_decision.py"
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

#: SHA-256 of every historical schema artifact (byte-identity anchor).
_HISTORICAL_SCHEMA_HASHES: dict[str, str] = {}


def _load_historical_schema_hashes() -> dict[str, str]:
    """The 47 historical schema byte hashes, probed once and hard-coded."""
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
        "CampaignOutcomeDistributionMatrix.schema.json": (
            "85e42a329ad7b85bf3833a7d3e12ef7ddbba6e3dbba2ec0a9217c8ccc65037e4"
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

#: The five authoritative scenario objectives in deliberately
#: NON-lexicographic order (sorted would be obj-1..obj-5): the first
#: three are targeted, the last two optimization-only.
_ACCEPTANCE_OBJECTIVES = (
    Objective(
        identifier="obj-3",
        description="Minimize the primary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-1",
        description="Maximize the primary metric",
        direction=ObjectiveDirection.MAXIMIZE,
        target=90.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-5",
        description="Reach the primary metric target band",
        direction=ObjectiveDirection.REACH,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-2",
        description="Optimize the primary metric downward",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-4",
        description="Optimize the primary metric upward",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=1.0,
    ),
)

#: The caller-owned profile drafts binding every objective to m-1.
_ACCEPTANCE_PROFILE_DRAFTS = (
    ObjectiveMetricBindingDraft(
        objective_id="obj-3", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-1", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-5",
        metric_id="m-1",
        reach_tolerance=5.0,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-2", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-4", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
)

#: The exact ordered per-objective target coverage of the fixture.
_TARGETED_IDS = ("obj-3", "obj-1", "obj-5")

#: The exact generic public messages of the two derived-artifact errors.
_COMPARISON_INTEGRITY_MESSAGE = (
    "Campaign strategy comparison derivation failed integrity verification and was rejected"
)
_BRIEF_INTEGRITY_MESSAGE = (
    "Campaign decision brief derivation failed integrity verification and was rejected"
)

#: A raw diagnostic sentinel that must never leak into an error body.
_RAW_SENTINEL = "SENTINEL-RAW-DIAGNOSTIC-9f3a"


def _build_complete_store() -> InMemoryScenarioStore:
    """A real COMPLETE runtime-3.0.0 campaign over the fixture objectives.

    Declarations, compilation, preparation, planning, start, full
    execution (2 strategies x 2 seeds), and per-run observation
    extraction all go through the real public services; the evaluation
    profile is declared before world compilation so the compiled world
    embeds the exact snapshot. No policy is declared here.
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
            campaign_name="Decision API acceptance campaign",
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


def _declare_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """Declare the fixture policy through the real declaration service.

    Per-objective thresholds 0.4 on the three targeted objectives in
    exact authoritative order, minimum sample count 2 (equal to the
    fixture's seed count, so the decision is evaluated), tie tolerance
    0.05, hard gates on.
    """
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-1",
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="per_objective",
            minimum_sample_count=2,
            tie_tolerance=0.05,
            all_targeted_objectives_are_hard_gates=True,
            declared_at=DECLARED_AT,
            minimum_target_achievement_probability=None,
            objective_target_requirements=tuple(
                ObjectiveTargetRequirement(
                    objective_id=objective_id,
                    minimum_target_achievement_probability=0.4,
                )
                for objective_id in _TARGETED_IDS
            ),
            metadata={},
        ),
    )


@pytest.fixture(scope="module")
def decision_base_store() -> InMemoryScenarioStore:
    """The real executed COMPLETE acceptance store without a policy."""
    return _build_complete_store()


@pytest.fixture(scope="module")
def decision_store(decision_base_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """The complete store with the policy declared through the real service."""
    store = copy.deepcopy(decision_base_store)
    _declare_policy(store)
    return store


@pytest.fixture()
def store(decision_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the policy-bearing store."""
    return copy.deepcopy(decision_store)


@pytest.fixture()
def base_store(decision_base_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the store without a policy."""
    return copy.deepcopy(decision_base_store)


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
    for name, collection in store.__dict__.items():
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
        "obj-1",
        "obj-3",
        "obj-5",
        "0.4",
        _RAW_SENTINEL,
    ):
        assert forbidden not in serialized, f"error body leaks {forbidden!r}: {serialized}"


def _global_request_payload(**overrides: object) -> dict[str, object]:
    """A valid global-mode declaration request payload; ``overrides`` win."""
    payload: dict[str, object] = {
        "target_requirement_mode": "global",
        "minimum_target_achievement_probability": 0.5,
        "objective_target_requirements": [],
        "minimum_sample_count": 2,
        "tie_tolerance": 0.05,
        "all_targeted_objectives_are_hard_gates": True,
        "declared_at": "2026-01-04T12:00:00Z",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _per_objective_request_payload(**overrides: object) -> dict[str, object]:
    """A valid per-objective-mode declaration request payload; ``overrides`` win."""
    payload: dict[str, object] = {
        "target_requirement_mode": "per_objective",
        "minimum_target_achievement_probability": None,
        "objective_target_requirements": [
            {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
            {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
            {"objective_id": "obj-5", "minimum_target_achievement_probability": 0.4},
        ],
        "minimum_sample_count": 2,
        "tie_tolerance": 0.05,
        "all_targeted_objectives_are_hard_gates": True,
        "declared_at": "2026-01-04T12:00:00Z",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


class TestOpenApiSurface:
    """The OpenAPI contract of the four new operations."""

    def test_exactly_four_operations_on_three_new_paths(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        new_paths = {
            path: set(ops)
            for path, ops in paths.items()
            if any(
                marker in path
                for marker in ("decision-policy", "strategy-comparison", "decision-brief")
            )
        }
        assert new_paths == DECISION_PATHS
        assert sum(len(ops) for ops in DECISION_PATHS.values()) == 4

    def test_exact_request_and_response_refs(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        schemas = spec["components"]["schemas"]
        post = paths[DECISION_POLICY_PATH]["post"]
        body_ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert body_ref == "#/components/schemas/CampaignDecisionPolicyDeclarationRequest"
        assert "CampaignDecisionPolicyDeclarationRequest" in schemas
        assert post["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == (
            "#/components/schemas/CampaignDecisionPolicy"
        )
        assert (
            paths[DECISION_POLICY_PATH]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/CampaignDecisionPolicy"
        )
        assert (
            paths[STRATEGY_COMPARISON_PATH]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/CampaignStrategyComparison"
        )
        assert (
            paths[DECISION_BRIEF_PATH]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == "#/components/schemas/CampaignDecisionBrief"
        )
        for name in (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
        ):
            assert name in schemas

    def test_required_tenant_header_on_all_four_operations(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        expected_header = {
            "name": "X-Tenant-ID",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "title": "X-Tenant-Id"},
        }
        for path, operations in DECISION_PATHS.items():
            for operation_name in operations:
                operation = paths[path][operation_name]
                parameters = operation.get("parameters", [])
                headers = [parameter for parameter in parameters if parameter["in"] == "header"]
                assert headers == [expected_header], f"{path} {operation_name}"
                queries = [parameter for parameter in parameters if parameter["in"] == "query"]
                assert queries == [], f"{path} {operation_name}"
                assert all("runtime" not in str(parameter).lower() for parameter in parameters), (
                    f"{path} {operation_name}"
                )

    def test_no_get_request_body(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        for path, operations in DECISION_PATHS.items():
            for operation_name in operations:
                if operation_name == "get":
                    assert "requestBody" not in paths[path]["get"], path

    def test_earlier_paths_remain_unchanged(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        realization_paths = {
            path: set(ops) for path, ops in paths.items() if "realization-" in path
        }
        assert realization_paths == REALIZATION_PATHS
        assert sum(len(ops) for ops in REALIZATION_PATHS.values()) == 7
        assert set(paths[OUTCOME_PATH]) == {"get"}
        assert set(paths["/v1/scenarios/{scenario_id}/evaluation-profile"]) == {"get", "post"}
        assert set(paths["/v1/campaigns/{campaign_id}/objective-evaluations"]) == {"get"}

    def test_openapi_components_include_decision_nested_records(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        schemas = spec["components"]["schemas"]
        policy = schemas["CampaignDecisionPolicy"]
        assert policy["properties"]["objective_target_requirements"]["items"]["$ref"] == (
            "#/components/schemas/ObjectiveTargetRequirement"
        )
        assert policy["properties"]["objective_weight_snapshots"]["items"]["$ref"] == (
            "#/components/schemas/ObjectiveWeightSnapshot"
        )
        assert "ObjectiveTargetRequirement" in schemas
        assert "ObjectiveWeightSnapshot" in schemas
        comparison = schemas["CampaignStrategyComparison"]
        assert comparison["properties"]["paired_comparisons"]["items"]["$ref"] == (
            "#/components/schemas/ObjectivePairedComparison"
        )
        assert "DominanceRelation" in schemas
        assert "StrategyRobustnessProfile" in schemas


class TestRealLifecycle:
    """The real policy-bearing HTTP proof."""

    def _post(self, client: TestClient, payload: dict[str, object]) -> Any:
        return client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            json=payload,
        )

    def _get_policy(self, client: TestClient, campaign_id: str = "campaign-1") -> Any:
        return client.get(DECISION_POLICY_PATH.format(campaign_id=campaign_id), headers=HEADERS)

    def _get_comparison(self, client: TestClient, campaign_id: str = "campaign-1") -> Any:
        return client.get(STRATEGY_COMPARISON_PATH.format(campaign_id=campaign_id), headers=HEADERS)

    def _get_brief(self, client: TestClient, campaign_id: str = "campaign-1") -> Any:
        return client.get(DECISION_BRIEF_PATH.format(campaign_id=campaign_id), headers=HEADERS)

    def test_post_policy_201_and_get_policy_equals_declared(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        response = self._post(client, _per_objective_request_payload())
        assert response.status_code == 201
        declared = CampaignDecisionPolicy.model_validate(response.json())
        assert declared.campaign_id == "campaign-1"
        assert declared.target_requirement_mode == "per_objective"
        assert declared.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"
        assert declared.tail_alpha == 0.95
        assert declared.objective_target_requirements[0].objective_id == "obj-3"
        fetched = self._get_policy(client)
        assert fetched.status_code == 200
        assert fetched.json() == response.json()

    def test_post_policy_global_mode_201(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        response = self._post(client, _global_request_payload())
        assert response.status_code == 201
        declared = CampaignDecisionPolicy.model_validate(response.json())
        assert declared.target_requirement_mode == "global"
        assert declared.minimum_target_achievement_probability == 0.5

    def test_get_comparison_equals_direct_verified_query(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._get_comparison(client)
        assert response.status_code == 200
        comparison = CampaignStrategyComparison.model_validate(response.json())
        assert comparison.runtime_version == "3.0.0"
        assert comparison.comparison_mode == "identical_conditions"
        assert comparison.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"
        assert comparison.ordered_strategy_candidate_ids == ("mock-a", "mock-b")
        assert comparison.ordered_scenario_seed_ids == ("seed-0", "seed-2")
        assert comparison.ordered_objective_ids == ("obj-3", "obj-1", "obj-5", "obj-2", "obj-4")
        assert len(comparison.paired_comparisons) == 10
        assert len(comparison.robustness_profiles) == 2
        direct = get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert response.json() == direct.model_dump(mode="json")

    def test_get_brief_equals_direct_verified_query(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._get_brief(client)
        assert response.status_code == 200
        brief = CampaignDecisionBrief.model_validate(response.json())
        assert brief.runtime_version == "3.0.0"
        assert brief.campaign_id == "campaign-1"
        assert brief.status in (
            "preferred",
            "inconclusive",
            "insufficient_evidence",
            "no_feasible_strategy",
        )
        assert brief.terminal_reason.code in (
            "unique_minimax_preference",
            "regret_tie_within_tolerance",
            "insufficient_seed_samples",
            "no_feasible_strategy",
        )
        assert len(brief.robustness_profiles) == 2
        direct = get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert response.json() == direct.model_dump(mode="json")

    def test_response_validates_as_exact_response_contracts(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        assert CampaignDecisionPolicy.model_validate(self._get_policy(client).json())
        assert CampaignStrategyComparison.model_validate(self._get_comparison(client).json())
        assert CampaignDecisionBrief.model_validate(self._get_brief(client).json())

    def test_repeated_gets_byte_identical_and_store_unchanged(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before = _store_state(store)
        first_policy = self._get_policy(client)
        second_policy = self._get_policy(client)
        first_comparison = self._get_comparison(client)
        second_comparison = self._get_comparison(client)
        first_brief = self._get_brief(client)
        second_brief = self._get_brief(client)
        assert first_policy.status_code == 200
        assert second_policy.json() == first_policy.json()
        assert canonical_json(second_policy.json()) == canonical_json(first_policy.json())
        assert second_comparison.json() == first_comparison.json()
        assert canonical_json(second_comparison.json()) == canonical_json(first_comparison.json())
        assert second_brief.json() == first_brief.json()
        assert canonical_json(second_brief.json()) == canonical_json(first_brief.json())
        assert _store_state(store) == before

    def test_gets_record_no_operational_activity(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before_activity = store.list_operational_activity(TENANT)
        assert self._get_policy(client).status_code == 200
        assert self._get_comparison(client).status_code == 200
        assert self._get_brief(client).status_code == 200
        assert store.list_operational_activity(TENANT) == before_activity

    def test_comparison_and_brief_never_stored(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before = _store_state(store)
        assert self._get_comparison(client).status_code == 200
        assert self._get_brief(client).status_code == 200
        assert _store_state(store) == before
        assert not hasattr(store, "_campaign_strategy_comparisons")
        assert not hasattr(store, "_campaign_decision_briefs")
        assert not hasattr(store, "put_campaign_strategy_comparison")
        assert not hasattr(store, "put_campaign_decision_brief")


class TestRequestValidation:
    """Request validation of the declaration operation (typed 422s)."""

    def _post(
        self, client: TestClient, payload: dict[str, object], headers: dict[str, str] | None = None
    ) -> Any:
        return client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=headers if headers is not None else HEADERS,
            json=payload,
        )

    def test_missing_tenant_header_422(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        response = self._post(client, _per_objective_request_payload(), headers={})
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_valid_modes_are_201(
        self,
        client: TestClient,
        base_store: InMemoryScenarioStore,
        decision_base_store: InMemoryScenarioStore,
    ) -> None:
        _install_store(client, base_store)
        assert self._post(client, _global_request_payload()).status_code == 201
        # A second fresh store without a policy (per-test isolation).
        _install_store(client, copy.deepcopy(decision_base_store))
        assert self._post(client, _per_objective_request_payload()).status_code == 201

    @pytest.mark.parametrize(
        "override",
        [
            {"surprise": 1},
            {"identifier": "forged-policy-id"},
            {"content_hash": "1" * 64},
            {"tenant_id": "tenant-other"},
            {"campaign_id": "campaign-9"},
            {"scenario_id": "scenario-9"},
            {"world_version_id": "world-9"},
            {"evaluation_profile_id": "profile-9"},
            {"algorithm_identifier": "other-algorithm"},
            {"objective_weight_snapshots": [{"objective_id": "obj-1", "weight": 1.0}]},
            {"tail_alpha": 0.99},
            {"runtime_version": "9.9.9"},
            {"comparison_mode": "independent"},
        ],
    )
    def test_missing_extra_forged_authoritative_fields_rejected_422(
        self, client: TestClient, base_store: InMemoryScenarioStore, override: dict[str, object]
    ) -> None:
        _install_store(client, base_store)
        payload = _per_objective_request_payload()
        payload.update(override)
        response = self._post(client, payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_xor_violations_rejected_422(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        cases: list[dict[str, object]] = [
            # global mode without the global probability
            _global_request_payload(minimum_target_achievement_probability=None),
            # global mode with per-objective requirements
            _global_request_payload(
                objective_target_requirements=[
                    {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4}
                ]
            ),
            # per_objective mode with a global probability
            _per_objective_request_payload(minimum_target_achievement_probability=0.5),
            # per_objective mode without requirements
            _per_objective_request_payload(objective_target_requirements=[]),
        ]
        for payload in cases:
            response = self._post(client, payload)
            _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    @pytest.mark.parametrize(
        "override",
        [
            {"minimum_target_achievement_probability": 1.5},
            {"minimum_target_achievement_probability": -0.1},
            {"minimum_sample_count": 0},
            {"minimum_sample_count": 1.5},
            {"tie_tolerance": -0.05},
            # Unrepresentable huge integers are rejected before any
            # coercion (non-finite floats cannot travel as JSON, so the
            # non-finite rejection is proven at the request-model layer).
            {"tie_tolerance": 10**400},
            {"all_targeted_objectives_are_hard_gates": "true"},
            {"all_targeted_objectives_are_hard_gates": 1},
            {"metadata": [1, 2]},
            {"metadata": "not-an-object"},
        ],
    )
    def test_invalid_threshold_count_tolerance_bool_metadata_422(
        self, client: TestClient, base_store: InMemoryScenarioStore, override: dict[str, object]
    ) -> None:
        _install_store(client, base_store)
        payload = _global_request_payload()
        payload.update(override)
        response = self._post(client, payload)
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_unknown_and_reordered_coverage_rejected_422(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        cases: list[dict[str, object]] = [
            # unknown objective (service-level typed validation error)
            _per_objective_request_payload(
                objective_target_requirements=[
                    {"objective_id": "obj-ghost", "minimum_target_achievement_probability": 0.4},
                    {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
                    {"objective_id": "obj-5", "minimum_target_achievement_probability": 0.4},
                ]
            ),
            # reordered coverage
            _per_objective_request_payload(
                objective_target_requirements=[
                    {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
                    {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
                    {"objective_id": "obj-5", "minimum_target_achievement_probability": 0.4},
                ]
            ),
            # duplicate requirement objective
            _per_objective_request_payload(
                objective_target_requirements=[
                    {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
                    {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.6},
                    {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
                ]
            ),
        ]
        for payload in cases:
            response = self._post(client, payload)
            _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_duplicate_declaration_409_conflict(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = self._post(client, _per_objective_request_payload())
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        assert (
            response.json()["message"]
            == "Campaign decision policy already exists for this campaign"
        )


class TestTenantAndState:
    """Tenant isolation and campaign-state behavior."""

    def test_unknown_and_foreign_campaign_404_all_operations(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        payload = _per_objective_request_payload()
        request_calls: tuple[Callable[[], Any], ...] = (
            lambda: client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-ghost"), headers=HEADERS
            ),
            lambda: client.get(
                STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-ghost"), headers=HEADERS
            ),
            lambda: client.get(
                DECISION_BRIEF_PATH.format(campaign_id="campaign-ghost"), headers=HEADERS
            ),
            lambda: client.post(
                DECISION_POLICY_PATH.format(campaign_id="campaign-ghost"),
                headers=HEADERS,
                json=payload,
            ),
            lambda: client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
                headers={"X-Tenant-ID": OTHER_TENANT},
            ),
            lambda: client.get(
                STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"),
                headers={"X-Tenant-ID": OTHER_TENANT},
            ),
            lambda: client.get(
                DECISION_BRIEF_PATH.format(campaign_id="campaign-1"),
                headers={"X-Tenant-ID": OTHER_TENANT},
            ),
            lambda: client.post(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
                headers={"X-Tenant-ID": OTHER_TENANT},
                json=payload,
            ),
        )
        for request_call in request_calls:
            _assert_error_shape(request_call(), 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_missing_and_foreign_policy_404(
        self, client: TestClient, base_store: InMemoryScenarioStore, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)
        assert response.json()["message"] == "Campaign decision policy not found"
        # A foreign tenant sees the indistinguishable campaign-level 404:
        # the tenant-scoped recorded-run-plan read fails first with the
        # same typed not-found behavior as an unknown campaign.
        _install_store(client, store)
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers={"X-Tenant-ID": OTHER_TENANT},
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)
        _install_store(client, copy.deepcopy(store))
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-ghost"), headers=HEADERS
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_non_complete_declaration_comparison_brief_409_invalid_state(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.DRAFT})
        )
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            json=_per_objective_request_payload(),
        )
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)
        response = client.get(
            STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)
        response = client.get(DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)

    def test_stored_policy_retrievable_when_campaign_no_longer_complete(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.RUNNING})
        )
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        assert response.status_code == 200
        CampaignDecisionPolicy.model_validate(response.json())
        response = client.get(
            STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)


class TestRuntimeGate:
    """Recorded-runtime dispatch derives only from stored run plans."""

    def test_empty_run_plans_fail_409_before_any_service(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        store._run_plans[(TENANT, "campaign-1")] = ()
        symbols = (
            "declare_campaign_decision_policy",
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_strategy_comparison",
            "get_verified_campaign_decision_brief",
        )
        with mock.patch.multiple(
            "kalhas.api.routes_campaign_decision", **{name: mock.DEFAULT for name in symbols}
        ) as spies:
            response = client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert all(spies[name].call_count == 0 for name in symbols)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_legacy_runtime_fails_409_before_service(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=plans[0], unsupported_version="1.0.0"
        )
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_decision_policy"
        ) as spy:
            response = client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    @pytest.mark.parametrize("index", (0, 1, 3))
    def test_unsupported_runtime_at_first_middle_last_position_fails_before_service(
        self, client: TestClient, store: InMemoryScenarioStore, index: int
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[index])
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_strategy_comparison"
        ) as spy:
            response = client.get(
                STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
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
            "kalhas.api.routes_campaign_decision.get_verified_campaign_decision_brief"
        ) as spy:
            response = client.get(
                DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert spy.call_count == 0
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_query_parameters_cannot_select_or_alter_runtime_dispatch(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            params={"runtime_version": "1.0.0"},
        )
        assert response.status_code == 200
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            params={"runtime_version": "3.0.0"},
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_exactly_one_downstream_service_call_on_success(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        original_declare = declare_campaign_decision_policy
        original_get_policy = get_verified_campaign_decision_policy
        with mock.patch(
            "kalhas.api.routes_campaign_decision.declare_campaign_decision_policy",
            side_effect=original_declare,
        ) as declare_spy:
            response = client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert declare_spy.call_count == 0
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_decision_policy",
            side_effect=original_get_policy,
        ) as get_spy:
            response = client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert response.status_code == 200
            assert get_spy.call_count == 1
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_strategy_comparison",
            side_effect=get_verified_campaign_strategy_comparison,
        ) as comparison_spy:
            response = client.get(
                STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert response.status_code == 200
            assert comparison_spy.call_count == 1
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_decision_brief",
            side_effect=get_verified_campaign_decision_brief,
        ) as brief_spy:
            response = client.get(
                DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
            assert response.status_code == 200
            assert brief_spy.call_count == 1


class TestErrorMapping:
    """Typed API error mapping for the decision surface."""

    def test_policy_not_found_404(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_policy_duplicate_409_conflict(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            json=_per_objective_request_payload(),
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_policy_validation_422(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        payload = _per_objective_request_payload(
            objective_target_requirements=[
                {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
                {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
                {"objective_id": "obj-5", "minimum_target_achievement_probability": 0.4},
            ]
        )
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS, json=payload
        )
        _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value, leak_scan=False)

    def test_policy_integrity_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        stored = store._campaign_decision_policies[(TENANT, "campaign-1")]
        store._campaign_decision_policies[(TENANT, "campaign-1")] = stored.model_copy(
            update={"content_hash": "1" * 64}
        )
        response = client.get(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_campaign_incomplete_409_invalid_state(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.DRAFT})
        )
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            json=_per_objective_request_payload(),
        )
        _assert_error_shape(response, 409, ErrorCode.INVALID_STATE.value)

    def test_unsupported_runtime_409_conflict_no_leak(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        response = client.get(
            STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_outcome_integrity_409_integrity_error(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        store._evaluation_profiles[(TENANT, "scenario-1")] = stored.model_copy(
            update={"content_hash": "1" * 64}
        )
        response = client.get(
            STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)
        response = client.get(DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_comparison_integrity_error_maps_to_exact_generic_409_body(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        with mock.patch(
            "kalhas.application.campaign_decision_query_service.build_campaign_strategy_comparison",
            side_effect=ValueError(_RAW_SENTINEL),
        ):
            response = client.get(
                STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)
        body = response.json()
        assert body["message"] == _COMPARISON_INTEGRITY_MESSAGE
        assert body["message"] == str(
            CampaignDecisionComparisonIntegrityError(TENANT, "campaign-1")
        )
        assert _RAW_SENTINEL not in json.dumps(body)

    def test_brief_integrity_error_maps_to_exact_generic_409_body(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        with mock.patch(
            "kalhas.application.campaign_decision_query_service.build_campaign_decision_brief",
            side_effect=ValueError(_RAW_SENTINEL),
        ):
            response = client.get(
                DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)
        body = response.json()
        assert body["message"] == _BRIEF_INTEGRITY_MESSAGE
        assert body["message"] == str(CampaignDecisionBriefIntegrityError(TENANT, "campaign-1"))
        assert _RAW_SENTINEL not in json.dumps(body)

    def test_failed_queries_never_return_a_partial_artifact(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        before = _store_state(store)
        response = client.get(
            STRATEGY_COMPARISON_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        assert response.status_code == 409
        assert "paired_comparisons" not in response.text
        assert "ordered_strategy_candidate_ids" not in response.text
        assert _store_state(store) == before


class TestReadOnlyAndAtomicity:
    """Strict read-only behavior and zero-write failures."""

    def test_failed_post_produces_zero_policy_write(
        self, client: TestClient, base_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, base_store)
        before = _store_state(base_store)
        payload = _global_request_payload(minimum_target_achievement_probability=None)
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS, json=payload
        )
        assert response.status_code == 422
        assert _store_state(base_store) == before
        assert (TENANT, "campaign-1") not in base_store._campaign_decision_policies

    def test_duplicate_post_produces_zero_policy_write(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        before = _store_state(store)
        response = client.post(
            DECISION_POLICY_PATH.format(campaign_id="campaign-1"),
            headers=HEADERS,
            json=_per_objective_request_payload(),
        )
        assert response.status_code == 409
        assert _store_state(store) == before

    def test_runtime_gate_failure_does_no_store_write(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        before = _store_state(store)
        response = client.get(DECISION_BRIEF_PATH.format(campaign_id="campaign-1"), headers=HEADERS)
        assert response.status_code == 409
        assert _store_state(store) == before

    def test_route_invokes_runtime_gate_before_service(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        events: list[str] = []
        original_get_run_plans = store.get_run_plans
        original_query = get_verified_campaign_decision_policy

        def counting_get_run_plans(*args: Any, **kwargs: Any) -> Any:
            events.append("plans")
            return original_get_run_plans(*args, **kwargs)

        def counting_query(*args: Any, **kwargs: Any) -> Any:
            events.append("query")
            return original_query(*args, **kwargs)

        store.get_run_plans = counting_get_run_plans  # type: ignore[method-assign]
        with mock.patch(
            "kalhas.api.routes_campaign_decision.get_verified_campaign_decision_policy",
            side_effect=counting_query,
        ):
            response = client.get(
                DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
            )
        assert response.status_code == 200
        assert events[0] == "plans"
        assert events.count("query") == 1

    @pytest.mark.parametrize("method", ("put", "patch", "delete"))
    def test_no_other_http_methods_on_decision_policy(
        self, client: TestClient, store: InMemoryScenarioStore, method: str
    ) -> None:
        _install_store(client, store)
        response = client.request(
            method, DECISION_POLICY_PATH.format(campaign_id="campaign-1"), headers=HEADERS
        )
        _assert_error_shape(response, 405, ErrorCode.METHOD_NOT_ALLOWED.value, leak_scan=False)

    def test_no_other_http_methods_on_comparison_and_brief(
        self, client: TestClient, store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, store)
        for path in (STRATEGY_COMPARISON_PATH, DECISION_BRIEF_PATH):
            for method in ("post", "put", "patch", "delete"):
                response = client.request(
                    method, path.format(campaign_id="campaign-1"), headers=HEADERS
                )
                _assert_error_shape(
                    response, 405, ErrorCode.METHOD_NOT_ALLOWED.value, leak_scan=False
                )


class TestContractRegistration:
    """PUBLIC_CONTRACTS indexes 47-49 and the schema artifact set."""

    def test_public_contracts_preserve_accepted_50_prefix_with_phase27_tail(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 50
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47:50] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
        )

    def test_nested_decision_records_remain_unregistered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in (
            "ObjectiveWeightSnapshot",
            "ObjectiveTargetRequirement",
            "ObjectivePairedComparison",
            "ObjectiveFeasibilityEvidence",
            "ObjectiveRegretEvidence",
            "ObjectiveProbabilityEvidence",
            "ObjectiveDownsideEvidence",
            "ObjectiveDominanceStatus",
            "DominanceRelation",
            "StrategyRobustnessProfile",
            "DecisionReasonRecord",
            "DecisionFactorRecord",
        ):
            assert nested not in names
        assert "CampaignDecisionPolicy" in names
        assert "CampaignStrategyComparison" in names
        assert "CampaignDecisionBrief" in names

    def test_schema_artifacts_follow_the_public_registry(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        by_name = {path.name: path for path in schema_files}
        assert len(_HISTORICAL_SCHEMA_HASHES) == 47
        for name, expected in _HISTORICAL_SCHEMA_HASHES.items():
            assert name in by_name, name
            digest = hashlib.sha256(by_name[name].read_bytes()).hexdigest()
            assert digest == expected, f"{name} changed: {digest}"
        for name in (
            "CampaignDecisionPolicy.schema.json",
            "CampaignStrategyComparison.schema.json",
            "CampaignDecisionBrief.schema.json",
        ):
            assert name in by_name
        assert "ObjectiveTargetRequirement.schema.json" not in by_name
        assert "StrategyRobustnessProfile.schema.json" not in by_name

    def test_new_schemas_match_model_json_schema_output(self) -> None:
        expected: dict[type[BaseModel], str] = {
            CampaignDecisionPolicy: "CampaignDecisionPolicy.schema.json",
            CampaignStrategyComparison: "CampaignStrategyComparison.schema.json",
            CampaignDecisionBrief: "CampaignDecisionBrief.schema.json",
        }
        for contract, filename in expected.items():
            path = SCHEMA_DIR / filename
            rendered = json.loads(path.read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False
        policy_schema = json.loads(
            (SCHEMA_DIR / "CampaignDecisionPolicy.schema.json").read_text(encoding="utf-8")
        )
        assert "ObjectiveTargetRequirement" in policy_schema["$defs"]
        comparison_schema = json.loads(
            (SCHEMA_DIR / "CampaignStrategyComparison.schema.json").read_text(encoding="utf-8")
        )
        assert "ObjectivePairedComparison" in comparison_schema["$defs"]
        assert "StrategyRobustnessProfile" in comparison_schema["$defs"]
        brief_schema = json.loads(
            (SCHEMA_DIR / "CampaignDecisionBrief.schema.json").read_text(encoding="utf-8")
        )
        assert "DecisionReasonRecord" in brief_schema["$defs"]
        assert "DecisionFactorRecord" in brief_schema["$defs"]


class TestModuleBoundaries:
    """The route/app/error modules carry no forbidden surface."""

    def test_route_module_imports_only_allowed_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        paths = _imported_module_paths(tree)
        for path in sorted(paths):
            assert not path.startswith(("kalhas.adapters", "kalhas.domain_packs")), path
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
        assert called <= {"get", "get_run_plans", "post"}, (
            f"unexpected method calls: {sorted(called)}"
        )

    def test_no_ranking_winner_recommendation_surface(self) -> None:
        forbidden = re.compile(r"rank|winner|recommend|confidence|forecast", re.IGNORECASE)
        for relative in (
            "api/routes_campaign_decision.py",
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
            "api/routes_campaign_decision.py",
            "api/app.py",
            "api/errors.py",
            "contracts/v1/__init__.py",
            "contracts/v1/campaign_decision.py",
            "application/campaign_decision_query_service.py",
        ):
            source_text = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
            assert not pattern.search(source_text), relative

    def test_route_registered_exactly_once_in_create_app(self) -> None:
        source = (KALHAS_ROOT / "api" / "app.py").read_text(encoding="utf-8")
        assert source.count("campaign_decision_router") == 2  # import alias + include call
        assert source.count("include_router(campaign_decision_router)") == 1

    def test_error_mapping_registered_exactly_once(self) -> None:
        source = (KALHAS_ROOT / "api" / "errors.py").read_text(encoding="utf-8")
        assert source.count("CampaignDecisionComparisonIntegrityError") == 2
        assert source.count("CampaignDecisionBriefIntegrityError") == 2
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
