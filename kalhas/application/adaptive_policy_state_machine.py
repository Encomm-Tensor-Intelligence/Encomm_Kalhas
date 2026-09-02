"""Pure runtime-4 adaptive-policy state machine (Phase 28, H28-S04).

Implements the pure, deterministic runtime-4 policy state machine: an
initializer that builds the immutable :class:`AdaptivePolicyStateSnapshot` for
a policy, and an ``advance`` step that turns one pre-decision snapshot and one
current-decision causal :class:`RuntimeObservationEvent` tuple into a new
:class:`AdaptivePolicyDecisionEvent`, the actual switch event (exactly when
the action changed, else ``None``), and the following pre-decision snapshot.
It is pure and deterministic: no stores, persistence, activity events, API,
trajectory execution, wall clock, RNG, UUID, filesystem, network, provider,
adapter, NEXUS, or LEGION dependency, no input mutation, and no partial result
on failure.

Every evaluated enter/retain tree uses the accepted production function
:func:`evaluate_adaptive_condition` (H28-S03); the numeric, missing, event-
hash, timing, and condition-AST evaluation logic is never duplicated here.
:class:`AdaptiveConditionEvaluationError` and
:class:`AdaptiveConditionMissingObservationError` propagate unchanged with
zero partial result.

Frozen ADR-004/D28-01 state-machine semantics:

- initialization is not a switch and consumes no budget;
- rules evaluate in ascending stored priority order; the first matching
  *eligible* rule wins and lower rules are not evaluated;
- a matching same-action rule is eligible immediately: it selects the current
  action and consumes no budget;
- a matching different-action rule must pass eligibility (minimum dwell,
  cooldown, global budget, and its own rule budget); a matching ineligible rule
  records exactly one deterministic blocked reason and evaluation continues;
- the fallback action cannot bypass dwell, cooldown, or the global budget, has
  no per-rule budget, and a blocked fallback retains the current action with
  ``decision_kind == "blocked_fallback"``;
- only an actual action change decrements the global budget exactly once and
  the triggering rule's budget exactly once (rule switches only), and updates
  the last-switch step; the next snapshot advances the decision step by one.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_condition_evaluator import evaluate_adaptive_condition
from kalhas.application.adaptive_policy_state_errors import AdaptivePolicyStateMachineError
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyRule,
    ConditionNode,
)
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
    ConditionRole,
    DecisionKind,
    EligibilityBlockedReason,
    RuleEvaluationRecord,
    SwitchTriggerKind,
)
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"


@dataclass(frozen=True, slots=True)
class AdaptivePolicyStepResult:
    """The frozen, slotted outcome of one policy step.

    Carries the decision event, the switch event (exactly ``None`` when the
    action did not change - i.e. initialization, same-action selection, and
    blocked decisions never produce one), and the next immutable pre-decision
    state snapshot.
    """

    decision_event: AdaptivePolicyDecisionEvent
    switch_event: AdaptivePolicySwitchEvent | None
    next_state: AdaptivePolicyStateSnapshot


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied artifact from its detached serialization.

    The artifact's Python payload is re-derived with the established Pydantic
    serializer-warnings suppression and the exact model class is re-validated
    with ``strict=True``, so a validator-bypassed same-type instance
    (wrong-typed or non-finite raw values, booleans where strict integers
    belong, malformed budget tuples, inconsistent fields, tampered nested
    records) is rejected before any field of it is trusted. The revalidation
    result is discarded; the supplied artifact is never replaced, repaired,
    or mutated. Any structural, type, or validator failure is converted to
    the typed :class:`AdaptivePolicyStateMachineError` with a safe internal
    reason; a raw Pydantic ``ValidationError``, ``TypeError``, or
    ``AttributeError`` is never leaked.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise AdaptivePolicyStateMachineError("input_failed_detached_strict_revalidation") from None


def initialize_adaptive_policy_state(policy: AdaptivePolicy) -> AdaptivePolicyStateSnapshot:
    """Build the immutable initial pre-decision state for a policy.

    The policy must be an exact runtime-4 :class:`AdaptivePolicy`. The initial
    snapshot is at decision step 0, holds ``initial_action_id`` installed at
    step 0 with zero completed applications, carries no last switch, and the
    full global and per-rule budgets in policy rule order. Initialization is
    not a switch and consumes no budget.
    """
    if type(policy) is not AdaptivePolicy:
        raise AdaptivePolicyStateMachineError("policy_must_be_exact_adaptive_policy")
    _strictly_revalidate_detached(policy, AdaptivePolicy)
    if policy.runtime_version != RUNTIME_VERSION:
        raise AdaptivePolicyStateMachineError("policy_must_be_runtime_4")
    budgets = tuple((rule.rule_id, rule.per_rule_switch_budget) for rule in policy.rules)
    return AdaptivePolicyStateSnapshot(
        runtime_version=RUNTIME_VERSION,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=0,
        current_action_id=policy.initial_action_id,
        action_installed_at_decision_step=0,
        completed_applications=0,
        last_switch_decision_step=None,
        remaining_global_switch_budget=policy.global_switch_budget,
        per_rule_remaining_budgets=budgets,
    )


def advance_adaptive_policy_state(
    *,
    policy: AdaptivePolicy,
    state: AdaptivePolicyStateSnapshot,
    events: tuple[RuntimeObservationEvent, ...],
    scenario_seed_id: str,
    seed_content_hash: str,
) -> AdaptivePolicyStepResult:
    """Advance one policy step from a pre-decision snapshot and decision.

    ``policy`` is the exact immutable ``AdaptivePolicy``, ``state`` is the
    exact pre-decision ``AdaptivePolicyStateSnapshot`` (its ``decision_step``
    drives the step), ``events`` is the exact tuple of current-decision
    ``RuntimeObservationEvent`` instances, and ``scenario_seed_id`` /
    ``seed_content_hash`` are the expected scenario-seed identity and content
    hash the events must agree with.

    The complete input is verified atomically and fail-closed before any
    evaluation (never repaired, sorted, coerced, or silently accepted). On
    success it returns a frozen :class:`AdaptivePolicyStepResult`; on failure
    it raises :class:`AdaptivePolicyStateMachineError` or lets the condition
    evaluator's typed errors propagate unchanged, with no partial result and
    no input mutation.
    """
    _preflight(
        policy=policy,
        state=state,
        events=events,
        scenario_seed_id=scenario_seed_id,
        seed_content_hash=seed_content_hash,
    )

    decision_step = state.decision_step
    budgets_by_rule: dict[str, int] = {
        rule_id: budget for rule_id, budget in state.per_rule_remaining_budgets
    }

    evidence: list[RuleEvaluationRecord] = []
    selected_rule_id: str | None = None
    selected_action_id: str = state.current_action_id
    action_changed = False
    decision_kind: DecisionKind = "fallback"
    fallback_blocked_reason: EligibilityBlockedReason | None = None
    trigger_kind: SwitchTriggerKind | None = None
    triggered_rule_id: str | None = None
    rule_budget_before: int | None = None

    for rule in policy.rules:
        role, condition = _rule_enter_or_retain(state=state, rule=rule)
        evaluation = evaluate_adaptive_condition(
            policy=policy,
            condition=condition,
            events=events,
            decision_step=decision_step,
            scenario_seed_id=scenario_seed_id,
            seed_content_hash=seed_content_hash,
        )
        matched = evaluation.matched
        if not matched:
            evidence.append((rule.rule_id, role, False, None))
            continue
        if role == "retain":
            # Same-action match: eligible immediately, consumes no budget.
            evidence.append((rule.rule_id, role, True, None))
            selected_rule_id = rule.rule_id
            decision_kind = "rule"
            action_changed = False
            break
        # Matching different-action rule: must pass eligibility.
        block = _eligibility_block(
            policy=policy,
            state=state,
            decision_step=decision_step,
            include_per_rule=True,
            rule_budget=budgets_by_rule.get(rule.rule_id, 0),
        )
        if block is not None:
            evidence.append((rule.rule_id, role, True, block))
            continue
        evidence.append((rule.rule_id, role, True, None))
        selected_rule_id = rule.rule_id
        selected_action_id = rule.target_action_id
        decision_kind = "rule"
        action_changed = True
        trigger_kind = "rule"
        triggered_rule_id = rule.rule_id
        rule_budget_before = budgets_by_rule[rule.rule_id]
        break
    else:
        # No matching eligible rule won: the fallback action decides.
        if policy.fallback_action_id == state.current_action_id:
            selected_action_id = state.current_action_id
            decision_kind = "fallback"
            action_changed = False
        else:
            block = _eligibility_block(
                policy=policy,
                state=state,
                decision_step=decision_step,
                include_per_rule=False,
                rule_budget=0,
            )
            if block is not None:
                selected_action_id = state.current_action_id
                decision_kind = "blocked_fallback"
                fallback_blocked_reason = block
                action_changed = False
            else:
                selected_action_id = policy.fallback_action_id
                decision_kind = "fallback"
                action_changed = True
                trigger_kind = "fallback"
                triggered_rule_id = None
                rule_budget_before = None

    decision_event = AdaptivePolicyDecisionEvent(
        runtime_version=RUNTIME_VERSION,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=decision_step,
        current_action_id=state.current_action_id,
        rule_evaluation_evidence=tuple(evidence),
        selected_rule_id=selected_rule_id,
        selected_action_id=selected_action_id,
        decision_kind=decision_kind,
        action_changed=action_changed,
        fallback_blocked_reason=fallback_blocked_reason,
    )

    # For an actual action change the trigger kind must already be explicitly
    # established ("rule" or "fallback"); an impossible combination fails
    # closed rather than being silently inferred as a fallback.
    if action_changed and trigger_kind is None:
        raise AdaptivePolicyStateMachineError("action_changed_without_trigger_kind")

    # Generated snapshot/decision/switch records must never leak a generic
    # Pydantic validation exception; convert any unexpected failure into the
    # typed state-machine error with no partial result.
    try:
        if action_changed:
            if trigger_kind is None:
                raise AdaptivePolicyStateMachineError("action_changed_without_trigger_kind")
            switch_trigger_kind: SwitchTriggerKind = trigger_kind
            switch_event = AdaptivePolicySwitchEvent(
                runtime_version=RUNTIME_VERSION,
                policy_id=policy.policy_id,
                policy_content_hash=policy.content_hash,
                decision_step=decision_step,
                old_action_id=state.current_action_id,
                new_action_id=selected_action_id,
                trigger_kind=switch_trigger_kind,
                triggering_rule_id=triggered_rule_id,
                global_switch_budget_before=state.remaining_global_switch_budget,
                global_switch_budget_after=state.remaining_global_switch_budget - 1,
                rule_switch_budget_before=rule_budget_before,
                rule_switch_budget_after=(
                    rule_budget_before - 1 if rule_budget_before is not None else None
                ),
            )
        else:
            switch_event = None

        if action_changed:
            next_state = AdaptivePolicyStateSnapshot(
                runtime_version=RUNTIME_VERSION,
                policy_id=policy.policy_id,
                policy_content_hash=policy.content_hash,
                decision_step=decision_step + 1,
                current_action_id=selected_action_id,
                action_installed_at_decision_step=decision_step,
                completed_applications=1,
                last_switch_decision_step=decision_step,
                remaining_global_switch_budget=state.remaining_global_switch_budget - 1,
                per_rule_remaining_budgets=_next_per_rule_budgets(
                    current=state.per_rule_remaining_budgets,
                    decremented_rule_id=triggered_rule_id,
                ),
            )
        else:
            next_state = AdaptivePolicyStateSnapshot(
                runtime_version=RUNTIME_VERSION,
                policy_id=policy.policy_id,
                policy_content_hash=policy.content_hash,
                decision_step=decision_step + 1,
                current_action_id=selected_action_id,
                action_installed_at_decision_step=state.action_installed_at_decision_step,
                completed_applications=state.completed_applications + 1,
                last_switch_decision_step=state.last_switch_decision_step,
                remaining_global_switch_budget=state.remaining_global_switch_budget,
                per_rule_remaining_budgets=state.per_rule_remaining_budgets,
            )
    except (ValidationError, TypeError, AttributeError):
        raise AdaptivePolicyStateMachineError("generated_record_failed_strict_integrity") from None

    return AdaptivePolicyStepResult(
        decision_event=decision_event,
        switch_event=switch_event,
        next_state=next_state,
    )


def _rule_enter_or_retain(
    *,
    state: AdaptivePolicyStateSnapshot,
    rule: AdaptivePolicyRule,
) -> tuple[ConditionRole, ConditionNode]:
    """Return the role and tree for one rule under the current action."""
    if rule.target_action_id == state.current_action_id:
        return "retain", rule.retain_condition
    return "enter", rule.enter_condition


def _eligibility_block(
    *,
    policy: AdaptivePolicy,
    state: AdaptivePolicyStateSnapshot,
    decision_step: int,
    include_per_rule: bool,
    rule_budget: int,
) -> EligibilityBlockedReason | None:
    """Return the single deterministic blocked reason or ``None`` if eligible.

    Precedence is frozen: ``minimum_dwell``, ``cooldown``, ``global_switch_budget``,
    then (for an actual rule-triggered change) ``per_rule_switch_budget``. The
    blocking checks are selected-entire; only the first failing reason is returned.
    """
    if decision_step < (policy.minimum_dwell_steps + state.action_installed_at_decision_step):
        return "minimum_dwell"
    if state.last_switch_decision_step is not None and decision_step < (
        state.last_switch_decision_step + policy.cooldown_steps + 1
    ):
        return "cooldown"
    if state.remaining_global_switch_budget <= 0:
        return "global_switch_budget"
    if include_per_rule and rule_budget <= 0:
        return "per_rule_switch_budget"
    return None


def _next_per_rule_budgets(
    *,
    current: tuple[tuple[str, int], ...],
    decremented_rule_id: str | None,
) -> tuple[tuple[str, int], ...]:
    if decremented_rule_id is None:
        return current
    return tuple(
        (rule_id, budget - 1 if rule_id == decremented_rule_id else budget)
        for rule_id, budget in current
    )


def _preflight(
    *,
    policy: AdaptivePolicy,
    state: AdaptivePolicyStateSnapshot,
    events: tuple[RuntimeObservationEvent, ...],
    scenario_seed_id: str,
    seed_content_hash: str,
) -> None:
    """Verify the complete advance input atomically; never repair or coerce."""

    if type(policy) is not AdaptivePolicy:
        raise AdaptivePolicyStateMachineError("policy_must_be_exact_adaptive_policy")
    if policy.runtime_version != RUNTIME_VERSION:
        raise AdaptivePolicyStateMachineError("policy_must_be_runtime_4")
    if type(state) is not AdaptivePolicyStateSnapshot:
        raise AdaptivePolicyStateMachineError("state_must_be_exact_adaptive_policy_state_snapshot")
    if state.runtime_version != RUNTIME_VERSION:
        raise AdaptivePolicyStateMachineError("state_must_be_runtime_4")
    if state.policy_id != policy.policy_id:
        raise AdaptivePolicyStateMachineError("state_policy_id_mismatch")
    if state.policy_content_hash != policy.content_hash:
        raise AdaptivePolicyStateMachineError("state_policy_content_hash_mismatch")
    if not isinstance(events, tuple) or not all(
        type(event) is RuntimeObservationEvent for event in events
    ):
        raise AdaptivePolicyStateMachineError(
            "events_must_be_exact_tuple_of_runtime_observation_events"
        )
    if not isinstance(scenario_seed_id, str):
        raise AdaptivePolicyStateMachineError("scenario_seed_id_must_be_a_str")
    if not isinstance(seed_content_hash, str):
        raise AdaptivePolicyStateMachineError("seed_content_hash_must_be_a_str")

    # Detached strict revalidation precedes any trusted field read: a
    # validator-bypassed same-type instance is rejected here before a single
    # value is consumed. The revalidated copies are discarded.
    _strictly_revalidate_detached(policy, AdaptivePolicy)
    _strictly_revalidate_detached(state, AdaptivePolicyStateSnapshot)
    for event in events:
        _strictly_revalidate_detached(event, RuntimeObservationEvent)

    decision_step = state.decision_step
    action_ids = {action.action_id for action in policy.actions}
    if state.current_action_id not in action_ids:
        raise AdaptivePolicyStateMachineError("unknown_current_action")

    if state.action_installed_at_decision_step > decision_step:
        raise AdaptivePolicyStateMachineError("installed_at_step_must_not_exceed_decision_step")
    if state.completed_applications != (decision_step - state.action_installed_at_decision_step):
        raise AdaptivePolicyStateMachineError("completed_applications_inconsistent")
    if state.last_switch_decision_step is not None and (
        state.last_switch_decision_step >= decision_step
    ):
        raise AdaptivePolicyStateMachineError("last_switch_must_be_strictly_before_decision")
    # Initialization is the only non-switch installation (at step 0); every
    # later installation must be an actual switch recorded as the last switch.
    if state.last_switch_decision_step is None:
        if state.action_installed_at_decision_step != 0:
            raise AdaptivePolicyStateMachineError("non_initial_installation_requires_a_switch")
    elif state.last_switch_decision_step != state.action_installed_at_decision_step:
        raise AdaptivePolicyStateMachineError("switch_installation_step_must_equal_last_switch")

    if state.remaining_global_switch_budget > policy.global_switch_budget:
        raise AdaptivePolicyStateMachineError("remaining_global_budget_exceeds_declared_max")

    if len(state.per_rule_remaining_budgets) != len(policy.rules):
        raise AdaptivePolicyStateMachineError("per_rule_remaining_budget_count_mismatch")
    for budget_entry, rule in zip(state.per_rule_remaining_budgets, policy.rules, strict=True):
        rule_id, remaining = budget_entry
        if rule_id != rule.rule_id:
            raise AdaptivePolicyStateMachineError("per_rule_remaining_budget_policy_order_mismatch")
        if remaining > rule.per_rule_switch_budget:
            raise AdaptivePolicyStateMachineError("per_rule_remaining_budget_exceeds_declared_max")


__all__ = [
    "AdaptivePolicyStepResult",
    "RUNTIME_VERSION",
    "advance_adaptive_policy_state",
    "initialize_adaptive_policy_state",
]
