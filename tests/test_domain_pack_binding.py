"""Tests for the DomainPackBinding contract and the binding service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

import pytest
from kalhas.application.domain_errors import (
    DomainPackBindingAlreadyExistsError,
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    ScenarioNotFoundError,
)
from kalhas.application.domain_pack_binding_service import (
    bind_manifest,
    binding_identifier,
    get_binding,
    list_bindings,
)
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import JsonValue
from pydantic import ValidationError

from tests.test_application_services import build_scenario

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

CAPABILITIES = (
    DomainPackCapability(
        identifier="cap-1",
        description="Declared capability",
        input_ids=("in-1",),
        output_ids=("out-1",),
    ),
    DomainPackCapability(
        identifier="cap-2",
        description="Second declared capability",
        input_ids=(),
        output_ids=("out-2",),
    ),
)


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


def register(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = "tenant-1",
    identifier: str = "manifest-1",
    pack_id: str = "pack-1",
    pack_version: str = "1.2.3",
    capabilities: tuple[DomainPackCapability, ...] = CAPABILITIES,
) -> DomainPackManifest:
    params: Draft = {
        "tenant_id": tenant_id,
        "identifier": identifier,
        "pack_id": pack_id,
        "name": "Reference domain pack",
        "pack_version": pack_version,
        "description": "Declarative pack metadata only",
        "supported_api_versions": ("1",),
        "capabilities": capabilities,
        "schema_metadata": {"declarative": True},
        "created_at": NOW,
        "metadata": {},
    }
    return register_manifest(store, **params)


def bind(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    bound_at: datetime = BOUND_AT,
) -> DomainPackBinding:
    return bind_manifest(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        bound_at=bound_at,
    )


class TestBindingContract:
    def payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "identifier": "binding-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "manifest_id": "manifest-1",
            "pack_id": "pack-1",
            "pack_version": "1.2.3",
            "manifest_content_hash": HASH_64,
            "capability_ids": ["cap-1", "cap-2"],
            "bound_at": BOUND_AT,
        }
        payload.update(overrides)
        return payload

    def test_accepts_valid_payload(self) -> None:
        binding = DomainPackBinding.model_validate(self.payload())
        assert binding.identifier == "binding-1"
        assert binding.tenant_id == "tenant-1"
        assert binding.schema_version == "1.0.0"

    def test_rejects_unknown_fields(self) -> None:
        payload = self.payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            DomainPackBinding.model_validate(payload)

    def test_rejects_malformed_manifest_content_hash(self) -> None:
        for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64, HASH_64.upper()):
            with pytest.raises(ValidationError):
                DomainPackBinding.model_validate(self.payload(manifest_content_hash=bad_hash[:64]))

    def test_rejects_non_semantic_pack_version(self) -> None:
        for bad_version in ("1.0", "1", "1.0.0.0", "v1.2.3", ""):
            with pytest.raises(ValidationError):
                DomainPackBinding.model_validate(self.payload(pack_version=bad_version))

    def test_rejects_duplicate_capability_ids(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackBinding.model_validate(self.payload(capability_ids=["cap-1", "cap-1"]))

    def test_rejects_empty_capability_ids(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackBinding.model_validate(self.payload(capability_ids=[]))

    def test_is_frozen_by_contract(self) -> None:
        binding = DomainPackBinding.model_validate(self.payload())
        with pytest.raises(ValidationError):
            binding.pack_id = "tampered"

    def test_json_round_trip_preserves_capability_order(self) -> None:
        binding = DomainPackBinding.model_validate(self.payload())
        reloaded = DomainPackBinding.model_validate_json(binding.model_dump_json())
        assert reloaded == binding
        assert list(reloaded.capability_ids) == ["cap-1", "cap-2"]


class TestBindingIdentifier:
    def test_is_deterministic_and_prefixed(self) -> None:
        first = binding_identifier(scenario_id="scenario-1", manifest_id="manifest-1")
        second = binding_identifier(scenario_id="scenario-1", manifest_id="manifest-1")
        assert first == second
        assert first.startswith("binding-")
        assert len(first) == len("binding-") + 16

    def test_changes_with_either_identity_input(self) -> None:
        base = binding_identifier(scenario_id="s-1", manifest_id="m-1")
        assert binding_identifier(scenario_id="s-2", manifest_id="m-1") != base
        assert binding_identifier(scenario_id="s-1", manifest_id="m-2") != base


class TestBindService:
    def test_binding_copies_exact_manifest_identity(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        manifest = register(store)
        binding = bind(store)

        assert binding.tenant_id == "tenant-1"
        assert binding.scenario_id == "scenario-1"
        assert binding.manifest_id == manifest.identifier
        assert binding.pack_id == manifest.pack_id
        assert binding.pack_version == manifest.pack_version
        assert binding.manifest_content_hash == manifest.content_hash
        # Capability identifiers are copied from the registered manifest in
        # exact manifest order - there is no client input for them.
        assert list(binding.capability_ids) == ["cap-1", "cap-2"]
        assert binding.bound_at == BOUND_AT

    def test_binding_identifier_matches_deterministic_derivation(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        assert binding.identifier == binding_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1"
        )

    def test_binding_requires_owned_scenario(self) -> None:
        store = InMemoryScenarioStore()
        register(store)
        with pytest.raises(ScenarioNotFoundError):
            bind(store, scenario_id="scenario-ghost")
        with pytest.raises(ScenarioNotFoundError):
            bind(store, tenant_id="tenant-2")

    def test_binding_requires_owned_manifest(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        with pytest.raises(DomainPackNotFoundError):
            bind(store, manifest_id="manifest-ghost")
        register(store, tenant_id="tenant-2")
        with pytest.raises(DomainPackNotFoundError):
            bind(store, tenant_id="tenant-1", manifest_id="manifest-1")

    def test_duplicate_binding_rejected_and_never_overwrites(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        original = bind(store)
        with pytest.raises(DomainPackBindingAlreadyExistsError):
            bind(store, bound_at=datetime(2026, 2, 1, tzinfo=UTC))
        assert store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1") == original

    def test_same_scenario_and_manifest_in_another_tenant_is_allowed(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(tenant_id="tenant-a"))
        store.put_scenario(build_scenario(tenant_id="tenant-b"))
        register(store, tenant_id="tenant-a")
        register(store, tenant_id="tenant-b")
        bind(store, tenant_id="tenant-a")
        bind(store, tenant_id="tenant-b")
        assert len(store.list_domain_pack_bindings("tenant-a", "scenario-1")) == 1
        assert len(store.list_domain_pack_bindings("tenant-b", "scenario-1")) == 1

    def test_get_unknown_or_foreign_binding_raises_typed_404(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(DomainPackBindingNotFoundError):
            get_binding(store, "tenant-1", "scenario-1", "manifest-ghost")
        with pytest.raises(DomainPackBindingNotFoundError):
            get_binding(store, "tenant-2", "scenario-1", "manifest-1")
        assert get_binding(store, "tenant-1", "scenario-1", "manifest-1").pack_id == "pack-1"

    def test_listing_is_sorted_by_manifest_identifier(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        for identifier in ("manifest-z", "manifest-a", "manifest-m"):
            register(store, identifier=identifier, pack_id=f"pack-{identifier}")
        bind(store, manifest_id="manifest-z")
        bind(store, manifest_id="manifest-a")
        bind(store, manifest_id="manifest-m")
        listed = list_bindings(store, "tenant-1", "scenario-1")
        assert [binding.manifest_id for binding in listed] == [
            "manifest-a",
            "manifest-m",
            "manifest-z",
        ]
        assert list_bindings(store, "tenant-1", "scenario-1") == listed

    def test_listing_verifies_scenario_ownership(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(ScenarioNotFoundError):
            list_bindings(store, "tenant-2", "scenario-1")
        with pytest.raises(ScenarioNotFoundError):
            list_bindings(store, "tenant-1", "scenario-ghost")

    def test_store_exposes_no_mutation_surface_for_bindings(self) -> None:
        store = InMemoryScenarioStore()
        for method in (
            "update_domain_pack_binding",
            "delete_domain_pack_binding",
            "replace_domain_pack_binding",
            "unbind_domain_pack",
        ):
            assert not hasattr(store, method)

    def test_bind_does_not_touch_other_store_collections(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        # Binding created no worlds, campaigns, runs, events, replay
        # manifests, or integrity manifests: public lookups all 404.
        from kalhas.application.domain_errors import (
            CampaignNotFoundError,
            RunNotFoundError,
            WorldNotFoundError,
        )

        with pytest.raises(WorldNotFoundError):
            store.get_world("tenant-1", "world-any")
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign("tenant-1", "campaign-any")
        with pytest.raises(RunNotFoundError):
            store.get_run_status("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_run_events("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_input_integrity_manifest("tenant-1", "run-any")
