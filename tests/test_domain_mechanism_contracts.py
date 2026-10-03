"""H29-S02A adversarial contract tests for the domain-mechanism seam.

Covers the three public Phase 29 contracts (``DomainMechanismSpec``,
``DomainMechanismStepRequest``, ``DomainMechanismStepResult``) and their
nested helpers exactly as frozen for H29-S02A: registry order/count and
schema export, nested helpers never registered or schematized, exact
fail-closed raw-JSON validation (tuples, sets, ``Decimal``, arbitrary
objects, non-string keys, NaN/infinities are never coerced), required
release-profile identity references, mechanism-protocol/semantic-version
and hash literals, positive timestep/quantum numerics, exact
int/number preservation, realization both-or-neither and entry/request
agreement, canonical exogenous coordinate order with uniqueness,
contiguous unique emissions/evidence, strict JSON round trips, the
absence of any executable/provider/import/policy/persistence surface,
and the unchanged historical 55-contract schema prefix.

Only generic synthetic names and data are used. Nothing here loads,
executes, imports, or persists anything.
"""

from __future__ import annotations

import hashlib
import json
from collections import UserDict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
    MechanismExogenousInput,
    MechanismPlatformIdentity,
    MechanismQuantizationBoundary,
)
from pydantic import BaseModel, ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES, _HISTORICAL_SCHEMA_HASHES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
MODULE_PATH = REPO_ROOT / "kalhas" / "contracts" / "v1" / "domain_mechanism.py"

_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: Nested helper models that must never become public or schematized.
_NESTED_MECHANISM_MODELS = (
    MechanismPlatformIdentity,
    MechanismQuantizationBoundary,
    MechanismExogenousInput,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
)

#: Field names that must never exist on any mechanism contract: the seam
#: is declarative data only.
_FORBIDDEN_FIELDS = (
    "callback",
    "callable_ref",
    "code",
    "code_path",
    "expression",
    "import_path",
    "module_path",
    "entry_point",
    "provider",
    "provider_id",
    "network",
    "endpoint",
    "url",
    "clock",
    "timestamp",
    "wall_time",
    "environment",
    "env",
    "persistence",
    "persist",
    "receipt",
    "policy_id",
    "policy_choice",
    "scheduler",
    "schedule",
    "dispatch",
    "execute_fn",
    "fn",
    "func",
)


# ---------------------------------------------------------------------------
# Generic synthetic payload builders (plain dicts only, so every nested
# model is fully validated from raw input).
# ---------------------------------------------------------------------------


def _platform_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "os_name": "os-generic",
        "architecture": "arch-generic",
        "python_implementation": "cpython",
        "python_version": "3.12.0",
        "dependency_lock_hash": _HASH,
        "implementation_id": "implementation-1",
        "implementation_version": "2.0.0",
        "implementation_hash": _HASH,
        "solver_id": "solver-1",
        "solver_version": "3.0.0",
        "numeric_profile": "kalhas-platform-bound-binary64-v1",
    }
    payload.update(overrides)
    return payload


def _boundary_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "boundary_id": "boundary-1",
        "quantum": 0.25,
        "unit": "units",
    }
    payload.update(overrides)
    return payload


def _spec_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "mechanism-spec-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_id": "manifest-1",
        "manifest_content_hash": _HASH,
        "mechanism_id": "mechanism-1",
        "mechanism_version": "1.0.0",
        "mechanism_protocol_version": "1.0.0",
        "state_schema_id": "state-schema-1",
        "action_schema_id": "action-schema-1",
        "configuration_schema_id": "configuration-schema-1",
        "emission_schema_id": "emission-schema-1",
        "evidence_schema_id": "evidence-schema-1",
        "state_schema_hash": _HASH,
        "action_schema_hash": _HASH,
        "configuration_schema_hash": _HASH,
        "emission_schema_hash": _HASH,
        "evidence_schema_hash": _HASH,
        "configuration": {"alpha": 1, "beta": "on"},
        "configuration_hash": _HASH,
        "implementation_id": "implementation-1",
        "implementation_version": "2.0.0",
        "implementation_hash": _HASH,
        "dependency_lock_hash": _HASH,
        "solver_id": "solver-1",
        "solver_version": "3.0.0",
        "data_identities": [
            {"data_id": "data-1", "data_content_hash": _HASH},
        ],
        "parameter_bindings": [
            {
                "parameter_id": "parameter-1",
                "unit": "units",
                "data_id": "data-1",
                "data_content_hash": _HASH,
            },
        ],
        "timestep": 0.5,
        "timestep_unit": "hour",
        "event_order": ["event-a", "event-b"],
        "reduction_order": ["reduction-a"],
        "numeric_profile": "kalhas-platform-bound-binary64-v1",
        "precision": "ieee-754-binary64",
        "rounding_mode": "round-to-nearest-ties-to-even",
        "quantization_boundaries": [_boundary_payload()],
        "platform_identity": _platform_payload(),
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def _exogenous_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "exogenous-1",
        "stream": "stream-1",
        "variable": "variable-1",
        "entity_id": "entity-1",
        "draw_index": 0,
        "value_kind": "number",
        "value": 1.5,
        "unit": "units",
        "content_hash": _HASH,
        "world_version_id": "world-v1",
        "world_content_hash": _HASH,
        "seed_id": "seed-1",
        "seed_content_hash": _HASH,
        "run_id": "run-1",
        "step_index": 0,
    }
    payload.update(overrides)
    return payload


def _request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "mechanism-step-request-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "mechanism_spec_id": "mechanism-spec-1",
        "mechanism_spec_content_hash": _HASH,
        "release_profile_id": "release-profile-1",
        "release_profile_content_hash": _HASH,
        "realization_id": None,
        "realization_content_hash": None,
        "scenario_id": "scenario-1",
        "scenario_content_hash": _HASH,
        "world_version_id": "world-v1",
        "world_content_hash": _HASH,
        "seed_id": "seed-1",
        "seed_content_hash": _HASH,
        "run_id": "run-1",
        "step_index": 0,
        "state_schema_id": "state-schema-1",
        "action_schema_id": "action-schema-1",
        "configuration_schema_id": "configuration-schema-1",
        "state_schema_hash": _HASH,
        "action_schema_hash": _HASH,
        "configuration_schema_hash": _HASH,
        "state_payload": {"level": 0},
        "action_payload": {"kind": "advance"},
        "configuration_payload": {"alpha": 1},
        "state_hash": _HASH,
        "action_hash": _HASH,
        "configuration_hash": _HASH,
        "exogenous_inputs": [],
        "content_hash": _HASH,
    }
    payload.update(overrides)
    if "exogenous_inputs" not in overrides:
        payload["exogenous_inputs"] = [
            _exogenous_payload(
                world_version_id=payload["world_version_id"],
                world_content_hash=payload["world_content_hash"],
                seed_id=payload["seed_id"],
                seed_content_hash=payload["seed_content_hash"],
                run_id=payload["run_id"],
                step_index=payload["step_index"],
                realization_id=payload["realization_id"],
                realization_content_hash=payload["realization_content_hash"],
            )
        ]
    return payload


def _emission_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "emission-1",
        "sequence_position": 0,
        "emission_schema_id": "emission-schema-1",
        "emission_schema_hash": _HASH,
        "content_hash": _HASH,
        "payload": {"amount": 2.5},
        "unit": "units",
    }
    payload.update(overrides)
    return payload


def _evidence_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "evidence-1",
        "sequence_position": 0,
        "evidence_schema_id": "evidence-schema-1",
        "evidence_schema_hash": _HASH,
        "content_hash": _HASH,
        "payload": {"observed": True},
    }
    payload.update(overrides)
    return payload


def _result_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "mechanism-step-result-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "request_id": "mechanism-step-request-1",
        "request_content_hash": _HASH,
        "mechanism_spec_id": "mechanism-spec-1",
        "mechanism_spec_content_hash": _HASH,
        "release_profile_id": "release-profile-1",
        "release_profile_content_hash": _HASH,
        "world_version_id": "world-v1",
        "world_content_hash": _HASH,
        "seed_id": "seed-1",
        "seed_content_hash": _HASH,
        "realization_id": None,
        "realization_content_hash": None,
        "run_id": "run-1",
        "step_index": 0,
        "next_state_schema_id": "state-schema-1",
        "next_state_schema_hash": _HASH,
        "next_state_payload": {"level": 1},
        "next_state_hash": _HASH,
        "emissions": [_emission_payload()],
        "evidence": [_evidence_payload()],
        "content_hash": _HASH,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registry, schemas, and freeze surface
# ---------------------------------------------------------------------------


class TestRegistryAndSchemas:
    def test_mechanism_contracts_occupy_indexes_55_to_57_in_order(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        # Additive safety only: this historical suite is not the exact
        # current-count owner (tests/test_phase28_registry_compatibility.py
        # is). Later accepted appends keep this test green.
        assert len(names) >= 58
        assert names[55:58] == [
            "DomainMechanismSpec",
            "DomainMechanismStepRequest",
            "DomainMechanismStepResult",
        ]
        assert names[:55] == [
            *(name for name in _HISTORICAL_47_NAMES),
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
            "AdaptivePolicy",
            "AdaptiveRunTrajectoryExecution",
            "AdaptiveRunTrajectoryReplayManifest",
        ]

    def test_schema_export_covers_exactly_the_registry(self) -> None:
        generated = generate_schemas()
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert set(generated) == {f"{name}.schema.json" for name in names}
        assert {
            "DomainMechanismSpec.schema.json",
            "DomainMechanismStepRequest.schema.json",
            "DomainMechanismStepResult.schema.json",
        }.issubset(set(generated))

    def test_mechanism_schemas_equal_live_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            DomainMechanismSpec: "DomainMechanismSpec.schema.json",
            DomainMechanismStepRequest: "DomainMechanismStepRequest.schema.json",
            DomainMechanismStepResult: "DomainMechanismStepResult.schema.json",
        }
        for contract, filename in expected.items():
            rendered = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_nested_helpers_are_never_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for model in _NESTED_MECHANISM_MODELS:
            assert model.__name__ not in names

    def test_nested_helpers_have_no_standalone_schema(self) -> None:
        artifact_names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for model in _NESTED_MECHANISM_MODELS:
            assert f"{model.__name__}.schema.json" not in artifact_names

    def test_historical_schema_prefix_remains_unchanged(self) -> None:
        by_name = {path.name: path for path in SCHEMA_DIR.glob("*.schema.json")}
        assert len(_HISTORICAL_SCHEMA_HASHES) == 47
        for name, expected in _HISTORICAL_SCHEMA_HASHES.items():
            assert name in by_name, f"historical schema missing: {name}"
            assert hashlib.sha256(by_name[name].read_bytes()).hexdigest() == expected, (
                f"historical schema drifted: {name}"
            )
        for name in _HISTORICAL_47_NAMES:
            assert f"{name}.schema.json" in by_name

    def test_frozen_public_contracts_reject_mutation_and_unknown_fields(self) -> None:
        for contract, payload in (
            (DomainMechanismSpec, _spec_payload()),
            (DomainMechanismStepRequest, _request_payload()),
            (DomainMechanismStepResult, _result_payload()),
        ):
            instance = contract.model_validate(payload)
            with pytest.raises(ValidationError):
                instance.identifier = "tampered"
            tampered = dict(payload)
            tampered["unexpected_field"] = 1
            with pytest.raises(ValidationError):
                contract.model_validate(tampered)

    def test_frozen_nested_helpers_reject_mutation(self) -> None:
        boundary = MechanismQuantizationBoundary.model_validate(_boundary_payload())
        with pytest.raises(ValidationError):
            boundary.quantum = 1.0
        entry = MechanismExogenousInput.model_validate(_exogenous_payload())
        with pytest.raises(ValidationError):
            entry.draw_index = 5


# ---------------------------------------------------------------------------
# Correction A: exact fail-closed raw-JSON validation
# ---------------------------------------------------------------------------


class TestExactJsonFailClosed:
    @pytest.mark.parametrize(
        "offending_tree",
        [
            {"level": (1, 2)},
            {"level": {1, 2}},
            {"level": Decimal("1.5")},
            {"level": UserDict({"a": 1})},
            {"level": NOW},
            {"level": object()},
            {1: "non-string key"},
            {"level": [1, {"nested": (2,)}]},
            {"level": float("nan")},
            {"level": float("inf")},
            {"level": [1, float("-inf")]},
        ],
        ids=[
            "tuple",
            "set",
            "decimal",
            "foreign-mapping",
            "datetime",
            "arbitrary-object",
            "non-string-key",
            "nested-tuple",
            "nan",
            "inf",
            "nested-neg-inf",
        ],
    )
    def test_request_state_payload_rejects_non_exact_json(self, offending_tree: object) -> None:
        payload = _request_payload(state_payload=offending_tree)
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepRequest.model_validate(payload)

    def test_request_action_and_configuration_payloads_are_guarded(self) -> None:
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepRequest.model_validate(
                _request_payload(action_payload={"kind": ("advance",)})
            )
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepRequest.model_validate(
                _request_payload(configuration_payload={"alpha": Decimal("1")})
            )

    def test_spec_configuration_and_metadata_are_guarded(self) -> None:
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismSpec.model_validate(
                _spec_payload(configuration={"alpha": {"beta": object()}})
            )
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismSpec.model_validate(_spec_payload(metadata={"at": NOW}))

    def test_result_next_state_payload_is_guarded(self) -> None:
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepResult.model_validate(
                _result_payload(next_state_payload=Decimal("1.5"))
            )

    def test_emission_and_evidence_payloads_are_guarded(self) -> None:
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepResult.model_validate(
                _result_payload(emissions=[_emission_payload(payload={"amount": {1, 2}})])
            )
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepResult.model_validate(
                _result_payload(evidence=[_evidence_payload(payload=("observed",))])
            )

    def test_accepted_json_trees_preserve_exact_types(self) -> None:
        payload = _request_payload(
            state_payload={
                "level": 2,
                "ratio": 0.25,
                "flag": True,
                "label": "1",
                "nothing": None,
                "items": [1, 2.5, False, None, "x"],
                "nested": {"deep": [3]},
            }
        )
        request = DomainMechanismStepRequest.model_validate(payload)
        dumped = json.loads(request.model_dump_json())
        assert dumped["state_payload"] == {
            "level": 2,
            "ratio": 0.25,
            "flag": True,
            "label": "1",
            "nothing": None,
            "items": [1, 2.5, False, None, "x"],
            "nested": {"deep": [3]},
        }
        assert isinstance(dumped["state_payload"]["level"], int)
        assert isinstance(dumped["state_payload"]["ratio"], float)
        assert isinstance(dumped["state_payload"]["flag"], bool)
        assert isinstance(dumped["state_payload"]["label"], str)

    @staticmethod
    def _subclass_cases() -> list[object]:
        def _int_subclass() -> int:
            class MyInt(int):
                pass

            return MyInt(2)

        def _float_subclass() -> float:
            class MyFloat(float):
                pass

            return MyFloat(0.5)

        def _str_subclass() -> str:
            class MyStr(str):
                pass

            return MyStr("two")

        def _list_subclass() -> list[int]:
            class MyList(list[int]):
                pass

            return MyList([1, 2])

        def _dict_subclass() -> dict[str, int]:
            class MyDict(dict[str, int]):
                pass

            return MyDict({"a": 1})

        def _bool_subclass() -> object:
            class MyBool(int):
                def __bool__(self) -> bool:
                    return False

            return MyBool(1)

        def _dict_with_subclass_key() -> dict[object, int]:
            class MyStr(str):
                pass

            return {MyStr("k"): 1}

        return [
            _int_subclass(),
            _float_subclass(),
            _str_subclass(),
            _list_subclass(),
            _dict_subclass(),
            {"nested": [_bool_subclass()]},
            _dict_with_subclass_key(),
        ]

    @pytest.mark.parametrize(
        "subclass_value",
        _subclass_cases(),
        ids=[
            "int-subclass",
            "float-subclass",
            "str-subclass",
            "list-subclass",
            "dict-subclass",
            "nested-bool-subclass",
            "dict-with-subclass-key",
        ],
    )
    def test_json_tree_rejects_builtin_subclasses(self, subclass_value: object) -> None:
        payload = _request_payload(state_payload={"level": subclass_value})
        with pytest.raises(ValidationError, match="must contain only exact JSON values"):
            DomainMechanismStepRequest.model_validate(payload)

    def test_numeric_looking_strings_are_never_converted(self) -> None:
        payload = _request_payload(state_payload={"level": "2", "ratio": "0.25", "flag": "true"})
        request = DomainMechanismStepRequest.model_validate(payload)
        assert request.state_payload == {"level": "2", "ratio": "0.25", "flag": "true"}
        assert all(isinstance(value, str) for value in request.state_payload.values())


# ---------------------------------------------------------------------------
# Correction B: required release-profile identity
# ---------------------------------------------------------------------------


class TestReleaseProfileIdentity:
    def test_request_requires_release_profile_id_and_hash(self) -> None:
        missing_id = _request_payload()
        del missing_id["release_profile_id"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepRequest.model_validate(missing_id)
        missing_hash = _request_payload()
        del missing_hash["release_profile_content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepRequest.model_validate(missing_hash)

    def test_result_requires_release_profile_id_and_hash(self) -> None:
        missing_id = _result_payload()
        del missing_id["release_profile_id"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepResult.model_validate(missing_id)
        missing_hash = _result_payload()
        del missing_hash["release_profile_content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepResult.model_validate(missing_hash)

    def test_release_profile_references_are_opaque_identity_only(self) -> None:
        request = DomainMechanismStepRequest.model_validate(_request_payload())
        assert request.release_profile_id == "release-profile-1"
        assert request.release_profile_content_hash == _HASH
        assert not any(
            field.startswith("release_profile_implementation")
            for field in DomainMechanismStepRequest.model_fields
        )
        assert not any("model_pack" in field for field in DomainMechanismStepRequest.model_fields)


# ---------------------------------------------------------------------------
# Correction C: public field clarity before freeze
# ---------------------------------------------------------------------------


class TestPublicFieldClarity:
    def test_spec_uses_mechanism_protocol_version_literal(self) -> None:
        assert DomainMechanismSpec.model_fields["mechanism_protocol_version"].is_required()
        spec = DomainMechanismSpec.model_validate(_spec_payload())
        assert spec.mechanism_protocol_version == "1.0.0"
        assert "protocol_version" not in DomainMechanismSpec.model_fields
        bad = _spec_payload(mechanism_protocol_version="1.0.1")
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(bad)
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(_spec_payload(mechanism_protocol_version="2.0.0"))

    def test_exogenous_entries_use_content_hash(self) -> None:
        assert "content_hash" in MechanismExogenousInput.model_fields
        assert "value_hash" not in MechanismExogenousInput.model_fields
        missing = _exogenous_payload()
        del missing["content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            MechanismExogenousInput.model_validate(missing)

    def test_emission_and_evidence_records_require_content_hash(self) -> None:
        assert MechanismEmissionRecord.model_fields["content_hash"].is_required()
        assert MechanismEvidenceRecord.model_fields["content_hash"].is_required()
        emission = _emission_payload()
        del emission["content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            MechanismEmissionRecord.model_validate(emission)
        evidence = _evidence_payload()
        del evidence["content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            MechanismEvidenceRecord.model_validate(evidence)

    def test_emission_unit_is_optional(self) -> None:
        without_unit = _emission_payload()
        del without_unit["unit"]
        record = MechanismEmissionRecord.model_validate(without_unit)
        assert record.unit is None
        with_unit = MechanismEmissionRecord.model_validate(_emission_payload())
        assert with_unit.unit == "units"


# ---------------------------------------------------------------------------
# Correction D: quantization boundary with explicit positive quantum
# ---------------------------------------------------------------------------


class TestQuantizationBoundary:
    def test_boundary_carries_id_quantum_and_optional_unit(self) -> None:
        record = MechanismQuantizationBoundary.model_validate(_boundary_payload())
        assert record.boundary_id == "boundary-1"
        assert record.quantum == 0.25
        assert record.unit == "units"
        no_unit = _boundary_payload()
        del no_unit["unit"]
        record = MechanismQuantizationBoundary.model_validate(no_unit)
        assert record.unit is None

    @pytest.mark.parametrize(
        "bad_quantum",
        [0, 0.0, -1, -0.5, "0.25", True, False, Decimal("0.25"), float("nan"), float("inf")],
    )
    def test_quantum_rejects_zero_negative_bool_string_decimal_nonfinite(
        self, bad_quantum: object
    ) -> None:
        with pytest.raises(ValidationError):
            MechanismQuantizationBoundary.model_validate(_boundary_payload(quantum=bad_quantum))

    def test_quantum_is_preserved_exactly(self) -> None:
        int_quantum = MechanismQuantizationBoundary.model_validate(_boundary_payload(quantum=1))
        assert isinstance(int_quantum.quantum, int)
        float_quantum = MechanismQuantizationBoundary.model_validate(
            _boundary_payload(quantum=0.125)
        )
        assert isinstance(float_quantum.quantum, float)
        assert float_quantum.quantum == 0.125

    def test_no_legacy_ambiguous_value_field_exists(self) -> None:
        assert "value" not in MechanismQuantizationBoundary.model_fields
        legacy = _boundary_payload(value=0.5)
        with pytest.raises(ValidationError):
            MechanismQuantizationBoundary.model_validate(legacy)

    def test_empty_boundaries_mean_no_declared_quantization(self) -> None:
        spec = DomainMechanismSpec.model_validate(_spec_payload(quantization_boundaries=[]))
        assert spec.quantization_boundaries == ()

    def test_non_empty_boundaries_are_unique_and_ordered_by_identity(self) -> None:
        spec = DomainMechanismSpec.model_validate(
            _spec_payload(
                quantization_boundaries=[
                    _boundary_payload(boundary_id="boundary-a", quantum=0.5),
                    _boundary_payload(boundary_id="boundary-b", quantum=1),
                ]
            )
        )
        assert [boundary.boundary_id for boundary in spec.quantization_boundaries] == [
            "boundary-a",
            "boundary-b",
        ]
        with pytest.raises(ValidationError, match="quantization boundary ids must be unique"):
            DomainMechanismSpec.model_validate(
                _spec_payload(
                    quantization_boundaries=[
                        _boundary_payload(boundary_id="boundary-a"),
                        _boundary_payload(boundary_id="boundary-a", unit=None),
                    ]
                )
            )

    def test_spec_declares_ties_to_even_with_no_hidden_rounding_fields(self) -> None:
        spec = DomainMechanismSpec.model_validate(_spec_payload())
        assert spec.rounding_mode == "round-to-nearest-ties-to-even"
        assert not any("clip" in field for field in DomainMechanismSpec.model_fields)
        assert not any("tolerance" in field for field in DomainMechanismSpec.model_fields)
        assert not any("default_quant" in field for field in DomainMechanismSpec.model_fields)


# ---------------------------------------------------------------------------
# Spec validation: literals, hashes, timestep, orders, platform agreement
# ---------------------------------------------------------------------------


class TestSpecValidation:
    def test_semver_fields_reject_non_semver(self) -> None:
        for field in (
            "pack_version",
            "mechanism_version",
            "implementation_version",
            "solver_version",
        ):
            with pytest.raises(ValidationError):
                DomainMechanismSpec.model_validate(_spec_payload(**{field: "1.2"}))
            with pytest.raises(ValidationError):
                DomainMechanismSpec.model_validate(_spec_payload(**{field: "v1.2.3"}))

    def test_hash_fields_reject_malformed_hashes(self) -> None:
        for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64):
            with pytest.raises(ValidationError):
                DomainMechanismSpec.model_validate(
                    _spec_payload(manifest_content_hash=bad_hash[:64])
                )
            with pytest.raises(ValidationError):
                DomainMechanismSpec.model_validate(_spec_payload(configuration_hash=bad_hash[:64]))

    @pytest.mark.parametrize(
        "field",
        ["numeric_profile", "precision", "rounding_mode", "mechanism_protocol_version"],
    )
    def test_frozen_literals_reject_any_other_value(self, field: str) -> None:
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(_spec_payload(**{field: "not-a-declared-literal"}))

    @pytest.mark.parametrize("bad_timestep", [0, -1, "0.5", True, float("nan"), float("inf")])
    def test_timestep_must_be_positive_exact_numeric(self, bad_timestep: object) -> None:
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(_spec_payload(timestep=bad_timestep))

    def test_timestep_preserves_int_and_float_exactly(self) -> None:
        int_step = DomainMechanismSpec.model_validate(_spec_payload(timestep=1))
        assert isinstance(int_step.timestep, int) and int_step.timestep == 1
        float_step = DomainMechanismSpec.model_validate(_spec_payload(timestep=0.5))
        assert isinstance(float_step.timestep, float) and float_step.timestep == 0.5

    def test_orders_must_be_non_empty_and_unique(self) -> None:
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(_spec_payload(event_order=[]))
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(_spec_payload(reduction_order=[]))
        with pytest.raises(ValidationError, match="event_order entries must be unique"):
            DomainMechanismSpec.model_validate(_spec_payload(event_order=["a", "a"]))
        with pytest.raises(ValidationError, match="reduction_order entries must be unique"):
            DomainMechanismSpec.model_validate(_spec_payload(reduction_order=["a", "a"]))

    def test_platform_identity_must_agree_exactly(self) -> None:
        for field, other in (
            ("implementation_id", "implementation-other"),
            ("implementation_version", "9.9.9"),
            ("implementation_hash", _HASH[:-1] + ("0" if _HASH[-1] != "0" else "1")),
            ("dependency_lock_hash", _HASH[:-1] + ("0" if _HASH[-1] != "0" else "1")),
            ("solver_id", "solver-other"),
            ("solver_version", "9.9.9"),
        ):
            disagreeing = _platform_payload(**{field: other})
            with pytest.raises(ValidationError, match="platform_identity disagrees"):
                DomainMechanismSpec.model_validate(_spec_payload(platform_identity=disagreeing))

    def test_declared_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            DomainMechanismSpec.model_validate(
                _spec_payload(declared_at=datetime(2026, 1, 1, 12, 0, 0))
            )

    def test_data_and_parameter_identities_must_be_unique(self) -> None:
        duplicate_data = [
            {"data_id": "data-1", "data_content_hash": _HASH},
            {"data_id": "data-1", "data_content_hash": _HASH},
        ]
        with pytest.raises(ValidationError, match="data identity ids must be unique"):
            DomainMechanismSpec.model_validate(_spec_payload(data_identities=duplicate_data))
        duplicate_binding = [
            {"parameter_id": "parameter-1", "unit": None},
            {"parameter_id": "parameter-1", "unit": "units"},
        ]
        with pytest.raises(ValidationError, match="parameter binding ids must be unique"):
            DomainMechanismSpec.model_validate(_spec_payload(parameter_bindings=duplicate_binding))

    def test_parameter_binding_data_identity_is_both_or_neither(self) -> None:
        partial = [{"parameter_id": "parameter-1", "data_id": "data-1"}]
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            DomainMechanismSpec.model_validate(_spec_payload(parameter_bindings=partial))
        neutral = [{"parameter_id": "parameter-1", "unit": "units"}]
        spec = DomainMechanismSpec.model_validate(_spec_payload(parameter_bindings=neutral))
        assert spec.parameter_bindings[0].data_id is None
        assert spec.parameter_bindings[0].data_content_hash is None


# ---------------------------------------------------------------------------
# Exogenous inputs: kinds, coordinates, realization pairs
# ---------------------------------------------------------------------------


class TestExogenousInputs:
    def test_exactly_one_of_entity_or_slot(self) -> None:
        with pytest.raises(ValidationError, match="exactly one of entity_id or slot_id"):
            MechanismExogenousInput.model_validate(_exogenous_payload(slot_id="slot-1"))
        neither = _exogenous_payload()
        neither["entity_id"] = None
        with pytest.raises(ValidationError, match="exactly one of entity_id or slot_id"):
            MechanismExogenousInput.model_validate(neither)

    def test_integer_kind_requires_exact_int(self) -> None:
        entry = MechanismExogenousInput.model_validate(
            _exogenous_payload(value_kind="integer", value=3)
        )
        assert entry.value == 3 and isinstance(entry.value, int)
        for bad in (1.5, "3", True, float("nan")):
            with pytest.raises(ValidationError, match="integer entries require an exact int"):
                MechanismExogenousInput.model_validate(
                    _exogenous_payload(value_kind="integer", value=bad)
                )

    def test_number_kind_accepts_exact_finite_numeric_without_conversion(self) -> None:
        float_entry = MechanismExogenousInput.model_validate(_exogenous_payload(value=1.5))
        assert isinstance(float_entry.value, float)
        int_entry = MechanismExogenousInput.model_validate(_exogenous_payload(value=2))
        assert isinstance(int_entry.value, int) and int_entry.value == 2
        for bad in ("1.5", True, float("nan"), float("inf")):
            with pytest.raises(ValidationError, match="number entries require"):
                MechanismExogenousInput.model_validate(_exogenous_payload(value=bad))

    @pytest.mark.parametrize("bad_index", [-1, 0.5, "0", True, float("nan")])
    def test_draw_index_and_step_index_are_strict_non_negative(self, bad_index: object) -> None:
        with pytest.raises(ValidationError):
            MechanismExogenousInput.model_validate(_exogenous_payload(draw_index=bad_index))
        with pytest.raises(ValidationError):
            MechanismExogenousInput.model_validate(_exogenous_payload(step_index=bad_index))

    def test_realization_pair_is_both_or_neither(self) -> None:
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            MechanismExogenousInput.model_validate(
                _exogenous_payload(realization_id="realization-1")
            )
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            MechanismExogenousInput.model_validate(
                _exogenous_payload(realization_content_hash=_HASH)
            )
        paired = MechanismExogenousInput.model_validate(
            _exogenous_payload(
                realization_id="realization-1",
                realization_content_hash=_HASH,
            )
        )
        assert paired.realization_id == "realization-1"
        assert paired.realization_content_hash == _HASH
        unpaired = MechanismExogenousInput.model_validate(_exogenous_payload())
        assert unpaired.realization_id is None
        assert unpaired.realization_content_hash is None

    def test_coordinate_is_complete_and_orderable(self) -> None:
        entity = MechanismExogenousInput.model_validate(_exogenous_payload(draw_index=2))
        assert entity.coordinate == ("stream-1", "variable-1", "entity", "entity-1", 2)
        slot = MechanismExogenousInput.model_validate(
            _exogenous_payload(entity_id=None, slot_id="slot-1", draw_index=0)
        )
        assert slot.coordinate == ("stream-1", "variable-1", "slot", "slot-1", 0)
        assert entity.coordinate > slot.coordinate or entity.coordinate < slot.coordinate


# ---------------------------------------------------------------------------
# Step request: canonical order, uniqueness, agreement
# ---------------------------------------------------------------------------


class TestStepRequest:
    def test_empty_exogenous_input_is_valid(self) -> None:
        request = DomainMechanismStepRequest.model_validate(_request_payload(exogenous_inputs=[]))
        assert request.exogenous_inputs == ()

    def test_entries_must_copy_request_identity(self) -> None:
        foreign_world = _request_payload(
            world_version_id="world-other",
            exogenous_inputs=[_exogenous_payload()],
        )
        with pytest.raises(ValidationError, match="copy the request identity"):
            DomainMechanismStepRequest.model_validate(foreign_world)
        foreign_step = _request_payload(
            step_index=1,
            exogenous_inputs=[_exogenous_payload()],
        )
        with pytest.raises(ValidationError, match="copy the request identity"):
            DomainMechanismStepRequest.model_validate(foreign_step)

    def test_entry_realization_must_match_request_exactly(self) -> None:
        realized = _request_payload(
            realization_id="realization-1",
            realization_content_hash=_HASH,
        )
        request = DomainMechanismStepRequest.model_validate(realized)
        entry = request.exogenous_inputs[0]
        assert entry.realization_id == "realization-1"
        assert entry.realization_content_hash == _HASH
        absent_pair_on_entry = _request_payload(
            realization_id="realization-1",
            realization_content_hash=_HASH,
        )
        request_entries = absent_pair_on_entry["exogenous_inputs"]
        assert isinstance(request_entries, list)
        assert isinstance(request_entries[0], dict)
        del request_entries[0]["realization_id"]
        del request_entries[0]["realization_content_hash"]
        with pytest.raises(ValidationError, match="copy the optional realization identity"):
            DomainMechanismStepRequest.model_validate(absent_pair_on_entry)
        mismatched = _request_payload(
            realization_id="realization-1",
            realization_content_hash=_HASH,
        )
        mismatched_entries = mismatched["exogenous_inputs"]
        assert isinstance(mismatched_entries, list)
        assert isinstance(mismatched_entries[0], dict)
        mismatched_entries[0]["realization_id"] = "realization-other"
        with pytest.raises(ValidationError, match="copy the optional realization identity"):
            DomainMechanismStepRequest.model_validate(mismatched)

    def test_request_realization_is_both_or_neither(self) -> None:
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            DomainMechanismStepRequest.model_validate(
                _request_payload(realization_id="realization-1")
            )
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            DomainMechanismStepRequest.model_validate(
                _request_payload(realization_content_hash=_HASH)
            )

    def _canonical_entries(self) -> list[dict[str, object]]:
        return [
            _exogenous_payload(identifier="e1", stream="s1", variable="v1", draw_index=0),
            _exogenous_payload(identifier="e2", stream="s1", variable="v1", draw_index=1),
            _exogenous_payload(
                identifier="e3", stream="s1", variable="v1", entity_id=None, slot_id="sl1"
            ),
            _exogenous_payload(identifier="e4", stream="s1", variable="v2"),
            _exogenous_payload(identifier="e5", stream="s2", variable="v1"),
        ]

    def test_canonical_coordinate_order_is_accepted(self) -> None:
        request = DomainMechanismStepRequest.model_validate(
            _request_payload(exogenous_inputs=self._canonical_entries())
        )
        assert [entry.identifier for entry in request.exogenous_inputs] == [
            "e1",
            "e2",
            "e3",
            "e4",
            "e5",
        ]

    def test_noncanonical_order_is_rejected_not_sorted(self) -> None:
        entries = self._canonical_entries()
        entries[0], entries[1] = entries[1], entries[0]
        with pytest.raises(ValidationError, match="canonical coordinate order"):
            DomainMechanismStepRequest.model_validate(_request_payload(exogenous_inputs=entries))

    def test_duplicate_coordinates_and_identifiers_fail(self) -> None:
        entries = self._canonical_entries()
        entries.append(
            _exogenous_payload(identifier="e6", stream="s1", variable="v1", draw_index=0)
        )
        with pytest.raises(ValidationError, match="coordinates must be unique"):
            DomainMechanismStepRequest.model_validate(_request_payload(exogenous_inputs=entries))
        duplicated_id = self._canonical_entries()
        duplicated_id.append(
            _exogenous_payload(identifier="e1", stream="s2", variable="v9", draw_index=7)
        )
        with pytest.raises(ValidationError, match="identifiers must be unique"):
            DomainMechanismStepRequest.model_validate(
                _request_payload(exogenous_inputs=duplicated_id)
            )

    def test_payloads_hashes_and_references_are_required(self) -> None:
        missing = _request_payload()
        del missing["action_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepRequest.model_validate(missing)
        missing = _request_payload()
        del missing["mechanism_spec_content_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepRequest.model_validate(missing)

    def test_request_has_no_timestamp_or_wall_clock_field(self) -> None:
        assert not any(
            "time" in field or "clock" in field or field[-2:] == "at"
            for field in DomainMechanismStepRequest.model_fields
        )


# ---------------------------------------------------------------------------
# Step result: contiguous unique emissions/evidence, references
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_emissions_must_be_contiguous_from_zero_in_order(self) -> None:
        with pytest.raises(ValidationError, match="contiguous from zero in order"):
            DomainMechanismStepResult.model_validate(
                _result_payload(emissions=[_emission_payload(sequence_position=1)])
            )
        with pytest.raises(ValidationError, match="contiguous from zero in order"):
            DomainMechanismStepResult.model_validate(
                _result_payload(
                    emissions=[
                        _emission_payload(identifier="m-1", sequence_position=0),
                        _emission_payload(identifier="m-2", sequence_position=2),
                    ]
                )
            )

    def test_evidence_must_be_contiguous_from_zero_in_order(self) -> None:
        with pytest.raises(ValidationError, match="contiguous from zero in order"):
            DomainMechanismStepResult.model_validate(
                _result_payload(evidence=[_evidence_payload(sequence_position=1)])
            )

    def test_reordered_positions_fail(self) -> None:
        with pytest.raises(ValidationError, match="contiguous from zero in order"):
            DomainMechanismStepResult.model_validate(
                _result_payload(
                    emissions=[
                        _emission_payload(identifier="m-1", sequence_position=1),
                        _emission_payload(identifier="m-2", sequence_position=0),
                    ]
                )
            )

    def test_duplicate_emission_and_evidence_identifiers_fail(self) -> None:
        with pytest.raises(ValidationError, match="identifiers must be unique"):
            DomainMechanismStepResult.model_validate(
                _result_payload(
                    emissions=[
                        _emission_payload(identifier="m-1", sequence_position=0),
                        _emission_payload(identifier="m-1", sequence_position=1),
                    ]
                )
            )
        with pytest.raises(ValidationError, match="identifiers must be unique"):
            DomainMechanismStepResult.model_validate(
                _result_payload(
                    evidence=[
                        _evidence_payload(identifier="d-1", sequence_position=0),
                        _evidence_payload(identifier="d-1", sequence_position=1),
                    ]
                )
            )

    def test_empty_emissions_and_evidence_are_valid(self) -> None:
        result = DomainMechanismStepResult.model_validate(
            _result_payload(emissions=[], evidence=[])
        )
        assert result.emissions == ()
        assert result.evidence == ()

    def test_emission_and_evidence_hashes_are_recorded(self) -> None:
        result = DomainMechanismStepResult.model_validate(_result_payload())
        assert result.emissions[0].content_hash == _HASH
        assert result.emissions[0].emission_schema_hash == _HASH
        assert result.evidence[0].content_hash == _HASH
        assert result.evidence[0].evidence_schema_hash == _HASH

    def test_result_realization_is_both_or_neither(self) -> None:
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            DomainMechanismStepResult.model_validate(
                _result_payload(realization_id="realization-1")
            )
        realized = _result_payload(
            realization_id="realization-1",
            realization_content_hash=_HASH,
        )
        result = DomainMechanismStepResult.model_validate(realized)
        assert result.realization_id == "realization-1"
        assert result.realization_content_hash == _HASH

    def test_result_references_are_required(self) -> None:
        missing = _result_payload()
        del missing["request_id"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepResult.model_validate(missing)
        missing = _result_payload()
        del missing["next_state_hash"]
        with pytest.raises(ValidationError, match="Field required"):
            DomainMechanismStepResult.model_validate(missing)

    def test_result_has_no_persistence_or_scheduler_surface(self) -> None:
        forbidden = ("receipt", "persist", "scheduler", "winner", "recommendation", "saved_at")
        assert not any(field in DomainMechanismStepResult.model_fields for field in forbidden)
        assert not any(
            any(token in field for token in forbidden)
            for field in DomainMechanismStepResult.model_fields
        )


# ---------------------------------------------------------------------------
# Strict JSON round trips
# ---------------------------------------------------------------------------


class TestJsonRoundTrips:
    def test_spec_round_trips_strictly(self) -> None:
        instance = DomainMechanismSpec.model_validate(_spec_payload())
        reloaded = DomainMechanismSpec.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        assert instance.model_dump(mode="json") == json.loads(instance.model_dump_json())

    def test_request_round_trips_strictly(self) -> None:
        instance = DomainMechanismStepRequest.model_validate(_request_payload())
        reloaded = DomainMechanismStepRequest.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        dumped = instance.model_dump(mode="json")
        assert dumped["exogenous_inputs"][0]["value"] == 1.5
        assert isinstance(dumped["exogenous_inputs"][0]["value"], float)

    def test_result_round_trips_strictly(self) -> None:
        instance = DomainMechanismStepResult.model_validate(_result_payload())
        reloaded = DomainMechanismStepResult.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        assert instance.model_dump(mode="json") == json.loads(instance.model_dump_json())

    def test_int_and_float_stay_distinct_through_json(self) -> None:
        spec = DomainMechanismSpec.model_validate(_spec_payload(timestep=1))
        dumped = json.loads(spec.model_dump_json())
        assert dumped["timestep"] == 1
        assert isinstance(dumped["timestep"], int)
        boundary = json.loads(
            MechanismQuantizationBoundary.model_validate(
                _boundary_payload(quantum=2)
            ).model_dump_json()
        )
        assert isinstance(boundary["quantum"], int)


# ---------------------------------------------------------------------------
# Correction E regression: typed contiguity helper covers both record kinds
# ---------------------------------------------------------------------------


class TestContiguityHelperTyping:
    def test_helper_accepts_emission_and_evidence_collections(self) -> None:
        emissions = [
            MechanismEmissionRecord.model_validate(_emission_payload(identifier="m-1")),
            MechanismEmissionRecord.model_validate(
                _emission_payload(identifier="m-2", sequence_position=1)
            ),
        ]
        evidence = [
            MechanismEvidenceRecord.model_validate(_evidence_payload(identifier="d-1")),
            MechanismEvidenceRecord.model_validate(
                _evidence_payload(identifier="d-2", sequence_position=1)
            ),
        ]
        result = DomainMechanismStepResult.model_validate(
            _result_payload(
                emissions=[dict(item) for item in emissions],
                evidence=[dict(item) for item in evidence],
            )
        )
        assert [record.sequence_position for record in result.emissions] == [0, 1]
        assert [record.sequence_position for record in result.evidence] == [0, 1]


# ---------------------------------------------------------------------------
# No executable/provider/import/policy/persistence surface anywhere
# ---------------------------------------------------------------------------


class TestPuritySurface:
    _PUBLIC_MECHANISM_CONTRACTS = (
        DomainMechanismSpec,
        DomainMechanismStepRequest,
        DomainMechanismStepResult,
    )

    def test_public_contracts_express_no_forbidden_field(self) -> None:
        for contract in self._PUBLIC_MECHANISM_CONTRACTS:
            for forbidden in _FORBIDDEN_FIELDS:
                assert forbidden not in contract.model_fields, (contract.__name__, forbidden)

    def test_nested_helpers_express_no_forbidden_field(self) -> None:
        for model in _NESTED_MECHANISM_MODELS:
            for forbidden in _FORBIDDEN_FIELDS:
                assert forbidden not in model.model_fields, (model.__name__, forbidden)

    def test_module_source_contains_no_execution_machinery(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for token in (
            "importlib",
            "__import__",
            "import_module",
            "walk_packages",
            "iter_modules",
            "entry_points",
            "eval(",
            "exec(",
            "subprocess",
            "socket",
            "urllib",
            "requests.",
            "open(",
            "Path(",
            "os.environ",
            "time.time",
            "datetime.now",
            "random.",
        ):
            assert token not in source, f"forbidden execution surface in module: {token}"


# ---------------------------------------------------------------------------
# Correction E regression: realized and absent-realization request cases
# ---------------------------------------------------------------------------


class TestRealizationCases:
    def test_present_realization_request_is_valid_and_copied(self) -> None:
        payload = _request_payload(
            realization_id="realization-1",
            realization_content_hash=_HASH,
        )
        request = DomainMechanismStepRequest.model_validate(payload)
        assert request.realization_id == "realization-1"
        assert request.realization_content_hash == _HASH
        assert request.exogenous_inputs[0].realization_id == "realization-1"
        assert request.exogenous_inputs[0].realization_content_hash == _HASH

    def test_absent_realization_request_is_valid_and_copied(self) -> None:
        request = DomainMechanismStepRequest.model_validate(_request_payload())
        assert request.realization_id is None
        assert request.realization_content_hash is None
        assert request.exogenous_inputs[0].realization_id is None
        assert request.exogenous_inputs[0].realization_content_hash is None

    def test_result_realization_absent_by_default(self) -> None:
        result = DomainMechanismStepResult.model_validate(_result_payload())
        assert result.realization_id is None
        assert result.realization_content_hash is None


# ---------------------------------------------------------------------------
# Cross-check: NaN/infinities can never sneak through any explicit numeric
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nan_value", [float("nan"), float("inf"), float("-inf")])
def test_spec_rejects_nonfinite_timestep(nan_value: float) -> None:
    with pytest.raises(ValidationError):
        DomainMechanismSpec.model_validate(_spec_payload(timestep=nan_value))


@pytest.mark.parametrize("nan_value", [float("nan"), float("inf"), float("-inf")])
def test_boundary_rejects_nonfinite_quantum(nan_value: float) -> None:
    with pytest.raises(ValidationError):
        MechanismQuantizationBoundary.model_validate(_boundary_payload(quantum=nan_value))


@pytest.mark.parametrize("nan_value", [float("nan"), float("inf"), float("-inf")])
def test_exogenous_rejects_nonfinite_value(nan_value: float) -> None:
    with pytest.raises(ValidationError):
        MechanismExogenousInput.model_validate(_exogenous_payload(value=nan_value))
