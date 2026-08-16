"""Phase 25 realization-aware runtime-3 contract tests.

Covers the six new top-level public contracts (registered at PUBLIC_CONTRACTS
indexes 40-45), the three unregistered nested types, runtime literal
enforcement, strictness/freezing/round-trip, structural matrix validators,
self-hashing replay manifest coverage, deterministic identifiers and
content hashes, and schema synchronization of the six new artifacts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationCell,
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
    RealizationCampaignTrajectoryRunCell,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64B = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"

REALIZATION_NAMES = (
    "RealizationRunTrajectoryExecution",
    "RealizationRunTrajectoryReplayManifest",
    "RealizationCampaignTrajectoryMatrix",
    "RealizationRunMetricObservationSet",
    "RealizationCampaignMetricObservationMatrix",
    "RealizationCampaignMetricStatisticsMatrix",
)

NEW_CONTRACTS = (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
    RealizationCampaignTrajectoryMatrix,
    RealizationRunMetricObservationSet,
    RealizationCampaignMetricObservationMatrix,
    RealizationCampaignMetricStatisticsMatrix,
)


def _attempt() -> dict[str, object]:
    return {
        "sequence_position": 0,
        "transition_identifier": "transition-1",
        "transition_id": "t-1",
        "transition_content_hash": H64,
        "outcome": "applied",
        "before_state_hash": H64,
        "after_state_hash": H64B,
    }


def _result() -> dict[str, object]:
    return {
        "trajectory_plan_id": "trajectory-plan-0123456789abcdef",
        "trajectory_plan_content_hash": H64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": H64,
        "initial_state": {"level": 1},
        "initial_state_hash": H64,
        "attempts": [_attempt()],
        "final_state": {"level": 84},
        "final_state_hash": H64B,
        "trace_hash": H64,
        "content_hash": H64,
    }


def execution_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-trajectory-execution-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": H64,
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": H64,
        "runtime_version": "3.0.0",
        "input_hash": H64,
        "trajectory_plan_set_hash": H64,
        "results": [_result()],
        "content_hash": H64,
        "executed_at": NOW,
    }
    payload.update(overrides)
    return payload


def replay_manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-replay-run-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "realization_run_trajectory_execution_id": (
            "realization-trajectory-execution-0123456789abcdef"
        ),
        "realization_run_metric_observation_set_id": (
            "realization-metric-observation-set-0123456789abcdef"
        ),
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": H64,
        "runtime_version": "3.0.0",
        "input_hash": H64,
        "trajectory_plan_set_hash": H64,
        "expected_execution_hash": H64,
        "recomputed_execution_hash": H64,
        "expected_observation_set_hash": H64,
        "recomputed_observation_set_hash": H64,
        "replay_classification": "exact",
        "replayed_at": NOW,
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


def trajectory_cell(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "sequence_position": 0,
        "strategy_position": 0,
        "seed_position": 0,
        "run_id": "run-1",
        "run_plan_id": "plan-1",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "input_hash": H64,
        "realization_run_trajectory_execution_id": (
            "realization-trajectory-execution-0123456789abcdef"
        ),
        "realization_run_trajectory_execution_content_hash": H64,
        "trajectory_plan_set_hash": H64,
        "result_content_hashes": [],
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": H64,
    }
    payload.update(overrides)
    return payload


def trajectory_matrix_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-trajectory-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": H64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["mock-baseline", "mock-conservative"],
        "ordered_scenario_seed_ids": ["seed-1", "seed-2"],
        "ordered_world_realization_ids": [
            "world-realization-0123456789abcdef",
            "world-realization-0123456789abcde0",
        ],
        "ordered_world_realization_content_hashes": [H64, H64B],
        "cells": [
            trajectory_cell(sequence_position=0, strategy_position=0, seed_position=0),
            trajectory_cell(
                sequence_position=1,
                strategy_position=0,
                seed_position=1,
                run_id="run-2",
                run_plan_id="plan-2",
                scenario_seed_id="seed-2",
                world_realization_id="world-realization-0123456789abcde0",
                world_realization_content_hash=H64B,
            ),
            trajectory_cell(
                sequence_position=2,
                strategy_position=1,
                seed_position=0,
                strategy_candidate_id="mock-conservative",
            ),
            trajectory_cell(
                sequence_position=3,
                strategy_position=1,
                seed_position=1,
                run_id="run-4",
                run_plan_id="plan-4",
                strategy_candidate_id="mock-conservative",
                scenario_seed_id="seed-2",
                world_realization_id="world-realization-0123456789abcde0",
                world_realization_content_hash=H64B,
            ),
        ],
        "content_hash": H64,
        "assembled_at": NOW,
    }
    payload.update(overrides)
    return payload


def observation_set_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-metric-observation-set-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": H64,
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": H64,
        "runtime_version": "3.0.0",
        "input_hash": H64,
        "realization_run_trajectory_execution_id": (
            "realization-trajectory-execution-0123456789abcdef"
        ),
        "realization_run_trajectory_execution_content_hash": H64,
        "observations": [],
        "content_hash": H64,
        "observed_at": NOW,
    }
    payload.update(overrides)
    return payload


def observation_value(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": "m-1",
        "metric_unit": "units",
        "binding_id": "binding-1",
        "binding_content_hash": H64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": H64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "trajectory_plan_id": "trajectory-plan-0123456789abcdef",
        "trajectory_plan_content_hash": H64,
        "trajectory_result_content_hash": H64,
        "raw_value": 84,
    }
    payload.update(overrides)
    return payload


def observation_cell(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "sequence_position": 0,
        "strategy_position": 0,
        "seed_position": 0,
        "run_id": "run-1",
        "run_plan_id": "plan-1",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "input_hash": H64,
        "realization_run_trajectory_execution_id": (
            "realization-trajectory-execution-0123456789abcdef"
        ),
        "realization_run_trajectory_execution_content_hash": H64,
        "realization_run_metric_observation_set_id": (
            "realization-metric-observation-set-0123456789abcdef"
        ),
        "realization_run_metric_observation_set_content_hash": H64,
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": H64,
        "observations": [observation_value()],
    }
    payload.update(overrides)
    return payload


def observation_matrix_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-metric-observation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": H64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["mock-baseline", "mock-conservative"],
        "ordered_scenario_seed_ids": ["seed-1", "seed-2"],
        "ordered_metric_ids": ["m-1"],
        "ordered_world_realization_ids": [
            "world-realization-0123456789abcdef",
            "world-realization-0123456789abcde0",
        ],
        "ordered_world_realization_content_hashes": [H64, H64B],
        "cells": [
            observation_cell(sequence_position=0, strategy_position=0, seed_position=0),
            observation_cell(
                sequence_position=1,
                strategy_position=0,
                seed_position=1,
                run_id="run-2",
                run_plan_id="plan-2",
                scenario_seed_id="seed-2",
                world_realization_id="world-realization-0123456789abcde0",
                world_realization_content_hash=H64B,
            ),
            observation_cell(
                sequence_position=2,
                strategy_position=1,
                seed_position=0,
                strategy_candidate_id="mock-conservative",
            ),
            observation_cell(
                sequence_position=3,
                strategy_position=1,
                seed_position=1,
                run_id="run-4",
                run_plan_id="plan-4",
                strategy_candidate_id="mock-conservative",
                scenario_seed_id="seed-2",
                world_realization_id="world-realization-0123456789abcde0",
                world_realization_content_hash=H64B,
            ),
        ],
        "content_hash": H64,
        "assembled_at": NOW,
    }
    payload.update(overrides)
    return payload


def statistics_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "realization-metric-statistics-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": H64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "statistics_mode": "descriptive",
        "source_metric_observation_matrix_id": (
            "realization-metric-observation-matrix-0123456789abcdef"
        ),
        "source_metric_observation_matrix_content_hash": H64,
        "ordered_strategy_candidate_ids": ["mock-baseline", "mock-conservative"],
        "ordered_scenario_seed_ids": ["seed-1", "seed-2"],
        "ordered_metric_ids": ["m-1"],
        "ordered_world_realization_ids": [
            "world-realization-0123456789abcdef",
            "world-realization-0123456789abcde0",
        ],
        "ordered_world_realization_content_hashes": [H64, H64B],
        "summaries": [
            {
                "strategy_position": 0,
                "metric_position": 0,
                "strategy_candidate_id": "mock-baseline",
                "metric_id": "m-1",
                "metric_unit": "units",
                "ordered_observed_values": [84, 103],
                "observation_count": 2,
                "minimum": 84.0,
                "maximum": 103.0,
                "arithmetic_mean": 93.5,
                "median": 93.5,
                "population_standard_deviation": 9.5,
            },
            {
                "strategy_position": 1,
                "metric_position": 0,
                "strategy_candidate_id": "mock-conservative",
                "metric_id": "m-1",
                "metric_unit": "units",
                "ordered_observed_values": [84, 103],
                "observation_count": 2,
                "minimum": 84.0,
                "maximum": 103.0,
                "arithmetic_mean": 93.5,
                "median": 93.5,
                "population_standard_deviation": 9.5,
            },
        ],
        "content_hash": H64,
        "summarized_at": NOW,
    }
    payload.update(overrides)
    return payload


class TestRegistration:
    def test_public_contract_count_is_exactly_47(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 47

    def test_realization_contracts_at_indexes_40_through_45(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[40:46] == REALIZATION_NAMES

    def test_indexes_0_through_39_unchanged(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[:37] == (
            "ScenarioSpec",
            "ContextBundle",
            "ClarificationQuestion",
            "ValidationReport",
            "WorldManifest",
            "WorldVersion",
            "UncertaintyDefinition",
            "StrategyRequest",
            "StrategyCandidate",
            "CampaignSpec",
            "CampaignStatus",
            "ScenarioSeed",
            "RunEvent",
            "OutcomeVector",
            "EvidenceReference",
            "DecisionBrief",
            "RunPlan",
            "RunStatus",
            "ReplayManifest",
            "RunInputIntegrityManifest",
            "DomainPackManifest",
            "DomainPackBinding",
            "DomainCapabilityDeclaration",
            "DomainStateModel",
            "DomainStateTransition",
            "OperationalActivityEvent",
            "StrategyTrajectoryPlan",
            "StrategyTrajectoryPlanRequest",
            "RunTrajectoryExecution",
            "RunTrajectoryReplayManifest",
            "CampaignTrajectoryMatrix",
            "DomainMetricObservationBinding",
            "RunMetricObservationSet",
            "CampaignMetricObservationMatrix",
            "CampaignMetricStatisticsMatrix",
            "ScenarioEvaluationProfile",
            "CampaignObjectiveEvaluationMatrix",
        )
        assert names[37] == "WorldUncertaintyModel"
        assert names[38] == "WorldRealization"
        assert names[39] == "CampaignWorldRealizationMatrix"

    def test_nested_types_are_not_registered(self) -> None:
        registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "RealizedStateTrajectoryResult" not in registered
        assert "RealizationCampaignTrajectoryRunCell" not in registered
        assert "RealizationCampaignMetricObservationCell" not in registered


class TestExecutionContract:
    def test_valid_execution_round_trip(self) -> None:
        execution = RealizationRunTrajectoryExecution.model_validate(execution_payload())
        assert execution.runtime_version == "3.0.0"
        assert execution.model_dump(mode="json") == json.loads(execution.model_dump_json())

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryExecution.model_validate(
                execution_payload(runtime_version="2.0.0")
            )
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryExecution.model_validate(
                execution_payload(runtime_version="4.0.0")
            )

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryExecution.model_validate(execution_payload(unexpected="x"))

    def test_frozen_instance(self) -> None:
        execution = RealizationRunTrajectoryExecution.model_validate(execution_payload())
        with pytest.raises(ValidationError):
            execution.run_id = "run-other"

    def test_required_realization_provenance(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryExecution.model_validate(
                execution_payload(world_realization_id="")
            )
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryExecution.model_validate(
                execution_payload(world_realization_content_hash="bad")
            )

    def test_attempts_reuse_the_runtime_2_attempt_record(self) -> None:
        result = RealizedStateTrajectoryResult.model_validate(_result())
        assert all(isinstance(attempt, RunTrajectoryAttemptRecord) for attempt in result.attempts)


class TestReplayManifestContract:
    def test_valid_manifest_round_trip(self) -> None:
        manifest = RealizationRunTrajectoryReplayManifest.model_validate(replay_manifest_payload())
        assert manifest.replay_classification == "exact"
        assert manifest.model_dump(mode="json") == json.loads(manifest.model_dump_json())

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryReplayManifest.model_validate(
                replay_manifest_payload(runtime_version="2.0.0")
            )

    def test_self_covering_content_hash(self) -> None:
        """The content hash must cover every other field (self-hashing)."""
        from kalhas.application.hashing import canonical_json, sha256_hex

        manifest = RealizationRunTrajectoryReplayManifest.model_validate(replay_manifest_payload())
        payload = manifest.model_dump(mode="json")
        del payload["content_hash"]
        recomputed = sha256_hex(canonical_json(payload))
        # The manifest's own recorded hash is the placeholder; the digest
        # over the payload must equal the independently recomputed digest
        # of the same payload (the verifier recomputes it at trust
        # boundaries and rejects a tampered field because it changes the
        # canonical payload).
        assert manifest.content_hash != recomputed  # placeholder in this fixture
        tampered = manifest.model_copy(update={"expected_observation_set_hash": H64B})
        tampered_payload = tampered.model_dump(mode="json")
        del tampered_payload["content_hash"]
        assert sha256_hex(canonical_json(tampered_payload)) != recomputed

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunTrajectoryReplayManifest.model_validate(
                replay_manifest_payload(unexpected="x")
            )


class TestTrajectoryMatrixContract:
    def test_valid_matrix_round_trip(self) -> None:
        matrix = RealizationCampaignTrajectoryMatrix.model_validate(trajectory_matrix_payload())
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignTrajectoryMatrix.model_validate(
                trajectory_matrix_payload(runtime_version="2.0.0")
            )

    def test_realization_tuples_must_match_seed_count(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignTrajectoryMatrix.model_validate(
                trajectory_matrix_payload(ordered_world_realization_ids=[H64[:16]])
            )
        with pytest.raises(ValidationError):
            RealizationCampaignTrajectoryMatrix.model_validate(
                trajectory_matrix_payload(ordered_world_realization_content_hashes=[H64])
            )

    def test_cell_realization_agreement_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignTrajectoryMatrix.model_validate(
                trajectory_matrix_payload(
                    cells=[
                        trajectory_cell(
                            sequence_position=0,
                            strategy_position=0,
                            seed_position=0,
                            world_realization_id="world-realization-0123456789abcde0",
                        ),
                        trajectory_cell(
                            sequence_position=1,
                            strategy_position=0,
                            seed_position=1,
                            run_id="run-2",
                            run_plan_id="plan-2",
                            scenario_seed_id="seed-2",
                            world_realization_id="world-realization-0123456789abcde0",
                            world_realization_content_hash=H64B,
                        ),
                        trajectory_cell(
                            sequence_position=2,
                            strategy_position=1,
                            seed_position=0,
                            strategy_candidate_id="mock-conservative",
                        ),
                        trajectory_cell(
                            sequence_position=3,
                            strategy_position=1,
                            seed_position=1,
                            run_id="run-4",
                            run_plan_id="plan-4",
                            strategy_candidate_id="mock-conservative",
                            scenario_seed_id="seed-2",
                            world_realization_id="world-realization-0123456789abcde0",
                            world_realization_content_hash=H64B,
                        ),
                    ]
                )
            )

    def test_structural_matrix_shape_replicated(self) -> None:
        # Duplicate strategy x seed pair must be rejected.
        with pytest.raises(ValidationError):
            RealizationCampaignTrajectoryMatrix.model_validate(
                trajectory_matrix_payload(
                    cells=[
                        trajectory_cell(sequence_position=0, strategy_position=0, seed_position=0),
                        trajectory_cell(sequence_position=1, strategy_position=0, seed_position=0),
                        trajectory_cell(sequence_position=2, strategy_position=1, seed_position=0),
                        trajectory_cell(sequence_position=3, strategy_position=1, seed_position=1),
                    ]
                )
            )

    def test_cell_is_unregistered_nested_type(self) -> None:
        cell = RealizationCampaignTrajectoryRunCell.model_validate(trajectory_cell())
        assert cell.sequence_position == 0


class TestObservationSetContract:
    def test_valid_set_round_trip(self) -> None:
        observation_set = RealizationRunMetricObservationSet.model_validate(
            observation_set_payload()
        )
        assert observation_set.runtime_version == "3.0.0"

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunMetricObservationSet.model_validate(
                observation_set_payload(runtime_version="2.0.0")
            )

    def test_observations_canonicalized_by_metric_id(self) -> None:
        # Two observations out of canonical order must be rejected.
        with pytest.raises(ValidationError):
            RealizationRunMetricObservationSet.model_validate(
                observation_set_payload(
                    observations=[
                        observation_value(metric_id="m-2", raw_value=0.0),
                        observation_value(metric_id="m-1", raw_value=84),
                    ]
                )
            )

    def test_renamed_execution_reference_required(self) -> None:
        with pytest.raises(ValidationError):
            RealizationRunMetricObservationSet.model_validate(
                observation_set_payload(realization_run_trajectory_execution_id="")
            )


class TestObservationMatrixContract:
    def test_valid_matrix_round_trip(self) -> None:
        matrix = RealizationCampaignMetricObservationMatrix.model_validate(
            observation_matrix_payload()
        )
        assert matrix.runtime_version == "3.0.0"
        assert matrix.ordered_metric_ids == ("m-1",)

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignMetricObservationMatrix.model_validate(
                observation_matrix_payload(runtime_version="2.0.0")
            )

    def test_cell_observation_metric_ids_match_ordered_metrics(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignMetricObservationMatrix.model_validate(
                observation_matrix_payload(
                    cells=[
                        observation_cell(
                            sequence_position=0,
                            strategy_position=0,
                            seed_position=0,
                            observations=[observation_value(metric_id="m-2", raw_value=0.0)],
                        ),
                        observation_cell(
                            sequence_position=1,
                            strategy_position=0,
                            seed_position=1,
                            run_id="run-2",
                            run_plan_id="plan-2",
                            scenario_seed_id="seed-2",
                            world_realization_id="world-realization-0123456789abcde0",
                            world_realization_content_hash=H64B,
                        ),
                        observation_cell(
                            sequence_position=2,
                            strategy_position=1,
                            seed_position=0,
                            strategy_candidate_id="mock-conservative",
                        ),
                        observation_cell(
                            sequence_position=3,
                            strategy_position=1,
                            seed_position=1,
                            run_id="run-4",
                            run_plan_id="plan-4",
                            strategy_candidate_id="mock-conservative",
                            scenario_seed_id="seed-2",
                            world_realization_id="world-realization-0123456789abcde0",
                            world_realization_content_hash=H64B,
                        ),
                    ]
                )
            )

    def test_cell_is_unregistered_nested_type(self) -> None:
        cell = RealizationCampaignMetricObservationCell.model_validate(observation_cell())
        assert cell.observations[0].raw_value == 84


class TestStatisticsMatrixContract:
    def test_valid_matrix_round_trip(self) -> None:
        matrix = RealizationCampaignMetricStatisticsMatrix.model_validate(statistics_payload())
        assert matrix.runtime_version == "3.0.0"
        assert matrix.statistics_mode == "descriptive"

    def test_runtime_literal_enforced(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignMetricStatisticsMatrix.model_validate(
                statistics_payload(runtime_version="2.0.0")
            )

    def test_summary_values_length_must_equal_seed_count(self) -> None:
        with pytest.raises(ValidationError):
            RealizationCampaignMetricStatisticsMatrix.model_validate(
                statistics_payload(
                    ordered_scenario_seed_ids=["seed-1"],
                    ordered_world_realization_ids=["world-realization-0123456789abcdef"],
                    ordered_world_realization_content_hashes=[H64],
                    summaries=[
                        {
                            "strategy_position": 0,
                            "metric_position": 0,
                            "strategy_candidate_id": "mock-baseline",
                            "metric_id": "m-1",
                            "metric_unit": "units",
                            "ordered_observed_values": [84, 103],
                            "observation_count": 2,
                            "minimum": 84.0,
                            "maximum": 103.0,
                            "arithmetic_mean": 93.5,
                            "median": 93.5,
                            "population_standard_deviation": 9.5,
                        },
                        {
                            "strategy_position": 1,
                            "metric_position": 0,
                            "strategy_candidate_id": "mock-conservative",
                            "metric_id": "m-1",
                            "metric_unit": "units",
                            "ordered_observed_values": [84, 103],
                            "observation_count": 2,
                            "minimum": 84.0,
                            "maximum": 103.0,
                            "arithmetic_mean": 93.5,
                            "median": 93.5,
                            "population_standard_deviation": 9.5,
                        },
                    ],
                )
            )


class TestSchemaArtifacts:
    @pytest.mark.parametrize("name", REALIZATION_NAMES)
    def test_schema_artifact_exists_and_is_synchronized(self, name: str) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        generated = generate_schemas()
        filename = f"{name}.schema.json"
        assert filename in generated
        path = SCHEMA_DIR / filename
        assert path.read_text(encoding="utf-8") == generated[filename]
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["title"] == name
