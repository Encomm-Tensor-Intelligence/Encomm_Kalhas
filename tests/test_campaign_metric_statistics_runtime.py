"""Phase 22 pure runtime tests: exact descriptive statistics and the deterministic builder.

Proves the one fixed descriptive-statistics algorithm (minimum,
maximum, arithmetic mean, median, population standard deviation -
Python standard library only, ``math.fsum``/``math.sqrt``, population
denominator N) with exact float expectations on odd/even medians,
mixed int/float inputs, negative values, duplicates, and the
single-observation ``0.0`` rule; and proves the pure builder derives
the complete statistics matrix from a completely verified Phase 21
``CampaignMetricObservationMatrix`` - exact seed-order preservation
(never sorted or repaired), raw integers stay integers, deterministic
identifier/hash/``summarized_at``, byte-identical repeated builds, no
input mutation, the zero-metric empty-summaries shape, and the full
tamper matrix: reordered/tampered cells, wrong strategy/seed/metric
identity, inconsistent unit or binding provenance, missing/additional
metric values, bool/non-finite/wrong-kind validator-bypass tampering,
huge integers and non-finite derived calculations, and no partial
result. Tampering is always self-consistent (content hash recomputed)
so exactly the check under test fires, and never mutates the store.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from kalhas.application.campaign_metric_statistics_runtime import (
    build_campaign_metric_statistics_matrix,
    campaign_metric_statistics_matrix_content_hash,
    campaign_metric_statistics_matrix_identifier,
    statistics_arithmetic_mean,
    statistics_maximum,
    statistics_median,
    statistics_minimum,
    statistics_population_standard_deviation,
)
from kalhas.application.domain_errors import (
    CampaignMetricStatisticsIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.scenario import ScenarioSeed

from tests.phase4_helpers import build_seed
from tests.phase22_helpers import (
    replace_cell,
    self_consistent_copy,
    tamper_observation,
    verified_observation_campaign,
)

SEEDS = (build_seed(identifier="seed-1"), build_seed(identifier="seed-2"))
TWO_SEEDS = (build_seed(identifier="seed-1"), build_seed(identifier="seed-2"))
THREE_SEEDS = (
    build_seed(identifier="seed-1"),
    build_seed(identifier="seed-2"),
    build_seed(identifier="seed-3"),
)


class TestExactAlgorithm:
    """The one fixed descriptive-statistics definition, asserted exactly."""

    def test_arithmetic_mean(self) -> None:
        assert statistics_arithmetic_mean((1, 2, 3)) == 2.0
        assert statistics_arithmetic_mean((1, 2.5, 3)) == 2.1666666666666665
        assert statistics_arithmetic_mean((-2, 0, 2)) == 0.0
        assert statistics_arithmetic_mean((2, 2, 2)) == 2.0
        assert statistics_arithmetic_mean((7,)) == 7.0

    def test_odd_median(self) -> None:
        assert statistics_median((3, 1, 2)) == 2.0
        assert statistics_median((-5, -10, -20)) == -10.0
        assert statistics_median((2,)) == 2.0
        assert statistics_median((1, 2, 2, 3, 4)) == 2.0

    def test_even_median(self) -> None:
        assert statistics_median((1, 2, 3, 4)) == 2.5
        assert statistics_median((1, 3)) == 2.0
        assert statistics_median((1.0, 2.5)) == 1.75
        assert statistics_median((2, 2, 2, 2)) == 2.0

    def test_minimum_and_maximum(self) -> None:
        assert statistics_minimum((3, -1, 2.5)) == -1.0
        assert statistics_maximum((3, -1, 2.5)) == 3.0
        assert statistics_minimum((5,)) == 5.0
        assert statistics_maximum((5,)) == 5.0
        assert statistics_minimum((-5, -1, -3)) == -5.0
        assert statistics_maximum((-5, -1, -3)) == -1.0

    def test_population_standard_deviation(self) -> None:
        assert statistics_population_standard_deviation((1, 2, 3)) == math.sqrt(2 / 3)
        assert statistics_population_standard_deviation((1, 3)) == 1.0
        assert statistics_population_standard_deviation((1, 2, 3, 4)) == math.sqrt(1.25)
        assert statistics_population_standard_deviation((-2, 0, 2)) == math.sqrt(8 / 3)
        assert statistics_population_standard_deviation((2, 2, 2)) == 0.0

    def test_single_observation_standard_deviation_exactly_zero(self) -> None:
        assert statistics_population_standard_deviation((5,)) == 0.0
        assert statistics_population_standard_deviation((5,)) == 0

    def test_population_denominator_never_n_minus_one(self) -> None:
        # Two observations: population variance of (1,3) is 1.0; the
        # sample (N-1) variance would be 2.0 - the definition uses N.
        assert statistics_population_standard_deviation((1, 3)) == 1.0

    def test_huge_integer_overflow_raises(self) -> None:
        with pytest.raises(OverflowError):
            statistics_minimum((10**400,))
        with pytest.raises(OverflowError):
            statistics_arithmetic_mean((10**400, 1))
        with pytest.raises(OverflowError):
            statistics_median((10**400, 1))


class TestBuilderSuccess:
    def _matrix(
        self, seeds: tuple[ScenarioSeed, ...] = THREE_SEEDS
    ) -> CampaignMetricObservationMatrix:
        _store, matrix, _run_ids = verified_observation_campaign(seeds=seeds)
        return matrix

    def _set_values(
        self,
        matrix: CampaignMetricObservationMatrix,
        *,
        metric_position: int,
        pattern: Callable[[int, int], int | float],
    ) -> CampaignMetricObservationMatrix:
        tampered = matrix
        for cell_index, cell in enumerate(matrix.cells):
            tampered = tamper_observation(
                tampered,
                cell_index,
                metric_position,
                raw_value=pattern(cell.strategy_position, cell.seed_position),
            )
        return tampered

    def test_multi_strategy_multi_seed_multi_metric_calculation(self) -> None:
        matrix = self._matrix()
        # m-1 (integer): 10 + 10*strategy + 10*seed; m-2 (number): 1.5 + strategy + seed.
        matrix = self._set_values(
            matrix, metric_position=0, pattern=lambda s, p: 10 + 10 * s + 10 * p
        )
        matrix = self._set_values(matrix, metric_position=1, pattern=lambda s, p: 1.5 + s + p)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert len(statistics.summaries) == 5 * 2
        # Strategy-major, metric-minor exact order.
        assert [summary.strategy_position for summary in statistics.summaries] == [
            0,
            0,
            1,
            1,
            2,
            2,
            3,
            3,
            4,
            4,
        ]
        assert [summary.metric_position for summary in statistics.summaries] == [
            0,
            1,
            0,
            1,
            0,
            1,
            0,
            1,
            0,
            1,
        ]
        first = statistics.summaries[0]  # strategy 0, m-1
        assert first.ordered_observed_values == (10, 20, 30)
        assert first.observation_count == 3
        assert first.minimum == 10.0
        assert first.maximum == 30.0
        assert first.arithmetic_mean == 20.0
        assert first.median == 20.0
        assert first.population_standard_deviation == 8.16496580927726
        second = statistics.summaries[1]  # strategy 0, m-2
        assert second.ordered_observed_values == (1.5, 2.5, 3.5)
        assert second.minimum == 1.5
        assert second.maximum == 3.5
        assert second.arithmetic_mean == 2.5
        assert second.median == 2.5
        assert second.population_standard_deviation == 0.816496580927726
        third = statistics.summaries[2]  # strategy 1, m-1
        assert third.ordered_observed_values == (20, 30, 40)
        assert third.arithmetic_mean == 30.0
        assert third.median == 30.0
        assert third.population_standard_deviation == 8.16496580927726

    def test_exact_seed_order_preserved_never_sorted(self) -> None:
        matrix = self._matrix()
        matrix = self._set_values(
            matrix, metric_position=0, pattern=lambda s, p: {0: 10, 1: 30, 2: 20}[p]
        )
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (10, 30, 20)
        assert first.arithmetic_mean == 20.0
        assert first.median == 20.0
        assert first.minimum == 10.0
        assert first.maximum == 30.0

    def test_integer_values_remain_integers(self) -> None:
        matrix = self._matrix()
        matrix = self._set_values(
            matrix, metric_position=0, pattern=lambda s, p: 10 + 10 * s + 10 * p
        )
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        observed = statistics.summaries[0].ordered_observed_values
        assert observed == (10, 20, 30)
        assert all(type(value) is int for value in observed)
        assert all(not isinstance(value, bool) for value in observed)

    def test_mixed_int_float_inputs(self) -> None:
        matrix = self._matrix()
        matrix = self._set_values(
            matrix, metric_position=1, pattern=lambda s, p: {0: 1, 1: 2.5, 2: 3}[p]
        )
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        first = statistics.summaries[1]
        assert first.ordered_observed_values == (1, 2.5, 3)
        assert first.arithmetic_mean == 2.1666666666666665
        assert first.median == 2.5
        assert first.population_standard_deviation == math.sqrt(
            (
                (1 - 2.1666666666666665) ** 2
                + (2.5 - 2.1666666666666665) ** 2
                + (3 - 2.1666666666666665) ** 2
            )
            / 3
        )

    def test_negative_values(self) -> None:
        matrix = self._matrix()
        matrix = self._set_values(matrix, metric_position=0, pattern=lambda s, p: -5 - 5 * p)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (-5, -10, -15)
        assert first.minimum == -15.0
        assert first.maximum == -5.0
        assert first.arithmetic_mean == -10.0
        assert first.median == -10.0

    def test_duplicate_values(self) -> None:
        matrix = self._matrix()
        matrix = self._set_values(matrix, metric_position=0, pattern=lambda s, p: 2)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (2, 2, 2)
        assert first.minimum == 2.0
        assert first.maximum == 2.0
        assert first.arithmetic_mean == 2.0
        assert first.median == 2.0
        assert first.population_standard_deviation == 0.0

    def test_single_seed(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign(seeds=SEEDS[:1])
        matrix = tamper_observation(matrix, 0, 0, raw_value=7)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert len(statistics.summaries) == 5 * 2
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (7,)
        assert first.observation_count == 1
        assert first.minimum == 7.0
        assert first.maximum == 7.0
        assert first.arithmetic_mean == 7.0
        assert first.median == 7.0
        assert first.population_standard_deviation == 0.0

    def test_zero_metrics_yields_empty_summaries(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign(with_bindings=False)
        assert matrix.ordered_metric_ids == ()
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert statistics.ordered_metric_ids == ()
        assert statistics.summaries == ()
        assert statistics.campaign_id == "campaign-1"
        assert statistics.source_metric_observation_matrix_id == matrix.identifier
        assert len(statistics.content_hash) == 64

    def test_source_identity_carried_exactly(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign(seeds=SEEDS)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert statistics.source_metric_observation_matrix_id == matrix.identifier
        assert statistics.source_metric_observation_matrix_content_hash == matrix.content_hash
        assert statistics.tenant_id == matrix.tenant_id
        assert statistics.campaign_id == matrix.campaign_id
        assert statistics.scenario_id == matrix.scenario_id
        assert statistics.world_version_id == matrix.world_version_id
        assert statistics.world_content_hash == matrix.world_content_hash
        assert statistics.ordered_strategy_candidate_ids == matrix.ordered_strategy_candidate_ids
        assert statistics.ordered_scenario_seed_ids == matrix.ordered_scenario_seed_ids
        assert statistics.ordered_metric_ids == matrix.ordered_metric_ids

    def test_deterministic_identifier(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign()
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert statistics.identifier.startswith("metric-statistics-matrix-")
        assert len(statistics.identifier) == len("metric-statistics-matrix-") + 16
        assert statistics.identifier == campaign_metric_statistics_matrix_identifier(
            campaign_id=matrix.campaign_id,
            world_version_id=matrix.world_version_id,
            runtime_version=matrix.runtime_version,
            source_metric_observation_matrix_id=matrix.identifier,
        )

    def test_deterministic_content_hash_and_timestamp(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign()
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert statistics.content_hash == campaign_metric_statistics_matrix_content_hash(statistics)
        # summarized_at is the authoritative Phase 21 matrix assembled_at,
        # never the wall clock.
        assert statistics.summarized_at == matrix.assembled_at

    def test_byte_identical_repeated_build(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign()
        first = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        second = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert first == second
        assert first.model_dump_json() == second.model_dump_json()

    def test_no_input_mutation(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign()
        before = matrix.model_dump(mode="json")
        build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        assert matrix.model_dump(mode="json") == before

    def test_summary_identity_matches_positions(self) -> None:
        _store, matrix, _run_ids = verified_observation_campaign(seeds=SEEDS)
        statistics = build_campaign_metric_statistics_matrix(observation_matrix=matrix)
        strategies = matrix.ordered_strategy_candidate_ids
        metrics = matrix.ordered_metric_ids
        for summary in statistics.summaries:
            assert summary.strategy_candidate_id == strategies[summary.strategy_position]
            assert summary.metric_id == metrics[summary.metric_position]
            assert len(summary.ordered_observed_values) == len(matrix.ordered_scenario_seed_ids)


class TestBuilderRejections:
    """Self-consistent tampering: only the check under test can fail."""

    def _verified(
        self, seeds: tuple[ScenarioSeed, ...] = THREE_SEEDS
    ) -> CampaignMetricObservationMatrix:
        _store, matrix, _run_ids = verified_observation_campaign(seeds=seeds)
        return matrix

    def test_reordered_cells_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=self_consistent_copy(matrix, cells=matrix.cells[::-1])
            )

    def test_wrong_strategy_identity_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(matrix, 0, strategy_candidate_id="foreign-strategy")
            )

    def test_wrong_seed_identity_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(matrix, 0, scenario_seed_id="foreign-seed")
            )

    def test_tampered_sequence_position_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(matrix, 0, sequence_position=1)
            )

    def test_tampered_strategy_position_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(matrix, 1, strategy_position=1)
            )

    def test_missing_metric_value_rejected(self) -> None:
        matrix = self._verified()
        cell = matrix.cells[0]
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(matrix, 0, observations=cell.observations[:1])
            )

    def test_additional_metric_value_rejected(self) -> None:
        matrix = self._verified()
        cell = matrix.cells[0]
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(
                    matrix,
                    0,
                    observations=cell.observations + (cell.observations[0],),
                )
            )

    def test_reordered_metric_values_rejected(self) -> None:
        matrix = self._verified()
        cell = matrix.cells[0]
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=replace_cell(
                    matrix,
                    0,
                    observations=tuple(reversed(cell.observations)),
                )
            )

    def test_inconsistent_metric_unit_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, metric_unit="other")
            )

    def test_inconsistent_binding_provenance_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, binding_id="other-binding")
            )

    def test_bool_validator_bypass_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, raw_value=True)
            )
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 1, raw_value=False)
            )

    def test_nan_validator_bypass_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 1, raw_value=float("nan"))
            )

    def test_infinity_validator_bypass_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 1, raw_value=float("inf"))
            )
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 1, raw_value=float("-inf"))
            )

    def test_string_validator_bypass_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, raw_value="5")
            )

    def test_wrong_value_kind_validator_bypass_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, state_field_value_kind="string")
            )

    def test_huge_integer_rejected_without_partial_result(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError) as captured:
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, raw_value=10**400)
            )
        # The safe public message never exposes the internal reason or values.
        assert "integrity" in str(captured.value)
        assert "observed" not in str(captured.value)
        assert "raw" not in str(captured.value)

    def test_non_finite_derived_statistic_rejected(self) -> None:
        matrix = self._verified(seeds=TWO_SEEDS)
        matrix = tamper_observation(matrix, 0, 1, raw_value=1e308)
        matrix = tamper_observation(matrix, 1, 1, raw_value=1e308)
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(observation_matrix=matrix)

    def test_unsupported_runtime_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(UnsupportedRuntimeVersionError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=self_consistent_copy(matrix, runtime_version="3.0.0")
            )

    def test_comparison_mode_tamper_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=self_consistent_copy(
                    matrix, comparison_mode="different_conditions"
                )
            )

    def test_source_identifier_pattern_mismatch_rejected(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=self_consistent_copy(
                    matrix, identifier="metric-observation-matrix-ffffffffffffffff"
                )
            )

    def test_source_content_hash_mismatch_rejected(self) -> None:
        matrix = self._verified()
        # Deliberately NOT self-consistent: the recorded content hash no
        # longer covers the matrix content, so the hash check fires.
        with pytest.raises(CampaignMetricStatisticsIntegrityError):
            build_campaign_metric_statistics_matrix(
                observation_matrix=matrix.model_copy(update={"content_hash": "1" * 64})
            )

    def test_error_message_is_safe_and_generic(self) -> None:
        matrix = self._verified()
        with pytest.raises(CampaignMetricStatisticsIntegrityError) as captured:
            build_campaign_metric_statistics_matrix(
                observation_matrix=tamper_observation(matrix, 0, 0, raw_value=True)
            )
        message = str(captured.value)
        assert message == (
            "Campaign 'campaign-1' failed metric statistics integrity verification and was rejected"
        )
        assert "True" not in message
        assert "raw_value" not in message
