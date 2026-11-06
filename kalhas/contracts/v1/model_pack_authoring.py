"""Frozen authoring inputs and the closed observation vocabulary."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.benchmark_forecast import Semver
from kalhas.contracts.v1.dataset import DatasetId, DeclaredText, RelativePosixPath
from kalhas.contracts.v1.domain_mechanism import _reject_non_json_tree
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import Sha256Hex

QuantityName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class StockSumOperator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["stock_sum"]
    stocks: tuple[QuantityName, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sorted_stocks(self) -> StockSumOperator:
        if tuple(sorted(set(self.stocks))) != self.stocks:
            raise ValueError("stocks must be sorted and unique")
        return self


class FlowSumOperator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["flow_sum"]
    flow: QuantityName


InnerOperator = Annotated[StockSumOperator | FlowSumOperator, Field(discriminator="op")]


class PerHundredKOperator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["per_100k"]
    inner: InnerOperator


ObservationOperator = Annotated[
    StockSumOperator | FlowSumOperator | PerHundredKOperator, Field(discriminator="op")
]


class TargetObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_path: RelativePosixPath
    variant_id: DatasetId
    operator: ObservationOperator


class DenominatorEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    series: DeclaredText
    year: Annotated[int, Field(strict=True, ge=1, le=9999)]
    value: Annotated[int, Field(strict=True, ge=1)]


def _has_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_float(item) for item in value)
    return False


class ModelPackAuthoringBinding(VersionedContract):
    """An immutable binding of declared observations to a locked protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: DatasetId
    binding_version: Semver
    pack_id: DeclaredText
    pack_version: Semver
    protocol_manifest_id: DeclaredText
    protocol_content_hash: Sha256Hex
    operator_vocabulary_version: Literal["1.0.0"]
    observations: tuple[TargetObservation, ...] = Field(min_length=1)
    denominators: tuple[DenominatorEntry, ...]
    payload: dict[str, JsonValue]
    assumptions: tuple[DeclaredText, ...] = Field(min_length=1)
    declared_at: AwareDatetime
    content_hash: Sha256Hex
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _exact_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("payload", data)
            _reject_non_json_tree("metadata", data)
            if _has_float(data.get("payload")):
                raise ValueError("payload numbers must be exact")
        return data

    @model_validator(mode="after")
    def _valid(self) -> ModelPackAuthoringBinding:
        if (
            self.identifier
            != f"model-pack-authoring-binding-{self.binding_id}-{self.binding_version}"
        ):
            raise ValueError("identifier must match binding identity")
        observations = [(item.target_path, item.variant_id) for item in self.observations]
        if observations != sorted(set(observations)):
            raise ValueError("observations must be sorted and unique")
        denominators = [(item.series, item.year) for item in self.denominators]
        if denominators != sorted(set(denominators)):
            raise ValueError("denominators must be sorted and unique")
        if set(self.payload) != {"initial_state_rule", "action_schedule", "candidate_grid"} or any(
            type(value) is not dict for value in self.payload.values()
        ):
            raise ValueError("payload requires exactly three objects")
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must be finite JSON")
        return self
