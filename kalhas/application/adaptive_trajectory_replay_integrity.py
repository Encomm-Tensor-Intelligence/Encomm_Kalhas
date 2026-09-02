"""Pure full-record integrity verification of runtime-4 adaptive replay manifests (B1A).

Store-independent, read-only, deterministic verification of a supplied
:class:`AdaptiveRunTrajectoryReplayManifest` against the explicitly
supplied **already-verified** runtime-4 execution authority and the
recorded replay timestamp authority. The caller verifies the
:class:`AdaptiveRunTrajectoryExecution` independently (with
``verify_adaptive_run_trajectory_execution_authority`` before it is
passed here); this verifier never re-verifies the execution, never reads
a store, and never reads a clock.

The manifest is first verified through its deterministic identity
(exact type, detached strict revalidation, runtime literal, deterministic
identifier, and self-covering content hash), then every provenance field
is checked for exact agreement with the verified execution authority:

- tenant/run/campaign ownership;
- the deterministic execution reference;
- world, scenario-seed, and world-realization identities with their
  content hashes;
- the adaptive-policy identifier, logical ``policy_id``, and content
  hash;
- the optional external-observation-input bundle identity/hash pair
  (both present or both absent, matching the execution);
- the runtime literal ``4.0.0``;
- the run input hash and the exact ordered trajectory-plan-set hash;
- the stored expected execution hash and the independently recomputed
  execution hash - both must equal the verified execution's content
  hash for an exact replay manifest;
- the ``replay_classification`` literal (always ``"exact"``);
- ``replayed_at`` equal to the recorded replay timestamp authority
  supplied by the caller (the established replay rule: the recorded
  RunPlan creation time - never a wall clock);
- the deterministic identifier and the final self-covering content hash.

The verifier performs no replay, no recomputation of the execution, no
store access, no write, no RNG, no clock read, no provider call, and no
repair: any violated rule raises the safe typed
:class:`AdaptiveRunTrajectoryReplayManifestIntegrityError` with a generic
public message; the internal ``reason`` names only the violated rule
class. A failing manifest is rejected, never repaired, normalized, or
silently accepted.
"""

from __future__ import annotations

from typing import NoReturn

from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
)
from kalhas.application.adaptive_trajectory_replay_identity import (
    adaptive_run_trajectory_replay_manifest_content_hash,
    adaptive_run_trajectory_replay_manifest_identifier,
    verify_adaptive_run_trajectory_replay_manifest_identity,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from kalhas.contracts.v1.shared import AwareDatetime


def _reject(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    raise AdaptiveRunTrajectoryReplayManifestIntegrityError(tenant_id, run_id, reason)


def _convert(
    tenant_id: str, run_id: str, reason: str
) -> AdaptiveRunTrajectoryReplayManifestIntegrityError:
    return AdaptiveRunTrajectoryReplayManifestIntegrityError(tenant_id, run_id, reason)


def verify_adaptive_run_trajectory_replay_manifest_record(
    manifest: AdaptiveRunTrajectoryReplayManifest,
    *,
    execution: AdaptiveRunTrajectoryExecution,
    replayed_at: AwareDatetime,
) -> None:
    """Verify a replay manifest against the verified execution and replay time.

    Every check is deterministic; the first violated rule raises
    :class:`AdaptiveRunTrajectoryReplayManifestIntegrityError` with a
    generic public message and an internal reason. The supplied
    ``execution`` is the already-verified runtime-4 execution authority
    (verified independently by the caller), and ``replayed_at`` is the
    recorded replay timestamp authority the caller derived from the
    recorded RunPlan creation time - never a wall clock. Nothing is
    replayed, recomputed, repaired, or written.
    """
    tenant_id = execution.tenant_id
    run_id = execution.run_id

    # Deterministic identity and detached strict revalidation first: a
    # validator-bypassed or forged manifest is rejected before any field
    # of it is trusted.
    try:
        verify_adaptive_run_trajectory_replay_manifest_identity(manifest)
    except (TypeError, ValueError, AttributeError) as exc:
        raise _convert(tenant_id, run_id, "manifest violates its contract") from exc

    # The deterministic manifest identifier is derived from the manifest's
    # own run identity and runtime literal.
    if manifest.identifier != adaptive_run_trajectory_replay_manifest_identifier(
        run_id=manifest.run_id,
        runtime_version=manifest.runtime_version,
    ):
        _reject(tenant_id, run_id, "manifest identifier mismatch")

    # Exact tenant/run/campaign ownership against the verified execution.
    if manifest.tenant_id != execution.tenant_id:
        _reject(tenant_id, run_id, "manifest tenant mismatch")
    if manifest.run_id != execution.run_id:
        _reject(tenant_id, run_id, "manifest run identity mismatch")
    if manifest.campaign_id != execution.campaign_id:
        _reject(tenant_id, run_id, "manifest campaign mismatch")

    # The deterministic execution reference must be the verified
    # execution's own deterministic identifier.
    if manifest.adaptive_run_trajectory_execution_id != execution.identifier:
        _reject(tenant_id, run_id, "manifest execution reference mismatch")

    # Exact world, scenario-seed, and world-realization provenance.
    if manifest.world_version_id != execution.world_version_id:
        _reject(tenant_id, run_id, "manifest world identity mismatch")
    if manifest.world_content_hash != execution.world_content_hash:
        _reject(tenant_id, run_id, "manifest world content hash mismatch")
    if manifest.scenario_seed_id != execution.scenario_seed_id:
        _reject(tenant_id, run_id, "manifest scenario seed mismatch")
    if manifest.seed_content_hash != execution.seed_content_hash:
        _reject(tenant_id, run_id, "manifest seed content hash mismatch")
    if manifest.world_realization_id != execution.world_realization_id:
        _reject(tenant_id, run_id, "manifest realization identity mismatch")
    if manifest.world_realization_content_hash != execution.world_realization_content_hash:
        _reject(tenant_id, run_id, "manifest realization content hash mismatch")

    # Exact adaptive-policy identity: stable contract identifier, logical
    # policy id, and content hash.
    if manifest.adaptive_policy_identifier != execution.adaptive_policy_identifier:
        _reject(tenant_id, run_id, "manifest policy identity mismatch")
    if manifest.policy_id != execution.policy_id:
        _reject(tenant_id, run_id, "manifest policy identifier mismatch")
    if manifest.adaptive_policy_content_hash != execution.adaptive_policy_content_hash:
        _reject(tenant_id, run_id, "manifest policy content hash mismatch")

    # The optional external bundle pair is both present or both absent
    # (contract-enforced) and must match the execution's pair exactly.
    if (
        manifest.external_observation_input_bundle_id
        != execution.external_observation_input_bundle_id
        or manifest.external_observation_input_bundle_content_hash
        != execution.external_observation_input_bundle_content_hash
    ):
        _reject(tenant_id, run_id, "manifest external bundle mismatch")

    # The exact runtime literal and the recorded run input / plan-set
    # hashes must agree with the verified execution.
    if manifest.runtime_version != execution.runtime_version:
        _reject(tenant_id, run_id, "manifest runtime mismatch")
    if manifest.input_hash != execution.input_hash:
        _reject(tenant_id, run_id, "manifest input hash mismatch")
    if manifest.trajectory_plan_set_hash != execution.trajectory_plan_set_hash:
        _reject(tenant_id, run_id, "manifest plan set hash mismatch")

    # For an exact replay manifest both the stored expected hash and the
    # independently recomputed hash must equal the verified execution's
    # content hash.
    if manifest.expected_execution_hash != execution.content_hash:
        _reject(tenant_id, run_id, "manifest expected execution hash mismatch")
    if manifest.recomputed_execution_hash != execution.content_hash:
        _reject(tenant_id, run_id, "manifest recomputed execution hash mismatch")

    # The classification literal is always exactly "exact".
    if manifest.replay_classification != "exact":
        _reject(tenant_id, run_id, "manifest classification mismatch")

    # The recorded replay timestamp must equal the caller-supplied
    # authority (the recorded RunPlan creation time).
    if manifest.replayed_at != replayed_at:
        _reject(tenant_id, run_id, "manifest replayed at mismatch")

    # The final aggregate content hash is exact (independent recompute).
    if manifest.content_hash != adaptive_run_trajectory_replay_manifest_content_hash(manifest):
        _reject(tenant_id, run_id, "manifest content hash mismatch")


__all__ = ["verify_adaptive_run_trajectory_replay_manifest_record"]
