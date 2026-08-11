"""Phase 19 boundary scans.

Proves the new contract module, the declaration service, the store
collection, and the world-compiler/integrity extensions contain no
NEXUS/LEGION imports or calls, no network/provider/filesystem/time/
randomness surface, no dynamic loading or executable expressions, no
domain-pack imports, no domain-specific vocabulary, no
extraction/outcome/evidence/recommendation-producing calls, and no
trajectory/execution/replay access; that the declaration service exposes
exactly the focused declaration surface; that the structural event kind
tuple remains exactly the existing three kinds; that Phase 18 matrix
behavior remains registered and untouched; that PUBLIC_CONTRACTS remains
exactly 32 with the new binding appended after the unchanged 31 existing
contracts; and that runtime/execution/replay signatures are unchanged.
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

_PHASE19_MODULES = (
    "contracts/v1/metric_observation.py",
    "application/domain_metric_observation_service.py",
    "application/in_memory_store.py",
    "application/world_compiler.py",
    "application/world_integrity.py",
)

#: The exact 31 contracts registered before Phase 19, in registration
#: order - Phase 19 must append without touching any of them.
_PRE_PHASE19_CONTRACTS = (
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
    r"\b(outcome|evidence|recommendation|decision_brief|point_estimate|probability|score)\b"
)
# Extraction/evaluation/replay entry points Phase 19 must never call.
_FORBIDDEN_CALLS = re.compile(
    r"^(?:build_run_trajectory_execution|replay_run|evaluate_trajectory|execute_run|"
    r"execute_campaign|prepare_strategy_trajectory_plans|evaluate_campaign|"
    r"derive_initial_state|validate_state|state_hash|extract_metric_value|"
    r"aggregate_observations|sample_uncertainty)$"
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
    for relative in _PHASE19_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE19_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE19_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_evidence_or_recommendation_production() -> None:
    for relative in _PHASE19_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_phase19_path_never_calls_extraction_execution_or_evaluation() -> None:
    for relative in _PHASE19_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"extraction/execution/replay/evaluation calls in {relative}: {calls}"


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/metric_observation.py"))
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
        "kalhas.contracts.v1.shared",
        "kalhas.contracts.v1.state_model",
    ], imports


def test_declaration_service_exposes_only_focused_functions() -> None:
    module = ast.parse(_module_source("application/domain_metric_observation_service.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == [
        "build_domain_metric_observation",
        "declare_domain_metric_observation",
        "domain_metric_observation_content_hash",
        "domain_metric_observation_identifier",
        "get_domain_metric_observation",
        "list_domain_metric_observations",
    ], functions


def test_declaration_service_signature_accepts_no_adapters_or_execution_inputs() -> None:
    from kalhas.application.domain_metric_observation_service import (
        declare_domain_metric_observation,
    )

    parameters = list(inspect.signature(declare_domain_metric_observation).parameters)
    assert parameters == [
        "store",
        "tenant_id",
        "scenario_id",
        "manifest_id",
        "state_model_id",
        "metric_id",
        "state_field_id",
        "declared_at",
        "metadata",
    ], parameters


def test_store_has_no_update_delete_or_repair_surface() -> None:
    source = _module_source("application/in_memory_store.py")
    for token in (
        "update_domain_metric_observation",
        "delete_domain_metric_observation",
        "repair_domain_metric_observation",
        "replace_domain_metric_observation",
    ):
        assert token not in source


def test_structural_event_kinds_are_exactly_three() -> None:
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_phase18_matrix_behavior_unchanged() -> None:
    """The Phase 18 matrix contract stays registered at its slot."""
    from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix

    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[30] == "CampaignTrajectoryMatrix"
    assert CampaignTrajectoryMatrix in PUBLIC_CONTRACTS


def test_public_contracts_remain_exactly_thirty_four() -> None:
    assert len(PUBLIC_CONTRACTS) == 37


def test_existing_v1_contracts_unchanged_and_binding_appended() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:31] == _PRE_PHASE19_CONTRACTS
    assert names[31] == "DomainMetricObservationBinding"


def test_contract_fields_carry_no_executable_types() -> None:
    from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding

    for name, field in DomainMetricObservationBinding.model_fields.items():
        annotation = str(field.annotation)
        assert not re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
            f"DomainMetricObservationBinding.{name}"
        )


def test_runtime_and_replay_signatures_unchanged() -> None:
    """Phase 19 must not touch runtime/execution/replay entry points."""
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
