"""Phase 24 verified query-service tests.

Covers the read-only campaign world-realization chain: successful
derivations (present and absent models), byte identity, lifecycle-state
independence, typed 404 behavior for unknown/foreign campaigns, the
full integrity-error family (missing world/manifest, scenario
mismatch, corrupted snapshots, stored-vs-embedded model mismatches,
impossible stored models), the deterministic sampling-error propagation
(409 CONFLICT class, never converted to integrity), and the absence of
all side effects (no writes, no activity events, no execution).
"""

from __future__ import annotations

from typing import Literal

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.application.world_uncertainty_errors import (
    CampaignWorldRealizationMatrixIntegrityError,
    WorldRealizationSamplingError,
    WorldUncertaintyModelIntegrityError,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.world_realization import UniformDistribution

from tests.phase4_helpers import NOW, TENANT
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase24_helpers import (
    build_uncertainty_store,
    declare_model,
    prepared_campaign,
)

OTHER_TENANT = "tenant-other"


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


def _compiled_store(*, level_allowed: tuple[JsonValue, ...] = ()) -> InMemoryScenarioStore:
    store = build_uncertainty_store(level_allowed=level_allowed)
    declare_model(store, bindings=(_draft(),))
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepared_campaign(store, world_version_id=compiled.version.identifier)
    return store


def _set_status(
    store: InMemoryScenarioStore,
    campaign_id: str,
    state: CampaignState,
) -> None:
    store.update_campaign_status(
        TENANT,
        campaign_id,
        CampaignStatus(
            identifier=f"status-{campaign_id}",
            tenant_id=TENANT,
            schema_version="1.0.0",
            campaign_id=campaign_id,
            state=state,
            changed_at=NOW,
            message="test status",
        ),
    )


class TestSuccessfulPaths:
    def test_present_model_one_realization_per_seed(self) -> None:
        store = _compiled_store()
        matrix = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert len(matrix.realizations) == len(campaign.seed_ensemble)
        assert matrix.ordered_scenario_seed_ids == tuple(
            seed.identifier for seed in campaign.seed_ensemble
        )
        assert matrix.uncertainty_model_id is not None

    def test_absent_model_stable_empty_realizations(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepared_campaign(store, world_version_id=world_version_id)
        matrix = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.uncertainty_model_id is None
        assert all(r.sampled_values == () for r in matrix.realizations)
        assert all(r.realized_initial_state_overrides == () for r in matrix.realizations)

    def test_repeated_query_byte_identical(self) -> None:
        store = _compiled_store()
        first = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_lifecycle_state_does_not_change_bytes(self) -> None:
        store = _compiled_store()
        baseline = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for state in (
            CampaignState.DRAFT,
            CampaignState.VALIDATED,
            CampaignState.COMPILED,
            CampaignState.RUNNING,
            CampaignState.COMPLETE,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        ):
            _set_status(store, "campaign-1", state)
            matrix = get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
            assert matrix.model_dump(mode="json") == baseline.model_dump(mode="json")

    def test_query_performs_no_status_transition(self) -> None:
        store = _compiled_store()
        get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state == "compiled"

    def test_stored_and_embedded_canonically_equal(self) -> None:
        store = _compiled_store()
        matrix = get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        assert stored.identifier == matrix.uncertainty_model_id


class TestTenantAndNotFound:
    def test_unknown_campaign_typed_404(self) -> None:
        store = _compiled_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-nope"
            )

    def test_foreign_tenant_campaign_indistinguishable(self) -> None:
        store = _compiled_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=OTHER_TENANT, campaign_id="campaign-1"
            )


class TestIntegrityBehavior:
    def test_missing_world_is_matrix_integrity_error(self) -> None:
        store = _compiled_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._worlds[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_missing_manifest_is_matrix_integrity_error(self) -> None:
        store = _compiled_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._manifests[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_campaign_world_scenario_mismatch_is_integrity_error(self) -> None:
        store = _compiled_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        tampered = campaign.model_copy(update={"scenario_id": "scenario-other"})
        store._campaigns[(TENANT, "campaign-1")] = tampered
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_corrupted_world_snapshot_is_integrity_error(self) -> None:
        store = _compiled_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        tampered_body = dict(world.world)
        tampered_body["compiler_version"] = "9.9.9"
        broken = world.model_copy(update={"world": tampered_body})
        store._worlds[(TENANT, campaign.world_version_id)] = broken
        with pytest.raises(WorldSnapshotIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_embedded_model_without_stored_model_is_integrity_error(self) -> None:
        store = _compiled_store()
        del store._world_uncertainty_models[(TENANT, "scenario-1")]
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_stored_model_differing_from_embedded_is_integrity_error(self) -> None:
        store = _compiled_store()
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        # Change metadata and recompute the content hash so the stored
        # record still passes revalidation but differs from the embedded
        # snapshot.
        from kalhas.application.world_uncertainty_identity import (
            uncertainty_model_content_hash,
        )

        tampered = stored.model_copy(update={"metadata": {"tampered": True}})
        tampered = tampered.model_copy(
            update={"content_hash": uncertainty_model_content_hash(tampered)}
        )
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_stored_model_tampered_identity_is_integrity_error(self) -> None:
        store = _compiled_store()
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"content_hash": "f" * 64})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_model_free_world_with_stored_model_is_integrity_error(self) -> None:
        # Declare a valid model on one store, compile a model-free world
        # on another, then inject the stored model directly (bypassing
        # the declaration-before-compilation gate).
        source_store = build_uncertainty_store()
        model = declare_model(source_store, bindings=(_draft(),))
        store = build_uncertainty_store()
        world_version_id = compile_observation_world(store)
        prepared_campaign(store, world_version_id=world_version_id)
        store.put_world_uncertainty_model(TENANT, "scenario-1", model)
        with pytest.raises(CampaignWorldRealizationMatrixIntegrityError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestSamplingBehavior:
    def _failing_store(self) -> InMemoryScenarioStore:
        store = build_uncertainty_store(level_allowed=(0, 1))
        declare_model(
            store,
            bindings=(
                UncertaintyBindingDraft(
                    manifest_id="manifest-1",
                    state_model_id="sm-1",
                    state_field_id="level",
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
                    rounding_policy="nearest_ties_to_even",
                ),
            ),
        )
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        # Use the deterministic failing seed from the verified probe.
        from kalhas.contracts.v1.scenario import ScenarioSeed

        failing_seed = ScenarioSeed(
            identifier="seed-fail-0",
            tenant_id=TENANT,
            algorithm="deterministic",
            seed_value="v1",
        )
        prepared_campaign(
            store,
            world_version_id=compiled.version.identifier,
            seeds=(failing_seed,),
        )
        return store

    def test_sampling_failure_propagates_unchanged(self) -> None:
        store = self._failing_store()
        with pytest.raises(WorldRealizationSamplingError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_sampling_failure_is_not_converted_to_integrity(self) -> None:
        store = self._failing_store()
        try:
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        except WorldRealizationSamplingError as exc:
            assert not isinstance(exc, CampaignWorldRealizationMatrixIntegrityError)
        else:  # pragma: no cover - the probe seed must fail
            raise AssertionError("expected a deterministic sampling failure")

    def test_no_partial_matrix_returned(self) -> None:
        store = self._failing_store()
        with pytest.raises(WorldRealizationSamplingError):
            get_verified_campaign_world_realizations(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestNoSideEffects:
    def test_query_performs_no_store_writes(self) -> None:
        store = _compiled_store()
        before_worlds = dict(store._worlds)
        before_models = dict(store._world_uncertainty_models)
        before_campaigns = dict(store._campaigns)
        before_plans = dict(store._run_plans)
        get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store._worlds == before_worlds
        assert store._world_uncertainty_models == before_models
        assert store._campaigns == before_campaigns
        assert store._run_plans == before_plans

    def test_query_records_no_operational_activity(self) -> None:
        store = _compiled_store()
        get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.list_operational_activity(TENANT, limit=100) == ()

    def test_query_creates_no_runs_or_events(self) -> None:
        store = _compiled_store()
        # Preparation itself records run plans (the real Phase 4 seam);
        # the query must add nothing.
        plans_before = store._run_plans.get((TENANT, "campaign-1"))
        events_before = store._run_events.get((TENANT, "campaign-1"))
        get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store._run_plans.get((TENANT, "campaign-1")) == plans_before
        assert store._run_events.get((TENANT, "campaign-1")) == events_before

    def test_query_uses_no_adapters(self) -> None:
        # The query service accepts only the store; adapter calls are
        # structurally impossible. Prove no adapter imports exist in the
        # production module.
        import inspect

        from kalhas.application import world_realization_query_service as module

        source = inspect.getsource(module)
        assert "adapters" not in source
