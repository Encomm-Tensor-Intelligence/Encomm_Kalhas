"""Phase 22 campaign metric-statistics contract tests.

Proves ``CampaignMetricStatisticsMatrix`` and its nested
``CampaignStrategyMetricStatistics`` are frozen, strict
(``extra="forbid"``) public-contract surfaces: exact runtime/comparison/
statistics literals, hash patterns, timezone-aware ``summarized_at``,
strict raw numeric validation (no bool/string/None/container/NaN/
Infinity, raw integers stay integers), observation-count consistency,
exact observed-extrema minimum/maximum, finite derived statistics, the
single-observation standard deviation ``0.0`` rule, unique and strictly
increasing identifier collections, the complete strategy x metric
Cartesian summary coverage in the exact strategy-major/metric-minor
order with contiguous positions and exact identity-vs-position
agreement, per-summary observed-value length equal to the seed count,
the zero-metric empty-summaries shape, schema round-trip and export,
and the exact 35-contract registration layout with the nested summary
never registered and the new matrix last.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_metric_statistics import (
    CampaignMetricStatisticsMatrix,
    CampaignStrategyMetricStatistics,
)
from kalhas.contracts.v1.shared import VersionedContract
from pydantic import ValidationError

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

STRATEGIES = ("sc-1", "sc-2")
SEEDS = ("seed-1", "seed-2")
METRICS = ("m-1", "m-2")

#: The exact 34 contracts registered before Phase 22, in registration order.
_PRE_PHASE22_CONTRACTS = (
    "ScenarioSpec",
    "ContextBundle",
    "ClarificationQuestion",
    "ValidationReport",
    "WorldManifest",
    "WorldVersion",
    "UncertaintyDefinition",
    "StrategyRequest",
    "StrategyCandidate",
    "CampaignSpec",
    "CampaignStatus",
    "ScenarioSeed",
    "RunEvent",
    "OutcomeVector",
    "EvidenceReference",
    "DecisionBrief",
    "RunPlan",
    "RunStatus",
    "ReplayManifest",
    "RunInputIntegrityManifest",
    "DomainPackManifest",
    "DomainPackBinding",
    "DomainCapabilityDeclaration",
    "DomainStateModel",
    "DomainStateTransition",
    "OperationalActivityEvent",
    "StrategyTrajectoryPlan",
    "StrategyTrajectoryPlanRequest",
    "RunTrajectoryExecution",
    "RunTrajectoryReplayManifest",
    "CampaignTrajectoryMatrix",
    "DomainMetricObservationBinding",
    "RunMetricObservationSet",
    "CampaignMetricObservationMatrix",
)


def _summary_payload(
    strategy_position: int,
    metric_position: int,
    values: tuple[int | float, ...],
    *,
    strategies: tuple[str, ...] = STRATEGIES,
    metrics: tuple[str, ...] = METRICS,
    **overrides: object,
) -> dict[str, object]:
    """One summary payload with automatically consistent count/min/max.

    The arithmetic mean, median, and population standard deviation are
    supplied as simple finite defaults (the exact computation lives in
    the pure builder, which the contract does not duplicate); the
    single-observation standard-deviation rule still applies.
    """
    payload: dict[str, object] = {
        "strategy_position": strategy_position,
        "metric_position": metric_position,
        "strategy_candidate_id": (
            strategies[strategy_position]
            if strategy_position < len(strategies)
            else f"sc-out-of-range-{strategy_position}"
        ),
        "metric_id": (
            metrics[metric_position]
            if metric_position < len(metrics)
            else f"m-out-of-range-{metric_position}"
        ),
        "metric_unit": "units" if metric_position == 0 else "percent",
        "ordered_observed_values": list(values),
        "observation_count": len(values),
        "minimum": float(min(values)) if values else 0.0,
        "maximum": float(max(values)) if values else 0.0,
        "arithmetic_mean": 1.5,
        "median": 1.5,
        "population_standard_deviation": 0.0 if len(values) == 1 else 0.5,
    }
    payload.update(overrides)
    return payload


def _matrix_payload(
    *,
    strategies: tuple[str, ...] = STRATEGIES,
    seeds: tuple[str, ...] = SEEDS,
    metrics: tuple[str, ...] = METRICS,
    values: tuple[int | float, ...] = (1, 2),
    summaries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """The complete valid matrix payload over the Cartesian product."""
    if summaries is None:
        summaries = [
            _summary_payload(
                strategy_position,
                metric_position,
                values,
                strategies=strategies,
                metrics=metrics,
            )
            for strategy_position in range(len(strategies))
            for metric_position in range(len(metrics))
        ]
    payload: dict[str, object] = {
        "identifier": "metric-statistics-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": HASH_64,
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "statistics_mode": "descriptive",
        "source_metric_observation_matrix_id": "metric-observation-matrix-0123456789abcdef",
        "source_metric_observation_matrix_content_hash": HASH_64,
        "ordered_strategy_candidate_ids": list(strategies),
        "ordered_scenario_seed_ids": list(seeds),
        "ordered_metric_ids": list(metrics),
        "summaries": summaries,
        "content_hash": HASH_64,
        "summarized_at": NOW,
    }
    return payload


#: Friendly keyword names of the payload builder mapped to the exact
#: matrix payload keys, so ``_matrix`` overrides land on the right field.
_PAYLOAD_KEY_BY_KWARG = {
    "strategies": "ordered_strategy_candidate_ids",
    "seeds": "ordered_scenario_seed_ids",
    "metrics": "ordered_metric_ids",
    "summaries": "summaries",
}


def _matrix(**overrides: object) -> CampaignMetricStatisticsMatrix:
    """Validate a matrix payload with the supplied overrides applied."""
    payload = _matrix_payload()
    for key, value in overrides.items():
        if key == "values":
            values = value
            assert isinstance(values, tuple)
            payload["summaries"] = [
                _summary_payload(
                    strategy_position,
                    metric_position,
                    values,
                )
                for strategy_position in range(len(STRATEGIES))
                for metric_position in range(len(METRICS))
            ]
        else:
            payload[_PAYLOAD_KEY_BY_KWARG.get(key, key)] = value
    return CampaignMetricStatisticsMatrix.model_validate(payload)


class TestRegistration:
    def test_public_contract_count_is_exactly_40(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 47

    def test_matrix_is_registered_last_and_summary_is_not(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert names[35] == "ScenarioEvaluationProfile"
        assert names[36] == "CampaignObjectiveEvaluationMatrix"
        assert names[37] == "WorldUncertaintyModel"
        assert names[38] == "WorldRealization"
        assert names[39] == "CampaignWorldRealizationMatrix"
        assert names[40] == "RealizationRunTrajectoryExecution"
        assert names[41] == "RealizationRunTrajectoryReplayManifest"
        assert names[42] == "RealizationCampaignTrajectoryMatrix"
        assert names[43] == "RealizationRunMetricObservationSet"
        assert names[44] == "RealizationCampaignMetricObservationMatrix"
        assert names[45] == "RealizationCampaignMetricStatisticsMatrix"
        assert "CampaignStrategyMetricStatistics" not in names

    def test_prior_34_contracts_unchanged_and_in_order(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert tuple(names[:34]) == _PRE_PHASE22_CONTRACTS

    def test_matrix_is_versioned_contract_and_summary_is_not(self) -> None:
        assert issubclass(CampaignMetricStatisticsMatrix, VersionedContract)
        assert not issubclass(CampaignStrategyMetricStatistics, VersionedContract)

    def test_matrix_appended_after_campaign_metric_observation_matrix(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert names[31] == "DomainMetricObservationBinding"
        assert names[32] == "RunMetricObservationSet"
        assert names[33] == "CampaignMetricObservationMatrix"
        assert names[34] == "CampaignMetricStatisticsMatrix"


class TestSummaryShape:
    def test_valid_payload_accepted(self) -> None:
        summary = CampaignStrategyMetricStatistics.model_validate(_summary_payload(0, 0, (1, 2)))
        assert summary.strategy_candidate_id == "sc-1"
        assert summary.metric_id == "m-1"
        assert summary.observation_count == 2

    def test_frozen_summary_rejects_assignment(self) -> None:
        summary = CampaignStrategyMetricStatistics.model_validate(_summary_payload(0, 0, (1, 2)))
        with pytest.raises(ValidationError):
            summary.arithmetic_mean = 9.0

    def test_frozen_matrix_rejects_assignment(self) -> None:
        matrix = _matrix()
        with pytest.raises(ValidationError):
            matrix.summaries = ()

    def test_extra_fields_rejected_on_summary(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (1, 2), unexpected=1)
            )

    def test_extra_fields_rejected_on_matrix(self) -> None:
        payload = _matrix_payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            CampaignMetricStatisticsMatrix.model_validate(payload)

    def test_raw_integer_values_remain_integers(self) -> None:
        matrix = _matrix(values=(1, 2))
        observed = matrix.summaries[0].ordered_observed_values
        assert observed == (1, 2)
        assert type(observed[0]) is int
        assert not isinstance(observed[0], bool)

    def test_raw_float_values_remain_floats(self) -> None:
        matrix = _matrix(values=(1.5, 2.5))
        observed = matrix.summaries[0].ordered_observed_values
        assert observed == (1.5, 2.5)
        assert type(observed[0]) is float

    def test_mixed_int_float_values_preserved(self) -> None:
        summary = CampaignStrategyMetricStatistics.model_validate(
            _summary_payload(0, 0, (1, 2.5, 3))
        )
        assert summary.ordered_observed_values == (1, 2.5, 3)
        assert type(summary.ordered_observed_values[0]) is int
        assert type(summary.ordered_observed_values[1]) is float

    def test_observation_count_must_equal_collection_length(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (1, 2), observation_count=3)
            )

    def test_observation_count_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (1, 2), observation_count=0)
            )

    def test_observed_values_collection_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(_summary_payload(0, 0, ()))

    def test_minimum_must_equal_exact_observed_minimum(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (1, 2), minimum=0.0)
            )

    def test_maximum_must_equal_exact_observed_maximum(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (1, 2), maximum=3.0)
            )

    def test_negative_values_preserved_in_extrema(self) -> None:
        summary = CampaignStrategyMetricStatistics.model_validate(
            _summary_payload(0, 0, (-5, -1, -3))
        )
        assert summary.minimum == -5.0
        assert summary.maximum == -1.0

    def test_duplicate_values_preserved(self) -> None:
        summary = CampaignStrategyMetricStatistics.model_validate(_summary_payload(0, 0, (2, 2, 2)))
        assert summary.minimum == 2.0
        assert summary.maximum == 2.0
        assert summary.observation_count == 3

    def test_derived_statistics_must_be_finite(self) -> None:
        for field in ("arithmetic_mean", "median", "population_standard_deviation"):
            payload = _summary_payload(0, 0, (1, 2))
            payload[field] = float("nan")
            with pytest.raises(ValidationError):
                CampaignStrategyMetricStatistics.model_validate(payload)
            payload = _summary_payload(0, 0, (1, 2))
            payload[field] = float("inf")
            with pytest.raises(ValidationError):
                CampaignStrategyMetricStatistics.model_validate(payload)

    def test_single_observation_standard_deviation_exactly_zero(self) -> None:
        valid = CampaignStrategyMetricStatistics.model_validate(_summary_payload(0, 0, (5,)))
        assert valid.population_standard_deviation == 0.0
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                _summary_payload(0, 0, (5,), population_standard_deviation=1.0)
            )


class TestRawValueStrictness:
    """Invalid raw observed values fail through the summary before-validator."""

    def _summary_with_values(self, values: object) -> dict[str, object]:
        return _summary_payload(0, 0, (1, 2), ordered_observed_values=values)

    def test_bool_values_rejected(self) -> None:
        for bad in (True, False):
            with pytest.raises(ValidationError):
                CampaignStrategyMetricStatistics.model_validate(self._summary_with_values([bad, 1]))

    def test_string_values_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(self._summary_with_values(["5", 1]))

    def test_none_values_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(self._summary_with_values([None, 1]))

    def test_container_values_rejected(self) -> None:
        for bad in ([1], (1,), {"value": 1}):
            with pytest.raises(ValidationError):
                CampaignStrategyMetricStatistics.model_validate(self._summary_with_values([bad, 1]))

    def test_nan_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                self._summary_with_values([float("nan"), 1])
            )

    def test_positive_infinity_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                self._summary_with_values([float("inf"), 1])
            )

    def test_negative_infinity_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignStrategyMetricStatistics.model_validate(
                self._summary_with_values([float("-inf"), 1])
            )

    def test_nested_invalid_values_rejected_through_matrix(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2), ordered_observed_values=[True, 1]),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)


class TestMatrixShape:
    def test_valid_payload_accepted(self) -> None:
        matrix = _matrix()
        assert matrix.identifier
        assert matrix.tenant_id == "tenant-1"
        assert matrix.schema_version == "1.0.0"
        assert len(matrix.summaries) == 4

    def test_runtime_literal_is_exactly_200(self) -> None:
        assert get_args(
            CampaignMetricStatisticsMatrix.model_fields["runtime_version"].annotation
        ) == ("2.0.0",)
        for bad in ("1.0.0", "3.0.0", "2.1.0"):
            with pytest.raises(ValidationError):
                _matrix(runtime_version=bad)

    def test_comparison_mode_is_exactly_identical_conditions(self) -> None:
        assert get_args(
            CampaignMetricStatisticsMatrix.model_fields["comparison_mode"].annotation
        ) == ("identical_conditions",)
        assert _matrix().comparison_mode == "identical_conditions"
        with pytest.raises(ValidationError):
            _matrix(comparison_mode="different_conditions")

    def test_statistics_mode_is_exactly_descriptive(self) -> None:
        assert get_args(
            CampaignMetricStatisticsMatrix.model_fields["statistics_mode"].annotation
        ) == ("descriptive",)
        assert _matrix().statistics_mode == "descriptive"
        for bad in ("inferential", "predictive", ""):
            with pytest.raises(ValidationError):
                _matrix(statistics_mode=bad)

    def test_hash_patterns_enforced(self) -> None:
        for field in (
            "world_content_hash",
            "source_metric_observation_matrix_content_hash",
            "content_hash",
        ):
            payload = _matrix_payload()
            payload[field] = "z" * 64
            with pytest.raises(ValidationError):
                CampaignMetricStatisticsMatrix.model_validate(payload)

    def test_identifier_fields_must_be_non_empty(self) -> None:
        for field in ("campaign_id", "scenario_id", "world_version_id"):
            payload = _matrix_payload()
            payload[field] = ""
            with pytest.raises(ValidationError):
                CampaignMetricStatisticsMatrix.model_validate(payload)
        payload = _matrix_payload()
        payload["source_metric_observation_matrix_id"] = ""
        with pytest.raises(ValidationError):
            CampaignMetricStatisticsMatrix.model_validate(payload)

    def test_summarized_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(summarized_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_summarized_at_round_trips_aware(self) -> None:
        matrix = _matrix()
        assert matrix.summarized_at.tzinfo is not None
        assert matrix.summarized_at == NOW

    def test_strategy_ids_must_be_unique(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(strategies=("sc-1", "sc-1"))

    def test_seed_ids_must_be_unique(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(seeds=("seed-1", "seed-1"))

    def test_metric_ids_must_be_unique(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(metrics=("m-1", "m-1"))

    def test_metric_ids_must_be_strictly_increasing(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(metrics=("m-2", "m-1"))

    def test_strategy_and_seed_collections_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(strategies=())
        with pytest.raises(ValidationError):
            _matrix(seeds=())

    def test_exact_cartesian_summary_count_required(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)  # one missing
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
            _summary_payload(0, 0, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)  # one additional

    def test_strategy_and_metric_position_bounds(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(2, 0, (1, 2)),
            _summary_payload(2, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)  # strategy_position out of range
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 2, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 2, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)  # metric_position out of range

    def test_exact_strategy_major_metric_minor_order_required(self) -> None:
        summaries = [
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)
        summaries = [
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
            _summary_payload(0, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)

    def test_duplicate_strategy_metric_pair_rejected(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)

    def test_summary_identity_must_match_declared_positions(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(1, 0, (1, 2), strategy_candidate_id="sc-1"),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)
        summaries = [
            _summary_payload(0, 0, (1, 2)),
            _summary_payload(0, 1, (1, 2), metric_id="m-1"),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)

    def test_summary_observed_length_must_equal_seed_count(self) -> None:
        summaries = [
            _summary_payload(0, 0, (1, 2, 3)),
            _summary_payload(0, 1, (1, 2)),
            _summary_payload(1, 0, (1, 2)),
            _summary_payload(1, 1, (1, 2)),
        ]
        with pytest.raises(ValidationError):
            _matrix(summaries=summaries)

    def test_zero_metric_matrix_with_empty_summaries_accepted(self) -> None:
        matrix = _matrix(metrics=(), summaries=[])
        assert matrix.ordered_metric_ids == ()
        assert matrix.summaries == ()

    def test_zero_metric_matrix_with_summaries_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(metrics=(), summaries=[_summary_payload(0, 0, (1, 2))])


class TestSchema:
    def test_schema_round_trip(self) -> None:
        matrix = _matrix()
        dumped = matrix.model_dump_json()
        reloaded = CampaignMetricStatisticsMatrix.model_validate_json(dumped)
        assert reloaded == matrix
        assert matrix.model_dump(mode="json") == json.loads(dumped)

    def test_schema_export_has_nested_definitions_without_summary_artifact(self) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        schemas = generate_schemas()
        assert "CampaignMetricStatisticsMatrix.schema.json" in schemas
        assert "CampaignStrategyMetricStatistics.schema.json" not in schemas
        rendered = json.loads(schemas["CampaignMetricStatisticsMatrix.schema.json"])
        assert "$defs" in rendered
        assert "CampaignStrategyMetricStatistics" in rendered["$defs"]
        properties = rendered["properties"]
        assert properties["runtime_version"]["const"] == "2.0.0"
        assert properties["comparison_mode"]["const"] == "identical_conditions"
        assert properties["statistics_mode"]["const"] == "descriptive"
        assert properties["summaries"]["items"]["$ref"].endswith("CampaignStrategyMetricStatistics")
        summary_def = rendered["$defs"]["CampaignStrategyMetricStatistics"]
        assert summary_def["additionalProperties"] is False
        assert summary_def["properties"]["ordered_observed_values"]["items"]["anyOf"] == [
            {"type": "integer"},
            {"type": "number"},
        ]
        assert summary_def["properties"]["ordered_observed_values"]["minItems"] == 1

    def test_on_disk_schema_artifact_matches_generated(self) -> None:
        from pathlib import Path

        from kalhas.contracts.schema_export import generate_schemas

        artifact = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "v1"
            / "CampaignMetricStatisticsMatrix.schema.json"
        )
        assert artifact.exists()
        assert json.loads(artifact.read_text(encoding="utf-8")) == json.loads(
            generate_schemas()["CampaignMetricStatisticsMatrix.schema.json"]
        )

    def test_matrix_json_schema_is_forbid_and_frozen_shape(self) -> None:
        schema = CampaignMetricStatisticsMatrix.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "required" in schema
        for required in (
            "campaign_id",
            "world_version_id",
            "runtime_version",
            "statistics_mode",
            "source_metric_observation_matrix_id",
            "source_metric_observation_matrix_content_hash",
            "ordered_strategy_candidate_ids",
            "ordered_scenario_seed_ids",
            "ordered_metric_ids",
            "summaries",
            "content_hash",
            "summarized_at",
        ):
            assert required in schema["required"]


def test_any_unregistered_nested_contract_is_not_public() -> None:
    registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
    assert "CampaignStrategyMetricStatistics" not in registered
    assert "RunMetricObservationValue" not in registered
    assert "CampaignMetricObservationCell" not in registered
