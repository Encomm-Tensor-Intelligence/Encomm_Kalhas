"""Evaluate observations from declared daily records using exact arithmetic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from kalhas.application.benchmark_task_engine import TimeType
from kalhas.application.model_pack_authoring_errors import ObservationOperatorError
from kalhas.contracts.v1.dataset_split import parse_split_time
from kalhas.contracts.v1.model_pack_authoring import (
    DenominatorEntry,
    FlowSumOperator,
    ObservationOperator,
    PerHundredKOperator,
    StockSumOperator,
)


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    day: date
    stocks: Mapping[str, int]
    flows: Mapping[str, int]


def target_period_days(target_time: str, time_type: TimeType) -> tuple[date, ...]:
    try:
        if time_type not in ("date", "iso_week"):
            raise ValueError("invalid time type")
        parts = parse_split_time(target_time, time_type)
        if time_type == "date":
            return (date(parts[0], parts[1], parts[2]),)
        monday = date.fromisocalendar(parts[0], parts[1], 1)
        return tuple(monday + timedelta(days=offset) for offset in range(7))
    except (TypeError, ValueError, OverflowError):
        raise ObservationOperatorError("invalid_target_time") from None


def denominator_year(target_time: str, time_type: TimeType) -> int:
    day = target_period_days(target_time, time_type)[0]
    return day.year if time_type == "date" else day.isocalendar().year


def evaluate_observation_operator(
    operator: ObservationOperator,
    steps: Sequence[TrajectoryStep],
    target_time: str,
    time_type: TimeType,
    series: str,
    denominators: Sequence[DenominatorEntry],
) -> Fraction:
    days = target_period_days(target_time, time_type)
    previous: date | None = None
    by_day: dict[date, TrajectoryStep] = {}
    for step in steps:
        if (
            type(step) is not TrajectoryStep
            or type(step.day) is not date
            or (previous is not None and step.day <= previous)
            or not isinstance(step.stocks, Mapping)
            or not isinstance(step.flows, Mapping)
            or any(type(value) is not int or value < 0 for value in step.stocks.values())
            or any(type(value) is not int or value < 0 for value in step.flows.values())
        ):
            raise ObservationOperatorError("invalid_steps")
        by_day[step.day] = step
        previous = step.day
    inner = operator.inner if isinstance(operator, PerHundredKOperator) else operator
    if isinstance(inner, StockSumOperator) and time_type != "date":
        raise ObservationOperatorError("operator_time_mismatch")
    if any(day not in by_day for day in days):
        raise ObservationOperatorError("incomplete_period")
    try:
        if isinstance(inner, StockSumOperator):
            value = sum(by_day[days[0]].stocks[name] for name in inner.stocks)
        elif isinstance(inner, FlowSumOperator):
            value = sum(by_day[day].flows[inner.flow] for day in days)
        else:
            raise ObservationOperatorError("unknown_quantity")
    except KeyError:
        raise ObservationOperatorError("unknown_quantity") from None
    if isinstance(operator, PerHundredKOperator):
        year = denominator_year(target_time, time_type)
        entry = next((d for d in denominators if (d.series, d.year) == (series, year)), None)
        if entry is None:
            raise ObservationOperatorError("denominator_missing")
        return Fraction(value * 100_000, entry.value)
    return Fraction(value)
