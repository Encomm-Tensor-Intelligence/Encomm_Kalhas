"""Phase 19 contract tests: DomainMetricObservationBinding.

The binding is an immutable, frozen, strict VersionedContract that
connects exactly one scenario metric to exactly one numeric state field
of an existing scenario-bound DomainStateModel. These tests prove the
contract surface: frozen and extra-forbid behavior, the numeric
value-kind literal only, the ``final_state`` observation-point literal
only, SHA-256 and semantic-version validation, timezone-aware
``declared_at``, JSON safety (no executable-like fields), non-finite
metadata rejection, PUBLIC_CONTRACTS exactly 32, and schema export
round-trip coverage.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.shared import VersionedContract
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

_CONTRACT_SOURCE = (
    Path(__file__).resolve().parents[1] / "kalhas" / "contracts" / "v1" / ("metric_observation.py")
)


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "observation-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "metric_id": "m-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "content_hash": HASH_64,
        "declared_at": NOW,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def make_binding(**overrides: object) -> DomainMetricObservationBinding:
    return DomainMetricObservationBinding.model_validate(valid_payload(**overrides))


class TestBindingContractShape:
    def test_accepts_valid_payload(self) -> None:
        binding = make_binding()
        assert binding.identifier == "observation-1"
        assert binding.tenant_id == "tenant-1"
        assert binding.schema_version == "1.0.0"
        assert binding.observation_point == "final_state"
        assert binding.state_field_value_kind == "integer"

    def test_is_versioned_contract_and_frozen(self) -> None:
        assert isinstance(make_binding(), VersionedContract)
        binding = make_binding()
        # Runtime frozen behavior: attribute assignment raises even when
        # the assigned value is type-compatible (mypy-clean assignment).
        with pytest.raises(ValidationError):
            binding.metric_id = "m-2"
        with pytest.raises(ValidationError):
            binding.observation_point = "initial_state"  # type: ignore[assignment]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(unexpected_field=1)

    def test_scenario_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(scenario_id="")

    def test_metric_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(metric_id="")

    def test_state_model_identifier_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(state_model_identifier="")

    def test_state_model_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(state_model_id="")

    def test_state_field_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(state_field_id="")

    def test_schema_version_must_be_semantic(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(schema_version="1.0")

    def test_pack_version_must_be_semantic(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(pack_version="1.2")
        with pytest.raises(ValidationError):
            make_binding(pack_version="one.two.three")

    def test_hashes_must_be_lowercase_sha256(self) -> None:
        for field in ("manifest_content_hash", "state_model_content_hash", "content_hash"):
            with pytest.raises(ValidationError):
                make_binding(**{field: "not-a-hash"})
            with pytest.raises(ValidationError):
                make_binding(**{field: "A" * 64})  # uppercase rejected
            with pytest.raises(ValidationError):
                make_binding(**{field: "a" * 63})  # wrong length

    def test_declared_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            make_binding(declared_at=datetime(2026, 1, 1, 12, 0, 0))  # naive


class TestBindingLiterals:
    def test_numeric_value_kind_literal_only(self) -> None:
        assert make_binding(state_field_value_kind="integer").state_field_value_kind == "integer"
        assert make_binding(state_field_value_kind="number").state_field_value_kind == "number"
        for rejected in ("string", "boolean", "json", "INTEGER", "float", ""):
            with pytest.raises(ValidationError):
                make_binding(state_field_value_kind=rejected)

    def test_final_state_observation_point_literal_only(self) -> None:
        assert make_binding().observation_point == "final_state"
        # The field defaults to "final_state" when omitted.
        payload = valid_payload()
        del payload["observation_point"]
        assert DomainMetricObservationBinding.model_validate(payload).observation_point == (
            "final_state"
        )
        for rejected in ("initial_state", "every_state", "FINAL_STATE", ""):
            with pytest.raises(ValidationError):
                make_binding(observation_point=rejected)


class TestBindingJsonSafety:
    def test_metadata_rejects_non_finite_floats(self) -> None:
        for bad in ({"x": float("nan")}, {"x": float("inf")}, {"x": [1, float("nan")]}):
            with pytest.raises(ValidationError):
                make_binding(metadata=bad)

    def test_metadata_accepts_finite_json(self) -> None:
        binding = make_binding(metadata={"x": 1, "y": [True, None, {"z": 1.5}]})
        assert binding.metadata["y"] == [True, None, {"z": 1.5}]

    def test_contract_carries_no_executable_like_fields(self) -> None:
        """No formulas, expressions, callbacks, or executable references."""
        forbidden = re.compile(
            r"\b(eval|exec|import_module|__import__|compile|lambda|callback|provider)\b"
        )
        source = "".join(_CONTRACT_SOURCE.read_text(encoding="utf-8").split('"""')[::2])
        assert not forbidden.search(source)
        # No field may be callable or carry an executable annotation.
        for field in DomainMetricObservationBinding.model_fields.values():
            assert "Callable" not in str(field.annotation)
            assert not re.search(r"\b(?:Callable|exec|lambda)\b", str(field.annotation))
        # The contract has no value-bearing fields at all: no observed
        # value, no state snapshot, no outcome, no score, no evidence.
        json_schema = DomainMetricObservationBinding.model_json_schema()
        properties = set(json_schema["properties"])
        for forbidden_key in ("value", "observed_value", "raw_value", "final_state_value"):
            assert forbidden_key not in properties

    def test_json_round_trip(self) -> None:
        binding = make_binding(metadata={"nested": {"k": [1, 2]}})
        dumped = binding.model_dump_json()
        reloaded = DomainMetricObservationBinding.model_validate_json(dumped)
        assert reloaded == binding
        assert binding.model_dump(mode="json") == json.loads(dumped)


class TestBindingRegistration:
    def test_public_contract_count_is_exactly_40(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 47

    def test_binding_is_registered(self) -> None:
        assert DomainMetricObservationBinding in PUBLIC_CONTRACTS

    def test_schema_export_round_trip(self) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        schemas = generate_schemas()
        assert "DomainMetricObservationBinding.schema.json" in schemas
        rendered = json.loads(schemas["DomainMetricObservationBinding.schema.json"])
        properties = cast(dict[str, Any], rendered["properties"])
        assert properties["state_field_value_kind"]["enum"] == ["integer", "number"]
        assert properties["observation_point"]["const"] == "final_state"
        assert properties["observation_point"]["default"] == "final_state"
        assert properties["manifest_content_hash"]["pattern"] == "^[0-9a-f]{64}$"
        assert properties["pack_version"]["pattern"] == r"^\d+\.\d+\.\d+$"
        # No value/outcome/evidence fields may appear in the schema.
        schema_text = json.dumps(rendered)
        for forbidden_key in ("value", "observed_value", "raw_value", "outcome", "evidence"):
            assert re.search(rf'"{forbidden_key}":', schema_text) is None, forbidden_key
