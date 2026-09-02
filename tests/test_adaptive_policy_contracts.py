"""Phase 28 closed adaptive-policy contract tests (H28-S02).

Covers the untrusted ``AdaptivePolicyDraft``, the immutable bound
``AdaptivePolicy`` (public contract index 52), and the nested condition/
action/rule models: JSON round trips, frozen/strict rejection, the
closed operator/node-kind catalogs, exact numeric threshold adversaries,
integer/number threshold agreement, compound fan-out bounds, maximum
depth and node-count bounds, canonical child ordering, duplicate
condition identifiers, catalog ordering/uniqueness for actions,
trajectory bindings, and observation bindings, complete exact
observation-catalog coverage with unused-binding rejection, action
reference membership, rule canonical order/uniqueness/maximum, mandatory
distinct explicit enter/retain fields, strict non-negative dwell/
cooldown/budgets, initial/fallback membership, draft trust-boundary
exclusions, absence of any runtime-state surface on the bound policy,
the immutable 52-contract prefix plus the exact index-52 append and the
additive-safe registry/schema state (the exact current cardinality is
owned by the Phase 28 registry-compatibility suite), schema equality
without nested schema artifacts, and byte-identity of all pre-existing
schema files.
"""

from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_policy import (
    MAX_ACTION_COUNT,
    MAX_COMPOUND_FAN_OUT,
    MAX_CONDITION_DEPTH,
    MAX_CONDITION_NODES,
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRule,
    AdaptivePolicyRuleDraft,
    BoundAdaptiveAction,
    ConditionAllNode,
    ConditionAnyNode,
    ConditionComparisonLeaf,
    ObservationBinding,
    TrajectoryPlanBinding,
)
from pydantic import BaseModel, ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
KALHAS_ROOT = REPO_ROOT / "kalhas"

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: Nested/helper models that must never be registered or exported.
_NESTED_MODELS = (
    "AdaptivePolicyDraft",
    "AdaptivePolicyRule",
    "AdaptivePolicyRuleDraft",
    "BoundAdaptiveAction",
    "ConditionAllNode",
    "ConditionAnyNode",
    "ConditionComparisonLeaf",
    "ObservationBinding",
    "TrajectoryPlanBinding",
)

#: Draft trust-boundary exclusion tokens: no such field may exist on the draft.
_DRAFT_FORBIDDEN_FIELDS = (
    "identifier",
    "tenant_id",
    "schema_version",
    "runtime_version",
    "campaign_id",
    "scenario_id",
    "world_version_id",
    "world_content_hash",
    "policy_id",
    "policy_version",
    "content_hash",
    "bound_at",
    "declared_at",
    "created_at",
    "metadata",
    "hash",
    "manifest_id",
    "state_model_id",
    "state_model_identifier",
    "state_model_content_hash",
    "trajectory_plan_id",
    "strategy_candidate_id",
    "strategy_content_hash",
    "observation_binding",
    "provider",
    "network",
    "callback",
    "executable",
    "expression",
)

_ID_COUNTER = {"value": 0}


def _nid() -> str:
    """A fresh condition identifier; allocation order keeps children sorted."""
    _ID_COUNTER["value"] += 1
    return f"c-{_ID_COUNTER['value']:04d}"


def _leaf(condition_id: str = "c-1", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "comparison",
        "condition_id": condition_id,
        "observation_id": "obs-1",
        "observed_value_kind": "integer",
        "unit": None,
        "operator": "gte",
        "threshold": 5,
        "missing_behavior": "false",
    }
    payload.update(overrides)
    return payload


def _auto_leaf(**overrides: object) -> dict[str, object]:
    return _leaf(_nid(), **overrides)


def _all_node(condition_id: str, children: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": "all", "condition_id": condition_id, "children": children}


def _assert_fixture_compounds_canonical(node: object, unique_direct_siblings: bool = True) -> None:
    """Fixture audit: every compound node's direct children are canonical.

    Proves an adversarial duplicate fixture is rejected by the
    global-uniqueness validator rather than by child ordering. Raises
    ``AssertionError`` before validation if the fixture itself is
    mis-ordered. ``unique_direct_siblings=False`` permits an intentional
    direct-sibling duplication (the direct-child uniqueness adversary).
    """
    if not isinstance(node, dict):
        return
    children = node.get("children")
    if isinstance(children, list):
        ids = [child["condition_id"] for child in children]
        assert ids == sorted(ids), f"fixture compound {node['condition_id']} mis-ordered"
        if unique_direct_siblings:
            assert len(set(ids)) == len(ids), (
                f"fixture compound {node['condition_id']} has duplicate direct siblings"
            )
        for child in children:
            _assert_fixture_compounds_canonical(child)


def _any_node(condition_id: str, children: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": "any", "condition_id": condition_id, "children": children}


def _auto_compound(kind: str, children: list[dict[str, object]]) -> dict[str, object]:
    return {"kind": kind, "condition_id": _nid(), "children": children}


def _validate(payload_fn: Callable[..., dict[str, object]], **overrides: object) -> Any:
    """Build a payload through a helper and validate it with the right model."""
    built = payload_fn(**overrides)
    model: type[BaseModel] = (
        AdaptivePolicy if payload_fn is _policy_payload else AdaptivePolicyDraft
    )
    return model.model_validate(built)


def _enter_tree(unit: str | None = None, missing: str = "false") -> dict[str, object]:
    """A two-leaf ``all`` tree over observation ``obs-1`` (ids c-e*)."""
    return _all_node(
        "c-enter",
        [
            _leaf("c-e1", operator="gte", threshold=5, unit=unit, missing_behavior=missing),
            _leaf("c-e2", operator="lt", threshold=100, unit=unit, missing_behavior=missing),
        ],
    )


def _retain_tree(unit: str | None = None, missing: str = "false") -> dict[str, object]:
    """A two-leaf ``all`` tree over observation ``obs-1`` (ids c-r*)."""
    return _all_node(
        "c-retain",
        [
            _leaf("c-r1", operator="gte", threshold=4, unit=unit, missing_behavior=missing),
            _leaf("c-r2", operator="lt", threshold=90, unit=unit, missing_behavior=missing),
        ],
    )


def _rule_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule_id": "rule-1",
        "priority": 0,
        "target_action_id": "act-b",
        "enter_condition": _enter_tree(),
        "retain_condition": _retain_tree(),
        "per_rule_switch_budget": 3,
    }
    payload.update(overrides)
    return payload


def _draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": "draft-request-1",
        "actions": ["act-a", "act-b"],
        "initial_action_id": "act-a",
        "fallback_action_id": "act-b",
        "rules": [_rule_payload()],
        "minimum_dwell_steps": 2,
        "cooldown_steps": 1,
        "global_switch_budget": 10,
    }
    payload.update(overrides)
    return payload


def _binding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "observation_id": "obs-1",
        "runtime_observation_declaration_id": "runtime-observation-1",
        "runtime_observation_declaration_content_hash": H64,
        "observed_value_kind": "integer",
        "unit": None,
        "missing_behavior": "false",
    }
    payload.update(overrides)
    return payload


def _plan_binding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": H64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _action_payload(action_id: str = "act-a", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action_id": action_id,
        "strategy_candidate_id": "sc-1",
        "strategy_content_hash": H64,
        "trajectory_plan_bindings": [_plan_binding_payload()],
    }
    payload.update(overrides)
    return payload


def _policy_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "adaptive-policy-bound-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "runtime_version": "4.0.0",
        "policy_id": "policy-1",
        "policy_version": "1.0.0",
        "observation_bindings": [_binding_payload()],
        "actions": [_action_payload("act-a"), _action_payload("act-b")],
        "initial_action_id": "act-a",
        "fallback_action_id": "act-b",
        "rules": [_rule_payload()],
        "minimum_dwell_steps": 2,
        "cooldown_steps": 1,
        "global_switch_budget": 10,
        "content_hash": H64,
        "bound_at": NOW,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _max_nodes(depth_budget: int) -> int:
    """Largest node count of a valid tree with depth at most ``depth_budget``."""
    if depth_budget == 1:
        return 1
    return 1 + MAX_COMPOUND_FAN_OUT * _max_nodes(depth_budget - 1)


def _build_tree(size: int, depth_budget: int) -> dict[str, object]:
    """A canonically ordered ``all``-chain tree holding exactly ``size`` nodes."""
    if size == 1:
        return _auto_leaf()
    if depth_budget < 2 or size < 3:
        raise AssertionError(f"infeasible tree request: size={size} budget={depth_budget}")
    child_cap = _max_nodes(depth_budget - 1)
    children: list[dict[str, object]] = []
    remaining = size - 1
    while remaining:
        slots_left = MAX_COMPOUND_FAN_OUT - len(children) - 1
        take = min(child_cap, remaining)
        if len(children) == 0:
            take = min(take, remaining - 1)  # reserve at least one sibling
        if take < 1 or remaining - take > slots_left * child_cap:
            raise AssertionError(f"infeasible split: size={size} budget={depth_budget}")
        children.append(_build_tree(take, depth_budget - 1))
        remaining -= take
    if not 2 <= len(children) <= MAX_COMPOUND_FAN_OUT:
        raise AssertionError(f"bad fan-out {len(children)}")
    return _auto_compound("all", children)


class TestAdaptivePolicyDraftRoundTripAndStrictness:
    def test_valid_draft_round_trip(self) -> None:
        draft = AdaptivePolicyDraft.model_validate(_draft_payload())
        assert draft.actions == ("act-a", "act-b")
        assert draft.rules[0].target_action_id == "act-b"
        dumped = draft.model_dump_json()
        reloaded = AdaptivePolicyDraft.model_validate_json(dumped)
        assert reloaded == draft

    def test_draft_is_frozen(self) -> None:
        draft = AdaptivePolicyDraft.model_validate(_draft_payload())
        with pytest.raises(ValidationError):
            draft.request_id = "tampered"

    def test_draft_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyDraft.model_validate(_draft_payload(unexpected_field=1))

    def test_empty_rules_are_expressible_but_actions_are_not(self) -> None:
        draft = _validate(_draft_payload, rules=[])
        assert draft.rules == ()
        with pytest.raises(ValidationError):
            _validate(_draft_payload, actions=[])


class TestClosedOperatorCatalog:
    @pytest.mark.parametrize("operator", ["lt", "lte", "eq", "gte", "gt"])
    def test_exact_operator_catalog_accepts_only_five_operators(self, operator: str) -> None:
        leaf = ConditionComparisonLeaf.model_validate(_leaf(operator=operator))
        assert leaf.operator == operator

    @pytest.mark.parametrize(
        "bad_operator",
        ["ne", "not", "nand", "~", "<=", "===", "GTE", "between", "approx", ""],
    )
    def test_rejects_every_non_catalog_operator(self, bad_operator: str) -> None:
        with pytest.raises(ValidationError):
            ConditionComparisonLeaf.model_validate(_leaf(operator=bad_operator))

    def test_no_negation_or_tolerance_surface_exists_on_leaves(self) -> None:
        forbidden_fields = {
            "negate",
            "tolerance",
            "epsilon",
            "abs_tol",
            "rel_tol",
            "clip",
            "clamp",
            "coerce",
            "expression",
            "formula",
            "callback",
        }
        assert not forbidden_fields & set(ConditionComparisonLeaf.model_fields)
        assert set(ConditionComparisonLeaf.model_fields) == {
            "kind",
            "condition_id",
            "observation_id",
            "observed_value_kind",
            "unit",
            "operator",
            "threshold",
            "missing_behavior",
        }


class TestExactNumericThresholds:
    @pytest.mark.parametrize("threshold", [0, -7, 2**63, 10**30])
    def test_integer_kind_requires_exact_int_threshold(self, threshold: int) -> None:
        leaf = ConditionComparisonLeaf.model_validate(
            _leaf(observed_value_kind="integer", threshold=threshold)
        )
        assert isinstance(leaf.threshold, int)

    @pytest.mark.parametrize("bad_threshold", [5.0, 5.5, True, False, "5", None])
    def test_integer_kind_rejects_everything_else(self, bad_threshold: Any) -> None:
        with pytest.raises(ValidationError):
            ConditionComparisonLeaf.model_validate(
                _leaf(observed_value_kind="integer", threshold=bad_threshold)
            )

    @pytest.mark.parametrize("threshold", [1.5, -0.25, 2**63, float(10), 7])
    def test_number_kind_accepts_exact_finite_int_or_float(self, threshold: Any) -> None:
        leaf = ConditionComparisonLeaf.model_validate(
            _leaf(observed_value_kind="number", threshold=threshold)
        )
        assert not isinstance(leaf.threshold, bool)

    @pytest.mark.parametrize(
        "bad_threshold",
        [True, False, "1.5", None, [1], {"v": 1}, float("nan"), float("inf"), float("-inf")],
    )
    def test_number_kind_rejects_adversaries_including_nan_infinity(
        self, bad_threshold: Any
    ) -> None:
        with pytest.raises(ValidationError):
            ConditionComparisonLeaf.model_validate(
                _leaf(observed_value_kind="number", threshold=bad_threshold)
            )

    def test_equality_stays_exact_across_kinds(self) -> None:
        integer_leaf = ConditionComparisonLeaf.model_validate(
            _leaf(observed_value_kind="integer", operator="eq", threshold=1)
        )
        number_leaf = ConditionComparisonLeaf.model_validate(
            _leaf(observed_value_kind="number", operator="eq", threshold=1.0)
        )
        assert isinstance(integer_leaf.threshold, int)
        assert isinstance(number_leaf.threshold, float)
        # Canonical JSON keeps integer 1 and float 1.0 distinct across kinds.
        integer_text = json.dumps(integer_leaf.model_dump(mode="json")["threshold"])
        number_text = json.dumps(number_leaf.model_dump(mode="json")["threshold"])
        assert integer_text == "1"
        assert number_text == "1.0"

    def test_missing_behavior_is_closed_and_explicit(self) -> None:
        assert (
            ConditionComparisonLeaf.model_validate(_leaf(missing_behavior="error")).missing_behavior
            == "error"
        )
        for bad in ("none", "default", "skip", True, "", "FALSE"):
            with pytest.raises(ValidationError):
                ConditionComparisonLeaf.model_validate(_leaf(missing_behavior=bad))

    def test_condition_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            ConditionComparisonLeaf.model_validate(_leaf(condition_id=""))


class TestCompoundNodesAndFanOut:
    def test_minimal_compound_with_two_children_is_accepted(self) -> None:
        node = ConditionAllNode.model_validate(_all_node("c-r", [_leaf("c-1"), _leaf("c-2")]))
        assert len(node.children) == 2

    def test_maximal_flat_compound_with_eight_children_is_accepted(self) -> None:
        children = [_leaf(f"c-{index}") for index in range(MAX_COMPOUND_FAN_OUT)]
        node = ConditionAnyNode.model_validate(_any_node("c-r", children))
        assert len(node.children) == MAX_COMPOUND_FAN_OUT

    def test_single_child_compound_fan_out_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConditionAllNode.model_validate(_all_node("c-r", [_leaf("c-1")]))

    def test_nine_child_compound_fan_out_nine_is_rejected(self) -> None:
        children = [_leaf(f"c-{index}") for index in range(MAX_COMPOUND_FAN_OUT + 1)]
        with pytest.raises(ValidationError):
            ConditionAnyNode.model_validate(_any_node("c-r", children))

    def test_zero_child_compound_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConditionAllNode.model_validate(_all_node("c-r", []))

    def test_unknown_node_kind_fails_through_the_discriminated_union(self) -> None:
        rogue: dict[str, object] = {"kind": "not", "condition_id": "c-x", "child": _leaf("c-1")}
        with pytest.raises(ValidationError):
            _validate(_draft_payload, rules=[_rule_payload(enter_condition=rogue)])
        xor: dict[str, object] = {
            "kind": "xor",
            "condition_id": "c-9",
            "children": [_leaf("c-2"), _leaf("c-3")],
        }
        with pytest.raises(ValidationError):
            ConditionAllNode.model_validate(_all_node("c-r", [_leaf("c-1"), xor]))

    def test_nested_all_any_mixing_is_accepted(self) -> None:
        tree = _all_node(
            "c-root",
            [_any_node("c-mid", [_leaf("c-m1"), _leaf("c-m2")]), _leaf("c-tail")],
        )
        rule = _rule_payload(enter_condition=tree, retain_condition=_retain_tree())
        draft = AdaptivePolicyDraft.model_validate(_draft_payload(rules=[rule]))
        enter = draft.rules[0].enter_condition
        assert isinstance(enter, ConditionAllNode)
        assert isinstance(enter.children[0], ConditionAnyNode)


class TestDepthNodeCountAndCanonicalOrdering:
    def test_maximum_depth_four_is_accepted(self) -> None:
        tree: dict[str, object] = _build_tree(7, MAX_CONDITION_DEPTH)
        rule = _rule_payload(enter_condition=tree, retain_condition=_retain_tree())
        draft = AdaptivePolicyDraft.model_validate(_draft_payload(rules=[rule]))
        assert draft.rules[0].enter_condition.condition_id.startswith("c-")

    def test_depth_five_is_rejected(self) -> None:
        too_deep: dict[str, object] = _build_tree(9, MAX_CONDITION_DEPTH + 1)
        with pytest.raises(ValidationError, match="depth"):
            AdaptivePolicyRuleDraft.model_validate(
                _rule_payload(enter_condition=too_deep, retain_condition=_retain_tree())
            )

    def test_sixty_four_nodes_within_depth_four_is_accepted(self) -> None:
        tree: dict[str, object] = _build_tree(MAX_CONDITION_NODES, MAX_CONDITION_DEPTH)
        rule = AdaptivePolicyRuleDraft.model_validate(
            _rule_payload(enter_condition=tree, retain_condition=_auto_leaf())
        )
        assert rule.enter_condition.condition_id.startswith("c-")

    def test_sixty_five_nodes_is_rejected(self) -> None:
        oversized: dict[str, object] = _build_tree(MAX_CONDITION_NODES + 1, MAX_CONDITION_DEPTH)
        with pytest.raises(ValidationError, match="64"):
            AdaptivePolicyRuleDraft.model_validate(
                _rule_payload(enter_condition=oversized, retain_condition=_auto_leaf())
            )

    def test_direct_children_canonically_ordered_by_condition_id(self) -> None:
        ordered = _all_node("c-r", [_leaf("c-a"), _leaf("c-b")])
        reordered = _all_node("c-r", [_leaf("c-b"), _leaf("c-a")])
        ConditionAllNode.model_validate(ordered)
        with pytest.raises(ValidationError, match="canonically ordered"):
            ConditionAllNode.model_validate(reordered)

    def test_reordered_children_deep_inside_a_rule_are_rejected(self) -> None:
        deep = _all_node(
            "c-root",
            [_any_node("c-mid", [_leaf("c-z"), _leaf("c-a")]), _leaf("c-tail")],
        )
        with pytest.raises(ValidationError, match="canonically ordered"):
            AdaptivePolicyRuleDraft.model_validate(
                _rule_payload(enter_condition=deep, retain_condition=_retain_tree())
            )

    @pytest.mark.parametrize(
        ("placement", "expected_error", "unique_direct_siblings"),
        [
            ("direct_siblings", "duplicate condition_id among direct compound children", False),
            (
                "cross_branch",
                "condition identifiers must be globally unique within one tree",
                True,
            ),
        ],
        ids=["direct-siblings", "cross-branch"],
    )
    @pytest.mark.parametrize("rule_model", [AdaptivePolicyRuleDraft, AdaptivePolicyRule])
    def test_duplicate_condition_identifiers_fail_everywhere(
        self,
        placement: str,
        expected_error: str,
        unique_direct_siblings: bool,
        rule_model: type[BaseModel],
    ) -> None:
        if placement == "direct_siblings":
            tree = _all_node("c-r", [_leaf("c-dup"), _leaf("c-dup")])
            _assert_fixture_compounds_canonical(tree, unique_direct_siblings=unique_direct_siblings)
        else:
            # Canonical at every compound node and unique within every direct
            # sibling set; "c-shared" is duplicated only across two separate
            # sibling branches, so neither ordering nor direct-child checks
            # can be the rejection cause.
            tree = _all_node(
                "a-root",
                [
                    _all_node("a-branch", [_leaf("c-shared"), _leaf("d-unique-a")]),
                    _all_node("b-branch", [_leaf("c-shared"), _leaf("d-unique-b")]),
                ],
            )
            _assert_fixture_compounds_canonical(tree)
        with pytest.raises(ValidationError, match=expected_error):
            rule_model.model_validate(
                _rule_payload(enter_condition=tree, retain_condition=_retain_tree())
            )

    @pytest.mark.parametrize("rule_model", [AdaptivePolicyRuleDraft, AdaptivePolicyRule])
    def test_root_identifier_duplicated_at_deep_descendant_is_rejected(
        self, rule_model: type[BaseModel]
    ) -> None:
        """A fully canonical tree whose only defect is root/deep reuse."""
        tree = _all_node(
            "c-root",
            [
                _leaf("c-aaa"),
                _any_node("c-zzz", [_leaf("c-kkk"), _leaf("c-root")]),
            ],
        )
        _assert_fixture_compounds_canonical(tree)
        with pytest.raises(
            ValidationError,
            match="condition identifiers must be globally unique within one tree",
        ):
            rule_model.model_validate(
                _rule_payload(enter_condition=tree, retain_condition=_retain_tree())
            )

    def test_canonical_globally_unique_multi_branch_tree_is_accepted(self) -> None:
        tree = _all_node(
            "c-root",
            [
                _leaf("c-aaa"),
                _any_node("c-zzz", [_leaf("c-kkk"), _leaf("c-mmm")]),
            ],
        )
        _assert_fixture_compounds_canonical(tree)
        for model in (AdaptivePolicyRuleDraft, AdaptivePolicyRule):
            rule = model.model_validate(
                _rule_payload(enter_condition=tree, retain_condition=_retain_tree())
            )
            assert rule.enter_condition.condition_id == "c-root"

    def test_duplicate_ids_across_enter_and_retain_are_allowed(self) -> None:
        """Uniqueness holds per tree; enter and retain are separate trees."""
        shared = _all_node("c-shared", [_leaf("c-1"), _leaf("c-2")])
        rule = _rule_payload(enter_condition=shared, retain_condition=shared)
        draft = AdaptivePolicyDraft.model_validate(_draft_payload(rules=[rule]))
        assert draft.rules[0].enter_condition == draft.rules[0].retain_condition


class TestActionCatalogRules:
    def test_draft_actions_canonical_order_uniqueness_and_bounds(self) -> None:
        with pytest.raises(ValidationError, match="canonically ordered"):
            _validate(_draft_payload, actions=["act-b", "act-a"], fallback_action_id="act-b")
        with pytest.raises(ValidationError, match="unique"):
            _validate(_draft_payload, actions=["act-a", "act-a"], fallback_action_id="act-a")
        maxed = [f"act-{index:03d}" for index in range(MAX_ACTION_COUNT)]
        draft = _validate(
            _draft_payload,
            actions=maxed,
            initial_action_id="act-000",
            fallback_action_id="act-063",
            rules=[],
        )
        assert len(draft.actions) == MAX_ACTION_COUNT
        with pytest.raises(ValidationError):
            _validate(
                _draft_payload,
                actions=[*maxed, "act-zzz"],
                initial_action_id="act-000",
                fallback_action_id="act-zzz",
                rules=[],
            )

    def test_bound_actions_canonical_order_and_uniqueness(self) -> None:
        with pytest.raises(ValidationError, match="canonically ordered"):
            _validate(
                _policy_payload,
                actions=[_action_payload("act-b"), _action_payload("act-a")],
                initial_action_id="act-b",
            )
        with pytest.raises(ValidationError, match="unique"):
            _validate(_policy_payload, actions=[_action_payload("act-a"), _action_payload("act-a")])
        assert BoundAdaptiveAction.model_validate(_action_payload()).action_id == "act-a"

    def test_trajectory_bindings_canonical_ordering_and_uniqueness(self) -> None:
        first = _plan_binding_payload(trajectory_plan_id="plan-1", state_model_identifier="sm-a")
        second = _plan_binding_payload(trajectory_plan_id="plan-2", state_model_identifier="sm-b")
        action = BoundAdaptiveAction.model_validate(
            _action_payload(trajectory_plan_bindings=[first, second])
        )
        assert len(action.trajectory_plan_bindings) == 2
        with pytest.raises(ValidationError, match="canonically ordered"):
            BoundAdaptiveAction.model_validate(
                _action_payload(trajectory_plan_bindings=[second, first])
            )
        same_state_model = _plan_binding_payload(
            trajectory_plan_id="plan-2", state_model_identifier="sm-a"
        )
        with pytest.raises(ValidationError, match="one trajectory-plan binding per"):
            BoundAdaptiveAction.model_validate(
                _action_payload(trajectory_plan_bindings=[first, same_state_model])
            )
        repeated_plan = _plan_binding_payload(
            trajectory_plan_id="plan-1", state_model_identifier="sm-b"
        )
        with pytest.raises(ValidationError, match="unique"):
            BoundAdaptiveAction.model_validate(
                _action_payload(trajectory_plan_bindings=[first, repeated_plan])
            )
        with pytest.raises(ValidationError):
            BoundAdaptiveAction.model_validate(_action_payload(trajectory_plan_bindings=[]))


class TestObservationBindingCatalog:
    def _two_binding_policy_kwargs(self) -> dict[str, object]:
        second = _binding_payload(
            observation_id="obs-2", runtime_observation_declaration_id="decl-2"
        )
        rules = [
            _rule_payload(
                rule_id="r-1",
                priority=0,
                target_action_id="act-b",
                enter_condition=_all_node(
                    "c-en",
                    [
                        _leaf("c-e1"),
                        _leaf("c-e2", observation_id="obs-2"),
                    ],
                ),
                retain_condition=_all_node(
                    "c-rt",
                    [
                        _leaf("c-g1", observation_id="obs-2"),
                        _leaf("c-g2"),
                    ],
                ),
            ),
            _rule_payload(
                rule_id="r-2",
                priority=1,
                target_action_id="act-a",
                enter_condition=_all_node(
                    "c-en2",
                    [
                        _leaf("c-f1", observation_id="obs-2"),
                        _leaf("c-f2"),
                    ],
                ),
                retain_condition=_all_node(
                    "c-rt2",
                    [
                        _leaf("c-h1", observation_id="obs-2"),
                        _leaf("c-h2"),
                    ],
                ),
            ),
        ]
        return {"observation_bindings": [_binding_payload(), second], "rules": rules}

    def test_catalog_canonical_ordering_with_unique_ids(self) -> None:
        policy = _validate(_policy_payload, **self._two_binding_policy_kwargs())
        assert len(policy.observation_bindings) == 2
        reordered_kwargs = self._two_binding_policy_kwargs()
        bindings = cast_any(reordered_kwargs["observation_bindings"])
        reordered_kwargs["observation_bindings"] = [bindings[1], bindings[0]]
        with pytest.raises(ValidationError, match="canonically ordered"):
            _validate(_policy_payload, **reordered_kwargs)

    def test_duplicate_observation_ids_are_rejected(self) -> None:
        duplicate = _binding_payload(runtime_observation_declaration_id="decl-2")
        with pytest.raises(ValidationError, match="unique"):
            _validate(
                _policy_payload,
                observation_bindings=[_binding_payload(), duplicate],
                rules=[],
            )

    def test_duplicate_declaration_identifiers_are_rejected(self) -> None:
        other = _binding_payload(observation_id="obs-2")
        with pytest.raises(ValidationError, match="unique"):
            _validate(_policy_payload, observation_bindings=[_binding_payload(), other], rules=[])

    def test_empty_observation_catalog_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _validate(_policy_payload, observation_bindings=[], rules=[])


def cast_any(value: object) -> Any:
    return value


class TestObservationCoverageCompleteness:
    def test_leaf_referencing_unknown_observation_id_is_rejected(self) -> None:
        rule = _rule_payload(enter_condition=_leaf("c-unknown", observation_id="obs-none"))
        with pytest.raises(ValidationError, match="unknown observation_id"):
            _validate(_policy_payload, rules=[rule])

    def test_leaf_value_kind_must_match_the_binding(self) -> None:
        mismatched = _leaf("c-kind", observed_value_kind="number", threshold=5.0)
        with pytest.raises(ValidationError, match="value kind disagrees"):
            _validate(_policy_payload, rules=[_rule_payload(enter_condition=mismatched)])

    def test_leaf_unit_must_match_the_binding_both_directions(self) -> None:
        mismatched = _leaf("c-unit", unit="celsius")
        with pytest.raises(ValidationError, match="unit disagrees"):
            _validate(_policy_payload, rules=[_rule_payload(enter_condition=mismatched)])
        celsius_binding = _binding_payload(unit="celsius")
        matching_rule = _rule_payload(
            enter_condition=_enter_tree(unit="celsius"),
            retain_condition=_retain_tree(unit="celsius"),
        )
        policy = _validate(
            _policy_payload,
            observation_bindings=[celsius_binding],
            rules=[matching_rule],
        )
        assert len(policy.observation_bindings) == 1

    def test_leaf_missing_behavior_must_match_the_binding(self) -> None:
        mismatched = _leaf("c-miss", missing_behavior="error")
        with pytest.raises(ValidationError, match="missing behavior disagrees"):
            _validate(_policy_payload, rules=[_rule_payload(enter_condition=mismatched)])

    def test_unused_observation_bindings_are_rejected_until_fully_covered(self) -> None:
        used = _binding_payload()
        unused = _binding_payload(
            observation_id="obs-unused",
            runtime_observation_declaration_id="runtime-observation-unused",
        )
        with pytest.raises(ValidationError, match="unused"):
            _validate(_policy_payload, observation_bindings=[used, unused], rules=[])
        only_unused = _all_node(
            "c-pe",
            [
                _leaf("c-pe1", observation_id="obs-unused"),
                _leaf("c-pe2", observation_id="obs-unused"),
            ],
        )
        with pytest.raises(ValidationError, match="unused"):
            _validate(
                _policy_payload,
                observation_bindings=[used, unused],
                rules=[
                    _rule_payload(
                        rule_id="r-part",
                        priority=0,
                        target_action_id="act-b",
                        enter_condition=only_unused,
                        retain_condition=_all_node(
                            "c-pt",
                            [
                                _leaf("c-pt1", observation_id="obs-unused"),
                                _leaf("c-pt2", observation_id="obs-unused"),
                            ],
                        ),
                    )
                ],
            )
        fully_used = _validate(
            _policy_payload,
            observation_bindings=[used, unused],
            rules=[
                _rule_payload(
                    rule_id="r-full",
                    priority=0,
                    target_action_id="act-b",
                    enter_condition=_all_node(
                        "c-fe",
                        [
                            _leaf("c-fe1", observation_id="obs-unused"),
                            _leaf("c-fe2"),
                        ],
                    ),
                    retain_condition=_all_node(
                        "c-pr",
                        [
                            _leaf("c-pr1", observation_id="obs-unused"),
                            _leaf("c-pr2"),
                        ],
                    ),
                )
            ],
        )
        assert len(fully_used.observation_bindings) == 2


class TestActionReferenceMembership:
    def test_rule_targeting_unknown_action_is_rejected(self) -> None:
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError, match="target_action_id must exist in the"):
                _validate(payload, rules=[_rule_payload(target_action_id="act-none")])

    def test_initial_and_fallback_membership_both_models(self) -> None:
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError, match="initial_action_id must exist"):
                _validate(payload, initial_action_id="act-none")
            with pytest.raises(ValidationError, match="fallback_action_id must exist"):
                _validate(payload, fallback_action_id="act-none")

    def test_empty_bound_action_catalog_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _validate(_policy_payload, actions=[], initial_action_id="", fallback_action_id="")


class TestRuleContracts:
    def test_rules_canonical_priority_order_unique_priorities_unique_ids(self) -> None:
        low = _rule_payload(rule_id="r-low", priority=0)
        high = _rule_payload(
            rule_id="r-high",
            priority=1,
            enter_condition=_retain_tree(),
            retain_condition=_enter_tree(),
        )
        accepted = _validate(_draft_payload, rules=[low, high])
        assert accepted.rules[0].priority == 0
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError, match="ascending by priority"):
                _validate(payload, rules=[high, low])
            with pytest.raises(ValidationError, match="priorities must be unique"):
                _validate(payload, rules=[low, dict(low, rule_id="r-other")])

    def test_duplicate_rule_identifiers_are_rejected(self) -> None:
        twin_a = _rule_payload(rule_id="r-twin", priority=0)
        twin_b = _rule_payload(
            rule_id="r-twin",
            priority=1,
            enter_condition=_retain_tree(),
            retain_condition=_enter_tree(),
        )
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError, match="identifiers must be unique"):
                _validate(payload, rules=[twin_a, twin_b])

    def test_maximum_sixty_four_rules_accepted_and_sixty_five_rejected(self) -> None:
        def rule_at(index: int) -> dict[str, object]:
            flip = index % 2 == 0
            return _rule_payload(
                rule_id=f"r-{index:03d}",
                priority=index,
                enter_condition=_enter_tree() if flip else _retain_tree(),
                retain_condition=_retain_tree() if flip else _enter_tree(),
            )

        full = [rule_at(index) for index in range(64)]
        accepted = _validate(_draft_payload, rules=full)
        assert len(accepted.rules) == 64
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError):
                _validate(payload, rules=[*full, rule_at(64)])

    def test_negative_or_fractional_strict_fields_on_rules_are_rejected(self) -> None:
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError):
                _validate(payload, rules=[_rule_payload(priority=-1)])
            with pytest.raises(ValidationError):
                _validate(payload, rules=[_rule_payload(priority=1.5)])
            with pytest.raises(ValidationError):
                _validate(payload, rules=[_rule_payload(per_rule_switch_budget=-1)])

    def test_bound_rule_type_is_separate_from_draft_rule(self) -> None:
        assert AdaptivePolicyRule.model_validate(_rule_payload()).priority == 0
        assert not issubclass(
            type(AdaptivePolicyRule.model_validate(_rule_payload())), AdaptivePolicyRuleDraft
        )


class TestMandatoryEnterRetainConditions:
    def test_enter_and_retain_are_individually_mandatory(self) -> None:
        broken = _rule_payload()
        del broken["retain_condition"]
        with pytest.raises(ValidationError):
            AdaptivePolicyRuleDraft.model_validate(broken)
        broken = _rule_payload()
        del broken["enter_condition"]
        with pytest.raises(ValidationError):
            AdaptivePolicyRuleDraft.model_validate(broken)
        with pytest.raises(ValidationError):
            AdaptivePolicyRuleDraft.model_validate(_rule_payload(retain_condition=None))

    def test_structurally_equivalent_trees_express_no_hysteresis(self) -> None:
        shared = _all_node("c-shared", [_leaf("c-1"), _leaf("c-2")])
        rule = _rule_payload(enter_condition=shared, retain_condition=shared)
        draft = AdaptivePolicyDraft.model_validate(_draft_payload(rules=[rule]))
        assert draft.rules[0].enter_condition.condition_id == "c-shared"
        assert draft.rules[0].retain_condition.condition_id == "c-shared"


class TestStateMachineDeclarations:
    @pytest.mark.parametrize(
        "field", ["minimum_dwell_steps", "cooldown_steps", "global_switch_budget"]
    )
    @pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
    def test_strict_non_negative_declarations(self, field: str, bad: Any) -> None:
        for payload in (_draft_payload, _policy_payload):
            with pytest.raises(ValidationError):
                _validate(payload, **{field: bad})

    def test_zero_values_are_valid_declarations(self) -> None:
        draft = _validate(
            _draft_payload, minimum_dwell_steps=0, cooldown_steps=0, global_switch_budget=0
        )
        assert draft.minimum_dwell_steps == 0
        policy = _validate(
            _policy_payload, minimum_dwell_steps=0, cooldown_steps=0, global_switch_budget=0
        )
        assert policy.global_switch_budget == 0

    def test_documented_semantics_are_declared_not_executed(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_policy.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        for token in ("minimum dwell", "cooldown", "switch budget", "d + N", "s + N + 1"):
            assert token.replace(" ", "") in source.replace(" ", "").replace("-", ""), (
                f"ADR semantics not documented: {token}"
            )
        for executable in ("def evaluate", "def apply", "def select", "def decide"):
            assert executable not in code, f"executable state-machine surface: {executable}"


class TestDraftTrustBoundary:
    def test_draft_cannot_express_authority_hashes_identity_or_metadata(self) -> None:
        fields = set(AdaptivePolicyDraft.model_fields)
        assert fields == {
            "request_id",
            "actions",
            "initial_action_id",
            "fallback_action_id",
            "rules",
            "minimum_dwell_steps",
            "cooldown_steps",
            "global_switch_budget",
        }
        for token in _DRAFT_FORBIDDEN_FIELDS:
            assert not any(token in name for name in fields), f"draft accepts {token!r}"

    def test_draft_rejects_authority_fields_as_extra_data(self) -> None:
        for key, value in (
            ("identifier", "pol-1"),
            ("tenant_id", "tenant-1"),
            ("schema_version", "1.0.0"),
            ("runtime_version", "4.0.0"),
            ("campaign_id", "campaign-1"),
            ("scenario_id", "scenario-1"),
            ("world_version_id", "world-v1"),
            ("world_content_hash", H64),
            ("policy_id", "policy-1"),
            ("content_hash", H64),
            ("bound_at", NOW),
            ("metadata", {}),
            ("trajectory_plan_id", "tp-1"),
            ("strategy_candidate_id", "sc-1"),
            ("observation_bindings", []),
            ("provider", {"name": "x"}),
            ("callback", "lambda: None"),
            ("expression", "a > b"),
        ):
            with pytest.raises(ValidationError):
                AdaptivePolicyDraft.model_validate(_draft_payload(**{key: value}))

    def test_draft_is_not_a_versioned_contract(self) -> None:
        from kalhas.contracts.v1.shared import VersionedContract

        assert not issubclass(AdaptivePolicyDraft, VersionedContract)
        assert issubclass(AdaptivePolicy, VersionedContract)

    def test_draft_rule_cannot_carry_hashes_or_state_values(self) -> None:
        with pytest.raises(ValidationError):
            AdaptivePolicyRuleDraft.model_validate(_rule_payload(strategy_candidate_id="sc-1"))
        with pytest.raises(ValidationError):
            AdaptivePolicyRuleDraft.model_validate(_rule_payload(initial_value={"level": 5}))

    def test_nested_models_have_no_executable_types(self) -> None:
        for model in (
            AdaptivePolicyRuleDraft,
            ConditionComparisonLeaf,
            ConditionAllNode,
            ConditionAnyNode,
            ObservationBinding,
            TrajectoryPlanBinding,
            BoundAdaptiveAction,
            AdaptivePolicyRule,
        ):
            for field_info in model.model_fields.values():
                assert field_info.annotation is not None
                assert "Callable" not in str(field_info.annotation)
                assert "ModuleType" not in str(field_info.annotation)

    def test_contract_module_has_no_executable_or_network_surface(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "adaptive_policy.py").read_text(
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


class TestBoundPolicySurface:
    def test_bound_policy_round_trip(self) -> None:
        policy = AdaptivePolicy.model_validate(_policy_payload())
        dumped = policy.model_dump_json()
        reloaded = AdaptivePolicy.model_validate_json(dumped)
        assert reloaded == policy

    def test_bound_policy_is_frozen_and_strict(self) -> None:
        policy = AdaptivePolicy.model_validate(_policy_payload())
        with pytest.raises(ValidationError):
            policy.policy_id = "tampered"
        with pytest.raises(ValidationError):
            AdaptivePolicy.model_validate(_policy_payload(unexpected_field=1))

    def test_runtime_literal_is_exactly_4_0_0(self) -> None:
        for wrong in ("3.0.0", "4.0.1", "4.1.0", "5.0.0"):
            with pytest.raises(ValidationError):
                _validate(_policy_payload, runtime_version=wrong)

    def test_policy_version_is_semantic(self) -> None:
        for bad_version in ("1.0", "v1.0.0", "", "1.0.0-rc1"):
            with pytest.raises(ValidationError):
                _validate(_policy_payload, policy_version=bad_version)
        assert _validate(_policy_payload, policy_version="10.20.30").policy_version == "10.20.30"

    def test_bound_policy_has_no_runtime_state_or_outcome_surface(self) -> None:
        fields = set(AdaptivePolicy.model_fields)
        for token in (
            "current_action",
            "decision",
            "switch_event",
            "outcome",
            "recommendation",
            "evaluation_result",
            "step_index",
            "observation_event",
            "snapshot",
            "evidence",
            "run_id",
        ):
            assert not any(token in name for name in fields), f"runtime surface {token!r}"

    def test_bound_policy_metadata_rejects_non_finite(self) -> None:
        for bad in ({"x": float("nan")}, {"nested": {"y": float("inf")}}):
            with pytest.raises(ValidationError):
                _validate(_policy_payload, metadata=bad)

    def test_world_content_hash_pattern_enforced(self) -> None:
        for bad_hash in ("ABC" * 22, "z" * 64, "abc", ""):
            with pytest.raises(ValidationError):
                _validate(_policy_payload, world_content_hash=bad_hash[:64])


class TestRegistrySchemaAndPrefix:
    def test_adaptive_policy_is_index_52_after_immutable_52_prefix(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 53
        assert len(_HISTORICAL_47_NAMES) == 47
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[47:52] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
        )
        assert names[52] == "AdaptivePolicy"

    def test_registry_grows_only_additively_after_adaptive_policy(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert len(PUBLIC_CONTRACTS) >= 53
        assert "AdaptivePolicy" in names

    def test_nested_models_never_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_MODELS:
            assert nested not in names, f"{nested} independently registered"
        assert "AdaptivePolicy" in names

    def test_schema_artifact_set_follows_registry_without_nested_files(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        names = {path.name for path in schema_files}
        for nested in _NESTED_MODELS:
            assert f"{nested}.schema.json" not in names, f"standalone schema for {nested}"
        assert "AdaptivePolicy.schema.json" in names

    def test_adaptive_policy_schema_equals_model_json_schema(self) -> None:
        rendered = json.loads(
            (SCHEMA_DIR / "AdaptivePolicy.schema.json").read_text(encoding="utf-8")
        )
        assert rendered == AdaptivePolicy.model_json_schema()
        assert rendered["title"] == "AdaptivePolicy"
        assert rendered["additionalProperties"] is False

    def test_all_pre_existing_schema_files_byte_identical(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "schemas/v1"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_draft_has_no_standalone_schema_artifact(self) -> None:
        names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        assert "AdaptivePolicyDraft.schema.json" not in names

    def test_protected_h28_artifacts_remain_byte_identical(self) -> None:
        expected = {
            "docs/decisions/ADR-004-deterministic-adaptive-runtime-4.md": (
                "32518c01baa8443da73650b106cbd674b86b7ae8"
            ),
            "kalhas/contracts/v1/runtime_observation.py": (
                "1635868c936c055ff000587473944e699703df6d"
            ),
            "schemas/v1/RuntimeObservationDeclaration.schema.json": (
                "6b544b39657e2e4a605793bf0ac21f2e461e7e70"
            ),
            "schemas/v1/ExternalObservationInputBundle.schema.json": (
                "4211cf4480b2e04691ec12d7527371076eff184f"
            ),
            "tests/test_phase27_boundaries.py": ("ac8b7a5f32b5a9475d59acb69b88d8407d80625a"),
        }

        def git_hash(relative: str) -> str:
            result = subprocess.run(
                ["git", "hash-object", relative],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO_ROOT,
            )
            return result.stdout.strip()

        for relative, digest in expected.items():
            assert git_hash(relative) == digest, f"protected artifact drifted: {relative}"

    def test_deep_copy_round_trip_preserves_immutability(self) -> None:
        policy = AdaptivePolicy.model_validate(_policy_payload())
        snapshot = copy.deepcopy(policy)
        with pytest.raises(ValidationError):
            snapshot.initial_action_id = "act-b"
        assert snapshot == policy
