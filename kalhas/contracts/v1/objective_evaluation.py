"""Objective-to-metric evaluation contracts: deterministic value-level evaluations (Phase 23).

Phase 23 adds the **deterministic objective-to-metric evaluation
artifact**: an immutable, tenant-scoped ``ScenarioEvaluationProfile``
declaring - for every scenario objective - exactly which scenario
metric measures it, plus the authoritative snapshots needed to
evaluate exact observed values against the objective (direction,
target, weight, metric unit, reach tolerance, and normalization
scale), and the deterministic campaign-level
``CampaignObjectiveEvaluationMatrix`` of exact value-level statements
derived exclusively from the completely verified Phase 21
``CampaignMetricObservationMatrix`` and the exact
``ScenarioEvaluationProfile`` embedded in the campaign's compiled
world. The pipeline is

    ScenarioEvaluationProfile + verified CampaignMetricObservationMatrix
        -> exact per-strategy/per-seed/per-objective value evaluations

``ObjectiveMetricBinding`` is one immutable objective-to-metric
declaration: the objective and metric identities, the authoritative
snapshots copied from the stored ``ScenarioSpec`` (``direction``,
``target``, ``weight``, and ``metric_unit`` - never client-supplied),
the ``reach_tolerance`` (required, finite, and non-negative for a
``reach`` objective only; forbidden for ``minimize`` and
``maximize``), and the finite strictly positive
``normalization_scale`` needed for future comparable regret. A
``reach`` objective without an authoritative target cannot
participate in a profile; ``minimize``/``maximize`` objectives may
have no target and are then optimization-only. One metric may measure
multiple objectives; every scenario objective is bound exactly once.

``ScenarioEvaluationProfile`` is the immutable one-per-scenario
declaration: the scenario identity and its authoritative snapshot
content hash, the complete objective-to-metric binding tuple in the
exact authoritative ``ScenarioSpec.objectives`` order (caller binding
order never affects the artifact), a deterministic independently
derived identifier (never derived from the content hash), the
self-covering ``content_hash``, and the deterministic caller-supplied
``declared_at``. It is declared before the first world of the
scenario is compiled, cannot be updated, replaced, deleted, or
re-declared, and its complete snapshot is embedded in subsequently
compiled worlds under the compiler-owned ``evaluation_profile`` key.

``ObjectiveObservationEvaluation`` is one exact value-level
evaluation: the strategy/seed/objective positions and identities, the
metric identity and unit, the run identity and input hash, the exact
raw observed numeric value (integers stay integers, floats stay
floats - booleans, strings, ``None``, containers, NaN, and Infinity
are rejected before any coercion), the direction/target/weight/
tolerance/scale snapshots, ``target_achieved`` (``None`` exactly when
no target exists), the direction-aware ``signed_target_delta``, and
the non-negative normalized target-violation loss.

Signed target delta has one documented orientation - **positive means
adverse relative to the target or tolerance boundary, zero means
exactly on the boundary, negative means within or beyond the
acceptable side**:

- ``minimize``: ``value - target``
- ``maximize``: ``target - value``
- ``reach``: ``abs(value - target) - reach_tolerance``

For targeted objectives ``target_achieved`` is ``signed_target_delta
<= 0`` and the normalized target violation is ``max(0,
signed_target_delta) / normalization_scale``, which is exactly
``max(0, value - target) / scale`` for minimize, ``max(0, target -
value) / scale`` for maximize, and ``max(0, abs(value - target) -
tolerance) / scale`` for reach. When no target exists for a
minimize/maximize objective, ``target_achieved``,
``signed_target_delta``, and ``normalized_target_violation`` are all
``None`` - no target is ever invented. Target violation answers
"did the declared target get missed, and by how much (normalized)?";
it is **not** the later cross-strategy comparative regret.

``CampaignObjectiveEvaluationMatrix`` is the immutable aggregate: the
campaign/scenario/world identity with the world content hash, the
trajectory runtime version (always ``"2.0.0"``), the comparison mode
(always ``identical_conditions``), the exact verified source
``CampaignMetricObservationMatrix`` reference (deterministic
identifier and content hash), the exact world-embedded evaluation
profile reference (identifier and content hash), the authoritative
scenario content hash, the exact ordered strategy, seed, and
objective identifiers (objectives in exact ``ScenarioSpec`` order),
and the complete cell tuple in the exact strategy-major, seed-minor,
objective-minor order with contiguous sequence positions and exact
identity-vs-position agreement - the complete Cartesian product
present exactly once. Its identifier is independently derived from
the canonical campaign/world/runtime/source/profile identity (never
from the content hash), ``evaluated_at`` is the authoritative Phase
21 matrix ``assembled_at`` - never the wall clock - and the
``content_hash`` is the canonical digest of the complete payload
excluding ``content_hash`` itself.

The matrix is **exact value-level evaluation only**: it performs no
statistical aggregation, produces no probability, confidence,
empirical distribution, risk, CVaR, ranking, dominance, regret,
preference, winner selection, evidence, ``MetricOutcome``,
``OutcomeVector``, ``DistributionSummary``, recommendation, or
``DecisionBrief``, and nothing here loads, imports, instantiates, or
executes a domain pack. No field type can express a callback,
expression, formula, code reference, provider, or executable
mechanism.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The trajectory runtime version this matrix describes. Kept as a
#: literal so the matrix can never record any other runtime version.
OBJECTIVE_EVALUATION_MATRIX_RUNTIME_VERSION_LITERAL: Literal["2.0.0"] = "2.0.0"

#: The declared objective directions an evaluation binding may snapshot.
ObjectiveDirectionValue = Literal["minimize", "maximize", "reach"]


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value.

    Booleans are never accepted as integers or numbers, and non-finite
    floats (NaN/Infinity) are rejected because they are not valid JSON
    numbers. Strings, ``None``, and containers are rejected - no
    numeric coercion of any kind happens.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def evaluate_target_delta(
    *,
    direction: str,
    raw_value: int | float,
    target: float | None,
    reach_tolerance: float | None,
) -> float | None:
    """The single deterministic direction-aware signed target delta definition.

    - ``minimize``: ``raw_value - target``
    - ``maximize``: ``target - raw_value``
    - ``reach``: ``abs(raw_value - target) - reach_tolerance``

    Returns ``None`` exactly when no target exists. This one pure
    expression is shared by the evaluation cell contract validator and
    the Phase 23 builder, so the two semantic definitions can never
    drift. It is deterministic and domain-neutral, with no store,
    wall-clock, I/O, network, or provider access; numeric overflow
    surfaces as ``OverflowError``/``ArithmeticError`` and a missing
    reach tolerance as ``ValueError`` - callers decide how to map
    failures.
    """
    if target is None:
        return None
    if direction == "minimize":
        return raw_value - target
    if direction == "maximize":
        return target - raw_value
    if reach_tolerance is None:
        raise ValueError("reach tolerance is required")
    return abs(raw_value - target) - reach_tolerance


class ObjectiveMetricBinding(BaseModel):
    """One immutable objective-to-metric evaluation binding.

    Declares which scenario metric measures one scenario objective and
    snapshots the authoritative objective/metric fields copied from the
    stored ``ScenarioSpec``: ``direction``, ``target``, ``weight``, and
    ``metric_unit`` are never client-supplied. ``reach_tolerance`` is
    required, finite, and non-negative for a ``reach`` objective only
    and forbidden for ``minimize``/``maximize``; a ``reach`` objective
    without an authoritative target cannot participate in a profile.
    ``normalization_scale`` is exact numeric, finite, and strictly
    positive. One metric may measure multiple objectives; every
    scenario objective is bound exactly once. The binding is
    declarative data only - nothing here evaluates a value, aggregates,
    scores, ranks, or recommends.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: IdentifierString
    metric_id: IdentifierString
    direction: ObjectiveDirectionValue
    target: float | None = None
    weight: float = Field(default=1.0, ge=0.0)
    metric_unit: str | None = None
    reach_tolerance: float | None = None
    normalization_scale: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject bool/non-numeric raw values before any coercion.

        Pydantic lax mode would otherwise coerce ``True`` into a float
        and strings into numbers; checking the un-coerced input keeps
        booleans, strings, ``None``, containers, and non-finite floats
        out of the numeric fields.
        """
        if not isinstance(data, dict):
            return data
        for key in ("target", "weight", "reach_tolerance", "normalization_scale"):
            raw = data.get(key)
            if raw is None:
                continue
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _target_tolerance_scale_rules(self) -> ObjectiveMetricBinding:
        """Enforce the exact target, tolerance, and scale rules.

        A ``reach`` objective requires both an authoritative target and
        a finite non-negative ``reach_tolerance``; ``minimize`` and
        ``maximize`` must not carry a tolerance. The normalization
        scale must be finite and strictly positive.
        """
        if self.direction == "reach":
            if self.target is None:
                raise ValueError("reach objective requires an authoritative target")
            if self.reach_tolerance is None:
                raise ValueError("reach objective requires a reach_tolerance")
            if not math.isfinite(self.reach_tolerance) or self.reach_tolerance < 0.0:
                raise ValueError("reach_tolerance must be finite and non-negative")
        elif self.reach_tolerance is not None:
            raise ValueError("reach_tolerance is forbidden for minimize and maximize")
        if not math.isfinite(self.normalization_scale) or self.normalization_scale <= 0.0:
            raise ValueError("normalization_scale must be finite and strictly positive")
        if self.target is not None and not math.isfinite(self.target):
            raise ValueError("target must be finite when present")
        if not math.isfinite(self.weight):
            raise ValueError("weight must be finite")
        return self


class ScenarioEvaluationProfile(VersionedContract):
    """The immutable one-per-scenario objective-to-metric evaluation profile.

    Declares, for exactly one stored ``ScenarioSpec``, the complete
    objective-to-metric binding tuple in the exact authoritative
    ``ScenarioSpec.objectives`` order - every objective bound exactly
    once, objective identifiers unique, and equivalent caller binding
    orders producing the same canonical artifact. The authoritative
    ``scenario_content_hash`` is the SHA-256 digest of the canonical
    JSON serialization of the complete stored scenario. The profile
    identifier is independently derived from the canonical
    tenant/scenario/scenario-hash/schema identity - never from the
    content hash - and ``content_hash`` is the canonical digest of the
    complete profile serialization excluding ``content_hash`` itself.
    ``declared_at`` is the deterministic caller-supplied timestamp and
    is included in content hashing; no wall clock is ever read.

    The profile is declared before the first world of the scenario is
    compiled, cannot be updated, replaced, deleted, or re-declared, and
    is embedded as a complete declarative snapshot in subsequently
    compiled worlds. It is data only: nothing here evaluates values,
    aggregates, scores, ranks, or recommends.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    bindings: tuple[ObjectiveMetricBinding, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bindings_are_unique(self) -> ScenarioEvaluationProfile:
        """Every objective must be bound at most once in the profile.

        Completeness (every scenario objective bound exactly once) and
        the exact ``ScenarioSpec`` binding order are verified against
        the stored scenario by the declaration service and by world
        integrity verification - the contract cannot check them alone.
        """
        identifiers = [binding.objective_id for binding in self.bindings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("bindings must carry unique objective identifiers")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> ScenarioEvaluationProfile:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class ObjectiveObservationEvaluation(BaseModel):
    """One exact value-level objective evaluation of one campaign run.

    Evaluates one exact raw observed metric value against one
    objective binding: the strategy/seed/objective positions and
    identities, the metric identity and unit, the run identity and
    input hash the value came from, the exact raw value (integers stay
    integers, floats stay floats), the direction/target/weight/
    tolerance/scale snapshots, ``target_achieved`` (``None`` exactly
    when no target exists), the direction-aware ``signed_target_delta``
    (positive = adverse, zero = boundary, negative = acceptable), and
    the non-negative normalized target violation
    ``max(0, signed_target_delta) / normalization_scale``. When no
    target exists all three evaluation fields are ``None`` - no target
    is ever invented. All derived values must be finite; anything else
    is rejected. The evaluation is data only: nothing here aggregates,
    scores, ranks, or recommends.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    strategy_position: int = Field(ge=0)
    seed_position: int = Field(ge=0)
    objective_position: int = Field(ge=0)
    strategy_candidate_id: IdentifierString
    scenario_seed_id: IdentifierString
    objective_id: IdentifierString
    metric_id: IdentifierString
    metric_unit: str | None = None
    run_id: IdentifierString
    input_hash: Sha256Hex
    raw_value: int | float
    direction: ObjectiveDirectionValue
    target: float | None = None
    weight: float = Field(default=1.0, ge=0.0)
    reach_tolerance: float | None = None
    normalization_scale: float
    target_achieved: bool | None = None
    signed_target_delta: float | None = None
    normalized_target_violation: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject bool/non-numeric raw values before any coercion.

        Pydantic lax mode would otherwise coerce ``True`` into an
        integer or number and strings into numbers; checking the
        un-coerced input keeps booleans, strings, ``None``, containers,
        and non-finite floats out of ``raw_value``, ``target``, and the
        other numeric fields.
        """
        if not isinstance(data, dict):
            return data
        if not _is_exact_finite_numeric(data.get("raw_value")):
            raise ValueError("raw_value must be an exact finite numeric value")
        for key in ("target", "weight", "reach_tolerance", "normalization_scale"):
            raw = data.get(key)
            if raw is None:
                continue
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _evaluation_consistency(self) -> ObjectiveObservationEvaluation:
        """Enforce the exact evaluation consistency rules.

        The three evaluation fields are ``None`` exactly when no target
        exists. When a target exists, the expected signed target delta
        is **independently recomputed** from this cell's own raw value,
        direction, target, and reach tolerance via the shared
        :func:`evaluate_target_delta` helper - the same pure expression
        the Phase 23 builder uses - and ``signed_target_delta``,
        ``target_achieved``, and ``normalized_target_violation`` must
        equal the recomputed values exactly. A self-consistent but
        forged triple (delta/achieved/violation mutually consistent but
        inconsistent with the raw inputs) is rejected: never clamped,
        rounded, coerced, repaired, or approximately compared.
        Overflow and non-finite derivations are rejected.
        """
        if self.direction == "reach":
            if self.target is None:
                raise ValueError("reach objective requires an authoritative target")
            if self.reach_tolerance is None:
                raise ValueError("reach objective requires a reach_tolerance")
            if not math.isfinite(self.reach_tolerance) or self.reach_tolerance < 0.0:
                raise ValueError("reach_tolerance must be finite and non-negative")
        elif self.reach_tolerance is not None:
            raise ValueError("reach_tolerance is forbidden for minimize and maximize")
        if not math.isfinite(self.normalization_scale) or self.normalization_scale <= 0.0:
            raise ValueError("normalization_scale must be finite and strictly positive")
        if not math.isfinite(self.weight):
            raise ValueError("weight must be finite")
        if isinstance(self.raw_value, float) and not math.isfinite(self.raw_value):
            raise ValueError("raw_value must be a finite numeric value")
        if self.target is None:
            if (
                self.target_achieved is not None
                or self.signed_target_delta is not None
                or self.normalized_target_violation is not None
            ):
                raise ValueError("evaluation fields must be None when no target exists")
            return self
        if not math.isfinite(self.target):
            raise ValueError("target must be finite when present")
        if (
            self.target_achieved is None
            or self.signed_target_delta is None
            or self.normalized_target_violation is None
        ):
            raise ValueError("evaluation fields are required when a target exists")
        try:
            expected_delta = evaluate_target_delta(
                direction=self.direction,
                raw_value=self.raw_value,
                target=self.target,
                reach_tolerance=self.reach_tolerance,
            )
        except (OverflowError, ArithmeticError, ValueError):
            raise ValueError("evaluation delta derivation overflow") from None
        if expected_delta is None or not math.isfinite(expected_delta):
            raise ValueError("expected signed target delta must be finite")
        try:
            expected_violation = max(0.0, expected_delta) / self.normalization_scale
        except (OverflowError, ArithmeticError, ZeroDivisionError):
            raise ValueError("evaluation delta derivation overflow") from None
        if not math.isfinite(expected_violation):
            raise ValueError("expected normalized target violation must be finite")
        if self.signed_target_delta != expected_delta:
            raise ValueError(
                "signed_target_delta must equal the authoritative raw value, "
                "direction, target, and tolerance derivation"
            )
        if self.target_achieved != (expected_delta <= 0.0):
            raise ValueError("target_achieved must equal (expected signed target delta <= 0)")
        if self.normalized_target_violation != expected_violation:
            raise ValueError(
                "normalized_target_violation must equal "
                "max(0, expected signed target delta) / normalization_scale"
            )
        return self


class CampaignObjectiveEvaluationMatrix(VersionedContract):
    """The deterministic objective-evaluation matrix of one completed 2.0.0 campaign.

    The complete strategy x seed x objective evaluation of a completed
    runtime-2.0.0 campaign, derived exclusively from its completely
    verified Phase 21 ``CampaignMetricObservationMatrix`` and the exact
    ``ScenarioEvaluationProfile`` embedded in the campaign's compiled
    world: the campaign/scenario/world identity and world content hash,
    the runtime version (always ``"2.0.0"``), the comparison mode
    (always ``identical_conditions``), the exact source matrix
    reference, the exact evaluation profile reference, the
    authoritative scenario content hash, the exact ordered strategy,
    seed, and objective identifiers (objectives in exact
    ``ScenarioSpec`` order - no lexical ordering requirement), and the
    complete cell tuple in the exact strategy-major, seed-minor,
    objective-minor order. Every strategy/seed/objective position is in
    range, every strategy x seed x objective triple appears exactly
    once, sequence positions are contiguous from zero, and each cell's
    identities match its authoritative positions. ``evaluated_at`` is
    the authoritative Phase 21 matrix ``assembled_at`` - never the wall
    clock - and the identifier is independently derived from the
    canonical campaign/world/runtime/source/profile identity, never
    from the content hash.

    The matrix is exact value-level evaluation only: it performs no
    aggregation, produces no probability, confidence, distribution,
    risk, ranking, dominance, regret, preference, winner, evidence,
    recommendation, or decision brief, and executes, replays, extracts,
    or stores nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["2.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    source_metric_observation_matrix_id: IdentifierString
    source_metric_observation_matrix_content_hash: Sha256Hex
    evaluation_profile_id: IdentifierString
    evaluation_profile_content_hash: Sha256Hex
    scenario_content_hash: Sha256Hex
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_objective_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    cells: tuple[ObjectiveObservationEvaluation, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_evaluation_shape(self) -> CampaignObjectiveEvaluationMatrix:
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        objective_ids = list(self.ordered_objective_ids)
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("ordered_objective_ids must be unique")

        expected_count = len(strategy_ids) * len(seed_ids) * len(objective_ids)
        if len(self.cells) != expected_count:
            raise ValueError(
                "cells must cover the complete strategy x seed x objective matrix exactly"
            )

        seen_triples: set[tuple[int, int, int]] = set()
        for position, cell in enumerate(self.cells):
            if cell.sequence_position != position:
                raise ValueError("cell sequence positions must be contiguous from zero")
            if cell.strategy_position >= len(strategy_ids):
                raise ValueError("cell strategy position out of range")
            if cell.seed_position >= len(seed_ids):
                raise ValueError("cell seed position out of range")
            if cell.objective_position >= len(objective_ids):
                raise ValueError("cell objective position out of range")
            triple = (cell.strategy_position, cell.seed_position, cell.objective_position)
            if triple in seen_triples:
                raise ValueError("duplicate strategy x seed x objective cell")
            seen_triples.add(triple)
            expected_index = (cell.strategy_position * len(seed_ids) + cell.seed_position) * len(
                objective_ids
            ) + cell.objective_position
            if expected_index != position:
                raise ValueError(
                    "cells must be in the exact strategy-major, seed-minor, objective-minor order"
                )
            if cell.strategy_candidate_id != strategy_ids[cell.strategy_position]:
                raise ValueError("cell strategy identity does not match its strategy position")
            if cell.scenario_seed_id != seed_ids[cell.seed_position]:
                raise ValueError("cell seed identity does not match its seed position")
            if cell.objective_id != objective_ids[cell.objective_position]:
                raise ValueError("cell objective identity does not match its objective position")
        return self
