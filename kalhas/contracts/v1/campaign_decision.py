"""Immutable declarative campaign decision artifacts (KALHAS).

This module defines the immutable, domain-neutral declarative contract
surface of the campaign decision pipeline: the stored decision policy
(``CampaignDecisionPolicy``), the derived ordered-pair strategy
comparison (``CampaignStrategyComparison``), and the derived auditable
campaign decision brief (``CampaignDecisionBrief``), together with
their nested immutable evidence records.

The three top-level artifacts are strict and frozen
(``extra="forbid"``), inherit the versioned-contract identity fields,
and self-cover their complete content with a canonical SHA-256
``content_hash``. Every numeric field follows the exact built-in
numeric input policy: only raw ``int`` and ``float`` values are
accepted, booleans, strings, ``Decimal``, ``None``, containers,
non-finite floats, and unrepresentable huge integers are rejected
before any coercion, and nothing is clipped, repaired, normalized, or
mutated. Cross-field rules that can be proven from the contract itself
(ordered-pair cardinality and ordering, reverse-pair delta/count/
quantile/extrema mirrors, feasibility/dominance/status consistency,
reason/factor catalogue compatibility, both-or-neither provenance) are
enforced here; source-authority and recomputation checks that require
repository records (profile coverage, recorded hashes, recomputed
evidence) belong to the pure application builders and services and are
deliberately not faked here.

The policy binds the campaign/scenario/world/evaluation-profile
identity with content hashes, the accepted algorithm identifier, the
exact global-or-per-objective target-requirement mode with its
probability rules, the fixed CVaR tail alpha (exactly ``0.95``;
callers cannot select another alpha), the exact-int minimum sample
count, the finite non-negative tie tolerance, the hard-gate flag, the
authoritative objective-weight snapshot (one immutable
``ObjectiveWeightSnapshot`` per authoritative objective, unique and in
the exact supplied authoritative order, never sorted and never
normalized), and deterministic metadata. The policy is declarative data only: no callbacks,
expressions, scripts, templates, provider references, plugins,
executable formulas, or arbitrary code references are representable,
and no request, service, store, or API surface exists here.

The comparison carries the complete ordered-pair matrix with the
exact cardinality ``S * (S - 1) * O`` (no self-pairs, both directions
of every pair, every objective), the exact deterministic
pair-major/objective-minor ordering formula, the reverse-pair
structural invariants, the per-pair dominance relations with
per-objective statuses, and one robustness profile per strategy. The
brief carries exactly one of the four accepted statuses, an optional
preferred strategy id present only for ``preferred`` and only when it
is a considered strategy, one terminal reason whose code matches the
status, ordered decisive and blocking factors from a closed code
catalogue, the copied robustness profiles, the authoritative declared
assumptions, complete evidence references, and a deterministic
factual summary. Nothing here generates narrative, chain-of-thought,
hidden reasoning, arbitrary prose, or an unexplained scalar score.

The module is domain-neutral and declarative: it imports only the
Python standard library, pydantic, and the shared v1 contract module,
reads no wall clock, uses no randomness, network, providers,
filesystem, store, API, adapters, or domain packs, and exposes no
callback, expression, or executable surface.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import (
    Assumption,
    AwareDatetime,
    JsonValue,
    VersionedContract,
)

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: The accepted comparison algorithm identifier (closed literal).
_ALGORITHM_IDENTIFIER: Literal["feasibility-pareto-minimax-regret-v1"] = (
    "feasibility-pareto-minimax-regret-v1"
)


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


def _validate_exact_finite_values(values: object) -> None:
    """Reject any collection that is not a tuple/list of exact finite numerics.

    Like :func:`_validate_exact_finite_samples` but the collection may
    be empty; used for the positional structured value tuples of the
    reason/factor records.
    """
    if not isinstance(values, (list, tuple)):
        raise ValueError("structured values must be a tuple or list")
    for value in values:
        if not _is_exact_finite_numeric(value):
            raise ValueError("every structured value must be an exact finite int or float")


def _require_exact_int(value: object, name: str) -> None:
    """Require an exact ``int`` (never ``bool``, float, or string) raw value."""
    if type(value) is not int:
        raise ValueError(f"{name} must be an exact int")


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


def _contains_non_finite(value: object) -> bool:
    """True when any nested ``float`` inside a JSON-like tree is non-finite."""
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_non_finite(item) for item in value.values())
    return False


def _is_probability(value: float) -> bool:
    """True for a finite probability within the inclusive ``[0.0, 1.0]`` band."""
    return math.isfinite(value) and 0.0 <= value <= 1.0


class ObjectiveWeightSnapshot(BaseModel):
    """One immutable authoritative objective-weight snapshot.

    Binds one authoritative objective identifier to its declared
    weight. Weights are exact finite non-negative built-in numerics;
    they are never normalized or renormalized anywhere, and an
    all-zero weight collection remains representable. The complete
    ordered snapshot (one entry per authoritative objective, unique,
    in the exact supplied authoritative order - the order is
    preserved, never sorted) is a policy-level rule; completeness and
    source verification against the authoritative scenario/
    evaluation-profile record belong to the future policy service.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    weight: float

    @model_validator(mode="before")
    @classmethod
    def _raw_weight_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw = data.get("weight")
        if raw is not None and not _is_exact_finite_numeric(raw):
            raise ValueError("weight must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _weight_is_non_negative(self) -> ObjectiveWeightSnapshot:
        """Enforce the exact finite non-negative weight rule."""
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise ValueError("weight must be finite and non-negative")
        return self


class ObjectiveTargetRequirement(BaseModel):
    """One immutable per-objective target-achievement requirement.

    Binds one targeted objective identifier to its minimum empirical
    target-achievement probability threshold, inclusive on both
    boundaries of ``[0.0, 1.0]``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    minimum_target_achievement_probability: float

    @model_validator(mode="before")
    @classmethod
    def _raw_probability_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw = data.get("minimum_target_achievement_probability")
        if raw is not None and not _is_exact_finite_numeric(raw):
            raise ValueError(
                "minimum_target_achievement_probability must be an exact finite int or float"
            )
        return data

    @model_validator(mode="after")
    def _probability_within_unit_band(self) -> ObjectiveTargetRequirement:
        """Enforce the inclusive probability band."""
        if not _is_probability(self.minimum_target_achievement_probability):
            raise ValueError("minimum_target_achievement_probability must be within [0.0, 1.0]")
        return self


class ObjectivePairedComparison(BaseModel):
    """One immutable ordered-pair/objective paired comparison.

    Binds one ordered strategy pair and one objective to the exact
    ordered paired deltas in authoritative shared-seed order, the
    decomposed win/tie/loss counts and rates under the declared tie
    tolerance, and the median/p05/p95/worst/best paired deltas.
    Positive deltas always mean the first strategy is worse after
    direction normalization; negative means better; values within the
    declared tolerance are ties.

    The contract independently recomputes the win/tie/loss counts from
    the recorded deltas and the recorded tolerance with the exact
    boundary semantics (``d < -tol`` win, ``|d| <= tol`` tie,
    ``d > +tol`` loss), requires the rates to equal ``count / K``
    exactly, the worst/best deltas to equal the recorded maxima/
    minima exactly, and the median/p05/p95 to lie within the extrema
    under the deterministic one-adjacent-float-step relation. The
    reverse-pair mirrors (exact IEEE delta negation, count mirrors,
    quantile/extrema mirrors) are enforced at the comparison level,
    where both directions are present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    first_strategy_position: int = Field(ge=0)
    second_strategy_position: int = Field(ge=0)
    first_strategy_candidate_id: IdentifierString
    second_strategy_candidate_id: IdentifierString
    objective_position: int = Field(ge=0)
    objective_id: IdentifierString
    metric_id: IdentifierString
    tie_tolerance: float
    ordered_paired_deltas: tuple[float, ...] = Field(min_length=1)
    win_count: int = Field(ge=0)
    tie_count: int = Field(ge=0)
    loss_count: int = Field(ge=0)
    win_rate: float
    tie_rate: float
    loss_rate: float
    median_paired_delta: float
    p05_paired_delta: float
    p95_paired_delta: float
    worst_paired_delta: float
    best_paired_delta: float

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        for key in (
            "sequence_position",
            "first_strategy_position",
            "second_strategy_position",
            "objective_position",
            "win_count",
            "tie_count",
            "loss_count",
        ):
            raw = data.get(key)
            if raw is not None:
                _require_exact_int(raw, key)
        raw_deltas = data.get("ordered_paired_deltas")
        if raw_deltas is not None:
            _validate_exact_finite_samples(raw_deltas)
        for key in (
            "tie_tolerance",
            "win_rate",
            "tie_rate",
            "loss_rate",
            "median_paired_delta",
            "p05_paired_delta",
            "p95_paired_delta",
            "worst_paired_delta",
            "best_paired_delta",
        ):
            raw = data.get(key)
            if raw is not None and not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _paired_comparison_is_internally_consistent(self) -> ObjectivePairedComparison:
        """Enforce the exact paired-comparison consistency rules.

        The first and second strategy positions must differ; the
        recorded win/tie/loss counts must equal the exact recomputation
        over the recorded deltas under the recorded tolerance
        (``d < -tol`` win, ``|d| <= tol`` tie, ``d > +tol`` loss); the
        counts must sum to the delta count; the rates must equal
        ``count / K`` exactly; the worst/best paired deltas must equal
        the recorded maxima/minima exactly; and the median/p05/p95
        must lie within the extrema under the deterministic
        one-adjacent-float-step relation. The tie tolerance must be
        finite and non-negative. Source-level verification (the
        tolerance matching the stored policy, the seed alignment with
        the outcome matrix) belongs to the comparison contract and the
        application builders.
        """
        if self.first_strategy_position == self.second_strategy_position:
            raise ValueError("paired comparison requires two distinct strategies")
        if self.first_strategy_candidate_id == self.second_strategy_candidate_id:
            raise ValueError("paired comparison strategy identities must differ")
        if not math.isfinite(self.tie_tolerance) or self.tie_tolerance < 0.0:
            raise ValueError("tie_tolerance must be finite and non-negative")
        sample_count = len(self.ordered_paired_deltas)
        wins = ties = losses = 0
        for delta in self.ordered_paired_deltas:
            if delta < -self.tie_tolerance:
                wins += 1
            elif delta > self.tie_tolerance:
                losses += 1
            else:
                ties += 1
        if wins != self.win_count or ties != self.tie_count or losses != self.loss_count:
            raise ValueError("win/tie/loss counts must equal the exact tolerance recomputation")
        if self.win_count + self.tie_count + self.loss_count != sample_count:
            raise ValueError("win/tie/loss counts must sum to the delta count")
        if self.win_rate != self.win_count / sample_count:
            raise ValueError("win_rate must equal win_count / delta count exactly")
        if self.tie_rate != self.tie_count / sample_count:
            raise ValueError("tie_rate must equal tie_count / delta count exactly")
        if self.loss_rate != self.loss_count / sample_count:
            raise ValueError("loss_rate must equal loss_count / delta count exactly")
        if self.worst_paired_delta != max(self.ordered_paired_deltas):
            raise ValueError("worst_paired_delta must equal the exact recorded maximum")
        if self.best_paired_delta != min(self.ordered_paired_deltas):
            raise ValueError("best_paired_delta must equal the exact recorded minimum")
        for derived in (
            self.win_rate,
            self.tie_rate,
            self.loss_rate,
            self.median_paired_delta,
            self.p05_paired_delta,
            self.p95_paired_delta,
            self.worst_paired_delta,
            self.best_paired_delta,
        ):
            if not math.isfinite(derived):
                raise ValueError("every derived paired-delta value must be finite")
        for derived in (self.median_paired_delta, self.p05_paired_delta, self.p95_paired_delta):
            if not _leq_within_one_step(
                self.best_paired_delta, derived
            ) or not _leq_within_one_step(derived, self.worst_paired_delta):
                raise ValueError(
                    "median/p05/p95 paired deltas must lie within the paired-delta extrema"
                )
        return self


class ObjectiveFeasibilityEvidence(BaseModel):
    """One immutable per-objective target-feasibility evidence record.

    Binds one targeted objective to its declared threshold and the
    observed empirical target-achievement probability; ``passed``
    means exactly the comparison ``observed_probability >= threshold``
    and nothing else. The pipeline feasibility flag is the profile's
    ``feasible`` field, which this nested record cannot derive - the
    policy hard-gate flag lives on the stored policy, outside the
    nested evidence scope; the future builder verifies ``feasible ==
    (hard gates disabled or every targeted requirement passed)``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    threshold: float
    observed_probability: float
    passed: bool

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        for key in ("threshold", "observed_probability"):
            raw = data.get(key)
            if raw is not None and not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _feasibility_evidence_is_consistent(self) -> ObjectiveFeasibilityEvidence:
        """Enforce the exact threshold/probability/passed rules."""
        if not _is_probability(self.threshold):
            raise ValueError("threshold must be within [0.0, 1.0]")
        if not _is_probability(self.observed_probability):
            raise ValueError("observed_probability must be within [0.0, 1.0]")
        if self.passed != (self.observed_probability >= self.threshold):
            raise ValueError("passed must equal observed_probability >= threshold")
        return self


class ObjectiveRegretEvidence(BaseModel):
    """One immutable per-objective weighted-regret evidence record.

    Binds one objective to its finite non-negative weighted regret.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    weighted_regret: float

    @model_validator(mode="before")
    @classmethod
    def _raw_regret_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw = data.get("weighted_regret")
        if raw is not None and not _is_exact_finite_numeric(raw):
            raise ValueError("weighted_regret must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _regret_is_non_negative(self) -> ObjectiveRegretEvidence:
        """Enforce the exact finite non-negative weighted-regret rule."""
        if not math.isfinite(self.weighted_regret) or self.weighted_regret < 0.0:
            raise ValueError("weighted_regret must be finite and non-negative")
        return self


class ObjectiveProbabilityEvidence(BaseModel):
    """One immutable per-objective target-achievement probability record.

    Copies the empirical target-achievement probability from the
    verified outcome matrix; it is supporting evidence only and is
    never part of a dominance test.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    empirical_target_achievement_probability: float

    @model_validator(mode="before")
    @classmethod
    def _raw_probability_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw = data.get("empirical_target_achievement_probability")
        if raw is not None and not _is_exact_finite_numeric(raw):
            raise ValueError(
                "empirical_target_achievement_probability must be an exact finite int or float"
            )
        return data

    @model_validator(mode="after")
    def _probability_within_unit_band(self) -> ObjectiveProbabilityEvidence:
        """Enforce the inclusive probability band."""
        if not _is_probability(self.empirical_target_achievement_probability):
            raise ValueError("empirical_target_achievement_probability must be within [0.0, 1.0]")
        return self


class ObjectiveDownsideEvidence(BaseModel):
    """One immutable per-objective downside-risk evidence record.

    Copies the worst normalized target violation, the fixed-alpha
    target-violation CVaR, and the direction-aware adverse-tail
    statistic from the verified outcome matrix; it is supporting
    evidence only and is never part of a dominance test. The worst
    violation and the CVaR are both present or both absent (they are
    absent for optimization-only objectives), and every present value
    is finite and non-negative.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    worst_normalized_target_violation: float | None = None
    target_violation_cvar: float | None = None
    adverse_tail_statistic: float

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        for key in ("worst_normalized_target_violation", "target_violation_cvar"):
            raw = data.get(key)
            if raw is not None and not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite int or float when present")
        raw_adverse = data.get("adverse_tail_statistic")
        if raw_adverse is not None and not _is_exact_finite_numeric(raw_adverse):
            raise ValueError("adverse_tail_statistic must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _downside_evidence_is_consistent(self) -> ObjectiveDownsideEvidence:
        """Enforce the both-or-neither and non-negative downside rules."""
        if (self.worst_normalized_target_violation is None) != (self.target_violation_cvar is None):
            raise ValueError(
                "worst_normalized_target_violation and target_violation_cvar must both be "
                "present or both be absent"
            )
        if not math.isfinite(self.adverse_tail_statistic):
            raise ValueError("adverse_tail_statistic must be finite")
        for value in (self.worst_normalized_target_violation, self.target_violation_cvar):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError(
                    "worst_normalized_target_violation and target_violation_cvar must be "
                    "finite and non-negative when present"
                )
        return self


class ObjectiveDominanceStatus(BaseModel):
    """One immutable per-objective dominance status for one ordered strategy pair.

    Reads the win/tie/loss counts and the median paired delta from the
    stored forward paired comparison of the same ordered pair and
    objective. The status is derived from the recorded counts with the
    exact algorithm semantics: ``worse`` requires at least one loss
    (the first strategy is not no-worse), ``better`` requires no
    losses and at least one win (no-worse and strictly better), and
    ``tied`` requires no wins and no losses (every paired delta within
    the tolerance).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    status: Literal["better", "tied", "worse"]
    win_count: int = Field(ge=0)
    tie_count: int = Field(ge=0)
    loss_count: int = Field(ge=0)
    median_paired_delta: float

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        for key in ("win_count", "tie_count", "loss_count"):
            raw = data.get(key)
            if raw is not None:
                _require_exact_int(raw, key)
        raw_median = data.get("median_paired_delta")
        if raw_median is not None and not _is_exact_finite_numeric(raw_median):
            raise ValueError("median_paired_delta must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _status_matches_recorded_counts(self) -> ObjectiveDominanceStatus:
        """Enforce the exact status-vs-counts derivation rules."""
        if not math.isfinite(self.median_paired_delta):
            raise ValueError("median_paired_delta must be finite")
        if self.status == "worse":
            if self.loss_count <= 0:
                raise ValueError("worse status requires at least one loss")
        elif self.status == "better":
            if self.loss_count != 0 or self.win_count <= 0:
                raise ValueError("better status requires no losses and at least one win")
        else:
            if self.win_count != 0 or self.loss_count != 0 or self.tie_count <= 0:
                raise ValueError("tied status requires every paired delta to be a tie")
        return self


class DominanceRelation(BaseModel):
    """One immutable dominance relation for one ordered strategy pair.

    Binds one ordered strategy pair to its dominance flag and its
    per-objective statuses. The first strategy dominates the second
    exactly when no per-objective status is ``worse`` and at least one
    status is ``better`` (no-worse everywhere, strictly better in at
    least one required measure). The reverse pair carries its own
    stored relation; silent reconstruction is forbidden.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_strategy_position: int = Field(ge=0)
    second_strategy_position: int = Field(ge=0)
    first_strategy_candidate_id: IdentifierString
    second_strategy_candidate_id: IdentifierString
    dominates: bool
    per_objective_status: tuple[ObjectiveDominanceStatus, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _raw_positions_must_be_exact_int(cls, data: Any) -> Any:
        """Reject non-integer raw values on the un-coerced input, before any coercion.

        Both strategy positions accept an exact built-in ``int`` only;
        booleans, floats (including integral floats), strings,
        ``Decimal``, ``None``, and containers are rejected, and the
        non-negative constraint is enforced by the field bounds.
        """
        if not isinstance(data, dict):
            return data
        for key in ("first_strategy_position", "second_strategy_position"):
            raw = data.get(key)
            if raw is not None:
                _require_exact_int(raw, key)
        return data

    @model_validator(mode="after")
    def _dominance_relation_is_consistent(self) -> DominanceRelation:
        """Enforce the exact dominance derivation and per-objective coverage rules.

        The two strategy positions and identities must differ; the
        per-objective statuses must carry unique objective identifiers;
        and the dominance flag must equal the exact derivation over
        the statuses (no ``worse`` status and at least one ``better``
        status). The complete ordered-pair coverage, identity-vs-
        position agreement, and independent reverse status derivation
        (from each direction's own mirrored counts) are enforced at
        the comparison level.
        """
        if self.first_strategy_position == self.second_strategy_position:
            raise ValueError("dominance relation requires two distinct strategies")
        if self.first_strategy_candidate_id == self.second_strategy_candidate_id:
            raise ValueError("dominance relation strategy identities must differ")
        objective_ids = [status.objective_id for status in self.per_objective_status]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("per_objective_status objective identifiers must be unique")
        statuses = [status.status for status in self.per_objective_status]
        expected = "worse" not in statuses and "better" in statuses
        if self.dominates != expected:
            raise ValueError(
                "dominates must be true exactly when no objective is worse and at least one "
                "is better"
            )
        return self


class StrategyRobustnessProfile(BaseModel):
    """One immutable robustness profile for one strategy.

    Binds one strategy to its pipeline feasibility flag, its ordered
    per-objective feasibility evidence, its ordered dominance
    relations (dominated-by and dominates identifiers in authoritative
    strategy order, cross-checked against the stored dominance
    relations at the comparison level), its per-objective weighted
    regrets, its exact ordered per-seed total weighted regrets with
    the maximum/median/p95 aggregates, and the copied per-objective
    target-achievement probability and downside-risk evidence from the
    verified outcome matrix.

    ``feasible`` is the pipeline result. The nested evidence cannot
    derive it: the policy hard-gate flag lives on the stored policy,
    outside the profile's scope, so the contract deliberately does not
    tie ``feasible`` to the recorded ``passed`` flags (hard gates
    disabled make the test vacuous). The future builder verifies
    ``feasible == (hard gates disabled or every targeted requirement
    passed)``.

    The maximum total weighted regret must equal the exact recorded
    maximum of the ordered per-seed totals; the median and p95 must
    lie within the totals extrema under the deterministic
    one-adjacent-float-step relation; every per-seed total must be
    finite and non-negative. The comparison contract enforces the
    full-coverage per-objective tuple order (weighted regret and
    downside evidence cover every objective exactly once in objective
    order) and the target-only tuple rules (feasibility and
    achievement probabilities cover targeted objectives only, as
    identical subsets in relative objective order).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_position: int = Field(ge=0)
    strategy_candidate_id: IdentifierString
    feasible: bool
    target_feasibility: tuple[ObjectiveFeasibilityEvidence, ...] = Field(default_factory=tuple)
    dominated_by: tuple[IdentifierString, ...] = Field(default_factory=tuple)
    dominates: tuple[IdentifierString, ...] = Field(default_factory=tuple)
    per_objective_weighted_regret: tuple[ObjectiveRegretEvidence, ...] = Field(
        default_factory=tuple
    )
    per_seed_total_weighted_regrets: tuple[float, ...] = Field(min_length=1)
    median_total_weighted_regret: float
    p95_total_weighted_regret: float
    maximum_total_weighted_regret: float
    target_achievement_probabilities: tuple[ObjectiveProbabilityEvidence, ...] = Field(
        default_factory=tuple
    )
    downside_evidence: tuple[ObjectiveDownsideEvidence, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_position = data.get("strategy_position")
        if raw_position is not None:
            _require_exact_int(raw_position, "strategy_position")
        raw_totals = data.get("per_seed_total_weighted_regrets")
        if raw_totals is not None:
            _validate_exact_finite_samples(raw_totals)
        for key in (
            "median_total_weighted_regret",
            "p95_total_weighted_regret",
            "maximum_total_weighted_regret",
        ):
            raw = data.get(key)
            if raw is not None and not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _profile_is_internally_consistent(self) -> StrategyRobustnessProfile:
        """Enforce the exact regret and dominance-list rules.

        The feasibility flag is the pipeline result and is deliberately
        not derived from the recorded ``passed`` flags here - the
        hard-gate flag lives on the stored policy, outside the nested
        evidence scope (see the class documentation); every per-seed
        total weighted regret must be finite and non-negative; the
        maximum total weighted regret must equal the exact recorded
        maximum; the median and p95 must lie within the totals extrema
        under the deterministic one-adjacent-float-step relation with
        the median never above the p95; every per-objective evidence
        collection must carry unique objective identifiers; and the
        dominated-by/dominates identifier collections must be unique,
        ordered, disjoint, and never contain the strategy itself. The
        comparison contract cross-checks the collections against the
        stored dominance relations, the full-coverage per-objective
        order, and the target-only tuple rules.
        """
        for totals_key in (
            "target_feasibility",
            "per_objective_weighted_regret",
            "target_achievement_probabilities",
            "downside_evidence",
        ):
            records = getattr(self, totals_key)
            objective_ids = [record.objective_id for record in records]
            if len(objective_ids) != len(set(objective_ids)):
                raise ValueError(f"{totals_key} objective identifiers must be unique")
        if any(
            not math.isfinite(total) or total < 0.0
            for total in self.per_seed_total_weighted_regrets
        ):
            raise ValueError("per_seed_total_weighted_regrets must be finite and non-negative")
        if self.maximum_total_weighted_regret != max(self.per_seed_total_weighted_regrets):
            raise ValueError("maximum_total_weighted_regret must equal the exact recorded maximum")
        totals_minimum = min(self.per_seed_total_weighted_regrets)
        for derived in (self.median_total_weighted_regret, self.p95_total_weighted_regret):
            if not math.isfinite(derived) or derived < 0.0:
                raise ValueError("median/p95 total weighted regret must be finite and non-negative")
            if not _leq_within_one_step(totals_minimum, derived) or not _leq_within_one_step(
                derived, self.maximum_total_weighted_regret
            ):
                raise ValueError(
                    "median/p95 total weighted regret must lie within the per-seed extrema"
                )
        if not _leq_within_one_step(
            self.median_total_weighted_regret, self.p95_total_weighted_regret
        ):
            raise ValueError("median total weighted regret must never exceed the p95")
        for collection_name in ("dominated_by", "dominates"):
            identifiers = list(getattr(self, collection_name))
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{collection_name} identifiers must be unique")
            if self.strategy_candidate_id in identifiers:
                raise ValueError(f"{collection_name} must not contain the strategy itself")
        if set(self.dominated_by) & set(self.dominates):
            raise ValueError("dominated_by and dominates must be disjoint")
        return self


#: The closed terminal-reason code catalogue (exactly one per brief).
DecisionReasonCode = Literal[
    "unique_minimax_preference",
    "regret_tie_within_tolerance",
    "insufficient_seed_samples",
    "no_feasible_strategy",
]


class DecisionReasonRecord(BaseModel):
    """One immutable terminal decision-reason record.

    Binds one closed reason code to its positional structured values
    and optional related strategy identifiers. The exact code-to-status
    compatibility is enforced at the brief level; here each code's
    positional value shape is enforced: ``unique_minimax_preference``
    and ``regret_tie_within_tolerance`` carry two finite non-negative
    values ``[best_max_total_weighted_regret, tie_tolerance]`` (the
    latter additionally requires non-empty related strategy ids),
    while ``insufficient_seed_samples`` and ``no_feasible_strategy``
    carry two exact non-negative integer counts
    ``[declared_minimum_sample_count, recorded_seed_count]`` and
    ``[considered_count, feasible_count]``. The strategy id of a
    unique minimax preference is the brief's ``preferred_strategy_id``,
    never duplicated here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DecisionReasonCode
    values: tuple[int | float, ...] = Field(default_factory=tuple)
    related_strategy_ids: tuple[IdentifierString, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_values = data.get("values")
        if raw_values is not None:
            _validate_exact_finite_values(raw_values)
        return data

    @model_validator(mode="after")
    def _reason_shape_matches_code(self) -> DecisionReasonRecord:
        """Enforce the exact per-code positional value shape."""
        related = list(self.related_strategy_ids)
        if len(related) != len(set(related)):
            raise ValueError("related_strategy_ids must be unique")
        if self.code in ("unique_minimax_preference", "regret_tie_within_tolerance"):
            if len(self.values) != 2:
                raise ValueError(f"{self.code} requires exactly two structured values")
            if any(
                type(value) is not float or not math.isfinite(value) or value < 0.0
                for value in self.values
            ):
                raise ValueError(f"{self.code} structured values must be finite and non-negative")
            if self.code == "regret_tie_within_tolerance" and not related:
                raise ValueError("regret_tie_within_tolerance requires related strategy ids")
            if self.code == "unique_minimax_preference" and related:
                raise ValueError("unique_minimax_preference carries no related strategy ids")
        else:
            if len(self.values) != 2:
                raise ValueError(f"{self.code} requires exactly two structured values")
            if any(type(value) is not int or value < 0 for value in self.values):
                raise ValueError(f"{self.code} structured values must be exact non-negative ints")
            if related:
                raise ValueError(f"{self.code} carries no related strategy ids")
        return self


#: The closed decision-factor code catalogue (kind fixed by code).
DecisionFactorCode = Literal[
    "feasible_candidate",
    "target_feasibility_passed",
    "pareto_non_dominated",
    "unique_minimax_regret",
    "objective_target_failed",
    "dominated_strategy",
    "minimax_regret_tie",
    "no_feasible_strategy",
    "insufficient_seed_count",
]

#: Decisive factor codes, ordered by pipeline stage (evidence,
#: feasibility, dominance, minimax).
_DECISIVE_STAGE = {
    "feasible_candidate": 0,
    "target_feasibility_passed": 1,
    "pareto_non_dominated": 2,
    "unique_minimax_regret": 3,
}

#: Blocking factor codes, ordered by pipeline stage (feasibility,
#: dominance, minimax, terminal).
_BLOCKING_STAGE = {
    "objective_target_failed": 0,
    "dominated_strategy": 1,
    "minimax_regret_tie": 2,
    "no_feasible_strategy": 3,
    "insufficient_seed_count": 4,
}


class DecisionFactorRecord(BaseModel):
    """One immutable decisive or blocking decision-factor record.

    Binds one closed factor code to its typed structured values; the
    kind (decisive or blocking) is fixed by the code and enforced at
    the brief level together with the pipeline-stage ordering. The
    per-code value shapes enforced here:

    - ``feasible_candidate`` / ``pareto_non_dominated``: strategy id
      only, no values, no related ids;
    - ``target_feasibility_passed``: strategy id + objective id plus
      two values ``[threshold, observed_probability]`` with the
      observed probability at or above the threshold;
    - ``objective_target_failed``: strategy id + objective id plus two
      values ``[threshold, observed_probability]`` with the observed
      probability below the threshold;
    - ``unique_minimax_regret``: strategy id, exactly one related
      competitor id, and three values
      ``[winner_max_regret, nearest_max_regret, gap]`` with the gap
      exactly equal to ``nearest_max_regret - winner_max_regret``;
    - ``dominated_strategy``: strategy id (the dominated strategy) plus
      non-empty related dominator ids in strategy order;
    - ``minimax_regret_tie``: non-empty related tied ids plus two
      values ``[best_max_regret, tie_tolerance]``;
    - ``no_feasible_strategy``: two exact integer values
      ``[considered_count, feasible_count]``;
    - ``insufficient_seed_count``: two exact integer values
      ``[declared_minimum, recorded_count]``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DecisionFactorCode
    strategy_id: IdentifierString | None = None
    objective_id: IdentifierString | None = None
    values: tuple[int | float, ...] = Field(default_factory=tuple)
    related_strategy_ids: tuple[IdentifierString, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_values = data.get("values")
        if raw_values is not None:
            _validate_exact_finite_values(raw_values)
        return data

    @model_validator(mode="after")
    def _factor_shape_matches_code(self) -> DecisionFactorRecord:
        """Enforce the exact per-code typed value shape."""
        related = list(self.related_strategy_ids)
        if len(related) != len(set(related)):
            raise ValueError("related_strategy_ids must be unique")
        if self.code in ("feasible_candidate", "pareto_non_dominated"):
            if self.strategy_id is None or self.objective_id is not None:
                raise ValueError(f"{self.code} requires a strategy id and no objective id")
            if self.values or related:
                raise ValueError(f"{self.code} carries no values and no related ids")
        elif self.code in ("target_feasibility_passed", "objective_target_failed"):
            if self.strategy_id is None or self.objective_id is None:
                raise ValueError(f"{self.code} requires a strategy id and an objective id")
            if len(self.values) != 2:
                raise ValueError(f"{self.code} requires exactly two structured values")
            threshold = self.values[0]
            observed = self.values[1]
            if type(threshold) is not float or not math.isfinite(threshold):
                raise ValueError(f"{self.code} threshold must be a finite float")
            if type(observed) is not float or not math.isfinite(observed):
                raise ValueError(f"{self.code} observed_probability must be a finite float")
            if not _is_probability(threshold) or not _is_probability(observed):
                raise ValueError(
                    f"{self.code} threshold and observed_probability must be within [0.0, 1.0]"
                )
            if self.code == "target_feasibility_passed":
                if observed < threshold:
                    raise ValueError(
                        "target_feasibility_passed requires observed_probability >= threshold"
                    )
            elif observed >= threshold:
                raise ValueError(
                    "objective_target_failed requires observed_probability < threshold"
                )
            if related:
                raise ValueError(f"{self.code} carries no related ids")
        elif self.code == "unique_minimax_regret":
            if self.strategy_id is None or self.objective_id is not None:
                raise ValueError("unique_minimax_regret requires a strategy id and no objective id")
            if len(related) != 1:
                raise ValueError("unique_minimax_regret requires exactly one related competitor")
            if related[0] == self.strategy_id:
                raise ValueError("unique_minimax_regret competitor must differ from the winner")
            if len(self.values) != 3:
                raise ValueError("unique_minimax_regret requires exactly three structured values")
            winner = self.values[0]
            nearest = self.values[1]
            gap = self.values[2]
            if any(
                type(value) is not float or not math.isfinite(value) or value < 0.0
                for value in (winner, nearest, gap)
            ):
                raise ValueError("unique_minimax_regret values must be finite and non-negative")
            if gap != nearest - winner:
                raise ValueError(
                    "unique_minimax_regret gap must equal nearest_max_regret - winner_max_regret"
                )
        elif self.code == "dominated_strategy":
            if self.strategy_id is None or self.objective_id is not None:
                raise ValueError("dominated_strategy requires a strategy id and no objective id")
            if self.values:
                raise ValueError("dominated_strategy carries no values")
            if not related:
                raise ValueError("dominated_strategy requires at least one dominator id")
            if self.strategy_id in related:
                raise ValueError("dominated_strategy dominators must not contain the strategy")
        elif self.code == "minimax_regret_tie":
            if self.strategy_id is not None or self.objective_id is not None:
                raise ValueError("minimax_regret_tie carries no strategy/objective ids")
            if len(self.values) != 2:
                raise ValueError("minimax_regret_tie requires exactly two structured values")
            if any(
                type(value) is not float or not math.isfinite(value) or value < 0.0
                for value in self.values
            ):
                raise ValueError("minimax_regret_tie values must be finite and non-negative")
            if not related:
                raise ValueError("minimax_regret_tie requires at least one tied strategy id")
        else:
            if self.strategy_id is not None or self.objective_id is not None:
                raise ValueError(f"{self.code} carries no strategy/objective ids")
            if len(self.values) != 2:
                raise ValueError(f"{self.code} requires exactly two structured values")
            if any(type(value) is not int or value < 0 for value in self.values):
                raise ValueError(f"{self.code} structured values must be exact non-negative ints")
            if related:
                raise ValueError(f"{self.code} carries no related ids")
        return self


class CampaignDecisionPolicy(VersionedContract):
    """The immutable stored campaign decision policy.

    Binds one campaign's declarative decision policy: the campaign,
    scenario, world-version, and evaluation-profile identity with the
    scenario and world content hashes; the accepted algorithm
    identifier; the exact global-or-per-objective target-requirement
    mode (``global`` requires the global probability and forbids
    per-objective requirements; ``per_objective`` requires at least
    one requirement and forbids the global probability); the fixed
    tail alpha exactly ``0.95`` (callers cannot select another alpha);
    the exact-int minimum sample count (``>= 1``, booleans and
    integral floats rejected before coercion); the finite non-negative
    tie tolerance; the hard-gate flag; the authoritative objective-
    weight snapshot (one immutable ``ObjectiveWeightSnapshot`` per
    authoritative objective, unique, preserved in the exact supplied
    authoritative order - never sorted, never normalized); the
    deterministic caller-supplied declaration
    timestamp; and finite-only metadata.

    The scenario identity is part of the policy: the future policy
    declaration cannot invent or override scenario identity, evaluation
    identity, tail alpha, or weights - the future policy service copies
    and verifies those values from the authoritative scenario/
    evaluation-profile snapshot. The policy is declarative data only
    and never alters simulation or evidence artifacts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    evaluation_profile_id: IdentifierString
    evaluation_profile_content_hash: Sha256Hex
    algorithm_identifier: Literal["feasibility-pareto-minimax-regret-v1"] = _ALGORITHM_IDENTIFIER
    target_requirement_mode: Literal["global", "per_objective"]
    minimum_target_achievement_probability: float | None = None
    objective_target_requirements: tuple[ObjectiveTargetRequirement, ...] = Field(
        default_factory=tuple
    )
    objective_weight_snapshots: tuple[ObjectiveWeightSnapshot, ...] = Field(min_length=1)
    minimum_sample_count: int = Field(ge=1)
    tie_tolerance: float
    all_targeted_objectives_are_hard_gates: bool
    tail_alpha: Literal[0.95] = 0.95  # type: ignore[valid-type]
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_minimum = data.get("minimum_sample_count")
        if raw_minimum is not None:
            _require_exact_int(raw_minimum, "minimum_sample_count")
        raw_probability = data.get("minimum_target_achievement_probability")
        if raw_probability is not None and not _is_exact_finite_numeric(raw_probability):
            raise ValueError(
                "minimum_target_achievement_probability must be an exact finite int or float"
            )
        raw_tolerance = data.get("tie_tolerance")
        if raw_tolerance is not None and not _is_exact_finite_numeric(raw_tolerance):
            raise ValueError("tie_tolerance must be an exact finite int or float")
        raw_alpha = data.get("tail_alpha")
        if raw_alpha is not None and (type(raw_alpha) is not float or raw_alpha != 0.95):
            raise ValueError("tail_alpha must be exactly 0.95")
        return data

    @model_validator(mode="after")
    def _policy_is_internally_consistent(self) -> CampaignDecisionPolicy:
        """Enforce the exact policy rules.

        The global/per-objective mode XOR (``global`` requires the
        global probability and an empty requirements tuple;
        ``per_objective`` requires a ``None`` global probability and a
        non-empty requirements tuple); the inclusive probability band
        when a global probability exists; unique requirement objective
        identifiers; unique weight-snapshot objective identifiers
        (the supplied authoritative order is preserved exactly - the
        contract never sorts it, and weights are never normalized or
        renormalized; all-zero weights remain representable; external
        completeness/order/weight verification against the
        authoritative scenario/evaluation-profile record belongs to
        the future policy service); the fixed tail alpha exactly
        ``0.95``; the finite non-negative tie tolerance; and metadata
        free of non-finite floats.
        """
        if self.target_requirement_mode == "global":
            if self.minimum_target_achievement_probability is None:
                raise ValueError(
                    "global mode requires a global minimum target-achievement probability"
                )
            if self.objective_target_requirements:
                raise ValueError("global mode forbids per-objective target requirements")
        else:
            if self.minimum_target_achievement_probability is not None:
                raise ValueError("per_objective mode forbids a global probability")
            if not self.objective_target_requirements:
                raise ValueError("per_objective mode requires at least one target requirement")
        probability = self.minimum_target_achievement_probability
        if probability is not None and not _is_probability(probability):
            raise ValueError("minimum_target_achievement_probability must be within [0.0, 1.0]")
        requirement_ids = [
            requirement.objective_id for requirement in self.objective_target_requirements
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("objective_target_requirements objective identifiers must be unique")
        weight_ids = [snapshot.objective_id for snapshot in self.objective_weight_snapshots]
        if len(weight_ids) != len(set(weight_ids)):
            raise ValueError("objective_weight_snapshots objective identifiers must be unique")
        if self.tail_alpha != 0.95:
            raise ValueError("tail_alpha must be exactly 0.95")
        if not math.isfinite(self.tie_tolerance) or self.tie_tolerance < 0.0:
            raise ValueError("tie_tolerance must be finite and non-negative")
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must not contain non-finite floats")
        return self


class CampaignStrategyComparison(VersionedContract):
    """The immutable derived campaign-level strategy comparison.

    Binds one completed campaign's complete ordered-pair comparison
    matrix: the campaign/scenario/world identity with content hashes,
    the recorded runtime version and comparison mode literals, the
    accepted algorithm identifier, the referenced decision policy
    (identity + content hash) whose tie tolerance and minimum sample
    count are snapshotted here, the source outcome-matrix reference,
    the ordered strategy/seed/objective identifiers, the complete
    ``S * (S - 1) * O`` paired-comparison tuple, the complete
    ``S * (S - 1)`` dominance-relation tuple, and exactly one
    robustness profile per strategy in strategy order.

    The contract enforces the complete structural shape: no self-pairs;
    both directions of every pair and every objective; the exact
    deterministic pair-major/objective-minor ordering formula
    ``position = (a * (S - 1) + (b if b < a else b - 1)) * O + o``
    with contiguous positions and identity-vs-position agreement;
    every paired comparison aligned to the recorded seed count and the
    recorded tie tolerance; the exact reverse-pair invariants (deltas
    are exact IEEE negations, win/loss/tie counts mirror, median/p05/
    p95 and worst/best mirror exactly); dominance relations with
    per-objective statuses read from the stored forward paired
    comparisons whose reverse statuses are derived independently from
    each direction's own mirrored counts (no unconditional worse/
    better mirror - crossing seed-level performance is representable)
    with mutual overall dominance forbidden; and robustness profiles
    whose full-coverage per-objective tuples (weighted regret and
    downside evidence) follow the exact objective order and whose
    target-only tuples (feasibility and achievement probabilities)
    carry the same targeted objective ids in the same relative order
    (both may be empty when no objective has a target; the future
    builder verifies exact targeted coverage from the policy/profile).
    Source-authority verification (the policy record, the outcome-matrix
    record, and their recorded hashes) belongs to the application
    builders.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    algorithm_identifier: Literal["feasibility-pareto-minimax-regret-v1"] = _ALGORITHM_IDENTIFIER
    policy_id: IdentifierString
    policy_content_hash: Sha256Hex
    tie_tolerance: float
    minimum_sample_count: int = Field(ge=1)
    source_outcome_matrix_id: IdentifierString
    source_outcome_matrix_content_hash: Sha256Hex
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_objective_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    paired_comparisons: tuple[ObjectivePairedComparison, ...] = Field(min_length=1)
    dominance_relations: tuple[DominanceRelation, ...] = Field(min_length=1)
    robustness_profiles: tuple[StrategyRobustnessProfile, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    derived_at: AwareDatetime

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_minimum = data.get("minimum_sample_count")
        if raw_minimum is not None:
            _require_exact_int(raw_minimum, "minimum_sample_count")
        raw_tolerance = data.get("tie_tolerance")
        if raw_tolerance is not None and not _is_exact_finite_numeric(raw_tolerance):
            raise ValueError("tie_tolerance must be an exact finite int or float")
        return data

    @model_validator(mode="after")
    def _comparison_structural_shape(self) -> CampaignStrategyComparison:
        """Enforce the complete ordered-pair matrix structural shape.

        See the class documentation for the exact rules; the reverse
        pair of every ordered pair and objective is mandatory and is
        never reconstructed - missing reverse records are a cardinality
        failure.
        """
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        seed_ids = list(self.ordered_scenario_seed_ids)
        objective_ids = list(self.ordered_objective_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("ordered_objective_ids must be unique")
        strategy_count = len(strategy_ids)
        seed_count = len(seed_ids)
        objective_count = len(objective_ids)
        if strategy_count < 2:
            raise ValueError("a strategy comparison requires at least two strategies")
        if not math.isfinite(self.tie_tolerance) or self.tie_tolerance < 0.0:
            raise ValueError("tie_tolerance must be finite and non-negative")
        ordered_pair_count = strategy_count * (strategy_count - 1)
        if len(self.paired_comparisons) != ordered_pair_count * objective_count:
            raise ValueError(
                "paired_comparisons must cover every ordered strategy pair and objective "
                "exactly once"
            )
        if len(self.dominance_relations) != ordered_pair_count:
            raise ValueError(
                "dominance_relations must cover every ordered strategy pair exactly once"
            )
        if len(self.robustness_profiles) != strategy_count:
            raise ValueError("robustness_profiles must contain exactly one profile per strategy")

        def pair_index(first: int, second: int) -> int:
            return first * (strategy_count - 1) + (second if second < first else second - 1)

        comparisons_by_key: dict[tuple[int, int, int], ObjectivePairedComparison] = {}
        for position, comparison in enumerate(self.paired_comparisons):
            first = comparison.first_strategy_position
            second = comparison.second_strategy_position
            objective_position = comparison.objective_position
            if first >= strategy_count or second >= strategy_count or first == second:
                raise ValueError("paired comparison strategy positions must be in range and differ")
            if objective_position >= objective_count:
                raise ValueError("paired comparison objective position out of range")
            expected_position = pair_index(first, second) * objective_count + objective_position
            if comparison.sequence_position != position or expected_position != position:
                raise ValueError(
                    "paired comparisons must be contiguous in the exact pair-major, "
                    "objective-minor order"
                )
            if comparison.first_strategy_candidate_id != strategy_ids[first]:
                raise ValueError(
                    "paired comparison first strategy identity does not match its position"
                )
            if comparison.second_strategy_candidate_id != strategy_ids[second]:
                raise ValueError(
                    "paired comparison second strategy identity does not match its position"
                )
            if comparison.objective_id != objective_ids[objective_position]:
                raise ValueError("paired comparison objective identity does not match its position")
            if comparison.tie_tolerance != self.tie_tolerance:
                raise ValueError("paired comparison tie tolerance must equal the recorded snapshot")
            if len(comparison.ordered_paired_deltas) != seed_count:
                raise ValueError("paired comparison delta count must equal the recorded seed count")
            key = (first, second, objective_position)
            if key in comparisons_by_key:
                raise ValueError("duplicate ordered pair/objective paired comparison")
            comparisons_by_key[key] = comparison

        for (first, second, objective_position), comparison in comparisons_by_key.items():
            reverse = comparisons_by_key.get((second, first, objective_position))
            if reverse is None:
                raise ValueError("missing reverse-pair comparison")
            if reverse.ordered_paired_deltas != tuple(
                -delta for delta in comparison.ordered_paired_deltas
            ):
                raise ValueError(
                    "reverse-pair deltas must be exact negations of the forward deltas"
                )
            if (
                reverse.win_count != comparison.loss_count
                or reverse.loss_count != comparison.win_count
                or reverse.tie_count != comparison.tie_count
            ):
                raise ValueError("reverse-pair win/tie/loss counts must mirror the forward counts")
            if reverse.median_paired_delta != -comparison.median_paired_delta:
                raise ValueError("reverse-pair median must equal the negated forward median")
            if reverse.p05_paired_delta != -comparison.p95_paired_delta:
                raise ValueError("reverse-pair p05 must equal the negated forward p95")
            if reverse.p95_paired_delta != -comparison.p05_paired_delta:
                raise ValueError("reverse-pair p95 must equal the negated forward p05")
            if reverse.worst_paired_delta != -comparison.best_paired_delta:
                raise ValueError("reverse-pair worst must equal the negated forward best")
            if reverse.best_paired_delta != -comparison.worst_paired_delta:
                raise ValueError("reverse-pair best must equal the negated forward worst")

        relations_by_pair: dict[tuple[int, int], DominanceRelation] = {}
        for relation in self.dominance_relations:
            first = relation.first_strategy_position
            second = relation.second_strategy_position
            if first >= strategy_count or second >= strategy_count or first == second:
                raise ValueError(
                    "dominance relation strategy positions must be in range and differ"
                )
            if relation.first_strategy_candidate_id != strategy_ids[first]:
                raise ValueError("dominance relation first strategy identity mismatch")
            if relation.second_strategy_candidate_id != strategy_ids[second]:
                raise ValueError("dominance relation second strategy identity mismatch")
            statuses = list(relation.per_objective_status)
            if len(statuses) != objective_count:
                raise ValueError(
                    "dominance relation must carry one status per objective in objective order"
                )
            for objective_position, status in enumerate(statuses):
                if status.objective_id != objective_ids[objective_position]:
                    raise ValueError(
                        "dominance status objective identity does not match its position"
                    )
                comparison = comparisons_by_key[(first, second, objective_position)]
                if (
                    status.win_count != comparison.win_count
                    or status.tie_count != comparison.tie_count
                    or status.loss_count != comparison.loss_count
                ):
                    raise ValueError(
                        "dominance status counts must equal the stored forward paired comparison"
                    )
                if status.median_paired_delta != comparison.median_paired_delta:
                    raise ValueError(
                        "dominance status median must equal the stored forward paired comparison"
                    )
            relation_key = (first, second)
            if relation_key in relations_by_pair:
                raise ValueError("duplicate dominance relation for an ordered pair")
            relations_by_pair[relation_key] = relation

        for (first, second), relation in relations_by_pair.items():
            reverse_relation = relations_by_pair.get((second, first))
            if reverse_relation is None:
                raise ValueError("missing reverse-pair dominance relation")
            if relation.dominates and reverse_relation.dominates:
                raise ValueError("a strategy pair cannot dominate each other")
            for objective_position, status in enumerate(relation.per_objective_status):
                reverse_status = reverse_relation.per_objective_status[objective_position]
                if (
                    reverse_status.win_count != status.loss_count
                    or reverse_status.tie_count != status.tie_count
                    or reverse_status.loss_count != status.win_count
                ):
                    raise ValueError(
                        "reverse dominance status counts must mirror the forward status"
                    )
                if reverse_status.median_paired_delta != -status.median_paired_delta:
                    raise ValueError(
                        "reverse dominance median must equal the negated forward median"
                    )
                # The reverse status is derived independently from its
                # own (mirrored) counts - there is no unconditional
                # worse <-> better mirror: crossing seed-level
                # performance is representable (mixed wins and losses
                # yield "worse" in both directions, and neither
                # strategy dominates). Each status must equal the exact
                # derivation over its own counts.
                reverse_expected: Literal["better", "tied", "worse"]
                if reverse_status.loss_count > 0:
                    reverse_expected = "worse"
                elif reverse_status.win_count > 0:
                    reverse_expected = "better"
                else:
                    reverse_expected = "tied"
                if reverse_status.status != reverse_expected:
                    raise ValueError(
                        "reverse dominance status must derive from its own mirrored counts"
                    )

        for position, profile in enumerate(self.robustness_profiles):
            if profile.strategy_position != position:
                raise ValueError(
                    "robustness profile positions must be contiguous in strategy order"
                )
            if profile.strategy_candidate_id != strategy_ids[position]:
                raise ValueError("robustness profile identity does not match its strategy position")
            full_coverage_tuples: tuple[tuple[Any, ...], ...] = (
                profile.per_objective_weighted_regret,
                profile.downside_evidence,
            )
            for records in full_coverage_tuples:
                if len(records) != objective_count:
                    raise ValueError(
                        "robustness profile per-objective tuples must cover every objective "
                        "exactly once"
                    )
                for objective_position, record in enumerate(records):
                    if record.objective_id != objective_ids[objective_position]:
                        raise ValueError(
                            "robustness profile per-objective records must follow the exact "
                            "objective order"
                        )
            target_only_tuples: tuple[tuple[Any, ...], ...] = (
                profile.target_feasibility,
                profile.target_achievement_probabilities,
            )
            for records in target_only_tuples:
                if len(records) != len({record.objective_id for record in records}):
                    raise ValueError(
                        "robustness profile target-only tuples must carry unique objective ids"
                    )
                for record in records:
                    if record.objective_id not in objective_ids:
                        raise ValueError(
                            "robustness profile target-only records must reference known objectives"
                        )
                relative_positions = [
                    objective_ids.index(record.objective_id) for record in records
                ]
                if any(
                    previous >= following
                    for previous, following in zip(
                        relative_positions, relative_positions[1:], strict=False
                    )
                ):
                    raise ValueError(
                        "robustness profile target-only records must follow the relative "
                        "objective order"
                    )
            if [record.objective_id for record in profile.target_feasibility] != [
                record.objective_id for record in profile.target_achievement_probabilities
            ]:
                raise ValueError(
                    "target_feasibility and target_achievement_probabilities must carry the "
                    "same targeted objective ids in the same order"
                )
            if len(profile.per_seed_total_weighted_regrets) != seed_count:
                raise ValueError(
                    "robustness profile per-seed regrets must align with the recorded seed count"
                )
            dominated_by = [
                strategy_ids[dominator]
                for dominator in range(strategy_count)
                if dominator != position and relations_by_pair[(dominator, position)].dominates
            ]
            dominates = [
                strategy_ids[dominated]
                for dominated in range(strategy_count)
                if dominated != position and relations_by_pair[(position, dominated)].dominates
            ]
            if profile.dominated_by != tuple(dominated_by):
                raise ValueError(
                    "robustness profile dominated_by must equal the stored dominance relations"
                )
            if profile.dominates != tuple(dominates):
                raise ValueError(
                    "robustness profile dominates must equal the stored dominance relations"
                )
        return self


class CampaignDecisionBrief(VersionedContract):
    """The immutable derived auditable campaign decision brief.

    Binds one campaign's decision outcome: the campaign/scenario/world
    identity, the recorded runtime/comparison-mode/algorithm literals,
    the referenced decision policy and strategy comparison (identity +
    content hash), exactly one of the four accepted statuses
    (``preferred``, ``inconclusive``, ``insufficient_evidence``,
    ``no_feasible_strategy``), an optional preferred strategy id
    present only for ``preferred`` and only when it is one of the
    considered strategies, the authoritative considered-strategy order,
    a deterministic factual summary, exactly one terminal reason whose
    code matches the status, ordered decisive and blocking factors
    from the closed catalogue, the copied robustness profiles, the
    copied declared assumptions, and complete evidence references
    (evaluation profile, optional uncertainty model both-or-neither,
    source world-realization matrix, source metric-observation matrix,
    source outcome matrix).

    The contract enforces the exact decision rules: preferred-id
    presence and membership; terminal-reason code-to-status
    compatibility; decisive/blocking factor kind fixed by code with
    the exact pipeline-stage ordering; both-or-neither uncertainty
    provenance; unique assumptions; exactly one robustness profile per
    considered strategy in strategy order; and the status-to-
    feasibility consistency rules (``no_feasible_strategy`` requires
    every profile infeasible; ``preferred`` requires the preferred
    profile feasible). The brief contains no chain-of-thought, hidden
    reasoning, fabricated prose, or unexplained scalar score; the
    summary is assembled from deterministic factual templates by the
    application builder.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    algorithm_identifier: Literal["feasibility-pareto-minimax-regret-v1"] = _ALGORITHM_IDENTIFIER
    policy_id: IdentifierString
    policy_content_hash: Sha256Hex
    comparison_id: IdentifierString
    comparison_content_hash: Sha256Hex
    status: Literal["preferred", "inconclusive", "insufficient_evidence", "no_feasible_strategy"]
    preferred_strategy_id: IdentifierString | None = None
    considered_strategy_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    summary: str = Field(min_length=1)
    terminal_reason: DecisionReasonRecord
    decisive_factors: tuple[DecisionFactorRecord, ...] = Field(default_factory=tuple)
    blocking_factors: tuple[DecisionFactorRecord, ...] = Field(default_factory=tuple)
    robustness_profiles: tuple[StrategyRobustnessProfile, ...] = Field(min_length=1)
    assumptions: tuple[Assumption, ...] = Field(default_factory=tuple)
    evaluation_profile_id: IdentifierString
    evaluation_profile_content_hash: Sha256Hex
    uncertainty_model_id: IdentifierString | None = None
    uncertainty_model_content_hash: Sha256Hex | None = None
    source_world_realization_matrix_id: IdentifierString
    source_world_realization_matrix_content_hash: Sha256Hex
    source_metric_observation_matrix_id: IdentifierString
    source_metric_observation_matrix_content_hash: Sha256Hex
    source_outcome_matrix_id: IdentifierString
    source_outcome_matrix_content_hash: Sha256Hex
    content_hash: Sha256Hex
    produced_at: AwareDatetime

    @model_validator(mode="after")
    def _brief_decision_rules(self) -> CampaignDecisionBrief:
        """Enforce the exact brief decision rules.

        See the class documentation for the exact rules; the preferred
        strategy id is allowed only for the ``preferred`` status and
        must then be one of the considered strategies, the terminal
        reason code must match the status, the decisive/blocking factor
        tuples must carry only their kind's codes in the exact
        pipeline-stage order, and the status-to-feasibility rules must
        hold.
        """
        strategy_ids = list(self.considered_strategy_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("considered_strategy_ids must be unique")
        if self.status == "preferred":
            if self.preferred_strategy_id is None:
                raise ValueError("preferred status requires preferred_strategy_id")
            if self.preferred_strategy_id not in strategy_ids:
                raise ValueError("preferred_strategy_id must be one of the considered strategies")
        elif self.preferred_strategy_id is not None:
            raise ValueError("preferred_strategy_id is allowed only for the preferred status")

        expected_code: Literal[
            "unique_minimax_preference",
            "regret_tie_within_tolerance",
            "insufficient_seed_samples",
            "no_feasible_strategy",
        ]
        if self.status == "preferred":
            expected_code = "unique_minimax_preference"
        elif self.status == "inconclusive":
            expected_code = "regret_tie_within_tolerance"
        elif self.status == "insufficient_evidence":
            expected_code = "insufficient_seed_samples"
        else:
            expected_code = "no_feasible_strategy"
        if self.terminal_reason.code != expected_code:
            raise ValueError("terminal_reason.code must match the brief status")

        for factor in self.decisive_factors:
            if factor.code not in _DECISIVE_STAGE:
                raise ValueError("decisive_factors may only carry decisive factor codes")
        for factor in self.blocking_factors:
            if factor.code not in _BLOCKING_STAGE:
                raise ValueError("blocking_factors may only carry blocking factor codes")
        if any(
            _DECISIVE_STAGE[previous.code] > _DECISIVE_STAGE[next_factor.code]
            for previous, next_factor in zip(
                self.decisive_factors, self.decisive_factors[1:], strict=False
            )
        ):
            raise ValueError("decisive_factors must be ordered by pipeline stage")
        if any(
            _BLOCKING_STAGE[previous.code] > _BLOCKING_STAGE[next_factor.code]
            for previous, next_factor in zip(
                self.blocking_factors, self.blocking_factors[1:], strict=False
            )
        ):
            raise ValueError("blocking_factors must be ordered by pipeline stage")

        if (self.uncertainty_model_id is None) != (self.uncertainty_model_content_hash is None):
            raise ValueError(
                "uncertainty_model_id and uncertainty_model_content_hash must both be "
                "present or both be absent"
            )
        if len(self.robustness_profiles) != len(strategy_ids):
            raise ValueError(
                "robustness_profiles must contain exactly one profile per considered strategy"
            )
        for position, profile in enumerate(self.robustness_profiles):
            if profile.strategy_position != position:
                raise ValueError("robustness profile positions must match the considered order")
            if profile.strategy_candidate_id != strategy_ids[position]:
                raise ValueError("robustness profile identity must match the considered order")
        if self.status == "no_feasible_strategy" and any(
            profile.feasible for profile in self.robustness_profiles
        ):
            raise ValueError(
                "no_feasible_strategy requires every robustness profile to be infeasible"
            )
        if self.status == "preferred":
            if self.preferred_strategy_id is None:
                raise ValueError("preferred status requires preferred_strategy_id")
            preferred_position = strategy_ids.index(self.preferred_strategy_id)
            if not self.robustness_profiles[preferred_position].feasible:
                raise ValueError("the preferred strategy must be feasible")
        assumption_ids = [assumption.identifier for assumption in self.assumptions]
        if len(assumption_ids) != len(set(assumption_ids)):
            raise ValueError("assumptions must carry unique identifiers")
        return self


__all__ = [
    "ObjectiveWeightSnapshot",
    "ObjectiveTargetRequirement",
    "ObjectivePairedComparison",
    "ObjectiveFeasibilityEvidence",
    "ObjectiveRegretEvidence",
    "ObjectiveProbabilityEvidence",
    "ObjectiveDownsideEvidence",
    "ObjectiveDominanceStatus",
    "DominanceRelation",
    "StrategyRobustnessProfile",
    "DecisionReasonCode",
    "DecisionReasonRecord",
    "DecisionFactorCode",
    "DecisionFactorRecord",
    "CampaignDecisionPolicy",
    "CampaignStrategyComparison",
    "CampaignDecisionBrief",
]
