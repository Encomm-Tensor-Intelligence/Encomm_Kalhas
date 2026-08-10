"""Strategy boundary contracts: requests to LEGION and declared candidates."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from kalhas.contracts.v1.shared import (
    Assumption,
    AwareDatetime,
    JsonValue,
    VersionedContract,
)


class PolicyRule(BaseModel):
    """One declarative rule of a policy. Human-readable; never executable."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    statement: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class PolicyDeclaration(BaseModel):
    """A declared policy: summary plus declarative rules and parameters."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    rules: list[PolicyRule] = Field(default_factory=list)


class ObservationRequirement(BaseModel):
    """A required observation of a metric."""

    model_config = ConfigDict(extra="forbid")

    metric_id: str
    description: str
    required: bool = True


class StrategyRequest(VersionedContract):
    """A request for strategy generation, addressed through the LegionAdapter."""

    scenario_id: str
    context_bundle_id: str | None = None
    constraint_ids: list[str] = Field(default_factory=list)
    required_observations: list[ObservationRequirement] = Field(default_factory=list)
    requested_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class StrategyCandidate(VersionedContract):
    """A declared strategy candidate: policy, required observations, assumptions.

    Represents a strategy without running it - no execution, no simulation.
    """

    strategy_version: str
    policy: PolicyDeclaration
    required_observations: list[ObservationRequirement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
