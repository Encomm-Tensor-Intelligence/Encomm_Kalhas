"""Strict benchmark protocol shapes and serialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from pydantic import ValidationError

from tests.test_benchmark_task_engine import chain


def payload() -> dict[str, Any]:
    return chain()[-1].model_dump(mode="json")


@pytest.mark.parametrize("horizons", [[], [2, 1], [1, 1], [0], [367], [True]])
def test_invalid_horizons(horizons: list[object]) -> None:
    data = payload()
    data["targets"][0]["horizons"] = horizons
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("history_window", 0),
        ("history_window", 3661),
        ("history_window", True),
        ("min_history_points", 0),
        ("min_history_points", 3),
        ("min_history_points", True),
        ("minimum_evaluable_tasks", 0),
        ("minimum_evaluable_tasks", True),
        ("non_negative", 1),
    ],
)
def test_invalid_limits(field: str, value: object) -> None:
    data = payload()
    data["targets"][0][field] = value
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate(data)


@pytest.mark.parametrize("threshold", ["0", "1.0000001", "-1", "1e0"])
def test_invalid_threshold(threshold: str) -> None:
    data = payload()
    data["comparison"]["relative_wis_pass_below"] = threshold
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate(data)


@pytest.mark.parametrize(
    "case",
    [
        "columns",
        "unsorted",
        "duplicate",
        "empty_targets",
        "path",
        "quantile_order",
        "quantile_missing",
        "quantile_extra",
        "scoring",
        "note",
        "identity",
        "bad_version",
        "bad_baseline",
        "extra",
        "metadata",
    ],
)
def test_invalid_protocol(case: str) -> None:
    data = payload()
    if case == "columns":
        data["targets"][0]["value_column"] = "day"
    elif case == "unsorted":
        data["targets"].reverse()
    elif case == "duplicate":
        data["targets"][1]["path"] = data["targets"][0]["path"]
    elif case == "empty_targets":
        data["targets"] = []
    elif case == "path":
        data["targets"][0]["path"] = "../x.csv"
    elif case == "quantile_order":
        data["quantile_levels"].reverse()
    elif case == "quantile_missing":
        data["quantile_levels"].pop()
    elif case == "quantile_extra":
        data["quantile_levels"].append("0.99")
    elif case == "scoring":
        data["scoring_rule"] = "other"
    elif case == "note":
        data["preregistration_note"] = " "
    elif case == "identity":
        data["identifier"] = "wrong"
    elif case == "bad_version":
        data["protocol_version"] = "1.0"
    elif case == "bad_baseline":
        data["comparison"]["reference_baseline_version"] = "v1"
    elif case == "extra":
        data["extra"] = 1
    else:
        data["metadata"] = {"bad": float("nan")}
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate(data)


def test_boundaries_immutability_and_helpers() -> None:
    data = payload()
    target = data["targets"][0]
    target.update(horizons=[1, 366], history_window=3660, min_history_points=3660)
    data["comparison"]["relative_wis_pass_below"] = "0.000001"
    model = BenchmarkProtocol.model_validate(data)
    assert BenchmarkProtocol.model_validate_json(model.model_dump_json()) == model
    with pytest.raises(ValidationError):
        model.protocol_id = "other"
    with pytest.raises(ValidationError):
        model.targets[0].path = "other.csv"
    names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
    schemas = Path(__file__).resolve().parents[1] / "schemas/v1"
    for helper in ("BenchmarkTarget", "BenchmarkComparison"):
        assert helper not in names
        assert not (schemas / f"{helper}.schema.json").exists()
