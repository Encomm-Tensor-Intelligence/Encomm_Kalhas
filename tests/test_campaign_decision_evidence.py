"""Tests for the pure evidence-sufficiency and strategy-feasibility layer.

Tests for ``kalhas/application/campaign_decision_evidence.py``: the
single public builder that transforms one verified
``CampaignOutcomeDistributionMatrix`` and one matching
``CampaignDecisionPolicy`` into the complete immutable
``CampaignDecisionEvidenceAssessment`` - the recorded seed-count
sufficiency fact, the per-strategy hard-gate feasibility flag with the
factual per-targeted-objective threshold evidence, the copied
target-achievement probabilities, and the copied full-objective
downside evidence - together with the strict detached revalidation of
both sources, every cross-source check, the target-coverage rules, and
the purity/boundary guarantees.

Valid fixtures use the real Phase 26 outcome contracts/builders (the
accepted ``build_strategy_objective_outcome`` primitive plus strict
contract validation); no production statistical formula is duplicated
inside the tests. Threshold-boundary assertions use the exact IEEE
comparison semantics (exact equality at the boundary, one adjacent
representable float step on either side).
"""

from __future__ import annotations

import ast
import inspect
import math
import re
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_decision_evidence import (
    CampaignDecisionEvidenceAssessment,
    StrategyFeasibilityAssessment,
    build_campaign_decision_evidence,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
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
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_decision_evidence.py"
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
OBJ4_BINDING = _binding(
    objective_id="obj-4",
    metric_id="m-4",
    direction="minimize",
    target=None,
    weight=0.25,
    normalization_scale=5.0,
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
        "identifier": "matrix-1",
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
        "content_hash": "f" * 64,
        "derived_at": "2026-08-15T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _matrix_2x1(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one minimize objective x three seeds.

    obj-1 minimize (target 100, scale 100): sc-a (90, 95, 99.5) and
    sc-b (100, 100, 100) - both achieve 3/3, empirical probability 1.0.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 95, 99.5),
                ("sc-b", "obj-1"): (100, 100, 100),
            },
            **overrides,
        )
    )


def _matrix_3x2(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Three strategies x two targeted objectives x three seeds.

    obj-1 minimize (scale 100): sc-a (90, 95, 99), sc-b (100, 100, 100),
    sc-c (150, 160, 170) - probabilities 1.0 / 1.0 / 0.0.
    obj-2 maximize (scale 10): sc-a (60, 55, 50), sc-b (50, 50, 50),
    sc-c (50, 50, 30) - probabilities 1.0 / 1.0 / 2/3.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
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
    )


def _matrix_4obj(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two targeted + one optimization-only objective x three seeds.

    obj-1 minimize (probabilities 1.0 / 1.0), obj-2 maximize
    (probabilities 1.0 / 1.0), obj-4 optimization-only minimize.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING, "obj-4": OBJ4_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 95, 99),
                ("sc-b", "obj-1"): (100, 100, 100),
                ("sc-a", "obj-2"): (60, 55, 50),
                ("sc-b", "obj-2"): (50, 50, 50),
                ("sc-a", "obj-4"): (10, 20, 30),
                ("sc-b", "obj-4"): (5, 5, 5),
            },
            **overrides,
        )
    )


def _matrix_probs(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x two targeted objectives x four seeds.

    Exact binary probabilities: sc-a obj-1 3/4 = 0.75, sc-b obj-1 2/4 =
    0.5, sc-a obj-2 2/4 = 0.5, sc-b obj-2 1/4 = 0.25.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2", "seed-3"),
            bindings={"obj-1": OBJ1_BINDING, "obj-2": OBJ2_BINDING},
            values={
                ("sc-a", "obj-1"): (90, 90, 90, 110),
                ("sc-b", "obj-1"): (90, 90, 110, 110),
                ("sc-a", "obj-2"): (60, 60, 40, 40),
                ("sc-b", "obj-2"): (60, 40, 40, 40),
            },
            **overrides,
        )
    )


def _matrix_opt_only(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """Two strategies x one optimization-only objective x three seeds."""
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a", "sc-b"),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-4": OBJ4_BINDING},
            values={
                ("sc-a", "obj-4"): (10, 20, 30),
                ("sc-b", "obj-4"): (5, 5, 5),
            },
            **overrides,
        )
    )


def _matrix_ones_strategy(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """One structurally valid strategy x one objective x three seeds.

    The matrix contract permits a single strategy; the builder must
    reject it because the evidence assessment requires at least two.
    """
    return CampaignOutcomeDistributionMatrix.model_validate(
        _matrix_payload(
            strategies=("sc-a",),
            seeds=("seed-0", "seed-1", "seed-2"),
            bindings={"obj-1": OBJ1_BINDING},
            values={("sc-a", "obj-1"): (90, 95, 99)},
            **overrides,
        )
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
        "identifier": "policy-1",
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
        "identifier": "policy-1",
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


def _apply_overrides(payload: dict[str, Any], overrides: dict[str, object]) -> None:
    """Merge caller overrides into a policy payload.

    Translates the helper-level parameter names into the exact contract
    field names: ``requirements`` (a tuple of objective/threshold
    pairs) becomes ``objective_target_requirements``, ``threshold``
    becomes ``minimum_target_achievement_probability``, and
    ``hard_gates`` becomes ``all_targeted_objectives_are_hard_gates``.
    """
    for key, value in overrides.items():
        if key == "requirements":
            payload["objective_target_requirements"] = [
                {
                    "objective_id": objective_id,
                    "minimum_target_achievement_probability": threshold,
                }
                for objective_id, threshold in cast(tuple[tuple[str, float], ...], value)
            ]
        elif key == "threshold":
            payload["minimum_target_achievement_probability"] = value
        elif key == "hard_gates":
            payload["all_targeted_objectives_are_hard_gates"] = value
        else:
            payload[key] = value


def _policy(**overrides: object) -> CampaignDecisionPolicy:
    """One validated per-objective policy matching the 2x1 matrix by default."""
    payload = _policy_payload()
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_global(**overrides: object) -> CampaignDecisionPolicy:
    """One validated global-mode policy matching the 2x1 matrix by default."""
    payload = _policy_global_payload()
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_3x2(**overrides: object) -> CampaignDecisionPolicy:
    """One validated per-objective policy matching the 3x2 matrix."""
    payload = _policy_payload(
        requirements=(("obj-1", 0.4), ("obj-2", 0.4)),
        weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
    )
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_4obj(**overrides: object) -> CampaignDecisionPolicy:
    """One validated per-objective policy matching the 4-objective matrix."""
    payload = _policy_payload(
        requirements=(("obj-1", 0.4), ("obj-2", 0.4)),
        weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5), ("obj-4", 0.25)),
    )
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_probs(**overrides: object) -> CampaignDecisionPolicy:
    """One validated per-objective policy matching the K=4 probability matrix."""
    payload = _policy_payload(
        requirements=(("obj-1", 0.75), ("obj-2", 0.5)),
        weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
        minimum_sample_count=4,
    )
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_probs_global(**overrides: object) -> CampaignDecisionPolicy:
    """One validated global-mode policy matching the K=4 probability matrix."""
    payload = _policy_global_payload(
        threshold=0.4,
        weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
        minimum_sample_count=4,
    )
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


def _policy_opt_only(**overrides: object) -> CampaignDecisionPolicy:
    """One validated global-mode policy matching the optimization-only matrix."""
    payload = _policy_global_payload(
        threshold=0.5,
        weight_snapshots=(("obj-4", 0.25),),
    )
    _apply_overrides(payload, overrides)
    return CampaignDecisionPolicy.model_validate(payload)


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


def _assessment_for(
    assessments: tuple[StrategyFeasibilityAssessment, ...], strategy_id: str
) -> StrategyFeasibilityAssessment:
    """The single strategy assessment of one strategy."""
    matches = [
        assessment for assessment in assessments if assessment.strategy_candidate_id == strategy_id
    ]
    assert len(matches) == 1
    return matches[0]


def _feasibility_for(
    assessment: StrategyFeasibilityAssessment, objective_id: str
) -> ObjectiveFeasibilityEvidence:
    """The single target-feasibility record of one objective."""
    matches = [
        record for record in assessment.target_feasibility if record.objective_id == objective_id
    ]
    assert len(matches) == 1
    return matches[0]


class TestPublicSurface:
    def test_exact_all(self) -> None:
        from kalhas.application import campaign_decision_evidence as module

        assert module.__all__ == [
            "CampaignDecisionEvidenceAssessment",
            "StrategyFeasibilityAssessment",
            "build_campaign_decision_evidence",
        ]
        assert module.build_campaign_decision_evidence.__module__ == (
            "kalhas.application.campaign_decision_evidence"
        )
        assert module.CampaignDecisionEvidenceAssessment.__module__ == (
            "kalhas.application.campaign_decision_evidence"
        )
        assert module.StrategyFeasibilityAssessment.__module__ == (
            "kalhas.application.campaign_decision_evidence"
        )

    def test_builder_signature_is_keyword_only_and_clock_free(self) -> None:
        signature = inspect.signature(build_campaign_decision_evidence)
        assert tuple(signature.parameters) == ("policy", "outcome_matrix")
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        for parameter in signature.parameters.values():
            assert parameter.name not in {"now", "clock", "timestamp", "wall_clock", "current_time"}

    def test_namedtuple_results_are_immutable(self) -> None:
        result = build_campaign_decision_evidence(policy=_policy(), outcome_matrix=_matrix_2x1())
        assert isinstance(result, tuple)
        assert isinstance(result, CampaignDecisionEvidenceAssessment)
        assert CampaignDecisionEvidenceAssessment._fields == (
            "recorded_sample_count",
            "minimum_sample_count",
            "sufficient",
            "strategy_assessments",
        )
        assert StrategyFeasibilityAssessment._fields == (
            "strategy_position",
            "strategy_candidate_id",
            "feasible",
            "target_feasibility",
            "target_achievement_probabilities",
            "downside_evidence",
        )
        assert isinstance(result.strategy_assessments[0], StrategyFeasibilityAssessment)
        with pytest.raises(AttributeError):
            result.sufficient = True  # type: ignore[misc]
        with pytest.raises(AttributeError):
            result.strategy_assessments[0].feasible = True  # type: ignore[misc]

    def test_evidence_records_are_the_exact_contract_models(self) -> None:
        result = build_campaign_decision_evidence(policy=_policy(), outcome_matrix=_matrix_2x1())
        assessment = result.strategy_assessments[0]
        assert type(assessment.target_feasibility[0]) is ObjectiveFeasibilityEvidence
        assert type(assessment.target_achievement_probabilities[0]) is ObjectiveProbabilityEvidence
        assert type(assessment.downside_evidence[0]) is ObjectiveDownsideEvidence

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
        assert "hash" not in calls
        assert not any(chain.startswith("random.") for chain in calls)

    def test_no_store_api_identity_hash_query_or_activity_surface(self) -> None:
        tree = _module_tree()
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names
        assert "api" not in names
        assert "identity" not in names
        assert "query" not in names
        assert "activity" not in names
        module_paths = _imported_module_paths(tree)
        forbidden_imports = {
            "kalhas.application.in_memory_store",
            "kalhas.application.campaign_decision_identity",
            "kalhas.application.campaign_decision_errors",
            "kalhas.application.campaign_decision_policy_service",
            "kalhas.application.campaign_decision_statistics",
            "kalhas.application.campaign_decision_paired_comparison",
            "kalhas.application.campaign_outcome_identity",
            "kalhas.application.campaign_outcome_runtime",
            "kalhas.application.campaign_outcome_statistics",
            "kalhas.application.campaign_outcome_errors",
            "kalhas.application.campaign_outcome_matrix_runtime",
            "kalhas.application.campaign_outcome_query_service",
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
        for call in calls:
            assert not call.startswith("store."), call
            assert call not in {"put_", "record_operational_activity", "record_activity"}, call

    def test_no_decision_surface_symbols(self) -> None:
        forbidden = _DECISION_SURFACE_PATTERN
        tree = _module_tree()
        symbols = set(_imported_symbols(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.add(node.name)
                symbols.update(argument.arg for argument in node.args.args)
            if isinstance(node, ast.ClassDef):
                symbols.add(node.name)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden decision symbol {symbol!r}"

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

    def test_repeated_calls_produce_equal_assessments(self) -> None:
        policy = _policy_4obj()
        matrix = _matrix_4obj()
        first = build_campaign_decision_evidence(policy=policy, outcome_matrix=matrix)
        second = build_campaign_decision_evidence(policy=policy, outcome_matrix=matrix)
        assert first == second
        assert first._asdict() == second._asdict()
        assert tuple(
            record.model_dump(mode="json")
            for assessment in first.strategy_assessments
            for record in assessment.downside_evidence
        ) == tuple(
            record.model_dump(mode="json")
            for assessment in second.strategy_assessments
            for record in assessment.downside_evidence
        )

    def test_input_artifacts_unchanged(self) -> None:
        matrix = _matrix_4obj()
        policy = _policy_4obj()
        matrix_before = matrix.model_dump(mode="python")
        policy_before = policy.model_dump(mode="python")
        build_campaign_decision_evidence(policy=policy, outcome_matrix=matrix)
        assert matrix.model_dump(mode="python") == matrix_before
        assert policy.model_dump(mode="python") == policy_before


class TestEvidenceSufficiency:
    def test_below_minimum_returns_complete_assessment_no_exception(self) -> None:
        policy = _policy(minimum_sample_count=4)
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_2x1())
        assert result.recorded_sample_count == 3
        assert result.minimum_sample_count == 4
        assert result.sufficient is False

    def test_exactly_minimum_is_sufficient(self) -> None:
        policy = _policy(minimum_sample_count=3)
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_2x1())
        assert result.recorded_sample_count == 3
        assert result.minimum_sample_count == 3
        assert result.sufficient is True

    def test_above_minimum_is_sufficient(self) -> None:
        policy = _policy(minimum_sample_count=2)
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_2x1())
        assert result.recorded_sample_count == 3
        assert result.minimum_sample_count == 2
        assert result.sufficient is True

    def test_below_minimum_still_contains_complete_factual_evidence(self) -> None:
        matrix = _matrix_3x2()
        insufficient = build_campaign_decision_evidence(
            policy=_policy_3x2(minimum_sample_count=100), outcome_matrix=matrix
        )
        sufficient = build_campaign_decision_evidence(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        assert insufficient.sufficient is False
        assert sufficient.sufficient is True
        assert len(insufficient.strategy_assessments) == 3
        assert insufficient.strategy_assessments == sufficient.strategy_assessments
        for strategy_position, assessment in enumerate(insufficient.strategy_assessments):
            assert [record.objective_id for record in assessment.target_feasibility] == [
                "obj-1",
                "obj-2",
            ]
            assert len(assessment.downside_evidence) == 2
            for objective_position, record in enumerate(assessment.target_feasibility):
                expected = matrix.outcomes[
                    strategy_position * 2 + objective_position
                ].empirical_target_achievement_probability
                assert record.observed_probability == expected


class TestThresholdBoundaries:
    def test_observed_exactly_equal_to_threshold_passes(self) -> None:
        # sc-a obj-1 probability 0.75, obj-2 probability 0.5.
        result = build_campaign_decision_evidence(
            policy=_policy_probs(), outcome_matrix=_matrix_probs()
        )
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        assert _feasibility_for(sc_a, "obj-1").passed is True
        assert _feasibility_for(sc_a, "obj-2").passed is True
        assert _feasibility_for(sc_a, "obj-1").observed_probability == 0.75
        assert _feasibility_for(sc_a, "obj-2").observed_probability == 0.5

    def test_threshold_one_representable_step_below_passes(self) -> None:
        below = math.nextafter(0.75, -math.inf)
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", below), ("obj-2", 0.5)),
                weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
                minimum_sample_count=4,
            )
        )
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_probs())
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        record = _feasibility_for(sc_a, "obj-1")
        assert record.threshold == below
        assert below <= 0.75
        assert record.passed is True

    def test_threshold_one_representable_step_above_fails(self) -> None:
        above = math.nextafter(0.75, math.inf)
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", above), ("obj-2", 0.5)),
                weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
                minimum_sample_count=4,
            )
        )
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_probs())
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        record = _feasibility_for(sc_a, "obj-1")
        assert record.threshold == above
        assert above > 0.75
        assert record.passed is False

    def test_global_threshold_applied_to_every_targeted_objective(self) -> None:
        policy = _policy_probs_global(threshold=0.4)
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_probs())
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        sc_b = _assessment_for(result.strategy_assessments, "sc-b")
        for record in sc_a.target_feasibility:
            assert record.threshold == 0.4
            assert record.passed is True
        # sc-b obj-1 0.5 passes, obj-2 0.25 fails under the same global threshold.
        assert [record.threshold for record in sc_b.target_feasibility] == [0.4, 0.4]
        assert [record.passed for record in sc_b.target_feasibility] == [True, False]

    def test_per_objective_thresholds_applied_in_exact_objective_order(self) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", 0.8), ("obj-2", 0.4)),
                weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
                minimum_sample_count=4,
            )
        )
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_probs())
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        assert [record.objective_id for record in sc_a.target_feasibility] == ["obj-1", "obj-2"]
        assert [record.threshold for record in sc_a.target_feasibility] == [0.8, 0.4]

    def test_mixed_pass_fail_across_targeted_objectives(self) -> None:
        policy = CampaignDecisionPolicy.model_validate(
            _policy_payload(
                requirements=(("obj-1", 0.8), ("obj-2", 0.4)),
                weight_snapshots=(("obj-1", 1.0), ("obj-2", 0.5)),
                minimum_sample_count=4,
            )
        )
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_probs())
        sc_a = _assessment_for(result.strategy_assessments, "sc-a")
        assert [record.passed for record in sc_a.target_feasibility] == [False, True]


class TestHardGates:
    def test_gates_enabled_all_passed_feasible(self) -> None:
        result = build_campaign_decision_evidence(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        assert _assessment_for(result.strategy_assessments, "sc-a").feasible is True
        assert _assessment_for(result.strategy_assessments, "sc-b").feasible is True

    def test_gates_enabled_one_failure_infeasible(self) -> None:
        result = build_campaign_decision_evidence(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        sc_c = _assessment_for(result.strategy_assessments, "sc-c")
        assert [record.passed for record in sc_c.target_feasibility] == [False, True]
        assert sc_c.feasible is False

    def test_gates_disabled_factual_failure_stays_feasible_with_passed_false(self) -> None:
        policy = _policy_3x2(hard_gates=False)
        result = build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_3x2())
        sc_c = _assessment_for(result.strategy_assessments, "sc-c")
        assert [record.passed for record in sc_c.target_feasibility] == [False, True]
        assert sc_c.feasible is True

    def test_all_optimization_only_objectives_vacuous_feasibility(self) -> None:
        for hard_gates in (True, False):
            policy = _policy_opt_only(hard_gates=hard_gates)
            result = build_campaign_decision_evidence(
                policy=policy, outcome_matrix=_matrix_opt_only()
            )
            assert result.sufficient is True
            for assessment in result.strategy_assessments:
                assert assessment.target_feasibility == ()
                assert assessment.target_achievement_probabilities == ()
                assert assessment.feasible is True

    def test_no_hard_gates_never_suppress_factual_evidence(self) -> None:
        enabled = build_campaign_decision_evidence(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        disabled = build_campaign_decision_evidence(
            policy=_policy_3x2(hard_gates=False), outcome_matrix=_matrix_3x2()
        )
        for enabled_assessment, disabled_assessment in zip(
            enabled.strategy_assessments, disabled.strategy_assessments, strict=True
        ):
            assert disabled_assessment.target_feasibility == enabled_assessment.target_feasibility
            assert (
                disabled_assessment.target_achievement_probabilities
                == enabled_assessment.target_achievement_probabilities
            )
            assert disabled_assessment.downside_evidence == enabled_assessment.downside_evidence


class TestSupportingEvidence:
    def test_target_probabilities_copied_exactly(self) -> None:
        matrix = _matrix_4obj()
        result = build_campaign_decision_evidence(policy=_policy_4obj(), outcome_matrix=matrix)
        for strategy_position, strategy_id in enumerate(("sc-a", "sc-b")):
            assessment = _assessment_for(result.strategy_assessments, strategy_id)
            expected = tuple(
                matrix.outcomes[
                    strategy_position * 3 + objective_position
                ].empirical_target_achievement_probability
                for objective_position in range(2)
            )
            expected_probabilities = tuple(
                probability for probability in expected if probability is not None
            )
            assert len(expected_probabilities) == 2
            assert assessment.target_achievement_probabilities == tuple(
                ObjectiveProbabilityEvidence(
                    objective_id=objective_id,
                    empirical_target_achievement_probability=probability,
                )
                for objective_id, probability in zip(
                    ("obj-1", "obj-2"), expected_probabilities, strict=True
                )
            )
            assert tuple(
                record.empirical_target_achievement_probability
                for record in assessment.target_achievement_probabilities
            ) == (1.0, 1.0)

    def test_downside_copied_exactly_for_targeted_objectives(self) -> None:
        matrix = _matrix_4obj()
        result = build_campaign_decision_evidence(policy=_policy_4obj(), outcome_matrix=matrix)
        for strategy_position, strategy_id in enumerate(("sc-a", "sc-b")):
            assessment = _assessment_for(result.strategy_assessments, strategy_id)
            for objective_position in range(2):
                outcome = matrix.outcomes[strategy_position * 3 + objective_position]
                record = assessment.downside_evidence[objective_position]
                assert record.worst_normalized_target_violation == (
                    outcome.worst_normalized_target_violation
                )
                assert record.target_violation_cvar == outcome.target_violation_cvar
                assert record.adverse_tail_statistic == outcome.adverse_tail_statistic

    def test_optimization_only_downside_none_none_with_exact_adverse_tail(self) -> None:
        matrix = _matrix_4obj()
        result = build_campaign_decision_evidence(policy=_policy_4obj(), outcome_matrix=matrix)
        for strategy_position, strategy_id in enumerate(("sc-a", "sc-b")):
            assessment = _assessment_for(result.strategy_assessments, strategy_id)
            record = assessment.downside_evidence[2]
            assert record.objective_id == "obj-4"
            assert record.worst_normalized_target_violation is None
            assert record.target_violation_cvar is None
            expected_tail = matrix.outcomes[strategy_position * 3 + 2].adverse_tail_statistic
            assert record.adverse_tail_statistic == expected_tail
            assert record.adverse_tail_statistic is not None

    def test_target_only_and_full_objective_ordering_is_exact(self) -> None:
        result = build_campaign_decision_evidence(
            policy=_policy_4obj(), outcome_matrix=_matrix_4obj()
        )
        for assessment in result.strategy_assessments:
            assert [record.objective_id for record in assessment.target_feasibility] == [
                "obj-1",
                "obj-2",
            ]
            assert [
                record.objective_id for record in assessment.target_achievement_probabilities
            ] == ["obj-1", "obj-2"]
            assert [record.objective_id for record in assessment.downside_evidence] == [
                "obj-1",
                "obj-2",
                "obj-4",
            ]
            assert [record.objective_id for record in assessment.target_feasibility] == [
                record.objective_id for record in assessment.target_achievement_probabilities
            ]

    def test_strategy_order_and_positions_are_exact(self) -> None:
        result = build_campaign_decision_evidence(
            policy=_policy_3x2(), outcome_matrix=_matrix_3x2()
        )
        assert [assessment.strategy_position for assessment in result.strategy_assessments] == [
            0,
            1,
            2,
        ]
        assert [assessment.strategy_candidate_id for assessment in result.strategy_assessments] == [
            "sc-a",
            "sc-b",
            "sc-c",
        ]


class TestAdversarialRejection:
    def test_wrong_source_types(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=cast(Any, matrix), outcome_matrix=matrix)
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=cast(Any, "x"))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=cast(Any, None), outcome_matrix=matrix)
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=cast(Any, policy))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=cast(Any, 42), outcome_matrix=matrix)

    def test_validator_bypassed_policy(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_policy(policy, tie_tolerance=-1.0),
            _tampered_policy(policy, tail_alpha=0.9),
            _tampered_policy(policy, minimum_sample_count="x"),
            _tampered_policy(policy, objective_weight_snapshots=()),
            _tampered_policy(policy, all_targeted_objectives_are_hard_gates="yes"),
        ):
            with pytest.raises(ValueError):
                build_campaign_decision_evidence(policy=tampered, outcome_matrix=matrix)

    def test_validator_bypassed_outcome_matrix(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_matrix(matrix, runtime_version="9.9.9"),
            _tampered_matrix(matrix, comparison_mode="other"),
            _tampered_matrix(matrix, ordered_scenario_seed_ids=("seed-0",)),
            _tampered_matrix(matrix, ordered_objective_ids=()),
            _tampered_matrix(matrix, ordered_strategy_candidate_ids=("sc-a", "sc-a")),
            _tampered_matrix(matrix, outcomes=()),
            _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(float("nan"),)),
            _tampered_outcome_matrix(matrix, 0, target=None),
        ):
            with pytest.raises(ValueError):
                build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_identity_mismatches(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        mismatches: tuple[tuple[str, object], ...] = (
            ("tenant_id", "tenant-2"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "0" * 64),
            ("world_version_id", "world-2"),
            ("world_content_hash", "1" * 64),
            ("evaluation_profile_id", "profile-2"),
            ("evaluation_profile_content_hash", "2" * 64),
        )
        for field, value in mismatches:
            tampered = policy.model_copy(update={field: value})
            with pytest.raises(ValueError):
                build_campaign_decision_evidence(policy=tampered, outcome_matrix=matrix)

    def test_algorithm_runtime_and_mode_literals(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy.model_copy(update={"algorithm_identifier": "other"}),
                outcome_matrix=matrix,
            )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy, outcome_matrix=_tampered_matrix(matrix, runtime_version="2.0.0")
            )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy,
                outcome_matrix=_tampered_matrix(matrix, comparison_mode="per_seed"),
            )

    def test_tail_alpha_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy.model_copy(update={"tail_alpha": 0.9}), outcome_matrix=matrix
            )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy, outcome_matrix=_tampered_outcome_matrix(matrix, 0, tail_alpha=0.9)
            )

    def test_per_objective_requirements_reordered(self) -> None:
        policy = _policy_3x2(
            requirements=(("obj-2", 0.4), ("obj-1", 0.4)),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_3x2())

    def test_per_objective_requirements_missing(self) -> None:
        policy = _policy_3x2(
            requirements=(("obj-1", 0.4),),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_3x2())

    def test_per_objective_requirements_additional_unknown(self) -> None:
        policy = _policy_3x2(
            requirements=(("obj-1", 0.4), ("obj-2", 0.4), ("obj-3", 0.4)),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_3x2())

    def test_per_objective_requirement_for_optimization_only_objective(self) -> None:
        policy = _policy_4obj(
            requirements=(("obj-1", 0.4), ("obj-2", 0.4), ("obj-4", 0.4)),
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_4obj())

    def test_weight_snapshot_value_id_and_order_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        snapshot = policy.objective_weight_snapshots[0]
        wrong_value = policy.model_copy(
            update={"objective_weight_snapshots": (snapshot.model_copy(update={"weight": 9.9}),)}
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=wrong_value, outcome_matrix=matrix)
        wrong_id = policy.model_copy(
            update={
                "objective_weight_snapshots": (
                    snapshot.model_copy(update={"objective_id": "obj-9"}),
                )
            }
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=wrong_id, outcome_matrix=matrix)
        policy_2 = _policy_3x2()
        reordered = policy_2.model_copy(
            update={
                "objective_weight_snapshots": tuple(reversed(policy_2.objective_weight_snapshots))
            }
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=reordered, outcome_matrix=_matrix_3x2())

    def test_missing_duplicate_and_reordered_outcomes(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        payload = matrix.model_dump(mode="python")
        outcomes = tuple(cast(tuple[dict[str, Any], ...], payload["outcomes"]))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy, outcome_matrix=_tampered_matrix(matrix, outcomes=())
            )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy,
                outcome_matrix=_tampered_matrix(matrix, outcomes=(outcomes[0], outcomes[0])),
            )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(
                policy=policy,
                outcome_matrix=_tampered_matrix(matrix, outcomes=(outcomes[1], outcomes[0])),
            )

    def test_invalid_sequence_strategy_and_objective_positions_or_identities(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_outcome_matrix(matrix, 0, sequence_position=5),
            _tampered_outcome_matrix(matrix, 0, strategy_position=1),
            _tampered_outcome_matrix(matrix, 0, objective_position=1),
            _tampered_outcome_matrix(matrix, 0, strategy_candidate_id="sc-x"),
            _tampered_outcome_matrix(matrix, 0, objective_id="obj-x"),
        ):
            with pytest.raises(ValueError):
                build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_observed_length_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(90, 95))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_empirical_samples_mismatch(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        payload = matrix.model_dump(mode="python")
        outcomes = list(cast(list[dict[str, Any]], payload["outcomes"]))
        tampered_outcome = dict(outcomes[0])
        distribution = dict(cast(dict[str, Any], tampered_outcome["empirical_distribution"]))
        distribution["ordered_samples"] = (1.0, 2.0, 3.0)
        tampered_outcome["empirical_distribution"] = distribution
        outcomes[0] = tampered_outcome
        tampered = _tampered_matrix(matrix, outcomes=tuple(outcomes))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_inconsistent_objective_snapshots_across_strategies(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        for tampered in (
            _tampered_outcome_matrix(matrix, 1, weight=5.0),
            _tampered_outcome_matrix(matrix, 1, target=50.0),
            _tampered_outcome_matrix(matrix, 1, normalization_scale=1.0),
            _tampered_outcome_matrix(matrix, 1, metric_id="m-9"),
        ):
            with pytest.raises(ValueError):
                build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_targeted_evidence_fields_must_match_target_presence(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(
            matrix, 0, empirical_target_achievement_probability=None
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)
        opt_only = _matrix_opt_only()
        policy_opt = _policy_opt_only()
        tampered_opt = _tampered_outcome_matrix(
            opt_only, 0, empirical_target_achievement_probability=0.5
        )
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy_opt, outcome_matrix=tampered_opt)

    def test_one_strategy_only_rejected(self) -> None:
        policy = _policy()
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=_matrix_ones_strategy())

    def test_late_malformed_evidence_produces_no_partial_result(self) -> None:
        matrix = _matrix_4obj()
        policy = _policy_4obj()
        # The final outcome of the final strategy is malformed: validation
        # must fail before any assessment is produced, and the inputs must
        # remain unchanged.
        tampered = _tampered_outcome_matrix(matrix, 5, ordered_observed_values=(10**400,))
        matrix_before = tampered.model_dump(mode="python")
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)
        assert tampered.model_dump(mode="python") == matrix_before

    def test_non_finite_policy_metadata(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_policy(policy, metadata={"bad": float("nan")})
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=tampered, outcome_matrix=matrix)

    def test_huge_integer_rejected_at_the_boundary(self) -> None:
        matrix = _matrix_2x1()
        policy = _policy()
        tampered = _tampered_outcome_matrix(matrix, 0, ordered_observed_values=(10**400,))
        with pytest.raises(ValueError):
            build_campaign_decision_evidence(policy=policy, outcome_matrix=tampered)

    def test_overflow_error_is_never_converted_to_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        matrix = _matrix_2x1()

        def exploding_validate(payload: object, **kwargs: object) -> object:
            raise OverflowError("numeric representability overflow")

        monkeypatch.setattr(CampaignOutcomeDistributionMatrix, "model_validate", exploding_validate)
        with pytest.raises(OverflowError):
            build_campaign_decision_evidence(policy=_policy(), outcome_matrix=matrix)


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


#: The later-pipeline decision-surface symbol pattern (no dominance,
#: regret, minimax, tie-set selection, terminal status, reason/factor,
#: comparison/brief assembly, identity/hash, or persistence surface may
#: exist in the evidence layer).
_DECISION_SURFACE_PATTERN = re.compile(
    r"rank|winner|prefer|recommend|confidence|forecast|dominance|dominat|"
    r"regret|minimax|pareto|status|inconclusive|insufficient|paired|tie|"
    r"reason|factor|brief|hash|identity|store|api|query|activity|selection",
    re.IGNORECASE,
)
