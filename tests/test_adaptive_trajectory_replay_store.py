"""H28-S07B1B immutable persistence authority proofs for the runtime-4 replay manifest.

Real runtime-4 executions (built by the real service through the real
store, then re-verified with the established execution authority) and
real ``AdaptiveRunTrajectoryReplayManifest`` records (the same
``_manifest_for`` construction the B1A identity/integrity tests verify)
are used to prove the canonical
``put_adaptive_run_trajectory_replay_manifest`` /
``get_adaptive_run_trajectory_replay_manifest`` flow end to end against
independently re-derived authority: valid absent-bundle and
present-bundle persistence, deep defensive-copy isolation, immutability
(every second write raises the typed ``AlreadyExists`` error and never
overwrites), exact-type/subclass/``model_construct`` forgery rejection,
key-ownership enforcement, the parametrized rejection of every
identity/content/provenance mismatch, expected/recomputed execution-hash
mismatch, replay-timestamp mismatch, missing/corrupt stored execution,
missing/corrupt run plan and run status, corrupt-stored-manifest
rejection without repair, non-leaking typed messages, zero activity and
full atomicity for every failure, the absence of any
list/update/delete/upsert surface, and the unchanged runtime-2/runtime-3
replay-manifest store behavior. No mocks, monkeypatch, skip, xfail,
noqa, or type-ignore appear in this module; no replay computation,
builder, clock, RNG, provider, or network surface is invoked.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest
from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestAlreadyExistsError,
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
    AdaptiveRunTrajectoryReplayManifestNotFoundError,
    AdaptiveRunTrajectoryReplayManifestValidationError,
)
from kalhas.application.adaptive_trajectory_replay_identity import (
    adaptive_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.domain_errors import (
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryReplayManifest

from tests.phase4_helpers import TENANT
from tests.test_adaptive_run_execution_builder import _build_env, _build_env_external
from tests.test_adaptive_trajectory_replay_identity_integrity import (
    _manifest_for,
    _verified_execution,
)

#: A distinct tenant that never owns any fixture authority.
FOREIGN_TENANT = "tenant-2"

#: A distinct, valid 64-lowercase-hex digest used to displace any real hash.
_H64_ALT = "f" * 64

#: A distinct valid replay-timestamp authority used only for mismatch proofs;
#: the recorded RunPlan creation time is the authoritative replay timestamp.
_OTHER_TIMESTAMP = datetime(2026, 2, 2, 8, 0, 0, tzinfo=UTC)

#: Deterministic replay-manifest identifier of a hypothetical "run-other"
#: run, so a run-identity mismatch can pass identity verification and fail
#: exactly at the record field comparison.
_RUN_OTHER_IDENTIFIER = adaptive_run_trajectory_replay_manifest_identifier(
    run_id="run-other", runtime_version="4.0.0"
)


# ---------------------------------------------------------------------------
# Fixture helpers (real service, real store, established B1A construction)
# ---------------------------------------------------------------------------


def _fixture(
    *,
    external: bool = False,
) -> tuple[InMemoryScenarioStore, str, RunPlan, AdaptiveRunTrajectoryExecution]:
    """One real runtime-4 run with its verified execution already stored.

    ``execute_adaptive_run`` persists the execution through the canonical
    store putter and records the COMPLETE run status, so the returned
    store already contains every authority the replay-manifest store
    reverifies. ``external=True`` uses the real external-bundle
    environment, so the execution and manifest carry a present bundle
    pair.
    """
    env = _build_env_external() if external else _build_env()
    return _verified_execution(env, external=external)


def _manifest(
    execution: AdaptiveRunTrajectoryExecution,
    run_plan: RunPlan,
    **overrides: object,
) -> AdaptiveRunTrajectoryReplayManifest:
    """The real manifest attesting ``execution`` at the recorded plan time."""
    return _manifest_for(execution, replayed_at=run_plan.created_at, **overrides)


def _stored_manifests(store: InMemoryScenarioStore) -> int:
    return len(store._adaptive_run_trajectory_replay_manifests)


# ---------------------------------------------------------------------------
# Group A - valid persistence: absent bundle and present bundle
# ---------------------------------------------------------------------------


def test_absent_bundle_put_then_get_round_trip() -> None:
    store, run_id, run_plan, execution = _fixture()
    assert execution.external_observation_input_bundle_id is None
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    got = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert got == manifest
    assert type(got) is AdaptiveRunTrajectoryReplayManifest
    assert _stored_manifests(store) == 1


def test_present_bundle_put_then_get_round_trip() -> None:
    store, run_id, run_plan, execution = _fixture(external=True)
    assert execution.external_observation_input_bundle_id is not None
    assert execution.external_observation_input_bundle_content_hash is not None
    manifest = _manifest(execution, run_plan)
    assert manifest.external_observation_input_bundle_id is not None
    assert manifest.external_observation_input_bundle_content_hash is not None
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    got = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert got == manifest
    assert (
        got.external_observation_input_bundle_id == execution.external_observation_input_bundle_id
    )
    assert got.external_observation_input_bundle_content_hash == (
        execution.external_observation_input_bundle_content_hash
    )


def test_manifest_fields_record_verified_authority() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    assert manifest.replayed_at == run_plan.created_at
    assert manifest.adaptive_run_trajectory_execution_id == execution.identifier
    assert manifest.expected_execution_hash == execution.content_hash
    assert manifest.recomputed_execution_hash == execution.content_hash
    assert manifest.replay_classification == "exact"


def test_retrieved_manifest_is_a_fresh_defensive_copy() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    first = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    second = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert first == second == manifest
    assert first is not second
    assert first is not manifest
    assert first is not store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)]


def test_put_stores_a_detached_copy_and_leaves_input_unchanged() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    before = manifest.model_dump(mode="json")
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    assert manifest.model_dump(mode="json") == before
    stored = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)]
    assert stored == manifest
    assert stored is not manifest


def test_put_and_get_produce_zero_activity() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


# ---------------------------------------------------------------------------
# Group B - immutability: every second write raises AlreadyExists
# ---------------------------------------------------------------------------


def test_identical_second_write_rejected_and_original_preserved() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestAlreadyExistsError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    got = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert got == manifest
    assert _stored_manifests(store) == 1


def test_equal_but_distinct_second_write_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    equal_copy = _manifest(execution, run_plan)
    assert equal_copy == manifest
    assert equal_copy is not manifest
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestAlreadyExistsError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=equal_copy
        )
    assert _stored_manifests(store) == 1


def test_conflicting_second_write_rejected_and_original_preserved() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    conflicting = _manifest(execution, run_plan, input_hash=_H64_ALT)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestAlreadyExistsError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=conflicting
        )
    got = store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert got == manifest
    assert got != conflicting


# ---------------------------------------------------------------------------
# Group C - ownership and non-leakage: missing and foreign are indistinguishable
# ---------------------------------------------------------------------------


def test_missing_manifest_lookup_raises_typed_not_found() -> None:
    store, run_id, _run_plan, _execution = _fixture()
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id="missing-run")


def test_foreign_tenant_lookup_indistinguishable_from_missing() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=FOREIGN_TENANT, run_id=run_id)


def test_foreign_tenant_put_rejected_by_key_ownership() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=FOREIGN_TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_wrong_run_key_put_rejected_by_key_ownership() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id="run-other", manifest=manifest
        )
    assert _stored_manifests(store) == 0


# ---------------------------------------------------------------------------
# Group D - exact-type / subclass / model_construct rejection
# ---------------------------------------------------------------------------


def test_wrong_type_dict_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    put: Callable[..., object] = store.put_adaptive_run_trajectory_replay_manifest
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        put(tenant_id=TENANT, run_id=run_id, manifest={"run_id": "run-1"})
    assert _stored_manifests(store) == 0


def test_wrong_type_string_rejected() -> None:
    store, run_id, _run_plan, _execution = _fixture()
    put: Callable[..., object] = store.put_adaptive_run_trajectory_replay_manifest
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        put(tenant_id=TENANT, run_id=run_id, manifest="not-a-manifest")
    assert _stored_manifests(store) == 0


def test_subclass_forgery_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)

    class _Sub(AdaptiveRunTrajectoryReplayManifest):
        pass

    forged = _Sub.model_construct(**manifest.model_dump(mode="python"))
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert _stored_manifests(store) == 0


def test_model_construct_invalid_value_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    dump = manifest.model_dump(mode="python")
    dump["policy_id"] = 42
    forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert _stored_manifests(store) == 0


def test_model_construct_missing_required_field_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    dump = manifest.model_dump(mode="python")
    del dump["content_hash"]
    forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert _stored_manifests(store) == 0


def test_wrong_runtime_literal_model_construct_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    dump = manifest.model_dump(mode="python")
    dump["runtime_version"] = "5.0.0"
    forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert _stored_manifests(store) == 0


def test_wrong_classification_model_construct_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
    dump = manifest.model_dump(mode="python")
    dump["replay_classification"] = "approximate"
    forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert _stored_manifests(store) == 0


# ---------------------------------------------------------------------------
# Group E - every identity / content / provenance mismatch is rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"campaign_id": "campaign-other"}, "manifest campaign mismatch"),
        (
            {"adaptive_run_trajectory_execution_id": "execution-other"},
            "manifest execution reference mismatch",
        ),
        ({"world_version_id": "world-other"}, "manifest world identity mismatch"),
        ({"world_content_hash": _H64_ALT}, "manifest world content hash mismatch"),
        ({"scenario_seed_id": "seed-other"}, "manifest scenario seed mismatch"),
        ({"seed_content_hash": _H64_ALT}, "manifest seed content hash mismatch"),
        (
            {"world_realization_id": "realization-other"},
            "manifest realization identity mismatch",
        ),
        (
            {"world_realization_content_hash": _H64_ALT},
            "manifest realization content hash mismatch",
        ),
        (
            {"adaptive_policy_identifier": "policy-other"},
            "manifest policy identity mismatch",
        ),
        ({"policy_id": "policy-id-other"}, "manifest policy identifier mismatch"),
        (
            {"adaptive_policy_content_hash": _H64_ALT},
            "manifest policy content hash mismatch",
        ),
        ({"input_hash": _H64_ALT}, "manifest input hash mismatch"),
        ({"trajectory_plan_set_hash": _H64_ALT}, "manifest plan set hash mismatch"),
    ],
)
def test_every_provenance_field_mismatch_rejected(
    overrides: dict[str, object], expected_reason: str
) -> None:
    store, run_id, run_plan, execution = _fixture()
    forged = _manifest(execution, run_plan, **overrides)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == expected_reason
    assert _stored_manifests(store) == 0


def test_expected_execution_hash_mismatch_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    forged = _manifest(execution, run_plan, expected_execution_hash=_H64_ALT)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == "manifest expected execution hash mismatch"
    assert _stored_manifests(store) == 0


def test_recomputed_execution_hash_mismatch_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    forged = _manifest(execution, run_plan, recomputed_execution_hash=_H64_ALT)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == "manifest recomputed execution hash mismatch"
    assert _stored_manifests(store) == 0


def test_replayed_at_mismatch_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    forged = _manifest_for(execution, replayed_at=_OTHER_TIMESTAMP)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == "manifest replayed at mismatch"
    assert _stored_manifests(store) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"external_observation_input_bundle_id": "bundle-other"},
        {"external_observation_input_bundle_content_hash": _H64_ALT},
    ],
)
def test_present_bundle_pair_mismatch_rejected(overrides: dict[str, object]) -> None:
    store, run_id, run_plan, execution = _fixture(external=True)
    forged = _manifest(execution, run_plan, **overrides)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == "manifest external bundle mismatch"
    assert _stored_manifests(store) == 0


def test_absent_manifest_claiming_a_bundle_rejected() -> None:
    store, run_id, run_plan, execution = _fixture()
    forged = _manifest(
        execution,
        run_plan,
        external_observation_input_bundle_id="bundle-other",
        external_observation_input_bundle_content_hash=_H64_ALT,
    )
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=forged
        )
    assert excinfo.value.reason == "manifest external bundle mismatch"
    assert _stored_manifests(store) == 0


# ---------------------------------------------------------------------------
# Group F - missing / corrupt stored execution
# ---------------------------------------------------------------------------


def test_missing_stored_execution_put_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    store._adaptive_run_trajectory_executions.clear()
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_missing_stored_execution_get_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    store._adaptive_run_trajectory_executions.clear()
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


def test_corrupt_stored_execution_put_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    tampered = execution.model_copy(update={"input_hash": "c" * 64})
    store._adaptive_run_trajectory_executions[(TENANT, run_id)] = tampered
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_corrupt_stored_execution_get_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    tampered = execution.model_copy(update={"input_hash": "c" * 64})
    store._adaptive_run_trajectory_executions[(TENANT, run_id)] = tampered
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


# ---------------------------------------------------------------------------
# Group G - missing / corrupt run plan and run status
# ---------------------------------------------------------------------------


def test_missing_run_status_put_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    del store._run_statuses[(TENANT, run_id)]
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_missing_run_status_get_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    del store._run_statuses[(TENANT, run_id)]
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


def test_corrupt_run_status_put_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"input_hash": "6" * 64})
    store.put_run_status(TENANT, run_id, drifted)
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_corrupt_run_status_get_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    drifted = store.get_run_status(TENANT, run_id).model_copy(update={"input_hash": "6" * 64})
    store.put_run_status(TENANT, run_id, drifted)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


def test_missing_run_plans_put_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    del store._run_plans[(TENANT, run_plan.campaign_id)]
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_missing_run_plans_get_converts_to_typed_validation() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    del store._run_plans[(TENANT, run_plan.campaign_id)]
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestValidationError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


def test_corrupt_run_plan_put_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    tampered = run_plan.model_copy(update={"input_hash": "5" * 64})
    store.put_run_plans(TENANT, run_plan.campaign_id, (tampered,))
    manifest = _manifest(execution, run_plan)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    assert _stored_manifests(store) == 0


def test_corrupt_run_plan_get_converts_to_typed_integrity() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    tampered = run_plan.model_copy(update={"input_hash": "5" * 64})
    store.put_run_plans(TENANT, run_plan.campaign_id, (tampered,))
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)


# ---------------------------------------------------------------------------
# Group H - corrupt stored replay manifest: rejected on get, never repaired
# ---------------------------------------------------------------------------


def test_corrupt_stored_content_hash_rejected_on_get_never_repaired() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    corrupted = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)].model_copy(
        update={"content_hash": "1" * 64}
    )
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = corrupted
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    stored = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)]
    assert stored == corrupted
    assert stored != _manifest(execution, run_plan)
    assert _stored_manifests(store) == 1


def test_corrupt_stored_provenance_rejected_on_get_never_repaired() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    corrupted = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)].model_copy(
        update={"input_hash": "b" * 64}
    )
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = corrupted
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    stored = store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)]
    assert stored == corrupted
    assert _stored_manifests(store) == 1


def test_corrupt_stored_wrong_type_rejected_on_get_never_repaired() -> None:
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    corrupt: object = "corrupt"
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = cast(
        AdaptiveRunTrajectoryReplayManifest, corrupt
    )
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    assert store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] == corrupt
    assert _stored_manifests(store) == 1


# ---------------------------------------------------------------------------
# Group I - typed safe messages never leak tenant / run / hash / value content
# ---------------------------------------------------------------------------


def test_public_error_messages_leak_nothing() -> None:
    store, run_id, run_plan, execution = _fixture()
    manifest = _manifest(execution, run_plan)
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
        manifest.identifier,
        manifest.content_hash,
        _H64_ALT,
        "run-other",
        "execution-other",
        "bundle-other",
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
            raise AssertionError(f"expected a typed rejection from {action}")

    _capture(
        lambda: store.get_adaptive_run_trajectory_replay_manifest(
            tenant_id=FOREIGN_TENANT, run_id=run_id
        )
    )
    _capture(
        lambda: store.get_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id="missing-run"
        )
    )
    _capture(
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id="run-other", manifest=manifest
        )
    )
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=manifest
    )
    _capture(
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=manifest
        )
    )
    forged = _manifest(execution, run_plan, input_hash=_H64_ALT)
    _capture(
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id="run-other", manifest=forged
        )
    )
    store._adaptive_run_trajectory_replay_manifests[(TENANT, run_id)] = manifest.model_copy(
        update={"content_hash": "1" * 64}
    )
    _capture(
        lambda: store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id)
    )
    assert all(message.strip() for message in observed)
    for message in observed:
        for secret in secrets:
            assert secret not in message


# ---------------------------------------------------------------------------
# Group J - atomicity: every failure writes nothing and records no activity
# ---------------------------------------------------------------------------


def _assert_rejection_is_atomic(
    store: InMemoryScenarioStore,
    run_id: str,
    action: Callable[[], object],
    expected: type[BaseException],
) -> None:
    manifests_before = dict(store._adaptive_run_trajectory_replay_manifests)
    statuses_before = dict(store._run_statuses)
    plans_before = dict(store._run_plans)
    executions_before = dict(store._adaptive_run_trajectory_executions)
    with pytest.raises(expected):
        action()
    assert dict(store._adaptive_run_trajectory_replay_manifests) == manifests_before
    assert dict(store._run_statuses) == statuses_before
    assert dict(store._run_plans) == plans_before
    assert dict(store._adaptive_run_trajectory_executions) == executions_before
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def test_every_failure_class_is_atomic_without_activity() -> None:
    # Missing execution on put.
    store, run_id, run_plan, execution = _fixture()
    store._adaptive_run_trajectory_executions.clear()
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
        ),
        AdaptiveRunTrajectoryReplayManifestValidationError,
    )
    assert _stored_manifests(store) == 0

    # Corrupt stored execution on put.
    store, run_id, run_plan, execution = _fixture()
    tampered = execution.model_copy(update={"input_hash": "c" * 64})
    store._adaptive_run_trajectory_executions[(TENANT, run_id)] = tampered
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
        ),
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
    )
    assert _stored_manifests(store) == 0

    # Provenance mismatch on put.
    store, run_id, run_plan, execution = _fixture()
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT,
            run_id=run_id,
            manifest=_manifest(execution, run_plan, input_hash=_H64_ALT),
        ),
        AdaptiveRunTrajectoryReplayManifestIntegrityError,
    )
    assert _stored_manifests(store) == 0

    # Key-ownership mismatch on put.
    store, run_id, run_plan, execution = _fixture()
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=FOREIGN_TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
        ),
        AdaptiveRunTrajectoryReplayManifestValidationError,
    )
    assert _stored_manifests(store) == 0

    # Missing run status on put.
    store, run_id, run_plan, execution = _fixture()
    del store._run_statuses[(TENANT, run_id)]
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.put_adaptive_run_trajectory_replay_manifest(
            tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
        ),
        AdaptiveRunTrajectoryReplayManifestValidationError,
    )
    assert _stored_manifests(store) == 0

    # Missing run plans on get.
    store, run_id, run_plan, execution = _fixture()
    store.put_adaptive_run_trajectory_replay_manifest(
        tenant_id=TENANT, run_id=run_id, manifest=_manifest(execution, run_plan)
    )
    del store._run_plans[(TENANT, run_plan.campaign_id)]
    _assert_rejection_is_atomic(
        store,
        run_id,
        lambda: store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id=run_id),
        AdaptiveRunTrajectoryReplayManifestValidationError,
    )
    assert _stored_manifests(store) == 1


# ---------------------------------------------------------------------------
# Group K - no list / update / delete / upsert surface
# ---------------------------------------------------------------------------


def test_no_mutation_surfaces_exist() -> None:
    assert not hasattr(InMemoryScenarioStore, "list_adaptive_run_trajectory_replay_manifests")
    assert not hasattr(InMemoryScenarioStore, "update_adaptive_run_trajectory_replay_manifest")
    assert not hasattr(InMemoryScenarioStore, "delete_adaptive_run_trajectory_replay_manifest")
    assert not hasattr(InMemoryScenarioStore, "upsert_adaptive_run_trajectory_replay_manifest")


# ---------------------------------------------------------------------------
# Group L - original runtime-2 / runtime-3 replay store behavior is intact
# ---------------------------------------------------------------------------


def _runtime2_manifest() -> RunTrajectoryReplayManifest:
    return RunTrajectoryReplayManifest(
        identifier="replay-r2",
        tenant_id=TENANT,
        run_id="run-r2",
        campaign_id="campaign-r2",
        run_trajectory_execution_id="execution-r2",
        world_version_id="world-r2",
        strategy_candidate_id="strategy-r2",
        scenario_seed_id="seed-r2",
        runtime_version="2.0.0",
        input_hash="1" * 64,
        trajectory_plan_set_hash="2" * 64,
        expected_execution_hash="3" * 64,
        recomputed_execution_hash="3" * 64,
        replay_classification="exact",
        replayed_at=datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC),
    )


def test_runtime2_replay_store_behavior_unchanged() -> None:
    store = InMemoryScenarioStore()
    manifest = _runtime2_manifest()
    store.put_run_trajectory_replay_manifest(TENANT, "run-r2", manifest)
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == manifest
    # Identical rewrite remains idempotent.
    store.put_run_trajectory_replay_manifest(TENANT, "run-r2", manifest)
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == manifest
    # Conflicting rewrite stays rejected without overwriting.
    conflicting = manifest.model_copy(update={"input_hash": "9" * 64})
    with pytest.raises(RunTrajectoryReplayManifestConflictError):
        store.put_run_trajectory_replay_manifest(TENANT, "run-r2", conflicting)
    assert store.get_run_trajectory_replay_manifest(TENANT, "run-r2") == manifest
    # Foreign lookup remains indistinguishable from missing.
    with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
        store.get_run_trajectory_replay_manifest(FOREIGN_TENANT, "run-r2")


def _runtime3_manifest() -> RealizationRunTrajectoryReplayManifest:
    return RealizationRunTrajectoryReplayManifest(
        identifier="replay-r3",
        tenant_id=TENANT,
        run_id="run-r3",
        campaign_id="campaign-r3",
        realization_run_trajectory_execution_id="execution-r3",
        realization_run_metric_observation_set_id="set-r3",
        world_version_id="world-r3",
        strategy_candidate_id="strategy-r3",
        scenario_seed_id="seed-r3",
        world_realization_id="realization-r3",
        world_realization_content_hash="4" * 64,
        runtime_version="3.0.0",
        input_hash="5" * 64,
        trajectory_plan_set_hash="6" * 64,
        expected_execution_hash="7" * 64,
        recomputed_execution_hash="7" * 64,
        expected_observation_set_hash="8" * 64,
        recomputed_observation_set_hash="8" * 64,
        replay_classification="exact",
        replayed_at=datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC),
        content_hash="a" * 64,
    )


def test_runtime3_replay_store_behavior_unchanged() -> None:
    store = InMemoryScenarioStore()
    manifest = _runtime3_manifest()
    store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", manifest)
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == manifest
    # Identical rewrite remains idempotent.
    store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", manifest)
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == manifest
    # Conflicting rewrite stays rejected without overwriting.
    conflicting = manifest.model_copy(update={"input_hash": "9" * 64})
    with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
        store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", conflicting)
    assert store.get_realization_run_trajectory_replay_manifest(TENANT, "run-r3") == manifest
    # Foreign lookup remains indistinguishable from missing.
    with pytest.raises(RealizationRunTrajectoryReplayManifestNotFoundError):
        store.get_realization_run_trajectory_replay_manifest(FOREIGN_TENANT, "run-r3")


def test_replay_runtimes_use_separate_collections() -> None:
    store = InMemoryScenarioStore()
    r2 = _runtime2_manifest()
    store.put_run_trajectory_replay_manifest(TENANT, "run-r2", r2)
    # The runtime-4 surface never sees the runtime-2 record.
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id="run-r2")
    r3 = _runtime3_manifest()
    store.put_realization_run_trajectory_replay_manifest(TENANT, "run-r3", r3)
    with pytest.raises(AdaptiveRunTrajectoryReplayManifestNotFoundError):
        store.get_adaptive_run_trajectory_replay_manifest(tenant_id=TENANT, run_id="run-r3")
