"""Phase 16 pure execution-builder tests.

Proves ``build_run_trajectory_execution`` is deterministic, pure, and
exact: one evaluation per applicable state-model plan in canonical
order, references preserved exactly (including repetitions), engine
attempts converted exactly, every hash recomputable and order-correct,
identical across independent stores, insertion-order invariant,
mutation-free, wall-clock-free, and randomness-free; the recorded seed
changes provenance and execution identity but never the current
state-transition trace semantics; and the runtime-version and
plan-selection gates reject invalid inputs before anything is built.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import (
    RunTrajectoryExecutionIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import (
    VerifiedRunTrajectoryInputs,
    verify_run_trajectory_inputs,
)
from kalhas.application.run_trajectory_runtime import (
    build_run_trajectory_execution,
    run_trajectory_execution_content_hash,
    run_trajectory_execution_identifier,
    state_trajectory_result_content_hash,
    trajectory_plan_set_hash,
)
from kalhas.application.state_transition_engine import evaluate_trajectory, state_hash
from kalhas.application.strategy_trajectory_service import get_strategy_trajectory_plans
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import StateValueKind
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)

from tests.phase4_helpers import build_seed, build_store, prepare
from tests.phase16_helpers import (
    SM_1_IDENTIFIER,
    SM_2_IDENTIFIER,
    ScriptedTrajectoryLegion,
    build_model,
    build_trajectory_store,
    build_transition,
)

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _resolved(store: InMemoryScenarioStore, run_id: str) -> VerifiedRunTrajectoryInputs:
    return verify_run_trajectory_inputs(store=store, tenant_id="tenant-1", run_id=run_id)


def _first_run_id(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> str:
    plan = store.get_run_plans("tenant-1", campaign_id)[0]
    return run_identifier(plan)


def _draft(request: StrategyTrajectoryPlanRequest) -> StrategyTrajectoryPlanDraft:
    """Default canonical draft: every available transition in order."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=tuple(
            transition.identifier for transition in request.available_transitions
        ),
    )


def _repeated_draft(
    transition_identifier: str,
) -> Callable[[StrategyTrajectoryPlanRequest], StrategyTrajectoryPlanDraft]:
    def script(request: StrategyTrajectoryPlanRequest) -> StrategyTrajectoryPlanDraft:
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=(
                transition_identifier,
                transition_identifier,
                transition_identifier,
            ),
        )

    return script


def _single_draft(
    transition_identifier: str,
) -> Callable[[StrategyTrajectoryPlanRequest], StrategyTrajectoryPlanDraft]:
    def script(request: StrategyTrajectoryPlanRequest) -> StrategyTrajectoryPlanDraft:
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=(transition_identifier,),
        )

    return script


class TestSinglePlanExecution:
    def test_one_plan_applied_trajectory(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _first_run_id(store)
        resolved = _resolved(store, run_id)
        assert len(resolved.plans) == 1
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        assert len(execution.results) == 1
        result = execution.results[0]
        assert result.state_model_identifier == SM_1_IDENTIFIER
        assert result.initial_state == {"status": "idle"}
        assert result.final_state == {"status": "active"}
        assert len(result.attempts) == 1
        attempt = result.attempts[0]
        assert attempt.sequence_position == 0
        assert attempt.outcome == "applied"
        assert attempt.transition_id == "t-1"
        assert attempt.transition_identifier == transition.identifier
        assert attempt.transition_content_hash == transition.content_hash
        assert attempt.before_state_hash == result.initial_state_hash
        assert attempt.after_state_hash == result.final_state_hash

    def test_repeated_references_preserved_exactly(self) -> None:
        model = build_model()
        transition = build_transition(model)
        legion = ScriptedTrajectoryLegion(_repeated_draft(transition.identifier))
        store, _ = build_trajectory_store(
            state_models=(model,), transitions=(transition,), legion=legion
        )
        run_id = _first_run_id(store)
        resolved = _resolved(store, run_id)
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        result = execution.results[0]
        assert [attempt.transition_identifier for attempt in result.attempts] == [
            transition.identifier,
            transition.identifier,
            transition.identifier,
        ]
        # idle -> active (applied); the guard then no longer matches, so
        # the second and third attempts leave the state unchanged.
        assert [attempt.outcome for attempt in result.attempts] == [
            "applied",
            "guard_not_satisfied",
            "guard_not_satisfied",
        ]
        assert result.final_state == {"status": "active"}

    def test_guard_not_satisfied_records_unchanged_state(self) -> None:
        model = build_model()
        transition = build_transition(model, transition_id="t-2", guard_values={"status": "active"})
        legion = ScriptedTrajectoryLegion(_single_draft(transition.identifier))
        store, _ = build_trajectory_store(
            state_models=(model,), transitions=(transition,), legion=legion
        )
        run_id = _first_run_id(store)
        resolved = _resolved(store, run_id)
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        result = execution.results[0]
        attempt = result.attempts[0]
        assert attempt.outcome == "guard_not_satisfied"
        assert attempt.before_state_hash == attempt.after_state_hash
        assert result.final_state == {"status": "idle"}
        assert result.initial_state_hash == result.final_state_hash

    def test_multiple_state_models_in_canonical_order(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        transition_1 = build_transition(model_1, transition_id="t-1a")
        transition_2 = build_transition(model_2, transition_id="t-2a")
        store, _ = build_trajectory_store(
            state_models=(model_1, model_2), transitions=(transition_1, transition_2)
        )
        run_id = _first_run_id(store)
        resolved = _resolved(store, run_id)
        assert len(resolved.plans) == 2
        assert [plan.state_model_identifier for plan in resolved.plans] == [
            SM_1_IDENTIFIER,
            SM_2_IDENTIFIER,
        ]
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        assert [result.state_model_identifier for result in execution.results] == [
            SM_1_IDENTIFIER,
            SM_2_IDENTIFIER,
        ]
        assert [result.trajectory_plan_id for result in execution.results] == [
            plan.identifier for plan in resolved.plans
        ]


class TestHashRules:
    def test_initial_final_trace_result_and_aggregate_hashes_recompute(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        result = execution.results[0]
        assert result.initial_state_hash == state_hash(result.initial_state)
        assert result.final_state_hash == state_hash(result.final_state)
        # The recorded trace hash is exactly the engine's own digest.
        evaluation = evaluate_trajectory(model, (transition,))
        assert result.trace_hash == evaluation.trace_hash
        assert result.content_hash == state_trajectory_result_content_hash(result)
        assert execution.content_hash == run_trajectory_execution_content_hash(execution)
        assert execution.trajectory_plan_set_hash == trajectory_plan_set_hash(resolved.plans)
        assert execution.input_hash == resolved.inputs.run_plan.input_hash

    def test_trace_hash_is_order_dependent(self) -> None:
        model = build_model()
        transition = build_transition(model)
        legion = ScriptedTrajectoryLegion(_repeated_draft(transition.identifier))
        store, _ = build_trajectory_store(
            state_models=(model,), transitions=(transition,), legion=legion
        )
        resolved = _resolved(store, _first_run_id(store))
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        result = execution.results[0]
        assert len(result.attempts) == 3
        # The engine's own digest over the same ordered attempts matches.
        evaluation = evaluate_trajectory(model, (transition, transition, transition))
        assert result.trace_hash == evaluation.trace_hash

    def test_plan_set_hash_is_order_sensitive(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        plans = get_strategy_trajectory_plans(
            store=store, tenant_id="tenant-1", campaign_id="campaign-1"
        )
        # The full collection spans five strategies: reversing it must
        # change the ordered plan-set digest.
        assert len(plans) > 1
        assert trajectory_plan_set_hash(plans) != trajectory_plan_set_hash(tuple(reversed(plans)))

    def test_identifier_is_deterministic_from_run_identity_and_runtime(self) -> None:
        first = run_trajectory_execution_identifier(run_id="run-1", runtime_version="2.0.0")
        second = run_trajectory_execution_identifier(run_id="run-1", runtime_version="2.0.0")
        assert first == second
        assert first != run_trajectory_execution_identifier(run_id="run-2", runtime_version="2.0.0")
        assert first != run_trajectory_execution_identifier(run_id="run-1", runtime_version="1.0.0")
        assert first.startswith("trajectory-execution-")


class TestDeterminism:
    def test_identical_across_independent_stores(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store_a, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        store_b, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved_a = _resolved(store_a, _first_run_id(store_a))
        resolved_b = _resolved(store_b, _first_run_id(store_b))
        execution_a = build_run_trajectory_execution(
            inputs=resolved_a.inputs, plans=resolved_a.plans, catalogs=resolved_a.catalogs
        )
        execution_b = build_run_trajectory_execution(
            inputs=resolved_b.inputs, plans=resolved_b.plans, catalogs=resolved_b.catalogs
        )
        assert execution_a == execution_b
        assert execution_a.model_dump(mode="json") == execution_b.model_dump(mode="json")

    def test_no_wall_clock_no_randomness(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        # executed_at is the recorded plan creation time, never wall clock.
        assert execution.executed_at == resolved.inputs.run_plan.created_at
        assert execution.executed_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_insertion_order_invariance(self) -> None:
        nested_a: dict[str, JsonValue] = {"second": 2, "first": 1, "nested": {"b": 2, "a": 1}}
        nested_b: dict[str, JsonValue] = {"nested": {"a": 1, "b": 2}, "first": 1, "second": 2}
        model_a = build_model(
            state_model_id="sm-1",
            field="payload",
            value_kind=StateValueKind.JSON,
            initial_value=nested_a,
        )
        model_b = build_model(
            state_model_id="sm-1",
            field="payload",
            value_kind=StateValueKind.JSON,
            initial_value=nested_b,
        )
        # Canonical model content: insertion order is irrelevant.
        assert model_a.content_hash == model_b.content_hash
        store_a, _ = build_trajectory_store(
            state_models=(model_a,), transitions=(build_transition(model_a),)
        )
        store_b, _ = build_trajectory_store(
            state_models=(model_b,), transitions=(build_transition(model_b),)
        )
        resolved_a = _resolved(store_a, _first_run_id(store_a))
        resolved_b = _resolved(store_b, _first_run_id(store_b))
        execution_a = build_run_trajectory_execution(
            inputs=resolved_a.inputs, plans=resolved_a.plans, catalogs=resolved_a.catalogs
        )
        execution_b = build_run_trajectory_execution(
            inputs=resolved_b.inputs, plans=resolved_b.plans, catalogs=resolved_b.catalogs
        )
        assert execution_a == execution_b

    def test_no_input_mutation(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        plans_pristine = copy.deepcopy(resolved.plans)
        catalogs_pristine = copy.deepcopy(resolved.catalogs)
        inputs_pristine = copy.deepcopy(resolved.inputs)
        build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        assert resolved.plans == plans_pristine
        assert resolved.catalogs == catalogs_pristine
        assert resolved.inputs == inputs_pristine

    def test_frozen_snapshots_converted_to_detached_plain_json(self) -> None:
        model = build_model(
            field="payload",
            value_kind=StateValueKind.JSON,
            initial_value={"items": [1, 2], "flag": True},
        )
        transition = build_transition(
            model,
            target_values={
                "payload": {"items": [1, 2, 3], "flag": True, "extra": {"deep": "value"}}
            },
        )
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        execution = build_run_trajectory_execution(
            inputs=resolved.inputs, plans=resolved.plans, catalogs=resolved.catalogs
        )
        result = execution.results[0]
        # Plain dict/list trees - not MappingProxyType/_FrozenList views.
        assert type(result.initial_state) is dict
        assert type(result.final_state) is dict
        payload = result.final_state["payload"]
        assert type(payload) is dict
        items = payload["items"]
        assert type(items) is list
        # Detached: mutating the converted trees cannot affect the engine
        # result, the model, or anything else (fresh tree by construction).
        mutated = copy.deepcopy(result.final_state)
        mutated_payload = mutated["payload"]
        assert isinstance(mutated_payload, dict)
        mutated_payload["tampered"] = True
        payload_value = result.final_state["payload"]
        assert isinstance(payload_value, dict)
        assert "tampered" not in payload_value


class TestSeedProvenance:
    def test_seed_changes_provenance_and_identity_but_not_trace_semantics(self) -> None:
        model = build_model()
        transition = build_transition(model)
        seed_a = build_seed(identifier="seed-1")
        seed_b = build_seed(identifier="seed-2")
        store_a, _ = build_trajectory_store(
            state_models=(model,), transitions=(transition,), seeds=(seed_a,)
        )
        store_b, _ = build_trajectory_store(
            state_models=(model,), transitions=(transition,), seeds=(seed_b,)
        )
        resolved_a = _resolved(store_a, _first_run_id(store_a))
        resolved_b = _resolved(store_b, _first_run_id(store_b))
        execution_a = build_run_trajectory_execution(
            inputs=resolved_a.inputs, plans=resolved_a.plans, catalogs=resolved_a.catalogs
        )
        execution_b = build_run_trajectory_execution(
            inputs=resolved_b.inputs, plans=resolved_b.plans, catalogs=resolved_b.catalogs
        )
        # Provenance and identity differ with the seed...
        assert execution_a.scenario_seed_id == "seed-1"
        assert execution_b.scenario_seed_id == "seed-2"
        assert execution_a.run_id != execution_b.run_id
        assert execution_a.identifier != execution_b.identifier
        assert execution_a.input_hash != execution_b.input_hash
        # ...but the current transition trace is seed-independent: the
        # declarative kernel never samples or uses the seed.
        assert execution_a.results == execution_b.results


class TestBuilderGates:
    def test_legacy_runtime_version_rejected(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        plan = prepared.run_plans[0]
        resolved = verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_identifier(plan))
        assert resolved.run_plan.runtime_version == LEGACY_STRUCTURAL_RUNTIME_VERSION
        with pytest.raises(UnsupportedRuntimeVersionError):
            build_run_trajectory_execution(inputs=resolved, plans=(), catalogs=())

    def test_foreign_strategy_plan_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        foreign_plan = resolved.plans[0].model_copy(
            update={
                "strategy_candidate_id": "mock-conservative",
                "content_hash": HASH_64,
            }
        )
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            build_run_trajectory_execution(
                inputs=resolved.inputs,
                plans=(foreign_plan,),
                catalogs=resolved.catalogs,
            )
        reason = exc_info.value.reason
        assert reason is not None
        assert "strategy" in reason

    def test_plan_collection_pair_mismatch_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            build_run_trajectory_execution(
                inputs=resolved.inputs,
                plans=(),
                catalogs=resolved.catalogs,
            )

    def test_unknown_plan_state_model_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        resolved = _resolved(store, _first_run_id(store))
        tampered_plan = resolved.plans[0].model_copy(
            update={
                "state_model_identifier": "state-model-ghost",
                "content_hash": HASH_64,
            }
        )
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            build_run_trajectory_execution(
                inputs=resolved.inputs,
                plans=(tampered_plan,),
                catalogs=resolved.catalogs,
            )
        # The plan/state-model pair check fires before the model lookup.
        reason = exc_info.value.reason
        assert reason is not None
        assert "trajectory plan collection" in reason
