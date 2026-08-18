"""Pure ordered objective-paired comparison builder (KALHAS).

This module implements the single pure application builder that
transforms one verified campaign outcome-distribution matrix and one
matching campaign decision policy into the complete immutable tuple of
``ObjectivePairedComparison`` records - the ordered-pair/objective
evidence layer of the campaign decision surface.

The builder is pure and deterministic:

- it is store-free, API-free, identity-free, hash-free, query-free,
  and activity-free: it imports only the Python standard library,
  pydantic validation support, the three relevant contract types, and
  the accepted Slice 3 numeric primitives (``paired_delta_vector`` and
  ``paired_delta_statistics`` from ``campaign_decision_statistics``);
- it reads no wall clock, uses no randomness, network, providers,
  filesystem, store, API, adapters, or domain packs, and never mutates
  either input artifact;
- it performs no dominance, feasibility, regret, minimax, strategy
  selection, status, recommendation, or brief derivation of any kind -
  the records are pure paired evidence.

Input boundary
--------------

Both inputs must be exact contract instances. Before anything is
trusted, every supplied artifact is strictly revalidated from a
detached Python-mode serialization (``model_dump(mode="python")`` +
``model_validate(..., strict=True)``) with the established Pydantic
serializer-warnings suppression, so a validator-bypassed instance
(wrong-typed or non-finite raw values, booleans where integers belong,
invalid literals, malformed positions or ordering, tampered nested
records) is rejected before any field of it is read. The revalidation
result is discarded; neither artifact is ever replaced, repaired, or
normalized. The policy metadata additionally undergoes the explicit
recursive non-finite scan because strict ``JsonValue`` trees can still
carry NaN.

After revalidation the builder enforces every cross-source fact
directly represented by its two inputs: the tenant, campaign, scenario
(identity and content hash), world version (identity and content
hash), and evaluation profile (identity and content hash) must agree
exactly; the policy algorithm identifier must be the accepted literal;
the matrix comparison mode and runtime version must be the accepted
literals; the policy tail alpha and every outcome tail alpha must be
the fixed value; the policy objective-weight snapshots must match the
matrix objective order exactly with each snapshot weight equal to the
objective's authoritative matrix weight; and the inputs must carry at
least two strategies, at least one objective, and at least one seed.
Duplicate strategy/objective/seed identifiers, outcome shape, and
objective snapshot agreement are contract-enforced rules proven by the
strict revalidation. No minimum sample count is applied here: an
undersized but structurally valid matrix still produces paired
evidence, and no target threshold or hard-gate selection is applied.

Authoritative indexing
----------------------

The outcome matrix carries outcomes in exact strategy-major,
objective-minor order. Only after complete validation is an immutable
positional lookup built; for every strategy position and objective
position it verifies exactly one outcome, contiguous sequence
positions, exact strategy/objective position and identity agreement,
observed tuples of exactly the ordered seed count, empirical samples
equal to the ordered observed values, and exact objective/metric
snapshot agreement (metric id, unit, direction, target, reach
tolerance, weight, normalization scale) across every strategy of the
same objective. Seeds, strategies, and objectives are never matched
through unordered set or dict iteration - the recorded tuples define
all authoritative ordering.

Ordered-pair generation
-----------------------

For ``S`` strategies and ``O`` objectives the builder emits exactly
``S * (S - 1) * O`` records: no self-pairs, both directions of every
pair, every objective. The deterministic traversal is first strategy
position ascending, second strategy position ascending excluding self,
objective position ascending, and every record carries the exact
sequence position ``(a * (S - 1) + (b if b < a else b - 1)) * O + o``
so the positions are contiguous and the tuple is directly embeddable
in a structurally valid ``CampaignStrategyComparison``. Each record
snapshots the positions and identifiers, the metric id, the policy tie
tolerance, the ordered paired deltas in exact recorded seed order, the
win/tie/loss counts and rates, and the median/p05/p95/worst/best
paired deltas, all derived exclusively through the accepted Slice 3
primitives.

Canonical reverse construction
------------------------------

Both orientations are stored explicitly, but every unordered strategy
pair and objective computes its delta vector and statistics exactly
once in the canonical lower-position-to-higher-position direction; the
reverse record is derived from that canonical evidence by the exact
mirror rules:

- reverse deltas are the exact elementwise unary negation;
- reverse win/loss counts swap, ties are preserved, and every reverse
  rate uses the mirrored count over the same sample count;
- reverse median is the exact negated forward median;
- reverse p05 is the exact negated forward p95 and reverse p95 the
  exact negated forward p05 (Type-7 sign-flip equivariance holds
  exactly under the integer-index formulation - independently
  recomputing the reverse direction could land one ULP away);
- reverse worst is the exact negated forward best and reverse best the
  exact negated forward worst (the worst delta is orientation-
  independent: ``worst(B,A) == -best(A,B)``, never ``-worst(A,B)``).

Both orientations are cached and emitted only in the required
deterministic traversal; a reverse pair is never reconstructed outside
this builder.

Signed zeros are preserved exactly as IEEE arithmetic produces them:
the canonical direction is fixed, every reverse value is an exact
unary negation of a canonical value, and no value is ever normalized,
so repeated calls return value-identical tuples including any signed
zero representations. No ad hoc normalization is introduced.

Error semantics
---------------

Invalid structural or cross-source input raises ``ValueError``;
numeric overflow from the accepted primitives (an unrepresentable
integer or an overflowing arithmetic result) remains ``OverflowError``;
a pydantic rejection of any generated record is converted to
``ValueError``; and no partial result is ever returned - the builder
either returns the complete tuple or raises.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal, NamedTuple

from pydantic import BaseModel

from kalhas.application.campaign_decision_statistics import (
    PairedDeltaSummary,
    paired_delta_statistics,
    paired_delta_vector,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    ObjectivePairedComparison,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)

#: The accepted comparison algorithm identifier (closed literal).
_ALGORITHM_IDENTIFIER: Literal["feasibility-pareto-minimax-regret-v1"] = (
    "feasibility-pareto-minimax-regret-v1"
)

#: The required recorded outcome-matrix runtime version.
_REQUIRED_RUNTIME_VERSION: Literal["3.0.0"] = "3.0.0"

#: The fixed tail alpha shared by the policy and every outcome.
_FIXED_TAIL_ALPHA = 0.95


class _CanonicalPairEvidence(NamedTuple):
    """Immutable canonical evidence of one unordered strategy pair and objective.

    Holds the canonical lower-position-to-higher-position delta vector
    and its statistics, computed exactly once; both orientations of the
    stored pair derive from this single source.
    """

    forward_deltas: tuple[float, ...]
    forward_summary: PairedDeltaSummary


def _contains_non_finite(value: object) -> bool:
    """True when any nested ``float`` inside a JSON-like tree is non-finite."""
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_non_finite(item) for item in value.values())
    return False


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied artifact from its detached serialization.

    The artifact's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the complete contract
    is re-validated with ``strict=True``, so a validator-bypassed
    instance (wrong-typed or non-finite raw values, booleans where
    integers belong, invalid literals or hash patterns, malformed
    positions or ordering, tampered nested records) is rejected before
    any field of it is trusted. The revalidation result is discarded;
    the supplied artifact is never replaced, normalized, repaired, or
    mutated. Invalid input raises ``ValueError``.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (TypeError, AttributeError, ValueError):
        raise ValueError("supplied artifact failed strict detached revalidation") from None


def _verify_cross_source_agreement(
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> None:
    """Enforce every cross-source fact directly represented by the two inputs."""
    if policy.tenant_id != outcome_matrix.tenant_id:
        raise ValueError("policy tenant and outcome matrix tenant must agree")
    if policy.campaign_id != outcome_matrix.campaign_id:
        raise ValueError("policy campaign and outcome matrix campaign must agree")
    if policy.scenario_id != outcome_matrix.scenario_id:
        raise ValueError("policy scenario and outcome matrix scenario must agree")
    if policy.scenario_content_hash != outcome_matrix.scenario_content_hash:
        raise ValueError("policy and outcome matrix scenario content hashes must agree")
    if policy.world_version_id != outcome_matrix.world_version_id:
        raise ValueError("policy world version and outcome matrix world version must agree")
    if policy.world_content_hash != outcome_matrix.world_content_hash:
        raise ValueError("policy and outcome matrix world content hashes must agree")
    if policy.evaluation_profile_id != outcome_matrix.evaluation_profile_id:
        raise ValueError(
            "policy evaluation profile and outcome matrix evaluation profile must agree"
        )
    if policy.evaluation_profile_content_hash != outcome_matrix.evaluation_profile_content_hash:
        raise ValueError("policy and outcome matrix evaluation profile content hashes must agree")
    if policy.algorithm_identifier != _ALGORITHM_IDENTIFIER:
        raise ValueError("policy algorithm identifier is not the accepted literal")
    if outcome_matrix.comparison_mode != "identical_conditions":
        raise ValueError("outcome comparison mode must be the accepted literal")
    if outcome_matrix.runtime_version != _REQUIRED_RUNTIME_VERSION:
        raise ValueError("outcome runtime version must be the accepted literal")
    if policy.tail_alpha != _FIXED_TAIL_ALPHA:
        raise ValueError("policy tail alpha must be the fixed value")
    for outcome in outcome_matrix.outcomes:
        if outcome.tail_alpha != policy.tail_alpha:
            raise ValueError("every outcome tail alpha must equal the policy tail alpha")
    if len(outcome_matrix.ordered_strategy_candidate_ids) < 2:
        raise ValueError("paired comparison requires at least two strategies")
    if not outcome_matrix.ordered_objective_ids:
        raise ValueError("paired comparison requires at least one objective")
    if not outcome_matrix.ordered_scenario_seed_ids:
        raise ValueError("paired comparison requires at least one seed")
    snapshot_ids = [snapshot.objective_id for snapshot in policy.objective_weight_snapshots]
    if snapshot_ids != list(outcome_matrix.ordered_objective_ids):
        raise ValueError(
            "policy objective-weight snapshots must match the outcome objective order exactly"
        )
    for objective_position, snapshot in enumerate(policy.objective_weight_snapshots):
        authoritative_weight = outcome_matrix.outcomes[objective_position].weight
        if snapshot.weight != authoritative_weight:
            raise ValueError(
                "policy objective weight must equal the outcome matrix authoritative weight"
            )


def _verified_strategy_outcome_rows(
    matrix: CampaignOutcomeDistributionMatrix,
) -> tuple[tuple[StrategyObjectiveOutcome, ...], ...]:
    """The immutable strategy-major, objective-minor outcome lookup.

    Performs the authoritative positional checks for every strategy
    position and objective position: exactly one outcome, contiguous
    sequence positions, exact strategy/objective position and identity
    agreement, observed tuples of exactly the ordered seed count,
    empirical samples equal to the ordered observed values, and exact
    objective/metric snapshot agreement (metric id, unit, direction,
    target, reach tolerance, weight, normalization scale) across every
    strategy of the same objective. All ordering comes from the
    recorded tuples; no set or dict iteration is ever used.
    """
    strategy_ids = matrix.ordered_strategy_candidate_ids
    objective_ids = matrix.ordered_objective_ids
    seed_count = len(matrix.ordered_scenario_seed_ids)
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    rows: list[tuple[StrategyObjectiveOutcome, ...]] = []
    for strategy_position in range(strategy_count):
        row: list[StrategyObjectiveOutcome] = []
        for objective_position in range(objective_count):
            outcome = matrix.outcomes[strategy_position * objective_count + objective_position]
            expected_sequence = strategy_position * objective_count + objective_position
            if outcome.sequence_position != expected_sequence:
                raise ValueError(
                    "outcome sequence positions must be contiguous in the exact "
                    "strategy-major, objective-minor order"
                )
            if (
                outcome.strategy_position != strategy_position
                or outcome.objective_position != objective_position
            ):
                raise ValueError(
                    "outcome strategy/objective positions must match the recorded order"
                )
            if (
                outcome.strategy_candidate_id != strategy_ids[strategy_position]
                or outcome.objective_id != objective_ids[objective_position]
            ):
                raise ValueError("outcome identities must match their recorded positions")
            if len(outcome.ordered_observed_values) != seed_count:
                raise ValueError("outcome observed values must align with the ordered seed count")
            if outcome.empirical_distribution.ordered_samples != outcome.ordered_observed_values:
                raise ValueError("outcome empirical samples must equal the ordered observed values")
            row.append(outcome)
        rows.append(tuple(row))
    for objective_position in range(objective_count):
        reference = rows[0][objective_position]
        reference_snapshot = (
            reference.metric_id,
            reference.metric_unit,
            reference.direction,
            reference.target,
            reference.reach_tolerance,
            reference.weight,
            reference.normalization_scale,
        )
        for strategy_position in range(1, strategy_count):
            outcome = rows[strategy_position][objective_position]
            snapshot = (
                outcome.metric_id,
                outcome.metric_unit,
                outcome.direction,
                outcome.target,
                outcome.reach_tolerance,
                outcome.weight,
                outcome.normalization_scale,
            )
            if snapshot != reference_snapshot:
                raise ValueError("objective snapshots must agree exactly across strategies")
    return tuple(rows)


def _mirrored_summary(forward: PairedDeltaSummary) -> PairedDeltaSummary:
    """The exact reverse-pair summary derived from the canonical forward summary.

    The win/loss counts swap, ties are preserved, every rate uses the
    mirrored count over the same sample count, and every location and
    extremum is the exact unary negation of its forward counterpart
    with the orientation reversals: reverse p05 equals the negated
    forward p95, reverse p95 the negated forward p05, reverse worst the
    negated forward best, and reverse best the negated forward worst.
    """
    return PairedDeltaSummary(
        sample_count=forward.sample_count,
        win_count=forward.loss_count,
        tie_count=forward.tie_count,
        loss_count=forward.win_count,
        win_rate=forward.loss_rate,
        tie_rate=forward.tie_rate,
        loss_rate=forward.win_rate,
        median_paired_delta=-forward.median_paired_delta,
        p05_paired_delta=-forward.p95_paired_delta,
        p95_paired_delta=-forward.p05_paired_delta,
        worst_paired_delta=-forward.best_paired_delta,
        best_paired_delta=-forward.worst_paired_delta,
    )


def _pair_index(first: int, second: int, strategy_count: int) -> int:
    """The exact deterministic ordered-pair index formula."""
    return first * (strategy_count - 1) + (second if second < first else second - 1)


def _build_record(
    *,
    sequence_position: int,
    first_position: int,
    second_position: int,
    first_id: str,
    second_id: str,
    objective_position: int,
    objective_id: str,
    metric_id: str,
    tie_tolerance: float,
    deltas: tuple[float, ...],
    summary: PairedDeltaSummary,
) -> ObjectivePairedComparison:
    """Construct one immutable record; any pydantic rejection becomes ValueError."""
    try:
        return ObjectivePairedComparison(
            sequence_position=sequence_position,
            first_strategy_position=first_position,
            second_strategy_position=second_position,
            first_strategy_candidate_id=first_id,
            second_strategy_candidate_id=second_id,
            objective_position=objective_position,
            objective_id=objective_id,
            metric_id=metric_id,
            tie_tolerance=tie_tolerance,
            ordered_paired_deltas=deltas,
            win_count=summary.win_count,
            tie_count=summary.tie_count,
            loss_count=summary.loss_count,
            win_rate=summary.win_rate,
            tie_rate=summary.tie_rate,
            loss_rate=summary.loss_rate,
            median_paired_delta=summary.median_paired_delta,
            p05_paired_delta=summary.p05_paired_delta,
            p95_paired_delta=summary.p95_paired_delta,
            worst_paired_delta=summary.worst_paired_delta,
            best_paired_delta=summary.best_paired_delta,
        )
    except ValueError as exc:
        raise ValueError("generated paired comparison violates its contract") from exc


def _build_paired_comparisons(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> tuple[ObjectivePairedComparison, ...]:
    """The complete validated construction pipeline (see the public builder)."""
    _strictly_revalidate_detached(policy, CampaignDecisionPolicy)
    _strictly_revalidate_detached(outcome_matrix, CampaignOutcomeDistributionMatrix)
    if _contains_non_finite(policy.metadata):
        raise ValueError("policy metadata must not contain non-finite floats")
    _verify_cross_source_agreement(policy, outcome_matrix)
    rows = _verified_strategy_outcome_rows(outcome_matrix)
    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    objective_ids = outcome_matrix.ordered_objective_ids
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    tie_tolerance = policy.tie_tolerance

    # Canonical lower-position-to-higher-position evidence, computed
    # exactly once per unordered strategy pair and objective.
    canonical: dict[tuple[int, int, int], _CanonicalPairEvidence] = {}
    for lower in range(strategy_count):
        for higher in range(lower + 1, strategy_count):
            for objective_position in range(objective_count):
                lower_outcome = rows[lower][objective_position]
                higher_outcome = rows[higher][objective_position]
                deltas = paired_delta_vector(
                    lower_outcome.ordered_observed_values,
                    higher_outcome.ordered_observed_values,
                    direction=lower_outcome.direction,
                    normalization_scale=lower_outcome.normalization_scale,
                    target=lower_outcome.target,
                )
                summary = paired_delta_statistics(deltas, tie_tolerance=tie_tolerance)
                canonical[(lower, higher, objective_position)] = _CanonicalPairEvidence(
                    forward_deltas=deltas, forward_summary=summary
                )

    # Both orientations of every unordered pair are cached and emitted
    # only in the required deterministic ordered-pair traversal.
    cached_pairs: dict[
        tuple[int, int, int], tuple[ObjectivePairedComparison, ObjectivePairedComparison]
    ] = {}
    for lower in range(strategy_count):
        for higher in range(lower + 1, strategy_count):
            for objective_position in range(objective_count):
                evidence = canonical[(lower, higher, objective_position)]
                forward_record = _build_record(
                    sequence_position=_pair_index(lower, higher, strategy_count) * objective_count
                    + objective_position,
                    first_position=lower,
                    second_position=higher,
                    first_id=strategy_ids[lower],
                    second_id=strategy_ids[higher],
                    objective_position=objective_position,
                    objective_id=objective_ids[objective_position],
                    metric_id=rows[lower][objective_position].metric_id,
                    tie_tolerance=tie_tolerance,
                    deltas=evidence.forward_deltas,
                    summary=evidence.forward_summary,
                )
                reverse_record = _build_record(
                    sequence_position=_pair_index(higher, lower, strategy_count) * objective_count
                    + objective_position,
                    first_position=higher,
                    second_position=lower,
                    first_id=strategy_ids[higher],
                    second_id=strategy_ids[lower],
                    objective_position=objective_position,
                    objective_id=objective_ids[objective_position],
                    metric_id=rows[lower][objective_position].metric_id,
                    tie_tolerance=tie_tolerance,
                    deltas=tuple(-delta for delta in evidence.forward_deltas),
                    summary=_mirrored_summary(evidence.forward_summary),
                )
                cached_pairs[(lower, higher, objective_position)] = (
                    forward_record,
                    reverse_record,
                )

    comparisons: list[ObjectivePairedComparison] = []
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            for objective_position in range(objective_count):
                lower, higher = (first, second) if first < second else (second, first)
                forward_record, reverse_record = cached_pairs[(lower, higher, objective_position)]
                comparisons.append(forward_record if first < second else reverse_record)
    return tuple(comparisons)


def build_ordered_objective_paired_comparisons(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> tuple[ObjectivePairedComparison, ...]:
    """Build the complete immutable ordered-pair comparison tuple.

    Transforms one verified outcome matrix and one matching decision
    policy into the exact ``S * (S - 1) * O`` ``ObjectivePairedComparison``
    records in the deterministic pair-major, objective-minor order.
    Both inputs must be exact contract instances and are strictly
    revalidated from detached Python-mode serialization before any
    field is trusted; every cross-source fact directly represented by
    the two inputs is then enforced, the authoritative positional
    outcome lookup is built, and every unordered strategy pair and
    objective computes its canonical lower-to-higher delta vector and
    statistics exactly once while both orientations are derived and
    cached from that single source. No minimum sample count, target
    threshold, or hard-gate selection is applied, and no dominance,
    feasibility, regret, minimax, status, recommendation, or brief
    logic exists here. Invalid structural or cross-source input raises
    ``ValueError``; numeric overflow from the accepted primitives
    remains ``OverflowError``; a pydantic rejection of any generated
    record is converted to ``ValueError``; no partial result is ever
    returned and neither input is ever mutated.
    """
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    try:
        return _build_paired_comparisons(policy=policy, outcome_matrix=outcome_matrix)
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError("paired comparison construction failed on malformed input") from exc


__all__ = ["build_ordered_objective_paired_comparisons"]
