"""Domain metric-observation binding contracts: immutable declarative bindings.

A ``DomainMetricObservationBinding`` is **data only** - the immutable,
tenant-scoped declaration that a future phase *may* observe one numeric
field of an already-declared ``DomainStateModel`` as the raw observation
of exactly one metric declared by the scenario's ``ScenarioSpec``. It
binds identity and provenance only: it declares *what could be observed
and from where*, never *what is observed*. Nothing here inspects a run
trajectory execution, extracts a metric value, evaluates a trajectory,
calculates an outcome, aggregates observations, produces evidence,
ranks strategies, or generates recommendations.

The binding carries no formulas, expressions, callbacks, transformations,
scaling factors, aggregation implementations, executable references,
provider references, observed values, state snapshots, outcomes,
evidence, scores, or recommendations - such content cannot be expressed
by these field types. ``state_field_value_kind`` is restricted to the
numeric kinds (``integer`` and ``number``): a binding may only reference
a state field whose declared ``StateValueKind`` is numeric, because a
future observation phase can only ever read a numeric field as a metric
raw observation. ``observation_point`` is exactly ``"final_state"`` - a
binding always refers to the field's final trajectory state, nothing
else.

``DomainMetricObservationBinding`` is an immutable ``VersionedContract``
anchored to an existing ``DomainPackBinding``, its registered manifest,
and a declared ``DomainStateModel``: the binding identifier, manifest
identifier, logical ``pack_id``, semantic ``pack_version``, authoritative
manifest content hash, the referenced state model's deterministic
identifier and authoritative content hash, and the copied numeric field
value kind are all taken exclusively from stored immutable records -
never from client input. The binding's deterministic identifier is
hash-derived from the canonical
tenant/scenario/metric/manifest/state-model/state-field/observation-point
identity, and ``content_hash`` is the SHA-256 digest of the canonical
serialized binding content excluding ``content_hash`` itself. Metadata
holds only finite JSON-compatible values (non-finite floats such as NaN
or Infinity are rejected anywhere, including arbitrarily nested inside
JSON-compatible trees).

For the Phase 19 MVP exactly one observation binding may exist per
scenario metric: the binding is stored under a
``(tenant_id, scenario_id, metric_id)`` key and is never updated,
deleted, replaced, repaired, or re-declared.

Nothing here loads, imports, instantiates, or executes a domain pack.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"

NumericStateFieldValueKind = Literal["integer", "number"]
"""The numeric state-field value kinds a binding may reference.

A binding may only reference a state field whose declared value kind is
numeric (``integer`` or ``number``); string, boolean, and json fields
are rejected by the declaration service.
"""

ObservationPoint = Literal["final_state"]
"""The single supported observation point: the field's final trajectory state."""


class DomainMetricObservationBinding(VersionedContract):
    """Immutable declarative state-to-metric observation binding.

    The binding connects exactly one scenario metric (identified by
    ``metric_id`` against the stored ``ScenarioSpec``) to exactly one
    numeric field (identified by ``state_field_id``) of an existing
    scenario-bound ``DomainStateModel`` (identified by
    ``state_model_identifier`` and ``state_model_id``). Every identity
    field - binding id, manifest id, logical ``pack_id``, semantic
    ``pack_version``, authoritative manifest content hash, the
    referenced state model's deterministic identifier and authoritative
    content hash - is copied from stored immutable records, never from
    client input. The copied ``state_field_value_kind`` is the
    authoritative numeric value kind of the referenced field.

    The binding declares that a future phase *may* observe the
    referenced field's final trajectory state as the metric's raw
    observation. It is a declaration of provenance only: nothing here
    inspects any ``RunTrajectoryExecution``, reads ``initial_state`` or
    ``final_state``, extracts metric values, evaluates trajectories,
    calculates outcomes, aggregates observations, produces evidence,
    ranks strategies, or generates recommendations.

    The binding is frozen by contract and is never updated, deleted,
    replaced, repaired, or re-declared; at most one binding may exist
    per scenario metric (Phase 19 MVP).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    binding_id: str
    manifest_id: str
    pack_id: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    metric_id: str = Field(min_length=1)
    state_model_identifier: str = Field(min_length=1)
    state_model_id: str = Field(min_length=1)
    state_model_content_hash: str = Field(pattern=_SHA256_PATTERN)
    state_field_id: str = Field(min_length=1)
    state_field_value_kind: NumericStateFieldValueKind
    observation_point: ObservationPoint = "final_state"
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> DomainMetricObservationBinding:
        """Metadata must hold only finite JSON-compatible values.

        Non-finite floats (NaN/Infinity) are not valid JSON and are
        rejected anywhere they appear - top-level or arbitrarily nested
        inside arrays and objects.
        """
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
