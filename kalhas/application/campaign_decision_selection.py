"""Pure deterministic Pareto-dominance and minimax-regret layer (KALHAS).

This module implements the pure application builders that transform
one verified campaign outcome-distribution matrix, one matching
campaign decision policy, and the complete supplied tuple of
``ObjectivePairedComparison`` records into the immutable dominance and
weighted-regret assessments of the campaign decision surface:

- ``build_campaign_pareto_dominance``: the accepted evidence
  assessment (the sole feasibility source), the complete factual
  ordered-pair dominance relations with exact per-objective statuses
  read from the supplied paired records, the factual
  dominated-by/dominates identifier tuples for every strategy, and the
  feasible-only non-dominated strategy subset;
- ``build_campaign_minimax_regret``: the same-seed per-objective
  regret of every strategy against all strategies (feasible,
  infeasible, dominated and non-dominated alike) through the accepted
  Slice 3 numeric primitives, the weighted per-objective mean regrets
  with the exact non-normalized matrix weights, the per-seed total
  weighted regret vectors in exact seed order with their
  median/p95/maximum statistics, the feasible non-dominated minimax
  candidate set, the exact inclusive minimax tie set under the policy
  tie tolerance, and the unique minimax strategy identity when exactly
  one candidate is justified.

Both builders are pure and deterministic:

- they are store-free, API-free, identity-free, hash-free,
  query-free, terminal-selection-free, and activity-free: they import
  only the Python standard library, pydantic validation support, the
  two relevant contract modules, the accepted Slice 5 evidence
  builder, and the accepted Slice 3 statistics primitives. They never
  import the paired-comparison builder - the paired records are
  supplied evidence and are never rebuilt, repaired, or reconstructed
  - and never import stores, services, API, identity/hash modules,
  adapters, domain packs, NEXUS, or LEGION;
- they read no wall clock, use no randomness, network, providers,
  filesystem, store, API, adapters, or domain packs, and never mutate
  any input;
- they perform no paired-delta recomputation, no target-feasibility
  recomputation outside the accepted evidence builder, no terminal
  decision status (preferred/inconclusive/insufficient/no-feasible),
  no reason or factor records, no comparison or brief assembly, no
  identity or content hashing, and no persistence or API behavior.
  The later pipeline owns the terminal sufficiency rule; these layers
  only report the factual dominance and algorithmic minimax facts.

Input boundary
--------------

All three inputs must be exact contract instances;
``paired_comparisons`` must be an exact ``tuple`` (never a list or
another iterable) of exact ``ObjectivePairedComparison`` instances.
The accepted evidence builder owns the strict policy/matrix
validation; its ``ValueError`` and ``OverflowError`` semantics
propagate unchanged, and its returned assessment is the sole
feasibility source. Every supplied paired record is additionally
strictly revalidated from a detached Python-mode serialization
(``model_dump(mode="python")`` + ``model_validate(..., strict=True)``)
with the established Pydantic serializer-warnings suppression, so a
validator-bypassed record (wrong-typed or non-finite raw values,
booleans where integers belong, tampered nested fields) is rejected
before any field of it is trusted. The revalidation result is
discarded; no record is ever replaced, repaired, normalized, sorted,
or mutated.

Paired-matrix validation
------------------------

Before any dominance output is constructed the supplied paired tuple
is independently verified against the policy and the outcome matrix:
exactly ``S * (S - 1) * O`` records; the deterministic pair-major,
objective-minor ordering formula ``pair_index * O + objective_position``
with ``pair_index = first * (S - 1) + (second if second < first else
second - 1)`` and contiguous sequence positions; no self-pairs; both
orientations of every unordered pair and objective; exact position and
identity agreement; metric ids equal to the authoritative matrix
objective metric snapshot; tie tolerance equal to the policy tolerance
exactly; delta counts equal to the recorded seed count; and the exact
reverse-pair invariants (elementwise exact delta negation, mirrored
win/tie/loss counts, negated median, negated p05/p95 swap, and
negated worst/best swap). A missing, additional, duplicated, or
reordered record is rejected; a reverse record is never generated,
repaired, normalized, sorted, or replaced. Validation always finishes
before any relation or assessment is returned.

Per-objective status semantics
------------------------------

For every supplied ordered-pair/objective record the status is derived
exactly from its recorded counts: ``worse`` when ``loss_count > 0``,
``better`` when no losses and at least one win, ``tied`` when every
paired delta is a tie. The exact tolerance boundaries remain ties
because the accepted paired record already owns the classification;
no quantile, mean, target probability, downside statistic, or regret
is ever inspected for dominance. One ``DominanceRelation`` is
constructed per ordered strategy pair with one per-objective status in
objective order; the relation's factual flag is true exactly when no
status is ``worse`` and at least one is ``better``. The reverse
relation is read from its own supplied reverse records - never
inferred by swapping statuses - so crossing seed-level performance may
validly produce ``worse`` in both directions and mutual dominance
never occurs.

Feasible-only Pareto subset
---------------------------

The accepted evidence assessment is the sole feasibility source. A
strategy is non-dominated among feasible strategies exactly when it is
feasible and no other feasible strategy factually dominates it; an
infeasible strategy may carry factual dominance relations but never
enters the subset, and an infeasible factual dominator never removes a
feasible strategy. Zero feasible strategies yield an empty tuple, a
single feasible strategy a singleton, and all-feasible ties every
feasible strategy. The factual dominated-by/dominates tuples are never
filtered by feasibility.

Same-seed weighted regret semantics
-----------------------------------

For every objective and seed the same-seed regret vector over ALL
supplied strategies in authoritative strategy order is computed by the
accepted ``same_seed_regret`` primitive (minimize: ``(value -
same-seed minimum) / scale``; maximize: ``(same-seed maximum - value)
/ scale``; reach: ``(abs(value - target) - same-seed minimum absolute
deviation) / scale``). The comparator always includes infeasible and
dominated strategies; same-seed alignment is mandatory, independent
means are never compared, and no sorting, clipping, negative-value
repair, or target-violation substitution ever happens. One
``ObjectiveRegretEvidence`` per objective in authoritative objective
order carries ``objective_weighted_mean_regret(per_seed_regrets,
weight=authoritative_weight)`` with the exact non-normalized matrix
weights (all-zero weights remain valid). Per strategy the objective-
major per-seed regret matrix is passed to the accepted
``total_regret_vector`` primitive (exact recorded seed order
preserved) and the resulting per-seed total weighted regrets to the
accepted ``total_regret_statistics`` primitive; the median/p95/
maximum results are copied without duplication. Every strategy -
feasible, infeasible, dominated and non-dominated alike - receives one
complete ``StrategyRegretAssessment`` in authoritative strategy order.

Minimax semantics
-----------------

``minimax_candidate_ids`` copies the Pareto assessment's feasible
non-dominated strategy ids and remains factual even when evidence is
insufficient. Minimax is evaluated exactly when the accepted evidence
assessment reports sufficiency and the candidate set is non-empty;
otherwise the best/tie/unique fields stay ``None``/empty while the
complete regret assessments are still returned. When evaluated, the
best maximum total weighted regret is the minimum over the candidates
and the exact inclusive tie set contains every candidate whose maximum
total weighted regret is at most ``best + policy.tie_tolerance``
(exact IEEE comparison, inclusive boundary, no ``isclose``, no
relative tolerance, no ULP relaxation, no rounding, no arbitrary
winner); the unique minimax strategy identity is present exactly when
the tie set is a singleton. A non-finite best-plus-tolerance boundary
raises ``OverflowError``. This layer derives no terminal status and
never calls the identity "preferred".

All ordering comes exclusively from the recorded tuples and ranges of
the three artifacts; dicts are used only for validated positional
lookup and their iteration is never an ordering authority.

Error semantics
---------------

Invalid structural, source, cardinality, ordering, coverage, identity,
metric, tolerance, seed-count, or reverse-invariant input raises
``ValueError``; a numeric representability overflow raised by strict
validation is never converted (``OverflowError`` propagates); a pydantic
rejection of any generated record is converted to ``ValueError``;
every ``OverflowError`` from the accepted primitives or from a
non-finite minimax boundary remains ``OverflowError``; and no partial
result is ever returned - each builder either returns the complete
assessment or raises. The minimax builder additionally re-verifies,
defensively, that the returned Pareto assessment aligns exactly with
the matrix (one dominance and one evidence strategy assessment per
strategy with contiguous positions, exact identities/order and
identical feasibility, a matching evidence sample count, the complete
``S * (S - 1)`` dominance-relation tuple in exact authoritative pair
order with reverse coverage and no mutual dominance, dominated-by/
dominates tuples and non-dominated-among-feasible flags re-derived
from the supplied factual relations, the non-dominated feasible
strategy id tuple equal to the exact complete derivation - no omitted,
additional, reordered, duplicated, unknown, infeasible or factually
dominated candidate and no forged flags - complete outcome rows with
matching observed lengths and snapshot agreement, and policy weight
agreement) so an internally inconsistent injected assessment fails
safely before any regret arithmetic.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal, NamedTuple

from pydantic import BaseModel

from kalhas.application.campaign_decision_evidence import (
    CampaignDecisionEvidenceAssessment,
    build_campaign_decision_evidence,
)
from kalhas.application.campaign_decision_statistics import (
    objective_weighted_mean_regret,
    same_seed_regret,
    total_regret_statistics,
    total_regret_vector,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    DominanceRelation,
    ObjectiveDominanceStatus,
    ObjectivePairedComparison,
    ObjectiveRegretEvidence,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)


class StrategyDominanceAssessment(NamedTuple):
    """Immutable per-strategy factual dominance assessment.

    Binds one strategy to its pipeline feasibility flag (copied from
    the accepted evidence assessment), its ordered factual
    ``dominated_by`` and ``dominates`` identifier tuples (never
    filtered by feasibility), and its exact membership in the
    feasible-only non-dominated strategy subset.
    """

    strategy_position: int
    strategy_candidate_id: str
    feasible: bool
    dominated_by: tuple[str, ...]
    dominates: tuple[str, ...]
    non_dominated_among_feasible: bool


class CampaignParetoDominanceAssessment(NamedTuple):
    """Immutable complete Pareto-dominance assessment.

    Binds the accepted evidence assessment (the sole feasibility
    source), the complete ``S * (S - 1)`` factual ``DominanceRelation``
    tuple in exact pair order, the ordered per-strategy
    ``StrategyDominanceAssessment`` records, and the feasible-only
    non-dominated strategy ids in authoritative strategy order. This
    layer derives no terminal decision status; the later pipeline owns
    the terminal rules.
    """

    evidence_assessment: CampaignDecisionEvidenceAssessment
    dominance_relations: tuple[DominanceRelation, ...]
    strategy_assessments: tuple[StrategyDominanceAssessment, ...]
    non_dominated_feasible_strategy_ids: tuple[str, ...]


class StrategyRegretAssessment(NamedTuple):
    """Immutable per-strategy weighted-regret assessment.

    Binds one strategy to its ordered per-objective
    ``ObjectiveRegretEvidence`` records (authoritative objective order,
    exact non-normalized weights), its per-seed total weighted regrets
    in exact recorded seed order, and the median/p95/maximum statistics
    of that vector copied from the accepted statistics primitive. One
    record exists per strategy - feasible, infeasible, dominated and
    non-dominated alike - in authoritative strategy order.
    """

    strategy_position: int
    strategy_candidate_id: str
    per_objective_weighted_regret: tuple[ObjectiveRegretEvidence, ...]
    per_seed_total_weighted_regrets: tuple[float, ...]
    median_total_weighted_regret: float
    p95_total_weighted_regret: float
    maximum_total_weighted_regret: float


class CampaignMinimaxRegretAssessment(NamedTuple):
    """Immutable complete weighted-regret and minimax assessment.

    Binds the authoritative Pareto dominance assessment (the sole
    source of evidence sufficiency, strategy feasibility, factual
    dominance, and the feasible non-dominated minimax candidates), the
    ordered per-strategy ``StrategyRegretAssessment`` records, the
    factual minimax candidate ids, the exact evaluated flag, and - when
    evaluated - the best maximum total weighted regret, the exact
    inclusive minimax tie set under the policy tie tolerance, and the
    unique minimax strategy identity when exactly one candidate is
    justified. This layer derives no terminal decision status.
    """

    pareto_assessment: CampaignParetoDominanceAssessment
    strategy_regret_assessments: tuple[StrategyRegretAssessment, ...]
    minimax_candidate_ids: tuple[str, ...]
    minimax_evaluated: bool
    best_maximum_total_weighted_regret: float | None
    minimax_tie_strategy_ids: tuple[str, ...]
    unique_minimax_strategy_id: str | None


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied paired record from its detached serialization.

    The record's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the complete contract
    is re-validated with ``strict=True``, so a validator-bypassed
    instance (wrong-typed or non-finite raw values, booleans where
    integers belong, tampered nested fields) is rejected before any
    field of it is trusted. The revalidation result is discarded; the
    supplied record is never replaced, normalized, repaired, or
    mutated. Invalid input raises ``ValueError``; a numeric
    representability overflow raised during strict validation is never
    converted and propagates as ``OverflowError``.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (TypeError, AttributeError, ValueError):
        raise ValueError("supplied paired record failed strict detached revalidation") from None


def _pair_index(first: int, second: int, strategy_count: int) -> int:
    """The exact deterministic ordered-pair index formula."""
    return first * (strategy_count - 1) + (second if second < first else second - 1)


def _verify_reverse_mirror(
    forward: ObjectivePairedComparison,
    reverse: ObjectivePairedComparison,
) -> None:
    """Enforce the exact reverse-pair invariants between two supplied records."""
    if reverse.ordered_paired_deltas != tuple(-delta for delta in forward.ordered_paired_deltas):
        raise ValueError("reverse-pair deltas must be exact negations of the forward deltas")
    if (
        reverse.win_count != forward.loss_count
        or reverse.loss_count != forward.win_count
        or reverse.tie_count != forward.tie_count
    ):
        raise ValueError("reverse-pair win/tie/loss counts must mirror the forward counts")
    if reverse.median_paired_delta != -forward.median_paired_delta:
        raise ValueError("reverse-pair median must equal the negated forward median")
    if reverse.p05_paired_delta != -forward.p95_paired_delta:
        raise ValueError("reverse-pair p05 must equal the negated forward p95")
    if reverse.p95_paired_delta != -forward.p05_paired_delta:
        raise ValueError("reverse-pair p95 must equal the negated forward p05")
    if reverse.worst_paired_delta != -forward.best_paired_delta:
        raise ValueError("reverse-pair worst must equal the negated forward best")
    if reverse.best_paired_delta != -forward.worst_paired_delta:
        raise ValueError("reverse-pair best must equal the negated forward worst")


def _derive_status(record: ObjectivePairedComparison) -> ObjectiveDominanceStatus:
    """One per-objective dominance status copied from one supplied forward record.

    The status is derived exactly from the recorded counts (``worse``
    requires at least one loss, ``better`` requires no losses and at
    least one win, ``tied`` requires every paired delta to be a tie)
    and copies the objective identity, win/tie/loss counts, and median
    paired delta exactly; any pydantic rejection of the generated
    record becomes ``ValueError``.
    """
    status: Literal["better", "tied", "worse"]
    if record.loss_count > 0:
        status = "worse"
    elif record.win_count > 0:
        status = "better"
    else:
        status = "tied"
    try:
        return ObjectiveDominanceStatus(
            objective_id=record.objective_id,
            status=status,
            win_count=record.win_count,
            tie_count=record.tie_count,
            loss_count=record.loss_count,
            median_paired_delta=record.median_paired_delta,
        )
    except ValueError as exc:
        raise ValueError("generated objective dominance status violates its contract") from exc


def _build_relation(
    first: int,
    second: int,
    strategy_ids: tuple[str, ...],
    statuses: tuple[ObjectiveDominanceStatus, ...],
) -> DominanceRelation:
    """One factual dominance relation for one ordered strategy pair.

    The factual flag is true exactly when no per-objective status is
    ``worse`` and at least one is ``better``; any pydantic rejection of
    the generated relation becomes ``ValueError``.
    """
    relation_statuses = [status.status for status in statuses]
    dominates = "worse" not in relation_statuses and "better" in relation_statuses
    try:
        return DominanceRelation(
            first_strategy_position=first,
            second_strategy_position=second,
            first_strategy_candidate_id=strategy_ids[first],
            second_strategy_candidate_id=strategy_ids[second],
            dominates=dominates,
            per_objective_status=statuses,
        )
    except ValueError as exc:
        raise ValueError("generated dominance relation violates its contract") from exc


def _build_pareto_dominance(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    paired_comparisons: tuple[ObjectivePairedComparison, ...],
) -> CampaignParetoDominanceAssessment:
    """The complete validated construction pipeline (see the public builder)."""
    evidence = build_campaign_decision_evidence(policy=policy, outcome_matrix=outcome_matrix)

    for record in paired_comparisons:
        _strictly_revalidate_detached(record, ObjectivePairedComparison)

    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    objective_ids = outcome_matrix.ordered_objective_ids
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)
    expected_record_count = strategy_count * (strategy_count - 1) * objective_count
    if len(paired_comparisons) != expected_record_count:
        raise ValueError("paired_comparisons must contain exactly S * (S - 1) * O records")
    authoritative_metric_ids = tuple(
        outcome_matrix.outcomes[objective_position].metric_id
        for objective_position in range(objective_count)
    )

    records_by_key: dict[tuple[int, int, int], ObjectivePairedComparison] = {}
    for position, record in enumerate(paired_comparisons):
        first = record.first_strategy_position
        second = record.second_strategy_position
        objective_position = record.objective_position
        if first >= strategy_count or second >= strategy_count or first == second:
            raise ValueError("paired comparison strategy positions must be in range and differ")
        if objective_position >= objective_count:
            raise ValueError("paired comparison objective position out of range")
        expected_position = (
            _pair_index(first, second, strategy_count) * objective_count + objective_position
        )
        if record.sequence_position != position or expected_position != position:
            raise ValueError(
                "paired comparisons must be contiguous in the exact pair-major, "
                "objective-minor order"
            )
        if record.first_strategy_candidate_id != strategy_ids[first]:
            raise ValueError("paired comparison first strategy identity mismatch")
        if record.second_strategy_candidate_id != strategy_ids[second]:
            raise ValueError("paired comparison second strategy identity mismatch")
        if record.objective_id != objective_ids[objective_position]:
            raise ValueError("paired comparison objective identity mismatch")
        if record.metric_id != authoritative_metric_ids[objective_position]:
            raise ValueError(
                "paired comparison metric must equal the authoritative matrix objective metric"
            )
        if record.tie_tolerance != policy.tie_tolerance:
            raise ValueError("paired comparison tie tolerance must equal the policy tolerance")
        if len(record.ordered_paired_deltas) != seed_count:
            raise ValueError("paired comparison delta count must equal the recorded seed count")
        key = (first, second, objective_position)
        if key in records_by_key:
            raise ValueError("duplicate ordered pair/objective paired comparison")
        records_by_key[key] = record

    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            for objective_position in range(objective_count):
                forward = records_by_key[(first, second, objective_position)]
                reverse = records_by_key.get((second, first, objective_position))
                if reverse is None:
                    raise ValueError("missing reverse-pair comparison")
                _verify_reverse_mirror(forward, reverse)

    relations: list[DominanceRelation] = []
    relations_by_pair: dict[tuple[int, int], DominanceRelation] = {}
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            statuses = tuple(
                _derive_status(records_by_key[(first, second, objective_position)])
                for objective_position in range(objective_count)
            )
            relation = _build_relation(first, second, strategy_ids, statuses)
            relations.append(relation)
            relations_by_pair[(first, second)] = relation

    for (first, second), relation in relations_by_pair.items():
        if relation.dominates and relations_by_pair[(second, first)].dominates:
            raise ValueError("a strategy pair cannot dominate each other")

    evidence_assessments = evidence.strategy_assessments
    if len(evidence_assessments) != strategy_count:
        raise ValueError("evidence strategy assessments must align with the outcome matrix")
    for position, assessment in enumerate(evidence_assessments):
        if (
            assessment.strategy_position != position
            or assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("evidence strategy assessment identity mismatch")
    feasible_by_position = tuple(assessment.feasible for assessment in evidence_assessments)

    non_dominated_ids: list[str] = []
    for position in range(strategy_count):
        if not feasible_by_position[position]:
            continue
        dominated_by_feasible = any(
            feasible_by_position[dominator] and relations_by_pair[(dominator, position)].dominates
            for dominator in range(strategy_count)
            if dominator != position
        )
        if not dominated_by_feasible:
            non_dominated_ids.append(strategy_ids[position])
    non_dominated_set = set(non_dominated_ids)

    strategy_assessments: list[StrategyDominanceAssessment] = []
    for position in range(strategy_count):
        dominated_by = tuple(
            strategy_ids[dominator]
            for dominator in range(strategy_count)
            if dominator != position and relations_by_pair[(dominator, position)].dominates
        )
        dominates = tuple(
            strategy_ids[dominated]
            for dominated in range(strategy_count)
            if dominated != position and relations_by_pair[(position, dominated)].dominates
        )
        strategy_assessments.append(
            StrategyDominanceAssessment(
                strategy_position=position,
                strategy_candidate_id=strategy_ids[position],
                feasible=feasible_by_position[position],
                dominated_by=dominated_by,
                dominates=dominates,
                non_dominated_among_feasible=strategy_ids[position] in non_dominated_set,
            )
        )

    return CampaignParetoDominanceAssessment(
        evidence_assessment=evidence,
        dominance_relations=tuple(relations),
        strategy_assessments=tuple(strategy_assessments),
        non_dominated_feasible_strategy_ids=tuple(non_dominated_ids),
    )


def build_campaign_pareto_dominance(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    paired_comparisons: tuple[ObjectivePairedComparison, ...],
) -> CampaignParetoDominanceAssessment:
    """Build the complete immutable Pareto-dominance assessment.

    Transforms one verified outcome matrix, one matching decision
    policy, and the complete supplied ``ObjectivePairedComparison``
    tuple into the complete factual ``CampaignParetoDominanceAssessment``:
    the accepted evidence assessment (the sole feasibility source, from
    exactly one call to the accepted evidence builder), the complete
    ``S * (S - 1)`` dominance relations with per-objective statuses
    read from the supplied forward paired records, the factual
    dominated-by/dominates identifier tuples for every strategy, and
    the feasible-only non-dominated strategy subset. The paired tuple
    must be an exact ``tuple`` of exact ``ObjectivePairedComparison``
    instances; every record is strictly revalidated from detached
    serialization, and the complete paired matrix - cardinality,
    deterministic ordering, positions, identities, metric snapshots,
    tie tolerance, seed count, both-direction coverage, and every
    reverse-pair invariant - is verified before any output is
    constructed. No paired-delta or target-feasibility recomputation,
    weighted regret, per-seed regret totals, minimax, tie-set
    selection, terminal status, reason/factor record, comparison/brief
    assembly, identity/hash, persistence, or API behavior exists here.
    Invalid structural or cross-source input raises ``ValueError``; the
    accepted evidence builder's ``ValueError`` and ``OverflowError``
    semantics propagate unchanged; a pydantic rejection of any
    generated record is converted to ``ValueError``; no partial result
    is ever returned and no input is ever mutated.
    """
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    if type(paired_comparisons) is not tuple:
        raise ValueError("paired_comparisons must be an exact tuple")
    for record in paired_comparisons:
        if not isinstance(record, ObjectivePairedComparison):
            raise ValueError(
                "every paired comparison must be an ObjectivePairedComparison instance"
            )
    try:
        return _build_pareto_dominance(
            policy=policy,
            outcome_matrix=outcome_matrix,
            paired_comparisons=paired_comparisons,
        )
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError(
            "campaign pareto dominance construction failed on malformed input"
        ) from exc


def _verified_outcome_rows(
    matrix: CampaignOutcomeDistributionMatrix,
) -> tuple[tuple[StrategyObjectiveOutcome, ...], ...]:
    """The immutable strategy-major, objective-minor outcome lookup, re-verified.

    Defensively re-proves the essential positional and snapshot facts
    directly from the supplied matrix before any regret arithmetic: the
    complete strategy x objective coverage with contiguous sequence
    positions and exact position/identity agreement, observed tuples of
    exactly the ordered seed count, and identical objective snapshots
    (metric id, direction, target, reach tolerance, weight,
    normalization scale) across every strategy of the same objective.
    All ordering comes from the recorded tuples; no set or dict
    iteration is ever used as an ordering authority.
    """
    strategy_ids = matrix.ordered_strategy_candidate_ids
    objective_ids = matrix.ordered_objective_ids
    seed_count = len(matrix.ordered_scenario_seed_ids)
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    if len(matrix.outcomes) != strategy_count * objective_count:
        raise ValueError("outcomes must cover every strategy x objective pair exactly once")
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
                raise ValueError("outcome positions must match the recorded order")
            if (
                outcome.strategy_candidate_id != strategy_ids[strategy_position]
                or outcome.objective_id != objective_ids[objective_position]
            ):
                raise ValueError("outcome identities must match their recorded positions")
            if len(outcome.ordered_observed_values) != seed_count:
                raise ValueError("outcome observed values must align with the ordered seed count")
            row.append(outcome)
        rows.append(tuple(row))
    for objective_position in range(objective_count):
        reference = rows[0][objective_position]
        reference_snapshot = (
            reference.metric_id,
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
                outcome.direction,
                outcome.target,
                outcome.reach_tolerance,
                outcome.weight,
                outcome.normalization_scale,
            )
            if snapshot != reference_snapshot:
                raise ValueError("objective snapshots must agree exactly across strategies")
    return tuple(rows)


def _verify_pareto_alignment(
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    pareto_assessment: CampaignParetoDominanceAssessment,
) -> tuple[tuple[StrategyObjectiveOutcome, ...], ...]:
    """Prove the supplied Pareto assessment aligns exactly with the matrix.

    The accepted builder already proves these facts; this layer re-checks
    the alignment defensively so a monkeypatched or internally
    inconsistent returned assessment fails safely before any regret
    arithmetic. The complete cross-verification covers:

    - one dominance strategy assessment per strategy with contiguous
      positions and exact strategy identities/order;
    - one evidence strategy assessment per strategy aligned with the
      dominance assessment (same position, same strategy id, identical
      feasible flag) and an evidence recorded sample count equal to the
      matrix seed count;
    - the complete ``S * (S - 1)`` dominance-relation tuple in the
      exact authoritative ordered-pair order with exact
      ``DominanceRelation`` instances, in-range differing positions,
      exact first/second identities, reverse coverage for every pair,
      and no mutual dominance;
    - per-strategy dominated-by/dominates tuples re-derived from the
      supplied factual relations in authoritative other-strategy
      order;
    - per-strategy non-dominated-among-feasible flags re-derived from
      feasibility plus the complete factual relations (an infeasible
      dominator never excludes a feasible strategy);
    - the non-dominated feasible strategy id tuple equal to the exact
      complete derivation - no omitted, additional, reordered,
      duplicated, unknown, infeasible or factually dominated candidate
      and no forged flags - the tuple is never sorted, completed,
      repaired, or normalized;
    - complete outcome rows with matching observed lengths and
      snapshot agreement, and policy weight ids/order/values equal to
      the verified matrix objective snapshots.

    Returns the verified strategy-major outcome rows.
    """
    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    objective_ids = outcome_matrix.ordered_objective_ids
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)
    strategy_count = len(strategy_ids)

    strategy_assessments = pareto_assessment.strategy_assessments
    if type(strategy_assessments) is not tuple:
        raise ValueError("pareto strategy assessments must be an exact tuple")
    if len(strategy_assessments) != strategy_count:
        raise ValueError("pareto strategy assessments must align with the outcome matrix")
    for position, assessment in enumerate(strategy_assessments):
        if (
            assessment.strategy_position != position
            or assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("pareto strategy assessment identity mismatch")

    evidence = pareto_assessment.evidence_assessment
    if evidence.recorded_sample_count != seed_count:
        raise ValueError("evidence recorded sample count must equal the matrix seed count")
    evidence_assessments = evidence.strategy_assessments
    if type(evidence_assessments) is not tuple:
        raise ValueError("evidence strategy assessments must be an exact tuple")
    if len(evidence_assessments) != strategy_count:
        raise ValueError("evidence strategy assessments must align with the outcome matrix")
    for position, evidence_assessment in enumerate(evidence_assessments):
        if (
            evidence_assessment.strategy_position != position
            or evidence_assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("evidence strategy assessment identity mismatch")
        if strategy_assessments[position].feasible is not evidence_assessment.feasible:
            raise ValueError("dominance feasibility must equal the evidence feasibility exactly")

    relations = pareto_assessment.dominance_relations
    if type(relations) is not tuple:
        raise ValueError("dominance relations must be an exact tuple")
    if len(relations) != strategy_count * (strategy_count - 1):
        raise ValueError("dominance relations must cover every ordered strategy pair exactly once")
    relations_by_pair: dict[tuple[int, int], DominanceRelation] = {}
    for position, relation in enumerate(relations):
        if not isinstance(relation, DominanceRelation):
            raise ValueError("every dominance relation must be a DominanceRelation instance")
        first = relation.first_strategy_position
        second = relation.second_strategy_position
        if first >= strategy_count or second >= strategy_count or first == second:
            raise ValueError("dominance relation strategy positions must be in range and differ")
        if position != _pair_index(first, second, strategy_count):
            raise ValueError(
                "dominance relations must be contiguous in the exact ordered-pair order"
            )
        if relation.first_strategy_candidate_id != strategy_ids[first]:
            raise ValueError("dominance relation first strategy identity mismatch")
        if relation.second_strategy_candidate_id != strategy_ids[second]:
            raise ValueError("dominance relation second strategy identity mismatch")
        if type(relation.dominates) is not bool:
            raise ValueError("dominance relation dominates flag must be a bool")
        key = (first, second)
        if key in relations_by_pair:
            raise ValueError("duplicate dominance relation for an ordered pair")
        relations_by_pair[key] = relation
    for (first, second), relation in relations_by_pair.items():
        reverse = relations_by_pair.get((second, first))
        if reverse is None:
            raise ValueError("missing reverse-pair dominance relation")
        if relation.dominates and reverse.dominates:
            raise ValueError("a strategy pair cannot dominate each other")

    feasible_by_position = tuple(assessment.feasible for assessment in strategy_assessments)
    expected_non_dominated_flags: list[bool] = []
    for position in range(strategy_count):
        expected_dominated_by = tuple(
            strategy_ids[dominator]
            for dominator in range(strategy_count)
            if dominator != position and relations_by_pair[(dominator, position)].dominates is True
        )
        expected_dominates = tuple(
            strategy_ids[dominated]
            for dominated in range(strategy_count)
            if dominated != position and relations_by_pair[(position, dominated)].dominates is True
        )
        assessment = strategy_assessments[position]
        if assessment.dominated_by != expected_dominated_by:
            raise ValueError("strategy dominated_by must equal the factual relation-derived tuple")
        if assessment.dominates != expected_dominates:
            raise ValueError("strategy dominates must equal the factual relation-derived tuple")
        expected_non_dominated = feasible_by_position[position] is True and not any(
            feasible_by_position[dominator] is True
            and relations_by_pair[(dominator, position)].dominates is True
            for dominator in range(strategy_count)
            if dominator != position
        )
        if assessment.non_dominated_among_feasible is not expected_non_dominated:
            raise ValueError(
                "non_dominated_among_feasible must equal the feasible factual derivation"
            )
        expected_non_dominated_flags.append(expected_non_dominated)

    candidate_ids = pareto_assessment.non_dominated_feasible_strategy_ids
    if type(candidate_ids) is not tuple:
        raise ValueError("minimax candidate ids must be an exact tuple")
    expected_candidate_ids = tuple(
        strategy_ids[position]
        for position in range(strategy_count)
        if expected_non_dominated_flags[position]
    )
    if candidate_ids != expected_candidate_ids:
        raise ValueError("minimax candidate ids must equal the complete feasible non-dominated set")

    snapshot_ids = tuple(snapshot.objective_id for snapshot in policy.objective_weight_snapshots)
    if snapshot_ids != objective_ids:
        raise ValueError("policy objective-weight snapshots must match the objective order exactly")
    rows = _verified_outcome_rows(outcome_matrix)
    for objective_position, snapshot in enumerate(policy.objective_weight_snapshots):
        if snapshot.weight != rows[0][objective_position].weight:
            raise ValueError(
                "policy objective weight must equal the outcome matrix authoritative weight"
            )
    return rows


def _build_minimax_regret(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    paired_comparisons: tuple[ObjectivePairedComparison, ...],
) -> CampaignMinimaxRegretAssessment:
    """The complete validated construction pipeline (see the public builder)."""
    pareto_assessment = build_campaign_pareto_dominance(
        policy=policy,
        outcome_matrix=outcome_matrix,
        paired_comparisons=paired_comparisons,
    )
    rows = _verify_pareto_alignment(policy, outcome_matrix, pareto_assessment)
    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    objective_ids = outcome_matrix.ordered_objective_ids
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)

    objective_directions: list[Literal["minimize", "maximize", "reach"]] = []
    objective_targets: list[float | None] = []
    objective_scales: list[float] = []
    objective_weights: list[float] = []
    for objective_position in range(objective_count):
        reference = rows[0][objective_position]
        objective_directions.append(reference.direction)
        objective_targets.append(reference.target)
        objective_scales.append(reference.normalization_scale)
        objective_weights.append(reference.weight)
    weights = tuple(objective_weights)

    # For every objective and seed, one same-seed regret vector over ALL
    # strategies in authoritative strategy order (feasible, infeasible,
    # dominated and non-dominated alike).
    regrets_by_objective_seed: list[list[tuple[float, ...]]] = []
    for objective_position in range(objective_count):
        per_seed_vectors: list[tuple[float, ...]] = []
        for seed_position in range(seed_count):
            values = tuple(
                rows[strategy_position][objective_position].ordered_observed_values[seed_position]
                for strategy_position in range(strategy_count)
            )
            per_seed_vectors.append(
                same_seed_regret(
                    values,
                    direction=objective_directions[objective_position],
                    normalization_scale=objective_scales[objective_position],
                    target=objective_targets[objective_position],
                )
            )
        regrets_by_objective_seed.append(per_seed_vectors)

    strategy_assessments: list[StrategyRegretAssessment] = []
    for strategy_position in range(strategy_count):
        per_objective_regret: list[ObjectiveRegretEvidence] = []
        objective_regret_vectors: list[tuple[float, ...]] = []
        for objective_position in range(objective_count):
            per_seed_regrets = tuple(
                regrets_by_objective_seed[objective_position][seed_position][strategy_position]
                for seed_position in range(seed_count)
            )
            weighted_regret = objective_weighted_mean_regret(
                per_seed_regrets,
                weight=objective_weights[objective_position],
            )
            try:
                regret_evidence = ObjectiveRegretEvidence(
                    objective_id=objective_ids[objective_position],
                    weighted_regret=weighted_regret,
                )
            except ValueError as exc:
                raise ValueError(
                    "generated objective regret evidence violates its contract"
                ) from exc
            per_objective_regret.append(regret_evidence)
            objective_regret_vectors.append(per_seed_regrets)
        per_seed_totals = total_regret_vector(tuple(objective_regret_vectors), weights)
        summary = total_regret_statistics(per_seed_totals)
        strategy_assessments.append(
            StrategyRegretAssessment(
                strategy_position=strategy_position,
                strategy_candidate_id=strategy_ids[strategy_position],
                per_objective_weighted_regret=tuple(per_objective_regret),
                per_seed_total_weighted_regrets=per_seed_totals,
                median_total_weighted_regret=summary.median_total_regret,
                p95_total_weighted_regret=summary.p95_total_regret,
                maximum_total_weighted_regret=summary.maximum_total_regret,
            )
        )

    minimax_candidate_ids = pareto_assessment.non_dominated_feasible_strategy_ids
    minimax_evaluated = (
        pareto_assessment.evidence_assessment.sufficient is True and len(minimax_candidate_ids) > 0
    )
    if not minimax_evaluated:
        best_maximum_total_weighted_regret: float | None = None
        minimax_tie_strategy_ids: tuple[str, ...] = ()
        unique_minimax_strategy_id: str | None = None
    else:
        assessment_by_id = {
            assessment.strategy_candidate_id: assessment for assessment in strategy_assessments
        }
        candidate_maxima = [
            assessment_by_id[candidate_id].maximum_total_weighted_regret
            for candidate_id in minimax_candidate_ids
        ]
        best = min(candidate_maxima)
        boundary = best + policy.tie_tolerance
        if not math.isfinite(boundary):
            raise OverflowError(
                "best maximum total weighted regret plus tie tolerance is not finite"
            )
        minimax_tie_strategy_ids = tuple(
            candidate_id
            for candidate_id in minimax_candidate_ids
            if assessment_by_id[candidate_id].maximum_total_weighted_regret <= boundary
        )
        best_maximum_total_weighted_regret = best
        unique_minimax_strategy_id = (
            minimax_tie_strategy_ids[0] if len(minimax_tie_strategy_ids) == 1 else None
        )

    return CampaignMinimaxRegretAssessment(
        pareto_assessment=pareto_assessment,
        strategy_regret_assessments=tuple(strategy_assessments),
        minimax_candidate_ids=minimax_candidate_ids,
        minimax_evaluated=minimax_evaluated,
        best_maximum_total_weighted_regret=best_maximum_total_weighted_regret,
        minimax_tie_strategy_ids=minimax_tie_strategy_ids,
        unique_minimax_strategy_id=unique_minimax_strategy_id,
    )


def build_campaign_minimax_regret(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    paired_comparisons: tuple[ObjectivePairedComparison, ...],
) -> CampaignMinimaxRegretAssessment:
    """Build the complete immutable weighted-regret and minimax assessment.

    Transforms one verified outcome matrix, one matching decision
    policy, and the complete supplied ``ObjectivePairedComparison``
    tuple into the complete algorithmic
    ``CampaignMinimaxRegretAssessment``: exactly one call to the
    accepted Pareto builder supplies the authoritative evidence
    sufficiency, strategy feasibility, factual dominance, and the
    feasible non-dominated minimax candidates; same-seed regret
    compares every strategy against all strategies under the same
    exact seed and objective (including infeasible and dominated
    strategies) through the accepted ``same_seed_regret`` primitive;
    one ``ObjectiveRegretEvidence`` per objective in authoritative
    objective order carries the accepted
    ``objective_weighted_mean_regret`` result with the exact
    non-normalized matrix weights; the per-seed total weighted regret
    vectors in exact seed order and their median/p95/maximum statistics
    come from the accepted ``total_regret_vector`` and
    ``total_regret_statistics`` primitives; and the exact inclusive
    minimax tie set under the policy tie tolerance (exact IEEE
    comparison, inclusive boundary, no isclose/relative tolerance/ULP
    relaxation/rounding/arbitrary winner) with the unique minimax
    strategy identity when exactly one candidate is justified. Minimax
    is evaluated exactly when the evidence is sufficient and the
    candidate set is non-empty; otherwise the best/tie/unique fields
    stay ``None``/empty while the complete regret assessments are still
    returned. The returned Pareto assessment is defensively re-verified
    against the matrix - evidence/dominance strategy alignment,
    complete dominance-relation structure, relation-derived factual
    tuples and flags, and exact complete candidate coverage - before
    any regret arithmetic. Invalid structural
    input raises ``ValueError``; every ``OverflowError`` from the
    accepted primitives or from a non-finite best-plus-tolerance
    boundary remains ``OverflowError``; a pydantic rejection of any
    generated regret record is converted to ``ValueError``; no partial
    result is ever returned and no input is ever mutated.
    """
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    if type(paired_comparisons) is not tuple:
        raise ValueError("paired_comparisons must be an exact tuple")
    for record in paired_comparisons:
        if not isinstance(record, ObjectivePairedComparison):
            raise ValueError(
                "every paired comparison must be an ObjectivePairedComparison instance"
            )
    try:
        return _build_minimax_regret(
            policy=policy,
            outcome_matrix=outcome_matrix,
            paired_comparisons=paired_comparisons,
        )
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError("campaign minimax regret construction failed on malformed input") from exc


__all__ = [
    "CampaignMinimaxRegretAssessment",
    "CampaignParetoDominanceAssessment",
    "StrategyDominanceAssessment",
    "StrategyRegretAssessment",
    "build_campaign_minimax_regret",
    "build_campaign_pareto_dominance",
]
