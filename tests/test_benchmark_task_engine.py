"""Synthetic task and information-set tests."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest
from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_protocol_verifier import compute_benchmark_protocol_content_hash
from kalhas.application.benchmark_task_engine import (
    BenchmarkTask,
    build_information_set,
    derive_benchmark_tasks,
)
from kalhas.application.dataset_split_engine import compute_split_membership
from kalhas.application.dataset_split_errors import SealedPartitionError
from kalhas.application.dataset_split_verifier import compute_dataset_split_content_hash
from kalhas.application.dataset_transformation_engine import (
    derive_transformation_output_columns,
    execute_transformation_plan,
)
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest, TransformationPlan
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest, FileSplitRule

from tests.test_curated_dataset_contracts import build_raw_manifest, seal_curated

DAILY = (
    b"series,zone,day,value\n"
    b"alpha,n,2020-01-01,1\n"
    b"alpha,n,2020-01-02,NA\n"
    b"alpha,n,2020-01-03,3\n"
    b"alpha,h,2020-01-04,4\n"
    b"alpha,n,2020-01-05,5\n"
    b"alpha,n,2020-01-06,6\n"
    b"alpha,n,2020-01-07,7\n"
    b"alpha,n,2020-01-08,8\n"
    b"beta,n,2020-01-01,9\n"
    b"gamma,n,2020-01-03,10\n"
)
WEEKLY = b"series,zone,week,value\nalpha,n,2019-W52,10\nalpha,n,2020-W01,11\nalpha,n,2020-W02,12\n"


def chain(
    daily: bytes = DAILY, geography_only: bool = False
) -> tuple[
    RawDatasetManifest,
    dict[str, bytes],
    CuratedDatasetManifest,
    dict[str, bytes],
    DatasetSplitManifest,
    BenchmarkProtocol,
]:
    sources = {"raw-daily.csv": daily, "raw-weekly.csv": WEEKLY}
    raw_files = []
    for path, content in sources.items():
        time = "day" if "daily" in path else "week"
        kind = "date" if time == "day" else "iso_week"
        raw_columns = [
            {
                "name": name,
                "value_type": value_type,
                "unit": "none",
                "missing_tokens": ["NA"] if name == "value" else [],
            }
            for name, value_type in (
                ("series", "string"),
                ("zone", "string"),
                (time, kind),
                ("value", "decimal"),
            )
        ]
        raw_files.append(
            {
                "path": path,
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "media_type": "text/csv",
                "columns": raw_columns,
            }
        )
    raw = build_raw_manifest(
        files=raw_files,
        time_basis={
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": ["day", "week"],
            "time_semantics": "observation_date",
        },
        geography_basis={"scheme": "synthetic", "geography_columns": ["series", "zone"]},
    )
    output_plans = [
        {
            "output_path": out,
            "source_manifest_id": raw.identifier,
            "source_path": source,
            "steps": [{"op": "decode_text", "encoding": "utf-8"}, {"op": "parse_csv"}],
        }
        for out, source in (("daily.csv", "raw-daily.csv"), ("weekly.csv", "raw-weekly.csv"))
    ]
    plan = TransformationPlan.model_validate(
        {"vocabulary_version": "1.0.0", "outputs": output_plans}
    )
    bundles = {raw.identifier: (raw, sources)}
    files = execute_transformation_plan(plan, bundles)
    columns = derive_transformation_output_columns(plan, bundles)
    declarations = [
        {
            "path": p,
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "text/csv",
            "columns": [c.model_dump(mode="json") for c in columns[p]],
        }
        for p, data in files.items()
    ]
    curated_data: dict[str, Any] = {
        "identifier": "curated-dataset-synthetic-benchmark-1.0.0",
        "tenant_id": raw.tenant_id,
        "schema_version": "1.0.0",
        "curated_dataset_id": "synthetic-benchmark",
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
        "modification_notice": "Canonical encoding.",
        "files": declarations,
        "bundle_hash": "0" * 64,
        "time_basis": {
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": ["day", "week"],
            "time_semantics": "observation_date",
        },
        "geography_basis": {"scheme": "synthetic", "geography_columns": ["series", "zone"]},
        "content_hash": "0" * 64,
        "declared_at": "2026-11-03T00:00:00Z",
        "metadata": {},
    }
    curated = CuratedDatasetManifest.model_validate(seal_curated(curated_data))
    geo = {"column": "zone", "validation_values": [], "holdout_values": ["h"]}
    daily_time = (
        None
        if geography_only
        else {
            "column": "day",
            "value_type": "date",
            "validation_from": "2020-01-06",
            "holdout_from": "2020-01-10",
        }
    )
    rules = tuple(
        FileSplitRule.model_validate(x)
        for x in [
            {"path": "daily.csv", "time_rule": daily_time, "geography_rule": geo},
            {
                "path": "weekly.csv",
                "time_rule": {
                    "column": "week",
                    "value_type": "iso_week",
                    "validation_from": "2020-W03",
                    "holdout_from": "2020-W04",
                },
            },
        ]
    )
    memberships = compute_split_membership(rules, curated, files)
    split_data: dict[str, Any] = {
        "identifier": "dataset-split-synthetic-benchmark-1.0.0",
        "tenant_id": raw.tenant_id,
        "schema_version": "1.0.0",
        "split_id": "synthetic-benchmark",
        "split_version": "1.0.0",
        "curated_manifest_id": curated.identifier,
        "curated_content_hash": curated.content_hash,
        "curated_bundle_hash": curated.bundle_hash,
        "rule_vocabulary_version": "1.0.0",
        "file_rules": [r.model_dump(mode="json") for r in rules],
        "memberships": [
            {"path": path, "counts": counts.model_dump(mode="json"), "membership_hash": digest}
            for path, (_, counts, digest) in memberships.items()
        ],
        "preregistration_note": "Calendar and geography fixed before values were inspected.",
        "locked_at": "2026-11-03T00:00:00Z",
        "content_hash": "0" * 64,
        "metadata": {},
    }
    split = DatasetSplitManifest.model_validate(split_data)
    split_data["content_hash"] = compute_dataset_split_content_hash(split)
    split = DatasetSplitManifest.model_validate(split_data)
    protocol_data: dict[str, Any] = {
        "identifier": "benchmark-protocol-synthetic-1.0.0",
        "tenant_id": raw.tenant_id,
        "schema_version": "1.0.0",
        "protocol_id": "synthetic",
        "protocol_version": "1.0.0",
        "split_manifest_id": split.identifier,
        "split_content_hash": split.content_hash,
        "curated_manifest_id": curated.identifier,
        "curated_content_hash": curated.content_hash,
        "curated_bundle_hash": curated.bundle_hash,
        "task_vocabulary_version": "1.0.0",
        "targets": [
            {
                "path": p,
                "series_column": "series",
                "time_column": t,
                "value_column": "value",
                "horizons": [1, 2],
                "history_window": 2,
                "min_history_points": 2,
                "minimum_evaluable_tasks": 1,
                "non_negative": True,
            }
            for p, t in (("daily.csv", "day"), ("weekly.csv", "week"))
        ],
        "quantile_levels": ["0.025", "0.1", "0.25", "0.5", "0.75", "0.9", "0.975"],
        "scoring_rule": "kalhas-wis-k3-v1",
        "comparison": {
            "reference_baseline_id": "synthetic",
            "reference_baseline_version": "1.0.0",
            "relative_wis_pass_below": "0.9",
        },
        "preregistration_note": "Fixed without inspecting outcome values.",
        "locked_at": "2026-11-03T00:00:00Z",
        "content_hash": "0" * 64,
        "metadata": {},
    }
    protocol = BenchmarkProtocol.model_validate(protocol_data)
    protocol_data["content_hash"] = compute_benchmark_protocol_content_hash(protocol)
    protocol = BenchmarkProtocol.model_validate(protocol_data)
    return raw, sources, curated, files, split, protocol


def test_golden_validation_tasks() -> None:
    _, _, curated, files, split, protocol = chain()
    before = copy.deepcopy((protocol, split, curated, files))
    result = derive_benchmark_tasks(protocol, split, curated, files, "validation")
    expected = (
        BenchmarkTask(
            "daily.csv", "alpha", "2020-01-04", 2, "2020-01-06", "validation", "inadmissible_origin"
        ),
        BenchmarkTask(
            "daily.csv",
            "alpha",
            "2020-01-05",
            1,
            "2020-01-06",
            "validation",
            "insufficient_history",
        ),
        BenchmarkTask(
            "daily.csv",
            "alpha",
            "2020-01-05",
            2,
            "2020-01-07",
            "validation",
            "insufficient_history",
        ),
        BenchmarkTask(
            "daily.csv", "alpha", "2020-01-06", 1, "2020-01-07", "validation", "evaluable"
        ),
        BenchmarkTask(
            "daily.csv", "alpha", "2020-01-06", 2, "2020-01-08", "validation", "evaluable"
        ),
        BenchmarkTask(
            "daily.csv", "alpha", "2020-01-07", 1, "2020-01-08", "validation", "evaluable"
        ),
    )
    assert result == expected
    assert result == derive_benchmark_tasks(protocol, split, curated, files, "validation")
    assert before == (protocol, split, curated, files)


def test_weekly_tasks_cross_the_iso_year_boundary() -> None:
    _, _, curated, files, split, protocol = chain()
    tasks = derive_benchmark_tasks(protocol, split, curated, files, "development")
    assert tuple(task for task in tasks if task.path == "weekly.csv") == (
        BenchmarkTask(
            "weekly.csv", "alpha", "2019-W52", 1, "2020-W01", "development", "insufficient_history"
        ),
        BenchmarkTask(
            "weekly.csv", "alpha", "2019-W52", 2, "2020-W02", "development", "insufficient_history"
        ),
        BenchmarkTask("weekly.csv", "alpha", "2020-W01", 1, "2020-W02", "development", "evaluable"),
    )


def test_information_set_enforces_availability() -> None:
    _, _, curated, files, split, protocol = chain()
    view = build_information_set(protocol, split, curated, files, "validation")
    saturday = BenchmarkTask(
        "daily.csv", "alpha", "2020-01-04", 1, "2020-01-05", "validation", "inadmissible_origin"
    )
    sunday = BenchmarkTask(
        "daily.csv", "alpha", "2020-01-05", 1, "2020-01-06", "validation", "insufficient_history"
    )
    assert view.rows(saturday, "weekly.csv", "alpha") == (("2019-W52", "10"),)
    assert view.rows(sunday, "weekly.csv", "alpha") == (("2019-W52", "10"), ("2020-W01", "11"))
    assert view.rows(sunday, "daily.csv", "alpha") == (
        ("2020-01-01", "1"),
        ("2020-01-03", "3"),
        ("2020-01-05", "5"),
    )
    assert all(row.value != "4" and row.value != "NA" for row in view._rows)
    weekly_origin = BenchmarkTask(
        "weekly.csv", "alpha", "2020-W01", 1, "2020-W02", "validation", "evaluable"
    )
    assert view.rows(weekly_origin, "daily.csv", "alpha") == (
        ("2020-01-01", "1"),
        ("2020-01-03", "3"),
        ("2020-01-05", "5"),
    )
    development = build_information_set(protocol, split, curated, files, "development")
    late_origin = BenchmarkTask(
        "daily.csv", "alpha", "2020-01-08", 1, "2020-01-09", "development", "evaluable"
    )
    assert development.rows(late_origin, "daily.csv", "alpha") == (
        ("2020-01-01", "1"),
        ("2020-01-03", "3"),
        ("2020-01-05", "5"),
    )
    with pytest.raises(BenchmarkError) as error:
        view.rows(
            BenchmarkTask(
                "daily.csv", "alpha", "2020-01-05", 1, "2020-01-06", "development", "evaluable"
            ),
            "daily.csv",
            "alpha",
        )
    assert error.value.reason == "partition_mismatch"
    with pytest.raises(BenchmarkError) as error:
        view.rows(sunday, "missing.csv", "alpha")
    assert error.value.reason == "unknown_target"


@pytest.mark.parametrize("function", [derive_benchmark_tasks, build_information_set])
def test_sealed_and_invalid_partition(function: Any) -> None:
    with pytest.raises(SealedPartitionError) as error:
        function(None, None, None, None, "holdout")
    assert str(error.value) == "The requested partition is sealed"
    with pytest.raises(BenchmarkError) as invalid:
        function(None, None, None, None, "other")
    assert invalid.value.reason == "invalid_partition"


def test_rejects_duplicate_and_invalid_time() -> None:
    for data, reason in (
        (DAILY + b"alpha,n,2020-01-01,22\n", "duplicate_series_time"),
        (DAILY.replace(b"2020-01-01", b"2020-02-30", 1), "time_value_invalid"),
    ):
        _, _, curated, files, split, protocol = chain(data, geography_only=True)
        with pytest.raises(BenchmarkError) as error:
            derive_benchmark_tasks(protocol, split, curated, files, "development")
        assert error.value.reason == reason


def test_reference_and_file_tamper_fail() -> None:
    _, _, curated, files, split, protocol = chain()
    data = protocol.model_dump(mode="json")
    data["split_content_hash"] = "1" * 64
    with pytest.raises(BenchmarkError) as error:
        derive_benchmark_tasks(
            BenchmarkProtocol.model_validate(data), split, curated, files, "development"
        )
    assert error.value.reason == "reference_mismatch"
    changed = dict(files)
    changed["daily.csv"] += b"x"
    with pytest.raises(BenchmarkError) as error:
        build_information_set(protocol, split, curated, changed, "validation")
    assert error.value.reason == "invalid_input"
