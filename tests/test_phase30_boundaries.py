"""Phase 30 boundary tests pinned to ADR-006 (H30-S01).

ADR-006 is the specification of the offline dataset intake and the
``RawDatasetManifest`` contract. Every boundary here stays additive-safe:
nothing asserts the absence of a later intake slice's artifacts.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
ADR_PATH = (
    REPO_ROOT / "docs" / "decisions" / "ADR-006-offline-dataset-intake-and-raw-dataset-manifest.md"
)

_NEW_MODULES = (
    "contracts/v1/dataset.py",
    "application/raw_dataset_verifier.py",
    "application/raw_dataset_errors.py",
)

#: Whole-word domain vocabulary that must never appear in the neutral kernel
#: modules (identifiers or string literals).
_DOMAIN_WORDS = frozenset(
    {"pan", "pandemic", "covid", "hospital", "icu", "ecdc", "eurostat", "patient"}
)

_ALLOWED_EXACT_IMPORTS = frozenset(
    {
        "__future__",
        "typing",
        "collections.abc",
        "hashlib",
        "json",
        "math",
        "re",
        "datetime",
        "pydantic",
        "kalhas.application.hashing",
        "kalhas.application.domain_errors",
        "kalhas.application.raw_dataset_errors",
    }
)
_ALLOWED_IMPORT_PREFIXES = ("kalhas.contracts.v1.",)


def _adr_normalized() -> str:
    return re.sub(r"\s+", " ", ADR_PATH.read_text(encoding="utf-8")).lower()


def _words(text: str) -> set[str]:
    """Lowercase whole words of a text, splitting camelCase and underscores."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {word.lower() for word in re.findall(r"[A-Za-z]+", spaced)}


def test_adr006_is_accepted_and_dated() -> None:
    assert ADR_PATH.is_file(), "ADR-006 file is missing"
    normalized = _adr_normalized()
    assert "# adr 006: offline dataset intake and the raw-dataset manifest" in normalized
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-02" in normalized


def test_adr006_records_all_six_decisions() -> None:
    normalized = _adr_normalized()
    for heading in (
        "### d30-01a — offline, immutable, local bundles only",
        "### d30-01b — license classes and admissibility",
        "### d30-01c — raw-dataset manifest identity",
        "### d30-01d — checksum verification",
        "### d30-01e — vintages, lineage and holdout lock",
        "### d30-01f — first intended sources",
    ):
        assert heading in normalized, heading


def test_adr006_supersedes_nothing_and_claims_no_later_work() -> None:
    normalized = _adr_normalized()
    assert "this adr supersedes nothing" in normalized
    assert "must not be read as claiming any of them" in normalized


def test_adr006_freezes_the_manifest_name_license_classes_and_limits() -> None:
    normalized = _adr_normalized()
    assert "rawdatasetmanifest" in normalized
    assert "`public_domain`" in normalized
    assert "`attribution_commercial`" in normalized
    assert "only aggregate data is admissible" in normalized
    assert 'data_subject_level = "aggregate"' in normalized
    assert "25 mib" in normalized


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_carry_no_domain_vocabulary(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= _words(node.value)
        elif isinstance(node, ast.Name):
            found |= _words(node.id)
        elif isinstance(node, ast.Attribute):
            found |= _words(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found |= _words(node.name)
        elif isinstance(node, ast.arg):
            found |= _words(node.arg)
        elif isinstance(node, ast.alias):
            found |= _words(node.name)
            if node.asname:
                found |= _words(node.asname)
    assert not (found & _DOMAIN_WORDS), (relative, sorted(found & _DOMAIN_WORDS))


def test_domain_vocabulary_matching_is_whole_word() -> None:
    assert _words("expand the company span") & _DOMAIN_WORDS == set()
    assert _words("ICU_beds PatientRecord") & _DOMAIN_WORDS == {"icu", "patient"}


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_import_only_the_allowlist(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (relative, "relative import")
            names = [node.module or ""]
        else:
            continue
        for name in names:
            allowed = name in _ALLOWED_EXACT_IMPORTS or name.startswith(_ALLOWED_IMPORT_PREFIXES)
            assert allowed, (relative, name)


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_never_use_clock_constructors(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow"}, (relative, node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            assert not {alias.name for alias in node.names} & {"datetime", "date", "time"}, relative
