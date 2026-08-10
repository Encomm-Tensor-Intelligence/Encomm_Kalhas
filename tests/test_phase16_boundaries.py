"""Phase 16 boundary scans.

Proves the new trajectory runtime, input resolution, integrity
verification, replay, and contract modules contain no NEXUS/LEGION
calls, no domain-pack execution or imports, no network/provider/
filesystem surface, no dynamic loading or executable expressions, no
outcome/evidence/recommendation production, and no domain-specific
vocabulary; that the structural event kind tuple remains exactly the
existing three kinds; and that execution and replay expose no
trajectory-supplying signature surface.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from kalhas.application.replay_service import replay_run
from kalhas.application.structural_runtime import (
    STRUCTURAL_EVENT_KINDS,
    execute_campaign,
    execute_run,
)
from kalhas.contracts.v1.simulation import RunEventKind

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE16_MODULES = (
    "application/run_trajectory_runtime.py",
    "application/run_trajectory_inputs.py",
    "application/trajectory_integrity.py",
    "application/replay_service.py",
    "contracts/v1/trajectory_execution.py",
)

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


def _code_only(source: str) -> str:
    """Strip docstrings so prose naming the non-goals cannot false-positive."""
    return "".join(source.split('"""')[::2])


def _module_source(relative: str) -> str:
    return (KALHAS_ROOT / relative).read_text(encoding="utf-8")


def test_no_nexus_or_legion_imports() -> None:
    for relative in _PHASE16_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE16_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE16_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_outcome_evidence_or_recommendation_production() -> None:
    """AST call scan: no outcome/evidence/recommendation-producing calls."""
    for relative in _PHASE16_MODULES:
        module = ast.parse(_module_source(relative))
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
            if _OUTCOME_TOKENS.search(name):
                calls.append((node.lineno, name))
        assert not calls, f"outcome-producing calls in {relative}: {calls}"


def test_structural_event_kinds_are_exactly_three() -> None:
    assert tuple(STRUCTURAL_EVENT_KINDS) == (
        RunEventKind.RUN_STARTED,
        RunEventKind.STRATEGY_DECLARATION_RECORDED,
        RunEventKind.RUN_COMPLETED,
    )


def test_execution_and_replay_signatures_expose_no_trajectory_inputs() -> None:
    import inspect

    assert list(inspect.signature(execute_run).parameters) == ["store", "tenant_id", "run_id"]
    assert list(inspect.signature(execute_campaign).parameters) == [
        "store",
        "tenant_id",
        "campaign_id",
    ]
    assert list(inspect.signature(replay_run).parameters) == ["store", "tenant_id", "run_id"]


def test_contract_module_fields_are_json_safe() -> None:
    """Structural proof: no field annotation can express executable content."""
    from kalhas.contracts.v1.trajectory_execution import (
        RunStateTrajectoryResult,
        RunTrajectoryAttemptRecord,
        RunTrajectoryExecution,
        RunTrajectoryReplayManifest,
    )

    for contract in (
        RunTrajectoryAttemptRecord,
        RunStateTrajectoryResult,
        RunTrajectoryExecution,
        RunTrajectoryReplayManifest,
    ):
        for name, field in contract.model_fields.items():
            annotation = str(field.annotation)
            # Word boundaries: "exec" is a substring of the module name
            # "trajectory_execution" inside annotations.
            assert not re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
                f"{contract.__name__}.{name}"
            )
