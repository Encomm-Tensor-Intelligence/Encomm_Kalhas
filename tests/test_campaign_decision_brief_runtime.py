"""Tests for the pure campaign decision brief assembly builder.

Tests for ``kalhas/application/campaign_decision_brief_runtime.py``:
the single public builder that transforms one verified
``ScenarioSpec``, one verified ``CampaignDecisionPolicy``, one verified
``CampaignOutcomeDistributionMatrix``, and one verified
``CampaignStrategyComparison`` into the complete immutable derived
``CampaignDecisionBrief`` artifact. Proves:

- the exact public surface (keyword-only signature, exact ``__all__``,
  the narrow import allowlist, and the purity/boundary guarantees: no
  wall clock, randomness, UUID, store, API, query, activity, execution,
  replay, registration, or lower-builder surface);
- the four exact statuses (``preferred`` unique minimax, ``inconclusive``
  minimax tie, ``insufficient_evidence`` seed gate, ``no_feasible_strategy``
  hard-gate gate), the preferred-id presence rules, and the exact
  boundaries (K below/at the minimum, inclusive best-plus-tolerance
  ties, one adjacent float above the boundary, all-zero weights,
  singleton candidates, gates disabled);
- the exact terminal reasons, the exact summary strings, and the
  complete ordered decisive/blocking factor trails from the closed
  catalogue (feasible candidates, target pass/fail values, Pareto
  non-dominated identities, dominated identities with feasible
  dominators, the complete tie set, the nearest competitor with the
  exact regret gap, and the terminal blocking factors);
- provenance and determinism: assumptions and profiles copied exactly
  and in order, every evidence id/hash copied from the verified
  sources, ``produced_at`` equal to the comparison ``derived_at``,
  deterministic identifier and content hash, repeated-call equality,
  and never-stored output;
- the adversarial trust boundaries: every identifier/hash mismatch,
  every cross-source mismatch, both-or-neither violations, ordered
  tuple and timestamp mismatches, validator-bypassed malformed nested
  data, generated reason/factor/brief rejections, late failure with no
  partial result, and the non-finite decision boundary propagating
  ``OverflowError`` unchanged;
- architectural purity through AST/source assertions.

Valid expected results always come from the accepted builders and the
recorded fields of the verified artifacts; no decision formula is
duplicated inside these tests.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_decision_brief_runtime import (
    build_campaign_decision_brief,
)
from kalhas.application.campaign_decision_comparison_runtime import (
    build_campaign_strategy_comparison,
)
from kalhas.application.campaign_decision_identity import (
    campaign_decision_brief_content_hash,
    campaign_decision_brief_identifier,
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
    campaign_strategy_comparison_content_hash,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.objective_evaluation_identity import scenario_content_hash
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    StrategyRobustnessProfile,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding
from kalhas.contracts.v1.scenario import ScenarioSpec

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_decision_brief_runtime.py"
)

TENANT = "tenant-1"
CAMPAIGN = "campaign-1"
SCENARIO = "scenario-1"
WORLD = "world-1"
PROFILE = "profile-1"
HASH_B = "b" * 64
HASH_C = "c" * 64
TOLERANCE = 0.05
ALGORITHM = "feasibility-pareto-minimax-regret-v1"
_DERIVED_AT = "2026-08-15T12:00:00Z"


def _binding(
    *,
    objective_id: str,
    metric_id: str,
    direction: str,
    target: float | None,
    weight: float,
    normalization_scale: float,
    reach_tolerance: float | None = None,
) -> ObjectiveMetricBinding:
    """One valid objective-to-metric binding for outcome construction."""
    payload: dict[str, object] = {
        "objective_id": objective_id,
        "metric_id": metric_id,
        "direction": direction,
        "target": target,
        "weight": weight,
        "metric_unit": "units",
        "reach_tolerance": reach_tolerance,
        "normalization_scale": normalization_scale,
    }
    return ObjectiveMetricBinding(**cast(Any, payload))


OBJ1_BINDING = _binding(
    objective_id="obj-1",
    metric_id="m-1",
    direction="minimize",
    target=100.0,
    weight=1.0,
    normalization_scale=100.0,
)
OBJ2_BINDING = _binding(
    objective_id="obj-2",
    metric_id="m-2",
    direction="maximize",
    target=50.0,
    weight=0.5,
    normalization_scale=10.0,
)
OBJ5_BINDING = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=0.25,
    normalization_scale=10.0,
)
OBJ4_BINDING_W1 = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=1.0,
    normalization_scale=1.0,
)
OBJ5_BINDING_W1 = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=1.0,
    normalization_scale=1.0,
)
OBJ4_BINDING_W0 = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=0.0,
    normalization_scale=1.0,
)
OBJ5_BINDING_W0 = _binding(
    objective_id="obj-5",
    metric_id="m-5",
    direction="minimize",
    target=None,
    weight=0.0,
    normalization_scale=1.0,
)


def _scenario(**overrides: object) -> ScenarioSpec:
    """The canonical declared scenario bound to the policy/matrix fixtures."""
    payload: dict[str, Any] = {
        "identifier": SCENARIO,
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "name": "Canonical decision scenario",
        "description": "Declared fixture scenario for the decision brief builder.",
        "created_at": "2026-08-14T12:00:00Z",
        "objectives": [
            {
                "identifier": "obj-1",
                "description": "Minimize cost.",
                "direction": "minimize",
                "target": 100.0,
                "weight": 1.0,
            },
            {
                "identifier": "obj-2",
                "description": "Maximize coverage.",
                "direction": "maximize",
                "target": 50.0,
                "weight": 0.5,
            },
        ],
        "constraints": [],
        "time_horizon": {
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-12-31T00:00:00Z",
        },
        "metrics": [],
        "assumptions": [
            {
                "identifier": "assumption-1",
                "statement": "Declared fixture assumption one.",
                "confidence": 1.0,
            },
            {
                "identifier": "assumption-2",
                "statement": "Declared fixture assumption two.",
                "confidence": 0.9,
            },
        ],
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return ScenarioSpec.model_validate(payload)


#: The deterministic content hash of the canonical scenario; every honest
#: policy/matrix fixture records exactly this digest.
_SCENARIO_HASH = scenario_content_hash(_scenario())


def _outcome(
    *,
    sequence_position: int,
    strategy_position: int,
    objective_position: int,
    strategy_candidate_id: str,
    binding: ObjectiveMetricBinding,
    ordered_observed_values: tuple[int | float, ...],
) -> StrategyObjectiveOutcome:
    """One outcome built by the accepted pure builder (never duplicated)."""
    return build_strategy_objective_outcome(
        sequence_position=sequence_position,
        strategy_position=strategy_position,
        objective_position=objective_position,
        strategy_candidate_id=strategy_candidate_id,
        binding=binding,
        ordered_observed_values=ordered_observed_values,
    )


def _matrix_payload(
    *,
    strategies: tuple[str, ...],
    seeds: tuple[str, ...],
    bindings: dict[str, ObjectiveMetricBinding],
    values: dict[tuple[str, str], tuple[int | float, ...]],
    scenario_content_hash: str = _SCENARIO_HASH,
    **overrides: object,
) -> dict[str, object]:
    """One internally consistent matrix payload (all outcomes derived)."""
    objective_ids = tuple(bindings)
    metric_ids = tuple(bindings[objective_id].metric_id for objective_id in objective_ids)
    outcomes: list[StrategyObjectiveOutcome] = []
    for strategy_position, strategy_id in enumerate(strategies):
        for objective_position, objective_id in enumerate(objective_ids):
            outcomes.append(
                _outcome(
                    sequence_position=strategy_position * len(objective_ids) + objective_position,
                    strategy_position=strategy_position,
                    objective_position=objective_position,
                    strategy_candidate_id=strategy_id,
                    binding=bindings[objective_id],
                    ordered_observed_values=values[(strategy_id, objective_id)],
                )
            )
    payload: dict[str, object] = {
        "identifier": "placeholder",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": scenario_content_hash,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "uncertainty_model_id": None,
        "uncertainty_model_content_hash": None,
        "source_world_realization_matrix_id": "realization-matrix-1",
        "source_world_realization_matrix_content_hash": "d" * 64,
        "source_metric_observation_matrix_id": "observation-matrix-1",
        "source_metric_observation_matrix_content_hash": "e" * 64,
        "ordered_strategy_candidate_ids": list(strategies),
        "ordered_scenario_seed_ids": list(seeds),
        "ordered_objective_ids": list(objective_ids),
        "ordered_metric_ids": list(metric_ids),
        "outcomes": outcomes,
        "content_hash": "0" * 64,
        "derived_at": _DERIVED_AT,
    }
    payload.update(overrides)
    return payload


def _finalize_matrix(
    matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignOutcomeDistributionMatrix:
    """Finalize a matrix with its genuine computed identifier and content hash."""
    identifier = campaign_outcome_distribution_matrix_identifier(
        campaign_id=matrix.campaign_id,
        world_version_id=matrix.world_version_id,
        runtime_version=matrix.runtime_version,
        evaluation_profile_id=matrix.evaluation_profile_id,
        source_world_realization_matrix_id=matrix.source_world_realization_matrix_id,
        source_metric_observation_matrix_id=matrix.source_metric_observation_matrix_id,
    )
    with_identifier = matrix.model_copy(update={"identifier": identifier})
    content_hash = campaign_outcome_distribution_matrix_content_hash(with_identifier)
    return with_identifier.model_copy(update={"content_hash": content_hash})


def _matrix(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """The validated matrix built from the payload with genuine identity/hash."""
    return _finalize_matrix(
        CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(**cast(Any, overrides)))
    )


def _matrix_2x1(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted minimize objective x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99.5) and sc-b (100, 100, 100).
    sc-a dominates sc-b under the 0.05 tolerance; both achieve 3/3 so
    both are feasible and sc-a is the singleton non-dominated candidate.
    """
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1", "seed-2"),
        bindings={"obj-1": OBJ1_BINDING},
        values={
            ("sc-a", "obj-1"): (90, 95, 99.5),
            ("sc-b", "obj-1"): (100, 100, 100),
        },
        **overrides,
    )


def _matrix_3x2(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Three strategies x two targeted objectives x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99), sc-b (100, 100, 100),
    sc-c (150, 160, 170) - probabilities 1.0 / 1.0 / 0.0.
    obj-2 maximize (scale 10): sc-a (60, 55, 50), sc-b (50, 50, 50),
    sc-c (50, 50, 30) - probabilities 1.0 / 1.0 / 2/3.

    sc-a dominates sc-b and sc-c; sc-b dominates sc-c; sc-c is
    infeasible (obj-1 probability 0.0 under a 0.4 threshold). The
    feasible non-dominated candidate set is the singleton (sc-a,).
    """
    return _matrix(
        strategies=("sc-a", "sc-b", "sc-c"),
        seeds=("seed-0", "seed-1", "seed-2"),
        bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING},
        values={
            ("sc-a", "obj-1"): (90, 95, 99),
            ("sc-b", "obj-1"): (100, 100, 100),
            ("sc-c", "obj-1"): (150, 160, 170),
            ("sc-a", "obj-2"): (60, 55, 50),
            ("sc-b", "obj-2"): (50, 50, 50),
            ("sc-c", "obj-2"): (50, 50, 30),
        },
        **overrides,
    )


def _matrix_crossing(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one optimization-only minimize objective, crossing deltas.

    obj-5 minimize (scale 10, no target): sc-a (100, 110, 90), sc-b
    (105, 105, 105) - mixed wins and losses in both directions, so
    neither strategy dominates and both are minimax candidates with
    distinct maxima (a unique minimax preference for sc-a).
    """
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1", "seed-2"),
        bindings={"obj-5": OBJ5_BINDING},
        values={
            ("sc-a", "obj-5"): (100, 110, 90),
            ("sc-b", "obj-5"): (105, 105, 105),
        },
        **overrides,
    )


def _matrix_zero_feasible(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one targeted objective, both infeasible under 1.0.

    obj-1 minimize (target 100, scale 100): sc-a (90, 90, 110) and
    sc-b (95, 95, 105) both achieve 2/3 - both fail a global threshold
    of 1.0; every paired delta is a tie so neither dominates and no
    feasible strategy exists under hard gates.
    """
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1", "seed-2"),
        bindings={"obj-1": OBJ1_BINDING},
        values={
            ("sc-a", "obj-1"): (90, 90, 110),
            ("sc-b", "obj-1"): (95, 95, 105),
        },
        **overrides,
    )


def _matrix_boundary(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two weight-1 minimize objectives with mirrored values.

    sc-a carries (1, 2) on obj-4 and zeros on obj-5; sc-b zeros on
    obj-4 and (1, 2) on obj-5 - crossing wins on the two objectives so
    neither strategy dominates and both stay minimax candidates with
    identical per-seed total weighted regrets (a genuine two-way tie
    with no unique winner).
    """
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1"),
        bindings={"obj-4": OBJ4_BINDING_W1, "obj-5": OBJ5_BINDING_W1},
        values={
            ("sc-a", "obj-4"): (1, 2),
            ("sc-b", "obj-4"): (0, 0),
            ("sc-a", "obj-5"): (0, 0),
            ("sc-b", "obj-5"): (1, 2),
        },
        **overrides,
    )


def _matrix_ulp(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """The boundary matrix with sc-b exactly one float step above the tie boundary.

    obj-4/obj-5 minimize scale 1: sc-a maxima are exactly 2.0 while
    sc-b's maxima equal ``nextafter(2.05, inf)`` - one adjacent float
    above ``best + tie_tolerance``, so sc-b is not tied and sc-a is the
    unique minimax preference.
    """
    n = math.nextafter(2.05, math.inf)
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1"),
        bindings={"obj-4": OBJ4_BINDING_W1, "obj-5": OBJ5_BINDING_W1},
        values={
            ("sc-a", "obj-4"): (1, 2),
            ("sc-b", "obj-4"): (0, 0),
            ("sc-a", "obj-5"): (0, 0),
            ("sc-b", "obj-5"): (n, n),
        },
        **overrides,
    )


def _matrix_zero_weights(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """The boundary matrix under all-zero authoritative weights.

    Every weighted regret is exactly 0.0, so both candidates share the
    same maximum and the minimax decision is an exact tie - no
    arbitrary winner may be manufactured.
    """
    return _matrix(
        strategies=("sc-a", "sc-b"),
        seeds=("seed-0", "seed-1"),
        bindings={"obj-4": OBJ4_BINDING_W0, "obj-5": OBJ5_BINDING_W0},
        values={
            ("sc-a", "obj-4"): (1, 2),
            ("sc-b", "obj-4"): (0, 0),
            ("sc-a", "obj-5"): (0, 0),
            ("sc-b", "obj-5"): (1, 2),
        },
        **overrides,
    )


def _policy_payload(
    *,
    requirements: tuple[tuple[str, float], ...] = (("obj-1", 0.4),),
    weight_snapshots: tuple[tuple[str, float], ...] = (("obj-1", 1.0),),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    hard_gates: bool = True,
    scenario_content_hash: str = _SCENARIO_HASH,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent per-objective-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "placeholder",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": scenario_content_hash,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "algorithm_identifier": ALGORITHM,
        "target_requirement_mode": "per_objective",
        "minimum_target_achievement_probability": None,
        "objective_target_requirements": [
            {"objective_id": objective_id, "minimum_target_achievement_probability": threshold}
            for objective_id, threshold in requirements
        ],
        "objective_weight_snapshots": [
            {"objective_id": objective_id, "weight": weight}
            for objective_id, weight in weight_snapshots
        ],
        "minimum_sample_count": minimum_sample_count,
        "tie_tolerance": tolerance,
        "all_targeted_objectives_are_hard_gates": hard_gates,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _policy_global_payload(
    *,
    threshold: float = 0.4,
    weight_snapshots: tuple[tuple[str, float], ...] = (("obj-1", 1.0),),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    hard_gates: bool = True,
    scenario_content_hash: str = _SCENARIO_HASH,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent global-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "placeholder",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": scenario_content_hash,
        "world_version_id": WORLD,
        "world_content_hash": HASH_B,
        "evaluation_profile_id": PROFILE,
        "evaluation_profile_content_hash": HASH_C,
        "algorithm_identifier": ALGORITHM,
        "target_requirement_mode": "global",
        "minimum_target_achievement_probability": threshold,
        "objective_target_requirements": [],
        "objective_weight_snapshots": [
            {"objective_id": objective_id, "weight": weight}
            for objective_id, weight in weight_snapshots
        ],
        "minimum_sample_count": minimum_sample_count,
        "tie_tolerance": tolerance,
        "all_targeted_objectives_are_hard_gates": hard_gates,
        "tail_alpha": 0.95,
        "content_hash": "0" * 64,
        "declared_at": "2026-08-16T12:00:00Z",
        "metadata": {"source": "authoritative"},
    }
    payload.update(overrides)
    return payload


def _finalize_policy(policy: CampaignDecisionPolicy) -> CampaignDecisionPolicy:
    """Finalize a policy with its genuine computed identifier and content hash."""
    identifier = campaign_decision_policy_identifier(
        tenant_id=policy.tenant_id,
        campaign_id=policy.campaign_id,
        scenario_id=policy.scenario_id,
        world_version_id=policy.world_version_id,
        evaluation_profile_id=policy.evaluation_profile_id,
        schema_version=policy.schema_version,
    )
    with_identifier = policy.model_copy(update={"identifier": identifier})
    content_hash = campaign_decision_policy_content_hash(with_identifier)
    return with_identifier.model_copy(update={"content_hash": content_hash})


def _policy(**overrides: Any) -> CampaignDecisionPolicy:
    """The per-objective policy matching the single-objective obj-1 matrices."""
    return _finalize_policy(CampaignDecisionPolicy.model_validate(_policy_payload(**overrides)))


def _policy_3x2(**overrides: Any) -> CampaignDecisionPolicy:
    """The per-objective policy matching the two-targeted-objective matrices."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", 0.4), ("obj-2", 0.4)),
                weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
                **overrides,
            )
        )
    )


def _policy_global_obj5(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the optimization-only obj-5 matrix."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(
            _policy_global_payload(weight_snapshots=(("obj-5", 0.25),), **overrides)
        )
    )


def _policy_global_threshold_1(**overrides: Any) -> CampaignDecisionPolicy:
    """The global-mode policy matching the zero-feasible matrix (threshold 1.0)."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(_policy_global_payload(threshold=1.0, **overrides))
    )


def _policy_insufficient(**overrides: Any) -> CampaignDecisionPolicy:
    """The policy matching the 2x1 matrix with an unmet sample-count minimum."""
    return _policy(minimum_sample_count=10, **overrides)


def _policy_boundary(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the two weight-1 boundary matrix."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(
            _policy_global_payload(
                weight_snapshots=(("obj-4", 1.0), ("obj-5", 1.0)),
                minimum_sample_count=2,
                **overrides,
            )
        )
    )


def _policy_ulp(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the one-ulp-above-boundary matrix."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(
            _policy_global_payload(
                weight_snapshots=(("obj-4", 1.0), ("obj-5", 1.0)),
                minimum_sample_count=2,
                **overrides,
            )
        )
    )


def _policy_zero_weights(**overrides: Any) -> CampaignDecisionPolicy:
    """The global policy matching the all-zero-weight boundary matrix."""
    return _finalize_policy(
        CampaignDecisionPolicy.model_validate(
            _policy_global_payload(
                weight_snapshots=(("obj-4", 0.0), ("obj-5", 0.0)),
                minimum_sample_count=2,
                **overrides,
            )
        )
    )


def _parts(
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    scenario: ScenarioSpec | None = None,
) -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The complete (scenario, policy, matrix, comparison) fixture tuple."""
    if scenario is None:
        scenario = _scenario()
    comparison = build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)
    return scenario, policy, matrix, comparison


def _parts_3x2(
    policy_overrides: dict[str, object] | None = None,
    matrix_overrides: dict[str, object] | None = None,
) -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The preferred-singleton three-strategy fixture."""
    return _parts(
        _policy_3x2(scenario_content_hash=_SCENARIO_HASH, **(policy_overrides or {})),
        _matrix_3x2(scenario_content_hash=_SCENARIO_HASH, **(matrix_overrides or {})),
    )


def _parts_2x1() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The preferred-singleton two-strategy fixture (K == minimum)."""
    return _parts(
        _policy(scenario_content_hash=_SCENARIO_HASH),
        _matrix_2x1(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_insufficient() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The insufficient-evidence fixture (K = 3 below the declared minimum 10)."""
    return _parts(
        _policy_insufficient(scenario_content_hash=_SCENARIO_HASH),
        _matrix_2x1(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_boundary() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The inconclusive two-way tie fixture."""
    return _parts(
        _policy_boundary(scenario_content_hash=_SCENARIO_HASH),
        _matrix_boundary(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_zero() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The no-feasible-strategy fixture (hard gates, threshold 1.0)."""
    return _parts(
        _policy_global_threshold_1(scenario_content_hash=_SCENARIO_HASH),
        _matrix_zero_feasible(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_crossing() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The preferred-with-competitor fixture (unique minimax, nearest competitor)."""
    return _parts(
        _policy_global_obj5(scenario_content_hash=_SCENARIO_HASH),
        _matrix_crossing(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_ulp() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The one-adjacent-float-above-boundary fixture."""
    return _parts(
        _policy_ulp(scenario_content_hash=_SCENARIO_HASH),
        _matrix_ulp(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_zero_weights() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The all-zero-weights exact-tie fixture."""
    return _parts(
        _policy_zero_weights(scenario_content_hash=_SCENARIO_HASH),
        _matrix_zero_weights(scenario_content_hash=_SCENARIO_HASH),
    )


def _parts_gates_off_zero() -> tuple[
    ScenarioSpec,
    CampaignDecisionPolicy,
    CampaignOutcomeDistributionMatrix,
    CampaignStrategyComparison,
]:
    """The zero-feasible matrix under disabled hard gates (never no-feasible)."""
    return _parts(
        _policy_global_threshold_1(scenario_content_hash=_SCENARIO_HASH, hard_gates=False),
        _matrix_zero_feasible(scenario_content_hash=_SCENARIO_HASH),
    )


def _brief(
    scenario: ScenarioSpec,
    policy: CampaignDecisionPolicy,
    matrix: CampaignOutcomeDistributionMatrix,
    comparison: CampaignStrategyComparison,
) -> CampaignDecisionBrief:
    """One complete derived brief through the builder under test."""
    return build_campaign_decision_brief(
        scenario=scenario,
        policy=policy,
        outcome_matrix=matrix,
        comparison=comparison,
    )


def _tampered_comparison(
    comparison: CampaignStrategyComparison, **updates: object
) -> CampaignStrategyComparison:
    """A self-consistently rehashed validator-bypassed comparison."""
    tampered = comparison.model_copy(update=cast(Any, updates))
    return tampered.model_copy(
        update={"content_hash": campaign_strategy_comparison_content_hash(tampered)}
    )


def _rehashed_policy(policy: CampaignDecisionPolicy) -> CampaignDecisionPolicy:
    """The supplied policy with its recorded content hash recomputed over its payload."""
    return policy.model_copy(update={"content_hash": campaign_decision_policy_content_hash(policy)})


def _rehashed_matrix(
    matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignOutcomeDistributionMatrix:
    """The supplied matrix with its recorded content hash recomputed over its payload."""
    return matrix.model_copy(
        update={"content_hash": campaign_outcome_distribution_matrix_content_hash(matrix)}
    )


def _tampered_profile(
    comparison: CampaignStrategyComparison, position: int, **updates: object
) -> CampaignStrategyComparison:
    """The comparison with one self-consistently rehashed tampered profile."""
    profiles = list(comparison.robustness_profiles)
    profiles[position] = profiles[position].model_copy(update=cast(Any, updates))
    return _tampered_comparison(comparison, robustness_profiles=tuple(profiles))


def _tamper_feasibility_record(
    comparison: CampaignStrategyComparison,
    position: int,
    objective_position: int,
    **updates: object,
) -> CampaignStrategyComparison:
    """The comparison with one coherently forged target-feasibility record.

    The record is modified in place of a genuine comparison, the
    enclosing profile is reassembled without validation, and the
    comparison content hash is recomputed over the forged payload, so
    the tamper reaches exactly the brief trust boundary checks.
    """
    profile = comparison.robustness_profiles[position]
    records = list(profile.target_feasibility)
    records[objective_position] = records[objective_position].model_copy(update=cast(Any, updates))
    return _tampered_profile(comparison, position, target_feasibility=tuple(records))


def _tamper_probability_record(
    comparison: CampaignStrategyComparison,
    position: int,
    objective_position: int,
    **updates: object,
) -> CampaignStrategyComparison:
    """The comparison with one coherently forged target-achievement record."""
    profile = comparison.robustness_profiles[position]
    records = list(profile.target_achievement_probabilities)
    records[objective_position] = records[objective_position].model_copy(update=cast(Any, updates))
    return _tampered_profile(comparison, position, target_achievement_probabilities=tuple(records))


def _tamper_downside_record(
    comparison: CampaignStrategyComparison,
    position: int,
    objective_position: int,
    **updates: object,
) -> CampaignStrategyComparison:
    """The comparison with one coherently forged downside-evidence record."""
    profile = comparison.robustness_profiles[position]
    records = list(profile.downside_evidence)
    records[objective_position] = records[objective_position].model_copy(update=cast(Any, updates))
    return _tampered_profile(comparison, position, downside_evidence=tuple(records))


class TestPublicSurface:
    def test_exact_all(self) -> None:
        from kalhas.application import campaign_decision_brief_runtime as module

        assert module.__all__ == ["build_campaign_decision_brief"]
        assert module.build_campaign_decision_brief.__module__ == (
            "kalhas.application.campaign_decision_brief_runtime"
        )

    def test_builder_signature_is_keyword_only_and_clock_free(self) -> None:
        signature = inspect.signature(build_campaign_decision_brief)
        assert tuple(signature.parameters) == ("scenario", "policy", "outcome_matrix", "comparison")
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        for parameter in signature.parameters.values():
            assert parameter.name not in {"now", "clock", "timestamp", "wall_clock", "current_time"}
        assert signature.return_annotation == "CampaignDecisionBrief"

    def test_imported_module_boundary(self) -> None:
        tree = _module_tree()
        modules = _imported_modules(tree)
        assert modules <= {"__future__", "typing", "math", "warnings", "pydantic", "kalhas"}
        kalhas_paths = {
            path
            for path in _imported_module_paths(tree)
            if path == "kalhas" or path.startswith("kalhas.")
        }
        assert kalhas_paths <= {
            "kalhas.application.campaign_decision_identity",
            "kalhas.application.campaign_outcome_identity",
            "kalhas.application.objective_evaluation_identity",
            "kalhas.contracts.v1.campaign_decision",
            "kalhas.contracts.v1.campaign_outcome",
            "kalhas.contracts.v1.scenario",
        }

    def test_no_forbidden_module_imports(self) -> None:
        forbidden = {
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "os",
            "sys",
            "subprocess",
            "shutil",
            "tempfile",
            "pathlib",
            "random",
            "uuid",
            "secrets",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
            "datetime",
            "time",
            "dateutil",
        }
        assert not (_imported_modules(_module_tree()) & forbidden)

    def test_no_clock_randomness_or_process_hash_calls(self) -> None:
        tree = _module_tree()
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_chains = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "time.time",
            "time.monotonic",
            "time.perf_counter",
            "random.seed",
            "random.random",
            "uuid.uuid4",
            "os.getpid",
            "os.urandom",
        }
        assert not (calls & forbidden_chains)
        assert not any(chain.startswith("random.") for chain in calls)

    def test_no_store_api_query_activity_execution_replay_surface(self) -> None:
        tree = _module_tree()
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("store", "api", "query", "activity", "execution", "replay"):
            assert forbidden not in names
        module_paths = _imported_module_paths(tree)
        forbidden_imports = {
            "kalhas.application.in_memory_store",
            "kalhas.application.campaign_decision_errors",
            "kalhas.application.campaign_decision_policy_service",
            "kalhas.application.campaign_decision_statistics",
            "kalhas.application.campaign_decision_evidence",
            "kalhas.application.campaign_decision_paired_comparison",
            "kalhas.application.campaign_decision_selection",
            "kalhas.application.campaign_decision_comparison_runtime",
            "kalhas.application.hashing",
            "kalhas.api",
            "kalhas.adapters",
            "kalhas.domain_packs",
        }
        assert not any(
            path == forbidden or path.startswith(forbidden + ".")
            for path in module_paths
            for forbidden in forbidden_imports
        )
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_writes = {
            "put_",
            "record_operational_activity",
            "record_activity",
            "start",
            "prepare_campaign",
            "execute_campaign",
            "replay_run",
            "execute_run",
            "register",
            "bind_manifest",
            "export_schemas",
        }
        for call in calls:
            assert not any(call.startswith(fragment) for fragment in ("store.", "put_")), call
            assert call not in forbidden_writes, call

    def test_no_lower_builder_import_or_call_surface(self) -> None:
        tree = _module_tree()
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        lower_builders = {
            "build_ordered_objective_paired_comparisons",
            "build_campaign_minimax_regret",
            "build_campaign_pareto_dominance",
            "build_campaign_decision_evidence",
            "build_campaign_strategy_comparison",
            "build_strategy_objective_outcome",
            "build_campaign_outcome_distribution_matrix",
        }
        assert not (calls & lower_builders)
        symbols = _imported_symbols(tree)
        assert not any(symbol in symbols for symbol in lower_builders)

    def test_no_executable_expression_or_callback_surface(self) -> None:
        tree = _module_tree()
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Lambda), "lambda in the pure builder"
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"exec", "eval", "compile", "__import__"}, (
                    f"executable call {name!r}"
                )
        symbols = _imported_symbols(tree)
        assert not any(symbol in symbols for symbol in ("Callable", "callback"))

    def test_module_source_free_of_phase_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_output_is_never_stored(self) -> None:
        module = importlib.import_module("kalhas.application.campaign_decision_brief_runtime")
        assert not any(
            name.startswith("store") or name.startswith("api") for name in module.__dict__
        )


class TestStatusDerivation:
    def test_preferred_unique_minimax(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "sc-a"
        assert brief.terminal_reason.code == "unique_minimax_preference"
        assert brief.terminal_reason.values == (0.0, TOLERANCE)
        assert brief.terminal_reason.related_strategy_ids == ()

    def test_inconclusive_minimax_tie(self) -> None:
        scenario, policy, matrix, comparison = _parts_boundary()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "inconclusive"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.code == "regret_tie_within_tolerance"
        assert brief.terminal_reason.values == (2.0, TOLERANCE)
        assert brief.terminal_reason.related_strategy_ids == ("sc-a", "sc-b")

    def test_insufficient_evidence(self) -> None:
        scenario, policy, matrix, comparison = _parts_insufficient()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "insufficient_evidence"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.code == "insufficient_seed_samples"
        assert brief.terminal_reason.values == (10, 3)
        assert brief.terminal_reason.related_strategy_ids == ()

    def test_no_feasible_strategy(self) -> None:
        scenario, policy, matrix, comparison = _parts_zero()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "no_feasible_strategy"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.code == "no_feasible_strategy"
        assert brief.terminal_reason.values == (2, 0)
        assert brief.terminal_reason.related_strategy_ids == ()

    @pytest.mark.parametrize(
        ("parts_name", "expected_status"),
        [
            ("_parts_3x2", "preferred"),
            ("_parts_boundary", "inconclusive"),
            ("_parts_insufficient", "insufficient_evidence"),
            ("_parts_zero", "no_feasible_strategy"),
        ],
    )
    def test_preferred_id_presence_rules(self, parts_name: str, expected_status: str) -> None:
        parts = globals()[parts_name]()
        brief = _brief(*parts)
        assert brief.status == expected_status
        if expected_status == "preferred":
            assert brief.preferred_strategy_id is not None
        else:
            assert brief.preferred_strategy_id is None

    def test_k_below_minimum_is_insufficient(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        policy = _policy_3x2(scenario_content_hash=_SCENARIO_HASH, minimum_sample_count=10)
        comparison = build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "insufficient_evidence"
        assert brief.terminal_reason.values == (10, 3)

    def test_k_equal_to_minimum_proceeds(self) -> None:
        scenario, policy, matrix, comparison = _parts_2x1()
        assert len(matrix.ordered_scenario_seed_ids) == policy.minimum_sample_count
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "sc-a"

    def test_inclusive_tolerance_boundary_tie(self) -> None:
        scenario, policy, matrix, comparison = _parts_boundary()
        brief = _brief(scenario, policy, matrix, comparison)
        best = comparison.robustness_profiles[0].maximum_total_weighted_regret
        second = comparison.robustness_profiles[1].maximum_total_weighted_regret
        assert best == second == 2.0
        assert best + policy.tie_tolerance >= second
        assert brief.status == "inconclusive"
        assert brief.terminal_reason.related_strategy_ids == ("sc-a", "sc-b")

    def test_one_adjacent_float_above_boundary_is_not_tied(self) -> None:
        scenario, policy, matrix, comparison = _parts_ulp()
        brief = _brief(scenario, policy, matrix, comparison)
        boundary = math.nextafter(2.05, math.inf)
        assert comparison.robustness_profiles[1].maximum_total_weighted_regret == boundary
        assert boundary > 2.0 + policy.tie_tolerance
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "sc-a"
        assert brief.terminal_reason.values == (2.0, TOLERANCE)

    def test_all_zero_weights_produce_no_arbitrary_winner(self) -> None:
        scenario, policy, matrix, comparison = _parts_zero_weights()
        brief = _brief(scenario, policy, matrix, comparison)
        assert all(snapshot.weight == 0.0 for snapshot in policy.objective_weight_snapshots)
        assert brief.status == "inconclusive"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.related_strategy_ids == ("sc-a", "sc-b")
        assert brief.terminal_reason.values == (0.0, TOLERANCE)

    def test_exactly_one_feasible_candidate_is_preferred(self) -> None:
        scenario, policy, matrix, comparison = _parts_2x1()
        brief = _brief(scenario, policy, matrix, comparison)
        feasible = [
            profile.strategy_candidate_id
            for profile in comparison.robustness_profiles
            if profile.feasible
        ]
        assert feasible == ["sc-a", "sc-b"]
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "sc-a"

    def test_gates_disabled_never_no_feasible_and_never_claims_failed_gates(self) -> None:
        scenario, policy, matrix, comparison = _parts_gates_off_zero()
        assert not policy.all_targeted_objectives_are_hard_gates
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "inconclusive"
        assert brief.preferred_strategy_id is None
        assert all(factor.code != "objective_target_failed" for factor in brief.blocking_factors)
        assert all(factor.code != "no_feasible_strategy" for factor in brief.blocking_factors)
        assert [factor.code for factor in brief.blocking_factors] == ["minimax_regret_tie"]

    def test_considered_order_preserved(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.considered_strategy_ids == comparison.ordered_strategy_candidate_ids


class TestReasonsFactorsSummaries:
    @pytest.mark.parametrize(
        ("parts_name", "expected"),
        [
            ("_parts_3x2", ("unique_minimax_preference", (0.0, TOLERANCE), ())),
            (
                "_parts_boundary",
                ("regret_tie_within_tolerance", (2.0, TOLERANCE), ("sc-a", "sc-b")),
            ),  # noqa: E501
            ("_parts_insufficient", ("insufficient_seed_samples", (10, 3), ())),
            ("_parts_zero", ("no_feasible_strategy", (2, 0), ())),
        ],
    )
    def test_terminal_reason_exact_for_all_four_statuses(
        self, parts_name: str, expected: tuple[object, ...]
    ) -> None:
        brief = _brief(*globals()[parts_name]())
        assert brief.terminal_reason.code == expected[0]
        assert brief.terminal_reason.values == expected[1]
        assert brief.terminal_reason.related_strategy_ids == expected[2]

    def test_summary_exact_strings_for_all_four_statuses(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.summary == (
            f"Strategy sc-a is preferred under policy {policy.identifier}: feasible, "
            "non-dominated, unique minimum maximum total weighted regret (0.0)."
        )
        assert (
            brief.summary.encode("utf-8")
            == (
                f"Strategy sc-a is preferred under policy {policy.identifier}: feasible, "
                "non-dominated, unique minimum maximum total weighted regret (0.0)."
            ).encode()
        )

        brief = _brief(*_parts_boundary())
        assert brief.summary == (
            "No preferred strategy is issued: 2 feasible non-dominated strategies remain "
            "tied within the declared tolerance (0.05)."
        )
        assert brief.summary.encode("utf-8") == (
            b"No preferred strategy is issued: 2 feasible non-dominated strategies remain "
            b"tied within the declared tolerance (0.05)."
        )

        brief = _brief(*_parts_insufficient())
        assert brief.summary == (
            "Decision is insufficient_evidence: campaign seed count (3) is below the "
            "declared minimum sample count (10)."
        )
        assert brief.summary.encode("utf-8") == (
            b"Decision is insufficient_evidence: campaign seed count (3) is below the "
            b"declared minimum sample count (10)."
        )

        brief = _brief(*_parts_zero())
        assert brief.summary == (
            "No feasible strategy exists: none of the 2 considered strategies meets every "
            "hard target-achievement threshold."
        )
        assert brief.summary.encode("utf-8") == (
            b"No feasible strategy exists: none of the 2 considered strategies meets every "
            b"hard target-achievement threshold."
        )

    def test_complete_factor_trail_preferred_singleton(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        profiles = comparison.robustness_profiles
        expected_decisive: list[tuple[object, ...]] = [
            ("feasible_candidate", "sc-a", None, (), ()),
            ("feasible_candidate", "sc-b", None, (), ()),
        ]
        for profile in profiles:
            for record in profile.target_feasibility:
                if record.passed:
                    expected_decisive.append(
                        (
                            "target_feasibility_passed",
                            profile.strategy_candidate_id,
                            record.objective_id,
                            (record.threshold, record.observed_probability),
                            (),
                        )
                    )
        expected_decisive.append(("pareto_non_dominated", "sc-a", None, (), ()))
        assert [
            (
                factor.code,
                factor.strategy_id,
                factor.objective_id,
                factor.values,
                factor.related_strategy_ids,
            )
            for factor in brief.decisive_factors
        ] == [
            (
                code,
                strategy_id,
                objective_id,
                values,
                related,
            )
            for code, strategy_id, objective_id, values, related in expected_decisive
        ]
        assert [factor.code for factor in brief.decisive_factors] == [
            "feasible_candidate",
            "feasible_candidate",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "pareto_non_dominated",
        ]
        assert [
            (
                factor.code,
                factor.strategy_id,
                factor.objective_id,
                factor.values,
                factor.related_strategy_ids,
            )
            for factor in brief.blocking_factors
        ] == [
            ("objective_target_failed", "sc-c", "obj-1", (0.4, 0.0), ()),
            ("dominated_strategy", "sc-b", None, (), ("sc-a",)),
        ]

    def test_exact_target_pass_fail_values(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        records_by_key = {
            (profile.strategy_candidate_id, record.objective_id, record.passed): (
                record.threshold,
                record.observed_probability,
            )
            for profile in comparison.robustness_profiles
            for record in profile.target_feasibility
        }
        for factor in brief.decisive_factors:
            if factor.code == "target_feasibility_passed":
                assert factor.strategy_id is not None
                assert factor.objective_id is not None
                assert (
                    factor.values == records_by_key[(factor.strategy_id, factor.objective_id, True)]
                )
        for factor in brief.blocking_factors:
            if factor.code == "objective_target_failed":
                assert factor.strategy_id is not None
                assert factor.objective_id is not None
                assert (
                    factor.values
                    == records_by_key[(factor.strategy_id, factor.objective_id, False)]
                )
        failed = [
            factor for factor in brief.blocking_factors if factor.code == "objective_target_failed"
        ]
        assert len(failed) == 1
        assert failed[0].strategy_id == "sc-c"
        assert failed[0].objective_id == "obj-1"
        assert failed[0].values[0] == 0.4
        assert failed[0].values[1] == 0.0

    def test_exact_feasible_non_dominated_dominated_identities(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert [factor.strategy_id for factor in brief.decisive_factors] == [
            "sc-a",
            "sc-b",
            "sc-a",
            "sc-a",
            "sc-b",
            "sc-b",
            "sc-c",
            "sc-a",
        ]
        dominated = [
            factor for factor in brief.blocking_factors if factor.code == "dominated_strategy"
        ]
        assert [(factor.strategy_id, factor.related_strategy_ids) for factor in dominated] == [
            ("sc-b", ("sc-a",))
        ]

    def test_complete_tie_set_inconclusive(self) -> None:
        scenario, policy, matrix, comparison = _parts_boundary()
        brief = _brief(scenario, policy, matrix, comparison)
        tie_factors = [
            factor for factor in brief.blocking_factors if factor.code == "minimax_regret_tie"
        ]
        assert len(tie_factors) == 1
        assert tie_factors[0].related_strategy_ids == ("sc-a", "sc-b")
        assert tie_factors[0].values == (2.0, TOLERANCE)
        assert brief.terminal_reason.related_strategy_ids == ("sc-a", "sc-b")

    def test_nearest_competitor_and_exact_regret_gap(self) -> None:
        scenario, policy, matrix, comparison = _parts_crossing()
        brief = _brief(scenario, policy, matrix, comparison)
        unique = [
            factor for factor in brief.decisive_factors if factor.code == "unique_minimax_regret"
        ]
        assert len(unique) == 1
        winner_max = comparison.robustness_profiles[0].maximum_total_weighted_regret
        nearest_max = comparison.robustness_profiles[1].maximum_total_weighted_regret
        assert winner_max < nearest_max
        assert unique[0].strategy_id == "sc-a"
        assert unique[0].related_strategy_ids == ("sc-b",)
        assert unique[0].values == (winner_max, nearest_max, nearest_max - winner_max)
        assert unique[0].values[2] == unique[0].values[1] - unique[0].values[0]

    def test_exact_gap_one_ulp_above_boundary(self) -> None:
        scenario, policy, matrix, comparison = _parts_ulp()
        brief = _brief(scenario, policy, matrix, comparison)
        unique = [
            factor for factor in brief.decisive_factors if factor.code == "unique_minimax_regret"
        ]
        assert len(unique) == 1
        n = math.nextafter(2.05, math.inf)
        assert unique[0].values == (2.0, n, n - 2.0)
        assert unique[0].values[2] == unique[0].values[1] - unique[0].values[0]
        assert unique[0].values[2] != 0.05

    def test_singleton_candidate_has_no_fabricated_competitor(self) -> None:
        for parts_name in ("_parts_3x2", "_parts_2x1"):
            brief = _brief(*globals()[parts_name]())
            assert brief.status == "preferred"
            assert all(factor.code != "unique_minimax_regret" for factor in brief.decisive_factors)

    def test_no_objective_target_failed_when_gates_disabled(self) -> None:
        for parts_name in ("_parts_gates_off_zero",):
            brief = _brief(*globals()[parts_name]())
            assert all(
                factor.code != "objective_target_failed" for factor in brief.blocking_factors
            )
            assert all(
                factor.code != "target_feasibility_passed" for factor in brief.decisive_factors
            )

    def test_insufficient_evidence_terminal_factors(self) -> None:
        scenario, policy, matrix, comparison = _parts_insufficient()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.decisive_factors == ()
        assert [(factor.code, factor.values) for factor in brief.blocking_factors] == [
            ("insufficient_seed_count", (10, 3))
        ]

    def test_no_feasible_terminal_factors_with_exact_counts(self) -> None:
        scenario, policy, matrix, comparison = _parts_zero()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.decisive_factors == ()
        expected_failed = [
            (profile.strategy_candidate_id, record)
            for profile in comparison.robustness_profiles
            for record in profile.target_feasibility
            if not record.passed
        ]
        expected_blocking = [
            (
                "objective_target_failed",
                strategy_id,
                (record.threshold, record.observed_probability),
            )
            for strategy_id, record in expected_failed
        ] + [("no_feasible_strategy", None, (2, 0))]
        assert [
            (factor.code, factor.strategy_id, factor.values) for factor in brief.blocking_factors
        ] == expected_blocking
        terminal = [
            factor for factor in brief.blocking_factors if factor.code == "no_feasible_strategy"
        ]
        assert terminal[0].values == (2, 0)

    def test_factor_stage_order_holds_for_every_status(self) -> None:
        decisive_stages = {
            "feasible_candidate": 0,
            "target_feasibility_passed": 1,
            "pareto_non_dominated": 2,
            "unique_minimax_regret": 3,
        }
        blocking_stages = {
            "objective_target_failed": 0,
            "dominated_strategy": 1,
            "minimax_regret_tie": 2,
            "no_feasible_strategy": 3,
            "insufficient_seed_count": 4,
        }
        for parts_name in (
            "_parts_3x2",
            "_parts_boundary",
            "_parts_insufficient",
            "_parts_zero",
            "_parts_crossing",
            "_parts_ulp",
            "_parts_zero_weights",
            "_parts_gates_off_zero",
        ):
            brief = _brief(*globals()[parts_name]())
            decisive_codes = [factor.code for factor in brief.decisive_factors]
            blocking_codes = [factor.code for factor in brief.blocking_factors]
            assert decisive_codes == sorted(decisive_codes, key=lambda code: decisive_stages[code])
            assert blocking_codes == sorted(blocking_codes, key=lambda code: blocking_stages[code])


class TestProvenanceAndDeterminism:
    def test_assumptions_copied_exactly_and_in_order(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.assumptions == tuple(scenario.assumptions)
        assert [assumption.identifier for assumption in brief.assumptions] == [
            "assumption-1",
            "assumption-2",
        ]

    def test_profiles_copied_exactly_and_in_order(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert len(brief.robustness_profiles) == len(comparison.robustness_profiles)
        for position, profile in enumerate(brief.robustness_profiles):
            assert isinstance(profile, StrategyRobustnessProfile)
            assert profile.model_dump(mode="json") == comparison.robustness_profiles[
                position
            ].model_dump(mode="json")
        assert [profile.strategy_position for profile in brief.robustness_profiles] == [
            0,
            1,
            2,
        ]

    def test_every_evidence_reference_copied_from_verified_source(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.evaluation_profile_id == matrix.evaluation_profile_id
        assert brief.evaluation_profile_content_hash == matrix.evaluation_profile_content_hash
        assert brief.uncertainty_model_id == matrix.uncertainty_model_id
        assert brief.uncertainty_model_content_hash == matrix.uncertainty_model_content_hash
        assert brief.source_world_realization_matrix_id == matrix.source_world_realization_matrix_id
        assert (
            brief.source_world_realization_matrix_content_hash
            == matrix.source_world_realization_matrix_content_hash
        )
        assert (
            brief.source_metric_observation_matrix_id == matrix.source_metric_observation_matrix_id
        )
        assert (
            brief.source_metric_observation_matrix_content_hash
            == matrix.source_metric_observation_matrix_content_hash
        )
        assert brief.source_outcome_matrix_id == matrix.identifier
        assert brief.source_outcome_matrix_content_hash == matrix.content_hash
        assert brief.policy_id == policy.identifier
        assert brief.policy_content_hash == policy.content_hash
        assert brief.comparison_id == comparison.identifier
        assert brief.comparison_content_hash == comparison.content_hash
        assert brief.world_content_hash == comparison.world_content_hash
        assert brief.campaign_id == comparison.campaign_id
        assert brief.scenario_id == comparison.scenario_id
        assert brief.world_version_id == comparison.world_version_id
        assert brief.runtime_version == "3.0.0"
        assert brief.comparison_mode == "identical_conditions"
        assert brief.algorithm_identifier == ALGORITHM

    def test_uncertainty_provenance_copied_when_present(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2(
            matrix_overrides={
                "uncertainty_model_id": "uncertainty-1",
                "uncertainty_model_content_hash": "f" * 64,
            }
        )
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.uncertainty_model_id == "uncertainty-1"
        assert brief.uncertainty_model_content_hash == "f" * 64
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.uncertainty_model_id is None
        assert brief.uncertainty_model_content_hash is None

    def test_produced_at_equals_comparison_derived_at(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.produced_at == comparison.derived_at
        assert brief.produced_at == matrix.derived_at

    def test_deterministic_identifier(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.identifier == campaign_decision_brief_identifier(
            campaign_id=comparison.campaign_id,
            world_version_id=comparison.world_version_id,
            policy_id=policy.identifier,
            comparison_id=comparison.identifier,
        )
        assert brief.identifier.startswith("campaign-decision-brief-")
        assert len(brief.identifier) == len("campaign-decision-brief-") + 16

    def test_deterministic_content_hash(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.content_hash != "0" * 64
        assert brief.content_hash == campaign_decision_brief_content_hash(brief)

    def test_repeated_calls_return_equal_artifacts(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        first = _brief(scenario, policy, matrix, comparison)
        second = _brief(scenario, policy, matrix, comparison)
        assert second == first
        assert second.model_dump() == first.model_dump()
        assert second.identifier == first.identifier
        assert second.content_hash == first.content_hash
        assert second.produced_at == first.produced_at
        assert second.summary == first.summary
        assert second.terminal_reason == first.terminal_reason
        assert second.decisive_factors == first.decisive_factors
        assert second.blocking_factors == first.blocking_factors
        assert second.robustness_profiles == first.robustness_profiles
        assert second.assumptions == first.assumptions

    def test_complete_artifact_passes_strict_validation(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        revalidated = CampaignDecisionBrief.model_validate(
            brief.model_dump(mode="python"), strict=True
        )
        assert revalidated == brief
        json_round = CampaignDecisionBrief.model_validate_json(brief.model_dump_json())
        assert json_round == brief

    def test_inputs_are_never_mutated(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        scenario_before = scenario.model_dump(mode="json")
        policy_before = policy.model_dump(mode="json")
        matrix_before = matrix.model_dump(mode="json")
        comparison_before = comparison.model_dump(mode="json")
        _brief(scenario, policy, matrix, comparison)
        assert scenario.model_dump(mode="json") == scenario_before
        assert policy.model_dump(mode="json") == policy_before
        assert matrix.model_dump(mode="json") == matrix_before
        assert comparison.model_dump(mode="json") == comparison_before


class TestAdversarialTrustBoundaries:
    def test_wrong_top_level_types(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        with pytest.raises(ValueError, match="scenario must be a ScenarioSpec"):
            build_campaign_decision_brief(
                scenario=policy,  # type: ignore[arg-type]
                policy=policy,
                outcome_matrix=matrix,
                comparison=comparison,
            )
        with pytest.raises(ValueError, match="policy must be a CampaignDecisionPolicy"):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=matrix,  # type: ignore[arg-type]
                outcome_matrix=matrix,
                comparison=comparison,
            )
        with pytest.raises(
            ValueError, match="outcome_matrix must be a CampaignOutcomeDistributionMatrix"
        ):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=policy,
                outcome_matrix=policy,  # type: ignore[arg-type]
                comparison=comparison,
            )
        with pytest.raises(ValueError, match="comparison must be a CampaignStrategyComparison"):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=policy,
                outcome_matrix=matrix,
                comparison=policy,  # type: ignore[arg-type]
            )

    def test_scenario_identity_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        foreign = _scenario(identifier="scenario-2")
        with pytest.raises(ValueError, match="scenario identifier"):
            build_campaign_decision_brief(
                scenario=foreign, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_scenario_tenant_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        foreign = _scenario(tenant_id="tenant-2")
        with pytest.raises(ValueError, match="scenario tenant"):
            build_campaign_decision_brief(
                scenario=foreign, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_scenario_content_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        altered = _scenario(
            assumptions=[
                {
                    "identifier": "assumption-1",
                    "statement": "Altered fixture assumption.",
                    "confidence": 1.0,
                }
            ]
        )
        assert altered.identifier == scenario.identifier
        assert scenario_content_hash(altered) != scenario_content_hash(scenario)
        with pytest.raises(ValueError, match="scenario content hash"):
            build_campaign_decision_brief(
                scenario=altered, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_policy_identifier_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = policy.model_copy(update={"campaign_id": "campaign-2"})
        with pytest.raises(ValueError, match="policy identifier"):
            build_campaign_decision_brief(
                scenario=scenario, policy=tampered, outcome_matrix=matrix, comparison=comparison
            )

    def test_policy_content_hash_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = policy.model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError, match="policy content hash"):
            build_campaign_decision_brief(
                scenario=scenario, policy=tampered, outcome_matrix=matrix, comparison=comparison
            )

    def test_matrix_identifier_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = matrix.model_copy(update={"campaign_id": "campaign-2"})
        with pytest.raises(ValueError, match="outcome matrix identifier"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=tampered, comparison=comparison
            )

    def test_matrix_content_hash_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = matrix.model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError, match="outcome matrix content hash"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=tampered, comparison=comparison
            )

    def test_comparison_identifier_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(comparison, policy_id="policy-2")
        with pytest.raises(ValueError, match="comparison identifier"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_comparison_content_hash_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = comparison.model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError, match="comparison content hash"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_comparison_policy_reference_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(comparison, policy_content_hash="1" * 64)
        with pytest.raises(ValueError, match="policy content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_comparison_source_matrix_reference_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(comparison, source_outcome_matrix_content_hash="1" * 64)
        with pytest.raises(ValueError, match="source matrix content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_foreign_content_matrix_with_same_identity_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        other = _finalize_matrix(
            CampaignOutcomeDistributionMatrix.model_validate(
                _matrix_payload(
                    strategies=("sc-a", "sc-b", "sc-c"),
                    seeds=("seed-0", "seed-1", "seed-2"),
                    bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING},
                    values={
                        ("sc-a", "obj-1"): (91, 96, 100),
                        ("sc-b", "obj-1"): (100, 100, 100),
                        ("sc-c", "obj-1"): (150, 160, 170),
                        ("sc-a", "obj-2"): (60, 55, 50),
                        ("sc-b", "obj-2"): (50, 50, 50),
                        ("sc-c", "obj-2"): (50, 50, 30),
                    },
                )
            )
        )
        assert other.identifier == matrix.identifier
        assert other.content_hash != matrix.content_hash
        with pytest.raises(ValueError, match="source matrix content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=other, comparison=comparison
            )

    def test_policy_tolerance_snapshot_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        # A policy whose decision parameters differ from the comparison
        # snapshots is a different policy (its content hash covers the
        # tolerance), so the recorded policy content-hash reference is
        # the first cross-source check to reject it; the explicit
        # snapshot equality checks stay as defense-in-depth.
        tampered = _rehashed_policy(policy.model_copy(update={"tie_tolerance": 0.1}))
        with pytest.raises(ValueError, match="policy content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=tampered, outcome_matrix=matrix, comparison=comparison
            )

    def test_policy_minimum_sample_snapshot_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _rehashed_policy(policy.model_copy(update={"minimum_sample_count": 5}))
        with pytest.raises(ValueError, match="policy content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=tampered, outcome_matrix=matrix, comparison=comparison
            )

    def test_ordered_strategy_tuple_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(
            comparison, ordered_strategy_candidate_ids=("sc-x", "sc-b", "sc-c")
        )
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_ordered_seed_tuple_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(
            comparison, ordered_scenario_seed_ids=("seed-x", "seed-1", "seed-2")
        )
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_ordered_objective_tuple_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(comparison, ordered_objective_ids=("obj-x", "obj-2"))
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_matrix_derived_at_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        # The shifted derived_at is part of the matrix content, so the
        # recorded source-matrix content-hash reference is the first
        # cross-source check to reject it; the explicit derived_at
        # equality check stays as defense-in-depth.
        other = _rehashed_matrix(
            matrix.model_copy(update={"derived_at": datetime(2026, 8, 17, tzinfo=UTC)})
        )
        with pytest.raises(ValueError, match="source matrix content hash reference"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=other, comparison=comparison
            )

    def test_comparison_derived_at_mismatch(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_comparison(comparison, derived_at=datetime(2026, 8, 17, tzinfo=UTC))
        with pytest.raises(ValueError, match="derived_at"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_uncertainty_both_or_neither_violation(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = matrix.model_copy(
            update={"uncertainty_model_id": "uncertainty-1", "uncertainty_model_content_hash": None}
        )
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=tampered, comparison=comparison
            )

    def test_validator_bypassed_policy_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = policy.model_copy(update={"minimum_sample_count": True})
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=tampered, outcome_matrix=matrix, comparison=comparison
            )

    def test_validator_bypassed_comparison_feasibility_tamper_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        # sc-c fails its obj-1 gate in the recorded evidence; flipping its
        # recorded feasible flag survives the comparison contract (the flag
        # is a pipeline result, not a derived field) but violates the
        # accepted hard-gate semantics proven at the brief trust boundary.
        tampered = _tampered_profile(comparison, 2, feasible=True)
        with pytest.raises(ValueError, match="feasible flag"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_validator_bypassed_profile_identity_tamper_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tampered_profile(comparison, 0, strategy_candidate_id="sc-other")
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_validator_bypassed_target_coverage_tamper_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        profile = comparison.robustness_profiles[0]
        # Truncating both target-only tuples consistently keeps the
        # comparison contract satisfied (identical subsets in relative
        # order) while violating the exact targeted-objective coverage
        # proven at the brief trust boundary.
        tampered = _tampered_profile(
            comparison,
            0,
            target_feasibility=profile.target_feasibility[:1],
            target_achievement_probabilities=profile.target_achievement_probabilities[:1],
        )
        with pytest.raises(ValueError, match="target feasibility"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_generated_reason_rejection_becomes_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = importlib.import_module("kalhas.application.campaign_decision_brief_runtime")

        def failing_reason(**kwargs: object) -> object:
            raise ValueError("reason boom")

        monkeypatch.setattr(module, "DecisionReasonRecord", failing_reason)
        scenario, policy, matrix, comparison = _parts_3x2()
        with pytest.raises(ValueError, match="generated decision reason violates its contract"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_generated_factor_rejection_becomes_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = importlib.import_module("kalhas.application.campaign_decision_brief_runtime")

        def failing_factor(**kwargs: object) -> object:
            raise ValueError("factor boom")

        monkeypatch.setattr(module, "DecisionFactorRecord", failing_factor)
        scenario, policy, matrix, comparison = _parts_3x2()
        with pytest.raises(ValueError, match="generated decision factor violates its contract"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_generated_brief_rejection_becomes_value_error(self) -> None:
        duplicate = {
            "identifier": "assumption-1",
            "statement": "Declared fixture assumption one.",
            "confidence": 1.0,
        }
        scenario = _scenario(assumptions=[duplicate, duplicate])
        scenario_hash = scenario_content_hash(scenario)
        policy = _policy_3x2(scenario_content_hash=scenario_hash)
        matrix = _matrix_3x2(scenario_content_hash=scenario_hash)
        comparison = build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)
        with pytest.raises(
            ValueError, match="generated campaign decision brief violates its contract"
        ):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_late_factor_failure_returns_no_partial_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = importlib.import_module("kalhas.application.campaign_decision_brief_runtime")
        real_factor = module.DecisionFactorRecord

        def failing_late_factor(**kwargs: object) -> object:
            if kwargs.get("code") == "dominated_strategy":
                raise ValueError("late factor boom")
            return real_factor(**cast(Any, kwargs))

        monkeypatch.setattr(module, "DecisionFactorRecord", failing_late_factor)
        scenario, policy, matrix, comparison = _parts_3x2()
        with pytest.raises(ValueError, match="generated decision factor violates its contract"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=comparison
            )

    def test_non_finite_decision_boundary_raises_overflow(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2(policy_overrides={"tie_tolerance": 1e308})
        # Under the huge tolerance every paired delta is a tie, so both
        # feasible strategies are non-dominated minimax candidates.
        # Raising both recorded candidate maxima to 1e308 makes
        # best + tie_tolerance overflow to infinity at the decision
        # boundary, which must propagate as OverflowError (never a
        # repaired boundary and never a ValueError).
        huge = {
            "per_seed_total_weighted_regrets": (1e308, 1e308, 1e308),
            "median_total_weighted_regret": 1e308,
            "p95_total_weighted_regret": 1e308,
            "maximum_total_weighted_regret": 1e308,
        }
        tampered = _tampered_profile(comparison, 0, **huge)
        tampered = _tampered_profile(tampered, 1, **huge)
        with pytest.raises(OverflowError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_no_partial_output_on_rejection(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered_policy = policy.model_copy(update={"minimum_sample_count": True})
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=tampered_policy,
                outcome_matrix=matrix,
                comparison=comparison,
            )
        tampered_matrix = matrix.model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=policy,
                outcome_matrix=tampered_matrix,
                comparison=comparison,
            )
        # The honest inputs still build the exact artifact afterwards.
        honest = _brief(scenario, policy, matrix, comparison)
        assert honest.status == "preferred"
        assert honest.preferred_strategy_id == "sc-a"


class TestIndependentEvidenceVerification:
    """Independent profile-evidence cross-source verification regressions.

    Every forged comparison in this class is self-consistently rehashed
    (the comparison content hash is recomputed over the forged payload)
    so the tamper reaches exactly the brief trust-boundary checks and
    never fails on a stale hash.
    """

    def test_authoritative_threshold_factor_still_emitted(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        brief = _brief(scenario, policy, matrix, comparison)
        passed = [
            (factor.strategy_id, factor.objective_id, factor.values)
            for factor in brief.decisive_factors
            if factor.code == "target_feasibility_passed"
        ]
        assert ("sc-a", "obj-1", (0.4, 1.0)) in passed

    def test_forged_threshold_rejected(self) -> None:
        # The confirmed defect: authoritative 0.4 forged to 0.0 on the
        # sc-a / obj-1 feasibility record. The record stays internally
        # coherent (passed True remains consistent with 1.0 >= 0.0), so
        # only the independent policy binding can reject it.
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tamper_feasibility_record(comparison, 0, 0, threshold=0.0)
        with pytest.raises(ValueError, match="threshold"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_forged_observed_probability_rejected(self) -> None:
        # Both observed_probability and passed are forged coherently
        # (0.3 < 0.4 keeps passed False consistent); the outcome matrix
        # still records 1.0, so the independent binding rejects it.
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tamper_feasibility_record(
            comparison, 0, 0, observed_probability=0.3, passed=False
        )
        with pytest.raises(ValueError, match="observed probability"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_forged_achievement_probability_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        tampered = _tamper_probability_record(
            comparison, 0, 0, empirical_target_achievement_probability=0.5
        )
        with pytest.raises(ValueError, match="achievement probability"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_missing_achievement_probability_record_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        profile = comparison.robustness_profiles[0]
        # Truncating both target-only tuples consistently keeps the
        # comparison contract satisfied while breaking the exact
        # targeted-objective coverage.
        tampered = _tampered_profile(
            comparison,
            0,
            target_feasibility=profile.target_feasibility[:1],
            target_achievement_probabilities=profile.target_achievement_probabilities[:1],
        )
        with pytest.raises(ValueError, match="target feasibility"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_reordered_achievement_probability_record_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        profile = comparison.robustness_profiles[0]
        tampered = _tampered_profile(
            comparison,
            0,
            target_feasibility=tuple(reversed(profile.target_feasibility)),
            target_achievement_probabilities=tuple(
                reversed(profile.target_achievement_probabilities)
            ),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_additional_achievement_probability_record_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        profile = comparison.robustness_profiles[0]
        probabilities = profile.target_achievement_probabilities
        tampered = _tampered_profile(
            comparison,
            0,
            target_achievement_probabilities=tuple(list(probabilities) + [probabilities[0]]),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_forged_downside_adverse_tail_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        honest = comparison.robustness_profiles[0].downside_evidence[0]
        tampered = _tamper_downside_record(
            comparison,
            0,
            0,
            adverse_tail_statistic=honest.adverse_tail_statistic + 1.0,
        )
        with pytest.raises(ValueError, match="adverse tail statistic"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_forged_downside_violation_values_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        honest = comparison.robustness_profiles[0].downside_evidence[0]
        tampered = _tamper_downside_record(
            comparison,
            0,
            0,
            worst_normalized_target_violation=(
                honest.worst_normalized_target_violation + 1.0
                if honest.worst_normalized_target_violation is not None
                else 1.0
            ),
        )
        with pytest.raises(ValueError, match="worst normalized target violation"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )
        tampered = _tamper_downside_record(
            comparison,
            0,
            0,
            target_violation_cvar=(
                honest.target_violation_cvar + 1.0
                if honest.target_violation_cvar is not None
                else 1.0
            ),
        )
        with pytest.raises(ValueError, match="target violation CVaR"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_forged_downside_on_optimization_only_objective_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_crossing()
        honest = comparison.robustness_profiles[0].downside_evidence[0]
        tampered = _tamper_downside_record(
            comparison,
            0,
            0,
            adverse_tail_statistic=honest.adverse_tail_statistic + 1.0,
        )
        with pytest.raises(ValueError, match="adverse tail statistic"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_requirement_reorder_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        requirements = policy.objective_target_requirements
        reordered = _rehashed_policy(
            policy.model_copy(
                update={"objective_target_requirements": tuple(reversed(requirements))}
            )
        )
        tampered = _tampered_comparison(comparison, policy_content_hash=reordered.content_hash)
        with pytest.raises(ValueError, match="requirements"):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=reordered,
                outcome_matrix=matrix,
                comparison=tampered,
            )

    def test_requirement_substitution_rejected(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2()
        requirements = policy.objective_target_requirements
        substituted = _rehashed_policy(
            policy.model_copy(
                update={
                    "objective_target_requirements": (
                        requirements[1].model_copy(update={"objective_id": "obj-x"}),
                        requirements[0],
                    )
                }
            )
        )
        tampered = _tampered_comparison(comparison, policy_content_hash=substituted.content_hash)
        with pytest.raises(ValueError, match="requirements"):
            build_campaign_decision_brief(
                scenario=scenario,
                policy=substituted,
                outcome_matrix=matrix,
                comparison=tampered,
            )

    def test_gates_disabled_evidence_still_verified(self) -> None:
        scenario, policy, matrix, comparison = _parts_3x2(policy_overrides={"hard_gates": False})
        assert not policy.all_targeted_objectives_are_hard_gates
        brief = _brief(scenario, policy, matrix, comparison)
        assert brief.status == "preferred"
        assert all(profile.feasible for profile in comparison.robustness_profiles)
        tampered = _tamper_probability_record(
            comparison, 0, 0, empirical_target_achievement_probability=0.5
        )
        with pytest.raises(ValueError, match="achievement probability"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )
        honest = comparison.robustness_profiles[1].downside_evidence[1]
        tampered = _tamper_downside_record(
            comparison,
            1,
            1,
            adverse_tail_statistic=honest.adverse_tail_statistic + 1.0,
        )
        with pytest.raises(ValueError, match="adverse tail statistic"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )

    def test_late_profile_tamper_returns_no_partial_brief(self) -> None:
        # Corrupt the LAST strategy's LAST objective evidence record;
        # the failure must abort the whole build with no partial brief.
        scenario, policy, matrix, comparison = _parts_3x2()
        honest = comparison.robustness_profiles[2].downside_evidence[1]
        tampered = _tamper_downside_record(
            comparison,
            2,
            1,
            adverse_tail_statistic=honest.adverse_tail_statistic + 1.0,
        )
        with pytest.raises(ValueError, match="adverse tail statistic"):
            build_campaign_decision_brief(
                scenario=scenario, policy=policy, outcome_matrix=matrix, comparison=tampered
            )
        # The genuine inputs still produce the exact artifact.
        honest_brief = _brief(scenario, policy, matrix, comparison)
        assert honest_brief.status == "preferred"
        assert honest_brief.preferred_strategy_id == "sc-a"


def _module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``math`` from ``math.fsum``)."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths


def _imported_symbols(tree: ast.Module) -> set[str]:
    """Every name bound by an ``import``/``from`` statement."""
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names)
    return symbols


def _attribute_call_chains(tree: ast.Module) -> set[str]:
    """Dotted callable chains of every call whose target is an attribute."""
    chains: set[str] = set()
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
        chains.add(".".join(reversed(parts)))
    return chains


def _name_calls(tree: ast.Module) -> set[str]:
    """Every bare-name call (``sorted(...)`` -> ``sorted``)."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    return calls
