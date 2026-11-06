"""Golden exact arithmetic and fail-closed observation behavior."""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction

import pytest
from kalhas.application.model_pack_authoring_errors import ObservationOperatorError
from kalhas.application.observation_operators import (
    TrajectoryStep,
    denominator_year,
    evaluate_observation_operator,
    target_period_days,
)
from kalhas.contracts.v1.model_pack_authoring import (
    DenominatorEntry,
    FlowSumOperator,
    PerHundredKOperator,
    StockSumOperator,
)

FLOW = FlowSumOperator(op="flow_sum", flow="flow_a")
STOCK = StockSumOperator(op="stock_sum", stocks=("stock_a", "stock_b"))
SCALED = PerHundredKOperator(op="per_100k", inner=FLOW)
MONDAY = date(2019, 12, 30)


def week(value: int = 10) -> tuple[TrajectoryStep, ...]:
    return tuple(
        TrajectoryStep(MONDAY + timedelta(days=i), {"stock_a": 3, "stock_b": 4}, {"flow_a": value})
        for i in range(7)
    )


def test_exact_golden_observations() -> None:
    steps = week()
    assert evaluate_observation_operator(STOCK, steps, "2020-01-01", "date", "a", ()) == Fraction(7)
    assert evaluate_observation_operator(FLOW, steps, "2020-01-01", "date", "a", ()) == Fraction(10)
    assert evaluate_observation_operator(FLOW, steps, "2020-W01", "iso_week", "a", ()) == Fraction(
        70
    )
    million = (DenominatorEntry(series="a", year=2020, value=1000000),)
    assert evaluate_observation_operator(
        SCALED, steps, "2020-W01", "iso_week", "a", million
    ) == Fraction(7)
    three = (DenominatorEntry(series="a", year=2020, value=3),)
    assert evaluate_observation_operator(
        SCALED, week(1), "2020-W01", "iso_week", "a", three
    ) == Fraction(700000, 3)


def test_period_boundaries_and_denominator_year() -> None:
    assert target_period_days("2020-W01", "iso_week") == tuple(
        MONDAY + timedelta(days=i) for i in range(7)
    )
    assert denominator_year("2020-W01", "iso_week") == 2020
    assert target_period_days("2020-W53", "iso_week")[-1] == date(2021, 1, 3)
    assert denominator_year("2020-W53", "iso_week") == 2020
    assert denominator_year("2020-12-31", "date") == 2020


def test_outside_days_do_not_change_result() -> None:
    extra = (
        TrajectoryStep(date(2019, 12, 29), {}, {"flow_a": 999}),
        *week(),
        TrajectoryStep(date(2020, 1, 6), {}, {"flow_a": 888}),
    )
    assert evaluate_observation_operator(FLOW, extra, "2020-W01", "iso_week", "a", ()) == Fraction(
        70
    )


@pytest.mark.parametrize("bad", ["2021-W53", "2020-W00", "bad", "2020-W1", "0000-W01"])
def test_invalid_target_time(bad: str) -> None:
    with pytest.raises(ObservationOperatorError, match="rejected") as caught:
        target_period_days(bad, "iso_week")
    assert caught.value.reason == "invalid_target_time"


@pytest.mark.parametrize(
    "steps",
    [
        (TrajectoryStep(date(2020, 1, 1), {}, {}), TrajectoryStep(date(2020, 1, 1), {}, {})),
        (TrajectoryStep(date(2020, 1, 2), {}, {}), TrajectoryStep(date(2020, 1, 1), {}, {})),
        (TrajectoryStep(date(2020, 1, 1), {"x": True}, {}),),
        (TrajectoryStep(date(2020, 1, 1), {}, {"x": -1}),),
    ],
)
def test_invalid_steps(steps: tuple[TrajectoryStep, ...]) -> None:
    with pytest.raises(ObservationOperatorError) as caught:
        evaluate_observation_operator(FLOW, steps, "2020-01-01", "date", "a", ())
    assert caught.value.reason == "invalid_steps"


@pytest.mark.parametrize("operator", [STOCK, PerHundredKOperator(op="per_100k", inner=STOCK)])
def test_operator_time_mismatch(operator: StockSumOperator | PerHundredKOperator) -> None:
    with pytest.raises(ObservationOperatorError) as caught:
        evaluate_observation_operator(operator, week(), "2020-W01", "iso_week", "a", ())
    assert caught.value.reason == "operator_time_mismatch"


def test_incomplete_period() -> None:
    with pytest.raises(ObservationOperatorError) as caught:
        evaluate_observation_operator(FLOW, week()[:-1], "2020-W01", "iso_week", "a", ())
    assert caught.value.reason == "incomplete_period"


def test_unknown_quantity() -> None:
    with pytest.raises(ObservationOperatorError) as caught:
        evaluate_observation_operator(
            STOCK, (TrajectoryStep(date(2020, 1, 1), {}, {}),), "2020-01-01", "date", "a", ()
        )
    assert caught.value.reason == "unknown_quantity"


def test_denominator_missing() -> None:
    with pytest.raises(ObservationOperatorError) as caught:
        evaluate_observation_operator(SCALED, week(), "2020-W01", "iso_week", "a", ())
    assert caught.value.reason == "denominator_missing"
