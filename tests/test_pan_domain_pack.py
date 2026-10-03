"""H29-S04 tests for the minimal synthetic KALHAS-PAN v0.1 DomainPack.

Covers, per the slice requirements:

A. Protocol and isolation - resolved ``DomainPack`` structural
   conformance (``typing.get_type_hints``, never string-annotation
   comparison), exact identities across manifest/profile/spec, the
   top-level ``kalhas.domain_packs`` export, PAN isolation below its
   dedicated subpackage, no kernel/application PAN import, no dynamic
   loading or discovery, and real static evidence that no
   API/runtime/store/adapter module references PAN.
B. Identity and reproducibility - byte-identical fresh instances,
   recomputation of every content hash, the five pack-owned schema
   descriptors rebuilt fresh and equal to their bound digests (never
   shared mutable globals), the ``mechanism.py`` implementation-hash
   binding, the unchanged ``uv.lock`` dependency-lock binding, fixed
   timezone-aware timestamps, and no random/process-dependent
   identifiers.
C. Happy-path behavior - direct and dispatched steps, byte-identical
   repeats, unchanged request, detached results whose in-place mutation
   contaminates nothing, conservation, non-negativity, absorbing
   deceased, capacity respect, ordered and hashed emissions/evidence.
D. Hand-checkable transition semantics - two fully hand-calculated
   pinned fixtures (transition counts, next state, emissions, evidence,
   and hashes), non-increasing intervention exposure with a strictly
   decreasing representative, full-intervention effect, zero-compliance
   irrelevance, zero-source zero-flow identities, capacity capping with
   overflow retained in the source compartment, no same-step cascade,
   and exact half-even ties.
E. Adversarial validation - parametrized missing/extra keys, booleans,
   floats, strings, negatives, out-of-range action and configuration
   values, invalid capacities, broken conservation, occupancy above
   capacity, non-empty exogenous input, foreign schema identities and
   hashes, malformed contract hashes versus well-formed false hashes,
   changed configuration under the same release identity, mutated and
   replaced manifest/spec/profile/nested-configuration authority, fresh
   instances never contaminated by a mutated pack, and non-finite or
   arbitrary-object values, with no silent coercion, normalization, or
   repair anywhere.
F. Static purity and truthful scope - AST scans proving the production
   PAN source performs no filesystem, network, provider, database,
   environment, clock, subprocess, dynamic-import, or RNG access, an
   exact import allowlist, no forbidden symbols, no mutable
   module-level container authority, no assurance/catalogue artifact or
   maturity value, the public-contract registry and the schema
   directory at exactly 61, and byte-equal generated schema artifacts.

All fixtures are synthetic; every pinned expectation below was
hand-calculated from the declared PAN v0.1 equations in
``kalhas/domain_packs/pan/mechanism.py`` and no expected value is
computed by production transition logic.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_type_hints

import pytest
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.schema_export import generate_schemas
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismExogenousInput,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import (
    ModelPackAssuranceProfile,
    ModelPackCatalogueEntry,
    ModelPackLimitation,
    ModelPackProvenance,
    ModelPackReleaseProfile,
    ModelPackResourceEnvelope,
    ModelPackScope,
)
from kalhas.domain_packs import DomainPack
from kalhas.domain_packs.pan import PanV01DomainPack
from kalhas.domain_packs.pan.mechanism import (
    BPS_MAX,
    CONFIGURATION_KEYS,
    EVENT_IDS,
    STATE_KEYS,
    PanDomainPackError,
    compute_transition,
    effective_transmission_bps,
    round_half_even,
    validate_action_payload,
    validate_configuration_payload,
    validate_state_payload,
)
from pydantic import BaseModel, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
PAN_PACKAGE = REPO_ROOT / "kalhas" / "domain_packs" / "pan"
MECHANISM_PATH = PAN_PACKAGE / "mechanism.py"
PACK_PATH = PAN_PACKAGE / "pack.py"
INIT_PATH = PAN_PACKAGE / "__init__.py"
LOCK_PATH = REPO_ROOT / "uv.lock"
KALHAS_ROOT = REPO_ROOT / "kalhas"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

PRODUCTION_PAN_MODULES = ("__init__.py", "mechanism.py", "pack.py")

EXPECTED_IMPLEMENTATION_HASH = "947bfcca6d0b049439cecf08d110afd3b91f2b402a18c22cba45469f420d2774"
EXPECTED_DEPENDENCY_LOCK_HASH = "0c5c4f978111d01bec3bcefaf5186964ee2c2fab4fa4d3f26937b3857205f422"

_MATURITY_VOCABULARY = (
    "experimental",
    "benchmarked",
    "externally_reviewed",
    "partner_evaluation_ready",
    "conformance_only",
    "catalogued",
)

_FREEZING_EXTERNAL_NAMES = (
    "covasim",
    "starsim",
    "gleam",
    "numpy",
    "scipy",
)

#: Exactly 64 valid lowercase hexadecimal characters, guaranteed to
#: differ from every genuine pack hash (verified in the tamper tests).
_FAKE_HEX_64 = "0123456789abcdef" * 4


# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------


def _canonical_hash(payload: object) -> str:
    """Canonical SHA-256 of the exact JSON payload (independent of production)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _self_hash(model: BaseModel) -> str:
    """Independent self-covering hash over a contract's JSON rendering."""
    dumped: dict[str, object] = model.model_dump(mode="json")
    del dumped["content_hash"]
    return _canonical_hash(dumped)


def _pin_state(
    susceptible: int = 900,
    exposed: int = 50,
    infectious: int = 30,
    hospitalized: int = 15,
    intensive_care: int = 5,
    recovered: int = 0,
    deceased: int = 0,
) -> dict[str, int]:
    """A hand-chosen synthetic PAN state; conservation is structural."""
    population_total = (
        susceptible + exposed + infectious + hospitalized + intensive_care + recovered + deceased
    )
    return {
        "population_total": population_total,
        "susceptible": susceptible,
        "exposed": exposed,
        "infectious": infectious,
        "hospitalized": hospitalized,
        "intensive_care": intensive_care,
        "recovered": recovered,
        "deceased": deceased,
    }


@pytest.fixture(scope="module")
def pan_pack() -> PanV01DomainPack:
    """One fresh pack instance shared by identity-focused tests."""
    return PanV01DomainPack()


def _validated_configuration(pan_pack: PanV01DomainPack) -> dict[str, int]:
    """The pack's exact immutable configuration as validated integers."""
    spec_configuration = pan_pack.mechanism_spec.configuration
    return validate_configuration_payload(spec_configuration, spec_configuration)


def _configuration_variant(
    pan_pack: PanV01DomainPack, key: str, value: object
) -> dict[str, object]:
    """The exact configuration with one value replaced (contract-valid JSON)."""
    configuration: dict[str, object] = dict(_validated_configuration(pan_pack))
    configuration[key] = value
    return configuration


def _request_payload(
    spec: DomainMechanismSpec,
    release_profile_id: str,
    release_profile_content_hash: str,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
    *,
    identifier: str = "pan-request-1",
    step_index: int = 0,
) -> dict[str, object]:
    """A canonical request payload for the PAN authorities.

    Every payload hash covers the exact payload content and the overall
    ``content_hash`` is sealed with the repository rule, so a mutated
    payload yields a self-consistent request whose rejection is a real
    mechanism decision, never a construction artifact.
    """
    state: Mapping[str, object] = _pin_state() if state_payload is None else state_payload
    action: Mapping[str, object] = (
        {"intervention_intensity_bps": 2500} if action_payload is None else action_payload
    )
    configuration: Mapping[str, object] = (
        dict(validate_configuration_payload(spec.configuration, spec.configuration))
        if configuration_payload is None
        else configuration_payload
    )
    payload: dict[str, object] = {
        "identifier": identifier,
        "tenant_id": "kalhas-synthetic",
        "schema_version": "1.0.0",
        "mechanism_spec_id": spec.identifier,
        "mechanism_spec_content_hash": spec.content_hash,
        "release_profile_id": release_profile_id,
        "release_profile_content_hash": release_profile_content_hash,
        "realization_id": None,
        "realization_content_hash": None,
        "scenario_id": "scenario-pan-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-pan-v1",
        "world_content_hash": "b" * 64,
        "seed_id": "seed-pan-1",
        "seed_content_hash": "c" * 64,
        "run_id": "run-pan-1",
        "step_index": step_index,
        "state_schema_id": spec.state_schema_id,
        "action_schema_id": spec.action_schema_id,
        "configuration_schema_id": spec.configuration_schema_id,
        "state_schema_hash": spec.state_schema_hash,
        "action_schema_hash": spec.action_schema_hash,
        "configuration_schema_hash": spec.configuration_schema_hash,
        "state_payload": state,
        "action_payload": action,
        "configuration_payload": configuration,
        "state_hash": _canonical_hash(state),
        "action_hash": _canonical_hash(action),
        "configuration_hash": _canonical_hash(configuration),
        "exogenous_inputs": [],
        "content_hash": "0" * 64,
    }
    payload["content_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    return payload


def _verified_request(
    pan_pack: PanV01DomainPack,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
    *,
    identifier: str = "pan-request-1",
    step_index: int = 0,
) -> DomainMechanismStepRequest:
    """Build one hash-consistent verified request for the given pack."""
    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
        state_payload=state_payload,
        action_payload=action_payload,
        configuration_payload=configuration_payload,
        identifier=identifier,
        step_index=step_index,
    )
    return DomainMechanismStepRequest.model_validate(payload)


def _finalized_mutated_request(payload: dict[str, object]) -> DomainMechanismStepRequest:
    """Re-seal a mutated request payload with the repository hash rule.

    The self-covering digest covers everything except the
    ``content_hash`` field itself, exactly as the contract computes it.
    """
    payload["content_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    return DomainMechanismStepRequest.model_validate(payload)


def _state_variant(mutation: dict[str, object]) -> dict[str, object]:
    """The pinned state with one mutation applied.

    ``...`` (Ellipsis) as the value removes the key entirely; any other
    value replaces the key's value while remaining valid JSON content,
    so rejection happens inside the PAN mechanism, not at construction.
    """
    state: dict[str, object] = dict(_pin_state())
    for key, value in mutation.items():
        if value is ...:
            state.pop(key)
        else:
            state[key] = value
    return state


def _expect_pan_rejection(
    pan_pack: PanV01DomainPack,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
    *,
    identifier: str = "pan-request-1",
    step_index: int = 0,
) -> None:
    """The mutated request is rejected by direct step and by dispatch."""
    request = _verified_request(
        pan_pack,
        state_payload,
        action_payload,
        configuration_payload,
        identifier=identifier,
        step_index=step_index,
    )
    with pytest.raises(PanDomainPackError):
        pan_pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pan_pack, request)


def _production_code(name: str) -> str:
    """The production source of one PAN module with docstrings stripped."""
    source = (PAN_PACKAGE / name).read_text(encoding="utf-8")
    return "".join(source.split('"""')[::2])


# ---------------------------------------------------------------------------
# Section A: protocol and isolation
# ---------------------------------------------------------------------------


def test_pan_pack_statically_conforms_to_domainpack_protocol() -> None:
    """PanV01DomainPack structurally satisfies the DomainPack protocol.

    Class and method annotations are resolved with
    ``typing.get_type_hints`` and compared against the protocol's
    resolved annotations, so declared strings can never masquerade as
    runtime classes.  Passing the instance to the generic dispatcher
    (annotated against ``DomainPack``) additionally proves full
    structural conformance under strict mypy.
    """
    pack_hints = get_type_hints(PanV01DomainPack)
    protocol_hints = get_type_hints(DomainPack)
    for member in ("manifest", "release_profile", "mechanism_protocol_version"):
        assert pack_hints[member] == protocol_hints[member], member
    assert get_type_hints(PanV01DomainPack.step) == get_type_hints(DomainPack.step)
    assert pack_hints["manifest"] is DomainPackManifest
    assert pack_hints["mechanism_spec"] is DomainMechanismSpec
    assert pack_hints["release_profile"] is ModelPackReleaseProfile
    assert pack_hints["mechanism_protocol_version"] == Literal["1.0.0"]
    instance = PanV01DomainPack()
    assert isinstance(instance.manifest, DomainPackManifest)
    assert isinstance(instance.release_profile, ModelPackReleaseProfile)
    assert instance.mechanism_protocol_version == "1.0.0"
    assert callable(instance.step)
    assert getattr(DomainPack, "_is_protocol", False) is True


def test_pan_pack_has_exactly_one_public_executable_operation() -> None:
    """``step`` is the only public method; no second executable surface."""
    public_attributes = {
        name
        for name in dir(PanV01DomainPack)
        if not name.startswith("_")
        and name not in {"manifest", "release_profile", "mechanism_spec"}
    }
    methods = {
        name
        for name in public_attributes
        if callable(getattr(PanV01DomainPack, name, None))
        and not isinstance(getattr(PanV01DomainPack, name), property)
    }
    assert methods == {"step"}
    forbidden = {
        "run",
        "execute",
        "schedule",
        "advance",
        "simulate",
        "load",
        "resolve",
        "register",
        "discover",
        "bind",
        "start",
        "stop",
        "on_event",
        "callback",
    }
    assert not (methods & forbidden)


def test_pan_protocol_manifest_and_release_profile_are_exact_v1_contracts(
    pan_pack: PanV01DomainPack,
) -> None:
    """The pack surface is exactly the shipped v1 contract types."""
    assert type(pan_pack.manifest) is DomainPackManifest
    assert type(pan_pack.mechanism_protocol_version) is str
    assert pan_pack.mechanism_protocol_version == "1.0.0"
    assert type(pan_pack.release_profile) is ModelPackReleaseProfile


def test_pan_manifest_profile_spec_identities_agree(pan_pack: PanV01DomainPack) -> None:
    """Pack/version/manifest/mechanism identities agree across the surface."""
    manifest, spec, profile = pan_pack.manifest, pan_pack.mechanism_spec, pan_pack.release_profile
    assert profile.pack_id == manifest.pack_id == spec.pack_id == "kalhas-pan"
    assert profile.pack_version == manifest.pack_version == spec.pack_version == "0.1.0"
    assert profile.manifest_id == manifest.identifier == spec.manifest_id
    assert profile.manifest_content_hash == manifest.content_hash == spec.manifest_content_hash
    assert profile.mechanism_id == spec.mechanism_id == "pan-compartment-flow"
    assert profile.mechanism_version == spec.mechanism_version == "0.1.0"
    assert profile.mechanism_protocol_version == spec.mechanism_protocol_version == "1.0.0"
    assert profile.configuration_identity == spec.configuration_hash
    assert manifest.tenant_id == spec.tenant_id == profile.tenant_id == "kalhas-synthetic"


def test_pan_spec_declares_exact_protocol_numbers_and_timestep(pan_pack: PanV01DomainPack) -> None:
    """The spec declares the exact protocol version, numeric rule, and day step."""
    spec = pan_pack.mechanism_spec
    assert spec.mechanism_protocol_version == "1.0.0"
    assert spec.numeric_profile == "kalhas-platform-bound-binary64-v1"
    assert spec.precision == "ieee-754-binary64"
    assert spec.rounding_mode == "round-to-nearest-ties-to-even"
    assert spec.timestep == 1
    assert spec.timestep_unit == "day"
    assert spec.event_order == EVENT_IDS
    assert len(spec.reduction_order) >= 1


def test_pan_subpackage_exposes_only_the_concrete_entry_point() -> None:
    """``kalhas.domain_packs.pan`` exports exactly ``PanV01DomainPack``."""
    import kalhas.domain_packs.pan as pan_init

    assert pan_init.__all__ == ["PanV01DomainPack"]
    init_source = INIT_PATH.read_text(encoding="utf-8")
    assert "__all__" in init_source
    tree = ast.parse(init_source)
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]
    assert imported == ["PanV01DomainPack"]


def test_top_level_domain_packs_still_exports_only_domainpack() -> None:
    """The top-level pack package still exposes only the protocol."""
    import kalhas.domain_packs as top_level

    assert top_level.__all__ == ["DomainPack"]


def test_pan_is_imported_only_from_its_dedicated_subpackage() -> None:
    """Only the PAN subpackage itself imports PAN modules."""
    offenders: list[str] = []
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        relative = path.relative_to(KALHAS_ROOT).as_posix()
        if relative.startswith("domain_packs/pan/"):
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"domain_packs[.\w]*pan", source):
            offenders.append(relative)
    assert not offenders, f"PAN imported outside its subpackage: {offenders}"


def test_no_kernel_or_application_module_imports_pan() -> None:
    """No kernel/application module imports PAN or recognizes PAN vocabulary."""
    for subpath in ("application", "contracts", "adapters", "api", "runtime", "store"):
        directory = KALHAS_ROOT / subpath
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            assert "domain_packs.pan" not in source, f"PAN import in {path}"
            assert "PanV01DomainPack" not in source, f"PAN symbol in {path}"


def test_pan_creation_uses_no_dynamic_loading_or_discovery() -> None:
    """Production PAN source contains no discovery or import machinery."""
    machinery = re.compile(
        r"\b(pkgutil|walk_packages|iter_modules|entry_points|import_module|"
        r"importlib|__import__|exec\(|eval\(|compile\(|__builtins__)\b"
    )
    for name in PRODUCTION_PAN_MODULES:
        code = _production_code(name)
        assert not machinery.search(code), f"dynamic machinery in {name}"


def test_no_api_runtime_store_adapter_file_references_pan() -> None:
    """No API/runtime/store/adapter module references PAN in any form.

    Real static evidence on exact file bytes: the dedicated-subpackage
    import ``kalhas.domain_packs.pan.pack`` is legitimate inside PAN
    itself, so the scan here covers every non-PAN kernel surface and
    must fail if a PAN import, the PAN symbol, or even the standalone
    token ``pan`` enters one of them.
    """
    for subpath in ("api", "runtime", "store", "adapters"):
        directory = KALHAS_ROOT / subpath
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            assert "domain_packs.pan" not in source, f"PAN import in {path}"
            assert not re.search(r"\bpan\b", source, re.IGNORECASE), f"PAN token in {path}"
            assert "PanV01DomainPack" not in source, f"PAN symbol in {path}"


# ---------------------------------------------------------------------------
# Section B: identity and reproducibility
# ---------------------------------------------------------------------------


def test_two_fresh_packs_are_byte_identical() -> None:
    """Two fresh instances serialize byte-identically."""
    first, second = PanV01DomainPack(), PanV01DomainPack()
    assert first.manifest.model_dump_json() == second.manifest.model_dump_json()
    assert first.mechanism_spec.model_dump_json() == second.mechanism_spec.model_dump_json()
    assert first.release_profile.model_dump_json() == second.release_profile.model_dump_json()
    assert (
        first.step(_verified_request(first)).model_dump_json()
        == second.step(_verified_request(second)).model_dump_json()
    )


def test_manifest_spec_and_profile_hashes_recompute_exactly(pan_pack: PanV01DomainPack) -> None:
    """Every self-covering identity hash recomputes from content."""
    assert manifest_content_hash(pan_pack.manifest) == pan_pack.manifest.content_hash
    assert _self_hash(pan_pack.mechanism_spec) == pan_pack.mechanism_spec.content_hash
    assert _self_hash(pan_pack.release_profile) == pan_pack.release_profile.content_hash


def test_configuration_hash_recomputes_exactly(pan_pack: PanV01DomainPack) -> None:
    """The configuration hash covers the exact immutable configuration."""
    spec = pan_pack.mechanism_spec
    assert set(spec.configuration) == set(CONFIGURATION_KEYS)
    assert _canonical_hash(spec.configuration) == spec.configuration_hash
    assert pan_pack.release_profile.configuration_identity == spec.configuration_hash


def test_all_five_schema_descriptors_reproduce_their_bound_hashes(
    pan_pack: PanV01DomainPack,
) -> None:
    """All five pack-owned schema descriptors rebuild fresh to their digests.

    White-box identity proof: the descriptors are private builder
    functions precisely so no mutable module-level dictionary exists;
    each rebuild returns an equal-but-distinct dictionary (including
    its nested containers) whose canonical hash equals the bound
    mechanism-spec digest.
    """
    from kalhas.domain_packs.pan.pack import (
        _action_schema,
        _configuration_schema,
        _emission_schema,
        _evidence_schema,
        _state_schema,
    )

    spec = pan_pack.mechanism_spec
    for build, declared_id, declared_hash in (
        (_state_schema, spec.state_schema_id, spec.state_schema_hash),
        (_action_schema, spec.action_schema_id, spec.action_schema_hash),
        (_configuration_schema, spec.configuration_schema_id, spec.configuration_schema_hash),
        (_emission_schema, spec.emission_schema_id, spec.emission_schema_hash),
        (_evidence_schema, spec.evidence_schema_id, spec.evidence_schema_hash),
    ):
        descriptor = build()
        again = build()
        assert descriptor == again
        assert descriptor is not again
        assert descriptor["schema_id"] == declared_id
        assert _canonical_hash(descriptor) == declared_hash
        first_nested = [id(value) for value in descriptor.values() if isinstance(value, list)]
        second_nested = [id(value) for value in again.values() if isinstance(value, list)]
        assert not set(first_nested) & set(second_nested)


def test_implementation_hash_matches_mechanism_file_bytes() -> None:
    """The recorded implementation hash is the exact on-disk mechanism.py SHA-256."""
    from kalhas.domain_packs.pan.pack import PAN_IMPLEMENTATION_HASH

    on_disk = hashlib.sha256(MECHANISM_PATH.read_bytes()).hexdigest()
    assert PAN_IMPLEMENTATION_HASH == EXPECTED_IMPLEMENTATION_HASH
    assert on_disk == PAN_IMPLEMENTATION_HASH
    assert PanV01DomainPack().mechanism_spec.implementation_hash == PAN_IMPLEMENTATION_HASH


def test_dependency_lock_hash_matches_unchanged_uv_lock_bytes() -> None:
    """The recorded dependency-lock hash is the exact on-disk uv.lock SHA-256."""
    from kalhas.domain_packs.pan.pack import PAN_DEPENDENCY_LOCK_HASH

    on_disk = hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    assert PAN_DEPENDENCY_LOCK_HASH == EXPECTED_DEPENDENCY_LOCK_HASH
    assert on_disk == PAN_DEPENDENCY_LOCK_HASH
    assert PanV01DomainPack().mechanism_spec.dependency_lock_hash == PAN_DEPENDENCY_LOCK_HASH


def test_declaration_timestamps_are_fixed_and_timezone_aware(pan_pack: PanV01DomainPack) -> None:
    """Declared times are fixed, timezone-aware constants, never the clock."""
    assert pan_pack.mechanism_spec.declared_at.tzinfo is not None
    assert pan_pack.mechanism_spec.declared_at.utcoffset() is not None
    assert pan_pack.release_profile.declared_at == pan_pack.mechanism_spec.declared_at
    assert pan_pack.manifest.created_at.tzinfo is not None
    assert pan_pack.mechanism_spec.declared_at == datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    fresh = PanV01DomainPack()
    assert fresh.mechanism_spec.declared_at == pan_pack.mechanism_spec.declared_at


def test_pan_identifiers_carry_no_random_or_process_dependent_part(
    pan_pack: PanV01DomainPack,
) -> None:
    """Identifiers are stable literals; no uuid, pid, or hostname token."""
    identifiers = [
        pan_pack.manifest.identifier,
        pan_pack.mechanism_spec.identifier,
        pan_pack.release_profile.identifier,
        pan_pack.mechanism_spec.platform_identity.implementation_id,
        pan_pack.mechanism_spec.solver_id,
    ]
    for identifier in identifiers:
        assert "uuid" not in identifier.lower()
        assert str(len(identifier)) not in identifier
    assert pan_pack.mechanism_spec.identifier == PanV01DomainPack().mechanism_spec.identifier
    forbidden = re.compile(r"\b(uuid|uuid4|random|getpid|gethostname|secrets)\b")
    for name in PRODUCTION_PAN_MODULES:
        code = _production_code(name)
        assert not forbidden.search(code), f"random/process identifier in {name}"


def test_release_profile_declares_no_maturity_metadata(pan_pack: PanV01DomainPack) -> None:
    """No maturity value appears in release-profile metadata."""
    flat = json.dumps(pan_pack.release_profile.metadata, sort_keys=True)
    assert flat == json.dumps(
        {"no_real_data": True, "stochastic_draws": 0, "synthetic_only": True}, sort_keys=True
    )


def test_pan_result_identity_is_fully_reproducible_across_reimports() -> None:
    """A fresh module-level rebuild produces the identical release identity."""
    from kalhas.domain_packs.pan.pack import (
        PACK_ID,
        PACK_VERSION,
        SPEC_IDENTIFIER,
        _configuration,
    )

    fresh = PanV01DomainPack()
    assert fresh.manifest.identifier == "manifest-kalhas-pan-0-1-0"
    assert fresh.mechanism_spec.identifier == SPEC_IDENTIFIER
    assert fresh.mechanism_spec.pack_id == PACK_ID
    assert fresh.mechanism_spec.pack_version == PACK_VERSION == "0.1.0"
    rebuilt_configuration = _configuration()
    assert fresh.mechanism_spec.configuration == rebuilt_configuration
    assert _canonical_hash(rebuilt_configuration) == fresh.mechanism_spec.configuration_hash


# ---------------------------------------------------------------------------
# Section C: happy-path mechanism behavior
# ---------------------------------------------------------------------------


def test_direct_step_returns_valid_complete_result(pan_pack: PanV01DomainPack) -> None:
    """A direct step returns a fully verified complete result."""
    result = pan_pack.step(_verified_request(pan_pack))
    assert type(result) is DomainMechanismStepResult
    assert result.request_id == "pan-request-1"
    assert set(result.next_state_payload) == set(STATE_KEYS)
    assert result.emissions[0].sequence_position == 0
    assert result.evidence[0].sequence_position == 0


def test_dispatch_through_the_accepted_seam_succeeds(pan_pack: PanV01DomainPack) -> None:
    """The accepted generic dispatcher verifies and dispatches the pack."""
    request = _verified_request(pan_pack)
    result = dispatch_domain_mechanism_step(pan_pack, request)
    assert type(result) is DomainMechanismStepResult
    assert result.request_content_hash == request.content_hash
    assert result.mechanism_spec_content_hash == pan_pack.mechanism_spec.content_hash
    assert result.release_profile_content_hash == pan_pack.release_profile.content_hash


def test_repeated_identical_requests_produce_byte_identical_results(
    pan_pack: PanV01DomainPack,
) -> None:
    """Repetition is byte-identical across direct and dispatched calls."""
    request = _verified_request(pan_pack)
    first = pan_pack.step(request)
    second = pan_pack.step(request)
    third = dispatch_domain_mechanism_step(pan_pack, request)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.model_dump_json() == third.model_dump_json()


def test_request_and_nested_containers_remain_unchanged(pan_pack: PanV01DomainPack) -> None:
    """The request object graph is untouched by stepping."""
    request = _verified_request(pan_pack)
    snapshot = request.model_dump_json()
    nested_snapshot = json.dumps(request.state_payload, sort_keys=True)
    pan_pack.step(request)
    assert request.model_dump_json() == snapshot
    assert json.dumps(request.state_payload, sort_keys=True) == nested_snapshot


def test_mutating_one_returned_result_contaminates_nothing(pan_pack: PanV01DomainPack) -> None:
    """In-place mutation of one returned result can change nothing else.

    Returned payload dictionaries are detached plain JSON objects, so
    in-place mutation succeeds locally; the actual guarantee is that
    the mutation cannot reach the request, another separately produced
    result, the pack authorities, or any future result of the pack.
    """
    request = _verified_request(pan_pack)
    request_snapshot = request.model_dump_json()
    first = pan_pack.step(request)
    first_snapshot = first.model_dump_json()
    authorities_snapshot = (
        pan_pack.manifest.model_dump_json(),
        pan_pack.mechanism_spec.model_dump_json(),
        pan_pack.release_profile.model_dump_json(),
    )

    second = pan_pack.step(request)
    second.next_state_payload["susceptible"] = 12345
    second.emissions[0].payload["new_exposures"] = 99999
    second.evidence[1].payload["declared_event_order"] = []

    assert request.model_dump_json() == request_snapshot
    assert first.model_dump_json() == first_snapshot
    assert (
        pan_pack.manifest.model_dump_json(),
        pan_pack.mechanism_spec.model_dump_json(),
        pan_pack.release_profile.model_dump_json(),
    ) == authorities_snapshot
    third = pan_pack.step(request)
    assert third.model_dump_json() == first_snapshot
    assert first.next_state_payload is not second.next_state_payload
    assert second.next_state_payload is not third.next_state_payload
    assert first.emissions[0].payload is not second.emissions[0].payload


def test_population_is_conserved_and_counts_non_negative(pan_pack: PanV01DomainPack) -> None:
    """The next state conserves population exactly with non-negative counts."""
    result = pan_pack.step(_verified_request(pan_pack))
    next_state = validate_state_payload(
        result.next_state_payload, _validated_configuration(pan_pack)
    )
    assert next_state["population_total"] == sum(
        next_state[key] for key in STATE_KEYS if key != "population_total"
    )
    assert all(next_state[key] >= 0 for key in STATE_KEYS)


def test_deceased_is_absorbing_across_chained_steps(pan_pack: PanV01DomainPack) -> None:
    """Chaining two steps never resurrects the deceased compartment."""
    configuration = _validated_configuration(pan_pack)
    first = pan_pack.step(_verified_request(pan_pack))
    first_state = validate_state_payload(first.next_state_payload, configuration)
    chained_payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
        state_payload=first.next_state_payload,
        identifier="pan-request-chain-1",
        step_index=1,
    )
    chained = DomainMechanismStepRequest.model_validate(chained_payload)
    second = pan_pack.step(chained)
    second_state = validate_state_payload(second.next_state_payload, configuration)
    assert second_state["deceased"] >= first_state["deceased"]


def test_capacities_are_respected_in_next_state(pan_pack: PanV01DomainPack) -> None:
    """Hospital and ICU occupancy never exceeds the declared capacities."""
    configuration = _validated_configuration(pan_pack)
    result = pan_pack.step(_verified_request(pan_pack))
    next_state = validate_state_payload(result.next_state_payload, configuration)
    assert next_state["hospitalized"] <= configuration["hospital_capacity"]
    assert next_state["intensive_care"] <= configuration["icu_capacity"]


def test_emissions_and_evidence_are_ordered_complete_and_hashed(
    pan_pack: PanV01DomainPack,
) -> None:
    """Emissions/evidence are contiguous, schema-bound, and self-hashed."""
    request = _verified_request(pan_pack)
    result = pan_pack.step(request)
    spec = pan_pack.mechanism_spec
    for position, emission_record in enumerate(result.emissions):
        assert emission_record.sequence_position == position
        assert emission_record.emission_schema_id == spec.emission_schema_id
        assert emission_record.emission_schema_hash == spec.emission_schema_hash
        assert _self_hash(emission_record) == emission_record.content_hash
    for position, evidence_record in enumerate(result.evidence):
        assert evidence_record.sequence_position == position
        assert evidence_record.evidence_schema_id == spec.evidence_schema_id
        assert evidence_record.evidence_schema_hash == spec.evidence_schema_hash
        assert _self_hash(evidence_record) == evidence_record.content_hash
    emission_payloads = [record.payload for record in result.emissions]
    assert emission_payloads[0]["new_exposures"] == 2
    assert "hospital_admissions" in emission_payloads[2]
    assert "icu_admissions" in emission_payloads[4]
    assert "deaths" in emission_payloads[6]
    next_state = validate_state_payload(
        result.next_state_payload, _validated_configuration(pan_pack)
    )
    assert emission_payloads[8]["hospital_occupancy"] == next_state["hospitalized"]
    assert emission_payloads[8]["icu_occupancy"] == next_state["intensive_care"]
    evidence_payloads = [record.payload for record in result.evidence]
    assert evidence_payloads[0]["label"] == "conditional_modeled_outcomes"
    assert evidence_payloads[0]["stochastic_draws"] == 0
    assert evidence_payloads[1]["declared_event_order"] == list(EVENT_IDS)
    assert (
        evidence_payloads[2]["population_total_before"]
        == (evidence_payloads[2]["population_total_after"])
    )
    assert len(evidence_payloads) == 3 + len(EVENT_IDS)


def test_result_copies_request_world_seed_run_step_identity(pan_pack: PanV01DomainPack) -> None:
    """World/seed/realization/run/step identity is copied exactly."""
    request = _verified_request(pan_pack)
    result = pan_pack.step(request)
    assert result.world_version_id == request.world_version_id
    assert result.world_content_hash == request.world_content_hash
    assert result.seed_id == request.seed_id
    assert result.seed_content_hash == request.seed_content_hash
    assert result.realization_id == request.realization_id
    assert result.realization_content_hash == request.realization_content_hash
    assert result.run_id == request.run_id
    assert result.step_index == request.step_index


# ---------------------------------------------------------------------------
# Section D: hand-checkable transition semantics
# ---------------------------------------------------------------------------


def test_round_half_even_resolves_exact_ties_to_even() -> None:
    """Half-even ties resolve exactly as declared (0.5 to 0, 1.5 to 2)."""
    assert round_half_even(1, 2) == 0
    assert round_half_even(3, 2) == 2
    assert round_half_even(5, 2) == 2
    assert round_half_even(7, 2) == 4
    assert round_half_even(1, 3) == 0
    assert round_half_even(2, 3) == 1
    assert round_half_even(4, 3) == 1
    assert round_half_even(5, 3) == 2
    assert round_half_even(100, 1) == 100


def test_effective_transmission_identities_hold() -> None:
    """Zero compliance restores t; full intervention with full compliance is zero."""
    assert effective_transmission_bps(2000, 0, 5000) == 2000
    assert effective_transmission_bps(2000, 10000, 10000) == 0
    assert effective_transmission_bps(3000, 10000, 5000) == 1500
    assert effective_transmission_bps(1000, 2500, 4000) == 900


def test_pinned_fixture_full_hand_calculation(pan_pack: PanV01DomainPack) -> None:
    """One exact fixture hand-calculated from the declared equations.

    State S=900 E=50 I=30 H=15 C=5 R=0 D=0, N=1000, action i=2500.
    Hand calculation (all integer arithmetic):
      E_tx = R(1000*(10^8-2500*4000), 10^8) = R(9.0*10^8, 10^8) = 900
      n1 = min(900, R(900*30*900, 10^7)) = min(900, 2.43) = 2
      n2 = min(50, R(50*3000, 10^4)) = min(50, 15) = 15
      n3 = min(30, R(30*2000, 10^4)=6, 50-15=35) = 6
      n4 = min(30-6, R(30*1000, 10^4)=3) = 3
      n5 = min(15, R(15*5000, 10^4)=8 (7.5 ties to 8), 10-5=5) = 5
      n6 = min(15-5, R(15*2000, 10^4)=3) = 3
      n7 = min(5, R(5*1000, 10^4)=0 (0.5 ties to 0)) = 0
      n8 = min(5-0, R(5*4000, 10^4)=2) = 2
      Next: S'=898 E'=37 I'=36 H'=13 C'=8 R'=8 D'=0 N'=1000.
    """
    configuration = _validated_configuration(pan_pack)
    state = _pin_state()
    transition = compute_transition(state, 2500, configuration)
    assert transition.counts == (2, 15, 6, 3, 5, 3, 0, 2)
    assert transition.source_pools == (900, 50, 30, 24, 15, 10, 5, 5)
    assert transition.next_state == {
        "population_total": 1000,
        "susceptible": 898,
        "exposed": 37,
        "infectious": 36,
        "hospitalized": 13,
        "intensive_care": 8,
        "recovered": 8,
        "deceased": 0,
    }
    request = _verified_request(pan_pack)
    result = pan_pack.step(request)
    next_state = validate_state_payload(result.next_state_payload, configuration)
    assert next_state == transition.next_state
    assert _canonical_hash(next_state) == result.next_state_hash
    evidence_payloads = [record.payload for record in result.evidence]
    counts = [payload["transition_count"] for payload in evidence_payloads[3:]]
    assert counts == [2, 15, 6, 3, 5, 3, 0, 2]
    emission_payloads = [record.payload for record in result.emissions]
    assert emission_payloads[0]["new_exposures"] == 2
    assert emission_payloads[2]["hospital_admissions"] == 6
    assert emission_payloads[4]["icu_admissions"] == 5
    assert emission_payloads[6]["deaths"] == 0
    assert emission_payloads[8]["hospital_occupancy"] == 13
    assert emission_payloads[8]["icu_occupancy"] == 8


def test_exposures_non_increasing_as_intervention_increases(pan_pack: PanV01DomainPack) -> None:
    """Monotonicity: higher intensity never yields more new exposures.

    The same exposure sequence cannot be required to be both ascending
    and descending; the declared monotonicity is non-increasing, with
    the sequence above hand-verifiably nonconstant (3 down to 2).
    """
    configuration = _validated_configuration(pan_pack)
    state = _pin_state()
    exposures = [
        compute_transition(state, intensity, configuration).counts[0]
        for intensity in (0, 1000, 2500, 5000, 7500, 10000)
    ]
    for weaker, stronger in zip(exposures, exposures[1:], strict=False):
        assert stronger <= weaker
    assert exposures[0] > exposures[-1]


def test_maximum_intervention_with_full_compliance_zeroes_transmission(
    pan_pack: PanV01DomainPack,
) -> None:
    """i=10000 with k=10000 gives E_tx=0 and zero new exposures."""
    configuration = dict(_validated_configuration(pan_pack))
    configuration["compliance_bps"] = 10000
    state = _pin_state()
    transition = compute_transition(state, 10000, configuration)
    assert transition.counts[0] == 0
    assert effective_transmission_bps(configuration["transmission_bps"], 10000, 10000) == 0


def test_zero_compliance_makes_intervention_irrelevant(pan_pack: PanV01DomainPack) -> None:
    """k=0: every intensity yields the identical transition."""
    configuration = dict(_validated_configuration(pan_pack))
    configuration["compliance_bps"] = 0
    state = _pin_state(susceptible=500, exposed=10, infectious=5)
    baseline = compute_transition(state, 0, configuration)
    for intensity in (1, 1234, 5000, 9999, 10000):
        assert compute_transition(state, intensity, configuration).counts == baseline.counts


def test_zero_infectious_population_produces_zero_new_exposures(
    pan_pack: PanV01DomainPack,
) -> None:
    """I=0: transmission is exactly zero."""
    configuration = _validated_configuration(pan_pack)
    state = _pin_state(infectious=0)
    assert compute_transition(state, 0, configuration).counts[0] == 0
    assert compute_transition(state, 10000, configuration).counts[0] == 0


def test_zero_exposed_population_produces_zero_progression(
    pan_pack: PanV01DomainPack,
) -> None:
    """E=0: progression is exactly zero."""
    configuration = _validated_configuration(pan_pack)
    state = _pin_state(exposed=0)
    assert compute_transition(state, 0, configuration).counts[1] == 0
    assert compute_transition(state, 10000, configuration).counts[1] == 0


def test_hospital_capacity_caps_admissions_and_overflow_remains(
    pan_pack: PanV01DomainPack,
) -> None:
    """Admissions cap at free capacity; overflow stays infectious, not deleted.

    Hand check with a_h=2000 (default) and all other flows closed on
    state S=900 E=50 I=30 H=2 C=1 (N=983), action i=0: free hospital
    capacity is 3-2=1, so n3=min(30, 6, 1)=1 - the capacity term binds
    (the rate alone would admit 6); the other five infectious remain,
    and H'=2+1-0-0=3 exactly reaches capacity.
    """
    configuration = dict(_validated_configuration(pan_pack))
    configuration["exposed_progression_bps"] = 0
    configuration["infectious_recovery_bps"] = 0
    configuration["icu_admission_bps"] = 0
    configuration["hospital_recovery_bps"] = 0
    configuration["icu_mortality_bps"] = 0
    configuration["icu_recovery_bps"] = 0
    configuration["hospital_capacity"] = 3
    state = _pin_state(infectious=30, hospitalized=2, intensive_care=1)
    transition = compute_transition(state, 0, configuration)
    assert transition.counts[2] == 1
    assert transition.next_state["infectious"] == 30 - 1
    assert transition.next_state["hospitalized"] == 2 + 1


def test_icu_capacity_caps_escalation_and_overflow_remains(
    pan_pack: PanV01DomainPack,
) -> None:
    """Escalation caps at free ICU capacity; overflow stays hospitalized.

    Hand check with a_c=5000 (default) and all other flows closed on
    state S=900 E=50 I=30 H=10 C=1 (N=991), action i=0: free ICU
    capacity is 2-1=1, so n5=min(10, 5, 1)=1 - the capacity term binds
    (the rate alone would escalate 5); the other nine hospitalized
    remain, and C'=1+1-0-0=2 exactly reaches capacity.
    """
    configuration = dict(_validated_configuration(pan_pack))
    configuration["exposed_progression_bps"] = 0
    configuration["hospital_admission_bps"] = 0
    configuration["infectious_recovery_bps"] = 0
    configuration["hospital_recovery_bps"] = 0
    configuration["icu_mortality_bps"] = 0
    configuration["icu_recovery_bps"] = 0
    configuration["icu_capacity"] = 2
    state = _pin_state(hospitalized=10, intensive_care=1)
    transition = compute_transition(state, 0, configuration)
    assert transition.counts[4] == 1
    assert transition.next_state["hospitalized"] == 10 - 1
    assert transition.next_state["intensive_care"] == 1 + 1


def test_no_same_step_cascade_of_newly_entered_compartments(
    pan_pack: PanV01DomainPack,
) -> None:
    """Newly exposed/infectious/admitted never cascade within the step.

    Hand check with p=10000 (all exposed progress), a_h=10000 (all
    pre-step infectious admitted), a_c=10000 (all pre-step hospitalized
    escalate): with E=4, I=3, H=2 the counts are exactly (0, 4, 3, 0,
    2, 0, 0, 0) - the new arrivals do not progress, get admitted, or
    escalate in the same step.
    """
    configuration = dict(_validated_configuration(pan_pack))
    configuration["exposed_progression_bps"] = 10000
    configuration["hospital_admission_bps"] = 10000
    configuration["infectious_recovery_bps"] = 0
    configuration["icu_admission_bps"] = 10000
    configuration["hospital_recovery_bps"] = 0
    configuration["icu_mortality_bps"] = 0
    configuration["icu_recovery_bps"] = 0
    state = _pin_state(susceptible=10, exposed=4, infectious=3, hospitalized=2, intensive_care=1)
    transition = compute_transition(state, 0, configuration)
    assert transition.counts == (0, 4, 3, 0, 2, 0, 0, 0)
    assert transition.next_state == {
        "population_total": 20,
        "susceptible": 10,
        "exposed": 0,
        "infectious": 4,
        "hospitalized": 3,
        "intensive_care": 3,
        "recovered": 0,
        "deceased": 0,
    }
    # Same values, written as explicit hand-calculation ledger lines:
    # S' = 10-0; E' = 4-4+0; I' = 3-3-0+4; H' = 2+3-2-0;
    # C' = 1+2-0-0; R' = 0+0+0+0; D' = 0.


def test_zero_transmission_and_zero_recovery_fixture(pan_pack: PanV01DomainPack) -> None:
    """A second hand-calculated fixture with suppressed flows.

    E_tx = 0 (full intervention, full compliance): n1=0. With
    r_i=r_h=r_c=0, m_c=5000, p=2000, a_h=1000, a_c=5000 on state
    S=100 E=5 I=10 H=4 C=2 R=1 D=0 (N=122):
      n1=0; n2=min(5, R(5*2000,10^4)=1)=1;
      n3=min(10, R(10*1000,10^4)=1, K_h-H=46)=1; n4=0;
      n5=min(4, R(4*5000,10^4)=2, K_c-C=8)=2; n6=0;
      n7=min(2, R(2*5000,10^4)=1)=1; n8=0.
      Next: S'=100 E'=5-1+0=4 I'=10-1-0+1=10 H'=4+1-2-0=3
            C'=2+2-1-0=3 R'=1+0+0+0=1 D'=0+1=1 N'=122.
    """
    configuration = dict(_validated_configuration(pan_pack))
    configuration["exposed_progression_bps"] = 2000
    configuration["hospital_admission_bps"] = 1000
    configuration["infectious_recovery_bps"] = 0
    configuration["icu_admission_bps"] = 5000
    configuration["hospital_recovery_bps"] = 0
    configuration["icu_mortality_bps"] = 5000
    configuration["icu_recovery_bps"] = 0
    configuration["compliance_bps"] = 10000
    state = _pin_state(
        susceptible=100, exposed=5, infectious=10, hospitalized=4, intensive_care=2, recovered=1
    )
    transition = compute_transition(state, 10000, configuration)
    assert transition.counts == (0, 1, 1, 0, 2, 0, 1, 0)
    assert transition.next_state == {
        "population_total": 122,
        "susceptible": 100,
        "exposed": 4,
        "infectious": 10,
        "hospitalized": 3,
        "intensive_care": 3,
        "recovered": 1,
        "deceased": 1,
    }


def test_half_even_ties_resolve_exactly_in_transition_counts(
    pan_pack: PanV01DomainPack,
) -> None:
    """Exact ties inside the transition resolve to the even neighbour.

    With C=1, m_c=5000 gives R(5000,10^4)=0.5 -> 0 (ties to even);
    with C=3, m_c=5000 gives R(15000,10^4)=1.5 -> 2 (ties to even).
    """
    configuration = dict(_validated_configuration(pan_pack))
    configuration["icu_mortality_bps"] = 5000
    configuration["icu_recovery_bps"] = 0
    first = compute_transition(
        _pin_state(infectious=0, hospitalized=0, intensive_care=1), 0, configuration
    )
    assert first.counts[6] == 0
    second = compute_transition(
        _pin_state(infectious=0, hospitalized=0, intensive_care=3), 0, configuration
    )
    assert second.counts[6] == 2


# ---------------------------------------------------------------------------
# Section E: adversarial validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"susceptible": ...},
        {"deceased": ...},
        {"population_total": ...},
        {"unknown_extra": 1},
        {"population_total": True},
        {"population_total": 1000.0},
        {"susceptible": 900.0},
        {"susceptible": "900"},
        {"susceptible": -1},
        {"recovered": -5},
        {"intensive_care": False},
        {"population_total": 999},
    ],
)
def test_invalid_state_payloads_fail_closed(
    pan_pack: PanV01DomainPack, mutation: dict[str, object]
) -> None:
    """Missing/extra keys, bools, floats, strings, negatives: all rejected.

    Every collected case executes; the previously skipped
    conservation-breaking population mutation is a distinct executed
    adversary here.
    """
    _expect_pan_rejection(pan_pack, state_payload=_state_variant(mutation))


@pytest.mark.parametrize(
    "action_payload",
    [
        {},
        {"intervention_intensity_bps": 2500, "extra": 1},
        {"unknown": 1},
        {"intervention_intensity_bps": True},
        {"intervention_intensity_bps": 25.0},
        {"intervention_intensity_bps": "2500"},
        {"intervention_intensity_bps": -1},
        {"intervention_intensity_bps": 10001},
        {"intervention_intensity_bps": BPS_MAX + 1},
    ],
)
def test_invalid_action_payloads_fail_closed(
    pan_pack: PanV01DomainPack, action_payload: dict[str, object]
) -> None:
    """Wrong action types, ranges, and key sets are all rejected."""
    with pytest.raises(PanDomainPackError):
        validate_action_payload(action_payload)
    if action_payload:
        _expect_pan_rejection(pan_pack, action_payload=action_payload)


@pytest.mark.parametrize(
    "key, value",
    [
        ("transmission_bps", -1),
        ("transmission_bps", BPS_MAX + 1),
        ("transmission_bps", True),
        ("transmission_bps", 1.0),
        ("transmission_bps", "1000"),
        ("compliance_bps", -1),
        ("compliance_bps", 10001),
        ("hospital_capacity", -1),
        ("icu_capacity", -1),
        ("hospital_capacity", True),
        ("icu_capacity", 10.0),
    ],
)
def test_invalid_configuration_values_fail_closed(
    pan_pack: PanV01DomainPack, key: str, value: object
) -> None:
    """Invalid rate/compliance/capacity values are rejected."""
    configuration = _validated_configuration(pan_pack)
    adjusted = _configuration_variant(pan_pack, key, value)
    with pytest.raises(PanDomainPackError):
        validate_configuration_payload(adjusted, configuration)
    _expect_pan_rejection(pan_pack, configuration_payload=adjusted)


@pytest.mark.parametrize("drop_key", [True, False])
def test_configuration_key_set_mismatch_fails_closed(
    pan_pack: PanV01DomainPack, drop_key: bool
) -> None:
    """Missing or extra configuration keys are rejected before comparison."""
    configuration = _validated_configuration(pan_pack)
    adjusted: dict[str, object] = dict(configuration)
    if drop_key:
        del adjusted["compliance_bps"]
    else:
        adjusted["unexpected_extra"] = 1
    with pytest.raises(PanDomainPackError):
        validate_configuration_payload(adjusted, configuration)
    _expect_pan_rejection(pan_pack, configuration_payload=adjusted)


def test_changed_configuration_under_same_identity_fails_closed(
    pan_pack: PanV01DomainPack,
) -> None:
    """A self-consistently rehashed changed configuration is rejected.

    The mutated configuration payload is correctly hashed and the
    request content hash is resealed, so the request is fully
    self-consistent; only the identity comparison against the fixed
    mechanism-specification configuration can reject it, both directly
    and through the dispatcher.
    """
    adjusted = _configuration_variant(pan_pack, "transmission_bps", 1001)
    _expect_pan_rejection(pan_pack, configuration_payload=adjusted)


def test_broken_population_conservation_fails_closed(pan_pack: PanV01DomainPack) -> None:
    """A state whose compartments do not sum to the total is rejected."""
    state = _pin_state()
    state["population_total"] = state["population_total"] + 1
    _expect_pan_rejection(pan_pack, state_payload=state)


@pytest.mark.parametrize(
    "key, capacity_key",
    [("hospitalized", "hospital_capacity"), ("intensive_care", "icu_capacity")],
)
def test_occupancy_above_capacity_fails_closed(
    pan_pack: PanV01DomainPack, key: str, capacity_key: str
) -> None:
    """Occupancy above the declared capacity is rejected, never corrected."""
    configuration = _validated_configuration(pan_pack)
    adjusted_configuration = dict(configuration)
    adjusted_configuration[capacity_key] = 1
    state = _pin_state()
    state[key] = 5
    state["population_total"] = state["population_total"] + 4
    with pytest.raises(PanDomainPackError):
        validate_state_payload(state, adjusted_configuration)
    _expect_pan_rejection(
        pan_pack, state_payload=state, configuration_payload=adjusted_configuration
    )


def _exogenous_entry() -> MechanismExogenousInput:
    """One coordinate-complete synthetic exogenous input for the request."""
    return MechanismExogenousInput(
        identifier="exogenous-1",
        stream="stream-1",
        variable="variable-1",
        entity_id="entity-1",
        draw_index=0,
        value_kind="integer",
        value=1,
        content_hash=_canonical_hash(1),
        world_version_id="world-pan-v1",
        world_content_hash="b" * 64,
        seed_id="seed-pan-1",
        seed_content_hash="c" * 64,
        run_id="run-pan-1",
        step_index=0,
    )


def test_non_empty_exogenous_input_is_rejected_not_ignored(
    pan_pack: PanV01DomainPack,
) -> None:
    """Non-empty exogenous input fails closed; it is never silently ignored."""
    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    payload["exogenous_inputs"] = [_exogenous_entry().model_dump(mode="python")]
    payload["content_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    request = DomainMechanismStepRequest.model_validate(payload)
    with pytest.raises(PanDomainPackError):
        pan_pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pan_pack, request)


def test_foreign_schema_identities_fail_closed(pan_pack: PanV01DomainPack) -> None:
    """Copied schema ids and hashes must equal the spec exactly."""
    for field in (
        "state_schema_id",
        "state_schema_hash",
        "action_schema_id",
        "action_schema_hash",
        "configuration_schema_id",
        "configuration_schema_hash",
    ):
        payload = _request_payload(
            pan_pack.mechanism_spec,
            pan_pack.release_profile.identifier,
            pan_pack.release_profile.content_hash,
        )
        payload[field] = "0" * 64 if field.endswith("hash") else "foreign-schema"
        request = _finalized_mutated_request(payload)
        with pytest.raises(PanDomainPackError):
            pan_pack.step(request)


@pytest.mark.parametrize("hash_field", ["state_hash", "action_hash", "configuration_hash"])
def test_contract_invalid_malformed_hashes_fail_validation(
    pan_pack: PanV01DomainPack, hash_field: str
) -> None:
    """Malformed (non-64-hex-character) hashes never construct a request.

    The v1 contract boundary rejects the malformed digest during
    Pydantic validation, before any mechanism code runs.
    """
    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    payload[hash_field] = "not-even-hex"
    with pytest.raises(ValidationError):
        DomainMechanismStepRequest.model_validate(payload)


@pytest.mark.parametrize(
    "hash_field, payload_field",
    [
        ("state_hash", "state_payload"),
        ("action_hash", "action_payload"),
        ("configuration_hash", "configuration_payload"),
    ],
)
def test_well_formed_false_payload_hashes_fail_verification(
    pan_pack: PanV01DomainPack, hash_field: str, payload_field: str
) -> None:
    """A valid-shape but false 64-character hash is rejected by verification.

    Unlike the malformed digests above, this hash has exactly the
    contract shape, so the request constructs successfully and must be
    rejected by the PAN and dispatcher payload verification itself.
    """
    assert len(_FAKE_HEX_64) == 64
    assert _FAKE_HEX_64.lower() == _FAKE_HEX_64
    assert pan_pack.mechanism_spec.content_hash != _FAKE_HEX_64
    assert pan_pack.release_profile.content_hash != _FAKE_HEX_64
    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    assert payload[payload_field] is not None
    payload[hash_field] = _FAKE_HEX_64
    request = _finalized_mutated_request(payload)
    with pytest.raises(PanDomainPackError):
        pan_pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pan_pack, request)


def test_malformed_request_identity_fails_closed(pan_pack: PanV01DomainPack) -> None:
    """Foreign spec/profile references and tampered content hashes fail."""
    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    payload["mechanism_spec_id"] = "other-spec"
    with pytest.raises(PanDomainPackError):
        pan_pack.step(_finalized_mutated_request(payload))

    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    payload["release_profile_content_hash"] = _FAKE_HEX_64
    with pytest.raises(PanDomainPackError):
        pan_pack.step(_finalized_mutated_request(payload))

    payload = _request_payload(
        pan_pack.mechanism_spec,
        pan_pack.release_profile.identifier,
        pan_pack.release_profile.content_hash,
    )
    payload["content_hash"] = _FAKE_HEX_64
    with pytest.raises(PanDomainPackError):
        pan_pack.step(DomainMechanismStepRequest.model_validate(payload))
    # A tampered overall digest fails the self-covering recheck above even
    # though the request otherwise validates.


def test_mutating_one_returned_result_cannot_alter_the_request(
    pan_pack: PanV01DomainPack,
) -> None:
    """Post-step mutation of a returned payload leaves the request intact."""
    request = _verified_request(pan_pack)
    snapshot = request.model_dump_json()
    result = pan_pack.step(request)
    result.next_state_payload["susceptible"] = 12345
    result.emissions[0].payload["new_exposures"] = 99999
    assert request.model_dump_json() == snapshot


def test_non_finite_and_arbitrary_object_values_fail_closed(
    pan_pack: PanV01DomainPack,
) -> None:
    """Float payloads and arbitrary objects cannot reach the mechanism."""
    configuration = _validated_configuration(pan_pack)
    with pytest.raises(PanDomainPackError):
        validate_state_payload({"susceptible": float("nan")}, configuration)
    with pytest.raises(PanDomainPackError):
        validate_action_payload({"intervention_intensity_bps": object()})
    with pytest.raises(PanDomainPackError):
        validate_action_payload({"intervention_intensity_bps": float("inf")})
    with pytest.raises(PanDomainPackError):
        validate_configuration_payload({key: object() for key in CONFIGURATION_KEYS}, configuration)


def _mutate_spec_configuration(pack: PanV01DomainPack) -> None:
    pack.mechanism_spec.configuration["transmission_bps"] = 9999


def _mutate_spec_metadata(pack: PanV01DomainPack) -> None:
    pack.mechanism_spec.metadata["synthetic_only"] = False


def _mutate_manifest_metadata(pack: PanV01DomainPack) -> None:
    pack.manifest.metadata["synthetic_only"] = False


def _mutate_profile_metadata(pack: PanV01DomainPack) -> None:
    pack.release_profile.metadata["no_real_data"] = False


@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_spec_configuration,
        _mutate_spec_metadata,
        _mutate_manifest_metadata,
        _mutate_profile_metadata,
    ],
)
def test_direct_step_rejects_mutated_nested_authority(
    mutate: Callable[[PanV01DomainPack], None],
) -> None:
    """Direct step and dispatch both fail closed on any mutated authority.

    The request is rebuilt against the already-mutated pack, so the
    rejection is the pack's own authority gate (the mutated content
    still recomputes its self-consistent state but no longer matches
    the declared release identity), not the request's copied
    profile/spec reference check.
    """
    pack = PanV01DomainPack()
    request = _verified_request(pack)
    mutation_callable = mutate
    mutation_callable(pack)
    tampered_request = _verified_request(pack)
    with pytest.raises(PanDomainPackError):
        pack.step(request)
    with pytest.raises(PanDomainPackError):
        pack.step(tampered_request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_direct_step_rejects_replaced_manifest_authority() -> None:
    """A self-consistently replaced manifest fails closed before execution.

    A second request rebuilt against the tampered pack keeps the original
    profile hash, so the prebuilt request and the rebuilt request are
    rejected for different reasons - both fail closed before execution.
    """
    pack = PanV01DomainPack()
    request = _verified_request(pack)
    forged = pack.manifest.model_copy(update={"pack_id": "other-pack"})
    forged = forged.model_copy(update={"content_hash": manifest_content_hash(forged)})
    pack.manifest = forged
    tampered_request = _verified_request(pack)
    assert tampered_request.release_profile_content_hash == request.release_profile_content_hash
    with pytest.raises(PanDomainPackError):
        pack.step(request)
    with pytest.raises(PanDomainPackError):
        pack.step(tampered_request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_direct_step_rejects_replaced_spec_authority() -> None:
    """A self-consistently replaced mechanism spec fails closed."""
    pack = PanV01DomainPack()
    request = _verified_request(pack)
    forged = pack.mechanism_spec.model_copy(update={"mechanism_id": "other-mechanism"})
    dumped: dict[str, object] = forged.model_dump(mode="json")
    del dumped["content_hash"]
    forged = forged.model_copy(update={"content_hash": _canonical_hash(dumped)})
    pack.mechanism_spec = forged
    with pytest.raises(PanDomainPackError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_direct_step_rejects_replaced_profile_authority() -> None:
    """A self-consistently replaced release profile fails closed.

    The replacement embeds the pack's own manifest and spec and carries
    a correctly recomputed self hash, so only the pack's authority gate
    can reject it.
    """
    pack = PanV01DomainPack()
    request = _verified_request(pack)
    forged = pack.release_profile.model_copy(
        update={"metadata": {"synthetic_only": True, "no_real_data": False}}
    )
    dumped: dict[str, object] = forged.model_dump(mode="json")
    del dumped["content_hash"]
    forged = forged.model_copy(update={"content_hash": _canonical_hash(dumped)})
    pack.release_profile = forged
    tampered_request = _verified_request(pack)
    with pytest.raises(PanDomainPackError):
        pack.step(request)
    with pytest.raises(PanDomainPackError):
        pack.step(tampered_request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_mutated_authority_cannot_contaminate_a_fresh_instance(
    pan_pack: PanV01DomainPack,
) -> None:
    """A mutated pack leaves a fresh instance byte-identical and green.

    Schema descriptors and the configuration are rebuilt per instance
    from immutable scalar/tuple declarations, so in-place mutation of
    one pack's reachable containers cannot leak into any later pack.
    """
    pristine = (
        pan_pack.manifest.model_dump_json(),
        pan_pack.mechanism_spec.model_dump_json(),
        pan_pack.release_profile.model_dump_json(),
    )
    pan_pack.mechanism_spec.configuration["transmission_bps"] = 9999
    pan_pack.manifest.metadata["synthetic_only"] = False
    pan_pack.release_profile.metadata["no_real_data"] = False

    fresh = PanV01DomainPack()
    assert (
        fresh.manifest.model_dump_json(),
        fresh.mechanism_spec.model_dump_json(),
        fresh.release_profile.model_dump_json(),
    ) == pristine
    # Direct step on the mutated instance still fails closed.
    pristine_request = _verified_request(fresh)
    with pytest.raises(PanDomainPackError):
        pan_pack.step(pristine_request)


def test_dispatcher_rejects_tampered_pack_identity(pan_pack: PanV01DomainPack) -> None:
    """The dispatcher still rejects a forged manifest under PAN identity."""
    request = _verified_request(pan_pack)
    forged_manifest = pan_pack.manifest.model_copy(update={"pack_id": "other-pack"})
    forged_manifest = forged_manifest.model_copy(
        update={"content_hash": manifest_content_hash(forged_manifest)}
    )

    class _ForgedPack:
        manifest = forged_manifest
        release_profile = pan_pack.release_profile
        mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

        def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
            return pan_pack.step(request)

    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(_ForgedPack(), request)


# ---------------------------------------------------------------------------
# Section E2: coordinated authority-replacement adversaries
# ---------------------------------------------------------------------------
#
# Every adversary below first builds a *coordinated* forged authority
# chain - each forged object carries a correctly recomputed configuration,
# schema, and self-covering hash, so every ordinary hash verification
# passes - and the tests prove the pack fails closed anyway, because the
# forged chain is self-consistent but is not the exact frozen ``kalhas-pan``
# v0.1 release.  Only the pristine-rebuild equality anchors inside the
# production authority gate can reject these chains.


def _rehash_spec(spec: DomainMechanismSpec) -> DomainMechanismSpec:
    """Recompute the self-covering content hash of a forged spec."""
    dumped: dict[str, object] = spec.model_dump(mode="json")
    del dumped["content_hash"]
    return spec.model_copy(update={"content_hash": _canonical_hash(dumped)})


def _rehash_profile(profile: ModelPackReleaseProfile) -> ModelPackReleaseProfile:
    """Recompute the self-covering content hash of a forged profile."""
    dumped: dict[str, object] = profile.model_dump(mode="json")
    del dumped["content_hash"]
    return profile.model_copy(update={"content_hash": _canonical_hash(dumped)})


#: Spec-level coordinated replacement keys.  Each mutation is applied via
#: ``model_copy(update=...)`` to the deep-copied frozen spec, then the
#: forged spec is rehashed and embedded into a rehashed forged release
#: profile.
_SPEC_MUTATIONS: dict[str, Callable[[DomainMechanismSpec], DomainMechanismSpec]] = {
    "transmission_bps": lambda spec: spec.model_copy(
        update={
            "configuration": {**spec.configuration, "transmission_bps": 9999},
            "configuration_hash": sha256_hex(
                canonical_json({**spec.configuration, "transmission_bps": 9999})
            ),
        }
    ),
    "solver_version": lambda spec: spec.model_copy(update={"solver_version": "9.9.9"}),
    "implementation_hash": lambda spec: spec.model_copy(
        update={
            "implementation_hash": "e" * 64,
            "platform_identity": spec.platform_identity.model_copy(
                update={"implementation_hash": "e" * 64}
            ),
        }
    ),
    "event_order": lambda spec: spec.model_copy(
        update={"event_order": tuple(reversed(spec.event_order))}
    ),
    "state_schema_hash": lambda spec: spec.model_copy(update={"state_schema_hash": "f" * 64}),
    "platform_solver": lambda spec: spec.model_copy(
        update={
            "solver_version": "9.9.9",
            "platform_identity": spec.platform_identity.model_copy(
                update={"solver_version": "9.9.9"}
            ),
        }
    ),
}


def _forged_spec_chain(
    pan_pack: PanV01DomainPack, key: str
) -> tuple[DomainMechanismSpec, ModelPackReleaseProfile]:
    """One coordinated forged spec chain with correctly recomputed hashes.

    Applies the named release-critical field replacement to a deep copy
    of the frozen spec via ``model_copy(update=...)`` - keeping every
    contract-level internal consistency rule intact - recomputes the
    spec self-covering hash, embeds the forged spec into a forged
    release profile carrying the matching configuration identity, and
    recomputes the profile hash.
    """
    spec = _SPEC_MUTATIONS[key](pan_pack.mechanism_spec)
    spec = _rehash_spec(spec)
    profile = pan_pack.release_profile.model_copy(
        update={"mechanism_spec": spec, "configuration_identity": spec.configuration_hash}
    )
    return spec, _rehash_profile(profile)


def _forged_profile_chain(
    pan_pack: PanV01DomainPack, key: str
) -> tuple[DomainMechanismSpec, ModelPackReleaseProfile]:
    """One coordinated forged profile chain with a recomputed profile hash.

    The mechanism spec stays exactly the frozen release spec; the named
    release-level profile field is replaced on a deep copy and the
    profile self-covering hash is correctly recomputed.
    """
    profile = pan_pack.release_profile.model_copy(deep=True)
    forged_limitations = profile.limitations + (
        ModelPackLimitation(
            limitation_id="limitation-forged",
            statement="forged limitation injected by the coordinated adversary",
        ),
    )
    forged_scope = ModelPackScope(
        decision_questions=("forged_decision_question",),
        intended_users=("forged_user",),
        horizon="forged_horizon",
        resolution="forged_resolution",
        validity_envelope="forged validity envelope statement",
    )
    forged_provenance = ModelPackProvenance(
        author_id="forged-author",
        method="forged_method",
        statement="forged provenance statement",
    )
    forged_resources = ModelPackResourceEnvelope(
        max_memory_megabytes=999,
        max_cpu_seconds=999,
        memory_unit="MiB",
        cpu_unit="seconds",
    )
    forged_fields: dict[str, object] = {
        "limitations": forged_limitations,
        "scope": forged_scope,
        "provenance": forged_provenance,
        "resource_envelope": forged_resources,
    }
    if key not in forged_fields:
        raise AssertionError(f"unknown coordinated profile replacement key: {key}")
    profile = profile.model_copy(update={key: forged_fields[key]})
    return pan_pack.mechanism_spec, _rehash_profile(profile)


def _install_forged_chain(
    pan_pack: PanV01DomainPack, spec: DomainMechanismSpec, profile: ModelPackReleaseProfile
) -> tuple[DomainPackManifest, DomainMechanismSpec, ModelPackReleaseProfile]:
    """Install the forged spec/profile authorities and return the originals."""
    original = (pan_pack.manifest, pan_pack.mechanism_spec, pan_pack.release_profile)
    pan_pack.mechanism_spec = spec
    pan_pack.release_profile = profile
    return original


def _restore_authorities(
    pan_pack: PanV01DomainPack,
    original: tuple[DomainPackManifest, DomainMechanismSpec, ModelPackReleaseProfile],
) -> None:
    """Restore the pristine authorities so forged state cannot leak."""
    pan_pack.manifest, pan_pack.mechanism_spec, pan_pack.release_profile = original


def _prove_coordinated_chain_is_internally_consistent(
    pan_pack: PanV01DomainPack, spec: DomainMechanismSpec, profile: ModelPackReleaseProfile
) -> None:
    """Prove the installed forged chain is fully internally self-consistent.

    Every recomputed-hash check the pack's gate performs - the manifest
    content hash, both self-covering hashes, the profile's embedded
    manifest/spec equality, and the configuration identity against the
    configuration hash - passes on the forged chain, and a request built
    against the forged authorities is itself hash-consistent, so a later
    rejection is attributable only to the exact-release pinning and never
    to an ordinary hash mismatch.
    """
    assert manifest_content_hash(pan_pack.manifest) == pan_pack.manifest.content_hash
    assert _self_hash(spec) == spec.content_hash
    assert _self_hash(profile) == profile.content_hash
    assert profile.manifest == pan_pack.manifest
    assert profile.mechanism_spec == spec
    assert profile.configuration_identity == spec.configuration_hash
    _verified_request(pan_pack)


def _expect_coordinated_rejection(
    pan_pack: PanV01DomainPack, spec: DomainMechanismSpec, profile: ModelPackReleaseProfile
) -> None:
    """Direct step and dispatcher both reject the coordinated forged chain.

    Direct step must reject before any mechanism execution, and the
    dispatcher must translate its own authority verification of the
    supplied manifest/profile (and the pack's internal gate reached
    through ``step``) into the single typed dispatch error.
    """
    forged_request = _verified_request(pan_pack)
    with pytest.raises(PanDomainPackError):
        pan_pack.step(forged_request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pan_pack, forged_request)


def _run_coordinated_replacement(pan_pack: PanV01DomainPack, key: str) -> None:
    """The named coordinated replacement is self-consistent yet rejected."""
    replacement_key: str = key
    if replacement_key in _SPEC_MUTATIONS:
        spec, profile = _forged_spec_chain(pan_pack, replacement_key)
    else:
        spec, profile = _forged_profile_chain(pan_pack, replacement_key)
    assert (spec, profile) != (
        pan_pack.mechanism_spec,
        pan_pack.release_profile,
    )
    original = _install_forged_chain(pan_pack, spec, profile)
    try:
        _prove_coordinated_chain_is_internally_consistent(pan_pack, spec, profile)
        _expect_coordinated_rejection(pan_pack, spec, profile)
    finally:
        _restore_authorities(pan_pack, original)


@pytest.mark.parametrize(
    "key",
    [
        "transmission_bps",
        "solver_version",
        "implementation_hash",
        "event_order",
        "state_schema_hash",
        "platform_solver",
    ],
)
def test_coordinated_spec_replacements_fail_closed(key: str) -> None:
    """Coordinated rehashed spec-field replacements are rejected as non-frozen.

    A fresh pack is used per case so no other test's deliberate
    contamination of a shared instance can mask the release pinning.
    """
    _run_coordinated_replacement(PanV01DomainPack(), key)


@pytest.mark.parametrize(
    "key",
    ["limitations", "scope", "provenance", "resource_envelope"],
)
def test_coordinated_profile_replacements_fail_closed(key: str) -> None:
    """Coordinated rehashed profile-field replacements are rejected as non-frozen."""
    _run_coordinated_replacement(PanV01DomainPack(), key)


def test_coordinated_configuration_replacement_fails_closed() -> None:
    """A rehashed ``transmission_bps`` 9999 chain is rejected as non-frozen.

    The attacker changes the transmission rate, recomputes the
    configuration hash, rehashes the mechanism spec, embeds the forged
    spec and configuration identity into a rehashed release profile, and
    rebuilds a hash-consistent request.  Every forged hash recomputes;
    both execution surfaces still fail closed.
    """
    pan_pack = PanV01DomainPack()
    spec = pan_pack.mechanism_spec.model_copy(
        update={
            "configuration": {**pan_pack.mechanism_spec.configuration, "transmission_bps": 9999},
            "configuration_hash": sha256_hex(
                canonical_json({**pan_pack.mechanism_spec.configuration, "transmission_bps": 9999})
            ),
        }
    )
    assert spec.configuration["transmission_bps"] == 9999
    spec = _rehash_spec(spec)
    assert spec.configuration_hash != pan_pack.mechanism_spec.configuration_hash
    profile = pan_pack.release_profile.model_copy(
        update={"mechanism_spec": spec, "configuration_identity": spec.configuration_hash}
    )
    profile = _rehash_profile(profile)
    assert profile.mechanism_spec == spec
    original = _install_forged_chain(pan_pack, spec, profile)
    try:
        _prove_coordinated_chain_is_internally_consistent(pan_pack, spec, profile)
        _expect_coordinated_rejection(pan_pack, spec, profile)
    finally:
        _restore_authorities(pan_pack, original)


def test_coordinated_solver_replacement_fails_closed() -> None:
    """A coordinated ``solver_version`` chain is rejected as non-frozen."""
    pan_pack = PanV01DomainPack()
    forged_spec = pan_pack.mechanism_spec.model_copy(update={"solver_version": "9.9.9"})
    assert forged_spec.solver_version == "9.9.9"
    assert forged_spec.solver_version != pan_pack.mechanism_spec.solver_version
    spec = _rehash_spec(forged_spec)
    profile = pan_pack.release_profile.model_copy(
        update={"mechanism_spec": spec, "configuration_identity": spec.configuration_hash}
    )
    profile = _rehash_profile(profile)
    assert profile.mechanism_spec == spec
    original = _install_forged_chain(pan_pack, spec, profile)
    try:
        _prove_coordinated_chain_is_internally_consistent(pan_pack, spec, profile)
        _expect_coordinated_rejection(pan_pack, spec, profile)
    finally:
        _restore_authorities(pan_pack, original)


def test_coordinated_manifest_chain_replacement_fails_closed() -> None:
    """A fully rehashed manifest chain is rejected as non-frozen.

    The manifest description is altered, the manifest hash recomputed,
    the spec's manifest identity updated and rehashed, and the forged
    manifest and spec embedded into a rehashed profile: the complete
    chain agrees internally and still fails closed as a non-release.
    """
    pan_pack = PanV01DomainPack()
    manifest = pan_pack.manifest.model_copy(update={"description": "totally benign pack"})
    manifest = manifest.model_copy(update={"content_hash": manifest_content_hash(manifest)})
    assert manifest.description == "totally benign pack"
    assert manifest.description != pan_pack.manifest.description
    assert manifest_content_hash(manifest) == manifest.content_hash

    spec = pan_pack.mechanism_spec.model_copy(
        update={
            "manifest_id": manifest.identifier,
            "manifest_content_hash": manifest.content_hash,
        }
    )
    spec = _rehash_spec(spec)
    assert spec.manifest_content_hash == manifest.content_hash
    profile = pan_pack.release_profile.model_copy(
        update={
            "manifest": manifest,
            "manifest_id": manifest.identifier,
            "manifest_content_hash": manifest.content_hash,
            "mechanism_spec": spec,
            "configuration_identity": spec.configuration_hash,
        }
    )
    profile = _rehash_profile(profile)
    assert profile.manifest == manifest
    assert profile.mechanism_spec == spec

    original = (pan_pack.manifest, pan_pack.mechanism_spec, pan_pack.release_profile)
    pan_pack.manifest = manifest
    pan_pack.mechanism_spec = spec
    pan_pack.release_profile = profile
    try:
        _prove_coordinated_chain_is_internally_consistent(pan_pack, spec, profile)
        _expect_coordinated_rejection(pan_pack, spec, profile)
    finally:
        pan_pack.manifest, pan_pack.mechanism_spec, pan_pack.release_profile = original


def test_mutated_pack_protocol_attribute_fails_closed() -> None:
    """A mutated pack-level protocol attribute is rejected before execution.

    The mutation bypasses the ``Literal["1.0.0"]`` annotation at runtime
    while remaining a plain exact ``str``, so only the production
    equality check against the frozen protocol constant can reject it.
    """
    pan_pack = PanV01DomainPack()
    original_protocol = pan_pack.mechanism_protocol_version
    request = _verified_request(pan_pack)
    forged_protocol: str = "9.9.9"
    assert forged_protocol != original_protocol
    object.__setattr__(pan_pack, "mechanism_protocol_version", forged_protocol)
    try:
        assert pan_pack.mechanism_protocol_version == forged_protocol
        with pytest.raises(PanDomainPackError):
            pan_pack.step(request)
        with pytest.raises(DomainMechanismDispatchError):
            dispatch_domain_mechanism_step(pan_pack, request)
    finally:
        pan_pack.mechanism_protocol_version = original_protocol


# ---------------------------------------------------------------------------
# Section F: static purity and truthful scope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,label",
    [
        (r"\b(open|read_text|write_text|read_bytes|write_bytes|Path\(|mkdir|unlink)\b", "fs"),
        (r"\b(requests|urllib|socket|subprocess|httpx|http\.client|ftplib)\b", "network"),
        (r"\b(os\.environ|getenv|environ\[)\b", "environment"),
        (
            r"\b(datetime\.now|datetime\.today|now\(|today\(|time\.time|monotonic\(|"
            r"perf_counter|utcnow)\b",
            "clock",
        ),
        (r"\b(random|getrandbits|randint|shuffle|seed|SystemRandom)\b", "rng"),
        (r"\b(importlib|__import__|import_module|exec\(|eval\()\b", "dynamic-import"),
        (r"\b(sqlite3|psycopg|pymysql|sqlalchemy)\b", "database"),
    ],
)
def test_pan_production_source_is_pure(pattern: str, label: str) -> None:
    """Production PAN source contains no environment-facing access."""
    forbidden = re.compile(pattern)
    for name in PRODUCTION_PAN_MODULES:
        assert not forbidden.search(_production_code(name)), f"{label} access in {name}"


def test_pan_production_has_no_mutable_module_level_container_authority() -> None:
    """No mutable module-level dict/list/set authority exists in pack.py.

    The real guarantee (not a ``global``-statement regex): the runtime
    namespace of the fully imported pack module contains no mutable
    container at all, so schema descriptors and the configuration can
    only ever be produced fresh by the private builders.
    """
    import kalhas.domain_packs.pan.pack as pack_module

    mutable = [
        name
        for name, value in vars(pack_module).items()
        if not name.startswith("__") and isinstance(value, (dict, list, set))
    ]
    assert not mutable, f"mutable module-level container authority: {mutable}"


def test_pan_production_source_imports_are_allowlisted() -> None:
    """Every import in production PAN source is on the declared allowlist.

    ``kalhas.domain_packs.pan.pack`` is the legitimate dedicated-
    subpackage import of the public entry point.
    """
    allowed_modules = {
        "__future__",
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        "pydantic",
        "kalhas.application.domain_pack_registry",
        "kalhas.application.hashing",
        "kalhas.contracts.v1.domain_mechanism",
        "kalhas.contracts.v1.domain_pack",
        "kalhas.contracts.v1.model_pack",
        "kalhas.contracts.v1.shared",
        "kalhas.domain_packs.pan.mechanism",
        "kalhas.domain_packs.pan.pack",
    }
    for name in PRODUCTION_PAN_MODULES:
        tree = ast.parse((PAN_PACKAGE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name in allowed_modules, f"{name}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") in allowed_modules, f"{name}: from {node.module}"


def test_pan_production_source_has_no_forbidden_symbols() -> None:
    """No persistence/API/runtime/NEXUS/LEGION/policy/scheduler symbols."""
    forbidden_tokens = (
        "InMemoryScenarioStore",
        "nexus",
        "legion",
        "scheduler",
        "strategy_comparison",
        "policy_selection",
        "register_manifest",
        "fastapi",
        "APIRouter",
        "run_campaign",
        "httpx",
        "requests",
    )
    for name in PRODUCTION_PAN_MODULES:
        code = _production_code(name).lower()
        for token in forbidden_tokens:
            assert token not in code, f"forbidden token {token!r} in {name}"


def test_pan_names_no_external_simulator_or_real_dataset() -> None:
    """No external simulator name and no real-data reference anywhere."""
    for name in PRODUCTION_PAN_MODULES:
        source = (PAN_PACKAGE / name).read_text(encoding="utf-8").lower()
        for token in _FREEZING_EXTERNAL_NAMES:
            assert token not in source, f"external simulator/dependency {token!r} in {name}"


def test_pan_tests_never_create_assurance_or_catalogue_artifacts() -> None:
    """No assurance profile, catalogue entry, or maturity is created."""
    assert not hasattr(PanV01DomainPack, "assurance_profile")
    assert not hasattr(PanV01DomainPack, "catalogue_entry")
    fresh = PanV01DomainPack()
    assert not hasattr(fresh, "assurance_profile")
    assert not hasattr(fresh, "catalogue_entry")
    assert getattr(PanV01DomainPack, "assurance_profile", None) is None
    assert getattr(PanV01DomainPack, "catalogue_entry", None) is None
    assert getattr(fresh, "assurance_profile", None) is None
    assert getattr(fresh, "catalogue_entry", None) is None
    assert not isinstance(getattr(fresh, "assurance_profile", None), ModelPackAssuranceProfile)
    assert not isinstance(getattr(fresh, "catalogue_entry", None), ModelPackCatalogueEntry)
    code = _production_code("pack.py")
    assert "ModelPackAssuranceProfile(" not in code
    assert "ModelPackCatalogueEntry(" not in code
    assert "maturity" not in code.lower()
    for maturity in _MATURITY_VOCABULARY:
        assert maturity not in code


def test_registry_and_schema_cardinality_remain_exactly_61() -> None:
    """The public registry and the schema directory both stay at 61."""
    assert len(PUBLIC_CONTRACTS) == 61
    schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    assert len(schema_files) == 61


def test_generated_schemas_remain_byte_equal_to_checked_in_files() -> None:
    """Generated schema bytes equal the checked-in artifacts."""
    generated = generate_schemas()
    assert len(generated) == 61
    for name, rendered in generated.items():
        on_disk = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        assert on_disk == rendered, f"{name} drifted from the generated schema"


def test_existing_kernel_boundary_stays_green_without_pan_vocabulary() -> None:
    """Kernel non-pack modules still carry no PAN vocabulary."""
    vocabulary = re.compile(
        r"(pandemic|compartmen|infection|epidemi|pathogen|covasim|starsim|gleam)",
        re.IGNORECASE,
    )
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        relative = path.relative_to(KALHAS_ROOT).as_posix()
        if relative.startswith("domain_packs/"):
            continue
        assert not vocabulary.search(path.read_text(encoding="utf-8")), (
            f"domain vocabulary in {relative}"
        )


def test_pan_v01_fixture_uses_only_the_one_declared_scenario_shape(
    pan_pack: PanV01DomainPack,
) -> None:
    """The release covers exactly the declared synthetic scenario shape."""
    assert len(pan_pack.manifest.capabilities) == 1
    assert pan_pack.manifest.capabilities[0].identifier == "pan-compartment-flow"
    assert pan_pack.mechanism_spec.timestep == 1
    assert pan_pack.mechanism_spec.timestep_unit == "day"
