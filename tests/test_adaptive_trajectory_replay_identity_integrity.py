"""H28-S07B1A replay-manifest identity and full-record integrity proofs.

Real runtime-4 executions (built by the real service through the real
store, then re-verified with the established execution authority
verifier) are used to attest real ``AdaptiveRunTrajectoryReplayManifest``
instances. The proofs cover the deterministic replay-manifest identifier
and self-covering content hash, complete valid absent-bundle and
present-bundle manifestations, exact-type/subclass/``model_construct``
forgery rejection, malformed and wrong identifiers and content hashes,
the parametrized mismatch of every provenance field (including
expected/recomputed execution hashes independently, the external bundle
pair, runtime, classification, and the recorded replay timestamp), the
non-leaking typed failures, pure unchanged-input behavior, and the
absence of any store, builder, service, replay, network, RNG, or clock
surface in the three new modules. No mocks, monkeypatch, skip, xfail,
noqa, or type-ignore appear in this module.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from types import ModuleType

import kalhas.application.adaptive_trajectory_replay_errors as errors_module
import kalhas.application.adaptive_trajectory_replay_identity as identity_module
import kalhas.application.adaptive_trajectory_replay_integrity as integrity_module
import pytest
from kalhas.application.adaptive_run_execution_builder import (
    AdaptiveRunExecutionBuildDraft,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    verify_adaptive_run_trajectory_execution_authority,
)
from kalhas.application.adaptive_trajectory_replay_errors import (
    AdaptiveRunTrajectoryReplayManifestAlreadyExistsError,
    AdaptiveRunTrajectoryReplayManifestIntegrityError,
    AdaptiveRunTrajectoryReplayManifestNotFoundError,
    AdaptiveRunTrajectoryReplayManifestValidationError,
)
from kalhas.application.adaptive_trajectory_replay_identity import (
    RUNTIME_VERSION_LITERAL,
    adaptive_run_trajectory_replay_manifest_content_hash,
    adaptive_run_trajectory_replay_manifest_identifier,
    verify_adaptive_run_trajectory_replay_manifest_identity,
)
from kalhas.application.adaptive_trajectory_replay_integrity import (
    verify_adaptive_run_trajectory_replay_manifest_record,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from kalhas.contracts.v1.run_plan import RunPlan

from tests.phase4_helpers import TENANT
from tests.test_adaptive_run_execution_builder import (
    Env,
    _build_env,
    _build_env_external,
)
from tests.test_adaptive_run_execution_service import (
    _planned_run,
    _rebuilt_authorities,
    execute_adaptive_run,
)

#: A distinct, valid 64-lowercase-hex digest used to displace any real hash.
_H64_ALT = "f" * 64

#: The recorded replay timestamp authority is the recorded RunPlan creation
#: time; this is a distinct valid authority used only for mismatch proofs.
_OTHER_TIMESTAMP = datetime(2026, 2, 2, 8, 0, 0, tzinfo=UTC)

#: Deterministic replay-manifest identifier of a hypothetical "run-other"
#: run, so a run-identity mismatch can pass identity verification and fail
#: exactly at the run-identity field comparison.
_RUN_OTHER_IDENTIFIER = adaptive_run_trajectory_replay_manifest_identifier(
    run_id="run-other", runtime_version=RUNTIME_VERSION_LITERAL
)

#: The deterministic identifier prefix of the runtime-4 replay manifest.
_ID_PREFIX = "adaptive-run-trajectory-replay-"


def _verified_execution(
    env: Env, *, external: bool = False
) -> tuple[InMemoryScenarioStore, str, RunPlan, AdaptiveRunTrajectoryExecution]:
    """Build one real runtime-4 execution and re-verify it as the authority.

    Returns ``(store, run_id, run_plan, execution)`` where the execution is
    produced by the real service on a real environment and independently
    accepted by the established execution authority verifier, exactly the
    "verified AdaptiveRunTrajectoryExecution authority" the replay-manifest
    record verifier expects.
    """
    store, run_id, run_plan, _status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=env.bundle_draft if external else None
        ),
    )
    execution = result.execution
    authorities = _rebuilt_authorities(store, env, run_id)
    verify_adaptive_run_trajectory_execution_authority(execution, authorities=authorities)
    return store, run_id, run_plan, execution


def _manifest_for(
    execution: AdaptiveRunTrajectoryExecution,
    *,
    replayed_at: datetime,
    **overrides: object,
) -> AdaptiveRunTrajectoryReplayManifest:
    """The real replay manifest that truthfully attests one verified execution.

    Every provenance field is copied exactly from the verified execution;
    ``expected_execution_hash`` and ``recomputed_execution_hash`` both equal
    the execution content hash, the classification is exactly ``"exact"``,
    and ``replayed_at`` is the recorded replay timestamp authority. The
    self-covering content hash is computed over the complete payload with the
    established placeholder-then-``model_copy`` pattern and is never
    trusted as recorded.
    """
    payload: dict[str, object] = {
        "identifier": adaptive_run_trajectory_replay_manifest_identifier(
            run_id=execution.run_id,
            runtime_version=execution.runtime_version,
        ),
        "tenant_id": execution.tenant_id,
        "run_id": execution.run_id,
        "campaign_id": execution.campaign_id,
        "adaptive_run_trajectory_execution_id": execution.identifier,
        "world_version_id": execution.world_version_id,
        "world_content_hash": execution.world_content_hash,
        "scenario_seed_id": execution.scenario_seed_id,
        "seed_content_hash": execution.seed_content_hash,
        "world_realization_id": execution.world_realization_id,
        "world_realization_content_hash": execution.world_realization_content_hash,
        "adaptive_policy_identifier": execution.adaptive_policy_identifier,
        "policy_id": execution.policy_id,
        "adaptive_policy_content_hash": execution.adaptive_policy_content_hash,
        "external_observation_input_bundle_id": execution.external_observation_input_bundle_id,
        "external_observation_input_bundle_content_hash": (
            execution.external_observation_input_bundle_content_hash
        ),
        "runtime_version": execution.runtime_version,
        "input_hash": execution.input_hash,
        "trajectory_plan_set_hash": execution.trajectory_plan_set_hash,
        "expected_execution_hash": execution.content_hash,
        "recomputed_execution_hash": execution.content_hash,
        "replay_classification": "exact",
        "replayed_at": replayed_at,
        "content_hash": "0" * 64,
    }
    payload.update(overrides)
    manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(payload)
    return manifest.model_copy(
        update={"content_hash": adaptive_run_trajectory_replay_manifest_content_hash(manifest)}
    )


# ---------------------------------------------------------------------------
# 1. Deterministic identifier and content hash.
# ---------------------------------------------------------------------------


class TestDeterministicIdentity:
    def test_identifier_deterministic_and_run_bound(self) -> None:
        _store, _run_id, _run_plan, execution = _verified_execution(_build_env())
        first = adaptive_run_trajectory_replay_manifest_identifier(
            run_id=execution.run_id, runtime_version=execution.runtime_version
        )
        second = adaptive_run_trajectory_replay_manifest_identifier(
            run_id=execution.run_id, runtime_version=execution.runtime_version
        )
        assert first == second
        assert (
            adaptive_run_trajectory_replay_manifest_identifier(
                run_id="run-other", runtime_version=execution.runtime_version
            )
            != first
        )

    def test_identifier_has_readable_prefix_and_exact_hex_suffix(self) -> None:
        _store, _run_id, _run_plan, execution = _verified_execution(_build_env())
        identifier = adaptive_run_trajectory_replay_manifest_identifier(
            run_id=execution.run_id, runtime_version=execution.runtime_version
        )
        assert identifier.startswith(_ID_PREFIX)
        assert len(identifier) == len(_ID_PREFIX) + 16
        suffix = identifier[len(_ID_PREFIX) :]
        assert len(suffix) == 16
        assert all(character in "0123456789abcdef" for character in suffix)

    def test_identifier_never_collides_with_execution_identifier(self) -> None:
        _store, _run_id, _run_plan, execution = _verified_execution(_build_env())
        replay_id = adaptive_run_trajectory_replay_manifest_identifier(
            run_id=execution.run_id, runtime_version=execution.runtime_version
        )
        assert replay_id != execution.identifier
        assert not replay_id.startswith("adaptive-run-trajectory-execution-")

    def test_identifier_runtime_literal_participates(self) -> None:
        identifier = adaptive_run_trajectory_replay_manifest_identifier(
            run_id="run-1", runtime_version="4.0.0"
        )
        assert identifier != adaptive_run_trajectory_replay_manifest_identifier(
            run_id="run-1", runtime_version="5.0.0"
        )

    def test_content_hash_deterministic_across_independent_builds(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        first = _manifest_for(execution, replayed_at=run_plan.created_at)
        second = _manifest_for(execution, replayed_at=run_plan.created_at)
        assert first != second or first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.content_hash == second.content_hash
        assert first.identifier == second.identifier

    def test_content_hash_excludes_only_the_content_hash_field(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        displaced = manifest.model_copy(update={"content_hash": _H64_ALT})
        assert adaptive_run_trajectory_replay_manifest_content_hash(displaced) == (
            adaptive_run_trajectory_replay_manifest_content_hash(manifest)
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"tenant_id": "tenant-other"},
            {"run_id": "run-other", "identifier": _RUN_OTHER_IDENTIFIER},
            {"campaign_id": "campaign-other"},
            {"adaptive_run_trajectory_execution_id": "execution-other"},
            {"world_version_id": "world-other"},
            {"world_content_hash": _H64_ALT},
            {"scenario_seed_id": "seed-other"},
            {"seed_content_hash": _H64_ALT},
            {"world_realization_id": "realization-other"},
            {"world_realization_content_hash": _H64_ALT},
            {"adaptive_policy_identifier": "policy-other"},
            {"policy_id": "policy-id-other"},
            {"adaptive_policy_content_hash": _H64_ALT},
            {"input_hash": _H64_ALT},
            {"trajectory_plan_set_hash": _H64_ALT},
            {"expected_execution_hash": _H64_ALT},
            {"recomputed_execution_hash": _H64_ALT},
        ],
    )
    def test_content_hash_covers_every_provenance_field(self, overrides: dict[str, object]) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        base = _manifest_for(execution, replayed_at=run_plan.created_at)
        altered = _manifest_for(execution, replayed_at=run_plan.created_at, **overrides)
        assert altered.content_hash != base.content_hash

    def test_content_hash_covers_replayed_at(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        base = _manifest_for(execution, replayed_at=run_plan.created_at)
        altered = _manifest_for(execution, replayed_at=_OTHER_TIMESTAMP)
        assert altered.content_hash != base.content_hash


# ---------------------------------------------------------------------------
# 2. Complete valid manifestations (absent and present bundle).
# ---------------------------------------------------------------------------


class TestValidManifestations:
    def test_absent_bundle_manifest_passes_identity_and_record(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        assert execution.external_observation_input_bundle_id is None
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        verify_adaptive_run_trajectory_replay_manifest_identity(manifest)
        verify_adaptive_run_trajectory_replay_manifest_record(
            manifest, execution=execution, replayed_at=run_plan.created_at
        )

    def test_present_bundle_manifest_passes_identity_and_record(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(
            _build_env_external(), external=True
        )
        assert execution.external_observation_input_bundle_id is not None
        assert execution.external_observation_input_bundle_content_hash is not None
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        verify_adaptive_run_trajectory_replay_manifest_identity(manifest)
        verify_adaptive_run_trajectory_replay_manifest_record(
            manifest, execution=execution, replayed_at=run_plan.created_at
        )
        assert manifest.external_observation_input_bundle_id == (
            execution.external_observation_input_bundle_id
        )
        assert manifest.external_observation_input_bundle_content_hash == (
            execution.external_observation_input_bundle_content_hash
        )

    def test_both_execution_hashes_equal_the_verified_content_hash(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        assert manifest.expected_execution_hash == execution.content_hash
        assert manifest.recomputed_execution_hash == execution.content_hash


# ---------------------------------------------------------------------------
# 3. Identity forgery rejection (exact type, subclass, model_construct).
# ---------------------------------------------------------------------------


class TestIdentityForgeryRejection:
    def test_wrong_type_dict_rejected(self) -> None:
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity({"run_id": "run-1"})

    def test_wrong_type_execution_rejected(self) -> None:
        _store, _run_id, _run_plan, execution = _verified_execution(_build_env())
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(execution)

    def test_subclass_forgery_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)

        class _Sub(AdaptiveRunTrajectoryReplayManifest):
            pass

        forged = _Sub.model_construct(**manifest.model_dump(mode="python"))
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(forged)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                forged, execution=execution, replayed_at=run_plan.created_at
            )

    @pytest.mark.parametrize(
        "tamper",
        [
            {"policy_id": 42},
            {"runtime_version": "5.0.0"},
            {"replay_classification": "approximate"},
            {"replayed_at": "not-a-time"},
        ],
    )
    def test_model_construct_wrong_typed_value_rejected(self, tamper: dict[str, object]) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        dump = manifest.model_dump(mode="python")
        dump.update(tamper)
        forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(forged)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                forged, execution=execution, replayed_at=run_plan.created_at
            )

    def test_model_construct_missing_required_field_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        dump = manifest.model_dump(mode="python")
        del dump["content_hash"]
        forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(forged)

    def test_wrong_identifier_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        wrong = manifest.model_copy(update={"identifier": f"{_ID_PREFIX}{'0' * 16}"})
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(wrong)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                wrong, execution=execution, replayed_at=run_plan.created_at
            )

    def test_malformed_identifier_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        malformed = manifest.model_copy(update={"identifier": "not-a-replay-manifest"})
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(malformed)

    def test_wrong_content_hash_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        wrong = manifest.model_copy(update={"content_hash": _H64_ALT})
        with pytest.raises(ValueError):
            verify_adaptive_run_trajectory_replay_manifest_identity(wrong)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                wrong, execution=execution, replayed_at=run_plan.created_at
            )


# ---------------------------------------------------------------------------
# 4. Full-record integrity: parametrized provenance mismatches.
# ---------------------------------------------------------------------------


class TestRecordMismatches:
    @pytest.mark.parametrize(
        "overrides,expected_reason",
        [
            ({"tenant_id": "tenant-other"}, "manifest tenant mismatch"),
            (
                {"run_id": "run-other", "identifier": _RUN_OTHER_IDENTIFIER},
                "manifest run identity mismatch",
            ),
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
        self, overrides: dict[str, object], expected_reason: str
    ) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at, **overrides)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == expected_reason

    def test_expected_execution_hash_mismatch_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(
            execution, replayed_at=run_plan.created_at, expected_execution_hash=_H64_ALT
        )
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == "manifest expected execution hash mismatch"

    def test_recomputed_execution_hash_mismatch_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(
            execution, replayed_at=run_plan.created_at, recomputed_execution_hash=_H64_ALT
        )
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == "manifest recomputed execution hash mismatch"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"external_observation_input_bundle_id": "bundle-other"},
            {"external_observation_input_bundle_content_hash": _H64_ALT},
        ],
    )
    def test_present_bundle_mismatch_rejected(self, overrides: dict[str, object]) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(
            _build_env_external(), external=True
        )
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at, **overrides)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == "manifest external bundle mismatch"

    def test_manifest_claiming_bundle_for_bundleness_execution_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(
            execution,
            replayed_at=run_plan.created_at,
            external_observation_input_bundle_id="bundle-other",
            external_observation_input_bundle_content_hash=_H64_ALT,
        )
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == "manifest external bundle mismatch"

    def test_replayed_at_mismatch_rejected(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=_OTHER_TIMESTAMP)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                manifest, execution=execution, replayed_at=run_plan.created_at
            )
        assert excinfo.value.reason == "manifest replayed at mismatch"

    def test_wrong_runtime_literal_rejected_at_record_boundary(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        dump = manifest.model_dump(mode="python")
        dump["runtime_version"] = "5.0.0"
        forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                forged, execution=execution, replayed_at=run_plan.created_at
            )

    def test_wrong_classification_rejected_at_record_boundary(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        dump = manifest.model_dump(mode="python")
        dump["replay_classification"] = "approximate"
        forged = AdaptiveRunTrajectoryReplayManifest.model_construct(**dump)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError):
            verify_adaptive_run_trajectory_replay_manifest_record(
                forged, execution=execution, replayed_at=run_plan.created_at
            )


# ---------------------------------------------------------------------------
# 5. Non-leaking typed failures and pure unchanged-input behavior.
# ---------------------------------------------------------------------------


class TestSafetyAndPurity:
    def test_public_messages_leak_nothing(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
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
            run_plan.created_at.isoformat(),
            _OTHER_TIMESTAMP.isoformat(),
            "run-other",
            "campaign-other",
            "policy-id-other",
            "execution-other",
        )
        observed: list[str] = []
        for overrides in (
            {"tenant_id": "tenant-other"},
            {"run_id": "run-other", "identifier": _RUN_OTHER_IDENTIFIER},
            {"campaign_id": "campaign-other"},
            {"expected_execution_hash": _H64_ALT},
            {"recomputed_execution_hash": _H64_ALT},
        ):
            manifest = _manifest_for(execution, replayed_at=run_plan.created_at, **overrides)
            with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
                verify_adaptive_run_trajectory_replay_manifest_record(
                    manifest, execution=execution, replayed_at=run_plan.created_at
                )
            observed.append(str(excinfo.value))
            assert excinfo.value.reason is not None
        # The recorded replay timestamp mismatch raises the same generic
        # integrity message.
        mismatched_replay = _manifest_for(execution, replayed_at=_OTHER_TIMESTAMP)
        with pytest.raises(AdaptiveRunTrajectoryReplayManifestIntegrityError) as excinfo:
            verify_adaptive_run_trajectory_replay_manifest_record(
                mismatched_replay, execution=execution, replayed_at=run_plan.created_at
            )
        observed.append(str(excinfo.value))
        assert excinfo.value.reason is not None
        # Identity-level failures are equally generic.
        wrong = _manifest_for(execution, replayed_at=run_plan.created_at).model_copy(
            update={"content_hash": _H64_ALT}
        )
        with pytest.raises(ValueError) as identity_exc:
            verify_adaptive_run_trajectory_replay_manifest_identity(wrong)
        observed.append(str(identity_exc.value))
        assert all(
            message == "Adaptive run trajectory replay manifest failed integrity verification"
            for message in observed[:6]
        )
        assert all(secret not in " ".join(observed) for secret in secrets)

    def test_identity_and_record_leave_inputs_unchanged(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        manifest_before = manifest.model_dump(mode="json")
        execution_before = execution.model_dump(mode="json")
        verify_adaptive_run_trajectory_replay_manifest_identity(manifest)
        verify_adaptive_run_trajectory_replay_manifest_record(
            manifest, execution=execution, replayed_at=run_plan.created_at
        )
        assert manifest.model_dump(mode="json") == manifest_before
        assert execution.model_dump(mode="json") == execution_before

    def test_record_verifier_is_repeatable_and_deterministic(self) -> None:
        _store, _run_id, run_plan, execution = _verified_execution(_build_env())
        manifest = _manifest_for(execution, replayed_at=run_plan.created_at)
        verify_adaptive_run_trajectory_replay_manifest_record(
            manifest, execution=execution, replayed_at=run_plan.created_at
        )
        verify_adaptive_run_trajectory_replay_manifest_record(
            manifest, execution=execution, replayed_at=run_plan.created_at
        )

    def test_error_types_are_typed_domain_errors(self) -> None:
        from kalhas.application.domain_errors import KalhasDomainError

        error_types = (
            AdaptiveRunTrajectoryReplayManifestValidationError,
            AdaptiveRunTrajectoryReplayManifestAlreadyExistsError,
            AdaptiveRunTrajectoryReplayManifestNotFoundError,
            AdaptiveRunTrajectoryReplayManifestIntegrityError,
        )
        for error_type in error_types:
            assert issubclass(error_type, KalhasDomainError)
        validation = AdaptiveRunTrajectoryReplayManifestValidationError("tenant-1", "run-1")
        assert str(validation) == "Adaptive run trajectory replay manifest input is invalid"
        already = AdaptiveRunTrajectoryReplayManifestAlreadyExistsError("tenant-1", "run-1")
        assert str(already) == (
            "Adaptive run trajectory replay manifest already exists for this run and is immutable"
        )
        not_found = AdaptiveRunTrajectoryReplayManifestNotFoundError("tenant-1", "run-1")
        assert str(not_found) == "Adaptive run trajectory replay manifest not found"
        integrity = AdaptiveRunTrajectoryReplayManifestIntegrityError(
            "tenant-1", "run-1", reason="manifest tenant mismatch"
        )
        assert str(integrity) == (
            "Adaptive run trajectory replay manifest failed integrity verification"
        )
        assert integrity.reason == "manifest tenant mismatch"


# ---------------------------------------------------------------------------
# 6. No store / builder / service / replay / network / RNG / clock surface.
# ---------------------------------------------------------------------------


class TestNoForbiddenSurface:
    def _import_sets(self, module: ModuleType) -> tuple[set[str], set[str]]:
        source = inspect.getsource(module)
        tree = ast.parse(source)
        roots: set[str] = set()
        kalhas_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                roots.add(node.module.split(".")[0])
                if node.module.startswith("kalhas"):
                    kalhas_modules.add(node.module)
        return roots, kalhas_modules

    def _forbidden_names(self, module: ModuleType) -> set[str]:
        source = inspect.getsource(module)
        tree = ast.parse(source)
        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id
            in {"datetime", "time", "uuid", "random", "now", "utcnow", "monotonic", "time_ns"}
        }

    def _forbidden_attributes(self, module: ModuleType) -> set[str]:
        source = inspect.getsource(module)
        tree = ast.parse(source)
        return {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr
            in {
                "put_replay_manifest",
                "put_adaptive_run_trajectory_replay_manifest",
                "get_adaptive_run_trajectory_replay_manifest",
                "put_adaptive_run_trajectory_execution",
                "get_adaptive_run_trajectory_execution",
                "record_operational_activity",
                "put_run_status",
                "get_run_status",
                "put_world",
                "put_campaign",
                "put_policy",
                "delete",
                "upsert",
                "list_operational_activity",
            }
        }

    def test_identity_module_import_boundary(self) -> None:
        roots, kalhas_modules = self._import_sets(identity_module)
        assert roots <= {"__future__", "typing", "kalhas", "warnings", "pydantic"}
        assert kalhas_modules == {
            "kalhas.application.hashing",
            "kalhas.contracts.v1.adaptive_trajectory_replay",
        }

    def test_integrity_module_import_boundary(self) -> None:
        roots, kalhas_modules = self._import_sets(integrity_module)
        assert roots <= {"__future__", "typing", "kalhas"}
        assert kalhas_modules == {
            "kalhas.application.adaptive_trajectory_replay_errors",
            "kalhas.application.adaptive_trajectory_replay_identity",
            "kalhas.contracts.v1.adaptive_trajectory_execution",
            "kalhas.contracts.v1.adaptive_trajectory_replay",
            "kalhas.contracts.v1.shared",
        }

    def test_errors_module_import_boundary(self) -> None:
        roots, kalhas_modules = self._import_sets(errors_module)
        assert roots <= {"__future__", "kalhas"}
        assert kalhas_modules == {"kalhas.application.domain_errors"}

    def test_no_clock_random_network_store_or_replay_surface(self) -> None:
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
            "sqlite3",
            "networkx",
        }
        for module in (identity_module, integrity_module, errors_module):
            roots, kalhas_modules = self._import_sets(module)
            assert not (roots & forbidden_roots)
            assert self._forbidden_names(module) == set()
            assert self._forbidden_attributes(module) == set()
            # No builder, service, store, engine, runtime, or replay
            # computation module is reachable from the replay
            # identity/integrity boundary (the manifest modules themselves
            # legitimately carry "replay" in their names).
            forbidden_module_prefixes = (
                "kalhas.application.in_memory_store",
                "kalhas.application.adaptive_run_execution_builder",
                "kalhas.application.adaptive_run_execution_service",
                "kalhas.application.adaptive_decision_step_service",
                "kalhas.application.adaptive_condition_evaluator",
                "kalhas.application.adaptive_policy_state_machine",
                "kalhas.application.realization_replay",
                "kalhas.application.run_trajectory_runtime",
                "kalhas.adapters",
            )
            for module_path in kalhas_modules:
                assert module_path.startswith("kalhas.application.") or module_path.startswith(
                    "kalhas.contracts.v1."
                )
                assert not module_path.startswith(forbidden_module_prefixes)

    def test_no_clock_or_rng_identifiers_in_function_bodies(self) -> None:
        for module in (identity_module, integrity_module, errors_module):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert not (
                name_ids
                & {"now", "utcnow", "monotonic", "time_ns", "datetime", "time", "random", "uuid"}
            )

    def test_exact_all_exports(self) -> None:
        assert identity_module.__all__ == [
            "RUNTIME_VERSION_LITERAL",
            "adaptive_run_trajectory_replay_manifest_content_hash",
            "adaptive_run_trajectory_replay_manifest_identifier",
            "verify_adaptive_run_trajectory_replay_manifest_identity",
        ]
        assert integrity_module.__all__ == ["verify_adaptive_run_trajectory_replay_manifest_record"]
        assert errors_module.__all__ == [
            "AdaptiveRunTrajectoryReplayManifestAlreadyExistsError",
            "AdaptiveRunTrajectoryReplayManifestIntegrityError",
            "AdaptiveRunTrajectoryReplayManifestNotFoundError",
            "AdaptiveRunTrajectoryReplayManifestValidationError",
        ]

    def test_public_signature_boundary(self) -> None:
        record = inspect.signature(verify_adaptive_run_trajectory_replay_manifest_record)
        parameters = list(record.parameters.values())
        assert [parameter.name for parameter in parameters] == [
            "manifest",
            "execution",
            "replayed_at",
        ]
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])
        assert not any(
            parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for parameter in parameters
        )
        identity = inspect.signature(verify_adaptive_run_trajectory_replay_manifest_identity)
        assert [parameter.name for parameter in identity.parameters.values()] == ["manifest"]
        identifier = inspect.signature(adaptive_run_trajectory_replay_manifest_identifier)
        identifier_params = list(identifier.parameters.values())
        assert [parameter.name for parameter in identifier_params] == ["run_id", "runtime_version"]
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in identifier_params
        )
        content_hash = inspect.signature(adaptive_run_trajectory_replay_manifest_content_hash)
        assert [parameter.name for parameter in content_hash.parameters.values()] == ["manifest"]
