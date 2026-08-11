"""Phase 21 campaign metric-observation matrix contract tests.

Proves ``CampaignMetricObservationMatrix`` and its nested
``CampaignMetricObservationCell`` are frozen, strict (``extra="forbid"``)
public-contract surfaces that reuse the Phase 20
``RunMetricObservationValue`` directly: exact runtime/comparison literals,
hash patterns, timezone-aware ``assembled_at``, unique and strictly
increasing identifier collections, the complete Cartesian strategy x
seed cell coverage in the exact strategy-major/seed-minor RunPlan order,
contiguous sequence positions, exact per-cell identity/metric binding,
strict raw-value kind validation through the nested Phase 20 contract
(no bool/string/NaN/Infinity, integers stay integers), the empty-matrix
shape, schema round-trip and export, and the exact 35-contract
registration layout with the cell never registered and the statistics
matrix last.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_metric_observation import (
    CampaignMetricObservationCell,
    CampaignMetricObservationMatrix,
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


def _value(
    metric_id: str,
    raw_value: int | float,
    *,
    kind: str,
    cell_index: int,
) -> dict[str, object]:
    """One nested Phase 20 value payload bound to a cell."""
    return {
        "metric_id": metric_id,
        "metric_unit": "units" if metric_id == "m-1" else "percent",
        "binding_id": f"observation-{metric_id}",
        "binding_content_hash": HASH_64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level" if kind == "integer" else "ratio",
        "state_field_value_kind": kind,
        "observation_point": "final_state",
        "trajectory_plan_id": f"trajectory-plan-{cell_index}",
        "trajectory_plan_content_hash": HASH_64,
        "trajectory_result_content_hash": HASH_64,
        "raw_value": raw_value,
    }


def _cell(
    strategy_position: int,
    seed_position: int,
    *,
    strategies: tuple[str, ...] = STRATEGIES,
    seeds: tuple[str, ...] = SEEDS,
    metrics: tuple[str, ...] = METRICS,
    sequence_position: int | None = None,
    observations: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    """One cell payload for the exact strategy x seed position."""
    index = strategy_position * len(seeds) + seed_position
    if observations is None:
        observations = [
            _value(metric_id, 1 if metric_id == "m-1" else 2.5, kind=kind, cell_index=index)
            for metric_id, kind in zip(metrics, ("integer", "number"), strict=False)
        ]
    # Out-of-range positions still need a payload id; the contract
    # validator - not the payload builder - rejects the position.
    strategy_id = (
        strategies[strategy_position]
        if strategy_position < len(strategies)
        else f"sc-out-of-range-{strategy_position}"
    )
    seed_id = (
        seeds[seed_position] if seed_position < len(seeds) else f"seed-out-of-range-{seed_position}"
    )
    payload: dict[str, object] = {
        "sequence_position": index if sequence_position is None else sequence_position,
        "strategy_position": strategy_position,
        "seed_position": seed_position,
        "run_id": f"run-{index}",
        "run_plan_id": f"plan-{index}",
        "strategy_candidate_id": strategy_id,
        "scenario_seed_id": seed_id,
        "input_hash": HASH_64,
        "trajectory_execution_id": f"trajectory-execution-{index}",
        "trajectory_execution_content_hash": HASH_64,
        "metric_observation_set_id": f"metric-observation-set-{index}",
        "metric_observation_set_content_hash": HASH_64,
        "observations": observations,
    }
    payload.update(overrides)
    return payload


def _matrix_payload(
    *,
    strategies: tuple[str, ...] = STRATEGIES,
    seeds: tuple[str, ...] = SEEDS,
    metrics: tuple[str, ...] = METRICS,
    cells: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """The complete valid matrix payload over the Cartesian product."""
    if cells is None:
        cells = [
            _cell(
                strategy_position,
                seed_position,
                strategies=strategies,
                seeds=seeds,
                metrics=metrics,
            )
            for strategy_position in range(len(strategies))
            for seed_position in range(len(seeds))
        ]
    payload: dict[str, object] = {
        "identifier": "metric-observation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": HASH_64,
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": list(strategies),
        "ordered_scenario_seed_ids": list(seeds),
        "ordered_metric_ids": list(metrics),
        "cells": cells,
        "content_hash": HASH_64,
        "assembled_at": NOW,
    }
    return payload


#: Friendly keyword names of the payload builder mapped to the exact
#: matrix payload keys, so ``_matrix`` overrides land on the right field.
_PAYLOAD_KEY_BY_KWARG = {
    "strategies": "ordered_strategy_candidate_ids",
    "seeds": "ordered_scenario_seed_ids",
    "metrics": "ordered_metric_ids",
    "cells": "cells",
}


def _matrix(**overrides: object) -> CampaignMetricObservationMatrix:
    """Validate a matrix payload with the supplied overrides applied."""
    payload = _matrix_payload()
    for key, value in overrides.items():
        payload[_PAYLOAD_KEY_BY_KWARG.get(key, key)] = value
    return CampaignMetricObservationMatrix.model_validate(payload)


class TestRegistration:
    def test_public_contract_count_is_exactly_35(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 37

    def test_matrix_is_registered_last_and_cell_is_not(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert names[-2] == "ScenarioEvaluationProfile"
        assert names[-1] == "CampaignObjectiveEvaluationMatrix"
        assert "CampaignMetricObservationCell" not in names
        assert "CampaignStrategyMetricStatistics" not in names
        assert "ObjectiveMetricBinding" not in names
        assert "ObjectiveObservationEvaluation" not in names

    def test_prior_34_contracts_unchanged_and_in_order(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert tuple(names[:34]) == _PRE_PHASE22_CONTRACTS

    def test_matrix_is_versioned_contract_and_cell_is_not(self) -> None:
        assert issubclass(CampaignMetricObservationMatrix, VersionedContract)
        assert not issubclass(CampaignMetricObservationCell, VersionedContract)

    def test_run_metric_observation_value_reused_directly(self) -> None:
        from kalhas.contracts.v1.run_metric_observation import RunMetricObservationValue

        annotation = str(CampaignMetricObservationCell.model_fields["observations"].annotation)
        assert "tuple[" in annotation
        assert "RunMetricObservationValue" in annotation
        # The matrix/cell never re-declares the value shape: the nested
        # tuple element is the exact Phase 20 contract class.
        matrix = _matrix()
        assert isinstance(matrix.cells[0].observations[0], RunMetricObservationValue)


class TestMatrixShape:
    def test_valid_payload_accepted(self) -> None:
        matrix = _matrix()
        assert matrix.identifier
        assert matrix.tenant_id == "tenant-1"
        assert matrix.schema_version == "1.0.0"

    def test_frozen_matrix_rejects_assignment(self) -> None:
        matrix = _matrix()
        with pytest.raises(ValidationError):
            matrix.cells = ()

    def test_frozen_cell_rejects_assignment(self) -> None:
        cell = CampaignMetricObservationCell.model_validate(_cell(0, 0))
        with pytest.raises(ValidationError):
            cell.run_id = "run-other"

    def test_extra_fields_rejected_on_matrix(self) -> None:
        payload = _matrix_payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            CampaignMetricObservationMatrix.model_validate(payload)

    def test_extra_fields_rejected_on_cell(self) -> None:
        with pytest.raises(ValidationError):
            CampaignMetricObservationCell.model_validate(_cell(0, 0, unexpected=1))

    def test_runtime_literal_is_exactly_200(self) -> None:
        assert get_args(
            CampaignMetricObservationMatrix.model_fields["runtime_version"].annotation
        ) == ("2.0.0",)
        for bad in ("1.0.0", "3.0.0", "2.1.0"):
            with pytest.raises(ValidationError):
                _matrix(runtime_version=bad)

    def test_comparison_mode_is_exactly_identical_conditions(self) -> None:
        assert get_args(
            CampaignMetricObservationMatrix.model_fields["comparison_mode"].annotation
        ) == ("identical_conditions",)
        assert _matrix().comparison_mode == "identical_conditions"
        with pytest.raises(ValidationError):
            _matrix(comparison_mode="different_conditions")

    def test_hash_patterns_enforced(self) -> None:
        for field in (
            "world_content_hash",
            "content_hash",
        ):
            payload = _matrix_payload()
            payload[field] = "z" * 64
            with pytest.raises(ValidationError):
                CampaignMetricObservationMatrix.model_validate(payload)
        for field in (
            "input_hash",
            "trajectory_execution_content_hash",
            "metric_observation_set_content_hash",
        ):
            cell_payload = _cell(0, 0)
            cell_payload[field] = "z" * 64
            with pytest.raises(ValidationError):
                _matrix(cells=[cell_payload])

    def test_assembled_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(assembled_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_assembled_at_round_trips_aware(self) -> None:
        matrix = _matrix()
        assert matrix.assembled_at.tzinfo is not None
        assert matrix.assembled_at == NOW

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

    def test_strategy_seed_and_cell_collections_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(strategies=())
        with pytest.raises(ValidationError):
            _matrix(seeds=())
        with pytest.raises(ValidationError):
            _matrix(cells=[])

    def test_exact_cartesian_cell_count_required(self) -> None:
        cells = [_cell(0, 0), _cell(0, 1), _cell(1, 0)]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)  # one missing
        cells = [
            _cell(0, 0),
            _cell(0, 1),
            _cell(1, 0),
            _cell(1, 1),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)  # one additional

    def test_sequence_positions_must_be_contiguous_from_zero(self) -> None:
        cells = [
            _cell(0, 0, sequence_position=1),
            _cell(0, 1, sequence_position=0),
            _cell(1, 0, sequence_position=2),
            _cell(1, 1, sequence_position=3),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)

    def test_strategy_and_seed_position_bounds(self) -> None:
        cells = [
            _cell(0, 0),
            _cell(0, 1),
            _cell(2, 0),
            _cell(2, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)  # strategy_position out of range
        cells = [
            _cell(0, 0),
            _cell(0, 2),
            _cell(1, 0),
            _cell(1, 2),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)  # seed_position out of range

    def test_exact_strategy_major_seed_minor_order_required(self) -> None:
        cells = [
            _cell(0, 1),
            _cell(0, 0),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)
        cells = [
            _cell(1, 0),
            _cell(0, 0),
            _cell(1, 1),
            _cell(0, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)

    def test_duplicate_strategy_seed_pair_rejected(self) -> None:
        cells = [
            _cell(0, 0),
            _cell(0, 0),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)

    def test_cell_identity_must_match_declared_positions(self) -> None:
        cells = [
            _cell(0, 0),
            _cell(0, 1),
            _cell(1, 0, strategy_candidate_id="sc-1"),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)
        cells = [
            _cell(0, 0),
            _cell(0, 1, scenario_seed_id="seed-1"),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)

    def test_cell_metric_collection_must_equal_ordered_metric_ids(self) -> None:
        # Missing observation.
        cells = [
            _cell(0, 0, observations=[_value("m-1", 1, kind="integer", cell_index=0)]),
            _cell(0, 1),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)
        # Additional observation.
        extra = [
            _value("m-1", 1, kind="integer", cell_index=0),
            _value("m-2", 2.5, kind="number", cell_index=0),
            _value("m-1", 1, kind="integer", cell_index=0),
        ]
        cells = [_cell(0, 0, observations=extra), _cell(0, 1), _cell(1, 0), _cell(1, 1)]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)
        # Duplicate metric in the cell.
        duplicated = [
            _value("m-1", 1, kind="integer", cell_index=0),
            _value("m-1", 1, kind="integer", cell_index=0),
        ]
        cells = [
            _cell(0, 0, observations=duplicated),
            _cell(0, 1),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)
        # Reordered observations.
        reordered = [
            _value("m-2", 2.5, kind="number", cell_index=0),
            _value("m-1", 1, kind="integer", cell_index=0),
        ]
        cells = [
            _cell(0, 0, observations=reordered),
            _cell(0, 1),
            _cell(1, 0),
            _cell(1, 1),
        ]
        with pytest.raises(ValidationError):
            _matrix(cells=cells)

    def test_empty_ordered_metric_ids_accepted_when_every_cell_is_empty(self) -> None:
        matrix = _matrix(
            metrics=(),
            cells=[
                _cell(0, 0, metrics=(), observations=[]),
                _cell(0, 1, metrics=(), observations=[]),
                _cell(1, 0, metrics=(), observations=[]),
                _cell(1, 1, metrics=(), observations=[]),
            ],
        )
        assert matrix.ordered_metric_ids == ()
        assert all(cell.observations == () for cell in matrix.cells)

    def test_empty_ordered_metric_ids_rejected_when_a_cell_has_observations(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                metrics=(),
                cells=[
                    _cell(0, 0),
                    _cell(0, 1, metrics=(), observations=[]),
                    _cell(1, 0, metrics=(), observations=[]),
                    _cell(1, 1, metrics=(), observations=[]),
                ],
            )

    def test_nested_integer_raw_value_remains_integer(self) -> None:
        matrix = _matrix()
        raw = matrix.cells[0].observations[0].raw_value
        assert raw == 1
        assert type(raw) is int
        assert not isinstance(raw, bool)
        raw_float = matrix.cells[0].observations[1].raw_value
        assert raw_float == 2.5
        assert type(raw_float) is float


class TestNestedRawValueValidation:
    """Invalid nested raw values fail through the reused Phase 20 model."""

    def _cell_with_raw_value(self, raw_value: object, kind: str) -> dict[str, object]:
        """A cell whose m-1 value carries the invalid raw input.

        The cell still carries the complete m-1, m-2 collection, so the
        only failing validator is the nested Phase 20 value model.
        """
        first = _value("m-1", 1, kind=kind, cell_index=0)
        first["raw_value"] = raw_value
        first["state_field_value_kind"] = kind
        second = _value("m-2", 2.5, kind="number", cell_index=0)
        return _cell(0, 0, observations=[first, second])

    def test_bool_raw_value_rejected_for_integer_kind(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(True, "integer"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_bool_raw_value_rejected_for_number_kind(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(False, "number"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_string_raw_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value("5", "integer"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_nan_raw_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(float("nan"), "number"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_infinity_raw_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(float("inf"), "number"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_negative_infinity_raw_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(float("-inf"), "number"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )

    def test_invalid_value_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(
                cells=[
                    self._cell_with_raw_value(1, "string"),
                    _cell(0, 1),
                    _cell(1, 0),
                    _cell(1, 1),
                ]
            )


class TestSchema:
    def test_schema_round_trip(self) -> None:
        matrix = _matrix()
        dumped = matrix.model_dump_json()
        reloaded = CampaignMetricObservationMatrix.model_validate_json(dumped)
        assert reloaded == matrix
        assert matrix.model_dump(mode="json") == json.loads(dumped)

    def test_schema_export_has_nested_definitions_without_cell_artifact(self) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        schemas = generate_schemas()
        assert "CampaignMetricObservationMatrix.schema.json" in schemas
        assert "CampaignMetricObservationCell.schema.json" not in schemas
        assert "RunMetricObservationValue.schema.json" not in schemas
        rendered = json.loads(schemas["CampaignMetricObservationMatrix.schema.json"])
        assert "$defs" in rendered
        assert "CampaignMetricObservationCell" in rendered["$defs"]
        assert "RunMetricObservationValue" in rendered["$defs"]
        properties = rendered["properties"]
        assert properties["runtime_version"]["const"] == "2.0.0"
        assert properties["comparison_mode"]["const"] == "identical_conditions"
        assert properties["cells"]["items"]["$ref"].endswith("CampaignMetricObservationCell")
        cell_def = rendered["$defs"]["CampaignMetricObservationCell"]
        assert cell_def["additionalProperties"] is False
        assert cell_def["properties"]["observations"]["items"]["$ref"].endswith(
            "RunMetricObservationValue"
        )
        value_def = rendered["$defs"]["RunMetricObservationValue"]
        assert value_def["additionalProperties"] is False
        assert value_def["properties"]["raw_value"]["anyOf"] == [
            {"type": "integer"},
            {"type": "number"},
        ]
        assert value_def["properties"]["state_field_value_kind"]["enum"] == ["integer", "number"]
        assert value_def["properties"]["observation_point"]["const"] == "final_state"

    def test_on_disk_schema_artifact_matches_generated(self) -> None:
        from pathlib import Path

        from kalhas.contracts.schema_export import generate_schemas

        artifact = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "v1"
            / "CampaignMetricObservationMatrix.schema.json"
        )
        assert artifact.exists()
        assert json.loads(artifact.read_text(encoding="utf-8")) == json.loads(
            generate_schemas()["CampaignMetricObservationMatrix.schema.json"]
        )

    def test_matrix_json_schema_is_forbid_and_frozen_shape(self) -> None:
        schema = CampaignMetricObservationMatrix.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "required" in schema
        for required in (
            "campaign_id",
            "world_version_id",
            "runtime_version",
            "ordered_strategy_candidate_ids",
            "ordered_scenario_seed_ids",
            "ordered_metric_ids",
            "cells",
            "content_hash",
            "assembled_at",
        ):
            assert required in schema["required"]


def test_any_unregistered_nested_contract_is_not_public() -> None:
    registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
    assert "RunMetricObservationValue" not in registered
    assert "CampaignTrajectoryRunCell" not in registered
    assert "CampaignMetricObservationCell" not in registered
    assert "CampaignStrategyMetricStatistics" not in registered
