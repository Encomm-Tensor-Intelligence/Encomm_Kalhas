"""Tests for the pure campaign decision identity and content-hash primitives.

Tests for ``kalhas/application/campaign_decision_identity.py``: the six
deterministic primitives for the three campaign decision artifacts
(policy identifier/content hash, comparison identifier/content hash,
brief identifier/content hash). Proves:

- the exact public surface (keyword-only identifier parameters, exact
  signatures, exact ``__all__``);
- hard-coded golden identifiers and golden content hashes for the fixed
  standard fixtures, each independently recomputed via canonical JSON;
- repeated-call equality, caller mapping-order independence, and
  per-input sensitivity of every identity input of all three
  identifiers;
- identifier independence from content fields: content hash,
  timestamps, evidence values, metadata, float text, and the tenant for
  the derived comparison/brief identifiers (the tenant is part of the
  stored policy identifier only);
- policy scenario identity affects the policy identifier; objective
  weights and the fixed tail alpha are content-covered;
- full content-hash coverage: recorded ``content_hash`` ignored, every
  other top-level field of all three artifacts independently changing
  the digest, every nested record change (weights, requirements,
  deltas, statuses, regrets, reasons, factors, assumptions, metadata)
  changing the digest, optional uncertainty presence changing the
  brief digest, and validator-bypassed ``model_copy`` tampering
  detected;
- zero input mutation, JSON round-trip equality, the narrow import
  boundary, no wall clock/randomness/store/executable surfaces, no
  phase literals, and the decision contracts registered at indexes
  47-49 with exactly 50 registry/schema entries.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.application.campaign_decision_identity import (
    campaign_decision_brief_content_hash,
    campaign_decision_brief_identifier,
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
    campaign_strategy_comparison_content_hash,
    campaign_strategy_comparison_identifier,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_decision_identity.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

_ALGORITHM = "feasibility-pareto-minimax-regret-v1"
_POLICY_PREFIX = "campaign-decision-policy-"
_COMPARISON_PREFIX = "campaign-strategy-comparison-"
_BRIEF_PREFIX = "campaign-decision-brief-"
_ID_DIGEST_LENGTH = 16

#: Hard-coded golden identifiers for the fixed identity inputs below.
GOLDEN_POLICY_IDENTIFIER = "campaign-decision-policy-61d7e649661625d6"
GOLDEN_COMPARISON_IDENTIFIER = "campaign-strategy-comparison-2d852a3ac98e1bee"
GOLDEN_BRIEF_IDENTIFIER = "campaign-decision-brief-90a4e0837e75981f"

#: Hard-coded golden canonical content hashes of the standard artifacts.
GOLDEN_POLICY_HASH = "9ce2fbbc18483511d06385c74ef316bb9422241228edd1de6c127e81aca47846"
GOLDEN_COMPARISON_HASH = "3b146f9241cd67816ceb3706b6bf2d03b34221766f58e0d0d2031955f8344220"
GOLDEN_BRIEF_HASH = "5222a51e9b1bde5d21db5ad37d542d9f82bb978813e54154cfee6c8c92465320"

_POLICY_IDENTITY_INPUTS = {
    "tenant_id": "tenant-1",
    "campaign_id": "campaign-1",
    "scenario_id": "scenario-1",
    "world_version_id": "world-1",
    "evaluation_profile_id": "profile-1",
    "schema_version": "1.0.0",
}

_COMPARISON_IDENTITY_INPUTS = {
    "campaign_id": "campaign-1",
    "world_version_id": "world-1",
    "evaluation_profile_id": "profile-1",
    "policy_id": "policy-1",
    "source_outcome_matrix_id": "matrix-1",
}

_BRIEF_IDENTITY_INPUTS = {
    "campaign_id": "campaign-1",
    "world_version_id": "world-1",
    "policy_id": "policy-1",
    "comparison_id": "comparison-1",
}

STRATEGIES = ("sc-a", "sc-b")
OBJECTIVES = ("obj-1", "obj-2")
SEEDS = ("seed-0", "seed-1", "seed-2")
TOLERANCE = 0.05


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
) -> dict[str, Any]:
    return {
        "strategy_position": position,
        "strategy_candidate_id": strategy_id,
        "feasible": feasible,
        "target_feasibility": [
            {
                "objective_id": "obj-1",
                "threshold": 0.4,
                "observed_probability": 0.6,
                "passed": True,
            },
            {
                "objective_id": "obj-2",
                "threshold": 0.4,
                "observed_probability": 0.5,
                "passed": True,
            },
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
            {"objective_id": "obj-1", "empirical_target_achievement_probability": 0.6},
            {"objective_id": "obj-2", "empirical_target_achievement_probability": 0.5},
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


def _default_deltas() -> dict[tuple[int, int, int], tuple[float, ...]]:
    return {
        (0, 1, 0): (-1.0, -0.5, -0.1),
        (0, 1, 1): (0.0, 0.0, 0.0),
        (1, 0, 0): (1.0, 0.5, 0.1),
        (1, 0, 1): (0.0, 0.0, 0.0),
    }


def _comparison_payload(**overrides: object) -> dict[str, Any]:
    strategy_count = len(STRATEGIES)
    objective_count = len(OBJECTIVES)
    deltas = _default_deltas()
    comparisons: list[dict[str, Any]] = []
    for first in range(strategy_count):
        for second in range(strategy_count):
            if first == second:
                continue
            for o in range(objective_count):
                pair_index = first * (strategy_count - 1) + (
                    second if second < first else second - 1
                )
                comparisons.append(
                    _paired_payload(
                        sequence_position=pair_index * objective_count + o,
                        first=first,
                        second=second,
                        first_id=STRATEGIES[first],
                        second_id=STRATEGIES[second],
                        objective_position=o,
                        objective_id=OBJECTIVES[o],
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
                    first, second, STRATEGIES[first], STRATEGIES[second], pair_comparisons
                )
            )
    profiles = [
        _profile_payload(position=0, strategy_id="sc-a", dominated_by=(), dominates=("sc-b",)),
        _profile_payload(
            position=1,
            strategy_id="sc-b",
            dominated_by=("sc-a",),
            dominates=(),
            per_seed=(1.5, 1.0, 0.5),
        ),
    ]
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
        "tie_tolerance": TOLERANCE,
        "minimum_sample_count": 3,
        "source_outcome_matrix_id": "matrix-1",
        "source_outcome_matrix_content_hash": "f" * 64,
        "ordered_strategy_candidate_ids": list(STRATEGIES),
        "ordered_scenario_seed_ids": list(SEEDS),
        "ordered_objective_ids": list(OBJECTIVES),
        "paired_comparisons": comparisons,
        "dominance_relations": relations,
        "robustness_profiles": profiles,
        "content_hash": "0" * 64,
        "derived_at": "2026-08-16T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _policy_payload(**overrides: object) -> dict[str, Any]:
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
            {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
            {"objective_id": "obj-2", "minimum_target_achievement_probability": 0.4},
        ],
        "objective_weight_snapshots": [
            {"objective_id": "obj-1", "weight": 1.0},
            {"objective_id": "obj-2", "weight": 0.5},
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


def _brief_payload(**overrides: object) -> dict[str, Any]:
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
        "status": "preferred",
        "preferred_strategy_id": "sc-a",
        "considered_strategy_ids": list(STRATEGIES),
        "summary": "Strategy sc-a is preferred under policy policy-1.",
        "terminal_reason": {"code": "unique_minimax_preference", "values": [1.0, 0.05]},
        "decisive_factors": [
            {"code": "feasible_candidate", "strategy_id": "sc-a"},
            {"code": "feasible_candidate", "strategy_id": "sc-b"},
            {
                "code": "target_feasibility_passed",
                "strategy_id": "sc-a",
                "objective_id": "obj-1",
                "values": [0.4, 0.6],
            },
            {
                "code": "target_feasibility_passed",
                "strategy_id": "sc-a",
                "objective_id": "obj-2",
                "values": [0.4, 0.5],
            },
            {
                "code": "target_feasibility_passed",
                "strategy_id": "sc-b",
                "objective_id": "obj-1",
                "values": [0.4, 0.6],
            },
            {
                "code": "target_feasibility_passed",
                "strategy_id": "sc-b",
                "objective_id": "obj-2",
                "values": [0.4, 0.5],
            },
            {"code": "pareto_non_dominated", "strategy_id": "sc-a"},
            {
                "code": "unique_minimax_regret",
                "strategy_id": "sc-a",
                "related_strategy_ids": ["sc-b"],
                "values": [1.0, 1.5, 0.5],
            },
        ],
        "blocking_factors": [
            {"code": "dominated_strategy", "strategy_id": "sc-b", "related_strategy_ids": ["sc-a"]},
        ],
        "robustness_profiles": [
            _profile_payload(position=0, strategy_id="sc-a", dominated_by=(), dominates=("sc-b",)),
            _profile_payload(
                position=1,
                strategy_id="sc-b",
                dominated_by=("sc-a",),
                dominates=(),
                per_seed=(1.5, 1.0, 0.5),
            ),
        ],
        "assumptions": [
            {
                "identifier": "assumption-1",
                "statement": "Declared fixture assumption.",
                "confidence": 1.0,
            },
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
    return CampaignStrategyComparison.model_validate(_comparison_payload(**overrides))


def _brief(**overrides: object) -> CampaignDecisionBrief:
    return CampaignDecisionBrief.model_validate(_brief_payload(**overrides))


class TestPublicSurface:
    def test_exact_all(self) -> None:
        import kalhas.application.campaign_decision_identity as module

        assert module.__all__ == [
            "campaign_decision_policy_identifier",
            "campaign_decision_policy_content_hash",
            "campaign_strategy_comparison_identifier",
            "campaign_strategy_comparison_content_hash",
            "campaign_decision_brief_identifier",
            "campaign_decision_brief_content_hash",
        ]
        for name in module.__all__:
            assert hasattr(module, name)

    def test_policy_identifier_signature_is_keyword_only_and_exact(self) -> None:
        parameters = tuple(inspect.signature(campaign_decision_policy_identifier).parameters)
        assert parameters == (
            "tenant_id",
            "campaign_id",
            "scenario_id",
            "world_version_id",
            "evaluation_profile_id",
            "schema_version",
        )
        signature = inspect.signature(campaign_decision_policy_identifier)
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        assert signature.return_annotation == "str"

    def test_comparison_identifier_signature_is_keyword_only_and_exact(self) -> None:
        parameters = tuple(inspect.signature(campaign_strategy_comparison_identifier).parameters)
        assert parameters == (
            "campaign_id",
            "world_version_id",
            "evaluation_profile_id",
            "policy_id",
            "source_outcome_matrix_id",
        )
        signature = inspect.signature(campaign_strategy_comparison_identifier)
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        assert signature.return_annotation == "str"

    def test_brief_identifier_signature_is_keyword_only_and_exact(self) -> None:
        parameters = tuple(inspect.signature(campaign_decision_brief_identifier).parameters)
        assert parameters == (
            "campaign_id",
            "world_version_id",
            "policy_id",
            "comparison_id",
        )
        signature = inspect.signature(campaign_decision_brief_identifier)
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        assert signature.return_annotation == "str"

    def test_content_hash_signatures_are_exact(self) -> None:
        assert tuple(inspect.signature(campaign_decision_policy_content_hash).parameters) == (
            "policy",
        )
        assert tuple(inspect.signature(campaign_strategy_comparison_content_hash).parameters) == (
            "comparison",
        )
        assert tuple(inspect.signature(campaign_decision_brief_content_hash).parameters) == (
            "brief",
        )


class TestIdentifierGolden:
    def test_golden_policy_identifier_hard_coded(self) -> None:
        assert campaign_decision_policy_identifier(**_POLICY_IDENTITY_INPUTS) == (
            GOLDEN_POLICY_IDENTIFIER
        )

    def test_golden_comparison_identifier_hard_coded(self) -> None:
        assert campaign_strategy_comparison_identifier(**_COMPARISON_IDENTITY_INPUTS) == (
            GOLDEN_COMPARISON_IDENTIFIER
        )

    def test_golden_brief_identifier_hard_coded(self) -> None:
        assert campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS) == (
            GOLDEN_BRIEF_IDENTIFIER
        )

    def test_exact_prefixes_and_sixteen_lowercase_hex_digest_chars(self) -> None:
        policy_identifier = campaign_decision_policy_identifier(**_POLICY_IDENTITY_INPUTS)
        comparison_identifier = campaign_strategy_comparison_identifier(
            **_COMPARISON_IDENTITY_INPUTS
        )
        brief_identifier = campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS)
        for identifier, prefix, inputs in (
            (policy_identifier, _POLICY_PREFIX, _POLICY_IDENTITY_INPUTS),
            (comparison_identifier, _COMPARISON_PREFIX, _COMPARISON_IDENTITY_INPUTS),
            (brief_identifier, _BRIEF_PREFIX, _BRIEF_IDENTITY_INPUTS),
        ):
            assert identifier.startswith(prefix)
            assert len(identifier) == len(prefix) + _ID_DIGEST_LENGTH
            digest = identifier[len(prefix) :]
            assert re.fullmatch(rf"[0-9a-f]{{{_ID_DIGEST_LENGTH}}}", digest) is not None
            assert digest == sha256_hex(canonical_json(inputs))[:_ID_DIGEST_LENGTH]

    def test_repeated_calls_return_identical_identifiers(self) -> None:
        first = campaign_decision_policy_identifier(**_POLICY_IDENTITY_INPUTS)
        second = campaign_decision_policy_identifier(**_POLICY_IDENTITY_INPUTS)
        assert first == second == GOLDEN_POLICY_IDENTIFIER
        first = campaign_strategy_comparison_identifier(**_COMPARISON_IDENTITY_INPUTS)
        second = campaign_strategy_comparison_identifier(**_COMPARISON_IDENTITY_INPUTS)
        assert first == second == GOLDEN_COMPARISON_IDENTIFIER
        first = campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS)
        second = campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS)
        assert first == second == GOLDEN_BRIEF_IDENTIFIER

    @pytest.mark.parametrize(
        ("field", "changed"),
        (
            pytest.param("tenant_id", "tenant-2", id="tenant-id"),
            pytest.param("campaign_id", "campaign-2", id="campaign-id"),
            pytest.param("scenario_id", "scenario-2", id="scenario-id"),
            pytest.param("world_version_id", "world-2", id="world-version-id"),
            pytest.param("evaluation_profile_id", "profile-2", id="evaluation-profile-id"),
            pytest.param("schema_version", "2.0.0", id="schema-version"),
        ),
    )
    def test_each_policy_identity_input_changes_the_identifier(
        self, field: str, changed: str
    ) -> None:
        inputs = dict(_POLICY_IDENTITY_INPUTS)
        inputs[field] = changed
        assert campaign_decision_policy_identifier(**inputs) != GOLDEN_POLICY_IDENTIFIER

    @pytest.mark.parametrize(
        ("field", "changed"),
        (
            pytest.param("campaign_id", "campaign-2", id="campaign-id"),
            pytest.param("world_version_id", "world-2", id="world-version-id"),
            pytest.param("evaluation_profile_id", "profile-2", id="evaluation-profile-id"),
            pytest.param("policy_id", "policy-2", id="policy-id"),
            pytest.param("source_outcome_matrix_id", "matrix-2", id="source-outcome-matrix-id"),
        ),
    )
    def test_each_comparison_identity_input_changes_the_identifier(
        self, field: str, changed: str
    ) -> None:
        inputs = dict(_COMPARISON_IDENTITY_INPUTS)
        inputs[field] = changed
        assert campaign_strategy_comparison_identifier(**inputs) != GOLDEN_COMPARISON_IDENTIFIER

    @pytest.mark.parametrize(
        ("field", "changed"),
        (
            pytest.param("campaign_id", "campaign-2", id="campaign-id"),
            pytest.param("world_version_id", "world-2", id="world-version-id"),
            pytest.param("policy_id", "policy-2", id="policy-id"),
            pytest.param("comparison_id", "comparison-2", id="comparison-id"),
        ),
    )
    def test_each_brief_identity_input_changes_the_identifier(
        self, field: str, changed: str
    ) -> None:
        inputs = dict(_BRIEF_IDENTITY_INPUTS)
        inputs[field] = changed
        assert campaign_decision_brief_identifier(**inputs) != GOLDEN_BRIEF_IDENTIFIER

    def test_equivalent_inputs_never_depend_on_caller_mapping_order(self) -> None:
        reversed_policy = {
            "schema_version": _POLICY_IDENTITY_INPUTS["schema_version"],
            "evaluation_profile_id": _POLICY_IDENTITY_INPUTS["evaluation_profile_id"],
            "world_version_id": _POLICY_IDENTITY_INPUTS["world_version_id"],
            "scenario_id": _POLICY_IDENTITY_INPUTS["scenario_id"],
            "campaign_id": _POLICY_IDENTITY_INPUTS["campaign_id"],
            "tenant_id": _POLICY_IDENTITY_INPUTS["tenant_id"],
        }
        assert set(reversed_policy) == set(_POLICY_IDENTITY_INPUTS)
        assert campaign_decision_policy_identifier(**reversed_policy) == (GOLDEN_POLICY_IDENTIFIER)
        reversed_comparison = {
            "source_outcome_matrix_id": _COMPARISON_IDENTITY_INPUTS["source_outcome_matrix_id"],
            "policy_id": _COMPARISON_IDENTITY_INPUTS["policy_id"],
            "evaluation_profile_id": _COMPARISON_IDENTITY_INPUTS["evaluation_profile_id"],
            "world_version_id": _COMPARISON_IDENTITY_INPUTS["world_version_id"],
            "campaign_id": _COMPARISON_IDENTITY_INPUTS["campaign_id"],
        }
        assert set(reversed_comparison) == set(_COMPARISON_IDENTITY_INPUTS)
        assert campaign_strategy_comparison_identifier(**reversed_comparison) == (
            GOLDEN_COMPARISON_IDENTIFIER
        )
        reversed_brief = {
            "comparison_id": _BRIEF_IDENTITY_INPUTS["comparison_id"],
            "policy_id": _BRIEF_IDENTITY_INPUTS["policy_id"],
            "world_version_id": _BRIEF_IDENTITY_INPUTS["world_version_id"],
            "campaign_id": _BRIEF_IDENTITY_INPUTS["campaign_id"],
        }
        assert set(reversed_brief) == set(_BRIEF_IDENTITY_INPUTS)
        assert campaign_decision_brief_identifier(**reversed_brief) == GOLDEN_BRIEF_IDENTIFIER

    def test_identifiers_do_not_use_artifact_content_fields(self) -> None:
        # Wildly different artifact contents with the same identity
        # inputs must yield the identical identifiers.
        decorated_policy = _policy(
            content_hash="1" * 64,
            declared_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
            metadata={"source": "other"},
            tie_tolerance=1.5,
            minimum_sample_count=500,
        )
        policy_identity = {
            "tenant_id": decorated_policy.tenant_id,
            "campaign_id": decorated_policy.campaign_id,
            "scenario_id": decorated_policy.scenario_id,
            "world_version_id": decorated_policy.world_version_id,
            "evaluation_profile_id": decorated_policy.evaluation_profile_id,
            "schema_version": decorated_policy.schema_version,
        }
        assert campaign_decision_policy_identifier(**policy_identity) == (GOLDEN_POLICY_IDENTIFIER)
        decorated_comparison = _comparison(
            content_hash="2" * 64,
            derived_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        comparison_identity = {
            "campaign_id": decorated_comparison.campaign_id,
            "world_version_id": decorated_comparison.world_version_id,
            # The comparison identifier's evaluation-profile identity
            # comes from the authoritative policy record, never from
            # the comparison artifact itself.
            "evaluation_profile_id": _COMPARISON_IDENTITY_INPUTS["evaluation_profile_id"],
            "policy_id": decorated_comparison.policy_id,
            "source_outcome_matrix_id": decorated_comparison.source_outcome_matrix_id,
        }
        assert campaign_strategy_comparison_identifier(**comparison_identity) == (
            GOLDEN_COMPARISON_IDENTIFIER
        )
        decorated_brief = _brief(
            content_hash="3" * 64,
            produced_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
            summary="Completely different deterministic summary text.",
        )
        brief_identity = {
            "campaign_id": decorated_brief.campaign_id,
            "world_version_id": decorated_brief.world_version_id,
            "policy_id": decorated_brief.policy_id,
            "comparison_id": decorated_brief.comparison_id,
        }
        assert campaign_decision_brief_identifier(**brief_identity) == GOLDEN_BRIEF_IDENTIFIER

    def test_tenant_affects_only_the_stored_policy_identifier(self) -> None:
        foreign_policy = _policy(tenant_id="tenant-9")
        assert (
            campaign_decision_policy_identifier(
                tenant_id="tenant-9",
                campaign_id=foreign_policy.campaign_id,
                scenario_id=foreign_policy.scenario_id,
                world_version_id=foreign_policy.world_version_id,
                evaluation_profile_id=foreign_policy.evaluation_profile_id,
                schema_version=foreign_policy.schema_version,
            )
            != GOLDEN_POLICY_IDENTIFIER
        )
        # The derived comparison/brief identifiers have no tenant input
        # and are insensitive to the stored policy's tenant.
        assert (
            campaign_strategy_comparison_identifier(**_COMPARISON_IDENTITY_INPUTS)
            == GOLDEN_COMPARISON_IDENTIFIER
        )
        assert campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS) == (
            GOLDEN_BRIEF_IDENTIFIER
        )


class TestContentHashGolden:
    def test_golden_policy_content_hash_hard_coded(self) -> None:
        assert campaign_decision_policy_content_hash(_policy()) == GOLDEN_POLICY_HASH

    def test_golden_comparison_content_hash_hard_coded(self) -> None:
        assert campaign_strategy_comparison_content_hash(_comparison()) == (GOLDEN_COMPARISON_HASH)

    def test_golden_brief_content_hash_hard_coded(self) -> None:
        assert campaign_decision_brief_content_hash(_brief()) == GOLDEN_BRIEF_HASH

    def test_recomputed_hashes_are_not_the_recorded_content_hashes(self) -> None:
        assert _policy().content_hash == "0" * 64
        assert campaign_decision_policy_content_hash(_policy()) != "0" * 64
        assert _comparison().content_hash == "0" * 64
        assert campaign_strategy_comparison_content_hash(_comparison()) != "0" * 64
        assert _brief().content_hash == "0" * 64
        assert campaign_decision_brief_content_hash(_brief()) != "0" * 64

    def test_repeated_calls_return_identical_hashes(self) -> None:
        policy = _policy()
        comparison = _comparison()
        brief = _brief()
        first = campaign_decision_policy_content_hash(policy)
        second = campaign_decision_policy_content_hash(policy)
        assert first == second == GOLDEN_POLICY_HASH
        first = campaign_strategy_comparison_content_hash(comparison)
        second = campaign_strategy_comparison_content_hash(comparison)
        assert first == second == GOLDEN_COMPARISON_HASH
        first = campaign_decision_brief_content_hash(brief)
        second = campaign_decision_brief_content_hash(brief)
        assert first == second == GOLDEN_BRIEF_HASH

    def test_json_round_tripped_equivalent_artifacts_have_same_hashes(self) -> None:
        for instance in (_policy(), _comparison(), _brief()):
            restored = instance.__class__.model_validate(json.loads(instance.model_dump_json()))
            assert restored == instance
        assert (
            campaign_decision_policy_content_hash(
                CampaignDecisionPolicy.model_validate(json.loads(_policy().model_dump_json()))
            )
            == GOLDEN_POLICY_HASH
        )
        assert (
            campaign_strategy_comparison_content_hash(
                CampaignStrategyComparison.model_validate(
                    json.loads(_comparison().model_dump_json())
                )
            )
            == GOLDEN_COMPARISON_HASH
        )
        assert (
            campaign_decision_brief_content_hash(
                CampaignDecisionBrief.model_validate(json.loads(_brief().model_dump_json()))
            )
            == GOLDEN_BRIEF_HASH
        )

    def test_changing_only_recorded_content_hash_leaves_recomputation_unchanged(self) -> None:
        policy = _policy()
        comparison = _comparison()
        brief = _brief()
        for recorded in ("1" * 64, "a" * 64, "0" * 63 + "1"):
            assert (
                campaign_decision_policy_content_hash(
                    policy.model_copy(update={"content_hash": recorded})
                )
                == GOLDEN_POLICY_HASH
            )
            assert (
                campaign_strategy_comparison_content_hash(
                    comparison.model_copy(update={"content_hash": recorded})
                )
                == GOLDEN_COMPARISON_HASH
            )
            assert (
                campaign_decision_brief_content_hash(
                    brief.model_copy(update={"content_hash": recorded})
                )
                == GOLDEN_BRIEF_HASH
            )

    def test_every_policy_top_level_field_changes_the_hash(self) -> None:
        policy = _policy()
        changed: list[tuple[str, object]] = [
            ("identifier", "policy-2"),
            ("tenant_id", "tenant-2"),
            ("schema_version", "2.0.0"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "a" * 63 + "b"),
            ("world_version_id", "world-2"),
            ("world_content_hash", "b" * 63 + "c"),
            ("evaluation_profile_id", "profile-2"),
            ("evaluation_profile_content_hash", "c" * 63 + "d"),
            ("algorithm_identifier", "other-algorithm-v1"),
            ("target_requirement_mode", "global"),
            ("minimum_target_achievement_probability", 0.5),
            (
                "objective_target_requirements",
                (
                    policy.objective_target_requirements[0].model_copy(
                        update={"minimum_target_achievement_probability": 0.6}
                    ),
                    policy.objective_target_requirements[1],
                ),
            ),
            (
                "objective_weight_snapshots",
                (
                    policy.objective_weight_snapshots[0].model_copy(update={"weight": 2.0}),
                    policy.objective_weight_snapshots[1],
                ),
            ),
            ("minimum_sample_count", 100),
            ("tie_tolerance", 0.1),
            ("all_targeted_objectives_are_hard_gates", False),
            ("tail_alpha", 0.9),
            ("declared_at", datetime(2026, 8, 17, 12, 0, tzinfo=UTC)),
            ("metadata", {"source": "other"}),
        ]
        for field, value in changed:
            modified = policy.model_copy(update={field: value})
            assert campaign_decision_policy_content_hash(modified) != GOLDEN_POLICY_HASH, (
                f"policy field {field} did not change the hash"
            )

    def test_every_comparison_top_level_field_changes_the_hash(self) -> None:
        comparison = _comparison()
        changed: list[tuple[str, object]] = [
            ("identifier", "comparison-2"),
            ("tenant_id", "tenant-2"),
            ("schema_version", "2.0.0"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "a" * 63 + "b"),
            ("world_version_id", "world-2"),
            ("world_content_hash", "b" * 63 + "c"),
            ("runtime_version", "9.9.9"),
            ("comparison_mode", "shared_conditions"),
            ("algorithm_identifier", "other-algorithm-v1"),
            ("policy_id", "policy-2"),
            ("policy_content_hash", "ab" * 31 + "cd"),
            ("tie_tolerance", 0.1),
            ("minimum_sample_count", 100),
            ("source_outcome_matrix_id", "matrix-2"),
            ("source_outcome_matrix_content_hash", "f" * 63 + "e"),
            ("ordered_strategy_candidate_ids", ("sc-a", "sc-b", "sc-c")),
            ("ordered_scenario_seed_ids", ("seed-0", "seed-1", "seed-2", "seed-3")),
            ("ordered_objective_ids", ("obj-1", "obj-2", "obj-3")),
            (
                "paired_comparisons",
                (
                    comparison.paired_comparisons[0].model_copy(
                        update={"worst_paired_delta": -0.05}
                    ),
                    *comparison.paired_comparisons[1:],
                ),
            ),
            (
                "dominance_relations",
                (
                    comparison.dominance_relations[0].model_copy(update={"dominates": False}),
                    comparison.dominance_relations[1],
                ),
            ),
            (
                "robustness_profiles",
                (
                    comparison.robustness_profiles[0].model_copy(
                        update={"maximum_total_weighted_regret": 0.9}
                    ),
                    comparison.robustness_profiles[1],
                ),
            ),
            ("derived_at", datetime(2026, 8, 17, 12, 0, tzinfo=UTC)),
        ]
        for field, value in changed:
            modified = comparison.model_copy(update={field: value})
            assert campaign_strategy_comparison_content_hash(modified) != (
                GOLDEN_COMPARISON_HASH
            ), f"comparison field {field} did not change the hash"

    def test_every_brief_top_level_field_changes_the_hash(self) -> None:
        brief = _brief()
        changed: list[tuple[str, object]] = [
            ("identifier", "brief-2"),
            ("tenant_id", "tenant-2"),
            ("schema_version", "2.0.0"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("world_version_id", "world-2"),
            ("world_content_hash", "b" * 63 + "c"),
            ("runtime_version", "9.9.9"),
            ("comparison_mode", "shared_conditions"),
            ("algorithm_identifier", "other-algorithm-v1"),
            ("policy_id", "policy-2"),
            ("policy_content_hash", "ab" * 31 + "cd"),
            ("comparison_id", "comparison-2"),
            ("comparison_content_hash", "cd" * 31 + "ef"),
            ("status", "inconclusive"),
            ("preferred_strategy_id", None),
            ("considered_strategy_ids", ("sc-a", "sc-b", "sc-c")),
            ("summary", "Different deterministic summary text."),
            (
                "terminal_reason",
                brief.terminal_reason.model_copy(update={"values": (2.0, 0.05)}),
            ),
            (
                "decisive_factors",
                (
                    brief.decisive_factors[0].model_copy(update={"strategy_id": "sc-b"}),
                    *brief.decisive_factors[1:],
                ),
            ),
            (
                "blocking_factors",
                (
                    brief.blocking_factors[0].model_copy(
                        update={"related_strategy_ids": ("sc-a", "sc-c")}
                    ),
                ),
            ),
            (
                "robustness_profiles",
                (
                    brief.robustness_profiles[0].model_copy(
                        update={"maximum_total_weighted_regret": 0.9}
                    ),
                    brief.robustness_profiles[1],
                ),
            ),
            (
                "assumptions",
                (brief.assumptions[0].model_copy(update={"statement": "Changed."}),),
            ),
            ("evaluation_profile_id", "profile-2"),
            ("evaluation_profile_content_hash", "c" * 63 + "d"),
            ("uncertainty_model_id", "um-1"),
            ("uncertainty_model_content_hash", "ab" * 32),
            ("source_world_realization_matrix_id", "realization-matrix-2"),
            ("source_world_realization_matrix_content_hash", "d" * 63 + "e"),
            ("source_metric_observation_matrix_id", "observation-matrix-2"),
            ("source_metric_observation_matrix_content_hash", "e" * 63 + "f"),
            ("source_outcome_matrix_id", "matrix-2"),
            ("source_outcome_matrix_content_hash", "f" * 63 + "e"),
            ("produced_at", datetime(2026, 8, 17, 12, 0, tzinfo=UTC)),
        ]
        for field, value in changed:
            modified = brief.model_copy(update={field: value})
            assert campaign_decision_brief_content_hash(modified) != GOLDEN_BRIEF_HASH, (
                f"brief field {field} did not change the hash"
            )

    def test_policy_weights_and_tail_alpha_are_content_covered(self) -> None:
        policy = _policy()
        reweighted = policy.model_copy(
            update={
                "objective_weight_snapshots": (
                    policy.objective_weight_snapshots[0].model_copy(update={"weight": 0.0}),
                    policy.objective_weight_snapshots[1],
                )
            }
        )
        assert campaign_decision_policy_content_hash(reweighted) != GOLDEN_POLICY_HASH
        reordered = policy.model_copy(
            update={
                "objective_weight_snapshots": tuple(reversed(policy.objective_weight_snapshots))
            }
        )
        assert campaign_decision_policy_content_hash(reordered) != GOLDEN_POLICY_HASH
        assert (
            campaign_decision_policy_content_hash(policy.model_copy(update={"tail_alpha": 0.9}))
            != GOLDEN_POLICY_HASH
        )

    def test_nested_evidence_changes_detectable_via_model_copy(self) -> None:
        comparison = _comparison()
        tampered_delta = comparison.paired_comparisons[0].model_copy(
            update={"ordered_paired_deltas": (-1.0, -0.5, -0.2)}
        )
        modified = comparison.model_copy(
            update={"paired_comparisons": (tampered_delta, *comparison.paired_comparisons[1:])}
        )
        assert campaign_strategy_comparison_content_hash(modified) != GOLDEN_COMPARISON_HASH
        brief = _brief()
        tampered_status = brief.robustness_profiles[0].model_copy(update={"feasible": False})
        modified_brief = brief.model_copy(
            update={
                "robustness_profiles": (
                    tampered_status,
                    *brief.robustness_profiles[1:],
                )
            }
        )
        assert campaign_decision_brief_content_hash(modified_brief) != GOLDEN_BRIEF_HASH

    def test_optional_uncertainty_absent_vs_present_changes_brief_hash(self) -> None:
        absent = _brief()
        present = _brief(
            uncertainty_model_id="um-1",
            uncertainty_model_content_hash="ab" * 32,
        )
        assert campaign_decision_brief_content_hash(present) != (
            campaign_decision_brief_content_hash(absent)
        )
        other = present.model_copy(update={"uncertainty_model_content_hash": "cd" * 32})
        assert campaign_decision_brief_content_hash(other) != (
            campaign_decision_brief_content_hash(present)
        )

    def test_functions_never_mutate_inputs(self) -> None:
        policy = _policy()
        comparison = _comparison()
        brief = _brief()
        policy_before = policy.model_dump(mode="json")
        comparison_before = comparison.model_dump(mode="json")
        brief_before = brief.model_dump(mode="json")
        campaign_decision_policy_identifier(**_POLICY_IDENTITY_INPUTS)
        campaign_strategy_comparison_identifier(**_COMPARISON_IDENTITY_INPUTS)
        campaign_decision_brief_identifier(**_BRIEF_IDENTITY_INPUTS)
        campaign_decision_policy_content_hash(policy)
        campaign_strategy_comparison_content_hash(comparison)
        campaign_decision_brief_content_hash(brief)
        assert policy.model_dump(mode="json") == policy_before
        assert comparison.model_dump(mode="json") == comparison_before
        assert brief.model_dump(mode="json") == brief_before


class TestModuleBoundaries:
    def test_imports_only_the_two_allowed_internal_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_paths.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_paths.add(node.module)
        assert module_paths == {
            "__future__",
            "kalhas.application.hashing",
            "kalhas.contracts.v1.campaign_decision",
        }, sorted(module_paths)
        modules = {path.split(".")[0] for path in module_paths}
        assert modules == {"__future__", "kalhas"}
        assert "pydantic" not in modules

    def test_no_forbidden_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        forbidden = {
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "shutil",
            "tempfile",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "random",
            "uuid",
            "secrets",
            "datetime",
            "time",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
        }
        assert not (modules & forbidden)

    def test_no_store_api_query_or_persistence_identifiers(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names
        module_paths: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module_paths.add(node.module)
        assert not any(path.startswith("kalhas.api") for path in module_paths)
        assert not any("query" in path for path in module_paths)

    def test_no_wall_clock_randomness_or_activity_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        calls: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            parts: list[str] = []
            target: ast.expr = node.func
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
            calls.add(".".join(reversed(parts)))
        forbidden_calls = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "date.today",
            "time.time",
            "time.monotonic",
            "time.perf_counter",
            "time.clock",
            "time.gmtime",
            "time.localtime",
            "random.seed",
            "random.random",
            "uuid.uuid4",
            "uuid.uuid1",
        }
        assert not (calls & forbidden_calls)
        assert not any(
            "record_activity" in call or "operational_activity" in call for call in calls
        )

    def test_no_executable_expression_surface(self) -> None:
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

    def test_no_phase_number_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_ranking_winner_recommendation_adaptive_surface(self) -> None:
        import kalhas.application.campaign_decision_identity as module

        forbidden = re.compile(r"rank|winner|recommend|confidence|forecast|adaptive", re.IGNORECASE)
        symbols = list(module.__all__)
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
                symbols.extend(argument.arg for argument in node.args.args)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"

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

    def test_module_source_sha256_recorded(self) -> None:
        digest = hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest()
        assert len(digest) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None
