"""Deterministic domain pack binding service.

A binding is the immutable, tenant-scoped link between one registered
``DomainPackManifest`` and one ``ScenarioSpec``. The service copies every
pack identity and hash field exclusively from the stored immutable
manifest - never from client input (the API draft carries only
``manifest_id`` and ``bound_at``) - and stores the frozen binding keyed by
``(tenant_id, scenario_id, manifest_id)``.

The service is pure and deterministic: the binding identifier is hash
derived from canonical identity inputs, ``bound_at`` is supplied
explicitly, and nothing loads, instantiates, imports, or executes a domain
pack. The compiler consumes the stored bindings as declarative snapshots.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import DomainPackBinding, DomainPackManifest
from kalhas.contracts.v1.shared import AwareDatetime

_BINDING_ID_PREFIX = "binding-"
_ID_HASH_LENGTH = 16


def binding_identifier(*, scenario_id: str, manifest_id: str) -> str:
    """Deterministic, collision-safe binding identifier.

    Hash-derived from the canonical identity tuple, so user-provided
    delimiter characters cannot create ambiguity and identical inputs
    always yield the same identifier. Never random, never wall-clock.
    """
    canonical = canonical_json({"scenario_id": scenario_id, "manifest_id": manifest_id})
    return f"{_BINDING_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def build_binding(
    *,
    tenant_id: str,
    scenario_id: str,
    manifest: DomainPackManifest,
    bound_at: AwareDatetime,
) -> DomainPackBinding:
    """Build a binding from the registered manifest (never from client input).

    Copies the manifest's identifier, logical ``pack_id``, semantic
    ``pack_version``, authoritative content hash, and the ordered
    capability identifiers exactly as registered.
    """
    return DomainPackBinding(
        identifier=binding_identifier(scenario_id=scenario_id, manifest_id=manifest.identifier),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest.identifier,
        pack_id=manifest.pack_id,
        pack_version=manifest.pack_version,
        manifest_content_hash=manifest.content_hash,
        capability_ids=tuple(capability.identifier for capability in manifest.capabilities),
        bound_at=bound_at,
    )


def bind_manifest(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    bound_at: AwareDatetime,
) -> DomainPackBinding:
    """Bind a registered manifest to a scenario; raises typed errors.

    The tenant must own both the scenario and the registered manifest:
    unknown or foreign scenarios raise ScenarioNotFoundError and unknown
    or foreign manifests raise DomainPackNotFoundError (both typed 404
    without leaking another tenant's data). Duplicate bindings raise
    DomainPackBindingAlreadyExistsError and never overwrite the original.
    """
    store.get_scenario(tenant_id, scenario_id)
    manifest = store.get_domain_pack_manifest(tenant_id, manifest_id)
    binding = build_binding(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest=manifest,
        bound_at=bound_at,
    )
    store.put_domain_pack_binding(binding)
    return binding


def get_binding(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str, manifest_id: str
) -> DomainPackBinding:
    """Fetch one binding; raises DomainPackBindingNotFoundError."""
    return store.get_domain_pack_binding(tenant_id, scenario_id, manifest_id)


def list_bindings(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str
) -> tuple[DomainPackBinding, ...]:
    """List a scenario's bindings in deterministic manifest-id order.

    Verifies the tenant owns the scenario first: unknown or foreign
    scenarios raise the existing typed 404 (ScenarioNotFoundError).
    """
    store.get_scenario(tenant_id, scenario_id)
    return store.list_domain_pack_bindings(tenant_id, scenario_id)
