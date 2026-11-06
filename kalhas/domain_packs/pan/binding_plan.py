"""Validate and expand the declared PAN authoring plan without execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from kalhas.application.hashing import canonical_json
from kalhas.application.mechanism_forecasts import MechanismForecastMember
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs.pan.candidates import build_pan_candidate_pack
from kalhas.domain_packs.pan.initial_state import (
    PAN_INITIAL_STATE_RULE_ID,
    PAN_INITIAL_STATE_RULE_VERSION,
)
from kalhas.domain_packs.pan.mechanism import (
    PanDomainPackError,
    validate_action_payload,
    validate_configuration_payload,
)


@dataclass(frozen=True, slots=True)
class PanCandidate:
    index: int
    configuration: Mapping[str, int]
    initial_state_parameters: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class PanBindingPlan:
    hospital_path: str
    icu_path: str
    action: Mapping[str, int]
    fitter: Mapping[str, JsonValue]
    variants: tuple[tuple[str, Mapping[str, int]], ...]
    candidates: tuple[PanCandidate, ...]


def _object(value: object, keys: set[str]) -> dict[str, JsonValue]:
    if type(value) is not dict or set(value) != keys:
        raise PanDomainPackError("invalid plan object")
    return value


def _ratios(value: object, keys: set[str], bounded: set[str]) -> dict[str, int]:
    data = _object(value, keys)
    result = {}
    for key, item in data.items():
        if type(item) is not int or item < 0 or (key in bounded and item > 10000):
            raise PanDomainPackError("invalid plan ratio")
        result[key] = item
    return result


def parse_pan_binding_plan(binding: ModelPackAuthoringBinding) -> PanBindingPlan:
    """Check the closed payload and preserve its canonical candidate order."""
    if binding.pack_id != "kalhas-pan":
        raise PanDomainPackError("unknown pack")
    payload = binding.payload
    initial = _object(
        payload["initial_state_rule"], {"rule_id", "rule_version", "hospital_path", "icu_path"}
    )
    if (
        initial["rule_id"] != PAN_INITIAL_STATE_RULE_ID
        or initial["rule_version"] != PAN_INITIAL_STATE_RULE_VERSION
    ):
        raise PanDomainPackError("initial state rule invalid")
    hospital, icu = initial["hospital_path"], initial["icu_path"]
    targets = {observation.target_path for observation in binding.observations}
    if (
        type(hospital) is not str
        or type(icu) is not str
        or hospital not in targets
        or icu not in targets
    ):
        raise PanDomainPackError("initial state paths invalid")
    schedule = _object(payload["action_schedule"], {"kind", "action"})
    if schedule["kind"] != "constant":
        raise PanDomainPackError("action schedule invalid")
    action_data = _object(schedule["action"], {"intervention_intensity_bps"})
    intensity = validate_action_payload(action_data)
    action = {"intervention_intensity_bps": intensity}
    grid = _object(payload["candidate_grid"], {"fitter", "variants", "candidates", "sources"})
    expected_fitter: dict[str, JsonValue] = {
        "algorithm_id": "kalhas-grid-fitter-v1",
        "algorithm_version": "1.0.0",
        "objective": "mean_relative_wis_over_cells",
        "partition": "development",
        "retention_tolerance": "21/20",
        "max_ensemble_members": 8,
    }
    fitter = _object(grid["fitter"], set(expected_fitter))
    if fitter != expected_fitter or type(fitter["max_ensemble_members"]) is not int:
        raise PanDomainPackError("fitter invalid")
    variants_raw = grid["variants"]
    if type(variants_raw) is not dict:
        raise PanDomainPackError("variants invalid")
    variant_ids = {item.variant_id for item in binding.observations if item.target_path == hospital}
    if set(variants_raw) != variant_ids:
        raise PanDomainPackError("variant identities invalid")
    ratio_keys = {"icu_share_bps", "immune_share_bps", "exposed_per_infectious_bps"}
    variants = tuple(
        (name, _ratios(value, ratio_keys, {"icu_share_bps", "immune_share_bps"}))
        for name, value in sorted(variants_raw.items())
    )
    candidates_raw = grid["candidates"]
    if type(candidates_raw) is not list or not 1 <= len(candidates_raw) <= 12:
        raise PanDomainPackError("candidate count invalid")
    candidates = []
    previous = ""
    for index, raw in enumerate(candidates_raw, 1):
        item = _object(raw, {"configuration", "initial_state_parameters"})
        serialized = canonical_json(item)
        if serialized <= previous:
            raise PanDomainPackError("candidate order invalid")
        previous = serialized
        config = item["configuration"]
        if type(config) is not dict:
            raise PanDomainPackError("configuration invalid")
        validated = validate_configuration_payload(config, config)
        parameters = _ratios(
            item["initial_state_parameters"], {"infectious_per_hospitalized_bps"}, set()
        )
        candidates.append(PanCandidate(index, validated, parameters))
    sources = grid["sources"]
    if type(sources) is not list:
        raise PanDomainPackError("sources invalid")
    source_names = []
    for raw in sources:
        source = _object(raw, {"parameter", "basis", "statement", "reference"})
        if any(type(value) is not str or not value.strip() for value in source.values()):
            raise PanDomainPackError("source fields invalid")
        if source["basis"] not in ("source", "assumption", "derived"):
            raise PanDomainPackError("source basis invalid")
        name = source["parameter"]
        assert isinstance(name, str)
        source_names.append(name)
    expected_sources = set(candidates[0].configuration) | {
        "infectious_per_hospitalized_bps",
        "exposed_per_infectious_bps",
        "icu_share_bps",
        "immune_share_bps",
    }
    if source_names != sorted(set(source_names)) or set(source_names) != expected_sources:
        raise PanDomainPackError("source parameters invalid")
    return PanBindingPlan(hospital, icu, action, dict(fitter), variants, tuple(candidates))


def pan_plan_members(
    plan: PanBindingPlan, binding: ModelPackAuthoringBinding, variant: str
) -> tuple[MechanismForecastMember, ...]:
    choices = dict(plan.variants)
    if variant not in choices:
        raise PanDomainPackError("unknown variant")
    return tuple(
        MechanismForecastMember(
            member_id=f"candidate-{candidate.index:02d}",
            pack=build_pan_candidate_pack(
                tenant_id=binding.tenant_id,
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                candidate_index=candidate.index,
                configuration=candidate.configuration,
                declared_at=binding.declared_at,
            ),
            action=plan.action,
            initial_state_parameters={
                "hospital_path": plan.hospital_path,
                "icu_path": plan.icu_path,
                "variant": variant,
                **choices[variant],
                **candidate.initial_state_parameters,
            },
        )
        for candidate in plan.candidates
    )


def pan_plan_variant_selection(
    plan: PanBindingPlan, binding: ModelPackAuthoringBinding, variant: str
) -> dict[str, str]:
    if variant not in dict(plan.variants):
        raise PanDomainPackError("unknown variant")
    selected = {plan.hospital_path: variant}
    for observation in binding.observations:
        if observation.target_path == plan.hospital_path:
            continue
        if observation.target_path in selected:
            raise PanDomainPackError("target has multiple variants")
        selected[observation.target_path] = observation.variant_id
    return selected
