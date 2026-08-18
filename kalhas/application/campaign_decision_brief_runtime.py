"""Pure deterministic campaign decision brief assembly (KALHAS).

This module implements the single pure application builder that
transforms one verified ``ScenarioSpec``, one verified
``CampaignDecisionPolicy``, one verified
``CampaignOutcomeDistributionMatrix``, and one verified
``CampaignStrategyComparison`` into the complete immutable derived
``CampaignDecisionBrief`` artifact: the deterministic brief identifier
and content hash, the copied campaign/scenario/world identity, the
recorded runtime/comparison-mode/algorithm literals, the policy and
comparison references with their recorded content hashes, the exact
derived decision status with the optional preferred strategy id, the
authoritative considered-strategy order, the exact terminal reason,
the ordered decisive and blocking decision factors from the closed
catalogue, the copied robustness profiles, the copied declared
assumptions, the complete evidence references copied from the verified
outcome matrix, and the copied comparison ``derived_at`` timestamp as
``produced_at``.

The builder is pure and deterministic:

- it is store-free, API-free, query-free, activity-free, execution-
  free, replay-free, registration-free, and schema-free: it imports
  only the Python standard library, pydantic validation support, the
  three relevant contract modules, and the accepted identity/hash
  helper modules. It never imports stores, services, error modules,
  API modules, hashing helpers directly, statistics primitives,
  lower builders, adapters, domain packs, NEXUS, or LEGION;
- it reads no wall clock, uses no randomness, network, providers,
  filesystem, store, API, adapters, or domain packs, never mutates any
  input artifact, and never computes a timestamp - the brief's
  ``produced_at`` is copied exactly from the verified comparison;
- it performs no paired-delta, evidence, dominance, Pareto, regret, or
  minimax recomputation - the decision derives exclusively from the
  verified recorded facts of the supplied comparison (feasibility
  flags, factual dominance tuples, and maximum total weighted regrets)
  against the verified policy decision rules - and calls no lower
  comparison, selection, evidence, paired, statistics, outcome,
  execution, or replay builder.

Composition
-----------

The exact composition order is fixed: all four source artifacts are
strictly revalidated from detached Python-mode serialization; every
recorded identifier and content hash is recomputed and verified,
including the scenario content hash through the accepted
scenario-content-hash helper; every cross-source fact directly
represented by the four inputs is enforced (tenant ownership,
campaign/scenario/world/evaluation-profile identity and content
hashes, the runtime/comparison-mode/algorithm literals, the policy and
source-outcome-matrix references, the tie-tolerance and
minimum-sample-count snapshots, the exact ordered strategy/seed/
objective tuples, the derived timestamps, the both-or-neither
uncertainty provenance, the per-profile authoritative position and
identity, the exact policy target coverage, the hard-gate feasibility
semantics computed from authoritative thresholds and outcome
probabilities, and the exact value binding of every target-feasibility,
target-achievement-probability, and downside-evidence record to the
verified policy thresholds and outcome rows); the decision status is
derived
from the verified policy and comparison with the exact inclusive
minimax tie rule; the terminal reason, the ordered decisive/blocking
factors, and the deterministic summary are assembled from the closed
catalogue and the fixed templates; the brief is constructed with the
deterministic identifier and a placeholder content hash; the content
hash is computed over the placeholder and finalized via an immutable
copy; and the final artifact is strictly revalidated and independently
re-verified before it is returned. No partial artifact ever escapes.

Error semantics
---------------

Invalid structural or cross-source input raises ``ValueError``; a
numeric representability overflow raised by strict source validation
and a non-finite minimax decision boundary propagate as
``OverflowError``; a pydantic rejection of any generated reason,
factor, or of the generated brief is converted to ``ValueError``; and
the builder either returns the complete immutable artifact or raises.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal, NamedTuple

from pydantic import BaseModel

from kalhas.application.campaign_decision_identity import (
    campaign_decision_brief_content_hash,
    campaign_decision_brief_identifier,
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
    campaign_strategy_comparison_content_hash,
    campaign_strategy_comparison_identifier,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.application.objective_evaluation_identity import scenario_content_hash
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    DecisionFactorCode,
    DecisionFactorRecord,
    DecisionReasonCode,
    DecisionReasonRecord,
    ObjectiveDownsideEvidence,
    ObjectiveFeasibilityEvidence,
    ObjectiveProbabilityEvidence,
    StrategyRobustnessProfile,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix
from kalhas.contracts.v1.scenario import ScenarioSpec

#: The accepted decision algorithm identifier (closed literal).
_ALGORITHM_IDENTIFIER: Literal["feasibility-pareto-minimax-regret-v1"] = (
    "feasibility-pareto-minimax-regret-v1"
)

#: The required recorded runtime version.
_REQUIRED_RUNTIME_VERSION: Literal["3.0.0"] = "3.0.0"

#: The required recorded comparison mode.
_REQUIRED_COMPARISON_MODE: Literal["identical_conditions"] = "identical_conditions"

#: The placeholder content hash of the draft brief.
_PLACEHOLDER_CONTENT_HASH = "0" * 64

#: The fixed deterministic summary template for the preferred status.
_SUMMARY_PREFERRED = (
    "Strategy {id} is preferred under policy {policy_id}: feasible, non-dominated, "
    "unique minimum maximum total weighted regret ({max_regret})."
)

#: The fixed deterministic summary template for the inconclusive status.
_SUMMARY_INCONCLUSIVE = (
    "No preferred strategy is issued: {n} feasible non-dominated strategies remain "
    "tied within the declared tolerance ({tolerance})."
)

#: The fixed deterministic summary template for the insufficient-evidence status.
_SUMMARY_INSUFFICIENT = (
    "Decision is insufficient_evidence: campaign seed count ({seeds}) is below the "
    "declared minimum sample count ({minimum})."
)

#: The fixed deterministic summary template for the no-feasible-strategy status.
_SUMMARY_NO_FEASIBLE = (
    "No feasible strategy exists: none of the {considered} considered strategies "
    "meets every hard target-achievement threshold."
)


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


def _verify_policy_identity(policy: CampaignDecisionPolicy) -> None:
    """Recompute and verify the recorded policy identifier and content hash."""
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


def _verify_comparison_identity(
    comparison: CampaignStrategyComparison,
    evaluation_profile_id: str,
) -> None:
    """Recompute and verify the recorded comparison identifier and content hash.

    The comparison identifier derivation covers the evaluation-profile
    identity, which the comparison artifact does not record itself; the
    verified outcome matrix (cross-checked against the policy) supplies
    the authoritative evaluation-profile identity.
    """
    expected_identifier = campaign_strategy_comparison_identifier(
        campaign_id=comparison.campaign_id,
        world_version_id=comparison.world_version_id,
        evaluation_profile_id=evaluation_profile_id,
        policy_id=comparison.policy_id,
        source_outcome_matrix_id=comparison.source_outcome_matrix_id,
    )
    if comparison.identifier != expected_identifier:
        raise ValueError("comparison identifier does not match its deterministic derivation")
    if comparison.content_hash != campaign_strategy_comparison_content_hash(comparison):
        raise ValueError("comparison content hash does not match its deterministic derivation")


def _verify_scenario_authority(
    scenario: ScenarioSpec,
    policy: CampaignDecisionPolicy,
) -> None:
    """Bind the supplied scenario to the verified policy scenario identity.

    The scenario identifier and tenant must equal the policy record and
    the scenario content hash must equal the policy's recorded scenario
    content hash through the accepted scenario-content-hash helper. The
    recorded hash is never trusted or repaired.
    """
    if scenario.identifier != policy.scenario_id:
        raise ValueError("scenario identifier must equal the policy scenario identity")
    if scenario.tenant_id != policy.tenant_id:
        raise ValueError("scenario tenant must equal the policy tenant")
    if scenario_content_hash(scenario) != policy.scenario_content_hash:
        raise ValueError("scenario content hash must equal the policy scenario content hash")


def _verify_cross_source_agreement(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> None:
    """Independently enforce every cross-source fact represented by the inputs."""
    if policy.tenant_id != outcome_matrix.tenant_id:
        raise ValueError("policy tenant and outcome matrix tenant must agree")
    if outcome_matrix.tenant_id != comparison.tenant_id:
        raise ValueError("outcome matrix tenant and comparison tenant must agree")
    if policy.campaign_id != outcome_matrix.campaign_id:
        raise ValueError("policy campaign and outcome matrix campaign must agree")
    if outcome_matrix.campaign_id != comparison.campaign_id:
        raise ValueError("outcome matrix campaign and comparison campaign must agree")
    if policy.scenario_id != outcome_matrix.scenario_id:
        raise ValueError("policy scenario and outcome matrix scenario must agree")
    if outcome_matrix.scenario_id != comparison.scenario_id:
        raise ValueError("outcome matrix scenario and comparison scenario must agree")
    if policy.scenario_content_hash != outcome_matrix.scenario_content_hash:
        raise ValueError("policy and outcome matrix scenario content hashes must agree")
    if outcome_matrix.scenario_content_hash != comparison.scenario_content_hash:
        raise ValueError("outcome matrix and comparison scenario content hashes must agree")
    if policy.world_version_id != outcome_matrix.world_version_id:
        raise ValueError("policy world version and outcome matrix world version must agree")
    if outcome_matrix.world_version_id != comparison.world_version_id:
        raise ValueError("outcome matrix world version and comparison world version must agree")
    if policy.world_content_hash != outcome_matrix.world_content_hash:
        raise ValueError("policy and outcome matrix world content hashes must agree")
    if outcome_matrix.world_content_hash != comparison.world_content_hash:
        raise ValueError("outcome matrix and comparison world content hashes must agree")
    if policy.evaluation_profile_id != outcome_matrix.evaluation_profile_id:
        raise ValueError(
            "policy evaluation profile and outcome matrix evaluation profile must agree"
        )
    if policy.evaluation_profile_content_hash != outcome_matrix.evaluation_profile_content_hash:
        raise ValueError("policy and outcome matrix evaluation profile content hashes must agree")
    if outcome_matrix.runtime_version != _REQUIRED_RUNTIME_VERSION:
        raise ValueError("outcome matrix runtime version must be the accepted literal")
    if comparison.runtime_version != _REQUIRED_RUNTIME_VERSION:
        raise ValueError("comparison runtime version must be the accepted literal")
    if outcome_matrix.comparison_mode != _REQUIRED_COMPARISON_MODE:
        raise ValueError("outcome comparison mode must be the accepted literal")
    if comparison.comparison_mode != _REQUIRED_COMPARISON_MODE:
        raise ValueError("comparison comparison mode must be the accepted literal")
    if policy.algorithm_identifier != _ALGORITHM_IDENTIFIER:
        raise ValueError("policy algorithm identifier is not the accepted literal")
    if comparison.algorithm_identifier != _ALGORITHM_IDENTIFIER:
        raise ValueError("comparison algorithm identifier is not the accepted literal")
    if comparison.policy_id != policy.identifier:
        raise ValueError("comparison policy reference must equal the policy identifier")
    if comparison.policy_content_hash != policy.content_hash:
        raise ValueError(
            "comparison policy content hash reference must equal the policy content hash"
        )
    if comparison.source_outcome_matrix_id != outcome_matrix.identifier:
        raise ValueError(
            "comparison source matrix reference must equal the outcome matrix identifier"
        )
    if comparison.source_outcome_matrix_content_hash != outcome_matrix.content_hash:
        raise ValueError(
            "comparison source matrix content hash reference must equal the "
            "outcome matrix content hash"
        )
    if comparison.tie_tolerance != policy.tie_tolerance:
        raise ValueError("comparison tie tolerance snapshot must equal the policy tolerance")
    if comparison.minimum_sample_count != policy.minimum_sample_count:
        raise ValueError("comparison minimum sample count snapshot must equal the policy minimum")
    if comparison.ordered_strategy_candidate_ids != outcome_matrix.ordered_strategy_candidate_ids:
        raise ValueError("comparison and outcome matrix strategy order must agree")
    if comparison.ordered_scenario_seed_ids != outcome_matrix.ordered_scenario_seed_ids:
        raise ValueError("comparison and outcome matrix seed order must agree")
    if comparison.ordered_objective_ids != outcome_matrix.ordered_objective_ids:
        raise ValueError("comparison and outcome matrix objective order must agree")
    if comparison.derived_at != outcome_matrix.derived_at:
        raise ValueError("comparison derived_at must equal the outcome matrix derived_at")
    if (outcome_matrix.uncertainty_model_id is None) != (
        outcome_matrix.uncertainty_model_content_hash is None
    ):
        raise ValueError("uncertainty model provenance must be both present or both absent")


def _verify_profiles(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> None:
    """Verify every recorded robustness profile against its authoritative sources.

    Beyond the exact authoritative strategy position and identity, the
    profile's recorded evidence is independently bound back to the
    verified policy and outcome matrix. The policy target coverage must
    be exact: global mode applies its single threshold to every
    targeted objective and forbids per-objective requirements;
    per-objective mode must carry exactly the targeted objectives in
    exact objective order with the exact recorded thresholds. Every
    target-feasibility record must equal the authoritative objective
    identity, the exact policy threshold, the exact authoritative
    outcome probability, and the exact derived passed flag; every
    target-achievement-probability record must equal the authoritative
    outcome value with exact coverage and order; every downside-
    evidence record must equal the authoritative outcome values for
    every objective in exact objective order (None preserved exactly);
    and the profile feasible flag must equal the authoritative
    hard-gate result computed from the authoritative thresholds and
    outcome probabilities - never from potentially forged profile
    thresholds.
    """
    strategy_ids = comparison.ordered_strategy_candidate_ids
    objective_ids = comparison.ordered_objective_ids
    objective_count = len(objective_ids)
    targeted_ids = tuple(
        objective_ids[objective_position]
        for objective_position in range(objective_count)
        if outcome_matrix.outcomes[objective_position].target is not None
    )

    if policy.target_requirement_mode == "global":
        if policy.objective_target_requirements:
            raise ValueError("global target mode forbids per-objective target requirements")
        global_threshold = policy.minimum_target_achievement_probability
        if global_threshold is None:
            raise ValueError(
                "global target mode requires the global target-achievement probability"
            )
        authoritative_thresholds = {objective_id: global_threshold for objective_id in targeted_ids}
    else:
        requirement_ids = [
            requirement.objective_id for requirement in policy.objective_target_requirements
        ]
        if requirement_ids != list(targeted_ids):
            raise ValueError(
                "per-objective target requirements must cover exactly the targeted "
                "objectives in objective order"
            )
        authoritative_thresholds = {
            requirement.objective_id: requirement.minimum_target_achievement_probability
            for requirement in policy.objective_target_requirements
        }

    for position, profile in enumerate(comparison.robustness_profiles):
        if not isinstance(profile, StrategyRobustnessProfile):
            raise ValueError(
                "every comparison robustness profile must be a StrategyRobustnessProfile"
            )
        if profile.strategy_position != position:
            raise ValueError(
                "robustness profile positions must match the authoritative strategy order"
            )
        if profile.strategy_candidate_id != strategy_ids[position]:
            raise ValueError(
                "robustness profile identity must match the authoritative strategy order"
            )
        objective_row = {
            objective_ids[objective_position]: outcome_matrix.outcomes[
                position * objective_count + objective_position
            ]
            for objective_position in range(objective_count)
        }
        authoritative_probabilities: dict[str, float] = {}
        for objective_id in targeted_ids:
            row_probability = objective_row[objective_id].empirical_target_achievement_probability
            if row_probability is None:
                raise ValueError(
                    "authoritative outcome probability must be present for a targeted objective"
                )
            authoritative_probabilities[objective_id] = row_probability

        feasibility = profile.target_feasibility
        if type(feasibility) is not tuple:
            raise ValueError("robustness profile target feasibility must be an exact tuple")
        feasibility_ids: list[str] = []
        for record in feasibility:
            if not isinstance(record, ObjectiveFeasibilityEvidence):
                raise ValueError(
                    "every target feasibility record must be an ObjectiveFeasibilityEvidence"
                )
            feasibility_ids.append(record.objective_id)
        if feasibility_ids != list(targeted_ids):
            raise ValueError(
                "robustness profile target feasibility must cover exactly the "
                "targeted objectives in order"
            )
        for record, objective_id in zip(feasibility, targeted_ids, strict=True):
            threshold = authoritative_thresholds[objective_id]
            authoritative_probability = authoritative_probabilities[objective_id]
            if record.threshold != threshold:
                raise ValueError(
                    "target feasibility threshold must equal the authoritative policy threshold"
                )
            if record.observed_probability != authoritative_probability:
                raise ValueError(
                    "target feasibility observed probability must equal the authoritative "
                    "outcome probability"
                )
            expected_passed = authoritative_probability >= threshold
            if record.passed is not expected_passed:
                raise ValueError(
                    "target feasibility passed flag must equal the authoritative outcome comparison"
                )

        probabilities = profile.target_achievement_probabilities
        if type(probabilities) is not tuple:
            raise ValueError(
                "robustness profile target achievement probabilities must be an exact tuple"
            )
        probability_ids: list[str] = []
        for probability_record in probabilities:
            if not isinstance(probability_record, ObjectiveProbabilityEvidence):
                raise ValueError(
                    "every target achievement probability record must be an "
                    "ObjectiveProbabilityEvidence"
                )
            probability_ids.append(probability_record.objective_id)
        if probability_ids != list(targeted_ids):
            raise ValueError(
                "robustness profile target achievement probabilities must cover exactly "
                "the targeted objectives in order"
            )
        for probability_record, objective_id in zip(probabilities, targeted_ids, strict=True):
            if (
                probability_record.empirical_target_achievement_probability
                != (authoritative_probabilities[objective_id])
            ):
                raise ValueError(
                    "target achievement probability must equal the authoritative "
                    "outcome probability"
                )

        downside = profile.downside_evidence
        if type(downside) is not tuple:
            raise ValueError("robustness profile downside evidence must be an exact tuple")
        downside_ids: list[str] = []
        for downside_record in downside:
            if not isinstance(downside_record, ObjectiveDownsideEvidence):
                raise ValueError(
                    "every downside evidence record must be an ObjectiveDownsideEvidence"
                )
            downside_ids.append(downside_record.objective_id)
        if downside_ids != list(objective_ids):
            raise ValueError(
                "robustness profile downside evidence must cover every objective exactly "
                "once in objective order"
            )
        for downside_record, objective_id in zip(downside, objective_ids, strict=True):
            authoritative_row = objective_row[objective_id]
            if downside_record.worst_normalized_target_violation != (
                authoritative_row.worst_normalized_target_violation
            ):
                raise ValueError(
                    "worst normalized target violation must equal the authoritative outcome value"
                )
            if downside_record.target_violation_cvar != authoritative_row.target_violation_cvar:
                raise ValueError("target violation CVaR must equal the authoritative outcome value")
            if downside_record.adverse_tail_statistic != (authoritative_row.adverse_tail_statistic):
                raise ValueError(
                    "adverse tail statistic must equal the authoritative outcome value"
                )

        authoritative_feasible = not policy.all_targeted_objectives_are_hard_gates or all(
            authoritative_probabilities[objective_id] >= authoritative_thresholds[objective_id]
            for objective_id in targeted_ids
        )
        if profile.feasible is not authoritative_feasible:
            raise ValueError(
                "robustness profile feasible flag must follow the accepted hard-gate rule"
            )


class _DecisionState(NamedTuple):
    """The complete derived decision state of one brief build."""

    status: Literal["preferred", "inconclusive", "insufficient_evidence", "no_feasible_strategy"]
    preferred_strategy_id: str | None
    best_maximum_total_weighted_regret: float | None
    tie_set: tuple[str, ...]
    candidates: tuple[str, ...]


def _derive_decision(
    *,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> _DecisionState:
    """Derive the exact decision status from the verified recorded facts.

    The seed-count gate runs first; the hard-gate feasibility gate runs
    only when hard gates are enabled; the feasible non-dominated
    candidate tuple derives from the recorded feasibility flags and the
    factual dominance tuples; the best maximum total weighted regret is
    the exact minimum over the candidates; the tie set is the exact
    inclusive ``<= best + tie_tolerance`` set; and the status is
    ``preferred`` exactly when the tie set is a singleton. A non-finite
    best-plus-tolerance boundary raises ``OverflowError``; an empty
    candidate tuple on an evaluated decision is invalid input and
    raises ``ValueError``.
    """
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)
    profiles = comparison.robustness_profiles
    feasible_set = {
        profile.strategy_candidate_id for profile in profiles if profile.feasible is True
    }
    candidates = tuple(
        profile.strategy_candidate_id
        for profile in profiles
        if profile.feasible is True
        and not any(dominator in feasible_set for dominator in profile.dominated_by)
    )
    max_regret_by_id = {
        profile.strategy_candidate_id: profile.maximum_total_weighted_regret for profile in profiles
    }
    if seed_count < policy.minimum_sample_count:
        return _DecisionState("insufficient_evidence", None, None, (), ())
    if policy.all_targeted_objectives_are_hard_gates and not feasible_set:
        return _DecisionState("no_feasible_strategy", None, None, (), ())
    if not candidates:
        raise ValueError("the feasible non-dominated candidate set must not be empty")
    best = min(max_regret_by_id[candidate_id] for candidate_id in candidates)
    boundary = best + policy.tie_tolerance
    if not math.isfinite(boundary):
        raise OverflowError("best maximum total weighted regret plus tie tolerance is not finite")
    tie_set = tuple(
        candidate_id for candidate_id in candidates if max_regret_by_id[candidate_id] <= boundary
    )
    if len(tie_set) == 1:
        return _DecisionState("preferred", tie_set[0], best, tie_set, candidates)
    return _DecisionState("inconclusive", None, best, tie_set, candidates)


def _require_best(state: _DecisionState) -> float:
    """The best maximum total weighted regret of an evaluated minimax state."""
    if state.best_maximum_total_weighted_regret is None:
        raise ValueError("preferred or inconclusive status requires the minimax best regret")
    return state.best_maximum_total_weighted_regret


def _reason(
    *,
    code: DecisionReasonCode,
    values: tuple[int | float, ...],
    related: tuple[str, ...] = (),
) -> DecisionReasonRecord:
    """One generated terminal reason; a contract rejection becomes ``ValueError``."""
    try:
        return DecisionReasonRecord(code=code, values=values, related_strategy_ids=related)
    except ValueError as exc:
        raise ValueError("generated decision reason violates its contract") from exc


def _factor(
    *,
    code: DecisionFactorCode,
    strategy_id: str | None = None,
    objective_id: str | None = None,
    values: tuple[int | float, ...] = (),
    related: tuple[str, ...] = (),
) -> DecisionFactorRecord:
    """One generated decision factor; a contract rejection becomes ``ValueError``."""
    try:
        return DecisionFactorRecord(
            code=code,
            strategy_id=strategy_id,
            objective_id=objective_id,
            values=values,
            related_strategy_ids=related,
        )
    except ValueError as exc:
        raise ValueError("generated decision factor violates its contract") from exc


def _build_reason(
    *,
    state: _DecisionState,
    policy: CampaignDecisionPolicy,
    seed_count: int,
    considered_count: int,
) -> DecisionReasonRecord:
    """The exact terminal reason of the derived status."""
    if state.status == "preferred":
        return _reason(
            code="unique_minimax_preference",
            values=(_require_best(state), policy.tie_tolerance),
        )
    if state.status == "inconclusive":
        return _reason(
            code="regret_tie_within_tolerance",
            values=(_require_best(state), policy.tie_tolerance),
            related=state.tie_set,
        )
    if state.status == "insufficient_evidence":
        return _reason(
            code="insufficient_seed_samples",
            values=(policy.minimum_sample_count, seed_count),
        )
    return _reason(code="no_feasible_strategy", values=(considered_count, 0))


def _build_decisive_factors(
    *,
    policy: CampaignDecisionPolicy,
    profiles: tuple[StrategyRobustnessProfile, ...],
    candidates: tuple[str, ...],
    state: _DecisionState,
) -> tuple[DecisionFactorRecord, ...]:
    """The ordered decisive factor trail in exact pipeline-stage order."""
    if state.status == "insufficient_evidence":
        return ()
    max_regret_by_id = {
        profile.strategy_candidate_id: profile.maximum_total_weighted_regret for profile in profiles
    }
    decisive: list[DecisionFactorRecord] = []
    for profile in profiles:
        if profile.feasible is True:
            decisive.append(
                _factor(code="feasible_candidate", strategy_id=profile.strategy_candidate_id)
            )
    if policy.all_targeted_objectives_are_hard_gates:
        for profile in profiles:
            for record in profile.target_feasibility:
                if record.passed is True:
                    decisive.append(
                        _factor(
                            code="target_feasibility_passed",
                            strategy_id=profile.strategy_candidate_id,
                            objective_id=record.objective_id,
                            values=(record.threshold, record.observed_probability),
                        )
                    )
    for candidate_id in candidates:
        decisive.append(_factor(code="pareto_non_dominated", strategy_id=candidate_id))
    if state.status == "preferred" and len(candidates) > 1:
        preferred_id = state.preferred_strategy_id
        if preferred_id is None:
            raise ValueError("preferred status requires the preferred strategy id")
        competitors = [candidate for candidate in candidates if candidate != preferred_id]
        nearest_id = competitors[0]
        nearest_max = max_regret_by_id[nearest_id]
        for candidate_id in competitors[1:]:
            candidate_max = max_regret_by_id[candidate_id]
            if candidate_max < nearest_max:
                nearest_max = candidate_max
                nearest_id = candidate_id
        winner_max = max_regret_by_id[preferred_id]
        decisive.append(
            _factor(
                code="unique_minimax_regret",
                strategy_id=preferred_id,
                related=(nearest_id,),
                values=(winner_max, nearest_max, nearest_max - winner_max),
            )
        )
    return tuple(decisive)


def _build_blocking_factors(
    *,
    policy: CampaignDecisionPolicy,
    profiles: tuple[StrategyRobustnessProfile, ...],
    state: _DecisionState,
    seed_count: int,
    considered_count: int,
) -> tuple[DecisionFactorRecord, ...]:
    """The ordered blocking factor trail in exact pipeline-stage order."""
    if state.status == "insufficient_evidence":
        return (
            _factor(
                code="insufficient_seed_count",
                values=(policy.minimum_sample_count, seed_count),
            ),
        )
    blocking: list[DecisionFactorRecord] = []
    if policy.all_targeted_objectives_are_hard_gates:
        for profile in profiles:
            for record in profile.target_feasibility:
                if record.passed is not True:
                    blocking.append(
                        _factor(
                            code="objective_target_failed",
                            strategy_id=profile.strategy_candidate_id,
                            objective_id=record.objective_id,
                            values=(record.threshold, record.observed_probability),
                        )
                    )
    feasible_set = {
        profile.strategy_candidate_id for profile in profiles if profile.feasible is True
    }
    for profile in profiles:
        if profile.feasible is not True:
            continue
        feasible_dominators = tuple(
            dominator for dominator in profile.dominated_by if dominator in feasible_set
        )
        if feasible_dominators:
            blocking.append(
                _factor(
                    code="dominated_strategy",
                    strategy_id=profile.strategy_candidate_id,
                    related=feasible_dominators,
                )
            )
    if state.status == "inconclusive":
        blocking.append(
            _factor(
                code="minimax_regret_tie",
                related=state.tie_set,
                values=(_require_best(state), policy.tie_tolerance),
            )
        )
    elif state.status == "no_feasible_strategy":
        blocking.append(_factor(code="no_feasible_strategy", values=(considered_count, 0)))
    return tuple(blocking)


def _build_summary(
    *,
    state: _DecisionState,
    policy: CampaignDecisionPolicy,
    seed_count: int,
    considered_count: int,
) -> str:
    """The exact deterministic summary from the fixed templates."""
    if state.status == "preferred":
        if state.preferred_strategy_id is None:
            raise ValueError("preferred status requires the preferred strategy id")
        return _SUMMARY_PREFERRED.format(
            id=state.preferred_strategy_id,
            policy_id=policy.identifier,
            max_regret=str(_require_best(state)),
        )
    if state.status == "inconclusive":
        return _SUMMARY_INCONCLUSIVE.format(
            n=len(state.tie_set), tolerance=str(policy.tie_tolerance)
        )
    if state.status == "insufficient_evidence":
        return _SUMMARY_INSUFFICIENT.format(seeds=seed_count, minimum=policy.minimum_sample_count)
    return _SUMMARY_NO_FEASIBLE.format(considered=considered_count)


def _build_brief(
    *,
    scenario: ScenarioSpec,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> CampaignDecisionBrief:
    """The complete validated construction pipeline (see the public builder)."""
    _strictly_revalidate_detached(scenario, ScenarioSpec)
    _strictly_revalidate_detached(policy, CampaignDecisionPolicy)
    _strictly_revalidate_detached(outcome_matrix, CampaignOutcomeDistributionMatrix)
    _strictly_revalidate_detached(comparison, CampaignStrategyComparison)
    if _contains_non_finite(policy.metadata):
        raise ValueError("policy metadata must not contain non-finite floats")
    _verify_policy_identity(policy)
    _verify_matrix_identity(outcome_matrix)
    _verify_comparison_identity(comparison, outcome_matrix.evaluation_profile_id)
    _verify_scenario_authority(scenario, policy)
    _verify_cross_source_agreement(
        policy=policy, outcome_matrix=outcome_matrix, comparison=comparison
    )
    _verify_profiles(policy=policy, outcome_matrix=outcome_matrix, comparison=comparison)

    state = _derive_decision(policy=policy, outcome_matrix=outcome_matrix, comparison=comparison)
    seed_count = len(outcome_matrix.ordered_scenario_seed_ids)
    considered_count = len(comparison.ordered_strategy_candidate_ids)
    reason = _build_reason(
        state=state,
        policy=policy,
        seed_count=seed_count,
        considered_count=considered_count,
    )
    decisive_factors = _build_decisive_factors(
        policy=policy,
        profiles=comparison.robustness_profiles,
        candidates=state.candidates,
        state=state,
    )
    blocking_factors = _build_blocking_factors(
        policy=policy,
        profiles=comparison.robustness_profiles,
        state=state,
        seed_count=seed_count,
        considered_count=considered_count,
    )
    summary = _build_summary(
        state=state,
        policy=policy,
        seed_count=seed_count,
        considered_count=considered_count,
    )

    brief_identifier = campaign_decision_brief_identifier(
        campaign_id=comparison.campaign_id,
        world_version_id=comparison.world_version_id,
        policy_id=policy.identifier,
        comparison_id=comparison.identifier,
    )
    try:
        placeholder = CampaignDecisionBrief(
            identifier=brief_identifier,
            tenant_id=comparison.tenant_id,
            schema_version=comparison.schema_version,
            campaign_id=comparison.campaign_id,
            scenario_id=comparison.scenario_id,
            world_version_id=comparison.world_version_id,
            world_content_hash=comparison.world_content_hash,
            runtime_version=_REQUIRED_RUNTIME_VERSION,
            comparison_mode=_REQUIRED_COMPARISON_MODE,
            algorithm_identifier=comparison.algorithm_identifier,
            policy_id=policy.identifier,
            policy_content_hash=policy.content_hash,
            comparison_id=comparison.identifier,
            comparison_content_hash=comparison.content_hash,
            status=state.status,
            preferred_strategy_id=state.preferred_strategy_id,
            considered_strategy_ids=comparison.ordered_strategy_candidate_ids,
            summary=summary,
            terminal_reason=reason,
            decisive_factors=decisive_factors,
            blocking_factors=blocking_factors,
            robustness_profiles=comparison.robustness_profiles,
            assumptions=tuple(scenario.assumptions),
            evaluation_profile_id=outcome_matrix.evaluation_profile_id,
            evaluation_profile_content_hash=outcome_matrix.evaluation_profile_content_hash,
            uncertainty_model_id=outcome_matrix.uncertainty_model_id,
            uncertainty_model_content_hash=outcome_matrix.uncertainty_model_content_hash,
            source_world_realization_matrix_id=outcome_matrix.source_world_realization_matrix_id,
            source_world_realization_matrix_content_hash=(
                outcome_matrix.source_world_realization_matrix_content_hash
            ),
            source_metric_observation_matrix_id=outcome_matrix.source_metric_observation_matrix_id,
            source_metric_observation_matrix_content_hash=(
                outcome_matrix.source_metric_observation_matrix_content_hash
            ),
            source_outcome_matrix_id=outcome_matrix.identifier,
            source_outcome_matrix_content_hash=outcome_matrix.content_hash,
            content_hash=_PLACEHOLDER_CONTENT_HASH,
            produced_at=comparison.derived_at,
        )
    except ValueError as exc:
        raise ValueError("generated campaign decision brief violates its contract") from exc

    computed_hash = campaign_decision_brief_content_hash(placeholder)
    final = placeholder.model_copy(update={"content_hash": computed_hash})

    _strictly_revalidate_detached(final, CampaignDecisionBrief)

    recomputed_identifier = campaign_decision_brief_identifier(
        campaign_id=comparison.campaign_id,
        world_version_id=comparison.world_version_id,
        policy_id=policy.identifier,
        comparison_id=comparison.identifier,
    )
    if final.identifier != recomputed_identifier:
        raise ValueError("final brief identifier must equal its deterministic derivation")
    if final.content_hash != campaign_decision_brief_content_hash(final):
        raise ValueError("final brief content hash must equal its deterministic derivation")
    return final


def build_campaign_decision_brief(
    *,
    scenario: ScenarioSpec,
    policy: CampaignDecisionPolicy,
    outcome_matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> CampaignDecisionBrief:
    """Build the complete immutable derived campaign decision brief.

    Transforms one verified scenario, one matching decision policy, one
    verified outcome matrix, and one matching derived comparison into
    the complete immutable ``CampaignDecisionBrief``: the deterministic
    identifier and content hash, the copied identity and source
    references, the recorded literals, the exact derived status with
    the optional preferred strategy id, the authoritative considered
    order, the exact terminal reason, the ordered decisive/blocking
    factors, the copied robustness profiles and declared assumptions,
    and the copied evidence references with ``produced_at`` equal to
    the comparison ``derived_at``. All four inputs must be exact
    contract instances and are strictly revalidated from detached
    Python-mode serialization before any field is trusted; every
    recorded identifier and content hash is recomputed and verified,
    including the scenario content hash; every cross-source fact
    directly represented by the inputs is enforced; the decision is
    derived exclusively from the verified recorded comparison facts and
    policy rules with the exact inclusive minimax tie rule; the brief
    is constructed with a placeholder content hash, finalized by the
    deterministic digest, strictly revalidated, and independently
    re-verified before it is returned. Invalid structural or cross-
    source input raises ``ValueError``; numeric representability
    overflows and a non-finite minimax decision boundary propagate as
    ``OverflowError``; a pydantic rejection of any generated reason,
    factor, or of the generated brief is converted to ``ValueError``;
    no partial result is ever returned and no input is ever mutated.
    """
    if not isinstance(scenario, ScenarioSpec):
        raise ValueError("scenario must be a ScenarioSpec instance")
    if not isinstance(policy, CampaignDecisionPolicy):
        raise ValueError("policy must be a CampaignDecisionPolicy instance")
    if not isinstance(outcome_matrix, CampaignOutcomeDistributionMatrix):
        raise ValueError("outcome_matrix must be a CampaignOutcomeDistributionMatrix instance")
    if not isinstance(comparison, CampaignStrategyComparison):
        raise ValueError("comparison must be a CampaignStrategyComparison instance")
    try:
        return _build_brief(
            scenario=scenario,
            policy=policy,
            outcome_matrix=outcome_matrix,
            comparison=comparison,
        )
    except (TypeError, AttributeError, IndexError, KeyError) as exc:
        raise ValueError("campaign decision brief construction failed on malformed input") from exc


__all__ = ["build_campaign_decision_brief"]
