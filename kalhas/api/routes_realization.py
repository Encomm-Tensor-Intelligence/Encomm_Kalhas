"""HTTP routes for the runtime-3.0.0 realization-aware trajectory surface (Phase 25).

Exactly six unique paths and seven OpenAPI operations serve every
runtime-3 artifact, mirroring the runtime-2 endpoint families under the
``realization-`` prefix:

- ``GET /v1/runs/{run_id}/realization-trajectory-execution``
- ``GET /v1/runs/{run_id}/realization-trajectory-replay-manifest``
- ``POST /v1/runs/{run_id}/realization-metric-observations`` (201)
- ``GET /v1/runs/{run_id}/realization-metric-observations``
- ``GET /v1/campaigns/{campaign_id}/realization-trajectory-matrix``
- ``GET /v1/campaigns/{campaign_id}/realization-metric-observation-matrix``
- ``GET /v1/campaigns/{campaign_id}/realization-metric-statistics``

Every operation is ``X-Tenant-ID`` scoped and reads the tenant-scoped
recorded runtime **before** invoking any artifact service: exactly
``3.0.0`` is accepted, every other recorded runtime raises the typed
:class:`UnsupportedRuntimeVersionError` (409 conflict). The runtime
switch never comes from a query parameter or caller-provided value.
The established safe typed 404, 409 invalid_state, 409 conflict, and
409 integrity_error mappings and the generic no-leak error bodies are
preserved unchanged.

The two direct run-artifact GETs use small private read-only helpers
that reuse the authoritative Phase 25 verification functions -
``verify_run_trajectory_inputs``, ``verify_realization_run_trajectory_
execution_record``, ``verify_realization_run_metric_observation_set_
record``, ``verify_realization_run_trajectory_replay_manifest_record``,
and ``trajectory_plan_set_hash`` - never reimplementing their
validation algorithms. All six GET operations are strictly read-only:
no lifecycle changes, no events, no artifact creation, no extraction,
no replay, no repair or overwrite, and no operational-activity event.
The observation POST writes only the observation set through the
existing extraction service and records no operational-activity event.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_metric_statistics_query_service import (
    get_verified_realization_campaign_metric_statistics,
)
from kalhas.application.realization_campaign_trajectory_query_service import (
    get_verified_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_execution_record,
    verify_realization_run_trajectory_replay_manifest_record,
)
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
    get_verified_realization_run_metric_observation_set,
    verify_realization_run_metric_observation_set_record,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)

router = APIRouter()


def _store(request: Request) -> InMemoryScenarioStore:
    """Resolve the process-local in-memory store from app state."""
    store: InMemoryScenarioStore = request.app.state.store
    return store


def _require_realization_run(store: InMemoryScenarioStore, tenant_id: str, run_id: str) -> None:
    """Read the tenant-scoped recorded runtime and require exactly 3.0.0.

    Unknown or foreign runs raise the store's typed not-found error
    (404); any recorded runtime other than ``3.0.0`` raises the typed
    unsupported-runtime error (409 conflict) before any artifact service
    is invoked. The recorded ``RunStatus`` is the only trusted source.
    """
    status = store.get_run_status(tenant_id, run_id)
    if status.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            status.runtime_version, operation="realization run artifact"
        )


def _require_realization_campaign(
    store: InMemoryScenarioStore, tenant_id: str, campaign_id: str
) -> None:
    """Read the tenant-scoped recorded run plans and require every runtime 3.0.0.

    Unknown or foreign campaigns raise the store's typed not-found error
    (404); an empty recorded plan tuple - which has no recorded runtime
    to dispatch on - and any recorded plan runtime other than ``3.0.0``
    raise the typed unsupported-runtime error (409 conflict) before any
    artifact service is invoked. The recorded ``RunPlan`` set is the only
    trusted source; no query parameter or caller-provided switch is ever
    read.
    """
    plans = store.get_run_plans(tenant_id, campaign_id)
    if not plans:
        # Fail closed: no recorded runtime exists, so no runtime-3 query
        # service or artifact access may run.
        raise UnsupportedRuntimeVersionError("", operation="realization campaign artifact")
    for plan in plans:
        if plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="realization campaign artifact"
            )


def _verified_realization_execution(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RealizationRunTrajectoryExecution:
    """Load and fully verify a run's stored runtime-3 trajectory execution.

    Strictly read-only retrieval: the tenant-scoped recorded runtime is
    read first (exactly ``3.0.0`` required), the recorded trajectory
    inputs are verified, the stored execution is loaded through the
    store's deep-copy boundary, and it is returned only after
    ``verify_realization_run_trajectory_execution_record`` accepts every
    deterministic check against the verified inputs, plans, catalogs,
    and reconstructed realization. Missing artifacts raise the typed
    404; corrupted or tampered artifacts the typed 409 integrity_error.
    Nothing is rebuilt, repaired, overwritten, or written.
    """
    _require_realization_run(store, tenant_id, run_id)
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    if trajectory_inputs.realization is None:
        raise RealizationRunTrajectoryExecutionIntegrityError(
            run_id, "realized initial state missing after trajectory verification"
        )
    execution = store.get_realization_run_trajectory_execution(tenant_id, run_id)
    verify_realization_run_trajectory_execution_record(
        execution,
        inputs=trajectory_inputs.inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
        realization=trajectory_inputs.realization,
    )
    return execution


def _verified_realization_replay_manifest(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RealizationRunTrajectoryReplayManifest:
    """Load and fully verify a run's stored runtime-3 trajectory replay manifest.

    Strictly read-only retrieval: the tenant-scoped recorded runtime is
    read first (exactly ``3.0.0`` required), the recorded trajectory
    inputs are verified, the authoritative stored execution is loaded
    and fully verified, the stored observation set is loaded and
    verified through the authoritative regeneration-equality verifier,
    the exact ordered trajectory plan-set hash is recomputed, and the
    stored manifest is returned only after
    ``verify_realization_run_trajectory_replay_manifest_record`` accepts
    every check. This never triggers replay, extraction, evaluation,
    regeneration, or any write: before a successful replay the typed 404
    is returned and nothing is created.
    """
    _require_realization_run(store, tenant_id, run_id)
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    if trajectory_inputs.realization is None:
        raise RealizationRunTrajectoryExecutionIntegrityError(
            run_id, "realized initial state missing after trajectory verification"
        )
    execution = store.get_realization_run_trajectory_execution(tenant_id, run_id)
    verify_realization_run_trajectory_execution_record(
        execution,
        inputs=trajectory_inputs.inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
        realization=trajectory_inputs.realization,
    )
    observation_set = store.get_realization_run_metric_observation_set(tenant_id, run_id)
    verify_realization_run_metric_observation_set_record(
        observation_set,
        store=store,
        tenant_id=tenant_id,
        run_id=run_id,
        trajectory_inputs=trajectory_inputs,
    )
    plan_set_hash = trajectory_plan_set_hash(trajectory_inputs.plans)
    manifest = store.get_realization_run_trajectory_replay_manifest(tenant_id, run_id)
    verify_realization_run_trajectory_replay_manifest_record(
        manifest,
        inputs=trajectory_inputs.inputs,
        execution=execution,
        observation_set=observation_set,
        plan_set_hash=plan_set_hash,
    )
    return manifest


@router.get(
    "/v1/runs/{run_id}/realization-trajectory-execution",
    response_model=RealizationRunTrajectoryExecution,
    tags=["realization"],
    summary="Fetch a run's verified runtime-3 realization trajectory execution",
)
def get_realization_run_trajectory_execution_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationRunTrajectoryExecution:
    """Fetch the immutable realization trajectory execution artifact of a 3.0.0 run.

    Read-only inspection of the Phase 25 artifact: the tenant-scoped
    recorded runtime is read first (exactly 3.0.0 required, every other
    recorded runtime returns the typed 409 conflict), the recorded run
    inputs and the exact applicable trajectory plans and closed
    compiled-world catalogs are verified, the reconstructed realization
    is provenance-checked, the stored artifact is loaded through the
    store boundary and fully verified, and returned only after complete
    verification. Retrieval never executes, replays, evaluates, repairs,
    normalizes, or writes anything, and records no operational-activity
    event. Unknown or foreign runs return the typed 404; not-yet-
    executed 3.0.0 runs have no artifact and also return the typed 404;
    corrupted artifacts fail through the typed 409 integrity mapping -
    without leaking tenant ids, hashes, state values, guards, targets,
    policies, or internal reasons.
    """
    return _verified_realization_execution(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.get(
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest",
    response_model=RealizationRunTrajectoryReplayManifest,
    tags=["realization"],
    summary="Fetch a run's verified runtime-3 realization trajectory replay manifest",
)
def get_realization_run_trajectory_replay_manifest_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationRunTrajectoryReplayManifest:
    """Fetch the immutable runtime-3 replay manifest of a replayed 3.0.0 run.

    Read-only retrieval of an already-created manifest: the tenant-
    scoped recorded runtime is read first (exactly 3.0.0 required,
    every other recorded runtime returns the typed 409 conflict), the
    recorded trajectory inputs are verified, the authoritative stored
    execution artifact is loaded and verified first, the stored
    observation set is verified through the authoritative
    regeneration-equality verifier, the exact ordered trajectory
    plan-set hash is recomputed, and the stored manifest is verified
    against the authoritative execution, observation set, and plan-set
    hash before it is returned. This endpoint never triggers replay,
    evaluation, artifact regeneration, or any write, and records no
    operational-activity event. Before a successful replay there is no
    manifest and the typed 404 is returned; corrupted records preserve
    the typed 409 conflict/integrity mappings without leaking internal
    reasons, hashes, state values, guards, targets, policies, or
    validation details.
    """
    return _verified_realization_replay_manifest(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.post(
    "/v1/runs/{run_id}/realization-metric-observations",
    response_model=RealizationRunMetricObservationSet,
    status_code=201,
    tags=["realization"],
    summary="Extract and store a run's immutable runtime-3 metric observation set",
)
def extract_realization_run_metric_observations_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationRunMetricObservationSet:
    """Explicitly extract and store the immutable raw observation set of a 3.0.0 run.

    Post-execution extraction only: the tenant-scoped recorded runtime
    is read first (exactly 3.0.0 required, every other recorded runtime
    returns the typed 409 conflict before any read, build, or write),
    the recorded run and trajectory inputs are verified, the run must be
    COMPLETE, the stored ``RealizationRunTrajectoryExecution`` is loaded
    through the store boundary and fully verified, and one raw
    observation is extracted per observation binding embedded in the
    run's exact compiled world - from the verified execution's final
    realized state only, in canonical metric-id order. The complete set
    is stored only after every validation and integrity check succeeds;
    any failure writes nothing. Unknown or foreign runs return the typed
    404; a second extraction of the same run returns the typed 409
    conflict and never overwrites. Extraction never evaluates
    transitions, replays, aggregates, or calculates outcomes, and no
    operational-activity event is recorded.
    """
    _require_realization_run(_store(request), x_tenant_id, run_id)
    return extract_realization_run_metric_observations(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.get(
    "/v1/runs/{run_id}/realization-metric-observations",
    response_model=RealizationRunMetricObservationSet,
    tags=["realization"],
    summary="Fetch a run's verified runtime-3 metric observation set",
)
def get_realization_run_metric_observations_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationRunMetricObservationSet:
    """Fetch the immutable metric observation set of a 3.0.0 run, fully verified.

    Strictly read-only: the tenant-scoped recorded runtime is read first
    (exactly 3.0.0 required, every other recorded runtime returns the
    typed 409 conflict), the recorded run and trajectory inputs are
    verified, the run must be COMPLETE, the stored set is loaded through
    the store boundary, the authoritative execution is verified, and the
    stored set is returned only after the verifier regenerates the
    expected set in memory and requires exact canonical-JSON equality
    (identifier, ordering, values, provenance, content hash). This
    endpoint never performs extraction: a missing or foreign set returns
    the typed 404 and nothing is ever created. Corrupted or tampered
    records fail through the typed 409 integrity mapping, no
    operational-activity event is recorded, and no raw observed values,
    hashes, state values, guards, targets, policies, internal reasons,
    or validation details are leaked.
    """
    _require_realization_run(_store(request), x_tenant_id, run_id)
    return get_verified_realization_run_metric_observation_set(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix",
    response_model=RealizationCampaignTrajectoryMatrix,
    tags=["realization"],
    summary="Fetch a completed campaign's verified runtime-3 trajectory matrix",
)
def get_realization_campaign_trajectory_matrix_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationCampaignTrajectoryMatrix:
    """Fetch the deterministic realization trajectory matrix of a COMPLETE 3.0.0 campaign.

    Read-only retrieval: the tenant-scoped recorded run plans are read
    first (every recorded runtime must be exactly 3.0.0; any other value
    returns the typed 409 conflict before the artifact service is
    invoked), then the complete strategy x shared-seed realization
    trajectory matrix is assembled from every verified Phase 25
    ``RealizationRunTrajectoryExecution`` through the existing verified
    query service and returned without being stored. Unknown or foreign
    campaigns return the typed 404; non-COMPLETE campaigns the typed 409
    invalid_state; missing, inconsistent, or corrupted matrix inputs or
    executions the typed 409 integrity_error - without leaking internal
    reasons, hashes, state values, guards, targets, policies, or
    validation details. The GET performs no write and creates no
    operational-activity event.
    """
    _require_realization_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_realization_campaign_trajectory_matrix(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix",
    response_model=RealizationCampaignMetricObservationMatrix,
    tags=["realization"],
    summary="Fetch a completed campaign's verified runtime-3 metric-observation matrix",
)
def get_realization_campaign_metric_observation_matrix_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationCampaignMetricObservationMatrix:
    """Fetch the deterministic metric-observation matrix of a COMPLETE 3.0.0 campaign.

    Read-only retrieval: the tenant-scoped recorded run plans are read
    first (every recorded runtime must be exactly 3.0.0; any other value
    returns the typed 409 conflict before the artifact service is
    invoked), then the complete strategy x shared-seed observation
    layout is assembled through the existing verified query service -
    every run's observation set must already exist and pass the existing
    verification; nothing is ever extracted automatically - and returned
    without being stored. Unknown or foreign campaigns return the typed
    404; non-COMPLETE campaigns the typed 409 invalid_state; missing,
    inconsistent, or corrupted observation sets or matrix inputs the
    typed 409 integrity_error - without leaking raw observation values,
    hashes, state values, guards, targets, policies, metadata, internal
    reasons, or validation details. The GET performs no write and
    creates no operational-activity event.
    """
    _require_realization_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_realization_campaign_metric_observation_matrix(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/realization-metric-statistics",
    response_model=RealizationCampaignMetricStatisticsMatrix,
    tags=["realization"],
    summary="Fetch a completed campaign's deterministic runtime-3 metric statistics",
)
def get_realization_campaign_metric_statistics_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RealizationCampaignMetricStatisticsMatrix:
    """Fetch the deterministic descriptive-statistics matrix of a COMPLETE 3.0.0 campaign.

    Read-only retrieval: the tenant-scoped recorded run plans are read
    first (every recorded runtime must be exactly 3.0.0; any other value
    returns the typed 409 conflict before the artifact service is
    invoked), then the descriptive-statistics matrix is derived through
    the existing verified query service exclusively from the completely
    verified Phase 25 metric-observation matrix and returned without
    being stored. Unknown or foreign campaigns return the typed 404;
    non-COMPLETE campaigns the typed 409 invalid_state; missing,
    inconsistent, or corrupted observation sets or matrix inputs the
    typed 409 integrity_error; calculation, consistency, overflow, or
    non-finite failures the typed 409 integrity_error - without leaking
    raw observation values, calculated statistics, hashes, state values,
    field names, policies, metadata, internal reasons, or validation
    details. The GET performs no write and creates no
    operational-activity event.
    """
    _require_realization_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_realization_campaign_metric_statistics(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
