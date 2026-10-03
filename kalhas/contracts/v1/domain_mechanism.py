"""Declarative domain-mechanism contracts (Phase 29, H29-S02A).

ADR-005 (D29-02, D34-01) freezes the pure mechanism seam. This module adds
exactly three top-level public v1 contracts plus their synchronized JSON
Schemas:

- ``DomainMechanismSpec`` - the immutable declarative identity of one
  mechanism: its pack/manifest binding, mechanism identity and mechanism
  protocol version, state/action/configuration/emission/evidence schema
  ids and hashes, the immutable configuration, the implementation/
  dependency/solver and platform identity, the exact timestep, the
  explicitly ordered event and reduction orders, the
  ``kalhas-platform-bound-binary64-v1`` numeric profile with IEEE-754
  binary64 precision and round-to-nearest ties-to-even rounding at
  explicitly named quantization boundaries only, a self-covering content
  hash, a timezone-aware caller-supplied declaration time, and finite
  metadata.
- ``DomainMechanismStepRequest`` - exactly ``verified state + validated
  action + ordered coordinate-addressed exogenous inputs + immutable
  configuration``: the mechanism-spec reference, the required opaque
  release-profile identity reference (id and content hash), the
  tenant/scenario/world/seed/run/step identity, the copied state, action,
  and configuration schema identities, the three payloads with their
  content hashes, and canonically ordered exogenous entries. The release
  profile is an opaque identity reference only; no ModelPack profile is
  implemented here. There is no timestamp and no wall-clock authority
  anywhere in a request.
- ``DomainMechanismStepResult`` - exactly ``verified next state + ordered
  typed emissions + ordered deterministic mechanism evidence``: the
  request/mechanism-spec/release-profile references, the same
  world/seed/optional-realization/run/step identity, the verified next
  state with schema identity and hash, ordered emission and evidence
  records with unique identifiers and contiguous sequence positions from
  zero, and a self-covering content hash. No time, persistence receipt,
  recommendation, winner, scheduler, or external effect is expressible.

The nested helper records (platform identity, quantization boundaries,
data identities, parameter bindings, exogenous entries, emission records,
evidence records) are frozen, strict, and extra-forbid; they are NOT
registered in ``PUBLIC_CONTRACTS`` and receive no standalone schema files.

Numerical rules (D34-01): numeric fields accept only exact built-in
``int`` or finite built-in ``float`` according to the declared kind.
Booleans, numeric strings, Decimal-like objects, NaN, infinities, and any
coercion or overflow fail closed. Integer kinds accept exact ``int`` only;
number kinds accept an exact ``int`` or finite ``float`` without
conversion. Accepted values are preserved exactly; JSON strings remain
strings and are never coerced into numerics. Subclasses of the JSON
built-ins (``int``, ``float``, ``str``, ``list``, ``dict``, ``bool``)
are rejected by exact type identity, not normalized. Non-finite values
are rejected recursively anywhere inside a JSON payload or metadata tree.
Noncanonical coordinate order is rejected instead of being sorted.

Exact fail-closed raw input: every configuration, state, action,
next-state, emission, evidence, and metadata JSON tree passes one local
recursive validator before Pydantic sees the value, so only exact JSON
structures are expressible: built-in ``dict`` with exact string keys,
built-in ``list``, exact ``str``/``int``/finite ``float``/``bool``, and
``None``. Tuples, sets, ``Decimal``, datetimes, arbitrary mappings or
objects, non-string keys, NaN, and infinities are rejected outright and
can never be coerced into a neighboring JSON type.

Quantization (D34-01): a ``MechanismQuantizationBoundary`` declares one
uniquely named boundary with an exact positive numeric ``quantum`` and an
optional unit. An empty ``quantization_boundaries`` declares no
quantization at all; a non-empty set declares quantization only at those
boundaries under the spec's round-to-nearest ties-to-even literal. No
hidden clipping, tolerance, or default quantization exists.

These contracts are **declarative data only**. This slice defines the
contract shapes; it computes no authoritative hash and performs no
cross-authority verification. Execution, services, release profiles, a
dispatcher, and runtime integration belong to later slices. No callback,
expression, executable or importable path, provider, network, clock,
environment, persistence, policy-choice, comparison, scheduler, or
live-action field is expressible anywhere in this module.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    Strict,
    model_validator,
)

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import (
    ExactNumeric,
    IdentifierString,
    Sha256Hex,
    _is_exact_finite_numeric,
)

#: The frozen mechanism protocol version of the ADR-005 seam.
MechanismProtocolVersion = Literal["1.0.0"]

#: The frozen D34-01 numeric/platform profile identifier.
NumericProfileLiteral = Literal["kalhas-platform-bound-binary64-v1"]

#: The frozen IEEE-754 binary64 precision declaration.
PrecisionLiteral = Literal["ieee-754-binary64"]

#: The frozen rounding rule: round-to-nearest, ties-to-even.
RoundingModeLiteral = Literal["round-to-nearest-ties-to-even"]

#: Semantic version pattern for pack, mechanism, implementation, and solver
#: versions (same shape as the schema-version pattern).
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"

#: A semantic version string field.
MechanismSemVer = Annotated[str, Field(pattern=_SEMVER_PATTERN)]

#: A strict non-negative integer: floats, strings, and booleans are
#: rejected before any coercion, and the value must be >= 0.
StrictNonNegativeInt = Annotated[int, Strict(), Field(ge=0)]

#: A strict exact positive integer: floats, strings, and booleans are
#: rejected before any coercion, and the value must be > 0.
StrictPositiveInt = Annotated[int, Strict(), Field(gt=0)]


def _require_finite(value: int | float) -> int | float:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("numeric value must be finite")
    return value


#: A strict finite float: strings and booleans are rejected and NaN and
#: infinities fail closed.
StrictFiniteFloat = Annotated[float, Strict(), AfterValidator(_require_finite)]

#: A strict finite positive float: strings and booleans are rejected and
#: the value must be finite and > 0.
StrictPositiveFiniteFloat = Annotated[
    float,
    Strict(),
    Field(gt=0),
    AfterValidator(_require_finite),
]

#: A strict positive exact numeric: an exact ``int`` or finite ``float``
#: strictly greater than zero; NaN and infinities fail closed, and
#: booleans and strings fail strict typing. Built per-member because
#: ``Strict()`` cannot be applied to a union schema directly.
StrictPositiveNumeric = StrictPositiveInt | StrictPositiveFiniteFloat


def _is_exact_json_value(value: object) -> bool:
    """True only for a value that is exactly representable as JSON data.

    Accepts recursively: built-in ``dict`` with exact string keys, built-in
    ``list``, exact ``str``/``int``/finite ``float``, ``bool``, and
    ``None``. Tuples, sets, ``Decimal`` values, datetimes, arbitrary
    mappings or objects, non-string dict keys, NaN, and infinities are all
    rejected, so nothing can later be coerced into a neighboring JSON
    type. Purely structural; nothing here is evaluated or executed.
    """
    if value is None:
        return True
    if type(value) in (bool, str, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_exact_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_exact_json_value(item) for key, item in value.items())
    return False


def _reject_non_json_tree(field_name: str, data: dict[str, Any]) -> None:
    """Fail closed when a declared JSON tree is not an exact JSON value.

    Applied to the raw model input before Pydantic validates the fields,
    so tuples, sets, ``Decimal`` values, datetimes, arbitrary mappings or
    objects, non-string keys, NaN, and infinities are rejected before any
    coercion into a neighboring JSON type can happen.
    """
    if not _is_exact_json_value(data.get(field_name)):
        raise ValueError(
            f"{field_name} must contain only exact JSON values: objects with "
            "string keys, arrays, strings, exact integers, finite floats, "
            "booleans, and null"
        )


class MechanismPlatformIdentity(BaseModel):
    """The recorded platform identity of one mechanism (D34-01).

    Binds the operating system, architecture, Python implementation and
    version, the dependency-lock hash, the mechanism implementation
    identity, the solver identity, and the frozen numeric-profile
    identifier. Exact replay is claimed only under this recorded
    identity; a mismatch rejects exact replay or comparison.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    os_name: IdentifierString
    architecture: IdentifierString
    python_implementation: IdentifierString
    python_version: IdentifierString
    dependency_lock_hash: Sha256Hex
    implementation_id: IdentifierString
    implementation_version: MechanismSemVer
    implementation_hash: Sha256Hex
    solver_id: IdentifierString
    solver_version: MechanismSemVer
    numeric_profile: NumericProfileLiteral


class MechanismQuantizationBoundary(BaseModel):
    """One explicitly named quantization boundary (D34-01).

    ``quantum`` is the exact positive numeric step of this boundary;
    zero, negatives, booleans, strings, ``Decimal``, NaN, and infinities
    fail closed. Quantization happens only at these declared boundaries,
    with the spec's round-to-nearest ties-to-even semantics. There is no
    hidden rounding, clipping, tolerance, or default quantization
    anywhere.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary_id: IdentifierString
    quantum: StrictPositiveNumeric
    unit: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _raw_quantum_must_be_exact_finite(cls, data: Any) -> Any:
        if isinstance(data, dict) and not _is_exact_finite_numeric(data.get("quantum")):
            raise ValueError("quantum must be an exact finite positive numeric value")
        return data


class MechanismDataIdentity(BaseModel):
    """One behavior-affecting data identity bound into the mechanism.

    A declared dataset or derived data layer that can affect mechanism
    behavior, carried as its stable identifier and content hash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_id: IdentifierString
    data_content_hash: Sha256Hex


class MechanismParameterBinding(BaseModel):
    """One parameter/unit binding of the mechanism configuration.

    Binds one declared parameter to its unit and, optionally, to the
    behavior-affecting data identity it derives from (both the data
    identifier and its content hash, or neither).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: IdentifierString
    unit: str | None = None
    data_id: IdentifierString | None = None
    data_content_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def _data_identity_both_or_neither(self) -> MechanismParameterBinding:
        if (self.data_id is None) != (self.data_content_hash is None):
            raise ValueError("data_id and data_content_hash must both be present or both be absent")
        return self


class MechanismExogenousInput(BaseModel):
    """One ordered, coordinate-addressed exogenous input value.

    The complete recorded coordinate binds the request's world, seed,
    optional realization, run, and step identity plus the stream,
    variable, exactly one of entity or slot, and the non-negative draw
    index, so mechanism branching, call order, retries, or scheduling
    cannot shift unrelated draws. The value is exact and finite per its
    declared kind: integer kinds require an exact ``int``; number kinds
    accept an exact finite ``int`` or ``float`` without conversion. The
    ``content_hash`` is the caller-declared content hash of this entry's
    value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    stream: IdentifierString
    variable: IdentifierString
    entity_id: IdentifierString | None = None
    slot_id: IdentifierString | None = None
    draw_index: StrictNonNegativeInt
    value_kind: Literal["integer", "number"]
    unit: str | None = None
    value: ExactNumeric
    content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    realization_id: IdentifierString | None = None
    realization_content_hash: Sha256Hex | None = None
    run_id: IdentifierString
    step_index: StrictNonNegativeInt

    @model_validator(mode="before")
    @classmethod
    def _raw_value_matches_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_kind = data.get("value_kind")
        raw_value = data.get("value")
        if raw_kind == "integer":
            if not (_is_exact_finite_numeric(raw_value) and isinstance(raw_value, int)):
                raise ValueError("integer entries require an exact int value")
        elif raw_kind == "number" and not _is_exact_finite_numeric(raw_value):
            raise ValueError("number entries require an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _entity_or_slot_exactly_one(self) -> MechanismExogenousInput:
        if (self.entity_id is None) == (self.slot_id is None):
            raise ValueError("exactly one of entity_id or slot_id must be present")
        return self

    @model_validator(mode="after")
    def _realization_both_or_neither(self) -> MechanismExogenousInput:
        if (self.realization_id is None) != (self.realization_content_hash is None):
            raise ValueError(
                "realization_id and realization_content_hash must both be present or both be absent"
            )
        return self

    @property
    def coordinate(self) -> tuple[str, str, str, str, int]:
        """The complete unique coordinate of this entry.

        ``(stream, variable, subject_kind, subject, draw_index)`` where
        ``subject_kind`` is ``"entity"`` or ``"slot"`` and ``subject``
        is the entity or slot identifier.
        """
        if self.entity_id is not None:
            return (self.stream, self.variable, "entity", self.entity_id, self.draw_index)
        assert self.slot_id is not None
        return (self.stream, self.variable, "slot", self.slot_id, self.draw_index)


class MechanismEmissionRecord(BaseModel):
    """One typed, ordered emission of a mechanism step result.

    Carries a unique identifier, a contiguous sequence position, the
    referenced emission schema identity and hash, a required self-covering
    ``content_hash``, an optional unit, and a finite exact-JSON payload.
    Emissions are declarative evidence records; nothing here interprets,
    evaluates, or persists them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    sequence_position: StrictNonNegativeInt
    emission_schema_id: IdentifierString
    emission_schema_hash: Sha256Hex
    content_hash: Sha256Hex
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    unit: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _raw_payload_is_exact_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _reject_non_json_tree("payload", data)
        return data

    @model_validator(mode="after")
    def _payload_contains_no_non_finite(self) -> MechanismEmissionRecord:
        if _contains_non_finite(self.payload):
            raise ValueError("payload must contain only finite JSON-compatible values")
        return self


class MechanismEvidenceRecord(BaseModel):
    """One deterministic, ordered mechanism-evidence record.

    Carries a unique identifier, a contiguous sequence position, the
    referenced evidence schema identity and hash, a required self-covering
    ``content_hash``, and a finite exact-JSON payload. Evidence is
    immutable declarative data; no analyzer or projection may mutate
    mechanism state through it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    sequence_position: StrictNonNegativeInt
    evidence_schema_id: IdentifierString
    evidence_schema_hash: Sha256Hex
    content_hash: Sha256Hex
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_payload_is_exact_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _reject_non_json_tree("payload", data)
        return data

    @model_validator(mode="after")
    def _payload_contains_no_non_finite(self) -> MechanismEvidenceRecord:
        if _contains_non_finite(self.payload):
            raise ValueError("payload must contain only finite JSON-compatible values")
        return self


class DomainMechanismSpec(VersionedContract):
    """Immutable declarative identity of one domain mechanism.

    Binds the pack/manifest identity, the mechanism identity and
    mechanism protocol version ``1.0.0``, the five schema identities and
    hashes, the immutable configuration and its hash, the implementation,
    dependency-lock, solver, and data identities, the parameter/unit
    bindings, the positive exact timestep with explicit unit, the
    non-empty unique explicitly ordered event and reduction orders, the
    frozen numeric profile (``kalhas-platform-bound-binary64-v1``, IEEE-
    754 binary64, round-to-nearest ties-to-even), the explicitly named
    unique quantization boundaries, the recorded platform identity, the
    self-covering content hash, the timezone-aware caller-supplied
    declaration time, and finite metadata.

    The platform identity must agree exactly with the spec-level
    implementation, dependency-lock, solver, and numeric-profile
    identities; any disagreement fails closed. Every behavior-affecting
    identity change requires a new appropriate identity/version; an
    in-place change is never expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: IdentifierString
    pack_version: MechanismSemVer
    manifest_id: IdentifierString
    manifest_content_hash: Sha256Hex
    mechanism_id: IdentifierString
    mechanism_version: MechanismSemVer
    mechanism_protocol_version: MechanismProtocolVersion
    state_schema_id: IdentifierString
    action_schema_id: IdentifierString
    configuration_schema_id: IdentifierString
    emission_schema_id: IdentifierString
    evidence_schema_id: IdentifierString
    state_schema_hash: Sha256Hex
    action_schema_hash: Sha256Hex
    configuration_schema_hash: Sha256Hex
    emission_schema_hash: Sha256Hex
    evidence_schema_hash: Sha256Hex
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    configuration_hash: Sha256Hex
    implementation_id: IdentifierString
    implementation_version: MechanismSemVer
    implementation_hash: Sha256Hex
    dependency_lock_hash: Sha256Hex
    solver_id: IdentifierString
    solver_version: MechanismSemVer
    data_identities: tuple[MechanismDataIdentity, ...] = Field(default_factory=tuple)
    parameter_bindings: tuple[MechanismParameterBinding, ...] = Field(default_factory=tuple)
    timestep: StrictPositiveNumeric
    timestep_unit: IdentifierString
    event_order: tuple[IdentifierString, ...] = Field(min_length=1)
    reduction_order: tuple[IdentifierString, ...] = Field(min_length=1)
    numeric_profile: NumericProfileLiteral
    precision: PrecisionLiteral
    rounding_mode: RoundingModeLiteral
    quantization_boundaries: tuple[MechanismQuantizationBoundary, ...] = Field(
        default_factory=tuple
    )
    platform_identity: MechanismPlatformIdentity
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_configuration_and_metadata_are_exact_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _reject_non_json_tree("configuration", data)
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _orders_are_unique(self) -> DomainMechanismSpec:
        for name, order in (
            ("event_order", self.event_order),
            (
                "reduction_order",
                self.reduction_order,
            ),
        ):
            if len(set(order)) != len(order):
                raise ValueError(f"{name} entries must be unique")
        return self

    @model_validator(mode="after")
    def _boundaries_and_identities_are_unique(self) -> DomainMechanismSpec:
        boundary_ids = [boundary.boundary_id for boundary in self.quantization_boundaries]
        if len(set(boundary_ids)) != len(boundary_ids):
            raise ValueError("quantization boundary ids must be unique")
        data_ids = [identity.data_id for identity in self.data_identities]
        if len(set(data_ids)) != len(data_ids):
            raise ValueError("data identity ids must be unique")
        parameter_ids = [binding.parameter_id for binding in self.parameter_bindings]
        if len(set(parameter_ids)) != len(parameter_ids):
            raise ValueError("parameter binding ids must be unique")
        return self

    @model_validator(mode="after")
    def _configuration_and_metadata_finite(self) -> DomainMechanismSpec:
        if _contains_non_finite(self.configuration):
            raise ValueError("configuration must contain only finite JSON-compatible values")
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _platform_identity_agrees(self) -> DomainMechanismSpec:
        platform = self.platform_identity
        for spec_value, platform_value, name in (
            (self.implementation_id, platform.implementation_id, "implementation_id"),
            (
                self.implementation_version,
                platform.implementation_version,
                "implementation_version",
            ),
            (self.implementation_hash, platform.implementation_hash, "implementation_hash"),
            (self.dependency_lock_hash, platform.dependency_lock_hash, "dependency_lock_hash"),
            (self.solver_id, platform.solver_id, "solver_id"),
            (self.solver_version, platform.solver_version, "solver_version"),
            (self.numeric_profile, platform.numeric_profile, "numeric_profile"),
        ):
            if spec_value != platform_value:
                raise ValueError(f"platform_identity disagrees with the spec {name}")
        return self


class DomainMechanismStepRequest(VersionedContract):
    """Immutable step request: verified state, action, exogenous inputs,
    configuration.

    Represents exactly ``verified state + validated action + ordered
    coordinate-addressed exogenous inputs + immutable configuration``.
    Binds the mechanism-spec reference, the required opaque release-
    profile identity reference (id and content hash - never a partial
    reference, and never an implementation of that profile), the
    scenario/world/seed/run/step identity, the copied state, action, and
    configuration schema identities, the three payloads with their
    content hashes, and the canonically ordered exogenous entries. Every
    entry must copy and match the request's world, seed,
    optional-realization, run, and step identity, carry a unique
    identifier and a unique complete coordinate, and appear in the
    documented canonical coordinate order ``(stream, variable,
    subject_kind, subject, draw_index)``; noncanonical order is rejected
    instead of being sorted. Empty exogenous input is valid. There is no
    timestamp and no wall-clock authority anywhere in a request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism_spec_id: IdentifierString
    mechanism_spec_content_hash: Sha256Hex
    release_profile_id: IdentifierString
    release_profile_content_hash: Sha256Hex
    realization_id: IdentifierString | None = None
    realization_content_hash: Sha256Hex | None = None
    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    run_id: IdentifierString
    step_index: StrictNonNegativeInt
    state_schema_id: IdentifierString
    action_schema_id: IdentifierString
    configuration_schema_id: IdentifierString
    state_schema_hash: Sha256Hex
    action_schema_hash: Sha256Hex
    configuration_schema_hash: Sha256Hex
    state_payload: dict[str, JsonValue] = Field(default_factory=dict)
    action_payload: dict[str, JsonValue] = Field(default_factory=dict)
    configuration_payload: dict[str, JsonValue] = Field(default_factory=dict)
    state_hash: Sha256Hex
    action_hash: Sha256Hex
    configuration_hash: Sha256Hex
    exogenous_inputs: tuple[MechanismExogenousInput, ...] = Field(default_factory=tuple)
    content_hash: Sha256Hex

    @model_validator(mode="before")
    @classmethod
    def _raw_payloads_are_exact_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field_name in ("state_payload", "action_payload", "configuration_payload"):
                _reject_non_json_tree(field_name, data)
        return data

    @model_validator(mode="after")
    def _realization_both_or_neither(self) -> DomainMechanismStepRequest:
        if (self.realization_id is None) != (self.realization_content_hash is None):
            raise ValueError(
                "realization_id and realization_content_hash must both be present or both be absent"
            )
        return self

    @model_validator(mode="after")
    def _payloads_contain_no_non_finite(self) -> DomainMechanismStepRequest:
        for name, payload in (
            ("state_payload", self.state_payload),
            ("action_payload", self.action_payload),
            ("configuration_payload", self.configuration_payload),
        ):
            if _contains_non_finite(payload):
                raise ValueError(f"{name} must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _entries_agree_and_are_canonical(self) -> DomainMechanismStepRequest:
        identifiers = [entry.identifier for entry in self.exogenous_inputs]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("exogenous entry identifiers must be unique")
        coordinates = [entry.coordinate for entry in self.exogenous_inputs]
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("exogenous entry coordinates must be unique")
        ordering = [
            (
                entry.stream,
                entry.variable,
                entry.coordinate[2],
                entry.coordinate[3],
                entry.draw_index,
            )
            for entry in self.exogenous_inputs
        ]
        if ordering != sorted(ordering):
            raise ValueError(
                "exogenous entries must appear in canonical coordinate order "
                "(stream, variable, subject_kind, subject, draw_index)"
            )
        for entry in self.exogenous_inputs:
            if (
                entry.world_version_id != self.world_version_id
                or entry.world_content_hash != self.world_content_hash
                or entry.seed_id != self.seed_id
                or entry.seed_content_hash != self.seed_content_hash
                or entry.run_id != self.run_id
                or entry.step_index != self.step_index
            ):
                raise ValueError("exogenous entries must copy the request identity")
            if (entry.realization_id is None) != (self.realization_id is None) or (
                entry.realization_id is not None
                and (
                    entry.realization_id != self.realization_id
                    or entry.realization_content_hash != self.realization_content_hash
                )
            ):
                raise ValueError(
                    "exogenous entries must copy the optional realization identity exactly"
                )
        return self


class DomainMechanismStepResult(VersionedContract):
    """Immutable step result: verified next state, emissions, evidence.

    Represents exactly ``verified next state + ordered typed emissions +
    ordered deterministic mechanism evidence``. Binds the request,
    mechanism-spec, and required release-profile identity references, the
    same world/seed/optional-realization/run/step identity, the verified
    next state with its schema identity, schema hash, and state hash,
    ordered emission and evidence records with unique identifiers and
    contiguous sequence positions from zero, and the self-covering
    content hash. No time, persistence receipt, recommendation, winner,
    scheduler, or external effect is expressible. Foreign identities,
    gaps, duplicates, reordered positions, invalid schemas, and
    non-finite payloads fail closed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: IdentifierString
    request_content_hash: Sha256Hex
    mechanism_spec_id: IdentifierString
    mechanism_spec_content_hash: Sha256Hex
    release_profile_id: IdentifierString
    release_profile_content_hash: Sha256Hex
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    realization_id: IdentifierString | None = None
    realization_content_hash: Sha256Hex | None = None
    run_id: IdentifierString
    step_index: StrictNonNegativeInt
    next_state_schema_id: IdentifierString
    next_state_schema_hash: Sha256Hex
    next_state_payload: dict[str, JsonValue] = Field(default_factory=dict)
    next_state_hash: Sha256Hex
    emissions: tuple[MechanismEmissionRecord, ...] = Field(default_factory=tuple)
    evidence: tuple[MechanismEvidenceRecord, ...] = Field(default_factory=tuple)
    content_hash: Sha256Hex

    @model_validator(mode="before")
    @classmethod
    def _raw_next_state_payload_is_exact_json(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _reject_non_json_tree("next_state_payload", data)
        return data

    @model_validator(mode="after")
    def _realization_both_or_neither(self) -> DomainMechanismStepResult:
        if (self.realization_id is None) != (self.realization_content_hash is None):
            raise ValueError(
                "realization_id and realization_content_hash must both be present or both be absent"
            )
        return self

    @model_validator(mode="after")
    def _payload_contains_no_non_finite(self) -> DomainMechanismStepResult:
        if _contains_non_finite(self.next_state_payload):
            raise ValueError("next_state_payload must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _emissions_are_contiguous_and_unique(self) -> DomainMechanismStepResult:
        _require_contiguous_unique("emissions", self.emissions)
        return self

    @model_validator(mode="after")
    def _evidence_is_contiguous_and_unique(self) -> DomainMechanismStepResult:
        _require_contiguous_unique("evidence", self.evidence)
        return self


class _SequencedMechanismRecord(Protocol):
    """Structural surface shared by emission and evidence records.

    A local ``Protocol`` (plus a PEP 695 generic and ``Sequence``) keeps
    ``_require_contiguous_unique`` precisely typed: mypy preserves the
    concrete record element type instead of reducing the historical
    tuple-union parameter to ``BaseModel``.
    """

    @property
    def identifier(self) -> str: ...

    @property
    def sequence_position(self) -> int: ...


def _require_contiguous_unique[RecordT: _SequencedMechanismRecord](
    name: str, records: Sequence[RecordT]
) -> None:
    """Reject gaps, duplicates, or reordered sequence positions.

    Positions must be exactly ``0..N-1`` in recorded order and every
    identifier must be unique within the collection.
    """
    for expected_position, record in enumerate(records):
        if record.sequence_position != expected_position:
            raise ValueError(f"{name} sequence positions must be contiguous from zero in order")
    identifiers = [record.identifier for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{name} identifiers must be unique")
