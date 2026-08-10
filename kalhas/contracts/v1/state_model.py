"""Domain state-model contracts: immutable declarative state-field definitions.

A ``DomainStateModel`` is **data only** - the declarative definition of
which state fields exist for a scenario-bound domain pack, their value
kinds, their initial values, and optionally the exact set of allowed
values. It defines state *schema*, never behavior: nothing here executes
transitions, formulas, expressions, policies, mechanisms, simulations,
outcomes, metrics, evidence, recommendations, briefs, or real-world
actions. No callbacks, imports, executable expressions, provider
references, or runtime behavior can be expressed by these field types.

``DomainStateFieldDefinition`` declares one state field: a stable
identifier, a description, a ``StateValueKind`` (``string``, ``integer``,
``number``, ``boolean``, ``json``), an ``initial_value`` that must exactly
match the declared kind, an optional tuple of ``allowed_values`` (every
entry must match the kind, be canonically unique, and include the initial
value), and optional JSON-compatible metadata. Booleans are never
silently accepted as integers or numbers, and non-finite numbers are
rejected everywhere.

``DomainStateModel`` is an immutable ``VersionedContract`` anchored to an
existing ``DomainPackBinding``: the scenario, binding, and manifest
identifiers, the logical ``pack_id``, the semantic ``pack_version``, and
the authoritative manifest content hash are copied exclusively from
stored immutable records - never from client input. The
``state_model_id`` is a stable, non-empty client-chosen name for the
model; the deterministic model identifier is hash-derived from the
canonical scenario/manifest/state-model identity, and the model
``content_hash`` is the SHA-256 digest of the canonical serialized model
content excluding ``content_hash`` itself. State fields are canonicalized
by identifier for identity, hash, and world-snapshot purposes, so
equivalent caller field orderings produce the same canonical
representation and hash.

Nothing here loads, imports, instantiates, or executes a domain pack.
"""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"


def _canonical_value_text(value: JsonValue) -> str:
    """Render a JSON-compatible value in the repository's canonical form.

    Mirrors ``kalhas.application.hashing.canonical_json`` (sorted keys, no
    insignificant whitespace) but lives here as a pure stdlib helper used
    ONLY for equality comparisons inside contract validation - never for
    hashing, which stays exclusively in the application layer.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _contains_non_finite(value: object) -> bool:
    """Return True when a JSON-compatible value contains any non-finite float.

    Pure recursive structural scan over JSON-compatible trees (dicts,
    lists, and primitives). NaN and Infinity are not valid JSON, so they
    are rejected anywhere they appear - top-level or nested arbitrarily
    deep inside arrays and objects. Declarative and standard-library
    only: nothing here is evaluated or executed.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_non_finite(item) for item in value.values())
    return False


def _value_matches_kind(value: Any, kind: StateValueKind) -> bool:
    """Return True when the raw value exactly matches the declared kind.

    The checks run against the raw input before any Pydantic coercion, so
    a boolean can never slip through as an integer or number, and
    non-finite floats (top-level or nested) are rejected for every kind -
    they are not valid JSON.
    """
    if kind is StateValueKind.STRING:
        return isinstance(value, str)
    if kind is StateValueKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is StateValueKind.NUMBER:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        return not isinstance(value, float) or math.isfinite(value)
    if kind is StateValueKind.BOOLEAN:
        return isinstance(value, bool)
    if kind is StateValueKind.JSON:
        if not isinstance(value, (str, int, float, bool, type(None), list, dict)):
            return False
        return not _contains_non_finite(value)
    return False


class StateValueKind(StrEnum):
    """The declared value kind of one state field.

    ``json`` accepts any JSON-compatible value (the widest kind). The
    kinds are structural only: they describe data shapes, never behavior.
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class DomainStateFieldDefinition(BaseModel):
    """One declarative state field of a scenario-bound domain pack.

    The field declares its stable identifier, a description, its value
    kind, an initial value that must exactly match the kind, an optional
    tuple of allowed values (all matching the kind, canonically unique,
    and including the initial value), and optional JSON-compatible
    metadata. It is data only: no formulas, expressions, policies,
    callbacks, or executable content can be expressed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: str = Field(min_length=1)
    description: str
    value_kind: StateValueKind
    initial_value: JsonValue
    allowed_values: tuple[JsonValue, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_match_kind(cls, data: Any) -> Any:
        """Reject kind mismatches on the raw input, before any coercion.

        Pydantic lax mode would otherwise accept ``True`` as an integer
        or number; checking the un-coerced input keeps booleans out of
        ``integer``/``number`` fields and non-finite floats out of every
        kind.
        """
        if not isinstance(data, dict):
            return data
        raw_kind = data.get("value_kind")
        if not isinstance(raw_kind, str):
            return data  # invalid enum is reported by field validation
        try:
            kind = StateValueKind(raw_kind)
        except ValueError:
            return data  # invalid enum is reported by field validation
        if not _value_matches_kind(data.get("initial_value"), kind):
            raise ValueError(f"initial_value does not match the declared value kind {kind.value!r}")
        allowed = data.get("allowed_values", ())
        if allowed:
            for index, value in enumerate(allowed):
                if not _value_matches_kind(value, kind):
                    raise ValueError(
                        f"allowed_values[{index}] does not match the declared value kind "
                        f"{kind.value!r}"
                    )
        return data

    @model_validator(mode="after")
    def _allowed_values_canonically_unique(self) -> DomainStateFieldDefinition:
        """Reject duplicate allowed values under canonical JSON equality."""
        if not self.allowed_values:
            return self
        canonical = [_canonical_value_text(value) for value in self.allowed_values]
        if len(canonical) != len(set(canonical)):
            raise ValueError("allowed_values must be canonically unique")
        return self

    @model_validator(mode="after")
    def _initial_value_is_allowed(self) -> DomainStateFieldDefinition:
        """The initial value must be one of the allowed values (canonically)."""
        if not self.allowed_values:
            return self
        initial = _canonical_value_text(self.initial_value)
        allowed = [_canonical_value_text(value) for value in self.allowed_values]
        if initial not in allowed:
            raise ValueError("initial_value must be one of the allowed_values")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> DomainStateFieldDefinition:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class DomainStateModel(VersionedContract):
    """Immutable declarative state schema for a scenario-bound domain pack.

    The model is anchored to an existing ``DomainPackBinding``: every
    identity field (binding id, manifest id, logical ``pack_id``, semantic
    ``pack_version``, authoritative manifest content hash) is copied from
    stored immutable records - never from client input. The stable
    ``state_model_id`` is a non-empty client-chosen name; the model's
    deterministic identifier is hash-derived from the canonical
    scenario/manifest/state-model identity, and ``content_hash`` is the
    SHA-256 digest of the canonical serialized model content excluding
    ``content_hash`` itself.

    ``state_fields`` are canonicalized by identifier: equivalent caller
    orderings produce the same canonical model, hash, and world snapshot.
    The model is frozen by contract and is never updated, deleted,
    replaced, or re-declared; it defines state fields only and never
    executes, interprets, or derives anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    binding_id: str
    manifest_id: str
    pack_id: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    state_model_id: str = Field(min_length=1)
    state_fields: tuple[DomainStateFieldDefinition, ...] = Field(default_factory=tuple)
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_state_field_identifiers(self) -> DomainStateModel:
        identifiers = [field.identifier for field in self.state_fields]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("state field identifiers must be unique")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> DomainStateModel:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
