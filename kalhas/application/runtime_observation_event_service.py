"""Pure deterministic causal observation-event derivation service (H28-S06B2).

Implements the pure, read-only runtime-4 causal observation-event engine
required by ADR-004 D28-02/D28-03: one application service derives the
frozen :class:`ObservationStepResult` for exactly one decision step - the
newly sourced :class:`RuntimeObservationEvent` records for the current
source step plus the exact canonically ordered event tuple available to
the current decision step - from verified stored
:class:`RuntimeObservationDeclaration` authorities, the exact stored
:class:`AdaptivePolicy` observation bindings, the verified scenario seed,
the visible pre-action state, an optional already-accepted
:class:`ExternalObservationInputBundle`, and the complete prior
sourced-event ledger required by causal completeness.

The derivation is **causally closed and read-only**: it never executes a
trajectory action, never advances the adaptive-policy state machine,
never persists an ``AdaptiveRunTrajectoryExecution``, never performs
replay, and never writes the store or records an activity event. It reads
only verified stored authorities, validates the complete input atomically
and fail-closed before any derivation, and returns detached immutable
evidence; every input byte/object is preserved unchanged.

The caller supplies the exact ``final_decision_step`` horizon of the run
with every derivation call; terminality is determined at event creation
as ``source_step_index + delay_steps > final_decision_step`` and never
from whether the current call happens to be the final decision.

Per source kind:

- a **state-field** observation reads only the explicitly declared visible
  field of the supplied pre-action state (validated against the exact
  canonical state-model authority and hashed with the established
  :func:`state_hash` helper); latent or undeclared state is unreachable,
  and a missing or malformed required visible field fails closed - it is
  never treated as an external-style missing value. With the no-noise
  declaration the exposed value exactly equals the source value; with the
  additive-uniform declaration exactly one local draw (``draw_index`` 0)
  is derived solely from the frozen ADR-004 D28-03 observation-noise
  coordinate, quantized and summed under the repository's exact Q64.64
  rational-round-half-even semantics through the established sampler
  helpers, and any overflow, non-finite, or unrepresentable result fails
  closed;
- an **external** observation consumes only the already-accepted and
  strictly verified external input bundle at the exact
  ``(declaration, source step)`` coordinate - never fresh noise - and an
  absent scheduled coordinate produces explicit missing evidence bound to
  the bundle identity.

Observations are scheduled exactly when ``step >= start_step`` and
``(step - start_step) % every_n_steps == 0``; availability is exactly
``source_step_index + delay_steps``, ``delay_steps == 0`` influences the
same decision, simultaneously available events are returned in canonical
declaration-identity order, and an event is terminal exactly when its
availability step lies beyond the caller-supplied ``final_decision_step``
horizon - terminal evidence is recorded, carries no available decision
step, and never enters the available-event tuple.

``prior_events`` is the **complete immutable sourced-event ledger** from
every source step strictly before ``decision_step``: for every
policy-bound declaration the independently derived set of scheduled
``(declaration, source step)`` coordinates for all
``0 <= source_step_index < decision_step`` must equal the supplied
coordinates exactly - a missing coordinate (an absent external input is
itself a proper ``status="missing"`` event), an extra or unscheduled or
future-source coordinate, a duplicate or reordered coordinate, a forged
or foreign event, or any broken sequence position, ordering, identity,
content hash, or terminal/non-terminal classification fails closed and
atomically. Prior evidence is never sorted or repaired: a pending
delayed event whose availability lies at or after the current decision
is valid historical sourced evidence, and terminal prior evidence is
valid history that never becomes available to any policy.

The module is pure application logic: no FastAPI, no NEXUS/LEGION
imports, no wall clock, randomness, UUID, global RNG, Decimal context,
platform libm behavior, network, providers, filesystem, or database
access, no store write, no adapters, and no activity event. Public
messages never expose internal reasons, hashes, identities, channels,
field values, thresholds, counts, units, or validator diagnostics.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.deterministic_sampler import (
    SamplerOverflowError,
    exact_value_to_fix,
    record_raw_value,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    DomainStateModelNotFoundError,
    ScenarioNotFoundError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.external_observation_input_errors import (
    ExternalObservationInputIntegrityError,
)
from kalhas.application.external_observation_input_identity import (
    verify_external_observation_input_bundle_identity,
)
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventCausalOrderError,
    RuntimeObservationEventIntegrityError,
    RuntimeObservationEventNoiseError,
    RuntimeObservationEventValidationError,
)
from kalhas.application.runtime_observation_event_identity import (
    OBSERVATION_NOISE_DOMAIN_LITERAL,
    OBSERVATION_NOISE_SAMPLER_VERSION,
    RUNTIME_VERSION_LITERAL,
    observation_noise_word,
    runtime_observation_event_content_hash,
    runtime_observation_event_identifier,
    verify_runtime_observation_event_identity,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy, ObservationBinding
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.runtime_observation import (
    AdditiveUniformObservationNoise,
    ExternalObservationInputBundle,
    ExternalObservationSource,
    NoObservationNoise,
    RuntimeObservationDeclaration,
    RuntimeObservationEvent,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.world import WorldVersion

_PLACEHOLDER_HASH = "0" * 64

#: The visible pre-action state collection: exactly one complete state
#: mapping per state-model identifier that the bound declarations declare.
StateCollection = Mapping[str, Mapping[str, JsonValue]]


@dataclass(frozen=True, slots=True)
class ObservationStepDraft:
    """The application-local caller-owned derivation request for one decision.

    Carries only the strict non-negative integer ``decision_step`` (the
    current decision and source step), the strict non-negative integer
    ``final_decision_step`` horizon of the run (the exact same value on
    every derivation call of one history; ``decision_step`` must never
    exceed it), the visible pre-action ``state`` collection, the complete
    verified prior sourced-event ledger ``prior_events`` in canonical
    order, and the optional already-accepted external input bundle draft.
    No authoritative identity, hash, declaration, policy, or seed value
    is accepted here; every authoritative value is loaded from the store
    and independently verified.
    """

    decision_step: int
    final_decision_step: int
    state: StateCollection
    prior_events: tuple[RuntimeObservationEvent, ...] = ()
    external_bundle_draft: ExternalObservationInputBundleDraft | None = None


@dataclass(frozen=True, slots=True)
class ObservationStepResult:
    """The frozen outcome of one causal observation derivation step.

    ``new_events`` holds the newly sourced events for the current source
    step in canonical declaration-identity order; ``available_events``
    is the exact canonically ordered tuple of non-terminal events whose
    availability step equals the current decision step - the complete
    decision input for the policy evaluation that follows in the frozen
    within-step causal schedule. Terminal events never enter it.
    """

    new_events: tuple[RuntimeObservationEvent, ...]
    available_events: tuple[RuntimeObservationEvent, ...]


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` (booleans rejected)."""
    if type(value) is bool:
        return False
    if type(value) is int:
        return True
    if type(value) is float:
        return value == value and value not in (float("inf"), float("-inf"))
    return False


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied artifact from its detached serialization.

    The artifact's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance is rejected before any field of it is trusted. The
    revalidation result is discarded; the artifact is never replaced,
    repaired, or mutated. Any failure raises ``ValueError``.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("artifact failed detached strict revalidation") from None


def _strictly_revalidate_draft(draft: ObservationStepDraft) -> None:
    """Validate every caller-owned derivation input; raises ``ValueError``.

    Enforces the exact draft type (subclasses and validator-bypassed or
    uninitialized instances are rejected), the exact non-negative integer
    decision step and the exact non-negative integer final-decision
    horizon (bool, float, string, and negative values fail; the decision
    step must never exceed the horizon), the genuine mapping shape of the
    state collection and of every state, the exact tuple of strictly
    revalidated prior events, and the exact optional bundle-draft type.
    Nothing is repaired, coerced, sorted, or normalized.
    """
    if type(draft) is not ObservationStepDraft:
        raise ValueError("draft must be a valid ObservationStepDraft")
    step = draft.decision_step
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("decision_step must be an exact non-negative integer")
    horizon = draft.final_decision_step
    if type(horizon) is not int or horizon < 0:
        raise ValueError("final_decision_step must be an exact non-negative integer")
    if step > horizon:
        raise ValueError("decision_step must not exceed final_decision_step")
    if not isinstance(draft.state, Mapping):
        raise ValueError("state must be a mapping of state-model identifiers to states")
    for key, value in draft.state.items():
        if not isinstance(key, str) or not key:
            raise ValueError("state keys must be non-empty state-model identifiers")
        if not isinstance(value, Mapping):
            raise ValueError("every state must be a mapping of field identifiers to values")
    if not isinstance(draft.prior_events, tuple):
        raise ValueError("prior_events must be a tuple of runtime observation events")
    for event in draft.prior_events:
        if type(event) is not RuntimeObservationEvent:
            raise ValueError("prior_events must contain only exact runtime observation events")
        _strictly_revalidate_detached(event, RuntimeObservationEvent)
    if draft.external_bundle_draft is not None and type(draft.external_bundle_draft) is not (
        ExternalObservationInputBundleDraft
    ):
        raise ValueError("external_bundle_draft must be a valid bundle draft")


def _load_verified_run_authority(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
) -> tuple[CampaignSpec, WorldVersion, str, str, str]:
    """Load and verify the exact compiled campaign, world, and seed identities.

    Returns ``(campaign, world, scenario_id, world_version_id,
    world_content_hash)`` for the exactly-COMPILED tenant-scoped campaign
    whose verified compiled world belongs to the same tenant and scenario.
    """
    try:
        campaign = store.get_campaign(tenant_id, campaign_id)
        status = store.get_campaign_status(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="campaign authority missing"
        ) from exc
    if status.state is not CampaignState.COMPILED:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="campaign must be exactly COMPILED"
        )
    scenario_id = campaign.scenario_id
    world_version_id = campaign.world_version_id
    try:
        store.get_scenario(tenant_id, scenario_id)
    except ScenarioNotFoundError as exc:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="scenario authority missing"
        ) from exc
    try:
        world = store.get_world(tenant_id, world_version_id)
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError as exc:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="world authority missing"
        ) from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="world authority corrupt"
        ) from exc
    if world.tenant_id != tenant_id or world.source_scenario_id != scenario_id:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
        )
    return campaign, world, scenario_id, world_version_id, world.content_hash


def _load_verified_seed(
    campaign: CampaignSpec,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
) -> tuple[ScenarioSeed, str]:
    """Locate the exact campaign scenario seed and compute its content hash."""
    seed = next(
        (
            candidate
            for candidate in campaign.seed_ensemble
            if candidate.identifier == scenario_seed_id
        ),
        None,
    )
    if seed is None:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="scenario seed authority missing"
        )
    if seed.tenant_id != tenant_id:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="scenario seed tenant mismatch"
        )
    return seed, seed_content_hash(seed)


def _load_verified_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    world_content_hash: str,
) -> AdaptivePolicy:
    """Load and verify the exact stored adaptive policy for the campaign."""
    try:
        policy = store.get_adaptive_policy(tenant_id, campaign_id)
    except AdaptivePolicyNotFoundError as exc:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="adaptive policy authority missing"
        ) from exc
    except AdaptivePolicyIntegrityError as exc:
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="adaptive policy authority corrupt"
        ) from exc
    if (
        policy.runtime_version != RUNTIME_VERSION_LITERAL
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != scenario_id
        or policy.world_version_id != world_version_id
        or policy.world_content_hash != world_content_hash
    ):
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="campaign/policy/scenario/world identity mismatch"
        )
    return policy


def _load_verified_declarations(
    store: InMemoryScenarioStore,
    policy: AdaptivePolicy,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    world_content_hash: str,
) -> dict[str, tuple[RuntimeObservationDeclaration, ObservationBinding]]:
    """Load and verify the stored declaration behind every policy binding.

    Only observation declarations bound by the stored policy are used.
    Every stored record is strictly reverified by the store getter on
    read; the service additionally requires the exact policy-binding
    agreement (declaration identifier and content hash, observed value
    kind, unit, and missing behavior) and the exact scenario/world/
    runtime provenance, so a forged or disagreeing authority fails
    closed before any derivation.
    """
    resolved: dict[str, tuple[RuntimeObservationDeclaration, ObservationBinding]] = {}
    for binding in policy.observation_bindings:
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, scenario_id, world_version_id, binding.observation_id
            )
        except RuntimeObservationDeclarationNotFoundError as exc:
            raise RuntimeObservationEventValidationError(
                tenant_id, campaign_id, reason="observation declaration authority missing"
            ) from exc
        except RuntimeObservationDeclarationIntegrityError as exc:
            raise RuntimeObservationEventIntegrityError(
                tenant_id, campaign_id, reason="observation declaration authority corrupt"
            ) from exc
        if (
            declaration.runtime_version != RUNTIME_VERSION_LITERAL
            or declaration.tenant_id != tenant_id
            or declaration.scenario_id != scenario_id
            or declaration.world_version_id != world_version_id
            or declaration.world_content_hash != world_content_hash
            or binding.runtime_observation_declaration_id != declaration.identifier
            or binding.runtime_observation_declaration_content_hash != declaration.content_hash
            or binding.observed_value_kind != declaration.observed_value_kind
            or binding.unit != declaration.unit
            or binding.missing_behavior != declaration.missing_behavior
        ):
            raise RuntimeObservationEventValidationError(
                tenant_id, campaign_id, reason="policy binding disagrees with stored authority"
            )
        resolved[binding.observation_id] = (declaration, binding)
    return resolved


def _verify_state_collection(
    state: StateCollection,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    declarations: dict[str, tuple[RuntimeObservationDeclaration, ObservationBinding]],
    store: InMemoryScenarioStore,
) -> dict[str, str]:
    """Require exact canonical state-model authority for the supplied state.

    The supplied collection must carry exactly one state for every
    state-model identifier declared by the bound state-field sources -
    no missing, extra, foreign, or duplicated model - and every model is
    loaded from the store (which strictly re-verifies it) and required to
    agree exactly with its declaration's copied authority. Every state is
    then validated against its model's field definitions and hashed with
    the established canonical :func:`state_hash` helper. Returns the
    mapping of state-model identifier to canonical state hash.
    """
    expected_models: dict[str, tuple[str, str, str]] = {}
    for declaration, _binding in declarations.values():
        source = declaration.observation_source
        if isinstance(source, StateFieldObservationSource):
            expected_models.setdefault(
                source.state_model_identifier,
                (source.manifest_id, source.state_model_id, source.state_model_content_hash),
            )
    for model_identifier in expected_models:
        if model_identifier not in state:
            raise RuntimeObservationEventValidationError(
                tenant_id, campaign_id, reason="state collection is missing a declared state"
            )
    if len(state) != len(expected_models):
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="state collection carries foreign state"
        )
    state_hashes: dict[str, str] = {}
    for model_identifier, state_value in state.items():
        manifest_id, logical_id, content_hash = expected_models[model_identifier]
        try:
            model = store.get_domain_state_model(tenant_id, scenario_id, manifest_id, logical_id)
        except DomainStateModelNotFoundError as exc:
            raise RuntimeObservationEventValidationError(
                tenant_id, campaign_id, reason="state model authority missing"
            ) from exc
        if (
            model.identifier != model_identifier
            or model.state_model_id != logical_id
            or model.content_hash != content_hash
        ):
            raise RuntimeObservationEventIntegrityError(
                tenant_id, campaign_id, reason="state model authority mismatch"
            )
        plain: dict[str, JsonValue] = dict(state_value)
        try:
            _validate_state_against_model(plain, model)
        except ValueError as exc:
            raise RuntimeObservationEventValidationError(
                tenant_id, campaign_id, reason="state violates its declared authority"
            ) from exc
        state_hashes[model_identifier] = state_hash(plain)
    return state_hashes


def _validate_state_against_model(state: dict[str, JsonValue], model: DomainStateModel) -> None:
    """Validate one plain state mapping against its model; raises ``ValueError``."""
    from kalhas.contracts.v1.state_model import _canonical_value_text, _value_matches_kind

    fields = {field.identifier: field for field in model.state_fields}
    for field_id in fields:
        if field_id not in state:
            raise ValueError(f"missing required state field {field_id!r}")
    for key, value in state.items():
        field = fields.get(key)
        if field is None:
            raise ValueError(f"unknown state field {key!r}")
        if not _value_matches_kind(value, field.value_kind):
            raise ValueError(f"state value for field {key!r} violates its declared kind")
        if field.allowed_values:
            allowed = [_canonical_value_text(item) for item in field.allowed_values]
            if _canonical_value_text(value) not in allowed:
                raise ValueError(f"state value for field {key!r} is not allowed")


def _resolve_external_bundle(
    store: InMemoryScenarioStore,
    draft: ExternalObservationInputBundleDraft,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    world_content_hash: str,
    scenario_seed_id: str,
    seed_hash: str,
) -> ExternalObservationInputBundle:
    """Require the caller's draft to be the accepted, verified stored bundle.

    The stored bundle for this ``(tenant, campaign, seed)`` locality is
    retrieved (strictly reverified by the store) and independently
    re-verified; the caller's draft must then match it exactly - entry
    coordinates, values, and the deterministic ``accepted_at`` - so a
    forged, stale, or foreign bundle fails closed and the derivation only
    ever consumes accepted evidence.
    """
    try:
        stored = store.get_external_observation_input_bundle(
            tenant_id=tenant_id, campaign_id=campaign_id, scenario_seed_id=scenario_seed_id
        )
    except ExternalObservationInputIntegrityError as exc:
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="external bundle authority corrupt"
        ) from exc
    try:
        verify_external_observation_input_bundle_identity(
            stored,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=scenario_id,
            world_version_id=world_version_id,
            scenario_seed_id=scenario_seed_id,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="external bundle authority mismatch"
        ) from exc
    draft_values = tuple(
        (value.observation_id, value.source_step_index, value.value) for value in draft.entries
    )
    stored_values = tuple(
        (entry.observation_id, entry.source_step_index, entry.value) for entry in stored.entries
    )
    if (
        draft_values != stored_values
        or draft.accepted_at != stored.accepted_at
        or stored.scenario_id != scenario_id
        or stored.world_version_id != world_version_id
        or stored.world_content_hash != world_content_hash
        or stored.scenario_seed_id != scenario_seed_id
        or stored.seed_content_hash != seed_hash
    ):
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="external bundle does not match the accepted authority"
        )
    return stored


def _event_record(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    seed_hash: str,
    declaration: RuntimeObservationDeclaration,
    status: Literal["observed", "missing"],
    sequence_position: int,
    source_step_index: int,
    final_decision_step: int,
    source_state_hash: str | None,
    external_input_bundle_id: str | None,
    external_input_bundle_content_hash: str | None,
    source_value: int | float | None,
    applied_noise_value: int | float | None,
    exposed_observation_value: int | float | None,
    noise_draw_index: int | None,
) -> RuntimeObservationEvent:
    """Build one self-hashing event record from verified fields.

    The event binds the declaration identity and content hash, the
    declaration's verified world identity, the exact scenario-seed
    identity and content hash of the verified seed, the frozen cadence,
    terminality, status, provenance, and the frozen ADR-004 noise-coordinate
    provenance. Terminality is explicit, never inferred from the current
    call: the event is terminal exactly when its availability step lies
    beyond the caller-supplied immutable ``final_decision_step`` horizon -
    recorded evidence carrying no available decision step that can never
    enter any decision input. The content hash is computed over the
    complete payload and finalized into the returned record.
    """
    delay_steps = declaration.timing.delay_steps
    available = source_step_index + delay_steps
    terminal = available > final_decision_step
    observed = status == "observed"
    placeholder = RuntimeObservationEvent(
        identifier=runtime_observation_event_identifier(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            runtime_observation_declaration_id=declaration.identifier,
            source_step_index=source_step_index,
        ),
        runtime_version=RUNTIME_VERSION_LITERAL,
        observation_declaration_id=declaration.identifier,
        observation_declaration_content_hash=declaration.content_hash,
        observation_id=declaration.observation_id,
        source_kind=declaration.observation_source.kind,
        world_version_id=declaration.world_version_id,
        world_content_hash=declaration.world_content_hash,
        scenario_seed_id=scenario_seed_id,
        seed_content_hash=seed_hash,
        sequence_position=sequence_position,
        source_step_index=source_step_index,
        delay_steps=delay_steps,
        available_decision_step=None if terminal else available,
        terminal=terminal,
        status=status,
        source_state_hash=source_state_hash,
        external_input_bundle_id=external_input_bundle_id,
        external_input_bundle_content_hash=external_input_bundle_content_hash,
        source_value=source_value,
        applied_noise_value=applied_noise_value,
        exposed_observation_value=exposed_observation_value,
        observed_value_kind=declaration.observed_value_kind if observed else None,
        observed_value_unit=declaration.unit if observed else None,
        noise_domain_literal=OBSERVATION_NOISE_DOMAIN_LITERAL,
        noise_sampler_version=OBSERVATION_NOISE_SAMPLER_VERSION,
        noise_draw_index=noise_draw_index,
        content_hash=_PLACEHOLDER_HASH,
    )
    digest = runtime_observation_event_content_hash(placeholder)
    return placeholder.model_copy(update={"content_hash": digest})


def _scheduled(declaration: RuntimeObservationDeclaration, step: int) -> bool:
    """True exactly when ``step`` satisfies the declaration cadence."""
    timing = declaration.timing
    return step >= timing.start_step and (step - timing.start_step) % timing.every_n_steps == 0


def _verify_prior_event_provenance(
    *,
    event: RuntimeObservationEvent,
    declaration: RuntimeObservationDeclaration,
    binding: ObservationBinding,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    seed_hash: str,
    world_version_id: str,
    world_content_hash: str,
    final_decision_step: int,
) -> None:
    """Verify one prior event's complete provenance and terminality class.

    Beyond the identity, authority, and binding agreement, the recorded
    terminal/non-terminal classification must be exactly the one the
    event's own coordinates imply against the caller-supplied
    ``final_decision_step`` horizon: terminal exactly when
    ``source_step_index + delay_steps > final_decision_step``, with the
    availability step present exactly when non-terminal and absent
    exactly when terminal.
    """
    try:
        verify_runtime_observation_event_identity(
            event,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            runtime_observation_declaration_id=declaration.identifier,
            source_step_index=event.source_step_index,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event failed authority verification"
        ) from exc
    if (
        event.world_version_id != world_version_id
        or event.world_content_hash != world_content_hash
        or event.seed_content_hash != seed_hash
        or event.observation_id != declaration.observation_id
        or event.observation_declaration_content_hash != declaration.content_hash
        or event.source_kind != declaration.observation_source.kind
        or event.delay_steps != declaration.timing.delay_steps
    ):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event disagrees with its stored authority"
        )
    if event.status == "observed" and (
        event.observed_value_kind != binding.observed_value_kind
        or event.observed_value_unit != binding.unit
    ):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event disagrees with its binding"
        )
    available = event.source_step_index + event.delay_steps
    terminal = available > final_decision_step
    if event.terminal is not terminal or event.available_decision_step != (
        None if terminal else available
    ):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event terminal classification is impossible"
        )


def _expected_prior_coordinates(
    declarations: dict[str, tuple[RuntimeObservationDeclaration, ObservationBinding]],
    *,
    decision_step: int,
) -> set[tuple[str, int]]:
    """The exact scheduled prior coordinates implied by the bound cadences.

    For every policy-bound declaration, every source step
    ``0 <= source_step_index < decision_step`` satisfying the declared
    cadence is a scheduled coordinate. An external input that was absent
    at a scheduled coordinate is still represented by a proper
    ``status="missing"`` event, so ledger completeness is proven over
    coordinates, not over observed values.
    """
    expected: set[tuple[str, int]] = set()
    for declaration, _binding in declarations.values():
        start = declaration.timing.start_step
        every_n = declaration.timing.every_n_steps
        for step in range(start, decision_step, every_n):
            expected.add((declaration.identifier, step))
    return expected


def _verify_prior_events(
    prior_events: tuple[RuntimeObservationEvent, ...],
    *,
    declarations: dict[str, tuple[RuntimeObservationDeclaration, ObservationBinding]],
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    seed_hash: str,
    world_version_id: str,
    world_content_hash: str,
    decision_step: int,
    final_decision_step: int,
) -> None:
    """Verify the complete prior sourced-event ledger; never sort or repair.

    The ledger is the complete immutable sourced-event record from every
    source step strictly before this decision step. Independently derived
    from the bound declarations' cadences, the set of expected
    ``(declaration, source step)`` coordinates must equal the supplied
    coordinates exactly: a missing scheduled coordinate, an extra,
    unscheduled, or future-source coordinate, a duplicate coordinate or
    identifier, reordered or non-contiguous sequence positions, a forged
    or foreign event, or a wrong terminal/non-terminal classification
    fails closed. Availability itself is not causal availability to this
    decision: a pending delayed event whose availability lies at or after
    the current decision is valid sourced evidence, and terminal prior
    evidence is valid history that never becomes available to a policy.
    """
    ordering = [
        (event.source_step_index, event.observation_declaration_id) for event in prior_events
    ]
    if ordering != sorted(ordering):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior events are not in canonical order"
        )
    positions = [event.sequence_position for event in prior_events]
    if positions != list(range(len(positions))):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior sequence positions must be contiguous"
        )
    if len({event.identifier for event in prior_events}) != len(prior_events):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event identifiers must be unique"
        )
    coordinates = [
        (event.observation_declaration_id, event.source_step_index) for event in prior_events
    ]
    if len(coordinates) != len(set(coordinates)):
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior event coordinates must be unique"
        )
    for event in prior_events:
        if event.source_step_index >= decision_step:
            raise RuntimeObservationEventCausalOrderError(
                tenant_id, campaign_id, reason="prior evidence is sourced at or after this decision"
            )
    expected = _expected_prior_coordinates(declarations, decision_step=decision_step)
    supplied = set(coordinates)
    if supplied != expected:
        raise RuntimeObservationEventCausalOrderError(
            tenant_id, campaign_id, reason="prior evidence is not the complete sourced ledger"
        )
    for event in prior_events:
        resolved = declarations.get(event.observation_id)
        if resolved is None:
            raise RuntimeObservationEventCausalOrderError(
                tenant_id, campaign_id, reason="prior event references an undeclared observation"
            )
        declaration, binding = resolved
        _verify_prior_event_provenance(
            event=event,
            declaration=declaration,
            binding=binding,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            seed_hash=seed_hash,
            world_version_id=world_version_id,
            world_content_hash=world_content_hash,
            final_decision_step=final_decision_step,
        )


def _external_channel(declaration: RuntimeObservationDeclaration) -> str:
    """The declared external channel identifier of an external declaration."""
    source = declaration.observation_source
    if isinstance(source, ExternalObservationSource):
        return source.external_channel_id
    raise RuntimeObservationEventIntegrityError(
        "", "", reason="state-field declarations carry no external channel"
    )


def _derive_external_event(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    seed_hash: str,
    declaration: RuntimeObservationDeclaration,
    decision_step: int,
    final_decision_step: int,
    sequence_position: int,
    bundle: ExternalObservationInputBundle,
) -> RuntimeObservationEvent:
    """Derive one external-input observation event; never fresh noise.

    The exact bundle entry at ``(declaration, source step)`` is used; an
    absent scheduled coordinate produces explicit missing evidence bound
    to the bundle identity. No noise draw, applied noise value, or draw
    index is ever attached to external evidence.
    """
    entry = next(
        (
            candidate
            for candidate in bundle.entries
            if candidate.runtime_observation_declaration_id == declaration.identifier
            and candidate.source_step_index == decision_step
        ),
        None,
    )
    bundle_id = bundle.identifier
    bundle_hash = bundle.content_hash
    if entry is None:
        return _event_record(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            seed_hash=seed_hash,
            declaration=declaration,
            status="missing",
            sequence_position=sequence_position,
            source_step_index=decision_step,
            final_decision_step=final_decision_step,
            source_state_hash=None,
            external_input_bundle_id=bundle_id,
            external_input_bundle_content_hash=bundle_hash,
            source_value=None,
            applied_noise_value=None,
            exposed_observation_value=None,
            noise_draw_index=None,
        )
    if (
        entry.runtime_observation_declaration_content_hash != declaration.content_hash
        or entry.observation_id != declaration.observation_id
        or entry.external_channel_id != _external_channel(declaration)
        or entry.value_kind != declaration.observed_value_kind
        or entry.unit != declaration.unit
        or not _is_exact_finite_numeric(entry.value)
    ):
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="external entry disagrees with its declaration"
        )
    return _event_record(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        seed_hash=seed_hash,
        declaration=declaration,
        status="observed",
        sequence_position=sequence_position,
        source_step_index=decision_step,
        final_decision_step=final_decision_step,
        source_state_hash=None,
        external_input_bundle_id=bundle_id,
        external_input_bundle_content_hash=bundle_hash,
        source_value=entry.value,
        applied_noise_value=None,
        exposed_observation_value=entry.value,
        noise_draw_index=None,
    )


def _derive_state_field_event(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    seed_hash: str,
    declaration: RuntimeObservationDeclaration,
    decision_step: int,
    final_decision_step: int,
    sequence_position: int,
    source_state_hash: str,
    source_value: int | float,
    state_value: Mapping[str, JsonValue],
) -> RuntimeObservationEvent:
    """Derive one state-field observation event from the visible state.

    Reads only the explicitly declared visible field. The no-noise
    declaration exposes the source value unchanged; the additive-uniform
    declaration draws exactly one local noise word (``draw_index`` 0)
    from the frozen ADR-004 coordinate, converts it through the exact
    stored lower/upper bounds under the repository's Q64.64
    rational-round-half-even semantics, and records the quantized source
    plus applied noise. Overflow, non-finite, and unrepresentable results
    fail closed. Terminality is classified against the exact
    ``final_decision_step`` horizon, never against the current call.
    """
    source = declaration.observation_source
    if not isinstance(source, StateFieldObservationSource):
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="external declarations carry no state field"
        )
    if source.state_field_id not in state_value:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="declared visible state field is missing"
        )
    noise = declaration.noise
    if isinstance(noise, NoObservationNoise):
        return _event_record(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            seed_hash=seed_hash,
            declaration=declaration,
            status="observed",
            sequence_position=sequence_position,
            source_step_index=decision_step,
            final_decision_step=final_decision_step,
            source_state_hash=source_state_hash,
            external_input_bundle_id=None,
            external_input_bundle_content_hash=None,
            source_value=source_value,
            applied_noise_value=None,
            exposed_observation_value=source_value,
            noise_draw_index=None,
        )
    if not isinstance(noise, AdditiveUniformObservationNoise):
        raise RuntimeObservationEventIntegrityError(
            tenant_id, campaign_id, reason="observation noise declaration is not closed"
        )
    word = observation_noise_word(
        world_content_hash=declaration.world_content_hash,
        seed_content_hash=seed_hash,
        runtime_observation_declaration_content_hash=declaration.content_hash,
        source_step_index=decision_step,
        draw_index=0,
    )
    lower_fix = exact_value_to_fix(noise.lower_bound)
    upper_fix = exact_value_to_fix(noise.upper_bound)
    noise_fix = lower_fix + (((upper_fix - lower_fix) * word) >> 64)
    source_fix = exact_value_to_fix(source_value)
    total_fix = source_fix + noise_fix
    try:
        applied_value = record_raw_value(noise_fix, "float")
        exposed_value = record_raw_value(total_fix, "float")
    except SamplerOverflowError as exc:
        raise RuntimeObservationEventNoiseError(
            tenant_id, campaign_id, reason="noise derivation is not finitely representable"
        ) from exc
    return _event_record(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        seed_hash=seed_hash,
        declaration=declaration,
        status="observed",
        sequence_position=sequence_position,
        source_step_index=decision_step,
        final_decision_step=final_decision_step,
        source_state_hash=source_state_hash,
        external_input_bundle_id=None,
        external_input_bundle_content_hash=None,
        source_value=source_value,
        applied_noise_value=applied_value,
        exposed_observation_value=exposed_value,
        noise_draw_index=0,
    )


def derive_observation_step(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    draft: ObservationStepDraft,
) -> ObservationStepResult:
    """Derive one decision step's causal observation evidence; raises typed errors.

    The pure, read-only runtime-4 derivation: it reads verified stored
    authorities, validates the complete input atomically and fail-closed,
    and returns the frozen step result with detached immutable evidence.
    Every failure is atomic: the store, its activity feed, and every
    input object are left exactly unchanged.
    """
    try:
        _strictly_revalidate_draft(draft)
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeObservationEventValidationError(
            tenant_id, campaign_id, reason="draft invalid"
        ) from exc
    decision_step = draft.decision_step
    final_decision_step = draft.final_decision_step

    # 1. Verified campaign/world/seed/policy authority.
    campaign, _world, scenario_id, world_version_id, world_content_hash = (
        _load_verified_run_authority(store, tenant_id=tenant_id, campaign_id=campaign_id)
    )
    _seed, seed_hash = _load_verified_seed(
        campaign,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
    )
    policy = _load_verified_policy(
        store,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
    )

    # 2. Policy-bound stored declaration authorities.
    declarations = _load_verified_declarations(
        store,
        policy,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
    )

    # 3. External bundle authority (only when one is supplied).
    bundle = (
        None
        if draft.external_bundle_draft is None
        else _resolve_external_bundle(
            store,
            draft.external_bundle_draft,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=scenario_id,
            world_version_id=world_version_id,
            world_content_hash=world_content_hash,
            scenario_seed_id=scenario_seed_id,
            seed_hash=seed_hash,
        )
    )

    # 4. Canonical state authority and visible-state hashes.
    state_hashes = _verify_state_collection(
        draft.state,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        declarations=declarations,
        store=store,
    )

    # 5. Prior evidence causal verification (never sorted or repaired).
    _verify_prior_events(
        draft.prior_events,
        declarations=declarations,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        seed_hash=seed_hash,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
        decision_step=decision_step,
        final_decision_step=final_decision_step,
    )

    # 6. The verified prior events available exactly at this decision.
    prior_available = tuple(
        event
        for event in draft.prior_events
        if not event.terminal and event.available_decision_step == decision_step
    )

    # 7. Scheduled derivation in canonical declaration-identity order.
    # A previous event for the same declaration never suppresses the new
    # event: every declaration scheduled at the current source step is
    # derived exactly once now.
    scheduled = sorted(
        (declaration.identifier, observation_id)
        for observation_id, (declaration, _binding) in declarations.items()
        if _scheduled(declaration, decision_step)
    )

    new_events: list[RuntimeObservationEvent] = []
    derived_available: list[RuntimeObservationEvent] = []
    for _declaration_id, observation_id in scheduled:
        declaration, _binding = declarations[observation_id]
        source = declaration.observation_source
        source_state_hash: str | None = None
        source_value: int | float | None = None
        state_value: Mapping[str, JsonValue] | None = None
        if isinstance(source, StateFieldObservationSource):
            source_state_hash = state_hashes[source.state_model_identifier]
            state_value = draft.state[source.state_model_identifier]
            raw = state_value[source.state_field_id]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise RuntimeObservationEventValidationError(
                    tenant_id,
                    campaign_id,
                    reason="declared state field must be an exact finite numeric",
                )
            if isinstance(raw, float) and not _is_exact_finite_numeric(raw):
                raise RuntimeObservationEventValidationError(
                    tenant_id,
                    campaign_id,
                    reason="declared state field must be an exact finite numeric",
                )
            source_value = raw
        if source_state_hash is None and isinstance(source, StateFieldObservationSource):
            raise RuntimeObservationEventIntegrityError(
                tenant_id, campaign_id, reason="state hash authority is missing"
            )
        if isinstance(source, ExternalObservationSource):
            if bundle is None:
                raise RuntimeObservationEventValidationError(
                    tenant_id,
                    campaign_id,
                    reason="external derivation requires the accepted bundle",
                )
            event = _derive_external_event(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                scenario_seed_id=scenario_seed_id,
                seed_hash=seed_hash,
                declaration=declaration,
                decision_step=decision_step,
                final_decision_step=final_decision_step,
                sequence_position=len(draft.prior_events) + len(new_events),
                bundle=bundle,
            )
        else:
            if source_value is None:
                raise RuntimeObservationEventIntegrityError(
                    tenant_id, campaign_id, reason="state field authority is missing"
                )
            event = _derive_state_field_event(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                scenario_seed_id=scenario_seed_id,
                seed_hash=seed_hash,
                declaration=declaration,
                decision_step=decision_step,
                final_decision_step=final_decision_step,
                sequence_position=len(draft.prior_events) + len(new_events),
                source_state_hash=str(source_state_hash),
                source_value=source_value,
                state_value=state_value if state_value is not None else {},
            )
        new_events.append(event)
        if event.available_decision_step == decision_step:
            derived_available.append(event)

    # 8. The derived decision input: every verified non-terminal event
    # whose availability step is exactly the current decision step - the
    # available prior events plus the newly derived delay-0 events - each
    # exposed at most once, in canonical declaration-identity order. No
    # event with availability before or after this decision enters it.
    available_events = tuple(
        sorted(
            (*prior_available, *derived_available),
            key=lambda event: event.observation_declaration_id,
        )
    )

    return ObservationStepResult(
        new_events=tuple(new_events),
        available_events=available_events,
    )


__all__ = [
    "ObservationStepDraft",
    "ObservationStepResult",
    "RUNTIME_VERSION_LITERAL",
    "derive_observation_step",
]
