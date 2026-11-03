"""Forecast and score contract shape validation."""

from __future__ import annotations

from typing import Any, cast

import pytest
from kalhas.contracts.v1.benchmark_forecast import (
    BenchmarkScoreReport,
    ForecastSet,
    ScoreCell,
    ScoreSummary,
)
from pydantic import ValidationError

from tests.test_contracts import VALID_PAYLOADS


def test_public_contract_examples_are_frozen() -> None:
    for cls in (ForecastSet, BenchmarkScoreReport):
        item = cls.model_validate(VALID_PAYLOADS[cls])
        with pytest.raises(ValidationError):
            item.identifier = "changed"
        with pytest.raises(ValidationError):
            cls.model_validate({**VALID_PAYLOADS[cls], "extra": 1})
        with pytest.raises(ValidationError):
            cls.model_validate({**VALID_PAYLOADS[cls], "identifier": "wrong"})
        with pytest.raises(ValidationError):
            cls.model_validate({**VALID_PAYLOADS[cls], "metadata": {"bad": object()}})


@pytest.mark.parametrize("value", ["-1.000000", "1.0000000", "1", "nan"])
def test_summary_rejects_invalid_decimal(value: str) -> None:
    with pytest.raises(ValidationError):
        ScoreSummary(
            mean_wis=value,
            mean_absolute_error="0.000000",
            coverage_50="0.000000",
            coverage_95="0.000000",
        )


def test_cell_consistency() -> None:
    good = {
        "path": "series.csv",
        "horizon": 1,
        "evaluable_tasks": 0,
        "inadmissible_origin_tasks": 0,
        "insufficient_history_tasks": 0,
        "candidate": None,
        "reference": None,
        "relative_wis": None,
        "verdict": "inconclusive",
        "verdict_reason": "insufficient_evaluable_tasks",
    }
    ScoreCell.model_validate(good)
    for changes in (
        {"evaluable_tasks": True},
        {"horizon": 0},
        {"verdict": "pass"},
        {"verdict": "fail"},
        {"relative_wis": "0.000000"},
        {"verdict_reason": "reference_score_zero"},
        {"evaluable_tasks": 1},
    ):
        with pytest.raises(ValidationError):
            ScoreCell.model_validate({**good, **changes})


def test_report_limitations_and_order() -> None:
    source = cast(dict[str, Any], VALID_PAYLOADS[BenchmarkScoreReport])
    cell = source["cells"][0]
    changes: dict[str, Any]
    for changes in (
        {"limitations": []},
        {"limitations": ["same", "same"]},
        {"cells": [cell, cell]},
    ):
        with pytest.raises(ValidationError):
            BenchmarkScoreReport.model_validate({**source, **changes})


def test_forecast_file_bounds() -> None:
    source = cast(dict[str, Any], VALID_PAYLOADS[ForecastSet])
    for changes in ({"byte_size": 0}, {"byte_size": 26_214_401}, {"row_count": True}):
        with pytest.raises(ValidationError):
            ForecastSet.model_validate(
                {**source, "forecasts_file": {**source["forecasts_file"], **changes}}
            )


def test_report_sorted_and_score_shapes() -> None:
    source = cast(dict[str, Any], VALID_PAYLOADS[BenchmarkScoreReport])
    cell = source["cells"][0]
    with pytest.raises(ValidationError):
        BenchmarkScoreReport.model_validate(
            {**source, "cells": [{**cell, "path": "z.csv"}, {**cell, "path": "a.csv"}]}
        )
    for field in ("coverage_50", "coverage_95"):
        data = {
            "mean_wis": "0.000000",
            "mean_absolute_error": "0.000000",
            "coverage_50": "0.000000",
            "coverage_95": "0.000000",
        }
        with pytest.raises(ValidationError):
            ScoreSummary.model_validate({**data, field: "1.000001"})
    summary = {
        "mean_wis": "1.000000",
        "mean_absolute_error": "1.000000",
        "coverage_50": "0.000000",
        "coverage_95": "0.000000",
    }
    base = {
        **cell,
        "evaluable_tasks": 1,
        "candidate": summary,
        "reference": summary,
        "relative_wis": "1.000000",
    }
    for verdict, reason in (
        ("pass", "below_threshold"),
        ("fail", "not_below_threshold"),
        ("inconclusive", "insufficient_evaluable_tasks"),
    ):
        ScoreCell.model_validate({**base, "verdict": verdict, "verdict_reason": reason})
    for changes in (
        {"candidate": None},
        {"reference": None},
        {"verdict": "pass", "verdict_reason": "below_threshold", "relative_wis": None},
        {"verdict": "fail", "verdict_reason": "below_threshold"},
        {
            "verdict": "inconclusive",
            "verdict_reason": "reference_score_zero",
            "relative_wis": "1.000000",
        },
    ):
        with pytest.raises(ValidationError):
            ScoreCell.model_validate({**base, **changes})
