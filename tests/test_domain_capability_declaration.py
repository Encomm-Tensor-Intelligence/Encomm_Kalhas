"""Tests for the DomainCapabilityDeclaration contract and declaration service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict, cast

import pytest
from kalhas.application.domain_capability_declaration_service import (
    declaration_content_hash,
    declaration_identifier,
    declare_capability_inputs,
    get_declaration,
    list_declarations,
)
from kalhas.application.domain_errors import (
    DomainCapabilityDeclarationAlreadyExistsError,
    DomainCapabilityDeclarationIntegrityError,
    DomainCapabilityDeclarationNotFoundError,
    DomainCapabilityInputKeyMismatchError,
    DomainCapabilityNotFoundError,
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    ScenarioNotFoundError,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_compiler import compile_world, content_hash
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import JsonValue
from pydantic import ValidationError

from tests.test_application_services import build_scenario

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

# cap-1 declares two ordered inputs; cap-2 declares zero inputs.
CAPABILITIES = (
    DomainPackCapability(
        identifier="cap-1",
        description="Declared capability",
        input_ids=("in-a", "in-b"),
        output_ids=("out-1",),
    ),
    DomainPackCapability(
        identifier="cap-2",
        description="Zero-input declared capability",
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
    capabilities: tuple[DomainPackCapability, ...] = CAPABILITIES,
) -> DomainPackManifest:
    params: Draft = {
        "tenant_id": tenant_id,
        "identifier": identifier,
        "pack_id": pack_id,
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
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
) -> DomainPackBinding:
    return bind_manifest(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        bound_at=BOUND_AT,
    )


def declare(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    capability_id: str = "cap-1",
    input_values: dict[str, JsonValue] | None = None,
    declared_at: datetime = DECLARED_AT,
) -> DomainCapabilityDeclaration:
    if input_values is None:
        input_values = {"in-a": "value-a", "in-b": 42}
    return declare_capability_inputs(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        capability_id=capability_id,
        input_values=input_values,
        declared_at=declared_at,
    )


class TestDeclarationContract:
    def payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "identifier": "declaration-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "binding_id": "binding-1",
            "manifest_id": "manifest-1",
            "pack_id": "pack-1",
            "pack_version": "1.2.3",
            "manifest_content_hash": HASH_64,
            "capability_id": "cap-1",
            "input_values": {"in-a": "value-a", "in-b": 42},
            "content_hash": HASH_64,
            "declared_at": DECLARED_AT,
        }
        payload.update(overrides)
        return payload

    def test_accepts_valid_payload(self) -> None:
        declaration = DomainCapabilityDeclaration.model_validate(self.payload())
        assert declaration.identifier == "declaration-1"
        assert declaration.tenant_id == "tenant-1"
        assert declaration.schema_version == "1.0.0"
        assert declaration.input_values == {"in-a": "value-a", "in-b": 42}

    def test_rejects_unknown_fields(self) -> None:
        payload = self.payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            DomainCapabilityDeclaration.model_validate(payload)

    def test_rejects_malformed_hashes(self) -> None:
        for field in ("manifest_content_hash", "content_hash"):
            for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64, HASH_64.upper()):
                with pytest.raises(ValidationError):
                    DomainCapabilityDeclaration.model_validate(
                        self.payload(**{field: bad_hash[:64]})
                    )

    def test_rejects_non_semantic_pack_version(self) -> None:
        for bad_version in ("1.0", "1", "1.0.0.0", "v1.2.3", ""):
            with pytest.raises(ValidationError):
                DomainCapabilityDeclaration.model_validate(self.payload(pack_version=bad_version))

    def test_is_frozen_by_contract(self) -> None:
        declaration = DomainCapabilityDeclaration.model_validate(self.payload())
        with pytest.raises(ValidationError):
            declaration.input_values = {"tampered": 1}

    def test_json_round_trip_preserves_input_values(self) -> None:
        declaration = DomainCapabilityDeclaration.model_validate(self.payload())
        reloaded = DomainCapabilityDeclaration.model_validate_json(declaration.model_dump_json())
        assert reloaded == declaration
        assert reloaded.input_values == {"in-a": "value-a", "in-b": 42}


class TestDeclarationIdentifier:
    def test_is_deterministic_and_prefixed(self) -> None:
        first = declaration_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", capability_id="cap-1"
        )
        second = declaration_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", capability_id="cap-1"
        )
        assert first == second
        assert first.startswith("declaration-")
        assert len(first) == len("declaration-") + 16

    def test_changes_with_any_identity_input(self) -> None:
        base = declaration_identifier(scenario_id="s-1", manifest_id="m-1", capability_id="c-1")
        assert (
            declaration_identifier(scenario_id="s-2", manifest_id="m-1", capability_id="c-1")
            != base
        )
        assert (
            declaration_identifier(scenario_id="s-1", manifest_id="m-2", capability_id="c-1")
            != base
        )
        assert (
            declaration_identifier(scenario_id="s-1", manifest_id="m-1", capability_id="c-2")
            != base
        )


class TestDeclarationContentHash:
    def test_is_deterministic(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        first = declare(store)
        second = declare_capability_inputs(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            capability_id="cap-2",
            input_values={},
            declared_at=DECLARED_AT,
        )
        assert declaration_content_hash(first) == first.content_hash
        assert declaration_content_hash(second) == second.content_hash

    def test_excludes_the_content_hash_field_itself(self) -> None:
        declaration = DomainCapabilityDeclaration.model_validate(
            TestDeclarationContract().payload()
        )
        # Two snapshots identical except for the content_hash value must
        # compute the same digest: the hash field never feeds itself.
        other = declaration.model_copy(update={"content_hash": "f" * 64})
        assert declaration_content_hash(declaration) == declaration_content_hash(other)
        assert re_full_match(declaration_content_hash(declaration))


def re_full_match(value: str) -> bool:
    """Return True when the value is a lowercase 64-character hex digest."""
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


class TestDeclareService:
    def test_identity_fields_copied_from_stored_records(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        manifest = register(store)
        binding = bind(store)
        declaration = declare(store)

        assert declaration.tenant_id == "tenant-1"
        assert declaration.scenario_id == "scenario-1"
        assert declaration.binding_id == binding.identifier
        assert declaration.manifest_id == manifest.identifier
        assert declaration.pack_id == manifest.pack_id
        assert declaration.pack_version == manifest.pack_version
        assert declaration.manifest_content_hash == manifest.content_hash
        assert declaration.capability_id == "cap-1"
        assert declaration.input_values == {"in-a": "value-a", "in-b": 42}
        assert declaration.declared_at == DECLARED_AT

    def test_identifier_matches_deterministic_derivation(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declaration = declare(store)
        assert declaration.identifier == declaration_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", capability_id="cap-1"
        )

    def test_requires_owned_scenario(self) -> None:
        store = InMemoryScenarioStore()
        register(store)
        with pytest.raises(ScenarioNotFoundError):
            declare(store, scenario_id="scenario-ghost")
        with pytest.raises(ScenarioNotFoundError):
            declare(store, tenant_id="tenant-2")

    def test_requires_binding(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, manifest_id="manifest-1")
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, manifest_id="manifest-ghost")

    def test_requires_owned_manifest(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        # A stored binding always implies an owned manifest through the
        # public API (bind requires the manifest). The manifest-missing
        # path is defense-in-depth: construct a binding directly so the
        # declared manifest has no registered record.
        store.put_domain_pack_binding(
            DomainPackBinding(
                identifier="binding-x",
                tenant_id="tenant-1",
                scenario_id="scenario-1",
                manifest_id="manifest-ghost",
                pack_id="pack-x",
                pack_version="1.2.3",
                manifest_content_hash=HASH_64,
                capability_ids=("cap-1",),
                bound_at=BOUND_AT,
            )
        )
        with pytest.raises(DomainPackNotFoundError):
            declare(store, manifest_id="manifest-ghost")

    def test_foreign_binding_is_indistinguishable_from_unknown(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(tenant_id="tenant-1"))
        store.put_scenario(build_scenario(tenant_id="tenant-2"))
        register(store, tenant_id="tenant-1")
        bind(store, tenant_id="tenant-1")
        # tenant-2 owns the scenario but not the binding: typed 404.
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, tenant_id="tenant-2", manifest_id="manifest-1")

    def test_missing_input_keys_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(DomainCapabilityInputKeyMismatchError) as exc_info:
            declare(store, input_values={"in-a": "value-a"})
        assert exc_info.value.missing == ("in-b",)
        assert exc_info.value.extra == ()

    def test_extra_input_keys_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(DomainCapabilityInputKeyMismatchError) as exc_info:
            declare(store, input_values={"in-a": "value-a", "in-b": 1, "in-extra": 2})
        assert exc_info.value.missing == ()
        assert exc_info.value.extra == ("in-extra",)

    def test_zero_input_capability_accepts_only_empty_values(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declaration = declare(store, capability_id="cap-2", input_values={})
        assert declaration.input_values == {}
        with pytest.raises(DomainCapabilityInputKeyMismatchError):
            declare(store, capability_id="cap-2", input_values={"in-extra": 1})

    def test_unknown_capability_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(DomainCapabilityNotFoundError):
            declare(store, capability_id="cap-ghost")

    def test_binding_snapshot_inconsistency_rejected_safely(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        # The store deliberately has no overwrite surface for bindings, so
        # a divergent snapshot cannot arise through the public API; the
        # integrity check is defense-in-depth. Simulate the divergence by
        # writing a tampered binding directly into the collection.
        tampered = binding.model_copy(update={"pack_id": "pack-tampered"})
        binding_key = (binding.tenant_id, binding.scenario_id, binding.manifest_id)
        store._domain_pack_bindings[binding_key] = tampered
        with pytest.raises(DomainCapabilityDeclarationIntegrityError) as exc_info:
            declare(store)
        message = str(exc_info.value)
        assert "pack-tampered" not in message
        assert "pack-1" not in message
        assert tampered.manifest_content_hash not in message
        assert exc_info.value.reason == "pack_id mismatch"

    def test_duplicate_declaration_rejected_and_never_overwrites(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        original = declare(store)
        with pytest.raises(DomainCapabilityDeclarationAlreadyExistsError):
            declare(store, declared_at=datetime(2026, 2, 1, tzinfo=UTC))
        assert (
            store.get_domain_capability_declaration("tenant-1", "scenario-1", "manifest-1", "cap-1")
            == original
        )

    def test_same_identities_in_another_tenant_are_allowed(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(tenant_id="tenant-a"))
        store.put_scenario(build_scenario(tenant_id="tenant-b"))
        register(store, tenant_id="tenant-a")
        register(store, tenant_id="tenant-b")
        bind(store, tenant_id="tenant-a")
        bind(store, tenant_id="tenant-b")
        declare(store, tenant_id="tenant-a")
        declare(store, tenant_id="tenant-b")
        assert len(store.list_domain_capability_declarations("tenant-a", "scenario-1")) == 1
        assert len(store.list_domain_capability_declarations("tenant-b", "scenario-1")) == 1

    def test_get_unknown_or_foreign_raises_typed_404(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declare(store)
        with pytest.raises(DomainCapabilityDeclarationNotFoundError):
            get_declaration(store, "tenant-1", "scenario-1", "manifest-1", "cap-ghost")
        with pytest.raises(DomainCapabilityDeclarationNotFoundError):
            get_declaration(store, "tenant-2", "scenario-1", "manifest-1", "cap-1")
        assert (
            get_declaration(store, "tenant-1", "scenario-1", "manifest-1", "cap-1").pack_id
            == "pack-1"
        )

    def test_listing_is_sorted_by_manifest_then_capability(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store, identifier="manifest-z", pack_id="pack-z")
        register(store, identifier="manifest-a", pack_id="pack-a")
        bind(store, manifest_id="manifest-z")
        bind(store, manifest_id="manifest-a")
        # Declare in deliberately shuffled order.
        declare(store, manifest_id="manifest-z", capability_id="cap-2", input_values={})
        declare(store, manifest_id="manifest-a", capability_id="cap-1")
        declare(store, manifest_id="manifest-z", capability_id="cap-1")
        declare(store, manifest_id="manifest-a", capability_id="cap-2", input_values={})
        listed = list_declarations(store, "tenant-1", "scenario-1")
        assert [(d.manifest_id, d.capability_id) for d in listed] == [
            ("manifest-a", "cap-1"),
            ("manifest-a", "cap-2"),
            ("manifest-z", "cap-1"),
            ("manifest-z", "cap-2"),
        ]
        assert list_declarations(store, "tenant-1", "scenario-1") == listed

    def test_listing_verifies_scenario_ownership(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declare(store)
        with pytest.raises(ScenarioNotFoundError):
            list_declarations(store, "tenant-2", "scenario-1")
        with pytest.raises(ScenarioNotFoundError):
            list_declarations(store, "tenant-1", "scenario-ghost")

    def test_store_exposes_no_mutation_surface_for_declarations(self) -> None:
        store = InMemoryScenarioStore()
        for method in (
            "update_domain_capability_declaration",
            "delete_domain_capability_declaration",
            "replace_domain_capability_declaration",
        ):
            assert not hasattr(store, method)

    def test_declare_does_not_touch_other_store_collections(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declare(store)
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


class TestBindingIntegrityHardening:
    """Corrupted stored records must be rejected safely with no mutation.

    The store deliberately has no overwrite surface for bindings or
    manifests, so divergences cannot arise through the public API; the
    integrity checks are defense-in-depth. Each test simulates a
    divergence by writing a tampered record directly into the collection,
    then proves the declaration is rejected and nothing was created.
    """

    def _tamper_binding(
        self, store: InMemoryScenarioStore, binding: DomainPackBinding, **updates: object
    ) -> None:
        tampered = binding.model_copy(update=updates)
        key = (binding.tenant_id, binding.scenario_id, binding.manifest_id)
        store._domain_pack_bindings[key] = tampered

    def _tamper_manifest(
        self, store: InMemoryScenarioStore, manifest: DomainPackManifest, **updates: object
    ) -> None:
        tampered = manifest.model_copy(update=updates)
        key = (manifest.tenant_id, manifest.identifier)
        store._domain_pack_manifests[key] = tampered

    def _assert_rejected_with_no_mutation(
        self, store: InMemoryScenarioStore, expected_reason: str
    ) -> None:
        with pytest.raises(DomainCapabilityDeclarationIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == expected_reason
        # No declaration and no world were created.
        from kalhas.application.domain_errors import WorldNotFoundError

        with pytest.raises(DomainCapabilityDeclarationNotFoundError):
            store.get_domain_capability_declaration("tenant-1", "scenario-1", "manifest-1", "cap-1")
        with pytest.raises(WorldNotFoundError):
            store.get_world("tenant-1", "world-any")

    def test_corrupted_binding_tenant_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        self._tamper_binding(store, binding, tenant_id="tenant-9")
        self._assert_rejected_with_no_mutation(store, "binding tenant mismatch")

    def test_corrupted_binding_scenario_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        self._tamper_binding(store, binding, scenario_id="scenario-9")
        self._assert_rejected_with_no_mutation(store, "binding scenario mismatch")

    def test_corrupted_binding_manifest_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        self._tamper_binding(store, binding, manifest_id="manifest-9")
        self._assert_rejected_with_no_mutation(store, "binding manifest mismatch")

    def test_corrupted_binding_identifier_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        self._tamper_binding(store, binding, identifier="binding-wrong")
        self._assert_rejected_with_no_mutation(store, "binding identifier mismatch")

    def test_corrupted_manifest_tenant_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        manifest = register(store)
        bind(store)
        self._tamper_manifest(store, manifest, tenant_id="tenant-9")
        self._assert_rejected_with_no_mutation(store, "manifest tenant mismatch")

    def test_corrupted_binding_pack_id_is_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        binding = bind(store)
        self._tamper_binding(store, binding, pack_id="pack-tampered")
        self._assert_rejected_with_no_mutation(store, "pack_id mismatch")


class TestWorldCompilerDeclarations:
    def test_declaration_free_compile_is_unchanged(self) -> None:
        scenario = build_scenario()
        assert content_hash(scenario) == content_hash(scenario, declarations=())
        assert compile_world(scenario).version.content_hash == content_hash(scenario)
        world = compile_world(scenario).version
        assert "domain_capability_declarations" not in world.world
        assert (
            "declared_domain_capability_declaration_count"
            not in compile_world(scenario).manifest.state
        )

    def test_declarations_create_distinct_hash_and_immutable_snapshot(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        declaration = declare(store)
        scenario = build_scenario()
        plain = compile_world(scenario)
        compiled = compile_world(scenario, declarations=(declaration,))
        assert plain.version.content_hash != compiled.version.content_hash
        assert plain.version.identifier != compiled.version.identifier
        assert compiled.version.world["domain_capability_declarations"] == [
            declaration.model_dump(mode="json")
        ]
        assert compiled.manifest.state["declared_domain_capability_declaration_count"] == 1
        # Declarations are embedded in deterministic manifest-id then
        # capability-id order when supplied sorted (store listing order).
        assert content_hash(scenario, declarations=(declaration,)) == compiled.version.content_hash


class TestCompilerCanonicalOrdering:
    """The compiler canonicalizes snapshot order itself: caller-supplied
    tuple order never affects the compiled world, its content hash, or the
    manifest counts. Already correctly ordered inputs sort to the same
    order, so established hashes are unchanged (covered by the API tests)."""

    def _declarations(self) -> tuple[DomainCapabilityDeclaration, ...]:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store, identifier="manifest-a", pack_id="pack-a")
        register(store, identifier="manifest-z", pack_id="pack-z")
        bind(store, manifest_id="manifest-a")
        bind(store, manifest_id="manifest-z")
        return (
            declare(store, manifest_id="manifest-a", capability_id="cap-1"),
            declare(store, manifest_id="manifest-a", capability_id="cap-2", input_values={}),
            declare(store, manifest_id="manifest-z", capability_id="cap-1"),
            declare(store, manifest_id="manifest-z", capability_id="cap-2", input_values={}),
        )

    def test_reversed_declaration_tuples_compile_identically(self) -> None:
        scenario = build_scenario()
        forward = self._declarations()
        backward = tuple(reversed(forward))
        first = compile_world(scenario, declarations=forward)
        second = compile_world(scenario, declarations=backward)

        assert first.version.content_hash == second.version.content_hash
        assert first.version.world == second.version.world
        assert first.manifest == second.manifest
        assert content_hash(scenario, declarations=forward) == content_hash(
            scenario, declarations=backward
        )
        # Serialized snapshots appear in canonical (manifest_id, capability_id) order.
        snapshots = cast(
            list[dict[str, object]], first.version.world["domain_capability_declarations"]
        )
        assert [(d["manifest_id"], d["capability_id"]) for d in snapshots] == [
            ("manifest-a", "cap-1"),
            ("manifest-a", "cap-2"),
            ("manifest-z", "cap-1"),
            ("manifest-z", "cap-2"),
        ]
        assert first.manifest.state["declared_domain_capability_declaration_count"] == 4

    def test_reversed_binding_tuples_compile_identically(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store, identifier="manifest-a", pack_id="pack-a")
        register(store, identifier="manifest-z", pack_id="pack-z")
        binding_a = bind(store, manifest_id="manifest-a")
        binding_z = bind(store, manifest_id="manifest-z")
        scenario = build_scenario()

        first = compile_world(scenario, bindings=(binding_a, binding_z))
        second = compile_world(scenario, bindings=(binding_z, binding_a))

        assert first.version.content_hash == second.version.content_hash
        assert first.version.world == second.version.world
        assert first.manifest == second.manifest
        assert content_hash(scenario, bindings=(binding_a, binding_z)) == content_hash(
            scenario, bindings=(binding_z, binding_a)
        )
        snapshots = cast(list[dict[str, object]], first.version.world["domain_pack_bindings"])
        assert [b["manifest_id"] for b in snapshots] == ["manifest-a", "manifest-z"]
        assert first.manifest.state["declared_domain_pack_binding_count"] == 2

    def test_reversed_binding_and_declaration_tuples_compile_identically(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store, identifier="manifest-a", pack_id="pack-a")
        register(store, identifier="manifest-z", pack_id="pack-z")
        binding_a = bind(store, manifest_id="manifest-a")
        binding_z = bind(store, manifest_id="manifest-z")
        declaration_a = declare(store, manifest_id="manifest-a", capability_id="cap-1")
        declaration_z = declare(store, manifest_id="manifest-z", capability_id="cap-1")
        scenario = build_scenario()

        forward = compile_world(
            scenario,
            bindings=(binding_a, binding_z),
            declarations=(declaration_a, declaration_z),
        )
        backward = compile_world(
            scenario,
            bindings=(binding_z, binding_a),
            declarations=(declaration_z, declaration_a),
        )
        assert forward.version.content_hash == backward.version.content_hash
        assert forward.version.world == backward.version.world
        assert forward.manifest == backward.manifest
