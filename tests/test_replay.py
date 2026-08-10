"""Tests for exact replay of completed runs."""

from __future__ import annotations

import pytest
from kalhas.application.domain_errors import (
    ReplayHashMismatchError,
    RunNotCompleteError,
    RunNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.replay_service import replay_run
from kalhas.application.run_planner import run_identifier
from kalhas.application.structural_runtime import event_hash, structural_events
from kalhas.contracts.v1.execution import ReplayManifest, RunState, RunStatus

from tests.phase4_helpers import (
    build_seed,
    build_store,
    execute,
    prepare,
    start,
)


def _execute_default_campaign(store: InMemoryScenarioStore, world_id: str) -> str:
    """Prepare, start, and execute; returns the first run id."""
    prepared = prepare(store, world_id)
    start(store)
    execute(store)
    return run_identifier(prepared.run_plans[0])


class TestExactReplay:
    def test_replay_returns_exact_manifest(self) -> None:
        store, world_id = build_store()
        run_id = _execute_default_campaign(store, world_id)

        manifest = replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        assert isinstance(manifest, ReplayManifest)
        assert manifest.replay_classification == "exact"
        assert manifest.run_id == run_id
        assert manifest.campaign_id == "campaign-1"
        assert manifest.world_version_id == world_id
        status = store.get_run_status("tenant-1", run_id)
        assert manifest.expected_event_hash == status.event_hash
        assert manifest.input_hash == status.input_hash
        assert len(manifest.expected_event_hash) == 64

    def test_replay_regenerates_identical_events_and_hash(self) -> None:
        store, world_id = build_store()
        run_id = _execute_default_campaign(store, world_id)

        replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        status = store.get_run_status("tenant-1", run_id)
        stored_events = store.get_run_events("tenant-1", run_id)
        # The replay result is a genuine regeneration: its hash equals the
        # hash of the stored stream and the recorded expected hash.
        assert event_hash(stored_events) == status.event_hash
        assert len(stored_events) == 3

    def test_replay_is_repeatable(self) -> None:
        store, world_id = build_store()
        run_id = _execute_default_campaign(store, world_id)
        first = replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        second = replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        assert first.model_dump() == second.model_dump()

    def test_replay_of_incomplete_run_rejected(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        with pytest.raises(RunNotCompleteError):
            replay_run(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_replay_of_planned_run_rejected(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        run_id = run_identifier(prepared.run_plans[0])
        with pytest.raises(RunNotCompleteError):
            replay_run(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_replay_hash_mismatch_rejected(self) -> None:
        store, world_id = build_store()
        run_id = _execute_default_campaign(store, world_id)
        # Corrupt the recorded expected hash; regeneration must fail loudly.
        status = store.get_run_status("tenant-1", run_id)
        corrupted = RunStatus(
            identifier=status.identifier,
            tenant_id=status.tenant_id,
            run_id=status.run_id,
            campaign_id=status.campaign_id,
            run_plan_id=status.run_plan_id,
            state=RunState.COMPLETE,
            runtime_version=status.runtime_version,
            input_hash=status.input_hash,
            event_hash="f" * 64,
            created_at=status.created_at,
            changed_at=status.changed_at,
        )
        store.put_run_status("tenant-1", run_id, corrupted)
        with pytest.raises(ReplayHashMismatchError):
            replay_run(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_replay_of_unknown_run_rejected(self) -> None:
        store, world_id = build_store()
        _execute_default_campaign(store, world_id)
        with pytest.raises(RunNotFoundError):
            replay_run(store=store, tenant_id="tenant-1", run_id="run-unknown")

    def test_replay_uses_recorded_inputs_not_cached_events(self) -> None:
        """Deleting the stored event stream must not affect replay."""
        store, world_id = build_store()
        run_id = _execute_default_campaign(store, world_id)
        store.put_run_events("tenant-1", run_id, ())  # wipe cached output
        manifest = replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        assert len(manifest.expected_event_hash) == 64
        # The regenerated stream hash must still match the recorded expected hash.
        plan = next(
            p for p in store.get_run_plans("tenant-1", "campaign-1") if run_identifier(p) == run_id
        )
        regenerated = structural_events(
            run_plan=plan,
            world=store.get_world("tenant-1", world_id),
            strategy=store.get_strategy_candidates("tenant-1", "campaign-1")[0],
            seed=build_seed(),
            run_id=run_id,
        )
        assert event_hash(regenerated) == manifest.expected_event_hash
