"""Offline disk-level checks of the committed raw dataset bundles (H30-D01).

Tamper tests copy the real bundle into a temporary directory and point the script at it
with ``--root``; they never touch the committed files.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from kalhas.contracts.v1.dataset import MAX_RAW_DATASET_TOTAL_BYTES, RawDatasetManifest
from pydantic import BaseModel

from tests.test_curated_dataset_contracts import (
    GOLDEN_OUTPUT,
    RAW_FILES,
    build_curated,
    build_raw_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "verify_dataset_bundles.py"
RAW_ROOT = REPO_ROOT / "datasets" / "v1" / "raw"
ECDC_ID = "ecdc-covid19-hospital-icu"
ATTRIBUTION_PREFIX = "Dataset provided by ECDC based on data provided by"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": ""},
    )


def _manifest_paths() -> list[Path]:
    return sorted(RAW_ROOT.glob("*/*/manifest.json"))


def _ecdc_manifest_path() -> Path:
    paths = sorted((RAW_ROOT / ECDC_ID).glob("*/manifest.json"))
    assert len(paths) == 1
    return paths[0]


def _ecdc_manifest() -> RawDatasetManifest:
    return RawDatasetManifest.model_validate_json(_ecdc_manifest_path().read_bytes())


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def scratch_root() -> Iterator[Path]:
    """A private temporary directory (pytest's own base temp is not writable here)."""
    with tempfile.TemporaryDirectory(prefix="kalhas-dataset-check-") as name:
        yield Path(name)


@pytest.fixture
def copied_root(scratch_root: Path) -> Path:
    shutil.copytree(REPO_ROOT / "datasets", scratch_root / "datasets")
    return scratch_root


def _bundle_dir(root: Path) -> Path:
    return next((root / "datasets" / "v1" / "raw" / ECDC_ID).iterdir())


def test_script_passes_on_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok datasets/v1/raw/{ECDC_ID}/" in result.stdout


def test_script_reports_no_bundles_for_an_empty_root(scratch_root: Path) -> None:
    result = _run(scratch_root)
    assert result.returncode == 0
    assert "no dataset bundles" in result.stdout


def test_every_committed_manifest_validates() -> None:
    paths = _manifest_paths()
    assert paths
    for path in paths:
        manifest = RawDatasetManifest.model_validate_json(path.read_bytes())
        assert path.parent.name == manifest.vintage
        assert path.parent.parent.name == manifest.dataset_id


def test_ecdc_bundle_declares_the_expected_terms_and_shape() -> None:
    manifest = _ecdc_manifest()
    assert manifest.license.license_class == "attribution_commercial"
    assert manifest.license.attribution_statement is not None
    assert manifest.license.attribution_statement.startswith(ATTRIBUTION_PREFIX)
    assert manifest.license.modifications_must_be_disclosed is True
    assert manifest.data_subject_level == "aggregate"
    assert manifest.revision_policy == "closed_series"
    assert manifest.dataset_id == ECDC_ID
    assert sum(file.byte_size for file in manifest.files) <= MAX_RAW_DATASET_TOTAL_BYTES
    assert _ecdc_manifest_path().parent.name == manifest.vintage
    assert manifest.metadata["modification_notice"] == "none — raw bytes as published"


def test_ecdc_manifest_is_canonical_lf_json() -> None:
    raw = _ecdc_manifest_path().read_bytes()
    assert b"\r" not in raw
    manifest = RawDatasetManifest.model_validate_json(raw)
    expected = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )
    assert raw.decode("utf-8") == expected


def test_datasets_readme_carries_the_verbatim_attribution() -> None:
    statement = _ecdc_manifest().license.attribution_statement
    assert statement is not None
    readme = (REPO_ROOT / "datasets" / "README.md").read_text(encoding="utf-8")
    assert statement in readme
    assert "no modification — raw bytes as published" in readme


def test_gitattributes_keeps_raw_bytes_untouched() -> None:
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "/datasets/** -text" in lines
    assert not [line for line in lines if line.startswith("*")]


def test_script_never_writes(copied_root: Path) -> None:
    before = _tree_digest(copied_root)
    assert _run(copied_root).returncode == 0
    assert _tree_digest(copied_root) == before


def test_one_byte_change_is_detected(copied_root: Path) -> None:
    data = _bundle_dir(copied_root) / "data.csv"
    content = bytearray(data.read_bytes())
    content[-2] ^= 0x01
    data.write_bytes(bytes(content))
    result = _run(copied_root)
    assert result.returncode == 1
    assert "sha256_mismatch" in result.stdout


def test_an_extra_file_is_detected(copied_root: Path) -> None:
    (_bundle_dir(copied_root) / "extra.csv").write_bytes(b"x")
    result = _run(copied_root)
    assert result.returncode == 1
    assert "undeclared_file" in result.stdout


def test_an_extra_nested_file_is_detected(copied_root: Path) -> None:
    nested = _bundle_dir(copied_root) / "sub"
    nested.mkdir()
    (nested / "extra.csv").write_bytes(b"x")
    result = _run(copied_root)
    assert result.returncode == 1
    assert "undeclared_file" in result.stdout


def test_a_missing_file_is_detected(copied_root: Path) -> None:
    (_bundle_dir(copied_root) / "data.csv").unlink()
    result = _run(copied_root)
    assert result.returncode == 1
    assert "missing_file" in result.stdout


def test_a_manifest_edit_with_a_stale_content_hash_is_detected(copied_root: Path) -> None:
    path = _bundle_dir(copied_root) / "manifest.json"
    text = path.read_text(encoding="utf-8")
    edited = text.replace("ECDC ceased updates", "ECDC stopped updates", 1)
    assert edited != text
    path.write_text(edited, encoding="utf-8", newline="\n")
    result = _run(copied_root)
    assert result.returncode == 1
    assert "content_hash_mismatch" in result.stdout


def test_a_renamed_vintage_directory_is_an_identity_failure(copied_root: Path) -> None:
    bundle = _bundle_dir(copied_root)
    bundle.rename(bundle.parent / "2099-01-01")
    result = _run(copied_root)
    assert result.returncode == 1
    assert "identity_mismatch" in result.stdout


def test_a_directory_without_a_manifest_is_a_failure(copied_root: Path) -> None:
    (_bundle_dir(copied_root) / "manifest.json").unlink()
    result = _run(copied_root)
    assert result.returncode == 1
    assert "missing_manifest" in result.stdout


def test_failure_output_never_contains_bytes_or_hashes(copied_root: Path) -> None:
    data = _bundle_dir(copied_root) / "data.csv"
    data.write_bytes(data.read_bytes() + b"tamper")
    result = _run(copied_root)
    manifest = _ecdc_manifest()
    assert result.returncode == 1
    assert manifest.files[0].sha256 not in result.stdout
    assert manifest.content_hash not in result.stdout
    assert "tamper" not in result.stdout


def test_nothing_under_kalhas_references_datasets_or_the_script() -> None:
    for path in sorted((REPO_ROOT / "kalhas").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "datasets/" not in text, path
        assert "verify_dataset_bundles" not in text, path


# --- synthetic raw -> curated chain in a temporary root ----------------------------------------


def _render(model: BaseModel) -> str:
    dumped = model.model_dump(mode="json")
    return json.dumps(dumped, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.fixture
def chain_root(scratch_root: Path) -> Path:
    raw = build_raw_manifest()
    raw_dir = scratch_root / "datasets/v1/raw" / raw.dataset_id / raw.vintage
    raw_dir.mkdir(parents=True)
    (raw_dir / "manifest.json").write_text(_render(raw), encoding="utf-8", newline="\n")
    for path, content in RAW_FILES.items():
        (raw_dir / path).write_bytes(content)
    curated = build_curated(raw=raw)
    curated_dir = (
        scratch_root / "datasets/v1/curated" / curated.curated_dataset_id / curated.curation_version
    )
    curated_dir.mkdir(parents=True)
    (curated_dir / "manifest.json").write_text(_render(curated), encoding="utf-8", newline="\n")
    (curated_dir / "clean.csv").write_bytes(GOLDEN_OUTPUT)
    return scratch_root


def _curated_dir(root: Path) -> Path:
    return root / "datasets/v1/curated/synthetic-clean/1.0.0"


def test_the_script_passes_on_a_synthetic_raw_and_curated_chain(chain_root: Path) -> None:
    result = _run(chain_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok datasets/v1/raw/synthetic-weekly/2026-11-02" in result.stdout
    assert "ok datasets/v1/curated/synthetic-clean/1.0.0" in result.stdout


def test_the_chain_check_never_writes(chain_root: Path) -> None:
    before = _tree_digest(chain_root)
    assert _run(chain_root).returncode == 0
    assert _tree_digest(chain_root) == before


def test_a_curated_byte_tamper_fails(chain_root: Path) -> None:
    data = _curated_dir(chain_root) / "clean.csv"
    content = bytearray(data.read_bytes())
    content[0] ^= 0x01
    data.write_bytes(bytes(content))
    result = _run(chain_root)
    assert result.returncode == 1
    assert "FAIL datasets/v1/curated/synthetic-clean/1.0.0: sha256_mismatch" in result.stdout
    assert "ok datasets/v1/raw/synthetic-weekly/2026-11-02" in result.stdout


def test_a_missing_referenced_raw_bundle_fails(chain_root: Path) -> None:
    shutil.rmtree(chain_root / "datasets/v1/raw")
    result = _run(chain_root)
    assert result.returncode == 1
    assert "FAIL datasets/v1/curated/synthetic-clean/1.0.0: raw_input_missing" in result.stdout


def test_a_raw_tamper_fails_the_raw_and_the_curated_bundle(chain_root: Path) -> None:
    source = chain_root / "datasets/v1/raw/synthetic-weekly/2026-11-02/source.csv"
    content = bytearray(source.read_bytes())
    content[-3] ^= 0x01
    source.write_bytes(bytes(content))
    result = _run(chain_root)
    assert result.returncode == 1
    assert "FAIL datasets/v1/raw/synthetic-weekly/2026-11-02: sha256_mismatch" in result.stdout
    assert "FAIL datasets/v1/curated/synthetic-clean/1.0.0: raw_input_invalid" in result.stdout


def test_an_extra_curated_file_fails(chain_root: Path) -> None:
    (_curated_dir(chain_root) / "extra.csv").write_bytes(b"x")
    result = _run(chain_root)
    assert result.returncode == 1
    assert "undeclared_file" in result.stdout


def test_a_renamed_curated_version_directory_is_an_identity_failure(chain_root: Path) -> None:
    directory = _curated_dir(chain_root)
    directory.rename(directory.parent / "9.9.9")
    result = _run(chain_root)
    assert result.returncode == 1
    assert "identity_mismatch" in result.stdout


def test_a_curated_directory_without_a_manifest_fails(chain_root: Path) -> None:
    (_curated_dir(chain_root) / "manifest.json").unlink()
    result = _run(chain_root)
    assert result.returncode == 1
    assert "missing_manifest" in result.stdout
