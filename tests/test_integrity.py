"""Tests for deterministic run-input integrity verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    RunInputIntegrityError,
    RunNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.run_planner import run_identifier
from kalhas.application.structural_runtime import execute_campaign, execute_run
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.strategy import PolicyDeclaration

from tests.phase4_helpers import (
    build_request,
    build_store,
    execute,
    prepare,
    start,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_SOURCE = REPO_ROOT / "kalhas" / "application" / "input_integrity.py"


def _plans(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> list[RunPlan]:
    return list(store.get_run_plans("tenant-1", campaign_id))


class TestVerifier:
    def test_normal_planned_run_verifies_exact(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        plan = prepared.run_plans[0]
        run_id = run_identifier(plan)

        verified = verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)
        assert verified.manifest.verification_classification == "exact"
        assert verified.manifest.expected_input_hash == plan.input_hash
        assert verified.manifest.recomputed_input_hash == plan.input_hash
        assert verified.manifest.recorded_at == plan.created_at  # deterministic, not wall clock
        assert verified.manifest.run_id == run_id
        assert verified.manifest.campaign_id == "campaign-1"
        assert verified.manifest.run_plan_id == plan.identifier
        assert verified.manifest.world_version_id == world_id
        assert verified.manifest.strategy_candidate_id == plan.strategy_candidate_id
        assert verified.manifest.scenario_seed_id == plan.scenario_seed_id
        assert verified.manifest.runtime_version == plan.runtime_version
        assert verified.world.identifier == world_id

    def test_verification_uses_persisted_candidate_not_legion(self) -> None:
        store, world_id = build_store()
        legion = MockLegionAdapter()
        prepare(store, world_id, legion=legion)
        plan = _plans(store)[0]
        run_id = run_identifier(plan)

        # The verifier reads the exact contracts persisted at preparation.
        recorded = store.get_strategy_candidates("tenant-1", "campaign-1")
        expected = legion.request_strategies(build_request())
        assert [c.model_dump() for c in recorded] == [c.model_dump() for c in expected]

        verified = verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)
        assert verified.strategy.identifier == plan.strategy_candidate_id
        assert verified.manifest.recomputed_input_hash == plan.input_hash
        # The verifier module must never reference a Legion adapter.
        assert "legion" not in VERIFIER_SOURCE.read_text(encoding="utf-8").lower()

    def test_changed_stored_candidate_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        candidates = store.get_strategy_candidates("tenant-1", "campaign-1")
        tampered = tuple(
            candidate.model_copy(
                update={"policy": PolicyDeclaration(summary="tampered policy", rules=[])}
            )
            if candidate.identifier == candidates[0].identifier
            else candidate
            for candidate in candidates
        )
        store.put_strategy_candidates("tenant-1", "campaign-1", tampered)
        run_id = run_identifier(_plans(store)[0])
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_changed_world_content_hash_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        world = store.get_world("tenant-1", world_id)
        store.put_world(
            world.model_copy(update={"content_hash": "f" * 64}),
            store.get_manifest("tenant-1", world_id),
        )
        run_id = run_identifier(_plans(store)[0])
        # Phase 14: compiled-world integrity verification runs before the
        # world is trusted for input-hash recomputation, so a tampered
        # world content hash surfaces as WorldSnapshotIntegrityError
        # (same typed safe 409 integrity_error family as before).
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_changed_runtime_version_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        run_id = run_identifier(_plans(store)[0])
        status = store.get_run_status("tenant-1", run_id)
        store.put_run_status(
            "tenant-1",
            run_id,
            status.model_copy(update={"runtime_version": "9.9.9"}),
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_changed_run_plan_reference_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        plan = _plans(store)[0]
        store.put_run_plans(
            "tenant-1",
            "campaign-1",
            tuple(
                p.model_copy(update={"scenario_seed_id": "ghost-seed"})
                if p.identifier == plan.identifier
                else p
                for p in _plans(store)
            ),
        )
        run_id = run_identifier(plan)
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_changed_strategy_cross_reference_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        plan = _plans(store)[0]
        store.put_run_plans(
            "tenant-1",
            "campaign-1",
            tuple(
                p.model_copy(update={"strategy_candidate_id": "ghost-strategy"})
                if p.identifier == plan.identifier
                else p
                for p in _plans(store)
            ),
        )
        run_id = run_identifier(plan)
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_error_message_is_safe_and_generic(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        candidates = store.get_strategy_candidates("tenant-1", "campaign-1")
        store.put_strategy_candidates(
            "tenant-1",
            "campaign-1",
            tuple(
                candidate.model_copy(
                    update={"policy": PolicyDeclaration(summary="tampered", rules=[])}
                )
                for candidate in candidates
            ),
        )
        run_id = run_identifier(_plans(store)[0])
        with pytest.raises(RunInputIntegrityError) as excinfo:
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)
        message = str(excinfo.value)
        assert "inconsistent or tampered" in message
        assert "f" * 64 not in message  # no raw hash values
        assert "tampered policy" not in message  # no foreign/internal data


class TestSyntheticPlanIsolation:
    """A synthetic RunPlan can never influence execution or verification."""

    def _synthetic_plan(self, plan: RunPlan) -> RunPlan:
        """A crafted plan sharing the identifier but pointing everywhere else."""
        return RunPlan(
            identifier=plan.identifier,
            tenant_id="tenant-1",
            campaign_id="campaign-evil",
            world_version_id="world-evil",
            strategy_candidate_id="evil-strategy",
            scenario_seed_id="evil-seed",
            runtime_version="9.9.9",
            input_hash="f" * 64,
            created_at=plan.created_at,
        )

    def test_synthetic_run_plan_cannot_influence_execution(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        plan = prepared.run_plans[0]
        run_id = run_identifier(plan)
        synthetic = self._synthetic_plan(plan)

        # execute_run accepts only (store, tenant_id, run_id): the synthetic
        # plan lives only in the caller's memory and can never be executed.
        execution = execute_run(store=store, tenant_id="tenant-1", run_id=run_id)
        assert execution.status.campaign_id == plan.campaign_id
        assert execution.status.run_plan_id == plan.identifier
        assert execution.status.runtime_version == plan.runtime_version
        assert execution.status.input_hash == plan.input_hash
        assert execution.status.state is RunState.COMPLETE
        for event in store.get_run_events("tenant-1", run_id):
            assert event.campaign_id == plan.campaign_id
            assert event.world_version_id == world_id
            assert event.strategy_candidate_id == plan.strategy_candidate_id
            assert event.scenario_seed_id == plan.scenario_seed_id
            assert event.payload["runtime_version"] == plan.runtime_version
        # The synthetic plan's fields never leaked anywhere.
        assert synthetic.campaign_id != execution.status.campaign_id

    def test_synthetic_stored_plan_with_same_identifier_rejected(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        plan = prepared.run_plans[0]
        synthetic = self._synthetic_plan(plan)
        store.put_run_plans(
            "tenant-1",
            "campaign-1",
            tuple([synthetic, *prepared.run_plans[1:]]),
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_identifier(plan))

    def test_world_source_scenario_mismatch_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        world = store.get_world("tenant-1", world_id)
        store.put_world(
            world.model_copy(update={"source_scenario_id": "scenario-other"}),
            store.get_manifest("tenant-1", world_id),
        )
        run_id = run_identifier(_plans(store)[0])
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)

    def test_strategy_outside_campaign_set_rejected(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        candidates = store.get_strategy_candidates("tenant-1", "campaign-1")
        extra = candidates[0].model_copy(update={"identifier": "outside-candidate"})
        store.put_strategy_candidates("tenant-1", "campaign-1", tuple(candidates) + (extra,))
        plan = prepared.run_plans[0]
        store.put_run_plans(
            "tenant-1",
            "campaign-1",
            tuple(
                p.model_copy(update={"strategy_candidate_id": "outside-candidate"})
                if p.identifier == plan.identifier
                else p
                for p in prepared.run_plans
            ),
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_identifier(plan))

    def test_status_identifier_mismatch_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        run_id = run_identifier(_plans(store)[0])
        status = store.get_run_status("tenant-1", run_id)
        store.put_run_status(
            "tenant-1", run_id, status.model_copy(update={"identifier": "status-wrong"})
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)


class TestExecutionGate:
    def test_rejected_execution_preserves_planned_status_and_no_events(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        candidates = store.get_strategy_candidates("tenant-1", "campaign-1")
        store.put_strategy_candidates(
            "tenant-1",
            "campaign-1",
            tuple(
                candidate.model_copy(
                    update={"policy": PolicyDeclaration(summary="tampered", rules=[])}
                )
                for candidate in candidates
            ),
        )
        run_plan = prepared.run_plans[0]
        run_id = run_identifier(run_plan)
        with pytest.raises(RunInputIntegrityError):
            execute_run(store=store, tenant_id="tenant-1", run_id=run_id)
        assert store.get_run_status("tenant-1", run_id).state is RunState.PLANNED
        with pytest.raises(RunNotFoundError):
            store.get_run_events("tenant-1", run_id)

    def test_campaign_preflight_failure_is_atomic(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        # Tamper the third plan's seed reference.
        plans = list(prepared.run_plans)
        tampered = plans[2].model_copy(update={"scenario_seed_id": "ghost-seed"})
        store.put_run_plans(
            "tenant-1", "campaign-1", tuple(plans[:2]) + (tampered,) + tuple(plans[3:])
        )
        with pytest.raises(RunInputIntegrityError):
            execute_campaign(store=store, tenant_id="tenant-1", campaign_id="campaign-1")
        # Atomic: no run executed, no events, statuses still PLANNED, campaign RUNNING.
        for plan in plans:
            status = store.get_run_status("tenant-1", run_identifier(plan))
            assert status.state is RunState.PLANNED
            with pytest.raises(RunNotFoundError):
                store.get_run_events("tenant-1", run_identifier(plan))
        campaign_status = store.get_campaign_status("tenant-1", "campaign-1")
        assert campaign_status.state.value == "running"

    def test_preflight_passes_then_execution_succeeds(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        statuses = execute(store)
        assert all(status.state is RunState.COMPLETE for status in statuses)


class TestReplayGate:
    def test_replay_rejects_tampered_inputs_before_hash_comparison(self) -> None:
        from kalhas.application.replay_service import replay_run

        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute(store)
        run_id = run_identifier(_plans(store)[0])
        # Tamper the stored candidate after a successful execution.
        candidates = store.get_strategy_candidates("tenant-1", "campaign-1")
        store.put_strategy_candidates(
            "tenant-1",
            "campaign-1",
            tuple(
                candidate.model_copy(
                    update={"policy": PolicyDeclaration(summary="tampered", rules=[])}
                )
                for candidate in candidates
            ),
        )
        with pytest.raises(RunInputIntegrityError):
            replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        # The stored events and status are untouched.
        assert len(store.get_run_events("tenant-1", run_id)) == 3
        assert store.get_run_status("tenant-1", run_id).state is RunState.COMPLETE
