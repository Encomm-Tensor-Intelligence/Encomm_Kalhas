"""Pure deterministic campaign metric-observation matrix builder (Phase 21).

Builds the immutable ``CampaignMetricObservationMatrix`` of one
completed runtime-2.0.0 campaign from **already verified authoritative
records only**: the recorded ``CampaignSpec``, the completely verified
Phase 18 ``CampaignTrajectoryMatrix`` (whose strategy x shared-seed
layout and RunPlan order are authoritative), and the exact ordered tuple
of completely verified Phase 20 ``RunMetricObservationSet`` artifacts -
one per trajectory-matrix cell, in the exact trajectory-cell/RunPlan
order. The module never loads the store, never calls LEGION or NEXUS,
never uses wall-clock time, randomness, network, providers, filesystem,
or domain packs, and never mutates any input. It performs no execution,
replay, transition evaluation, aggregation, or outcome calculation of
any kind: the observation sets it binds are the already-verified Phase
20 artifacts, and the builder only verifies identities and binding
provenance, preserves exact orders and raw values, and hashes the
comparison-ready matrix.

The builder enforces the complete comparison-ready structure:

- the trajectory runtime version (every supplied artifact must record
  2.0.0);
- identical tenant ownership across the campaign, the trajectory
  matrix, and every observation set;
- exact campaign/scenario/world identity agreement between the
  campaign, the trajectory matrix, and every observation set;
- the exact campaign strategy order and seed ensemble order (the
  trajectory matrix ordering is authoritative and must equal the
  recorded campaign ordering);
- one observation set per trajectory-matrix cell in the exact
  trajectory-cell order - missing, additional, duplicated, reordered,
  or foreign sets are all rejected;
- every cell bound to its exact run/run-plan/strategy/seed/input/
  world/trajectory-execution identities, with tenant ownership
  verified;
- every cell's observation ordering preserved exactly, with every cell
  carrying the same ordered metric-id collection;
- for the same metric across cells, the immutable binding provenance
  must agree exactly (metric id and unit, binding identifier and
  content hash, manifest identity, state-model identity and content
  hash, state-field identity and value kind, and the observation
  point);
- run-specific trajectory-plan/result provenance (the plan identity/
  content hash and the result content hash recorded on each
  observation) is preserved exactly **without** requiring equality
  across strategies;
- raw values preserved exactly, without interpretation or conversion.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only):

- ``campaign_metric_observation_matrix_identifier(...)``: deterministic
  from the campaign identity, the world identity, and the runtime
  version, with a readable distinct prefix.
- ``campaign_metric_observation_matrix_content_hash(matrix)``: SHA-256
  over the complete canonical matrix serialization excluding
  ``content_hash``.
- ``assembled_at`` is the recorded campaign ``created_at`` - never the
  wall clock.

Equivalent authoritative inputs always produce byte-identical artifacts
regardless of caller container insertion order; the authoritative
sequence order is never silently sorted or repaired - an incorrect
order is rejected.

All errors are safe typed domain errors; public messages never expose
state or observed values, hashes, guards, targets, policies, metadata,
or validation details.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    CampaignMetricObservationMatrixIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.campaign_metric_observation import (
    CampaignMetricObservationCell,
    CampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.run_metric_observation import (
    RunMetricObservationSet,
    RunMetricObservationValue,
)

_MATRIX_ID_PREFIX = "metric-observation-matrix-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64

#: The immutable binding-provenance fields that must agree exactly for
#: the same metric across every cell of the matrix. Run-specific
#: trajectory-plan/result provenance and the raw value itself are
#: deliberately excluded: they are per-run provenance and observation,
#: preserved exactly but never required to agree across strategies.
_BINDING_PROVENANCE_FIELDS = (
    "metric_id",
    "metric_unit",
    "binding_id",
    "binding_content_hash",
    "manifest_id",
    "state_model_identifier",
    "state_model_id",
    "state_model_content_hash",
    "state_field_id",
    "state_field_value_kind",
    "observation_point",
)


def campaign_metric_observation_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
) -> str:
    """Deterministic matrix identifier from campaign, world, and runtime identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    runtime_version)`` identity with a readable, distinct prefix;
    identical inputs always yield the identical identifier.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_metric_observation_matrix_content_hash(
    matrix: CampaignMetricObservationMatrix,
) -> str:
    """Canonical SHA-256 of the complete matrix content, excluding content_hash."""
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(campaign_id: str, reason: str) -> CampaignMetricObservationMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return CampaignMetricObservationMatrixIntegrityError(campaign_id, reason)


def _observation_metric_ids(
    observation_set: RunMetricObservationSet,
) -> list[str]:
    """The ordered metric identifiers of one set, exactly as recorded."""
    return [observation.metric_id for observation in observation_set.observations]


def _provenance_of(
    observation: RunMetricObservationValue,
) -> tuple[object, ...]:
    """The immutable binding provenance of one observation, as an ordered tuple."""
    return tuple(getattr(observation, field) for field in _BINDING_PROVENANCE_FIELDS)


def build_campaign_metric_observation_matrix(
    *,
    campaign: CampaignSpec,
    trajectory_matrix: CampaignTrajectoryMatrix,
    observation_sets: tuple[RunMetricObservationSet, ...],
) -> CampaignMetricObservationMatrix:
    """Build and fully hash the deterministic campaign metric-observation matrix.

    Requires the trajectory runtime version (every supplied artifact
    must record 2.0.0; legacy and unsupported versions raise
    :class:`UnsupportedRuntimeVersionError`), identical tenant
    ownership, exact campaign/scenario/world identity agreement, the
    exact campaign strategy order and seed ensemble order, and exactly
    one observation set per trajectory-matrix cell in the exact
    trajectory-cell/RunPlan order - missing, additional, duplicated,
    reordered, or foreign sets are rejected. Every cell is bound to its
    exact run/run-plan/strategy/seed/input/world/trajectory-execution
    identities; every cell carries the same ordered metric-id
    collection; and the immutable binding provenance of the same metric
    must agree exactly across cells, while run-specific
    trajectory-plan/result provenance and raw values are preserved
    exactly without cross-strategy equality requirements.
    ``assembled_at`` is the recorded campaign ``created_at`` - never
    the wall clock. Nothing here mutates any input, accesses the store,
    or performs execution, replay, transition evaluation, aggregation,
    or outcome calculation.
    """
    if trajectory_matrix.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            trajectory_matrix.runtime_version, operation="campaign metric observation matrix"
        )
    for observation_set in observation_sets:
        if observation_set.runtime_version != TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                observation_set.runtime_version,
                operation="campaign metric observation matrix",
            )

    if trajectory_matrix.tenant_id != campaign.tenant_id:
        raise _reject(campaign.identifier, "trajectory matrix tenant mismatch")
    if trajectory_matrix.campaign_id != campaign.identifier:
        raise _reject(campaign.identifier, "trajectory matrix campaign mismatch")
    if trajectory_matrix.scenario_id != campaign.scenario_id:
        raise _reject(campaign.identifier, "trajectory matrix scenario mismatch")
    if trajectory_matrix.world_version_id != campaign.world_version_id:
        raise _reject(campaign.identifier, "trajectory matrix world version mismatch")

    if list(campaign.strategy_candidate_ids) != list(
        trajectory_matrix.ordered_strategy_candidate_ids
    ):
        raise _reject(campaign.identifier, "campaign strategy order mismatch")
    if [seed.identifier for seed in campaign.seed_ensemble] != list(
        trajectory_matrix.ordered_scenario_seed_ids
    ):
        raise _reject(campaign.identifier, "campaign seed ensemble order mismatch")

    expected_count = len(trajectory_matrix.cells)
    if len(observation_sets) != expected_count:
        raise _reject(campaign.identifier, "observation set count mismatch")

    expected_metric_ids: list[str] | None = None
    for cell, observation_set in zip(trajectory_matrix.cells, observation_sets, strict=True):
        if observation_set.tenant_id != campaign.tenant_id:
            raise _reject(campaign.identifier, "observation set tenant mismatch")
        if observation_set.run_id != cell.run_id:
            raise _reject(campaign.identifier, "observation set run identity mismatch")
        if observation_set.run_plan_id != cell.run_plan_id:
            raise _reject(campaign.identifier, "observation set run plan mismatch")
        if observation_set.campaign_id != campaign.identifier:
            raise _reject(campaign.identifier, "observation set campaign mismatch")
        if observation_set.scenario_id != trajectory_matrix.scenario_id:
            raise _reject(campaign.identifier, "observation set scenario mismatch")
        if observation_set.world_version_id != trajectory_matrix.world_version_id:
            raise _reject(campaign.identifier, "observation set world version mismatch")
        if observation_set.world_content_hash != trajectory_matrix.world_content_hash:
            raise _reject(campaign.identifier, "observation set world content hash mismatch")
        if observation_set.strategy_candidate_id != cell.strategy_candidate_id:
            raise _reject(campaign.identifier, "observation set strategy mismatch")
        if observation_set.scenario_seed_id != cell.scenario_seed_id:
            raise _reject(campaign.identifier, "observation set scenario seed mismatch")
        if observation_set.input_hash != cell.input_hash:
            raise _reject(campaign.identifier, "observation set input hash mismatch")
        if observation_set.trajectory_execution_id != cell.trajectory_execution_id:
            raise _reject(campaign.identifier, "observation set trajectory execution mismatch")
        if (
            observation_set.trajectory_execution_content_hash
            != cell.trajectory_execution_content_hash
        ):
            raise _reject(
                campaign.identifier, "observation set trajectory execution content hash mismatch"
            )
        if (
            cell.strategy_candidate_id
            != trajectory_matrix.ordered_strategy_candidate_ids[cell.strategy_position]
        ):
            raise _reject(campaign.identifier, "cell strategy position mismatch")
        if cell.scenario_seed_id != trajectory_matrix.ordered_scenario_seed_ids[cell.seed_position]:
            raise _reject(campaign.identifier, "cell seed position mismatch")

        metric_ids = _observation_metric_ids(observation_set)
        if expected_metric_ids is None:
            expected_metric_ids = metric_ids
        elif metric_ids != expected_metric_ids:
            raise _reject(campaign.identifier, "observation metric collections differ across cells")
        for position, observation in enumerate(observation_set.observations):
            reference = observation_sets[0].observations[position]
            if _provenance_of(observation) != _provenance_of(reference):
                raise _reject(
                    campaign.identifier, "observation binding provenance mismatch across cells"
                )

    cells = tuple(
        CampaignMetricObservationCell(
            sequence_position=cell.sequence_position,
            strategy_position=cell.strategy_position,
            seed_position=cell.seed_position,
            run_id=cell.run_id,
            run_plan_id=cell.run_plan_id,
            strategy_candidate_id=cell.strategy_candidate_id,
            scenario_seed_id=cell.scenario_seed_id,
            input_hash=cell.input_hash,
            trajectory_execution_id=cell.trajectory_execution_id,
            trajectory_execution_content_hash=cell.trajectory_execution_content_hash,
            metric_observation_set_id=observation_set.identifier,
            metric_observation_set_content_hash=observation_set.content_hash,
            observations=observation_set.observations,
        )
        for cell, observation_set in zip(trajectory_matrix.cells, observation_sets, strict=True)
    )

    matrix = CampaignMetricObservationMatrix(
        identifier=campaign_metric_observation_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=trajectory_matrix.world_version_id,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=trajectory_matrix.scenario_id,
        world_version_id=trajectory_matrix.world_version_id,
        world_content_hash=trajectory_matrix.world_content_hash,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ordered_strategy_candidate_ids=trajectory_matrix.ordered_strategy_candidate_ids,
        ordered_scenario_seed_ids=trajectory_matrix.ordered_scenario_seed_ids,
        ordered_metric_ids=tuple(expected_metric_ids or ()),
        cells=cells,
        content_hash=_PLACEHOLDER_HASH,
        assembled_at=campaign.created_at,
    )
    return matrix.model_copy(
        update={"content_hash": campaign_metric_observation_matrix_content_hash(matrix)}
    )
