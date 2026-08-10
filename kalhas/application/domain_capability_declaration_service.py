"""Deterministic domain capability declaration service.

A declaration is the immutable, tenant-scoped set of declared input
values for exactly one capability of a manifest already bound to a
scenario. It is a generic declared fact/configuration input for future
domain mechanisms: generic key/value data validated only against the
capability's declared ``input_ids`` (no schema interpretation beyond safe
identifier matching). Nothing here executes a capability, invokes code,
calculates outputs, generates metrics, or produces decision evidence.

Every identity field is copied exclusively from stored immutable records
- the scenario, the ``DomainPackBinding``, and the registered
``DomainPackManifest`` - never from client input. The service verifies
the stored binding and manifest are exactly the records implied by the
request (tenants, scenario and manifest identifiers, deterministic
binding identifier) and that the binding snapshot still matches the
registered manifest (pack id, pack version, manifest content hash, and
the exact ordered capability identifier set) before accepting a
declaration, so a tampered or inconsistent snapshot raises a safe typed
integrity error. The declaration identifier and content hash are
deterministic.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    DomainCapabilityDeclarationIntegrityError,
    DomainCapabilityInputKeyMismatchError,
    DomainCapabilityNotFoundError,
)
from kalhas.application.domain_pack_binding_service import binding_identifier
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue

_DECLARATION_ID_PREFIX = "declaration-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def declaration_identifier(*, scenario_id: str, manifest_id: str, capability_id: str) -> str:
    """Deterministic, collision-safe declaration identifier.

    Hash-derived from the canonical identity tuple (scenario, manifest,
    capability), so user-provided delimiter characters cannot create
    ambiguity and identical inputs always yield the same identifier.
    Never random, never wall-clock.
    """
    canonical = canonical_json(
        {
            "scenario_id": scenario_id,
            "manifest_id": manifest_id,
            "capability_id": capability_id,
        }
    )
    return f"{_DECLARATION_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def declaration_content_hash(declaration: DomainCapabilityDeclaration) -> str:
    """Canonical SHA-256 of the declaration content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, so equivalent declarations always produce
    the same lowercase 64-character digest.
    """
    payload = declaration.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


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
    raise DomainCapabilityDeclarationIntegrityError(
        tenant_id, scenario_id, manifest_id, reason=reason
    )


def build_declaration(
    *,
    tenant_id: str,
    scenario_id: str,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    capability_id: str,
    input_values: dict[str, JsonValue],
    declared_at: AwareDatetime,
) -> DomainCapabilityDeclaration:
    """Build a declaration from verified stored records (never from client input).

    All identity fields (binding id, manifest id, logical ``pack_id``,
    semantic ``pack_version``, authoritative manifest content hash) are
    copied from the stored immutable binding and manifest. The
    declaration identifier is deterministically derived from the
    canonical scenario/manifest/capability identity tuple, and the
    declaration content hash is computed over the canonical serialized
    declaration content excluding ``content_hash`` itself.
    """
    declaration = DomainCapabilityDeclaration(
        identifier=declaration_identifier(
            scenario_id=scenario_id, manifest_id=manifest.identifier, capability_id=capability_id
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding_id=binding.identifier,
        manifest_id=manifest.identifier,
        pack_id=manifest.pack_id,
        pack_version=manifest.pack_version,
        manifest_content_hash=manifest.content_hash,
        capability_id=capability_id,
        input_values=input_values,
        content_hash=_PLACEHOLDER_HASH,
        declared_at=declared_at,
    )
    digest = declaration_content_hash(declaration)
    return declaration.model_copy(update={"content_hash": digest})


def declare_capability_inputs(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    capability_id: str,
    input_values: dict[str, JsonValue],
    declared_at: AwareDatetime,
) -> DomainCapabilityDeclaration:
    """Declare immutable input values for a bound capability; raises typed errors.

    The tenant must own the scenario (404 otherwise) and the manifest
    must already be bound to that exact scenario (404 otherwise). The
    stored binding and manifest must be exactly the records implied by
    the request (binding/manifest tenant, binding scenario and manifest
    identifiers, deterministic binding identifier) and the binding
    snapshot must exactly match the registered manifest (pack id, pack
    version, content hash, capability identifier set) or a safe typed 409
    integrity error is raised. The capability must be declared by the
    manifest, and the input-value keys must match its ordered
    ``input_ids`` exactly - no missing keys, no extra keys (a capability
    with no ``input_ids`` accepts only an empty object) - or a typed 422
    error is raised. Duplicate declarations raise a typed 409 and never
    overwrite the original.
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

    capability = next(
        (candidate for candidate in manifest.capabilities if candidate.identifier == capability_id),
        None,
    )
    if capability is None:
        raise DomainCapabilityNotFoundError(capability_id, manifest_id)

    declared_keys = set(input_values)
    expected_keys = set(capability.input_ids)
    missing = tuple(sorted(expected_keys - declared_keys))
    extra = tuple(sorted(declared_keys - expected_keys))
    if missing or extra:
        raise DomainCapabilityInputKeyMismatchError(
            capability_id, manifest_id, missing=missing, extra=extra
        )

    declaration = build_declaration(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding=binding,
        manifest=manifest,
        capability_id=capability_id,
        input_values=input_values,
        declared_at=declared_at,
    )
    store.put_domain_capability_declaration(declaration)
    return declaration


def get_declaration(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    capability_id: str,
) -> DomainCapabilityDeclaration:
    """Fetch one declaration; raises DomainCapabilityDeclarationNotFoundError."""
    return store.get_domain_capability_declaration(
        tenant_id, scenario_id, manifest_id, capability_id
    )


def list_declarations(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str
) -> tuple[DomainCapabilityDeclaration, ...]:
    """List a scenario's declarations in deterministic manifest-id then capability-id order.

    Verifies the tenant owns the scenario first: unknown or foreign
    scenarios raise the existing typed 404 (ScenarioNotFoundError).
    """
    store.get_scenario(tenant_id, scenario_id)
    return store.list_domain_capability_declarations(tenant_id, scenario_id)
