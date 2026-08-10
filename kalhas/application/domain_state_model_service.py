"""Deterministic domain state-model declaration service.

A state model is the immutable, tenant-scoped declarative definition of
which state fields exist for a scenario-bound domain pack - data only,
never behavior. It declares field identifiers, value kinds, initial
values, and optional allowed values; nothing here executes transitions,
formulas, expressions, policies, mechanisms, simulations, outcomes,
metrics, evidence, recommendations, briefs, or real-world actions, and no
domain-pack code is ever loaded, imported, instantiated, invoked, or
interpreted.

Every identity field is copied exclusively from stored immutable records
- the scenario, the ``DomainPackBinding``, and the registered
``DomainPackManifest`` - never from client input. The service verifies
the stored binding and manifest are exactly the records implied by the
request (tenants, scenario and manifest identifiers, deterministic
binding identifier) and that the binding snapshot still matches the
registered manifest (pack id, pack version, manifest content hash, and
the exact ordered capability identifier set) before accepting a state
model, so a tampered or inconsistent snapshot raises a safe typed
integrity error. The state-model identifier and content hash are
deterministic, and state fields are canonicalized by identifier so
equivalent caller orderings produce the same canonical model and hash.
"""

from __future__ import annotations

from kalhas.application.domain_errors import DomainStateModelIntegrityError
from kalhas.application.domain_pack_binding_service import binding_identifier
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
)

_STATE_MODEL_ID_PREFIX = "state-model-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def state_model_identifier(*, scenario_id: str, manifest_id: str, state_model_id: str) -> str:
    """Deterministic, collision-safe state-model identifier.

    Hash-derived from the canonical identity tuple (scenario, manifest,
    state-model id), so user-provided delimiter characters cannot create
    ambiguity and identical inputs always yield the same identifier.
    Never random, never wall-clock.
    """
    canonical = canonical_json(
        {
            "scenario_id": scenario_id,
            "manifest_id": manifest_id,
            "state_model_id": state_model_id,
        }
    )
    return f"{_STATE_MODEL_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def state_model_content_hash(state_model: DomainStateModel) -> str:
    """Canonical SHA-256 of the state-model content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, and state fields are canonicalized by
    identifier, so equivalent models always produce the same lowercase
    64-character digest.
    """
    payload = state_model.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def canonical_state_fields(
    state_fields: tuple[DomainStateFieldDefinition, ...],
) -> tuple[DomainStateFieldDefinition, ...]:
    """Order state fields by identifier (stable, deterministic).

    Caller field ordering must never be a source of nondeterminism:
    equivalent declarations with differently ordered fields produce the
    same canonical model, content hash, and world snapshot.
    """
    return tuple(sorted(state_fields, key=lambda field: field.identifier))


def _verify_binding_integrity(
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
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
    raise DomainStateModelIntegrityError(tenant_id, scenario_id, manifest_id, reason=reason)


def build_state_model(
    *,
    tenant_id: str,
    scenario_id: str,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    state_model_id: str,
    state_fields: tuple[DomainStateFieldDefinition, ...],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateModel:
    """Build a state model from verified stored records (never from client input).

    All identity fields (binding id, manifest id, logical ``pack_id``,
    semantic ``pack_version``, authoritative manifest content hash) are
    copied from the stored immutable binding and manifest. The state-model
    identifier is deterministically derived from the canonical
    scenario/manifest/state-model identity tuple, state fields are
    canonicalized by identifier, and the model content hash is computed
    over the canonical serialized model content excluding
    ``content_hash`` itself.
    """
    if metadata is None:
        metadata = {}
    state_model = DomainStateModel(
        identifier=state_model_identifier(
            scenario_id=scenario_id, manifest_id=manifest.identifier, state_model_id=state_model_id
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding_id=binding.identifier,
        manifest_id=manifest.identifier,
        pack_id=manifest.pack_id,
        pack_version=manifest.pack_version,
        manifest_content_hash=manifest.content_hash,
        state_model_id=state_model_id,
        state_fields=canonical_state_fields(state_fields),
        content_hash=_PLACEHOLDER_HASH,
        declared_at=declared_at,
        metadata=metadata,
    )
    digest = state_model_content_hash(state_model)
    return state_model.model_copy(update={"content_hash": digest})


def declare_state_model(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    state_fields: tuple[DomainStateFieldDefinition, ...],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateModel:
    """Declare an immutable state model for a bound manifest; raises typed errors.

    The tenant must own the scenario (404 otherwise) and the manifest
    must already be bound to that exact scenario (404 otherwise). The
    stored binding and manifest must be exactly the records implied by
    the request (binding/manifest tenant, binding scenario and manifest
    identifiers, deterministic binding identifier) and the binding
    snapshot must exactly match the registered manifest (pack id, pack
    version, content hash, capability identifier set) or a safe typed 409
    integrity error is raised. Duplicate state models raise a typed 409
    and never overwrite the original. The state model is never executed
    or interpreted.
    """
    store.get_scenario(tenant_id, scenario_id)
    binding = store.get_domain_pack_binding(tenant_id, scenario_id, manifest_id)
    manifest = store.get_domain_pack_manifest(tenant_id, manifest_id)
    _verify_binding_integrity(
        binding,
        manifest,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
    )
    state_model = build_state_model(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding=binding,
        manifest=manifest,
        state_model_id=state_model_id,
        state_fields=state_fields,
        declared_at=declared_at,
        metadata=metadata,
    )
    store.put_domain_state_model(state_model)
    return state_model


def get_state_model(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
) -> DomainStateModel:
    """Fetch one state model; raises DomainStateModelNotFoundError."""
    return store.get_domain_state_model(tenant_id, scenario_id, manifest_id, state_model_id)


def list_state_models(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str
) -> tuple[DomainStateModel, ...]:
    """List a scenario's state models in deterministic manifest-id then state-model-id order.

    Verifies the tenant owns the scenario first: unknown or foreign
    scenarios raise the existing typed 404 (ScenarioNotFoundError).
    """
    store.get_scenario(tenant_id, scenario_id)
    return store.list_domain_state_models(tenant_id, scenario_id)
