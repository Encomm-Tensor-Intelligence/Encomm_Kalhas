"""Tests for the pure deterministic Pareto-dominance and minimax-regret layer.

Tests for ``kalhas/application/campaign_decision_selection.py``: the
two public builders that transform one verified
``CampaignOutcomeDistributionMatrix``, one matching
``CampaignDecisionPolicy``, and the complete supplied
``ObjectivePairedComparison`` tuple into the immutable
``CampaignParetoDominanceAssessment`` (the accepted evidence
assessment - the sole feasibility source - the complete factual
``S * (S - 1)`` dominance relations with per-objective statuses read
from the supplied paired records, the factual dominated-by/dominates
tuples, and the feasible-only non-dominated strategy subset) and the
immutable ``CampaignMinimaxRegretAssessment`` (same-seed all-strategy
per-objective regret, weighted per-objective mean regrets, per-seed
total weighted regret vectors with their median/p95/maximum
statistics, the feasible non-dominated minimax candidates, the exact
inclusive minimax tie set, and the unique minimax strategy identity) -
together with the strict detached revalidation of every paired record,
the complete paired-matrix validation (cardinality, ordering, identity,
metric, tolerance, seed count, both-direction coverage, and every
reverse-pair invariant), the exact per-objective status semantics, the
feasible-only Pareto filtering, the exact same-seed regret and
inclusive tie-boundary semantics, and the purity/boundary guarantees.

Valid paired evidence is built through the accepted Slice 4 builder
(``build_ordered_objective_paired_comparisons``), feasibility through
the accepted Slice 5 builder, and expected statistical values through
the accepted Slice 3 primitives; neither algorithm is duplicated
inside these tests.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from kalhas.application.campaign_decision_paired_comparison import (
    build_ordered_objective_paired_comparisons,
)
from kalhas.application.campaign_decision_selection import (
    CampaignMinimaxRegretAssessment,
    CampaignParetoDominanceAssessment,
    StrategyDominanceAssessment,
    StrategyRegretAssessment,
    build_campaign_minimax_regret,
    build_campaign_pareto_dominance,
)
from kalhas.application.campaign_decision_statistics import (
    objective_weighted_mean_regret,
    same_seed_regret,
    total_regret_statistics,
    total_regret_vector,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    DominanceRelation,
    ObjectivePairedComparison,
    ObjectiveRegretEvidence,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_decision_selection.py"
)

TENANT = "tenant-1"
CAMPAIGN = "campaign-1"
SCENARIO = "scenario-1"
WORLD = "world-1"
PROFILE = "profile-1"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
TOLERANCE = 0.05
ALGORITHM = "feasibility-pareto-minimax-regret-v1"


def _binding(
    *,
    objective_id: str,
    metric_id: str,
    direction: str,
    target: float | None,
    weight: float,
    normalization_scale: float,
    reach_tolerance: float | None = None,
) -> ObjectiveMetricBinding:
    """One valid objective-to-metric binding for outcome construction."""
    payload: dict[str, object] = {
        "objective_id": objective_id,
        "metric_id": metric_id,
        "direction": direction,
        "target": target,
        "weight": weight,
        "metric_unit": "units",
        "reach_tolerance": reach_tolerance,
        "normalization_scale": normalization_scale,
    }
    return ObjectiveMetricBinding(**cast(Any, payload))


OBJ1_BINDING = _binding(
    objective_id="obj-1",
    metric_id="m-1",
    direction="minimize",
    target=100.0,
    weight=1.0,
    normalization_scale=100.0,
)
OBJ2_BINDING = _binding(
    objective_id="obj-2",
    metric_id="m-2",
    direction="maximize",
    target=50.0,
    weight=0.5,
    normalization_scale=10.0,
)
OBJ4_BINDING = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=0.25,
    normalization_scale=1.0,
)
OBJ5_BINDING = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=0.25,
    normalization_scale=10.0,
)


def _outcome(
    *,
    sequence_position: int,
    strategy_position: int,
    objective_position: int,
    strategy_candidate_id: str,
    binding: ObjectiveMetricBinding,
    ordered_observed_values: tuple[int | float, ...],
) -> StrategyObjectiveOutcome:
    """One outcome built by the accepted pure builder (never duplicated)."""
    return build_strategy_objective_outcome(
        sequence_position=sequence_position,
        strategy_position=strategy_position,
        objective_position=objective_position,
        strategy_candidate_id=strategy_candidate_id,
        binding=binding,
        ordered_observed_values=ordered_observed_values,
    )


def _matrix_payload(
    *,
    strategies: tuple[str, ...],
    seeds: tuple[str, ...],
    bindings: dict[str, ObjectiveMetricBinding],
    values: dict[tuple[str, str], tuple[int | float, ...]],
    **overrides: object,
) -> dict[str, object]:
    """One internally consistent matrix payload (all outcomes derived)."""
    objective_ids = tuple(bindings)
    metric_ids = tuple(bindings[objective_id].metric_id for objective_id in objective_ids)
    outcomes: list[StrategyObjectiveOutcome] = []
    for strategy_position, strategy_id in enumerate(strategies):
        for objective_position, objective_id in enumerate(objective_ids):
            outcomes.append(
                _outcome(
                    sequence_position=strategy_position * len(objective_ids) + objective_position,
                    strategy_position=strategy_position,
                    objective_position=objective_position,
                    strategy_candidate_id=strategy_id,
                    binding=bindings[objective_id],
                    ordered_observed_values=values[(strategy_id, objective_id)],
                )
            )
    payload: dict[str, object] = {
        "identifier": "matrix-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "uncertainty_model_id": None,
        "uncertainty_model_content_hash": None,
        "source_world_realization_matrix_id": "realization-matrix-1",
        "source_world_realization_matrix_content_hash": "d" * 64,
        "source_metric_observation_matrix_id": "observation-matrix-1",
        "source_metric_observation_matrix_content_hash": "e" * 64,
        "ordered_strategy_candidate_ids": list(strategies),
        "ordered_scenario_seed_ids": list(seeds),
        "ordered_objective_ids": list(objective_ids),
        "ordered_metric_ids": list(metric_ids),
        "outcomes": outcomes,
        "content_hash": "f" * 64,
        "derived_at": "2026-08-15T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _matrix_2x1(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted minimize objective x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99.5) and sc-b (100, 100, 100).
    Deltas sc-a -> sc-b: (-0.1, -0.05, -0.005) -> one win, two ties ->
    "better"; both strategies achieve 3/3 (probability 1.0) so both are
    feasible under a threshold <= 1.0.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 95, 99.5),
                ("sc-b", "obj-1"): (100, 100, 100),
            },
            **overrides,
        )
    )


def _matrix_3x2(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Three strategies x two targeted objectives x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99), sc-b (100, 100, 100),
    sc-c (150, 160, 170) - probabilities 1.0 / 1.0 / 0.0.
    obj-2 maximize (scale 10): sc-a (60, 55, 50), sc-b (50, 50, 50),
    sc-c (50, 50, 30) - probabilities 1.0 / 1.0 / 2/3.

    Factual relations: sc-a dominates sc-b (better/better) and sc-c
    (better/better); sc-b dominates sc-c (better/better); the reverse
    relations are worse/worse and no mutual dominance exists. sc-c is
    infeasible (obj-1 probability 0.0 under a 0.4 threshold).
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b", "sc-c"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 95, 99),
                ("sc-b", "obj-1"): (100, 100, 100),
                ("sc-c", "obj-1"): (150, 160, 170),
                ("sc-a", "obj-2"): (60, 55, 50),
                ("sc-b", "obj-2"): (50, 50, 50),
                ("sc-c", "obj-2"): (50, 50, 30),
            },
            **overrides,
        )
    )


def _matrix_better_tied(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two targeted objectives: one better, one tied.

    obj-1 minimize (scale 100): sc-a (85, 85, 85) -> delta -0.1 -> win;
    sc-b (95, 95, 95) - both probabilities 1.0.
    obj-2 maximize (scale 10): sc-a (50, 50, 50), sc-b (50, 50, 50) ->
    every delta exactly 0.0 -> tied. Both feasible.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING},
            values={
                ("sc-a", "obj-1"): (85, 85, 85),
                ("sc-b", "obj-1"): (95, 95, 95),
                ("sc-a", "obj-2"): (50, 50, 50),
                ("sc-b", "obj-2"): (50, 50, 50),
            },
            **overrides,
        )
    )


def _matrix_crossing(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one optimization-only objective with crossing deltas.

    obj-5 minimize (scale 10, no target): sc-a (100, 110, 90), sc-b
    (105, 105, 105). Deltas sc-a -> sc-b: (-0.5, 0.5, -1.5) -> mixed
    wins and losses -> "worse"; the reverse deltas (0.5, -0.5, 1.5) are
    also mixed -> "worse" in both directions; neither dominates.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-5": OBJ5_BINDING},
            values={
                ("sc-a", "obj-5"): (100, 110, 90),
                ("sc-b", "obj-5"): (105, 105, 105),
            },
            **overrides,
        )
    )


def _matrix_tolerance(
    values: tuple[int | float, ...],
    second_values: tuple[int | float, ...] = (0.0, 0.0, 0.0),
    **overrides: object,
) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one optimization-only minimize objective, scale 1.

    obj-4 minimize (scale 1, no target): sc-a carries the supplied
    values, sc-b the second values (all zeros by default), so every
    paired delta equals the difference exactly (subtraction of 0.0 is
    exact).
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-4": OBJ4_BINDING},
            values={
                ("sc-a", "obj-4"): values,
                ("sc-b", "obj-4"): second_values,
            },
            **overrides,
        )
    )


def _matrix_all_tied(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one optimization-only objective, every delta 0.0."""
    return _matrix_tolerance((1.0, 1.0, 1.0), second_values=(1.0, 1.0, 1.0), **overrides)


def _matrix_infeasible_dominator(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies: an infeasible factual dominator.

    obj-1 minimize (target 100, scale 100): sc-a (99, 99, 99) achieves
    3/3 (probability 1.0, feasible under threshold 1.0); sc-c
    (101, 101, 101) achieves 0/3 (infeasible). Deltas sc-c -> sc-a are
    +0.02 -> ties on obj-1.
    obj-2 minimize (scale 10, no target): sc-a (100, 100, 100), sc-c
    (50, 50, 50). Deltas sc-c -> sc-a: -5.0 -> wins -> "better". So the
    infeasible sc-c factually dominates the feasible sc-a (obj-1 tied,
    obj-2 better) while sc-a does not dominate sc-c (obj-1 tied, obj-2
    worse).
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-c"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING, "obj-5": OBJ5_BINDING},
            values={
                ("sc-a", "obj-1"): (99, 99, 99),
                ("sc-c", "obj-1"): (101, 101, 101),
                ("sc-a", "obj-5"): (100, 100, 100),
                ("sc-c", "obj-5"): (50, 50, 50),
            },
            **overrides,
        )
    )


def _matrix_zero_feasible(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted objective, both infeasible.

    obj-1 minimize (target 100, scale 100): sc-a (90, 90, 110) and
    sc-b (95, 95, 105) both achieve 2/3 (probability 2/3) - both fail a
    global threshold of 1.0. Deltas sc-a -> sc-b are exactly -0.05,
    -0.05, +0.05 -> all ties -> no dominance.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 90, 110),
                ("sc-b", "obj-1"): (95, 95, 105),
            },
            **overrides,
        )
    )


def _matrix_singleton_feasible(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted objective, exactly one feasible.

    obj-1 minimize (target 100, scale 100): sc-a (90, 90, 110)
    achieves 2/3; sc-b (95, 95, 100) achieves 3/3. Under a global
    threshold of 0.8 only sc-b is feasible. Deltas sc-a -> sc-b:
    (-0.05, -0.05, 0.1) -> mixed -> "worse"; no dominance either way.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 90, 110),
                ("sc-b", "obj-1"): (95, 95, 100),
            },
            **overrides,
        )
    )


def _policy_payload(
    *,
    requirements: tuple[tuple[str, float], ...] = (("obj-1", 0.4),),
    weight_snapshots: tuple[tuple[str, float], ...] = (("obj-1", 1.0),),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    hard_gates: bool = True,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent per-objective-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "policy-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "algorithm_identifier": ALGORITHM,
        "target_requirement_mode": "per_objective",
        "minimum_target_achievement_probability": None,
        "objective_target_requirements": [
            {"objective_id": objective_id, "minimum_target_achievement_probability": threshold}
            for objective_id, threshold in requirements
        ],
        "objective_weight_snapshots": [
            {"objective_id": objective_id, "weight": weight}
            for objective_id, weight in weight_snapshots
        ],
        "minimum_sample_count": minimum_sample_count,
        "tie_tolerance": tolerance,
        "all_targeted_objectives_are_hard_gates": hard_gates,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _policy_global_payload(
    *,
    threshold: float = 0.4,
    weight_snapshots: tuple[tuple[str, float], ...] = (("obj-1", 1.0),),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    hard_gates: bool = True,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent global-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "policy-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "algorithm_identifier": ALGORITHM,
        "target_requirement_mode": "global",
        "minimum_target_achievement_probability": threshold,
        "objective_target_requirements": [],
        "objective_weight_snapshots": [
            {"objective_id": objective_id, "weight": weight}
            for objective_id, weight in weight_snapshots
        ],
        "minimum_sample_count": minimum_sample_count,
        "tie_tolerance": tolerance,
        "all_targeted_objectives_are_hard_gates": hard_gates,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _policy(**overrides: Any) -> CampaignDecisionPolicy:
    """The per-objective policy matching the single-objective obj-1 matrices."""
    return CampaignDecisionPolicy.model_validate(_policy_payload(**overrides))


def _policy_3x2(**overrides: Any) -> CampaignDecisionPolicy:
    """The per-objective policy matching the two-targeted-objective matrices."""
    return CampaignDecisionPolicy.model_validate(
        _policy_payload(
            requirements=(("obj-1", 0.4), ("obj-2", 0.4)),
            weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
            **overrides,
        )
    )


def _policy_global(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the single-objective obj-1 matrices."""
    return CampaignDecisionPolicy.model_validate(_policy_global_payload(**overrides))


def _policy_global_obj4(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the optimization-only obj-4 matrices."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(weight_snapshots=(("obj-4", 0.25),), **overrides)
    )


def _policy_global_obj5(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the optimization-only obj-5 matrices."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(weight_snapshots=(("obj-5", 0.25),), **overrides)
    )


OBJ4_BINDING_W1 = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=1.0,
    normalization_scale=1.0,
)
OBJ5_BINDING_W1 = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=1.0,
    normalization_scale=1.0,
)
OBJ4_BINDING_W2 = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=2.0,
    normalization_scale=1.0,
)
OBJ5_BINDING_W05 = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=0.5,
    normalization_scale=1.0,
)
OBJ4_BINDING_ZERO = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=0.0,
    normalization_scale=1.0,
)
OBJ6_BINDING = _binding(
    objective_id="obj-6",
    metric_id="m-6",
    direction="reach",
    target=50.0,
    weight=0.5,
    normalization_scale=10.0,
    reach_tolerance=5.0,
)


def _matrix_two_objectives_optimization(
    *,
    values: dict[tuple[str, str], tuple[int | float, ...]],
    bindings: dict[str, ObjectiveMetricBinding],
    seeds: tuple[str, ...] = ("seed-0", "seed-1"),
    **overrides: object,
) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x the supplied optimization-only objectives x supplied seeds."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=seeds,
            bindings=bindings,
            values=values,
            **overrides,
        )
    )


def _matrix_maximize_golden(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted maximize objective x three seeds.

    obj-2 maximize (scale 10, target 50): sc-a (60, 55, 50) and
    sc-b (50, 50, 40) - sc-a wins every seed and dominates sc-b; both
    achieve 3/3 and 2/3 so both are feasible under a 0.4 threshold.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-2": OBJ2_BINDING},
            values={
                ("sc-a", "obj-2"): (60, 55, 50),
                ("sc-b", "obj-2"): (50, 50, 40),
            },
            **overrides,
        )
    )


def _matrix_reach(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one reach objective x three seeds.

    obj-6 reach (target 50, tolerance 5, scale 10): sc-a (50, 60, 45)
    and sc-b (55, 55, 55) - crossing wins and losses on the paired
    deltas so neither dominates; both feasible under a 0.4 threshold.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-6": OBJ6_BINDING},
            values={
                ("sc-a", "obj-6"): (50, 60, 45),
                ("sc-b", "obj-6"): (55, 55, 55),
            },
            **overrides,
        )
    )


def _matrix_boundary(
    obj4_sc_a: tuple[int | float, ...],
    obj5_sc_b: tuple[int | float, ...],
    **overrides: object,
) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two weight-1 minimize objectives with mirrored values.

    sc-a carries ``obj4_sc_a`` on obj-4 and zeros on obj-5; sc-b carries
    zeros on obj-4 and ``obj5_sc_b`` on obj-5 - crossing wins on the two
    objectives so neither strategy dominates and both stay candidates.
    """
    return _matrix_two_objectives_optimization(
        values={
            ("sc-a", "obj-4"): obj4_sc_a,
            ("sc-b", "obj-4"): (0.0, 0.0),
            ("sc-a", "obj-5"): (0.0, 0.0),
            ("sc-b", "obj-5"): obj5_sc_b,
        },
        bindings={"obj-4": OBJ4_BINDING_W1, "obj-5": OBJ5_BINDING_W1},
        **cast(Any, overrides),
    )


def _matrix_no_normalization(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two minimize objectives with raw weights 2.0 and 0.5."""
    return _matrix_two_objectives_optimization(
        values={
            ("sc-a", "obj-4"): (10, 20),
            ("sc-b", "obj-4"): (20, 10),
            ("sc-a", "obj-5"): (10, 20),
            ("sc-b", "obj-5"): (20, 10),
        },
        bindings={"obj-4": OBJ4_BINDING_W2, "obj-5": OBJ5_BINDING_W05},
        **cast(Any, overrides),
    )


def _matrix_zero_weight(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one zero-weight minimize objective, every value 1.0."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-4": OBJ4_BINDING_ZERO},
            values={
                ("sc-a", "obj-4"): (1.0, 1.0, 1.0),
                ("sc-b", "obj-4"): (1.0, 1.0, 1.0),
            },
            **overrides,
        )
    )


def _policy_global_obj2(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the single targeted maximize obj-2 matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(weight_snapshots=(("obj-2", 0.5),), **overrides)
    )


def _policy_reach(**overrides: Any) -> CampaignDecisionPolicy:
    """The per-objective policy matching the reach matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_payload(
            requirements=(("obj-6", 0.4),),
            weight_snapshots=(("obj-6", 0.5),),
            **overrides,
        )
    )


def _policy_boundary(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the two weight-1 objective boundary matrices."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(
            weight_snapshots=(("obj-4", 1.0), ("obj-5", 1.0)),
            minimum_sample_count=2,
            **overrides,
        )
    )


def _policy_no_normalization(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the raw-weight 2.0/0.5 objective matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(
            weight_snapshots=(("obj-4", 2.0), ("obj-5", 0.5)),
            minimum_sample_count=2,
            **overrides,
        )
    )


def _policy_zero_weight(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the zero-weight all-tied matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_global_payload(weight_snapshots=(("obj-4", 0.0),), **overrides)
    )


def _pairs(
    policy: CampaignDecisionPolicy, matrix: CampaignOutcomeDistributionMatrix
) -> tuple[ObjectivePairedComparison, ...]:
    """The complete paired evidence through the accepted Slice 4 builder."""
    return build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)


def _assessment(
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    paired: tuple[ObjectivePairedComparison, ...] | None = None,
) -> CampaignParetoDominanceAssessment:
    """One complete Pareto dominance assessment over accepted paired evidence."""
    return build_campaign_pareto_dominance(
        policy=policy,
        outcome_matrix=matrix,
        paired_comparisons=paired or _pairs(policy, matrix),
    )


def _minimax(
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    paired: tuple[ObjectivePairedComparison, ...] | None = None,
) -> CampaignMinimaxRegretAssessment:
    """One complete minimax regret assessment over accepted paired evidence."""
    return build_campaign_minimax_regret(
        policy=policy,
        outcome_matrix=matrix,
        paired_comparisons=paired or _pairs(policy, matrix),
    )


def _regret_by_strategy(
    assessment: CampaignMinimaxRegretAssessment,
) -> dict[str, StrategyRegretAssessment]:
    return {
        record.strategy_candidate_id: record for record in assessment.strategy_regret_assessments
    }


def _minimax_with_pareto(
    monkeypatch: pytest.MonkeyPatch,
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    paired: tuple[ObjectivePairedComparison, ...],
    pareto_result: CampaignParetoDominanceAssessment,
) -> CampaignMinimaxRegretAssessment:
    """Run the minimax builder with a patched Pareto builder returning the result."""
    import kalhas.application.campaign_decision_selection as selection_module

    def fake(*, policy: Any, outcome_matrix: Any, paired_comparisons: Any) -> Any:
        return pareto_result

    monkeypatch.setattr(selection_module, "build_campaign_pareto_dominance", fake)
    return selection_module.build_campaign_minimax_regret(
        policy=policy, outcome_matrix=matrix, paired_comparisons=paired
    )


def _construct_matrix_with_bad_outcome(
    matrix: CampaignOutcomeDistributionMatrix,
    position: int,
    **changes: object,
) -> CampaignOutcomeDistributionMatrix:
    """A validator-bypassed matrix copy with one tampered outcome."""
    original = matrix.outcomes[position]
    payload = original.model_dump(mode="python")
    payload.update(changes)
    payload["empirical_distribution"] = original.empirical_distribution
    payload["normalized_target_violation_distribution"] = (
        original.normalized_target_violation_distribution
    )
    bad_outcome = StrategyObjectiveOutcome.model_construct(**payload)
    matrix_payload = matrix.model_dump(mode="python")
    matrix_payload["outcomes"] = [
        bad_outcome if index == position else outcome
        for index, outcome in enumerate(matrix.outcomes)
    ]
    return CampaignOutcomeDistributionMatrix.model_construct(**matrix_payload)


def _mutated(record: ObjectivePairedComparison, **changes: object) -> ObjectivePairedComparison:
    """A validator-bypassed copy of one paired record with changed fields."""
    payload = record.model_dump(mode="python")
    payload.update(changes)
    return ObjectivePairedComparison.model_construct(**payload)


def _mutated_relation(relation: DominanceRelation, **changes: object) -> DominanceRelation:
    """A validator-bypassed copy of one dominance relation with changed fields."""
    payload = relation.model_dump(mode="python")
    payload.update(changes)
    return DominanceRelation.model_construct(**payload)


def _relations_by_pair(
    assessment: CampaignParetoDominanceAssessment,
) -> dict[tuple[int, int], DominanceRelation]:
    return {
        (relation.first_strategy_position, relation.second_strategy_position): relation
        for relation in assessment.dominance_relations
    }


def _comparison_payload(
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    paired: tuple[ObjectivePairedComparison, ...],
    assessment: CampaignParetoDominanceAssessment,
) -> dict[str, Any]:
    """A structurally complete CampaignStrategyComparison payload embedding the outputs.

    Robustness profiles copy the feasibility/evidence records from the
    accepted evidence assessment and carry zero-weighted regrets (the
    later pipeline owns real regret values); the dominance tuples come
    from this slice's factual assessments. This proves the outputs
    satisfy the comparison contract's structural expectations.
    """
    strategy_ids = matrix.ordered_strategy_candidate_ids
    objective_ids = matrix.ordered_objective_ids
    seed_count = len(matrix.ordered_scenario_seed_ids)
    evidence = assessment.evidence_assessment
    profiles: list[dict[str, Any]] = []
    for position, strategy_id in enumerate(strategy_ids):
        feasibility = evidence.strategy_assessments[position]
        strategy_assessment = assessment.strategy_assessments[position]
        profiles.append(
            {
                "strategy_position": position,
                "strategy_candidate_id": strategy_id,
                "feasible": feasibility.feasible,
                "target_feasibility": [
                    record.model_dump(mode="python") for record in feasibility.target_feasibility
                ],
                "dominated_by": list(strategy_assessment.dominated_by),
                "dominates": list(strategy_assessment.dominates),
                "per_objective_weighted_regret": [
                    {"objective_id": objective_id, "weighted_regret": 0.0}
                    for objective_id in objective_ids
                ],
                "per_seed_total_weighted_regrets": [0.0] * seed_count,
                "median_total_weighted_regret": 0.0,
                "p95_total_weighted_regret": 0.0,
                "maximum_total_weighted_regret": 0.0,
                "target_achievement_probabilities": [
                    record.model_dump(mode="python")
                    for record in feasibility.target_achievement_probabilities
                ],
                "downside_evidence": [
                    record.model_dump(mode="python") for record in feasibility.downside_evidence
                ],
            }
        )
    return {
        "identifier": "comparison-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "algorithm_identifier": ALGORITHM,
        "policy_id": policy.identifier,
        "policy_content_hash": policy.content_hash,
        "tie_tolerance": policy.tie_tolerance,
        "minimum_sample_count": policy.minimum_sample_count,
        "source_outcome_matrix_id": matrix.identifier,
        "source_outcome_matrix_content_hash": matrix.content_hash,
        "ordered_strategy_candidate_ids": list(strategy_ids),
        "ordered_scenario_seed_ids": list(matrix.ordered_scenario_seed_ids),
        "ordered_objective_ids": list(objective_ids),
        "paired_comparisons": [record.model_dump(mode="python") for record in paired],
        "dominance_relations": [
            relation.model_dump(mode="python") for relation in assessment.dominance_relations
        ],
        "robustness_profiles": profiles,
        "content_hash": "9" * 64,
        "derived_at": "2026-08-17T12:00:00Z",
    }


class TestPublicSurface:
    """Section A: public surface, purity, and input guarantees."""

    def test_exact_all(self) -> None:
        import kalhas.application.campaign_decision_selection as module

        assert module.__all__ == [
            "CampaignMinimaxRegretAssessment",
            "CampaignParetoDominanceAssessment",
            "StrategyDominanceAssessment",
            "StrategyRegretAssessment",
            "build_campaign_minimax_regret",
            "build_campaign_pareto_dominance",
        ]

    def test_exact_keyword_only_signatures(self) -> None:
        for builder, return_type in (
            (build_campaign_pareto_dominance, CampaignParetoDominanceAssessment),
            (build_campaign_minimax_regret, CampaignMinimaxRegretAssessment),
        ):
            signature = inspect.signature(builder)
            parameters = list(signature.parameters.values())
            assert [parameter.name for parameter in parameters] == [
                "policy",
                "outcome_matrix",
                "paired_comparisons",
            ]
            assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters)
            hints = get_type_hints(builder)
            assert hints["policy"] is CampaignDecisionPolicy
            assert hints["outcome_matrix"] is CampaignOutcomeDistributionMatrix
            assert hints["paired_comparisons"] == tuple[ObjectivePairedComparison, ...]
            assert hints["return"] is return_type

    def test_exact_named_tuple_fields(self) -> None:
        assert StrategyDominanceAssessment._fields == (
            "strategy_position",
            "strategy_candidate_id",
            "feasible",
            "dominated_by",
            "dominates",
            "non_dominated_among_feasible",
        )
        assert CampaignParetoDominanceAssessment._fields == (
            "evidence_assessment",
            "dominance_relations",
            "strategy_assessments",
            "non_dominated_feasible_strategy_ids",
        )
        assert StrategyRegretAssessment._fields == (
            "strategy_position",
            "strategy_candidate_id",
            "per_objective_weighted_regret",
            "per_seed_total_weighted_regrets",
            "median_total_weighted_regret",
            "p95_total_weighted_regret",
            "maximum_total_weighted_regret",
        )
        assert CampaignMinimaxRegretAssessment._fields == (
            "pareto_assessment",
            "strategy_regret_assessments",
            "minimax_candidate_ids",
            "minimax_evaluated",
            "best_maximum_total_weighted_regret",
            "minimax_tie_strategy_ids",
            "unique_minimax_strategy_id",
        )
        assert issubclass(StrategyDominanceAssessment, tuple)
        assert issubclass(CampaignParetoDominanceAssessment, tuple)
        assert issubclass(StrategyRegretAssessment, tuple)
        assert issubclass(CampaignMinimaxRegretAssessment, tuple)

    def test_result_immutability(self) -> None:
        assessment = _assessment(_policy_3x2(), _matrix_3x2())
        with pytest.raises(AttributeError):
            assessment.dominance_relations = ()  # type: ignore[misc]
        with pytest.raises(AttributeError):
            assessment.non_dominated_feasible_strategy_ids = ()  # type: ignore[misc]
        with pytest.raises(AttributeError):
            assessment.strategy_assessments[0].dominates = ()  # type: ignore[misc]
        strategy_assessment = assessment.strategy_assessments[0]
        assert isinstance(strategy_assessment, StrategyDominanceAssessment)

        minimax = _minimax(_policy_3x2(), _matrix_3x2())
        with pytest.raises(AttributeError):
            minimax.strategy_regret_assessments = ()  # type: ignore[misc]
        with pytest.raises(AttributeError):
            minimax.minimax_candidate_ids = ()  # type: ignore[misc]
        with pytest.raises(AttributeError):
            minimax.strategy_regret_assessments[0].per_objective_weighted_regret = ()  # type: ignore[misc]
        regret_assessment = minimax.strategy_regret_assessments[0]
        assert isinstance(regret_assessment, StrategyRegretAssessment)

    def test_exact_import_allowlist(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        allowed = {
            "__future__",
            "math",
            "warnings",
            "typing",
            "pydantic",
            "kalhas.application.campaign_decision_evidence",
            "kalhas.application.campaign_decision_statistics",
            "kalhas.contracts.v1.campaign_decision",
            "kalhas.contracts.v1.campaign_outcome",
        }
        paths: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                paths.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                paths.add(node.module)
        assert paths == allowed

    def test_forbidden_imports_absent(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        paths: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                paths.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                paths.add(node.module)
        forbidden = {
            "kalhas.application.campaign_decision_paired_comparison",
            "kalhas.application.campaign_decision_identity",
            "kalhas.application.campaign_decision_errors",
            "kalhas.application.campaign_decision_policy_service",
            "kalhas.application.in_memory_store",
            "kalhas.application.campaign_outcome_runtime",
            "kalhas.application.campaign_outcome_statistics",
            "kalhas.application.campaign_outcome_identity",
            "kalhas.application.campaign_outcome_errors",
            "kalhas.application.campaign_outcome_matrix_runtime",
            "kalhas.application.campaign_outcome_query_service",
            "kalhas.application.hashing",
            "kalhas.api",
            "kalhas.adapters",
            "kalhas.domain_packs",
        }
        assert not any(
            path == forbidden_path or path.startswith(forbidden_path + ".")
            for path in paths
            for forbidden_path in forbidden
        )

    def test_no_terminal_recommendation_or_service_surface(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        forbidden = {
            "terminal",
            "preferred",
            "inconclusive",
            "insufficient",
            "reason",
            "factor",
            "brief",
            "hash",
            "identity",
            "store",
            "api",
            "query",
            "activity",
            "replay",
            "execution",
            "uuid",
            "random",
            "clock",
            "datetime",
        }
        assert not (names & forbidden)

    def test_no_clock_randomness_or_ordering_builtins(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        chains: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            parts: list[str] = []
            target: Any = node.func
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            chains.add(".".join(reversed(parts)))
        bare_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        forbidden_chains = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "time.time",
            "time.monotonic",
            "random.seed",
            "random.random",
            "os.urandom",
            "uuid.uuid4",
        }
        assert not (chains & forbidden_chains)
        assert not any(chain.startswith("random.") for chain in chains)
        assert not (bare_calls & {"sorted", "reversed", "hash"})

    def test_evidence_builder_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        calls: list[tuple[Any, Any]] = []
        original = selection_module.build_campaign_decision_evidence  # type: ignore[attr-defined]

        def counting(*, policy: Any, outcome_matrix: Any) -> Any:
            calls.append((policy, outcome_matrix))
            return original(policy=policy, outcome_matrix=outcome_matrix)

        monkeypatch.setattr(selection_module, "build_campaign_decision_evidence", counting)
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = selection_module.build_campaign_pareto_dominance(
            policy=policy, outcome_matrix=matrix, paired_comparisons=paired
        )
        assert len(calls) == 1
        assert calls[0] == (policy, matrix)
        assert assessment.evidence_assessment is not None

    def test_repeated_calls_return_equal_assessments(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        first = _assessment(policy, matrix)
        second = _assessment(policy, matrix)
        assert first == second
        assert first.dominance_relations == second.dominance_relations
        assert first.strategy_assessments == second.strategy_assessments
        assert (
            first.non_dominated_feasible_strategy_ids == second.non_dominated_feasible_strategy_ids
        )

    def test_all_inputs_unchanged(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        policy_before = policy.model_dump(mode="python")
        matrix_before = matrix.model_dump(mode="python")
        paired_before = [record.model_dump(mode="python") for record in paired]
        _assessment(policy, matrix, paired)
        assert policy.model_dump(mode="python") == policy_before
        assert matrix.model_dump(mode="python") == matrix_before
        assert [record.model_dump(mode="python") for record in paired] == paired_before


class TestCardinalityAndOrdering:
    """Section B: exact cardinality, deterministic ordering, and coverage."""

    def test_exact_record_and_relation_cardinality(self) -> None:
        for matrix, policy in (
            (_matrix_2x1(), _policy()),
            (_matrix_3x2(), _policy_3x2()),
            (_matrix_crossing(), _policy_global_obj5()),
        ):
            paired = _pairs(policy, matrix)
            strategy_count = len(matrix.ordered_strategy_candidate_ids)
            objective_count = len(matrix.ordered_objective_ids)
            assert len(paired) == strategy_count * (strategy_count - 1) * objective_count
            assessment = _assessment(policy, matrix, paired)
            assert len(assessment.dominance_relations) == strategy_count * (strategy_count - 1)
            assert len(assessment.strategy_assessments) == strategy_count

    def test_exact_pair_and_objective_ordering(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        strategy_count = len(matrix.ordered_strategy_candidate_ids)
        expected_pairs = [
            (first, second)
            for first in range(strategy_count)
            for second in range(strategy_count)
            if first != second
        ]
        observed_pairs = [
            (relation.first_strategy_position, relation.second_strategy_position)
            for relation in assessment.dominance_relations
        ]
        assert observed_pairs == expected_pairs
        objective_ids = list(matrix.ordered_objective_ids)
        for relation in assessment.dominance_relations:
            assert [
                status.objective_id for status in relation.per_objective_status
            ] == objective_ids

    def test_exact_positions_and_identities(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        strategy_ids = matrix.ordered_strategy_candidate_ids
        for relation in assessment.dominance_relations:
            assert (
                relation.first_strategy_candidate_id
                == strategy_ids[relation.first_strategy_position]
            )
            assert (
                relation.second_strategy_candidate_id
                == strategy_ids[relation.second_strategy_position]
            )
        for position, strategy_assessment in enumerate(assessment.strategy_assessments):
            assert strategy_assessment.strategy_position == position
            assert strategy_assessment.strategy_candidate_id == strategy_ids[position]

    def test_complete_both_direction_coverage_no_self_pairs(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        strategy_count = len(matrix.ordered_strategy_candidate_ids)
        pairs = {
            (relation.first_strategy_position, relation.second_strategy_position)
            for relation in assessment.dominance_relations
        }
        expected = {
            (first, second)
            for first in range(strategy_count)
            for second in range(strategy_count)
            if first != second
        }
        assert pairs == expected
        assert all(first != second for first, second in pairs)

    def test_outputs_embed_in_campaign_strategy_comparison(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        comparison = CampaignStrategyComparison.model_validate(
            _comparison_payload(policy, matrix, paired, assessment)
        )
        assert len(comparison.dominance_relations) == len(assessment.dominance_relations)
        assert comparison.tie_tolerance == policy.tie_tolerance

    def test_exact_status_counts_and_median_copied(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        records_by_key = {
            (
                record.first_strategy_position,
                record.second_strategy_position,
                record.objective_position,
            ): record
            for record in paired
        }
        for relation in assessment.dominance_relations:
            first = relation.first_strategy_position
            second = relation.second_strategy_position
            for objective_position, status in enumerate(relation.per_objective_status):
                record = records_by_key[(first, second, objective_position)]
                assert status.objective_id == record.objective_id
                assert status.win_count == record.win_count
                assert status.tie_count == record.tie_count
                assert status.loss_count == record.loss_count
                assert status.median_paired_delta == record.median_paired_delta


class TestDominanceSemantics:
    """Section C: exact per-objective statuses and factual dominance."""

    def test_one_objective_better_none_worse_dominates(self) -> None:
        matrix = _matrix_2x1()
        assessment = _assessment(_policy_global(), matrix)
        relation = _relations_by_pair(assessment)[(0, 1)]
        assert relation.dominates is True
        assert relation.per_objective_status[0].status == "better"
        assert relation.per_objective_status[0].win_count == 1
        assert relation.per_objective_status[0].loss_count == 0

    def test_one_better_one_tied_dominates(self) -> None:
        matrix = _matrix_better_tied()
        assessment = _assessment(_policy_3x2(), matrix)
        relation = _relations_by_pair(assessment)[(0, 1)]
        statuses = relation.per_objective_status
        assert [status.status for status in statuses] == ["better", "tied"]
        assert relation.dominates is True
        reverse = _relations_by_pair(assessment)[(1, 0)]
        assert [status.status for status in reverse.per_objective_status] == ["worse", "tied"]
        assert reverse.dominates is False

    def test_all_tied_no_dominance(self) -> None:
        matrix = _matrix_all_tied()
        assessment = _assessment(_policy_global_obj4(), matrix)
        relation = _relations_by_pair(assessment)[(0, 1)]
        assert relation.per_objective_status[0].status == "tied"
        assert relation.per_objective_status[0].tie_count == 3
        assert relation.dominates is False

    def test_any_worse_objective_blocks_dominance(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        relations = _relations_by_pair(assessment)
        assert relations[(1, 0)].dominates is False  # sc-b -> sc-a: worse/worse
        assert relations[(2, 0)].dominates is False  # sc-c -> sc-a: worse/worse
        assert relations[(2, 1)].dominates is False  # sc-c -> sc-b: worse/worse
        for relation in assessment.dominance_relations:
            if relation.dominates:
                statuses = [status.status for status in relation.per_objective_status]
                assert "worse" not in statuses
                assert "better" in statuses

    def test_crossing_wins_and_losses_is_worse(self) -> None:
        matrix = _matrix_crossing()
        assessment = _assessment(_policy_global_obj5(), matrix)
        forward = _relations_by_pair(assessment)[(0, 1)]
        reverse = _relations_by_pair(assessment)[(1, 0)]
        assert forward.per_objective_status[0].status == "worse"
        assert forward.per_objective_status[0].win_count == 2
        assert forward.per_objective_status[0].loss_count == 1
        assert reverse.per_objective_status[0].status == "worse"
        assert reverse.per_objective_status[0].win_count == 1
        assert reverse.per_objective_status[0].loss_count == 2
        assert forward.dominates is False
        assert reverse.dominates is False

    def test_no_mutual_dominance_across_all_fixtures(self) -> None:
        fixtures = [
            (_policy_3x2(), _matrix_3x2()),
            (_policy_3x2(), _matrix_better_tied()),
            (_policy(), _matrix_2x1()),
            (_policy_global_obj5(), _matrix_crossing()),
            (_policy_global_obj4(), _matrix_all_tied()),
        ]
        for policy, matrix in fixtures:
            assessment = _assessment(policy, matrix)
            relations = _relations_by_pair(assessment)
            for (first, second), relation in relations.items():
                assert not (relation.dominates and relations[(second, first)].dominates)

    def test_forward_and_reverse_statuses_read_independently(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        relations = _relations_by_pair(assessment)
        forward = relations[(0, 1)]  # sc-a -> sc-b: better/better
        reverse = relations[(1, 0)]  # sc-b -> sc-a: worse/worse
        assert [status.status for status in forward.per_objective_status] == [
            "better",
            "better",
        ]
        assert [status.status for status in reverse.per_objective_status] == ["worse", "worse"]
        assert forward.dominates is True
        assert reverse.dominates is False

    def test_exact_tolerance_boundaries_remain_ties(self) -> None:
        matrix = _matrix_tolerance((0.05, -0.05, 0.0))
        assessment = _assessment(_policy_global_obj4(), matrix)
        status = _relations_by_pair(assessment)[(0, 1)].per_objective_status[0]
        assert status.status == "tied"
        assert status.win_count == 0
        assert status.loss_count == 0
        assert status.tie_count == 3

    def test_nextafter_beyond_tolerance_boundaries_win_and_loss(self) -> None:
        below = math.nextafter(-TOLERANCE, -math.inf)
        above = math.nextafter(TOLERANCE, math.inf)
        assert below < -TOLERANCE
        assert above > TOLERANCE

        win_matrix = _matrix_tolerance((below, below, below))
        win_assessment = _assessment(_policy_global_obj4(), win_matrix)
        win_status = _relations_by_pair(win_assessment)[(0, 1)].per_objective_status[0]
        assert win_status.status == "better"
        assert win_status.win_count == 3
        assert win_status.loss_count == 0

        loss_matrix = _matrix_tolerance((above, above, above))
        loss_assessment = _assessment(_policy_global_obj4(), loss_matrix)
        loss_status = _relations_by_pair(loss_assessment)[(0, 1)].per_objective_status[0]
        assert loss_status.status == "worse"
        assert loss_status.loss_count == 3
        assert loss_status.win_count == 0

    def test_better_status_requires_no_losses_and_at_least_one_win(self) -> None:
        matrix = _matrix_2x1()
        assessment = _assessment(_policy_global(), matrix)
        status = _relations_by_pair(assessment)[(0, 1)].per_objective_status[0]
        assert status.loss_count == 0
        assert status.win_count > 0
        assert status.status == "better"


class TestFeasibleParetoSubset:
    """Section D: feasible-only non-dominated filtering."""

    def test_all_feasible_with_dominance(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a",)
        sc_b = assessment.strategy_assessments[1]
        assert sc_b.feasible is True
        assert sc_b.non_dominated_among_feasible is False

    def test_mixed_feasible_infeasible(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        assert [strategy.feasible for strategy in assessment.strategy_assessments] == [
            True,
            True,
            False,
        ]
        sc_c = assessment.strategy_assessments[2]
        assert sc_c.non_dominated_among_feasible is False
        assert "sc-c" not in assessment.non_dominated_feasible_strategy_ids

    def test_infeasible_factual_dominator_does_not_exclude_feasible(self) -> None:
        policy = _policy(
            requirements=(("obj-1", 1.0),),
            weight_snapshots=(("obj-1", 1.0), ("obj-5", 0.25)),
        )
        matrix = _matrix_infeasible_dominator()
        assessment = _assessment(policy, matrix)
        assert [strategy.feasible for strategy in assessment.strategy_assessments] == [
            True,
            False,
        ]
        relations = _relations_by_pair(assessment)
        assert relations[(1, 0)].dominates is True  # sc-c (infeasible) dominates sc-a
        assert relations[(0, 1)].dominates is False
        sc_a = assessment.strategy_assessments[0]
        assert sc_a.dominated_by == ("sc-c",)
        assert sc_a.non_dominated_among_feasible is True
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a",)

    def test_infeasible_strategy_never_enters_subset(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        for strategy in assessment.strategy_assessments:
            if strategy.strategy_candidate_id == "sc-c":
                assert strategy.feasible is False
                assert strategy.non_dominated_among_feasible is False
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a",)

    def test_zero_feasible_empty_subset(self) -> None:
        policy = _policy_global(threshold=1.0)
        matrix = _matrix_zero_feasible()
        assessment = _assessment(policy, matrix)
        assert assessment.non_dominated_feasible_strategy_ids == ()
        assert all(strategy.feasible is False for strategy in assessment.strategy_assessments)
        assert all(
            strategy.non_dominated_among_feasible is False
            for strategy in assessment.strategy_assessments
        )
        # the factual relations are still complete
        assert len(assessment.dominance_relations) == 2
        assert _relations_by_pair(assessment)[(0, 1)].dominates is False

    def test_singleton_feasible_subset(self) -> None:
        policy = _policy_global(threshold=0.8)
        matrix = _matrix_singleton_feasible()
        assessment = _assessment(policy, matrix)
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-b",)
        assert [strategy.feasible for strategy in assessment.strategy_assessments] == [
            False,
            True,
        ]

    def test_all_feasible_tied_all_non_dominated(self) -> None:
        matrix = _matrix_all_tied()
        assessment = _assessment(_policy_global_obj4(), matrix)
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a", "sc-b")
        assert all(
            strategy.non_dominated_among_feasible for strategy in assessment.strategy_assessments
        )

    def test_factual_tuples_unfiltered_by_feasibility(self) -> None:
        matrix = _matrix_3x2()
        assessment = _assessment(_policy_3x2(), matrix)
        sc_c = assessment.strategy_assessments[2]
        assert sc_c.dominated_by == ("sc-a", "sc-b")
        assert sc_c.dominates == ()
        sc_a = assessment.strategy_assessments[0]
        assert sc_a.dominated_by == ()
        assert sc_a.dominates == ("sc-b", "sc-c")
        # sc-b's dominance over the infeasible sc-c is factual and retained
        sc_b = assessment.strategy_assessments[1]
        assert sc_b.dominates == ("sc-c",)

    def test_below_minimum_evidence_returns_complete_relations(self) -> None:
        policy = _policy(minimum_sample_count=5)
        matrix = _matrix_2x1()
        assessment = _assessment(policy, matrix)
        assert assessment.evidence_assessment.recorded_sample_count == 3
        assert assessment.evidence_assessment.minimum_sample_count == 5
        assert assessment.evidence_assessment.sufficient is False
        assert len(assessment.dominance_relations) == 2
        assert _relations_by_pair(assessment)[(0, 1)].dominates is True
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a",)


class TestRegretGolden:
    """Section B: exact same-seed weighted regret semantics."""

    def test_minimize_same_seed_vectors_golden(self) -> None:
        assessment = _minimax(_policy(), _matrix_2x1())
        records = _regret_by_strategy(assessment)
        # obj-1 minimize scale 100: seed minima are 90, 95, 99.5 (sc-a),
        # so sc-b carries (0.1, 0.05, 0.005) and sc-a exactly 0.0.
        assert records["sc-a"].per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.1, 0.05, 0.005)
        assert records["sc-b"].per_objective_weighted_regret == (
            ObjectiveRegretEvidence(
                objective_id="obj-1",
                weighted_regret=objective_weighted_mean_regret((0.1, 0.05, 0.005), weight=1.0),
            ),
        )

    def test_maximize_same_seed_vectors_golden(self) -> None:
        assessment = _minimax(_policy_global_obj2(), _matrix_maximize_golden())
        records = _regret_by_strategy(assessment)
        # obj-2 maximize scale 10: seed maxima are 60, 55, 50 (sc-a),
        # so sc-b carries (1.0, 0.5, 1.0) and sc-a exactly 0.0; the
        # totals apply the exact weight 0.5.
        assert records["sc-a"].per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.5, 0.25, 0.5)
        assert records["sc-b"].per_objective_weighted_regret == (
            ObjectiveRegretEvidence(
                objective_id="obj-2",
                weighted_regret=objective_weighted_mean_regret((1.0, 0.5, 1.0), weight=0.5),
            ),
        )

    def test_reach_same_seed_vectors_golden(self) -> None:
        assessment = _minimax(_policy_reach(), _matrix_reach())
        records = _regret_by_strategy(assessment)
        # obj-6 reach (target 50, scale 10): deviations sc-a (0, 10, 5),
        # sc-b (5, 5, 5); seed minima 0, 5, 5 give sc-a (0.0, 0.5, 0.0)
        # and sc-b (0.5, 0.0, 0.0). The tied seed-2 best receives 0.0.
        assert records["sc-a"].per_seed_total_weighted_regrets == (0.0, 0.25, 0.0)
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.25, 0.0, 0.0)
        assert records["sc-a"].per_seed_total_weighted_regrets[2] == 0.0
        assert records["sc-b"].per_seed_total_weighted_regrets[2] == 0.0
        assert records["sc-a"].per_objective_weighted_regret == (
            ObjectiveRegretEvidence(
                objective_id="obj-6",
                weighted_regret=objective_weighted_mean_regret((0.0, 0.5, 0.0), weight=0.5),
            ),
        )

    def test_multiple_objectives_and_seeds_three_strategy_golden(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        records = _regret_by_strategy(assessment)
        # obj-1 minimize scale 100 over (90,100,150), (95,100,160),
        # (99,100,170); obj-2 maximize scale 10 over (60,50,50),
        # (55,50,50), (50,50,30). sc-b's per-seed totals are exactly
        # (0.6, 0.3, 0.01) and its obj-2 regrets (1.0, 0.5, 0.0) are
        # computed against all three strategies (seed-1 maximum 55).
        assert records["sc-a"].per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.6, 0.3, 0.01)
        obj1_vectors = [
            same_seed_regret(values, direction="minimize", normalization_scale=100)
            for values in ((90, 100, 150), (95, 100, 160), (99, 100, 170))
        ]
        obj2_vectors = [
            same_seed_regret(values, direction="maximize", normalization_scale=10)
            for values in ((60, 50, 50), (55, 50, 50), (50, 50, 30))
        ]
        expected_sc_c = total_regret_vector(
            (
                tuple(vector[2] for vector in obj1_vectors),
                tuple(vector[2] for vector in obj2_vectors),
            ),
            (1.0, 0.5),
        )
        assert records["sc-c"].per_seed_total_weighted_regrets == expected_sc_c
        assert records["sc-c"].per_seed_total_weighted_regrets == (1.1, 0.9, 1.71)

    def test_tied_same_seed_best_strategies_receive_zero(self) -> None:
        assessment = _minimax(_policy_global_obj4(), _matrix_all_tied())
        records = _regret_by_strategy(assessment)
        assert records["sc-a"].per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)

    def test_comparator_includes_infeasible_strategy(self) -> None:
        policy = _policy(
            requirements=(("obj-1", 1.0),),
            weight_snapshots=(("obj-1", 1.0), ("obj-5", 0.25)),
        )
        assessment = _minimax(policy, _matrix_infeasible_dominator())
        records = _regret_by_strategy(assessment)
        # The infeasible sc-c (50) is the same-seed best on obj-5
        # minimize (scale 10), so the feasible sc-a carries regret 5.0
        # on every seed - proof the comparator includes sc-c.
        assert records["sc-a"].per_seed_total_weighted_regrets == (1.25, 1.25, 1.25)
        assert records["sc-a"].per_objective_weighted_regret[1].weighted_regret == 1.25

    def test_comparator_includes_dominated_strategy(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        records = _regret_by_strategy(assessment)
        # sc-b is dominated by sc-a but still participates in every
        # same-seed comparator: its obj-2 regrets (1.0, 0.5, 0.0) come
        # from the all-strategy maxima (60, 55, 50), never a pairwise
        # comparison with sc-c alone.
        assert records["sc-b"].per_seed_total_weighted_regrets == (0.6, 0.3, 0.01)

    def test_weights_copied_exactly_no_normalization(self) -> None:
        assessment = _minimax(_policy_no_normalization(), _matrix_no_normalization())
        sc_a = _regret_by_strategy(assessment)["sc-a"]
        # Raw weights 2.0 and 0.5: the obj-4 weighted mean is exactly
        # 2.0 * 10 / 2 = 10.0 (a normalized 0.8 weight would give 4.0).
        assert sc_a.per_objective_weighted_regret[0].weighted_regret == 10.0
        assert sc_a.per_objective_weighted_regret[1].weighted_regret == 2.5
        assert sc_a.per_seed_total_weighted_regrets == (0.0, 25.0)

    def test_all_zero_weights_exact_zero(self) -> None:
        assessment = _minimax(_policy_zero_weight(), _matrix_zero_weight())
        records = _regret_by_strategy(assessment)
        for record in records.values():
            assert record.per_objective_weighted_regret == (
                ObjectiveRegretEvidence(objective_id="obj-4", weighted_regret=0.0),
            )
            assert record.per_seed_total_weighted_regrets == (0.0, 0.0, 0.0)
            assert record.median_total_weighted_regret == 0.0
            assert record.p95_total_weighted_regret == 0.0
            assert record.maximum_total_weighted_regret == 0.0

    def test_per_objective_evidence_exact_order(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        for record in assessment.strategy_regret_assessments:
            assert [item.objective_id for item in record.per_objective_weighted_regret] == [
                "obj-1",
                "obj-2",
            ]

    def test_aggregate_statistics_equal_primitives(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        sc_b = _regret_by_strategy(assessment)["sc-b"]
        expected = total_regret_statistics((0.6, 0.3, 0.01))
        assert sc_b.median_total_weighted_regret == expected.median_total_regret
        assert sc_b.p95_total_weighted_regret == expected.p95_total_regret
        assert sc_b.maximum_total_weighted_regret == expected.maximum_total_regret
        assert sc_b.maximum_total_weighted_regret == 0.6
        assert sc_b.median_total_weighted_regret == 0.3

    def test_every_strategy_gets_complete_assessment(self) -> None:
        policy = _policy(
            requirements=(("obj-1", 1.0),),
            weight_snapshots=(("obj-1", 1.0), ("obj-5", 0.25)),
        )
        assessment = _minimax(policy, _matrix_infeasible_dominator())
        records = _regret_by_strategy(assessment)
        assert set(records) == {"sc-a", "sc-c"}
        sc_c = records["sc-c"]
        assert [item.objective_id for item in sc_c.per_objective_weighted_regret] == [
            "obj-1",
            "obj-5",
        ]
        assert sc_c.per_seed_total_weighted_regrets == (0.02, 0.02, 0.02)


class TestMinimaxSelection:
    """Section C: exact minimax candidate, boundary, and tie semantics."""

    def test_unique_minimax_candidate(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        assert assessment.minimax_candidate_ids == ("sc-a",)
        assert assessment.minimax_evaluated is True
        assert assessment.best_maximum_total_weighted_regret == 0.0
        assert assessment.minimax_tie_strategy_ids == ("sc-a",)
        assert assessment.unique_minimax_strategy_id == "sc-a"

    def test_multiple_candidate_tie_no_unique_id(self) -> None:
        assessment = _minimax(_policy_boundary(), _matrix_boundary((0.10, 0.0), (0.06, 0.0)))
        assert assessment.minimax_candidate_ids == ("sc-a", "sc-b")
        assert assessment.minimax_evaluated is True
        assert assessment.best_maximum_total_weighted_regret == 0.06
        assert assessment.minimax_tie_strategy_ids == ("sc-a", "sc-b")
        assert assessment.unique_minimax_strategy_id is None

    def test_candidate_exactly_at_best_plus_tolerance_included(self) -> None:
        assessment = _minimax(_policy_boundary(), _matrix_boundary((0.11, 0.0), (0.06, 0.0)))
        assert assessment.best_maximum_total_weighted_regret == 0.06
        assert assessment.minimax_tie_strategy_ids == ("sc-a", "sc-b")
        assert assessment.unique_minimax_strategy_id is None

    def test_one_representable_step_above_boundary_excluded(self) -> None:
        above = math.nextafter(0.11, math.inf)
        assessment = _minimax(_policy_boundary(), _matrix_boundary((above, 0.0), (0.06, 0.0)))
        assert assessment.best_maximum_total_weighted_regret == 0.06
        assert assessment.minimax_tie_strategy_ids == ("sc-b",)
        assert assessment.unique_minimax_strategy_id == "sc-b"

    def test_singleton_feasible_candidate_unique_id(self) -> None:
        assessment = _minimax(_policy_global(threshold=0.8), _matrix_singleton_feasible())
        assert assessment.minimax_candidate_ids == ("sc-b",)
        assert assessment.minimax_evaluated is True
        assert assessment.minimax_tie_strategy_ids == ("sc-b",)
        assert assessment.unique_minimax_strategy_id == "sc-b"

    def test_one_non_dominated_among_several_feasible_unique_id(self) -> None:
        assessment = _minimax(_policy_3x2(), _matrix_3x2())
        assert assessment.minimax_candidate_ids == ("sc-a",)
        assert assessment.unique_minimax_strategy_id == "sc-a"

    def test_all_zero_weights_complete_candidate_tie(self) -> None:
        assessment = _minimax(_policy_zero_weight(), _matrix_zero_weight())
        assert assessment.minimax_evaluated is True
        assert assessment.best_maximum_total_weighted_regret == 0.0
        assert assessment.minimax_tie_strategy_ids == ("sc-a", "sc-b")
        assert assessment.unique_minimax_strategy_id is None

    def test_zero_feasible_not_evaluated(self) -> None:
        assessment = _minimax(_policy_global(threshold=1.0), _matrix_zero_feasible())
        assert assessment.minimax_candidate_ids == ()
        assert assessment.minimax_evaluated is False
        assert assessment.best_maximum_total_weighted_regret is None
        assert assessment.minimax_tie_strategy_ids == ()
        assert assessment.unique_minimax_strategy_id is None
        assert len(assessment.strategy_regret_assessments) == 2

    def test_insufficient_evidence_retains_candidates_and_regrets(self) -> None:
        assessment = _minimax(_policy(minimum_sample_count=5), _matrix_2x1())
        assert assessment.pareto_assessment.evidence_assessment.sufficient is False
        assert assessment.minimax_candidate_ids == ("sc-a",)
        assert assessment.minimax_evaluated is False
        assert assessment.best_maximum_total_weighted_regret is None
        assert assessment.minimax_tie_strategy_ids == ()
        assert assessment.unique_minimax_strategy_id is None
        assert len(assessment.strategy_regret_assessments) == 2
        assert _regret_by_strategy(assessment)["sc-b"].per_seed_total_weighted_regrets == (
            0.1,
            0.05,
            0.005,
        )

    def test_candidate_and_tie_ordering_authoritative(self) -> None:
        assessment = _minimax(_policy_boundary(), _matrix_boundary((0.10, 0.0), (0.06, 0.0)))
        assert assessment.minimax_candidate_ids == ("sc-a", "sc-b")
        assert assessment.minimax_tie_strategy_ids == ("sc-a", "sc-b")

    def test_repeated_calls_equal(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        first = _minimax(policy, matrix)
        second = _minimax(policy, matrix)
        assert first == second
        assert first.strategy_regret_assessments == second.strategy_regret_assessments


class TestMinimaxAdversarial:
    """Section D: adversarial rejection, overflow, and purity of the minimax builder."""

    def test_wrong_input_types_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=cast(Any, {}), outcome_matrix=matrix, paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=cast(Any, "policy"), outcome_matrix=matrix, paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=policy, outcome_matrix=cast(Any, []), paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=policy, outcome_matrix=cast(Any, 42), paired_comparisons=paired
            )

    def test_paired_comparisons_list_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=policy, outcome_matrix=matrix, paired_comparisons=cast(Any, list(paired))
            )

    def test_upstream_value_error_propagates(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_minimax_regret(
                policy=policy, outcome_matrix=matrix, paired_comparisons=paired[:-1]
            )

    def test_upstream_overflow_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)

        def exploding_validate(payload: object, **kwargs: object) -> object:
            raise OverflowError("numeric representability overflow")

        monkeypatch.setattr(ObjectivePairedComparison, "model_validate", exploding_validate)
        with pytest.raises(OverflowError):
            build_campaign_minimax_regret(
                policy=policy, outcome_matrix=matrix, paired_comparisons=paired
            )

    def test_wrong_strategy_count_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(strategy_assessments=assessment.strategy_assessments[:-1])
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_wrong_strategy_order_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        swapped = (assessment.strategy_assessments[1], assessment.strategy_assessments[0])
        bad = assessment._replace(
            strategy_assessments=swapped + assessment.strategy_assessments[2:]
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_wrong_strategy_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        first = assessment.strategy_assessments[0]._replace(strategy_candidate_id="sc-x")
        bad = assessment._replace(
            strategy_assessments=(first,) + assessment.strategy_assessments[1:]
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_wrong_strategy_position_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        first = assessment.strategy_assessments[0]._replace(strategy_position=1)
        bad = assessment._replace(
            strategy_assessments=(first,) + assessment.strategy_assessments[1:]
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_wrong_evidence_sample_count_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        evidence = assessment.evidence_assessment._replace(recorded_sample_count=2)
        bad = assessment._replace(evidence_assessment=evidence)
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_unknown_candidate_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-x",))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_duplicate_candidate_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-a", "sc-a"))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_reordered_candidate_ids_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-b", "sc-a"))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_infeasible_candidate_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-a", "sc-c"))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_dominated_candidate_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-a", "sc-b"))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_inconsistent_outcome_snapshot_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad_matrix = _construct_matrix_with_bad_outcome(matrix, 1, normalization_scale=999.0)
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, bad_matrix, paired, assessment)

    def test_observed_seed_length_mismatch_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad_matrix = _construct_matrix_with_bad_outcome(matrix, 1, ordered_observed_values=(1.0,))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, bad_matrix, paired, assessment)

    def test_wrong_policy_weight_value_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        wrong_policy = _policy(weight_snapshots=(("obj-1", 2.0),))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, wrong_policy, matrix, paired, assessment)

    def test_wrong_policy_weight_ids_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        wrong_policy = _policy(weight_snapshots=(("obj-x", 1.0),))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, wrong_policy, matrix, paired, assessment)

    def test_wrong_policy_weight_order_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        wrong_policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", 0.4), ("obj-2", 0.4)),
                weight_snapshots=(("obj-2", 0.5), ("obj-1", 1.0)),
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, wrong_policy, matrix, paired, assessment)

    def test_same_seed_regret_overflow_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        def exploding(*args: object, **kwargs: object) -> object:
            raise OverflowError("same-seed regret overflow")

        monkeypatch.setattr(selection_module, "same_seed_regret", exploding)
        with pytest.raises(OverflowError):
            _minimax(_policy(), _matrix_2x1())

    def test_weighting_overflow_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        def exploding(*args: object, **kwargs: object) -> object:
            raise OverflowError("weighted mean regret overflow")

        monkeypatch.setattr(selection_module, "objective_weighted_mean_regret", exploding)
        with pytest.raises(OverflowError):
            _minimax(_policy(), _matrix_2x1())

    def test_total_regret_vector_overflow_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        def exploding(*args: object, **kwargs: object) -> object:
            raise OverflowError("total regret vector overflow")

        monkeypatch.setattr(selection_module, "total_regret_vector", exploding)
        with pytest.raises(OverflowError):
            _minimax(_policy(), _matrix_2x1())

    def test_non_finite_best_plus_tolerance_overflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module
        from kalhas.application.campaign_decision_statistics import TotalRegretSummary

        policy = _policy(tolerance=1.7e308)
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        summary = TotalRegretSummary(
            sample_count=3,
            median_total_regret=0.0,
            p95_total_regret=0.0,
            maximum_total_regret=1.7e308,
        )

        def fake_statistics(total_regrets: object) -> object:
            return summary

        monkeypatch.setattr(selection_module, "total_regret_statistics", fake_statistics)
        with pytest.raises(OverflowError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, assessment)

    def test_generated_regret_evidence_rejection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        class _ExplodingEvidence:
            def __init__(self, **kwargs: object) -> None:
                raise ValueError("rejected")

        monkeypatch.setattr(selection_module, "ObjectiveRegretEvidence", _ExplodingEvidence)
        with pytest.raises(ValueError):
            _minimax(_policy(), _matrix_2x1())

    def test_late_failure_no_partial_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        policy = _policy_3x2()
        matrix = _matrix_3x2()
        state = {"count": 0}

        class _LateExplodingEvidence:
            def __init__(self, **kwargs: object) -> None:
                state["count"] += 1
                if state["count"] == 6:  # the final strategy x objective record
                    raise ValueError("late rejection")

        monkeypatch.setattr(selection_module, "ObjectiveRegretEvidence", _LateExplodingEvidence)
        with pytest.raises(ValueError):
            _minimax(policy, matrix)

    def test_pareto_builder_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import kalhas.application.campaign_decision_selection as selection_module

        calls: list[tuple[Any, Any, Any]] = []
        original = selection_module.build_campaign_pareto_dominance

        def counting(*, policy: Any, outcome_matrix: Any, paired_comparisons: Any) -> Any:
            calls.append((policy, outcome_matrix, paired_comparisons))
            return original(
                policy=policy,
                outcome_matrix=outcome_matrix,
                paired_comparisons=paired_comparisons,
            )

        monkeypatch.setattr(selection_module, "build_campaign_pareto_dominance", counting)
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        result = selection_module.build_campaign_minimax_regret(
            policy=policy, outcome_matrix=matrix, paired_comparisons=paired
        )
        assert len(calls) == 1
        assert calls[0] == (policy, matrix, paired)
        assert result.pareto_assessment is not None

    def test_all_inputs_unchanged_on_success_and_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        policy_before = policy.model_dump(mode="python")
        matrix_before = matrix.model_dump(mode="python")
        paired_before = [record.model_dump(mode="python") for record in paired]
        _minimax(policy, matrix, paired)
        assert policy.model_dump(mode="python") == policy_before
        assert matrix.model_dump(mode="python") == matrix_before
        assert [record.model_dump(mode="python") for record in paired] == paired_before

        wrong_policy = _policy(weight_snapshots=(("obj-1", 2.0),))
        wrong_policy_before = wrong_policy.model_dump(mode="python")
        assessment = _assessment(policy, matrix, paired)
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, wrong_policy, matrix, paired, assessment)
        assert wrong_policy.model_dump(mode="python") == wrong_policy_before
        assert policy.model_dump(mode="python") == policy_before
        assert matrix.model_dump(mode="python") == matrix_before
        assert [record.model_dump(mode="python") for record in paired] == paired_before


class TestParetoAggregateAlignment:
    """Section F: complete evidence/relation/candidate trust-boundary alignment.

    The accepted Pareto builder always returns internally consistent
    values; these tests prove the minimax layer rejects every
    monkeypatched assessment that is individually plausible but
    incomplete or relation-inconsistent - in particular an omitted
    legitimate candidate that could otherwise manufacture a false
    singleton unique minimax result.
    """

    def test_omitted_candidate_from_all_tied_assessment_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a", "sc-b")
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-a",))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_omitted_candidate_manufacturing_false_unique_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Genuine result: candidates ("sc-a", "sc-b") with maxima 0.10 and
        # 0.06 - both within tolerance, no unique id. Omitting sc-a would
        # otherwise manufacture the false singleton "sc-b".
        policy = _policy_boundary()
        matrix = _matrix_boundary((0.10, 0.0), (0.06, 0.0))
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        assert assessment.non_dominated_feasible_strategy_ids == ("sc-a", "sc-b")
        bad = assessment._replace(non_dominated_feasible_strategy_ids=("sc-b",))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_evidence_strategy_assessment_count_mismatch_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        evidence = assessment.evidence_assessment
        bad = assessment._replace(
            evidence_assessment=evidence._replace(
                strategy_assessments=evidence.strategy_assessments[:-1]
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_evidence_strategy_order_id_position_mismatch_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        evidence = assessment.evidence_assessment
        entries = evidence.strategy_assessments
        # reordered
        bad = assessment._replace(
            evidence_assessment=evidence._replace(
                strategy_assessments=(entries[1], entries[0]) + entries[2:]
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)
        # wrong strategy id
        first = entries[0]._replace(strategy_candidate_id="sc-x")
        bad = assessment._replace(
            evidence_assessment=evidence._replace(strategy_assessments=(first,) + entries[1:])
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)
        # wrong strategy position
        first = entries[0]._replace(strategy_position=1)
        bad = assessment._replace(
            evidence_assessment=evidence._replace(strategy_assessments=(first,) + entries[1:])
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_evidence_feasible_flag_mismatch_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        evidence = assessment.evidence_assessment
        entries = evidence.strategy_assessments
        # sc-c is infeasible in both layers; forge the evidence flag to True
        forged = entries[2]._replace(feasible=True)
        bad = assessment._replace(
            evidence_assessment=evidence._replace(strategy_assessments=entries[:2] + (forged,))
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_missing_dominance_relation_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        bad = assessment._replace(dominance_relations=assessment.dominance_relations[:-1])
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_reordered_dominance_relations_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        relations = assessment.dominance_relations
        bad = assessment._replace(dominance_relations=(relations[1], relations[0]))
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_wrong_relation_pair_identity_or_position_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        relations = assessment.dominance_relations
        # wrong pair positions on the first relation
        bad = assessment._replace(
            dominance_relations=(
                _mutated_relation(
                    relations[0],
                    first_strategy_position=1,
                    second_strategy_position=0,
                ),
                relations[1],
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)
        # wrong first identity on the first relation
        bad = assessment._replace(
            dominance_relations=(
                _mutated_relation(relations[0], first_strategy_candidate_id="sc-b"),
                relations[1],
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_dominated_by_missing_factual_dominator_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        # sc-c is factually dominated by sc-a and sc-b; omit sc-a
        sc_c = assessment.strategy_assessments[2]
        assert sc_c.dominated_by == ("sc-a", "sc-b")
        forged = sc_c._replace(dominated_by=("sc-b",))
        bad = assessment._replace(
            strategy_assessments=assessment.strategy_assessments[:2] + (forged,)
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_dominates_containing_unsupported_id_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        sc_a = assessment.strategy_assessments[0]
        assert sc_a.dominates == ("sc-b", "sc-c")
        forged = sc_a._replace(dominates=("sc-b", "sc-c", "sc-x"))
        bad = assessment._replace(
            strategy_assessments=(forged,) + assessment.strategy_assessments[1:]
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_forged_non_dominated_true_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        # sc-b is factually dominated by the feasible sc-a; forge its flag
        sc_b = assessment.strategy_assessments[1]
        assert sc_b.non_dominated_among_feasible is False
        forged = sc_b._replace(non_dominated_among_feasible=True)
        bad = assessment._replace(
            strategy_assessments=(
                assessment.strategy_assessments[0],
                forged,
                assessment.strategy_assessments[2],
            )
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_forged_non_dominated_false_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        sc_a = assessment.strategy_assessments[0]
        assert sc_a.non_dominated_among_feasible is True
        forged = sc_a._replace(non_dominated_among_feasible=False)
        bad = assessment._replace(
            strategy_assessments=(forged,) + assessment.strategy_assessments[1:]
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_mutually_consistent_forged_flags_and_candidates_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # sc-b's forged flag and the extended candidate tuple agree with
        # each other, but both disagree with the factual dominance
        # relations (the feasible sc-a factually dominates sc-b).
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        sc_b = assessment.strategy_assessments[1]
        forged = sc_b._replace(non_dominated_among_feasible=True)
        bad = assessment._replace(
            strategy_assessments=(
                assessment.strategy_assessments[0],
                forged,
                assessment.strategy_assessments[2],
            ),
            non_dominated_feasible_strategy_ids=("sc-a", "sc-b"),
        )
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, policy, matrix, paired, bad)

    def test_late_alignment_failure_no_partial_result_inputs_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        assessment = _assessment(policy, matrix, paired)
        # The weight-value mismatch is the final alignment check: every
        # evidence/relation/candidate check passes first, then the builder
        # fails with no partial result and no input mutated.
        wrong_policy = _policy(weight_snapshots=(("obj-1", 2.0),))
        policy_before = wrong_policy.model_dump(mode="python")
        matrix_before = matrix.model_dump(mode="python")
        paired_before = [record.model_dump(mode="python") for record in paired]
        assessment_before = tuple(assessment)
        with pytest.raises(ValueError):
            _minimax_with_pareto(monkeypatch, wrong_policy, matrix, paired, assessment)
        assert wrong_policy.model_dump(mode="python") == policy_before
        assert matrix.model_dump(mode="python") == matrix_before
        assert [record.model_dump(mode="python") for record in paired] == paired_before
        assert tuple(assessment) == assessment_before


class TestAdversarialRejection:
    """Section E: every invalid input shape raises and never returns partial output."""

    def test_wrong_policy_and_matrix_types(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=cast(Any, {}), outcome_matrix=matrix, paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=cast(Any, "policy"), outcome_matrix=matrix, paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=cast(Any, []), paired_comparisons=paired
            )
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=cast(Any, 42), paired_comparisons=paired
            )

    def test_paired_comparisons_list_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=cast(Any, list(paired))
            )

    def test_wrong_tuple_element_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=cast(Any, paired[:-1] + (42,)),
            )
        from kalhas.contracts.v1.campaign_decision import ObjectiveFeasibilityEvidence

        foreign = ObjectiveFeasibilityEvidence(
            objective_id="obj-1", threshold=0.4, observed_probability=0.5, passed=True
        )
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=cast(Any, paired[:-1] + (foreign,)),
            )

    def test_validator_bypassed_paired_record_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        bad = _mutated(paired[0], median_paired_delta=float("nan"))
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=paired[:1] + (bad,) + paired[1:],
            )

    def test_missing_record_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=paired[:-1]
            )

    def test_additional_record_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=paired + (paired[0],),
            )

    def test_duplicate_record_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=paired[:-1] + (paired[0],),
            )

    def test_reordered_records_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        reordered = [*paired]
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=tuple(reordered)
            )

    def test_wrong_sequence_position_rejected(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        bad = _mutated(paired[0], sequence_position=paired[0].sequence_position + 1)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=(bad,) + paired[1:],
            )

    def test_wrong_pair_position_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        record = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        bad = _mutated(record, first_strategy_position=2)
        replaced = tuple(bad if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_wrong_objective_position_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        record = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        bad = _mutated(record, objective_position=1)
        replaced = tuple(bad if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )
        out_of_range = _mutated(record, objective_position=2)
        replaced = tuple(out_of_range if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_wrong_strategy_identity_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        record = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        bad = _mutated(record, second_strategy_candidate_id="sc-c")
        replaced = tuple(bad if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_wrong_objective_identity_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        record = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        bad = _mutated(record, objective_id="obj-x")
        replaced = tuple(bad if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_wrong_metric_identity_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        record = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        bad = _mutated(record, metric_id="m-x")
        replaced = tuple(bad if other == record else other for other in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_wrong_tie_tolerance_rejected(self) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        # All-zero deltas keep the record internally consistent under any
        # tolerance, so the policy-tolerance mismatch is the only violation.
        bad = _mutated(paired[0], tie_tolerance=0.99)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=(bad,) + paired[1:],
            )

    def test_wrong_delta_count_rejected(self) -> None:
        policy = _policy_global_obj4()
        matrix = _matrix_all_tied()
        paired = _pairs(policy, matrix)
        record = paired[0]
        two_deltas = ObjectivePairedComparison.model_validate(
            {
                **record.model_dump(mode="python"),
                "ordered_paired_deltas": (0.0, 0.0),
                "win_count": 0,
                "tie_count": 2,
                "loss_count": 0,
                "win_rate": 0.0,
                "tie_rate": 1.0,
                "loss_rate": 0.0,
                "median_paired_delta": 0.0,
                "p05_paired_delta": 0.0,
                "p95_paired_delta": 0.0,
                "worst_paired_delta": 0.0,
                "best_paired_delta": 0.0,
            }
        )
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=(two_deltas,) + paired[1:],
            )

    def test_missing_reverse_record_rejected(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        paired = _pairs(policy, matrix)
        forward = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (0, 1)
            and record.objective_position == 0
        )
        without_reverse = tuple(
            record
            for record in paired
            if not (
                record.first_strategy_position == 1
                and record.second_strategy_position == 0
                and record.objective_position == 0
            )
        )
        assert len(without_reverse) == len(paired) - 1
        assert forward in without_reverse
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=without_reverse
            )

    @pytest.mark.parametrize(
        "mutator",
        [
            pytest.param(
                lambda record: _mutated(record, ordered_paired_deltas=(0.5, -0.5, 1.4)),
                id="delta-negation",
            ),
            pytest.param(
                lambda record: _mutated(record, win_count=record.loss_count),
                id="count-mirror",
            ),
            pytest.param(
                lambda record: _mutated(record, median_paired_delta=0.25),
                id="median-mirror",
            ),
            pytest.param(
                lambda record: _mutated(record, p05_paired_delta=-0.3),
                id="p05-mirror",
            ),
            pytest.param(
                lambda record: _mutated(record, p95_paired_delta=1.3),
                id="p95-mirror",
            ),
            pytest.param(
                lambda record: _mutated(record, worst_paired_delta=1.4),
                id="worst-mirror",
            ),
            pytest.param(
                lambda record: _mutated(record, best_paired_delta=-0.3),
                id="best-mirror",
            ),
        ],
    )
    def test_every_reverse_mirror_mismatch_rejected(self, mutator: Any) -> None:
        policy = _policy_global_obj5()
        matrix = _matrix_crossing()
        paired = _pairs(policy, matrix)
        reverse = next(
            record
            for record in paired
            if (record.first_strategy_position, record.second_strategy_position) == (1, 0)
        )
        bad = mutator(reverse)
        replaced = tuple(bad if record is reverse else record for record in paired)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=replaced
            )

    def test_late_malformed_final_record_no_partial_output(self) -> None:
        policy = _policy_global()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        bad = _mutated(paired[-1], median_paired_delta=float("nan"))
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=paired[:-1] + (bad,),
            )

    def test_inputs_unchanged_on_failure(self) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)
        policy_before = policy.model_dump(mode="python")
        matrix_before = matrix.model_dump(mode="python")
        paired_before = [record.model_dump(mode="python") for record in paired]
        bad = _mutated(paired[0], tie_tolerance=0.99)
        with pytest.raises(ValueError):
            build_campaign_pareto_dominance(
                policy=policy,
                outcome_matrix=matrix,
                paired_comparisons=(bad,) + paired[1:],
            )
        assert policy.model_dump(mode="python") == policy_before
        assert matrix.model_dump(mode="python") == matrix_before
        assert [record.model_dump(mode="python") for record in paired] == paired_before

    def test_overflow_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy = _policy()
        matrix = _matrix_2x1()
        paired = _pairs(policy, matrix)

        def exploding_validate(payload: object, **kwargs: object) -> object:
            raise OverflowError("numeric representability overflow")

        monkeypatch.setattr(ObjectivePairedComparison, "model_validate", exploding_validate)
        with pytest.raises(OverflowError):
            build_campaign_pareto_dominance(
                policy=policy, outcome_matrix=matrix, paired_comparisons=paired
            )


def _module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
