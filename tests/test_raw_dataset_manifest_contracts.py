"""Shape tests for the ``RawDatasetManifest`` contract (Phase 30, H30-S01).

Every manifest here is built from tiny synthetic aggregate bytes defined in
this module. The contract checks shape only; the verifier recomputes the
hashes (see ``tests/test_raw_dataset_verifier.py``).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from kalhas.application.raw_dataset_verifier import (
    compute_raw_dataset_bundle_hash,
    compute_raw_dataset_manifest_content_hash,
)
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.dataset import (
    MAX_RAW_DATASET_TOTAL_BYTES,
    RawDatasetFile,
    RawDatasetManifest,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

TENANT = "kalhas-synthetic"
FILE_A = b"region,period,count\nr1,2024-01-01,5\nr2,2024-01-01,7\n"
FILE_B = b"region,period,count\nr1,2024-01-02,6\nr2,2024-01-02,8\n"
RAW_FILES: dict[str, bytes] = {"data/a.csv": FILE_A, "data/b.csv": FILE_B}

HELPER_NAMES = (
    "RawDatasetSource",
    "RawDatasetLicense",
    "RawDatasetColumn",
    "RawDatasetFile",
    "RawDatasetTimeBasis",
    "RawDatasetGeographyBasis",
)


def _columns() -> list[dict[str, Any]]:
    return [
        {"name": "region", "value_type": "string", "unit": "none", "missing_tokens": []},
        {"name": "period", "value_type": "date", "unit": "none", "missing_tokens": []},
        {"name": "count", "value_type": "integer", "unit": "persons", "missing_tokens": [""]},
    ]


def _file_entry(path: str, content: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "media_type": "text/csv",
        "columns": _columns(),
    }


def valid_payload() -> dict[str, Any]:
    """A shape-valid manifest payload (hashes are placeholders, not sealed)."""
    return {
        "identifier": "raw-dataset-synthetic-counts-2026-11-02",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "dataset_id": "synthetic-counts",
        "vintage": "2026-11-02",
        "retrieved_at": "2026-11-02T09:30:00Z",
        "source": {
            "publisher": "Synthetic Publisher",
            "title": "Synthetic aggregate counts",
            "source_locator": "synthetic://opaque-locator",
            "publisher_release_id": None,
        },
        "license": {
            "license_class": "attribution_commercial",
            "license_id": "synthetic-attribution-1.0",
            "terms_locator": "synthetic://opaque-terms",
            "terms_read_at": "2026-11-01T08:00:00Z",
            "attribution_statement": "Synthetic attribution statement.",
            "modifications_must_be_disclosed": True,
            "scope_restrictions": ["synthetic-scope"],
        },
        "data_subject_level": "aggregate",
        "files": [_file_entry(path, content) for path, content in sorted(RAW_FILES.items())],
        "bundle_hash": "a" * 64,
        "time_basis": {
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": ["period"],
            "time_semantics": "observation_date",
        },
        "geography_basis": {"scheme": "synthetic-regions", "geography_columns": ["region"]},
        "revision_policy": "closed_series",
        "revision_notes": "",
        "content_hash": "b" * 64,
        "declared_at": "2026-11-02T12:00:00Z",
        "metadata": {"purpose": "synthetic"},
    }


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with the exact bundle hash and content hash."""
    sealed = copy.deepcopy(payload)
    files = [RawDatasetFile.model_validate(entry) for entry in sealed["files"]]
    sealed["bundle_hash"] = compute_raw_dataset_bundle_hash(files)
    sealed["content_hash"] = "0" * 64
    provisional = RawDatasetManifest.model_validate(sealed)
    sealed["content_hash"] = compute_raw_dataset_manifest_content_hash(provisional)
    return sealed


def build_manifest(**overrides: Any) -> RawDatasetManifest:
    payload = valid_payload()
    payload.update(overrides)
    return RawDatasetManifest.model_validate(seal(payload))


def _set(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(payload: dict[str, Any]) -> None:
        node: Any = payload
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


def _delete(path: tuple[Any, ...]) -> Callable[[dict[str, Any]], None]:
    def mutate(payload: dict[str, Any]) -> None:
        node: Any = payload
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return mutate


def _swap_files(payload: dict[str, Any]) -> None:
    payload["files"] = list(reversed(payload["files"]))


def _duplicate_file(payload: dict[str, Any]) -> None:
    payload["files"] = [payload["files"][0], copy.deepcopy(payload["files"][0])]


def _oversize(payload: dict[str, Any]) -> None:
    payload["files"][0]["byte_size"] = MAX_RAW_DATASET_TOTAL_BYTES
    payload["files"][1]["byte_size"] = 1


def _duplicate_column(payload: dict[str, Any]) -> None:
    payload["files"][0]["columns"].append(copy.deepcopy(payload["files"][0]["columns"][0]))


def test_valid_manifest_builds_with_the_exact_identity() -> None:
    manifest = build_manifest()
    assert manifest.identifier == "raw-dataset-synthetic-counts-2026-11-02"
    assert manifest.tenant_id == TENANT
    assert manifest.schema_version == "1.0.0"
    assert manifest.data_subject_level == "aggregate"
    assert [file.path for file in manifest.files] == ["data/a.csv", "data/b.csv"]
    assert manifest.license.license_class == "attribution_commercial"


_INVALID_CASES: dict[str, Callable[[dict[str, Any]], None]] = {
    "identifier_mismatch": _set(("identifier",), "raw-dataset-other-2026-11-02"),
    "dataset_id_uppercase": _set(("dataset_id",), "Synthetic-Counts"),
    "dataset_id_double_hyphen": _set(("dataset_id",), "synthetic--counts"),
    "dataset_id_leading_hyphen": _set(("dataset_id",), "-synthetic"),
    "dataset_id_underscore": _set(("dataset_id",), "synthetic_counts"),
    "vintage_bad_format": _set(("vintage",), "2026-1-2"),
    "vintage_zero_suffix": _set(("vintage",), "2026-11-02.0"),
    "vintage_date_mismatch": _set(("retrieved_at",), "2026-11-03T09:30:00Z"),
    "retrieved_at_naive": _set(("retrieved_at",), "2026-11-02T09:30:00"),
    "retrieved_at_utc_date_differs_from_local": _set(
        ("retrieved_at",), "2026-11-02T23:30:00-05:00"
    ),
    "terms_read_after_retrieved": _set(("license", "terms_read_at"), "2026-11-02T10:00:00Z"),
    "terms_read_naive": _set(("license", "terms_read_at"), "2026-11-01T08:00:00"),
    "license_class_non_commercial": _set(("license", "license_class"), "non_commercial"),
    "license_class_unknown": _set(("license", "license_class"), "unknown"),
    "license_class_restricted": _set(("license", "license_class"), "restricted"),
    "attribution_missing": _set(("license", "attribution_statement"), None),
    "attribution_empty": _set(("license", "attribution_statement"), ""),
    "attribution_whitespace": _set(("license", "attribution_statement"), "   "),
    "modifications_not_boolean": _set(("license", "modifications_must_be_disclosed"), "yes"),
    "scope_restrictions_duplicate": _set(("license", "scope_restrictions"), ["a", "a"]),
    "source_publisher_empty": _set(("source", "publisher"), ""),
    "source_locator_empty": _set(("source", "source_locator"), ""),
    "release_id_empty": _set(("source", "publisher_release_id"), ""),
    "data_subject_individual": _set(("data_subject_level",), "individual"),
    "data_subject_missing": _delete(("data_subject_level",)),
    "files_empty": _set(("files",), []),
    "files_unsorted": _swap_files,
    "files_duplicate": _duplicate_file,
    "files_total_over_25_mib": _oversize,
    "file_path_absolute": _set(("files", 0, "path"), "/data/a.csv"),
    "file_path_parent_segment": _set(("files", 0, "path"), "data/../a.csv"),
    "file_path_leading_parent": _set(("files", 0, "path"), "../a.csv"),
    "file_path_backslash": _set(("files", 0, "path"), "data\\a.csv"),
    "file_path_empty_segment": _set(("files", 0, "path"), "data//a.csv"),
    "file_path_trailing_slash": _set(("files", 0, "path"), "data/a.csv/"),
    "file_path_dot_segment": _set(("files", 0, "path"), "./a.csv"),
    "file_path_empty": _set(("files", 0, "path"), ""),
    "file_path_control_character": _set(("files", 0, "path"), "data/a\x00.csv"),
    "file_byte_size_zero": _set(("files", 0, "byte_size"), 0),
    "file_byte_size_negative": _set(("files", 0, "byte_size"), -1),
    "file_byte_size_boolean": _set(("files", 0, "byte_size"), True),
    "file_byte_size_string": _set(("files", 0, "byte_size"), "10"),
    "file_sha256_uppercase": _set(("files", 0, "sha256"), "A" * 64),
    "file_sha256_short": _set(("files", 0, "sha256"), "a" * 63),
    "file_media_type_other": _set(("files", 0, "media_type"), "text/plain"),
    "file_columns_empty": _set(("files", 0, "columns"), []),
    "file_columns_duplicate": _duplicate_column,
    "column_value_type_other": _set(("files", 0, "columns", 0, "value_type"), "float"),
    "column_unit_empty": _set(("files", 0, "columns", 0, "unit"), ""),
    "column_missing_tokens_duplicate": _set(("files", 0, "columns", 0, "missing_tokens"), ["", ""]),
    "bundle_hash_not_hex": _set(("bundle_hash",), "z" * 64),
    "content_hash_short": _set(("content_hash",), "b" * 10),
    "time_columns_undeclared": _set(("time_basis", "time_columns"), ["unknown_column"]),
    "time_columns_empty": _set(("time_basis", "time_columns"), []),
    "time_columns_duplicate": _set(("time_basis", "time_columns"), ["period", "period"]),
    "time_calendar_other": _set(("time_basis", "calendar"), "fiscal_year"),
    "time_granularity_other": _set(("time_basis", "granularity"), "hour"),
    "time_semantics_other": _set(("time_basis", "time_semantics"), "event_date"),
    "geography_columns_undeclared": _set(("geography_basis", "geography_columns"), ["nowhere"]),
    "geography_columns_empty": _set(("geography_basis", "geography_columns"), []),
    "geography_scheme_empty": _set(("geography_basis", "scheme"), ""),
    "revision_policy_other": _set(("revision_policy",), "sometimes"),
    "revision_unknown_without_notes": lambda payload: payload.update(
        revision_policy="unknown", revision_notes=""
    ),
    "revision_unknown_whitespace_notes": lambda payload: payload.update(
        revision_policy="unknown", revision_notes="   "
    ),
    "declared_at_naive": _set(("declared_at",), "2026-11-02T12:00:00"),
    "metadata_non_finite": _set(("metadata",), {"value": float("nan")}),
    "metadata_infinite": _set(("metadata",), {"value": [float("inf")]}),
    "metadata_non_json_tuple": _set(("metadata",), {"value": (1, 2)}),
    "extra_field": _set(("unexpected",), "value"),
    "tenant_missing": _delete(("tenant_id",)),
}


@pytest.mark.parametrize("case", sorted(_INVALID_CASES))
def test_invalid_shapes_fail_closed(case: str) -> None:
    payload = valid_payload()
    _INVALID_CASES[case](payload)
    with pytest.raises(ValidationError):
        RawDatasetManifest.model_validate(payload)


def test_exactly_25_mib_is_admissible() -> None:
    payload = valid_payload()
    payload["files"][0]["byte_size"] = MAX_RAW_DATASET_TOTAL_BYTES - 1
    payload["files"][1]["byte_size"] = 1
    assert RawDatasetManifest.model_validate(payload).files[0].byte_size == 26_214_399


def test_same_day_suffix_vintage_is_admissible() -> None:
    manifest = build_manifest(
        identifier="raw-dataset-synthetic-counts-2026-11-02.2", vintage="2026-11-02.2"
    )
    assert manifest.vintage == "2026-11-02.2"


def test_vintage_date_is_the_utc_date_of_retrieved_at() -> None:
    manifest = build_manifest(
        identifier="raw-dataset-synthetic-counts-2026-11-03",
        vintage="2026-11-03",
        retrieved_at="2026-11-02T23:30:00-05:00",
    )
    assert manifest.vintage == "2026-11-03"


def test_public_domain_license_needs_no_attribution_statement() -> None:
    payload = valid_payload()
    payload["license"]["license_class"] = "public_domain"
    payload["license"]["attribution_statement"] = None
    payload["license"]["scope_restrictions"] = []
    assert RawDatasetManifest.model_validate(payload).license.attribution_statement is None


def test_unknown_revision_policy_with_notes_is_admissible() -> None:
    manifest = build_manifest(revision_policy="unknown", revision_notes="Revisions undocumented.")
    assert manifest.revision_policy == "unknown"


@pytest.mark.parametrize("policy", ["closed_series", "revised_in_place", "versioned_releases"])
def test_declared_revision_policies_are_admissible(policy: str) -> None:
    assert build_manifest(revision_policy=policy).revision_policy == policy


def test_time_and_geography_columns_may_come_from_different_files() -> None:
    payload = valid_payload()
    payload["files"][1]["columns"] = [
        {"name": "area", "value_type": "string", "unit": "none", "missing_tokens": []},
        {"name": "stamp", "value_type": "date", "unit": "none", "missing_tokens": []},
    ]
    payload["time_basis"]["time_columns"] = ["stamp"]
    payload["geography_basis"]["geography_columns"] = ["area"]
    assert RawDatasetManifest.model_validate(payload).time_basis.time_columns == ("stamp",)


def test_manifest_and_helpers_are_frozen() -> None:
    manifest = build_manifest()
    with pytest.raises(ValidationError):
        manifest.__setattr__("dataset_id", "other")
    for helper in (
        manifest.source,
        manifest.license,
        manifest.files[0],
        manifest.files[0].columns[0],
        manifest.time_basis,
        manifest.geography_basis,
    ):
        with pytest.raises(ValidationError):
            helper.__setattr__(next(iter(type(helper).model_fields)), "other")


def test_manifest_is_a_registered_public_contract_and_helpers_are_not() -> None:
    names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
    assert "RawDatasetManifest" in names
    for helper in HELPER_NAMES:
        assert helper not in names
        assert not (SCHEMA_DIR / f"{helper}.schema.json").exists()
    assert (SCHEMA_DIR / "RawDatasetManifest.schema.json").is_file()
    assert "RawDatasetManifest.schema.json" in generate_schemas()


def test_schema_admits_exactly_two_license_classes_and_aggregate_only() -> None:
    schema = RawDatasetManifest.model_json_schema()
    definitions = schema["$defs"]
    license_class = definitions["RawDatasetLicense"]["properties"]["license_class"]
    assert license_class["enum"] == ["public_domain", "attribution_commercial"]
    assert schema["properties"]["data_subject_level"]["const"] == "aggregate"
    assert schema["additionalProperties"] is False


def test_json_round_trip_is_exact() -> None:
    manifest = build_manifest()
    rendered = manifest.model_dump_json()
    assert RawDatasetManifest.model_validate_json(rendered) == manifest
    assert RawDatasetManifest.model_validate(json.loads(rendered)) == manifest
    assert json.loads(rendered)["identifier"] == manifest.identifier


def test_helper_modules_stay_unregistered_by_name() -> None:
    from kalhas.contracts.v1 import dataset

    for helper in HELPER_NAMES:
        assert hasattr(dataset, helper)
        assert getattr(dataset, helper) not in PUBLIC_CONTRACTS
