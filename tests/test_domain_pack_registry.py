"""Application-layer tests for the domain pack registry service and storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

import pytest
from kalhas.application.domain_errors import (
    DomainPackAlreadyExistsError,
    DomainPackNotFoundError,
)
from kalhas.application.domain_pack_registry import (
    build_manifest,
    get_manifest,
    list_manifests,
    manifest_content_hash,
    register_manifest,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.shared import JsonValue

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

CAPABILITY = DomainPackCapability(
    identifier="cap-1",
    description="Declared capability",
    input_ids=("in-1", "in-2"),
    output_ids=("out-1",),
    metadata={"declared": True},
)

SCHEMA_METADATA: dict[str, JsonValue] = {"declarative": True}
METADATA: dict[str, JsonValue] = {"owner": "foundation"}


class Draft(TypedDict):
    tenant_id: str
    identifier: str
    pack_id: str
    name: str
    pack_version: str
    description: str | None
    supported_api_versions: tuple[str, ...]
    capabilities: tuple[DomainPackCapability, ...]
    schema_metadata: dict[str, JsonValue]
    created_at: datetime
    metadata: dict[str, JsonValue]


def build(
    store: InMemoryScenarioStore | None = None,
    *,
    tenant_id: str = "tenant-1",
    identifier: str = "manifest-1",
    pack_version: str = "1.2.3",
) -> DomainPackManifest:
    """Build a manifest (or register it, when a store is given)."""
    params: Draft = {
        "tenant_id": tenant_id,
        "identifier": identifier,
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": pack_version,
        "description": "Declarative pack metadata only",
        "supported_api_versions": ("1",),
        "capabilities": (CAPABILITY,),
        "schema_metadata": SCHEMA_METADATA,
        "created_at": NOW,
        "metadata": METADATA,
    }
    if store is None:
        return build_manifest(**params)
    return register_manifest(store, **params)


class TestManifestConstruction:
    def test_register_computes_authoritative_content_hash(self) -> None:
        store = InMemoryScenarioStore()
        manifest = build(store)
        assert manifest.content_hash != "0" * 64
        # The stored hash is exactly the canonical hash of the manifest
        # content excluding content_hash itself.
        assert manifest.content_hash == manifest_content_hash(manifest)
        assert len(manifest.content_hash) == 64
        assert manifest.content_hash == manifest.content_hash.lower()

    def test_equivalent_drafts_produce_identical_content_hash(self) -> None:
        assert build().content_hash == build().content_hash

    def test_hash_covers_tenant_schema_version_and_every_manifest_field(self) -> None:
        """The canonical hash input equals the manifest content sans hash."""
        from kalhas.application.hashing import canonical_json, sha256_hex

        manifest = build()
        payload = manifest.model_dump(mode="json")
        payload.pop("content_hash", None)
        assert manifest.content_hash == sha256_hex(canonical_json(payload))

    def test_created_at_is_derived_from_draft_not_wall_clock(self) -> None:
        assert build().created_at == NOW

    def test_same_draft_in_different_tenants_hashes_differently(self) -> None:
        store = InMemoryScenarioStore()
        tenant_a = build(store, tenant_id="tenant-a")
        tenant_b = build(store, tenant_id="tenant-b")
        assert tenant_a.content_hash != tenant_b.content_hash


class TestRegistration:
    def test_duplicate_registration_is_rejected_per_tenant(self) -> None:
        store = InMemoryScenarioStore()
        build(store)
        with pytest.raises(DomainPackAlreadyExistsError):
            build(store)

    def test_duplicate_rejection_never_overwrites_stored_manifest(self) -> None:
        store = InMemoryScenarioStore()
        original = build(store)
        with pytest.raises(DomainPackAlreadyExistsError):
            build(store)
        assert store.get_domain_pack_manifest("tenant-1", "manifest-1") == original

    def test_same_identifier_in_different_tenant_is_allowed(self) -> None:
        store = InMemoryScenarioStore()
        build(store, tenant_id="tenant-a")
        build(store, tenant_id="tenant-b")
        assert len(store.list_domain_pack_manifests("tenant-a")) == 1
        assert len(store.list_domain_pack_manifests("tenant-b")) == 1

    def test_store_exposes_no_mutation_surface_for_manifests(self) -> None:
        store = InMemoryScenarioStore()
        assert not hasattr(store, "update_domain_pack_manifest")
        assert not hasattr(store, "delete_domain_pack_manifest")
        assert not hasattr(store, "replace_domain_pack_manifest")


class TestLookup:
    def test_get_unknown_manifest_raises_typed_404(self) -> None:
        store = InMemoryScenarioStore()
        with pytest.raises(DomainPackNotFoundError):
            get_manifest(store, "tenant-1", "manifest-ghost")

    def test_get_foreign_manifest_raises_typed_404(self) -> None:
        store = InMemoryScenarioStore()
        build(store, tenant_id="tenant-a")
        with pytest.raises(DomainPackNotFoundError):
            get_manifest(store, "tenant-b", "manifest-1")

    def test_get_returns_registered_manifest(self) -> None:
        store = InMemoryScenarioStore()
        registered = build(store)
        assert get_manifest(store, "tenant-1", "manifest-1") == registered


class TestListing:
    def test_listing_is_sorted_by_manifest_identifier(self) -> None:
        store = InMemoryScenarioStore()
        for identifier in ("manifest-z", "manifest-a", "manifest-m"):
            build(store, identifier=identifier)
        listed = list_manifests(store, "tenant-1")
        assert [manifest.identifier for manifest in listed] == [
            "manifest-a",
            "manifest-m",
            "manifest-z",
        ]
        # Re-listing is stable.
        assert list_manifests(store, "tenant-1") == listed

    def test_listing_is_tenant_isolated(self) -> None:
        store = InMemoryScenarioStore()
        build(store, tenant_id="tenant-a")
        build(store, tenant_id="tenant-b", identifier="manifest-other")
        assert list_manifests(store, "tenant-a") == (
            store.get_domain_pack_manifest("tenant-a", "manifest-1"),
        )
        assert [manifest.identifier for manifest in list_manifests(store, "tenant-b")] == [
            "manifest-other"
        ]
        assert list_manifests(store, "tenant-c") == ()
