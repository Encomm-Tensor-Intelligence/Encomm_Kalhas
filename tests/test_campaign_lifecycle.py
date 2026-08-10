"""Tests for the pure campaign lifecycle state machine."""

from __future__ import annotations

import pytest
from kalhas.application.campaign_lifecycle import (
    CampaignTransitionError,
    allowed_transitions,
    can_transition,
    is_terminal,
    transition,
)
from kalhas.contracts.v1.campaign import CampaignState

ALL_STATES = list(CampaignState)

EXPECTED_ALLOWED: dict[CampaignState, set[CampaignState]] = {
    CampaignState.DRAFT: {CampaignState.VALIDATED, CampaignState.CANCELLED},
    CampaignState.VALIDATED: {
        CampaignState.COMPILED,
        CampaignState.DRAFT,
        CampaignState.CANCELLED,
    },
    CampaignState.COMPILED: {
        CampaignState.RUNNING,
        CampaignState.VALIDATED,
        CampaignState.CANCELLED,
    },
    CampaignState.RUNNING: {
        CampaignState.COMPLETE,
        CampaignState.FAILED,
        CampaignState.CANCELLED,
    },
    CampaignState.COMPLETE: set(),
    CampaignState.FAILED: set(),
    CampaignState.CANCELLED: set(),
}


@pytest.mark.parametrize("current", ALL_STATES)
def test_allowed_transitions_match_table(current: CampaignState) -> None:
    assert set(allowed_transitions(current)) == EXPECTED_ALLOWED[current]


@pytest.mark.parametrize("current", ALL_STATES)
@pytest.mark.parametrize("target", ALL_STATES)
def test_transition_applies_only_allowed(current: CampaignState, target: CampaignState) -> None:
    if target in EXPECTED_ALLOWED[current]:
        assert can_transition(current, target)
        assert transition(current, target) is target
    else:
        assert not can_transition(current, target)
        with pytest.raises(CampaignTransitionError) as excinfo:
            transition(current, target)
        assert excinfo.value.current is current
        assert excinfo.value.target is target


@pytest.mark.parametrize("current", ALL_STATES)
def test_terminal_states_have_no_outgoing(current: CampaignState) -> None:
    assert is_terminal(current) == (allowed_transitions(current) == frozenset())


def test_full_forward_chain_is_legal() -> None:
    state = CampaignState.DRAFT
    for target in (
        CampaignState.VALIDATED,
        CampaignState.COMPILED,
        CampaignState.RUNNING,
        CampaignState.COMPLETE,
    ):
        state = transition(state, target)
    assert state is CampaignState.COMPLETE
    assert is_terminal(state)


def test_illegal_transition_from_terminal_state() -> None:
    with pytest.raises(CampaignTransitionError):
        transition(CampaignState.COMPLETE, CampaignState.RUNNING)
    with pytest.raises(CampaignTransitionError):
        transition(CampaignState.CANCELLED, CampaignState.DRAFT)
    with pytest.raises(CampaignTransitionError):
        transition(CampaignState.FAILED, CampaignState.RUNNING)
