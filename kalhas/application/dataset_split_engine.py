"""Pure, value-blind assignment of curated rows to locked partitions."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence

from kalhas.application.dataset_split_errors import DatasetSplitError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset_split import FileSplitRule, PartitionCounts, parse_split_time


def _rows(content: bytes, header: list[str]) -> list[list[str]]:
    try:
        text = content.decode("utf-8")
        if text.startswith("\ufeff"):
            raise ValueError
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        if next(reader) != header:
            raise DatasetSplitError("header_mismatch")
        rows = list(reader)
        if any(len(row) != len(header) for row in rows):
            raise DatasetSplitError("row_width_mismatch")
        return rows
    except DatasetSplitError:
        raise
    except (UnicodeError, csv.Error, StopIteration, ValueError) as exc:
        raise DatasetSplitError("invalid_csv") from exc


def compute_split_membership(
    split_rules: Sequence[FileSplitRule],
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
) -> dict[str, tuple[list[str], PartitionCounts, str]]:
    """Return labels, counts and canonical JSON hash in each file's row order."""
    if type(curated_manifest) is not CuratedDatasetManifest or not isinstance(
        curated_files, Mapping
    ):
        raise DatasetSplitError("invalid_input")
    declarations = {file.path: file for file in curated_manifest.files}
    results: dict[str, tuple[list[str], PartitionCounts, str]] = {}
    for rule in split_rules:
        if type(rule) is not FileSplitRule or rule.path in results:
            raise DatasetSplitError("invalid_rule")
        file = declarations.get(rule.path)
        content = curated_files.get(rule.path)
        if file is None or type(content) is not bytes:
            raise DatasetSplitError("missing_file")
        columns = {column.name: column for column in file.columns}
        header = [column.name for column in file.columns]
        positions: dict[str, int] = {}
        for definition, allowed in (
            (rule.time_rule, curated_manifest.time_basis.time_columns),
            (rule.geography_rule, curated_manifest.geography_basis.geography_columns),
        ):
            if definition is None:
                continue
            if definition.column not in columns:
                raise DatasetSplitError("unknown_column")
            if definition.column not in allowed:
                raise DatasetSplitError("forbidden_column")
            positions[definition.column] = header.index(definition.column)
        if rule.time_rule is not None and (
            columns[rule.time_rule.column].value_type != rule.time_rule.value_type
        ):
            raise DatasetSplitError("time_type_mismatch")
        rows = _rows(content, header)
        geo = rule.geography_rule
        if geo is not None:
            observed = {row[positions[geo.column]] for row in rows}
            if not set(geo.validation_values + geo.holdout_values) <= observed:
                raise DatasetSplitError("unknown_geography_value")
        labels: list[str] = []
        for row in rows:
            is_holdout = False
            is_validation = False
            if geo is not None:
                value = row[positions[geo.column]]
                is_holdout = value in geo.holdout_values
                is_validation = value in geo.validation_values
            time = rule.time_rule
            if time is not None:
                value = row[positions[time.column]]
                if value in columns[time.column].missing_tokens:
                    raise DatasetSplitError("time_value_invalid")
                try:
                    parsed = parse_split_time(value, time.value_type)
                    is_holdout = is_holdout or parsed >= parse_split_time(
                        time.holdout_from, time.value_type
                    )
                    is_validation = is_validation or parsed >= parse_split_time(
                        time.validation_from, time.value_type
                    )
                except ValueError as exc:
                    raise DatasetSplitError("time_value_invalid") from exc
            labels.append(
                "holdout" if is_holdout else "validation" if is_validation else "development"
            )
        counts = PartitionCounts(
            development=labels.count("development"),
            validation=labels.count("validation"),
            holdout=labels.count("holdout"),
        )
        results[rule.path] = (labels, counts, sha256_hex(canonical_json(labels)))
    return results
