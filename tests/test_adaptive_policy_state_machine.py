"""Phase 28 runtime-4 adaptive-policy state machine tests (H28-S04-C01).

Builds real strict ``AdaptivePolicy``, ``ConditionNode``, and
``RuntimeObservationEvent`` instances and exercises the pure application
state machine ``initialize_adaptive_policy_state`` /
``advance_adaptive_policy_state`` end-to-end, plus the three frozen nested
contract roles in ``kalhas/contracts/v1/adaptive_policy_state.py``. Event
content hashes are computed truthfully with the production canonical hashing
convention; no validator is monkeypatched and no state-machine output is
manufactured by replacing the production functions.

The adversarial proof covers, against the implementation itself:
initialization is not a switch and keeps budgets full; first matching eligible
rule wins; lower rules are never evaluated after a winner; a matching
ineligible rule is recorded and evaluation continues to a lower eligible rule;
exact enter-versus-retain condition selection; same-action retention consumes
no budget; minimum-dwell boundaries immediately before and exactly at
``d + N``; cooldown boundaries immediately before and exactly at
``s + N + 1``; zero/one global-budget and per-rule-budget boundaries; a rule
switch decrements the global and its rule budget only; a fallback switch
decrements the global budget only; fallback cannot bypass dwell, cooldown, or
global budget; deterministic blocked-reason precedence; initialization,
same-action, and blocked decisions produce no switch event; exact switch-event
decrement invariants; next-snapshot installed/completed/last-switch semantics;
multiple consecutive decisions and switching back; deterministic repeated
calls; input immutability after success and failure; malformed, subclassed,
foreign-policy, unknown-action, reordered-budget, inflated-budget, and
inconsistent-snapshot rejection; condition-evaluator errors propagate with
zero partial result; no duplicated condition algorithm or forbidden subsystem
surface; the exact 53-contract public registry prefix preserved with the
fixed ``AdaptivePolicy`` index-52 append and synchronized schema artifacts
(the exact current cardinality is owned by the Phase 28 registry-compatibility
suite); and unchanged protected git blobs.
"""

from __future__ import annotations

import inspect
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from kalhas.application.adaptive_condition_errors import (
    AdaptiveConditionEvaluationError,
    AdaptiveConditionMissingObservationError,
)
from kalhas.application.adaptive_policy_state_errors import AdaptivePolicyStateMachineError
from kalhas.application.adaptive_policy_state_machine import (
    AdaptivePolicyStepResult,
    advance_adaptive_policy_state,
    initialize_adaptive_policy_state,
)
from kalhas.application.domain_errors import KalhasDomainError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    ConditionAllNode,
    ConditionAnyNode,
    ConditionComparisonLeaf,
    ConditionNode,
)
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent
from pydantic import ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64_OTHER = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

WORLD_ID = "world-v1"
WORLD_HASH = H64
SEED_ID = "seed-1"
SEED_HASH = H64

#: The six protected baseline identifiers from the H28-S04 session brief.
#: ``tests/test_adaptive_condition_evaluator.py`` is deliberately unpinned:
#: its blob legitimately advances with the H28-S06A-C02 additive-registry
#: closure edit, so pinning it would recreate a false blocker (the same
#: remove-don't-update doctrine applied to the evaluator suite's own pins).
PROTECTED_FINGERPRINTS = {
    "docs/decisions/ADR-004-deterministic-adaptive-runtime-4.md": (
        "32518c01baa8443da73650b106cbd674b86b7ae8"
    ),
    "kalhas/contracts/v1/adaptive_policy.py": ("dbb5fb05290f6b0e13c21b9c6bc8d567bb17e1ed"),
    "kalhas/contracts/v1/runtime_observation.py": ("1635868c936c055ff000587473944e699703df6d"),
    "kalhas/application/adaptive_condition_errors.py": ("e12fc4d373044e17f2807ba590581f16704c57fe"),
    "kalhas/application/adaptive_condition_evaluator.py": (
        "dc863268e92760fec0bd602dd45ad812be7259d9"
    ),
    "tests/test_api_phase23.py": ("adbabab4c091e3f7923c5315f8e9d17de73d210a"),
}


# ---------------------------------------------------------------------------
# Condition, rule, policy, and event builders.
# ---------------------------------------------------------------------------


def _leaf(
    obs: int,
    *,
    kind: Literal["integer", "number"] = "integer",
    operator: Literal["lt", "lte", "eq", "gte", "gt"] = "gte",
    threshold: int | float = 5,
    missing: Literal["false", "error"] = "false",
    unit: str | None = None,
    condition_id: str | None = None,
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id or f"c-{obs}",
        observation_id=f"obs-{obs}",
        observed_value_kind=kind,
        unit=unit,
        operator=operator,
        threshold=threshold,
        missing_behavior=missing,
    )


def _all(condition_id: str, children: tuple[ConditionNode, ...]) -> ConditionAllNode:
    return ConditionAllNode(kind="all", condition_id=condition_id, children=children)


def _any(condition_id: str, children: tuple[ConditionNode, ...]) -> ConditionAnyNode:
    return ConditionAnyNode(kind="any", condition_id=condition_id, children=children)


def _collect_leaves(node: ConditionNode, into: list[ConditionComparisonLeaf]) -> None:
    if isinstance(node, ConditionComparisonLeaf):
        into.append(node)
        return
    for child in node.children:
        _collect_leaves(child, into)


def _decl_id(observation_id: str) -> str:
    return "runtime-observation-" + observation_id.split("-")[-1]


def _rule(
    rule_id: str,
    priority: int,
    target_action_id: str,
    enter: ConditionNode,
    retain: ConditionNode | None = None,
    per_rule_switch_budget: int = 3,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "priority": priority,
        "target_action_id": target_action_id,
        "enter_condition": enter,
        "retain_condition": retain if retain is not None else enter,
        "per_rule_switch_budget": per_rule_switch_budget,
    }


def _action_payload(action_id: str) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "strategy_candidate_id": f"sc-{action_id}",
        "strategy_content_hash": H64,
        "trajectory_plan_bindings": [
            {
                "trajectory_plan_id": "trajectory-plan-1",
                "trajectory_plan_content_hash": H64,
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": H64,
            }
        ],
    }


def _policy(
    *,
    rules: list[dict[str, Any]],
    actions: tuple[str, ...] = ("act-a", "act-b", "act-c"),
    initial_action_id: str = "act-a",
    fallback_action_id: str | None = None,
    minimum_dwell_steps: int = 0,
    cooldown_steps: int = 0,
    global_switch_budget: int = 3,
    policy_id: str = "policy-x",
) -> AdaptivePolicy:
    """Build an immutable ``AdaptivePolicy`` over the supplied rules.

    The observation-binding catalog covers exactly the observations referenced
    by the rules' enter/retain leaves so the contract's complete-coverage and
    leaf/binding agreement validators hold. Every rule is stored in the given
    (ascending-priority) order.
    """
    fallback_action_id = fallback_action_id or actions[-1]
    leaves: list[ConditionComparisonLeaf] = []
    for rule in rules:
        _collect_leaves(rule["enter_condition"], leaves)
        _collect_leaves(rule["retain_condition"], leaves)
    seen: dict[str, ConditionComparisonLeaf] = {}
    for leaf in leaves:
        seen[leaf.observation_id] = leaf
    bindings = [
        {
            "observation_id": obs_id,
            "runtime_observation_declaration_id": _decl_id(obs_id),
            "runtime_observation_declaration_content_hash": H64,
            "observed_value_kind": leaf.observed_value_kind,
            "unit": leaf.unit,
            "missing_behavior": leaf.missing_behavior,
        }
        for obs_id, leaf in sorted(seen.items())
    ]
    payload: dict[str, Any] = {
        "identifier": f"adaptive-policy-{policy_id}",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": WORLD_ID,
        "world_content_hash": WORLD_HASH,
        "runtime_version": "4.0.0",
        "policy_id": policy_id,
        "policy_version": "1.0.0",
        "observation_bindings": bindings,
        "actions": [_action_payload(action_id) for action_id in actions],
        "initial_action_id": initial_action_id,
        "fallback_action_id": fallback_action_id,
        "rules": rules,
        "minimum_dwell_steps": minimum_dwell_steps,
        "cooldown_steps": cooldown_steps,
        "global_switch_budget": global_switch_budget,
        "content_hash": H64,
        "bound_at": NOW,
        "metadata": {},
    }
    return AdaptivePolicy.model_validate(payload)


def _event(
    obs: int,
    *,
    value: int | float = 10,
    status: str = "observed",
    observed_kind: str | None = "integer",
    unit: str | None = None,
    sequence: int | None = None,
    available: int | None = 1,
    terminal: bool = False,
    scenario_seed_id: str = SEED_ID,
    seed_hash: str = SEED_HASH,
    world_version_id: str = WORLD_ID,
    world_hash: str = WORLD_HASH,
    declaration_id: str | None = None,
    declaration_hash: str | None = H64,
    identifier: str | None = None,
    runtime_version: str = "4.0.0",
    **extra: Any,
) -> RuntimeObservationEvent:
    is_observed = status == "observed"
    avail = None if terminal else (available if available is not None else 1)
    payload: dict[str, Any] = {
        "identifier": identifier or f"event-{obs}",
        "runtime_version": runtime_version,
        "observation_declaration_id": declaration_id or f"runtime-observation-{obs}",
        "observation_declaration_content_hash": declaration_hash or H64,
        "observation_id": f"obs-{obs}",
        "source_kind": "state_field",
        "world_version_id": world_version_id,
        "world_content_hash": world_hash,
        "scenario_seed_id": scenario_seed_id,
        "seed_content_hash": seed_hash,
        "sequence_position": sequence if sequence is not None else obs,
        "source_step_index": avail if avail is not None else 0,
        "delay_steps": 0,
        "available_decision_step": avail,
        "terminal": terminal,
        "status": status,
        "source_state_hash": H64,
        "external_input_bundle_id": None,
        "external_input_bundle_content_hash": None,
        "source_value": value if is_observed else None,
        "applied_noise_value": None,
        "exposed_observation_value": value if is_observed else None,
        "observed_value_kind": observed_kind if is_observed else None,
        "observed_value_unit": unit if is_observed else None,
        "noise_domain_literal": "kalhas-observation-noise-v1",
        "noise_sampler_version": "sha256-counter-v1",
        "noise_draw_index": None,
        "content_hash": H64,
    }
    payload.update(extra)
    event = RuntimeObservationEvent.model_validate(payload)
    digest = sha256_hex(canonical_json(event.model_dump(mode="json", exclude={"content_hash"})))
    return event.model_copy(update={"content_hash": digest})


def _evidence(
    *values: tuple[int, int | float], missing: set[int] | None = None, available: int = 0
) -> tuple[RuntimeObservationEvent, ...]:
    """One canonical event per (obs, value) pair, ascending by declaration id."""
    missing = missing or set()
    return tuple(
        _event(
            obs,
            value=value,
            status="missing" if obs in missing else "observed",
            sequence=obs,
            available=available,
        )
        for obs, value in sorted(values)
    )


def _advance(
    policy: AdaptivePolicy,
    state: AdaptivePolicyStateSnapshot,
    *values: tuple[int, int | float],
    missing: set[int] | None = None,
) -> AdaptivePolicyStepResult:
    return advance_adaptive_policy_state(
        policy=policy,
        state=state,
        events=_evidence(*values, missing=missing, available=state.decision_step),
        scenario_seed_id=SEED_ID,
        seed_content_hash=SEED_HASH,
    )


def _chain(
    policy: AdaptivePolicy, *steps: tuple[tuple[int, int | float], ...]
) -> list[AdaptivePolicyStepResult]:
    state = initialize_adaptive_policy_state(policy)
    results: list[AdaptivePolicyStepResult] = []
    for values in steps:
        result = _advance(policy, state, *values)
        results.append(result)
        state = result.next_state
    return results


# ---------------------------------------------------------------------------
# 1. Closed aliases and nested-contract registration boundaries.
# ---------------------------------------------------------------------------


class TestRegistriesAndAliases:
    def test_machine_error_derives_from_kalhas_domain_error(self) -> None:
        assert issubclass(AdaptivePolicyStateMachineError, KalhasDomainError)
        error = AdaptivePolicyStateMachineError("some_reason")
        assert error.reason == "some_reason"
        # The public message stays generic and never leaks internal values.
        assert "some_reason" not in str(error)

    def test_nested_roles_are_not_versioned_contracts_and_stay_unregistered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in (
            "AdaptivePolicyStateSnapshot",
            "AdaptivePolicyDecisionEvent",
            "AdaptivePolicySwitchEvent",
        ):
            assert nested not in names, f"{nested} independently registered"

    def test_public_contract_registry_preserves_the_exact_53_contract_prefix(
        self,
    ) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 53
        assert len(_HISTORICAL_47_NAMES) == 47
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[47:53] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
            "AdaptivePolicy",
        )
        assert names[52] == "AdaptivePolicy"

    def test_nested_roles_have_no_standalone_schema_artifact(self) -> None:
        schema_names = {path.name for path in (REPO_ROOT / "schemas" / "v1").glob("*.schema.json")}
        assert len(schema_names) == len(PUBLIC_CONTRACTS)
        for nested in (
            "AdaptivePolicyStateSnapshot",
            "AdaptivePolicyDecisionEvent",
            "AdaptivePolicySwitchEvent",
        ):
            assert f"{nested}.schema.json" not in schema_names

    def test_aliases_are_the_frozen_literals(self) -> None:
        from typing import get_args

        from kalhas.contracts.v1.adaptive_policy_state import (
            ConditionRole,
            DecisionKind,
            EligibilityBlockedReason,
            SwitchTriggerKind,
        )

        assert get_args(ConditionRole) == ("enter", "retain")
        assert get_args(EligibilityBlockedReason) == (
            "minimum_dwell",
            "cooldown",
            "global_switch_budget",
            "per_rule_switch_budget",
        )
        assert get_args(DecisionKind) == ("rule", "fallback", "blocked_fallback")
        assert get_args(SwitchTriggerKind) == ("rule", "fallback")


# ---------------------------------------------------------------------------
# 2. AdaptivePolicyStateSnapshot contract invariants.
# ---------------------------------------------------------------------------


def _snapshot_payload(**overrides: Any) -> dict[str, Any]:
    # Default: action installed at step 3 by its last switch at step 3, with
    # decision step 5 (5 - 3 == 2 completed applications). This satisfies the
    # strict invariant that every non-initial installation is an actual switch.
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-x",
        "policy_content_hash": H64,
        "decision_step": 5,
        "current_action_id": "act-a",
        "action_installed_at_decision_step": 3,
        "completed_applications": 2,
        "last_switch_decision_step": 3,
        "remaining_global_switch_budget": 3,
        "per_rule_remaining_budgets": (("r1", 2), ("r2", 1)),
    }
    payload.update(overrides)
    return payload


class TestSnapshotContract:
    def test_valid_snapshot_roundtrip_is_frozen_and_strict(self) -> None:
        snapshot = AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload())
        assert snapshot.decision_step == 5
        assert snapshot.completed_applications == 2
        assert snapshot.per_rule_remaining_budgets == (("r1", 2), ("r2", 1))
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate({**_snapshot_payload(), "extra_field": 1})

    def test_installed_step_may_not_exceed_decision_step(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(action_installed_at_decision_step=6)
            )

    def test_completed_applications_must_equal_difference(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload(completed_applications=3))

    def test_last_switch_must_be_strictly_before_decision_step(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(last_switch_decision_step=5)
            )
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(last_switch_decision_step=6)
            )
        # A last switch strictly before the decision step, equal to the
        # installation step, is accepted.
        assert (
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(last_switch_decision_step=3)
            ).last_switch_decision_step
            == 3
        )

    def test_per_rule_budget_rule_ids_must_be_unique(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(per_rule_remaining_budgets=(("r1", 2), ("r1", 1)))
            )

    @pytest.mark.parametrize(
        "bad_budget",
        [True, 1.5, "4", -1, None, [1, 2], (("r1", 2), ("r2", "3"))],
    )
    def test_malformed_budget_values_fail(self, bad_budget: Any) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(
                    per_rule_remaining_budgets=[bad_budget]
                    if isinstance(bad_budget, tuple)
                    else bad_budget
                )
            )

    def test_float_string_bool_negative_decision_step_fail(self) -> None:
        for bad in (1.0, "1", True, -1):
            with pytest.raises(ValidationError):
                AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload(decision_step=bad))

    def test_runtime_literal_is_exactly_4_0_0(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload(runtime_version="4.1.0"))

    def test_unknown_field_and_missing_field_fail(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload(current_action_id=None))
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                {key: value for key, value in _snapshot_payload().items() if key != "policy_id"}
            )


# ---------------------------------------------------------------------------
# 2b. DEFECT-1 strict invariant: installation is the only, and always a
#     switch-or-initialization, installation.
# ---------------------------------------------------------------------------


class TestInstallationSwitchInvariant:
    def test_initial_snapshot_no_switch_installed_at_zero_passes(self) -> None:
        snap = AdaptivePolicyStateSnapshot.model_validate(
            _snapshot_payload(
                decision_step=3,
                action_installed_at_decision_step=0,
                completed_applications=3,
                last_switch_decision_step=None,
            )
        )
        assert snap.last_switch_decision_step is None
        assert snap.action_installed_at_decision_step == 0

    def test_switched_snapshot_installed_equals_last_switch_passes(self) -> None:
        snap = AdaptivePolicyStateSnapshot.model_validate(
            _snapshot_payload(
                decision_step=6,
                action_installed_at_decision_step=4,
                completed_applications=2,
                last_switch_decision_step=4,
            )
        )
        assert snap.last_switch_decision_step == snap.action_installed_at_decision_step == 4

    def test_installed_after_zero_without_last_switch_fails(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(
                    decision_step=2,
                    action_installed_at_decision_step=1,
                    completed_applications=1,
                    last_switch_decision_step=None,
                )
            )

    def test_last_switch_different_from_installed_step_fails(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(
                _snapshot_payload(
                    action_installed_at_decision_step=2,
                    completed_applications=3,
                    last_switch_decision_step=3,
                )
            )

    def test_machine_init_installed_zero_no_last_switch(self) -> None:
        policy = _single_rule_policy(target="act-b")
        snap = initialize_adaptive_policy_state(policy)
        assert snap.action_installed_at_decision_step == 0
        assert snap.last_switch_decision_step is None

    def test_impossible_history_fails_closed_via_both_bypassers(self) -> None:
        # The exact impossible pre-decision state: decision_step=2,
        # action_installed_at_decision_step=1, completed_applications=1,
        # last_switch_decision_step=None (initialization is at step 0; only a
        # switch installs later).
        policy = _single_rule_policy(target="act-b")
        base = initialize_adaptive_policy_state(policy)
        impossible = {
            "decision_step": 2,
            "action_installed_at_decision_step": 1,
            "completed_applications": 1,
            "last_switch_decision_step": None,
        }
        copy_bypassed = base.model_copy(update=impossible)
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, copy_bypassed, (1, 25))

        payload = base.model_dump(mode="python")
        payload.update(impossible)
        constructed = AdaptivePolicyStateSnapshot.model_construct(**payload)
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, constructed, (1, 25))


# ---------------------------------------------------------------------------
# 3. AdaptivePolicyDecisionEvent contract invariants.
# ---------------------------------------------------------------------------


def _decision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-x",
        "policy_content_hash": H64,
        "decision_step": 3,
        "current_action_id": "act-a",
        "rule_evaluation_evidence": (
            ("r1", "enter", False, None),
            ("r2", "enter", True, None),
        ),
        "selected_rule_id": "r2",
        "selected_action_id": "act-c",
        "decision_kind": "rule",
        "action_changed": True,
        "fallback_blocked_reason": None,
    }
    payload.update(overrides)
    return payload


class TestDecisionEventContract:
    def test_valid_rule_decision(self) -> None:
        event = AdaptivePolicyDecisionEvent.model_validate(_decision_payload())
        assert event.selected_rule_id == "r2"
        assert event.action_changed is True

    def test_duplicate_rule_ids_in_evidence_fail(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    rule_evaluation_evidence=(
                        ("r1", "enter", False, None),
                        ("r1", "retain", True, None),
                    )
                )
            )

    def test_nonmatching_rule_may_not_carry_a_blocked_reason(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(rule_evaluation_evidence=(("r1", "enter", False, "cooldown"),))
            )

    def test_blocked_reason_requires_a_matched_rule(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    rule_evaluation_evidence=(
                        ("r1", "enter", False, None),
                        ("r2", "enter", False, "cooldown"),
                    )
                )
            )

    def test_selected_rule_must_be_last_matched_and_unblocked(self) -> None:
        # Selected rule must be the last evaluated record.
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    rule_evaluation_evidence=(
                        ("r1", "enter", True, None),
                        ("r2", "enter", True, None),
                    ),
                    selected_rule_id="r1",
                )
            )
        # A blocked selected rule is rejected.
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    rule_evaluation_evidence=(
                        ("r1", "enter", False, None),
                        ("r2", "enter", True, "cooldown"),
                    ),
                    selected_rule_id="r2",
                )
            )

    def test_rule_kind_requires_a_selected_rule(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(_decision_payload(selected_rule_id=None))

    def test_fallback_kinds_forbid_a_selected_rule(self) -> None:
        for kind in ("fallback", "blocked_fallback"):
            with pytest.raises(ValidationError):
                AdaptivePolicyDecisionEvent.model_validate(
                    _decision_payload(
                        decision_kind=kind,
                        selected_rule_id="r2",
                        selected_action_id="act-a",
                        action_changed=False,
                    )
                )

    def test_blocked_fallback_requires_reason_and_retains_current_action(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    decision_kind="blocked_fallback",
                    fallback_blocked_reason=None,
                    selected_action_id="act-a",
                    action_changed=False,
                )
            )
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    decision_kind="blocked_fallback",
                    fallback_blocked_reason="cooldown",
                    selected_action_id="act-b",
                    action_changed=True,
                )
            )

    def test_non_fallback_kinds_forbid_a_fallback_blocked_reason(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(fallback_blocked_reason="cooldown")
            )

    def test_action_changed_must_match_action_identity(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(_decision_payload(action_changed=False))
        with pytest.raises(ValidationError):
            AdaptivePolicyDecisionEvent.model_validate(
                _decision_payload(
                    selected_action_id="act-a",
                    action_changed=True,
                )
            )


# ---------------------------------------------------------------------------
# 4. AdaptivePolicySwitchEvent contract invariants.
# ---------------------------------------------------------------------------


def _switch_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_version": "4.0.0",
        "policy_id": "policy-x",
        "policy_content_hash": H64,
        "decision_step": 2,
        "old_action_id": "act-a",
        "new_action_id": "act-b",
        "trigger_kind": "rule",
        "triggering_rule_id": "r1",
        "global_switch_budget_before": 3,
        "global_switch_budget_after": 2,
        "rule_switch_budget_before": 1,
        "rule_switch_budget_after": 0,
    }
    payload.update(overrides)
    return payload


class TestSwitchEventContract:
    def test_valid_rule_switch(self) -> None:
        event = AdaptivePolicySwitchEvent.model_validate(_switch_payload())
        assert event.trigger_kind == "rule"
        assert event.global_switch_budget_after == 2

    def test_old_and_new_action_ids_must_differ(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(_switch_payload(new_action_id="act-a"))

    def test_global_budget_must_decrement_by_exactly_one(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(_switch_payload(global_switch_budget_after=1))
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(_switch_payload(global_switch_budget_after=3))

    def test_rule_switch_requires_rule_id_and_exact_rule_decrement(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(_switch_payload(triggering_rule_id=None))
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(
                _switch_payload(rule_switch_budget_before=None, rule_switch_budget_after=None)
            )
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate(
                _switch_payload(rule_switch_budget_after=0, rule_switch_budget_before=2)
            )

    def test_fallback_switch_forbids_rule_id_and_rule_budget_fields(self) -> None:
        base = dict(_switch_payload())
        base.update(
            {
                "trigger_kind": "fallback",
                "triggering_rule_id": None,
                "rule_switch_budget_before": None,
                "rule_switch_budget_after": None,
                "global_switch_budget_before": 2,
                "global_switch_budget_after": 1,
            }
        )
        assert AdaptivePolicySwitchEvent.model_validate(base).trigger_kind == "fallback"
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate({**base, "triggering_rule_id": "r1"})
        with pytest.raises(ValidationError):
            AdaptivePolicySwitchEvent.model_validate({**base, "rule_switch_budget_before": 1})


# ---------------------------------------------------------------------------
# 5. Machine init and first-step semantics.
# ---------------------------------------------------------------------------


def _single_rule_policy(
    *,
    target: str = "act-b",
    enter: ConditionNode | None = None,
    retain: ConditionNode | None = None,
    **kwargs: Any,
) -> AdaptivePolicy:
    enter = enter if enter is not None else _leaf(1, threshold=10)
    return _policy(
        rules=[_rule("r1", 0, target, enter, retain=retain)],
        actions=("act-a", "act-b", "act-c"),
        fallback_action_id="act-c",
        **kwargs,
    )


class TestInitialization:
    def test_init_is_not_a_switch_and_budgets_stay_full(self) -> None:
        policy = _single_rule_policy(global_switch_budget=4)
        snapshot = initialize_adaptive_policy_state(policy)
        assert snapshot.decision_step == 0
        assert snapshot.current_action_id == "act-a"
        assert snapshot.action_installed_at_decision_step == 0
        assert snapshot.completed_applications == 0
        assert snapshot.last_switch_decision_step is None
        assert snapshot.remaining_global_switch_budget == 4
        assert snapshot.per_rule_remaining_budgets == (("r1", 3),)
        assert snapshot.policy_id == policy.policy_id
        assert snapshot.policy_content_hash == policy.content_hash
        assert snapshot.runtime_version == "4.0.0"

    def test_initialize_rejects_subclassed_policy(self) -> None:
        policy = _single_rule_policy()

        class SubPolicy(AdaptivePolicy):
            pass

        sub = SubPolicy.model_validate(policy.model_dump(mode="json"))
        with pytest.raises(AdaptivePolicyStateMachineError):
            initialize_adaptive_policy_state(sub)
        # An exact-type policy is accepted.
        assert initialize_adaptive_policy_state(policy).decision_step == 0


class TestFirstEligiblePriorityWins:
    def test_rules_evaluate_in_priority_order_and_higher_priority_eligible_wins(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10)),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20)),
            ],
            fallback_action_id="act-c",
            global_switch_budget=3,
        )
        # value 25 matches both; the first eligible rule (r1) wins.
        results = _chain(policy, ((1, 25),))
        result = results[0]
        assert result.decision_event.decision_kind == "rule"
        assert result.decision_event.selected_rule_id == "r1"
        assert result.decision_event.selected_action_id == "act-b"
        assert result.decision_event.action_changed is True
        assert [record[0] for record in result.decision_event.rule_evaluation_evidence] == ["r1"]
        assert result.switch_event is not None
        assert result.switch_event.triggering_rule_id == "r1"

    def test_lower_rules_are_not_evaluated_after_a_winner(self) -> None:
        # r2's guard is satisfied by the supplied observations: if it were
        # evaluated it would match and win. The winner is r1 (priority 0), so
        # r2 is never reached and never appears in the evaluation evidence.
        matching_policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10, condition_id="m1")),
                _rule(
                    "r2",
                    1,
                    "act-c",
                    _all(
                        "guard-root",
                        (
                            _leaf(1, threshold=10, condition_id="g1"),
                            _leaf(2, threshold=0, condition_id="g2"),
                        ),
                    ),
                ),
            ],
            fallback_action_id="act-c",
        )
        events = _evidence((1, 25), (2, 5))
        result = advance_adaptive_policy_state(
            policy=matching_policy,
            state=initialize_adaptive_policy_state(matching_policy),
            events=events,
            scenario_seed_id=SEED_ID,
            seed_content_hash=SEED_HASH,
        )
        assert result.decision_event.selected_rule_id == "r1"
        assert [record[0] for record in result.decision_event.rule_evaluation_evidence] == ["r1"]
        assert result.decision_event.selected_action_id == "act-b"

    def test_matching_ineligible_rule_is_recorded_and_lower_eligible_rule_wins(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=0),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20)),
            ],
            fallback_action_id="act-c",
            global_switch_budget=3,
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        evidence = result.decision_event.rule_evaluation_evidence
        assert evidence == (
            ("r1", "enter", True, "per_rule_switch_budget"),
            ("r2", "enter", True, None),
        )
        assert result.decision_event.selected_rule_id == "r2"
        assert result.decision_event.selected_action_id == "act-c"
        assert result.switch_event is not None
        assert result.switch_event.triggering_rule_id == "r2"


class TestEnterRetainSelection:
    def test_enter_condition_controls_a_different_action_rule(self) -> None:
        enter = _leaf(1, threshold=10)
        retain = _leaf(1, threshold=500, operator="gt")
        policy = _single_rule_policy(target="act-b", enter=enter, retain=retain)
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        assert result.decision_event.rule_evaluation_evidence[0][:2] == ("r1", "enter")
        assert result.decision_event.selected_action_id == "act-b"

    def test_retain_condition_controls_a_same_action_rule(self) -> None:
        enter = _leaf(1, threshold=500, operator="gt")
        retain = _leaf(1, threshold=10)
        # current action is r1's target: the retain tree decides retention.
        policy = _policy(
            rules=[_rule("r1", 0, "act-a", enter, retain=retain, per_rule_switch_budget=2)],
            initial_action_id="act-a",
            fallback_action_id="act-c",
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        record = result.decision_event.rule_evaluation_evidence[0]
        assert record[:2] == ("r1", "retain")
        assert record[2] is True and record[3] is None
        assert result.decision_event.selected_rule_id == "r1"
        assert result.decision_event.selected_action_id == "act-a"
        assert result.decision_event.action_changed is False
        assert result.switch_event is None


class TestSameActionRetention:
    def test_retention_consumes_no_budget_and_preserves_state_budgets(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-a", _leaf(1, threshold=10))],
            initial_action_id="act-a",
            fallback_action_id="act-c",
            global_switch_budget=2,
        )
        state = initialize_adaptive_policy_state(policy)
        result = _advance(policy, state, (1, 25))
        assert result.decision_event.action_changed is False
        assert result.switch_event is None
        assert result.next_state.remaining_global_switch_budget == 2
        assert result.next_state.per_rule_remaining_budgets == (("r1", 3),)
        assert result.next_state.completed_applications == 1
        assert result.next_state.action_installed_at_decision_step == 0
        assert result.next_state.last_switch_decision_step is None


# ---------------------------------------------------------------------------
# 6. Dwell, cooldown, and budget boundaries.
# ---------------------------------------------------------------------------


class TestMinimumDwellBoundaries:
    def test_dwell_boundaries_immediately_before_and_at_d_plus_n(self) -> None:
        # Action installed at step 0, dwell N = 3: blocked at 0..2, first
        # switch allowed at exactly step 3.
        policy = _single_rule_policy(minimum_dwell_steps=3, global_switch_budget=5)
        results = _chain(policy, ((1, 25),), ((1, 25),), ((1, 25),), ((1, 25),))
        for index in (0, 1, 2):
            assert results[index].decision_event.decision_kind == "blocked_fallback"
            assert results[index].decision_event.action_changed is False
            assert results[index].switch_event is None
            assert results[index].next_state.current_action_id == "act-a"
            assert results[index].next_state.action_installed_at_decision_step == 0
        # Step 3 == installed(0) + dwell(3): eligible.
        final = results[3]
        assert final.decision_event.decision_kind == "rule"
        assert final.decision_event.selected_rule_id == "r1"
        assert final.decision_event.action_changed is True
        assert final.switch_event is not None
        assert final.next_state.current_action_id == "act-b"
        assert final.next_state.action_installed_at_decision_step == 3
        assert final.next_state.completed_applications == 1


class TestCooldownBoundaries:
    def test_cooldown_boundaries_immediately_before_and_at_s_plus_n_plus_1(self) -> None:
        # First switch at step 0 (last_switch s=0). Cooldown N=1 blocks the
        # next switch until exactly s + N + 1 = step 2.
        policy = _policy(
            rules=[
                _rule(
                    "r1", 0, "act-b", _leaf(1, threshold=10), _leaf(1, threshold=500, operator="gt")
                ),
                _rule("r2", 1, "act-c", _leaf(1, threshold=10)),
            ],
            fallback_action_id="act-a",
            cooldown_steps=1,
            global_switch_budget=5,
        )
        results = _chain(policy, ((1, 25),), ((1, 25),), ((1, 25),))
        first = results[0]
        assert first.decision_event.decision_kind == "rule"
        assert first.decision_event.selected_rule_id == "r1"
        assert first.switch_event is not None
        assert first.switch_event.trigger_kind == "rule"
        assert first.next_state.last_switch_decision_step == 0

        second = results[1]
        assert second.decision_event.decision_kind == "blocked_fallback"
        assert second.decision_event.fallback_blocked_reason == "cooldown"
        assert second.decision_event.action_changed is False
        assert second.switch_event is None
        assert second.next_state.current_action_id == "act-b"

        third = results[2]
        assert third.decision_event.decision_kind == "rule"
        assert third.decision_event.selected_rule_id == "r2"
        assert third.decision_event.action_changed is True
        assert third.switch_event is not None
        assert third.next_state.current_action_id == "act-c"
        assert third.next_state.last_switch_decision_step == 2


class TestGlobalBudgetBoundaries:
    def test_zero_and_one_remaining_global_budget_boundaries(self) -> None:
        # One global budget entry permits exactly one switch; afterwards zero
        # blocks every different-action match with the global reason.
        policy = _policy(
            rules=[
                _rule(
                    "r1", 0, "act-b", _leaf(1, threshold=10), _leaf(1, threshold=500, operator="gt")
                ),
                _rule("r2", 1, "act-c", _leaf(1, threshold=10)),
            ],
            fallback_action_id="act-a",
            global_switch_budget=1,
        )
        results = _chain(policy, ((1, 25),), ((1, 25),))
        first = results[0]
        assert first.decision_event.action_changed is True
        assert first.switch_event is not None
        assert first.switch_event.global_switch_budget_before == 1
        assert first.switch_event.global_switch_budget_after == 0

        second = results[1]
        blocked_records = [
            record for record in second.decision_event.rule_evaluation_evidence if record[3]
        ]
        assert blocked_records
        assert all(record[3] == "global_switch_budget" for record in blocked_records)
        assert second.decision_event.decision_kind == "blocked_fallback"
        assert second.decision_event.fallback_blocked_reason == "global_switch_budget"
        assert second.decision_event.action_changed is False
        assert second.switch_event is None
        assert second.next_state.remaining_global_switch_budget == 0


class TestPerRuleBudgetBoundaries:
    def test_zero_rule_budget_blocks_that_rule_but_fallback_still_runs(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=0),
            ],
            fallback_action_id="act-a",
            global_switch_budget=3,
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        evidence = result.decision_event.rule_evaluation_evidence
        assert evidence == (("r1", "enter", True, "per_rule_switch_budget"),)
        assert result.decision_event.decision_kind == "fallback"
        assert result.decision_event.action_changed is False
        assert result.switch_event is None

    def test_one_rule_budget_permits_one_switch_and_then_blocks_that_rule(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1",
                    0,
                    "act-b",
                    _leaf(1, threshold=10),
                    _leaf(1, threshold=500, operator="gt"),
                    per_rule_switch_budget=1,
                ),
                _rule(
                    "r2",
                    1,
                    "act-c",
                    _leaf(1, threshold=10),
                    _leaf(1, threshold=500, operator="gt"),
                    per_rule_switch_budget=1,
                ),
            ],
            fallback_action_id="act-c",
            global_switch_budget=5,
            cooldown_steps=0,
        )
        # step0: r1 switches a->b (r1 budget 1->0). step1: r1 retain misses,
        # r2 switches b->c (r2 budget 1->0). step2: r1 (back to b, budget 0)
        # is blocked per-rule; r2 retains c and stops evaluation.
        results = _chain(policy, ((1, 25),), ((1, 25),), ((1, 25),))
        assert results[0].decision_event.selected_action_id == "act-b"
        switch0 = results[0].switch_event
        assert switch0 is not None
        assert switch0.rule_switch_budget_before == 1
        assert switch0.rule_switch_budget_after == 0
        assert results[1].decision_event.selected_action_id == "act-c"
        switch1 = results[1].switch_event
        assert switch1 is not None
        assert switch1.rule_switch_budget_before == 1
        assert switch1.rule_switch_budget_after == 0
        third = results[2]
        assert third.decision_event.action_changed is False
        assert third.next_state.current_action_id == "act-c"
        # r1 carries its per-rule blocked evidence on the way down.
        blocked = [record for record in third.decision_event.rule_evaluation_evidence if record[3]]
        assert ("r1", "enter", True, "per_rule_switch_budget") in blocked


# ---------------------------------------------------------------------------
# 7. Switch semantics: decrements, fallback, precedence, no-switch cases.
# ---------------------------------------------------------------------------


class TestSwitchDecrements:
    def test_rule_switch_decrements_global_and_that_rule_only(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=2),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20), per_rule_switch_budget=4),
            ],
            fallback_action_id="act-c",
            global_switch_budget=5,
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        switch = result.switch_event
        assert switch is not None
        assert switch.trigger_kind == "rule"
        assert switch.triggering_rule_id == "r1"
        assert switch.global_switch_budget_before == 5
        assert switch.global_switch_budget_after == 4
        assert switch.rule_switch_budget_before == 2
        assert switch.rule_switch_budget_after == 1
        assert result.next_state.remaining_global_switch_budget == 4
        assert result.next_state.per_rule_remaining_budgets == (("r1", 1), ("r2", 4))

    def test_fallback_switch_decrements_global_only(self) -> None:
        policy = _single_rule_policy(target="act-b", enter=_leaf(1, threshold=500, operator="gt"))
        # The only rule never matches, so the different fallback act-c switches.
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 1))
        assert result.decision_event.decision_kind == "fallback"
        assert result.decision_event.selected_action_id == "act-c"
        assert result.decision_event.action_changed is True
        switch = result.switch_event
        assert switch is not None
        assert switch.trigger_kind == "fallback"
        assert switch.triggering_rule_id is None
        assert switch.rule_switch_budget_before is None
        assert switch.rule_switch_budget_after is None
        assert (switch.global_switch_budget_before, switch.global_switch_budget_after) == (3, 2)
        assert result.next_state.per_rule_remaining_budgets == (("r1", 3),)

    def test_fallback_retains_current_action_without_a_switch(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-b", _leaf(1, threshold=500, operator="gt"))],
            fallback_action_id="act-a",
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 1))
        assert result.decision_event.decision_kind == "fallback"
        assert result.decision_event.selected_action_id == "act-a"
        assert result.decision_event.action_changed is False
        assert result.switch_event is None


class TestFallbackCannotBypassEligibility:
    def test_fallback_cannot_bypass_dwell(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-c", _leaf(1, threshold=500, operator="gt"))],
            fallback_action_id="act-b",
            minimum_dwell_steps=2,
        )
        result = _advance(policy, initialize_adaptive_policy_state(policy), (1, 1))
        assert result.decision_event.decision_kind == "blocked_fallback"
        assert result.decision_event.fallback_blocked_reason == "minimum_dwell"
        assert result.decision_event.action_changed is False
        assert result.switch_event is None

    def test_fallback_cannot_bypass_cooldown(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1", 0, "act-b", _leaf(1, threshold=10), _leaf(1, threshold=500, operator="gt")
                ),
                _rule("r2", 1, "act-c", _leaf(1, threshold=500, operator="gt")),
            ],
            fallback_action_id="act-c",
            cooldown_steps=2,
            global_switch_budget=5,
        )
        # Step0 switches to act-b (s=0). Step1: r1 retain misses, r2 enter
        # misses, fallback act-c differs but cooldown blocks it.
        results = _chain(policy, ((1, 25),), ((1, 1),))
        assert results[0].decision_event.action_changed is True
        second = results[1]
        assert second.decision_event.decision_kind == "blocked_fallback"
        assert second.decision_event.fallback_blocked_reason == "cooldown"
        assert second.decision_event.action_changed is False
        assert second.switch_event is None

    def test_fallback_cannot_bypass_global_budget(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1", 0, "act-b", _leaf(1, threshold=10), _leaf(1, threshold=500, operator="gt")
                )
            ],
            fallback_action_id="act-c",
            global_switch_budget=1,
        )
        results = _chain(policy, ((1, 25),), ((1, 1),))
        assert results[0].decision_event.action_changed is True
        switch0 = results[0].switch_event
        assert switch0 is not None
        assert switch0.global_switch_budget_after == 0
        second = results[1]
        assert second.decision_event.decision_kind == "blocked_fallback"
        assert second.decision_event.fallback_blocked_reason == "global_switch_budget"
        assert second.decision_event.action_changed is False
        assert second.switch_event is None


class TestBlockedReasonPrecedence:
    def test_precedence_is_dwell_then_cooldown_then_global_then_rule(self) -> None:
        # All four restrictions hold at once; the single recorded reason is
        # exactly minimum_dwell (first in precedence).
        policy = _policy(
            rules=[
                _rule(
                    "r1",
                    0,
                    "act-b",
                    _leaf(1, threshold=10),
                    per_rule_switch_budget=0,
                )
            ],
            fallback_action_id="act-b",
            minimum_dwell_steps=5,
            cooldown_steps=3,
            global_switch_budget=0,
        )
        state = AdaptivePolicyStateSnapshot(
            runtime_version="4.0.0",
            policy_id=policy.policy_id,
            policy_content_hash=policy.content_hash,
            decision_step=1,
            current_action_id="act-a",
            action_installed_at_decision_step=0,
            completed_applications=1,
            last_switch_decision_step=None,
            remaining_global_switch_budget=0,
            per_rule_remaining_budgets=(("r1", 0),),
        )
        result = _advance(policy, state, (1, 25))
        assert result.decision_event.rule_evaluation_evidence == (
            ("r1", "enter", True, "minimum_dwell"),
        )

    def test_cooldown_wins_over_global_and_rule_when_dwell_passes(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=0)],
            fallback_action_id="act-b",
            minimum_dwell_steps=0,
            cooldown_steps=4,
            global_switch_budget=0,
        )
        state = AdaptivePolicyStateSnapshot(
            runtime_version="4.0.0",
            policy_id=policy.policy_id,
            policy_content_hash=policy.content_hash,
            decision_step=1,
            current_action_id="act-a",
            action_installed_at_decision_step=0,
            completed_applications=1,
            last_switch_decision_step=0,
            remaining_global_switch_budget=0,
            per_rule_remaining_budgets=(("r1", 0),),
        )
        result = _advance(policy, state, (1, 25))
        assert result.decision_event.rule_evaluation_evidence == (
            ("r1", "enter", True, "cooldown"),
        )

    def test_global_wins_over_rule_budget_when_dwell_and_cooldown_pass(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=0)],
            fallback_action_id="act-b",
            minimum_dwell_steps=0,
            cooldown_steps=0,
            global_switch_budget=0,
        )
        state = AdaptivePolicyStateSnapshot(
            runtime_version="4.0.0",
            policy_id=policy.policy_id,
            policy_content_hash=policy.content_hash,
            decision_step=2,
            current_action_id="act-a",
            action_installed_at_decision_step=1,
            completed_applications=1,
            last_switch_decision_step=1,
            remaining_global_switch_budget=0,
            per_rule_remaining_budgets=(("r1", 0),),
        )
        result = _advance(policy, state, (1, 25))
        assert result.decision_event.rule_evaluation_evidence == (
            ("r1", "enter", True, "global_switch_budget"),
        )


class TestNoSwitchDecisionKinds:
    def test_initialization_same_action_and_blocked_never_produce_switch_events(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=0)],
            fallback_action_id="act-a",
            minimum_dwell_steps=1,
        )
        # blocked decision
        blocked = _advance(policy, initialize_adaptive_policy_state(policy), (1, 1))
        assert blocked.decision_event.action_changed is False
        assert blocked.switch_event is None
        # same-action retention: r1 matches via enter? no, enter targets act-b
        # while current act-a; make a same-action rule match instead.
        same_policy = _policy(
            rules=[_rule("r1", 0, "act-a", _leaf(1, threshold=10))],
            fallback_action_id="act-c",
        )
        same = _advance(same_policy, initialize_adaptive_policy_state(same_policy), (1, 25))
        assert same.decision_event.action_changed is False
        assert same.switch_event is None
        # initialization never emits a switch event (nothing to advance).
        assert initialize_adaptive_policy_state(same_policy).last_switch_decision_step is None


# ---------------------------------------------------------------------------
# 8. Next-state semantics and chained runs.
# ---------------------------------------------------------------------------


class TestNextSnapshotSemantics:
    def test_unchanged_step_increments_completed_applications_only(self) -> None:
        policy = _policy(
            rules=[_rule("r1", 0, "act-a", _leaf(1, threshold=10))],
            initial_action_id="act-a",
            fallback_action_id="act-c",
        )
        state = initialize_adaptive_policy_state(policy)
        first = _advance(policy, state, (1, 25))
        second = _advance(policy, first.next_state, (1, 25))
        assert first.next_state.decision_step == 1
        assert first.next_state.completed_applications == 1
        assert second.next_state.decision_step == 2
        assert second.next_state.completed_applications == 2
        assert second.next_state.action_installed_at_decision_step == 0
        assert second.next_state.last_switch_decision_step is None
        # completed == decision - installed invariant holds chain-wide.
        snap = second.next_state
        assert (
            snap.completed_applications
            == snap.decision_step - snap.action_installed_at_decision_step
        )

    def test_changed_step_resets_install_completed_and_last_switch(self) -> None:
        # retain threshold is low enough that a later observation retains
        # act-b, while enter requires >= 10 for the initial switch.
        policy = _single_rule_policy(
            target="act-b",
            enter=_leaf(1, threshold=10),
            retain=_leaf(1, threshold=3),
            global_switch_budget=3,
        )
        first = _advance(policy, initialize_adaptive_policy_state(policy), (1, 25))
        assert first.next_state.current_action_id == "act-b"
        assert first.next_state.action_installed_at_decision_step == 0
        assert first.next_state.completed_applications == 1
        assert first.next_state.last_switch_decision_step == 0
        second = _advance(policy, first.next_state, (1, 5))
        # obs 5 retains act-b (retain >= 3); no switch, no budget change.
        assert second.decision_event.action_changed is False
        assert second.next_state.completed_applications == 2
        assert second.next_state.action_installed_at_decision_step == 0
        assert second.next_state.last_switch_decision_step == 0
        assert second.next_state.remaining_global_switch_budget == 2

    def test_multiple_consecutive_decisions_and_switching_back(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1",
                    0,
                    "act-b",
                    _leaf(1, threshold=10),
                    _leaf(1, threshold=500, operator="gt"),
                    per_rule_switch_budget=2,
                ),
                _rule(
                    "r2",
                    1,
                    "act-c",
                    _leaf(2, threshold=10),
                    _leaf(2, threshold=500, operator="gt"),
                    per_rule_switch_budget=2,
                ),
                _rule(
                    "r3",
                    2,
                    "act-a",
                    _leaf(3, threshold=10),
                    _leaf(3, threshold=500, operator="gt"),
                    per_rule_switch_budget=2,
                ),
            ],
            fallback_action_id="act-a",
            global_switch_budget=5,
        )
        # step0: obs1 drives r1 -> act-b. step1: obs2 drives r2 -> act-c.
        # step2: obs3 drives r3 back to act-a (r1 and r2 do not match).
        results = _chain(
            policy,
            ((1, 25), (2, 1), (3, 1)),
            ((1, 1), (2, 25), (3, 1)),
            ((1, 1), (2, 1), (3, 25)),
        )
        assert results[0].decision_event.selected_action_id == "act-b"
        assert results[0].decision_event.selected_rule_id == "r1"
        assert results[1].decision_event.selected_action_id == "act-c"
        assert results[1].decision_event.selected_rule_id == "r2"
        assert results[2].decision_event.selected_action_id == "act-a"
        assert results[2].decision_event.selected_rule_id == "r3"
        assert results[2].switch_event is not None
        assert results[2].switch_event.old_action_id == "act-c"
        assert results[2].switch_event.new_action_id == "act-a"
        final = results[2].next_state
        assert final.current_action_id == "act-a"
        assert final.action_installed_at_decision_step == 2
        assert final.completed_applications == 1
        assert final.last_switch_decision_step == 2
        assert final.remaining_global_switch_budget == 2
        assert final.per_rule_remaining_budgets == (("r1", 1), ("r2", 1), ("r3", 1))


class TestDeterminismAndImmutability:
    def test_repeated_calls_are_exactly_equal(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1", 0, "act-b", _leaf(1, threshold=10), _leaf(1, threshold=500, operator="gt")
                ),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20)),
            ],
            fallback_action_id="act-a",
        )
        state = initialize_adaptive_policy_state(policy)
        first = _advance(policy, state, (1, 25))
        second = _advance(policy, state, (1, 25))
        assert first.next_state == second.next_state
        assert first.decision_event == second.decision_event
        assert first.switch_event == second.switch_event

    def test_inputs_are_never_mutated_on_success(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)
        before_policy = policy.model_dump(mode="json")
        before_state = state.model_dump(mode="json")
        _advance(policy, state, (1, 25))
        assert policy.model_dump(mode="json") == before_policy
        assert state.model_dump(mode="json") == before_state

    def test_inputs_are_never_mutated_on_failure(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)
        before_state = state.model_dump(mode="json")
        foreign = _single_rule_policy(policy_id="foreign")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(foreign, state, (1, 25))
        assert state.model_dump(mode="json") == before_state


# ---------------------------------------------------------------------------
# 9. Fail-closed rejection of malformed and adversarial inputs.
# ---------------------------------------------------------------------------


class TestFailClosedRejection:
    def test_subclassed_and_malformed_policy_inputs_are_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)

        class SubPolicy(AdaptivePolicy):
            pass

        payload = policy.model_dump(mode="json")
        sub = SubPolicy.model_validate(payload)
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=sub,
                state=state,
                events=_evidence((1, 25)),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )
        # A same-type instance is accepted through preflight.
        assert (
            advance_adaptive_policy_state(
                policy=policy,
                state=state,
                events=_evidence((1, 25), available=0),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            ).decision_event.action_changed
            is True
        )

    def test_subclassed_snapshot_is_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)

        class SubSnapshot(AdaptivePolicyStateSnapshot):
            pass

        snapshot = SubSnapshot.model_validate(state.model_dump(mode="json"))
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=policy,
                state=snapshot,
                events=_evidence((1, 25)),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )

    def test_foreign_policy_snapshot_is_rejected(self) -> None:
        foreign = _single_rule_policy(policy_id="foreign-policy")
        home = _single_rule_policy(policy_id="policy-x")
        state = initialize_adaptive_policy_state(home)
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(foreign, state, (1, 25))

    def test_unknown_current_action_is_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy).model_copy(
            update={"current_action_id": "act-zz"}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, state, (1, 25))

    def test_reordered_per_rule_budget_tuple_is_rejected(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10)),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20)),
            ],
            global_switch_budget=3,
        )
        state = initialize_adaptive_policy_state(policy).model_copy(
            update={"per_rule_remaining_budgets": (("r2", 3), ("r1", 3))}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, state, (1, 25))

    def test_inflated_per_rule_budget_is_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy).model_copy(
            update={"per_rule_remaining_budgets": (("r1", 99),)}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, state, (1, 25))

    def test_inflated_global_budget_is_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b", global_switch_budget=3)
        state = initialize_adaptive_policy_state(policy).model_copy(
            update={"remaining_global_switch_budget": 7}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, state, (1, 25))

    def test_inconsistent_snapshot_is_rejected_by_contract_and_machine(self) -> None:
        # The contract rejects an inconsistent snapshot at construction...
        with pytest.raises(ValidationError):
            AdaptivePolicyStateSnapshot.model_validate(_snapshot_payload(completed_applications=9))
        # ...and a validator-bypassing copy is rejected by the machine preflight.
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy).model_copy(
            update={"completed_applications": 9}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, state, (1, 25))

    def test_malformed_events_tuple_is_rejected(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=policy,
                state=state,
                events=[_event(1, value=25)],  # type: ignore[arg-type]
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )

    def test_wrong_seed_identity_is_rejected_by_the_evaluator(self) -> None:
        policy = _single_rule_policy(target="act-b")
        state = initialize_adaptive_policy_state(policy)
        with pytest.raises(AdaptiveConditionEvaluationError):
            advance_adaptive_policy_state(
                policy=policy,
                state=state,
                events=_evidence((1, 25)),
                scenario_seed_id="other-seed",
                seed_content_hash=SEED_HASH,
            )


class TestEvaluatorErrorPropagation:
    def test_missing_error_observation_propagates_with_zero_partial_result(self) -> None:
        policy = _policy(
            rules=[
                _rule(
                    "r1",
                    0,
                    "act-b",
                    _leaf(1, threshold=10, missing="error"),
                )
            ],
            fallback_action_id="act-a",
        )
        state = initialize_adaptive_policy_state(policy)
        with pytest.raises(AdaptiveConditionMissingObservationError):
            _advance(policy, state, (1, 0), missing={1})
        # State still untouched and reusable afterwards.
        assert state.decision_step == 0


# ---------------------------------------------------------------------------
# 9b. DEFECT-2 detached strict revalidation of validator-bypassed instances.
# ---------------------------------------------------------------------------


class TestDetachedStrictRevalidation:
    def _policy_and_state(self) -> tuple[AdaptivePolicy, AdaptivePolicyStateSnapshot]:
        policy = _single_rule_policy(target="act-b")
        return policy, initialize_adaptive_policy_state(policy)

    @pytest.mark.parametrize(
        "bad_budget",
        [True, "3", 3.5, -1, None],
    )
    def test_bool_string_float_negative_snapshot_global_budget_fails(self, bad_budget: Any) -> None:
        policy, state = self._policy_and_state()
        tampered = state.model_copy(update={"remaining_global_switch_budget": bad_budget})
        before = tampered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, tampered, (1, 25))
        assert tampered.model_dump(mode="python") == before

    def test_malformed_per_rule_budget_tuple_fails(self) -> None:
        policy, state = self._policy_and_state()
        tampered = state.model_copy(update={"per_rule_remaining_budgets": (("r1", "lots"),)})
        before = tampered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, tampered, (1, 25))
        assert tampered.model_dump(mode="python") == before

    def test_inconsistent_temporal_fields_fail(self) -> None:
        policy, state = self._policy_and_state()
        tampered = state.model_copy(update={"completed_applications": 9})
        before = tampered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(policy, tampered, (1, 25))
        assert tampered.model_dump(mode="python") == before

    def test_invalid_policy_rule_order_fails(self) -> None:
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10), per_rule_switch_budget=2),
                _rule("r2", 1, "act-c", _leaf(1, threshold=20), per_rule_switch_budget=2),
            ],
            fallback_action_id="act-c",
            global_switch_budget=3,
        )
        state = initialize_adaptive_policy_state(policy)
        reordered = policy.model_copy(update={"rules": tuple(reversed(policy.rules))})
        before = reordered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=reordered,
                state=state,
                events=_evidence((1, 25)),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )
        assert reordered.model_dump(mode="python") == before

    def test_malformed_policy_scalar_field_fails(self) -> None:
        policy, state = self._policy_and_state()
        tampered = policy.model_copy(update={"minimum_dwell_steps": True})
        before = tampered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(tampered, state, (1, 25))
        assert tampered.model_dump(mode="python") == before

    def test_malformed_runtime_observation_event_field_fails(self) -> None:
        policy, state = self._policy_and_state()
        bad_event = _event(1, value=25).model_copy(update={"source_step_index": "nope"})
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=policy,
                state=state,
                events=(bad_event,),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )

    def test_non_finite_nested_event_value_fails(self) -> None:
        policy, state = self._policy_and_state()
        bad_event = _event(1, value=25, observed_kind="number").model_copy(
            update={"exposed_observation_value": float("inf")}
        )
        with pytest.raises(AdaptivePolicyStateMachineError):
            advance_adaptive_policy_state(
                policy=policy,
                state=state,
                events=(bad_event,),
                scenario_seed_id=SEED_ID,
                seed_content_hash=SEED_HASH,
            )

    def test_bypassed_policy_is_never_repaired_or_replaced(self) -> None:
        policy, state = self._policy_and_state()
        tampered = policy.model_copy(update={"global_switch_budget": -1})
        before = tampered.model_dump(mode="python")
        with pytest.raises(AdaptivePolicyStateMachineError):
            _advance(tampered, state, (1, 25))
        assert tampered.model_dump(mode="python") == before
        # The untampered original still advances successfully.
        assert _advance(policy, state, (1, 25)).decision_event.action_changed is True

    def test_legitimate_evaluator_errors_still_propagate_unchanged(self) -> None:
        # DEFECT-2 preflight must not convert legitimate evaluator errors.
        policy = _policy(
            rules=[
                _rule("r1", 0, "act-b", _leaf(1, threshold=10, missing="error")),
            ],
            fallback_action_id="act-a",
        )
        state = initialize_adaptive_policy_state(policy)
        with pytest.raises(AdaptiveConditionMissingObservationError):
            _advance(policy, state, (1, 0), missing={1})


# ---------------------------------------------------------------------------
# 10. Forbidden subsystem surface, purity, and protected fingerprints.
# ---------------------------------------------------------------------------


class TestForbiddenSurface:
    _FORBIDDEN_IMPORTS = (
        "importlib",
        "__import__",
        "eval(",
        "exec(",
        "in_memory_store",
        "operational_activity",
        "ActivityEvent",
        "dataset_gateway",
        "external_provider",
        "DatasetGateway",
    )
    _SUBSYSTEM_PATHS = (
        "kalhas.adapters",
        "kalhas.legion",
        "kalhas.nexus",
        "NexusAdapter",
        "LegionAdapter",
        "in_memory_store",
        "operational_activity",
        "ActivityEvent",
        "dataset_gateway",
        "external_provider",
        "DatasetGateway",
    )
    _DYNAMIC_TOKENS = (
        "random.",
        ".randint",
        ".uniform(",
        "uuid4",
        "datetime.now",
        "time.time",
        "monotonic",
        "socket",
        "Path(",
        "os.path",
        "open(",
    )

    def test_machine_and_errors_sources_have_no_forbidden_surface(self) -> None:
        import kalhas.application.adaptive_policy_state_errors as errors_mod
        import kalhas.application.adaptive_policy_state_machine as machine_mod

        for source in (inspect.getsource(machine_mod), inspect.getsource(errors_mod)):
            for fragment in self._FORBIDDEN_IMPORTS:
                assert fragment not in source
            for token in self._DYNAMIC_TOKENS:
                assert token not in source
            for path in self._SUBSYSTEM_PATHS:
                assert path not in source
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    assert stripped.startswith(
                        (
                            "from __future__",
                            "from dataclasses",
                            "from typing",
                            "from pydantic",
                            "import warnings",
                            "from kalhas.",
                        )
                    ), stripped

    def test_machine_reuses_the_production_condition_evaluator(self) -> None:
        import kalhas.application.adaptive_policy_state_machine as machine_mod

        source = inspect.getsource(machine_mod)
        assert "evaluate_adaptive_condition(" in source
        # The closed leaf operators and the AST walk are never reimplemented.
        for operator_token in ("_apply_operator", "_eval_node", "_eval_leaf"):
            assert operator_token not in source

    def test_result_dataclass_is_frozen_and_slotted(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(AdaptivePolicyStepResult)
        assert AdaptivePolicyStepResult.__slots__ == (
            "decision_event",
            "switch_event",
            "next_state",
        )

    def test_protected_git_blobs_are_unchanged(self) -> None:
        for rel_path, expected in PROTECTED_FINGERPRINTS.items():
            result = subprocess.run(
                ["git", "hash-object", str(REPO_ROOT / rel_path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == expected, rel_path

    def test_nested_roles_have_no_standalone_schema_and_registry_stays_synchronized(
        self,
    ) -> None:
        schema_names = {path.name for path in (REPO_ROOT / "schemas" / "v1").glob("*.schema.json")}
        assert len(schema_names) == len(PUBLIC_CONTRACTS)
        for path in (
            "AdaptivePolicyStateSnapshot",
            "AdaptivePolicyDecisionEvent",
            "AdaptivePolicySwitchEvent",
        ):
            assert f"{path}.schema.json" not in schema_names
