"""Tests for the pure raw-dataset bundle verifier (Phase 30, H30-S01)."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from kalhas.application.domain_errors import KalhasDomainError
from kalhas.application.raw_dataset_errors import RawDatasetVerificationError
from kalhas.application.raw_dataset_verifier import (
    compute_raw_dataset_bundle_hash,
    compute_raw_dataset_manifest_content_hash,
    verify_raw_dataset_bundle,
)
from kalhas.contracts.v1.dataset import RawDatasetManifest

from tests.test_raw_dataset_manifest_contracts import (
    FILE_A,
    FILE_B,
    RAW_FILES,
    TENANT,
    build_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"

_MODULES = (
    "contracts/v1/dataset.py",
    "application/raw_dataset_verifier.py",
    "application/raw_dataset_errors.py",
)


def _reason(manifest: Any, files: Any) -> str:
    with pytest.raises(RawDatasetVerificationError) as excinfo:
        verify_raw_dataset_bundle(manifest, files)
    return excinfo.value.reason


def test_a_valid_bundle_verifies() -> None:
    verify_raw_dataset_bundle(build_manifest(), dict(RAW_FILES))


def test_bundle_and_content_hash_rules_are_recomputed_independently() -> None:
    manifest = build_manifest()
    records = [
        {
            "path": file.path,
            "byte_size": len(RAW_FILES[file.path]),
            "sha256": hashlib.sha256(RAW_FILES[file.path]).hexdigest(),
            "media_type": "text/csv",
        }
        for file in manifest.files
    ]
    bundle = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    assert manifest.bundle_hash == bundle
    assert compute_raw_dataset_bundle_hash(manifest.files) == bundle

    dumped = json.loads(manifest.model_dump_json())
    del dumped["content_hash"]
    content = hashlib.sha256(
        json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    assert manifest.content_hash == content
    assert compute_raw_dataset_manifest_content_hash(manifest) == content


def test_bundle_hash_excludes_declared_columns() -> None:
    manifest = build_manifest()
    other_columns = [
        file.model_copy(update={"columns": file.columns[:1]}) for file in manifest.files
    ]
    assert compute_raw_dataset_bundle_hash(other_columns) == manifest.bundle_hash


def test_a_missing_declared_file_is_rejected() -> None:
    assert _reason(build_manifest(), {"data/a.csv": FILE_A}) == "missing_file"
    assert _reason(build_manifest(), {}) == "missing_file"


def test_an_undeclared_extra_file_is_rejected() -> None:
    files = {**RAW_FILES, "data/extra.csv": b"x"}
    assert _reason(build_manifest(), files) == "undeclared_file"


def test_a_one_byte_change_is_rejected() -> None:
    changed = bytearray(FILE_B)
    changed[0] ^= 0x01
    files = {"data/a.csv": FILE_A, "data/b.csv": bytes(changed)}
    assert _reason(build_manifest(), files) == "sha256_mismatch"


def test_a_size_change_is_rejected() -> None:
    files = {"data/a.csv": FILE_A + b"\n", "data/b.csv": FILE_B}
    assert _reason(build_manifest(), files) == "size_mismatch"
    files = {"data/a.csv": FILE_A[:-1], "data/b.csv": FILE_B}
    assert _reason(build_manifest(), files) == "size_mismatch"


def test_a_tampered_bundle_hash_is_rejected() -> None:
    tampered = build_manifest().model_copy(update={"bundle_hash": "f" * 64})
    assert _reason(tampered, dict(RAW_FILES)) == "bundle_hash_mismatch"


def test_a_tampered_content_hash_is_rejected() -> None:
    tampered = build_manifest().model_copy(update={"content_hash": "f" * 64})
    assert _reason(tampered, dict(RAW_FILES)) == "content_hash_mismatch"


def test_a_changed_declaration_with_a_stale_content_hash_is_rejected() -> None:
    manifest = build_manifest()
    edited = manifest.model_copy(update={"revision_notes": "edited after sealing"})
    assert _reason(edited, dict(RAW_FILES)) == "content_hash_mismatch"


def test_a_wrong_model_type_is_rejected() -> None:
    manifest = build_manifest()
    assert _reason(manifest.model_dump(mode="json"), dict(RAW_FILES)) == "invalid_manifest"
    assert _reason(None, dict(RAW_FILES)) == "invalid_manifest"
    assert _reason(manifest.files[0], dict(RAW_FILES)) == "invalid_manifest"


def test_a_subclassed_manifest_is_rejected() -> None:
    class Forged(RawDatasetManifest):
        pass

    forged = Forged.model_validate(build_manifest().model_dump(mode="python"))
    assert _reason(forged, dict(RAW_FILES)) == "invalid_manifest"


def test_a_model_construct_forgery_is_rejected() -> None:
    manifest = build_manifest()
    fields = dict(manifest)
    for update in (
        {"identifier": "raw-dataset-forged-2026-11-02"},
        {"data_subject_level": "individual"},
        {"files": ()},
        {"vintage": "not-a-vintage"},
    ):
        forged = RawDatasetManifest.model_construct(**{**fields, **update})
        assert type(forged) is RawDatasetManifest
        assert _reason(forged, dict(RAW_FILES)) == "invalid_manifest"


def test_malformed_file_mappings_are_rejected() -> None:
    manifest = build_manifest()
    assert _reason(manifest, [("data/a.csv", FILE_A)]) == "invalid_bundle"
    assert _reason(manifest, {"data/a.csv": FILE_A, "data/b.csv": "text"}) == "invalid_bundle"
    assert _reason(manifest, {"data/a.csv": FILE_A, "data/b.csv": bytearray(FILE_B)}) == (
        "invalid_bundle"
    )
    assert _reason(manifest, {"data/a.csv": FILE_A, 1: FILE_B}) == "invalid_bundle"


def test_public_message_is_generic_and_leaks_nothing() -> None:
    manifest = build_manifest()
    changed = bytearray(FILE_B)
    changed[0] ^= 0x01
    cases: list[tuple[Any, Any]] = [
        (manifest, {"data/a.csv": FILE_A}),
        (manifest, {**RAW_FILES, "data/secret-extra.csv": b"hidden-bytes"}),
        (manifest, {"data/a.csv": FILE_A, "data/b.csv": bytes(changed)}),
        (manifest, {"data/a.csv": FILE_A + b"!", "data/b.csv": FILE_B}),
        (manifest.model_copy(update={"bundle_hash": "e" * 64}), dict(RAW_FILES)),
        (manifest.model_copy(update={"content_hash": "d" * 64}), dict(RAW_FILES)),
        (None, dict(RAW_FILES)),
    ]
    messages: set[str] = set()
    sensitive = [
        TENANT,
        "data/a.csv",
        "data/b.csv",
        "secret-extra",
        "hidden-bytes",
        manifest.bundle_hash,
        manifest.content_hash,
        manifest.files[0].sha256,
        manifest.files[1].sha256,
        repr(FILE_A),
        "e" * 64,
        "d" * 64,
    ]
    for candidate, files in cases:
        with pytest.raises(RawDatasetVerificationError) as excinfo:
            verify_raw_dataset_bundle(candidate, files)
        error = excinfo.value
        rendered = f"{error!s}|{error!r}|{error.args!r}"
        for secret in sensitive:
            assert secret not in rendered
        messages.add(str(error))
        assert isinstance(error, KalhasDomainError)
    assert len(messages) == 1


def test_each_failure_reason_is_a_distinct_bounded_code() -> None:
    manifest = build_manifest()
    reasons = {
        _reason(manifest, {}),
        _reason(manifest, {**RAW_FILES, "x": b""}),
        _reason(manifest, {"data/a.csv": FILE_A + b"!", "data/b.csv": FILE_B}),
        _reason(manifest, {"data/a.csv": FILE_B[: len(FILE_A)], "data/b.csv": FILE_B}),
        _reason(manifest.model_copy(update={"bundle_hash": "0" * 64}), dict(RAW_FILES)),
        _reason(manifest.model_copy(update={"content_hash": "0" * 64}), dict(RAW_FILES)),
        _reason(None, dict(RAW_FILES)),
        _reason(manifest, []),
    }
    assert reasons == {
        "missing_file",
        "undeclared_file",
        "size_mismatch",
        "sha256_mismatch",
        "bundle_hash_mismatch",
        "content_hash_mismatch",
        "invalid_manifest",
        "invalid_bundle",
    }


def test_verification_is_deterministic_and_does_not_mutate_inputs() -> None:
    manifest = build_manifest()
    files: dict[str, bytes] = dict(RAW_FILES)
    manifest_before = manifest.model_dump_json()
    files_before = copy.deepcopy(files)
    for _ in range(3):
        verify_raw_dataset_bundle(manifest, files)
    assert manifest.model_dump_json() == manifest_before
    assert files == files_before

    broken = {**files, "data/a.csv": FILE_A + b"!"}
    broken_before = copy.deepcopy(broken)
    assert {_reason(manifest, broken) for _ in range(3)} == {"size_mismatch"}
    assert broken == broken_before
    assert manifest.model_dump_json() == manifest_before


def test_a_read_only_mapping_is_accepted() -> None:
    class ReadOnly(Mapping[str, bytes]):
        def __init__(self, data: dict[str, bytes]) -> None:
            self._data = data

        def __getitem__(self, key: str) -> bytes:
            return self._data[key]

        def __iter__(self) -> Any:
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    verify_raw_dataset_bundle(build_manifest(), ReadOnly(dict(RAW_FILES)))


_FORBIDDEN_ROOTS = frozenset(
    {
        "os",
        "pathlib",
        "urllib",
        "http",
        "socket",
        "requests",
        "time",
        "random",
        "secrets",
        "subprocess",
        "logging",
        "io",
        "shutil",
        "tempfile",
        "warnings",
    }
)
_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "now",
        "today",
        "utcnow",
        "getenv",
        "environ",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "open",
    }
)
_FORBIDDEN_NAMES = frozenset({"open", "print", "input", "exec", "eval", "__import__"})


@pytest.mark.parametrize("relative", _MODULES)
def test_modules_have_no_filesystem_network_clock_or_random_access(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in _FORBIDDEN_ROOTS, (relative, alias.name)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in _FORBIDDEN_ROOTS, (
                relative,
                node.module,
            )
        elif isinstance(node, ast.Attribute):
            assert node.attr not in _FORBIDDEN_ATTRIBUTES, (relative, node.attr)
        elif isinstance(node, ast.Name):
            assert node.id not in _FORBIDDEN_NAMES, (relative, node.id)


def test_verifier_module_keeps_no_module_level_mutable_state() -> None:
    tree = ast.parse(
        (KALHAS_ROOT / "application/raw_dataset_verifier.py").read_text(encoding="utf-8")
    )
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue
            value = node.value
            assert not isinstance(value, ast.List | ast.Dict | ast.Set), ast.dump(node)
