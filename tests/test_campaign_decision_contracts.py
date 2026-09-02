"""Tests for the immutable campaign decision contract surface.

Exhaustive focused tests for ``kalhas/contracts/v1/campaign_decision.py``:
the three top-level artifacts (``CampaignDecisionPolicy``,
``CampaignStrategyComparison``, ``CampaignDecisionBrief``) and their
nested immutable records. Proves:

- valid construction of every top-level and nested record;
- strict frozen behavior, extra-field rejection, and tuple immutability;
- the policy rules: global/per-objective mode XOR, scenario/evaluation/
  world binding fields, objective-weight snapshot uniqueness with the
  supplied authoritative order preserved exactly (never sorted),
  fixed ``tail_alpha == 0.95`` with every alternative rejected,
  exact-int ``minimum_sample_count`` with ``>= 1``, inclusive
  probability bands, non-negative tie tolerance, all-zero weights
  representable, finite-only metadata;
- the exact numeric input policy everywhere: exact int/float
  acceptance, bool/string/``Decimal``/``None``/container rejection,
  NaN/Infinity rejection, huge-integer finite-float rejection;
- the complete ordered-pair cardinality ``S * (S - 1) * O``, no
  self-pairs, the deterministic pair-major/objective-minor ordering
  formula, and missing/duplicate/reversed/additional record rejection;
- the reverse-pair delta/count/quantile/extrema relationships;
- the dominance-relation rules (status derivation from each
  direction's own counts, forward-record agreement, independent
  reverse status derivation with the four crossing cases, no mutual
  dominance);
- the robustness-profile rules (pipeline-feasibility representability
  independent of the recorded ``passed`` flags, full-coverage
  per-objective order for regret/downside evidence, target-only tuple
  rules for feasibility/achievement probabilities, regret extrema,
  dominance cross-checks);
- the brief decision rules (status/preferred-id, terminal-reason
  code-to-status compatibility, decisive/blocking factor catalogue and
  pipeline-stage ordering, both-or-neither uncertainty provenance,
  status-to-feasibility rules);
- malformed hashes and empty identifiers rejected, and no
  executable/callback-like typed surface (AST module boundary).

The three decision contracts are registered at ``PUBLIC_CONTRACTS``
indexes 47-49 with exactly 50 schema artifacts; the nested decision
records stay unregistered.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    DecisionFactorRecord,
    DecisionReasonRecord,
    DominanceRelation,
    ObjectiveDominanceStatus,
    ObjectiveDownsideEvidence,
    ObjectiveFeasibilityEvidence,
    ObjectivePairedComparison,
    ObjectiveProbabilityEvidence,
    ObjectiveRegretEvidence,
    ObjectiveTargetRequirement,
    ObjectiveWeightSnapshot,
    StrategyRobustnessProfile,
)
from pydantic import BaseModel, ValidationError

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "contracts" / "v1" / "campaign_decision.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

STRATEGIES = ("sc-a", "sc-b")
OBJECTIVES = ("obj-1", "obj-2")
SEEDS = ("seed-0", "seed-1", "seed-2")
TOLERANCE = 0.05

_ALGORITHM = "feasibility-pareto-minimax-regret-v1"


#: The exact deterministic ordered-pair position formula
#: ``(a * (S - 1) + (b if b < a else b - 1)) * O + o``.
def _pair_index(first: int, second: int, strategy_count: int) -> int:
    return first * (strategy_count - 1) + (second if second < first else second - 1)


def _relation_for(
    comparison: CampaignStrategyComparison, first: int, second: int
) -> DominanceRelation:
    """The stored dominance relation of one ordered strategy pair."""
    for relation in comparison.dominance_relations:
        if (
            relation.first_strategy_position == first
            and relation.second_strategy_position == second
        ):
            return relation
    raise AssertionError(f"missing dominance relation for ({first}, {second})")


def _type7_quantile(values: tuple[float, ...], percent: int) -> float:
    """The documented integer-index Type 7 empirical quantile (test-local)."""
    ordered = tuple(sorted(values))
    n = len(ordered)
    numerator = (n - 1) * percent
    lower = numerator // 100
    remainder = numerator % 100
    upper = min(lower + 1, n - 1)
    if remainder == 0:
        return float(ordered[lower])
    return math.fsum(
        [
            ((100 - remainder) / 100) * ordered[lower],
            (remainder / 100) * ordered[upper],
        ]
    )


def _weight_snapshot_payload(*, objective_id: str = "obj-1", weight: float = 1.0) -> dict[str, Any]:
    return {"objective_id": objective_id, "weight": weight}


def _target_requirement_payload(
    *, objective_id: str = "obj-1", probability: float = 0.4
) -> dict[str, Any]:
    return {
        "objective_id": objective_id,
        "minimum_target_achievement_probability": probability,
    }


def _paired_payload(
    *,
    sequence_position: int,
    first: int,
    second: int,
    first_id: str,
    second_id: str,
    objective_position: int,
    objective_id: str,
    tolerance: float = TOLERANCE,
    deltas: tuple[float, ...],
) -> dict[str, Any]:
    """One internally consistent paired-comparison payload (deltas in seed order)."""
    wins = ties = losses = 0
    for delta in deltas:
        if delta < -tolerance:
            wins += 1
        elif delta > tolerance:
            losses += 1
        else:
            ties += 1
    count = len(deltas)
    return {
        "sequence_position": sequence_position,
        "first_strategy_position": first,
        "second_strategy_position": second,
        "first_strategy_candidate_id": first_id,
        "second_strategy_candidate_id": second_id,
        "objective_position": objective_position,
        "objective_id": objective_id,
        "metric_id": f"m-{objective_position + 1}",
        "tie_tolerance": tolerance,
        "ordered_paired_deltas": list(deltas),
        "win_count": wins,
        "tie_count": ties,
        "loss_count": losses,
        "win_rate": wins / count,
        "tie_rate": ties / count,
        "loss_rate": losses / count,
        "median_paired_delta": _type7_quantile(deltas, 50),
        "p05_paired_delta": _type7_quantile(deltas, 5),
        "p95_paired_delta": _type7_quantile(deltas, 95),
        "worst_paired_delta": max(deltas),
        "best_paired_delta": min(deltas),
    }


def _status_payload(objective_id: str, comparison: dict[str, Any]) -> dict[str, Any]:
    """One dominance status derived from a stored forward paired comparison."""
    wins = int(comparison["win_count"])
    ties = int(comparison["tie_count"])
    losses = int(comparison["loss_count"])
    if losses > 0:
        status = "worse"
    elif wins > 0:
        status = "better"
    else:
        status = "tied"
    return {
        "objective_id": objective_id,
        "status": status,
        "win_count": wins,
        "tie_count": ties,
        "loss_count": losses,
        "median_paired_delta": comparison["median_paired_delta"],
    }


def _relation_payload(
    first: int,
    second: int,
    first_id: str,
    second_id: str,
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    """One dominance relation derived from the stored forward comparisons."""
    statuses = [_status_payload(str(c["objective_id"]), c) for c in comparisons]
    statuses_list = [str(s["status"]) for s in statuses]
    dominates = "worse" not in statuses_list and "better" in statuses_list
    return {
        "first_strategy_position": first,
        "second_strategy_position": second,
        "first_strategy_candidate_id": first_id,
        "second_strategy_candidate_id": second_id,
        "dominates": dominates,
        "per_objective_status": statuses,
    }


def _profile_payload(
    *,
    position: int,
    strategy_id: str,
    feasible: bool = True,
    dominated_by: tuple[str, ...] = (),
    dominates: tuple[str, ...] = (),
    per_seed: tuple[float, ...] = (0.0, 0.5, 1.0),
    observed: tuple[float, float] = (0.6, 0.5),
    threshold: float = 0.4,
    targeted: tuple[str, ...] = ("obj-1", "obj-2"),
) -> dict[str, Any]:
    """One internally consistent robustness-profile payload.

    ``targeted`` selects the target-only tuple coverage: feasibility
    and achievement-probability records are emitted for the targeted
    objectives only (in the supplied order), while the full-coverage
    tuples always carry every objective.
    """
    observation_by_objective = {"obj-1": observed[0], "obj-2": observed[1]}
    return {
        "strategy_position": position,
        "strategy_candidate_id": strategy_id,
        "feasible": feasible,
        "target_feasibility": [
            {
                "objective_id": objective_id,
                "threshold": threshold,
                "observed_probability": observation_by_objective[objective_id],
                "passed": observation_by_objective[objective_id] >= threshold,
            }
            for objective_id in targeted
        ],
        "dominated_by": list(dominated_by),
        "dominates": list(dominates),
        "per_objective_weighted_regret": [
            {"objective_id": "obj-1", "weighted_regret": 0.25},
            {"objective_id": "obj-2", "weighted_regret": 0.5},
        ],
        "per_seed_total_weighted_regrets": list(per_seed),
        "median_total_weighted_regret": _type7_quantile(per_seed, 50),
        "p95_total_weighted_regret": _type7_quantile(per_seed, 95),
        "maximum_total_weighted_regret": max(per_seed),
        "target_achievement_probabilities": [
            {
                "objective_id": objective_id,
                "empirical_target_achievement_probability": observation_by_objective[objective_id],
            }
            for objective_id in targeted
        ],
        "downside_evidence": [
            {
                "objective_id": "obj-1",
                "worst_normalized_target_violation": 0.1,
                "target_violation_cvar": 0.1,
                "adverse_tail_statistic": 100.0,
            },
            {
                "objective_id": "obj-2",
                "worst_normalized_target_violation": 0.2,
                "target_violation_cvar": 0.2,
                "adverse_tail_statistic": 0.0,
            },
        ],
    }


#: Default per-objective-pair deltas for the standard two-strategy,
#: two-objective, three-seed fixture (sc-a dominates sc-b).
_DEFAULT_DELTAS: dict[tuple[int, int, int], tuple[float, ...]] = {
    (0, 1, 0): (-1.0, -0.5, -0.1),
    (0, 1, 1): (0.0, 0.0, 0.0),
    (1, 0, 0): (1.0, 0.5, 0.1),
    (1, 0, 1): (0.0, 0.0, 0.0),
}


def _comparison_payload(
    *,
    strategies: tuple[str, ...] = STRATEGIES,
    objectives: tuple[str, ...] = OBJECTIVES,
    seeds: tuple[str, ...] = SEEDS,
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    deltas_by_pair: dict[tuple[int, int, int], tuple[float, ...]] | None = None,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent comparison payload (all records derived)."""
    strategy_count = len(strategies)
    objective_count = len(objectives)
    deltas = deltas_by_pair if deltas_by_pair is not None else _DEFAULT_DELTAS
    comparisons: list[dict[str, Any]] = []
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            for o in range(objective_count):
                comparisons.append(
                    _paired_payload(
                        sequence_position=_pair_index(first, second, strategy_count)
                        * objective_count
                        + o,
                        first=first,
                        second=second,
                        first_id=strategies[first],
                        second_id=strategies[second],
                        objective_position=o,
                        objective_id=objectives[o],
                        tolerance=tolerance,
                        deltas=deltas[(first, second, o)],
                    )
                )
    relations: list[dict[str, Any]] = []
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            pair_comparisons = [
                c
                for c in comparisons
                if c["first_strategy_position"] == first and c["second_strategy_position"] == second
            ]
            relations.append(
                _relation_payload(
                    first, second, strategies[first], strategies[second], pair_comparisons
                )
            )
    relations_by_key = {
        (
            int(relation["first_strategy_position"]),
            int(relation["second_strategy_position"]),
        ): relation
        for relation in relations
    }
    profiles: list[dict[str, object]] = []
    for position in range(strategy_count):
        dominated_by = tuple(
            strategies[dominator]
            for dominator in range(strategy_count)
            if dominator != position and bool(relations_by_key[(dominator, position)]["dominates"])
        )
        dominates = tuple(
            strategies[dominated]
            for dominated in range(strategy_count)
            if dominated != position and bool(relations_by_key[(position, dominated)]["dominates"])
        )
        per_seed = (0.0, 0.5, 1.0) if position == 0 else (1.5, 1.0, 0.5)
        profiles.append(
            _profile_payload(
                position=position,
                strategy_id=strategies[position],
                feasible=True,
                dominated_by=dominated_by,
                dominates=dominates,
                per_seed=per_seed,
            )
        )
    payload: dict[str, Any] = {
        "identifier": "comparison-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-1",
        "world_content_hash": "b" * 64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "algorithm_identifier": _ALGORITHM,
        "policy_id": "policy-1",
        "policy_content_hash": "ab" * 32,
        "tie_tolerance": tolerance,
        "minimum_sample_count": minimum_sample_count,
        "source_outcome_matrix_id": "matrix-1",
        "source_outcome_matrix_content_hash": "f" * 64,
        "ordered_strategy_candidate_ids": list(strategies),
        "ordered_scenario_seed_ids": list(seeds),
        "ordered_objective_ids": list(objectives),
        "paired_comparisons": comparisons,
        "dominance_relations": relations,
        "robustness_profiles": profiles,
        "content_hash": "0" * 64,
        "derived_at": "2026-08-16T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _policy_payload(**overrides: object) -> dict[str, Any]:
    """One internally consistent per-objective-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "policy-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-1",
        "world_content_hash": "b" * 64,
        "evaluation_profile_id": "profile-1",
        "evaluation_profile_content_hash": "c" * 64,
        "algorithm_identifier": _ALGORITHM,
        "target_requirement_mode": "per_objective",
        "minimum_target_achievement_probability": None,
        "objective_target_requirements": [
            _target_requirement_payload(objective_id="obj-1"),
            _target_requirement_payload(objective_id="obj-2"),
        ],
        "objective_weight_snapshots": [
            _weight_snapshot_payload(objective_id="obj-1", weight=1.0),
            _weight_snapshot_payload(objective_id="obj-2", weight=0.5),
        ],
        "minimum_sample_count": 3,
        "tie_tolerance": TOLERANCE,
        "all_targeted_objectives_are_hard_gates": True,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _reason_payload(
    *, code: str, values: tuple[object, ...] = (), related: tuple[str, ...] = ()
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code}
    if values:
        payload["values"] = list(values)
    if related:
        payload["related_strategy_ids"] = list(related)
    return payload


def _factor_payload(
    *,
    code: str,
    strategy_id: str | None = None,
    objective_id: str | None = None,
    values: tuple[object, ...] = (),
    related: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code}
    if strategy_id is not None:
        payload["strategy_id"] = strategy_id
    if objective_id is not None:
        payload["objective_id"] = objective_id
    if values:
        payload["values"] = list(values)
    if related:
        payload["related_strategy_ids"] = list(related)
    return payload


def _default_decisive_factors() -> tuple[dict[str, object], ...]:
    """The frozen catalogue-ordered decisive factors of the standard preferred brief."""
    return (
        _factor_payload(code="feasible_candidate", strategy_id="sc-a"),
        _factor_payload(code="feasible_candidate", strategy_id="sc-b"),
        _factor_payload(
            code="target_feasibility_passed",
            strategy_id="sc-a",
            objective_id="obj-1",
            values=(0.4, 0.6),
        ),
        _factor_payload(
            code="target_feasibility_passed",
            strategy_id="sc-a",
            objective_id="obj-2",
            values=(0.4, 0.5),
        ),
        _factor_payload(
            code="target_feasibility_passed",
            strategy_id="sc-b",
            objective_id="obj-1",
            values=(0.4, 0.6),
        ),
        _factor_payload(
            code="target_feasibility_passed",
            strategy_id="sc-b",
            objective_id="obj-2",
            values=(0.4, 0.5),
        ),
        _factor_payload(code="pareto_non_dominated", strategy_id="sc-a"),
        _factor_payload(
            code="unique_minimax_regret",
            strategy_id="sc-a",
            related=("sc-b",),
            values=(1.0, 1.5, 0.5),
        ),
    )


def _default_blocking_factors() -> tuple[dict[str, object], ...]:
    """The frozen catalogue-ordered blocking factors of the standard preferred brief."""
    return (_factor_payload(code="dominated_strategy", strategy_id="sc-b", related=("sc-a",)),)


def _brief_payload(
    *,
    status: str = "preferred",
    preferred_strategy_id: str | None = None,
    terminal_reason: dict[str, object] | None = None,
    decisive_factors: tuple[dict[str, object], ...] | None = None,
    blocking_factors: tuple[dict[str, object], ...] | None = None,
    profiles: tuple[dict[str, object], ...] | None = None,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent brief payload (copied profiles from the comparison)."""
    if preferred_strategy_id is None and status == "preferred":
        preferred_strategy_id = "sc-a"
    if terminal_reason is None:
        if status == "preferred":
            terminal_reason = _reason_payload(code="unique_minimax_preference", values=(1.0, 0.05))
        elif status == "inconclusive":
            terminal_reason = _reason_payload(
                code="regret_tie_within_tolerance", values=(1.0, 0.05), related=("sc-a", "sc-b")
            )
        elif status == "insufficient_evidence":
            terminal_reason = _reason_payload(code="insufficient_seed_samples", values=(100, 3))
        else:
            terminal_reason = _reason_payload(code="no_feasible_strategy", values=(2, 0))
    if decisive_factors is None:
        decisive_factors = _default_decisive_factors()
    if blocking_factors is None:
        if status == "preferred":
            blocking_factors = _default_blocking_factors()
        elif status == "inconclusive":
            blocking_factors = (
                _factor_payload(
                    code="minimax_regret_tie", related=("sc-a", "sc-b"), values=(1.0, 0.05)
                ),
            )
        elif status == "insufficient_evidence":
            blocking_factors = (_factor_payload(code="insufficient_seed_count", values=(100, 3)),)
        else:
            blocking_factors = (_factor_payload(code="no_feasible_strategy", values=(2, 0)),)
    if profiles is None:
        if status == "no_feasible_strategy":
            profiles = (
                _profile_payload(
                    position=0, strategy_id="sc-a", feasible=False, observed=(0.3, 0.3)
                ),
                _profile_payload(
                    position=1,
                    strategy_id="sc-b",
                    feasible=False,
                    observed=(0.3, 0.3),
                    per_seed=(1.5, 1.0, 0.5),
                ),
            )
        else:
            profiles = (
                _profile_payload(position=0, strategy_id="sc-a"),
                _profile_payload(position=1, strategy_id="sc-b", per_seed=(1.5, 1.0, 0.5)),
            )
    payload: dict[str, Any] = {
        "identifier": "brief-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": "b" * 64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "algorithm_identifier": _ALGORITHM,
        "policy_id": "policy-1",
        "policy_content_hash": "ab" * 32,
        "comparison_id": "comparison-1",
        "comparison_content_hash": "cd" * 32,
        "status": status,
        "preferred_strategy_id": preferred_strategy_id,
        "considered_strategy_ids": list(STRATEGIES),
        "summary": f"Strategy {preferred_strategy_id} is preferred under policy policy-1.",
        "terminal_reason": terminal_reason,
        "decisive_factors": list(decisive_factors),
        "blocking_factors": list(blocking_factors),
        "robustness_profiles": list(profiles),
        "assumptions": [
            {
                "identifier": "assumption-1",
                "statement": "Declared fixture assumption.",
                "confidence": 1.0,
            }
        ],
        "evaluation_profile_id": "profile-1",
        "evaluation_profile_content_hash": "c" * 64,
        "uncertainty_model_id": None,
        "uncertainty_model_content_hash": None,
        "source_world_realization_matrix_id": "realization-matrix-1",
        "source_world_realization_matrix_content_hash": "d" * 64,
        "source_metric_observation_matrix_id": "observation-matrix-1",
        "source_metric_observation_matrix_content_hash": "e" * 64,
        "source_outcome_matrix_id": "matrix-1",
        "source_outcome_matrix_content_hash": "f" * 64,
        "content_hash": "0" * 64,
        "produced_at": "2026-08-16T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _policy(**overrides: object) -> CampaignDecisionPolicy:
    return CampaignDecisionPolicy.model_validate(_policy_payload(**overrides))


def _comparison(**overrides: object) -> CampaignStrategyComparison:
    return CampaignStrategyComparison.model_validate(_comparison_payload(**cast(Any, overrides)))


def _brief(**overrides: object) -> CampaignDecisionBrief:
    return CampaignDecisionBrief.model_validate(_brief_payload(**cast(Any, overrides)))


#: Every model class with a payload builder, for the uniform strict/frozen tests.
_MODEL_BUILDERS: tuple[tuple[type[BaseModel], Callable[[], dict[str, object]]], ...] = (
    (ObjectiveWeightSnapshot, lambda: _weight_snapshot_payload()),
    (ObjectiveTargetRequirement, lambda: _target_requirement_payload()),
    (
        ObjectivePairedComparison,
        lambda: _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        ),
    ),
    (
        ObjectiveFeasibilityEvidence,
        lambda: {
            "objective_id": "obj-1",
            "threshold": 0.4,
            "observed_probability": 0.6,
            "passed": True,
        },
    ),
    (ObjectiveRegretEvidence, lambda: {"objective_id": "obj-1", "weighted_regret": 0.25}),
    (
        ObjectiveProbabilityEvidence,
        lambda: {"objective_id": "obj-1", "empirical_target_achievement_probability": 0.6},
    ),
    (
        ObjectiveDownsideEvidence,
        lambda: {
            "objective_id": "obj-1",
            "worst_normalized_target_violation": 0.1,
            "target_violation_cvar": 0.1,
            "adverse_tail_statistic": 100.0,
        },
    ),
    (
        ObjectiveDominanceStatus,
        lambda: {
            "objective_id": "obj-1",
            "status": "better",
            "win_count": 3,
            "tie_count": 0,
            "loss_count": 0,
            "median_paired_delta": -0.5,
        },
    ),
    (
        DominanceRelation,
        lambda: {
            "first_strategy_position": 0,
            "second_strategy_position": 1,
            "first_strategy_candidate_id": "sc-a",
            "second_strategy_candidate_id": "sc-b",
            "dominates": True,
            "per_objective_status": [
                {
                    "objective_id": "obj-1",
                    "status": "better",
                    "win_count": 3,
                    "tie_count": 0,
                    "loss_count": 0,
                    "median_paired_delta": -0.5,
                },
                {
                    "objective_id": "obj-2",
                    "status": "tied",
                    "win_count": 0,
                    "tie_count": 3,
                    "loss_count": 0,
                    "median_paired_delta": 0.0,
                },
            ],
        },
    ),
    (StrategyRobustnessProfile, lambda: _profile_payload(position=0, strategy_id="sc-a")),
    (
        DecisionReasonRecord,
        lambda: _reason_payload(code="unique_minimax_preference", values=(1.0, 0.05)),
    ),
    (DecisionFactorRecord, lambda: _factor_payload(code="feasible_candidate", strategy_id="sc-a")),
    (CampaignDecisionPolicy, lambda: _policy_payload()),
    (CampaignStrategyComparison, lambda: _comparison_payload()),
    (CampaignDecisionBrief, lambda: _brief_payload()),
)


class TestValidConstruction:
    def test_all_models_construct_validly(self) -> None:
        for model_class, builder in _MODEL_BUILDERS:
            instance = model_class.model_validate(builder())
            assert isinstance(instance, model_class)

    def test_policy_global_mode_constructs_validly(self) -> None:
        payload = _policy_payload(
            target_requirement_mode="global",
            minimum_target_achievement_probability=0.5,
            objective_target_requirements=[],
        )
        policy = CampaignDecisionPolicy.model_validate(payload)
        assert policy.target_requirement_mode == "global"
        assert policy.minimum_target_achievement_probability == 0.5
        assert policy.objective_target_requirements == ()

    def test_brief_all_four_statuses_construct_validly(self) -> None:
        for status, preferred in (
            ("preferred", "sc-a"),
            ("inconclusive", None),
            ("insufficient_evidence", None),
            ("no_feasible_strategy", None),
        ):
            brief = CampaignDecisionBrief.model_validate(_brief_payload(status=status))
            assert brief.status == status
            assert brief.preferred_strategy_id == preferred

    def test_comparison_three_strategy_fixture_constructs_validly(self) -> None:
        strategies = ("sc-a", "sc-b", "sc-c")
        deltas: dict[tuple[int, int, int], tuple[float, ...]] = {}
        for first in range(3):
            for second in range(3):
                if first == second:
                    continue
                for o in range(2):
                    value = -1.0 if first < second else 1.0
                    deltas[(first, second, o)] = (value, value, value)
        comparison = CampaignStrategyComparison.model_validate(
            _comparison_payload(strategies=strategies, deltas_by_pair=deltas)
        )
        assert len(comparison.paired_comparisons) == 3 * 2 * 2
        assert len(comparison.dominance_relations) == 3 * 2


class TestFrozenStrict:
    @pytest.mark.parametrize(
        ("model_name", "field"),
        (
            ("policy", "tie_tolerance"),
            ("comparison", "tie_tolerance"),
            ("brief", "summary"),
        ),
    )
    def test_frozen_assignment_raises(self, model_name: str, field: str) -> None:
        instance = {"policy": _policy(), "comparison": _comparison(), "brief": _brief()}[model_name]
        with pytest.raises(ValidationError):
            setattr(instance, field, 123)

    def test_every_model_is_frozen(self) -> None:
        for model_class, builder in _MODEL_BUILDERS:
            instance = model_class.model_validate(builder())
            for field in model_class.model_fields:
                with pytest.raises(ValidationError):
                    setattr(instance, field, getattr(instance, field))

    def test_every_model_rejects_extra_fields(self) -> None:
        for model_class, builder in _MODEL_BUILDERS:
            payload = builder()
            assert isinstance(payload, dict)
            payload["unexpected_field"] = "surprise"
            with pytest.raises(ValidationError):
                model_class.model_validate(payload)

    def test_tuple_fields_are_immutable(self) -> None:
        comparison = _comparison()
        with pytest.raises(ValidationError):
            comparison.ordered_strategy_candidate_ids = ("sc-b", "sc-a")
        policy = _policy()
        with pytest.raises(ValidationError):
            policy.objective_weight_snapshots = ()


class TestPolicyRules:
    def test_global_mode_requires_probability(self) -> None:
        payload = _policy_payload(
            target_requirement_mode="global", objective_target_requirements=[]
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_global_mode_forbids_requirements(self) -> None:
        payload = _policy_payload(
            target_requirement_mode="global",
            minimum_target_achievement_probability=0.5,
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_per_objective_mode_forbids_global_probability(self) -> None:
        payload = _policy_payload(minimum_target_achievement_probability=0.5)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_per_objective_mode_requires_requirements(self) -> None:
        payload = _policy_payload(objective_target_requirements=[])
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize("probability", (0.0, 0.4, 1.0))
    def test_global_probability_inclusive_boundaries_accepted(self, probability: float) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                target_requirement_mode="global",
                minimum_target_achievement_probability=probability,
                objective_target_requirements=[],
            )
        )
        assert policy.minimum_target_achievement_probability == probability

    @pytest.mark.parametrize("probability", (-0.01, 1.01))
    def test_global_probability_outside_band_rejected(self, probability: float) -> None:
        payload = _policy_payload(
            target_requirement_mode="global",
            minimum_target_achievement_probability=probability,
            objective_target_requirements=[],
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_tail_alpha_fixed_default(self) -> None:
        assert _policy().tail_alpha == 0.95

    @pytest.mark.parametrize(
        "alpha",
        (0.9, 0.99, 0.96, "0.95", True, 0, 1, Decimal("0.95")),
    )
    def test_alternative_tail_alpha_rejected(self, alpha: object) -> None:
        payload = _policy_payload(tail_alpha=alpha)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize("minimum", (3, 100, 1))
    def test_minimum_sample_count_exact_int_accepted(self, minimum: int) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(minimum_sample_count=minimum)
        )
        assert policy.minimum_sample_count == minimum

    @pytest.mark.parametrize("minimum", (3.0, True, "3", 0, -1))
    def test_minimum_sample_count_invalid_rejected(self, minimum: object) -> None:
        payload = _policy_payload(minimum_sample_count=minimum)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize("tolerance", (0.0, 0.05, 1.5))
    def test_tie_tolerance_non_negative_accepted(self, tolerance: float) -> None:
        assert _policy(tie_tolerance=tolerance).tie_tolerance == tolerance

    def test_negative_tie_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _policy(tie_tolerance=-0.01)

    def test_requirement_objective_ids_unique(self) -> None:
        payload = _policy_payload(
            objective_target_requirements=[
                _target_requirement_payload(objective_id="obj-1"),
                _target_requirement_payload(objective_id="obj-1"),
            ]
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_weight_snapshot_unique_objective_ids(self) -> None:
        payload = _policy_payload(
            objective_weight_snapshots=[
                _weight_snapshot_payload(objective_id="obj-1"),
                _weight_snapshot_payload(objective_id="obj-1", weight=2.0),
            ]
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_weight_snapshot_supplied_order_preserved_never_sorted(self) -> None:
        # The authoritative scenario/profile objective order is
        # preserved exactly: non-lexicographic orders are accepted and
        # never sorted, and weights are never normalized or
        # renormalized. External completeness/order/weight source
        # verification belongs to the future policy service.
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                objective_weight_snapshots=[
                    _weight_snapshot_payload(objective_id="obj-z", weight=0.75),
                    _weight_snapshot_payload(objective_id="obj-a", weight=0.25),
                    _weight_snapshot_payload(objective_id="obj-m", weight=1.0),
                ]
            )
        )
        assert [s.objective_id for s in policy.objective_weight_snapshots] == [
            "obj-z",
            "obj-a",
            "obj-m",
        ]
        assert [s.weight for s in policy.objective_weight_snapshots] == [0.75, 0.25, 1.0]

    def test_weight_snapshot_order_representation_preserved(self) -> None:
        policy = _policy()
        assert [s.objective_id for s in policy.objective_weight_snapshots] == ["obj-1", "obj-2"]
        assert [s.weight for s in policy.objective_weight_snapshots] == [1.0, 0.5]

    def test_negative_weight_rejected(self) -> None:
        payload = _policy_payload(
            objective_weight_snapshots=[
                _weight_snapshot_payload(objective_id="obj-1", weight=-0.1),
                _weight_snapshot_payload(objective_id="obj-2", weight=0.5),
            ]
        )
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_all_zero_weights_remain_representable(self) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                objective_weight_snapshots=[
                    _weight_snapshot_payload(objective_id="obj-1", weight=0.0),
                    _weight_snapshot_payload(objective_id="obj-2", weight=0.0),
                ]
            )
        )
        assert all(snapshot.weight == 0.0 for snapshot in policy.objective_weight_snapshots)

    def test_policy_binds_scenario_and_world_and_profile(self) -> None:
        policy = _policy()
        assert policy.scenario_id == "scenario-1"
        assert policy.scenario_content_hash == "a" * 64
        assert policy.world_version_id == "world-1"
        assert policy.world_content_hash == "b" * 64
        assert policy.evaluation_profile_id == "profile-1"
        assert policy.evaluation_profile_content_hash == "c" * 64

    @pytest.mark.parametrize(
        "field",
        (
            "scenario_content_hash",
            "world_content_hash",
            "evaluation_profile_content_hash",
            "content_hash",
        ),
    )
    def test_policy_malformed_hashes_rejected(self, field: str) -> None:
        for malformed in ("A" * 64, "ab" * 32 + "Z", "a" * 63, "ab" * 32 + "12"):
            payload = _policy_payload(**{field: malformed})
            with pytest.raises(ValidationError):
                CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize(
        "field",
        ("campaign_id", "scenario_id", "world_version_id", "evaluation_profile_id"),
    )
    def test_policy_empty_identifier_fields_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _policy(**{field: ""})

    @pytest.mark.parametrize(
        ("builder", "field"),
        (
            (_comparison, "campaign_id"),
            (_comparison, "policy_id"),
            (_brief, "campaign_id"),
            (_brief, "comparison_id"),
        ),
    )
    def test_comparison_and_brief_empty_identifier_fields_rejected(
        self, builder: Callable[..., BaseModel], field: str
    ) -> None:
        with pytest.raises(ValidationError):
            builder(**{field: ""})

    @pytest.mark.parametrize("metadata", ({"flag": float("nan")}, {"nested": {"v": float("inf")}}))
    def test_policy_metadata_non_finite_rejected(self, metadata: dict[str, object]) -> None:
        payload = _policy_payload(metadata=metadata)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_policy_metadata_finite_accepted(self) -> None:
        policy = _policy(metadata={"nested": {"values": [1, 2.5, "ok"]}, "flag": True})
        assert policy.metadata["flag"] is True


class TestExactNumericInputs:
    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("weight", True),
            ("minimum_target_achievement_probability", True),
            ("tie_tolerance", False),
            ("minimum_sample_count", True),
        ),
    )
    def test_bool_rejected_for_policy_numerics(self, field: str, value: object) -> None:
        payload = _policy_payload(**{field: value})
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize("value", ("0.05", Decimal("0.05"), None, [0.05]))
    def test_string_decimal_none_container_rejected_for_tie_tolerance(self, value: object) -> None:
        payload = _policy_payload(tie_tolerance=value)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    @pytest.mark.parametrize(
        "value", (float("nan"), float("inf"), float("-inf"), 10**400, -(10**400))
    )
    def test_non_finite_and_huge_numerics_rejected(self, value: object) -> None:
        payload = _policy_payload(tie_tolerance=value)
        with pytest.raises(ValidationError):
            CampaignDecisionPolicy.model_validate(payload)

    def test_exact_int_accepted_for_float_field(self) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                objective_weight_snapshots=[
                    _weight_snapshot_payload(objective_id="obj-1", weight=1),
                    _weight_snapshot_payload(objective_id="obj-2", weight=0),
                ]
            )
        )
        assert policy.objective_weight_snapshots[0].weight == 1.0
        assert policy.objective_weight_snapshots[1].weight == 0.0

    def test_paired_deltas_reject_bool_and_decimal_and_non_finite(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        for bad in (True, Decimal("0.5"), float("nan"), float("inf"), "0.5", 10**400):
            payload = dict(base)
            payload["ordered_paired_deltas"] = [-1.0, bad, -0.1]
            with pytest.raises(ValidationError):
                ObjectivePairedComparison.model_validate(payload)

    def test_paired_deltas_empty_rejected(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["ordered_paired_deltas"] = []
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)

    def test_positions_and_counts_require_exact_int(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        for field in (
            "sequence_position",
            "first_strategy_position",
            "second_strategy_position",
            "objective_position",
            "win_count",
            "tie_count",
            "loss_count",
        ):
            payload = dict(base)
            payload[field] = 1.0
            with pytest.raises(ValidationError):
                ObjectivePairedComparison.model_validate(payload)

    def test_dominance_relation_positions_require_exact_int(self) -> None:
        # The previously uncovered exact-int positions of the
        # dominance relation: exact built-in int only; bool, float,
        # string, Decimal, None, and containers rejected; non-negative
        # enforced.
        base: dict[str, Any] = {
            "first_strategy_position": 0,
            "second_strategy_position": 1,
            "first_strategy_candidate_id": "sc-a",
            "second_strategy_candidate_id": "sc-b",
            "dominates": True,
            "per_objective_status": [
                {
                    "objective_id": "obj-1",
                    "status": "better",
                    "win_count": 3,
                    "tie_count": 0,
                    "loss_count": 0,
                    "median_paired_delta": -0.5,
                }
            ],
        }
        for field in ("first_strategy_position", "second_strategy_position"):
            for bad in (True, 1.0, "1", Decimal("1"), None, [1]):
                payload = dict(base)
                payload[field] = bad
                with pytest.raises(ValidationError):
                    DominanceRelation.model_validate(payload)
        with pytest.raises(ValidationError):
            DominanceRelation.model_validate({**base, "first_strategy_position": -1})
        with pytest.raises(ValidationError):
            DominanceRelation.model_validate({**base, "second_strategy_position": -1})

    def test_probability_evidence_bounds(self) -> None:
        for probability in (0.0, 1.0):
            ObjectiveProbabilityEvidence.model_validate(
                {"objective_id": "obj-1", "empirical_target_achievement_probability": probability}
            )
        for probability in (-0.01, 1.01, float("nan")):
            with pytest.raises(ValidationError):
                ObjectiveProbabilityEvidence.model_validate(
                    {
                        "objective_id": "obj-1",
                        "empirical_target_achievement_probability": probability,
                    }
                )

    def test_downside_evidence_both_or_neither(self) -> None:
        ObjectiveDownsideEvidence.model_validate(
            {"objective_id": "obj-1", "adverse_tail_statistic": 1.0}
        )
        with pytest.raises(ValidationError):
            ObjectiveDownsideEvidence.model_validate(
                {
                    "objective_id": "obj-1",
                    "worst_normalized_target_violation": 0.1,
                    "target_violation_cvar": None,
                    "adverse_tail_statistic": 1.0,
                }
            )
        with pytest.raises(ValidationError):
            ObjectiveDownsideEvidence.model_validate(
                {
                    "objective_id": "obj-1",
                    "worst_normalized_target_violation": None,
                    "target_violation_cvar": 0.1,
                    "adverse_tail_statistic": 1.0,
                }
            )


class TestPairedComparisonRules:
    def test_counts_recomputed_exactly(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["win_count"] = 2
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)

    def test_rates_must_equal_count_over_k(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["win_rate"] = 0.99
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)

    def test_worst_best_equal_recorded_extrema(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["worst_paired_delta"] = -0.2
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["best_paired_delta"] = -1.1
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)

    def test_quantiles_within_extrema_one_step(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["p95_paired_delta"] = 0.05  # two steps above the worst (-0.1)
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)

    def test_tolerance_boundary_classification(self) -> None:
        # Exactly at -tol and +tol the deltas are ties; one ULP past is a win/loss.
        record = ObjectivePairedComparison.model_validate(
            _paired_payload(
                sequence_position=0,
                first=0,
                second=1,
                first_id="sc-a",
                second_id="sc-b",
                objective_position=0,
                objective_id="obj-1",
                tolerance=0.05,
                deltas=(-0.05, 0.05, 0.0),
            )
        )
        assert (record.win_count, record.tie_count, record.loss_count) == (0, 3, 0)
        record = ObjectivePairedComparison.model_validate(
            _paired_payload(
                sequence_position=0,
                first=0,
                second=1,
                first_id="sc-a",
                second_id="sc-b",
                objective_position=0,
                objective_id="obj-1",
                tolerance=0.05,
                deltas=(-0.05000000000000001, 0.05000000000000001, 0.0),
            )
        )
        assert (record.win_count, record.tie_count, record.loss_count) == (1, 1, 1)

    def test_first_and_second_positions_must_differ(self) -> None:
        base = _paired_payload(
            sequence_position=0,
            first=0,
            second=1,
            first_id="sc-a",
            second_id="sc-b",
            objective_position=0,
            objective_id="obj-1",
            deltas=(-1.0, -0.5, -0.1),
        )
        base["second_strategy_position"] = 0
        with pytest.raises(ValidationError):
            ObjectivePairedComparison.model_validate(base)


class TestComparisonStructuralRules:
    def test_exact_cardinality_missing_record_rejected(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        payload["paired_comparisons"] = comparisons[:-1]
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_exact_cardinality_additional_record_rejected(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons.append(comparisons[0])
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_duplicate_ordered_pair_rejected(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        duplicate = dict(comparisons[1])
        duplicate["sequence_position"] = 0
        comparisons[0] = duplicate
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_reordered_records_rejected(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[0], comparisons[1] = comparisons[1], comparisons[0]
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_wrong_sequence_position_rejected(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[1]["sequence_position"] = 0
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_no_self_pairs(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[0]["second_strategy_position"] = 0
        comparisons[0]["second_strategy_candidate_id"] = "sc-a"
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_identity_position_agreement(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[0]["first_strategy_candidate_id"] = "sc-b"
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_objective_identity_position_agreement(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[0]["objective_id"] = "obj-2"
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_ordering_formula_positions_match_standard_fixture(self) -> None:
        comparison = _comparison()
        for record in comparison.paired_comparisons:
            expected = (
                _pair_index(record.first_strategy_position, record.second_strategy_position, 2) * 2
                + record.objective_position
            )
            assert record.sequence_position == expected

    def test_delta_count_equals_seed_count(self) -> None:
        payload = _comparison_payload(seeds=("seed-0", "seed-1"))
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_tie_tolerance_snapshot_equality(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[0]["tie_tolerance"] = 0.1
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_duplicate_strategy_ids_rejected(self) -> None:
        payload = _comparison_payload(strategies=("sc-a", "sc-a"))
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_single_strategy_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _comparison(strategies=("sc-a",))


class TestReversePairInvariants:
    def test_standard_fixture_reverse_relationships_hold(self) -> None:
        comparison = _comparison()
        by_key = {
            (
                record.first_strategy_position,
                record.second_strategy_position,
                record.objective_position,
            ): record
            for record in comparison.paired_comparisons
        }
        for (first, second, o), record in by_key.items():
            reverse = by_key[(second, first, o)]
            assert reverse.ordered_paired_deltas == tuple(-d for d in record.ordered_paired_deltas)
            assert reverse.win_count == record.loss_count
            assert reverse.loss_count == record.win_count
            assert reverse.tie_count == record.tie_count
            assert reverse.median_paired_delta == -record.median_paired_delta
            assert reverse.p05_paired_delta == -record.p95_paired_delta
            assert reverse.p95_paired_delta == -record.p05_paired_delta
            assert reverse.worst_paired_delta == -record.best_paired_delta
            assert reverse.best_paired_delta == -record.worst_paired_delta

    def test_reverse_delta_negation_enforced(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[2]["ordered_paired_deltas"] = [1.0, 0.5, 0.2]
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_reverse_quantile_mirrors_enforced(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[2]["p05_paired_delta"] = 0.2
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_reverse_median_mirror_enforced(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[2]["median_paired_delta"] = 0.4
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_reverse_worst_best_mirrors_enforced(self) -> None:
        payload = _comparison_payload()
        comparisons = list(payload["paired_comparisons"])
        comparisons[2]["worst_paired_delta"] = 0.9
        payload["paired_comparisons"] = comparisons
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)


class TestDominanceRules:
    def test_relation_cardinality_missing_rejected(self) -> None:
        payload = _comparison_payload()
        relations = list(payload["dominance_relations"])
        payload["dominance_relations"] = relations[:-1]
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_relation_cardinality_additional_rejected(self) -> None:
        payload = _comparison_payload()
        relations = list(payload["dominance_relations"])
        relations.append(relations[0])
        payload["dominance_relations"] = relations
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_status_counts_must_match_forward_comparison(self) -> None:
        payload = _comparison_payload()
        relations = list(payload["dominance_relations"])
        statuses = list(relations[0]["per_objective_status"])
        statuses[0] = dict(statuses[0])
        statuses[0]["win_count"] = 2
        relations[0] = dict(relations[0])
        relations[0]["per_objective_status"] = statuses
        payload["dominance_relations"] = relations
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_status_median_must_match_forward_comparison(self) -> None:
        payload = _comparison_payload()
        relations = list(payload["dominance_relations"])
        statuses = list(relations[0]["per_objective_status"])
        statuses[0] = dict(statuses[0])
        statuses[0]["median_paired_delta"] = -0.4
        relations[0] = dict(relations[0])
        relations[0]["per_objective_status"] = statuses
        payload["dominance_relations"] = relations
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_worse_status_requires_loss(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveDominanceStatus.model_validate(
                {
                    "objective_id": "obj-1",
                    "status": "worse",
                    "win_count": 3,
                    "tie_count": 0,
                    "loss_count": 0,
                    "median_paired_delta": -0.5,
                }
            )

    def test_better_status_requires_no_loss_and_a_win(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveDominanceStatus.model_validate(
                {
                    "objective_id": "obj-1",
                    "status": "better",
                    "win_count": 0,
                    "tie_count": 3,
                    "loss_count": 0,
                    "median_paired_delta": 0.0,
                }
            )

    def test_tied_status_requires_all_ties(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveDominanceStatus.model_validate(
                {
                    "objective_id": "obj-1",
                    "status": "tied",
                    "win_count": 1,
                    "tie_count": 2,
                    "loss_count": 0,
                    "median_paired_delta": 0.0,
                }
            )

    def test_dominates_flag_derivation(self) -> None:
        base = {
            "first_strategy_position": 0,
            "second_strategy_position": 1,
            "first_strategy_candidate_id": "sc-a",
            "second_strategy_candidate_id": "sc-b",
            "per_objective_status": [
                {
                    "objective_id": "obj-1",
                    "status": "better",
                    "win_count": 3,
                    "tie_count": 0,
                    "loss_count": 0,
                    "median_paired_delta": -0.5,
                },
                {
                    "objective_id": "obj-2",
                    "status": "tied",
                    "win_count": 0,
                    "tie_count": 3,
                    "loss_count": 0,
                    "median_paired_delta": 0.0,
                },
            ],
        }
        with pytest.raises(ValidationError):
            DominanceRelation.model_validate({**base, "dominates": False})
        DominanceRelation.model_validate({**base, "dominates": True})

    def test_reverse_dominance_forward_all_wins_reverse_worse(self) -> None:
        # Forward all wins: forward better in every objective, reverse
        # worse; only the forward direction dominates.
        deltas: dict[tuple[int, int, int], tuple[float, ...]] = {}
        for objective_position in range(2):
            deltas[(0, 1, objective_position)] = (-2.0, -2.0, -2.0)
            deltas[(1, 0, objective_position)] = (2.0, 2.0, 2.0)
        comparison = _comparison(deltas_by_pair=deltas)
        forward = _relation_for(comparison, 0, 1)
        reverse = _relation_for(comparison, 1, 0)
        assert [status.status for status in forward.per_objective_status] == [
            "better",
            "better",
        ]
        assert forward.dominates is True
        assert [status.status for status in reverse.per_objective_status] == [
            "worse",
            "worse",
        ]
        assert reverse.dominates is False

    def test_reverse_dominance_all_ties_tied_in_both_directions(self) -> None:
        deltas = {
            (first, second, objective_position): (0.0, 0.0, 0.0)
            for first in (0, 1)
            for second in (0, 1)
            if first != second
            for objective_position in range(2)
        }
        comparison = _comparison(deltas_by_pair=deltas)
        forward = _relation_for(comparison, 0, 1)
        reverse = _relation_for(comparison, 1, 0)
        assert [status.status for status in forward.per_objective_status] == [
            "tied",
            "tied",
        ]
        assert [status.status for status in reverse.per_objective_status] == [
            "tied",
            "tied",
        ]
        assert forward.dominates is False
        assert reverse.dominates is False

    def test_reverse_dominance_mixed_worse_in_both_directions(self) -> None:
        # Crossing seed-level performance: wins and losses in both
        # directions. Each status derives independently from its own
        # counts, so both directions are "worse" and neither strategy
        # dominates.
        deltas = {}
        for objective_position in range(2):
            deltas[(0, 1, objective_position)] = (-2.0, 0.0, 2.0)
            deltas[(1, 0, objective_position)] = (2.0, 0.0, -2.0)
        comparison = _comparison(deltas_by_pair=deltas)
        forward = _relation_for(comparison, 0, 1)
        reverse = _relation_for(comparison, 1, 0)
        assert [status.status for status in forward.per_objective_status] == [
            "worse",
            "worse",
        ]
        assert [status.status for status in reverse.per_objective_status] == [
            "worse",
            "worse",
        ]
        assert forward.dominates is False
        assert reverse.dominates is False

    def test_reverse_dominance_forward_worse_zero_wins_reverse_better(self) -> None:
        deltas = {}
        for objective_position in range(2):
            deltas[(0, 1, objective_position)] = (0.0, 2.0, 2.0)
            deltas[(1, 0, objective_position)] = (0.0, -2.0, -2.0)
        comparison = _comparison(deltas_by_pair=deltas)
        forward = _relation_for(comparison, 0, 1)
        reverse = _relation_for(comparison, 1, 0)
        assert [status.status for status in forward.per_objective_status] == [
            "worse",
            "worse",
        ]
        assert forward.dominates is False
        assert [status.status for status in reverse.per_objective_status] == [
            "better",
            "better",
        ]
        assert reverse.dominates is True

    def test_no_mutual_dominance(self) -> None:
        payload = _comparison_payload()
        relations = list(payload["dominance_relations"])
        reverse = dict(relations[1])
        reverse["dominates"] = True
        payload["dominance_relations"] = relations[:1] + [reverse]
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_relation_requires_two_distinct_strategies(self) -> None:
        with pytest.raises(ValidationError):
            DominanceRelation.model_validate(
                {
                    "first_strategy_position": 0,
                    "second_strategy_position": 0,
                    "first_strategy_candidate_id": "sc-a",
                    "second_strategy_candidate_id": "sc-a",
                    "dominates": False,
                    "per_objective_status": [
                        {
                            "objective_id": "obj-1",
                            "status": "tied",
                            "win_count": 0,
                            "tie_count": 3,
                            "loss_count": 0,
                            "median_paired_delta": 0.0,
                        }
                    ],
                }
            )


class TestRobustnessRules:
    def test_failed_threshold_evidence_with_infeasible_flag_accepted(self) -> None:
        profile = StrategyRobustnessProfile.model_validate(
            _profile_payload(position=0, strategy_id="sc-a", feasible=False, observed=(0.3, 0.3))
        )
        assert profile.feasible is False
        assert all(not evidence.passed for evidence in profile.target_feasibility)

    def test_identical_failed_threshold_evidence_with_feasible_flag_accepted(self) -> None:
        # The nested evidence cannot derive ``feasible``: the policy
        # hard-gate flag lives outside the profile. Identical failed
        # threshold evidence is therefore representable with
        # ``feasible=True`` (hard gates disabled makes the test
        # vacuous); the future builder verifies ``feasible == (gates
        # off or every targeted requirement passed)``.
        profile = StrategyRobustnessProfile.model_validate(
            _profile_payload(position=0, strategy_id="sc-a", feasible=True, observed=(0.3, 0.3))
        )
        assert profile.feasible is True
        assert all(not evidence.passed for evidence in profile.target_feasibility)

    def test_empty_target_evidence_with_feasible_flag_accepted(self) -> None:
        profile = StrategyRobustnessProfile.model_validate(
            _profile_payload(position=0, strategy_id="sc-a", feasible=True, targeted=())
        )
        assert profile.feasible is True
        assert profile.target_feasibility == ()
        assert profile.target_achievement_probabilities == ()

    def test_passed_means_exactly_threshold_comparison(self) -> None:
        for observed, expected in ((0.4, True), (0.39, False), (1.0, True), (0.0, False)):
            evidence = ObjectiveFeasibilityEvidence.model_validate(
                {
                    "objective_id": "obj-1",
                    "threshold": 0.4,
                    "observed_probability": observed,
                    "passed": expected,
                }
            )
            assert evidence.passed is expected
        with pytest.raises(ValidationError):
            ObjectiveFeasibilityEvidence.model_validate(
                {
                    "objective_id": "obj-1",
                    "threshold": 0.4,
                    "observed_probability": 0.5,
                    "passed": False,
                }
            )

    def test_full_coverage_tuples_require_every_objective(self) -> None:
        # per_objective_weighted_regret and downside_evidence must
        # cover every objective exactly once in objective order.
        for tuple_key in ("per_objective_weighted_regret", "downside_evidence"):
            payload = _comparison_payload()
            profiles = list(payload["robustness_profiles"])
            profile = dict(profiles[0])
            profile[tuple_key] = profile[tuple_key][:1]
            profiles[0] = profile
            payload["robustness_profiles"] = profiles
            with pytest.raises(ValidationError):
                CampaignStrategyComparison.model_validate(payload)

    def test_target_only_tuples_may_be_partial(self) -> None:
        # target_feasibility and target_achievement_probabilities
        # cover targeted objectives only: with one targeted objective
        # both tuples carry obj-1 alone and the comparison validates.
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        for index in range(2):
            profile = dict(profiles[index])
            profile["target_feasibility"] = profile["target_feasibility"][:1]
            profile["target_achievement_probabilities"] = profile[
                "target_achievement_probabilities"
            ][:1]
            profiles[index] = profile
        payload["robustness_profiles"] = profiles
        comparison = CampaignStrategyComparison.model_validate(payload)
        for robustness_profile in comparison.robustness_profiles:
            assert [e.objective_id for e in robustness_profile.target_feasibility] == ["obj-1"]
            assert [
                e.objective_id for e in robustness_profile.target_achievement_probabilities
            ] == ["obj-1"]

    def test_one_targeted_plus_one_optimization_only_objective(self) -> None:
        # obj-1 targeted, obj-2 optimization-only: no target evidence -
        # and in particular no fabricated probability - exists for the
        # optimization-only objective, while the full-coverage tuples
        # still carry every objective.
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        for index in range(2):
            profile = dict(profiles[index])
            profile["target_feasibility"] = profile["target_feasibility"][:1]
            profile["target_achievement_probabilities"] = profile[
                "target_achievement_probabilities"
            ][:1]
            profiles[index] = profile
        payload["robustness_profiles"] = profiles
        comparison = CampaignStrategyComparison.model_validate(payload)
        for robustness_profile in comparison.robustness_profiles:
            assert [e.objective_id for e in robustness_profile.target_feasibility] == ["obj-1"]
            assert [
                e.objective_id for e in robustness_profile.target_achievement_probabilities
            ] == ["obj-1"]
            assert [e.objective_id for e in robustness_profile.per_objective_weighted_regret] == [
                "obj-1",
                "obj-2",
            ]
            assert [e.objective_id for e in robustness_profile.downside_evidence] == [
                "obj-1",
                "obj-2",
            ]

    def test_target_only_tuples_both_empty_accepted(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        for index in range(2):
            profile = dict(profiles[index])
            profile["target_feasibility"] = []
            profile["target_achievement_probabilities"] = []
            profiles[index] = profile
        payload["robustness_profiles"] = profiles
        comparison = CampaignStrategyComparison.model_validate(payload)
        assert comparison.robustness_profiles[0].target_feasibility == ()
        assert comparison.robustness_profiles[0].target_achievement_probabilities == ()

    def test_target_only_tuple_unknown_objective_rejected(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["target_feasibility"] = [
            {
                "objective_id": "obj-unknown",
                "threshold": 0.4,
                "observed_probability": 0.6,
                "passed": True,
            }
        ]
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_target_only_tuple_relative_order_rejected(self) -> None:
        # Both target-only tuples carry obj-2 before obj-1: the
        # relative order must follow ordered_objective_ids.
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        feasibility = list(profile["target_feasibility"])
        feasibility.reverse()
        probabilities = list(profile["target_achievement_probabilities"])
        probabilities.reverse()
        profile["target_feasibility"] = feasibility
        profile["target_achievement_probabilities"] = probabilities
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_target_only_tuple_ids_mismatch_rejected(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["target_achievement_probabilities"] = [
            {
                "objective_id": "obj-2",
                "empirical_target_achievement_probability": 0.5,
            }
        ]
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_per_seed_regrets_alignment(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["per_seed_total_weighted_regrets"] = [0.0, 0.5]
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_maximum_regret_exact(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["maximum_total_weighted_regret"] = 0.9
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_regret_quantiles_within_extrema(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["p95_total_weighted_regret"] = 1.5  # two steps above the maximum 1.0
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_negative_per_seed_regret_rejected(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["per_seed_total_weighted_regrets"] = [0.0, -0.5, 1.0]
        profile["median_total_weighted_regret"] = _type7_quantile((0.0, -0.5, 1.0), 50)
        profile["p95_total_weighted_regret"] = _type7_quantile((0.0, -0.5, 1.0), 95)
        profile["maximum_total_weighted_regret"] = 1.0
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_dominated_by_cross_check(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[0])
        profile["dominated_by"] = ["sc-b"]
        profiles[0] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_dominates_cross_check(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profile = dict(profiles[1])
        profile["dominates"] = ["sc-a"]
        profiles[1] = profile
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)

    def test_profile_tuple_order_enforced(self) -> None:
        payload = _comparison_payload()
        profiles = list(payload["robustness_profiles"])
        profiles[0], profiles[1] = profiles[1], profiles[0]
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignStrategyComparison.model_validate(payload)


class TestBriefRules:
    def test_preferred_requires_preferred_id(self) -> None:
        payload = _brief_payload(status="preferred")
        del payload["preferred_strategy_id"]
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_non_preferred_forbids_preferred_id(self) -> None:
        payload = _brief_payload(status="inconclusive", preferred_strategy_id="sc-a")
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_preferred_id_must_be_considered(self) -> None:
        payload = _brief_payload(status="preferred", preferred_strategy_id="sc-unknown")
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_preferred_id_present_only_for_preferred(self) -> None:
        brief = _brief()
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "sc-a"
        assert brief.preferred_strategy_id in brief.considered_strategy_ids

    @pytest.mark.parametrize(
        ("status", "code"),
        (
            ("preferred", "unique_minimax_preference"),
            ("inconclusive", "regret_tie_within_tolerance"),
            ("insufficient_evidence", "insufficient_seed_samples"),
            ("no_feasible_strategy", "no_feasible_strategy"),
        ),
    )
    def test_terminal_reason_code_matches_status(self, status: str, code: str) -> None:
        brief = CampaignDecisionBrief.model_validate(_brief_payload(status=status))
        assert brief.terminal_reason.code == code

    def test_terminal_reason_code_mismatch_rejected(self) -> None:
        payload = _brief_payload(
            status="inconclusive",
            terminal_reason=_reason_payload(code="unique_minimax_preference", values=(1.0, 0.05)),
        )
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_decisive_code_in_blocking_rejected(self) -> None:
        payload = _brief_payload(
            blocking_factors=(_factor_payload(code="feasible_candidate", strategy_id="sc-a"),)
        )
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_blocking_code_in_decisive_rejected(self) -> None:
        payload = _brief_payload(
            decisive_factors=(
                _factor_payload(code="dominated_strategy", strategy_id="sc-b", related=("sc-a",)),
            )
        )
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_decisive_stage_order_enforced(self) -> None:
        decisive = list(_default_decisive_factors())
        decisive[0], decisive[-1] = decisive[-1], decisive[0]
        payload = _brief_payload(decisive_factors=tuple(decisive))
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_uncertainty_provenance_both_or_neither(self) -> None:
        payload = _brief_payload(uncertainty_model_id="um-1", uncertainty_model_content_hash=None)
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)
        payload = _brief_payload(
            uncertainty_model_id="um-1", uncertainty_model_content_hash="ab" * 32
        )
        brief = CampaignDecisionBrief.model_validate(payload)
        assert brief.uncertainty_model_id == "um-1"

    def test_considered_strategies_unique(self) -> None:
        payload = _brief_payload(considered_strategy_ids=["sc-a", "sc-a"])
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_profile_count_matches_considered(self) -> None:
        payload = _brief_payload(
            robustness_profiles=(_profile_payload(position=0, strategy_id="sc-a"),)
        )
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_no_feasible_strategy_requires_all_infeasible(self) -> None:
        payload = _brief_payload(status="no_feasible_strategy")
        profiles = list(payload["robustness_profiles"])
        profiles[0]["feasible"] = True
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_preferred_strategy_must_be_feasible(self) -> None:
        payload = _brief_payload(status="preferred")
        profiles = list(payload["robustness_profiles"])
        profiles[0]["feasible"] = False
        payload["robustness_profiles"] = profiles
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_assumptions_unique(self) -> None:
        payload = _brief_payload(
            assumptions=[
                {
                    "identifier": "assumption-1",
                    "statement": "First.",
                    "confidence": 1.0,
                },
                {
                    "identifier": "assumption-1",
                    "statement": "Second.",
                    "confidence": 1.0,
                },
            ]
        )
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)

    def test_summary_must_be_non_empty(self) -> None:
        payload = _brief_payload(summary="")
        with pytest.raises(ValidationError):
            CampaignDecisionBrief.model_validate(payload)


class TestReasonAndFactorCatalogues:
    @pytest.mark.parametrize(
        ("code", "values", "related"),
        (
            ("unique_minimax_preference", (1.0, 0.05), ()),
            ("regret_tie_within_tolerance", (1.0, 0.05), ("sc-a", "sc-b")),
            ("insufficient_seed_samples", (100, 3), ()),
            ("no_feasible_strategy", (2, 0), ()),
        ),
    )
    def test_every_reason_code_constructs(
        self, code: str, values: tuple[object, ...], related: tuple[str, ...]
    ) -> None:
        DecisionReasonRecord.model_validate(
            _reason_payload(code=code, values=values, related=related)
        )

    @pytest.mark.parametrize(
        ("code", "values", "related"),
        (
            ("unique_minimax_preference", (1.0,), ()),
            ("unique_minimax_preference", (1.0, 0.05, 0.1), ()),
            ("unique_minimax_preference", (1.0, -0.05), ()),
            ("regret_tie_within_tolerance", (1.0, 0.05), ()),
            ("insufficient_seed_samples", (100.0, 3), ()),
            ("insufficient_seed_samples", (100, -3), ()),
            ("no_feasible_strategy", (2, 0), ("sc-a",)),
        ),
    )
    def test_reason_code_value_shape_enforced(
        self, code: str, values: tuple[object, ...], related: tuple[str, ...]
    ) -> None:
        with pytest.raises(ValidationError):
            DecisionReasonRecord.model_validate(
                _reason_payload(code=code, values=values, related=related)
            )

    @pytest.mark.parametrize(
        ("code", "strategy_id", "objective_id", "values", "related"),
        (
            ("feasible_candidate", "sc-a", None, (), ()),
            ("pareto_non_dominated", "sc-a", None, (), ()),
            ("target_feasibility_passed", "sc-a", "obj-1", (0.4, 0.6), ()),
            ("unique_minimax_regret", "sc-a", None, (1.0, 1.5, 0.5), ("sc-b",)),
            ("objective_target_failed", "sc-a", "obj-1", (0.4, 0.3), ()),
            ("dominated_strategy", "sc-b", None, (), ("sc-a",)),
            ("minimax_regret_tie", None, None, (1.0, 0.05), ("sc-a", "sc-b")),
            ("no_feasible_strategy", None, None, (2, 0), ()),
            ("insufficient_seed_count", None, None, (100, 3), ()),
        ),
    )
    def test_every_factor_code_constructs(
        self,
        code: str,
        strategy_id: str | None,
        objective_id: str | None,
        values: tuple[object, ...],
        related: tuple[str, ...],
    ) -> None:
        DecisionFactorRecord.model_validate(
            _factor_payload(
                code=code,
                strategy_id=strategy_id,
                objective_id=objective_id,
                values=values,
                related=related,
            )
        )

    @pytest.mark.parametrize(
        ("code", "strategy_id", "objective_id", "values", "related"),
        (
            ("feasible_candidate", None, None, (), ()),
            ("feasible_candidate", "sc-a", None, (1.0,), ()),
            ("target_feasibility_passed", "sc-a", None, (0.4, 0.6), ()),
            ("target_feasibility_passed", "sc-a", "obj-1", (0.6, 0.4), ()),
            ("objective_target_failed", "sc-a", "obj-1", (0.4, 0.6), ()),
            ("unique_minimax_regret", "sc-a", None, (1.0, 1.5, 0.6), ("sc-b",)),
            ("unique_minimax_regret", "sc-a", None, (1.0, 1.5, 0.5), ()),
            ("dominated_strategy", "sc-b", None, (), ()),
            ("dominated_strategy", "sc-b", None, (), ("sc-b",)),
            ("minimax_regret_tie", "sc-a", None, (1.0, 0.05), ("sc-b",)),
            ("no_feasible_strategy", None, None, (2.0, 0), ()),
            ("insufficient_seed_count", None, None, (100, 3), ("sc-a",)),
        ),
    )
    def test_factor_code_value_shape_enforced(
        self,
        code: str,
        strategy_id: str | None,
        objective_id: str | None,
        values: tuple[object, ...],
        related: tuple[str, ...],
    ) -> None:
        with pytest.raises(ValidationError):
            DecisionFactorRecord.model_validate(
                _factor_payload(
                    code=code,
                    strategy_id=strategy_id,
                    objective_id=objective_id,
                    values=values,
                    related=related,
                )
            )


class TestModuleBoundaries:
    def test_imports_only_stdlib_pydantic_and_shared(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_paths.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_paths.add(node.module)
        assert module_paths == {
            "__future__",
            "math",
            "typing",
            "pydantic",
            "kalhas.contracts.v1.shared",
        }, sorted(module_paths)

    def test_no_application_layer_imports(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("kalhas.application"), node.module
                assert not node.module.startswith("kalhas.api"), node.module

    def test_no_wall_clock_randomness_or_store_surface(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"now", "utcnow", "today", "time", "random", "uuid4"}, name
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names

    def test_no_executable_or_callback_typed_surface(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Lambda), "lambda expression in the module"
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"exec", "eval", "compile", "__import__"}, name
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "Callable" not in names
        assert "callback" not in names

    def test_no_forward_phase_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_public_contracts_and_schemas_preserve_accepted_50_prefix(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 50
        assert names[47] == "CampaignDecisionPolicy"
        assert names[48] == "CampaignStrategyComparison"
        assert names[49] == "CampaignDecisionBrief"
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        file_names = {path.name for path in schema_files}
        assert "CampaignDecisionPolicy.schema.json" in file_names
        assert "CampaignStrategyComparison.schema.json" in file_names
        assert "CampaignDecisionBrief.schema.json" in file_names


class TestDeterminism:
    def test_repeated_construction_identical(self) -> None:
        first = _comparison()
        second = _comparison()
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert _policy().model_dump(mode="json") == _policy().model_dump(mode="json")
        assert _brief().model_dump(mode="json") == _brief().model_dump(mode="json")

    def test_json_round_trip_preserves_models(self) -> None:
        import json

        for instance in (_policy(), _comparison(), _brief()):
            restored = instance.__class__.model_validate(json.loads(instance.model_dump_json()))
            assert restored == instance

    def test_declared_at_and_metadata_are_deterministic_inputs(self) -> None:
        policy = _policy(declared_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC))
        assert policy.declared_at == datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
        assert policy.declared_at.tzinfo is not None
