"""Deterministic structural runtime.

Executes planned runs using only recorded in-memory inputs (immutable
WorldVersion, recorded StrategyCandidate, recorded ScenarioSeed, RunPlan,
recorded runtime version) and emits a fixed ordered stream of three
structural events per run. No Legion, no NEXUS, no provider, no model, no
random generator, no wall clock, no filesystem, no network.

This is a kernel proof only: COMPLETE means structural execution finished,
not that decision evidence was produced. No OutcomeVector, EvidenceReference,
DecisionBrief, metrics, recommendation state, or fake success probabilities
are ever generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter

from kalhas.application.domain_errors import (
    CampaignNotRunningError,
    MalformedWorldError,
    RunNotPlannedError,
    RunTrajectoryExecutionAlreadyExistsError,
    RunTrajectoryExecutionNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import VerifiedRunInputs, verify_run_inputs
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.run_trajectory_runtime import build_run_trajectory_execution
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.simulation import RunEvent, RunEventKind
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion

STRUCTURAL_EVENT_SEQUENCE = (0, 1, 2)
STRUCTURAL_EVENT_KINDS = (
    RunEventKind.RUN_STARTED,
    RunEventKind.STRATEGY_DECLARATION_RECORDED,
    RunEventKind.RUN_COMPLETED,
)

_horizon_adapter: TypeAdapter[AwareDatetime] = TypeAdapter(AwareDatetime)


def _horizon_bounds(world: WorldVersion) -> tuple[datetime, datetime]:
    """The scenario horizon embedded in the compiled world (start, end)."""
    scenario = world.world.get("scenario")
    if not isinstance(scenario, dict):
        raise MalformedWorldError(world.identifier)
    horizon = scenario.get("time_horizon")
    if not isinstance(horizon, dict):
        raise MalformedWorldError(world.identifier)
    start_raw = horizon.get("start")
    end_raw = horizon.get("end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise MalformedWorldError(world.identifier)
    try:
        start = _horizon_adapter.validate_python(start_raw)
        end = _horizon_adapter.validate_python(end_raw)
    except (TypeError, ValueError) as exc:
        raise MalformedWorldError(world.identifier) from exc
    return start, end


def structural_events(
    *,
    run_plan: RunPlan,
    world: WorldVersion,
    strategy: StrategyCandidate,
    seed: ScenarioSeed,
    run_id: str,
) -> tuple[RunEvent, ...]:
    """Regenerate the three ordered structural events from recorded inputs only.

    simulation_time: RUN_STARTED and STRATEGY_DECLARATION_RECORDED at the
    recorded horizon start, RUN_COMPLETED at the horizon end. created_at is
    the recorded run plan creation time - never the wall clock.
    """
    start, end = _horizon_bounds(world)
    created_at = run_plan.created_at

    def event(
        *,
        sequence: int,
        kind: RunEventKind,
        simulation_time: AwareDatetime,
        identifier: str,
        payload: dict[str, JsonValue],
    ) -> RunEvent:
        return RunEvent(
            identifier=identifier,
            tenant_id=run_plan.tenant_id,
            run_id=run_id,
            campaign_id=run_plan.campaign_id,
            world_version_id=run_plan.world_version_id,
            strategy_candidate_id=run_plan.strategy_candidate_id,
            scenario_seed_id=run_plan.scenario_seed_id,
            sequence=sequence,
            kind=kind,
            simulation_time=simulation_time,
            created_at=created_at,
            payload=payload,
        )

    return (
        event(
            sequence=0,
            kind=RunEventKind.RUN_STARTED,
            simulation_time=start,
            identifier=f"ev-{run_id}-0",
            payload={
                "runtime_version": run_plan.runtime_version,
                "run_plan_id": run_plan.identifier,
                "lifecycle": "planned -> running",
            },
        ),
        event(
            sequence=1,
            kind=RunEventKind.STRATEGY_DECLARATION_RECORDED,
            simulation_time=start,
            identifier=f"ev-{run_id}-1",
            payload={
                "runtime_version": run_plan.runtime_version,
                "strategy_version": strategy.strategy_version,
                "policy_summary": strategy.policy.summary,
            },
        ),
        event(
            sequence=2,
            kind=RunEventKind.RUN_COMPLETED,
            simulation_time=end,
            identifier=f"ev-{run_id}-2",
            payload={
                "runtime_version": run_plan.runtime_version,
                "lifecycle": "running -> complete",
                "event_count": 3,
            },
        ),
    )


def event_hash(events: tuple[RunEvent, ...]) -> str:
    """SHA-256 (lowercase, 64 hex) over the canonical ordered event stream."""
    canonical = canonical_json([event.model_dump(mode="json") for event in events])
    return sha256_hex(canonical)


@dataclass(frozen=True)
class RunExecution:
    """A completed structural execution of one run."""

    status: RunStatus
    events: tuple[RunEvent, ...]


def execute_run(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunExecution:
    """Execute one planned run: verify inputs, then PLANNED -> RUNNING -> COMPLETE.

    Accepts only the tenant and the deterministic run identifier: all
    lifecycle transitions, timestamps, hashes, event payloads, and
    references derive exclusively from the verified stored inputs
    (``verified.run_plan``, ``verified.world``, ``verified.strategy``,
    ``verified.seed``, ``verified.status``). A synthetic RunPlan cannot be
    injected through the signature, and no plan, model, transition, or
    execution artifact may be supplied by the caller.

    Runtime selection derives only from the recorded RunPlan/RunStatus:

    - legacy "1.0.0" runs execute under the exact structural-only
      behavior: verify recorded inputs, emit exactly the same three
      structural events, produce the same event hash, perform PLANNED ->
      RUNNING -> COMPLETE, and create no trajectory execution artifact;
    - trajectory "2.0.0" runs verify and resolve their exact trajectory
      plans/catalogs, ensure no execution artifact already exists,
      evaluate every applicable plan in memory, and build the complete
      ``RunTrajectoryExecution`` artifact **before the first lifecycle
      write**; only after all evaluation succeeds are the integrity
      manifest recorded, the run transitioned RUNNING, the three
      structural events stored, the execution artifact stored, and the
      run transitioned COMPLETE with the existing structural event hash;
    - any other recorded version is rejected with a typed
      :class:`UnsupportedRuntimeVersionError` before any lifecycle
      change.

    On any verification/evaluation/contract/hash failure the existing
    RunStatus remains PLANNED, zero run events and zero trajectory
    artifacts are written, the run is not marked FAILED, and the typed
    error is raised. Raises RunNotPlannedError unless the run is
    currently PLANNED.
    """
    verified = verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
    recorded_version = verified.run_plan.runtime_version
    if recorded_version == LEGACY_STRUCTURAL_RUNTIME_VERSION:
        return _execute_run_legacy(store, tenant_id, run_id, verified)
    if recorded_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(recorded_version, operation="run execution")
    return _execute_run_trajectory(store, tenant_id, run_id, verified)


def _execute_run_legacy(
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
    verified: VerifiedRunInputs,
) -> RunExecution:
    """The exact legacy structural-only execution (runtime version 1.0.0).

    Byte-identical to the pre-Phase 16 behavior: the integrity manifest
    is recorded first, the PLANNED gate applies, and the three
    structural events are generated, stored, and hashed exactly as
    before. No trajectory execution artifact is created.
    """
    store.put_input_integrity_manifest(tenant_id, run_id, verified.manifest)

    existing = verified.status
    if existing.state is not RunState.PLANNED:
        raise RunNotPlannedError(run_id, existing.state.value)

    run_plan = verified.run_plan
    world = verified.world
    strategy = verified.strategy
    seed = verified.seed

    running = RunStatus(
        identifier=f"status-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=run_plan.campaign_id,
        run_plan_id=run_plan.identifier,
        state=RunState.RUNNING,
        runtime_version=run_plan.runtime_version,
        input_hash=run_plan.input_hash,
        created_at=run_plan.created_at,
        changed_at=run_plan.created_at,
    )
    store.put_run_status(tenant_id, run_id, running)

    events = structural_events(
        run_plan=run_plan, world=world, strategy=strategy, seed=seed, run_id=run_id
    )
    store.put_run_events(tenant_id, run_id, events)

    digest = event_hash(events)
    complete = RunStatus(
        identifier=f"status-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=run_plan.campaign_id,
        run_plan_id=run_plan.identifier,
        state=RunState.COMPLETE,
        runtime_version=run_plan.runtime_version,
        input_hash=run_plan.input_hash,
        event_hash=digest,
        created_at=run_plan.created_at,
        changed_at=run_plan.created_at,
    )
    store.put_run_status(tenant_id, run_id, complete)
    return RunExecution(status=complete, events=events)


def _execute_run_trajectory(
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
    verified: VerifiedRunInputs,
) -> RunExecution:
    """The trajectory runtime execution (runtime version 2.0.0).

    All trajectory inputs are verified and resolved, the PLANNED gate
    applies, no pre-existing execution artifact may exist, and the
    complete ``RunTrajectoryExecution`` artifact is built and validated
    in memory - all **before the first lifecycle write**. Only after
    every evaluation succeeds is the integrity manifest recorded, the
    run transitioned RUNNING, the three structural events stored, the
    execution artifact stored, and the run transitioned COMPLETE with
    the existing structural event hash. The structural event stream and
    its hash are exactly the same three events as the legacy runtime;
    the trajectory execution hash is independent and never feeds the
    event stream.
    """
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    inputs = trajectory_inputs.inputs

    existing = verified.status
    if existing.state is not RunState.PLANNED:
        raise RunNotPlannedError(run_id, existing.state.value)

    try:
        store.get_run_trajectory_execution(tenant_id, run_id)
    except RunTrajectoryExecutionNotFoundError:
        pass
    else:
        raise RunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)

    # Evaluate every applicable plan in memory and build the complete
    # artifact; the pure builder verifies the runtime version, plan
    # strategy binding, closed-catalog resolution, engine attempts, and
    # every content hash. Any failure raises before any write, and the
    # built artifact is the exact object stored after the structural
    # events (the builder is pure and deterministic; it never mutates
    # any input and never samples time or randomness).
    execution = build_run_trajectory_execution(
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )

    run_plan = inputs.run_plan
    world = inputs.world
    strategy = inputs.strategy
    seed = inputs.seed

    store.put_input_integrity_manifest(tenant_id, run_id, inputs.manifest)

    running = RunStatus(
        identifier=f"status-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=run_plan.campaign_id,
        run_plan_id=run_plan.identifier,
        state=RunState.RUNNING,
        runtime_version=run_plan.runtime_version,
        input_hash=run_plan.input_hash,
        created_at=run_plan.created_at,
        changed_at=run_plan.created_at,
    )
    store.put_run_status(tenant_id, run_id, running)

    events = structural_events(
        run_plan=run_plan, world=world, strategy=strategy, seed=seed, run_id=run_id
    )
    store.put_run_events(tenant_id, run_id, events)

    store.put_run_trajectory_execution(tenant_id, run_id, execution)

    digest = event_hash(events)
    complete = RunStatus(
        identifier=f"status-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=run_plan.campaign_id,
        run_plan_id=run_plan.identifier,
        state=RunState.COMPLETE,
        runtime_version=run_plan.runtime_version,
        input_hash=run_plan.input_hash,
        event_hash=digest,
        created_at=run_plan.created_at,
        changed_at=run_plan.created_at,
    )
    store.put_run_status(tenant_id, run_id, complete)
    return RunExecution(status=complete, events=events)


def execute_campaign(
    *, store: InMemoryScenarioStore, tenant_id: str, campaign_id: str
) -> tuple[RunStatus, ...]:
    """Preflight every run, then execute all planned runs in stored order.

    A campaign may execute only from RUNNING. Before the first run
    begins, every stored RunPlan is preflight-verified in its
    deterministic stored order - recorded inputs as today, and for every
    trajectory-runtime (2.0.0) run additionally its exact trajectory
    inputs, the absence of any unexpected pre-existing execution
    artifact, and the full in-memory build of its expected
    ``RunTrajectoryExecution``. If any run fails preflight, zero runs
    execute, zero events and zero trajectory artifacts are written,
    every RunStatus stays PLANNED, the campaign stays RUNNING, and the
    typed error is raised (atomic failure). After a successful preflight
    the runs execute in the existing deterministic stored order; the
    per-run ``execute_run`` still independently reloads and verifies
    every stored input rather than accepting preflight objects. After
    every planned run is COMPLETE the campaign transitions RUNNING ->
    COMPLETE. No outcome vectors, evidence, briefs, metrics, or
    recommendations are produced.
    """
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.RUNNING:
        raise CampaignNotRunningError(campaign_id, status.state.value)

    plans = store.get_run_plans(tenant_id, campaign_id)

    # Atomic preflight: every run must verify before any execution
    # begins, including the full trajectory resolution and in-memory
    # artifact build for every 2.0.0 run. Any failure leaves every run
    # PLANNED and the campaign RUNNING with zero writes.
    for run_plan in plans:
        run_id = run_identifier(run_plan)
        verified = verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
        recorded_version = verified.run_plan.runtime_version
        if recorded_version == LEGACY_STRUCTURAL_RUNTIME_VERSION:
            continue
        if recorded_version != TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(recorded_version, operation="run execution")
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=tenant_id, run_id=run_id
        )
        try:
            store.get_run_trajectory_execution(tenant_id, run_id)
        except RunTrajectoryExecutionNotFoundError:
            pass
        else:
            raise RunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)
        build_run_trajectory_execution(
            inputs=trajectory_inputs.inputs,
            plans=trajectory_inputs.plans,
            catalogs=trajectory_inputs.catalogs,
        )

    # Stored-plan ordering is retained only to derive each deterministic run
    # id; execution itself loads and verifies every input from recorded state.
    statuses: list[RunStatus] = []
    for run_plan in plans:
        execution = execute_run(store=store, tenant_id=tenant_id, run_id=run_identifier(run_plan))
        statuses.append(execution.status)

    completed = CampaignStatus(
        identifier=status.identifier,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        state=CampaignState.COMPLETE,
        changed_at=plans[0].created_at,
        message="campaign complete: structural execution finished; no decision evidence produced",
    )
    store.update_campaign_status(tenant_id, campaign_id, completed)
    return tuple(statuses)
