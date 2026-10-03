"""Generic DomainPack-driven pure mechanism dispatcher (Phase 29, H29-S03).

The single composition/dispatch seam of ADR-005 (D29-02): a caller hands
one explicitly supplied conforming ``DomainPack`` object and one
``DomainMechanismStepRequest`` to :func:`dispatch_domain_mechanism_step`;
the seam verifies every authority before execution, invokes the pack's
exactly one pure ``step`` operation exactly once with a detached deep copy
of the verified request, verifies and detaches the returned
``DomainMechanismStepResult``, and returns the complete verified result.
Every rejected dispatch raises exactly one
``DomainMechanismDispatchError`` with a generic public message, no
partial result, and no KALHAS-side effect.

Fail-closed verification, in order:

1. Exact supplied surface: the request, the pack manifest, and the pack
   release profile must be exactly the shipped v1 contract types (no
   dict coercion, no subclasses), the mechanism protocol version must be
   the exact built-in string ``1.0.0``, and ``step`` must be present and
   callable. A legacy manifest-only carrier is not an executable pack
   and is rejected. No ``isinstance`` against the ``DomainPack``
   protocol, no runtime check, no dynamic loading, no discovery, and no
   registry lookup exists anywhere in this module.
2. Pre-normalization exact object-graph audit: before any serialization
   or other type-erasing operation, the original supplied Python object
   graph of the request, the manifest, the release profile (including
   its embedded manifest and mechanism spec), and the returned result is
   inspected recursively on the original runtime values. Only exact
   built-in ``dict``, ``list``, ``tuple``, ``str``, ``int``, finite
   ``float``, ``bool``, ``None``, timezone-aware ``datetime``, and the
   exact shipped contract record types are accepted anywhere in the
   graph. Subclasses of JSON built-ins or structural containers,
   subclasses of nested contract records, foreign Pydantic models, and
   arbitrary lookalike objects are rejected outright instead of being
   normalized, so Pydantic serialization can never erase a hostile
   runtime type before strict revalidation sees it. Nothing here scans
   the serialized output in place of the original objects.
3. Detached strict revalidation: every supplied record is treated as
   untrusted even when it is already a Pydantic instance. A detached
   Python-mode copy is strictly revalidated, so validator-bypassed,
   forged, shallow-mutated, subclassed, unserializable, or malformed
   records fail closed. Python mode keeps tuple and datetime fields
   exact for strict validation. Input is never repaired, normalized,
   sorted, coerced, or silently accepted.
4. Manifest and release-profile authority: recomputed canonical
   self-covering content hashes, exact embedded-manifest content
   equality, tenant/pack/version/manifest identity agreement, the
   embedded ``DomainMechanismSpec`` (strictly revalidated), the frozen
   mechanism protocol version across pack literal, spec, and profile,
   the recomputed spec self hash, and the configuration identity.
5. Request authority: recomputed state/action/configuration payload
   hashes, per-entry exogenous value hashes, all copied identity fields
   (tenant, spec, release profile, schema identities, configuration)
   against the verified authorities, and the recomputed overall request
   content hash excluding only the ``content_hash`` field itself.
6. Exactly-once invocation with isolation: the pack receives one
   detached deep copy of the verified request. The caller's request and
   all nested containers are never shared with the pack, and the copy
   the pack receives is never used as a post-dispatch authority. No
   retry, no loop, no second pack method, no policy or strategy choice,
   and no filesystem, store, clock, environment, network, or random
   access exists here. A pack exception is wrapped into the typed
   dispatch error and never retried.
7. Post-dispatch authority: the returned value must be exactly
   ``DomainMechanismStepResult``, is audited on its original object
   graph, strictly revalidated from a detached serialized copy, and
   every identity and hash field must agree exactly with the verified
   request and the mechanism/release authorities. The returned result
   is a fresh detached verified object sharing no mutable container
   with the pack-owned return value.

Every failure during original graph inspection, detached extraction,
serialization, strict validation, or canonical hash recomputation is
converted into exactly one :class:`DomainMechanismDispatchError` that
preserves the underlying exception as its ``__cause__`` while never
exposing its text or any hostile object representation publicly.

Content-hash semantics are the existing repository conventions via
:mod:`kalhas.application.hashing`: a self-covering model hash is the
canonical SHA-256 over ``model_dump(mode="json")`` excluding that
model's own ``content_hash`` field; payload hashes are canonical
SHA-256 of the exact JSON payload; an exogenous entry's hash is the
canonical SHA-256 of its exact value. Canonical JSON preserves the
built-in ``int`` versus ``float`` distinction, so ``1`` and ``1.0``
hash differently.

This module is a KALHAS application-layer implementation detail: it adds
no public contract, no schema, no registry item, and no API surface, is
not re-exported through ``kalhas.application.__init__``, and never
imports a concrete pack or a ``domain_packs`` subpackage. The only
domain-pack import is the public protocol, ``from kalhas.domain_packs
import DomainPack``.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import NoReturn

from pydantic import BaseModel

from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismDataIdentity,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
    MechanismExogenousInput,
    MechanismParameterBinding,
    MechanismPlatformIdentity,
    MechanismQuantizationBoundary,
)
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.model_pack import (
    ModelPackAssumption,
    ModelPackDatasetIdentity,
    ModelPackEvidenceRecord,
    ModelPackIntendedUse,
    ModelPackLimitation,
    ModelPackProvenance,
    ModelPackReleaseProfile,
    ModelPackResourceEnvelope,
    ModelPackRetainedFailure,
    ModelPackScope,
    ModelPackSupportedClaim,
    ModelPackUnitDeclaration,
)
from kalhas.contracts.v1.shared import VersionedContract
from kalhas.domain_packs import DomainPack

__all__ = ["dispatch_domain_mechanism_step"]

#: The frozen ADR-005 mechanism protocol version accepted at this seam.
_MECHANISM_PROTOCOL_VERSION = "1.0.0"

#: Ordinary exceptions convertible into the single typed dispatch error
#: wherever canonical JSON extraction, serialization, or hashing can
#: fail on hostile (for example cyclic or non-exact) object graphs.
_HASH_FAILURES: tuple[type[Exception], ...] = (TypeError, ValueError, RecursionError)


def _fail(reason: str, request_id: str | None = None) -> NoReturn:
    """Raise the single typed dispatch error with a bounded internal reason."""
    raise DomainMechanismDispatchError(reason, request_id=request_id)


def _self_covering_hash(model: BaseModel, reason: str, request_id: str | None) -> str:
    """Canonical SHA-256 over the model's JSON content minus its own hash.

    Hash computation is part of the protected failure surface: a hostile
    object graph that survives the exact-type audit only through a
    contract-typed field (for example a cyclic payload injected behind an
    exact ``dict``) fails here and becomes the single typed error.
    """
    try:
        payload = model.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_hex(canonical_json(payload))
    except _HASH_FAILURES as exc:
        raise DomainMechanismDispatchError(reason, request_id=request_id) from exc


def _payload_hash(payload: object, reason: str, request_id: str | None) -> str:
    """Canonical SHA-256 of the exact JSON payload value."""
    try:
        return sha256_hex(canonical_json(payload))
    except _HASH_FAILURES as exc:
        raise DomainMechanismDispatchError(reason, request_id=request_id) from exc


# ---------------------------------------------------------------------------
# Pre-normalization exact object-graph audit
# ---------------------------------------------------------------------------

#: Exact atomic runtime types accepted anywhere in a supplied authority
#: graph. Subclasses are rejected by exact type identity: serialization
#: must never be the first observer of a hostile runtime type.
_EXACT_ATOMIC_TYPES = frozenset({bool, str, int, float, datetime})

#: Exact structural container types accepted at their contract positions.
_EXACT_SEQUENCE_TYPES = (list, tuple)
_EXACT_MAPPING_TYPE = dict

#: The exact contract record types allowed at the root of one supplied
#: authority graph (top-level request, manifest, profile, or result).
_ROOT_CONTRACTS: tuple[type[VersionedContract], ...] = (
    DomainPackManifest,
    ModelPackReleaseProfile,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)

#: The exact shipped nested contract record types allowed inside a
#: supplied authority graph. Any other Pydantic model - including a
#: subclass of one of these records or a structurally identical foreign
#: model - is rejected before its runtime type can be erased.
_NESTED_CONTRACTS: tuple[type[BaseModel], ...] = (
    DomainPackCapability,
    DomainPackManifest,
    MechanismDataIdentity,
    MechanismParameterBinding,
    MechanismPlatformIdentity,
    MechanismQuantizationBoundary,
    MechanismExogenousInput,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
    DomainMechanismSpec,
    ModelPackAssumption,
    ModelPackDatasetIdentity,
    ModelPackEvidenceRecord,
    ModelPackIntendedUse,
    ModelPackLimitation,
    ModelPackProvenance,
    ModelPackResourceEnvelope,
    ModelPackRetainedFailure,
    ModelPackScope,
    ModelPackSupportedClaim,
    ModelPackUnitDeclaration,
)


def _field_values(record: BaseModel) -> list[object]:
    """The declared field values of one contract record instance.

    Frozen Pydantic v2 models carry exactly their declared fields in
    ``__dict__`` (no extras, no private state under these contracts), so
    the instance namespace minus dunder entries is the complete authority
    graph continuation. ``__dict__`` is read without recursion triggers
    or custom descriptors and is never mutated.
    """
    return [
        value
        for name, value in vars(record).items()
        if not (name.startswith("__") and name.endswith("__"))
    ]


def _find_non_exact_object_defect(
    value: object, *, root: bool, visiting: frozenset[int]
) -> TypeError | None:
    """Return the first exact-type defect in the original runtime graph.

    Purely structural recursion over the original supplied Python values,
    before any serialization can normalize a hostile runtime type.
    Accepts only exact built-in ``dict`` with exact ``str`` keys, exact
    ``list`` and contract ``tuple`` positions, exact ``str``/``int``/
    finite ``float``/``bool``, ``None``, timezone-aware ``datetime``,
    and the exact shipped contract record types. Subclasses, foreign
    models, arbitrary lookalike objects, and cyclic containers are
    defects; nothing is repaired, coerced, or normalized, and nothing
    here is evaluated or executed. ``visiting`` holds the identities of
    the containers on the current descent path so a hostile self-
    referencing graph is rejected deterministically instead of
    overflowing the interpreter stack.
    """
    if value is None:
        return None
    value_type = type(value)
    if value_type in _EXACT_ATOMIC_TYPES:
        return None
    if isinstance(value, (list, tuple, dict)):
        if value_type not in _EXACT_SEQUENCE_TYPES and value_type is not _EXACT_MAPPING_TYPE:
            return TypeError("non-exact container type in supplied object graph")
        marker = id(value)
        if marker in visiting:
            return TypeError("cyclic container in supplied object graph")
        next_visiting = visiting | {marker}
        if isinstance(value, dict):
            for key, item in value.items():
                if type(key) is not str:
                    return TypeError("non-exact JSON object key type")
                defect = _find_non_exact_object_defect(item, root=False, visiting=next_visiting)
                if defect is not None:
                    return defect
            return None
        for item in value:
            defect = _find_non_exact_object_defect(item, root=False, visiting=next_visiting)
            if defect is not None:
                return defect
        return None
    allowed_contracts = _ROOT_CONTRACTS if root else _NESTED_CONTRACTS
    if value_type in allowed_contracts:
        if not isinstance(value, BaseModel):
            return TypeError("non-exact runtime object graph type")
        next_visiting = visiting | {id(value)}
        for nested in _field_values(value):
            defect = _find_non_exact_object_defect(nested, root=False, visiting=next_visiting)
            if defect is not None:
                return defect
        return None
    return TypeError("non-exact runtime object graph type")


def _reject_non_exact_object_graph(
    record: VersionedContract, reason: str, request_id: str | None
) -> None:
    """Fail closed when the original object graph is not exactly typed.

    The audit observes the original supplied values before ``model_dump``
    or any other normalizing operation can erase a hostile runtime type.
    The inspection boundary is complete: a validator-bypassed record may
    carry a hostile mapping in its instance namespace, so every ordinary
    exception raised while enumerating or descending the original graph -
    including hostile namespace operations and interpreter recursion
    exhaustion - becomes the single typed error with the underlying
    exception preserved privately as its cause. A returned defect raises
    the same typed error. No ``BaseException`` is caught here.
    """
    try:
        defect = _find_non_exact_object_defect(record, root=True, visiting=frozenset())
    except Exception as exc:
        raise DomainMechanismDispatchError(reason, request_id=request_id) from exc
    if defect is not None:
        raise DomainMechanismDispatchError(reason, request_id=request_id) from defect


def _detached_revalidated[ModelT: VersionedContract](
    model_type: type[ModelT], record: ModelT, reason: str, request_id: str | None
) -> ModelT:
    """Strictly revalidate a detached serialized copy of an untrusted record.

    The supplied instance is never trusted directly and never repaired:
    its full content is revalidated from scratch, so forged,
    validator-bypassed, shallow-mutated, subclassed, or malformed state
    fails closed here. The pre-normalization exact object-graph audit has
    already rejected hostile runtime types on the original values, so the
    serialization below observes only exact objects. The entire
    untrusted-data operation - Python-mode dumping (which preserves tuple
    and datetime fields for strict validation, where JSON mode would turn
    valid tuples into lists and datetimes into strings), detached
    extraction, and strict revalidation - sits behind one complete
    exception boundary: every ordinary failure, including serialization,
    extraction, validation, runtime, and recursion errors, becomes
    exactly one :class:`DomainMechanismDispatchError` with the underlying
    exception preserved privately as its cause and the bounded reason and
    request ID retained. Python mode and ``strict=True`` are never
    weakened, and input is never repaired, normalized, sorted, coerced,
    or silently accepted. No ``BaseException`` is caught here.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            payload = record.model_dump(mode="python")
        return model_type.model_validate(payload, strict=True)
    except Exception as exc:
        raise DomainMechanismDispatchError(reason, request_id=request_id) from exc


def _verified_pack_surface(
    pack: DomainPack, request: DomainMechanismStepRequest
) -> tuple[
    DomainPackManifest,
    ModelPackReleaseProfile,
    str,
    Callable[[DomainMechanismStepRequest], DomainMechanismStepResult],
]:
    """Verify the exact supplied pack surface before any authority check.

    Only the explicitly supplied object is inspected: exact type identity
    for the request, the manifest, and the release profile; the
    pre-normalization exact object-graph audit of the original request
    values; the exact built-in protocol string; and a present callable
    ``step`` operation. A legacy manifest-only carrier fails closed here
    with zero side effects.
    """
    if type(request) is not DomainMechanismStepRequest:
        _fail("request_type")
    _reject_non_exact_object_graph(request, "request_revalidation", None)
    try:
        pack_manifest = pack.manifest
        pack_release_profile = pack.release_profile
        pack_protocol_version = pack.mechanism_protocol_version
        step = pack.step
    except AttributeError as exc:
        raise DomainMechanismDispatchError("legacy_manifest_only_or_incomplete_pack") from exc
    except Exception as exc:
        raise DomainMechanismDispatchError("pack_attribute_access") from exc
    if type(pack_manifest) is not DomainPackManifest:
        _fail("manifest_type")
    if type(pack_release_profile) is not ModelPackReleaseProfile:
        _fail("release_profile_type")
    protocol_is_exact = (
        type(pack_protocol_version) is str and pack_protocol_version == _MECHANISM_PROTOCOL_VERSION
    )
    if not protocol_is_exact:
        _fail("mechanism_protocol_version")
    if step is None or not callable(step):
        _fail("step_not_callable")
    return pack_manifest, pack_release_profile, pack_protocol_version, step


def _verified_manifest_and_release_authorities(
    untrusted_manifest: DomainPackManifest,
    untrusted_release_profile: ModelPackReleaseProfile,
    pack_protocol_version: str,
) -> tuple[DomainPackManifest, ModelPackReleaseProfile, DomainMechanismSpec]:
    """Verify the manifest, release profile, and embedded mechanism spec.

    The original object graphs are audited before any serialization, and
    everything else is checked on detached revalidated copies: self-covering
    content hashes are recomputed, the profile must embed the exact
    manifest content, all copied identity fields must agree across
    manifest, profile, and spec, the protocol literal must agree across
    the pack, the spec, and the profile, and the configuration identity
    must be the recomputed hash of the spec's immutable configuration.
    """
    _reject_non_exact_object_graph(untrusted_manifest, "manifest_revalidation", None)
    _reject_non_exact_object_graph(untrusted_release_profile, "release_profile_revalidation", None)
    manifest = _detached_revalidated(
        DomainPackManifest, untrusted_manifest, "manifest_revalidation", None
    )
    profile = _detached_revalidated(
        ModelPackReleaseProfile, untrusted_release_profile, "release_profile_revalidation", None
    )
    try:
        recomputed_manifest_hash = manifest_content_hash(manifest)
    except _HASH_FAILURES as exc:
        raise DomainMechanismDispatchError("manifest_content_hash") from exc
    if recomputed_manifest_hash != manifest.content_hash:
        _fail("manifest_content_hash")
    if _self_covering_hash(profile, "release_profile_content_hash", None) != profile.content_hash:
        _fail("release_profile_content_hash")
    if profile.manifest.model_dump(mode="json") != manifest.model_dump(mode="json"):
        _fail("release_profile_manifest_embedding")
    spec = profile.mechanism_spec
    if manifest.tenant_id != profile.tenant_id or spec.tenant_id != profile.tenant_id:
        _fail("tenant_agreement")
    for copied, embedded, reason in (
        (profile.pack_id, manifest.pack_id, "pack_identity"),
        (profile.pack_version, manifest.pack_version, "pack_identity"),
        (profile.manifest_id, manifest.identifier, "manifest_identity"),
        (profile.manifest_content_hash, manifest.content_hash, "manifest_identity"),
        (spec.manifest_id, manifest.identifier, "spec_manifest_identity"),
        (spec.manifest_content_hash, manifest.content_hash, "spec_manifest_identity"),
        (spec.pack_id, manifest.pack_id, "spec_pack_identity"),
        (spec.pack_version, manifest.pack_version, "spec_pack_identity"),
    ):
        if copied != embedded:
            _fail(reason)
    if (
        spec.mechanism_protocol_version != _MECHANISM_PROTOCOL_VERSION
        or profile.mechanism_protocol_version != _MECHANISM_PROTOCOL_VERSION
        or pack_protocol_version != spec.mechanism_protocol_version
        or pack_protocol_version != profile.mechanism_protocol_version
    ):
        _fail("mechanism_protocol_agreement")
    if _self_covering_hash(spec, "mechanism_spec_content_hash", None) != spec.content_hash:
        _fail("mechanism_spec_content_hash")
    if (
        _payload_hash(spec.configuration, "mechanism_spec_configuration_hash", None)
        != spec.configuration_hash
    ):
        _fail("mechanism_spec_configuration_hash")
    if profile.configuration_identity != spec.configuration_hash:
        _fail("release_profile_configuration_identity")
    return manifest, profile, spec


def _verified_request_authority(
    untrusted_request: DomainMechanismStepRequest,
    manifest: DomainPackManifest,
    profile: ModelPackReleaseProfile,
    spec: DomainMechanismSpec,
) -> DomainMechanismStepRequest:
    """Verify the request's detached copy, identities, and hashes.

    Every hash is recomputed from the exact content; every copied
    identity field must agree with the verified manifest, release
    profile, and mechanism spec authorities. Nothing is inferred,
    generated, sampled, reordered, or modified.
    """
    request = _detached_revalidated(
        DomainMechanismStepRequest, untrusted_request, "request_revalidation", None
    )
    request_id = request.identifier
    if request.tenant_id != profile.tenant_id or request.tenant_id != manifest.tenant_id:
        _fail("request_tenant_agreement", request_id)
    if (
        request.mechanism_spec_id != spec.identifier
        or request.mechanism_spec_content_hash != spec.content_hash
    ):
        _fail("request_mechanism_spec_reference", request_id)
    if (
        request.release_profile_id != profile.identifier
        or request.release_profile_content_hash != profile.content_hash
    ):
        _fail("request_release_profile_reference", request_id)
    for request_field, spec_field, reason in (
        ("state_schema_id", "state_schema_id", "request_state_schema_identity"),
        ("action_schema_id", "action_schema_id", "request_action_schema_identity"),
        (
            "configuration_schema_id",
            "configuration_schema_id",
            "request_configuration_schema_identity",
        ),
        ("state_schema_hash", "state_schema_hash", "request_state_schema_identity"),
        ("action_schema_hash", "action_schema_hash", "request_action_schema_identity"),
        (
            "configuration_schema_hash",
            "configuration_schema_hash",
            "request_configuration_schema_identity",
        ),
    ):
        if getattr(request, request_field) != getattr(spec, spec_field):
            _fail(reason, request_id)
    if _payload_hash(request.state_payload, "request_state_hash", request_id) != request.state_hash:
        _fail("request_state_hash", request_id)
    if (
        _payload_hash(request.action_payload, "request_action_hash", request_id)
        != request.action_hash
    ):
        _fail("request_action_hash", request_id)
    if (
        _payload_hash(request.configuration_payload, "request_configuration_payload_hash", None)
        != request.configuration_hash
    ):
        _fail("request_configuration_payload_hash", request_id)
    try:
        configuration_matches = canonical_json(request.configuration_payload) == canonical_json(
            spec.configuration
        )
    except _HASH_FAILURES as exc:
        raise DomainMechanismDispatchError(
            "request_configuration_differs_from_spec", request_id=request_id
        ) from exc
    if not configuration_matches:
        _fail("request_configuration_differs_from_spec", request_id)
    for entry in request.exogenous_inputs:
        if entry.content_hash != _payload_hash(entry.value, "request_exogenous_value_hash", None):
            _fail("request_exogenous_value_hash", request_id)
    if _self_covering_hash(request, "request_content_hash", request_id) != request.content_hash:
        _fail("request_content_hash", request_id)
    return request


def dispatch_domain_mechanism_step(
    pack: DomainPack, request: DomainMechanismStepRequest
) -> DomainMechanismStepResult:
    """Dispatch one verified pure mechanism step through a supplied pack.

    Verifies every precondition, invokes the pack's ``step`` exactly once
    with a detached deep copy of the verified request, verifies the
    returned result against every authority, and returns a fresh detached
    verified result. Any rejected precondition, pack failure, or failed
    postcondition raises :class:`DomainMechanismDispatchError` with no
    partial result and no KALHAS-side effect.
    """
    untrusted_manifest, untrusted_release_profile, pack_protocol_version, step = (
        _verified_pack_surface(pack, request)
    )
    manifest, profile, spec = _verified_manifest_and_release_authorities(
        untrusted_manifest, untrusted_release_profile, pack_protocol_version
    )
    verified_request = _verified_request_authority(request, manifest, profile, spec)

    detached_request = verified_request.model_copy(deep=True)
    try:
        returned = step(detached_request)
    except Exception as exc:
        raise DomainMechanismDispatchError(
            "pack_step_raised", request_id=verified_request.identifier
        ) from exc

    if type(returned) is not DomainMechanismStepResult:
        _fail("result_type", verified_request.identifier)
    _reject_non_exact_object_graph(returned, "result_revalidation", verified_request.identifier)
    result = _detached_revalidated(
        DomainMechanismStepResult, returned, "result_revalidation", verified_request.identifier
    )
    _verify_result_authority(result, verified_request, spec, profile)
    return result


def _verify_result_authority(
    result: DomainMechanismStepResult,
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    profile: ModelPackReleaseProfile,
) -> None:
    """Verify the returned result against the request and the authorities."""
    request_id = request.identifier
    if result.tenant_id != request.tenant_id:
        _fail("result_tenant_agreement", request_id)
    if result.request_id != request.identifier or result.request_content_hash != (
        request.content_hash
    ):
        _fail("result_request_reference", request_id)
    if (
        result.mechanism_spec_id != spec.identifier
        or result.mechanism_spec_content_hash != spec.content_hash
    ):
        _fail("result_mechanism_spec_reference", request_id)
    if (
        result.release_profile_id != profile.identifier
        or result.release_profile_content_hash != profile.content_hash
    ):
        _fail("result_release_profile_reference", request_id)
    if (
        result.world_version_id != request.world_version_id
        or result.world_content_hash != request.world_content_hash
        or result.seed_id != request.seed_id
        or result.seed_content_hash != request.seed_content_hash
    ):
        _fail("result_world_seed_identity", request_id)
    if (result.realization_id is None) != (request.realization_id is None):
        _fail("result_realization_identity", request_id)
    if result.realization_id is not None and (
        result.realization_id != request.realization_id
        or result.realization_content_hash != request.realization_content_hash
    ):
        _fail("result_realization_identity", request_id)
    if result.run_id != request.run_id or result.step_index != request.step_index:
        _fail("result_run_step_identity", request_id)
    if (
        result.next_state_schema_id != spec.state_schema_id
        or result.next_state_schema_hash != spec.state_schema_hash
    ):
        _fail("result_next_state_schema_identity", request_id)
    if (
        _payload_hash(result.next_state_payload, "result_next_state_hash", request_id)
        != result.next_state_hash
    ):
        _fail("result_next_state_hash", request_id)
    _verify_sequenced_records(
        result.emissions,
        "emission_schema_id",
        "emission_schema_hash",
        spec.emission_schema_id,
        spec.emission_schema_hash,
        "result_emission",
        request_id,
    )
    _verify_sequenced_records(
        result.evidence,
        "evidence_schema_id",
        "evidence_schema_hash",
        spec.evidence_schema_id,
        spec.evidence_schema_hash,
        "result_evidence",
        request_id,
    )
    if _self_covering_hash(result, "result_content_hash", request_id) != result.content_hash:
        _fail("result_content_hash", request_id)


def _verify_sequenced_records(
    records: Sequence[MechanismEmissionRecord | MechanismEvidenceRecord],
    schema_id_field: str,
    schema_hash_field: str,
    schema_id: str,
    schema_hash: str,
    reason_prefix: str,
    request_id: str,
) -> None:
    """Verify one ordered record collection's schema identity and hashes.

    Sequence positions must remain contiguous from zero in recorded order
    with unique identifiers, every record must use the mechanism spec's
    declared schema identity, and every self-covering content hash must
    recompute exactly.
    """
    seen_identifiers: list[str] = []
    for position, record in enumerate(records):
        if record.sequence_position != position:
            _fail(f"{reason_prefix}_order", request_id)
        seen_identifiers.append(record.identifier)
        if (
            getattr(record, schema_id_field) != schema_id
            or getattr(record, schema_hash_field) != schema_hash
        ):
            _fail(f"{reason_prefix}_schema_identity", request_id)
        if (
            _self_covering_hash(record, f"{reason_prefix}_content_hash", request_id)
            != record.content_hash
        ):
            _fail(f"{reason_prefix}_content_hash", request_id)
    if len(set(seen_identifiers)) != len(seen_identifiers):
        _fail(f"{reason_prefix}_identifier", request_id)
