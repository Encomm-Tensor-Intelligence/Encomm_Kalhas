"""Phase 20 integrity tests: regeneration-based verification and tamper matrix.

Proves that the verifier regenerates the expected observation set from
the authoritative recorded inputs (run inputs, compiled world, embedded
bindings, verified ``RunTrajectoryExecution``) and requires exact
equality - identifier, ownership, ordering, values, provenance, and
content hash - and that tampering **any** authoritative provenance,
value, or hash field of the stored artifact is rejected with the safe
typed integrity error while the stored artifact is never repaired,
normalized, reordered, or replaced.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import (
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
    RunTrajectoryExecutionIntegrityError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_metric_observation_service import (
    extract_run_metric_observations,
    get_verified_run_metric_observation_set,
    verify_run_metric_observation_set_record,
)
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

from tests.phase4_helpers import TENANT
from tests.phase20_helpers import build_complete_observation_run

OTHER_HASH = "1" * 64


def _extract(store: InMemoryScenarioStore, run_id: str) -> RunMetricObservationSet:
    return extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)


def _tamper(
    artifact: RunMetricObservationSet,
    *,
    field: str,
    value: object,
) -> RunMetricObservationSet:
    """Return a self-consistent-looking artifact with one field tampered."""
    if field == "content_hash":
        return artifact.model_copy(update={"content_hash": OTHER_HASH})
    if field == "observed_at":
        return artifact.model_copy(
            update={"observed_at": datetime(2027, 1, 1, 12, 0, 0, tzinfo=UTC)}
        )
    if field == "runtime_version":
        return artifact.model_copy(update={"runtime_version": "1.0.0"})
    if field.startswith("observations."):
        value_field = field.split(".", 1)[1]
        tampered_values = []
        for index, observation in enumerate(artifact.observations):
            if index == 0:
                tampered_values.append(observation.model_copy(update={value_field: value}))
            else:
                tampered_values.append(observation)
        return artifact.model_copy(update={"observations": tuple(tampered_values)})
    return artifact.model_copy(update={field: value})


class TestVerifierAcceptance:
    def test_verifier_accepts_the_exact_stored_artifact(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        stored = store.get_run_metric_observation_set(TENANT, run_id)
        assert stored == extracted
        verify_run_metric_observation_set_record(
            stored, store=store, tenant_id=TENANT, run_id=run_id
        )
        verified = get_verified_run_metric_observation_set(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert verified == extracted
        assert verified.model_dump(mode="json") == extracted.model_dump(mode="json")

    def test_missing_stored_artifact_never_created(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        _extract(store, run_id)
        # Delete the stored artifact behind the store's back.
        del store._run_metric_observation_sets[(TENANT, run_id)]
        with pytest.raises(RunMetricObservationNotFoundError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)
        # Nothing was recreated.
        assert (TENANT, run_id) not in store._run_metric_observation_sets


class TestTamperMatrix:
    """Every authoritative provenance/value/hash field, tampered one at a time."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("identifier", "metric-observation-set-tampered"),
            ("tenant_id", "tenant-other"),
            ("run_id", "run-other"),
            ("campaign_id", "campaign-other"),
            ("run_plan_id", "plan-other"),
            ("scenario_id", "scenario-other"),
            ("world_version_id", "world-other"),
            ("world_content_hash", OTHER_HASH),
            ("strategy_candidate_id", "mock-other"),
            ("strategy_content_hash", OTHER_HASH),
            ("scenario_seed_id", "seed-other"),
            ("runtime_version", "1.0.0"),
            ("input_hash", OTHER_HASH),
            ("trajectory_execution_id", "trajectory-execution-other"),
            ("trajectory_execution_content_hash", OTHER_HASH),
            ("content_hash", OTHER_HASH),
        ],
    )
    def test_tampered_set_level_field_rejected(self, field: str, value: object) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        tampered = _tamper(extracted, field=field, value=value)
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )
        # Never repaired: the tampered artifact is still what is stored.
        assert store._run_metric_observation_sets[(TENANT, run_id)] == tampered

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("metric_id", "m-other"),
            ("metric_unit", "gallons"),
            ("binding_id", "observation-other"),
            ("binding_content_hash", OTHER_HASH),
            ("manifest_id", "manifest-other"),
            ("state_model_identifier", "state-model-other"),
            ("state_model_id", "sm-other"),
            ("state_model_content_hash", OTHER_HASH),
            ("state_field_id", "field-other"),
            ("state_field_value_kind", "number"),
            ("observation_point", "initial_state"),
            ("trajectory_plan_id", "trajectory-plan-other"),
            ("trajectory_plan_content_hash", OTHER_HASH),
            ("trajectory_result_content_hash", OTHER_HASH),
            ("raw_value", 999),
        ],
    )
    def test_tampered_observation_value_field_rejected(self, field: str, value: object) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        tampered = _tamper(extracted, field=f"observations.{field}", value=value)
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )
        assert store._run_metric_observation_sets[(TENANT, run_id)] == tampered

    def test_tampered_observation_order_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        swapped = extracted.model_copy(
            update={"observations": tuple(reversed(extracted.observations))}
        )
        store._run_metric_observation_sets[(TENANT, run_id)] = swapped
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                swapped, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_tampered_boolean_raw_value_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        tampered = _tamper(extracted, field="observations.raw_value", value=True)
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_tampered_non_finite_raw_value_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        tampered = _tamper(extracted, field="observations.raw_value", value=float("nan"))
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_tampered_observed_at_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        from datetime import UTC, datetime

        tampered = extracted.model_copy(
            update={"observed_at": datetime(2027, 1, 1, 12, 0, 0, tzinfo=UTC)}
        )
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_tampered_authoritative_execution_rejected(self) -> None:
        """Tampering the authoritative execution invalidates the stored set."""
        store, _world_id, run_id = build_complete_observation_run()
        _extract(store, run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_state = dict(result.final_state)
        tampered_state["ratio"] = 42.0
        tampered_execution = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": tampered_state}),)}
        )
        store._run_trajectory_executions[(TENANT, run_id)] = tampered_execution
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)

    def test_tampered_authoritative_world_rejected(self) -> None:
        store, world_id, run_id = build_complete_observation_run()
        _extract(store, run_id)
        world = store.get_world(TENANT, world_id)
        body = copy.deepcopy(world.world)
        snapshots = body["domain_metric_observations"]
        assert isinstance(snapshots, list)
        snapshot = snapshots[0]
        assert isinstance(snapshot, dict)
        snapshot["metric_id"] = "m-ghost"
        store._worlds[(TENANT, world_id)] = world.model_copy(update={"world": body})
        with pytest.raises(WorldSnapshotIntegrityError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)

    def test_verification_never_repairs_storage(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = _extract(store, run_id)
        tampered = extracted.model_copy(update={"content_hash": OTHER_HASH})
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        before = copy.deepcopy(store._run_metric_observation_sets)
        with pytest.raises(RunMetricObservationIntegrityError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)
        assert store._run_metric_observation_sets == before
