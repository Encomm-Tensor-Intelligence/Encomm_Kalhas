"""Runtime adaptive-policy state, decision and switch evidence (Phase 28, H28-S04).

Phase 28 adds the **runtime adaptive-policy state** surface for the additive
runtime version ``4.0.0``. ADR-004 (D28-01/D28-04) freezes three strict,
frozen, ``extra="forbid"`` nested **non-authoritative** record roles:

- ``AdaptivePolicyStateSnapshot`` -- immutable pre-decision policy state;
- ``AdaptivePolicyDecisionEvent`` -- one decision's ordered causal evidence;
- ``AdaptivePolicySwitchEvent`` -- evidence for exactly one actual action
  switch.

These roles are nested, later-hash-covered members of the future
``AdaptiveRunTrajectoryExecution`` aggregate (ADR-004 D28-04): they carry no
independent identifier or content hash, are therefore deliberately **not**
``VersionedContract`` authorities, are **never** added to ``PUBLIC_CONTRACTS``,
receive **no** standalone schema artifact, and are **not** exported through
``kalhas/contracts/v1``. Nothing in this module evaluates a condition or runs
the policy state machine; those belong to the pure application layer.

The three closed roles only ever record immutable evidence; they never
execute, persist, replay, sample, or query anything, and no field type can
express a callback, expression, provider, or executable mechanism. All fields
are strict: booleans, floats, strings (where an exact ``int`` is required),
``NaN``/``Infinity``, unknown fields, and malformed tuple/budget values fail
closed before any coercion.

Contract-level invariants enforced here are the structural ones reachable from
the record itself. Runtime-policy invariants that need the ``AdaptivePolicy``
authority (canonical per-rule budget order and catalog agreement, evaluation
following stored priority order, a living ineligible *different-action* rule
recording exactly one blocked reason, and a rule-triggered switch's rule-budget
decrement) are verified by the application state machine, never duplicated
here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from kalhas.contracts.v1.adaptive_policy import StrictNonNegativeInt
from kalhas.contracts.v1.world_realization import IdentifierString, Sha256Hex

#: Whether a rule recorded for this decision was evaluated for entry into a
#: different action or for retention of the current action. Both trees are
#: always explicit and never inferred from each other.
ConditionRole = Literal["enter", "retain"]

#: The closed, deterministic single reason an actual action change may block.
EligibilityBlockedReason = Literal[
    "minimum_dwell",
    "cooldown",
    "global_switch_budget",
    "per_rule_switch_budget",
]

#: How a policy step resolved.
DecisionKind = Literal["rule", "fallback", "blocked_fallback"]

#: What triggered an actual action switch.
SwitchTriggerKind = Literal["rule", "fallback"]

#: One ordered rule-evaluation record, deliberately not a helper Pydantic
#: class: ``(rule_id, condition_role, matched, blocked_reason_or_none)``.
#: ``condition_role`` is ``"retain"`` exactly when the rule targets the
#: current action and ``"enter"`` otherwise. ``blocked_reason_or_none`` is
#: ``None`` for a nonmatching rule and for a winning eligible rule, and is the
#: single deterministic reason for an ineligible matched *different-action*
#: rule.
RuleEvaluationRecord = tuple[IdentifierString, ConditionRole, bool, EligibilityBlockedReason | None]


class AdaptivePolicyStateSnapshot(BaseModel):
    """Immutable pre-decision policy state for one policy step.

    Represents the policy state *before* a decision at ``decision_step``: the
    copied runtime/policy identity, the strict non-negative decision step, the
    current action id and the decision step at which that action was installed,
    the strict non-negative count of completed applications of that action, the
    optional decision step of the last switch, the remaining global switch
    budget, and the canonical per-rule remaining budgets as an exact tuple of
    ``(rule_id, remaining_budget)`` pairs in policy rule order.

    Contract invariants: the installed step never exceeds the decision step;
    completed applications equal ``decision_step - action_installed_at_decision_step``;
    a present last-switch step is strictly before this pre-decision step; and
    initialization is the only non-switch installation (no last switch implies
    installation at step 0, and any switch-installed action records that switch
    step as its last switch); and per-rule ``rule_id`` values are unique.
    Bool/float/string/negative/duplicate/malformed budget values fail as
    ``StrictNonNegativeInt``. The
    *policy-relative* budget order and catalog agreement are verified by the
    application state machine against the supplied ``AdaptivePolicy``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: Literal["4.0.0"]
    policy_id: IdentifierString
    policy_content_hash: Sha256Hex
    decision_step: StrictNonNegativeInt
    current_action_id: IdentifierString
    action_installed_at_decision_step: StrictNonNegativeInt
    completed_applications: StrictNonNegativeInt
    last_switch_decision_step: StrictNonNegativeInt | None = None
    remaining_global_switch_budget: StrictNonNegativeInt
    per_rule_remaining_budgets: tuple[tuple[IdentifierString, StrictNonNegativeInt], ...]

    @model_validator(mode="after")
    def _temporal_consistency(self) -> AdaptivePolicyStateSnapshot:
        if self.action_installed_at_decision_step > self.decision_step:
            raise ValueError("action_installed_at_decision_step must not exceed decision_step")
        if self.completed_applications != (
            self.decision_step - self.action_installed_at_decision_step
        ):
            raise ValueError(
                "completed_applications must equal "
                "decision_step - action_installed_at_decision_step"
            )
        if self.last_switch_decision_step is not None and (
            self.last_switch_decision_step >= self.decision_step
        ):
            raise ValueError("last_switch_decision_step must be strictly before decision_step")
        # Initialization is the only non-switch installation and occurs at
        # decision step 0; every later installation must be an actual switch.
        if self.last_switch_decision_step is None:
            if self.action_installed_at_decision_step != 0:
                raise ValueError(
                    "without a last switch, action_installed_at_decision_step "
                    "must be 0 (initialization is the only non-switch installation)"
                )
        elif self.last_switch_decision_step != self.action_installed_at_decision_step:
            raise ValueError(
                "with a last switch, action_installed_at_decision_step must "
                "equal last_switch_decision_step"
            )
        return self

    @model_validator(mode="after")
    def _per_rule_ids_unique(self) -> AdaptivePolicyStateSnapshot:
        rule_ids = [rule_id for rule_id, _ in self.per_rule_remaining_budgets]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("per-rule budget rule_id values must be unique")
        return self


class AdaptivePolicyDecisionEvent(BaseModel):
    """Ordered evidence for exactly one policy step.

    Records the current action before the decision, the ordered
    rule-evaluation evidence, the selected rule id (or ``None`` for fallback),
    the selected action id, the decision kind, whether the action actually
    changed, and the optional fallback blocked reason.

    Contract invariants: evaluation ``rule_id`` values are unique; a
    nonmatching rule carries no blocked reason (and a blocked reason decorates
    only a matched rule); a selected rule must be the last evaluated, matched,
    unblocked rule; ``decision_kind == "rule"`` requires an unselected first
    rule early, ``blocked_fallback`` requires a fallback blocked reason that
    retains the current action, other kinds forbid a fallback blocked reason,
    and ``action_changed`` must equal
    ``selected_action_id != current_action_id``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: Literal["4.0.0"]
    policy_id: IdentifierString
    policy_content_hash: Sha256Hex
    decision_step: StrictNonNegativeInt
    current_action_id: IdentifierString
    rule_evaluation_evidence: tuple[RuleEvaluationRecord, ...]
    selected_rule_id: IdentifierString | None
    selected_action_id: IdentifierString
    decision_kind: DecisionKind
    action_changed: bool
    fallback_blocked_reason: EligibilityBlockedReason | None = None

    @model_validator(mode="after")
    def _ordered_and_unique_evaluation(self) -> AdaptivePolicyDecisionEvent:
        rule_ids = [record[0] for record in self.rule_evaluation_evidence]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule evaluation evidence must carry unique rule ids")
        for record in self.rule_evaluation_evidence:
            _rule_id, _role, matched, blocked = record
            if blocked is not None and not matched:
                raise ValueError("a blocked reason requires a matched rule")
        return self

    @model_validator(mode="after")
    def _selection_and_kind(self) -> AdaptivePolicyDecisionEvent:
        if self.decision_kind == "rule":
            if self.selected_rule_id is None:
                raise ValueError("decision_kind 'rule' requires a selected rule")
            if not self.rule_evaluation_evidence:
                raise ValueError("a selected rule requires non-empty evaluation evidence")
            last = self.rule_evaluation_evidence[-1]
            if (last[0] != self.selected_rule_id) or (not last[2]) or (last[3] is not None):
                raise ValueError(
                    "the selected rule must be the last evaluated, matched, unblocked rule"
                )
        else:
            if self.selected_rule_id is not None:
                raise ValueError("fallback decision kinds forbid a selected rule")
        return self

    @model_validator(mode="after")
    def _blocked_and_changed(self) -> AdaptivePolicyDecisionEvent:
        if self.decision_kind == "blocked_fallback":
            if self.fallback_blocked_reason is None:
                raise ValueError("blocked_fallback requires a fallback blocked reason")
            if self.selected_action_id != self.current_action_id:
                raise ValueError("blocked_fallback must retain the current action")
        elif self.fallback_blocked_reason is not None:
            raise ValueError("this decision kind forbids a fallback blocked reason")
        if self.action_changed != (self.selected_action_id != self.current_action_id):
            raise ValueError("action_changed must equal selected_action_id != current_action_id")
        return self


class AdaptivePolicySwitchEvent(BaseModel):
    """Evidence for exactly one actual action switch.

    Emitted only when the action actually changed: the copied runtime/policy
    identity, the decision step, the old and new action ids, the trigger kind,
    the optional triggering rule id, the global switch budget before/after, and
    the rule switch budget before/after (rule switches only).

    Contract invariants: the old and new action ids differ; the global budget
    decrements by exactly one; rule-triggered switches require a rule id and a
    rule-budget decrement of exactly one; fallback switches forbid the rule id
    and rule-budget fields. No switch evidence exists for initialization or
    same-action selection.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: Literal["4.0.0"]
    policy_id: IdentifierString
    policy_content_hash: Sha256Hex
    decision_step: StrictNonNegativeInt
    old_action_id: IdentifierString
    new_action_id: IdentifierString
    trigger_kind: SwitchTriggerKind
    triggering_rule_id: IdentifierString | None = None
    global_switch_budget_before: StrictNonNegativeInt
    global_switch_budget_after: StrictNonNegativeInt
    rule_switch_budget_before: StrictNonNegativeInt | None = None
    rule_switch_budget_after: StrictNonNegativeInt | None = None

    @model_validator(mode="after")
    def _switch_semantics(self) -> AdaptivePolicySwitchEvent:
        if self.old_action_id == self.new_action_id:
            raise ValueError("the old and new action ids must differ")
        if self.global_switch_budget_after != self.global_switch_budget_before - 1:
            raise ValueError("the global switch budget must decrement by exactly one")
        if self.trigger_kind == "rule":
            if self.triggering_rule_id is None:
                raise ValueError("a rule switch requires a triggering rule id")
            if self.rule_switch_budget_before is None or self.rule_switch_budget_after is None:
                raise ValueError("a rule switch requires the triggering-rule budgets")
            if self.rule_switch_budget_after != self.rule_switch_budget_before - 1:
                raise ValueError("the rule switch budget must decrement by exactly one")
        else:
            if self.triggering_rule_id is not None:
                raise ValueError("a fallback switch forbids a triggering rule id")
            if (
                self.rule_switch_budget_before is not None
                or self.rule_switch_budget_after is not None
            ):
                raise ValueError("a fallback switch forbids rule-switch budget fields")
        return self


__all__ = [
    "AdaptivePolicyDecisionEvent",
    "AdaptivePolicyStateSnapshot",
    "AdaptivePolicySwitchEvent",
    "ConditionRole",
    "DecisionKind",
    "EligibilityBlockedReason",
    "RuleEvaluationRecord",
    "SwitchTriggerKind",
]
