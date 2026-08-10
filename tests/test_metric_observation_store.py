"""Phase 19 store tests: immutable tenant-scoped observation-binding collection.

The store keeps domain metric observation bindings under a
``(tenant_id, scenario_id, metric_id)`` key with deep defensive copies on
every write and read, strict complete contract revalidation before
storage, duplicate and incorrect-ownership-key rejection, deterministic
metric-id listing order, foreign-tenant access indistinguishable from
missing, and no update/delete/repair surface.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kalhas.application.domain_errors import (
    DomainMetricObservationAlreadyExistsError,
    DomainMetricObservationIntegrityError,
    DomainMetricObservationNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0" * 64


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "observation-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "metric_id": "m-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "content_hash": HASH_64,
        "declared_at": NOW,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def make_binding(**overrides: object) -> DomainMetricObservationBinding:
    return DomainMetricObservationBinding.model_validate(valid_payload(**overrides))


def make_store() -> InMemoryScenarioStore:
    return InMemoryScenarioStore()


def _snapshot(store: InMemoryScenarioStore) -> dict[tuple[str, str, str], object]:
    return cast(
        dict[tuple[str, str, str], object], copy.deepcopy(store._domain_metric_observations)
    )


class TestStoreWriteReadIsolation:
    def test_write_stores_deep_defensive_copy(self) -> None:
        store = make_store()
        binding = make_binding(metadata={"nested": {"k": [1]}})
        store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", binding)
        metadata = binding.metadata
        assert isinstance(metadata, dict)
        nested = metadata["nested"]
        assert isinstance(nested, dict)
        nested["k"].append(999)  # type: ignore[union-attr]
        stored = store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1")
        assert stored.metadata["nested"] == {"k": [1]}

    def test_read_returns_fresh_deep_copy(self) -> None:
        store = make_store()
        store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", make_binding())
        retrieved = store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1")
        metadata = retrieved.metadata
        assert isinstance(metadata, dict)
        metadata["tampered"] = True
        again = store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1")
        assert "tampered" not in again.metadata
        assert (
            "tampered"
            not in store._domain_metric_observations[("tenant-1", "scenario-1", "m-1")].metadata
        )

    def test_list_returns_fresh_deep_copies(self) -> None:
        store = make_store()
        store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", make_binding())
        listed = store.list_domain_metric_observations("tenant-1", "scenario-1")
        assert len(listed) == 1
        metadata = listed[0].metadata
        assert isinstance(metadata, dict)
        metadata["tampered"] = True
        assert (
            "tampered"
            not in store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1").metadata
        )

    def test_retrieved_nested_metadata_mutation_cannot_affect_storage(self) -> None:
        store = make_store()
        store.put_domain_metric_observation(
            "tenant-1",
            "scenario-1",
            "m-1",
            make_binding(metadata={"nested": {"deep": [1, 2]}}),
        )
        retrieved = store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1")
        nested = retrieved.metadata["nested"]
        assert isinstance(nested, dict)
        deep = nested["deep"]
        assert isinstance(deep, list)
        deep.append(3)
        stored = store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1")
        assert stored.metadata == {"nested": {"deep": [1, 2]}}


class TestStoreOrderingAndIsolation:
    def test_deterministic_metric_id_ordering(self) -> None:
        store = make_store()
        for metric_id in ("m-3", "m-1", "m-2"):
            store.put_domain_metric_observation(
                "tenant-1", "scenario-1", metric_id, make_binding(metric_id=metric_id)
            )
        listed = store.list_domain_metric_observations("tenant-1", "scenario-1")
        assert [binding.metric_id for binding in listed] == ["m-1", "m-2", "m-3"]

    def test_tenant_isolation_list_and_get(self) -> None:
        store = make_store()
        store.put_domain_metric_observation(
            "tenant-a", "scenario-1", "m-1", make_binding(tenant_id="tenant-a")
        )
        assert store.list_domain_metric_observations("tenant-b", "scenario-1") == ()
        assert store.list_domain_metric_observations("tenant-a", "scenario-other") == ()
        with pytest.raises(DomainMetricObservationNotFoundError):
            store.get_domain_metric_observation("tenant-b", "scenario-1", "m-1")
        with pytest.raises(DomainMetricObservationNotFoundError):
            store.get_domain_metric_observation("tenant-a", "scenario-1", "m-other")


class TestStoreRejection:
    def test_duplicate_rejected_never_overwrites(self) -> None:
        store = make_store()
        first = make_binding(metadata={"owner": "first"})
        store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", first)
        with pytest.raises(DomainMetricObservationAlreadyExistsError):
            store.put_domain_metric_observation(
                "tenant-1", "scenario-1", "m-1", make_binding(metadata={"owner": "second"})
            )
        assert store.get_domain_metric_observation("tenant-1", "scenario-1", "m-1") == first

    def test_incorrect_ownership_key_rejected(self) -> None:
        store = make_store()
        foreign_binding = make_binding(tenant_id="tenant-b")
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-a", "scenario-1", "m-1", foreign_binding)
        wrong_scenario = make_binding(scenario_id="scenario-other")
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", wrong_scenario)
        wrong_metric = make_binding(metric_id="m-other")
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", wrong_metric)
        assert store.list_domain_metric_observations("tenant-1", "scenario-1") == ()

    def test_validator_bypass_rejected(self) -> None:
        """A model_construct binding whose validators never ran is rejected."""
        store = make_store()
        bypassed = DomainMetricObservationBinding.model_construct(
            **cast(dict[str, Any], valid_payload(state_field_value_kind="string"))
        )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", bypassed)
        bypassed_point = DomainMetricObservationBinding.model_construct(
            **cast(dict[str, Any], valid_payload(observation_point="initial_state"))
        )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-2", bypassed_point)
        assert store.list_domain_metric_observations("tenant-1", "scenario-1") == ()

    def test_malformed_nested_metadata_rejected(self) -> None:
        """NaN inside nested metadata (validator bypass) is rejected on write."""
        store = make_store()
        bypassed = DomainMetricObservationBinding.model_construct(
            **cast(dict[str, Any], valid_payload(metadata={"nested": [float("nan")]}))
        )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", bypassed)

    def test_foreign_object_rejected(self) -> None:
        store = make_store()
        foreign: object = {"not": "a binding"}
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", foreign)  # type: ignore[arg-type]

    def test_rejected_writes_leave_storage_byte_identical(self) -> None:
        store = make_store()
        store.put_domain_metric_observation("tenant-1", "scenario-1", "m-1", make_binding())
        before = _snapshot(store)
        with pytest.raises(DomainMetricObservationAlreadyExistsError):
            store.put_domain_metric_observation(
                "tenant-1", "scenario-1", "m-1", make_binding(metadata={"x": 1})
            )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation(
                "tenant-1", "scenario-1", "m-2", make_binding(tenant_id="tenant-b")
            )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation(
                "tenant-1", "scenario-1", "m-2", make_binding(metric_id="m-other")
            )
        with pytest.raises(DomainMetricObservationIntegrityError):
            store.put_domain_metric_observation(
                "tenant-1",
                "scenario-1",
                "m-2",
                DomainMetricObservationBinding.model_construct(
                    **cast(dict[str, Any], valid_payload(state_field_value_kind="string"))
                ),
            )
        assert _snapshot(store) == before

    def test_no_update_delete_or_repair_surface(self) -> None:
        store = make_store()
        for name in dir(store):
            assert not name.startswith("update_domain_metric_observation")
            assert not name.startswith("delete_domain_metric_observation")
            assert not name.startswith("repair_domain_metric_observation")
            assert not name.startswith("replace_domain_metric_observation")
