"""Frozen forecast and benchmark score artifacts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.dataset import DatasetId, DeclaredText, RelativePosixPath
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex

ScoreDecimal = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]{6}$")]
CoverageDecimal = Annotated[str, Field(pattern=r"^(0\.[0-9]{6}|1\.000000)$")]
Semver = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
Count = Annotated[int, Field(strict=True, ge=0)]
Verdict = Literal["pass", "fail", "inconclusive"]
VerdictReason = Literal[
    "below_threshold", "not_below_threshold", "insufficient_evaluable_tasks", "reference_score_zero"
]
MAX_FORECAST_FILE_BYTES = 26_214_400


class ForecastProducer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["baseline", "model_pack_mechanism"]
    producer_id: DatasetId
    producer_version: Semver
    configuration_hash: Sha256Hex


class ForecastFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: Literal["forecasts.csv"]
    sha256: Sha256Hex
    byte_size: Annotated[int, Field(strict=True, ge=1, le=MAX_FORECAST_FILE_BYTES)]
    row_count: Count


class ForecastSet(VersionedContract):
    """A protocol-bound forecast file and its immutable producer identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    forecast_set_id: DatasetId
    forecast_set_version: Semver
    protocol_manifest_id: DeclaredText
    protocol_content_hash: Sha256Hex
    partition: Literal["development", "validation", "holdout"]
    producer: ForecastProducer
    forecasts_file: ForecastFile
    created_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_is_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _valid(self) -> ForecastSet:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        if self.identifier != f"forecast-set-{self.forecast_set_id}-{self.forecast_set_version}":
            raise ValueError("identifier must match forecast set identity")
        return self


class ScoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mean_wis: ScoreDecimal
    mean_absolute_error: ScoreDecimal
    coverage_50: CoverageDecimal
    coverage_95: CoverageDecimal


class ScoreCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: RelativePosixPath
    horizon: Annotated[int, Field(strict=True, ge=1, le=366)]
    evaluable_tasks: Count
    inadmissible_origin_tasks: Count
    insufficient_history_tasks: Count
    candidate: ScoreSummary | None
    reference: ScoreSummary | None
    relative_wis: ScoreDecimal | None
    verdict: Verdict
    verdict_reason: VerdictReason

    @model_validator(mode="after")
    def _valid(self) -> ScoreCell:
        if self.evaluable_tasks == 0:
            if (
                self.candidate is not None
                or self.reference is not None
                or self.relative_wis is not None
                or self.verdict_reason != "insufficient_evaluable_tasks"
            ):
                raise ValueError("empty cell must be inconclusive")
        elif self.candidate is None or self.reference is None:
            raise ValueError("nonempty cell requires summaries")
        if self.verdict == "pass" and (
            self.verdict_reason != "below_threshold" or self.relative_wis is None
        ):
            raise ValueError("invalid pass")
        if self.verdict == "fail" and (
            self.verdict_reason != "not_below_threshold" or self.relative_wis is None
        ):
            raise ValueError("invalid fail")
        if self.verdict == "inconclusive" and self.verdict_reason not in (
            "insufficient_evaluable_tasks",
            "reference_score_zero",
        ):
            raise ValueError("invalid inconclusive reason")
        if self.verdict_reason == "reference_score_zero" and self.relative_wis is not None:
            raise ValueError("zero reference has no relative score")
        return self


class BenchmarkScoreReport(VersionedContract):
    """An immutable score report with declared limitations."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    report_id: DatasetId
    report_version: Semver
    protocol_manifest_id: DeclaredText
    protocol_content_hash: Sha256Hex
    partition: Literal["development", "validation", "holdout"]
    candidate_forecast_set_id: DeclaredText
    candidate_forecast_set_content_hash: Sha256Hex
    reference_forecast_set_id: DeclaredText
    reference_forecast_set_content_hash: Sha256Hex
    scoring_rule: Literal["kalhas-wis-k3-v1"]
    cells: tuple[ScoreCell, ...] = Field(min_length=1)
    limitations: tuple[DeclaredText, ...] = Field(min_length=1)
    scored_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_is_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _valid(self) -> BenchmarkScoreReport:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        if self.identifier != f"benchmark-score-report-{self.report_id}-{self.report_version}":
            raise ValueError("identifier must match report identity")
        keys = [(cell.path, cell.horizon) for cell in self.cells]
        if keys != sorted(set(keys)):
            raise ValueError("cells must be sorted and unique")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("limitations must be unique")
        return self
