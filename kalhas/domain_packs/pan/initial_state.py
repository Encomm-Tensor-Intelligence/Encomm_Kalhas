"""PAN initial states derived from origin-available occupancy observations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from fractions import Fraction

from kalhas.application.benchmark_scoring import parse_observed_value
from kalhas.application.benchmark_task_engine import (
    BenchmarkInformationSet,
    BenchmarkTask,
    TimeType,
)
from kalhas.application.mechanism_forecasts import InitialStateRule
from kalhas.application.observation_operators import target_period_days
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs.pan.mechanism import PanDomainPackError

PAN_INITIAL_STATE_RULE_ID = "kalhas-pan-initial-state-v1"
PAN_INITIAL_STATE_RULE_VERSION = "1.0.0"
LOOKBACK_DAYS = 7
_KEYS = frozenset(
    {
        "hospital_path",
        "icu_path",
        "variant",
        "icu_share_bps",
        "immune_share_bps",
        "infectious_per_hospitalized_bps",
        "exposed_per_infectious_bps",
    }
)


def build_pan_initial_state_rule(binding: ModelPackAuthoringBinding) -> InitialStateRule:
    """Create the origin-only rule with the binding's declared denominators."""
    denominators = binding.denominators

    def build(
        task: BenchmarkTask, view: BenchmarkInformationSet, params: Mapping[str, JsonValue]
    ) -> Mapping[str, int] | None:
        if set(params) != _KEYS:
            raise PanDomainPackError("initial state parameter keys invalid")
        hospital_path, icu_path, variant = (
            params["hospital_path"],
            params["icu_path"],
            params["variant"],
        )
        if (
            type(hospital_path) is not str
            or type(icu_path) is not str
            or type(variant) is not str
            or variant not in ("h-only", "h-and-c")
        ):
            raise PanDomainPackError("initial state paths or variant invalid")
        kinds = dict(view._types)
        if hospital_path not in kinds or icu_path not in kinds:
            raise PanDomainPackError("initial state path is not a target")
        keys = (
            "icu_share_bps",
            "immune_share_bps",
            "infectious_per_hospitalized_bps",
            "exposed_per_infectious_bps",
        )
        values = [params[key] for key in keys]
        if any(type(value) is not int or value < 0 for value in values):
            raise PanDomainPackError("initial state ratio invalid")
        share, immune, infectious_ratio, exposed_ratio = values
        assert (
            isinstance(share, int)
            and isinstance(immune, int)
            and isinstance(infectious_ratio, int)
            and isinstance(exposed_ratio, int)
        )
        if share > 10000 or immune > 10000:
            raise PanDomainPackError("initial state share invalid")
        kind: TimeType = "iso_week" if "-W" in task.origin else "date"
        day = target_period_days(task.origin, kind)[-1]
        entry = next(
            (item for item in denominators if (item.series, item.year) == (task.series, day.year)),
            None,
        )
        if entry is None:
            return None

        def latest(path: str) -> Fraction | None:
            found = []
            for when, value in view.rows(task, path, task.series):
                observed_day = target_period_days(when, "date")[-1]
                if day - timedelta(days=LOOKBACK_DAYS) <= observed_day <= day:
                    found.append((observed_day, parse_observed_value(value)))
            return max(found, key=lambda item: item[0])[1] if found else None

        oh, oc = latest(hospital_path), latest(icu_path)
        if oh is None and oc is None:
            return None
        if oc is None:
            assert oh is not None
            c = round(oh * share / 10000)
        else:
            c = round(oc)
        if oh is None:
            if share == 0:
                return None
            assert oc is not None
            h = round(oc * 10000 / share)
        else:
            h = round(oh)
        if variant == "h-and-c":
            h -= c
        i = round(Fraction(h * infectious_ratio, 10000))
        e = round(Fraction(i * exposed_ratio, 10000))
        recovered = round(Fraction(entry.value * immune, 10000))
        susceptible = entry.value - e - i - h - c - recovered
        state = {
            "population_total": entry.value,
            "susceptible": susceptible,
            "exposed": e,
            "infectious": i,
            "hospitalized": h,
            "intensive_care": c,
            "recovered": recovered,
            "deceased": 0,
        }
        return None if any(value < 0 for value in state.values()) else state

    return InitialStateRule(PAN_INITIAL_STATE_RULE_ID, PAN_INITIAL_STATE_RULE_VERSION, build)
