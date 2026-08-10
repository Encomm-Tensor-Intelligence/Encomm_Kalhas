"""Strict validation tests for the domain pack registry contracts.

The DomainPackManifest is also covered by the parametrized contract tests
in ``test_contracts.py`` (valid payload, unknown fields, schema version,
JSON round-trip). These tests focus on the domain-pack-specific invariants:
semantic pack versions, content hashes, API version 1 support, unique
capability identifiers, immutability, and the descriptive-only boundary.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "contracts" / "v1" / "domain_pack.py"
)


def manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "manifest-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1", "in-2"],
                "output_ids": ["out-1"],
                "metadata": {"declared": True},
            }
        ],
        "schema_metadata": {"declarative": True},
        "content_hash": HASH_64,
        "created_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


class TestPackVersionValidation:
    @pytest.mark.parametrize(
        "bad_version",
        ["1.0", "1", "1.0.0.0", "v1.0.0", "1.0.0-alpha", "1..0", ""],
    )
    def test_rejects_non_semantic_pack_versions(self, bad_version: str) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(pack_version=bad_version))

    def test_accepts_strict_semantic_version(self) -> None:
        manifest = DomainPackManifest.model_validate(manifest_payload(pack_version="0.0.1"))
        assert manifest.pack_version == "0.0.1"


class TestContentHashValidation:
    @pytest.mark.parametrize(
        "bad_hash",
        ["ABC" * 22, "abc" * 21, "z" * 64, "abc" * 21 + "A", HASH_64.upper()],
    )
    def test_rejects_malformed_content_hashes(self, bad_hash: str) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(content_hash=bad_hash[:64]))


class TestStrictness:
    def test_manifest_rejects_unknown_fields(self) -> None:
        payload = manifest_payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(payload)

    def test_capability_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackCapability.model_validate(
                {"identifier": "cap-1", "description": "x", "callback": "run"}
            )

    def test_manifest_rejects_empty_capabilities(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(capabilities=[]))

    def test_manifest_rejects_empty_supported_api_versions(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(supported_api_versions=[]))

    def test_manifest_rejects_non_digit_api_version_entries(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(supported_api_versions=["1.0"]))


class TestInvariants:
    def test_missing_api_version_1_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(manifest_payload(supported_api_versions=["2"]))

    def test_api_version_1_among_others_is_accepted(self) -> None:
        manifest = DomainPackManifest.model_validate(
            manifest_payload(supported_api_versions=["1", "2"])
        )
        assert list(manifest.supported_api_versions) == ["1", "2"]

    def test_duplicate_capability_identifiers_are_rejected(self) -> None:
        capability = {
            "identifier": "cap-1",
            "description": "Declared capability",
            "input_ids": [],
            "output_ids": [],
            "metadata": {},
        }
        with pytest.raises(ValidationError):
            DomainPackManifest.model_validate(
                manifest_payload(capabilities=[capability, capability])
            )

    def test_capability_metadata_rejects_non_json_values(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackCapability.model_validate(
                {"identifier": "cap-1", "description": "x", "metadata": {1: "value"}}
            )

    def test_duplicate_input_ids_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackCapability.model_validate(
                {
                    "identifier": "cap-1",
                    "description": "Declared capability",
                    "input_ids": ["in-1", "in-1"],
                    "output_ids": [],
                }
            )

    def test_duplicate_output_ids_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DomainPackCapability.model_validate(
                {
                    "identifier": "cap-1",
                    "description": "Declared capability",
                    "input_ids": [],
                    "output_ids": ["out-1", "out-1"],
                }
            )

    def test_duplicate_ids_rejected_inside_manifest(self) -> None:
        for field in ("input_ids", "output_ids"):
            capability = {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1", "in-1"] if field == "input_ids" else ["in-1"],
                "output_ids": ["out-1", "out-1"] if field == "output_ids" else ["out-1"],
                "metadata": {},
            }
            with pytest.raises(ValidationError):
                DomainPackManifest.model_validate(manifest_payload(capabilities=[capability]))


class TestImmutabilityAndRoundTrip:
    def test_manifest_is_frozen_by_contract(self) -> None:
        manifest = DomainPackManifest.model_validate(manifest_payload())
        with pytest.raises(ValidationError):
            manifest.name = "tampered"

    def test_capability_is_frozen_by_contract(self) -> None:
        capability = DomainPackCapability(
            identifier="cap-1", description="Declared capability", input_ids=("in-1",)
        )
        with pytest.raises(ValidationError):
            capability.input_ids = ("tampered",)

    def test_json_round_trip_preserves_ordered_inputs_and_outputs(self) -> None:
        manifest = DomainPackManifest.model_validate(manifest_payload())
        reloaded = DomainPackManifest.model_validate_json(manifest.model_dump_json())
        assert reloaded == manifest
        capability = reloaded.capabilities[0]
        assert list(capability.input_ids) == ["in-1", "in-2"]
        assert list(capability.output_ids) == ["out-1"]


class TestDescriptiveOnlyBoundary:
    def test_contract_module_contains_no_executable_code_tokens(self) -> None:
        """Capability metadata is descriptive only: no callbacks, imports,
        executable expressions, provider references, or runtime behavior.

        Field types already make executable content inexpressible; this
        scan is a cheap net for code tokens that would indicate otherwise.
        """
        source = CONTRACT_PATH.read_text(encoding="utf-8")
        forbidden = re.compile(r"\b(exec|eval|lambda|__import__|import_module|Callable|callback)\b")
        offenders = [line.strip() for line in source.splitlines() if forbidden.search(line)]
        assert not offenders, f"executable code tokens found in contract: {offenders}"

    def test_capability_fields_are_declarative_types_only(self) -> None:
        capability = DomainPackCapability(
            identifier="cap-1",
            description="Declared capability",
            input_ids=("in-1",),
            output_ids=("out-1",),
            metadata={"declared": True},
        )
        dumped = capability.model_dump(mode="json")
        assert dumped == {
            "identifier": "cap-1",
            "description": "Declared capability",
            "input_ids": ["in-1"],
            "output_ids": ["out-1"],
            "metadata": {"declared": True},
        }
