"""Run trajectory execution contracts: immutable run-scoped execution artifacts.

Phase 16 introduces **deterministic run trajectory execution and exact
replay** for runtime version 2.0.0 campaigns. These contracts record the
complete evaluated trajectory of every applicable strategy trajectory
plan of one run - the resolved state-model snapshots, the ordered
transition attempts with their before/after state hashes, and the final
state - as one immutable, self-hashing artifact, plus the provenance
manifest of an exact replay of that artifact.

The boundary is strict and declarative end to end:

- ``RunTrajectoryAttemptRecord`` is one authoritative attempt record: its
  sequence position, the referenced transition's deterministic
  identifier, logical transition id, and content hash, the deterministic
  outcome (``applied`` or ``guard_not_satisfied``), and the
  before/after state hashes. It carries **no guard values, no target
  values, no state snapshots, no explanations, no evidence, no
  recommendations, and no executable behavior**.
- ``RunStateTrajectoryResult`` is one evaluated state-model plan: the
  exact plan identity and content hash, the resolved state-model identity
  and content hash, fresh plain JSON snapshots of the initial and final
  states with their hashes, the ordered attempt records, the engine's
  deterministic trace hash, and a self-covering ``content_hash`` over the
  complete canonical result excluding ``content_hash`` itself.
- ``RunTrajectoryExecution`` is the immutable aggregate artifact of one
  completed run: run/campaign/plan identity, the verified world and
  strategy identities with their content hashes, the recorded seed
  identity (recorded provenance only - the declarative transition kernel
  does not sample uncertainty), the trajectory runtime version, the run
  input hash, the exact ordered plan-set hash, the ordered result tuple,
  the aggregate content hash, and the deterministic ``executed_at`` from
  the recorded RunPlan creation time. Its identifier is deterministic
  from the run identity and runtime version. An empty results tuple is
  valid only for a verified world with no transition-capable state
  models.
- ``RunTrajectoryReplayManifest`` attests one exact replay: it binds the
  replay to the stored execution artifact and records that the
  independently regenerated execution hash equals the recorded expected
  execution hash, with ``replay_classification`` always ``"exact"`` and
  a deterministic ``replayed_at``.

Nothing here loads, imports, instantiates, or executes a domain pack,
and no field type can express a callback, expression, formula, code
reference, provider, or executable mechanism.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: The trajectory runtime version these contracts describe. Kept as a
#: literal so a contract can never record any other runtime version.
TRAJECTORY_RUNTIME_VERSION_LITERAL = "2.0.0"


class RunTrajectoryAttemptRecord(BaseModel):
    """One deterministic transition attempt within an evaluated trajectory.

    Records only the attempt's sequence position, the authoritative
    reference to the attempted transition (deterministic identifier,
    logical transition id, content hash), the deterministic outcome, and
    the before/after state hashes. It carries no guard or target values,
    no state snapshots, no explanation, no evidence, no recommendation,
    and no hidden reasoning.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    transition_identifier: str
    transition_id: str = Field(min_length=1)
    transition_content_hash: str = Field(pattern=_SHA256_PATTERN)
    outcome: Literal["applied", "guard_not_satisfied"]
    before_state_hash: str = Field(pattern=_SHA256_PATTERN)
    after_state_hash: str = Field(pattern=_SHA256_PATTERN)


class RunStateTrajectoryResult(BaseModel):
    """The immutable evaluated result of one state-model plan.

    Binds the result to its exact ``StrategyTrajectoryPlan`` (identifier
    and content hash) and to the exact resolved state model embedded in
    the verified compiled world (manifest, deterministic model
    identifier, logical model id, and content hash). The initial and
    final states are fresh plain JSON snapshots (never the engine's
    frozen views and never references into the model or the world), with
    their canonical hashes; the ordered attempt records, the engine's
    deterministic trace hash, and a self-covering ``content_hash`` over
    the complete canonical result excluding ``content_hash`` itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trajectory_plan_id: str
    trajectory_plan_content_hash: str = Field(pattern=_SHA256_PATTERN)
    manifest_id: str
    state_model_identifier: str
    state_model_id: str
    state_model_content_hash: str = Field(pattern=_SHA256_PATTERN)
    initial_state: dict[str, JsonValue]
    initial_state_hash: str = Field(pattern=_SHA256_PATTERN)
    attempts: tuple[RunTrajectoryAttemptRecord, ...]
    final_state: dict[str, JsonValue]
    final_state_hash: str = Field(pattern=_SHA256_PATTERN)
    trace_hash: str = Field(pattern=_SHA256_PATTERN)
    content_hash: str = Field(pattern=_SHA256_PATTERN)


class RunTrajectoryExecution(VersionedContract):
    """The immutable run-scoped trajectory execution artifact.

    One aggregate artifact per completed trajectory-runtime run: the run,
    campaign, and run-plan identity; the verified compiled world and the
    exact recorded strategy with their content hashes; the recorded seed
    identity (provenance only - the declarative transition kernel never
    samples or uses the seed); the trajectory runtime version; the run
    input hash; the exact ordered plan-set hash; the ordered result tuple
    (one per applicable state-model plan, in canonical order); the
    aggregate ``content_hash``; and the deterministic ``executed_at``
    from the recorded RunPlan creation time - never the wall clock. The
    identifier is deterministic from the run identity and runtime
    version. An empty results tuple is valid only for a verified world
    with no transition-capable state models.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    campaign_id: str
    run_plan_id: str
    world_version_id: str
    world_content_hash: str = Field(pattern=_SHA256_PATTERN)
    strategy_candidate_id: str
    strategy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    scenario_seed_id: str
    runtime_version: Literal["2.0.0"]
    input_hash: str = Field(pattern=_SHA256_PATTERN)
    trajectory_plan_set_hash: str = Field(pattern=_SHA256_PATTERN)
    results: tuple[RunStateTrajectoryResult, ...]
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    executed_at: AwareDatetime


class RunTrajectoryReplayManifest(VersionedContract):
    """Provenance manifest of an exact replay of a trajectory execution.

    Binds the replay to the run, campaign, and the stored
    ``RunTrajectoryExecution`` artifact (by its deterministic
    identifier), records the verified world/strategy/seed identities, the
    trajectory runtime version, the run input hash, and the exact ordered
    plan-set hash, and attests that the independently regenerated
    execution hash equals the recorded expected execution hash with
    ``replay_classification`` always ``"exact"``. ``replayed_at`` is
    deterministic (the recorded RunPlan creation time) - never the wall
    clock.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    campaign_id: str
    run_trajectory_execution_id: str
    world_version_id: str
    strategy_candidate_id: str
    scenario_seed_id: str
    runtime_version: Literal["2.0.0"]
    input_hash: str = Field(pattern=_SHA256_PATTERN)
    trajectory_plan_set_hash: str = Field(pattern=_SHA256_PATTERN)
    expected_execution_hash: str = Field(pattern=_SHA256_PATTERN)
    recomputed_execution_hash: str = Field(pattern=_SHA256_PATTERN)
    replay_classification: Literal["exact"] = "exact"
    replayed_at: AwareDatetime
