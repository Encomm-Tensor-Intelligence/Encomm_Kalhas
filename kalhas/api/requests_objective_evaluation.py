"""Strict typed request models for the Phase 23 objective-evaluation endpoints.

The declaration request accepts only caller-owned values: per binding
``objective_id``, ``metric_id``, ``reach_tolerance``, and
``normalization_scale``; at profile level ``declared_at`` and optional
``metadata``. It deliberately accepts no ``direction``, ``target``,
``weight``, ``metric_unit``, ``identifier``, ``tenant_id``,
``scenario_id``, ``scenario_content_hash``, ``schema_version``, or
``content_hash``: every authoritative identity and snapshot field is
copied from stored immutable records by the service, and the profile
content hash is always computed - a client-supplied hash is never
accepted. Unknown fields are rejected. Non-finite floats (NaN/Infinity)
and booleans are rejected anywhere they appear, so invalid drafts fail
with 422 before reaching the service.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import _contains_non_finite


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value.

    Booleans are never accepted as integers or numbers, and non-finite
    floats (NaN/Infinity) are rejected. Strings, ``None``, and
    containers are rejected - no numeric coercion of any kind happens.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


class ObjectiveMetricBindingDeclaration(BaseModel):
    """One caller-owned objective-to-metric binding draft.

    Accepts only ``objective_id``, ``metric_id``, ``reach_tolerance``,
    and ``normalization_scale``. ``reach_tolerance`` must be finite and
    non-negative when supplied (the direction-specific required/
    forbidden rules are enforced by the service against the stored
    scenario objective); ``normalization_scale`` must be exact numeric,
    finite, and strictly positive. Booleans, strings, ``None`` where
    prohibited, NaN, and Infinity are rejected before any coercion.
    """

    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    reach_tolerance: float | None = None
    normalization_scale: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        """Reject bool/non-numeric raw values before any coercion."""
        if not isinstance(data, dict):
            return data
        for key in ("reach_tolerance", "normalization_scale"):
            raw = data.get(key)
            if raw is None:
                continue
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _tolerance_and_scale_rules(self) -> ObjectiveMetricBindingDeclaration:
        """Reach tolerance must be finite and non-negative; scale strictly positive."""
        if self.reach_tolerance is not None and self.reach_tolerance < 0.0:
            raise ValueError("reach_tolerance must be non-negative")
        if not math.isfinite(self.normalization_scale) or self.normalization_scale <= 0.0:
            raise ValueError("normalization_scale must be finite and strictly positive")
        return self


class ObjectiveEvaluationProfileDeclarationRequest(BaseModel):
    """Request to declare an immutable scenario evaluation profile.

    Accepts only ``bindings``, ``declared_at``, and optional
    ``metadata``. Binding objective identifiers must be unique (the
    exact scenario coverage and ordering rules are enforced by the
    service against the stored scenario), and metadata must hold only
    finite JSON-compatible values, so invalid drafts fail with 422
    before reaching the service.
    """

    model_config = ConfigDict(extra="forbid")

    bindings: tuple[ObjectiveMetricBindingDeclaration, ...] = Field(min_length=1)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_objective_identifiers(self) -> ObjectiveEvaluationProfileDeclarationRequest:
        identifiers = [binding.objective_id for binding in self.bindings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("bindings must carry unique objective identifiers")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> ObjectiveEvaluationProfileDeclarationRequest:
        """Metadata must hold only finite JSON-compatible values (typed 422)."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
