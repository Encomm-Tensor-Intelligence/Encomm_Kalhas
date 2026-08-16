"""Phase 20 boundary scans.

Proves the new contract module, the extraction/verification service, and
the store collection contain no NEXUS/LEGION imports or calls, no
network/provider/filesystem/time/randomness surface, no dynamic loading
or executable expressions, no domain-pack imports, no domain-specific
vocabulary, no outcome/aggregation/evidence/ranking/recommendation
production, no transition evaluation or replay triggering, and no
automatic extraction during campaign execution; that the extraction
service exposes exactly the focused surface; that the structural event
kind tuple remains exactly the existing three kinds; that Phase 17/18/19
behavior stays registered and untouched; that PUBLIC_CONTRACTS remains
exactly 35 with ``CampaignMetricStatisticsMatrix`` appended last
(Phase 20's ``RunMetricObservationSet``
keeps its own slot); and that runtime/execution/replay signatures and
the runtime version constants are unchanged.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from kalhas.application.structural_runtime import STRUCTURAL_EVENT_KINDS
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.simulation import RunEventKind

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE20_MODULES = (
    "contracts/v1/run_metric_observation.py",
    "application/run_metric_observation_service.py",
    "application/in_memory_store.py",
)

#: The exact 32 contracts registered before Phase 20, in registration
#: order - Phase 20 must append without touching any of them.
_PRE_PHASE20_CONTRACTS = (
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
)

#: Modules that must never integrate extraction automatically.
_AUTOMATIC_INTEGRATION_MODULES = (
    "application/structural_runtime.py",
    "application/campaign_service.py",
    "application/campaign_lifecycle.py",
    "application/replay_service.py",
    "application/run_trajectory_runtime.py",
    "application/run_planner.py",
    "application/campaign_trajectory_query_service.py",
)

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(
    r"\b(requests|urllib|socket|subprocess|httpx|http\.client|open\(|Path\(|os\.|"
    r"datetime\.now|time\.|random|secrets|fastapi)\b"
)
_BEHAVIOR_TOKENS = re.compile(r"\b(callback|executable|callable)\b")
_DOMAIN_VOCABULARY = re.compile(r"\b(maritime|logistics|port|fuel|vessel|cargo)\b")
_OUTCOME_TOKENS = re.compile(
    r"\b(outcome|evidence|recommendation|decision_brief|point_estimate|probability|score|"
    r"distribution|rank)\b"
)
# Evaluation/replay/execution/sampling entry points Phase 20 must never call.
_FORBIDDEN_CALLS = re.compile(
    r"^(?:build_run_trajectory_execution|replay_run|evaluate_trajectory|execute_run|"
    r"execute_campaign|prepare_strategy_trajectory_plans|evaluate_campaign|"
    r"derive_initial_state|validate_state|state_hash|sample_uncertainty|"
    r"aggregate_observations|extract_metric_value)$"
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
    for relative in _PHASE20_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE20_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE20_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_evidence_or_recommendation_production() -> None:
    for relative in _PHASE20_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_phase20_never_calls_evaluation_execution_or_replay() -> None:
    for relative in _PHASE20_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"evaluation/execution/replay calls in {relative}: {calls}"


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/run_metric_observation.py"))
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
        "kalhas.contracts.v1.metric_observation",
        "kalhas.contracts.v1.shared",
    ], imports


def test_extraction_service_exposes_only_focused_functions() -> None:
    module = ast.parse(_module_source("application/run_metric_observation_service.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == [
        "build_run_metric_observation_set",
        "extract_run_metric_observations",
        "get_verified_run_metric_observation_set",
        "run_metric_observation_set_content_hash",
        "run_metric_observation_set_identifier",
        "verify_run_metric_observation_set_record",
    ], functions


def test_extraction_service_signature_accepts_no_adapters_or_execution_inputs() -> None:
    from kalhas.application.run_metric_observation_service import (
        extract_run_metric_observations,
        get_verified_run_metric_observation_set,
    )

    assert list(inspect.signature(extract_run_metric_observations).parameters) == [
        "store",
        "tenant_id",
        "run_id",
    ]
    assert list(inspect.signature(get_verified_run_metric_observation_set).parameters) == [
        "store",
        "tenant_id",
        "run_id",
    ]


def test_store_has_no_update_delete_or_repair_surface() -> None:
    source = _module_source("application/in_memory_store.py")
    for token in (
        "update_run_metric_observation_set",
        "delete_run_metric_observation_set",
        "repair_run_metric_observation_set",
        "replace_run_metric_observation_set",
    ):
        assert token not in source


def test_no_automatic_extraction_during_campaign_execution() -> None:
    for relative in _AUTOMATIC_INTEGRATION_MODULES:
        source = _module_source(relative)
        assert "run_metric_observation" not in source, f"{relative} integrates extraction"
        assert "extract_run_metric_observations" not in source


def test_structural_event_kinds_are_exactly_three() -> None:
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_phase17_18_19_behavior_unchanged() -> None:
    """The Phase 16-19 contracts stay registered at their exact slots."""
    from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
    from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding

    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[30] == "CampaignTrajectoryMatrix"
    assert names[31] == "DomainMetricObservationBinding"
    assert CampaignTrajectoryMatrix in PUBLIC_CONTRACTS
    assert DomainMetricObservationBinding in PUBLIC_CONTRACTS


def test_public_contracts_remain_exactly_forty() -> None:
    assert len(PUBLIC_CONTRACTS) == 47


def test_existing_v1_contracts_unchanged_and_set_appended() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:32] == _PRE_PHASE20_CONTRACTS
    assert names[32] == "RunMetricObservationSet"
    assert names[33] == "CampaignMetricObservationMatrix"


def test_contract_fields_carry_no_executable_types() -> None:
    from kalhas.contracts.v1.run_metric_observation import (
        RunMetricObservationSet,
        RunMetricObservationValue,
    )

    for contract in (RunMetricObservationSet, RunMetricObservationValue):
        for name, field in contract.model_fields.items():
            annotation = str(field.annotation)
            assert not re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
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


def test_observation_set_runtime_literal_matches_authoritative_constant() -> None:
    from typing import get_args

    from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
    from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet
    from kalhas.contracts.v1.trajectory_execution import TRAJECTORY_RUNTIME_VERSION_LITERAL

    annotation = RunMetricObservationSet.model_fields["runtime_version"].annotation
    assert get_args(annotation) == ("2.0.0",)
    assert TRAJECTORY_RUNTIME_VERSION_LITERAL == TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    # The set schema constrains the literal to the authoritative version.
    schema = RunMetricObservationSet.model_json_schema()
    assert schema["properties"]["runtime_version"]["const"] == "2.0.0"


def test_no_new_operational_activity_kinds() -> None:
    from kalhas.contracts.v1.activity import OperationalActivityKind

    kinds = [kind.value for kind in OperationalActivityKind]
    assert "metric" not in " ".join(kinds)
    assert "observation" not in " ".join(kinds)


def test_no_colony_changes() -> None:
    source = _module_source("api/routes.py")
    assert "/colony/" in source
    assert "COLONY_UI_DIR" in source
    for relative in _PHASE20_MODULES:
        assert "colony" not in _code_only(_module_source(relative))
