"""Pure deterministic evidence-sufficiency and strategy-feasibility layer (KALHAS).

This module implements the single pure application builder that
transforms one verified campaign outcome-distribution matrix and one
matching campaign decision policy into the complete immutable evidence
assessment of the campaign decision surface: the recorded seed-count
sufficiency fact, the factual per-objective target-threshold evidence,
the hard-gate strategy feasibility flag, the copied target-achievement
probability evidence, and the copied downside-risk evidence.

The builder is pure and deterministic:

- it is store-free, API-free, identity-free, hash-free, query-free,
  selection-free, and activity-free: it imports only the Python
  standard library, pydantic validation support, and the two relevant
  contract modules (``kalhas.contracts.v1.campaign_decision`` and
  ``kalhas.contracts.v1.campaign_outcome``). It never imports the
  paired-comparison builder, the selection logic, the statistics
  primitives, stores, services, API, identity/hash modules, adapters,
  domain packs, NEXUS, or LEGION;
- it reads no wall clock, uses no randomness, network, providers,
  filesystem, store, API, adapters, or domain packs, and never mutates
  either input artifact;
- it performs no paired comparison, no Pareto dominance, no regret,
  no minimax, no tie-set selection, no terminal status selection
  (preferred/inconclusive/no-feasible/insufficient), no reason or
  factor records, no comparison/brief assembly, no identity or content
  hashing, and no persistence or API behavior. The terminal
  ``insufficient_evidence`` decision belongs to the later pipeline;
  this layer only reports the factual sufficiency fact.

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

After revalidation the builder independently enforces every cross-source
fact directly represented by its two inputs: the tenant, campaign,
scenario (identity and content hash), world version (identity and
content hash), and evaluation profile (identity and content hash) must
agree exactly; the policy algorithm identifier must be the accepted
literal; the matrix comparison mode and runtime version must be the
accepted literals; the policy tail alpha and every outcome tail alpha
must be the fixed value; the policy objective-weight snapshots must
match the matrix objective order exactly with each snapshot weight
equal to the objective's authoritative matrix weight; and the inputs
must carry at least two strategies, at least one objective, and at
least one seed. The full positional outcome verification then proves,
for every strategy position and objective position, exactly one
outcome, contiguous sequence positions, exact position/identity
agreement, observed tuples of exactly the ordered seed count, empirical
samples equal to the ordered observed values, exact objective/metric
snapshot agreement (metric id, unit, direction, target, reach
tolerance, weight, normalization scale) across every strategy of the
same objective, and the targeted-versus-optimization-only evidence
field rules (targeted outcomes carry a non-``None`` probability, worst
violation, and CVaR; optimization-only outcomes carry none of those
fields). Finally the declared target policy is validated against the
matrix's actual targeted objectives: global mode applies its single
threshold to every targeted objective (zero targeted objectives is
valid - feasibility is then vacuous), while per-objective mode must
cover every targeted objective exactly once in the exact authoritative
relative order, and requirements for optimization-only, unknown,
missing, additional, duplicated, or reordered objective ids are
rejected.

Sufficiency semantics
---------------------

With ``K = len(outcome_matrix.ordered_scenario_seed_ids)`` the
assessment reports ``recorded_sample_count = K``,
``minimum_sample_count = policy.minimum_sample_count``, and
``sufficient = K >= policy.minimum_sample_count`` (the equality
boundary is inclusive). A structurally valid matrix with ``K`` below
the policy minimum is not an exception: the builder returns a complete
factual evidence assessment with ``sufficient=False``, and sufficiency
never alters, suppresses, or falsifies the factual per-strategy
feasibility evidence.

Target and feasibility semantics
--------------------------------

A targeted objective is exactly an objective whose authoritative
matrix snapshot has ``target != None``; optimization-only objectives
have ``target == None`` and never appear in the target-feasibility or
target-probability tuples. For every strategy and targeted objective
the builder records ``ObjectiveFeasibilityEvidence`` with the applied
threshold (the single global threshold in global mode; the matching
requirement threshold in per-objective mode), the copied observed
probability, and ``passed = (observed_probability >= threshold)`` -
exact IEEE comparison with no ``isclose``, epsilon, ULP relaxation,
rounding, clipping, normalization, or coercion. The hard-gate rule is
``feasible = (not policy.all_targeted_objectives_are_hard_gates or
all(record.passed for record in target_feasibility))``: hard gates
enabled requires every targeted objective to factually pass; hard
gates disabled makes every strategy feasible; zero targeted objectives
is vacuously feasible. ``passed`` always remains the factual
comparison result even when gates are disabled.

Supporting evidence
-------------------

For every strategy the builder copies, without recomputation,
``ObjectiveProbabilityEvidence`` for exactly the targeted objectives in
exact authoritative relative order and ``ObjectiveDownsideEvidence``
for every objective in full authoritative order (worst normalized
target violation and target-violation CVaR copied from the verified
outcome; optimization-only objectives retain ``None`` for those two
fields and still carry their copied adverse-tail statistic). The
verified outcome matrix is the authoritative source; no statistic of
any kind is recomputed here.

All ordering comes exclusively from the recorded tuples of the two
artifacts; no dict or set iteration is ever used as an ordering
authority.

Error semantics
---------------

Invalid structural or cross-source input raises ``ValueError``; a
numeric representability overflow raised by strict source validation
is never converted into ``ValueError`` (``OverflowError`` propagates);
a pydantic rejection of any generated record is converted to
``ValueError``; and no partial result is ever returned - the builder
either returns the complete assessment or raises.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal, NamedTuple

from pydantic import BaseModel

from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    ObjectiveDownsideEvidence,
    ObjectiveFeasibilityEvidence,
    ObjectiveProbabilityEvidence,
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

#: The required recorded outcome-matrix comparison mode.
_REQUIRED_COMPARISON_MODE: Literal["identical_conditions"] = "identical_conditions"

#: The fixed tail alpha shared by the policy and every outcome.
_FIXED_TAIL_ALPHA = 0.95


class StrategyFeasibilityAssessment(NamedTuple):
    """Immutable per-strategy feasibility and supporting-evidence assessment.

    Binds one strategy to its pipeline feasibility flag (the hard-gate
    result over the factual per-objective target evidence), the ordered
    per-targeted-objective ``ObjectiveFeasibilityEvidence`` records, the
    copied per-targeted-objective ``ObjectiveProbabilityEvidence``
    records, and the copied full-objective ``ObjectiveDownsideEvidence``
    records. The strategy order and positions come from the recorded
    outcome matrix.
    """

    strategy_position: int
    strategy_candidate_id: str
    feasible: bool
    target_feasibility: tuple[ObjectiveFeasibilityEvidence, ...]
    target_achievement_probabilities: tuple[ObjectiveProbabilityEvidence, ...]
    downside_evidence: tuple[ObjectiveDownsideEvidence, ...]


class CampaignDecisionEvidenceAssessment(NamedTuple):
    """Immutable complete evidence-sufficiency and feasibility assessment.

    Binds the recorded seed count ``K``, the policy minimum sample
    count, the factual sufficiency flag ``K >= minimum_sample_count``
    (inclusive boundary), and the ordered per-strategy feasibility
    assessments. This layer derives no terminal decision status; the
    later pipeline owns the terminal ``insufficient_evidence``
    decision.
    """

    recorded_sample_count: int
    minimum_sample_count: int
    sufficient: bool
    strategy_assessments: tuple[StrategyFeasibilityAssessment, ...]


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
    if outcome_matrix.comparison_mode != _REQUIRED_COMPARISON_MODE:
        raise ValueError("outcome comparison mode must be the accepted literal")
    if outcome_matrix.runtime_version != _REQUIRED_RUNTIME_VERSION:
        raise ValueError("outcome runtime version must be the accepted literal")
    if policy.tail_alpha != _FIXED_TAIL_ALPHA:
        raise ValueError("policy tail alpha must be the fixed value")
    for outcome in outcome_matrix.outcomes:
        if outcome.tail_alpha != policy.tail_alpha:
            raise ValueError("every outcome tail alpha must equal the policy tail alpha")
    if len(outcome_matrix.ordered_strategy_candidate_ids) < 2:
        raise ValueError("the evidence assessment requires at least two strategies")
    if not outcome_matrix.ordered_objective_ids:
        raise ValueError("the evidence assessment requires at least one objective")
    if not outcome_matrix.ordered_scenario_seed_ids:
        raise ValueError("the evidence assessment requires at least one seed")
    strategy_ids = list(outcome_matrix.ordered_strategy_candidate_ids)
    seed_ids = list(outcome_matrix.ordered_scenario_seed_ids)
    objective_ids = list(outcome_matrix.ordered_objective_ids)
    if len(strategy_ids) != len(set(strategy_ids)):
        raise ValueError("strategy identifiers must be unique")
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("seed identifiers must be unique")
    if len(objective_ids) != len(set(objective_ids)):
        raise ValueError("objective identifiers must be unique")
    snapshot_ids = [snapshot.objective_id for snapshot in policy.objective_weight_snapshots]
    if snapshot_ids != objective_ids:
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


def _targeted_objective_ids(
    rows: tuple[tuple[StrategyObjectiveOutcome, ...], ...],
    objective_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """The authoritative targeted objective ids, in exact objective order.

    A targeted objective is exactly one whose authoritative matrix
    snapshot has ``target != None``. Simultaneously enforces the
    targeted-versus-optimization-only evidence field rules: targeted
    outcomes must carry a non-``None`` empirical probability, worst
    normalized target violation, and target-violation CVaR, while
    optimization-only outcomes must carry none of those fields.
    """
    objective_count = len(objective_ids)
    targeted_ids: list[str] = []
    for objective_position in range(objective_count):
        targeted = rows[0][objective_position].target is not None
        if targeted:
            targeted_ids.append(objective_ids[objective_position])
        for strategy_position in range(len(rows)):
            outcome = rows[strategy_position][objective_position]
            probability = outcome.empirical_target_achievement_probability
            worst = outcome.worst_normalized_target_violation
            cvar = outcome.target_violation_cvar
            if targeted:
                if probability is None or worst is None or cvar is None:
                    raise ValueError("targeted objectives require the targeted evidence fields")
            elif probability is not None or worst is not None or cvar is not None:
                raise ValueError(
                    "optimization-only objectives must not carry targeted evidence fields"
                )
    return tuple(targeted_ids)


def _verify_target_coverage(
    policy: CampaignDecisionPolicy,
    targeted_ids: tuple[str, ...],
) -> None:
    """Validate the declared target policy against the actual targeted objectives.

    Global mode applies its single threshold to every targeted
    objective and is valid with zero targeted objectives (feasibility
    is then vacuous). Per-objective mode must cover every targeted
    objective exactly once in the exact authoritative relative order;
    missing, duplicate, unknown, additional, or reordered requirements
    - and requirements for optimization-only objectives - are rejected.
    """
    if policy.target_requirement_mode == "global":
        return
    requirement_ids = tuple(
        requirement.objective_id for requirement in policy.objective_target_requirements
    )
    if requirement_ids != targeted_ids:
        if len(requirement_ids) == len(targeted_ids) and set(requirement_ids) == set(targeted_ids):
            raise ValueError(
                "per-objective target requirements must follow the exact authoritative "
                "targeted-objective order"
            )
        raise ValueError(
            "per-objective target requirements must cover exactly the targeted objectives, "
            "each exactly once"
        )


def _threshold_for(policy: CampaignDecisionPolicy, objective_id: str) -> float:
    """The exact policy threshold applied to one targeted objective."""
    if policy.target_requirement_mode == "global":
        threshold = policy.minimum_target_achievement_probability
        if threshold is None:
            raise ValueError("global mode requires a global target-achievement threshold")
        return threshold
    for requirement in policy.objective_target_requirements:
        if requirement.objective_id == objective_id:
            return requirement.minimum_target_achievement_probability
    raise ValueError("missing per-objective target requirement for a targeted objective")


def _build_evidence(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignDecisionEvidenceAssessment:
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
    targeted_ids = _targeted_objective_ids(rows, objective_ids)
    _verify_target_coverage(policy, targeted_ids)

    assessments: list[StrategyFeasibilityAssessment] = []
    for strategy_position in range(strategy_count):
        target_feasibility: list[ObjectiveFeasibilityEvidence] = []
        target_probabilities: list[ObjectiveProbabilityEvidence] = []
        for objective_position in range(objective_count):
            outcome = rows[strategy_position][objective_position]
            if outcome.target is None:
                continue
            objective_id = objective_ids[objective_position]
            observed = outcome.empirical_target_achievement_probability
            if observed is None:
                raise ValueError("targeted objectives require an observed achievement probability")
            threshold = _threshold_for(policy, objective_id)
            try:
                feasibility_record = ObjectiveFeasibilityEvidence(
                    objective_id=objective_id,
                    threshold=threshold,
                    observed_probability=observed,
                    passed=observed >= threshold,
                )
                probability_record = ObjectiveProbabilityEvidence(
                    objective_id=objective_id,
                    empirical_target_achievement_probability=observed,
                )
            except ValueError as exc:
                raise ValueError("generated evidence record violates its contract") from exc
            target_feasibility.append(feasibility_record)
            target_probabilities.append(probability_record)
        feasible = not policy.all_targeted_objectives_are_hard_gates or all(
            record.passed for record in target_feasibility
        )
        try:
            downside_evidence = tuple(
                ObjectiveDownsideEvidence(
                    objective_id=objective_ids[objective_position],
                    worst_normalized_target_violation=rows[strategy_position][
                        objective_position
                    ].worst_normalized_target_violation,
                    target_violation_cvar=rows[strategy_position][
                        objective_position
                    ].target_violation_cvar,
                    adverse_tail_statistic=rows[strategy_position][
                        objective_position
                    ].adverse_tail_statistic,
                )
                for objective_position in range(objective_count)
            )
        except ValueError as exc:
            raise ValueError("generated evidence record violates its contract") from exc
        assessments.append(
            StrategyFeasibilityAssessment(
                strategy_position=strategy_position,
                strategy_candidate_id=strategy_ids[strategy_position],
                feasible=feasible,
                target_feasibility=tuple(target_feasibility),
                target_achievement_probabilities=tuple(target_probabilities),
                downside_evidence=downside_evidence,
            )
        )

    recorded_sample_count = len(outcome_matrix.ordered_scenario_seed_ids)
    minimum_sample_count = policy.minimum_sample_count
    return CampaignDecisionEvidenceAssessment(
        recorded_sample_count=recorded_sample_count,
        minimum_sample_count=minimum_sample_count,
        sufficient=recorded_sample_count >= minimum_sample_count,
        strategy_assessments=tuple(assessments),
    )


def build_campaign_decision_evidence(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignDecisionEvidenceAssessment:
    """Build the complete immutable evidence-sufficiency and feasibility assessment.

    Transforms one verified outcome matrix and one matching decision
    policy into the complete factual ``CampaignDecisionEvidenceAssessment``:
    the recorded seed-count sufficiency fact, the per-strategy hard-gate
    feasibility flag with the per-targeted-objective threshold evidence,
    the copied target-achievement probabilities, and the copied
    full-objective downside evidence. Both inputs must be exact contract
    instances and are strictly revalidated from detached Python-mode
    serialization before any field is trusted; every cross-source fact
    directly represented by the two inputs is then enforced, the
    authoritative positional outcome lookup is built, and the declared
    target policy is validated against the matrix's actual targeted
    objectives. A structurally valid matrix with ``K`` below the policy
    minimum is not an exception - it returns a complete factual
    assessment with ``sufficient=False``. No paired comparison,
    dominance, regret, minimax, tie-set selection, terminal status,
    reason/factor record, comparison/brief assembly, identity/hash,
    persistence, or API behavior exists here. Invalid structural or
    cross-source input raises ``ValueError``; a numeric representability
    overflow raised by strict source validation propagates as
    ``OverflowError``; a pydantic rejection of any generated record is
    converted to ``ValueError``; no partial result is ever returned and
    neither input is ever mutated.
    """
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    try:
        return _build_evidence(policy=policy, outcome_matrix=outcome_matrix)
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError(
            "campaign decision evidence construction failed on malformed input"
        ) from exc


__all__ = [
    "CampaignDecisionEvidenceAssessment",
    "StrategyFeasibilityAssessment",
    "build_campaign_decision_evidence",
]
