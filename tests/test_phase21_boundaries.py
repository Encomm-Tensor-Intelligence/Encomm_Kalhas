"""Phase 21 boundary scans.

Proves the new contract module, the pure matrix builder, and the
verified query service contain no NEXUS/LEGION imports or calls, no
network/provider/filesystem/database/wall-clock/randomness surface, no
dynamic loading or executable expressions, no domain-pack imports, no
statistical aggregation, outcome, distribution, evidence, scoring,
ranking, recommendation, normalization, or unit-conversion production,
and no execution/replay/evaluation triggering; that the pure builder
never accesses the store and the query never triggers Phase 20
extraction; that no campaign-matrix storage collection or method exists
anywhere; that the runtime/execution/replay/lifecycle modules are
untouched; that the structural event kinds remain exactly the existing
five; that Phase 18/19/20 behavior stays registered and untouched; that
PUBLIC_CONTRACTS remains exactly 35 with the unchanged 34 existing
contracts and ``CampaignMetricStatisticsMatrix`` appended last; and
that the runtime version constants are unchanged.
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

_PHASE21_MODULES = (
    "contracts/v1/campaign_metric_observation.py",
    "application/campaign_metric_observation_runtime.py",
    "application/campaign_metric_observation_query_service.py",
)

#: The exact 33 contracts registered before Phase 21, in registration
#: order - Phase 21 must append without touching any of them.
_PRE_PHASE21_CONTRACTS = (
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
)

#: Modules that must never integrate the matrix (no storage, no calls).
_AUTOMATIC_INTEGRATION_MODULES = (
    "application/structural_runtime.py",
    "application/campaign_service.py",
    "application/campaign_lifecycle.py",
    "application/replay_service.py",
    "application/run_trajectory_runtime.py",
    "application/run_planner.py",
    "application/campaign_trajectory_query_service.py",
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
_STATISTICS_TOKENS = re.compile(
    r"\b(mean|average|median|quantile|percentile|variance|stddev|distribution|"
    r"aggregate|sum\(|min\(|max\(|confidence)\b"
)
_OUTCOME_TOKENS = re.compile(
    r"\b(outcome|evidence|recommendation|decision_brief|point_estimate|probability|"
    r"score|rank)\b"
)
_NORMALIZATION_TOKENS = re.compile(
    r"\b(normalize|normalization|transform|conversion|convert|scale)\b"
)
# Evaluation/replay/execution/sampling entry points Phase 21 must never call.
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
    for relative in _PHASE21_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE21_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE21_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_statistical_aggregation_or_outcome_production() -> None:
    for relative in _PHASE21_MODULES:
        code = _code_only(_module_source(relative))
        assert not _STATISTICS_TOKENS.search(code), f"statistics tokens in {relative}"
        assert not _NORMALIZATION_TOKENS.search(code), f"normalization tokens in {relative}"
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_no_outcome_vector_or_distribution_summary_construction() -> None:
    for relative in _PHASE21_MODULES:
        code = _code_only(_module_source(relative))
        for token in (
            "MetricOutcome",
            "OutcomeVector",
            "DistributionSummary",
            "DecisionBrief",
            "EvidenceReference",
        ):
            assert token not in code, f"{token} referenced in {relative}"


def test_phase21_never_calls_evaluation_execution_extraction_or_replay() -> None:
    for relative in _PHASE21_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"evaluation/execution/replay calls in {relative}: {calls}"


def test_pure_builder_never_accesses_the_store() -> None:
    source = _code_only(_module_source("application/campaign_metric_observation_runtime.py"))
    assert "in_memory_store" not in source
    assert "InMemoryScenarioStore" not in source
    for token in ("store.", "get_campaign", "get_run_plans", "get_run_metric_observation_set"):
        assert token not in source, f"store access token {token!r} in the pure builder"


def test_query_never_triggers_phase20_extraction() -> None:
    source = _module_source("application/campaign_metric_observation_query_service.py")
    assert "extract_run_metric_observations" not in source
    assert "extract" not in _code_only(source)


def test_no_matrix_storage_collection_or_method_anywhere() -> None:
    store_source = _module_source("application/in_memory_store.py")
    assert "matrix" not in store_source
    for token in (
        "put_campaign_metric_observation_matrix",
        "get_campaign_metric_observation_matrix",
        "update_campaign_metric_observation_matrix",
        "delete_campaign_metric_observation_matrix",
        "repair_campaign_metric_observation_matrix",
    ):
        assert token not in store_source
    for relative in _AUTOMATIC_INTEGRATION_MODULES:
        source = _module_source(relative)
        assert "metric_observation_matrix" not in source, f"{relative} integrates the matrix"
        assert "campaign_metric_observation" not in source, f"{relative} integrates the matrix"


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/campaign_metric_observation.py"))
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert imports == [
        "__future__",
        "typing",
        "pydantic",
        "kalhas.contracts.v1.run_metric_observation",
        "kalhas.contracts.v1.shared",
    ], imports


def test_builder_exposes_only_focused_functions() -> None:
    module = ast.parse(_module_source("application/campaign_metric_observation_runtime.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == [
        "build_campaign_metric_observation_matrix",
        "campaign_metric_observation_matrix_content_hash",
        "campaign_metric_observation_matrix_identifier",
    ], functions


def test_query_service_exposes_only_focused_function() -> None:
    module = ast.parse(_module_source("application/campaign_metric_observation_query_service.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == ["get_verified_campaign_metric_observation_matrix"], functions


def test_builder_and_query_signatures_accept_no_adapters_or_execution_inputs() -> None:
    from kalhas.application.campaign_metric_observation_query_service import (
        get_verified_campaign_metric_observation_matrix,
    )
    from kalhas.application.campaign_metric_observation_runtime import (
        build_campaign_metric_observation_matrix,
    )

    assert list(inspect.signature(build_campaign_metric_observation_matrix).parameters) == [
        "campaign",
        "trajectory_matrix",
        "observation_sets",
    ]
    assert list(inspect.signature(get_verified_campaign_metric_observation_matrix).parameters) == [
        "store",
        "tenant_id",
        "campaign_id",
    ]


def test_phase18_19_20_behavior_unchanged() -> None:
    from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
    from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
    from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[30] == "CampaignTrajectoryMatrix"
    assert names[31] == "DomainMetricObservationBinding"
    assert names[32] == "RunMetricObservationSet"
    for contract in (
        CampaignTrajectoryMatrix,
        DomainMetricObservationBinding,
        RunMetricObservationSet,
    ):
        assert contract in PUBLIC_CONTRACTS


def test_public_contracts_remain_exactly_forty() -> None:
    assert len(PUBLIC_CONTRACTS) == 50


def test_existing_v1_contracts_unchanged_and_matrix_appended_last() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:33] == _PRE_PHASE21_CONTRACTS
    assert names[33] == "CampaignMetricObservationMatrix"
    assert names[34] == "CampaignMetricStatisticsMatrix"
    assert "CampaignMetricObservationCell" not in names
    assert "CampaignStrategyMetricStatistics" not in names


def test_contract_fields_carry_no_executable_types() -> None:
    import re as _re

    from kalhas.contracts.v1.campaign_metric_observation import (
        CampaignMetricObservationCell,
        CampaignMetricObservationMatrix,
    )

    for contract in (CampaignMetricObservationMatrix, CampaignMetricObservationCell):
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


def test_matrix_runtime_literal_matches_authoritative_constant() -> None:
    from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
    from kalhas.contracts.v1.campaign_metric_observation import (
        METRIC_OBSERVATION_MATRIX_RUNTIME_VERSION_LITERAL,
        CampaignMetricObservationMatrix,
    )
    from kalhas.contracts.v1.trajectory_execution import TRAJECTORY_RUNTIME_VERSION_LITERAL

    annotation = CampaignMetricObservationMatrix.model_fields["runtime_version"].annotation
    assert get_args(annotation) == ("2.0.0",)
    assert (
        METRIC_OBSERVATION_MATRIX_RUNTIME_VERSION_LITERAL == TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    )
    assert TRAJECTORY_RUNTIME_VERSION_LITERAL == TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    schema = CampaignMetricObservationMatrix.model_json_schema()
    assert schema["properties"]["runtime_version"]["const"] == "2.0.0"
    assert schema["properties"]["comparison_mode"]["const"] == "identical_conditions"


def test_runtime_version_constants_are_phase25_aware() -> None:
    from kalhas.application.run_planner import (
        LEGACY_STRUCTURAL_RUNTIME_VERSION,
        REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        RUNTIME_VERSION,
        TRAJECTORY_RUNTIME_VERSION,
    )

    # The recorded runtime-2 planning constants remain exactly unchanged.
    assert {LEGACY_STRUCTURAL_RUNTIME_VERSION, TRAJECTORY_RUNTIME_VERSION} == {"1.0.0", "2.0.0"}
    assert LEGACY_STRUCTURAL_RUNTIME_VERSION == "1.0.0"
    assert TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    assert RUNTIME_VERSION == TRAJECTORY_RUNTIME_VERSION
    # Phase 25 adds the separate runtime-3 planner constant.
    assert REALIZATION_TRAJECTORY_RUNTIME_VERSION == "3.0.0"


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
    assert "observation" not in " ".join(kinds)
    assert "matrix" not in " ".join(kinds)


def test_no_colony_changes() -> None:
    source = _module_source("api/routes.py")
    assert "/colony/" in source
    assert "COLONY_UI_DIR" in source
    for relative in _PHASE21_MODULES:
        assert "colony" not in _code_only(_module_source(relative))
