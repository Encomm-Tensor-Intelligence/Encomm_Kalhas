"""HTTP routes for KALHAS.

Phase 0: health and system info. Phase 2: scenario, validation, compilation,
and world endpoints backed by the in-memory store and the local mock
integration surface.
"""

from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.api.requests import (
    BindDomainPackRequest,
    DeclareCapabilityInputsRequest,
    DeclareStateModelRequest,
    DeclareStateTransitionRequest,
    DomainMetricObservationDeclarationRequest,
    DomainPackRegistrationRequest,
    PrepareCampaignRequest,
    StartCampaignRequest,
)
from kalhas.api.responses import (
    CampaignDetailResponse,
    CampaignExecutionResponse,
    CompiledWorldResponse,
    DomainCapabilityDeclarationListResponse,
    DomainMetricObservationListResponse,
    DomainPackBindingListResponse,
    DomainPackListResponse,
    DomainStateModelListResponse,
    DomainStateTransitionListResponse,
    OperationalActivityListResponse,
    RunEventListResponse,
    RunPlanListResponse,
    ScenarioValidationResponse,
)
from kalhas.application.campaign_service import prepare_campaign, start_campaign
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.domain_capability_declaration_service import (
    declare_capability_inputs,
    list_declarations,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
    list_domain_metric_observations,
)
from kalhas.application.domain_pack_binding_service import (
    bind_manifest,
    list_bindings,
)
from kalhas.application.domain_pack_registry import (
    get_manifest,
    list_manifests,
    register_manifest,
)
from kalhas.application.domain_state_model_service import (
    declare_state_model,
    list_state_models,
)
from kalhas.application.domain_state_transition_service import (
    declare_transition,
    list_transitions,
)
from kalhas.application.in_memory_store import MAX_ACTIVITY_LIMIT, InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.operational_activity import (
    latest_sequence,
    list_activity,
    record_campaign_executed,
    record_campaign_prepared,
    record_campaign_started,
    record_capability_inputs_declared,
    record_domain_pack_bound,
    record_domain_pack_registered,
    record_domain_state_model_declared,
    record_domain_state_transition_declared,
    record_run_inputs_verified,
    record_run_replayed,
    record_scenario_registered,
    record_world_compiled,
)
from kalhas.application.replay_service import replay_run
from kalhas.application.runtime import get_runtime_mode
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.system_info import get_system_info
from kalhas.application.trajectory_query_service import (
    get_verified_run_trajectory_execution,
    get_verified_run_trajectory_replay_manifest,
)
from kalhas.contracts.v1 import API_VERSION
from kalhas.contracts.v1.campaign import CampaignStatus
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunStatus
from kalhas.contracts.v1.health import HealthResponse
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.system_info import SystemInfoResponse
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldVersion
from kalhas.version import __version__

router = APIRouter()


def _mock_nexus(request: Request) -> MockNexusAdapter:
    """Resolve the process-local mock integration surface from app state."""
    mock_nexus: MockNexusAdapter = request.app.state.mock_nexus
    return mock_nexus


def _mock_legion(request: Request) -> MockLegionAdapter:
    """Resolve the process-local mock strategy boundary from app state."""
    mock_legion: MockLegionAdapter = request.app.state.mock_legion
    return mock_legion


def _store(request: Request) -> InMemoryScenarioStore:
    """Resolve the process-local in-memory store from app state."""
    store: InMemoryScenarioStore = request.app.state.store
    return store


def _require_tenant_match(scenario: ScenarioSpec, x_tenant_id: str) -> None:
    if scenario.tenant_id != x_tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id must match the X-Tenant-ID header")


@router.get("/health", response_model=HealthResponse, tags=["system"], summary="Liveness probe")
def health() -> HealthResponse:
    """Return liveness status of the KALHAS service."""
    return HealthResponse(version=__version__, api_version=API_VERSION)


@router.get(
    "/v1/system-info",
    response_model=SystemInfoResponse,
    tags=["system"],
    summary="System information",
)
def system_info() -> SystemInfoResponse:
    """Return metadata about the running KALHAS instance."""
    return get_system_info(get_runtime_mode())


@router.post(
    "/v1/scenarios",
    response_model=ScenarioSpec,
    status_code=201,
    tags=["scenarios"],
    summary="Register a scenario",
)
def create_scenario(
    scenario: ScenarioSpec,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> ScenarioSpec:
    """Store a scenario; the body tenant must match the X-Tenant-ID header."""
    _require_tenant_match(scenario, x_tenant_id)
    _mock_nexus(request).submit_scenario(scenario)
    record_scenario_registered(_store(request), tenant_id=x_tenant_id, scenario=scenario)
    return scenario


@router.post(
    "/v1/scenarios/{scenario_id}/validate",
    response_model=ScenarioValidationResponse,
    tags=["scenarios"],
    summary="Validate a scenario semantically",
)
def validate_scenario_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> ScenarioValidationResponse:
    """Validate a stored scenario; returns the report and clarification questions."""
    result = _mock_nexus(request).validate_scenario(x_tenant_id, scenario_id)
    return ScenarioValidationResponse(report=result.report, questions=result.questions)


@router.post(
    "/v1/scenarios/{scenario_id}/compile",
    response_model=CompiledWorldResponse,
    tags=["scenarios"],
    summary="Compile a scenario into an immutable world",
)
def compile_scenario_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CompiledWorldResponse:
    """Compile a semantically valid scenario; 422 when validation fails."""
    compiled = _mock_nexus(request).compile_scenario(x_tenant_id, scenario_id)
    record_world_compiled(
        _store(request), tenant_id=x_tenant_id, scenario_id=scenario_id, world=compiled.version
    )
    return CompiledWorldResponse(version=compiled.version, manifest=compiled.manifest)


@router.get(
    "/v1/worlds/{world_version_id}",
    response_model=WorldVersion,
    tags=["worlds"],
    summary="Fetch a compiled world",
)
def get_world_route(
    world_version_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> WorldVersion:
    """Fetch a compiled immutable world by version id."""
    return _mock_nexus(request).world(x_tenant_id, world_version_id)


@router.post(
    "/v1/campaigns",
    response_model=CampaignDetailResponse,
    status_code=201,
    tags=["campaigns"],
    summary="Prepare a campaign",
)
def create_campaign_route(
    request_body: PrepareCampaignRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignDetailResponse:
    """Prepare a campaign: plans runs only, never executes them.

    Tenant validation for the strategy request, seeds, and candidates is
    enforced by the application service with typed domain errors.
    """
    prepared = prepare_campaign(
        store=_store(request),
        legion=_mock_legion(request),
        tenant_id=x_tenant_id,
        scenario_id=request_body.scenario_id,
        world_version_id=request_body.world_version_id,
        strategy_request=request_body.strategy_request,
        campaign_id=request_body.campaign_id,
        campaign_name=request_body.campaign_name,
        seed_ensemble=request_body.seed_ensemble,
        created_at=request_body.created_at,
        runtime_version=request_body.runtime_version,
    )
    record_campaign_prepared(
        _store(request),
        tenant_id=x_tenant_id,
        campaign=prepared.campaign,
        status=prepared.status,
        run_plan_count=len(prepared.run_plans),
    )
    return CampaignDetailResponse(campaign=prepared.campaign, status=prepared.status)


@router.post(
    "/v1/campaigns/{campaign_id}/start",
    response_model=CampaignStatus,
    tags=["campaigns"],
    summary="Start a campaign",
)
def start_campaign_route(
    campaign_id: str,
    request_body: StartCampaignRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignStatus:
    """Perform only the COMPILED -> RUNNING transition; never simulates."""
    status = start_campaign(
        store=_store(request),
        tenant_id=x_tenant_id,
        campaign_id=campaign_id,
        changed_at=request_body.changed_at,
    )
    record_campaign_started(_store(request), tenant_id=x_tenant_id, status=status)
    return status


@router.get(
    "/v1/campaigns/{campaign_id}",
    response_model=CampaignDetailResponse,
    tags=["campaigns"],
    summary="Fetch a campaign",
)
def get_campaign_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignDetailResponse:
    """Fetch a campaign and its lifecycle status (tenant-scoped)."""
    return CampaignDetailResponse(
        campaign=_store(request).get_campaign(x_tenant_id, campaign_id),
        status=_store(request).get_campaign_status(x_tenant_id, campaign_id),
    )


@router.get(
    "/v1/campaigns/{campaign_id}/runs",
    response_model=RunPlanListResponse,
    tags=["campaigns"],
    summary="List planned runs",
)
def get_campaign_runs_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunPlanListResponse:
    """Fetch the ordered planning manifests of a campaign (no outcomes)."""
    plans = _store(request).get_run_plans(x_tenant_id, campaign_id)
    return RunPlanListResponse(run_plans=list(plans))


@router.post(
    "/v1/campaigns/{campaign_id}/execute",
    response_model=CampaignExecutionResponse,
    tags=["campaigns"],
    summary="Execute a campaign structurally",
)
def execute_campaign_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignExecutionResponse:
    """Execute all planned runs in order (campaign must be RUNNING).

    Structural execution only: no outcomes, evidence, or recommendations.
    Completes the campaign when every run is COMPLETE.
    """
    statuses = execute_campaign(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
    final_status = _store(request).get_campaign_status(x_tenant_id, campaign_id)
    record_campaign_executed(
        _store(request),
        tenant_id=x_tenant_id,
        campaign_id=campaign_id,
        status=final_status,
        run_statuses=statuses,
    )
    return CampaignExecutionResponse(run_statuses=list(statuses))


@router.get(
    "/v1/campaigns/{campaign_id}/trajectory-matrix",
    response_model=CampaignTrajectoryMatrix,
    tags=["campaigns"],
    summary="Fetch a completed campaign's verified trajectory matrix",
)
def get_campaign_trajectory_matrix_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignTrajectoryMatrix:
    """Fetch the deterministic trajectory matrix of a COMPLETE 2.0.0 campaign.

    The exact authoritative strategy x shared-seed run matrix of one
    completed trajectory-runtime campaign, assembled from every verified
    Phase 16 ``RunTrajectoryExecution`` of that campaign: a structural
    comparison provenance artifact only - verified references and
    integrity hashes for every run, never rankings, scores, outcomes,
    evidence, or recommendations. Read-only retrieval: the campaign must
    be COMPLETE, every recorded run must use runtime 2.0.0, and the
    complete collection is verified through the existing Phase 16/17
    pipelines before the matrix is built in memory and returned - it is
    never stored, executed, replayed, evaluated, repaired, or partially
    returned. Unknown or foreign campaigns return the typed 404;
    non-COMPLETE campaigns the typed 409 invalid_state; legacy or
    unsupported runtime the typed 409 conflict; and missing,
    inconsistent, or corrupted matrix inputs or executions the typed 409
    integrity_error - without leaking internal reasons, hashes, state
    values, guards, targets, policies, or validation details. The GET
    performs no write and creates no operational-activity event.
    """
    return get_verified_campaign_trajectory_matrix(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )


@router.get(
    "/v1/runs/{run_id}",
    response_model=RunStatus,
    tags=["runs"],
    summary="Fetch run status",
)
def get_run_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunStatus:
    """Fetch the lifecycle status of one run (tenant-scoped)."""
    return _store(request).get_run_status(x_tenant_id, run_id)


@router.get(
    "/v1/runs/{run_id}/events",
    response_model=RunEventListResponse,
    tags=["runs"],
    summary="Fetch run events",
)
def get_run_events_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunEventListResponse:
    """Fetch the ordered structural event stream of one run (tenant-scoped)."""
    events = _store(request).get_run_events(x_tenant_id, run_id)
    return RunEventListResponse(events=list(events))


@router.get(
    "/v1/runs/{run_id}/replay",
    response_model=ReplayManifest,
    tags=["runs"],
    summary="Replay a completed run exactly",
)
def replay_run_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> ReplayManifest:
    """Regenerate a COMPLETE run's event stream and verify its hash.

    The stream is genuinely regenerated from recorded inputs; the manifest
    is returned only when the recomputed hash matches the expected hash.
    """
    manifest = replay_run(store=_store(request), tenant_id=x_tenant_id, run_id=run_id)
    record_run_replayed(_store(request), tenant_id=x_tenant_id, manifest=manifest)
    return manifest


@router.get(
    "/v1/runs/{run_id}/trajectory-execution",
    response_model=RunTrajectoryExecution,
    tags=["runs"],
    summary="Fetch a run's verified trajectory execution artifact",
)
def get_run_trajectory_execution_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunTrajectoryExecution:
    """Fetch the immutable trajectory execution artifact of a 2.0.0 run.

    Read-only inspection of the Phase 16 artifact: the recorded run
    inputs and the exact applicable trajectory plans and closed
    compiled-world catalogs are loaded and verified, the stored artifact
    is loaded, verified end to end, and returned only after complete
    verification. Retrieval never executes, replays, evaluates, repairs,
    normalizes, or writes anything. Legacy 1.0.0 runs and not-yet-
    executed 2.0.0 runs have no artifact and return the typed 404;
    corrupted artifacts fail through the typed 409 integrity mapping.
    The response carries the contract-declared state snapshots only -
    never guards, target values, strategy policy content, hidden
    reasoning, evidence, or recommendations.
    """
    return get_verified_run_trajectory_execution(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.get(
    "/v1/runs/{run_id}/trajectory-replay-manifest",
    response_model=RunTrajectoryReplayManifest,
    tags=["runs"],
    summary="Fetch a run's verified trajectory replay manifest",
)
def get_run_trajectory_replay_manifest_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunTrajectoryReplayManifest:
    """Fetch the immutable trajectory replay manifest of a replayed 2.0.0 run.

    Read-only retrieval of an already-created manifest: the recorded run
    and trajectory inputs are verified, the authoritative stored
    execution artifact is loaded and verified first, and the stored
    manifest is verified against the authoritative execution and the
    exact ordered trajectory plan-set hash before it is returned. This
    endpoint never triggers ``replay_run``, evaluation, artifact
    regeneration, or any write. Before a successful replay there is no
    manifest and the typed 404 is returned; corrupted records preserve
    the existing typed 409 conflict/integrity mappings without leaking
    internal reasons, hashes, state values, guards, targets, policies,
    or validation details.
    """
    return get_verified_run_trajectory_replay_manifest(
        store=_store(request), tenant_id=x_tenant_id, run_id=run_id
    )


@router.post(
    "/v1/runs/{run_id}/verify-inputs",
    response_model=RunInputIntegrityManifest,
    tags=["runs"],
    summary="Verify run input integrity",
)
def verify_run_inputs_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> RunInputIntegrityManifest:
    """Verify a run's recorded inputs deterministically and record the manifest.

    Read-only with respect to lifecycle and events: it never changes
    campaign or run state and never creates events, outcomes, evidence,
    briefs, or recommendations. Returns 409 integrity_error for
    inconsistent or tampered inputs.
    """
    verified = verify_run_inputs(store=_store(request), tenant_id=x_tenant_id, run_id=run_id)
    _store(request).put_input_integrity_manifest(x_tenant_id, run_id, verified.manifest)
    record_run_inputs_verified(_store(request), tenant_id=x_tenant_id, manifest=verified.manifest)
    return verified.manifest


@router.post(
    "/v1/domain-packs",
    response_model=DomainPackManifest,
    status_code=201,
    tags=["domain-packs"],
    summary="Register a declarative domain pack manifest",
)
def register_domain_pack_route(
    request_body: DomainPackRegistrationRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainPackManifest:
    """Register a declarative domain pack manifest (metadata only).

    Tenant ownership is derived from the X-Tenant-ID header; the draft
    carries neither a tenant nor a content hash. The content hash is
    computed by the registry and returned with the stored manifest. No
    pack code is loaded, imported, instantiated, or executed, and no
    scenario, world, campaign, run, event, replay, or integrity state is
    touched.
    """
    manifest = register_manifest(
        store=_store(request),
        tenant_id=x_tenant_id,
        identifier=request_body.identifier,
        pack_id=request_body.pack_id,
        name=request_body.name,
        pack_version=request_body.pack_version,
        description=request_body.description,
        supported_api_versions=request_body.supported_api_versions,
        capabilities=request_body.capabilities,
        schema_metadata=request_body.schema_metadata,
        created_at=request_body.created_at,
        metadata=request_body.metadata,
    )
    record_domain_pack_registered(_store(request), tenant_id=x_tenant_id, manifest=manifest)
    return manifest


@router.get(
    "/v1/domain-packs",
    response_model=DomainPackListResponse,
    tags=["domain-packs"],
    summary="List registered domain pack manifests",
)
def list_domain_packs_route(
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainPackListResponse:
    """List the tenant's manifests in deterministic identifier order.

    Only the requesting tenant's manifests are ever visible.
    """
    manifests = list_manifests(store=_store(request), tenant_id=x_tenant_id)
    return DomainPackListResponse(manifests=list(manifests))


@router.get(
    "/v1/domain-packs/{manifest_id}",
    response_model=DomainPackManifest,
    tags=["domain-packs"],
    summary="Fetch one domain pack manifest",
)
def get_domain_pack_route(
    manifest_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainPackManifest:
    """Fetch one tenant-owned manifest.

    Unknown and foreign manifests both return a typed 404; no data about
    another tenant's manifests is ever leaked.
    """
    return get_manifest(store=_store(request), tenant_id=x_tenant_id, manifest_id=manifest_id)


@router.post(
    "/v1/scenarios/{scenario_id}/domain-pack-bindings",
    response_model=DomainPackBinding,
    status_code=201,
    tags=["domain-packs"],
    summary="Bind a registered domain pack manifest to a scenario",
)
def bind_domain_pack_route(
    scenario_id: str,
    request_body: BindDomainPackRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainPackBinding:
    """Bind a registered manifest to a scenario (declarative metadata only).

    The request accepts only ``manifest_id`` and ``bound_at``; every pack
    identity and hash field is copied from the stored immutable manifest.
    Nothing is loaded, imported, instantiated, or executed, and no
    outcomes, evidence, briefs, or recommendations are ever produced.
    """
    binding = bind_manifest(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        manifest_id=request_body.manifest_id,
        bound_at=request_body.bound_at,
    )
    record_domain_pack_bound(_store(request), tenant_id=x_tenant_id, binding=binding)
    return binding


@router.get(
    "/v1/scenarios/{scenario_id}/domain-pack-bindings",
    response_model=DomainPackBindingListResponse,
    tags=["domain-packs"],
    summary="List a scenario's domain pack bindings",
)
def list_domain_pack_bindings_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainPackBindingListResponse:
    """List a scenario's bindings in deterministic manifest-id order.

    Unknown or foreign scenarios return a typed 404; only the requesting
    tenant's bindings are ever visible.
    """
    bindings = list_bindings(store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id)
    return DomainPackBindingListResponse(bindings=list(bindings))


@router.post(
    "/v1/scenarios/{scenario_id}/domain-capability-declarations",
    response_model=DomainCapabilityDeclaration,
    status_code=201,
    tags=["domain-packs"],
    summary="Declare immutable input values for a bound capability",
)
def declare_capability_inputs_route(
    scenario_id: str,
    request_body: DeclareCapabilityInputsRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainCapabilityDeclaration:
    """Declare immutable input values for one capability of a bound manifest.

    The request accepts only ``manifest_id``, ``capability_id``,
    ``input_values``, and ``declared_at``; every identity field (tenant,
    binding id, pack identity, manifest hash, declaration identifier) and
    the declaration content hash come from stored immutable records and
    deterministic computation - never from client input. The stored
    binding snapshot is verified against the registered manifest before
    the declaration is accepted (safe typed 409 on inconsistency), the
    capability must be declared by the manifest, and the input-value keys
    must match its declared ``input_ids`` exactly (typed 422 otherwise).
    Declarations are inert: nothing is executed, interpreted, or invoked,
    and no outcomes, evidence, briefs, or recommendations are produced.
    """
    declaration = declare_capability_inputs(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        manifest_id=request_body.manifest_id,
        capability_id=request_body.capability_id,
        input_values=request_body.input_values,
        declared_at=request_body.declared_at,
    )
    record_capability_inputs_declared(
        _store(request), tenant_id=x_tenant_id, declaration=declaration
    )
    return declaration


@router.get(
    "/v1/scenarios/{scenario_id}/domain-capability-declarations",
    response_model=DomainCapabilityDeclarationListResponse,
    tags=["domain-packs"],
    summary="List a scenario's declared capability inputs",
)
def list_domain_capability_declarations_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainCapabilityDeclarationListResponse:
    """List a scenario's declarations in deterministic manifest-id then capability-id order.

    Unknown or foreign scenarios return a typed 404; only the requesting
    tenant's declarations are ever visible.
    """
    declarations = list_declarations(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )
    return DomainCapabilityDeclarationListResponse(declarations=list(declarations))


@router.post(
    "/v1/scenarios/{scenario_id}/domain-state-models",
    response_model=DomainStateModel,
    status_code=201,
    tags=["domain-packs"],
    summary="Declare a domain state model for a bound manifest",
)
def declare_state_model_route(
    scenario_id: str,
    request_body: DeclareStateModelRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainStateModel:
    """Declare an immutable, declarative state model for a bound manifest.

    The request accepts only ``manifest_id``, ``state_model_id``,
    ``state_fields``, ``declared_at``, and optional ``metadata``. All
    identity fields (binding id, pack identity, manifest hash) and the
    deterministic model identifier and content hash come from stored
    records and application logic - never from the client. The stored
    binding snapshot is verified against the registered manifest before
    the model is accepted (safe typed 409 on inconsistency); duplicates
    are rejected and never overwrite. State models are data only: nothing
    is executed, interpreted, or invoked, and no outcomes, evidence,
    briefs, or recommendations are produced.
    """
    state_model = declare_state_model(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        manifest_id=request_body.manifest_id,
        state_model_id=request_body.state_model_id,
        state_fields=tuple(request_body.state_fields),
        declared_at=request_body.declared_at,
        metadata=request_body.metadata,
    )
    record_domain_state_model_declared(
        _store(request), tenant_id=x_tenant_id, state_model=state_model
    )
    return state_model


@router.get(
    "/v1/scenarios/{scenario_id}/domain-state-models",
    response_model=DomainStateModelListResponse,
    tags=["domain-packs"],
    summary="List a scenario's domain state models",
)
def list_state_models_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainStateModelListResponse:
    """List a scenario's state models in deterministic manifest-id then state-model-id order.

    Unknown or foreign scenarios return a typed 404; only the requesting
    tenant's state models are ever visible.
    """
    state_models = list_state_models(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )
    return DomainStateModelListResponse(state_models=list(state_models))


@router.post(
    "/v1/scenarios/{scenario_id}/domain-state-transitions",
    response_model=DomainStateTransition,
    status_code=201,
    tags=["domain-packs"],
    summary="Declare a domain state transition for a declared state model",
)
def declare_state_transition_route(
    scenario_id: str,
    request_body: DeclareStateTransitionRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainStateTransition:
    """Declare an immutable, declarative transition specification for a state model.

    The request accepts only ``manifest_id``, ``state_model_id``,
    ``transition_id``, ``description``, ``guard_values``, ``target_values``,
    ``declared_at``, and optional ``metadata``. All identity fields
    (binding id, pack identity, manifest hash, state-model content hash)
    and the deterministic transition identifier and content hash come
    from stored records and application logic - never from the client.
    The stored binding snapshot is verified against the registered
    manifest and the stored state model's copied identity, deterministic
    identifier, content hash, canonical fields, and binding relationship
    are verified before the transition is accepted (safe typed 409 on
    inconsistency); every guard/target key must identify an existing
    state-model field whose declared value kind and allowed values
    exactly match the supplied value (typed 422 otherwise); duplicates
    are rejected and never overwrite. Transitions are declarative data
    only: a guard is never evaluated and a target state patch is never
    applied - nothing is executed, interpreted, or invoked, and no
    outcomes, evidence, briefs, or recommendations are produced.
    """
    transition = declare_transition(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        manifest_id=request_body.manifest_id,
        state_model_id=request_body.state_model_id,
        transition_id=request_body.transition_id,
        description=request_body.description,
        guard_values=request_body.guard_values,
        target_values=request_body.target_values,
        declared_at=request_body.declared_at,
        metadata=request_body.metadata,
    )
    record_domain_state_transition_declared(
        _store(request), tenant_id=x_tenant_id, transition=transition
    )
    return transition


@router.get(
    "/v1/scenarios/{scenario_id}/domain-state-transitions",
    response_model=DomainStateTransitionListResponse,
    tags=["domain-packs"],
    summary="List a scenario's domain state transitions",
)
def list_state_transitions_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainStateTransitionListResponse:
    """List a scenario's transitions in deterministic manifest-id, state-model-id,
    then transition-id order.

    Unknown or foreign scenarios return a typed 404; only the requesting
    tenant's transitions are ever visible.
    """
    transitions = list_transitions(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )
    return DomainStateTransitionListResponse(transitions=list(transitions))


@router.post(
    "/v1/scenarios/{scenario_id}/metric-observations",
    response_model=DomainMetricObservationBinding,
    status_code=201,
    tags=["domain-packs"],
    summary="Declare a domain metric observation binding for a scenario metric",
)
def declare_domain_metric_observation_route(
    scenario_id: str,
    request_body: DomainMetricObservationDeclarationRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainMetricObservationBinding:
    """Declare an immutable, declarative state-to-metric observation binding.

    The request accepts only ``manifest_id``, ``state_model_id``,
    ``metric_id``, ``state_field_id``, ``declared_at``, and optional
    ``metadata``. All authoritative identity fields (tenant, scenario,
    binding id, pack identity, manifest hash, state-model deterministic
    identifier and content hash, state-field value kind, observation
    point) and the deterministic binding identifier and content hash
    come from stored records and application logic - never from the
    client. The stored binding snapshot is verified against the
    registered manifest and the stored state model's copied identity,
    deterministic identifier, content hash, canonical fields, and
    binding relationship are verified before the binding is accepted
    (safe typed 409 on inconsistency); ``metric_id`` must identify
    exactly one metric of the stored scenario, ``state_field_id`` must
    identify an existing state-model field whose declared value kind is
    numeric (typed 422 otherwise - string, boolean, and json fields are
    rejected); duplicates for the same scenario metric are rejected and
    never overwrite. Bindings are declarative provenance data only:
    nothing is inspected, extracted, evaluated, aggregated, or executed,
    and no domain pack is ever loaded or invoked. No operational-activity
    event is recorded for this declaration.
    """
    observation = declare_domain_metric_observation(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        manifest_id=request_body.manifest_id,
        state_model_id=request_body.state_model_id,
        metric_id=request_body.metric_id,
        state_field_id=request_body.state_field_id,
        declared_at=request_body.declared_at,
        metadata=request_body.metadata,
    )
    return observation


@router.get(
    "/v1/scenarios/{scenario_id}/metric-observations",
    response_model=DomainMetricObservationListResponse,
    tags=["domain-packs"],
    summary="List a scenario's domain metric observation bindings",
)
def list_domain_metric_observations_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> DomainMetricObservationListResponse:
    """List a scenario's observation bindings in deterministic metric-id order.

    Unknown or foreign scenarios return a typed 404; only the requesting
    tenant's observation bindings are ever visible. The listing is
    read-only and never creates operational-activity events.
    """
    observations = list_domain_metric_observations(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )
    return DomainMetricObservationListResponse(observations=list(observations))


@router.get(
    "/v1/operational-activity",
    response_model=OperationalActivityListResponse,
    tags=["operational-activity"],
    summary="List a tenant's operational activity feed",
)
def list_operational_activity_route(
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    after_sequence: int | None = Query(
        default=None,
        ge=-1,
        description="Return only events strictly after this tenant-local sequence cursor "
        "(-1 retrieves everything; defaults to the beginning of the feed)",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=MAX_ACTIVITY_LIMIT,
        description=f"Maximum number of events to return (1-{MAX_ACTIVITY_LIMIT}, default 20)",
    ),
) -> OperationalActivityListResponse:
    """List one bounded page of the tenant's operational activity feed.

    Read-only operational observability: this endpoint never creates
    activity events itself. Events are returned in ascending sequence
    order strictly after ``after_sequence``; ``next_after_sequence`` is
    the cursor for the next request and ``latest_sequence`` is the
    tenant's newest sequence (-1 when the tenant has no activity). Only
    the requesting tenant's events are ever visible; an empty feed
    returns an empty typed list.
    """
    events = list_activity(_store(request), x_tenant_id, after_sequence=after_sequence, limit=limit)
    next_cursor = (
        events[-1].sequence if events else (after_sequence if after_sequence is not None else -1)
    )
    return OperationalActivityListResponse(
        events=list(events),
        next_after_sequence=next_cursor,
        latest_sequence=latest_sequence(_store(request), x_tenant_id),
    )


COLONY_UI_DIR = Path(__file__).resolve().parents[1] / "colony_ui"


@router.get("/colony/", include_in_schema=False, summary="Encomm Colony local observability UI")
def colony_index() -> FileResponse:
    """Serve the Encomm Colony local observability UI (Phase 10).

    Colony is an optional, strictly read-only companion presentation
    layer for KALHAS operational observability: plain static HTML/CSS/JS
    served from the same application (no CORS, no credentials, no
    external assets). The page itself issues only ``GET
    /v1/operational-activity`` requests with manual pull refresh.

    Serving Colony never touches the store and adds no background work;
    the KALHAS API remains fully usable if Colony is never opened.
    """
    return FileResponse(COLONY_UI_DIR / "index.html", media_type="text/html")


@router.get("/colony/styles.css", include_in_schema=False, summary="Colony stylesheet")
def colony_styles() -> FileResponse:
    """Serve the Colony stylesheet (local static asset, no external fonts)."""
    return FileResponse(COLONY_UI_DIR / "styles.css", media_type="text/css")


@router.get("/colony/app.js", include_in_schema=False, summary="Colony client script")
def colony_app_js() -> FileResponse:
    """Serve the Colony client script (local static asset)."""
    return FileResponse(COLONY_UI_DIR / "app.js", media_type="text/javascript")
