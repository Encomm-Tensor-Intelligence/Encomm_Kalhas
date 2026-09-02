"""Pure deterministic adaptive-condition evaluation (Phase 28, H28-S03).

Implements the pure deterministic evaluator for exactly one accepted closed
``ConditionNode`` tree evaluated against one complete, canonical
current-decision ``RuntimeObservationEvent`` tuple under one immutable
``AdaptivePolicy`` (runtime ``4.0.0``).

Before any leaf is evaluated, the complete input is validated **atomically
and fail-closed** (never repaired, sorted, coerced, synthesized, or silently
accepted):

- the policy is an exact runtime-4 ``AdaptivePolicy``;
- the decision step is an exact non-negative ``int`` (bool, float, string,
  and negative values are rejected);
- the observation events are an exact tuple of ``RuntimeObservationEvent``
  instances;
- there is exactly one event for every ``policy.observation_bindings`` entry
  (missing coverage, additions, undeclared events, duplicates, or ambiguity
  fail);
- tuple order is canonical ascending by observation declaration identity;
- ``sequence_position`` values are unique and strictly increasing in tuple
  order;
- event identifiers, observation IDs, and declaration IDs are unique;
- each event agrees exactly with its observation binding (observation ID,
  declaration ID and hash, value kind, and unit for observed events);
- every event agrees with the runtime ``4.0.0`` literal, the policy world
  version ID and world content hash, and the expected scenario-seed ID and
  seed content hash;
- every event is non-terminal and available at exactly the requested
  decision step (future, late, and terminal events fail);
- every recomputed event content hash (canonical JSON of the complete
  JSON-mode payload excluding ``content_hash``) matches the recorded value,
  so any forged event fails.

Evaluation uses exactly the closed language: leaf operators ``lt``, ``lte``,
``eq``, ``gte``, ``gt`` and compound nodes ``all``/``any``. Children are
traversed in their already-validated canonical order and every child is
evaluated eagerly - there is no short-circuiting - so a complete depth-first
leaf trace is produced and a missing observation with behavior ``"error"``
fails even when a sibling has already determined the boolean aggregate. A
missing observation with behavior ``"false"`` returns a false leaf result;
missing behavior is never inferred from truthiness. Observed leaves compare
only ``exposed_observation_value`` with the exact finite threshold using
direct Python numeric comparisons (no ``float`` conversion, rounding,
``isclose``, Decimal conversion, clipping, normalization, or tolerance): for
the ``number`` kind ``1`` and ``1.0`` compare numerically equal without
converting either operand, while integer-kind operands remain exact ints.

This module never mutates the policy, condition, events, or tuple, uses no
RNG, wall clock, ``uuid``, filesystem write, store, activity event, network,
adapter, NEXUS, or LEGION dependency. The result dataclasses are frozen and
slotted and carry only safe reference identities - never raw observed
values. Being fully deterministic, repeated calls on identical inputs return
exactly equal results. Rule ordering, winner selection, enter-versus-retain
selection, dwell/cooldown/switch-budget/fallback/current-action state,
``AdaptivePolicyStateSnapshot``, decision and switch events, runtime
execution/planning/replay/campaign integration, observation production,
sampling, state-field extraction, or external-input resolution, and
persistence/query/API/schema/registry surfaces are deliberately out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kalhas.application.adaptive_condition_errors import (
    AdaptiveConditionEvaluationError,
    AdaptiveConditionMissingObservationError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    ConditionAllNode,
    ConditionAnyNode,
    ConditionComparisonLeaf,
    ConditionNode,
    ObservationBinding,
)
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

#: The closed set of supported leaf comparison operators. Any other operator
#: is a foreign node/operator kind and fails fail-closed.
_VALID_OPERATORS = frozenset(("lt", "lte", "eq", "gte", "gt"))


def evaluate_adaptive_condition(
    *,
    policy: AdaptivePolicy,
    condition: ConditionNode,
    events: tuple[RuntimeObservationEvent, ...],
    decision_step: int,
    scenario_seed_id: str,
    seed_content_hash: str,
) -> ConditionEvaluationResult:
    """Evaluate exactly one accepted condition tree against complete evidence.

    The input preflight is atomic and fail-closed; any violation raises the
    typed :class:`AdaptiveConditionEvaluationError` (or the closed
    :class:`AdaptiveConditionMissingObservationError` for a missing
    observation with behavior ``"error"``) and produces no partial result. On
    success it returns a frozen result carrying the root condition identifier,
    the final matched boolean, and the complete ordered depth-first
    leaf-evaluation trace. No input is mutated and no raw observed value is
    copied into the result.
    """
    if type(policy) is not AdaptivePolicy:
        raise AdaptiveConditionEvaluationError("policy_must_be_exact_adaptive_policy")
    if policy.runtime_version != "4.0.0":
        raise AdaptiveConditionEvaluationError("policy_must_be_exact_runtime_4_adaptive_policy")

    if isinstance(decision_step, bool) or not isinstance(decision_step, int) or decision_step < 0:
        raise AdaptiveConditionEvaluationError("decision_step_must_be_exact_non_negative_int")

    if not isinstance(events, tuple) or not all(
        type(event) is RuntimeObservationEvent for event in events
    ):
        raise AdaptiveConditionEvaluationError(
            "observation_events_must_be_exact_tuple_of_runtime_observation_events"
        )

    _verify_condition_authority(policy=policy, condition=condition)

    _verify_inputs(
        policy=policy,
        events=events,
        decision_step=decision_step,
        scenario_seed_id=scenario_seed_id,
        seed_content_hash=seed_content_hash,
    )

    events_by_observation: dict[str, RuntimeObservationEvent] = {
        event.observation_id: event for event in events
    }
    trace: list[ConditionLeafTrace] = []
    matched = _eval_node(
        node=condition,
        events_by_observation=events_by_observation,
        trace=trace,
    )
    return ConditionEvaluationResult(
        root_condition_id=condition.condition_id,
        matched=bool(matched),
        leaf_trace=tuple(trace),
    )


def _verify_condition_authority(
    *,
    policy: AdaptivePolicy,
    condition: ConditionNode,
) -> None:
    """Require the supplied condition to be authoritative policy content.

    The condition must be an exact closed node model type (``comparison``,
    ``all``, or ``any``) whose canonical JSON content is an identical member
    of the supplied ``AdaptivePolicy`` - matching, by canonical JSON equality,
    one of every bound rule's ``enter_condition`` or ``retain_condition``
    trees. An identical detached copy is accepted; altered thresholds,
    operators, missing behaviors, observation references, or content
    copied from another policy are rejected. Canonical numeric distinction (JSON
    ``1`` versus ``1.0``) is preserved because comparison is over canonical
    JSON bytes, never object identity. Rule selection and the enter/retain
    state-machine choice are deliberately out of scope here.
    """
    if type(condition) not in (
        ConditionComparisonLeaf,
        ConditionAllNode,
        ConditionAnyNode,
    ):
        raise AdaptiveConditionEvaluationError("condition_must_be_exact_closed_node_type")
    condition_json = canonical_json(condition.model_dump(mode="json"))
    for rule in policy.rules:
        if canonical_json(rule.enter_condition.model_dump(mode="json")) == condition_json:
            return
        if canonical_json(rule.retain_condition.model_dump(mode="json")) == condition_json:
            return
    raise AdaptiveConditionEvaluationError(
        "condition_must_be_authoritative_content_of_supplied_policy"
    )


def _verify_inputs(
    *,
    policy: AdaptivePolicy,
    events: tuple[RuntimeObservationEvent, ...],
    decision_step: int,
    scenario_seed_id: str,
    seed_content_hash: str,
) -> None:
    """Verify the complete input atomically; never repair or coerce anything."""
    expected_observation_ids = [binding.observation_id for binding in policy.observation_bindings]
    event_observation_ids = [event.observation_id for event in events]

    if len(events) != len(policy.observation_bindings):
        raise AdaptiveConditionEvaluationError("event_count_must_equal_observation_binding_count")
    if set(event_observation_ids) != set(expected_observation_ids):
        raise AdaptiveConditionEvaluationError(
            "event_coverage_must_be_exactly_one_event_per_binding"
        )
    # ADR-004 D28-02 requires simultaneously available events to be ordered
    # canonically ascending by observation declaration identity. The expected
    # order is derived from the policy binding declaration IDs; the supplied
    # events must already be in exactly that ascending order and are never
    # sorted, repaired, or reordered here.
    expected_declaration_order = sorted(
        binding.runtime_observation_declaration_id for binding in policy.observation_bindings
    )
    event_declaration_ids = [event.observation_declaration_id for event in events]
    if event_declaration_ids != expected_declaration_order:
        raise AdaptiveConditionEvaluationError(
            "events_must_be_canonically_ordered_by_observation_declaration_identity"
        )

    sequence_positions = [event.sequence_position for event in events]
    if any(
        sequence_positions[index] >= sequence_positions[index + 1]
        for index in range(len(sequence_positions) - 1)
    ):
        raise AdaptiveConditionEvaluationError(
            "sequence_positions_must_be_unique_strictly_increasing"
        )
    if len({event.identifier for event in events}) != len(events):
        raise AdaptiveConditionEvaluationError("event_identifiers_must_be_unique")
    if len({event.observation_declaration_id for event in events}) != len(events):
        raise AdaptiveConditionEvaluationError("declaration_ids_must_be_unique")

    binding_by_observation = {
        binding.observation_id: binding for binding in policy.observation_bindings
    }
    for event in events:
        _verify_event_agreement(
            event=event,
            binding=binding_by_observation[event.observation_id],
            policy=policy,
            decision_step=decision_step,
            scenario_seed_id=scenario_seed_id,
            seed_content_hash=seed_content_hash,
        )


def _verify_event_agreement(
    *,
    event: RuntimeObservationEvent,
    binding: ObservationBinding,
    policy: AdaptivePolicy,
    decision_step: int,
    scenario_seed_id: str,
    seed_content_hash: str,
) -> None:
    """Verify one event's exact agreement with its binding and the evidence header."""
    if event.observation_declaration_id != binding.runtime_observation_declaration_id:
        raise AdaptiveConditionEvaluationError("event_declaration_reference_mismatch")
    if (
        event.observation_declaration_content_hash
        != binding.runtime_observation_declaration_content_hash
    ):
        raise AdaptiveConditionEvaluationError("event_declaration_content_hash_mismatch")
    if event.status == "observed":
        if event.observed_value_kind != binding.observed_value_kind:
            raise AdaptiveConditionEvaluationError("event_value_kind_mismatch")
        if event.observed_value_unit != binding.unit:
            raise AdaptiveConditionEvaluationError("event_unit_mismatch")

    if event.runtime_version != "4.0.0":
        raise AdaptiveConditionEvaluationError("event_runtime_mismatch")
    if event.world_version_id != policy.world_version_id:
        raise AdaptiveConditionEvaluationError("event_world_identity_mismatch")
    if event.world_content_hash != policy.world_content_hash:
        raise AdaptiveConditionEvaluationError("event_world_content_hash_mismatch")
    if event.scenario_seed_id != scenario_seed_id:
        raise AdaptiveConditionEvaluationError("event_seed_identity_mismatch")
    if event.seed_content_hash != seed_content_hash:
        raise AdaptiveConditionEvaluationError("event_seed_content_hash_mismatch")

    if event.terminal:
        raise AdaptiveConditionEvaluationError("event_must_be_non_terminal")
    if event.available_decision_step != decision_step:
        raise AdaptiveConditionEvaluationError("event_must_be_available_at_exact_decision_step")

    recomputed = sha256_hex(canonical_json(event.model_dump(mode="json", exclude={"content_hash"})))
    if recomputed != event.content_hash:
        raise AdaptiveConditionEvaluationError("event_content_hash_mismatch")


def _eval_node(
    *,
    node: ConditionNode,
    events_by_observation: dict[str, RuntimeObservationEvent],
    trace: list[ConditionLeafTrace],
) -> bool:
    """Evaluate one node eagerly and record its leaf trace in depth-first order."""
    if isinstance(node, ConditionComparisonLeaf):
        return _eval_leaf(
            node=node,
            events_by_observation=events_by_observation,
            trace=trace,
        )
    children_results = [
        _eval_node(
            node=child,
            events_by_observation=events_by_observation,
            trace=trace,
        )
        for child in node.children
    ]
    if isinstance(node, ConditionAllNode):
        return all(children_results)
    if isinstance(node, ConditionAnyNode):
        return any(children_results)
    raise AdaptiveConditionEvaluationError("unknown_condition_node_kind")


def _eval_leaf(
    *,
    node: ConditionComparisonLeaf,
    events_by_observation: dict[str, RuntimeObservationEvent],
    trace: list[ConditionLeafTrace],
) -> bool:
    """Evaluate exactly one comparison leaf, recording only safe references."""
    event = events_by_observation.get(node.observation_id)
    if event is None:
        raise AdaptiveConditionEvaluationError("leaf_observation_has_no_available_event")

    if event.status == "missing":
        if node.missing_behavior == "false":
            trace.append(
                ConditionLeafTrace(
                    condition_id=node.condition_id,
                    observation_id=node.observation_id,
                    event_identifier=event.identifier,
                    event_content_hash=event.content_hash,
                    status="missing",
                    matched=False,
                )
            )
            return False
        if node.missing_behavior == "error":
            raise AdaptiveConditionMissingObservationError("missing_observation")
        raise AdaptiveConditionEvaluationError("unknown_missing_behavior")

    if event.observed_value_kind != node.observed_value_kind:
        raise AdaptiveConditionEvaluationError("leaf_value_kind_mismatch")
    if event.observed_value_unit != node.unit:
        raise AdaptiveConditionEvaluationError("leaf_unit_mismatch")

    value = event.exposed_observation_value
    if value is None:
        raise AdaptiveConditionEvaluationError("observed_event_has_no_exposed_value")
    if node.operator not in _VALID_OPERATORS:
        raise AdaptiveConditionEvaluationError("unknown_leaf_operator")

    matched = _apply_operator(node.operator, value, node.threshold)
    trace.append(
        ConditionLeafTrace(
            condition_id=node.condition_id,
            observation_id=node.observation_id,
            event_identifier=str(event.identifier),
            event_content_hash=str(event.content_hash),
            status="observed",
            matched=bool(matched),
        )
    )
    return bool(matched)


def _apply_operator(operator: str, value: int | float, threshold: int | float) -> bool:
    """Direct exact numeric comparison; no conversion, rounding, or tolerance."""
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    if operator == "eq":
        return value == threshold
    if operator == "gte":
        return value >= threshold
    if operator == "gt":
        return value > threshold
    raise AdaptiveConditionEvaluationError("unknown_leaf_operator")


@dataclass(frozen=True, slots=True)
class ConditionLeafTrace:
    """One safe, deterministic leaf reference for the later state-machine slice.

    Carries only identities and status - never raw observed values, thresholds,
    or counts.
    """

    condition_id: str
    observation_id: str
    event_identifier: str
    event_content_hash: str
    status: Literal["observed", "missing"]
    matched: bool


@dataclass(frozen=True, slots=True)
class ConditionEvaluationResult:
    """The frozen result of one condition evaluation.

    ``root_condition_id`` identifies the evaluated root, ``matched`` is the
    final boolean aggregate, and ``leaf_trace`` is the complete ordered
    depth-first trace of every evaluated leaf.
    """

    root_condition_id: str
    matched: bool
    leaf_trace: tuple[ConditionLeafTrace, ...]


__all__ = [
    "ConditionEvaluationResult",
    "ConditionLeafTrace",
    "evaluate_adaptive_condition",
]
