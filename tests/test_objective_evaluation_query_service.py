"""Phase 23 verified-query tests: the read-only campaign objective-evaluation chain.

Proves ``get_verified_campaign_objective_evaluations`` derives the
complete matrix in memory from already verified artifacts only: the
tenant-scoped COMPLETE campaign, the verified Phase 21 matrix, the
fully verified compiled world, and the exact world-embedded profile
strictly matched against the stored record - 404 for a world without
an embedded profile, 409 integrity for a missing/malformed/mismatched
stored record, 409 invalid_state for non-COMPLETE campaigns, 404 for
unknown/foreign campaigns, and 409 integrity for tampered worlds,
profiles, or observation artifacts. Repeated GETs are byte-identical,
and the query never stores, extracts, executes, or replays anything.
"""

from __future__ import annotations

import copy

import pytest
from kalhas.application.domain_errors import CampaignNotCompleteError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_errors import (
    CampaignObjectiveEvaluationMatrixIntegrityError,
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_query_service import (
    get_verified_campaign_objective_evaluations,
)
from kalhas.contracts.v1.objective_evaluation import CampaignObjectiveEvaluationMatrix
from kalhas.contracts.v1.world import WorldVersion

from tests.phase4_helpers import TENANT, build_seed
from tests.phase21_helpers import complete_observation_campaign
from tests.phase23_helpers import (
    DEFAULT_BINDING_DRAFTS,
    complete_evaluation_campaign,
    self_consistent_profile_copy,
    verified_evaluation_campaign,
)

OTHER_TENANT = "tenant-other"


def _query(
    store: InMemoryScenarioStore, campaign_id: str = "campaign-1", tenant_id: str = TENANT
) -> CampaignObjectiveEvaluationMatrix:
    return get_verified_campaign_objective_evaluations(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )


class TestVerifiedHappyPath:
    def test_returns_complete_matrix(self) -> None:
        _store, matrix, _run_ids = verified_evaluation_campaign()
        assert matrix.campaign_id == "campaign-1"
        assert matrix.runtime_version == "2.0.0"
        assert len(matrix.cells) == 5 * 1 * 3
        assert matrix.ordered_objective_ids == ("obj-b", "obj-a", "obj-c")

    def test_repeated_calls_are_byte_identical(self) -> None:
        store, first, _run_ids = verified_evaluation_campaign()
        second = _query(store)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.content_hash == second.content_hash

    def test_matrix_never_stored(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        snapshot = copy.deepcopy(store.__dict__)
        _query(store)
        assert store.__dict__ == snapshot

    def test_multi_seed_campaign(self) -> None:
        seeds = (build_seed(identifier="seed-1"), build_seed(identifier="seed-2"))
        _store, matrix, _run_ids = verified_evaluation_campaign(seeds=seeds)
        assert len(matrix.cells) == 5 * 2 * 3
        assert matrix.ordered_scenario_seed_ids == ("seed-1", "seed-2")


class TestCampaignGates:
    def test_unknown_campaign_404(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        from kalhas.application.domain_errors import CampaignNotFoundError

        with pytest.raises(CampaignNotFoundError):
            _query(store, campaign_id="campaign-unknown")

    def test_foreign_tenant_campaign_404(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        from kalhas.application.domain_errors import CampaignNotFoundError

        with pytest.raises(CampaignNotFoundError):
            _query(store, tenant_id=OTHER_TENANT)

    def test_non_complete_campaign_409_invalid_state(self) -> None:
        store, _world_version_id, _run_ids = complete_evaluation_campaign(execute=False)
        with pytest.raises(CampaignNotCompleteError):
            _query(store)


class TestProfileResolution:
    def test_world_without_embedded_profile_404(self) -> None:
        # A Phase 21 campaign over a world compiled before any profile.
        store, _world_version_id, _run_ids = complete_observation_campaign()
        with pytest.raises(EvaluationProfileNotFoundError):
            _query(store)

    def test_missing_stored_record_409_integrity(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _query(store)

    def test_tampered_stored_profile_409_integrity(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        tampered = self_consistent_profile_copy(stored, metadata={"note": "tampered"})
        store._evaluation_profiles[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _query(store)

    def test_stored_and_embedded_canonical_equality_required(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        replaced = self_consistent_profile_copy(
            stored, declared_at=stored.declared_at, metadata={"note": "replaced"}
        )
        store._evaluation_profiles[(TENANT, "scenario-1")] = replaced
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _query(store)


class TestWorldAndArtifactTamper:
    def _world(self, store: InMemoryScenarioStore, world_version_id: str) -> WorldVersion:
        return store._worlds[(TENANT, world_version_id)]

    def test_tampered_world_profile_rejected(self) -> None:
        store, _matrix, _run_ids = verified_evaluation_campaign()
        world = self._world(store, store.get_campaign(TENANT, "campaign-1").world_version_id)
        body = dict(world.world)
        profile_payload = body["evaluation_profile"]
        assert isinstance(profile_payload, dict)
        body["evaluation_profile"] = {
            **profile_payload,
            "scenario_content_hash": "f" * 64,
        }
        tampered_world = world.model_copy(update={"world": body})
        store._worlds[(TENANT, world.identifier)] = tampered_world
        with pytest.raises(Exception) as excinfo:
            _query(store)
        from kalhas.application.domain_errors import WorldSnapshotIntegrityError

        assert isinstance(excinfo.value, WorldSnapshotIntegrityError)

    def test_corrupted_run_observation_set_rejected_upstream(self) -> None:
        store, _matrix, run_ids = verified_evaluation_campaign()
        stored_set = store._run_metric_observation_sets[(TENANT, run_ids[0])]
        observations = list(stored_set.observations)
        observations[0] = observations[0].model_copy(update={"raw_value": 999})
        tampered_set = stored_set.model_copy(update={"observations": tuple(observations)})
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = tampered_set
        # The Phase 21 verified query wraps the upstream Phase 20
        # integrity failure in its own typed matrix integrity error,
        # which passes through the Phase 23 query unchanged.
        from kalhas.application.domain_errors import (
            CampaignMetricObservationMatrixIntegrityError,
        )

        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)

    def test_missing_bound_metric_observations_rejected(self) -> None:
        # obj-c binds m-3, which has no Phase 19 binding and therefore
        # never appears in the verified Phase 21 matrix.
        from kalhas.application.objective_evaluation_service import (
            ObjectiveMetricBindingDraft,
        )

        bindings = (
            ObjectiveMetricBindingDraft(
                objective_id="obj-b",
                metric_id="m-1",
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-a",
                metric_id="m-2",
                reach_tolerance=None,
                normalization_scale=20.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-c",
                metric_id="m-3",
                reach_tolerance=5.0,
                normalization_scale=50.0,
            ),
        )
        store, _world_version_id, _run_ids = complete_evaluation_campaign(bindings=bindings)
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _query(store)


class TestTenantIsolation:
    def test_profile_of_other_tenant_invisible(self) -> None:
        store = InMemoryScenarioStore()
        from kalhas.application.objective_evaluation_service import (
            declare_scenario_evaluation_profile,
        )

        from tests.phase23_helpers import PROFILE_DECLARED_AT, build_evaluation_scenario

        store.put_scenario(build_evaluation_scenario(tenant_id=OTHER_TENANT))
        declare_scenario_evaluation_profile(
            store,
            tenant_id=OTHER_TENANT,
            scenario_id="scenario-1",
            bindings=DEFAULT_BINDING_DRAFTS,
            declared_at=PROFILE_DECLARED_AT,
        )
        with pytest.raises(EvaluationProfileNotFoundError):
            store.get_evaluation_profile(TENANT, "scenario-1")
