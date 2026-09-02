"""Phase 28 adaptive-run trajectory execution contract tests (H28-S06 contract slice).

Covers the immutable ``AdaptiveRunTrajectoryExecution`` public contract:
JSON round trips, frozen/strict rejection, the exact ``4.0.0`` runtime
literal, decision cardinality with exactly contiguous ``0..N-1`` snapshot
and decision steps, policy/world/seed provenance agreement, strictly
ordered unique switch events that exist exactly for ``action_changed``
decisions and agree with their decision's current/selected actions,
contiguous observation ``sequence_position`` values with unique
declaration/source-step coordinates and bounded non-terminal availability,
canonical per-decision trajectory-result tuples with unique state-model and
plan identifiers, optional external bundle identifier/hash pairing,
malformed hashes and naive timestamps, bool/coercion/non-finite
adversaries, absence of any forbidden execution surface, and the exact
registry append with schema synchronization. Every adversarial case audits
its own base fixture as valid first, so each rejection is proven to fire
for the intended invariant. No skips, xfails, mocks, monkeypatching,
``type: ignore``, ``noqa``, or manual schema edits exist in this module.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from pydantic import ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
KALHAS_ROOT = REPO_ROOT / "kalhas"

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64_OTHER = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: The nested evidence roles this aggregate reuses; none may be registered
#: or schematized independently.
_NESTED_ROLES = (
    "RuntimeObservationEvent",
    "AdaptivePolicyStateSnapshot",
    "AdaptivePolicyDecisionEvent",
    "AdaptivePolicySwitchEvent",
    "RealizedStateTrajectoryResult",
)


def _result_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": H64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-a",
        "state_model_id": "sm-a",
        "state_model_content_hash": H64,
        "initial_state": {"level": 0},
        "initial_state_hash": H64,
        "attempts": [],
        "final_state": {"level": 1},
        "final_state_hash": H64,
        "trace_hash": H64,
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _observation_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": "observation-event-1",
        "runtime_version": "4.0.0",
        "observation_declaration_id": "declaration-1",
        "observation_declaration_content_hash": H64,
        "observation_id": "observation-1",
        "source_kind": "state_field",
        "world_version_id": "world-1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "sequence_position": 0,
        "source_step_index": 0,
        "delay_steps": 0,
        "available_decision_step": 0,
        "terminal": False,
        "status": "observed",
        "source_state_hash": H64,
        "external_input_bundle_id": None,
        "external_input_bundle_content_hash": None,
        "source_value": 7,
        "applied_noise_value": None,
        "exposed_observation_value": 7,
        "observed_value_kind": "integer",
        "observed_value_unit": None,
        "noise_domain_literal": "kalhas-observation-noise-v1",
        "noise_sampler_version": "sha256-counter-v1",
        "noise_draw_index": None,
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _snapshot_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-1",
        "policy_content_hash": H64,
        "decision_step": 0,
        "current_action_id": "act-a",
        "action_installed_at_decision_step": 0,
        "completed_applications": 0,
        "last_switch_decision_step": None,
        "remaining_global_switch_budget": 10,
        "per_rule_remaining_budgets": [["rule-1", 3]],
    }
    payload.update(overrides)
    return payload


def _decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-1",
        "policy_content_hash": H64,
        "decision_step": 0,
        "current_action_id": "act-a",
        "rule_evaluation_evidence": [["rule-1", "enter", True, None]],
        "selected_rule_id": "rule-1",
        "selected_action_id": "act-b",
        "decision_kind": "rule",
        "action_changed": True,
        "fallback_blocked_reason": None,
    }
    payload.update(overrides)
    return payload


def _switch_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-1",
        "policy_content_hash": H64,
        "decision_step": 0,
        "old_action_id": "act-a",
        "new_action_id": "act-b",
        "trigger_kind": "rule",
        "triggering_rule_id": "rule-1",
        "global_switch_budget_before": 10,
        "global_switch_budget_after": 9,
        "rule_switch_budget_before": 3,
        "rule_switch_budget_after": 2,
    }
    payload.update(overrides)
    return payload


def _minimal_aggregate_payload(**overrides: Any) -> dict[str, Any]:
    """One decision (step 0) that switches act-a -> act-b via rule-1."""
    payload: dict[str, Any] = {
        "identifier": "adaptive-run-trajectory-execution-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "run-plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "world_realization_id": "world-realization-1",
        "world_realization_content_hash": H64,
        "runtime_version": "4.0.0",
        "adaptive_policy_identifier": "adaptive-policy-1",
        "policy_id": "policy-1",
        "adaptive_policy_content_hash": H64,
        "external_observation_input_bundle_id": None,
        "external_observation_input_bundle_content_hash": None,
        "input_hash": H64,
        "trajectory_plan_set_hash": H64,
        "observation_events": [_observation_payload()],
        "policy_state_snapshots": [_snapshot_payload()],
        "decision_events": [_decision_payload()],
        "switch_events": [_switch_payload()],
        "trajectory_results_by_decision": [[_result_payload()]],
        "content_hash": H64,
        "executed_at": NOW,
    }
    payload.update(overrides)
    return payload


def _multi_step_aggregate_payload(**overrides: Any) -> dict[str, Any]:
    """Three decisions: retain act-a, rule-switch to act-b, blocked fallback."""
    payload: dict[str, Any] = {
        "identifier": "adaptive-run-trajectory-execution-2",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-2",
        "campaign_id": "campaign-1",
        "run_plan_id": "run-plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "world_realization_id": "world-realization-1",
        "world_realization_content_hash": H64,
        "runtime_version": "4.0.0",
        "adaptive_policy_identifier": "adaptive-policy-1",
        "policy_id": "policy-1",
        "adaptive_policy_content_hash": H64,
        "external_observation_input_bundle_id": None,
        "external_observation_input_bundle_content_hash": None,
        "input_hash": H64,
        "trajectory_plan_set_hash": H64,
        "observation_events": [
            _observation_payload(identifier="observation-event-1", sequence_position=0),
            _observation_payload(
                identifier="observation-event-2",
                sequence_position=1,
                source_step_index=2,
                delay_steps=0,
                available_decision_step=None,
                terminal=True,
            ),
        ],
        "policy_state_snapshots": [
            _snapshot_payload(
                decision_step=0,
                current_action_id="act-a",
                action_installed_at_decision_step=0,
                completed_applications=0,
                last_switch_decision_step=None,
                remaining_global_switch_budget=2,
                per_rule_remaining_budgets=[["rule-1", 2]],
            ),
            _snapshot_payload(
                decision_step=1,
                current_action_id="act-a",
                action_installed_at_decision_step=0,
                completed_applications=1,
                last_switch_decision_step=None,
                remaining_global_switch_budget=2,
                per_rule_remaining_budgets=[["rule-1", 2]],
            ),
            _snapshot_payload(
                decision_step=2,
                current_action_id="act-b",
                action_installed_at_decision_step=1,
                completed_applications=1,
                last_switch_decision_step=1,
                remaining_global_switch_budget=1,
                per_rule_remaining_budgets=[["rule-1", 1]],
            ),
        ],
        "decision_events": [
            _decision_payload(
                decision_step=0,
                current_action_id="act-a",
                rule_evaluation_evidence=[["rule-1", "retain", True, None]],
                selected_rule_id="rule-1",
                selected_action_id="act-a",
                decision_kind="rule",
                action_changed=False,
            ),
            _decision_payload(
                decision_step=1,
                current_action_id="act-a",
                rule_evaluation_evidence=[["rule-1", "enter", True, None]],
                selected_rule_id="rule-1",
                selected_action_id="act-b",
                decision_kind="rule",
                action_changed=True,
            ),
            _decision_payload(
                decision_step=2,
                current_action_id="act-b",
                rule_evaluation_evidence=[["rule-1", "enter", False, None]],
                selected_rule_id=None,
                selected_action_id="act-b",
                decision_kind="blocked_fallback",
                action_changed=False,
                fallback_blocked_reason="global_switch_budget",
            ),
        ],
        "switch_events": [
            _switch_payload(
                decision_step=1,
                old_action_id="act-a",
                new_action_id="act-b",
                global_switch_budget_before=2,
                global_switch_budget_after=1,
                rule_switch_budget_before=2,
                rule_switch_budget_after=1,
            ),
        ],
        "trajectory_results_by_decision": [
            [
                _result_payload(trajectory_plan_id="trajectory-plan-1"),
                _result_payload(
                    trajectory_plan_id="trajectory-plan-2",
                    state_model_identifier="state-model-b",
                    state_model_id="sm-b",
                    trajectory_plan_content_hash=H64_OTHER,
                    state_model_content_hash=H64_OTHER,
                    content_hash=H64_OTHER,
                ),
            ],
            [_result_payload()],
            [_result_payload()],
        ],
        "content_hash": H64,
        "executed_at": NOW,
    }
    payload.update(overrides)
    return payload


def _expect_invalid(
    payload: dict[str, Any],
    *,
    base_payload: dict[str, Any] | None = None,
) -> None:
    """Audit the base fixture as valid, then require the tampered one to fail."""
    base = _minimal_aggregate_payload() if base_payload is None else base_payload
    AdaptiveRunTrajectoryExecution.model_validate(base)
    with pytest.raises(ValidationError):
        AdaptiveRunTrajectoryExecution.model_validate(payload)


def _audit_minimal_valid() -> None:
    AdaptiveRunTrajectoryExecution.model_validate(_minimal_aggregate_payload())


# ---------------------------------------------------------------------------
# 1. Valid aggregates and strict model surface.
# ---------------------------------------------------------------------------


class TestValidAggregates:
    def test_minimal_aggregate_with_switch_is_accepted(self) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(_minimal_aggregate_payload())
        assert aggregate.runtime_version == "4.0.0"
        assert aggregate.policy_id == "policy-1"
        assert len(aggregate.decision_events) == 1
        assert aggregate.model_dump(mode="json")["executed_at"] is not None

    def test_multi_step_aggregate_with_retain_switch_and_blocked_fallback(
        self,
    ) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(_multi_step_aggregate_payload())
        assert [event.decision_step for event in aggregate.decision_events] == [0, 1, 2]
        assert [switch.decision_step for switch in aggregate.switch_events] == [1]
        assert [event.action_changed for event in aggregate.decision_events] == [
            False,
            True,
            False,
        ]

    def test_empty_observation_and_switch_tuples_are_expressible(self) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(
            _minimal_aggregate_payload(
                observation_events=[],
                switch_events=[],
                decision_events=[
                    _decision_payload(
                        current_action_id="act-a",
                        selected_action_id="act-a",
                        action_changed=False,
                    )
                ],
                policy_state_snapshots=[_snapshot_payload()],
            )
        )
        assert aggregate.observation_events == ()
        assert aggregate.switch_events == ()

    def test_optional_external_bundle_pair_is_accepted(self) -> None:
        payload = _minimal_aggregate_payload(
            external_observation_input_bundle_id="external-input-bundle-1",
            external_observation_input_bundle_content_hash=H64_OTHER,
        )
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(payload)
        assert aggregate.external_observation_input_bundle_id == ("external-input-bundle-1")
        assert aggregate.external_observation_input_bundle_content_hash == H64_OTHER

    def test_json_round_trip_preserves_every_field(self) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(_multi_step_aggregate_payload())
        restored = AdaptiveRunTrajectoryExecution.model_validate(
            json.loads(json.dumps(aggregate.model_dump(mode="json")))
        )
        assert restored == aggregate

    def test_aggregate_is_frozen(self) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(_minimal_aggregate_payload())
        with pytest.raises(ValidationError):
            aggregate.policy_id = "policy-other"

    def test_unknown_fields_are_rejected(self) -> None:
        payload = _minimal_aggregate_payload(surprise=True)
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryExecution.model_validate(payload)

    def test_runtime_literal_is_exactly_4_0_0_and_required(self) -> None:
        schema = AdaptiveRunTrajectoryExecution.model_json_schema()
        const = schema["properties"]["runtime_version"]["const"]
        assert const == "4.0.0"
        assert schema["properties"]["runtime_version"]["type"] == "string"
        assert "runtime_version" in schema["required"]
        for bad_runtime in ("4.0", "4", "3.0.0", 4, 4.0, True):
            payload = _minimal_aggregate_payload(runtime_version=bad_runtime)
            with pytest.raises(ValidationError):
                AdaptiveRunTrajectoryExecution.model_validate(payload)
        missing = _minimal_aggregate_payload()
        del missing["runtime_version"]
        with pytest.raises(ValidationError):
            AdaptiveRunTrajectoryExecution.model_validate(missing)


# ---------------------------------------------------------------------------
# 2. Decision cardinality and contiguous ordering.
# ---------------------------------------------------------------------------


class TestDecisionCardinalityAndOrdering:
    def test_at_least_one_decision_is_required(self) -> None:
        payload = _minimal_aggregate_payload(
            decision_events=[],
            policy_state_snapshots=[],
            trajectory_results_by_decision=[],
            switch_events=[],
        )
        _expect_invalid(payload)

    def test_missing_snapshot_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(policy_state_snapshots=[])
        _expect_invalid(payload)

    def test_extra_snapshot_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(
            policy_state_snapshots=[_snapshot_payload(), _snapshot_payload()]
        )
        _expect_invalid(payload)

    def test_missing_outer_result_tuple_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(trajectory_results_by_decision=[])
        _expect_invalid(payload)

    def test_extra_outer_result_tuple_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(
            trajectory_results_by_decision=[[_result_payload()], [_result_payload()]]
        )
        _expect_invalid(payload)

    def test_non_contiguous_decision_steps_are_rejected(self) -> None:
        payload = _multi_step_aggregate_payload(
            decision_events=[
                _decision_payload(
                    decision_step=0,
                    current_action_id="act-a",
                    selected_action_id="act-a",
                    action_changed=False,
                ),
                _decision_payload(decision_step=2, selected_action_id="act-b"),
                _decision_payload(
                    decision_step=1,
                    current_action_id="act-b",
                    rule_evaluation_evidence=[["rule-1", "enter", False, None]],
                    selected_rule_id=None,
                    selected_action_id="act-b",
                    decision_kind="blocked_fallback",
                    action_changed=False,
                    fallback_blocked_reason="global_switch_budget",
                ),
            ]
        )
        _expect_invalid(payload, base_payload=_multi_step_aggregate_payload())

    def test_snapshot_step_must_match_its_position(self) -> None:
        payload = _multi_step_aggregate_payload(
            policy_state_snapshots=[
                _snapshot_payload(
                    decision_step=0,
                    current_action_id="act-a",
                    action_installed_at_decision_step=0,
                    completed_applications=0,
                    remaining_global_switch_budget=2,
                    per_rule_remaining_budgets=[["rule-1", 2]],
                ),
                _snapshot_payload(
                    decision_step=0,
                    current_action_id="act-a",
                    action_installed_at_decision_step=0,
                    completed_applications=0,
                    remaining_global_switch_budget=2,
                    per_rule_remaining_budgets=[["rule-1", 2]],
                ),
                _snapshot_payload(
                    decision_step=2,
                    current_action_id="act-b",
                    action_installed_at_decision_step=1,
                    completed_applications=1,
                    last_switch_decision_step=1,
                    remaining_global_switch_budget=1,
                    per_rule_remaining_budgets=[["rule-1", 1]],
                ),
            ]
        )
        _expect_invalid(payload, base_payload=_multi_step_aggregate_payload())


# ---------------------------------------------------------------------------
# 3. Policy/world/seed provenance agreement.
# ---------------------------------------------------------------------------


class TestProvenanceAgreement:
    def test_snapshot_policy_identity_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            policy_state_snapshots=[_snapshot_payload(policy_id="policy-other")]
        )
        _expect_invalid(payload)

    def test_snapshot_policy_hash_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            adaptive_policy_content_hash=H64_OTHER,
            policy_state_snapshots=[_snapshot_payload(policy_content_hash=H64)],
        )
        _expect_invalid(payload)

    def test_decision_policy_identity_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            decision_events=[_decision_payload(policy_id="policy-other")]
        )
        _expect_invalid(payload)

    def test_decision_policy_hash_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            decision_events=[_decision_payload(policy_content_hash=H64_OTHER)]
        )
        _expect_invalid(payload)

    def test_observation_world_identity_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[_observation_payload(world_version_id="world-other")]
        )
        _expect_invalid(payload)

    def test_observation_world_hash_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[_observation_payload(world_content_hash=H64_OTHER)]
        )
        _expect_invalid(payload)

    def test_observation_seed_identity_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[_observation_payload(scenario_seed_id="seed-other")]
        )
        _expect_invalid(payload)

    def test_observation_seed_hash_must_match_aggregate(self) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[_observation_payload(seed_content_hash=H64_OTHER)]
        )
        _expect_invalid(payload)


# ---------------------------------------------------------------------------
# 4. Switch/decision agreement and uniqueness.
# ---------------------------------------------------------------------------


class TestSwitchAgreement:
    def test_duplicate_switch_decision_steps_are_rejected(self) -> None:
        payload = _minimal_aggregate_payload(switch_events=[_switch_payload(), _switch_payload()])
        _expect_invalid(payload)

    def test_stored_switch_steps_must_be_ascending(self) -> None:
        base = _multi_step_aggregate_payload()
        payload = _multi_step_aggregate_payload(
            decision_events=[
                _decision_payload(
                    decision_step=0,
                    current_action_id="act-a",
                    selected_action_id="act-a",
                    action_changed=False,
                ),
                _decision_payload(decision_step=1, selected_action_id="act-b"),
                _decision_payload(
                    decision_step=2,
                    current_action_id="act-b",
                    rule_evaluation_evidence=[["rule-1", "enter", False, None]],
                    selected_rule_id=None,
                    selected_action_id="act-b",
                    decision_kind="blocked_fallback",
                    action_changed=False,
                    fallback_blocked_reason="global_switch_budget",
                ),
            ],
            switch_events=[
                _switch_payload(
                    decision_step=2,
                    old_action_id="act-b",
                    new_action_id="act-a",
                    global_switch_budget_before=1,
                    global_switch_budget_after=0,
                    rule_switch_budget_before=1,
                    rule_switch_budget_after=0,
                ),
                _switch_payload(
                    decision_step=1,
                    global_switch_budget_before=2,
                    global_switch_budget_after=1,
                    rule_switch_budget_before=2,
                    rule_switch_budget_after=1,
                ),
            ],
        )
        _expect_invalid(payload, base_payload=base)

    def test_switch_step_outside_decision_range_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(switch_events=[_switch_payload(decision_step=1)])
        _expect_invalid(payload)

    def test_switch_for_same_action_decision_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(
            decision_events=[
                _decision_payload(
                    current_action_id="act-a",
                    selected_action_id="act-a",
                    action_changed=False,
                )
            ],
            policy_state_snapshots=[_snapshot_payload()],
            switch_events=[_switch_payload(decision_step=0)],
        )
        _expect_invalid(payload)

    def test_missing_switch_for_changed_decision_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(switch_events=[])
        _expect_invalid(payload)

    def test_switch_old_action_must_equal_decision_current_action(self) -> None:
        payload = _minimal_aggregate_payload(
            switch_events=[_switch_payload(old_action_id="act-other")]
        )
        _expect_invalid(payload)

    def test_switch_new_action_must_equal_decision_selected_action(self) -> None:
        payload = _minimal_aggregate_payload(
            switch_events=[_switch_payload(new_action_id="act-other")]
        )
        _expect_invalid(payload)


# ---------------------------------------------------------------------------
# 5. Observation ordering, bounds, duplicates, and terminal semantics.
# ---------------------------------------------------------------------------


class TestObservationEvidence:
    def test_sequence_positions_must_be_contiguous_from_zero(self) -> None:
        payload = _multi_step_aggregate_payload(
            observation_events=[
                _observation_payload(identifier="observation-event-1", sequence_position=0),
                _observation_payload(
                    identifier="observation-event-2",
                    sequence_position=2,
                    source_step_index=2,
                    delay_steps=0,
                    available_decision_step=2,
                ),
            ]
        )
        _expect_invalid(payload, base_payload=_multi_step_aggregate_payload())

    def test_stored_sequence_positions_must_be_ascending(self) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[
                _observation_payload(identifier="observation-event-1", sequence_position=1),
                _observation_payload(
                    identifier="observation-event-2",
                    sequence_position=0,
                    observation_declaration_id="declaration-2",
                ),
            ]
        )
        _expect_invalid(payload)

    def test_duplicate_declaration_source_step_coordinates_are_rejected(
        self,
    ) -> None:
        payload = _minimal_aggregate_payload(
            observation_events=[
                _observation_payload(identifier="observation-event-1"),
                _observation_payload(identifier="observation-event-2", sequence_position=1),
            ]
        )
        _expect_invalid(payload)

    def test_non_terminal_available_step_outside_decision_range_is_rejected(
        self,
    ) -> None:
        base = _multi_step_aggregate_payload()
        payload = _multi_step_aggregate_payload(
            observation_events=[
                _observation_payload(
                    identifier="observation-event-1",
                    sequence_position=0,
                    source_step_index=1,
                    delay_steps=2,
                    available_decision_step=3,
                ),
            ]
        )
        _expect_invalid(payload, base_payload=base)

    def test_terminal_observation_may_carry_no_available_step(self) -> None:
        aggregate = AdaptiveRunTrajectoryExecution.model_validate(
            _minimal_aggregate_payload(
                observation_events=[
                    _observation_payload(
                        identifier="observation-event-1",
                        terminal=True,
                        available_decision_step=None,
                    )
                ]
            )
        )
        assert aggregate.observation_events[0].terminal is True


# ---------------------------------------------------------------------------
# 6. Canonical per-decision trajectory results.
# ---------------------------------------------------------------------------


class TestTrajectoryResults:
    def test_inner_results_must_be_canonically_ordered(self) -> None:
        payload = _minimal_aggregate_payload(
            trajectory_results_by_decision=[
                [
                    _result_payload(
                        trajectory_plan_id="trajectory-plan-2",
                        state_model_identifier="state-model-b",
                        state_model_id="sm-b",
                        trajectory_plan_content_hash=H64_OTHER,
                        state_model_content_hash=H64_OTHER,
                        content_hash=H64_OTHER,
                    ),
                    _result_payload(),
                ]
            ]
        )
        _expect_invalid(payload)

    def test_inner_results_reject_duplicate_state_model_identifiers(self) -> None:
        payload = _minimal_aggregate_payload(
            trajectory_results_by_decision=[[_result_payload(), _result_payload()]]
        )
        _expect_invalid(payload)

    def test_inner_results_reject_duplicate_plan_identifiers(self) -> None:
        payload = _minimal_aggregate_payload(
            trajectory_results_by_decision=[
                [
                    _result_payload(),
                    _result_payload(trajectory_plan_id="trajectory-plan-1"),
                ]
            ]
        )
        _expect_invalid(payload)


# ---------------------------------------------------------------------------
# 7. Optional external bundle pairing, hashes, and timestamps.
# ---------------------------------------------------------------------------


class TestBundleHashesAndTimestamps:
    def test_bundle_id_without_hash_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(
            external_observation_input_bundle_id="external-input-bundle-1"
        )
        _expect_invalid(payload)

    def test_bundle_hash_without_id_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(
            external_observation_input_bundle_content_hash=H64_OTHER
        )
        _expect_invalid(payload)

    def test_malformed_hashes_are_rejected_everywhere(self) -> None:
        bad_hashes = (
            "ABC" * 22,
            "abc" * 21,
            "z" * 64,
            "abc" * 21 + "A",
        )
        for bad_hash in bad_hashes:
            for field in ("content_hash", "world_content_hash", "input_hash"):
                payload = _minimal_aggregate_payload(**{field: bad_hash[:64]})
                _expect_invalid(payload)

    def test_naive_executed_at_is_rejected(self) -> None:
        payload = _minimal_aggregate_payload(executed_at=datetime(2026, 1, 1, 12, 0, 0))
        _expect_invalid(payload)


# ---------------------------------------------------------------------------
# 8. Bool/coercion/non-finite adversaries.
# ---------------------------------------------------------------------------


class TestAdversarialInputs:
    def test_bool_float_string_for_sequence_position_is_rejected(self) -> None:
        for bad_position in (True, 1.0, "1"):
            payload = _minimal_aggregate_payload(
                observation_events=[_observation_payload(sequence_position=bad_position)]
            )
            _expect_invalid(payload)

    def test_bool_float_string_for_decision_step_is_rejected(self) -> None:
        for bad_step in (True, 1.0, "1"):
            payload = _minimal_aggregate_payload(
                decision_events=[_decision_payload(decision_step=bad_step)]
            )
            _expect_invalid(payload)

    def test_bool_for_string_identifier_is_rejected(self) -> None:
        for bad_id in (True, 123):
            payload = _minimal_aggregate_payload(run_id=bad_id)
            _expect_invalid(payload)

    def test_non_finite_result_state_values_are_rejected(self) -> None:
        for bad_state in (
            {"level": float("nan")},
            {"nested": {"ratio": float("inf")}},
        ):
            payload = _minimal_aggregate_payload(
                trajectory_results_by_decision=[[_result_payload(initial_state=bad_state)]]
            )
            _expect_invalid(payload)
            payload = _minimal_aggregate_payload(
                trajectory_results_by_decision=[[_result_payload(final_state=bad_state)]]
            )
            _expect_invalid(payload)

    def test_non_finite_observation_values_are_rejected(self) -> None:
        for bad_value in (float("nan"), float("inf")):
            payload = _minimal_aggregate_payload(
                observation_events=[_observation_payload(source_value=bad_value)]
            )
            _expect_invalid(payload)


# ---------------------------------------------------------------------------
# 9. Forbidden-surface and registration boundaries.
# ---------------------------------------------------------------------------


class TestForbiddenSurfaceAndRegistration:
    def test_contract_module_has_no_executable_or_network_surface(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_trajectory_execution.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        for token in (
            "eval(",
            "exec(",
            "import_module",
            "__import__",
            "lambda",
            "callback",
            "provider",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "random",
            "uuid",
            "datetime.now",
        ):
            assert token not in code, f"forbidden surface token {token!r} in module"

    def test_no_forbidden_execution_surfaces_expressible(self) -> None:
        fields = tuple(AdaptiveRunTrajectoryExecution.model_fields)
        for token in (
            "callback",
            "expression",
            "provider",
            "recommendation",
            "replay",
            "outcome",
            "metadata",
        ):
            assert not any(token in name for name in fields), (
                f"forbidden surface {token!r} expressible in {fields!r}"
            )

    def test_nested_roles_are_not_registered_or_exported(self) -> None:
        from kalhas.contracts.v1 import __all__ as public_exports

        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_ROLES:
            assert nested not in names, f"{nested} independently registered"
            assert nested not in public_exports, f"{nested} independently exported"

    def test_nested_roles_have_no_standalone_schema_artifact(self) -> None:
        names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for nested in _NESTED_ROLES:
            assert f"{nested}.schema.json" not in names, f"standalone schema for {nested}"

    def test_aggregate_defines_no_replay_manifest_surface(self) -> None:
        assert "replay" not in tuple(AdaptiveRunTrajectoryExecution.model_fields)


# ---------------------------------------------------------------------------
# 10. Registry append and schema synchronization.
# ---------------------------------------------------------------------------


class TestRegistryAndSchema:
    def test_registry_appends_at_index_53_after_immutable_53_prefix(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 54
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[47:53] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
            "AdaptivePolicy",
        )
        assert names[53] == "AdaptiveRunTrajectoryExecution"

    def test_schema_artifact_is_synchronized_with_the_model(self) -> None:
        rendered = json.loads(
            (SCHEMA_DIR / "AdaptiveRunTrajectoryExecution.schema.json").read_text(encoding="utf-8")
        )
        assert rendered == AdaptiveRunTrajectoryExecution.model_json_schema()
        assert rendered["title"] == "AdaptiveRunTrajectoryExecution"
        assert rendered["additionalProperties"] is False

    def test_schema_requires_decision_events(self) -> None:
        schema = AdaptiveRunTrajectoryExecution.model_json_schema()
        assert schema["properties"]["decision_events"]["minItems"] == 1
        assert "decision_events" in schema["required"]

    def test_executed_at_schema_is_datetime_with_format(self) -> None:
        schema = AdaptiveRunTrajectoryExecution.model_json_schema()
        executed_at = schema["properties"]["executed_at"]
        assert executed_at["type"] == "string"
        assert executed_at["format"] == "date-time"
