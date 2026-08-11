"""Strict typed request models for the Phase 24 uncertainty-model endpoints.

The declaration request accepts only caller-owned values: per binding
``manifest_id``, ``state_model_id``, ``state_field_id``, the closed
``distribution`` specification, the ``rounding_policy`` (when
applicable), and the independently optional ``lower_bound``/
``upper_bound``; at model level ``declared_at`` and optional
``metadata``. It deliberately accepts no ``tenant_id``,
``scenario_id``, ``scenario_content_hash``, binding/pack/state-model
provenance, identifiers, content hashes, sampler literals, or
quantization literals: every authoritative identity and snapshot field
is copied from stored immutable records by the service, and every
content hash is always computed - a client-supplied hash is never
accepted. Unknown fields are rejected. Booleans, strings, containers,
NaN, and Infinity are rejected before any coercion, so invalid drafts
fail with 422 before reaching the service.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import (
    DistributionSpecification,
    StrictFiniteFloat,
    StrictInt,
)

#: Strict int | strict finite float | None with pre-coercion rejection of
#: bool, strings, containers, NaN, and Infinity. Pydantic never converts
#: an integer bound into ``1.0`` or a float bound into ``1``; canonical
#: JSON and content hashes preserve the caller-owned bound type.
BoundNumber = StrictInt | StrictFiniteFloat

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]


class UncertaintyBindingDeclaration(BaseModel):
    """One caller-owned uncertainty-binding draft.

    Accepts only the target tuple, the distribution specification, the
    rounding policy, and the independently optional clipping bounds.
    Every authoritative provenance field is copied by the service from
    stored immutable records; no identifiers, hashes, or sampler/
    quantization literals are accepted.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: IdentifierString
    state_model_id: IdentifierString
    state_field_id: IdentifierString
    distribution: DistributionSpecification
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = None
    lower_bound: BoundNumber | None = None
    upper_bound: BoundNumber | None = None


class WorldUncertaintyModelDeclarationRequest(BaseModel):
    """Request to declare an immutable scenario uncertainty model.

    Accepts only ``bindings``, ``declared_at``, and optional
    ``metadata``. Binding target tuples must be unique (the exact
    canonicalization, coverage, and field rules are enforced by the
    service against the stored scenario records), and metadata must
    hold only finite JSON-compatible values, so invalid drafts fail
    with 422 before reaching the service.
    """

    model_config = ConfigDict(extra="forbid")

    bindings: tuple[UncertaintyBindingDeclaration, ...] = Field(min_length=1)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_target_tuples(self) -> WorldUncertaintyModelDeclarationRequest:
        targets = [
            (binding.manifest_id, binding.state_model_id, binding.state_field_id)
            for binding in self.bindings
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("bindings must carry unique target tuples")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> WorldUncertaintyModelDeclarationRequest:
        """Metadata must hold only finite JSON-compatible values (typed 422)."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
