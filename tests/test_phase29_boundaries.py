"""Phase 29 architecture boundaries: ADR-005 decisions proven durably.

These tests verify that ADR-005 (``docs/decisions/ADR-005-versioned-
domain-pack-mechanism-and-model-pack-assurance.md``) records the accepted
Phase 29 decisions D29-01, D29-02, D29-03, and D34-01, and that the
repository still honors the durable replacement invariants: the shipped v1
domain-pack contracts stay frozen, legacy manifest records stay valid and
inert, the single ``DomainPack`` boundary evolves additively, concrete
packs stay isolated below ``kalhas/domain_packs/`` and are never
dynamically discovered or kernel-imported, and no simulator dependency,
forbidden maturity status, or kernel-side domain vocabulary exists. The
six frozen artifact names (D29-01) are recorded in the ADR-005 freeze
list for later slices to implement; nothing here requires those names to
remain absent from the repository permanently.

The tests are deliberately non-brittle: they pin decisions (recorded
rules, frozen bytes, absent machinery), not future implementation files.
Later Phase 29 slices (``H29-S02A`` through ``H29-S09``) can implement
the accepted design without another permanent-boundary rewrite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints

import pytest
from kalhas.application.domain_pack_registry import build_manifest, manifest_content_hash
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs import DomainPack
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "ADR-005-versioned-domain-pack-mechanism-and-model-pack-assurance.md"
)

#: Planned additive public artifact names frozen by D29-01 for later
#: slices. The ADR-005 freeze list is the single source of truth for
#: these names; later Phase 29 slices implement them as versioned
#: public artifacts over the same DomainPack identity.
FROZEN_FUTURE_ARTIFACT_NAMES = (
    "DomainMechanismSpec",
    "DomainMechanismStepRequest",
    "DomainMechanismStepResult",
    "ModelPackReleaseProfile",
    "ModelPackAssuranceProfile",
    "ModelPackCatalogueEntry",
)

#: Maturity vocabulary of D29-03.
MATURITY_VALUES = (
    "catalogued",
    "conformance_only",
    "experimental",
    "benchmarked",
    "externally_reviewed",
    "partner_evaluation_ready",
)


def _normalized(source: str) -> str:
    """Lowercased, whitespace-collapsed text without markdown emphasis."""
    stripped = source.replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _adr_normalized() -> str:
    return _normalized(ADR_PATH.read_text(encoding="utf-8"))


def _kalhas_relative_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        sources[path.relative_to(KALHAS_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return sources


# ---------------------------------------------------------------------------
# Frozen-payload helpers (D29-01): byte-level freeze proof for shipped v1
# ---------------------------------------------------------------------------

_FIXED_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_FIXED_STAMP = "2026-01-01T12:00:00Z"


def _frozen_manifest_payload() -> dict[str, object]:
    return {
        "identifier": "manifest-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1", "in-2"],
                "output_ids": ["out-1"],
                "metadata": {"declared": True},
            }
        ],
        "schema_metadata": {"declarative": True},
        "content_hash": _FIXED_HASH,
        "created_at": _FIXED_STAMP,
        "metadata": {"owner": "foundation"},
    }


def _frozen_binding_payload() -> dict[str, object]:
    return {
        "identifier": "binding-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": _FIXED_HASH,
        "capability_ids": ["cap-1"],
        "bound_at": _FIXED_STAMP,
    }


def _frozen_declaration_payload() -> dict[str, object]:
    return {
        "identifier": "declaration-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": _FIXED_HASH,
        "capability_id": "cap-1",
        "input_values": {"in-1": 1, "in-2": "a"},
        "content_hash": _FIXED_HASH,
        "declared_at": _FIXED_STAMP,
    }


def _canonical_payload_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Section A: ADR-005 records the accepted Phase 29 decisions
# ---------------------------------------------------------------------------


def test_phase29_adr_records_all_required_decisions() -> None:
    """ADR-005 exists, is Accepted 2026-09-13, and records D29-01..D34-01."""
    assert ADR_PATH.is_file(), "ADR-005 file is missing"
    normalized = _adr_normalized()
    assert "# adr 005: versioned domainpack mechanism and model pack assurance" in normalized
    assert "- status: accepted" in normalized
    assert "- date: 2026-09-13" in normalized
    for heading in (
        "### d29-01 — versioned evolution of the manifest-only domainpack protocol",
        "### d29-02 — pure mechanism seam, composition, and identity semantics",
        "### d34-01 — phase 29 numerical/platform decision",
        "### d29-03 — model pack product vocabulary, profiles, and maturity",
    ):
        assert heading in normalized, f"missing ADR section: {heading}"


def test_adr005_supersedes_only_the_phase0_manifest_only_limitation() -> None:
    """Only the Phase-0 manifest-only limitation is superseded.

    Domain-neutrality and no-live-effects decisions of ADR-002 stay in
    force; no other ADR is superseded.
    """
    normalized = _adr_normalized()
    assert "supersedes only the phase-0 manifest-only limitation in adr-002" in normalized
    assert (
        "domain-neutrality decisions and its no-live-effects decisions remain fully in force"
        in (normalized)
    )
    assert "supersedes adr-002" not in normalized
    assert "supersedes adr-004" not in normalized


def test_adr005_claims_no_later_slice_work_exists() -> None:
    """The ADR must not claim implemented future work.

    Contracts, mechanisms, PAN, dispatcher, runtime integration,
    cross-platform proof, benchmark evidence, and Model Pack maturity are
    the work of later slices and must not be claimed as existing.
    """
    normalized = _adr_normalized()
    assert "later slices (h29-s02a through h29-s09) implement these decisions" in normalized
    forbidden_claims = (
        "pan pack exists",
        "dispatcher is implemented",
        "cross-platform proof exists in phase 29",
        "benchmark evidence exists for pan",
        "pan is benchmarked",
        "pan is externally reviewed",
        "pan is partner evaluation ready",
    )
    for claim in forbidden_claims:
        assert claim not in normalized, f"ADR claims unimplemented work: {claim}"
    assert "at the time of writing, no executable mechanism contract, pan pack" in normalized
    assert "must not be read as claiming any of them" in normalized


def test_phase29_future_artifact_names_are_frozen_in_the_adr() -> None:
    """All six planned artifact names are frozen in the ADR-005 freeze list.

    The ADR freeze list is the single source of truth for the planned
    additive public artifact names; later Phase 29 slices implement them.
    Nothing here requires the names to remain absent from the repository:
    once a later authorized slice implements an artifact, its exact name
    simply continues to be verified as frozen in the ADR.
    """
    adr_source = ADR_PATH.read_text(encoding="utf-8")
    for name in FROZEN_FUTURE_ARTIFACT_NAMES:
        assert name in adr_source, f"{name} missing from the ADR-005 freeze list"


# ---------------------------------------------------------------------------
# Section B: D29-01 — frozen contracts and inert legacy records
# ---------------------------------------------------------------------------


def test_shipped_v1_domain_pack_contracts_remain_byte_and_semantically_frozen() -> None:
    """The shipped v1 manifest/binding/declaration surface is unchanged.

    Byte check: the contract module still declares exactly the four
    shipped v1 classes. Semantic check: canonical serialized payloads for
    all three shipped identity contracts hash to their accepted values,
    frozen fields cannot be reassigned, and unknown fields are still
    rejected.
    """
    contract_source = (KALHAS_ROOT / "contracts" / "v1" / "domain_pack.py").read_text(
        encoding="utf-8"
    )
    assert "class DomainPackCapability(BaseModel):" in contract_source
    assert "class DomainPackManifest(VersionedContract):" in contract_source
    assert "class DomainPackBinding(VersionedContract):" in contract_source
    assert "class DomainCapabilityDeclaration(VersionedContract):" in contract_source

    manifest = DomainPackManifest.model_validate(_frozen_manifest_payload())
    binding = DomainPackBinding.model_validate(_frozen_binding_payload())
    declaration = DomainCapabilityDeclaration.model_validate(_frozen_declaration_payload())
    assert _canonical_payload_hash(manifest.model_dump(mode="json")) == _canonical_payload_hash(
        _frozen_manifest_payload()
    )
    assert _canonical_payload_hash(binding.model_dump(mode="json")) == _canonical_payload_hash(
        _frozen_binding_payload()
    )
    assert _canonical_payload_hash(declaration.model_dump(mode="json")) == _canonical_payload_hash(
        _frozen_declaration_payload()
    )
    with pytest.raises(ValidationError):
        manifest.pack_version = "2.0.0"
    with pytest.raises(ValidationError):
        DomainPackManifest.model_validate({**_frozen_manifest_payload(), "unexpected": True})


def test_existing_manifest_records_stay_valid_inert_and_never_autoexecutable() -> None:
    """Registration/binding/world inputs keep their inert historical meaning.

    Manifest registration remains deterministic inert metadata: identical
    drafts always produce the identical computed content hash, the hash is
    never the placeholder, recomputation matches, and the registry still
    documents that nothing is loaded or executed.
    """
    registry_source = (KALHAS_ROOT / "application" / "domain_pack_registry.py").read_text(
        encoding="utf-8"
    )
    assert "nothing in this module loads, imports, instantiates, or executes a pack" in (
        registry_source
    )
    capability = DomainPackCapability(
        identifier="cap-1",
        description="Declared capability",
        input_ids=("in-1", "in-2"),
        output_ids=("out-1",),
        metadata={"declared": True},
    )
    schema_metadata: dict[str, JsonValue] = {"declarative": True}
    manifest_metadata: dict[str, JsonValue] = {"owner": "foundation"}
    created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    built = [
        build_manifest(
            tenant_id="tenant-1",
            identifier="manifest-1",
            pack_id="pack-1",
            name="Reference domain pack",
            pack_version="1.2.3",
            description="Declarative pack metadata only",
            supported_api_versions=("1",),
            capabilities=(capability,),
            schema_metadata=dict(schema_metadata),
            created_at=created_at,
            metadata=dict(manifest_metadata),
        ),
        build_manifest(
            tenant_id="tenant-1",
            identifier="manifest-1",
            pack_id="pack-1",
            name="Reference domain pack",
            pack_version="1.2.3",
            description="Declarative pack metadata only",
            supported_api_versions=("1",),
            capabilities=(capability,),
            schema_metadata=dict(schema_metadata),
            created_at=created_at,
            metadata=dict(manifest_metadata),
        ),
    ]
    assert built[0].content_hash == built[1].content_hash
    assert built[0].content_hash != "0" * 64
    assert manifest_content_hash(built[0]) == built[0].content_hash


# ---------------------------------------------------------------------------
# Section C: D29-01 — single additive boundary, fail-closed identity
# ---------------------------------------------------------------------------


def test_domain_pack_boundary_remains_the_single_pack_protocol() -> None:
    """Exactly one Python pack boundary exists: the DomainPack protocol.

    The protocol keeps its required ``manifest`` annotation of the frozen
    v1 ``DomainPackManifest`` type. ADR-005 (D29-01) evolves the protocol
    additively - later authorized slices add the ``release_profile``,
    mechanism protocol version, and ``step(request) -> result`` members -
    so this test pins only the durable invariants: the manifest annotation,
    the single-protocol boundary, and the package export.
    """
    assert getattr(DomainPack, "_is_protocol", False) is True
    from kalhas.contracts.v1.domain_pack import DomainPackManifest

    hints = get_type_hints(DomainPack)
    assert hints.get("manifest") is DomainPackManifest
    base_source = (KALHAS_ROOT / "domain_packs" / "base.py").read_text(encoding="utf-8")
    module = ast.parse(base_source)
    class_defs = [node for node in module.body if isinstance(node, ast.ClassDef)]
    assert [cls.name for cls in class_defs] == ["DomainPack"]
    init_source = (KALHAS_ROOT / "domain_packs" / "__init__.py").read_text(encoding="utf-8")
    init_tree = ast.parse(init_source)
    dunder_all = [
        node.value
        for node in init_tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__all__"
    ]
    assert len(dunder_all) == 1
    assert ast.literal_eval(dunder_all[0]) == ["DomainPack"]


def test_executable_pack_identity_is_additive_and_fails_closed() -> None:
    """Executable identity is additive; missing identity never promotes.

    The ADR records the exact executable surface (manifest, release
    profile, mechanism protocol version 1.0.0, one pure ``step``), and
    records that a legacy manifest-only carrier is not executable and that
    missing/mismatched executable identity fails closed.
    """
    normalized = _adr_normalized()
    assert "mechanism protocol version 1.0.0" in normalized
    assert "one pure step(request) -> result operation" in normalized
    assert "a legacy manifest-only carrier remains valid as inert metadata" in normalized
    assert "it is not an executable pack" in normalized
    assert "missing or mismatched executable identity" in normalized
    assert "fails closed" in normalized
    assert "nothing silently promotes inert metadata into executable behavior" in normalized
    assert "no second component, plugin bus, pack runtime, executable registry," in normalized
    assert "dynamic discovery mechanism, or alternate integration protocol is created" in normalized
    assert "runtime 4 remains the only execution authority" in normalized


def test_manifest_only_carrier_remains_valid_but_is_not_executable() -> None:
    """A manifest-only object still satisfies the legacy surface.

    It proves inert legacy manifest compatibility (ADR-005, D29-01) and is
    not an executable pack: it carries no step operation, and nothing here
    loads or executes domain behavior.
    """

    class _LegacyCarrier:
        def __init__(self, manifest: DomainPackManifest) -> None:
            self.manifest = manifest

    carrier = _LegacyCarrier(DomainPackManifest.model_validate(_frozen_manifest_payload()))
    assert carrier.manifest.pack_id == "pack-1"
    assert not hasattr(carrier, "step")
    assert not hasattr(_LegacyCarrier, "step")


# ---------------------------------------------------------------------------
# Section D: D29-02 — pure mechanism semantics, composition, identity
# ---------------------------------------------------------------------------


def test_mechanism_semantics_and_purity_are_accepted() -> None:
    """The ADR freezes the pure transition and full mechanism isolation.

    The mechanism performs none of the banned accesses and cannot choose
    policy, compare strategies, persist authority, schedule a second
    simulation, or call NEXUS/LEGION.
    """
    normalized = _adr_normalized()
    assert (
        "verified state + validated action + ordered, coordinate-addressed exogenous inputs"
        in normalized
    )
    assert "+ immutable configuration -> verified next state + typed emissions" in normalized
    assert "+ deterministic mechanism evidence" in normalized
    for purity in (
        "performs no filesystem, network, provider, database, clock,",
        "environment, dynamic-import, subprocess, global-state, or global-rng",
        "access. it reads no wall clock, environment variable, mutable global, or",
        "global random source; all randomness arrives as already-addressed",
        "exogenous input.",
    ):
        assert purity in normalized, f"missing purity statement: {purity}"
    for inability in (
        "cannot choose policy, compare strategies, persist authority,",
        "schedule a second simulation, or call nexus or legion.",
    ):
        assert inability in normalized, f"missing inability: {inability}"


def test_composition_is_explicit_and_identity_is_behavior_affecting() -> None:
    """Composition passes objects; identity covers every behavior input.

    Runtime 4 stays the only scheduler/execution authority and invokes the
    mechanism exactly once at the declared step; randomness is
    coordinate-addressed and failures are atomic.
    """
    normalized = _adr_normalized()
    assert "composition is explicit: callers hand a concrete conforming domainpack" in normalized
    assert "object to the seam. identifiers or import paths carried inside public data" in (
        normalized
    )
    assert "never load code; dynamic resolution from data fails closed" in normalized
    assert "runtime 4 remains the only scheduler/execution authority" in normalized
    assert "invokes the mechanism exactly once at the declared step" in normalized
    assert "existing runtime-4 records" in normalized
    assert "retain their historical meaning" in normalized
    assert "never reinterpreted as mechanism executions" in normalized
    assert (
        "whose recorded coordinates bind world, realization/seed, run, step,"
        " stream, variable, entity/slot, and draw index"
    ) in normalized
    assert "mechanism branching, call order, retries, or scheduling cannot shift" in normalized
    assert "unrelated draws" in normalized
    assert "every failure is atomic" in normalized
    assert "no authority mutation" in normalized
    for identity in (
        "solver",
        "timestep",
        "event order",
        "precision",
        "rounding",
        "implementation",
        "dependency-lock",
        "configuration",
        "data identities",
    ):
        assert identity in normalized, f"missing identity component: {identity}"
    assert "requires a new appropriate identity/version; it is never an" in normalized
    assert "in-place change" in normalized


# ---------------------------------------------------------------------------
# Section E: D34-01 — platform-bound binary64 numerical decision
# ---------------------------------------------------------------------------


def test_phase29_numerical_platform_rule_is_platform_bound_binary64() -> None:
    """The recorded D34-01 rule is exact replay under platform identity."""
    normalized = _adr_normalized()
    assert "kalhas-platform-bound-binary64-v1" in normalized
    assert "exact replay only under a recorded platform identity" in normalized
    assert "option 2 of §16 phase 34b" in normalized
    assert "only exact built-in integers and finite" in normalized
    assert "ieee-754 binary64 values are accepted" in normalized
    assert "booleans, numeric strings," in normalized
    assert "decimal-like coercions, nan, infinities, and unrepresentable overflow" in normalized
    assert "fail closed" in normalized
    assert "arithmetic and reductions follow an explicitly declared stable order" in normalized
    assert "no unordered reduction and no implicit tolerance is authoritative" in normalized
    assert "round-to-nearest, ties-to-even at explicit" in normalized
    assert "named boundaries only. there is no hidden rounding or clipping" in normalized
    assert "platform identity binds os, architecture, python implementation/version," in normalized
    assert "dependency lock, mechanism implementation, solver, and the numeric" in normalized
    assert "replay requires identical authoritative bytes under the recorded platform" in normalized
    assert "phase 29 does not claim unexecuted linux/macos equivalence" in normalized
    assert "a platform mismatch rejects exact replay/comparison unless a later" in normalized
    assert "changing the numerical/platform rule changes identity/version" in normalized
    assert "canonical cross-platform fixtures may be created later" in normalized
    assert "windows-only run cannot claim cross-platform proof" in normalized


# ---------------------------------------------------------------------------
# Section F: D29-03 — Model Pack vocabulary, maturity, prohibited uses
# ---------------------------------------------------------------------------


def test_model_pack_vocabulary_binds_profiles_to_the_existing_identity() -> None:
    """Model Pack is vocabulary over one identity; no second source of truth."""
    normalized = _adr_normalized()
    assert "model pack is product vocabulary for one exact, versioned domainpack" in normalized
    assert "it is not a component," in normalized
    assert "protocol, registry, runtime, provider adapter, or plugin system" in normalized
    assert "modelpackreleaseprofile binds the exact manifest, mechanism," in normalized
    assert "modelpackassuranceprofile binds one exact release/profile hash to" in normalized
    assert "evidence, retained failures, bounded supported claims, review state, and" in normalized
    assert "evidence-derived maturity" in normalized
    assert "modelpackcatalogueentry is declarative catalogue metadata only" in normalized
    assert "cannot resolve or execute code and cannot establish implemented" in normalized
    assert "a catalogue entry creates no capability" in normalized
    assert "these artifacts remain bound to the existing domainpack" in normalized
    assert "no second executable registry or second source of" in normalized
    assert "truth is permitted" in normalized


def test_maturity_vocabulary_is_exact_and_never_transfers() -> None:
    """Maturity values, their binding, and the Phase 29 caps are recorded."""
    normalized = _adr_normalized()
    for value in MATURITY_VALUES:
        assert value in normalized, f"missing maturity value: {value}"
    assert "maturity and claims never transfer across pack versions, configurations," in normalized
    for dimension in (
        "mechanisms",
        "implementations",
        "dependencies",
        "datasets",
        "vintages",
        "geographies",
        "horizons",
        "platforms",
        "domains",
    ):
        assert dimension in normalized, f"missing transfer dimension: {dimension}"
    assert "pan may reach only experimental in phase 29" in normalized
    assert "the synthetic non-health fixture is always conformance_only" in normalized
    assert "every other portfolio entry remains catalogued" in normalized
    assert "no phase 28-35 artifact may assign government_ready, certified," in normalized
    for forbidden in ("universally validated", "autonomous", "production-safe"):
        assert forbidden in normalized


def test_public_sector_prohibited_use_floor_is_recorded() -> None:
    """The §11 public-sector prohibited-use floor is preserved verbatim."""
    normalized = _adr_normalized()
    assert "the public-sector prohibited-use floor of strategic §11 is preserved" in normalized
    assert "all packs are decision support only" in normalized
    for prohibited in (
        "autonomous public",
        "eligibility/benefit decisions",
        "enforcement recommendations",
        "predictive-policing judgments",
        "individual or social scoring",
        "political persuasion",
        "voter targeting",
        "biometric/surveillance assessment",
        "offensive cyber action",
    ):
        assert prohibited in normalized, f"missing prohibited use: {prohibited}"
    assert "outputs remain labeled conditional" in normalized
    assert "modeled outcomes with accountable human authority visible" in normalized


def test_external_simulators_stay_reference_only_with_no_dependencies() -> None:
    """Covasim/Starsim/GLEAM are reference-only; nothing may be added."""
    normalized = _adr_normalized()
    for simulator in ("covasim", "starsim", "gleam/gleamviz"):
        assert simulator in normalized, f"missing simulator reference: {simulator}"
    assert "are reference-only" in normalized
    assert "authorizes no import, dependency, server/client adapter, callback" in normalized
    assert "surface, dataset assumption, network call, or execution authority" in normalized
    assert "none may be added to dependencies or kernel surfaces" in normalized
    assert "phase 29 uses synthetic/reference fixtures only" in normalized
    assert "adds no dependency" in normalized
    assert "no real, personal, or company data" in normalized
    assert "phase 29 changes neither nexusadapter nor legionadapter" in normalized
    assert "concrete conformance work remains phase 31" in normalized
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    for simulator in ("covasim", "starsim", "gleam"):
        assert simulator not in lock.lower(), f"{simulator} appears in uv.lock"


def test_kernel_sources_gain_no_domain_vocabulary_or_pack_machinery() -> None:
    """Generic kernel sources stay domain-neutral and free of machinery.

    The kernel excludes ``kalhas/domain_packs/`` itself (packs own their
    domain vocabulary by ADR-002/ADR-005), so this scan pins: no
    pandemic/simulator vocabulary or forbidden maturity status in generic
    kernel code, and no dynamic discovery/import machinery anywhere under
    ``kalhas/``.
    """
    vocabulary = re.compile(
        r"(pandemic|compartmen|infection|epidemi|pathogen|covasim|starsim|gleam|"
        r"government_ready|production-safe)",
        re.IGNORECASE,
    )
    machinery = re.compile(
        r"\b(pkgutil|walk_packages|iter_modules|entry_points|import_module|"
        r"importlib|__import__)\b"
    )
    for relative, source in _kalhas_relative_sources().items():
        assert not machinery.search(source), f"pack discovery machinery in {relative}"
        if relative.startswith("domain_packs/"):
            continue
        assert not vocabulary.search(source), f"domain vocabulary in {relative}"
