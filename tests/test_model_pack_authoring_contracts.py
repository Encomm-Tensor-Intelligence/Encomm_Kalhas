"""Shape, exact-JSON and immutability checks for authoring bindings."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from pydantic import ValidationError


def binding_payload() -> dict[str, Any]:
    return {
        "identifier": "model-pack-authoring-binding-example-1.0.0",
        "tenant_id": "kalhas-synthetic",
        "schema_version": "1.0.0",
        "binding_id": "example",
        "binding_version": "1.0.0",
        "pack_id": "example-pack",
        "pack_version": "1.0.0",
        "protocol_manifest_id": "benchmark-protocol-synthetic-1.0.0",
        "protocol_content_hash": "0" * 64,
        "operator_vocabulary_version": "1.0.0",
        "observations": [
            {
                "target_path": "daily.csv",
                "variant_id": "default",
                "operator": {"op": "stock_sum", "stocks": ["stock_a", "stock_b"]},
            },
            {
                "target_path": "weekly.csv",
                "variant_id": "default",
                "operator": {"op": "per_100k", "inner": {"op": "flow_sum", "flow": "flow_a"}},
            },
        ],
        "denominators": [{"series": "alpha", "year": 2020, "value": 1000000}],
        "payload": {
            "initial_state_rule": {"nested": [1, "0.25", {"allowed": True}]},
            "action_schedule": {},
            "candidate_grid": {},
        },
        "assumptions": ["Synthetic assumption."],
        "declared_at": "2026-11-03T00:00:00Z",
        "content_hash": "0" * 64,
        "metadata": {},
    }


def test_binding_roundtrip_and_frozen_models() -> None:
    binding = ModelPackAuthoringBinding.model_validate(binding_payload())
    assert ModelPackAuthoringBinding.model_validate_json(binding.model_dump_json()) == binding
    with pytest.raises(ValidationError):
        binding.binding_id = "other"
    with pytest.raises(ValidationError):
        binding.observations[0].variant_id = "other"
    with pytest.raises(ValidationError):
        binding.denominators[0].value = 2


@pytest.mark.parametrize(
    "case",
    [
        "identity",
        "observations_unsorted",
        "observations_duplicate",
        "denominators_unsorted",
        "denominators_duplicate",
        "stocks_unsorted",
        "stocks_duplicate",
        "stocks_empty",
        "invalid_quantity",
        "nested_scale",
        "year_zero",
        "year_large",
        "value_zero",
        "value_bool",
        "empty_assumptions",
        "payload_missing",
        "payload_extra",
        "payload_value",
        "payload_float",
        "payload_tuple",
        "metadata_nonfinite",
        "metadata_tuple",
    ],
)
def test_invalid_binding_cases(case: str) -> None:
    data = binding_payload()
    if case == "identity":
        data["identifier"] = "wrong"
    elif case == "observations_unsorted":
        data["observations"].reverse()
    elif case == "observations_duplicate":
        data["observations"].append(copy.deepcopy(data["observations"][-1]))
    elif case == "denominators_unsorted":
        data["denominators"].insert(0, {"series": "z", "year": 2020, "value": 1})
    elif case == "denominators_duplicate":
        data["denominators"].append(copy.deepcopy(data["denominators"][0]))
    elif case == "stocks_unsorted":
        data["observations"][0]["operator"]["stocks"].reverse()
    elif case == "stocks_duplicate":
        data["observations"][0]["operator"]["stocks"] = ["stock_a", "stock_a"]
    elif case == "stocks_empty":
        data["observations"][0]["operator"]["stocks"] = []
    elif case == "invalid_quantity":
        data["observations"][0]["operator"]["stocks"] = ["Stock-A"]
    elif case == "nested_scale":
        data["observations"][1]["operator"]["inner"] = copy.deepcopy(
            data["observations"][1]["operator"]
        )
    elif case == "year_zero":
        data["denominators"][0]["year"] = 0
    elif case == "year_large":
        data["denominators"][0]["year"] = 10000
    elif case == "value_zero":
        data["denominators"][0]["value"] = 0
    elif case == "value_bool":
        data["denominators"][0]["value"] = True
    elif case == "empty_assumptions":
        data["assumptions"] = []
    elif case == "payload_missing":
        del data["payload"]["action_schedule"]
    elif case == "payload_extra":
        data["payload"]["extra"] = {}
    elif case == "payload_value":
        data["payload"]["candidate_grid"] = []
    elif case == "payload_float":
        data["payload"]["initial_state_rule"]["nested"] = [{"x": [0.5]}]
    elif case == "payload_tuple":
        data["payload"]["initial_state_rule"]["nested"] = (1,)
    elif case == "metadata_nonfinite":
        data["metadata"] = {"x": float("inf")}
    else:
        data["metadata"] = {"x": (1,)}
    with pytest.raises(ValidationError):
        ModelPackAuthoringBinding.model_validate(data)


def test_helper_models_are_not_registered() -> None:
    names = {item.__name__ for item in PUBLIC_CONTRACTS}
    assert not names.intersection(
        {
            "StockSumOperator",
            "FlowSumOperator",
            "PerHundredKOperator",
            "TargetObservation",
            "DenominatorEntry",
        }
    )
