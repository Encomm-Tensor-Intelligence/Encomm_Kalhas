"""Import-boundary and protocol-availability tests.

These tests encode the durable rule: KALHAS core never imports NEXUS or
LEGION internals. The only allowed coupling is the placeholder protocols
in ``kalhas/adapters/``.

Since ADR-005 (Phase 29, D29-01) the ``DomainPack`` boundary is no longer
permanently manifest-only: an executable pack surface becomes possible
additively while legacy manifest records stay valid and inert. This module
keeps the protocol/annotation checks and the durable isolation rule
(concrete packs live only below ``kalhas/domain_packs/``, are never
dynamically discovered, and generic kernel code may import only the public
``DomainPack`` protocol from the pack package - never a concrete pack);
the accepted Phase 29 mechanism/assurance architecture is proven in
``tests/test_phase29_boundaries.py``.
"""

import ast
import re
from pathlib import Path
from typing import get_type_hints

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
    """AGENTS.md deterministically asserts the authoritative architecture guidance."""
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)

    assert (
        "NEXUS** owns natural-language dialogue, organizational context, memory, and "
        "presentation" in normalized
    )
    assert "LEGION** owns strategy and agent exploration" in normalized
    assert (
        "KALHAS** owns versioned world models, uncertainty, deterministic simulation" in normalized
    )
    assert "campaigns, evidence, replay" in normalized
    assert "No other components exist" in normalized
    assert "Do not introduce new components or integration surfaces" in normalized
    assert "the three named roles are the only allowed ones" in normalized
    assert "Ordinary internal KALHAS modules are implementation details within KALHAS" in normalized
    assert "not additional components or integration surfaces" in normalized
    assert "must remain within KALHAS responsibilities" in normalized
    assert "must not take over NEXUS or LEGION responsibilities" in normalized
    assert "Domain-neutral kernel" in normalized
    assert "contains no domain-specific logic" in normalized
    assert "domain packs" in normalized
    assert "KALHAS core never imports NEXUS or LEGION modules" in normalized
    assert "NexusAdapter" in normalized
    assert "LegionAdapter" in normalized


def test_domain_pack_protocol_manifest_annotation_is_preserved() -> None:
    """The protocol keeps its manifest annotation of the frozen v1 type.

    ADR-005 (D29-01) preserves every existing manifest meaning: the
    ``manifest`` attribute remains part of the protocol surface and its
    annotation stays exactly the shipped v1 ``DomainPackManifest``.
    """
    hints = get_type_hints(DomainPack)
    assert hints["manifest"] is DomainPackManifest


def test_domain_pack_protocol_no_longer_exposes_placeholder_surface() -> None:
    """The historical Phase 0 placeholder stays forbidden (ADR-002)."""
    assert not hasattr(DomainPack, "build_world_model")
    assert not hasattr(DomainPack, "name")
    assert not hasattr(DomainPack, "version")


def test_top_level_domain_pack_infrastructure_exposes_protocol_only() -> None:
    """Durable ADR-005 isolation rule for top-level pack infrastructure.

    ``kalhas/domain_packs/`` top-level infrastructure exposes the
    ``DomainPack`` protocol only: no concrete pack implementation lives at
    the top level. Concrete packs, once introduced by later Phase 29
    slices, must live isolated below ``kalhas/domain_packs/`` (for example
    in dedicated subpackages) and never at the top level next to the
    protocol itself.
    """
    top_level = sorted(path.name for path in (KALHAS_ROOT / "domain_packs").glob("*.py"))
    assert top_level == ["__init__.py", "base.py"]
    source = (KALHAS_ROOT / "domain_packs" / "__init__.py").read_text(encoding="utf-8")
    assert "DomainPack" in source


def test_kernel_code_never_imports_concrete_packs_or_discovers_them() -> None:
    """Concrete packs are never dynamically discovered or kernel-imported.

    Generic kernel code (everything outside ``kalhas/domain_packs/``) may
    import only the public ``DomainPack`` protocol, and only from
    ``kalhas.domain_packs`` or ``kalhas.domain_packs.base`` (ADR-005,
    D29-01). Imports of concrete pack subpackages/modules and of any
    concrete pack symbol stay forbidden, as is dynamic discovery/import
    machinery that could load a pack by name. Packs reach the kernel only
    as explicitly supplied conforming objects.

    The import rule is enforced by AST inspection of import statements,
    not by a broad substring ban.
    """
    import_offenders: list[str] = []
    machinery_offenders: list[str] = []
    for path in _kalhas_source_files():
        relative = path.relative_to(KALHAS_ROOT).as_posix()
        if relative.startswith("domain_packs/"):
            continue
        source = path.read_text(encoding="utf-8")
        if _DYNAMIC_LOADING.search(source):
            machinery_offenders.append(relative)
        tree = ast.parse(source)
        package_parts = path.relative_to(KALHAS_ROOT).parent.parts
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kalhas.domain_packs" or alias.name.startswith(
                        "kalhas.domain_packs."
                    ):
                        import_offenders.append(f"{relative}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # Resolve a relative import against the file's package.
                    base_parts = package_parts[: len(package_parts) - (node.level - 1)]
                    resolved = ".".join(base_parts)
                    if node.module:
                        resolved = f"{resolved}.{node.module}"
                else:
                    resolved = node.module or ""
                # Any import resolving into a ``domain_packs`` package is in
                # scope (including sibling subpackage-relative imports); the
                # only permitted form is the public protocol from the
                # canonical top-level locations.
                if "domain_packs" not in resolved.split("."):
                    continue
                for alias in node.names:
                    allowed = (
                        resolved == "kalhas.domain_packs" or resolved == "kalhas.domain_packs.base"
                    ) and alias.name == "DomainPack"
                    if not allowed:
                        import_offenders.append(
                            f"{relative}:{node.lineno}: from {resolved} import {alias.name}"
                        )
    assert not import_offenders, f"kernel pack-import offenders: {import_offenders}"
    assert not machinery_offenders, f"kernel pack-discovery offenders: {machinery_offenders}"


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


class _LegacyManifestCarrier:
    """Test-only inert legacy manifest carrier, not a DomainPack implementation.

    Lives only inside tests; generic identifiers only, no industry example.
    It carries a manifest as inert metadata and deliberately has no
    executable surface: it does not conform to the executable DomainPack
    protocol surface (no ``step``) and never will be executed.
    """

    def __init__(self, manifest: DomainPackManifest) -> None:
        self.manifest = manifest


def test_legacy_manifest_carrier_stays_valid_inert_metadata_not_executable() -> None:
    """A manifest-only object is valid inert metadata, not an executable pack.

    This legacy manifest-only carrier stays valid as inert metadata
    (ADR-005, D29-01): it proves manifest compatibility only. It is NOT an
    executable DomainPack - it has no ``step`` operation, and nothing here
    loads or executes domain behavior.
    """
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
    fake = _LegacyManifestCarrier(manifest)
    assert fake.manifest is manifest
    assert fake.manifest.pack_id == "pack-1"
    # The carrier stays inert: a manifest-only object is not executable.
    assert not hasattr(fake, "step")


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
