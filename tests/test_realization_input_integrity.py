"""Focused tests for the Phase 25 corrected single-pass input-integrity chain.

Proves the version-dispatched ``verify_run_inputs``: runtime 1.0.0/2.0.0
retain the exact historical ``run_input_hash`` behavior, runtime 3.0.0
reconstructs the Phase 24 realization exactly once per verification
operation and recomputes the runtime-3 input hash that binds the
realization content hash, and the same seed realization hash is used
independently of strategy. The stored-vs-embedded uncertainty-model
consistency rules fail closed in every direction; realization-integrity
failures are converted to ``RunInputIntegrityError`` while deterministic
sampling failures propagate unchanged; tampered plan/status hashes and
unsupported recorded runtimes are rejected; the chain performs no writes
and records no events; ``verify_run_trajectory_inputs`` calls
``verify_run_inputs`` exactly once and reuses (never reconstructs) the
realization; and ``realization_identity`` still has no runtime import of
``input_integrity``.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_errors import (
    RunInputIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import (
    VerifiedRunInputs,
    verify_run_inputs,
)
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
    run_identifier,
    run_input_hash,
    run_realization_input_hash,
)
from kalhas.application.run_trajectory_inputs import (
    verify_run_trajectory_inputs,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationSamplingError,
    WorldUncertaintyModelIntegrityError,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_model_content_hash,
    uncertainty_model_identifier,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import (
    UniformDistribution,
    WorldRealization,
)

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, prepare
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase24_helpers import build_uncertainty_store, declare_model


def _draft(
    *,
    state_field_id: str = "level",
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = (
        "nearest_ties_to_even"
    ),
) -> UncertaintyBindingDraft:
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id=state_field_id,
        distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy=rounding_policy,
    )


@dataclass(frozen=True)
class RuntimeThreeContext:
    """The recorded runtime-3 campaign records tests need to reach any run."""

    plans: tuple[RunPlan, ...]
    realizations: dict[str, WorldRealization]
    world: WorldVersion


def _runtime_three_store(
    *,
    with_model: bool = True,
) -> tuple[InMemoryScenarioStore, RuntimeThreeContext]:
    """A store with a compiled world and a fully recorded runtime-3 campaign.

    Returns ``(store, context)`` where ``context`` carries the plans,
    realizations, strategies, seeds, and world so tests can reach any
    run. The campaign is recorded directly through the store seams (the
    Phase 25 preparation service gates runtime 3.0.0 and is not part of
    this slice).
    """
    store = build_uncertainty_store()
    if with_model:
        declare_model(store, bindings=(_draft(),))
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    world = store.get_world(TENANT, compiled.version.identifier)
    strategies = MockLegionAdapter().request_strategies(build_request())
    seeds = (build_seed(identifier="seed-1"), build_seed(identifier="seed-2"))
    catalog = extract_world_catalog(world)
    realizations = {
        seed.identifier: build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=NOW,
        )
        for seed in seeds
    }
    plans = plan_realization_runs(
        campaign_id="campaign-1",
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=strategies,
        seeds=seeds,
        created_at=NOW,
        realizations=realizations,
    )
    campaign = CampaignSpec(
        identifier="campaign-1",
        tenant_id=TENANT,
        name="Runtime three campaign",
        scenario_id="scenario-1",
        world_version_id=world.identifier,
        strategy_candidate_ids=[strategy.identifier for strategy in strategies],
        seed_ensemble=seeds,
        created_at=NOW,
    )
    store.put_campaign(
        campaign,
        CampaignStatus(
            identifier="status-campaign-1",
            tenant_id=TENANT,
            schema_version="1.0.0",
            campaign_id="campaign-1",
            state=CampaignState.COMPILED,
            changed_at=NOW,
            message="test status",
        ),
    )
    store.put_strategy_candidates(TENANT, "campaign-1", strategies)
    store.put_run_plans(TENANT, "campaign-1", plans)
    for plan in plans:
        run_id = run_identifier(plan)
        store.put_run_status(
            TENANT,
            run_id,
            RunStatus(
                identifier=f"status-{run_id}",
                tenant_id=TENANT,
                schema_version="1.0.0",
                run_id=run_id,
                campaign_id="campaign-1",
                run_plan_id=plan.identifier,
                state=RunState.PLANNED,
                runtime_version=plan.runtime_version,
                input_hash=plan.input_hash,
                created_at=NOW,
                changed_at=NOW,
            ),
        )
    context = RuntimeThreeContext(
        plans=plans,
        realizations=realizations,
        world=world,
    )
    return store, context


def _first_run_id(context: RuntimeThreeContext) -> str:
    return run_identifier(context.plans[0])


class TestRuntimeTwoCompatibility:
    def test_runtime_two_retains_historical_input_hash(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(
            store,
            world_version_id,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
            legion=MockLegionAdapter(),
        )
        plans = store.get_run_plans(TENANT, "campaign-1")
        verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_identifier(plans[0]))
        assert verified.realization is None
        assert verified.manifest.verification_classification == "exact"
        assert verified.manifest.recomputed_input_hash == plans[0].input_hash
        assert verified.manifest.recomputed_input_hash == run_input_hash(
            world_content_hash=verified.world.content_hash,
            strategy=verified.strategy,
            seed=verified.seed,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        )

    def test_runtime_one_retains_historical_input_hash(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, legion=MockLegionAdapter())
        plans = store.get_run_plans(TENANT, "campaign-1")
        verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_identifier(plans[0]))
        assert verified.realization is None
        assert verified.manifest.recomputed_input_hash == run_input_hash(
            world_content_hash=verified.world.content_hash,
            strategy=verified.strategy,
            seed=verified.seed,
            runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION,
        )

    def test_historical_constructor_sites_remain_valid(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, legion=MockLegionAdapter())
        plans = store.get_run_plans(TENANT, "campaign-1")
        verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_identifier(plans[0]))
        # Six-field construction (no realization) still works.
        assert (
            VerifiedRunInputs(
                run_plan=verified.run_plan,
                world=verified.world,
                strategy=verified.strategy,
                seed=verified.seed,
                status=verified.status,
                manifest=verified.manifest,
            ).realization
            is None
        )


class TestRuntimeThreeVerification:
    def test_correct_runtime_three_input_hash_succeeds(self) -> None:
        store, context = _runtime_three_store()
        run_id = _first_run_id(context)
        verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)
        plan = context.plans[0]
        assert verified.realization is not None
        assert verified.manifest.runtime_version == REALIZATION_TRAJECTORY_RUNTIME_VERSION
        assert verified.manifest.recomputed_input_hash == plan.input_hash
        assert verified.manifest.recomputed_input_hash == run_realization_input_hash(
            world_content_hash=verified.world.content_hash,
            strategy=verified.strategy,
            seed=verified.seed,
            world_realization_content_hash=verified.realization.content_hash,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        )

    def test_exact_reconstructed_realization_is_returned(self) -> None:
        store, context = _runtime_three_store()
        verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))
        plan = context.plans[0]
        expected = context.realizations[plan.scenario_seed_id]
        assert verified.realization == expected
        assert verified.realization.scenario_seed_id == plan.scenario_seed_id

    def test_one_reconstruction_per_verification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, context = _runtime_three_store()
        calls = 0
        original = build_world_realization

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr("kalhas.application.input_integrity.build_world_realization", counting)
        verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))
        assert calls == 1

    def test_trajectory_verification_reuses_not_reconstructs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, context = _runtime_three_store()
        calls = 0
        original = build_world_realization

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr("kalhas.application.input_integrity.build_world_realization", counting)
        trajectory = verify_run_trajectory_inputs(
            store=store, tenant_id=TENANT, run_id=_first_run_id(context)
        )
        assert calls == 1  # only the base verifier reconstructed once
        assert trajectory.realization is not None
        assert trajectory.realization == context.realizations["seed-1"]

    def test_trajectory_verification_calls_base_verifier_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, context = _runtime_three_store()
        calls = 0
        original = verify_run_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr("kalhas.application.run_trajectory_inputs.verify_run_inputs", counting)
        verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))
        assert calls == 1

    def test_same_seed_realization_hash_independent_of_strategy(self) -> None:
        store, context = _runtime_three_store()
        plans = context.plans
        seed_hashes: dict[str, set[str]] = {}
        for plan in plans:
            verified = verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_identifier(plan))
            assert verified.realization is not None
            seed_hashes.setdefault(plan.scenario_seed_id, set()).add(
                verified.realization.content_hash
            )
        assert seed_hashes["seed-1"] == {context.realizations["seed-1"].content_hash}
        assert seed_hashes["seed-2"] == {context.realizations["seed-2"].content_hash}
        assert seed_hashes["seed-1"] != seed_hashes["seed-2"]


class TestStoredEmbeddedConsistency:
    def test_missing_stored_model_fails_closed(self) -> None:
        store, context = _runtime_three_store()
        del store._world_uncertainty_models[(TENANT, "scenario-1")]
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_corrupt_stored_model_raises_typed_integrity_error(self) -> None:
        store, context = _runtime_three_store()
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        # A self-consistent model with a stale content hash fails identity.
        corrupt = stored.model_copy(update={"content_hash": "0" * 64})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = corrupt
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_stored_embedded_mismatch_fails_closed(self) -> None:
        store, context = _runtime_three_store()
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
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_stored_model_without_embedded_model_fails_closed(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        # The world embeds no uncertainty model. A contract-valid model is
        # declared on a separate store (declaration after compilation is
        # rejected by the Phase 24 service) and injected into this store's
        # private collection, simulating a stored declaration that the
        # compiled world never embedded.
        model_source = build_uncertainty_store()
        model = declare_model(model_source, bindings=(_draft(),), declared_at=NOW)
        store._world_uncertainty_models[(TENANT, "scenario-1")] = model
        context = _runtime_three_store_context_on(store, world_version_id)
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))


def _runtime_three_store_context_on(
    store: InMemoryScenarioStore, world_version_id: str
) -> RuntimeThreeContext:
    """Record a runtime-3 campaign on an already populated store."""
    world = store.get_world(TENANT, world_version_id)
    strategies = MockLegionAdapter().request_strategies(build_request())
    seeds = (build_seed(identifier="seed-1"),)
    catalog = extract_world_catalog(world)
    realizations = {
        seed.identifier: build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=NOW,
        )
        for seed in seeds
    }
    plans = plan_realization_runs(
        campaign_id="campaign-1",
        tenant_id=TENANT,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=strategies,
        seeds=seeds,
        created_at=NOW,
        realizations=realizations,
    )
    campaign = CampaignSpec(
        identifier="campaign-1",
        tenant_id=TENANT,
        name="Runtime three campaign",
        scenario_id="scenario-1",
        world_version_id=world.identifier,
        strategy_candidate_ids=[strategy.identifier for strategy in strategies],
        seed_ensemble=seeds,
        created_at=NOW,
    )
    store.put_campaign(
        campaign,
        CampaignStatus(
            identifier="status-campaign-1",
            tenant_id=TENANT,
            schema_version="1.0.0",
            campaign_id="campaign-1",
            state=CampaignState.COMPILED,
            changed_at=NOW,
            message="test status",
        ),
    )
    store.put_strategy_candidates(TENANT, "campaign-1", strategies)
    store.put_run_plans(TENANT, "campaign-1", plans)
    for plan in plans:
        run_id = run_identifier(plan)
        store.put_run_status(
            TENANT,
            run_id,
            RunStatus(
                identifier=f"status-{run_id}",
                tenant_id=TENANT,
                schema_version="1.0.0",
                run_id=run_id,
                campaign_id="campaign-1",
                run_plan_id=plan.identifier,
                state=RunState.PLANNED,
                runtime_version=plan.runtime_version,
                input_hash=plan.input_hash,
                created_at=NOW,
                changed_at=NOW,
            ),
        )
    return RuntimeThreeContext(plans=plans, realizations=realizations, world=world)


class TestFailureConversionAndRejection:
    def test_realization_integrity_failure_converted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kalhas.application.world_uncertainty_errors import WorldRealizationIntegrityError

        store, context = _runtime_three_store()

        def broken(*args: object, **kwargs: object) -> object:
            raise WorldRealizationIntegrityError(TENANT, "scenario-1", reason="boom")

        monkeypatch.setattr("kalhas.application.input_integrity.build_world_realization", broken)
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_sampling_failure_propagates_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store, context = _runtime_three_store()

        def broken(*args: object, **kwargs: object) -> object:
            raise WorldRealizationSamplingError(TENANT, "scenario-1", reason="boom")

        monkeypatch.setattr("kalhas.application.input_integrity.build_world_realization", broken)
        with pytest.raises(WorldRealizationSamplingError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_tampered_plan_input_hash_rejected(self) -> None:
        store, context = _runtime_three_store()
        plan = context.plans[0]
        tampered = plan.model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            tampered if candidate.identifier == plan.identifier else candidate
            for candidate in context.plans
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=_first_run_id(context))

    def test_tampered_status_input_hash_rejected(self) -> None:
        store, context = _runtime_three_store()
        run_id = _first_run_id(context)
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(
            TENANT,
            run_id,
            status.model_copy(update={"input_hash": "f" * 64}),
        )
        with pytest.raises(RunInputIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store, context = _runtime_three_store()
        run_id = _first_run_id(context)
        status = store.get_run_status(TENANT, run_id)
        plan = context.plans[0]
        bogus_plan = plan.model_copy(update={"runtime_version": "9.9.9"})
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            bogus_plan if candidate.identifier == plan.identifier else candidate
            for candidate in context.plans
        )
        store.put_run_status(
            TENANT,
            run_id,
            status.model_copy(update={"runtime_version": "9.9.9"}),
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)

    def test_chain_performs_no_writes_and_records_no_events(self) -> None:
        store, context = _runtime_three_store()
        run_id = _first_run_id(context)
        before_activity = len(store._operational_activity)
        before_sequences = len(store._activity_sequences)
        verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)
        verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)
        assert len(store._operational_activity) == before_activity
        assert len(store._activity_sequences) == before_sequences
        assert store._realization_run_trajectory_executions == {}
        assert store._realization_run_trajectory_replay_manifests == {}
        assert store._realization_run_metric_observation_sets == {}


class TestIdentityImportBoundary:
    def test_identity_module_has_no_runtime_input_integrity_import(self) -> None:
        probe = (
            "import sys; "
            "import kalhas.application.realization_identity; "
            "assert 'kalhas.application.input_integrity' not in sys.modules; "
            "print('acyclic')"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "acyclic" in result.stdout
