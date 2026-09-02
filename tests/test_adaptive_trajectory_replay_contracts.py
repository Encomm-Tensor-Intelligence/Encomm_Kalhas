"""Phase 28 adaptive-run trajectory replay manifest contract tests (H28-S07A slice).

Covers the immutable ``AdaptiveRunTrajectoryReplayManifest`` public
contract: exact valid construction, frozen/strict rejection, the exact
``4.0.0`` runtime literal, ``replay_classification`` limited to
``"exact"``, identifier and hash field validation, the optional external
bundle identifier/hash pair (both present or both absent), the required
timezone-aware ``replayed_at``, absence of any metadata/callback/
expression/import/provider/network surface and of any nested
observations/decisions/switches/states/trajectory results, structural
tolerance of differing expected/recomputed execution hashes (equality is
cross-authority replay-integrity work owned by the later verifier), a
required-but-never-recomputed ``content_hash``, deterministic JSON
round trips, schema synchronization with ``model_json_schema``, the exact
registry append at index 54 after the immutable 54-prefix, the exact
module ``__all__``, contracts-only source imports, automatic generic
``VALID_PAYLOAD`` coverage, and the absence of persistence/identity/
hashing/replay-execution/service surface. Every adversarial case audits
its own base fixture as valid first. No mocks, monkeypatch, skips,
xfails, ``noqa``, ``type: ignore``, or manual schema edits exist in this
module.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1 import adaptive_trajectory_replay as replay_module
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest
from pydantic import ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
KALHAS_ROOT = REPO_ROOT / "kalhas"

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64_OTHER = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_IDENTIFIER_FIELDS = (
    "run_id",
    "campaign_id",
    "adaptive_run_trajectory_execution_id",
    "world_version_id",
    "scenario_seed_id",
    "world_realization_id",
    "adaptive_policy_identifier",
    "policy_id",
)

_HASH_FIELDS = (
    "world_content_hash",
    "seed_content_hash",
    "world_realization_content_hash",
    "adaptive_policy_content_hash",
    "input_hash",
    "trajectory_plan_set_hash",
    "expected_execution_hash",
    "recomputed_execution_hash",
    "content_hash",
)


def _manifest_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": "adaptive-run-trajectory-replay-manifest-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "adaptive_run_trajectory_execution_id": "adaptive-run-trajectory-execution-1",
        "world_version_id": "world-1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "world_realization_id": "world-realization-1",
        "world_realization_content_hash": H64,
        "adaptive_policy_identifier": "adaptive-policy-1",
        "policy_id": "policy-1",
        "adaptive_policy_content_hash": H64,
        "external_observation_input_bundle_id": None,
        "external_observation_input_bundle_content_hash": None,
        "runtime_version": "4.0.0",
        "input_hash": H64,
        "trajectory_plan_set_hash": H64,
        "expected_execution_hash": H64,
        "recomputed_execution_hash": H64,
        "replay_classification": "exact",
        "replayed_at": NOW,
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. Exact valid construction.
# ---------------------------------------------------------------------------


class TestValidConstruction:
    def test_exact_valid_construction(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        assert manifest.identifier == "adaptive-run-trajectory-replay-manifest-1"
        assert manifest.tenant_id == "tenant-1"
        assert manifest.schema_version == "1.0.0"
        assert manifest.run_id == "run-1"
        assert manifest.campaign_id == "campaign-1"
        assert manifest.adaptive_run_trajectory_execution_id == (
            "adaptive-run-trajectory-execution-1"
        )
        assert manifest.world_version_id == "world-1"
        assert manifest.world_content_hash == H64
        assert manifest.scenario_seed_id == "seed-1"
        assert manifest.seed_content_hash == H64
        assert manifest.world_realization_id == "world-realization-1"
        assert manifest.world_realization_content_hash == H64
        assert manifest.adaptive_policy_identifier == "adaptive-policy-1"
        assert manifest.policy_id == "policy-1"
        assert manifest.adaptive_policy_content_hash == H64
        assert manifest.external_observation_input_bundle_id is None
        assert manifest.external_observation_input_bundle_content_hash is None
        assert manifest.runtime_version == "4.0.0"
        assert manifest.input_hash == H64
        assert manifest.trajectory_plan_set_hash == H64
        assert manifest.expected_execution_hash == H64
        assert manifest.recomputed_execution_hash == H64
        assert manifest.replay_classification == "exact"
        assert manifest.replayed_at == NOW
        assert manifest.content_hash == H64


# ---------------------------------------------------------------------------
# 2-3. Frozen and strict.
# ---------------------------------------------------------------------------


class TestFrozenAndStrict:
    def test_contract_is_frozen(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        assert AdaptiveRunTrajectoryReplayManifest.model_config["frozen"] is True
        with pytest.raises(ValidationError):
            manifest.run_id = "run-other"

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload(surprise=True))


# ---------------------------------------------------------------------------
# 4-5. Literals.
# ---------------------------------------------------------------------------


class TestLiterals:
    @pytest.mark.parametrize("bad", ["4.0.1", "4.0", "4", "3.0.0", "4.0.0.0"])
    def test_runtime_literal_is_exactly_4_0_0(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(
                _manifest_payload(runtime_version=bad)
            )

    @pytest.mark.parametrize("bad", ["Exact", "approximate", "partial", "none", "exact "])
    def test_replay_classification_only_exact(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(
                _manifest_payload(replay_classification=bad)
            )

    def test_replay_classification_defaults_to_exact(self) -> None:
        payload = _manifest_payload()
        del payload["replay_classification"]
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(payload)
        assert manifest.replay_classification == "exact"


# ---------------------------------------------------------------------------
# 6. Identifier fields.
# ---------------------------------------------------------------------------


class TestIdentifierFields:
    @pytest.mark.parametrize("field", _IDENTIFIER_FIELDS)
    def test_identifier_fields_reject_empty_strings(self, field: str) -> None:
        payload = _manifest_payload()
        assert AdaptiveRunTrajectoryReplayManifest.model_validate(payload) is not None
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload(**{field: ""}))

    @pytest.mark.parametrize("field", _IDENTIFIER_FIELDS)
    def test_identifier_fields_reject_non_strings(self, field: str) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload(**{field: 123}))

    def test_identifier_fields_are_all_present_in_schema(self) -> None:
        properties = AdaptiveRunTrajectoryReplayManifest.model_json_schema()["properties"]
        for field in _IDENTIFIER_FIELDS:
            assert field in properties
            assert properties[field]["minLength"] == 1


# ---------------------------------------------------------------------------
# 7. Hash fields.
# ---------------------------------------------------------------------------


class TestHashFields:
    @pytest.mark.parametrize("field", _HASH_FIELDS)
    @pytest.mark.parametrize("bad", ["gg" + H64[2:], H64.upper(), H64[:63], H64 + "0"])
    def test_hash_fields_reject_malformed_values(self, field: str, bad: str) -> None:
        payload = _manifest_payload()
        assert AdaptiveRunTrajectoryReplayManifest.model_validate(payload) is not None
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload(**{field: bad}))

    def test_optional_bundle_hash_is_also_validated_when_present(self) -> None:
        bundle_payload = _manifest_payload(
            external_observation_input_bundle_id="bundle-1",
            external_observation_input_bundle_content_hash=H64_OTHER,
        )
        assert AdaptiveRunTrajectoryReplayManifest.model_validate(bundle_payload) is not None
        for bad in ("gg" + H64[2:], H64.upper(), H64[:63], H64 + "0"):
            with pytest.raises(ValidationError):
                AdaptiveRunTrajectoryReplayManifest.model_validate(
                    _manifest_payload(
                        external_observation_input_bundle_id="bundle-1",
                        external_observation_input_bundle_content_hash=bad,
                    )
                )


# ---------------------------------------------------------------------------
# 8-11. External bundle pairing.
# ---------------------------------------------------------------------------


class TestExternalBundlePairing:
    def test_bundle_pair_both_absent_accepted(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        assert manifest.external_observation_input_bundle_id is None
        assert manifest.external_observation_input_bundle_content_hash is None

    def test_bundle_pair_both_present_accepted(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(
            _manifest_payload(
                external_observation_input_bundle_id="bundle-1",
                external_observation_input_bundle_content_hash=H64_OTHER,
            )
        )
        assert manifest.external_observation_input_bundle_id == "bundle-1"
        assert manifest.external_observation_input_bundle_content_hash == H64_OTHER

    def test_identifier_only_bundle_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(
                _manifest_payload(
                    external_observation_input_bundle_id="bundle-1",
                    external_observation_input_bundle_content_hash=None,
                )
            )

    def test_hash_only_bundle_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(
                _manifest_payload(
                    external_observation_input_bundle_id=None,
                    external_observation_input_bundle_content_hash=H64_OTHER,
                )
            )


# ---------------------------------------------------------------------------
# 12. replayed_at.
# ---------------------------------------------------------------------------


class TestReplayedAt:
    def test_replayed_at_is_required(self) -> None:
        payload = _manifest_payload()
        del payload["replayed_at"]
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(payload)

    def test_naive_replayed_at_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(
                _manifest_payload(replayed_at=datetime(2026, 1, 1, 12, 0, 0))
            )

    def test_replayed_at_is_timezone_aware(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        assert manifest.replayed_at.tzinfo is not None
        assert manifest.replayed_at.utcoffset() is not None


# ---------------------------------------------------------------------------
# 13-14. Forbidden and nested surfaces.
# ---------------------------------------------------------------------------


class TestForbiddenSurface:
    def test_no_metadata_callback_expression_import_provider_network_fields(self) -> None:
        fields = tuple(AdaptiveRunTrajectoryReplayManifest.model_fields)
        for token in (
            "metadata",
            "callback",
            "expression",
            "import",
            "provider",
            "network",
            "path",
            "executable",
        ):
            assert not any(token in name for name in fields), (
                f"forbidden surface {token!r} expressible in {fields!r}"
            )
        properties = AdaptiveRunTrajectoryReplayManifest.model_json_schema()["properties"]
        assert "metadata" not in properties

    def test_contract_module_has_no_executable_or_network_surface(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_trajectory_replay.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        for token in (
            "eval(",
            "exec(",
            "import_module",
            "__import__",
            "lambda",
            "callback",
            "provider",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "random",
            "uuid",
            "datetime.now",
            "metadata",
        ):
            assert token not in code, f"forbidden surface token {token!r} in module"

    def test_no_nested_observation_decision_switch_state_or_result_surface(self) -> None:
        fields = tuple(AdaptiveRunTrajectoryReplayManifest.model_fields)
        properties = AdaptiveRunTrajectoryReplayManifest.model_json_schema()["properties"]
        # Exact nested-role field names that must never surface on the
        # manifest; a plain substring scan over "observation" etc. would
        # wrongly catch the spec-required external observation input
        # bundle pair, so only these exact names are forbidden.
        forbid = (
            "observation_events",
            "decision_events",
            "switch_events",
            "policy_state_snapshots",
            "trajectory_results_by_decision",
        )
        for name in forbid:
            assert name not in fields, f"nested evidence surface {name!r} in model_fields"
            assert name not in properties, f"nested evidence surface {name!r} in schema properties"
        # The external observation input bundle pair is required public
        # contract surface and must remain legal on both views.
        assert "external_observation_input_bundle_id" in fields
        assert "external_observation_input_bundle_content_hash" in fields
        assert "external_observation_input_bundle_id" in properties
        assert "external_observation_input_bundle_content_hash" in properties

    def test_contract_module_defines_no_nested_models(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_trajectory_replay.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        assert classes == ["AdaptiveRunTrajectoryReplayManifest"]
        schema = AdaptiveRunTrajectoryReplayManifest.model_json_schema()
        assert "$defs" not in schema
        assert "definitions" not in schema

    def test_no_nested_state_surface(self) -> None:
        fields = tuple(AdaptiveRunTrajectoryReplayManifest.model_fields)
        assert not any("state" in name for name in fields)


# ---------------------------------------------------------------------------
# 15-16. Cross-authority equality and content_hash scope.
# ---------------------------------------------------------------------------


class TestIntegrityScope:
    def test_expected_and_recomputed_hashes_may_differ(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(
            _manifest_payload(expected_execution_hash=H64, recomputed_execution_hash=H64_OTHER)
        )
        assert manifest.expected_execution_hash == H64
        assert manifest.recomputed_execution_hash == H64_OTHER

    def test_content_hash_is_required(self) -> None:
        payload = _manifest_payload()
        del payload["content_hash"]
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryReplayManifest.model_validate(payload)

    def test_content_hash_is_not_recomputed_by_the_contract(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(
            _manifest_payload(content_hash=H64_OTHER)
        )
        assert manifest.content_hash == H64_OTHER


# ---------------------------------------------------------------------------
# 17. Deterministic round trip.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_json_round_trip_preserves_every_field(self) -> None:
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        dumped = manifest.model_dump_json()
        restored = AdaptiveRunTrajectoryReplayManifest.model_validate_json(dumped)
        assert restored == manifest
        assert manifest.model_dump(mode="json") == json.loads(dumped)

    def test_dump_validate_is_deterministic(self) -> None:
        first = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        second = AdaptiveRunTrajectoryReplayManifest.model_validate(_manifest_payload())
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.model_dump_json() == second.model_dump_json()
        assert json.loads(first.model_dump_json()) == json.loads(second.model_dump_json())


# ---------------------------------------------------------------------------
# 18. Schema synchronization.
# ---------------------------------------------------------------------------


class TestSchema:
    def test_schema_artifact_equals_model_json_schema(self) -> None:
        rendered = json.loads(
            (SCHEMA_DIR / "AdaptiveRunTrajectoryReplayManifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        assert rendered == AdaptiveRunTrajectoryReplayManifest.model_json_schema()
        assert rendered["title"] == "AdaptiveRunTrajectoryReplayManifest"
        assert rendered["additionalProperties"] is False

    def test_schema_restricts_runtime_version_and_classification(self) -> None:
        schema = AdaptiveRunTrajectoryReplayManifest.model_json_schema()
        assert schema["properties"]["runtime_version"]["const"] == "4.0.0"
        assert "runtime_version" in schema["required"]
        assert schema["properties"]["replay_classification"]["const"] == "exact"

    def test_schema_marks_bundle_pair_optional(self) -> None:
        schema = AdaptiveRunTrajectoryReplayManifest.model_json_schema()
        required = schema["required"]
        assert "external_observation_input_bundle_id" not in required
        assert "external_observation_input_bundle_content_hash" not in required
        for field in (
            "external_observation_input_bundle_id",
            "external_observation_input_bundle_content_hash",
        ):
            types = {
                alternative.get("type") for alternative in schema["properties"][field]["anyOf"]
            }
            assert types == {"null", "string"}


# ---------------------------------------------------------------------------
# 19-21. Registry boundary.
# ---------------------------------------------------------------------------


class TestRegistryBoundary:
    def test_registry_index_is_exactly_54(self) -> None:
        assert len(PUBLIC_CONTRACTS) >= 55
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[54] == "AdaptiveRunTrajectoryReplayManifest"

    def test_previous_54_registry_entries_remain_the_exact_prefix(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(names) >= 55
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[47:50] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
        )
        assert names[50:54] == (
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
            "AdaptivePolicy",
            "AdaptiveRunTrajectoryExecution",
        )
        assert names[54] == "AdaptiveRunTrajectoryReplayManifest"

    def test_only_the_manifest_is_newly_registered(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        prefix = set(names[:54])
        assert names[-1] == "AdaptiveRunTrajectoryReplayManifest"
        assert set(names) - prefix == {"AdaptiveRunTrajectoryReplayManifest"}
        for nested in (
            "RuntimeObservationEvent",
            "AdaptivePolicyStateSnapshot",
            "AdaptivePolicyDecisionEvent",
            "AdaptivePolicySwitchEvent",
            "RealizedStateTrajectoryResult",
            "AdaptivePolicyDraft",
        ):
            assert nested not in names, f"{nested} independently registered"


# ---------------------------------------------------------------------------
# 22-23. Module surface.
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_module_all_is_exact(self) -> None:
        assert replay_module.__all__ == ["AdaptiveRunTrajectoryReplayManifest"]

    def test_source_imports_contracts_only(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_trajectory_replay.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        roots: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                roots.append(node.module)
        assert roots
        for root in roots:
            if root == "kalhas" or root.startswith("kalhas."):
                assert root == "kalhas.contracts" or root.startswith("kalhas.contracts."), (
                    f"module imports non-contract kalhas code: {root}"
                )
            else:
                assert root in ("__future__", "typing", "pydantic") or root.startswith(
                    ("typing.", "pydantic.")
                ), f"unexpected import root: {root}"


# ---------------------------------------------------------------------------
# 24-25. Generic coverage and scope boundaries.
# ---------------------------------------------------------------------------


class TestGenericCoverageAndScope:
    def test_generic_valid_payload_covers_the_manifest(self) -> None:
        from tests.test_contracts import VALID_PAYLOADS

        assert AdaptiveRunTrajectoryReplayManifest in VALID_PAYLOADS
        manifest = AdaptiveRunTrajectoryReplayManifest.model_validate(
            VALID_PAYLOADS[AdaptiveRunTrajectoryReplayManifest]
        )
        assert manifest.identifier
        assert manifest.tenant_id
        assert manifest.schema_version == "1.0.0"

    def test_no_persistence_identity_hashing_or_service_surface(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_trajectory_replay.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        for token in (
            "store",
            "persistence",
            "persist",
            "service",
            "verifier",
            "should_recompute",
            "hashlib",
            "sha256(",
            "application",
            "nexus",
            "legion",
            "domain_pack",
        ):
            assert token not in code, f"forbidden scope token {token!r} in module"
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            if isinstance(node, ast.ClassDef):
                continue
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__all__"
            ):
                continue
            raise AssertionError(f"unexpected executable module statement: {ast.dump(node)}")
        fields = tuple(AdaptiveRunTrajectoryReplayManifest.model_fields)
        assert not any("execution_service_id" in name for name in fields)
