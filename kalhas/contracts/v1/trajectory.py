"""Strategy trajectory-plan contracts: immutable, strategy-bound plan proposals.

Phase 15 introduces **planning and recording only**: LEGION may propose
an explicitly ordered sequence of already-declared ``DomainStateTransition``
references, and KALHAS authoritatively verifies, binds, hashes, and stores
the resulting immutable ``StrategyTrajectoryPlan``. Nothing here evaluates
or executes a trajectory: no state is derived, no guard is compared, no
target is applied, and no trajectory result is produced.

The boundary is strict and declarative end to end:

- ``StrategyTrajectoryTransitionReference`` is one authoritative reference
  to an existing transition: its deterministic identifier, its stable
  logical ``transition_id``, and its authoritative content hash. It carries
  **no guard values, no target values, no state snapshots, no outcomes, no
  evidence, no explanations, and no executable behavior**. Repeated
  references are allowed, because an explicitly supplied trajectory may
  intentionally attempt the same declared transition more than once.
- ``StrategyTrajectoryPlanRequest`` is the authoritative, KALHAS-built
  request sent across the ``LegionAdapter`` boundary. It embeds the exact
  stored ``StrategyCandidate``, the exact ``DomainStateModel`` from the
  verified compiled world, and the canonical tuple of that model's
  available ``DomainStateTransition`` snapshots (non-empty). Its
  deterministic identifier is derived by KALHAS from the canonical
  campaign/world/strategy/state-model identity; LEGION never supplies or
  chooses it.
- ``StrategyTrajectoryPlanDraft`` is the **untrusted proposal** returned by
  LEGION: only a request identifier and the ordered transition identifiers
  (minimum 1, maximum 1000). It cannot carry tenant identity, hashes, plan
  identifiers, state values, callbacks, expressions, code, provider
  configuration, or metadata; the service re-validates it even when it
  arrives as a Pydantic instance created through a validator-bypassing
  path.
- ``StrategyTrajectoryPlan`` is the immutable, KALHAS-built
  ``VersionedContract`` that authoritatively binds one prepared campaign,
  one verified compiled world, one exact stored strategy candidate, one
  state model embedded in that world, and an explicitly ordered sequence of
  transitions embedded in the same world. It carries no guard/target
  values, no state snapshots, no outcomes, no evidence, no recommendation,
  and no hidden reasoning. Its ``content_hash`` is the SHA-256 digest of
  the complete canonical plan content excluding ``content_hash`` itself,
  with tuple ordering and transition repetitions significant.

Nothing here loads, imports, instantiates, or executes a domain pack, and
no field type can express a callback, expression, formula, code reference,
provider, or executable mechanism.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.transition import DomainStateTransition

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

MAX_TRAJECTORY_PLAN_TRANSITIONS = 1000


class StrategyTrajectoryTransitionReference(BaseModel):
    """One authoritative reference to a declared transition in a plan.

    Carries only the deterministic transition identifier, the stable
    logical ``transition_id``, and the authoritative content hash - no
    guard values, no target values, no state snapshots, no outcomes, no
    evidence, no explanations, and no executable behavior. Repeated
    references are allowed: an explicitly supplied trajectory may
    intentionally attempt the same declared transition more than once.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_position: int = Field(ge=0)
    transition_identifier: str
    transition_id: str = Field(min_length=1)
    transition_content_hash: str = Field(pattern=_SHA256_PATTERN)


class StrategyTrajectoryPlanRequest(VersionedContract):
    """Authoritative trajectory-plan request sent across the LEGION boundary.

    Built **only by KALHAS** from verified stored records: the prepared
    campaign identity, the verified compiled world identity and content
    hash, the exact stored ``StrategyCandidate`` snapshot with its full
    content hash, the exact ``DomainStateModel`` snapshot from the
    compiled world, and the canonical tuple of that model's available
    ``DomainStateTransition`` snapshots (non-empty). The deterministic
    identifier is derived by KALHAS from the canonical
    campaign/world/strategy/state-model identity; LEGION must not supply
    or choose it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    scenario_id: str
    world_version_id: str
    world_content_hash: str = Field(pattern=_SHA256_PATTERN)
    strategy_candidate: StrategyCandidate
    strategy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    state_model: DomainStateModel
    available_transitions: tuple[DomainStateTransition, ...] = Field(default_factory=tuple)
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def _available_transitions_must_be_non_empty(self) -> StrategyTrajectoryPlanRequest:
        """A request always carries at least one available transition."""
        if not self.available_transitions:
            raise ValueError("available_transitions must be non-empty")
        return self


class StrategyTrajectoryPlanDraft(BaseModel):
    """Untrusted LEGION proposal: an ordered sequence of transition identifiers.

    The draft is **data only** - a request identifier plus the proposed
    ordered transition identifiers (minimum 1, maximum 1000, repetitions
    allowed). It cannot accept tenant identity, campaign/world/strategy/
    state-model/transition hashes, plan identifiers, plan content hashes,
    state values, callbacks, expressions, code, scripts, imports, provider
    configuration, or metadata. The service validates the draft again even
    when it arrives as a Pydantic instance created through ``model_copy``
    or another validator-bypassing path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    ordered_transition_identifiers: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_TRAJECTORY_PLAN_TRANSITIONS
    )


class StrategyTrajectoryPlan(VersionedContract):
    """Immutable, authoritatively bound trajectory plan for one campaign.

    Binds one prepared campaign, one verified compiled world (by
    identifier and full content hash), one exact stored strategy candidate
    (by identifier and full content hash), one state model embedded in
    that world (by manifest, deterministic model identifier, logical
    state-model id, and content hash), and an explicitly ordered tuple of
    transition references embedded in the same world (minimum 1, maximum
    1000; repetitions allowed and significant). The plan carries no
    transition guard/target values, no state snapshots, no outcomes, no
    evidence, no recommendation, and no hidden reasoning.

    ``content_hash`` is the SHA-256 digest of the complete canonical plan
    content excluding ``content_hash`` itself; tuple ordering and
    transition repetitions are significant, so changing any transition
    position or reference changes the hash. ``planned_at`` is
    deterministic (the recorded campaign ``created_at``) - never
    wall-clock time and never LEGION.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    scenario_id: str
    world_version_id: str
    world_content_hash: str = Field(pattern=_SHA256_PATTERN)
    strategy_candidate_id: str
    strategy_content_hash: str = Field(pattern=_SHA256_PATTERN)
    manifest_id: str
    state_model_identifier: str
    state_model_id: str
    state_model_content_hash: str = Field(pattern=_SHA256_PATTERN)
    transition_references: tuple[StrategyTrajectoryTransitionReference, ...] = Field(
        min_length=1, max_length=MAX_TRAJECTORY_PLAN_TRANSITIONS
    )
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    planned_at: AwareDatetime
