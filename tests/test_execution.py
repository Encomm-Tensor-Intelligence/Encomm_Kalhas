"""Tests for deterministic structural execution."""

from __future__ import annotations

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import CampaignNotRunningError, RunNotPlannedError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.structural_runtime import (
    STRUCTURAL_EVENT_KINDS,
    event_hash,
    execute_run,
    structural_events,
)
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.simulation import RunEventKind

from tests.phase4_helpers import (
    LATER,
    NOW,
    build_request,
    build_seed,
    build_store,
    execute,
    prepare,
    start,
)

_FORBIDDEN_PAYLOAD_KEYS = {
    "outcome",
    "outcomes",
    "recommendation",
    "point_estimate",
    "distribution",
    "probability",
    "score",
    "evidence",
    "decision",
    "metric_value",
}


def _run_statuses(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> list[RunStatus]:
    """All run statuses of a campaign, in plan order."""
    plans = store.get_run_plans("tenant-1", campaign_id)
    return [store.get_run_status("tenant-1", run_identifier(plan)) for plan in plans]


class TestCandidatePersistence:
    def test_preparation_persists_exact_strategy_contracts(self) -> None:
        store, world_id = build_store()
        legion = MockLegionAdapter()
        prepare(store, world_id, legion=legion)

        recorded = store.get_strategy_candidates("tenant-1", "campaign-1")
        expected = legion.request_strategies(build_request())
        assert [candidate.model_dump() for candidate in recorded] == [
            candidate.model_dump() for candidate in expected
        ]
        # Execution must never call Legion again: the recorded contracts are
        # sufficient for run generation and replay.
        assert len(recorded) == 5


class TestCampaignExecution:
    def test_execution_rejected_before_campaign_start(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        with pytest.raises(CampaignNotRunningError):
            execute(store)

    def test_execution_rejected_after_completion(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        with pytest.raises(CampaignNotRunningError):
            execute(store)

    def test_every_planned_run_becomes_complete(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        statuses = execute(store)
        assert len(statuses) == 5
        assert all(status.state is RunState.COMPLETE for status in statuses)
        assert all(status.event_hash is not None for status in statuses)
        assert all(len(status.event_hash or "") == 64 for status in statuses)

    def test_campaign_completes_only_after_all_runs(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        campaign_status = store.get_campaign_status("tenant-1", "campaign-1")
        assert campaign_status.state.value == "complete"
        assert "no decision evidence produced" in (campaign_status.message or "")

    def test_runs_start_planned_before_execution(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        for plan in prepared.run_plans:
            status = store.get_run_status("tenant-1", run_identifier(plan))
            assert status.state is RunState.PLANNED
            assert status.event_hash is None

    def test_run_cannot_be_executed_twice(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        execute(store)
        run_plan = prepared.run_plans[0]
        with pytest.raises(RunNotPlannedError):
            execute_run(
                store=store,
                tenant_id="tenant-1",
                run_id=run_identifier(run_plan),
            )


class TestStructuralEvents:
    def test_each_run_emits_exactly_three_events_in_sequence(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        for status in _run_statuses(store):
            events = store.get_run_events("tenant-1", status.run_id)
            assert [event.sequence for event in events] == [0, 1, 2]
            assert [event.kind for event in events] == list(STRUCTURAL_EVENT_KINDS)
            assert [event.kind for event in events] == [
                RunEventKind.RUN_STARTED,
                RunEventKind.STRATEGY_DECLARATION_RECORDED,
                RunEventKind.RUN_COMPLETED,
            ]

    def test_events_carry_full_references(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        execute(store)
        plans = {plan.identifier: plan for plan in prepared.run_plans}
        for status in _run_statuses(store):
            plan = plans[status.run_plan_id]
            for event in store.get_run_events("tenant-1", status.run_id):
                assert event.run_id == status.run_id
                assert event.campaign_id == "campaign-1"
                assert event.world_version_id == world_id
                assert event.strategy_candidate_id == plan.strategy_candidate_id
                assert event.scenario_seed_id == plan.scenario_seed_id
                assert event.simulation_time in (NOW, LATER)
                assert event.created_at == NOW  # derived from recorded inputs, never wall clock

    def test_events_contain_no_outcome_or_recommendation_content(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        for status in _run_statuses(store):
            for event in store.get_run_events("tenant-1", status.run_id):
                assert not _FORBIDDEN_PAYLOAD_KEYS.intersection(event.payload)
                assert not _FORBIDDEN_PAYLOAD_KEYS.intersection(event.metadata.details)
                assert event.kind in STRUCTURAL_EVENT_KINDS

    def test_identical_recorded_inputs_regenerate_identical_events_and_hash(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        execute(store)

        run_plan = prepared.run_plans[0]
        run_id = run_identifier(run_plan)
        stored_events = store.get_run_events("tenant-1", run_id)
        regenerated = structural_events(
            run_plan=run_plan,
            world=store.get_world("tenant-1", world_id),
            strategy=store.get_strategy_candidates("tenant-1", "campaign-1")[0],
            seed=build_seed(),
            run_id=run_id,
        )
        assert [event.model_dump() for event in stored_events] == [
            event.model_dump() for event in regenerated
        ]
        assert event_hash(stored_events) == event_hash(regenerated)


class TestNoArtifactFabrication:
    def test_campaign_completion_produces_no_decision_artifacts(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        # The execution layer has no outcome/evidence/brief concepts: the
        # only artifacts ever written for a run are its status and events,
        # and neither carries outcome-like content.
        for status in _run_statuses(store):
            assert RunStatus.model_validate(status.model_dump()).state is RunState.COMPLETE
            for event in store.get_run_events("tenant-1", status.run_id):
                assert "outcome" not in event.payload
                assert "recommendation" not in event.payload
                assert "evidence" not in event.payload
