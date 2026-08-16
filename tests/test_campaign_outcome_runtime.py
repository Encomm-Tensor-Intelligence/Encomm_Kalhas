"""Tests for the pure deterministic strategy/objective campaign-outcome builder.

Phase 26 runtime-slice tests for
``kalhas/application/campaign_outcome_runtime.py``: the single public
``build_strategy_objective_outcome`` builder. Proves:

- the exact public surface (keyword-only signature, exact ``__all__``);
- golden targeted minimize/maximize/reach outcomes and golden
  optimization-only outcomes with all five targeted evidence fields
  ``None``;
- exact achievement counts and probabilities at target/tolerance
  boundaries;
- exact normalized violation tuples in original seed order;
- actual primitive-generated CVaR and adverse-tail values, including
  the fractional n=21/n=41 tail boundaries;
- one-sample, short-tail, repeated-vector, negative, and mixed
  int/float behavior;
- legal finite-float projections (``2**53 + 1``, ``-(2**53 + 1)``,
  ``10**100``) and unrepresentable-integer ``OverflowError``;
- the complete rejection matrix (empty/list/bool/string/``Decimal``/
  ``None``/container/NaN/Infinity, validator-bypassed and wrong-object
  bindings, invalid positions, empty strategy identity, and
  arithmetic/statistical overflow) with the exact exception types -
  ``ValueError`` for invalid shape/type/non-finite input and
  ``OverflowError`` for finite-float conversion and statistical
  overflow, never silently converted;
- exact snapshot copying from the binding, input immutability, and
  repeated-call deterministic equality of ``model_dump(mode="json")``;
- the architectural boundary: the module imports only the standard
  library, pydantic, and the accepted statistics/contract modules,
  reuses (never redefines) every accepted primitive and algorithm
  constant by identity, carries no store/API/query/clock/randomness/
  executable surface, and exposes no ranking/winner/preference/
  recommendation vocabulary.

Golden results use exact equality whenever the result is exactly
representable; mathematically non-terminating fractional results use
one-ULP assertions (``abs(actual - expected) <= math.ulp(expected)``),
the same convention the accepted statistics-slice tests use.
"""

from __future__ import annotations

import ast
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_metric_statistics_runtime import (
    statistics_arithmetic_mean,
    statistics_median,
    statistics_population_standard_deviation,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.campaign_outcome_statistics import (
    empirical_lower_tail_mean_95,
    empirical_upper_tail_mean_95,
)
from kalhas.contracts.v1.campaign_outcome import (
    EmpiricalDistributionSummary,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_outcome_runtime.py"
)


def _binding(**overrides: object) -> ObjectiveMetricBinding:
    """One valid minimize binding: target 100, scale 100, weight 1, unit ``units``."""
    payload: dict[str, object] = {
        "objective_id": "obj-1",
        "metric_id": "m-1",
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "metric_unit": "units",
        "reach_tolerance": None,
        "normalization_scale": 100.0,
    }
    payload.update(overrides)
    return ObjectiveMetricBinding(**cast(Any, payload))


def _bypassed_binding(**overrides: object) -> ObjectiveMetricBinding:
    """One validator-bypassed binding (``model_construct``) with the same defaults."""
    payload: dict[str, object] = {
        "objective_id": "obj-1",
        "metric_id": "m-1",
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "metric_unit": "units",
        "reach_tolerance": None,
        "normalization_scale": 100.0,
    }
    payload.update(overrides)
    return ObjectiveMetricBinding.model_construct(**cast(Any, payload))


def _call_with(**overrides: object) -> StrategyObjectiveOutcome:
    """Call the builder with the canonical defaults, applying overrides."""
    payload: dict[str, object] = {
        "sequence_position": 0,
        "strategy_position": 0,
        "objective_position": 0,
        "strategy_candidate_id": "sc-1",
        "binding": _binding(),
        "ordered_observed_values": (91, 95, 110, 120),
    }
    payload.update(overrides)
    return build_strategy_objective_outcome(**cast(Any, payload))


def _call(
    *,
    sequence_position: int = 0,
    strategy_position: int = 0,
    objective_position: int = 0,
    strategy_candidate_id: str = "sc-1",
    binding: ObjectiveMetricBinding | None = None,
    ordered_observed_values: tuple[int | float, ...] = (91, 95, 110, 120),
) -> StrategyObjectiveOutcome:
    """The typed happy-path call helper."""
    return _call_with(
        sequence_position=sequence_position,
        strategy_position=strategy_position,
        objective_position=objective_position,
        strategy_candidate_id=strategy_candidate_id,
        binding=_binding() if binding is None else binding,
        ordered_observed_values=ordered_observed_values,
    )


def _recomputed_violations(
    values: tuple[int | float, ...],
    direction: str,
    target: float,
    reach_tolerance: float | None,
    normalization_scale: float,
) -> tuple[float, ...]:
    """The exact normalized target violation of every value, in seed order."""
    result: list[float] = []
    for value in values:
        if direction == "minimize":
            delta = value - target
        elif direction == "maximize":
            delta = target - value
        else:
            assert reach_tolerance is not None
            delta = abs(value - target) - reach_tolerance
        result.append(max(0.0, delta) / normalization_scale)
    return tuple(result)


def _recomputed_achievement_count(
    values: tuple[int | float, ...],
    direction: str,
    target: float,
    reach_tolerance: float | None,
) -> int:
    """The exact count of observed values that achieve the target."""
    count = 0
    for value in values:
        if direction == "minimize":
            achieved = value <= target
        elif direction == "maximize":
            achieved = value >= target
        else:
            assert reach_tolerance is not None
            achieved = abs(value - target) <= reach_tolerance
        if achieved:
            count += 1
    return count


def _assert_within_one_ulp(actual: float, expected: float) -> None:
    """Prove the result differs from the rational reference by at most one ULP."""
    assert abs(actual - expected) <= math.ulp(expected)


class TestGoldenTargetedMinimize:
    def test_golden_outcome(self) -> None:
        outcome = _call(ordered_observed_values=(91, 95, 110, 120))
        summary = outcome.empirical_distribution
        assert summary.ordered_samples == (91, 95, 110, 120)
        assert summary.sample_count == 4
        assert summary.minimum == 91.0
        assert summary.maximum == 120.0
        assert summary.arithmetic_mean == 104.0
        assert summary.median == 102.5
        assert summary.population_standard_deviation == 11.640446726822816
        assert summary.p05 == 91.6
        assert summary.p25 == 94.0
        assert summary.p75 == 112.5
        assert summary.p95 == 118.5
        assert summary.quantile_algorithm == "hyndman-fan-type-7-v1"

    def test_golden_targeted_evidence(self) -> None:
        outcome = _call(ordered_observed_values=(91, 95, 110, 120))
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0, 0.0, 0.1, 0.2)
        assert violations.sample_count == 4
        assert violations.minimum == 0.0
        assert violations.maximum == 0.2
        assert violations.arithmetic_mean == 0.07500000000000001
        assert violations.median == 0.05
        assert violations.population_standard_deviation == 0.082915619758885
        assert violations.p75 == 0.125
        assert violations.p95 == 0.185
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 0.5
        assert outcome.worst_normalized_target_violation == 0.2
        assert outcome.target_violation_cvar == 0.2
        assert outcome.adverse_tail_statistic == 120.0
        assert outcome.tail_alpha == 0.95
        assert outcome.tail_algorithm == "empirical-fractional-tail-mean-v1"


class TestGoldenTargetedMaximize:
    def test_golden_outcome(self) -> None:
        binding = _binding(direction="maximize")
        outcome = _call(binding=binding, ordered_observed_values=(80, 90, 110, 130))
        summary = outcome.empirical_distribution
        assert summary.minimum == 80.0
        assert summary.maximum == 130.0
        assert summary.arithmetic_mean == 102.5
        assert summary.median == 100.0
        assert summary.population_standard_deviation == 19.20286436967152
        assert summary.p05 == 81.5
        assert summary.p95 == 127.0
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.2, 0.1, 0.0, 0.0)
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 0.5
        assert outcome.worst_normalized_target_violation == 0.2
        assert outcome.target_violation_cvar == 0.2
        assert outcome.adverse_tail_statistic == 80.0


class TestGoldenTargetedReach:
    def test_golden_outcome(self) -> None:
        binding = _binding(direction="reach", reach_tolerance=5.0)
        outcome = _call(binding=binding, ordered_observed_values=(90, 96, 104, 110))
        summary = outcome.empirical_distribution
        assert summary.minimum == 90.0
        assert summary.maximum == 110.0
        assert summary.arithmetic_mean == 100.0
        assert summary.median == 100.0
        assert summary.population_standard_deviation == 7.615773105863909
        assert summary.p05 == 90.9
        assert summary.p25 == 94.5
        assert summary.p75 == 105.5
        assert summary.p95 == 109.1
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.05, 0.0, 0.0, 0.05)
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 0.5
        assert outcome.worst_normalized_target_violation == 0.05
        assert outcome.target_violation_cvar == 0.05
        assert outcome.adverse_tail_statistic == 10.0


class TestGoldenOptimizationOnly:
    def test_minimize_without_target_leaves_all_targeted_fields_none(self) -> None:
        binding = _binding(target=None)
        outcome = _call(binding=binding, ordered_observed_values=(5, 7, 9))
        assert outcome.target is None
        assert outcome.target_achievement_count is None
        assert outcome.empirical_target_achievement_probability is None
        assert outcome.normalized_target_violation_distribution is None
        assert outcome.worst_normalized_target_violation is None
        assert outcome.target_violation_cvar is None
        assert outcome.adverse_tail_statistic == 9.0
        summary = outcome.empirical_distribution
        assert summary.minimum == 5.0
        assert summary.maximum == 9.0
        assert summary.arithmetic_mean == 7.0
        assert summary.median == 7.0
        assert summary.population_standard_deviation == 1.632993161855452

    def test_maximize_without_target_leaves_all_targeted_fields_none(self) -> None:
        binding = _binding(direction="maximize", target=None)
        outcome = _call(binding=binding, ordered_observed_values=(5, 7, 9))
        assert outcome.target_achievement_count is None
        assert outcome.empirical_target_achievement_probability is None
        assert outcome.normalized_target_violation_distribution is None
        assert outcome.worst_normalized_target_violation is None
        assert outcome.target_violation_cvar is None
        assert outcome.adverse_tail_statistic == 5.0
        assert outcome.direction == "maximize"

    def test_adverse_tail_remains_available_for_optimization_only(self) -> None:
        binding = _binding(direction="maximize", target=None)
        outcome = _call(binding=binding, ordered_observed_values=(10, 20, 30))
        assert outcome.adverse_tail_statistic == 10.0


class TestAchievementBoundaries:
    def test_minimize_boundary_values_are_achieved(self) -> None:
        outcome = _call(ordered_observed_values=(100, 100))
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 1.0

    def test_minimize_just_above_target_not_achieved(self) -> None:
        outcome = _call(ordered_observed_values=(100.0, 100.0001))
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 0.5

    def test_minimize_never_achieved(self) -> None:
        outcome = _call(ordered_observed_values=(101, 102))
        assert outcome.target_achievement_count == 0
        assert outcome.empirical_target_achievement_probability == 0.0

    def test_maximize_boundary_values_are_achieved(self) -> None:
        outcome = _call(binding=_binding(direction="maximize"), ordered_observed_values=(100, 100))
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 1.0

    def test_maximize_just_below_target_not_achieved(self) -> None:
        outcome = _call(binding=_binding(direction="maximize"), ordered_observed_values=(100, 99))
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 0.5

    def test_reach_exactly_at_tolerance_is_achieved(self) -> None:
        outcome = _call(
            binding=_binding(direction="reach", reach_tolerance=5.0),
            ordered_observed_values=(95, 105),
        )
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 1.0

    def test_reach_just_beyond_tolerance_not_achieved(self) -> None:
        outcome = _call(
            binding=_binding(direction="reach", reach_tolerance=5.0),
            ordered_observed_values=(94, 106),
        )
        assert outcome.target_achievement_count == 0
        assert outcome.empirical_target_achievement_probability == 0.0

    def test_fractional_probability_is_exact_count_over_sample_count(self) -> None:
        outcome = _call(
            binding=_binding(direction="reach", reach_tolerance=5.0),
            ordered_observed_values=(95, 105, 106),
        )
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 2 / 3
        assert outcome.empirical_target_achievement_probability == 2 / len((95, 105, 106))


class TestNormalizedViolationSeedOrder:
    def test_minimize_violations_preserve_seed_order(self) -> None:
        values = (120, 91, 110, 95)
        outcome = _call(ordered_observed_values=values)
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert outcome.ordered_observed_values == values
        assert violations.ordered_samples == (0.2, 0.0, 0.1, 0.0)
        assert violations.ordered_samples == _recomputed_violations(
            values, "minimize", 100.0, None, 100.0
        )

    def test_maximize_violations_preserve_seed_order(self) -> None:
        values = (70, 130, 100, 80)
        outcome = _call(binding=_binding(direction="maximize"), ordered_observed_values=values)
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.3, 0.0, 0.0, 0.2)
        assert violations.ordered_samples == _recomputed_violations(
            values, "maximize", 100.0, None, 100.0
        )

    def test_reach_violations_preserve_seed_order(self) -> None:
        values = (90, 110, 80, 120)
        outcome = _call(
            binding=_binding(direction="reach", reach_tolerance=5.0),
            ordered_observed_values=values,
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.05, 0.05, 0.15, 0.15)
        assert violations.ordered_samples == _recomputed_violations(
            values, "reach", 100.0, 5.0, 100.0
        )

    def test_achievement_count_matches_independent_recomputation(self) -> None:
        values = (120, 91, 110, 95)
        outcome = _call(ordered_observed_values=values)
        assert outcome.target_achievement_count == _recomputed_achievement_count(
            values, "minimize", 100.0, None
        )


class TestPrimitiveGeneratedCvarAndAdverseTail:
    def test_minimize_n21_fractional_cvar(self) -> None:
        values = tuple(range(1, 22))
        outcome = _call(
            binding=_binding(target=0.0, normalization_scale=1.0),
            ordered_observed_values=values,
        )
        assert outcome.target_violation_cvar == empirical_upper_tail_mean_95(values)
        assert outcome.adverse_tail_statistic == empirical_upper_tail_mean_95(values)
        _assert_within_one_ulp(outcome.target_violation_cvar, (100 * 21 + 5 * 20) / 105)

    def test_maximize_n21_fractional_tails(self) -> None:
        values = tuple(range(1, 22))
        outcome = _call(
            binding=_binding(direction="maximize", target=1000.0, normalization_scale=1.0),
            ordered_observed_values=values,
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert outcome.target_violation_cvar == empirical_upper_tail_mean_95(
            violations.ordered_samples
        )
        _assert_within_one_ulp(outcome.target_violation_cvar, (100 * 999 + 5 * 998) / 105)
        assert outcome.adverse_tail_statistic == empirical_lower_tail_mean_95(values)
        _assert_within_one_ulp(outcome.adverse_tail_statistic, 110 / 105)

    def test_n41_two_full_observations_fractional_cvar(self) -> None:
        values = tuple(range(1, 42))
        outcome = _call(
            binding=_binding(target=0.0, normalization_scale=1.0),
            ordered_observed_values=values,
        )
        assert outcome.target_violation_cvar is not None
        _assert_within_one_ulp(outcome.target_violation_cvar, (100 * 41 + 100 * 40 + 5 * 39) / 205)

    def test_reach_cvar_and_adverse_tail_come_from_the_primitives(self) -> None:
        values = tuple(range(80, 122, 2))
        binding = _binding(direction="reach", target=100.0, reach_tolerance=5.0)
        outcome = _call(binding=binding, ordered_observed_values=values)
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        expected_violations = _recomputed_violations(values, "reach", 100.0, 5.0, 100.0)
        assert violations.ordered_samples == expected_violations
        assert outcome.target_violation_cvar == empirical_upper_tail_mean_95(expected_violations)
        expected_deviations = tuple(abs(value - 100.0) for value in values)
        assert outcome.adverse_tail_statistic == empirical_upper_tail_mean_95(expected_deviations)

    def test_constant_violation_cvar_is_exact(self) -> None:
        outcome = _call(ordered_observed_values=(80, 80, 80))
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert outcome.target_violation_cvar == 0.0
        assert outcome.worst_normalized_target_violation == 0.0


class TestOneSample:
    def test_single_sample_all_derived_values_equal_the_sample(self) -> None:
        outcome = _call(ordered_observed_values=(7,))
        summary = outcome.empirical_distribution
        assert summary.sample_count == 1
        assert summary.minimum == 7.0
        assert summary.maximum == 7.0
        assert summary.arithmetic_mean == 7.0
        assert summary.median == 7.0
        assert summary.population_standard_deviation == 0.0
        assert summary.p05 == 7.0
        assert summary.p25 == 7.0
        assert summary.p75 == 7.0
        assert summary.p95 == 7.0

    def test_single_sample_achieved(self) -> None:
        outcome = _call(
            binding=_binding(target=10.0, normalization_scale=1.0),
            ordered_observed_values=(7,),
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0,)
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 1.0
        assert outcome.worst_normalized_target_violation == 0.0
        assert outcome.target_violation_cvar == 0.0
        assert outcome.adverse_tail_statistic == 7.0

    def test_single_sample_missed(self) -> None:
        outcome = _call(binding=_binding(target=5.0), ordered_observed_values=(7,))
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.02,)
        assert outcome.target_achievement_count == 0
        assert outcome.empirical_target_achievement_probability == 0.0
        assert outcome.worst_normalized_target_violation == 0.02
        assert outcome.target_violation_cvar == 0.02

    def test_single_sample_maximize(self) -> None:
        outcome = _call(
            binding=_binding(direction="maximize", target=10.0),
            ordered_observed_values=(7,),
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.03,)
        assert outcome.target_achievement_count == 0
        assert outcome.target_violation_cvar == 0.03
        assert outcome.adverse_tail_statistic == 7.0

    def test_single_sample_reach(self) -> None:
        outcome = _call(
            binding=_binding(direction="reach", target=10.0, reach_tolerance=2.0),
            ordered_observed_values=(7,),
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.01,)
        assert outcome.target_achievement_count == 0
        assert outcome.target_violation_cvar == 0.01
        assert outcome.adverse_tail_statistic == 3.0


class TestShortTail:
    def test_two_sample_minimize(self) -> None:
        outcome = _call(binding=_binding(target=15.0), ordered_observed_values=(10, 20))
        summary = outcome.empirical_distribution
        assert summary.arithmetic_mean == 15.0
        assert summary.median == 15.0
        assert summary.population_standard_deviation == 5.0
        assert summary.p05 == 10.5
        assert summary.p95 == 19.5
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0, 0.05)
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 0.5
        assert outcome.adverse_tail_statistic == 20.0

    def test_two_sample_maximize(self) -> None:
        outcome = _call(
            binding=_binding(direction="maximize", target=15.0),
            ordered_observed_values=(10, 20),
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.05, 0.0)
        assert outcome.target_achievement_count == 1
        assert outcome.adverse_tail_statistic == 10.0


class TestRepeatedVectors:
    def test_repeated_ints_emit_exact_zero_standard_deviation(self) -> None:
        outcome = _call(ordered_observed_values=(99, 99, 99))
        summary = outcome.empirical_distribution
        assert summary.population_standard_deviation == 0.0
        assert summary.minimum == 99.0
        assert summary.maximum == 99.0
        assert summary.arithmetic_mean == 99.0
        assert summary.median == 99.0
        assert summary.p05 == 99.00000000000001
        assert summary.p25 == 99.0
        assert summary.p75 == 99.0
        assert summary.p95 == 99.00000000000001

    def test_repeated_floats_emit_exact_zero_standard_deviation(self) -> None:
        outcome = _call(ordered_observed_values=(0.1, 0.1, 0.1))
        summary = outcome.empirical_distribution
        assert summary.population_standard_deviation == 0.0
        assert summary.minimum == 0.1
        assert summary.maximum == 0.1
        assert summary.arithmetic_mean == 0.10000000000000002
        assert summary.median == 0.1
        assert summary.p05 == 0.1
        assert summary.p25 == 0.1
        assert summary.p75 == 0.1
        assert summary.p95 == 0.1

    def test_repeated_float_vector_of_21(self) -> None:
        outcome = _call(ordered_observed_values=(100.0,) * 21)
        summary = outcome.empirical_distribution
        assert summary.sample_count == 21
        assert summary.population_standard_deviation == 0.0
        assert summary.minimum == 100.0
        assert summary.maximum == 100.0
        assert summary.arithmetic_mean == 100.0
        assert summary.median == 100.0
        assert summary.p05 == 100.0
        assert summary.p25 == 100.0
        assert summary.p75 == 100.0
        assert summary.p95 == 100.0

    def test_repeated_vector_targeted_evidence(self) -> None:
        outcome = _call(
            binding=_binding(target=100.0, normalization_scale=1.0),
            ordered_observed_values=(100.0,) * 21,
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0,) * 21
        assert violations.population_standard_deviation == 0.0
        assert outcome.target_achievement_count == 21
        assert outcome.empirical_target_achievement_probability == 1.0
        assert outcome.worst_normalized_target_violation == 0.0
        assert outcome.target_violation_cvar == 0.0
        # The fixed-alpha fractional upper-tail mean of a constant
        # vector can land one ULP below the constant (the accepted
        # deterministic primitive artifact).
        _assert_within_one_ulp(outcome.adverse_tail_statistic, 100.0)
        assert outcome.adverse_tail_statistic == empirical_upper_tail_mean_95((100.0,) * 21)


class TestNegativeAndMixedObservations:
    def test_negative_values_minimize(self) -> None:
        outcome = _call(binding=_binding(target=-2.0), ordered_observed_values=(-5, -4, -3, -2, -1))
        summary = outcome.empirical_distribution
        assert summary.minimum == -5.0
        assert summary.maximum == -1.0
        assert summary.arithmetic_mean == -3.0
        assert summary.median == -3.0
        assert summary.population_standard_deviation == 1.4142135623730951
        _assert_within_one_ulp(summary.p05, -4.8)
        _assert_within_one_ulp(summary.p95, -1.2)
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0, 0.0, 0.0, 0.0, 0.01)
        assert outcome.target_achievement_count == 4
        assert outcome.empirical_target_achievement_probability == 0.8
        assert outcome.worst_normalized_target_violation == 0.01
        assert outcome.adverse_tail_statistic == -1.0

    def test_negative_values_maximize(self) -> None:
        outcome = _call(
            binding=_binding(direction="maximize", target=-4.0),
            ordered_observed_values=(-5, -4, -3, -2, -1),
        )
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.01, 0.0, 0.0, 0.0, 0.0)
        assert outcome.target_achievement_count == 4
        assert outcome.empirical_target_achievement_probability == 0.8
        assert outcome.adverse_tail_statistic == -5.0

    def test_mixed_int_float_values_preserve_exact_types(self) -> None:
        values = (1, 2.5, 3, 4.5, 6)
        outcome = _call(ordered_observed_values=values)
        assert outcome.ordered_observed_values == values
        assert type(outcome.ordered_observed_values[0]) is int
        assert type(outcome.ordered_observed_values[1]) is float
        summary = outcome.empirical_distribution
        assert summary.ordered_samples == values
        assert summary.arithmetic_mean == 3.4
        assert summary.p25 == 2.5
        assert summary.p75 == 4.5


class TestLegalFiniteFloatProjections:
    def test_two_to_53_plus_one_projects_to_nearest_float(self) -> None:
        projected = float(2**53 + 1)
        assert projected == 9007199254740992.0
        outcome = _call(
            binding=_binding(target=projected, normalization_scale=1.0),
            ordered_observed_values=(2**53 + 1,),
        )
        summary = outcome.empirical_distribution
        assert summary.minimum == projected
        assert summary.maximum == projected
        assert summary.arithmetic_mean == projected
        assert summary.median == projected
        assert summary.population_standard_deviation == 0.0
        assert summary.p05 == projected
        assert summary.p95 == projected
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0,)
        # The achievement comparison is exact on the raw integer: the
        # integer 2**53 + 1 is strictly greater than the float
        # projection 9007199254740992.0, so the single sample is not
        # achieved even though the violation delta is exactly 0.0.
        assert outcome.target_achievement_count == 0
        assert outcome.empirical_target_achievement_probability == 0.0
        assert outcome.adverse_tail_statistic == projected

    def test_negative_two_to_53_plus_one_projects_to_nearest_float(self) -> None:
        projected = float(-(2**53 + 1))
        assert projected == -9007199254740992.0
        binding = _binding(direction="maximize", target=projected, normalization_scale=1.0)
        outcome = _call(binding=binding, ordered_observed_values=(-(2**53 + 1),))
        assert outcome.empirical_distribution.minimum == projected
        assert outcome.empirical_distribution.population_standard_deviation == 0.0
        assert outcome.target_achievement_count == 0
        violations = outcome.normalized_target_violation_distribution
        assert violations is not None
        assert violations.ordered_samples == (0.0,)

    def test_ten_to_hundred_projects_to_finite_float(self) -> None:
        outcome = _call(ordered_observed_values=(10**100,))
        summary = outcome.empirical_distribution
        assert summary.minimum == 1e100
        assert summary.maximum == 1e100
        assert summary.arithmetic_mean == 1e100
        assert summary.median == 1e100
        assert summary.population_standard_deviation == 0.0
        assert summary.p05 == 1e100
        assert summary.p95 == 1e100

    def test_ten_to_hundred_repeated(self) -> None:
        outcome = _call(ordered_observed_values=(10**100, 10**100))
        summary = outcome.empirical_distribution
        assert summary.population_standard_deviation == 0.0
        assert summary.minimum == 1e100
        assert summary.maximum == 1e100
        assert summary.arithmetic_mean == 1e100

    def test_mixed_projection_summary(self) -> None:
        values = (2**53 + 1, 1)
        outcome = _call(ordered_observed_values=values)
        summary = outcome.empirical_distribution
        assert summary.minimum == 1.0
        assert summary.maximum == float(2**53 + 1)
        assert summary.arithmetic_mean == statistics_arithmetic_mean(values)
        assert summary.median == statistics_median(values)
        assert summary.population_standard_deviation == statistics_population_standard_deviation(
            values
        )


class TestUnrepresentableIntegersOverflow:
    @pytest.mark.parametrize(
        "values",
        (
            pytest.param((10**400,), id="single-huge-integer"),
            pytest.param((-(10**400),), id="single-negative-huge-integer"),
            pytest.param((10**400, 10**400), id="all-huge-integers"),
            pytest.param((1, 10**400), id="huge-integer-last-position"),
            pytest.param((10**400, 1), id="huge-integer-first-position"),
            pytest.param((1, 10**400, 2), id="huge-integer-middle-position"),
            pytest.param((1, -(10**400)), id="negative-huge-integer-last-position"),
            pytest.param((-(10**400), 1), id="negative-huge-integer-first-position"),
        ),
    )
    def test_huge_integer_raises_overflow_error(self, values: object) -> None:
        with pytest.raises(OverflowError):
            _call_with(ordered_observed_values=cast(Any, values))

    def test_huge_integer_rejected_before_any_statistical_work(self) -> None:
        # The conversion proof covers every sample before any quantile,
        # tail, or summary arithmetic begins.
        with pytest.raises(OverflowError):
            _call_with(
                binding=_binding(target=0.0),
                ordered_observed_values=cast(Any, (10**400,)),
            )


class TestInvalidObservedValues:
    @pytest.mark.parametrize(
        "values",
        (
            pytest.param((), id="empty-tuple"),
            pytest.param(cast(Any, [1, 2, 3]), id="list-not-tuple"),
            pytest.param(cast(Any, (True, 1, 2)), id="bool-sample"),
            pytest.param(cast(Any, (1, False)), id="bool-sample-second"),
            pytest.param(cast(Any, ("5", 1)), id="string-sample"),
            pytest.param(cast(Any, (1, None)), id="none-sample"),
            pytest.param(cast(Any, (1, [2])), id="list-container-sample"),
            pytest.param(cast(Any, (1, (2, 3))), id="tuple-container-sample"),
            pytest.param(cast(Any, ({1: 2}, 3)), id="dict-container-sample"),
            pytest.param(cast(Any, (1, Decimal("1.5"))), id="decimal-sample"),
            pytest.param(cast(Any, (1, 2j)), id="complex-sample"),
            pytest.param((1.0, float("nan")), id="nan-sample"),
            pytest.param((1.0, float("inf")), id="positive-infinity-sample"),
            pytest.param((1.0, float("-inf")), id="negative-infinity-sample"),
        ),
    )
    def test_invalid_observed_values_rejected(self, values: object) -> None:
        with pytest.raises(ValueError):
            _call_with(ordered_observed_values=cast(Any, values))

    @pytest.mark.parametrize(
        "values",
        (
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, "abc"), id="string"),
            pytest.param(cast(Any, 42), id="integer"),
            pytest.param(cast(Any, {1: 2}), id="dict"),
        ),
    )
    def test_non_tuple_observed_values_rejected(self, values: object) -> None:
        with pytest.raises(ValueError):
            _call_with(ordered_observed_values=values)

    def test_tuple_subclass_rejected(self) -> None:
        class _TupleSubclass(tuple[int, ...]):
            pass

        with pytest.raises(ValueError):
            _call_with(ordered_observed_values=cast(Any, _TupleSubclass((1, 2))))


class TestBindingRevalidation:
    @pytest.mark.parametrize(
        "wrong",
        (
            pytest.param(cast(Any, {"objective_id": "o"}), id="dict"),
            pytest.param(cast(Any, "binding"), id="string"),
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, 42), id="integer"),
            pytest.param(cast(Any, (1, 2)), id="tuple"),
        ),
    )
    def test_wrong_object_binding_rejected(self, wrong: object) -> None:
        with pytest.raises(ValueError):
            _call_with(binding=wrong)

    def test_wrong_model_type_rejected(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(
            {
                "ordered_samples": [1, 2, 3],
                "sample_count": 3,
                "minimum": 1.0,
                "maximum": 3.0,
                "arithmetic_mean": 2.0,
                "median": 2.0,
                "population_standard_deviation": 0.0,
                "quantile_algorithm": "hyndman-fan-type-7-v1",
                "p05": 1.1,
                "p25": 1.5,
                "p75": 2.5,
                "p95": 2.9,
            }
        )
        with pytest.raises(ValueError):
            _call_with(binding=cast(Any, summary))

    def test_outcome_model_rejected_as_binding(self) -> None:
        outcome = _call()
        with pytest.raises(ValueError):
            _call_with(binding=cast(Any, outcome))

    @pytest.mark.parametrize(
        "overrides",
        (
            pytest.param({"target": float("nan")}, id="nan-target"),
            pytest.param({"target": float("inf")}, id="infinite-target"),
            pytest.param({"target": "100"}, id="string-target"),
            pytest.param({"target": True}, id="bool-target"),
            pytest.param({"weight": True}, id="bool-weight"),
            pytest.param({"weight": -1.0}, id="negative-weight"),
            pytest.param({"normalization_scale": -1.0}, id="negative-scale"),
            pytest.param({"normalization_scale": 0.0}, id="zero-scale"),
            pytest.param({"normalization_scale": "100"}, id="string-scale"),
            pytest.param({"direction": "sideways"}, id="invalid-direction"),
            pytest.param({"direction": True}, id="bool-direction"),
            pytest.param({"direction": "reach", "target": None}, id="reach-without-target"),
            pytest.param({"direction": "reach"}, id="reach-without-tolerance"),
            pytest.param({"direction": "reach", "reach_tolerance": -1.0}, id="negative-tolerance"),
            pytest.param({"reach_tolerance": 5.0}, id="tolerance-on-minimize"),
            pytest.param({"objective_id": ""}, id="empty-objective-id"),
            pytest.param({"metric_id": ""}, id="empty-metric-id"),
        ),
    )
    def test_validator_bypassed_binding_rejected(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            _call_with(binding=_bypassed_binding(**overrides))

    def test_validator_bypassed_binding_with_valid_values_is_trusted(self) -> None:
        outcome = _call_with(binding=_bypassed_binding())
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 0.5
        assert outcome.adverse_tail_statistic == 120.0

    def test_bypassed_valid_binding_matches_normal_binding(self) -> None:
        normal = _call_with(binding=_binding())
        bypassed = _call_with(binding=_bypassed_binding())
        assert bypassed.model_dump(mode="json") == normal.model_dump(mode="json")

    def test_bypassed_binding_is_never_mutated(self) -> None:
        binding = _bypassed_binding(normalization_scale=-1.0)
        before = binding.model_dump(mode="python")
        with pytest.raises(ValueError):
            _call_with(binding=binding)
        assert binding.model_dump(mode="python") == before


class TestPositionsAndStrategyIdentity:
    @pytest.mark.parametrize(
        "position_field",
        ("sequence_position", "strategy_position", "objective_position"),
    )
    @pytest.mark.parametrize(
        "value",
        (
            pytest.param(True, id="bool-true"),
            pytest.param(False, id="bool-false"),
            pytest.param(1.5, id="float"),
            pytest.param(0.0, id="integral-float"),
            pytest.param("0", id="numeric-string"),
            pytest.param(-1, id="negative"),
            pytest.param(None, id="none"),
        ),
    )
    def test_positions_must_be_exact_non_negative_ints(
        self, position_field: str, value: object
    ) -> None:
        with pytest.raises(ValueError):
            _call_with(**{position_field: value})

    @pytest.mark.parametrize(
        "strategy_id",
        (
            pytest.param(cast(Any, ""), id="empty"),
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, 5), id="integer"),
            pytest.param(cast(Any, True), id="bool"),
        ),
    )
    def test_strategy_identity_must_be_a_non_empty_string(self, strategy_id: object) -> None:
        with pytest.raises(ValueError):
            _call_with(strategy_candidate_id=strategy_id)

    def test_positions_are_copied_exactly(self) -> None:
        outcome = _call(
            sequence_position=7,
            strategy_position=3,
            objective_position=11,
            strategy_candidate_id="strategy-z",
        )
        assert outcome.sequence_position == 7
        assert outcome.strategy_position == 3
        assert outcome.objective_position == 11
        assert outcome.strategy_candidate_id == "strategy-z"

    def test_builder_is_keyword_only(self) -> None:
        function = cast(Any, build_strategy_objective_outcome)
        with pytest.raises(TypeError):
            function(0, 0, 0, "sc-1", _binding(), (91, 95, 110, 120))


class TestArithmeticAndStatisticalOverflow:
    def test_mean_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            _call_with(ordered_observed_values=cast(Any, (1e308, 1e308)))

    def test_standard_deviation_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            _call_with(ordered_observed_values=cast(Any, (1e308, -1e308)))

    def test_violation_delta_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            _call_with(
                binding=_binding(target=-1e308, normalization_scale=1.0),
                ordered_observed_values=cast(Any, (1e308,)),
            )

    def test_reach_deviation_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            _call_with(
                binding=_binding(
                    direction="reach", target=-1e308, reach_tolerance=0.0, normalization_scale=1.0
                ),
                ordered_observed_values=cast(Any, (1e308,)),
            )

    def test_tiny_scale_violation_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            _call_with(
                binding=_binding(target=0.0, normalization_scale=1e-300),
                ordered_observed_values=cast(Any, (1e308,)),
            )

    def test_large_finite_values_without_overflow_succeed(self) -> None:
        outcome = _call(
            binding=_binding(target=0.0, normalization_scale=1.0),
            ordered_observed_values=cast(Any, (1e308,)),
        )
        assert outcome.empirical_distribution.arithmetic_mean == 1e308
        assert outcome.worst_normalized_target_violation == 1e308
        assert outcome.target_violation_cvar == 1e308
        assert outcome.adverse_tail_statistic == 1e308


class TestSnapshotCopying:
    def test_all_binding_snapshots_copied_exactly(self) -> None:
        binding = _binding(
            objective_id="obj-x",
            metric_id="metric-y",
            metric_unit=None,
            direction="maximize",
            target=42.5,
            weight=2.5,
            normalization_scale=7.5,
        )
        outcome = _call(binding=binding, ordered_observed_values=(10, 20, 30))
        assert outcome.objective_id == "obj-x"
        assert outcome.metric_id == "metric-y"
        assert outcome.metric_unit is None
        assert outcome.direction == "maximize"
        assert outcome.target == 42.5
        assert outcome.weight == 2.5
        assert outcome.normalization_scale == 7.5
        assert outcome.reach_tolerance is None

    def test_metric_unit_and_reach_tolerance_copied_exactly(self) -> None:
        binding = _binding(
            direction="reach",
            target=100.0,
            reach_tolerance=3.5,
            metric_unit="kg",
            weight=0.0,
        )
        outcome = _call(binding=binding, ordered_observed_values=(99, 101))
        assert outcome.metric_unit == "kg"
        assert outcome.reach_tolerance == 3.5
        assert outcome.weight == 0.0
        assert outcome.target == 100.0

    def test_no_campaign_or_matrix_identity_is_derived(self) -> None:
        outcome = _call()
        assert outcome.strategy_candidate_id == "sc-1"
        assert outcome.sequence_position == 0
        # The outcome carries only the caller-supplied strategy identity
        # and positions - no campaign/scenario/world/seed identifiers.
        assert not hasattr(outcome, "campaign_id")
        assert not hasattr(outcome, "scenario_id")
        assert not hasattr(outcome, "world_version_id")


class TestInputsNeverMutated:
    def test_observed_values_tuple_never_mutated(self) -> None:
        values = (91, 95, 110, 120)
        outcome = _call(ordered_observed_values=values)
        assert values == (91, 95, 110, 120)
        assert outcome.ordered_observed_values == values
        assert outcome.empirical_distribution.ordered_samples == values

    def test_binding_never_mutated(self) -> None:
        binding = _binding(direction="maximize", target=50.0, weight=3.0)
        before = binding.model_dump(mode="python")
        _call(binding=binding, ordered_observed_values=(10, 20))
        assert binding.model_dump(mode="python") == before

    def test_outcome_does_not_share_mutable_state_with_inputs(self) -> None:
        values = (1, 2, 3)
        outcome = _call(ordered_observed_values=values)
        assert outcome.ordered_observed_values == values
        assert outcome.ordered_observed_values is not values


class TestDeterminism:
    def test_repeated_calls_produce_equal_json_payloads(self) -> None:
        first = _call()
        second = _call()
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert json.dumps(first.model_dump(mode="json")) == json.dumps(
            second.model_dump(mode="json")
        )

    def test_equivalent_inputs_produce_equal_python_payloads(self) -> None:
        binding_a = _binding()
        binding_b = _binding()
        first = _call(binding=binding_a)
        second = _call(binding=binding_b)
        assert first.model_dump() == second.model_dump()
        assert first == second

    def test_same_binding_instance_reused_is_stable(self) -> None:
        binding = _binding()
        first = _call(binding=binding)
        second = _call(binding=binding)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_targeted_and_optimization_only_payloads_stay_stable(self) -> None:
        for binding in (
            _binding(),
            _binding(direction="maximize", target=None),
            _binding(direction="reach", reach_tolerance=2.0),
        ):
            first = _call(binding=binding, ordered_observed_values=(5, 9, 12))
            second = _call(binding=binding, ordered_observed_values=(5, 9, 12))
            assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestModuleBoundaries:
    def test_exact_public_all(self) -> None:
        import kalhas.application.campaign_outcome_runtime as module

        assert module.__all__ == ["build_strategy_objective_outcome"]
        for name in module.__all__:
            assert hasattr(module, name)

    def test_builder_signature_is_exact(self) -> None:
        import inspect
        from typing import get_type_hints

        parameters = tuple(inspect.signature(build_strategy_objective_outcome).parameters)
        assert parameters == (
            "sequence_position",
            "strategy_position",
            "objective_position",
            "strategy_candidate_id",
            "binding",
            "ordered_observed_values",
        )
        signature = inspect.signature(build_strategy_objective_outcome)
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        hints = get_type_hints(build_strategy_objective_outcome)
        assert hints["return"] is StrategyObjectiveOutcome
        assert hints["binding"] is ObjectiveMetricBinding

    def test_imports_only_stdlib_pydantic_and_the_accepted_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(tree)
        allowed = {
            "__future__",
            "math",
            "warnings",
            "typing",
            "pydantic",
            "kalhas.application.campaign_metric_statistics_runtime",
            "kalhas.application.campaign_outcome_statistics",
            "kalhas.contracts.v1.campaign_outcome",
            "kalhas.contracts.v1.objective_evaluation",
        }
        assert set(module_paths) <= allowed, sorted(set(module_paths) - allowed)
        modules = _imported_modules(tree)
        assert modules == {"__future__", "math", "warnings", "typing", "pydantic", "kalhas"}
        forbidden = {
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "shutil",
            "tempfile",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "random",
            "uuid",
            "secrets",
            "datetime",
            "time",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
        }
        assert not (modules & forbidden)

    def test_reuses_accepted_primitives_without_redefinition(self) -> None:
        import kalhas.application.campaign_metric_statistics_runtime as statistics_runtime
        import kalhas.application.campaign_outcome_runtime as module
        import kalhas.application.campaign_outcome_statistics as outcome_statistics

        assert module.__dict__["statistics_minimum"] is statistics_runtime.statistics_minimum
        assert module.__dict__["statistics_maximum"] is statistics_runtime.statistics_maximum
        assert (
            module.__dict__["statistics_arithmetic_mean"]
            is statistics_runtime.statistics_arithmetic_mean
        )
        assert module.__dict__["statistics_median"] is statistics_runtime.statistics_median
        assert (
            module.__dict__["statistics_population_standard_deviation"]
            is statistics_runtime.statistics_population_standard_deviation
        )
        assert (
            module.__dict__["empirical_type7_quantile"]
            is outcome_statistics.empirical_type7_quantile
        )
        assert (
            module.__dict__["empirical_upper_tail_mean_95"]
            is outcome_statistics.empirical_upper_tail_mean_95
        )
        assert (
            module.__dict__["empirical_lower_tail_mean_95"]
            is outcome_statistics.empirical_lower_tail_mean_95
        )
        assert (
            module.__dict__["EMPIRICAL_QUANTILE_ALGORITHM"]
            is outcome_statistics.EMPIRICAL_QUANTILE_ALGORITHM
        )
        assert (
            module.__dict__["EMPIRICAL_TAIL_ALGORITHM"]
            is outcome_statistics.EMPIRICAL_TAIL_ALGORITHM
        )
        assert module.__dict__["EMPIRICAL_TAIL_ALPHA"] is outcome_statistics.EMPIRICAL_TAIL_ALPHA

    def test_no_store_api_query_or_persistence_identifiers(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names
        assert not ({"InMemoryScenarioStore", "in_memory_store"} & _imported_symbols(tree))
        module_paths = _imported_module_paths(tree)
        assert not any(path.startswith("kalhas.api") for path in module_paths)
        assert not any("query" in path for path in module_paths)

    def test_no_wall_clock_randomness_or_activity_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_calls = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "date.today",
            "time.time",
            "time.monotonic",
            "time.perf_counter",
            "time.clock",
            "time.gmtime",
            "time.localtime",
            "random.seed",
            "random.random",
            "uuid.uuid4",
            "uuid.uuid1",
        }
        assert not (calls & forbidden_calls)
        assert not any(
            "record_activity" in call or "operational_activity" in call for call in calls
        )

    def test_no_executable_expression_surface(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Lambda), "lambda expression in the module"
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"exec", "eval", "compile", "__import__"}, (
                    f"executable call {name!r} in the module"
                )

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        import kalhas.application.campaign_outcome_runtime as module

        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        symbols = list(module.__all__)
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
                symbols.extend(argument.arg for argument in node.args.args)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"

    def test_builder_has_no_clock_or_timestamp_parameters(self) -> None:
        import inspect

        forbidden_parameters = {"now", "clock", "timestamp", "wall_clock", "current_time"}
        parameters = tuple(inspect.signature(build_strategy_objective_outcome).parameters)
        assert not (forbidden_parameters & set(parameters))


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
