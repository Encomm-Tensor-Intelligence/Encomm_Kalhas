"""Tests for in-memory storage, semantic validation, and world compilation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import (
    InvalidScenarioError,
    ScenarioAlreadyExistsError,
    ScenarioNotFoundError,
    WorldNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.scenario_service import validate_scenario
from kalhas.application.world_compiler import COMPILER_VERSION, compile_world, content_hash
from kalhas.contracts.v1.scenario import (
    Constraint,
    Objective,
    ObjectiveDirection,
    ScenarioSpec,
    TimeHorizon,
)
from kalhas.contracts.v1.shared import Assumption, MetricDefinition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)


def build_scenario(
    *,
    identifier: str = "scenario-1",
    tenant_id: str = "tenant-1",
    with_objectives: bool = True,
    with_constraints: bool = True,
    with_metrics: bool = True,
    with_resolution: bool = True,
) -> ScenarioSpec:
    """Build a scenario; omit parts to make it semantically incomplete."""
    return ScenarioSpec(
        identifier=identifier,
        tenant_id=tenant_id,
        name="Reference scenario",
        description="Domain-neutral scenario",
        created_at=NOW,
        objectives=(
            [
                Objective(
                    identifier="obj-1",
                    description="Maximize the primary metric",
                    direction=ObjectiveDirection.MAXIMIZE,
                    target=100.0,
                    weight=1.0,
                )
            ]
            if with_objectives
            else []
        ),
        constraints=(
            [Constraint(identifier="c-1", description="Stay within declared bounds", hard=True)]
            if with_constraints
            else []
        ),
        time_horizon=TimeHorizon(
            start=NOW, end=LATER, resolution="step" if with_resolution else None
        ),
        metrics=(
            [
                MetricDefinition(
                    identifier="m-1",
                    name="Primary metric",
                    unit="units",
                    aggregation="mean",
                )
            ]
            if with_metrics
            else []
        ),
        assumptions=[
            Assumption(identifier="a-1", statement="Conditions remain stable", confidence=0.9)
        ],
        metadata={},
    )


class TestInMemoryStore:
    def test_put_and_get_scenario_round_trip(self) -> None:
        store = InMemoryScenarioStore()
        scenario = build_scenario()
        store.put_scenario(scenario)
        assert store.get_scenario("tenant-1", "scenario-1") == scenario

    def test_duplicate_scenario_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario())
        with pytest.raises(ScenarioAlreadyExistsError):
            store.put_scenario(build_scenario())

    def test_duplicate_across_tenants_allowed(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(tenant_id="tenant-1"))
        store.put_scenario(build_scenario(tenant_id="tenant-2"))
        assert store.get_scenario("tenant-2", "scenario-1").tenant_id == "tenant-2"

    def test_lookup_by_foreign_tenant_rejected(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_scenario(tenant_id="tenant-1"))
        with pytest.raises(ScenarioNotFoundError):
            store.get_scenario("tenant-2", "scenario-1")

    def test_world_round_trip_and_foreign_tenant(self) -> None:
        store = InMemoryScenarioStore()
        compiled = compile_world(build_scenario())
        store.put_world(compiled.version, compiled.manifest)
        assert store.get_world("tenant-1", compiled.version.identifier) == compiled.version
        assert store.get_manifest("tenant-1", compiled.version.identifier) == compiled.manifest
        with pytest.raises(WorldNotFoundError):
            store.get_world("tenant-2", compiled.version.identifier)
        with pytest.raises(WorldNotFoundError):
            store.get_world("tenant-1", "world-does-not-exist")


class TestSemanticValidation:
    def test_complete_scenario_is_valid_without_questions(self) -> None:
        result = validate_scenario(build_scenario(), validated_at=NOW)
        assert result.report.valid is True
        assert result.report.issues == []
        assert result.questions == []

    def test_missing_objectives_raises_issue_and_question(self) -> None:
        result = validate_scenario(build_scenario(with_objectives=False), validated_at=NOW)
        assert result.report.valid is False
        codes = {issue.code for issue in result.report.issues}
        assert "missing_objectives" in codes
        prompts = {question.prompt for question in result.questions}
        assert "Which objectives should this scenario pursue?" in prompts
        question = next(q for q in result.questions if q.identifier == "q-missing_objectives")
        assert question.targets == ["objectives"]
        assert question.required is True
        assert question.tenant_id == "tenant-1"

    def test_missing_resolution_raises_time_horizon_issue(self) -> None:
        result = validate_scenario(build_scenario(with_resolution=False), validated_at=NOW)
        codes = {issue.code for issue in result.report.issues}
        assert "missing_time_horizon" in codes
        question = next(q for q in result.questions if q.identifier == "q-missing_time_horizon")
        assert question.targets == ["time_horizon.resolution"]
        assert "temporal resolution" in question.prompt.lower()

    def test_missing_metrics_and_constraints_raise_issues(self) -> None:
        result = validate_scenario(
            build_scenario(with_metrics=False, with_constraints=False), validated_at=NOW
        )
        codes = {issue.code for issue in result.report.issues}
        assert {"missing_success_metrics", "missing_constraints"} <= codes
        assert len(result.questions) == 2

    def test_validation_never_invents_values(self) -> None:
        result = validate_scenario(build_scenario(with_objectives=False), validated_at=NOW)
        for issue in result.report.issues:
            assert "target" not in issue.message.lower() and "value" not in issue.message.lower()


class TestWorldCompiler:
    def test_compile_rejects_invalid_scenario_with_report(self) -> None:
        scenario = build_scenario(with_objectives=False)
        with pytest.raises(InvalidScenarioError) as excinfo:
            compile_world(scenario)
        assert excinfo.value.report.valid is False
        assert excinfo.value.report.subject_id == "scenario-1"

    def test_compile_produces_world_and_manifest(self) -> None:
        compiled = compile_world(build_scenario())
        version = compiled.version
        manifest = compiled.manifest
        assert isinstance(version, WorldVersion)
        assert isinstance(manifest, WorldManifest)
        assert version.source_scenario_id == "scenario-1"
        assert version.compiler_version == COMPILER_VERSION
        assert version.created_at == NOW
        assert version.parent_version_id is None
        assert manifest.world_version_id == version.identifier
        assert manifest.tenant_id == "tenant-1"

    def test_manifest_entity_count_is_zero_with_declared_counts(self) -> None:
        """The generic compiler compiles scenario elements, not entities."""
        manifest = compile_world(build_scenario()).manifest
        assert manifest.entity_count == 0
        assert manifest.state["declared_objective_count"] == 1
        assert manifest.state["declared_constraint_count"] == 1
        assert manifest.state["declared_metric_count"] == 1
        assert manifest.state["declared_assumption_count"] == 1
        assert manifest.state["declared_objective_ids"] == ["obj-1"]

    def test_manifest_counts_reflect_declared_contents(self) -> None:
        scenario = ScenarioSpec(
            identifier="scenario-2",
            tenant_id="tenant-1",
            name="Multi-element scenario",
            created_at=NOW,
            objectives=[
                Objective(
                    identifier="obj-1",
                    description="First objective",
                    direction=ObjectiveDirection.MAXIMIZE,
                ),
                Objective(
                    identifier="obj-2",
                    description="Second objective",
                    direction=ObjectiveDirection.MINIMIZE,
                ),
            ],
            constraints=[Constraint(identifier="c-1", description="One constraint")],
            time_horizon=TimeHorizon(start=NOW, end=LATER, resolution="step"),
            metrics=[
                MetricDefinition(identifier="m-1", name="Metric one"),
                MetricDefinition(identifier="m-2", name="Metric two"),
            ],
            assumptions=[
                Assumption(identifier="a-1", statement="First", confidence=0.9),
                Assumption(identifier="a-2", statement="Second", confidence=0.8),
                Assumption(identifier="a-3", statement="Third", confidence=0.7),
            ],
            metadata={},
        )
        manifest = compile_world(scenario).manifest
        assert manifest.entity_count == 0
        assert manifest.state["declared_objective_count"] == 2
        assert manifest.state["declared_constraint_count"] == 1
        assert manifest.state["declared_metric_count"] == 2
        assert manifest.state["declared_assumption_count"] == 3
        assert manifest.state["declared_objective_ids"] == ["obj-1", "obj-2"]

    def test_compile_is_deterministic(self) -> None:
        first = compile_world(build_scenario())
        second = compile_world(build_scenario())
        assert first.version.identifier == second.version.identifier
        assert first.version.content_hash == second.version.content_hash
        assert first.manifest == second.manifest
        assert first.version.content_hash == content_hash(build_scenario())

    def test_compile_differs_across_compiler_versions(self) -> None:
        first = compile_world(build_scenario(), compiler_version="1.0.0")
        second = compile_world(build_scenario(), compiler_version="1.0.1")
        assert first.version.identifier != second.version.identifier

    def test_compiled_world_is_immutable(self) -> None:
        compiled = compile_world(build_scenario())
        with pytest.raises(ValidationError):
            compiled.version.world = {"tampered": True}

    def test_compile_has_no_wall_clock_dependence(self) -> None:
        """Compilation output must not change with the current time."""
        compiled = compile_world(build_scenario())
        assert compiled.version.created_at == NOW
        assert compiled.version.content_hash == content_hash(build_scenario())
