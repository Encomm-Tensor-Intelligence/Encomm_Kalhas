"""Shared helpers for the Phase 27 100-seed causal decision acceptance fixture.

Builds one deterministic, domain-neutral, end-to-end runtime-3.0.0
campaign over exactly 100 fixed shared seeds (``seed-000`` through
``seed-099``, the first 100 identifiers in ascending order - never
searched, retried, re-rolled, filtered, or adaptively chosen) through
the real public services only: declarations (state model ``sm-1`` with
integer ``level``/``reserve``, seven guarded causal transitions, the two
metric-observation bindings m-1 -> level and m-2 -> reserve, the discrete
uncertainty model over both fields, and the two-objective evaluation
profile declared **before** world compilation), world compilation
through the mock-NEXUS compilation seam, runtime-3 preparation through
``prepare_realization_campaign`` (with the single sanctioned
``EXPECTED_STRATEGY_SET_SIZE == 3`` alignment for the three-candidate
acceptance LEGION adapter, scoped to the preparation call), trajectory
planning, start, full campaign execution (300 runs: 3 strategies x 100
seeds), and explicit per-run observation extraction. No observed value,
realization, matrix, hash, outcome, policy, comparison, brief, or
expected artifact is ever patched, injected, or manufactured.

The three declared strategies are genuinely different transition-
reference orders over the same closed catalog:

- ``mock-a`` = ``[t-z, t-z2, t-v, t-u]``: the best ordinary
  primary-objective mean (32.46) but the worst maximum total weighted
  regret (4.0) - its reserve collapses to 5 in every level-9 world;
- ``mock-b`` = ``[t-x, t-w, t-y, t-u]``: a slightly worse primary mean
  (94.26) and the unique minimax-robust maximum total weighted regret
  (2.24);
- ``mock-c`` = ``[t-x, t-u, t-y]``: consistently inferior and dominated
  by ``mock-b``.

The frozen decision goldens (distributions, means, target-achievement
probabilities, paired win/tie/loss counts, dominance relations,
per-world-type total weighted regrets, minimax result, decisive/blocking
factor trails, the preferred brief, and every policy/comparison/brief
identifier and content hash) were derived once at authoring time through
the real policy service and the real verified comparison/brief queries
against this exact final fixture world, and are embedded as immutable
constants below. The acceptance test never recomputes a decision golden
through an identity or decision function.

The helper deliberately contains no comparison, dominance, regret,
minimax, or brief algorithm: every one of those facts is read from the
real derived artifacts. The only reconstruction logic is the independent
causal transition simulation (guard check + state update over the
declared transitions) that proves the engine-produced final states and
attempt orders, exactly as the acceptance suite requires.
"""

from __future__ import annotations

import math
from unittest.mock import patch

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application import realization_campaign_service
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
from kalhas.contracts.v1.strategy import (
    PolicyDeclaration,
    PolicyRule,
    StrategyCandidate,
    StrategyRequest,
)
from kalhas.contracts.v1.world_realization import DiscreteDistribution

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import state_field

#: The three genuinely different declared strategy plans (logical transition ids).
STRATEGY_PLANS: dict[str, tuple[str, ...]] = {
    "mock-a": ("t-z", "t-z2", "t-v", "t-u"),
    "mock-b": ("t-x", "t-w", "t-y", "t-u"),
    "mock-c": ("t-x", "t-u", "t-y"),
}

#: The authoritative strategy order of the acceptance campaign.
STRATEGIES: tuple[str, ...] = ("mock-a", "mock-b", "mock-c")

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

#: The fixed decision-policy rules of the acceptance declaration.
THRESHOLDS: dict[str, float] = {"obj-1": 0.40, "obj-2": 0.40}
TIE_TOLERANCE = 0.05
MINIMUM_SAMPLE_COUNT = 100

#: The fixed 100-seed ensemble: the first 100 identifiers in ascending
#: order, immutable, never searched or re-selected at runtime.
SEED_IDENTIFIERS: tuple[str, ...] = (
    "seed-000",
    "seed-001",
    "seed-002",
    "seed-003",
    "seed-004",
    "seed-005",
    "seed-006",
    "seed-007",
    "seed-008",
    "seed-009",
    "seed-010",
    "seed-011",
    "seed-012",
    "seed-013",
    "seed-014",
    "seed-015",
    "seed-016",
    "seed-017",
    "seed-018",
    "seed-019",
    "seed-020",
    "seed-021",
    "seed-022",
    "seed-023",
    "seed-024",
    "seed-025",
    "seed-026",
    "seed-027",
    "seed-028",
    "seed-029",
    "seed-030",
    "seed-031",
    "seed-032",
    "seed-033",
    "seed-034",
    "seed-035",
    "seed-036",
    "seed-037",
    "seed-038",
    "seed-039",
    "seed-040",
    "seed-041",
    "seed-042",
    "seed-043",
    "seed-044",
    "seed-045",
    "seed-046",
    "seed-047",
    "seed-048",
    "seed-049",
    "seed-050",
    "seed-051",
    "seed-052",
    "seed-053",
    "seed-054",
    "seed-055",
    "seed-056",
    "seed-057",
    "seed-058",
    "seed-059",
    "seed-060",
    "seed-061",
    "seed-062",
    "seed-063",
    "seed-064",
    "seed-065",
    "seed-066",
    "seed-067",
    "seed-068",
    "seed-069",
    "seed-070",
    "seed-071",
    "seed-072",
    "seed-073",
    "seed-074",
    "seed-075",
    "seed-076",
    "seed-077",
    "seed-078",
    "seed-079",
    "seed-080",
    "seed-081",
    "seed-082",
    "seed-083",
    "seed-084",
    "seed-085",
    "seed-086",
    "seed-087",
    "seed-088",
    "seed-089",
    "seed-090",
    "seed-091",
    "seed-092",
    "seed-093",
    "seed-094",
    "seed-095",
    "seed-096",
    "seed-097",
    "seed-098",
    "seed-099",
)

#: The exact realized world-type split of the fixed ensemble
#: ``(level, reserve) -> seed count`` (probed once at authoring time
#: through the real realization builder against this fixture world).
EXPECTED_WORLD_TYPE_COUNTS: dict[tuple[int, int], int] = {
    (5, 20): 22,
    (5, 30): 24,
    (9, 20): 27,
    (9, 30): 27,
}

#: The independent causal expectation function: for every strategy and
#: every realized world type, the engine-produced final ``(level,
#: reserve)`` under the declared guarded transitions.
CAUSAL_EXPECTATION: dict[str, dict[tuple[int, int], tuple[int, int]]] = {
    "mock-a": {
        (5, 20): (60, 55),
        (5, 30): (60, 45),
        (9, 20): (9, 5),
        (9, 30): (9, 5),
    },
    "mock-b": {
        (5, 20): (84, 35),
        (5, 30): (84, 45),
        (9, 20): (103, 35),
        (9, 30): (103, 45),
    },
    "mock-c": {
        (5, 20): (84, 20),
        (5, 30): (84, 45),
        (9, 20): (103, 20),
        (9, 30): (103, 45),
    },
}

#: Frozen observed-value distributions ``value -> count`` per strategy
#: and objective (derived once from the real fixture; every value is an
#: exactly representable float of an engine-produced integer).
EXPECTED_DISTRIBUTIONS: dict[str, dict[str, dict[float, int]]] = {
    "mock-a": {
        "obj-1": {9.0: 54, 60.0: 46},
        "obj-2": {5.0: 54, 45.0: 24, 55.0: 22},
    },
    "mock-b": {
        "obj-1": {84.0: 46, 103.0: 54},
        "obj-2": {35.0: 49, 45.0: 51},
    },
    "mock-c": {
        "obj-1": {84.0: 46, 103.0: 54},
        "obj-2": {20.0: 49, 45.0: 51},
    },
}

#: Frozen ordinary arithmetic means ``(obj-1, obj-2)`` per strategy.
EXPECTED_MEANS: dict[str, tuple[float, float]] = {
    "mock-a": (32.46, 25.6),
    "mock-b": (94.26, 40.1),
    "mock-c": (94.26, 32.75),
}

#: Frozen empirical target-achievement probabilities ``(obj-1, obj-2)``
#: per strategy (obj-1 minimize, obj-2 maximize).
EXPECTED_TARGET_PROBABILITIES: dict[str, tuple[float, float]] = {
    "mock-a": (1.0, 0.46),
    "mock-b": (0.46, 1.0),
    "mock-c": (0.46, 0.51),
}

#: Frozen ordered-pair win/tie/loss counts keyed by
#: ``(first_strategy, second_strategy, objective_id)`` (tolerance 0.05).
EXPECTED_PAIR_COUNTS: dict[tuple[str, str, str], tuple[int, int, int]] = {
    ("mock-a", "mock-b", "obj-1"): (100, 0, 0),
    ("mock-a", "mock-b", "obj-2"): (22, 24, 54),
    ("mock-a", "mock-c", "obj-1"): (100, 0, 0),
    ("mock-a", "mock-c", "obj-2"): (22, 24, 54),
    ("mock-b", "mock-a", "obj-1"): (0, 0, 100),
    ("mock-b", "mock-a", "obj-2"): (54, 24, 22),
    ("mock-b", "mock-c", "obj-1"): (0, 100, 0),
    ("mock-b", "mock-c", "obj-2"): (49, 51, 0),
    ("mock-c", "mock-a", "obj-1"): (0, 0, 100),
    ("mock-c", "mock-a", "obj-2"): (54, 24, 22),
    ("mock-c", "mock-b", "obj-1"): (0, 100, 0),
    ("mock-c", "mock-b", "obj-2"): (0, 51, 49),
}

#: Frozen per-world-type total weighted regrets per strategy
#: ``(level, reserve) -> total`` (probed once from the real comparison).
EXPECTED_WORLD_TYPE_TOTAL_REGRET: dict[str, dict[tuple[int, int], float]] = {
    "mock-a": {(5, 20): 0.0, (5, 30): 0.0, (9, 20): 3.0, (9, 30): 4.0},
    "mock-b": {(5, 20): 2.24, (5, 30): 0.24, (9, 20): 0.94, (9, 30): 0.94},
    "mock-c": {(5, 20): 3.74, (5, 30): 0.24, (9, 20): 2.44, (9, 30): 0.94},
}

#: Frozen total-regret aggregates ``(max, median, p95)`` per strategy.
#: ``p95`` of mock-c is the exact Type-7 interpolation result
#: ``fsum(3.74 * 0.95, 3.74 * 0.05) == 3.7399999999999998`` - one ULP
#: below the literal 3.74 (the strict one-ULP helper accepts the max).
EXPECTED_REGRET_AGGREGATES: dict[str, tuple[float, float, float]] = {
    "mock-a": (4.0, 3.0, 4.0),
    "mock-b": (2.24, 0.94, 2.24),
    "mock-c": (3.74, 0.94, 3.7399999999999998),
}

#: Frozen minimax result facts.
BEST_MAXIMUM_TOTAL_REGRET = 2.24
MINIMAX_TIE_SET: tuple[str, ...] = ("mock-b",)
NEAREST_COMPETITOR = "mock-a"
REGRET_GAP = 1.7599999999999998

#: Frozen decisive factor trail ``(code, strategy, objective, values,
#: related)`` in exact pipeline-stage order.
EXPECTED_DECISIVE_FACTORS: tuple[
    tuple[str, str | None, str | None, tuple[float, ...], tuple[str, ...]], ...
] = (
    ("feasible_candidate", "mock-a", None, (), ()),
    ("feasible_candidate", "mock-b", None, (), ()),
    ("feasible_candidate", "mock-c", None, (), ()),
    ("target_feasibility_passed", "mock-a", "obj-1", (0.4, 1.0), ()),
    ("target_feasibility_passed", "mock-a", "obj-2", (0.4, 0.46), ()),
    ("target_feasibility_passed", "mock-b", "obj-1", (0.4, 0.46), ()),
    ("target_feasibility_passed", "mock-b", "obj-2", (0.4, 1.0), ()),
    ("target_feasibility_passed", "mock-c", "obj-1", (0.4, 0.46), ()),
    ("target_feasibility_passed", "mock-c", "obj-2", (0.4, 0.51), ()),
    ("pareto_non_dominated", "mock-a", None, (), ()),
    ("pareto_non_dominated", "mock-b", None, (), ()),
    ("unique_minimax_regret", "mock-b", None, (2.24, 4.0, 1.7599999999999998), ("mock-a",)),
)

#: Frozen blocking factor trail ``(code, strategy, objective, values,
#: related)`` in exact pipeline-stage order.
EXPECTED_BLOCKING_FACTORS: tuple[
    tuple[str, str | None, str | None, tuple[float, ...], tuple[str, ...]], ...
] = (("dominated_strategy", "mock-c", None, (), ("mock-b",)),)

#: Frozen deterministic identifiers and content hashes of the real
#: acceptance decision artifacts (derived once at authoring time through
#: the real policy service and verified queries over this exact final
#: fixture; the test never recomputes them through identity functions).
GOLDEN_POLICY_ID = "campaign-decision-policy-9caab5493c904b86"
GOLDEN_POLICY_CONTENT_HASH = "460506bcb428aa37b60cfddbd2298d72b12d54840f4c4c9d8f2e7d14bfc017ea"
GOLDEN_COMPARISON_ID = "campaign-strategy-comparison-0538c7e968c25a5c"
GOLDEN_COMPARISON_CONTENT_HASH = "8953b853eacad92a9facdd533c5162dab5d94c0a4dc883a50049626eae4fbcdd"
GOLDEN_BRIEF_ID = "campaign-decision-brief-9ac779fc1df02f5a"
GOLDEN_BRIEF_CONTENT_HASH = "141986a4e53ff769fa5dd8ea0728ad8e150113c623f9d2579174b26791fde596"

#: The exact frozen gate-aware summary (the policy identifier is the
#: frozen acceptance policy identifier).
GOLDEN_BRIEF_SUMMARY = (
    "Strategy mock-b is preferred under policy campaign-decision-policy-9caab5493c904b86: "
    "feasible, non-dominated, unique minimum maximum total weighted regret (2.24)."
)

#: Frozen identifiers and content hashes of the Phase 26 two-strategy
#: tie-control decision artifacts (same derivation discipline).
GOLDEN_CONTROL_POLICY_ID = "campaign-decision-policy-cc0e04078fb8d995"
GOLDEN_CONTROL_POLICY_CONTENT_HASH = (
    "548e7662b12f9ce635aa63d5a9954001461d204bb534b91d9b301fb3e0058921"
)
GOLDEN_CONTROL_COMPARISON_ID = "campaign-strategy-comparison-58f430374f298749"
GOLDEN_CONTROL_COMPARISON_CONTENT_HASH = (
    "91ae09283299c8df3208b9d2f174d3e6b70a04493afc668d090657986ffe92f3"
)
GOLDEN_CONTROL_BRIEF_ID = "campaign-decision-brief-40f80552fcaf5543"
GOLDEN_CONTROL_BRIEF_CONTENT_HASH = (
    "89ad112839f4d9b02f044519807dfa9aa51763a919dc9d6e08e5420d7ee0a03d"
)

#: The exact frozen tie-control summary.
GOLDEN_CONTROL_BRIEF_SUMMARY = (
    "No preferred strategy is issued: 2 feasible non-dominated strategies remain "
    "tied within the declared tolerance (0.05)."
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

#: The declared transition guards keyed by transition id (frozen data).
TRANSITION_GUARDS: dict[str, dict[str, JsonValue]] = {
    transition_id: guard for transition_id, guard, _target in TRANSITIONS
}

#: The declared transition targets keyed by transition id (frozen data).
TRANSITION_TARGETS: dict[str, dict[str, JsonValue]] = {
    transition_id: target for transition_id, _guard, target in TRANSITIONS
}


class Phase27LegionAdapter(MockLegionAdapter):
    """Test-only LEGION boundary restricted to exactly three candidates.

    ``request_strategies`` returns exactly three deterministic,
    domain-neutral strategy candidates (``mock-a``, ``mock-b``,
    ``mock-c``) with identical ordered observation permissions, so a
    prepared campaign holds exactly three strategies and exactly 300 run
    plans (3 x 100). ``request_trajectory_plan`` is the real fail-closed
    declaration resolution inherited unchanged from
    ``MockLegionAdapter``.
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
            for label in ("a", "b", "c")
        )


def phase27_legion() -> Phase27LegionAdapter:
    """The acceptance LEGION boundary with the declared three plans."""
    return Phase27LegionAdapter(declared_transition_sequences=STRATEGY_PLANS)


def build_seed_ensemble() -> tuple[ScenarioSeed, ...]:
    """The fixed 100 ``ScenarioSeed`` records in authoritative order."""
    return tuple(build_seed(identifier=identifier) for identifier in SEED_IDENTIFIERS)


def declared_fixture_store() -> InMemoryScenarioStore:
    """A store with every acceptance declaration, before world compilation.

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


def complete_100_seed_store(
    seed_ensemble: tuple[ScenarioSeed, ...],
) -> InMemoryScenarioStore:
    """A COMPLETE runtime-3 100-seed acceptance campaign with observations extracted.

    Compiles the acceptance world through the real mock-NEXUS
    compilation path and prepares the runtime-3.0.0 campaign through the
    real ``prepare_realization_campaign`` service with the test-only
    three-candidate acceptance LEGION adapter (the preparation service's
    ``EXPECTED_STRATEGY_SET_SIZE`` is aligned to 3 only inside the
    preparation call - the single explicit seam of the fixture), plans
    the three strategy trajectory plans, starts the campaign, fully
    executes every run (3 strategies x 100 seeds, strategy-major/seed-
    minor), and explicitly extracts the metric-observation set of every
    run through the real extraction service. Nothing is patched,
    injected, or manufactured.
    """
    store = declared_fixture_store()
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    with patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 3):
        prepare_realization_campaign(
            store=store,
            legion=phase27_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-1",
            campaign_name="phase-27 acceptance campaign",
            seed_ensemble=seed_ensemble,
            created_at=NOW,
        )
    prepare_strategy_trajectory_plans(
        store=store, legion=phase27_legion(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store


def declare_acceptance_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """Declare the real acceptance policy through the real policy service.

    Per-objective mode with the 0.40 hard gates on both targeted
    objectives, minimum sample count 100, tie tolerance 0.05, the
    deterministic authoring-time ``declared_at`` from the existing test
    constants, and empty metadata. Every authoritative identity, hash,
    weight snapshot, the algorithm identifier, and the fixed tail alpha
    are copied by the service from the verified stored records.
    """
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-1",
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


def declare_control_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """Declare the real tie-control policy on the Phase 26 fixture campaign.

    Per-objective mode with the single 0.40 hard gate on the Phase 26
    objective obj-1, minimum sample count 100, tie tolerance 0.05, the
    deterministic ``declared_at`` constant, and empty metadata.
    """
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-1",
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="per_objective",
            minimum_sample_count=MINIMUM_SAMPLE_COUNT,
            tie_tolerance=TIE_TOLERANCE,
            all_targeted_objectives_are_hard_gates=True,
            declared_at=DECLARED_AT,
            minimum_target_achievement_probability=None,
            objective_target_requirements=(
                ObjectiveTargetRequirement(
                    objective_id="obj-1",
                    minimum_target_achievement_probability=THRESHOLDS["obj-1"],
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
    campaign = store.get_campaign(TENANT, "campaign-1")
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
