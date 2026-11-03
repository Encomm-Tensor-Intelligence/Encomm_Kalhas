"""Pure, closed dataset transformation engine (Phase 30, H30-S02A, ADR-007).

``execute_transformation_plan`` interprets one declarative
``TransformationPlan`` over raw bundles and returns the exact canonical
output bytes per output path. It is a pure function: no filesystem,
network, clock, randomness, logging, or global-state access, and it never
mutates its inputs. It performs no aggregation, interpolation, imputation,
smoothing, outlier removal, unit conversion, or statistics.

Semantics (exact):

- ``decode_text`` decodes the source bytes with the declared encoding;
  invalid bytes fail. ``utf-8`` keeps a leading byte order mark, so it then
  becomes part of the first header cell and fails the header check.
- ``parse_csv`` uses the stdlib ``csv`` reader (comma, double quote, strict
  quoting). The header must equal the raw manifest's declared column names
  for that file, exactly and in order, which proves the declarations true.
  Every row must have the header's width.
- A cell equal to one of its column's declared missing tokens is missing.
  Missing values are never coerced and render as empty cells. A column with
  declared missing tokens that also holds a literal empty non-missing cell
  would render ambiguously and fails closed.
- ``select_columns`` / ``rename_columns`` need existing names and keep the
  column names unique. ``filter_rows_in`` keeps a row when its raw cell text
  is in the declared values.
- ``cast_columns`` validates only and keeps the text verbatim: ``integer``
  is an optional ``-`` and ASCII digits; ``decimal`` is an optional ``-``,
  digits and an optional ``.`` fraction (finite, no exponent); ``date`` is
  strict ``YYYY-MM-DD``; ``iso_week`` is ``YYYY-Www`` with a week valid for
  that ISO year. Any failure fails the whole plan.
- ``require_unique_key`` fails on duplicate keys. ``sort_rows`` is a stable
  ascending sort by typed values (int, ``Decimal``, date, (year, week), or
  text for uncast columns) with missing values first.
- The writer is canonical: ``csv.writer`` with ``\\n`` line endings and
  minimal quoting, UTF-8 without a byte order mark, header first.

Every failure raises exactly one ``DatasetTransformationError`` with a
fixed generic message and a bounded reason; cell values are never echoed.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from kalhas.application.dataset_transformation_errors import DatasetTransformationError
from kalhas.contracts.v1.curated_dataset import (
    CastColumnsStep,
    CuratedOutputPlan,
    DecodeTextStep,
    FilterRowsInStep,
    RenameColumnsStep,
    RequireUniqueKeyStep,
    SelectColumnsStep,
    SortRowsStep,
    TransformationPlan,
)
from kalhas.contracts.v1.dataset import RawDatasetColumn, RawDatasetFile, RawDatasetManifest

__all__ = [
    "derive_transformation_output_columns",
    "execute_transformation_plan",
]

_INTEGER = re.compile(r"-?[0-9]+")
_DECIMAL = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ISO_WEEK = re.compile(r"([0-9]{4})-W([0-9]{2})")


class _Column:
    """Mutable per-execution column state (never shared with the inputs)."""

    __slots__ = ("cast", "name", "tokens", "unit", "value_type")

    def __init__(self, declaration: RawDatasetColumn) -> None:
        self.name = declaration.name
        self.value_type: str = declaration.value_type
        self.unit = declaration.unit
        self.tokens: tuple[str, ...] = tuple(declaration.missing_tokens)
        self.cast: str | None = None

    def is_missing(self, cell: str) -> bool:
        return cell in self.tokens


def _fail(reason: str) -> DatasetTransformationError:
    return DatasetTransformationError(reason)


def _valid_iso_week(text: str) -> tuple[int, int] | None:
    match = _ISO_WEEK.fullmatch(text)
    if match is None:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        weeks_in_year = date(year, 12, 28).isocalendar().week
    except ValueError:
        return None
    if not 1 <= week <= weeks_in_year:
        return None
    return year, week


def _typed_value(cast: str | None, text: str) -> object:
    """Parse one non-missing cell for the declared cast, or raise ``ValueError``."""
    if cast == "integer":
        if _INTEGER.fullmatch(text) is None:
            raise ValueError
        return int(text)
    if cast == "decimal":
        if _DECIMAL.fullmatch(text) is None:
            raise ValueError
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError from exc
        if not number.is_finite():
            raise ValueError
        return number
    if cast == "date":
        if _DATE.fullmatch(text) is None:
            raise ValueError
        return date.fromisoformat(text)
    if cast == "iso_week":
        week = _valid_iso_week(text)
        if week is None:
            raise ValueError
        return week
    return text


def _index(columns: list[_Column], name: str) -> int:
    for position, column in enumerate(columns):
        if column.name == name:
            return position
    raise _fail("unknown_column")


def _apply_select(
    columns: list[_Column], rows: list[list[str]], step: SelectColumnsStep
) -> tuple[list[_Column], list[list[str]]]:
    positions = [_index(columns, name) for name in step.columns]
    if len(set(positions)) != len(positions):
        raise _fail("duplicate_column")
    return (
        [columns[p] for p in positions],
        [[row[p] for p in positions] for row in rows],
    )


def _apply_rename(columns: list[_Column], step: RenameColumnsStep) -> None:
    for old in step.mapping:
        _index(columns, old)
    renamed = [step.mapping.get(column.name, column.name) for column in columns]
    if len(set(renamed)) != len(renamed):
        raise _fail("duplicate_column")
    for column, name in zip(columns, renamed, strict=True):
        column.name = name


def _apply_cast(columns: list[_Column], rows: list[list[str]], step: CastColumnsStep) -> None:
    for name, cast in step.types.items():
        position = _index(columns, name)
        column = columns[position]
        for row in rows:
            cell = row[position]
            if column.is_missing(cell):
                continue
            try:
                _typed_value(cast, cell)
            except ValueError as exc:
                raise _fail("cast_failed") from exc
        column.cast = cast
        column.value_type = cast


def _apply_unique_key(
    columns: list[_Column], rows: list[list[str]], step: RequireUniqueKeyStep
) -> None:
    positions = [_index(columns, name) for name in step.columns]
    seen: set[tuple[str | None, ...]] = set()
    for row in rows:
        key = tuple(None if columns[p].is_missing(row[p]) else row[p] for p in positions)
        if key in seen:
            raise _fail("duplicate_key")
        seen.add(key)


def _apply_sort(columns: list[_Column], rows: list[list[str]], step: SortRowsStep) -> None:
    positions = [_index(columns, name) for name in step.columns]

    def sort_key(row: list[str]) -> tuple[tuple[object, ...], ...]:
        parts: list[tuple[object, ...]] = []
        for position in positions:
            column = columns[position]
            cell = row[position]
            if column.is_missing(cell):
                parts.append((0,))
            else:
                parts.append((1, _typed_value(column.cast, cell)))
        return tuple(parts)

    rows.sort(key=sort_key)


def _source_file(
    output: CuratedOutputPlan,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> tuple[RawDatasetFile, bytes]:
    entry = raw_bundles.get(output.source_manifest_id)
    if entry is None:
        raise _fail("missing_source")
    manifest, files = entry
    declarations = [file for file in manifest.files if file.path == output.source_path]
    if len(declarations) != 1 or output.source_path not in files:
        raise _fail("missing_source")
    return declarations[0], files[output.source_path]


def _execute_output(
    output: CuratedOutputPlan,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> tuple[bytes, tuple[RawDatasetColumn, ...]]:
    declaration, source = _source_file(output, raw_bundles)
    decode = output.steps[0]
    if not isinstance(decode, DecodeTextStep):
        raise _fail("invalid_plan")
    try:
        text = source.decode(decode.encoding)
    except UnicodeDecodeError as exc:
        raise _fail("decode_failed") from exc

    try:
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise _fail("parse_failed") from exc
    if not parsed:
        raise _fail("header_mismatch")
    header, rows = parsed[0], parsed[1:]
    if header != [column.name for column in declaration.columns]:
        raise _fail("header_mismatch")
    if any(len(row) != len(header) for row in rows):
        raise _fail("row_width_mismatch")

    columns = [_Column(declared) for declared in declaration.columns]
    for step in output.steps[2:]:
        if isinstance(step, SelectColumnsStep):
            columns, rows = _apply_select(columns, rows, step)
        elif isinstance(step, RenameColumnsStep):
            _apply_rename(columns, step)
        elif isinstance(step, FilterRowsInStep):
            position = _index(columns, step.column)
            allowed = set(step.values)
            rows = [row for row in rows if row[position] in allowed]
        elif isinstance(step, CastColumnsStep):
            _apply_cast(columns, rows, step)
        elif isinstance(step, RequireUniqueKeyStep):
            _apply_unique_key(columns, rows, step)
        elif isinstance(step, SortRowsStep):
            _apply_sort(columns, rows, step)
        else:
            raise _fail("invalid_plan")

    for position, column in enumerate(columns):
        if column.tokens and "" not in column.tokens:
            for row in rows:
                if row[position] == "":
                    raise _fail("ambiguous_missing")

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([column.name for column in columns])
    for row in rows:
        writer.writerow(
            [
                "" if column.is_missing(cell) else cell
                for column, cell in zip(columns, row, strict=True)
            ]
        )
    declared = tuple(
        RawDatasetColumn.model_validate(
            {
                "name": column.name,
                "value_type": column.value_type,
                "unit": column.unit,
                "missing_tokens": [""] if column.tokens else [],
            }
        )
        for column in columns
    )
    return buffer.getvalue().encode("utf-8"), declared


def _execute(
    plan: TransformationPlan,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> dict[str, tuple[bytes, tuple[RawDatasetColumn, ...]]]:
    if type(plan) is not TransformationPlan:
        raise _fail("invalid_plan")
    try:
        revalidated = TransformationPlan.model_validate(plan.model_dump(mode="python"), strict=True)
    except Exception as exc:
        raise _fail("invalid_plan") from exc
    if not isinstance(raw_bundles, Mapping):
        raise _fail("invalid_input")
    try:
        for entry in raw_bundles.values():
            manifest, files = entry
            if type(manifest) is not RawDatasetManifest or not isinstance(files, Mapping):
                raise _fail("invalid_input")
        results: dict[str, tuple[bytes, tuple[RawDatasetColumn, ...]]] = {}
        for output in revalidated.outputs:
            results[output.output_path] = _execute_output(output, raw_bundles)
        return results
    except DatasetTransformationError:
        raise
    except Exception as exc:
        raise _fail("invalid_input") from exc


def execute_transformation_plan(
    plan: TransformationPlan,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> dict[str, bytes]:
    """Execute ``plan`` and return the canonical output bytes per output path."""
    return {path: content for path, (content, _) in _execute(plan, raw_bundles).items()}


def derive_transformation_output_columns(
    plan: TransformationPlan,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> dict[str, tuple[RawDatasetColumn, ...]]:
    """Execute ``plan`` and return the output column declarations per output path.

    Names are renamed as applicable, ``value_type`` is the cast type when a
    column was cast (otherwise the source declaration), ``unit`` is carried
    from the source, and ``missing_tokens`` is ``("",)`` when the source
    column declared any missing token (they render as empty cells), else
    empty.
    """
    return {path: columns for path, (_, columns) in _execute(plan, raw_bundles).items()}
