"""Nested immutable campaign-outcome evidence value objects (KALHAS).

This module defines three nested, immutable, declarative value objects
that describe empirical campaign outcome evidence:

- ``EmpiricalDistributionSummary``: the exact ordered observed samples
  in authoritative shared-seed order together with their sample count,
  extrema, arithmetic mean, median, population standard deviation, and
  the deterministic empirical quantiles ``p05``/``p25``/``p75``/``p95``
  under an explicit quantile algorithm identifier.
- ``StrategyObjectiveOutcome``: one strategy/objective outcome binding
  the authoritative objective/metric snapshots (direction, target,
  reach tolerance, weight, normalization scale), the exact ordered
  observed values and their empirical summary, the target-achievement
  count and empirical probability when a target exists, the normalized
  target-violation distribution with its worst value and fixed-alpha
  0.95 CVaR when targeted, and the orientation-aware adverse-tail
  statistic in the metric's original unit.
- ``CampaignOutcomeDistributionMatrix``: the immutable top-level
  campaign outcome-distribution matrix binding one completed
  runtime-3.0.0 campaign's campaign/scenario/world identity and
  hashes, evaluation-profile and uncertainty-model provenance, the two
  exact source artifact references, the ordered strategy/seed/
  objective/metric identifiers, and the complete strategy-major,
  objective-minor outcome tuple - the structural shape is enforced
  here, while deterministic identity, content hashing, and source
  verification belong to the application layer.

The two outcome models are strict and frozen (``extra="forbid"``). Every numeric
field rejects booleans, strings, ``Decimal``, ``None``, containers,
non-finite floats, and unrepresentable integers on the un-coerced raw
input - no numeric string coercion and no NaN/Infinity ever pass.
Exact raw ``int`` and ``float`` types are preserved (integers stay
integers, floats stay floats).

The exact statistical algorithms - the Hyndman-Fan Type 7 empirical
quantile and the fixed-alpha fractional empirical tail means - are
owned by the accepted pure application primitives; these contracts
validate internal consistency only and never recompute or duplicate
those algorithms. The normalized target-violation and target-
achievement semantics, however, are independently recomputed here in
exact seed order from the frozen direction/target/tolerance/scale
snapshots, because they are pure function applications of the recorded
values; overflow and non-finite derivations are rejected.

The module is domain-neutral and declarative: it imports only the
Python standard library, pydantic, and the shared v1 contract module,
reads no wall clock, uses no randomness, network, providers,
filesystem, store, API, adapters, or domain packs, and exposes no
callback, expression, or executable surface.
``EmpiricalDistributionSummary`` and ``StrategyObjectiveOutcome`` are
plain ``BaseModel`` value objects that remain unregistered;
``CampaignOutcomeDistributionMatrix`` is a ``VersionedContract``
registered in the public contract registry and exported as its own
JSON Schema artifact. Nothing here ranks, prefers, selects, or
recommends a strategy; the artifacts are empirical evidence only.

Structural-bound comparison policy
----------------------------------

The statistical structural bounds (mean/median within extrema, the
non-decreasing quantile chain, the CVaR band, and the direction-aware
adverse-tail band) are compared with a deterministic
one-adjacent-float-step relation built on ``math.nextafter``: a value
may cross a structural bound by at most one adjacent representable
float, because the accepted pure statistical primitives can land one
ULP from the exact rational boundary (for example a Type 7
interpolated quantile of ``(99, 25, 99)`` is ``99.00000000000001``,
one step above the observed maximum, and the ``math.fsum``/``n`` mean
of ``(0.1, 0.1, 0.1)`` is ``0.10000000000000002``, one step above the
observed maximum). The policy exists solely for composability with
those accepted deterministic primitives; it is never ``math.isclose``,
never a relative tolerance, and never a broad absolute epsilon, and
crossing a structural bound by two or more adjacent float steps is
still rejected.

Semantic and identity invariants remain exact with no tolerance:
sample counts and positions, ordered-sample equality and seed order,
algorithm literals and the fixed alpha, target/direction/tolerance
rules, the independently recomputed normalized-violation tuple,
achievement count and probability, worst-violation equality with the
violation distribution maximum, targeted-versus-optimization-only
field presence, and every exact-type/finite-value/bool rejection. A
single sample still requires every location/quantile value to equal
the projected sample exactly and a standard deviation of exactly
``0.0``; a repeated multi-sample collection permits the deterministic
mean and quantile values to differ from the projected constant by at
most one adjacent float step while the population standard deviation
must remain exactly ``0.0``.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value.

    Booleans are never accepted as integers or numbers, and non-finite
    floats (NaN/Infinity) are rejected because they are not valid JSON
    numbers. Strings, ``Decimal``, ``None``, containers, and arbitrary
    numeric-like objects are rejected, and an integer that cannot be
    converted to a finite float is rejected too - no numeric coercion
    of any kind happens.
    """
    if type(value) is bool:
        return False
    if type(value) is not int and type(value) is not float:
        return False
    if type(value) is float and not math.isfinite(value):
        return False
    try:
        converted = float(value)
    except OverflowError:
        return False
    return math.isfinite(converted)


def _validate_exact_finite_samples(samples: object) -> None:
    """Reject any collection that is not a non-empty tuple/list of exact finite numerics.

    Every sample must have exact type ``int`` or ``float`` - booleans,
    strings, ``Decimal``, ``None``, containers, and arbitrary
    numeric-like objects are rejected - every float sample must be
    finite, and every sample must be convertible to a finite float
    (an unrepresentable integer raises a validation failure). The
    collection must be non-empty. Nothing is coerced, clipped,
    repaired, or mutated.
    """
    if not isinstance(samples, (list, tuple)):
        raise ValueError("ordered samples must be a tuple or list")
    if not samples:
        raise ValueError("ordered samples must be non-empty")
    for value in samples:
        if not _is_exact_finite_numeric(value):
            raise ValueError("every sample must be an exact finite int or float")


def _leq_within_one_step(left: float, right: float) -> bool:
    """``left <= right``, allowing ``left`` to be exactly one adjacent float step above ``right``.

    The deterministic structural-bound relation used for the floating
    statistical bounds, built on ``math.nextafter``: the accepted pure
    statistical primitives can land one ULP from the exact rational
    boundary, so a value exactly one adjacent representable float
    across a structural bound is accepted. Exact or better values are
    always accepted; crossing the bound by two or more adjacent float
    steps is rejected. No ``math.isclose``, no relative tolerance, and
    no broad absolute epsilon.
    """
    return left <= right or left == math.nextafter(right, math.inf)


def _eq_within_one_step(left: float, right: float) -> bool:
    """Exact equality, or one adjacent float step in either direction.

    Used only for the repeated multi-sample constant-value rule, where
    the deterministic mean/quantile values may differ from the
    projected constant by at most one adjacent representable float.
    """
    return (
        left == right
        or left == math.nextafter(right, math.inf)
        or left == math.nextafter(right, -math.inf)
    )


class EmpiricalDistributionSummary(BaseModel):
    """One immutable empirical distribution summary of exact ordered samples.

    Summarizes the exact ordered observed samples of one metric for one
    strategy across the campaign's identical ordered shared seeds: the
    samples are preserved in the exact authoritative seed order (raw
    integers remain integers, raw floats remain floats - never
    converted, rounded, clipped, normalized, weighted, or
    unit-converted), together with the sample count, the exact observed
    minimum and maximum, the arithmetic mean, the median, the population
    standard deviation, and the deterministic empirical quantiles
    ``p05``/``p25``/``p75``/``p95`` under the exact quantile algorithm
    identifier ``hyndman-fan-type-7-v1``.

    The contract validates internal consistency only: the count must
    equal the collection length; minimum and maximum must equal the
    exact finite-float projections of the observed extrema; every
    derived value must be finite; the mean and median must lie within
    the observed extrema; the standard deviation must be non-negative;
    the quantiles must be non-decreasing within the observed extrema;
    and the quantile algorithm must be the exact supported literal.
    The floating structural bounds (mean/median within extrema and the
    quantile chain) use the deterministic one-adjacent-float-step
    relation so that the output of the accepted pure statistical
    primitives - which can land one ULP from the exact rational
    boundary - is always composable with this contract. A single
    sample requires every derived location and quantile value to equal
    the projected sample exactly and a population standard deviation
    of exactly ``0.0``; a repeated multi-sample collection permits the
    deterministic mean and quantile values to differ from the
    projected constant by at most one adjacent float step while the
    population standard deviation must remain exactly ``0.0``. The
    exact Type 7 computation itself is owned by the accepted pure
    application primitives; this contract never recomputes or
    duplicates it.

    The summary is empirical evidence only: it ranks nothing, scores
    nothing, declares no winner, compares nothing against objectives or
    targets, creates no pass/fail judgment, and produces no outcomes,
    evidence briefs, recommendations, or decision briefs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordered_samples: tuple[int | float, ...] = Field(min_length=1)
    sample_count: int = Field(ge=1)
    minimum: float
    maximum: float
    arithmetic_mean: float
    median: float
    population_standard_deviation: float
    quantile_algorithm: Literal["hyndman-fan-type-7-v1"] = "hyndman-fan-type-7-v1"
    p05: float
    p25: float
    p75: float
    p95: float

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion.

        Pydantic lax mode would otherwise coerce booleans into numbers,
        integral floats into integers, and numeric strings into numbers;
        checking the un-coerced input keeps booleans, strings,
        ``Decimal``, ``None``, containers, and non-finite floats out of
        ``ordered_samples``, ``sample_count``, and every derived numeric
        field. ``sample_count`` must have exact type ``int`` (never
        ``bool``), and every derived numeric field must have exact raw
        type ``int`` or ``float`` and be finite and finite-float
        representable.
        """
        if not isinstance(data, dict):
            return data
        raw_samples = data.get("ordered_samples")
        if raw_samples is not None:
            _validate_exact_finite_samples(raw_samples)
        raw_count = data.get("sample_count")
        if raw_count is not None and type(raw_count) is not int:
            raise ValueError("sample_count must be an exact int")
        for key in (
            "minimum",
            "maximum",
            "arithmetic_mean",
            "median",
            "population_standard_deviation",
            "p05",
            "p25",
            "p75",
            "p95",
        ):
            raw = data.get(key)
            if raw is None:
                continue
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _summary_is_internally_consistent(self) -> EmpiricalDistributionSummary:
        """Enforce the exact summary consistency rules.

        The sample count must equal the collection length; minimum and
        maximum must equal the exact finite-float projections of the
        observed extrema (the accepted primitives operate in the
        finite-float codomain, so a legal integer sample such as
        ``2**53 + 1`` projects to its nearest finite float); every
        derived value must be finite; the arithmetic mean and the
        median must lie within the observed extrema; the population
        standard deviation must be non-negative; the empirical
        quantiles must be non-decreasing from ``p05`` through ``p95``
        within the observed extrema; and the quantile algorithm must be
        the exact supported literal. The floating statistical
        structural bounds (mean/median within extrema and the quantile
        chain) use the deterministic one-adjacent-float-step relation
        for composability with the accepted pure statistical
        primitives. A single sample requires every derived location and
        quantile value to equal the projected sample exactly and a
        population standard deviation of exactly ``0.0``; a repeated
        multi-sample collection permits the mean and quantile values to
        differ from the projected constant by at most one adjacent
        float step while the population standard deviation must remain
        exactly ``0.0``. The exact mean/median/standard-deviation/
        quantile computation lives in the pure application layer; the
        contract validates internal consistency only.
        """
        if self.sample_count != len(self.ordered_samples):
            raise ValueError("sample_count must equal len(ordered_samples)")
        if self.minimum != float(min(self.ordered_samples)):
            raise ValueError("minimum must equal the exact projected observed minimum")
        if self.maximum != float(max(self.ordered_samples)):
            raise ValueError("maximum must equal the exact projected observed maximum")
        for derived in (
            self.minimum,
            self.maximum,
            self.arithmetic_mean,
            self.median,
            self.population_standard_deviation,
            self.p05,
            self.p25,
            self.p75,
            self.p95,
        ):
            if not math.isfinite(derived):
                raise ValueError("every derived value must be finite")
        if not _leq_within_one_step(self.minimum, self.arithmetic_mean) or not _leq_within_one_step(
            self.arithmetic_mean, self.maximum
        ):
            raise ValueError("arithmetic_mean must lie within the observed extrema")
        if not _leq_within_one_step(self.minimum, self.median) or not _leq_within_one_step(
            self.median, self.maximum
        ):
            raise ValueError("median must lie within the observed extrema")
        if self.population_standard_deviation < 0.0:
            raise ValueError("population_standard_deviation must be non-negative")
        chain = (self.minimum, self.p05, self.p25, self.median, self.p75, self.p95, self.maximum)
        if any(not _leq_within_one_step(chain[i], chain[i + 1]) for i in range(len(chain) - 1)):
            raise ValueError(
                "empirical quantiles must be non-decreasing within the observed extrema"
            )
        if self.quantile_algorithm != "hyndman-fan-type-7-v1":
            raise ValueError("quantile_algorithm must be the exact supported literal")
        if self.sample_count == 1:
            expected = float(self.ordered_samples[0])
            for derived in (
                self.minimum,
                self.maximum,
                self.arithmetic_mean,
                self.median,
                self.p05,
                self.p25,
                self.p75,
                self.p95,
            ):
                if derived != expected:
                    raise ValueError(
                        "a single sample requires every derived value to equal the "
                        "projected sample exactly"
                    )
            if self.population_standard_deviation != 0.0:
                raise ValueError(
                    "a single sample requires a population standard deviation of exactly 0.0"
                )
        elif self.minimum == self.maximum:
            expected = self.minimum
            for derived in (
                self.arithmetic_mean,
                self.median,
                self.p05,
                self.p25,
                self.p75,
                self.p95,
            ):
                if not _eq_within_one_step(derived, expected):
                    raise ValueError(
                        "repeated-value summaries must equal the constant sample value "
                        "within one adjacent float step"
                    )
            if self.population_standard_deviation != 0.0:
                raise ValueError("repeated-value population standard deviation must be exactly 0.0")
        return self


class StrategyObjectiveOutcome(BaseModel):
    """One immutable empirical outcome of one strategy/objective pair.

    Binds one strategy/objective pair's outcome evidence: the
    strategy/objective sequence positions and identities, the metric
    identity and unit, the authoritative direction/target/reach-
    tolerance/weight/normalization-scale snapshots, the exact ordered
    observed values in shared-seed order together with their
    ``EmpiricalDistributionSummary``, and - when a target exists - the
    target-achievement count and empirical probability, the normalized
    target-violation distribution, the worst normalized target
    violation, and the fixed-alpha 0.95 target-violation CVaR. For
    optimization-only objectives (no target) all five targeted evidence
    fields are ``None`` while the direction-aware ``adverse_tail_statistic``
    remains mandatory.

    The normalized target violation and the target-achievement count
    are **independently recomputed here in exact seed order** from the
    frozen snapshots with the authoritative semantics:

    - ``minimize``: ``max(0, value - target) / normalization_scale``
      and ``value <= target``;
    - ``maximize``: ``max(0, target - value) / normalization_scale``
      and ``value >= target``;
    - ``reach``: ``max(0, abs(value - target) - reach_tolerance)
      / normalization_scale`` and ``abs(value - target)
      <= reach_tolerance``.

    The recomputed violation tuple must equal
    ``normalized_target_violation_distribution.ordered_samples``
    exactly, and the recomputed count and probability must equal the
    recorded fields exactly; overflow and non-finite derivations are
    rejected. The contract additionally validates the safe structural
    bounds of the evidence: the worst normalized target violation must
    equal the violation distribution maximum, the target-violation CVaR
    must be finite, non-negative, and lie between the violation
    distribution ``p95`` and the worst violation, and the adverse-tail
    statistic must lie between the arithmetic mean and the maximum for
    ``minimize``, between the minimum and the arithmetic mean for
    ``maximize``, and be non-negative for ``reach``. The two floating
    bands (the CVaR band and the adverse-tail band) use the
    deterministic one-adjacent-float-step relation so that the actual
    tail-primitive output - which can land one ULP from the exact
    rational boundary - is composable with this contract; the exact
    tail statistics themselves are owned by the accepted pure
    application primitives, and the contract validates internal
    consistency only.

    The outcome is empirical evidence only: it ranks nothing, scores
    nothing, declares no winner, prefers no strategy, creates no
    recommendation, and produces no decision brief.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    strategy_position: int = Field(ge=0)
    objective_position: int = Field(ge=0)
    strategy_candidate_id: IdentifierString
    objective_id: IdentifierString
    metric_id: IdentifierString
    metric_unit: str | None = None
    direction: Literal["minimize", "maximize", "reach"]
    target: float | None = None
    reach_tolerance: float | None = None
    weight: float = Field(ge=0.0)
    normalization_scale: float = Field(gt=0.0)
    ordered_observed_values: tuple[int | float, ...] = Field(min_length=1)
    empirical_distribution: EmpiricalDistributionSummary
    target_achievement_count: int | None = None
    empirical_target_achievement_probability: float | None = None
    normalized_target_violation_distribution: EmpiricalDistributionSummary | None = None
    worst_normalized_target_violation: float | None = None
    tail_alpha: Literal[0.95] = 0.95  # type: ignore[valid-type]
    tail_algorithm: Literal["empirical-fractional-tail-mean-v1"] = (
        "empirical-fractional-tail-mean-v1"
    )
    target_violation_cvar: float | None = None
    adverse_tail_statistic: float

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion.

        The three positions and ``target_achievement_count`` (when
        present) must have exact type ``int`` - booleans, integral
        floats, and numeric strings are rejected before pydantic could
        coerce them. ``ordered_observed_values`` follows the same exact
        finite numeric rules as ``EmpiricalDistributionSummary``. Every
        scalar numeric field must have exact raw type ``int`` or
        ``float`` and be finite; booleans, strings, ``Decimal``,
        containers, and non-finite values are rejected, and nullable
        fields may be ``None`` only where their semantic rules allow it.
        """
        if not isinstance(data, dict):
            return data
        for key in ("sequence_position", "strategy_position", "objective_position"):
            raw = data.get(key)
            if raw is not None and type(raw) is not int:
                raise ValueError(f"{key} must be an exact int")
        raw_count = data.get("target_achievement_count")
        if raw_count is not None and type(raw_count) is not int:
            raise ValueError("target_achievement_count must be an exact int when present")
        raw_values = data.get("ordered_observed_values")
        if raw_values is not None:
            _validate_exact_finite_samples(raw_values)
        for key in (
            "target",
            "reach_tolerance",
            "weight",
            "normalization_scale",
            "empirical_target_achievement_probability",
            "worst_normalized_target_violation",
            "target_violation_cvar",
            "adverse_tail_statistic",
            "tail_alpha",
        ):
            raw = data.get(key)
            if raw is None:
                continue
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    def _recomputed_normalized_violations(self) -> tuple[float, ...]:
        """The exact normalized target violation of every observed value, in seed order.

        Recomputes ``max(0, delta) / normalization_scale`` for every
        observed value in exact seed order with the authoritative
        direction semantics (minimize/maximize/reach). Arithmetic
        overflow and non-finite derivations raise ``OverflowError``.
        """
        target = self.target
        if target is None:
            raise ValueError("targeted objectives require an authoritative target")
        scale = self.normalization_scale
        tolerance = self.reach_tolerance
        direction = self.direction
        violations: list[float] = []
        for value in self.ordered_observed_values:
            try:
                if direction == "minimize":
                    delta = value - target
                elif direction == "maximize":
                    delta = target - value
                else:
                    if tolerance is None:
                        raise ValueError("reach objectives require a reach_tolerance")
                    delta = abs(value - target) - tolerance
                violation = max(0.0, delta) / scale
            except (OverflowError, ArithmeticError):
                raise OverflowError("normalized target violation derivation overflow") from None
            if not math.isfinite(violation):
                raise OverflowError("normalized target violation derivation overflow")
            violations.append(violation)
        return tuple(violations)

    def _recomputed_target_achievement_count(self) -> int:
        """The exact count of observed values that achieve the target.

        Recomputes the authoritative achievement semantics in exact seed
        order: ``value <= target`` for minimize, ``value >= target`` for
        maximize, and ``abs(value - target) <= reach_tolerance`` for
        reach.
        """
        target = self.target
        if target is None:
            raise ValueError("targeted objectives require an authoritative target")
        tolerance = self.reach_tolerance
        direction = self.direction
        count = 0
        for value in self.ordered_observed_values:
            if direction == "minimize":
                achieved = value <= target
            elif direction == "maximize":
                achieved = value >= target
            else:
                if tolerance is None:
                    raise ValueError("reach objectives require a reach_tolerance")
                achieved = abs(value - target) <= tolerance
            if achieved:
                count += 1
        return count

    @model_validator(mode="after")
    def _outcome_is_internally_consistent(self) -> StrategyObjectiveOutcome:
        """Enforce the exact outcome consistency rules.

        The empirical distribution must equal the observed values
        exactly; weight must be finite and non-negative; the
        normalization scale must be finite and strictly positive; the
        adverse-tail statistic must be finite; the alpha and algorithm
        literals must be exact. A ``reach`` objective requires a finite
        non-negative target and reach tolerance; ``minimize``/``maximize``
        must not carry a tolerance. When a target exists every targeted
        evidence field is required, the normalized violations and the
        achievement count are independently recomputed in exact seed
        order and must match the recorded fields exactly, the worst
        violation must equal the violation distribution maximum, and
        the CVaR must lie between the violation ``p95`` and the worst
        violation. When no target exists all five targeted evidence
        fields must be ``None``.
        """
        if self.empirical_distribution.ordered_samples != self.ordered_observed_values:
            raise ValueError(
                "empirical_distribution.ordered_samples must equal ordered_observed_values exactly"
            )
        if self.empirical_distribution.sample_count != len(self.ordered_observed_values):
            raise ValueError(
                "empirical_distribution.sample_count must equal the observed sample count"
            )
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise ValueError("weight must be finite and non-negative")
        if not math.isfinite(self.normalization_scale) or self.normalization_scale <= 0.0:
            raise ValueError("normalization_scale must be finite and strictly positive")
        if not math.isfinite(self.adverse_tail_statistic):
            raise ValueError("adverse_tail_statistic must be finite")
        if self.tail_alpha != 0.95:
            raise ValueError("tail_alpha must be exactly 0.95")
        if self.tail_algorithm != "empirical-fractional-tail-mean-v1":
            raise ValueError("tail_algorithm must be the exact supported literal")

        sample_count = len(self.ordered_observed_values)
        if self.direction == "reach":
            if self.target is None:
                raise ValueError("reach objectives require an authoritative target")
            if self.reach_tolerance is None:
                raise ValueError("reach objectives require a reach_tolerance")
            if not math.isfinite(self.reach_tolerance) or self.reach_tolerance < 0.0:
                raise ValueError("reach_tolerance must be finite and non-negative")
        elif self.reach_tolerance is not None:
            raise ValueError("reach_tolerance is forbidden for minimize and maximize")
        if self.target is not None and not math.isfinite(self.target):
            raise ValueError("target must be finite when present")

        target = self.target
        if target is not None:
            count = self.target_achievement_count
            probability = self.empirical_target_achievement_probability
            violation_distribution = self.normalized_target_violation_distribution
            worst = self.worst_normalized_target_violation
            cvar = self.target_violation_cvar
            if count is None or probability is None:
                raise ValueError("targeted objectives require the target-achievement fields")
            if violation_distribution is None or worst is None or cvar is None:
                raise ValueError("targeted objectives require the target-violation evidence fields")
            try:
                recomputed_violations = self._recomputed_normalized_violations()
            except (OverflowError, ArithmeticError):
                raise ValueError("normalized target violation derivation overflow") from None
            if recomputed_violations != violation_distribution.ordered_samples:
                raise ValueError(
                    "normalized_target_violation_distribution must equal the exact "
                    "seed-order recomputation"
                )
            recomputed_count = self._recomputed_target_achievement_count()
            if recomputed_count != count:
                raise ValueError("target_achievement_count must equal the exact recomputed count")
            if count < 0 or count > sample_count:
                raise ValueError("target_achievement_count must be between 0 and the sample count")
            expected_probability = count / sample_count
            if probability != expected_probability:
                raise ValueError(
                    "empirical_target_achievement_probability must equal "
                    "target_achievement_count / sample_count"
                )
            if probability < 0.0 or probability > 1.0:
                raise ValueError(
                    "empirical_target_achievement_probability must be within [0.0, 1.0]"
                )
            if violation_distribution.sample_count != sample_count:
                raise ValueError(
                    "the normalized target violation distribution must match the "
                    "observed sample count"
                )
            if any(sample < 0.0 for sample in violation_distribution.ordered_samples):
                raise ValueError("normalized target violations must be non-negative")
            if worst != violation_distribution.maximum:
                raise ValueError(
                    "worst_normalized_target_violation must equal the violation "
                    "distribution maximum"
                )
            if worst < 0.0:
                raise ValueError("worst_normalized_target_violation must be non-negative")
            if not math.isfinite(cvar) or cvar < 0.0:
                raise ValueError("target_violation_cvar must be finite and non-negative")
            if not _leq_within_one_step(
                violation_distribution.p95, cvar
            ) or not _leq_within_one_step(cvar, worst):
                raise ValueError(
                    "target_violation_cvar must lie between the violation distribution "
                    "p95 and the worst normalized target violation"
                )
        else:
            if self.direction == "reach":
                raise ValueError("reach objectives require an authoritative target")
            if (
                self.target_achievement_count is not None
                or self.empirical_target_achievement_probability is not None
                or self.normalized_target_violation_distribution is not None
                or self.worst_normalized_target_violation is not None
                or self.target_violation_cvar is not None
            ):
                raise ValueError("targeted evidence fields must be None when no target exists")

        if self.direction == "minimize":
            if not _leq_within_one_step(
                self.empirical_distribution.arithmetic_mean, self.adverse_tail_statistic
            ) or not _leq_within_one_step(
                self.adverse_tail_statistic, self.empirical_distribution.maximum
            ):
                raise ValueError(
                    "adverse_tail_statistic must lie between the arithmetic mean and "
                    "the maximum for minimize"
                )
        elif self.direction == "maximize":
            if not _leq_within_one_step(
                self.empirical_distribution.minimum, self.adverse_tail_statistic
            ) or not _leq_within_one_step(
                self.adverse_tail_statistic, self.empirical_distribution.arithmetic_mean
            ):
                raise ValueError(
                    "adverse_tail_statistic must lie between the minimum and the "
                    "arithmetic mean for maximize"
                )
        else:
            if self.adverse_tail_statistic < 0.0:
                raise ValueError("adverse_tail_statistic must be non-negative for reach")
        return self


class CampaignOutcomeDistributionMatrix(VersionedContract):
    """The deterministic campaign-level empirical outcome-distribution matrix.

    The immutable, tenant-scoped top-level artifact binding one
    completed runtime-3.0.0 campaign's complete per-strategy/per-
    objective empirical outcome evidence: the campaign/scenario/world
    identity with the scenario and world content hashes, the recorded
    runtime version (always ``"3.0.0"``) and comparison mode (always
    ``identical_conditions``), the evaluation-profile reference, the
    uncertainty-model reference (both identity and content hash, or
    neither), the two exact source references (the world-realization
    matrix and the runtime-3 metric-observation matrix), the exact
    ordered strategy, seed, objective, and metric identifiers, and the
    complete strategy-major, objective-minor outcome tuple with
    contiguous sequence positions and exact identity-vs-position
    agreement.

    The contract enforces the structural shape only: both-or-neither
    uncertainty provenance; unique strategy/seed/objective/metric
    identifiers; strictly increasing metric identifiers; exactly one
    outcome per strategy x objective pair in the exact strategy-major,
    objective-minor order; every outcome's sequence position equal to
    its tuple position, positions in range, identities matching their
    positions, metric present in the ordered metric collection, and
    observed-value and empirical-summary counts equal to the seed
    count; and identical authoritative objective/binding snapshots
    (objective, metric, unit, direction, target, tolerance, weight,
    scale) across every strategy of the same objective - while the
    outcome evidence values themselves may legitimately differ across
    strategies.

    Deterministic identifier derivation, content-hash recomputation,
    source-artifact hash verification, sample-to-seed provenance,
    evaluation-profile integrity, and tenant-ownership verification
    beyond the inherited field belong to the application layer and are
    deliberately not performed here. The matrix is declarative data
    only: nothing here builds, verifies, queries, stores, reads a
    clock, samples, executes, replays, ranks, scores, declares a
    winner, prefers, or recommends a strategy, and no field type can
    express a callback, expression, formula, code reference, provider,
    or executable mechanism.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    evaluation_profile_id: IdentifierString
    evaluation_profile_content_hash: Sha256Hex
    uncertainty_model_id: IdentifierString | None = None
    uncertainty_model_content_hash: Sha256Hex | None = None
    source_world_realization_matrix_id: IdentifierString
    source_world_realization_matrix_content_hash: Sha256Hex
    source_metric_observation_matrix_id: IdentifierString
    source_metric_observation_matrix_content_hash: Sha256Hex
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_objective_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_metric_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    outcomes: tuple[StrategyObjectiveOutcome, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    derived_at: AwareDatetime

    @model_validator(mode="after")
    def _matrix_structural_shape(self) -> CampaignOutcomeDistributionMatrix:
        """Enforce the exact structural shape of the outcome matrix.

        The uncertainty provenance must be both present or both
        absent; strategy, seed, objective, and metric identifiers must
        each be unique; metric identifiers must be strictly increasing;
        the outcomes must contain exactly one entry per strategy x
        objective pair in the exact strategy-major, objective-minor
        order with contiguous sequence positions and exact identity-vs-
        position agreement; every outcome's metric must exist in the
        ordered metric collection and its observed-value and empirical-
        summary counts must equal the seed count; and every strategy
        must carry identical objective/binding snapshots for the same
        objective position. Outcome evidence values are allowed to
        differ across strategies. Identity derivation, content-hash
        recomputation, and source verification are intentionally out of
        scope here.
        """
        if (self.uncertainty_model_id is None) != (self.uncertainty_model_content_hash is None):
            raise ValueError(
                "uncertainty_model_id and uncertainty_model_content_hash must both be "
                "present or both be absent"
            )
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        objective_ids = list(self.ordered_objective_ids)
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("ordered_objective_ids must be unique")
        metric_ids = list(self.ordered_metric_ids)
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("ordered_metric_ids must be unique")
        if any(a >= b for a, b in zip(metric_ids, metric_ids[1:], strict=False)):
            raise ValueError("ordered_metric_ids must be strictly increasing")

        objective_count = len(objective_ids)
        seed_count = len(seed_ids)
        expected_count = len(strategy_ids) * objective_count
        if len(self.outcomes) != expected_count:
            raise ValueError("outcomes must cover every strategy x objective pair exactly once")

        seen_pairs: set[tuple[int, int]] = set()
        for position, outcome in enumerate(self.outcomes):
            if outcome.strategy_position >= len(strategy_ids):
                raise ValueError("outcome strategy position out of range")
            if outcome.objective_position >= objective_count:
                raise ValueError("outcome objective position out of range")
            pair = (outcome.strategy_position, outcome.objective_position)
            if pair in seen_pairs:
                raise ValueError("duplicate strategy x objective outcome")
            seen_pairs.add(pair)
            expected_index = (
                outcome.strategy_position * objective_count + outcome.objective_position
            )
            if outcome.sequence_position != position:
                raise ValueError("outcome sequence_position must equal its tuple position")
            if expected_index != position:
                raise ValueError(
                    "outcomes must be contiguous in the exact strategy-major, objective-minor order"
                )
            if outcome.strategy_candidate_id != strategy_ids[outcome.strategy_position]:
                raise ValueError("outcome strategy identity does not match its strategy position")
            if outcome.objective_id != objective_ids[outcome.objective_position]:
                raise ValueError("outcome objective identity does not match its objective position")
            if outcome.metric_id not in metric_ids:
                raise ValueError("outcome metric_id must exist in ordered_metric_ids")
            if len(outcome.ordered_observed_values) != seed_count:
                raise ValueError("outcome ordered_observed_values length must equal the seed count")
            if outcome.empirical_distribution.sample_count != seed_count:
                raise ValueError(
                    "outcome empirical_distribution.sample_count must equal the seed count"
                )

        for objective_position in range(objective_count):
            reference = self.outcomes[objective_position]
            for strategy_position in range(len(strategy_ids)):
                outcome = self.outcomes[strategy_position * objective_count + objective_position]
                if outcome.metric_id != reference.metric_id:
                    raise ValueError(
                        "every strategy must carry identical metric_id for the same objective"
                    )
                if outcome.metric_unit != reference.metric_unit:
                    raise ValueError(
                        "every strategy must carry identical metric_unit for the same objective"
                    )
                if outcome.direction != reference.direction:
                    raise ValueError(
                        "every strategy must carry identical direction for the same objective"
                    )
                if outcome.target != reference.target:
                    raise ValueError(
                        "every strategy must carry identical target for the same objective"
                    )
                if outcome.reach_tolerance != reference.reach_tolerance:
                    raise ValueError(
                        "every strategy must carry identical reach_tolerance for the same objective"
                    )
                if outcome.weight != reference.weight:
                    raise ValueError(
                        "every strategy must carry identical weight for the same objective"
                    )
                if outcome.normalization_scale != reference.normalization_scale:
                    raise ValueError(
                        "every strategy must carry identical normalization_scale "
                        "for the same objective"
                    )
        return self


__all__ = [
    "EmpiricalDistributionSummary",
    "StrategyObjectiveOutcome",
    "CampaignOutcomeDistributionMatrix",
]
