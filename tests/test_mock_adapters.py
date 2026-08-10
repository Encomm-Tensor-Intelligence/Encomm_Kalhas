"""Tests for the local deterministic mock adapters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_errors import InvalidScenarioError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.scenario import (
    Constraint,
    Objective,
    ObjectiveDirection,
    ScenarioSpec,
    TimeHorizon,
)
from kalhas.contracts.v1.shared import Assumption, MetricDefinition
from kalhas.contracts.v1.strategy import ObservationRequirement, StrategyRequest

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)


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


class TestMockNexusAdapter:
    def test_standalone_flow_submit_validate_compile(self) -> None:
        adapter = MockNexusAdapter(InMemoryScenarioStore())
        adapter.submit_scenario(build_scenario())

        result = adapter.validate_scenario("tenant-1", "scenario-1")
        assert result.report.valid is True
        assert adapter.clarification_questions("tenant-1", "scenario-1") == []

        compiled = adapter.compile_scenario("tenant-1", "scenario-1")
        assert compiled.version.source_scenario_id == "scenario-1"

        fetched = adapter.world("tenant-1", compiled.version.identifier)
        assert fetched == compiled.version
        manifest = adapter.manifest("tenant-1", compiled.version.identifier)
        assert manifest.world_version_id == compiled.version.identifier

    def test_compile_surfaces_questions_for_incomplete_scenario(self) -> None:
        adapter = MockNexusAdapter(InMemoryScenarioStore())
        incomplete = build_scenario().model_copy(deep=True)
        incomplete.objectives = []
        adapter.submit_scenario(incomplete)

        questions = adapter.clarification_questions("tenant-1", "scenario-1")
        assert [q.identifier for q in questions] == ["q-missing_objectives"]
        with pytest.raises(InvalidScenarioError):
            adapter.compile_scenario("tenant-1", "scenario-1")

    def test_compile_is_idempotent_in_store(self) -> None:
        adapter = MockNexusAdapter(InMemoryScenarioStore())
        adapter.submit_scenario(build_scenario())
        first = adapter.compile_scenario("tenant-1", "scenario-1")
        second = adapter.compile_scenario("tenant-1", "scenario-1")
        assert first.version.identifier == second.version.identifier
        assert adapter.world("tenant-1", first.version.identifier) == first.version


class TestMockLegionAdapter:
    def test_returns_exactly_five_deterministic_candidates(self) -> None:
        adapter = MockLegionAdapter()
        first = adapter.request_strategies(build_request())
        second = adapter.request_strategies(build_request())
        assert len(first) == 5
        assert [candidate.identifier for candidate in first] == [
            "mock-baseline",
            "mock-conservative",
            "mock-balanced",
            "mock-adaptive",
            "mock-diversified",
        ]
        assert [c.model_dump() for c in first] == [c.model_dump() for c in second]

    def test_candidates_are_versioned_with_declared_policies(self) -> None:
        adapter = MockLegionAdapter()
        candidates = adapter.request_strategies(build_request())
        for candidate in candidates:
            assert candidate.strategy_version == "1.0.0"
            assert candidate.policy.summary
            assert len(candidate.policy.rules) >= 1
            assert len(candidate.assumptions) >= 1

    def test_all_candidates_share_identical_observation_permissions(self) -> None:
        adapter = MockLegionAdapter()
        request = build_request()
        candidates = adapter.request_strategies(request)
        expected = [obs.model_dump() for obs in request.required_observations]
        for candidate in candidates:
            assert [obs.model_dump() for obs in candidate.required_observations] == expected
        assert len({len(c.required_observations) for c in candidates}) == 1

    def test_no_policy_execution(self) -> None:
        """Candidates are pure data: rules are declarative strings plus parameters."""
        adapter = MockLegionAdapter()
        for candidate in adapter.request_strategies(build_request()):
            for rule in candidate.policy.rules:
                assert rule.statement
                assert set(rule.parameters) <= {"aggressiveness"}
