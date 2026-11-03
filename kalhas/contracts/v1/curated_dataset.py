"""Curated-dataset manifest and closed transformation-plan contracts (H30-S02A).

ADR-007 implements ADR-006 D30-01e. This module adds exactly one top-level
public v1 contract plus its synchronized JSON Schema:

- ``CuratedDatasetManifest`` - the immutable declarative identity of one
  curated dataset bundle: stable identity and version, the exact raw
  references it was derived from (manifest identifier, content hash and
  bundle hash), the full embedded ``TransformationPlan``, the inherited
  license, a non-empty modification notice, the declared output files with
  size, SHA-256 and columns, an output bundle hash, the declared time and
  geography bases, and a self-covering content hash.

The transformation plan is declarative data interpreted by one generic,
pure engine (``kalhas.application.dataset_transformation_engine``). It uses
a closed vocabulary of eight operations and contains no code, expression,
regular expression, callback, import, path outside its bundle, or network
locator. The nested records (plan, output plan, steps, raw reference) are
frozen, strict, and extra-forbid; they are NOT registered in
``PUBLIC_CONTRACTS`` and receive no standalone schema files.

The contract checks shape only. The hashes are caller-declared identity
fields that the pure verifier in
``kalhas.application.curated_dataset_verifier`` recomputes by re-executing
the plan against the raw bytes.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.dataset import (
    MAX_RAW_DATASET_TOTAL_BYTES,
    DatasetId,
    DeclaredText,
    RawDatasetFile,
    RawDatasetGeographyBasis,
    RawDatasetLicense,
    RawDatasetTimeBasis,
    RelativePosixPath,
)
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex

#: The frozen transformation vocabulary version (ADR-007, D30-01e-1).
TRANSFORMATION_VOCABULARY_VERSION = "1.0.0"

#: The exact closed set of plan operations, in declaration order.
TRANSFORMATION_OPERATIONS = (
    "decode_text",
    "parse_csv",
    "select_columns",
    "rename_columns",
    "filter_rows_in",
    "cast_columns",
    "require_unique_key",
    "sort_rows",
)

#: Target types of ``cast_columns``; values are validated and kept verbatim.
CastType = Literal["string", "integer", "decimal", "date", "iso_week"]

_CURATION_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")


class DecodeTextStep(BaseModel):
    """Decode the source bytes as text (mandatory first step)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["decode_text"]
    encoding: Literal["utf-8", "utf-8-sig"]


class ParseCsvStep(BaseModel):
    """Parse CSV: comma delimiter, double-quote quoting, first row is the header."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["parse_csv"]


class SelectColumnsStep(BaseModel):
    """Keep exactly these existing columns, in this order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["select_columns"]
    columns: tuple[DeclaredText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _columns_are_unique(self) -> SelectColumnsStep:
        _require_unique(self.columns, "selected columns")
        return self


class RenameColumnsStep(BaseModel):
    """Rename existing columns to new, unique names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["rename_columns"]
    mapping: dict[DeclaredText, DeclaredText] = Field(min_length=1)

    @model_validator(mode="after")
    def _new_names_are_unique(self) -> RenameColumnsStep:
        _require_unique(tuple(self.mapping.values()), "new column names")
        return self


class FilterRowsInStep(BaseModel):
    """Keep rows whose raw ``column`` text is in a declared value list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["filter_rows_in"]
    column: DeclaredText
    values: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _values_are_unique(self) -> FilterRowsInStep:
        _require_unique(self.values, "filter values")
        return self


class CastColumnsStep(BaseModel):
    """Validate columns against a target type; the text is kept verbatim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["cast_columns"]
    types: dict[DeclaredText, CastType] = Field(min_length=1)


class RequireUniqueKeyStep(BaseModel):
    """Fail the plan unless these columns are unique across rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["require_unique_key"]
    columns: tuple[DeclaredText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _columns_are_unique(self) -> RequireUniqueKeyStep:
        _require_unique(self.columns, "key columns")
        return self


class SortRowsStep(BaseModel):
    """Stable ascending sort by these columns using typed comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["sort_rows"]
    columns: tuple[DeclaredText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _columns_are_unique(self) -> SortRowsStep:
        _require_unique(self.columns, "sort columns")
        return self


#: One plan step, discriminated on ``op``. An unknown ``op`` is rejected.
PlanStep = Annotated[
    DecodeTextStep
    | ParseCsvStep
    | SelectColumnsStep
    | RenameColumnsStep
    | FilterRowsInStep
    | CastColumnsStep
    | RequireUniqueKeyStep
    | SortRowsStep,
    Field(discriminator="op"),
]


class CuratedOutputPlan(BaseModel):
    """The ordered steps that produce one output file from one raw file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_path: RelativePosixPath
    source_manifest_id: DeclaredText
    source_path: RelativePosixPath
    steps: tuple[PlanStep, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _shape_is_closed(self) -> CuratedOutputPlan:
        if not self.output_path.endswith(".csv"):
            raise ValueError("output_path must end in .csv")
        if not isinstance(self.steps[0], DecodeTextStep):
            raise ValueError("the first step must be decode_text")
        if not isinstance(self.steps[1], ParseCsvStep):
            raise ValueError("the second step must be parse_csv")
        if any(isinstance(step, DecodeTextStep | ParseCsvStep) for step in self.steps[2:]):
            raise ValueError("decode_text and parse_csv must not repeat")
        return self


class TransformationPlan(BaseModel):
    """A closed, declarative plan with one or more named outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vocabulary_version: Literal["1.0.0"]
    outputs: tuple[CuratedOutputPlan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _outputs_are_sorted_and_unique(self) -> TransformationPlan:
        paths = [output.output_path for output in self.outputs]
        if len(set(paths)) != len(paths):
            raise ValueError("output paths must be unique")
        if paths != sorted(paths):
            raise ValueError("outputs must be sorted ascending by output_path")
        return self


class RawDatasetReference(BaseModel):
    """An exact reference to one raw dataset manifest and its bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_manifest_id: DeclaredText
    raw_content_hash: Sha256Hex
    raw_bundle_hash: Sha256Hex


class CuratedDatasetManifest(VersionedContract):
    """Immutable declarative identity of one curated dataset bundle.

    ``identifier`` must equal ``curated-dataset-<curated_dataset_id>-
    <curation_version>``. Inputs are unique and sorted by raw manifest
    identifier, and every plan output must name one of them. The declared
    files must be ``text/csv`` and their paths must equal the plan output
    paths exactly, in the same order, within 25 MiB in total. Time and
    geography columns must name declared output columns. The contract
    checks shape only: the hashes are recomputed by the pure verifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    curated_dataset_id: DatasetId
    curation_version: Annotated[str, Field(pattern=_CURATION_VERSION_PATTERN)]
    inputs: tuple[RawDatasetReference, ...] = Field(min_length=1)
    plan: TransformationPlan
    license: RawDatasetLicense
    modification_notice: DeclaredText
    files: tuple[RawDatasetFile, ...] = Field(min_length=1)
    bundle_hash: Sha256Hex
    time_basis: RawDatasetTimeBasis
    geography_basis: RawDatasetGeographyBasis
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_metadata_is_exact_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> CuratedDatasetManifest:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _identity_is_exact(self) -> CuratedDatasetManifest:
        expected = f"curated-dataset-{self.curated_dataset_id}-{self.curation_version}"
        if self.identifier != expected:
            raise ValueError("identifier must equal curated-dataset-<id>-<curation_version>")
        if not re.fullmatch(_CURATION_VERSION_PATTERN, self.curation_version):
            raise ValueError("curation_version must be MAJOR.MINOR.PATCH")
        return self

    @model_validator(mode="after")
    def _inputs_are_sorted_unique_and_cover_the_plan(self) -> CuratedDatasetManifest:
        ids = [reference.raw_manifest_id for reference in self.inputs]
        if len(set(ids)) != len(ids):
            raise ValueError("input raw manifest ids must be unique")
        if ids != sorted(ids):
            raise ValueError("inputs must be sorted ascending by raw_manifest_id")
        for output in self.plan.outputs:
            if output.source_manifest_id not in ids:
                raise ValueError("every plan output must name a declared input")
        return self

    @model_validator(mode="after")
    def _files_match_the_plan_and_are_bounded(self) -> CuratedDatasetManifest:
        if any(file.media_type != "text/csv" for file in self.files):
            raise ValueError("curated files must be text/csv")
        if [file.path for file in self.files] != [o.output_path for o in self.plan.outputs]:
            raise ValueError("file paths must equal the plan output paths exactly, in order")
        if sum(file.byte_size for file in self.files) > MAX_RAW_DATASET_TOTAL_BYTES:
            raise ValueError("total declared size must not exceed 25 MiB")
        return self

    @model_validator(mode="after")
    def _bases_name_declared_output_columns(self) -> CuratedDatasetManifest:
        declared = {column.name for file in self.files for column in file.columns}
        for name in self.time_basis.time_columns:
            if name not in declared:
                raise ValueError("every time column must be a declared output column")
        for name in self.geography_basis.geography_columns:
            if name not in declared:
                raise ValueError("every geography column must be a declared output column")
        return self
