"""Tests for the pure campaign strategy comparison assembly builder.

Tests for ``kalhas/application/campaign_decision_comparison_runtime.py``:
the single public builder that transforms one verified
``CampaignDecisionPolicy`` and one verified
``CampaignOutcomeDistributionMatrix`` into the complete immutable
derived ``CampaignStrategyComparison`` artifact. Proves:

- the exact public surface (keyword-only signature, exact ``__all__``,
  the narrow import allowlist, and the purity/boundary guarantees: no
  wall clock, randomness, UUID, store, API, query, activity, execution,
  replay, or registration surface);
- the exact builder composition: the accepted ordered-pair builder is
  called exactly once, the accepted minimax-regret builder exactly once
  and strictly after the paired builder, with the exact paired tuple
  object returned by the paired builder;
- the strict source verification: genuine computed policy/matrix
  identifiers and content hashes are accepted, every identifier input
  mismatch, every recorded-hash mismatch, every validator-bypassed
  artifact, and every cross-source mismatch is rejected with
  ``ValueError`` before any output exists;
- the intermediate trust boundary: monkeypatched malformed minimax
  aggregates (wrong counts, positions, identities, feasibility,
  relations, statuses, candidates, tie/unique fields, regret records,
  aggregates, or supporting evidence) fail before any final artifact is
  returned;
- the exact assembly: deterministic comparison identifier, content
  hash, copied ``derived_at``, exact source references, exact paired
  and dominance tuples, one robustness profile per strategy in exact
  order with every field copied from the accepted evidence/dominance/
  regret assessment, strict revalidation of the final artifact, and
  content-hash sensitivity under every material nested mutation;
- determinism (repeated calls return equal artifacts) and complete
  input/mid-result non-mutation;
- ``ValueError``/``OverflowError`` propagation semantics.

Valid expected results always come from the accepted builders and
primitives; no Phase 26 statistics, regret, Pareto, or minimax formula
is duplicated inside these tests.
"""

from __future__ import annotations

import ast
import inspect
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_decision_comparison_runtime import (
    build_campaign_strategy_comparison,
)
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
    CampaignParetoDominanceAssessment,
    build_campaign_minimax_regret,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    ObjectivePairedComparison,
    StrategyRobustnessProfile,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_decision_comparison_runtime.py"
)

TENANT = "tenant-1"
CAMPAIGN = "campaign-1"
SCENARIO = "scenario-1"
WORLD = "world-1"
PROFILE = "profile-1"
HASH_A = "a" * 64
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
        "scenario_content_hash": HASH_A,
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
    Deltas sc-a -> sc-b: (-0.1, -0.05, -0.005) -> one win, two ties ->
    sc-a dominates sc-b; both achieve 3/3 (probability 1.0) so both are
    feasible under a threshold <= 1.0.
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
    infeasible (obj-1 probability 0.0 under a 0.4 threshold). Minimax
    candidates (sc-a, sc-b); evaluated with a unique best.
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
    neither strategy dominates and both are minimax candidates.
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
    of 1.0; every paired delta is a tie so neither dominates and the
    feasible non-dominated candidate set is empty.
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


def _policy_payload(
    *,
    requirements: tuple[tuple[str, float], ...] = (("obj-1", 0.4),),
    weight_snapshots: tuple[tuple[str, float], ...] = (("obj-1", 1.0),),
    tolerance: float = TOLERANCE,
    minimum_sample_count: int = 3,
    hard_gates: bool = True,
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent per-objective-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "placeholder",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
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
    **overrides: object,
) -> dict[str, Any]:
    """One internally consistent global-mode policy payload."""
    payload: dict[str, Any] = {
        "identifier": "placeholder",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN,
        "scenario_id": SCENARIO,
        "scenario_content_hash": HASH_A,
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


def _tampered_policy(policy: CampaignDecisionPolicy, **updates: object) -> CampaignDecisionPolicy:
    """A validator-bypassed policy assembled with ``model_construct``."""
    payload = policy.model_dump(mode="python")
    payload.update(updates)
    return CampaignDecisionPolicy.model_construct(**payload)


def _tampered_matrix(
    matrix: CampaignOutcomeDistributionMatrix, **updates: object
) -> CampaignOutcomeDistributionMatrix:
    """A validator-bypassed matrix assembled with ``model_construct``."""
    payload = matrix.model_dump(mode="python")
    payload.update(updates)
    return CampaignOutcomeDistributionMatrix.model_construct(**payload)


def _tampered_outcome_matrix(
    matrix: CampaignOutcomeDistributionMatrix,
    position: int,
    **outcome_updates: object,
) -> CampaignOutcomeDistributionMatrix:
    """A validator-bypassed matrix with one tampered outcome dict."""
    payload = matrix.model_dump(mode="python")
    outcomes = list(cast(list[dict[str, Any]], payload["outcomes"]))
    tampered = dict(outcomes[position])
    tampered.update(outcome_updates)
    outcomes[position] = tampered
    payload["outcomes"] = tuple(outcomes)
    return CampaignOutcomeDistributionMatrix.model_construct(**payload)


def _with_recomputed_matrix_hash(
    matrix: CampaignOutcomeDistributionMatrix,
) -> CampaignOutcomeDistributionMatrix:
    """The supplied matrix with its recorded content hash recomputed over its payload."""
    return matrix.model_copy(
        update={"content_hash": campaign_outcome_distribution_matrix_content_hash(matrix)}
    )


def _pairs(
    policy: CampaignDecisionPolicy, matrix: CampaignOutcomeDistributionMatrix
) -> tuple[ObjectivePairedComparison, ...]:
    """The complete paired evidence through the accepted Slice 4 builder."""
    return build_ordered_objective_paired_comparisons(policy=policy, outcome_matrix=matrix)


def _expected_minimax(
    policy: CampaignDecisionPolicy, matrix: CampaignOutcomeDistributionMatrix
) -> CampaignMinimaxRegretAssessment:
    """The complete accepted minimax assessment over accepted paired evidence."""
    return build_campaign_minimax_regret(
        policy=policy,
        outcome_matrix=matrix,
        paired_comparisons=_pairs(policy, matrix),
    )


def _comparison(
    policy: CampaignDecisionPolicy, matrix: CampaignOutcomeDistributionMatrix
) -> CampaignStrategyComparison:
    """One complete derived comparison through the builder under test."""
    return build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)


def _inject_minimax(
    monkeypatch: pytest.MonkeyPatch, minimax: CampaignMinimaxRegretAssessment
) -> None:
    """Inject one (possibly tampered) minimax aggregate into the builder."""

    def fake_minimax(**kwargs: object) -> CampaignMinimaxRegretAssessment:
        return minimax

    monkeypatch.setattr(
        "kalhas.application.campaign_decision_comparison_runtime.build_campaign_minimax_regret",
        fake_minimax,
    )


def _tampered_minimax(
    minimax: CampaignMinimaxRegretAssessment, **updates: Any
) -> CampaignMinimaxRegretAssessment:
    """A tampered minimax aggregate (NamedTuple replace, no revalidation)."""
    return minimax._replace(**updates)


def _tampered_pareto(
    pareto: CampaignParetoDominanceAssessment, **updates: Any
) -> CampaignParetoDominanceAssessment:
    """A tampered Pareto aggregate (NamedTuple replace, no revalidation)."""
    return pareto._replace(**updates)


class TestPublicSurface:
    def test_exact_all(self) -> None:
        from kalhas.application import campaign_decision_comparison_runtime as module

        assert module.__all__ == ["build_campaign_strategy_comparison"]
        assert module.build_campaign_strategy_comparison.__module__ == (
            "kalhas.application.campaign_decision_comparison_runtime"
        )

    def test_builder_signature_is_keyword_only_and_clock_free(self) -> None:
        signature = inspect.signature(build_campaign_strategy_comparison)
        assert tuple(signature.parameters) == ("policy", "outcome_matrix")
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        for parameter in signature.parameters.values():
            assert parameter.name not in {"now", "clock", "timestamp", "wall_clock", "current_time"}
        assert signature.return_annotation == "CampaignStrategyComparison"

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
            "kalhas.application.campaign_decision_paired_comparison",
            "kalhas.application.campaign_decision_selection",
            "kalhas.contracts.v1.campaign_decision",
            "kalhas.contracts.v1.campaign_outcome",
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
        }
        for call in calls:
            assert not any(call.startswith(fragment) for fragment in ("store.", "put_")), call
            assert call not in forbidden_writes, call

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


class TestBuilderComposition:
    def test_paired_builder_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        real_paired = (
            "kalhas.application.campaign_decision_comparison_runtime."
            "build_ordered_objective_paired_comparisons"
        )

        def paired_wrapper(
            *,
            policy: CampaignDecisionPolicy,
            outcome_matrix: CampaignOutcomeDistributionMatrix,
        ) -> tuple[ObjectivePairedComparison, ...]:
            calls.append("paired")
            return build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=outcome_matrix
            )

        monkeypatch.setattr(real_paired, paired_wrapper)
        _comparison(_policy_3x2(), _matrix_3x2())
        assert calls == ["paired"]

    def test_minimax_called_exactly_once_after_paired_with_exact_tuple(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log: list[str] = []
        paired_result: dict[str, object] = {}
        minimax_argument: dict[str, object] = {}
        real_minimax = (
            "kalhas.application.campaign_decision_comparison_runtime.build_campaign_minimax_regret"
        )
        real_paired = (
            "kalhas.application.campaign_decision_comparison_runtime."
            "build_ordered_objective_paired_comparisons"
        )

        def paired_wrapper(
            *,
            policy: CampaignDecisionPolicy,
            outcome_matrix: CampaignOutcomeDistributionMatrix,
        ) -> tuple[ObjectivePairedComparison, ...]:
            log.append("paired")
            result = build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=outcome_matrix
            )
            paired_result["tuple"] = result
            return result

        def minimax_wrapper(
            *,
            policy: CampaignDecisionPolicy,
            outcome_matrix: CampaignOutcomeDistributionMatrix,
            paired_comparisons: tuple[ObjectivePairedComparison, ...],
        ) -> CampaignMinimaxRegretAssessment:
            log.append("minimax")
            minimax_argument["tuple"] = paired_comparisons
            return build_campaign_minimax_regret(
                policy=policy,
                outcome_matrix=outcome_matrix,
                paired_comparisons=paired_comparisons,
            )

        monkeypatch.setattr(real_paired, paired_wrapper)
        monkeypatch.setattr(real_minimax, minimax_wrapper)
        comparison = _comparison(_policy_3x2(), _matrix_3x2())
        assert log == ["paired", "minimax"]
        assert minimax_argument["tuple"] is paired_result["tuple"]
        assert comparison.paired_comparisons == cast(
            tuple[ObjectivePairedComparison, ...], paired_result["tuple"]
        )

    def test_repeated_calls_return_equal_artifacts(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        first = _comparison(policy, matrix)
        second = _comparison(policy, matrix)
        assert second == first
        assert second.model_dump() == first.model_dump()
        assert second.identifier == first.identifier
        assert second.content_hash == first.content_hash
        assert second.derived_at == first.derived_at
        assert second.paired_comparisons == first.paired_comparisons
        assert second.robustness_profiles == first.robustness_profiles

    def test_inputs_are_never_mutated(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        policy_before = policy.model_dump(mode="json")
        matrix_before = matrix.model_dump(mode="json")
        _comparison(policy, matrix)
        assert policy.model_dump(mode="json") == policy_before
        assert matrix.model_dump(mode="json") == matrix_before


class TestSourceIntegrity:
    def test_wrong_top_level_types(self) -> None:
        matrix = _matrix_3x2()
        with pytest.raises(ValueError, match="policy must be a CampaignDecisionPolicy"):
            build_campaign_strategy_comparison(policy=matrix, outcome_matrix=matrix)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="policy must be a CampaignDecisionPolicy"):
            build_campaign_strategy_comparison(policy={"x": 1}, outcome_matrix=matrix)  # type: ignore[arg-type]
        with pytest.raises(
            ValueError, match="outcome_matrix must be a CampaignOutcomeDistributionMatrix"
        ):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_policy_3x2())  # type: ignore[arg-type]

    def test_validator_bypassed_policy_rejected(self) -> None:
        policy = _tampered_policy(_policy_3x2(), minimum_sample_count=True)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=_matrix_3x2())

    def test_policy_metadata_non_finite_rejected(self) -> None:
        policy = _tampered_policy(_policy_3x2(), metadata={"value": float("nan")})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=_matrix_3x2())

    def test_validator_bypassed_matrix_rejected(self) -> None:
        matrix = _tampered_matrix(
            _matrix_3x2(), ordered_strategy_candidate_ids=("sc-a", "sc-b", "sc-a")
        )
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)
        matrix = _tampered_outcome_matrix(_matrix_3x2(), 0, weight=True)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("tenant_id", "tenant-2"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("world_version_id", "world-2"),
            ("evaluation_profile_id", "profile-2"),
            ("schema_version", "2.0.0"),
        ],
    )
    def test_every_policy_identifier_input_mismatch(self, field: str, value: str) -> None:
        policy = _policy_3x2().model_copy(update={field: value})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=_matrix_3x2())

    def test_policy_content_hash_mismatch(self) -> None:
        policy = _policy_3x2().model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=_matrix_3x2())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("campaign_id", "campaign-2"),
            ("world_version_id", "world-2"),
            ("runtime_version", "2.0.0"),
            ("evaluation_profile_id", "profile-2"),
            ("source_world_realization_matrix_id", "realization-matrix-2"),
            ("source_metric_observation_matrix_id", "observation-matrix-2"),
        ],
    )
    def test_every_matrix_identifier_input_mismatch(self, field: str, value: str) -> None:
        matrix = _matrix_3x2().model_copy(update={field: value})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)

    def test_matrix_content_hash_mismatch(self) -> None:
        matrix = _matrix_3x2().model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("tenant_id", "tenant-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "1" * 64),
            ("world_content_hash", "1" * 64),
            ("evaluation_profile_content_hash", "1" * 64),
        ],
    )
    def test_policy_matrix_cross_source_mismatch(self, field: str, value: str) -> None:
        tampered = _matrix_3x2().model_copy(update={field: value})
        matrix = _with_recomputed_matrix_hash(tampered)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)

    def test_runtime_mode_algorithm_tail_and_weight_mismatch(self) -> None:
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(
                policy=_policy_3x2(),
                outcome_matrix=_matrix_3x2().model_copy(update={"runtime_version": "2.0.0"}),
            )
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(
                policy=_policy_3x2(),
                outcome_matrix=_matrix_3x2().model_copy(
                    update={"comparison_mode": "parallel_conditions"}
                ),
            )
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(
                policy=_policy_3x2().model_copy(update={"algorithm_identifier": "other-algorithm"}),
                outcome_matrix=_matrix_3x2(),
            )
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(
                policy=_policy_3x2().model_copy(update={"tail_alpha": 0.5}),
                outcome_matrix=_matrix_3x2(),
            )
        tampered_snapshot = _policy_3x2().model_copy(
            update={
                "objective_weight_snapshots": (
                    _policy_3x2().objective_weight_snapshots[0].model_copy(update={"weight": 2.0}),
                )
            }
        )
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(
                policy=tampered_snapshot, outcome_matrix=_matrix_3x2()
            )

    def test_no_partial_output_on_rejection(self) -> None:
        policy = _tampered_policy(_policy_3x2(), minimum_sample_count=True)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=_matrix_3x2())
        matrix = _matrix_3x2().model_copy(update={"content_hash": "1" * 64})
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=matrix)


class TestAssembly:
    def test_exact_comparison_identifier(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        assert comparison.identifier == campaign_strategy_comparison_identifier(
            campaign_id=matrix.campaign_id,
            world_version_id=matrix.world_version_id,
            evaluation_profile_id=matrix.evaluation_profile_id,
            policy_id=policy.identifier,
            source_outcome_matrix_id=matrix.identifier,
        )

    def test_exact_content_hash(self) -> None:
        comparison = _comparison(_policy_3x2(), _matrix_3x2())
        assert comparison.content_hash == campaign_strategy_comparison_content_hash(comparison)

    def test_derived_at_copies_matrix_exactly(self) -> None:
        matrix = _matrix_3x2()
        comparison = _comparison(_policy_3x2(), matrix)
        assert comparison.derived_at == matrix.derived_at

    def test_source_references_and_copied_identity_fields(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        assert comparison.tenant_id == matrix.tenant_id
        assert comparison.schema_version == matrix.schema_version
        assert comparison.campaign_id == matrix.campaign_id
        assert comparison.scenario_id == matrix.scenario_id
        assert comparison.scenario_content_hash == matrix.scenario_content_hash
        assert comparison.world_version_id == matrix.world_version_id
        assert comparison.world_content_hash == matrix.world_content_hash
        assert comparison.runtime_version == "3.0.0"
        assert comparison.comparison_mode == "identical_conditions"
        assert comparison.algorithm_identifier == policy.algorithm_identifier
        assert comparison.policy_id == policy.identifier
        assert comparison.policy_content_hash == policy.content_hash
        assert comparison.tie_tolerance == policy.tie_tolerance
        assert comparison.minimum_sample_count == policy.minimum_sample_count
        assert comparison.source_outcome_matrix_id == matrix.identifier
        assert comparison.source_outcome_matrix_content_hash == matrix.content_hash
        assert comparison.ordered_strategy_candidate_ids == matrix.ordered_strategy_candidate_ids
        assert comparison.ordered_scenario_seed_ids == matrix.ordered_scenario_seed_ids
        assert comparison.ordered_objective_ids == matrix.ordered_objective_ids

    def test_paired_tuple_exact_equality(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        assert comparison.paired_comparisons == _pairs(policy, matrix)
        assert len(comparison.paired_comparisons) == 12

    def test_dominance_relations_exact_equality(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        minimax = _expected_minimax(policy, matrix)
        assert comparison.dominance_relations == minimax.pareto_assessment.dominance_relations
        assert len(comparison.dominance_relations) == 6

    def test_one_profile_per_strategy_in_exact_order(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        assert len(comparison.robustness_profiles) == 3
        assert [profile.strategy_position for profile in comparison.robustness_profiles] == [
            0,
            1,
            2,
        ]
        assert [profile.strategy_candidate_id for profile in comparison.robustness_profiles] == [
            "sc-a",
            "sc-b",
            "sc-c",
        ]
        for profile in comparison.robustness_profiles:
            assert isinstance(profile, StrategyRobustnessProfile)

    def test_every_profile_field_equals_accepted_assessment_source(self) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        comparison = _comparison(policy, matrix)
        minimax = _expected_minimax(policy, matrix)
        for position, profile in enumerate(comparison.robustness_profiles):
            evidence = minimax.pareto_assessment.evidence_assessment.strategy_assessments[position]
            dominance = minimax.pareto_assessment.strategy_assessments[position]
            regret = minimax.strategy_regret_assessments[position]
            assert profile.feasible == evidence.feasible
            assert profile.target_feasibility == evidence.target_feasibility
            assert (
                profile.target_achievement_probabilities
                == evidence.target_achievement_probabilities
            )
            assert profile.downside_evidence == evidence.downside_evidence
            assert profile.dominated_by == dominance.dominated_by
            assert profile.dominates == dominance.dominates
            assert profile.per_objective_weighted_regret == regret.per_objective_weighted_regret
            assert profile.per_seed_total_weighted_regrets == regret.per_seed_total_weighted_regrets
            assert profile.median_total_weighted_regret == regret.median_total_weighted_regret
            assert profile.p95_total_weighted_regret == regret.p95_total_weighted_regret
            assert profile.maximum_total_weighted_regret == regret.maximum_total_weighted_regret

    def test_optimization_only_fixture_assembly(self) -> None:
        policy, matrix = _policy_global_obj5(), _matrix_crossing()
        comparison = _comparison(policy, matrix)
        assert [profile.target_feasibility for profile in comparison.robustness_profiles] == [
            (),
            (),
        ]
        assert comparison.robustness_profiles[0].downside_evidence[0].objective_id == "obj-5"

    def test_not_evaluated_minimax_still_assembles(self) -> None:
        comparison = _comparison(_policy_insufficient(), _matrix_2x1())
        assert len(comparison.robustness_profiles) == 2
        zero_feasible = _comparison(_policy_global_threshold_1(), _matrix_zero_feasible())
        assert len(zero_feasible.robustness_profiles) == 2
        assert all(not profile.feasible for profile in zero_feasible.robustness_profiles)

    def test_complete_artifact_passes_strict_validation(self) -> None:
        comparison = _comparison(_policy_3x2(), _matrix_3x2())
        revalidated = CampaignStrategyComparison.model_validate(
            comparison.model_dump(mode="python"), strict=True
        )
        assert revalidated == comparison
        json_round = CampaignStrategyComparison.model_validate_json(comparison.model_dump_json())
        assert json_round == comparison

    def test_content_hash_changes_under_each_material_mutation(self) -> None:
        comparison = _comparison(_policy_3x2(), _matrix_3x2())
        original_hash = comparison.content_hash
        derived_at = datetime(2026, 8, 17, tzinfo=UTC)
        top_level_mutations: list[tuple[str, object]] = [
            ("identifier", "campaign-strategy-comparison-0000000000000000"),
            ("tenant_id", "tenant-2"),
            ("schema_version", "2.0.0"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "1" * 64),
            ("world_version_id", "world-2"),
            ("world_content_hash", "1" * 64),
            ("policy_id", "policy-2"),
            ("policy_content_hash", "1" * 64),
            ("tie_tolerance", 0.1),
            ("minimum_sample_count", 5),
            ("source_outcome_matrix_id", "matrix-2"),
            ("source_outcome_matrix_content_hash", "1" * 64),
            ("ordered_strategy_candidate_ids", ("sc-other", "sc-b", "sc-c")),
            ("ordered_scenario_seed_ids", ("seed-x", "seed-1", "seed-2")),
            ("ordered_objective_ids", ("obj-x", "obj-2")),
            ("derived_at", derived_at),
        ]
        for field, value in top_level_mutations:
            variant = comparison.model_copy(update={field: value})
            assert campaign_strategy_comparison_content_hash(variant) != original_hash, field

        paired = comparison.paired_comparisons
        mutated_paired = tuple(
            [paired[0].model_copy(update={"win_count": paired[0].win_count + 1})] + list(paired[1:])
        )
        assert (
            campaign_strategy_comparison_content_hash(
                comparison.model_copy(update={"paired_comparisons": mutated_paired})
            )
            != original_hash
        )

        relations = comparison.dominance_relations
        mutated_relations = tuple(
            [relations[0].model_copy(update={"dominates": not relations[0].dominates})]
            + list(relations[1:])
        )
        assert (
            campaign_strategy_comparison_content_hash(
                comparison.model_copy(update={"dominance_relations": mutated_relations})
            )
            != original_hash
        )

        profiles = comparison.robustness_profiles
        mutated_profiles = tuple(
            [profiles[0].model_copy(update={"feasible": not profiles[0].feasible})]
            + list(profiles[1:])
        )
        assert (
            campaign_strategy_comparison_content_hash(
                comparison.model_copy(update={"robustness_profiles": mutated_profiles})
            )
            != original_hash
        )

    def test_input_and_mid_result_mutation_never_occurs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        policy_before = policy.model_dump(mode="json")
        matrix_before = matrix.model_dump(mode="json")
        captured_paired: dict[str, object] = {}
        captured_minimax: dict[str, object] = {}
        real_minimax = (
            "kalhas.application.campaign_decision_comparison_runtime.build_campaign_minimax_regret"
        )
        real_paired = (
            "kalhas.application.campaign_decision_comparison_runtime."
            "build_ordered_objective_paired_comparisons"
        )

        def paired_wrapper(
            *,
            policy: CampaignDecisionPolicy,
            outcome_matrix: CampaignOutcomeDistributionMatrix,
        ) -> tuple[ObjectivePairedComparison, ...]:
            result = build_ordered_objective_paired_comparisons(
                policy=policy, outcome_matrix=outcome_matrix
            )
            captured_paired["result"] = result
            return result

        def minimax_wrapper(
            *,
            policy: CampaignDecisionPolicy,
            outcome_matrix: CampaignOutcomeDistributionMatrix,
            paired_comparisons: tuple[ObjectivePairedComparison, ...],
        ) -> CampaignMinimaxRegretAssessment:
            result = build_campaign_minimax_regret(
                policy=policy,
                outcome_matrix=outcome_matrix,
                paired_comparisons=paired_comparisons,
            )
            captured_minimax["result"] = result
            return result

        monkeypatch.setattr(real_paired, paired_wrapper)
        monkeypatch.setattr(real_minimax, minimax_wrapper)
        _comparison(policy, matrix)
        assert policy.model_dump(mode="json") == policy_before
        assert matrix.model_dump(mode="json") == matrix_before
        captured_paired_value = cast(
            tuple[ObjectivePairedComparison, ...], captured_paired["result"]
        )
        expected_paired = _pairs(policy, matrix)
        assert tuple(record.model_dump(mode="json") for record in captured_paired_value) == tuple(
            record.model_dump(mode="json") for record in expected_paired
        )
        captured_minimax_value = cast(CampaignMinimaxRegretAssessment, captured_minimax["result"])
        assert captured_minimax_value == _expected_minimax(policy, matrix)


class TestInjectedTampering:
    def _tampered_assessment(
        self,
    ) -> tuple[
        CampaignDecisionPolicy, CampaignOutcomeDistributionMatrix, CampaignMinimaxRegretAssessment
    ]:
        policy, matrix = _policy_3x2(), _matrix_3x2()
        return policy, matrix, _expected_minimax(policy, matrix)

    def _expect_rejection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        minimax: CampaignMinimaxRegretAssessment,
    ) -> None:
        _inject_minimax(monkeypatch, minimax)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())

    def test_wrong_evidence_strategy_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        evidence = pareto.evidence_assessment._replace(
            strategy_assessments=pareto.evidence_assessment.strategy_assessments[:-1]
        )
        tampered = _tampered_minimax(
            minimax, pareto_assessment=_tampered_pareto(pareto, evidence_assessment=evidence)
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_dominance_strategy_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto, strategy_assessments=pareto.strategy_assessments[:-1]
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_regret_strategy_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        tampered = _tampered_minimax(
            minimax, strategy_regret_assessments=minimax.strategy_regret_assessments[:-1]
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_regret_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        tampered_assessment = assessments[1]._replace(strategy_position=0)
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple(
                [assessments[0], tampered_assessment] + list(assessments[2:])
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_dominance_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        assessments = pareto.strategy_assessments
        tampered_assessment = assessments[0]._replace(strategy_candidate_id="sc-other")
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                strategy_assessments=tuple([tampered_assessment] + list(assessments[1:])),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_feasibility_mismatch_between_evidence_and_dominance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        assessments = pareto.strategy_assessments
        tampered_assessment = assessments[0]._replace(feasible=not assessments[0].feasible)
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                strategy_assessments=tuple([tampered_assessment] + list(assessments[1:])),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_missing_dominance_relation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto, dominance_relations=pareto.dominance_relations[:-1]
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_reordered_dominance_relation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        relations = pareto.dominance_relations
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                dominance_relations=tuple([relations[1], relations[0]] + list(relations[2:])),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_relation_status_disagrees_with_paired_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        relations = pareto.dominance_relations
        relation = relations[0]
        status = relation.per_objective_status[0]
        tampered_status = status.model_copy(update={"win_count": status.win_count + 1})
        tampered_relation = relation.model_copy(
            update={
                "per_objective_status": tuple(
                    [tampered_status] + list(relation.per_objective_status[1:])
                )
            }
        )
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                dominance_relations=tuple([tampered_relation] + list(relations[1:])),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_incomplete_candidate_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy, matrix = _policy_boundary(), _matrix_boundary()
        minimax = _expected_minimax(policy, matrix)
        # The genuine candidate set holds BOTH strategies in a two-way
        # minimax tie with no unique winner, so omitting one candidate
        # would manufacture a false singleton preference (tie set
        # ("sc-a",) and unique "sc-a") that the complete factual
        # derivation does not support.
        assert minimax.minimax_candidate_ids == ("sc-a", "sc-b")
        assert minimax.minimax_tie_strategy_ids == ("sc-a", "sc-b")
        assert minimax.unique_minimax_strategy_id is None
        pareto = minimax.pareto_assessment
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto, non_dominated_feasible_strategy_ids=("sc-a",)
            ),
            minimax_candidate_ids=("sc-a",),
            minimax_tie_strategy_ids=("sc-a",),
            unique_minimax_strategy_id="sc-a",
        )
        _inject_minimax(monkeypatch, tampered)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)

    def test_candidate_ids_not_authoritative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        tampered = _tampered_minimax(minimax, minimax_candidate_ids=("sc-b",))
        self._expect_rejection(monkeypatch, tampered)

    @pytest.mark.parametrize(
        "update",
        [
            {"minimax_evaluated": False},
            {"best_maximum_total_weighted_regret": 0.5},
            {"minimax_tie_strategy_ids": ()},
            {"unique_minimax_strategy_id": None},
            {"unique_minimax_strategy_id": "sc-b"},
        ],
    )
    def test_inconsistent_minimax_tie_unique_fields(
        self, monkeypatch: pytest.MonkeyPatch, update: dict[str, object]
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        tampered = _tampered_minimax(minimax, **update)
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_objective_regret_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        records = assessments[0].per_objective_weighted_regret
        tampered_assessment = assessments[0]._replace(
            per_objective_weighted_regret=tuple([records[1], records[0]])
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple([tampered_assessment] + list(assessments[1:])),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_regret_objective_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        records = assessments[0].per_objective_weighted_regret
        tampered_record = records[0].model_copy(update={"objective_id": "obj-x"})
        tampered_assessment = assessments[0]._replace(
            per_objective_weighted_regret=tuple([tampered_record] + list(records[1:]))
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple([tampered_assessment] + list(assessments[1:])),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_seed_total_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        tampered_assessment = assessments[0]._replace(
            per_seed_total_weighted_regrets=assessments[0].per_seed_total_weighted_regrets[:-1]
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple([tampered_assessment] + list(assessments[1:])),
        )
        self._expect_rejection(monkeypatch, tampered)

    @pytest.mark.parametrize(
        "update",
        [
            {"maximum_total_weighted_regret": 1.0},
            {"median_total_weighted_regret": 1e9},
            {"p95_total_weighted_regret": -1.0},
        ],
    )
    def test_wrong_regret_aggregate(
        self, monkeypatch: pytest.MonkeyPatch, update: dict[str, object]
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        tampered_assessment = cast(Any, assessments[0])._replace(**update)
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple([tampered_assessment] + list(assessments[1:])),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_wrong_supporting_evidence_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        evidence = pareto.evidence_assessment
        assessments = evidence.strategy_assessments
        downside = assessments[0].downside_evidence
        tampered_assessment = assessments[0]._replace(downside_evidence=tuple(reversed(downside)))
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                evidence_assessment=evidence._replace(
                    strategy_assessments=tuple([tampered_assessment] + list(assessments[1:]))
                ),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_target_evidence_not_exact_targeted_subset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        pareto = minimax.pareto_assessment
        evidence = pareto.evidence_assessment
        assessments = evidence.strategy_assessments
        tampered_assessment = assessments[0]._replace(
            target_feasibility=assessments[0].target_feasibility[:1],
            target_achievement_probabilities=assessments[0].target_achievement_probabilities[:1],
        )
        tampered = _tampered_minimax(
            minimax,
            pareto_assessment=_tampered_pareto(
                pareto,
                evidence_assessment=evidence._replace(
                    strategy_assessments=tuple([tampered_assessment] + list(assessments[1:]))
                ),
            ),
        )
        self._expect_rejection(monkeypatch, tampered)

    def test_generated_profile_rejection_becomes_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        # sc-c (position 2) is infeasible and never a minimax candidate,
        # so tampering its regret assessment leaves every earlier minimax
        # consistency check valid (best/tie/unique fields are untouched).
        # The aggregates stay internally consistent for the trust boundary
        # (maximum equals the exact max, median/p95 within the extrema),
        # but the negative per-seed total violates the robustness-profile
        # contract, so the rejection happens at the profile boundary.
        tampered_assessment = assessments[2]._replace(
            per_seed_total_weighted_regrets=(-1.0, 0.5, 1.0),
            median_total_weighted_regret=0.5,
            p95_total_weighted_regret=1.0,
            maximum_total_weighted_regret=1.0,
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple(list(assessments[:2]) + [tampered_assessment]),
        )
        _inject_minimax(monkeypatch, tampered)
        with pytest.raises(ValueError, match="generated robustness profile violates"):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())

    def test_late_final_profile_failure_gives_no_partial_artifact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, minimax = self._tampered_assessment()
        assessments = minimax.strategy_regret_assessments
        # Tamper the LAST strategy's regret assessment so the failure
        # occurs at the final profile construction; nothing may escape.
        tampered_assessment = assessments[-1]._replace(
            per_seed_total_weighted_regrets=(-1.0, 0.5, 1.0),
            median_total_weighted_regret=0.5,
            p95_total_weighted_regret=1.0,
            maximum_total_weighted_regret=1.0,
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple(list(assessments[:-1]) + [tampered_assessment]),
        )
        _inject_minimax(monkeypatch, tampered)
        with pytest.raises(ValueError, match="generated robustness profile violates"):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())

    def test_non_finite_minimax_boundary_raises_overflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A very large finite policy tie tolerance plus a coherent
        # injected aggregate whose candidate maxima are all 1e308 makes
        # best + tie_tolerance overflow to infinity; the trust
        # boundary's explicit finiteness check must raise OverflowError
        # (never a ValueError, and never a repaired boundary).
        policy = _policy_3x2(tie_tolerance=1e308)
        matrix = _matrix_3x2()
        minimax = _expected_minimax(policy, matrix)
        # With the huge tolerance every paired delta is a tie, so the
        # genuine assessment holds both feasible candidates in an
        # inclusive tie with no unique winner.
        assert minimax.minimax_candidate_ids == ("sc-a", "sc-b")
        assert minimax.minimax_tie_strategy_ids == ("sc-a", "sc-b")
        assert minimax.unique_minimax_strategy_id is None
        assessments = minimax.strategy_regret_assessments
        tampered_candidates = tuple(
            assessment._replace(
                per_seed_total_weighted_regrets=(1e308, 1e308, 1e308),
                median_total_weighted_regret=1e308,
                p95_total_weighted_regret=1e308,
                maximum_total_weighted_regret=1e308,
            )
            for assessment in assessments[:2]
        )
        tampered = _tampered_minimax(
            minimax,
            strategy_regret_assessments=tuple(list(tampered_candidates) + list(assessments[2:])),
            best_maximum_total_weighted_regret=1e308,
            minimax_tie_strategy_ids=("sc-a", "sc-b"),
            unique_minimax_strategy_id=None,
        )
        _inject_minimax(monkeypatch, tampered)
        with pytest.raises(OverflowError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)

    def test_not_evaluated_fields_must_stay_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        policy, matrix = _policy_insufficient(), _matrix_2x1()
        minimax = _expected_minimax(policy, matrix)
        assert not minimax.minimax_evaluated
        tampered = _tampered_minimax(minimax, best_maximum_total_weighted_regret=0.0)
        _inject_minimax(monkeypatch, tampered)
        with pytest.raises(ValueError):
            build_campaign_strategy_comparison(policy=policy, outcome_matrix=matrix)


class TestErrorPropagation:
    def test_paired_builder_value_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_paired(**kwargs: object) -> tuple[ObjectivePairedComparison, ...]:
            raise ValueError("paired boom")

        monkeypatch.setattr(
            "kalhas.application.campaign_decision_comparison_runtime."
            "build_ordered_objective_paired_comparisons",
            failing_paired,
        )
        with pytest.raises(ValueError, match="paired boom"):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())

    def test_minimax_builder_value_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_minimax(**kwargs: object) -> CampaignMinimaxRegretAssessment:
            raise ValueError("minimax boom")

        monkeypatch.setattr(
            "kalhas.application.campaign_decision_comparison_runtime.build_campaign_minimax_regret",
            failing_minimax,
        )
        with pytest.raises(ValueError, match="minimax boom"):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())

    def test_overflow_error_propagates_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_minimax(**kwargs: object) -> CampaignMinimaxRegretAssessment:
            raise OverflowError("overflow boom")

        monkeypatch.setattr(
            "kalhas.application.campaign_decision_comparison_runtime.build_campaign_minimax_regret",
            failing_minimax,
        )
        with pytest.raises(OverflowError, match="overflow boom"):
            build_campaign_strategy_comparison(policy=_policy_3x2(), outcome_matrix=_matrix_3x2())


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
