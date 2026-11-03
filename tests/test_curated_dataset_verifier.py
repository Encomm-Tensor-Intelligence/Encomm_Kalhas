"""Tests for the pure curated-dataset verifier by re-execution (H30-S02A)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from kalhas.application.curated_dataset_verifier import (
    compute_curated_dataset_bundle_hash,
    compute_curated_dataset_content_hash,
    verify_curated_dataset_bundle,
)
from kalhas.application.dataset_transformation_errors import CuratedDatasetVerificationError
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest

from tests.test_curated_dataset_contracts import (
    GOLDEN_OUTPUT,
    LICENSE,
    RAW_FILES,
    TENANT,
    build_curated,
    build_raw_manifest,
    curated_payload,
    golden_plan,
    raw_bundles_for,
    seal_curated,
)

CURATED_FILES: dict[str, bytes] = {"clean.csv": GOLDEN_OUTPUT}


def _reason(manifest: Any, raw_bundles: Any = None, curated_files: Any = None) -> str:
    bundles = raw_bundles if raw_bundles is not None else raw_bundles_for(build_raw_manifest())
    files = curated_files if curated_files is not None else dict(CURATED_FILES)
    with pytest.raises(CuratedDatasetVerificationError) as excinfo:
        verify_curated_dataset_bundle(manifest, bundles, files)
    return excinfo.value.reason


def _manifest(**overrides: Any) -> CuratedDatasetManifest:
    return CuratedDatasetManifest.model_validate(curated_payload(**overrides))


def test_a_valid_raw_to_curated_chain_verifies() -> None:
    verify_curated_dataset_bundle(
        build_curated(), raw_bundles_for(build_raw_manifest()), dict(CURATED_FILES)
    )


def test_hash_rules_are_recomputed_by_the_verifier() -> None:
    manifest = build_curated()
    assert compute_curated_dataset_bundle_hash(manifest) == manifest.bundle_hash
    assert compute_curated_dataset_content_hash(manifest) == manifest.content_hash


def test_a_raw_byte_tamper_is_rejected() -> None:
    raw = build_raw_manifest()
    changed = bytearray(RAW_FILES["source.csv"])
    changed[-3] ^= 0x01
    tampered = raw_bundles_for(raw, {"source.csv": bytes(changed)})
    assert _reason(build_curated(), tampered) == "raw_input_invalid"


def test_a_missing_raw_input_is_rejected() -> None:
    assert _reason(build_curated(), {}) == "raw_input_invalid"
    raw = build_raw_manifest()
    renamed = {"raw-dataset-other-2026-11-02": (raw, dict(RAW_FILES))}
    assert _reason(build_curated(), renamed) == "raw_input_invalid"


def test_a_curated_byte_tamper_is_rejected() -> None:
    changed = bytearray(GOLDEN_OUTPUT)
    changed[0] ^= 0x01
    assert _reason(build_curated(), curated_files={"clean.csv": bytes(changed)}) == (
        "sha256_mismatch"
    )
    assert _reason(build_curated(), curated_files={"clean.csv": GOLDEN_OUTPUT + b"\n"}) == (
        "size_mismatch"
    )


def test_a_stale_reference_hash_is_rejected() -> None:
    for field in ("raw_content_hash", "raw_bundle_hash"):
        payload = curated_payload()
        payload["inputs"][0][field] = "f" * 64
        manifest = CuratedDatasetManifest.model_validate(seal_curated(payload))
        assert _reason(manifest) == "reference_mismatch"


def test_a_tenant_mismatch_is_rejected() -> None:
    assert _reason(_manifest(tenant_id="kalhas-reference")) == "tenant_mismatch"


def test_a_license_mismatch_is_rejected() -> None:
    other = copy.deepcopy(LICENSE)
    other["attribution_statement"] = "A different attribution statement."
    assert _reason(_manifest(license=other)) == "license_mismatch"
    more_permissive = copy.deepcopy(LICENSE)
    more_permissive.update(license_class="public_domain", attribution_statement=None)
    assert _reason(_manifest(license=more_permissive)) == "license_mismatch"


def test_a_plan_that_no_longer_reproduces_the_declared_bytes_is_rejected() -> None:
    payload = curated_payload()
    payload["plan"]["outputs"][0]["steps"].pop()  # drop the final sort_rows
    manifest = CuratedDatasetManifest.model_validate(seal_curated(payload))
    assert _reason(manifest) == "sha256_mismatch"


def test_a_plan_that_cannot_execute_is_not_reproducible() -> None:
    payload = curated_payload()
    payload["plan"]["outputs"][0]["steps"][3] = {"op": "select_columns", "columns": ["zzz"]}
    manifest = CuratedDatasetManifest.model_validate(seal_curated(payload))
    assert _reason(manifest) == "not_reproducible"


def test_an_extra_or_missing_curated_file_is_rejected() -> None:
    assert _reason(build_curated(), curated_files={**CURATED_FILES, "extra.csv": b"x"}) == (
        "undeclared_file"
    )
    assert _reason(build_curated(), curated_files={"other.csv": GOLDEN_OUTPUT}) == "missing_file"
    assert _reason(build_curated(), curated_files={"clean.csv": GOLDEN_OUTPUT, "x": b""}) == (
        "undeclared_file"
    )


def test_a_declared_column_mismatch_is_rejected() -> None:
    payload = curated_payload()
    payload["files"][0]["columns"][2]["unit"] = "other-unit"
    manifest = CuratedDatasetManifest.model_validate(seal_curated(payload))
    assert _reason(manifest) == "columns_mismatch"
    payload = curated_payload()
    payload["files"][0]["columns"][1]["value_type"] = "string"
    manifest = CuratedDatasetManifest.model_validate(seal_curated(payload))
    assert _reason(manifest) == "columns_mismatch"


def test_a_tampered_bundle_hash_is_rejected() -> None:
    tampered = build_curated().model_copy(update={"bundle_hash": "f" * 64})
    assert _reason(tampered) == "bundle_hash_mismatch"


def test_a_stale_content_hash_is_rejected() -> None:
    stale = build_curated().model_copy(update={"content_hash": "f" * 64})
    assert _reason(stale) == "content_hash_mismatch"
    edited = build_curated().model_copy(update={"modification_notice": "edited after sealing"})
    assert _reason(edited) == "content_hash_mismatch"


def test_a_wrong_model_type_or_forged_manifest_is_rejected() -> None:
    manifest = build_curated()
    assert _reason(manifest.model_dump(mode="json")) == "invalid_manifest"
    assert _reason(None) == "invalid_manifest"
    assert _reason(build_raw_manifest()) == "invalid_manifest"

    class Forged(CuratedDatasetManifest):
        pass

    forged_subclass = Forged.model_validate(manifest.model_dump(mode="python"))
    assert _reason(forged_subclass) == "invalid_manifest"
    fields = dict(manifest)
    for update in (
        {"identifier": "curated-dataset-forged-1.0.0"},
        {"curation_version": "not-a-version"},
        {"files": ()},
        {"modification_notice": ""},
    ):
        constructed = CuratedDatasetManifest.model_construct(**{**fields, **update})
        assert type(constructed) is CuratedDatasetManifest
        assert _reason(constructed) == "invalid_manifest"


def test_malformed_mappings_are_rejected() -> None:
    manifest = build_curated()
    raw_bundles = raw_bundles_for(build_raw_manifest())
    assert _reason(manifest, raw_bundles=[1]) == "invalid_input"
    assert _reason(manifest, curated_files=[("clean.csv", GOLDEN_OUTPUT)]) == "invalid_input"
    assert _reason(manifest, curated_files={"clean.csv": "text"}) == "invalid_input"
    assert _reason(manifest, curated_files={"clean.csv": bytearray(GOLDEN_OUTPUT)}) == (
        "invalid_input"
    )
    raw_bundles_bad: dict[str, Any] = {next(iter(raw_bundles)): "not-a-tuple"}
    assert _reason(manifest, raw_bundles=raw_bundles_bad) == "raw_input_invalid"


def test_the_public_message_is_generic_and_leaks_nothing() -> None:
    manifest = build_curated()
    raw = build_raw_manifest()
    changed = bytearray(GOLDEN_OUTPUT)
    changed[0] ^= 0x01
    cases: list[tuple[Any, Any, Any]] = [
        (manifest, raw_bundles_for(raw), {"clean.csv": bytes(changed)}),
        (manifest, raw_bundles_for(raw), {**CURATED_FILES, "secret-extra.csv": b"hidden-bytes"}),
        (_manifest(tenant_id="kalhas-reference"), raw_bundles_for(raw), dict(CURATED_FILES)),
        (
            manifest.model_copy(update={"content_hash": "d" * 64}),
            raw_bundles_for(raw),
            CURATED_FILES,
        ),
        (None, raw_bundles_for(raw), dict(CURATED_FILES)),
        (manifest, {}, dict(CURATED_FILES)),
    ]
    sensitive = [
        TENANT,
        "kalhas-reference",
        "clean.csv",
        "source.csv",
        "secret-extra",
        "hidden-bytes",
        "r3,2021-W01",
        manifest.bundle_hash,
        manifest.content_hash,
        manifest.files[0].sha256,
        raw.content_hash,
        "d" * 64,
    ]
    messages: set[str] = set()
    for candidate, bundles, files in cases:
        with pytest.raises(CuratedDatasetVerificationError) as excinfo:
            verify_curated_dataset_bundle(candidate, bundles, files)
        rendered = f"{excinfo.value!s}|{excinfo.value!r}|{excinfo.value.args!r}"
        for secret in sensitive:
            assert secret not in rendered
        messages.add(str(excinfo.value))
    assert len(messages) == 1


def test_each_failure_reason_is_a_bounded_code() -> None:
    manifest = build_curated()
    reasons = {
        _reason(None),
        _reason(manifest, raw_bundles=[1]),
        _reason(manifest, raw_bundles={}),
        _reason(_manifest(tenant_id="kalhas-reference")),
        _reason(manifest, curated_files={"other.csv": GOLDEN_OUTPUT}),
        _reason(manifest, curated_files={**CURATED_FILES, "x": b""}),
        _reason(manifest.model_copy(update={"bundle_hash": "0" * 64})),
        _reason(manifest.model_copy(update={"content_hash": "0" * 64})),
    }
    assert reasons == {
        "invalid_manifest",
        "invalid_input",
        "raw_input_invalid",
        "tenant_mismatch",
        "missing_file",
        "undeclared_file",
        "bundle_hash_mismatch",
        "content_hash_mismatch",
    }


def test_verification_is_deterministic_and_does_not_mutate_inputs() -> None:
    manifest = build_curated()
    raw = build_raw_manifest()
    raw_bundles = raw_bundles_for(raw)
    curated_files = dict(CURATED_FILES)
    before = (
        manifest.model_dump_json(),
        raw.model_dump_json(),
        copy.deepcopy(dict(raw_bundles[raw.identifier][1])),
        copy.deepcopy(curated_files),
    )
    for _ in range(3):
        verify_curated_dataset_bundle(manifest, raw_bundles, curated_files)
    after = (
        manifest.model_dump_json(),
        raw.model_dump_json(),
        dict(raw_bundles[raw.identifier][1]),
        curated_files,
    )
    assert after == before

    broken = {"clean.csv": GOLDEN_OUTPUT + b"!"}
    assert {_reason(manifest, raw_bundles, broken) for _ in range(3)} == {"size_mismatch"}
    assert curated_files == before[3]


def test_the_golden_plan_is_the_documented_plan() -> None:
    plan = golden_plan()
    ops = [step["op"] for step in plan["outputs"][0]["steps"]]
    assert ops == [
        "decode_text",
        "parse_csv",
        "filter_rows_in",
        "select_columns",
        "rename_columns",
        "cast_columns",
        "require_unique_key",
        "sort_rows",
    ]
    assert isinstance(build_raw_manifest(), RawDatasetManifest)
