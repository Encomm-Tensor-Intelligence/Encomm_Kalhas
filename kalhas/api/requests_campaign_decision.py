"""Strict typed request models for the campaign decision policy endpoint.

The declaration request accepts only caller-owned values: the
``target_requirement_mode`` with its exact XOR rule (``global``
requires the global probability and forbids per-objective
requirements; ``per_objective`` requires at least one requirement and
forbids the global probability), the inclusive probability band
``[0.0, 1.0]``, the exact-int ``minimum_sample_count >= 1``, the
finite non-negative ``tie_tolerance``, the exact bool hard-gate flag,
the deterministic ``declared_at`` timestamp, and finite JSON-compatible
``metadata``. The four decision rules (``minimum_sample_count``,
``tie_tolerance``, ``all_targeted_objectives_are_hard_gates``,
``declared_at``) are explicit required fields - there are no silent
defaults.

It deliberately accepts no ``identifier``, ``content_hash``,
``schema_version``, ``tenant_id``, ``campaign_id``, scenario identity
or hash, world identity or hash, evaluation-profile identity or hash,
objective weights, ``tail_alpha``, an algorithm identifier, a runtime
version, or a comparison mode: every authoritative identity and
snapshot field is copied from stored immutable records by the service,
and the fixed tail alpha and algorithm identifier are service-owned.
Unknown fields are rejected. Exact built-in numeric policy is enforced
before any coercion: booleans, strings, ``Decimal``, ``None``,
containers, non-finite floats, and unrepresentable huge integers are
rejected for every numeric field, and the hard-gate flag must be an
uncoerced exact ``bool`` (``0``/``1``, ``0.0``/``1.0``, ``"true"``/
``"false"``, ``Decimal``, ``None``, containers, and arbitrary
truthy/falsy objects are rejected). Metadata must be a genuine
recursively JSON-compatible tree (string keys; values only ``str``,
exact ``int``, finite exact ``float``, exact ``bool``, ``None``,
``list``, ``dict`` - ``Decimal``, numeric subclasses, tuples, sets,
arbitrary objects, NaN, and Infinity rejected) and is never mutated.
No callbacks, expressions, scripts, provider references, or executable
templates are representable.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.campaign_decision import (
    _is_exact_finite_numeric,
    _require_exact_int,
)
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]


def _validate_metadata_tree(value: object) -> None:
    """Require a genuine recursively JSON-compatible tree; raises ``ValueError``.

    Dictionary keys must be exact strings; values may only be ``str``,
    exact ``int``, finite exact ``float``, exact ``bool``, ``None``,
    ``list``, or ``dict``, validated recursively. ``Decimal``, numeric
    subclasses, tuples, sets, arbitrary objects, NaN, and Infinity are
    rejected. The caller mapping is never mutated.
    """
    if value is None:
        return
    if type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("metadata must contain only finite JSON-compatible numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_metadata_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("metadata dictionary keys must be strings")
            _validate_metadata_tree(item)
        return
    raise ValueError("metadata must contain only JSON-compatible values")


class ObjectiveTargetRequirementRequest(BaseModel):
    """One caller-owned per-objective target-achievement requirement draft.

    Accepts only the target ``objective_id`` and its inclusive
    minimum target-achievement probability within ``[0.0, 1.0]``. The
    probability must be an exact finite ``int`` or ``float`` before any
    coercion - booleans, strings, ``Decimal``, ``None``, containers,
    NaN, Infinity, and unrepresentable huge integers are rejected.
    Coverage, ordering, and optimization-only rules are enforced by the
    service against the authoritative stored scenario objectives.
    """

    model_config = ConfigDict(extra="forbid")

    objective_id: IdentifierString
    minimum_target_achievement_probability: float

    @model_validator(mode="before")
    @classmethod
    def _raw_probability_exact_finite(cls, data: object) -> object:
        """Reject non-numeric raw values on the un-coerced input, before any coercion."""
        if not isinstance(data, dict):
            return data
        raw = data.get("minimum_target_achievement_probability")
        if raw is not None and not _is_exact_finite_numeric(raw):
            raise ValueError(
                "minimum_target_achievement_probability must be an exact finite int or float"
            )
        return data

    @model_validator(mode="after")
    def _probability_within_unit_band(self) -> ObjectiveTargetRequirementRequest:
        """Enforce the inclusive probability band."""
        probability = self.minimum_target_achievement_probability
        if probability < 0.0 or probability > 1.0:
            raise ValueError("minimum_target_achievement_probability must be within [0.0, 1.0]")
        return self


class CampaignDecisionPolicyDeclarationRequest(BaseModel):
    """Request to declare an immutable campaign decision policy.

    Accepts only the caller-owned declaration values; the four decision
    rules (``minimum_sample_count``, ``tie_tolerance``,
    ``all_targeted_objectives_are_hard_gates``, ``declared_at``) are
    explicit required fields, and the exact global/per-objective XOR is
    enforced here so an invalid draft fails with a typed 422 before
    reaching the service. The exact built-in numeric policy rejects
    booleans, strings, ``Decimal``, ``None``, containers, non-finite
    floats, and unrepresentable huge integers before any coercion;
    probabilities must lie within the inclusive ``[0.0, 1.0]`` band;
    ``minimum_sample_count`` must be an exact ``int >= 1``;
    ``tie_tolerance`` must be finite and non-negative;
    ``all_targeted_objectives_are_hard_gates`` must be an uncoerced
    exact ``bool``; per-objective requirement objective identifiers
    must be unique; and metadata must be a genuine recursively
    JSON-compatible tree. The requirements tuple is immutable after
    validation (JSON arrays validate into the declared tuple as normal
    request behavior). The coverage and ordering rules against the
    authoritative targeted objectives are enforced by the service.
    """

    model_config = ConfigDict(extra="forbid")

    target_requirement_mode: Literal["global", "per_objective"]
    minimum_sample_count: int = Field(ge=1)
    tie_tolerance: float
    all_targeted_objectives_are_hard_gates: bool
    declared_at: AwareDatetime
    minimum_target_achievement_probability: float | None = None
    objective_target_requirements: tuple[ObjectiveTargetRequirementRequest, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_values_must_be_exact(cls, data: object) -> object:
        """Reject bool/non-numeric raw values before any coercion."""
        if not isinstance(data, dict):
            return data
        raw_minimum = data.get("minimum_sample_count")
        if raw_minimum is not None:
            _require_exact_int(raw_minimum, "minimum_sample_count")
        raw_probability = data.get("minimum_target_achievement_probability")
        if raw_probability is not None and not _is_exact_finite_numeric(raw_probability):
            raise ValueError(
                "minimum_target_achievement_probability must be an exact finite int or float"
            )
        raw_tolerance = data.get("tie_tolerance")
        if raw_tolerance is not None and not _is_exact_finite_numeric(raw_tolerance):
            raise ValueError("tie_tolerance must be an exact finite int or float")
        if "all_targeted_objectives_are_hard_gates" in data:
            raw_gates = data.get("all_targeted_objectives_are_hard_gates")
            if type(raw_gates) is not bool:
                raise ValueError("all_targeted_objectives_are_hard_gates must be an exact bool")
        if "metadata" in data:
            raw_metadata = data.get("metadata")
            if raw_metadata is not None:
                try:
                    _validate_metadata_tree(raw_metadata)
                except ValueError as exc:
                    raise ValueError("metadata must contain only JSON-compatible values") from exc
        return data

    @model_validator(mode="after")
    def _declaration_is_internally_consistent(self) -> CampaignDecisionPolicyDeclarationRequest:
        """Enforce the exact mode XOR, bands, uniqueness, and metadata rules."""
        if self.target_requirement_mode == "global":
            probability = self.minimum_target_achievement_probability
            if probability is None:
                raise ValueError(
                    "global mode requires a global minimum target-achievement probability"
                )
            if self.objective_target_requirements:
                raise ValueError("global mode forbids per-objective target requirements")
            if probability < 0.0 or probability > 1.0:
                raise ValueError("minimum_target_achievement_probability must be within [0.0, 1.0]")
        else:
            if self.minimum_target_achievement_probability is not None:
                raise ValueError("per_objective mode forbids a global probability")
            if not self.objective_target_requirements:
                raise ValueError("per_objective mode requires at least one target requirement")
        if self.tie_tolerance < 0.0:
            raise ValueError("tie_tolerance must be non-negative")
        requirement_ids = [
            requirement.objective_id for requirement in self.objective_target_requirements
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("objective_target_requirements objective identifiers must be unique")
        try:
            _validate_metadata_tree(self.metadata)
        except ValueError as exc:
            raise ValueError("metadata must contain only JSON-compatible values") from exc
        return self


__all__ = [
    "ObjectiveTargetRequirementRequest",
    "CampaignDecisionPolicyDeclarationRequest",
]
