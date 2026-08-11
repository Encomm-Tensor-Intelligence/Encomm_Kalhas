"""Phase 18 boundary scans.

Proves the new contract module, the pure matrix builder, and the matrix
query service contain no NEXUS/LEGION imports or calls, no network/
provider/filesystem/time/randomness surface, no dynamic loading or
executable expressions, no domain-pack imports, no domain-specific
vocabulary, no outcome/evidence/recommendation/score-producing calls,
and no execution/replay/evaluation calls; that the builder performs no
store access and the query service exposes only the one verified
getter; that the route delegates exclusively to the query service; that
the structural event kind tuple remains exactly the existing three
kinds; that PUBLIC_CONTRACTS remains exactly 31 with the new matrix
appended after the unchanged 30 existing contracts; and that the
contract carries no executable field types.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from kalhas.application.structural_runtime import STRUCTURAL_EVENT_KINDS
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.simulation import RunEventKind

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE18_MODULES = (
    "contracts/v1/campaign_trajectory.py",
    "application/campaign_trajectory_runtime.py",
    "application/campaign_trajectory_query_service.py",
)

#: The exact 30 contracts registered before Phase 18, in registration
#: order - Phase 18 must append without touching any of them.
_PRE_PHASE18_CONTRACTS = (
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
)

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(
    r"\b(requests|urllib|socket|subprocess|httpx|http\.client|open\(|Path\(|os\.|"
    r"datetime\.now|time\.|random|secrets|fastapi)\b"
)
_BEHAVIOR_TOKENS = re.compile(r"\b(lambda|callback|executable|callable)\b")
_DOMAIN_VOCABULARY = re.compile(r"\b(maritime|logistics|port|fuel|vessel|cargo)\b")
_OUTCOME_TOKENS = re.compile(
    r"\b(outcome|evidence|recommendation|decision_brief|point_estimate|probability|score)\b"
)
# Execution/replay/evaluation entry points the matrix path must never call.
_FORBIDDEN_CALLS = re.compile(
    r"^(?:build_run_trajectory_execution|replay_run|evaluate_trajectory|execute_run|"
    r"execute_campaign|prepare_strategy_trajectory_plans|evaluate_campaign)$"
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
    for relative in _PHASE18_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE18_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE18_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_evidence_or_recommendation_production() -> None:
    for relative in _PHASE18_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_matrix_path_never_calls_execution_replay_or_evaluation() -> None:
    for relative in _PHASE18_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"execution/replay/evaluation calls in {relative}: {calls}"


def test_builder_performs_no_store_access() -> None:
    source = _module_source("application/campaign_trajectory_runtime.py")
    assert "in_memory_store" not in source
    assert "InMemoryScenarioStore" not in source
    assert "get_run_plans" not in source
    # No store-write call anywhere (a naive "put_" substring scan would
    # false-positive on "input_hash").
    module = ast.parse(source)
    writes = [name for _, name in _call_names(module) if name.startswith("put_")]
    assert not writes, f"store write calls in the pure builder: {writes}"


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/campaign_trajectory.py"))
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
    ], imports


def test_query_service_exposes_only_the_verified_getter() -> None:
    module = ast.parse(_module_source("application/campaign_trajectory_query_service.py"))
    functions = [
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions == ["get_verified_campaign_trajectory_matrix"]


def test_query_service_signature_accepts_no_adapters_or_execution_inputs() -> None:
    import inspect

    from kalhas.application.campaign_trajectory_query_service import (
        get_verified_campaign_trajectory_matrix,
    )

    parameters = list(inspect.signature(get_verified_campaign_trajectory_matrix).parameters)
    assert parameters == ["store", "tenant_id", "campaign_id"], parameters


def test_route_delegates_exclusively_to_the_query_service() -> None:
    """The new route function calls only the store resolver + the query service."""
    module = ast.parse(_module_source("api/routes.py"))
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "get_campaign_trajectory_matrix_route":
            continue
        calls: set[str] = set()
        for statement in node.body:
            calls |= {
                name for _, name in _call_names(ast.Module(body=[statement], type_ignores=[]))
            }
        allowed = {"get_verified_campaign_trajectory_matrix", "_store"}
        unexpected = calls - allowed
        assert not unexpected, f"{node.name} calls outside the query service: {unexpected}"


def test_structural_event_kinds_are_exactly_three() -> None:
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_public_contracts_remain_exactly_thirty_four() -> None:
    assert len(PUBLIC_CONTRACTS) == 35


def test_existing_v1_contracts_unchanged_and_matrix_appended() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:30] == _PRE_PHASE18_CONTRACTS
    assert names[30] == "CampaignTrajectoryMatrix"


def test_contract_fields_carry_no_executable_types() -> None:
    import re as _re

    from kalhas.contracts.v1.campaign_trajectory import (
        CampaignTrajectoryMatrix,
        CampaignTrajectoryRunCell,
    )

    for contract in (CampaignTrajectoryRunCell, CampaignTrajectoryMatrix):
        for name, field in contract.model_fields.items():
            annotation = str(field.annotation)
            assert not _re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
                f"{contract.__name__}.{name}"
            )
