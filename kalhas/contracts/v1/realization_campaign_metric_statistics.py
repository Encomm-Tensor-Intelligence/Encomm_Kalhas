"""Realization-aware campaign metric statistics contracts (Phase 25).

Phase 25 introduces the **deterministic realization-aware campaign
metric-statistics matrix**: an immutable, tenant-scoped,
descriptive-statistics artifact derived exclusively from one completely
verified Phase 25 ``RealizationCampaignMetricObservationMatrix`` of a
completed runtime-3.0.0 campaign. The pipeline is

    verified RealizationCampaignMetricObservationMatrix
        -> exact per-strategy/per-metric seed observations
        -> deterministic descriptive statistics

The summary values reuse the Phase 22 ``CampaignStrategyMetricStatistics``
contract unchanged (its shipped semantics - exact ordered raw observed
values preserved in seed order, observation count, and the exact finite
derived descriptive statistics minimum/maximum/arithmetic mean/median/
population standard deviation - remain exactly true under runtime 3.0.0).

``RealizationCampaignMetricStatisticsMatrix`` is the immutable aggregate:
the campaign, scenario, and world identity with the world content hash;
the realization trajectory runtime version (always ``"3.0.0"``), the
comparison mode (always ``identical_conditions``), and the statistics mode
(always ``descriptive``); the exact verified source
``RealizationCampaignMetricObservationMatrix`` reference (deterministic
identifier and content hash); the exact ordered strategy candidate,
scenario seed, and metric identifiers; the seed-aligned world-realization
identity/hash tuples; the complete summary tuple in the exact
strategy-major, metric-minor order; the self-covering ``content_hash``;
and the deterministic ``summarized_at`` taken from the authoritative
Phase 25 matrix ``assembled_at`` - never the wall clock. Its identifier is
deterministic from the campaign identity, the world identity, the runtime
version, and the source matrix identity.

The contract enforces the structural shape: unique and non-empty
strategy/seed identifiers; unique and strictly increasing metric
identifiers; the seed-aligned realization tuples exactly one entry per
seed; summaries in the exact strategy-major/metric-minor order with
contiguous positions and exact identity-vs-position agreement; every
summary's observed-value length equal to the seed count; and the complete
strategy x metric Cartesian product present exactly once.
Authoritative identity, hash, provenance, and raw-value verification
against the verified Phase 25 matrix remains in the application layer
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

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.campaign_metric_statistics import CampaignStrategyMetricStatistics
from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The statistics matrix runtime version literal; must stay equal to the
#: authoritative ``REALIZATION_TRAJECTORY_RUNTIME_VERSION`` constant
#: (asserted by the Phase 25 boundary tests).
REALIZATION_STATISTICS_MATRIX_RUNTIME_VERSION_LITERAL = "3.0.0"


class RealizationCampaignMetricStatisticsMatrix(VersionedContract):
    """The deterministic realization-aware descriptive-statistics matrix of one completed
    3.0.0 campaign.

    The complete strategy x metric descriptive-statistics summary of a
    completed runtime-3.0.0 campaign, derived exclusively from its
    completely verified Phase 25 ``RealizationCampaignMetricObservationMatrix``:
    the campaign/scenario/world identity and world content hash, the
    realization trajectory runtime version (always ``"3.0.0"``), the
    comparison mode (always ``identical_conditions``), the statistics mode
    (always ``descriptive``), the exact source matrix reference
    (deterministic identifier and content hash), the exact ordered
    strategy, seed, and metric identifiers, the seed-aligned
    world-realization identity/hash tuples, and the complete summary tuple
    in the exact strategy-major, metric-minor order - every strategy has
    exactly one summary for every metric, and an empty metric collection
    requires empty summaries. ``summarized_at`` is the authoritative Phase
    25 matrix ``assembled_at`` - never the wall clock - and the identifier
    is deterministic from the campaign identity, the world identity, the
    runtime version, and the source matrix identity.

    The matrix is descriptive statistics only: it never ranks or scores
    strategies, declares a winner, compares against objectives or targets,
    creates pass/fail judgments, produces ``MetricOutcome`` or
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
    runtime_version: Literal["3.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    statistics_mode: Literal["descriptive"]
    source_metric_observation_matrix_id: IdentifierString
    source_metric_observation_matrix_content_hash: Sha256Hex
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_metric_ids: tuple[IdentifierString, ...]
    ordered_world_realization_ids: tuple[IdentifierString, ...]
    ordered_world_realization_content_hashes: tuple[Sha256Hex, ...]
    summaries: tuple[CampaignStrategyMetricStatistics, ...]
    content_hash: Sha256Hex
    summarized_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_statistics_shape(self) -> RealizationCampaignMetricStatisticsMatrix:
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
        realization_ids = list(self.ordered_world_realization_ids)
        if len(realization_ids) != len(set(realization_ids)):
            raise ValueError("ordered_world_realization_ids must be unique")
        if len(realization_ids) != len(seed_ids):
            raise ValueError("ordered_world_realization_ids must have exactly one entry per seed")
        if len(self.ordered_world_realization_content_hashes) != len(seed_ids):
            raise ValueError(
                "ordered_world_realization_content_hashes must have exactly one entry per seed"
            )

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
