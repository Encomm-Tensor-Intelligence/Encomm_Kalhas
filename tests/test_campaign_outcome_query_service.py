"""Tests for the verified read-only campaign outcome-distribution query.

Tests for ``kalhas/application/campaign_outcome_query_service.py``: the
single public ``get_verified_campaign_outcome_distributions`` query and
its exact verified pipeline. Proves:

- a real COMPLETE multi-strategy/shared-seed runtime-3 campaign whose
  evaluation profile was declared through the real declaration service
  **before** world compilation returns the exact accepted
  strategy-major/objective-minor outcome evidence (values 84/103 in
  seed order, targeted minimize/maximize/reach evidence, and
  optimization-only null behavior);
- the query result carries the same deterministic identifier/content
  hash/timestamp lineage as direct use of the accepted pure builder
  over the same verified sources; repeated calls are byte/JSON
  identical and leave the complete store state byte-unchanged;
- the two upstream verified query functions and the pure builder are
  each called exactly once on a successful query, and are never called
  for unknown campaigns, foreign tenants, or non-COMPLETE campaigns;
- DRAFT/VALIDATED/COMPILED/RUNNING/FAILED/CANCELLED campaigns are
  rejected before any derivation; a verified world with no embedded
  profile raises the established not-found error and invents nothing;
- the full profile-assembly fail-closed matrix: missing stored profile,
  validator-bypassed stored corruption, identifier/hash tampering,
  self-consistently rehashed stored-vs-embedded divergence, and
  foreign-tenant/scenario substitution all fail closed with the safe
  typed integrity error;
- missing/corrupted world or manifest, stored-versus-embedded
  uncertainty corruption (through the verified realization query),
  missing/corrupted first/middle/last observation sets, and
  legacy/unsupported recorded runtime all fail closed, with the
  established upstream typed errors preserved;
- integrity failures never yield a partial matrix and never cause
  writes; the public integrity-error message is exact, generic, and
  never exposes internal reasons;
- the module's AST/import/call boundary: no API/adapters/domain-pack
  imports, no wall-clock/randomness/network/provider/filesystem/
  database surface, no store write methods, and no ranking or
  recommendation vocabulary;
- PUBLIC_CONTRACTS and schema artifact counts remain unchanged, and
  every accepted earlier-slice file stays byte-identical.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import campaign_outcome_query_service as service_module
from kalhas.application import realization_campaign_service
from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_matrix_runtime import (
    build_campaign_outcome_distribution_matrix,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    UnsupportedRuntimeVersionError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
)
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.realization_errors import (
    RealizationCampaignMetricObservationMatrixIntegrityError,
)
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.application.world_uncertainty_errors import (
    CampaignWorldRealizationMatrixIntegrityError,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_model_content_hash,
)
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import (
    ScenarioEvaluationProfile,
)
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

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_outcome_query_service.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

#: The accepted earlier-slice files with their preservation hashes.
_PRESERVED_FILES = (
    (
        "CODEX_HERMES_HANDOFF_PHASE_26_START.md",
        "0ce6a46915666fb29ef7e4fe2b49d324e8e094187d78404f0b733db1fcda1f22",
    ),
    (
        "kalhas/application/campaign_outcome_errors.py",
        "573e43376d794dae38f617007898a304da61e37ecd7da565ea02b90504f8a656",
    ),
    (
        "kalhas/application/campaign_outcome_identity.py",
        "be673a606fb6308b1c1c88104bde44e10714ef5b95d5f469a0b2d1053f747a04",
    ),
    (
        "kalhas/application/campaign_outcome_matrix_runtime.py",
        "ee22dd9cbb0e4c5b3863b85af4d649d9b326c2c28fdb2436ca58f61028b7015c",
    ),
    (
        "kalhas/application/campaign_outcome_runtime.py",
        "2829dffa57d45398265f831f704839e5a702853973a243c4d8d33b3c01ef3fd9",
    ),
    (
        "kalhas/application/campaign_outcome_statistics.py",
        "5e4d32f8346a543c3260a43e67df593d695e8e091d0592a46566f8e08ae0e3d2",
    ),
    (
        "kalhas/contracts/v1/campaign_outcome.py",
        "0100c5e5be6a47483c340179be8a4ba733662b7a1d58d5866cc8f1720d66cdd4",
    ),
    (
        "tests/test_campaign_outcome_contracts.py",
        "6315c5f118ca697042014c62dec8abf796d4f8246b224adb0b301354fe015169",
    ),
    (
        "tests/test_campaign_outcome_identity.py",
        "41db11e7c6e6864b289379e1493b87aa36034682044466aaf4faa541ca795539",
    ),
    (
        "tests/test_campaign_outcome_matrix_runtime.py",
        "53d6f0b73f40ee84543624bdc064a52c215ff8ebb71f6b8209343b424bfed0c6",
    ),
    (
        "tests/test_campaign_outcome_runtime.py",
        "cf55a64ede5f2b12643f598e42db66741ce53e92326e41ca4e62615d2a289cac",
    ),
    (
        "tests/test_campaign_outcome_statistics.py",
        "4f9dc8fd70e0a34cf20a91abc94df85600c5cb4fadb375c2f5450be02c9111bf",
    ),
)

#: The five authoritative scenario objectives of the query fixture,
#: matching the accepted outcome evidence semantics exactly.
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

#: The caller-owned profile drafts: every objective bound to the single
#: observed metric m-1 (unit "units") with the accepted scales/tolerance.
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


def _outcome(
    matrix: CampaignOutcomeDistributionMatrix,
    strategy_position: int,
    objective_position: int,
) -> StrategyObjectiveOutcome:
    """One outcome of the strategy-major/objective-minor matrix."""
    return matrix.outcomes[strategy_position * 5 + objective_position]


def _expected_observed_value(store: InMemoryScenarioStore, campaign: Any, seed: Any) -> int:
    """The causally expected observed value of one seed under the fixture world.

    Reconstructs the deterministic realization of the seed (tests may
    reconstruct; only production may not) and applies the fixture's
    guarded-transition causality locally: a realized branch value of 5
    produces 84 and a realized branch value of 9 produces 103 - exactly
    the engine-mediated outcome the real lifecycle produced.
    """
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


def _module_symbol(module: Any, name: str) -> Any:
    """One module attribute read through a variable (mypy no_implicit_reexport)."""
    return getattr(module, name)


def _install_spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Counting wrappers around the two upstream queries and the pure builder.

    The wrappers forward to the real functions; the counters prove the
    exact call counts of the query pipeline. The module exports exactly
    one public function, so the spy targets are read through ``getattr``
    (mypy no_implicit_reexport).
    """
    names = (
        "get_verified_campaign_world_realizations",
        "get_verified_realization_campaign_metric_observation_matrix",
        "build_campaign_outcome_distribution_matrix",
    )
    originals = {name: getattr(service_module, name) for name in names}
    counts: dict[str, int] = {"realizations": 0, "observations": 0, "builder": 0}
    keys = ("realizations", "observations", "builder")

    def counting(name: str, key: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            counts[key] += 1
            return originals[name](*args, **kwargs)

        return wrapper

    for name, key in zip(names, keys, strict=True):
        monkeypatch.setattr(service_module, name, counting(name, key))
    return counts


def _profile_for(
    *,
    tenant_id: str,
    scenario_id: str,
    scenario_hash: str,
    bindings: tuple[Any, ...],
    declared_at: Any,
    metadata: dict[str, Any],
) -> ScenarioEvaluationProfile:
    """One self-consistent evaluation profile for an arbitrary tenant/scenario."""
    profile = ScenarioEvaluationProfile(
        identifier=evaluation_profile_identifier(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            scenario_content_hash_value=scenario_hash,
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        scenario_content_hash=scenario_hash,
        bindings=bindings,
        content_hash="0" * 64,
        declared_at=declared_at,
        metadata=metadata,
    )
    return profile.model_copy(update={"content_hash": evaluation_profile_content_hash(profile)})


def _declared_profile_store() -> InMemoryScenarioStore:
    """The real profile-bearing runtime-3 acceptance lifecycle.

    Every declaration goes through the real declaration services: the
    five-objective scenario, the pack binding, state model sm-1, the two
    guarded causal transitions t-x/t-y, the single metric-observation
    binding m-1 -> level, the discrete uncertainty model (branch values
    5/9), and the evaluation profile **declared before world
    compilation**, so the compiled world embeds the exact profile
    snapshot. The campaign is prepared (two strategies mock-a/mock-b,
    seeds seed-0/seed-2), planned, started, fully executed, and every
    observation set explicitly extracted through the real services.
    Nothing is patched or injected.
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
    with patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 2):
        prepare_realization_campaign(
            store=store,
            legion=acceptance_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-1",
            campaign_name="Outcome query acceptance campaign",
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


@pytest.fixture(scope="module")
def outcome_store() -> InMemoryScenarioStore:
    """The real executed profile-bearing acceptance store (built once)."""
    return _declared_profile_store()


@pytest.fixture()
def store(outcome_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the real lifecycle store."""
    return copy.deepcopy(outcome_store)


class TestRealLifecycleProof:
    """The real COMPLETE multi-strategy/shared-seed proof (no mocks)."""

    def test_complete_multi_strategy_shared_seed_campaign_returns_accepted_evidence(
        self, store: InMemoryScenarioStore
    ) -> None:
        matrix = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(matrix, CampaignOutcomeDistributionMatrix)
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
        for strategy_position, strategy_id in enumerate(("mock-a", "mock-b")):
            for objective_position, objective_id in enumerate(
                ("obj-1", "obj-2", "obj-3", "obj-4", "obj-5")
            ):
                outcome = _outcome(matrix, strategy_position, objective_position)
                assert outcome.strategy_candidate_id == strategy_id
                assert outcome.objective_id == objective_id
                assert outcome.sequence_position == strategy_position * 5 + objective_position
                assert outcome.ordered_observed_values == expected_values
                assert outcome.empirical_distribution.ordered_samples == expected_values
                assert outcome.empirical_distribution.sample_count == 2

        targeted = _outcome(matrix, 0, 0)
        assert targeted.direction == "minimize"
        assert targeted.target == 100.0
        assert targeted.metric_unit == "units"
        assert targeted.target_achievement_count == 1
        assert targeted.empirical_target_achievement_probability == 0.5
        assert targeted.worst_normalized_target_violation == 0.03
        assert targeted.target_violation_cvar == 0.03
        assert targeted.adverse_tail_statistic == 103.0

        maximize = _outcome(matrix, 0, 1)
        assert maximize.direction == "maximize"
        assert maximize.target == 90.0
        assert maximize.target_achievement_count == 1
        assert maximize.empirical_target_achievement_probability == 0.5
        assert maximize.worst_normalized_target_violation == 0.06
        assert maximize.target_violation_cvar == 0.06
        assert maximize.adverse_tail_statistic == 84.0

        reach = _outcome(matrix, 0, 2)
        assert reach.direction == "reach"
        assert reach.target == 100.0
        assert reach.reach_tolerance == 5.0
        assert reach.target_achievement_count == 1
        assert reach.empirical_target_achievement_probability == 0.5
        assert reach.worst_normalized_target_violation == 0.11
        assert reach.target_violation_cvar == 0.11
        assert reach.adverse_tail_statistic == 16.0

        for objective_position, adverse in ((3, 103.0), (4, 84.0)):
            optimization_only = _outcome(matrix, 0, objective_position)
            assert optimization_only.target is None
            assert optimization_only.target_achievement_count is None
            assert optimization_only.empirical_target_achievement_probability is None
            assert optimization_only.normalized_target_violation_distribution is None
            assert optimization_only.worst_normalized_target_violation is None
            assert optimization_only.target_violation_cvar is None
            assert optimization_only.adverse_tail_statistic == adverse

        # Strategy-major block: the second strategy carries the same
        # shared-seed outcome evidence in the same objective-minor order.
        for objective_position in range(5):
            assert _outcome(matrix, 1, objective_position).ordered_observed_values == (
                expected_values
            )

    def test_world_embeds_the_declared_profile_snapshot(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        manifest = store.get_manifest(TENANT, campaign.world_version_id)
        verify_world_snapshot(world, manifest)
        embedded = extract_world_catalog(world).evaluation_profile
        assert embedded is not None
        stored = store.get_evaluation_profile(TENANT, world.source_scenario_id)
        assert embedded.model_dump(mode="json") == stored.model_dump(mode="json")
        assert embedded.identifier == evaluation_profile_identifier(
            tenant_id=TENANT,
            scenario_id=world.source_scenario_id,
            scenario_content_hash_value=scenario_content_hash(
                store.get_scenario(TENANT, world.source_scenario_id)
            ),
        )
        matrix = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.evaluation_profile_id == embedded.identifier
        assert matrix.evaluation_profile_content_hash == embedded.content_hash
        assert matrix.scenario_content_hash == embedded.scenario_content_hash
        assert matrix.uncertainty_model_id is not None
        assert matrix.uncertainty_model_content_hash is not None
        stored_model = store.get_world_uncertainty_model(TENANT, world.source_scenario_id)
        assert matrix.uncertainty_model_id == stored_model.identifier
        assert matrix.uncertainty_model_content_hash == stored_model.content_hash

    def test_query_lineage_equals_direct_pure_builder_over_same_verified_sources(
        self, store: InMemoryScenarioStore
    ) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        embedded = extract_world_catalog(world).evaluation_profile
        assert embedded is not None
        realization_matrix = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        direct = build_campaign_outcome_distribution_matrix(
            profile=embedded,
            world_realization_matrix=realization_matrix,
            observation_matrix=observation_matrix,
        )
        queried = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert queried.identifier == direct.identifier
        assert queried.content_hash == direct.content_hash
        assert queried.derived_at == direct.derived_at
        assert queried.model_dump(mode="json") == direct.model_dump(mode="json")
        assert queried.source_world_realization_matrix_id == realization_matrix.identifier
        assert queried.source_world_realization_matrix_content_hash == (
            realization_matrix.content_hash
        )
        assert queried.source_metric_observation_matrix_id == observation_matrix.identifier
        assert queried.source_metric_observation_matrix_content_hash == (
            observation_matrix.content_hash
        )
        assert queried.derived_at == observation_matrix.assembled_at
        assert observation_matrix.assembled_at == realization_matrix.assembled_at
        assert realization_matrix.assembled_at == campaign.created_at

    def test_repeated_calls_byte_identical_json(self, store: InMemoryScenarioStore) -> None:
        first = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        third = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        first_json = first.model_dump(mode="json")
        second_json = second.model_dump(mode="json")
        third_json = third.model_dump(mode="json")
        assert second_json == first_json
        assert third_json == first_json
        assert canonical_json(second_json) == canonical_json(first_json)
        assert canonical_json(third_json) == canonical_json(first_json)

    def test_entire_store_unchanged_after_successful_queries(
        self, store: InMemoryScenarioStore
    ) -> None:
        before = _store_state(store)
        for _ in range(3):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        after = _store_state(store)
        assert after == before


class TestCallCounts:
    """Exact once-per-operation wiring and zero-work proofs."""

    def test_successful_query_calls_upstreams_and_builder_exactly_once(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        counts = _install_spies(monkeypatch)
        result = service_module.get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert counts == {"realizations": 1, "observations": 1, "builder": 1}
        assert isinstance(result, CampaignOutcomeDistributionMatrix)

    @pytest.mark.parametrize(
        ("tenant_id", "campaign_id"),
        ((TENANT, "campaign-unknown"), ("tenant-2", "campaign-1")),
    )
    def test_unknown_campaign_and_foreign_tenant_are_indistinguishable_and_do_no_work(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        tenant_id: str,
        campaign_id: str,
    ) -> None:
        counts = _install_spies(monkeypatch)
        before = _store_state(store)
        with pytest.raises(CampaignNotFoundError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=tenant_id, campaign_id=campaign_id
            )
        assert counts == {"realizations": 0, "observations": 0, "builder": 0}
        assert _store_state(store) == before


class TestStateGate:
    """Every non-COMPLETE state is rejected before any derivation."""

    @pytest.mark.parametrize(
        "state",
        (
            CampaignState.DRAFT,
            CampaignState.VALIDATED,
            CampaignState.COMPILED,
            CampaignState.RUNNING,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        ),
    )
    def test_non_complete_states_rejected_before_derivation(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        state: CampaignState,
    ) -> None:
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": state})
        )
        counts = _install_spies(monkeypatch)
        with pytest.raises(CampaignNotCompleteError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.current_state == state.value
        assert counts == {"realizations": 0, "observations": 0, "builder": 0}


class TestProfileAssembly:
    """The world/profile assembly fail-closed matrix."""

    def test_world_without_embedded_profile_raises_not_found_and_invents_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = acceptance_observation_store()
        counts = _install_spies(monkeypatch)
        before = _store_state(store)
        with pytest.raises(EvaluationProfileNotFoundError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.scenario_id == "scenario-1"
        assert counts == {"realizations": 0, "observations": 0, "builder": 0}
        assert _store_state(store) == before

    def test_missing_stored_profile_fails_closed(self, store: InMemoryScenarioStore) -> None:
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.campaign_id == "campaign-1"

    def test_validator_bypassed_stored_profile_corruption_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        bad_binding = stored.bindings[0].model_copy(update={"normalization_scale": -1.0})
        bypassed = ScenarioEvaluationProfile.model_construct(
            identifier=stored.identifier,
            tenant_id=stored.tenant_id,
            scenario_id=stored.scenario_id,
            scenario_content_hash=stored.scenario_content_hash,
            bindings=tuple(
                bad_binding if binding.objective_id == "obj-1" else binding
                for binding in stored.bindings
            ),
            content_hash=stored.content_hash,
            declared_at=stored.declared_at,
            metadata=stored.metadata,
        )
        store._evaluation_profiles[(TENANT, "scenario-1")] = bypassed
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_stored_profile_identifier_tamper_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"identifier": "tampered-profile-identifier"})
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_stored_profile_content_hash_tamper_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"content_hash": "1" * 64})
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_self_consistent_rehashed_stored_profile_differing_from_embedded_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        tampered = stored.model_copy(
            update={
                "bindings": tuple(
                    binding.model_copy(update={"weight": 2.0})
                    if binding.objective_id == "obj-3"
                    else binding
                    for binding in stored.bindings
                )
            }
        )
        tampered = tampered.model_copy(
            update={"content_hash": evaluation_profile_content_hash(tampered)}
        )
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        reason = exc_info.value.reason
        assert reason is not None and "mismatch" in reason

    def test_foreign_tenant_profile_substitution_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        foreign = _profile_for(
            tenant_id="tenant-2",
            scenario_id="scenario-1",
            scenario_hash=stored.scenario_content_hash,
            bindings=stored.bindings,
            declared_at=stored.declared_at,
            metadata=stored.metadata,
        )
        store._evaluation_profiles[(TENANT, "scenario-1")] = foreign
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_foreign_scenario_profile_substitution_fails_closed(
        self, store: InMemoryScenarioStore
    ) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        foreign = _profile_for(
            tenant_id=TENANT,
            scenario_id="scenario-other",
            scenario_hash=stored.scenario_content_hash,
            bindings=stored.bindings,
            declared_at=stored.declared_at,
            metadata=stored.metadata,
        )
        store._evaluation_profiles[(TENANT, "scenario-1")] = foreign
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_missing_world_fails_closed(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._worlds[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_missing_manifest_fails_closed(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._manifests[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_corrupted_world_fails_closed(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        store._worlds[(TENANT, campaign.world_version_id)] = world.model_copy(
            update={"content_hash": "2" * 64}
        )
        with pytest.raises(WorldSnapshotIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestUpstreamPropagation:
    """Established upstream typed errors pass through unchanged."""

    def test_stored_uncertainty_model_corruption_rejected_through_realization_query(
        self, store: InMemoryScenarioStore
    ) -> None:
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
        tampered = tampered.model_copy(
            update={"content_hash": uncertainty_model_content_hash(tampered)}
        )
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("index", (0, 1, 3))
    def test_missing_first_middle_last_observation_set_prevents_any_result(
        self, store: InMemoryScenarioStore, index: int
    ) -> None:
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[index])
        del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_corrupted_observation_set_prevents_any_result(
        self, store: InMemoryScenarioStore
    ) -> None:
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        stored_set = store.get_realization_run_metric_observation_set(TENANT, run_id)
        tampered = stored_set.model_copy(
            update={
                "observations": tuple(
                    observation.model_copy(update={"raw_value": 100})
                    for observation in stored_set.observations
                )
            }
        )
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_unsupported_recorded_runtime_preserves_typed_error(
        self, store: InMemoryScenarioStore
    ) -> None:
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.runtime_version == "9.9.9"


class TestErrorSafety:
    """Generic non-leaking messages, no partial matrices, no writes."""

    @pytest.mark.parametrize("failure", ("missing_profile", "tampered_profile", "missing_world"))
    def test_integrity_public_message_exact_generic_and_non_leaking(
        self, store: InMemoryScenarioStore, failure: str
    ) -> None:
        if failure == "missing_profile":
            del store._evaluation_profiles[(TENANT, "scenario-1")]
        elif failure == "tampered_profile":
            stored = store.get_evaluation_profile(TENANT, "scenario-1")
            store._evaluation_profiles[(TENANT, "scenario-1")] = stored.model_copy(
                update={"content_hash": "1" * 64}
            )
        else:
            campaign = store.get_campaign(TENANT, "campaign-1")
            del store._worlds[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as exc_info:
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        error = exc_info.value
        assert str(error) == (
            "Campaign 'campaign-1' failed outcome distribution matrix integrity "
            "verification and was rejected"
        )
        reason = error.reason
        assert reason is not None and reason not in str(error)
        assert "scenario-1" not in str(error)
        assert "evaluation" not in str(error)

    @pytest.mark.parametrize(
        ("failure", "expected_type"),
        (
            ("missing_profile", CampaignOutcomeDistributionMatrixIntegrityError),
            ("tampered_profile", CampaignOutcomeDistributionMatrixIntegrityError),
            ("missing_world", CampaignOutcomeDistributionMatrixIntegrityError),
            ("missing_observations", RealizationCampaignMetricObservationMatrixIntegrityError),
        ),
    )
    def test_failures_never_yield_partial_matrix_and_do_not_write(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        failure: str,
        expected_type: type[Exception],
    ) -> None:
        if failure == "missing_profile":
            del store._evaluation_profiles[(TENANT, "scenario-1")]
        elif failure == "tampered_profile":
            stored = store.get_evaluation_profile(TENANT, "scenario-1")
            store._evaluation_profiles[(TENANT, "scenario-1")] = stored.model_copy(
                update={"content_hash": "1" * 64}
            )
        elif failure == "missing_world":
            campaign = store.get_campaign(TENANT, "campaign-1")
            del store._worlds[(TENANT, campaign.world_version_id)]
        else:
            run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[2])
            del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        counts = _install_spies(monkeypatch)
        before = _store_state(store)
        with pytest.raises(expected_type):
            service_module.get_verified_campaign_outcome_distributions(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert counts["builder"] == 0
        assert _store_state(store) == before


class TestModuleBoundaries:
    """AST/import/call-boundary proofs and unchanged registry/schema counts."""

    def test_module_exact_public_surface_and_signature(self) -> None:
        assert service_module.__all__ == ["get_verified_campaign_outcome_distributions"]
        signature = inspect.signature(service_module.get_verified_campaign_outcome_distributions)
        parameters = tuple(signature.parameters.values())
        assert [parameter.name for parameter in parameters] == ["store", "tenant_id", "campaign_id"]
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters)
        assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)

    def test_upstream_and_builder_symbols_are_the_accepted_verified_functions(self) -> None:
        from kalhas.application import (
            campaign_outcome_matrix_runtime,
            realization_campaign_metric_observation_query_service,
            world_realization_query_service,
        )

        observation_query_service = realization_campaign_metric_observation_query_service
        assert (
            _module_symbol(service_module, "get_verified_campaign_world_realizations")
            is world_realization_query_service.get_verified_campaign_world_realizations
        )
        assert (
            _module_symbol(
                service_module,
                "get_verified_realization_campaign_metric_observation_matrix",
            )
            is observation_query_service.get_verified_realization_campaign_metric_observation_matrix
        )
        assert (
            _module_symbol(service_module, "build_campaign_outcome_distribution_matrix")
            is campaign_outcome_matrix_runtime.build_campaign_outcome_distribution_matrix
        )

    def test_imports_only_allowed_kernel_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        paths = _imported_module_paths(tree)
        forbidden_prefixes = ("kalhas.api", "kalhas.adapters", "kalhas.domain_packs")
        for path in sorted(paths):
            assert not path.startswith(forbidden_prefixes), path
        top_level = _imported_modules(tree)
        forbidden_top_level = {
            "fastapi",
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

    def test_no_store_write_or_mutation_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        allowed = {
            "get_campaign",
            "get_campaign_status",
            "get_world",
            "get_manifest",
            "get_evaluation_profile",
            "model_dump",
        }
        assert called <= allowed, f"unexpected method calls: {sorted(called - allowed)}"

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        symbols: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
                symbols.extend(argument.arg for argument in node.args.args)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"

    def test_no_phase_number_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_public_contracts_and_schemas_stay_47(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) == 47
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 47
        file_names = {path.name for path in schema_files}
        assert "CampaignOutcomeDistributionMatrix.schema.json" in file_names

    def test_accepted_baseline_files_remain_byte_identical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative, expected in _PRESERVED_FILES:
            digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            assert digest == expected, f"{relative} changed: {digest}"


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``math`` from ``math.fsum``)."""
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
