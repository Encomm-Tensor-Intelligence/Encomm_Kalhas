"""Deterministic pure numeric primitives for paired comparison and weighted regret (KALHAS).

This module defines the pure numerical foundation of the campaign
decision statistics surface: direction-normalized paired deltas between
two strategies over identical shared seeds, the derived win/tie/loss
decomposition with median/p05/p95/extrema statistics, same-seed
normalized regret across all supplied strategies in authoritative
strategy order, and the weighted regret aggregation helpers
(per-objective weighted mean regret, per-seed total weighted regret, the
complete per-seed total vector from rectangular objective-major regret
vectors, and the median/p95/maximum statistics of that vector).

The module is pure, deterministic, store-free, contract-free, and
domain-neutral: it imports only the Python standard library plus the
accepted median primitive (``statistics_median`` from the frozen
metric-statistics runtime) and the accepted Type-7 quantile primitive
(``empirical_type7_quantile`` from the outcome-statistics module). It
never redefines or subtly redefines those accepted algorithms. It reads
no wall clock, uses no randomness, network, providers, filesystem,
store, API, adapters, or domain packs, and never mutates any caller
collection or value. It carries no candidate-choice logic and produces
no decision artifact of any kind: no strategy is ever chosen or ordered
here.

Common validation contract (enforced independently by every public
primitive before any selection, sorting, or arithmetic):

- collections must be actual plain ``tuple`` instances (exact type;
  tuple subclasses are rejected), non-empty where mathematically
  required, with exact rectangular shape where required;
- every numeric value must have exact type ``int`` or ``float`` -
  ``bool`` is rejected even though it subclasses ``int``, and strings,
  ``Decimal``, ``None``, containers, and arbitrary numeric-like objects
  (including numeric subclasses) are rejected;
- float values must be finite (NaN and Infinity are rejected);
- every integer is independently proven convertible to a finite float
  before any arithmetic begins - a huge integer that cannot be
  represented as a finite float raises ``OverflowError``;
- invalid shape, type, or non-finite input raises ``ValueError``;
- finite inputs whose arithmetic result overflows or becomes non-finite
  raise ``OverflowError``; an impossible negative regret result is
  rejected rather than clamped;
- nothing is ever clamped, repaired, rounded, normalized, or silently
  skipped, and caller collections are never mutated or reordered.

Direction rules: ``direction`` must be exactly one of ``minimize``,
``maximize``, or ``reach``. ``normalization_scale`` must be an exact
finite numeric greater than zero. ``tie_tolerance`` and ``weight`` must
be exact finite numerics greater than or equal to zero. ``reach``
requires an exact finite ``target``; ``minimize``/``maximize`` never use
``target``.

Paired delta formulas (positive always means the first strategy is
worse, negative means better):

- minimize: ``(value_A - value_B) / normalization_scale``
- maximize: ``(value_B - value_A) / normalization_scale``
- reach: ``(abs(value_A - target) - abs(value_B - target))
  / normalization_scale``

Tie classification under the declared tolerance: ``delta < -tolerance``
is a win for the first strategy, ``abs(delta) <= tolerance`` is a tie
(``+-tolerance`` inclusive), and ``delta > +tolerance`` is a loss.

Same-seed regret formulas (one objective, one seed, all supplied
strategies compared under the same comparator):

- minimize: ``(value - same_seed_minimum) / normalization_scale``
- maximize: ``(same_seed_maximum - value) / normalization_scale``
- reach: ``(abs(value - target) - same_seed_minimum_absolute_deviation)
  / normalization_scale``

The best same-seed strategy receives exactly ``0.0`` where arithmetic
permits; tied best strategies all receive ``0.0``; regret is
non-negative; and regret is comparative - it stays distinct from target
violation.

Weighted aggregation: per-objective weighted mean regret is ``weight *
math.fsum(per_seed_regrets) / sample_count``; per-seed total weighted
regret is ``math.fsum(weight_j * regret_j)`` over the authoritative
objective order. Weights are never renormalized; all-zero weights are
valid and produce exact zero totals. All required sums use
``math.fsum`` and every result is provably finite and non-negative.
This module performs no selection of any kind.
"""

from __future__ import annotations

import math
from typing import Literal, NamedTuple, cast

from kalhas.application.campaign_metric_statistics_runtime import statistics_median
from kalhas.application.campaign_outcome_statistics import empirical_type7_quantile

#: The exact closed set of supported objective directions.
Direction = Literal["minimize", "maximize", "reach"]

_DIRECTIONS: tuple[Direction, ...] = ("minimize", "maximize", "reach")


class PairedDeltaSummary(NamedTuple):
    """Immutable summary of one ordered paired-delta tuple.

    Exposes the win/tie/loss decomposition under the declared tie
    tolerance (``win_count``/``tie_count``/``loss_count`` and the exact
    rates ``count / sample_count``) plus the deterministic location and
    spread statistics (``median_paired_delta``, ``p05_paired_delta``,
    ``p95_paired_delta``) and the exact extrema (``worst_paired_delta``
    is the maximum, ``best_paired_delta`` is the minimum). Positive
    deltas always mean the first strategy is worse. The summary carries
    no strategy choice of any kind.
    """

    sample_count: int
    win_count: int
    tie_count: int
    loss_count: int
    win_rate: float
    tie_rate: float
    loss_rate: float
    median_paired_delta: float
    p05_paired_delta: float
    p95_paired_delta: float
    worst_paired_delta: float
    best_paired_delta: float


class TotalRegretSummary(NamedTuple):
    """Immutable aggregate statistics of a complete per-seed total-regret vector.

    Exposes the deterministic median, the Type-7 p95, and the exact
    maximum of the per-seed total weighted regrets, all of which are
    provably finite and non-negative.
    """

    sample_count: int
    median_total_regret: float
    p95_total_regret: float
    maximum_total_regret: float


def _exact_finite_float(value: int | float, name: str) -> float:
    """Exact-type finite numeric proof for one scalar value.

    ``value`` must have exact type ``int`` or ``float`` - ``bool``,
    strings, ``Decimal``, ``None``, containers, and numeric subclasses
    are rejected - and every float must be finite. After the exact-type
    and finite checks the integer is independently proven convertible to
    a finite float: an unrepresentable huge integer raises
    ``OverflowError``. Nothing is coerced, clipped, repaired, rounded,
    or mutated. Invalid input raises ``ValueError``.
    """
    if type(value) is bool:
        raise ValueError(f"{name} must be an exact int or float")
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be an exact int or float")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    try:
        converted = float(value)
    except OverflowError:
        raise OverflowError(f"{name} cannot be represented as a finite float") from None
    if not math.isfinite(converted):
        raise OverflowError(f"{name} cannot be represented as a finite float")
    return converted


def _validated_numeric_tuple(values: object, name: str, *, non_empty: bool) -> tuple[float, ...]:
    """Strictly validate the common numeric-collection contract.

    ``values`` must be an actual plain ``tuple`` instance (tuple
    subclasses are rejected), non-empty when ``non_empty`` is true, with
    every value validated by :func:`_exact_finite_float` - the complete
    tuple is validated before any arithmetic can begin. Returns a fresh
    tuple of the finite float projections; the caller collection is
    never mutated or reordered.
    """
    if type(values) is not tuple:
        raise ValueError(f"{name} must be an actual tuple")
    samples = cast("tuple[int | float, ...]", values)
    if non_empty and not samples:
        raise ValueError(f"{name} must be non-empty")
    return tuple(
        _exact_finite_float(value, f"{name}[{index}]") for index, value in enumerate(samples)
    )


def _validated_non_negative_tuple(
    values: object, name: str, *, non_empty: bool
) -> tuple[float, ...]:
    """Like :func:`_validated_numeric_tuple`, with every value additionally
    required to be non-negative."""
    converted = _validated_numeric_tuple(values, name, non_empty=non_empty)
    for value in converted:
        if value < 0.0:
            raise ValueError(f"{name} must be non-negative")
    return converted


def _validated_direction(direction: object) -> None:
    """Reject every direction except the exact strings ``minimize``, ``maximize``, ``reach``."""
    if type(direction) is not str or direction not in _DIRECTIONS:
        raise ValueError("direction must be exactly 'minimize', 'maximize', or 'reach'")


def _validated_positive_scale(value: int | float) -> float:
    """An exact finite numeric strictly greater than zero."""
    converted = _exact_finite_float(value, "normalization_scale")
    if converted <= 0.0:
        raise ValueError("normalization_scale must be greater than zero")
    return converted


def _validated_non_negative(value: int | float, name: str) -> float:
    """An exact finite numeric greater than or equal to zero."""
    converted = _exact_finite_float(value, name)
    if converted < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return converted


def _resolved_target(direction: Direction, target: int | float | None) -> float | None:
    """The finite float target for ``reach``, or ``None`` for the other directions.

    ``reach`` requires an exact finite target (a missing target raises
    ``ValueError``; an invalid or unrepresentable target raises
    ``ValueError``/``OverflowError`` through :func:`_exact_finite_float`).
    ``minimize`` and ``maximize`` never use ``target``: it is neither
    validated nor read.
    """
    if direction == "reach":
        if target is None:
            raise ValueError("reach requires an exact finite target")
        return _exact_finite_float(target, "target")
    return None


def _paired_delta_value(
    value_a: float,
    value_b: float,
    *,
    direction: Direction,
    normalization_scale: float,
    target: float | None,
) -> float:
    """One direction-normalized paired delta for one shared seed.

    Implements the authoritative formulas: minimize ``(A - B) / scale``,
    maximize ``(B - A) / scale``, reach
    ``(abs(A - target) - abs(B - target)) / scale``. Positive always
    means the first strategy is worse. Every intermediate step that
    could become non-finite is checked: an overflowing difference,
    deviation, or division raises ``OverflowError``, and NaN/Infinity is
    never returned.
    """
    if direction == "minimize":
        difference = value_a - value_b
        if not math.isfinite(difference):
            raise OverflowError("paired delta difference is not finite")
        result = difference / normalization_scale
    elif direction == "maximize":
        difference = value_b - value_a
        if not math.isfinite(difference):
            raise OverflowError("paired delta difference is not finite")
        result = difference / normalization_scale
    else:
        if target is None:  # defensive; reach targets are resolved before arithmetic
            raise ValueError("reach requires an exact finite target")
        deviation_a = abs(value_a - target)
        if not math.isfinite(deviation_a):
            raise OverflowError("reach deviation is not finite")
        deviation_b = abs(value_b - target)
        if not math.isfinite(deviation_b):
            raise OverflowError("reach deviation is not finite")
        difference = deviation_a - deviation_b
        result = difference / normalization_scale
    if not math.isfinite(result):
        raise OverflowError("paired delta result is not finite")
    return result


def paired_delta(
    value_a: int | float,
    value_b: int | float,
    *,
    direction: Direction,
    normalization_scale: int | float,
    target: int | float | None = None,
) -> float:
    """One direction-normalized paired delta between two strategies for one shared seed.

    Positive means the first strategy is worse; negative means the first
    strategy is better; exactly ``0.0`` means identical. ``direction``
    must be exactly ``minimize``, ``maximize``, or ``reach``;
    ``normalization_scale`` must be an exact finite numeric greater than
    zero; ``reach`` requires an exact finite ``target`` (``minimize``
    and ``maximize`` never use ``target``). Both values are fully
    validated before any arithmetic. Invalid shape/type/non-finite input
    raises ``ValueError``; an unrepresentable integer or an overflowing
    arithmetic result raises ``OverflowError``; NaN/Infinity is never
    returned.
    """
    _validated_direction(direction)
    value_a_float = _exact_finite_float(value_a, "value_a")
    value_b_float = _exact_finite_float(value_b, "value_b")
    scale = _validated_positive_scale(normalization_scale)
    target_float = _resolved_target(direction, target)
    return _paired_delta_value(
        value_a_float,
        value_b_float,
        direction=direction,
        normalization_scale=scale,
        target=target_float,
    )


def paired_delta_vector(
    values_a: tuple[int | float, ...],
    values_b: tuple[int | float, ...],
    *,
    direction: Direction,
    normalization_scale: int | float,
    target: int | float | None = None,
) -> tuple[float, ...]:
    """The ordered paired-delta vector over identical authoritative shared-seed order.

    Both tuples must be actual plain tuples of the same non-empty
    length; every sample in both tuples is validated before any
    arithmetic. The result tuple preserves the exact shared-seed order
    (no independent sorting or matching by value), and the swapped
    A/B vector is the exact sign reverse of this vector where IEEE
    arithmetic permits. ``direction``/``normalization_scale``/``target``
    follow :func:`paired_delta`. Invalid input raises ``ValueError``;
    an unrepresentable integer or an overflowing arithmetic result
    raises ``OverflowError``; NaN/Infinity is never returned; caller
    tuples are never mutated or reordered.
    """
    _validated_direction(direction)
    scale = _validated_positive_scale(normalization_scale)
    target_float = _resolved_target(direction, target)
    if type(values_a) is not tuple:
        raise ValueError("values_a must be an actual tuple")
    if type(values_b) is not tuple:
        raise ValueError("values_b must be an actual tuple")
    if not values_a or not values_b:
        raise ValueError("values_a and values_b must be non-empty")
    if len(values_a) != len(values_b):
        raise ValueError("values_a and values_b must have the same length")
    converted_a = tuple(_exact_finite_float(value, "values_a") for value in values_a)
    converted_b = tuple(_exact_finite_float(value, "values_b") for value in values_b)
    return tuple(
        _paired_delta_value(
            value_a,
            value_b,
            direction=direction,
            normalization_scale=scale,
            target=target_float,
        )
        for value_a, value_b in zip(converted_a, converted_b, strict=True)
    )


def paired_delta_statistics(
    deltas: tuple[int | float, ...],
    *,
    tie_tolerance: int | float,
) -> PairedDeltaSummary:
    """The win/tie/loss decomposition and statistics of one ordered paired-delta tuple.

    Classification under the declared tolerance: ``delta < -tolerance``
    is a win for the first strategy, ``abs(delta) <= tolerance`` is a
    tie (values at exactly ``+-tolerance`` are ties), and
    ``delta > +tolerance`` is a loss. The rates are the exact quotients
    ``count / sample_count``; ``worst_paired_delta`` is the exact
    maximum and ``best_paired_delta`` the exact minimum; the median
    comes from the accepted ``statistics_median`` primitive and p05/p95
    from the accepted Type-7 ``empirical_type7_quantile`` primitive -
    never redefined. ``tie_tolerance`` must be an exact finite numeric
    greater than or equal to zero. Invalid input raises ``ValueError``;
    an unrepresentable integer or an overflowing statistical result
    raises ``OverflowError``; NaN/Infinity is never returned; the
    returned summary is immutable and carries no strategy choice.
    """
    tolerance = _validated_non_negative(tie_tolerance, "tie_tolerance")
    if type(deltas) is not tuple:
        raise ValueError("deltas must be an actual tuple")
    if not deltas:
        raise ValueError("deltas must be non-empty")
    converted = tuple(
        _exact_finite_float(delta, f"deltas[{index}]") for index, delta in enumerate(deltas)
    )
    sample_count = len(converted)
    win_count = 0
    tie_count = 0
    loss_count = 0
    for delta in converted:
        if delta < -tolerance:
            win_count += 1
        elif delta > tolerance:
            loss_count += 1
        else:
            tie_count += 1
    median_paired_delta = statistics_median(converted)
    if not math.isfinite(median_paired_delta):
        raise OverflowError("median paired delta is not finite")
    p05_paired_delta = empirical_type7_quantile(converted, 5)
    p95_paired_delta = empirical_type7_quantile(converted, 95)
    return PairedDeltaSummary(
        sample_count=sample_count,
        win_count=win_count,
        tie_count=tie_count,
        loss_count=loss_count,
        win_rate=win_count / sample_count,
        tie_rate=tie_count / sample_count,
        loss_rate=loss_count / sample_count,
        median_paired_delta=median_paired_delta,
        p05_paired_delta=p05_paired_delta,
        p95_paired_delta=p95_paired_delta,
        worst_paired_delta=float(max(converted)),
        best_paired_delta=float(min(converted)),
    )


def same_seed_regret(
    values: tuple[int | float, ...],
    *,
    direction: Direction,
    normalization_scale: int | float,
    target: int | float | None = None,
) -> tuple[float, ...]:
    """Same-seed normalized regret for one objective across all supplied strategies.

    Compares every supplied strategy value under the same seed against
    the same-seed comparator over all strategies - minimize uses the
    same-seed minimum, maximize the same-seed maximum, and reach the
    same-seed minimum absolute deviation from ``target`` - and returns
    the regret of each strategy in the exact supplied strategy order
    (never sorted). The best same-seed strategy receives exactly ``0.0``
    where arithmetic permits; tied best strategies all receive ``0.0``;
    every regret is non-negative; an impossible negative or non-finite
    result is rejected with ``OverflowError`` rather than clamped.
    Regret is comparative and remains distinct from target violation.
    ``values`` must be an actual non-empty plain tuple; at least one
    strategy value is required. ``direction``/``normalization_scale``/
    ``target`` follow :func:`paired_delta`. Invalid input raises
    ``ValueError``; an unrepresentable integer or an overflowing
    arithmetic result raises ``OverflowError``; NaN/Infinity is never
    returned; the caller tuple is never mutated.
    """
    _validated_direction(direction)
    scale = _validated_positive_scale(normalization_scale)
    target_float = _resolved_target(direction, target)
    if type(values) is not tuple:
        raise ValueError("values must be an actual tuple")
    if not values:
        raise ValueError("values must be non-empty")
    converted = tuple(
        _exact_finite_float(value, f"values[{index}]") for index, value in enumerate(values)
    )
    deviations: list[float] | None = None
    if direction == "minimize":
        comparator = min(converted)
    elif direction == "maximize":
        comparator = max(converted)
    else:
        if target_float is None:  # defensive; reach targets are resolved before arithmetic
            raise ValueError("reach requires an exact finite target")
        deviations = []
        for value in converted:
            deviation = abs(value - target_float)
            if not math.isfinite(deviation):
                raise OverflowError("reach deviation is not finite")
            deviations.append(deviation)
        comparator = min(deviations)
    regrets: list[float] = []
    for position, value in enumerate(converted):
        if direction == "minimize":
            regret = (value - comparator) / scale
        elif direction == "maximize":
            regret = (comparator - value) / scale
        else:
            if deviations is None:  # defensive; unreachable after the branch above
                raise ValueError("reach requires an exact finite target")
            regret = (deviations[position] - comparator) / scale
        if not math.isfinite(regret):
            raise OverflowError("regret result is not finite")
        if regret < 0.0:
            raise OverflowError("regret result is negative")
        regrets.append(regret)
    return tuple(regrets)


def objective_weighted_mean_regret(
    per_seed_regrets: tuple[int | float, ...],
    *,
    weight: int | float,
) -> float:
    """Per-objective weighted mean regret over the per-seed regrets of one objective.

    Computes exactly ``weight * math.fsum(per_seed_regrets) /
    sample_count``. The weight is an exact finite numeric greater than
    or equal to zero and is never renormalized; ``per_seed_regrets``
    must be an actual non-empty plain tuple of exact finite non-negative
    numerics. The result is provably finite and non-negative: an
    overflowing sum or product raises ``OverflowError`` and an
    all-zero-weight call returns exactly ``0.0``. Invalid input raises
    ``ValueError``; NaN/Infinity is never returned.
    """
    regrets = _validated_non_negative_tuple(per_seed_regrets, "per_seed_regrets", non_empty=True)
    weight_float = _validated_non_negative(weight, "weight")
    total = math.fsum(regrets)
    if not math.isfinite(total):
        raise OverflowError("regret sum is not finite")
    result = weight_float * total / len(regrets)
    if not math.isfinite(result):
        raise OverflowError("weighted mean regret is not finite")
    return result


def per_seed_total_weighted_regret(
    per_seed_regrets: tuple[int | float, ...],
    weights: tuple[int | float, ...],
) -> float:
    """Per-seed total weighted regret over the authoritative objective order.

    Computes exactly ``math.fsum(weight_j * regret_j)`` for one seed,
    where ``per_seed_regrets`` carries the per-objective regrets of that
    seed in the authoritative objective order and ``weights`` the
    matching objective weights. Both must be actual non-empty plain
    tuples of the same length; every regret and weight must be an exact
    finite non-negative numeric. Weights are never renormalized and an
    all-zero-weight call returns exactly ``0.0``. The result is provably
    finite and non-negative: an overflowing product or sum raises
    ``OverflowError``. Invalid input raises ``ValueError``; NaN/Infinity
    is never returned.
    """
    regrets = _validated_non_negative_tuple(per_seed_regrets, "per_seed_regrets", non_empty=True)
    weight_values = _validated_non_negative_tuple(weights, "weights", non_empty=True)
    if len(regrets) != len(weight_values):
        raise ValueError("per_seed_regrets and weights must have the same length")
    total = math.fsum(
        weight_value * regret for weight_value, regret in zip(weight_values, regrets, strict=True)
    )
    if not math.isfinite(total):
        raise OverflowError("per-seed total regret is not finite")
    return total


def total_regret_vector(
    objective_regret_vectors: tuple[tuple[int | float, ...], ...],
    weights: tuple[int | float, ...],
) -> tuple[float, ...]:
    """The complete per-seed total weighted regret vector from rectangular
    objective-major regret vectors.

    ``objective_regret_vectors`` is an objective-major matrix: one
    actual non-empty plain tuple per objective, each carrying that
    objective's per-seed regrets in the exact shared-seed order, and all
    rows sharing one common seed count (rectangular shape is fully
    validated before any arithmetic). ``weights`` carries one exact
    finite non-negative weight per objective in the exact authoritative
    objective order. For every seed the total is exactly
    ``math.fsum(weight_j * regret_j)`` over the objectives; the result
    tuple preserves the exact seed order. Weights are never
    renormalized; all-zero weights produce an exact all-zero vector.
    Every total is provably finite and non-negative: an overflowing
    product or sum raises ``OverflowError``. Invalid input raises
    ``ValueError``; NaN/Infinity is never returned; no caller tuple is
    ever mutated.
    """
    if type(objective_regret_vectors) is not tuple:
        raise ValueError("objective_regret_vectors must be an actual tuple")
    if not objective_regret_vectors:
        raise ValueError("objective_regret_vectors must be non-empty")
    weight_values = _validated_non_negative_tuple(weights, "weights", non_empty=True)
    rows: list[tuple[float, ...]] = []
    seed_count: int | None = None
    for vector in objective_regret_vectors:
        if type(vector) is not tuple:
            raise ValueError("every objective regret vector must be an actual tuple")
        if not vector:
            raise ValueError("every objective regret vector must be non-empty")
        row = _validated_non_negative_tuple(vector, "objective_regret_vectors", non_empty=False)
        if seed_count is None:
            seed_count = len(row)
        elif len(row) != seed_count:
            raise ValueError("objective regret vectors must share one common seed count")
        rows.append(row)
    if len(rows) != len(weight_values):
        raise ValueError("weights must match the objective regret vector count")
    if seed_count is None:  # defensive; the non-empty check above prevents this
        raise ValueError("objective_regret_vectors must be non-empty")
    totals: list[float] = []
    for seed_position in range(seed_count):
        total = math.fsum(
            weight_values[objective] * rows[objective][seed_position]
            for objective in range(len(rows))
        )
        if not math.isfinite(total):
            raise OverflowError("per-seed total regret is not finite")
        totals.append(total)
    return tuple(totals)


def total_regret_statistics(
    total_regrets: tuple[int | float, ...],
) -> TotalRegretSummary:
    """The median, p95, and maximum statistics of a complete per-seed total-regret vector.

    ``total_regrets`` must be an actual non-empty plain tuple of exact
    finite non-negative numerics (per-seed total weighted regrets in
    seed order). The median comes from the accepted ``statistics_median``
    primitive and p95 from the accepted Type-7
    ``empirical_type7_quantile`` primitive - never redefined - and the
    maximum is the exact maximum. Every statistic is provably finite and
    non-negative: an overflowing statistical result raises
    ``OverflowError``. Invalid input raises ``ValueError``; NaN/Infinity
    is never returned; the returned summary is immutable.
    """
    values = _validated_non_negative_tuple(total_regrets, "total_regrets", non_empty=True)
    median_total_regret = statistics_median(values)
    if not math.isfinite(median_total_regret):
        raise OverflowError("median total regret is not finite")
    return TotalRegretSummary(
        sample_count=len(values),
        median_total_regret=median_total_regret,
        p95_total_regret=empirical_type7_quantile(values, 95),
        maximum_total_regret=float(max(values)),
    )


__all__ = [
    "PairedDeltaSummary",
    "TotalRegretSummary",
    "paired_delta",
    "paired_delta_vector",
    "paired_delta_statistics",
    "same_seed_regret",
    "objective_weighted_mean_regret",
    "per_seed_total_weighted_regret",
    "total_regret_vector",
    "total_regret_statistics",
]
