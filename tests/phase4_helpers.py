"""Shared helpers for Phase 4 execution and replay tests."""

from __future__ import annotations

from datetime import UTC, datetime

from kalhas.adapters.legion import LegionAdapter
from kalhas.application.campaign_service import PreparedCampaign, prepare_campaign, start_campaign
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import LEGACY_STRUCTURAL_RUNTIME_VERSION
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.campaign import CampaignStatus
from kalhas.contracts.v1.execution import RunStatus
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

TENANT = "tenant-1"


def build_scenario(*, identifier: str = "scenario-1", tenant_id: str = TENANT) -> ScenarioSpec:
    return ScenarioSpec(
        identifier=identifier,
        tenant_id=tenant_id,
        name="Reference scenario",
        description="Domain-neutral scenario",
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
        metrics=[MetricDefinition(identifier="m-1", name="Primary metric")],
        assumptions=[
            Assumption(identifier="a-1", statement="Conditions remain stable", confidence=0.9)
        ],
        metadata={},
    )


def build_seed(*, identifier: str = "seed-1", tenant_id: str = TENANT) -> ScenarioSeed:
    return ScenarioSeed(
        identifier=identifier, tenant_id=tenant_id, algorithm="deterministic", seed_value="v1"
    )


def build_request(tenant_id: str = TENANT) -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        required_observations=[ObservationRequirement(metric_id="m-1", description="observe m-1")],
        requested_at=NOW,
    )


def build_store(*, tenant_id: str = TENANT) -> tuple[InMemoryScenarioStore, str]:
    """Store a scenario + compiled world; returns (store, world_version_id)."""
    store = InMemoryScenarioStore()
    scenario = build_scenario(tenant_id=tenant_id)
    store.put_scenario(scenario)
    compiled = compile_world(scenario)
    store.put_world(compiled.version, compiled.manifest)
    return store, compiled.version.identifier


def prepare(
    store: InMemoryScenarioStore,
    world_version_id: str,
    *,
    campaign_id: str = "campaign-1",
    tenant_id: str = TENANT,
    legion: LegionAdapter | None = None,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    runtime_version: str = LEGACY_STRUCTURAL_RUNTIME_VERSION,
) -> PreparedCampaign:
    """Prepare a campaign under a recorded runtime version.

    Defaults to the legacy structural runtime ("1.0.0") so the
    pre-Phase 16 structural execution/replay suites keep their exact
    behavior; trajectory-runtime (2.0.0) tests pass
    ``runtime_version="2.0.0"`` explicitly.
    """
    return prepare_campaign(
        store=store,
        legion=legion if legion is not None else _DefaultFakeLegion(tenant_id),
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        world_version_id=world_version_id,
        strategy_request=build_request(tenant_id),
        campaign_id=campaign_id,
        campaign_name="Reference campaign",
        seed_ensemble=seeds,
        created_at=NOW,
        runtime_version=runtime_version,
    )


class _DefaultFakeLegion:
    """Minimal protocol-compatible fake used when no adapter is supplied."""

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        return tuple(
            StrategyCandidate(
                identifier=f"fake-{index}",
                tenant_id=self._tenant_id,
                strategy_version="1.0.0",
                policy=PolicyDeclaration(summary=f"fake policy {index}", rules=[]),
                required_observations=list(request.required_observations),
                assumptions=[],
            )
            for index in range(5)
        )

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        """Deterministic fallback: propose the available transitions in order."""
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=tuple(
                transition.identifier for transition in request.available_transitions
            ),
        )


def start(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> CampaignStatus:
    return start_campaign(store=store, tenant_id=TENANT, campaign_id=campaign_id, changed_at=NOW)


def execute(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> tuple[RunStatus, ...]:
    return execute_campaign(store=store, tenant_id=TENANT, campaign_id=campaign_id)
