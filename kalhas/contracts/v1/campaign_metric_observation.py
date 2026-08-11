"""Campaign metric-observation matrix contracts: deterministic comparison-ready raw observations.

Phase 21 introduces the **deterministic campaign metric-observation
matrix**: the exact authoritative ``strategy candidate x identical shared
seed`` observation layout of one completed runtime-2.0.0 campaign,
assembled from every completely verified Phase 20 ``RunMetricObservationSet``
of that campaign - the layout already proven by the Phase 18
``CampaignTrajectoryMatrix`` - into one immutable, self-hashing,
comparison-ready artifact of **exact raw observations and provenance
only**.

- ``CampaignMetricObservationCell`` is one authoritative campaign run of
  the matrix: its sequence, strategy, and seed positions; the run and
  run-plan identity; the strategy and seed identities; the run input
  hash; the verified trajectory-execution reference (deterministic
  identifier and content hash); the verified Phase 20
  ``RunMetricObservationSet`` reference (deterministic identifier and
  content hash); and the exact ordered tuple of Phase 20
  ``RunMetricObservationValue`` records - the raw values are reused
  directly, never duplicated, converted, or interpreted.
- ``CampaignMetricObservationMatrix`` is the immutable aggregate:
  campaign, scenario, and world identity with the world content hash;
  the trajectory runtime version (always ``"2.0.0"``); the comparison
  mode (always ``identical_conditions``); the exact ordered strategy
  candidate identifiers, the exact ordered shared seed identifiers, and
  the exact ordered metric identifiers; the complete cell tuple in the
  exact authoritative RunPlan order (strategy-major, seed-minor); the
  self-covering ``content_hash``; and the deterministic ``assembled_at``
  derived from the recorded campaign ``created_at`` - never the wall
  clock. Its identifier is deterministic from the campaign identity,
  the world identity, and the runtime version.

The matrix is **comparison-ready raw observation provenance only**. It
performs no statistical aggregation of any kind (no averages, sums,
minima, maxima, distributions, confidence intervals, or uncertainty),
creates no ``MetricOutcome`` or ``OutcomeVector``, scores or ranks no
strategy, decides nothing about which strategy is better, and produces
no evidence, recommendations, or ``DecisionBrief``. Nothing here
normalizes, transforms, or converts units, and nothing extracts missing
Phase 20 artifacts.

The contract enforces the structural shape: non-empty ordered strategy,
seed, and cell collections; unique strategy and seed identifiers;
``ordered_metric_ids`` unique and strictly increasing (empty only when
every cell's observations are empty); the complete Cartesian product
present exactly once; every cell bound to its declared strategy and seed
position; cells in the exact RunPlan order; and every cell's observation
metric identifiers equal to ``ordered_metric_ids`` exactly and in the
same order - duplicate, reordered, missing, or additional cells or
observations are rejected. Authoritative identity, hash, and binding-
provenance verification against the stored records remains in the
application layer (the pure matrix builder and the verified query
service).

Nothing here loads, imports, instantiates, or executes a domain pack,
and no field type can express a callback, expression, formula, code
reference, provider, or executable mechanism.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.run_metric_observation import RunMetricObservationValue
from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The trajectory runtime version this matrix describes. Kept as a
#: literal so the matrix can never record any other runtime version.
METRIC_OBSERVATION_MATRIX_RUNTIME_VERSION_LITERAL = "2.0.0"


class CampaignMetricObservationCell(BaseModel):
    """One authoritative campaign run of the metric-observation matrix.

    A pure comparison cell: the run's sequence, strategy, and seed
    positions; the run and run-plan identity; the strategy and seed
    identities; the run input hash; the verified trajectory-execution
    reference (deterministic identifier and content hash); the verified
    Phase 20 ``RunMetricObservationSet`` reference (deterministic
    identifier and content hash); and the exact ordered tuple of Phase
    20 ``RunMetricObservationValue`` records - raw values and provenance
    preserved exactly, never aggregated, normalized, converted, or
    interpreted. It carries no state snapshots, no transition guards or
    target values, no strategy policy content, no outcomes, no
    evidence, no ranking or score, and no explanations or hidden
    reasoning.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    strategy_position: int = Field(ge=0)
    seed_position: int = Field(ge=0)
    run_id: IdentifierString
    run_plan_id: IdentifierString
    strategy_candidate_id: IdentifierString
    scenario_seed_id: IdentifierString
    input_hash: Sha256Hex
    trajectory_execution_id: IdentifierString
    trajectory_execution_content_hash: Sha256Hex
    metric_observation_set_id: IdentifierString
    metric_observation_set_content_hash: Sha256Hex
    observations: tuple[RunMetricObservationValue, ...]


class CampaignMetricObservationMatrix(VersionedContract):
    """The deterministic campaign metric-observation matrix of one completed 2.0.0 campaign.

    The complete Cartesian product of the campaign's ordered strategy
    candidates and its ordered shared seed ensemble, in the exact
    authoritative RunPlan order (strategy-major, seed-minor): every
    strategy appears once for every seed, every strategy receives the
    identical ordered seed identifiers, and every cell carries the
    verified Phase 20 ``RunMetricObservationSet`` reference and the
    exact raw observation values of its run. The matrix is a
    comparison-ready raw observation and provenance artifact only - it
    never aggregates observations, calculates outcomes or
    distributions, scores or ranks strategies, decides that one
    strategy is better, or produces evidence, recommendations, or
    decision briefs. ``assembled_at`` is derived from the recorded
    campaign ``created_at`` - never the wall clock - and the identifier
    is deterministic from the campaign identity, the world identity,
    and the runtime version.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["2.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_metric_ids: tuple[IdentifierString, ...]
    cells: tuple[CampaignMetricObservationCell, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    assembled_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_matrix_shape(self) -> CampaignMetricObservationMatrix:
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

        expected_count = len(strategy_ids) * len(seed_ids)
        if len(self.cells) != expected_count:
            raise ValueError("cells must cover the complete strategy x seed matrix exactly")

        seen_pairs: set[tuple[int, int]] = set()
        previous_pair: tuple[int, int] | None = None
        for position, cell in enumerate(self.cells):
            if cell.sequence_position != position:
                raise ValueError("cell sequence positions must be contiguous from zero")
            if cell.strategy_position >= len(strategy_ids):
                raise ValueError("cell strategy position out of range")
            if cell.seed_position >= len(seed_ids):
                raise ValueError("cell seed position out of range")
            pair = (cell.strategy_position, cell.seed_position)
            if pair in seen_pairs:
                raise ValueError("duplicate strategy x seed cell")
            seen_pairs.add(pair)
            if previous_pair is not None and pair <= previous_pair:
                raise ValueError(
                    "cells must be in the exact RunPlan order (strategy-major, seed-minor)"
                )
            previous_pair = pair
            if cell.strategy_candidate_id != strategy_ids[cell.strategy_position]:
                raise ValueError("cell strategy identity does not match its strategy position")
            if cell.scenario_seed_id != seed_ids[cell.seed_position]:
                raise ValueError("cell seed identity does not match its seed position")
            cell_metric_ids = [observation.metric_id for observation in cell.observations]
            if cell_metric_ids != metric_ids:
                raise ValueError(
                    "cell observations must carry exactly the ordered metric identifiers"
                )
        return self
