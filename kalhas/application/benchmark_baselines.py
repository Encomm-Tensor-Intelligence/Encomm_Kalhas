"""Deterministic reference forecasts over the permitted information-set view."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from fractions import Fraction

from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_forecast_errors import BenchmarkBaselineVerificationError
from kalhas.application.benchmark_forecast_verifier import verify_forecast_set
from kalhas.application.benchmark_scoring import (
    ForecastRow,
    build_forecast_set,
    parse_observed_value,
    quantize_half_even,
    render_forecast_csv,
)
from kalhas.application.benchmark_task_engine import (
    BenchmarkInformationSet,
    BenchmarkTask,
    TimeType,
    _parse,
    build_information_set,
    derive_benchmark_tasks,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.benchmark_forecast import ForecastProducer, ForecastSet
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol, BenchmarkTarget
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.shared import JsonValue

POINT_BASELINE_ID = "kalhas-persistence-point-v1"
QUANTILE_BASELINE_ID = "kalhas-persistence-quantile-v1"
BASELINE_VERSION = "1.0.0"
BASELINE_CONFIGURATION_HASH = sha256_hex(canonical_json({}))
_LEVELS = (
    Fraction(1, 40),
    Fraction(1, 10),
    Fraction(1, 4),
    Fraction(1, 2),
    Fraction(3, 4),
    Fraction(9, 10),
    Fraction(39, 40),
)


def type7_quantile(sorted_values: Sequence[Fraction], level: Fraction) -> Fraction:
    if (
        not sorted_values
        or type(level) is not Fraction
        or not 0 <= level <= 1
        or any(type(value) is not Fraction for value in sorted_values)
    ):
        raise BenchmarkError("invalid_input")
    position = (len(sorted_values) - 1) * level
    index = position.numerator // position.denominator
    if index + 1 == len(sorted_values):
        return sorted_values[index]
    return sorted_values[index] + (position - index) * (
        sorted_values[index + 1] - sorted_values[index]
    )


def symmetric_difference_offsets(differences: Sequence[Fraction]) -> tuple[Fraction, ...]:
    if not differences or any(type(value) is not Fraction for value in differences):
        raise BenchmarkError("invalid_input")
    values = sorted(value for difference in differences for value in (difference, -difference))
    return tuple(type7_quantile(values, level) for level in _LEVELS)


def _task_values(
    baseline_id: str,
    task: BenchmarkTask,
    target: BenchmarkTarget,
    kind: TimeType,
    view: BenchmarkInformationSet,
) -> tuple[tuple[str, ...], bool]:
    observations = view.rows(task, task.path, task.series)
    origin_values = [value for text, value in observations if text == task.origin]
    if len(origin_values) != 1:
        raise BenchmarkError("invalid_input")
    origin_value = parse_observed_value(origin_values[0])
    fallback = False
    values: tuple[Fraction, ...] = (origin_value,) * 7
    if baseline_id == QUANTILE_BASELINE_ID:
        origin = _parse(task.origin, kind)
        unit = 1 if kind == "date" else 7
        boundary = origin.toordinal() - unit * target.history_window
        history = {
            parsed: parse_observed_value(value)
            for text, value in observations
            if boundary < (parsed := _parse(text, kind)).toordinal() <= origin.toordinal()
        }
        step = timedelta(days=unit * task.horizon)
        differences = [
            value - history[when - step]
            for when, value in history.items()
            if when.toordinal() - step.days >= 1 and when - step in history
        ]
        if differences:
            values = tuple(
                origin_value + offset for offset in symmetric_difference_offsets(differences)
            )
        else:
            fallback = True
        if target.non_negative:
            values = tuple(max(Fraction(0), value) for value in values)
    return tuple(quantize_half_even(value) for value in values), fallback


def render_baseline_forecasts(
    baseline_id: str,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
) -> tuple[bytes, int, dict[str, JsonValue]]:
    if baseline_id not in {POINT_BASELINE_ID, QUANTILE_BASELINE_ID}:
        raise BenchmarkError("unknown_baseline")
    tasks = derive_benchmark_tasks(
        protocol, split_manifest, curated_manifest, curated_files, partition
    )
    view = build_information_set(
        protocol, split_manifest, curated_manifest, curated_files, partition
    )
    targets = {target.path: target for target in protocol.targets}
    kinds: dict[str, TimeType] = {}
    for target in protocol.targets:
        column = next(
            column
            for item in curated_manifest.files
            if item.path == target.path
            for column in item.columns
            if column.name == target.time_column
        )
        kinds[target.path] = "date" if column.value_type == "date" else "iso_week"
    forecasts: list[ForecastRow] = []
    fallback_count = 0
    for task in tasks:
        if task.status != "evaluable":
            continue
        quantiles, fallback = _task_values(
            baseline_id, task, targets[task.path], kinds[task.path], view
        )
        fallback_count += int(fallback)
        forecasts.append(ForecastRow(task.path, task.series, task.origin, task.horizon, quantiles))
    metadata: dict[str, JsonValue] = (
        {"fallback_count": fallback_count} if baseline_id == QUANTILE_BASELINE_ID else {}
    )
    return render_forecast_csv(forecasts), len(forecasts), metadata


def _produce(
    baseline_id: str,
    *,
    forecast_set_id: str,
    forecast_set_version: str,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
    created_at: datetime,
) -> tuple[ForecastSet, bytes]:
    content, count, metadata = render_baseline_forecasts(
        baseline_id, protocol, split_manifest, curated_manifest, curated_files, partition
    )
    producer = ForecastProducer(
        kind="baseline",
        producer_id=baseline_id,
        producer_version=BASELINE_VERSION,
        configuration_hash=BASELINE_CONFIGURATION_HASH,
    )
    forecast = build_forecast_set(
        forecast_set_id=forecast_set_id,
        forecast_set_version=forecast_set_version,
        protocol=protocol,
        partition=partition,
        producer=producer,
        csv_bytes=content,
        row_count=count,
        created_at=created_at,
        metadata=metadata,
    )
    return forecast, content


def produce_persistence_point_forecasts(
    *,
    forecast_set_id: str,
    forecast_set_version: str,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
    created_at: datetime,
) -> tuple[ForecastSet, bytes]:
    return _produce(
        POINT_BASELINE_ID,
        forecast_set_id=forecast_set_id,
        forecast_set_version=forecast_set_version,
        protocol=protocol,
        split_manifest=split_manifest,
        curated_manifest=curated_manifest,
        curated_files=curated_files,
        partition=partition,
        created_at=created_at,
    )


def produce_persistence_quantile_forecasts(
    *,
    forecast_set_id: str,
    forecast_set_version: str,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
    created_at: datetime,
) -> tuple[ForecastSet, bytes]:
    return _produce(
        QUANTILE_BASELINE_ID,
        forecast_set_id=forecast_set_id,
        forecast_set_version=forecast_set_version,
        protocol=protocol,
        split_manifest=split_manifest,
        curated_manifest=curated_manifest,
        curated_files=curated_files,
        partition=partition,
        created_at=created_at,
    )


def verify_baseline_forecast_set(
    forecast_set: ForecastSet,
    csv_bytes: bytes,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    verify_forecast_set(
        forecast_set,
        csv_bytes,
        protocol,
        split_manifest,
        curated_manifest,
        curated_files,
        raw_bundles,
    )
    producer = forecast_set.producer
    if producer.kind != "baseline":
        raise BenchmarkBaselineVerificationError("not_a_baseline")
    if (producer.producer_id, producer.producer_version) not in {
        (POINT_BASELINE_ID, BASELINE_VERSION),
        (QUANTILE_BASELINE_ID, BASELINE_VERSION),
    }:
        raise BenchmarkBaselineVerificationError("unknown_baseline")
    if producer.configuration_hash != BASELINE_CONFIGURATION_HASH:
        raise BenchmarkBaselineVerificationError("configuration_mismatch")
    try:
        rendered, _, metadata = render_baseline_forecasts(
            producer.producer_id,
            protocol,
            split_manifest,
            curated_manifest,
            curated_files,
            forecast_set.partition,
        )
    except Exception:
        raise BenchmarkBaselineVerificationError("reexecution_mismatch") from None
    if rendered != csv_bytes:
        raise BenchmarkBaselineVerificationError("reexecution_mismatch")
    if canonical_json(metadata) != canonical_json(forecast_set.metadata):
        raise BenchmarkBaselineVerificationError("metadata_mismatch")
