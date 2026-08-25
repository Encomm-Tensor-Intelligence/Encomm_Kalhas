"""Gate 27.1 helpers: the unpatched exact-five causal acceptance fixture.

Builds one deterministic, domain-neutral, end-to-end runtime-3.0.0
campaign over exactly four immutable shared seeds (``seed-000``,
``seed-001``, ``seed-003``, ``seed-004``, constructed directly from
their identifiers - never scanned, retried, re-rolled, filtered, or
adaptively chosen) through the real public services only: declarations
(state model ``sm-1`` with integer ``level``/``reserve``, seven guarded
causal transitions, metric-observation bindings m-1 -> level and m-2 ->
reserve, the discrete uncertainty model over both fields, and the
two-objective evaluation profile declared **before** compilation), world
compilation through the mock-NEXUS seam, runtime-3 preparation through
the real ``prepare_realization_campaign``, trajectory planning, start,
full campaign execution (20 runs: 5 strategies x 4 seeds), and explicit
per-run observation extraction.

The LEGION boundary is the **real** ``MockLegionAdapter`` constructed
with explicit ``declared_transition_sequences`` - no subclass, no
replacement ``request_strategies``, no cardinality patch, no production
mutation. The unmodified production ``EXPECTED_STRATEGY_SET_SIZE == 5``
invariant accepts the adapter's five default candidates unchanged, and
the five declarations make the candidates causally different executable
plans rather than five labels.

The five declared strategies are genuinely different transition-reference
orders over the same closed catalog:

- ``mock-baseline``     = ``[t-z, t-z2, t-v, t-u]``: the best ordinary
  primary mean but the worst maximum total weighted regret (5.0);
- ``mock-conservative`` = ``[t-x, t-w, t-y, t-u]``;
- ``mock-balanced``     = ``[t-x, t-u, t-y]``;
- ``mock-adaptive``     = ``[t-x, t-v, t-y, t-u]``: the unique
  minimum-maximum-total-weighted-regret preference (0.94);
- ``mock-diversified``  = ``[t-z, t-y, t-w, t-u]``.

The frozen decision goldens (target-achievement probabilities, maximum
total weighted regrets, the preferred brief, and every policy/comparison/
brief identifier and content hash) were derived once at authoring time
through the real policy service and the real verified comparison/brief
queries against this exact final fixture world and are embedded as
immutable constants below.

The helper deliberately contains no comparison, dominance, regret,
minimax, or brief algorithm: every one of those facts is read from the
real derived artifacts. The only reconstruction logic is the independent
causal transition simulation (guard check + state update over the
declared transitions) that proves the engine-produced final states and
attempt orders, and the detached canonical store-state digest reuse.
"""

from __future__ import annotations

import math

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
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
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    ObjectiveTargetRequirement,
)
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection, ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import StateValueKind
from kalhas.contracts.v1.world_realization import DiscreteDistribution

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import state_field

#: The authoritative campaign identity of the Gate 27.1 fixture.
CAMPAIGN_ID = "campaign-1"
CAMPAIGN_NAME = "gate-27.1 exact-five reference campaign"

#: The five default candidates of the real ``MockLegionAdapter`` in their
#: exact production return order (labels only; policies are never executed).
STRATEGIES: tuple[str, ...] = (
    "mock-baseline",
    "mock-conservative",
    "mock-balanced",
    "mock-adaptive",
    "mock-diversified",
)

#: The exact immutable declaration mapping: every strategy receives an
#: explicit declared logical transition order (repetitions significant).
STRATEGY_PLANS: dict[str, tuple[str, ...]] = {
    "mock-baseline": ("t-z", "t-z2", "t-v", "t-u"),
    "mock-conservative": ("t-x", "t-w", "t-y", "t-u"),
    "mock-balanced": ("t-x", "t-u", "t-y"),
    "mock-adaptive": ("t-x", "t-v", "t-y", "t-u"),
    "mock-diversified": ("t-z", "t-y", "t-w", "t-u"),
}

#: Declared transitions: ``(identifier, guard_values, target_values)``.
TRANSITIONS: tuple[tuple[str, dict[str, JsonValue], dict[str, JsonValue]], ...] = (
    ("t-x", {"level": 5}, {"level": 84}),
    ("t-y", {"level": 9}, {"level": 103}),
    ("t-z", {"level": 5}, {"level": 60}),
    ("t-z2", {"level": 9}, {"reserve": 5}),
    ("t-v", {"reserve": 20}, {"reserve": 55}),
    ("t-w", {"reserve": 20}, {"reserve": 35}),
    ("t-u", {"reserve": 30}, {"reserve": 45}),
)

#: The transition guards keyed by transition id (frozen data).
TRANSITION_GUARDS: dict[str, dict[str, JsonValue]] = {
    transition_id: guard for transition_id, guard, _target in TRANSITIONS
}

#: The transition targets keyed by transition id (frozen data).
TRANSITION_TARGETS: dict[str, dict[str, JsonValue]] = {
    transition_id: target for transition_id, _guard, target in TRANSITIONS
}

#: Objective identifiers of the acceptance scenario (authoritative order).
OBJECTIVE_IDS: tuple[str, ...] = ("obj-1", "obj-2")

#: Metric identifiers bound to the two objectives (authoritative order).
METRIC_IDS: tuple[str, ...] = ("m-1", "m-2")

#: The declared minimize target of obj-1 (level) and maximize target of obj-2 (reserve).
TARGETS: dict[str, float] = {"obj-1": 100.0, "obj-2": 35.0}

#: The declared normalization scales of the objective-to-metric bindings.
NORMALIZATION_SCALES: dict[str, float] = {"obj-1": 100.0, "obj-2": 10.0}

#: The declared objective weights (never normalized).
WEIGHTS: dict[str, float] = {"obj-1": 1.0, "obj-2": 1.0}

#: The fixed decision-policy rules of the Gate 27.1 declaration.
THRESHOLDS: dict[str, float] = {"obj-1": 0.40, "obj-2": 0.40}
TIE_TOLERANCE = 0.05
MINIMUM_SAMPLE_COUNT = 4

#: The four immutable shared seeds in their exact frozen order,
#: constructed directly from their identifiers.
SEED_IDENTIFIERS: tuple[str, ...] = ("seed-000", "seed-001", "seed-003", "seed-004")

#: The frozen realized world types of the shared seeds
#: ``(level, reserve)`` per seed identifier.
EXPECTED_WORLD_TYPES: dict[str, tuple[int, int]] = {
    "seed-000": (9, 30),
    "seed-001": (5, 30),
    "seed-003": (5, 20),
    "seed-004": (9, 20),
}

#: The independent causal expectation function: for every strategy and
#: every realized world type, the engine-produced final ``(level,
#: reserve)`` under the declared guarded transitions.
CAUSAL_EXPECTATION: dict[str, dict[tuple[int, int], tuple[int, int]]] = {
    "mock-baseline": {
        (5, 20): (60, 55),
        (5, 30): (60, 45),
        (9, 20): (9, 5),
        (9, 30): (9, 5),
    },
    "mock-conservative": {
        (5, 20): (84, 35),
        (5, 30): (84, 45),
        (9, 20): (103, 35),
        (9, 30): (103, 45),
    },
    "mock-balanced": {
        (5, 20): (84, 20),
        (5, 30): (84, 45),
        (9, 20): (103, 20),
        (9, 30): (103, 45),
    },
    "mock-adaptive": {
        (5, 20): (84, 55),
        (5, 30): (84, 45),
        (9, 20): (103, 55),
        (9, 30): (103, 45),
    },
    "mock-diversified": {
        (5, 20): (60, 35),
        (5, 30): (60, 45),
        (9, 20): (103, 35),
        (9, 30): (103, 45),
    },
}

#: Frozen empirical target-achievement probabilities ``(obj-1, obj-2)``
#: per strategy (obj-1 minimize, obj-2 maximize) over the four shared seeds.
EXPECTED_TARGET_PROBABILITIES: dict[str, tuple[float, float]] = {
    "mock-baseline": (1.0, 0.5),
    "mock-conservative": (0.5, 1.0),
    "mock-balanced": (0.5, 0.5),
    "mock-adaptive": (0.5, 1.0),
    "mock-diversified": (0.5, 1.0),
}

#: Frozen maximum total weighted regrets per strategy (probed once from
#: the real comparison; the balanced value is the exact engine float of
#: the non-exact decimal 4.44).
EXPECTED_MAX_TOTAL_REGRETS: dict[str, float] = {
    "mock-baseline": 5.0,
    "mock-conservative": 2.94,
    "mock-balanced": 4.4399999999999995,
    "mock-adaptive": 0.94,
    "mock-diversified": 2.94,
}

#: Frozen deterministic identifiers and content hashes of the Gate 27.1
#: decision artifacts (derived once at authoring time through the real
#: policy service and verified queries over this exact final fixture;
#: the test never recomputes them through identity functions).
GOLDEN_POLICY_ID = "campaign-decision-policy-9caab5493c904b86"
GOLDEN_POLICY_CONTENT_HASH = "68f68e171b69431c70167bbf28b7a65055e6fbb1c4ac836373d754e338d5df17"
GOLDEN_COMPARISON_ID = "campaign-strategy-comparison-0538c7e968c25a5c"
GOLDEN_COMPARISON_CONTENT_HASH = "a9d79086d4a386b219e9e6a9ed10faff7ae15a55af391c9e7d874d8b184cfd71"
GOLDEN_BRIEF_ID = "campaign-decision-brief-9ac779fc1df02f5a"
GOLDEN_BRIEF_CONTENT_HASH = "3995d689700cb0ab8fbf3d0f7b48136875f34ab2f95b8347f05d89ca5a535aff"

#: The exact frozen gate-aware summary (the policy identifier is the
#: frozen Gate 27.1 policy identifier).
GOLDEN_BRIEF_SUMMARY = (
    "Strategy mock-adaptive is preferred under policy "
    "campaign-decision-policy-9caab5493c904b86: feasible, non-dominated, "
    "unique minimum maximum total weighted regret (0.94)."
)

#: The store collections whose complete state must never change on query.
STORE_COLLECTIONS: tuple[str, ...] = (
    "_scenarios",
    "_worlds",
    "_manifests",
    "_campaigns",
    "_campaign_statuses",
    "_run_plans",
    "_strategy_candidates",
    "_run_statuses",
    "_run_events",
    "_replay_manifests",
    "_input_integrity_manifests",
    "_domain_pack_manifests",
    "_domain_pack_bindings",
    "_domain_capability_declarations",
    "_domain_state_models",
    "_domain_state_transitions",
    "_domain_metric_observations",
    "_evaluation_profiles",
    "_world_uncertainty_models",
    "_campaign_decision_policies",
    "_operational_activity",
    "_activity_sequences",
    "_strategy_trajectory_plans",
    "_run_trajectory_executions",
    "_run_trajectory_replay_manifests",
    "_run_metric_observation_sets",
    "_realization_run_trajectory_executions",
    "_realization_run_trajectory_replay_manifests",
    "_realization_run_metric_observation_sets",
)


def exact_five_legion() -> MockLegionAdapter:
    """The real ``MockLegionAdapter`` with the exact declared five plans.

    No subclass and no replacement ``request_strategies``: the adapter's
    production ``request_strategies`` returns its five default candidates
    in the exact production order, and its production fail-closed
    ``request_trajectory_plan`` resolves every declaration to the
    request's available catalog.
    """
    return MockLegionAdapter(declared_transition_sequences=STRATEGY_PLANS)


def build_seed_ensemble() -> tuple[ScenarioSeed, ...]:
    """The four fixed ``ScenarioSeed`` records in authoritative order."""
    return tuple(build_seed(identifier=identifier) for identifier in SEED_IDENTIFIERS)


def declared_fixture_store() -> InMemoryScenarioStore:
    """A store with every Gate 27.1 declaration, before world compilation.

    Registers the observation scenario with its two objectives replaced
    by the authoritative pair (obj-1 minimize target 100.0, obj-2
    maximize target 35.0, both weight 1.0), the generic pack binding,
    state model sm-1 (integer level and reserve, both initial 0), the
    seven guarded causal transitions, the two metric-observation
    bindings m-1 -> level and m-2 -> reserve, the discrete uncertainty
    model (level values [5, 9], reserve values [20, 30], equal weights,
    nearest-ties-to-even rounding for both integer fields), and the
    evaluation profile binding obj-1 -> m-1 (scale 100.0) and obj-2 ->
    m-2 (scale 10.0) - all through the real declaration services, with
    the profile declared **before** compilation so the compiled world
    embeds the exact profile snapshot.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario().model_copy(
        update={
            "objectives": [
                Objective(
                    identifier=OBJECTIVE_IDS[0],
                    description="Minimize the primary metric",
                    direction=ObjectiveDirection.MINIMIZE,
                    target=TARGETS["obj-1"],
                    weight=WEIGHTS["obj-1"],
                ),
                Objective(
                    identifier=OBJECTIVE_IDS[1],
                    description="Maximize the secondary metric",
                    direction=ObjectiveDirection.MAXIMIZE,
                    target=TARGETS["obj-2"],
                    weight=WEIGHTS["obj-2"],
                ),
            ]
        }
    )
    store.put_scenario(scenario)
    _register_pack(store)
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=(
            state_field("level", StateValueKind.INTEGER, 0),
            state_field("reserve", StateValueKind.INTEGER, 0),
        ),
        declared_at=DECLARED_AT,
    )
    for transition_id, guard, target in TRANSITIONS:
        declare_transition(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id=transition_id,
            description=f"transition {transition_id}",
            guard_values=guard,
            target_values=target,
            declared_at=DECLARED_AT,
        )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=METRIC_IDS[0],
        state_field_id="level",
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=METRIC_IDS[1],
        state_field_id="reserve",
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
                    values=(5, 9),
                    probabilities=(0.5, 0.5),
                ),
                rounding_policy="nearest_ties_to_even",
            ),
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-1",
                state_field_id="reserve",
                distribution=DiscreteDistribution(
                    kind="discrete",
                    values=(20, 30),
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
        bindings=(
            ObjectiveMetricBindingDraft(
                objective_id=OBJECTIVE_IDS[0],
                metric_id=METRIC_IDS[0],
                reach_tolerance=None,
                normalization_scale=NORMALIZATION_SCALES["obj-1"],
            ),
            ObjectiveMetricBindingDraft(
                objective_id=OBJECTIVE_IDS[1],
                metric_id=METRIC_IDS[1],
                reach_tolerance=None,
                normalization_scale=NORMALIZATION_SCALES["obj-2"],
            ),
        ),
        declared_at=DECLARED_AT,
        metadata={},
    )
    return store


def complete_exact_five_store() -> InMemoryScenarioStore:
    """A COMPLETE runtime-3 exact-five campaign with observations extracted.

    Compiles the fixture world through the real mock-NEXUS compilation
    path and prepares the runtime-3.0.0 campaign through the real
    ``prepare_realization_campaign`` service with the **unmodified
    production** ``EXPECTED_STRATEGY_SET_SIZE == 5`` invariant and the
    real ``MockLegionAdapter`` carrying the five explicit declarations -
    no patch, no production mutation, no replacement adapter behavior.
    Plans the five authoritative strategy trajectory plans through the
    real planning service, starts the campaign, fully executes every run
    (5 strategies x 4 seeds = 20 runs, strategy-major/seed-minor), and
    explicitly extracts the metric-observation set of every run through
    the real extraction service. Nothing is patched, injected, or
    manufactured.
    """
    store = declared_fixture_store()
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=exact_five_legion(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id=CAMPAIGN_ID,
        campaign_name=CAMPAIGN_NAME,
        seed_ensemble=build_seed_ensemble(),
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=exact_five_legion(), tenant_id=TENANT, campaign_id=CAMPAIGN_ID
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID)
    for plan in store.get_run_plans(TENANT, CAMPAIGN_ID):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store


def declare_exact_five_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """Declare the real Gate 27.1 policy through the real policy service.

    Per-objective mode with the 0.40 hard gates on both targeted
    objectives, minimum sample count 4, tie tolerance 0.05, the
    deterministic authoring-time ``declared_at`` from the existing test
    constants, and empty metadata. Every authoritative identity, hash,
    weight snapshot, the algorithm identifier, and the fixed tail alpha
    are copied by the service from the verified stored records.
    """
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN_ID,
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="per_objective",
            minimum_sample_count=MINIMUM_SAMPLE_COUNT,
            tie_tolerance=TIE_TOLERANCE,
            all_targeted_objectives_are_hard_gates=True,
            declared_at=DECLARED_AT,
            minimum_target_achievement_probability=None,
            objective_target_requirements=(
                ObjectiveTargetRequirement(
                    objective_id=OBJECTIVE_IDS[0],
                    minimum_target_achievement_probability=THRESHOLDS["obj-1"],
                ),
                ObjectiveTargetRequirement(
                    objective_id=OBJECTIVE_IDS[1],
                    minimum_target_achievement_probability=THRESHOLDS["obj-2"],
                ),
            ),
            metadata={},
        ),
    )


def realized_world_type(store: InMemoryScenarioStore, seed: ScenarioSeed) -> tuple[int, int]:
    """The deterministically realized ``(level, reserve)`` of one seed.

    Reconstructs the world type through the real realization builder
    against the fixture world (tests may reconstruct; production never
    does) - the independent causal input of every expectation.
    """
    campaign = store.get_campaign(TENANT, CAMPAIGN_ID)
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
    reserve = next(
        override.value
        for override in realization.realized_initial_state_overrides
        if override.state_field_id == "reserve"
    )
    assert isinstance(level, int)
    assert isinstance(reserve, int)
    return (level, reserve)


def expected_observed(strategy_id: str, world_type: tuple[int, int]) -> tuple[int, int]:
    """The causally expected final ``(level, reserve)`` of one run."""
    return CAUSAL_EXPECTATION[strategy_id][world_type]


def expected_attempt_sequence(
    plan_ids: tuple[str, ...],
    world_type: tuple[int, int],
) -> tuple[tuple[str, str], ...]:
    """The independent causal attempt simulation of one declared plan.

    Walks the declared plan in order over a running state copy starting
    at the realized world type: every transition is attempted, applies
    exactly when its declared guard matches the current state, and an
    applied transition updates the state with its declared targets. The
    returned flattened ``(transition_id, outcome)`` tuple is the
    independent expectation the real engine-produced attempt records
    must equal.
    """
    state: dict[str, int] = {"level": world_type[0], "reserve": world_type[1]}
    attempts: list[tuple[str, str]] = []
    for transition_id in plan_ids:
        guard = TRANSITION_GUARDS[transition_id]
        target = TRANSITION_TARGETS[transition_id]
        if all(state[field] == value for field, value in guard.items()):
            attempts.append((transition_id, "applied"))
            for field, value in target.items():
                assert isinstance(value, int)
                state[field] = value
        else:
            attempts.append((transition_id, "guard_not_satisfied"))
    return tuple(attempts)


def is_within_one_ulp(value: float, expected: float) -> bool:
    """Exact equality or exactly one adjacent float step (strict one-ULP).

    The deterministic one-adjacent-float-step relation used for the
    non-exact decimal goldens: no ``math.isclose``, no relative
    tolerance, and no broad absolute epsilon.
    """
    if value == expected:
        return True
    return value == math.nextafter(expected, math.inf) or value == math.nextafter(
        expected, -math.inf
    )


def dump_value(value: object) -> object:
    """One canonical JSON dump of a stored record or record tuple."""
    if isinstance(value, tuple):
        return tuple(dump_value(item) for item in value)
    if isinstance(value, VersionedContract):
        return value.model_dump(mode="json")
    return value


def store_state(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest of the complete store state."""
    payload: dict[str, object] = {}
    for name in STORE_COLLECTIONS:
        collection = getattr(store, name)
        payload[name] = {repr(key): dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)
