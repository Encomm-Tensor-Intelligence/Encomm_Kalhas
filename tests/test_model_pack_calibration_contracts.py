"""Validation of the calibration contract and its nested records."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.model_pack_calibration import ModelPackCalibrationRecord
from pydantic import ValidationError


def payload() -> dict[str, Any]:
    return {
        "identifier": "model-pack-calibration-record-example-1.0.0",
        "tenant_id": "tenant-1",
        "record_id": "example",
        "record_version": "1.0.0",
        "binding_manifest_id": "binding-1",
        "binding_content_hash": "0" * 64,
        "protocol_manifest_id": "protocol-1",
        "protocol_content_hash": "0" * 64,
        "partition": "development",
        "variants": [{"target_path": "x.csv", "variant_id": "default"}],
        "algorithm_id": "kalhas-grid-fitter-v1",
        "algorithm_version": "1.0.0",
        "objective": "mean_relative_wis_over_cells",
        "retention_tolerance": "21/20",
        "max_ensemble_members": 8,
        "reference_forecast_set_id": "reference-1",
        "reference_forecast_set_content_hash": "0" * 64,
        "candidates": [
            {
                "candidate_index": 1,
                "member_id": "candidate-01",
                "configuration_hash": "0" * 64,
                "forecasts_sha256": "0" * 64,
                "objective": "1.000000",
                "objective_exact": "1/1",
                "cells": [
                    {"path": "x.csv", "horizon": 1, "relative_wis": "1.000000", "included": True}
                ],
                "fallback_count": 0,
                "dispatched_step_count": 1,
                "rank": 1,
                "status": "retained",
            }
        ],
        "qualifying_left_out_count": 0,
        "limitations": ["Synthetic fixture."],
        "calibrated_at": datetime(2026, 11, 6, tzinfo=UTC),
        "content_hash": "0" * 64,
        "metadata": {},
    }


def test_round_trip_and_frozen() -> None:
    record = ModelPackCalibrationRecord.model_validate(payload())
    assert ModelPackCalibrationRecord.model_validate_json(record.model_dump_json()) == record
    with pytest.raises(ValidationError):
        record.record_id = "other"
    with pytest.raises(ValidationError):
        record.candidates[0].cells[0].included = False


def test_helpers_are_not_public_contracts() -> None:
    assert not {"CalibrationTargetVariant", "CalibrationCell", "CalibrationCandidate"} & {
        item.__name__ for item in PUBLIC_CONTRACTS
    }


@pytest.mark.parametrize(
    "case",
    [
        "identity",
        "unknown",
        "partition",
        "variants_empty",
        "variants_order",
        "variants_duplicate",
        "algorithm",
        "algorithm_version",
        "objective",
        "tolerance",
        "cap_zero",
        "cap_bool",
        "cap_high",
        "candidates_empty",
        "index",
        "index_bool",
        "member_duplicate",
        "rank_gap",
        "rank_best",
        "retained_cap",
        "left_count",
        "limits_empty",
        "limits_duplicate",
        "cell_missing_score",
        "cell_bool",
        "cell_horizon",
        "cell_duplicate",
        "cell_order",
        "objective_missing",
        "exact_missing",
        "exact_format",
        "exact_reduced",
        "exact_denominator",
        "rank_missing",
        "status_missing",
        "no_objective_status",
        "no_objective_value",
        "negative_count",
        "metadata_nonfinite",
        "metadata_tuple",
    ],
)
def test_invalid_contract(case: str) -> None:
    data = payload()
    candidate = data["candidates"][0]
    cell = candidate["cells"][0]
    if case == "identity":
        data["identifier"] = "other"
    elif case == "unknown":
        data["extra"] = 1
    elif case == "partition":
        data["partition"] = "validation"
    elif case == "variants_empty":
        data["variants"] = []
    elif case == "variants_order":
        data["variants"] = [
            {"target_path": "z.csv", "variant_id": "default"},
            {"target_path": "a.csv", "variant_id": "default"},
        ]
    elif case == "variants_duplicate":
        data["variants"].append(copy.deepcopy(data["variants"][0]))
    elif case == "algorithm":
        data["algorithm_id"] = "other"
    elif case == "algorithm_version":
        data["algorithm_version"] = "2.0.0"
    elif case == "objective":
        data["objective"] = "other"
    elif case == "tolerance":
        data["retention_tolerance"] = "1/1"
    elif case == "cap_zero":
        data["max_ensemble_members"] = 0
    elif case == "cap_bool":
        data["max_ensemble_members"] = True
    elif case == "cap_high":
        data["max_ensemble_members"] = 65
    elif case == "candidates_empty":
        data["candidates"] = []
    elif case == "index":
        candidate["candidate_index"] = 2
    elif case == "index_bool":
        candidate["candidate_index"] = True
    elif case in {"member_duplicate", "rank_gap", "retained_cap"}:
        second = copy.deepcopy(candidate)
        second.update(candidate_index=2, member_id="candidate-02", rank=2)
        data["candidates"].append(second)
        if case == "member_duplicate":
            second["member_id"] = candidate["member_id"]
        elif case == "rank_gap":
            second["rank"] = 3
        else:
            data["max_ensemble_members"] = 1
    elif case == "rank_best":
        candidate["status"] = "not_retained"
    elif case == "left_count":
        data["qualifying_left_out_count"] = 1
    elif case == "limits_empty":
        data["limitations"] = []
    elif case == "limits_duplicate":
        data["limitations"] *= 2
    elif case == "cell_missing_score":
        cell["relative_wis"] = None
    elif case == "cell_bool":
        cell["included"] = 1
    elif case == "cell_horizon":
        cell["horizon"] = 367
    elif case == "cell_duplicate":
        candidate["cells"].append(copy.deepcopy(cell))
    elif case == "cell_order":
        candidate["cells"].insert(0, {**cell, "path": "z.csv"})
    elif case == "objective_missing":
        candidate["objective"] = None
    elif case == "exact_missing":
        candidate["objective_exact"] = None
    elif case == "exact_format":
        candidate["objective_exact"] = "1"
    elif case == "exact_reduced":
        candidate["objective_exact"] = "2/2"
    elif case == "exact_denominator":
        candidate["objective_exact"] = "1/0"
    elif case == "rank_missing":
        candidate["rank"] = None
    elif case == "status_missing":
        candidate["status"] = "no_objective"
    elif case == "no_objective_status":
        cell["included"] = False
    elif case == "no_objective_value":
        cell["included"] = False
        candidate.update(objective=None, objective_exact=None, rank=None, status="retained")
    elif case == "negative_count":
        candidate["fallback_count"] = -1
    elif case == "metadata_nonfinite":
        data["metadata"] = {"x": float("nan")}
    elif case == "metadata_tuple":
        data["metadata"] = {"x": (1,)}
    with pytest.raises(ValidationError):
        ModelPackCalibrationRecord.model_validate(data)
