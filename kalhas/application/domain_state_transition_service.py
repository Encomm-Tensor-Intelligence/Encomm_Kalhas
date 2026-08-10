"""Deterministic domain state-transition declaration service.

A transition specification is the immutable, tenant-scoped declarative
description of one *possible* state change for an already-declared
``DomainStateModel`` - data only, never behavior. A guard is only a
declarative equality condition and a target is only a declarative
intended state patch: nothing here executes transitions, mutates state,
invokes domain packs, evaluates formulas or expressions, generates
outcomes, creates evidence, produces recommendations, or performs any
real-world action, and no domain-pack code is ever loaded, imported,
instantiated, invoked, or interpreted.

Every identity field is copied exclusively from stored immutable records
- the scenario, the ``DomainPackBinding``, the registered
``DomainPackManifest``, and the declared ``DomainStateModel`` - never
from client input. The service verifies the stored binding and manifest
are exactly the records implied by the request (tenants, scenario and
manifest identifiers, deterministic binding identifier) and that the
binding snapshot still matches the registered manifest (pack id, pack
version, manifest content hash, and the exact ordered capability
identifier set) before accepting a transition. It additionally verifies
the referenced state model's copied identity, deterministic identifier,
content hash, canonical field representation, and binding relationship
against the stored immutable records, so a tampered or inconsistent
record raises a safe typed integrity error. The transition identifier
and content hash are deterministic, guard/target mappings are
canonicalized by field identifier, and every guard/target key must
identify an existing state-model field whose declared ``StateValueKind``
and ``allowed_values`` exactly match the supplied value - otherwise a
typed validation error is raised and nothing is stored.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    DomainStateTransitionIntegrityError,
    DomainStateTransitionValuesError,
)
from kalhas.application.domain_pack_binding_service import binding_identifier
from kalhas.application.domain_state_model_service import (
    canonical_state_fields,
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    _canonical_value_text,
    _value_matches_kind,
)
from kalhas.contracts.v1.transition import DomainStateTransition

_TRANSITION_ID_PREFIX = "transition-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def transition_identifier(
    *,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    transition_id: str,
) -> str:
    """Deterministic, collision-safe transition identifier.

    Hash-derived from the canonical identity tuple (scenario, manifest,
    state model, transition id), so user-provided delimiter characters
    cannot create ambiguity and identical inputs always yield the same
    identifier. Never random, never wall-clock.
    """
    canonical = canonical_json(
        {
            "scenario_id": scenario_id,
            "manifest_id": manifest_id,
            "state_model_id": state_model_id,
            "transition_id": transition_id,
        }
    )
    return f"{_TRANSITION_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def transition_content_hash(transition: DomainStateTransition) -> str:
    """Canonical SHA-256 of the transition content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, and guard/target mappings are canonicalized
    by field identifier, so equivalent transitions always produce the
    same lowercase 64-character digest.
    """
    payload = transition.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def canonical_value_mappings(
    *,
    guard_values: dict[str, JsonValue],
    target_values: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Order guard/target mappings by field identifier (stable, deterministic).

    Caller key ordering must never be a source of nondeterminism:
    equivalent declarations with differently ordered mappings produce the
    same canonical transition, content hash, stored representation, and
    world snapshot.
    """
    return (
        dict(sorted(guard_values.items())),
        dict(sorted(target_values.items())),
    )


def _verify_binding_integrity(
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
) -> None:
    """Raise a safe typed integrity error when stored records are inconsistent.

    Verifies that the stored binding and manifest are exactly the records
    implied by the request - binding tenant matches the requested tenant,
    manifest tenant matches the requested tenant, binding scenario and
    manifest identifiers match the request, and the binding identifier
    matches its deterministic derivation - and that the binding snapshot
    exactly matches the registered manifest: logical pack id, semantic
    pack version, authoritative content hash, and the exact ordered
    capability identifier set. On any mismatch the raised error carries a
    generic public message and an internal ``reason`` for diagnostics
    only - raw hashes and internal details are never exposed.
    """
    if binding.tenant_id != tenant_id:
        reason = "binding tenant mismatch"
    elif manifest.tenant_id != tenant_id:
        reason = "manifest tenant mismatch"
    elif binding.scenario_id != scenario_id:
        reason = "binding scenario mismatch"
    elif binding.manifest_id != manifest_id:
        reason = "binding manifest mismatch"
    elif binding.identifier != binding_identifier(scenario_id=scenario_id, manifest_id=manifest_id):
        reason = "binding identifier mismatch"
    elif binding.pack_id != manifest.pack_id:
        reason = "pack_id mismatch"
    elif binding.pack_version != manifest.pack_version:
        reason = "pack_version mismatch"
    elif binding.manifest_content_hash != manifest.content_hash:
        reason = "manifest content hash mismatch"
    elif binding.capability_ids != tuple(
        capability.identifier for capability in manifest.capabilities
    ):
        reason = "capability identifier set mismatch"
    else:
        return
    raise DomainStateTransitionIntegrityError(
        tenant_id, scenario_id, manifest_id, state_model_id, reason=reason
    )


def _verify_state_model_integrity(
    state_model: DomainStateModel,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
) -> None:
    """Verify the stored state model against the stored immutable records.

    The referenced state model must carry the copied identity implied by
    the request (tenant, scenario, manifest, binding relationship), its
    deterministic identifier must match the derivation from the canonical
    scenario/manifest/state-model identity, its ``content_hash`` must
    match the recomputed canonical digest, its pack identity and manifest
    content hash must match the binding and registered manifest, and its
    state fields must be canonicalized by identifier. On any mismatch a
    safe typed integrity error is raised with a generic public message
    and an internal ``reason`` for diagnostics only.
    """
    if state_model.tenant_id != tenant_id:
        reason = "state model tenant mismatch"
    elif state_model.scenario_id != scenario_id:
        reason = "state model scenario mismatch"
    elif state_model.manifest_id != manifest_id:
        reason = "state model manifest mismatch"
    elif state_model.binding_id != binding.identifier:
        reason = "state model binding relationship mismatch"
    elif state_model.identifier != state_model_identifier(
        scenario_id=scenario_id, manifest_id=manifest_id, state_model_id=state_model_id
    ):
        reason = "state model identifier mismatch"
    elif state_model.content_hash != state_model_content_hash(state_model):
        reason = "state model content hash mismatch"
    elif state_model.pack_id != binding.pack_id:
        reason = "state model pack_id mismatch"
    elif state_model.pack_version != binding.pack_version:
        reason = "state model pack_version mismatch"
    elif state_model.manifest_content_hash != manifest.content_hash:
        reason = "state model manifest content hash mismatch"
    elif state_model.state_fields != canonical_state_fields(state_model.state_fields):
        reason = "state model fields not canonical"
    else:
        return
    raise DomainStateTransitionIntegrityError(
        tenant_id, scenario_id, manifest_id, state_model_id, reason=reason
    )


def _field_by_identifier(
    state_model: DomainStateModel,
) -> dict[str, DomainStateFieldDefinition]:
    """Map the state model's canonical field identifiers to their definitions."""
    return {field.identifier: field for field in state_model.state_fields}


def _validate_transition_values(
    state_model: DomainStateModel,
    *,
    state_model_id: str,
    transition_id: str,
    guard_values: dict[str, JsonValue],
    target_values: dict[str, JsonValue],
) -> None:
    """Enforce the declarative value rules of the referenced state model.

    Every guard/target key must identify an existing field of the
    referenced state model, every guard/target value must exactly match
    that field's ``StateValueKind`` (booleans are never accepted as
    integers or numbers, and non-finite floats are rejected everywhere -
    including arbitrarily nested inside ``json`` values), and when the
    field declares ``allowed_values`` the value must be canonically among
    them. Any violation raises a typed validation error and nothing is
    stored; the guards are never evaluated and the targets are never
    applied.
    """
    fields = _field_by_identifier(state_model)
    for mapping_name, mapping in (("guard", guard_values), ("target", target_values)):
        for key, value in mapping.items():
            field_definition = fields.get(key)
            if field_definition is None:
                raise DomainStateTransitionValuesError(
                    state_model_id,
                    transition_id,
                    reason=f"{mapping_name} field {key!r} does not exist in the state model",
                )
            if not _value_matches_kind(value, field_definition.value_kind):
                raise DomainStateTransitionValuesError(
                    state_model_id,
                    transition_id,
                    reason=(
                        f"{mapping_name} value for field {key!r} does not match its "
                        f"declared value kind {field_definition.value_kind.value!r}"
                    ),
                )
            if field_definition.allowed_values:
                canonical = _canonical_value_text(value)
                allowed = [
                    _canonical_value_text(allowed_value)
                    for allowed_value in field_definition.allowed_values
                ]
                if canonical not in allowed:
                    raise DomainStateTransitionValuesError(
                        state_model_id,
                        transition_id,
                        reason=(
                            f"{mapping_name} value for field {key!r} is not among its "
                            "declared allowed_values"
                        ),
                    )


def build_transition(
    *,
    tenant_id: str,
    scenario_id: str,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    state_model: DomainStateModel,
    transition_id: str,
    description: str,
    guard_values: dict[str, JsonValue],
    target_values: dict[str, JsonValue],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateTransition:
    """Build a transition from verified stored records (never from client input).

    All identity fields (binding id, manifest id, logical ``pack_id``,
    semantic ``pack_version``, authoritative manifest content hash, and
    the referenced state model's authoritative content hash) are copied
    from the stored immutable binding, manifest, and state model. The
    transition identifier is deterministically derived from the canonical
    scenario/manifest/state-model/transition identity tuple, guard and
    target mappings are canonicalized by field identifier, and the
    transition content hash is computed over the canonical serialized
    transition content excluding ``content_hash`` itself.
    """
    if metadata is None:
        metadata = {}
    canonical_guard, canonical_target = canonical_value_mappings(
        guard_values=guard_values, target_values=target_values
    )
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=scenario_id,
            manifest_id=manifest.identifier,
            state_model_id=state_model.state_model_id,
            transition_id=transition_id,
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding_id=binding.identifier,
        manifest_id=manifest.identifier,
        pack_id=manifest.pack_id,
        pack_version=manifest.pack_version,
        manifest_content_hash=manifest.content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=transition_id,
        description=description,
        guard_values=canonical_guard,
        target_values=canonical_target,
        content_hash=_PLACEHOLDER_HASH,
        declared_at=declared_at,
        metadata=metadata,
    )
    digest = transition_content_hash(transition)
    return transition.model_copy(update={"content_hash": digest})


def declare_transition(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    transition_id: str,
    description: str,
    guard_values: dict[str, JsonValue],
    target_values: dict[str, JsonValue],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateTransition:
    """Declare an immutable transition for a state model; raises typed errors.

    The tenant must own the scenario (404 otherwise), the manifest must
    already be bound to that exact scenario (404 otherwise), and the
    referenced state model must exist (404 otherwise). The stored binding
    and manifest must be exactly the records implied by the request
    (binding/manifest tenant, binding scenario and manifest identifiers,
    deterministic binding identifier) with the binding snapshot exactly
    matching the registered manifest, and the stored state model must
    carry its verified copied identity, deterministic identifier, content
    hash, canonical fields, and binding relationship - any inconsistency
    raises a safe typed 409 integrity error. Guard/target keys must
    identify existing state-model fields whose declared value kind and
    allowed values exactly match the supplied values (typed 422
    otherwise). Duplicate transitions raise a typed 409 and never
    overwrite the original. The transition is never executed or
    interpreted: guards are never evaluated and targets are never
    applied.
    """
    store.get_scenario(tenant_id, scenario_id)
    binding = store.get_domain_pack_binding(tenant_id, scenario_id, manifest_id)
    manifest = store.get_domain_pack_manifest(tenant_id, manifest_id)
    state_model = store.get_domain_state_model(tenant_id, scenario_id, manifest_id, state_model_id)
    _verify_binding_integrity(
        binding,
        manifest,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
    )
    _verify_state_model_integrity(
        state_model,
        binding,
        manifest,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
    )
    _validate_transition_values(
        state_model,
        state_model_id=state_model_id,
        transition_id=transition_id,
        guard_values=guard_values,
        target_values=target_values,
    )
    transition = build_transition(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding=binding,
        manifest=manifest,
        state_model=state_model,
        transition_id=transition_id,
        description=description,
        guard_values=guard_values,
        target_values=target_values,
        declared_at=declared_at,
        metadata=metadata,
    )
    store.put_domain_state_transition(transition)
    return transition


def get_transition(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    transition_id: str,
) -> DomainStateTransition:
    """Fetch one transition; raises DomainStateTransitionNotFoundError."""
    return store.get_domain_state_transition(
        tenant_id, scenario_id, manifest_id, state_model_id, transition_id
    )


def list_transitions(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str
) -> tuple[DomainStateTransition, ...]:
    """List a scenario's transitions in deterministic order.

    Ordered by ``(manifest_id, state_model_id, transition_id)``. Verifies
    the tenant owns the scenario first: unknown or foreign scenarios
    raise the existing typed 404 (ScenarioNotFoundError).
    """
    store.get_scenario(tenant_id, scenario_id)
    return store.list_domain_state_transitions(tenant_id, scenario_id)
