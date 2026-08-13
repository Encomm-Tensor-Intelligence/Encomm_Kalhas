"""Deterministic identity, content hashing, and provenance verification for runtime 3.0.0.

This module is dependency-neutral: it imports only contracts, the
repository hashing helpers, and ``world_uncertainty_identity`` (the
Phase 24 identity module). It never imports ``input_integrity`` or
``VerifiedRunInputs`` at runtime, so no import cycle can arise between
the input-integrity chain and the realization identity layer.

Identifier and content-hash rules mirror the runtime-2 conventions:

- run-scoped identifiers are deterministic from the run identity (and
  runtime version where the design requires it); the replay-manifest
  identifier is the readable ``realization-replay-{run_id}`` form;
- every content hash is the canonical SHA-256 of the complete payload
  excluding ``content_hash`` itself; the replay-manifest hash is
  self-covering by construction (it covers every other field, including
  the observation-set identity and hashes).

``verify_realization_provenance`` is the pure Phase 25 realization
provenance re-derivation: it checks scenario/world/seed identity
agreement, seed-content-hash agreement, uncertainty-model provenance
(both-or-neither, and exact identity/hash agreement when present), the
deterministic realization identifier recomputation (with the recorded
sampler/quantization provenance), and the content-hash recomputation.
Any mismatch raises the typed realization execution integrity error;
the realization is never repaired or silently accepted.
"""

from __future__ import annotations

from pydantic import BaseModel

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import (
    WorldRealization,
    WorldUncertaintyModel,
)

_EXECUTION_ID_PREFIX = "realization-trajectory-execution-"
_REPLAY_MANIFEST_ID_PREFIX = "realization-replay-"
_OBSERVATION_SET_ID_PREFIX = "realization-metric-observation-set-"
_TRAJECTORY_MATRIX_ID_PREFIX = "realization-trajectory-matrix-"
_OBSERVATION_MATRIX_ID_PREFIX = "realization-metric-observation-matrix-"
_STATISTICS_MATRIX_ID_PREFIX = "realization-metric-statistics-matrix-"
_ID_HASH_LENGTH = 16


def _identity(*, prefix: str, payload: dict[str, object]) -> str:
    """Deterministic identifier from the canonical identity payload."""
    return f"{prefix}{sha256_hex(canonical_json(payload))[:_ID_HASH_LENGTH]}"


def realization_run_trajectory_execution_identifier(*, run_id: str, runtime_version: str) -> str:
    """Deterministic runtime-3 execution identifier from run identity and runtime version."""
    return _identity(
        prefix=_EXECUTION_ID_PREFIX,
        payload={"run_id": run_id, "runtime_version": runtime_version},
    )


def realization_run_trajectory_replay_manifest_identifier(run_id: str) -> str:
    """Deterministic identifier of a run's runtime-3 replay manifest."""
    return f"{_REPLAY_MANIFEST_ID_PREFIX}{run_id}"


def realization_run_metric_observation_set_identifier(*, run_id: str, runtime_version: str) -> str:
    """Deterministic runtime-3 metric-observation-set identifier."""
    return _identity(
        prefix=_OBSERVATION_SET_ID_PREFIX,
        payload={"run_id": run_id, "runtime_version": runtime_version},
    )


def realization_trajectory_matrix_identifier(
    *, campaign_id: str, world_version_id: str, runtime_version: str
) -> str:
    """Deterministic runtime-3 campaign trajectory matrix identifier."""
    return _identity(
        prefix=_TRAJECTORY_MATRIX_ID_PREFIX,
        payload={
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
        },
    )


def realization_metric_observation_matrix_identifier(
    *, campaign_id: str, world_version_id: str, runtime_version: str
) -> str:
    """Deterministic runtime-3 campaign metric-observation matrix identifier."""
    return _identity(
        prefix=_OBSERVATION_MATRIX_ID_PREFIX,
        payload={
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
        },
    )


def realization_metric_statistics_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
    source_metric_observation_matrix_id: str,
) -> str:
    """Deterministic runtime-3 campaign metric-statistics matrix identifier."""
    return _identity(
        prefix=_STATISTICS_MATRIX_ID_PREFIX,
        payload={
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
            "source_metric_observation_matrix_id": source_metric_observation_matrix_id,
        },
    )


def _content_hash_of(artifact: BaseModel) -> str:
    payload = artifact.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def realization_run_trajectory_execution_content_hash(
    execution: RealizationRunTrajectoryExecution,
) -> str:
    """Canonical SHA-256 of the complete runtime-3 execution content, excluding content_hash."""
    return _content_hash_of(execution)


def realization_run_trajectory_replay_manifest_content_hash(
    manifest: RealizationRunTrajectoryReplayManifest,
) -> str:
    """Self-covering canonical SHA-256 of the replay manifest, excluding content_hash.

    Covers the complete payload - realization identity/hash, execution
    identity, expected/recomputed execution hashes, observation-set
    identity, expected/recomputed observation-set hashes, classification,
    timestamps, and run provenance - so any tamper fails the recompute at
    every trust boundary.
    """
    return _content_hash_of(manifest)


def realization_run_metric_observation_set_content_hash(
    observation_set: RealizationRunMetricObservationSet,
) -> str:
    """Canonical SHA-256 of the complete runtime-3 observation set, excluding content_hash."""
    return _content_hash_of(observation_set)


def realization_trajectory_matrix_content_hash(
    matrix: RealizationCampaignTrajectoryMatrix,
) -> str:
    """Canonical SHA-256 of the runtime-3 trajectory matrix, excluding content_hash."""
    return _content_hash_of(matrix)


def realization_metric_observation_matrix_content_hash(
    matrix: RealizationCampaignMetricObservationMatrix,
) -> str:
    """Canonical SHA-256 of the runtime-3 observation matrix, excluding content_hash."""
    return _content_hash_of(matrix)


def realization_metric_statistics_matrix_content_hash(
    matrix: RealizationCampaignMetricStatisticsMatrix,
) -> str:
    """Canonical SHA-256 of the runtime-3 statistics matrix, excluding content_hash."""
    return _content_hash_of(matrix)


def verify_realization_provenance(
    *,
    run_id: str,
    world: WorldVersion,
    seed: ScenarioSeed,
    realization: WorldRealization,
    uncertainty_model: WorldUncertaintyModel | None,
) -> None:
    """Verify a reconstructed world realization against the authoritative records.

    Pure re-derivation over the verified world, the recorded seed, the
    embedded uncertainty model (or its verified absence), and the
    realization itself: scenario/world/seed identity agreement,
    seed-content-hash agreement, uncertainty-model provenance
    (both-or-neither, and exact identity/hash agreement when present),
    deterministic realization-identifier recomputation (with the
    recorded sampler/quantization provenance), and content-hash
    recomputation. Any mismatch raises the typed realization execution
    integrity error with an internal diagnostic reason; the realization
    is never repaired, normalized, or silently accepted.
    """
    if realization.scenario_id != world.source_scenario_id:
        _reject(run_id, "realization scenario identity mismatch")
    if realization.tenant_id != world.tenant_id:
        _reject(run_id, "realization tenant identity mismatch")
    if realization.world_version_id != world.identifier:
        _reject(run_id, "realization world identity mismatch")
    if realization.world_content_hash != world.content_hash:
        _reject(run_id, "realization world content hash mismatch")
    if realization.scenario_seed_id != seed.identifier:
        _reject(run_id, "realization seed identity mismatch")
    if realization.seed_content_hash != seed_content_hash(seed):
        _reject(run_id, "realization seed content hash mismatch")

    if (realization.uncertainty_model_id is None) != (uncertainty_model is None):
        _reject(run_id, "realization uncertainty-model provenance both-or-neither violated")
    if uncertainty_model is not None:
        if realization.uncertainty_model_id != uncertainty_model.identifier:
            _reject(run_id, "realization uncertainty-model identity mismatch")
        if realization.uncertainty_model_content_hash != uncertainty_model.content_hash:
            _reject(run_id, "realization uncertainty-model content hash mismatch")

    expected_identifier = world_realization_identifier(
        world_version_id=realization.world_version_id,
        world_content_hash=realization.world_content_hash,
        scenario_seed_id=realization.scenario_seed_id,
        seed_content_hash_value=realization.seed_content_hash,
        uncertainty_model_id=realization.uncertainty_model_id,
        uncertainty_model_content_hash_value=realization.uncertainty_model_content_hash,
        sampler_version=realization.sampler_version,
        quantization_policy=realization.quantization_policy,
        quantization_fraction_bits=realization.quantization_fraction_bits,
    )
    if realization.identifier != expected_identifier:
        _reject(run_id, "realization identifier mismatch")
    if realization.content_hash != world_realization_content_hash(realization):
        _reject(run_id, "realization content hash mismatch")


def _reject(run_id: str, reason: str) -> None:
    raise RealizationRunTrajectoryExecutionIntegrityError(run_id, reason)
