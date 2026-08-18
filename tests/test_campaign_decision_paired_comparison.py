"""Tests for the pure ordered objective-paired comparison builder.

Tests for ``kalhas/application/campaign_decision_paired_comparison.py``:
the single public builder that transforms one verified
``CampaignOutcomeDistributionMatrix`` and one matching
``CampaignDecisionPolicy`` into the complete immutable tuple of
``ObjectivePairedComparison`` records - exact cardinality and ordering,
canonical reverse-pair construction with exact mirror invariants,
direction semantics, strict detached revalidation of both sources,
cross-source agreement, and the purity/boundary guarantees.

Golden expectations mirror the implementation's accepted expressions:
expected deltas come from the accepted ``paired_delta_vector``
primitive and expected statistics from the accepted
``paired_delta_statistics`` primitive (never re-derived in the test),
while counts, rates, mirror rules, and hand-computable exact cases are
asserted independently. The ``ObjectivePairedComparison`` records are
built through the real contracts, so a rejection of any generated
record would surface as a test failure here.
"""

from __future__ import annotations

import ast
import inspect
import math
import re
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_decision_paired_comparison import (
    build_ordered_objective_paired_comparisons,
)
from kalhas.application.campaign_decision_statistics import (
    Direction,
    PairedDeltaSummary,
    paired_delta_statistics,
    paired_delta_vector,
)
from kalhas.application.campaign_metric_statistics_runtime import statistics_median
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.campaign_outcome_statistics import empirical_type7_quantile
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    ObjectivePairedComparison,
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
    / "campaign_decision_paired_comparison.py"
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
_DERIVED_AT = "2026-08-16T12:00:00Z"


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
OBJ3_BINDING = _binding(
    objective_id="obj-3",
    metric_id="m-3",
    direction="reach",
    target=100.0,
    weight=2.0,
    normalization_scale=20.0,
    reach_tolerance=5.0,
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
    """Two strategies x one minimize objective x three seeds.

    sc-a (90, 95, 99.5) vs sc-b (100, 100, 100) on obj-1 (minimize,
    scale 100): deltas (-0.1, -0.05, -0.005).
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
    """Three strategies x two objectives x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99), sc-b (100, 100, 100),
    sc-c (150, 160, 170); obj-2 maximize (scale 10): sc-a (60, 55, 50),
    sc-b (50, 50, 50), sc-c (40, 45, 30).
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
                ("sc-c", "obj-2"): (40, 45, 30),
            },
            **overrides,
        )
    )


def _matrix_reach(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one reach objective x three seeds.

    obj-3 reach (target 100, tolerance 5, scale 20): sc-a (100, 96, 108),
    sc-b (96, 100, 104): deltas (-0.2, 0.2, 0.2) - a crossing vector.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-3": OBJ3_BINDING},
            values={
                ("sc-a", "obj-3"): (100, 96, 108),
                ("sc-b", "obj-3"): (96, 100, 104),
            },
            **overrides,
        )
    )


def _matrix_oneseed(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x one seed."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0",),
            bindings={"obj-1": OBJ1_BINDING},
            values={("sc-a", "obj-1"): (5,), ("sc-b", "obj-1"): (10,)},
            **overrides,
        )
    )


def _matrix_even(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x two seeds."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1"),
            bindings={"obj-1": OBJ1_BINDING},
            values={("sc-a", "obj-1"): (90, 95), ("sc-b", "obj-1"): (100, 100)},
            **overrides,
        )
    )


def _matrix_repeated(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three identical seeds."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (100, 100, 100),
                ("sc-b", "obj-1"): (100, 100, 100),
            },
            **overrides,
        )
    )


def _matrix_signed_zero(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three signed-zero seeds."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (-0.0, -0.0, -0.0),
                ("sc-b", "obj-1"): (0.0, 0.0, 0.0),
            },
            **overrides,
        )
    )


def _matrix_type7(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three seeds with the
    documented Type-7 interpolation case ``(99, 25, 99)``.

    Scale 1.0 and values sc-a (100, 50, 100) / sc-b (1, 25, 1) produce
    exactly the deltas ``(99, 25, 99)`` whose Type-7 p95 is
    ``99.00000000000001``, one ULP above the observed maximum - the
    case known to expose rounding asymmetry when both directions are
    independently recomputed.
    """
    binding = _binding(
        objective_id="obj-1",
        metric_id="m-1",
        direction="minimize",
        target=100.0,
        weight=1.0,
        normalization_scale=1.0,
    )
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": binding},
            values={
                ("sc-a", "obj-1"): (100, 50, 100),
                ("sc-b", "obj-1"): (1, 25, 1),
            },
            **overrides,
        )
    )


def _matrix_ulp_boundary(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three seeds at the
    exact one-ULP tolerance boundary.

    Deltas ``(0.05, nextafter(0.05, inf), -0.05)``: the values exactly
    at ``+-tolerance`` are ties and the value one adjacent float step
    beyond ``+tolerance`` is a loss.
    """
    binding = _binding(
        objective_id="obj-1",
        metric_id="m-1",
        direction="minimize",
        target=100.0,
        weight=1.0,
        normalization_scale=1.0,
    )
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": binding},
            values={
                ("sc-a", "obj-1"): (0.05, math.nextafter(0.05, math.inf), 0.05),
                ("sc-b", "obj-1"): (0.0, 0.0, 0.1),
            },
            **overrides,
        )
    )


def _matrix_type7_ulp(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three seeds whose Type-7
    p05 lands exactly one adjacent float step toward zero from -3.5.

    Scale 1.0 and values sc-a (-3.86, -0.26, 1.0) / sc-b (0.0, 0.0, 0.0)
    produce the deltas (-3.86, -0.26, 1.0) with
    ``p05 == -3.4999999999999996`` - the documented ULP case the
    canonical reverse construction was verified against.
    """
    binding = _binding(
        objective_id="obj-1",
        metric_id="m-1",
        direction="minimize",
        target=100.0,
        weight=1.0,
        normalization_scale=1.0,
    )
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": binding},
            values={
                ("sc-a", "obj-1"): (-3.86, -0.26, 1.0),
                ("sc-b", "obj-1"): (0.0, 0.0, 0.0),
            },
            **overrides,
        )
    )


def _matrix_overflow(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x one seed whose paired
    delta overflows the finite float range (2**1023 - (-2**1023))."""
    binding = _binding(
        objective_id="obj-1",
        metric_id="m-1",
        direction="minimize",
        target=100.0,
        weight=1.0,
        normalization_scale=1.0,
    )
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0",),
            bindings={"obj-1": binding},
            values={("sc-a", "obj-1"): (2**1023,), ("sc-b", "obj-1"): (-(2**1023),)},
            **overrides,
        )
    )


def _matrix_ones_strategy(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """One structurally valid strategy x one objective x three seeds.

    The matrix contract permits a single strategy; the builder must
    reject it because paired comparison requires at least two.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a",),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={("sc-a", "obj-1"): (90, 95, 99)},
            **overrides,
        )
    )


def _policy_payload(
    *,
    objectives: tuple[str, ...] = ("obj-1",),
    weights: tuple[float, ...] = (1.0,),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
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
            {"objective_id": objective_id, "minimum_target_achievement_probability": 0.4}
            for objective_id in objectives
        ],
        "objective_weight_snapshots": [
            {"objective_id": objective_id, "weight": weight}
            for objective_id, weight in zip(objectives, weights, strict=True)
        ],
        "minimum_sample_count": minimum_sample_count,
        "tie_tolerance": tolerance,
        "all_targeted_objectives_are_hard_gates": True,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _policy(**overrides: object) -> CampaignDecisionPolicy:
    """One validated policy matching the standard 2x1 matrix by default."""
    return CampaignDecisionPolicy.model_validate(_policy_payload(**cast(Any, overrides)))


def _policy_3x2() -> CampaignDecisionPolicy:
    """One validated policy matching the 3x2 matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_payload(objectives=("obj-1", "obj-2"), weights=(1.0, 0.5))
    )


def _policy_reach() -> CampaignDecisionPolicy:
    """One validated policy matching the reach matrix."""
    return CampaignDecisionPolicy.model_validate(
        _policy_payload(objectives=("obj-3",), weights=(2.0,))
    )


def _tampered_policy(policy: CampaignDecisionPolicy, **updates: object) -> CampaignDecisionPolicy:
    """A validator-bypassed policy assembled with ``model_construct``."""
    payload = policy.model_dump(mode="python")
    payload.update(updates)
    return CampaignDecisionPolicy.model_construct(**payload)


def _tampered_matrix(
    matrix: CampaignOutcomeDistributionMatrix, **updates: object
) -> CampaignOutcomeDistributionMatrix:
    """A validator-bypassed matrix assembled with ``model_construct``."""
    payload = matrix.model_dump(mode="python")
    payload.update(updates)
    return CampaignOutcomeDistributionMatrix.model_construct(**payload)


def _tampered_outcome_matrix(
    matrix: CampaignOutcomeDistributionMatrix,
    position: int,
    **outcome_updates: object,
) -> CampaignOutcomeDistributionMatrix:
    """A validator-bypassed matrix with one tampered outcome dict."""
    payload = matrix.model_dump(mode="python")
    outcomes = list(cast(list[dict[str, Any]], payload["outcomes"]))
    tampered = dict(outcomes[position])
    tampered.update(outcome_updates)
    outcomes[position] = tampered
    payload["outcomes"] = tuple(outcomes)
    return CampaignOutcomeDistributionMatrix.model_construct(**payload)


def _record_for(
    records: tuple[ObjectivePairedComparison, ...],
    first: int,
    second: int,
    objective: int,
) -> ObjectivePairedComparison:
    """The single stored record of one ordered pair and objective."""
    matches = [
        record
        for record in records
        if record.first_strategy_position == first
        and record.second_strategy_position == second
        and record.objective_position == objective
    ]
    assert len(matches) == 1
    return matches[0]


def _expected_evidence(
    values_a: tuple[int | float, ...],
    values_b: tuple[int | float, ...],
    *,
    direction: Direction,
    scale: float,
    target: float | None,
    tolerance: float,
) -> tuple[tuple[float, ...], PairedDeltaSummary]:
    """The exact expected delta vector and summary from the accepted primitives."""
    deltas = paired_delta_vector(
        values_a,
        values_b,
        direction=direction,
        normalization_scale=scale,
        target=target,
    )
    return deltas, paired_delta_statistics(deltas, tie_tolerance=tolerance)


def _assert_mirror_invariants(
    forward: ObjectivePairedComparison, reverse: ObjectivePairedComparison
) -> None:
    """Assert every exact reverse-pair invariant of the stored records."""
    assert reverse.ordered_paired_deltas == tuple(-delta for delta in forward.ordered_paired_deltas)
    assert reverse.win_count == forward.loss_count
    assert reverse.loss_count == forward.win_count
    assert reverse.tie_count == forward.tie_count
    assert reverse.win_rate == forward.loss_rate
    assert reverse.tie_rate == forward.tie_rate
    assert reverse.loss_rate == forward.win_rate
    assert reverse.median_paired_delta == -forward.median_paired_delta
    assert reverse.p05_paired_delta == -forward.p95_paired_delta
    assert reverse.p95_paired_delta == -forward.p05_paired_delta
    assert reverse.worst_paired_delta == -forward.best_paired_delta
    assert reverse.best_paired_delta == -forward.worst_paired_delta
    sample_count = len(reverse.ordered_paired_deltas)
    assert reverse.win_rate == reverse.win_count / sample_count
    assert reverse.tie_rate == reverse.tie_count / sample_count
    assert reverse.loss_rate == reverse.loss_count / sample_count


class TestOrderedPairGeneration:
    def test_two_strategies_one_objective(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_2x1()
        )
        assert len(records) == 2
        assert [record.sequence_position for record in records] == [0, 1]
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.sequence_position == 0
        assert reverse.sequence_position == 1
        assert forward.ordered_paired_deltas == (-0.1, -0.05, -0.005)
        assert forward.win_count == 1
        assert forward.tie_count == 2
        assert forward.loss_count == 0
        assert forward.win_rate == 1 / 3
        assert forward.tie_rate == 2 / 3
        assert forward.loss_rate == 0.0
        assert forward.worst_paired_delta == -0.005
        assert forward.best_paired_delta == -0.1

    def test_three_strategies_two_objectives_cardinality_and_order(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        assert len(records) == 3 * 2 * 2
        expected_positions: list[int] = []
        for first in range(3):
            for second in range(3):
                if first == second:
                    continue
                pair_index = first * 2 + (second if second < first else second - 1)
                for objective_position in range(2):
                    expected_positions.append(pair_index * 2 + objective_position)
        assert [record.sequence_position for record in records] == expected_positions
        assert [record.sequence_position for record in records] == list(range(12))
        traversal = [
            (
                record.first_strategy_position,
                record.second_strategy_position,
                record.objective_position,
            )
            for record in records
        ]
        expected_traversal = [
            (first, second, objective_position)
            for first in range(3)
            for second in range(3)
            if first != second
            for objective_position in range(2)
        ]
        assert traversal == expected_traversal

    def test_no_self_pairs_and_both_directions_every_objective(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        assert all(
            record.first_strategy_position != record.second_strategy_position for record in records
        )
        keys = {
            (
                record.first_strategy_position,
                record.second_strategy_position,
                record.objective_position,
            )
            for record in records
        }
        expected_keys = {
            (first, second, objective_position)
            for first in range(3)
            for second in range(3)
            if first != second
            for objective_position in range(2)
        }
        assert keys == expected_keys

    def test_identity_position_and_metric_agreement(self) -> None:
        matrix = _matrix_3x2()
        policy = _policy_3x2()
        records = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        strategy_ids = matrix.ordered_strategy_candidate_ids
        objective_ids = matrix.ordered_objective_ids
        for record in records:
            assert (
                record.first_strategy_candidate_id == strategy_ids[record.first_strategy_position]
            )
            assert (
                record.second_strategy_candidate_id == strategy_ids[record.second_strategy_position]
            )
            assert record.objective_id == objective_ids[record.objective_position]
            assert record.metric_id == ("m-1" if record.objective_position == 0 else "m-2")

    def test_shared_seed_order_and_tie_tolerance_snapshot(self) -> None:
        matrix = _matrix_3x2()
        policy = _policy_3x2()
        records = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        values = {
            ("sc-a", 0): (90, 95, 99),
            ("sc-b", 0): (100, 100, 100),
            ("sc-c", 0): (150, 160, 170),
            ("sc-a", 1): (60, 55, 50),
            ("sc-b", 1): (50, 50, 50),
            ("sc-c", 1): (40, 45, 30),
        }
        for record in records:
            assert record.tie_tolerance == policy.tie_tolerance
            first_values = values[(record.first_strategy_candidate_id, record.objective_position)]
            second_values = values[(record.second_strategy_candidate_id, record.objective_position)]
            expected_deltas, _ = _expected_evidence(
                first_values,
                second_values,
                direction="minimize" if record.objective_position == 0 else "maximize",
                scale=100.0 if record.objective_position == 0 else 10.0,
                target=100.0 if record.objective_position == 0 else 50.0,
                tolerance=policy.tie_tolerance,
            )
            assert record.ordered_paired_deltas == expected_deltas

    def test_record_values_match_accepted_primitives(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        records = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        deltas, summary = _expected_evidence(
            (90, 95, 99.5),
            (100, 100, 100),
            direction="minimize",
            scale=100.0,
            target=100.0,
            tolerance=policy.tie_tolerance,
        )
        record = records[0]
        assert record.ordered_paired_deltas == deltas
        assert record.win_count == summary.win_count
        assert record.tie_count == summary.tie_count
        assert record.loss_count == summary.loss_count
        assert record.win_rate == summary.win_rate
        assert record.tie_rate == summary.tie_rate
        assert record.loss_rate == summary.loss_rate
        assert record.median_paired_delta == summary.median_paired_delta
        assert record.p05_paired_delta == summary.p05_paired_delta
        assert record.p95_paired_delta == summary.p95_paired_delta
        assert record.worst_paired_delta == summary.worst_paired_delta
        assert record.best_paired_delta == summary.best_paired_delta
        assert record.median_paired_delta == statistics_median((-0.1, -0.05, -0.005))
        assert record.p05_paired_delta == empirical_type7_quantile((-0.1, -0.05, -0.005), 5)
        assert record.p95_paired_delta == empirical_type7_quantile((-0.1, -0.05, -0.005), 95)


class TestDirectionSemantics:
    def test_minimize_delta_formula(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_2x1()
        )
        forward = _record_for(records, 0, 1, 0)
        assert forward.ordered_paired_deltas == tuple(
            (a - b) / 100.0 for a, b in zip((90, 95, 99.5), (100, 100, 100), strict=True)
        )

    def test_maximize_delta_formula(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        forward = _record_for(records, 0, 1, 1)
        assert forward.ordered_paired_deltas == tuple(
            (b - a) / 10.0 for a, b in zip((60, 55, 50), (50, 50, 50), strict=True)
        )

    def test_reach_delta_formula(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_reach(), outcome_matrix=_matrix_reach()
        )
        forward = _record_for(records, 0, 1, 0)
        assert forward.ordered_paired_deltas == tuple(
            (abs(a - 100.0) - abs(b - 100.0)) / 20.0
            for a, b in zip((100, 96, 108), (96, 100, 104), strict=True)
        )

    def test_positive_means_first_strategy_worse(self) -> None:
        records_3x2 = build_ordered_objective_paired_comparisons(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        worse_minimize = _record_for(records_3x2, 2, 0, 0)
        assert worse_minimize.ordered_paired_deltas == (0.6, 0.65, 0.71)
        assert worse_minimize.loss_count == 3
        assert worse_minimize.win_count == 0
        better_minimize = _record_for(records_3x2, 0, 2, 0)
        assert better_minimize.win_count == 3
        assert better_minimize.loss_count == 0
        worse_maximize = _record_for(records_3x2, 2, 0, 1)
        assert worse_maximize.ordered_paired_deltas == (2.0, 1.0, 2.0)
        assert worse_maximize.loss_count == 3
        records_reach = build_ordered_objective_paired_comparisons(
            policy=_policy_reach(), outcome_matrix=_matrix_reach()
        )
        worse_reach = _record_for(records_reach, 1, 0, 0)
        assert worse_reach.ordered_paired_deltas == (0.2, -0.2, -0.2)
        assert worse_reach.loss_count == 1
        assert worse_reach.win_count == 2

    def test_exact_ties_and_one_ulp_tolerance_boundary(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_ulp_boundary()
        )
        forward = _record_for(records, 0, 1, 0)
        assert forward.ordered_paired_deltas == (
            0.05,
            math.nextafter(0.05, math.inf),
            -0.05,
        )
        assert forward.win_count == 0
        assert forward.tie_count == 2
        assert forward.loss_count == 1
        assert forward.win_rate == 0.0
        assert forward.tie_rate == 2 / 3
        assert forward.loss_rate == 1 / 3

    def test_deltas_exactly_at_tolerance_are_ties(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_2x1()
        )
        forward = _record_for(records, 0, 1, 0)
        assert forward.ordered_paired_deltas == (-0.1, -0.05, -0.005)
        assert forward.tie_count == 2  # -0.05 and -0.005 are both ties


class TestReverseInvariants:
    def test_seedwise_exact_negation_and_count_mirrors(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        for first in range(3):
            for second in range(3):
                if first == second:
                    continue
                for objective_position in range(2):
                    forward = _record_for(records, first, second, objective_position)
                    reverse = _record_for(records, second, first, objective_position)
                    _assert_mirror_invariants(forward, reverse)

    def test_asymmetric_vector_worst_is_not_negated_forward_worst(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_reach(), outcome_matrix=_matrix_reach()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.ordered_paired_deltas == (-0.2, 0.2, 0.2)
        assert forward.worst_paired_delta == 0.2
        assert forward.best_paired_delta == -0.2
        assert reverse.worst_paired_delta == -forward.best_paired_delta
        assert reverse.best_paired_delta == -forward.worst_paired_delta
        assert reverse.worst_paired_delta != -forward.worst_paired_delta
        assert reverse.best_paired_delta != -forward.best_paired_delta

    def test_odd_and_even_seed_counts(self) -> None:
        odd = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_2x1()
        )
        even = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_even()
        )
        _assert_mirror_invariants(_record_for(odd, 0, 1, 0), _record_for(odd, 1, 0, 0))
        _assert_mirror_invariants(_record_for(even, 0, 1, 0), _record_for(even, 1, 0, 0))
        even_forward = _record_for(even, 0, 1, 0)
        assert even_forward.ordered_paired_deltas == (-0.1, -0.05)
        assert even_forward.median_paired_delta == statistics_median((-0.1, -0.05))
        assert even_forward.p05_paired_delta == empirical_type7_quantile((-0.1, -0.05), 5)
        assert even_forward.p95_paired_delta == empirical_type7_quantile((-0.1, -0.05), 95)

    def test_one_sample_outcome(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_oneseed()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.ordered_paired_deltas == (-0.05,)
        assert forward.win_count == 0
        assert forward.tie_count == 1
        assert forward.loss_count == 0
        assert forward.median_paired_delta == -0.05
        assert forward.p05_paired_delta == -0.05
        assert forward.p95_paired_delta == -0.05
        assert forward.worst_paired_delta == -0.05
        assert forward.best_paired_delta == -0.05
        _assert_mirror_invariants(forward, reverse)

    def test_repeated_values(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_repeated()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.ordered_paired_deltas == (0.0, 0.0, 0.0)
        assert forward.win_count == 0
        assert forward.tie_count == 3
        assert forward.loss_count == 0
        assert forward.win_rate == 0.0
        assert forward.tie_rate == 1.0
        assert forward.loss_rate == 0.0
        assert forward.median_paired_delta == 0.0
        assert forward.p05_paired_delta == 0.0
        assert forward.p95_paired_delta == 0.0
        assert forward.worst_paired_delta == 0.0
        assert forward.best_paired_delta == 0.0
        _assert_mirror_invariants(forward, reverse)

    def test_signed_zero_case(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_signed_zero()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert all(math.copysign(1.0, delta) == -1.0 for delta in forward.ordered_paired_deltas)
        assert all(math.copysign(1.0, delta) == 1.0 for delta in reverse.ordered_paired_deltas)
        assert reverse.ordered_paired_deltas == tuple(
            -delta for delta in forward.ordered_paired_deltas
        )
        _assert_mirror_invariants(forward, reverse)
        # The canonical construction is deterministic: a second call
        # reproduces the exact signed-zero representations.
        again = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_signed_zero()
        )
        assert [record.model_dump(mode="json") for record in again] == [
            record.model_dump(mode="json") for record in records
        ]

    def test_type7_interpolation_case_never_independently_recomputed(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_type7()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.ordered_paired_deltas == (99.0, 25.0, 99.0)
        assert forward.median_paired_delta == 99.0
        assert forward.p05_paired_delta == 32.4
        assert forward.p95_paired_delta == 99.00000000000001
        assert forward.worst_paired_delta == 99.0
        assert forward.best_paired_delta == 25.0
        # The Type-7 interpolation of (99, 25, 99) lands exactly one
        # adjacent float step ABOVE the observed maximum - the
        # documented ULP-drift case. The reverse record must carry the
        # exact negated value, one step BELOW the reverse minimum; the
        # contract's deterministic one-adjacent-float-step structural
        # relation accepts exactly that.
        assert forward.p95_paired_delta == math.nextafter(99.0, math.inf)
        assert reverse.p05_paired_delta == -forward.p95_paired_delta
        assert reverse.p05_paired_delta == math.nextafter(-99.0, -math.inf)
        assert reverse.p95_paired_delta == -forward.p05_paired_delta
        assert reverse.median_paired_delta == -forward.median_paired_delta
        # The accepted integer-index Type-7 primitive is exactly
        # sign-equivariant (integer numerator/remainder plus
        # ``math.fsum``, which sign-commutes), so an independent
        # recomputation over the negated deltas agrees with the mirror.
        # The canonical rule nevertheless guarantees the mirror holds
        # by construction for every valid input instead of relying on
        # that algebraic property of one primitive.
        assert (
            empirical_type7_quantile(reverse.ordered_paired_deltas, 5) == reverse.p05_paired_delta
        )
        assert (
            empirical_type7_quantile(reverse.ordered_paired_deltas, 95) == reverse.p95_paired_delta
        )

    def test_type7_ulp_case_documented_negative_p05(self) -> None:
        # Observed values sc-a (-3.86, -0.26, 1.0) vs sc-b (0.0, 0.0, 0.0)
        # at scale 1 produce the deltas (-3.86, -0.26, 1.0) whose Type-7
        # p05 is exactly -3.4999999999999996 - one adjacent float step
        # toward zero from -3.5 - the case the canonical reverse rule
        # was verified against.
        records = build_ordered_objective_paired_comparisons(
            policy=_policy(), outcome_matrix=_matrix_type7_ulp()
        )
        forward = _record_for(records, 0, 1, 0)
        reverse = _record_for(records, 1, 0, 0)
        assert forward.ordered_paired_deltas == (-3.86, -0.26, 1.0)
        assert forward.p05_paired_delta == -3.4999999999999996
        assert forward.p05_paired_delta == math.nextafter(-3.5, math.inf)
        assert reverse.p95_paired_delta == -forward.p05_paired_delta
        assert reverse.p95_paired_delta == 3.4999999999999996
        assert reverse.p95_paired_delta == math.nextafter(3.5, -math.inf)
        _assert_mirror_invariants(forward, reverse)


class TestSourceValidation:
    def test_wrong_source_types(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=cast(Any, matrix), outcome_matrix=matrix
            )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=cast(Any, "x"))
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=cast(Any, None), outcome_matrix=matrix
            )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=cast(Any, policy)
            )

    def test_validator_bypassed_policy(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_policy(policy, tie_tolerance=-1.0),
            _tampered_policy(policy, tail_alpha=0.9),
            _tampered_policy(policy, minimum_sample_count="x"),
            _tampered_policy(policy, objective_weight_snapshots=()),
        ):
            with pytest.raises(ValueError):
                build_ordered_objective_paired_comparisons(policy=tampered, outcome_matrix=matrix)

    def test_validator_bypassed_outcome_matrix(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_matrix(matrix, runtime_version="9.9.9"),
            _tampered_matrix(matrix, comparison_mode="other"),
            _tampered_matrix(matrix, ordered_scenario_seed_ids=("seed-0",)),
            _tampered_matrix(matrix, ordered_objective_ids=()),
            _tampered_matrix(matrix, ordered_strategy_candidate_ids=("sc-a", "sc-a")),
            _tampered_matrix(matrix, outcomes=()),
            _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(float("nan"),)),
        ):
            with pytest.raises(ValueError):
                build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_identity_mismatches(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        mismatches: tuple[tuple[str, object], ...] = (
            ("tenant_id", "tenant-2"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "0" * 64),
            ("world_version_id", "world-2"),
            ("world_content_hash", "1" * 64),
            ("evaluation_profile_id", "profile-2"),
            ("evaluation_profile_content_hash", "2" * 64),
        )
        for field, value in mismatches:
            tampered = policy.model_copy(update={field: value})
            with pytest.raises(ValueError):
                build_ordered_objective_paired_comparisons(policy=tampered, outcome_matrix=matrix)

    def test_algorithm_runtime_and_mode_literals(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy.model_copy(update={"algorithm_identifier": "other"}),
                outcome_matrix=matrix,
            )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=_tampered_matrix(matrix, runtime_version="2.0.0")
            )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy,
                outcome_matrix=_tampered_matrix(matrix, comparison_mode="per_seed"),
            )

    def test_tail_alpha_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy.model_copy(update={"tail_alpha": 0.9}), outcome_matrix=matrix
            )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=_tampered_outcome_matrix(matrix, 0, tail_alpha=0.9)
            )

    def test_weight_snapshot_value_id_and_order_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        snapshot = policy.objective_weight_snapshots[0]
        wrong_value = policy.model_copy(
            update={"objective_weight_snapshots": (snapshot.model_copy(update={"weight": 9.9}),)}
        )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=wrong_value, outcome_matrix=matrix)
        wrong_id = policy.model_copy(
            update={
                "objective_weight_snapshots": (
                    snapshot.model_copy(update={"objective_id": "obj-9"}),
                )
            }
        )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=wrong_id, outcome_matrix=matrix)
        policy_3x2 = _policy_3x2()
        swapped = policy_3x2.model_copy(
            update={
                "objective_weight_snapshots": tuple(reversed(policy_3x2.objective_weight_snapshots))
            }
        )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=swapped, outcome_matrix=_matrix_3x2())

    def test_one_strategy_only(self) -> None:
        with pytest.raises(ValueError, match="at least two strategies"):
            build_ordered_objective_paired_comparisons(
                policy=_policy(), outcome_matrix=_matrix_ones_strategy()
            )

    def test_duplicate_and_empty_strategy_seed_objective_evidence(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_matrix(matrix, ordered_strategy_candidate_ids=("sc-a", "sc-a")),
            _tampered_matrix(matrix, ordered_scenario_seed_ids=("seed-0", "seed-0", "seed-1")),
            _tampered_matrix(matrix, ordered_objective_ids=("obj-1", "obj-1")),
            _tampered_matrix(matrix, ordered_strategy_candidate_ids=()),
            _tampered_matrix(matrix, ordered_scenario_seed_ids=()),
            _tampered_matrix(matrix, ordered_objective_ids=()),
            _tampered_matrix(matrix, outcomes=()),
        ):
            with pytest.raises(ValueError):
                build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_missing_and_reordered_outcomes(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        missing = _tampered_matrix(matrix, outcomes=(matrix.outcomes[0],))
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=missing)
        reordered = _tampered_matrix(matrix, outcomes=tuple(reversed(matrix.outcomes)))
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=reordered)

    def test_wrong_positions_ids_and_metric_ids(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_outcome_matrix(matrix, 0, strategy_position=1),
            _tampered_outcome_matrix(matrix, 0, objective_position=1),
            _tampered_outcome_matrix(matrix, 0, strategy_candidate_id="sc-c"),
            _tampered_outcome_matrix(matrix, 0, objective_id="obj-9"),
            _tampered_outcome_matrix(matrix, 0, metric_id="m-9"),
            _tampered_outcome_matrix(matrix, 0, sequence_position=5),
        ):
            with pytest.raises(ValueError):
                build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_observed_length_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(90, 95))
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_empirical_samples_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(
            matrix,
            0,
            empirical_distribution={
                "ordered_samples": (1.0, 2.0, 3.0),
                "sample_count": 3,
                "minimum": 1.0,
                "maximum": 3.0,
                "arithmetic_mean": 2.0,
                "median": 2.0,
                "population_standard_deviation": 1.0,
                "quantile_algorithm": "hyndman-fan-type-7-v1",
                "p05": 1.0,
                "p25": 1.5,
                "p75": 2.5,
                "p95": 3.0,
            },
        )
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_inconsistent_objective_snapshots_across_strategies(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(matrix, 1, weight=5.0)
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)

    def test_huge_integer_rejected_at_the_boundary(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(10**400,))
        with pytest.raises(ValueError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=tampered)


class TestBehavior:
    def test_undersized_matrix_still_builds_evidence(self) -> None:
        policy = _policy(minimum_sample_count=100)
        records = build_ordered_objective_paired_comparisons(
            policy=policy, outcome_matrix=_matrix_2x1()
        )
        assert len(records) == 2

    def test_input_models_unchanged(self) -> None:
        matrix = _matrix_3x2()
        policy = _policy_3x2()
        matrix_before = matrix.model_dump(mode="python")
        policy_before = policy.model_dump(mode="python")
        build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        assert matrix.model_dump(mode="python") == matrix_before
        assert policy.model_dump(mode="python") == policy_before

    def test_repeated_calls_produce_value_identical_tuples(self) -> None:
        policy = _policy_3x2()
        matrix = _matrix_3x2()
        first = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        second = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        assert first == second
        assert [record.model_dump(mode="json") for record in first] == [
            record.model_dump(mode="json") for record in second
        ]

    def test_no_partial_result_on_late_failure(self) -> None:
        policy = _policy()
        matrix = _matrix_overflow()
        matrix_before = matrix.model_dump(mode="python")
        with pytest.raises(OverflowError):
            build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        assert matrix.model_dump(mode="python") == matrix_before

    def test_arithmetic_overflow_propagates_as_overflow_error(self) -> None:
        with pytest.raises(OverflowError):
            build_ordered_objective_paired_comparisons(
                policy=_policy(), outcome_matrix=_matrix_overflow()
            )

    def test_reach_evidence_builds_with_mixed_orientation(self) -> None:
        records = build_ordered_objective_paired_comparisons(
            policy=_policy_reach(), outcome_matrix=_matrix_reach()
        )
        assert len(records) == 2
        forward = _record_for(records, 0, 1, 0)
        assert forward.win_count == 1
        assert forward.tie_count == 0
        assert forward.loss_count == 2


class TestEmbeddability:
    def test_tuple_accepted_inside_structurally_valid_comparison(self) -> None:
        matrix = _matrix_3x2()
        policy = _policy_3x2()
        records = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        comparison = CampaignStrategyComparison.model_validate(
            _comparison_payload_from(records, policy, matrix)
        )
        assert comparison.paired_comparisons == records
        assert len(comparison.paired_comparisons) == 12
        assert len(comparison.dominance_relations) == 6
        assert len(comparison.robustness_profiles) == 3

    def test_two_strategy_tuple_also_embeddable(self) -> None:
        matrix = _matrix_reach()
        policy = _policy_reach()
        records = build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)
        comparison = CampaignStrategyComparison.model_validate(
            _comparison_payload_from(records, policy, matrix)
        )
        assert comparison.paired_comparisons == records


def _comparison_payload_from(
    records: tuple[ObjectivePairedComparison, ...],
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
) -> dict[str, Any]:
    """One structurally valid comparison payload embedding the records."""
    strategy_ids = list(matrix.ordered_strategy_candidate_ids)
    objective_ids = list(matrix.ordered_objective_ids)
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    seed_count = len(matrix.ordered_scenario_seed_ids)
    relations: list[dict[str, Any]] = []
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            statuses: list[dict[str, Any]] = []
            for objective_position in range(objective_count):
                record = _record_for(records, first, second, objective_position)
                if record.loss_count > 0:
                    status = "worse"
                elif record.win_count > 0:
                    status = "better"
                else:
                    status = "tied"
                statuses.append(
                    {
                        "objective_id": objective_ids[objective_position],
                        "status": status,
                        "win_count": record.win_count,
                        "tie_count": record.tie_count,
                        "loss_count": record.loss_count,
                        "median_paired_delta": record.median_paired_delta,
                    }
                )
            status_codes = [str(status["status"]) for status in statuses]
            relations.append(
                {
                    "first_strategy_position": first,
                    "second_strategy_position": second,
                    "first_strategy_candidate_id": strategy_ids[first],
                    "second_strategy_candidate_id": strategy_ids[second],
                    "dominates": "worse" not in status_codes and "better" in status_codes,
                    "per_objective_status": statuses,
                }
            )
    relations_by_key = {
        (
            int(relation["first_strategy_position"]),
            int(relation["second_strategy_position"]),
        ): relation
        for relation in relations
    }
    profiles: list[dict[str, Any]] = []
    for position in range(strategy_count):
        dominated_by = [
            strategy_ids[dominator]
            for dominator in range(strategy_count)
            if dominator != position and bool(relations_by_key[(dominator, position)]["dominates"])
        ]
        dominates = [
            strategy_ids[dominated]
            for dominated in range(strategy_count)
            if dominated != position and bool(relations_by_key[(position, dominated)]["dominates"])
        ]
        profiles.append(
            {
                "strategy_position": position,
                "strategy_candidate_id": strategy_ids[position],
                "feasible": True,
                "target_feasibility": [],
                "dominated_by": dominated_by,
                "dominates": dominates,
                "per_objective_weighted_regret": [
                    {"objective_id": objective_id, "weighted_regret": 0.0}
                    for objective_id in objective_ids
                ],
                "per_seed_total_weighted_regrets": [0.0] * seed_count,
                "median_total_weighted_regret": 0.0,
                "p95_total_weighted_regret": 0.0,
                "maximum_total_weighted_regret": 0.0,
                "target_achievement_probabilities": [],
                "downside_evidence": [
                    {
                        "objective_id": objective_id,
                        "worst_normalized_target_violation": None,
                        "target_violation_cvar": None,
                        "adverse_tail_statistic": 0.0,
                    }
                    for objective_id in objective_ids
                ],
            }
        )
    return {
        "identifier": "comparison-1",
        "tenant_id": matrix.tenant_id,
        "schema_version": "1.0.0",
        "campaign_id": matrix.campaign_id,
        "scenario_id": matrix.scenario_id,
        "scenario_content_hash": matrix.scenario_content_hash,
        "world_version_id": matrix.world_version_id,
        "world_content_hash": matrix.world_content_hash,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "algorithm_identifier": ALGORITHM,
        "policy_id": policy.identifier,
        "policy_content_hash": policy.content_hash,
        "tie_tolerance": policy.tie_tolerance,
        "minimum_sample_count": policy.minimum_sample_count,
        "source_outcome_matrix_id": matrix.identifier,
        "source_outcome_matrix_content_hash": matrix.content_hash,
        "ordered_strategy_candidate_ids": strategy_ids,
        "ordered_scenario_seed_ids": list(matrix.ordered_scenario_seed_ids),
        "ordered_objective_ids": objective_ids,
        "paired_comparisons": [record.model_dump(mode="python") for record in records],
        "dominance_relations": relations,
        "robustness_profiles": profiles,
        "content_hash": "0" * 64,
        "derived_at": _DERIVED_AT,
    }


class TestPurityAndBoundaries:
    def test_exact_all(self) -> None:
        from kalhas.application import campaign_decision_paired_comparison as module

        assert module.__all__ == ["build_ordered_objective_paired_comparisons"]
        assert module.build_ordered_objective_paired_comparisons.__module__ == (
            "kalhas.application.campaign_decision_paired_comparison"
        )

    def test_builder_signature_is_keyword_only_and_clock_free(self) -> None:
        signature = inspect.signature(build_ordered_objective_paired_comparisons)
        assert tuple(signature.parameters) == ("policy", "outcome_matrix")
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        for parameter in signature.parameters.values():
            assert parameter.name not in {"now", "clock", "timestamp", "wall_clock", "current_time"}

    def test_imported_module_boundary(self) -> None:
        tree = _module_tree()
        modules = _imported_modules(tree)
        assert modules <= {"__future__", "typing", "math", "warnings", "pydantic", "kalhas"}
        kalhas_paths = {
            path
            for path in _imported_module_paths(tree)
            if path == "kalhas" or path.startswith("kalhas.")
        }
        assert kalhas_paths <= {
            "kalhas.application.campaign_decision_statistics",
            "kalhas.contracts.v1.campaign_decision",
            "kalhas.contracts.v1.campaign_outcome",
        }

    def test_no_forbidden_module_imports(self) -> None:
        forbidden = {
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "os",
            "sys",
            "subprocess",
            "shutil",
            "tempfile",
            "pathlib",
            "random",
            "uuid",
            "secrets",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
            "datetime",
            "time",
            "dateutil",
        }
        assert not (_imported_modules(_module_tree()) & forbidden)

    def test_no_clock_randomness_or_process_hash_calls(self) -> None:
        tree = _module_tree()
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_chains = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "time.time",
            "time.monotonic",
            "time.perf_counter",
            "random.seed",
            "random.random",
            "uuid.uuid4",
            "os.getpid",
            "os.urandom",
        }
        assert not (calls & forbidden_chains)
        assert "hash" not in calls
        assert not any(chain.startswith("random.") for chain in calls)

    def test_no_store_api_identity_hash_query_or_activity_surface(self) -> None:
        tree = _module_tree()
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names
        assert "api" not in names
        assert "identity" not in names
        assert "query" not in names
        assert "activity" not in names
        module_paths = _imported_module_paths(tree)
        forbidden_imports = {
            "kalhas.application.in_memory_store",
            "kalhas.application.campaign_decision_identity",
            "kalhas.application.campaign_decision_errors",
            "kalhas.application.campaign_decision_policy_service",
            "kalhas.application.hashing",
            "kalhas.application.campaign_outcome_identity",
            "kalhas.api",
        }
        assert not any(
            path == forbidden or path.startswith(forbidden + ".")
            for path in module_paths
            for forbidden in forbidden_imports
        )
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_writes = {
            "put_",
            "record_operational_activity",
            "record_activity",
            "start",
            "prepare_campaign",
            "execute_campaign",
        }
        for call in calls:
            assert not any(call.startswith(fragment) for fragment in ("store.", "put_")), call
            assert call not in forbidden_writes, call

    def test_no_decision_surface_symbols(self) -> None:
        forbidden = _DECISION_SURFACE_PATTERN
        tree = _module_tree()
        symbols = set(_imported_symbols(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.add(node.name)
                symbols.update(argument.arg for argument in node.args.args)
            if isinstance(node, ast.ClassDef):
                symbols.add(node.name)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden decision symbol {symbol!r}"

    def test_no_executable_expression_or_callback_surface(self) -> None:
        tree = _module_tree()
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Lambda), "lambda in the pure builder"
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"exec", "eval", "compile", "__import__"}, (
                    f"executable call {name!r}"
                )
        symbols = _imported_symbols(tree)
        assert not any(symbol in symbols for symbol in ("Callable", "callback"))

    def test_module_source_free_of_phase_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))


def _module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``math`` from ``math.fsum``)."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths


def _imported_symbols(tree: ast.Module) -> set[str]:
    """Every name bound by an ``import``/``from`` statement."""
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names)
    return symbols


def _attribute_call_chains(tree: ast.Module) -> set[str]:
    """Dotted callable chains of every call whose target is an attribute."""
    chains: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        parts: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        chains.add(".".join(reversed(parts)))
    return chains


def _name_calls(tree: ast.Module) -> set[str]:
    """Every bare-name call (``sorted(...)`` -> ``sorted``)."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    return calls


#: The decision-surface symbol pattern (no dominance/regret/minimax/
#: status/brief/recommendation surface may exist in the pure builder).
_DECISION_SURFACE_PATTERN = re.compile(
    r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief|"
    r"dominance|dominat|regret|minimax|feasib|status|adaptive",
    re.IGNORECASE,
)
