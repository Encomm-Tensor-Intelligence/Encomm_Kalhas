"""Tests for the DomainStateTransition contract, identifiers, hashes, and service.

Phase 12: immutable declarative state-transition specifications. These
tests prove the transition is data only (declarative guard/target values,
strict value-kind and allowed-values enforcement, nested non-finite
rejection, no executable content), deterministic (canonical mapping
ordering, stable identifiers and hashes), tenant-scoped, anchored to
verified stored binding/manifest/state-model records (tampered records
raise safe typed integrity errors), and immutable (duplicates rejected,
never overwritten). Guards are never evaluated and targets are never
applied.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TypedDict

import pytest
from kalhas.application.domain_errors import (
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    DomainStateModelNotFoundError,
    DomainStateTransitionAlreadyExistsError,
    DomainStateTransitionIntegrityError,
    DomainStateTransitionNotFoundError,
    DomainStateTransitionValuesError,
    ScenarioNotFoundError,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import (
    declare_state_model,
    state_model_content_hash,
)
from kalhas.application.domain_state_transition_service import (
    canonical_value_mappings,
    declare_transition,
    get_transition,
    list_transitions,
    transition_content_hash,
    transition_identifier,
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
from kalhas.contracts.v1.transition import DomainStateTransition
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
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description=description,
        value_kind=value_kind,
        initial_value=initial_value,
        allowed_values=allowed_values,
    )


def default_fields() -> tuple[DomainStateFieldDefinition, ...]:
    return (
        field("status", value_kind=StateValueKind.STRING, initial_value="idle"),
        field("level", value_kind=StateValueKind.INTEGER, initial_value=0),
        field("flag", value_kind=StateValueKind.BOOLEAN, initial_value=False),
        field(
            "extra",
            value_kind=StateValueKind.JSON,
            initial_value={"nested": [1, None]},
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


def declare_model(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    state_model_id: str = "sm-1",
    state_fields: tuple[DomainStateFieldDefinition, ...] | None = None,
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
        declared_at=DECLARED_AT,
    )


def declare(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    state_model_id: str = "sm-1",
    transition_id: str = "t-1",
    description: str = "A possible state change",
    guard_values: dict[str, JsonValue] | None = None,
    target_values: dict[str, JsonValue] | None = None,
    declared_at: datetime = DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainStateTransition:
    if guard_values is None:
        guard_values = {"level": 0, "flag": False}
    if target_values is None:
        target_values = {"status": "active", "level": 1}
    return declare_transition(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
        transition_id=transition_id,
        description=description,
        guard_values=guard_values,
        target_values=target_values,
        declared_at=declared_at,
        metadata=metadata,
    )


def prepared_store(
    *,
    tenant_id: str = "tenant-1",
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    state_model_id: str = "sm-1",
) -> InMemoryScenarioStore:
    store = InMemoryScenarioStore()
    store.put_scenario(build_scenario(identifier=scenario_id, tenant_id=tenant_id))
    register(store, tenant_id=tenant_id, identifier=manifest_id)
    bind(store, tenant_id=tenant_id, scenario_id=scenario_id, manifest_id=manifest_id)
    declare_model(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
    )
    return store


def transition_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "transition-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "transition_id": "t-1",
        "description": "A possible state change",
        "guard_values": {"level": 0},
        "target_values": {"status": "active"},
        "content_hash": HASH_64,
        "declared_at": DECLARED_AT,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


class TestTransitionContract:
    def test_accepts_valid_payload(self) -> None:
        transition = DomainStateTransition.model_validate(
            transition_payload(
                guard_values={"level": 0, "flag": False, "extra": {"k": [1, None]}},
                target_values={
                    "status": "active",
                    "level": 3,
                    "flag": True,
                    "extra": {"nested": [2]},
                },
            )
        )
        assert transition.transition_id == "t-1"
        assert transition.target_values["status"] == "active"

    def test_rejects_empty_transition_id(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(transition_id=""))

    def test_rejects_empty_target_values(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(target_values={}))

    def test_accepts_empty_guard_values(self) -> None:
        transition = DomainStateTransition.model_validate(transition_payload(guard_values={}))
        assert transition.guard_values == {}

    def test_rejects_unknown_fields(self) -> None:
        payload = transition_payload()
        payload["evaluator"] = "print(1)"
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(payload)

    def test_rejects_malformed_hashes_and_pack_version(self) -> None:
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(content_hash="not-a-hash"))
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(manifest_content_hash="x" * 64))
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(
                transition_payload(state_model_content_hash="x" * 64)
            )
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(pack_version="1.2"))

    @pytest.mark.parametrize(
        ("mapping_key", "bad_value"),
        [
            ("guard_values", {"status": {"nested": {"x": float("nan")}}}),
            ("target_values", {"extra": [1, float("inf")]}),
            ("guard_values", {"extra": {"deep": [float("-inf")]}}),
            ("target_values", {"extra": float("nan")}),
            ("metadata", {"nested": {"x": float("inf")}}),
        ],
    )
    def test_nested_non_finite_values_rejected(
        self, mapping_key: str, bad_value: JsonValue
    ) -> None:
        with pytest.raises(ValidationError):
            DomainStateTransition.model_validate(transition_payload(**{mapping_key: bad_value}))

    def test_is_frozen_by_contract(self) -> None:
        transition = DomainStateTransition.model_validate(transition_payload())
        with pytest.raises(ValidationError):
            transition.target_values = {"status": "tampered"}

    def test_json_round_trip_preserves_values(self) -> None:
        transition = DomainStateTransition.model_validate(
            transition_payload(
                guard_values={"level": 0, "flag": False},
                target_values={"status": "active", "level": 1},
            )
        )
        restored = DomainStateTransition.model_validate(
            json.loads(json.dumps(transition.model_dump(mode="json")))
        )
        assert restored == transition


class TestTransitionIdentifier:
    def test_is_deterministic_and_prefixed(self) -> None:
        first = transition_identifier(
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-1",
        )
        second = transition_identifier(
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-1",
        )
        assert first == second
        assert first.startswith("transition-")
        assert len(first) == len("transition-") + 16

    def test_changes_with_any_identity_input(self) -> None:
        base = dict(
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-1",
        )
        base_id = transition_identifier(**base)
        assert transition_identifier(**{**base, "scenario_id": "scenario-2"}) != base_id
        assert transition_identifier(**{**base, "manifest_id": "manifest-2"}) != base_id
        assert transition_identifier(**{**base, "state_model_id": "sm-2"}) != base_id
        assert transition_identifier(**{**base, "transition_id": "t-2"}) != base_id


class TestTransitionContentHash:
    def test_is_deterministic(self) -> None:
        store = prepared_store()
        first = declare(store)
        second = declare(store, transition_id="t-2")
        assert first.content_hash == transition_content_hash(first)
        assert second.content_hash == transition_content_hash(second)

    def test_excludes_the_content_hash_field_itself(self) -> None:
        store = prepared_store()
        transition = declare(store)
        payload = transition.model_dump(mode="json")
        del payload["content_hash"]
        expected = sha256_hex(canonical_json(payload))
        assert transition.content_hash == expected

    def test_canonical_mapping_order_yields_identical_transition_and_hash(self) -> None:
        # Equivalent caller key orderings canonicalize to the same
        # mappings.
        ordered: dict[str, JsonValue] = {"level": 0, "flag": False}
        reversed_order: dict[str, JsonValue] = {"flag": False, "level": 0}
        canonical_guard, canonical_target = canonical_value_mappings(
            guard_values=ordered, target_values=reversed_order
        )
        assert canonical_guard == {"flag": False, "level": 0}
        assert list(canonical_guard) == ["flag", "level"]
        assert canonical_target == dict(sorted(ordered.items()))
        # Two stores declaring the same semantic transition with
        # differently ordered caller mappings produce the identical
        # stored transition: same identifier, same content hash, same
        # canonical mapping representation.
        store_a = prepared_store()
        store_b = prepared_store()
        first = declare(
            store_a, guard_values=ordered, target_values={"level": 1, "status": "active"}
        )
        second = declare(
            store_b,
            guard_values=reversed_order,
            target_values={"status": "active", "level": 1},
        )
        assert first.identifier == second.identifier
        assert first.content_hash == second.content_hash
        assert first.guard_values == second.guard_values == {"flag": False, "level": 0}
        assert first.target_values == second.target_values == {"level": 1, "status": "active"}
        assert first == second


class TestDeclareService:
    def test_identity_fields_copied_from_stored_records(self) -> None:
        store = prepared_store()
        transition = declare(store)
        binding = store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1")
        manifest = store.get_domain_pack_manifest("tenant-1", "manifest-1")
        model = store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "sm-1")
        assert transition.scenario_id == "scenario-1"
        assert transition.binding_id == binding.identifier
        assert transition.manifest_id == manifest.identifier
        assert transition.pack_id == manifest.pack_id
        assert transition.pack_version == manifest.pack_version
        assert transition.manifest_content_hash == manifest.content_hash
        assert transition.state_model_id == model.state_model_id
        assert transition.state_model_content_hash == model.content_hash
        assert transition.identifier == transition_identifier(
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-1",
        )

    def test_guard_and_target_values_are_canonicalized_by_field_identifier(
        self,
    ) -> None:
        store = prepared_store()
        transition = declare(
            store,
            guard_values={"flag": False, "level": 0},
            target_values={"level": 1, "status": "active"},
        )
        assert list(transition.guard_values) == ["flag", "level"]
        assert list(transition.target_values) == ["level", "status"]

    def test_requires_owned_scenario(self) -> None:
        store = InMemoryScenarioStore()
        with pytest.raises(ScenarioNotFoundError):
            declare(store)

    def test_requires_binding(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        # A valid immutable state model exists for the scenario/manifest,
        # but its binding was never inserted: the transition service must
        # fail on the binding lookup (its declared order is scenario
        # ownership -> binding -> manifest -> state model) before ever
        # reading the state model.
        store.put_domain_state_model(
            DomainStateModel(
                identifier="state-model-fixture",
                tenant_id="tenant-1",
                scenario_id="scenario-1",
                binding_id="binding-fixture",
                manifest_id="manifest-1",
                pack_id="pack-1",
                pack_version="1.2.3",
                manifest_content_hash=HASH_64,
                state_model_id="sm-1",
                state_fields=default_fields(),
                content_hash=HASH_64,
                declared_at=DECLARED_AT,
            )
        )
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store)

    def test_requires_owned_manifest(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        # Defense-in-depth: a stored binding implies an owned manifest
        # through the public API, so construct a ghost binding directly.
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

    def test_requires_state_model(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        register(store)
        bind(store)
        with pytest.raises(DomainStateModelNotFoundError):
            declare(store)

    def test_foreign_binding_is_indistinguishable_from_unknown(self) -> None:
        store = prepared_store(tenant_id="tenant-a", scenario_id="scenario-a")
        store.put_scenario(build_scenario(identifier="scenario-a", tenant_id="tenant-b"))
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, tenant_id="tenant-b", scenario_id="scenario-a")

    def test_guard_key_must_exist_in_state_model(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainStateTransitionValuesError) as exc_info:
            declare(store, guard_values={"ghost-field": 1})
        assert exc_info.value.reason == (
            "guard field 'ghost-field' does not exist in the state model"
        )

    def test_target_key_must_exist_in_state_model(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainStateTransitionValuesError) as exc_info:
            declare(store, target_values={"ghost-field": 1})
        assert exc_info.value.reason == (
            "target field 'ghost-field' does not exist in the state model"
        )

    @pytest.mark.parametrize(
        ("guard_values", "target_values"),
        [
            ({"level": True}, None),  # bool as integer guard
            (None, {"level": True}),  # bool as integer target
            (None, {"level": 1.5}),  # float as integer target
            (None, {"status": 5}),  # string field with integer value
            (None, {"flag": 1}),  # integer as boolean target
            (None, {"flag": "true"}),  # string as boolean target
            ({"level": "0"}, None),  # string as integer guard
        ],
    )
    def test_values_must_exactly_match_declared_kind(
        self,
        guard_values: dict[str, JsonValue] | None,
        target_values: dict[str, JsonValue] | None,
    ) -> None:
        store = prepared_store()
        with pytest.raises(DomainStateTransitionValuesError):
            declare(
                store,
                guard_values=guard_values,
                target_values=target_values,
            )

    def test_allowed_values_enforced_when_declared(self) -> None:
        # The default fixture fields declare no allowed_values.
        assert all(field_definition.allowed_values == () for field_definition in default_fields())
        # A state model with allowed values: string field limited to idle/active.
        constrained_store = InMemoryScenarioStore()
        constrained_store.put_scenario(build_scenario())
        register(constrained_store)
        bind(constrained_store)
        declare_model(
            constrained_store,
            state_fields=(
                field(
                    "status",
                    value_kind=StateValueKind.STRING,
                    initial_value="idle",
                    allowed_values=("idle", "active"),
                ),
            ),
        )
        with pytest.raises(DomainStateTransitionValuesError) as exc_info:
            declare(
                constrained_store,
                guard_values={},
                target_values={"status": "reserved"},
            )
        assert exc_info.value.reason == (
            "target value for field 'status' is not among its declared allowed_values"
        )
        transition = declare(constrained_store, guard_values={}, target_values={"status": "active"})
        assert transition.target_values == {"status": "active"}

    def test_nested_non_finite_json_values_rejected_by_service(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainStateTransitionValuesError):
            declare(store, target_values={"extra": {"nested": [float("nan")]}})

    def test_binding_snapshot_inconsistency_rejected_safely(self) -> None:
        store = prepared_store()
        tampered = store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1").model_copy(
            update={"pack_id": "pack-tampered"}
        )
        # The store deliberately has no overwrite surface for immutable
        # contracts, so the tampered snapshot is injected directly.
        store._domain_pack_bindings[("tenant-1", "scenario-1", "manifest-1")] = tampered
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        message = str(exc_info.value)
        assert "pack-tampered" not in message
        assert "manifest-1" in message
        assert HASH_64 not in message
        assert exc_info.value.reason == "pack_id mismatch"

    def test_tampered_manifest_rejected_safely(self) -> None:
        store = prepared_store()
        manifest = store.get_domain_pack_manifest("tenant-1", "manifest-1")
        tampered = manifest.model_copy(update={"pack_id": "pack-altered"})
        store._domain_pack_manifests[("tenant-1", "manifest-1")] = tampered
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == "pack_id mismatch"
        assert "pack-altered" not in str(exc_info.value)

    def test_tampered_state_model_content_hash_rejected(self) -> None:
        store = prepared_store()
        model = store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "sm-1")
        tampered = model.model_copy(update={"content_hash": "0" * 64})
        store._domain_state_models[("tenant-1", "scenario-1", "manifest-1", "sm-1")] = tampered
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == "state model content hash mismatch"
        assert "0" * 64 not in str(exc_info.value)

    def test_tampered_state_model_identifier_rejected(self) -> None:
        store = prepared_store()
        model = store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "sm-1")
        tampered = model.model_copy(update={"identifier": "state-model-forged"})
        store._domain_state_models[("tenant-1", "scenario-1", "manifest-1", "sm-1")] = tampered
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == "state model identifier mismatch"
        assert "state-model-forged" not in str(exc_info.value)

    def test_tampered_state_model_binding_relationship_rejected(self) -> None:
        store = prepared_store()
        model = store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "sm-1")
        tampered = model.model_copy(update={"binding_id": "binding-forged"})
        store._domain_state_models[("tenant-1", "scenario-1", "manifest-1", "sm-1")] = tampered
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == "state model binding relationship mismatch"

    def test_non_canonical_state_model_fields_rejected(self) -> None:
        store = prepared_store()
        model = store.get_domain_state_model("tenant-1", "scenario-1", "manifest-1", "sm-1")
        reversed_fields = tuple(reversed(model.state_fields))
        non_canonical = model.model_copy(
            update={"state_fields": reversed_fields, "content_hash": "0" * 64}
        )
        # The forger recomputes the content hash over the non-canonical
        # representation, so only the canonical-fields check can catch it.
        forged_hash = state_model_content_hash(non_canonical)
        forged = non_canonical.model_copy(update={"content_hash": forged_hash})
        store._domain_state_models[("tenant-1", "scenario-1", "manifest-1", "sm-1")] = forged
        with pytest.raises(DomainStateTransitionIntegrityError) as exc_info:
            declare(store)
        assert exc_info.value.reason == "state model fields not canonical"

    def test_duplicate_declaration_rejected_and_never_overwrites(self) -> None:
        store = prepared_store()
        first = declare(store)
        with pytest.raises(DomainStateTransitionAlreadyExistsError):
            declare(store, target_values={"status": "active", "level": 9})
        assert (
            store.get_domain_state_transition("tenant-1", "scenario-1", "manifest-1", "sm-1", "t-1")
            == first
        )

    def test_same_identities_in_another_tenant_are_allowed(self) -> None:
        store = prepared_store(tenant_id="tenant-a", scenario_id="scenario-a")
        declare(store, tenant_id="tenant-a", scenario_id="scenario-a")
        store.put_scenario(build_scenario(identifier="scenario-a", tenant_id="tenant-b"))
        register(store, tenant_id="tenant-b")
        bind(store, tenant_id="tenant-b", scenario_id="scenario-a")
        declare_model(store, tenant_id="tenant-b", scenario_id="scenario-a")
        transition_b = declare(store, tenant_id="tenant-b", scenario_id="scenario-a")
        assert transition_b.tenant_id == "tenant-b"
        assert len(store.list_domain_state_transitions("tenant-a", "scenario-a")) == 1

    def test_get_unknown_or_foreign_raises_typed_404(self) -> None:
        store = prepared_store()
        declare(store)
        with pytest.raises(DomainStateTransitionNotFoundError):
            get_transition(store, "tenant-1", "scenario-1", "manifest-1", "sm-1", "ghost")
        with pytest.raises(DomainStateTransitionNotFoundError):
            get_transition(store, "tenant-other", "scenario-1", "manifest-1", "sm-1", "t-1")

    def test_listing_is_sorted_by_manifest_then_state_model_then_transition(
        self,
    ) -> None:
        store = prepared_store()
        declare(store, transition_id="t-b")
        declare(store, transition_id="t-a")
        declare_model(store, state_model_id="sm-2")
        declare(store, state_model_id="sm-2", transition_id="t-x")
        register(store, identifier="manifest-2", pack_id="pack-2")
        bind(store, manifest_id="manifest-2")
        declare_model(store, manifest_id="manifest-2", state_model_id="sm-1")
        declare(store, manifest_id="manifest-2", transition_id="t-1")
        listing = list_transitions(store, "tenant-1", "scenario-1")
        assert [(t.manifest_id, t.state_model_id, t.transition_id) for t in listing] == [
            ("manifest-1", "sm-1", "t-a"),
            ("manifest-1", "sm-1", "t-b"),
            ("manifest-1", "sm-2", "t-x"),
            ("manifest-2", "sm-1", "t-1"),
        ]

    def test_listing_verifies_scenario_ownership(self) -> None:
        store = prepared_store()
        declare(store)
        with pytest.raises(ScenarioNotFoundError):
            list_transitions(store, "tenant-other", "scenario-1")

    def test_transition_never_executed_or_interpreted(self) -> None:
        store = prepared_store()
        transition = declare(store)
        # The service returns the stored immutable contract untouched: no
        # evaluated guards, no applied target patches, no derived values.
        assert transition == store.get_domain_state_transition(
            "tenant-1", "scenario-1", "manifest-1", "sm-1", "t-1"
        )
        assert transition.guard_values == {"flag": False, "level": 0}
        assert transition.target_values == {"level": 1, "status": "active"}
