"""Adaptive-run trajectory replay manifest (Phase 28, H28-S07A contract slice).

``AdaptiveRunTrajectoryReplayManifest`` is the fifth and final top-level
persisted authority of ADR-004 D28-04: an immutable, self-hashed
attestation that KALHAS independently regenerated the complete runtime-4
adaptive execution from verified recorded authorities and obtained exactly
the stored execution bytes/content hash. It binds the replay to the run,
campaign, and the stored runtime-4 ``AdaptiveRunTrajectoryExecution``
artifact (by its deterministic identifier), records the verified
world/scenario-seed/world-realization identities and content hashes, the
adaptive-policy identity (logical ``policy_id`` and stable contract
identifier) with its content hash, the optional external-observation-input
bundle identity/hash pair, the runtime literal ``4.0.0``, the run input
hash and exact ordered trajectory plan-set hash, the stored expected
execution hash, the independently recomputed execution hash, the
``replay_classification`` literal (always ``"exact"``), the deterministic
caller-supplied authority time ``replayed_at``, and the aggregate
``content_hash``.

Contract-invariant scope is deliberately structural and contract-local.
Exact equality of ``expected_execution_hash`` with
``recomputed_execution_hash`` is a cross-authority replay-integrity check
owned by the later verifier/service, never by this contract; identity and
self-hash verification belong to the next S07 slice. No metadata field, no
callbacks, expressions, import paths, provider/network fields,
observations, decisions, switches, states, or trajectory results are
copied into this manifest, and the module imports contracts only - never
application, NEXUS, LEGION, or domain code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract
from kalhas.contracts.v1.world_realization import IdentifierString, Sha256Hex


class AdaptiveRunTrajectoryReplayManifest(VersionedContract):
    """Immutable attestation of an exact independent runtime-4 replay.

    The manifest is persisted as a top-level authority, never nested
    evidence. The external observation input bundle identifier and content
    hash are both present or both absent (external provenance is
    optional). ``replayed_at`` is deterministic authority time and is
    later required to equal ``RunPlan.created_at``; no wall clock exists
    in this contract. ``content_hash`` is required but is never computed
    here, and ``expected_execution_hash`` is never compared with
    ``recomputed_execution_hash`` inside this contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: IdentifierString
    campaign_id: IdentifierString
    adaptive_run_trajectory_execution_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex
    adaptive_policy_identifier: IdentifierString
    policy_id: IdentifierString
    adaptive_policy_content_hash: Sha256Hex
    external_observation_input_bundle_id: IdentifierString | None = None
    external_observation_input_bundle_content_hash: Sha256Hex | None = None
    runtime_version: Literal["4.0.0"]
    input_hash: Sha256Hex
    trajectory_plan_set_hash: Sha256Hex
    expected_execution_hash: Sha256Hex
    recomputed_execution_hash: Sha256Hex
    replay_classification: Literal["exact"] = "exact"
    replayed_at: AwareDatetime
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def _external_bundle_pair_present_or_absent(self) -> AdaptiveRunTrajectoryReplayManifest:
        if (self.external_observation_input_bundle_id is None) != (
            self.external_observation_input_bundle_content_hash is None
        ):
            raise ValueError(
                "the external observation input bundle identifier and content hash "
                "must be both present or both absent"
            )
        return self


__all__ = ["AdaptiveRunTrajectoryReplayManifest"]
