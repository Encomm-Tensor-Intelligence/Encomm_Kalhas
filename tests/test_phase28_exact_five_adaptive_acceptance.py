"""H28-S12 acceptance: the unpatched exact-five-plus-adaptive production proof.

One deterministic, domain-neutral, end-to-end campaign built exclusively
through the real public services over one ``InMemoryScenarioStore``, starting
from the frozen Gate 27.1 exact-five fixture helpers: the unmodified
production five-candidate invariant, the real ``MockLegionAdapter`` with the
five ordered static candidates (``mock-baseline``, ``mock-conservative``,
``mock-balanced``, ``mock-adaptive``, ``mock-diversified``), the four
immutable shared seeds (``seed-000``, ``seed-001``, ``seed-003``,
``seed-004``), and all twenty real runtime-3 static runs with their extracted
metric observations.

The campaign is then moved from COMPLETE to exactly COMPILED through the real
``update_campaign_status`` surface, and the additive runtime-4 adaptive arm is
built through the real services only: one external runtime observation
declaration ``obs-level`` (channel ``channel-1``, availability delay 0,
``NoObservationNoise``), the real ``bind_adaptive_policy`` service binding
``act-1`` to ``mock-baseline`` and ``act-2`` to ``mock-balanced`` with
initial/fallback ``act-1``, rule-1 entering ``act-2`` when ``obs-level > 0``,
rule-2 retaining ``act-1`` when ``obs-level > -1000``, minimum dwell 1,
cooldown 1, and global switch budget 2, four real external input bundles
(one per seed, decision step 0 value -3, decision step 1 value 5), the real
world realization matrix, the real adaptive planning authority (exactly four
plans anchored to ``mock-baseline``), four real PLANNED run statuses, four
real ``execute_adaptive_run`` executions with ``final_decision_step=1`` and
their real external bundles, the real comparison evidence, and the real
``replay_adaptive_run`` for every adaptive run.

The causal switch proof is exact production-path arithmetic: at decision
step 0 the only evidence is the step-0 external observation -3 (delay 0);
rule-1's enter tree compares ``-3 > 0`` (no match) and rule-2's retain tree
compares ``-3 > -1000`` (match on the current action ``act-1`` - eligible
immediately, no budget), so ``act-1`` is retained. The step-1 evidence is
not available at step 0 (a fresh bundle entry sourced at step 1 cannot be
consumed before decision 1). At step 1 the step-1 observation value 5 makes
rule-1's enter tree compare ``5 > 0`` (match), the dwell/cooldown/
global-budget eligibility passes exactly (dwell 1 installed at 0 permits
step 1; no prior switch means no cooldown; global budget 2 > 0; rule budget
1 > 0), and the real ``act-1 -> act-2`` rule switch fires: the global budget
decrements 2 -> 1, rule-1's budget 1 -> 0, and the recorded switch event
carries ``decision_step == 1`` - identically for all four seeds.

The comparison evidence is derived through the real
``derive_adaptive_static_comparison_evidence``: the adaptive side is paired
against every static arm, and each arm pair carries both objectives, so the
derived ``objective_pairs`` tuple holds exactly ten entries - the five
adaptive-vs-static arm pairs (``pair_position`` exactly 0..4) times the two
authoritative objectives - alongside exactly 20 seed-alignment receipts
(5 static arms x 4 seeds), exactly 4 switch summaries and exactly 4 noise
summaries (one per adaptive seed run), with canonical ordering and identical
seed alignment between the adaptive arm and every static candidate. Replay
proves canonical bytes and content-hash equality through the real
``replay_adaptive_run`` for all four adaptive runs plus the idempotent second
replay that writes nothing.

The adversarial section follows the established model_copy + canonical
rehash + private-collection injection + try/finally restore patterns: a
self-consistently rehashed corrupt adaptive execution, a reordered seed/plan
identity tuple, and a corrupted replay dependency are each rejected with the
exact typed error before and after a full-store fingerprint equality proof,
and the final pristine behavior is reverified. The store fingerprint covers
every normal ``STORE_COLLECTIONS`` entry plus the five runtime-4 adaptive
collections. No production behavior is patched, mocked, or mutated
anywhere in this module; the five-candidate/four-seed cardinality is never
reduced; no authority is hand-built; and no executed/replayed artifact is
faked.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from kalhas.application.adaptive_campaign_planning_service import (
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
from kalhas.application.adaptive_run_execution_builder import AdaptiveRunExecutionBuildDraft
from kalhas.application.adaptive_run_execution_query_service import (
    get_verified_adaptive_policy_decision_events,
    get_verified_adaptive_policy_switch_events,
    get_verified_runtime_observation_events,
)
from kalhas.application.adaptive_run_execution_service import execute_adaptive_run
from kalhas.application.adaptive_run_planner import ADAPTIVE_RUNTIME_VERSION, plan_adaptive_runs
from kalhas.application.adaptive_static_comparison_runtime import (
    derive_adaptive_static_comparison_evidence,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_trajectory_execution_content_hash,
)
from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
    AdaptiveRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.adaptive_trajectory_replay_service import replay_adaptive_run
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
    accept_external_observation_input_bundle,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_campaign_world_realization_matrix
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
)

from tests.phase4_helpers import NOW, TENANT
from tests.phase27_1_helpers import (
    CAMPAIGN_ID,
    SEED_IDENTIFIERS,
    STORE_COLLECTIONS,
    STRATEGIES,
    complete_exact_five_store,
    declare_exact_five_policy,
)

#: The frozen observation identifier of the single external channel.
OBSERVATION_ID = "obs-level"

#: The frozen external channel of the ``obs-level`` declaration.
EXTERNAL_CHANNEL = "channel-1"

#: The frozen logical adaptive actions and their static anchors.
ACTION_INITIAL = "act-1"
ACTION_ENTER = "act-2"
ANCHOR_INITIAL = "mock-baseline"
ANCHOR_ENTER = "mock-balanced"

#: The frozen causal evidence: decision step 0 sees -3, decision step 1 sees 5.
STEP0_VALUE = -3
STEP1_VALUE = 5

#: The frozen policy state-machine declarations.
MINIMUM_DWELL = 1
COOLDOWN = 1
GLOBAL_BUDGET = 2
RULE1_BUDGET = 1

#: The five runtime-4 adaptive store collections appended to the fingerprint.
ADAPTIVE_COLLECTIONS: tuple[str, ...] = (
    "_adaptive_policies",
    "_runtime_observation_declarations",
    "_external_observation_input_bundles",
    "_adaptive_run_trajectory_executions",
    "_adaptive_run_trajectory_replay_manifests",
)

#: The complete fingerprint surface: every normal collection plus runtime 4.
FINGERPRINT_COLLECTIONS: tuple[str, ...] = STORE_COLLECTIONS + ADAPTIVE_COLLECTIONS


def full_store_fingerprint(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest over every store collection, normal + runtime-4."""
    from tests.phase27_1_helpers import dump_value

    payload: dict[str, object] = {}
    for name in FINGERPRINT_COLLECTIONS:
        collection = getattr(store, name)
        payload[name] = {repr(key): dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)


def move_to_compiled(store: InMemoryScenarioStore) -> None:
    """Move the COMPLETE campaign to exactly COMPILED through the real surface."""
    status = store.get_campaign_status(TENANT, CAMPAIGN_ID)
    assert status.state is CampaignState.COMPLETE
    store.update_campaign_status(
        TENANT, CAMPAIGN_ID, status.model_copy(update={"state": CampaignState.COMPILED})
    )


def declare_obs_level(store: InMemoryScenarioStore, world_version_id: str) -> None:
    """Declare the real external ``obs-level`` observation (delay 0, no noise)."""
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_version_id,
            observation_id=OBSERVATION_ID,
            external_source=ExternalObservationDraft(
                external_channel_id=EXTERNAL_CHANNEL, external_value_kind="integer"
            ),
            timing=ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0),
            noise=NoObservationNoise(kind="none", draw_count=0),
            missing_behavior="false",
            declared_at=NOW,
            metadata={},
        ),
    )


def bind_exact_policy(store: InMemoryScenarioStore) -> None:
    """Bind the real adaptive policy through the real binding service."""
    leaf = ConditionComparisonLeaf(
        kind="comparison",
        condition_id="c-leaf",
        observation_id=OBSERVATION_ID,
        observed_value_kind="integer",
        unit=None,
        operator="gt",
        threshold=0,
        missing_behavior="false",
    )
    threshold_leaf = leaf.model_copy(update={"threshold": -1000})
    rule1_enter = leaf.model_copy(update={"condition_id": "c-rule1-enter"})
    rule1_retain = threshold_leaf.model_copy(update={"condition_id": "c-rule1-retain"})
    rule2_enter = leaf.model_copy(update={"condition_id": "c-rule2-enter"})
    rule2_retain = threshold_leaf.model_copy(update={"condition_id": "c-rule2-retain"})
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN_ID,
        draft=AdaptivePolicyDraft(
            request_id="req-h28-s12",
            actions=(ACTION_INITIAL, ACTION_ENTER),
            initial_action_id=ACTION_INITIAL,
            fallback_action_id=ACTION_INITIAL,
            rules=(
                AdaptivePolicyRuleDraft(
                    rule_id="rule-1",
                    priority=0,
                    target_action_id=ACTION_ENTER,
                    enter_condition=rule1_enter,
                    retain_condition=rule1_retain,
                    per_rule_switch_budget=RULE1_BUDGET,
                ),
                AdaptivePolicyRuleDraft(
                    rule_id="rule-2",
                    priority=1,
                    target_action_id=ACTION_INITIAL,
                    enter_condition=rule2_enter,
                    retain_condition=rule2_retain,
                    per_rule_switch_budget=1,
                ),
            ),
            minimum_dwell_steps=MINIMUM_DWELL,
            cooldown_steps=COOLDOWN,
            global_switch_budget=GLOBAL_BUDGET,
        ),
        binding_request=AdaptivePolicyBindingRequest(
            policy_id="policy-h28-s12",
            policy_version="1.0.0",
            action_mappings=(
                ActionStrategyMapping(
                    action_id=ACTION_INITIAL, strategy_candidate_id=ANCHOR_INITIAL
                ),
                ActionStrategyMapping(action_id=ACTION_ENTER, strategy_candidate_id=ANCHOR_ENTER),
            ),
            bound_at=NOW,
            metadata={},
        ),
    )


def accept_exact_bundles(
    store: InMemoryScenarioStore,
) -> dict[str, ExternalObservationInputBundleDraft]:
    """Accept the four real external bundles, one per shared seed, in seed order."""
    drafts: dict[str, ExternalObservationInputBundleDraft] = {}
    for seed_id in SEED_IDENTIFIERS:
        draft = ExternalObservationInputBundleDraft(
            entries=(
                ExternalObservationInputValueDraft(
                    observation_id=OBSERVATION_ID, source_step_index=0, value=STEP0_VALUE
                ),
                ExternalObservationInputValueDraft(
                    observation_id=OBSERVATION_ID, source_step_index=1, value=STEP1_VALUE
                ),
            ),
            accepted_at=NOW,
        )
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN_ID,
            scenario_seed_id=seed_id,
            draft=draft,
        )
        drafts[seed_id] = draft
    return drafts


def build_adaptive_arm(
    store: InMemoryScenarioStore,
) -> tuple[str, tuple[str, ...]]:
    """Build the complete additive adaptive arm through the real services only.

    Runs the exact mandated sequence: COMPILED transition, ``obs-level``
    declaration, policy binding, four external bundles, the real adaptive
    planning authority (stored via the real ``put_run_plans`` surface), the
    four PLANNED run statuses, and the four real adaptive executions. Returns
    the world version identifier and the adaptive run identifiers in the
    canonical campaign seed order.
    """
    move_to_compiled(store)
    campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
    world_version_id = campaign.world_version_id
    declare_obs_level(store, world_version_id)
    bind_exact_policy(store)
    bundle_drafts = accept_exact_bundles(store)
    plans = derive_adaptive_campaign_planning_authority(
        store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
    )
    assert len(plans) == 4
    store.put_run_plans(TENANT, CAMPAIGN_ID, plans)
    run_ids = tuple(run_identifier(plan) for plan in plans)
    for plan, run_id in zip(plans, run_ids, strict=True):
        store.put_run_status(
            TENANT,
            run_id,
            RunStatus(
                identifier=f"status-{run_id}",
                tenant_id=TENANT,
                run_id=run_id,
                campaign_id=CAMPAIGN_ID,
                run_plan_id=plan.identifier,
                state=RunState.PLANNED,
                runtime_version=plan.runtime_version,
                input_hash=plan.input_hash,
                event_hash=None,
                created_at=plan.created_at,
                changed_at=plan.created_at,
            ),
        )
        result = execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=1,
                external_bundle_draft=bundle_drafts[plan.scenario_seed_id],
            ),
        )
        assert result.status.state is RunState.COMPLETE, result.status
    return world_version_id, run_ids


def run_identifier(run_plan: Any) -> str:
    """The established deterministic run identifier of one run plan."""
    return f"run-{run_plan.identifier}"


@pytest.fixture(scope="module")
def env() -> tuple[InMemoryScenarioStore, str, tuple[str, ...]]:
    """The full exact-five-plus-adaptive environment over the real services."""
    store = complete_exact_five_store()
    declare_exact_five_policy(store)
    world_id, run_ids = build_adaptive_arm(store)
    return store, world_id, run_ids


# ---------------------------------------------------------------------------
# A. Exact-five compatibility
# ---------------------------------------------------------------------------


class TestExactFiveCompatibility:
    def test_all_five_static_candidates_remain_ordered_and_unchanged(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = env
        candidates = store.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        assert tuple(candidate.identifier for candidate in candidates) == STRATEGIES
        # The exact-five compatibility proof is the real production gate:
        # campaign preparation already succeeded under the unmodified
        # production invariant, so the five ordered candidates are the
        # unchanged production set.
        assert len(candidates) == 5

    def test_four_seeds_and_twenty_static_runs_remain_present(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, adaptive_run_ids = env
        campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
        assert tuple(seed.identifier for seed in campaign.seed_ensemble) == SEED_IDENTIFIERS
        executions = store._realization_run_trajectory_executions
        static_run_keys = {
            key for key in executions if key[0] == TENANT and key[1] not in adaptive_run_ids
        }
        assert len(static_run_keys) == 20
        observation_sets = store._realization_run_metric_observation_sets
        static_observation_keys = {
            key for key in observation_sets if key[0] == TENANT and key[1] not in adaptive_run_ids
        }
        assert len(static_observation_keys) == 20

    def test_adaptive_arm_is_additive_not_a_sixth_static_candidate(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = env
        candidates = store.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        assert tuple(candidate.identifier for candidate in candidates) == STRATEGIES
        adaptive_policy = store.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        anchored = {
            action.strategy_candidate_id
            for action in adaptive_policy.actions
            if action.strategy_candidate_id in STRATEGIES
        }
        # The adaptive actions are bound to existing static candidates; the
        # candidate set itself grew by nothing.
        assert anchored == {ANCHOR_INITIAL, ANCHOR_ENTER}

    def test_planning_yields_four_adaptive_plans_the_pure_planner_recomputes(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, world_id, run_ids = env
        plans = store.get_run_plans(TENANT, CAMPAIGN_ID)
        assert len(plans) == 4
        assert [run_identifier(plan) for plan in plans] == list(run_ids)
        assert [plan.scenario_seed_id for plan in plans] == list(SEED_IDENTIFIERS)
        assert all(plan.strategy_candidate_id == ANCHOR_INITIAL for plan in plans)
        assert all(plan.runtime_version == "4.0.0" for plan in plans)
        # The accepted pure planner recomputes exactly the stored tuple
        # from the verified authorities and the single realization matrix -
        # the stored plans are faithful, and the derivation is detached.
        campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
        world = store.get_world(TENANT, world_id)
        catalog = extract_world_catalog(world)
        model = store.get_world_uncertainty_model(TENANT, "scenario-1")
        matrix = build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=model,
        )
        realizations = {
            realization.scenario_seed_id: realization for realization in matrix.realizations
        }
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        recomputed = plan_adaptive_runs(
            campaign_id=CAMPAIGN_ID,
            tenant_id=TENANT,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            policy=policy,
            seeds=campaign.seed_ensemble,
            created_at=campaign.created_at,
            realizations=realizations,
            runtime_version=ADAPTIVE_RUNTIME_VERSION,
        )
        assert canonical_json([plan.model_dump(mode="json") for plan in plans]) == canonical_json(
            [plan.model_dump(mode="json") for plan in recomputed]
        )


# ---------------------------------------------------------------------------
# B. Causal switching and budgets
# ---------------------------------------------------------------------------


class TestCausalSwitchingAndBudgets:
    def test_step0_retains_act1_on_the_only_available_evidence(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        for run_id in run_ids:
            decisions = get_verified_adaptive_policy_decision_events(
                store, tenant_id=TENANT, run_id=run_id
            )
            observations = get_verified_runtime_observation_events(
                store, tenant_id=TENANT, run_id=run_id
            )
            step0 = decisions[0]
            assert step0.decision_step == 0
            assert step0.current_action_id == ACTION_INITIAL
            assert step0.selected_action_id == ACTION_INITIAL
            assert step0.action_changed is False
            # The step-0 decision input is exactly the step-0 observation -3.
            available = [
                event
                for event in observations
                if event.available_decision_step == 0 and not event.terminal
            ]
            assert [event.exposed_observation_value for event in available] == [STEP0_VALUE]
            # Rule-1's enter tree does not match (-3 > 0 is false); rule-2's
            # retain tree matches (-3 > -1000) on the current action and is
            # eligible immediately without consuming any budget.
            records = {record[0]: record for record in step0.rule_evaluation_evidence}
            assert records["rule-1"] == ("rule-1", "enter", False, None)
            assert records["rule-2"] == ("rule-2", "retain", True, None)
            assert step0.selected_rule_id == "rule-2"
            assert step0.decision_kind == "rule"

    def test_step1_evidence_is_unavailable_at_step0(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        for run_id in run_ids:
            observations = get_verified_runtime_observation_events(
                store, tenant_id=TENANT, run_id=run_id
            )
            by_step = {event.source_step_index: event for event in observations}
            assert set(by_step) == {0, 1}
            # The delay-0 declaration makes each event available exactly at
            # its own source step; the step-1 event can never enter the
            # step-0 decision input.
            assert by_step[0].available_decision_step == 0
            assert by_step[1].available_decision_step == 1
            assert by_step[0].exposed_observation_value == STEP0_VALUE
            assert by_step[1].exposed_observation_value == STEP1_VALUE

    def test_step1_rule_switch_act1_to_act2_with_exact_budgets_for_all_seeds(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        for run_id in run_ids:
            decisions = get_verified_adaptive_policy_decision_events(
                store, tenant_id=TENANT, run_id=run_id
            )
            switches = get_verified_adaptive_policy_switch_events(
                store, tenant_id=TENANT, run_id=run_id
            )
            assert len(decisions) == 2
            assert len(switches) == 1
            step1 = decisions[1]
            assert step1.current_action_id == ACTION_INITIAL
            assert step1.selected_action_id == ACTION_ENTER
            assert step1.selected_rule_id == "rule-1"
            assert step1.decision_kind == "rule"
            assert step1.action_changed is True
            assert step1.rule_evaluation_evidence == (("rule-1", "enter", True, None),)
            switch = switches[0]
            assert switch.decision_step == 1
            assert switch.old_action_id == ACTION_INITIAL
            assert switch.new_action_id == ACTION_ENTER
            assert switch.trigger_kind == "rule"
            assert switch.triggering_rule_id == "rule-1"
            assert switch.global_switch_budget_before == GLOBAL_BUDGET
            assert switch.global_switch_budget_after == GLOBAL_BUDGET - 1
            assert switch.rule_switch_budget_before == RULE1_BUDGET
            assert switch.rule_switch_budget_after == RULE1_BUDGET - 1

    def test_pre_switch_snapshot_proves_the_exact_pre_decision_budgets(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        for run_id in run_ids:
            execution = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
            snapshots = execution.policy_state_snapshots
            assert len(snapshots) == 2
            initial = snapshots[0]
            assert initial.current_action_id == ACTION_INITIAL
            assert initial.last_switch_decision_step is None
            assert initial.remaining_global_switch_budget == GLOBAL_BUDGET
            assert dict(initial.per_rule_remaining_budgets) == {
                "rule-1": RULE1_BUDGET,
                "rule-2": 1,
            }
            pre_switch = snapshots[1]
            # The pre-decision state of step 1 still carries the untouched
            # budgets; the switch itself is recorded by the step-1 event
            # with decision step 1 - the exact recorded last-switch step.
            assert pre_switch.current_action_id == ACTION_INITIAL
            assert pre_switch.last_switch_decision_step is None
            assert pre_switch.remaining_global_switch_budget == GLOBAL_BUDGET
            switch = execution.switch_events[0]
            assert switch.decision_step == 1
            assert switch.global_switch_budget_after == (
                pre_switch.remaining_global_switch_budget - 1
            )

    def test_final_execution_authority_proves_the_transition(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, world_id, run_ids = env
        campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
        world = store.get_world(TENANT, world_id)
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        assert policy.initial_action_id == ACTION_INITIAL
        assert policy.fallback_action_id == ACTION_INITIAL
        assert policy.minimum_dwell_steps == MINIMUM_DWELL
        assert policy.cooldown_steps == COOLDOWN
        assert policy.global_switch_budget == GLOBAL_BUDGET
        plans = {run_identifier(plan): plan for plan in store.get_run_plans(TENANT, CAMPAIGN_ID)}
        for run_id in run_ids:
            execution = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
            plan = plans[run_id]
            assert execution.run_plan_id == plan.identifier
            assert execution.campaign_id == CAMPAIGN_ID
            assert execution.world_version_id == world.identifier
            assert execution.world_content_hash == world.content_hash
            assert execution.policy_id == policy.policy_id
            assert execution.adaptive_policy_content_hash == policy.content_hash
            assert execution.scenario_seed_id == plan.scenario_seed_id
            assert execution.runtime_version == "4.0.0"
            # The wide runtime-4 digest is never the narrow planning digest.
            assert execution.input_hash != plan.input_hash
        assert world.identifier == campaign.world_version_id


# ---------------------------------------------------------------------------
# C. Comparison evidence
# ---------------------------------------------------------------------------


class TestComparisonEvidence:
    def test_exact_cardinalities_of_all_comparison_artifacts(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = env
        evidence = derive_adaptive_static_comparison_evidence(
            store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        # Five adaptive-vs-static arm pairs (pair_position 0..4), each
        # carrying both authoritative objectives: ten evidence entries.
        assert len(evidence.objective_pairs) == 10
        assert {pair.pair_position for pair in evidence.objective_pairs} == {0, 1, 2, 3, 4}
        assert len({pair.static_strategy_candidate_id for pair in evidence.objective_pairs}) == 5
        assert len(evidence.seed_alignment_receipts) == 20
        assert len(evidence.switch_summaries) == 4
        assert len(evidence.noise_summaries) == 4

    def test_canonical_ordering_and_identical_seed_alignment(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, world_id, _run_ids = env
        evidence = derive_adaptive_static_comparison_evidence(
            store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
        world = store.get_world(TENANT, world_id)
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        seed_ids = list(SEED_IDENTIFIERS)
        assert evidence.ordered_seed_ids == tuple(seed_ids)
        assert evidence.campaign_id == CAMPAIGN_ID
        assert evidence.world_version_id == world.identifier
        assert evidence.world_content_hash == world.content_hash
        assert evidence.adaptive_policy_id == policy.policy_id
        assert evidence.adaptive_policy_content_hash == policy.content_hash
        # Objective pairs: the adaptive side against each static arm in the
        # exact campaign candidate order, arm-major and objective-minor,
        # with canonical seed alignment on every entry.
        arm_order: list[str] = []
        for pair in evidence.objective_pairs:
            if not arm_order or arm_order[-1] != pair.static_strategy_candidate_id:
                arm_order.append(pair.static_strategy_candidate_id)
        assert arm_order == list(STRATEGIES)
        for index, pair in enumerate(evidence.objective_pairs):
            expected_objective = "obj-1" if index % 2 == 0 else "obj-2"
            assert pair.objective_id == expected_objective
            assert pair.objective_position == index % 2
            assert pair.ordered_seed_ids == tuple(seed_ids)
        # The adaptive values are the one shared adaptive arm across pairs;
        # the static values are each static arm's own.
        first_pair = evidence.objective_pairs[0]
        for pair in evidence.objective_pairs:
            if pair.objective_id == first_pair.objective_id:
                assert pair.ordered_adaptive_values == first_pair.ordered_adaptive_values
        # Seed-alignment receipts: every (static arm, seed) pair, in
        # seed-major order, proving identical realization and world
        # authorities across arms.
        expected_receipt_keys = [(arm, seed_id) for seed_id in seed_ids for arm in STRATEGIES]
        actual_receipt_keys = [
            (receipt.static_strategy_candidate_id, receipt.scenario_seed_id)
            for receipt in evidence.seed_alignment_receipts
        ]
        assert actual_receipt_keys == expected_receipt_keys
        seed_by_id = {seed.identifier: seed for seed in campaign.seed_ensemble}
        for receipt in evidence.seed_alignment_receipts:
            assert receipt.adaptive_world_realization_id == receipt.static_world_realization_id
            # One shared realization identity/hash field per receipt: both
            # arms bound the identical shared-seed realization record.
            assert receipt.world_realization_content_hash != ""
            assert receipt.adaptive_world_content_hash == world.content_hash
            assert receipt.static_world_content_hash == world.content_hash
            assert receipt.adaptive_seed_content_hash == seed_content_hash(
                seed_by_id[receipt.scenario_seed_id]
            )
            assert receipt.static_seed_content_hash == receipt.adaptive_seed_content_hash
        # Switch and noise summaries follow the exact canonical seed order.
        assert [summary.scenario_seed_id for summary in evidence.switch_summaries] == seed_ids
        assert [summary.scenario_seed_id for summary in evidence.noise_summaries] == seed_ids
        assert all(
            summary.initial_action_id == ACTION_INITIAL
            and summary.initial_action_strategy_anchor == ANCHOR_INITIAL
            for summary in evidence.switch_summaries
        )
        assert all(summary.switch_count == 1 for summary in evidence.switch_summaries)
        assert all(
            switch.decision_step == 1
            and switch.old_action_id == ACTION_INITIAL
            and switch.new_action_id == ACTION_ENTER
            and switch.left_initial_action_strategy_anchor is True
            for summary in evidence.switch_summaries
            for switch in summary.switches
        )
        assert all(summary.all_noise_coordinates_verified for summary in evidence.noise_summaries)
        assert all(summary.observed_event_count == 2 for summary in evidence.noise_summaries)
        assert all(summary.noise_draw_event_count == 0 for summary in evidence.noise_summaries)

    def test_public_query_surfaces_return_deep_copy_safe_authoritative_data(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        run_id = run_ids[0]

        def evidence_json(derived: Any) -> str:
            return canonical_json(
                {
                    "pairs": [pair._asdict() for pair in derived.objective_pairs],
                    "receipts": [receipt._asdict() for receipt in derived.seed_alignment_receipts],
                    "switches": [summary._asdict() for summary in derived.switch_summaries],
                    "noise": [summary._asdict() for summary in derived.noise_summaries],
                }
            )

        baseline = evidence_json(
            derive_adaptive_static_comparison_evidence(
                store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            )
        )
        before = full_store_fingerprint(store)
        # Repeated derivations and reads are byte-identical and write-free.
        repeated = derive_adaptive_static_comparison_evidence(
            store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert evidence_json(repeated) == baseline
        assert full_store_fingerprint(store) == before
        # The evidence aggregate is an immutable derived artifact: its
        # named-tuple members cannot be mutated in place, and a replaced
        # copy is a detached new object.
        replaced_switch = repeated.switch_summaries[0].switches[0]._replace(decision_step=99)
        assert replaced_switch.decision_step == 99
        assert repeated.switch_summaries[0].switches[0].decision_step == 1
        # Query projections are frozen contracts: a mutated copy is a new
        # detached object and the store's authority is untouched.
        events = get_verified_adaptive_policy_decision_events(
            store, tenant_id=TENANT, run_id=run_id
        )
        detached = events[0].model_copy(update={"selected_action_id": "act-x"})
        assert detached.selected_action_id == "act-x"
        assert (
            get_verified_adaptive_policy_decision_events(store, tenant_id=TENANT, run_id=run_id)[
                0
            ].selected_action_id
            == ACTION_INITIAL
        )
        assert full_store_fingerprint(store) == before


# ---------------------------------------------------------------------------
# D. Replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_every_adaptive_execution_replays_with_canonical_bytes_and_hashes(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        for run_id in run_ids:
            execution = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
            manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
            assert manifest.run_id == run_id
            assert manifest.campaign_id == CAMPAIGN_ID
            assert manifest.expected_execution_hash == execution.content_hash
            assert manifest.recomputed_execution_hash == execution.content_hash
            assert manifest.replay_classification == "exact"
            assert manifest.input_hash == execution.input_hash
            assert manifest.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
            assert manifest.world_content_hash == execution.world_content_hash
            assert manifest.seed_content_hash == execution.seed_content_hash
            assert (
                manifest.external_observation_input_bundle_id
                == execution.external_observation_input_bundle_id
            )
            assert manifest.adaptive_policy_content_hash == execution.adaptive_policy_content_hash
            stored = store.get_adaptive_run_trajectory_replay_manifest(
                tenant_id=TENANT, run_id=run_id
            )
            assert canonical_json(manifest.model_dump(mode="json")) == canonical_json(
                stored.model_dump(mode="json")
            )

    def test_second_replay_is_idempotent_and_changes_no_store_state(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        before = full_store_fingerprint(store)
        for run_id in run_ids:
            first = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
            second = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
            assert canonical_json(first.model_dump(mode="json")) == canonical_json(
                second.model_dump(mode="json")
            )
        assert full_store_fingerprint(store) == before


# ---------------------------------------------------------------------------
# E. Corruption / rejection boundaries
# ---------------------------------------------------------------------------


def _expect_comparison_rejection(store: InMemoryScenarioStore, expected_reason: str) -> None:
    with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
        derive_adaptive_static_comparison_evidence(store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID)
    assert excinfo.value.reason == expected_reason


def _expect_replay_rejection(
    store: InMemoryScenarioStore,
    run_id: str,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)


class TestCorruptionRejectionBoundaries:
    def test_corrupt_adaptive_execution_authority_is_rejected_exactly(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        run_id = run_ids[0]
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_id)
        original = collection[key]
        pristine = full_store_fingerprint(store)
        try:
            # Self-consistent tamper: the recorded world hash no longer
            # agrees with the stored world authority, while the record's own
            # content hash covers the change - the verified store getter
            # rejects the disagreement before any derivation runs.
            broken = original.model_copy(update={"world_content_hash": "f" * 64})
            broken = broken.model_copy(
                update={"content_hash": adaptive_run_trajectory_execution_content_hash(broken)}
            )
            collection[key] = broken
            before = full_store_fingerprint(store)
            _expect_comparison_rejection(store, "adaptive execution authority missing or corrupt")
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        # Pristine behavior is reverified after the adversary.
        assert (
            derive_adaptive_static_comparison_evidence(
                store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            ).campaign_id
            == CAMPAIGN_ID
        )

    def test_missing_adaptive_execution_authority_is_rejected_exactly(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_ids[1])
        original = collection[key]
        pristine = full_store_fingerprint(store)
        try:
            del collection[key]
            before = full_store_fingerprint(store)
            _expect_comparison_rejection(store, "adaptive execution authority missing or corrupt")
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        assert (
            derive_adaptive_static_comparison_evidence(
                store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            ).campaign_id
            == CAMPAIGN_ID
        )

    def test_seed_order_and_plan_alignment_corruption_is_rejected_exactly(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = env
        collection = store._run_plans
        key = (TENANT, CAMPAIGN_ID)
        original = collection[key]
        pristine = full_store_fingerprint(store)
        try:
            reordered = (original[1], original[0], original[2], original[3])
            collection[key] = reordered
            before = full_store_fingerprint(store)
            # The comparison requires the stored adaptive plan tuple to
            # carry the exact campaign seed order and the exact
            # initial-action anchor; a reordered tuple violates the order.
            _expect_comparison_rejection(store, "stored adaptive plan seed order mismatch")
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        # Anchor corruption on an otherwise ordered tuple.
        try:
            swapped_anchor = tuple(
                plan.model_copy(update={"strategy_candidate_id": ANCHOR_ENTER})
                if position == 0
                else plan
                for position, plan in enumerate(original)
            )
            collection[key] = swapped_anchor
            before = full_store_fingerprint(store)
            _expect_comparison_rejection(store, "stored adaptive plan anchor mismatch")
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        assert (
            derive_adaptive_static_comparison_evidence(
                store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            ).campaign_id
            == CAMPAIGN_ID
        )

    def test_wide_input_digest_corruption_is_rejected_exactly(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        run_id = run_ids[2]
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_id)
        original = collection[key]
        pristine = full_store_fingerprint(store)
        try:
            # A wrong wide runtime-4 digest cannot pass the verified store
            # getter: the getter's authority verifier recomputes the digest
            # from the store's own authority chain and rejects the record.
            broken = original.model_copy(update={"input_hash": "a" * 64})
            collection[key] = broken
            before = full_store_fingerprint(store)
            _expect_comparison_rejection(store, "adaptive execution authority missing or corrupt")
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        assert (
            derive_adaptive_static_comparison_evidence(
                store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            ).campaign_id
            == CAMPAIGN_ID
        )

    def test_corrupted_replay_dependency_is_rejected_exactly(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = env
        run_id = run_ids[3]
        collection = store._adaptive_run_trajectory_executions
        key = (TENANT, run_id)
        original = collection[key]
        pristine = full_store_fingerprint(store)
        try:
            broken = original.model_copy(update={"world_realization_content_hash": "e" * 64})
            broken = broken.model_copy(
                update={"content_hash": adaptive_run_trajectory_execution_content_hash(broken)}
            )
            collection[key] = broken
            before = full_store_fingerprint(store)
            # The verified store getter itself rejects the disagreeing
            # realization provenance before the replay service runs.
            _expect_replay_rejection(
                store, run_id, AdaptiveRunTrajectoryReplayManifestIntegrityError
            )
            assert full_store_fingerprint(store) == before
        finally:
            collection[key] = original
        assert full_store_fingerprint(store) == pristine
        # Pristine replay is reverified and stays idempotent.
        first = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
        second = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
        assert canonical_json(first.model_dump(mode="json")) == canonical_json(
            second.model_dump(mode="json")
        )

    def test_missing_replay_manifest_read_is_the_typed_not_found(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = env
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
            store.get_adaptive_run_trajectory_replay_manifest(
                tenant_id=TENANT, run_id="run-does-not-exist"
            )


# ---------------------------------------------------------------------------
# F. Architecture and hygiene
# ---------------------------------------------------------------------------


class TestArchitectureAndHygiene:
    def test_no_forbidden_surface_or_production_mutation(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        import kalhas.application.realization_campaign_service as preparation_module

        import tests.test_phase28_exact_five_adaptive_acceptance as this_module

        source = inspect.getsource(this_module)
        lowered = source.lower()
        # Built from fragments so the sentinels cannot match this module's
        # own source text.
        forbidden_markers = (
            "monkey" + "patch",
            "unittest." + "mock",
            "pytest." + "skip",
            "pytest." + "mark." + "xfail",
            "no" + "qa",
            "type: " + "ignore",
            "EXPECTED_" + "STRATEGY_SET_SIZE =",
        )
        for marker in forbidden_markers:
            assert marker.lower() not in lowered, marker
        # The production cardinality invariant is the untouched value 5.
        assert getattr(preparation_module, "EXPECTED_" + "STRATEGY_SET_SIZE") == 5

    def test_no_nexus_legion_imports_or_new_components(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        import tests.test_phase28_exact_five_adaptive_acceptance as this_module

        for name, value in vars(this_module).items():
            if name.startswith("__"):
                continue
            module = getattr(value, "__module__", None)
            if module is None:
                continue
            assert "nexus" not in module, name
            assert "legion" not in module, name

    def test_domain_neutral_kernel_boundary_and_frozen_v1_compatibility(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        import kalhas.application.adaptive_static_comparison_runtime as comparison_module
        import kalhas.contracts.v1.adaptive_policy as policy_contract_module

        # The adaptive runtime is consumed only through kalhas.application
        # services and kalhas.contracts.v1 - the domain-neutral kernel keeps
        # no domain logic and the contracts stay inside frozen v1.
        for module_source in (
            inspect.getsource(comparison_module),
            inspect.getsource(policy_contract_module),
        ):
            assert "import nexus" not in module_source.lower()
            assert "import legion" not in module_source.lower()
        store, world_id, _run_ids = env
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN_ID)
        assert policy.schema_version == "1.0.0"
        assert policy.runtime_version == "4.0.0"
        declaration = store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, OBSERVATION_ID
        )
        assert declaration.schema_version == "1.0.0"
        assert declaration.runtime_version == "4.0.0"

    def test_no_live_action_surface_in_the_acceptance_module(
        self, env: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        import tests.test_phase28_exact_five_adaptive_acceptance as this_module

        source = inspect.getsource(this_module)
        # Built from fragments so the sentinels cannot match this module's
        # own source text.
        forbidden_surface_literals = (
            "re" + "quests.",
            "url" + "lib",
            "sock" + "et.",
            "ht" + "tpx",
            "subpro" + "cess",
        )
        for forbidden in forbidden_surface_literals:
            assert forbidden not in source
