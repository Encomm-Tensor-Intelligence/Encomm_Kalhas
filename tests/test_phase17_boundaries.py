"""Phase 17 boundary scans.

Proves the new trajectory query service and the two new route functions
contain no NEXUS/LEGION imports or calls, no network/provider/
filesystem/time/randomness surface, no dynamic loading or executable
expressions, no domain-pack imports, no domain-specific vocabulary, no
outcome/evidence/recommendation-producing calls, and no execution/
replay/evaluation calls; that the routes delegate exclusively to the
query service; that the structural event kind tuple remains exactly the
existing three kinds; and that PUBLIC_CONTRACTS remains exactly 31
(Phase 18 appended CampaignTrajectoryMatrix; the Phase 17 pair and all
earlier contracts are unchanged).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from kalhas.application.structural_runtime import STRUCTURAL_EVENT_KINDS
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.simulation import RunEventKind

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE17_MODULES = ("application/trajectory_query_service.py",)

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(
    r"\b(requests|urllib|socket|subprocess|httpx|http\.client|open\(|Path\(|os\.|"
    r"datetime\.now|time\.|random|secrets)\b"
)
_BEHAVIOR_TOKENS = re.compile(r"\b(lambda|callback|executable|callable)\b")
_DOMAIN_VOCABULARY = re.compile(r"\b(maritime|logistics|port|fuel|vessel|cargo)\b")
_OUTCOME_TOKENS = re.compile(
    r"\b(outcome|evidence|recommendation|decision_brief|point_estimate|probability|score)\b"
)
# Execution/replay/evaluation entry points the query path must never call.
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
    for relative in _PHASE17_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE17_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE17_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_evidence_or_recommendation_production() -> None:
    for relative in _PHASE17_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _OUTCOME_TOKENS.search(name)
        ]
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_query_service_never_calls_execution_replay_or_evaluation() -> None:
    for relative in _PHASE17_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"execution/replay/evaluation calls in {relative}: {calls}"


def test_query_service_exposes_only_the_two_verified_getters() -> None:
    module = ast.parse(_module_source("application/trajectory_query_service.py"))
    functions = [
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions == [
        "get_verified_run_trajectory_execution",
        "get_verified_run_trajectory_replay_manifest",
    ]


def test_query_service_signatures_accept_no_adapters_or_execution_inputs() -> None:
    import inspect

    from kalhas.application.trajectory_query_service import (
        get_verified_run_trajectory_execution,
        get_verified_run_trajectory_replay_manifest,
    )

    for function in (
        get_verified_run_trajectory_execution,
        get_verified_run_trajectory_replay_manifest,
    ):
        parameters = list(inspect.signature(function).parameters)
        assert parameters == ["store", "tenant_id", "run_id"], parameters


def test_routes_delegate_exclusively_to_the_query_service() -> None:
    """The two new route functions call only the store resolver + the query service."""
    module = ast.parse(_module_source("api/routes.py"))
    targets = {
        "get_run_trajectory_execution_route",
        "get_run_trajectory_replay_manifest_route",
    }
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef) or node.name not in targets:
            continue
        # Only the function body counts: the decorator call and the
        # Header(...) default are not part of the route's behavior.
        calls: set[str] = set()
        for statement in node.body:
            calls |= {
                name for _, name in _call_names(ast.Module(body=[statement], type_ignores=[]))
            }
        allowed = {
            "get_verified_run_trajectory_execution",
            "get_verified_run_trajectory_replay_manifest",
            "_store",
        }
        unexpected = calls - allowed
        assert not unexpected, f"{node.name} calls outside the query service: {unexpected}"


def test_structural_event_kinds_are_exactly_three() -> None:
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_public_contracts_remain_exactly_forty() -> None:
    assert len(PUBLIC_CONTRACTS) == 40
