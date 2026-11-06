"""Offline daily trajectories through the verified mechanism dispatcher."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.mechanism_forecast_errors import MechanismForecastError
from kalhas.application.observation_operators import TrajectoryStep
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs import DomainPack


def trajectory_step_from_result(day: date, result: DomainMechanismStepResult) -> TrajectoryStep:
    stocks: dict[str, int] = {}
    for key, value in result.next_state_payload.items():
        if type(value) is not int:
            raise MechanismForecastError("mechanism_output_unsupported")
        stocks[key] = value
    flows: dict[str, int] = {}
    for emission in result.emissions:
        for key, value in emission.payload.items():
            if type(value) is str:
                continue
            if type(value) is not int or key in flows:
                raise MechanismForecastError("mechanism_output_unsupported")
            flows[key] = value
    return TrajectoryStep(day=day, stocks=stocks, flows=flows)


def run_mechanism_trajectory(
    pack: DomainPack,
    *,
    binding: ModelPackAuthoringBinding,
    protocol: BenchmarkProtocol,
    run_id: str,
    last_observed_day: date,
    initial_state: Mapping[str, int],
    action: Mapping[str, JsonValue],
    step_count: int,
) -> tuple[TrajectoryStep, ...]:
    profile = pack.release_profile
    spec = profile.mechanism_spec
    if spec.timestep != 1 or spec.timestep_unit != "day":
        raise MechanismForecastError("timestep_unsupported")
    state: Mapping[str, int] = dict(initial_state)
    action_payload = dict(action)
    output = []
    for index in range(step_count):
        state_payload: dict[str, JsonValue] = {key: value for key, value in state.items()}
        request = DomainMechanismStepRequest(
            identifier=f"{run_id}:step:{index}",
            tenant_id=profile.tenant_id,
            schema_version="1.0.0",
            mechanism_spec_id=spec.identifier,
            mechanism_spec_content_hash=spec.content_hash,
            release_profile_id=profile.identifier,
            release_profile_content_hash=profile.content_hash,
            realization_id=None,
            realization_content_hash=None,
            scenario_id=binding.identifier,
            scenario_content_hash=binding.content_hash,
            world_version_id=protocol.identifier,
            world_content_hash=protocol.content_hash,
            seed_id="no-stochastic-draw",
            seed_content_hash=sha256_hex(canonical_json({"seed": None})),
            run_id=run_id,
            step_index=index,
            state_schema_id=spec.state_schema_id,
            action_schema_id=spec.action_schema_id,
            configuration_schema_id=spec.configuration_schema_id,
            state_schema_hash=spec.state_schema_hash,
            action_schema_hash=spec.action_schema_hash,
            configuration_schema_hash=spec.configuration_schema_hash,
            state_payload=state_payload,
            action_payload=action_payload,
            configuration_payload=dict(spec.configuration),
            state_hash=sha256_hex(canonical_json(state_payload)),
            action_hash=sha256_hex(canonical_json(action_payload)),
            configuration_hash=spec.configuration_hash,
            exogenous_inputs=(),
            content_hash="0" * 64,
        )
        content = request.model_dump(mode="json")
        del content["content_hash"]
        request = request.model_copy(update={"content_hash": sha256_hex(canonical_json(content))})
        try:
            result = dispatch_domain_mechanism_step(pack, request)
        except DomainMechanismDispatchError:
            raise MechanismForecastError("mechanism_dispatch_failed") from None
        step = trajectory_step_from_result(last_observed_day + timedelta(days=index + 1), result)
        output.append(step)
        state = step.stocks
    return tuple(output)
