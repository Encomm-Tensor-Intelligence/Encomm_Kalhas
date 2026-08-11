"""Phase 20 extraction service tests.

Proves the deterministic extraction pipeline: verified-input and
runtime/completeness gates, stored-execution authority, compiled-world
binding authority (never newer live declarations), canonical metric-id
order, exact unit copying, exact final-state extraction, deterministic
identity/hash/timestamp, empty binding collections, typed rejection of
missing/ambiguous results, missing fields, provenance mismatches,
wrong numeric kinds, booleans, non-finite values, corrupted
worlds/executions/bindings, legacy and unsupported runtimes, incomplete
runs, and the failed-extraction-writes-nothing guarantee.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
    RunNotCompleteError,
    RunNotFoundError,
    RunTrajectoryExecutionIntegrityError,
    UnsupportedRuntimeVersionError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_metric_observation_service import (
    _resolve_trajectory_result,
    build_run_metric_observation_set,
    extract_run_metric_observations,
    get_verified_run_metric_observation_set,
    run_metric_observation_set_content_hash,
    run_metric_observation_set_identifier,
    verify_run_metric_observation_set_record,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
    strategy_candidate_content_hash,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, StateValueKind

from tests.phase4_helpers import (
    TENANT,
    build_request,
    build_seed,
    build_store,
    execute,
    prepare,
    start,
)
from tests.phase20_helpers import (
    DECLARED_AT,
    build_complete_observation_run,
    build_observation_scenario,
    build_observation_store,
)

HASH_64 = "0" * 64


def _store_set_snapshot(
    store: InMemoryScenarioStore,
) -> dict[tuple[str, str], RunMetricObservationSet]:
    return copy.deepcopy(store._run_metric_observation_sets)


def _field(
    identifier: str, value_kind: StateValueKind, initial_value: JsonValue
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description="Declared state field",
        value_kind=value_kind,
        initial_value=initial_value,
    )


class TestSuccessfulExtraction:
    def test_integer_and_number_observations_extracted(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert [o.metric_id for o in observation_set.observations] == ["m-1", "m-2"]
        integer, number = observation_set.observations
        # Integer binding: exact int from final_state["level"] (0 -> 1).
        assert integer.state_field_value_kind == "integer"
        assert integer.state_field_id == "level"
        assert integer.raw_value == 1
        assert isinstance(integer.raw_value, int)
        # Number binding: exact float from final_state["ratio"] (0.0 -> 1.5).
        assert number.state_field_value_kind == "number"
        assert number.state_field_id == "ratio"
        assert number.raw_value == 1.5
        assert isinstance(number.raw_value, float)
        assert number.observation_point == "final_state"
        assert integer.observation_point == "final_state"

    def test_observation_provenance_copied_from_verified_records(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        binding = store.get_domain_metric_observation(TENANT, "scenario-1", "m-1")
        state_model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        value = observation_set.observations[0]
        assert value.binding_id == binding.identifier
        assert value.binding_content_hash == binding.content_hash
        assert value.manifest_id == binding.manifest_id
        assert value.state_model_identifier == state_model.identifier
        assert value.state_model_id == state_model.state_model_id
        assert value.state_model_content_hash == state_model.content_hash
        assert value.trajectory_plan_id == execution.results[0].trajectory_plan_id
        assert (
            value.trajectory_plan_content_hash == execution.results[0].trajectory_plan_content_hash
        )
        assert value.trajectory_result_content_hash == execution.results[0].content_hash

    def test_set_provenance_copied_from_verified_records(self) -> None:
        store, world_id, run_id = build_complete_observation_run()
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        run_plan = store.get_run_plans(TENANT, "campaign-1")[0]
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        status = store.get_run_status(TENANT, run_id)
        strategy = store.get_strategy_candidates(TENANT, "campaign-1")[0]
        seed = store.get_campaign(TENANT, "campaign-1").seed_ensemble[0]
        assert observation_set.run_id == run_id
        assert observation_set.campaign_id == "campaign-1"
        assert observation_set.run_plan_id == run_plan.identifier
        assert observation_set.scenario_id == "scenario-1"
        assert observation_set.world_version_id == world_id
        assert observation_set.world_content_hash == store.get_world(TENANT, world_id).content_hash
        assert observation_set.strategy_candidate_id == strategy.identifier
        assert observation_set.strategy_content_hash == strategy_candidate_content_hash(strategy)
        assert observation_set.scenario_seed_id == seed.identifier
        assert observation_set.runtime_version == "2.0.0"
        assert observation_set.input_hash == status.input_hash
        assert observation_set.trajectory_execution_id == execution.identifier
        assert observation_set.trajectory_execution_content_hash == execution.content_hash
        assert observation_set.tenant_id == TENANT

    def test_exact_unit_copied_from_embedded_scenario(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert observation_set.observations[0].metric_unit == "units"
        assert observation_set.observations[1].metric_unit == "percent"

    def test_deterministic_identifier_hash_and_timestamp(self) -> None:
        store_a, _wa, run_a = build_complete_observation_run()
        store_b, _wb, run_b = build_complete_observation_run()
        set_a = extract_run_metric_observations(store=store_a, tenant_id=TENANT, run_id=run_a)
        set_b = extract_run_metric_observations(store=store_b, tenant_id=TENANT, run_id=run_b)
        assert set_a.identifier == set_b.identifier
        assert set_a.content_hash == set_b.content_hash
        assert set_a.identifier == run_metric_observation_set_identifier(
            run_id=run_a, runtime_version="2.0.0"
        )
        assert set_a.identifier.startswith("metric-observation-set-")
        assert len(set_a.identifier) == len("metric-observation-set-") + 16
        assert run_metric_observation_set_content_hash(set_a) == set_a.content_hash
        # observed_at is the authoritative execution's executed_at - never wall clock.
        execution = store_a.get_run_trajectory_execution(TENANT, run_a)
        assert set_a.observed_at == execution.executed_at
        assert set_a.observed_at == store_a.get_run_plans(TENANT, "campaign-1")[0].created_at
        assert set_a.observed_at == set_b.observed_at

    def test_insertion_order_invariance(self) -> None:
        """Binding insertion order never affects the extracted artifact."""
        store_a, _wa, run_a = build_complete_observation_run()
        store_b, _wb, run_b = build_complete_observation_run()
        # Recompile store_b's world with the observation bindings in the
        # reverse tuple order; the compiler canonicalizes by metric_id, so
        # the embedded snapshots and the extracted artifact must be identical.
        binding = store_b.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
        state_model = store_b.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
        transition = store_b.get_domain_state_transition(
            TENANT, "scenario-1", "manifest-1", "sm-1", "t-1"
        )
        observations = tuple(
            reversed(store_b.list_domain_metric_observations(TENANT, "scenario-1"))
        )
        compiled = compile_world(
            build_observation_scenario(),
            bindings=(binding,),
            state_models=(state_model,),
            transitions=(transition,),
            domain_metric_observations=observations,
        )
        store_b.put_world(compiled.version, compiled.manifest)
        set_a = extract_run_metric_observations(store=store_a, tenant_id=TENANT, run_id=run_a)
        set_b = extract_run_metric_observations(store=store_b, tenant_id=TENANT, run_id=run_b)
        assert set_a == set_b
        assert set_a.identifier == set_b.identifier
        assert set_a.content_hash == set_b.content_hash

    def test_compiled_world_authority_ignores_newer_declarations(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        # A binding declared AFTER world compilation (newer scenario-level
        # declaration) must never influence extraction.
        declare_domain_metric_observation(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-3",
            state_field_id="level",
            declared_at=DECLARED_AT,
        )
        assert len(store.list_domain_metric_observations(TENANT, "scenario-1")) == 3
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert [o.metric_id for o in observation_set.observations] == ["m-1", "m-2"]

    def test_empty_binding_collection_yields_empty_observations(self) -> None:
        store, _world_id, run_id = build_complete_observation_run(with_bindings=False)
        observation_set = extract_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert observation_set.observations == ()
        assert (
            run_metric_observation_set_content_hash(observation_set) == observation_set.content_hash
        )

    def test_extraction_is_stored_and_retrievable(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_run_metric_observation_set(TENANT, run_id)
        assert stored == extracted
        verified = get_verified_run_metric_observation_set(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert verified == extracted


class TestTypedRejections:
    def test_missing_trajectory_result_rejected(self) -> None:
        """A binding to a state model without an evaluated trajectory result."""
        store = build_observation_store()
        declare_state_model(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-2",
            state_fields=(_field("score", StateValueKind.NUMBER, 0.0),),
            declared_at=DECLARED_AT,
        )
        declare_domain_metric_observation(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-2",
            metric_id="m-3",
            state_field_id="score",
            declared_at=DECLARED_AT,
        )
        binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
        sm_1 = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
        sm_2 = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-2")
        transition = store.get_domain_state_transition(
            TENANT, "scenario-1", "manifest-1", "sm-1", "t-1"
        )
        observations = tuple(store.list_domain_metric_observations(TENANT, "scenario-1"))
        compiled = compile_world(
            build_observation_scenario(),
            bindings=(binding,),
            state_models=(sm_1, sm_2),
            transitions=(transition,),
            domain_metric_observations=observations,
        )
        store.put_world(compiled.version, compiled.manifest)
        prepare(
            store,
            compiled.version.identifier,
            runtime_version="2.0.0",
            legion=MockLegionAdapter(),
            campaign_id="campaign-1",
        )
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        start(store, "campaign-1")
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        before = _store_set_snapshot(store)
        with pytest.raises(RunMetricObservationIntegrityError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        assert _store_set_snapshot(store) == before

    def test_ambiguous_trajectory_result_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        duplicated = execution.model_copy(
            update={"results": (execution.results[0], execution.results[0])}
        )
        binding = store.get_domain_metric_observation(TENANT, "scenario-1", "m-1")
        with pytest.raises(RunMetricObservationIntegrityError):
            _resolve_trajectory_result("run-x", duplicated, binding)

    def test_missing_final_state_field_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        pruned_state = {k: v for k, v in result.final_state.items() if k != "level"}
        crafted = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": pruned_state}),)}
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            build_run_metric_observation_set(inputs=trajectory_inputs, execution=crafted)

    def test_state_model_identity_mismatch_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        crafted = execution.model_copy(
            update={"results": (result.model_copy(update={"state_model_id": "sm-other"}),)}
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            build_run_metric_observation_set(inputs=trajectory_inputs, execution=crafted)

    def test_state_model_hash_mismatch_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        crafted = execution.model_copy(
            update={"results": (result.model_copy(update={"state_model_content_hash": HASH_64}),)}
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            build_run_metric_observation_set(inputs=trajectory_inputs, execution=crafted)

    @pytest.mark.parametrize(
        ("bad_value", "kind"),
        [
            ("5", "integer"),
            (True, "integer"),
            ("2.5", "number"),
            (True, "number"),
            (float("nan"), "number"),
            (float("inf"), "number"),
            (1.5, "integer"),
        ],
    )
    def test_wrong_numeric_kind_bool_and_non_finite_rejected(
        self, bad_value: JsonValue, kind: str
    ) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        trajectory_inputs = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        field = "level" if kind == "integer" else "ratio"
        tampered_state = dict(result.final_state)
        tampered_state[field] = bad_value
        crafted = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": tampered_state}),)}
        )
        with pytest.raises(RunMetricObservationIntegrityError):
            build_run_metric_observation_set(inputs=trajectory_inputs, execution=crafted)

    def test_corrupted_execution_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_state = dict(result.final_state)
        tampered_state["ratio"] = 99.0
        tampered = execution.model_copy(
            update={"results": (result.model_copy(update={"final_state": tampered_state}),)}
        )
        store._run_trajectory_executions[(TENANT, run_id)] = tampered
        before = _store_set_snapshot(store)
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        assert _store_set_snapshot(store) == before

    def test_corrupted_world_rejected(self) -> None:
        store, world_id, run_id = build_complete_observation_run()
        world = store.get_world(TENANT, world_id)
        body = copy.deepcopy(world.world)
        snapshots = body["domain_metric_observations"]
        assert isinstance(snapshots, list)
        snapshot = snapshots[0]
        assert isinstance(snapshot, dict)
        snapshot["metric_id"] = "m-ghost"
        tampered = world.model_copy(update={"world": body})
        store._worlds[(TENANT, world_id)] = tampered
        before = _store_set_snapshot(store)
        with pytest.raises(WorldSnapshotIntegrityError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        assert _store_set_snapshot(store) == before

    def test_corrupted_binding_rejected(self) -> None:
        """A tampered embedded binding is caught by world verification."""
        store, world_id, run_id = build_complete_observation_run()
        world = store.get_world(TENANT, world_id)
        body = copy.deepcopy(world.world)
        snapshots = body["domain_metric_observations"]
        assert isinstance(snapshots, list)
        snapshot = snapshots[0]
        assert isinstance(snapshot, dict)
        snapshot["state_field_id"] = "status"
        tampered = world.model_copy(update={"world": body})
        store._worlds[(TENANT, world_id)] = tampered
        with pytest.raises(WorldSnapshotIntegrityError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)

    def test_legacy_runtime_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)

    def test_unsupported_runtime_rejected(self) -> None:
        store, world_id = build_complete_observation_run(execute=False)[:2]
        # Re-prepare a second campaign under an unsupported recorded version.
        from kalhas.application.campaign_service import prepare_campaign

        prepare_campaign(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-unsupported",
            campaign_name="Unsupported campaign",
            seed_ensemble=(build_seed(),),
            created_at=datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC),
            runtime_version="3.0.0",
        )
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-unsupported")[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)

    def test_incomplete_run_rejected(self) -> None:
        store, _world_id, run_id = build_complete_observation_run(execute=False)
        with pytest.raises(RunNotCompleteError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)

    def test_duplicate_extraction_rejected_never_overwrites(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        first = extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        from kalhas.application.domain_errors import RunMetricObservationAlreadyExistsError

        with pytest.raises(RunMetricObservationAlreadyExistsError):
            extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        assert store.get_run_metric_observation_set(TENANT, run_id) == first

    def test_unknown_run_indistinguishable_from_missing(self) -> None:
        store, _world_id, _run_id = build_complete_observation_run()
        with pytest.raises(RunNotFoundError):
            get_verified_run_metric_observation_set(
                store=store, tenant_id="tenant-ghost", run_id="run-ghost"
            )

    def test_get_before_extraction_raises_typed_not_found(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        with pytest.raises(RunMetricObservationNotFoundError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)
        # GET never creates the artifact.
        with pytest.raises(RunMetricObservationNotFoundError):
            store.get_run_metric_observation_set(TENANT, run_id)


class TestVerification:
    def test_verifier_accepts_exact_artifact(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        verify_run_metric_observation_set_record(
            extracted, store=store, tenant_id=TENANT, run_id=run_id
        )

    def test_verifier_rejects_tampered_artifact(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extracted = extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        tampered = extracted.model_copy(update={"content_hash": HASH_64})
        store._run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RunMetricObservationIntegrityError):
            get_verified_run_metric_observation_set(store=store, tenant_id=TENANT, run_id=run_id)
        # The stored artifact is never repaired or replaced.
        assert store._run_metric_observation_sets[(TENANT, run_id)] == tampered

    def test_verifier_rejects_foreign_artifact(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        extract_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_run_metric_observation_set(TENANT, run_id)
        foreign = stored.model_copy(update={"tenant_id": "tenant-other"})
        store._run_metric_observation_sets[(TENANT, run_id)] = foreign
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                foreign, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_verifier_rejects_non_contract_object(self) -> None:
        store, _world_id, run_id = build_complete_observation_run()
        with pytest.raises(RunMetricObservationIntegrityError):
            verify_run_metric_observation_set_record(
                {"not": "a set"}, store=store, tenant_id=TENANT, run_id=run_id
            )
