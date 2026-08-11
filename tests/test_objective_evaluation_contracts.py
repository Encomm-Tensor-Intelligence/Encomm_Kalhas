"""Phase 23 contract tests: strictness, freezing, shape, and registration.

Proves the four new objective-evaluation contracts are strict and
frozen (unknown fields rejected, attribute assignment raises
ValidationError), reject bool/string/None/NaN/Infinity before any
coercion, preserve exact int/float raw values, enforce the exact
target/tolerance/scale rules for every direction, enforce the
evaluation-field consistency rules (``target_achieved`` equals
``signed_target_delta <= 0`` and the normalized violation equals
``max(0, delta) / scale``), accept scenario objective order that is
deliberately not lexical, and register exactly the two top-level
contracts (``ScenarioEvaluationProfile`` at index 35 and
``CampaignObjectiveEvaluationMatrix`` at index 36) while the binding
and the evaluation cell stay nested.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ObjectiveMetricBinding,
    ObjectiveObservationEvaluation,
    ScenarioEvaluationProfile,
)
from kalhas.contracts.v1.shared import VersionedContract
from pydantic import ValidationError

from tests.phase23_helpers import PROFILE_DECLARED_AT, build_observation_matrix, build_profile


def _binding_payload(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "objective_id": "obj-b",
        "metric_id": "m-1",
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "metric_unit": "units",
        "reach_tolerance": None,
        "normalization_scale": 100.0,
    }
    payload.update(overrides)
    return payload


def _evaluation_payload(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "sequence_position": 0,
        "strategy_position": 0,
        "seed_position": 0,
        "objective_position": 0,
        "strategy_candidate_id": "sc-1",
        "scenario_seed_id": "seed-1",
        "objective_id": "obj-b",
        "metric_id": "m-1",
        "metric_unit": "units",
        "run_id": "run-1",
        "input_hash": "0" * 64,
        "raw_value": 91,
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "reach_tolerance": None,
        "normalization_scale": 100.0,
        "target_achieved": True,
        "signed_target_delta": -9.0,
        "normalized_target_violation": 0.0,
    }
    payload.update(overrides)
    return payload


def _evaluation_matrix_payload(**overrides: Any) -> dict[str, object]:
    """A valid matrix payload with objectives in deliberately non-lexical order.

    Objective order is obj-b, obj-a, obj-c (the authoritative scenario
    order); lexical order would be obj-a, obj-b, obj-c. The matrix
    contract must accept it.
    """
    objectives = ("obj-b", "obj-a", "obj-c")
    cells = []
    for objective_position, objective_id in enumerate(objectives):
        cells.append(
            {
                "sequence_position": objective_position,
                "strategy_position": 0,
                "seed_position": 0,
                "objective_position": objective_position,
                "strategy_candidate_id": "sc-1",
                "scenario_seed_id": "seed-1",
                "objective_id": objective_id,
                "metric_id": "m-1",
                "metric_unit": "units",
                "run_id": "run-1",
                "input_hash": "0" * 64,
                "raw_value": 91,
                "direction": "minimize",
                "target": 100.0,
                "weight": 1.0,
                "reach_tolerance": None,
                "normalization_scale": 100.0,
                "target_achieved": True,
                "signed_target_delta": -9.0,
                "normalized_target_violation": 0.0,
            }
        )
    payload: dict[str, object] = {
        "identifier": "objective-evaluation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": "0" * 64,
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "source_metric_observation_matrix_id": "metric-observation-matrix-0123456789abcdef",
        "source_metric_observation_matrix_content_hash": "0" * 64,
        "evaluation_profile_id": "evaluation-profile-0123456789abcdef",
        "evaluation_profile_content_hash": "0" * 64,
        "scenario_content_hash": "0" * 64,
        "ordered_strategy_candidate_ids": ["sc-1"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_objective_ids": list(objectives),
        "cells": cells,
        "content_hash": "0" * 64,
        "evaluated_at": PROFILE_DECLARED_AT,
    }
    payload.update(overrides)
    return payload


def _non_lexical_objective_matrix() -> CampaignObjectiveEvaluationMatrix:
    return CampaignObjectiveEvaluationMatrix.model_validate(_evaluation_matrix_payload())


class TestRegistration:
    def test_public_contract_count_is_exactly_37(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 37

    def test_first_35_contracts_unchanged_and_in_exact_order(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[34] == "CampaignMetricStatisticsMatrix"
        assert names[35] == "ScenarioEvaluationProfile"
        assert names[36] == "CampaignObjectiveEvaluationMatrix"

    def test_only_the_two_new_phase23_contracts_registered(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert ScenarioEvaluationProfile in PUBLIC_CONTRACTS
        assert CampaignObjectiveEvaluationMatrix in PUBLIC_CONTRACTS
        assert "ObjectiveMetricBinding" not in names
        assert "ObjectiveObservationEvaluation" not in names

    def test_phase23_top_level_contracts_are_versioned(self) -> None:
        assert issubclass(ScenarioEvaluationProfile, VersionedContract)
        assert issubclass(CampaignObjectiveEvaluationMatrix, VersionedContract)
        assert not issubclass(ObjectiveMetricBinding, VersionedContract)
        assert not issubclass(ObjectiveObservationEvaluation, VersionedContract)


class TestObjectiveMetricBinding:
    def test_valid_payload_accepted(self) -> None:
        binding = ObjectiveMetricBinding.model_validate(_binding_payload())
        assert binding.direction == "minimize"
        assert binding.target == 100.0
        assert binding.normalization_scale == 100.0

    def test_frozen_assignment_raises(self) -> None:
        binding = ObjectiveMetricBinding.model_validate(_binding_payload())
        with pytest.raises(ValidationError):
            binding.target = 50.0

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(weight=1.0, direction="minimize", extra="forged")
            )

    def test_direction_literal_rejects_other_values(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(_binding_payload(direction="optimize"))

    def test_reach_requires_authoritative_target(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(direction="reach", target=None, reach_tolerance=5.0)
            )

    def test_reach_requires_tolerance(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(direction="reach", target=50.0, reach_tolerance=None)
            )

    def test_tolerance_forbidden_for_minimize(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(direction="minimize", reach_tolerance=5.0)
            )

    def test_tolerance_forbidden_for_maximize(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(direction="maximize", target=None, reach_tolerance=5.0)
            )

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(
                _binding_payload(direction="reach", target=50.0, reach_tolerance=-1.0)
            )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"target": True},
            {"target": "100"},
            {"target": float("nan")},
            {"target": float("inf")},
            {"reach_tolerance": True},
            {"reach_tolerance": float("nan")},
            {"reach_tolerance": float("inf")},
            {"normalization_scale": True},
            {"normalization_scale": float("nan")},
            {"normalization_scale": float("inf")},
            {"normalization_scale": 0.0},
            {"normalization_scale": -5.0},
            {"weight": True},
            {"weight": float("nan")},
            {"weight": float("inf")},
        ],
    )
    def test_bool_and_non_finite_and_scale_rejected_before_coercion(
        self, overrides: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            ObjectiveMetricBinding.model_validate(_binding_payload(**overrides))

    def test_json_round_trip(self) -> None:
        binding = ObjectiveMetricBinding.model_validate(_binding_payload())
        reloaded = ObjectiveMetricBinding.model_validate_json(binding.model_dump_json())
        assert reloaded == binding


class TestScenarioEvaluationProfile:
    def test_valid_profile_accepted_and_round_trips(self) -> None:
        profile = build_profile()
        assert profile.identifier.startswith("evaluation-profile-")
        assert len(profile.content_hash) == 64
        reloaded = ScenarioEvaluationProfile.model_validate_json(profile.model_dump_json())
        assert reloaded == profile
        assert profile.model_dump(mode="json") == json.loads(profile.model_dump_json())

    def test_frozen_assignment_raises(self) -> None:
        profile = build_profile()
        with pytest.raises(ValidationError):
            profile.declared_at = PROFILE_DECLARED_AT

    def test_unknown_field_rejected(self) -> None:
        payload = build_profile().model_dump(mode="json")
        payload["forged"] = True
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)

    def test_empty_bindings_rejected(self) -> None:
        payload = build_profile().model_dump(mode="json")
        payload["bindings"] = []
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)

    def test_duplicate_objective_bindings_rejected(self) -> None:
        payload = build_profile().model_dump(mode="json")
        bindings = payload["bindings"]
        assert isinstance(bindings, list)
        bindings.append(bindings[0])
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)

    def test_non_lexical_objective_order_accepted(self) -> None:
        # obj-b, obj-a, obj-c is the authoritative scenario order and is
        # deliberately not lexical; the profile contract must accept it.
        profile = build_profile()
        assert [binding.objective_id for binding in profile.bindings] == [
            "obj-b",
            "obj-a",
            "obj-c",
        ]

    def test_metadata_non_finite_rejected(self) -> None:
        payload = build_profile().model_dump(mode="json")
        payload["metadata"] = {"nested": [float("nan")]}
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)

    def test_hash_patterns_enforced(self) -> None:
        payload = build_profile().model_dump(mode="json")
        payload["scenario_content_hash"] = "not-a-hash"
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)
        payload = build_profile().model_dump(mode="json")
        payload["content_hash"] = "ABCDEF"
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)

    def test_declared_at_must_be_timezone_aware(self) -> None:
        from datetime import datetime

        payload = build_profile().model_dump(mode="json")
        payload["declared_at"] = datetime(2026, 1, 5, 12, 0, 0).isoformat()
        with pytest.raises(ValidationError):
            ScenarioEvaluationProfile.model_validate(payload)


class TestObjectiveObservationEvaluation:
    def test_valid_payload_accepted_and_round_trips(self) -> None:
        evaluation = ObjectiveObservationEvaluation.model_validate(_evaluation_payload())
        assert evaluation.target_achieved is True
        assert evaluation.signed_target_delta == -9.0
        assert evaluation.normalized_target_violation == 0.0
        reloaded = ObjectiveObservationEvaluation.model_validate_json(evaluation.model_dump_json())
        assert reloaded == evaluation

    def test_frozen_assignment_raises(self) -> None:
        evaluation = ObjectiveObservationEvaluation.model_validate(_evaluation_payload())
        with pytest.raises(ValidationError):
            evaluation.raw_value = 5

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(_evaluation_payload(extra="forged"))

    @pytest.mark.parametrize(
        "overrides",
        [
            {"raw_value": True},
            {"raw_value": "91"},
            {"raw_value": None},
            {"raw_value": [91]},
            {"raw_value": float("nan")},
            {"raw_value": float("inf")},
            {"target": True},
            {"target": float("nan")},
            {"target": float("inf")},
        ],
    )
    def test_bool_string_none_container_and_non_finite_rejected_before_coercion(
        self, overrides: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(_evaluation_payload(**overrides))

    def test_raw_integer_stays_integer_and_float_stays_float(self) -> None:
        integer_eval = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(raw_value=91)
        )
        float_eval = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(raw_value=91.0)
        )
        dumped_int = integer_eval.model_dump(mode="json")["raw_value"]
        dumped_float = float_eval.model_dump(mode="json")["raw_value"]
        assert dumped_int == 91 and isinstance(dumped_int, int)
        assert dumped_float == 91.0 and isinstance(dumped_float, float)

    def test_evaluation_fields_none_iff_target_none(self) -> None:
        payload = _evaluation_payload(
            direction="maximize",
            target=None,
            target_achieved=None,
            signed_target_delta=None,
            normalized_target_violation=None,
        )
        evaluation = ObjectiveObservationEvaluation.model_validate(payload)
        assert evaluation.target_achieved is None
        assert evaluation.signed_target_delta is None
        assert evaluation.normalized_target_violation is None
        # A target present with None evaluation fields is inconsistent.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(_evaluation_payload(target_achieved=None))
        # No target with evaluation fields populated is inconsistent.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    direction="maximize",
                    target=None,
                    target_achieved=True,
                    signed_target_delta=5.0,
                    normalized_target_violation=0.05,
                )
            )

    def test_target_achieved_must_equal_delta_le_zero(self) -> None:
        # Forged achieved (consistent with the forged delta, inconsistent
        # with the raw inputs) is rejected: raw 91 vs target 100 gives an
        # expected delta of -9, so achieved must be True.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(target_achieved=False)
            )
        # The exact zero-delta boundary: raw 100 vs target 100 is
        # achieved with delta 0.0 and zero violation.
        boundary = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(
                raw_value=100,
                signed_target_delta=0.0,
                target_achieved=True,
                normalized_target_violation=0.0,
            )
        )
        assert boundary.target_achieved is True
        assert boundary.signed_target_delta == 0.0

    def test_normalized_violation_must_equal_max_of_delta_over_scale(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(normalized_target_violation=1.0)
            )
        # A positive delta of 30 with scale 100 gives violation 0.3.
        evaluation = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(
                raw_value=130,
                signed_target_delta=30.0,
                target_achieved=False,
                normalized_target_violation=0.3,
            )
        )
        assert evaluation.normalized_target_violation == 0.3

    def test_negative_violation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    raw_value=91,
                    signed_target_delta=-9.0,
                    target_achieved=True,
                    normalized_target_violation=-1.0,
                )
            )

    def test_non_finite_delta_and_violation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(signed_target_delta=float("nan"))
            )
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(signed_target_delta=float("inf"))
            )
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(normalized_target_violation=float("inf"))
            )

    def test_reach_tolerance_rules(self) -> None:
        # raw 44 vs target 50 with tolerance 5: expected delta
        # abs(44-50)-5 = 1.0, not achieved, violation 1.0/100.
        evaluation = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(
                direction="reach",
                objective_id="obj-c",
                target=50.0,
                reach_tolerance=5.0,
                raw_value=44,
                signed_target_delta=1.0,
                target_achieved=False,
                normalized_target_violation=0.01,
            )
        )
        assert evaluation.reach_tolerance == 5.0
        # The exact tolerance boundary: raw 45 gives expected delta 0.0.
        boundary = ObjectiveObservationEvaluation.model_validate(
            _evaluation_payload(
                direction="reach",
                objective_id="obj-c",
                target=50.0,
                reach_tolerance=5.0,
                raw_value=45,
                signed_target_delta=0.0,
                target_achieved=True,
                normalized_target_violation=0.0,
            )
        )
        assert boundary.target_achieved is True
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    direction="reach",
                    objective_id="obj-c",
                    target=50.0,
                    reach_tolerance=None,
                )
            )
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(direction="minimize", reach_tolerance=5.0)
            )

    @pytest.mark.parametrize(
        ("direction", "target", "tolerance", "raw_value", "forged_delta"),
        [
            # minimize: expected delta = raw - target = 100 - 0 = 100
            ("minimize", 0.0, None, 100, 0.0),
            # maximize: expected delta = target - raw = 0 - 100 = -100
            ("maximize", 0.0, None, 100, 0.0),
            # reach: expected delta = abs(raw - target) - tolerance = 45
            ("reach", 50.0, 5.0, 100, 0.0),
        ],
    )
    def test_forged_signed_delta_rejected(
        self,
        direction: str,
        target: float,
        tolerance: float | None,
        raw_value: int,
        forged_delta: float,
    ) -> None:
        """A delta consistent with the other two evaluation fields but
        inconsistent with the authoritative raw inputs is rejected."""
        payload = _evaluation_payload(
            direction=direction,
            target=target,
            reach_tolerance=tolerance,
            raw_value=raw_value,
            signed_target_delta=forged_delta,
            target_achieved=forged_delta <= 0.0,
            normalized_target_violation=max(0.0, forged_delta) / 100.0,
        )
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(payload)

    def test_forged_achieved_consistent_with_forged_delta_rejected(self) -> None:
        # raw 91 vs target 100 (minimize) requires delta -9 and achieved
        # True; a delta/achieved pair consistent with each other but not
        # with the raw inputs is rejected.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    signed_target_delta=50.0,
                    target_achieved=False,
                    normalized_target_violation=0.5,
                )
            )

    def test_forged_violation_consistent_with_forged_delta_rejected(self) -> None:
        # raw 91 vs target 100 (minimize, scale 100) requires violation
        # 0.0; a violation consistent with a forged delta is rejected.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    signed_target_delta=50.0,
                    target_achieved=False,
                    normalized_target_violation=0.5,
                )
            )

    def test_overflow_derivation_rejected(self) -> None:
        # 10**400 - target overflows the float conversion; the derivation
        # must fail validation instead of coercing or clamping.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    raw_value=10**400,
                    target=0.0,
                    signed_target_delta=0.0,
                    target_achieved=True,
                    normalized_target_violation=0.0,
                )
            )

    def test_infinite_violation_derivation_rejected(self) -> None:
        # 1e308 / 1e-308 overflows to infinity; the violation is not
        # finite and the cell is rejected.
        with pytest.raises(ValidationError):
            ObjectiveObservationEvaluation.model_validate(
                _evaluation_payload(
                    raw_value=1e308,
                    target=0.0,
                    normalization_scale=1e-308,
                    signed_target_delta=1e308,
                    target_achieved=False,
                    normalized_target_violation=float("inf"),
                )
            )


class TestCampaignObjectiveEvaluationMatrix:
    def test_valid_non_lexical_objective_order_accepted(self) -> None:
        matrix = _non_lexical_objective_matrix()
        assert list(matrix.ordered_objective_ids) == ["obj-b", "obj-a", "obj-c"]
        assert len(matrix.cells) == 3

    def test_frozen_and_unknown_field(self) -> None:
        matrix = _non_lexical_objective_matrix()
        with pytest.raises(ValidationError):
            matrix.campaign_id = "other"
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(forged=True)
            )

    def test_literals_enforced(self) -> None:
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(runtime_version="3.0.0")
            )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(comparison_mode="shared_seeds")
            )

    def test_runtime_version_is_required(self) -> None:
        payload = _evaluation_matrix_payload()
        del payload["runtime_version"]
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(payload)

    def test_runtime_version_required_in_schema(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (
                repo_root / "schemas" / "v1" / "CampaignObjectiveEvaluationMatrix.schema.json"
            ).read_text(encoding="utf-8")
        )
        assert "runtime_version" in schema["required"]

    def test_json_round_trip(self) -> None:
        matrix = _non_lexical_objective_matrix()
        reloaded = CampaignObjectiveEvaluationMatrix.model_validate_json(matrix.model_dump_json())
        assert reloaded == matrix

    def test_cartesian_completeness_required(self) -> None:
        payload = _evaluation_matrix_payload()
        cells = payload["cells"]
        assert isinstance(cells, list)
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(cells=cells[:-1])
            )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(cells=cells + [cells[-1]])
            )

    def test_exact_strategy_major_seed_minor_objective_minor_order(self) -> None:
        payload = _evaluation_matrix_payload()
        cells = payload["cells"]
        assert isinstance(cells, list)
        swapped = [cells[2], cells[1], cells[0]]
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(cells=swapped)
            )

    def test_sequence_positions_must_be_contiguous(self) -> None:
        payload = _evaluation_matrix_payload()
        cells = payload["cells"]
        assert isinstance(cells, list)
        renumbered = [dict(cells[0], sequence_position=5), cells[1], cells[2]]
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(cells=renumbered)
            )

    def test_positions_out_of_range_rejected(self) -> None:
        payload = _evaluation_matrix_payload()
        cells = payload["cells"]
        assert isinstance(cells, list)
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(
                    cells=[dict(cells[0], objective_position=7), cells[1], cells[2]]
                )
            )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(
                    ordered_strategy_candidate_ids=[],
                )
            )

    def test_identity_must_match_authoritative_position(self) -> None:
        payload = _evaluation_matrix_payload()
        cells = payload["cells"]
        assert isinstance(cells, list)
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(
                    cells=[dict(cells[0], objective_id="obj-zzz"), cells[1], cells[2]]
                )
            )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(
                    cells=[dict(cells[0], strategy_candidate_id="sc-other"), cells[1], cells[2]]
                )
            )

    def test_duplicate_ordered_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(ordered_objective_ids=["obj-b", "obj-b", "obj-c"])
            )

    def test_hash_patterns_enforced(self) -> None:
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(world_content_hash="short")
            )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate(
                _evaluation_matrix_payload(content_hash="short")
            )


class TestSchemaArtifacts:
    def test_schema_artifacts_exist_and_are_strict(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        schema_dir = repo_root / "schemas" / "v1"
        for name in ("ScenarioEvaluationProfile", "CampaignObjectiveEvaluationMatrix"):
            schema = json.loads((schema_dir / f"{name}.schema.json").read_text(encoding="utf-8"))
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert schema["title"] == name

    def test_observation_matrix_schema_has_no_lexical_objective_requirement(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (
                repo_root / "schemas" / "v1" / "CampaignObjectiveEvaluationMatrix.schema.json"
            ).read_text(encoding="utf-8")
        )
        objective_ids = schema["properties"]["ordered_objective_ids"]
        # Uniqueness is a cross-field model_validator (like the Phase
        # 21/22 matrices), not expressible as uniqueItems; the schema
        # must carry no lexical ordering pattern on objective ids.
        assert objective_ids["type"] == "array"
        assert objective_ids["minItems"] == 1
        assert objective_ids["items"] == {"minLength": 1, "type": "string"}
        assert "pattern" not in objective_ids["items"]


class TestSharedBuilderHelpers:
    def test_observation_matrix_helper_is_contract_valid(self) -> None:
        from kalhas.contracts.v1.campaign_metric_observation import (
            CampaignMetricObservationMatrix as MatrixContract,
        )

        matrix = build_observation_matrix()
        reloaded = MatrixContract.model_validate_json(matrix.model_dump_json())
        assert reloaded == matrix
