"""Offline disk-level checks of the committed raw dataset bundles (H30-D01).

Tamper tests copy the real bundle into a temporary directory and point the script at it
with ``--root``; they never touch the committed files.
"""

from __future__ import annotations

import functools
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


@functools.cache
def _run_repository() -> subprocess.CompletedProcess[str]:
    return _run(REPO_ROOT)


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


# --- committed ECDC curated bundle (H30-D02) ---------------------------------------------


ECDC_CURATED = "ecdc-covid19-hospital-icu-by-indicator"
ECDC_CURATED_PATH = f"datasets/v1/curated/{ECDC_CURATED}/1.0.0"
ECDC_OUTPUTS = {
    "daily-hospital-occupancy.csv",
    "daily-icu-occupancy.csv",
    "weekly-hospital-admissions-per-100k.csv",
    "weekly-icu-admissions-per-100k.csv",
}


def test_committed_ecdc_curated_bundle_and_completeness() -> None:
    import csv

    from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest

    directory = REPO_ROOT / ECDC_CURATED_PATH
    manifest = CuratedDatasetManifest.model_validate_json(
        (directory / "manifest.json").read_bytes()
    )
    raw = _ecdc_manifest()
    assert manifest.tenant_id == "kalhas-reference"
    assert manifest.license == raw.license
    assert {file.path for file in manifest.files} == ECDC_OUTPUTS
    assert len(manifest.files) == 4

    def row_count(path: Path, encoding: str) -> int:
        with path.open(encoding=encoding, newline="") as source:
            reader = csv.reader(source)
            next(reader)
            return sum(1 for _ in reader)

    raw_count = row_count(_ecdc_manifest_path().parent / "data.csv", "utf-8-sig")
    assert sum(row_count(directory / name, "utf-8") for name in ECDC_OUTPUTS) == raw_count

    readme = (REPO_ROOT / "datasets/README.md").read_text(encoding="utf-8")
    assert raw.license.attribution_statement is not None
    assert raw.license.attribution_statement in readme
    assert manifest.modification_notice in readme

    result = _run_repository()
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok {ECDC_CURATED_PATH}" in result.stdout


def test_committed_ecdc_curated_byte_tamper_fails(copied_root: Path) -> None:
    data = copied_root / ECDC_CURATED_PATH / "daily-hospital-occupancy.csv"
    content = bytearray(data.read_bytes())
    content[-2] ^= 0x01
    data.write_bytes(bytes(content))
    result = _run(copied_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_CURATED_PATH}: sha256_mismatch" in result.stdout


def test_committed_ecdc_curated_missing_file_fails(copied_root: Path) -> None:
    (copied_root / ECDC_CURATED_PATH / "daily-hospital-occupancy.csv").unlink()
    result = _run(copied_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_CURATED_PATH}: missing_file" in result.stdout


# --- synthetic split bundle --------------------------------------------------------------


@pytest.fixture
def split_chain_root(scratch_root: Path) -> Path:
    from tests.test_dataset_split_engine import RAW_FILES as SPLIT_RAW_FILES
    from tests.test_dataset_split_engine import build_split, synthetic_chain

    raw, curated, files = synthetic_chain()
    raw_dir = scratch_root / "datasets/v1/raw" / raw.dataset_id / raw.vintage
    raw_dir.mkdir(parents=True)
    (raw_dir / "manifest.json").write_text(_render(raw), encoding="utf-8", newline="\n")
    for name, content in SPLIT_RAW_FILES.items():
        (raw_dir / name).write_bytes(content)
    curated_dir = (
        scratch_root / "datasets/v1/curated" / curated.curated_dataset_id / curated.curation_version
    )
    curated_dir.mkdir(parents=True)
    (curated_dir / "manifest.json").write_text(_render(curated), encoding="utf-8", newline="\n")
    for name, content in files.items():
        (curated_dir / name).write_bytes(content)
    split = build_split(curated, files)
    split_dir = scratch_root / "datasets/v1/splits" / split.split_id / split.split_version
    split_dir.mkdir(parents=True)
    (split_dir / "manifest.json").write_text(_render(split), encoding="utf-8", newline="\n")
    return scratch_root


def test_split_chain_script_passes(split_chain_root: Path) -> None:
    result = _run(split_chain_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok datasets/v1/splits/synthetic/1.0.0" in result.stdout


def test_split_chain_rejects_extra_file(split_chain_root: Path) -> None:
    (split_chain_root / "datasets/v1/splits/synthetic/1.0.0/extra").write_bytes(b"x")
    result = _run(split_chain_root)
    assert result.returncode == 1
    assert "undeclared_file" in result.stdout


def test_split_chain_rejects_manifest_edit(split_chain_root: Path) -> None:
    path = split_chain_root / "datasets/v1/splits/synthetic/1.0.0/manifest.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("Calendar and geography", "Different calendar and geography"),
        encoding="utf-8",
        newline="\n",
    )
    result = _run(split_chain_root)
    assert result.returncode == 1
    assert "content_hash_mismatch" in result.stdout


def test_split_chain_rejects_missing_curated(split_chain_root: Path) -> None:
    shutil.rmtree(split_chain_root / "datasets/v1/curated")
    result = _run(split_chain_root)
    assert result.returncode == 1
    assert "curated_input_missing" in result.stdout


# --- committed ECDC split (H30-D03) ------------------------------------------------------


ECDC_SPLIT_PATH = "datasets/v1/splits/ecdc-covid19-hospital-icu-primary/1.0.0"


def test_ecdc_split_fixed_rule_and_sealed_holdout() -> None:
    import csv

    from kalhas.application.dataset_split_errors import SealedPartitionError
    from kalhas.application.dataset_split_verifier import select_partition_rows
    from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
    from kalhas.contracts.v1.dataset_split import DatasetSplitManifest

    split = DatasetSplitManifest.model_validate_json(
        (REPO_ROOT / ECDC_SPLIT_PATH / "manifest.json").read_bytes()
    )
    directory = REPO_ROOT / ECDC_CURATED_PATH
    curated = CuratedDatasetManifest.model_validate_json((directory / "manifest.json").read_bytes())
    assert split.tenant_id == "kalhas-reference"
    assert split.curated_manifest_id == curated.identifier
    assert split.curated_content_hash == curated.content_hash
    assert split.curated_bundle_hash == curated.bundle_hash
    assert split.split_id == "ecdc-covid19-hospital-icu-primary"
    assert split.split_version == "1.0.0"
    assert split.metadata["geography_holdout_procedure"] == "sha256-rank-ascending-top-5"

    labels_by_file: dict[str, set[str]] = {}
    counts_by_file: dict[str, int] = {}
    files = {}
    for file in curated.files:
        files[file.path] = (directory / file.path).read_bytes()
        with (directory / file.path).open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source)
            country = next(reader).index("country")
            labels: set[str] = set()
            count = 0
            for row in reader:
                labels.add(row[country])
                count += 1
            labels_by_file[file.path] = labels
            counts_by_file[file.path] = count
    all_labels = set().union(*labels_by_file.values())
    holdout = sorted(
        all_labels, key=lambda label: hashlib.sha256(label.encode("utf-8")).hexdigest()
    )[:5]
    assert len(holdout) == 5
    assert split.metadata["geography_holdout_set"] == holdout
    assert [rule.path for rule in split.file_rules] == [file.path for file in curated.files]
    for rule, membership in zip(split.file_rules, split.memberships, strict=True):
        assert rule.path == membership.path
        assert rule.time_rule is not None
        if rule.path.startswith("daily-"):
            assert (
                rule.time_rule.column,
                rule.time_rule.value_type,
                rule.time_rule.validation_from,
                rule.time_rule.holdout_from,
            ) == ("date", "date", "2022-07-01", "2023-01-01")
        else:
            assert (
                rule.time_rule.column,
                rule.time_rule.value_type,
                rule.time_rule.validation_from,
                rule.time_rule.holdout_from,
            ) == ("year_week", "iso_week", "2022-W26", "2023-W01")
        expected = [label for label in holdout if label in labels_by_file[rule.path]]
        if expected:
            assert rule.geography_rule is not None
            assert rule.geography_rule.column == "country"
            assert rule.geography_rule.validation_values == ()
            assert list(rule.geography_rule.holdout_values) == expected
        else:
            assert rule.geography_rule is None
        counts = membership.counts
        assert counts.development + counts.validation + counts.holdout == counts_by_file[rule.path]
        with pytest.raises(SealedPartitionError):
            select_partition_rows(split, curated, files, rule.path, "holdout")
    result = _run_repository()
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok {ECDC_SPLIT_PATH}" in result.stdout
    assert split.preregistration_note in (REPO_ROOT / "datasets/README.md").read_text(
        encoding="utf-8"
    )


def test_ecdc_split_edited_cut_is_rejected(copied_root: Path) -> None:
    path = copied_root / ECDC_SPLIT_PATH / "manifest.json"
    text = path.read_text(encoding="utf-8")
    edited = text.replace('"validation_from": "2022-07-01"', '"validation_from": "2022-07-02"', 1)
    assert edited != text
    path.write_text(edited, encoding="utf-8", newline="\n")
    result = _run(copied_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_SPLIT_PATH}:" in result.stdout


def test_ecdc_split_extra_file_is_rejected(copied_root: Path) -> None:
    (copied_root / ECDC_SPLIT_PATH / "extra").write_bytes(b"x")
    result = _run(copied_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_SPLIT_PATH}: undeclared_file" in result.stdout


# --- synthetic protocol chain -------------------------------------------------------------


@pytest.fixture
def protocol_chain_root(scratch_root: Path) -> Path:
    from tests.test_benchmark_task_engine import chain

    raw, sources, curated, files, split, protocol = chain()
    raw_dir = scratch_root / "datasets/v1/raw" / raw.dataset_id / raw.vintage
    raw_dir.mkdir(parents=True)
    (raw_dir / "manifest.json").write_text(_render(raw), encoding="utf-8", newline="\n")
    for name, content in sources.items():
        (raw_dir / name).write_bytes(content)
    curated_dir = (
        scratch_root / "datasets/v1/curated" / curated.curated_dataset_id / curated.curation_version
    )
    curated_dir.mkdir(parents=True)
    (curated_dir / "manifest.json").write_text(_render(curated), encoding="utf-8", newline="\n")
    for name, content in files.items():
        (curated_dir / name).write_bytes(content)
    split_dir = scratch_root / "datasets/v1/splits" / split.split_id / split.split_version
    split_dir.mkdir(parents=True)
    (split_dir / "manifest.json").write_text(_render(split), encoding="utf-8", newline="\n")
    directory = (
        scratch_root / "benchmarks/v1/protocols" / protocol.protocol_id / protocol.protocol_version
    )
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(_render(protocol), encoding="utf-8", newline="\n")
    return scratch_root


def test_protocol_chain_passes(protocol_chain_root: Path) -> None:
    result = _run(protocol_chain_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok benchmarks/v1/protocols/synthetic/1.0.0" in result.stdout


def test_protocol_chain_extra_file_fails(protocol_chain_root: Path) -> None:
    (protocol_chain_root / "benchmarks/v1/protocols/synthetic/1.0.0/extra").write_bytes(b"x")
    result = _run(protocol_chain_root)
    assert result.returncode == 1
    assert "undeclared_file" in result.stdout


def test_protocol_chain_edited_manifest_fails(protocol_chain_root: Path) -> None:
    path = protocol_chain_root / "benchmarks/v1/protocols/synthetic/1.0.0/manifest.json"
    text = path.read_text(encoding="utf-8")
    edited = text.replace("Fixed without", "Changed without")
    assert edited != text
    path.write_text(edited, encoding="utf-8", newline="\n")
    result = _run(protocol_chain_root)
    assert result.returncode == 1
    assert "content_hash_mismatch" in result.stdout


def test_protocol_chain_missing_split_fails(protocol_chain_root: Path) -> None:
    shutil.rmtree(protocol_chain_root / "datasets/v1/splits")
    result = _run(protocol_chain_root)
    assert result.returncode == 1
    assert "split_input_missing" in result.stdout


def test_real_repository_has_verified_chain_and_locked_protocol() -> None:
    result = _run_repository()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok datasets/v1/raw/ecdc-covid19-hospital-icu/2026-11-02" in result.stdout
    assert "ok datasets/v1/curated/ecdc-covid19-hospital-icu-by-indicator/1.0.0" in result.stdout
    assert "ok datasets/v1/splits/ecdc-covid19-hospital-icu-primary/1.0.0" in result.stdout
    assert (
        "ok benchmarks/v1/protocols/ecdc-covid19-hospital-icu-primary-benchmark/1.0.0"
        in result.stdout
    )
    for partition in ("development", "validation"):
        for baseline in ("point", "quantile"):
            assert (
                f"ok benchmarks/v1/forecasts/ecdc-primary-persistence-{baseline}-{partition}/1.0.0"
                in result.stdout
            )
        assert (
            f"ok benchmarks/v1/reports/ecdc-primary-point-vs-quantile-{partition}/1.0.0"
            in result.stdout
        )


# --- committed ECDC protocol (H30-D04) ----------------------------------------------------

ECDC_PROTOCOL_PATH = "benchmarks/v1/protocols/ecdc-covid19-hospital-icu-primary-benchmark/1.0.0"
ECDC_PROTOCOL_NOTE = (
    "Targets, horizons (7, 14, 21 and 28 days; 1, 2, 3 and 4 ISO weeks), history rules "
    "(84 days with at least 8 points; 12 weeks with at least 4 points), the minimum of 100 "
    "evaluable tasks per target and horizon, the quantile levels, the scoring rule and the "
    "reference baseline with its threshold of 1 were fixed by the reviewer without inspecting "
    "outcome values. The non_negative declaration follows from the indicators being counts of "
    "patients and rates per population, not from inspecting values. Before locking, the reviewer "
    "ran the task engine on this split with these same parameters for software verification and "
    "sizing only, observing task counts per target, horizon and status for the development and "
    "validation partitions, but no values: 61132 evaluable and 1042 insufficient-history tasks in "
    "development, 13280 evaluable and 35 insufficient-history tasks in validation, and at least "
    "270 evaluable tasks in every target and horizon cell. No tasks were derived for the holdout "
    "partition."
)


def test_ecdc_protocol_fixed_parameters_and_references() -> None:
    from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
    from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
    from kalhas.contracts.v1.dataset_split import DatasetSplitManifest

    content = (REPO_ROOT / ECDC_PROTOCOL_PATH / "manifest.json").read_bytes()
    protocol = BenchmarkProtocol.model_validate_json(content)
    split = DatasetSplitManifest.model_validate_json(
        (REPO_ROOT / ECDC_SPLIT_PATH / "manifest.json").read_bytes()
    )
    curated = CuratedDatasetManifest.model_validate_json(
        (REPO_ROOT / ECDC_CURATED_PATH / "manifest.json").read_bytes()
    )
    assert len(content) == 3655
    assert hashlib.sha256(content).hexdigest() == (
        "27cba51375f89afb25481d3a4c141dede2f9718bdc8373c106bcf92b8973dff2"
    )
    assert protocol.model_dump(mode="json") == {
        "identifier": "benchmark-protocol-ecdc-covid19-hospital-icu-primary-benchmark-1.0.0",
        "tenant_id": "kalhas-reference",
        "schema_version": "1.0.0",
        "protocol_id": "ecdc-covid19-hospital-icu-primary-benchmark",
        "protocol_version": "1.0.0",
        "split_manifest_id": "dataset-split-ecdc-covid19-hospital-icu-primary-1.0.0",
        "split_content_hash": "5b025a700402477934155a18c5807850907054e1c479f280b3e0e540095e70e6",
        "curated_manifest_id": "curated-dataset-ecdc-covid19-hospital-icu-by-indicator-1.0.0",
        "curated_content_hash": "418e2fc4d1e0d9130a3c751a507216baf37e6447d7ecfb4dc0ee631cd475ac2c",
        "curated_bundle_hash": "c8fee2790fa1ed1ebdddca237531c6b70f092c404b507c30501b49568f243e0e",
        "task_vocabulary_version": "1.0.0",
        "targets": [
            {
                "path": "daily-hospital-occupancy.csv",
                "series_column": "country",
                "time_column": "date",
                "value_column": "value",
                "horizons": [7, 14, 21, 28],
                "history_window": 84,
                "min_history_points": 8,
                "minimum_evaluable_tasks": 100,
                "non_negative": True,
            },
            {
                "path": "daily-icu-occupancy.csv",
                "series_column": "country",
                "time_column": "date",
                "value_column": "value",
                "horizons": [7, 14, 21, 28],
                "history_window": 84,
                "min_history_points": 8,
                "minimum_evaluable_tasks": 100,
                "non_negative": True,
            },
            {
                "path": "weekly-hospital-admissions-per-100k.csv",
                "series_column": "country",
                "time_column": "year_week",
                "value_column": "value",
                "horizons": [1, 2, 3, 4],
                "history_window": 12,
                "min_history_points": 4,
                "minimum_evaluable_tasks": 100,
                "non_negative": True,
            },
            {
                "path": "weekly-icu-admissions-per-100k.csv",
                "series_column": "country",
                "time_column": "year_week",
                "value_column": "value",
                "horizons": [1, 2, 3, 4],
                "history_window": 12,
                "min_history_points": 4,
                "minimum_evaluable_tasks": 100,
                "non_negative": True,
            },
        ],
        "quantile_levels": ["0.025", "0.1", "0.25", "0.5", "0.75", "0.9", "0.975"],
        "scoring_rule": "kalhas-wis-k3-v1",
        "comparison": {
            "reference_baseline_id": "kalhas-persistence-quantile-v1",
            "reference_baseline_version": "1.0.0",
            "relative_wis_pass_below": "1",
        },
        "preregistration_note": ECDC_PROTOCOL_NOTE,
        "locked_at": "2026-11-04T09:05:00Z",
        "metadata": {},
        "content_hash": "2a1b258f07dc158de32115726acbe88beb7a43cc6722382dcf0e187a7c372df8",
    }
    assert (protocol.split_manifest_id, protocol.split_content_hash) == (
        split.identifier,
        split.content_hash,
    )
    assert (
        protocol.curated_manifest_id,
        protocol.curated_content_hash,
        protocol.curated_bundle_hash,
    ) == (curated.identifier, curated.content_hash, curated.bundle_hash)
    readme = (REPO_ROOT / "benchmarks/README.md").read_text(encoding="utf-8")
    assert ECDC_PROTOCOL_NOTE in readme
    assert "without inspecting outcome values" in readme


def test_ecdc_protocol_task_counts_and_sealed_holdout() -> None:
    from collections import Counter

    from kalhas.application.benchmark_task_engine import (
        build_information_set,
        derive_benchmark_tasks,
    )
    from kalhas.application.dataset_split_errors import SealedPartitionError
    from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
    from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
    from kalhas.contracts.v1.dataset_split import DatasetSplitManifest

    protocol = BenchmarkProtocol.model_validate_json(
        (REPO_ROOT / ECDC_PROTOCOL_PATH / "manifest.json").read_bytes()
    )
    split = DatasetSplitManifest.model_validate_json(
        (REPO_ROOT / ECDC_SPLIT_PATH / "manifest.json").read_bytes()
    )
    directory = REPO_ROOT / ECDC_CURATED_PATH
    curated = CuratedDatasetManifest.model_validate_json((directory / "manifest.json").read_bytes())
    files = {item.path: (directory / item.path).read_bytes() for item in curated.files}
    expected_cells = {
        (path, horizon)
        for path, horizons in (
            ("daily-hospital-occupancy.csv", (7, 14, 21, 28)),
            ("daily-icu-occupancy.csv", (7, 14, 21, 28)),
            ("weekly-hospital-admissions-per-100k.csv", (1, 2, 3, 4)),
            ("weekly-icu-admissions-per-100k.csv", (1, 2, 3, 4)),
        )
        for horizon in horizons
    }
    for partition, evaluable, insufficient in (
        ("development", 61132, 1042),
        ("validation", 13280, 35),
    ):
        tasks = derive_benchmark_tasks(protocol, split, curated, files, partition)
        status = Counter(task.status for task in tasks)
        assert status == {"evaluable": evaluable, "insufficient_history": insufficient}
        assert status["inadmissible_origin"] == 0
        cells = Counter((task.path, task.horizon) for task in tasks if task.status == "evaluable")
        assert set(cells) == expected_cells
        assert all(cells[cell] >= 270 for cell in expected_cells)
    for function in (derive_benchmark_tasks, build_information_set):
        with pytest.raises(SealedPartitionError):
            function(protocol, split, curated, files, "holdout")


@pytest.fixture
def protocol_copy_root(scratch_root: Path) -> Path:
    shutil.copytree(REPO_ROOT / "datasets", scratch_root / "datasets")
    (scratch_root / "benchmarks/v1").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "benchmarks/v1/protocols", scratch_root / "benchmarks/v1/protocols")
    shutil.copy2(REPO_ROOT / "benchmarks/README.md", scratch_root / "benchmarks/README.md")
    return scratch_root


def test_ecdc_protocol_horizon_tamper_is_rejected(protocol_copy_root: Path) -> None:
    path = protocol_copy_root / ECDC_PROTOCOL_PATH / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["targets"][0]["horizons"][0] = 6
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    result = _run(protocol_copy_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_PROTOCOL_PATH}: content_hash_mismatch" in result.stdout


def test_ecdc_protocol_extra_file_is_rejected(protocol_copy_root: Path) -> None:
    (protocol_copy_root / ECDC_PROTOCOL_PATH / "extra").write_bytes(b"x")
    result = _run(protocol_copy_root)
    assert result.returncode == 1
    assert f"FAIL {ECDC_PROTOCOL_PATH}: undeclared_file" in result.stdout


# --- committed baseline results (H30-D05) -------------------------------------------------


def test_ecdc_baseline_result_file_hashes() -> None:
    expected = {
        "forecasts/ecdc-primary-persistence-point-development/1.0.0/forecasts.csv": (
            "d69130a8fd0660f12afaf4e8f6c416bb3c395f50c27fbfe52d0d644e8479bb77"
        ),
        "forecasts/ecdc-primary-persistence-point-development/1.0.0/manifest.json": (
            "162d3371fab1fc2437b8303e6e2f9f07b89851d1bd2a3adda2772ef80635a07e"
        ),
        "forecasts/ecdc-primary-persistence-point-validation/1.0.0/forecasts.csv": (
            "f79453679c19520ac7e6d3ee996dffa6182a314a508ce28933d8201deb343853"
        ),
        "forecasts/ecdc-primary-persistence-point-validation/1.0.0/manifest.json": (
            "191c1db95ff294656f5ab4b70d71412dde090414c14956a1f0004a7591724bd6"
        ),
        "forecasts/ecdc-primary-persistence-quantile-development/1.0.0/forecasts.csv": (
            "1cca74aae651692c390949cc9edf4232c350dab66adef86569d91978418a8b1e"
        ),
        "forecasts/ecdc-primary-persistence-quantile-development/1.0.0/manifest.json": (
            "737538c66f3365018f955b3095e9201e72b84ba17c3d4e8f2c1c97396188d708"
        ),
        "forecasts/ecdc-primary-persistence-quantile-validation/1.0.0/forecasts.csv": (
            "0607b4dbb0c2a316abc384aaa83228128b1fd8d1b0b6a8cca16e8fc1f1cd8eff"
        ),
        "forecasts/ecdc-primary-persistence-quantile-validation/1.0.0/manifest.json": (
            "576fa77fdfb6060fbfea1cb419532b0a631adb2a1e52fe5c333dd461014331b2"
        ),
        "reports/ecdc-primary-point-vs-quantile-development/1.0.0/manifest.json": (
            "643c26e5b7a375ac7618476eb1263c40b9aeae25e893ff2b8a94768fb9f39a65"
        ),
        "reports/ecdc-primary-point-vs-quantile-validation/1.0.0/manifest.json": (
            "dfed29c26c284b11a99481cc349bcac17d017a102535abe41da60843a275fda1"
        ),
    }
    for path, digest in expected.items():
        assert (
            hashlib.sha256((REPO_ROOT / "benchmarks/v1" / path).read_bytes()).hexdigest() == digest
        )


def test_ecdc_baseline_forecasts_and_reports() -> None:
    from fractions import Fraction

    from kalhas.application.benchmark_baselines import BASELINE_CONFIGURATION_HASH
    from kalhas.contracts.v1.benchmark_forecast import BenchmarkScoreReport, ForecastSet
    from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol

    base = REPO_ROOT / "benchmarks/v1"
    protocol = BenchmarkProtocol.model_validate_json(
        (REPO_ROOT / ECDC_PROTOCOL_PATH / "manifest.json").read_bytes()
    )
    all_forecasts = tuple((base / "forecasts").glob("*/*/manifest.json"))
    all_reports = tuple((base / "reports").glob("*/*/manifest.json"))
    assert len(all_forecasts) == 4
    assert len(all_reports) == 2
    assert all(
        ForecastSet.model_validate_json(path.read_bytes()).partition != "holdout"
        for path in all_forecasts
    )
    assert all(
        BenchmarkScoreReport.model_validate_json(path.read_bytes()).partition != "holdout"
        for path in all_reports
    )
    limitations = (
        "The evaluation is retrospective against one final data vintage. "
        "Reporting delays and revisions are absent.",
        "Admission criteria and reporting differ by country and over time.",
        "Sources change within some series.",
        "Daily series have gaps.",
        "A benchmarked label binds only the exact pack and configuration, data vintage, "
        "geography, horizon, metric and claim. It disappears rather than transfers when "
        "that binding is absent.",
        "This report compares two reference baselines as a sanity benchmark. Neither is a "
        "Model Pack mechanism, and no verdict here is a claim about any Model Pack.",
    )
    for partition, count, fallback, wis_min, wis_max, coverage_min, coverage_max in (
        ("development", 61132, 751, "1.549059", "1.675262", "0.740612", "0.868811"),
        ("validation", 13280, 2, "1.637843", "1.825789", "0.825926", "0.925558"),
    ):
        sets = {}
        for baseline in ("point", "quantile"):
            identifier = f"ecdc-primary-persistence-{baseline}-{partition}"
            path = base / "forecasts" / identifier / "1.0.0/manifest.json"
            forecast = ForecastSet.model_validate_json(path.read_bytes())
            sets[baseline] = forecast
            assert forecast.partition == partition
            assert forecast.forecast_set_id == identifier
            assert forecast.forecast_set_version == "1.0.0"
            assert forecast.forecasts_file.row_count == count
            assert forecast.metadata == (
                {"fallback_count": fallback} if baseline == "quantile" else {}
            )
            assert forecast.producer.kind == "baseline"
            assert forecast.producer.producer_id == f"kalhas-persistence-{baseline}-v1"
            assert forecast.producer.producer_version == "1.0.0"
            assert forecast.producer.configuration_hash == BASELINE_CONFIGURATION_HASH
            assert (forecast.protocol_manifest_id, forecast.protocol_content_hash) == (
                protocol.identifier,
                protocol.content_hash,
            )
        report_id = f"ecdc-primary-point-vs-quantile-{partition}"
        report = BenchmarkScoreReport.model_validate_json(
            (base / "reports" / report_id / "1.0.0/manifest.json").read_bytes()
        )
        assert report.partition == partition
        assert (report.protocol_manifest_id, report.protocol_content_hash) == (
            protocol.identifier,
            protocol.content_hash,
        )
        assert (report.candidate_forecast_set_id, report.candidate_forecast_set_content_hash) == (
            sets["point"].identifier,
            sets["point"].content_hash,
        )
        assert (report.reference_forecast_set_id, report.reference_forecast_set_content_hash) == (
            sets["quantile"].identifier,
            sets["quantile"].content_hash,
        )
        assert report.limitations == limitations
        assert len(report.cells) == 16
        assert all(
            (cell.verdict, cell.verdict_reason) == ("fail", "not_below_threshold")
            for cell in report.cells
        )
        assert all(
            cell.relative_wis is not None and cell.reference is not None for cell in report.cells
        )
        wis = [
            Fraction(cell.relative_wis) for cell in report.cells if cell.relative_wis is not None
        ]
        coverage = [
            Fraction(cell.reference.coverage_95)
            for cell in report.cells
            if cell.reference is not None
        ]
        assert (min(wis), max(wis)) == (Fraction(wis_min), Fraction(wis_max))
        assert (min(coverage), max(coverage)) == (Fraction(coverage_min), Fraction(coverage_max))
    assert "## First results: reference baselines (development and validation)" in (
        REPO_ROOT / "benchmarks/README.md"
    ).read_text(encoding="utf-8")


@pytest.fixture
def forecast_chain_root(protocol_chain_root: Path) -> Path:
    from kalhas.application.benchmark_baselines import (
        QUANTILE_BASELINE_ID,
        produce_persistence_quantile_forecasts,
    )
    from kalhas.application.benchmark_protocol_verifier import (
        compute_benchmark_protocol_content_hash,
    )
    from kalhas.application.benchmark_scoring import (
        build_benchmark_score_report,
        compute_forecast_set_content_hash,
    )

    from tests.test_benchmark_scoring import NOW, prepared

    _, _, curated, files, split, protocol, candidate, cb, _, _ = prepared()
    comparison = protocol.comparison.model_copy(
        update={"reference_baseline_id": QUANTILE_BASELINE_ID}
    )
    protocol = protocol.model_copy(update={"comparison": comparison})
    protocol = protocol.model_copy(
        update={"content_hash": compute_benchmark_protocol_content_hash(protocol)}
    )
    protocol_path = (
        protocol_chain_root
        / "benchmarks/v1/protocols"
        / protocol.protocol_id
        / protocol.protocol_version
        / "manifest.json"
    )
    protocol_path.write_text(_render(protocol), encoding="utf-8", newline="\n")
    candidate = candidate.model_copy(update={"protocol_content_hash": protocol.content_hash})
    candidate = candidate.model_copy(
        update={"content_hash": compute_forecast_set_content_hash(candidate)}
    )
    reference, rb = produce_persistence_quantile_forecasts(
        forecast_set_id="reference",
        forecast_set_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        partition="development",
        created_at=NOW,
    )
    for artifact, data in ((candidate, cb), (reference, rb)):
        directory = (
            protocol_chain_root
            / "benchmarks/v1/forecasts"
            / artifact.forecast_set_id
            / artifact.forecast_set_version
        )
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(_render(artifact), encoding="utf-8", newline="\n")
        (directory / "forecasts.csv").write_bytes(data)
    report = build_benchmark_score_report(
        report_id="report",
        report_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        candidate=candidate,
        candidate_csv=cb,
        reference=reference,
        reference_csv=rb,
        limitations=("Synthetic only",),
        scored_at=NOW,
        metadata={},
    )
    directory = (
        protocol_chain_root / "benchmarks/v1/reports" / report.report_id / report.report_version
    )
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(_render(report), encoding="utf-8", newline="\n")
    return protocol_chain_root


def test_forecast_and_report_chain_passes(forecast_chain_root: Path) -> None:
    result = _run(forecast_chain_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok benchmarks/v1/forecasts/candidate/1.0.0" in result.stdout
    assert "ok benchmarks/v1/reports/report/1.0.0" in result.stdout


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("extra", "undeclared_file"),
        ("missing", "missing_forecasts_file"),
        ("edited", "file_mismatch"),
        ("manifest", "invalid_manifest"),
        ("protocol", "protocol_input_missing"),
        ("report-input", "forecast_input_missing"),
        ("holdout", "sealed_partition"),
    ],
)
def test_forecast_and_report_fail_closed(
    forecast_chain_root: Path, mutation: str, reason: str
) -> None:
    directory = forecast_chain_root / "benchmarks/v1/forecasts/candidate/1.0.0"
    if mutation == "extra":
        (directory / "extra").write_bytes(b"x")
    elif mutation == "missing":
        (directory / "forecasts.csv").unlink()
    elif mutation == "edited":
        (directory / "forecasts.csv").write_bytes(b"edited")
    elif mutation == "manifest":
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
    elif mutation == "protocol":
        shutil.rmtree(forecast_chain_root / "benchmarks/v1/protocols")
    elif mutation == "report-input":
        shutil.rmtree(directory)
    else:
        path = directory / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["partition"] = "holdout"
        path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert reason in result.stdout
    assert "Traceback" not in result.stderr


def test_forecast_manifest_hash_tampering(forecast_chain_root: Path) -> None:
    path = forecast_chain_root / "benchmarks/v1/forecasts/candidate/1.0.0/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["metadata"] = {"changed": True}
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert "content_hash_mismatch" in result.stdout


def test_holdout_report_is_sealed(forecast_chain_root: Path) -> None:
    path = forecast_chain_root / "benchmarks/v1/reports/report/1.0.0/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["partition"] = "holdout"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert "FAIL benchmarks/v1/reports/report/1.0.0: sealed_partition" in result.stdout
    assert "Traceback" not in result.stderr


def test_forecast_failures_precede_report_results(forecast_chain_root: Path) -> None:
    path = forecast_chain_root / "benchmarks/v1/forecasts/candidate/1.0.0/forecasts.csv"
    path.write_bytes(b"edited")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert result.stdout.index("FAIL benchmarks/v1/forecasts/") < result.stdout.index(
        "FAIL benchmarks/v1/reports/"
    )


@pytest.mark.parametrize(
    "mutation,reason", [("forged", "reexecution_mismatch"), ("unknown", "unknown_baseline")]
)
def test_baseline_reexecution_fails_report(
    forecast_chain_root: Path, mutation: str, reason: str
) -> None:
    from kalhas.application.benchmark_forecast_verifier import verify_benchmark_score_report
    from kalhas.application.benchmark_scoring import (
        build_benchmark_score_report,
        compute_forecast_set_content_hash,
    )
    from kalhas.contracts.v1.benchmark_forecast import ForecastSet
    from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol

    from tests.test_benchmark_scoring import NOW
    from tests.test_benchmark_task_engine import chain

    directory = forecast_chain_root / "benchmarks/v1/forecasts/reference/1.0.0"
    path = directory / "manifest.json"
    item = ForecastSet.model_validate_json(path.read_bytes())
    if mutation == "forged":
        content = (directory / "forecasts.csv").read_bytes().replace(b"10.050000", b"10.060000")
        (directory / "forecasts.csv").write_bytes(content)
        file = item.forecasts_file.model_copy(
            update={"sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content)}
        )
        item = item.model_copy(update={"forecasts_file": file})
    else:
        item = item.model_copy(
            update={"producer": item.producer.model_copy(update={"producer_id": "synthetic"})}
        )
    item = item.model_copy(update={"content_hash": compute_forecast_set_content_hash(item)})
    path.write_text(_render(item), encoding="utf-8", newline="\n")
    if mutation == "forged":
        raw, raw_files, curated, curated_files, split, original_protocol = chain()
        protocol_path = (
            forecast_chain_root
            / "benchmarks/v1/protocols"
            / original_protocol.protocol_id
            / original_protocol.protocol_version
            / "manifest.json"
        )
        protocol = BenchmarkProtocol.model_validate_json(protocol_path.read_bytes())
        candidate_dir = forecast_chain_root / "benchmarks/v1/forecasts/candidate/1.0.0"
        candidate = ForecastSet.model_validate_json((candidate_dir / "manifest.json").read_bytes())
        candidate_csv = (candidate_dir / "forecasts.csv").read_bytes()
        report = build_benchmark_score_report(
            report_id="report",
            report_version="1.0.0",
            protocol=protocol,
            split_manifest=split,
            curated_manifest=curated,
            curated_files=curated_files,
            candidate=candidate,
            candidate_csv=candidate_csv,
            reference=item,
            reference_csv=content,
            limitations=("Synthetic only",),
            scored_at=NOW,
            metadata={},
        )
        verify_benchmark_score_report(
            report,
            candidate,
            candidate_csv,
            item,
            content,
            protocol,
            split,
            curated,
            curated_files,
            {raw.identifier: (raw, raw_files)},
        )
        report_path = forecast_chain_root / "benchmarks/v1/reports/report/1.0.0/manifest.json"
        report_path.write_text(_render(report), encoding="utf-8", newline="\n")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert f"FAIL benchmarks/v1/forecasts/reference/1.0.0: {reason}" in result.stdout
    assert "FAIL benchmarks/v1/reports/report/1.0.0: forecast_input_invalid" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("name", ["candidate", "reference"])
def test_report_maps_sealed_forecast_to_invalid_input(forecast_chain_root: Path, name: str) -> None:
    path = forecast_chain_root / "benchmarks/v1/forecasts" / name / "1.0.0/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["partition"] = "holdout"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert f"FAIL benchmarks/v1/forecasts/{name}/1.0.0: sealed_partition" in result.stdout
    assert "FAIL benchmarks/v1/reports/report/1.0.0: forecast_input_invalid" in result.stdout
    assert "Traceback" not in result.stderr


# --- committed population bundles (H30-D06) ---

POPULATION_RAW_PATH = "datasets/v1/raw/eurostat-demo-pjan-ecdc-geographies/2026-11-05"
POPULATION_CURATED_PATH = "datasets/v1/curated/eurostat-population-ecdc-geographies/1.0.0"
POPULATION_LABELS = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "EE": "Estonia",
    "EL": "Greece",
    "ES": "Spain",
    "FR": "France",
    "HU": "Hungary",
    "IE": "Ireland",
    "IS": "Iceland",
    "IT": "Italy",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MT": "Malta",
    "NL": "Netherlands",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
}


def test_population_bundle_hashes_and_terms() -> None:
    from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest

    expected = {
        f"{POPULATION_RAW_PATH}/data.csv": (
            "855fe507bb55c2aa1cff26c8e404a811998289b216f5a216870d578d1952cfbc"
        ),
        f"{POPULATION_RAW_PATH}/manifest.json": (
            "588e6d902fcdd9e2df538669463e58fd3c35978f7f70c9545e9b411b52f16a15"
        ),
        f"{POPULATION_CURATED_PATH}/population.csv": (
            "352e5da4fa0c349d7fff38d822d0985b32f058c108beb20e94c29000ec0d668a"
        ),
        f"{POPULATION_CURATED_PATH}/manifest.json": (
            "928f10105286d46fea80c26130c7a4f3f1bb24d9db35c6a267be5a6f7b39dc6d"
        ),
    }
    for path, digest in expected.items():
        assert hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest() == digest
    raw = RawDatasetManifest.model_validate_json(
        (REPO_ROOT / POPULATION_RAW_PATH / "manifest.json").read_bytes()
    )
    curated = CuratedDatasetManifest.model_validate_json(
        (REPO_ROOT / POPULATION_CURATED_PATH / "manifest.json").read_bytes()
    )
    assert raw.data_subject_level == "aggregate"
    assert curated.license == raw.license
    assert raw.license.license_class == "attribution_commercial"
    assert raw.license.license_id == "eurostat-copyright-notice"
    assert raw.license.attribution_statement == "Source: Eurostat, dataset demo_pjan."
    assert raw.license.scope_restrictions == (
        "permission limited to data for EU, EFTA, EU candidate and acceding countries",
        "permission does not extend to material identified as third-party copyright",
    )
    assert raw.license.modifications_must_be_disclosed
    assert curated.metadata["geography_labels"] == POPULATION_LABELS
    readme = (REPO_ROOT / "datasets/README.md").read_text(encoding="utf-8")
    assert raw.license.attribution_statement in readme
    assert curated.modification_notice in readme


def test_population_rows_and_ecdc_geography_labels() -> None:
    import csv

    for path in (
        REPO_ROOT / POPULATION_RAW_PATH / "data.csv",
        REPO_ROOT / POPULATION_CURATED_PATH / "population.csv",
    ):
        with path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        assert len(rows) == 150
        assert {row["geo"] for row in rows} == set(POPULATION_LABELS)
        assert {row["TIME_PERIOD"] for row in rows} == {
            "2019",
            "2020",
            "2021",
            "2022",
            "2023",
            "2024",
        }
        keys = [(row["geo"], row["TIME_PERIOD"]) for row in rows]
        assert len(keys) == len(set(keys))
        assert set(keys) == {
            (geo, str(year)) for geo in POPULATION_LABELS for year in range(2019, 2025)
        }
    countries: set[str] = set()
    for name in ECDC_OUTPUTS:
        with (REPO_ROOT / ECDC_CURATED_PATH / name).open(encoding="utf-8", newline="") as source:
            countries.update(row["country"] for row in csv.DictReader(source))
    assert countries == set(POPULATION_LABELS.values())


def test_population_bundles_verify_and_tampering_fails(copied_root: Path) -> None:
    result = _run_repository()
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok {POPULATION_RAW_PATH}" in result.stdout
    assert f"ok {POPULATION_CURATED_PATH}" in result.stdout
    path = copied_root / POPULATION_CURATED_PATH / "population.csv"
    content = bytearray(path.read_bytes())
    content[-2] ^= 1
    path.write_bytes(bytes(content))
    result = _run(copied_root)
    assert result.returncode == 1
    assert f"FAIL {POPULATION_CURATED_PATH}: sha256_mismatch" in result.stdout


@pytest.fixture(autouse=True)
def _replayable_forecast_chain_candidate(request: pytest.FixtureRequest) -> None:
    """Keep the existing synthetic chain tests on a re-executable candidate."""
    if "forecast_chain_root" not in request.fixturenames:
        return
    from kalhas.application.benchmark_baselines import produce_persistence_point_forecasts
    from kalhas.application.benchmark_scoring import build_benchmark_score_report
    from kalhas.contracts.v1.benchmark_forecast import ForecastSet
    from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol

    from tests.test_benchmark_scoring import NOW
    from tests.test_benchmark_task_engine import chain

    root: Path = request.getfixturevalue("forecast_chain_root")
    _, _, curated, files, split, _ = chain()
    protocol_path = root / "benchmarks/v1/protocols/synthetic/1.0.0/manifest.json"
    protocol = BenchmarkProtocol.model_validate_json(protocol_path.read_bytes())
    candidate, content = produce_persistence_point_forecasts(
        forecast_set_id="candidate",
        forecast_set_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        partition="development",
        created_at=NOW,
    )
    candidate_dir = root / "benchmarks/v1/forecasts/candidate/1.0.0"
    (candidate_dir / "manifest.json").write_text(_render(candidate), encoding="utf-8", newline="\n")
    (candidate_dir / "forecasts.csv").write_bytes(content)
    reference_dir = root / "benchmarks/v1/forecasts/reference/1.0.0"
    reference = ForecastSet.model_validate_json((reference_dir / "manifest.json").read_bytes())
    report = build_benchmark_score_report(
        report_id="report",
        report_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        candidate=candidate,
        candidate_csv=content,
        reference=reference,
        reference_csv=(reference_dir / "forecasts.csv").read_bytes(),
        limitations=("Synthetic only",),
        scored_at=NOW,
        metadata={},
    )
    report_path = root / "benchmarks/v1/reports/report/1.0.0/manifest.json"
    report_path.write_text(_render(report), encoding="utf-8", newline="\n")


def test_mechanism_forecast_requires_reexecution(forecast_chain_root: Path) -> None:
    path = forecast_chain_root / "benchmarks/v1/forecasts/candidate/1.0.0/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["producer"]["kind"] = "model_pack_mechanism"
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    result = _run(forecast_chain_root)
    assert result.returncode == 1
    assert "mechanism_reexecution_unavailable" in result.stdout
    assert "Traceback" not in result.stderr
