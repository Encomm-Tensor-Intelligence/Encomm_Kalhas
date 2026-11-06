"""PAN authoring plan validation and synthetic integration."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.mechanism_forecasts import (
    mechanism_configuration,
    produce_mechanism_forecasts,
    verify_mechanism_forecast_set,
)
from kalhas.application.model_pack_authoring_verifier import (
    compute_model_pack_authoring_binding_content_hash,
)
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.domain_packs.pan.binding_plan import (
    pan_plan_members,
    pan_plan_variant_selection,
    parse_pan_binding_plan,
)
from kalhas.domain_packs.pan.initial_state import build_pan_initial_state_rule
from kalhas.domain_packs.pan.mechanism import PanDomainPackError

from tests.test_benchmark_task_engine import chain
from tests.test_model_pack_authoring_verifier import seal

ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = ROOT / "benchmarks/v1/bindings/ecdc-covid19-pan-primary/1.0.0/manifest.json"


def binding_data() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(BINDING_PATH.read_bytes()))


def binding() -> ModelPackAuthoringBinding:
    return ModelPackAuthoringBinding.model_validate_json(BINDING_PATH.read_bytes())


def test_committed_binding_and_golden_grid() -> None:
    assert (
        hashlib.sha256(BINDING_PATH.read_bytes()).hexdigest()
        == "eda796041e67fbf8237c57d6eb943e49397ef7505942344d9314bbada2f28f9f"
    )
    item = binding()
    assert (
        item.content_hash
        == compute_model_pack_authoring_binding_content_hash(item)
        == "fa95fe5542bdf06547f9fa164de9675633dcc1c173506b9ecabe6433da784a32"
    )
    plan = parse_pan_binding_plan(item)
    assert len(plan.candidates) == 12
    assert [name for name, _ in plan.variants] == ["h-and-c", "h-only"]
    assert plan.candidates[0].configuration["transmission_bps"] == 1174
    assert plan.candidates[0].initial_state_parameters["infectious_per_hospitalized_bps"] == 182368
    assert plan.candidates[-1].configuration["transmission_bps"] == 2054
    assert plan.candidates[-1].initial_state_parameters["infectious_per_hospitalized_bps"] == 729474
    assert {item.configuration["transmission_bps"] for item in plan.candidates} == {
        1174,
        1467,
        1760,
        2054,
    }
    assert {
        item.initial_state_parameters["infectious_per_hospitalized_bps"] for item in plan.candidates
    } == {182368, 364737, 729474}
    fixed = {
        "exposed_progression_bps": 2500,
        "infectious_recovery_bps": 1429,
        "hospital_admission_bps": 38,
        "icu_admission_bps": 252,
        "hospital_recovery_bps": 1134,
        "icu_mortality_bps": 356,
        "icu_recovery_bps": 634,
        "hospital_capacity": 100000000,
        "icu_capacity": 100000000,
        "compliance_bps": 0,
    }
    for candidate in plan.candidates:
        assert {key: candidate.configuration[key] for key in fixed} == fixed
    assert dict(plan.variants) == {
        "h-and-c": {
            "icu_share_bps": 2029,
            "immune_share_bps": 0,
            "exposed_per_infectious_bps": 5868,
        },
        "h-only": {
            "icu_share_bps": 2545,
            "immune_share_bps": 0,
            "exposed_per_infectious_bps": 5868,
        },
    }
    assert plan.action == {"intervention_intensity_bps": 0}


@pytest.mark.parametrize("variant", ["h-only", "h-and-c"])
def test_members_and_variant_selection(variant: str) -> None:
    item = binding()
    plan = parse_pan_binding_plan(item)
    members = pan_plan_members(plan, item, variant)
    assert [member.member_id for member in members] == [
        f"candidate-{index:02d}" for index in range(1, 13)
    ]
    assert [member.pack.release_profile.pack_version for member in members] == [
        f"0.2.{index}" for index in range(1, 13)
    ]
    for member, candidate in zip(members, plan.candidates, strict=True):
        assert member.action == plan.action
        assert member.initial_state_parameters == {
            "hospital_path": plan.hospital_path,
            "icu_path": plan.icu_path,
            "variant": variant,
            **dict(plan.variants)[variant],
            **candidate.initial_state_parameters,
        }
    selected = pan_plan_variant_selection(plan, item, variant)
    assert selected[plan.hospital_path] == variant
    assert len(selected) == 4
    assert all(value == "default" for path, value in selected.items() if path != plan.hospital_path)
    assert mechanism_configuration(item, members, build_pan_initial_state_rule(item), selected)


@pytest.mark.parametrize(
    "case",
    [
        "pack",
        "initial_keys",
        "rule_id",
        "rule_version",
        "hospital_path",
        "icu_path",
        "schedule_keys",
        "schedule_kind",
        "action_keys",
        "action_invalid",
        "grid_keys",
        "fitter_keys",
        "fitter_value",
        "variants_type",
        "variants_ids",
        "variant_keys",
        "variant_bool",
        "variant_negative",
        "variant_bound",
        "candidates_type",
        "candidates_empty",
        "candidates_many",
        "candidate_keys",
        "candidate_order",
        "candidate_duplicate",
        "config_type",
        "config_keys",
        "config_invalid",
        "parameters_keys",
        "parameters_bool",
        "parameters_negative",
        "sources_type",
        "source_keys",
        "source_empty",
        "source_basis",
        "source_order",
        "source_duplicate",
        "source_missing",
    ],
)
def test_plan_rejects_invalid_payload(case: str) -> None:
    data = binding_data()
    payload = data["payload"]
    initial, schedule, grid = (
        payload["initial_state_rule"],
        payload["action_schedule"],
        payload["candidate_grid"],
    )
    variant = grid["variants"]["h-only"]
    candidates = grid["candidates"]
    sources = grid["sources"]
    if case == "pack":
        data["pack_id"] = "other"
    elif case == "initial_keys":
        initial["extra"] = 1
    elif case == "rule_id":
        initial["rule_id"] = "other"
    elif case == "rule_version":
        initial["rule_version"] = "2.0.0"
    elif case == "hospital_path":
        initial["hospital_path"] = "missing.csv"
    elif case == "icu_path":
        initial["icu_path"] = "missing.csv"
    elif case == "schedule_keys":
        schedule["extra"] = 1
    elif case == "schedule_kind":
        schedule["kind"] = "other"
    elif case == "action_keys":
        schedule["action"]["extra"] = 1
    elif case == "action_invalid":
        schedule["action"]["intervention_intensity_bps"] = True
    elif case == "grid_keys":
        grid["extra"] = 1
    elif case == "fitter_keys":
        grid["fitter"]["extra"] = 1
    elif case == "fitter_value":
        grid["fitter"]["partition"] = "validation"
    elif case == "variants_type":
        grid["variants"] = []
    elif case == "variants_ids":
        del grid["variants"]["h-only"]
    elif case == "variant_keys":
        variant["extra"] = 1
    elif case == "variant_bool":
        variant["icu_share_bps"] = True
    elif case == "variant_negative":
        variant["exposed_per_infectious_bps"] = -1
    elif case == "variant_bound":
        variant["immune_share_bps"] = 10001
    elif case == "candidates_type":
        grid["candidates"] = {}
    elif case == "candidates_empty":
        grid["candidates"] = []
    elif case == "candidates_many":
        candidates.append(copy.deepcopy(candidates[-1]))
    elif case == "candidate_keys":
        candidates[0]["extra"] = 1
    elif case == "candidate_order":
        candidates.reverse()
    elif case == "candidate_duplicate":
        candidates[1] = copy.deepcopy(candidates[0])
    elif case == "config_type":
        candidates[0]["configuration"] = []
    elif case == "config_keys":
        del candidates[0]["configuration"]["icu_capacity"]
    elif case == "config_invalid":
        candidates[0]["configuration"]["transmission_bps"] = True
    elif case == "parameters_keys":
        candidates[0]["initial_state_parameters"]["extra"] = 1
    elif case == "parameters_bool":
        candidates[0]["initial_state_parameters"]["infectious_per_hospitalized_bps"] = True
    elif case == "parameters_negative":
        candidates[0]["initial_state_parameters"]["infectious_per_hospitalized_bps"] = -1
    elif case == "sources_type":
        grid["sources"] = {}
    elif case == "source_keys":
        sources[0]["extra"] = "x"
    elif case == "source_empty":
        sources[0]["reference"] = " "
    elif case == "source_basis":
        sources[0]["basis"] = "other"
    elif case == "source_order":
        sources.reverse()
    elif case == "source_duplicate":
        sources[1] = copy.deepcopy(sources[0])
    elif case == "source_missing":
        sources.pop()
    with pytest.raises(PanDomainPackError):
        parse_pan_binding_plan(seal(data))


def test_unknown_variant_and_multiple_nonhospital_variants() -> None:
    item = binding()
    plan = parse_pan_binding_plan(item)
    with pytest.raises(PanDomainPackError):
        pan_plan_members(plan, item, "unknown")
    with pytest.raises(PanDomainPackError):
        pan_plan_variant_selection(plan, item, "unknown")
    data = binding_data()
    other = copy.deepcopy(data["observations"][2])
    other["variant_id"] = "other"
    data["observations"].append(other)
    data["observations"].sort(key=lambda o: (o["target_path"], o["variant_id"]))
    modified = seal(data)
    with pytest.raises(PanDomainPackError):
        pan_plan_variant_selection(parse_pan_binding_plan(modified), modified, "h-only")


def test_synthetic_forecast_integration() -> None:
    raw, source, curated, files, split, protocol = chain()
    data = binding_data()
    data.update(
        protocol_manifest_id=protocol.identifier,
        protocol_content_hash=protocol.content_hash,
        tenant_id=protocol.tenant_id,
    )
    data["denominators"] = [{"series": "alpha", "year": 2020, "value": 1000000}]
    data["observations"] = [
        {
            "target_path": "daily.csv",
            "variant_id": "h-and-c",
            "operator": {"op": "stock_sum", "stocks": ["hospitalized", "intensive_care"]},
        },
        {
            "target_path": "daily.csv",
            "variant_id": "h-only",
            "operator": {"op": "stock_sum", "stocks": ["hospitalized"]},
        },
        {
            "target_path": "weekly.csv",
            "variant_id": "default",
            "operator": {
                "op": "per_100k",
                "inner": {"op": "flow_sum", "flow": "hospital_admissions"},
            },
        },
    ]
    data["payload"]["initial_state_rule"].update(hospital_path="daily.csv", icu_path="daily.csv")
    item = seal(data)
    plan = parse_pan_binding_plan(item)
    args: dict[str, Any] = dict(
        binding=item,
        members=pan_plan_members(plan, item, "h-only"),
        rule=build_pan_initial_state_rule(item),
        variants=pan_plan_variant_selection(plan, item, "h-only"),
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        raw_bundles={raw.identifier: (raw, source)},
    )
    artifact, content = produce_mechanism_forecasts(
        forecast_set_id="synthetic",
        forecast_set_version="1.0.0",
        partition="validation",
        created_at=item.declared_at,
        **args,
    )
    assert artifact.metadata["dispatched_step_count"] == 36
    assert artifact.metadata["fallback_count"] == 0
    verify_mechanism_forecast_set(artifact, content, **args)


def test_plan_purity_boundary() -> None:
    tree = ast.parse((ROOT / "kalhas/domain_packs/pan/binding_plan.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
        if isinstance(node, ast.Name):
            assert node.id not in {"float", "decimal", "math"}
