"""Frozen split rules and membership lock for a curated dataset (ADR-008)."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.dataset import DatasetId, DeclaredText, RelativePosixPath
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex


def parse_split_time(value: str, value_type: Literal["date", "iso_week"]) -> tuple[int, ...]:
    """Parse a strictly formatted date or valid ISO week for comparisons."""
    if value_type == "date":
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("invalid time")
        parsed = date.fromisoformat(value)
        return parsed.year, parsed.month, parsed.day
    match = re.fullmatch(r"([0-9]{4})-W([0-9]{2})", value)
    if match is None:
        raise ValueError("invalid time")
    year, week = int(match.group(1)), int(match.group(2))
    if not 1 <= week <= date(year, 12, 28).isocalendar().week:
        raise ValueError("invalid time")
    return year, week


class TimePartitionRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    column: DeclaredText
    value_type: Literal["date", "iso_week"]
    validation_from: str
    holdout_from: str

    @model_validator(mode="after")
    def _ordered(self) -> TimePartitionRule:
        if parse_split_time(self.validation_from, self.value_type) >= parse_split_time(
            self.holdout_from, self.value_type
        ):
            raise ValueError("time cut points must be ordered")
        return self


class GeographyPartitionRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    column: DeclaredText
    validation_values: tuple[DeclaredText, ...]
    holdout_values: tuple[DeclaredText, ...]

    @model_validator(mode="after")
    def _disjoint(self) -> GeographyPartitionRule:
        validation, holdout = set(self.validation_values), set(self.holdout_values)
        if (not validation and not holdout) or validation & holdout:
            raise ValueError("geography values must be nonempty and disjoint")
        if len(validation) != len(self.validation_values) or len(holdout) != len(
            self.holdout_values
        ):
            raise ValueError("geography values must be unique")
        return self


class FileSplitRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePosixPath
    time_rule: TimePartitionRule | None = None
    geography_rule: GeographyPartitionRule | None = None

    @model_validator(mode="after")
    def _valid_rule(self) -> FileSplitRule:
        if not self.path.endswith(".csv") or (
            self.time_rule is None and self.geography_rule is None
        ):
            raise ValueError("a CSV path and at least one rule are required")
        return self


class PartitionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    development: Annotated[int, Field(strict=True, ge=0)]
    validation: Annotated[int, Field(strict=True, ge=0)]
    holdout: Annotated[int, Field(strict=True, ge=0)]


class FileMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePosixPath
    counts: PartitionCounts
    membership_hash: Sha256Hex


class DatasetSplitManifest(VersionedContract):
    """A locked split; the note explains the rule and declares value-blind selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    split_id: DatasetId
    split_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    curated_manifest_id: DeclaredText
    curated_content_hash: Sha256Hex
    curated_bundle_hash: Sha256Hex
    rule_vocabulary_version: Literal["1.0.0"]
    file_rules: tuple[FileSplitRule, ...] = Field(min_length=1)
    memberships: tuple[FileMembership, ...] = Field(min_length=1)
    preregistration_note: DeclaredText
    locked_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _exact_metadata(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _shape(self) -> DatasetSplitManifest:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        if self.identifier != f"dataset-split-{self.split_id}-{self.split_version}":
            raise ValueError("identifier must match split identity")
        paths = [rule.path for rule in self.file_rules]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("rule paths must be sorted and unique")
        if paths != [item.path for item in self.memberships]:
            raise ValueError("memberships must match rule paths")
        return self
