"""Pure deterministic campaign metric-statistics builder (Phase 22).

Builds the immutable ``CampaignMetricStatisticsMatrix`` of one
completed runtime-2.0.0 campaign from **one completely verified Phase
21 ``CampaignMetricObservationMatrix``** - and nothing else. The module
never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input. It performs no execution, replay,
transition evaluation, extraction, or outcome calculation of any kind:
it only re-verifies the source matrix identity, re-verifies every raw
value strictly, resolves the exact per-strategy/per-metric seed
observations in the exact seed order, and computes the one fixed
deterministic descriptive-statistics definition.

The **one explicit descriptive-statistics algorithm** (Python standard
library only, defined centrally in this module and asserted exactly by
the Phase 22 tests):

- ``statistics_minimum``: the built-in ``min`` over the exact finite
  numeric values, converted to float.
- ``statistics_maximum``: the built-in ``max`` over the exact finite
  numeric values, converted to float.
- ``statistics_arithmetic_mean``: ``math.fsum(float(value) for value in
  values) / len(values)``.
- ``statistics_median``: sort numerically; for an odd count, the float
  of the middle value; for an even count,
  ``math.fsum((float(left), float(right))) / 2``.
- ``statistics_population_standard_deviation``: uses the defined
  arithmetic mean, sums the exact square deviations with
  ``math.fsum``, divides by the population count N (never N-1), and
  takes ``math.sqrt``; one value gives exactly ``0.0``.

No NumPy, pandas, or other dependencies are used. Raw integers remain
integers and raw floats remain floats in ``ordered_observed_values``
even though the derived statistics use floating-point calculation. If a
valid exact raw integer is too large to convert to a finite float, or
any derived statistic overflows or becomes non-finite, the complete
statistics matrix is rejected with the safe typed
:class:`CampaignMetricStatisticsIntegrityError` - nothing is ever
silently clamped, rounded, replaced, or partially returned.

The builder verifies, in order:

- the source matrix runtime is exactly ``"2.0.0"`` (anything else is
  :class:`UnsupportedRuntimeVersionError`), and its comparison mode is
  exactly ``identical_conditions``;
- the source matrix structural identity: its deterministic identifier
  pattern and its self-covering content hash;
- the exact strategy x seed cell shape, with every cell's sequence,
  strategy, and seed positions and identities bound exactly;
- the exact metric collection in every cell;
- for every metric, identical immutable binding provenance across all
  cells (metric id and unit, binding, manifest, state-model, state
  field, value kind, and observation point);
- every raw value strictly again before any numerical calculation (no
  bool, string, ``None``, container, non-finite float, or malformed
  kind/value combination);
- per strategy x metric, the exact ordered seed observations in the
  exact ``ordered_scenario_seed_ids`` order (never sorted, repaired, or
  reordered).

A source matrix with zero ordered metrics produces a valid statistics
matrix with ``summaries=()`` - no metric records are fabricated.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only):

- ``campaign_metric_statistics_matrix_identifier(...)``: deterministic
  from the campaign identity, the world identity, the runtime version,
  and the source matrix identifier, with a readable distinct prefix.
- ``campaign_metric_statistics_matrix_content_hash(matrix)``: SHA-256
  over the complete canonical matrix serialization excluding
  ``content_hash``.
- ``summarized_at`` is the authoritative Phase 21 matrix
  ``assembled_at`` - never the wall clock.

Equivalent authoritative inputs always produce byte-identical
artifacts; the authoritative sequence order is never silently sorted or
repaired - an incorrect order is rejected.

All errors are safe typed domain errors; public messages never expose
raw observed values, calculated statistics, hashes, state values,
field names, strategy policy, or validation details.
"""

from __future__ import annotations

import math

from kalhas.application.campaign_metric_observation_runtime import (
    _provenance_of,
    campaign_metric_observation_matrix_content_hash,
    campaign_metric_observation_matrix_identifier,
)
from kalhas.application.domain_errors import (
    CampaignMetricStatisticsIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.campaign_metric_statistics import (
    CampaignMetricStatisticsMatrix,
    CampaignStrategyMetricStatistics,
)
from kalhas.contracts.v1.run_metric_observation import raw_value_matches_numeric_kind

_MATRIX_ID_PREFIX = "metric-statistics-matrix-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def statistics_minimum(values: tuple[int | float, ...]) -> float:
    """The exact observed minimum as a float (built-in ``min``, never rounded)."""
    return float(min(values))


def statistics_maximum(values: tuple[int | float, ...]) -> float:
    """The exact observed maximum as a float (built-in ``max``, never rounded)."""
    return float(max(values))


def statistics_arithmetic_mean(values: tuple[int | float, ...]) -> float:
    """The exact arithmetic mean: ``math.fsum`` over the float conversions, divided by N."""
    return math.fsum(float(value) for value in values) / len(values)


def statistics_median(values: tuple[int | float, ...]) -> float:
    """The exact median of the numerically sorted values.

    Odd counts take the float of the middle value; even counts take
    ``math.fsum((float(left), float(right))) / 2``.
    """
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return math.fsum((float(ordered[middle - 1]), float(ordered[middle]))) / 2


def statistics_population_standard_deviation(values: tuple[int | float, ...]) -> float:
    """The exact population standard deviation (denominator N, never N-1).

    Uses the defined arithmetic mean, sums the exact square deviations
    with ``math.fsum``, divides by the population count, and takes
    ``math.sqrt``. One value gives exactly ``0.0``.
    """
    mean = statistics_arithmetic_mean(values)
    squared_deviations = ((float(value) - mean) ** 2 for value in values)
    variance = math.fsum(squared_deviations) / len(values)
    return math.sqrt(variance)


def campaign_metric_statistics_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
    source_metric_observation_matrix_id: str,
) -> str:
    """Deterministic statistics-matrix identifier from the full source identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    runtime_version, source_metric_observation_matrix_id)`` identity
    with a readable, distinct prefix; identical inputs always yield the
    identical identifier.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
            "source_metric_observation_matrix_id": source_metric_observation_matrix_id,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_metric_statistics_matrix_content_hash(
    matrix: CampaignMetricStatisticsMatrix,
) -> str:
    """Canonical SHA-256 of the complete matrix content, excluding content_hash."""
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(campaign_id: str, reason: str) -> CampaignMetricStatisticsIntegrityError:
    """A generic, safe statistics-matrix integrity error with an internal diagnostic reason."""
    return CampaignMetricStatisticsIntegrityError(campaign_id, reason)


def build_campaign_metric_statistics_matrix(
    *,
    observation_matrix: CampaignMetricObservationMatrix,
) -> CampaignMetricStatisticsMatrix:
    """Build and fully hash the deterministic campaign metric-statistics matrix.

    Derives the complete descriptive-statistics matrix of one completed
    runtime-2.0.0 campaign from its completely verified Phase 21
    ``CampaignMetricObservationMatrix``: the source runtime must be
    exactly ``"2.0.0"`` (legacy and unsupported versions raise
    :class:`UnsupportedRuntimeVersionError`), the comparison mode must
    be exactly ``identical_conditions``, the source matrix structural
    identity (deterministic identifier pattern and self-covering
    content hash) must hold, every cell must be bound to its exact
    strategy/seed position and identity with the exact metric
    collection, every metric's immutable binding provenance must agree
    exactly across all cells, and every raw value is strictly
    re-validated before the exact descriptive statistics are computed
    per strategy x metric over the exact ordered seed observations.
    ``summarized_at`` is the source matrix ``assembled_at`` - never the
    wall clock. A source matrix with zero ordered metrics yields a
    valid statistics matrix with ``summaries=()``. Nothing here mutates
    any input, accesses the store, or performs execution, replay,
    extraction, ranking, scoring, or outcome calculation.
    """
    campaign_id = observation_matrix.campaign_id
    if observation_matrix.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            observation_matrix.runtime_version,
            operation="campaign metric statistics matrix",
        )
    if observation_matrix.comparison_mode != "identical_conditions":
        raise _reject(campaign_id, "source matrix comparison mode mismatch")

    expected_identifier = campaign_metric_observation_matrix_identifier(
        campaign_id=observation_matrix.campaign_id,
        world_version_id=observation_matrix.world_version_id,
        runtime_version=observation_matrix.runtime_version,
    )
    if observation_matrix.identifier != expected_identifier:
        raise _reject(campaign_id, "source matrix identifier mismatch")
    if (
        campaign_metric_observation_matrix_content_hash(observation_matrix)
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
        if [observation.metric_id for observation in cell.observations] != list(metrics):
            raise _reject(campaign_id, "source matrix cell metric collection mismatch")

    if not metrics:
        summaries: tuple[CampaignStrategyMetricStatistics, ...] = ()
    else:
        # Binding provenance must agree exactly for the same metric
        # across every cell, and every raw value is strictly re-validated
        # against its authoritative numeric kind before any calculation.
        for metric_position in range(len(metrics)):
            reference = observation_matrix.cells[0].observations[metric_position]
            for cell in observation_matrix.cells:
                observation = cell.observations[metric_position]
                if _provenance_of(observation) != _provenance_of(reference):
                    raise _reject(
                        campaign_id, "observation binding provenance mismatch across cells"
                    )
                if not raw_value_matches_numeric_kind(
                    observation.raw_value, observation.state_field_value_kind
                ):
                    raise _reject(
                        campaign_id, "observed raw value is not an exact finite numeric value"
                    )

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

    matrix = CampaignMetricStatisticsMatrix(
        identifier=campaign_metric_statistics_matrix_identifier(
            campaign_id=observation_matrix.campaign_id,
            world_version_id=observation_matrix.world_version_id,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
            source_metric_observation_matrix_id=observation_matrix.identifier,
        ),
        tenant_id=observation_matrix.tenant_id,
        campaign_id=observation_matrix.campaign_id,
        scenario_id=observation_matrix.scenario_id,
        world_version_id=observation_matrix.world_version_id,
        world_content_hash=observation_matrix.world_content_hash,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        comparison_mode="identical_conditions",
        statistics_mode="descriptive",
        source_metric_observation_matrix_id=observation_matrix.identifier,
        source_metric_observation_matrix_content_hash=observation_matrix.content_hash,
        ordered_strategy_candidate_ids=strategies,
        ordered_scenario_seed_ids=seeds,
        ordered_metric_ids=metrics,
        summaries=summaries,
        content_hash=_PLACEHOLDER_HASH,
        summarized_at=observation_matrix.assembled_at,
    )
    return matrix.model_copy(
        update={"content_hash": campaign_metric_statistics_matrix_content_hash(matrix)}
    )


__all__ = [
    "build_campaign_metric_statistics_matrix",
    "campaign_metric_statistics_matrix_content_hash",
    "campaign_metric_statistics_matrix_identifier",
    "statistics_arithmetic_mean",
    "statistics_maximum",
    "statistics_median",
    "statistics_minimum",
    "statistics_population_standard_deviation",
]
