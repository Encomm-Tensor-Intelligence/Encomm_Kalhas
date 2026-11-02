"""Pack-agnostic Runtime-4 authority-chain builder for Phase 29 acceptance tests.

Replicates the deterministic Runtime-4 authority chain (scenario, world,
campaign, seed, realization, policy, decision event, run plan, run
status) used by the mechanism-bridge tests, without importing any
private name from them. It carries no pack-specific payload and
references no concrete pack: the pack and its pack-owned state and
action payloads are always supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_policy_state_machine import (
    advance_adaptive_policy_state,
    initialize_adaptive_policy_state,
)
from kalhas.application.domain_mechanism_runtime import (
    Runtime4DomainMechanismStepDraft,
    Runtime4DomainMechanismStepExecution,
    execute_runtime4_domain_mechanism_step,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_trajectory_runtime import realized_initial_state
from kalhas.application.runtime_observation_declaration_service import (
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_service import (
    ObservationStepDraft,
    derive_observation_step,
)
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_compiler import compile_world
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.adaptive_policy_state import AdaptivePolicyDecisionEvent
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.domain_mechanism import MechanismExogenousInput
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.scenario import ScenarioSeed, ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, StateValueKind
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import UniformDistribution, WorldRealization
from kalhas.domain_packs import DomainPack

HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
#: The synthetic tenant shared by the whole authority chain; every
#: synthetic pack declares the same tenant.
TENANT = "kalhas-synthetic"
OTHER_TENANT = "tenant-other"
CAMPAIGN = "campaign-1"
SEED_ID = "seed-1"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
RUNTIME_VERSION = "4.0.0"
STEP = 0


def _canonical_hash(payload: object) -> str:
    """Canonical SHA-256 of the exact JSON payload value (independent)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _leaf(condition_id: str, threshold: int) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id="obs-level",
        observed_value_kind="integer",
        unit=None,
        operator="gt",
        threshold=threshold,
        missing_behavior="false",
    )


def _rule(rule_id: str, priority: int, target: str, threshold: int) -> AdaptivePolicyRuleDraft:
    return AdaptivePolicyRuleDraft(
        rule_id=rule_id,
        priority=priority,
        target_action_id=target,
        enter_condition=_leaf(f"{rule_id}-enter", threshold),
        retain_condition=_leaf(f"{rule_id}-retain", threshold),
        per_rule_switch_budget=1,
    )


def _policy_draft() -> AdaptivePolicyDraft:
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            _rule("rule-1", 0, "act-2", 0),
            _rule("rule-2", 1, "act-1", -1000),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _binding_request(policy_id: str) -> AdaptivePolicyBindingRequest:
    return AdaptivePolicyBindingRequest(
        policy_id=policy_id,
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=BOUND_AT,
        metadata={},
    )


def _new_store_with_world() -> tuple[InMemoryScenarioStore, str]:
    """A compiled two-model world with an uncertainty model and transitions."""
    store = InMemoryScenarioStore()
    scenario = _scenario()
    store.put_scenario(scenario)
    register_manifest(
        store,
        tenant_id=TENANT,
        identifier="manifest-1",
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.2.3",
        description="Declarative pack metadata only",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        schema_metadata={},
        created_at=NOW,
        metadata={},
    )
    bind_manifest(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        bound_at=BOUND_AT,
    )

    def _field(
        identifier: str, kind: StateValueKind, initial: JsonValue
    ) -> DomainStateFieldDefinition:
        return DomainStateFieldDefinition(
            identifier=identifier,
            description="Declared state field",
            value_kind=kind,
            initial_value=initial,
        )

    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-a",
        state_fields=(
            _field("level", StateValueKind.INTEGER, 0),
            _field("ratio", StateValueKind.NUMBER, 0.0),
            _field("status", StateValueKind.STRING, "idle"),
        ),
        declared_at=DECLARED_AT,
    )
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-b",
        state_fields=(
            _field("count", StateValueKind.INTEGER, 3),
            _field("weight", StateValueKind.NUMBER, 0.5),
        ),
        declared_at=DECLARED_AT,
    )
    uncertainty_model = declare_world_uncertainty_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=(
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-b",
                state_field_id="weight",
                distribution=UniformDistribution(kind="uniform", low=5.0, high=10.0),
            ),
        ),
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-a",
        transition_id="t-1",
        description="Advance the numeric fields",
        guard_values={"level": 0, "ratio": 0.0},
        target_values={"level": 1, "ratio": 1.5},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-b",
        transition_id="t-1",
        description="Set the secondary numeric fields",
        guard_values={"count": 3},
        target_values={"count": 4, "weight": 1.0},
        declared_at=DECLARED_AT,
    )
    compiled = compile_world(
        scenario,
        bindings=(store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1"),),
        state_models=(
            store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a"),
            store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b"),
        ),
        transitions=tuple(store.list_domain_state_transitions(TENANT, "scenario-1")),
        uncertainty_model=uncertainty_model,
    )
    store.put_world(compiled.version, compiled.manifest)
    return store, compiled.version.identifier


def _scenario() -> ScenarioSpec:
    from kalhas.contracts.v1.scenario import Constraint, Objective, ObjectiveDirection, TimeHorizon
    from kalhas.contracts.v1.shared import MetricDefinition

    return ScenarioSpec(
        identifier="scenario-1",
        tenant_id=TENANT,
        name="Reference scenario",
        description="Domain-neutral scenario",
        created_at=NOW,
        objectives=[
            Objective(
                identifier="obj-1",
                description="Maximize the primary metric",
                direction=ObjectiveDirection.MAXIMIZE,
                target=100.0,
                weight=1.0,
            )
        ],
        constraints=[Constraint(identifier="c-1", description="Stay within declared bounds")],
        time_horizon=TimeHorizon(start=NOW, end=LATER, resolution="step"),
        metrics=[MetricDefinition(identifier="m-1", name="Primary metric")],
        metadata={},
    )


_TIMING_0 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)


class Phase29Environment:
    """The complete deterministic Runtime-4 authority chain of one run."""

    def __init__(self) -> None:
        store, world_id = _new_store_with_world()
        from kalhas.application.campaign_service import prepare_campaign
        from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
        from kalhas.contracts.v1.scenario import ScenarioSeed as SeedContract
        from kalhas.contracts.v1.strategy import (
            ObservationRequirement,
            StrategyRequest,
        )

        scenario = store.get_scenario(TENANT, "scenario-1")
        prepare_campaign(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            strategy_request=StrategyRequest(
                identifier="sr-1",
                tenant_id=TENANT,
                scenario_id="scenario-1",
                required_observations=[
                    ObservationRequirement(metric_id="m-1", description="observe m-1")
                ],
                requested_at=NOW,
            ),
            campaign_id=CAMPAIGN,
            campaign_name="Reference campaign",
            seed_ensemble=(
                SeedContract(
                    identifier=SEED_ID, tenant_id=TENANT, algorithm="deterministic", seed_value="v1"
                ),
            ),
            created_at=NOW,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        )
        del scenario
        prepare_strategy_trajectory_plans(
            store=store,
            legion=MockLegionAdapter(
                declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}
            ),
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
        )
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=RuntimeObservationDeclarationDraft(
                scenario_id="scenario-1",
                world_version_id=world_id,
                observation_id="obs-level",
                state_source=StateFieldObservationDraft(
                    manifest_id="manifest-1", state_model_id="sm-a", state_field_id="level"
                ),
                timing=_TIMING_0,
                noise=_NO_NOISE,
                missing_behavior="false",
                declared_at=DECLARED_AT,
                metadata={},
            ),
        )
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            draft=_policy_draft(),
            binding_request=_binding_request("policy-1"),
        )
        self.store = store
        self.world_id = world_id
        self.scenario = store.get_scenario(TENANT, "scenario-1")
        self.world: WorldVersion = store.get_world(TENANT, world_id)
        self.world_manifest: WorldManifest = store.get_manifest(TENANT, world_id)
        self.campaign = store.get_campaign(TENANT, CAMPAIGN)
        self.campaign_status = store.get_campaign_status(TENANT, CAMPAIGN)
        assert self.campaign_status.state is CampaignState.COMPILED
        self.seed: ScenarioSeed = next(
            member for member in self.campaign.seed_ensemble if member.identifier == SEED_ID
        )
        catalog = extract_world_catalog(self.world)
        self.realization: WorldRealization = build_world_realization(
            world=self.world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=self.seed,
            realized_at=NOW,
        )
        self.policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
        anchor_actions = [
            action
            for action in self.policy.actions
            if action.action_id == self.policy.initial_action_id
        ]
        self.anchor = anchor_actions[0].strategy_candidate_id
        self.run_plan = RunPlan(
            identifier=(
                "plan-"
                + _canonical_hash(
                    {
                        "campaign_id": CAMPAIGN,
                        "world_version_id": world_id,
                        "strategy_candidate_id": self.anchor,
                        "scenario_seed_id": SEED_ID,
                        "runtime_version": RUNTIME_VERSION,
                    }
                )[:16]
            ),
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            world_version_id=world_id,
            strategy_candidate_id=self.anchor,
            scenario_seed_id=SEED_ID,
            runtime_version=RUNTIME_VERSION,
            input_hash=_canonical_hash(
                {
                    "policy": self.policy.model_dump(mode="json"),
                    "runtime_version": RUNTIME_VERSION,
                    "seed": self.seed.model_dump(mode="json"),
                    "world_content_hash": self.world.content_hash,
                    "world_realization_content_hash": self.realization.content_hash,
                }
            ),
            created_at=NOW,
        )
        self.run_id = f"run-{self.run_plan.identifier}"
        self.run_status = RunStatus(
            identifier=f"status-{self.run_id}",
            tenant_id=TENANT,
            run_id=self.run_id,
            campaign_id=CAMPAIGN,
            run_plan_id=self.run_plan.identifier,
            state=RunState.RUNNING,
            runtime_version=RUNTIME_VERSION,
            input_hash=self.run_plan.input_hash,
            event_hash=None,
            created_at=NOW,
            changed_at=NOW,
        )
        # The complete pre-action state collection from the verified world
        # realization, and the real decision event of decision step 0.
        self.models = {model.identifier: model for model in catalog.state_models}
        self.states: dict[str, dict[str, JsonValue]] = {
            identifier: realized_initial_state(
                state_model=self.models[identifier],
                realization=self.realization,
                run_id=self.run_id,
            )
            for identifier in sorted(self.models)
        }
        self.decision_event = self._derive_decision_event()

    def _derive_decision_event(self) -> AdaptivePolicyDecisionEvent:
        """One real Runtime-4 decision step through the established primitives."""
        decl = self.store.get_runtime_observation_declaration(
            TENANT, "scenario-1", self.world_id, "obs-level"
        )
        source = decl.observation_source
        if not isinstance(source, StateFieldObservationSource):
            raise AssertionError("fixture expects a state-field observation source")
        visible_model = source.state_model_identifier
        observations = derive_observation_step(
            self.store,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            scenario_seed_id=SEED_ID,
            draft=ObservationStepDraft(
                decision_step=0,
                final_decision_step=0,
                state={visible_model: self.states[visible_model]},
                prior_events=(),
                external_bundle_draft=None,
            ),
        )
        step = advance_adaptive_policy_state(
            policy=self.policy,
            state=initialize_adaptive_policy_state(self.policy),
            events=observations.available_events,
            scenario_seed_id=SEED_ID,
            seed_content_hash=seed_content_hash(self.seed),
        )
        return step.decision_event

    def draft(
        self,
        *,
        step_index: int = STEP,
        state_payload: dict[str, JsonValue],
        action_payloads: dict[str, dict[str, JsonValue]],
        exogenous_inputs: tuple[MechanismExogenousInput, ...] | None = None,
    ) -> Runtime4DomainMechanismStepDraft:
        return Runtime4DomainMechanismStepDraft(
            step_index=step_index,
            state_payload={key: value for key, value in state_payload.items()},
            action_payloads={
                action_id: dict(payload) for action_id, payload in action_payloads.items()
            },
            exogenous_inputs=() if exogenous_inputs is None else exogenous_inputs,
        )

    def call(
        self,
        *,
        pack: DomainPack,
        draft: Runtime4DomainMechanismStepDraft,
        scenario: ScenarioSpec | None = None,
        world_manifest: WorldManifest | None = None,
        campaign: CampaignSpec | None = None,
        campaign_status: CampaignStatus | None = None,
        world: WorldVersion | None = None,
        seed: ScenarioSeed | None = None,
        realization: WorldRealization | None = None,
        policy: AdaptivePolicy | None = None,
        decision_event: AdaptivePolicyDecisionEvent | None = None,
        run_plan: RunPlan | None = None,
        run_status: RunStatus | None = None,
    ) -> Runtime4DomainMechanismStepExecution:
        """Call the bridge; every authority defaults to the fixture value."""
        return execute_runtime4_domain_mechanism_step(
            pack=pack,
            scenario=self.scenario if scenario is None else scenario,
            world_manifest=self.world_manifest if world_manifest is None else world_manifest,
            campaign=self.campaign if campaign is None else campaign,
            campaign_status=self.campaign_status if campaign_status is None else campaign_status,
            world=self.world if world is None else world,
            seed=self.seed if seed is None else seed,
            realization=self.realization if realization is None else realization,
            policy=self.policy if policy is None else policy,
            decision_event=self.decision_event if decision_event is None else decision_event,
            run_plan=self.run_plan if run_plan is None else run_plan,
            run_status=self.run_status if run_status is None else run_status,
            draft=draft,
        )
