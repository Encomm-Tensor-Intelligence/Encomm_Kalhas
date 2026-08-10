"""Pure, in-memory campaign lifecycle state machine.

Phase 1 defines the lifecycle only: explicit allowed transitions, a typed
domain exception for invalid transitions, and no persistence, no FastAPI
dependencies, and no side effects. The machine is deterministic: the same
(current, target) pair always yields the same decision.

Canonical transition table:

    DRAFT      -> VALIDATED, CANCELLED
    VALIDATED  -> COMPILED, DRAFT, CANCELLED
    COMPILED   -> RUNNING, VALIDATED, CANCELLED
    RUNNING    -> COMPLETE, FAILED, CANCELLED
    COMPLETE   -> (terminal)
    FAILED     -> (terminal)
    CANCELLED  -> (terminal)
"""

from __future__ import annotations

from kalhas.contracts.v1.campaign import CampaignState

_ALLOWED_TRANSITIONS: dict[CampaignState, frozenset[CampaignState]] = {
    CampaignState.DRAFT: frozenset({CampaignState.VALIDATED, CampaignState.CANCELLED}),
    CampaignState.VALIDATED: frozenset(
        {CampaignState.COMPILED, CampaignState.DRAFT, CampaignState.CANCELLED}
    ),
    CampaignState.COMPILED: frozenset(
        {CampaignState.RUNNING, CampaignState.VALIDATED, CampaignState.CANCELLED}
    ),
    CampaignState.RUNNING: frozenset(
        {CampaignState.COMPLETE, CampaignState.FAILED, CampaignState.CANCELLED}
    ),
    CampaignState.COMPLETE: frozenset(),
    CampaignState.FAILED: frozenset(),
    CampaignState.CANCELLED: frozenset(),
}

_TERMINAL_STATES: frozenset[CampaignState] = frozenset(
    {CampaignState.COMPLETE, CampaignState.FAILED, CampaignState.CANCELLED}
)


class CampaignTransitionError(Exception):
    """Typed domain exception raised for an invalid campaign state transition."""

    def __init__(self, current: CampaignState, target: CampaignState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid campaign transition: {current.value} -> {target.value}")


def allowed_transitions(state: CampaignState) -> frozenset[CampaignState]:
    """Return the immutable set of states reachable from ``state``."""
    return _ALLOWED_TRANSITIONS[state]


def can_transition(current: CampaignState, target: CampaignState) -> bool:
    """Return True iff the transition is allowed."""
    return target in _ALLOWED_TRANSITIONS[current]


def transition(current: CampaignState, target: CampaignState) -> CampaignState:
    """Apply one transition and return the new state.

    Raises :class:`CampaignTransitionError` when the transition is not
    allowed.
    """
    if not can_transition(current, target):
        raise CampaignTransitionError(current, target)
    return target


def is_terminal(state: CampaignState) -> bool:
    """Return True iff ``state`` has no outgoing transitions."""
    return state in _TERMINAL_STATES
