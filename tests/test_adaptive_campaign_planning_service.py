"""Adversarial tests for the runtime-4 adaptive campaign planning service (H28-S08B).

Covers the read-only
:func:`~kalhas.application.adaptive_campaign_planning_service.derive_adaptive_campaign_planning_authority`
seam end to end against real stored authority: real compiled worlds with a
declared uncertainty model (and a modelless variant), real prepared COMPILED
campaigns through the real runtime-3 preparation service, real stored strategy
candidates, real prepared trajectory plans, real bound adaptive policies
through the real binding service, and the accepted pure planner
(:func:`~kalhas.application.adaptive_run_planner.plan_adaptive_runs`, H28-S08A).

Proof groups:

- RUNTIME GATE: the exact ``4.0.0`` gate precedes any store read and any
  authority inspection - including when the stored authority would
  independently fail - with the typed unsupported-runtime error.
- SUCCESS / DETERMINISM: exactly ``K`` plans for ``K`` ordered seeds
  (never ``K x S``), the campaign's exact seed order preserved (including a
  reverse-order proof), byte-identical repeated derivations in the same and
  independent environments, equality with the accepted planner's exact
  output, the exact initial-action strategy anchor from the stored policy
  (following a differently bound initial action), exact provenance
  (campaign identity, tenant, world identity/content hash, recorded
  ``created_at``), and the strategy-independent shared realizations
  (exactly one source-level matrix build and one planner call; the matrix
  is byte-identical on rebuild and every plan binds exactly its own seed's
  shared realization digest).
- OBSERVATION-AUTHORITY BOUNDARY: observation-noise derivation is not
  introduced here and the service carries no noise surface; runtime-4
  observation authority remains with the established declaration records.
- ATOMIC TYPED REJECTIONS (zero writes): missing/foreign campaign,
  status-not-COMPILED, missing scenario, missing/corrupt world, missing
  manifest, missing/reordered/extra/duplicated/foreign candidates,
  reordered/missing trajectory-plan collection, missing/corrupt/
  disagreeing policy (campaign/world/runtime mismatch), stored/embedded
  uncertainty-model mismatch, stored-model-without-embedded-model,
  missing stored model, corrupt stored model, tampered/foreign campaign
  seeds (rejected through the independent stored runtime-3 plan-matrix
  authority), and missing/mixed-runtime/tampered stored runtime-3 plan
  matrices - every failure typed and write-free over a complete
  store-surface fingerprint.
- PURITY: no store write/update/delete, no LEGION/NEXUS, no execution,
  replay, policy evaluation, RNG, clock, network/provider, callback,
  dynamic import, ``eval``, or ``exec`` surface; input and stored
  authority immutability with repeated derivations equal yet detached
  (mutating a returned plan alters no stored authority, no separately
  derived tuple, and no fresh later derivation); the exact minimal
  ``__all__`` and signature; no runtime-1/2/3 literals; and all 90
  pre-existing dirty paths (both H28-S08A files included) byte-identical
  to the preflight ledger.

No mocks, monkeypatch, skip, xfail, noqa, type-ignore, weakened
assertions, invented outputs, real company or personal data, or live
effects are used anywhere in this module.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application import adaptive_campaign_planning_service as service_module
from kalhas.application.adaptive_campaign_planning_service import (
    RUNTIME_VERSION,
    derive_adaptive_campaign_planning_authority,
)
from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_run_planner import adaptive_run_input_hash, plan_adaptive_runs
from kalhas.application.domain_errors import KalhasDomainError, UnsupportedRuntimeVersionError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
)
from kalhas.application.world_uncertainty_errors import WorldUncertaintyModelIntegrityError
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import (
    ObservationRequirement,
    PolicyDeclaration,
    PolicyRule,
)

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed
from tests.phase20_helpers import DECLARED_AT
from tests.phase24_helpers import build_uncertainty_store, declare_model
from tests.phase25_helpers import level_binding
from tests.test_adaptive_run_execution_builder import _new_store_with_world

SERVICE_PATH = Path(service_module.__file__).resolve()
OTHER_TENANT = "tenant-99"
CAMPAIGN_ID = "campaign-1"

#: The default typed planning-authority failure; every rejection proof
#: asserts the type and an internal reason, mirroring the established
#: atomicity idiom.
SERVICE_ERROR = AdaptivePolicyBindingValidationError

TWO_SEEDS: tuple[ScenarioSeed, ...] = (
    build_seed(identifier="seed-1"),
    build_seed(identifier="seed-2"),
)
FOUR_SEEDS: tuple[ScenarioSeed, ...] = tuple(
    build_seed(identifier=f"seed-{index}") for index in range(4)
)


# --------------------------------------------------------------------------- #
# Real end-to-end environment builders. Every record passes its real store
# verification; the only private seams are deliberate corruption injections
# in the rejection proofs, exactly as the established store-test idiom uses.
# --------------------------------------------------------------------------- #


def _candidate(identifier: str, tenant_id: str, observations: list[ObservationRequirement]) -> Any:
    from kalhas.contracts.v1.strategy import StrategyCandidate

    return StrategyCandidate(
        identifier=identifier,
        tenant_id=tenant_id,
        strategy_version="1.0.0",
        policy=PolicyDeclaration(
            summary=f"Declared mock policy: {identifier}",
            rules=[
                PolicyRule(
                    identifier=f"{identifier}-rule-1",
                    statement="Declared mock rule",
                    parameters={"aggressiveness": 0.5},
                )
            ],
        ),
        required_observations=observations,
        assumptions=[],
    )


def _policy_draft(initial_action_id: str = "act-1") -> Any:
    from kalhas.contracts.v1.adaptive_policy import (
        AdaptivePolicyDraft,
        AdaptivePolicyRuleDraft,
        ConditionComparisonLeaf,
    )

    fallback_action_id = "act-2" if initial_action_id == "act-1" else "act-1"

    def leaf(condition_id: str, observation_id: str, threshold: int) -> ConditionComparisonLeaf:
        return ConditionComparisonLeaf(
            kind="comparison",
            condition_id=condition_id,
            observation_id=observation_id,
            observed_value_kind="integer",
            unit=None,
            operator="gt",
            threshold=threshold,
            missing_behavior="false",
        )

    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id=initial_action_id,
        fallback_action_id=fallback_action_id,
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=leaf("c1a", "obs-level", 0),
                retain_condition=leaf("c1r", "obs-level", 0),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-2",
                priority=1,
                target_action_id="act-2",
                enter_condition=leaf("c2a", "obs-level", -1000),
                retain_condition=leaf("c2r", "obs-level", -1000),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _binding_request() -> AdaptivePolicyBindingRequest:
    return AdaptivePolicyBindingRequest(
        policy_id="policy-1",
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=NOW,
        metadata={},
    )


def _declare_level_observation(store: InMemoryScenarioStore, world_id: str) -> None:
    """Declare the policy's single bound runtime observation through the real seam."""
    from kalhas.application.runtime_observation_declaration_service import (
        ExternalObservationDraft,
        RuntimeObservationDeclarationDraft,
        declare_runtime_observation_declaration,
    )
    from kalhas.contracts.v1.runtime_observation import NoObservationNoise, ObservationTiming

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


def _build_env(
    *,
    seeds: tuple[ScenarioSeed, ...] = TWO_SEEDS,
    campaign_id: str = CAMPAIGN_ID,
    with_model: bool = True,
    initial_action_id: str = "act-1",
) -> InMemoryScenarioStore:
    """A real COMPILED campaign with candidates, plans, and a bound policy.

    The world is the established, execution-builder-validated fixture
    (``tests.test_adaptive_run_execution_builder._new_store_with_world``):
    real state models ``sm-a``/``sm-b``, two ``t-1`` transitions, and the
    embedded uncertainty model on ``sm-b.weight``, declared through the
    real Phase 24 seam before compilation. The runtime-3 preparation
    service writes the real COMPILED campaign; the trajectory-plan
    service writes the real candidate-major plan collection (ten plans
    for five candidates across two state models); and the real binding
    service writes the immutable runtime-4 policy with
    ``initial_action_id`` as the stored initial action (``act-1`` ->
    ``mock-baseline``, ``act-2`` -> ``mock-balanced``).

    With ``with_model=False`` the fixture's stored declaration is
    removed through the established private seam and the world is
    recompiled modelless through the real mock-NEXUS compilation seam,
    so the compiled world embeds no uncertainty model and the stored
    declaration is absent.
    """
    store, world_id = _new_store_with_world()
    if not with_model:
        del store._world_uncertainty_models[(TENANT, "scenario-1")]
        modelless = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        store.put_world(modelless.version, modelless.manifest)
        world_id = modelless.version.identifier
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=world_id,
        strategy_request=build_request(TENANT),
        campaign_id=campaign_id,
        campaign_name="Adaptive planning authority campaign",
        seed_ensemble=seeds,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id=campaign_id
    )
    _declare_level_observation(store, world_id)
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_policy_draft(initial_action_id),
        binding_request=_binding_request(),
    )
    return store


def _policy_anchor(policy: AdaptivePolicyLike) -> str:
    """The initial-action strategy anchor of a bound policy."""
    anchor: str = next(
        action.strategy_candidate_id
        for action in policy.actions
        if action.action_id == policy.initial_action_id
    )
    return anchor


AdaptivePolicyLike = Any


# --------------------------------------------------------------------------- #
# Store-surface fingerprint for atomicity proofs (the established idiom).
# --------------------------------------------------------------------------- #


def _surface(store: InMemoryScenarioStore, campaign_id: str) -> dict[str, Any]:
    """A deep serializable fingerprint of every store surface the service
    could touch. Missing authority records are fingerprinted as ``None``
    or ``()`` so rejection proofs can compare byte-identical surfaces
    before and after a failed call."""
    try:
        policy_dump: Any = store.get_adaptive_policy(TENANT, campaign_id).model_dump(mode="json")
    except KalhasDomainError:
        policy_dump = None
    try:
        plans_dump: Any = tuple(
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, campaign_id)
        )
    except KalhasDomainError:
        plans_dump = ()
    try:
        candidates_dump: Any = tuple(
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, campaign_id)
        )
    except KalhasDomainError:
        candidates_dump = ()
    try:
        world_id = store.get_campaign(TENANT, campaign_id).world_version_id
        world_dump: Any = store.get_world(TENANT, world_id).model_dump(mode="json")
        manifest_dump: Any = store.get_manifest(TENANT, world_id).model_dump(mode="json")
    except KalhasDomainError:
        world_dump = None
        manifest_dump = None
    return {
        "campaigns": tuple(
            campaign.model_dump(mode="json") for campaign in store._campaigns.values()
        ),
        "campaign_statuses": tuple(
            status.model_dump(mode="json") for status in store._campaign_statuses.values()
        ),
        "run_plans": tuple(
            tuple(plan.model_dump(mode="json") for plan in plans)
            for plans in store._run_plans.values()
        ),
        "run_statuses": tuple(
            status.model_dump(mode="json") for status in store._run_statuses.values()
        ),
        "strategy_candidates": tuple(
            tuple(candidate.model_dump(mode="json") for candidate in candidates)
            for candidates in store._strategy_candidates.values()
        ),
        "trajectory_plans": tuple(
            tuple(plan.model_dump(mode="json") for plan in plans)
            for plans in store._strategy_trajectory_plans.values()
        ),
        "adaptive_policies": tuple(
            stored.model_dump(mode="json") for stored in store._adaptive_policies.values()
        ),
        "worlds": tuple(world.model_dump(mode="json") for world in store._worlds.values()),
        "manifests": tuple(
            manifest.model_dump(mode="json") for manifest in store._manifests.values()
        ),
        "uncertainty": tuple(
            model.model_dump(mode="json") for model in store._world_uncertainty_models.values()
        ),
        "declarations": tuple(
            declaration.model_dump(mode="json")
            for declaration in store._runtime_observation_declarations.values()
        ),
        "activity": tuple(
            event.model_dump(mode="json") for event in store.list_operational_activity(TENANT)
        ),
        "policy": policy_dump,
        "plans": plans_dump,
        "candidates": candidates_dump,
        "world": world_dump,
        "manifest": manifest_dump,
    }


def _assert_atomic_rejection(
    store: InMemoryScenarioStore,
    campaign_id: str,
    *,
    tenant_id: str = TENANT,
    runtime_version: str = RUNTIME_VERSION,
    expected: type[BaseException] | tuple[type[BaseException], ...] = SERVICE_ERROR,
) -> pytest.ExceptionInfo[Any]:
    """Derive once, require the typed error, prove the complete store
    surface (authorities, activity, statuses) is byte-identical."""
    before = _surface(store, campaign_id)
    with pytest.raises(expected) as excinfo:
        derive_adaptive_campaign_planning_authority(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            runtime_version=runtime_version,
        )
    assert _surface(store, campaign_id) == before
    assert isinstance(excinfo.value, KalhasDomainError)
    reason = getattr(excinfo.value, "reason", None)
    if isinstance(excinfo.value, AdaptivePolicyBindingValidationError):
        assert reason is not None
    return excinfo


def _matrix_of(store: InMemoryScenarioStore, campaign_id: str) -> Any:
    """The campaign realization matrix rebuilt from stored authority."""
    campaign = store.get_campaign(TENANT, campaign_id)
    world = store.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
    return build_campaign_world_realization_matrix(
        campaign=campaign,
        world=world,
        state_models=catalog.state_models,
        model=stored,
    )


def _expected_plans(store: InMemoryScenarioStore, campaign_id: str) -> tuple[RunPlan, ...]:
    """The accepted planner's exact output over the stored authority."""
    campaign = store.get_campaign(TENANT, campaign_id)
    world = store.get_world(TENANT, campaign.world_version_id)
    policy = store.get_adaptive_policy(TENANT, campaign_id)
    matrix = _matrix_of(store, campaign_id)
    realizations = {
        realization.scenario_seed_id: realization for realization in matrix.realizations
    }
    return plan_adaptive_runs(
        campaign_id=campaign.identifier,
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        policy=policy,
        seeds=campaign.seed_ensemble,
        created_at=campaign.created_at,
        realizations=realizations,
        runtime_version=RUNTIME_VERSION,
    )


# --------------------------------------------------------------------------- #
# Runtime gate.
# --------------------------------------------------------------------------- #


class TestRuntimeGate:
    def test_exact_runtime_literal(self) -> None:
        assert RUNTIME_VERSION == "4.0.0"
        assert service_module.RUNTIME_VERSION == "4.0.0"

    def test_every_non_4_value_rejected_before_any_effect(self) -> None:
        env = _build_env()
        before = _surface(env, CAMPAIGN_ID)
        for runtime in ("", "1.0.0", "2.0.0", "3.0.0", "4.0.1", "5.0.0", "4", "v4.0.0"):
            with pytest.raises(UnsupportedRuntimeVersionError) as excinfo:
                derive_adaptive_campaign_planning_authority(
                    env,
                    tenant_id=TENANT,
                    campaign_id=CAMPAIGN_ID,
                    runtime_version=runtime,
                )
            assert excinfo.value.runtime_version == runtime
        assert _surface(env, CAMPAIGN_ID) == before

    def test_gate_precedes_authority_inspection_on_contradictory_store(self) -> None:
        # A campaign whose status is NOT COMPILED would fail authority
        # verification; a wrong runtime must surface the gate first.
        env = _build_env()
        status = env.get_campaign_status(TENANT, CAMPAIGN_ID)
        env.update_campaign_status(
            TENANT, CAMPAIGN_ID, status.model_copy(update={"state": CampaignState.RUNNING})
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            derive_adaptive_campaign_planning_authority(
                env,
                tenant_id=TENANT,
                campaign_id=CAMPAIGN_ID,
                runtime_version="3.0.0",
            )
        with pytest.raises(AdaptivePolicyBindingValidationError):
            derive_adaptive_campaign_planning_authority(
                env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            )

    def test_gate_is_the_first_statement_of_the_derivation_path(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "derive_adaptive_campaign_planning_authority"
        )
        try_node = next(node for node in function.body if isinstance(node, ast.Try))
        first_statement = try_node.body[0]
        assert isinstance(first_statement, ast.If)
        names = {node.id for node in ast.walk(first_statement.test) if isinstance(node, ast.Name)}
        assert "runtime_version" in names
        assert "RUNTIME_VERSION" in names
        # No store call precedes the gate: the gate is the try body's
        # first statement and the raise carries the unsupported-runtime
        # error, so no authority can be inspected before it.
        assert first_statement.body and isinstance(first_statement.body[0], ast.Raise)


# --------------------------------------------------------------------------- #
# Success, determinism, cardinality, order, anchor, provenance.
# --------------------------------------------------------------------------- #


class TestDerivationSuccessAndDeterminism:
    def test_exactly_k_plans_for_k_ordered_seeds(self) -> None:
        env = _build_env()
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        assert len(plans) == len(campaign.seed_ensemble) == 2

    def test_exactly_four_plans_for_four_seeds_never_k_times_s(self) -> None:
        env = _build_env(seeds=FOUR_SEEDS)
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        candidates = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        assert len(plans) == 4
        assert len(candidates) == 5
        assert len(plans) != 4 * 5

    def test_campaign_seed_order_is_preserved_exactly(self) -> None:
        env = _build_env()
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        assert [plan.scenario_seed_id for plan in plans] == [
            seed.identifier for seed in campaign.seed_ensemble
        ]

    def test_reversed_campaign_order_reverses_plan_order(self) -> None:
        forward_env = _build_env()
        reverse_env = _build_env(seeds=tuple(reversed(TWO_SEEDS)))
        forward = derive_adaptive_campaign_planning_authority(
            forward_env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        reverse = derive_adaptive_campaign_planning_authority(
            reverse_env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert [plan.scenario_seed_id for plan in forward] == ["seed-1", "seed-2"]
        assert [plan.scenario_seed_id for plan in reverse] == ["seed-2", "seed-1"]
        assert {plan.identifier for plan in forward} == {plan.identifier for plan in reverse}

    def test_repeated_derivation_is_byte_identical(self) -> None:
        env = _build_env()
        first = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        second = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert first == second
        assert [plan.model_dump_json() for plan in first] == [
            plan.model_dump_json() for plan in second
        ]

    def test_independent_identical_environments_are_byte_identical(self) -> None:
        first = derive_adaptive_campaign_planning_authority(
            _build_env(), tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        second = derive_adaptive_campaign_planning_authority(
            _build_env(), tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert [plan.model_dump_json() for plan in first] == [
            plan.model_dump_json() for plan in second
        ]

    def test_equals_the_accepted_planners_exact_output(self) -> None:
        env = _build_env()
        derived = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert derived == _expected_plans(env, CAMPAIGN_ID)
        assert all(isinstance(plan, RunPlan) for plan in derived)

    def test_exact_provenance_fields_from_recorded_authority(self) -> None:
        env = _build_env()
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        world = env.get_world(TENANT, campaign.world_version_id)
        policy = env.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        anchor = _policy_anchor(policy)
        from kalhas.application.run_planner import run_plan_identifier

        for plan in plans:
            assert plan.tenant_id == TENANT
            assert plan.campaign_id == CAMPAIGN_ID
            assert plan.world_version_id == world.identifier
            assert plan.runtime_version == RUNTIME_VERSION
            assert plan.created_at == campaign.created_at
            assert plan.strategy_candidate_id == anchor
            assert plan.identifier == run_plan_identifier(
                campaign_id=CAMPAIGN_ID,
                world_version_id=world.identifier,
                strategy_candidate_id=anchor,
                scenario_seed_id=plan.scenario_seed_id,
                runtime_version=RUNTIME_VERSION,
            )


class TestInitialActionStrategyAnchor:
    def test_anchor_is_the_stored_policy_initial_action_strategy(self) -> None:
        env = _build_env()
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        policy = env.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        assert _policy_anchor(policy) == "mock-baseline"
        assert {plan.strategy_candidate_id for plan in plans} == {"mock-baseline"}

    def test_anchor_follows_the_stored_policy_initial_action(self) -> None:
        # A second real environment whose stored policy binds a different
        # initial action must anchor the other strategy; the anchor is a
        # property of recorded authority, never of the caller.
        default_env = _build_env()
        swapped_env = _build_env(initial_action_id="act-2")
        default_policy = default_env.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        swapped_policy = swapped_env.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        assert default_policy.initial_action_id == "act-1"
        assert swapped_policy.initial_action_id == "act-2"
        default_plans = derive_adaptive_campaign_planning_authority(
            default_env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        swapped_plans = derive_adaptive_campaign_planning_authority(
            swapped_env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert {plan.strategy_candidate_id for plan in default_plans} == {"mock-baseline"}
        assert {plan.strategy_candidate_id for plan in swapped_plans} == {"mock-balanced"}
        # The anchor participates in the collision-safe plan identifier:
        # different stored anchors produce different plan identifiers.
        assert {plan.identifier for plan in default_plans}.isdisjoint(
            {plan.identifier for plan in swapped_plans}
        )


class TestStrategyIndependentRealizations:
    def test_one_source_level_matrix_build_and_one_planner_call(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        matrix_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_campaign_world_realization_matrix"
        ]
        planner_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "plan_adaptive_runs"
        ]
        assert len(matrix_calls) == 1
        assert len(planner_calls) == 1

    def test_matrix_rebuild_is_byte_identical_and_strategy_absent(self) -> None:
        env = _build_env(seeds=FOUR_SEEDS)
        matrix_first = _matrix_of(env, CAMPAIGN_ID)
        matrix_second = _matrix_of(env, CAMPAIGN_ID)
        assert matrix_first == matrix_second
        assert matrix_first.model_dump_json() == matrix_second.model_dump_json()
        assert len(matrix_first.realizations) == 4
        # Strategy identifiers appear nowhere in the realization matrix.
        assert "strategy_candidate" not in matrix_first.model_dump_json()

    def test_every_plan_binds_its_own_seed_shared_realization(self) -> None:
        env = _build_env(seeds=FOUR_SEEDS)
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        world = env.get_world(TENANT, campaign.world_version_id)
        policy = env.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        plans = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        by_seed = {
            realization.scenario_seed_id: realization
            for realization in _matrix_of(env, CAMPAIGN_ID).realizations
        }
        # Two compared policy actions over two strategies, yet exactly
        # one plan per seed: branching is structurally absent from the
        # realization path, and each plan binds exactly its own seed's
        # shared realization digest through the accepted input hash.
        assert len(policy.actions) == 2
        assert len(plans) == 4
        for plan in plans:
            seed = next(s for s in campaign.seed_ensemble if s.identifier == plan.scenario_seed_id)
            realization = by_seed[plan.scenario_seed_id]
            assert plan.input_hash == adaptive_run_input_hash(
                runtime_version=RUNTIME_VERSION,
                world_content_hash=world.content_hash,
                policy=policy,
                seed=seed,
                world_realization_content_hash=realization.content_hash,
            )
        hashes = {realization.content_hash for realization in by_seed.values()}
        assert len(hashes) == 4


class TestObservationNoiseBoundary:
    def test_service_introduces_no_observation_noise_surface(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        for marker in (
            "observation_noise",
            "noise_draw",
            "kalhas-observation-noise",
            "draw_index",
            "sample_observation",
        ):
            assert marker not in source
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("runtime_observation" in module for module in imported)

    def test_runtime_observation_authority_stays_with_the_declarations(self) -> None:
        env = _build_env()
        world_id = env.get_campaign(TENANT, CAMPAIGN_ID).world_version_id
        declaration = env.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, "obs-level"
        )
        assert declaration.runtime_version == "4.0.0"
        # The derivation neither consumes nor alters the declaration.
        before = declaration.model_dump(mode="json")
        derive_adaptive_campaign_planning_authority(env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID)
        assert (
            env.get_runtime_observation_declaration(
                TENANT, "scenario-1", world_id, "obs-level"
            ).model_dump(mode="json")
            == before
        )


# --------------------------------------------------------------------------- #
# Atomic typed rejections (zero writes).
# --------------------------------------------------------------------------- #


class TestCampaignAuthorityRejections:
    def test_missing_campaign_rejected_atomically(self) -> None:
        env = _build_env()
        _assert_atomic_rejection(env, "campaign-absent")

    def test_foreign_tenant_campaign_rejected_atomically(self) -> None:
        env = _build_env()
        _assert_atomic_rejection(env, CAMPAIGN_ID, tenant_id=OTHER_TENANT)

    def test_non_compiled_status_rejected_atomically(self) -> None:
        env = _build_env()
        status = env.get_campaign_status(TENANT, CAMPAIGN_ID)
        recorded = status.model_dump(mode="json")
        for state in (CampaignState.DRAFT, CampaignState.RUNNING, CampaignState.COMPLETE):
            env.update_campaign_status(
                TENANT, CAMPAIGN_ID, status.model_copy(update={"state": state})
            )
            _assert_atomic_rejection(env, CAMPAIGN_ID)
        env.update_campaign_status(TENANT, CAMPAIGN_ID, status)
        assert env.get_campaign_status(TENANT, CAMPAIGN_ID).model_dump(mode="json") == recorded

    def test_missing_scenario_rejected_atomically(self) -> None:
        env = _build_env()
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        env._campaigns[(TENANT, CAMPAIGN_ID)] = campaign.model_copy(
            update={"scenario_id": "scenario-foreign"}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestWorldAndManifestAuthorityRejections:
    def test_missing_world_rejected_atomically(self) -> None:
        env = _build_env()
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        env._campaigns[(TENANT, CAMPAIGN_ID)] = campaign.model_copy(
            update={"world_version_id": "world-absent"}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_corrupt_world_snapshot_rejected_atomically(self) -> None:
        env = _build_env()
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        world = env.get_world(TENANT, campaign.world_version_id)
        env._worlds[(TENANT, campaign.world_version_id)] = world.model_copy(
            update={"content_hash": "f" * 64}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_missing_manifest_rejected_atomically(self) -> None:
        env = _build_env()
        world_id = env.get_campaign(TENANT, CAMPAIGN_ID).world_version_id
        del env._manifests[(TENANT, world_id)]
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestCandidateAuthorityRejections:
    def test_missing_candidates_rejected_atomically(self) -> None:
        env = _build_env()
        del env._strategy_candidates[(TENANT, CAMPAIGN_ID)]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_reordered_candidates_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        env._strategy_candidates[(TENANT, CAMPAIGN_ID)] = tuple(reversed(stored))
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_missing_single_candidate_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        env._strategy_candidates[(TENANT, CAMPAIGN_ID)] = stored[:-1]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_extra_candidate_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        env._strategy_candidates[(TENANT, CAMPAIGN_ID)] = stored + (
            _candidate("mock-extra", TENANT, []),
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_duplicated_candidate_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        env._strategy_candidates[(TENANT, CAMPAIGN_ID)] = stored + (stored[0],)
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_foreign_candidate_tenant_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        foreign_identifier = stored[0].identifier
        env._strategy_candidates[(TENANT, CAMPAIGN_ID)] = tuple(
            candidate.model_copy(update={"tenant_id": OTHER_TENANT})
            if candidate.identifier == foreign_identifier
            else candidate
            for candidate in stored
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestTrajectoryPlanOrderRejections:
    def test_reordered_trajectory_plan_order_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env.get_strategy_trajectory_plans(TENANT, CAMPAIGN_ID)
        first_strategy = stored[0].strategy_candidate_id
        first_group = tuple(plan for plan in stored if plan.strategy_candidate_id == first_strategy)
        rest = tuple(plan for plan in stored if plan.strategy_candidate_id != first_strategy)
        env._strategy_trajectory_plans[(TENANT, CAMPAIGN_ID)] = rest + first_group
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_missing_trajectory_plan_collection_rejected_atomically(self) -> None:
        env = _build_env()
        del env._strategy_trajectory_plans[(TENANT, CAMPAIGN_ID)]
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestPolicyAuthorityRejections:
    def test_missing_policy_rejected_atomically(self) -> None:
        env = _build_env()
        del env._adaptive_policies[(TENANT, CAMPAIGN_ID)]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_corrupt_policy_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._adaptive_policies[(TENANT, CAMPAIGN_ID)]
        env._adaptive_policies[(TENANT, CAMPAIGN_ID)] = stored.model_copy(
            update={"content_hash": "e" * 64}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_policy_campaign_disagreement_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._adaptive_policies[(TENANT, CAMPAIGN_ID)]
        env._adaptive_policies[(TENANT, CAMPAIGN_ID)] = stored.model_copy(
            update={"campaign_id": "campaign-other"}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_policy_world_hash_disagreement_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._adaptive_policies[(TENANT, CAMPAIGN_ID)]
        env._adaptive_policies[(TENANT, CAMPAIGN_ID)] = stored.model_copy(
            update={"world_content_hash": "d" * 64}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_policy_runtime_disagreement_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._adaptive_policies[(TENANT, CAMPAIGN_ID)]
        env._adaptive_policies[(TENANT, CAMPAIGN_ID)] = stored.model_copy(
            update={"runtime_version": "9.9.9"}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestUncertaintyAuthorityRejections:
    def test_missing_stored_model_with_embedded_model_rejected_atomically(self) -> None:
        env = _build_env()
        del env._world_uncertainty_models[(TENANT, "scenario-1")]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_stored_model_disagreeing_with_embedded_model_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._world_uncertainty_models[(TENANT, "scenario-1")]
        env._world_uncertainty_models[(TENANT, "scenario-1")] = stored.model_copy(
            update={"declared_at": datetime(2020, 1, 1, tzinfo=UTC)}
        )
        # Either the deterministic identity verification or the exact
        # stored-vs-embedded JSON comparison fails closed.
        _assert_atomic_rejection(
            env,
            CAMPAIGN_ID,
            expected=(WorldUncertaintyModelIntegrityError, AdaptivePolicyBindingValidationError),
        )

    def test_stored_model_without_embedded_model_rejected_atomically(self) -> None:
        env = _build_env(with_model=False)
        # The modelless compiled world embeds no model, so a stored
        # declaration is contradictory authority. The parallel model is
        # declared through the real Phase 24 seam on a fresh, uncompiled
        # store (the declaration seam forbids post-compilation
        # declarations) and injected through the private corruption seam.
        parallel = build_uncertainty_store()
        model = declare_model(parallel, bindings=(level_binding(),))
        env._world_uncertainty_models[(TENANT, "scenario-1")] = model
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_corrupt_stored_model_rejected_atomically(self) -> None:
        env = _build_env()
        stored = env._world_uncertainty_models[(TENANT, "scenario-1")]
        env._world_uncertainty_models[(TENANT, "scenario-1")] = stored.model_copy(
            update={"content_hash": "c" * 64}
        )
        _assert_atomic_rejection(
            env,
            CAMPAIGN_ID,
            expected=(WorldUncertaintyModelIntegrityError, AdaptivePolicyBindingValidationError),
        )


class TestRealizationAuthorityRejections:
    def test_tampered_campaign_seed_rejected_atomically(self) -> None:
        # A recorded seed whose authority (seed_value) differs from the
        # seed content used when the campaign was prepared disagrees with
        # the independent stored runtime-3 plan matrix (whose input hashes
        # digest the original seed content): tampered, atomic, zero writes.
        env = _build_env()
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        altered_seed = campaign.seed_ensemble[0].model_copy(update={"seed_value": "v2"})
        env._campaigns[(TENANT, CAMPAIGN_ID)] = campaign.model_copy(
            update={"seed_ensemble": (altered_seed,) + campaign.seed_ensemble[1:]}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_foreign_campaign_seed_rejected_atomically(self) -> None:
        env = _build_env()
        campaign = env.get_campaign(TENANT, CAMPAIGN_ID)
        foreign_seed = campaign.seed_ensemble[0].model_copy(update={"tenant_id": OTHER_TENANT})
        env._campaigns[(TENANT, CAMPAIGN_ID)] = campaign.model_copy(
            update={"seed_ensemble": (foreign_seed,) + campaign.seed_ensemble[1:]}
        )
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestStoredRuntime3AuthorityRejections:
    """The stored runtime-3 plan matrix is the independent seed authority.

    Every corruption below is injected through the established private
    seam after a real preparation, and every rejection is proven typed
    and write-free over the complete store-surface fingerprint by
    :func:`_assert_atomic_rejection`.
    """

    def test_stored_runtime3_plan_matrix_missing_rejected_atomically(self) -> None:
        env = _build_env()
        del env._run_plans[(TENANT, CAMPAIGN_ID)]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_stored_runtime3_plan_matrix_reordered_by_seed_rejected_atomically(self) -> None:
        env = _build_env()
        plans = env.get_run_plans(TENANT, CAMPAIGN_ID)
        assert len(plans) >= 2
        env._run_plans[(TENANT, CAMPAIGN_ID)] = (plans[1], plans[0]) + plans[2:]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_stored_runtime3_plan_matrix_tampered_input_hash_rejected_atomically(self) -> None:
        env = _build_env()
        plans = env.get_run_plans(TENANT, CAMPAIGN_ID)
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        env._run_plans[(TENANT, CAMPAIGN_ID)] = (tampered,) + plans[1:]
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_stored_runtime3_plan_matrix_extra_plan_rejected_atomically(self) -> None:
        env = _build_env()
        plans = env.get_run_plans(TENANT, CAMPAIGN_ID)
        extra = plans[-1].model_copy(update={"identifier": "plan-extra"})
        env._run_plans[(TENANT, CAMPAIGN_ID)] = plans + (extra,)
        _assert_atomic_rejection(env, CAMPAIGN_ID)

    def test_stored_runtime3_plan_matrix_mixed_runtime_rejected_atomically(self) -> None:
        env = _build_env()
        plans = env.get_run_plans(TENANT, CAMPAIGN_ID)
        foreign_runtime = plans[-1].model_copy(update={"runtime_version": "2.0.0"})
        env._run_plans[(TENANT, CAMPAIGN_ID)] = plans[:-1] + (foreign_runtime,)
        _assert_atomic_rejection(env, CAMPAIGN_ID)


class TestInvalidCallerInputs:
    def test_non_string_identifiers_rejected_atomically(self) -> None:
        env = _build_env()
        before = _surface(env, CAMPAIGN_ID)
        for tenant_value, campaign_value in (
            (123, CAMPAIGN_ID),
            (TENANT, 456),
            ("", ""),
            (None, None),
        ):
            with pytest.raises(SERVICE_ERROR):
                derive_adaptive_campaign_planning_authority(
                    env,
                    tenant_id=tenant_value,  # type: ignore[arg-type]
                    campaign_id=campaign_value,  # type: ignore[arg-type]
                )
        assert _surface(env, CAMPAIGN_ID) == before


# --------------------------------------------------------------------------- #
# Purity, boundaries, and the protected baseline.
# --------------------------------------------------------------------------- #


class TestPurityAndBoundaries:
    def test_no_forbidden_store_write_surface_or_adapters(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not (
            attributes
            & {
                "put_run_events",
                "put_input_integrity_manifest",
                "put_replay_manifest",
                "record_operational_activity",
                "update_campaign_status",
                "put_adaptive_run_trajectory_replay_manifest",
                "put_world",
                "put_campaign",
                "put_run_plans",
                "put_run_status",
                "put_scenario",
                "put_manifest",
                "put_strategy_candidates",
                "put_strategy_trajectory_plans",
                "put_adaptive_policy",
                "put_run_trajectory_execution",
                "put_adaptive_run_trajectory_execution",
                "put_world_uncertainty_model",
                "put_runtime_observation_declaration",
                "put_external_observation_input_bundle",
                "put_domain_state_transition",
                "put_domain_state_model",
                "delete",
                "upsert",
                "clear",
            }
        )
        lowered = source.lower()
        assert "legionadapter" not in lowered
        assert "nexusadapter" not in lowered

    def test_no_clock_random_network_filesystem_or_dynamic_import(self) -> None:
        tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        assert roots <= {"__future__", "typing", "kalhas"}
        forbidden = {
            "datetime",
            "time",
            "random",
            "uuid",
            "os",
            "sys",
            "socket",
            "urllib",
            "requests",
            "subprocess",
            "hashlib",
            "pathlib",
            "json",
            "importlib",
        }
        assert not (roots & forbidden)
        name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not (
            name_ids
            & {"datetime", "time", "uuid", "random", "now", "utcnow", "monotonic", "time_ns"}
        )
        call_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    call_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    call_names.add(func.attr)
        assert not (call_names & {"eval", "exec", "compile", "__import__", "open", "input"})

    def test_derivation_preserves_all_authority_and_results_are_detached(self) -> None:
        # Honest detachment proof (the v1 RunPlan contract is deliberately
        # not frozen): repeated derivations are equal, and mutating one
        # returned plan object alters no stored authority, no separately
        # derived tuple, and no fresh later derivation.
        env = _build_env()
        before = _surface(env, CAMPAIGN_ID)
        first = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        second = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert _surface(env, CAMPAIGN_ID) == before
        assert first == second
        assert all(isinstance(plan, RunPlan) for plan in first)
        for plan in first:
            plan.strategy_candidate_id = "tampered"
            plan.input_hash = "f" * 64
        assert _surface(env, CAMPAIGN_ID) == before
        assert first != second
        third = derive_adaptive_campaign_planning_authority(
            env, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert third == second
        assert third != first
        assert [plan.model_dump_json() for plan in third] == [
            plan.model_dump_json() for plan in second
        ]

    def test_exact_minimal_all(self) -> None:
        assert sorted(service_module.__all__) == [
            "RUNTIME_VERSION",
            "derive_adaptive_campaign_planning_authority",
        ]

    def test_exact_public_signature_boundary(self) -> None:
        signature = inspect.signature(derive_adaptive_campaign_planning_authority)
        parameters = list(signature.parameters.values())
        assert [parameter.name for parameter in parameters] == [
            "store",
            "tenant_id",
            "campaign_id",
            "runtime_version",
        ]
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])
        assert not any(
            parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for parameter in parameters
        )
        assert parameters[3].default == "4.0.0"

    def test_no_docstring_marker_or_todo_markers(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        for marker in ("TODO", "FIXME", "placeholder", "not implemented"):
            assert marker not in source

    def test_service_source_carries_no_runtime_one_two_three_literals(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        assert '"1.0.0"' not in source
        assert '"2.0.0"' not in source
        assert '"3.0.0"' not in source

    def test_service_source_has_no_machine_specific_paths(self) -> None:
        """Production code stays independent of authoring-machine paths."""
        source = SERVICE_PATH.read_text(encoding="utf-8")
        for marker in ("C:/Users/", "AppData/", "profile/cache"):
            assert marker not in source
