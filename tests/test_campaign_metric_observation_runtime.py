"""Phase 21 pure matrix builder tests.

Proves ``build_campaign_metric_observation_matrix`` assembles the exact
strategy x shared-seed observation matrix from already-verified records:
the Phase 18 trajectory matrix is the authoritative layout and cell
order, the Phase 20 observation sets bind exactly one per cell with all
identities and hashes verified, common binding provenance agrees across
cells while run-specific trajectory-plan/result provenance may
legitimately differ and is preserved exactly, raw values are never
converted, identifier/content-hash/assembled_at are deterministic from
the recorded campaign, repeated builds are byte-identical, inputs are
never mutated or reordered, and every missing/additional/duplicated/
reordered/foreign/mismatched input is rejected with the typed integrity
or unsupported-runtime error.
"""

from __future__ import annotations

import pytest
from kalhas.application.campaign_metric_observation_runtime import (
    build_campaign_metric_observation_matrix,
    campaign_metric_observation_matrix_content_hash,
    campaign_metric_observation_matrix_identifier,
)
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.domain_errors import (
    CampaignMetricObservationMatrixIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet

from tests.phase4_helpers import TENANT, build_seed
from tests.phase21_helpers import complete_observation_campaign

OTHER_TENANT = "tenant-other"


@pytest.fixture(scope="module")
def complete_store() -> tuple[InMemoryScenarioStore, str, tuple[str, ...]]:
    """A COMPLETE 5-strategy x 2-seed campaign with verified sets for every run."""
    return complete_observation_campaign(seeds=(build_seed(), build_seed(identifier="seed-2")))


@pytest.fixture(scope="module")
def empty_bindings_store() -> InMemoryScenarioStore:
    """A COMPLETE campaign whose compiled world embeds no observation bindings."""
    store, _world, _run_ids = complete_observation_campaign(with_bindings=False)
    return store


def _builder_inputs(
    store: InMemoryScenarioStore,
) -> tuple[CampaignSpec, CampaignTrajectoryMatrix, tuple[RunMetricObservationSet, ...]]:
    """Fresh deep-copied builder inputs from the store (never mutated)."""
    campaign = store.get_campaign(TENANT, "campaign-1")
    trajectory_matrix = get_verified_campaign_trajectory_matrix(
        store=store, tenant_id=TENANT, campaign_id="campaign-1"
    )
    observation_sets = tuple(
        store.get_run_metric_observation_set(TENANT, run_id)
        for run_id in (run_identifier(plan) for plan in store.get_run_plans(TENANT, "campaign-1"))
    )
    return campaign, trajectory_matrix, observation_sets


def _build(
    store: InMemoryScenarioStore,
) -> CampaignMetricObservationMatrix:
    campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
    return build_campaign_metric_observation_matrix(
        campaign=campaign,
        trajectory_matrix=trajectory_matrix,
        observation_sets=observation_sets,
    )


def _run_ids(store: InMemoryScenarioStore) -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, "campaign-1"))


class TestSuccessfulBuild:
    def test_multi_strategy_multi_seed_matrix(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, run_ids = complete_store
        matrix = _build(store)
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert len(matrix.cells) == len(run_ids) == 10
        assert len(matrix.ordered_strategy_candidate_ids) == 5
        assert len(matrix.ordered_scenario_seed_ids) == 2
        assert matrix.campaign_id == campaign.identifier
        assert matrix.runtime_version == "2.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        trajectory_matrix = get_verified_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.world_content_hash == trajectory_matrix.world_content_hash
        assert matrix.world_version_id == trajectory_matrix.world_version_id

    def test_exact_phase18_cell_order_preserved(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        trajectory_matrix = get_verified_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.cells) == len(trajectory_matrix.cells)
        for cell, reference in zip(matrix.cells, trajectory_matrix.cells, strict=True):
            assert cell.sequence_position == reference.sequence_position
            assert cell.strategy_position == reference.strategy_position
            assert cell.seed_position == reference.seed_position
            assert cell.run_id == reference.run_id
            assert cell.run_plan_id == reference.run_plan_id
            assert cell.strategy_candidate_id == reference.strategy_candidate_id
            assert cell.scenario_seed_id == reference.scenario_seed_id
            assert cell.input_hash == reference.input_hash
            assert cell.trajectory_execution_id == reference.trajectory_execution_id
            assert (
                cell.trajectory_execution_content_hash
                == reference.trajectory_execution_content_hash
            )

    def test_exact_strategy_major_seed_minor_order(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        pairs = [(cell.strategy_position, cell.seed_position) for cell in matrix.cells]
        assert pairs == [
            (strategy_position, seed_position)
            for strategy_position in range(5)
            for seed_position in range(2)
        ]

    def test_exact_phase20_values_preserved(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, fixture_run_ids = complete_store
        matrix = _build(store)
        for cell, run_id in zip(matrix.cells, fixture_run_ids, strict=True):
            stored = store.get_run_metric_observation_set(TENANT, run_id)
            assert cell.metric_observation_set_id == stored.identifier
            assert cell.metric_observation_set_content_hash == stored.content_hash
            assert cell.observations == stored.observations
            assert [o.model_dump(mode="json") for o in cell.observations] == [
                o.model_dump(mode="json") for o in stored.observations
            ]

    def test_integer_raw_value_not_converted_to_float(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        for cell in matrix.cells:
            integer_value = cell.observations[0]
            assert integer_value.metric_id == "m-1"
            assert integer_value.raw_value == 1
            assert type(integer_value.raw_value) is int
            number_value = cell.observations[1]
            assert number_value.metric_id == "m-2"
            assert number_value.raw_value == 1.5
            assert type(number_value.raw_value) is float

    def test_deterministic_identifier(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign = store.get_campaign(TENANT, "campaign-1")
        first = _build(store)
        second = _build(store)
        assert first.identifier == second.identifier
        assert first.identifier == campaign_metric_observation_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=campaign.world_version_id,
            runtime_version="2.0.0",
        )
        assert first.identifier.startswith("metric-observation-matrix-")
        assert len(first.identifier) == len("metric-observation-matrix-") + 16

    def test_deterministic_content_hash(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        assert matrix.content_hash == campaign_metric_observation_matrix_content_hash(matrix)
        assert len(matrix.content_hash) == 64
        assert all(c in "0123456789abcdef" for c in matrix.content_hash)
        assert _build(store).content_hash == matrix.content_hash

    def test_assembled_at_is_campaign_created_at(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        assert matrix.assembled_at == store.get_campaign(TENANT, "campaign-1").created_at
        assert matrix.assembled_at.tzinfo is not None

    def test_repeated_builds_byte_identical(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        first = _build(store)
        second = _build(store)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_inputs_never_mutated(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        before = (
            campaign.model_dump(mode="json"),
            trajectory_matrix.model_dump(mode="json"),
            tuple(s.model_dump(mode="json") for s in observation_sets),
        )
        build_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        after = (
            campaign.model_dump(mode="json"),
            trajectory_matrix.model_dump(mode="json"),
            tuple(s.model_dump(mode="json") for s in observation_sets),
        )
        assert after == before

    def test_common_binding_provenance_agrees_across_cells(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        for position in range(2):
            references = [
                cell.observations[position].model_dump(mode="json") for cell in matrix.cells
            ]
            first = dict(references[0])
            first.pop("trajectory_plan_id")
            first.pop("trajectory_plan_content_hash")
            first.pop("trajectory_result_content_hash")
            first.pop("raw_value")
            for reference in references[1:]:
                comparable = dict(reference)
                comparable.pop("trajectory_plan_id")
                comparable.pop("trajectory_plan_content_hash")
                comparable.pop("trajectory_result_content_hash")
                comparable.pop("raw_value")
                assert comparable == first

    def test_run_specific_plan_result_provenance_may_differ_and_is_preserved(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, fixture_run_ids = complete_store
        matrix = _build(store)
        plan_ids = {cell.observations[0].trajectory_plan_id for cell in matrix.cells}
        plan_hashes = {cell.observations[0].trajectory_plan_content_hash for cell in matrix.cells}
        result_hashes = {
            cell.observations[0].trajectory_result_content_hash for cell in matrix.cells
        }
        # Different strategies receive distinct plan identifiers, so the
        # run-specific provenance legitimately differs across cells.
        assert len(plan_ids) > 1
        assert len(plan_hashes) > 1
        assert len(result_hashes) > 1
        # The matrix preserved each cell's exact recorded provenance.
        for cell, run_id in zip(matrix.cells, fixture_run_ids, strict=True):
            stored = store.get_run_metric_observation_set(TENANT, run_id)
            assert (
                cell.observations[0].trajectory_plan_id == stored.observations[0].trajectory_plan_id
            )
            assert (
                cell.observations[0].trajectory_plan_content_hash
                == stored.observations[0].trajectory_plan_content_hash
            )
            assert (
                cell.observations[0].trajectory_result_content_hash
                == stored.observations[0].trajectory_result_content_hash
            )

    def test_every_cell_empty_when_world_has_no_bindings(
        self, empty_bindings_store: InMemoryScenarioStore
    ) -> None:
        store = empty_bindings_store
        matrix = _build(store)
        assert matrix.ordered_metric_ids == ()
        assert len(matrix.cells) == 5
        assert all(cell.observations == () for cell in matrix.cells)

    def test_matrix_is_frozen_and_self_consistent(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        matrix = _build(store)
        assert (
            CampaignMetricObservationMatrix.model_validate(matrix.model_dump(mode="json")) == matrix
        )


class TestRejections:
    @staticmethod
    def _reject(
        *,
        campaign: CampaignSpec,
        trajectory_matrix: CampaignTrajectoryMatrix,
        observation_sets: tuple[RunMetricObservationSet, ...],
    ) -> None:
        build_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )

    def test_missing_observation_set_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=observation_sets[:-1],
            )

    def test_additional_observation_set_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=observation_sets + (observation_sets[0],),
            )

    def test_duplicated_observation_set_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(observation_sets[0],) + observation_sets,
            )

    def test_reordered_observation_sets_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=observation_sets[::-1],
            )

    def test_foreign_tenant_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"tenant_id": OTHER_TENANT})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_campaign_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"campaign_id": "campaign-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_scenario_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"scenario_id": "scenario-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_world_identifier_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"world_version_id": "world-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_world_content_hash_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"world_content_hash": "f" * 64})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_matrix_runtime_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = trajectory_matrix.model_copy(update={"runtime_version": "1.0.0"})
        with pytest.raises(UnsupportedRuntimeVersionError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=tampered,
                observation_sets=observation_sets,
            )

    def test_set_runtime_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"runtime_version": "1.0.0"})
        with pytest.raises(UnsupportedRuntimeVersionError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_strategy_order_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = trajectory_matrix.model_copy(
            update={
                "ordered_strategy_candidate_ids": list(
                    reversed(trajectory_matrix.ordered_strategy_candidate_ids)
                )
            }
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=tampered,
                observation_sets=observation_sets,
            )

    def test_seed_order_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = trajectory_matrix.model_copy(
            update={
                "ordered_scenario_seed_ids": list(
                    reversed(trajectory_matrix.ordered_scenario_seed_ids)
                )
            }
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=tampered,
                observation_sets=observation_sets,
            )

    def test_run_id_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"run_id": "run-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_run_plan_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"run_plan_id": "plan-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_strategy_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"strategy_candidate_id": "mock-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_seed_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"scenario_seed_id": "seed-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_input_hash_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"input_hash": "f" * 64})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_trajectory_execution_identifier_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(
            update={"trajectory_execution_id": "trajectory-execution-other"}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_trajectory_execution_hash_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(
            update={"trajectory_execution_content_hash": "f" * 64}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )

    def test_differing_metric_collections_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[1].model_copy(
            update={"observations": observation_sets[1].observations[:-1]}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(observation_sets[0], tampered) + observation_sets[2:],
            )

    def test_differing_binding_provenance_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered_value = (
            observation_sets[1]
            .observations[0]
            .model_copy(update={"binding_id": "observation-other"})
        )
        tampered = observation_sets[1].model_copy(
            update={"observations": (tampered_value,) + observation_sets[1].observations[1:]}
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(observation_sets[0], tampered) + observation_sets[2:],
            )

    def test_campaign_vs_trajectory_matrix_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = campaign.model_copy(update={"identifier": "campaign-other"})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=tampered,
                trajectory_matrix=trajectory_matrix,
                observation_sets=observation_sets,
            )

    def test_cell_position_mismatch_rejected(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        cells = trajectory_matrix.cells
        tampered_cell = cells[0].model_copy(update={"strategy_position": 1})
        tampered = trajectory_matrix.model_copy(update={"cells": (tampered_cell,) + cells[1:]})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            self._reject(
                campaign=campaign,
                trajectory_matrix=tampered,
                observation_sets=observation_sets,
            )

    def test_failure_messages_never_leak_internal_details(
        self, complete_store: tuple[InMemoryScenarioStore, str, tuple[str, ...]]
    ) -> None:
        store, _world_id, _run_ids = complete_store
        campaign, trajectory_matrix, observation_sets = _builder_inputs(store)
        tampered = observation_sets[0].model_copy(update={"input_hash": "f" * 64})
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError) as exc_info:
            self._reject(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(tampered,) + observation_sets[1:],
            )
        message = str(exc_info.value)
        assert "f" * 64 not in message
        assert "input hash" not in message
        assert "1.5" not in message
        assert "ratio" not in message
        assert message == (
            "Campaign 'campaign-1' failed metric observation matrix integrity "
            "verification and was rejected"
        )
