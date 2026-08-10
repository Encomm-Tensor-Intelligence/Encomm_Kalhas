"""World model contracts: immutable world versions, manifests, uncertainty."""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import (
    AwareDatetime,
    DistributionKind,
    JsonValue,
    VersionedContract,
)


class WorldVersion(VersionedContract):
    """An immutable world-model version.

    Frozen by contract: attribute assignment raises after validation.
    Supports a parent version id so world models evolve as a version chain.
    Carries provenance: the source scenario, the compiler version, and the
    content hash that make compilation reproducible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_version_id: str | None = None
    source_scenario_id: str
    compiler_version: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    world: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _parent_must_differ(self) -> WorldVersion:
        if self.parent_version_id == self.identifier:
            raise ValueError("parent_version_id must differ from identifier")
        return self


class WorldManifest(VersionedContract):
    """A declarative inventory of a world model version.

    ``entity_count`` counts compiled entities. The Phase 2 generic compiler
    compiles declarative scenario elements only - not entities - so
    ``entity_count`` is 0 for its worlds; the declarative objective,
    constraint, metric, and assumption counts are preserved separately in
    ``state``.
    """

    world_version_id: str
    entity_count: int = Field(ge=0)
    state: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class UncertaintyDefinition(VersionedContract):
    """A declared uncertainty about a target; distribution metadata only."""

    target: str
    distribution: DistributionKind = DistributionKind.UNSPECIFIED
    parameters: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
