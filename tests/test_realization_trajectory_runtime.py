"""Phase 25 pure realization-aware execution builder and integrity verifier tests.

Covers the pure ``build_realization_run_trajectory_execution`` builder
(deterministic byte-identical construction, exact runtime-3 identity and
hashes, realization provenance carried into the artifact, realized
overrides applied before transition zero with authoritative
``initial_state_hash``, models without overrides retaining declared
defaults, per-seed causal variation, exact plan order and transition
repetitions, attempt/reference alignment, empty-catalog artifacts,
zero input mutation, runtime rejection, realization agreement
rejection, ownership/plan/catalog/transition reference rejection, and
invalid realized states rejected before any attempt) and the strict
``verify_realization_run_trajectory_execution_record`` verifier (accepts
correct records; rejects wrong objects, validator-bypassed fields,
tampering of every aggregate provenance field, realization tampering,
result count/order/identity tampering, self-consistently rehashed but
incorrect realized states, hash tampering, attempt count/position/
reference/state-chain tampering, and non-finite state content; never
mutates or repairs; public messages never leak values). Boundary checks
prove the new modules never import or use the store, LEGION/NEXUS,
random/time/network/filesystem, that runtime-2 modules remain
source-unchanged, and that realization_identity stays cycle-free.
"""

from __future__ import annotations

import copy
import inspect
import subprocess
import sys
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_errors import (
    StateValidationError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import VerifiedRunInputs
from kalhas.application.realization_campaign_service import (
    prepare_realization_campaign,
)
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_execution_content_hash,
    realization_run_trajectory_execution_identifier,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_execution_record,
)
from kalhas.application.realization_trajectory_runtime import (
    build_realization_run_trajectory_execution,
    realized_initial_state,
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.run_trajectory_inputs import (
    VerifiedRunTrajectoryInputs,
    verify_run_trajectory_inputs,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.trajectory_integrity import _trace_hash
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel, StateValueKind
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world_realization import (
    RealizedStateFieldValue,
    WorldRealization,
)

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed
from tests.phase20_helpers import BOUND_AT, DECLARED_AT
from tests.phase24_helpers import build_uncertainty_store, declare_model, state_field
from tests.phase25_helpers import level_binding, runtime_three_store


def _declare_transition(
    store: InMemoryScenarioStore,
    model: DomainStateModel,
    *,
    transition_id: str,
    guard_values: dict[str, JsonValue],
    target_values: dict[str, JsonValue],
) -> DomainStateTransition:
    """Declare one transition of the model through the store seam."""
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=model.scenario_id,
            manifest_id=model.manifest_id,
            state_model_id=model.state_model_id,
            transition_id=transition_id,
        ),
        tenant_id=model.tenant_id,
        scenario_id=model.scenario_id,
        binding_id=model.binding_id,
        manifest_id=model.manifest_id,
        pack_id=model.pack_id,
        pack_version=model.pack_version,
        manifest_content_hash=model.manifest_content_hash,
        state_model_id=model.state_model_id,
        state_model_content_hash=model.content_hash,
        transition_id=transition_id,
        description="Declared state change",
        guard_values=guard_values,
        target_values=target_values,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    return transition


def _transition_world_store(*, level_allowed: tuple[JsonValue, ...] = ()) -> InMemoryScenarioStore:
    """A compiled world embedding two transition-capable models, no campaign.

    sm-1 (manifest-1, level/ratio/status) carries t-1 (guard status idle
    + level 0 -> active) and t-2 (guard status idle + level 1 -> level
    84); sm-2 (manifest-2, mode/off) carries t-3 (off -> on) and has no
    uncertainty binding, so its realized state must be its declared
    defaults.
    """
    store = build_uncertainty_store(level_allowed=level_allowed)
    declare_model(store, bindings=(level_binding(),))
    sm_1 = store.list_domain_state_models(TENANT, "scenario-1")[0]
    _declare_transition(
        store,
        sm_1,
        transition_id="t-1",
        guard_values={"status": "idle", "level": 0},
        target_values={"status": "active"},
    )
    _declare_transition(
        store,
        sm_1,
        transition_id="t-2",
        guard_values={"status": "idle", "level": 1},
        target_values={"status": "active", "level": 84},
    )
    register_manifest(
        store,
        tenant_id=TENANT,
        identifier="manifest-2",
        pack_id="pack-2",
        name="Second generic reference pack",
        pack_version="1.2.3",
        description="Declarative pack metadata only",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-2",
                description="Declared capability",
                input_ids=("in-2",),
                output_ids=("out-2",),
            ),
        ),
        schema_metadata={},
        created_at=NOW,
        metadata={},
    )
    bind_manifest(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-2",
        bound_at=BOUND_AT,
    )
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-2",
        state_model_id="sm-2",
        state_fields=(state_field("mode", StateValueKind.STRING, "off"),),
        declared_at=DECLARED_AT,
    )
    sm_2 = store.list_domain_state_models(TENANT, "scenario-1")[1]
    _declare_transition(
        store,
        sm_2,
        transition_id="t-3",
        guard_values={"mode": "off"},
        target_values={"mode": "on"},
    )
    MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    return store


class _RepeatingLegion(MockLegionAdapter):
    """Proposes [t-1, t-1, t-2] for sm-1 plans and the canonical draft otherwise."""

    def __init__(self, sequence: tuple[str, str, str]) -> None:
        super().__init__()
        self._sequence = sequence

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        if request.state_model.state_model_id == "sm-1":
            by_logical = {
                transition.transition_id: transition.identifier
                for transition in request.available_transitions
            }
            return StrategyTrajectoryPlanDraft(
                request_id=request.identifier,
                ordered_transition_identifiers=tuple(
                    by_logical[logical_id] for logical_id in self._sequence
                ),
            )
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=tuple(
                transition.identifier for transition in request.available_transitions
            ),
        )


def _prepare_runtime_three_campaign(
    store: InMemoryScenarioStore,
    *,
    seeds: tuple[ScenarioSeed, ScenarioSeed],
    repeating: bool = False,
) -> None:
    world = next(iter(store._worlds.values()))
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=world.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three trajectory campaign",
        seed_ensemble=seeds,
        created_at=NOW,
    )
    legion: Any = _RepeatingLegion(("t-1", "t-1", "t-2")) if repeating else MockLegionAdapter()
    prepare_strategy_trajectory_plans(
        store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
    )


def _differing_seed_store() -> tuple[InMemoryScenarioStore, str, str]:
    """A prepared store whose two seeds realize different level values."""
    store = _transition_world_store()
    world = next(iter(store._worlds.values()))
    catalog = extract_world_catalog(world)
    levels: dict[str, JsonValue] = {}
    for index in range(1, 25):
        seed = build_seed(identifier=f"seed-{index}")
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=NOW,
        )
        for override in realization.realized_initial_state_overrides:
            if override.state_field_id == "level":
                levels[seed.identifier] = override.value
    selected: tuple[ScenarioSeed, ScenarioSeed] | None = None
    for first, first_level in levels.items():
        for second, second_level in levels.items():
            if first != second and first_level != second_level:
                selected = (build_seed(identifier=first), build_seed(identifier=second))
                break
        if selected is not None:
            break
    assert selected is not None, "no two candidate seeds realized differing levels"
    _prepare_runtime_three_campaign(store, seeds=selected)
    return store, selected[0].identifier, selected[1].identifier


def _fixed_seed_store(
    *, repeating: bool = False, level_allowed: tuple[JsonValue, ...] = ()
) -> InMemoryScenarioStore:
    store = _transition_world_store(level_allowed=level_allowed)
    _prepare_runtime_three_campaign(
        store,
        seeds=(build_seed(identifier="seed-a"), build_seed(identifier="seed-b")),
        repeating=repeating,
    )
    return store


def _verified_run(store: InMemoryScenarioStore, seed_id: str) -> VerifiedRunTrajectoryInputs:
    """Verified trajectory inputs of the first strategy's run for one seed."""
    plans = store.get_run_plans(TENANT, "campaign-1")
    plan = next(p for p in plans if p.scenario_seed_id == seed_id)
    return verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_identifier(plan))


def _realization(verified: VerifiedRunTrajectoryInputs) -> WorldRealization:
    """The verified runtime-3 realization, narrowed from the optional slot."""
    assert verified.realization is not None
    return verified.realization


def _built(store: InMemoryScenarioStore, seed_id: str) -> RealizationRunTrajectoryExecution:
    verified = _verified_run(store, seed_id)
    return build_realization_run_trajectory_execution(
        inputs=verified.inputs,
        plans=verified.plans,
        catalogs=verified.catalogs,
        realization=_realization(verified),
    )


def _expected_final_state(initial_state: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """The causal expected final state under the fixture's transitions."""
    status = initial_state["status"]
    level = initial_state["level"]
    if status == "idle" and level == 0:
        return {**initial_state, "status": "active"}
    if status == "idle" and level == 1:
        return {**initial_state, "status": "active", "level": 84}
    return dict(initial_state)


def _rehashed_result(result: RealizedStateTrajectoryResult) -> RealizedStateTrajectoryResult:
    """Recompute a result's content hash over its current (tampered) content."""
    return result.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(result)}
    )


def _rehashed_execution(
    execution: RealizationRunTrajectoryExecution,
    results: tuple[RealizedStateTrajectoryResult, ...],
) -> RealizationRunTrajectoryExecution:
    """Recompute the aggregate hash over a (tampered) result tuple."""
    return execution.model_copy(
        update={
            "results": results,
            "content_hash": realization_run_trajectory_execution_content_hash(
                execution.model_copy(update={"results": results})
            ),
        }
    )


class TestBuilder:
    def test_deterministic_byte_identical_repeated_construction(self) -> None:
        store = _fixed_seed_store()
        first = _built(store, "seed-a")
        second = _built(store, "seed-a")
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_exact_identity_and_content_hashes(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        run_id = verified.inputs.status.run_id
        assert execution.identifier == realization_run_trajectory_execution_identifier(
            run_id=run_id, runtime_version="3.0.0"
        )
        assert execution.content_hash == realization_run_trajectory_execution_content_hash(
            execution
        )
        assert execution.runtime_version == "3.0.0"
        assert execution.executed_at == verified.inputs.run_plan.created_at
        assert execution.input_hash == verified.inputs.run_plan.input_hash

    def test_realization_carried_into_execution(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        assert execution.world_realization_id == _realization(verified).identifier
        assert execution.world_realization_content_hash == _realization(verified).content_hash

    def test_realized_override_applied_before_transition_zero(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        realized_level = next(
            override.value
            for override in _realization(verified).realized_initial_state_overrides
            if override.state_field_id == "level"
        )
        result = execution.results[0]
        assert result.initial_state["level"] == realized_level
        assert result.initial_state_hash == state_hash(result.initial_state)
        expected = realized_initial_state(
            state_model=verified.catalogs[0].state_model,
            realization=_realization(verified),
            run_id=verified.inputs.status.run_id,
        )
        assert result.initial_state_hash == state_hash(expected)

    def test_model_without_override_retains_declared_defaults(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        sm_2_result = execution.results[1]
        assert sm_2_result.state_model_id == "sm-2"
        assert sm_2_result.initial_state == {"mode": "off"}
        assert sm_2_result.initial_state_hash == state_hash({"mode": "off"})

    def test_different_seed_realizations_produce_causal_variation(self) -> None:
        store, seed_a_id, seed_b_id = _differing_seed_store()
        execution_a = _built(store, seed_a_id)
        execution_b = _built(store, seed_b_id)
        initial_a = execution_a.results[0].initial_state
        initial_b = execution_b.results[0].initial_state
        assert initial_a["level"] != initial_b["level"]
        assert (
            execution_a.results[0].initial_state_hash != execution_b.results[0].initial_state_hash
        )
        # Guards evaluate against the realized level: the final state is
        # exactly the causal engine output for each realized initial state.
        assert execution_a.results[0].final_state == _expected_final_state(initial_a)
        assert execution_b.results[0].final_state == _expected_final_state(initial_b)
        assert execution_a.results[0].final_state != execution_b.results[0].final_state

    def test_exact_plan_order_and_attempt_alignment(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        assert [result.trajectory_plan_id for result in execution.results] == [
            plan.identifier for plan in verified.plans
        ]
        for result, plan in zip(execution.results, verified.plans, strict=True):
            assert len(result.attempts) == len(plan.transition_references)
            for attempt, reference in zip(result.attempts, plan.transition_references, strict=True):
                assert attempt.sequence_position == reference.sequence_position
                assert attempt.transition_id == reference.transition_id
                assert attempt.transition_content_hash == reference.transition_content_hash

    def test_transition_repetitions_preserved_exactly(self) -> None:
        store = _fixed_seed_store(repeating=True)
        execution = _built(store, "seed-a")
        sm_1_result = execution.results[0]
        assert [attempt.transition_id for attempt in sm_1_result.attempts] == [
            "t-1",
            "t-1",
            "t-2",
        ]
        assert [attempt.sequence_position for attempt in sm_1_result.attempts] == [0, 1, 2]

    def test_result_and_aggregate_hashes_recompute(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        for result in execution.results:
            assert result.content_hash == realized_state_trajectory_result_content_hash(result)
            assert result.trace_hash is not None

    def test_empty_catalogs_produce_empty_results(self) -> None:
        store = runtime_three_store()
        verified = _verified_run(store, "seed-1")
        assert verified.plans == ()
        assert verified.catalogs == ()
        execution = build_realization_run_trajectory_execution(
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )
        assert execution.results == ()
        assert execution.content_hash == realization_run_trajectory_execution_content_hash(
            execution
        )

    def test_no_input_mutation(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        plans_before = copy.deepcopy(verified.plans)
        catalogs_before = copy.deepcopy(verified.catalogs)
        realization_before = copy.deepcopy(verified.realization)
        inputs_before = copy.deepcopy(verified.inputs)
        build_realization_run_trajectory_execution(
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )
        assert verified.plans == plans_before
        assert verified.catalogs == catalogs_before
        assert verified.realization == realization_before
        assert verified.inputs == inputs_before

    @pytest.mark.parametrize("runtime", ["1.0.0", "2.0.0", "9.9.9"])
    def test_unsupported_recorded_runtime_rejected(self, runtime: str) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        inputs = VerifiedRunInputs(
            run_plan=verified.inputs.run_plan.model_copy(update={"runtime_version": runtime}),
            world=verified.inputs.world,
            strategy=verified.inputs.strategy,
            seed=verified.inputs.seed,
            status=verified.inputs.status,
            manifest=verified.inputs.manifest,
            realization=_realization(verified),
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            build_realization_run_trajectory_execution(
                inputs=inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_missing_inputs_realization_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        inputs = VerifiedRunInputs(
            run_plan=verified.inputs.run_plan,
            world=verified.inputs.world,
            strategy=verified.inputs.strategy,
            seed=verified.inputs.seed,
            status=verified.inputs.status,
            manifest=verified.inputs.manifest,
            realization=None,
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_differing_inputs_realization_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        other = _realization(verified).model_copy(update={"identifier": "realization-other"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=other,
            )

    def test_wrong_realization_ownership_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        foreign = _realization(verified).model_copy(update={"tenant_id": "tenant-other"})
        inputs = VerifiedRunInputs(
            run_plan=verified.inputs.run_plan,
            world=verified.inputs.world,
            strategy=verified.inputs.strategy,
            seed=verified.inputs.seed,
            status=verified.inputs.status,
            manifest=verified.inputs.manifest,
            realization=foreign,
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=foreign,
            )

    def test_wrong_plans_for_strategy_rejected(self) -> None:
        store = _fixed_seed_store()
        verified_a = _verified_run(store, "seed-a")
        plans = store.get_run_plans(TENANT, "campaign-1")
        other_strategy_plan = next(
            p
            for p in plans
            if p.strategy_candidate_id == "mock-conservative" and p.scenario_seed_id == "seed-a"
        )
        other = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=run_identifier(other_strategy_plan)
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=verified_a.inputs,
                plans=other.plans,
                catalogs=verified_a.catalogs,
                realization=_realization(verified_a),
            )

    def test_wrong_catalogs_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=(),
                realization=_realization(verified),
            )

    def test_unknown_transition_reference_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        catalog = verified.catalogs[0]
        truncated = ModelTrajectoryCatalog(
            state_model=catalog.state_model, transitions=catalog.transitions[:1]
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=(truncated, verified.catalogs[1]),
                realization=_realization(verified),
            )

    def test_invalid_realized_state_rejected_before_any_attempt(self) -> None:
        # allowed values cover every sampled and targeted level (uniform
        # 0..3, t-2 target 84) so the fixture prepares cleanly, while 999
        # remains outside the allowed set.
        store = _fixed_seed_store(level_allowed=(0, 1, 2, 3, 84))
        verified = _verified_run(store, "seed-a")
        tampered_overrides = tuple(
            RealizedStateFieldValue(
                state_model_identifier=override.state_model_identifier,
                state_field_id=override.state_field_id,
                value=999,
            )
            if override.state_field_id == "level"
            else override
            for override in _realization(verified).realized_initial_state_overrides
        )
        tampered = _realization(verified).model_copy(
            update={"realized_initial_state_overrides": tampered_overrides}
        )
        inputs = VerifiedRunInputs(
            run_plan=verified.inputs.run_plan,
            world=verified.inputs.world,
            strategy=verified.inputs.strategy,
            seed=verified.inputs.seed,
            status=verified.inputs.status,
            manifest=verified.inputs.manifest,
            realization=tampered,
        )
        with pytest.raises(StateValidationError):
            build_realization_run_trajectory_execution(
                inputs=inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=tampered,
            )

    def test_duplicate_matching_override_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        first = _realization(verified).realized_initial_state_overrides[0]
        duplicate = RealizedStateFieldValue(
            state_model_identifier=first.state_model_identifier,
            state_field_id=first.state_field_id,
            value=2,
        )
        duplicated = WorldRealization.model_construct(
            identifier=_realization(verified).identifier,
            tenant_id=_realization(verified).tenant_id,
            scenario_id=_realization(verified).scenario_id,
            world_version_id=_realization(verified).world_version_id,
            world_content_hash=_realization(verified).world_content_hash,
            scenario_seed_id=_realization(verified).scenario_seed_id,
            seed_content_hash=_realization(verified).seed_content_hash,
            uncertainty_model_id=_realization(verified).uncertainty_model_id,
            uncertainty_model_content_hash=_realization(verified).uncertainty_model_content_hash,
            sampler_version=_realization(verified).sampler_version,
            quantization_policy=_realization(verified).quantization_policy,
            quantization_fraction_bits=_realization(verified).quantization_fraction_bits,
            sampled_values=(),
            realized_initial_state_overrides=(
                _realization(verified).realized_initial_state_overrides + (duplicate,)
            ),
            content_hash=_realization(verified).content_hash,
            realized_at=_realization(verified).realized_at,
        )
        inputs = VerifiedRunInputs(
            run_plan=verified.inputs.run_plan,
            world=verified.inputs.world,
            strategy=verified.inputs.strategy,
            seed=verified.inputs.seed,
            status=verified.inputs.status,
            manifest=verified.inputs.manifest,
            realization=duplicated,
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            build_realization_run_trajectory_execution(
                inputs=inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=duplicated,
            )


class TestVerifier:
    def test_accepts_correct_execution(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        verify_realization_run_trajectory_execution_record(
            execution,
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )  # must not raise

    def test_wrong_object_rejected(self) -> None:
        store = _fixed_seed_store()
        verified = _verified_run(store, "seed-a")
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                object(),  # type: ignore[arg-type]
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_validator_bypassed_fields_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        bypassed_payload = execution.model_dump(mode="python")
        bypassed_payload["runtime_version"] = "2.0.0"
        bypassed = RealizationRunTrajectoryExecution.model_construct(**bypassed_payload)
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                bypassed,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    @pytest.mark.parametrize(
        "field",
        [
            "identifier",
            "tenant_id",
            "run_id",
            "campaign_id",
            "run_plan_id",
            "world_version_id",
            "world_content_hash",
            "strategy_candidate_id",
            "strategy_content_hash",
            "scenario_seed_id",
            "runtime_version",
            "input_hash",
            "trajectory_plan_set_hash",
            "executed_at",
        ],
    )
    def test_every_aggregate_provenance_field_tampering_rejected(self, field: str) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        if field == "executed_at":
            tampered = execution.model_copy(update={"executed_at": NOW.replace(year=2020)})
        else:
            tampered = execution.model_copy(update={field: f"tampered-{field}"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_realization_field_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        for field in ("world_realization_id", "world_realization_content_hash"):
            tampered = execution.model_copy(update={field: "f" * 64})
            with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
                verify_realization_run_trajectory_execution_record(
                    tampered,
                    inputs=verified.inputs,
                    plans=verified.plans,
                    catalogs=verified.catalogs,
                    realization=_realization(verified),
                )

    def test_result_count_and_order_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        dropped = execution.model_copy(update={"results": execution.results[:1]})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                dropped,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )
        swapped = execution.model_copy(
            update={"results": (execution.results[1], execution.results[0])}
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                swapped,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_plan_and_model_identity_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        for field in (
            "trajectory_plan_id",
            "trajectory_plan_content_hash",
            "state_model_identifier",
            "state_model_id",
            "state_model_content_hash",
        ):
            tampered = execution.model_copy(
                update={
                    "results": (result.model_copy(update={field: f"tampered-{field}"}),)
                    + execution.results[1:]
                }
            )
            with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
                verify_realization_run_trajectory_execution_record(
                    tampered,
                    inputs=verified.inputs,
                    plans=verified.plans,
                    catalogs=verified.catalogs,
                    realization=_realization(verified),
                )

    def test_self_consistently_rehashed_wrong_realized_state_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        wrong_state = dict(result.initial_state)
        wrong_state["level"] = 99
        rehashed_result = result.model_copy(
            update={
                "initial_state": wrong_state,
                "initial_state_hash": state_hash(wrong_state),
            }
        )
        rehashed_result = rehashed_result.model_copy(
            update={"content_hash": realized_state_trajectory_result_content_hash(rehashed_result)}
        )
        tampered = execution.model_copy(
            update={
                "results": (rehashed_result,) + execution.results[1:],
                "content_hash": realization_run_trajectory_execution_content_hash(
                    execution.model_copy(
                        update={"results": (rehashed_result,) + execution.results[1:]}
                    )
                ),
            }
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_hash_field_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        for field in ("initial_state_hash", "final_state_hash", "trace_hash", "content_hash"):
            tampered_result = result.model_copy(update={field: "f" * 64})
            tampered = execution.model_copy(
                update={"results": (tampered_result,) + execution.results[1:]}
            )
            with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
                verify_realization_run_trajectory_execution_record(
                    tampered,
                    inputs=verified.inputs,
                    plans=verified.plans,
                    catalogs=verified.catalogs,
                    realization=_realization(verified),
                )
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_attempt_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        attempts = result.attempts

        dropped = result.model_copy(update={"attempts": attempts[:1]})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                execution.model_copy(update={"results": (dropped,) + execution.results[1:]}),
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

        reordered = result.model_copy(update={"attempts": (attempts[1], attempts[0])})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                execution.model_copy(update={"results": (reordered,) + execution.results[1:]}),
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

        wrong_transition = attempts[0].model_copy(update={"transition_id": "t-99"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                execution.model_copy(
                    update={
                        "results": (
                            result.model_copy(
                                update={"attempts": (wrong_transition,) + attempts[1:]}
                            ),
                        )
                        + execution.results[1:]
                    }
                ),
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_self_consistent_attempt_chain_tampering_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        attempts = result.attempts
        # Tamper the state chain and rehash everything consistently except
        # the chain itself: attempt[1].before no longer equals the tampered
        # attempt[0].after.
        broken_chain = (attempts[0].model_copy(update={"after_state_hash": "f" * 64}),) + attempts[
            1:
        ]
        rehashed_result = result.model_copy(update={"attempts": broken_chain})
        rehashed_result = rehashed_result.model_copy(
            update={
                "trace_hash": _trace_hash(broken_chain),
                "content_hash": realized_state_trajectory_result_content_hash(rehashed_result),
            }
        )
        tampered = execution.model_copy(
            update={
                "results": (rehashed_result,) + execution.results[1:],
                "content_hash": realization_run_trajectory_execution_content_hash(
                    execution.model_copy(
                        update={"results": (rehashed_result,) + execution.results[1:]}
                    )
                ),
            }
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_non_finite_state_content_rejected(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        non_finite_state = dict(result.final_state)
        non_finite_state["ratio"] = float("nan")
        tampered_result = result.model_copy(update={"final_state": non_finite_state})
        tampered = execution.model_copy(
            update={"results": (tampered_result,) + execution.results[1:]}
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_never_mutates_or_repairs_the_record(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        snapshot = copy.deepcopy(execution)
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )
        assert tampered == snapshot.model_copy(update={"content_hash": "f" * 64})
        assert execution == snapshot

    def test_alternate_valid_transition_tamper_rejected(self) -> None:
        """Catalog membership alone must never suffice for an attempt.

        Replaces one attempt with another valid transition of the same
        model/catalog that is not the authoritative plan reference at that
        position, then recomputes trace, result, and aggregate hashes so
        every structural hash check is self-consistent.
        """
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        attempts = result.attempts
        # t-2 is a valid transition of the same catalog/model but the
        # authoritative plan reference at position 0 is t-1.
        alternate = verified.catalogs[0].transitions[1]
        assert alternate.transition_id == "t-2"
        swapped = attempts[0].model_copy(
            update={
                "transition_identifier": alternate.identifier,
                "transition_id": alternate.transition_id,
                "transition_content_hash": alternate.content_hash,
            }
        )
        tampered_result = _rehashed_result(
            result.model_copy(
                update={
                    "attempts": (swapped,) + attempts[1:],
                    "trace_hash": _trace_hash((swapped,) + attempts[1:]),
                }
            )
        )
        tampered = _rehashed_execution(execution, (tampered_result,) + execution.results[1:])
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_attempt_count_tamper_rejected(self) -> None:
        """Removing attempts is rejected even when every hash is rehashed."""
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        result = execution.results[0]
        references = verified.plans[0].transition_references
        assert len(references) >= 2

        # Drop the last attempt and rehash everything consistently. The
        # surviving chain stays consistent whenever the dropped attempt
        # was a guard failure (before == after); the count check must
        # reject regardless of which surviving-position checks align.
        dropped = _rehashed_result(
            result.model_copy(
                update={
                    "attempts": result.attempts[:-1],
                    "trace_hash": _trace_hash(result.attempts[:-1]),
                }
            )
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                _rehashed_execution(execution, (dropped,) + execution.results[1:]),
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

        # Drop every attempt of the same non-empty plan.
        empty_attempts = _rehashed_result(
            result.model_copy(update={"attempts": (), "trace_hash": _trace_hash(())})
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_run_trajectory_execution_record(
                _rehashed_execution(execution, (empty_attempts,) + execution.results[1:]),
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )

    def test_repeated_references_accepted_in_exact_order(self) -> None:
        store = _fixed_seed_store(repeating=True)
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        verify_realization_run_trajectory_execution_record(
            execution,
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )  # must not raise

    def test_empty_plan_with_empty_attempts_accepted(self) -> None:
        store = runtime_three_store()
        verified = _verified_run(store, "seed-1")
        execution = build_realization_run_trajectory_execution(
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )
        assert execution.results == ()
        verify_realization_run_trajectory_execution_record(
            execution,
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=_realization(verified),
        )  # must not raise

    def test_public_messages_never_leak_values(self) -> None:
        store = _fixed_seed_store()
        execution = _built(store, "seed-a")
        verified = _verified_run(store, "seed-a")
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError) as exc_info:
            verify_realization_run_trajectory_execution_record(
                tampered,
                inputs=verified.inputs,
                plans=verified.plans,
                catalogs=verified.catalogs,
                realization=_realization(verified),
            )
        message = str(exc_info.value)
        assert "integrity verification" in message
        for leaked in ("level", "84", "idle", "t-1", "0" * 64, "f" * 64):
            assert leaked not in message


class TestBoundaries:
    def test_runtime_modules_have_no_store_or_adapter_imports(self) -> None:
        for module_name in (
            "kalhas.application.realization_trajectory_runtime",
            "kalhas.application.realization_integrity",
        ):
            module = __import__(module_name, fromlist=["*"])
            source = inspect.getsource(module)
            assert "kalhas.adapters" not in source
            assert "in_memory_store" not in source
            assert "InMemoryScenarioStore" not in source
            assert "import random" not in source
            assert "import time" not in source
            assert "time.time(" not in source
            assert "time.perf_counter" not in source
            assert "datetime.now" not in source
            assert "utcnow" not in source
            assert "urllib" not in source
            assert "requests" not in source
            assert "socket" not in source
            assert "open(" not in source

    def test_runtime_two_modules_source_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--exit-code",
                "--",
                "kalhas/application/run_trajectory_runtime.py",
                "kalhas/application/trajectory_integrity.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout

    def test_integrity_verifier_is_replay_free(self) -> None:
        module = __import__("kalhas.application.realization_integrity", fromlist=["*"])
        source = inspect.getsource(module)
        # The verifier never evaluates, replays, or derives states; it
        # imports only the pure state_hash helper from the engine.
        assert "evaluate_trajectory" not in source
        assert "derive_initial_state" not in source

    def test_realization_identity_remains_cycle_free(self) -> None:
        probe = (
            "import sys; "
            "import kalhas.application.realization_identity; "
            "assert 'kalhas.application.input_integrity' not in sys.modules; "
            "print('acyclic')"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "acyclic" in result.stdout
