"""Campaign-outcome contract tests: the nested immutable value objects.

Phase 26 contract-slice tests for
``kalhas/contracts/v1/campaign_outcome.py``: ``EmpiricalDistributionSummary``,
``StrategyObjectiveOutcome``, and the top-level
``CampaignOutcomeDistributionMatrix``. Proves:

- strict frozen value-object behavior (``extra="forbid"``, assignment
  raises ``ValidationError``), JSON round-trip, list input becoming an
  immutable tuple, exact field order, and no input mutation;
- exact raw numeric validation before any coercion: bool/string/
  ``Decimal``/``None``/container/NaN/Infinity/unrepresentable-integer
  rejection, exact ``int`` requirements for counts and positions, and
  preserved exact ``int``/``float`` types;
- the summary's internal consistency rules: count, exact extrema,
  finite derived values, mean/median within extrema, non-negative
  standard deviation, non-decreasing quantile chain at every adjacent
  boundary, the exact quantile algorithm literal, and the one-sample /
  repeated-value invariants;
- the outcome's general rules (observed/empirical exact agreement,
  finite non-negative weight, finite strictly positive scale, fixed
  alpha and algorithm literals, direction rules for reach tolerance and
  target) and the targeted / optimization-only rules: exact seed-order
  recomputation of normalized target violations and target achievement
  for all three directions, count/probability consistency, worst
  violation equality, CVaR bounds, and adverse-tail structural bounds;
- the architectural boundary: both models are plain ``BaseModel``
  value objects, never registered in ``PUBLIC_CONTRACTS`` (exactly 47
  contracts with the exact runtime-3 tail at indexes 40-45 and the
  campaign outcome-distribution matrix at index 46, and exactly 47
  schema artifacts), the module imports only
  the standard library and pydantic, exposes no executable surface and
  no wall-clock/randomness calls, contains no phase-number literals,
  and carries no ranking/winner/preference/recommendation field or
  symbol.

The production module's statistical structural bounds use a
deterministic one-adjacent-float-step relation (``math.nextafter``
based, never ``math.isclose``/relative tolerance/absolute epsilon)
solely for composability with the accepted deterministic primitives:
the Type 7 interpolated quantile of ``(99, 25, 99)`` is
``99.00000000000001`` (one step above the maximum), the Type 7
quantiles of ``(99, 99, 99)`` are ``99.00000000000001``, and the
``math.fsum``/``n`` mean of ``(0.1, 0.1, 0.1)`` is
``0.10000000000000002`` (one step above the maximum) - all of which
the contract must accept while still rejecting crossings of two or
more adjacent float steps and while keeping every semantic/identity
invariant exact. The composability tests feed the real primitive
output (including one-sample projections of ``2**53 + 1`` and
``10**100``, a constant-violation CVaR one ULP below the violation
``p95``, and constant-value adverse tails one ULP below the
arithmetic mean) and the relaxed-boundary family tests prove exact /
one-step acceptance and two-step rejection for every relaxed band.
"""

from __future__ import annotations

import ast
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast, get_args

import pytest
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.campaign_outcome_statistics import (
    empirical_lower_tail_mean_95,
    empirical_type7_quantile,
    empirical_upper_tail_mean_95,
)
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    EmpiricalDistributionSummary,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding
from kalhas.contracts.v1.shared import VersionedContract
from pydantic import BaseModel, ValidationError

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "contracts" / "v1" / "campaign_outcome.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

#: The exact six runtime-3 contracts appended at indexes 40-45.
_RUNTIME3_CONTRACTS = (
    "RealizationRunTrajectoryExecution",
    "RealizationRunTrajectoryReplayManifest",
    "RealizationCampaignTrajectoryMatrix",
    "RealizationRunMetricObservationSet",
    "RealizationCampaignMetricObservationMatrix",
    "RealizationCampaignMetricStatisticsMatrix",
)


def _arithmetic_mean(values: tuple[int | float, ...]) -> float:
    return math.fsum(float(value) for value in values) / len(values)


def _median(values: tuple[int | float, ...]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return math.fsum((float(ordered[middle - 1]), float(ordered[middle]))) / 2


def _population_standard_deviation(values: tuple[int | float, ...]) -> float:
    mean = _arithmetic_mean(values)
    squared = [(float(value) - mean) ** 2 for value in values]
    return math.sqrt(math.fsum(squared) / len(values))


def _is_exact_finite(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value."""
    if type(value) is bool or (type(value) is not int and type(value) is not float):
        return False
    if type(value) is float and not math.isfinite(value):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _summary_payload(values: tuple[int | float, ...], **overrides: object) -> dict[str, object]:
    """One internally consistent summary payload for the exact samples.

    The derived values always come from the real deterministic
    computations - ``math.fsum``/``n`` mean and median, the population
    standard deviation formula, and the accepted Hyndman-Fan Type 7
    primitives for the quantiles - including for constant collections,
    so a constant vector such as ``(99, 99, 99)`` carries the actual
    Type 7 output (``99.00000000000001`` for ``p05``/``p95``) and
    ``(0.1, 0.1, 0.1)`` carries the actual ``math.fsum``/``n`` mean
    (``0.10000000000000002``). The one exception is the population
    standard deviation of a constant collection, which is emitted as
    exactly ``0.0`` because the contract requires exactly ``0.0`` for
    repeated collections (the float formula would otherwise report a
    sub-ULP artifact such as ``1.39e-17``). When the samples themselves
    are attack values (non-finite, non-numeric), finite placeholder
    statistics are emitted because the contract rejects the samples
    before the derived fields are ever inspected.
    """
    if not all(_is_exact_finite(value) for value in values):
        payload: dict[str, object] = {
            "ordered_samples": list(values),
            "sample_count": len(values),
            "minimum": 0.0,
            "maximum": 1.0,
            "arithmetic_mean": 0.5,
            "median": 0.5,
            "population_standard_deviation": 0.5,
            "quantile_algorithm": "hyndman-fan-type-7-v1",
            "p05": 0.0,
            "p25": 0.25,
            "p75": 0.75,
            "p95": 1.0,
        }
        payload.update(overrides)
        return payload
    payload = {
        "ordered_samples": list(values),
        "sample_count": len(values),
        "minimum": float(min(values)),
        "maximum": float(max(values)),
        "arithmetic_mean": _arithmetic_mean(values),
        "median": _median(values),
        "population_standard_deviation": _population_standard_deviation(values),
        "quantile_algorithm": "hyndman-fan-type-7-v1",
        "p05": empirical_type7_quantile(values, 5),
        "p25": empirical_type7_quantile(values, 25),
        "p75": empirical_type7_quantile(values, 75),
        "p95": empirical_type7_quantile(values, 95),
    }
    if len(values) == 1 or len(set(values)) == 1:
        payload["population_standard_deviation"] = 0.0
    payload.update(overrides)
    return payload


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


def _default_adverse_tail(
    values: tuple[int | float, ...],
    direction: str,
    target: float | None,
) -> float:
    """The actual direction-aware adverse-tail statistic from the accepted primitives.

    ``minimize`` uses the fixed-alpha upper-tail mean of the observed
    values, ``maximize`` uses the fixed-alpha lower-tail mean, and
    ``reach`` uses the upper-tail mean of the absolute deviations from
    the target (always non-negative). When a ``reach`` payload has no
    target (an attack the contract rejects on its direction rules), a
    non-negative placeholder is emitted.
    """
    if direction == "minimize":
        return empirical_upper_tail_mean_95(values)
    if direction == "maximize":
        return empirical_lower_tail_mean_95(values)
    if target is None:
        return 0.0
    deviations = tuple(abs(value - target) for value in values)
    return empirical_upper_tail_mean_95(deviations)


def _outcome_payload(
    *,
    sequence_position: int = 0,
    strategy_position: int = 0,
    objective_position: int = 0,
    strategy_candidate_id: str = "sc-1",
    objective_id: str = "obj-1",
    metric_id: str = "m-1",
    metric_unit: str | None = "units",
    direction: str = "minimize",
    target: float | None = 100.0,
    reach_tolerance: float | None = None,
    weight: float = 1.0,
    normalization_scale: float = 100.0,
    values: tuple[int | float, ...] = (91, 95, 110, 120),
    adverse_tail_statistic: float | None = None,
    **overrides: object,
) -> dict[str, object]:
    """One internally consistent strategy/objective outcome payload.

    When ``target`` is present the payload carries the exact seed-order
    recomputed normalized violations, achievement count and probability,
    the violation distribution maximum as the worst violation, and the
    actual fixed-alpha upper-tail mean of the normalized violations as
    the target-violation CVaR - the value the accepted pure tail
    primitive produces (the contract's CVaR band is one-adjacent-float
    tolerant so even a constant-violation CVaR one ULP below the
    violation ``p95`` validates).
    """
    payload: dict[str, object] = {
        "sequence_position": sequence_position,
        "strategy_position": strategy_position,
        "objective_position": objective_position,
        "strategy_candidate_id": strategy_candidate_id,
        "objective_id": objective_id,
        "metric_id": metric_id,
        "metric_unit": metric_unit,
        "direction": direction,
        "target": target,
        "reach_tolerance": reach_tolerance,
        "weight": weight,
        "normalization_scale": normalization_scale,
        "ordered_observed_values": list(values),
        "empirical_distribution": _summary_payload(values),
        "target_achievement_count": None,
        "empirical_target_achievement_probability": None,
        "normalized_target_violation_distribution": None,
        "worst_normalized_target_violation": None,
        "tail_alpha": 0.95,
        "tail_algorithm": "empirical-fractional-tail-mean-v1",
        "target_violation_cvar": None,
        "adverse_tail_statistic": 0.0,
    }
    if target is not None:
        try:
            violations = _recomputed_violations(
                values, direction, target, reach_tolerance, normalization_scale
            )
            count = _recomputed_achievement_count(values, direction, target, reach_tolerance)
        except (TypeError, AssertionError, ArithmeticError):
            # Attack payloads (string/bool/non-finite target or scale,
            # missing reach tolerance, zero scale): the targeted fields
            # stay at their None defaults and the contract rejects the
            # payload on the raw-value or direction rules first.
            violations = None
            count = None
        if violations is not None and count is not None:
            payload["target_achievement_count"] = count
            payload["empirical_target_achievement_probability"] = count / len(values)
            payload["normalized_target_violation_distribution"] = _summary_payload(violations)
            payload["worst_normalized_target_violation"] = float(max(violations))
            payload["target_violation_cvar"] = empirical_upper_tail_mean_95(violations)
    if adverse_tail_statistic is None:
        adverse_tail_statistic = _default_adverse_tail(values, direction, target)
    payload["adverse_tail_statistic"] = adverse_tail_statistic
    payload.update(overrides)
    return payload


def _assert_within_one_ulp(actual: float, expected: float) -> None:
    """Prove the result differs from the rational reference by at most one ULP."""
    assert abs(actual - expected) <= math.ulp(expected)


def _matrix_binding(**overrides: object) -> ObjectiveMetricBinding:
    """One valid objective-to-metric binding for matrix outcome construction."""
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


def _matrix_outcome(
    *,
    sequence_position: int,
    strategy_position: int,
    objective_position: int,
    strategy_candidate_id: str,
    binding: ObjectiveMetricBinding,
    ordered_observed_values: tuple[int | float, ...],
) -> StrategyObjectiveOutcome:
    """One outcome built by the accepted pure builder (never duplicated algorithms)."""
    return build_strategy_objective_outcome(
        sequence_position=sequence_position,
        strategy_position=strategy_position,
        objective_position=objective_position,
        strategy_candidate_id=strategy_candidate_id,
        binding=binding,
        ordered_observed_values=ordered_observed_values,
    )


def _matrix_payload(**overrides: object) -> dict[str, object]:
    """One internally consistent 2-strategy x 2-objective matrix payload.

    Outcomes are produced by the accepted pure builder: strategies
    ``sc-a``/``sc-b``, seeds ``seed-0``/``seed-1``, objectives ``obj-1``
    (minimize, metric ``m-1``, target 100, scale 100) and ``obj-2``
    (maximize, metric ``m-2``, target 50, scale 10). The two strategies
    carry different observed evidence, so valid matrices prove that
    evidence values may differ across strategies while the objective/
    binding snapshots stay identical.
    """
    strategy_ids = ("sc-a", "sc-b")
    seed_ids = ("seed-0", "seed-1")
    objective_ids = ("obj-1", "obj-2")
    metric_ids = ("m-1", "m-2")
    bindings = {
        "obj-1": _matrix_binding(
            objective_id="obj-1",
            metric_id="m-1",
            direction="minimize",
            target=100.0,
            normalization_scale=100.0,
        ),
        "obj-2": _matrix_binding(
            objective_id="obj-2",
            metric_id="m-2",
            direction="maximize",
            target=50.0,
            normalization_scale=10.0,
        ),
    }
    values_by_strategy = {"sc-a": (91, 95), "sc-b": (80, 60)}
    outcomes: list[StrategyObjectiveOutcome] = []
    for strategy_position, strategy_id in enumerate(strategy_ids):
        for objective_position, objective_id in enumerate(objective_ids):
            outcomes.append(
                _matrix_outcome(
                    sequence_position=strategy_position * len(objective_ids) + objective_position,
                    strategy_position=strategy_position,
                    objective_position=objective_position,
                    strategy_candidate_id=strategy_id,
                    binding=bindings[objective_id],
                    ordered_observed_values=values_by_strategy[strategy_id],
                )
            )
    payload: dict[str, object] = {
        "identifier": "matrix-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-1",
        "world_content_hash": "b" * 64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "evaluation_profile_id": "profile-1",
        "evaluation_profile_content_hash": "c" * 64,
        "uncertainty_model_id": None,
        "uncertainty_model_content_hash": None,
        "source_world_realization_matrix_id": "realization-matrix-1",
        "source_world_realization_matrix_content_hash": "d" * 64,
        "source_metric_observation_matrix_id": "observation-matrix-1",
        "source_metric_observation_matrix_content_hash": "e" * 64,
        "ordered_strategy_candidate_ids": list(strategy_ids),
        "ordered_scenario_seed_ids": list(seed_ids),
        "ordered_objective_ids": list(objective_ids),
        "ordered_metric_ids": list(metric_ids),
        "outcomes": outcomes,
        "content_hash": "f" * 64,
        "derived_at": "2026-08-15T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _default_matrix_outcomes() -> list[StrategyObjectiveOutcome]:
    """The default four outcomes of :func:`_matrix_payload`, in exact order."""
    payload = _matrix_payload()
    outcomes = payload["outcomes"]
    assert isinstance(outcomes, list)
    return [cast(StrategyObjectiveOutcome, outcome) for outcome in outcomes]


class TestSummaryValidSummaries:
    def test_odd_sample_count_golden(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3, 4, 5)))
        assert summary.sample_count == 5
        assert summary.minimum == 1.0
        assert summary.maximum == 5.0
        assert summary.arithmetic_mean == 3.0
        assert summary.median == 3.0
        # 6/5 and 24/5 are mathematically non-terminating in binary; the
        # mandated fsum interpolation can land one ULP from the correctly
        # rounded rational reference (the accepted statistics tests use
        # the same one-ULP bound for these two quantiles).
        _assert_within_one_ulp(summary.p05, 1.2)
        assert summary.p25 == 2.0
        assert summary.p75 == 4.0
        _assert_within_one_ulp(summary.p95, 4.8)
        assert summary.quantile_algorithm == "hyndman-fan-type-7-v1"
        assert math.isfinite(summary.population_standard_deviation)

    def test_even_sample_count_golden(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((0, 10, 20, 30)))
        assert summary.sample_count == 4
        assert summary.minimum == 0.0
        assert summary.maximum == 30.0
        assert summary.arithmetic_mean == 15.0
        assert summary.median == 15.0
        assert summary.p05 == 1.5
        assert summary.p25 == 7.5
        assert summary.p75 == 22.5
        assert summary.p95 == 28.5

    def test_two_sample_short_tail(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((10, 20)))
        assert summary.median == 15.0
        assert summary.p95 == 19.5
        assert summary.p05 == 10.5

    def test_negative_values(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(
            _summary_payload((-5, -4, -3, -2, -1))
        )
        assert summary.minimum == -5.0
        assert summary.maximum == -1.0
        assert summary.arithmetic_mean == -3.0
        assert summary.median == -3.0
        _assert_within_one_ulp(summary.p05, -4.8)
        assert summary.p25 == -4.0
        assert summary.p75 == -2.0
        _assert_within_one_ulp(summary.p95, -1.2)

    def test_mixed_int_float_values(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2.5, 3, 4.5, 6)))
        assert summary.sample_count == 5
        assert summary.arithmetic_mean == 3.4
        assert summary.p25 == 2.5
        assert summary.p75 == 4.5
        assert summary.ordered_samples == (1, 2.5, 3, 4.5, 6)
        assert type(summary.ordered_samples[0]) is int
        assert type(summary.ordered_samples[1]) is float

    def test_unsorted_input_preserves_exact_seed_order(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((5, 3, 1, 2, 4)))
        assert summary.ordered_samples == (5, 3, 1, 2, 4)
        assert summary.minimum == 1.0
        assert summary.maximum == 5.0

    def test_causal_pair_golden(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((84, 103)))
        assert summary.arithmetic_mean == 93.5
        assert summary.median == 93.5
        assert summary.population_standard_deviation == 9.5

    def test_one_sample_invariant(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((7,)))
        assert summary.sample_count == 1
        assert summary.minimum == 7.0
        assert summary.maximum == 7.0
        assert summary.arithmetic_mean == 7.0
        assert summary.median == 7.0
        assert summary.p05 == 7.0
        assert summary.p25 == 7.0
        assert summary.p75 == 7.0
        assert summary.p95 == 7.0
        assert summary.population_standard_deviation == 0.0

    def test_repeated_value_invariant(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((4, 4, 4, 4)))
        assert summary.sample_count == 4
        assert summary.minimum == 4.0
        assert summary.maximum == 4.0
        assert summary.arithmetic_mean == 4.0
        assert summary.median == 4.0
        assert summary.p05 == 4.0
        assert summary.p25 == 4.0
        assert summary.p75 == 4.0
        assert summary.p95 == 4.0
        assert summary.population_standard_deviation == 0.0

    def test_negative_repeated_values(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((-3, -3, -3)))
        assert summary.minimum == -3.0
        assert summary.p95 == -3.0
        assert summary.population_standard_deviation == 0.0


class TestSummaryFrozenAndStrict:
    def test_frozen_summary_rejects_assignment(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3)))
        with pytest.raises(ValidationError):
            summary.median = 9.0

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), unexpected_field=1)
            )

    def test_json_round_trip(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2.5, 3, 4.5, 6)))
        restored = EmpiricalDistributionSummary.model_validate(
            json.loads(summary.model_dump_json())
        )
        assert restored == summary

    def test_list_input_becomes_immutable_tuple(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3)))
        assert type(summary.ordered_samples) is tuple
        with pytest.raises(AttributeError):
            summary.ordered_samples.append(4)  # type: ignore[attr-defined]

    def test_exact_field_order(self) -> None:
        assert tuple(EmpiricalDistributionSummary.model_fields) == (
            "ordered_samples",
            "sample_count",
            "minimum",
            "maximum",
            "arithmetic_mean",
            "median",
            "population_standard_deviation",
            "quantile_algorithm",
            "p05",
            "p25",
            "p75",
            "p95",
        )

    def test_quantile_algorithm_is_the_exact_literal(self) -> None:
        assert get_args(
            EmpiricalDistributionSummary.model_fields["quantile_algorithm"].annotation
        ) == ("hyndman-fan-type-7-v1",)
        for bad in ("type-7", "hyndman-fan-type-7", "", "HYNDMAN-FAN-TYPE-7-V1"):
            with pytest.raises(ValidationError):
                EmpiricalDistributionSummary.model_validate(
                    _summary_payload((1, 2, 3), quantile_algorithm=bad)
                )

    def test_input_not_mutated(self) -> None:
        samples = [5, 3, 1, 2, 4]
        payload = _summary_payload(tuple(samples))
        payload["ordered_samples"] = samples
        EmpiricalDistributionSummary.model_validate(payload)
        assert samples == [5, 3, 1, 2, 4]


class TestSummaryRawStrictness:
    @pytest.mark.parametrize(
        "samples",
        (
            [True, 1, 2],
            [1, False, 2],
            ["5", 1, 2],
            [1, "2"],
            [None, 1, 2],
            [Decimal("1.5"), 1, 2],
            [1, Decimal("2.5")],
            [[1], 2, 3],
            [(1, 2), 3],
            [{"value": 1}, 2],
            [1.0, float("nan"), 2.0],
            [1.0, float("inf"), 2.0],
            [1.0, float("-inf"), 2.0],
            [10**400, 1, 2],
            [1, 10**400, 2],
            [-(10**400), 1],
            [],
        ),
    )
    def test_invalid_samples_rejected(self, samples: object) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), ordered_samples=samples)
            )

    @pytest.mark.parametrize("count", (True, False, 3.0, "3", None))
    def test_sample_count_must_be_exact_int(self, count: object) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), sample_count=count)
            )

    @pytest.mark.parametrize(
        "field",
        (
            "minimum",
            "maximum",
            "arithmetic_mean",
            "median",
            "population_standard_deviation",
            "p05",
            "p25",
            "p75",
            "p95",
        ),
    )
    @pytest.mark.parametrize(
        "bad",
        (True, "5", float("nan"), float("inf"), float("-inf"), None, [1.0]),
    )
    def test_derived_fields_reject_non_numeric_raw(self, field: str, bad: object) -> None:
        overrides: dict[str, object] = {field: bad}
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3), **overrides))

    def test_derived_fields_accept_exact_int_raw(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(
            _summary_payload((1, 2, 3), minimum=1, maximum=3)
        )
        assert summary.minimum == 1.0
        assert summary.maximum == 3.0


class TestSummaryConsistency:
    def test_sample_count_must_equal_collection_length(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3), sample_count=4))

    def test_minimum_must_equal_exact_observed_minimum(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3), minimum=0.0))

    def test_maximum_must_equal_exact_observed_maximum(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3), maximum=4.0))

    def test_non_finite_derived_values_rejected(self) -> None:
        for field in (
            "arithmetic_mean",
            "median",
            "population_standard_deviation",
            "p05",
            "p95",
        ):
            with pytest.raises(ValidationError):
                EmpiricalDistributionSummary.model_validate(
                    _summary_payload((1, 2, 3), **{field: float("nan")})
                )
            with pytest.raises(ValidationError):
                EmpiricalDistributionSummary.model_validate(
                    _summary_payload((1, 2, 3), **{field: float("inf")})
                )

    def test_negative_standard_deviation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), population_standard_deviation=-0.5)
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("arithmetic_mean", 5.5),
            ("arithmetic_mean", 0.5),
            ("median", 5.5),
            ("median", 0.5),
        ),
    )
    def test_mean_or_median_outside_extrema_rejected(self, field: str, value: float) -> None:
        overrides: dict[str, object] = {field: value}
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3, 4, 5), **overrides)
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("p05", 0.5),
            ("p05", 2.5),
            ("p25", 3.5),
            ("median", 4.5),
            ("p75", 4.9),
            ("p95", 5.5),
        ),
    )
    def test_quantile_ordering_violation_at_every_adjacent_boundary(
        self, field: str, value: float
    ) -> None:
        overrides: dict[str, object] = {field: value}
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3, 4, 5), **overrides)
            )

    def test_one_sample_invariant_enforced(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((7,), median=7.5))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((7,), population_standard_deviation=1.0)
            )

    def test_repeated_value_invariant_enforced(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((4, 4, 4, 4), p75=4.5))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((4, 4, 4, 4), arithmetic_mean=3.5)
            )
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((4, 4, 4, 4), population_standard_deviation=0.5)
            )

    @pytest.mark.parametrize("field", ("arithmetic_mean", "median", "p05", "p25", "p75", "p95"))
    @pytest.mark.parametrize("direction", ("above", "below"))
    def test_one_sample_tamper_by_even_one_ulp_rejected(self, field: str, direction: str) -> None:
        # The one-sample invariant is exact: tampering by a single
        # adjacent float step must still be rejected.
        base = 7.0
        tampered = (
            math.nextafter(base, math.inf)
            if direction == "above"
            else math.nextafter(base, -math.inf)
        )
        overrides: dict[str, object] = {field: tampered}
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((7,), **overrides))

    def test_one_sample_stddev_tamper_by_one_ulp_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((7,), population_standard_deviation=math.nextafter(0.0, math.inf))
            )

    def test_repeated_multi_sample_one_step_accepted_two_steps_rejected(self) -> None:
        one = math.nextafter(4.0, math.inf)
        two = math.nextafter(one, math.inf)
        valid = EmpiricalDistributionSummary.model_validate(_summary_payload((4, 4, 4, 4), p75=one))
        assert abs(valid.p75 - 4.0) <= math.ulp(4.0)
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(_summary_payload((4, 4, 4, 4), p75=two))
        valid = EmpiricalDistributionSummary.model_validate(
            _summary_payload((4, 4, 4, 4), arithmetic_mean=one)
        )
        assert abs(valid.arithmetic_mean - 4.0) <= math.ulp(4.0)
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((4, 4, 4, 4), arithmetic_mean=two)
            )
        # The population standard deviation of a repeated collection is
        # not relaxed: even one adjacent float step away from 0.0 is
        # rejected.
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((4, 4, 4, 4), population_standard_deviation=one)
            )


class TestPrimitiveFedComposability:
    """Primitive-fed summaries/outcomes the exact comparisons used to reject."""

    def test_type7_boundary_overshoot_accepted(self) -> None:
        # (99, 25, 99): the Type 7 p95 is 99.00000000000001, one adjacent
        # float step above the observed maximum 99.0.
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 99)))
        assert summary.p95 == math.nextafter(99.0, math.inf)
        assert abs(summary.p95 - 99.0) <= math.ulp(99.0)
        assert summary.maximum == 99.0

    def test_constant_vector_quantile_noise_accepted(self) -> None:
        # (99, 99, 99): the Type 7 p05/p95 are 99.00000000000001, one step
        # from the projected constant.
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((99, 99, 99)))
        for field in ("arithmetic_mean", "median", "p05", "p25", "p75", "p95"):
            assert abs(getattr(summary, field) - 99.0) <= math.ulp(99.0)
        assert summary.population_standard_deviation == 0.0

    def test_constant_mean_one_ulp_above_maximum_accepted(self) -> None:
        # (0.1, 0.1, 0.1): the fsum/n mean is 0.10000000000000002, one
        # step above the observed maximum 0.1.
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((0.1, 0.1, 0.1)))
        assert summary.arithmetic_mean == math.nextafter(0.1, math.inf)
        assert summary.maximum == 0.1
        assert summary.population_standard_deviation == 0.0

    def test_one_sample_large_integer_projection_accepted(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((2**53 + 1,)))
        assert summary.ordered_samples == (2**53 + 1,)
        assert type(summary.ordered_samples[0]) is int
        expected = float(2**53 + 1)
        for field in (
            "minimum",
            "maximum",
            "arithmetic_mean",
            "median",
            "p05",
            "p25",
            "p75",
            "p95",
        ):
            assert getattr(summary, field) == expected
        assert summary.population_standard_deviation == 0.0

    def test_one_sample_negative_large_integer_projection_accepted(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((-(2**53 + 1),)))
        assert summary.ordered_samples == (-(2**53 + 1),)
        expected = float(-(2**53 + 1))
        for field in ("minimum", "maximum", "arithmetic_mean", "median", "p05", "p95"):
            assert getattr(summary, field) == expected
        assert summary.population_standard_deviation == 0.0

    def test_one_sample_huge_power_of_ten_projection_accepted(self) -> None:
        summary = EmpiricalDistributionSummary.model_validate(_summary_payload((10**100,)))
        assert summary.ordered_samples == (10**100,)
        expected = float(10**100)
        for field in ("minimum", "maximum", "arithmetic_mean", "median", "p05", "p95"):
            assert getattr(summary, field) == expected
        assert summary.population_standard_deviation == 0.0

    def test_targeted_constant_violation_cvar_one_ulp_below_p95(self) -> None:
        # Violations (100.0,)*21: the Type 7 p95 is exactly 100.0 while
        # the actual upper-tail mean is 99.99999999999999 (one adjacent
        # float step below the p95); the CVaR band must accept it.
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="minimize", target=0.0, normalization_scale=1.0, values=(100.0,) * 21
            )
        )
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.p95 == 100.0
        assert outcome.target_violation_cvar == math.nextafter(100.0, -math.inf)
        assert outcome.target_violation_cvar == empirical_upper_tail_mean_95((100.0,) * 21)
        assert outcome.worst_normalized_target_violation == 100.0

    def test_minimize_adverse_tail_one_ulp_below_mean_accepted(self) -> None:
        # (100.0,)*21: the upper-tail mean is 99.99999999999999, one step
        # below the arithmetic mean 100.0 - the band edge.
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(direction="minimize", target=None, values=(100.0,) * 21)
        )
        assert outcome.empirical_distribution.arithmetic_mean == 100.0
        assert outcome.adverse_tail_statistic == math.nextafter(100.0, -math.inf)
        assert outcome.adverse_tail_statistic == empirical_upper_tail_mean_95((100.0,) * 21)

    def test_maximize_adverse_tail_one_ulp_below_minimum_accepted(self) -> None:
        # (100.0,)*21: the lower-tail mean is 99.99999999999999, one step
        # below the minimum 100.0 - the band edge.
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(direction="maximize", target=None, values=(100.0,) * 21)
        )
        assert outcome.empirical_distribution.minimum == 100.0
        assert outcome.adverse_tail_statistic == math.nextafter(100.0, -math.inf)
        assert outcome.adverse_tail_statistic == empirical_lower_tail_mean_95((100.0,) * 21)


class TestRelaxedBoundaryFamilies:
    """Exact / one-step accepted, two-step rejected for every relaxed band."""

    def test_mean_extrema_band(self) -> None:
        # (1, 2, 3): mean 2.0, maximum 3.0, minimum 1.0.
        one_high = math.nextafter(3.0, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        EmpiricalDistributionSummary.model_validate(
            _summary_payload((1, 2, 3), arithmetic_mean=3.0)
        )
        EmpiricalDistributionSummary.model_validate(
            _summary_payload((1, 2, 3), arithmetic_mean=one_high)
        )
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), arithmetic_mean=two_high)
            )
        one_low = math.nextafter(1.0, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        EmpiricalDistributionSummary.model_validate(
            _summary_payload((1, 2, 3), arithmetic_mean=1.0)
        )
        EmpiricalDistributionSummary.model_validate(
            _summary_payload((1, 2, 3), arithmetic_mean=one_low)
        )
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3), arithmetic_mean=two_low)
            )

    def test_median_extrema_band(self) -> None:
        # Upper edge: (99, 25, 99) has p75 == maximum == 99.0, so the
        # median-extrema band and the quantile chain share the boundary.
        one_high = math.nextafter(99.0, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 99), median=99.0))
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 99), median=one_high))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((99, 25, 99), median=two_high)
            )
        # Lower edge: (99, 25, 25) has p25 == minimum == 25.0.
        one_low = math.nextafter(25.0, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 25), median=25.0))
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 25), median=one_low))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((99, 25, 25), median=two_low)
            )

    def test_quantile_chain_band(self) -> None:
        # Upper edge: (99, 25, 99) with the maximum at 99.0.
        one_high = math.nextafter(99.0, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 99), p95=99.0))
        EmpiricalDistributionSummary.model_validate(_summary_payload((99, 25, 99), p95=one_high))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((99, 25, 99), p95=two_high)
            )
        # Lower edge: (1, 2, 3, 4, 5) with the minimum at 1.0.
        one_low = math.nextafter(1.0, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3, 4, 5), p05=1.0))
        EmpiricalDistributionSummary.model_validate(_summary_payload((1, 2, 3, 4, 5), p05=one_low))
        with pytest.raises(ValidationError):
            EmpiricalDistributionSummary.model_validate(
                _summary_payload((1, 2, 3, 4, 5), p05=two_low)
            )

    def test_cvar_band(self) -> None:
        # Targeted minimize (91, 95, 110, 120): violation p95 = 0.185,
        # worst = 0.2, default CVaR = 0.2.
        p95 = empirical_type7_quantile((0.0, 0.0, 0.1, 0.2), 95)
        one_low = math.nextafter(p95, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=p95))
        StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=one_low))
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=two_low))
        one_high = math.nextafter(0.2, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=0.2))
        StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=one_high))
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(target_violation_cvar=two_high)
            )

    def test_minimize_adverse_tail_band(self) -> None:
        # (91, 95, 110, 120) minimize: mean 104.0, maximum 120.0.
        one_high = math.nextafter(120.0, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=120.0))
        StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=one_high))
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(adverse_tail_statistic=two_high)
            )
        one_low = math.nextafter(104.0, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=104.0))
        StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=one_low))
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(adverse_tail_statistic=two_low)
            )

    def test_maximize_adverse_tail_band(self) -> None:
        # (80, 90, 95, 110) maximize: minimum 80.0, mean 93.75.
        one_low = math.nextafter(80.0, -math.inf)
        two_low = math.nextafter(one_low, -math.inf)
        StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=80.0
            )
        )
        StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=one_low
            )
        )
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=two_low
                )
            )
        one_high = math.nextafter(93.75, math.inf)
        two_high = math.nextafter(one_high, math.inf)
        StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=93.75
            )
        )
        StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=one_high
            )
        )
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=two_high
                )
            )


class TestOutcomeValidShapes:
    def test_valid_targeted_minimize(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload())
        assert outcome.sequence_position == 0
        assert outcome.strategy_candidate_id == "sc-1"
        assert outcome.objective_id == "obj-1"
        assert outcome.metric_id == "m-1"
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 0.5
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.0, 0.1, 0.2)
        assert outcome.worst_normalized_target_violation == 0.2
        cvar = outcome.target_violation_cvar
        assert cvar is not None
        assert distribution.p95 <= cvar <= outcome.worst_normalized_target_violation
        assert (
            outcome.empirical_distribution.arithmetic_mean
            <= outcome.adverse_tail_statistic
            <= outcome.empirical_distribution.maximum
        )

    def test_valid_targeted_maximize(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(direction="maximize", values=(80, 90, 95, 110))
        )
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 0.25
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.2, 0.1, 0.05, 0.0)
        assert outcome.worst_normalized_target_violation == 0.2
        assert (
            outcome.empirical_distribution.minimum
            <= outcome.adverse_tail_statistic
            <= outcome.empirical_distribution.arithmetic_mean
        )

    def test_valid_targeted_reach(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="reach",
                target=100.0,
                reach_tolerance=5.0,
                values=(95, 98, 105, 110),
            )
        )
        assert outcome.target_achievement_count == 3
        assert outcome.empirical_target_achievement_probability == 0.75
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.0, 0.0, 0.05)
        assert outcome.worst_normalized_target_violation == 0.05
        assert outcome.adverse_tail_statistic >= 0.0

    def test_valid_optimization_only_minimize(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(target=None, values=(91, 95, 110, 120))
        )
        assert outcome.target is None
        assert outcome.target_achievement_count is None
        assert outcome.empirical_target_achievement_probability is None
        assert outcome.normalized_target_violation_distribution is None
        assert outcome.worst_normalized_target_violation is None
        assert outcome.target_violation_cvar is None
        assert outcome.adverse_tail_statistic == 120.0
        assert math.isfinite(outcome.adverse_tail_statistic)

    def test_valid_optimization_only_maximize(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(direction="maximize", target=None, values=(80, 90, 95, 110))
        )
        assert outcome.target_achievement_count is None
        assert outcome.empirical_target_achievement_probability is None
        assert outcome.normalized_target_violation_distribution is None
        assert outcome.worst_normalized_target_violation is None
        assert outcome.target_violation_cvar is None
        assert outcome.adverse_tail_statistic == 80.0

    def test_exact_target_boundary(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload(values=(100, 101)))
        assert outcome.target_achievement_count == 1
        assert outcome.empirical_target_achievement_probability == 0.5
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.01)

    def test_exact_reach_tolerance_boundary(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(
                direction="reach",
                target=100.0,
                reach_tolerance=2.0,
                values=(98, 102),
            )
        )
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 1.0
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.0)
        assert outcome.worst_normalized_target_violation == 0.0
        assert outcome.target_violation_cvar == 0.0

    def test_all_values_achieve_the_target(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload(values=(100, 100)))
        assert outcome.target_achievement_count == 2
        assert outcome.empirical_target_achievement_probability == 1.0
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.0)

    def test_no_value_achieves_the_target(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload(values=(110, 120)))
        assert outcome.target_achievement_count == 0
        assert outcome.empirical_target_achievement_probability == 0.0
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.1, 0.2)

    def test_mixed_int_float_observed_values(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(target=5.0, normalization_scale=10.0, values=(1, 2.5, 3, 4.5, 6))
        )
        assert outcome.target_achievement_count == 4
        assert outcome.empirical_target_achievement_probability == 0.8
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.0, 0.0, 0.0, 0.0, 0.1)
        assert outcome.ordered_observed_values == (1, 2.5, 3, 4.5, 6)

    def test_exact_seed_order_preserved(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(values=(110, 91, 120, 95))
        )
        assert outcome.ordered_observed_values == (110, 91, 120, 95)
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == (0.1, 0.0, 0.2, 0.0)
        assert outcome.empirical_distribution.ordered_samples == (110, 91, 120, 95)
        assert outcome.target_achievement_count == 2

    def test_empirical_distribution_matches_observed_values(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload())
        assert outcome.empirical_distribution.ordered_samples == outcome.ordered_observed_values
        assert outcome.empirical_distribution.sample_count == len(outcome.ordered_observed_values)


class TestOutcomeTargetedRules:
    def test_target_achievement_count_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(target_achievement_count=1))

    def test_mutually_consistent_but_wrong_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    target_achievement_count=3, empirical_target_achievement_probability=0.75
                )
            )

    def test_achievement_probability_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(empirical_target_achievement_probability=0.75)
            )

    def test_count_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    target_achievement_count=5, empirical_target_achievement_probability=1.25
                )
            )

    @pytest.mark.parametrize(
        "overrides",
        (
            {"target_achievement_count": None},
            {"empirical_target_achievement_probability": None},
            {"normalized_target_violation_distribution": None},
            {"worst_normalized_target_violation": None},
            {"target_violation_cvar": None},
        ),
    )
    def test_missing_targeted_fields_rejected(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(**cast(Any, overrides)))

    def test_tampered_violation_samples_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    normalized_target_violation_distribution=_summary_payload((0.1, 0.1, 0.2, 0.3))
                )
            )

    def test_wrong_worst_violation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(worst_normalized_target_violation=0.5)
            )

    def test_negative_violation_sample_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    normalized_target_violation_distribution=_summary_payload((-0.1, 0.0, 0.1, 0.2))
                )
            )

    def test_non_finite_violation_sample_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    normalized_target_violation_distribution=_summary_payload(
                        (0.0, float("nan"), 0.1, 0.2)
                    )
                )
            )

    def test_cvar_below_violation_p95_rejected(self) -> None:
        p95 = empirical_type7_quantile((0.0, 0.0, 0.1, 0.2), 95)
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(target_violation_cvar=p95 - 0.01)
            )

    def test_cvar_above_worst_violation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=0.21))

    def test_negative_cvar_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(target_violation_cvar=-0.1))

    def test_observed_values_must_equal_empirical_summary_samples(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(empirical_distribution=_summary_payload((1, 2)))
            )

    def test_observed_values_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(ordered_observed_values=[90, 100, 110, 120])
            )


class TestOutcomeObjectiveRules:
    def test_reach_requires_target(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(direction="reach", target=None, reach_tolerance=5.0)
            )

    def test_reach_requires_tolerance(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(direction="reach", target=100.0, reach_tolerance=None)
            )

    def test_reach_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="reach", target=100.0, reach_tolerance=-1.0, values=(95, 98, 105, 110)
                )
            )

    def test_reach_non_finite_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(direction="reach", target=100.0, reach_tolerance=float("nan"))
            )

    @pytest.mark.parametrize("direction", ("minimize", "maximize"))
    def test_tolerance_forbidden_for_minimize_and_maximize(self, direction: str) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(direction=direction, reach_tolerance=1.0)
            )

    def test_optimization_only_reach_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(direction="reach", target=None, values=(91, 95, 110, 120))
            )

    @pytest.mark.parametrize(
        "overrides",
        (
            {"target_achievement_count": 2},
            {"empirical_target_achievement_probability": 0.5},
            {"normalized_target_violation_distribution": _summary_payload((0.1, 0.2))},
            {"worst_normalized_target_violation": 0.2},
            {"target_violation_cvar": 0.15},
        ),
    )
    def test_targeted_fields_forbidden_for_optimization_only(
        self, overrides: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(target=None, **cast(Any, overrides))
            )

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(weight=-1.0))

    @pytest.mark.parametrize("weight", (float("nan"), float("inf")))
    def test_non_finite_weight_rejected(self, weight: float) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(weight=weight))

    @pytest.mark.parametrize("scale", (0.0, -100.0, float("inf")))
    def test_invalid_normalization_scale_rejected(self, scale: float) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(normalization_scale=scale))

    def test_minimize_adverse_tail_below_mean_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=103.0))

    def test_minimize_adverse_tail_above_maximum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(adverse_tail_statistic=121.0))

    def test_maximize_adverse_tail_above_mean_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=94.0
                )
            )

    def test_maximize_adverse_tail_below_minimum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="maximize", values=(80, 90, 95, 110), adverse_tail_statistic=79.0
                )
            )

    def test_reach_negative_adverse_tail_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(
                    direction="reach",
                    target=100.0,
                    reach_tolerance=5.0,
                    values=(95, 98, 105, 110),
                    adverse_tail_statistic=-0.5,
                )
            )

    def test_wrong_tail_alpha_rejected(self) -> None:
        assert get_args(StrategyObjectiveOutcome.model_fields["tail_alpha"].annotation) == (0.95,)
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(tail_alpha=0.9))

    def test_wrong_tail_algorithm_rejected(self) -> None:
        assert get_args(StrategyObjectiveOutcome.model_fields["tail_algorithm"].annotation) == (
            "empirical-fractional-tail-mean-v1",
        )
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(tail_algorithm="other"))


class TestOutcomeRawStrictness:
    @pytest.mark.parametrize(
        "overrides",
        (
            {"sequence_position": True},
            {"strategy_position": True},
            {"objective_position": True},
            {"strategy_position": 1.5},
            {"objective_position": "0"},
            {"sequence_position": -1},
        ),
    )
    def test_positions_must_be_exact_non_negative_ints(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(**cast(Any, overrides)))

    @pytest.mark.parametrize(
        "overrides",
        (
            {"target_achievement_count": True},
            {"target_achievement_count": 2.0},
            {"target_achievement_count": "2"},
        ),
    )
    def test_achievement_count_must_be_exact_int(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(**cast(Any, overrides)))

    @pytest.mark.parametrize(
        "overrides",
        (
            {"weight": True},
            {"weight": "1"},
            {"target": True},
            {"target": "100"},
            {"target": float("nan")},
            {"normalization_scale": True},
            {"normalization_scale": "100"},
            {"empirical_target_achievement_probability": False},
            {"empirical_target_achievement_probability": float("nan")},
            {"worst_normalized_target_violation": False},
            {"target_violation_cvar": "0.5"},
            {"target_violation_cvar": float("inf")},
            {"adverse_tail_statistic": True},
            {"adverse_tail_statistic": float("inf")},
            {"tail_alpha": True},
        ),
    )
    def test_scalar_numeric_attacks_rejected(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(**cast(Any, overrides)))

    @pytest.mark.parametrize(
        "values",
        (
            [True, 91, 95, 110],
            ["91", 95, 110, 120],
            [91.0, float("nan"), 95.0, 110.0],
            [91.0, float("inf"), 95.0, 110.0],
            [10**400, 91, 95, 110],
            [None, 91, 95, 110],
        ),
    )
    def test_invalid_observed_values_rejected(self, values: object) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(
                _outcome_payload(ordered_observed_values=values)
            )

    def test_empty_observed_values_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(ordered_observed_values=[]))


class TestOutcomeFrozenAndStrict:
    def test_frozen_outcome_rejects_assignment(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(_outcome_payload())
        with pytest.raises(ValidationError):
            outcome.target = 50.0

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StrategyObjectiveOutcome.model_validate(_outcome_payload(unexpected_field=1))

    def test_json_round_trip(self) -> None:
        outcome = StrategyObjectiveOutcome.model_validate(
            _outcome_payload(direction="reach", target=100.0, reach_tolerance=5.0)
        )
        restored = StrategyObjectiveOutcome.model_validate(json.loads(outcome.model_dump_json()))
        assert restored == outcome

    def test_exact_field_order(self) -> None:
        assert tuple(StrategyObjectiveOutcome.model_fields) == (
            "sequence_position",
            "strategy_position",
            "objective_position",
            "strategy_candidate_id",
            "objective_id",
            "metric_id",
            "metric_unit",
            "direction",
            "target",
            "reach_tolerance",
            "weight",
            "normalization_scale",
            "ordered_observed_values",
            "empirical_distribution",
            "target_achievement_count",
            "empirical_target_achievement_probability",
            "normalized_target_violation_distribution",
            "worst_normalized_target_violation",
            "tail_alpha",
            "tail_algorithm",
            "target_violation_cvar",
            "adverse_tail_statistic",
        )

    def test_input_not_mutated(self) -> None:
        observed = [91, 95, 110, 120]
        payload = _outcome_payload()
        payload["ordered_observed_values"] = observed
        outcome = StrategyObjectiveOutcome.model_validate(payload)
        assert observed == [91, 95, 110, 120]
        assert outcome.ordered_observed_values == (91, 95, 110, 120)


class TestMatrixFieldOrder:
    def test_exact_field_order_after_inherited_fields(self) -> None:
        assert tuple(CampaignOutcomeDistributionMatrix.model_fields) == (
            "identifier",
            "tenant_id",
            "schema_version",
            "campaign_id",
            "scenario_id",
            "scenario_content_hash",
            "world_version_id",
            "world_content_hash",
            "runtime_version",
            "comparison_mode",
            "evaluation_profile_id",
            "evaluation_profile_content_hash",
            "uncertainty_model_id",
            "uncertainty_model_content_hash",
            "source_world_realization_matrix_id",
            "source_world_realization_matrix_content_hash",
            "source_metric_observation_matrix_id",
            "source_metric_observation_matrix_content_hash",
            "ordered_strategy_candidate_ids",
            "ordered_scenario_seed_ids",
            "ordered_objective_ids",
            "ordered_metric_ids",
            "outcomes",
            "content_hash",
            "derived_at",
        )


class TestMatrixValidConstruction:
    def test_multi_strategy_multi_objective_valid(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        assert matrix.identifier == "matrix-1"
        assert matrix.tenant_id == "tenant-1"
        assert matrix.campaign_id == "campaign-1"
        assert matrix.scenario_id == "scenario-1"
        assert matrix.scenario_content_hash == "a" * 64
        assert matrix.world_version_id == "world-1"
        assert matrix.world_content_hash == "b" * 64
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.evaluation_profile_id == "profile-1"
        assert matrix.evaluation_profile_content_hash == "c" * 64
        assert matrix.uncertainty_model_id is None
        assert matrix.uncertainty_model_content_hash is None
        assert matrix.source_world_realization_matrix_id == "realization-matrix-1"
        assert matrix.source_world_realization_matrix_content_hash == "d" * 64
        assert matrix.source_metric_observation_matrix_id == "observation-matrix-1"
        assert matrix.source_metric_observation_matrix_content_hash == "e" * 64
        assert matrix.ordered_strategy_candidate_ids == ("sc-a", "sc-b")
        assert matrix.ordered_scenario_seed_ids == ("seed-0", "seed-1")
        assert matrix.ordered_objective_ids == ("obj-1", "obj-2")
        assert matrix.ordered_metric_ids == ("m-1", "m-2")
        assert len(matrix.outcomes) == 4
        assert matrix.content_hash == "f" * 64
        assert matrix.schema_version == "1.0.0"

    def test_uncertainty_provenance_both_present_valid(self) -> None:
        payload = _matrix_payload(
            uncertainty_model_id="um-1",
            uncertainty_model_content_hash="ab" * 32,
        )
        matrix = CampaignOutcomeDistributionMatrix.model_validate(payload)
        assert matrix.uncertainty_model_id == "um-1"
        assert matrix.uncertainty_model_content_hash == "ab" * 32

    def test_identifier_and_content_hash_are_not_recomputed(self) -> None:
        # The contract validates structural shape only; no deterministic
        # identifier derivation or content-hash recomputation happens.
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        assert matrix.identifier == "matrix-1"
        assert matrix.content_hash == "f" * 64

    def test_list_input_converted_to_immutable_tuples(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        assert type(matrix.ordered_strategy_candidate_ids) is tuple
        assert type(matrix.ordered_scenario_seed_ids) is tuple
        assert type(matrix.ordered_objective_ids) is tuple
        assert type(matrix.ordered_metric_ids) is tuple
        assert type(matrix.outcomes) is tuple
        assert matrix.ordered_strategy_candidate_ids == ("sc-a", "sc-b")
        assert matrix.outcomes[0].strategy_candidate_id == "sc-a"
        assert matrix.outcomes[2].strategy_candidate_id == "sc-b"

    def test_frozen_matrix_rejects_assignment(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        with pytest.raises(ValidationError):
            matrix.content_hash = "0" * 64

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(unexpected_field=1))

    def test_json_round_trip(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        restored = CampaignOutcomeDistributionMatrix.model_validate(
            json.loads(matrix.model_dump_json())
        )
        assert restored == matrix

    def test_empty_ordered_collections_rejected(self) -> None:
        for field in (
            "ordered_strategy_candidate_ids",
            "ordered_scenario_seed_ids",
            "ordered_objective_ids",
            "ordered_metric_ids",
            "outcomes",
        ):
            with pytest.raises(ValidationError):
                CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(**{field: []}))


class TestMatrixStrictInputs:
    def test_timezone_aware_derived_at_required(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(derived_at="2026-08-15T12:00:00")
            )
        bad_values: tuple[object, ...] = ("not-a-date", None, [], {}, True)
        for bad_value in bad_values:
            with pytest.raises(ValidationError):
                CampaignOutcomeDistributionMatrix.model_validate(
                    _matrix_payload(derived_at=bad_value)
                )

    @pytest.mark.parametrize(
        "field",
        (
            "scenario_content_hash",
            "world_content_hash",
            "evaluation_profile_content_hash",
            "source_world_realization_matrix_content_hash",
            "source_metric_observation_matrix_content_hash",
            "content_hash",
        ),
    )
    def test_sha256_pattern_rejected(self, field: str) -> None:
        for bad_value in ("xyz", "A" * 64, "a" * 63, "a" * 65, ""):
            with pytest.raises(ValidationError):
                CampaignOutcomeDistributionMatrix.model_validate(
                    _matrix_payload(**{field: bad_value})
                )

    @pytest.mark.parametrize(
        "runtime",
        ("2.0.0", "3.1.0", "3.0", "3.0.0.0", None, 3),
    )
    def test_runtime_version_literal_rejected(self, runtime: object) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(runtime_version=runtime)
            )

    @pytest.mark.parametrize(
        "mode",
        ("shared_conditions", "identical", "identical_condition", None, 1),
    )
    def test_comparison_mode_literal_rejected(self, mode: object) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(comparison_mode=mode))


class TestMatrixUncertaintyProvenance:
    def test_both_absent_valid(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        assert matrix.uncertainty_model_id is None
        assert matrix.uncertainty_model_content_hash is None

    def test_id_without_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(uncertainty_model_id="um-1")
            )

    def test_hash_without_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(uncertainty_model_content_hash="ab" * 32)
            )


class TestMatrixIdentifierUniqueness:
    def test_duplicate_strategy_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(
                    ordered_strategy_candidate_ids=["sc-a", "sc-a"],
                )
            )

    def test_duplicate_seed_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(ordered_scenario_seed_ids=["seed-0", "seed-0"])
            )

    def test_duplicate_objective_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(ordered_objective_ids=["obj-1", "obj-1"])
            )

    def test_duplicate_metric_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(ordered_metric_ids=["m-1", "m-1"])
            )


class TestMatrixMetricOrdering:
    def test_non_increasing_metric_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(ordered_metric_ids=["m-2", "m-1"])
            )

    def test_strictly_increasing_metric_ids_accepted(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(
            _matrix_payload(ordered_metric_ids=["m-1", "m-2"])
        )
        assert matrix.ordered_metric_ids == ("m-1", "m-2")


class TestMatrixOutcomeCartesianShape:
    def test_missing_outcome_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=outcomes[:3]))

    def test_additional_outcome_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        extra = _matrix_outcome(
            sequence_position=4,
            strategy_position=0,
            objective_position=0,
            strategy_candidate_id="sc-a",
            binding=_matrix_binding(),
            ordered_observed_values=(91, 95),
        )
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(outcomes=[*outcomes, extra])
            )

    def test_duplicate_strategy_objective_pair_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        duplicated = _matrix_outcome(
            sequence_position=1,
            strategy_position=0,
            objective_position=0,
            strategy_candidate_id="sc-a",
            binding=_matrix_binding(),
            ordered_observed_values=(91, 95),
        )
        replaced = [outcomes[0], duplicated, outcomes[2], outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_reordered_outcomes_rejected(self) -> None:
        # Pair order (1,0), (0,0), (0,1), (1,1) with contiguous sequence
        # positions: the first outcome's expected index is 2, not 0.
        reordered = [
            _matrix_outcome(
                sequence_position=0,
                strategy_position=1,
                objective_position=0,
                strategy_candidate_id="sc-b",
                binding=_matrix_binding(objective_id="obj-1", metric_id="m-1", target=100.0),
                ordered_observed_values=(80, 60),
            ),
            _matrix_outcome(
                sequence_position=1,
                strategy_position=0,
                objective_position=0,
                strategy_candidate_id="sc-a",
                binding=_matrix_binding(),
                ordered_observed_values=(91, 95),
            ),
            _matrix_outcome(
                sequence_position=2,
                strategy_position=0,
                objective_position=1,
                strategy_candidate_id="sc-a",
                binding=_matrix_binding(
                    objective_id="obj-2",
                    metric_id="m-2",
                    direction="maximize",
                    target=50.0,
                    normalization_scale=10.0,
                ),
                ordered_observed_values=(91, 95),
            ),
            _matrix_outcome(
                sequence_position=3,
                strategy_position=1,
                objective_position=1,
                strategy_candidate_id="sc-b",
                binding=_matrix_binding(
                    objective_id="obj-2",
                    metric_id="m-2",
                    direction="maximize",
                    target=50.0,
                    normalization_scale=10.0,
                ),
                ordered_observed_values=(80, 60),
            ),
        ]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=reordered))

    def test_non_contiguous_sequence_position_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        broken = [outcome.model_copy(update={"sequence_position": 2}) for outcome in outcomes]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=broken))

    def test_out_of_range_strategy_position_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        out_of_range = _matrix_outcome(
            sequence_position=2,
            strategy_position=2,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], out_of_range, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_out_of_range_objective_position_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        out_of_range = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=2,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], out_of_range, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_strategy_identity_mismatch_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        mismatched = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-x",
            binding=_matrix_binding(),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], mismatched, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_objective_identity_mismatch_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        mismatched = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(objective_id="obj-x"),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], mismatched, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_outcome_metric_absent_from_ordered_metric_ids_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        missing_metric = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(metric_id="m-9"),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], missing_metric, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_outcome_observed_value_count_mismatch_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        wrong_count = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(),
            ordered_observed_values=(80, 60, 40),
        )
        replaced = [outcomes[0], outcomes[1], wrong_count, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_empirical_summary_sample_count_mismatch_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        outcome = outcomes[2]
        tampered_summary = EmpiricalDistributionSummary.model_construct(
            ordered_samples=outcome.empirical_distribution.ordered_samples,
            sample_count=99,
            minimum=outcome.empirical_distribution.minimum,
            maximum=outcome.empirical_distribution.maximum,
            arithmetic_mean=outcome.empirical_distribution.arithmetic_mean,
            median=outcome.empirical_distribution.median,
            population_standard_deviation=outcome.empirical_distribution.population_standard_deviation,
            quantile_algorithm="hyndman-fan-type-7-v1",
            p05=outcome.empirical_distribution.p05,
            p25=outcome.empirical_distribution.p25,
            p75=outcome.empirical_distribution.p75,
            p95=outcome.empirical_distribution.p95,
        )
        data = outcome.model_dump(mode="python")
        data["empirical_distribution"] = tampered_summary
        tampered_outcome = StrategyObjectiveOutcome.model_construct(**data)
        replaced = [outcomes[0], outcomes[1], tampered_outcome, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))


class TestMatrixSnapshotConsistency:
    @pytest.mark.parametrize(
        "drift",
        (
            pytest.param(
                {"metric_id": "m-2"},
                id="metric-id",
            ),
            pytest.param({"metric_unit": "kg"}, id="metric-unit"),
            pytest.param({"direction": "maximize"}, id="direction"),
            pytest.param({"target": 90.0}, id="target"),
            pytest.param({"weight": 2.0}, id="weight"),
            pytest.param({"normalization_scale": 50.0}, id="normalization-scale"),
        ),
    )
    def test_snapshot_drift_across_strategies_rejected(self, drift: dict[str, object]) -> None:
        outcomes = _default_matrix_outcomes()
        drifted = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(**drift),
            ordered_observed_values=(80, 60),
        )
        replaced = [outcomes[0], outcomes[1], drifted, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_reach_tolerance_drift_across_strategies_rejected(self) -> None:
        outcomes = _default_matrix_outcomes()
        reference = _matrix_outcome(
            sequence_position=0,
            strategy_position=0,
            objective_position=0,
            strategy_candidate_id="sc-a",
            binding=_matrix_binding(
                objective_id="obj-1",
                metric_id="m-1",
                direction="reach",
                target=100.0,
                reach_tolerance=5.0,
            ),
            ordered_observed_values=(96, 104),
        )
        drifted = _matrix_outcome(
            sequence_position=2,
            strategy_position=1,
            objective_position=0,
            strategy_candidate_id="sc-b",
            binding=_matrix_binding(
                objective_id="obj-1",
                metric_id="m-1",
                direction="reach",
                target=100.0,
                reach_tolerance=3.0,
            ),
            ordered_observed_values=(96, 104),
        )
        replaced = [reference, outcomes[1], drifted, outcomes[3]]
        with pytest.raises(ValidationError):
            CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(outcomes=replaced))

    def test_evidence_values_may_differ_across_strategies(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        first = matrix.outcomes[0]
        second = matrix.outcomes[2]
        assert first.strategy_candidate_id == "sc-a"
        assert second.strategy_candidate_id == "sc-b"
        assert first.ordered_observed_values == (91, 95)
        assert second.ordered_observed_values == (80, 60)
        assert first.empirical_distribution.arithmetic_mean != (
            second.empirical_distribution.arithmetic_mean
        )
        assert first.target_achievement_count == 2
        assert second.target_achievement_count == 2
        # Identical snapshots for the same objective position:
        assert first.objective_id == second.objective_id == "obj-1"
        assert first.metric_id == second.metric_id == "m-1"
        assert first.metric_unit == second.metric_unit == "units"
        assert first.direction == second.direction == "minimize"
        assert first.target == second.target == 100.0
        assert first.reach_tolerance == second.reach_tolerance is None
        assert first.weight == second.weight == 1.0
        assert first.normalization_scale == second.normalization_scale == 100.0


class TestMatrixOrderAndImmutability:
    def test_exact_strategy_major_objective_minor_order(self) -> None:
        matrix = CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload())
        assert [(o.strategy_position, o.objective_position) for o in matrix.outcomes] == [
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
        ]
        assert [o.sequence_position for o in matrix.outcomes] == [0, 1, 2, 3]
        assert [o.strategy_candidate_id for o in matrix.outcomes] == [
            "sc-a",
            "sc-a",
            "sc-b",
            "sc-b",
        ]
        assert [o.objective_id for o in matrix.outcomes] == [
            "obj-1",
            "obj-2",
            "obj-1",
            "obj-2",
        ]

    def test_inputs_never_mutated(self) -> None:
        payload = _matrix_payload()
        outcomes = payload["outcomes"]
        assert isinstance(outcomes, list)
        values = list(outcomes[0].ordered_observed_values)
        strategy_ids = payload["ordered_strategy_candidate_ids"]
        assert isinstance(strategy_ids, list)
        before_outcomes = [outcome.model_dump(mode="python") for outcome in outcomes]
        matrix = CampaignOutcomeDistributionMatrix.model_validate(payload)
        assert matrix is not None
        assert payload["ordered_strategy_candidate_ids"] == strategy_ids
        assert [outcome.model_dump(mode="python") for outcome in outcomes] == before_outcomes
        assert list(outcomes[0].ordered_observed_values) == values
        assert matrix.outcomes[0].ordered_observed_values == tuple(values)


class TestArchitectureCompatibility:
    def test_exact_public_all(self) -> None:
        import kalhas.contracts.v1.campaign_outcome as module

        assert module.__all__ == [
            "EmpiricalDistributionSummary",
            "StrategyObjectiveOutcome",
            "CampaignOutcomeDistributionMatrix",
        ]
        for name in module.__all__:
            assert hasattr(module, name)

    def test_models_are_plain_base_models_not_versioned_contracts(self) -> None:
        assert issubclass(EmpiricalDistributionSummary, BaseModel)
        assert issubclass(StrategyObjectiveOutcome, BaseModel)
        assert not issubclass(EmpiricalDistributionSummary, VersionedContract)
        assert not issubclass(StrategyObjectiveOutcome, VersionedContract)
        assert issubclass(CampaignOutcomeDistributionMatrix, VersionedContract)
        assert issubclass(CampaignOutcomeDistributionMatrix, BaseModel)

    def test_models_are_not_registered_and_contracts_stay_47(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) == 47
        assert names[40:46] == _RUNTIME3_CONTRACTS
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names
        assert "CampaignOutcomeDistributionMatrix" in names

    def test_schema_artifacts_stay_47_with_only_matrix_registered(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 47
        titles = {json.loads(path.read_text(encoding="utf-8"))["title"] for path in schema_files}
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert titles == names
        file_names = {path.name for path in schema_files}
        assert "EmpiricalDistributionSummary.schema.json" not in file_names
        assert "StrategyObjectiveOutcome.schema.json" not in file_names
        assert "CampaignOutcomeDistributionMatrix.schema.json" in file_names

    def test_module_imports_only_stdlib_pydantic_and_the_shared_contract_module(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(tree)
        kalhas_paths = {path for path in module_paths if path.startswith("kalhas")}
        assert kalhas_paths == {"kalhas.contracts.v1.shared"}, sorted(kalhas_paths)
        modules = _imported_modules(tree)
        assert modules == {"__future__", "typing", "pydantic", "math", "kalhas"}
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
        symbols = _imported_symbols(tree)
        assert not any(symbol in symbols for symbol in ("Callable", "callback"))

    def test_no_wall_clock_or_randomness_calls(self) -> None:
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

    def test_no_phase_number_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        import kalhas.contracts.v1.campaign_outcome as module

        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        symbols = [name for name in module.__all__ if hasattr(module, name)]
        symbols.extend(module.EmpiricalDistributionSummary.model_fields)
        symbols.extend(module.StrategyObjectiveOutcome.model_fields)
        symbols.extend(module.CampaignOutcomeDistributionMatrix.model_fields)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"


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
