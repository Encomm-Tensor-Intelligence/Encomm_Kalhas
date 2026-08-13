"""Realization-aware run trajectory execution contracts (Phase 25).

Phase 25 introduces **deterministic realization-aware trajectory execution
and observation-aware exact replay** for runtime version 3.0.0 campaigns.
These contracts record the complete evaluated trajectory of every applicable
strategy trajectory plan of one run - executed from the realized initial
state produced by the Phase 24 world realization of the run's recorded
seed - as one immutable, self-hashing artifact, plus the self-hashing
provenance manifest of an exact, observation-aware replay of that artifact.

The boundary is strict and declarative end to end:

- ``RealizedStateTrajectoryResult`` is one evaluated state-model plan: the
  exact plan identity and content hash, the resolved state-model identity
  and content hash, fresh plain JSON snapshots of the realized initial and
  final states with their hashes, the ordered attempt records, the engine's
  deterministic trace hash, and a self-covering ``content_hash`` over the
  complete canonical result excluding ``content_hash`` itself. It mirrors
  the Phase 16 ``RunStateTrajectoryResult`` exactly - the realized initial
  state and its hash are authoritative under runtime 3.0.0.
- ``RealizationRunTrajectoryExecution`` is the immutable aggregate artifact
  of one completed runtime-3.0.0 run: run/campaign/plan identity, the
  verified world and strategy identities with their content hashes, the
  recorded seed identity, the exact world realization identity and content
  hash (the seed's realized initial state), the realization trajectory
  runtime version (exactly ``"3.0.0"``), the run input hash, the exact
  ordered plan-set hash, the ordered result tuple, the aggregate content
  hash, and the deterministic ``executed_at`` from the recorded RunPlan
  creation time. Its identifier is deterministic from the run identity and
  runtime version.
- ``RealizationRunTrajectoryReplayManifest`` attests one exact
  observation-aware replay: it binds the replay to the stored runtime-3
  execution artifact and the stored runtime-3 metric-observation set,
  records that the independently regenerated execution hash equals the
  recorded expected execution hash and that the regenerated observation
  set hash equals the recorded expected observation set hash, with
  ``replay_classification`` always ``"exact"`` and a deterministic
  ``replayed_at``. Its ``content_hash`` is **self-covering**: it is the
  canonical digest over the complete payload excluding ``content_hash``
  itself, so every field - including the observation-set identity and
  hashes - is covered.

Nothing here loads, imports, instantiates, or executes a domain pack,
and no field type can express a callback, expression, formula, code
reference, provider, or executable mechanism.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The realization trajectory runtime version these contracts describe.
#: Kept as a literal so a contract can never record any other runtime
#: version.
REALIZATION_TRAJECTORY_RUNTIME_VERSION_LITERAL = "3.0.0"


class RealizedStateTrajectoryResult(BaseModel):
    """The immutable evaluated result of one state-model plan under a realized initial state.

    Mirrors the Phase 16 ``RunStateTrajectoryResult`` exactly: binds the
    result to its exact ``StrategyTrajectoryPlan`` (identifier and content
    hash) and to the exact resolved state model embedded in the verified
    compiled world (manifest, deterministic model identifier, logical model
    id, and content hash). The initial and final states are fresh plain
    JSON snapshots (never the engine's frozen views and never references
    into the model, the realization, or the world), with their canonical
    hashes; the initial state is the **realized** initial state supplied
    from the Phase 24 world realization, so its hash is the authoritative
    runtime-3 initial-state hash. The ordered attempt records, the engine's
    deterministic trace hash, and a self-covering ``content_hash`` over the
    complete canonical result excluding ``content_hash`` itself complete
    the record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trajectory_plan_id: str
    trajectory_plan_content_hash: Sha256Hex
    manifest_id: str
    state_model_identifier: str
    state_model_id: str
    state_model_content_hash: Sha256Hex
    initial_state: dict[str, JsonValue]
    initial_state_hash: Sha256Hex
    attempts: tuple[RunTrajectoryAttemptRecord, ...]
    final_state: dict[str, JsonValue]
    final_state_hash: Sha256Hex
    trace_hash: Sha256Hex
    content_hash: Sha256Hex


class RealizationRunTrajectoryExecution(VersionedContract):
    """The immutable run-scoped realization-aware trajectory execution artifact.

    One aggregate artifact per completed runtime-3.0.0 run: the run,
    campaign, and run-plan identity; the verified compiled world and the
    exact recorded strategy with their content hashes; the recorded seed
    identity; the exact world realization identity and content hash that
    supplied the realized initial states; the realization trajectory
    runtime version (exactly ``"3.0.0"``); the run input hash (the
    runtime-3 digest, covering the realization content hash); the exact
    ordered plan-set hash; the ordered result tuple (one per applicable
    state-model plan, in canonical order); the aggregate ``content_hash``;
    and the deterministic ``executed_at`` from the recorded RunPlan
    creation time - never the wall clock. The identifier is deterministic
    from the run identity and runtime version. An empty results tuple is
    valid only for a verified world with no transition-capable state
    models.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: IdentifierString
    campaign_id: IdentifierString
    run_plan_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    strategy_candidate_id: IdentifierString
    strategy_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    input_hash: Sha256Hex
    trajectory_plan_set_hash: Sha256Hex
    results: tuple[RealizedStateTrajectoryResult, ...]
    content_hash: Sha256Hex
    executed_at: AwareDatetime


class RealizationRunTrajectoryReplayManifest(VersionedContract):
    """Provenance manifest of an exact observation-aware replay of a realization execution.

    Binds the replay to the run, campaign, and the stored runtime-3
    ``RealizationRunTrajectoryExecution`` artifact (by its deterministic
    identifier), records the verified world/strategy/seed identities, the
    exact world realization identity and content hash, the realization
    trajectory runtime version, the run input hash, and the exact ordered
    plan-set hash, and attests that the independently regenerated execution
    hash equals the recorded expected execution hash and that the
    independently regenerated runtime-3 metric-observation set hash equals
    the recorded expected observation-set hash - with
    ``replay_classification`` always ``"exact"``. ``replayed_at`` is
    deterministic (the recorded RunPlan creation time) - never the wall
    clock. The ``content_hash`` is self-covering: it is the canonical
    digest over the complete payload excluding ``content_hash`` itself, so
    tampering any field - including the observation-set reference and
    hashes - fails the recompute at every trust boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: IdentifierString
    campaign_id: IdentifierString
    realization_run_trajectory_execution_id: IdentifierString
    realization_run_metric_observation_set_id: IdentifierString
    world_version_id: IdentifierString
    strategy_candidate_id: IdentifierString
    scenario_seed_id: IdentifierString
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    input_hash: Sha256Hex
    trajectory_plan_set_hash: Sha256Hex
    expected_execution_hash: Sha256Hex
    recomputed_execution_hash: Sha256Hex
    expected_observation_set_hash: Sha256Hex
    recomputed_observation_set_hash: Sha256Hex
    replay_classification: Literal["exact"] = "exact"
    replayed_at: AwareDatetime
    content_hash: Sha256Hex
