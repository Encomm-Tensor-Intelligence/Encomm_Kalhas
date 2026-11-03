"""Frozen, preregistered benchmark protocol (ADR-009)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from kalhas.contracts.v1.dataset import DatasetId, DeclaredText, RelativePosixPath
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex


class BenchmarkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePosixPath
    series_column: DeclaredText
    time_column: DeclaredText
    value_column: DeclaredText
    horizons: tuple[Annotated[int, Field(strict=True, ge=1, le=366)], ...] = Field(min_length=1)
    history_window: Annotated[int, Field(strict=True, ge=1, le=3660)]
    min_history_points: Annotated[int, Field(strict=True, ge=1)]
    minimum_evaluable_tasks: Annotated[int, Field(strict=True, ge=1)]
    non_negative: StrictBool

    @model_validator(mode="after")
    def _shape(self) -> BenchmarkTarget:
        if not self.path.endswith(".csv"):
            raise ValueError("target path must end in .csv")
        if len({self.series_column, self.time_column, self.value_column}) != 3:
            raise ValueError("target columns must be distinct")
        if list(self.horizons) != sorted(set(self.horizons)):
            raise ValueError("horizons must be strictly increasing")
        if self.min_history_points > self.history_window:
            raise ValueError("minimum history must fit the window")
        return self


class BenchmarkComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_baseline_id: DatasetId
    reference_baseline_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    relative_wis_pass_below: Annotated[str, Field(pattern=r"^[0-9]+(\.[0-9]{1,6})?$")]

    @model_validator(mode="after")
    def _positive(self) -> BenchmarkComparison:
        if Decimal(self.relative_wis_pass_below) <= 0:
            raise ValueError("threshold must be positive")
        return self


class BenchmarkProtocol(VersionedContract):
    """A protocol lock; its note declares that selection was value-blind."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol_id: DatasetId
    protocol_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    split_manifest_id: DeclaredText
    split_content_hash: Sha256Hex
    curated_manifest_id: DeclaredText
    curated_content_hash: Sha256Hex
    curated_bundle_hash: Sha256Hex
    task_vocabulary_version: Literal["1.0.0"]
    targets: tuple[BenchmarkTarget, ...] = Field(min_length=1)
    quantile_levels: tuple[str, ...]
    scoring_rule: Literal["kalhas-wis-k3-v1"]
    comparison: BenchmarkComparison
    preregistration_note: DeclaredText
    locked_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_is_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _valid(self) -> BenchmarkProtocol:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        if self.identifier != f"benchmark-protocol-{self.protocol_id}-{self.protocol_version}":
            raise ValueError("identifier must match protocol identity")
        paths = [target.path for target in self.targets]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("target paths must be sorted and unique")
        if self.quantile_levels != ("0.025", "0.1", "0.25", "0.5", "0.75", "0.9", "0.975"):
            raise ValueError("quantile levels must match the scoring rule")
        return self
