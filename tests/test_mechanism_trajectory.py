"""Daily trajectory goldens through the real dispatcher."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kalhas.application import mechanism_trajectory
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.mechanism_forecast_errors import MechanismForecastError
from kalhas.application.mechanism_trajectory import (
    run_mechanism_trajectory,
    trajectory_step_from_result,
)
from kalhas.contracts.v1.domain_mechanism import DomainMechanismStepResult
from kalhas.domain_packs.pan import PanV01DomainPack
from kalhas.domain_packs.pan.mechanism import compute_transition, validate_configuration_payload

from tests.test_benchmark_task_engine import chain
from tests.test_model_pack_authoring_contracts import binding_payload
from tests.test_model_pack_authoring_verifier import seal

STATE = {
    "population_total": 1000,
    "susceptible": 900,
    "exposed": 50,
    "infectious": 30,
    "hospitalized": 15,
    "intensive_care": 5,
    "recovered": 0,
    "deceased": 0,
}
ACTION = {"intervention_intensity_bps": 2500}


def make_binding() -> Any:
    data = binding_payload()
    data["pack_id"] = "kalhas-pan"
    data["pack_version"] = "0.1.0"
    return seal(data)


def test_trajectory_goldens_and_independent_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    pack = PanV01DomainPack()
    *_, protocol = chain()
    binding = make_binding()
    calls = []
    dispatch = dispatch_domain_mechanism_step

    def counting(*args: Any) -> Any:
        calls.append(args[1].step_index)
        return dispatch(*args)

    monkeypatch.setattr(mechanism_trajectory, "dispatch_domain_mechanism_step", counting)
    kwargs = dict(
        binding=binding,
        protocol=protocol,
        run_id="run-test",
        last_observed_day=date(2020, 1, 5),
        initial_state=STATE,
        action=ACTION,
        step_count=14,
    )
    steps = run_mechanism_trajectory(pack, **kwargs)
    assert calls == list(range(14))
    assert [step.day for step in steps] == [date(2020, 1, 6) + timedelta(days=i) for i in range(14)]
    config = validate_configuration_payload(
        pack.mechanism_spec.configuration, pack.mechanism_spec.configuration
    )
    state = dict(STATE)
    for step in steps:
        expected = compute_transition(state, 2500, config)
        assert step.stocks == expected.next_state
        assert step.flows["hospital_admissions"] == expected.counts[2]
        assert step.flows["icu_admissions"] == expected.counts[4]
        state = expected.next_state
    for start, end, hospitalized, intensive, hospital_flow, intensive_flow in (
        (0, 7, 13, 7, 44, 25),
        (7, 14, 3, 4, 18, 18),
    ):
        assert steps[end - 1].stocks["hospitalized"] == hospitalized
        assert steps[end - 1].stocks["intensive_care"] == intensive
        assert sum(step.flows["hospital_admissions"] for step in steps[start:end]) == hospital_flow
        assert sum(step.flows["icu_admissions"] for step in steps[start:end]) == intensive_flow
    assert run_mechanism_trajectory(pack, **kwargs) == steps
    assert calls == list(range(14)) * 2


def test_invalid_state_is_a_dispatch_failure() -> None:
    *_, protocol = chain()
    invalid = {**STATE, "susceptible": 899}
    with pytest.raises(MechanismForecastError) as caught:
        run_mechanism_trajectory(
            PanV01DomainPack(),
            binding=make_binding(),
            protocol=protocol,
            run_id="bad",
            last_observed_day=date(2020, 1, 1),
            initial_state=invalid,
            action=ACTION,
            step_count=1,
        )
    assert caught.value.reason == "mechanism_dispatch_failed"


def test_unsupported_timestep_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    *_, protocol = chain()
    pack = PanV01DomainPack()
    spec = pack.release_profile.mechanism_spec.model_copy(update={"timestep_unit": "step"})
    pack.release_profile = pack.release_profile.model_copy(update={"mechanism_spec": spec})
    calls: list[object] = []
    monkeypatch.setattr(
        mechanism_trajectory, "dispatch_domain_mechanism_step", lambda *a: calls.append(a)
    )
    with pytest.raises(MechanismForecastError) as caught:
        run_mechanism_trajectory(
            pack,
            binding=make_binding(),
            protocol=protocol,
            run_id="bad",
            last_observed_day=date(2020, 1, 1),
            initial_state=STATE,
            action=ACTION,
            step_count=1,
        )
    assert caught.value.reason == "timestep_unsupported"
    assert calls == []


@pytest.mark.parametrize(
    "stock,emissions",
    [
        ({"a": 1}, [{"x": 1.5}]),
        ({"a": 1}, [{"x": True}]),
        ({"a": "1"}, [{"x": 1}]),
        ({"a": 1}, [{"x": 1}, {"x": 2}]),
        ({"a": 1}, [{"x": None}]),
    ],
)
def test_unsupported_result(stock: dict[str, Any], emissions: list[dict[str, Any]]) -> None:
    result = SimpleNamespace(
        next_state_payload=stock, emissions=[SimpleNamespace(payload=x) for x in emissions]
    )
    with pytest.raises(MechanismForecastError) as caught:
        trajectory_step_from_result(date(2020, 1, 1), cast(DomainMechanismStepResult, result))
    assert caught.value.reason == "mechanism_output_unsupported"


def test_string_labels_are_not_flows() -> None:
    result = SimpleNamespace(
        next_state_payload={"a": 1},
        emissions=[SimpleNamespace(payload={"label": "x", "flow_a": 2})],
    )
    step = trajectory_step_from_result(date(2020, 1, 1), cast(DomainMechanismStepResult, result))
    assert step.stocks == {"a": 1}
    assert step.flows == {"flow_a": 2}
