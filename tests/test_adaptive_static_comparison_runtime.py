"""Focused H28-S09F tests for the adaptive-vs-static comparison runtime.

The fixture below is a fully repository-native reproduction of the proven
real-service environment used by the H28-S09D verification drivers: every
declaration, campaign preparation, runtime-3 execution, runtime-4 planning
and execution, and external-input acceptance goes through the real
application services over one ``InMemoryScenarioStore``. No scratch driver
is imported, no final state is patched, and the only aligned expectation is
the sanctioned two-candidate strategy-set size during campaign preparation.

Covered here (H28-S09F): the happy-path derivation shape, exact seed-major
alignment and paired-delta/statistics recomputation, adaptive identity vs.
the initial-action strategy anchor across the recorded switch, shared
authorities with noise/switch summaries and the stored tie tolerance,
deterministic repeated equality with a full-store zero-write fingerprint,
and the two ratified regressions (frozen wide adaptive-run digest; static
realization provenance under the verified embedded uncertainty model).

The typed rejection matrix implemented here (H28-S09G3): the runtime gate
(any requested runtime other than exactly ``4.0.0``, proven to precede the
first store read), runtime-4 adaptive execution authority mismatches
(run-plan identity, seed identity/hash, realization identity/hash,
adaptive-policy binding, and the independently recomputed wide input hash),
and runtime-3 static execution candidate, seed, and realization provenance
mismatches - every rejection proving deterministic zero-write behavior
through exact full-store fingerprint equality.

The typed rejection matrix added here (H28-S09G4): missing, foreign-tenant,
and corrupt campaign, world, decision-policy, and adaptive-policy
authorities (embedded evaluation-profile corruption included, reachable
only through the world snapshot seam), reordered and duplicated campaign
seed/plan identity, missing/extra/wrong-runtime/plan-set-hash-mismatched
adaptive RunPlan authorities, and adaptive-policy identifier, ``policy_id``,
and content-hash mismatches - again every rejection typed, stable-reasoned,
and exactly zero-write with the restored fingerprint equal to the pristine
one.

The typed rejection matrix added here (H28-S09G5, closing categories 8-11):
missing and corrupt stored runtime-3 metric-observation authorities, the
ambiguous evaluation-profile metric binding and the reordered decision-
policy objective-weight snapshot (a dedicated multi-objective draw-free
environment), real-draw observation-noise provenance with the explicit
verified no-draw semantics of the default no-noise fixture, and the
campaign-side foreign-seed authority distinguished from the already-covered
forged adaptive-plan seed vector - every rejection again typed,
stable-reasoned, and exactly zero-write.
"""

from __future__ import annotations

import hashlib
import json
import operator
from collections.abc import Callable
from typing import Any, NamedTuple
from unittest.mock import patch

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import realization_campaign_service
from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_policy_identity import (
    adaptive_policy_content_hash,
)
from kalhas.application.adaptive_run_execution_builder import AdaptiveRunExecutionBuildDraft
from kalhas.application.adaptive_run_execution_service import execute_adaptive_run
from kalhas.application.adaptive_run_planner import ADAPTIVE_RUNTIME_VERSION, plan_adaptive_runs
from kalhas.application.adaptive_static_comparison_runtime import (
    RUNTIME_VERSION,
    AdaptiveStaticComparisonEvidence,
    derive_adaptive_static_comparison_evidence,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_input_hash,
    adaptive_run_trajectory_execution_content_hash,
)
from kalhas.application.campaign_decision_identity import (
    campaign_decision_policy_content_hash,
)
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
)
from kalhas.application.campaign_decision_statistics import (
    paired_delta_statistics,
    paired_delta_vector,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.domain_metric_observation_service import declare_domain_metric_observation
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
    accept_external_observation_input_bundle,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_identity import (
    realization_run_trajectory_execution_content_hash,
)
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
    run_identifier,
)
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_identity import (
    runtime_observation_event_content_hash,
)
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
    strategy_candidate_content_hash,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_campaign_world_realization_matrix
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.realization_trajectory_execution import RealizationRunTrajectoryExecution
from kalhas.contracts.v1.runtime_observation import (
    AdditiveUniformObservationNoise,
    NoObservationNoise,
    ObservationTiming,
)
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection, ScenarioSeed
from kalhas.contracts.v1.world_realization import DiscreteDistribution

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import uncertainty_fields
from tests.phase25_helpers import acceptance_legion

FOREIGN_TENANT = "tenant-other"

OBJ = "obj-1"
METRIC = "m-1"
CAMPAIGN = "campaign-1"

SEEDS: tuple[ScenarioSeed, ...] = (
    build_seed(identifier="seed-1"),
    build_seed(identifier="seed-2"),
)


def store_fingerprint(store: InMemoryScenarioStore) -> str:
    """Deterministic digest over every private store collection, including sizes."""
    parts: list[str] = []
    for name in sorted(vars(store)):
        value: object = getattr(store, name)
        try:
            rendered = repr(value)
        except Exception:
            rendered = "<unrenderable>"
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        parts.append(f"{name}#{len(rendered)}#{digest}")
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()


def build_comparison_env(
    seeds: tuple[ScenarioSeed, ...],
    *,
    initial_action: str = "act-1",
    policy_id: str = "policy-1",
    campaign: str = CAMPAIGN,
    declaration_noise: NoObservationNoise | AdditiveUniformObservationNoise | None = None,
    step_one_value: int = -3,
) -> tuple[InMemoryScenarioStore, str]:
    """The full adaptive-vs-static environment over the real services.

    Two static runtime-3 candidates across the ordered seeds with real
    trajectory execution and stored metric observations, a COMPLETE-to-
    COMPILED lifecycle with a declared decision policy, then runtime-4
    observation declaration, adaptive policy binding, one adaptive RunPlan
    per ordered seed (written by tuple replacement), accepted external
    input bundles, and real COMPLETE adaptive executions.

    With the default ``NoObservationNoise`` the declaration observes the
    accepted external bundle (no fresh noise is contract-expressible for
    an external source). With an ``AdditiveUniformObservationNoise`` the
    declaration instead observes the declared visible ``level`` state
    field, so each adaptive run performs exactly one real deterministic
    noise draw per observed coordinate.
    """
    store = InMemoryScenarioStore()
    store.put_scenario(build_observation_scenario())
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
        description="X branch",
        guard_values={"level": 5},
        target_values={"level": 84},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-y",
        description="Y branch",
        guard_values={"level": 9},
        target_values={"level": 103},
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=METRIC,
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
                    kind="discrete", values=(5, 9), probabilities=(0.5, 0.5)
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
        bindings=(
            ObjectiveMetricBindingDraft(
                objective_id=OBJ,
                metric_id=METRIC,
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
        ),
        declared_at=DECLARED_AT,
        metadata={},
    )
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    world_id = compiled.version.identifier
    store.put_world(compiled.version, compiled.manifest)
    with patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 2):
        prepare_realization_campaign(
            store=store,
            legion=acceptance_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            strategy_request=build_request(TENANT),
            campaign_id=campaign,
            campaign_name="Adaptive comparison campaign",
            seed_ensemble=seeds,
            created_at=NOW,
        )
    prepare_strategy_trajectory_plans(
        store=store, legion=acceptance_legion(), tenant_id=TENANT, campaign_id=campaign
    )
    start(store, campaign)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id=campaign)
    for plan in store.get_run_plans(TENANT, campaign):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=f"run-{plan.identifier}"
        )
    declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign,
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="global",
            minimum_target_achievement_probability=0.5,
            minimum_sample_count=1,
            tie_tolerance=0.05,
            all_targeted_objectives_are_hard_gates=False,
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )
    status = store.get_campaign_status(TENANT, campaign)
    store.update_campaign_status(
        TENANT, campaign, status.model_copy(update={"state": CampaignState.COMPILED})
    )
    noise = (
        declaration_noise
        if declaration_noise is not None
        else NoObservationNoise(kind="none", draw_count=0)
    )
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-level",
            state_source=StateFieldObservationDraft(
                manifest_id="manifest-1", state_model_id="sm-1", state_field_id="level"
            )
            if isinstance(noise, AdditiveUniformObservationNoise)
            else None,
            external_source=ExternalObservationDraft(
                external_channel_id="channel-1", external_value_kind="integer"
            )
            if isinstance(noise, NoObservationNoise)
            else None,
            timing=ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0),
            noise=noise,
            missing_behavior="false",
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )

    def leaf(cid: str) -> ConditionComparisonLeaf:
        return ConditionComparisonLeaf(
            kind="comparison",
            condition_id=cid,
            observation_id="obs-level",
            observed_value_kind="number"
            if isinstance(noise, AdditiveUniformObservationNoise)
            else "integer",
            unit=None,
            operator="gt",
            threshold=0,
            missing_behavior="false",
        )

    fallback = "act-2" if initial_action == "act-1" else "act-1"
    draft = AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id=initial_action,
        fallback_action_id=fallback,
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=leaf("c1a"),
                retain_condition=leaf("c1r"),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-2",
                priority=1,
                target_action_id="act-2",
                enter_condition=leaf("c2a"),
                retain_condition=leaf("c2r"),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign,
        draft=draft,
        binding_request=AdaptivePolicyBindingRequest(
            policy_id=policy_id,
            policy_version="1.0.0",
            action_mappings=(
                ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-a"),
                ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-b"),
            ),
            bound_at=NOW,
            metadata={},
        ),
    )
    bundle_drafts: dict[str, ExternalObservationInputBundleDraft] = {}
    if isinstance(noise, NoObservationNoise):
        for seed in seeds:
            bundle_draft = ExternalObservationInputBundleDraft(
                entries=(
                    ExternalObservationInputValueDraft(
                        observation_id="obs-level", source_step_index=0, value=5
                    ),
                    ExternalObservationInputValueDraft(
                        observation_id="obs-level",
                        source_step_index=1,
                        value=step_one_value,
                    ),
                ),
                accepted_at=NOW,
            )
            accept_external_observation_input_bundle(
                store,
                tenant_id=TENANT,
                campaign_id=campaign,
                scenario_seed_id=seed.identifier,
                draft=bundle_draft,
            )
            bundle_drafts[seed.identifier] = bundle_draft
    campaign_obj = store.get_campaign(TENANT, campaign)
    world = store.get_world(TENANT, campaign_obj.world_version_id)
    catalog = extract_world_catalog(world)
    model = store.get_world_uncertainty_model(TENANT, "scenario-1")
    matrix = build_campaign_world_realization_matrix(
        campaign=campaign_obj,
        world=world,
        state_models=catalog.state_models,
        model=model,
    )
    realizations = {r.scenario_seed_id: r for r in matrix.realizations}
    policy = store.get_adaptive_policy(TENANT, campaign)
    plans = plan_adaptive_runs(
        campaign_id=campaign,
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        policy=policy,
        seeds=campaign_obj.seed_ensemble,
        created_at=campaign_obj.created_at,
        realizations=realizations,
        runtime_version=ADAPTIVE_RUNTIME_VERSION,
    )
    store.put_run_plans(TENANT, campaign, plans)
    for adaptive_plan in plans:
        adaptive_run_id = run_identifier(adaptive_plan)
        store.put_run_status(
            TENANT,
            adaptive_run_id,
            RunStatus(
                identifier=f"status-{adaptive_run_id}",
                tenant_id=TENANT,
                run_id=adaptive_run_id,
                campaign_id=campaign,
                run_plan_id=adaptive_plan.identifier,
                state=RunState.PLANNED,
                runtime_version=adaptive_plan.runtime_version,
                input_hash=adaptive_plan.input_hash,
                event_hash=None,
                created_at=adaptive_plan.created_at,
                changed_at=adaptive_plan.created_at,
            ),
        )
        result = execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=adaptive_run_id,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=1,
                external_bundle_draft=(
                    bundle_drafts[adaptive_plan.scenario_seed_id]
                    if isinstance(noise, NoObservationNoise)
                    else None
                ),
            ),
        )
        assert result.status.state is RunState.COMPLETE, result.status
    return store, world_id


def _matrix_of(store: InMemoryScenarioStore, campaign_id: str) -> Any:
    """The campaign realization matrix rebuilt from the stored authority."""
    campaign = store.get_campaign(TENANT, campaign_id)
    world = store.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    model = store.get_world_uncertainty_model(TENANT, campaign.scenario_id)
    return build_campaign_world_realization_matrix(
        campaign=campaign,
        world=world,
        state_models=catalog.state_models,
        model=model,
    )


def _derive(store: InMemoryScenarioStore) -> AdaptiveStaticComparisonEvidence:
    return derive_adaptive_static_comparison_evidence(store, tenant_id=TENANT, campaign_id=CAMPAIGN)


def _multi_derive(store: InMemoryScenarioStore) -> AdaptiveStaticComparisonEvidence:
    """Derive the comparison evidence of the multi-objective environment."""
    return derive_adaptive_static_comparison_evidence(
        store, tenant_id=TENANT, campaign_id="campaign-multi"
    )


def _adaptive_plan_and_execution(
    store: InMemoryScenarioStore,
) -> tuple[Any, Any, Any]:
    """The first stored adaptive plan, its execution, and its seed/realization."""
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, campaign.world_version_id)
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    plans = store.get_run_plans(TENANT, CAMPAIGN)
    assert len(plans) == 2
    plan = plans[0]
    execution = store.get_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=f"run-{plan.identifier}"
    )
    seed = next(
        candidate_seed
        for candidate_seed in campaign.seed_ensemble
        if candidate_seed.identifier == plan.scenario_seed_id
    )
    matrix = _matrix_of(store, CAMPAIGN)
    realization = next(
        candidate_realization
        for candidate_realization in matrix.realizations
        if candidate_realization.scenario_seed_id == plan.scenario_seed_id
    )
    return (plan, execution, (world, policy, seed, realization))


def _self_consistent_tamper(execution: Any, updates: dict[str, Any], hasher: Any) -> Any:
    """A narrowly changed model_copy whose content hash covers the change.

    ``hasher`` is the live content-hash primitive of the execution's own
    contract, so the tampered record stays self-consistent and reaches the
    intended authority verifier instead of failing earlier for generic
    corruption.
    """
    broken = execution.model_copy(update=updates)
    return broken.model_copy(update={"content_hash": hasher(broken)})


def _assert_tamper_rejected_zero_write(
    store: InMemoryScenarioStore,
    collection: dict[tuple[str, str], Any],
    key: tuple[str, str],
    original: Any,
    updates: dict[str, Any],
    hasher: Any,
    *,
    expected_reason: str,
) -> None:
    """Inject a self-consistent tamper, assert the typed rejection, restore.

    The derivation must fail closed with the exact comparison validation
    error carrying the stable internal reason; the derivation itself must
    be write-free (fingerprint taken with the tampered record already in
    place must be reproduced exactly); and the original authority is put
    back in a finally block, with the restored full-store fingerprint
    required to equal the pre-injection fingerprint.
    """
    pristine = store_fingerprint(store)
    try:
        collection[key] = _self_consistent_tamper(original, updates, hasher)
        before = store_fingerprint(store)
        with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
            _derive(store)
        assert excinfo.value.reason == expected_reason
        assert store_fingerprint(store) == before
    finally:
        collection[key] = original
    assert store_fingerprint(store) == pristine


def _static_plan_and_execution(store: InMemoryScenarioStore) -> tuple[Any, Any, str]:
    """The recomputed static runtime-3 plan for (``mock-a``, ``seed-1``).

    The expected plan matrix is recomputed with the accepted pure
    runtime-3 planner over the campaign's single authoritative
    realization matrix - exactly the authority the comparison verifier
    derives - and paired with the stored runtime-3 execution record.
    """
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, campaign.world_version_id)
    candidates = store.get_strategy_candidates(TENANT, CAMPAIGN)
    matrix = _matrix_of(store, CAMPAIGN)
    realizations = {
        candidate_realization.scenario_seed_id: candidate_realization
        for candidate_realization in matrix.realizations
    }
    expected_plans = plan_realization_runs(
        campaign_id=campaign.identifier,
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=candidates,
        seeds=campaign.seed_ensemble,
        created_at=campaign.created_at,
        realizations=realizations,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    )
    plan = next(
        candidate_plan
        for candidate_plan in expected_plans
        if candidate_plan.strategy_candidate_id == "mock-a"
        and candidate_plan.scenario_seed_id == "seed-1"
    )
    run_id = f"run-{plan.identifier}"
    execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
    return (plan, execution, run_id)


@pytest.fixture(scope="module")
def happy_env() -> tuple[InMemoryScenarioStore, str]:
    return build_comparison_env(SEEDS)


class TestHappyPathDerivation:
    def test_two_static_arms_one_adaptive_policy_arm_over_two_ordered_seeds(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, world_id = happy_env
        candidates = store.get_strategy_candidates(TENANT, CAMPAIGN)
        assert RUNTIME_VERSION == "4.0.0"
        evidence = _derive(store)
        assert evidence.campaign_id == CAMPAIGN
        assert evidence.scenario_id == "scenario-1"
        assert evidence.world_version_id == world_id
        assert evidence.ordered_seed_ids == ("seed-1", "seed-2")
        assert evidence.ordered_objective_ids == (OBJ,)
        assert evidence.adaptive_policy_id == "policy-1"
        assert (
            evidence.adaptive_policy_content_hash
            == store.get_adaptive_policy(TENANT, CAMPAIGN).content_hash
        )
        assert [
            (arm.strategy_candidate_id, arm.strategy_content_hash) for arm in evidence.static_arms
        ] == [
            (candidate.identifier, strategy_candidate_content_hash(candidate))
            for candidate in candidates
        ]
        assert [candidate.identifier for candidate in candidates] == ["mock-a", "mock-b"]
        assert len(evidence.objective_pairs) == len(evidence.static_arms) * len(
            evidence.ordered_objective_ids
        )
        assert [pair.pair_position for pair in evidence.objective_pairs] == [0, 1]
        assert [pair.static_strategy_candidate_id for pair in evidence.objective_pairs] == [
            "mock-a",
            "mock-b",
        ]
        assert all(pair.objective_position == 0 for pair in evidence.objective_pairs)
        assert all(len(pair.ordered_seed_ids) == 2 for pair in evidence.objective_pairs)
        assert all(
            len(pair.ordered_adaptive_values) == 2 and len(pair.ordered_static_values) == 2
            for pair in evidence.objective_pairs
        )


class TestSeedMajorAlignmentAndStatistics:
    def test_exact_seed_alignment_and_independent_delta_statistics_recomputation(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        evidence = _derive(store)
        world = store.get_world(TENANT, store.get_campaign(TENANT, CAMPAIGN).world_version_id)
        catalog = extract_world_catalog(world)
        profile = catalog.evaluation_profile
        assert profile is not None
        binding_by_objective = {binding.objective_id: binding for binding in profile.bindings}
        for pair in evidence.objective_pairs:
            assert pair.ordered_seed_ids == evidence.ordered_seed_ids
            binding = binding_by_objective[pair.objective_id]
            assert pair.direction == str(binding.direction)
            assert pair.normalization_scale == binding.normalization_scale
            assert pair.target == binding.target
            recomputed = paired_delta_vector(
                pair.ordered_adaptive_values,
                pair.ordered_static_values,
                direction=binding.direction,
                normalization_scale=binding.normalization_scale,
                target=binding.target,
            )
            assert pair.ordered_paired_deltas == recomputed
            assert pair.summary == paired_delta_statistics(
                recomputed, tie_tolerance=evidence.tie_tolerance
            )
            assert pair.summary.sample_count == 2
            assert pair.summary.win_count + pair.summary.tie_count + pair.summary.loss_count == 2
        receipts = evidence.seed_alignment_receipts
        assert [(r.scenario_seed_id, r.static_strategy_candidate_id) for r in receipts] == [
            ("seed-1", "mock-a"),
            ("seed-1", "mock-b"),
            ("seed-2", "mock-a"),
            ("seed-2", "mock-b"),
        ]


class TestAdaptiveIdentityAndSwitch:
    def test_identity_is_policy_id_and_hash_distinct_from_anchor_across_recorded_switch(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        evidence = _derive(store)
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
        assert evidence.adaptive_policy_id == policy.policy_id
        assert evidence.adaptive_policy_content_hash == policy.content_hash
        assert all(
            summary.initial_action_id == policy.initial_action_id
            for summary in evidence.switch_summaries
        )
        assert [summary.scenario_seed_id for summary in evidence.switch_summaries] == [
            "seed-1",
            "seed-2",
        ]
        anchors = {summary.initial_action_strategy_anchor for summary in evidence.switch_summaries}
        assert anchors == {"mock-a"}
        all_switches = [
            one_switch for summary in evidence.switch_summaries for one_switch in summary.switches
        ]
        assert len(all_switches) >= 1
        assert any(one_switch.left_initial_action_strategy_anchor for one_switch in all_switches)
        assert all(
            one_switch.scenario_seed_id in evidence.ordered_seed_ids for one_switch in all_switches
        )
        candidates = store.get_strategy_candidates(TENANT, CAMPAIGN)
        anchor_candidate = next(
            candidate
            for candidate in candidates
            if candidate.identifier == evidence.switch_summaries[0].initial_action_strategy_anchor
        )
        assert (evidence.adaptive_policy_id, evidence.adaptive_policy_content_hash) != (
            anchor_candidate.identifier,
            strategy_candidate_content_hash(anchor_candidate),
        )


class TestSharedAuthoritiesZeroWriteAndDeterminism:
    def test_shared_authorities_summaries_tolerance_and_zero_write_determinism(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        world = store.get_world(TENANT, campaign.world_version_id)
        decision_policy = store.get_campaign_decision_policy(TENANT, CAMPAIGN)
        evidence = _derive(store)
        assert evidence.world_version_id == campaign.world_version_id
        assert evidence.world_content_hash == world.content_hash
        assert evidence.tie_tolerance == decision_policy.tie_tolerance == 0.05
        assert evidence.minimum_sample_count == decision_policy.minimum_sample_count
        seeds_by_id = {seed.identifier: seed for seed in campaign.seed_ensemble}
        for receipt in evidence.seed_alignment_receipts:
            assert receipt.adaptive_world_realization_id == receipt.static_world_realization_id
            assert receipt.adaptive_world_content_hash == world.content_hash
            assert receipt.static_world_content_hash == world.content_hash
            assert receipt.adaptive_seed_content_hash == seed_content_hash(
                seeds_by_id[receipt.scenario_seed_id]
            )
            assert receipt.static_seed_content_hash == receipt.adaptive_seed_content_hash
        assert [summary.scenario_seed_id for summary in evidence.noise_summaries] == [
            "seed-1",
            "seed-2",
        ]
        assert all(summary.all_noise_coordinates_verified for summary in evidence.noise_summaries)
        before = store_fingerprint(store)
        repeated = _derive(store)
        assert repeated == evidence
        assert store_fingerprint(store) == before


class TestRatifiedRegressionAWideAdaptiveRunDigest:
    def test_adaptive_input_hash_equals_independent_wide_recomputation_and_differs_from_plan(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        plan, execution, (world, policy, seed, realization) = _adaptive_plan_and_execution(store)
        independent = adaptive_run_input_hash(
            run_plan_id=plan.identifier,
            run_plan_input_hash=plan.input_hash,
            campaign_id=CAMPAIGN,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            scenario_seed_id=seed.identifier,
            seed_content_hash_value=seed_content_hash(seed),
            world_realization_id=realization.identifier,
            world_realization_content_hash=realization.content_hash,
            adaptive_policy_identifier=policy.identifier,
            adaptive_policy_content_hash=policy.content_hash,
            trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
            external_observation_input_bundle_id=execution.external_observation_input_bundle_id,
            external_observation_input_bundle_content_hash=(
                execution.external_observation_input_bundle_content_hash
            ),
            final_decision_step=len(execution.decision_events) - 1,
        )
        assert execution.input_hash == independent
        assert execution.input_hash != plan.input_hash
        assert campaign.identifier == CAMPAIGN

    def test_tampered_wide_input_hash_fails_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        plan, execution, (world, policy, seed, realization) = _adaptive_plan_and_execution(store)
        run_id = f"run-{plan.identifier}"
        tampered_digest = adaptive_run_input_hash(
            run_plan_id=plan.identifier,
            run_plan_input_hash=plan.input_hash,
            campaign_id=CAMPAIGN,
            world_version_id=world.identifier,
            world_content_hash="f" * 64,
            scenario_seed_id=seed.identifier,
            seed_content_hash_value=seed_content_hash(seed),
            world_realization_id=realization.identifier,
            world_realization_content_hash=realization.content_hash,
            adaptive_policy_identifier=policy.identifier,
            adaptive_policy_content_hash=policy.content_hash,
            trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
            external_observation_input_bundle_id=execution.external_observation_input_bundle_id,
            external_observation_input_bundle_content_hash=(
                execution.external_observation_input_bundle_content_hash
            ),
            final_decision_step=len(execution.decision_events) - 1,
        )
        assert tampered_digest != execution.input_hash
        broken = execution.model_copy(update={"input_hash": tampered_digest})
        broken = broken.model_copy(
            update={"content_hash": adaptive_run_trajectory_execution_content_hash(broken)}
        )
        executions = store._adaptive_run_trajectory_executions
        original = executions[(TENANT, run_id)]
        executions[(TENANT, run_id)] = broken
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError):
                _derive(store)
            assert store_fingerprint(store) == before
        finally:
            executions[(TENANT, run_id)] = original


class TestRatifiedRegressionBStaticProvenance:
    def test_static_realization_under_verified_model_accepted_then_mismatch_fails_closed(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        world = store.get_world(TENANT, campaign.world_version_id)
        candidates = store.get_strategy_candidates(TENANT, CAMPAIGN)
        matrix = _matrix_of(store, CAMPAIGN)
        realizations = {
            candidate_realization.scenario_seed_id: candidate_realization
            for candidate_realization in matrix.realizations
        }
        expected_plans = plan_realization_runs(
            campaign_id=campaign.identifier,
            tenant_id=TENANT,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            strategies=candidates,
            seeds=campaign.seed_ensemble,
            created_at=campaign.created_at,
            realizations=realizations,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        )
        plan = next(
            candidate_plan
            for candidate_plan in expected_plans
            if candidate_plan.strategy_candidate_id == "mock-a"
            and candidate_plan.scenario_seed_id == "seed-1"
        )
        run_id = f"run-{plan.identifier}"
        execution: RealizationRunTrajectoryExecution = (
            store.get_realization_run_trajectory_execution(TENANT, run_id)
        )
        assert execution.world_realization_content_hash == realizations["seed-1"].content_hash
        accepted = _derive(store)
        assert accepted.campaign_id == CAMPAIGN
        broken = execution.model_copy(update={"world_realization_content_hash": "a" * 64})
        broken = broken.model_copy(
            update={"content_hash": realization_run_trajectory_execution_content_hash(broken)}
        )
        executions = store._realization_run_trajectory_executions
        original = executions[(TENANT, run_id)]
        executions[(TENANT, run_id)] = broken
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError):
                _derive(store)
            assert store_fingerprint(store) == before
        finally:
            executions[(TENANT, run_id)] = original


class TestRuntimeGateRejections:
    """Requested runtimes other than exactly 4.0.0 are rejected before any read."""

    def test_every_non_four_dot_zero_runtime_is_rejected_with_zero_write(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        before = store_fingerprint(store)
        for runtime_version in ("1.0.0", "2.0.0", "3.0.0", "4.0.1", "", " "):
            with pytest.raises(UnsupportedRuntimeVersionError) as excinfo:
                derive_adaptive_static_comparison_evidence(
                    store, tenant_id=TENANT, campaign_id=CAMPAIGN, runtime_version=runtime_version
                )
            assert excinfo.value.runtime_version == runtime_version
            assert excinfo.value.operation == "adaptive-vs-static comparison evidence"
            assert store_fingerprint(store) == before

    def test_runtime_gate_precedes_the_first_store_read(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        empty = InMemoryScenarioStore()
        for runtime_version in ("1.0.0", "2.0.0", "3.0.0", "4.0.1"):
            with pytest.raises(UnsupportedRuntimeVersionError) as gate_excinfo:
                derive_adaptive_static_comparison_evidence(
                    empty, tenant_id=TENANT, campaign_id=CAMPAIGN, runtime_version=runtime_version
                )
            assert gate_excinfo.value.runtime_version == runtime_version
        with pytest.raises(AdaptivePolicyBindingValidationError) as contrast_excinfo:
            derive_adaptive_static_comparison_evidence(
                empty, tenant_id=TENANT, campaign_id=CAMPAIGN, runtime_version=RUNTIME_VERSION
            )
        assert contrast_excinfo.value.reason == "campaign authority missing"


class TestAdaptiveExecutionAuthorityRejections:
    """Runtime-4 execution authority mismatches fail closed atomically.

    Each case injects a self-consistent tampered execution record through
    the established private in-memory-store seam: the content hash is
    recomputed with the live runtime-4 hash primitive, so the record
    passes strict revalidation and generic-corruption checks and the
    comparison verifier's stored-authority chain is what rejects it. The
    store getter itself independently cross-verifies the same stored
    authority chain on every read, so the stable rejection surfaces as
    the getter-wrapped comparison failure for every tampered field.
    """

    def test_execution_authority_tampers_fail_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        plan, execution, _ = _adaptive_plan_and_execution(store)
        run_id = f"run-{plan.identifier}"
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_id)
        cases: tuple[tuple[str, Any], ...] = (
            ("run_plan_id", f"{execution.run_plan_id}-forged"),
            ("scenario_seed_id", "seed-forged"),
            ("seed_content_hash", "b" * 64),
            ("world_realization_id", f"{execution.world_realization_id}-forged"),
            ("world_realization_content_hash", "c" * 64),
            ("adaptive_policy_identifier", f"{execution.adaptive_policy_identifier}-forged"),
            ("policy_id", f"{execution.policy_id}-forged"),
            ("adaptive_policy_content_hash", "d" * 64),
            ("input_hash", "0" * 64),
        )
        for field, value in cases:
            _assert_tamper_rejected_zero_write(
                store,
                collection,
                key,
                execution,
                {field: value},
                adaptive_run_trajectory_execution_content_hash,
                expected_reason="adaptive execution authority missing or corrupt",
            )


class TestStaticExecutionAuthorityRejections:
    """Runtime-3 static execution authority mismatches fail closed atomically.

    Runtime-3 executions are read raw by the comparison runtime and
    field-verified by its own authority verifier against the recomputed
    pure runtime-3 plan matrix, so each self-consistent tamper reaches
    the dedicated comparison rejection with its stable reason.
    """

    def test_static_execution_tampers_fail_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        plan, execution, run_id = _static_plan_and_execution(store)
        assert plan.input_hash == execution.input_hash
        collection = store._realization_run_trajectory_executions
        key = (TENANT, run_id)
        cases: tuple[tuple[str, Any], ...] = (
            ("strategy_candidate_id", "mock-forged"),
            ("strategy_content_hash", "e" * 64),
            ("scenario_seed_id", "seed-forged"),
            ("world_realization_id", f"{execution.world_realization_id}-forged"),
            ("world_realization_content_hash", "f" * 64),
            ("input_hash", "0" * 64),
        )
        for field, value in cases:
            _assert_tamper_rejected_zero_write(
                store,
                collection,
                key,
                execution,
                {field: value},
                realization_run_trajectory_execution_content_hash,
                expected_reason="runtime-3 execution authority mismatch",
            )


class _AuthorityCase(NamedTuple):
    """One named rejection vector of the H28-S09G4 authority matrix."""

    label: str
    expected_reason: str
    apply: Callable[[InMemoryScenarioStore], None]


def _remove_campaign(
    mapping: dict[tuple[str, str], Any], key: tuple[str, str]
) -> Callable[[InMemoryScenarioStore], None]:
    def apply(target_store: InMemoryScenarioStore) -> None:
        mapping.pop(key)

    return apply


def _relocate_authority(
    mapping: dict[tuple[str, str], Any], key: tuple[str, str], *, keep_local: bool
) -> Callable[[InMemoryScenarioStore], None]:
    """Move the stored authority under the foreign tenant, optionally keeping it.

    ``keep_local=False`` is the foreign-only form: the comparison tenant
    has no local record at all, so the strict getter cannot distinguish
    foreign tenancy from absence and the rejection proves tenant
    isolation exactly as a deletion does.
    """

    def apply(target_store: InMemoryScenarioStore) -> None:
        saved = mapping[key]
        if not keep_local:
            del mapping[key]
        mapping[(FOREIGN_TENANT, key[1])] = saved

    return apply


def _swap_model_copy(
    mapping: dict[Any, Any],
    key: Any,
    saved: Any,
    updates: tuple[tuple[str, Any], ...],
    hasher: Callable[[Any], str] | None,
) -> Callable[[InMemoryScenarioStore], None]:
    """A validator-passing ``model_copy`` swap, self-consistently rehashed."""

    def apply(target_store: InMemoryScenarioStore) -> None:
        record = saved
        for field, value in updates:
            record = record.model_copy(update={field: value})
        if hasher is not None:
            record = record.model_copy(update={"content_hash": hasher(record)})
        mapping[key] = record

    return apply


def _remove_world_and_manifest(
    world_key: tuple[str, str],
) -> Callable[[InMemoryScenarioStore], None]:
    def apply(target_store: InMemoryScenarioStore) -> None:
        target_store._worlds.pop(world_key)
        target_store._manifests.pop(world_key)

    return apply


def _relocate_world_and_manifest(
    world_key: tuple[str, str],
) -> Callable[[InMemoryScenarioStore], None]:
    def apply(target_store: InMemoryScenarioStore) -> None:
        world = target_store._worlds[world_key]
        manifest = target_store._manifests[world_key]
        del target_store._worlds[world_key]
        del target_store._manifests[world_key]
        target_store._worlds[(FOREIGN_TENANT, world_key[1])] = world
        target_store._manifests[(FOREIGN_TENANT, world_key[1])] = manifest

    return apply


def _remove_embedded_profile(
    world_key: tuple[str, str], world: Any
) -> Callable[[InMemoryScenarioStore], None]:
    def apply(target_store: InMemoryScenarioStore) -> None:
        body = dict(target_store._worlds[world_key].world)
        del body["evaluation_profile"]
        target_store._worlds[world_key] = world.model_copy(update={"world": body})

    return apply


def _corrupt_embedded_profile(
    world_key: tuple[str, str], world: Any
) -> Callable[[InMemoryScenarioStore], None]:
    def apply(target_store: InMemoryScenarioStore) -> None:
        body = dict(target_store._worlds[world_key].world)
        profile = body["evaluation_profile"]
        assert isinstance(profile, dict), "embedded evaluation_profile fixture must be a mapping"
        raw = dict(profile)
        raw["content_hash"] = "4" * 64
        body["evaluation_profile"] = raw
        target_store._worlds[world_key] = world.model_copy(update={"world": body})

    return apply


class TestAuthorityPresenceRejections:
    """Missing, foreign-only, and corrupt authority records fail closed.

    Deletion and foreign-only relocation use real private-store absence
    under the comparison tenant: the strict getters cannot distinguish
    absence from foreign tenancy, so the foreign-only cases prove tenant
    isolation exactly as a deletion does. Tenant-relocating ``model_copy``
    tampers and corrupted content hashes are self-consistently rehashed so
    they pass contract validators and reach exactly the intended comparison
    verifier. Embedded evaluation-profile corruption is reachable only
    through the world snapshot: the stored profile is never read by the
    comparison layer, and world verification (recompile equality) rejects
    every embedded corruption before any decision-policy seam.
    """

    def test_missing_foreign_and_corrupt_authorities_fail_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        pristine = store_fingerprint(store)
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        campaign_key = (TENANT, CAMPAIGN)
        world_key = (TENANT, campaign.world_version_id)
        decision_key = (TENANT, CAMPAIGN)
        adaptive_key = (TENANT, CAMPAIGN)
        world = store.get_world(TENANT, campaign.world_version_id)
        manifest = store.get_manifest(TENANT, campaign.world_version_id)
        decision_policy = store.get_campaign_decision_policy(TENANT, CAMPAIGN)
        adaptive_policy = store.get_adaptive_policy(TENANT, CAMPAIGN)

        cases: tuple[_AuthorityCase, ...] = (
            _AuthorityCase(
                "campaign missing",
                "campaign authority missing",
                _remove_campaign(store._campaigns, campaign_key),
            ),
            _AuthorityCase(
                "campaign foreign-only",
                "campaign authority missing",
                _relocate_authority(store._campaigns, campaign_key, keep_local=False),
            ),
            _AuthorityCase(
                "world missing",
                "world authority missing",
                _remove_world_and_manifest(world_key),
            ),
            _AuthorityCase(
                "world foreign-only",
                "world authority missing",
                _relocate_world_and_manifest(world_key),
            ),
            _AuthorityCase(
                "embedded evaluation profile missing",
                "world authority corrupt",
                _remove_embedded_profile(world_key, world),
            ),
            _AuthorityCase(
                "embedded evaluation profile corrupt",
                "world authority corrupt",
                _corrupt_embedded_profile(world_key, world),
            ),
            _AuthorityCase(
                "decision policy missing",
                "decision policy authority missing",
                _remove_campaign(store._campaign_decision_policies, decision_key),
            ),
            _AuthorityCase(
                "decision policy foreign-only",
                "decision policy authority missing",
                _relocate_authority(
                    store._campaign_decision_policies, decision_key, keep_local=False
                ),
            ),
            _AuthorityCase(
                "decision policy foreign tenant",
                "decision policy authority corrupt",
                _swap_model_copy(
                    store._campaign_decision_policies,
                    decision_key,
                    decision_policy,
                    (("tenant_id", FOREIGN_TENANT),),
                    campaign_decision_policy_content_hash,
                ),
            ),
            _AuthorityCase(
                "decision policy corrupt",
                "decision policy authority corrupt",
                _swap_model_copy(
                    store._campaign_decision_policies,
                    decision_key,
                    decision_policy,
                    (("content_hash", "8" * 64),),
                    None,
                ),
            ),
            _AuthorityCase(
                "adaptive policy missing",
                "adaptive policy authority missing",
                _remove_campaign(store._adaptive_policies, adaptive_key),
            ),
            _AuthorityCase(
                "adaptive policy foreign-only",
                "adaptive policy authority missing",
                _relocate_authority(store._adaptive_policies, adaptive_key, keep_local=False),
            ),
            _AuthorityCase(
                "adaptive policy foreign tenant",
                "adaptive policy authority corrupt",
                _swap_model_copy(
                    store._adaptive_policies,
                    adaptive_key,
                    adaptive_policy,
                    (("tenant_id", FOREIGN_TENANT),),
                    adaptive_policy_content_hash,
                ),
            ),
            _AuthorityCase(
                "adaptive policy corrupt",
                "adaptive policy authority corrupt",
                _swap_model_copy(
                    store._adaptive_policies,
                    adaptive_key,
                    adaptive_policy,
                    (("content_hash", "7" * 64),),
                    None,
                ),
            ),
        )
        for case in cases:
            case.apply(store)
            try:
                before = store_fingerprint(store)
                with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                    _derive(store)
                assert excinfo.value.reason == case.expected_reason, case.label
                assert store_fingerprint(store) == before, case.label
            finally:
                store._campaigns[campaign_key] = campaign
                store._worlds[world_key] = world
                store._manifests[world_key] = manifest
                store._campaign_decision_policies[decision_key] = decision_policy
                store._adaptive_policies[adaptive_key] = adaptive_policy
                store._campaigns.pop((FOREIGN_TENANT, CAMPAIGN), None)
                store._worlds.pop((FOREIGN_TENANT, campaign.world_version_id), None)
                store._manifests.pop((FOREIGN_TENANT, campaign.world_version_id), None)
                store._campaign_decision_policies.pop((FOREIGN_TENANT, CAMPAIGN), None)
                store._adaptive_policies.pop((FOREIGN_TENANT, CAMPAIGN), None)
            assert store_fingerprint(store) == pristine, case.label


class TestSeedAndPlanIdentityRejections:
    """Reordered or duplicated campaign seed/plan identity fails closed.

    The campaign is the sole seed-order authority (its ``seed_ensemble``
    is tampered with ``model_copy``, no getter revalidates it) while the
    stored adaptive RunPlan tuple is tampered only through tuple
    replacement, mirroring the single write surface ``put_run_plans``.
    Reordered ensembles, reordered tuples, extra and duplicate-identity
    plans all fail the exact seed-order verifier, a wrong runtime literal
    fails the runtime verifier first, and a duplicated seed identity
    reaches the derivation body where the evidence-inspection guard
    rejects the non-unique seed-major alignment.
    """

    def test_reordered_and_duplicate_seed_plan_identity_fails_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        pristine = store_fingerprint(store)
        campaign_key = (TENANT, CAMPAIGN)
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        plans_key = (TENANT, CAMPAIGN)
        plans = store.get_run_plans(TENANT, CAMPAIGN)

        def swap_campaign(target_store: InMemoryScenarioStore, update: dict[str, Any]) -> None:
            target_store._campaigns[campaign_key] = campaign.model_copy(update=update)

        def swap_plans(target_store: InMemoryScenarioStore, replacement: tuple[Any, ...]) -> None:
            target_store._run_plans[plans_key] = replacement

        cases: tuple[_AuthorityCase, ...] = (
            _AuthorityCase(
                "reordered campaign seed ensemble",
                "stored adaptive plan seed order mismatch",
                lambda target: swap_campaign(
                    target, {"seed_ensemble": tuple(reversed(campaign.seed_ensemble))}
                ),
            ),
            _AuthorityCase(
                "duplicate campaign seed identity",
                "comparison evidence inspection violated its contract",
                lambda target: swap_campaign(
                    target,
                    {
                        "seed_ensemble": (
                            campaign.seed_ensemble[0],
                            campaign.seed_ensemble[0],
                        )
                    },
                ),
            ),
            _AuthorityCase(
                "reordered adaptive plan tuple",
                "stored adaptive plan seed order mismatch",
                lambda target: swap_plans(target, tuple(reversed(plans))),
            ),
            _AuthorityCase(
                "extra adaptive plan appended",
                "stored adaptive plan seed order mismatch",
                lambda target: swap_plans(target, (*plans, plans[-1])),
            ),
            _AuthorityCase(
                "duplicate adaptive plan identity",
                "stored adaptive plan seed order mismatch",
                lambda target: swap_plans(target, (plans[0], plans[0])),
            ),
            _AuthorityCase(
                "wrong-runtime adaptive plan",
                "stored run-plan runtime mismatch",
                lambda target: swap_plans(
                    target,
                    (
                        plans[0].model_copy(update={"runtime_version": "9.9.9"}),
                        plans[1],
                    ),
                ),
            ),
            _AuthorityCase(
                "forged-seed adaptive plan",
                "stored adaptive plan seed order mismatch",
                lambda target: swap_plans(
                    target,
                    (
                        plans[0].model_copy(update={"scenario_seed_id": "seed-1-forged"}),
                        plans[1],
                    ),
                ),
            ),
        )
        for case in cases:
            case.apply(store)
            try:
                before = store_fingerprint(store)
                with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                    _derive(store)
                assert excinfo.value.reason == case.expected_reason, case.label
                assert store_fingerprint(store) == before, case.label
            finally:
                store._campaigns[campaign_key] = campaign
                store._run_plans[plans_key] = plans
            assert store_fingerprint(store) == pristine, case.label


class TestAdaptivePolicyIdentityRejections:
    """Adaptive-policy identity mismatches fail closed at the strict getter.

    The stored policy's identifier is hash-derived from the canonical
    ``(tenant, campaign, scenario, world, policy_id, policy_version,
    schema_version)`` identity payload and its content hash covers the
    complete payload, so every identity-mismatch vector is caught by the
    store getter's independent identity re-verification on read - before
    the comparison layer's own ``adaptive policy authority`` checks - and
    surfaces as exactly ``adaptive policy authority corrupt``. The
    comparison layer independently binds the verified policy into the
    execution chain (``_verify_adaptive_execution_authority`` reads
    ``execution.adaptive_policy_identifier`` / ``policy_id`` /
    ``adaptive_policy_content_hash`` against the policy), so any vector
    that reached the comparison layer would equally fail there; the
    stable narrow reason under the real strict store getters is the
    getter's.
    """

    def test_adaptive_policy_identity_mismatches_fail_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        pristine = store_fingerprint(store)
        adaptive_key = (TENANT, CAMPAIGN)
        adaptive_policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
        forged_identifier = "adaptive-policy-" + "0" * 16
        assert forged_identifier != adaptive_policy.identifier
        rehashed_identifier = adaptive_policy.model_copy(update={"identifier": forged_identifier})
        rehashed_identifier = rehashed_identifier.model_copy(
            update={"content_hash": adaptive_policy_content_hash(rehashed_identifier)}
        )
        rehashed_policy_id = adaptive_policy.model_copy(
            update={"policy_id": f"{adaptive_policy.policy_id}-forged"}
        )
        rehashed_policy_id = rehashed_policy_id.model_copy(
            update={"content_hash": adaptive_policy_content_hash(rehashed_policy_id)}
        )
        cases: tuple[_AuthorityCase, ...] = (
            _AuthorityCase(
                "policy identifier mismatch",
                "adaptive policy authority corrupt",
                lambda target: operator.setitem(
                    target._adaptive_policies, adaptive_key, rehashed_identifier
                ),
            ),
            _AuthorityCase(
                "policy_id mismatch",
                "adaptive policy authority corrupt",
                lambda target: operator.setitem(
                    target._adaptive_policies, adaptive_key, rehashed_policy_id
                ),
            ),
            _AuthorityCase(
                "policy content-hash mismatch",
                "adaptive policy authority corrupt",
                lambda target: operator.setitem(
                    target._adaptive_policies,
                    adaptive_key,
                    adaptive_policy.model_copy(update={"content_hash": "6" * 64}),
                ),
            ),
        )
        for case in cases:
            case.apply(store)
            try:
                before = store_fingerprint(store)
                with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                    _derive(store)
                assert excinfo.value.reason == case.expected_reason, case.label
                assert store_fingerprint(store) == before, case.label
            finally:
                store._adaptive_policies[adaptive_key] = adaptive_policy
            assert store_fingerprint(store) == pristine, case.label


FOREIGN_TENANT_SEED_ID = "seed-1"
MULTI_OBJ = "obj-2"
MULTI_METRIC = "m-2"
_ADDITIVE_UNIFORM = AdditiveUniformObservationNoise(
    kind="additive_uniform",
    lower_bound=-0.5,
    upper_bound=0.5,
    sampler_version="sha256-counter-v1",
    quantization_policy="rational-round-half-even",
    quantization_fraction_bits=64,
    draw_count=1,
)


def _build_multi_objective_env() -> tuple[InMemoryScenarioStore, str]:
    """A real two-objective, draw-free comparison environment.

    Mirrors ``build_comparison_env`` over a scenario with a second bound
    objective (``obj-2``, legitimately declared onto the same metric
    ``m-1`` so the embedded profile carries a duplicate metric binding)
    and the default ``NoObservationNoise`` fixture. This is the
    minimum self-consistent environment for the category 9 vectors:
    with a single objective the reordered decision-policy snapshot equals
    the authoritative order and is rejected before the snapshot
    comparison, so the reordering is only expressible with at least two
    objectives.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario()
    second_objective: Objective = scenario.objectives[0].model_copy(
        update={
            "identifier": MULTI_OBJ,
            "description": "Maximize the secondary metric",
            "direction": ObjectiveDirection.MAXIMIZE,
            "target": 100.0,
            "weight": 1.0,
        }
    )
    scenario = scenario.model_copy(update={"objectives": [*scenario.objectives, second_objective]})
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
        description="X branch",
        guard_values={"level": 5},
        target_values={"level": 84},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-y",
        description="Y branch",
        guard_values={"level": 9},
        target_values={"level": 103},
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=METRIC,
        state_field_id="level",
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=MULTI_METRIC,
        state_field_id="ratio",
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
                    kind="discrete", values=(5, 9), probabilities=(0.5, 0.5)
                ),
                rounding_policy="nearest_ties_to_even",
            ),
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-1",
                state_field_id="ratio",
                distribution=DiscreteDistribution(
                    kind="discrete", values=(1.0, 2.0), probabilities=(0.5, 0.5)
                ),
                rounding_policy=None,
            ),
        ),
        declared_at=DECLARED_AT,
    )
    declare_scenario_evaluation_profile(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=(
            ObjectiveMetricBindingDraft(
                objective_id=OBJ,
                metric_id=METRIC,
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id=MULTI_OBJ,
                metric_id=METRIC,
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
        ),
        declared_at=DECLARED_AT,
        metadata={},
    )
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    world_id = compiled.version.identifier
    store.put_world(compiled.version, compiled.manifest)
    with patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 2):
        prepare_realization_campaign(
            store=store,
            legion=acceptance_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-multi",
            campaign_name="Multi-objective adaptive comparison campaign",
            seed_ensemble=SEEDS,
            created_at=NOW,
        )
    prepare_strategy_trajectory_plans(
        store=store, legion=acceptance_legion(), tenant_id=TENANT, campaign_id="campaign-multi"
    )
    start(store, "campaign-multi")
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-multi")
    for plan in store.get_run_plans(TENANT, "campaign-multi"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=f"run-{plan.identifier}"
        )
    declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-multi",
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="global",
            minimum_target_achievement_probability=0.5,
            minimum_sample_count=1,
            tie_tolerance=0.05,
            all_targeted_objectives_are_hard_gates=False,
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )
    status = store.get_campaign_status(TENANT, "campaign-multi")
    store.update_campaign_status(
        TENANT, "campaign-multi", status.model_copy(update={"state": CampaignState.COMPILED})
    )
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-level",
            external_source=ExternalObservationDraft(
                external_channel_id="channel-1", external_value_kind="integer"
            ),
            timing=ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0),
            noise=NoObservationNoise(kind="none", draw_count=0),
            missing_behavior="false",
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )

    def leaf(cid: str) -> ConditionComparisonLeaf:
        return ConditionComparisonLeaf(
            kind="comparison",
            condition_id=cid,
            observation_id="obs-level",
            observed_value_kind="integer",
            unit=None,
            operator="gt",
            threshold=0,
            missing_behavior="false",
        )

    draft = AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=leaf("c1a"),
                retain_condition=leaf("c1r"),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-2",
                priority=1,
                target_action_id="act-2",
                enter_condition=leaf("c2a"),
                retain_condition=leaf("c2r"),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-multi",
        draft=draft,
        binding_request=AdaptivePolicyBindingRequest(
            policy_id="policy-1",
            policy_version="1.0.0",
            action_mappings=(
                ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-a"),
                ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-b"),
            ),
            bound_at=NOW,
            metadata={},
        ),
    )
    bundle_drafts: dict[str, ExternalObservationInputBundleDraft] = {}
    for seed in SEEDS:
        bundle_draft = ExternalObservationInputBundleDraft(
            entries=(
                ExternalObservationInputValueDraft(
                    observation_id="obs-level", source_step_index=0, value=5
                ),
                ExternalObservationInputValueDraft(
                    observation_id="obs-level", source_step_index=1, value=-3
                ),
            ),
            accepted_at=NOW,
        )
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id="campaign-multi",
            scenario_seed_id=seed.identifier,
            draft=bundle_draft,
        )
        bundle_drafts[seed.identifier] = bundle_draft
    campaign_obj = store.get_campaign(TENANT, "campaign-multi")
    world = store.get_world(TENANT, campaign_obj.world_version_id)
    catalog = extract_world_catalog(world)
    model = store.get_world_uncertainty_model(TENANT, "scenario-1")
    matrix = build_campaign_world_realization_matrix(
        campaign=campaign_obj,
        world=world,
        state_models=catalog.state_models,
        model=model,
    )
    realizations = {r.scenario_seed_id: r for r in matrix.realizations}
    policy = store.get_adaptive_policy(TENANT, "campaign-multi")
    plans = plan_adaptive_runs(
        campaign_id="campaign-multi",
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        policy=policy,
        seeds=campaign_obj.seed_ensemble,
        created_at=campaign_obj.created_at,
        realizations=realizations,
        runtime_version=ADAPTIVE_RUNTIME_VERSION,
    )
    store.put_run_plans(TENANT, "campaign-multi", plans)
    for adaptive_plan in plans:
        adaptive_run_id = run_identifier(adaptive_plan)
        store.put_run_status(
            TENANT,
            adaptive_run_id,
            RunStatus(
                identifier=f"status-{adaptive_run_id}",
                tenant_id=TENANT,
                run_id=adaptive_run_id,
                campaign_id="campaign-multi",
                run_plan_id=adaptive_plan.identifier,
                state=RunState.PLANNED,
                runtime_version=adaptive_plan.runtime_version,
                input_hash=adaptive_plan.input_hash,
                event_hash=None,
                created_at=adaptive_plan.created_at,
                changed_at=adaptive_plan.created_at,
            ),
        )
        result = execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=adaptive_run_id,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=1,
                external_bundle_draft=bundle_drafts[adaptive_plan.scenario_seed_id],
            ),
        )
        assert result.status.state is RunState.COMPLETE, result.status
    return store, world_id


class TestRuntime3ObservationAuthorityRejections:
    """Category 8: missing and corrupt runtime-3 observation authorities.

    The comparison runtime reads each runtime-3 observation set raw from
    the private store seam and strictly revalidates it, so a deleted
    record fails as ``runtime-3 observation authority missing`` and a
    self-consistently rehashed content-hash corruption passes the
    revalidation and fails as ``runtime-3 observation authority corrupt``.
    """

    def test_missing_and_corrupt_observation_sets_fail_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        pristine = store_fingerprint(store)
        plan, _execution, run_id = _static_plan_and_execution(store)
        assert (
            plan.input_hash
            == store.get_realization_run_metric_observation_set(TENANT, run_id).input_hash
        )
        collection = store._realization_run_metric_observation_sets
        key = (TENANT, run_id)
        saved = dict(collection)
        assert key in saved

        # Missing: real private-store absence under the comparison tenant,
        # rebuilt key-order-preserving so the full-store fingerprint (which
        # covers dict repr order) stays comparable.
        collection.clear()
        collection.update({k: v for k, v in saved.items() if k != key})
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                _derive(store)
            assert excinfo.value.reason == "runtime-3 observation authority missing"
            assert store_fingerprint(store) == before
        finally:
            collection.clear()
            collection.update(saved)
        assert store_fingerprint(store) == pristine

        # Corrupt: ``model_copy`` never re-runs contract validators, so a
        # validator-bypassed stored record (here a wrong runtime literal on
        # an otherwise intact set) stays injectable through the private
        # seam and is rejected by exactly the strict revalidation the
        # comparison runtime applies before trusting any observation set.
        # Key order is preserved because the fingerprint covers dict repr
        # order; the getter itself performs no verification, so this is
        # the minimum tamper that reaches the intended verifier.
        bypassed = saved[key].model_copy(update={"runtime_version": "9.9.9"})
        collection.clear()
        collection.update({k: (bypassed if k == key else v) for k, v in saved.items()})
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                _derive(store)
            assert excinfo.value.reason == "runtime-3 observation authority corrupt"
            assert store_fingerprint(store) == before
        finally:
            collection.clear()
            collection.update(saved)
        assert store_fingerprint(store) == pristine


class TestMetricAuthorityRejections:
    """Category 9: profile metric-binding and decision-policy snapshot authority.

    Both vectors run in the dedicated two-objective draw-free environment.
    The ambiguous binding duplicates the single metric across the two
    profile bindings (the profile contract only forbids duplicate
    objective identifiers); the reordered snapshot swaps the stored
    decision policy's objective-weight snapshot order away from the
    authoritative profile binding order, rehashing it so only the exact
    order comparison can catch it.
    """

    def test_ambiguous_metric_binding_fails_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, world_id = _build_multi_objective_env()
        pristine = store_fingerprint(store)
        # The ambiguity is declared through the legitimate profile
        # declaration path (both objectives bound to ``m-1``): the
        # runtime's duplicate-metric check runs on the verified world
        # catalog, and a raw embedded-world mutation can never reach it -
        # world snapshot verification recomputes the profile content hash
        # and cascades into an earlier rejection.
        profile = extract_world_catalog(store.get_world(TENANT, world_id)).evaluation_profile
        assert profile is not None
        assert [binding.metric_id for binding in profile.bindings] == [METRIC, METRIC]
        before = store_fingerprint(store)
        with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
            _multi_derive(store)
        assert excinfo.value.reason == "profile metric binding is ambiguous"
        assert store_fingerprint(store) == before
        assert store_fingerprint(store) == pristine

    def test_reordered_decision_policy_snapshot_fails_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _world_id = _build_multi_objective_env()
        pristine = store_fingerprint(store)
        decision_key = (TENANT, "campaign-multi")
        decision_policy = store.get_campaign_decision_policy(TENANT, "campaign-multi")
        snapshot_ids = [s.objective_id for s in decision_policy.objective_weight_snapshots]
        assert snapshot_ids == [OBJ, MULTI_OBJ]
        reordered = decision_policy.model_copy(
            update={
                "objective_weight_snapshots": tuple(
                    reversed(decision_policy.objective_weight_snapshots)
                )
            }
        )
        reordered = reordered.model_copy(
            update={"content_hash": campaign_decision_policy_content_hash(reordered)}
        )
        store._campaign_decision_policies[decision_key] = reordered
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                _multi_derive(store)
            assert excinfo.value.reason == "decision policy objective snapshot order mismatch"
            assert store_fingerprint(store) == before
        finally:
            store._campaign_decision_policies[decision_key] = decision_policy
        assert store_fingerprint(store) == pristine


class TestObservationNoiseProvenanceRejections:
    """Category 10: real-draw noise provenance and verified no-draw semantics."""

    def test_real_draw_environment_noise_provenance_and_tamper_fail_closed(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = build_comparison_env(
            SEEDS,
            declaration_noise=AdditiveUniformObservationNoise(
                kind="additive_uniform",
                lower_bound=-0.5,
                upper_bound=0.5,
                sampler_version="sha256-counter-v1",
                quantization_policy="rational-round-half-even",
                quantization_fraction_bits=64,
                draw_count=1,
            ),
        )
        pristine = store_fingerprint(store)
        declaration = store.get_runtime_observation_declaration(
            TENANT,
            "scenario-1",
            store.get_campaign(TENANT, CAMPAIGN).world_version_id,
            "obs-level",
        )
        assert declaration.noise == _ADDITIVE_UNIFORM
        evidence = _derive(store)
        summaries = {s.scenario_seed_id: s for s in evidence.noise_summaries}
        assert set(summaries) == {"seed-1", "seed-2"}
        assert all(summary.observed_event_count >= 1 for summary in summaries.values())
        assert all(
            summary.noise_draw_event_count == summary.observed_event_count
            for summary in summaries.values()
        )
        assert all(summary.all_noise_coordinates_verified for summary in summaries.values())
        assert evidence == _derive(store)
        assert store_fingerprint(store) == pristine
        plan, execution, _triple = _adaptive_plan_and_execution(store)
        assert plan.scenario_seed_id == execution.scenario_seed_id
        run_id = f"run-{plan.identifier}"
        assert plan.scenario_seed_id == "seed-1"
        observed_events = [
            event for event in execution.observation_events if event.status == "observed"
        ]
        assert observed_events, "the real-draw environment must produce observed state-field events"
        assert all(event.source_kind == "state_field" for event in observed_events)
        assert all(event.noise_draw_index is not None for event in observed_events)
        assert all(event.applied_noise_value is not None for event in observed_events)
        # Noise-evidence strip against the verified execution: removing one
        # state-field event's ``applied_noise_value``/``noise_draw_index``
        # (self-consistently rehashed at event and aggregate level) is the
        # minimum tamper that survives the strict store getter's detached
        # revalidation - the contract itself forbids value-kind flips whose
        # recorded values are not exact ints - and is caught exactly by the
        # runtime's per-event noise re-verification, which requires a local
        # draw receipt on every observed state-field coordinate.
        tampered_event = observed_events[0].model_copy(
            update={"applied_noise_value": None, "noise_draw_index": None}
        )
        tampered_event = tampered_event.model_copy(
            update={"content_hash": runtime_observation_event_content_hash(tampered_event)}
        )
        tampered_execution = execution.model_copy(
            update={
                "observation_events": tuple(
                    tampered_event if event.identifier == observed_events[0].identifier else event
                    for event in execution.observation_events
                )
            }
        )
        tampered_execution = tampered_execution.model_copy(
            update={
                "content_hash": adaptive_run_trajectory_execution_content_hash(tampered_execution)
            }
        )
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_id)
        original = collection[key]
        collection[key] = tampered_execution
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                _derive(store)
            assert excinfo.value.reason == "adaptive noise provenance receipt mismatch"
            assert store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert store_fingerprint(store) == pristine

    def test_default_no_noise_fixture_has_verified_zero_draw_semantics(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        declaration = store.get_runtime_observation_declaration(
            TENANT,
            "scenario-1",
            store.get_campaign(TENANT, CAMPAIGN).world_version_id,
            "obs-level",
        )
        assert declaration.noise == NoObservationNoise(kind="none", draw_count=0)
        evidence = _derive(store)
        summaries = {s.scenario_seed_id: s for s in evidence.noise_summaries}
        assert set(summaries) == {"seed-1", "seed-2"}
        for summary in summaries.values():
            assert summary.noise_draw_event_count == 0
            assert summary.all_noise_coordinates_verified
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
        executions = [
            store.get_adaptive_run_trajectory_execution(
                tenant_id=TENANT, run_id=f"run-{plan.identifier}"
            )
            for plan in store.get_run_plans(TENANT, CAMPAIGN)
        ]
        for execution in executions:
            assert execution.policy_id == policy.policy_id
            observed = [
                event for event in execution.observation_events if event.status == "observed"
            ]
            external = [event for event in observed if event.source_kind == "external_input"]
            state_field = [event for event in observed if event.source_kind == "state_field"]
            assert all(event.applied_noise_value is None for event in external)
            assert all(event.noise_draw_index is None for event in external)
            assert not state_field, (
                "the default fixture observes through the external bundle only, "
                "so zero draw events are structural, not vacuous"
            )


class TestCampaignSeedAuthorityRejections:
    """Category 11: campaign-side foreign-seed authority, canonical seed-major pairing.

    The existing class already covers reordered campaign seeds, duplicate
    campaign seed identity, reordered/extra/duplicate plan tuples, the
    wrong-runtime plan, and the forged adaptive-plan seed identifier; the
    only missing vector is the foreign-seed substitution in the campaign
    ensemble - the same seed identifier under a foreign tenant, which
    passes every identifier-keyed plan check and is caught by the strict
    adaptive-execution getter's seed-tenant verification.
    """

    def test_foreign_campaign_seed_identity_fails_closed_atomically(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        pristine = store_fingerprint(store)
        campaign_key = (TENANT, CAMPAIGN)
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        foreign_seed = next(
            seed for seed in campaign.seed_ensemble if seed.identifier == FOREIGN_TENANT_SEED_ID
        ).model_copy(update={"tenant_id": FOREIGN_TENANT})
        assert foreign_seed.identifier == FOREIGN_TENANT_SEED_ID
        assert foreign_seed.tenant_id == FOREIGN_TENANT
        substituted = tuple(
            foreign_seed if seed.identifier == FOREIGN_TENANT_SEED_ID else seed
            for seed in campaign.seed_ensemble
        )
        assert [seed.identifier for seed in substituted] == [
            seed.identifier for seed in campaign.seed_ensemble
        ]
        store._campaigns[campaign_key] = campaign.model_copy(update={"seed_ensemble": substituted})
        try:
            before = store_fingerprint(store)
            with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
                _derive(store)
            # The foreign seed never reaches the execution getters: the
            # single authoritative matrix is built first, and its builder
            # deterministically rejects a seed whose tenant differs from
            # the world tenant, so the comparison maps that typed failure
            # to "world realization derivation failed". This is the exact
            # stable landing point of the verifier for this vector.
            assert excinfo.value.reason == "world realization derivation failed"
            assert store_fingerprint(store) == before
        finally:
            store._campaigns[campaign_key] = campaign
        assert store_fingerprint(store) == pristine

    def test_canonical_seed_major_pairing_axis_is_preserved(
        self, happy_env: tuple[InMemoryScenarioStore, str]
    ) -> None:
        store, _ = happy_env
        evidence = _derive(store)
        assert evidence.ordered_seed_ids == ("seed-1", "seed-2")
        assert [receipt.scenario_seed_id for receipt in evidence.seed_alignment_receipts] == [
            "seed-1",
            "seed-1",
            "seed-2",
            "seed-2",
        ]
        assert [summary.scenario_seed_id for summary in evidence.switch_summaries] == [
            "seed-1",
            "seed-2",
        ]
        assert [summary.scenario_seed_id for summary in evidence.noise_summaries] == [
            "seed-1",
            "seed-2",
        ]
        for pair in evidence.objective_pairs:
            assert pair.ordered_seed_ids == evidence.ordered_seed_ids
