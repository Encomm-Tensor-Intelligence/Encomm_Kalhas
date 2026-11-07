"""Versioned, declarative grid calibration records."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.benchmark_forecast import Count, ScoreDecimal, Semver
from kalhas.contracts.v1.dataset import DatasetId, DeclaredText, RelativePosixPath
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex


class CalibrationTargetVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_path: RelativePosixPath
    variant_id: DatasetId


class CalibrationCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePosixPath
    horizon: Annotated[int, Field(strict=True, ge=1, le=366)]
    relative_wis: ScoreDecimal | None
    included: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def _valid(self) -> CalibrationCell:
        if self.included and self.relative_wis is None:
            raise ValueError("included cell needs a relative score")
        return self


class CalibrationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_index: Annotated[int, Field(strict=True, ge=1)]
    member_id: DatasetId
    configuration_hash: Sha256Hex
    forecasts_sha256: Sha256Hex
    objective: ScoreDecimal | None
    objective_exact: str | None
    cells: tuple[CalibrationCell, ...] = Field(min_length=1)
    fallback_count: Count
    dispatched_step_count: Count
    rank: Annotated[int, Field(strict=True, ge=1)] | None
    status: Literal["retained", "qualifying_left_out", "not_retained", "no_objective"]

    @model_validator(mode="after")
    def _valid(self) -> CalibrationCandidate:
        keys = [(cell.path, cell.horizon) for cell in self.cells]
        if keys != sorted(set(keys)):
            raise ValueError("cells must be sorted and unique")
        included = any(cell.included for cell in self.cells)
        if included:
            if (
                self.objective is None
                or self.objective_exact is None
                or self.rank is None
                or self.status == "no_objective"
            ):
                raise ValueError("included cells require objective and rank")
            text = self.objective_exact
            if re.fullmatch(r"(?:0|[1-9][0-9]*)/[1-9][0-9]*", text) is None:
                raise ValueError("invalid exact objective")
            value = Fraction(text)
            if text != f"{value.numerator}/{value.denominator}":
                raise ValueError("exact objective must be reduced")
        elif (
            any(value is not None for value in (self.objective, self.objective_exact, self.rank))
            or self.status != "no_objective"
        ):
            raise ValueError("empty objective must have no rank")
        return self


class ModelPackCalibrationRecord(VersionedContract):
    """An immutable calibration identity and its candidate results."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    record_id: DatasetId
    record_version: Semver
    binding_manifest_id: DeclaredText
    binding_content_hash: Sha256Hex
    protocol_manifest_id: DeclaredText
    protocol_content_hash: Sha256Hex
    partition: Literal["development"]
    variants: tuple[CalibrationTargetVariant, ...] = Field(min_length=1)
    algorithm_id: Literal["kalhas-grid-fitter-v1"]
    algorithm_version: Literal["1.0.0"]
    objective: Literal["mean_relative_wis_over_cells"]
    retention_tolerance: Literal["21/20"]
    max_ensemble_members: Annotated[int, Field(strict=True, ge=1, le=64)]
    reference_forecast_set_id: DeclaredText
    reference_forecast_set_content_hash: Sha256Hex
    candidates: tuple[CalibrationCandidate, ...] = Field(min_length=1)
    qualifying_left_out_count: Count
    limitations: tuple[DeclaredText, ...] = Field(min_length=1)
    calibrated_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_is_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _valid(self) -> ModelPackCalibrationRecord:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        if (
            self.identifier
            != f"model-pack-calibration-record-{self.record_id}-{self.record_version}"
        ):
            raise ValueError("identifier must match record identity")
        paths = [variant.target_path for variant in self.variants]
        if paths != sorted(set(paths)):
            raise ValueError("variants must be sorted and unique")
        if [candidate.candidate_index for candidate in self.candidates] != list(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("candidate indices must be consecutive")
        members = [candidate.member_id for candidate in self.candidates]
        if len(members) != len(set(members)):
            raise ValueError("member identities must be unique")
        ranks = [candidate.rank for candidate in self.candidates if candidate.rank is not None]
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("ranks must be consecutive")
        if (
            sum(candidate.status == "retained" for candidate in self.candidates)
            > self.max_ensemble_members
        ):
            raise ValueError("too many retained candidates")
        if ranks and not any(
            candidate.rank == 1 and candidate.status == "retained" for candidate in self.candidates
        ):
            raise ValueError("best candidate must be retained")
        if self.qualifying_left_out_count != sum(
            candidate.status == "qualifying_left_out" for candidate in self.candidates
        ):
            raise ValueError("left out count mismatch")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("limitations must be unique")
        return self
