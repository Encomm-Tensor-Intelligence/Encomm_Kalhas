"""Runtime-3.0.0 realization-aware run and campaign lifecycle execution (Phase 25).

``execute_realization_run`` executes one planned realization-trajectory
run and ``execute_realization_campaign`` executes every planned run of a
RUNNING campaign in its exact stored order. Both accept only the store,
tenant, and deterministic identifiers - no plans, catalogs, realizations,
runtime versions, execution artifacts, states, or transitions may be
injected through the signature.

Per run the execution is a strict sequence: read the recorded RunStatus,
gate exclusively on its recorded runtime version (exactly 3.0.0, anything
else raises ``UnsupportedRuntimeVersionError``), require ``PLANNED``
(``RunNotPlannedError``, zero writes), call
``verify_run_trajectory_inputs`` **exactly once** (which owns the
complete runtime-3 chain and the exactly-once reconstructed
``WorldRealization``; the separate run-scoped verifier is never called
here),
require the returned recorded runtime 3.0.0 and a non-None realization,
prove no runtime-3 execution artifact already exists (an existing
artifact, even an identical one, raises
``RealizationRunTrajectoryExecutionAlreadyExistsError`` and is never
overwritten or repaired), build the complete
``RealizationRunTrajectoryExecution`` in memory, and **only then** write:
input-integrity manifest, RUNNING status, the exact existing three
structural events, the structural event stream, the execution artifact,
and the COMPLETE status carrying the existing structural event hash -
never the realization execution content hash.

Any verification, build, or contract failure before the write phase
leaves the RunStatus unchanged (PLANNED, no event hash), zero run
events, zero runtime-3 artifacts, no FAILED transition, and raises the
typed error. Sequential writes are not transactional: an unexpected
failure after the first write may leave partial state, recovered only
through the defined deterministic replay/idempotence rules - no rollback
is claimed.

``execute_realization_campaign`` requires ``RUNNING``, preflights every
stored RunPlan atomically (one ``verify_run_trajectory_inputs`` call per
run plus runtime gate, PLANNED check, artifact-absence probe, and the
full in-memory artifact build), executes every run through
``execute_realization_run`` in exact stored order (each a separate
trust operation that independently reloads and verifies its inputs), and
only after all runs are COMPLETE transitions the campaign to COMPLETE
with the runtime-2 convention message. A preflight failure anywhere -
first, middle, or last run - executes zero runs and writes nothing.

No observations, replay manifests, campaign matrices, evidence,
decisions, probabilities, risk statistics, or recommendations are ever
created here. No LEGION/NEXUS, wall clock, randomness, provider,
network, or filesystem is used.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    CampaignNotRunningError,
    RunNotPlannedError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    preflight_realization_run_plan_matrix,
)
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionAlreadyExistsError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
)
from kalhas.application.realization_trajectory_runtime import (
    build_realization_run_trajectory_execution,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.structural_runtime import (
    RunExecution,
    event_hash,
    structural_events,
)
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus


def execute_realization_run(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunExecution:
    """Execute one planned realization-trajectory (3.0.0) run.

    Accepts only the tenant and the deterministic run identifier; all
    lifecycle transitions, timestamps, hashes, event payloads, and
    artifact references derive exclusively from the recorded state
    re-verified through ``verify_run_trajectory_inputs`` (exactly once).
    See the module docstring for the exact order and failure atomicity.
    """
    status = store.get_run_status(tenant_id, run_id)
    if status.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            status.runtime_version, operation="realization run execution"
        )
    if status.state is not RunState.PLANNED:
        raise RunNotPlannedError(run_id, status.state.value)

    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    inputs = trajectory_inputs.inputs
    if inputs.run_plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            inputs.run_plan.runtime_version, operation="realization run execution"
        )
    if trajectory_inputs.realization is None:
        raise RealizationRunTrajectoryExecutionIntegrityError(
            run_id, "realized initial state missing after trajectory verification"
        )

    try:
        store.get_realization_run_trajectory_execution(tenant_id, run_id)
    except RealizationRunTrajectoryExecutionNotFoundError:
        pass
    else:
        raise RealizationRunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)

    execution = build_realization_run_trajectory_execution(
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
        realization=trajectory_inputs.realization,
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

    store.put_realization_run_trajectory_execution(tenant_id, run_id, execution)

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


def execute_realization_campaign(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> tuple[RunStatus, ...]:
    """Execute every planned realization-trajectory run of a RUNNING campaign.

    The campaign may execute only from RUNNING. Before the first run
    begins, every stored RunPlan is preflight-verified in its
    deterministic stored order: recorded runtime exactly 3.0.0, PLANNED,
    one ``verify_run_trajectory_inputs`` call (with a non-None
    realization), no pre-existing execution artifact, and the full
    in-memory build of the expected artifact. If any run fails
    preflight, zero runs execute, zero events and zero artifacts are
    written, every RunStatus stays PLANNED, and the campaign stays
    RUNNING. After a successful preflight every run executes through
    ``execute_realization_run`` in exact stored order - each an
    independent trust operation that reloads and verifies its inputs.
    After every planned run is COMPLETE the campaign transitions RUNNING
    -> COMPLETE with the runtime-2 convention message.
    """
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.RUNNING:
        raise CampaignNotRunningError(campaign_id, status.state.value)

    # The complete strategy x seed matrix must be verified before any
    # run executes: the authoritative campaign and its compiled world
    # drive the existing read-only matrix preflight exactly once. It
    # proves exact stored candidate tuple and order, exact strategy x
    # seed RunPlan cardinality and strategy-major/seed-minor order, no
    # missing/additional/duplicated/reordered/tampered plans, recorded
    # runtime exactly 3.0.0, stored<->embedded uncertainty-model
    # consistency, deterministic realization-matrix reconstruction,
    # exact runtime-3 input hashes, and per-run input integrity - and it
    # never writes and never calls LEGION. Its internal per-run
    # run-scoped verification calls are owned by that preflight; no
    # direct run-scoped verification is added here.
    campaign = store.get_campaign(tenant_id, campaign_id)
    world = store.get_world(tenant_id, campaign.world_version_id)
    preflight_realization_run_plan_matrix(store, tenant_id, campaign, world)

    plans = store.get_run_plans(tenant_id, campaign_id)

    # Atomic preflight: every run must verify and fully build in memory
    # before any execution begins. Any failure leaves every run PLANNED
    # and the campaign RUNNING with zero writes.
    for run_plan in plans:
        run_id = run_identifier(run_plan)
        run_status = store.get_run_status(tenant_id, run_id)
        if run_status.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                run_status.runtime_version, operation="realization run execution"
            )
        if run_status.state is not RunState.PLANNED:
            raise RunNotPlannedError(run_id, run_status.state.value)
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=tenant_id, run_id=run_id
        )
        if trajectory_inputs.realization is None:
            raise RealizationRunTrajectoryExecutionIntegrityError(
                run_id, "realized initial state missing after trajectory verification"
            )
        try:
            store.get_realization_run_trajectory_execution(tenant_id, run_id)
        except RealizationRunTrajectoryExecutionNotFoundError:
            pass
        else:
            raise RealizationRunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)
        build_realization_run_trajectory_execution(
            inputs=trajectory_inputs.inputs,
            plans=trajectory_inputs.plans,
            catalogs=trajectory_inputs.catalogs,
            realization=trajectory_inputs.realization,
        )

    # Stored-plan ordering is retained only to derive each deterministic
    # run id; execution itself loads and verifies every input from
    # recorded state.
    statuses: list[RunStatus] = []
    for run_plan in plans:
        execution = execute_realization_run(
            store=store, tenant_id=tenant_id, run_id=run_identifier(run_plan)
        )
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
