"""Phase 15 contract tests: immutable strategy-bound trajectory plans.

Covers the strict shape of the four new trajectory contract types:
extra-field rejection, frozen configuration, SHA-256 patterns, non-empty
and maximum-1000 draft/plan sequence bounds, repeated transition
references, the non-empty available-transition catalog of the request,
public-contract enumeration, and the absence of any executable/code/
provider surface in the contract module.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.strategy import (
    PolicyDeclaration,
    StrategyCandidate,
)
from kalhas.contracts.v1.trajectory import (
    MAX_TRAJECTORY_PLAN_TRANSITIONS,
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
    StrategyTrajectoryTransitionReference,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
REQUEST_ID = "trajectory-request-0123456789abcdef"
PLAN_ID = "trajectory-plan-0123456789abcdef"


def _reference(sequence_position: int = 0) -> StrategyTrajectoryTransitionReference:
    return StrategyTrajectoryTransitionReference(
        sequence_position=sequence_position,
        transition_identifier="transition-1",
        transition_id="t-1",
        transition_content_hash=HASH_64,
    )


def _state_model() -> DomainStateModel:
    return DomainStateModel(
        identifier="state-model-1",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_fields=(
            DomainStateFieldDefinition(
                identifier="status",
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="idle",
            ),
        ),
        content_hash=HASH_64,
        declared_at=NOW,
    )


def _transition() -> DomainStateTransition:
    return DomainStateTransition(
        identifier="transition-1",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_model_content_hash=HASH_64,
        transition_id="t-1",
        description="Declared state change",
        guard_values={"status": "idle"},
        target_values={"status": "active"},
        content_hash=HASH_64,
        declared_at=NOW,
    )


def _candidate() -> StrategyCandidate:
    return StrategyCandidate(
        identifier="sc-1",
        tenant_id="tenant-1",
        strategy_version="1.0.0",
        policy=PolicyDeclaration(summary="Declared policy", rules=[]),
        assumptions=[],
    )


def _request(
    *,
    available_transitions: tuple[DomainStateTransition, ...] = (_transition(),),
) -> StrategyTrajectoryPlanRequest:
    return StrategyTrajectoryPlanRequest(
        identifier=REQUEST_ID,
        tenant_id="tenant-1",
        campaign_id="campaign-1",
        scenario_id="scenario-1",
        world_version_id="world-0123456789abcdef",
        world_content_hash=HASH_64,
        strategy_candidate=_candidate(),
        strategy_content_hash=HASH_64,
        state_model=_state_model(),
        available_transitions=available_transitions,
        requested_at=NOW,
    )


def _draft(request_id: str = REQUEST_ID) -> StrategyTrajectoryPlanDraft:
    return StrategyTrajectoryPlanDraft(
        request_id=request_id,
        ordered_transition_identifiers=("transition-1",),
    )


def _plan(
    transition_references: tuple[StrategyTrajectoryTransitionReference, ...] = (_reference(),),
) -> StrategyTrajectoryPlan:
    return StrategyTrajectoryPlan(
        identifier=PLAN_ID,
        tenant_id="tenant-1",
        campaign_id="campaign-1",
        scenario_id="scenario-1",
        world_version_id="world-0123456789abcdef",
        world_content_hash=HASH_64,
        strategy_candidate_id="sc-1",
        strategy_content_hash=HASH_64,
        manifest_id="manifest-1",
        state_model_identifier="state-model-1",
        state_model_id="sm-1",
        state_model_content_hash=HASH_64,
        transition_references=transition_references,
        content_hash=HASH_64,
        planned_at=NOW,
    )


class TestStrategyTrajectoryTransitionReference:
    def test_frozen_and_strict(self) -> None:
        reference = _reference()
        with pytest.raises(ValidationError):
            reference.transition_id = "other"  # frozen by contract
        with pytest.raises(ValidationError):
            StrategyTrajectoryTransitionReference.model_validate(
                {
                    "sequence_position": 0,
                    "transition_identifier": "transition-1",
                    "transition_id": "t-1",
                    "transition_content_hash": HASH_64,
                    "rogue": 1,
                }
            )

    def test_sequence_position_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            StrategyTrajectoryTransitionReference(
                sequence_position=-1,
                transition_identifier="transition-1",
                transition_id="t-1",
                transition_content_hash=HASH_64,
            )

    def test_content_hash_must_be_lowercase_sha256(self) -> None:
        for bad in ("f" * 63, "F" * 64, "zz" * 32):
            with pytest.raises(ValidationError):
                StrategyTrajectoryTransitionReference(
                    sequence_position=0,
                    transition_identifier="transition-1",
                    transition_id="t-1",
                    transition_content_hash=bad,
                )

    def test_reference_carries_no_guard_target_or_state_data(self) -> None:
        reference = _reference()
        assert reference.model_fields_set == {
            "sequence_position",
            "transition_identifier",
            "transition_id",
            "transition_content_hash",
        }


class TestStrategyTrajectoryPlanDraft:
    def test_frozen_and_strict(self) -> None:
        draft = _draft()
        with pytest.raises(ValidationError):
            draft.request_id = "other"  # frozen by contract
        with pytest.raises(ValidationError):
            StrategyTrajectoryPlanDraft.model_validate(
                {
                    "request_id": REQUEST_ID,
                    "ordered_transition_identifiers": ["transition-1"],
                    "rogue": 1,
                }
            )

    def test_sequence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StrategyTrajectoryPlanDraft(
                request_id=REQUEST_ID,
                ordered_transition_identifiers=(),
            )
        with pytest.raises(ValidationError):
            StrategyTrajectoryPlanDraft(
                request_id=REQUEST_ID,
                ordered_transition_identifiers=("x",) * (MAX_TRAJECTORY_PLAN_TRANSITIONS + 1),
            )

    def test_repetitions_allowed(self) -> None:
        draft = StrategyTrajectoryPlanDraft(
            request_id=REQUEST_ID,
            ordered_transition_identifiers=("transition-1", "transition-1", "transition-2"),
        )
        assert draft.ordered_transition_identifiers == (
            "transition-1",
            "transition-1",
            "transition-2",
        )

    def test_draft_cannot_carry_hashes_state_or_metadata(self) -> None:
        # The draft's field set is exactly the untrusted proposal surface.
        assert set(StrategyTrajectoryPlanDraft.model_fields) == {
            "request_id",
            "ordered_transition_identifiers",
        }


class TestStrategyTrajectoryPlanRequest:
    def test_frozen_and_strict(self) -> None:
        request = _request()
        with pytest.raises(ValidationError):
            request.campaign_id = "other"  # frozen by contract
        with pytest.raises(ValidationError):
            StrategyTrajectoryPlanRequest.model_validate(
                {
                    **request.model_dump(mode="json"),
                    "rogue": 1,
                }
            )

    def test_available_transitions_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            _request(available_transitions=())

    def test_embeds_exact_snapshots(self) -> None:
        request = _request()
        assert request.strategy_candidate.identifier == "sc-1"
        assert request.state_model.state_model_id == "sm-1"
        assert [t.transition_id for t in request.available_transitions] == ["t-1"]


class TestStrategyTrajectoryPlan:
    def test_frozen_and_strict(self) -> None:
        plan = _plan()
        with pytest.raises(ValidationError):
            plan.planned_at = NOW  # frozen by contract
        with pytest.raises(ValidationError):
            StrategyTrajectoryPlan.model_validate(
                {
                    **plan.model_dump(mode="json"),
                    "rogue": 1,
                }
            )

    def test_sequence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _plan(())
        many = tuple(
            _reference(position) for position in range(MAX_TRAJECTORY_PLAN_TRANSITIONS + 1)
        )
        with pytest.raises(ValidationError):
            _plan(many)

    def test_repeated_references_are_allowed(self) -> None:
        plan = _plan((_reference(0), _reference(1), _reference(2)))
        assert len(plan.transition_references) == 3
        assert [r.transition_identifier for r in plan.transition_references] == ["transition-1"] * 3

    def test_plan_contains_no_state_values_or_outcomes(self) -> None:
        assert set(StrategyTrajectoryPlan.model_fields) == {
            "identifier",
            "tenant_id",
            "schema_version",
            "campaign_id",
            "scenario_id",
            "world_version_id",
            "world_content_hash",
            "strategy_candidate_id",
            "strategy_content_hash",
            "manifest_id",
            "state_model_identifier",
            "state_model_id",
            "state_model_content_hash",
            "transition_references",
            "content_hash",
            "planned_at",
        }


class TestPublicSurface:
    def test_new_contracts_are_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "StrategyTrajectoryPlanRequest" in names
        assert "StrategyTrajectoryPlan" in names

    def test_all_trajectory_types_are_exported(self) -> None:
        from kalhas.contracts.v1 import (
            StrategyTrajectoryPlan as ExportedPlan,
        )
        from kalhas.contracts.v1 import (
            StrategyTrajectoryPlanDraft as ExportedDraft,
        )
        from kalhas.contracts.v1 import (
            StrategyTrajectoryPlanRequest as ExportedRequest,
        )
        from kalhas.contracts.v1 import (
            StrategyTrajectoryTransitionReference as ExportedReference,
        )

        assert ExportedPlan is StrategyTrajectoryPlan
        assert ExportedDraft is StrategyTrajectoryPlanDraft
        assert ExportedRequest is StrategyTrajectoryPlanRequest
        assert ExportedReference is StrategyTrajectoryTransitionReference


def test_trajectory_contract_module_has_no_executable_surface() -> None:
    """Source-scan: no callbacks, expressions, code, or provider tokens.

    Docstrings are stripped first so prose mentioning the forbidden words
    cannot false-positive the scan.
    """
    path = Path(__file__).resolve().parents[1] / "kalhas" / "contracts" / "v1" / "trajectory.py"
    source = path.read_text(encoding="utf-8")
    code = "".join(source.split('"""')[::2])
    forbidden = re.compile(
        r"\b(eval|exec|import_module|__import__|compile|lambda|callback|provider|"
        r"requests|urllib|socket|subprocess|executable)\b"
    )
    assert not forbidden.search(code)
