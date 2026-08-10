"""Domain state-transition contracts: immutable declarative transition specifications.

A ``DomainStateTransition`` is **data only** - the declarative
specification of one possible state change for an already-declared
``DomainStateModel`` of a scenario-bound domain pack. It describes what a
transition *would* mean, never what it does: a guard is only a declarative
equality condition over state fields, and a target is only a declarative
intended state patch. Nothing here executes transitions, mutates state,
invokes domain packs, evaluates formulas or expressions, generates
outcomes, creates evidence, produces recommendations, or performs any
real-world action. No callbacks, scripts, expressions, formulas,
evaluators, code references, providers, imports, dynamic loading,
policies, LLM calls, or executable mechanisms can be expressed by these
field types.

``DomainStateTransition`` is an immutable ``VersionedContract`` anchored to
an existing ``DomainStateModel``: the scenario, binding, manifest, logical
``pack_id``, semantic ``pack_version``, authoritative manifest content
hash, and the referenced state model's authoritative content hash are
copied exclusively from stored immutable records - never from client
input. The ``transition_id`` is a stable, non-empty client-chosen name
for the transition; the deterministic transition identifier is
hash-derived from the canonical scenario/manifest/state-model/transition
identity, and the ``content_hash`` is the SHA-256 digest of the canonical
serialized transition content excluding ``content_hash`` itself. Guard and
target mappings are canonicalized by field identifier for identity, hash,
stored representation, and world-snapshot purposes, so equivalent caller
key orderings produce the same canonical representation and hash.

Every guard/target key must identify an existing field of the referenced
state model, every guard/target value must exactly match that field's
``StateValueKind``, and ``allowed_values`` are enforced when the
referenced field declares them - these checks need the referenced state
model, so they live in the application service, not here. What this
contract guarantees on its own: ``transition_id`` is non-empty,
``target_values`` is non-empty, hashes and ``pack_version`` follow the
strict patterns, and no non-finite float (NaN/Infinity) appears anywhere
in the guard values, target values, or metadata - including arbitrarily
nested inside JSON-compatible trees (booleans are never silently accepted
as integers or numbers by any downstream kind check).

Nothing here loads, imports, instantiates, or executes a domain pack.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"


class DomainStateTransition(VersionedContract):
    """Immutable declarative specification of one possible state change.

    The transition is anchored to an existing ``DomainStateModel``:
    every identity field (binding id, manifest id, logical ``pack_id``,
    semantic ``pack_version``, authoritative manifest content hash, and
    the referenced state model's authoritative content hash) is copied
    from stored immutable records - never from client input. The stable
    ``transition_id`` is a non-empty client-chosen name; the
    transition's deterministic identifier is hash-derived from the
    canonical scenario/manifest/state-model/transition identity, and
    ``content_hash`` is the SHA-256 digest of the canonical serialized
    transition content excluding ``content_hash`` itself.

    ``guard_values`` and ``target_values`` are canonicalized by field
    identifier: equivalent caller key orderings produce the same
    canonical transition, hash, and world snapshot. A guard is only a
    declarative equality condition and a target is only a declarative
    intended state patch - neither is ever evaluated, compared, or
    applied here. ``target_values`` must be non-empty; ``guard_values``
    may be empty (an unconditional transition). The transition is frozen
    by contract and is never updated, deleted, replaced, or re-declared;
    it specifies possible transitions only and never executes anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    binding_id: str
    manifest_id: str
    pack_id: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    state_model_id: str
    state_model_content_hash: str = Field(pattern=_SHA256_PATTERN)
    transition_id: str = Field(min_length=1)
    description: str
    guard_values: dict[str, JsonValue] = Field(default_factory=dict)
    target_values: dict[str, JsonValue] = Field(default_factory=dict)
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _target_values_non_empty(self) -> DomainStateTransition:
        """A transition must declare at least one intended target field."""
        if not self.target_values:
            raise ValueError("target_values must be non-empty")
        return self

    @model_validator(mode="after")
    def _values_and_metadata_contain_no_non_finite(self) -> DomainStateTransition:
        """Guard values, target values, and metadata must be finite JSON.

        Non-finite floats (NaN/Infinity) are not valid JSON and are
        rejected anywhere they appear - top-level or arbitrarily nested
        inside arrays and objects.
        """
        if _contains_non_finite(self.guard_values):
            raise ValueError("guard_values must contain only finite JSON-compatible values")
        if _contains_non_finite(self.target_values):
            raise ValueError("target_values must contain only finite JSON-compatible values")
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
