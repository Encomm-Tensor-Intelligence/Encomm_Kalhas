"""H29-S05 adversarial tests for the Runtime-4 mechanism-step bridge.

Covers the pure opt-in Runtime-4 -> domain-mechanism binding through the
accepted PAN pack and domain-neutral fake packs:

- successful one-step execution through the accepted PAN v0.1 pack and
  a call-counting fake pack proving exactly one invocation, with the
  full Runtime-4 authority chain sharing the exact PAN pack tenant;
- identical inputs producing byte-identical request/result/binding
  evidence; the complete action-catalogue hash independently
  recomputed; the selected payload coming only from the decision
  event; the configuration coming only from the pack mechanism
  specification; the Runtime-4 tenant carried directly on the request
  and in the deterministic request identifier; and one explicit
  canonical request-identity payload independently reconstructed and
  recomputed by the test;
- every forged, foreign, or malformed authority (catalogue coverage,
  key types, JSON exactness, step indices, runtime version, scenario/
  world/manifest, campaign identity and seed snapshot, campaign status
  identifier/tenant/campaign/state, seed snapshot vs the campaign's
  exact unique seed, coordinated rehashed foreign seed/realization/
  run-plan/run-status attack, realization identity/content/provenance,
  policy identity/content hash, policy action strategy membership,
  decision-event policy/hash/step/action and rule evidence order/roles/
  selected-target agreement, run-plan identifier/input-hash/initial-
  action anchor, run-status identity/state/input-hash/timestamps/event
  hash, exogenous identity/order/value-hash) failing closed before any
  pack invocation;
- authority subclasses, lookalikes, boolean step indices, coercible
  containers, and non-finite/non-exact JSON failing closed;
- caller inputs and pack authorities remaining byte-identical across
  success and failure, with returned evidence never aliasing
  caller-owned containers;
- malformed/forged pack results rejected by the existing dispatcher
  with exactly one call and zero retry, a raising pack step producing
  the dispatcher's typed ``pack_step_raised`` with one call and zero
  retry, and dispatcher preflight reasons/request ids/public messages
  preserved by the bridge unchanged;
- the production module's isolated import surface (no concrete pack,
  no store, no service, no network/filesystem/dynamic import) and the
  unchanged public contract/schema surface (exactly 61 contracts, 61
  schemas, byte-identical generated schema bytes).

All fixtures are deterministic synthetic data. Expected identifiers and
hashes are computed independently in the tests, never via the
production function.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
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
from kalhas.application.adaptive_run_planner import (
    ADAPTIVE_RUNTIME_VERSION,
    adaptive_run_input_hash,
)
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
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
from kalhas.application.run_planner import run_plan_identifier
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
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.adaptive_policy_state import AdaptivePolicyDecisionEvent
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismExogenousInput,
    _is_exact_json_value,
)
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile
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
from kalhas.domain_packs.pan import PanV01DomainPack
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = REPO_ROOT / "kalhas" / "application" / "domain_mechanism_runtime.py"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
# The Runtime-4 authority chain uses the exact PAN pack tenant across the
# entire fixture, so the request tenant authority and the pack tenant
# authority agree by construction.
TENANT = PanV01DomainPack().release_profile.tenant_id
OTHER_TENANT = "tenant-other"
CAMPAIGN = "campaign-1"
SEED_ID = "seed-1"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
RUNTIME_VERSION = "4.0.0"
STEP = 0

#: A PAN-valid complete compartment state (conservation closed).
_PAN_STATE: dict[str, JsonValue] = {
    "population_total": 1000,
    "susceptible": 900,
    "exposed": 40,
    "infectious": 30,
    "hospitalized": 20,
    "intensive_care": 5,
    "recovered": 5,
    "deceased": 0,
}

#: PAN-valid action catalogue payloads within the declared BPS range.
_PAN_CATALOGUE: dict[str, dict[str, JsonValue]] = {
    "act-1": {"intervention_intensity_bps": 0},
    "act-2": {"intervention_intensity_bps": 2000},
}


def _canonical_hash(payload: object) -> str:
    """Canonical SHA-256 of the exact JSON payload value (independent)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _self_hash(model: BaseModel) -> str:
    """Self-covering canonical hash excluding the model's own content_hash."""
    payload = model.model_dump(mode="json")
    del payload["content_hash"]
    return _canonical_hash(payload)


# ---------------------------------------------------------------------------
# Deterministic Runtime-4 environment (real authorities, real decision)
# ---------------------------------------------------------------------------


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


class _Environment:
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
        self.pack: DomainPack = PanV01DomainPack()
        # Deterministic catalogue payloads for the generic fake pack.
        self.state_payload: dict[str, JsonValue] = {"level": 0}
        self.action_catalogue: dict[str, dict[str, JsonValue]] = {
            "act-1": {"intensity": 0},
            "act-2": {"intensity": 1},
        }

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
        state_payload: dict[str, JsonValue] | None = None,
        action_payloads: dict[str, dict[str, JsonValue]] | None = None,
        exogenous_inputs: tuple[MechanismExogenousInput, ...] | None = None,
    ) -> Runtime4DomainMechanismStepDraft:
        effective_state = dict(self.state_payload) if state_payload is None else state_payload
        effective_actions = (
            {action_id: dict(payload) for action_id, payload in self.action_catalogue.items()}
            if action_payloads is None
            else action_payloads
        )
        return Runtime4DomainMechanismStepDraft(
            step_index=step_index,
            state_payload=effective_state,
            action_payloads=effective_actions,
            exogenous_inputs=() if exogenous_inputs is None else exogenous_inputs,
        )

    def call(
        self,
        *,
        pack: DomainPack | None = None,
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
        draft: Runtime4DomainMechanismStepDraft | None = None,
    ) -> Runtime4DomainMechanismStepExecution:
        """Call the bridge; every authority defaults to the fixture value."""
        return execute_runtime4_domain_mechanism_step(
            pack=self.pack if pack is None else pack,
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
            draft=self.draft() if draft is None else draft,
        )


@pytest.fixture()
def env() -> _Environment:
    return _Environment()


def _serializable(value: object) -> object:
    """A JSON-safe snapshot for byte-equality comparisons."""
    if isinstance(value, BaseModel):
        return _serializable(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value


class _CallCountingPack:
    """A conforming DomainPack wrapper counting step delegations.

    Increments ``delegate_calls`` and delegates exactly once to the
    supplied valid underlying pack step, returning its valid result.
    """

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]
    delegate_calls: int
    _delegate: DomainPack

    def __init__(self, delegate: DomainPack) -> None:
        self._delegate = delegate
        self.delegate_calls = 0
        self.manifest = delegate.manifest
        self.release_profile = delegate.release_profile
        self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.delegate_calls += 1
        return self._delegate.step(request)


class _RaisingPack:
    """A conforming DomainPack whose step always raises."""

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def __init__(self) -> None:
        pan = PanV01DomainPack()
        self.manifest = pan.manifest
        self.release_profile = pan.release_profile
        self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        raise RuntimeError("hostile pack step failure")


class _TamperingResultPack:
    """A conforming DomainPack returning a forged result after delegation."""

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]
    delegate_calls: int
    _delegate: DomainPack

    def __init__(self, delegate: DomainPack) -> None:
        self._delegate = delegate
        self.delegate_calls = 0
        self.manifest = delegate.manifest
        self.release_profile = delegate.release_profile
        self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.delegate_calls += 1
        result = self._delegate.step(request)
        forged = result.model_dump(mode="python")
        forged["next_state_hash"] = "0" * 64
        return DomainMechanismStepResult.model_validate(forged)


def _rejects_zero_calls(
    env: _Environment,
    pack: DomainPack,
    *,
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
    draft: Runtime4DomainMechanismStepDraft | None = None,
) -> DomainMechanismDispatchError:
    """Assert one typed rejection with zero pack invocations."""
    counting = _CallCountingPack(pack)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        env.call(
            pack=counting,
            scenario=scenario,
            world_manifest=world_manifest,
            campaign=campaign,
            campaign_status=campaign_status,
            world=world,
            seed=seed,
            realization=realization,
            policy=policy,
            decision_event=decision_event,
            run_plan=run_plan,
            run_status=run_status,
            draft=draft,
        )
    assert counting.delegate_calls == 0
    return excinfo.value


# ---------------------------------------------------------------------------
# Section A: successful execution, exactly-once, determinism
# ---------------------------------------------------------------------------


def test_pan_pack_success_returns_complete_binding_evidence(env: _Environment) -> None:
    """The accepted PAN pack executes one full step with complete evidence."""
    pan = PanV01DomainPack()
    execution = env.call(
        pack=pan,
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert execution.runtime_version == "4.0.0"
    assert execution.run_id == env.run_id
    assert execution.adaptive_policy_identifier == env.policy.identifier
    assert execution.policy_id == env.policy.policy_id
    assert execution.adaptive_policy_content_hash == env.policy.content_hash
    assert execution.decision_event == env.decision_event
    assert execution.selected_action_id == env.decision_event.selected_action_id
    # The request tenant is exactly the verified Runtime-4 tenant, which the
    # whole fixture chain shares with the PAN pack.
    assert execution.request.tenant_id == TENANT
    assert execution.request.tenant_id == pan.release_profile.tenant_id
    assert execution.request.tenant_id == pan.manifest.tenant_id
    assert execution.request.run_id == env.run_id
    assert execution.request.step_index == STEP
    assert execution.result.request_id == execution.request.identifier
    assert execution.action_payload_catalogue_hash == _canonical_hash(_PAN_CATALOGUE)


def test_fake_pack_success_and_exactly_one_invocation(env: _Environment) -> None:
    """A domain-neutral fake pack is invoked exactly once per execution."""
    pack = _CallCountingPack(PanV01DomainPack())
    execution = env.call(
        pack=pack, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    assert pack.delegate_calls == 1
    assert execution.result.request_id == execution.request.identifier


def test_identical_inputs_produce_byte_identical_evidence(env: _Environment) -> None:
    """Repeated execution is fully deterministic at the byte level."""
    first = env.call(
        pack=PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    second = env.call(
        pack=PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert _serializable(first.request) == _serializable(second.request)
    assert _serializable(first.result) == _serializable(second.result)
    assert first.request.identifier == second.request.identifier
    assert first.action_payload_catalogue_hash == second.action_payload_catalogue_hash
    assert _serializable(first.decision_event) == _serializable(second.decision_event)


def _expected_identity_payload(env: _Environment, pan: DomainPack) -> dict[str, object]:
    """Independently reconstruct the complete canonical request-identity payload."""
    catalogue = dict(_PAN_CATALOGUE)
    return {
        "runtime_version": ADAPTIVE_RUNTIME_VERSION,
        "runtime_tenant_id": TENANT,
        "campaign": env.campaign.model_dump(mode="json"),
        "campaign_status": env.campaign_status.model_dump(mode="json"),
        "run_id": env.run_id,
        "run_plan": env.run_plan.model_dump(mode="json"),
        "run_status": env.run_status.model_dump(mode="json"),
        "policy": env.policy.model_dump(mode="json"),
        "decision_event": env.decision_event.model_dump(mode="json"),
        "pack_manifest": pan.manifest.model_dump(mode="json"),
        "release_profile": pan.release_profile.model_dump(mode="json"),
        "mechanism_spec": pan.release_profile.mechanism_spec.model_dump(mode="json"),
        "scenario": env.scenario.model_dump(mode="json"),
        "world": env.world.model_dump(mode="json"),
        "world_manifest": env.world_manifest.model_dump(mode="json"),
        "seed": env.seed.model_dump(mode="json"),
        "realization": env.realization.model_dump(mode="json"),
        "step_index": STEP,
        "state_payload": dict(_PAN_STATE),
        "action_payload_catalogue": catalogue,
        "action_payload_catalogue_hash": _canonical_hash(catalogue),
        "selected_action_id": env.decision_event.selected_action_id,
        "selected_action_payload": catalogue[env.decision_event.selected_action_id],
        "exogenous_inputs": [],
    }


def test_request_identifier_independently_reconstructed(env: _Environment) -> None:
    """The request identifier follows the complete canonical identity payload.

    The test reconstructs the payload and expected identifier without
    calling any production request-identifier helper.
    """
    pan = PanV01DomainPack()
    execution = env.call(
        pack=pan, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    payload = _expected_identity_payload(env, pan)
    expected = "domain-mechanism-step-" + _canonical_hash(payload)[:16]
    assert execution.request.identifier == expected


def test_runtime_tenant_participates_directly_in_identity(env: _Environment) -> None:
    """The Runtime-4 tenant is an explicit canonical identity input."""
    pan = PanV01DomainPack()
    payload = _expected_identity_payload(env, pan)
    foreign = dict(payload)
    foreign["runtime_tenant_id"] = OTHER_TENANT
    assert _canonical_hash(foreign) != _canonical_hash(payload)


def test_campaign_metadata_change_changes_request_identifier(env: _Environment) -> None:
    """A campaign metadata change alters the deterministic request identifier."""
    pan = PanV01DomainPack()
    baseline = env.call(
        pack=pan, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    forged_campaign = env.campaign.model_copy(update={"metadata": {"probe": "changed"}})
    changed = env.call(
        pack=pan,
        campaign=forged_campaign,
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert changed.request.identifier != baseline.request.identifier


def test_campaign_status_changed_at_changes_request_identifier(env: _Environment) -> None:
    """A campaign-status changed_at change alters the request identifier."""
    pan = PanV01DomainPack()
    baseline = env.call(
        pack=pan, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    forged_status = env.campaign_status.model_copy(update={"changed_at": LATER})
    changed = env.call(
        pack=pan,
        campaign_status=forged_status,
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert changed.request.identifier != baseline.request.identifier


def test_coordinated_timestamp_change_changes_request_identifier(env: _Environment) -> None:
    """Coordinated run-plan/run-status timestamp changes alter the identifier."""
    pan = PanV01DomainPack()
    baseline = env.call(
        pack=pan, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    forged_plan = env.run_plan.model_copy(update={"created_at": LATER})
    forged_status = env.run_status.model_copy(update={"created_at": LATER, "changed_at": LATER})
    changed = env.call(
        pack=pan,
        run_plan=forged_plan,
        run_status=forged_status,
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert changed.request.identifier != baseline.request.identifier


def test_selected_payload_comes_only_from_the_decision_event(env: _Environment) -> None:
    """The request action payload equals the selected catalogue entry only."""
    catalogue: dict[str, dict[str, JsonValue]] = {
        "act-1": {"intervention_intensity_bps": 0},
        "act-2": {"intervention_intensity_bps": 4000},
    }
    execution = env.call(
        pack=PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=catalogue),
    )
    selected = env.decision_event.selected_action_id
    assert execution.request.action_payload == catalogue[selected]
    assert execution.request.action_hash == _canonical_hash(execution.request.action_payload)


def test_configuration_comes_only_from_the_pack_mechanism_specification(
    env: _Environment,
) -> None:
    """The request configuration is the pack spec's immutable configuration."""
    pack = PanV01DomainPack()
    execution = env.call(
        pack=pack, draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    )
    spec = pack.release_profile.mechanism_spec
    assert execution.request.configuration_payload == spec.configuration
    assert execution.request.configuration_hash == _canonical_hash(spec.configuration)
    assert execution.request.mechanism_spec_id == spec.identifier
    assert execution.request.mechanism_spec_content_hash == spec.content_hash


# ---------------------------------------------------------------------------
# Section B: caller immutability and no aliasing
# ---------------------------------------------------------------------------


def test_caller_inputs_and_pack_authorities_remain_byte_identical(
    env: _Environment,
) -> None:
    """Success and failure leave every caller input unchanged."""
    pan = PanV01DomainPack()
    manifest_before = copy.deepcopy(_serializable(pan.manifest))
    profile_before = copy.deepcopy(_serializable(pan.release_profile))
    draft = env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE)
    decision_before = copy.deepcopy(_serializable(env.decision_event))
    authorities = (
        env.scenario,
        env.world_manifest,
        env.campaign,
        env.campaign_status,
        env.world,
        env.seed,
        env.realization,
        env.policy,
        env.run_plan,
        env.run_status,
    )
    before = [copy.deepcopy(_serializable(authority)) for authority in authorities]
    env.call(pack=pan, draft=draft)
    assert copy.deepcopy(_serializable(pan.manifest)) == manifest_before
    assert copy.deepcopy(_serializable(pan.release_profile)) == profile_before
    assert copy.deepcopy(_serializable(env.decision_event)) == decision_before
    assert draft.action_payloads == _PAN_CATALOGUE
    after = [_serializable(authority) for authority in authorities]
    assert before == after


def test_returned_evidence_does_not_alias_caller_containers(env: _Environment) -> None:
    """Mutating caller inputs after success never touches the evidence."""
    state_payload: dict[str, JsonValue] = copy.deepcopy(_PAN_STATE)
    action_payloads: dict[str, dict[str, JsonValue]] = copy.deepcopy(_PAN_CATALOGUE)
    execution = env.call(
        pack=PanV01DomainPack(),
        draft=env.draft(state_payload=state_payload, action_payloads=action_payloads),
    )
    request_payload_before = copy.deepcopy(_serializable(execution.request.state_payload))
    catalogue_hash_before = execution.action_payload_catalogue_hash
    state_payload["susceptible"] = 1
    action_payloads["act-1"]["injected"] = True
    assert _serializable(execution.request.state_payload) == request_payload_before
    assert execution.action_payload_catalogue_hash == catalogue_hash_before
    assert "injected" not in execution.request.action_payload


# ---------------------------------------------------------------------------
# Section C: pack and draft structural rejection
# ---------------------------------------------------------------------------


def test_cross_tenant_pack_rejected_with_zero_pack_calls(env: _Environment) -> None:
    """A pack whose tenant disagrees with Runtime-4 fails before any step."""

    class _ForeignTenantPack:
        manifest: DomainPackManifest
        release_profile: ModelPackReleaseProfile
        mechanism_protocol_version: Literal["1.0.0"]

        def __init__(self) -> None:
            pan = PanV01DomainPack()
            self.manifest = pan.manifest.model_copy(update={"tenant_id": OTHER_TENANT})
            self.release_profile = pan.release_profile.model_copy(
                update={"tenant_id": OTHER_TENANT}
            )
            self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

        def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
            raise AssertionError("pack.step must never run for a foreign tenant")

    error = _rejects_zero_calls(env, _ForeignTenantPack())
    assert error.reason == "pack_tenant_agreement"


def test_missing_and_extra_action_catalogue_keys_rejected(env: _Environment) -> None:
    """Missing or extra action-catalogue keys fail closed."""
    missing = {key: value for key, value in _PAN_CATALOGUE.items() if key != "act-2"}
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=missing),
    )
    assert error.reason == "draft_action_catalogue_coverage"
    extra = dict(_PAN_CATALOGUE)
    extra["act-3"] = {"intervention_intensity_bps": 0}
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=extra),
    )
    assert error.reason == "draft_action_catalogue_coverage"


def test_str_subclass_catalogue_keys_rejected(env: _Environment) -> None:
    """A str subclass used as an outer catalogue key fails closed."""

    class _StrSubclass(str):
        pass

    forged: dict[str, dict[str, JsonValue]] = dict(_PAN_CATALOGUE)
    forged[_StrSubclass("act-1")] = forged.pop("act-1")
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=forged),
    )
    assert error.reason == "draft_action_catalogue_key_type"


def test_subclass_and_non_json_catalogue_values_rejected(env: _Environment) -> None:
    """Dict/list/numeric subclasses and non-finite or non-JSON values fail."""

    class _DictSubclass(dict[str, JsonValue]):
        pass

    class _IntSubclass(int):
        pass

    class _ListSubclass(list[object]):
        pass

    dict_payload: dict[str, dict[str, JsonValue]] = {
        key: cast(dict[str, JsonValue], _DictSubclass(value))
        for key, value in _PAN_CATALOGUE.items()
    }
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=dict_payload),
    )
    assert error.reason == "draft_action_payload_type"

    list_payload: dict[str, dict[str, JsonValue]] = {
        "act-1": cast(dict[str, JsonValue], _ListSubclass()),
        "act-2": dict(_PAN_CATALOGUE["act-2"]),
    }
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=list_payload),
    )
    assert error.reason == "draft_action_payload_type"

    numeric_payload: dict[str, dict[str, JsonValue]] = {
        "act-1": {"intervention_intensity_bps": _IntSubclass(1000)},
        "act-2": dict(_PAN_CATALOGUE["act-2"]),
    }
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=numeric_payload),
    )
    assert error.reason == "draft_action_payload_json"

    non_finite_payload: dict[str, dict[str, JsonValue]] = {
        "act-1": {"intervention_intensity_bps": float("nan")},
        "act-2": dict(_PAN_CATALOGUE["act-2"]),
    }
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=non_finite_payload),
    )
    assert error.reason == "draft_action_payload_json"

    tuple_payload: dict[str, dict[str, JsonValue]] = {
        "act-1": cast(dict[str, JsonValue], {"intervention_intensity_bps": (1, 2)}),
        "act-2": dict(_PAN_CATALOGUE["act-2"]),
    }
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=tuple_payload),
    )
    assert error.reason == "draft_action_payload_json"

    assert not _is_exact_json_value((1, 2))
    assert not _is_exact_json_value(float("nan"))
    assert not _is_exact_json_value(_IntSubclass(1))


def test_boolean_negative_and_coercible_step_indices_rejected(env: _Environment) -> None:
    """Boolean, negative, and coercible-but-wrong step indices fail closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(step_index=True, state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert error.reason == "draft_step_index"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(step_index=-1, state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert error.reason == "draft_step_index"
    string_index = Runtime4DomainMechanismStepDraft(
        step_index=cast(int, "1"),
        state_payload=dict(_PAN_STATE),
        action_payloads=dict(_PAN_CATALOGUE),
        exogenous_inputs=(),
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), draft=string_index)
    assert error.reason == "draft_step_index"
    float_index = Runtime4DomainMechanismStepDraft(
        step_index=cast(int, 1.5),
        state_payload=dict(_PAN_STATE),
        action_payloads=dict(_PAN_CATALOGUE),
        exogenous_inputs=(),
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), draft=float_index)
    assert error.reason == "draft_step_index"


# ---------------------------------------------------------------------------
# Section D: authority forgery rejection
# ---------------------------------------------------------------------------


def test_wrong_runtime_version_on_policy_decision_run_plan_run_status(
    env: _Environment,
) -> None:
    """A forged historical runtime literal fails closed on every surface."""
    error = _rejects_zero_calls(
        env, PanV01DomainPack(), policy=env.policy.model_copy(update={"runtime_version": "1.0.0"})
    )
    assert error.reason == "policy_runtime_version"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(update={"runtime_version": "1.0.0"}),
    )
    assert error.reason == "decision_event_runtime_version"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_plan=env.run_plan.model_copy(update={"runtime_version": "1.0.0"}),
    )
    assert error.reason == "run_plan_runtime_version"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"runtime_version": "1.0.0"}),
    )
    assert error.reason == "run_status_runtime_version"


def test_forged_scenario_rejected(env: _Environment) -> None:
    """A foreign scenario identity or tenant fails closed."""
    forged = env.scenario.model_copy(update={"tenant_id": OTHER_TENANT})
    error = _rejects_zero_calls(env, PanV01DomainPack(), scenario=forged)
    assert error.reason == "scenario_tenant"
    forged = env.scenario.model_copy(update={"identifier": "scenario-forged"})
    error = _rejects_zero_calls(env, PanV01DomainPack(), scenario=forged)
    assert error.reason == "scenario_world_source_identity"


def test_forged_world_or_world_manifest_rejected(env: _Environment) -> None:
    """A forged world content hash or manifest identity fails closed."""
    forged_world = env.world.model_copy(update={"content_hash": "f" * 64})
    error = _rejects_zero_calls(env, PanV01DomainPack(), world=forged_world)
    assert error.reason == "world_snapshot_verification"
    forged_manifest = env.world_manifest.model_copy(update={"identifier": "manifest-forged"})
    error = _rejects_zero_calls(env, PanV01DomainPack(), world_manifest=forged_manifest)
    assert error.reason == "world_snapshot_verification"


def test_forged_campaign_identity_or_binding_rejected(env: _Environment) -> None:
    """A forged campaign tenant/scenario/world/seed binding fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign=env.campaign.model_copy(
            update={
                "tenant_id": OTHER_TENANT,
                # Keep the campaign contract-revalidatable: its seed ensemble
                # must carry the campaign tenant.
                "seed_ensemble": (env.seed.model_copy(update={"tenant_id": OTHER_TENANT}),),
            }
        ),
    )
    assert error.reason == "campaign_tenant"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign=env.campaign.model_copy(update={"scenario_id": "scenario-forged"}),
    )
    assert error.reason == "campaign_scenario"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign=env.campaign.model_copy(update={"world_version_id": "world-forged"}),
    )
    assert error.reason == "campaign_world"
    foreign_seed = ScenarioSeed(
        identifier="seed-foreign", tenant_id=TENANT, algorithm="deterministic", seed_value="foreign"
    )
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign=env.campaign.model_copy(update={"seed_ensemble": (foreign_seed,)}),
    )
    assert error.reason == "campaign_seed_membership"


def test_forged_campaign_status_rejected(env: _Environment) -> None:
    """A forged campaign-status identifier/tenant/campaign/state fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign_status=env.campaign_status.model_copy(update={"identifier": "status-forged"}),
    )
    assert error.reason == "campaign_status_identifier"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign_status=env.campaign_status.model_copy(update={"tenant_id": OTHER_TENANT}),
    )
    assert error.reason == "campaign_status_tenant"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign_status=env.campaign_status.model_copy(update={"campaign_id": "campaign-forged"}),
    )
    assert error.reason == "campaign_status_identity"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        campaign_status=env.campaign_status.model_copy(update={"state": CampaignState.DRAFT}),
    )
    assert error.reason == "campaign_status_state"


def test_supplied_seed_differing_from_campaign_snapshot_rejected(env: _Environment) -> None:
    """A same-identifier seed with different content than the campaign snapshot fails."""
    forged_seed = env.seed.model_copy(update={"seed_value": "forged"})
    assert forged_seed.identifier == env.seed.identifier
    error = _rejects_zero_calls(env, PanV01DomainPack(), seed=forged_seed)
    assert error.reason == "campaign_seed_snapshot"


def test_coordinated_rehashed_foreign_seed_attack_rejected(env: _Environment) -> None:
    """Rehashing a foreign seed/realization/run-plan/run-status cannot bypass the snapshot."""
    forged_seed = env.seed.model_copy(update={"seed_value": "forged"})
    catalog = extract_world_catalog(env.world)
    forged_realization = build_world_realization(
        world=env.world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
        seed=forged_seed,
        realized_at=NOW,
    )
    forged_input_hash = adaptive_run_input_hash(
        runtime_version=ADAPTIVE_RUNTIME_VERSION,
        world_content_hash=env.world.content_hash,
        policy=env.policy,
        seed=forged_seed,
        world_realization_content_hash=forged_realization.content_hash,
    )
    forged_plan = env.run_plan.model_copy(update={"input_hash": forged_input_hash})
    forged_status = env.run_status.model_copy(update={"input_hash": forged_input_hash})
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        seed=forged_seed,
        realization=forged_realization,
        run_plan=forged_plan,
        run_status=forged_status,
    )
    assert error.reason == "campaign_seed_snapshot"


def test_forged_realization_rejected(env: _Environment) -> None:
    """A forged realization identifier/content hash fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        realization=env.realization.model_copy(update={"identifier": "realization-forged"}),
    )
    assert error.reason == "realization_identifier"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        realization=env.realization.model_copy(update={"content_hash": "f" * 64}),
    )
    assert error.reason == "realization_content_hash"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        realization=env.realization.model_copy(update={"scenario_seed_id": "seed-foreign"}),
    )
    assert error.reason == "realization_identity"


def test_forged_policy_identifier_or_content_hash_rejected(env: _Environment) -> None:
    """A forged policy identifier or content hash fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        policy=env.policy.model_copy(update={"identifier": "policy-forged"}),
    )
    assert error.reason == "policy_identity"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        policy=env.policy.model_copy(update={"content_hash": "f" * 64}),
    )
    assert error.reason == "policy_identity"


def test_policy_action_strategy_not_in_campaign_rejected(env: _Environment) -> None:
    """A policy action bound to a foreign strategy candidate fails closed."""
    actions = list(env.policy.actions)
    forged_action = actions[1].model_copy(update={"strategy_candidate_id": "mock-foreign"})
    forged_policy = env.policy.model_copy(update={"actions": (actions[0], forged_action)})
    recomputed = forged_policy.model_dump(mode="json")
    del recomputed["content_hash"]
    forged_policy = forged_policy.model_copy(update={"content_hash": _canonical_hash(recomputed)})
    assert "mock-foreign" not in set(env.campaign.strategy_candidate_ids)
    error = _rejects_zero_calls(env, PanV01DomainPack(), policy=forged_policy)
    assert error.reason == "policy_strategy_membership"


def test_forged_decision_event_policy_hash_step_action_rejected(env: _Environment) -> None:
    """A forged decision policy/hash/step/action binding fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(update={"policy_id": "policy-forged"}),
    )
    assert error.reason == "decision_event_policy_identity"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(update={"policy_content_hash": "f" * 64}),
    )
    assert error.reason == "decision_event_policy_identity"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(update={"decision_step": 1}),
    )
    assert error.reason == "decision_event_step_binding"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(
            update={"current_action_id": "act-foreign", "action_changed": True}
        ),
    )
    assert error.reason == "decision_event_action_membership"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        decision_event=env.decision_event.model_copy(
            update={"selected_action_id": "act-foreign", "action_changed": True}
        ),
    )
    assert error.reason == "decision_event_action_membership"


def _rule_evidence(
    rule: str, role: str, matched: bool, blocked: str | None = None
) -> tuple[str, str, bool, str | None]:
    return (rule, role, matched, blocked)


def test_forged_decision_evidence_order_role_target_rejected(env: _Environment) -> None:
    """Unknown, reordered, wrong-role, and target-disagreeing evidence fails."""
    # Unknown rule id in the evaluated prefix.
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (_rule_evidence("ghost-rule", "enter", False),),
            "decision_kind": "fallback",
            "selected_rule_id": None,
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), decision_event=forged)
    assert error.reason == "decision_event_evidence_order"

    # Reordered evidence (rule-2 before rule-1) with a contract-valid rule kind.
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (
                _rule_evidence("rule-2", "retain", True),
                _rule_evidence("rule-1", "enter", True),
            ),
            "selected_rule_id": "rule-1",
            "selected_action_id": "act-2",
            "action_changed": True,
            "decision_kind": "rule",
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), decision_event=forged)
    assert error.reason == "decision_event_evidence_order"

    # Wrong role: rule-1 targets act-2 while the current action is act-1,
    # so its recorded role must be "enter", not "retain".
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (_rule_evidence("rule-1", "retain", True),),
            "selected_rule_id": "rule-1",
            "selected_action_id": "act-2",
            "action_changed": True,
            "decision_kind": "rule",
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), decision_event=forged)
    assert error.reason == "decision_event_evidence_role"

    # Selected rule targets act-1 but the selected action is forged to
    # act-2; the evidence keeps the exact policy prefix so only the
    # selected-target agreement can catch it.
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (
                _rule_evidence("rule-1", "enter", False),
                _rule_evidence("rule-2", "retain", True),
            ),
            "selected_rule_id": "rule-2",
            "selected_action_id": "act-2",
            "action_changed": True,
            "decision_kind": "rule",
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), decision_event=forged)
    assert error.reason == "decision_event_selected_target"

    # Ordinary fallback deciding an action other than the policy fallback.
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (),
            "selected_rule_id": None,
            "selected_action_id": "act-1",
            "action_changed": False,
            "decision_kind": "fallback",
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), decision_event=forged)
    assert error.reason == "decision_event_fallback_action"


def test_blocked_fallback_current_action_semantics_preserved(env: _Environment) -> None:
    """A blocked-fallback decision retains the current action and succeeds."""
    forged = env.decision_event.model_copy(
        update={
            "rule_evaluation_evidence": (
                _rule_evidence("rule-1", "enter", False),
                _rule_evidence("rule-2", "retain", True),
            ),
            "selected_rule_id": None,
            "selected_action_id": "act-1",
            "action_changed": False,
            "decision_kind": "blocked_fallback",
            "fallback_blocked_reason": "minimum_dwell",
        }
    )
    execution = env.call(
        pack=PanV01DomainPack(),
        decision_event=forged,
        draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
    )
    assert execution.selected_action_id == "act-1"


def test_forged_run_plan_rejected(env: _Environment) -> None:
    """A forged run-plan identifier/input hash/anchor fails closed."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_plan=env.run_plan.model_copy(update={"identifier": "plan-forged"}),
    )
    assert error.reason == "run_plan_identifier"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_plan=env.run_plan.model_copy(update={"input_hash": "f" * 64}),
    )
    assert error.reason == "run_plan_input_hash"
    # A coordinated forged strategy/anchor with a recomputed identifier:
    # only the initial-action anchor check can catch it.
    forged_plan = env.run_plan.model_copy(
        update={
            "strategy_candidate_id": "mock-balanced",
            "identifier": run_plan_identifier(
                campaign_id=env.campaign.identifier,
                world_version_id=env.world.identifier,
                strategy_candidate_id="mock-balanced",
                scenario_seed_id=SEED_ID,
                runtime_version=RUNTIME_VERSION,
            ),
        }
    )
    error = _rejects_zero_calls(env, PanV01DomainPack(), run_plan=forged_plan)
    assert error.reason == "run_plan_initial_action_anchor"


def test_forged_run_status_rejected(env: _Environment) -> None:
    """A forged run-status identifier/state/input hash/timestamps/event hash fails."""
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"identifier": "status-forged"}),
    )
    assert error.reason == "run_status_identifier"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"state": RunState.COMPLETE}),
    )
    assert error.reason == "run_status_state"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"input_hash": "f" * 64}),
    )
    assert error.reason == "run_status_identity"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"created_at": LATER}),
    )
    assert error.reason == "run_status_timestamps"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"changed_at": LATER}),
    )
    assert error.reason == "run_status_timestamps"
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        run_status=env.run_status.model_copy(update={"event_hash": "f" * 64}),
    )
    assert error.reason == "run_status_state"


def _exogenous_entry(
    env: _Environment,
    *,
    identifier: str,
    stream: str = "s-1",
    variable: str = "v-1",
    entity_id: str | None = "e-1",
    slot_id: str | None = None,
    draw_index: int = 0,
    value: int = 1,
    kind: Literal["integer", "number"] = "integer",
    content_hash: str | None = None,
    world_version_id: str | None = None,
    world_content_hash: str | None = None,
    seed_id: str | None = None,
    seed_content_hash_value: str | None = None,
    realization_id: str | None = None,
    realization_content_hash: str | None = None,
    run_id: str | None = None,
    step_index: int | None = None,
) -> MechanismExogenousInput:
    return MechanismExogenousInput(
        identifier=identifier,
        stream=stream,
        variable=variable,
        entity_id=entity_id,
        slot_id=slot_id,
        draw_index=draw_index,
        value_kind=kind,
        value=value,
        content_hash=(_canonical_hash(value) if content_hash is None else content_hash),
        world_version_id=env.world.identifier if world_version_id is None else world_version_id,
        world_content_hash=(
            env.world.content_hash if world_content_hash is None else world_content_hash
        ),
        seed_id=SEED_ID if seed_id is None else seed_id,
        seed_content_hash=(
            seed_content_hash(env.seed)
            if seed_content_hash_value is None
            else seed_content_hash_value
        ),
        realization_id=(env.realization.identifier if realization_id is None else realization_id),
        realization_content_hash=(
            env.realization.content_hash
            if realization_content_hash is None
            else realization_content_hash
        ),
        run_id=env.run_id if run_id is None else run_id,
        step_index=STEP if step_index is None else step_index,
    )


def test_foreign_malformed_wrongly_ordered_or_wrongly_hashed_exogenous_rejected(
    env: _Environment,
) -> None:
    """Foreign, malformed, wrongly ordered, or wrongly hashed exogenous inputs fail."""
    foreign_world = _exogenous_entry(env, identifier="x-1", world_version_id="world-foreign")
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(
            state_payload=_PAN_STATE,
            action_payloads=_PAN_CATALOGUE,
            exogenous_inputs=(foreign_world,),
        ),
    )
    assert error.reason == "exogenous_identity"

    wrong_hash = _exogenous_entry(env, identifier="x-2", content_hash="f" * 64)
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(
            state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE, exogenous_inputs=(wrong_hash,)
        ),
    )
    assert error.reason == "exogenous_value_hash"

    first = _exogenous_entry(env, identifier="x-3", stream="s-2", variable="v-1")
    second = _exogenous_entry(env, identifier="x-4", stream="s-1", variable="v-1")
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(
            state_payload=_PAN_STATE,
            action_payloads=_PAN_CATALOGUE,
            exogenous_inputs=(first, second),
        ),
    )
    assert error.reason == "exogenous_order"

    class _EvilEntry(MechanismExogenousInput):
        pass

    base = _exogenous_entry(env, identifier="x-5")
    malformed = _EvilEntry.model_validate(base.model_dump(mode="python"), strict=False)
    error = _rejects_zero_calls(
        env,
        PanV01DomainPack(),
        draft=env.draft(
            state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE, exogenous_inputs=(malformed,)
        ),
    )
    assert error.reason == "draft_exogenous_entry_type"


# ---------------------------------------------------------------------------
# Section E: exactly-once dispatch through the existing seam
# ---------------------------------------------------------------------------


def test_malformed_pack_result_one_call_zero_retry(env: _Environment) -> None:
    """A forged pack result is rejected after exactly one invocation."""
    pack = _TamperingResultPack(PanV01DomainPack())
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        env.call(
            pack=pack,
            draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
        )
    assert pack.delegate_calls == 1
    assert excinfo.value.reason == "result_next_state_hash"


def test_pack_step_raises_typed_error_one_call_zero_retry(env: _Environment) -> None:
    """A raising pack step becomes the dispatcher's typed error, one call, no retry."""
    counting = _CallCountingPack(_RaisingPack())
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        env.call(
            pack=counting,
            draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
        )
    assert counting.delegate_calls == 1
    assert excinfo.value.reason == "pack_step_raised"
    assert not isinstance(excinfo.value, RuntimeError)


def test_dispatcher_preflight_error_preserved_by_bridge(env: _Environment) -> None:
    """A dispatcher preflight reason/request id/public message survives the bridge."""

    class _ForgedManifestPack:
        manifest: DomainPackManifest
        release_profile: ModelPackReleaseProfile
        mechanism_protocol_version: Literal["1.0.0"]

        def __init__(self) -> None:
            pan = PanV01DomainPack()
            self.manifest = pan.manifest.model_copy(update={"content_hash": "f" * 64})
            self.release_profile = pan.release_profile
            self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

        def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
            raise AssertionError("pack.step must never run after a preflight failure")

    counting = _CallCountingPack(_ForgedManifestPack())
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        env.call(
            pack=counting,
            draft=env.draft(state_payload=_PAN_STATE, action_payloads=_PAN_CATALOGUE),
        )
    assert counting.delegate_calls == 0
    error = excinfo.value
    assert error.reason == "manifest_content_hash"
    assert (
        str(error) == "Domain mechanism step dispatch failed verification and was rejected; "
        "no result was produced and no authority state changed"
    )
    assert error.request_id is None


# ---------------------------------------------------------------------------
# Section F: production surface isolation and registry/schema parity
# ---------------------------------------------------------------------------


def test_production_module_forbidden_surface_scan() -> None:
    """The bridge imports no concrete pack, store, service, or IO surface."""
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_roots: list[str] = []
    simple_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            simple_names.extend(alias.name for alias in node.names)
            import_roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            simple_names.append(node.module)
            import_roots.append(node.module.split(".")[0])
    forbidden_roots = {
        "os",
        "sys",
        "json",
        "re",
        "ast",
        "subprocess",
        "socket",
        "pathlib",
        "importlib",
        "random",
        "uuid",
        "datetime",
        "time",
        "requests",
        "urllib",
        "httpx",
        "http",
        "pandas",
        "numpy",
    }
    for root in import_roots:
        assert root not in forbidden_roots, f"forbidden import root: {root}"
    # No concrete pack, store, service, network, or historical runtime module:
    # the kalhas import set is exactly the verified bridge allowlist below.
    joined = "\n".join(simple_names).lower()
    for token in ("pan", "nexus", "legion", "store"):
        assert re.search(rf"(^|\.){token}($|\.)", joined) is None, f"forbidden import name: {token}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            assert name not in ("open", "eval", "exec", "compile", "__import__"), name
        if isinstance(node, ast.Attribute):
            attribute_root = node.value
            while isinstance(attribute_root, ast.Attribute):
                attribute_root = attribute_root.value
            if isinstance(attribute_root, ast.Name):
                assert attribute_root.id not in (
                    "os",
                    "sys",
                    "socket",
                    "subprocess",
                    "pathlib",
                    "importlib",
                    "random",
                    "uuid",
                    "time",
                ), attribute_root.id
    app_imports = {name for name in simple_names if name.startswith("kalhas.")}
    assert app_imports == {
        "kalhas.application.adaptive_policy_identity",
        "kalhas.application.adaptive_run_planner",
        "kalhas.application.domain_mechanism_dispatcher",
        "kalhas.application.domain_mechanism_errors",
        "kalhas.application.hashing",
        "kalhas.application.objective_evaluation_identity",
        "kalhas.application.realization_identity",
        "kalhas.application.run_planner",
        "kalhas.application.world_integrity",
        "kalhas.application.world_uncertainty_identity",
        "kalhas.contracts.v1.adaptive_policy",
        "kalhas.contracts.v1.adaptive_policy_state",
        "kalhas.contracts.v1.campaign",
        "kalhas.contracts.v1.domain_mechanism",
        "kalhas.contracts.v1.execution",
        "kalhas.contracts.v1.run_plan",
        "kalhas.contracts.v1.scenario",
        "kalhas.contracts.v1.shared",
        "kalhas.contracts.v1.world",
        "kalhas.contracts.v1.world_realization",
        "kalhas.domain_packs",
    }


def test_registry_and_schema_counts_and_bytes_unchanged() -> None:
    """Public contract and generated schema surfaces stay 61/61 and byte-identical."""
    assert len(PUBLIC_CONTRACTS) == 61
    generated = generate_schemas()
    assert len(generated) == 61
    on_disk = {path.name: path.read_bytes() for path in sorted(SCHEMA_DIR.glob("*.schema.json"))}
    assert len(on_disk) == len(generated)
    assert set(on_disk) == set(generated)
    for name, content in generated.items():
        # Normalize newlines so a CRLF checkout still proves byte-identical
        # content modulo the repository's EOL normalization.
        normalized = on_disk[name].replace(b"\r\n", b"\n")
        assert normalized == content.encode("utf-8")


def test_historical_runtime_surfaces_not_imported(env: _Environment) -> None:
    """The bridge never imports historical Runtime services or stores."""
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "adaptive_run_execution_service",
        "adaptive_static_comparison_runtime",
        "structural_runtime",
        "replay_service",
        "in_memory_store",
        "campaign_trajectory_runtime",
        "strategy_trajectory_service",
    ):
        assert forbidden not in source


def test_module_declared_surface_exact(env: _Environment) -> None:
    """The bridge exports exactly its three public names."""
    import kalhas.application.domain_mechanism_runtime as runtime_module

    assert runtime_module.__all__ == [
        "Runtime4DomainMechanismStepDraft",
        "Runtime4DomainMechanismStepExecution",
        "execute_runtime4_domain_mechanism_step",
    ]
    # No ``Any`` in the executable surface: strip docstrings (which may
    # name the token in prose) and scan only code.
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    code_only = "\n".join(source.split('"""')[::2])
    assert "Any" not in code_only
