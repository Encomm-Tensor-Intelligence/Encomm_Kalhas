"""Phase 22 query-service tests: verified read-only metric statistics.

Proves ``get_verified_campaign_metric_statistics`` derives the
deterministic descriptive-statistics matrix exclusively through the
existing verified Phase 21 query service (never reimplementing or
weakening Phase 18/20/21 verification), preserves the existing typed
error mappings (404 not-found, 409 invalid_state, 409 conflict, 409
integrity_error for missing/corrupted earlier-phase artifacts), maps
Phase 22 internal failures to the safe typed integrity error, is
deterministic and byte-identical on repeated calls, writes nothing,
stores nothing, and never triggers extraction, execution, replay, or
repair.
"""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from kalhas.application.campaign_metric_statistics_query_service import (
    get_verified_campaign_metric_statistics,
)
from kalhas.application.domain_errors import (
    CampaignMetricObservationMatrixIntegrityError,
    CampaignMetricStatisticsIntegrityError,
    CampaignNotCompleteError,
    CampaignNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_metric_observation_service import (
    extract_run_metric_observations,
)
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.campaign_metric_statistics import CampaignMetricStatisticsMatrix
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet
from pydantic import ValidationError

from tests.phase4_helpers import TENANT, build_store, prepare, start
from tests.phase21_helpers import complete_observation_campaign
from tests.phase22_helpers import verified_observation_campaign

OTHER_TENANT = "tenant-other"


def _snapshot(store: InMemoryScenarioStore) -> object:
    return copy.deepcopy(store.__dict__)


class TestSuccess:
    def test_successful_verified_statistics_matrix(self) -> None:
        store, matrix, _run_ids = verified_observation_campaign()
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(statistics, CampaignMetricStatisticsMatrix)
        # 5 mock strategies x 1 shared seed x 2 metrics.
        assert len(statistics.summaries) == 5 * 2
        assert statistics.ordered_strategy_candidate_ids == (
            "mock-baseline",
            "mock-conservative",
            "mock-balanced",
            "mock-adaptive",
            "mock-diversified",
        )
        assert statistics.ordered_metric_ids == ("m-1", "m-2")
        first = statistics.summaries[0]
        assert first.strategy_candidate_id == "mock-baseline"
        assert first.metric_id == "m-1"
        assert first.metric_unit == "units"
        assert first.ordered_observed_values == (1,)
        assert type(first.ordered_observed_values[0]) is int
        assert first.population_standard_deviation == 0.0
        second = statistics.summaries[1]
        assert second.metric_id == "m-2"
        assert second.metric_unit == "percent"
        assert second.ordered_observed_values == (1.5,)
        assert type(second.ordered_observed_values[0]) is float
        # Summarized at the authoritative Phase 21 matrix assembled_at.
        assert statistics.summarized_at == matrix.assembled_at
        assert statistics.source_metric_observation_matrix_id == matrix.identifier
        assert statistics.source_metric_observation_matrix_content_hash == matrix.content_hash

    def test_zero_metric_campaign_yields_empty_summaries(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign(with_bindings=False)
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert statistics.ordered_metric_ids == ()
        assert statistics.summaries == ()

    def test_repeated_calls_byte_identical(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        first = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert first == second
        assert first.model_dump_json() == second.model_dump_json()


class TestAuthoritativePipeline:
    def test_phase21_query_is_authoritative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _boom(
            *,
            store: InMemoryScenarioStore,
            tenant_id: str,
            campaign_id: str,
        ) -> Any:
            raise AssertionError("phase 21 query must be called")

        monkeypatch.setattr(
            "kalhas.application.campaign_metric_statistics_query_service."
            "get_verified_campaign_metric_observation_matrix",
            _boom,
        )
        with pytest.raises(AssertionError, match="phase 21 query must be called"):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_phase21_typed_errors_pass_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _reject(
            *,
            store: InMemoryScenarioStore,
            tenant_id: str,
            campaign_id: str,
        ) -> Any:
            raise CampaignMetricObservationMatrixIntegrityError(campaign_id, reason="injected")

        monkeypatch.setattr(
            "kalhas.application.campaign_metric_statistics_query_service."
            "get_verified_campaign_metric_observation_matrix",
            _reject,
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_builder_integrity_failure_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _fail(
            *,
            observation_matrix: object,
        ) -> CampaignMetricStatisticsMatrix:
            raise CampaignMetricStatisticsIntegrityError("campaign-1", reason="injected")

        monkeypatch.setattr(
            "kalhas.application.campaign_metric_statistics_query_service."
            "build_campaign_metric_statistics_matrix",
            _fail,
        )
        with pytest.raises(CampaignMetricStatisticsIntegrityError) as captured:
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert "injected" not in str(captured.value)

    def test_builder_validation_failure_mapped_safely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _invalid(
            *,
            observation_matrix: object,
        ) -> CampaignMetricStatisticsMatrix:
            raise ValidationError.from_exception_data(
                "CampaignMetricStatisticsMatrix", line_errors=[]
            )

        monkeypatch.setattr(
            "kalhas.application.campaign_metric_statistics_query_service."
            "build_campaign_metric_statistics_matrix",
            _invalid,
        )
        with pytest.raises(CampaignMetricStatisticsIntegrityError) as captured:
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        message = str(captured.value)
        assert "integrity" in message
        assert "violates" not in message
        assert "campaign-1" in message


class TestTypedMappings:
    def test_unknown_campaign_raises_not_found(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-ghost"
            )

    def test_foreign_tenant_indistinguishable_from_missing(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=OTHER_TENANT, campaign_id="campaign-1"
            )

    def test_incomplete_campaign_raises_not_complete(self) -> None:
        store, _world_id, _run_ids = complete_observation_campaign(execute=False)
        with pytest.raises(CampaignNotCompleteError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_legacy_runtime_raises_unsupported(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_unsupported_runtime_raises_unsupported(self) -> None:
        from kalhas.contracts.v1.campaign import CampaignState

        from tests.phase25_helpers import inject_unsupported_recorded_runtime

        store, world_id = build_store()
        # Prepare a valid runtime-2 campaign, then simulate corrupted
        # recorded state through private test seams (not an application
        # preparation path): the selected RunPlan and its matching
        # RunStatus are re-stamped with an unsupported recorded runtime.
        prepared = prepare(store, world_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=prepared.run_plans[0]
        )
        start(store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT,
            "campaign-1",
            status.model_copy(update={"state": CampaignState.COMPLETE}),
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_missing_phase20_artifact_raises_matrix_integrity(self) -> None:
        store, _matrix, run_ids = verified_observation_campaign()
        del store._run_metric_observation_sets[(TENANT, run_ids[0])]
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        # Never repaired: nothing was recreated by the query.
        assert (TENANT, run_ids[0]) not in store._run_metric_observation_sets

    def test_corrupted_phase20_artifact_raises_matrix_integrity(self) -> None:
        store, _matrix, run_ids = verified_observation_campaign()
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = stored.model_copy(
            update={"content_hash": "1" * 64}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_tampered_observation_value_raises_matrix_integrity(self) -> None:
        store, _matrix, run_ids = verified_observation_campaign()
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        tampered_value = stored.observations[0].model_copy(update={"raw_value": 99})
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = stored.model_copy(
            update={"observations": (tampered_value,) + stored.observations[1:]}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_validator_bypassed_bool_raises_matrix_integrity(self) -> None:
        store, _matrix, run_ids = verified_observation_campaign()
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        value_payload = stored.observations[0].model_dump(mode="python")
        value_payload["raw_value"] = True
        tampered_value = type(stored.observations[0]).model_construct(**value_payload)
        set_payload = stored.model_dump(mode="python")
        set_payload["observations"] = (tampered_value,) + stored.observations[1:]
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = (
            RunMetricObservationSet.model_construct(**set_payload)
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestReadOnly:
    def test_no_writes_no_storage_no_lifecycle_changes(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        before = _snapshot(store)
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert _snapshot(store) == before
        # No statistics storage surface exists anywhere.
        assert not hasattr(store, "_campaign_metric_statistics_matrices")
        assert not hasattr(store, "put_campaign_metric_statistics_matrix")
        assert not hasattr(store, "get_campaign_metric_statistics_matrix")
        assert statistics is not None

    def test_no_extraction_triggered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _boom(*args: object, **kwargs: object) -> Any:
            raise AssertionError("extraction must never be triggered")

        monkeypatch.setattr(
            "kalhas.application.run_metric_observation_service.extract_run_metric_observations",
            _boom,
        )
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert statistics.campaign_id == "campaign-1"

    def test_no_execution_triggered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()

        def _boom(*args: object, **kwargs: object) -> Any:
            raise AssertionError("execution must never be triggered")

        monkeypatch.setattr("kalhas.application.structural_runtime.execute_campaign", _boom)
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert statistics.campaign_id == "campaign-1"

    def test_extract_import_exists_but_is_never_called_by_the_query_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Defense in depth: even the Phase 20 extractor is only reachable
        # through its own service, which the verified chain never invokes.
        store, _matrix, _run_ids = verified_observation_campaign()
        calls: list[object] = []
        original = extract_run_metric_observations

        def _spy(
            store: InMemoryScenarioStore, tenant_id: str, run_id: str
        ) -> RunMetricObservationSet:
            calls.append((store, tenant_id, run_id))
            return original(store=store, tenant_id=tenant_id, run_id=run_id)

        monkeypatch.setattr(
            "kalhas.application.run_metric_observation_service.extract_run_metric_observations",
            _spy,
        )
        get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == []

    def test_store_snapshot_byte_identical_after_repeated_queries(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        before = _snapshot(store)
        for _ in range(2):
            get_verified_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert _snapshot(store) == before

    def test_query_result_not_stored(self) -> None:
        store, _matrix, _run_ids = verified_observation_campaign()
        statistics = get_verified_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        # The returned matrix is not retrievable through any store surface.
        assert not hasattr(store, "get_campaign_metric_statistics_matrix")
        assert "campaign_metric_statistics" not in cast(dict[str, object], store.__dict__)
        assert statistics.content_hash
