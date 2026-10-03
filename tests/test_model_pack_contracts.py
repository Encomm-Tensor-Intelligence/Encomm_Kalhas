"""H29-S02B adversarial contract tests for the Model Pack profiles.

Covers the three public Phase 29 contracts (``ModelPackReleaseProfile``,
``ModelPackAssuranceProfile``, ``ModelPackCatalogueEntry``) and their
nested helpers exactly as frozen for H29-S02B: registry order/count and
schema export, nested helpers never registered or schematized, strict
JSON round trips, frozen/extra-forbid behavior, exact release-profile
binding to the embedded manifest and mechanism spec (tenant, pack,
version, manifest, mechanism, configuration, and hash identity must
agree; any disagreement fails closed), duplicate identity collections
fail closed, declarative-only dataset/license/provenance/resource/
scope/unit/use/assumption/limitation records, the mandatory closed
public-sector prohibited-use floor, the exact maturity vocabulary with
cumulative evidence-derived requirements and closed external review
coverage, bounded evidence-cited claims, retained failures that remain
visible, forbidden maturity/status terminology rejection, catalogue
entries that cannot express execution/discovery/provider capability and
cannot display unbound maturity above ``catalogued``, and the absence of
any executable/provider/import/policy/persistence surface.

Only generic synthetic names and data are used. Nothing here loads,
executes, imports, or persists anything.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast, get_args, get_origin, get_type_hints

import pytest
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import (
    ModelPackAssuranceProfile,
    ModelPackCatalogueEntry,
    ModelPackEvidenceRecord,
    ModelPackReleaseProfile,
    ModelPackRetainedFailure,
    ModelPackSupportedClaim,
)
from kalhas.domain_packs import DomainPack
from kalhas.domain_packs import base as domain_pack_base
from pydantic import BaseModel, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
MODULE_PATH = REPO_ROOT / "kalhas" / "contracts" / "v1" / "model_pack.py"

_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_HASH_ALT = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


#: Numeric stand-ins that must be rejected before any coercion.
class _IntSubclass(int):
    pass


class _FloatSubclass(float):
    pass


#: The complete canonical public-sector prohibited-use floor.
FLOOR = (
    "autonomous_public_decisions",
    "eligibility_or_benefit_decisions",
    "enforcement_recommendations",
    "predictive_policing_judgments",
    "individual_or_social_scoring",
    "political_persuasion",
    "voter_targeting",
    "biometric_or_surveillance_assessment",
    "offensive_cyber_action",
    "live_effects",
)

#: Nested helper models that must never become public or schematized.
_NESTED_MODEL_PACK_MODELS = (
    ModelPackEvidenceRecord,
    ModelPackRetainedFailure,
    ModelPackSupportedClaim,
)

#: Field names that must never exist on any Model Pack contract.
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
    "discovery",
    "plugin",
    "persistence",
    "persist",
    "receipt",
    "execute_fn",
    "fn",
    "func",
    "command",
    "loader",
)


# ---------------------------------------------------------------------------
# Generic synthetic payload builders (plain dicts only).
# ---------------------------------------------------------------------------


def _manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "manifest-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "name": "Synthetic reference pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1"],
                "output_ids": ["out-1"],
                "metadata": {},
            }
        ],
        "schema_metadata": {"declarative": True},
        "content_hash": _HASH,
        "created_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def _mechanism_spec_payload(**overrides: object) -> dict[str, object]:
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
        "data_identities": [],
        "parameter_bindings": [],
        "timestep": 0.5,
        "timestep_unit": "hour",
        "event_order": ["event-a"],
        "reduction_order": ["reduction-a"],
        "numeric_profile": "kalhas-platform-bound-binary64-v1",
        "precision": "ieee-754-binary64",
        "rounding_mode": "round-to-nearest-ties-to-even",
        "quantization_boundaries": [],
        "platform_identity": {
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
        },
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def _release_profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "release-profile-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_id": "manifest-1",
        "manifest_content_hash": _HASH,
        "manifest": _manifest_payload(),
        "mechanism_id": "mechanism-1",
        "mechanism_version": "1.0.0",
        "mechanism_protocol_version": "1.0.0",
        "configuration_identity": _HASH,
        "mechanism_spec": _mechanism_spec_payload(),
        "decision_scope": "decision_support_only",
        "accountability": "accountable_human_authority_required",
        "output_labeling": "conditional_modeled_outcomes",
        "scope": {
            "decision_questions": ["question-1"],
            "intended_users": ["user-role-1"],
            "horizon": "horizon-1",
            "resolution": "resolution-1",
            "validity_envelope": "envelope-1",
        },
        "units": [{"quantity_id": "quantity-1", "unit": "units"}],
        "provenance": {
            "author_id": "author-1",
            "method": "method-1",
            "statement": "Declared synthetic provenance",
        },
        "datasets": [
            {
                "dataset_id": "dataset-1",
                "vintage": "vintage-1",
                "content_hash": _HASH,
                "license_id": "license-1",
                "license_statement": "Declared synthetic license",
            }
        ],
        "resource_envelope": {
            "max_memory_megabytes": 512,
            "max_cpu_seconds": 60,
            "memory_unit": "MiB",
            "cpu_unit": "seconds",
        },
        "intended_uses": [{"use_id": "use-1", "statement": "Declared intended use"}],
        "prohibited_uses": list(FLOOR),
        "assumptions": [{"assumption_id": "assumption-1", "statement": "Declared assumption"}],
        "limitations": [{"limitation_id": "limitation-1", "statement": "Declared limitation"}],
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def _evidence_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "evidence_id": "evidence-1",
        "kind": "synthetic_conformance",
        "reference": "retained-artifact-1",
        "content_hash": _HASH,
    }
    payload.update(overrides)
    return payload


def _failure_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "failure_id": "failure-1",
        "statement": "Declared retained failure",
        "observed_in": "context-1",
    }
    payload.update(overrides)
    return payload


def _claim_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "claim_id": "claim-1",
        "statement": "Declared bounded claim",
        "evidence_ids": ["evidence-1"],
    }
    payload.update(overrides)
    return payload


def _assurance_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "assurance-profile-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "release_profile_id": "release-profile-1",
        "release_profile_content_hash": _HASH,
        "maturity": "catalogued",
        "evidence": [_evidence_payload()],
        "retained_failures": [_failure_payload()],
        "supported_claims": [],
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def _catalogue_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "catalogue-entry-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "title": "Synthetic catalogue title",
        "summary": "Synthetic catalogue summary",
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registry, schemas, freeze surface
# ---------------------------------------------------------------------------


class TestRegistryAndSchemas:
    def test_model_pack_contracts_occupy_indexes_58_to_60_in_order(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert len(names) == 61
        assert names[58:61] == [
            "ModelPackReleaseProfile",
            "ModelPackAssuranceProfile",
            "ModelPackCatalogueEntry",
        ]
        assert names[55:58] == [
            "DomainMechanismSpec",
            "DomainMechanismStepRequest",
            "DomainMechanismStepResult",
        ]

    def test_schema_export_covers_exactly_the_registry(self) -> None:
        generated = generate_schemas()
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert set(generated) == {f"{name}.schema.json" for name in names}

    def test_model_pack_schemas_equal_live_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            ModelPackReleaseProfile: "ModelPackReleaseProfile.schema.json",
            ModelPackAssuranceProfile: "ModelPackAssuranceProfile.schema.json",
            ModelPackCatalogueEntry: "ModelPackCatalogueEntry.schema.json",
        }
        for contract, filename in expected.items():
            rendered = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_nested_helpers_are_never_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for model in _NESTED_MODEL_PACK_MODELS:
            assert model.__name__ not in names

    def test_nested_helpers_have_no_standalone_schema(self) -> None:
        artifact_names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for model in _NESTED_MODEL_PACK_MODELS:
            assert f"{model.__name__}.schema.json" not in artifact_names

    def test_frozen_public_contracts_reject_mutation_and_unknown_fields(self) -> None:
        for contract, payload in (
            (ModelPackReleaseProfile, _release_profile_payload()),
            (ModelPackAssuranceProfile, _assurance_payload()),
            (ModelPackCatalogueEntry, _catalogue_payload()),
        ):
            instance = contract.model_validate(payload)
            with pytest.raises(ValidationError):
                instance.identifier = "tampered"
            tampered = dict(payload)
            tampered["unexpected_field"] = 1
            with pytest.raises(ValidationError):
                contract.model_validate(tampered)


# ---------------------------------------------------------------------------
# Strict JSON round trips
# ---------------------------------------------------------------------------


class TestJsonRoundTrips:
    def test_release_profile_round_trips_strictly(self) -> None:
        instance = ModelPackReleaseProfile.model_validate(_release_profile_payload())
        reloaded = ModelPackReleaseProfile.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        assert instance.model_dump(mode="json") == json.loads(instance.model_dump_json())

    def test_assurance_profile_round_trips_strictly(self) -> None:
        instance = ModelPackAssuranceProfile.model_validate(_assurance_payload())
        reloaded = ModelPackAssuranceProfile.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        assert instance.model_dump(mode="json") == json.loads(instance.model_dump_json())

    def test_catalogue_entry_round_trips_strictly(self) -> None:
        instance = ModelPackCatalogueEntry.model_validate(_catalogue_payload())
        reloaded = ModelPackCatalogueEntry.model_validate_json(instance.model_dump_json())
        assert reloaded == instance
        assert instance.model_dump(mode="json") == json.loads(instance.model_dump_json())

    def test_metadata_rejects_non_exact_json(self) -> None:
        for contract, payload in (
            (ModelPackReleaseProfile, _release_profile_payload()),
            (ModelPackAssuranceProfile, _assurance_payload()),
            (ModelPackCatalogueEntry, _catalogue_payload()),
        ):
            bad = dict(payload)
            bad["metadata"] = {"at": Decimal("1")}
            with pytest.raises(ValidationError, match="must contain only exact JSON values"):
                contract.model_validate(bad)
            bad = dict(payload)
            bad["metadata"] = {"x": float("nan")}
            with pytest.raises(ValidationError):
                contract.model_validate(bad)


# ---------------------------------------------------------------------------
# Release profile: exact binding, floor, uniqueness
# ---------------------------------------------------------------------------


class TestReleaseProfileBinding:
    def test_embedded_manifest_and_mechanism_spec_are_accepted(self) -> None:
        profile = ModelPackReleaseProfile.model_validate(_release_profile_payload())
        assert profile.manifest.pack_id == "pack-1"
        assert profile.mechanism_spec.mechanism_id == "mechanism-1"
        assert profile.mechanism_spec.configuration_hash == profile.configuration_identity

    @pytest.mark.parametrize(
        "field",
        [
            "pack_id",
            "pack_version",
            "manifest_id",
            "manifest_content_hash",
            "mechanism_id",
            "mechanism_version",
            "mechanism_protocol_version",
            "configuration_identity",
        ],
    )
    def test_copied_identity_mismatch_fails_closed(self, field: str) -> None:
        payload = _release_profile_payload()
        original = payload[field]
        flipped = (
            _HASH_ALT
            if isinstance(original, str) and len(original) == 64
            else ("9.9.9" if field == "pack_version" else "other")
        )
        payload[field] = flipped
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(payload)

    @pytest.mark.parametrize("embedded", ["manifest", "mechanism_spec"])
    @pytest.mark.parametrize(
        "change",
        ["pack_id", "pack_version", "tenant_id"],
        ids=["pack_id", "pack_version", "tenant_id"],
    )
    def test_embedded_identity_disagreement_fails_closed(self, embedded: str, change: str) -> None:
        value = _release_profile_payload()[embedded]
        assert isinstance(value, dict)
        foreign = {
            "tenant_id": "tenant-foreign",
            "pack_id": "pack-x",
            "pack_version": "9.9.9",
        }
        value[change] = foreign[change]
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(_release_profile_payload(**{embedded: value}))

    @pytest.mark.parametrize(
        "change",
        ["manifest_id", "manifest_content_hash", "mechanism_id", "mechanism_version"],
    )
    def test_mechanism_spec_manifest_identity_disagreement_fails_closed(self, change: str) -> None:
        spec = _mechanism_spec_payload()
        spec[change] = _HASH_ALT if "hash" in change else "other"
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(_release_profile_payload(mechanism_spec=spec))

    def test_profile_and_manifest_agreeing_against_foreign_spec_fails(self) -> None:
        """Profile+manifest on one hash while the spec carries another fails."""
        with pytest.raises(ValidationError, match="mechanism spec disagrees"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    manifest_content_hash=_HASH_ALT,
                    manifest=_manifest_payload(content_hash=_HASH_ALT),
                )
            )

    def test_duplicate_identity_collections_fail_closed(self) -> None:
        with pytest.raises(ValidationError, match="quantity ids must be unique"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    units=[
                        {"quantity_id": "q-1", "unit": "a"},
                        {"quantity_id": "q-1", "unit": "b"},
                    ]
                )
            )
        with pytest.raises(ValidationError, match="dataset ids must be unique"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    datasets=[
                        {
                            "dataset_id": "d-1",
                            "vintage": "v-1",
                            "content_hash": _HASH,
                            "license_id": "l-1",
                            "license_statement": "s",
                        },
                        {
                            "dataset_id": "d-1",
                            "vintage": "v-2",
                            "content_hash": _HASH,
                            "license_id": "l-1",
                            "license_statement": "s",
                        },
                    ]
                )
            )
        with pytest.raises(ValidationError, match="intended use ids must be unique"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    intended_uses=[
                        {"use_id": "u-1", "statement": "s"},
                        {"use_id": "u-1", "statement": "s2"},
                    ]
                )
            )
        with pytest.raises(ValidationError, match="assumption ids must be unique"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    assumptions=[
                        {"assumption_id": "a-1", "statement": "s"},
                        {"assumption_id": "a-1", "statement": "s2"},
                    ]
                )
            )
        with pytest.raises(ValidationError, match="limitation ids must be unique"):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    limitations=[
                        {"limitation_id": "l-1", "statement": "s"},
                        {"limitation_id": "l-1", "statement": "s2"},
                    ]
                )
            )


class TestPublicSectorFloor:
    def test_floor_is_accepted_verbatim(self) -> None:
        profile = ModelPackReleaseProfile.model_validate(_release_profile_payload())
        assert profile.prohibited_uses == FLOOR
        assert profile.decision_scope == "decision_support_only"
        assert profile.accountability == "accountable_human_authority_required"
        assert profile.output_labeling == "conditional_modeled_outcomes"

    def test_floor_cannot_be_omitted(self) -> None:
        payload = _release_profile_payload()
        del payload["prohibited_uses"]
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(payload)

    @pytest.mark.parametrize(
        "weakening",
        [
            FLOOR[1:],  # omission of one prohibited use
            tuple(reversed(FLOOR)),  # reordering
            (*FLOOR[1:], FLOOR[0]),  # rotation (reordered, duplicate-free)
            ("custom_extra_use", *FLOOR),  # extension
            FLOOR[:9],  # drop of live_effects
        ],
        ids=["omission", "reversed", "rotation", "extension", "dropped-tail"],
    )
    def test_floor_cannot_be_weakened_or_reordered(self, weakening: tuple[str, ...]) -> None:
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(prohibited_uses=list(weakening))
            )

    def test_floor_values_are_closed_literals(self) -> None:
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(prohibited_uses=[*FLOOR[:-1], "something_else_entirely"])
            )

    @pytest.mark.parametrize(
        "field, good, bad",
        [
            ("decision_scope", "decision_support_only", "autonomous_operations"),
            (
                "accountability",
                "accountable_human_authority_required",
                "automation_without_oversight",
            ),
            ("output_labeling", "conditional_modeled_outcomes", "raw_predictions"),
        ],
    )
    def test_floor_literals_are_closed(self, field: str, good: str, bad: str) -> None:
        payload = _release_profile_payload(**{field: good})
        profile = ModelPackReleaseProfile.model_validate(payload)
        assert getattr(profile, field) == good
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(_release_profile_payload(**{field: bad}))

    def test_intended_uses_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(_release_profile_payload(intended_uses=[]))

    def test_records_are_declarative_only(self) -> None:
        profile = ModelPackReleaseProfile.model_validate(_release_profile_payload())
        assert profile.scope.decision_questions == ("question-1",)
        assert profile.units[0].unit == "units"
        assert profile.provenance.author_id == "author-1"
        assert profile.datasets[0].license_id == "license-1"
        assert profile.resource_envelope.max_memory_megabytes == 512
        assert profile.intended_uses[0].statement == "Declared intended use"
        assert profile.assumptions[0].statement == "Declared assumption"
        assert profile.limitations[0].statement == "Declared limitation"

    @pytest.mark.parametrize(
        "bad_value",
        [
            0,
            -1,
            "512",
            True,
            float("nan"),
            float("inf"),
            float("-inf"),
            0.0,
            Decimal("1"),
            Decimal("0.5"),
            _IntSubclass(5),
            _FloatSubclass(2.5),
            object(),
        ],
    )
    def test_resource_envelope_rejects_non_positive_or_non_exact(self, bad_value: object) -> None:
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(
                    resource_envelope={
                        "max_memory_megabytes": bad_value,
                        "max_cpu_seconds": 60,
                        "memory_unit": "MiB",
                        "cpu_unit": "seconds",
                    }
                )
            )

    def test_resource_envelope_accepts_exact_int_and_finite_float(self) -> None:
        envelope = ModelPackReleaseProfile.model_validate(
            _release_profile_payload()
        ).resource_envelope
        assert type(envelope.max_memory_megabytes) is int
        assert envelope.max_memory_megabytes == 512
        assert type(envelope.max_cpu_seconds) is int
        assert envelope.max_cpu_seconds == 60
        fractional = ModelPackReleaseProfile.model_validate(
            _release_profile_payload(
                resource_envelope={
                    "max_memory_megabytes": 0.5,
                    "max_cpu_seconds": 1.25,
                    "memory_unit": "MiB",
                    "cpu_unit": "seconds",
                }
            )
        ).resource_envelope
        assert type(fractional.max_memory_megabytes) is float
        assert fractional.max_cpu_seconds == 1.25

    def test_declared_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            ModelPackReleaseProfile.model_validate(
                _release_profile_payload(declared_at=datetime(2026, 1, 1, 12, 0, 0))
            )


# ---------------------------------------------------------------------------
# Assurance profile: maturity vocabulary, evidence derivation, claims
# ---------------------------------------------------------------------------


class TestMaturityVocabulary:
    @pytest.mark.parametrize(
        "maturity, evidence_kinds",
        [
            ("catalogued", []),
            ("conformance_only", ["synthetic_conformance"]),
            ("experimental", ["synthetic_conformance", "deterministic_execution"]),
            (
                "benchmarked",
                ["synthetic_conformance", "deterministic_execution", "benchmark"],
            ),
            (
                "externally_reviewed",
                [
                    "synthetic_conformance",
                    "deterministic_execution",
                    "benchmark",
                    "external_review",
                ],
            ),
            (
                "partner_evaluation_ready",
                [
                    "synthetic_conformance",
                    "deterministic_execution",
                    "benchmark",
                    "external_review",
                    "packaging",
                    "replay",
                    "security",
                    "governance",
                ],
            ),
        ],
    )
    def test_each_maturity_value_is_expressible(
        self, maturity: str, evidence_kinds: list[str]
    ) -> None:
        evidence = []
        for position, kind in enumerate(evidence_kinds):
            extra: dict[str, object] = {}
            if kind == "benchmark":
                extra = {
                    "evidence_id": f"ev-{position}",
                    "kind": kind,
                    "reference": f"ref-{position}",
                    "data_vintage": "vintage-1",
                    "geography": "geo-1",
                    "horizon": "horizon-1",
                    "bound_claim_ids": ["claim-1"],
                }
            elif kind == "external_review":
                extra = {
                    "evidence_id": f"ev-{position}",
                    "kind": kind,
                    "reference": f"ref-{position}",
                    "review_state": "closed",
                    "covered_claim_ids": ["claim-1"],
                }
            else:
                extra = {
                    "evidence_id": f"ev-{position}",
                    "kind": kind,
                    "reference": f"ref-{position}",
                }
            evidence.append(_evidence_payload(**extra))
        claims = [_claim_payload(evidence_ids=["ev-0"])] if evidence_kinds else []
        model = ModelPackAssuranceProfile.model_validate(
            _assurance_payload(maturity=maturity, evidence=evidence, supported_claims=claims)
        )
        assert model.maturity == maturity

    @pytest.mark.parametrize(
        "forbidden",
        [
            "government_ready",
            "certified",
            "universally_validated",
            "autonomous",
            "production_safe",
            "production_ready",
            "approved",
            "validated",
            "experimental_plus",
            "CONFORMANCE_ONLY",
        ],
    )
    def test_forbidden_or_unknown_statuses_are_rejected(self, forbidden: str) -> None:
        with pytest.raises(ValidationError):
            ModelPackAssuranceProfile.model_validate(_assurance_payload(maturity=forbidden))


def _review_evidence(claim_ids: list[str], closed: bool = True) -> dict[str, object]:
    return _evidence_payload(
        evidence_id="review-1",
        kind="external_review",
        reference="review-artifact-1",
        review_state="closed" if closed else "open",
        covered_claim_ids=list(claim_ids),
    )


def _bench_evidence() -> dict[str, object]:
    return _evidence_payload(
        evidence_id="ev-bench",
        kind="benchmark",
        reference="bench-artifact-1",
        data_vintage="vintage-1",
        geography="geo-1",
        horizon="horizon-1",
        bound_claim_ids=["claim-1"],
    )


def _claim() -> dict[str, object]:
    return _claim_payload(claim_id="claim-1", evidence_ids=["ev-bench"])


def _benchmarked_assurance(**overrides: object) -> dict[str, object]:
    payload = _assurance_payload(
        maturity="benchmarked",
        evidence=[
            _evidence_payload(evidence_id="ev-conf"),
            _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
            _bench_evidence(),
        ],
        supported_claims=[_claim()],
    )
    payload.update(overrides)
    return payload


def _externally_reviewed_assurance(**overrides: object) -> dict[str, object]:
    payload = _assurance_payload(
        maturity="externally_reviewed",
        evidence=[
            _evidence_payload(evidence_id="ev-conf"),
            _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
            _bench_evidence(),
            _review_evidence(["claim-1"]),
        ],
        supported_claims=[_claim()],
    )
    payload.update(overrides)
    return payload


def _partner_ready_assurance(**overrides: object) -> dict[str, object]:
    payload = _assurance_payload(
        maturity="partner_evaluation_ready",
        evidence=[
            _evidence_payload(evidence_id="ev-conf"),
            _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
            _bench_evidence(),
            _review_evidence(["claim-1"]),
            _evidence_payload(evidence_id="ev-pack", kind="packaging"),
            _evidence_payload(evidence_id="ev-replay", kind="replay"),
            _evidence_payload(evidence_id="ev-sec", kind="security"),
            _evidence_payload(evidence_id="ev-gov", kind="governance"),
        ],
        supported_claims=[_claim()],
    )
    payload.update(overrides)
    return payload


class TestMaturityIsEvidenceDerived:
    def test_catalogued_requires_nothing(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_assurance_payload(evidence=[]))
        assert model.maturity == "catalogued"

    def test_conformance_only_requires_synthetic_conformance(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(
            _assurance_payload(maturity="conformance_only")
        )
        assert model.maturity == "conformance_only"
        with pytest.raises(ValidationError, match="requires evidence kinds"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(maturity="conformance_only", evidence=[])
            )

    def test_experimental_requires_execution_and_conformance(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(
            _assurance_payload(
                maturity="experimental",
                evidence=[
                    _evidence_payload(),
                    _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
                ],
            )
        )
        assert model.maturity == "experimental"
        with pytest.raises(ValidationError, match="requires evidence kinds"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(
                    maturity="experimental",
                    evidence=[_evidence_payload()],
                )
            )

    def test_benchmarked_requires_bound_benchmark_evidence(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_benchmarked_assurance())
        assert model.maturity == "benchmarked"
        with pytest.raises(ValidationError, match="requires evidence kinds"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(
                    maturity="benchmarked",
                    evidence=[
                        _evidence_payload(),
                        _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
                    ],
                )
            )

    def test_externally_reviewed_requires_closed_review(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_externally_reviewed_assurance())
        assert model.maturity == "externally_reviewed"
        with pytest.raises(ValidationError, match="closed external review"):
            ModelPackAssuranceProfile.model_validate(
                _externally_reviewed_assurance(
                    evidence=[
                        _evidence_payload(evidence_id="ev-conf"),
                        _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
                        _bench_evidence(),
                        _review_evidence(["claim-1"], closed=False),
                    ]
                )
            )

    def test_partner_evaluation_ready_requires_all_governance_evidence(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_partner_ready_assurance())
        assert model.maturity == "partner_evaluation_ready"
        for dropped in ("packaging", "replay", "security", "governance"):
            evidence = _partner_ready_assurance()["evidence"]
            assert isinstance(evidence, list)
            filtered = [
                dict(item)
                for item in evidence
                if isinstance(item, dict) and item.get("kind") != dropped
            ]
            with pytest.raises(ValidationError):
                ModelPackAssuranceProfile.model_validate(
                    _assurance_payload(maturity="partner_evaluation_ready", evidence=filtered)
                )

    def test_unsupported_maturity_escalation_fails(self) -> None:
        with pytest.raises(ValidationError, match="requires evidence kinds"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(maturity="partner_evaluation_ready")
            )

    def test_maturity_cannot_skip_cumulative_levels(self) -> None:
        with pytest.raises(ValidationError, match="requires evidence kinds"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(
                    maturity="experimental",
                    evidence=[
                        _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution")
                    ],
                )
            )


class TestClaimsAndEvidence:
    def test_claim_must_cite_existing_evidence(self) -> None:
        with pytest.raises(ValidationError, match="cites evidence absent"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(
                    supported_claims=[_claim_payload(evidence_ids=["evidence-absent-from-profile"])]
                )
            )

    def test_claim_must_cite_at_least_one_evidence_record(self) -> None:
        with pytest.raises(ValidationError):
            ModelPackSupportClaim_bad = _claim_payload(evidence_ids=[])
            del ModelPackSupportClaim_bad["evidence_ids"]
            ModelPackSupportedClaim.model_validate(ModelPackSupportClaim_bad)

    def test_claims_are_bounded_to_this_profile(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_benchmarked_assurance())
        assert model.supported_claims[0].claim_id == "claim-1"
        assert model.supported_claims[0].evidence_ids == ("ev-bench",)

    def test_benchmark_evidence_must_bind_vintage_geography_horizon_and_claim(self) -> None:
        with pytest.raises(ValidationError, match="vintage, geography, and horizon"):
            ModelPackEvidenceRecord.model_validate(
                _evidence_payload(kind="benchmark", reference="r", bound_claim_ids=["c-1"])
            )
        with pytest.raises(ValidationError, match="at least one supported claim"):
            ModelPackEvidenceRecord.model_validate(
                _evidence_payload(
                    kind="benchmark",
                    reference="r",
                    data_vintage="v",
                    geography="g",
                    horizon="h",
                )
            )

    def test_external_review_evidence_must_declare_review_state(self) -> None:
        with pytest.raises(ValidationError, match="review state"):
            ModelPackEvidenceRecord.model_validate(
                _evidence_payload(kind="external_review", reference="r")
            )

    def test_open_review_does_not_ground_reviewed_maturity(self) -> None:
        with pytest.raises(ValidationError, match="closed external review"):
            ModelPackAssuranceProfile.model_validate(
                _externally_reviewed_assurance(
                    evidence=[
                        _evidence_payload(),
                        _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
                        _evidence_payload(
                            evidence_id="ev-bench",
                            kind="benchmark",
                            data_vintage="vintage-1",
                            geography="geo-1",
                            horizon="horizon-1",
                            bound_claim_ids=["claim-1"],
                        ),
                        _review_evidence(["claim-1"], closed=False),
                    ]
                )
            )

    def test_closed_review_must_cover_every_claim(self) -> None:
        """A closed review covering only a strict subset fails closed.

        Both supported claims are internally consistent (each cites
        existing evidence, the benchmark binds both), so validation
        reaches the intended closed-review coverage validator, which must
        reject the uncovered second claim.
        """
        with pytest.raises(ValidationError, match="cover every supported claim"):
            ModelPackAssuranceProfile.model_validate(
                _externally_reviewed_assurance(
                    evidence=[
                        _evidence_payload(evidence_id="ev-conf"),
                        _evidence_payload(evidence_id="ev-exec", kind="deterministic_execution"),
                        _evidence_payload(
                            evidence_id="ev-bench",
                            kind="benchmark",
                            reference="bench-artifact-1",
                            data_vintage="vintage-1",
                            geography="geo-1",
                            horizon="horizon-1",
                            bound_claim_ids=["claim-1", "claim-2"],
                        ),
                        _review_evidence(["claim-1"]),
                    ],
                    supported_claims=[
                        _claim(),
                        _claim_payload(
                            claim_id="claim-2",
                            statement="Different",
                            evidence_ids=["ev-bench"],
                        ),
                    ],
                )
            )

    def test_evidence_binding_unknown_claim_fails(self) -> None:
        with pytest.raises(ValidationError, match="claims absent from this profile"):
            ModelPackAssuranceProfile.model_validate(
                _benchmarked_assurance(
                    supported_claims=[
                        _claim_payload(claim_id="other-claim", evidence_ids=["ev-bench"])
                    ]
                )
            )

    def test_duplicate_evidence_ids_fail_closed(self) -> None:
        with pytest.raises(ValidationError, match="evidence ids must be unique"):
            ModelPackAssuranceProfile.model_validate(
                _assurance_payload(evidence=[_evidence_payload(), _evidence_payload()])
            )

    def test_duplicate_claim_ids_fail_closed(self) -> None:
        with pytest.raises(ValidationError, match="supported claim ids must be unique"):
            ModelPackAssuranceProfile.model_validate(
                _benchmarked_assurance(
                    supported_claims=[
                        _claim_payload(),
                        _claim_payload(statement="different"),
                    ]
                )
            )


class TestRetainedFailures:
    def test_retained_failures_remain_present(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_partner_ready_assurance())
        assert [failure.failure_id for failure in model.retained_failures] == ["failure-1"]

    def test_positive_maturity_never_clears_failures(self) -> None:
        model = ModelPackAssuranceProfile.model_validate(_partner_ready_assurance())
        assert model.maturity == "partner_evaluation_ready"
        assert len(model.retained_failures) == 1

    def test_no_field_can_overwrite_or_resolve_failures(self) -> None:
        assert not any(
            "resolve" in field or "overwrite" in field or "clear" in field
            for field in ModelPackAssuranceProfile.model_fields
        )
        assert not any(
            "resolved" in field or "resolved" in str(field_type)
            for field, field_type in ModelPackRetainedFailure.model_fields.items()
        )


# ---------------------------------------------------------------------------
# Catalogue entry: declarative only, unbound roadmap stays catalogued
# ---------------------------------------------------------------------------


class TestCatalogueEntry:
    def test_unbound_roadmap_entry_is_catalogued(self) -> None:
        entry = ModelPackCatalogueEntry.model_validate(_catalogue_payload())
        assert entry.displayed_maturity == "catalogued"
        assert entry.release_profile_id is None
        assert entry.assurance_profile_id is None

    def test_unbound_entry_cannot_display_higher_maturity(self) -> None:
        for maturity in ("conformance_only", "experimental", "benchmarked"):
            with pytest.raises(ValidationError, match="bound to an exact assurance profile"):
                ModelPackCatalogueEntry.model_validate(
                    _catalogue_payload(displayed_maturity=maturity)
                )

    def test_bound_entry_may_display_higher_maturity(self) -> None:
        entry = ModelPackCatalogueEntry.model_validate(
            _catalogue_payload(
                displayed_maturity="experimental",
                release_profile_id="release-profile-1",
                release_profile_content_hash=_HASH,
                assurance_profile_id="assurance-profile-1",
                assurance_profile_content_hash=_HASH,
            )
        )
        assert entry.displayed_maturity == "experimental"

    def test_assurance_reference_requires_release_reference(self) -> None:
        with pytest.raises(ValidationError, match="also carries the exact release-profile"):
            ModelPackCatalogueEntry.model_validate(
                _catalogue_payload(
                    assurance_profile_id="assurance-profile-1",
                    assurance_profile_content_hash=_HASH,
                )
            )

    def test_release_only_reference_remains_valid(self) -> None:
        entry = ModelPackCatalogueEntry.model_validate(
            _catalogue_payload(
                release_profile_id="release-profile-1",
                release_profile_content_hash=_HASH,
            )
        )
        assert entry.release_profile_id == "release-profile-1"
        assert entry.assurance_profile_id is None
        assert entry.displayed_maturity == "catalogued"

    def test_profile_references_are_both_or_neither(self) -> None:
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            ModelPackCatalogueEntry.model_validate(
                _catalogue_payload(release_profile_id="release-profile-1")
            )
        with pytest.raises(ValidationError, match="both be present or both be absent"):
            ModelPackCatalogueEntry.model_validate(
                _catalogue_payload(assurance_profile_content_hash=_HASH)
            )

    def test_catalogue_entry_has_no_execution_or_discovery_surface(self) -> None:
        for forbidden in _FORBIDDEN_FIELDS:
            assert forbidden not in ModelPackCatalogueEntry.model_fields, forbidden
        assert "step" not in ModelPackCatalogueEntry.model_fields
        assert "run" not in ModelPackCatalogueEntry.model_fields
        assert "execute" not in ModelPackCatalogueEntry.model_fields

    def test_catalogue_entry_is_not_executable(self) -> None:
        entry = ModelPackCatalogueEntry.model_validate(_catalogue_payload())
        assert not hasattr(entry, "step")
        assert not callable(getattr(entry, "step", None))


# ---------------------------------------------------------------------------
# DomainPack protocol surface: exact, closed, non-executable seam
# ---------------------------------------------------------------------------


class TestDomainPackProtocolSurface:
    """The DomainPack seam stays exactly as accepted in H29-S02A.

    Proves structurally (source + annotations + runtime surface) that the
    protocol exposes exactly the manifest, the release profile, the frozen
    mechanism protocol version, and the single pure ``step`` operation,
    and that no resolver, dispatcher, registry, factory, loader, or extra
    lifecycle/execution member was added.
    """

    def _protocol_source(self) -> str:
        return inspect.getsource(domain_pack_base.DomainPack)

    def test_exactly_one_protocol_class_named_domain_pack_exists(self) -> None:
        classes = [
            name
            for name, obj in vars(domain_pack_base).items()
            if isinstance(obj, type) and obj.__module__ == domain_pack_base.__name__
        ]
        assert classes == ["DomainPack"]
        assert DomainPack.__name__ == "DomainPack"
        module_tree = ast.parse(Path(domain_pack_base.__file__).read_text(encoding="utf-8"))
        top_level_functions = [
            node.name
            for node in module_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert top_level_functions == []

    def test_package_exports_exactly_domain_pack(self) -> None:
        import kalhas.domain_packs as domain_packs_package

        assert domain_packs_package.__all__ == ["DomainPack"]

    def test_manifest_annotation_is_domain_pack_manifest(self) -> None:
        hints = get_type_hints(DomainPack)
        assert hints["manifest"] is DomainPackManifest

    def test_release_profile_annotation_is_model_pack_release_profile(self) -> None:
        hints = get_type_hints(DomainPack)
        assert hints["release_profile"] is ModelPackReleaseProfile

    def test_mechanism_protocol_version_is_frozen_literal(self) -> None:
        hints = get_type_hints(DomainPack)
        assert get_origin(hints["mechanism_protocol_version"]) is Literal
        assert get_args(hints["mechanism_protocol_version"]) == ("1.0.0",)

    def test_step_is_the_only_protocol_method(self) -> None:
        methods = [
            name
            for name, value in inspect.getmembers(DomainPack, inspect.isfunction)
            if not name.startswith("_")
        ]
        assert methods == ["step"]

    def test_step_accepts_step_request_and_returns_step_result(self) -> None:
        hints = get_type_hints(DomainPack.step)
        assert hints["request"] is DomainMechanismStepRequest
        assert hints["return"] is DomainMechanismStepResult

    def test_manifest_only_legacy_carrier_has_no_step(self) -> None:
        class _LegacyCarrier:
            manifest = DomainPackManifest.model_validate(_manifest_payload())

        carrier = _LegacyCarrier()
        assert not hasattr(carrier, "step")
        assert not callable(getattr(carrier, "step", None))
        # The protocol is intentionally not runtime_checkable: structural
        # conformance cannot be invoked as a silent isinstance promotion.
        with pytest.raises(TypeError):
            isinstance(carrier, cast(type[object], DomainPack))

    def test_no_runtime_checkable_or_machinery_was_added(self) -> None:
        source = self._protocol_source()
        for token in (
            "runtime_checkable",
            "dispatch",
            "resolve",
            "registry",
            "factory",
            "loader",
            "register",
            "discover",
        ):
            assert token not in source, f"forbidden protocol machinery: {token}"

    def test_no_extra_lifecycle_or_execution_member_was_added(self) -> None:
        forbidden_members = (
            "load",
            "save",
            "init",
            "setup",
            "teardown",
            "start",
            "stop",
            "run",
            "execute",
            "call",
            "invoke",
            "bind",
            "commit",
            "rollback",
        )
        declared: set[str] = set()
        for node in ast.walk(ast.parse(self._protocol_source())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                declared.add(node.name)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                declared.add(node.target.id)
        assert declared == {"manifest", "release_profile", "mechanism_protocol_version", "step"}
        for member in forbidden_members:
            assert member not in declared
            assert not hasattr(DomainPack, member)


# ---------------------------------------------------------------------------
# No executable/provider/import/policy/persistence surface anywhere
# ---------------------------------------------------------------------------


class TestPuritySurface:
    _PUBLIC_MODEL_PACK_CONTRACTS = (
        ModelPackReleaseProfile,
        ModelPackAssuranceProfile,
        ModelPackCatalogueEntry,
    )

    def test_public_contracts_express_no_forbidden_field(self) -> None:
        for contract in self._PUBLIC_MODEL_PACK_CONTRACTS:
            for forbidden in _FORBIDDEN_FIELDS:
                assert forbidden not in contract.model_fields, (contract.__name__, forbidden)

    def test_nested_helpers_express_no_forbidden_field(self) -> None:
        for model in _NESTED_MODEL_PACK_MODELS:
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
