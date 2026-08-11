"""Shared helpers for Phase 23 objective-evaluation tests.

Builds COMPLETE runtime-2.0.0 campaigns whose compiled world embeds a
declared ``ScenarioEvaluationProfile`` (declared **before** world
compilation through the real Phase 23 declaration service, with the
scenario objective order deliberately different from lexical order),
with fully extracted and verified Phase 20 ``RunMetricObservationSet``
artifacts, then obtains the completely verified Phase 23
``CampaignObjectiveEvaluationMatrix`` through the real verified query
service.

Also provides contract-level payload builders with fully controlled
raw values (for exact boundary and overflow tests of the pure builder)
and self-consistent tampering helpers (a ``model_copy``-based tamper
whose content hash is recomputed over the tampered content, so a
builder-level test reaches exactly the check under test instead of
failing on a source hash check). Tampering never mutates the store or
the original artifact.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from typing import cast

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.campaign_metric_observation_runtime import (
    campaign_metric_observation_matrix_content_hash,
    campaign_metric_observation_matrix_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
)
from kalhas.application.objective_evaluation_query_service import (
    get_verified_campaign_objective_evaluations,
)
from kalhas.application.objective_evaluation_runtime import (
    campaign_objective_evaluation_matrix_content_hash,
)
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
from kalhas.application.run_metric_observation_service import (
    extract_run_metric_observations,
)
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION, run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.campaign_metric_observation import (
    CampaignMetricObservationCell,
    CampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ObjectiveMetricBinding,
    ObjectiveObservationEvaluation,
    ScenarioEvaluationProfile,
)
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationValue
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection, ScenarioSeed, ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue, MetricDefinition

from tests.phase4_helpers import NOW, TENANT, build_scenario, build_seed, prepare, start
from tests.phase20_helpers import build_observation_store

PROFILE_DECLARED_AT = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)

#: Caller binding order deliberately differs from both the scenario
#: objective order (obj-b, obj-a, obj-c) and lexical order (obj-a,
#: obj-b, obj-c). The canonical profile must come out in scenario order.
DEFAULT_BINDING_DRAFTS: tuple[ObjectiveMetricBindingDraft, ...] = (
    ObjectiveMetricBindingDraft(
        objective_id="obj-c", metric_id="m-1", reach_tolerance=5.0, normalization_scale=50.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-a", metric_id="m-2", reach_tolerance=None, normalization_scale=20.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-b", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
)

#: Scenario objective order: minimize (target 100) -> maximize (no
#: target, optimization-only) -> reach (target 50). Deliberately NOT
#: lexical objective-id order.
DEFAULT_OBJECTIVES: tuple[Objective, ...] = (
    Objective(
        identifier="obj-b",
        description="Minimize the primary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-a",
        description="Maximize the secondary metric",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=2.0,
    ),
    Objective(
        identifier="obj-c",
        description="Reach the declared band",
        direction=ObjectiveDirection.REACH,
        target=50.0,
        weight=3.0,
    ),
)

DEFAULT_METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(identifier="m-1", name="Primary metric", unit="units"),
    MetricDefinition(identifier="m-2", name="Secondary metric", unit="percent"),
    MetricDefinition(identifier="m-3", name="Tertiary metric"),
)


def build_evaluation_scenario(*, tenant_id: str = TENANT) -> ScenarioSpec:
    """A scenario with objectives in deliberately non-lexical order.

    Objective order is obj-b, obj-a, obj-c - the authoritative
    ``ScenarioSpec.objectives`` order the profile and matrix must
    preserve (lexical order would be obj-a, obj-b, obj-c).
    """
    return build_scenario(tenant_id=tenant_id).model_copy(
        update={"objectives": list(DEFAULT_OBJECTIVES), "metrics": list(DEFAULT_METRICS)}
    )


def compile_evaluation_world(
    store: InMemoryScenarioStore,
    scenario: ScenarioSpec | None = None,
) -> str:
    """Compile the scenario's world embedding the stored evaluation profile.

    Loads the stored profile (the caller must have declared it before
    compilation) and embeds its complete snapshot together with the
    stored pack binding, state model, transition, and observation
    binding snapshots. Returns the compiled world version identifier.
    """
    effective_scenario = scenario if scenario is not None else build_evaluation_scenario()
    binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
    state_model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
    stored_transitions = store.list_domain_state_transitions(TENANT, "scenario-1")
    transitions = tuple(
        transition for transition in stored_transitions if transition.transition_id == "t-1"
    )
    observations = tuple(store.list_domain_metric_observations(TENANT, "scenario-1"))
    profile = store.get_evaluation_profile(TENANT, "scenario-1")
    compiled = compile_world(
        effective_scenario,
        bindings=(binding,),
        state_models=(state_model,),
        transitions=transitions,
        domain_metric_observations=observations,
        evaluation_profile=profile,
    )
    store.put_world(compiled.version, compiled.manifest)
    return compiled.version.identifier


def complete_evaluation_campaign(
    *,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
    scenario: ScenarioSpec | None = None,
    bindings: tuple[ObjectiveMetricBindingDraft, ...] = DEFAULT_BINDING_DRAFTS,
    with_transition: bool = True,
    execute: bool = True,
    extract: bool = True,
) -> tuple[InMemoryScenarioStore, str, tuple[str, ...]]:
    """A COMPLETE runtime-2.0.0 campaign whose world embeds an evaluation profile.

    Returns ``(store, world_version_id, run_ids)``. The profile is
    declared through the real Phase 23 service **before** the world is
    compiled; the campaign is prepared under runtime 2.0.0 with the
    mock strategy ensemble and the supplied shared seed ensemble, its
    complete trajectory-plan collection is prepared through the Phase
    15 service, the campaign is started, every planned run is executed
    (COMPLETE with a stored ``RunTrajectoryExecution``) unless
    ``execute`` is false, and - when ``extract`` is true - the explicit
    Phase 20 extraction runs for every planned run so the complete
    verified ``RunMetricObservationSet`` collection exists.
    """
    effective_scenario = scenario if scenario is not None else build_evaluation_scenario()
    store = build_observation_store(
        scenario=effective_scenario,
        with_bindings=True,
        with_transition=with_transition,
    )
    declare_scenario_evaluation_profile(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=bindings,
        declared_at=PROFILE_DECLARED_AT,
    )
    world_version_id = compile_evaluation_world(store, scenario=effective_scenario)
    prepare(
        store,
        world_version_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        seeds=seeds,
        campaign_id=campaign_id,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        campaign_id=campaign_id,
    )
    start(store, campaign_id)
    if execute:
        execute_campaign(store=store, tenant_id=TENANT, campaign_id=campaign_id)
    run_ids = tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, campaign_id))
    if extract and execute:
        for run_id in run_ids:
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
    return store, world_version_id, run_ids


def verified_evaluation_campaign(
    *,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
    scenario: ScenarioSpec | None = None,
    bindings: tuple[ObjectiveMetricBindingDraft, ...] = DEFAULT_BINDING_DRAFTS,
) -> tuple[InMemoryScenarioStore, CampaignObjectiveEvaluationMatrix, tuple[str, ...]]:
    """A COMPLETE 2.0.0 campaign and its completely verified Phase 23 matrix.

    Returns ``(store, evaluation_matrix, run_ids)`` where the matrix is
    obtained through the real verified Phase 23 query service over the
    real stored records.
    """
    store, _world_version_id, run_ids = complete_evaluation_campaign(
        seeds=seeds, campaign_id=campaign_id, scenario=scenario, bindings=bindings
    )
    matrix = get_verified_campaign_objective_evaluations(
        store=store, tenant_id=TENANT, campaign_id=campaign_id
    )
    return store, matrix, run_ids


def _binding_payloads() -> list[dict[str, object]]:
    """The default profile bindings as payload dicts (scenario order)."""
    return [
        {
            "objective_id": "obj-b",
            "metric_id": "m-1",
            "direction": "minimize",
            "target": 100.0,
            "weight": 1.0,
            "metric_unit": "units",
            "reach_tolerance": None,
            "normalization_scale": 100.0,
        },
        {
            "objective_id": "obj-a",
            "metric_id": "m-2",
            "direction": "maximize",
            "target": None,
            "weight": 2.0,
            "metric_unit": "percent",
            "reach_tolerance": None,
            "normalization_scale": 20.0,
        },
        {
            "objective_id": "obj-c",
            "metric_id": "m-1",
            "direction": "reach",
            "target": 50.0,
            "weight": 3.0,
            "metric_unit": "units",
            "reach_tolerance": 5.0,
            "normalization_scale": 50.0,
        },
    ]


def build_profile(
    *,
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    scenario_content_hash_value: str = "0" * 64,
    bindings: list[dict[str, object]] | None = None,
    declared_at: datetime = PROFILE_DECLARED_AT,
    metadata: dict[str, object] | None = None,
) -> ScenarioEvaluationProfile:
    """A contract-valid, self-hashed profile for direct builder/contract tests.

    The identifier is the real independent derivation over the canonical
    identity payload - never derived from the content hash - and the
    content hash is the real canonical digest, so the pure builder's
    re-derivation checks pass.
    """
    profile = ScenarioEvaluationProfile(
        identifier=evaluation_profile_identifier(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            scenario_content_hash_value=scenario_content_hash_value,
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        scenario_content_hash=scenario_content_hash_value,
        bindings=tuple(
            ObjectiveMetricBinding.model_validate(binding)
            for binding in (bindings if bindings is not None else _binding_payloads())
        ),
        content_hash="0" * 64,
        declared_at=declared_at,
        metadata=cast(dict[str, JsonValue], metadata or {}),
    )
    return profile.model_copy(update={"content_hash": evaluation_profile_content_hash(profile)})


def build_observation_matrix(
    *,
    strategy_ids: tuple[str, ...] = ("sc-1",),
    seed_ids: tuple[str, ...] = ("seed-1",),
    metric_ids: tuple[str, ...] = ("m-1", "m-2"),
    raw_values: dict[tuple[int, int, str], int | float] | None = None,
    campaign_id: str = "campaign-1",
    world_version_id: str = "world-0123456789abcdef",
    world_content_hash: str = "0" * 64,
    tenant_id: str = TENANT,
) -> CampaignMetricObservationMatrix:
    """A contract-valid, self-hashed Phase 21 observation matrix payload.

    One cell per strategy x seed in exact strategy-major, seed-minor
    order; every cell carries exactly one observation per metric in
    canonical metric order. ``raw_values`` overrides specific
    ``(strategy_position, seed_position, metric_id)`` raw values;
    defaults are 1 (integer, ``m-1``) and 1.5 (number, ``m-2``). The
    matrix identifier and content hash are the real derivations, so
    the Phase 23 builder's re-derivation checks pass.
    """
    cells: list[CampaignMetricObservationCell] = []
    sequence = 0
    for strategy_position, strategy_id in enumerate(strategy_ids):
        for seed_position, seed_id in enumerate(seed_ids):
            observations: list[RunMetricObservationValue] = []
            for metric_id in metric_ids:
                raw = (raw_values or {}).get(
                    (strategy_position, seed_position, metric_id),
                    1 if metric_id == "m-1" else 1.5,
                )
                observations.append(
                    RunMetricObservationValue(
                        metric_id=metric_id,
                        metric_unit="units" if metric_id == "m-1" else "percent",
                        binding_id=f"binding-{metric_id}",
                        binding_content_hash="0" * 64,
                        manifest_id="manifest-1",
                        state_model_identifier="state-model-1",
                        state_model_id="sm-1",
                        state_model_content_hash="0" * 64,
                        state_field_id="level" if metric_id == "m-1" else "ratio",
                        state_field_value_kind="integer" if metric_id == "m-1" else "number",
                        observation_point="final_state",
                        trajectory_plan_id=f"plan-{sequence}",
                        trajectory_plan_content_hash="0" * 64,
                        trajectory_result_content_hash="0" * 64,
                        raw_value=raw,
                    )
                )
            cells.append(
                CampaignMetricObservationCell(
                    sequence_position=sequence,
                    strategy_position=strategy_position,
                    seed_position=seed_position,
                    run_id=f"run-{sequence}",
                    run_plan_id=f"plan-{sequence}",
                    strategy_candidate_id=strategy_id,
                    scenario_seed_id=seed_id,
                    input_hash="0" * 64,
                    trajectory_execution_id=f"exec-{sequence}",
                    trajectory_execution_content_hash="0" * 64,
                    metric_observation_set_id=f"set-{sequence}",
                    metric_observation_set_content_hash="0" * 64,
                    observations=tuple(observations),
                )
            )
            sequence += 1
    matrix = CampaignMetricObservationMatrix(
        identifier=campaign_metric_observation_matrix_identifier(
            campaign_id=campaign_id,
            world_version_id=world_version_id,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ),
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id="scenario-1",
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ordered_strategy_candidate_ids=tuple(strategy_ids),
        ordered_scenario_seed_ids=tuple(seed_ids),
        ordered_metric_ids=tuple(metric_ids),
        cells=tuple(cells),
        content_hash="0" * 64,
        assembled_at=NOW,
    )
    return matrix.model_copy(
        update={"content_hash": campaign_metric_observation_matrix_content_hash(matrix)}
    )


def self_consistent_profile_copy(
    profile: ScenarioEvaluationProfile,
    **updates: object,
) -> ScenarioEvaluationProfile:
    """A ``model_copy``-tampered profile with a recomputed self-covering hash.

    The content hash is recomputed over the tampered content, so only
    the check under test can fail. The original profile is never
    mutated. Serializer warnings are expected and deliberately
    suppressed: a validator-bypassed nested value makes the canonical
    dump emit diagnostic noise while the hash is recomputed.
    """
    tampered = profile.model_copy(update=updates)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        digest = evaluation_profile_content_hash(tampered)
    return tampered.model_copy(update={"content_hash": digest})


def self_consistent_matrix_copy(
    matrix: CampaignObjectiveEvaluationMatrix,
    **updates: object,
) -> CampaignObjectiveEvaluationMatrix:
    """A ``model_copy``-tampered evaluation matrix with a recomputed hash."""
    tampered = matrix.model_copy(update=updates)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        digest = campaign_objective_evaluation_matrix_content_hash(tampered)
    return tampered.model_copy(update={"content_hash": digest})


def replace_evaluation_cell(
    matrix: CampaignObjectiveEvaluationMatrix,
    cell_index: int,
    **overrides: object,
) -> CampaignObjectiveEvaluationMatrix:
    """A self-consistent matrix copy with one evaluation cell replaced.

    The replacement cell is assembled with ``model_construct`` so
    validator-bypassed nested values (bool, NaN, Infinity) survive to
    the contract or builder checks under test - the cell payload is
    never re-validated.
    """
    cell = matrix.cells[cell_index]
    payload = cell.model_dump(mode="python")
    payload.update(overrides)
    replaced = ObjectiveObservationEvaluation.model_construct(**payload)
    cells = matrix.cells[:cell_index] + (replaced,) + matrix.cells[cell_index + 1 :]
    return self_consistent_matrix_copy(matrix, cells=cells)
