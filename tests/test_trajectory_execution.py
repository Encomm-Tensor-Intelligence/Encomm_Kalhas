"""Phase 16 run execution and campaign atomicity tests.

Proves trajectory-runtime (2.0.0) execution stores exactly one immutable
execution artifact per run with one result per applicable plan, keeps the
structural event stream at exactly three events with an independent
structural event hash and no raw state, and writes nothing on any
failure; that legacy (1.0.0) runs keep their byte-identical three-event
behavior with no artifact; that ``execute_run`` cannot accept synthetic
plans; that a second execution never overwrites an artifact; and that
campaign execution preflights every run atomically (invalid first or
later trajectory input => zero execution, zero events, zero artifacts,
all statuses PLANNED, campaign RUNNING) before executing a valid
campaign in stored order.
"""

from __future__ import annotations

import inspect

import pytest
from kalhas.application.domain_errors import (
    RunNotFoundError,
    RunNotPlannedError,
    RunTrajectoryExecutionAlreadyExistsError,
    RunTrajectoryExecutionNotFoundError,
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansRequiredError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.strategy_trajectory_service import (
    get_strategy_trajectory_plans,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import (
    STRUCTURAL_EVENT_KINDS,
    event_hash,
    execute_campaign,
    execute_run,
)
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.simulation import RunEvent, RunEventKind

from tests.phase4_helpers import TENANT, build_store, prepare, start
from tests.phase16_helpers import (
    build_model,
    build_trajectory_store,
    build_transition,
)

STRUCTURAL_PAYLOAD_KEYS = {
    "runtime_version",
    "run_plan_id",
    "lifecycle",
    "strategy_version",
    "policy_summary",
    "event_count",
}


def _run_ids(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, campaign_id))


def _statuses(store: InMemoryScenarioStore, run_ids: tuple[str, ...]) -> tuple[RunStatus, ...]:
    return tuple(store.get_run_status(TENANT, run_id) for run_id in run_ids)


def _events_of(store: InMemoryScenarioStore, run_id: str) -> tuple[RunEvent, ...]:
    return store.get_run_events(TENANT, run_id)


class TestTrajectoryRunExecution:
    def test_v2_run_stores_exactly_one_aggregate_artifact(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        assert execution.run_id == run_id
        assert execution.runtime_version == TRAJECTORY_RUNTIME_VERSION
        assert len(execution.results) == 1

    def test_result_count_equals_applicable_plan_count(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        store, _ = build_trajectory_store(
            state_models=(model_1, model_2),
            transitions=(build_transition(model_1), build_transition(model_2)),
        )
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        assert len(execution.results) == 2
        # One result per applicable plan, in canonical model order.
        plans = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        applicable = [
            p for p in plans if p.strategy_candidate_id == execution.strategy_candidate_id
        ]
        assert [r.trajectory_plan_id for r in execution.results] == [
            p.identifier for p in applicable
        ]

    def test_exactly_three_structural_events_remain(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        events = _events_of(store, run_id)
        assert [event.kind for event in events] == list(STRUCTURAL_EVENT_KINDS)
        assert [event.sequence for event in events] == [0, 1, 2]
        status = store.get_run_status(TENANT, run_id)
        assert status.state is RunState.COMPLETE
        assert status.event_hash == event_hash(events)

    def test_structural_event_hash_independent_of_trajectory_content_hash(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        events = _events_of(store, run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        status = store.get_run_status(TENANT, run_id)
        # The structural event hash is exactly the three-event digest and
        # never touches the trajectory execution content hash.
        assert status.event_hash == event_hash(events)
        assert status.event_hash != execution.content_hash

    def test_no_raw_state_in_structural_events(self) -> None:
        model = build_model(
            field="payload",
            initial_value="idle",
        )
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        for event in _events_of(store, run_id):
            assert set(event.payload) <= STRUCTURAL_PAYLOAD_KEYS
        # Distinctive fixture values never appear in any event payload.
        serialized = str([e.model_dump(mode="json") for e in _events_of(store, run_id)])
        assert "idle" not in serialized
        assert "active" not in serialized

    def test_empty_catalog_v2_run_records_a_valid_empty_execution(self) -> None:
        store, _ = build_trajectory_store()  # plain world, prepared empty plans
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        assert execution.results == ()
        assert len(execution.content_hash) == 64
        status = store.get_run_status(TENANT, run_id)
        assert status.state is RunState.COMPLETE
        assert len(_events_of(store, run_id)) == 3

    def test_v1_run_records_no_trajectory_artifact(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            store.get_run_trajectory_execution(TENANT, run_id)
        events = _events_of(store, run_id)
        assert [event.kind for event in events] == list(STRUCTURAL_EVENT_KINDS)

    def test_execute_run_cannot_accept_synthetic_plans(self) -> None:
        signature = inspect.signature(execute_run)
        assert list(signature.parameters) == ["store", "tenant_id", "run_id"]
        store, world_id = build_store()
        with pytest.raises(TypeError):
            execute_run(  # type: ignore[call-arg]
                store=store, tenant_id=TENANT, run_id="run-x", plans=()
            )

    def test_second_execution_rejected_without_overwriting_artifact(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_run_trajectory_execution(TENANT, run_id)
        # Re-run of a COMPLETE run is rejected by the PLANNED gate; even
        # with the status reset to PLANNED the immutable artifact blocks a
        # second execution.
        with pytest.raises(RunNotPlannedError):
            execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(TENANT, run_id, status.model_copy(update={"state": RunState.PLANNED}))
        with pytest.raises(RunTrajectoryExecutionAlreadyExistsError):
            execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert store.get_run_trajectory_execution(TENANT, run_id) == stored


class TestFailureWritesNothing:
    def test_failure_before_lifecycle_writes_nothing(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _run_ids(store)[0]
        # Break the run's plan selection: drop every plan of the run's
        # strategy from the stored collection (collection-level rejection).
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        strategy_id = store.get_run_plans(TENANT, "campaign-1")[0].strategy_candidate_id
        remaining = tuple(p for p in collection if p.strategy_candidate_id != strategy_id)
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = remaining
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        status = store.get_run_status(TENANT, run_id)
        assert status.state is RunState.PLANNED
        assert status.event_hash is None
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            store.get_run_trajectory_execution(TENANT, run_id)
        with pytest.raises(RunNotFoundError):
            store.get_run_events(TENANT, run_id)

    def test_unsupported_version_rejected_before_lifecycle(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version="3.0.0")
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        status = store.get_run_status(TENANT, run_id)
        assert status.state is RunState.PLANNED
        assert status.event_hash is None


class TestCampaignAtomicity:
    def test_invalid_first_run_trajectory_input_causes_zero_execution(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_ids = _run_ids(store)
        # Drop the first strategy's plan: the FIRST run's trajectory input
        # becomes invalid (collection-level rejection).
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(collection[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        # Zero runs executed, zero events, zero artifacts, all PLANNED,
        # campaign still RUNNING.
        for status in _statuses(store, run_ids):
            assert status.state is RunState.PLANNED
        assert all(store._run_events.get((TENANT, run_id)) is None for run_id in run_ids)
        assert all(
            store._run_trajectory_executions.get((TENANT, run_id)) is None for run_id in run_ids
        )
        assert store.get_campaign_status(TENANT, "campaign-1").state.value == "running"

    def test_invalid_later_run_trajectory_input_causes_zero_execution(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_ids = _run_ids(store)
        # Drop the LAST strategy's plan: the LAST run's trajectory input is
        # invalid, so no earlier run may execute either.
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(collection[:-1])
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for status in _statuses(store, run_ids):
            assert status.state is RunState.PLANNED
        assert all(store._run_events.get((TENANT, run_id)) is None for run_id in run_ids)
        assert all(
            store._run_trajectory_executions.get((TENANT, run_id)) is None for run_id in run_ids
        )
        assert store.get_campaign_status(TENANT, "campaign-1").state.value == "running"

    def test_missing_plans_for_whole_campaign_blocks_execution(self) -> None:
        # A transition-capable world whose campaign never prepared plans:
        # preflight raises TrajectoryPlansRequiredError for the first run.
        model = build_model()
        transition = build_transition(model)
        from kalhas.application.world_compiler import compile_world

        from tests.phase4_helpers import build_scenario

        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        compiled = compile_world(build_scenario(), state_models=(model,), transitions=(transition,))
        store.put_world(compiled.version, compiled.manifest)
        prepared = prepare(store, compiled.version.identifier, runtime_version="2.0.0")
        start(store)
        with pytest.raises(TrajectoryPlansRequiredError):
            execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in prepared.run_plans:
            assert store.get_run_status(TENANT, run_identifier(plan)).state is RunState.PLANNED
        assert store.get_campaign_status(TENANT, "campaign-1").state.value == "running"

    def test_valid_campaign_executes_in_stored_order_and_completes(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_ids = _run_ids(store)
        statuses = execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert [status.run_id for status in statuses] == list(run_ids)
        for run_id in run_ids:
            status = store.get_run_status(TENANT, run_id)
            assert status.state is RunState.COMPLETE
            assert len(_events_of(store, run_id)) == 3
            execution = store.get_run_trajectory_execution(TENANT, run_id)
            assert len(execution.results) == 1
        assert store.get_campaign_status(TENANT, "campaign-1").state.value == "complete"


class TestRuntimeVersioning:
    def test_new_plans_default_to_trajectory_runtime(self) -> None:
        from kalhas.adapters.mocks import MockLegionAdapter
        from kalhas.application.run_planner import plan_runs

        from tests.phase4_helpers import NOW, build_request, build_seed, build_store

        store, world_id = build_store()
        world = store.get_world(TENANT, world_id)
        candidates = MockLegionAdapter().request_strategies(build_request())
        plans = plan_runs(
            campaign_id="campaign-1",
            tenant_id=TENANT,
            world_version_id=world_id,
            world_content_hash=world.content_hash,
            strategies=candidates,
            seeds=(build_seed(),),
            created_at=NOW,
        )
        # The planner default (no runtime_version supplied) is the
        # trajectory runtime.
        assert {plan.runtime_version for plan in plans} == {TRAJECTORY_RUNTIME_VERSION}

    def test_legacy_three_event_behavior_byte_identical(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        events = _events_of(store, run_id)
        assert [event.kind for event in events] == list(STRUCTURAL_EVENT_KINDS)
        assert [event.sequence for event in events] == [0, 1, 2]
        # Payload shape is exactly the structural contract.
        for event in events:
            assert set(event.payload) <= STRUCTURAL_PAYLOAD_KEYS
        assert events[0].payload["runtime_version"] == LEGACY_STRUCTURAL_RUNTIME_VERSION
        assert events[2].payload["event_count"] == 3
        status = store.get_run_status(TENANT, run_id)
        assert status.event_hash == event_hash(events)
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            store.get_run_trajectory_execution(TENANT, run_id)

    def test_legacy_campaign_rejected_by_trajectory_planning(self) -> None:
        from kalhas.adapters.mocks import MockLegionAdapter

        store, world_id = build_store()
        prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        legion = MockLegionAdapter()
        with pytest.raises(UnsupportedRuntimeVersionError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_structural_event_kind_tuple_is_exactly_three_kinds(self) -> None:
        assert tuple(STRUCTURAL_EVENT_KINDS) == (
            RunEventKind.RUN_STARTED,
            RunEventKind.STRATEGY_DECLARATION_RECORDED,
            RunEventKind.RUN_COMPLETED,
        )
