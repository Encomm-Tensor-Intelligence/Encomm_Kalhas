"""H29-S03 adversarial tests for the generic pure mechanism dispatcher.

Covers the single composition/dispatch seam of ADR-005 (D29-02) through
generic synthetic fake packs only:

- the happy path returns a fresh detached verified result and the pack's
  ``step`` operation is invoked exactly once;
- repeated dispatch of the same recorded inputs is byte-identical and
  the exact ``int`` versus ``float`` distinction is preserved;
- every rejected precondition fails closed with zero calls (legacy
  manifest-only carriers, missing or non-callable ``step``, wrong exact
  types and subclasses, protocol-version disagreement);
- forged, validator-bypassed, ``model_copy``-mutated, tuple-field
  replaced with a canonically equivalent list, and unserializable-object
  records all fail detached strict revalidation;
- hostile runtime subclasses (of JSON built-ins, structural containers,
  and nested contract records), structurally identical foreign record
  models, and cyclic payloads are rejected on the original object graph
  before serialization can erase their type, with the exact zero/one
  call boundary intact;
- manifest, release-profile, and mechanism-spec hash tampering, every
  copied identity mismatch, state/action/configuration/request hash
  tampering, exogenous value hash tampering, exogenous order that is
  never repaired, and configuration differing from the mechanism spec
  are all rejected with zero calls;
- a pack ``step`` exception is wrapped safely and never retried;
- every postcondition failure (a dict result without coercion, request/
  spec/profile/world/seed/realization/run/step mismatch, wrong
  next-state schema/hash/payload hash, wrong emission/evidence schema
  identity, forged record or result content hashes) fails after exactly
  one call;
- the caller's request remains unchanged under adversarial mutation,
  the returned result shares no mutable container with the pack-owned
  object, and the dispatcher module contains no filesystem, store,
  network, provider, clock, environment, or random-source activity, no
  registry, dynamic discovery, import machinery, or concrete pack, and
  no policy selection, strategy comparison, LEGION/NEXUS call,
  scheduler, retry, persistence, or API behavior;
- the public contract registry remains exactly 61 with the accepted
  Phase 29 tail and every schema artifact remains byte-unchanged.

Only generic synthetic names and data are used. Nothing here loads,
executes, imports, or persists anything.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NoReturn, cast

import pytest
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.domain_pack_registry import build_manifest
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismEmissionRecord,
    MechanismExogenousInput,
)
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile
from kalhas.domain_packs import DomainPack
from pydantic import BaseModel, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER_PATH = REPO_ROOT / "kalhas" / "application" / "domain_mechanism_dispatcher.py"
ERRORS_PATH = REPO_ROOT / "kalhas" / "application" / "domain_mechanism_errors.py"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_HASH_ALT = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _canonical_hash(payload: object) -> str:
    """Canonical SHA-256 of the exact JSON payload value (int != float)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _self_hash(model: BaseModel) -> str:
    """Self-covering canonical hash excluding the model's own content_hash."""
    payload = model.model_dump(mode="json")
    del payload["content_hash"]
    return _canonical_hash(payload)


def _finalize_self_hash(model_type: type[BaseModel], payload: dict[str, object]) -> object:
    """Build a contract whose content hash covers its JSON-mode rendering.

    The hash must be computed over ``model_dump(mode="json")`` exactly as
    the seam computes it, so the model is first validated with a
    placeholder digest, the self hash is computed from the JSON-mode
    dump, and the final digest is revalidated. The hash input excludes
    ``content_hash`` itself, so the provisional validation cannot change
    the digest.
    """
    payload["content_hash"] = "0" * 64
    provisional = model_type.model_validate(payload)
    payload["content_hash"] = _self_hash(provisional)
    return model_type.model_validate(payload)


# ---------------------------------------------------------------------------
# Self-consistent synthetic authority world (exact types, real hashes)
# ---------------------------------------------------------------------------


def _real_manifest() -> DomainPackManifest:
    """A real, hash-consistent synthetic manifest."""
    return build_manifest(
        tenant_id="tenant-1",
        identifier="manifest-1",
        pack_id="pack-1",
        name="Synthetic reference pack",
        pack_version="1.2.3",
        description="Declarative pack metadata only",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
                metadata={"declared": True},
            ),
        ),
        schema_metadata={"declarative": True},
        created_at=NOW,
        metadata={"owner": "foundation"},
    )


def _platform() -> dict[str, object]:
    return {
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


def _mechanism_spec(manifest: DomainPackManifest) -> DomainMechanismSpec:
    """A self-consistent mechanism spec bound to the exact manifest."""
    configuration: dict[str, object] = {"alpha": 1, "beta": "on"}
    payload: dict[str, object] = {
        "identifier": "mechanism-spec-1",
        "tenant_id": manifest.tenant_id,
        "schema_version": "1.0.0",
        "pack_id": manifest.pack_id,
        "pack_version": manifest.pack_version,
        "manifest_id": manifest.identifier,
        "manifest_content_hash": manifest.content_hash,
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
        "evidence_schema_hash": "e" * 64,
        "configuration": configuration,
        "configuration_hash": _canonical_hash(configuration),
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
        "platform_identity": _platform(),
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    spec = cast(DomainMechanismSpec, _finalize_self_hash(DomainMechanismSpec, payload))
    return spec


def _release_profile(
    manifest: DomainPackManifest, spec: DomainMechanismSpec
) -> ModelPackReleaseProfile:
    """A self-consistent release profile embedding the exact manifest/spec."""
    payload: dict[str, object] = {
        "identifier": "release-profile-1",
        "tenant_id": manifest.tenant_id,
        "schema_version": "1.0.0",
        "pack_id": manifest.pack_id,
        "pack_version": manifest.pack_version,
        "manifest_id": manifest.identifier,
        "manifest_content_hash": manifest.content_hash,
        "manifest": manifest.model_dump(mode="json"),
        "mechanism_id": spec.mechanism_id,
        "mechanism_version": spec.mechanism_version,
        "mechanism_protocol_version": spec.mechanism_protocol_version,
        "configuration_identity": spec.configuration_hash,
        "mechanism_spec": spec.model_dump(mode="json"),
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
        "datasets": [],
        "resource_envelope": {
            "max_memory_megabytes": 512,
            "max_cpu_seconds": 60,
            "memory_unit": "MiB",
            "cpu_unit": "seconds",
        },
        "intended_uses": [{"use_id": "use-1", "statement": "Declared synthetic use"}],
        "prohibited_uses": [
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
        ],
        "assumptions": [],
        "limitations": [],
        "content_hash": _HASH,
        "declared_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    profile = cast(ModelPackReleaseProfile, _finalize_self_hash(ModelPackReleaseProfile, payload))
    return profile


class MechanismWorld:
    """One self-consistent synthetic authority world for dispatch tests."""

    def __init__(self) -> None:
        self.manifest = _real_manifest()
        self.spec = _mechanism_spec(self.manifest)
        self.profile = _release_profile(self.manifest, self.spec)
        self.state_payload: dict[str, object] = {"level": 0}
        self.action_payload: dict[str, object] = {"kind": "advance"}
        self.configuration_payload: dict[str, object] = {"alpha": 1, "beta": "on"}
        self.next_state_payload: dict[str, object] = {"level": 1}
        self.emission_payload: dict[str, object] = {"amount": 2.5}
        self.evidence_payload: dict[str, object] = {"observed": True}

    # -- request -----------------------------------------------------------

    def request_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "identifier": "mechanism-step-request-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "mechanism_spec_id": self.spec.identifier,
            "mechanism_spec_content_hash": self.spec.content_hash,
            "release_profile_id": self.profile.identifier,
            "release_profile_content_hash": self.profile.content_hash,
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
            "state_schema_id": self.spec.state_schema_id,
            "action_schema_id": self.spec.action_schema_id,
            "configuration_schema_id": self.spec.configuration_schema_id,
            "state_schema_hash": self.spec.state_schema_hash,
            "action_schema_hash": self.spec.action_schema_hash,
            "configuration_schema_hash": self.spec.configuration_schema_hash,
            "state_payload": dict(self.state_payload),
            "action_payload": dict(self.action_payload),
            "configuration_payload": dict(self.configuration_payload),
            "state_hash": _canonical_hash(self.state_payload),
            "action_hash": _canonical_hash(self.action_payload),
            "configuration_hash": _canonical_hash(self.configuration_payload),
            "exogenous_inputs": [],
            "content_hash": _HASH,
        }
        payload.update(overrides)
        digest = _canonical_hash({k: v for k, v in payload.items() if k != "content_hash"})
        payload["content_hash"] = digest
        return payload

    def request(self, **overrides: object) -> DomainMechanismStepRequest:
        return DomainMechanismStepRequest.model_validate(self.request_payload(**overrides))

    # -- exogenous ---------------------------------------------------------

    def exogenous_entries(self) -> list[dict[str, object]]:
        """Two canonically ordered entries with exact value hashes."""
        identity = {
            "world_version_id": "world-v1",
            "world_content_hash": _HASH,
            "seed_id": "seed-1",
            "seed_content_hash": _HASH,
            "realization_id": None,
            "realization_content_hash": None,
            "run_id": "run-1",
            "step_index": 0,
        }
        first: dict[str, object] = {
            "identifier": "exogenous-1",
            "stream": "stream-1",
            "variable": "variable-1",
            "entity_id": "entity-1",
            "slot_id": None,
            "draw_index": 0,
            "value_kind": "number",
            "value": 1.5,
            "unit": "units",
            "content_hash": _canonical_hash(1.5),
        }
        second: dict[str, object] = {
            "identifier": "exogenous-2",
            "stream": "stream-2",
            "variable": "variable-1",
            "entity_id": "entity-9",
            "slot_id": None,
            "draw_index": 0,
            "value_kind": "integer",
            "value": 7,
            "unit": None,
            "content_hash": _canonical_hash(7),
        }
        first.update(identity)
        second.update(identity)
        return [first, second]

    # -- result ------------------------------------------------------------

    def result_payload(self, request_payload: dict[str, object]) -> dict[str, object]:
        emission: dict[str, object] = {
            "identifier": "emission-1",
            "sequence_position": 0,
            "emission_schema_id": self.spec.emission_schema_id,
            "emission_schema_hash": self.spec.emission_schema_hash,
            "content_hash": _HASH,
            "payload": dict(self.emission_payload),
            "unit": "units",
        }
        emission["content_hash"] = _canonical_hash(
            {k: v for k, v in emission.items() if k != "content_hash"}
        )
        evidence: dict[str, object] = {
            "identifier": "evidence-1",
            "sequence_position": 0,
            "evidence_schema_id": self.spec.evidence_schema_id,
            "evidence_schema_hash": self.spec.evidence_schema_hash,
            "content_hash": _HASH,
            "payload": dict(self.evidence_payload),
        }
        evidence["content_hash"] = _canonical_hash(
            {k: v for k, v in evidence.items() if k != "content_hash"}
        )
        payload: dict[str, object] = {
            "identifier": "mechanism-step-result-1",
            "tenant_id": request_payload["tenant_id"],
            "schema_version": "1.0.0",
            "request_id": request_payload["identifier"],
            "request_content_hash": request_payload["content_hash"],
            "mechanism_spec_id": self.spec.identifier,
            "mechanism_spec_content_hash": self.spec.content_hash,
            "release_profile_id": self.profile.identifier,
            "release_profile_content_hash": self.profile.content_hash,
            "world_version_id": request_payload["world_version_id"],
            "world_content_hash": request_payload["world_content_hash"],
            "seed_id": request_payload["seed_id"],
            "seed_content_hash": request_payload["seed_content_hash"],
            "realization_id": request_payload["realization_id"],
            "realization_content_hash": request_payload["realization_content_hash"],
            "run_id": request_payload["run_id"],
            "step_index": request_payload["step_index"],
            "next_state_schema_id": self.spec.state_schema_id,
            "next_state_schema_hash": self.spec.state_schema_hash,
            "next_state_payload": dict(self.next_state_payload),
            "next_state_hash": _canonical_hash(self.next_state_payload),
            "emissions": [emission],
            "evidence": [evidence],
            "content_hash": _HASH,
        }
        digest = _canonical_hash({k: v for k, v in payload.items() if k != "content_hash"})
        payload["content_hash"] = digest
        return payload

    def result_for(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        return DomainMechanismStepResult.model_validate(
            self.result_payload(request.model_dump(mode="json"))
        )


# ---------------------------------------------------------------------------
# Generic synthetic fake packs (test-only, below the kernel)
# ---------------------------------------------------------------------------


class RecordingPack:
    """Conforming fake pack: records calls, serves a fresh valid result."""

    def __init__(self, world: MechanismWorld) -> None:
        self.world = world
        self.manifest = world.manifest
        self.release_profile = world.profile
        # The valid fake pack declares the protocol version with the
        # protocol's exact ``Literal["1.0.0"]`` type so it statically
        # satisfies ``DomainPack``. Adversarial values are injected on
        # instances through ``object.__setattr__`` and never widen this
        # declared type.
        self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"
        self.calls = 0
        self.seen_requests: list[DomainMechanismStepRequest] = []
        self.step_exception: Exception | None = None
        self.mutator: Callable[[DomainMechanismStepRequest], None] | None = None
        self.static_result: DomainMechanismStepResult | None = None
        self.result_override: object | None = None
        self.response_request_payload = world.request_payload()

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        self.seen_requests.append(request)
        if self.mutator is not None:
            self.mutator(request)
        if self.step_exception is not None:
            raise self.step_exception
        if self.result_override is not None:
            return cast(DomainMechanismStepResult, self.result_override)
        if self.static_result is not None:
            return self.static_result
        return DomainMechanismStepResult.model_validate(
            self.world.result_payload(self.response_request_payload)
        )


class LegacyManifestOnlyCarrier:
    """A legacy inert carrier: manifest only, no executable identity."""

    def __init__(self, manifest: DomainPackManifest) -> None:
        self.manifest = manifest


class MissingStepPack:
    """Carrier with executable identity fields but no ``step`` operation."""

    def __init__(self, world: MechanismWorld) -> None:
        self.manifest = world.manifest
        self.release_profile = world.profile
        self.mechanism_protocol_version = "1.0.0"


class NonCallableStepPack(MissingStepPack):
    """Carrier whose ``step`` attribute is present but not callable."""

    def __init__(self, world: MechanismWorld) -> None:
        super().__init__(world)
        self.step = "not-callable"


class HostileAttributePack:
    """A pack whose attribute access itself fails closed."""

    def __init__(self, world: MechanismWorld) -> None:
        self._world = world
        self.calls = 0

    @property
    def manifest(self) -> DomainPackManifest:
        raise RuntimeError("hostile attribute access")

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        return DomainMechanismStepResult.model_validate(
            self._world.result_payload(self._world.request_payload())
        )


class ForeignWorldPack:
    """A conforming pack of a different (self-consistent) release world.

    Its ``step`` is a tripwire: a zero-call rejection must never reach it.
    """

    def __init__(self, world: MechanismWorld, description: str) -> None:
        manifest = build_manifest(
            tenant_id=world.manifest.tenant_id,
            identifier=world.manifest.identifier,
            pack_id=world.manifest.pack_id,
            name=world.manifest.name,
            pack_version=world.manifest.pack_version,
            description=description,
            supported_api_versions=world.manifest.supported_api_versions,
            capabilities=world.manifest.capabilities,
            schema_metadata=dict(world.manifest.schema_metadata),
            created_at=world.manifest.created_at,
            metadata=dict(world.manifest.metadata),
        )
        self.manifest = manifest
        self.release_profile = _release_profile(manifest, _mechanism_spec(manifest))
        self.mechanism_protocol_version = "1.0.0"
        self.calls = 0

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        raise AssertionError("step must never be reached by a rejected dispatch")


def _valid_pack(world: MechanismWorld) -> RecordingPack:
    return RecordingPack(world)


def _rejects_zero_calls(
    pack: object,
    request: object,
    *,
    expected_reason: str | None = None,
) -> None:
    """Dispatch must fail closed with the typed error and zero step calls."""
    calls_before = getattr(pack, "calls", 0)
    pack_arg = cast(DomainPack, pack)
    request_arg = cast(DomainMechanismStepRequest, request)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack_arg, request_arg)
    assert isinstance(excinfo.value, DomainMechanismDispatchError)
    if expected_reason is not None:
        assert excinfo.value.reason == expected_reason
    assert getattr(pack, "calls", calls_before) == calls_before


def _rejects_after_exactly_one_call(
    pack: RecordingPack,
    request: DomainMechanismStepRequest,
    *,
    expected_reason: str | None = None,
) -> None:
    """A postcondition failure must raise the typed error after one call."""
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert isinstance(excinfo.value, DomainMechanismDispatchError)
    if expected_reason is not None:
        assert excinfo.value.reason == expected_reason
    assert pack.calls == 1


# ---------------------------------------------------------------------------
# Section A: happy path, determinism, exactly-once, isolation
# ---------------------------------------------------------------------------


def _fresh_world_and_pack() -> tuple[MechanismWorld, RecordingPack]:
    world = MechanismWorld()
    return world, RecordingPack(world)


def test_happy_path_returns_valid_detached_result() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = dispatch_domain_mechanism_step(pack, request)
    assert type(result) is DomainMechanismStepResult
    assert pack.calls == 1
    assert result.request_id == request.identifier
    assert _self_hash(result) == result.content_hash


def test_repeated_dispatch_is_byte_identical() -> None:
    world, pack = _fresh_world_and_pack()
    payload = world.request_payload()
    first = dispatch_domain_mechanism_step(pack, DomainMechanismStepRequest.model_validate(payload))
    second = dispatch_domain_mechanism_step(
        pack, DomainMechanismStepRequest.model_validate(payload)
    )
    assert pack.calls == 2
    first_dump = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    second_dump = json.dumps(second.model_dump(mode="json"), sort_keys=True)
    assert first_dump == second_dump
    assert first.model_dump_json() == second.model_dump_json()
    assert first.content_hash == second.content_hash


def test_exact_int_float_distinction_is_hashed_distinctly() -> None:
    world = MechanismWorld()
    int_payload = world.request_payload()
    float_payload = world.request_payload()
    float_payload["state_payload"] = {"level": 0.0}
    float_payload["state_hash"] = _canonical_hash({"level": 0.0})
    assert int_payload["state_hash"] != float_payload["state_hash"]
    int_request = DomainMechanismStepRequest.model_validate(int_payload)
    float_request = DomainMechanismStepRequest.model_validate(float_payload)
    assert int_request.state_hash != float_request.state_hash
    assert json.dumps(
        int_request.model_dump(mode="json")["state_payload"], sort_keys=True
    ) != json.dumps(float_request.model_dump(mode="json")["state_payload"], sort_keys=True)


def test_step_called_exactly_once_on_success() -> None:
    world, pack = _fresh_world_and_pack()
    dispatch_domain_mechanism_step(pack, world.request())
    assert pack.calls == 1
    assert len(pack.seen_requests) == 1


def test_pack_receives_detached_deep_copy_and_caller_request_unchanged() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    payload_before = json.dumps(request.model_dump(mode="json"), sort_keys=True)

    def mutate(seen: DomainMechanismStepRequest) -> None:
        object.__setattr__(seen, "run_id", "forged-by-pack")

    pack.mutator = mutate
    result = dispatch_domain_mechanism_step(pack, request)
    assert result.request_id == "mechanism-step-request-1"
    assert request.run_id == "run-1"
    assert pack.seen_requests[0].state_payload is not request.state_payload
    assert json.dumps(request.model_dump(mode="json"), sort_keys=True) == payload_before


def test_adversarial_mutation_of_nested_containers_leaves_original_unchanged() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    payload_before = json.dumps(request.model_dump(mode="json"), sort_keys=True)
    pack.static_result = world.result_for(request)

    def mutate(seen: DomainMechanismStepRequest) -> None:
        seen.state_payload["level"] = 999
        seen.action_payload.clear()

    pack.mutator = mutate
    dispatch_domain_mechanism_step(pack, request)
    assert json.dumps(request.model_dump(mode="json"), sort_keys=True) == payload_before


def test_returned_result_shares_no_mutable_container_with_pack_object() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = dispatch_domain_mechanism_step(pack, request)
    assert pack.seen_requests[0] is not request
    owned = pack.static_result
    assert owned is None
    pack.static_result = result
    returned_again = dispatch_domain_mechanism_step(pack, request)
    assert returned_again is not pack.static_result
    assert returned_again.next_state_payload is not pack.static_result.next_state_payload
    assert returned_again.emissions == pack.static_result.emissions
    assert returned_again.emissions[0].payload is not pack.static_result.emissions[0].payload


# ---------------------------------------------------------------------------
# Section B: pre-dispatch surface checks (zero calls)
# ---------------------------------------------------------------------------


def test_legacy_manifest_only_carrier_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    carrier = LegacyManifestOnlyCarrier(world.manifest)
    _rejects_zero_calls(
        carrier, world.request(), expected_reason="legacy_manifest_only_or_incomplete_pack"
    )


def test_missing_step_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    _rejects_zero_calls(
        MissingStepPack(world),
        world.request(),
        expected_reason="legacy_manifest_only_or_incomplete_pack",
    )


def test_non_callable_step_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    _rejects_zero_calls(
        NonCallableStepPack(world), world.request(), expected_reason="step_not_callable"
    )


def test_hostile_attribute_access_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    _rejects_zero_calls(
        HostileAttributePack(world), world.request(), expected_reason="pack_attribute_access"
    )


def test_wrong_exact_request_type_rejected() -> None:
    world, pack = _fresh_world_and_pack()
    _rejects_zero_calls(pack, {"identifier": "not-a-request"}, expected_reason="request_type")


def test_request_subclass_rejected() -> None:
    world, pack = _fresh_world_and_pack()

    class RequestSubclass(DomainMechanismStepRequest):
        pass

    subclassed = RequestSubclass.model_validate(world.request_payload())
    _rejects_zero_calls(pack, subclassed, expected_reason="request_type")


def test_manifest_subclass_rejected() -> None:
    world = MechanismWorld()

    class ManifestSubclass(DomainPackManifest):
        pass

    pack = RecordingPack(world)
    pack.manifest = ManifestSubclass.model_validate(world.manifest.model_dump(mode="json"))
    _rejects_zero_calls(pack, world.request(), expected_reason="manifest_type")


def test_release_profile_subclass_rejected() -> None:
    world = MechanismWorld()

    class ProfileSubclass(ModelPackReleaseProfile):
        pass

    pack = RecordingPack(world)
    pack.release_profile = ProfileSubclass.model_validate(world.profile.model_dump(mode="json"))
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_type")


def test_wrong_protocol_version_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    pack = RecordingPack(world)
    # Every invalid protocol value is an adversarial injection through
    # the explicit boundary; the declared Literal type of the valid
    # fake pack is never widened to accommodate any of them.
    object.__setattr__(pack, "mechanism_protocol_version", "2.0.0")
    _rejects_zero_calls(pack, world.request(), expected_reason="mechanism_protocol_version")
    object.__setattr__(pack, "mechanism_protocol_version", "1.0.0 ")
    _rejects_zero_calls(pack, world.request(), expected_reason="mechanism_protocol_version")
    object.__setattr__(pack, "mechanism_protocol_version", 1.0)
    _rejects_zero_calls(pack, world.request(), expected_reason="mechanism_protocol_version")


# ---------------------------------------------------------------------------
# Section C: forged and mutated records (detached revalidation, zero calls)
# ---------------------------------------------------------------------------


def test_forged_request_bypassing_validators_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    forged = world.request()
    object.__setattr__(forged, "step_index", -5)
    _rejects_zero_calls(pack, forged, expected_reason="request_revalidation")


def test_forged_manifest_bypassing_validators_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    forged_manifest = world.manifest.model_copy(update={"pack_version": "not-semver"})
    pack = RecordingPack(world)
    pack.manifest = forged_manifest
    _rejects_zero_calls(pack, world.request(), expected_reason="manifest_revalidation")


def test_forged_release_profile_bypassing_validators_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    forged_profile = world.profile.model_copy(update={"pack_version": "9.9.9"})
    pack = RecordingPack(world)
    pack.release_profile = forged_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_revalidation")


def test_shallow_mutated_request_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    mutated = world.request()
    object.__setattr__(mutated, "tenant_id", "tenant-2")
    _rejects_zero_calls(pack, mutated, expected_reason="request_tenant_agreement")


# ---------------------------------------------------------------------------
# Section D: manifest/profile/spec authority and hash tampering (zero calls)
# ---------------------------------------------------------------------------


def test_manifest_hash_tampering_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    forged_manifest = world.manifest.model_copy(update={"content_hash": _HASH_ALT})
    pack = RecordingPack(world)
    pack.manifest = forged_manifest
    _rejects_zero_calls(pack, world.request(), expected_reason="manifest_content_hash")


def test_release_profile_hash_tampering_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    forged_profile = world.profile.model_copy(update={"content_hash": _HASH_ALT})
    pack = RecordingPack(world)
    pack.release_profile = forged_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_content_hash")


def test_mechanism_spec_hash_tampering_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    spec_payload = world.spec.model_dump(mode="json")
    spec_payload["content_hash"] = _HASH_ALT
    forged_spec = DomainMechanismSpec.model_validate(spec_payload)
    profile_payload = world.profile.model_dump(mode="json")
    profile_payload["mechanism_spec"] = forged_spec.model_dump(mode="json")
    profile_payload["content_hash"] = _canonical_hash(
        {k: v for k, v in profile_payload.items() if k != "content_hash"}
    )
    forged_profile = ModelPackReleaseProfile.model_validate(profile_payload)
    pack = RecordingPack(world)
    pack.release_profile = forged_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="mechanism_spec_content_hash")


def test_release_profile_manifest_embedding_mismatch_rejected_with_zero_calls() -> None:
    """A hash-consistent profile around different manifest content fails."""
    world = MechanismWorld()
    tampered_manifest = build_manifest(
        tenant_id=world.manifest.tenant_id,
        identifier=world.manifest.identifier,
        pack_id=world.manifest.pack_id,
        name=world.manifest.name,
        pack_version=world.manifest.pack_version,
        description="Tampered declarative pack metadata",
        supported_api_versions=world.manifest.supported_api_versions,
        capabilities=world.manifest.capabilities,
        schema_metadata=dict(world.manifest.schema_metadata),
        created_at=world.manifest.created_at,
        metadata=dict(world.manifest.metadata),
    )
    assert tampered_manifest.content_hash != world.manifest.content_hash
    other_profile = _release_profile(tampered_manifest, _mechanism_spec(tampered_manifest))
    pack = RecordingPack(world)
    pack.manifest = world.manifest
    pack.release_profile = other_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_manifest_embedding")


def test_foreign_world_pack_rejected_at_request_spec_reference() -> None:
    """A self-consistent pack of another release fails at the spec reference."""
    world = MechanismWorld()
    foreign = ForeignWorldPack(world, description="A different synthetic release")
    assert foreign.manifest.content_hash != world.manifest.content_hash
    _rejects_zero_calls(
        foreign, world.request(), expected_reason="request_mechanism_spec_reference"
    )
    assert foreign.calls == 0


def test_configuration_hash_tampering_in_spec_rejected_with_zero_calls() -> None:
    world = MechanismWorld()
    spec_payload = world.spec.model_dump(mode="json")
    spec_payload["configuration_hash"] = _HASH_ALT
    spec_payload["content_hash"] = _canonical_hash(
        {k: v for k, v in spec_payload.items() if k != "content_hash"}
    )
    forged_spec = DomainMechanismSpec.model_validate(spec_payload)
    profile_payload = world.profile.model_dump(mode="json")
    profile_payload["mechanism_spec"] = forged_spec.model_dump(mode="json")
    profile_payload["configuration_identity"] = _HASH_ALT
    profile_payload["content_hash"] = _canonical_hash(
        {k: v for k, v in profile_payload.items() if k != "content_hash"}
    )
    forged_profile = ModelPackReleaseProfile.model_validate(profile_payload)
    pack = RecordingPack(world)
    pack.release_profile = forged_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="mechanism_spec_configuration_hash")


def test_pack_with_mismatched_profile_and_request_rejected_at_request_reference() -> None:
    """A pack of another release is rejected at the request reference check."""
    world = MechanismWorld()
    other = MechanismWorld()
    other_profile_payload = other.profile.model_dump(mode="json")
    other_profile_payload["identifier"] = "release-profile-other"
    other_profile = cast(
        ModelPackReleaseProfile,
        _finalize_self_hash(ModelPackReleaseProfile, other_profile_payload),
    )
    pack = RecordingPack(world)
    pack.release_profile = other_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="request_release_profile_reference")


# ---------------------------------------------------------------------------
# Section E: request authority (zero calls)
# ---------------------------------------------------------------------------


def test_state_hash_tampering_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    request_payload = world.request_payload()
    request_payload["state_payload"] = {"level": 1}
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(request_payload),
        expected_reason="request_state_hash",
    )


def test_action_hash_tampering_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    request_payload = world.request_payload()
    request_payload["action_payload"] = {"kind": "retreat"}
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(request_payload),
        expected_reason="request_action_hash",
    )


def test_configuration_payload_hash_tampering_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    request_payload = world.request_payload()
    request_payload["configuration_payload"] = {"alpha": 2, "beta": "on"}
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(request_payload),
        expected_reason="request_configuration_payload_hash",
    )


def test_request_hash_tampering_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    request_payload = world.request_payload()
    request_payload["content_hash"] = _HASH_ALT
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(request_payload),
        expected_reason="request_content_hash",
    )


def test_exogenous_value_hash_tampering_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    entries = world.exogenous_entries()
    entries[0]["value"] = 9.75
    payload = world.request_payload(exogenous_inputs=entries)
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(payload),
        expected_reason="request_exogenous_value_hash",
    )


def test_exogenous_order_is_never_repaired() -> None:
    world, pack = _fresh_world_and_pack()
    entries = world.exogenous_entries()
    payload = world.request_payload(exogenous_inputs=[entries[1], entries[0]])
    with pytest.raises(ValidationError):
        DomainMechanismStepRequest.model_validate(payload)
    assert pack.calls == 0


def test_configuration_differing_from_spec_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    payload = world.request_payload()
    payload["configuration_payload"] = {"alpha": 1}
    payload["configuration_hash"] = _canonical_hash({"alpha": 1})
    _rejects_zero_calls(
        pack,
        DomainMechanismStepRequest.model_validate(payload),
        expected_reason="request_configuration_differs_from_spec",
    )


def test_every_copied_identity_mismatch_is_rejected_with_zero_calls() -> None:
    world, pack = _fresh_world_and_pack()
    base = world.request_payload()
    mismatches: dict[str, object] = {
        "mechanism_spec_id": "mechanism-spec-other",
        "mechanism_spec_content_hash": _HASH_ALT,
        "release_profile_id": "release-profile-other",
        "release_profile_content_hash": _HASH_ALT,
        "state_schema_id": "state-schema-other",
        "action_schema_id": "action-schema-other",
        "configuration_schema_id": "configuration-schema-other",
        "state_schema_hash": _HASH_ALT,
        "action_schema_hash": _HASH_ALT,
        "configuration_schema_hash": _HASH_ALT,
        "tenant_id": "tenant-2",
    }
    reasons: dict[str, str] = {
        "mechanism_spec_id": "request_mechanism_spec_reference",
        "mechanism_spec_content_hash": "request_mechanism_spec_reference",
        "release_profile_id": "request_release_profile_reference",
        "release_profile_content_hash": "request_release_profile_reference",
        "state_schema_id": "request_state_schema_identity",
        "action_schema_id": "request_action_schema_identity",
        "configuration_schema_id": "request_configuration_schema_identity",
        "state_schema_hash": "request_state_schema_identity",
        "action_schema_hash": "request_action_schema_identity",
        "configuration_schema_hash": "request_configuration_schema_identity",
        "tenant_id": "request_tenant_agreement",
    }
    for field, wrong_value in mismatches.items():
        payload = dict(base)
        payload[field] = wrong_value
        _rejects_zero_calls(
            pack,
            DomainMechanismStepRequest.model_validate(payload),
            expected_reason=reasons[field],
        )
    assert pack.calls == 0


# ---------------------------------------------------------------------------
# Section F: exactly-once invocation, pack failure, never retried
# ---------------------------------------------------------------------------


def test_pack_step_exception_wrapped_and_never_retried() -> None:
    world, pack = _fresh_world_and_pack()
    pack.step_exception = RuntimeError("pack internal state")
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, world.request())
    assert excinfo.value.reason == "pack_step_raised"
    assert excinfo.value.__cause__ is pack.step_exception
    assert "pack internal state" not in str(excinfo.value)
    assert pack.calls == 1


def test_generic_public_message_is_stable_and_safe() -> None:
    world = MechanismWorld()
    carrier = LegacyManifestOnlyCarrier(world.manifest)
    # The legacy carrier is intentionally not a DomainPack; the narrow
    # explicit cast is the adversarial boundary at this direct call,
    # mirroring the hostile caller the dispatcher must reject.
    with pytest.raises(DomainMechanismDispatchError) as pre:
        dispatch_domain_mechanism_step(cast(DomainPack, carrier), world.request())
    pack = RecordingPack(world)
    pack.step_exception = RuntimeError("pack secret internals")
    with pytest.raises(DomainMechanismDispatchError) as mid:
        dispatch_domain_mechanism_step(pack, world.request())
    result_pack = RecordingPack(world)
    result_pack.result_override = {"not": "a result"}
    with pytest.raises(DomainMechanismDispatchError) as post:
        dispatch_domain_mechanism_step(result_pack, world.request())
    messages = {str(pre.value), str(mid.value), str(post.value)}
    assert len(messages) == 1
    (message,) = messages
    assert "pack secret internals" not in message
    for secret in (_HASH, _HASH_ALT, "tenant-2", "tenant-1"):
        assert secret not in message
    assert pre.value.request_id is None
    assert mid.value.request_id == "mechanism-step-request-1"


# ---------------------------------------------------------------------------
# Section G: post-dispatch verification (exactly one call)
# ---------------------------------------------------------------------------


def test_dict_result_rejected_without_coercion_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    pack.result_override = world.result_payload(world.request_payload())
    _rejects_after_exactly_one_call(pack, world.request(), expected_reason="result_type")


def test_result_subclass_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()

    class ResultSubclass(DomainMechanismStepResult):
        pass

    pack.result_override = ResultSubclass.model_validate(
        world.result_payload(world.request_payload())
    )
    _rejects_after_exactly_one_call(pack, world.request(), expected_reason="result_type")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("request_id", "mechanism-step-request-other", "result_request_reference"),
        ("request_content_hash", _HASH_ALT, "result_request_reference"),
        ("mechanism_spec_id", "mechanism-spec-other", "result_mechanism_spec_reference"),
        ("mechanism_spec_content_hash", _HASH_ALT, "result_mechanism_spec_reference"),
        ("release_profile_id", "release-profile-other", "result_release_profile_reference"),
        ("release_profile_content_hash", _HASH_ALT, "result_release_profile_reference"),
        ("world_version_id", "world-other", "result_world_seed_identity"),
        ("world_content_hash", _HASH_ALT, "result_world_seed_identity"),
        ("seed_id", "seed-other", "result_world_seed_identity"),
        ("seed_content_hash", _HASH_ALT, "result_world_seed_identity"),
        ("run_id", "run-other", "result_run_step_identity"),
        ("step_index", 7, "result_run_step_identity"),
    ],
)
def test_result_identity_mismatch_rejected_after_one_call(
    field: str, value: object, reason: str
) -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload[field] = value
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(pack, request, expected_reason=reason)


def test_result_realization_mismatch_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request(realization_id="realization-1", realization_content_hash=_HASH)
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["realization_id"] = None
    result_payload["realization_content_hash"] = None
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_realization_identity")
    request_payload = request.model_dump(mode="json")
    request_payload["realization_id"] = "realization-other"
    request_payload["realization_content_hash"] = _HASH_ALT
    request_payload["content_hash"] = _canonical_hash(
        {k: v for k, v in request_payload.items() if k != "content_hash"}
    )
    request_other = DomainMechanismStepRequest.model_validate(request_payload)
    result_payload_other = world.result_payload(request_other.model_dump(mode="json"))
    result_payload_other["realization_id"] = "realization-1"
    pack2 = RecordingPack(world)
    pack2.result_override = DomainMechanismStepResult.model_validate(result_payload_other)
    _rejects_after_exactly_one_call(
        pack2, request_other, expected_reason="result_realization_identity"
    )


def test_wrong_next_state_schema_identity_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["next_state_schema_id"] = "state-schema-other"
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(
        pack, request, expected_reason="result_next_state_schema_identity"
    )


def test_wrong_next_state_hash_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["next_state_hash"] = _HASH_ALT
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_next_state_hash")


def test_wrong_next_state_payload_hash_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["next_state_payload"] = {"level": 42}
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_next_state_hash")


_RECORD_SINGULAR = {"emissions": "emission", "evidence": "evidence"}


@pytest.mark.parametrize("collection", ["emissions", "evidence"])
def test_wrong_record_schema_identity_rejected_after_one_call(collection: str) -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    records = cast("list[dict[str, object]]", result_payload[collection])
    schema_field = f"{_RECORD_SINGULAR[collection]}_schema_id"
    record = dict(records[0])
    record[schema_field] = "schema-other"
    result_payload[collection] = [record]
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(
        pack, request, expected_reason=f"result_{_RECORD_SINGULAR[collection]}_schema_identity"
    )


@pytest.mark.parametrize("collection", ["emissions", "evidence"])
def test_forged_record_content_hash_rejected_after_one_call(collection: str) -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    records = cast("list[dict[str, object]]", result_payload[collection])
    record = dict(records[0])
    record["content_hash"] = _HASH_ALT
    result_payload[collection] = [record]
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(
        pack, request, expected_reason=f"result_{_RECORD_SINGULAR[collection]}_content_hash"
    )


def test_forged_result_content_hash_rejected_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["content_hash"] = _HASH_ALT
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_content_hash")


def test_reordered_record_positions_rejected_after_one_call() -> None:
    """A non-contiguous forged result fails closed after exactly one call.

    The result contract itself rejects non-contiguous positions during
    validation, so the forged object is assembled with validators
    bypassed (``model_construct``) exactly as a hostile pack would; the
    dispatcher's detached strict revalidation is the gate that rejects
    it, still after exactly one step call and with no partial result.
    """
    from kalhas.contracts.v1.domain_mechanism import MechanismEmissionRecord

    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    records = cast("list[dict[str, object]]", result_payload["emissions"])
    first = MechanismEmissionRecord.model_validate(records[0])
    validated = DomainMechanismStepResult.model_validate(result_payload)
    fields = dict(validated.__dict__)
    fields.pop("__pydantic_extra__", None)
    fields.pop("__pydantic_private__", None)
    fields["emissions"] = (first.model_copy(update={"sequence_position": 1}),)
    forged = DomainMechanismStepResult.model_construct(**fields)
    pack.result_override = forged
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_revalidation")


def test_empty_emissions_and_evidence_are_accepted_after_one_call() -> None:
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result_payload = world.result_payload(request.model_dump(mode="json"))
    result_payload["emissions"] = []
    result_payload["evidence"] = []
    result_payload["content_hash"] = _canonical_hash(
        {k: v for k, v in result_payload.items() if k != "content_hash"}
    )
    pack.result_override = DomainMechanismStepResult.model_validate(result_payload)
    result = dispatch_domain_mechanism_step(pack, request)
    assert pack.calls == 1
    assert result.emissions == ()
    assert result.evidence == ()


# ---------------------------------------------------------------------------
# Section G+: validator-bypassed tuple-to-list shapes and unserializable
# objects (detached strict revalidation; canonical equivalents never
# normalized)
# ---------------------------------------------------------------------------


def test_manifest_tuple_field_replaced_with_list_is_rejected_with_zero_calls() -> None:
    """A list in place of ``supported_api_versions`` fails strict revalidation.

    The replacement carries canonically equivalent JSON content; only the
    Python representation (list instead of tuple) is wrong, and the
    dispatcher must reject it instead of silently normalizing it.
    """
    world = MechanismWorld()
    forged_manifest = world.manifest.model_copy(deep=True)
    object.__setattr__(
        forged_manifest,
        "supported_api_versions",
        list(forged_manifest.supported_api_versions),
    )
    assert list(forged_manifest.supported_api_versions) == list(
        world.manifest.supported_api_versions
    )
    pack = RecordingPack(world)
    pack.manifest = forged_manifest
    _rejects_zero_calls(pack, world.request(), expected_reason="manifest_revalidation")


def test_release_profile_tuple_field_replaced_with_list_is_rejected_with_zero_calls() -> None:
    """A list in place of ``intended_uses`` fails strict revalidation."""
    world = MechanismWorld()
    forged_profile = world.profile.model_copy(deep=True)
    object.__setattr__(
        forged_profile,
        "intended_uses",
        [use.model_dump(mode="json") for use in forged_profile.intended_uses],
    )
    pack = RecordingPack(world)
    pack.release_profile = forged_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_revalidation")


def test_request_tuple_field_replaced_with_list_is_rejected_with_zero_calls() -> None:
    """A list in place of ``exogenous_inputs`` fails strict revalidation."""
    world, pack = _fresh_world_and_pack()
    request = world.request(exogenous_inputs=world.exogenous_entries())
    object.__setattr__(
        request,
        "exogenous_inputs",
        [entry.model_dump(mode="json") for entry in request.exogenous_inputs],
    )
    _rejects_zero_calls(pack, request, expected_reason="request_revalidation")


def test_result_tuple_field_replaced_with_list_is_rejected_after_one_call() -> None:
    """A list in place of ``emissions`` fails strict revalidation post-step."""
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    object.__setattr__(
        result,
        "emissions",
        [record.model_dump(mode="json") for record in result.emissions],
    )
    pack.result_override = result
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_revalidation")


def test_unserializable_request_payload_object_is_wrapped_with_zero_calls() -> None:
    """An unserializable payload object becomes the single typed error.

    The hostile value cannot cross the serialization boundary: the
    Python-mode dump itself raises, and the dispatcher must convert that
    into exactly one ``DomainMechanismDispatchError`` without leaking the
    underlying exception text or the hostile repr, and without ever
    reaching the pack.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    hostile = object()
    object.__setattr__(request, "state_payload", {"level": hostile})
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "request_revalidation"
    assert excinfo.value.request_id is None
    assert excinfo.value.__cause__ is not None
    message = str(excinfo.value)
    assert "object at 0x" not in message
    assert str(excinfo.value.__cause__) not in message
    assert pack.calls == 0


def test_unserializable_result_next_state_object_is_wrapped_after_one_call() -> None:
    """An unserializable next-state object becomes the typed error post-step."""
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    object.__setattr__(result, "next_state_payload", {"level": object()})
    pack.result_override = result
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "result_revalidation"
    assert excinfo.value.request_id == "mechanism-step-request-1"
    assert excinfo.value.__cause__ is not None
    message = str(excinfo.value)
    assert "object at 0x" not in message
    assert str(excinfo.value.__cause__) not in message
    assert pack.calls == 1


def test_valid_tuple_records_remain_accepted_strictly() -> None:
    """Strict Python-mode revalidation accepts every conforming record.

    The happy path stays green end to end, and the detached verified
    request the pack receives keeps its exact tuple representation of
    ``exogenous_inputs`` while the returned verified result keeps the
    tuple representation of ``emissions`` and ``evidence``.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request(exogenous_inputs=world.exogenous_entries())
    # The fake pack answers with the exact payload of THIS request, not
    # the constructor's default mirror, so the result binds to it.
    pack.response_request_payload = request.model_dump(mode="json")
    result = dispatch_domain_mechanism_step(pack, request)
    assert pack.calls == 1
    assert result.request_id == request.identifier
    seen = pack.seen_requests[0]
    assert type(seen.exogenous_inputs) is tuple
    assert seen.exogenous_inputs == request.exogenous_inputs
    assert type(result.emissions) is tuple
    assert type(result.evidence) is tuple
    assert len(result.emissions) == 1
    assert len(result.evidence) == 1
    assert _self_hash(result) == result.content_hash


# ---------------------------------------------------------------------------
# Section J: hostile runtime subclasses on the original object graph
# (pre-normalization exact-type audit; zero/one-call boundary intact)
# ---------------------------------------------------------------------------


class _HostileDictSub(dict[str, object]):
    """A hostile ``dict`` subclass indistinguishable after serialization."""

    def __init__(self, source: Mapping[str, object] | None = None, /) -> None:
        super().__init__(source or {})


class _HostileListSub(list[object]):
    """A hostile ``list`` subclass indistinguishable after serialization."""


class _HostileIntSub(int):
    """A hostile ``int`` subclass indistinguishable after serialization."""


class _HostileStrSub(str):
    """A hostile ``str`` subclass indistinguishable after serialization."""


class _HostileFloatSub(float):
    """A hostile ``float`` subclass indistinguishable after serialization."""


class _SpecSubclass(DomainMechanismSpec):
    """A hostile subclass of the embedded mechanism-spec record."""


class _EmissionSubclass(MechanismEmissionRecord):
    """A hostile subclass of the embedded emission record."""


class _ExogenousSubclass(MechanismExogenousInput):
    """A hostile subclass of the embedded exogenous-input record."""


class _ImpostorEmissionRecord(BaseModel):
    """A foreign record model whose serialized shape could be normalized.

    Not a subclass of anything shipped: a wrong sibling Pydantic model
    with exactly the ``MechanismEmissionRecord`` field surface, so the
    Python-mode dump erases its foreign identity completely.
    """

    identifier: str
    sequence_position: int
    emission_schema_id: str
    emission_schema_hash: str
    content_hash: str
    payload: dict[str, object] = {}
    unit: str | None = None


def _recomputed_request_payload(request: DomainMechanismStepRequest) -> dict[str, object]:
    """The request's canonically identical payload with hashes recomputed."""
    payload = request.model_dump(mode="json")
    payload["state_hash"] = _canonical_hash(payload["state_payload"])
    payload["content_hash"] = _canonical_hash(
        {k: v for k, v in payload.items() if k != "content_hash"}
    )
    return payload


def _recomputed_result_payload(result: DomainMechanismStepResult) -> dict[str, object]:
    """The result's canonically identical payload with hashes recomputed."""
    payload = result.model_dump(mode="json")
    payload["next_state_hash"] = _canonical_hash(payload["next_state_payload"])
    payload["content_hash"] = _canonical_hash(
        {k: v for k, v in payload.items() if k != "content_hash"}
    )
    return payload


def test_request_dict_subclass_payload_is_rejected_before_normalization() -> None:
    """Case J1: a hash-consistent ``dict`` subclass in ``state_payload``.

    The subclass is canonically identical to the plain JSON the hashes
    were computed over, so only the pre-normalization exact-type audit
    can reject it; serialization would normalize it to a built-in dict.
    Zero pack calls.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    object.__setattr__(
        request,
        "state_payload",
        _HostileDictSub(request.state_payload),
    )
    payload = _recomputed_request_payload(request)
    hostile = DomainMechanismStepRequest.model_validate(payload)
    state_payload = payload["state_payload"]
    assert isinstance(state_payload, dict)
    object.__setattr__(hostile, "state_payload", _HostileDictSub(state_payload))
    assert list(hostile.state_payload.items()) == list(world.state_payload.items())
    assert hostile.state_hash == _canonical_hash(dict(hostile.state_payload))
    _rejects_zero_calls(pack, hostile, expected_reason="request_revalidation")


def test_result_dict_subclass_payload_is_rejected_after_one_call() -> None:
    """Case J2: a hash-consistent ``dict`` subclass in ``next_state_payload``."""
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    payload = _recomputed_result_payload(result)
    hostile = DomainMechanismStepResult.model_validate(payload)
    next_state_payload = payload["next_state_payload"]
    assert isinstance(next_state_payload, dict)
    object.__setattr__(
        hostile,
        "next_state_payload",
        _HostileDictSub(next_state_payload),
    )
    assert hostile.next_state_hash == _canonical_hash(dict(hostile.next_state_payload))
    pack.result_override = hostile
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_revalidation")


def test_request_nested_list_subclass_is_rejected_not_hash_masked() -> None:
    """Case J3: a ``list`` subclass nested inside an exact JSON payload.

    State and request hashes are recomputed over the canonically
    equivalent plain content, so a hash mismatch cannot mask the type
    defect: rejection must come from the type audit at revalidation.
    """
    world, pack = _fresh_world_and_pack()
    plain_payload: dict[str, object] = {"level": 0, "tags": ["calm"]}
    payload = world.request_payload()
    payload["state_payload"] = plain_payload
    payload["state_hash"] = _canonical_hash(plain_payload)
    payload["content_hash"] = _canonical_hash(
        {k: v for k, v in payload.items() if k != "content_hash"}
    )
    request = DomainMechanismStepRequest.model_validate(payload)
    object.__setattr__(
        request,
        "state_payload",
        {"level": 0, "tags": _HostileListSub(["calm"])},
    )
    assert request.state_hash == _canonical_hash(dict(request.state_payload))
    _rejects_zero_calls(pack, request, expected_reason="request_revalidation")


@pytest.mark.parametrize(
    ("hostile_value", "plain_value"),
    [(_HostileIntSub(7), 7), (_HostileStrSub("sun"), "sun"), (_HostileFloatSub(0.25), 0.25)],
)
def test_request_scalar_builtin_subclass_is_rejected(
    hostile_value: object, plain_value: object
) -> None:
    """Case J4: ``int``/``str``/``float`` subclasses inside a payload.

    The state hash is recomputed over the canonically identical plain
    content, so a hash mismatch cannot mask the type defect: only the
    exact-type audit can reject these payloads.
    """
    world, pack = _fresh_world_and_pack()
    payload = world.request_payload()
    payload["state_payload"] = {"level": 0, "marker": plain_value}
    payload["state_hash"] = _canonical_hash({"level": 0, "marker": plain_value})
    payload["content_hash"] = _canonical_hash(
        {k: v for k, v in payload.items() if k != "content_hash"}
    )
    request = DomainMechanismStepRequest.model_validate(payload)
    object.__setattr__(request, "state_payload", {"level": 0, "marker": hostile_value})
    assert request.state_hash == _canonical_hash(dict(request.state_payload))
    _rejects_zero_calls(pack, request, expected_reason="request_revalidation")


def test_release_profile_spec_subclass_is_rejected_before_normalization() -> None:
    """Case J5: a ``DomainMechanismSpec`` subclass embedded in the profile.

    All content and hashes remain canonically identical to the accepted
    profile; only the runtime type of the embedded spec is hostile.
    Serialization would erase it; the audit rejects at revalidation with
    zero calls.
    """
    world = MechanismWorld()
    subclassed_spec = _SpecSubclass.model_validate(world.spec.model_dump(mode="json"))
    payload = world.profile.model_dump(mode="json")
    payload["mechanism_spec"] = subclassed_spec
    assert subclassed_spec.model_dump(mode="json") == world.spec.model_dump(mode="json")
    hostile_profile = ModelPackReleaseProfile.model_validate(payload)
    pack = RecordingPack(world)
    pack.release_profile = hostile_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_revalidation")


def test_result_emission_subclass_tuple_is_rejected_after_one_call() -> None:
    """Case J6: a ``MechanismEmissionRecord`` subclass in the exact tuple.

    Record and result hashes remain canonically identical; the exact
    ``tuple`` container itself is valid, so only the pre-normalization
    element-type audit can reject it. Exactly one call.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    subclassed = _EmissionSubclass.model_validate(result.emissions[0].model_dump(mode="json"))
    assert subclassed.model_dump(mode="python") == result.emissions[0].model_dump(mode="python")
    object.__setattr__(result, "emissions", (subclassed,))
    assert type(result.emissions) is tuple
    pack.result_override = result
    pack.response_request_payload = request.model_dump(mode="json")
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_revalidation")


def test_request_exogenous_subclass_tuple_is_rejected_with_zero_calls() -> None:
    """Case J7: a ``MechanismExogenousInput`` subclass in the exact tuple.

    The request content hash remains canonically identical to the valid
    request; only the runtime element type is hostile. Zero calls.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request(exogenous_inputs=world.exogenous_entries())
    subclassed_entries = tuple(
        _ExogenousSubclass.model_validate(entry.model_dump(mode="json"))
        for entry in request.exogenous_inputs
    )
    assert [entry.model_dump(mode="python") for entry in subclassed_entries] == [
        entry.model_dump(mode="python") for entry in request.exogenous_inputs
    ]
    object.__setattr__(request, "exogenous_inputs", subclassed_entries)
    assert type(request.exogenous_inputs) is tuple
    _rejects_zero_calls(pack, request, expected_reason="request_revalidation")


def test_result_foreign_impostor_record_is_rejected_after_one_call() -> None:
    """Case J8: a wrong sibling model whose dump is byte-equal to a record.

    The foreign model is not a subclass of anything shipped; its
    Python-mode dump equals the exact record's dump, so strict
    revalidation of the dumped payload alone could never reject it. The
    pre-normalization audit must. Exactly one call.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    impostor = _ImpostorEmissionRecord.model_validate(result.emissions[0].model_dump(mode="json"))
    assert impostor.model_dump(mode="python") == result.emissions[0].model_dump(mode="python")
    object.__setattr__(result, "emissions", (impostor,))
    pack.result_override = result
    pack.response_request_payload = request.model_dump(mode="json")
    _rejects_after_exactly_one_call(pack, request, expected_reason="result_revalidation")


def test_cyclic_exact_dict_payload_fails_closed_typed_with_zero_calls() -> None:
    """Case J9: a cyclic exact-``dict`` payload raises only the typed error.

    The cycle is invisible to the contract validators and to strict
    revalidation of the dumped form; it explodes in canonical hashing.
    The audit's cycle detection rejects it on the original graph before
    any hashing, so no raw ``RecursionError``/``ValueError`` escapes and
    the pack is never reached.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    cyclic: dict[str, object] = dict(request.state_payload)
    cyclic["self"] = cyclic
    object.__setattr__(request, "state_payload", cyclic)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "request_revalidation"
    assert excinfo.value.request_id is None
    assert isinstance(excinfo.value.__cause__, TypeError)
    assert "self" not in str(excinfo.value)
    assert pack.calls == 0


def test_deep_nesting_recursion_failure_is_typed_with_zero_calls() -> None:
    """Case J10: recursion exhaustion during the audit becomes the typed error.

    A finite, acyclic, deeply nested exact ``dict`` payload overflows the
    interpreter stack during graph inspection; the failure is converted
    into exactly one ``DomainMechanismDispatchError`` with the underlying
    ``RecursionError`` preserved privately and no hostile depth leaked.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    deep: object = {"level": 0}
    for _ in range(3 * sys.getrecursionlimit()):
        deep = {"nested": deep}
    object.__setattr__(request, "state_payload", deep)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "request_revalidation"
    assert excinfo.value.request_id is None
    assert isinstance(excinfo.value.__cause__, RecursionError)
    assert "RecursionError" not in str(excinfo.value)
    assert pack.calls == 0


def test_cyclic_exact_result_payload_fails_closed_typed_after_one_call() -> None:
    """Case J11: a cyclic result payload becomes the typed error post-step.

    The cycle sits behind an exact ``dict`` field of an exactly-typed
    result, so the hostile shape survives the surface checks and reaches
    hashing; the typed boundary converts the failure after exactly one
    pack call with no partial result.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    cyclic: dict[str, object] = dict(result.next_state_payload)
    cyclic["self"] = cyclic
    object.__setattr__(result, "next_state_payload", cyclic)
    pack.result_override = result
    pack.response_request_payload = request.model_dump(mode="json")
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "result_revalidation"
    assert excinfo.value.request_id == "mechanism-step-request-1"
    assert isinstance(excinfo.value.__cause__, TypeError)
    assert pack.calls == 1


def test_valid_exact_subclass_free_records_remain_accepted_strictly() -> None:
    """Case J12: the exact-typed happy path (J1-J11 shape) stays green.

    The full authority world - manifest, profile with embedded spec,
    request with exact tuple exogenous inputs, result with exact tuple
    emissions/evidence and timezone-aware datetimes - is accepted by the
    same audit that rejects every hostile runtime type above.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request(exogenous_inputs=world.exogenous_entries())
    pack.response_request_payload = request.model_dump(mode="json")
    result = dispatch_domain_mechanism_step(pack, request)
    assert pack.calls == 1
    assert type(result.emissions) is tuple
    assert type(result.evidence) is tuple
    assert type(pack.seen_requests[0].exogenous_inputs) is tuple
    assert world.manifest.created_at.tzinfo is not None
    assert _self_hash(result) == result.content_hash


def test_audit_rejects_every_hostile_graph_kind_with_preserved_cause() -> None:
    """Case J13: every audited authority rejects its own hostile graph.

    Request, manifest, and release-profile injections each fail at their
    own revalidation reason with zero calls, and each typed error
    preserves a ``TypeError`` cause without exposing its text.
    """
    world = MechanismWorld()
    request = world.request()
    object.__setattr__(request, "action_payload", _HostileDictSub(request.action_payload))
    pack = RecordingPack(world)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "request_revalidation"
    assert isinstance(excinfo.value.__cause__, TypeError)
    assert "dict" not in str(excinfo.value)

    forged_manifest = world.manifest.model_copy(deep=True)
    object.__setattr__(
        forged_manifest,
        "supported_api_versions",
        _HostileListSub(forged_manifest.supported_api_versions),
    )
    pack = RecordingPack(world)
    pack.manifest = forged_manifest
    _rejects_zero_calls(pack, world.request(), expected_reason="manifest_revalidation")

    subclassed_spec = _SpecSubclass.model_validate(world.spec.model_dump(mode="json"))
    payload = world.profile.model_dump(mode="json")
    payload["mechanism_spec"] = subclassed_spec
    hostile_profile = ModelPackReleaseProfile.model_validate(payload)
    pack = RecordingPack(world)
    pack.release_profile = hostile_profile
    _rejects_zero_calls(pack, world.request(), expected_reason="release_profile_revalidation")


def test_result_exact_tuple_still_accepted_after_hostile_cases() -> None:
    """Case J14: the valid-tuple happy path remains green (regression guard).

    The audit accepts exact built-in tuples for tuple contract fields and
    exact built-in dicts/lists for JSON payload fields, so rejecting
    subclasses never degrades into rejecting the contract shapes.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request(exogenous_inputs=world.exogenous_entries())
    pack.response_request_payload = request.model_dump(mode="json")
    result = dispatch_domain_mechanism_step(pack, request)
    assert pack.calls == 1
    assert type(result.emissions) is tuple
    assert type(result.emissions[0]) is MechanismEmissionRecord
    assert type(result.evidence) is tuple


# ---------------------------------------------------------------------------
# Section J+: hostile instance namespaces and dump-time failures
# (complete inspection/revalidation error boundaries)
# ---------------------------------------------------------------------------


class _HostileNamespaceDict(dict[str, object]):
    """A test-only mapping whose ``items()`` raises a private ``ValueError``.

    It stands in for a hostile ``__dict__`` replacement on a
    validator-bypassed exact record: ordinary inspection of the instance
    namespace explodes instead of yielding field values.
    """

    def __init__(self, source: dict[str, object], /) -> None:
        super().__init__(source)

    def items(self) -> NoReturn:
        raise ValueError("private hostile namespace text")


def _namespace_replaced(record: DomainMechanismStepRequest | DomainMechanismStepResult) -> None:
    """Replace one exact record's ``__dict__`` through the object boundary."""
    object.__setattr__(record, "__dict__", _HostileNamespaceDict(dict(record.__dict__)))


def test_hostile_request_namespace_fails_closed_with_zero_calls() -> None:
    """Case R1: a hostile ``__dict__`` on an exact request becomes typed.

    The audit itself must not explode when enumerating the instance
    namespace: every ordinary exception raised during inspection becomes
    the single typed error with the private cause preserved and the
    private text withheld, and the pack is never reached.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    _namespace_replaced(request)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "request_revalidation"
    assert excinfo.value.request_id is None
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert "private hostile namespace text" not in str(excinfo.value)
    assert "private hostile namespace text" not in repr(excinfo.value)
    assert pack.calls == 0


def test_hostile_result_namespace_fails_closed_after_one_call() -> None:
    """Case R2: a hostile ``__dict__`` on an exact returned result is typed.

    The valid result is built first, so the failure comes solely from the
    post-step namespace inspection: the typed error names the result
    revalidation reason after exactly one call, with a generic public
    message and no private text.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    result = world.result_for(request)
    pack.response_request_payload = request.model_dump(mode="json")
    _namespace_replaced(result)
    pack.result_override = result
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == "result_revalidation"
    assert excinfo.value.request_id == "mechanism-step-request-1"
    assert isinstance(excinfo.value.__cause__, ValueError)
    message = str(excinfo.value)
    assert "private hostile namespace text" not in message
    assert "private hostile namespace text" not in repr(excinfo.value)
    assert pack.calls == 1


@pytest.mark.parametrize(("dump_error", "expected_reason"), [(ValueError, "request_revalidation")])
def test_dump_failure_after_audit_becomes_typed_with_zero_calls(
    monkeypatch: pytest.MonkeyPatch, dump_error: type[Exception], expected_reason: str
) -> None:
    """Case R3: a dump-time failure behind a clean audit becomes typed.

    The request stays exact and the pre-normalization audit passes, so a
    temporary test-only class-level ``model_dump`` replacement raising an
    ordinary exception is the sole failure source (class attributes are
    invisible to the instance-graph audit, keeping the graph clean); the
    boundary must convert it with the original exception preserved
    privately, the public message generic, and the pack never reached.
    """
    world, pack = _fresh_world_and_pack()
    request = world.request()
    json_payload: dict[str, object] = request.model_dump(mode="json")
    private_message = "private dump failure text"

    def hostile_dump(*args: object, **kwargs: object) -> object:
        if kwargs.get("mode") == "python":
            raise dump_error(private_message)
        return dict(json_payload)

    monkeypatch.setattr(type(request), "model_dump", hostile_dump)
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        dispatch_domain_mechanism_step(pack, request)
    assert excinfo.value.reason == expected_reason
    assert excinfo.value.request_id is None
    assert isinstance(excinfo.value.__cause__, dump_error)
    assert private_message not in str(excinfo.value)
    assert private_message not in repr(excinfo.value)
    assert pack.calls == 0


def test_dispatcher_source_wires_the_prenormalization_audit() -> None:
    """Static guard: the pre-normalization audit precedes every dump site.

    The module must inspect original object graphs (``_reject_non_exact_object_graph``)
    and must not serialize ``untrusted_*`` values ahead of that audit, so
    a future edit cannot silently reintroduce dump-first type erasure.
    """
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    code = "".join(source.split('"""')[::2])
    assert "_reject_non_exact_object_graph" in code
    assert code.count("_reject_non_exact_object_graph(") == 5
    assert "cyclic container in supplied object graph" in code
    assert "RecursionError" in code
    assert "untrusted_manifest, untrusted_release_profile" in code


# ---------------------------------------------------------------------------
# Section H: static boundary proofs over the dispatcher module source
# ---------------------------------------------------------------------------

_STATIC_FORBIDDEN_TOKENS = (
    "importlib",
    "__import__",
    "import_module",
    "pkgutil",
    "walk_packages",
    "iter_modules",
    "entry_points",
    "open(",
    "Path(",
    "time.time",
    "datetime.now",
    "datetime.utcnow",
    "os.environ",
    "getenv",
    "random.",
    "numpy",
    "sqlite",
    "requests",
    "urllib",
    "socket",
    "subprocess",
    "nexus",
    "legion",
    "policy",
    "strategy",
    "scheduler",
    "retry",
    "Persist",
    "persistence",
    "isinstance(pack, DomainPack)",
    "runtime_checkable",
    "FastAPI",
    "APIRouter",
)


def _dispatcher_code_only() -> str:
    """The dispatcher source with all string/docstring literals stripped.

    Forbidden-token scanning over stripped code proves the executable
    surface, not prose: docstrings that describe what the module does not
    do must never fail the scan.
    """
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    return "".join(source.split('"""')[::2])


def test_dispatcher_module_has_no_forbidden_surface_tokens() -> None:
    code = _dispatcher_code_only()
    lowered = code.lower()
    for token in _STATIC_FORBIDDEN_TOKENS:
        assert token.lower() not in lowered, f"forbidden dispatcher token: {token}"
    error_source = ERRORS_PATH.read_text(encoding="utf-8")
    error_code = "".join(error_source.split('"""')[::2])
    for token in ("nexus", "legion", "policy", "strategy", "scheduler"):
        assert token not in error_code.lower(), f"forbidden error token: {token}"


def test_dispatcher_imports_only_the_public_domainpack_protocol() -> None:
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    domain_pack_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "domain_packs" in node.module:
            for alias in node.names:
                domain_pack_imports.append(f"{node.module}:{alias.name}")
    assert domain_pack_imports == ["kalhas.domain_packs:DomainPack"]


def test_dispatcher_module_defines_exactly_one_public_function() -> None:
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_functions = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert "dispatch_domain_mechanism_step" in top_level_functions
    public = [name for name in top_level_functions if not name.startswith("_")]
    assert public == ["dispatch_domain_mechanism_step"]


def test_dispatcher_registers_nothing_and_exports_nothing_globally() -> None:
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    assert "__all__" in source
    assert source.count("__all__") == 1
    assert "dispatch_domain_mechanism_step" in source
    application_init = (REPO_ROOT / "kalhas" / "application" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "domain_mechanism" not in application_init
    assert "dispatch" not in application_init


def test_error_module_public_message_is_generic_and_single() -> None:
    source = ERRORS_PATH.read_text(encoding="utf-8")
    assert "class DomainMechanismDispatchError(KalhasDomainError):" in source
    assert "super().__init__(" in source
    assert source.count("super().__init__(") == 1


def test_dispatch_rejects_via_single_typed_error_entrypoint() -> None:
    """Every reject path funnels through ``_fail``; all raises are typed."""
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    raised = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)]
    assert raised
    for node in raised:
        func = getattr(node.exc, "func", None)
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        assert name in {"DomainMechanismDispatchError", "_fail"}, (
            "every raise is the typed error or the typed helper"
        )
    fail_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_fail"
    ]
    assert len(fail_calls) >= 20


def test_every_pre_dispatch_failure_calls_step_zero_times_contract() -> None:
    """Section B–E helpers pin zero-call behavior; the contract holds."""
    world, pack = _fresh_world_and_pack()
    _rejects_zero_calls(pack, {"identifier": "not-a-request"}, expected_reason="request_type")
    assert pack.calls == 0


# ---------------------------------------------------------------------------
# Section I: unchanged public surface
# ---------------------------------------------------------------------------


def test_public_contract_registry_remains_exactly_61() -> None:
    assert len(PUBLIC_CONTRACTS) == 61


def test_phase29_registry_tail_remains_the_accepted_mechanism_modelpack_tail() -> None:
    names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
    assert names[55:61] == [
        "DomainMechanismSpec",
        "DomainMechanismStepRequest",
        "DomainMechanismStepResult",
        "ModelPackReleaseProfile",
        "ModelPackAssuranceProfile",
        "ModelPackCatalogueEntry",
    ]


def test_all_schema_artifacts_remain_byte_unchanged() -> None:
    schemas = generate_schemas()
    on_disk = {path.name: path for path in SCHEMA_DIR.glob("*.schema.json")}
    assert set(schemas) == set(on_disk)
    assert len(on_disk) == 61
    for name, content in schemas.items():
        assert on_disk[name].read_text(encoding="utf-8") == content


def test_new_slice_adds_no_schema_no_contract_no_registry_item() -> None:
    artifact_names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert "DomainMechanismDispatchError.schema.json" not in artifact_names
    contract_names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
    assert "DomainMechanismDispatchError" not in contract_names
    assert "dispatch_domain_mechanism_step" not in contract_names


def test_phase29_domain_neutrality_boundary_suite_remains_green() -> None:
    """The accepted Phase 29 boundary expectations still hold verbatim."""
    base = REPO_ROOT / "kalhas"
    dispatcher_source = DISPATCHER_PATH.read_text(encoding="utf-8")
    assert not re.search(
        r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b",
        dispatcher_source,
    )
    for path in sorted((base / "application").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    is_pack_import = alias.name == "kalhas.domain_packs" or alias.name.startswith(
                        "kalhas.domain_packs."
                    )
                    assert not is_pack_import, f"{path.name}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("kalhas.domain_packs"):
                    assert module in {"kalhas.domain_packs", "kalhas.domain_packs.base"}, (
                        f"{path.name}: from {module} import ..."
                    )
                    assert all(alias.name == "DomainPack" for alias in node.names), (
                        f"{path.name}: non-protocol pack import"
                    )
    vocabulary = re.compile(
        r"(pandemic|compartmen|infection|epidemi|pathogen|covasim|starsim|gleam|"
        r"government_ready|production-safe)",
        re.IGNORECASE,
    )
    for path in sorted((base / "application").glob("*.py")):
        assert not vocabulary.search(path.read_text(encoding="utf-8")), f"vocabulary in {path.name}"
