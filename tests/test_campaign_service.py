"""Tests for deterministic campaign preparation and start operations."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kalhas.adapters.legion import LegionAdapter
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.campaign_lifecycle import CampaignTransitionError
from kalhas.application.campaign_service import PreparedCampaign, prepare_campaign, start_campaign
from kalhas.application.domain_errors import (
    CampaignAlreadyExistsError,
    CampaignNotFoundError,
    CampaignPreparationError,
    ScenarioNotFoundError,
    WorldNotFoundError,
    WorldScenarioMismatchError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.scenario import (
    Constraint,
    Objective,
    ObjectiveDirection,
    ScenarioSeed,
    ScenarioSpec,
    TimeHorizon,
)
from kalhas.contracts.v1.shared import Assumption, MetricDefinition
from kalhas.contracts.v1.strategy import (
    ObservationRequirement,
    PolicyDeclaration,
    StrategyCandidate,
    StrategyRequest,
)
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)


class FakeLegionAdapter:
    """Protocol-compatible deterministic fake (test-only, no mock import).

    Conforms structurally to ``LegionAdapter.request_strategies`` and lets
    tests violate invariants (foreign tenant, duplicate ids, wrong count)
    that the real mock never would. The Phase 15 trajectory-plan boundary
    is implemented with the exact protocol signature but is never used by
    these strategy tests: calling it raises AssertionError so an
    unexpected trajectory request fails loudly.
    """

    def __init__(
        self,
        *,
        tenant_id: str = "tenant-1",
        candidate_count: int = 5,
        duplicate_ids: bool = False,
        foreign_tenant: bool = False,
    ) -> None:
        self._tenant_id = tenant_id
        self._candidate_count = candidate_count
        self._duplicate_ids = duplicate_ids
        self._foreign_tenant = foreign_tenant

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        tenant_id = "tenant-foreign" if self._foreign_tenant else self._tenant_id
        candidates: list[StrategyCandidate] = []
        for index in range(self._candidate_count):
            identifier = "dup-candidate" if self._duplicate_ids else f"fake-{index}"
            candidates.append(
                StrategyCandidate(
                    identifier=identifier,
                    tenant_id=tenant_id,
                    strategy_version="1.0.0",
                    policy=PolicyDeclaration(
                        summary=f"fake policy {index}",
                        rules=[],
                    ),
                    required_observations=list(request.required_observations),
                    assumptions=[],
                )
            )
        return tuple(candidates)

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        raise AssertionError(
            "FakeLegionAdapter serves strategy requests only; the trajectory-plan "
            "boundary was unexpectedly called"
        )


def build_scenario(*, identifier: str = "scenario-1", tenant_id: str = "tenant-1") -> ScenarioSpec:
    return ScenarioSpec(
        identifier=identifier,
        tenant_id=tenant_id,
        name="Reference scenario",
        created_at=NOW,
        objectives=[
            Objective(
                identifier="obj-1",
                description="Maximize the primary metric",
                direction=ObjectiveDirection.MAXIMIZE,
                target=100.0,
                weight=1.0,
            )
        ],
        constraints=[Constraint(identifier="c-1", description="Stay within declared bounds")],
        time_horizon=TimeHorizon(start=NOW, end=LATER, resolution="step"),
        metrics=[
            MetricDefinition(
                identifier="m-1", name="Primary metric", unit="units", aggregation="mean"
            )
        ],
        assumptions=[
            Assumption(identifier="a-1", statement="Conditions remain stable", confidence=0.9)
        ],
        metadata={},
    )


def build_request(tenant_id: str = "tenant-1") -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        required_observations=[
            ObservationRequirement(metric_id="m-1", description="observe m-1", required=True),
            ObservationRequirement(metric_id="m-2", description="observe m-2", required=False),
        ],
        requested_at=NOW,
    )


def build_seed(identifier: str = "seed-1") -> ScenarioSeed:
    return ScenarioSeed(
        identifier=identifier, tenant_id="tenant-1", seed_value=f"value-{identifier}"
    )


def build_store() -> tuple[InMemoryScenarioStore, str]:
    """Store with one valid scenario compiled to a world; returns (store, world_id)."""
    store = InMemoryScenarioStore()
    store.put_scenario(build_scenario())
    compiled = compile_world(build_scenario())
    store.put_world(compiled.version, compiled.manifest)
    return store, compiled.version.identifier


def prepare_default(
    store: InMemoryScenarioStore,
    world_version_id: str,
    *,
    campaign_id: str = "campaign-1",
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    tenant_id: str = "tenant-1",
    legion: LegionAdapter | None = None,
) -> PreparedCampaign:
    return prepare_campaign(
        store=store,
        legion=legion if legion is not None else FakeLegionAdapter(tenant_id=tenant_id),
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        world_version_id=world_version_id,
        strategy_request=build_request(tenant_id),
        campaign_id=campaign_id,
        campaign_name="Reference campaign",
        seed_ensemble=seeds,
        created_at=NOW,
    )


class TestPrepareCampaign:
    def test_prepares_compiled_campaign_with_five_candidates(self) -> None:
        store, world_id = build_store()
        prepared = prepare_default(store, world_id, legion=MockLegionAdapter())
        assert len(prepared.campaign.strategy_candidate_ids) == 5
        assert prepared.campaign.strategy_candidate_ids == [
            "mock-baseline",
            "mock-conservative",
            "mock-balanced",
            "mock-adaptive",
            "mock-diversified",
        ]
        assert prepared.status.state is CampaignState.COMPILED
        assert prepared.status.campaign_id == "campaign-1"
        assert prepared.campaign.scenario_id == "scenario-1"
        assert prepared.campaign.world_version_id == world_id

    def test_run_plan_count_is_five_times_seed_count(self) -> None:
        store, world_id = build_store()
        seeds = (build_seed("seed-1"), build_seed("seed-2"), build_seed("seed-3"))
        prepared = prepare_default(store, world_id, seeds=seeds)
        assert len(prepared.run_plans) == 15
        assert len(prepared.run_plans) == 5 * len(seeds)

    def test_every_strategy_shares_seed_order_and_world(self) -> None:
        store, world_id = build_store()
        seeds = (build_seed("seed-1"), build_seed("seed-2"))
        prepared = prepare_default(store, world_id, seeds=seeds)
        seed_ids = [seed.identifier for seed in seeds]
        by_strategy: dict[str, list[str]] = {}
        for plan in prepared.run_plans:
            by_strategy.setdefault(plan.strategy_candidate_id, []).append(plan.scenario_seed_id)
        for _strategy_id, received in by_strategy.items():
            assert received == seed_ids
        assert {p.world_version_id for p in prepared.run_plans} == {world_id}

    def test_repeated_preparation_is_deterministic(self) -> None:
        store, world_id = build_store()
        first = prepare_default(store, world_id)
        second = prepare_default(store, world_id, campaign_id="campaign-2")
        assert first.campaign.strategy_candidate_ids == second.campaign.strategy_candidate_ids
        # Identifiers embed the campaign id, so compare the deterministic content:
        assert [p.input_hash for p in first.run_plans] == [p.input_hash for p in second.run_plans]
        assert [p.strategy_candidate_id for p in first.run_plans] == [
            p.strategy_candidate_id for p in second.run_plans
        ]
        assert [p.scenario_seed_id for p in first.run_plans] == [
            p.scenario_seed_id for p in second.run_plans
        ]
        assert [p.world_version_id for p in first.run_plans] == [
            p.world_version_id for p in second.run_plans
        ]

    def test_duplicate_campaign_identifier_rejected(self) -> None:
        store, world_id = build_store()
        prepare_default(store, world_id)
        with pytest.raises(CampaignAlreadyExistsError):
            prepare_default(store, world_id)

    def test_missing_scenario_rejected(self) -> None:
        store, world_id = build_store()
        with pytest.raises(ScenarioNotFoundError):
            prepare_campaign(
                store=store,
                legion=FakeLegionAdapter(),
                tenant_id="tenant-1",
                scenario_id="scenario-ghost",
                world_version_id=world_id,
                strategy_request=build_request(),
                campaign_id="campaign-1",
                campaign_name="x",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )

    def test_missing_world_rejected(self) -> None:
        store, _ = build_store()
        with pytest.raises(WorldNotFoundError):
            prepare_campaign(
                store=store,
                legion=FakeLegionAdapter(),
                tenant_id="tenant-1",
                scenario_id="scenario-1",
                world_version_id="world-ghost",
                strategy_request=build_request(),
                campaign_id="campaign-1",
                campaign_name="x",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )

    def test_world_scenario_mismatch_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(identifier="scenario-a"))
        store.put_scenario(build_scenario(identifier="scenario-b"))
        compiled = compile_world(build_scenario(identifier="scenario-a"))
        store.put_world(compiled.version, compiled.manifest)
        with pytest.raises(WorldScenarioMismatchError):
            prepare_campaign(
                store=store,
                legion=FakeLegionAdapter(),
                tenant_id="tenant-1",
                scenario_id="scenario-b",
                world_version_id=compiled.version.identifier,
                strategy_request=build_request(),
                campaign_id="campaign-1",
                campaign_name="x",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )

    def test_strategy_request_scenario_mismatch_rejected(self) -> None:
        store, world_id = build_store()
        request = build_request()
        request.scenario_id = "scenario-other"
        with pytest.raises(CampaignPreparationError):
            prepare_campaign(
                store=store,
                legion=FakeLegionAdapter(),
                tenant_id="tenant-1",
                scenario_id="scenario-1",
                world_version_id=world_id,
                strategy_request=request,
                campaign_id="campaign-1",
                campaign_name="x",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )

    def test_foreign_tenant_cannot_read_campaign(self) -> None:
        store, world_id = build_store()
        prepare_default(store, world_id)
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign("tenant-2", "campaign-1")
        with pytest.raises(CampaignNotFoundError):
            store.get_run_plans("tenant-2", "campaign-1")


class TestPreparationInvariants:
    def test_prepare_works_with_protocol_compatible_fake(self) -> None:
        """campaign_service must work with any LegionAdapter-compatible adapter."""
        store, world_id = build_store()
        fake = FakeLegionAdapter(tenant_id="tenant-1")
        prepared = prepare_default(store, world_id, legion=fake)
        assert len(prepared.campaign.strategy_candidate_ids) == 5
        assert len(prepared.run_plans) == 5

    def test_foreign_tenant_seeds_rejected(self) -> None:
        store, world_id = build_store()
        foreign_seed = ScenarioSeed(
            identifier="seed-foreign", tenant_id="tenant-2", seed_value="value"
        )
        with pytest.raises(CampaignPreparationError) as excinfo:
            prepare_default(store, world_id, seeds=(foreign_seed,))
        assert "seed" in str(excinfo.value) and "tenant" in str(excinfo.value)

    def test_foreign_tenant_strategy_request_rejected(self) -> None:
        store, world_id = build_store()
        with pytest.raises(CampaignPreparationError) as excinfo:
            prepare_campaign(
                store=store,
                legion=FakeLegionAdapter(tenant_id="tenant-1"),
                tenant_id="tenant-1",
                scenario_id="scenario-1",
                world_version_id=world_id,
                strategy_request=build_request(tenant_id="tenant-2"),
                campaign_id="campaign-1",
                campaign_name="x",
                seed_ensemble=(build_seed(),),
                created_at=NOW,
            )
        assert "strategy_request" in str(excinfo.value)

    def test_foreign_tenant_candidates_rejected(self) -> None:
        store, world_id = build_store()
        with pytest.raises(CampaignPreparationError) as excinfo:
            prepare_default(store, world_id, legion=FakeLegionAdapter(foreign_tenant=True))
        assert "candidate" in str(excinfo.value)

    def test_duplicate_candidate_ids_rejected(self) -> None:
        store, world_id = build_store()
        with pytest.raises(CampaignPreparationError) as excinfo:
            prepare_default(store, world_id, legion=FakeLegionAdapter(duplicate_ids=True))
        assert "unique" in str(excinfo.value)

    def test_wrong_candidate_count_rejected(self) -> None:
        store, world_id = build_store()
        with pytest.raises(CampaignPreparationError):
            prepare_default(store, world_id, legion=FakeLegionAdapter(candidate_count=4))

    def test_candidates_outside_requested_strategy_set_rejected(self) -> None:
        """A candidate with different observation permissions does not belong to
        the requested strategy set contract."""
        store, world_id = build_store()

        class ObservationDriftingFake(FakeLegionAdapter):
            def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
                candidates = super().request_strategies(request)
                drifted = []
                for candidate in candidates:
                    drifted.append(
                        candidate.model_copy(
                            update={
                                "required_observations": [
                                    ObservationRequirement(
                                        metric_id="m-999",
                                        description="unrequested observation",
                                    )
                                ]
                            }
                        )
                    )
                return tuple(drifted)

        with pytest.raises(CampaignPreparationError) as excinfo:
            prepare_default(store, world_id, legion=ObservationDriftingFake())
        assert "observation permissions" in str(excinfo.value)


class TestStartCampaign:
    def test_compiled_campaign_starts_to_running(self) -> None:
        store, world_id = build_store()
        prepare_default(store, world_id)
        status = start_campaign(
            store=store, tenant_id="tenant-1", campaign_id="campaign-1", changed_at=LATER
        )
        assert status.state is CampaignState.RUNNING
        assert store.get_campaign_status("tenant-1", "campaign-1").state is CampaignState.RUNNING
        assert len(store.get_run_plans("tenant-1", "campaign-1")) == 5

    def test_only_compiled_can_transition_to_running(self) -> None:
        store = InMemoryScenarioStore()
        scenario = build_scenario()
        store.put_scenario(scenario)
        compiled = compile_world(scenario)
        store.put_world(compiled.version, compiled.manifest)
        prepared = prepare_default(store, compiled.version.identifier)
        # force an invalid state by direct store manipulation (test-only)
        store.update_campaign_status(
            "tenant-1",
            "campaign-1",
            CampaignStatus(
                identifier=prepared.status.identifier,
                tenant_id="tenant-1",
                campaign_id="campaign-1",
                state=CampaignState.DRAFT,
                changed_at=NOW,
            ),
        )
        with pytest.raises(CampaignTransitionError):
            start_campaign(
                store=store, tenant_id="tenant-1", campaign_id="campaign-1", changed_at=LATER
            )

    def test_start_does_not_generate_outcomes_or_events(self) -> None:
        store, world_id = build_store()
        prepare_default(store, world_id)
        start_campaign(
            store=store, tenant_id="tenant-1", campaign_id="campaign-1", changed_at=LATER
        )
        # Planning state is untouched and no simulation artifacts exist anywhere.
        plans = store.get_run_plans("tenant-1", "campaign-1")
        assert all(plan.planned_state == "planned" for plan in plans)
        status = store.get_campaign_status("tenant-1", "campaign-1")
        assert status.state is CampaignState.RUNNING
        assert status.message == "campaign started"

    def test_start_unknown_campaign_rejected(self) -> None:
        store, _ = build_store()
        with pytest.raises(CampaignNotFoundError):
            start_campaign(
                store=store, tenant_id="tenant-1", campaign_id="campaign-ghost", changed_at=LATER
            )
