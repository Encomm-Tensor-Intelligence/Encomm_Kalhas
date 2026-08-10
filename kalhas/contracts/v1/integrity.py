"""Run input integrity contract: deterministic verification attestation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RunInputIntegrityManifest(VersionedContract):
    """Attestation that a run's recorded inputs verified exactly.

    The manifest attests **deterministic input verification**, not a
    real-time audit event: ``recorded_at`` is the recorded RunPlan creation
    time (derived from recorded inputs), never the wall clock. Both hashes
    are the deterministic SHA-256 input digests (lowercase, 64 hex chars);
    ``verification_classification`` is always ``"exact"``.
    """

    run_id: str
    campaign_id: str
    run_plan_id: str
    world_version_id: str
    strategy_candidate_id: str
    scenario_seed_id: str
    runtime_version: str
    expected_input_hash: str = Field(pattern=_SHA256_PATTERN)
    recomputed_input_hash: str = Field(pattern=_SHA256_PATTERN)
    verification_classification: Literal["exact"] = "exact"
    recorded_at: AwareDatetime
