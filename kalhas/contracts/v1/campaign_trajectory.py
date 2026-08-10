"""Campaign trajectory matrix contracts: deterministic structural comparison provenance.

Phase 18 introduces the **deterministic campaign trajectory matrix**: the
exact authoritative ``strategy x shared-seed`` run matrix of one completed
runtime-2.0.0 campaign, assembled from every verified Phase 16
``RunTrajectoryExecution`` artifact of that campaign into one immutable,
self-hashing structural comparison artifact.

The matrix is **structural comparison provenance only**. It proves that
every strategy was executed under the campaign's identical ordered seed
conditions and provides verified references and integrity hashes for every
run. It never ranks strategies, never calculates scores, never interprets
state values, and never produces outcomes, evidence, or recommendations -
no claim that one strategy is better is expressible here.

- ``CampaignTrajectoryRunCell`` is one run of the matrix: its sequence,
  strategy, and seed positions; the run and run-plan identity; the
  strategy and seed identities; the run input hash; the verified
  trajectory-execution artifact reference (deterministic identifier and
  content hash) with its exact ordered plan-set hash; and the ordered
  result content hashes of that execution, preserved exactly. The cell
  carries **references and integrity hashes only** - no state snapshots,
  no transition guards or target values, no strategy policy content, no
  outcome values, no evidence, no ranking or score, and no explanations
  or hidden reasoning.
- ``CampaignTrajectoryMatrix`` is the immutable aggregate: campaign,
  scenario, and world identity with the world content hash; the
  trajectory runtime version (always ``2.0.0``); the comparison mode
  (always ``identical_conditions``); the exact ordered strategy
  candidate identifiers and the exact ordered shared seed identifiers;
  the complete cell tuple in the exact authoritative RunPlan order
  (strategy-major, seed-minor - every strategy once for every seed,
  with the identical ordered seed identifiers); the self-covering
  ``content_hash``; and the deterministic ``assembled_at`` derived from
  the recorded campaign ``created_at`` - never the wall clock. Its
  identifier is deterministic from the campaign identity, the world
  identity, and the runtime version.

The contract enforces the structural shape: non-empty ordered strategy,
seed, and cell collections; unique strategy and seed identifiers; the
complete Cartesian product present exactly once; every cell bound to its
declared strategy and seed position; and cells in the exact RunPlan
order. Authoritative identity and hash verification against the stored
RunPlan and RunTrajectoryExecution records remains in the application
layer (the pure matrix builder and the verified query service).

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

#: The trajectory runtime version this matrix describes. Kept as a
#: literal so the matrix can never record any other runtime version.
TRAJECTORY_MATRIX_RUNTIME_VERSION_LITERAL = "2.0.0"


class CampaignTrajectoryRunCell(BaseModel):
    """One run of the deterministic campaign trajectory matrix.

    A pure structural reference cell: the run's sequence, strategy, and
    seed positions; the run and run-plan identity; the strategy and seed
    identities; the run input hash; the verified trajectory-execution
    artifact reference (deterministic identifier and content hash) with
    the execution's exact ordered plan-set hash; and the ordered result
    content hashes of that execution, preserved exactly. It carries no
    state snapshots, no transition guards or target values, no strategy
    policy content, no outcome values, no evidence, no ranking or score,
    and no explanations or hidden reasoning.
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
    trajectory_plan_set_hash: Sha256Hex
    result_content_hashes: tuple[Sha256Hex, ...]


class CampaignTrajectoryMatrix(VersionedContract):
    """The deterministic campaign trajectory matrix of one completed 2.0.0 campaign.

    The complete Cartesian product of the campaign's ordered strategy
    candidates and its ordered shared seed ensemble, in the exact
    authoritative RunPlan order (strategy-major, seed-minor): every
    strategy appears once for every seed, every strategy receives the
    identical ordered seed identifiers, and every cell binds to its
    exact stored RunPlan and verified ``RunTrajectoryExecution``. The
    matrix is a structural comparison artifact only - it never ranks
    strategies, never interprets state values, and never produces
    outcomes, evidence, or recommendations. ``assembled_at`` is derived
    from the recorded campaign ``created_at`` - never the wall clock -
    and the identifier is deterministic from the campaign identity, the
    world identity, and the runtime version.
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
    cells: tuple[CampaignTrajectoryRunCell, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    assembled_at: AwareDatetime

    @model_validator(mode="after")
    def _structural_matrix_shape(self) -> CampaignTrajectoryMatrix:
        strategy_ids = list(self.ordered_strategy_candidate_ids)
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("ordered_strategy_candidate_ids must be unique")
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")

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
        return self
