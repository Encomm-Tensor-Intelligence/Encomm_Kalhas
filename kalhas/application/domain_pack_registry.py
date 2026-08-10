"""Domain pack registry: deterministic, declarative manifest registration.

A registered ``DomainPackManifest`` is metadata, never executable code:
nothing in this module loads, imports, instantiates, or executes a pack.
The registry builds the manifest from a validated registration draft,
computes its canonical SHA-256 content hash, stores the immutable manifest
tenant-scoped, and serves deterministic lookups and listings.

The content hash is computed over the canonical serialized manifest content
**excluding ``content_hash`` itself**. There is no parameter for a
client-supplied hash: the authority is always the computed digest.
Everything is deterministic - no wall clock (``created_at`` comes from the
draft), no randomness, no I/O.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue

_PLACEHOLDER_HASH = "0" * 64


def manifest_content_hash(manifest: DomainPackManifest) -> str:
    """Canonical SHA-256 of the manifest content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, so equivalent manifests always produce the
    same lowercase 64-character digest.
    """
    payload = manifest.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def build_manifest(
    *,
    tenant_id: str,
    identifier: str,
    pack_id: str,
    name: str,
    pack_version: str,
    description: str | None,
    supported_api_versions: tuple[str, ...],
    capabilities: tuple[DomainPackCapability, ...],
    schema_metadata: dict[str, JsonValue],
    created_at: AwareDatetime,
    metadata: dict[str, JsonValue],
) -> DomainPackManifest:
    """Build a fully validated manifest with its computed content hash.

    The draft is validated by the strict contract (unknown fields,
    semantic ``pack_version``, API version ``1`` required, unique
    capability identifiers). The authoritative content hash is computed
    here; a caller cannot supply one.
    """
    manifest = DomainPackManifest(
        identifier=identifier,
        tenant_id=tenant_id,
        pack_id=pack_id,
        name=name,
        pack_version=pack_version,
        description=description,
        supported_api_versions=supported_api_versions,
        capabilities=capabilities,
        schema_metadata=schema_metadata,
        content_hash=_PLACEHOLDER_HASH,
        created_at=created_at,
        metadata=metadata,
    )
    digest = manifest_content_hash(manifest)
    return manifest.model_copy(update={"content_hash": digest})


def register_manifest(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    identifier: str,
    pack_id: str,
    name: str,
    pack_version: str,
    description: str | None,
    supported_api_versions: tuple[str, ...],
    capabilities: tuple[DomainPackCapability, ...],
    schema_metadata: dict[str, JsonValue],
    created_at: AwareDatetime,
    metadata: dict[str, JsonValue],
) -> DomainPackManifest:
    """Register an immutable manifest; raises DomainPackAlreadyExistsError.

    Tenant ownership is derived from ``tenant_id`` (the X-Tenant-ID header
    at the API boundary); the draft carries no tenant or hash input.
    """
    manifest = build_manifest(
        tenant_id=tenant_id,
        identifier=identifier,
        pack_id=pack_id,
        name=name,
        pack_version=pack_version,
        description=description,
        supported_api_versions=supported_api_versions,
        capabilities=capabilities,
        schema_metadata=schema_metadata,
        created_at=created_at,
        metadata=metadata,
    )
    store.put_domain_pack_manifest(manifest)
    return manifest


def get_manifest(
    store: InMemoryScenarioStore, tenant_id: str, manifest_id: str
) -> DomainPackManifest:
    """Fetch one tenant-owned manifest; raises DomainPackNotFoundError.

    Unknown and foreign manifests raise the same typed error - no tenant
    can observe another tenant's manifests.
    """
    return store.get_domain_pack_manifest(tenant_id, manifest_id)


def list_manifests(store: InMemoryScenarioStore, tenant_id: str) -> tuple[DomainPackManifest, ...]:
    """List a tenant's manifests in deterministic identifier order."""
    return store.list_domain_pack_manifests(tenant_id)
