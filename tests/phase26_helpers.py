"""Shared helpers for the Phase 26 100-seed causal acceptance fixture.

Builds one deterministic, domain-neutral, end-to-end runtime-3.0.0
campaign over exactly 100 fixed shared seeds through the real public
services only: declarations (state model, guarded causal transitions,
metric-observation binding, discrete uncertainty model, evaluation
profile declared **before** world compilation), world compilation
through the mock-NEXUS compilation seam, runtime-3 preparation through
``prepare_realization_campaign`` (with the single sanctioned
``EXPECTED_STRATEGY_SET_SIZE == 2`` alignment for the two-candidate
acceptance LEGION adapter, scoped to the preparation call), trajectory
planning, start, full campaign execution, and explicit per-run
observation extraction. No observed value, realization, matrix, hash,
or expected artifact is ever patched, injected, or manufactured.

The world is the accepted Phase 25 causal branch fixture: a discrete
uncertainty binding on the integer ``level`` field with exactly two
support values (branch X = 5, branch Y = 9, equal weights) and two
declared guarded transitions ``t-x`` (guard level == 5, target
level -> 84) and ``t-y`` (guard level == 9, target level -> 103). The
two strategies ``mock-a`` (plan ``[t-x, t-y]``) and ``mock-b`` (plan
``[t-y, t-x]``) are genuinely distinct declared reference orders and
receive the exact same realized world per seed.

The fixed 100-seed ensemble is selected **at authoring time only**: the
realization of every candidate seed was computed once with the real
``build_world_realization`` builder against this exact fixture world,
and the first 81 branch-X seeds and the first 19 branch-Y seeds (in
ascending candidate order) were embedded as constants below. The test
never scans, retries, re-rolls, searches, or adaptively selects seeds
at runtime - the ensemble is immutable and the fixture asserts the
exact 81/19 split.

With the declared minimize objective (target 100.0, normalization scale
100.0), branch X produces the observed value 84 (achieved) and branch Y
produces 103 (missed), so the 81/19 realized-branch split is exactly
the 81/19 target-achievement split: 81 successful seeds out of 100,
``empirical_target_achievement_probability == 0.81``.
"""

from __future__ import annotations

from unittest.mock import patch

from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import realization_campaign_service
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
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
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection, ScenarioSeed
from kalhas.contracts.v1.world_realization import DiscreteDistribution

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import (
    DECLARED_AT,
    _register_pack,
    build_observation_scenario,
)
from tests.phase24_helpers import uncertainty_fields
from tests.phase25_helpers import (
    ACCEPTANCE_BRANCH_X,
    ACCEPTANCE_BRANCH_Y,
    ACCEPTANCE_VALUE_X,
    ACCEPTANCE_VALUE_Y,
    acceptance_legion,
)

#: The single authoritative minimize objective of the acceptance scenario.
OBJECTIVE_ID = "obj-1"

#: The single observed metric of the acceptance scenario (unit ``units``).
METRIC_ID = "m-1"

#: The declared minimize target: branch X (84) achieves it, branch Y (103) does not.
TARGET = 100.0

#: The declared normalization scale of the objective-to-metric binding.
NORMALIZATION_SCALE = 100.0

#: The two realized branch levels of the discrete uncertainty binding.
BRANCH_X_LEVEL = ACCEPTANCE_BRANCH_X
BRANCH_Y_LEVEL = ACCEPTANCE_BRANCH_Y

#: The engine-produced final observed values of the two branches.
BRANCH_X_VALUE = ACCEPTANCE_VALUE_X
BRANCH_Y_VALUE = ACCEPTANCE_VALUE_Y

#: The exact fixed ensemble split (81 branch-X seeds, 19 branch-Y seeds).
EXPECTED_X_COUNT = 81
EXPECTED_Y_COUNT = 19

#: The fixed 100-seed ensemble, selected once at authoring time against
#: the exact fixture world (see the module docstring). Immutable; the
#: acceptance fixture never searches or re-selects at runtime.
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
    "seed-043",
    "seed-046",
    "seed-048",
    "seed-049",
    "seed-050",
    "seed-052",
    "seed-054",
    "seed-055",
    "seed-057",
    "seed-058",
    "seed-059",
    "seed-060",
    "seed-061",
    "seed-065",
    "seed-066",
    "seed-067",
    "seed-068",
    "seed-069",
    "seed-074",
    "seed-075",
    "seed-076",
    "seed-078",
    "seed-082",
    "seed-083",
    "seed-084",
    "seed-086",
    "seed-090",
    "seed-094",
    "seed-095",
    "seed-101",
    "seed-103",
    "seed-105",
    "seed-109",
    "seed-110",
    "seed-111",
    "seed-112",
    "seed-114",
    "seed-116",
    "seed-117",
    "seed-119",
    "seed-120",
    "seed-121",
    "seed-124",
    "seed-125",
    "seed-127",
    "seed-128",
    "seed-132",
    "seed-134",
    "seed-135",
    "seed-138",
    "seed-139",
    "seed-141",
    "seed-142",
    "seed-143",
    "seed-145",
    "seed-146",
    "seed-147",
    "seed-148",
)


def build_seed_ensemble() -> tuple[ScenarioSeed, ...]:
    """The fixed 100 ``ScenarioSeed`` records in authoritative order."""
    return tuple(build_seed(identifier=identifier) for identifier in SEED_IDENTIFIERS)


def declared_fixture_store() -> InMemoryScenarioStore:
    """A store with every acceptance declaration, before world compilation.

    Registers the observation scenario with its objective replaced by
    the single authoritative minimize objective (target 100.0), the
    generic pack binding, state model sm-1 (level/ratio/status), the two
    guarded causal transitions t-x and t-y, the single metric-
    observation binding m-1 -> level, the discrete uncertainty model
    (values [5, 9], equal weights, nearest-ties-to-even rounding for the
    integer target), and the evaluation profile binding obj-1 -> m-1
    (normalization scale 100.0) - all through the real declaration
    services, with the profile declared **before** compilation so the
    compiled world embeds the exact profile snapshot.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario().model_copy(
        update={
            "objectives": [
                Objective(
                    identifier=OBJECTIVE_ID,
                    description="Minimize the primary metric",
                    direction=ObjectiveDirection.MINIMIZE,
                    target=TARGET,
                    weight=1.0,
                )
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
        guard_values={"level": BRANCH_X_LEVEL},
        target_values={"level": BRANCH_X_VALUE},
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
        guard_values={"level": BRANCH_Y_LEVEL},
        target_values={"level": BRANCH_Y_VALUE},
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id=METRIC_ID,
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
                    values=(BRANCH_X_LEVEL, BRANCH_Y_LEVEL),
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
                objective_id=OBJECTIVE_ID,
                metric_id=METRIC_ID,
                reach_tolerance=None,
                normalization_scale=NORMALIZATION_SCALE,
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
    two-candidate acceptance LEGION adapter (the preparation service's
    ``EXPECTED_STRATEGY_SET_SIZE`` is aligned to 2 only inside the
    preparation call - the single explicit seam of the fixture), plans
    the two strategy trajectory plans, starts the campaign, fully
    executes every run (2 strategies x N seeds, strategy-major/seed-
    minor), and explicitly extracts the metric-observation set of every
    run through the real extraction service. Nothing is patched,
    injected, or manufactured.
    """
    store = declared_fixture_store()
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
            campaign_name="100-seed acceptance campaign",
            seed_ensemble=seed_ensemble,
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
