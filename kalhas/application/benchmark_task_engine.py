"""Pure value-blind task derivation and sealed information-set views."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_protocol_verifier import (
    _targets_valid,
    compute_benchmark_protocol_content_hash,
)
from kalhas.application.curated_dataset_verifier import compute_curated_dataset_content_hash
from kalhas.application.dataset_split_engine import _rows, compute_split_membership
from kalhas.application.dataset_split_errors import SealedPartitionError
from kalhas.application.dataset_split_verifier import compute_dataset_split_content_hash
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest, parse_split_time

Partition = Literal["development", "validation"]
Status = Literal["evaluable", "inadmissible_origin", "insufficient_history"]
TimeType = Literal["date", "iso_week"]


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    path: str
    series: str
    origin: str
    horizon: int
    target_time: str
    partition: Partition
    status: Status


@dataclass(frozen=True, slots=True)
class _PresentRow:
    path: str
    series: str
    time: date
    text: str
    kind: TimeType
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class _InformationRow:
    path: str
    series: str
    time: date
    text: str
    kind: TimeType
    value: str


@dataclass(frozen=True, slots=True)
class BenchmarkInformationSet:
    """Immutable view containing only rows permitted for its partition."""

    partition: Partition
    _types: tuple[tuple[str, TimeType], ...]
    _rows: tuple[_InformationRow, ...]

    def rows(self, task: BenchmarkTask, path: str, series: str) -> tuple[tuple[str, str], ...]:
        if task.partition != self.partition:
            raise BenchmarkError("partition_mismatch")
        kinds = dict(self._types)
        if path not in kinds or task.path not in kinds:
            raise BenchmarkError("unknown_target")
        try:
            origin = _parse(task.origin, kinds[task.path])
        except (ValueError, OverflowError) as exc:
            raise BenchmarkError("time_value_invalid") from exc
        origin_kind = kinds[task.path]
        result = []
        for row in self._rows:
            if row.path != path or row.series != series:
                continue
            row_time, task_time = row.time.toordinal(), origin.toordinal()
            if row.kind != origin_kind:
                if row.kind == "iso_week":
                    row_time += 6
                if origin_kind == "iso_week":
                    task_time += 6
            if row_time <= task_time:
                result.append((row.text, row.value))
        return tuple(result)


def _parse(text: str, kind: TimeType) -> date:
    parts = parse_split_time(text, kind)
    if kind == "date":
        return date(parts[0], parts[1], parts[2])
    return date.fromisocalendar(parts[0], parts[1], 1)


def _text(value: date, kind: TimeType) -> str:
    if kind == "date":
        return value.isoformat()
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _partition(value: str) -> Partition:
    if value == "holdout":
        raise SealedPartitionError()
    if value == "development":
        return "development"
    if value == "validation":
        return "validation"
    raise BenchmarkError("invalid_partition")


def _input_rows(
    protocol: BenchmarkProtocol,
    split: DatasetSplitManifest,
    curated: CuratedDatasetManifest,
    files: Mapping[str, bytes],
) -> tuple[_PresentRow, ...]:
    if (
        type(protocol) is not BenchmarkProtocol
        or type(split) is not DatasetSplitManifest
        or type(curated) is not CuratedDatasetManifest
    ):
        raise BenchmarkError("invalid_input")
    try:
        protocol = BenchmarkProtocol.model_validate(protocol.model_dump(mode="python"), strict=True)
        split = DatasetSplitManifest.model_validate(split.model_dump(mode="python"), strict=True)
        curated = CuratedDatasetManifest.model_validate(
            curated.model_dump(mode="python"), strict=True
        )
        if (protocol.split_manifest_id, protocol.split_content_hash) != (
            split.identifier,
            split.content_hash,
        ):
            raise BenchmarkError("reference_mismatch")
        ref = (
            protocol.curated_manifest_id,
            protocol.curated_content_hash,
            protocol.curated_bundle_hash,
        )
        if ref != (
            split.curated_manifest_id,
            split.curated_content_hash,
            split.curated_bundle_hash,
        ) or ref != (curated.identifier, curated.content_hash, curated.bundle_hash):
            raise BenchmarkError("reference_mismatch")
        if (
            compute_benchmark_protocol_content_hash(protocol) != protocol.content_hash
            or compute_dataset_split_content_hash(split) != split.content_hash
            or compute_curated_dataset_content_hash(curated) != curated.content_hash
        ):
            raise BenchmarkError("reference_mismatch")
        if (
            protocol.tenant_id != split.tenant_id
            or split.tenant_id != curated.tenant_id
            or protocol.locked_at < split.locked_at
            or not _targets_valid(protocol, curated)
        ):
            raise BenchmarkError("invalid_input")
        if not isinstance(files, Mapping) or set(files) != {f.path for f in curated.files}:
            raise BenchmarkError("invalid_input")
        for file in curated.files:
            content = files[file.path]
            if (
                type(content) is not bytes
                or len(content) != file.byte_size
                or hashlib.sha256(content).hexdigest() != file.sha256
            ):
                raise BenchmarkError("invalid_input")
        labels = compute_split_membership(split.file_rules, curated, files)
        if [r.path for r in split.file_rules] != [f.path for f in curated.files]:
            raise BenchmarkError("invalid_input")
        for membership in split.memberships:
            _, counts, digest = labels[membership.path]
            if (counts, digest) != (membership.counts, membership.membership_hash):
                raise BenchmarkError("invalid_input")
        declared = {f.path: f for f in curated.files}
        result = []
        for target in protocol.targets:
            file = declared[target.path]
            columns = {c.name: c for c in file.columns}
            header = [c.name for c in file.columns]
            si, ti, vi = (
                header.index(x)
                for x in (target.series_column, target.time_column, target.value_column)
            )
            kind: TimeType = (
                "date" if columns[target.time_column].value_type == "date" else "iso_week"
            )
            seen: set[tuple[str, date]] = set()
            for row, label in zip(
                _rows(files[target.path], header), labels[target.path][0], strict=True
            ):
                if row[vi] in columns[target.value_column].missing_tokens:
                    continue
                try:
                    parsed = _parse(row[ti], kind)
                except (ValueError, OverflowError) as exc:
                    raise BenchmarkError("time_value_invalid") from exc
                key = (row[si], parsed)
                if key in seen:
                    raise BenchmarkError("duplicate_series_time")
                seen.add(key)
                result.append(
                    _PresentRow(
                        target.path, row[si], parsed, _text(parsed, kind), kind, row[vi], label
                    )
                )
        return tuple(result)
    except BenchmarkError:
        raise
    except Exception as exc:
        raise BenchmarkError("invalid_input") from exc


def derive_benchmark_tasks(
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
) -> tuple[BenchmarkTask, ...]:
    selected = _partition(partition)
    rows = _input_rows(protocol, split_manifest, curated_manifest, curated_files)
    allowed = {"development"} if selected == "development" else {"development", "validation"}
    result: list[BenchmarkTask] = []
    for target in protocol.targets:
        subset = sorted(
            (r for r in rows if r.path == target.path), key=lambda r: (r.series, r.time)
        )
        by_key = {(r.series, r.time): r for r in subset}
        history_by_series: dict[str, list[int]] = {}
        for row in subset:
            if row.label in allowed:
                history_by_series.setdefault(row.series, []).append(row.time.toordinal())
        for origin in subset:
            unit = 1 if origin.kind == "date" else 7
            dates = history_by_series.get(origin.series, [])
            upper = origin.time.toordinal()
            history = bisect_right(dates, upper) - bisect_right(
                dates, upper - unit * target.history_window
            )
            for horizon in target.horizons:
                try:
                    target_time = origin.time + timedelta(days=unit * horizon)
                except OverflowError:
                    continue
                future = by_key.get((origin.series, target_time))
                if future is None or future.label != selected:
                    continue
                status: Status = (
                    "inadmissible_origin"
                    if origin.label not in allowed
                    else "insufficient_history"
                    if history < target.min_history_points
                    else "evaluable"
                )
                result.append(
                    BenchmarkTask(
                        target.path,
                        origin.series,
                        origin.text,
                        horizon,
                        _text(target_time, origin.kind),
                        selected,
                        status,
                    )
                )
    return tuple(result)


def build_information_set(
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
) -> BenchmarkInformationSet:
    selected = _partition(partition)
    rows = _input_rows(protocol, split_manifest, curated_manifest, curated_files)
    allowed = {"development"} if selected == "development" else {"development", "validation"}
    keep = tuple(
        _InformationRow(r.path, r.series, r.time, r.text, r.kind, r.value)
        for r in sorted(rows, key=lambda r: (r.path, r.series, r.time))
        if r.label in allowed
    )
    kinds = tuple(
        (t.path, next(r.kind for r in rows if r.path == t.path))
        if any(r.path == t.path for r in rows)
        else (
            t.path,
            "date"
            if next(
                c
                for f in curated_manifest.files
                if f.path == t.path
                for c in f.columns
                if c.name == t.time_column
            ).value_type
            == "date"
            else "iso_week",
        )
        for t in protocol.targets
    )
    return BenchmarkInformationSet(selected, kinds, keep)
