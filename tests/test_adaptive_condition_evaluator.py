"""Phase 28 pure deterministic adaptive-condition evaluator tests (H28-S03-C01).

Builds real strict ``AdaptivePolicy``, ``ConditionNode``, and
``RuntimeObservationEvent`` instances and exercises the application evaluator
``evaluate_adaptive_condition`` end-to-end. Event content hashes are
computed truthfully with the production canonical hashing convention
(``canonical_json`` over the complete JSON-mode payload excluding
``content_hash``, digested with ``sha256_hex``); no validator is
monkeypatched and no result is manufactured by replacing the evaluator.

Every evaluated condition is **authoritative content** of its supplied
``AdaptivePolicy``: the evaluator requires the condition to be an exact
closed node type whose canonical JSON equals one of the policy's rule
``enter_condition``/``retain_condition`` trees, so the test helpers construct
a one-rule policy whose ``enter_condition`` is exactly the condition under
test (``_make_policy``) and pair it with events covering exactly the bound
observations.

The adversarial proof covers, against the implementation itself: every
closed leaf operator with exact boundary behaviour; positive/negative/zero/
large-int/finite-float cases; one-ULP float adversaries via
``math.nextafter`` with no tolerance or rounding; exact ``number`` equality
for ``1`` vs ``1.0``; integer-kind exactness and contract-boundary rejection
of inappropriate representations; nested canonical ``all``/``any`` trees
with complete depth-first trace ordering; eager evaluation; ``missing``/
``false`` vs ``missing``/``error``; future/late/terminal events; reordered
and duplicate/non-increasing sequence positions; missing/duplicate/extra/
undeclared coverage; canonical declaration-identity event ordering including
the observation-ID/declaration-ID conflict; authoritative condition
membership (identical detached copy accepted, altered threshold/operator/
missing-behavior/observation-reference and cross-policy content rejected,
canonical ``1`` vs ``1.0`` distinction preserved); exact-type rejection of
policy/event/condition subclasses and lookalikes; wrong declaration/world/
seed/kind/unit provenance; forged content hashes; exact determinism;
immutability of inputs; missing-error reason preservation and safe stable
public messages; absence of any RNG/wall-clock/network/adapter/NEXUS/LEGION/
store/activity/eval/exec/callback/expression/arbitrary-import surface; and
unchanged protected contracts/schemas with an immutable additive-safe
registry prefix (exact current registry cardinality is owned only by the
Phase 28 registry compatibility suite).
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from kalhas.application.adaptive_condition_errors import (
    AdaptiveConditionEvaluationError,
    AdaptiveConditionMissingObservationError,
)
from kalhas.application.adaptive_condition_evaluator import (
    ConditionEvaluationResult,
    evaluate_adaptive_condition,
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
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent
from pydantic import ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES
from tests.test_phase28_registry_compatibility import _PHASE27_TAIL, _PHASE28_TAIL

REPO_ROOT = Path(__file__).resolve().parents[1]

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64_OTHER = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

WORLD_ID = "world-v1"
WORLD_HASH = H64
SEED_ID = "seed-1"
SEED_HASH = H64
DECISION = 1

#: The six protected baseline identifiers (git blob IDs from the session
#: brief). Registry-dependent artifacts (the v1 ``__init__`` registration
#: module and the registry-coupled test suites) are deliberately not pinned:
#: additive registry appends legitimately advance those blobs, so registry
#: integrity is protected semantically here
#: (``test_public_contract_registry_prefix_holds``); exact current
#: cardinality is owned by ``tests/test_phase28_registry_compatibility.py``.
PROTECTED_FINGERPRINTS = {
    "docs/decisions/ADR-004-deterministic-adaptive-runtime-4.md": (
        "32518c01baa8443da73650b106cbd674b86b7ae8"
    ),
    "kalhas/contracts/v1/runtime_observation.py": ("1635868c936c055ff000587473944e699703df6d"),
    "kalhas/contracts/v1/adaptive_policy.py": ("dbb5fb05290f6b0e13c21b9c6bc8d567bb17e1ed"),
    "schemas/v1/RuntimeObservationDeclaration.schema.json": (
        "6b544b39657e2e4a605793bf0ac21f2e461e7e70"
    ),
    "schemas/v1/ExternalObservationInputBundle.schema.json": (
        "4211cf4480b2e04691ec12d7527371076eff184f"
    ),
    "schemas/v1/AdaptivePolicy.schema.json": ("efb75d7091fd9ffcc910c8f6ba7a2ce568fc6b39"),
}


# ---------------------------------------------------------------------------
# Condition and policy builders.
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


def _make_policy(
    *,
    enter: ConditionNode,
    retain: ConditionNode | None = None,
    policy_id: str = "policy-x",
    decl_map: dict[str, str] | None = None,
    kind_map: dict[str, str] | None = None,
    unit_map: dict[str, str] | None = None,
    missing_map: dict[str, str] | None = None,
) -> AdaptivePolicy:
    """Build a one-rule immutable ``AdaptivePolicy``.

    The rule's ``enter_condition`` is exactly the supplied ``enter`` (making
    it canonical authoritative content), ``retain_condition`` defaults to the
    same tree, and the observation-binding catalog covers exactly the
    observations referenced by the two condition trees so the contract's
    complete-coverage and leaf/binding agreement validators hold. Per-
    observation declaration identity, value kind, unit, and missing behavior
    may be overridden for adversarial ordering/provenance proof.
    """
    decl_map = decl_map or {}
    kind_map = kind_map or {}
    unit_map = unit_map or {}
    missing_map = missing_map or {}

    leaves: list[ConditionComparisonLeaf] = []
    _collect_leaves(enter, leaves)
    if retain is not None:
        _collect_leaves(retain, leaves)
    seen: dict[str, ConditionComparisonLeaf] = {}
    for leaf in leaves:
        seen[leaf.observation_id] = leaf

    bindings = []
    for obs_id in sorted(seen):
        leaf = seen[obs_id]
        bindings.append(
            {
                "observation_id": obs_id,
                "runtime_observation_declaration_id": decl_map.get(obs_id, _decl_id(obs_id)),
                "runtime_observation_declaration_content_hash": H64,
                "observed_value_kind": kind_map.get(obs_id, leaf.observed_value_kind),
                "unit": unit_map.get(obs_id, leaf.unit),
                "missing_behavior": missing_map.get(obs_id, leaf.missing_behavior),
            }
        )

    rule = {
        "rule_id": "rule-1",
        "priority": 0,
        "target_action_id": "act-b",
        "enter_condition": enter,
        "retain_condition": retain if retain is not None else enter,
        "per_rule_switch_budget": 3,
    }
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
        "actions": [_action_payload("act-a"), _action_payload("act-b")],
        "initial_action_id": "act-a",
        "fallback_action_id": "act-b",
        "rules": [rule],
        "minimum_dwell_steps": 2,
        "cooldown_steps": 1,
        "global_switch_budget": 10,
        "content_hash": H64,
        "bound_at": NOW,
        "metadata": {},
    }
    return AdaptivePolicy.model_validate(payload)


# ---------------------------------------------------------------------------
# Event builders.
# ---------------------------------------------------------------------------


def _event(
    obs: int,
    *,
    value: int | float = 10,
    status: str = "observed",
    observed_kind: str | None = "integer",
    unit: str | None = None,
    sequence: int | None = None,
    available: int | None = DECISION,
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
    avail = None if terminal else (available if available is not None else DECISION)
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


def _events(
    *values: int | float, missing: set[int] | None = None
) -> tuple[RuntimeObservationEvent, ...]:
    missing = missing or set()
    return tuple(
        _event(
            idx,
            value=value,
            status="missing" if idx in missing else "observed",
            sequence=idx,
        )
        for idx, value in enumerate(values, start=1)
    )


def _call(
    condition: ConditionNode,
    events: tuple[RuntimeObservationEvent, ...],
    *,
    decision: int = DECISION,
    seed: str = SEED_ID,
    seed_hash: str = SEED_HASH,
    policy: AdaptivePolicy | None = None,
) -> ConditionEvaluationResult:
    if policy is None:
        policy = _make_policy(enter=condition)
    return evaluate_adaptive_condition(
        policy=policy,
        condition=condition,
        events=events,
        decision_step=decision,
        scenario_seed_id=seed,
        seed_content_hash=seed_hash,
    )


def _num(
    operator: Literal["lt", "lte", "eq", "gte", "gt"],
    value: int | float,
    threshold: int | float,
) -> bool:
    condition = _leaf(1, kind="number", operator=operator, threshold=threshold)
    return _call(condition, (_event(1, value=value, observed_kind="number"),)).matched


def _digest(model: Any) -> str:
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = dataclasses.asdict(model)
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# Module-level authoritative fixtures.
# ---------------------------------------------------------------------------

LEAF1 = _leaf(1)
#: A canonical three-observation ``all`` tree over obs-1, obs-2, obs-3.
TREE3 = _all("enter-root", (_leaf(1), _leaf(2), _leaf(3)))
#: An immutable policy whose sole rule's ``enter_condition`` is ``TREE3``.
POLICY3 = _make_policy(enter=TREE3)
#: A single-observation policy whose ``enter_condition`` is ``LEAF1``.
POLICY1 = _make_policy(enter=LEAF1)


# ---------------------------------------------------------------------------
# 1. All five leaf operators with exact boundary behaviour.
# ---------------------------------------------------------------------------


class TestLeafOperatorBoundaries:
    @pytest.mark.parametrize(
        ("operator", "threshold", "passing", "failing"),
        [
            ("lt", 5, 4, 5),
            ("lte", 5, 5, 6),
            ("eq", 5, 5, 6),
            ("gte", 5, 5, 4),
            ("gt", 5, 6, 5),
        ],
    )
    def test_exact_boundary(
        self,
        operator: Literal["lt", "lte", "eq", "gte", "gt"],
        threshold: int,
        passing: int,
        failing: int,
    ) -> None:
        condition = _leaf(1, operator=operator, threshold=threshold)
        assert _call(condition, (_event(1, value=passing),)).matched is True
        assert _call(condition, (_event(1, value=failing),)).matched is False


class TestNumericAdversaries:
    @pytest.mark.parametrize(
        ("op", "threshold", "value", "expected"),
        [
            ("eq", 0, 0, True),
            ("eq", 0, -1, False),
            ("lt", 0, -1, True),
            ("gt", -10, 42, True),
            ("gte", -3, -3, True),
            ("lte", -3, -4, True),
            ("eq", -7, -7, True),
        ],
    )
    def test_integer_kind_exact(
        self,
        op: Literal["lt", "lte", "eq", "gte", "gt"],
        threshold: int,
        value: int,
        expected: bool,
    ) -> None:
        condition = _leaf(1, operator=op, threshold=threshold)
        assert _call(condition, (_event(1, value=value),)).matched is expected

    def test_large_integer(self) -> None:
        condition = _leaf(obs=1, operator="gt", threshold=2**63)
        assert _call(condition, (_event(1, value=2**63 + 7),)).matched is True
        assert _call(condition, (_event(1, value=2**63 - 7),)).matched is False

    def test_finite_float(self) -> None:
        assert _num("gte", 0.0, -0.5) is True
        assert _num("lt", 0.5, 1.25) is True
        assert _num("gt", 0.5, 0.75) is False
        assert _num("eq", -0.25, -0.25) is True

    def test_one_ulp_float_adversaries(self) -> None:
        threshold = 1.0
        above = math.nextafter(threshold, math.inf)
        below = math.nextafter(threshold, -math.inf)
        # No tolerance: the value one ULP above is strictly gt, never eq.
        assert _num("gt", above, threshold) is True
        assert _num("eq", above, threshold) is False
        # One ULP below is neither gte nor eq.
        assert _num("gte", below, threshold) is False
        assert _num("eq", below, threshold) is False
        # Opposite direction across the boundary.
        assert _num("lt", below, threshold) is True
        assert _num("gt", below, threshold) is False
        # Exact equality at the boundary still holds.
        assert _num("eq", 1.0, threshold) is True

    def test_number_eq_one_and_one_point_zero_are_equal(self) -> None:
        assert _num("eq", 1.0, 1.0) is True
        assert _num("eq", 1, 1.0) is True
        assert _num("eq", 1.0, 1) is True

    def test_integer_kind_keeps_exact_ints_at_the_boundary(self) -> None:
        # A float representation on an integer-kind leaf is rejected before
        # evaluation by the strict contract boundary.
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(
                {
                    "identifier": "typed-e",
                    "runtime_version": "4.0.0",
                    "observation_declaration_id": "runtime-observation-1",
                    "observation_declaration_content_hash": H64,
                    "observation_id": "obs-1",
                    "source_kind": "state_field",
                    "world_version_id": WORLD_ID,
                    "world_content_hash": WORLD_HASH,
                    "scenario_seed_id": SEED_ID,
                    "seed_content_hash": SEED_HASH,
                    "sequence_position": 1,
                    "source_step_index": 1,
                    "delay_steps": 0,
                    "available_decision_step": DECISION,
                    "terminal": False,
                    "status": "observed",
                    "source_state_hash": H64,
                    "source_value": 1.5,
                    "applied_noise_value": None,
                    "exposed_observation_value": 1.5,
                    "observed_value_kind": "integer",
                    "observed_value_unit": None,
                    "noise_domain_literal": "kalhas-observation-noise-v1",
                    "noise_sampler_version": "sha256-counter-v1",
                    "noise_draw_index": None,
                    "content_hash": H64,
                }
            )


# ---------------------------------------------------------------------------
# 6 & 7. Compound / trace / eager evaluation.
# ---------------------------------------------------------------------------


class TestCompoundTraceAndEager:
    def test_nested_all_any_depth_first_trace(self) -> None:
        tree = _all(
            "c-root",
            (
                _any(
                    "c-a",
                    (
                        _leaf(1, condition_id="c-a1", operator="gte", threshold=5),
                        _leaf(2, condition_id="c-a2", operator="lte", threshold=50),
                    ),
                ),
                _all(
                    "c-b",
                    (
                        _leaf(3, condition_id="c-b1", operator="lte", threshold=100),
                        _leaf(1, condition_id="c-b2", operator="gt", threshold=0),
                    ),
                ),
            ),
        )
        result = _call(tree, _events(10, 50, 10))
        assert result.matched is True
        assert result.root_condition_id == "c-root"
        assert [entry.condition_id for entry in result.leaf_trace] == [
            "c-a1",
            "c-a2",
            "c-b1",
            "c-b2",
        ]
        assert [entry.observation_id for entry in result.leaf_trace] == [
            "obs-1",
            "obs-2",
            "obs-3",
            "obs-1",
        ]

    def test_any_still_evaluates_every_child(self) -> None:
        # First child already True, second must still be evaluated and recorded.
        tree = _any(
            "c-roota",
            (
                _leaf(1, condition_id="ca1", operator="gte", threshold=5),
                _leaf(2, condition_id="ca2", operator="lte", threshold=200),
            ),
        )
        result = _call(tree, _events(10, 500))
        assert result.matched is True
        assert [entry.condition_id for entry in result.leaf_trace] == ["ca1", "ca2"]
        # Even though the aggregate short-circuits semantically, the second leaf
        # is still evaluated and its (false) outcome is present in the trace.
        assert result.leaf_trace[1].matched is False

    def test_eager_error_in_logically_unnecessary_child_raises(self) -> None:
        # all: first leaf already False, but the missing/error sibling is still
        # evaluated and must raise.
        tree = _all(
            "c-roote",
            (
                _leaf(1, condition_id="e1", operator="lt", threshold=5),
                _leaf(3, condition_id="e2", operator="gte", threshold=10, missing="error"),
            ),
        )
        events = (_event(1, value=10), _event(3, value=10, status="missing"))
        with pytest.raises(AdaptiveConditionMissingObservationError):
            _call(tree, events)


class TestMissingBehavior:
    def test_missing_false_returns_false_with_trace(self) -> None:
        condition = _leaf(3, operator="gte", threshold=10, missing="false")
        events = (_event(3, status="missing"),)
        result = _call(condition, events)
        assert result.matched is False
        assert len(result.leaf_trace) == 1
        entry = result.leaf_trace[0]
        assert entry.status == "missing"
        assert entry.matched is False
        assert entry.observation_id == "obs-3"

    def test_missing_error_raises_and_returns_no_partial_result(self) -> None:
        condition = _leaf(3, operator="gte", threshold=10, missing="error")
        events = (_event(3, status="missing"),)
        with pytest.raises(AdaptiveConditionMissingObservationError):
            _call(condition, events)


# ---------------------------------------------------------------------------
# 10 & 11. Causal availability and tuple ordering.
# ---------------------------------------------------------------------------


class TestCausalAvailability:
    def test_future_event_fails(self) -> None:
        events = (_event(1), _event(2), _event(3, available=DECISION + 1))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_late_event_fails(self) -> None:
        events = (_event(1, available=DECISION - 1), _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_terminal_event_fails(self) -> None:
        events = (_event(1, terminal=True), _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)


class TestTupleOrderingAndUniqueness:
    def test_events_out_of_declaration_order_fail(self) -> None:
        events = (_event(2), _event(1), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_non_increasing_sequence_positions_fail(self) -> None:
        events = (_event(1, sequence=1), _event(2, sequence=1), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_duplicate_sequence_positions_fail(self) -> None:
        events = (_event(1, sequence=0), _event(2, sequence=0), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_duplicate_event_identifiers_fail(self) -> None:
        events = (_event(1), _event(2, identifier="event-1"), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)


class TestDeclarationOrderingConflict:
    def test_declaration_order_and_observation_order_conflict(self) -> None:
        # A policy whose binding declaration identities are permuted relative
        # to observation identities: obs-1 -> decl-3, obs-2 -> decl-1, obs-3
        # -> decl-2. ADR-004 requires events ordered ascending by declaration
        # identity.
        conflict = _make_policy(
            enter=TREE3,
            decl_map={
                "obs-1": "runtime-observation-3",
                "obs-2": "runtime-observation-1",
                "obs-3": "runtime-observation-2",
            },
        )

        def ev(obs: int, seq: int) -> RuntimeObservationEvent:
            return _event(
                obs,
                sequence=seq,
                declaration_id={
                    1: "runtime-observation-3",
                    2: "runtime-observation-1",
                    3: "runtime-observation-2",
                }[obs],
            )

        # Declaration order (obs-2, obs-3, obs-1 -> decl-1, decl-2, decl-3)
        # must pass.
        declaration_order = (ev(2, 1), ev(3, 2), ev(1, 3))
        result = _call(TREE3, declaration_order, policy=conflict)
        assert result.matched is True

        # Observation-ID order (obs-1, obs-2, obs-3 -> decl-3, decl-1, decl-2)
        # must fail; inputs are never sorted or repaired.
        observation_order = (ev(1, 1), ev(2, 2), ev(3, 3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, observation_order, policy=conflict)


class TestEventCoverage:
    def test_missing_event_coverage_fails(self) -> None:
        events = (_event(1), _event(2))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_duplicate_event_coverage_fails(self) -> None:
        events = (_event(1), _event(1, identifier="dup"), _event(2))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_extra_event_fails(self) -> None:
        events = (_event(1), _event(2), _event(3), _event(4, identifier="extra"))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_undeclared_observation_event_fails(self) -> None:
        events = (
            _event(1),
            _event(2),
            _event(3, observation_id="obs-99", declaration_id="runtime-observation-99"),
        )
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)


# ---------------------------------------------------------------------------
# 13. Provenance agreement.
# ---------------------------------------------------------------------------


class TestProvenanceAgreement:
    @pytest.mark.parametrize(
        "override",
        [
            {"declaration_id": "runtime-observation-999"},
            {"declaration_hash": H64_OTHER},
            {"world_version_id": "world-v2"},
            {"world_hash": H64_OTHER},
            {"scenario_seed_id": "seed-2"},
            {"seed_hash": H64_OTHER},
            {"observed_kind": "number"},
        ],
    )
    def test_provenance_mismatches_fail(self, override: dict[str, Any]) -> None:
        event = _event(1, **override)
        events = (event, _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_non_4_0_0_runtime_is_rejected_at_the_contract_boundary(self) -> None:
        # The event contract fixes runtime_version to 4.0.0, so a foreign
        # runtime cannot even be constructed (failure before the evaluator).
        with pytest.raises(ValidationError):
            _event(1, runtime_version="3.0.0")

    def test_wrong_unit_fails(self) -> None:
        unit_tree = _all(
            "enter-root",
            (_leaf(1, unit="meters"), _leaf(2), _leaf(3)),
        )
        unit_policy = _make_policy(enter=unit_tree)
        events = (_event(1, unit="feet"), _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(unit_tree, events, policy=unit_policy)


# ---------------------------------------------------------------------------
# 14. Forged content hashes.
# ---------------------------------------------------------------------------


class TestForgedContentHash:
    def test_forged_event_content_hash_fails(self) -> None:
        real = _event(1)
        forged = real.model_copy(update={"content_hash": H64_OTHER})
        events = (forged, _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_tampered_value_changes_digest_and_fails(self) -> None:
        real = _event(1, value=3)
        # Tamper the exposed value but leave the content hash unchanged: the
        # recomputed digest no longer matches and the event is rejected.
        forged = real.model_copy(update={"exposed_observation_value": 5000})
        events = (forged, _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)


# ---------------------------------------------------------------------------
# 15 & 16. Determinism and input immutability.
# ---------------------------------------------------------------------------


class TestDeterminismAndImmutability:
    def test_repeated_evaluation_is_exactly_deterministic(self) -> None:
        tree = _all(
            "c-root",
            (
                _leaf(1, condition_id="a", operator="gte", threshold=5),
                _leaf(2, condition_id="b", operator="lte", threshold=200),
            ),
        )
        events = _events(10, 30)
        first = _call(tree, events)
        second = _call(tree, events)
        assert first == second
        assert first.leaf_trace == second.leaf_trace
        assert _digest(first) == _digest(second)

    def test_inputs_unchanged_after_success(self) -> None:
        tree = _all(
            "n",
            (
                _leaf(1, condition_id="a", operator="gte", threshold=5),
                _leaf(2, condition_id="b", operator="lt", threshold=100),
            ),
        )
        events = _events(10, 50)
        policy = _make_policy(enter=tree)
        policy_digest = _digest(policy)
        tree_digest = sha256_hex(canonical_json(tree.model_dump(mode="json")))
        events_digest = sha256_hex(canonical_json([e.model_dump(mode="json") for e in events]))
        _call(tree, events, policy=policy)
        assert _digest(policy) == policy_digest
        assert sha256_hex(canonical_json(tree.model_dump(mode="json"))) == tree_digest
        assert (
            sha256_hex(canonical_json([e.model_dump(mode="json") for e in events])) == events_digest
        )

    def test_inputs_unchanged_after_failure(self) -> None:
        condition = _leaf(3, missing="error")
        events = (_event(3, status="missing"),)
        policy = _make_policy(enter=condition)
        policy_digest = _digest(policy)
        events_digest = sha256_hex(canonical_json([e.model_dump(mode="json") for e in events]))
        with pytest.raises(AdaptiveConditionMissingObservationError):
            _call(condition, events, policy=policy)
        assert _digest(policy) == policy_digest
        assert (
            sha256_hex(canonical_json([e.model_dump(mode="json") for e in events])) == events_digest
        )


# ---------------------------------------------------------------------------
# 2. Authoritative condition membership.
# ---------------------------------------------------------------------------


class TestAuthoritativeCondition:
    def test_identical_detached_copy_is_accepted(self) -> None:
        detached = TREE3.model_copy(deep=True)
        assert detached is not TREE3
        assert _call(detached, _events(10, 50, 10), policy=POLICY3).matched is True

    def test_identical_shallow_copy_is_accepted(self) -> None:
        copy = TREE3.model_copy()
        assert copy is not TREE3
        assert _call(copy, _events(10, 50, 10), policy=POLICY3).matched is True

    def test_authoritative_leaf_matching_retain_condition_is_accepted(self) -> None:
        # LEAF1 is POLICY1's sole enter (and retain) condition.
        assert _call(LEAF1, (_event(1),), policy=POLICY1).matched is True

    @pytest.mark.parametrize(
        "bad",
        [
            _all("enter-root", (_leaf(1, threshold=6), _leaf(2), _leaf(3))),  # altered threshold
            _all("enter-root", (_leaf(1, operator="lt"), _leaf(2), _leaf(3))),  # altered operator
            _all("enter-root", (_leaf(1, missing="error"), _leaf(2), _leaf(3))),  # missing behavior
            _all(
                "enter-root",
                (
                    _leaf(1),
                    _leaf(2),
                    ConditionComparisonLeaf(
                        kind="comparison",
                        condition_id="c-3",
                        observation_id="obs-99",
                        observed_value_kind="integer",
                        unit=None,
                        operator="gte",
                        threshold=5,
                        missing_behavior="false",
                    ),
                ),
            ),  # observation reference
        ],
    )
    def test_altered_valid_tree_is_rejected(self, bad: ConditionNode) -> None:
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(bad, _events(10, 50, 10), policy=POLICY3)

    def test_content_copied_from_another_policy_is_rejected(self) -> None:
        # A tree identical in structure but different in threshold belongs to
        # another policy (POLICY_OTHER). Supplying it to POLICY3 must fail.
        other_tree = _all("enter-root", (_leaf(1, threshold=6), _leaf(2), _leaf(3)))
        _other_policy = _make_policy(enter=other_tree, policy_id="policy-other")
        assert other_tree not in (
            POLICY3.rules[0].enter_condition,
            POLICY3.rules[0].retain_condition,
        )
        assert _call(other_tree, _events(10, 50, 10), policy=_other_policy).matched is True
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(other_tree, _events(10, 50, 10), policy=POLICY3)

    def test_canonical_numeric_distinction_one_vs_one_point_zero(self) -> None:
        # A number-kind leaf with an exact int threshold 1 is authoritative.
        int_tree = _leaf(1, kind="number", operator="eq", threshold=1)
        int_policy = _make_policy(enter=int_tree, policy_id="policy-int")
        assert (
            _call(
                int_tree, (_event(1, value=1, observed_kind="number"),), policy=int_policy
            ).matched
            is True
        )
        # A detached leaf with a float threshold 1.0 serializes to distinct
        # canonical JSON ("1.0" vs "1") and is therefore not authoritative.
        float_tree = int_tree.model_copy(deep=True, update={"threshold": 1.0})
        assert canonical_json(int_tree.model_dump(mode="json")) != canonical_json(
            float_tree.model_dump(mode="json")
        )
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(float_tree, (_event(1, value=1.0, observed_kind="number"),), policy=int_policy)


# ---------------------------------------------------------------------------
# 3. Exact input types: subclasses and lookalikes are rejected.
# ---------------------------------------------------------------------------


class _PolicyLookalike(AdaptivePolicy):
    """A subclass carrying identical content; must be rejected on exact-type grounds."""


class _EventLookalike(RuntimeObservationEvent):
    """A subclass carrying identical content; must be rejected on exact-type grounds."""


class _LeafLookalike(ConditionComparisonLeaf):
    """A condition-node subclass; must be rejected on exact-type grounds."""


class TestExactInputTypes:
    def test_policy_subclass_is_rejected(self) -> None:
        lookalike = _PolicyLookalike.model_validate(POLICY3.model_dump(mode="json"))
        assert type(lookalike) is _PolicyLookalike
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, _events(10, 50, 10), policy=lookalike)

    def test_event_subclass_is_rejected(self) -> None:
        lookalike = _EventLookalike.model_validate(_event(1).model_dump(mode="json"))
        assert type(lookalike) is _EventLookalike
        events = (lookalike, _event(2), _event(3))
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(TREE3, events, policy=POLICY3)

    def test_condition_node_subclass_is_rejected(self) -> None:
        lookalike = _LeafLookalike.model_validate(_leaf(1).model_dump(mode="json"))
        assert type(lookalike) is _LeafLookalike
        with pytest.raises(AdaptiveConditionEvaluationError):
            _call(lookalike, (_event(1),), policy=POLICY1)


# ---------------------------------------------------------------------------
# 4. Missing-error constructor: reason preservation and safe stable messages.
# ---------------------------------------------------------------------------


class TestMissingErrorConstructor:
    def test_supplied_reason_is_preserved_exactly(self) -> None:
        err = AdaptiveConditionMissingObservationError("rule-99")
        assert err.reason == "rule-99"

    def test_general_reason_is_preserved_exactly(self) -> None:
        err = AdaptiveConditionEvaluationError("coverage-rule")
        assert err.reason == "coverage-rule"

    def test_stable_generic_public_messages(self) -> None:
        general = AdaptiveConditionEvaluationError("g")
        missing = AdaptiveConditionMissingObservationError("m")
        assert str(general) == (
            "Adaptive condition evaluation failed input or integrity verification and was rejected"
        )
        assert str(missing) == (
            "A referenced observation is missing and its declared missing "
            "behavior requires evaluation to fail closed"
        )

    def test_messages_do_not_leak_supplied_reason(self) -> None:
        secret = "policy-1:threshold-5:obs-secret"
        general = AdaptiveConditionEvaluationError(secret)
        missing = AdaptiveConditionMissingObservationError(secret)
        assert secret not in str(general)
        assert secret not in str(missing)
        assert general.reason == secret
        assert missing.reason == secret

    def test_missing_error_subclass_hierarchy(self) -> None:
        assert issubclass(
            AdaptiveConditionMissingObservationError, AdaptiveConditionEvaluationError
        )
        assert issubclass(AdaptiveConditionMissingObservationError, KalhasDomainError)

    def test_missing_error_raised_by_evaluator_preserves_reason(self) -> None:
        condition = _leaf(3, missing="error")
        events = (_event(3, status="missing"),)
        with pytest.raises(AdaptiveConditionMissingObservationError) as excinfo:
            _call(condition, events)
        assert excinfo.value.reason == "missing_observation"
        # The public message is the stable missing class message, not the reason.
        assert str(excinfo.value) == (
            "A referenced observation is missing and its declared missing "
            "behavior requires evaluation to fail closed"
        )

    def test_status_is_observed_or_missing(self) -> None:
        condition = _leaf(1, operator="gte", threshold=5)
        result = _call(condition, (_event(1),))
        assert result.leaf_trace[0].status == "observed"
        assert result.leaf_trace[0].status in ("observed", "missing")


# ---------------------------------------------------------------------------
# 17. No forbidden surface in the new implementation.
# ---------------------------------------------------------------------------


class TestNoForbiddenSurface:
    _FORBIDDEN_IMPORTS = (
        "import os",
        "import sys",
        "import time",
        "import datetime",
        "import random",
        "import uuid",
        "import math",
        "import socket",
        "import json",
        "import re",
        "import hashlib",
        "import subprocess",
        "import requests",
        "import urllib",
        "import pathlib",
        "import tempfile",
        "import shutil",
        "import importlib",
    )
    _DYNAMIC_TOKENS = (
        "eval(",
        "exec(",
        "compile(",
        "__import__",
        "importlib",
        "globals()",
        "locals()",
        "getattr(",
        "setattr(",
        "pickle",
        "marshal",
        "ctypes",
        "callable",
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

    def test_no_forbidden_imports_dynamic_eval_or_subsystem_reference(self) -> None:
        import kalhas.application.adaptive_condition_errors as errors_mod
        import kalhas.application.adaptive_condition_evaluator as evaluator_mod

        sources = (
            inspect.getsource(evaluator_mod),
            inspect.getsource(errors_mod),
        )
        for source in sources:
            for fragment in self._FORBIDDEN_IMPORTS:
                assert fragment not in source
            for token in self._DYNAMIC_TOKENS:
                assert token not in source
            for path in self._SUBSYSTEM_PATHS:
                assert path not in source
            # Every non-blank line is either a comment, a static standard-library
            # (dataclasses/typing/future) or kalhas import, or body code; no
            # dynamic or arbitrary import exists. ``typing`` is a non-dynamic
            # static type-annotation import required for the ``Literal`` status.
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    assert stripped.startswith(
                        (
                            "from __future__",
                            "from dataclasses",
                            "from typing",
                            "from kalhas.",
                        )
                    ), stripped

    def test_sources_have_no_rng_clock_or_io_identifier(self) -> None:
        import kalhas.application.adaptive_condition_evaluator as evaluator_mod

        source = inspect.getsource(evaluator_mod)
        for token in (
            "random.",
            "uuid4",
            ".randint",
            ".uniform(",
            "datetime.now",
            "time.time",
            "monotonic",
            "socket",
            "Path(",
            "os.path",
        ):
            assert token not in source


# ---------------------------------------------------------------------------
# 18. Protected fingerprint and registry invariants remain unchanged.
# ---------------------------------------------------------------------------


class TestProtectedFingerprintsAndRegistry:
    def test_protected_git_blob_ids_are_unchanged(self) -> None:
        for rel_path, expected in PROTECTED_FINGERPRINTS.items():
            result = subprocess.run(
                ["git", "hash-object", str(REPO_ROOT / rel_path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == expected, rel_path

    def test_public_contract_registry_prefix_holds(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        # Additive-safe registry semantics: Phase 28's accepted append grew
        # the v1 registry from 50 to 54, so this evaluator suite guards the
        # immutable 53-entry historical prefix and permits later additive
        # entries. Exact current cardinality is owned exclusively by
        # tests/test_phase28_registry_compatibility.py.
        assert len(names) >= 53
        assert names[50] == "RuntimeObservationDeclaration"
        assert names[51] == "ExternalObservationInputBundle"
        assert names[52] == "AdaptivePolicy"
        # The first 53 entries equal the repository prefix authority: the
        # frozen 47-name Phase 27 head, the immutable Phase 27 tail
        # (indexes 47-49), and the first three accepted Phase 28 names.
        historical_prefix = [*_HISTORICAL_47_NAMES, *_PHASE27_TAIL, *_PHASE28_TAIL[:3]]
        assert len(historical_prefix) == 53
        assert names[:53] == historical_prefix
