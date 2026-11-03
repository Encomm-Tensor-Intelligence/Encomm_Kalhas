"""Shape tests for the ``CuratedDatasetManifest`` contract (Phase 30, H30-S02A).

Everything is built from tiny synthetic bytes defined in this module. The
contract checks shape only; the engine and verifier tests recompute the
bytes and hashes. The builders here are shared with the engine and verifier
tests.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from kalhas.application.curated_dataset_verifier import (
    compute_curated_dataset_bundle_hash,
    compute_curated_dataset_content_hash,
)
from kalhas.application.dataset_transformation_engine import (
    derive_transformation_output_columns,
    execute_transformation_plan,
)
from kalhas.application.raw_dataset_verifier import (
    compute_raw_dataset_bundle_hash,
    compute_raw_dataset_manifest_content_hash,
)
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.curated_dataset import (
    TRANSFORMATION_OPERATIONS,
    CuratedDatasetManifest,
    TransformationPlan,
)
from kalhas.contracts.v1.dataset import (
    MAX_RAW_DATASET_TOTAL_BYTES,
    RawDatasetFile,
    RawDatasetManifest,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

TENANT = "kalhas-synthetic"
RAW_CSV = (
    b"\xef\xbb\xbfregion,period,kind,count,note\n"
    b"r2,2020-W53,b,10,x\n"
    b"r1,2020-W02,a,NA,y\n"
    b"r1,2020-W01,a,5,\n"
    b"r3,2021-W01,a,7,z\n"
)
RAW_FILES: dict[str, bytes] = {"source.csv": RAW_CSV}
GOLDEN_OUTPUT = b"region,period,total\nr1,2020-W01,5\nr1,2020-W02,\nr3,2021-W01,7\n"

HELPER_NAMES = (
    "DecodeTextStep",
    "ParseCsvStep",
    "SelectColumnsStep",
    "RenameColumnsStep",
    "FilterRowsInStep",
    "CastColumnsStep",
    "RequireUniqueKeyStep",
    "SortRowsStep",
    "CuratedOutputPlan",
    "TransformationPlan",
    "RawDatasetReference",
)

LICENSE: dict[str, Any] = {
    "license_class": "attribution_commercial",
    "license_id": "synthetic-attribution-1.0",
    "terms_locator": "synthetic://opaque-terms",
    "terms_read_at": "2026-11-01T08:00:00Z",
    "attribution_statement": "Synthetic attribution statement.",
    "modifications_must_be_disclosed": True,
    "scope_restrictions": [],
}


def golden_plan() -> dict[str, Any]:
    """A multi-step plan: BOM removal, filter, select, rename, cast, key, sort."""
    return {
        "vocabulary_version": "1.0.0",
        "outputs": [
            {
                "output_path": "clean.csv",
                "source_manifest_id": "raw-dataset-synthetic-weekly-2026-11-02",
                "source_path": "source.csv",
                "steps": [
                    {"op": "decode_text", "encoding": "utf-8-sig"},
                    {"op": "parse_csv"},
                    {"op": "filter_rows_in", "column": "kind", "values": ["a"]},
                    {"op": "select_columns", "columns": ["region", "period", "count"]},
                    {"op": "rename_columns", "mapping": {"count": "total"}},
                    {"op": "cast_columns", "types": {"period": "iso_week", "total": "integer"}},
                    {"op": "require_unique_key", "columns": ["region", "period"]},
                    {"op": "sort_rows", "columns": ["region", "period"]},
                ],
            }
        ],
    }


def _column(name: str, value_type: str, unit: str = "none", missing: tuple[str, ...] = ()) -> Any:
    return {"name": name, "value_type": value_type, "unit": unit, "missing_tokens": list(missing)}


def build_raw_manifest(**overrides: Any) -> RawDatasetManifest:
    payload: dict[str, Any] = {
        "identifier": "raw-dataset-synthetic-weekly-2026-11-02",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "dataset_id": "synthetic-weekly",
        "vintage": "2026-11-02",
        "retrieved_at": "2026-11-02T09:30:00Z",
        "source": {
            "publisher": "Synthetic Publisher",
            "title": "Synthetic weekly counts",
            "source_locator": "synthetic://opaque-locator",
            "publisher_release_id": None,
        },
        "license": copy.deepcopy(LICENSE),
        "data_subject_level": "aggregate",
        "files": [
            {
                "path": "source.csv",
                "byte_size": len(RAW_CSV),
                "sha256": hashlib.sha256(RAW_CSV).hexdigest(),
                "media_type": "text/csv",
                "columns": [
                    _column("region", "string"),
                    _column("period", "iso_week"),
                    _column("kind", "string"),
                    _column("count", "integer", "persons", ("NA",)),
                    _column("note", "string", "none", ("",)),
                ],
            }
        ],
        "bundle_hash": "0" * 64,
        "time_basis": {
            "calendar": "iso_week",
            "granularity": "week",
            "time_columns": ["period"],
            "time_semantics": "reference_period",
        },
        "geography_basis": {"scheme": "synthetic-regions", "geography_columns": ["region"]},
        "revision_policy": "closed_series",
        "revision_notes": "",
        "content_hash": "0" * 64,
        "declared_at": "2026-11-02T12:00:00Z",
        "metadata": {},
    }
    payload.update(overrides)
    files = [RawDatasetFile.model_validate(entry) for entry in payload["files"]]
    payload["bundle_hash"] = compute_raw_dataset_bundle_hash(files)
    provisional = RawDatasetManifest.model_validate(payload)
    payload["content_hash"] = compute_raw_dataset_manifest_content_hash(provisional)
    return RawDatasetManifest.model_validate(payload)


def raw_bundles_for(
    raw: RawDatasetManifest, files: Mapping[str, bytes] | None = None
) -> dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]]:
    return {raw.identifier: (raw, dict(files if files is not None else RAW_FILES))}


def curated_payload(
    plan: dict[str, Any] | None = None, raw: RawDatasetManifest | None = None, **overrides: Any
) -> dict[str, Any]:
    """A fully sealed, verifier-valid curated payload (JSON-compatible values)."""
    raw = raw if raw is not None else build_raw_manifest()
    plan_model = TransformationPlan.model_validate(plan if plan is not None else golden_plan())
    bundles = raw_bundles_for(raw)
    outputs = execute_transformation_plan(plan_model, bundles)
    columns = derive_transformation_output_columns(plan_model, bundles)
    files = [
        {
            "path": path,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "media_type": "text/csv",
            "columns": [column.model_dump(mode="json") for column in columns[path]],
        }
        for path, content in outputs.items()
    ]
    payload: dict[str, Any] = {
        "identifier": "curated-dataset-synthetic-clean-1.0.0",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "curated_dataset_id": "synthetic-clean",
        "curation_version": "1.0.0",
        "inputs": [
            {
                "raw_manifest_id": raw.identifier,
                "raw_content_hash": raw.content_hash,
                "raw_bundle_hash": raw.bundle_hash,
            }
        ],
        "plan": plan_model.model_dump(mode="json"),
        "license": copy.deepcopy(LICENSE),
        "modification_notice": "Removed the byte order mark and kept rows of kind a.",
        "files": files,
        "bundle_hash": "0" * 64,
        "time_basis": {
            "calendar": "iso_week",
            "granularity": "week",
            "time_columns": ["period"],
            "time_semantics": "reference_period",
        },
        "geography_basis": {"scheme": "synthetic-regions", "geography_columns": ["region"]},
        "content_hash": "0" * 64,
        "declared_at": "2026-11-02T12:00:00Z",
        "metadata": {},
    }
    payload.update(overrides)
    return seal_curated(payload)


def seal_curated(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(payload)
    sealed["bundle_hash"] = "0" * 64
    sealed["content_hash"] = "0" * 64
    provisional = CuratedDatasetManifest.model_validate(sealed)
    sealed["bundle_hash"] = compute_curated_dataset_bundle_hash(provisional)
    provisional = CuratedDatasetManifest.model_validate(sealed)
    sealed["content_hash"] = compute_curated_dataset_content_hash(provisional)
    return sealed


def build_curated(
    plan: dict[str, Any] | None = None, raw: RawDatasetManifest | None = None, **overrides: Any
) -> CuratedDatasetManifest:
    return CuratedDatasetManifest.model_validate(curated_payload(plan, raw, **overrides))


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


_STEPS = ("plan", "outputs", 0, "steps")


def _swap_decode_and_parse(payload: dict[str, Any]) -> None:
    steps = payload["plan"]["outputs"][0]["steps"]
    steps[0], steps[1] = steps[1], steps[0]


def _repeat_decode(payload: dict[str, Any]) -> None:
    payload["plan"]["outputs"][0]["steps"].append({"op": "decode_text", "encoding": "utf-8"})


def _repeat_parse(payload: dict[str, Any]) -> None:
    payload["plan"]["outputs"][0]["steps"].append({"op": "parse_csv"})


def _drop_parse(payload: dict[str, Any]) -> None:
    del payload["plan"]["outputs"][0]["steps"][1]


def _second_output(payload: dict[str, Any], path: str) -> None:
    second = copy.deepcopy(payload["plan"]["outputs"][0])
    second["output_path"] = path
    payload["plan"]["outputs"].append(second)


def _duplicate_output_path(payload: dict[str, Any]) -> None:
    _second_output(payload, "clean.csv")


def _unsorted_outputs(payload: dict[str, Any]) -> None:
    _second_output(payload, "a_first.csv")


def _duplicate_input(payload: dict[str, Any]) -> None:
    payload["inputs"].append(copy.deepcopy(payload["inputs"][0]))


def _unsorted_inputs(payload: dict[str, Any]) -> None:
    other = copy.deepcopy(payload["inputs"][0])
    other["raw_manifest_id"] = "raw-dataset-aaa-2026-11-02"
    payload["inputs"].append(other)


def _oversize(payload: dict[str, Any]) -> None:
    payload["files"][0]["byte_size"] = MAX_RAW_DATASET_TOTAL_BYTES + 1


_INVALID_CASES: dict[str, Callable[[dict[str, Any]], None]] = {
    "identifier_mismatch": _set(("identifier",), "curated-dataset-other-1.0.0"),
    "curated_id_uppercase": _set(("curated_dataset_id",), "Synthetic-Clean"),
    "curation_version_two_parts": _set(("curation_version",), "1.0"),
    "curation_version_prefixed": _set(("curation_version",), "v1.0.0"),
    "inputs_empty": _set(("inputs",), []),
    "inputs_duplicate": _duplicate_input,
    "inputs_unsorted": _unsorted_inputs,
    "input_hash_malformed": _set(("inputs", 0, "raw_content_hash"), "xyz"),
    "plan_source_not_an_input": _set(
        (*_STEPS[:3], "source_manifest_id"), "raw-dataset-x-2026-11-02"
    ),
    "plan_vocabulary_unknown": _set(("plan", "vocabulary_version"), "2.0.0"),
    "plan_outputs_empty": _set(("plan", "outputs"), []),
    "plan_outputs_duplicate_path": _duplicate_output_path,
    "plan_outputs_unsorted": _unsorted_outputs,
    "output_path_not_csv": _set(("plan", "outputs", 0, "output_path"), "clean.txt"),
    "output_path_absolute": _set(("plan", "outputs", 0, "output_path"), "/clean.csv"),
    "source_path_parent_segment": _set(("plan", "outputs", 0, "source_path"), "../source.csv"),
    "steps_first_not_decode": _swap_decode_and_parse,
    "steps_missing_parse": _drop_parse,
    "steps_decode_repeated": _repeat_decode,
    "steps_parse_repeated": _repeat_parse,
    "steps_only_decode": _set((*_STEPS,), [{"op": "decode_text", "encoding": "utf-8"}]),
    "step_unknown_op": _set((*_STEPS, 2), {"op": "drop_columns", "columns": ["note"]}),
    "step_missing_op": _set((*_STEPS, 2), {"columns": ["note"]}),
    "step_extra_field": _set((*_STEPS, 3, "extra"), "x"),
    "decode_encoding_other": _set((*_STEPS, 0, "encoding"), "latin-1"),
    "select_columns_empty": _set((*_STEPS, 3, "columns"), []),
    "select_columns_duplicate": _set((*_STEPS, 3, "columns"), ["region", "region"]),
    "rename_mapping_empty": _set((*_STEPS, 4, "mapping"), {}),
    "rename_new_names_duplicate": _set((*_STEPS, 4, "mapping"), {"count": "x", "region": "x"}),
    "filter_values_empty": _set((*_STEPS, 2, "values"), []),
    "filter_values_duplicate": _set((*_STEPS, 2, "values"), ["a", "a"]),
    "cast_types_empty": _set((*_STEPS, 5, "types"), {}),
    "cast_type_unknown": _set((*_STEPS, 5, "types"), {"period": "float"}),
    "unique_key_empty": _set((*_STEPS, 6, "columns"), []),
    "unique_key_duplicate": _set((*_STEPS, 6, "columns"), ["region", "region"]),
    "sort_columns_empty": _set((*_STEPS, 7, "columns"), []),
    "sort_columns_duplicate": _set((*_STEPS, 7, "columns"), ["region", "region"]),
    "license_class_other": _set(("license", "license_class"), "non_commercial"),
    "modification_notice_empty": _set(("modification_notice",), ""),
    "modification_notice_whitespace": _set(("modification_notice",), "   "),
    "files_empty": _set(("files",), []),
    "file_path_differs_from_plan": _set(("files", 0, "path"), "other.csv"),
    "file_media_type_not_csv": _set(("files", 0, "media_type"), "application/json"),
    "files_over_25_mib": _oversize,
    "time_column_undeclared": _set(("time_basis", "time_columns"), ["nowhere"]),
    "geography_column_undeclared": _set(("geography_basis", "geography_columns"), ["nowhere"]),
    "bundle_hash_malformed": _set(("bundle_hash",), "abc"),
    "content_hash_malformed": _set(("content_hash",), "ABC"),
    "declared_at_naive": _set(("declared_at",), "2026-11-02T12:00:00"),
    "metadata_non_finite": _set(("metadata",), {"value": float("nan")}),
    "metadata_non_json": _set(("metadata",), {"value": (1, 2)}),
    "extra_field": _set(("unexpected",), "value"),
    "tenant_missing": _delete(("tenant_id",)),
}


@pytest.mark.parametrize("case", sorted(_INVALID_CASES))
def test_invalid_shapes_fail_closed(case: str) -> None:
    payload = curated_payload()
    _INVALID_CASES[case](payload)
    with pytest.raises(ValidationError):
        CuratedDatasetManifest.model_validate(payload)


def test_valid_manifest_builds_with_the_exact_identity() -> None:
    manifest = build_curated()
    assert manifest.identifier == "curated-dataset-synthetic-clean-1.0.0"
    assert manifest.plan.vocabulary_version == "1.0.0"
    assert [file.path for file in manifest.files] == ["clean.csv"]
    assert manifest.inputs[0].raw_manifest_id == "raw-dataset-synthetic-weekly-2026-11-02"


def test_the_closed_vocabulary_is_exactly_eight_operations() -> None:
    assert TRANSFORMATION_OPERATIONS == (
        "decode_text",
        "parse_csv",
        "select_columns",
        "rename_columns",
        "filter_rows_in",
        "cast_columns",
        "require_unique_key",
        "sort_rows",
    )


def test_a_multi_output_plan_is_admissible() -> None:
    plan = golden_plan()
    second = copy.deepcopy(plan["outputs"][0])
    second["output_path"] = "z_second.csv"
    plan["outputs"].append(second)
    manifest = build_curated(plan)
    assert [file.path for file in manifest.files] == ["clean.csv", "z_second.csv"]


def test_exactly_25_mib_is_admissible() -> None:
    payload = curated_payload()
    payload["files"][0]["byte_size"] = MAX_RAW_DATASET_TOTAL_BYTES
    assert CuratedDatasetManifest.model_validate(payload).files[0].byte_size == 26_214_400


def test_manifest_and_helpers_are_frozen() -> None:
    manifest = build_curated()
    with pytest.raises(ValidationError):
        manifest.__setattr__("curated_dataset_id", "other")
    output = manifest.plan.outputs[0]
    for helper in (manifest.plan, output, output.steps[0], manifest.inputs[0]):
        with pytest.raises(ValidationError):
            helper.__setattr__(next(iter(type(helper).model_fields)), "other")


def test_manifest_is_registered_and_helpers_are_not() -> None:
    names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
    assert names[62] == "CuratedDatasetManifest"
    from kalhas.contracts.v1 import curated_dataset

    for helper in HELPER_NAMES:
        assert helper not in names
        assert not (SCHEMA_DIR / f"{helper}.schema.json").exists()
        assert hasattr(curated_dataset, helper)
    assert (SCHEMA_DIR / "CuratedDatasetManifest.schema.json").is_file()
    assert "CuratedDatasetManifest.schema.json" in generate_schemas()


def test_json_round_trip_is_exact() -> None:
    manifest = build_curated()
    rendered = manifest.model_dump_json()
    assert CuratedDatasetManifest.model_validate_json(rendered) == manifest
    assert CuratedDatasetManifest.model_validate(json.loads(rendered)) == manifest
    assert json.loads(rendered)["plan"]["outputs"][0]["steps"][0]["op"] == "decode_text"


def test_the_golden_plan_output_is_the_documented_bytes() -> None:
    manifest = build_curated()
    assert manifest.files[0].sha256 == hashlib.sha256(GOLDEN_OUTPUT).hexdigest()
    assert manifest.files[0].byte_size == len(GOLDEN_OUTPUT)
