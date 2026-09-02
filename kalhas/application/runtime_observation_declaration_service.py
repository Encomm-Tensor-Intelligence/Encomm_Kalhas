"""Deterministic runtime-observation declaration service (Phase 28, H28-S05).

Declares and persists the immutable :class:`RuntimeObservationDeclaration`
authority for a verified compiled world of runtime ``4.0.0``. This is the
authoring boundary only: an application-local untrusted draft plus
authoritative construction from verified stored records, deterministic
identity/hash computation, strict final revalidation, and no-overwrite
immutable persistence. No runtime execution, no observation events, no
replay, no external bundle execution, no API, no adapters/NEXUS/LEGION calls,
no network/provider/live effects, and no domain logic live here.

Two closed observation sources are authorable:

- a **state-field** observation: the service loads the exact stored
  scenario, world, manifest, and :class:`DomainStateModel` authorities,
  proves the domain-pack manifest and state model are exact members of the
  selected compiled world (an embedded world snapshot, not merely a
  store record), locates the exact declared state field, permits only exact
  ``integer``/``number`` state fields, and copies *every* authoritative
  manifest/model/field identity and hash from the stored records; the caller
  never supplies those authoritative values;
- an **external** observation: an explicit stable external channel with an
  exact integer/number value kind, no fresh observation noise, bound to the
  same exact scenario/world/runtime authority, and with no network, provider,
  or live-input behavior.

The declared unit, timing, observation noise, missing behavior, the
deterministic ``declared_at``, and the finite JSON-compatible metadata are
caller-owned authoring inputs preserved verbatim (within the contract's
closed constraints). The scenario/world authority is copied from verified
stored records and the runtime version is fixed to ``4.0.0``. The object
``observed_value_kind`` is *derived*, never caller-chosen: with no fresh noise
it equals the source's exact numeric value kind, and with additive noise it is
``"number"`` - the exact semantic the contract enforces. All existing contract
semantics are preserved without coercion.

Declaration is deterministic and atomic, in this exact order:

1. detachedly strict-revalidate the draft and every nested authoring input
   (a validator-bypassed or forged draft, timing, noise, or timestamp object
   is rejected before any field is trusted);
2. load the exact tenant-scoped ``ScenarioSpec``;
3. load the exact world and manifest and prove they are exactly compiler
   output (``verify_world_snapshot``) - a missing or corrupt world is
   rejected;
4. require the world's embedded ``source_scenario_id`` to equal the declared
   scenario and the scenario's tenant to match;
5. for a state-field source, load the exact stored ``DomainPackManifest`` and
   ``DomainStateModel`` authorities, require they agree on
   tenant/scenario/manifest identity, prove both are exact members of the
   selected compiled world, locate the exact declared state field, and
   require its value kind to be exactly ``integer`` or ``number``;
6. derive ``observed_value_kind`` from the source kind and the closed noise
   declaration;
7. build the declaration with a placeholder hash, derive the deterministic
   identifier, compute the deterministic content hash, and finalize it;
8. detachedly strict-revalidate the completed declaration and independently
   re-verify its identifier and content hash against the recomputed digests;
9. persist exactly once through the store's no-overwrite surface (a duplicate
   raises the typed already-exists error and never overwrites the original;
   any failure causes zero writes and no activity event).

Retrieval strictly revalidates the stored record from serialized data and
independently recomputes the deterministic identifier and content hash on
every read, exactly like the other immutable authorities.

The module is pure application logic: no FastAPI, no NEXUS/LEGION imports, no
domain-pack loading, no wall clock, randomness, network, providers,
filesystem, or database access. Public messages never expose internal
reasons, hashes, identities, field values, units, or validator diagnostics.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    DomainPackNotFoundError,
    DomainStateModelNotFoundError,
    ScenarioNotFoundError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationValidationError,
)
from kalhas.application.runtime_observation_declaration_identity import (
    runtime_observation_declaration_content_hash,
    runtime_observation_declaration_identifier,
    verify_runtime_observation_declaration_identity,
)
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.runtime_observation import (
    AdditiveUniformObservationNoise,
    ExternalObservationSource,
    NoObservationNoise,
    ObservationNoise,
    ObservationTiming,
    RuntimeObservationDeclaration,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION, AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.world import WorldVersion

_PLACEHOLDER_HASH = "0" * 64

#: The exact runtime literal of this authoring surface.
RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"

#: The world-integrity body key holding the compiler's embedded pack bindings.
_BINDINGS_KEY = "domain_pack_bindings"


def _validate_metadata_tree(value: object) -> None:
    """Require a genuine recursively JSON-compatible tree; raises ``ValueError``."""
    if value is None:
        return
    if type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not (value == value and value not in (float("inf"), float("-inf"))):
            raise ValueError("metadata must contain only finite JSON-compatible numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_metadata_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("metadata dictionary keys must be strings")
            _validate_metadata_tree(item)
        return
    raise ValueError("metadata must contain only JSON-compatible values")


@dataclass(frozen=True, kw_only=True)
class StateFieldObservationDraft:
    """The caller-owned locators for one exact stored state-field authority.

    Carries only the locator identifiers required to resolve the exact stored
    manifest/state-model/field authority: the ``manifest_id``, the logical
    ``state_model_id``, and the ``state_field_id``. None of the authoritative
    copied values is accepted here; the service copies them from the verified
    stored records.
    """

    manifest_id: str
    state_model_id: str
    state_field_id: str


@dataclass(frozen=True, kw_only=True)
class ExternalObservationDraft:
    """A stable external/offline channel authoring input.

    The channel identifier and the closed integer/number value kind are
    caller-owned; an external source requires no fresh observation noise.
    """

    external_channel_id: str
    external_value_kind: Literal["integer", "number"]


@dataclass(frozen=True, kw_only=True)
class RuntimeObservationDeclarationDraft:
    """The application-local untrusted authoring inputs of one declaration.

    Exactly one of ``state_source`` or ``external_source`` is supplied. The
    scenario/world locators must resolve to an existing tenant-scoped,
    compiler-verified world; authoritative identity/hash/version are never
    accepted from the caller.
    """

    scenario_id: str
    world_version_id: str
    observation_id: str
    state_source: StateFieldObservationDraft | None = None
    external_source: ExternalObservationDraft | None = None
    unit: str | None = None
    timing: ObservationTiming | None = None
    noise: ObservationNoise | None = None
    missing_behavior: Literal["false", "error"] | None = None
    declared_at: AwareDatetime | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)


def _stored_world_authority(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
) -> WorldVersion:
    """Load and verify the tenant's exact world/manifest authority.

    Returns the verified :class:`WorldVersion` record whose ``identifier``
    and ``content_hash`` are the authoritative world identity and digest -
    never accepted from the caller. A missing world/manifest or scenario
    raises the typed validation error; a world that fails compiler
    verification raises the typed integrity error. The world's embedded
    ``source_scenario_id`` must equal the declared scenario, so a declaration
    can never be bound over a foreign world.
    """
    try:
        _scenario = store.get_scenario(tenant_id, scenario_id)
    except ScenarioNotFoundError as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="scenario authority missing"
        ) from exc
    try:
        world = store.get_world(tenant_id, world_version_id)
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="world authority missing"
        ) from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise RuntimeObservationDeclarationIntegrityError(
            tenant_id, scenario_id, world_version_id, reason="world authority corrupt"
        ) from exc
    if world.source_scenario_id != scenario_id:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="world/scenario mismatch"
        )
    return world


def _world_embedded_members(
    world: WorldVersion,
) -> tuple[tuple[DomainStateModel, ...], tuple[DomainPackBinding, ...]]:
    """Extract the state models and pack bindings embedded in the compiled world.

    ``world`` has already passed ``verify_world_snapshot``, so its parent
    content is trustworthy and parses without further integrity checks. These
    are the authoritative world members used to prove a manifest and model
    belong to the selected compiled world rather than merely existing in the
    store. The raw embedded binding collection is explicitly narrowed to a
    JSON array before iteration: malformed embedded data (a non-list value, a
    non-dictionary entry, or an entry that does not validate as a
    :class:`DomainPackBinding`) fails closed through the safe typed
    :class:`RuntimeObservationDeclarationIntegrityError` and is never
    silently accepted.
    """
    catalog = extract_world_catalog(world)
    embedded_bindings: list[DomainPackBinding] = []
    raw_bindings = world.world.get(_BINDINGS_KEY)
    if raw_bindings is not None:
        if not isinstance(raw_bindings, list):
            raise RuntimeObservationDeclarationIntegrityError(
                world.tenant_id,
                world.source_scenario_id,
                world.identifier,
                reason="world authority corrupt",
            )
        for entry in raw_bindings:
            try:
                embedded_bindings.append(DomainPackBinding.model_validate(entry))
            except (ValidationError, TypeError, ValueError, AttributeError):
                raise RuntimeObservationDeclarationIntegrityError(
                    world.tenant_id,
                    world.source_scenario_id,
                    world.identifier,
                    reason="world authority corrupt",
                ) from None
    return catalog.state_models, tuple(embedded_bindings)


def _stored_state_field_authority(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
    world: WorldVersion,
    source: StateFieldObservationDraft,
) -> tuple[str, str, str, str, Literal["integer", "number"]]:
    """Copy authoritative state-field provenance from verified stored records.

    Returns ``(manifest_id, state_model_identifier, state_model_logical_id,
    state_model_content_hash, field_value_kind)`` where every value is copied
    from the stored ``DomainPackManifest``/``DomainStateModel`` records and
    the world's embedded snapshots, never from the caller. The domain-pack
    manifest and the state model must be exact members of the selected
    compiled world. The field must exist and have value kind exactly
    ``integer`` or ``number``; a missing/foreign model, manifest, field, or a
    nonnumeric field raises the typed validation error.
    """
    try:
        manifest: DomainPackManifest = store.get_domain_pack_manifest(tenant_id, source.manifest_id)
    except DomainPackNotFoundError as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state manifest authority missing"
        ) from exc
    try:
        model: DomainStateModel = store.get_domain_state_model(
            tenant_id, scenario_id, source.manifest_id, source.state_model_id
        )
    except DomainStateModelNotFoundError as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state model authority missing"
        ) from exc
    if model.tenant_id != tenant_id:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state model authority tenant mismatch"
        )
    if model.scenario_id != scenario_id or model.manifest_id != manifest.identifier:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state model authority mismatch"
        )

    world_models, world_bindings = _world_embedded_members(world)
    models_by_identifier = {member.identifier: member for member in world_models}
    embedded_model = models_by_identifier.get(model.identifier)
    if embedded_model is None:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id,
            scenario_id,
            world_version_id,
            reason="state model is not a member of the selected compiled world",
        )
    if embedded_model.content_hash != model.content_hash:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state model authority mismatch"
        )
    bindings_by_manifest = {binding.manifest_id: binding for binding in world_bindings}
    embedded_binding = bindings_by_manifest.get(source.manifest_id)
    if embedded_binding is None:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id,
            scenario_id,
            world_version_id,
            reason="state manifest is not a member of the selected compiled world",
        )
    if (
        manifest.pack_id != embedded_binding.pack_id
        or manifest.pack_version != embedded_binding.pack_version
        or manifest.content_hash != embedded_binding.manifest_content_hash
        or manifest.identifier != embedded_binding.manifest_id
    ):
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state manifest authority mismatch"
        )

    field = next((f for f in model.state_fields if f.identifier == source.state_field_id), None)
    if field is None:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="declared state field missing"
        )
    raw_kind = field.value_kind.value if hasattr(field.value_kind, "value") else field.value_kind
    if raw_kind == "integer":
        mapped: Literal["integer", "number"] = "integer"
    elif raw_kind == "number":
        mapped = "number"
    else:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, scenario_id, world_version_id, reason="state field must be integer or number"
        )
    return (
        manifest.identifier,
        model.identifier,
        model.state_model_id,
        model.content_hash,
        mapped,
    )


def _strictly_revalidate_draft(draft: RuntimeObservationDeclarationDraft) -> None:
    """Validate every caller-owned authoring input; raises ValueError.

    Checks structural non-emptiness, the exactly-one-source XOR, that timing,
    noise, and declared_at are genuine contract instances re-validated against
    their strict contracts (rejecting validator-bypassed instances), the
    timezone-aware timestamp, the validated-tree metadata, and - for an
    external source - the required no-fresh-noise declaration. Nothing is
    repaired, coerced, sorted, or normalized.
    """

    if type(draft) is not RuntimeObservationDeclarationDraft:
        raise ValueError("draft must be a valid RuntimeObservationDeclarationDraft")

    def require_identifier(value: object, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
        return value

    require_identifier(draft.scenario_id, "scenario_id")
    require_identifier(draft.world_version_id, "world_version_id")
    require_identifier(draft.observation_id, "observation_id")

    if (draft.state_source is None) == (draft.external_source is None):
        raise ValueError("exactly one of state_source or external_source must be set")

    if draft.state_source is not None:
        source = draft.state_source
        require_identifier(source.manifest_id, "manifest_id")
        require_identifier(source.state_model_id, "state_model_id")
        require_identifier(source.state_field_id, "state_field_id")
    else:
        external = draft.external_source
        if external is None:
            raise ValueError("exactly one of state_source or external_source must be set")
        require_identifier(external.external_channel_id, "external_channel_id")
        if external.external_value_kind not in ("integer", "number"):
            raise ValueError("external_source value kind must be 'integer' or 'number'")

    timing = draft.timing
    if timing is None or type(timing) is not ObservationTiming:
        raise ValueError("timing must be a valid ObservationTiming")
    try:
        revalidated_timing = ObservationTiming.model_validate(
            timing.model_dump(mode="python"), strict=True
        )
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("timing must be a valid ObservationTiming") from None
    if revalidated_timing != timing:
        raise ValueError("timing must be a valid ObservationTiming")

    noise = draft.noise
    if noise is None:
        raise ValueError("noise must be a valid observation noise declaration")
    if isinstance(noise, NoObservationNoise) and (noise.kind != "none" or noise.draw_count != 0):
        raise ValueError("no-observation-noise must declare kind 'none' and draw_count 0")
    if isinstance(noise, AdditiveUniformObservationNoise) and (
        noise.kind != "additive_uniform" or noise.draw_count != 1
    ):
        raise ValueError("additive noise must declare kind 'additive_uniform' and draw_count 1")
    if not isinstance(noise, (NoObservationNoise, AdditiveUniformObservationNoise)):
        raise ValueError("noise must be a valid observation noise declaration")
    try:
        revalidated_noise = type(noise).model_validate(noise.model_dump(mode="python"), strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("noise must be a valid observation noise declaration") from None
    if revalidated_noise != noise:
        raise ValueError("noise must be a valid observation noise declaration")

    declared_at = draft.declared_at
    if declared_at is None or not isinstance(declared_at, datetime):
        raise ValueError("declared_at must be a timezone-aware datetime")
    if declared_at.tzinfo is None or declared_at.utcoffset() is None:
        raise ValueError("declared_at must be a timezone-aware datetime")

    if not isinstance(draft.missing_behavior, str) or draft.missing_behavior not in (
        "false",
        "error",
    ):
        raise ValueError("missing_behavior must be 'false' or 'error'")

    if draft.state_source is None and not isinstance(noise, NoObservationNoise):
        raise ValueError("external source requires the no-fresh-noise declaration")

    if not isinstance(draft.metadata, dict):
        raise ValueError("metadata must be a JSON-compatible object")
    try:
        _validate_metadata_tree(draft.metadata)
    except ValueError as exc:
        raise ValueError("metadata must contain only finite JSON-compatible values") from exc


def declare_runtime_observation_declaration(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    draft: RuntimeObservationDeclarationDraft,
) -> RuntimeObservationDeclaration:
    """Declare an immutable runtime observation declaration; raises typed errors.

    Runs the exact deterministic authoring flow; the returned object is a
    detached immutable deep copy. A duplicate locality raises the typed
    already-exists error and never overwrites the original; every other
    failure is atomic with zero writes and no activity event.
    """
    try:
        _strictly_revalidate_draft(draft)
    except ValueError as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, draft.scenario_id, draft.world_version_id, reason="draft invalid"
        ) from exc

    world = _stored_world_authority(store, tenant_id, draft.scenario_id, draft.world_version_id)
    world_version_id = world.identifier
    world_content_hash = world.content_hash

    if draft.state_source is not None:
        (
            manifest_id,
            model_identifier,
            model_logical_id,
            model_content_hash,
            field_value_kind,
        ) = _stored_state_field_authority(
            store,
            tenant_id,
            draft.scenario_id,
            world_version_id,
            world,
            draft.state_source,
        )
        source_kind: Literal["integer", "number"] = field_value_kind
        observation_source: StateFieldObservationSource | ExternalObservationSource = (
            StateFieldObservationSource(
                kind="state_field",
                manifest_id=manifest_id,
                state_model_identifier=model_identifier,
                state_model_id=model_logical_id,
                state_model_content_hash=model_content_hash,
                state_field_id=draft.state_source.state_field_id,
                state_field_value_kind=field_value_kind,
            )
        )
    else:
        external = draft.external_source
        if external is None:
            raise RuntimeObservationDeclarationValidationError(
                tenant_id, draft.scenario_id, world_version_id, reason="draft invalid"
            )
        source_kind = external.external_value_kind
        observation_source = ExternalObservationSource(
            kind="external_input",
            external_channel_id=external.external_channel_id,
            external_value_kind=source_kind,
        )

    timing = draft.timing
    noise = draft.noise
    missing_behavior = draft.missing_behavior
    declared_at = draft.declared_at
    if timing is None or noise is None or missing_behavior is None or declared_at is None:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id, draft.scenario_id, world_version_id, reason="draft invalid"
        )

    if isinstance(noise, AdditiveUniformObservationNoise):
        observed_value_kind: Literal["integer", "number"] = "number"
    else:
        observed_value_kind = source_kind

    placeholder = RuntimeObservationDeclaration(
        identifier=runtime_observation_declaration_identifier(
            tenant_id=tenant_id,
            scenario_id=draft.scenario_id,
            world_version_id=world_version_id,
            observation_id=draft.observation_id,
        ),
        tenant_id=tenant_id,
        schema_version=SCHEMA_VERSION,
        scenario_id=draft.scenario_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
        observation_id=draft.observation_id,
        runtime_version=RUNTIME_VERSION,
        observation_source=observation_source,
        observed_value_kind=observed_value_kind,
        unit=draft.unit,
        timing=timing,
        noise=noise,
        missing_behavior=missing_behavior,
        content_hash=_PLACEHOLDER_HASH,
        declared_at=declared_at,
        metadata=draft.metadata,
    )
    digest = runtime_observation_declaration_content_hash(placeholder)
    declaration = placeholder.model_copy(update={"content_hash": digest})

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = declaration.model_dump(mode="python")
        revalidated = RuntimeObservationDeclaration.model_validate(serialized, strict=True)
        verify_runtime_observation_declaration_identity(
            revalidated,
            tenant_id=tenant_id,
            scenario_id=draft.scenario_id,
            world_version_id=world_version_id,
            observation_id=draft.observation_id,
        )
    except (ValidationError, TypeError, ValueError, AttributeError) as exc:
        raise RuntimeObservationDeclarationValidationError(
            tenant_id,
            draft.scenario_id,
            world_version_id,
            reason="declaration contradicts its contract",
        ) from exc

    store.put_runtime_observation_declaration(
        tenant_id=tenant_id,
        scenario_id=draft.scenario_id,
        world_version_id=world_version_id,
        observation_id=draft.observation_id,
        declaration=declaration,
    )
    return declaration.model_copy(deep=True)


__all__ = [
    "ExternalObservationDraft",
    "RuntimeObservationDeclarationDraft",
    "StateFieldObservationDraft",
    "declare_runtime_observation_declaration",
]
