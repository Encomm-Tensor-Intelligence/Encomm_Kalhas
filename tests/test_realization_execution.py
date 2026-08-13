"""Phase 25 runtime-3 preparation, preflight, and lifecycle execution tests.

Proves the historical ``prepare_campaign`` gate (exactly 1.0.0/2.0.0,
rejection before any store read, LEGION call, or write), the new
``prepare_realization_campaign`` service (exactly 3.0.0, one realization
matrix build, K realizations for K seeds - never K x S - with every
strategy sharing a seed bound to the identical realization content hash,
exact run/status counts and order, derived artifacts never stored, every
stored-vs-embedded uncertainty case failing closed with zero writes, and
sampling/candidate failures writing nothing), the read-only
``preflight_realization_run_plan_matrix`` (deterministic, every expected
run verified, and rejection of missing/additional/reordered/duplicated/
tampered/mixed-runtime matrices), the exactly-once preflight dispatch
inside ``prepare_strategy_trajectory_plans``, and the runtime-3
lifecycle services ``execute_realization_run`` and
``execute_realization_campaign`` (strict recorded-runtime gating,
PLANNED enforcement, exactly-once ``verify_run_trajectory_inputs`` per
trust operation, artifact-absence probing, full in-memory artifact build
before the first lifecycle write, the exact three structural events with
the structural-only event hash, failure atomicity before the write
phase, atomic campaign preflight with zero executions on any failure,
and exact stored-order execution ending in campaign COMPLETE).

Observation extraction, replay, matrices, mock strategy differentiation,
and API routes are deliberately NOT covered here - they belong to later
slices.
"""

from __future__ import annotations

import inspect
import subprocess
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.campaign_service import prepare_campaign
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    CampaignNotRunningError,
    CampaignPreparationError,
    RunInputIntegrityError,
    RunNotFoundError,
    RunNotPlannedError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    preflight_realization_run_plan_matrix,
    prepare_realization_campaign,
)
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionAlreadyExistsError,
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_execution import (
    execute_realization_campaign,
    execute_realization_run,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_execution_record,
)
from kalhas.application.realization_trajectory_runtime import (
    build_realization_run_trajectory_execution,
)
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
    run_realization_input_hash,
)
from kalhas.application.run_trajectory_inputs import (
    VerifiedRunTrajectoryInputs,
    verify_run_trajectory_inputs,
)
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import RunExecution, event_hash
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
)
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationSamplingError,
    WorldUncertaintyModelIntegrityError,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_model_content_hash,
    uncertainty_model_identifier,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.simulation import RunEventKind
from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.world_realization import WorldRealization

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, prepare
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase24_helpers import build_uncertainty_store, declare_model
from tests.phase25_helpers import (
    inject_unsupported_recorded_runtime,
    level_binding,
    runtime_three_execution_store,
    runtime_three_store,
)


class _SpyLegion:
    """LEGION adapter that fails loudly if any boundary call is made."""

    def __init__(self) -> None:
        self.strategy_calls = 0
        self.trajectory_calls = 0

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        self.strategy_calls += 1
        raise AssertionError("LEGION must not be called")

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.trajectory_calls += 1
        raise AssertionError("LEGION must not be called")


def _assert_zero_campaign_writes(store: InMemoryScenarioStore) -> None:
    """Preparation failures before the write phase leave no campaign/run state."""
    with pytest.raises(CampaignNotFoundError):
        store.get_campaign(TENANT, "campaign-1")
    with pytest.raises(CampaignNotFoundError):
        store.get_run_plans(TENANT, "campaign-1")
    with pytest.raises(CampaignNotFoundError):
        store.get_strategy_candidates(TENANT, "campaign-1")
    assert store._operational_activity == {}
    assert store._run_statuses == {}


class TestPrepareCampaignGate:
    def test_accepts_runtime_one_and_two_unchanged(self) -> None:
        for runtime in (LEGACY_STRUCTURAL_RUNTIME_VERSION, TRAJECTORY_RUNTIME_VERSION):
            store = build_observation_store()
            world_version_id = compile_observation_world(store)
            prepared = prepare(
                store,
                world_version_id,
                runtime_version=runtime,
                legion=MockLegionAdapter(),
            )
            assert prepared.campaign.identifier == "campaign-1"
            assert prepared.status.state.value == "compiled"
            assert len(prepared.run_plans) == 5  # 5 strategies x 1 seed
            assert {plan.runtime_version for plan in prepared.run_plans} == {runtime}

    @pytest.mark.parametrize("runtime", ["3.0.0", "9.9.9"])
    def test_rejects_before_store_access_legion_or_writes(self, runtime: str) -> None:
        # The empty store has no scenario: reaching get_scenario would raise
        # ScenarioNotFoundError, so the typed unsupported-runtime error proves
        # the gate runs before any store access.
        store = InMemoryScenarioStore()
        spy = _SpyLegion()
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            prepare_campaign(
                store=store,
                legion=spy,
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id="world-1",
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
                runtime_version=runtime,
            )
        assert exc_info.value.runtime_version == runtime
        assert exc_info.value.operation == "campaign preparation"
        assert spy.strategy_calls == 0
        _assert_zero_campaign_writes(store)


class TestPrepareRealizationCampaign:
    @pytest.mark.parametrize("runtime", ["1.0.0", "2.0.0", "9.9.9"])
    def test_accepts_only_runtime_three(self, runtime: str) -> None:
        store = InMemoryScenarioStore()
        spy = _SpyLegion()
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            prepare_realization_campaign(
                store=store,
                legion=spy,
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id="world-1",
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
                runtime_version=runtime,
            )
        assert exc_info.value.runtime_version == runtime
        assert exc_info.value.operation == "realization campaign preparation"
        assert spy.strategy_calls == 0
        _assert_zero_campaign_writes(store)

    def test_runtime_three_preparation_succeeds(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert campaign.comparison_mode == "identical_conditions"
        assert store.get_campaign_status(TENANT, "campaign-1").state.value == "compiled"
        plans = store.get_run_plans(TENANT, "campaign-1")
        assert len(plans) == 10  # 5 strategies x 2 seeds

    def test_builds_exactly_one_matrix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = 0
        original = build_campaign_world_realization_matrix

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            "kalhas.application.realization_campaign_service."
            "build_campaign_world_realization_matrix",
            counting,
        )
        runtime_three_store()
        assert calls == 1

    def test_k_realizations_never_k_times_s(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        catalog = extract_world_catalog(world)
        matrix = build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        seeds = campaign.seed_ensemble
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        assert len(matrix.realizations) == len(seeds) == 2
        assert len(matrix.realizations) != len(seeds) * len(strategies)
        assert matrix.ordered_scenario_seed_ids == tuple(seed.identifier for seed in seeds)

    def test_same_seed_same_realization_across_strategies(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        catalog = extract_world_catalog(world)
        matrix = build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        realizations_by_seed = {
            realization.scenario_seed_id: realization for realization in matrix.realizations
        }
        plans = store.get_run_plans(TENANT, "campaign-1")
        for plan in plans:
            realization = realizations_by_seed[plan.scenario_seed_id]
            assert plan.input_hash == run_realization_input_hash(
                world_content_hash=world.content_hash,
                strategy=next(
                    candidate
                    for candidate in store.get_strategy_candidates(TENANT, "campaign-1")
                    if candidate.identifier == plan.strategy_candidate_id
                ),
                seed=next(
                    seed
                    for seed in campaign.seed_ensemble
                    if seed.identifier == plan.scenario_seed_id
                ),
                world_realization_content_hash=realization.content_hash,
            )

    def test_run_and_status_order_and_counts_exact(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        plans = store.get_run_plans(TENANT, "campaign-1")
        expected_pairs = [
            (strategy_id, seed.identifier)
            for strategy_id in campaign.strategy_candidate_ids
            for seed in campaign.seed_ensemble
        ]
        assert [(plan.strategy_candidate_id, plan.scenario_seed_id) for plan in plans] == (
            expected_pairs
        )
        for plan in plans:
            status = store.get_run_status(TENANT, run_identifier(plan))
            assert status.state.value == "planned"
            assert status.runtime_version == REALIZATION_TRAJECTORY_RUNTIME_VERSION
            assert status.input_hash == plan.input_hash

    def test_realizations_and_matrix_never_stored(self) -> None:
        store = runtime_three_store()
        assert store._realization_run_trajectory_executions == {}
        assert store._realization_run_trajectory_replay_manifests == {}
        assert store._realization_run_metric_observation_sets == {}
        # The Phase 24 realization matrix has no storage collection at all;
        # re-derivation through the pure builder is the only surface.
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        catalog = extract_world_catalog(world)
        first = build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        second = build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_missing_stored_model_fails_closed_with_zero_writes(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(level_binding(),))
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        del store._world_uncertainty_models[(TENANT, "scenario-1")]
        with pytest.raises(RunInputIntegrityError):
            prepare_realization_campaign(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=compiled.version.identifier,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)

    def test_corrupt_stored_model_keeps_typed_integrity_error(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(level_binding(),))
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        store._world_uncertainty_models[(TENANT, "scenario-1")] = stored.model_copy(
            update={"content_hash": "0" * 64}
        )
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            prepare_realization_campaign(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=compiled.version.identifier,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)

    def test_stored_embedded_mismatch_fails_closed(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(level_binding(),))
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        variant = stored.model_copy(update={"metadata": {"variant": True}})
        variant = variant.model_copy(
            update={
                "content_hash": uncertainty_model_content_hash(variant),
                "identifier": uncertainty_model_identifier(
                    tenant_id=TENANT,
                    scenario_id="scenario-1",
                    scenario_content_hash_value=variant.scenario_content_hash,
                ),
            }
        )
        store._world_uncertainty_models[(TENANT, "scenario-1")] = variant
        with pytest.raises(RunInputIntegrityError):
            prepare_realization_campaign(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=compiled.version.identifier,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)

    def test_stored_model_without_embedded_fails_closed(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        model_source = build_uncertainty_store()
        model = declare_model(model_source, bindings=(level_binding(),))
        store._world_uncertainty_models[(TENANT, "scenario-1")] = model
        with pytest.raises(RunInputIntegrityError):
            prepare_realization_campaign(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=world_version_id,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)

    def test_sampling_failure_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(*args: object, **kwargs: object) -> object:
            raise WorldRealizationSamplingError(TENANT, "scenario-1", reason="boom")

        monkeypatch.setattr(
            "kalhas.application.realization_campaign_service."
            "build_campaign_world_realization_matrix",
            broken,
        )
        store = build_uncertainty_store()
        declare_model(store, bindings=(level_binding(),))
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        with pytest.raises(WorldRealizationSamplingError):
            prepare_realization_campaign(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=compiled.version.identifier,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)

    def test_candidate_validation_failure_writes_nothing(self) -> None:
        class _FewStrategiesLegion:
            def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
                return ()

            def request_trajectory_plan(
                self, request: StrategyTrajectoryPlanRequest
            ) -> StrategyTrajectoryPlanDraft:
                raise AssertionError("LEGION must not be called")

        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        # Reset the campaign-scoped records so this attempt starts from a
        # clean slate (test-only reset; preparation itself never deletes).
        del store._campaigns[(TENANT, "campaign-1")]
        del store._campaign_statuses[(TENANT, "campaign-1")]
        del store._run_plans[(TENANT, "campaign-1")]
        del store._strategy_candidates[(TENANT, "campaign-1")]
        store._run_statuses = {}
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign(TENANT, "campaign-1")
        with pytest.raises(CampaignPreparationError):
            prepare_realization_campaign(
                store=store,
                legion=_FewStrategiesLegion(),
                tenant_id=TENANT,
                scenario_id="scenario-1",
                world_version_id=world.identifier,
                strategy_request=build_request(TENANT),
                campaign_id="campaign-1",
                campaign_name="Rejected campaign",
                seed_ensemble=(build_seed(), build_seed(identifier="seed-2")),
                created_at=NOW,
            )
        _assert_zero_campaign_writes(store)


class TestPreflightRealizationRunPlanMatrix:
    def test_preflight_is_deterministic_and_read_only(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        before_activity = len(store._operational_activity)
        preflight_realization_run_plan_matrix(store, TENANT, campaign, world)
        preflight_realization_run_plan_matrix(store, TENANT, campaign, world)
        assert len(store._operational_activity) == before_activity
        assert store._realization_run_trajectory_executions == {}
        assert store._realization_run_trajectory_replay_manifests == {}
        assert store._realization_run_metric_observation_sets == {}

    def test_preflight_verifies_every_expected_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kalhas.application import input_integrity as input_integrity_module

        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        calls = 0
        original = input_integrity_module.verify_run_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            "kalhas.application.realization_campaign_service.verify_run_inputs", counting
        )
        preflight_realization_run_plan_matrix(store, TENANT, campaign, world)
        assert calls == 10  # 5 strategies x 2 seeds

    def test_rejects_missing_plan_matrix(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        del store._run_plans[(TENANT, "campaign-1")]
        # An absent collection surfaces the store's typed not-found error;
        # an empty stored tuple surfaces the matrix-level integrity error.
        with pytest.raises(CampaignNotFoundError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)
        store._run_plans[(TENANT, "campaign-1")] = ()
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_additional_plan(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = plans + (plans[0],)
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_reordered_plans(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        plans = list(store.get_run_plans(TENANT, "campaign-1"))
        plans[0], plans[1] = plans[1], plans[0]
        store._run_plans[(TENANT, "campaign-1")] = tuple(plans)
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_duplicated_plan(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = (plans[0],) * 2 + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_tampered_plan(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        plans = store.get_run_plans(TENANT, "campaign-1")
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            tampered if plan.identifier == plans[0].identifier else plan for plan in plans
        )
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_mixed_runtime_matrix(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # A runtime-2 plan in a non-leading position keeps the recorded
        # version gate at 3.0.0 and fails the exact matrix equality.
        foreign = plans[-1].model_copy(update={"runtime_version": TRAJECTORY_RUNTIME_VERSION})
        store._run_plans[(TENANT, "campaign-1")] = plans[:-1] + (foreign,)
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)
        # A runtime-2 plan in the LEADING position hits the recorded-version
        # gate first with the typed unsupported-runtime error.
        store._run_plans[(TENANT, "campaign-1")] = (foreign,) + plans[1:]
        with pytest.raises(UnsupportedRuntimeVersionError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)

    def test_rejects_foreign_candidate_collection(self) -> None:
        store = runtime_three_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        store._strategy_candidates[(TENANT, "campaign-1")] = candidates[1:] + (candidates[0],)
        with pytest.raises(RunInputIntegrityError):
            preflight_realization_run_plan_matrix(store, TENANT, campaign, world)


class TestTrajectoryPlanPreparationDispatch:
    def test_runtime_two_uses_historical_preflight_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(
            store,
            world_version_id,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
            legion=MockLegionAdapter(),
        )
        historical_calls = 0
        realization_calls = 0

        def historical(*args: object, **kwargs: object) -> None:
            nonlocal historical_calls
            historical_calls += 1

        def realization(*args: object, **kwargs: object) -> None:
            nonlocal realization_calls
            realization_calls += 1

        monkeypatch.setattr(
            "kalhas.application.strategy_trajectory_service.preflight_run_plan_matrix",
            historical,
        )
        monkeypatch.setattr(
            "kalhas.application.strategy_trajectory_service.preflight_realization_run_plan_matrix",
            realization,
        )
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert historical_calls == 1
        assert realization_calls == 0

    def test_runtime_three_uses_realization_preflight_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = runtime_three_store()
        historical_calls = 0
        realization_calls = 0

        def historical(*args: object, **kwargs: object) -> None:
            nonlocal historical_calls
            historical_calls += 1

        def realization(*args: object, **kwargs: object) -> None:
            nonlocal realization_calls
            realization_calls += 1

        monkeypatch.setattr(
            "kalhas.application.strategy_trajectory_service.preflight_run_plan_matrix",
            historical,
        )
        monkeypatch.setattr(
            "kalhas.application.strategy_trajectory_service.preflight_realization_run_plan_matrix",
            realization,
        )
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert historical_calls == 0
        assert realization_calls == 1

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = runtime_three_store()
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            prepare_strategy_trajectory_plans(
                store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_legacy_recorded_runtime_rejected(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(
            store,
            world_version_id,
            runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION,
            legion=MockLegionAdapter(),
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            prepare_strategy_trajectory_plans(
                store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestLifecycleExecution:
    """Runtime-3 lifecycle execution service tests."""

    @staticmethod
    def _store() -> InMemoryScenarioStore:
        return runtime_three_execution_store()

    @staticmethod
    def _plans(store: InMemoryScenarioStore) -> tuple[RunPlan, ...]:
        return store.get_run_plans(TENANT, "campaign-1")

    @classmethod
    def _first_run_id(cls, store: InMemoryScenarioStore) -> str:
        return run_identifier(cls._plans(store)[0])

    @classmethod
    def _verified(cls, store: InMemoryScenarioStore, run_id: str) -> VerifiedRunTrajectoryInputs:
        return verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)

    @staticmethod
    def _realization(verified: VerifiedRunTrajectoryInputs) -> WorldRealization:
        assert verified.realization is not None
        return verified.realization

    @staticmethod
    def _assert_planned_and_unwritten(store: InMemoryScenarioStore, run_id: str) -> None:
        status = store.get_run_status(TENANT, run_id)
        assert status.state is RunState.PLANNED
        assert status.event_hash is None
        with pytest.raises(RunNotFoundError):
            store.get_run_events(TENANT, run_id)

    def test_valid_planned_run_executes(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        result = execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert isinstance(result, RunExecution)
        assert result.status.state is RunState.COMPLETE
        assert result.status.run_id == run_id

    def test_exactly_one_artifact_stored(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert len(store._realization_run_trajectory_executions) == 1
        stored = store.get_realization_run_trajectory_execution(TENANT, run_id)
        assert stored.run_id == run_id

    def test_stored_artifact_passes_verifier(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_trajectory_execution(TENANT, run_id)
        verified = self._verified(store, run_id)
        verify_realization_run_trajectory_execution_record(
            stored,
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=self._realization(verified),
        )  # must not raise

    def test_artifact_realization_matches_reconstructed(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_trajectory_execution(TENANT, run_id)
        verified = self._verified(store, run_id)
        assert verified.realization is not None
        assert stored.world_realization_id == verified.realization.identifier
        assert stored.world_realization_content_hash == verified.realization.content_hash

    def test_non_empty_results_in_exact_plan_order(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_trajectory_execution(TENANT, run_id)
        verified = self._verified(store, run_id)
        assert stored.results
        assert [r.trajectory_plan_id for r in stored.results] == [
            plan.identifier for plan in verified.plans
        ]

    def test_planned_running_complete_transition(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        result = execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert result.status.state is RunState.COMPLETE
        payloads = [event.payload for event in result.events]
        assert payloads[0]["lifecycle"] == "planned -> running"
        assert payloads[2]["lifecycle"] == "running -> complete"

    def test_exactly_three_structural_events(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        result = execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert [event.sequence for event in result.events] == [0, 1, 2]
        assert [event.kind for event in result.events] == [
            RunEventKind.RUN_STARTED,
            RunEventKind.STRATEGY_DECLARATION_RECORDED,
            RunEventKind.RUN_COMPLETED,
        ]
        stored = store.get_run_events(TENANT, run_id)
        assert stored == result.events

    def test_complete_event_hash_is_structural_only(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        result = execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert result.status.event_hash == event_hash(result.events)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        assert result.status.event_hash != execution.content_hash

    def test_events_contain_no_realized_state_or_uncertainty_values(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        result = execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        allowed_keys = {
            "runtime_version",
            "run_plan_id",
            "lifecycle",
            "strategy_version",
            "policy_summary",
            "event_count",
        }
        for event in result.events:
            assert set(event.payload) <= allowed_keys
            for value in event.payload.values():
                assert "level" not in str(value)
                assert "84" not in str(value)

    def test_manifest_stored_only_after_successful_build(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        with pytest.raises(RunNotFoundError):
            store.get_input_integrity_manifest(TENANT, run_id)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        manifest = store.get_input_integrity_manifest(TENANT, run_id)
        assert manifest.recomputed_input_hash == self._plans(store)[0].input_hash

    def test_signature_has_no_synthetic_input_seams(self) -> None:
        parameters = inspect.signature(execute_realization_run).parameters
        assert tuple(parameters) == ("store", "tenant_id", "run_id")

    def test_verify_trajectory_inputs_called_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        calls = 0
        original = verify_run_trajectory_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            realization_execution_module(),
            "verify_run_trajectory_inputs",
            counting,
        )
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert calls == 1

    def test_verify_run_inputs_not_imported_or_called(self) -> None:
        module = realization_execution_module()
        source = inspect.getsource(module)
        assert "verify_run_inputs" not in source
        assert "import input_integrity" not in source
        assert "from kalhas.application.input_integrity" not in source

    def test_second_execution_rejected(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotPlannedError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored_before = store.get_realization_run_trajectory_execution(TENANT, run_id)
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(
            TENANT,
            run_id,
            status.model_copy(update={"state": RunState.PLANNED, "event_hash": None}),
        )
        with pytest.raises(RealizationRunTrajectoryExecutionAlreadyExistsError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored_after = store.get_realization_run_trajectory_execution(TENANT, run_id)
        assert stored_after == stored_before

    @pytest.mark.parametrize("runtime", ["1.0.0", "2.0.0"])
    def test_other_recorded_runtimes_rejected_zero_writes(self, runtime: str) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=runtime)
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        self._assert_planned_and_unwritten(store, run_id)
        assert not store._realization_run_trajectory_executions

    def test_unsupported_recorded_runtime_rejected_zero_writes(self) -> None:
        store = self._store()
        plan = self._plans(store)[0]
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        self._assert_planned_and_unwritten(store, run_id)
        assert not store._realization_run_trajectory_executions

    def test_foreign_and_unknown_tenant_typed_isolated(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        with pytest.raises(RunNotFoundError):
            execute_realization_run(store=store, tenant_id="tenant-other", run_id=run_id)
        with pytest.raises(RunNotFoundError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id="run-unknown")
        self._assert_planned_and_unwritten(store, run_id)
        assert not store._realization_run_trajectory_executions

    def test_tampered_input_provenance_fails_before_writes(self) -> None:
        store = self._store()
        plans = self._plans(store)
        run_id = run_identifier(plans[0])
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        self._assert_planned_and_unwritten(store, run_id)
        assert not store._realization_run_trajectory_executions

    def test_builder_failure_fails_before_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = self._store()
        run_id = self._first_run_id(store)

        def broken(*args: object, **kwargs: object) -> object:
            raise RealizationRunTrajectoryExecutionIntegrityError(
                run_id, "synthetic builder failure"
            )

        monkeypatch.setattr(
            realization_execution_module(),
            "build_realization_run_trajectory_execution",
            broken,
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        self._assert_planned_and_unwritten(store, run_id)
        assert not store._realization_run_trajectory_executions

    def test_pre_existing_artifact_fails_before_lifecycle_writes(self) -> None:
        store = self._store()
        run_id = self._first_run_id(store)
        verified = self._verified(store, run_id)
        execution = build_realization_run_trajectory_execution(
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=self._realization(verified),
        )
        store.put_realization_run_trajectory_execution(TENANT, run_id, execution)
        with pytest.raises(RealizationRunTrajectoryExecutionAlreadyExistsError):
            execute_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        self._assert_planned_and_unwritten(store, run_id)
        assert len(store._realization_run_trajectory_executions) == 1
        assert store.get_realization_run_trajectory_execution(TENANT, run_id) == execution

    def test_non_running_campaign_rejected_zero_executions(self) -> None:
        store = runtime_three_store()
        with pytest.raises(CampaignNotRunningError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in store.get_run_plans(TENANT, "campaign-1"):
            status = store.get_run_status(TENANT, run_identifier(plan))
            assert status.state is RunState.PLANNED
        assert not store._realization_run_trajectory_executions

    def test_invalid_first_run_causes_zero_executions(self) -> None:
        store = self._store()
        plans = self._plans(store)
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in plans:
            self._assert_planned_and_unwritten(store, run_identifier(plan))
        assert not store._realization_run_trajectory_executions
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    @pytest.mark.parametrize("tamper_index", [4, 9])
    def test_invalid_middle_or_last_run_causes_zero_executions(self, tamper_index: int) -> None:
        store = self._store()
        plans = self._plans(store)
        tampered = plans[tamper_index].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            tampered if plan.identifier == plans[tamper_index].identifier else plan
            for plan in plans
        )
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in plans:
            self._assert_planned_and_unwritten(store, run_identifier(plan))
        assert not store._realization_run_trajectory_executions
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_pre_existing_artifact_on_later_run_causes_zero_executions(self) -> None:
        store = self._store()
        plans = self._plans(store)
        last_run_id = run_identifier(plans[-1])
        verified = self._verified(store, last_run_id)
        execution = build_realization_run_trajectory_execution(
            inputs=verified.inputs,
            plans=verified.plans,
            catalogs=verified.catalogs,
            realization=self._realization(verified),
        )
        store.put_realization_run_trajectory_execution(TENANT, last_run_id, execution)
        with pytest.raises(RealizationRunTrajectoryExecutionAlreadyExistsError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in plans:
            self._assert_planned_and_unwritten(store, run_identifier(plan))
        assert len(store._realization_run_trajectory_executions) == 1
        assert store.get_realization_run_trajectory_execution(TENANT, last_run_id) == execution
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_builder_failure_on_later_run_causes_zero_executions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = self._store()
        calls = 0
        original = build_realization_run_trajectory_execution

        def failing(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 6:
                raise RealizationRunTrajectoryExecutionIntegrityError(
                    "run-unknown", "synthetic later-run builder failure"
                )
            return original(*args, **kwargs)

        monkeypatch.setattr(
            realization_execution_module(),
            "build_realization_run_trajectory_execution",
            failing,
        )
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert calls == 6
        for plan in self._plans(store):
            self._assert_planned_and_unwritten(store, run_identifier(plan))
        assert not store._realization_run_trajectory_executions
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_valid_campaign_executes_in_exact_stored_order(self) -> None:
        store = self._store()
        plans = self._plans(store)
        statuses = execute_realization_campaign(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [status.run_plan_id for status in statuses] == [plan.identifier for plan in plans]

    def test_every_run_complete_with_artifact_and_events(self) -> None:
        store = self._store()
        plans = self._plans(store)
        execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        for plan in plans:
            run_id = run_identifier(plan)
            status = store.get_run_status(TENANT, run_id)
            assert status.state is RunState.COMPLETE
            assert status.event_hash is not None
            artifact = store.get_realization_run_trajectory_execution(TENANT, run_id)
            assert artifact.results
            events = store.get_run_events(TENANT, run_id)
            assert len(events) == 3
            assert status.event_hash == event_hash(events)
        assert len(store._realization_run_trajectory_executions) == len(plans)

    def test_campaign_complete_only_after_all_runs_complete(self) -> None:
        store = self._store()
        plans = self._plans(store)
        statuses = execute_realization_campaign(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.COMPLETE
        assert (
            campaign.message
            == "campaign complete: structural execution finished; no decision evidence produced"
        )
        assert campaign.changed_at == plans[0].created_at
        assert all(status.state is RunState.COMPLETE for status in statuses)

    def test_verify_calls_exactly_twice_per_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = self._store()
        plans = self._plans(store)
        calls = 0
        original = verify_run_trajectory_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(
            realization_execution_module(),
            "verify_run_trajectory_inputs",
            counting,
        )
        execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert calls == 2 * len(plans)

    def test_same_seed_same_realization_across_strategies(self) -> None:
        store = self._store()
        plans = self._plans(store)
        first = next(p for p in plans if p.strategy_candidate_id == "mock-baseline")
        other = next(p for p in plans if p.strategy_candidate_id == "mock-conservative")
        assert first.scenario_seed_id == other.scenario_seed_id
        execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        artifact_a = store.get_realization_run_trajectory_execution(TENANT, run_identifier(first))
        artifact_b = store.get_realization_run_trajectory_execution(TENANT, run_identifier(other))
        assert artifact_a.world_realization_id == artifact_b.world_realization_id
        assert (
            artifact_a.world_realization_content_hash == artifact_b.world_realization_content_hash
        )

    def test_no_runtime2_artifacts_observations_or_replay_manifests(self) -> None:
        store = self._store()
        execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert not store._run_trajectory_executions
        assert not store._run_metric_observation_sets
        assert not store._run_trajectory_replay_manifests
        assert not store._realization_run_trajectory_replay_manifests
        assert not store._realization_run_metric_observation_sets

    def test_module_imports_no_adapters_or_providers(self) -> None:
        module = realization_execution_module()
        source = inspect.getsource(module)
        assert "kalhas.adapters" not in source
        assert "from kalhas.adapters" not in source
        assert "import legion" not in source
        assert "import nexus" not in source

    def test_no_wall_clock_random_network_filesystem(self) -> None:
        module = realization_execution_module()
        source = inspect.getsource(module)
        assert "import random" not in source
        assert "datetime.now" not in source
        assert "utcnow" not in source
        assert "time.time(" not in source
        assert "urllib" not in source
        assert "requests" not in source
        assert "socket" not in source
        assert "open(" not in source

    def test_no_api_replay_observation_or_matrix_surface(self) -> None:
        module = realization_execution_module()
        source = inspect.getsource(module)
        assert "fastapi" not in source
        assert "routes" not in source
        assert "import replay" not in source
        assert "replay_service" not in source
        assert "observation_service" not in source
        assert "import matrix" not in source
        # No replay/observation/matrix/API symbols exist in the module.
        assert not any(
            name in module.__dict__
            for name in (
                "replay",
                "observation",
                "matrix",
                "routes",
            )
        )

    def test_runtime2_structural_sources_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--exit-code",
                "--",
                "kalhas/application/structural_runtime.py",
                "kalhas/application/run_trajectory_runtime.py",
                "kalhas/application/trajectory_integrity.py",
                "kalhas/application/replay_service.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout


def realization_execution_module() -> Any:
    from kalhas.application import realization_execution as module

    return module


class TestCampaignMatrixPreflight:
    """Campaign-level complete strategy x seed matrix verification tests.

    ``execute_realization_campaign`` must verify the complete stored
    run-plan matrix through the existing read-only matrix preflight
    before any run executes: a missing, additional, duplicated,
    reordered, or tampered plan - or a mismatched candidate collection -
    must abort with zero executions, zero events, zero artifacts, zero
    manifests, every run still PLANNED, and the campaign still RUNNING.
    """

    @staticmethod
    def _store() -> InMemoryScenarioStore:
        return runtime_three_execution_store()

    @staticmethod
    def _plans(store: InMemoryScenarioStore) -> tuple[RunPlan, ...]:
        return store.get_run_plans(TENANT, "campaign-1")

    @staticmethod
    def _assert_no_writes(store: InMemoryScenarioStore, plans: tuple[RunPlan, ...]) -> None:
        for plan in plans:
            run_id = run_identifier(plan)
            status = store.get_run_status(TENANT, run_id)
            assert status.state is RunState.PLANNED
            assert status.event_hash is None
            with pytest.raises(RunNotFoundError):
                store.get_run_events(TENANT, run_id)
            with pytest.raises(RunNotFoundError):
                store.get_input_integrity_manifest(TENANT, run_id)
        assert not store._realization_run_trajectory_executions
        assert not store._run_events

    @pytest.mark.parametrize("removed_index", [0, 5, 9])
    def test_missing_stored_plan_rejected_zero_executions(self, removed_index: int) -> None:
        store = self._store()
        plans = self._plans(store)
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            plan for index, plan in enumerate(plans) if index != removed_index
        )
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_reordered_matrix_rejected_zero_executions(self) -> None:
        store = self._store()
        plans = self._plans(store)
        store._run_plans[(TENANT, "campaign-1")] = (
            plans[1],
            plans[0],
        ) + plans[2:]
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_duplicated_and_additional_plan_rejected_zero_executions(self) -> None:
        store = self._store()
        plans = self._plans(store)
        # Duplicated stored plan: the same plan appears twice.
        store._run_plans[(TENANT, "campaign-1")] = plans + (plans[0],)
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        # Additional foreign plan: a plan that the authoritative matrix
        # cannot contain (foreign seed) appended to the stored tuple.
        store._run_plans[(TENANT, "campaign-1")] = plans + (
            plans[0].model_copy(update={"scenario_seed_id": "seed-foreign"}),
        )
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_tampered_plan_rejected_zero_executions(self) -> None:
        store = self._store()
        plans = self._plans(store)
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    @pytest.mark.parametrize("mode", ["altered", "dropped"])
    def test_candidate_collection_mismatch_rejected_zero_executions(self, mode: str) -> None:
        store = self._store()
        plans = self._plans(store)
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        if mode == "altered":
            swapped = (candidates[1], candidates[0]) + candidates[2:]
            store._strategy_candidates[(TENANT, "campaign-1")] = swapped
        else:
            store._strategy_candidates[(TENANT, "campaign-1")] = candidates[:4]
        with pytest.raises(RunInputIntegrityError):
            execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        self._assert_no_writes(store, plans)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.RUNNING

    def test_matrix_preflight_called_exactly_once_and_campaign_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = self._store()
        plans = self._plans(store)
        matrix_calls = 0
        verify_calls = 0
        original_matrix = preflight_realization_run_plan_matrix
        original_verify = verify_run_trajectory_inputs

        def counting_matrix(*args: Any, **kwargs: Any) -> Any:
            nonlocal matrix_calls
            matrix_calls += 1
            return original_matrix(*args, **kwargs)

        def counting_verify(*args: Any, **kwargs: Any) -> Any:
            nonlocal verify_calls
            verify_calls += 1
            return original_verify(*args, **kwargs)

        monkeypatch.setattr(
            realization_execution_module(),
            "preflight_realization_run_plan_matrix",
            counting_matrix,
        )
        monkeypatch.setattr(
            realization_execution_module(),
            "verify_run_trajectory_inputs",
            counting_verify,
        )
        statuses = execute_realization_campaign(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix_calls == 1
        assert verify_calls == 2 * len(plans)
        assert all(status.state is RunState.COMPLETE for status in statuses)
        campaign = store.get_campaign_status(TENANT, "campaign-1")
        assert campaign.state is CampaignState.COMPLETE
