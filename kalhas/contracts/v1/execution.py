"""Execution contracts: run status and replay manifest."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RunState(StrEnum):
    """Lifecycle state of a single run."""

    PLANNED = "planned"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class RunStatus(VersionedContract):
    """Current lifecycle status of one run.

    ``event_hash`` is the SHA-256 (lowercase, 64 hex chars) of the canonical
    ordered event stream, recorded when the run reaches COMPLETE. COMPLETE in
    this phase means structural execution finished - it does not mean
    decision evidence was produced.
    """

    run_id: str
    campaign_id: str
    run_plan_id: str
    state: RunState
    runtime_version: str
    input_hash: str = Field(pattern=_SHA256_PATTERN)
    event_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    created_at: AwareDatetime
    changed_at: AwareDatetime


class ReplayManifest(VersionedContract):
    """Provenance manifest of an exact replay of a completed run.

    Replay regenerates the deterministic event stream from recorded inputs
    only; the recomputed hash must equal the stored expected event hash.
    """

    run_id: str
    campaign_id: str
    world_version_id: str
    strategy_candidate_id: str
    scenario_seed_id: str
    runtime_version: str
    input_hash: str = Field(pattern=_SHA256_PATTERN)
    expected_event_hash: str = Field(pattern=_SHA256_PATTERN)
    replay_classification: Literal["exact"] = "exact"
    created_at: AwareDatetime
