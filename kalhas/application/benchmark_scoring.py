"""Deterministic rational forecast scoring over recorded benchmark tasks."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_task_engine import (
    BenchmarkTask,
    _input_rows,
    _partition,
    derive_benchmark_tasks,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.benchmark_forecast import (
    BenchmarkScoreReport,
    ForecastFile,
    ForecastProducer,
    ForecastSet,
    ScoreCell,
    ScoreSummary,
    Verdict,
    VerdictReason,
)
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.shared import JsonValue

FORECAST_CSV_HEADER = (
    "path",
    "series",
    "origin",
    "horizon",
    "q0.025",
    "q0.1",
    "q0.25",
    "q0.5",
    "q0.75",
    "q0.9",
    "q0.975",
)


@dataclass(frozen=True, slots=True)
class ForecastRow:
    path: str
    series: str
    origin: str
    horizon: int
    quantiles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskScore:
    wis: Fraction
    absolute_error: Fraction
    in_50: bool
    in_95: bool


def _decimal_fraction(text: str) -> Fraction:
    """Parse already-validated decimal text without an interpreter digit limit."""
    negative = text.startswith("-")
    whole, _, fraction = text.removeprefix("-").partition(".")
    digits = whole + fraction
    numerator = 0
    for start in range(0, len(digits), 9):
        chunk = digits[start : start + 9]
        numerator = numerator * 10 ** len(chunk) + int(chunk)
    if negative:
        numerator = -numerator
    return Fraction(numerator, 10 ** len(fraction))


def parse_forecast_value(text: str) -> Fraction:
    if not isinstance(text, str) or re.fullmatch(r"-?[0-9]+(\.[0-9]{1,6})?", text) is None:
        raise BenchmarkError("invalid_value")
    return _decimal_fraction(text)


def parse_observed_value(text: str) -> Fraction:
    if not isinstance(text, str) or re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", text) is None:
        raise BenchmarkError("invalid_target_value")
    return _decimal_fraction(text)


def weighted_interval_score(quantiles: Sequence[Fraction], observed: Fraction) -> Fraction:
    if len(quantiles) != 7:
        raise BenchmarkError("invalid_input")
    result = Fraction(1, 2) * abs(observed - quantiles[3])
    for lo, hi, alpha in ((0, 6, Fraction(1, 20)), (1, 5, Fraction(1, 5)), (2, 4, Fraction(1, 2))):
        lower, upper = quantiles[lo], quantiles[hi]
        interval = upper - lower
        if observed < lower:
            interval += Fraction(2) / alpha * (lower - observed)
        if observed > upper:
            interval += Fraction(2) / alpha * (observed - upper)
        result += alpha / 2 * interval
    return result / Fraction(7, 2)


def score_task(quantiles: Sequence[Fraction], observed: Fraction) -> TaskScore:
    wis = weighted_interval_score(quantiles, observed)
    return TaskScore(
        wis,
        abs(observed - quantiles[3]),
        quantiles[2] <= observed <= quantiles[4],
        quantiles[0] <= observed <= quantiles[6],
    )


def quantize_half_even(value: Fraction) -> str:
    scaled = value * 1_000_000
    floor = scaled.numerator // scaled.denominator
    remainder = scaled - floor
    if remainder > Fraction(1, 2) or (remainder == Fraction(1, 2) and floor % 2):
        floor += 1
    sign = "-" if floor < 0 else ""
    integer, fraction = divmod(abs(floor), 1_000_000)
    chunks: list[int] = []
    while integer >= 1_000_000_000:
        integer, tail = divmod(integer, 1_000_000_000)
        chunks.append(tail)
    whole = str(integer) + "".join(f"{chunk:09d}" for chunk in reversed(chunks))
    return f"{sign}{whole}.{fraction:06d}"


def summarize_task_scores(scores: Sequence[TaskScore]) -> ScoreSummary:
    if not scores:
        raise BenchmarkError("invalid_input")
    count = len(scores)
    return ScoreSummary(
        mean_wis=quantize_half_even(sum((s.wis for s in scores), Fraction()) / count),
        mean_absolute_error=quantize_half_even(
            sum((s.absolute_error for s in scores), Fraction()) / count
        ),
        coverage_50=quantize_half_even(Fraction(sum(s.in_50 for s in scores), count)),
        coverage_95=quantize_half_even(Fraction(sum(s.in_95 for s in scores), count)),
    )


def decide_verdict(
    evaluable_tasks: int,
    minimum_evaluable_tasks: int,
    candidate_wis_sum: Fraction,
    reference_wis_sum: Fraction,
    threshold: str,
) -> tuple[str | None, Verdict, VerdictReason]:
    if evaluable_tasks == 0:
        return None, "inconclusive", "insufficient_evaluable_tasks"
    relative = candidate_wis_sum / reference_wis_sum if reference_wis_sum > 0 else None
    text = quantize_half_even(relative) if relative is not None else None
    if evaluable_tasks < minimum_evaluable_tasks:
        return text, "inconclusive", "insufficient_evaluable_tasks"
    if reference_wis_sum == 0:
        return None, "inconclusive", "reference_score_zero"
    if relative is None:
        raise BenchmarkError("invalid_input")
    if relative < Fraction(threshold):
        return text, "pass", "below_threshold"
    return text, "fail", "not_below_threshold"


def _render_rows(rows: Sequence[Sequence[str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def render_forecast_csv(rows: Sequence[ForecastRow]) -> bytes:
    return _render_rows(
        [
            FORECAST_CSV_HEADER,
            *((row.path, row.series, row.origin, str(row.horizon), *row.quantiles) for row in rows),
        ]
    )


def _parse_csv(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8")
        if text.startswith("\ufeff"):
            raise ValueError
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        if not rows or tuple(rows[0]) != FORECAST_CSV_HEADER or any(len(r) != 11 for r in rows):
            raise ValueError
        if _render_rows(rows) != content:
            raise ValueError
        return rows[1:]
    except (UnicodeError, csv.Error, ValueError):
        raise BenchmarkError("invalid_csv") from None


def _task_key(task: BenchmarkTask) -> tuple[str, str, str, str]:
    return (task.path, task.series, task.origin, str(task.horizon))


def _checked_values(rows: list[list[str]]) -> list[tuple[Fraction, ...]]:
    parsed = [tuple(parse_forecast_value(value) for value in row[4:]) for row in rows]
    if any(any(a > b for a, b in zip(q, q[1:], strict=False)) for q in parsed):
        raise BenchmarkError("non_monotone_quantiles")
    return parsed


def resolve_target_values(
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
) -> dict[tuple[str, str, str, int], str]:
    _partition(partition)
    tasks = derive_benchmark_tasks(
        protocol, split_manifest, curated_manifest, curated_files, partition
    )
    rows = _input_rows(protocol, split_manifest, curated_manifest, curated_files)
    values = {(row.path, row.series, row.text): row.value for row in rows if row.label == partition}
    return {
        (t.path, t.series, t.origin, t.horizon): values[(t.path, t.series, t.target_time)]
        for t in tasks
        if t.status == "evaluable"
    }


def compute_forecast_set_content_hash(forecast_set: ForecastSet) -> str:
    payload = forecast_set.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def compute_benchmark_score_report_content_hash(report: BenchmarkScoreReport) -> str:
    payload = report.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def build_forecast_set(
    *,
    forecast_set_id: str,
    forecast_set_version: str,
    protocol: BenchmarkProtocol,
    partition: str,
    producer: ForecastProducer,
    csv_bytes: bytes,
    row_count: int,
    created_at: datetime,
    metadata: dict[str, JsonValue],
) -> ForecastSet:
    _partition(partition)
    data = {
        "identifier": f"forecast-set-{forecast_set_id}-{forecast_set_version}",
        "tenant_id": protocol.tenant_id,
        "forecast_set_id": forecast_set_id,
        "forecast_set_version": forecast_set_version,
        "protocol_manifest_id": protocol.identifier,
        "protocol_content_hash": protocol.content_hash,
        "partition": partition,
        "producer": producer,
        "forecasts_file": ForecastFile(
            path="forecasts.csv",
            sha256=hashlib.sha256(csv_bytes).hexdigest(),
            byte_size=len(csv_bytes),
            row_count=row_count,
        ),
        "created_at": created_at,
        "content_hash": "0" * 64,
        "metadata": metadata,
    }
    artifact = ForecastSet.model_validate(data)
    return artifact.model_copy(update={"content_hash": compute_forecast_set_content_hash(artifact)})


def score_forecast_sets(
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    candidate: ForecastSet,
    candidate_csv: bytes,
    reference: ForecastSet,
    reference_csv: bytes,
) -> tuple[ScoreCell, ...]:
    if type(candidate) is not ForecastSet or type(reference) is not ForecastSet:
        raise BenchmarkError("invalid_input")
    _partition(candidate.partition)
    _partition(reference.partition)
    try:
        candidate = ForecastSet.model_validate(
            candidate.model_dump(mode="python", warnings="error"), strict=True
        )
        reference = ForecastSet.model_validate(
            reference.model_dump(mode="python", warnings="error"), strict=True
        )
        if type(protocol) is not BenchmarkProtocol:
            raise BenchmarkError("invalid_input")
        for artifact in (candidate, reference):
            if artifact.tenant_id != protocol.tenant_id:
                raise BenchmarkError("invalid_input")
            if (
                artifact.protocol_manifest_id != protocol.identifier
                or artifact.protocol_content_hash != protocol.content_hash
                or artifact.content_hash != compute_forecast_set_content_hash(artifact)
            ):
                raise BenchmarkError("reference_mismatch")
        if candidate.partition != reference.partition:
            raise BenchmarkError("partition_mismatch")
        if (
            reference.producer.kind != "baseline"
            or reference.producer.producer_id != protocol.comparison.reference_baseline_id
            or reference.producer.producer_version != protocol.comparison.reference_baseline_version
        ):
            raise BenchmarkError("reference_producer_mismatch")
        if candidate.producer == reference.producer:
            raise BenchmarkError("candidate_is_reference")
        tasks = derive_benchmark_tasks(
            protocol, split_manifest, curated_manifest, curated_files, candidate.partition
        )
        evaluable = [t for t in tasks if t.status == "evaluable"]
        parsed = []
        for artifact, content in ((candidate, candidate_csv), (reference, reference_csv)):
            if (
                type(content) is not bytes
                or len(content) != artifact.forecasts_file.byte_size
                or hashlib.sha256(content).hexdigest() != artifact.forecasts_file.sha256
            ):
                raise BenchmarkError("file_mismatch")
            rows = _parse_csv(content)
            if len(rows) != artifact.forecasts_file.row_count:
                raise BenchmarkError("file_mismatch")
            if [tuple(r[:4]) for r in rows] != [_task_key(t) for t in evaluable]:
                raise BenchmarkError("task_coverage_mismatch")
            parsed.append(_checked_values(rows))
        targets = resolve_target_values(
            protocol, split_manifest, curated_manifest, curated_files, candidate.partition
        )
        values = [
            parse_observed_value(targets[(t.path, t.series, t.origin, t.horizon)])
            for t in evaluable
        ]
        all_scores = [
            [score_task(q, y) for q, y in zip(quantiles, values, strict=True)]
            for quantiles in parsed
        ]
        result = []
        for target in protocol.targets:
            for horizon in target.horizons:
                group = [t for t in tasks if t.path == target.path and t.horizon == horizon]
                indices = [
                    i
                    for i, t in enumerate(evaluable)
                    if t.path == target.path and t.horizon == horizon
                ]
                cs = [all_scores[0][i] for i in indices]
                rs = [all_scores[1][i] for i in indices]
                relative, verdict, reason = decide_verdict(
                    len(indices),
                    target.minimum_evaluable_tasks,
                    sum((s.wis for s in cs), Fraction()),
                    sum((s.wis for s in rs), Fraction()),
                    protocol.comparison.relative_wis_pass_below,
                )
                result.append(
                    ScoreCell(
                        path=target.path,
                        horizon=horizon,
                        evaluable_tasks=len(indices),
                        inadmissible_origin_tasks=sum(
                            t.status == "inadmissible_origin" for t in group
                        ),
                        insufficient_history_tasks=sum(
                            t.status == "insufficient_history" for t in group
                        ),
                        candidate=summarize_task_scores(cs) if cs else None,
                        reference=summarize_task_scores(rs) if rs else None,
                        relative_wis=relative,
                        verdict=verdict,
                        verdict_reason=reason,
                    )
                )
        return tuple(result)
    except BenchmarkError:
        raise
    except Exception:
        raise BenchmarkError("invalid_input") from None


def build_benchmark_score_report(
    *,
    report_id: str,
    report_version: str,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    candidate: ForecastSet,
    candidate_csv: bytes,
    reference: ForecastSet,
    reference_csv: bytes,
    limitations: tuple[str, ...],
    scored_at: datetime,
    metadata: dict[str, JsonValue],
) -> BenchmarkScoreReport:
    cells = score_forecast_sets(
        protocol,
        split_manifest,
        curated_manifest,
        curated_files,
        candidate,
        candidate_csv,
        reference,
        reference_csv,
    )
    data = {
        "identifier": f"benchmark-score-report-{report_id}-{report_version}",
        "tenant_id": protocol.tenant_id,
        "report_id": report_id,
        "report_version": report_version,
        "protocol_manifest_id": protocol.identifier,
        "protocol_content_hash": protocol.content_hash,
        "partition": candidate.partition,
        "candidate_forecast_set_id": candidate.identifier,
        "candidate_forecast_set_content_hash": candidate.content_hash,
        "reference_forecast_set_id": reference.identifier,
        "reference_forecast_set_content_hash": reference.content_hash,
        "scoring_rule": protocol.scoring_rule,
        "cells": cells,
        "limitations": limitations,
        "scored_at": scored_at,
        "content_hash": "0" * 64,
        "metadata": metadata,
    }
    report = BenchmarkScoreReport.model_validate(data)
    return report.model_copy(
        update={"content_hash": compute_benchmark_score_report_content_hash(report)}
    )
