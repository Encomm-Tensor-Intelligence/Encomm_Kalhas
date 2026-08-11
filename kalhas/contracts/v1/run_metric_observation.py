"""Run metric observation contracts: immutable raw metric observations (Phase 20).

Phase 20 adds the **deterministic run metric-observation artifact**: the
immutable, tenant-scoped raw observation collection extracted from a
completely verified runtime 2.0.0 ``RunTrajectoryExecution``, using only
the ``DomainMetricObservationBinding`` snapshots embedded in the run's
exact compiled ``WorldVersion``. It bridges

    DomainMetricObservationBinding
        -> verified RunTrajectoryExecution.final_state
        -> immutable raw metric observations

``RunMetricObservationValue`` is one extracted raw observation: the
metric identity, the metric unit copied from the authoritative embedded
``ScenarioSpec`` (when the metric declares one), the observation
binding's identifier and content hash, the manifest and state-model
identity/content hashes, the observed ``state_field_id``, the
authoritative numeric ``state_field_value_kind`` (``"integer"`` or
``"number"`` only), the observation point (exactly ``"final_state"``),
the trajectory-plan/result identity and content hashes required to
locate the authoritative final state inside the verified execution, and
the exact finite ``raw_value`` read from that final state. Numeric
validation is strict: booleans are never accepted as integers or
numbers, integer bindings require an actual integer (excluding bool),
number bindings accept an actual finite int or float (excluding bool),
NaN and Infinity are rejected everywhere, no numeric coercion ever
happens, and the extracted value is preserved exactly - no
normalization, scaling, transformation, or unit conversion.

``RunMetricObservationSet`` is the complete immutable observation
collection of one run: the run/campaign/plan/scenario identity, the
verified world and strategy identities with their content hashes, the
recorded scenario seed identity, the trajectory runtime version
(exactly ``"2.0.0"``), the run input hash, the verified
``RunTrajectoryExecution`` identifier and content hash, the exact
ordered observation tuple canonicalized by ``metric_id``, the
deterministic ``content_hash`` over the complete canonical payload
excluding ``content_hash`` itself, and the deterministic ``observed_at``
taken from the authoritative trajectory execution's ``executed_at`` -
never wall-clock time. The set identifier is deterministically derived
from the stable run/runtime identity. An empty observation tuple is
valid only when the verified compiled world contains no observation
binding snapshots.

These contracts are raw extraction and provenance recording only: no
aggregation, no outcomes, no distributions, no evidence, no scoring,
no rankings, no recommendations, and no decision briefs. Nothing here
loads, imports, instantiates, or executes a domain pack, and no field
type can express a callback, expression, formula, code reference,
provider, or executable mechanism.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.metric_observation import (
    NumericStateFieldValueKind,
    ObservationPoint,
)
from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def raw_value_matches_numeric_kind(raw: object, kind: str) -> bool:
    """Return True when the raw value exactly matches the authoritative numeric kind.

    Strict and coercion-free: booleans are never accepted as integers or
    numbers, ``"integer"`` requires an actual ``int`` instance, and
    ``"number"`` accepts an actual finite ``int`` or ``float``. Non-finite
    floats (NaN/Infinity) are rejected because they are not valid JSON.
    Anything else - strings, other types, unknown kinds - is rejected.
    """
    if isinstance(raw, bool):
        return False
    if kind == "integer":
        return isinstance(raw, int)
    if kind == "number":
        if not isinstance(raw, (int, float)):
            return False
        return not isinstance(raw, float) or math.isfinite(raw)
    return False


class RunMetricObservationValue(BaseModel):
    """One immutable raw metric observation extracted from a verified final state.

    Carries the exact provenance required to prove where the value came
    from: the metric identity and its unit (copied from the authoritative
    embedded ``ScenarioSpec`` when declared), the observation binding
    identifier and content hash, the manifest and state-model
    identity/content hashes, the observed state field and its
    authoritative numeric value kind, the observation point (exactly
    ``"final_state"``), the trajectory-plan identity/content hash and the
    exact result content hash required to locate the authoritative final
    state inside the verified ``RunTrajectoryExecution``, and the exact
    finite ``raw_value`` read from ``final_state[state_field_id]`` - with
    no normalization, scaling, transformation, or unit conversion.

    The value is raw extraction data only: nothing here aggregates,
    scores, ranks, produces outcomes/evidence/recommendations, or
    executes anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str = Field(min_length=1)
    metric_unit: str | None = None
    binding_id: str = Field(min_length=1)
    binding_content_hash: str = Field(pattern=_SHA256_PATTERN)
    manifest_id: str = Field(min_length=1)
    state_model_identifier: str = Field(min_length=1)
    state_model_id: str = Field(min_length=1)
    state_model_content_hash: str = Field(pattern=_SHA256_PATTERN)
    state_field_id: str = Field(min_length=1)
    state_field_value_kind: NumericStateFieldValueKind
    observation_point: ObservationPoint = "final_state"
    trajectory_plan_id: str = Field(min_length=1)
    trajectory_plan_content_hash: str = Field(pattern=_SHA256_PATTERN)
    trajectory_result_content_hash: str = Field(pattern=_SHA256_PATTERN)
    raw_value: int | float

    @model_validator(mode="before")
    @classmethod
    def _raw_value_must_match_kind(cls, data: Any) -> Any:
        """Reject kind mismatches on the raw input, before any coercion.

        Pydantic lax mode would otherwise coerce ``True`` into an integer
        or number and strings into numbers; checking the un-coerced input
        keeps booleans and non-numeric values out of ``raw_value`` and
        non-finite floats out of ``"number"`` values.
        """
        if not isinstance(data, dict):
            return data
        raw_kind = data.get("state_field_value_kind")
        if not isinstance(raw_kind, str):
            return data  # invalid literal is reported by field validation
        if not raw_value_matches_numeric_kind(data.get("raw_value"), raw_kind):
            raise ValueError(f"raw_value does not match the authoritative value kind {raw_kind!r}")
        return data

    @model_validator(mode="after")
    def _raw_value_is_finite(self) -> RunMetricObservationValue:
        """Reject non-finite floats in the validated value (defense in depth)."""
        if isinstance(self.raw_value, float) and not math.isfinite(self.raw_value):
            raise ValueError("raw_value must be a finite numeric value")
        return self


class RunMetricObservationSet(VersionedContract):
    """The complete immutable raw metric-observation collection of one run.

    Exactly one artifact per tenant + run: the run/campaign/plan/scenario
    identity, the verified compiled world and the exact recorded strategy
    with their content hashes, the recorded seed identity, the trajectory
    runtime version (exactly ``"2.0.0"``), the run input hash, the
    verified ``RunTrajectoryExecution`` identifier and content hash, the
    exact ordered observation tuple canonicalized by ``metric_id``, the
    deterministic ``content_hash`` over the complete canonical payload
    excluding ``content_hash`` itself, and the deterministic
    ``observed_at`` from the authoritative execution's ``executed_at`` -
    never the wall clock. The identifier is deterministically derived
    from the stable run/runtime identity. An empty observation tuple is
    valid only for a verified compiled world with no observation binding
    snapshots.

    The set is raw extraction and provenance recording only: it never
    aggregates observations, calculates outcomes or distributions,
    produces evidence, scores, rankings, or recommendations, and nothing
    here loads or executes a domain pack.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    run_plan_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    world_version_id: str = Field(min_length=1)
    world_content_hash: str = Field(pattern=_SHA256_PATTERN)
    strategy_candidate_id: str = Field(min_length=1)
    strategy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    scenario_seed_id: str = Field(min_length=1)
    #: The trajectory runtime literal; must stay equal to the
    #: authoritative ``TRAJECTORY_RUNTIME_VERSION_LITERAL`` constant
    #: (asserted by the Phase 20 boundary tests).
    runtime_version: Literal["2.0.0"]
    input_hash: str = Field(pattern=_SHA256_PATTERN)
    trajectory_execution_id: str = Field(min_length=1)
    trajectory_execution_content_hash: str = Field(pattern=_SHA256_PATTERN)
    observations: tuple[RunMetricObservationValue, ...] = Field(default_factory=tuple)
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def _observations_canonicalized_by_metric_id(self) -> RunMetricObservationSet:
        """Observations must be canonicalized by metric identifier.

        The complete collection is ordered by strictly increasing
        ``metric_id`` (unique per run), so equivalent insertion orders
        can never produce different artifacts; an empty tuple satisfies
        the rule vacuously.
        """
        identifiers = [observation.metric_id for observation in self.observations]
        if any(a >= b for a, b in zip(identifiers, identifiers[1:], strict=False)):
            raise ValueError("observations must be canonicalized by metric_id")
        return self
