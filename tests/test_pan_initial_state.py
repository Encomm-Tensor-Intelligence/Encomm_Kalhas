"""Exact PAN initialization and forecast integration on synthetic observations."""

from __future__ import annotations

import ast
import csv
import io
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.benchmark_task_engine import BenchmarkInformationSet, BenchmarkTask
from kalhas.application.mechanism_forecasts import (
    MechanismForecastMember,
    produce_mechanism_forecasts,
    verify_mechanism_forecast_set,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs.pan.initial_state import (
    LOOKBACK_DAYS,
    PAN_INITIAL_STATE_RULE_ID,
    PAN_INITIAL_STATE_RULE_VERSION,
    build_pan_initial_state_rule,
)
from kalhas.domain_packs.pan.mechanism import (
    STATE_KEYS,
    PanDomainPackError,
    compute_transition,
    validate_configuration_payload,
)

from tests.test_benchmark_task_engine import chain
from tests.test_model_pack_authoring_contracts import binding_payload
from tests.test_model_pack_authoring_verifier import seal
from tests.test_pan_candidates import ACTION, CONFIG, DECLARED, candidate

PARAMS: dict[str, JsonValue] = {
    "hospital_path": "hospital.csv",
    "icu_path": "icu.csv",
    "variant": "h-only",
    "icu_share_bps": 2000,
    "immune_share_bps": 1000,
    "infectious_per_hospitalized_bps": 30000,
    "exposed_per_infectious_bps": 5000,
}


class View:
    _types = (
        ("hospital.csv", "date"),
        ("icu.csv", "date"),
        ("daily.csv", "date"),
        ("weekly.csv", "iso_week"),
    )

    def __init__(
        self, hospital: tuple[tuple[str, str], ...] = (), icu: tuple[tuple[str, str], ...] = ()
    ) -> None:
        self.data = {"hospital.csv": hospital, "icu.csv": icu}

    def rows(self, task: BenchmarkTask, path: str, series: str) -> tuple[tuple[str, str], ...]:
        assert series == task.series
        return self.data[path]


def task(origin: str = "2020-01-05", path: str = "daily.csv", horizon: int = 1) -> BenchmarkTask:
    return BenchmarkTask(path, "alpha", origin, horizon, "unused", "validation", "evaluable")


def rule(years: tuple[int, ...] = (2020,)) -> Any:
    data = binding_payload()
    data["denominators"] = [{"series": "alpha", "year": year, "value": 1000000} for year in years]
    return build_pan_initial_state_rule(seal(data))


def build(
    view: View,
    *,
    params: dict[str, JsonValue] = PARAMS,
    origin: str = "2020-01-05",
    years: tuple[int, ...] = (2020,),
    path: str = "daily.csv",
    horizon: int = 1,
) -> Any:
    return rule(years).build(
        task(origin, path, horizon), cast(BenchmarkInformationSet, view), params
    )


@pytest.mark.parametrize(("hospital", "icu"), [("100", "20"), ("100", None), (None, "20")])
@pytest.mark.parametrize(
    ("variant", "h", "c", "i", "e", "s"),
    [("h-only", 100, 20, 300, 150, 899430), ("h-and-c", 80, 20, 240, 120, 899540)],
)
def test_initial_state_table(
    hospital: str | None, icu: str | None, variant: str, h: int, c: int, i: int, e: int, s: int
) -> None:
    view = View(
        (("2020-01-05", hospital),) if hospital is not None else (),
        (("2020-01-05", icu),) if icu is not None else (),
    )
    result = build(view, params={**PARAMS, "variant": variant})
    assert result == {
        "population_total": 1000000,
        "susceptible": s,
        "exposed": e,
        "infectious": i,
        "hospitalized": h,
        "intensive_care": c,
        "recovered": 100000,
        "deceased": 0,
    }
    assert set(result) == set(STATE_KEYS)


@pytest.mark.parametrize(
    ("observed", "h", "c"), [("5", 5, 0), ("15", 15, 2), ("12.5", 12, 1), ("13.5", 14, 1)]
)
def test_half_even(observed: str, h: int, c: int) -> None:
    result = build(View((("2020-01-05", observed),)), params={**PARAMS, "icu_share_bps": 1000})
    assert result["hospitalized"] == h
    assert result["intensive_care"] == c


def test_lookback_and_latest() -> None:
    assert LOOKBACK_DAYS == 7
    assert build(View((("2019-12-29", "7"),)))["hospitalized"] == 7
    assert build(View((("2019-12-28", "8"),))) is None
    assert (
        build(
            View(
                (
                    ("2020-01-04", "4"),
                    ("2020-01-01", "1"),
                    ("2020-01-03", "3"),
                    ("2020-01-06", "99"),
                )
            )
        )["hospitalized"]
        == 4
    )


def test_no_state_cases() -> None:
    assert build(View()) is None
    assert build(View((("2020-01-05", "100"),)), years=()) is None
    assert build(View(icu=(("2020-01-05", "20"),)), params={**PARAMS, "icu_share_bps": 0}) is None
    assert (
        build(
            View((("2020-01-05", "10"),), (("2020-01-05", "20"),)),
            params={**PARAMS, "variant": "h-and-c"},
        )
        is None
    )
    assert (
        build(View((("2020-01-05", "100"),)), params={**PARAMS, "immune_share_bps": 10000}) is None
    )


def test_origin_day_year_and_trajectory_sharing() -> None:
    view = View((("2020-01-05", "100"), ("2021-01-03", "120")))
    weekly = build(view, origin="2020-W01", path="weekly.csv", horizon=9)
    assert weekly == build(view, origin="2020-01-05", horizon=1)
    assert weekly["hospitalized"] == 100
    assert build(view, origin="2020-W53", path="weekly.csv") is None
    assert (
        build(view, origin="2020-W53", path="weekly.csv", years=(2020, 2021))["hospitalized"] == 120
    )
    assert rule().rule_id == PAN_INITIAL_STATE_RULE_ID
    assert rule().rule_version == PAN_INITIAL_STATE_RULE_VERSION


@pytest.mark.parametrize(
    "changes",
    [
        {"hospital_path": 1},
        {"hospital_path": "missing"},
        {"icu_path": None},
        {"icu_path": "missing"},
        {"variant": 1},
        {"variant": "other"},
        {"icu_share_bps": -1},
        {"icu_share_bps": 10001},
        {"icu_share_bps": True},
        {"immune_share_bps": 10001},
        {"immune_share_bps": -1},
        {"immune_share_bps": True},
        {"infectious_per_hospitalized_bps": -1},
        {"infectious_per_hospitalized_bps": "1"},
        {"exposed_per_infectious_bps": -1},
        {"exposed_per_infectious_bps": False},
        {"extra": 0},
    ],
)
def test_invalid_parameters(changes: dict[str, JsonValue]) -> None:
    with pytest.raises(PanDomainPackError):
        build(View(), params={**PARAMS, **changes})
    with pytest.raises(PanDomainPackError):
        build(View(), params={key: value for key, value in PARAMS.items() if key != "variant"})


def test_forecast_integration_and_no_lookahead(monkeypatch: pytest.MonkeyPatch) -> None:
    raw, source, curated, files, split, protocol = chain()
    data = binding_payload()
    data.update(
        pack_id="kalhas-pan",
        pack_version="0.1.0",
        protocol_manifest_id=protocol.identifier,
        protocol_content_hash=protocol.content_hash,
    )
    data["observations"][0]["operator"] = {"op": "stock_sum", "stocks": ["hospitalized"]}
    data["observations"][1]["operator"] = {
        "op": "per_100k",
        "inner": {"op": "flow_sum", "flow": "hospital_admissions"},
    }
    binding = seal(data)
    params = {**PARAMS, "hospital_path": "daily.csv", "icu_path": "daily.csv"}
    initial = build_pan_initial_state_rule(binding)
    seen: list[tuple[str, str]] = []
    original = BenchmarkInformationSet.rows

    def rows(
        view: BenchmarkInformationSet, task: BenchmarkTask, path: str, series: str
    ) -> tuple[tuple[str, str], ...]:
        result = original(view, task, path, series)
        origin = date.fromisoformat(task.origin)
        assert all(date.fromisoformat(when) <= origin for when, _ in result)
        seen.extend(result)
        return result

    monkeypatch.setattr(BenchmarkInformationSet, "rows", rows)
    args: dict[str, Any] = dict(
        binding=binding,
        members=(MechanismForecastMember("one", candidate(), ACTION, params),),
        rule=initial,
        variants={"daily.csv": "default", "weekly.csv": "default"},
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        raw_bundles={raw.identifier: (raw, source)},
    )
    artifact, content = produce_mechanism_forecasts(
        forecast_set_id="candidate",
        forecast_set_version="1.0.0",
        partition="validation",
        created_at=DECLARED,
        **args,
    )
    assert artifact.metadata["dispatched_step_count"] == 3
    assert artifact.metadata["fallback_count"] == 0
    verify_mechanism_forecast_set(artifact, content, **args)
    assert seen
    expected: dict[tuple[str, str], int] = {}
    config = validate_configuration_payload(CONFIG, CONFIG)
    for origin, value in (("2020-01-06", 6), ("2020-01-07", 7)):
        state = {
            "population_total": 1000000,
            "susceptible": 1000000 - 100000 - 5 * value - 3 * value - value - value,
            "exposed": round(3 * value / 2),
            "infectious": 3 * value,
            "hospitalized": value,
            "intensive_care": value,
            "recovered": 100000,
            "deceased": 0,
        }
        state["susceptible"] = 1000000 - sum(
            v for k, v in state.items() if k not in ("population_total", "susceptible")
        )
        for horizon in (1, 2):
            state = compute_transition(state, 0, config).next_state
            expected[(origin, str(horizon))] = state["hospitalized"]
    for row in list(csv.reader(io.StringIO(content.decode("utf-8"))))[1:]:
        assert row[4:] == [f"{expected[(row[2], row[3])]}.000000"] * 7


@pytest.mark.parametrize("name", ["candidates.py", "initial_state.py"])
def test_pure_module_boundary(name: str) -> None:
    path = Path(__file__).resolve().parents[1] / "kalhas" / "domain_packs" / "pan" / name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
        if isinstance(node, ast.Name):
            assert node.id not in {"float", "decimal", "math"}
