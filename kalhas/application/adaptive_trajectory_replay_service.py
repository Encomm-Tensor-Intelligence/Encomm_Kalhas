"""Runtime-4 exact replay recomputation service (H28-S07B2).

Owns exactly one public entry point,
:func:`replay_adaptive_run`, which independently regenerates a complete
stored :class:`AdaptiveRunTrajectoryExecution` from verified recorded
authorities, compares the regenerated canonical artifact and content hash
to the stored authority, builds and verifies the deterministic
:class:`AdaptiveRunTrajectoryReplayManifest`, and persists exactly that
manifest through the already-verified B1B store surface.

The service accepts only the store and the deterministic
``tenant_id``/``run_id`` identifiers - no authorities, catalogs,
policy, plans, declarations, states, timestamps, hashes, or status. The
recorded execution is loaded through the store's verified execution
getter; the recorded runtime-4 :class:`RunStatus`/:class:`RunPlan`
authority is loaded through the store's established private runtime-4
authority surface (the exact surface the B1B replay-manifest authority
uses), and must be exactly COMPLETE with ``event_hash`` None; the
complete campaign/world/seed/realization/policy/declaration/action-plan/
external-bundle authority chain is resolved through the store's own
verified authority-chain resolver - the exact authorities the execution
getter verifies against. The execution is then regenerated through the
existing pure :func:`build_adaptive_run_trajectory_execution` path
(called exactly once) with only the causal horizon derived from the
stored execution cardinality (``len(decision_events) - 1``) and, when
the verified execution carries an external bundle, an
application-local :class:`ExternalObservationInputBundleDraft`
reconstructed from the already-verified immutable stored bundle entries
and ``accepted_at``. No stored observation event, policy-state
snapshot, decision event, switch event, trajectory result, or state
value is ever injected into the rebuild; nothing is executed, no
``RunStatus`` is mutated, and no execution is written.

After regeneration the stored and regenerated executions are compared by
exact canonical JSON bytes **and** content-hash equality; any difference
raises the typed :class:`AdaptiveRunTrajectoryReplayManifestIntegrityError`
and no manifest is written. The manifest is built completely in memory
from the verified stored execution, the independently regenerated
execution hash, the runtime literal ``4.0.0``, and ``replayed_at`` equal
to the authoritative recorded ``RunPlan.created_at`` (never a clock);
its identifier and self-covering content hash are derived only through
the B1A helpers, and the complete record is verified through
:func:`verify_adaptive_run_trajectory_replay_manifest_record` before any
persistence.

Existing-manifest behavior is deterministic and idempotent: when no
manifest exists the single B1B put happens only after every check
passes; when a manifest exists it is loaded through the verified getter,
must equal the newly recomputed expected manifest exactly (canonical
bytes), and the verified stored manifest is returned without a write - a
differing or corrupt existing manifest raises the typed replay integrity
error and is never overwritten or repaired. Every failure before the one
optional manifest write is atomic: no manifest, execution, run-status,
campaign, policy, plan, observation, activity, or sequence mutation.

The service is strictly local and read-only except for the single
optional manifest put: no clock, RNG, UUID, network, provider,
filesystem, API, adapter, NEXUS, or LEGION surface; no historical
runtime-1/2/3 replay or store behavior is touched; public messages never
leak identifiers, hashes, values, channels, steps, or foreign existence.
"""

from __future__ import annotations

from typing import NoReturn

from kalhas.application.adaptive_run_execution_builder import (
    AdaptiveRunExecutionBuildDraft,
    build_adaptive_run_trajectory_execution,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionNotFoundError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    AdaptiveRunExecutionAuthorities,
)
from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
    AdaptiveRunTrajectoryReplayManifestNotFoundError,
    AdaptiveRunTrajectoryReplayManifestValidationError,
)
from kalhas.application.adaptive_trajectory_replay_identity import (
    adaptive_run_trajectory_replay_manifest_content_hash,
    adaptive_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.adaptive_trajectory_replay_integrity import (
    verify_adaptive_run_trajectory_replay_manifest_record,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    KalhasDomainError,
    RunNotFoundError,
    TrajectoryPlansNotFoundError,
    WorldNotFoundError,
)
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.strategy_trajectory_service import ModelTrajectoryCatalog
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.shared import AwareDatetime
from kalhas.contracts.v1.world import WorldVersion


def _reject_validation(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe replay validation error with an internal reason."""
    raise AdaptiveRunTrajectoryReplayManifestValidationError(tenant_id, run_id, reason)


def _reject_integrity(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe replay integrity error with an internal reason."""
    raise AdaptiveRunTrajectoryReplayManifestIntegrityError(tenant_id, run_id, reason)


#: The accepted missing-authority cause family, mirroring the established
#: execution-service doctrine in
#: ``adaptive_run_execution_service._load_authorities``: genuinely missing
#: policy-bound authorities surface through the store's read-time policy
#: verification as a wrapped integrity error whose bounded ``__cause__``
#: chain terminates in one of these typed NotFound-family errors, and are
#: classified as replay validation; every other cause is a corrupt or
#: disagreeing stored authority and remains replay integrity.
_MISSING_AUTHORITY_CAUSES: tuple[type[BaseException], ...] = (
    CampaignNotFoundError,
    WorldNotFoundError,
    TrajectoryPlansNotFoundError,
    RuntimeObservationDeclarationNotFoundError,
)


def _has_missing_authority_cause(exc: BaseException) -> bool:
    """True when the bounded exception ``__cause__`` chain carries a missing authority.

    Walks the ``__cause__`` chain with a fixed bound and a visited-set
    guard (never unbounded, never message/reason parsing). Only the
    explicit accepted NotFound-family causes above are classified;
    corrupt or disagreeing authorities never carry one and stay replay
    integrity.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(6):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, _MISSING_AUTHORITY_CAUSES):
            return True
        current = current.__cause__
    return False


def _load_verified_execution(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> AdaptiveRunTrajectoryExecution:
    """Load the recorded runtime-4 execution through the verified getter.

    The established verified execution getter strictly revalidates and
    cross-authority verifies the stored record on every read, so the
    returned execution is the already-verified authority. Missing,
    foreign, or old-domain failures are converted to the safe typed
    replay validation error; corrupt stored authority converts to the
    safe typed replay integrity error - never a raw error, and never
    repaired. Genuinely missing policy-bound authorities that surface
    wrapped inside the store's typed integrity error (per the
    established execution-service doctrine) are classified as replay
    validation; corrupt or disagreeing authorities stay replay
    integrity. Nothing is written or executed.
    """
    try:
        return store.get_adaptive_run_trajectory_execution(tenant_id=tenant_id, run_id=run_id)
    except (
        AdaptiveRunTrajectoryExecutionNotFoundError,
        AdaptiveRunTrajectoryExecutionValidationError,
        RunNotFoundError,
        CampaignNotFoundError,
    ) as exc:
        raise AdaptiveRunTrajectoryReplayManifestValidationError(
            tenant_id, run_id, reason="execution or run authority missing"
        ) from exc
    except AdaptiveRunTrajectoryExecutionIntegrityError as exc:
        if _has_missing_authority_cause(exc):
            raise AdaptiveRunTrajectoryReplayManifestValidationError(
                tenant_id, run_id, reason="execution or run authority missing"
            ) from exc
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="execution authority corrupt"
        ) from exc


def _load_run_authority(
    store: InMemoryScenarioStore,
    execution: AdaptiveRunTrajectoryExecution,
    *,
    tenant_id: str,
    run_id: str,
) -> tuple[RunPlan, RunStatus]:
    """Load and reverify the recorded runtime-4 run status and run plan.

    Reuses the store's established private runtime-4 run-plan/run-status
    authority surface (the exact surface the B1B replay-manifest
    authority uses): the recorded :class:`RunStatus` and its exact
    verified :class:`RunPlan` are returned already checked for runtime-4
    literal, deterministic identity, ownership, and run-plan agreement.
    Missing run authority converts to the safe typed replay validation
    error; corrupt run authority converts to the safe typed replay
    integrity error.
    """
    try:
        return store._adaptive_run_plan_authority(execution, tenant_id=tenant_id, run_id=run_id)
    except (
        RunNotFoundError,
        CampaignNotFoundError,
        AdaptiveRunTrajectoryExecutionValidationError,
    ) as exc:
        raise AdaptiveRunTrajectoryReplayManifestValidationError(
            tenant_id, run_id, reason="run authority missing"
        ) from exc
    except AdaptiveRunTrajectoryExecutionIntegrityError as exc:
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="run authority corrupt"
        ) from exc


def _load_authorities(
    store: InMemoryScenarioStore,
    execution: AdaptiveRunTrajectoryExecution,
    *,
    tenant_id: str,
    run_id: str,
    run_plan: RunPlan,
    run_status: RunStatus,
) -> AdaptiveRunExecutionAuthorities:
    """Resolve the complete verified authority chain for the rebuild.

    Reuses the store's own verified authority-chain resolver - the exact
    surface the execution getter verifies against - to resolve the
    complete campaign/world/seed/realization/policy/declaration/
    action-plan/external-bundle authority chain from recorded stored
    authorities. Missing authorities convert to the safe typed replay
    validation error; corrupt or disagreeing authorities convert to the
    safe typed replay integrity error. Genuinely missing policy-bound
    authorities that surface wrapped inside the store's typed integrity
    error (per the established execution-service doctrine) are
    classified as replay validation; corrupt or disagreeing authorities
    stay replay integrity. Nothing is written or executed.
    """
    try:
        return store._adaptive_run_authorities(
            execution,
            tenant_id=tenant_id,
            run_id=run_id,
            run_plan=run_plan,
            run_status=run_status,
        )
    except AdaptiveRunTrajectoryExecutionValidationError as exc:
        raise AdaptiveRunTrajectoryReplayManifestValidationError(
            tenant_id, run_id, reason="authority chain missing"
        ) from exc
    except AdaptiveRunTrajectoryExecutionIntegrityError as exc:
        if _has_missing_authority_cause(exc):
            raise AdaptiveRunTrajectoryReplayManifestValidationError(
                tenant_id, run_id, reason="authority chain missing"
            ) from exc
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="authority chain corrupt"
        ) from exc


def _derived_catalogs(world: WorldVersion) -> tuple[ModelTrajectoryCatalog, ...]:
    """The closed canonical model-trajectory catalogs of the compiled world.

    Derived exclusively from the verified compiled world in canonical
    ascending state-model-identifier order: exactly one
    :class:`ModelTrajectoryCatalog` per embedded state model with its
    exact embedded transitions.
    """
    entries = extract_world_catalog(world)
    return tuple(
        sorted(
            (
                ModelTrajectoryCatalog(
                    state_model=model,
                    transitions=tuple(
                        transition
                        for transition in entries.transitions
                        if transition.state_model_id == model.state_model_id
                    ),
                )
                for model in entries.state_models
            ),
            key=lambda catalog: catalog.state_model.identifier,
        )
    )


def _reconstruct_bundle_draft(
    execution: AdaptiveRunTrajectoryExecution,
    authorities: AdaptiveRunExecutionAuthorities,
    *,
    tenant_id: str,
    run_id: str,
) -> ExternalObservationInputBundleDraft | None:
    """Reconstruct the application-local bundle draft from the verified bundle.

    When the verified execution carries an external bundle, the
    application-local :class:`ExternalObservationInputBundleDraft` is
    reconstructed only from the already-verified immutable stored bundle
    entries and ``accepted_at``, preserving exact ``observation_id`` /
    ``source_step_index`` / ``value`` bytes. When the execution carries
    no bundle, no draft is returned. A recorded bundle reference with a
    missing authority never happens (the authority chain already
    resolved and verified it) and fails closed. Nothing is re-accepted
    or rewritten.
    """
    if execution.external_observation_input_bundle_id is None:
        return None
    bundle = authorities.external_bundle
    if bundle is None:
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="recorded external bundle authority missing"
        )
    return ExternalObservationInputBundleDraft(
        entries=tuple(
            ExternalObservationInputValueDraft(
                observation_id=entry.observation_id,
                source_step_index=entry.source_step_index,
                value=entry.value,
            )
            for entry in bundle.entries
        ),
        accepted_at=bundle.accepted_at,
    )


def _regenerate(
    store: InMemoryScenarioStore,
    authorities: AdaptiveRunExecutionAuthorities,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    draft: AdaptiveRunExecutionBuildDraft,
    *,
    tenant_id: str,
    run_id: str,
) -> AdaptiveRunTrajectoryExecution:
    """Independently regenerate the execution through the pure builder.

    Calls :func:`build_adaptive_run_trajectory_execution` exactly once
    with only the derived causal horizon and the reconstructed bundle
    draft; every stored authority value comes from the verified
    authorities. The builder's own safe typed validation failures
    convert to the replay validation error and its safe typed integrity
    failures (and any other domain failure meaning the recorded
    authorities cannot reproduce the stored execution) convert to the
    replay integrity error.
    """
    try:
        return build_adaptive_run_trajectory_execution(
            store,
            authorities=authorities,
            catalogs=catalogs,
            draft=draft,
        )
    except AdaptiveRunTrajectoryExecutionValidationError as exc:
        raise AdaptiveRunTrajectoryReplayManifestValidationError(
            tenant_id, run_id, reason="execution regeneration input invalid"
        ) from exc
    except (AdaptiveRunTrajectoryExecutionIntegrityError, KalhasDomainError) as exc:
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="execution regeneration failed"
        ) from exc


def _build_manifest(
    execution: AdaptiveRunTrajectoryExecution,
    regenerated: AdaptiveRunTrajectoryExecution,
    *,
    replayed_at: AwareDatetime,
    tenant_id: str,
    run_id: str,
) -> AdaptiveRunTrajectoryReplayManifest:
    """Build the deterministic replay manifest completely in memory.

    Every provenance field is copied exactly from the verified stored
    execution; ``expected_execution_hash`` is the stored execution's
    content hash and ``recomputed_execution_hash`` the independently
    regenerated execution's content hash (already proven equal);
    ``replayed_at`` is the authoritative recorded RunPlan creation time;
    and the identifier and self-covering content hash are derived only
    through the B1A helpers. The complete record is then verified
    through the B1A full-record verifier before it may be persisted.
    """
    try:
        payload: dict[str, object] = {
            "identifier": adaptive_run_trajectory_replay_manifest_identifier(
                run_id=execution.run_id,
                runtime_version=execution.runtime_version,
            ),
            "tenant_id": execution.tenant_id,
            "run_id": execution.run_id,
            "campaign_id": execution.campaign_id,
            "adaptive_run_trajectory_execution_id": execution.identifier,
            "world_version_id": execution.world_version_id,
            "world_content_hash": execution.world_content_hash,
            "scenario_seed_id": execution.scenario_seed_id,
            "seed_content_hash": execution.seed_content_hash,
            "world_realization_id": execution.world_realization_id,
            "world_realization_content_hash": execution.world_realization_content_hash,
            "adaptive_policy_identifier": execution.adaptive_policy_identifier,
            "policy_id": execution.policy_id,
            "adaptive_policy_content_hash": execution.adaptive_policy_content_hash,
            "external_observation_input_bundle_id": (
                execution.external_observation_input_bundle_id
            ),
            "external_observation_input_bundle_content_hash": (
                execution.external_observation_input_bundle_content_hash
            ),
            "runtime_version": execution.runtime_version,
            "input_hash": execution.input_hash,
            "trajectory_plan_set_hash": execution.trajectory_plan_set_hash,
            "expected_execution_hash": execution.content_hash,
            "recomputed_execution_hash": regenerated.content_hash,
            "replay_classification": "exact",
            "replayed_at": replayed_at,
            "content_hash": "0" * 64,
        }
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(payload)
        finalized = manifest.model_copy(
            update={"content_hash": adaptive_run_trajectory_replay_manifest_content_hash(manifest)}
        )
        verify_adaptive_run_trajectory_replay_manifest_record(
            finalized,
            execution=execution,
            replayed_at=replayed_at,
        )
    except AdaptiveRunTrajectoryReplayManifestIntegrityError:
        raise
    except (TypeError, ValueError, AttributeError) as exc:
        raise AdaptiveRunTrajectoryReplayManifestIntegrityError(
            tenant_id, run_id, reason="manifest violates its contract"
        ) from exc
    return finalized


def replay_adaptive_run(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> AdaptiveRunTrajectoryReplayManifest:
    """Independently recompute, verify, and persist a run's exact replay manifest.

    Loads and verifies the complete recorded authority chain, regenerates
    the complete :class:`AdaptiveRunTrajectoryExecution` through the pure
    builder, requires exact canonical bytes and content-hash equality
    with the stored authority, builds and verifies the deterministic
    :class:`AdaptiveRunTrajectoryReplayManifest` in memory, and persists
    exactly that manifest through the B1B store surface. A second
    identical call returns the verified stored manifest without a write;
    a differing or corrupt existing manifest is never overwritten or
    repaired. Every failure before the single optional manifest write is
    atomic and typed. See the module docstring for the full contract.
    """
    try:
        if type(tenant_id) is not str or type(run_id) is not str or not tenant_id or not run_id:
            raise AdaptiveRunTrajectoryReplayManifestValidationError(
                tenant_id if isinstance(tenant_id, str) else "",
                run_id if isinstance(run_id, str) else "",
                reason="tenant_id and run_id must be exact non-empty strings",
            )
        execution = _load_verified_execution(store, tenant_id=tenant_id, run_id=run_id)
        run_plan, run_status = _load_run_authority(
            store, execution, tenant_id=tenant_id, run_id=run_id
        )
        # The recorded runtime-4 run must be exactly COMPLETE with no
        # event hash; any other recorded lifecycle state is a mismatch
        # against a stored execution authority and fails closed.
        if run_status.state is not RunState.COMPLETE or run_status.event_hash is not None:
            _reject_integrity(tenant_id, run_id, "recorded run state mismatch")
        authorities = _load_authorities(
            store,
            execution,
            tenant_id=tenant_id,
            run_id=run_id,
            run_plan=run_plan,
            run_status=run_status,
        )
        catalogs = _derived_catalogs(authorities.world)
        # The causal horizon is derived exclusively from the verified
        # stored execution cardinality - never from the caller, the
        # store, metadata, or any injected evidence.
        final_decision_step = len(execution.decision_events) - 1
        bundle_draft = _reconstruct_bundle_draft(
            execution, authorities, tenant_id=tenant_id, run_id=run_id
        )
        draft = AdaptiveRunExecutionBuildDraft(
            final_decision_step=final_decision_step,
            external_bundle_draft=bundle_draft,
        )
        regenerated = _regenerate(
            store,
            authorities,
            catalogs,
            draft,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        # Exact canonical JSON bytes AND content-hash equality; any
        # difference is a typed replay integrity error and no manifest
        # is written.
        if canonical_json(regenerated.model_dump(mode="json")) != canonical_json(
            execution.model_dump(mode="json")
        ):
            _reject_integrity(
                tenant_id, run_id, "regenerated execution differs from the stored execution"
            )
        if regenerated.content_hash != execution.content_hash:
            _reject_integrity(
                tenant_id, run_id, "regenerated execution hash differs from the stored execution"
            )
        manifest = _build_manifest(
            execution,
            regenerated,
            replayed_at=run_plan.created_at,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        # Existing-manifest behavior: load through the verified getter;
        # an exactly equal stored manifest is returned without a write; a
        # differing or corrupt stored manifest raises the typed replay
        # integrity error and is never overwritten or repaired.
        try:
            existing = store.get_adaptive_run_trajectory_replay_manifest(
                tenant_id=tenant_id, run_id=run_id
            )
        except AdaptiveRunTrajectoryReplayManifestNotFoundError:
            existing = None
        if existing is not None:
            if canonical_json(existing.model_dump(mode="json")) != canonical_json(
                manifest.model_dump(mode="json")
            ):
                _reject_integrity(
                    tenant_id, run_id, "existing manifest differs from the recomputed manifest"
                )
            return existing
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=tenant_id, run_id=run_id, manifest=manifest
        )
        return store.get_adaptive_run_trajectory_replay_manifest(tenant_id=tenant_id, run_id=run_id)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        _reject_validation(
            tenant_id if isinstance(tenant_id, str) else "",
            run_id if isinstance(run_id, str) else "",
            reason="input violates its contract",
        )


__all__ = ["replay_adaptive_run"]
