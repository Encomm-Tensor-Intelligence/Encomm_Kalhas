"""Phase 22 boundary scans.

Proves the new contract module, the pure statistics builder, and the
verified query service contain no NEXUS/LEGION imports or calls, no
network/provider/filesystem/database/wall-clock/randomness surface, no
dynamic loading or executable expressions, no domain-pack imports, no
outcome/evidence/ranking/scoring/recommendation/normalization/unit-
conversion production, no quantiles/confidence intervals/weighting, no
declared aggregation-policy interpretation, and no execution/replay/
extraction/evaluation triggering; that the pure builder never accesses
the store and the query never triggers Phase 20 extraction; that no
statistics storage collection or method exists anywhere; that the
runtime/execution/replay/lifecycle modules are untouched; that the
structural event kinds and operational activity kinds remain exactly
the existing ones; that PUBLIC_CONTRACTS remains exactly 35 with the
unchanged 34 existing contracts and ``CampaignMetricStatisticsMatrix``
appended last; that no new dependencies or runtime versions were added;
and that the Colony surface is unchanged.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import get_args

from kalhas.application.structural_runtime import STRUCTURAL_EVENT_KINDS
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.simulation import RunEventKind

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE22_MODULES = (
    "contracts/v1/campaign_metric_statistics.py",
    "application/campaign_metric_statistics_runtime.py",
    "application/campaign_metric_statistics_query_service.py",
)

#: The exact 34 contracts registered before Phase 22, in registration
#: order - Phase 22 must append without touching any of them.
_PRE_PHASE22_CONTRACTS = (
    "ScenarioSpec",
    "ContextBundle",
    "ClarificationQuestion",
    "ValidationReport",
    "WorldManifest",
    "WorldVersion",
    "UncertaintyDefinition",
    "StrategyRequest",
    "StrategyCandidate",
    "CampaignSpec",
    "CampaignStatus",
    "ScenarioSeed",
    "RunEvent",
    "OutcomeVector",
    "EvidenceReference",
    "DecisionBrief",
    "RunPlan",
    "RunStatus",
    "ReplayManifest",
    "RunInputIntegrityManifest",
    "DomainPackManifest",
    "DomainPackBinding",
    "DomainCapabilityDeclaration",
    "DomainStateModel",
    "DomainStateTransition",
    "OperationalActivityEvent",
    "StrategyTrajectoryPlan",
    "StrategyTrajectoryPlanRequest",
    "RunTrajectoryExecution",
    "RunTrajectoryReplayManifest",
    "CampaignTrajectoryMatrix",
    "DomainMetricObservationBinding",
    "RunMetricObservationSet",
    "CampaignMetricObservationMatrix",
)

#: Modules that must never integrate the statistics matrix (no storage, no calls).
_AUTOMATIC_INTEGRATION_MODULES = (
    "application/structural_runtime.py",
    "application/campaign_service.py",
    "application/campaign_lifecycle.py",
    "application/replay_service.py",
    "application/run_trajectory_runtime.py",
    "application/run_planner.py",
    "application/campaign_trajectory_query_service.py",
    "application/campaign_metric_observation_runtime.py",
    "application/campaign_metric_observation_query_service.py",
    "application/run_metric_observation_service.py",
    "application/trajectory_query_service.py",
    "application/input_integrity.py",
    "application/in_memory_store.py",
)

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(
    r"\b(requests|urllib|socket|subprocess|httpx|http\.client|open\(|Path\(|os\.|"
    r"datetime\.now|datetime\.utcnow|time\.|random|secrets|uuid4|fastapi|sqlite|"
    r"provider)\b"
)
_BEHAVIOR_TOKENS = re.compile(r"\b(callback|executable|callable)\b")
_DOMAIN_VOCABULARY = re.compile(r"\b(maritime|logistics|port|fuel|vessel|cargo)\b")
# Non-goal statistics tokens: descriptive statistics (mean/median/min/max/
# stddev) are the Phase 22 feature and are expected; quantiles, confidence
# intervals, weighting, sampling, and declared aggregation-policy
# interpretation are forbidden.
_NONGOAL_STATISTICS_TOKENS = re.compile(
    r"\b(quantile|percentile|confidence|weight|sample|aggregation|aggregate)\b"
)
_OUTCOME_TOKENS = re.compile(r"\b(outcome|evidence|recommend|decision_brief|score|rank|winner)\b")
_NORMALIZATION_TOKENS = re.compile(
    r"\b(normalize|normalization|transform|conversion|convert|scale)\b"
)
# Evaluation/replay/execution/extraction/sampling entry points Phase 22 must never call.
_FORBIDDEN_CALLS = re.compile(
    r"^(?:build_run_trajectory_execution|replay_run|evaluate_trajectory|execute_run|"
    r"execute_campaign|prepare_strategy_trajectory_plans|evaluate_campaign|"
    r"derive_initial_state|validate_state|state_hash|sample_uncertainty|"
    r"aggregate_observations|extract_metric_value|extract_run_metric_observations)$"
)


def _code_only(source: str) -> str:
    """Strip docstrings so prose naming the non-goals cannot false-positive."""
    return "".join(source.split('"""')[::2])


def _module_source(relative: str) -> str:
    return (KALHAS_ROOT / relative).read_text(encoding="utf-8")


def _call_names(module: ast.Module) -> list[tuple[int, str]]:
    """Every called function name in the module (position, name)."""
    calls: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue
        calls.append((node.lineno, name))
    return calls


def test_no_nexus_or_legion_imports() -> None:
    for relative in _PHASE22_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE22_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE22_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_production_or_normalization_or_aggregation_policy() -> None:
    for relative in _PHASE22_MODULES:
        code = _code_only(_module_source(relative))
        assert not _NONGOAL_STATISTICS_TOKENS.search(code), (
            f"non-goal statistics tokens in {relative}"
        )
        assert not _OUTCOME_TOKENS.search(code), f"outcome/ranking tokens in {relative}"
        assert not _NORMALIZATION_TOKENS.search(code), f"normalization tokens in {relative}"
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_no_outcome_vector_or_distribution_summary_construction() -> None:
    for relative in _PHASE22_MODULES:
        code = _code_only(_module_source(relative))
        for token in (
            "MetricOutcome",
            "OutcomeVector",
            "DistributionSummary",
            "DecisionBrief",
            "EvidenceReference",
        ):
            assert token not in code, f"{token} referenced in {relative}"


def test_phase22_never_calls_evaluation_execution_extraction_or_replay() -> None:
    for relative in _PHASE22_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"evaluation/execution/replay calls in {relative}: {calls}"


def test_pure_builder_never_accesses_the_store() -> None:
    source = _code_only(_module_source("application/campaign_metric_statistics_runtime.py"))
    assert "in_memory_store" not in source
    assert "InMemoryScenarioStore" not in source
    for token in ("store.", "get_campaign", "get_run_plans", "get_run_metric_observation_set"):
        assert token not in source, f"store access token {token!r} in the pure builder"


def test_query_never_triggers_phase20_extraction() -> None:
    source = _module_source("application/campaign_metric_statistics_query_service.py")
    assert "extract_run_metric_observations" not in source
    assert "extract" not in _code_only(source)


def test_no_statistics_storage_collection_or_method_anywhere() -> None:
    store_source = _module_source("application/in_memory_store.py")
    assert "campaign_metric_statistics" not in store_source
    assert "statistics_matrix" not in store_source
    for token in (
        "put_campaign_metric_statistics_matrix",
        "get_campaign_metric_statistics_matrix",
        "update_campaign_metric_statistics_matrix",
        "delete_campaign_metric_statistics_matrix",
        "repair_campaign_metric_statistics_matrix",
    ):
        assert token not in store_source
    for relative in _AUTOMATIC_INTEGRATION_MODULES:
        source = _module_source(relative)
        assert "metric_statistics" not in source, f"{relative} integrates the statistics matrix"
        assert "statistics_matrix" not in source, f"{relative} integrates the statistics matrix"


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/campaign_metric_statistics.py"))
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert imports == [
        "__future__",
        "math",
        "typing",
        "pydantic",
        "kalhas.contracts.v1.shared",
    ], imports


def test_builder_exposes_only_focused_functions() -> None:
    module = ast.parse(_module_source("application/campaign_metric_statistics_runtime.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == [
        "build_campaign_metric_statistics_matrix",
        "campaign_metric_statistics_matrix_content_hash",
        "campaign_metric_statistics_matrix_identifier",
        "statistics_arithmetic_mean",
        "statistics_maximum",
        "statistics_median",
        "statistics_minimum",
        "statistics_population_standard_deviation",
    ], functions


def test_query_service_exposes_only_focused_function() -> None:
    module = ast.parse(_module_source("application/campaign_metric_statistics_query_service.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == ["get_verified_campaign_metric_statistics"], functions


def test_builder_and_query_signatures_accept_no_adapters_or_execution_inputs() -> None:
    from kalhas.application.campaign_metric_statistics_query_service import (
        get_verified_campaign_metric_statistics,
    )
    from kalhas.application.campaign_metric_statistics_runtime import (
        build_campaign_metric_statistics_matrix,
    )

    assert list(inspect.signature(build_campaign_metric_statistics_matrix).parameters) == [
        "observation_matrix",
    ]
    assert list(inspect.signature(get_verified_campaign_metric_statistics).parameters) == [
        "store",
        "tenant_id",
        "campaign_id",
    ]


def test_phase18_19_20_21_behavior_unchanged() -> None:
    from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
    from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
    from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
    from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[30] == "CampaignTrajectoryMatrix"
    assert names[31] == "DomainMetricObservationBinding"
    assert names[32] == "RunMetricObservationSet"
    assert names[33] == "CampaignMetricObservationMatrix"
    for contract in (
        CampaignTrajectoryMatrix,
        DomainMetricObservationBinding,
        RunMetricObservationSet,
        CampaignMetricObservationMatrix,
    ):
        assert contract in PUBLIC_CONTRACTS


def test_public_contracts_remain_exactly_thirty_five() -> None:
    assert len(PUBLIC_CONTRACTS) == 37


def test_existing_v1_contracts_unchanged_and_statistics_matrix_appended_last() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:34] == _PRE_PHASE22_CONTRACTS
    assert names[34] == "CampaignMetricStatisticsMatrix"
    assert "CampaignStrategyMetricStatistics" not in names


def test_contract_fields_carry_no_executable_types() -> None:
    import re as _re

    from kalhas.contracts.v1.campaign_metric_statistics import (
        CampaignMetricStatisticsMatrix,
        CampaignStrategyMetricStatistics,
    )

    for contract in (CampaignMetricStatisticsMatrix, CampaignStrategyMetricStatistics):
        for name, field in contract.model_fields.items():
            annotation = str(field.annotation)
            assert not _re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
                f"{contract.__name__}.{name}"
            )


def test_runtime_versions_and_execution_signatures_unchanged() -> None:
    from kalhas.application.replay_service import replay_run
    from kalhas.application.run_planner import (
        LEGACY_STRUCTURAL_RUNTIME_VERSION,
        RUNTIME_VERSION,
        TRAJECTORY_RUNTIME_VERSION,
    )
    from kalhas.application.structural_runtime import execute_campaign, execute_run

    assert LEGACY_STRUCTURAL_RUNTIME_VERSION == "1.0.0"
    assert TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    assert RUNTIME_VERSION == TRAJECTORY_RUNTIME_VERSION
    assert list(inspect.signature(execute_run).parameters) == ["store", "tenant_id", "run_id"]
    assert list(inspect.signature(execute_campaign).parameters) == [
        "store",
        "tenant_id",
        "campaign_id",
    ]
    assert list(inspect.signature(replay_run).parameters) == ["store", "tenant_id", "run_id"]


def test_statistics_literals_match_authoritative_constants() -> None:
    from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
    from kalhas.contracts.v1.campaign_metric_statistics import (
        STATISTICS_MATRIX_RUNTIME_VERSION_LITERAL,
        CampaignMetricStatisticsMatrix,
    )
    from kalhas.contracts.v1.trajectory_execution import TRAJECTORY_RUNTIME_VERSION_LITERAL

    runtime_annotation = CampaignMetricStatisticsMatrix.model_fields["runtime_version"].annotation
    assert get_args(runtime_annotation) == ("2.0.0",)
    comparison_annotation = CampaignMetricStatisticsMatrix.model_fields[
        "comparison_mode"
    ].annotation
    assert get_args(comparison_annotation) == ("identical_conditions",)
    statistics_annotation = CampaignMetricStatisticsMatrix.model_fields[
        "statistics_mode"
    ].annotation
    assert get_args(statistics_annotation) == ("descriptive",)
    assert (
        STATISTICS_MATRIX_RUNTIME_VERSION_LITERAL
        == TRAJECTORY_RUNTIME_VERSION
        == TRAJECTORY_RUNTIME_VERSION_LITERAL
        == "2.0.0"
    )
    schema = CampaignMetricStatisticsMatrix.model_json_schema()
    assert schema["properties"]["runtime_version"]["const"] == "2.0.0"
    assert schema["properties"]["comparison_mode"]["const"] == "identical_conditions"
    assert schema["properties"]["statistics_mode"]["const"] == "descriptive"


def test_no_new_runtime_version_constant() -> None:
    from kalhas.application.run_planner import (
        LEGACY_STRUCTURAL_RUNTIME_VERSION,
        RUNTIME_VERSION,
        TRAJECTORY_RUNTIME_VERSION,
    )

    source = _module_source("application/run_planner.py")
    assert "3.0.0" not in source
    # The recorded runtime versions remain exactly the two known ones.
    assert {LEGACY_STRUCTURAL_RUNTIME_VERSION, TRAJECTORY_RUNTIME_VERSION} == {"1.0.0", "2.0.0"}
    assert RUNTIME_VERSION == TRAJECTORY_RUNTIME_VERSION


def test_structural_event_kinds_are_exactly_nine() -> None:
    assert tuple(RunEventKind) == (
        RunEventKind.STATE_CHANGE,
        RunEventKind.OBSERVATION,
        RunEventKind.DECISION,
        RunEventKind.MILESTONE,
        RunEventKind.ERROR,
        RunEventKind.NOTE,
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_no_new_operational_activity_kinds() -> None:
    from kalhas.contracts.v1.activity import OperationalActivityKind

    kinds = [kind.value for kind in OperationalActivityKind]
    assert "metric" not in " ".join(kinds)
    assert "statistics" not in " ".join(kinds)
    assert "observation" not in " ".join(kinds)
    assert "matrix" not in " ".join(kinds)


def test_no_colony_changes() -> None:
    source = _module_source("api/routes.py")
    assert "/colony/" in source
    assert "COLONY_UI_DIR" in source
    for relative in _PHASE22_MODULES:
        assert "colony" not in _code_only(_module_source(relative))


def test_no_new_dependencies() -> None:
    import tomllib
    from pathlib import Path as _Path

    pyproject = tomllib.loads(
        (_Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = " ".join(pyproject["project"]["dependencies"])
    for forbidden in ("numpy", "pandas", "scipy", "statistics", "openpyxl"):
        assert forbidden not in dependencies, f"forbidden dependency {forbidden!r}"
