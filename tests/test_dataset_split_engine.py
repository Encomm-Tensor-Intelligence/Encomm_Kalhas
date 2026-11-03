"""Synthetic split engine coverage; all input rows are invented."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest
from kalhas.application.dataset_split_engine import compute_split_membership
from kalhas.application.dataset_split_errors import DatasetSplitError
from kalhas.application.dataset_transformation_engine import (
    derive_transformation_output_columns,
    execute_transformation_plan,
)
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest, TransformationPlan
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest, FileSplitRule

from tests.test_curated_dataset_contracts import build_raw_manifest, seal_curated

RAW = (
    b"region,day,week,value\n"
    b"a,2020-01-01,2020-W01,1\n"
    b"b,2020-01-02,2020-W01,2\n"
    b"c,2020-01-03,2020-W02,3\n"
    b"d,2020-01-05,2020-W03,4\n"
    b"a,2020-01-05,2020-W03,5\n"
)
RAW_FILES = {"source.csv": RAW}


def synthetic_chain() -> tuple[RawDatasetManifest, CuratedDatasetManifest, dict[str, bytes]]:
    cols = [
        {"name": n, "value_type": t, "unit": "none", "missing_tokens": []}
        for n, t in (
            ("region", "string"),
            ("day", "date"),
            ("week", "iso_week"),
            ("value", "decimal"),
        )
    ]
    raw = build_raw_manifest(
        files=[
            {
                "path": "source.csv",
                "byte_size": len(RAW),
                "sha256": hashlib.sha256(RAW).hexdigest(),
                "media_type": "text/csv",
                "columns": cols,
            }
        ],
        time_basis={
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": ["day", "week"],
            "time_semantics": "observation_date",
        },
    )
    outputs = []
    for path, time, kind in (("daily.csv", "day", "date"), ("weekly.csv", "week", "iso_week")):
        outputs.append(
            {
                "output_path": path,
                "source_manifest_id": raw.identifier,
                "source_path": "source.csv",
                "steps": [
                    {"op": "decode_text", "encoding": "utf-8"},
                    {"op": "parse_csv"},
                    {"op": "select_columns", "columns": ["region", time, "value"]},
                    {"op": "cast_columns", "types": {time: kind, "value": "decimal"}},
                ],
            }
        )
    plan = TransformationPlan.model_validate({"vocabulary_version": "1.0.0", "outputs": outputs})
    bundles = {raw.identifier: (raw, RAW_FILES)}
    result = execute_transformation_plan(plan, bundles)
    columns = derive_transformation_output_columns(plan, bundles)
    files = [
        {
            "path": path,
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "text/csv",
            "columns": [c.model_dump(mode="json") for c in columns[path]],
        }
        for path, data in result.items()
    ]
    payload: dict[str, Any] = {
        "identifier": "curated-dataset-synthetic-two-1.0.0",
        "tenant_id": raw.tenant_id,
        "schema_version": "1.0.0",
        "curated_dataset_id": "synthetic-two",
        "curation_version": "1.0.0",
        "inputs": [
            {
                "raw_manifest_id": raw.identifier,
                "raw_content_hash": raw.content_hash,
                "raw_bundle_hash": raw.bundle_hash,
            }
        ],
        "plan": plan.model_dump(mode="json"),
        "license": raw.license.model_dump(mode="json"),
        "modification_notice": "Selected columns.",
        "files": files,
        "bundle_hash": "0" * 64,
        "time_basis": {
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": ["day", "week"],
            "time_semantics": "observation_date",
        },
        "geography_basis": {"scheme": "synthetic-regions", "geography_columns": ["region"]},
        "content_hash": "0" * 64,
        "declared_at": "2026-11-03T00:00:00Z",
        "metadata": {},
    }
    return raw, CuratedDatasetManifest.model_validate(seal_curated(payload)), result


def rule_payloads() -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "time_rule": {
                "column": col,
                "value_type": kind,
                "validation_from": val,
                "holdout_from": hold,
            },
            "geography_rule": {
                "column": "region",
                "validation_values": ["d"],
                "holdout_values": ["b"],
            },
        }
        for path, col, kind, val, hold in (
            ("daily.csv", "day", "date", "2020-01-03", "2020-01-05"),
            ("weekly.csv", "week", "iso_week", "2020-W02", "2020-W03"),
        )
    ]


def build_split(curated: CuratedDatasetManifest, files: dict[str, bytes]) -> DatasetSplitManifest:
    from kalhas.application.dataset_split_verifier import compute_dataset_split_content_hash

    rules = tuple(FileSplitRule.model_validate(item) for item in rule_payloads())
    computed = compute_split_membership(rules, curated, files)
    payload = {
        "identifier": "dataset-split-synthetic-1.0.0",
        "tenant_id": curated.tenant_id,
        "schema_version": "1.0.0",
        "split_id": "synthetic",
        "split_version": "1.0.0",
        "curated_manifest_id": curated.identifier,
        "curated_content_hash": curated.content_hash,
        "curated_bundle_hash": curated.bundle_hash,
        "rule_vocabulary_version": "1.0.0",
        "file_rules": [r.model_dump(mode="json") for r in rules],
        "memberships": [
            {"path": path, "counts": counts.model_dump(mode="json"), "membership_hash": digest}
            for path, (_, counts, digest) in computed.items()
        ],
        "preregistration_note": (
            "Calendar and geography labels were fixed in advance; no outcome values were inspected."
        ),
        "locked_at": "2026-11-03T00:00:00Z",
        "content_hash": "0" * 64,
        "metadata": {},
    }
    model = DatasetSplitManifest.model_validate(payload)
    payload["content_hash"] = compute_dataset_split_content_hash(model)
    return DatasetSplitManifest.model_validate(payload)


def test_golden_membership_and_determinism() -> None:
    _, curated, files = synthetic_chain()
    rules = tuple(FileSplitRule.model_validate(item) for item in rule_payloads())
    before = (curated.model_dump(), copy.deepcopy(files), copy.deepcopy(rules))
    result = compute_split_membership(rules, curated, files)
    assert result == compute_split_membership(rules, curated, files)
    labels, counts, digest = result["daily.csv"]
    assert labels == ["development", "holdout", "validation", "holdout", "holdout"]
    assert digest == "14e5c397109d3e938cd1aebc23a61c6ecc5854395a3f12e872b270f2b29b4882"
    assert (counts.development, counts.validation, counts.holdout) == (1, 1, 3)
    assert result["weekly.csv"][0] == labels
    assert before == (curated.model_dump(), files, rules)


@pytest.mark.parametrize(
    ("column", "reason"), [("value", "forbidden_column"), ("absent", "unknown_column")]
)
def test_rejects_forbidden_or_unknown_column(column: str, reason: str) -> None:
    _, curated, files = synthetic_chain()
    payload = rule_payloads()[0]
    payload["time_rule"]["column"] = column
    with pytest.raises(DatasetSplitError) as error:
        compute_split_membership((FileSplitRule.model_validate(payload),), curated, files)
    assert error.value.reason == reason


def test_unknown_geography_and_time_type() -> None:
    _, curated, files = synthetic_chain()
    payload = rule_payloads()[0]
    payload["geography_rule"]["holdout_values"] = ["unknown"]
    with pytest.raises(DatasetSplitError) as error:
        compute_split_membership((FileSplitRule.model_validate(payload),), curated, files)
    assert error.value.reason == "unknown_geography_value"
    payload = rule_payloads()[0]
    payload["time_rule"] = {
        "column": "day",
        "value_type": "iso_week",
        "validation_from": "2020-W01",
        "holdout_from": "2020-W02",
    }
    with pytest.raises(DatasetSplitError) as error:
        compute_split_membership((FileSplitRule.model_validate(payload),), curated, files)
    assert error.value.reason == "time_type_mismatch"


def test_invalid_or_missing_time_fails_even_for_holdout_geography() -> None:
    _, curated, files = synthetic_chain()
    rules = (FileSplitRule.model_validate(rule_payloads()[0]),)
    for value in (b"", b"2020-02-30"):
        changed = dict(files)
        changed["daily.csv"] = changed["daily.csv"].replace(b"2020-01-02", value)
        with pytest.raises(DatasetSplitError) as error:
            compute_split_membership(rules, curated, changed)
        assert error.value.reason == "time_value_invalid"


def test_individual_rule_kinds_and_bad_headers() -> None:
    _, curated, files = synthetic_chain()
    payload = rule_payloads()[0]
    payload["geography_rule"] = None
    time_rule = FileSplitRule.model_validate(payload)
    assert compute_split_membership((time_rule,), curated, files)["daily.csv"][0] == [
        "development",
        "development",
        "validation",
        "holdout",
        "holdout",
    ]
    payload = rule_payloads()[0]
    payload["time_rule"] = None
    geo_rule = FileSplitRule.model_validate(payload)
    assert compute_split_membership((geo_rule,), curated, files)["daily.csv"][0] == [
        "development",
        "holdout",
        "development",
        "validation",
        "development",
    ]
    changed = dict(files)
    changed["daily.csv"] = changed["daily.csv"].replace(b"region,day,value", b"region,day,other", 1)
    with pytest.raises(DatasetSplitError) as error:
        compute_split_membership((geo_rule,), curated, changed)
    assert error.value.reason == "header_mismatch"
