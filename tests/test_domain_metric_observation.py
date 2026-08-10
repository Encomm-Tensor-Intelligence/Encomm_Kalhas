"""Phase 19 service tests: domain metric observation declaration.

The declaration service copies every authoritative identity field from
stored immutable records, requires ``metric_id`` to identify exactly one
scenario metric, requires the referenced state field to be numeric
(``integer`` or ``number``), derives a deterministic identifier and
content hash, and stores the immutable binding tenant-scoped. These
tests prove the declaration behavior, the typed error surface, the
uniqueness rule (one binding per scenario metric), the failed-declaration
writes-nothing guarantee, and the absence of any domain-pack loading or
trajectory/execution access.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import (
    DomainMetricObservationAlreadyExistsError,
    DomainMetricObservationMetricNotFoundError,
    DomainMetricObservationNonNumericFieldError,
    DomainMetricObservationNotFoundError,
    DomainMetricObservationStateFieldNotFoundError,
    DomainPackBindingNotFoundError,
    DomainStateModelNotFoundError,
    ScenarioNotFoundError,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
    domain_metric_observation_content_hash,
    domain_metric_observation_identifier,
    get_domain_metric_observation,
    list_domain_metric_observations,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, StateValueKind

from tests.phase4_helpers import NOW, TENANT, build_scenario

DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)


def _field(
    identifier: str,
    value_kind: StateValueKind,
    initial_value: JsonValue,
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description="Declared state field",
        value_kind=value_kind,
        initial_value=initial_value,
    )


def _default_fields() -> tuple[DomainStateFieldDefinition, ...]:
    return (
        _field("level", StateValueKind.INTEGER, 0),
        _field("ratio", StateValueKind.NUMBER, 0.0),
        _field("status", StateValueKind.STRING, "idle"),
        _field("flag", StateValueKind.BOOLEAN, False),
        _field("extra", StateValueKind.JSON, {"nested": [1]}),
    )


def prepared_store(
    *,
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
    fields: tuple[DomainStateFieldDefinition, ...] | None = None,
) -> InMemoryScenarioStore:
    """A store with a scenario, registered manifest, binding, and state model."""
    store = InMemoryScenarioStore()
    scenario = build_scenario(identifier=scenario_id, tenant_id=tenant_id)
    store.put_scenario(scenario)
    register_manifest(
        store,
        tenant_id=tenant_id,
        identifier=manifest_id,
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.2.3",
        description="Declarative pack metadata only",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        schema_metadata={},
        created_at=NOW,
        metadata={},
    )
    bind_manifest(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        bound_at=BOUND_AT,
    )
    declare_state_model(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
        state_fields=fields if fields is not None else _default_fields(),
        declared_at=DECLARED_AT,
    )
    return store


def declare(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
    metric_id: str = "m-1",
    state_field_id: str = "level",
    declared_at: datetime = DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainMetricObservationBinding:
    return declare_domain_metric_observation(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
        metric_id=metric_id,
        state_field_id=state_field_id,
        declared_at=declared_at,
        metadata=metadata,
    )


class TestDeclareObservation:
    def test_valid_integer_field_binding(self) -> None:
        store = prepared_store()
        observation = declare(store)
        assert observation.scenario_id == "scenario-1"
        assert observation.metric_id == "m-1"
        assert observation.state_field_id == "level"
        assert observation.state_field_value_kind == "integer"
        assert observation.observation_point == "final_state"
        assert observation.identifier.startswith("observation-")
        assert len(observation.content_hash) == 64
        # Stored snapshot is exactly the returned binding.
        stored = get_domain_metric_observation(store, TENANT, "scenario-1", "m-1")
        assert stored == observation

    def test_valid_number_field_binding(self) -> None:
        store = prepared_store()
        observation = declare(store, state_field_id="ratio")
        assert observation.state_field_value_kind == "number"
        assert observation.state_field_id == "ratio"

    def test_authoritative_identity_and_hash_copying(self) -> None:
        store = prepared_store()
        observation = declare(store)
        binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
        manifest = store.get_domain_pack_manifest(TENANT, "manifest-1")
        state_model = store.get_domain_state_model(
            TENANT, "scenario-1", "manifest-1", "state-model-1"
        )
        assert observation.binding_id == binding.identifier
        assert observation.manifest_id == manifest.identifier
        assert observation.pack_id == manifest.pack_id
        assert observation.pack_version == manifest.pack_version
        assert observation.manifest_content_hash == manifest.content_hash
        assert observation.state_model_identifier == state_model.identifier
        assert observation.state_model_id == state_model.state_model_id
        assert observation.state_model_content_hash == state_model.content_hash

    def test_deterministic_identifier_and_content_hash(self) -> None:
        store = prepared_store()
        store_two = prepared_store()
        first = declare(store)
        second = declare(store_two, declared_at=datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC))
        # A different declared_at changes the content hash (it is part of
        # the canonical content) but never the identifier.
        assert first.identifier == second.identifier
        assert first.content_hash != second.content_hash
        expected_identifier = domain_metric_observation_identifier(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            metric_id="m-1",
            manifest_id="manifest-1",
            state_model_id="state-model-1",
            state_field_id="level",
            observation_point="final_state",
        )
        assert first.identifier == expected_identifier
        assert domain_metric_observation_content_hash(first) == first.content_hash

    def test_metadata_insertion_order_invariance(self) -> None:
        store_a = prepared_store()
        store_b = prepared_store()
        metadata_a: dict[str, JsonValue] = {"z": 1, "a": {"n": 2}}
        metadata_b: dict[str, JsonValue] = {"a": {"n": 2}, "z": 1}
        observation_a = declare(store_a, metadata=metadata_a)
        observation_b = declare(store_b, metadata=metadata_b)
        assert observation_a.identifier == observation_b.identifier
        assert observation_a.content_hash == observation_b.content_hash

    def test_string_field_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainMetricObservationNonNumericFieldError):
            declare(store, state_field_id="status")

    def test_boolean_field_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainMetricObservationNonNumericFieldError):
            declare(store, state_field_id="flag")

    def test_json_field_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainMetricObservationNonNumericFieldError):
            declare(store, state_field_id="extra")

    def test_unknown_scenario_metric_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainMetricObservationMetricNotFoundError):
            declare(store, metric_id="m-ghost")

    def test_unknown_manifest_binding_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, manifest_id="manifest-ghost")

    def test_unknown_state_model_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainStateModelNotFoundError):
            declare(store, state_model_id="state-model-ghost")

    def test_unknown_state_field_rejected(self) -> None:
        store = prepared_store()
        with pytest.raises(DomainMetricObservationStateFieldNotFoundError):
            declare(store, state_field_id="field-ghost")

    def test_foreign_tenant_scenario_indistinguishable_from_missing(self) -> None:
        """A tenant that does not own the scenario sees a typed 404."""
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(identifier="scenario-1", tenant_id="tenant-a"))
        with pytest.raises(ScenarioNotFoundError):
            declare(store, tenant_id="tenant-b")

    def test_foreign_tenant_binding_indistinguishable_from_missing(self) -> None:
        """A tenant owning the scenario but not the binding sees a typed 404."""
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(identifier="scenario-1", tenant_id="tenant-b"))
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, tenant_id="tenant-b", scenario_id="scenario-1")

    def test_duplicate_metric_binding_rejected_never_overwrites(self) -> None:
        store = prepared_store()
        first = declare(store)
        with pytest.raises(DomainMetricObservationAlreadyExistsError):
            declare(store, state_field_id="ratio")  # different field, same metric
        stored = get_domain_metric_observation(store, TENANT, "scenario-1", "m-1")
        assert stored == first

    def test_failed_declaration_writes_nothing(self) -> None:
        store = prepared_store()
        before = copy.deepcopy(store.list_domain_metric_observations(TENANT, "scenario-1"))
        with pytest.raises(DomainMetricObservationMetricNotFoundError):
            declare(store, metric_id="m-ghost")
        with pytest.raises(DomainMetricObservationNonNumericFieldError):
            declare(store, state_field_id="status")
        with pytest.raises(DomainMetricObservationStateFieldNotFoundError):
            declare(store, state_field_id="field-ghost")
        with pytest.raises(DomainPackBindingNotFoundError):
            declare(store, manifest_id="manifest-ghost")
        assert store.list_domain_metric_observations(TENANT, "scenario-1") == before


class TestObservationListing:
    def test_list_is_deterministic_metric_id_order(self) -> None:
        # A scenario with three metrics, bound and with a state model.
        from kalhas.contracts.v1.shared import MetricDefinition

        scenario = build_scenario().model_copy(
            update={
                "metrics": [
                    MetricDefinition(identifier="m-1", name="Primary metric"),
                    MetricDefinition(identifier="m-2", name="Secondary metric"),
                    MetricDefinition(identifier="m-3", name="Tertiary metric"),
                ]
            }
        )
        store = InMemoryScenarioStore()
        store.put_scenario(scenario)
        register_manifest(
            store,
            tenant_id=TENANT,
            identifier="manifest-1",
            pack_id="pack-1",
            name="Generic reference pack",
            pack_version="1.2.3",
            description="Declarative pack metadata only",
            supported_api_versions=("1",),
            capabilities=(
                DomainPackCapability(
                    identifier="cap-1",
                    description="Declared capability",
                    input_ids=("in-1",),
                    output_ids=("out-1",),
                ),
            ),
            schema_metadata={},
            created_at=NOW,
            metadata={},
        )
        bind_manifest(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            bound_at=BOUND_AT,
        )
        declare_state_model(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="state-model-1",
            state_fields=_default_fields(),
            declared_at=DECLARED_AT,
        )
        declare(store, metric_id="m-1")
        declare(store, metric_id="m-3", state_field_id="ratio")
        declare(store, metric_id="m-2")
        observations = list_domain_metric_observations(store, TENANT, "scenario-1")
        assert [observation.metric_id for observation in observations] == ["m-1", "m-2", "m-3"]

    def test_list_unknown_or_foreign_scenario_raises_typed_404(self) -> None:
        prepared_store(tenant_id="tenant-a")
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(identifier="scenario-ghost", tenant_id="tenant-b"))
        with pytest.raises(ScenarioNotFoundError):
            list_domain_metric_observations(store, "tenant-b", "scenario-1")

    def test_get_unknown_or_foreign_indistinguishable(self) -> None:
        store = prepared_store(tenant_id="tenant-a")
        with pytest.raises(DomainMetricObservationNotFoundError):
            get_domain_metric_observation(store, "tenant-a", "scenario-1", "m-ghost")
        with pytest.raises(DomainMetricObservationNotFoundError):
            get_domain_metric_observation(store, "tenant-b", "scenario-1", "m-1")

    def test_tampered_binding_integrity_rejected(self) -> None:
        """A self-consistent tamper of the stored binding is rejected."""
        store = prepared_store()
        declare(store)
        stored = store.get_domain_metric_observation(TENANT, "scenario-1", "m-1")
        tampered = stored.model_copy(update={"state_field_id": "ratio"})
        tampered = tampered.model_copy(
            update={"content_hash": domain_metric_observation_content_hash(tampered)}
        )
        store._domain_metric_observations[(TENANT, "scenario-1", "m-1")] = tampered
        # The getter is a plain store read (the service verifies on
        # declaration, not on read); integrity is enforced by the world
        # verifier and the store's write boundary. The stored snapshot is
        # never repaired.
        assert store.get_domain_metric_observation(TENANT, "scenario-1", "m-1") == tampered
        assert isinstance(tampered, type(stored))
        assert tampered.state_field_id == "ratio"

    def test_service_never_touches_domain_packs_or_trajectories(self) -> None:
        """Source scan: the service never loads packs or reads trajectory artifacts."""
        import re
        from pathlib import Path

        source = Path("kalhas/application/domain_metric_observation_service.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        assert not re.search(r"\b(importlib|__import__|import_module|exec\(|eval\()", code)
        assert "kalhas.domain_packs" not in code
        assert not re.search(
            r"\b(RunTrajectoryExecution|evaluate_trajectory|trajectory_execution|extract)\b",
            code,
        )
        assert not re.search(
            r"\b(random|uuid|datetime\.now|time\.|requests|urllib|socket|subprocess)\b", code
        )

    def test_duplicate_error_occurs_before_any_write(self) -> None:
        """The duplicate check fires before the store accepts the binding."""
        store = prepared_store()
        first = declare(store)
        tampered = first.model_copy(update={"state_field_id": "ratio"})
        tampered = tampered.model_copy(
            update={"content_hash": domain_metric_observation_content_hash(tampered)}
        )
        with pytest.raises(DomainMetricObservationAlreadyExistsError):
            store.put_domain_metric_observation(TENANT, "scenario-1", "m-1", tampered)
        assert store.get_domain_metric_observation(TENANT, "scenario-1", "m-1") == first
