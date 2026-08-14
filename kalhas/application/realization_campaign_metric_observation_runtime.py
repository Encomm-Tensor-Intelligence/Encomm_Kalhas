"""Pure deterministic runtime-3 realization-aware campaign metric-observation matrix builder.

Phase 25.

Builds the immutable ``RealizationCampaignMetricObservationMatrix`` of one
completed runtime-3.0.0 campaign from **already verified authoritative
records only**: the recorded ``CampaignSpec``, the completely verified
Phase 25 ``RealizationCampaignTrajectoryMatrix`` (whose strategy x shared-
seed layout and cell order are authoritative), and the exact ordered tuple
of completely verified Phase 25 ``RealizationRunMetricObservationSet``
artifacts - one per trajectory cell, in the exact trajectory-cell order.
The module never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input. It performs no execution, replay,
transition evaluation, observation extraction, aggregation, statistics,
scoring, ranking, or outcome calculation of any kind: the observation sets
it binds are the already-verified artifacts, and the builder only verifies
identities, references, and binding provenance, preserves exact orders and
raw values, and hashes the comparison-ready matrix.

The builder enforces the complete comparison-ready structure:

- the realization trajectory runtime version (the supplied trajectory
  matrix and every supplied observation set must record exactly 3.0.0;
  legacy and unsupported versions raise ``UnsupportedRuntimeVersionError``);
- the strict trust boundary: immediately after the runtime gates every
  supplied trajectory matrix and observation set is strictly revalidated
  against its complete contract (serializer-based ``model_dump`` +
  ``model_validate(strict=True)``), so wrong object types, validator-
  bypassed contracts, invalid nested observation values, boolean/numeric
  confusion, non-finite values, malformed positions/literals/hashes, and
  serializer or type failures are rejected before any field is trusted;
  the supplied objects are never normalized, repaired, or replaced;
- every observation set's ``observed_at`` equal to the recorded campaign
  ``created_at`` - never the wall clock;
- every observation's trajectory-result content hash a member of its
  trajectory cell's ordered result content hashes (a membership
  provenance check only - raw values and run-specific trajectory
  provenance are never required to agree across cells);
- the deterministic trajectory-matrix identifier and its recomputed
  content hash, verified independently of any caller;
- identical tenant ownership across the campaign, the trajectory matrix,
  and every observation set, with exact campaign/scenario/world identity
  agreement between the campaign and the trajectory matrix;
- the exact campaign strategy order and seed ensemble order (the
  trajectory-matrix ordering is authoritative and must equal the recorded
  campaign ordering);
- one observation set per trajectory cell in the exact trajectory-cell
  order - missing, additional, duplicated, reordered, or foreign sets are
  all rejected;
- the independent deterministic identifier and content-hash verification
  of every observation set;
- every cell bound to its exact run/run-plan/strategy/seed/input/world/
  execution identities, with tenant ownership verified;
- the observation-set realization identity and content hash equal to both
  the trajectory cell and its seed-aligned aggregate realization tuple;
- the trajectory-matrix strategy/seed/realization aggregate tuples
  preserved exactly;
- every cell carrying the exact ordered metric-id collection, with the
  metric collections agreeing exactly across all cells;
- for the same metric across cells, the immutable binding provenance must
  agree exactly (the same field set as the runtime-2 matrix builder);
- raw observation values and run-specific trajectory-plan/result
  provenance preserved exactly, without any equality requirement across
  strategies - they may differ legitimately and are never normalized;
- any construction-time validation/index/attribute failure converted to
  the same typed matrix integrity error, so the public builder never
  leaks a raw ``ValidationError``, ``IndexError``, ``AttributeError``, or
  internal validation detail.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only, reusing the Phase 25 identity functions):

- ``realization_metric_observation_matrix_identifier(...)``: deterministic
  from the campaign identity, the world identity, and the runtime version.
- ``realization_metric_observation_matrix_content_hash(matrix)``: SHA-256
  over the complete canonical matrix serialization excluding
  ``content_hash``.
- ``assembled_at`` is the recorded campaign ``created_at`` - never the
  wall clock.

Equivalent authoritative inputs always produce byte-identical artifacts;
the authoritative sequence order is never silently sorted or repaired - an
incorrect order is rejected. All errors are safe typed domain errors;
public messages never expose state or observed values, hashes, guards,
targets, policies, metadata, or validation details.
"""

from __future__ import annotations

import warnings

from pydantic import BaseModel, ValidationError

from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.realization_errors import (
    RealizationCampaignMetricObservationMatrixIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_content_hash,
    realization_metric_observation_matrix_identifier,
    realization_run_metric_observation_set_content_hash,
    realization_run_metric_observation_set_identifier,
    realization_trajectory_matrix_content_hash,
    realization_trajectory_matrix_identifier,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationCell,
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)

_PLACEHOLDER_HASH = "0" * 64

#: The immutable binding-provenance fields that must agree exactly for the
#: same metric across every cell of the matrix - the same field set the
#: runtime-2 matrix builder requires. Run-specific trajectory-plan/result
#: provenance (``trajectory_plan_id``, ``trajectory_plan_content_hash``,
#: ``trajectory_result_content_hash``) and the raw value itself are
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


def _reject(
    campaign_id: str, reason: str
) -> RealizationCampaignMetricObservationMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return RealizationCampaignMetricObservationMatrixIntegrityError(campaign_id, reason)


def _observation_metric_ids(observation_set: RealizationRunMetricObservationSet) -> list[str]:
    """The ordered metric identifiers of one set, exactly as recorded."""
    return [observation.metric_id for observation in observation_set.observations]


def _provenance_of(observation: object) -> tuple[object, ...]:
    """The immutable binding provenance of one observation, as an ordered tuple."""
    return tuple(getattr(observation, field) for field in _BINDING_PROVENANCE_FIELDS)


def _strict_revalidate[ContractT: BaseModel](
    campaign_id: str,
    artifact: object,
    model_type: type[ContractT],
    reason: str,
) -> None:
    """Strictly revalidate one supplied artifact against its complete contract.

    Serializer-based strict revalidation (the same pattern the store
    seams use): the artifact's Python payload is re-derived and the
    contract is re-validated with ``strict=True``, so a validator-bypassed
    instance (wrong-typed or non-finite raw values, booleans where
    integers belong, invalid literals or hash patterns, malformed
    positions or ordering) is rejected before any field of it is trusted.
    Wrong object types and serializer/type failures are rejected as well.
    The supplied artifact is never normalized, repaired, or replaced: the
    revalidation result is discarded and the original object is used.
    """
    if not isinstance(artifact, model_type):
        raise _reject(campaign_id, reason)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _reject(campaign_id, reason) from None


def _verify_observation_matrix_inputs(
    *,
    campaign: CampaignSpec,
    trajectory_matrix: RealizationCampaignTrajectoryMatrix,
    observation_sets: tuple[RealizationRunMetricObservationSet, ...],
) -> tuple[str, ...]:
    """Fully verify every supplied input; return the ordered metric identifiers.

    Runs after the runtime gates and before any matrix-cell construction.
    Every supplied artifact is first strictly revalidated against its
    complete contract; then the deterministic trajectory-matrix identity
    and content hash are verified, ownership and orders are checked, and
    every cell is bound to its exact observation set with the set's
    ``observed_at`` equal to the campaign ``created_at`` and every
    observation's trajectory-result content hash a member of the cell's
    ordered result content hashes. Any failure raises the safe typed
    matrix integrity error; nothing here mutates an input.
    """
    # Strict trust boundary: every supplied artifact is revalidated
    # against its complete contract before any field is trusted.
    _strict_revalidate(
        campaign.identifier,
        trajectory_matrix,
        RealizationCampaignTrajectoryMatrix,
        "trajectory matrix violates its contract",
    )
    for observation_set in observation_sets:
        _strict_revalidate(
            campaign.identifier,
            observation_set,
            RealizationRunMetricObservationSet,
            "observation set violates its contract",
        )

    # The supplied trajectory matrix is verified independently: its
    # deterministic identifier is re-derived from its own recorded
    # campaign/world/runtime identity, and its content hash is recomputed
    # over the complete canonical payload.
    if trajectory_matrix.identifier != realization_trajectory_matrix_identifier(
        campaign_id=trajectory_matrix.campaign_id,
        world_version_id=trajectory_matrix.world_version_id,
        runtime_version=trajectory_matrix.runtime_version,
    ):
        raise _reject(campaign.identifier, "trajectory matrix identifier mismatch")
    if trajectory_matrix.content_hash != realization_trajectory_matrix_content_hash(
        trajectory_matrix
    ):
        raise _reject(campaign.identifier, "trajectory matrix content hash mismatch")

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
        # The deterministic observed_at of a runtime-3 observation set is
        # the authoritative execution/run-plan timestamp, which equals the
        # campaign created_at; anything else is rejected before the set's
        # observations are trusted.
        if observation_set.observed_at != campaign.created_at:
            raise _reject(campaign.identifier, "observation set observed_at mismatch")
        # Independent verification of the set's deterministic identity and
        # recomputed content hash, before any field is trusted.
        if observation_set.identifier != realization_run_metric_observation_set_identifier(
            run_id=observation_set.run_id,
            runtime_version=observation_set.runtime_version,
        ):
            raise _reject(campaign.identifier, "observation set identifier mismatch")
        if observation_set.content_hash != realization_run_metric_observation_set_content_hash(
            observation_set
        ):
            raise _reject(campaign.identifier, "observation set content hash mismatch")

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
        if (
            observation_set.realization_run_trajectory_execution_id
            != cell.realization_run_trajectory_execution_id
        ):
            raise _reject(campaign.identifier, "observation set trajectory execution mismatch")
        if (
            observation_set.realization_run_trajectory_execution_content_hash
            != cell.realization_run_trajectory_execution_content_hash
        ):
            raise _reject(
                campaign.identifier,
                "observation set trajectory execution content hash mismatch",
            )
        if observation_set.world_realization_id != cell.world_realization_id:
            raise _reject(campaign.identifier, "observation set realization mismatch")
        if observation_set.world_realization_content_hash != cell.world_realization_content_hash:
            raise _reject(campaign.identifier, "observation set realization content hash mismatch")
        # The set's realization must equal both its trajectory cell and the
        # seed-aligned aggregate realization tuple of the trajectory matrix.
        if (
            observation_set.world_realization_id
            != trajectory_matrix.ordered_world_realization_ids[cell.seed_position]
        ):
            raise _reject(campaign.identifier, "observation set seed-aligned realization mismatch")
        if (
            observation_set.world_realization_content_hash
            != trajectory_matrix.ordered_world_realization_content_hashes[cell.seed_position]
        ):
            raise _reject(
                campaign.identifier,
                "observation set seed-aligned realization content hash mismatch",
            )
        if (
            cell.strategy_candidate_id
            != trajectory_matrix.ordered_strategy_candidate_ids[cell.strategy_position]
        ):
            raise _reject(campaign.identifier, "cell strategy position mismatch")
        if cell.scenario_seed_id != trajectory_matrix.ordered_scenario_seed_ids[cell.seed_position]:
            raise _reject(campaign.identifier, "cell seed position mismatch")

        # Every observation's trajectory-result content hash must be one
        # of the trajectory cell's ordered execution result content
        # hashes: a membership/provenance binding only. Raw values and
        # run-specific trajectory provenance are never required to agree
        # across different cells.
        for observation in observation_set.observations:
            if observation.trajectory_result_content_hash not in cell.result_content_hashes:
                raise _reject(
                    campaign.identifier,
                    "observation trajectory result reference mismatch",
                )

        metric_ids = _observation_metric_ids(observation_set)
        if expected_metric_ids is None:
            expected_metric_ids = metric_ids
        elif metric_ids != expected_metric_ids:
            raise _reject(campaign.identifier, "observation metric collections differ across cells")
        for position, observation in enumerate(observation_set.observations):
            reference = observation_sets[0].observations[position]
            if _provenance_of(observation) != _provenance_of(reference):
                raise _reject(
                    campaign.identifier,
                    "observation binding provenance mismatch across cells",
                )
    return tuple(expected_metric_ids or ())


def _construct_matrix(
    *,
    campaign: CampaignSpec,
    trajectory_matrix: RealizationCampaignTrajectoryMatrix,
    observation_sets: tuple[RealizationRunMetricObservationSet, ...],
    expected_metric_ids: tuple[str, ...],
) -> RealizationCampaignMetricObservationMatrix:
    """Construct and fully hash the matrix from completely verified inputs.

    Called exactly once, only after every input passed the trust-boundary
    verification. Builds the cells in the exact trajectory-cell order and
    computes the self-covering content hash over the complete canonical
    payload excluding ``content_hash`` itself.
    """
    cells = tuple(
        RealizationCampaignMetricObservationCell(
            sequence_position=cell.sequence_position,
            strategy_position=cell.strategy_position,
            seed_position=cell.seed_position,
            run_id=cell.run_id,
            run_plan_id=cell.run_plan_id,
            strategy_candidate_id=cell.strategy_candidate_id,
            scenario_seed_id=cell.scenario_seed_id,
            input_hash=cell.input_hash,
            realization_run_trajectory_execution_id=(cell.realization_run_trajectory_execution_id),
            realization_run_trajectory_execution_content_hash=(
                cell.realization_run_trajectory_execution_content_hash
            ),
            realization_run_metric_observation_set_id=observation_set.identifier,
            realization_run_metric_observation_set_content_hash=(observation_set.content_hash),
            world_realization_id=cell.world_realization_id,
            world_realization_content_hash=cell.world_realization_content_hash,
            observations=observation_set.observations,
        )
        for cell, observation_set in zip(trajectory_matrix.cells, observation_sets, strict=True)
    )

    matrix = RealizationCampaignMetricObservationMatrix(
        identifier=realization_metric_observation_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=trajectory_matrix.world_version_id,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        ),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=trajectory_matrix.scenario_id,
        world_version_id=trajectory_matrix.world_version_id,
        world_content_hash=trajectory_matrix.world_content_hash,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        comparison_mode="identical_conditions",
        ordered_strategy_candidate_ids=trajectory_matrix.ordered_strategy_candidate_ids,
        ordered_scenario_seed_ids=trajectory_matrix.ordered_scenario_seed_ids,
        ordered_metric_ids=expected_metric_ids,
        ordered_world_realization_ids=trajectory_matrix.ordered_world_realization_ids,
        ordered_world_realization_content_hashes=(
            trajectory_matrix.ordered_world_realization_content_hashes
        ),
        cells=cells,
        content_hash=_PLACEHOLDER_HASH,
        assembled_at=campaign.created_at,
    )
    return matrix.model_copy(
        update={"content_hash": realization_metric_observation_matrix_content_hash(matrix)}
    )


def build_realization_campaign_metric_observation_matrix(
    *,
    campaign: CampaignSpec,
    trajectory_matrix: RealizationCampaignTrajectoryMatrix,
    observation_sets: tuple[RealizationRunMetricObservationSet, ...],
) -> RealizationCampaignMetricObservationMatrix:
    """Build and fully hash the deterministic realization-aware metric-observation matrix.

    Requires the realization trajectory runtime version (the trajectory
    matrix and every observation set must record exactly 3.0.0; legacy
    and unsupported versions raise
    :class:`UnsupportedRuntimeVersionError`), then strictly revalidates
    every supplied artifact against its complete contract before any
    field is trusted. The deterministic trajectory-matrix identifier and
    content hash are verified independently; tenant ownership and exact
    campaign/scenario/world identity agreement are required; exactly one
    observation set per trajectory cell in the exact trajectory-cell
    order is required (missing, additional, duplicated, reordered, or
    foreign sets are rejected); every set's ``observed_at`` must equal
    the campaign ``created_at``; every observation's trajectory-result
    content hash must be a member of its trajectory cell's ordered result
    content hashes; every cell is bound to its exact
    run/run-plan/strategy/seed/input/world/execution identities and to
    the seed-aligned aggregate realization; every cell carries the same
    ordered metric-id collection; and the immutable binding provenance of
    the same metric must agree exactly across cells, while raw values and
    run-specific trajectory-plan/result provenance are preserved exactly
    without cross-strategy equality requirements. ``assembled_at`` is the
    recorded campaign ``created_at`` - never the wall clock. Nothing here
    mutates any input, accesses the store, or performs execution, replay,
    transition evaluation, observation extraction, aggregation,
    statistics, scoring, or ranking; any construction-time
    validation/index/attribute failure converts to the typed matrix
    integrity error.
    """
    if trajectory_matrix.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            trajectory_matrix.runtime_version,
            operation="realization campaign metric observation matrix",
        )
    for observation_set in observation_sets:
        if observation_set.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                observation_set.runtime_version,
                operation="realization campaign metric observation matrix",
            )

    try:
        expected_metric_ids = _verify_observation_matrix_inputs(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        return _construct_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
            expected_metric_ids=expected_metric_ids,
        )
    except RealizationCampaignMetricObservationMatrixIntegrityError:
        raise
    except (ValidationError, IndexError, AttributeError, TypeError) as exc:
        raise _reject(campaign.identifier, "internally built matrix violates its contract") from exc
