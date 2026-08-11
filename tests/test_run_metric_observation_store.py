"""Phase 20 store tests: immutable tenant-scoped observation-set collection.

The store keeps run metric observation sets under a ``(tenant_id,
run_id)`` key with deep defensive copies on every write and read, strict
complete contract revalidation before storage (validator-bypassed
artifacts and non-finite raw values rejected), duplicate rejection
(even for identical second writes), ownership-key rejection,
foreign-tenant access indistinguishable from missing, byte-identical
storage after rejected writes, and no update/delete/repair/replace
surface.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kalhas.application.domain_errors import (
    RunMetricObservationAlreadyExistsError,
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

NOW = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0" * 64


def value_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": "m-1",
        "metric_unit": "units",
        "binding_id": "observation-1",
        "binding_content_hash": HASH_64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": HASH_64,
        "trajectory_result_content_hash": HASH_64,
        "raw_value": 7,
    }
    payload.update(overrides)
    return payload


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "metric-observation-set-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": HASH_64,
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": HASH_64,
        "scenario_seed_id": "seed-1",
        "runtime_version": "2.0.0",
        "input_hash": HASH_64,
        "trajectory_execution_id": "trajectory-execution-1",
        "trajectory_execution_content_hash": HASH_64,
        "observations": [
            value_payload(),
            value_payload(
                metric_id="m-2",
                binding_id="observation-2",
                state_field_id="ratio",
                state_field_value_kind="number",
                raw_value=2.5,
            ),
        ],
        "content_hash": HASH_64,
        "observed_at": NOW,
    }
    payload.update(overrides)
    return payload


def make_set(**overrides: object) -> RunMetricObservationSet:
    return RunMetricObservationSet.model_validate(valid_payload(**overrides))


def make_store() -> InMemoryScenarioStore:
    return InMemoryScenarioStore()


def _snapshot(store: InMemoryScenarioStore) -> dict[tuple[str, str], object]:
    return cast(dict[tuple[str, str], object], copy.deepcopy(store._run_metric_observation_sets))


class TestStoreWriteReadIsolation:
    def test_write_stores_deep_defensive_copy(self) -> None:
        store = make_store()
        observation_set = make_set()
        store.put_run_metric_observation_set("tenant-1", "run-1", observation_set)
        stored = store.get_run_metric_observation_set("tenant-1", "run-1")
        # The stored snapshot is a distinct object from the supplied one.
        assert stored is not observation_set
        internal = store._run_metric_observation_sets[("tenant-1", "run-1")]
        assert internal is not observation_set

    def test_read_returns_fresh_deep_copy(self) -> None:
        store = make_store()
        store.put_run_metric_observation_set("tenant-1", "run-1", make_set())
        first = store.get_run_metric_observation_set("tenant-1", "run-1")
        second = store.get_run_metric_observation_set("tenant-1", "run-1")
        assert first == second
        assert first is not second
        assert first.observations[0] is not second.observations[0]


class TestStoreOrderingAndIsolation:
    def test_one_artifact_per_tenant_and_run(self) -> None:
        store = make_store()
        store.put_run_metric_observation_set("tenant-1", "run-1", make_set())
        store.put_run_metric_observation_set("tenant-1", "run-2", make_set(run_id="run-2"))
        store.put_run_metric_observation_set("tenant-2", "run-1", make_set(tenant_id="tenant-2"))
        assert store.get_run_metric_observation_set("tenant-1", "run-1").run_id == "run-1"
        assert store.get_run_metric_observation_set("tenant-1", "run-2").run_id == "run-2"
        assert store.get_run_metric_observation_set("tenant-2", "run-1").tenant_id == "tenant-2"

    def test_foreign_tenant_indistinguishable_from_missing(self) -> None:
        store = make_store()
        store.put_run_metric_observation_set("tenant-a", "run-1", make_set(tenant_id="tenant-a"))
        with pytest.raises(RunMetricObservationNotFoundError):
            store.get_run_metric_observation_set("tenant-b", "run-1")
        with pytest.raises(RunMetricObservationNotFoundError):
            store.get_run_metric_observation_set("tenant-a", "run-other")


class TestStoreRejection:
    def test_duplicate_rejected_never_overwrites(self) -> None:
        store = make_store()
        first = make_set()
        store.put_run_metric_observation_set("tenant-1", "run-1", first)
        with pytest.raises(RunMetricObservationAlreadyExistsError):
            store.put_run_metric_observation_set("tenant-1", "run-1", make_set())
        # Even an identical second artifact is rejected: creation is one-shot.
        with pytest.raises(RunMetricObservationAlreadyExistsError):
            store.put_run_metric_observation_set("tenant-1", "run-1", first)
        assert store.get_run_metric_observation_set("tenant-1", "run-1") == first

    def test_incorrect_ownership_key_rejected(self) -> None:
        store = make_store()
        foreign_tenant = make_set(tenant_id="tenant-b")
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-a", "run-1", foreign_tenant)
        wrong_run = make_set(run_id="run-other")
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", wrong_run)
        assert store._run_metric_observation_sets == {}

    def test_validator_bypassed_artifact_rejected(self) -> None:
        """model_construct artifacts whose validators never ran are rejected."""
        store = make_store()
        bypassed = RunMetricObservationSet.model_construct(
            **cast(dict[str, Any], valid_payload(runtime_version="1.0.0"))
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", bypassed)
        bad_order = RunMetricObservationSet.model_construct(
            **cast(
                dict[str, Any],
                valid_payload(
                    observations=[
                        value_payload(metric_id="m-2", binding_id="observation-2", raw_value=1),
                        value_payload(),
                    ]
                ),
            )
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", bad_order)
        bad_raw = RunMetricObservationSet.model_construct(
            **cast(
                dict[str, Any],
                valid_payload(observations=[value_payload(raw_value="5")]),
            )
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", bad_raw)
        assert store._run_metric_observation_sets == {}

    def test_non_finite_raw_value_rejected(self) -> None:
        store = make_store()
        bypassed = RunMetricObservationSet.model_construct(
            **cast(
                dict[str, Any],
                valid_payload(
                    observations=[
                        value_payload(
                            state_field_id="ratio",
                            state_field_value_kind="number",
                            raw_value=float("nan"),
                        )
                    ]
                ),
            )
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", bypassed)

    def test_foreign_object_rejected(self) -> None:
        store = make_store()
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-1", {"not": "a set"})  # type: ignore[arg-type]

    def test_rejected_writes_leave_storage_byte_identical(self) -> None:
        store = make_store()
        first = make_set()
        store.put_run_metric_observation_set("tenant-1", "run-1", first)
        before = _snapshot(store)
        with pytest.raises(RunMetricObservationAlreadyExistsError):
            store.put_run_metric_observation_set("tenant-1", "run-1", make_set())
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set(
                "tenant-1", "run-2", make_set(tenant_id="tenant-b")
            )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set(
                "tenant-1",
                "run-2",
                RunMetricObservationSet.model_construct(
                    **cast(dict[str, Any], valid_payload(runtime_version="3.0.0"))
                ),
            )
        with pytest.raises(RunMetricObservationIntegrityError):
            store.put_run_metric_observation_set("tenant-1", "run-2", make_set(run_id="run-other"))
        assert _snapshot(store) == before
        assert store.get_run_metric_observation_set("tenant-1", "run-1") == first

    def test_no_update_delete_repair_or_replace_surface(self) -> None:
        store = make_store()
        for name in dir(store):
            assert not name.startswith("update_run_metric_observation_set")
            assert not name.startswith("delete_run_metric_observation_set")
            assert not name.startswith("repair_run_metric_observation_set")
            assert not name.startswith("replace_run_metric_observation_set")
