"""Realization-aware campaign trajectory matrix contracts (Phase 25).

Phase 25 introduces the **deterministic realization-aware campaign
trajectory matrix**: the exact authoritative ``strategy x identical shared
seed`` run matrix of one completed runtime-3.0.0 campaign, assembled from
every verified Phase 25 ``RealizationRunTrajectoryExecution`` artifact of
that campaign into one immutable, self-hashing structural comparison
artifact.

The matrix mirrors the Phase 18 ``CampaignTrajectoryMatrix`` exactly and
adds the seed-aligned realization provenance: every cell carries the world
realization identity and content hash that supplied the run's realized
initial states, and the aggregate carries the complete ordered
``ordered_world_realization_ids`` / ``ordered_world_realization_content_hashes``
tuples (exactly one entry per seed, in exact seed-ensemble order, with
cell-to-tuple agreement enforced by the contract). The matrix is
**structural comparison provenance only**: it never ranks strategies,
never calculates scores, never interprets state values, and never produces
outcomes, evidence, or recommendations.

- ``RealizationCampaignTrajectoryRunCell`` is one run of the matrix: its
  sequence, strategy, and seed positions; the run and run-plan identity;
  the strategy and seed identities; the run input hash; the verified
  runtime-3 trajectory-execution artifact reference (deterministic
  identifier and content hash) with its exact ordered plan-set hash; the
  ordered result content hashes of that execution; and the world
  realization identity and content hash that supplied the realized
  initial states. The cell carries **references and integrity hashes
  only** - no state snapshots, no transition guards or target values, no
  strategy policy content, no outcome values, no evidence, no ranking or
  score, and no explanations or hidden reasoning.
- ``RealizationCampaignTrajectoryMatrix`` is the immutable aggregate:
  campaign, scenario, and world identity with the world content hash; the
  realization trajectory runtime version (always ``"3.0.0"``); the
  comparison mode (always ``identical_conditions``); the exact ordered
  strategy candidate identifiers and the exact ordered shared seed
  identifiers; the seed-aligned world-realization identity/hash tuples;
  the complete cell tuple in the exact authoritative RunPlan order
  (strategy-major, seed-minor); the self-covering ``content_hash``; and
  the deterministic ``assembled_at`` derived from the recorded campaign
  ``created_at`` - never the wall clock. Its identifier is deterministic
  from the campaign identity, the world identity, and the runtime version.

The contract enforces the structural shape: non-empty ordered strategy,
seed, and cell collections; unique strategy and seed identifiers; the
seed-aligned realization tuples exactly one entry per seed; the complete
Cartesian product present exactly once; every cell bound to its declared
strategy and seed position; cells in the exact RunPlan order; and every
cell's realization identity/hash agreeing with the seed-aligned tuples.
Authoritative identity and hash verification against the stored RunPlan,
``RealizationRunTrajectoryExecution``, and world-realization records
remains in the application layer (the pure matrix builder and the verified
query service).

Nothing here loads, imports, instantiates, or executes a domain pack,
and no field type can express a callback, expression, formula, code
reference, provider, or executable mechanism.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The realization trajectory runtime version this matrix describes. Kept
#: as a literal so the matrix can never record any other runtime version.
REALIZATION_TRAJECTORY_MATRIX_RUNTIME_VERSION_LITERAL = "3.0.0"


class RealizationCampaignTrajectoryRunCell(BaseModel):
    """One run of the deterministic realization-aware campaign trajectory matrix.

    A pure structural reference cell: the run's sequence, strategy, and
    seed positions; the run and run-plan identity; the strategy and seed
    identities; the run input hash; the verified runtime-3
    trajectory-execution artifact reference (deterministic identifier and
    content hash) with its exact ordered plan-set hash; the ordered result
    content hashes of that execution; and the world realization identity
    and content hash that supplied the run's realized initial states. It
    carries no state snapshots, no transition guards or target values, no
    strategy policy content, no outcome values, no evidence, no ranking or
    score, and no explanations or hidden reasoning.
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
    realization_run_trajectory_execution_id: IdentifierString
    realization_run_trajectory_execution_content_hash: Sha256Hex
    trajectory_plan_set_hash: Sha256Hex
    result_content_hashes: tuple[Sha256Hex, ...]
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex


class RealizationCampaignTrajectoryMatrix(VersionedContract):
    """The deterministic realization-aware trajectory matrix of one completed 3.0.0 campaign.

    The complete Cartesian product of the campaign's ordered strategy
    candidates and its ordered shared seed ensemble, in the exact
    authoritative RunPlan order (strategy-major, seed-minor): every
    strategy appears once for every seed, every strategy receives the
    identical ordered seed identifiers and the identical seed-aligned
    world realizations, and every cell binds to its exact stored RunPlan,
    verified ``RealizationRunTrajectoryExecution``, and seed-aligned world
    realization. The matrix is a structural comparison artifact only - it
    never ranks strategies, never interprets state values, and never
    produces outcomes, evidence, or recommendations. ``assembled_at`` is
    derived from the recorded campaign ``created_at`` - never the wall
    clock - and the identifier is deterministic from the campaign
    identity, the world identity, and the runtime version.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    comparison_mode: Literal["identical_conditions"] = "identical_conditions"
    ordered_strategy_candidate_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    ordered_world_realization_ids: tuple[IdentifierString, ...]
    ordered_world_realization_content_hashes: tuple[Sha256Hex, ...]
    cells: tuple[RealizationCampaignTrajectoryRunCell, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    assembled_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_matrix_shape(self) -> RealizationCampaignTrajectoryMatrix:
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        realization_ids = list(self.ordered_world_realization_ids)
        if len(realization_ids) != len(set(realization_ids)):
            raise ValueError("ordered_world_realization_ids must be unique")
        if len(realization_ids) != len(seed_ids):
            raise ValueError("ordered_world_realization_ids must have exactly one entry per seed")
        if len(self.ordered_world_realization_content_hashes) != len(seed_ids):
            raise ValueError(
                "ordered_world_realization_content_hashes must have exactly one entry per seed"
            )

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
            if cell.world_realization_id != realization_ids[cell.seed_position]:
                raise ValueError("cell realization identity does not match its seed position")
            if (
                cell.world_realization_content_hash
                != self.ordered_world_realization_content_hashes[cell.seed_position]
            ):
                raise ValueError("cell realization content hash does not match its seed position")
        return self
