"""Shared building blocks for the v1 contract surface.

These submodels are domain-neutral: they carry declared intent, declared
uncertainty, and safe JSON-like data. There are no executable expressions,
callbacks, imports, or plugin references anywhere in the contracts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_timezone_aware)]


class VersionedContract(BaseModel):
    """Base for every top-level public contract.

    Provides the stable identifier, the tenant identifier, and the semantic
    schema version. All public contracts are strict: unknown fields are
    rejected.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: str
    tenant_id: str
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")


class Assumption(BaseModel):
    """A declared assumption about the world or a strategy."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RiskStatement(BaseModel):
    """A declared risk with likelihood and impact; never a single score."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    description: str
    likelihood: float = Field(ge=0.0, le=1.0)
    impact: float = Field(ge=0.0, le=1.0)
    mitigations: list[str] = Field(default_factory=list)


class MetricDefinition(BaseModel):
    """Declared definition of a measurable outcome metric."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    name: str
    description: str = ""
    unit: str | None = None
    aggregation: str | None = None


class DistributionKind(StrEnum):
    """Declared distribution family. Describes uncertainty; never samples."""

    UNIFORM = "uniform"
    NORMAL = "normal"
    LOGNORMAL = "lognormal"
    TRIANGULAR = "triangular"
    DISCRETE = "discrete"
    UNSPECIFIED = "unspecified"


class DistributionSummary(BaseModel):
    """Declared summary of an outcome distribution (no sampling, no code)."""

    model_config = ConfigDict(extra="forbid")

    kind: DistributionKind = DistributionKind.UNSPECIFIED
    parameters: dict[str, float] = Field(default_factory=dict)
    mean: float | None = None
    median: float | None = None
    lower_quantile: float | None = None
    upper_quantile: float | None = None
    samples: list[float] = Field(default_factory=list)


class UncertaintyStatement(BaseModel):
    """A declared uncertainty about a target, with distribution metadata."""

    model_config = ConfigDict(extra="forbid")

    target: str
    description: str = ""
    distribution: DistributionKind = DistributionKind.UNSPECIFIED
    parameters: dict[str, float] = Field(default_factory=dict)
