"""Pure deterministic runtime-3 realization-aware campaign metric-statistics builder.

Phase 25.

Builds the immutable ``RealizationCampaignMetricStatisticsMatrix`` of one
completed runtime-3.0.0 campaign from **one completely verified Phase 25
``RealizationCampaignMetricObservationMatrix``** - and nothing else. The
module never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input. It performs no execution, replay,
transition evaluation, extraction, ranking, scoring, outcome calculation,
or recommendation of any kind: it only re-verifies the source matrix
identity, re-verifies every raw value strictly, resolves the exact
per-strategy/per-metric seed observations in the exact seed order, and
computes the one fixed deterministic descriptive-statistics definition
through the frozen Phase 22 statistics functions.

The descriptive-statistics algorithm is defined centrally by the Phase 22
runtime (``statistics_minimum``, ``statistics_maximum``,
``statistics_arithmetic_mean``, ``statistics_median``,
``statistics_population_standard_deviation`` - Python standard library
only) and is reused here unchanged: raw integers remain integers and raw
floats remain floats in ``ordered_observed_values`` even though the
derived statistics use floating-point calculation. If a valid exact raw
integer is too large to convert to a finite float, or any derived
statistic overflows or becomes non-finite, the complete statistics matrix
is rejected with the safe typed
:class:`RealizationCampaignMetricStatisticsIntegrityError` - nothing is
ever silently clamped, rounded, replaced, or partially returned.

The builder verifies, in order:

- the source matrix runtime is exactly ``"3.0.0"`` (anything else is
  :class:`UnsupportedRuntimeVersionError`);
- the strict trust boundary: the complete source matrix is revalidated
  against its contract (serializer-based ``model_dump`` +
  ``model_validate(strict=True)``), so wrong object types,
  validator-bypassed contracts, invalid nested observation values,
  boolean/numeric confusion, non-finite values, malformed positions or
  hashes, and serializer or type failures are rejected before any field
  is trusted; the supplied matrix is never normalized, repaired, or
  replaced;
- the source comparison mode is exactly ``identical_conditions``;
- the source matrix structural identity: its deterministic identifier
  and its self-covering content hash, verified independently;
- the exact strategy x seed cell shape (contiguous sequence positions,
  exact strategy-major/seed-minor order, strategy/seed identities bound
  to their aggregate positions, every cell's realization identity and
  content hash bound to the seed-aligned realization tuples, and the
  exact ordered metric collection in every cell);
- for every metric, identical immutable binding provenance across all
  cells (the same field set the Phase 25 observation matrix builder
  requires);
- every raw value strictly again before any numerical calculation (no
  bool, string, ``None``, container, non-finite float, or malformed
  kind/value combination - values are never normalized or repaired);
- per strategy x metric, the exact ordered seed observations in the
  exact ``ordered_scenario_seed_ids`` order (never sorted, repaired, or
  reordered), with the metric unit taken from the authoritative
  reference.

A source matrix with zero ordered metrics produces a valid statistics
matrix with ``summaries=()`` - no metric records are fabricated.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only):

- ``realization_metric_statistics_matrix_identifier(...)``: deterministic
  from the campaign identity, the world identity, the runtime version,
  and the source matrix identity.
- ``realization_metric_statistics_matrix_content_hash(matrix)``: SHA-256
  over the complete canonical matrix serialization excluding
  ``content_hash``.
- ``summarized_at`` is the authoritative Phase 25 matrix ``assembled_at``
  - never the wall clock.

Equivalent authoritative inputs always produce byte-identical artifacts;
the authoritative sequence order is never silently sorted or repaired -
an incorrect order is rejected. All errors are safe typed domain errors;
public messages never expose raw observed values, calculated statistics,
hashes, state values, field names, strategy policy, or validation
details, and the optional ``reason`` attribute is for internal
diagnostics only.
"""

from __future__ import annotations

import math
import warnings

from pydantic import BaseModel, ValidationError

from kalhas.application.campaign_metric_statistics_runtime import (
    statistics_arithmetic_mean,
    statistics_maximum,
    statistics_median,
    statistics_minimum,
    statistics_population_standard_deviation,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.realization_campaign_metric_observation_runtime import (
    _provenance_of,
)
from kalhas.application.realization_errors import (
    RealizationCampaignMetricStatisticsIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_content_hash,
    realization_metric_observation_matrix_identifier,
    realization_metric_statistics_matrix_content_hash,
    realization_metric_statistics_matrix_identifier,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign_metric_statistics import CampaignStrategyMetricStatistics
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.run_metric_observation import raw_value_matches_numeric_kind

_PLACEHOLDER_HASH = "0" * 64


def _reject(campaign_id: str, reason: str) -> RealizationCampaignMetricStatisticsIntegrityError:
    """A generic, safe statistics-matrix integrity error with an internal diagnostic reason."""
    return RealizationCampaignMetricStatisticsIntegrityError(campaign_id, reason)


def _strict_revalidate[ContractT: BaseModel](
    campaign_id: str,
    artifact: object,
    model_type: type[ContractT],
    reason: str,
) -> None:
    """Strictly revalidate one supplied artifact against its complete contract.

    Serializer-based strict revalidation (the same pattern the Phase 25
    trust boundaries use): the artifact's Python payload is re-derived
    and the contract is re-validated with ``strict=True``, so a
    validator-bypassed instance (wrong-typed or non-finite raw values,
    booleans where integers belong, invalid literals or hash patterns,
    malformed positions or ordering) is rejected before any field of it
    is trusted. Wrong object types and serializer/type failures are
    rejected as well. The supplied artifact is never normalized,
    repaired, or replaced: the revalidation result is discarded and the
    original object is used. Failures raise the typed statistics
    integrity error of this module.
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


def _verify_statistics_inputs(
    *,
    campaign_id: str,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> tuple[str, ...]:
    """Fully verify the supplied source matrix; return the ordered metric identifiers.

    Runs after the runtime gate and before any summary construction. The
    complete source matrix is first strictly revalidated against its
    contract; then the comparison mode, the deterministic identifier,
    the self-covering content hash, the exact cell shape and binding
    provenance, and every raw value are verified. Any failure raises the
    safe typed statistics integrity error; nothing here mutates an
    input.
    """
    # Strict trust boundary: the complete source matrix is revalidated
    # against its contract before any field is trusted.
    _strict_revalidate(
        campaign_id,
        observation_matrix,
        RealizationCampaignMetricObservationMatrix,
        "observation matrix violates its contract",
    )

    if observation_matrix.comparison_mode != "identical_conditions":
        raise _reject(campaign_id, "source matrix comparison mode mismatch")

    expected_identifier = realization_metric_observation_matrix_identifier(
        campaign_id=observation_matrix.campaign_id,
        world_version_id=observation_matrix.world_version_id,
        runtime_version=observation_matrix.runtime_version,
    )
    if observation_matrix.identifier != expected_identifier:
        raise _reject(campaign_id, "source matrix identifier mismatch")
    if (
        realization_metric_observation_matrix_content_hash(observation_matrix)
        != observation_matrix.content_hash
    ):
        raise _reject(campaign_id, "source matrix content hash mismatch")

    strategies = observation_matrix.ordered_strategy_candidate_ids
    seeds = observation_matrix.ordered_scenario_seed_ids
    metrics = observation_matrix.ordered_metric_ids
    seed_count = len(seeds)

    expected_cells = len(strategies) * seed_count
    if len(observation_matrix.cells) != expected_cells:
        raise _reject(campaign_id, "source matrix cell count mismatch")
    for position, cell in enumerate(observation_matrix.cells):
        if cell.sequence_position != position:
            raise _reject(campaign_id, "source matrix cell sequence mismatch")
        if cell.strategy_position != position // seed_count:
            raise _reject(campaign_id, "source matrix cell strategy position mismatch")
        if cell.seed_position != position % seed_count:
            raise _reject(campaign_id, "source matrix cell seed position mismatch")
        if cell.strategy_candidate_id != strategies[cell.strategy_position]:
            raise _reject(campaign_id, "source matrix cell strategy identity mismatch")
        if cell.scenario_seed_id != seeds[cell.seed_position]:
            raise _reject(campaign_id, "source matrix cell seed identity mismatch")
        if (
            cell.world_realization_id
            != observation_matrix.ordered_world_realization_ids[cell.seed_position]
        ):
            raise _reject(campaign_id, "source matrix cell realization identity mismatch")
        if (
            cell.world_realization_content_hash
            != observation_matrix.ordered_world_realization_content_hashes[cell.seed_position]
        ):
            raise _reject(campaign_id, "source matrix cell realization content hash mismatch")
        if [observation.metric_id for observation in cell.observations] != list(metrics):
            raise _reject(campaign_id, "source matrix cell metric collection mismatch")

    if metrics:
        # Binding provenance must agree exactly for the same metric
        # across every cell, and every raw value is strictly re-validated
        # against its authoritative numeric kind before any calculation.
        for metric_position in range(len(metrics)):
            reference = observation_matrix.cells[0].observations[metric_position]
            for cell in observation_matrix.cells:
                observation = cell.observations[metric_position]
                if _provenance_of(observation) != _provenance_of(reference):
                    raise _reject(
                        campaign_id,
                        "observation binding provenance mismatch across cells",
                    )
                if not raw_value_matches_numeric_kind(
                    observation.raw_value, observation.state_field_value_kind
                ):
                    raise _reject(
                        campaign_id,
                        "observed raw value is not an exact finite numeric value",
                    )
    return metrics


def _construct_statistics_matrix(
    *,
    campaign_id: str,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
    metrics: tuple[str, ...],
) -> RealizationCampaignMetricStatisticsMatrix:
    """Construct and fully hash the statistics matrix from completely verified inputs.

    Called exactly once, only after the source matrix passed the
    trust-boundary verification. Collects every strategy x metric raw
    value in the exact seed order, computes the five descriptive
    statistics exclusively through the frozen Phase 22 functions, and
    computes the self-covering content hash over the complete canonical
    payload excluding ``content_hash`` itself.
    """
    strategies = observation_matrix.ordered_strategy_candidate_ids
    seeds = observation_matrix.ordered_scenario_seed_ids
    seed_count = len(seeds)

    if not metrics:
        summaries: tuple[CampaignStrategyMetricStatistics, ...] = ()
    else:
        built: list[CampaignStrategyMetricStatistics] = []
        for strategy_position, strategy_id in enumerate(strategies):
            for metric_position, metric_id in enumerate(metrics):
                values = tuple(
                    observation_matrix.cells[strategy_position * seed_count + seed_position]
                    .observations[metric_position]
                    .raw_value
                    for seed_position in range(seed_count)
                )
                try:
                    minimum = statistics_minimum(values)
                    maximum = statistics_maximum(values)
                    arithmetic_mean = statistics_arithmetic_mean(values)
                    median = statistics_median(values)
                    population_standard_deviation = statistics_population_standard_deviation(values)
                except (OverflowError, ValueError):
                    raise _reject(
                        campaign_id, "observed values cannot be summarized deterministically"
                    ) from None
                for derived in (
                    minimum,
                    maximum,
                    arithmetic_mean,
                    median,
                    population_standard_deviation,
                ):
                    if not math.isfinite(derived):
                        raise _reject(campaign_id, "derived statistics are not finite")
                reference = observation_matrix.cells[strategy_position * seed_count].observations[
                    metric_position
                ]
                built.append(
                    CampaignStrategyMetricStatistics(
                        strategy_position=strategy_position,
                        metric_position=metric_position,
                        strategy_candidate_id=strategy_id,
                        metric_id=metric_id,
                        metric_unit=reference.metric_unit,
                        ordered_observed_values=values,
                        observation_count=len(values),
                        minimum=minimum,
                        maximum=maximum,
                        arithmetic_mean=arithmetic_mean,
                        median=median,
                        population_standard_deviation=population_standard_deviation,
                    )
                )
        summaries = tuple(built)

    matrix = RealizationCampaignMetricStatisticsMatrix(
        identifier=realization_metric_statistics_matrix_identifier(
            campaign_id=observation_matrix.campaign_id,
            world_version_id=observation_matrix.world_version_id,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
            source_metric_observation_matrix_id=observation_matrix.identifier,
        ),
        tenant_id=observation_matrix.tenant_id,
        campaign_id=observation_matrix.campaign_id,
        scenario_id=observation_matrix.scenario_id,
        world_version_id=observation_matrix.world_version_id,
        world_content_hash=observation_matrix.world_content_hash,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        comparison_mode="identical_conditions",
        statistics_mode="descriptive",
        source_metric_observation_matrix_id=observation_matrix.identifier,
        source_metric_observation_matrix_content_hash=observation_matrix.content_hash,
        ordered_strategy_candidate_ids=strategies,
        ordered_scenario_seed_ids=seeds,
        ordered_metric_ids=metrics,
        ordered_world_realization_ids=observation_matrix.ordered_world_realization_ids,
        ordered_world_realization_content_hashes=(
            observation_matrix.ordered_world_realization_content_hashes
        ),
        summaries=summaries,
        content_hash=_PLACEHOLDER_HASH,
        summarized_at=observation_matrix.assembled_at,
    )
    return matrix.model_copy(
        update={"content_hash": realization_metric_statistics_matrix_content_hash(matrix)}
    )


def build_realization_campaign_metric_statistics_matrix(
    *,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> RealizationCampaignMetricStatisticsMatrix:
    """Build and fully hash the deterministic realization-aware metric-statistics matrix.

    Derives the complete descriptive-statistics matrix of one completed
    runtime-3.0.0 campaign from its completely verified Phase 25
    ``RealizationCampaignMetricObservationMatrix``: the source runtime
    must be exactly ``"3.0.0"`` (legacy and unsupported versions raise
    :class:`UnsupportedRuntimeVersionError`), the complete source matrix
    is strictly revalidated against its contract before any field is
    trusted, the comparison mode must be exactly
    ``identical_conditions``, the source matrix structural identity
    (deterministic identifier pattern and self-covering content hash)
    must hold, every cell must be bound to its exact strategy/seed
    position and identity and to the seed-aligned realization tuple with
    the exact metric collection, every metric's immutable binding
    provenance must agree exactly across all cells, and every raw value
    is strictly re-validated before the exact descriptive statistics are
    computed per strategy x metric over the exact ordered seed
    observations through the frozen Phase 22 functions. ``summarized_at``
    is the source matrix ``assembled_at`` - never the wall clock. A
    source matrix with zero ordered metrics yields a valid statistics
    matrix with ``summaries=()``. Nothing here mutates any input,
    accesses the store, or performs execution, replay, transition
    evaluation, extraction, ranking, scoring, or outcome calculation;
    any construction-time validation/index/attribute failure converts to
    the typed statistics integrity error.
    """
    campaign_id = observation_matrix.campaign_id
    if observation_matrix.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            observation_matrix.runtime_version,
            operation="realization campaign metric statistics matrix",
        )

    try:
        metrics = _verify_statistics_inputs(
            campaign_id=campaign_id,
            observation_matrix=observation_matrix,
        )
        return _construct_statistics_matrix(
            campaign_id=campaign_id,
            observation_matrix=observation_matrix,
            metrics=metrics,
        )
    except RealizationCampaignMetricStatisticsIntegrityError:
        raise
    except (ValidationError, IndexError, AttributeError, TypeError) as exc:
        raise _reject(
            campaign_id, "internally built statistics matrix violates its contract"
        ) from exc


__all__ = ["build_realization_campaign_metric_statistics_matrix"]
