"""Lineage verification for synthetic forecasts and reports."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import pytest
from kalhas.application.benchmark_forecast_errors import (
    BenchmarkForecastVerificationError,
    BenchmarkScoreVerificationError,
)
from kalhas.application.benchmark_forecast_verifier import (
    verify_benchmark_score_report,
    verify_forecast_set,
)
from kalhas.application.benchmark_scoring import (
    build_benchmark_score_report,
    compute_forecast_set_content_hash,
)
from kalhas.application.dataset_split_errors import SealedPartitionError
from kalhas.contracts.v1.benchmark_forecast import ForecastFile

from tests.test_benchmark_scoring import NOW, prepared


def context() -> tuple[Any, ...]:
    (
        raw,
        raw_files,
        curated,
        files,
        split,
        protocol,
        candidate,
        candidate_csv,
        reference,
        reference_csv,
    ) = prepared()
    raw_bundles = {raw.identifier: (raw, raw_files)}
    report = build_benchmark_score_report(
        report_id="report",
        report_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        candidate=candidate,
        candidate_csv=candidate_csv,
        reference=reference,
        reference_csv=reference_csv,
        limitations=("Synthetic only",),
        scored_at=NOW,
        metadata={},
    )
    return (
        protocol,
        split,
        curated,
        files,
        raw_bundles,
        candidate,
        candidate_csv,
        reference,
        reference_csv,
        report,
    )


def reseal(item: Any, content: bytes, count: int | None = None) -> Any:
    file = ForecastFile(
        path="forecasts.csv",
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        row_count=item.forecasts_file.row_count if count is None else count,
    )
    changed = item.model_copy(update={"forecasts_file": file})
    return changed.model_copy(update={"content_hash": compute_forecast_set_content_hash(changed)})


def test_complete_verification_and_tampering() -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    verify_forecast_set(candidate, cb, p, s, c, f, raw)
    verify_benchmark_score_report(report, candidate, cb, reference, rb, p, s, c, f, raw)
    cases = [
        (candidate, cb.replace(b"11", b"12"), "file_mismatch"),
        (candidate.model_copy(update={"content_hash": "0" * 64}), cb, "content_hash_mismatch"),
        (candidate.model_copy(update={"tenant_id": "other"}), cb, "tenant_mismatch"),
        (
            candidate.model_copy(update={"created_at": p.locked_at - timedelta(seconds=1)}),
            cb,
            "lock_order_invalid",
        ),
        (
            candidate.model_copy(update={"protocol_content_hash": "0" * 64}),
            cb,
            "protocol_reference_mismatch",
        ),
    ]
    for item, content, reason in cases:
        with pytest.raises(BenchmarkForecastVerificationError) as exc:
            verify_forecast_set(item, content, p, s, c, f, raw)
        assert exc.value.reason == reason
        assert str(exc.value) == "Benchmark forecast verification failed and was rejected"
    with pytest.raises(BenchmarkScoreVerificationError) as score_exc:
        verify_benchmark_score_report(
            report.model_copy(update={"limitations": ("Edited",)}),
            candidate,
            cb,
            reference,
            rb,
            p,
            s,
            c,
            f,
            raw,
        )
    assert score_exc.value.reason == "content_hash_mismatch"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda b: b.replace(b"\n", b"\r\n"), "invalid_csv"),
        (lambda b: bytes([239, 187, 191]) + b, "invalid_csv"),
        (lambda b: b.rstrip(b"\n"), "invalid_csv"),
        (lambda b: b.replace(b"weekly.csv", b'"weekly.csv"'), "invalid_csv"),
        (lambda b: b.replace(b",11,", b",1e3,", 1), "invalid_value"),
        (lambda b: b.replace(b",11,", b",11.0000000,", 1), "invalid_value"),
        (lambda b: b.replace(b",11,", b",12,", 1), "non_monotone_quantiles"),
        (lambda b: b.replace(b",1,11", b",01,11", 1), "task_coverage_mismatch"),
    ],
)
def test_csv_tampering(mutation: Any, reason: str) -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    content = mutation(cb)
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(reseal(candidate, content), content, p, s, c, f, raw)
    assert exc.value.reason == reason


def test_holdout_and_invalid_types() -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    invalid: Any = None
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(invalid, cb, p, s, c, f, raw)
    assert exc.value.reason == "invalid_manifest"
    with pytest.raises(SealedPartitionError):
        verify_forecast_set(
            candidate.model_copy(update={"partition": "holdout"}), cb, p, s, c, f, raw
        )
    with pytest.raises(SealedPartitionError):
        verify_benchmark_score_report(
            report.model_copy(update={"partition": "holdout"}),
            candidate,
            cb,
            reference,
            rb,
            p,
            s,
            c,
            f,
            raw,
        )


@pytest.mark.parametrize(
    "reason",
    [
        "invalid_manifest",
        "candidate_input_invalid",
        "reference_input_invalid",
        "protocol_reference_mismatch",
        "tenant_mismatch",
        "forecast_reference_mismatch",
        "partition_mismatch",
        "reference_producer_mismatch",
        "candidate_is_reference",
        "lock_order_invalid",
        "cell_mismatch",
        "content_hash_mismatch",
    ],
)
def test_report_rejection_reasons(reason: str) -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    if reason == "invalid_manifest":
        report = None
    elif reason == "candidate_input_invalid":
        cb = b"edited"
    elif reason == "reference_input_invalid":
        rb = b"edited"
    elif reason == "protocol_reference_mismatch":
        report = report.model_copy(update={"protocol_content_hash": "0" * 64})
    elif reason == "tenant_mismatch":
        report = report.model_copy(update={"tenant_id": "other"})
    elif reason == "forecast_reference_mismatch":
        report = report.model_copy(update={"candidate_forecast_set_content_hash": "0" * 64})
    elif reason == "partition_mismatch":
        report = report.model_copy(update={"partition": "validation"})
    elif reason == "reference_producer_mismatch":
        reference = reference.model_copy(
            update={"producer": reference.producer.model_copy(update={"producer_id": "other"})}
        )
        reference = reseal(reference, rb)
        report = report.model_copy(
            update={"reference_forecast_set_content_hash": reference.content_hash}
        )
    elif reason == "candidate_is_reference":
        candidate = reseal(candidate.model_copy(update={"producer": reference.producer}), cb)
        report = report.model_copy(
            update={"candidate_forecast_set_content_hash": candidate.content_hash}
        )
    elif reason == "lock_order_invalid":
        report = report.model_copy(update={"scored_at": NOW - timedelta(seconds=1)})
    elif reason == "cell_mismatch":
        cells = list(report.cells)
        cells[0] = cells[0].model_copy(update={"inadmissible_origin_tasks": 99})
        report = report.model_copy(update={"cells": tuple(cells)})
    else:
        report = report.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(BenchmarkScoreVerificationError) as exc:
        verify_benchmark_score_report(report, candidate, cb, reference, rb, p, s, c, f, raw)
    assert exc.value.reason == reason
    assert str(exc.value) == "Benchmark score verification failed and was rejected"


def test_forecast_verifier_revalidation_order() -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    wrong = candidate.model_copy(update={"protocol_content_hash": "0" * 64, "tenant_id": "other"})
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(wrong, cb, p, s, c, f, raw)
    assert exc.value.reason == "protocol_reference_mismatch"
    invalid = candidate.model_copy(update={"partition": "bogus"})
    with pytest.raises(BenchmarkForecastVerificationError) as invalid_exc:
        verify_forecast_set(invalid, cb, p, s, c, f, raw)
    assert invalid_exc.value.reason == "invalid_manifest"
    with pytest.raises(BenchmarkForecastVerificationError) as bad_chain:
        verify_forecast_set(candidate, cb, p, s, c, f, {})
    assert bad_chain.value.reason == "protocol_input_invalid"


@pytest.mark.parametrize(
    "value", ["1e3", "1/3", " 1", "1 ", "1\n", "+1", ".5", "1.", "1.0000000", "١", "", "nan", "inf"]
)
def test_forecast_value_grammar_through_verifier(value: str) -> None:
    import csv
    import io

    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    rows = list(csv.reader(io.StringIO(cb.decode(), newline="")))
    rows[1][4] = value
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    content = output.getvalue().encode()
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(reseal(candidate, content), content, p, s, c, f, raw)
    assert exc.value.reason == "invalid_value"


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate", "swapped"])
def test_coverage_requires_exact_order(change: str) -> None:
    raw, raw_files, curated, files, split, protocol, candidate, cb, reference, rb = prepared(
        "validation"
    )
    rows = cb.splitlines(keepends=True)
    assert len(rows) >= 4
    if change == "extra":
        rows.append(rows[-1])
    elif change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = rows[-2]
    else:
        rows[1], rows[2] = rows[2], rows[1]
    content = b"".join(rows)
    item = reseal(candidate, content, len(rows) - 1)
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(
            item, content, protocol, split, curated, files, {raw.identifier: (raw, raw_files)}
        )
    assert exc.value.reason == "task_coverage_mismatch"


@pytest.mark.parametrize("change", ["blank", "header", "width"])
def test_csv_structure_rejected(change: str) -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    if change == "blank":
        content = cb + b"\n"
    elif change == "header":
        content = cb.replace(b"q0.025", b"q0.02", 1)
    else:
        content = cb.replace(b",11\n", b"\n", 1)
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(reseal(candidate, content), content, p, s, c, f, raw)
    assert exc.value.reason == "invalid_csv"


def test_forged_manifests_and_stale_file_content_hash() -> None:
    from kalhas.contracts.v1.benchmark_forecast import BenchmarkScoreReport, ForecastSet

    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    forged = ForecastSet.model_construct(**{**candidate.model_dump(), "producer": "invalid"})
    with pytest.raises(BenchmarkForecastVerificationError) as invalid_forecast:
        verify_forecast_set(forged, cb, p, s, c, f, raw)
    assert invalid_forecast.value.reason == "invalid_manifest"
    forged_report = BenchmarkScoreReport.model_construct(**{**report.model_dump(), "cells": ()})
    with pytest.raises(BenchmarkScoreVerificationError) as invalid_report:
        verify_benchmark_score_report(forged_report, candidate, cb, reference, rb, p, s, c, f, raw)
    assert invalid_report.value.reason == "invalid_manifest"
    changed = cb.replace(b",11,", b",10,", 1)
    descriptor = ForecastFile(
        path="forecasts.csv",
        sha256=hashlib.sha256(changed).hexdigest(),
        byte_size=len(changed),
        row_count=candidate.forecasts_file.row_count,
    )
    stale = candidate.model_copy(update={"forecasts_file": descriptor})
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(stale, changed, p, s, c, f, raw)
    assert exc.value.reason == "content_hash_mismatch"
    with pytest.raises(SealedPartitionError):
        verify_benchmark_score_report(
            report,
            candidate.model_copy(update={"partition": "holdout"}),
            cb,
            reference,
            rb,
            p,
            s,
            c,
            f,
            raw,
        )


def test_row_count_is_checked_before_coverage() -> None:
    p, s, c, f, raw, candidate, cb, reference, rb, report = context()
    changed = reseal(candidate, cb, 0)
    with pytest.raises(BenchmarkForecastVerificationError) as exc:
        verify_forecast_set(changed, cb, p, s, c, f, raw)
    assert exc.value.reason == "file_mismatch"
