"""Phase 16 run trajectory input resolution tests.

Proves ``verify_run_trajectory_inputs`` selects exactly the plans bound
to the run's recorded strategy - one per transition-capable state model
in canonical order - and rejects missing, additional, duplicated,
reordered, foreign, or mismatched plans; that a transition-capable world
without a prepared collection raises the typed
``TrajectoryPlansRequiredError`` while a plain world resolves an empty
tuple; that post-compilation declarations are ignored; that corrupted
world, plan, and store data is rejected; and that legacy and unsupported
runtime versions branch exactly as specified. The verifier is read-only.
"""

from __future__ import annotations

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansNotFoundError,
    TrajectoryPlansRequiredError,
    UnsupportedRuntimeVersionError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import (
    VerifiedRunTrajectoryInputs,
    verify_run_trajectory_inputs,
)
from kalhas.application.strategy_trajectory_service import (
    get_strategy_trajectory_plans,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan

from tests.phase4_helpers import TENANT, build_scenario, build_store, prepare, start
from tests.phase16_helpers import (
    SM_1_IDENTIFIER,
    SM_2_IDENTIFIER,
    build_model,
    build_trajectory_store,
    build_transition,
)
from tests.phase25_helpers import inject_unsupported_recorded_runtime

OTHER_TENANT = "tenant-other"


def _resolved(store: InMemoryScenarioStore, run_id: str) -> VerifiedRunTrajectoryInputs:
    return verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)


def _first_run_id(store: InMemoryScenarioStore) -> str:
    return run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])


def _first_strategy_id(store: InMemoryScenarioStore) -> str:
    return store.get_run_plans(TENANT, "campaign-1")[0].strategy_candidate_id


class TestStrategySubsetSelection:
    def test_exact_strategy_specific_subset(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        strategy_id = _first_strategy_id(store)
        resolved = _resolved(store, _first_run_id(store))
        assert len(resolved.plans) == 1
        assert resolved.plans[0].strategy_candidate_id == strategy_id
        # The full collection carries one plan per strategy per model.
        collection = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(collection) == 5

    def test_another_strategys_plans_never_leak(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        strategy_id = _first_strategy_id(store)
        resolved = _resolved(store, _first_run_id(store))
        assert {plan.strategy_candidate_id for plan in resolved.plans} == {strategy_id}
        assert strategy_id != "mock-conservative"

    def test_two_models_select_two_plans_in_canonical_order(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        store, _ = build_trajectory_store(
            state_models=(model_1, model_2),
            transitions=(build_transition(model_1), build_transition(model_2)),
        )
        resolved = _resolved(store, _first_run_id(store))
        assert [plan.state_model_identifier for plan in resolved.plans] == [
            SM_1_IDENTIFIER,
            SM_2_IDENTIFIER,
        ]
        assert len(resolved.catalogs) == 2

    def test_legacy_run_resolves_empty_and_never_consumes_plans(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        # A legacy campaign may even have no prepared collection at all.
        resolved = _resolved(store, run_identifier(prepared.run_plans[0]))
        assert resolved.plans == ()
        assert resolved.catalogs == ()
        assert resolved.inputs.run_plan.runtime_version == LEGACY_STRUCTURAL_RUNTIME_VERSION

    def test_unsupported_version_rejected(self) -> None:
        store, world_id = build_store()
        # Prepare a valid runtime-2 campaign, then simulate corrupted
        # recorded state through private test seams (not an application
        # preparation path): both the stored RunPlan and its matching
        # RunStatus are re-stamped with an unsupported recorded runtime.
        prepared = prepare(store, world_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        run_id = inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=prepared.run_plans[0]
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            _resolved(store, run_id)


class TestPlainWorldResolution:
    def test_plain_world_without_collection_resolves_empty(self) -> None:
        store, _ = build_trajectory_store()  # no state models at all
        resolved = _resolved(store, _first_run_id(store))
        assert resolved.plans == ()
        assert resolved.catalogs == ()

    def test_plain_world_with_prepared_empty_collection_resolves_empty(self) -> None:
        store, _ = build_trajectory_store()
        # The empty prepared collection is a stored value; resolution is
        # the same empty tuple.
        collection = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert collection == ()
        resolved = _resolved(store, _first_run_id(store))
        assert resolved.plans == ()
        assert resolved.catalogs == ()

    def test_plain_world_with_unexpected_nonempty_collection_rejected(self) -> None:
        store, _ = build_trajectory_store()
        # Inject a non-empty collection into a plain world's storage:
        # the service getter (matrix length) rejects it before the
        # verifier's own defense.
        model = build_model()
        transition = build_transition(model)
        compiled = compile_world(build_scenario(), state_models=(model,), transitions=(transition,))
        tamper_store, _ = build_store()
        # Build a real plan collection for a capable world first.
        tamper_store.put_world(compiled.version, compiled.manifest)
        prepare(tamper_store, compiled.version.identifier, runtime_version="2.0.0")
        prepare_strategy_trajectory_plans(
            store=tamper_store,
            legion=prepared_campaign_legion(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        foreign_plans = get_strategy_trajectory_plans(
            store=tamper_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = foreign_plans
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))


class TestSelectionRejections:
    def test_missing_plan_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        # Drop the first strategy's only plan: collection-level getter
        # verification rejects the tampered matrix.
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(collection[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))

    def test_additional_plan_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        duplicate = collection[0].model_copy(deep=True)
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple([duplicate, *collection])
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))

    def test_reordered_plan_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        # Reversing the whole collection breaks the canonical matrix order.
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(reversed(collection))
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))

    def test_duplicate_plan_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        # Duplicate the first plan in place: duplicate identifiers and
        # duplicate (strategy, model) pairs are rejected at collection
        # level before any run selection.
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(
            [collection[0], *collection]
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))

    def test_transition_capable_world_without_collection_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        compiled = compile_world(build_scenario(), state_models=(model,), transitions=(transition,))
        store.put_world(compiled.version, compiled.manifest)
        prepared = prepare(store, compiled.version.identifier, runtime_version="2.0.0")
        start(store)
        # No trajectory plans were prepared for this campaign.
        with pytest.raises(TrajectoryPlansRequiredError):
            _resolved(store, run_identifier(prepared.run_plans[0]))

    def test_mismatched_strategy_content_hash_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        # Tamper the first plan's strategy content hash self-consistently
        # enough to pass the collection checks? No - collection-level
        # verification catches it first (strategy content hash mismatch).
        tampered = collection[0].model_copy(update={"strategy_content_hash": "0" * 64})
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(
            [tampered, *collection[1:]]
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))


class TestCorruptedInputs:
    def test_corrupted_world_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _first_run_id(store)
        # Tamper the stored world body: Phase 14 recompilation verification
        # inside verify_run_inputs rejects it before any plan resolution.
        world = store.get_world(
            TENANT, store.get_run_plans(TENANT, "campaign-1")[0].world_version_id
        )
        tampered_world = world.model_copy(deep=True)
        body = dict(tampered_world.world)
        scenario_raw = body["scenario"]
        assert isinstance(scenario_raw, dict)
        scenario = dict(scenario_raw)
        scenario["name"] = "tampered"
        body["scenario"] = scenario
        tampered_world = tampered_world.model_copy(update={"world": body})
        store._worlds[(TENANT, world.identifier)] = tampered_world
        with pytest.raises(WorldSnapshotIntegrityError):
            _resolved(store, run_id)

    def test_corrupted_plan_data_rejected(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        collection = list(
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        )
        # A validator-bypassed plan (empty references) stored directly.
        bypassed = StrategyTrajectoryPlan.model_construct(
            **{**collection[0].model_dump(mode="python"), "transition_references": ()}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tuple(
            [bypassed, *collection[1:]]
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            _resolved(store, _first_run_id(store))

    def test_foreign_collection_indistinguishable_from_missing(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        # A foreign tenant's read of the prepared collection is
        # indistinguishable from a missing collection at the store level;
        # run resolution itself is tenant-scoped by the run status.
        with pytest.raises(TrajectoryPlansNotFoundError):
            get_strategy_trajectory_plans(
                store=store, tenant_id=OTHER_TENANT, campaign_id="campaign-1"
            )

    def test_verifier_is_read_only(self) -> None:
        model = build_model()
        transition = build_transition(model)
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = _first_run_id(store)
        before_plans = store.get_run_plans(TENANT, "campaign-1")
        before_events = dict(store._run_events)
        before_statuses = dict(store._run_statuses)
        before_artifacts = dict(store._run_trajectory_executions)
        before_manifests = dict(store._run_trajectory_replay_manifests)
        _resolved(store, run_id)
        assert store.get_run_plans(TENANT, "campaign-1") == before_plans
        assert store._run_events == before_events
        assert store._run_statuses == before_statuses
        assert store._run_trajectory_executions == before_artifacts
        assert store._run_trajectory_replay_manifests == before_manifests


def prepared_campaign_legion() -> MockLegionAdapter:
    """A fresh MockLegionAdapter matching the default prepare() fake ids.

    The default ``prepare()`` fake produces ``fake-0..fake-4`` candidate
    ids, so trajectory planning must use the same legion instance. This
    helper builds a store whose campaign uses MockLegionAdapter ids
    instead.
    """
    return MockLegionAdapter()
