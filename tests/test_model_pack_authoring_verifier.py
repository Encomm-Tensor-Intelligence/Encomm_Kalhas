"""Verification of authoring bindings against a synthetic locked chain."""

from __future__ import annotations

from typing import Any, cast

import pytest
from kalhas.application import model_pack_authoring_verifier as authoring_verifier
from kalhas.application.benchmark_task_engine import BenchmarkTask, derive_benchmark_tasks
from kalhas.application.model_pack_authoring_errors import ModelPackAuthoringVerificationError
from kalhas.application.model_pack_authoring_verifier import (
    compute_model_pack_authoring_binding_content_hash,
    verify_model_pack_authoring_binding,
)
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding

from tests.test_benchmark_task_engine import chain
from tests.test_model_pack_authoring_contracts import binding_payload


def seal(data: dict[str, Any]) -> ModelPackAuthoringBinding:
    provisional = ModelPackAuthoringBinding.model_validate(data)
    data["content_hash"] = compute_model_pack_authoring_binding_content_hash(provisional)
    return ModelPackAuthoringBinding.model_validate(data)


@pytest.fixture
def prepared() -> tuple[Any, ...]:
    raw, raw_files, curated, files, split, protocol = chain()
    data = binding_payload()
    data["protocol_manifest_id"] = protocol.identifier
    data["protocol_content_hash"] = protocol.content_hash
    binding = seal(data)
    return binding, protocol, split, curated, files, {raw.identifier: (raw, raw_files)}


def test_valid_binding_is_deterministic(prepared: tuple[Any, ...]) -> None:
    binding, protocol, split, curated, files, raw = prepared
    assert {item.target_path for item in binding.observations} == {"daily.csv", "weekly.csv"}
    assert any(
        task.status == "evaluable" and task.path == "weekly.csv"
        for task in derive_benchmark_tasks(protocol, split, curated, files, "development")
    )
    verify_model_pack_authoring_binding(binding, protocol, split, curated, files, raw)
    verify_model_pack_authoring_binding(binding, protocol, split, curated, files, raw)


@pytest.mark.parametrize(
    "reason",
    [
        "invalid_manifest",
        "protocol_input_invalid",
        "protocol_reference_mismatch",
        "tenant_mismatch",
        "lock_order_invalid",
        "content_hash_mismatch",
        "unknown_target",
        "target_not_covered",
        "operator_time_mismatch",
        "denominator_missing",
    ],
)
def test_verification_reasons(prepared: tuple[Any, ...], reason: str) -> None:
    binding, protocol, split, curated, files, raw = prepared
    data = binding.model_dump(mode="json")
    if reason == "invalid_manifest":
        binding = cast(ModelPackAuthoringBinding, object())
    elif reason == "protocol_input_invalid":
        protocol = None
    elif reason == "protocol_reference_mismatch":
        data["protocol_content_hash"] = "1" * 64
        binding = seal(data)
    elif reason == "tenant_mismatch":
        data["tenant_id"] = "another-tenant"
        binding = seal(data)
    elif reason == "lock_order_invalid":
        data["declared_at"] = "2026-11-02T23:59:59Z"
        binding = seal(data)
    elif reason == "content_hash_mismatch":
        data["content_hash"] = "1" * 64
        binding = ModelPackAuthoringBinding.model_validate(data)
    elif reason == "unknown_target":
        data["observations"][1]["target_path"] = "zzz.csv"
        binding = seal(data)
    elif reason == "target_not_covered":
        data["observations"].pop()
        binding = seal(data)
    elif reason == "operator_time_mismatch":
        data["observations"][1]["operator"] = {
            "op": "per_100k",
            "inner": {"op": "stock_sum", "stocks": ["stock_a"]},
        }
        binding = seal(data)
    else:
        data["denominators"] = []
        binding = seal(data)
    with pytest.raises(ModelPackAuthoringVerificationError) as caught:
        verify_model_pack_authoring_binding(binding, protocol, split, curated, files, raw)
    assert caught.value.reason == reason


@pytest.mark.parametrize("field", ["payload", "operator", "denominator"])
def test_each_authoring_change_changes_hash(prepared: tuple[Any, ...], field: str) -> None:
    binding = prepared[0]
    data = binding.model_dump(mode="json")
    if field == "payload":
        data["payload"]["candidate_grid"]["x"] = 3
    elif field == "operator":
        data["observations"][0]["operator"]["stocks"] = ["stock_a"]
    else:
        data["denominators"][0]["value"] += 1
    changed = ModelPackAuthoringBinding.model_validate(data)
    assert compute_model_pack_authoring_binding_content_hash(changed) != binding.content_hash


def test_invalid_manifest_precedes_other_errors(prepared: tuple[Any, ...]) -> None:
    _, _, split, curated, files, raw = prepared
    with pytest.raises(ModelPackAuthoringVerificationError) as caught:
        verify_model_pack_authoring_binding(
            cast(ModelPackAuthoringBinding, object()),
            cast(BenchmarkProtocol, None),
            split,
            curated,
            files,
            raw,
        )
    assert caught.value.reason == "invalid_manifest"


def test_invalid_constructed_model_is_revalidated(prepared: tuple[Any, ...]) -> None:
    binding, protocol, split, curated, files, raw = prepared
    binding = binding.model_copy(update={"denominators": (object(),)})
    with pytest.raises(ModelPackAuthoringVerificationError) as caught:
        verify_model_pack_authoring_binding(binding, protocol, split, curated, files, raw)
    assert caught.value.reason == "invalid_manifest"


def test_validation_tasks_require_their_own_denominator(
    prepared: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, protocol, split, curated, files, raw = prepared
    calls: list[str] = []
    original = derive_benchmark_tasks

    def derive(*args: Any) -> tuple[BenchmarkTask, ...]:
        partition = args[-1]
        calls.append(partition)
        tasks = original(*args)
        if partition == "validation":
            return (
                *tasks,
                BenchmarkTask(
                    "weekly.csv", "alpha", "2020-W53", 1, "2021-W01", "validation", "evaluable"
                ),
            )
        return tasks

    monkeypatch.setattr(authoring_verifier, "derive_benchmark_tasks", derive)
    with pytest.raises(ModelPackAuthoringVerificationError) as caught:
        verify_model_pack_authoring_binding(binding, protocol, split, curated, files, raw)
    assert caught.value.reason == "denominator_missing"
    assert calls == ["development", "validation"]
    data = binding.model_dump(mode="json")
    data["denominators"].append({"series": "alpha", "year": 2021, "value": 17})
    calls.clear()
    verify_model_pack_authoring_binding(seal(data), protocol, split, curated, files, raw)
    assert calls == ["development", "validation"]
