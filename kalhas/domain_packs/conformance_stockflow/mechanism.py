"""Conformance stock-flow v0.1 deterministic mechanism (H29-S07).

This module owns the actual transition of the synthetic, non-health
conformance fixture: exact input validation, the integer stock-flow
arithmetic, and the assembly of the verified
``DomainMechanismStepResult``. It is fixture-owned implementation data
below ``kalhas/domain_packs/conformance_stockflow/``; the domain-neutral
kernel never imports it. The module is pure: no filesystem, network,
provider, database, environment, clock, subprocess, loader, RNG, or
mutable-global access exists anywhere in it.

The fixture exists only to prove domain neutrality of the generic
``DomainPack`` seam. It has no real-world meaning.

Declared quantities and units
-----------------------------

All quantities are exact built-in integers in unit ``units``.

State: ``level`` L with ``0 <= L <= capacity``.

Action: ``release`` r with ``0 <= r <= max_release``.

Immutable configuration: ``capacity`` C (positive), ``inflow`` F
(non-negative), ``max_release`` M (non-negative). The configuration is
fixed by the mechanism specification and copied exactly into every
request; a changed configuration under the same identity is rejected.

Declared equations (pure integer arithmetic)
--------------------------------------------

::

    available = L + F
    released  = min(r, available)
    remaining = available - released
    spilled   = max(0, remaining - C)
    next_L    = remaining - spilled
    shortfall = r - released

Invariants, checked before the result is returned::

    L + F == next_L + released + spilled
    0 <= next_L <= C
    released, spilled, shortfall >= 0

No stochastic draw exists: ``exogenous_inputs`` must be exactly empty.
Nothing is rounded, clipped silently, or repaired.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
)
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile

#: Declared implementation identity of this mechanism (recorded in the
#: platform identity of the specification built by ``pack.py``).
IMPLEMENTATION_ID = "kalhas-conformance-stockflow-implementation"
IMPLEMENTATION_VERSION = "0.1.0"

#: Declared solver identity: the single integer balance step below.
SOLVER_ID = "kalhas-conformance-stockflow-integer-solver"
SOLVER_VERSION = "0.1.0"

#: The declared output label carried in the step evidence.
DECLARED_OUTPUT_LABEL = "conditional_modeled_outcomes"

#: The declared unit of every emitted modeled quantity.
EMISSION_UNIT = "units"

#: The exact declared state key set.
STATE_KEYS: tuple[str, ...] = ("level",)

#: The exact declared action key set.
ACTION_KEYS: tuple[str, ...] = ("release",)

#: The exact declared configuration key set, in canonical order.
CONFIGURATION_KEYS: tuple[str, ...] = ("capacity", "inflow", "max_release")

#: The declared emitted quantities, in canonical emission order.
QUANTITY_IDS: tuple[str, ...] = ("released", "spilled", "shortfall", "next_level")

#: The declared event order of the v0.1 mechanism.
EVENT_IDS: tuple[str, ...] = ("inflow", "release", "overflow")

#: The frozen mechanism protocol version accepted by this fixture.
MECHANISM_PROTOCOL_VERSION: Literal["1.0.0"] = "1.0.0"

#: Schema version stamped on every built v1 contract.
_SCHEMA_VERSION = "1.0.0"

#: Prefix of every identifier this mechanism derives from a request.
_ID_PREFIX = "conformance-stockflow-v01"


class ConformanceStockFlowError(ValueError):
    """The single typed rejection of the conformance stock-flow fixture.

    Raised for every invalid request: wrong contract type, foreign or
    malformed identity, non-empty exogenous input, wrong schema
    identity, changed configuration, and any state/action value that
    fails exact-key, exact-type, or range validation. Nothing is ever
    normalized, repaired, coerced, or silently corrected.
    """


@dataclass(frozen=True)
class StockFlowTransition:
    """The complete deterministic outcome of one stock-flow transition."""

    available: int
    released: int
    spilled: int
    shortfall: int
    next_level: int


def _require_exact_int(value: object, name: str) -> int:
    """Return ``value`` only when it is an exact built-in ``int``.

    Booleans are ``bool`` at exact type identity and are rejected, as
    are floats, strings, and arbitrary objects. Nothing is coerced.
    """
    if type(value) is not int:
        raise ConformanceStockFlowError(f"{name} must be an exact built-in integer")
    return value


def _require_non_negative_int(value: object, name: str) -> int:
    number = _require_exact_int(value, name)
    if number < 0:
        raise ConformanceStockFlowError(f"{name} must be non-negative")
    return number


def _require_exact_key_set(payload: Mapping[str, object], keys: tuple[str, ...], name: str) -> None:
    """Fail closed unless the payload has exactly the declared keys."""
    if set(payload.keys()) != set(keys):
        raise ConformanceStockFlowError(f"{name} must contain exactly the declared keys")


def validate_configuration_payload(
    payload: Mapping[str, object], spec_configuration: Mapping[str, object]
) -> dict[str, int]:
    """Validate one configuration payload exactly and return its values.

    The payload must contain exactly the declared keys with exact
    built-in integer values (``capacity`` positive, the others
    non-negative) and must be canonically equal to the immutable
    configuration of the mechanism specification.
    """
    _require_exact_key_set(payload, CONFIGURATION_KEYS, "configuration payload")
    capacity = _require_exact_int(payload["capacity"], "configuration capacity")
    if capacity <= 0:
        raise ConformanceStockFlowError("configuration capacity must be positive")
    inflow = _require_non_negative_int(payload["inflow"], "configuration inflow")
    max_release = _require_non_negative_int(payload["max_release"], "configuration max_release")
    if canonical_json(dict(payload)) != canonical_json(dict(spec_configuration)):
        raise ConformanceStockFlowError("configuration differs from the mechanism specification")
    return {"capacity": capacity, "inflow": inflow, "max_release": max_release}


def validate_state_payload(payload: Mapping[str, object], configuration: Mapping[str, int]) -> int:
    """Validate one state payload exactly and return its ``level``.

    Rejects missing and extra keys, booleans, floats, strings, negative
    values, and a level above the declared capacity.
    """
    _require_exact_key_set(payload, STATE_KEYS, "state payload")
    level = _require_non_negative_int(payload["level"], "state level")
    if level > configuration["capacity"]:
        raise ConformanceStockFlowError("state level exceeds declared capacity")
    return level


def validate_action_payload(payload: Mapping[str, object], configuration: Mapping[str, int]) -> int:
    """Validate one action payload exactly and return its ``release``.

    Rejects missing and extra keys, booleans, floats, strings, negative
    values, and a release above the declared ``max_release``.
    """
    _require_exact_key_set(payload, ACTION_KEYS, "action payload")
    release = _require_non_negative_int(payload["release"], "action release")
    if release > configuration["max_release"]:
        raise ConformanceStockFlowError("action release exceeds declared max_release")
    return release


def validate_request_against_authorities(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    profile: ModelPackReleaseProfile,
) -> None:
    """Validate every request identity field against the pack authorities.

    Verifies the mechanism-spec and release-profile references, the
    copied state/action/configuration schema identity fields, the
    recomputed payload hashes, the self-covering request content hash,
    and that the exogenous input is exactly empty. Any mismatch raises
    :class:`ConformanceStockFlowError`; nothing is repaired.
    """
    if (
        request.mechanism_spec_id != spec.identifier
        or request.mechanism_spec_content_hash != spec.content_hash
    ):
        raise ConformanceStockFlowError("request references a foreign mechanism specification")
    if (
        request.release_profile_id != profile.identifier
        or request.release_profile_content_hash != profile.content_hash
    ):
        raise ConformanceStockFlowError("request references a foreign release profile")
    if (
        request.state_schema_id != spec.state_schema_id
        or request.state_schema_hash != spec.state_schema_hash
    ):
        raise ConformanceStockFlowError("request state schema identity is foreign")
    if (
        request.action_schema_id != spec.action_schema_id
        or request.action_schema_hash != spec.action_schema_hash
    ):
        raise ConformanceStockFlowError("request action schema identity is foreign")
    if (
        request.configuration_schema_id != spec.configuration_schema_id
        or request.configuration_schema_hash != spec.configuration_schema_hash
    ):
        raise ConformanceStockFlowError("request configuration schema identity is foreign")
    if request.configuration_hash != spec.configuration_hash:
        raise ConformanceStockFlowError(
            "request configuration hash is not the declared mechanism configuration identity"
        )
    if request.exogenous_inputs:
        raise ConformanceStockFlowError("the conformance stock-flow accepts no exogenous input")
    for name, payload, declared_hash in (
        ("state", request.state_payload, request.state_hash),
        ("action", request.action_payload, request.action_hash),
        ("configuration", request.configuration_payload, request.configuration_hash),
    ):
        if sha256_hex(canonical_json(dict(payload))) != declared_hash:
            raise ConformanceStockFlowError(
                f"request {name} payload hash does not match its content"
            )
    dumped: dict[str, object] = request.model_dump(mode="json")
    dumped.pop("content_hash")
    if sha256_hex(canonical_json(dumped)) != request.content_hash:
        raise ConformanceStockFlowError("request content hash does not match its content")


def compute_transition(level: int, release: int, capacity: int, inflow: int) -> StockFlowTransition:
    """Run the declared single stock-flow balance step.

    The inputs must already be validated. The invariants are checked
    before the transition is returned, so an internal inconsistency
    fails closed instead of being repaired.
    """
    available = level + inflow
    released = min(release, available)
    remaining = available - released
    spilled = max(0, remaining - capacity)
    next_level = remaining - spilled
    shortfall = release - released
    if level + inflow != next_level + released + spilled:
        raise ConformanceStockFlowError("stock-flow conservation invariant is broken")
    if next_level < 0 or next_level > capacity:
        raise ConformanceStockFlowError("stock-flow level bound invariant is broken")
    if released < 0 or spilled < 0 or shortfall < 0:
        raise ConformanceStockFlowError("stock-flow count non-negativity invariant is broken")
    return StockFlowTransition(
        available=available,
        released=released,
        spilled=spilled,
        shortfall=shortfall,
        next_level=next_level,
    )


def _finalize_self_hashed[ModelT: BaseModel](
    model_type: type[ModelT], payload: dict[str, object]
) -> ModelT:
    """Build one frozen content-hashed contract from a fresh payload.

    Validates provisionally with a placeholder digest, computes the
    canonical self-covering hash over the JSON-mode dump minus the
    ``content_hash`` field itself (the repository's single hash rule),
    and revalidates with the final digest. Callers always pass a fresh
    literal, which this helper mutates.
    """
    payload["content_hash"] = "0" * 64
    provisional = model_type.model_validate(payload)
    dumped: dict[str, object] = provisional.model_dump(mode="json")
    dumped.pop("content_hash")
    payload["content_hash"] = sha256_hex(canonical_json(dumped))
    return model_type.model_validate(payload)


def _quantities(transition: StockFlowTransition) -> tuple[int, ...]:
    """The emitted quantities in canonical ``QUANTITY_IDS`` order."""
    return (
        transition.released,
        transition.spilled,
        transition.shortfall,
        transition.next_level,
    )


def _build_emissions(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    transition: StockFlowTransition,
) -> tuple[MechanismEmissionRecord, ...]:
    """Build the ordered modeled-quantity emissions, one per quantity."""
    records: list[MechanismEmissionRecord] = []
    for position, (quantity_id, value) in enumerate(
        zip(QUANTITY_IDS, _quantities(transition), strict=True)
    ):
        records.append(
            _finalize_self_hashed(
                MechanismEmissionRecord,
                {
                    "identifier": f"{_ID_PREFIX}:{request.identifier}:emission:{position}",
                    "sequence_position": position,
                    "emission_schema_id": spec.emission_schema_id,
                    "emission_schema_hash": spec.emission_schema_hash,
                    "content_hash": "0" * 64,
                    "payload": {"quantity_id": quantity_id, quantity_id: value},
                    "unit": EMISSION_UNIT,
                },
            )
        )
    return tuple(records)


def _build_evidence(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    level: int,
    release: int,
    inflow: int,
    transition: StockFlowTransition,
) -> tuple[MechanismEvidenceRecord, ...]:
    """Build the ordered deterministic mechanism evidence.

    Records the declared output label, the declared event-order
    identity, the before/after conservation totals, the ordered
    emitted quantities, and the zero stochastic-draw declaration.
    """
    total_in = level + inflow
    total_out = transition.next_level + transition.released + transition.spilled
    payloads: list[dict[str, object]] = [
        {
            "label": DECLARED_OUTPUT_LABEL,
            "mechanism_id": spec.mechanism_id,
            "step_index": request.step_index,
            "stochastic_draws": 0,
        },
        {
            "declared_event_order": list(EVENT_IDS),
            "event_count": len(EVENT_IDS),
        },
        {
            "level_before": level,
            "inflow": inflow,
            "requested_release": release,
            "available": transition.available,
            "total_in": total_in,
            "total_out": total_out,
            "conservation_delta": total_in - total_out,
        },
        {
            "ordered_quantities": list(QUANTITY_IDS),
            "values": list(_quantities(transition)),
        },
    ]
    records: list[MechanismEvidenceRecord] = []
    for position, payload in enumerate(payloads):
        records.append(
            _finalize_self_hashed(
                MechanismEvidenceRecord,
                {
                    "identifier": f"{_ID_PREFIX}:{request.identifier}:evidence:{position}",
                    "sequence_position": position,
                    "evidence_schema_id": spec.evidence_schema_id,
                    "evidence_schema_hash": spec.evidence_schema_hash,
                    "content_hash": "0" * 64,
                    "payload": payload,
                },
            )
        )
    return tuple(records)


def run_stockflow_step(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    profile: ModelPackReleaseProfile,
) -> DomainMechanismStepResult:
    """Execute one verified conformance stock-flow mechanism step.

    Validates the request identity against the specification and
    release-profile authorities, validates the state, action, and
    configuration payloads exactly, runs the deterministic transition,
    and assembles the complete verified result with self-covering
    canonical hashes. The request and every nested container are never
    mutated; the returned result shares no container with them.
    """
    if type(request) is not DomainMechanismStepRequest:
        raise ConformanceStockFlowError("request must be the exact v1 step-request contract")
    validate_request_against_authorities(request, spec, profile)
    configuration = validate_configuration_payload(
        request.configuration_payload, spec.configuration
    )
    level = validate_state_payload(request.state_payload, configuration)
    release = validate_action_payload(request.action_payload, configuration)
    transition = compute_transition(
        level, release, configuration["capacity"], configuration["inflow"]
    )
    emissions = _build_emissions(request, spec, transition)
    evidence = _build_evidence(request, spec, level, release, configuration["inflow"], transition)
    next_state_payload = {"level": transition.next_level}
    return _finalize_self_hashed(
        DomainMechanismStepResult,
        {
            "identifier": f"{_ID_PREFIX}:{request.identifier}:result",
            "tenant_id": profile.tenant_id,
            "schema_version": _SCHEMA_VERSION,
            "request_id": request.identifier,
            "request_content_hash": request.content_hash,
            "mechanism_spec_id": spec.identifier,
            "mechanism_spec_content_hash": spec.content_hash,
            "release_profile_id": profile.identifier,
            "release_profile_content_hash": profile.content_hash,
            "world_version_id": request.world_version_id,
            "world_content_hash": request.world_content_hash,
            "seed_id": request.seed_id,
            "seed_content_hash": request.seed_content_hash,
            "realization_id": request.realization_id,
            "realization_content_hash": request.realization_content_hash,
            "run_id": request.run_id,
            "step_index": request.step_index,
            "next_state_schema_id": spec.state_schema_id,
            "next_state_schema_hash": spec.state_schema_hash,
            "next_state_payload": next_state_payload,
            "next_state_hash": sha256_hex(canonical_json(next_state_payload)),
            "emissions": emissions,
            "evidence": evidence,
            "content_hash": "0" * 64,
        },
    )
