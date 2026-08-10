"""Run plan contract: a deterministic planning manifest for one run."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract


class RunPlan(VersionedContract):
    """A planning manifest for exactly one run of one strategy on one seed.

    Planning manifest only: no executable code, callbacks, provider
    configuration, arbitrary imports, or simulated outcomes. The input hash
    is a deterministic SHA-256 hex digest (lowercase, 64 chars) over the
    world content hash, the strategy contract, the seed contract, and the
    runtime version.
    """

    campaign_id: str
    world_version_id: str
    strategy_candidate_id: str
    scenario_seed_id: str
    runtime_version: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    planned_state: Literal["planned"] = "planned"
    created_at: AwareDatetime
