"""Tests for the DomainStateModel contract, identifiers, hashes, and service.

Phase 11: immutable declarative domain state-model registration. These
tests prove the state model is data only (strict value-kind validation,
no executable content), deterministic (canonical field ordering, stable
identifiers and hashes), tenant-scoped, anchored to verified stored
binding/manifest records, and immutable (duplicates rejected, never
overwritten).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TypedDict

import pytest
from kalhas.application.domain_errors import (
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    DomainStateModelAlreadyExistsError,
    DomainStateModelIntegrityError,
    DomainStateModelNotFoundError,
    ScenarioNotFoundError,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import (
    canonical_state_fields,
    declare_state_model,
    get_state_model,
    list_state_models,
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from pydantic import ValidationError

from tests.test_application_services import build_scenario

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

CAPABILITIES = (
    DomainPackCapability(
        identifier="cap-1",
        description="Declared capability",
        input_ids=("in-a", "in-b"),
        output_ids=("out-1",),
    ),
)


def field(
    identifier: str = "status",
    *,
    value_kind: StateValueKind = StateValueKind.STRING,
    initial_value: JsonValue = "idle",
    allowed_values: tuple[JsonValue, ...] = (),
    description: str = "A declared state field",
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description=description,
        value_kind=value_kind,
        initial_value=initial_value,
        allowed_values=allowed_values,
        metadata=metadata or {},
    )


def default_fields() -> tuple[DomainStateFieldDefinition, ...]:
    return (
        field("status", value_kind=StateValueKind.STRING, initial_value="idle"),
        field("level", value_kind=StateValueKind.INTEGER, initial_value=0),
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
) -> DomainPackManifest:
    params: Draft = {
        "tenant_id": tenant_id,
        "identifier": identifier,
        "pack_id": pack_id,
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ("1",),
        "capabilities": CAPABILITIES,
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
    state_model_id: str = "state-model-1",
    state_fields: tuple[DomainStateFieldDefinition, ...] | None = None,
    declared_at: datetime = DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateModel:
    if state_fields is None:
        state_fields = default_fields()
    return declare_state_model(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
        state_fields=state_fields,
        declared_at=declared_at,
        metadata=metadata,
    )


def prepared_store(
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
) -> InMemoryScenarioStore:
    store = InMemoryScenarioStore()
    store.put_scenario(build_scenario(identifier=scenario_id, tenant_id=tenant_id))
    register(store, tenant_id=tenant_id, identifier=manifest_id)
    bind(store, tenant_id=tenant_id, scenario_id=scenario_id, manifest_id=manifest_id)
    return store


class TestFieldDefinitionContract:
    def test_accepts_every_value_kind(self) -> None:
        cases: tuple[tuple[StateValueKind, JsonValue], ...] = (
            (StateValueKind.STRING, "text"),
            (StateValueKind.INTEGER, 7),
            (StateValueKind.NUMBER, 2.5),
            (StateValueKind.NUMBER, 3),
            (StateValueKind.BOOLEAN, True),
            (StateValueKind.JSON, {"nested": [1, 2, {"x": None}]}),
            (StateValueKind.JSON, True),
            (StateValueKind.JSON, "any json value"),
        )
        for value_kind, initial_value in cases:
            instance = field("f-1", value_kind=value_kind, initial_value=initial_value)
            assert instance.value_kind is value_kind
            assert instance.initial_value == initial_value

    @pytest.mark.parametrize(
        ("value_kind", "bad_value"),
        [
            (StateValueKind.INTEGER, True),
            (StateValueKind.INTEGER, 1.0),
            (StateValueKind.INTEGER, "1"),
            (StateValueKind.NUMBER, True),
            (StateValueKind.STRING, 5),
            (StateValueKind.STRING, False),
            (StateValueKind.BOOLEAN, 1),
            (StateValueKind.BOOLEAN, "true"),
        ],
    )
    def test_initial_value_must_exactly_match_kind(
        self, value_kind: StateValueKind, bad_value: JsonValue
    ) -> None:
        with pytest.raises(ValidationError):
            field("f-1", value_kind=value_kind, initial_value=bad_value)

    @pytest.mark.parametrize(
        ("value_kind", "bad_value"),
        [
            (StateValueKind.INTEGER, True),
            (StateValueKind.NUMBER, True),
            (StateValueKind.STRING, 1),
            (StateValueKind.BOOLEAN, 0),
        ],
    )
    def test_boolean_never_silently_accepted_as_integer_or_number(
        self, value_kind: StateValueKind, bad_value: JsonValue
    ) -> None:
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=value_kind,
                initial_value=bad_value,
            )

    @pytest.mark.parametrize(
        "bad_value",
        [float("nan"), float("inf"), float("-inf")],
    )
    def test_non_finite_numbers_rejected(self, bad_value: float) -> None:
        for kind in (StateValueKind.NUMBER, StateValueKind.JSON):
            with pytest.raises(ValidationError):
                field("f-1", value_kind=kind, initial_value=bad_value)

    @pytest.mark.parametrize(
        "bad_value",
        [
            {"nested": {"value": float("nan")}},
            [1, float("inf")],
            {"list": [1, {"deep": float("-inf")}]},
        ],
    )
    def test_nested_non_finite_json_values_rejected(self, bad_value: JsonValue) -> None:
        with pytest.raises(ValidationError):
            field("f-1", value_kind=StateValueKind.JSON, initial_value=bad_value)

    def test_nested_non_finite_in_allowed_values_rejected(self) -> None:
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=StateValueKind.JSON,
                initial_value={"ok": 1},
                allowed_values=({"ok": 1}, {"bad": float("nan")}),
            )

    def test_valid_nested_json_values_accepted(self) -> None:
        instance = field(
            "f-1",
            value_kind=StateValueKind.JSON,
            initial_value={"a": [1, 2.5, {"b": None, "c": True}]},
        )
        assert instance.initial_value == {"a": [1, 2.5, {"b": None, "c": True}]}

    def test_metadata_rejects_non_finite_values(self) -> None:
        with pytest.raises(ValidationError):
            field("f-1", metadata={"nested": {"x": float("nan")}})
        with pytest.raises(ValidationError):
            field("f-1", metadata={"x": float("inf")})

    def test_allowed_values_must_match_kind(self) -> None:
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=StateValueKind.STRING,
                initial_value="a",
                allowed_values=("a", 1),
            )
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=StateValueKind.INTEGER,
                initial_value=1,
                allowed_values=(1, True),
            )

    def test_allowed_values_must_be_canonically_unique(self) -> None:
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=StateValueKind.STRING,
                initial_value="a",
                allowed_values=("a", "a"),
            )
        # Canonically distinct values (1 vs 1.0) are allowed for number.
        instance = field(
            "f-1",
            value_kind=StateValueKind.NUMBER,
            initial_value=1.0,
            allowed_values=(1, 1.0),
        )
        assert len(instance.allowed_values) == 2

    def test_initial_value_must_be_in_allowed_values(self) -> None:
        with pytest.raises(ValidationError):
            field(
                "f-1",
                value_kind=StateValueKind.STRING,
                initial_value="missing",
                allowed_values=("a", "b"),
            )

    def test_initial_value_in_allowed_is_accepted(self) -> None:
        instance = field(
            "f-1",
            value_kind=StateValueKind.STRING,
            initial_value="b",
            allowed_values=("a", "b"),
        )
        assert instance.initial_value == "b"

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateFieldDefinition.model_validate(
                {
                    "identifier": "f-1",
                    "description": "d",
                    "value_kind": "string",
                    "initial_value": "x",
                    "executable": "print(1)",
                }
            )

    def test_field_is_frozen(self) -> None:
        instance = field("f-1")
        with pytest.raises(ValidationError):
            instance.identifier = "changed"


class TestStateModelContract:
    def test_accepts_valid_payload(self) -> None:
        model = DomainStateModel(
            identifier="state-model-1",
            tenant_id="tenant-1",
            schema_version="1.0.0",
            scenario_id="scenario-1",
            binding_id="binding-1",
            manifest_id="manifest-1",
            pack_id="pack-1",
            pack_version="1.2.3",
            manifest_content_hash=HASH_64,
            state_model_id="sm-1",
            state_fields=default_fields(),
            content_hash=HASH_64,
            declared_at=DECLARED_AT,
            metadata={"label": "reference"},
        )
        assert model.state_model_id == "sm-1"
        assert len(model.state_fields) == 2

    def test_rejects_duplicate_state_field_identifiers(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateModel(
                identifier="state-model-1",
                tenant_id="tenant-1",
                schema_version="1.0.0",
                scenario_id="scenario-1",
                binding_id="binding-1",
                manifest_id="manifest-1",
                pack_id="pack-1",
                pack_version="1.2.3",
                manifest_content_hash=HASH_64,
                state_model_id="sm-1",
                state_fields=(
                    field("dup"),
                    field("dup", initial_value="other"),
                ),
                content_hash=HASH_64,
                declared_at=DECLARED_AT,
            )

    def test_rejects_empty_state_model_id(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateModel(
                identifier="state-model-1",
                tenant_id="tenant-1",
                schema_version="1.0.0",
                scenario_id="scenario-1",
                binding_id="binding-1",
                manifest_id="manifest-1",
                pack_id="pack-1",
                pack_version="1.2.3",
                manifest_content_hash=HASH_64,
                state_model_id="",
                state_fields=default_fields(),
                content_hash=HASH_64,
                declared_at=DECLARED_AT,
            )

    def test_rejects_malformed_hashes_and_pack_version(self) -> None:
        base = dict(
            identifier="state-model-1",
            tenant_id="tenant-1",
            schema_version="1.0.0",
            scenario_id="scenario-1",
            binding_id="binding-1",
            manifest_id="manifest-1",
            pack_id="pack-1",
            pack_version="1.2.3",
            manifest_content_hash=HASH_64,
            state_model_id="sm-1",
            state_fields=default_fields(),
            content_hash=HASH_64,
            declared_at=DECLARED_AT,
        )
        with pytest.raises(ValidationError):
            DomainStateModel.model_validate({**base, "content_hash": "not-a-hash"})
        with pytest.raises(ValidationError):
            DomainStateModel.model_validate({**base, "manifest_content_hash": "x" * 64})
        with pytest.raises(ValidationError):
            DomainStateModel.model_validate({**base, "pack_version": "1.2"})

    def test_rejects_unknown_fields(self) -> None:
        payload = {
            "identifier": "state-model-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "binding_id": "binding-1",
            "manifest_id": "manifest-1",
            "pack_id": "pack-1",
            "pack_version": "1.2.3",
            "manifest_content_hash": HASH_64,
            "state_model_id": "sm-1",
            "state_fields": [f.model_dump(mode="json") for f in default_fields()],
            "content_hash": HASH_64,
            "declared_at": DECLARED_AT,
            "transition_rules": [],
        }
        with pytest.raises(ValidationError):
            DomainStateModel.model_validate(payload)

    def test_is_frozen_by_contract(self) -> None:
        model = DomainStateModel(
            identifier="state-model-1",
            tenant_id="tenant-1",
            schema_version="1.0.0",
            scenario_id="scenario-1",
            binding_id="binding-1",
            manifest_id="manifest-1",
            pack_id="pack-1",
            pack_version="1.2.3",
            manifest_content_hash=HASH_64,
            state_model_id="sm-1",
            state_fields=default_fields(),
            content_hash=HASH_64,
            declared_at=DECLARED_AT,
        )
        with pytest.raises(ValidationError):
            model.state_model_id = "changed"

    def test_json_round_trip_preserves_state_fields(self) -> None:
        model = DomainStateModel(
            identifier="state-model-1",
            tenant_id="tenant-1",
            schema_version="1.0.0",
            scenario_id="scenario-1",
            binding_id="binding-1",
            manifest_id="manifest-1",
            pack_id="pack-1",
            pack_version="1.2.3",
            manifest_content_hash=HASH_64,
            state_model_id="sm-1",
            state_fields=default_fields(),
            content_hash=HASH_64,
            declared_at=DECLARED_AT,
        )
        restored = DomainStateModel.model_validate(
            json.loads(json.dumps(model.model_dump(mode="json")))
        )
        assert restored == model


class TestStateModelIdentifier:
    def test_is_deterministic_and_prefixed(self) -> None:
        first = state_model_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="sm-1"
        )
        second = state_model_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="sm-1"
        )
        assert first == second
        assert first.startswith("state-model-")
        assert len(first) == len("state-model-") + 16

    def test_changes_with_any_identity_input(self) -> None:
        base = dict(scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="sm-1")
        base_id = state_model_identifier(**base)
        assert state_model_identifier(**{**base, "scenario_id": "scenario-2"}) != base_id
        assert state_model_identifier(**{**base, "manifest_id": "manifest-2"}) != base_id
        assert state_model_identifier(**{**base, "state_model_id": "sm-2"}) != base_id


class TestStateModelContentHash:
    def test_is_deterministic(self) -> None:
        store = prepared_store()
        first = declare(store)
        second = declare(store, state_model_id="state-model-2")
        assert first.content_hash == state_model_content_hash(first)
        assert second.content_hash == state_model_content_hash(second)

    def test_excludes_the_content_hash_field_itself(self) -> None:
        store = prepared_store()
        model = declare(store)
        payload = model.model_dump(mode="json")
        del payload["content_hash"]
        expected = sha256_hex(canonical_json(payload))
        assert model.content_hash == expected

    def test_canonical_field_order_yields_identical_model_and_hash(self) -> None:
        """Equivalent caller ordering must produce the same canonical model and hash."""
        store = prepared_store()
        ordered = (field("alpha"), field("beta"))
        reversed_order = (field("beta"), field("alpha"))
        first = declare(store, state_model_id="sm-a", state_fields=ordered)
        second = declare(store, state_model_id="sm-b", state_fields=reversed_order)
        # Identifiers differ (state_model_id differs) but the canonical
        # field representation and content hashes are order-independent.
        assert canonical_state_fields(ordered) == canonical_state_fields(reversed_order)
        assert first.state_fields == second.state_fields
        assert first.state_fields[0].identifier == "alpha"
        # Rebuilding the second model with the canonical fields yields the
        # same content hash the service computed from the reversed input.
        rebuilt = second.model_copy(
            update={
                "state_fields": canonical_state_fields(reversed_order),
                "content_hash": "0" * 64,
            }
        )
        assert state_model_content_hash(rebuilt) == second.content_hash


class TestDeclareService:
    def test_identity_fields_copied_from_stored_records(self) -> None:
        store = prepared_store()
        model = declare(store)
        binding = store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1")
        manifest = store.get_domain_pack_manifest("tenant-1", "manifest-1")
        assert model.scenario_id == "scenario-1"
        assert model.binding_id == binding.identifier
        assert model.manifest_id == manifest.identifier
        assert model.pack_id == manifest.pack_id
        assert model.pack_version == manifest.pack_version
        assert model.manifest_content_hash == manifest.content_hash
        assert model.identifier == state_model_identifier(
            scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="state-model-1"
        )

    def test_requires_owned_scenario(self) -> None:
        store = InMemoryScenarioStore()
        with pytest.raises(ScenarioNotFoundError):
            declare(store)

    def test_requires_binding(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store)

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
        # tenant-a owns scenario-a and has a binding for it. tenant-b owns
        # its OWN scenario-a (same identifier) but has no binding for it.
        # The service verifies tenant-b's scenario ownership first, then
        # fails the binding lookup with the same typed error as a truly
        # missing binding - a foreign binding never leaks tenant-a data.
        store = prepared_store(tenant_id="tenant-a", scenario_id="scenario-a")
        store.put_scenario(build_scenario(identifier="scenario-a", tenant_id="tenant-b"))
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, tenant_id="tenant-b", scenario_id="scenario-a")

    def test_binding_snapshot_inconsistency_rejected_safely(self) -> None:
        store = prepared_store()
        tampered = store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1").model_copy(
            update={"pack_id": "pack-tampered"}
        )
        # The store deliberately has no overwrite surface for immutable
        # contracts, so the tampered snapshot is injected directly.
        store._domain_pack_bindings[("tenant-1", "scenario-1", "manifest-1")] = tampered
        with pytest.raises(DomainStateModelIntegrityError) as exc_info:
            declare(store)
        message = str(exc_info.value)
        assert "pack-tampered" not in message
        assert "manifest-1" in message
        assert "0" * 64 not in message
        assert exc_info.value.reason == "pack_id mismatch"

    def test_duplicate_declaration_rejected_and_never_overwrites(self) -> None:
        store = prepared_store()
        first = declare(store)
        with pytest.raises(DomainStateModelAlreadyExistsError):
            declare(store, state_fields=(field("status"),))
        assert (
            store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "state-model-1")
            == first
        )

    def test_same_identities_in_another_tenant_are_allowed(self) -> None:
        store = prepared_store(tenant_id="tenant-a", scenario_id="scenario-a")
        declare(store, tenant_id="tenant-a", scenario_id="scenario-a")
        # tenant-b has its own scenario, manifest, and binding with the
        # same identifiers - an independent immutable state model.
        store.put_scenario(build_scenario(identifier="scenario-a", tenant_id="tenant-b"))
        register(store, tenant_id="tenant-b")
        bind(store, tenant_id="tenant-b", scenario_id="scenario-a")
        model_b = declare(store, tenant_id="tenant-b", scenario_id="scenario-a")
        assert model_b.tenant_id == "tenant-b"
        assert len(store.list_domain_state_models("tenant-a", "scenario-a")) == 1

    def test_get_unknown_or_foreign_raises_typed_404(self) -> None:
        store = prepared_store()
        declare(store)
        with pytest.raises(DomainStateModelNotFoundError):
            get_state_model(store, "tenant-1", "scenario-1", "manifest-1", "ghost")
        with pytest.raises(DomainStateModelNotFoundError):
            get_state_model(store, "tenant-other", "scenario-1", "manifest-1", "state-model-1")

    def test_listing_is_sorted_by_manifest_then_state_model(self) -> None:
        store = prepared_store()
        declare(store, state_model_id="sm-b")
        # Bind a second manifest and declare under it.
        register(store, identifier="manifest-2", pack_id="pack-2")
        bind(store, manifest_id="manifest-2")
        declare(store, manifest_id="manifest-2", state_model_id="sm-a")
        listing = list_state_models(store, "tenant-1", "scenario-1")
        assert [(m.manifest_id, m.state_model_id) for m in listing] == [
            ("manifest-1", "sm-b"),
            ("manifest-2", "sm-a"),
        ]

    def test_listing_verifies_scenario_ownership(self) -> None:
        store = prepared_store()
        declare(store)
        with pytest.raises(ScenarioNotFoundError):
            list_state_models(store, "tenant-other", "scenario-1")

    def test_state_model_never_executed_or_interpreted(self) -> None:
        store = prepared_store()
        model = declare(store)
        # The service returns the stored immutable contract untouched: no
        # derived values, no outcomes, no evidence, no evaluation results.
        assert model == store.get_domain_state_model(
            "tenant-1", "scenario-1", "manifest-1", "state-model-1"
        )
        assert len(model.state_fields) == 2
        assert model.metadata == {}
