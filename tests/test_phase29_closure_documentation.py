"""Documentation guards for the Phase 29 closure (H29-S09B).

These tests read documentation and the generated Model Pack artifacts as data.
They import no pack and make no network call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_CHANGELOG_HEADING = "## [Phase 29] — 2026-11-01"
_OVERLAY_HEADING = "## Phase 29 completion status (2026-11-01 closure overlay)"
_ADR_PATH = "docs/decisions/ADR-005-versioned-domain-pack-mechanism-and-model-pack-assurance.md"
_FOUNDATION_COMMIT = "1e15d14cac1594c1d74d724ce7f1b3cef6ad2609"

_REQUIRED_FACTS = (
    "kalhas-conformance-stockflow",
    "conformance_only",
    "experimental",
    "no benchmark evidence",
    "catalogued",
    "not yet consumed by campaign outcomes",
)

_FORBIDDEN_PHRASES = (
    "government_ready",
    "government-ready",
    "production-ready",
    "production_ready",
    "production-safe",
    "certified",
    "universally validated",
    "autonomous action",
    "predicts reality",
    "guaranteed outcome",
    "calibrated forecast",
    "pan is benchmarked",
    "benchmark evidence exists for pan",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _from_heading(relative: str, heading: str, *, until: str | None = None) -> str:
    """The raw text from ``heading`` to the next ``until`` prefix line, or the end."""
    lines = _read(relative).splitlines()
    start = lines.index(heading)
    end = len(lines)
    if until is not None:
        for index in range(start + 1, len(lines)):
            if lines[index].startswith(until):
                end = index
                break
    return "\n".join(lines[start:end])


def _changelog_entry() -> str:
    return _from_heading("CHANGELOG.md", _CHANGELOG_HEADING, until="## [")


def _overlay(relative: str) -> str:
    return _from_heading(relative, _OVERLAY_HEADING)


def _readme_phase29_section() -> str:
    return _from_heading("README.md", "## Phase 29 — complete", until="## ")


def _adr_new_note() -> str:
    text = _read(_ADR_PATH)
    start = text.index("Implementation note (2026-11-01)")
    end = text.find("\n\n", start)
    return text[start:end]


def _catalogue() -> list[dict[str, object]]:
    data = json.loads(_read("model_packs/v1/catalogue.json"))
    assert isinstance(data, list)
    return data


def _phase29_texts() -> dict[str, str]:
    return {
        "README.md": _read("README.md"),
        "docs/architecture/README.md overlay": _overlay("docs/architecture/README.md"),
        "docs/architecture/contracts-and-lifecycle.md overlay": _overlay(
            "docs/architecture/contracts-and-lifecycle.md"
        ),
        "CHANGELOG.md entry": _changelog_entry(),
        "docs/model-packs/README.md": _read("docs/model-packs/README.md"),
    }


def test_phase29_facts_are_present_in_every_closure_document() -> None:
    for name, text in _phase29_texts().items():
        normalized = _normalize(text)
        for fact in _REQUIRED_FACTS:
            assert fact in normalized, f"{fact!r} missing from {name}"


def test_readme_phase29_status_is_single_and_numbers_agree() -> None:
    readme = _read("README.md")
    headings = [line for line in readme.splitlines() if line.startswith("## Phase 29")]
    assert headings == ["## Phase 29 — complete"]
    assert _FOUNDATION_COMMIT in _readme_phase29_section()

    badge = re.search(r"badge/tests-([0-9%A-F]+)%20green", readme)
    assert badge is not None
    badge_count = badge.group(1).replace("%2C", "")
    gate = re.search(r"Latest full-suite gate: \*\*([0-9,]+) tests collected; exit code 0", readme)
    assert gate is not None
    changelog_gate = re.search(
        r"### Gate\n\n- ([0-9,]+) tests collected; exit code 0", _changelog_entry()
    )
    assert changelog_gate is not None
    assert badge_count == gate.group(1).replace(",", "")
    assert badge_count == changelog_gate.group(1).replace(",", "")


def test_catalogue_document_mirrors_the_catalogue_data() -> None:
    rows = [
        line for line in _read("docs/model-packs/README.md").splitlines() if line.startswith("|")
    ][2:]
    entries = _catalogue()
    assert len(rows) == 13
    assert len(entries) == 13
    for row, entry in zip(rows, entries, strict=True):
        metadata = entry["metadata"]
        assert isinstance(metadata, dict)
        assert f"`{entry['pack_id']}`" in row
        assert f"`{entry['displayed_maturity']}`" in row
        assert str(metadata["roadmap_wave"]) in row
        assert "kalhas-conformance-stockflow" not in row


def test_phase29_text_contains_no_overclaim() -> None:
    texts = dict(_phase29_texts())
    texts["ADR-005 2026-11-01 note"] = _adr_new_note()
    for name, text in texts.items():
        normalized = _normalize(text)
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase not in normalized, f"{phrase!r} in {name}"


def test_gate_surfaces_run_the_artifact_sync_check() -> None:
    for relative in ("CONTRIBUTING.md", "README.md", ".github/workflows/ci.yml"):
        assert "scripts/export_model_pack_artifacts.py --check" in _read(relative), relative


def test_gitattributes_pins_lf_for_every_evidence_reference() -> None:
    lines = _read(".gitattributes").splitlines()
    assert not [line for line in lines if line.startswith("*")]
    for artifact in (
        "model_packs/v1/assurance/kalhas-pan-0.1.0.json",
        "model_packs/v1/assurance/kalhas-conformance-stockflow-0.1.0.json",
    ):
        profile = json.loads(_read(artifact))
        for evidence in profile["evidence"]:
            pin = f"/{evidence['reference']} text eol=lf"
            assert pin in lines, f"{pin!r} missing from .gitattributes"


def test_adr005_records_the_closure_note_and_keeps_the_foundation_note() -> None:
    normalized = _normalize(_read(_ADR_PATH))
    assert "implementation note (2026-11-01)" in normalized
    assert "implementation note (2026-10-03)" in normalized
