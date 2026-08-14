"""Shared helpers for Phase 25 runtime-3 preparation/preflight and lifecycle tests.

Builds runtime-3.0.0 prepared campaigns through the real Phase 25
preparation service, the transition-capable execution fixture used by
the lifecycle tests, and exposes the private test seam used to simulate
corrupted recorded unsupported-runtime state (an explicit non-application
path documented at the helper).
"""

from __future__ import annotations

from unittest.mock import patch

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application import realization_campaign_service
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import (
    declare_transition,
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    prepare_realization_campaign,
)
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.strategy import (
    PolicyDeclaration,
    PolicyRule,
    StrategyCandidate,
    StrategyRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    UniformDistribution,
)

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import (
    DECLARED_AT,
    _register_pack,
    build_observation_scenario,
)
from tests.phase24_helpers import (
    build_uncertainty_store,
    declare_model,
    uncertainty_fields,
)

RUNTIME_THREE_SEEDS = (
    build_seed(identifier="seed-1"),
    build_seed(identifier="seed-2"),
)

#: One deterministic level-independent transition of sm-1 (status idle ->
#: active); the canonical LEGION draft applies it on every run.
_TRANSITION_ID = "t-1"
_TRANSITION_GUARD: dict[str, JsonValue] = {"status": "idle"}
_TRANSITION_TARGET: dict[str, JsonValue] = {"status": "active"}


def level_binding() -> UncertaintyBindingDraft:
    """One uniform(0, 3) nearest-ties-to-even binding on the integer level field."""
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id="level",
        distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy="nearest_ties_to_even",
    )


def runtime_three_store(*, with_model: bool = True) -> InMemoryScenarioStore:
    """A store with a compiled world and a runtime-3.0.0 prepared campaign.

    The campaign is prepared through the real
    ``prepare_realization_campaign`` service (the Phase 25 preparation
    seam) with the mock LEGION ensemble (five deterministic strategy
    candidates) and two seeds, so the stored records are exactly what
    production writes.
    """
    store = build_uncertainty_store()
    if with_model:
        declare_model(store, bindings=(level_binding(),))
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    return store


def runtime_three_execution_store() -> InMemoryScenarioStore:
    """A RUNNING runtime-3 campaign with one transition-capable model.

    The world embeds sm-1 (level/ratio/status) plus one deterministic
    level-independent transition (status idle -> active), prepared
    through the real preparation and trajectory-plan services with the
    canonical LEGION drafts and started through the real campaign-start
    seam: every stored run is PLANNED and the campaign is RUNNING, so
    ``execute_realization_campaign`` can preflight and execute all ten
    runs (five strategies x two seeds) with non-empty realization
    execution artifacts. Fully deterministic and domain-neutral.
    """
    store = build_uncertainty_store()
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id=_TRANSITION_ID,
        ),
        tenant_id=state_model.tenant_id,
        scenario_id=state_model.scenario_id,
        binding_id=state_model.binding_id,
        manifest_id=state_model.manifest_id,
        pack_id=state_model.pack_id,
        pack_version=state_model.pack_version,
        manifest_content_hash=state_model.manifest_content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=_TRANSITION_ID,
        description="Declared state change",
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three execution campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    return store


def runtime_three_observation_store(
    *,
    seeds: tuple[ScenarioSeed, ScenarioSeed] | None = None,
) -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign with observation bindings.

    The scenario declares metrics m-1 (unit ``units``) and m-2 (unit
    ``percent``); the world embeds observation bindings m-1 -> level and
    m-2 -> ratio, the uncertainty model on level, and one deterministic
    level-independent transition (status idle -> active) that leaves the
    realized level untouched in the final state. After real preparation,
    trajectory-plan preparation, start, and full campaign execution every
    run is COMPLETE with a stored realization execution, so metric
    observations can be extracted directly. Fully deterministic and
    domain-neutral.
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
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-2",
        state_field_id="ratio",
        declared_at=DECLARED_AT,
    )
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id=_TRANSITION_ID,
        ),
        tenant_id=state_model.tenant_id,
        scenario_id=state_model.scenario_id,
        binding_id=state_model.binding_id,
        manifest_id=state_model.manifest_id,
        pack_id=state_model.pack_id,
        pack_version=state_model.pack_version,
        manifest_content_hash=state_model.manifest_content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=_TRANSITION_ID,
        description="Declared state change",
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three observation campaign",
        seed_ensemble=seeds if seeds is not None else RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    return store


def inject_unsupported_recorded_runtime(
    store: InMemoryScenarioStore,
    *,
    campaign_id: str,
    plan: RunPlan,
    unsupported_version: str = "9.9.9",
) -> str:
    """Simulate corrupted recorded state through private test seams.

    This is deliberately **not** an application preparation path: a run
    prepared as runtime 2.0.0 is re-stamped with an unsupported recorded
    runtime in both its stored ``RunPlan`` and its matching ``RunStatus``,
    keeping every field unrelated to the version mutually consistent.
    Downstream services must reject the run with the typed
    unsupported-runtime error exactly as they would reject externally
    corrupted or foreign recorded state.
    """
    run_id = run_identifier(plan)
    tampered_plan = plan.model_copy(update={"runtime_version": unsupported_version})
    stored_plans = store.get_run_plans(TENANT, campaign_id)
    store._run_plans[(TENANT, campaign_id)] = tuple(
        tampered_plan if candidate.identifier == plan.identifier else candidate
        for candidate in stored_plans
    )
    status = store.get_run_status(TENANT, run_id)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"runtime_version": unsupported_version}),
    )
    return run_id


# ---------------------------------------------------------------------------
# Causal 84/103 acceptance fixture (runtime 3.0.0, end to end)
# ---------------------------------------------------------------------------
#
# Deterministic causal scenario: a discrete uncertainty binding on the
# integer "level" field with exactly two support values (branch X = 5,
# branch Y = 9). Two declared guarded transitions causally change the
# observed field: t-x (guard level == 5) sets level to 84; t-y (guard
# level == 9) sets level to 103. Every final 84/103 value is produced by
# the real state-transition engine through the real lifecycle - never
# copied into expected artifacts.

ACCEPTANCE_BRANCH_X = 5
ACCEPTANCE_BRANCH_Y = 9
ACCEPTANCE_VALUE_X = 84
ACCEPTANCE_VALUE_Y = 103

#: Fixed deterministic seeds, proven by the acceptance fixture itself
#: (test_seed_branch_selection_proven) to select branch X (realized
#: level == 5) and branch Y (realized level == 9) under the fixture's
#: discrete uncertainty binding. No randomness and no retry-until-
#: different behavior exists anywhere in the fixture.
ACCEPTANCE_SEEDS: tuple[ScenarioSeed, ScenarioSeed] = (
    build_seed(identifier="seed-0"),
    build_seed(identifier="seed-2"),
)

#: Declared trajectory sequences through the fail-closed mock
#: declaration seam: strategy mock-a proposes X-then-Y and strategy
#: mock-b proposes Y-then-X - two genuinely different authoritative
#: transition-reference orders.
ACCEPTANCE_DECLARED_SEQUENCES: dict[str, tuple[str, ...]] = {
    "mock-a": ("t-x", "t-y"),
    "mock-b": ("t-y", "t-x"),
}


class AcceptanceLegionAdapter(MockLegionAdapter):
    """Test-only LEGION boundary restricted to exactly two candidates.

    ``request_strategies`` returns exactly two deterministic,
    domain-neutral strategy candidates (``mock-a`` and ``mock-b``) with
    identical ordered observation permissions, so a prepared campaign
    holds exactly two strategies and exactly four run plans (2 x 2).
    ``request_trajectory_plan`` is the real fail-closed declaration
    resolution inherited unchanged from ``MockLegionAdapter``.
    """

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        observations = list(request.required_observations)
        return tuple(
            StrategyCandidate(
                identifier=f"mock-{label}",
                tenant_id=request.tenant_id,
                strategy_version="1.0.0",
                policy=PolicyDeclaration(
                    summary=f"Declared mock policy: {label}",
                    rules=[
                        PolicyRule(
                            identifier=f"mock-{label}-rule-1",
                            statement="Declared mock rule",
                            parameters={"aggressiveness": 0.5},
                        )
                    ],
                ),
                required_observations=observations,
                assumptions=[],
            )
            for label in ("a", "b")
        )


def acceptance_legion() -> AcceptanceLegionAdapter:
    """The acceptance LEGION boundary with the declared X/Y sequences."""
    return AcceptanceLegionAdapter(declared_transition_sequences=ACCEPTANCE_DECLARED_SEQUENCES)


def acceptance_fixture_store() -> InMemoryScenarioStore:
    """A store with every acceptance declaration, before world compilation.

    Registers the observation scenario (metrics m-1/m-2/m-3, units for
    m-1/m-2), the generic pack binding, state model sm-1
    (level/ratio/status), the two guarded causal transitions t-x and
    t-y, the single metric-observation binding m-1 -> level, and the
    discrete uncertainty model (values [5, 9], equal weights,
    nearest-ties-to-even rounding for the integer target) - all through
    the real declaration services.
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
    return store


def acceptance_campaign_store() -> InMemoryScenarioStore:
    """A COMPILED runtime-3 acceptance campaign with exactly two strategies.

    Compiles the acceptance world through the real mock-NEXUS
    compilation path and prepares the runtime-3.0.0 campaign through the
    real ``prepare_realization_campaign`` service with the test-only
    two-candidate ``AcceptanceLegionAdapter``. The preparation service
    enforces its expected candidate-count contract
    (``EXPECTED_STRATEGY_SET_SIZE``); the count expectation is aligned
    to the sanctioned two-candidate adapter for the duration of the
    preparation call only - the single explicit seam of the fixture. No
    final state, observation, execution, realization, hash, or matrix is
    ever patched or injected, and nothing else is monkeypatched.
    """
    store = acceptance_fixture_store()
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
            campaign_name="Acceptance campaign",
            seed_ensemble=ACCEPTANCE_SEEDS,
            created_at=NOW,
        )
    return store


def acceptance_execution_store() -> InMemoryScenarioStore:
    """A RUNNING runtime-3 acceptance campaign with declared plans prepared.

    Prepares the two strategy trajectory plans through the real
    trajectory-plan service with the declaration-carrying acceptance
    LEGION boundary (strategy mock-a: [t-x, t-y]; strategy mock-b:
    [t-y, t-x]) and starts the campaign, so every stored run is PLANNED
    and ``execute_realization_campaign`` can execute all four runs.
    """
    store = acceptance_campaign_store()
    prepare_strategy_trajectory_plans(
        store=store, legion=acceptance_legion(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    return store


def acceptance_observation_store() -> InMemoryScenarioStore:
    """A COMPLETE runtime-3 acceptance campaign with all observations extracted.

    Executes all four runs (2 strategies x 2 seeds, strategy-major/
    seed-minor) through the real campaign execution service and then
    explicitly extracts the metric-observation set of every run through
    the real extraction service, so every stored run is COMPLETE with a
    stored realization execution and a stored observation set.
    """
    store = acceptance_execution_store()
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store
