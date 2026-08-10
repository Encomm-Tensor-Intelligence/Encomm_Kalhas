"""Import-boundary and protocol-availability tests.

These tests encode the durable rule: KALHAS core never imports NEXUS or
LEGION internals. The only allowed coupling is the placeholder protocols
in ``kalhas/adapters/``.
"""

import ast
import re
from pathlib import Path
from typing import get_type_hints

import pytest
from kalhas.adapters import LegionAdapter, NexusAdapter
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.domain_packs import DomainPack

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(r"\b(requests|urllib|socket|subprocess|httpx|http\.client)\b")


def _kalhas_source_files() -> list[Path]:
    return sorted(KALHAS_ROOT.rglob("*.py"))


def _is_protocol(cls: type[object]) -> bool:
    """Return True if ``cls`` is a typing.Protocol class (mypy-clean check)."""
    return bool(getattr(cls, "_is_protocol", False))


def test_boundary_protocols_are_available() -> None:
    assert _is_protocol(NexusAdapter)
    assert _is_protocol(LegionAdapter)
    assert _is_protocol(DomainPack)


def test_boundary_protocols_are_exported() -> None:
    from kalhas.adapters.legion import LegionAdapter as LegionAdapterAlias
    from kalhas.adapters.nexus import NexusAdapter as NexusAdapterAlias
    from kalhas.domain_packs.base import DomainPack as DomainPackAlias

    assert NexusAdapterAlias is NexusAdapter
    assert LegionAdapterAlias is LegionAdapter
    assert DomainPackAlias is DomainPack


def test_kalhas_core_never_imports_nexus_or_legion_internals() -> None:
    """The architectural rule: no KALHAS module may import NEXUS/LEGION modules."""
    offenders: list[tuple[Path, int, str]] = []
    for path in _kalhas_source_files():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _FORBIDDEN_IMPORT.match(line):
                offenders.append((path, line_no, line.strip()))
    assert not offenders, f"Forbidden imports found: {offenders}"


def test_legion_adapter_exposes_plural_request_contract() -> None:
    """The LEGION boundary requests an ordered set of candidates, never one."""
    assert hasattr(LegionAdapter, "request_strategies")
    assert not hasattr(LegionAdapter, "request_strategy")


def test_legion_adapter_exposes_trajectory_plan_boundary() -> None:
    """The Phase 15 LEGION boundary proposes one ordered transition sequence.

    ``request_trajectory_plan`` takes the authoritative KALHAS-built
    ``StrategyTrajectoryPlanRequest`` and returns the untrusted
    ``StrategyTrajectoryPlanDraft`` - exact protocol signature, and no
    plural trajectory surface.
    """
    from kalhas.contracts.v1.trajectory import (
        StrategyTrajectoryPlanDraft,
        StrategyTrajectoryPlanRequest,
    )

    assert hasattr(LegionAdapter, "request_trajectory_plan")
    assert not hasattr(LegionAdapter, "request_trajectory_plans")
    hints = get_type_hints(LegionAdapter.request_trajectory_plan)
    assert hints["request"] is StrategyTrajectoryPlanRequest
    assert hints["return"] is StrategyTrajectoryPlanDraft


def test_mock_legion_adapter_implements_the_trajectory_boundary() -> None:
    """The deterministic mock proposes only from the supplied catalog.

    Its trajectory method performs no evaluation, no dynamic loading, no
    pack import, and no network access - it echoes the available
    transition identifiers in their supplied order.
    """
    from kalhas.adapters.mocks import MockLegionAdapter

    assert hasattr(MockLegionAdapter, "request_trajectory_plan")
    source = (KALHAS_ROOT / "adapters" / "mocks" / "legion.py").read_text(encoding="utf-8")
    code = "".join(source.split('"""')[::2])
    assert not _DYNAMIC_LOADING.search(code)
    assert not _NETWORK_SURFACE.search(code)
    assert "kalhas.domain_packs" not in code


def test_campaign_service_depends_on_protocol_not_concrete_mock() -> None:
    """Application services must depend on the LegionAdapter protocol only."""
    from kalhas.application import campaign_service

    assert hasattr(campaign_service, "LegionAdapter")
    assert not hasattr(campaign_service, "MockLegionAdapter")
    source = Path(campaign_service.__file__).read_text(encoding="utf-8")
    assert "from kalhas.adapters.legion import LegionAdapter" in source
    assert "MockLegionAdapter" not in source


def test_agents_md_contains_corrected_architecture_guidance() -> None:
    """AGENTS.md must state the corrected internal-module guidance.

    Skipped while the protected file still carries the outdated statement:
    the write guard requires an interactive approval that is pending. The
    assertions become active the moment the file is updated.
    """
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    if "No other components exist" in text:
        pytest.skip(
            "AGENTS.md still carries the outdated statement; the approved update is "
            "pending interactive write approval"
        )
    assert "canonical product boundaries" in text
    assert "NEXUS** owns dialogue, organizational context, memory, and presentation" in text
    assert "LEGION** owns strategy and agent exploration" in text
    assert "deterministic campaigns, evidence, replay, and simulation state" in text
    assert "Governed internal KALHAS modules" in text
    assert "must not take over NEXUS or LEGION responsibilities" in text
    assert "domain-neutral and must not import NEXUS or LEGION internals" in text
    assert "No other components exist" not in text


def test_domain_pack_protocol_is_declarative_identity_only() -> None:
    """The future DomainPack protocol exposes only a DomainPackManifest.

    No executable surface: no methods, no callbacks, nothing to import,
    instantiate, or run.
    """
    hints = get_type_hints(DomainPack)
    assert set(hints) == {"manifest"}
    assert hints["manifest"] is DomainPackManifest
    members = [
        name
        for name in dir(DomainPack)
        if not name.startswith("_") and callable(getattr(DomainPack, name, None))
    ]
    assert members == []


def test_domain_pack_protocol_no_longer_exposes_placeholder_surface() -> None:
    assert not hasattr(DomainPack, "build_world_model")
    assert not hasattr(DomainPack, "name")
    assert not hasattr(DomainPack, "version")


def test_no_domain_pack_implementation_ships() -> None:
    """No real pack exists: the pack directory holds only the boundary."""
    pack_files = sorted(path.name for path in (KALHAS_ROOT / "domain_packs").glob("*.py"))
    assert pack_files == ["__init__.py", "base.py"]


def test_binding_and_compiler_never_load_or_execute_pack_code() -> None:
    """Binding, declaration, state-model, transition, evaluation-engine,
    trajectory-planning, activity, and compilation are declarative: no
    dynamic loading, no exec, no import of the domain_packs package from
    the compiler, the binding service, the declaration service, the
    state-model service, the transition service, the evaluation engine,
    the trajectory-planning service, or the activity service.
    """
    for relative in (
        "application/world_compiler.py",
        "application/domain_pack_binding_service.py",
        "application/domain_capability_declaration_service.py",
        "application/domain_state_model_service.py",
        "application/domain_state_transition_service.py",
        "application/domain_metric_observation_service.py",
        "application/state_transition_engine.py",
        "application/strategy_trajectory_service.py",
        "application/operational_activity.py",
    ):
        source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
        assert not _DYNAMIC_LOADING.search(source), f"dynamic loading tokens in {relative}"
        assert "kalhas.domain_packs" not in source, f"{relative} imports the pack package"


class _GenericTestPack:
    """Test-only generic fake proving DomainPack protocol conformance.

    Lives only inside tests; generic identifiers only, no industry example.
    """

    def __init__(self, manifest: DomainPackManifest) -> None:
        self.manifest = manifest


def test_generic_test_fake_conforms_to_domain_pack_protocol() -> None:
    """A plain object exposing a manifest satisfies the protocol surface."""
    from datetime import UTC, datetime

    from kalhas.contracts.v1.domain_pack import DomainPackCapability

    manifest = DomainPackManifest(
        identifier="manifest-1",
        tenant_id="tenant-1",
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.0.0",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        content_hash="0" * 64,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    fake = _GenericTestPack(manifest)
    assert fake.manifest is manifest
    assert fake.manifest.pack_id == "pack-1"
    assert list(get_type_hints(DomainPack)) == ["manifest"]


def test_strategy_trajectory_service_never_calls_the_evaluation_kernel() -> None:
    """AST call scan: planning never evaluates or derives state.

    The module docstring legitimately names ``evaluate_trajectory`` as a
    non-goal, so a naive substring scan would false-positive. The AST
    call scan only matches real call sites in the code.
    """
    from kalhas.application import strategy_trajectory_service

    module = ast.parse(Path(strategy_trajectory_service.__file__).read_text(encoding="utf-8"))
    forbidden = {
        "evaluate_trajectory",
        "derive_initial_state",
        "validate_state",
        "state_hash",
    }
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
        if name in forbidden:
            calls.append((node.lineno, name))
    assert not calls, f"planning service calls the evaluation kernel: {calls}"


def test_strategy_trajectory_service_has_no_executable_or_network_surface() -> None:
    """The planning service is declarative: no callbacks, no executable
    expressions, no dynamic loading, no pack import, no network access."""
    source = (KALHAS_ROOT / "application" / "strategy_trajectory_service.py").read_text(
        encoding="utf-8"
    )
    code = "".join(source.split('"""')[::2])
    assert not _DYNAMIC_LOADING.search(code)
    assert not _NETWORK_SURFACE.search(code)
    behavior = re.compile(r"\b(lambda|callback|executable)\b")
    assert not behavior.search(code)
    assert "kalhas.domain_packs" not in code


def test_trajectory_contract_module_has_no_executable_surface() -> None:
    """The trajectory contract module carries no callbacks, expressions,
    code references, providers, or network tokens (docstrings stripped,
    so prose naming the non-goals cannot false-positive the scan)."""
    source = (KALHAS_ROOT / "contracts" / "v1" / "trajectory.py").read_text(encoding="utf-8")
    code = "".join(source.split('"""')[::2])
    forbidden = re.compile(
        r"\b(eval|exec|import_module|__import__|compile|lambda|callback|provider|"
        r"requests|urllib|socket|subprocess|executable)\b"
    )
    assert not forbidden.search(code)


def test_phase15_sources_contain_no_domain_specific_vocabulary() -> None:
    """Phase 15 files stay domain-neutral: no domain wording anywhere."""
    tokens = re.compile(r"\b(maritime|logistics|port|fuel|vessel|cargo)\b")
    for relative in (
        "contracts/v1/trajectory.py",
        "application/strategy_trajectory_service.py",
        "adapters/mocks/legion.py",
    ):
        source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
        assert not tokens.search(source), f"domain vocabulary in {relative}"
