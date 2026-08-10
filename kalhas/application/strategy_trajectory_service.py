"""Immutable strategy-bound trajectory-planning service (Phase 15).

Planning and recording only. LEGION *proposes* an explicitly ordered
sequence of transition references through the extended ``LegionAdapter``
boundary; KALHAS *verifies, binds, hashes, and stores* the resulting
immutable ``StrategyTrajectoryPlan`` for one prepared campaign, one
verified compiled world, one exact stored strategy candidate, and one
state model embedded in that world. Nothing here evaluates or executes a
trajectory: no state is derived, no guard is compared, no target is
applied, and ``evaluate_trajectory`` is never called.

Authoritative inputs come **only** from verified stored records:

- the campaign (identity, seed ensemble, stored run-plan matrix) and its
  exact COMPILED status;
- the stored ``WorldVersion`` and ``WorldManifest`` after Phase 14
  compiled-world verification;
- the state models and transitions **embedded in the compiled world
  snapshot** - never newer declarations from the live registries;
- the exact stored ``StrategyCandidate`` records referenced by the
  campaign, in campaign strategy order.

Every LEGION request is authoritative (KALHAS derives its identifier from
the canonical campaign/world/strategy/state-model identity) and detached:
an authoritative request snapshot is retained in the service and only a
disposable deep copy crosses the adapter boundary, so a hostile adapter
can never influence plan construction after the call returns. Every
draft is re-validated - even a Pydantic instance created through a
validator-bypassing path - and its proposed sequence is preserved
exactly, including repetitions: KALHAS never selects, sorts,
deduplicates, or reorders. Plans are built exclusively from the
authoritative stored records (campaign, verified compiled world, stored
strategy candidate, closed world catalog) - never from the boundary
request copy. The complete plan matrix is built and validated before the
first plan is stored; any invalid draft or adapter failure stores
nothing.

The world catalog is *closed*: every embedded transition must map to
exactly one embedded state model by manifest, state-model id, and
state-model content hash, with deterministic identifiers and no
duplicates - orphan, ambiguous, duplicate, or identity-invalid snapshots
fail before the first LEGION call with a safe typed integrity error. The
same closed construction is used when verifying stored plans on read.

Hashes and identifiers use only the repository's canonical JSON + SHA-256
conventions. There is no second world-hash algorithm, no wall clock, no
randomness, no network, and no domain-specific logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from kalhas.adapters.legion import LegionAdapter
from kalhas.application.domain_errors import (
    CampaignNotPlanningStateError,
    InvalidTrajectoryDraftError,
    RunInputIntegrityError,
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansAlreadyPreparedError,
    TrajectoryPlansNotFoundError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.domain_state_model_service import state_model_identifier
from kalhas.application.domain_state_transition_service import transition_identifier
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_trajectory_plan,
)
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION, plan_runs, run_identifier
from kalhas.application.state_transition_engine import validate_transition_catalog
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
    StrategyTrajectoryTransitionReference,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion

_REQUEST_ID_PREFIX = "trajectory-request-"
_PLAN_ID_PREFIX = "trajectory-plan-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def strategy_candidate_content_hash(candidate: StrategyCandidate) -> str:
    """Canonical SHA-256 of the exact full strategy candidate snapshot.

    The digest covers the candidate's complete canonical serialization
    (identity, policy, observations, assumptions, metadata), so mapping
    insertion order inside nested strategy data never affects it.
    """
    return sha256_hex(canonical_json(candidate.model_dump(mode="json")))


def _trajectory_identity_canonical(
    *,
    campaign_id: str,
    world_version_id: str,
    strategy_candidate_id: str,
    state_model_identifier: str,
) -> str:
    """Canonical identity payload shared by request and plan identifiers."""
    return canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "strategy_candidate_id": strategy_candidate_id,
            "state_model_identifier": state_model_identifier,
        }
    )


def trajectory_request_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    strategy_candidate_id: str,
    state_model_identifier: str,
) -> str:
    """Deterministic request identifier, derived by KALHAS, never LEGION.

    Hash-derived from the canonical campaign/world/strategy/state-model
    identity with a readable, distinct prefix. Identical inputs always
    yield the identical identifier.
    """
    canonical = _trajectory_identity_canonical(
        campaign_id=campaign_id,
        world_version_id=world_version_id,
        strategy_candidate_id=strategy_candidate_id,
        state_model_identifier=state_model_identifier,
    )
    return f"{_REQUEST_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def trajectory_plan_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    strategy_candidate_id: str,
    state_model_identifier: str,
) -> str:
    """Deterministic plan identifier, hash-derived from the same identity."""
    canonical = _trajectory_identity_canonical(
        campaign_id=campaign_id,
        world_version_id=world_version_id,
        strategy_candidate_id=strategy_candidate_id,
        state_model_identifier=state_model_identifier,
    )
    return f"{_PLAN_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def trajectory_plan_content_hash(plan: StrategyTrajectoryPlan) -> str:
    """Canonical SHA-256 of the complete plan content, excluding content_hash.

    The digest covers the full canonical plan - identity, strategy and
    state-model references, and the ordered transition references - so
    tuple ordering and transition repetitions are significant: changing
    any transition position or reference changes the hash.
    """
    payload = plan.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _load_verified_world(
    store: InMemoryScenarioStore,
    tenant_id: str,
    world_version_id: str,
) -> tuple[WorldVersion, WorldManifest]:
    """Load a world and manifest and prove they are exactly compiler output.

    A missing manifest is an integrity error (never a 404-style not
    found); a corrupted world is rejected with the typed
    :class:`WorldSnapshotIntegrityError` before any LEGION request.
    """
    world = store.get_world(tenant_id, world_version_id)
    try:
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError:
        raise WorldSnapshotIntegrityError(
            world_version_id, reason="world manifest missing"
        ) from None
    verify_world_snapshot(world, manifest)
    return world, manifest


@dataclass(frozen=True)
class ModelTrajectoryCatalog:
    """One transition-capable state model and its embedded transitions."""

    state_model: DomainStateModel
    transitions: tuple[DomainStateTransition, ...]


def closed_world_catalogs(world: WorldVersion) -> tuple[ModelTrajectoryCatalog, ...]:
    """Build the closed, validated transition-capable catalog set of a world.

    Only snapshots embedded in the compiled world are used, in the
    compiler's canonical ordering. The catalog is *closed*: every
    embedded transition must map to **exactly one** embedded state model
    by its exact ownership key (``manifest_id``, ``state_model_id``,
    ``state_model_content_hash``) - no transition may remain unmatched
    or be silently ignored. State-model and transition deterministic
    identifiers must equal the canonical derivations, and no state-model
    identifier, ownership key, or transition identifier may be
    duplicated. Every non-empty matched catalog then passes the
    reusable Phase 13 catalog validator (pure and read-only - no state
    derivation, no guard evaluation, no target application). State
    models without embedded transitions remain valid and are ignored for
    planning. Any orphan, ambiguous, duplicate, or identity-invalid
    snapshot raises a safe typed :class:`WorldSnapshotIntegrityError`
    with a generic public message - raw hashes, guards, targets, and
    state values are never exposed.
    """
    catalog = extract_world_catalog(world)
    for state_model in catalog.state_models:
        if state_model.identifier != state_model_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
        ):
            raise WorldSnapshotIntegrityError(
                world.identifier, reason="embedded state model identifier is not deterministic"
            )
    for transition in catalog.transitions:
        if transition.identifier != transition_identifier(
            scenario_id=transition.scenario_id,
            manifest_id=transition.manifest_id,
            state_model_id=transition.state_model_id,
            transition_id=transition.transition_id,
        ):
            raise WorldSnapshotIntegrityError(
                world.identifier, reason="embedded transition identifier is not deterministic"
            )
    model_keys = [
        (model.manifest_id, model.state_model_id, model.content_hash)
        for model in catalog.state_models
    ]
    if len(model_keys) != len(set(model_keys)):
        raise WorldSnapshotIntegrityError(
            world.identifier, reason="duplicate state model ownership keys"
        )
    model_identifiers = [model.identifier for model in catalog.state_models]
    if len(model_identifiers) != len(set(model_identifiers)):
        raise WorldSnapshotIntegrityError(
            world.identifier, reason="duplicate state model identifiers"
        )
    transition_identifiers = [transition.identifier for transition in catalog.transitions]
    if len(transition_identifiers) != len(set(transition_identifiers)):
        raise WorldSnapshotIntegrityError(
            world.identifier, reason="duplicate transition identifiers"
        )
    models_by_key = {
        (model.manifest_id, model.state_model_id, model.content_hash): model
        for model in catalog.state_models
    }
    grouped: dict[tuple[str, str, str], list[DomainStateTransition]] = {}
    for transition in catalog.transitions:
        key = (
            transition.manifest_id,
            transition.state_model_id,
            transition.state_model_content_hash,
        )
        if key not in models_by_key:
            if any(
                model.manifest_id == transition.manifest_id
                and model.state_model_id == transition.state_model_id
                for model in catalog.state_models
            ):
                raise WorldSnapshotIntegrityError(
                    world.identifier,
                    reason="embedded transition state-model content hash mismatch",
                )
            raise WorldSnapshotIntegrityError(
                world.identifier, reason="embedded transition has no matching state model"
            )
        grouped.setdefault(key, []).append(transition)
    capable: list[ModelTrajectoryCatalog] = []
    for state_model in catalog.state_models:
        key = (state_model.manifest_id, state_model.state_model_id, state_model.content_hash)
        transitions = tuple(grouped.get(key, ()))
        if not transitions:
            continue
        validate_transition_catalog(state_model, transitions)
        capable.append(ModelTrajectoryCatalog(state_model=state_model, transitions=transitions))
    return tuple(capable)


# Backward-compatible aliases: earlier phases imported the private names;
# the public names above are the single source of truth from Phase 16 on.
_ModelTrajectoryCatalog = ModelTrajectoryCatalog
_closed_world_catalogs = closed_world_catalogs


def _revalidate_draft(draft: StrategyTrajectoryPlanDraft) -> StrategyTrajectoryPlanDraft:
    """Re-validate a draft even when it bypassed contract validation.

    A draft built through ``model_construct``/``model_copy`` (which never
    re-run validators) or returned as a foreign object never reaches
    planning: the proposal is re-validated from its serialized form,
    enforcing the strict field set and the non-empty / maximum-1000
    sequence bounds.
    """
    if not isinstance(draft, StrategyTrajectoryPlanDraft):
        raise InvalidTrajectoryDraftError(reason="draft is not a plan proposal")
    try:
        return StrategyTrajectoryPlanDraft.model_validate(draft.model_dump(mode="json"))
    except (ValidationError, AttributeError, TypeError):
        raise InvalidTrajectoryDraftError(reason="draft is not a valid plan proposal") from None


def _build_authoritative_plan(
    *,
    request: StrategyTrajectoryPlanRequest,
    draft: StrategyTrajectoryPlanDraft,
    campaign: CampaignSpec,
    world: WorldVersion,
    strategy: StrategyCandidate,
    catalog: ModelTrajectoryCatalog,
) -> StrategyTrajectoryPlan:
    """Verify one untrusted draft and build the authoritative immutable plan.

    ``request`` is the retained authoritative request snapshot: it never
    crosses the adapter boundary (a disposable deep copy does), so its
    identifier is the authoritative identity the draft must reference.
    Every plan field is copied exclusively from the authoritative
    stored records - the campaign, the verified compiled world, the
    stored strategy candidate, and the closed world catalog's state
    model and transitions - never from the boundary request copy or
    anything the adapter could have touched. Only the draft's ordered
    transition identifiers influence the selected sequence, and only
    after re-validation: the draft's request identifier must equal the
    authoritative request identifier, and every proposed transition
    identifier must exist in the catalog. The proposed sequence is
    preserved exactly - including repetitions; KALHAS never selects,
    sorts, deduplicates, or reorders - and every reference is resolved
    to its authoritative stored identifier, logical transition id, and
    content hash. ``planned_at`` is the recorded campaign ``created_at``,
    never wall-clock time and never LEGION.
    """
    validated = _revalidate_draft(draft)
    if validated.request_id != request.identifier:
        raise InvalidTrajectoryDraftError(
            request.identifier, reason="draft request identifier mismatch"
        )
    available = {transition.identifier: transition for transition in catalog.transitions}
    references: list[StrategyTrajectoryTransitionReference] = []
    for position, proposed_identifier in enumerate(validated.ordered_transition_identifiers):
        transition = available.get(proposed_identifier)
        if transition is None:
            raise InvalidTrajectoryDraftError(
                request.identifier,
                reason=f"draft proposes an unknown transition identifier at position {position}",
            )
        references.append(
            StrategyTrajectoryTransitionReference(
                sequence_position=position,
                transition_identifier=transition.identifier,
                transition_id=transition.transition_id,
                transition_content_hash=transition.content_hash,
            )
        )
    state_model = catalog.state_model
    plan = StrategyTrajectoryPlan(
        identifier=trajectory_plan_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            strategy_candidate_id=strategy.identifier,
            state_model_identifier=state_model.identifier,
        ),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategy_candidate_id=strategy.identifier,
        strategy_content_hash=strategy_candidate_content_hash(strategy),
        manifest_id=state_model.manifest_id,
        state_model_identifier=state_model.identifier,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_references=tuple(references),
        content_hash=_PLACEHOLDER_HASH,
        planned_at=campaign.created_at,
    )
    return plan.model_copy(update={"content_hash": trajectory_plan_content_hash(plan)})


def preflight_run_plan_matrix(
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
) -> None:
    """Verify the campaign's exact stored run-plan matrix before LEGION.

    The stored strategy candidate tuple must equal the campaign's
    ``strategy_candidate_ids`` exactly - same identifiers, same order;
    missing, duplicate, reordered, or additional stored candidates are
    rejected. The stored run-plan tuple must then equal the
    deterministically recomputed matrix exactly: ``plan_runs`` over the
    campaign, the verified world content hash, the exact stored
    strategies, the campaign seed ensemble, ``campaign.created_at``, and
    the existing runtime version - so a missing, additional, reordered,
    or duplicated run plan, or a plan with internally plausible but
    different fields, is a matrix-level rejection. Every expected run
    then passes the existing run-input integrity verification (identity,
    ownership, world/strategy/seed references, recomputed input hash).
    Verification is read-only: no integrity manifest is recorded and no
    lifecycle record changes.

    Public since Phase 18 so the campaign trajectory matrix query can
    reuse the exact authoritative run-plan matrix check; the private
    ``_preflight_run_plan_matrix`` name is kept as an alias and the
    behavior is unchanged.
    """
    stored_candidates = store.get_strategy_candidates(tenant_id, campaign.identifier)
    if [candidate.identifier for candidate in stored_candidates] != list(
        campaign.strategy_candidate_ids
    ):
        raise RunInputIntegrityError(
            campaign.identifier, reason="stored strategy candidate collection mismatch"
        )
    # Trajectory planning is valid only for trajectory-runtime campaigns:
    # the recorded run-plan matrix carries the authoritative runtime
    # version, and a legacy or unsupported matrix is rejected with a
    # typed error instead of an obscure matrix mismatch.
    stored_plans = store.get_run_plans(tenant_id, campaign.identifier)
    if not stored_plans:
        raise RunInputIntegrityError(campaign.identifier, reason="stored run-plan matrix missing")
    recorded_version = stored_plans[0].runtime_version
    if recorded_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            recorded_version, operation="trajectory plan preparation"
        )
    expected_plans = plan_runs(
        campaign_id=campaign.identifier,
        tenant_id=tenant_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=stored_candidates,
        seeds=campaign.seed_ensemble,
        created_at=campaign.created_at,
        runtime_version=recorded_version,
    )
    if stored_plans != expected_plans:
        raise RunInputIntegrityError(campaign.identifier, reason="stored run-plan matrix mismatch")
    for plan in expected_plans:
        verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_identifier(plan))


#: Private alias kept so Phase 15/16 call sites keep importing the
#: private name; the behavior is identical.
_preflight_run_plan_matrix = preflight_run_plan_matrix


def prepare_strategy_trajectory_plans(
    *,
    store: InMemoryScenarioStore,
    legion: LegionAdapter,
    tenant_id: str,
    campaign_id: str,
) -> tuple[StrategyTrajectoryPlan, ...]:
    """Authoritatively prepare and store a campaign's trajectory plans.

    The campaign must exist for the tenant and be exactly COMPILED; its
    world and manifest must pass Phase 14 verification; the complete
    stored run-plan matrix must pass run-input integrity verification -
    all **before the first LEGION trajectory request**. Plans are built
    for every strategy candidate (campaign strategy order) and every
    transition-capable state model (compiled-world canonical order), from
    verified stored records only. The complete matrix is validated before
    the first plan is stored; any invalid draft or adapter failure stores
    nothing.

    A verified world with no transition-capable state models makes zero
    LEGION calls, records a successfully prepared empty collection, and
    returns an empty tuple. The function never alters campaign status,
    run plans, run statuses, run events, replay manifests, or
    input-integrity manifests, and never calls ``evaluate_trajectory``.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPILED:
        raise CampaignNotPlanningStateError(campaign_id, status.state.value)
    # A prepared collection - including a successfully prepared empty
    # one - makes a second preparation invalid BEFORE any new LEGION
    # trajectory request. Existing storage is never overwritten or
    # repaired; the store-level duplicate rejection stays as defense in
    # depth.
    try:
        store.get_strategy_trajectory_plans(tenant_id, campaign_id)
    except TrajectoryPlansNotFoundError:
        pass
    else:
        raise TrajectoryPlansAlreadyPreparedError(tenant_id, campaign_id)
    world, _ = _load_verified_world(store, tenant_id, campaign.world_version_id)
    _preflight_run_plan_matrix(store, tenant_id, campaign, world)

    stored_candidates = {
        candidate.identifier: candidate
        for candidate in store.get_strategy_candidates(tenant_id, campaign_id)
    }
    missing = [
        candidate_id
        for candidate_id in campaign.strategy_candidate_ids
        if candidate_id not in stored_candidates
    ]
    if missing:
        raise RunInputIntegrityError(campaign_id, reason="strategy candidate missing")
    strategies = tuple(
        stored_candidates[candidate_id] for candidate_id in campaign.strategy_candidate_ids
    )
    catalogs = closed_world_catalogs(world)

    built: list[StrategyTrajectoryPlan] = []
    for strategy in strategies:
        for catalog in catalogs:
            # The authoritative request snapshot embeds deep copies of
            # every stored record and NEVER crosses the adapter boundary.
            authoritative = StrategyTrajectoryPlanRequest(
                identifier=trajectory_request_identifier(
                    campaign_id=campaign_id,
                    world_version_id=world.identifier,
                    strategy_candidate_id=strategy.identifier,
                    state_model_identifier=catalog.state_model.identifier,
                ),
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                scenario_id=campaign.scenario_id,
                world_version_id=world.identifier,
                world_content_hash=world.content_hash,
                strategy_candidate=strategy.model_copy(deep=True),
                strategy_content_hash=strategy_candidate_content_hash(strategy),
                state_model=catalog.state_model.model_copy(deep=True),
                available_transitions=tuple(
                    transition.model_copy(deep=True) for transition in catalog.transitions
                ),
                requested_at=campaign.created_at,
            )
            # The boundary receives a disposable deep copy: a hostile
            # adapter mutating it can never influence plan construction,
            # which reads only the authoritative request and the
            # authoritative stored records after the call returns.
            draft = legion.request_trajectory_plan(authoritative.model_copy(deep=True))
            built.append(
                _build_authoritative_plan(
                    request=authoritative,
                    draft=draft,
                    campaign=campaign,
                    world=world,
                    strategy=strategy,
                    catalog=catalog,
                )
            )
    plans = tuple(built)
    store.put_strategy_trajectory_plans(tenant_id, campaign_id, plans)
    return plans


def get_strategy_trajectory_plans(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> tuple[StrategyTrajectoryPlan, ...]:
    """Fetch and deterministically verify a campaign's stored trajectory plans.

    The complete stored collection is re-verified before return: exact
    matrix length and ordering (one plan per campaign strategy candidate
    per transition-capable state model), unique plan identifiers and
    (strategy, state model) pairs, ``planned_at`` equal to the campaign
    ``created_at``, and per-plan recomputed identifier and content hash,
    tenant/campaign/scenario/world ownership, exact world content hash,
    strategy candidate identity and full content hash, state-model
    identity and content hash, contiguous sequence positions starting at
    zero, and reference membership in the closed, validated world
    catalog with ordering matching the stored tuple. A tampered
    collection raises :class:`StoredTrajectoryPlanIntegrityError` -
    never repaired, normalized, or silently accepted. Unknown and
    foreign campaigns are indistinguishable
    (:class:`TrajectoryPlansNotFoundError`).
    """
    plans = store.get_strategy_trajectory_plans(tenant_id, campaign_id)
    _verify_stored_plans(store, tenant_id, campaign_id, plans)
    return plans


def _verify_stored_plans(
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
    plans: tuple[StrategyTrajectoryPlan, ...],
) -> None:
    """Pure deterministic verification of the complete stored collection.

    The collection is verified as a whole, never plan by plan. **First**,
    every collection item is strictly revalidated against the complete
    ``StrategyTrajectoryPlan`` contract - exactly a plan instance, every
    field rule re-run over its serialized data with ``strict=True``,
    including the nested ``StrategyTrajectoryTransitionReference``
    contracts and the 1-1000 reference bound - so validator-bypassed
    stored records (empty or oversized reference tuples, malformed
    nested references, foreign objects) are rejected before any field is
    trusted; the temporary revalidated object is discarded and the
    actual stored snapshot is verified. Then the matrix is checked: the
    length must equal the exact expected matrix - one plan per campaign
    strategy candidate, in campaign order, per transition-capable state
    model, in compiled-world canonical order - and plan identifiers and
    (strategy candidate, state model) pairs must be unique and exactly
    the expected set in the exact expected order. Every ``planned_at``
    must equal the campaign ``created_at``, and every plan must pass the
    existing individual identity/hash/reference checks against the
    closed, validated world catalog (the same construction planning
    uses). For a world with no transition-capable state models the only
    valid stored collection is exactly the prepared empty tuple. Any
    mismatch raises :class:`StoredTrajectoryPlanIntegrityError` - the
    tampered collection is never repaired, sorted, normalized, replaced,
    or silently accepted.
    """

    def reject(reason: str) -> StoredTrajectoryPlanIntegrityError:
        return StoredTrajectoryPlanIntegrityError(campaign_id, reason=reason)

    # Strict contract revalidation before any plan field is read: a
    # model_copy/private-injection bypass can leave the plan instance
    # contract-invalid (empty or 1001 references, malformed nested
    # references, wrong object type), and no later check may trust it.
    for plan in plans:
        revalidate_stored_trajectory_plan(plan, campaign_id)

    campaign = store.get_campaign(tenant_id, campaign_id)
    world, _ = _load_verified_world(store, tenant_id, campaign.world_version_id)
    catalogs = closed_world_catalogs(world)
    expected_pairs = [
        (candidate_id, catalog.state_model.identifier)
        for candidate_id in campaign.strategy_candidate_ids
        for catalog in catalogs
    ]
    if len(plans) != len(expected_pairs):
        raise reject("trajectory plan collection length mismatch")
    identifiers = [plan.identifier for plan in plans]
    if len(identifiers) != len(set(identifiers)):
        raise reject("duplicate trajectory plan identifiers")
    pairs = [(plan.strategy_candidate_id, plan.state_model_identifier) for plan in plans]
    if len(pairs) != len(set(pairs)):
        raise reject("duplicate trajectory plan strategy/model pair")
    if set(pairs) != set(expected_pairs):
        raise reject("trajectory plan collection pair mismatch")
    if pairs != expected_pairs:
        raise reject("trajectory plan collection order mismatch")
    if any(plan.planned_at != campaign.created_at for plan in plans):
        raise reject("trajectory plan planned_at mismatch")

    models_by_identifier = {
        catalog.state_model.identifier: catalog.state_model for catalog in catalogs
    }
    transitions_by_identifier = {
        transition.identifier: transition
        for catalog in catalogs
        for transition in catalog.transitions
    }
    strategies = {
        candidate.identifier: candidate
        for candidate in store.get_strategy_candidates(tenant_id, campaign_id)
    }
    for plan in plans:
        if plan.tenant_id != tenant_id:
            raise reject("trajectory plan tenant mismatch")
        if plan.campaign_id != campaign_id:
            raise reject("trajectory plan campaign mismatch")
        if plan.scenario_id != campaign.scenario_id:
            raise reject("trajectory plan scenario mismatch")
        if plan.world_version_id != campaign.world_version_id:
            raise reject("trajectory plan world version mismatch")
        if plan.world_content_hash != world.content_hash:
            raise reject("trajectory plan world content hash mismatch")
        if plan.identifier != trajectory_plan_identifier(
            campaign_id=campaign_id,
            world_version_id=world.identifier,
            strategy_candidate_id=plan.strategy_candidate_id,
            state_model_identifier=plan.state_model_identifier,
        ):
            raise reject("trajectory plan identifier mismatch")
        if plan.content_hash != trajectory_plan_content_hash(plan):
            raise reject("trajectory plan content hash mismatch")
        if plan.strategy_candidate_id not in campaign.strategy_candidate_ids:
            raise reject("trajectory plan strategy mismatch")
        strategy = strategies.get(plan.strategy_candidate_id)
        if strategy is None:
            raise reject("trajectory plan strategy missing")
        if plan.strategy_content_hash != strategy_candidate_content_hash(strategy):
            raise reject("trajectory plan strategy content hash mismatch")
        state_model = models_by_identifier.get(plan.state_model_identifier)
        if state_model is None:
            raise reject("trajectory plan state model missing from the world")
        if plan.manifest_id != state_model.manifest_id:
            raise reject("trajectory plan manifest mismatch")
        if plan.state_model_id != state_model.state_model_id:
            raise reject("trajectory plan state model identity mismatch")
        if plan.state_model_content_hash != state_model.content_hash:
            raise reject("trajectory plan state model content hash mismatch")
        for position, reference in enumerate(plan.transition_references):
            if reference.sequence_position != position:
                raise reject("trajectory plan sequence positions are not contiguous")
            transition = transitions_by_identifier.get(reference.transition_identifier)
            if transition is None:
                raise reject("trajectory plan references an unknown transition")
            if (
                transition.manifest_id != state_model.manifest_id
                or transition.state_model_id != state_model.state_model_id
                or transition.state_model_content_hash != state_model.content_hash
            ):
                raise reject("trajectory plan transition model mismatch")
            if transition.transition_id != reference.transition_id:
                raise reject("trajectory plan transition id mismatch")
            if transition.content_hash != reference.transition_content_hash:
                raise reject("trajectory plan transition content hash mismatch")
