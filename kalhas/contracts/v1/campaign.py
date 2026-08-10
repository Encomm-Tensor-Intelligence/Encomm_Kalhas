"""Campaign contracts: specification, status, and the lifecycle state enum."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract


class CampaignState(StrEnum):
    """The campaign lifecycle states.

    The allowed transitions live in
    ``kalhas/application/campaign_lifecycle.py``.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    COMPILED = "compiled"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignSpec(VersionedContract):
    """A campaign comparing strategy candidates on one scenario and world.

    Fair comparison is a structural invariant, not a caller choice: every
    strategy candidate receives the exact same ordered seed identifiers (the
    shared ``seed_ensemble``) and equivalent observation permissions. Seed
    ensemble ownership belongs to the campaign, never to scenario-level
    input, and the seed ensemble is the sole source of run multiplicity.
    Campaigns run against an already compiled immutable world
    (``world_version_id``). Every seed must belong to the campaign tenant.
    """

    name: str
    scenario_id: str
    world_version_id: str
    strategy_candidate_ids: list[str] = Field(min_length=1)
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    seed_ensemble: tuple[ScenarioSeed, ...] = Field(min_length=1)
    created_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_strategy_candidate_ids(self) -> CampaignSpec:
        if len(self.strategy_candidate_ids) != len(set(self.strategy_candidate_ids)):
            raise ValueError("strategy_candidate_ids must be unique")
        return self

    @model_validator(mode="after")
    def _unique_seed_ensemble_identifiers(self) -> CampaignSpec:
        seed_ids = [seed.identifier for seed in self.seed_ensemble]
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("seed_ensemble identifiers must be unique")
        return self

    @model_validator(mode="after")
    def _seed_ensemble_matches_tenant(self) -> CampaignSpec:
        for seed in self.seed_ensemble:
            if seed.tenant_id != self.tenant_id:
                raise ValueError(
                    f"seed {seed.identifier!r} tenant_id does not match campaign tenant_id"
                )
        return self


class CampaignStatus(VersionedContract):
    """A snapshot of a campaign's lifecycle state."""

    campaign_id: str
    state: CampaignState
    changed_at: AwareDatetime
    message: str | None = None
