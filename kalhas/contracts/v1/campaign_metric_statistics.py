"""Campaign metric statistics contracts: deterministic descriptive statistics (Phase 22).

Phase 22 introduces the **deterministic campaign metric-statistics
matrix**: an immutable, tenant-scoped, descriptive-statistics artifact
derived exclusively from one completely verified Phase 21
``CampaignMetricObservationMatrix`` of a completed runtime-2.0.0
campaign. The pipeline is

    verified CampaignMetricObservationMatrix
        -> exact per-strategy/per-metric seed observations
        -> deterministic descriptive statistics

``CampaignStrategyMetricStatistics`` is one immutable strategy x metric
summary across the campaign's identical ordered shared seeds: the exact
strategy/metric positions and identities, the authoritative metric unit,
the exact ordered raw observed values preserved in the exact Phase 21
seed order (raw integers remain integers, raw floats remain floats, and
booleans, strings, ``None``, containers, NaN, and Infinity are never
accepted as numbers), the observation count, and the exact finite
derived descriptive statistics - minimum, maximum, arithmetic mean,
median, and population standard deviation. The collection is non-empty
because every campaign has at least one shared seed; for a single
observation the population standard deviation is exactly ``0.0``.
Minimum and maximum equal the exact observed extrema; no rounding,
clipping, normalization, weighting, or unit conversion ever happens.

``CampaignMetricStatisticsMatrix`` is the immutable aggregate: the
campaign, scenario, and world identity with the world content hash; the
trajectory runtime version (always ``"2.0.0"``), the comparison mode
(always ``identical_conditions``), and the statistics mode (always
``descriptive``); the exact verified source
``CampaignMetricObservationMatrix`` reference (deterministic identifier
and content hash); the exact ordered strategy candidate, scenario seed,
and metric identifiers; the complete summary tuple in the exact
strategy-major, metric-minor order; the self-covering ``content_hash``;
and the deterministic ``summarized_at`` taken from the authoritative
Phase 21 matrix ``assembled_at`` - never the wall clock. Its identifier
is deterministic from the campaign identity, the world identity, the
runtime version, and the source matrix identity.

The contract enforces the structural shape: unique and non-empty
strategy/seed identifiers; unique and strictly increasing metric
identifiers; summaries in the exact strategy-major/metric-minor order
with contiguous positions and exact identity-vs-position agreement;
every summary's observed-value length equal to the seed count; and the
complete strategy x metric Cartesian product present exactly once -
duplicate, missing, additional, or reordered summaries are rejected,
and an empty ``ordered_metric_ids`` requires empty ``summaries``.
Authoritative identity, hash, provenance, and raw-value verification
against the verified Phase 21 matrix remains in the application layer
(the pure statistics builder and the verified query service).

The matrix is **descriptive statistics only**. It ranks nothing, scores
nothing, declares no winner, compares nothing against objectives or
targets, creates no pass/fail judgment, produces no ``MetricOutcome``,
``OutcomeVector``, evidence, ``DecisionBrief``, or recommendation,
interprets no declared aggregation policy, normalizes no units, and
samples no uncertainty. Nothing here loads, imports, instantiates, or
executes a domain pack, and no field type can express a callback,
expression, formula, code reference, provider, or executable mechanism.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The statistics matrix runtime version literal; must stay equal to the
#: authoritative ``TRAJECTORY_RUNTIME_VERSION`` constant (asserted by the
#: Phase 22 boundary tests).
STATISTICS_MATRIX_RUNTIME_VERSION_LITERAL = "2.0.0"


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value.

    Booleans are never accepted as integers or numbers, and non-finite
    floats (NaN/Infinity) are rejected because they are not valid JSON
    numbers. Strings and containers are rejected - no numeric coercion
    of any kind happens.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


class CampaignStrategyMetricStatistics(BaseModel):
    """One immutable strategy x metric descriptive-statistics summary.

    Summarizes the exact ordered raw observed values of one metric for
    one strategy across the campaign's identical ordered shared seeds:
    the strategy and metric positions and identities, the authoritative
    metric unit, the exact observed values preserved in the exact Phase
    21 seed order (raw integers remain integers, raw floats remain
    floats - never converted, rounded, clipped, normalized, weighted,
    or unit-converted), the observation count, and the exact finite
    derived descriptive statistics (minimum, maximum, arithmetic mean,
    median, population standard deviation). The observed collection is
    non-empty because campaigns have at least one shared seed, the
    count must equal the collection length, minimum and maximum must
    equal the exact observed extrema, all derived statistics must be
    finite, and a single observation has population standard deviation
    exactly ``0.0``.

    The summary is descriptive statistics only: it ranks nothing,
    scores nothing, declares no winner, compares nothing against
    objectives or targets, creates no pass/fail judgment, and produces
    no outcomes, evidence, recommendations, or decision briefs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_position: int = Field(ge=0)
    metric_position: int = Field(ge=0)
    strategy_candidate_id: IdentifierString
    metric_id: IdentifierString
    metric_unit: str | None = None
    ordered_observed_values: tuple[int | float, ...] = Field(min_length=1)
    observation_count: int = Field(ge=1)
    minimum: float
    maximum: float
    arithmetic_mean: float
    median: float
    population_standard_deviation: float

    @model_validator(mode="before")
    @classmethod
    def _observed_values_must_be_exact_finite_numeric(cls, data: Any) -> Any:
        """Reject non-numeric observed values on the raw input, before any coercion.

        Pydantic lax mode would otherwise coerce booleans into integers
        or numbers and strings into numbers; checking the un-coerced
        input keeps booleans, strings, ``None``, containers, and
        non-finite floats out of ``ordered_observed_values``.
        """
        if not isinstance(data, dict):
            return data
        raw_values = data.get("ordered_observed_values")
        if isinstance(raw_values, (list, tuple)):
            for value in raw_values:
                if not _is_exact_finite_numeric(value):
                    raise ValueError("ordered_observed_values must be exact finite numeric values")
        return data

    @model_validator(mode="after")
    def _statistics_are_consistent(self) -> CampaignStrategyMetricStatistics:
        """Enforce the exact summary consistency rules.

        The observation count must equal the collection length; minimum
        and maximum must equal the exact observed extrema; every derived
        statistic must be finite; and a single observation has population
        standard deviation exactly ``0.0``. The exact mean/median/
        standard-deviation computation itself lives in the pure Phase 22
        builder, which defines the one deterministic algorithm centrally.
        """
        if self.observation_count != len(self.ordered_observed_values):
            raise ValueError("observation_count must equal len(ordered_observed_values)")
        if self.minimum != min(self.ordered_observed_values):
            raise ValueError("minimum must equal the exact observed minimum")
        if self.maximum != max(self.ordered_observed_values):
            raise ValueError("maximum must equal the exact observed maximum")
        for derived in (
            self.arithmetic_mean,
            self.median,
            self.population_standard_deviation,
        ):
            if not math.isfinite(derived):
                raise ValueError("derived statistics must be finite")
        if len(self.ordered_observed_values) == 1 and self.population_standard_deviation != 0.0:
            raise ValueError("single-observation population standard deviation must be exactly 0.0")
        return self


class CampaignMetricStatisticsMatrix(VersionedContract):
    """The deterministic descriptive-statistics matrix of one completed 2.0.0 campaign.

    The complete strategy x metric descriptive-statistics summary of a
    completed runtime-2.0.0 campaign, derived exclusively from its
    completely verified Phase 21 ``CampaignMetricObservationMatrix``:
    the campaign/scenario/world identity and world content hash, the
    trajectory runtime version (always ``"2.0.0"``), the comparison
    mode (always ``identical_conditions``), the statistics mode (always
    ``descriptive``), the exact source matrix reference (deterministic
    identifier and content hash), the exact ordered strategy, seed, and
    metric identifiers, and the complete summary tuple in the exact
    strategy-major, metric-minor order - every strategy has exactly one
    summary for every metric, and an empty metric collection requires
    empty summaries. ``summarized_at`` is the authoritative Phase 21
    matrix ``assembled_at`` - never the wall clock - and the identifier
    is deterministic from the campaign identity, the world identity,
    the runtime version, and the source matrix identity.

    The matrix is descriptive statistics only: it never ranks or scores
    strategies, declares a winner, compares against objectives or
    targets, creates pass/fail judgments, produces ``MetricOutcome`` or
    ``OutcomeVector``, creates evidence or ``DecisionBrief``, produces
    recommendations, interprets domain meaning, normalizes or converts
    units, samples uncertainty, or executes, replays, or extracts
    anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["2.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    statistics_mode: Literal["descriptive"]
    source_metric_observation_matrix_id: IdentifierString
    source_metric_observation_matrix_content_hash: Sha256Hex
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_metric_ids: tuple[IdentifierString, ...]
    summaries: tuple[CampaignStrategyMetricStatistics, ...]
    content_hash: Sha256Hex
    summarized_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_statistics_shape(self) -> CampaignMetricStatisticsMatrix:
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        metric_ids = list(self.ordered_metric_ids)
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("ordered_metric_ids must be unique")
        if any(a >= b for a, b in zip(metric_ids, metric_ids[1:], strict=False)):
            raise ValueError("ordered_metric_ids must be strictly increasing")

        if not metric_ids:
            if self.summaries:
                raise ValueError("summaries must be empty when ordered_metric_ids is empty")
            return self

        expected_count = len(strategy_ids) * len(metric_ids)
        if len(self.summaries) != expected_count:
            raise ValueError("summaries must cover every strategy x metric pair exactly once")

        seen_pairs: set[tuple[int, int]] = set()
        for position, summary in enumerate(self.summaries):
            if summary.strategy_position >= len(strategy_ids):
                raise ValueError("summary strategy position out of range")
            if summary.metric_position >= len(metric_ids):
                raise ValueError("summary metric position out of range")
            pair = (summary.strategy_position, summary.metric_position)
            if pair in seen_pairs:
                raise ValueError("duplicate strategy x metric summary")
            seen_pairs.add(pair)
            expected_index = summary.strategy_position * len(metric_ids) + summary.metric_position
            if expected_index != position:
                raise ValueError(
                    "summaries must be contiguous in the exact strategy-major, metric-minor order"
                )
            if summary.strategy_candidate_id != strategy_ids[summary.strategy_position]:
                raise ValueError("summary strategy identity does not match its strategy position")
            if summary.metric_id != metric_ids[summary.metric_position]:
                raise ValueError("summary metric identity does not match its metric position")
            if len(summary.ordered_observed_values) != len(seed_ids):
                raise ValueError("summary ordered_observed_values length must equal the seed count")
        return self
