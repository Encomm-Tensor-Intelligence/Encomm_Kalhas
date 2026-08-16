"""Pure deterministic strategy/objective campaign-outcome builder (KALHAS).

Builds the immutable ``StrategyObjectiveOutcome`` evidence artifact of
one strategy/objective pair from **already verified authoritative
records only**: a strictly revalidated ``ObjectiveMetricBinding`` and
the exact ordered observed values in authoritative shared-seed order.
The module is domain-neutral and pure: it imports only the Python
standard library, pydantic, the accepted pure statistical primitives,
and the accepted campaign-outcome/objective-evaluation contracts; it
reads no wall clock, uses no randomness, network, providers,
filesystem, store, API, query service, adapters, or domain packs,
never mutates any input, and never constructs a campaign matrix,
identifier, content hash, timestamp, persistence, or registration of
any kind. Nothing here ranks, scores, compares strategies, declares a
winner or preference, recommends, forecasts, or produces a decision
brief: the returned artifact is empirical evidence only.

The one public builder :func:`build_strategy_objective_outcome`:

- requires a real ``ObjectiveMetricBinding`` instance and **strictly
  revalidates its serialized Python payload** through
  ``ObjectiveMetricBinding.model_validate(..., strict=True)`` before
  any field is trusted - a validator-bypassed or wrong-object binding
  is rejected and the supplied binding is never repaired, normalized,
  replaced, or mutated;
- requires ``ordered_observed_values`` to be a non-empty exact plain
  ``tuple`` (tuple subclasses are rejected) of exact ``int``/``float``
  samples - booleans, strings, ``Decimal``, ``None``, containers, NaN,
  and Infinity are rejected, every sample's exact type and seed order
  are preserved, and an integer that cannot be represented as a finite
  float is rejected;
- enforces the exact-int/no-bool policy on the three positions and a
  non-empty ``strategy_candidate_id``;
- reuses (never redefines) the accepted deterministic primitives and
  algorithm constants: ``statistics_minimum``, ``statistics_maximum``,
  ``statistics_arithmetic_mean``, ``statistics_median``,
  ``statistics_population_standard_deviation``,
  ``empirical_type7_quantile``, ``empirical_upper_tail_mean_95``,
  ``empirical_lower_tail_mean_95``, ``EMPIRICAL_QUANTILE_ALGORITHM``,
  ``EMPIRICAL_TAIL_ALGORITHM``, and ``EMPIRICAL_TAIL_ALPHA``;
- builds the exact ``EmpiricalDistributionSummary`` of the observed
  values; a single sample or a numerically identical repeated
  collection (equal finite-float projections) emits a population
  standard deviation of exactly ``0.0``, while non-constant
  collections use the frozen Phase 22 primitive unchanged;
- when the binding carries a target, derives the target achievement
  count and the normalized target violations in **exact original seed
  order** with the exact Phase 23 semantics:

  - ``minimize``: ``max(0, value - target) / normalization_scale``
  - ``maximize``: ``max(0, target - value) / normalization_scale``
  - ``reach``: ``max(0, abs(value - target) - reach_tolerance)
    / normalization_scale``

  builds the complete violation ``EmpiricalDistributionSummary``,
  ``target_achievement_count`` (the exact achieved count),
  ``empirical_target_achievement_probability`` (``count /
  sample_count``), ``worst_normalized_target_violation`` (the
  violation distribution maximum), and ``target_violation_cvar``
  (``empirical_upper_tail_mean_95`` of the normalized violation
  tuple) - rejecting any non-finite or overflowing derivation and
  never clamping or partially returning evidence;
- for optimization-only objectives (``minimize``/``maximize`` with no
  target) all five targeted evidence fields remain ``None`` - no
  target is ever invented;
- computes the orientation-aware adverse-tail statistic in the
  metric's original unit through the accepted primitives: the
  upper-tail mean for ``minimize``, the lower-tail mean for
  ``maximize``, and the upper-tail mean of the absolute deviations
  from the target for ``reach``;
- copies the objective/metric/unit/direction/target/tolerance/weight/
  normalization-scale snapshots exactly from the revalidated binding
  and the strategy identity and the three positions exactly from the
  caller - no campaign or matrix identity is derived here.

Error semantics (the accepted Slice 1 contract): invalid shape, type,
or non-finite input raises ``ValueError``; a finite-float conversion
failure or a statistical/arithmetic overflow raises ``OverflowError``
and is never silently converted into ``ValueError``. No derived value
is ever clamped, rounded, or partially returned; on any failure the
function raises and returns nothing.

Equivalent inputs always produce exactly equal models and exactly
equal serialized payloads.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal, cast

from pydantic import ValidationError

from kalhas.application.campaign_metric_statistics_runtime import (
    statistics_arithmetic_mean,
    statistics_maximum,
    statistics_median,
    statistics_minimum,
    statistics_population_standard_deviation,
)
from kalhas.application.campaign_outcome_statistics import (
    EMPIRICAL_QUANTILE_ALGORITHM,
    EMPIRICAL_TAIL_ALGORITHM,
    EMPIRICAL_TAIL_ALPHA,
    empirical_lower_tail_mean_95,
    empirical_type7_quantile,
    empirical_upper_tail_mean_95,
)
from kalhas.contracts.v1.campaign_outcome import (
    EmpiricalDistributionSummary,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding


def _validated_observed_values(values: object) -> tuple[int | float, ...]:
    """Strictly validate the exact observed-values contract, returning them unchanged.

    ``values`` must be an actual plain ``tuple`` instance (exact type;
    tuple subclasses are rejected), non-empty, with every value of
    exact type ``int`` or ``float`` - booleans are rejected even though
    they subclass ``int``, and strings, ``Decimal``, ``None``,
    containers, and arbitrary numeric-like objects are rejected - and
    every float finite. After those checks every sample is
    independently proven convertible to a finite float before the
    builder proceeds: an integer whose conversion raises
    ``OverflowError`` fails with ``OverflowError`` immediately, and a
    conversion that is not finite also fails with ``OverflowError``.
    Nothing is coerced, clipped, repaired, normalized, rounded, or
    mutated; the exact tuple is returned unchanged. Invalid input
    raises ``ValueError``.
    """
    if type(values) is not tuple:
        raise ValueError("ordered_observed_values must be an actual tuple")
    if not values:
        raise ValueError("ordered_observed_values must be non-empty")
    for value in values:
        if type(value) is bool or (type(value) is not int and type(value) is not float):
            raise ValueError("every observed value must have exact type int or float")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("float observed values must be finite")
        try:
            converted = float(value)
        except OverflowError:
            raise OverflowError("observed value cannot be represented as a finite float") from None
        if not math.isfinite(converted):
            raise OverflowError("observed value cannot be represented as a finite float")
    return cast(tuple[int | float, ...], values)


def _validated_position(value: object, field_name: str) -> int:
    """Reject every position that is not an exact non-negative ``int``.

    Booleans (which subclass ``int``), integral floats, numeric
    strings, ``None``, and negative integers are rejected - the same
    exact-int/no-bool policy the accepted output contract enforces.
    """
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an exact int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _build_distribution_summary(samples: tuple[int | float, ...]) -> EmpiricalDistributionSummary:
    """The exact ``EmpiricalDistributionSummary`` of validated samples.

    Reuses the accepted primitives unchanged: minimum/maximum/mean/
    median/population standard deviation from the frozen Phase 22
    statistics functions and the four Type 7 quantiles from the
    accepted statistics module. A single sample or a collection whose
    finite-float projections are all equal emits a population standard
    deviation of exactly ``0.0`` (the float formula would otherwise
    report a sub-ULP artifact for repeated collections); non-constant
    collections use the frozen Phase 22 primitive unchanged. Every
    derived value must be finite - an intermediate statistical
    overflow raises ``OverflowError`` before any model is built.
    """
    minimum = statistics_minimum(samples)
    maximum = statistics_maximum(samples)
    arithmetic_mean = statistics_arithmetic_mean(samples)
    median = statistics_median(samples)
    if len(samples) == 1 or minimum == maximum:
        population_standard_deviation = 0.0
    else:
        population_standard_deviation = statistics_population_standard_deviation(samples)
    p05 = empirical_type7_quantile(samples, 5)
    p25 = empirical_type7_quantile(samples, 25)
    p75 = empirical_type7_quantile(samples, 75)
    p95 = empirical_type7_quantile(samples, 95)
    for derived in (
        minimum,
        maximum,
        arithmetic_mean,
        median,
        population_standard_deviation,
        p05,
        p25,
        p75,
        p95,
    ):
        if not math.isfinite(derived):
            raise OverflowError("derived statistics overflowed to a non-finite value")
    return EmpiricalDistributionSummary(
        ordered_samples=samples,
        sample_count=len(samples),
        minimum=minimum,
        maximum=maximum,
        arithmetic_mean=arithmetic_mean,
        median=median,
        population_standard_deviation=population_standard_deviation,
        quantile_algorithm=cast(Literal["hyndman-fan-type-7-v1"], EMPIRICAL_QUANTILE_ALGORITHM),
        p05=p05,
        p25=p25,
        p75=p75,
        p95=p95,
    )


def build_strategy_objective_outcome(
    *,
    sequence_position: int,
    strategy_position: int,
    objective_position: int,
    strategy_candidate_id: str,
    binding: ObjectiveMetricBinding,
    ordered_observed_values: tuple[int | float, ...],
) -> StrategyObjectiveOutcome:
    """Build one deterministic strategy/objective outcome evidence artifact.

    All inputs are strictly revalidated before any field is trusted
    and nothing is ever mutated: the binding must be a real
    ``ObjectiveMetricBinding`` instance whose serialized Python payload
    revalidates strictly, the observed values must be a non-empty exact
    tuple of exact finite ``int``/``float`` samples in authoritative
    seed order, the three positions must be exact non-negative
    ``int``s, and the strategy identity must be a non-empty string.
    The empirical distribution summary, the targeted evidence (when a
    target exists), the target-violation CVaR, and the orientation-
    aware adverse-tail statistic are all derived exclusively through
    the accepted primitives listed in the module docstring. Invalid
    shape/type/non-finite input raises ``ValueError``; finite-float
    conversion and statistical/arithmetic overflow raise
    ``OverflowError``. The returned artifact is empirical evidence
    only - nothing here ranks, scores, compares strategies, prefers,
    recommends, forecasts, or produces a decision brief.
    """
    if not isinstance(binding, ObjectiveMetricBinding):
        raise ValueError("binding must be an ObjectiveMetricBinding instance")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            verified_binding = ObjectiveMetricBinding.model_validate(
                binding.model_dump(mode="python"), strict=True
            )
    except (ValidationError, TypeError, AttributeError, ValueError):
        raise ValueError("binding violates the ObjectiveMetricBinding contract") from None
    samples = _validated_observed_values(ordered_observed_values)
    sequence_position = _validated_position(sequence_position, "sequence_position")
    strategy_position = _validated_position(strategy_position, "strategy_position")
    objective_position = _validated_position(objective_position, "objective_position")
    if not isinstance(strategy_candidate_id, str) or not strategy_candidate_id:
        raise ValueError("strategy_candidate_id must be a non-empty string")

    direction = verified_binding.direction
    target = verified_binding.target
    tolerance = verified_binding.reach_tolerance
    scale = verified_binding.normalization_scale
    if direction == "reach" and (target is None or tolerance is None):
        raise ValueError("reach objectives require an authoritative target and tolerance")

    empirical_distribution = _build_distribution_summary(samples)

    violation_distribution: EmpiricalDistributionSummary | None = None
    worst_violation: float | None = None
    cvar: float | None = None
    achieved_count: int | None = None
    probability: float | None = None
    adverse_tail_statistic: float
    if target is None:
        if direction == "minimize":
            adverse_tail_statistic = empirical_upper_tail_mean_95(samples)
        else:
            adverse_tail_statistic = empirical_lower_tail_mean_95(samples)
    else:
        violation_values: list[float] = []
        count = 0
        for value in samples:
            if direction == "minimize":
                delta = value - target
                achieved = value <= target
            elif direction == "maximize":
                delta = target - value
                achieved = value >= target
            else:
                if tolerance is None:
                    raise ValueError("reach objectives require a reach_tolerance")
                delta = abs(value - target) - tolerance
                achieved = abs(value - target) <= tolerance
            if achieved:
                count += 1
            violation = max(0.0, delta) / scale
            if not math.isfinite(violation):
                raise OverflowError("normalized target violation derivation overflow")
            violation_values.append(violation)
        violations = tuple(violation_values)
        violation_distribution = _build_distribution_summary(violations)
        worst_violation = violation_distribution.maximum
        cvar = empirical_upper_tail_mean_95(violations)
        achieved_count = count
        probability = count / len(samples)
        if direction == "reach":
            deviations = tuple(abs(value - target) for value in samples)
            for deviation in deviations:
                if not math.isfinite(deviation):
                    raise OverflowError("reach deviation derivation overflow")
            adverse_tail_statistic = empirical_upper_tail_mean_95(deviations)
        elif direction == "minimize":
            adverse_tail_statistic = empirical_upper_tail_mean_95(samples)
        else:
            adverse_tail_statistic = empirical_lower_tail_mean_95(samples)

    try:
        outcome = StrategyObjectiveOutcome(
            sequence_position=sequence_position,
            strategy_position=strategy_position,
            objective_position=objective_position,
            strategy_candidate_id=strategy_candidate_id,
            objective_id=verified_binding.objective_id,
            metric_id=verified_binding.metric_id,
            metric_unit=verified_binding.metric_unit,
            direction=direction,
            target=target,
            reach_tolerance=tolerance,
            weight=verified_binding.weight,
            normalization_scale=scale,
            ordered_observed_values=samples,
            empirical_distribution=empirical_distribution,
            target_achievement_count=achieved_count,
            empirical_target_achievement_probability=probability,
            normalized_target_violation_distribution=violation_distribution,
            worst_normalized_target_violation=worst_violation,
            tail_alpha=EMPIRICAL_TAIL_ALPHA,
            tail_algorithm=cast(
                Literal["empirical-fractional-tail-mean-v1"], EMPIRICAL_TAIL_ALGORITHM
            ),
            target_violation_cvar=cvar,
            adverse_tail_statistic=adverse_tail_statistic,
        )
    except ValidationError:
        raise ValueError("strategy objective outcome construction failed") from None
    return outcome


__all__ = ["build_strategy_objective_outcome"]
