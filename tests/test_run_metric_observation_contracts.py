"""Phase 20 contract tests: run metric observation value and set.

Proves the frozen, strict contracts: exact integer/number raw-value
acceptance with bool/string/coercion rejection, NaN/Infinity rejection,
the 2.0.0 runtime literal, hash patterns, timezone-aware ``observed_at``,
canonical metric-id ordering with duplicate rejection, empty observation
tuples, exact value preservation, schema round-trips, and the
registration of ``RunMetricObservationSet`` as the 33rd public contract
appended after the unchanged 32 existing contracts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.run_metric_observation import (
    RunMetricObservationSet,
    RunMetricObservationValue,
    raw_value_matches_numeric_kind,
)
from pydantic import ValidationError

NOW = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def value_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": "m-1",
        "metric_unit": "units",
        "binding_id": "observation-1",
        "binding_content_hash": HASH_64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": HASH_64,
        "trajectory_result_content_hash": HASH_64,
        "raw_value": 7,
    }
    payload.update(overrides)
    return payload


def set_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "metric-observation-set-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": HASH_64,
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": HASH_64,
        "scenario_seed_id": "seed-1",
        "runtime_version": "2.0.0",
        "input_hash": HASH_64,
        "trajectory_execution_id": "trajectory-execution-1",
        "trajectory_execution_content_hash": HASH_64,
        "observations": [
            value_payload(),
            value_payload(
                metric_id="m-2",
                binding_id="observation-2",
                state_field_id="ratio",
                state_field_value_kind="number",
                raw_value=2.5,
            ),
        ],
        "content_hash": HASH_64,
        "observed_at": NOW,
    }
    payload.update(overrides)
    return payload


def make_value(**overrides: object) -> RunMetricObservationValue:
    return RunMetricObservationValue.model_validate(value_payload(**overrides))


def make_set(**overrides: object) -> RunMetricObservationSet:
    return RunMetricObservationSet.model_validate(set_payload(**overrides))


class TestRawValueKindRules:
    @pytest.mark.parametrize(
        ("kind", "value"),
        [
            ("integer", 3),
            ("number", 3),
            ("number", 3.0),
            ("number", -2.75),
            ("integer", 0),
        ],
    )
    def test_exact_numeric_acceptance(self, kind: str, value: object) -> None:
        observation = make_value(state_field_value_kind=kind, raw_value=value)
        assert observation.raw_value == value

    @pytest.mark.parametrize(
        ("kind", "value"),
        [
            ("integer", True),
            ("integer", False),
            ("number", True),
            ("number", False),
        ],
    )
    def test_boolean_never_accepted(self, kind: str, value: object) -> None:
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind=kind, raw_value=value)

    def test_float_rejected_for_integer_kind(self) -> None:
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind="integer", raw_value=1.0)

    @pytest.mark.parametrize("value", ["5", "2.5", None, [1], {"a": 1}])
    def test_non_numeric_values_never_coerced(self, value: object) -> None:
        """Strings and other JSON values are rejected, never coerced to numbers."""
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind="number", raw_value=value)
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind="integer", raw_value=value)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_rejected(self, value: float) -> None:
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind="number", raw_value=value)

    def test_nan_rejected_by_after_validator_through_round_trip(self) -> None:
        """NaN survives Python-mode serialization, so the contract rejects it again."""
        bypassed = RunMetricObservationValue.model_construct(
            **cast(
                dict[str, Any],
                {**value_payload(), "state_field_value_kind": "number", "raw_value": float("nan")},
            )
        )
        with pytest.raises(ValidationError):
            RunMetricObservationValue.model_validate(
                bypassed.model_dump(mode="python"), strict=True
            )

    def test_raw_value_preserved_exactly(self) -> None:
        integer = make_value(state_field_value_kind="integer", raw_value=7)
        number = make_value(
            state_field_value_kind="number",
            state_field_id="ratio",
            raw_value=2.5,
        )
        assert integer.raw_value == 7
        assert isinstance(integer.raw_value, int)
        assert number.raw_value == 2.5
        assert isinstance(number.raw_value, float)
        assert integer.model_dump(mode="json")["raw_value"] == 7
        assert number.model_dump(mode="json")["raw_value"] == 2.5

    @pytest.mark.parametrize(
        ("raw", "kind", "expected"),
        [
            (1, "integer", True),
            (1.0, "integer", False),
            (1, "number", True),
            (1.5, "number", True),
            (True, "integer", False),
            (True, "number", False),
            ("1", "number", False),
            (None, "number", False),
            (float("nan"), "number", False),
            (float("inf"), "number", False),
            (1, "string", False),
        ],
    )
    def test_raw_value_matches_numeric_kind_helper(
        self, raw: object, kind: str, expected: bool
    ) -> None:
        assert raw_value_matches_numeric_kind(raw, kind) is expected


class TestValueContractStrictness:
    def test_frozen_value(self) -> None:
        observation = make_value()
        with pytest.raises(ValidationError):
            observation.raw_value = 99

    def test_value_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            make_value(unexpected_field=1)

    def test_value_rejects_invalid_hash_patterns(self) -> None:
        for field in (
            "binding_content_hash",
            "state_model_content_hash",
            "trajectory_plan_content_hash",
            "trajectory_result_content_hash",
        ):
            with pytest.raises(ValidationError):
                make_value(**{field: "not-a-hash"})

    def test_value_observation_point_literal(self) -> None:
        with pytest.raises(ValidationError):
            make_value(observation_point="initial_state")
        assert make_value().observation_point == "final_state"

    def test_value_value_kind_literal(self) -> None:
        with pytest.raises(ValidationError):
            make_value(state_field_value_kind="string")

    def test_value_metric_unit_optional(self) -> None:
        assert make_value(metric_unit=None).metric_unit is None
        assert make_value(metric_unit="percent").metric_unit == "percent"


class TestSetContractStrictness:
    def test_frozen_set(self) -> None:
        observation_set = make_set()
        with pytest.raises(ValidationError):
            observation_set.run_id = "run-other"

    def test_set_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            make_set(unexpected_field=1)

    def test_runtime_version_literal(self) -> None:
        for bad in ("1.0.0", "3.0.0", "2.0"):
            with pytest.raises(ValidationError):
                make_set(runtime_version=bad)
        assert make_set().runtime_version == "2.0.0"

    def test_hash_patterns(self) -> None:
        for field in (
            "world_content_hash",
            "strategy_content_hash",
            "input_hash",
            "trajectory_execution_content_hash",
            "content_hash",
        ):
            with pytest.raises(ValidationError):
                make_set(**{field: "z" * 64})

    def test_observed_at_requires_timezone(self) -> None:
        with pytest.raises(ValidationError):
            make_set(observed_at=datetime(2026, 1, 5, 12, 0, 0))
        assert make_set().observed_at == NOW

    def test_observed_at_any_timezone_aware_value_accepted(self) -> None:
        offset = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC) + timedelta(hours=2)
        observation_set = make_set(observed_at=offset)
        assert observation_set.observed_at == offset

    def test_empty_observation_tuple_valid(self) -> None:
        observation_set = make_set(observations=[])
        assert observation_set.observations == ()

    def test_canonical_metric_order_required(self) -> None:
        with pytest.raises(ValidationError):
            make_set(
                observations=[
                    value_payload(metric_id="m-2", binding_id="observation-2", raw_value=1),
                    value_payload(),
                ]
            )

    def test_duplicate_metric_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_set(
                observations=[
                    value_payload(),
                    value_payload(binding_id="observation-2", raw_value=2),
                ]
            )

    def test_equivalent_insertion_orders_are_rejected_not_silently_reordered(self) -> None:
        """The contract never reorders: non-canonical input is rejected outright."""
        with pytest.raises(ValidationError):
            make_set(
                observations=[
                    value_payload(metric_id="m-2", binding_id="observation-2", raw_value=1),
                    value_payload(metric_id="m-1", raw_value=2),
                ]
            )


class TestSerialization:
    def test_canonical_json_round_trip(self) -> None:
        observation_set = make_set()
        dumped = observation_set.model_dump_json()
        reloaded = RunMetricObservationSet.model_validate_json(dumped)
        assert reloaded == observation_set
        assert observation_set.model_dump(mode="json") == json.loads(dumped)

    def test_value_json_round_trip(self) -> None:
        observation = make_value(
            state_field_value_kind="number", state_field_id="ratio", raw_value=2.5
        )
        dumped = observation.model_dump_json()
        reloaded = RunMetricObservationValue.model_validate_json(dumped)
        assert reloaded == observation

    def test_schema_round_trip_via_schema_export(self) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        schemas = generate_schemas()
        rendered = json.loads(schemas["RunMetricObservationSet.schema.json"])
        assert rendered["title"] == "RunMetricObservationSet"
        properties = rendered["properties"]
        assert properties["runtime_version"]["const"] == "2.0.0"
        assert properties["observed_at"]["format"] == "date-time"
        assert properties["observations"]["type"] == "array"
        value_ref = properties["observations"]["items"]["$ref"]
        assert value_ref.endswith("RunMetricObservationValue")
        # The nested value contract is not a top-level public contract and
        # therefore has no standalone exported artifact; its schema is
        # exercised through the set schema and the model itself.
        assert "RunMetricObservationValue.schema.json" not in schemas
        value_schema = RunMetricObservationValue.model_json_schema()
        raw = value_schema["properties"]["raw_value"]
        assert raw["anyOf"] == [{"type": "integer"}, {"type": "number"}]
        assert value_schema["additionalProperties"] is False


class TestRegistration:
    def test_public_contract_count_is_at_least_50(self) -> None:
        assert len(PUBLIC_CONTRACTS) >= 50

    def test_set_is_registered_before_the_phase21_matrix(self) -> None:
        assert RunMetricObservationSet in PUBLIC_CONTRACTS
        assert PUBLIC_CONTRACTS[32] is RunMetricObservationSet
        assert PUBLIC_CONTRACTS[33].__name__ == "CampaignMetricObservationMatrix"
        assert PUBLIC_CONTRACTS[34].__name__ == "CampaignMetricStatisticsMatrix"
        assert PUBLIC_CONTRACTS[35].__name__ == "ScenarioEvaluationProfile"
        assert PUBLIC_CONTRACTS[36].__name__ == "CampaignObjectiveEvaluationMatrix"
        assert PUBLIC_CONTRACTS[37].__name__ == "WorldUncertaintyModel"
        assert PUBLIC_CONTRACTS[38].__name__ == "WorldRealization"
        assert PUBLIC_CONTRACTS[39].__name__ == "CampaignWorldRealizationMatrix"
        assert PUBLIC_CONTRACTS[40].__name__ == "RealizationRunTrajectoryExecution"
        assert PUBLIC_CONTRACTS[41].__name__ == "RealizationRunTrajectoryReplayManifest"
        assert PUBLIC_CONTRACTS[42].__name__ == "RealizationCampaignTrajectoryMatrix"
        assert PUBLIC_CONTRACTS[43].__name__ == "RealizationRunMetricObservationSet"
        assert PUBLIC_CONTRACTS[44].__name__ == "RealizationCampaignMetricObservationMatrix"
        assert PUBLIC_CONTRACTS[45].__name__ == "RealizationCampaignMetricStatisticsMatrix"

    def test_previous_32_contracts_unchanged_and_set_appended(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[:31] == (
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
        )
        assert names[31] == "DomainMetricObservationBinding"
        assert names[32] == "RunMetricObservationSet"
        assert DomainMetricObservationBinding in PUBLIC_CONTRACTS

    def test_value_is_not_a_top_level_contract(self) -> None:
        registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "RunMetricObservationValue" not in registered
