"""Raw-dataset manifest contract (Phase 30, H30-S01).

ADR-006 (D30-01) freezes the offline, immutable, local-bundle intake model.
This module adds exactly one top-level public v1 contract plus its
synchronized JSON Schema:

- ``RawDatasetManifest`` - the immutable declarative identity of one exact
  raw dataset bundle: stable dataset identity and vintage, the recorded
  source, an admissible license (exactly ``public_domain`` or
  ``attribution_commercial``), the aggregate-only data-subject level, an
  ordered unique list of relative files with byte size, SHA-256, declared
  media type and declared columns, a bundle hash, the declared time and
  geography bases, the publisher's revision policy, and a self-covering
  content hash.

The nested helper records (source, license, column, file, time basis,
geography basis) are frozen, strict, and extra-forbid; they are NOT
registered in ``PUBLIC_CONTRACTS`` and receive no standalone schema files.

The contract checks shape only. It never reads a file, never dereferences a
locator, and never recomputes a hash: the bundle hash and the content hash
are caller-declared identity fields that the pure verifier in
``kalhas.application.raw_dataset_verifier`` recomputes against the bytes, in
the same way the Phase 29 profiles declare hashes. Everything declared here
is data, never executable configuration, and nothing is inferred.
"""

from __future__ import annotations

import re
from datetime import UTC
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex

#: Largest admissible total raw-bundle size (25 MiB, D30-01a).
MAX_RAW_DATASET_TOTAL_BYTES = 26_214_400

_DATASET_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_VINTAGE_PATTERN = r"^\d{4}-\d{2}-\d{2}(\.[1-9]\d*)?$"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def _require_visible_text(value: str) -> str:
    """Reject empty or whitespace-only declared text."""
    if not value.strip():
        raise ValueError("declared text must not be empty or whitespace-only")
    return value


def _require_relative_posix_path(value: str) -> str:
    """Accept only a plain relative POSIX path made of ordinary segments.

    Pure string rules: no leading ``/``, no backslash, no control
    character, and no empty, ``.`` or ``..`` segment. Nothing is resolved
    against a filesystem.
    """
    if not value:
        raise ValueError("path must not be empty")
    if value.startswith("/"):
        raise ValueError("path must be relative")
    if "\\" in value:
        raise ValueError("path must use POSIX separators only")
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("path must not contain control characters")
    for segment in value.split("/"):
        if segment in ("", ".", ".."):
            raise ValueError("path must not contain empty, '.' or '..' segments")
    return value


#: Non-empty declared text that is not merely whitespace.
DeclaredText = Annotated[str, Field(min_length=1), AfterValidator(_require_visible_text)]

#: A relative POSIX path (string rules only).
RelativePosixPath = Annotated[str, AfterValidator(_require_relative_posix_path)]

#: Lowercase stable dataset slug.
DatasetId = Annotated[str, Field(pattern=_DATASET_ID_PATTERN)]

#: UTC import date ``YYYY-MM-DD`` with an optional ``.N`` same-day suffix.
DatasetVintage = Annotated[str, Field(pattern=_VINTAGE_PATTERN)]

#: Exactly the two admissible license classes (D30-01b). Non-commercial,
#: restricted, permission-required and unknown terms cannot be spelled.
LicenseClass = Literal["public_domain", "attribution_commercial"]

#: Declared text media types of raw files (CSV, JSON and XML text only).
RawMediaType = Literal["text/csv", "application/json", "application/xml"]

#: Declared value types of one column.
ColumnValueType = Literal["string", "integer", "decimal", "date", "iso_week", "boolean"]

#: Aggregate data only; person-level records are not representable.
DataSubjectLevel = Literal["aggregate"]

TimeCalendar = Literal["iso_date", "iso_week", "year", "year_month"]
TimeGranularity = Literal["day", "week", "month", "year"]
TimeSemantics = Literal["observation_date", "reporting_date", "reference_period"]

#: The publisher's declared revision policy. ``unknown`` is allowed and is a
#: retained limitation that must be explained.
RevisionPolicy = Literal["closed_series", "revised_in_place", "versioned_releases", "unknown"]


class RawDatasetSource(BaseModel):
    """Recorded source of one raw dataset (declarative only).

    ``source_locator`` is opaque text that is recorded and never
    dereferenced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    publisher: DeclaredText
    title: DeclaredText
    source_locator: DeclaredText
    publisher_release_id: DeclaredText | None = None


class RawDatasetLicense(BaseModel):
    """Declared license terms of one raw dataset (declarative only).

    Exactly two license classes are representable. ``terms_locator`` is
    opaque text that is recorded and never dereferenced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    license_class: LicenseClass
    license_id: DeclaredText
    terms_locator: DeclaredText
    terms_read_at: AwareDatetime
    attribution_statement: DeclaredText | None = None
    modifications_must_be_disclosed: StrictBool
    scope_restrictions: tuple[DeclaredText, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _terms_are_consistent(self) -> RawDatasetLicense:
        if self.license_class == "attribution_commercial" and self.attribution_statement is None:
            raise ValueError("attribution_commercial requires an attribution statement")
        if len(set(self.scope_restrictions)) != len(self.scope_restrictions):
            raise ValueError("scope restrictions must be unique")
        return self


class RawDatasetColumn(BaseModel):
    """One declared column of one raw file (declared, never inferred)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: DeclaredText
    value_type: ColumnValueType
    unit: DeclaredText
    missing_tokens: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _missing_tokens_are_unique(self) -> RawDatasetColumn:
        if len(set(self.missing_tokens)) != len(self.missing_tokens):
            raise ValueError("missing tokens must be unique")
        return self


class RawDatasetFile(BaseModel):
    """One declared raw file: relative path, size, SHA-256, type, columns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RelativePosixPath
    byte_size: StrictInt = Field(gt=0)
    sha256: Sha256Hex
    media_type: RawMediaType
    columns: tuple[RawDatasetColumn, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _column_names_are_unique(self) -> RawDatasetFile:
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("column names must be unique within a file")
        return self


class RawDatasetTimeBasis(BaseModel):
    """Declared time basis of a bundle (declared, never inferred)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calendar: TimeCalendar
    granularity: TimeGranularity
    time_columns: tuple[DeclaredText, ...] = Field(min_length=1)
    time_semantics: TimeSemantics

    @model_validator(mode="after")
    def _time_columns_are_unique(self) -> RawDatasetTimeBasis:
        if len(set(self.time_columns)) != len(self.time_columns):
            raise ValueError("time columns must be unique")
        return self


class RawDatasetGeographyBasis(BaseModel):
    """Declared geography basis of a bundle (declared, never inferred)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: DeclaredText
    geography_columns: tuple[DeclaredText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _geography_columns_are_unique(self) -> RawDatasetGeographyBasis:
        if len(set(self.geography_columns)) != len(self.geography_columns):
            raise ValueError("geography columns must be unique")
        return self


class RawDatasetManifest(VersionedContract):
    """Immutable declarative identity of one exact raw dataset bundle.

    ``identifier`` must equal ``raw-dataset-<dataset_id>-<vintage>`` and the
    UTC calendar date of ``retrieved_at`` must equal the vintage date. The
    file list is non-empty, unique and sorted ascending by path, and the
    declared byte sizes sum to at most 25 MiB. Time and geography columns
    must name columns declared by some file. The contract checks shape
    only: ``bundle_hash`` and ``content_hash`` are declared identity fields
    that the pure verifier recomputes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: DatasetId
    vintage: DatasetVintage
    retrieved_at: AwareDatetime
    source: RawDatasetSource
    license: RawDatasetLicense
    data_subject_level: DataSubjectLevel
    files: tuple[RawDatasetFile, ...] = Field(min_length=1)
    bundle_hash: Sha256Hex
    time_basis: RawDatasetTimeBasis
    geography_basis: RawDatasetGeographyBasis
    revision_policy: RevisionPolicy
    revision_notes: str
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
    def _metadata_contains_no_non_finite(self) -> RawDatasetManifest:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _identity_is_exact(self) -> RawDatasetManifest:
        if self.identifier != f"raw-dataset-{self.dataset_id}-{self.vintage}":
            raise ValueError("identifier must equal raw-dataset-<dataset_id>-<vintage>")
        vintage_date = self.vintage.split(".", 1)[0]
        if self.retrieved_at.astimezone(UTC).date().isoformat() != vintage_date:
            raise ValueError("the UTC date of retrieved_at must equal the vintage date")
        if self.license.terms_read_at > self.retrieved_at:
            raise ValueError("terms_read_at must not be after retrieved_at")
        return self

    @model_validator(mode="after")
    def _files_are_sorted_unique_and_bounded(self) -> RawDatasetManifest:
        paths = [file.path for file in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("file paths must be unique")
        if paths != sorted(paths):
            raise ValueError("files must be sorted ascending by path")
        if sum(file.byte_size for file in self.files) > MAX_RAW_DATASET_TOTAL_BYTES:
            raise ValueError("total declared size must not exceed 25 MiB")
        return self

    @model_validator(mode="after")
    def _declared_columns_cover_the_bases(self) -> RawDatasetManifest:
        declared = {column.name for file in self.files for column in file.columns}
        for name in self.time_basis.time_columns:
            if name not in declared:
                raise ValueError("every time column must be a declared column")
        for name in self.geography_basis.geography_columns:
            if name not in declared:
                raise ValueError("every geography column must be a declared column")
        return self

    @model_validator(mode="after")
    def _unknown_revision_policy_is_explained(self) -> RawDatasetManifest:
        if self.revision_policy == "unknown" and not self.revision_notes.strip():
            raise ValueError("an unknown revision policy requires non-empty revision notes")
        return self
