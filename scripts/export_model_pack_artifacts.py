"""Export the Model Pack assurance profiles and portfolio catalogue.

Usage (from the repository root):

    uv run python scripts/export_model_pack_artifacts.py           # write artifacts
    uv run python scripts/export_model_pack_artifacts.py --check   # verify artifacts are current

The artifacts are declarative, versioned data checked into
``model_packs/v1/``. They are generated deterministically from the live
pack release profiles and the exact bytes of the named evidence test
modules; never edit them by hand. There is no runtime registry, loader,
or kernel surface behind them, and no clock, network, or randomness is
used: every timestamp is the fixed ``DECLARED_AT``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.model_pack import (
    ModelPackAssuranceProfile,
    ModelPackCatalogueEntry,
    ModelPackEvidenceRecord,
    ModelPackReleaseProfile,
    ModelPackSupportedClaim,
)
from kalhas.domain_packs.conformance_stockflow import ConformanceStockFlowV01DomainPack
from kalhas.domain_packs.pan import PanV01DomainPack
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "model_packs" / "v1"

TENANT_ID = "kalhas-synthetic"
SCHEMA_VERSION = "1.0.0"
PACK_VERSION = "0.1.0"
DECLARED_AT = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

PAN_PACK_ID = "kalhas-pan"
FIXTURE_PACK_ID = "kalhas-conformance-stockflow"

PAN_ASSURANCE_PATH = "assurance/kalhas-pan-0.1.0.json"
FIXTURE_ASSURANCE_PATH = "assurance/kalhas-conformance-stockflow-0.1.0.json"
CATALOGUE_PATH = "catalogue.json"

#: (pack id, roadmap wave, summary) of the 13 portfolio entries, in order.
#: The wave records only the already-planned horizon; no post-35 ordering
#: is encoded anywhere.
PORTFOLIO: tuple[tuple[str, str, str], ...] = (
    (
        PAN_PACK_ID,
        "29-35",
        "Public health & biosecurity: outbreak, capacity, stockpile and conditional "
        "intervention comparison (synthetic v0.1)",
    ),
    (
        "kalhas-maritime-trade",
        "34A-35",
        "Ports, chokepoints and strategic supply chains under declared disruption branches",
    ),
    (
        "kalhas-quantum-readiness",
        "post-35",
        "Post-quantum cryptography transition planning; no cryptographic implementation, "
        "scanning, certification or quantum hardware",
    ),
    (
        "kalhas-climate-civil",
        "post-35",
        "Extreme-weather impacts and civil protection from pinned offline hazard "
        "ensembles; never replaces meteorological authorities",
    ),
    (
        "kalhas-energy-sec",
        "post-35",
        "Energy security: supply, storage, disruption and contingency scenarios",
    ),
    (
        "kalhas-food-water",
        "post-35",
        "Food and water security: shocks, reserves, allocation and affordability",
    ),
    (
        "kalhas-cyber-digital",
        "post-35",
        "Defensive digital-service resilience only; no exploit generation or live effects",
    ),
    (
        "kalhas-critical-resilience",
        "post-35",
        "Cross-sector infrastructure cascades and restoration order",
    ),
    (
        "kalhas-macro-fiscal",
        "post-35",
        "Conditional macro-fiscal scenarios; never an economic oracle or financial advice",
    ),
    (
        "kalhas-demography-capacity",
        "post-35",
        "Aggregate demography and public-service capacity; no individual scoring",
    ),
    (
        "kalhas-geo-policy",
        "post-35",
        "Declared geopolitical, trade and policy branches; no prediction of elections "
        "or persons, no persuasion",
    ),
    (
        "kalhas-robotics",
        "post-35",
        "Simulation-only fleet task allocation under energy, delay and failure constraints",
    ),
    (
        "kalhas-neuro-symbolic",
        "post-35",
        "Evaluation of reasoning and planning with rules and frozen model outputs",
    ),
)


def live_release_profiles() -> dict[str, ModelPackReleaseProfile]:
    """The live release profile of each assured pack, keyed by pack id."""
    return {
        PAN_PACK_ID: PanV01DomainPack().release_profile,
        FIXTURE_PACK_ID: ConformanceStockFlowV01DomainPack().release_profile,
    }


def _self_covering_hash(model: BaseModel) -> str:
    """The repository rule: SHA-256 of the canonical dump minus ``content_hash``."""
    dumped: dict[str, object] = model.model_dump(mode="json")
    dumped.pop("content_hash")
    return sha256_hex(canonical_json(dumped))


def _file_hash(reference: str) -> str:
    """SHA-256 of the exact bytes of one repository file."""
    return hashlib.sha256((REPO_ROOT / reference).read_bytes()).hexdigest()


def _evidence(evidence_id: str, kind: str, reference: str) -> ModelPackEvidenceRecord:
    return ModelPackEvidenceRecord.model_validate(
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "reference": reference,
            "content_hash": _file_hash(reference),
        }
    )


def _claim(claim_id: str, statement: str, evidence_ids: tuple[str, ...]) -> ModelPackSupportedClaim:
    return ModelPackSupportedClaim(
        claim_id=claim_id, statement=statement, evidence_ids=evidence_ids
    )


def _assurance_profile(
    pack_id: str,
    release_profile: ModelPackReleaseProfile,
    maturity: str,
    evidence: tuple[ModelPackEvidenceRecord, ...],
    claims: tuple[ModelPackSupportedClaim, ...],
    metadata: dict[str, object],
) -> ModelPackAssuranceProfile:
    payload = {
        "identifier": f"assurance-profile-{pack_id}-0-1-0",
        "tenant_id": TENANT_ID,
        "schema_version": SCHEMA_VERSION,
        "release_profile_id": release_profile.identifier,
        "release_profile_content_hash": release_profile.content_hash,
        "maturity": maturity,
        "evidence": [record.model_dump(mode="json") for record in evidence],
        "retained_failures": [],
        "supported_claims": [claim.model_dump(mode="json") for claim in claims],
        "content_hash": "0" * 64,
        "declared_at": DECLARED_AT.isoformat(),
        "metadata": metadata,
    }
    provisional = ModelPackAssuranceProfile.model_validate(payload)
    payload["content_hash"] = _self_covering_hash(provisional)
    return ModelPackAssuranceProfile.model_validate(payload)


def build_pan_assurance() -> ModelPackAssuranceProfile:
    """The evidence-derived assurance profile of PAN v0.1 (``experimental``)."""
    pack_tests = "pan-deterministic-execution-pack-tests"
    bridge = "pan-deterministic-execution-runtime4-bridge"
    shared = "pan-synthetic-conformance-shared-boundary"
    boundaries = "pan-synthetic-conformance-phase29-boundaries"
    evidence = (
        _evidence(pack_tests, "deterministic_execution", "tests/test_pan_domain_pack.py"),
        _evidence(bridge, "deterministic_execution", "tests/test_domain_mechanism_runtime.py"),
        _evidence(
            shared, "synthetic_conformance", "tests/test_phase29_shared_boundary_acceptance.py"
        ),
        _evidence(boundaries, "synthetic_conformance", "tests/test_phase29_boundaries.py"),
    )
    claims = (
        _claim(
            "deterministic-replay-on-recorded-platform",
            "Identical verified requests produce byte-identical results under the "
            "recorded platform identity",
            (pack_tests, bridge),
        ),
        _claim(
            "declared-invariants-hold-on-synthetic-fixtures",
            "Conservation, non-negativity and capacity invariants hold for the "
            "declared synthetic fixtures",
            (pack_tests,),
        ),
        _claim(
            "generic-seam-without-kernel-change",
            "The pack executes through the generic dispatcher and Runtime-4 bridge "
            "with no domain-specific kernel code",
            (shared, boundaries),
        ),
    )
    return _assurance_profile(
        PAN_PACK_ID,
        live_release_profiles()[PAN_PACK_ID],
        "experimental",
        evidence,
        claims,
        {"phase": "29", "synthetic_only": True, "empirical_adequacy_claim": False},
    )


def build_fixture_assurance() -> ModelPackAssuranceProfile:
    """The assurance profile of the conformance fixture (``conformance_only``)."""
    pack_tests = "conformance-stockflow-synthetic-conformance-pack-tests"
    shared = "conformance-stockflow-synthetic-conformance-shared-boundary"
    evidence = (
        _evidence(
            pack_tests,
            "synthetic_conformance",
            "tests/test_conformance_stockflow_domain_pack.py",
        ),
        _evidence(
            shared, "synthetic_conformance", "tests/test_phase29_shared_boundary_acceptance.py"
        ),
    )
    claims = (
        _claim(
            "generic-seam-without-kernel-change",
            "The fixture executes through the generic dispatcher and Runtime-4 bridge "
            "with no domain-specific kernel code",
            (pack_tests, shared),
        ),
    )
    return _assurance_profile(
        FIXTURE_PACK_ID,
        live_release_profiles()[FIXTURE_PACK_ID],
        "conformance_only",
        evidence,
        claims,
        {"phase": "29", "product_pack": False, "synthetic_only": True},
    )


def build_catalogue(pan_assurance: ModelPackAssuranceProfile) -> list[ModelPackCatalogueEntry]:
    """The 13-entry product portfolio; only PAN is bound to any profile."""
    pan_release = live_release_profiles()[PAN_PACK_ID]
    entries: list[ModelPackCatalogueEntry] = []
    for pack_id, wave, summary in PORTFOLIO:
        payload: dict[str, object] = {
            "identifier": f"catalogue-entry-{pack_id}-0-1-0",
            "tenant_id": TENANT_ID,
            "schema_version": SCHEMA_VERSION,
            "pack_id": pack_id,
            "pack_version": PACK_VERSION,
            "title": f"KALHAS {pack_id.removeprefix('kalhas-').upper()}",
            "summary": summary,
            "displayed_maturity": "catalogued",
            "content_hash": "0" * 64,
            "declared_at": DECLARED_AT.isoformat(),
            "metadata": {"roadmap_wave": wave},
        }
        if pack_id == PAN_PACK_ID:
            payload.update(
                release_profile_id=pan_release.identifier,
                release_profile_content_hash=pan_release.content_hash,
                assurance_profile_id=pan_assurance.identifier,
                assurance_profile_content_hash=pan_assurance.content_hash,
                displayed_maturity=pan_assurance.maturity,
            )
        provisional = ModelPackCatalogueEntry.model_validate(payload)
        payload["content_hash"] = _self_covering_hash(provisional)
        entries.append(ModelPackCatalogueEntry.model_validate(payload))
    return entries


def _render(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate_artifacts() -> dict[str, str]:
    """Every artifact as ``relative path -> exact LF-terminated text``."""
    pan = build_pan_assurance()
    fixture = build_fixture_assurance()
    catalogue = build_catalogue(pan)
    return {
        PAN_ASSURANCE_PATH: _render(pan.model_dump(mode="json")),
        FIXTURE_ASSURANCE_PATH: _render(fixture.model_dump(mode="json")),
        CATALOGUE_PATH: _render([entry.model_dump(mode="json") for entry in catalogue]),
    }


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    artifacts = generate_artifacts()
    if check_only:
        problems: list[str] = []
        for relative, content in artifacts.items():
            path = ARTIFACT_DIR / relative
            if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
                problems.append(relative)
        on_disk = (
            {path.relative_to(ARTIFACT_DIR).as_posix() for path in ARTIFACT_DIR.rglob("*")}
            if ARTIFACT_DIR.is_dir()
            else set()
        )
        on_disk_files = {name for name in on_disk if (ARTIFACT_DIR / name).is_file()}
        problems.extend(f"unexpected {name}" for name in sorted(on_disk_files - set(artifacts)))
        if problems:
            print("OUT OF SYNC: " + ", ".join(problems))
            return 1
        print("all model pack artifacts are synchronized")
        return 0
    for relative, content in artifacts.items():
        path = ARTIFACT_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
