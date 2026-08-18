"""Pure deterministic campaign strategy comparison assembly (KALHAS).

This module implements the single pure application builder that
transforms one verified campaign decision policy and one verified
campaign outcome-distribution matrix into the complete immutable
derived ``CampaignStrategyComparison`` artifact: the exact comparison
identifier and deterministic content hash, the copied campaign/
scenario/world identity, the recorded runtime/comparison-mode/algorithm
literals, the policy and source-matrix references with their recorded
content hashes, the tie-tolerance and minimum-sample-count snapshots,
the exact ordered strategy/seed/objective identifiers, the complete
paired-comparison tuple from the accepted ordered-pair builder, the
complete dominance-relation tuple and one robustness profile per
strategy assembled from the accepted evidence, dominance, and regret
assessments, and the copied matrix ``derived_at`` timestamp.

The builder is pure and deterministic:

- it is store-free, API-free, query-free, activity-free, execution-
  free, replay-free, registration-free, and schema-free: it imports
  only the Python standard library, pydantic validation support, the
  two relevant contract modules, the two identity/hash modules, the
  accepted ordered-pair builder, and the accepted selection builders.
  It never imports stores, services, error modules, API modules,
  hashing helpers directly, statistics primitives, adapters, domain
  packs, NEXUS, or LEGION;
- it reads no wall clock, uses no randomness, network, providers,
  filesystem, store, API, adapters, or domain packs, never mutates
  either input artifact, and never computes a timestamp - the
  comparison's ``derived_at`` is copied exactly from the verified
  outcome matrix;
- it performs no paired-delta recomputation, no evidence, dominance,
  Pareto, regret, or minimax recomputation - those facts come
  exclusively from exactly one call to the accepted ordered-pair
  builder followed by exactly one call to the accepted minimax-regret
  builder with the exact returned paired tuple - and no brief, status,
  reason, factor, recommendation, ranking, or scoring derivation of
  any kind.

Composition
-----------

The exact composition order is fixed: both source artifacts are
strictly revalidated from detached Python-mode serialization and their
recorded identifiers and content hashes are recomputed and verified;
every cross-source fact directly represented by the two inputs is
enforced; the accepted ordered-pair builder is called exactly once;
the accepted minimax-regret builder is called exactly once with the
exact paired tuple object returned by the ordered-pair builder; the
complete minimax aggregate is verified against the policy, the matrix,
and the paired tuple at the intermediate trust boundary; one
``StrategyRobustnessProfile`` is constructed per strategy in exact
matrix strategy order by copying the accepted evidence, dominance, and
regret assessment fields without recalculation; the comparison is
constructed with the deterministic identifier and a placeholder
content hash; the content hash is computed over the placeholder and
finalized via an immutable copy; and the final artifact is strictly
revalidated and independently re-verified before it is returned. No
partial artifact ever escapes.

Error semantics
---------------

Invalid structural or cross-source input raises ``ValueError``; a
numeric representability overflow raised by strict source validation
or by the accepted builders, and a non-finite minimax boundary proven
at the trust boundary, propagate as ``OverflowError``; a pydantic
rejection of any generated profile or of the generated comparison is
converted to ``ValueError``; and the builder either returns the
complete immutable artifact or raises.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal

from pydantic import BaseModel

from kalhas.application.campaign_decision_identity import (
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
    campaign_strategy_comparison_content_hash,
    campaign_strategy_comparison_identifier,
)
from kalhas.application.campaign_decision_paired_comparison import (
    build_ordered_objective_paired_comparisons,
)
from kalhas.application.campaign_decision_selection import (
    CampaignMinimaxRegretAssessment,
    build_campaign_minimax_regret,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    DominanceRelation,
    ObjectivePairedComparison,
    StrategyRobustnessProfile,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix

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

#: The placeholder content hash of the draft comparison.
_PLACEHOLDER_CONTENT_HASH = "0" * 64


def _contains_non_finite(value: object) -> bool:
    """True when any nested ``float`` inside a JSON-like tree is non-finite."""
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_non_finite(item) for item in value.values())
    return False


def _leq_within_one_step(left: float, right: float) -> bool:
    """``left <= right``, allowing exactly one adjacent float step above ``right``."""
    return left <= right or left == math.nextafter(right, math.inf)


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


def _verify_policy_identity(policy: CampaignDecisionPolicy) -> None:
    """Recompute and verify the recorded policy identifier and content hash.

    The recorded ``identifier`` must equal the deterministic derivation
    from the canonical identity payload and the recorded ``content_hash``
    must equal the canonical digest of the complete remaining policy
    payload; a recorded hash is never trusted or repaired.
    """
    expected_identifier = campaign_decision_policy_identifier(
        tenant_id=policy.tenant_id,
        campaign_id=policy.campaign_id,
        scenario_id=policy.scenario_id,
        world_version_id=policy.world_version_id,
        evaluation_profile_id=policy.evaluation_profile_id,
        schema_version=policy.schema_version,
    )
    if policy.identifier != expected_identifier:
        raise ValueError("policy identifier does not match its deterministic derivation")
    if policy.content_hash != campaign_decision_policy_content_hash(policy):
        raise ValueError("policy content hash does not match its deterministic derivation")


def _verify_matrix_identity(outcome_matrix: CampaignOutcomeDistributionMatrix) -> None:
    """Recompute and verify the recorded matrix identifier and content hash."""
    expected_identifier = campaign_outcome_distribution_matrix_identifier(
        campaign_id=outcome_matrix.campaign_id,
        world_version_id=outcome_matrix.world_version_id,
        runtime_version=outcome_matrix.runtime_version,
        evaluation_profile_id=outcome_matrix.evaluation_profile_id,
        source_world_realization_matrix_id=outcome_matrix.source_world_realization_matrix_id,
        source_metric_observation_matrix_id=outcome_matrix.source_metric_observation_matrix_id,
    )
    if outcome_matrix.identifier != expected_identifier:
        raise ValueError("outcome matrix identifier does not match its deterministic derivation")
    if outcome_matrix.content_hash != campaign_outcome_distribution_matrix_content_hash(
        outcome_matrix
    ):
        raise ValueError("outcome matrix content hash does not match its deterministic derivation")


def _verify_cross_source_agreement(
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> None:
    """Independently enforce every cross-source fact represented by the inputs."""
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
        raise ValueError("a strategy comparison requires at least two strategies")
    if not outcome_matrix.ordered_objective_ids:
        raise ValueError("a strategy comparison requires at least one objective")
    if not outcome_matrix.ordered_scenario_seed_ids:
        raise ValueError("a strategy comparison requires at least one seed")
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


def _pair_index(first: int, second: int, strategy_count: int) -> int:
    """The exact deterministic ordered-pair index formula."""
    return first * (strategy_count - 1) + (second if second < first else second - 1)


def _verify_minimax_alignment(
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    paired_comparisons: tuple[ObjectivePairedComparison, ...],
    minimax: CampaignMinimaxRegretAssessment,
) -> None:
    """Prove the returned minimax aggregate aligns exactly with its inputs.

    The accepted minimax builder already proves these facts; this layer
    re-checks the complete alignment defensively at the intermediate
    trust boundary so a monkeypatched or internally inconsistent
    returned assessment fails before any profile or comparison is
    constructed. The verification covers: the evidence sample and
    minimum counts against the matrix and policy; the evidence,
    dominance, and regret strategy assessments covering exactly the
    strategy order with exact identities and positions; exact
    feasibility agreement between the evidence and dominance
    assessments; the complete ``S * (S - 1)`` dominance-relation tuple
    in exact pair order with in-range positions, exact identities,
    per-objective statuses covering the exact objective order with
    counts and medians equal to the supplied paired records, and
    reverse coverage without mutual dominance; the factual
    dominated-by/dominates tuples and the non-dominated feasible
    strategy ids re-derived from the relations and feasibility; the
    minimax candidate ids equal to the Pareto non-dominated feasible
    ids; the minimax evaluated flag and the best/tie/unique fields
    satisfying the accepted sufficiency, feasibility, and exact
    inclusive tie-tolerance rules; every regret record covering all
    objectives exactly once in objective order; every per-seed total
    vector of exactly the seed count; the median/p95/maximum aggregates
    agreeing exactly with the per-seed totals; and every supporting
    evidence tuple covering its required objective subset in the exact
    required order.
    """
    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    objective_ids = outcome_matrix.ordered_objective_ids
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)
    strategy_count = len(strategy_ids)
    objective_count = len(objective_ids)

    pareto = minimax.pareto_assessment
    evidence = pareto.evidence_assessment
    if evidence.recorded_sample_count != seed_count:
        raise ValueError("evidence recorded sample count must equal the matrix seed count")
    if evidence.minimum_sample_count != policy.minimum_sample_count:
        raise ValueError("evidence minimum sample count must equal the policy minimum")
    if evidence.sufficient != (seed_count >= policy.minimum_sample_count):
        raise ValueError("evidence sufficiency must equal the recorded count rule")

    evidence_assessments = evidence.strategy_assessments
    if type(evidence_assessments) is not tuple or len(evidence_assessments) != strategy_count:
        raise ValueError("evidence strategy assessments must exactly cover the strategy order")
    for position, evidence_assessment in enumerate(evidence_assessments):
        if (
            evidence_assessment.strategy_position != position
            or evidence_assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("evidence strategy assessment identity mismatch")

    dominance_assessments = pareto.strategy_assessments
    if type(dominance_assessments) is not tuple or len(dominance_assessments) != strategy_count:
        raise ValueError("dominance strategy assessments must exactly cover the strategy order")
    for position, dominance_assessment in enumerate(dominance_assessments):
        if (
            dominance_assessment.strategy_position != position
            or dominance_assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("dominance strategy assessment identity mismatch")
        if dominance_assessment.feasible is not evidence_assessments[position].feasible:
            raise ValueError("dominance feasibility must equal the evidence feasibility exactly")

    regret_assessments = minimax.strategy_regret_assessments
    if type(regret_assessments) is not tuple or len(regret_assessments) != strategy_count:
        raise ValueError("regret strategy assessments must exactly cover the strategy order")
    for position, regret_assessment in enumerate(regret_assessments):
        if (
            regret_assessment.strategy_position != position
            or regret_assessment.strategy_candidate_id != strategy_ids[position]
        ):
            raise ValueError("regret strategy assessment identity mismatch")

    if type(paired_comparisons) is not tuple:
        raise ValueError("paired_comparisons must be an exact tuple")
    expected_pair_count = strategy_count * (strategy_count - 1) * objective_count
    if len(paired_comparisons) != expected_pair_count:
        raise ValueError("paired comparisons must contain exactly S * (S - 1) * O records")
    records_by_key: dict[tuple[int, int, int], ObjectivePairedComparison] = {}
    for record in paired_comparisons:
        if not isinstance(record, ObjectivePairedComparison):
            raise ValueError("every paired comparison must be an ObjectivePairedComparison")
        record_key = (
            record.first_strategy_position,
            record.second_strategy_position,
            record.objective_position,
        )
        if record_key in records_by_key:
            raise ValueError("duplicate ordered pair/objective paired comparison")
        records_by_key[record_key] = record
    expected_keys = {
        (first, second, objective_position)
        for first in range(strategy_count)
        for second in range(strategy_count)
        if first != second
        for objective_position in range(objective_count)
    }
    if set(records_by_key) != expected_keys:
        raise ValueError("paired comparisons must cover every ordered pair and objective")

    relations = pareto.dominance_relations
    if type(relations) is not tuple or len(relations) != strategy_count * (strategy_count - 1):
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
        statuses = relation.per_objective_status
        if type(statuses) is not tuple or len(statuses) != objective_count:
            raise ValueError(
                "dominance relation must carry one status per objective in objective order"
            )
        for objective_position, status in enumerate(statuses):
            if status.objective_id != objective_ids[objective_position]:
                raise ValueError("dominance status objective identity does not match its position")
            record = records_by_key[(first, second, objective_position)]
            if (
                status.win_count != record.win_count
                or status.tie_count != record.tie_count
                or status.loss_count != record.loss_count
            ):
                raise ValueError(
                    "dominance status counts must equal the supplied paired comparison"
                )
            if status.median_paired_delta != record.median_paired_delta:
                raise ValueError(
                    "dominance status median must equal the supplied paired comparison"
                )
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

    feasible_by_position = tuple(assessment.feasible for assessment in dominance_assessments)
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
        if dominance_assessments[position].dominated_by != expected_dominated_by:
            raise ValueError("strategy dominated_by must equal the factual relation-derived tuple")
        if dominance_assessments[position].dominates != expected_dominates:
            raise ValueError("strategy dominates must equal the factual relation-derived tuple")
        expected_non_dominated = feasible_by_position[position] is True and not any(
            feasible_by_position[dominator] is True
            and relations_by_pair[(dominator, position)].dominates is True
            for dominator in range(strategy_count)
            if dominator != position
        )
        if (
            dominance_assessments[position].non_dominated_among_feasible
            is not expected_non_dominated
        ):
            raise ValueError(
                "non_dominated_among_feasible must equal the feasible factual derivation"
            )
        expected_non_dominated_flags.append(expected_non_dominated)

    expected_candidate_ids = tuple(
        strategy_ids[position]
        for position in range(strategy_count)
        if expected_non_dominated_flags[position]
    )
    candidate_ids = pareto.non_dominated_feasible_strategy_ids
    if type(candidate_ids) is not tuple or candidate_ids != expected_candidate_ids:
        raise ValueError(
            "non-dominated feasible strategy ids must equal the complete factual derivation"
        )
    if minimax.minimax_candidate_ids != candidate_ids:
        raise ValueError("minimax candidate ids must equal the Pareto non-dominated feasible ids")

    expected_evaluated = evidence.sufficient is True and len(candidate_ids) > 0
    if minimax.minimax_evaluated is not expected_evaluated:
        raise ValueError("minimax evaluated flag must follow the accepted sufficiency rule")
    if not expected_evaluated:
        if minimax.best_maximum_total_weighted_regret is not None:
            raise ValueError("minimax best regret must stay unset when not evaluated")
        if minimax.minimax_tie_strategy_ids != ():
            raise ValueError("minimax tie set must stay empty when not evaluated")
        if minimax.unique_minimax_strategy_id is not None:
            raise ValueError("minimax unique strategy must stay unset when not evaluated")
    else:
        if type(minimax.minimax_tie_strategy_ids) is not tuple:
            raise ValueError("minimax tie strategy ids must be an exact tuple")
        assessment_by_id = {
            assessment.strategy_candidate_id: assessment for assessment in regret_assessments
        }
        candidate_maxima = [
            assessment_by_id[candidate_id].maximum_total_weighted_regret
            for candidate_id in candidate_ids
        ]
        best = min(candidate_maxima)
        if minimax.best_maximum_total_weighted_regret != best:
            raise ValueError("minimax best regret must equal the minimum candidate maximum")
        boundary = best + policy.tie_tolerance
        if not math.isfinite(boundary):
            raise OverflowError(
                "best maximum total weighted regret plus tie tolerance is not finite"
            )
        expected_tie = tuple(
            candidate_id
            for candidate_id in candidate_ids
            if assessment_by_id[candidate_id].maximum_total_weighted_regret <= boundary
        )
        if minimax.minimax_tie_strategy_ids != expected_tie:
            raise ValueError("minimax tie set must equal the exact inclusive tolerance rule")
        expected_unique = expected_tie[0] if len(expected_tie) == 1 else None
        if minimax.unique_minimax_strategy_id != expected_unique:
            raise ValueError("minimax unique strategy must follow the exact tie-set cardinality")

    for assessment in regret_assessments:
        regret_records = assessment.per_objective_weighted_regret
        if type(regret_records) is not tuple or len(regret_records) != objective_count:
            raise ValueError("regret records must cover every objective exactly once")
        for objective_position, regret_record in enumerate(regret_records):
            if regret_record.objective_id != objective_ids[objective_position]:
                raise ValueError("regret records must follow the exact objective order")
        totals = assessment.per_seed_total_weighted_regrets
        if type(totals) is not tuple or len(totals) != seed_count:
            raise ValueError("per-seed total weighted regrets must align with the seed count")
        if assessment.maximum_total_weighted_regret != max(totals):
            raise ValueError("maximum total weighted regret must equal the exact recorded maximum")
        totals_minimum = min(totals)
        for derived in (
            assessment.median_total_weighted_regret,
            assessment.p95_total_weighted_regret,
        ):
            if not math.isfinite(derived) or derived < 0.0:
                raise ValueError("median/p95 total weighted regret must be finite and non-negative")
            if not _leq_within_one_step(totals_minimum, derived) or not _leq_within_one_step(
                derived, assessment.maximum_total_weighted_regret
            ):
                raise ValueError("median/p95 must lie within the per-seed extrema")
        if not _leq_within_one_step(
            assessment.median_total_weighted_regret, assessment.p95_total_weighted_regret
        ):
            raise ValueError("median total weighted regret must never exceed the p95")

    targeted_ids = tuple(
        objective_ids[objective_position]
        for objective_position in range(objective_count)
        if outcome_matrix.outcomes[objective_position].target is not None
    )
    for supporting_assessment in evidence_assessments:
        target_feasibility = supporting_assessment.target_feasibility
        probabilities = supporting_assessment.target_achievement_probabilities
        downside = supporting_assessment.downside_evidence
        if type(downside) is not tuple or len(downside) != objective_count:
            raise ValueError("downside evidence must cover every objective exactly once")
        for objective_position, downside_record in enumerate(downside):
            if downside_record.objective_id != objective_ids[objective_position]:
                raise ValueError("downside evidence must follow the exact objective order")
        if type(target_feasibility) is not tuple or type(probabilities) is not tuple:
            raise ValueError("target-only evidence tuples must be exact tuples")
        feasibility_ids = [record.objective_id for record in target_feasibility]
        probability_ids = [record.objective_id for record in probabilities]
        if feasibility_ids != probability_ids:
            raise ValueError(
                "target feasibility and achievement probabilities must carry the same objective ids"
            )
        if len(feasibility_ids) != len(set(feasibility_ids)):
            raise ValueError("target-only evidence objective identifiers must be unique")
        if feasibility_ids != list(targeted_ids):
            raise ValueError(
                "target-only evidence must cover exactly the targeted objectives in order"
            )
        expected_feasible = not policy.all_targeted_objectives_are_hard_gates or all(
            record.passed for record in target_feasibility
        )
        if supporting_assessment.feasible is not expected_feasible:
            raise ValueError("strategy feasible flag must follow the accepted hard-gate rule")


def _build_comparison(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignStrategyComparison:
    """The complete validated construction pipeline (see the public builder)."""
    _strictly_revalidate_detached(policy, CampaignDecisionPolicy)
    _strictly_revalidate_detached(outcome_matrix, CampaignOutcomeDistributionMatrix)
    if _contains_non_finite(policy.metadata):
        raise ValueError("policy metadata must not contain non-finite floats")
    _verify_policy_identity(policy)
    _verify_matrix_identity(outcome_matrix)
    _verify_cross_source_agreement(policy, outcome_matrix)

    paired_comparisons = build_ordered_objective_paired_comparisons(
        policy=policy, outcome_matrix=outcome_matrix
    )
    minimax = build_campaign_minimax_regret(
        policy=policy,
        outcome_matrix=outcome_matrix,
        paired_comparisons=paired_comparisons,
    )
    _verify_minimax_alignment(policy, outcome_matrix, paired_comparisons, minimax)

    strategy_ids = outcome_matrix.ordered_strategy_candidate_ids
    strategy_count = len(strategy_ids)
    pareto = minimax.pareto_assessment
    evidence_assessments = pareto.evidence_assessment.strategy_assessments
    dominance_assessments = pareto.strategy_assessments
    regret_assessments = minimax.strategy_regret_assessments

    profiles: list[StrategyRobustnessProfile] = []
    for position in range(strategy_count):
        evidence_assessment = evidence_assessments[position]
        dominance_assessment = dominance_assessments[position]
        regret_assessment = regret_assessments[position]
        try:
            profile = StrategyRobustnessProfile(
                strategy_position=position,
                strategy_candidate_id=strategy_ids[position],
                feasible=evidence_assessment.feasible,
                target_feasibility=evidence_assessment.target_feasibility,
                dominated_by=dominance_assessment.dominated_by,
                dominates=dominance_assessment.dominates,
                per_objective_weighted_regret=regret_assessment.per_objective_weighted_regret,
                per_seed_total_weighted_regrets=regret_assessment.per_seed_total_weighted_regrets,
                median_total_weighted_regret=regret_assessment.median_total_weighted_regret,
                p95_total_weighted_regret=regret_assessment.p95_total_weighted_regret,
                maximum_total_weighted_regret=regret_assessment.maximum_total_weighted_regret,
                target_achievement_probabilities=evidence_assessment.target_achievement_probabilities,
                downside_evidence=evidence_assessment.downside_evidence,
            )
        except ValueError as exc:
            raise ValueError("generated robustness profile violates its contract") from exc
        profiles.append(profile)

    comparison_identifier = campaign_strategy_comparison_identifier(
        campaign_id=outcome_matrix.campaign_id,
        world_version_id=outcome_matrix.world_version_id,
        evaluation_profile_id=outcome_matrix.evaluation_profile_id,
        policy_id=policy.identifier,
        source_outcome_matrix_id=outcome_matrix.identifier,
    )
    try:
        placeholder = CampaignStrategyComparison(
            identifier=comparison_identifier,
            tenant_id=outcome_matrix.tenant_id,
            schema_version=outcome_matrix.schema_version,
            campaign_id=outcome_matrix.campaign_id,
            scenario_id=outcome_matrix.scenario_id,
            scenario_content_hash=outcome_matrix.scenario_content_hash,
            world_version_id=outcome_matrix.world_version_id,
            world_content_hash=outcome_matrix.world_content_hash,
            runtime_version=_REQUIRED_RUNTIME_VERSION,
            comparison_mode=_REQUIRED_COMPARISON_MODE,
            algorithm_identifier=policy.algorithm_identifier,
            policy_id=policy.identifier,
            policy_content_hash=policy.content_hash,
            tie_tolerance=policy.tie_tolerance,
            minimum_sample_count=policy.minimum_sample_count,
            source_outcome_matrix_id=outcome_matrix.identifier,
            source_outcome_matrix_content_hash=outcome_matrix.content_hash,
            ordered_strategy_candidate_ids=outcome_matrix.ordered_strategy_candidate_ids,
            ordered_scenario_seed_ids=outcome_matrix.ordered_scenario_seed_ids,
            ordered_objective_ids=outcome_matrix.ordered_objective_ids,
            paired_comparisons=paired_comparisons,
            dominance_relations=pareto.dominance_relations,
            robustness_profiles=tuple(profiles),
            content_hash=_PLACEHOLDER_CONTENT_HASH,
            derived_at=outcome_matrix.derived_at,
        )
    except ValueError as exc:
        raise ValueError("generated campaign strategy comparison violates its contract") from exc

    computed_hash = campaign_strategy_comparison_content_hash(placeholder)
    final = placeholder.model_copy(update={"content_hash": computed_hash})

    _strictly_revalidate_detached(final, CampaignStrategyComparison)

    recomputed_identifier = campaign_strategy_comparison_identifier(
        campaign_id=outcome_matrix.campaign_id,
        world_version_id=outcome_matrix.world_version_id,
        evaluation_profile_id=outcome_matrix.evaluation_profile_id,
        policy_id=policy.identifier,
        source_outcome_matrix_id=outcome_matrix.identifier,
    )
    if final.identifier != recomputed_identifier:
        raise ValueError("final comparison identifier must equal its deterministic derivation")
    if final.content_hash != campaign_strategy_comparison_content_hash(final):
        raise ValueError("final comparison content hash must equal its deterministic derivation")
    return final


def build_campaign_strategy_comparison(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignStrategyComparison:
    """Build the complete immutable derived campaign strategy comparison.

    Transforms one verified outcome matrix and one matching decision
    policy into the complete immutable ``CampaignStrategyComparison``:
    the deterministic identifier and content hash, the copied identity
    and source references, the recorded literals and snapshots, the
    exact ordered identifier tuples, the complete paired-comparison
    tuple from exactly one call to the accepted ordered-pair builder,
    the complete dominance-relation tuple, and one robustness profile
    per strategy assembled by copying the accepted evidence, dominance,
    and regret assessment fields. Both inputs must be exact contract
    instances and are strictly revalidated from detached Python-mode
    serialization before any field is trusted; every recorded
    identifier and content hash is recomputed and verified; every
    cross-source fact directly represented by the two inputs is
    enforced; the accepted minimax-regret builder is called exactly
    once with the exact paired tuple returned by the ordered-pair
    builder; the returned minimax aggregate is verified at the
    intermediate trust boundary; the comparison is constructed with a
    placeholder content hash, finalized by the deterministic digest,
    strictly revalidated, and independently re-verified before it is
    returned. ``derived_at`` is copied exactly from the outcome matrix;
    no wall clock, randomness, or timestamp derivation exists here.
    Invalid structural or cross-source input raises ``ValueError``;
    numeric representability overflows and a non-finite minimax
    boundary propagate as ``OverflowError``; a pydantic rejection of
    any generated profile or of the generated comparison is converted
    to ``ValueError``; no partial result is ever returned and neither
    input is ever mutated.
    """
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    try:
        return _build_comparison(policy=policy, outcome_matrix=outcome_matrix)
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError(
            "campaign strategy comparison construction failed on malformed input"
        ) from exc


__all__ = ["build_campaign_strategy_comparison"]
