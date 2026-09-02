"""H28-S07B2 exact replay recomputation service proofs (runtime 4.0.0).

Real runtime-4 executions (built by the real service through the real
store, then re-verified with the established execution authority) are
used to prove the deterministic
:func:`replay_adaptive_run` recomputation service end to end: successful
exact replay with and without a real accepted external bundle; the exact
manifest identifier, provenance fields, expected/recomputed hash
equality, classification, replay timestamp, and content hash;
independently regenerated complete execution canonical equality; the
cardinality-derived causal horizon (horizon 0 and multi-step/switch
evidence); deterministic results across byte-equivalent independent
environments; the idempotent second replay that returns the verified
existing manifest and changes no store or activity state; the rejection
of every PLANNED/RUNNING/FAILED/non-runtime-4/missing/foreign run; the
missing/corrupt execution, run plan, run status, campaign, world, seed,
policy, declaration, action-plan, and external-bundle rejections; the
stored-versus-regenerated mismatch rejection across observation, policy
state, decision, switch, trajectory/state, input hash, and plan-set
provenance (self-consistent tamperings recomputing every covered hash);
the wrong-type/subclass/``model_construct`` boundary adversaries;
non-leaking safe public messages; input/store fingerprints with zero
operational activity and full failure atomicity; the unchanged
runtime-1/2/3 replay and store behavior; and the absence of every
forbidden surface or import. No mocks, monkeypatch, skip, xfail, noqa,
or type-ignore appear in this module; no historical runtime-1/2/3
replay surface is invoked by the service.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import kalhas.application.adaptive_trajectory_replay_service as service_module
import pytest
from kalhas.application.adaptive_run_execution_builder import (
    AdaptiveRunExecutionBuildDraft,
    build_adaptive_run_trajectory_execution,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_trajectory_execution_content_hash,
)
from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestAlreadyExistsError,
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
    AdaptiveRunTrajectoryReplayManifestNotFoundError,
    AdaptiveRunTrajectoryReplayManifestValidationError,
)
from kalhas.application.adaptive_trajectory_replay_identity import (
    adaptive_run_trajectory_replay_manifest_content_hash,
    adaptive_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.adaptive_trajectory_replay_service import replay_adaptive_run
from kalhas.application.domain_errors import (
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.realization_trajectory_runtime import (
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.runtime_observation_event_identity import (
    runtime_observation_event_content_hash,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.trajectory_integrity import _trace_hash
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.run_plan import RunPlan

from tests.phase4_helpers import TENANT
from tests.test_adaptive_run_execution_builder import (
    CAMPAIGN,
    SEED_ID,
    Env,
    _build_env,
    _build_env_external,
)
from tests.test_adaptive_run_execution_service import (
    _planned_run,
    _rebuilt_authorities,
    _surface,
    execute_adaptive_run,
)
from tests.test_adaptive_trajectory_replay_identity_integrity import _manifest_for
from tests.test_adaptive_trajectory_replay_store import (
    _H64_ALT,
    FOREIGN_TENANT,
    _runtime2_manifest,
    _runtime3_manifest,
)

#: A distinct valid replay-timestamp authority used only for a differing
#: existing-manifest proof; the recorded RunPlan creation time is the
#: authoritative replay timestamp.
_OTHER_TIMESTAMP = datetime(2026, 2, 2, 8, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixture helpers (real service, real store, established B1A construction)
# ---------------------------------------------------------------------------


def _fixture(
    *,
    external: bool = False,
    final_step: int = 0,
) -> tuple[Env, InMemoryScenarioStore, str, RunPlan, AdaptiveRunTrajectoryExecution]:
    """One real completed runtime-4 run with its verified execution stored.

    ``external=True`` uses the real external-bundle environment (whose
    accepted bundle covers step 0 only, so its valid horizon is 0).
    """
    env = _build_env_external() if external else _build_env()
    store, run_id, run_plan, _status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=final_step,
            external_bundle_draft=env.bundle_draft if external else None,
        ),
    )
    return env, store, run_id, run_plan, result.execution


def _expected_manifest(
    execution: AdaptiveRunTrajectoryExecution,
    run_plan: RunPlan,
) -> AdaptiveRunTrajectoryReplayManifest:
    """The real manifest that truthfully attests ``execution`` at the plan time."""
    return _manifest_for(execution, replayed_at=run_plan.created_at)


def _stored_manifests(store: InMemoryScenarioStore) -> int:
    return len(store._adaptive_run_trajectory_replay_manifests)


def _replay_surface(store: InMemoryScenarioStore, run_id: str, world_id: str) -> dict[str, object]:
    """The established service-touch surface plus the replay-manifest records."""
    surface = _surface(store, run_id, world_id)
    surface["replay_manifests"] = tuple(
        manifest.model_dump(mode="json")
        for manifest in store._adaptive_run_trajectory_replay_manifests.values()
    )
    return surface


def _assert_rejection(
    expected: type[BaseException],
    store: InMemoryScenarioStore,
    run_id: str,
    world_id: str,
    action: Callable[[], object],
) -> pytest.ExceptionInfo[BaseException]:
    """Require the typed error and prove the complete store surface is unchanged."""
    before = _replay_surface(store, run_id, world_id)
    with pytest.raises(expected) as excinfo:
        action()
    assert _replay_surface(store, run_id, world_id) == before
    assert excinfo.value.args
    return excinfo


def _assert_light_rejection(
    expected: type[BaseException],
    store: InMemoryScenarioStore,
    run_id: str,
    action: Callable[[], object],
) -> pytest.ExceptionInfo[BaseException]:
    """Require the typed error with no manifest write and no activity."""
    with pytest.raises(expected) as excinfo:
        action()
    assert _stored_manifests(store) == 0
    assert store.list_operational_activity(TENANT) == ()
    return excinfo


def _store_execution(
    store: InMemoryScenarioStore, run_id: str, execution: AdaptiveRunTrajectoryExecution
) -> None:
    store._adaptive_run_trajectory_executions[(TENANT, run_id)] = execution


def _finalize_tamper(execution: AdaptiveRunTrajectoryExecution) -> AdaptiveRunTrajectoryExecution:
    return execution.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(execution)}
    )


def _tampered_observation(
    execution: AdaptiveRunTrajectoryExecution,
) -> AdaptiveRunTrajectoryExecution:
    """A self-consistent observed-value tamper that passes the verified getter."""
    events = list(execution.observation_events)
    first = events[0]
    tampered = first.model_copy(
        update={"exposed_observation_value": (first.exposed_observation_value or 0) + 1000}
    )
    tampered = tampered.model_copy(
        update={"content_hash": runtime_observation_event_content_hash(tampered)}
    )
    events[0] = tampered
    return _finalize_tamper(execution.model_copy(update={"observation_events": tuple(events)}))


def _tampered_snapshot(execution: AdaptiveRunTrajectoryExecution) -> AdaptiveRunTrajectoryExecution:
    """A self-consistent policy-state budget tamper that passes the getter."""
    snapshots = list(execution.policy_state_snapshots)
    snapshots[0] = snapshots[0].model_copy(update={"remaining_global_switch_budget": 99})
    return _finalize_tamper(
        execution.model_copy(update={"policy_state_snapshots": tuple(snapshots)})
    )


def _tampered_switch(execution: AdaptiveRunTrajectoryExecution) -> AdaptiveRunTrajectoryExecution:
    """A self-consistent switch-budget tamper that passes the getter."""
    switches = list(execution.switch_events)
    first = switches[0]
    switches[0] = first.model_copy(
        update={
            "global_switch_budget_before": first.global_switch_budget_before - 1,
            "global_switch_budget_after": first.global_switch_budget_after - 1,
        }
    )
    return _finalize_tamper(execution.model_copy(update={"switch_events": tuple(switches)}))


def _tampered_trajectory(
    execution: AdaptiveRunTrajectoryExecution,
) -> AdaptiveRunTrajectoryExecution:
    """A self-consistent trajectory-state tamper that passes the getter."""
    outer = list(execution.trajectory_results_by_decision)
    inner = list(outer[0])
    result = inner[0]
    new_final = dict(result.final_state)
    for key, value in new_final.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            new_final[key] = value + 100
            break
    tampered = result.model_copy(
        update={"final_state": new_final, "final_state_hash": state_hash(new_final)}
    )
    attempts = list(tampered.attempts)
    attempts[-1] = attempts[-1].model_copy(update={"after_state_hash": state_hash(new_final)})
    tampered = tampered.model_copy(
        update={"attempts": tuple(attempts), "trace_hash": _trace_hash(tuple(attempts))}
    )
    tampered = tampered.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(tampered)}
    )
    inner[0] = tampered
    outer[0] = tuple(inner)
    return _finalize_tamper(
        execution.model_copy(update={"trajectory_results_by_decision": tuple(outer)})
    )


# ---------------------------------------------------------------------------
# A. Successful exact replay: absent bundle and present bundle
# ---------------------------------------------------------------------------


def test_replay_absent_bundle_success() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    assert execution.external_observation_input_bundle_id is None
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert type(manifest) is AdaptiveRunTrajectoryReplayManifest
    assert manifest == _expected_manifest(execution, run_plan)
    assert manifest.external_observation_input_bundle_id is None
    assert manifest.external_observation_input_bundle_content_hash is None
    assert _stored_manifests(store) == 1
    assert store.list_operational_activity(TENANT) == ()


def test_replay_present_bundle_success() -> None:
    env, store, run_id, run_plan, execution = _fixture(external=True)
    assert execution.external_observation_input_bundle_id is not None
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest == _expected_manifest(execution, run_plan)
    assert (
        manifest.external_observation_input_bundle_id
        == execution.external_observation_input_bundle_id
    )
    assert manifest.external_observation_input_bundle_content_hash == (
        execution.external_observation_input_bundle_content_hash
    )
    assert _stored_manifests(store) == 1


def test_manifest_identifier_provenance_and_hashes() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest.identifier == adaptive_run_trajectory_replay_manifest_identifier(
        run_id=execution.run_id, runtime_version=execution.runtime_version
    )
    assert manifest.identifier.startswith("adaptive-run-trajectory-replay-")
    assert manifest.adaptive_run_trajectory_execution_id == execution.identifier
    assert manifest.campaign_id == execution.campaign_id
    assert manifest.world_version_id == execution.world_version_id
    assert manifest.world_content_hash == execution.world_content_hash
    assert manifest.scenario_seed_id == execution.scenario_seed_id
    assert manifest.seed_content_hash == execution.seed_content_hash
    assert manifest.world_realization_id == execution.world_realization_id
    assert manifest.world_realization_content_hash == execution.world_realization_content_hash
    assert manifest.adaptive_policy_identifier == execution.adaptive_policy_identifier
    assert manifest.policy_id == execution.policy_id
    assert manifest.adaptive_policy_content_hash == execution.adaptive_policy_content_hash
    assert manifest.runtime_version == execution.runtime_version == "4.0.0"
    assert manifest.input_hash == execution.input_hash
    assert manifest.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
    assert manifest.expected_execution_hash == execution.content_hash
    assert manifest.recomputed_execution_hash == execution.content_hash
    assert manifest.replay_classification == "exact"
    assert manifest.replayed_at == run_plan.created_at
    assert manifest.content_hash == adaptive_run_trajectory_replay_manifest_content_hash(manifest)
    assert manifest.content_hash != "0" * 64


def test_independently_regenerated_execution_canonical_equality() -> None:
    env, store, run_id, run_plan, execution = _fixture(final_step=1)
    authorities = _rebuilt_authorities(store, env, run_id)
    regenerated = build_adaptive_run_trajectory_execution(
        store,
        authorities=authorities,
        catalogs=env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=len(execution.decision_events) - 1
        ),
    )
    assert canonical_json(regenerated.model_dump(mode="json")) == canonical_json(
        execution.model_dump(mode="json")
    )
    assert regenerated.content_hash == execution.content_hash
    assert regenerated == execution
    # The replayed manifest records exactly that regenerated hash.
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest.recomputed_execution_hash == regenerated.content_hash


def test_horizon_zero_and_multistep_switch() -> None:
    # Horizon 0: exactly one decision, no switch evidence.
    env, store, run_id, run_plan, execution = _fixture(final_step=0)
    assert len(execution.decision_events) == 1
    assert execution.switch_events == ()
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest == _expected_manifest(execution, run_plan)

    # Multi-step switch evidence: two decisions, one real switch at step 1,
    # and the cardinality-derived horizon regenerates the exact stored bytes.
    env, store, run_id, run_plan, execution = _fixture(final_step=1)
    assert len(execution.decision_events) == 2
    assert [switch.decision_step for switch in execution.switch_events] == [1]
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest == _expected_manifest(execution, run_plan)
    authorities = _rebuilt_authorities(store, env, run_id)
    regenerated = build_adaptive_run_trajectory_execution(
        store,
        authorities=authorities,
        catalogs=env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    assert regenerated == execution
    assert manifest.recomputed_execution_hash == execution.content_hash


def test_deterministic_across_byte_equivalent_independent_environments() -> None:
    env_a, store_a, run_id_a, _plan_a, _execution_a = _fixture()
    env_b, store_b, run_id_b, _plan_b, _execution_b = _fixture()
    manifest_a = replay_adaptive_run(store_a, tenant_id=TENANT, run_id=run_id_a)
    manifest_b = replay_adaptive_run(store_b, tenant_id=TENANT, run_id=run_id_b)
    assert canonical_json(manifest_a.model_dump(mode="json")) == canonical_json(
        manifest_b.model_dump(mode="json")
    )
    assert manifest_a.content_hash == manifest_b.content_hash
    assert manifest_a == manifest_b


# ---------------------------------------------------------------------------
# B. Idempotent second replay and existing-manifest behavior
# ---------------------------------------------------------------------------


def test_second_identical_replay_returns_existing_and_changes_nothing() -> None:
    env, store, run_id, run_plan, _execution = _fixture()
    first = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    before = _replay_surface(store, run_id, env.world_id)
    second = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert second == first
    assert type(second) is AdaptiveRunTrajectoryReplayManifest
    assert second.replayed_at == run_plan.created_at
    assert _replay_surface(store, run_id, env.world_id) == before
    assert _stored_manifests(store) == 1
    assert store.list_operational_activity(TENANT) == ()


def test_existing_identical_manifest_returned_without_write() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    expected = _expected_manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=expected
    )
    before = _replay_surface(store, run_id, env.world_id)
    returned = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert returned == expected
    assert _replay_surface(store, run_id, env.world_id) == before
    assert _stored_manifests(store) == 1


def test_corrupt_existing_manifest_rejected_never_overwritten_or_repaired() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_expected_manifest(execution, run_plan)
    )
    corrupted = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)].model_copy(
        update={"content_hash": "1" * 64}
    )
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = corrupted
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    # Never overwritten and never repaired.
    assert store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] == corrupted
    assert _stored_manifests(store) == 1


def test_differing_existing_manifest_rejected_never_overwritten() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    # A full-record manifestation of the same execution at a foreign replay
    # timestamp violates the recorded replay-time authority; the store
    # getter rejects it as the typed integrity error and the service never
    # overwrites or repairs it.
    differing = _expected_manifest(execution, run_plan).model_copy(
        update={"replayed_at": _OTHER_TIMESTAMP}
    )
    assert differing != _expected_manifest(execution, run_plan)
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = differing
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] == differing
    assert _stored_manifests(store) == 1


def test_success_writes_only_the_manifest() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    before = _replay_surface(store, run_id, env.world_id)
    assert before["replay_manifests"] == ()
    replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    after = _replay_surface(store, run_id, env.world_id)
    replay_manifests = after["replay_manifests"]
    assert isinstance(replay_manifests, tuple)
    assert len(replay_manifests) == 1
    after["replay_manifests"] = ()
    assert after == before
    assert store.list_operational_activity(TENANT) == ()


# ---------------------------------------------------------------------------
# C. Run rejection: PLANNED / RUNNING / FAILED / non-runtime-4 / missing /
#    foreign / event-hash
# ---------------------------------------------------------------------------


def test_planned_run_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.PLANNED})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_running_run_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.RUNNING})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_failed_run_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.FAILED})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_recorded_event_hash_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"event_hash": "1" * 64})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_non_runtime4_run_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"runtime_version": "3.0.0"})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_run_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id="missing-run"),
    )


def test_foreign_run_rejected_atomically() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=FOREIGN_TENANT, run_id=run_id),
    )


# ---------------------------------------------------------------------------
# D. Missing / corrupt stored authorities
# ---------------------------------------------------------------------------


def test_missing_stored_execution_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    store._adaptive_run_trajectory_executions.clear()
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_run_status_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._run_statuses[(TENANT, run_id)]
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_run_plans_rejected() -> None:
    env, store, run_id, run_plan, _execution = _fixture()
    del store._run_plans[(TENANT, run_plan.campaign_id)]
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_campaign_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._campaigns[(TENANT, CAMPAIGN)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_campaign_status_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._campaign_statuses[(TENANT, CAMPAIGN)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_world_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._worlds[(TENANT, env.world_id)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_scenario_seed_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    store._campaigns[(TENANT, CAMPAIGN)] = campaign.model_copy(update={"seed_ensemble": ()})
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_and_corrupt_policy_rejected() -> None:
    # Missing policy.
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._adaptive_policies[(TENANT, CAMPAIGN)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    # Corrupt (forged) policy.
    env, store, run_id, _run_plan, _execution = _fixture()
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    forged = policy.model_copy(update={"policy_id": "forged"})
    store._adaptive_policies[(TENANT, CAMPAIGN)] = forged
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._adaptive_policies[(TENANT, CAMPAIGN)] == forged


def test_missing_and_corrupt_declaration_rejected() -> None:
    # Missing bound declaration.
    env, store, run_id, _run_plan, _execution = _fixture()
    key = (TENANT, "scenario-1", env.world_id, "obs-level")
    del store._runtime_observation_declarations[key]
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    # Corrupt (forged) bound declaration.
    env, store, run_id, _run_plan, _execution = _fixture()
    declaration = store.get_runtime_observation_declaration(
        TENANT, "scenario-1", env.world_id, "obs-level"
    )
    forged = declaration.model_copy(update={"observation_id": "forged"})
    store._runtime_observation_declarations[key] = forged
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._runtime_observation_declarations[key] == forged


def test_missing_and_corrupt_action_plans_rejected() -> None:
    # Missing action-plan collection.
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._strategy_trajectory_plans[(TENANT, CAMPAIGN)]
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    # Corrupt (mismatched) action plans.
    env, store, run_id, _run_plan, _execution = _fixture()
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    forged_plans = tuple(plan.model_copy(update={"state_model_id": "sm-forged"}) for plan in plans)
    store._strategy_trajectory_plans[(TENANT, CAMPAIGN)] = forged_plans
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._strategy_trajectory_plans[(TENANT, CAMPAIGN)] == forged_plans


def test_missing_and_corrupt_external_bundle_rejected() -> None:
    # Missing bundle on a present-bundle execution.
    env, store, run_id, _run_plan, _execution = _fixture(external=True)
    del store._external_observation_input_bundles[(TENANT, CAMPAIGN, SEED_ID)]
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    # Corrupt bundle: the store getter rejects the forged record.
    env, store, run_id, _run_plan, _execution = _fixture(external=True)
    bundle = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID
    )
    forged = bundle.model_copy(update={"content_hash": _H64_ALT})
    store._external_observation_input_bundles[(TENANT, CAMPAIGN, SEED_ID)] = forged
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._external_observation_input_bundles[(TENANT, CAMPAIGN, SEED_ID)] == forged


def test_corrupt_run_status_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"input_hash": "6" * 64})
    store.put_run_status(TENANT, run_id, drifted)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_corrupt_run_plan_rejected() -> None:
    env, store, run_id, run_plan, _execution = _fixture()
    tampered = run_plan.model_copy(update={"input_hash": "5" * 64})
    store.put_run_plans(TENANT, run_plan.campaign_id, (tampered,))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_corrupt_world_manifest_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    manifest = store.get_manifest(TENANT, env.world_id)
    # Corrupt a real covered manifest authority field - the recorded
    # world reference - while retaining the original store key, so the
    # next verified read fails verify_world_snapshot and the forged
    # stored record is never repaired.
    forged = manifest.model_copy(update={"world_version_id": "world-forged"})
    store._manifests[(TENANT, env.world_id)] = forged
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._manifests[(TENANT, env.world_id)] == forged


def test_corrupt_stored_execution_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    tampered = execution.model_copy(update={"input_hash": "c" * 64})
    _store_execution(store, run_id, tampered)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert store._adaptive_run_trajectory_executions[(TENANT, run_id)] == tampered


# ---------------------------------------------------------------------------
# E. Stored-versus-regenerated mismatch (self-consistent tamperings)
# ---------------------------------------------------------------------------


def test_observation_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(store, run_id, _tampered_observation(execution))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_policy_state_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture(final_step=1)
    _store_execution(store, run_id, _tampered_snapshot(execution))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_decision_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture(final_step=1)
    decisions = list(execution.decision_events)
    first = decisions[0]
    decisions[0] = first.model_copy(
        update={"current_action_id": "act-2", "selected_action_id": "act-2"}
    )
    tampered = _finalize_tamper(execution.model_copy(update={"decision_events": tuple(decisions)}))
    _store_execution(store, run_id, tampered)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_switch_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture(final_step=1)
    _store_execution(store, run_id, _tampered_switch(execution))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_trajectory_state_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(store, run_id, _tampered_trajectory(execution))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_input_hash_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(store, run_id, execution.model_copy(update={"input_hash": "c" * 64}))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_plan_set_provenance_mismatch_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(
        store, run_id, execution.model_copy(update={"trajectory_plan_set_hash": "d" * 64})
    )
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


# ---------------------------------------------------------------------------
# F. Wrong-type / subclass / model_construct adversaries
# ---------------------------------------------------------------------------


class _ExecutionSubclass(AdaptiveRunTrajectoryExecution):
    """A validator-passing subclass forgery for the exact-type boundary."""


def _reject_bad_tenant(
    store: InMemoryScenarioStore,
    run_id: str,
    bad: Any,
) -> None:
    """Require the safe validation error for one invalid tenant identifier."""
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=bad, run_id=run_id),
    )


def _reject_bad_run_id(
    store: InMemoryScenarioStore,
    run_id: str,
    bad: Any,
) -> None:
    """Require the safe validation error for one invalid run identifier."""
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=bad),
    )


def test_wrong_tenant_id_types_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    invalid: Any = None
    for value in (invalid, 123, False, "", b"tenant"):
        _reject_bad_tenant(store, run_id, value)


def test_wrong_run_id_types_rejected() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    for value in (None, 123, False, "", b"run"):
        _reject_bad_run_id(store, run_id, value)


def test_subclass_execution_forgery_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    forged = _ExecutionSubclass.model_validate(execution.model_dump(mode="python"))
    _store_execution(store, run_id, forged)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_model_construct_execution_forgery_rejected() -> None:
    env, store, run_id, _run_plan, execution = _fixture()
    payload: dict[str, Any] = execution.model_dump(mode="python")
    payload["input_hash"] = "c" * 64
    forged = AdaptiveRunTrajectoryExecution.model_construct(**payload)
    _store_execution(store, run_id, forged)
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


# ---------------------------------------------------------------------------
# G. Safe public messages, atomicity, and store fingerprints
# ---------------------------------------------------------------------------


def test_public_error_messages_leak_nothing() -> None:
    env, store, run_id, run_plan, execution = _fixture()
    secrets = (
        execution.identifier,
        execution.tenant_id,
        execution.run_id,
        execution.campaign_id,
        execution.input_hash,
        execution.content_hash,
        execution.trajectory_plan_set_hash,
        execution.world_content_hash,
        execution.seed_content_hash,
        _H64_ALT,
        "run-other",
        "missing-run",
        "tenant-2",
        "act-1",
        "act-2",
        "obs-level",
        "channel-1",
        _OTHER_TIMESTAMP.isoformat(),
    )
    observed: list[str] = []

    def _capture(action: Callable[[], object]) -> None:
        try:
            action()
        except (
            AdaptiveRunTrajectoryReplayManifestAlreadyExistsError,
            AdaptiveRunTrajectoryReplayManifestNotFoundError,
            AdaptiveRunTrajectoryReplayManifestValidationError,
            AdaptiveRunTrajectoryReplayManifestIntegrityError,
        ) as exc:
            observed.append(str(exc))
        else:
            raise AssertionError(f"expected a typed replay rejection from {action}")

    _capture(lambda: replay_adaptive_run(store, tenant_id=FOREIGN_TENANT, run_id=run_id))
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id="missing-run"))
    invalid: Any = None
    _capture(lambda: replay_adaptive_run(store, tenant_id=invalid, run_id=run_id))
    empty: Any = ""
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=empty))
    store.put_run_status(
        TENANT,
        run_id,
        store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.RUNNING}),
    )
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id))
    store.put_run_status(
        TENANT,
        run_id,
        store.get_run_status(TENANT, run_id).model_copy(
            update={"state": RunState.COMPLETE, "event_hash": None}
        ),
    )
    _store_execution(store, run_id, execution.model_copy(update={"input_hash": "c" * 64}))
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id))
    _store_execution(store, run_id, _tampered_observation(execution))
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id))
    _store_execution(store, run_id, execution)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_expected_manifest(execution, run_plan)
    )
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = (
        store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)].model_copy(
            update={"content_hash": "1" * 64}
        )
    )
    _capture(lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id))

    assert all(message.strip() for message in observed)
    for message in observed:
        for secret in secrets:
            assert secret not in message


def test_every_failure_class_is_atomic_without_activity() -> None:
    # Corrupt stored execution.
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(store, run_id, execution.model_copy(update={"input_hash": "c" * 64}))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )

    # Observation mismatch (self-consistent tamper).
    env, store, run_id, _run_plan, execution = _fixture()
    _store_execution(store, run_id, _tampered_observation(execution))
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )

    # RUNNING status.
    env, store, run_id, _run_plan, execution = _fixture()
    store.put_run_status(
        TENANT,
        run_id,
        store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.RUNNING}),
    )
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )

    # Corrupt run status.
    env, store, run_id, _run_plan, execution = _fixture()
    store.put_run_status(
        TENANT,
        run_id,
        store.get_run_status(TENANT, run_id).model_copy(update={"input_hash": "6" * 64}),
    )
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )

    # Foreign run.
    env, store, run_id, _run_plan, execution = _fixture()
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=FOREIGN_TENANT, run_id=run_id),
    )

    # Corrupt stored replay manifest (after a successful write).
    env, store, run_id, _run_plan, execution = _fixture()
    replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = (
        store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)].model_copy(
            update={"content_hash": "1" * 64}
        )
    )
    _assert_rejection(
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
        store,
        run_id,
        env.world_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )


def test_missing_authority_failures_are_atomic_and_never_repaired() -> None:
    # Missing declaration: no write, no activity, authority stays missing.
    env, store, run_id, _run_plan, _execution = _fixture()
    key = (TENANT, "scenario-1", env.world_id, "obs-level")
    del store._runtime_observation_declarations[key]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert key not in store._runtime_observation_declarations

    # Missing external bundle on a present-bundle execution.
    env, store, run_id, _run_plan, _execution = _fixture(external=True)
    del store._external_observation_input_bundles[(TENANT, CAMPAIGN, SEED_ID)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert (TENANT, CAMPAIGN, SEED_ID) not in store._external_observation_input_bundles

    # Missing run status: the recorded status stays absent.
    env, store, run_id, _run_plan, _execution = _fixture()
    del store._run_statuses[(TENANT, run_id)]
    _assert_light_rejection(
        AdaptiveRunTrajectoryReplayManifestValidationError,
        store,
        run_id,
        lambda: replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id),
    )
    assert (TENANT, run_id) not in store._run_statuses


# ---------------------------------------------------------------------------
# H. Historical runtime-2 / runtime-3 behavior unchanged
# ---------------------------------------------------------------------------


def test_runtime2_runtime3_replay_store_behavior_unchanged() -> None:
    env, store, run_id, _run_plan, _execution = _fixture()
    r2 = _runtime2_manifest()
    store.put_run_trajectory_replay_manifest(TENANT, "run-r2", r2)
    r3 = _runtime3_manifest()
    store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", r3)
    manifest = replay_adaptive_run(store, tenant_id=TENANT, run_id=run_id)
    assert manifest.run_id == run_id
    # Runtime-2 behavior unchanged: identical rewrite idempotent, conflict
    # rejected without overwriting, foreign lookup indistinguishable.
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == r2
    store.put_run_trajectory_replay_manifest(TENANT, "run-r2", r2)
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == r2
    with pytest.raises(RunTrajectoryReplayManifestConflictError):
        store.put_run_trajectory_replay_manifest(
            TENANT, "run-r2", r2.model_copy(update={"input_hash": "9" * 64})
        )
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == r2
    with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
        store.get_run_trajectory_replay_manifest(FOREIGN_TENANT, "run-r2")
    # Runtime-3 behavior unchanged.
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == r3
    store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", r3)
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == r3
    with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
        store.put_realization_run_trajectory_replay_manifest(
            TENANT, "run-r3", r3.model_copy(update={"input_hash": "9" * 64})
        )
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == r3
    with pytest.raises(RealizationRunTrajectoryReplayManifestNotFoundError):
        store.get_realization_run_trajectory_replay_manifest(FOREIGN_TENANT, "run-r3")
    # Separate collections: the runtime-4 surface never sees the historical
    # records, and the runtime-2/runtime-3 records were not altered.
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id="run-r2")
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id="run-r3")


# ---------------------------------------------------------------------------
# I. Source and architecture boundaries
# ---------------------------------------------------------------------------


def _service_source() -> str:
    return inspect.getsource(service_module)


def _service_tree() -> ast.Module:
    return ast.parse(_service_source())


def test_exactly_one_builder_call_and_no_execute_adaptive_run() -> None:
    tree = _service_tree()
    builder_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_adaptive_run_trajectory_execution"
    ]
    assert len(builder_calls) == 1
    keywords = {keyword.arg for keyword in builder_calls[0].keywords}
    assert keywords == {"authorities", "catalogs", "draft"}
    name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "execute_adaptive_run" not in name_ids


def test_stored_nested_evidence_never_passed_as_replay_input() -> None:
    tree = _service_tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "replay_adaptive_run"
    )
    accesses = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "execution"
    ]
    accessed = {node.attr for node in accesses}
    allowed = {
        "tenant_id",
        "run_id",
        "campaign_id",
        "identifier",
        "world_version_id",
        "world_content_hash",
        "scenario_seed_id",
        "seed_content_hash",
        "world_realization_id",
        "world_realization_content_hash",
        "adaptive_policy_identifier",
        "policy_id",
        "adaptive_policy_content_hash",
        "external_observation_input_bundle_id",
        "external_observation_input_bundle_content_hash",
        "runtime_version",
        "input_hash",
        "trajectory_plan_set_hash",
        "content_hash",
        "decision_events",
        "model_dump",
    }
    assert accessed <= allowed
    # ``decision_events`` appears exactly once, as the pure cardinality
    # horizon source inside a single len(...) call - never as builder input.
    len_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"
    ]
    assert len(len_calls) == 1
    argument = len_calls[0].args[0]
    assert (
        isinstance(argument, ast.Attribute)
        and isinstance(argument.value, ast.Name)
        and argument.value.id == "execution"
        and argument.attr == "decision_events"
    )
    decision_accesses = [node for node in accesses if node.attr == "decision_events"]
    assert len(decision_accesses) == 1
    # The manifest carries no nested evidence by contract.
    assert not {
        "observation_events",
        "policy_state_snapshots",
        "decision_events",
        "switch_events",
        "trajectory_results_by_decision",
    }.intersection(set(AdaptiveRunTrajectoryReplayManifest.model_fields))


def test_no_forbidden_surfaces_or_imports() -> None:
    tree = _service_tree()
    # The only store surfaces used are the verified execution getter, the
    # established private authority loaders, and the manifest get/put.
    store_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "store"
    ]
    store_attrs = {node.func.attr for node in store_calls if isinstance(node.func, ast.Attribute)}
    assert store_attrs <= {
        "get_adaptive_run_trajectory_execution",
        "get_adaptive_run_trajectory_replay_manifest",
        "put_adaptive_run_trajectory_replay_manifest",
        "_adaptive_run_plan_authority",
        "_adaptive_run_authorities",
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (
        attributes
        & {
            "put_adaptive_run_trajectory_execution",
            "put_run_status",
            "put_run_events",
            "put_input_integrity_manifest",
            "put_replay_manifest",
            "record_operational_activity",
            "update_campaign_status",
            "put_world",
            "put_campaign",
            "put_run_plans",
            "put_adaptive_policy",
            "delete",
            "upsert",
        }
    )
    roots: set[str] = set()
    kalhas_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("kalhas"):
                kalhas_modules.add(node.module)
    assert roots <= {"__future__", "typing", "kalhas"}
    forbidden_roots = {
        "datetime",
        "time",
        "random",
        "uuid",
        "os",
        "sys",
        "socket",
        "urllib",
        "requests",
        "subprocess",
        "hashlib",
        "pathlib",
        "json",
        "importlib",
    }
    assert not (roots & forbidden_roots)
    assert all(
        module.startswith("kalhas.application.") or module.startswith("kalhas.contracts.v1.")
        for module in kalhas_modules
    )
    assert "adapters" not in _service_source().lower()
    name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (
        name_ids & {"datetime", "time", "uuid", "random", "now", "utcnow", "monotonic", "time_ns"}
    )


def test_exact_public_surface_and_signature() -> None:
    assert service_module.__all__ == ["replay_adaptive_run"]
    signature = inspect.signature(replay_adaptive_run)
    parameters = list(signature.parameters.values())
    assert [parameter.name for parameter in parameters] == ["store", "tenant_id", "run_id"]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])
    assert not any(
        parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for parameter in parameters
    )


def test_import_smoke() -> None:
    import kalhas.application.adaptive_trajectory_replay_errors as errors_module
    import kalhas.application.adaptive_trajectory_replay_identity as identity_module
    import kalhas.application.adaptive_trajectory_replay_integrity as integrity_module

    assert callable(replay_adaptive_run)
    assert callable(identity_module.adaptive_run_trajectory_replay_manifest_identifier)
    assert callable(integrity_module.verify_adaptive_run_trajectory_replay_manifest_record)
    assert set(service_module.__all__) == {"replay_adaptive_run"}
    assert isinstance(errors_module.AdaptiveRunTrajectoryReplayManifestValidationError, type)
