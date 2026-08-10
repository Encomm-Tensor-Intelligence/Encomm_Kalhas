"""Scenario contracts: scenario specification, context, clarification, validation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import (
    Assumption,
    AwareDatetime,
    JsonValue,
    MetricDefinition,
    VersionedContract,
)


class ObjectiveDirection(StrEnum):
    """Declared direction of an objective."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    REACH = "reach"


class Objective(BaseModel):
    """A declared objective with direction, optional target, and weight."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    description: str
    direction: ObjectiveDirection
    target: float | None = None
    weight: float = Field(default=1.0, ge=0.0)


class Constraint(BaseModel):
    """A declared constraint on the scenario or on candidate strategies."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    description: str
    hard: bool = True
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TimeHorizon(BaseModel):
    """A declared time horizon for a scenario."""

    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime
    resolution: str | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> TimeHorizon:
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")
        return self


class ScenarioSeed(VersionedContract):
    """Reproducible, serializable seed material.

    Contains only declared seed data - no random sampling, no executables.
    """

    algorithm: str = "deterministic"
    seed_value: str = Field(min_length=1)
    derived_from: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ScenarioSpec(VersionedContract):
    """A declarative scenario specification (domain-neutral).

    Scenario-level input does not own campaign seed assignment; seed
    ensemble ownership belongs to ``CampaignSpec``. A scenario describes
    intent only: its world is produced later by the deterministic world
    compiler, which emits an immutable ``WorldVersion`` carrying this
    scenario's identifier as ``source_scenario_id``.
    """

    name: str
    description: str = ""
    created_at: AwareDatetime
    objectives: list[Objective]
    constraints: list[Constraint] = Field(default_factory=list)
    time_horizon: TimeHorizon
    metrics: list[MetricDefinition] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ContextBundle(VersionedContract):
    """Declared organizational context carried into KALHAS contracts."""

    title: str = ""
    summary: str = ""
    statements: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ClarificationQuestion(VersionedContract):
    """A question asking for clarification of a scenario or context."""

    prompt: str
    options: list[str] = Field(default_factory=list)
    required: bool = True
    targets: list[str] = Field(default_factory=list)


class ValidationSeverity(StrEnum):
    """Severity of a validation issue."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """One issue found during validation."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    loc: tuple[str | int, ...] = ()


class ValidationReport(VersionedContract):
    """The result of validating a scenario or another subject."""

    subject_id: str
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    validated_at: AwareDatetime
