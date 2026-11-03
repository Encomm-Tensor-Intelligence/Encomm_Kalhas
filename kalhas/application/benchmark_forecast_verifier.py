"""Verify forecast and score artifacts against their complete offline lineage."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from kalhas.application.benchmark_forecast_errors import (
    BenchmarkForecastVerificationError,
    BenchmarkScoreVerificationError,
)
from kalhas.application.benchmark_protocol_verifier import verify_benchmark_protocol
from kalhas.application.benchmark_scoring import (
    _checked_values,
    _parse_csv,
    _task_key,
    compute_benchmark_score_report_content_hash,
    compute_forecast_set_content_hash,
    score_forecast_sets,
)
from kalhas.application.benchmark_task_engine import derive_benchmark_tasks
from kalhas.application.dataset_split_errors import SealedPartitionError
from kalhas.contracts.v1.benchmark_forecast import BenchmarkScoreReport, ForecastSet
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest


def verify_forecast_set(
    forecast_set: ForecastSet,
    csv_bytes: bytes,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    error = BenchmarkForecastVerificationError
    if type(forecast_set) is not ForecastSet:
        raise error("invalid_manifest")
    try:
        item = ForecastSet.model_validate(
            forecast_set.model_dump(mode="python", warnings="error"), strict=True
        )
    except Exception:
        raise error("invalid_manifest") from None
    try:
        verify_benchmark_protocol(
            protocol, split_manifest, curated_manifest, curated_files, raw_bundles
        )
    except Exception:
        raise error("protocol_input_invalid") from None
    if (item.protocol_manifest_id, item.protocol_content_hash) != (
        protocol.identifier,
        protocol.content_hash,
    ):
        raise error("protocol_reference_mismatch")
    if item.tenant_id != protocol.tenant_id:
        raise error("tenant_mismatch")
    if item.created_at < protocol.locked_at:
        raise error("lock_order_invalid")
    if item.partition == "holdout":
        raise SealedPartitionError()
    if (
        type(csv_bytes) is not bytes
        or len(csv_bytes) != item.forecasts_file.byte_size
        or hashlib.sha256(csv_bytes).hexdigest() != item.forecasts_file.sha256
    ):
        raise error("file_mismatch")
    try:
        rows = _parse_csv(csv_bytes)
    except Exception:
        raise error("invalid_csv") from None
    if len(rows) != item.forecasts_file.row_count:
        raise error("file_mismatch")
    try:
        tasks = derive_benchmark_tasks(
            protocol, split_manifest, curated_manifest, curated_files, item.partition
        )
        if [tuple(row[:4]) for row in rows] != [
            _task_key(task) for task in tasks if task.status == "evaluable"
        ]:
            raise error("task_coverage_mismatch")
    except error:
        raise
    except Exception:
        raise error("task_coverage_mismatch") from None
    try:
        _checked_values(rows)
    except Exception as exc:
        reason = getattr(exc, "reason", "invalid_value")
        raise error(
            reason if reason in {"invalid_value", "non_monotone_quantiles"} else "invalid_value"
        ) from None
    try:
        if item.content_hash != compute_forecast_set_content_hash(item):
            raise error("content_hash_mismatch")
    except error:
        raise
    except Exception:
        raise error("content_hash_mismatch") from None


def verify_benchmark_score_report(
    report: BenchmarkScoreReport,
    candidate: ForecastSet,
    candidate_csv: bytes,
    reference: ForecastSet,
    reference_csv: bytes,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    error = BenchmarkScoreVerificationError
    if type(report) is not BenchmarkScoreReport:
        raise error("invalid_manifest")
    try:
        item = BenchmarkScoreReport.model_validate(
            report.model_dump(mode="python", warnings="error"), strict=True
        )
    except Exception:
        raise error("invalid_manifest") from None
    if item.partition == "holdout":
        raise SealedPartitionError()
    for artifact, content, reason in (
        (candidate, candidate_csv, "candidate_input_invalid"),
        (reference, reference_csv, "reference_input_invalid"),
    ):
        try:
            verify_forecast_set(
                artifact,
                content,
                protocol,
                split_manifest,
                curated_manifest,
                curated_files,
                raw_bundles,
            )
        except SealedPartitionError:
            raise
        except Exception:
            raise error(reason) from None
    if (item.protocol_manifest_id, item.protocol_content_hash) != (
        protocol.identifier,
        protocol.content_hash,
    ):
        raise error("protocol_reference_mismatch")
    if item.tenant_id != protocol.tenant_id:
        raise error("tenant_mismatch")
    if (
        item.candidate_forecast_set_id,
        item.candidate_forecast_set_content_hash,
        item.reference_forecast_set_id,
        item.reference_forecast_set_content_hash,
    ) != (
        candidate.identifier,
        candidate.content_hash,
        reference.identifier,
        reference.content_hash,
    ):
        raise error("forecast_reference_mismatch")
    if item.partition != candidate.partition or item.partition != reference.partition:
        raise error("partition_mismatch")
    if (
        reference.producer.kind != "baseline"
        or reference.producer.producer_id != protocol.comparison.reference_baseline_id
        or reference.producer.producer_version != protocol.comparison.reference_baseline_version
    ):
        raise error("reference_producer_mismatch")
    if candidate.producer == reference.producer:
        raise error("candidate_is_reference")
    if item.scored_at < candidate.created_at or item.scored_at < reference.created_at:
        raise error("lock_order_invalid")
    try:
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
        if cells != item.cells:
            raise error("cell_mismatch")
    except error:
        raise
    except Exception:
        raise error("cell_mismatch") from None
    try:
        if item.content_hash != compute_benchmark_score_report_content_hash(item):
            raise error("content_hash_mismatch")
    except error:
        raise
    except Exception:
        raise error("content_hash_mismatch") from None
