"""Strict validation and JSON round-trip tests for every public v1 contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.activity import OperationalActivityEvent
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignStatus
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.campaign_metric_statistics import CampaignMetricStatisticsMatrix
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunStatus
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ScenarioEvaluationProfile,
)
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import (
    ClarificationQuestion,
    ContextBundle,
    ScenarioSeed,
    ScenarioSpec,
    ValidationReport,
)
from kalhas.contracts.v1.shared import Assumption, RiskStatement, VersionedContract
from kalhas.contracts.v1.simulation import DecisionBrief, EvidenceReference, OutcomeVector, RunEvent
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import UncertaintyDefinition, WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix,
    WorldRealization,
    WorldUncertaintyModel,
)
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)

SEED_PAYLOAD: dict[str, object] = {
    "identifier": "seed-1",
    "tenant_id": "tenant-1",
    "schema_version": "1.0.0",
    "algorithm": "deterministic",
    "seed_value": "a1b2c3d4e5f6",
    "metadata": {"derived": False},
}

VALID_PAYLOADS: dict[type[VersionedContract], dict[str, object]] = {
    ScenarioSpec: {
        "identifier": "scenario-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "name": "Reference scenario",
        "description": "Domain-neutral scenario",
        "created_at": NOW,
        "objectives": [
            {
                "identifier": "obj-1",
                "description": "Maximize the primary metric",
                "direction": "maximize",
                "target": 100.0,
                "weight": 1.0,
            }
        ],
        "constraints": [
            {"identifier": "c-1", "description": "Stay within declared bounds", "hard": True}
        ],
        "time_horizon": {"start": NOW, "end": LATER, "resolution": "step"},
        "metrics": [
            {"identifier": "m-1", "name": "Primary metric", "unit": "units", "aggregation": "mean"}
        ],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {"owner": "foundation"},
    },
    ContextBundle: {
        "identifier": "ctx-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "title": "Decision context",
        "summary": "Neutral context",
        "statements": ["Statement one"],
        "tags": ["generic"],
        "metadata": {"k": "v"},
    },
    ScenarioSeed: dict(SEED_PAYLOAD),
    ClarificationQuestion: {
        "identifier": "q-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "prompt": "Which time horizon applies?",
        "options": ["Short", "Long"],
        "required": True,
        "targets": ["time_horizon"],
    },
    ValidationReport: {
        "identifier": "vr-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "subject_id": "scenario-1",
        "valid": True,
        "issues": [],
        "validated_at": NOW,
    },
    WorldVersion: {
        "identifier": "world-v2",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "parent_version_id": "world-v1",
        "source_scenario_id": "scenario-1",
        "compiler_version": "1.0.0",
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "created_at": NOW,
        "world": {"entities": 3, "properties": {"a": 1}},
        "metadata": {"label": "baseline"},
    },
    WorldManifest: {
        "identifier": "wm-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "world_version_id": "world-v2",
        "entity_count": 3,
        "state": {"snapshot": "json-like"},
        "metadata": {},
    },
    DomainPackManifest: {
        "identifier": "manifest-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1"],
                "output_ids": ["out-1"],
                "metadata": {},
            }
        ],
        "schema_metadata": {"declarative": True},
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "created_at": NOW,
        "metadata": {"owner": "foundation"},
    },
    DomainPackBinding: {
        "identifier": "binding-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "capability_ids": ["cap-1"],
        "bound_at": NOW,
    },
    DomainCapabilityDeclaration: {
        "identifier": "declaration-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "capability_id": "cap-1",
        "input_values": {"in-a": "value-a", "in-b": 42},
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
    },
    DomainStateModel: {
        "identifier": "state-model-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "state_model_id": "sm-1",
        "state_fields": [
            {
                "identifier": "status",
                "description": "A declared state field",
                "value_kind": "string",
                "initial_value": "idle",
                "allowed_values": ["idle", "active"],
                "metadata": {},
            },
            {
                "identifier": "level",
                "description": "A declared state field",
                "value_kind": "integer",
                "initial_value": 0,
                "metadata": {},
            },
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
        "metadata": {},
    },
    DomainStateTransition: {
        "identifier": "transition-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "state_model_id": "sm-1",
        "state_model_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "transition_id": "t-1",
        "description": "A possible state change",
        "guard_values": {"level": 0},
        "target_values": {"status": "active"},
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
        "metadata": {},
    },
    DomainMetricObservationBinding: {
        "identifier": "observation-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "metric_id": "m-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
        "metadata": {},
    },
    RunMetricObservationSet: {
        "identifier": "metric-observation-set-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-1",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "scenario_seed_id": "seed-1",
        "runtime_version": "2.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "trajectory_execution_id": "trajectory-execution-1",
        "trajectory_execution_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "observations": [
            {
                "metric_id": "m-1",
                "metric_unit": "units",
                "binding_id": "observation-1",
                "binding_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_field_id": "level",
                "state_field_value_kind": "integer",
                "observation_point": "final_state",
                "trajectory_plan_id": "trajectory-plan-1",
                "trajectory_plan_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "trajectory_result_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "raw_value": 7,
            },
            {
                "metric_id": "m-2",
                "metric_unit": "percent",
                "binding_id": "observation-2",
                "binding_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_field_id": "ratio",
                "state_field_value_kind": "number",
                "observation_point": "final_state",
                "trajectory_plan_id": "trajectory-plan-1",
                "trajectory_plan_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "trajectory_result_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "raw_value": 2.5,
            },
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "observed_at": NOW,
    },
    CampaignMetricObservationMatrix: {
        "identifier": "metric-observation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["sc-1"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_metric_ids": ["m-1", "m-2"],
        "cells": [
            {
                "sequence_position": 0,
                "strategy_position": 0,
                "seed_position": 0,
                "run_id": "run-plan-0123456789abcdef",
                "run_plan_id": "plan-0123456789abcdef",
                "strategy_candidate_id": "sc-1",
                "scenario_seed_id": "seed-1",
                "input_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "trajectory_execution_id": "trajectory-execution-0123456789abcdef",
                "trajectory_execution_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "metric_observation_set_id": "metric-observation-set-1",
                "metric_observation_set_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "observations": [
                    {
                        "metric_id": "m-1",
                        "metric_unit": "units",
                        "binding_id": "observation-1",
                        "binding_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "manifest_id": "manifest-1",
                        "state_model_identifier": "state-model-1",
                        "state_model_id": "sm-1",
                        "state_model_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "state_field_id": "level",
                        "state_field_value_kind": "integer",
                        "observation_point": "final_state",
                        "trajectory_plan_id": "trajectory-plan-1",
                        "trajectory_plan_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "trajectory_result_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "raw_value": 7,
                    },
                    {
                        "metric_id": "m-2",
                        "metric_unit": "percent",
                        "binding_id": "observation-2",
                        "binding_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "manifest_id": "manifest-1",
                        "state_model_identifier": "state-model-1",
                        "state_model_id": "sm-1",
                        "state_model_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "state_field_id": "ratio",
                        "state_field_value_kind": "number",
                        "observation_point": "final_state",
                        "trajectory_plan_id": "trajectory-plan-1",
                        "trajectory_plan_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "trajectory_result_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "raw_value": 2.5,
                    },
                ],
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assembled_at": NOW,
    },
    CampaignMetricStatisticsMatrix: {
        "identifier": "metric-statistics-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "statistics_mode": "descriptive",
        "source_metric_observation_matrix_id": "metric-observation-matrix-0123456789abcdef",
        "source_metric_observation_matrix_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "ordered_strategy_candidate_ids": ["sc-1"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_metric_ids": ["m-1", "m-2"],
        "summaries": [
            {
                "strategy_position": 0,
                "metric_position": 0,
                "strategy_candidate_id": "sc-1",
                "metric_id": "m-1",
                "metric_unit": "units",
                "ordered_observed_values": [1],
                "observation_count": 1,
                "minimum": 1.0,
                "maximum": 1.0,
                "arithmetic_mean": 1.0,
                "median": 1.0,
                "population_standard_deviation": 0.0,
            },
            {
                "strategy_position": 0,
                "metric_position": 1,
                "strategy_candidate_id": "sc-1",
                "metric_id": "m-2",
                "metric_unit": "percent",
                "ordered_observed_values": [2.5],
                "observation_count": 1,
                "minimum": 2.5,
                "maximum": 2.5,
                "arithmetic_mean": 2.5,
                "median": 2.5,
                "population_standard_deviation": 0.0,
            },
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "summarized_at": NOW,
    },
    ScenarioEvaluationProfile: {
        "identifier": "evaluation-profile-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "scenario_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "bindings": [
            {
                "objective_id": "obj-1",
                "metric_id": "m-1",
                "direction": "minimize",
                "target": 100.0,
                "weight": 1.0,
                "metric_unit": "units",
                "reach_tolerance": None,
                "normalization_scale": 100.0,
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
        "metadata": {},
    },
    CampaignObjectiveEvaluationMatrix: {
        "identifier": "objective-evaluation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "source_metric_observation_matrix_id": "metric-observation-matrix-0123456789abcdef",
        "source_metric_observation_matrix_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "evaluation_profile_id": "evaluation-profile-0123456789abcdef",
        "evaluation_profile_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "scenario_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "ordered_strategy_candidate_ids": ["sc-1"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_objective_ids": ["obj-1"],
        "cells": [
            {
                "sequence_position": 0,
                "strategy_position": 0,
                "seed_position": 0,
                "objective_position": 0,
                "strategy_candidate_id": "sc-1",
                "scenario_seed_id": "seed-1",
                "objective_id": "obj-1",
                "metric_id": "m-1",
                "metric_unit": "units",
                "run_id": "run-1",
                "input_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "raw_value": 91,
                "direction": "minimize",
                "target": 100.0,
                "weight": 1.0,
                "reach_tolerance": None,
                "normalization_scale": 100.0,
                "target_achieved": True,
                "signed_target_delta": -9.0,
                "normalized_target_violation": 0.0,
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "evaluated_at": NOW,
    },
    OperationalActivityEvent: {
        "identifier": "activity-0",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "sequence": 0,
        "kind": "scenario_registered",
        "occurred_at": NOW,
        "scenario_id": "scenario-1",
        "world_version_id": None,
        "campaign_id": None,
        "run_id": None,
        "manifest_id": None,
        "binding_id": None,
        "declaration_id": None,
        "payload": {"schema_version": "1.0.0"},
    },
    UncertaintyDefinition: {
        "identifier": "u-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "target": "metric:m-1",
        "distribution": "normal",
        "parameters": {"mean": 0.0, "stddev": 1.0},
        "notes": "declared only",
        "metadata": {},
    },
    StrategyRequest: {
        "identifier": "sr-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "context_bundle_id": "ctx-1",
        "constraint_ids": ["c-1"],
        "required_observations": [
            {"metric_id": "m-1", "description": "observe m-1", "required": True}
        ],
        "requested_at": NOW,
        "metadata": {},
    },
    StrategyCandidate: {
        "identifier": "sc-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "strategy_version": "1.0.0",
        "policy": {
            "summary": "Declared policy",
            "rules": [
                {
                    "identifier": "r-1",
                    "statement": "Prefer low risk",
                    "parameters": {"threshold": 0.2},
                }
            ],
        },
        "required_observations": [
            {"metric_id": "m-1", "description": "observe m-1", "required": True}
        ],
        "assumptions": [{"identifier": "a-1", "statement": "Stable", "confidence": 0.8}],
        "metadata": {},
    },
    CampaignSpec: {
        "identifier": "campaign-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_ids": ["sc-1", "sc-2"],
        "comparison_mode": "identical_conditions",
        "seed_ensemble": [dict(SEED_PAYLOAD)],
        "created_at": NOW,
        "metadata": {},
    },
    CampaignStatus: {
        "identifier": "cs-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "state": "draft",
        "changed_at": NOW,
        "message": "created",
    },
    RunEvent: {
        "identifier": "ev-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "sequence": 0,
        "kind": "observation",
        "simulation_time": NOW,
        "created_at": NOW,
        "payload": {"metric_id": "m-1"},
        "metadata": {"source": "test", "tags": ["demo"], "details": {"k": 1}},
    },
    RunPlan: {
        "identifier": "plan-campaign-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "runtime_version": "1.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "planned_state": "planned",
        "created_at": NOW,
    },
    RunStatus: {
        "identifier": "status-run-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-campaign-1",
        "state": "complete",
        "runtime_version": "1.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "event_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "created_at": NOW,
        "changed_at": NOW,
    },
    ReplayManifest: {
        "identifier": "replay-run-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "runtime_version": "1.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "expected_event_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "replay_classification": "exact",
        "created_at": NOW,
    },
    RunInputIntegrityManifest: {
        "identifier": "integrity-run-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-campaign-1",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "mock-baseline",
        "scenario_seed_id": "seed-1",
        "runtime_version": "1.0.0",
        "expected_input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "recomputed_input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "verification_classification": "exact",
        "recorded_at": NOW,
    },
    OutcomeVector: {
        "identifier": "ov-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "scenario_id": "scenario-1",
        "strategy_candidate_id": "sc-1",
        "metrics": [
            {
                "metric_id": "m-1",
                "unit": "units",
                "point_estimate": 42.0,
                "distribution": {
                    "kind": "normal",
                    "parameters": {"mean": 42.0, "stddev": 3.0},
                    "mean": 42.0,
                    "median": 41.9,
                    "lower_quantile": 39.0,
                    "upper_quantile": 45.0,
                    "samples": [],
                },
                "observed_values": [41.0, 42.5, 43.0],
            }
        ],
        "risks": [
            {"identifier": "r-1", "description": "Outlier risk", "likelihood": 0.2, "impact": 0.5}
        ],
        "assumptions": [{"identifier": "a-1", "statement": "Stable", "confidence": 0.8}],
        "uncertainty": [
            {
                "target": "m-1",
                "description": "Measurement noise",
                "distribution": "normal",
                "parameters": {"stddev": 0.1},
            }
        ],
        "evidence_references": [
            {
                "identifier": "ev-ref-1",
                "tenant_id": "tenant-1",
                "schema_version": "1.0.0",
                "source_kind": "run_event",
                "source_id": "ev-1",
                "recorded_at": NOW,
                "metadata": {},
            }
        ],
        "produced_at": NOW,
    },
    EvidenceReference: {
        "identifier": "ev-ref-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "source_kind": "run_event",
        "source_id": "ev-1",
        "recorded_at": NOW,
        "description": "recorded observation",
        "metadata": {},
    },
    DecisionBrief: {
        "identifier": "db-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "decision_id": "decision-1",
        "scenario_id": "scenario-1",
        "strategy_candidate_id": "sc-1",
        "summary": "Preferred candidate with full distribution context",
        "outcome": {
            "identifier": "ov-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "run_id": "run-1",
            "scenario_id": "scenario-1",
            "strategy_candidate_id": "sc-1",
            "metrics": [
                {
                    "metric_id": "m-1",
                    "unit": "units",
                    "point_estimate": 42.0,
                    "distribution": {
                        "kind": "normal",
                        "parameters": {"mean": 42.0, "stddev": 3.0},
                        "mean": 42.0,
                        "median": 41.9,
                        "lower_quantile": 39.0,
                        "upper_quantile": 45.0,
                        "samples": [],
                    },
                    "observed_values": [41.0, 42.5, 43.0],
                }
            ],
            "risks": [],
            "assumptions": [],
            "uncertainty": [],
            "evidence_references": [],
            "produced_at": NOW,
        },
        "risks": [
            {"identifier": "r-1", "description": "Outlier risk", "likelihood": 0.2, "impact": 0.5}
        ],
        "assumptions": [{"identifier": "a-1", "statement": "Stable", "confidence": 0.8}],
        "uncertainty": [
            {"target": "m-1", "description": "Measurement noise", "distribution": "normal"}
        ],
        "evidence_references": [
            {
                "identifier": "ev-ref-1",
                "tenant_id": "tenant-1",
                "schema_version": "1.0.0",
                "source_kind": "run_event",
                "source_id": "ev-1",
                "recorded_at": NOW,
                "metadata": {},
            }
        ],
        "produced_at": NOW,
    },
    StrategyTrajectoryPlanRequest: {
        "identifier": "trajectory-request-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "strategy_candidate": {
            "identifier": "sc-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "strategy_version": "1.0.0",
            "policy": {
                "summary": "Declared policy",
                "rules": [
                    {
                        "identifier": "r-1",
                        "statement": "Prefer low risk",
                        "parameters": {"threshold": 0.2},
                    }
                ],
            },
            "required_observations": [
                {"metric_id": "m-1", "description": "observe m-1", "required": True}
            ],
            "assumptions": [{"identifier": "a-1", "statement": "Stable", "confidence": 0.8}],
            "metadata": {},
        },
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "state_model": {
            "identifier": "state-model-1",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "binding_id": "binding-1",
            "manifest_id": "manifest-1",
            "pack_id": "pack-1",
            "pack_version": "1.2.3",
            "manifest_content_hash": (
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            ),
            "state_model_id": "sm-1",
            "state_fields": [
                {
                    "identifier": "status",
                    "description": "A declared state field",
                    "value_kind": "string",
                    "initial_value": "idle",
                    "allowed_values": ["idle", "active"],
                    "metadata": {},
                }
            ],
            "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "declared_at": NOW,
            "metadata": {},
        },
        "available_transitions": [
            {
                "identifier": "transition-1",
                "tenant_id": "tenant-1",
                "schema_version": "1.0.0",
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "pack_id": "pack-1",
                "pack_version": "1.2.3",
                "manifest_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "transition_id": "t-1",
                "description": "A possible state change",
                "guard_values": {"status": "idle"},
                "target_values": {"status": "active"},
                "content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "declared_at": NOW,
                "metadata": {},
            }
        ],
        "requested_at": NOW,
    },
    StrategyTrajectoryPlan: {
        "identifier": "trajectory-plan-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "strategy_candidate_id": "sc-1",
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "transition_references": [
            {
                "sequence_position": 0,
                "transition_identifier": "transition-1",
                "transition_id": "t-1",
                "transition_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "planned_at": NOW,
    },
    RunTrajectoryExecution: {
        "identifier": "trajectory-execution-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-plan-0123456789abcdef",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-0123456789abcdef",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "strategy_candidate_id": "sc-1",
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "scenario_seed_id": "seed-1",
        "runtime_version": "2.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "trajectory_plan_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "results": [
            {
                "trajectory_plan_id": "trajectory-plan-0123456789abcdef",
                "trajectory_plan_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "initial_state": {"status": "idle"},
                "initial_state_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "attempts": [
                    {
                        "sequence_position": 0,
                        "transition_identifier": "transition-1",
                        "transition_id": "t-1",
                        "transition_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "outcome": "applied",
                        "before_state_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "after_state_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                    }
                ],
                "final_state": {"status": "active"},
                "final_state_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "trace_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "executed_at": NOW,
    },
    RunTrajectoryReplayManifest: {
        "identifier": "trajectory-replay-run-plan-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-plan-0123456789abcdef",
        "campaign_id": "campaign-1",
        "run_trajectory_execution_id": "trajectory-execution-0123456789abcdef",
        "world_version_id": "world-0123456789abcdef",
        "strategy_candidate_id": "sc-1",
        "scenario_seed_id": "seed-1",
        "runtime_version": "2.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "trajectory_plan_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "expected_execution_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "recomputed_execution_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "replay_classification": "exact",
        "replayed_at": NOW,
    },
    CampaignTrajectoryMatrix: {
        "identifier": "trajectory-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "2.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["sc-1"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "cells": [
            {
                "sequence_position": 0,
                "strategy_position": 0,
                "seed_position": 0,
                "run_id": "run-plan-0123456789abcdef",
                "run_plan_id": "plan-0123456789abcdef",
                "strategy_candidate_id": "sc-1",
                "scenario_seed_id": "seed-1",
                "input_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "trajectory_execution_id": "trajectory-execution-0123456789abcdef",
                "trajectory_execution_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "trajectory_plan_set_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "result_content_hashes": [
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ],
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assembled_at": NOW,
    },
    WorldUncertaintyModel: {
        "identifier": "uncertainty-model-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "scenario_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "bindings": [
            {
                "identifier": "uncertainty-binding-0123456789abcdef",
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "pack_id": "pack-1",
                "pack_version": "1.2.3",
                "manifest_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_field_id": "level",
                "state_field_value_kind": "integer",
                "distribution": {"kind": "uniform", "low": 0.0, "high": 1.0},
                "rounding_policy": "floor",
                "lower_bound": None,
                "upper_bound": None,
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
            },
            {
                "identifier": "uncertainty-binding-0123456789abcde0",
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "pack_id": "pack-1",
                "pack_version": "1.2.3",
                "manifest_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "state_field_id": "ratio",
                "state_field_value_kind": "number",
                "distribution": {
                    "kind": "discrete",
                    "values": [1, 1.0],
                    "probabilities": [0.5, 0.5],
                },
                "rounding_policy": None,
                "lower_bound": None,
                "upper_bound": None,
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
            },
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "declared_at": NOW,
        "metadata": {},
    },
    WorldRealization: {
        "identifier": "world-realization-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "scenario_seed_id": "seed-1",
        "seed_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "uncertainty_model_id": "uncertainty-model-0123456789abcdef",
        "uncertainty_model_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "sampled_values": [
            {
                "uncertainty_binding_identifier": "uncertainty-binding-0123456789abcdef",
                "uncertainty_binding_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": "level",
                "state_field_value_kind": "integer",
                "distribution_kind": "uniform",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": 0,
                "draw_count": 1,
                "sampled_raw_value": 0.25,
                "realized_value": 0,
            },
            {
                "uncertainty_binding_identifier": "uncertainty-binding-0123456789abcde0",
                "uncertainty_binding_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": "ratio",
                "state_field_value_kind": "number",
                "distribution_kind": "discrete",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": 1,
                "draw_count": 1,
                "sampled_raw_value": 1.0,
                "realized_value": 1.0,
            },
        ],
        "realized_initial_state_overrides": [
            {
                "state_model_identifier": "state-model-1",
                "state_field_id": "level",
                "value": 0,
            },
            {
                "state_model_identifier": "state-model-1",
                "state_field_id": "ratio",
                "value": 1.0,
            },
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "realized_at": NOW,
    },
    CampaignWorldRealizationMatrix: {
        "identifier": "campaign-realization-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "uncertainty_model_id": "uncertainty-model-0123456789abcdef",
        "uncertainty_model_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "ordered_scenario_seed_ids": ["seed-1"],
        "realizations": [
            {
                "identifier": "world-realization-0123456789abcdef",
                "tenant_id": "tenant-1",
                "schema_version": "1.0.0",
                "scenario_id": "scenario-1",
                "world_version_id": "world-0123456789abcdef",
                "world_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "scenario_seed_id": "seed-1",
                "seed_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "uncertainty_model_id": "uncertainty-model-0123456789abcdef",
                "uncertainty_model_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "sampled_values": [
                    {
                        "uncertainty_binding_identifier": "uncertainty-binding-0123456789abcdef",
                        "uncertainty_binding_content_hash": (
                            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                        ),
                        "scenario_id": "scenario-1",
                        "binding_id": "binding-1",
                        "manifest_id": "manifest-1",
                        "state_model_identifier": "state-model-1",
                        "state_model_id": "sm-1",
                        "state_field_id": "level",
                        "state_field_value_kind": "integer",
                        "distribution_kind": "uniform",
                        "sampler_version": "sha256-counter-v1",
                        "quantization_policy": "rational-round-half-even",
                        "quantization_fraction_bits": 64,
                        "draw_index": 0,
                        "draw_count": 1,
                        "sampled_raw_value": 0.25,
                        "realized_value": 0,
                    }
                ],
                "realized_initial_state_overrides": [
                    {
                        "state_model_identifier": "state-model-1",
                        "state_field_id": "level",
                        "value": 0,
                    }
                ],
                "content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "realized_at": NOW,
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assembled_at": NOW,
    },
    RealizationRunTrajectoryExecution: {
        "identifier": "realization-trajectory-execution-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "scenario_seed_id": "seed-1",
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "runtime_version": "3.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "trajectory_plan_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "results": [],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "executed_at": NOW,
    },
    RealizationRunTrajectoryReplayManifest: {
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
        "world_realization_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "runtime_version": "3.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "trajectory_plan_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "expected_execution_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "recomputed_execution_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "expected_observation_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "recomputed_observation_set_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "replay_classification": "exact",
        "replayed_at": NOW,
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    },
    RealizationCampaignTrajectoryMatrix: {
        "identifier": "realization-trajectory-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["mock-baseline"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_world_realization_ids": ["world-realization-0123456789abcdef"],
        "ordered_world_realization_content_hashes": [
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ],
        "cells": [
            {
                "sequence_position": 0,
                "strategy_position": 0,
                "seed_position": 0,
                "run_id": "run-1",
                "run_plan_id": "plan-1",
                "strategy_candidate_id": "mock-baseline",
                "scenario_seed_id": "seed-1",
                "input_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "realization_run_trajectory_execution_id": (
                    "realization-trajectory-execution-0123456789abcdef"
                ),
                "realization_run_trajectory_execution_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "trajectory_plan_set_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "result_content_hashes": [],
                "world_realization_id": "world-realization-0123456789abcdef",
                "world_realization_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assembled_at": NOW,
    },
    RealizationRunMetricObservationSet: {
        "identifier": "realization-metric-observation-set-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "campaign_id": "campaign-1",
        "run_plan_id": "plan-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "strategy_candidate_id": "mock-baseline",
        "strategy_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "scenario_seed_id": "seed-1",
        "world_realization_id": "world-realization-0123456789abcdef",
        "world_realization_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "runtime_version": "3.0.0",
        "input_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "realization_run_trajectory_execution_id": (
            "realization-trajectory-execution-0123456789abcdef"
        ),
        "realization_run_trajectory_execution_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "observations": [],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "observed_at": NOW,
    },
    RealizationCampaignMetricObservationMatrix: {
        "identifier": "realization-metric-observation-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "ordered_strategy_candidate_ids": ["mock-baseline"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_metric_ids": [],
        "ordered_world_realization_ids": ["world-realization-0123456789abcdef"],
        "ordered_world_realization_content_hashes": [
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ],
        "cells": [
            {
                "sequence_position": 0,
                "strategy_position": 0,
                "seed_position": 0,
                "run_id": "run-1",
                "run_plan_id": "plan-1",
                "strategy_candidate_id": "mock-baseline",
                "scenario_seed_id": "seed-1",
                "input_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
                "realization_run_trajectory_execution_id": (
                    "realization-trajectory-execution-0123456789abcdef"
                ),
                "realization_run_trajectory_execution_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "realization_run_metric_observation_set_id": (
                    "realization-metric-observation-set-0123456789abcdef"
                ),
                "realization_run_metric_observation_set_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "world_realization_id": "world-realization-0123456789abcdef",
                "world_realization_content_hash": (
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                ),
                "observations": [],
            }
        ],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "assembled_at": NOW,
    },
    RealizationCampaignMetricStatisticsMatrix: {
        "identifier": "realization-metric-statistics-matrix-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "statistics_mode": "descriptive",
        "source_metric_observation_matrix_id": (
            "realization-metric-observation-matrix-0123456789abcdef"
        ),
        "source_metric_observation_matrix_content_hash": (
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "ordered_strategy_candidate_ids": ["mock-baseline"],
        "ordered_scenario_seed_ids": ["seed-1"],
        "ordered_metric_ids": [],
        "ordered_world_realization_ids": ["world-realization-0123456789abcdef"],
        "ordered_world_realization_content_hashes": [
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ],
        "summaries": [],
        "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "summarized_at": NOW,
    },
}


@pytest.mark.parametrize("contract", PUBLIC_CONTRACTS, ids=lambda c: c.__name__)
def test_contract_accepts_valid_payload(contract: type[VersionedContract]) -> None:
    instance = contract.model_validate(VALID_PAYLOADS[contract])
    assert instance.identifier
    assert instance.tenant_id
    assert instance.schema_version == "1.0.0"


@pytest.mark.parametrize("contract", PUBLIC_CONTRACTS, ids=lambda c: c.__name__)
def test_contract_rejects_unknown_fields(contract: type[VersionedContract]) -> None:
    payload = dict(VALID_PAYLOADS[contract])
    payload["unexpected_field"] = 1
    with pytest.raises(ValidationError):
        contract.model_validate(payload)


@pytest.mark.parametrize("contract", PUBLIC_CONTRACTS, ids=lambda c: c.__name__)
def test_contract_rejects_non_semantic_schema_version(
    contract: type[VersionedContract],
) -> None:
    payload = dict(VALID_PAYLOADS[contract])
    payload["schema_version"] = "1.0"
    with pytest.raises(ValidationError):
        contract.model_validate(payload)


@pytest.mark.parametrize("contract", PUBLIC_CONTRACTS, ids=lambda c: c.__name__)
def test_contract_json_round_trip(contract: type[VersionedContract]) -> None:
    instance = contract.model_validate(VALID_PAYLOADS[contract])
    dumped = instance.model_dump_json()
    reloaded = contract.model_validate_json(dumped)
    assert reloaded == instance
    assert instance.model_dump(mode="json") == json.loads(dumped)


def test_world_version_rejects_self_parent() -> None:
    payload = dict(VALID_PAYLOADS[WorldVersion])
    payload["parent_version_id"] = payload["identifier"]
    with pytest.raises(ValidationError):
        WorldVersion.model_validate(payload)


def test_world_version_is_immutable_by_contract() -> None:
    version = WorldVersion.model_validate(VALID_PAYLOADS[WorldVersion])
    with pytest.raises(ValidationError):
        version.world = {"tampered": True}


def test_time_horizon_rejects_end_before_start() -> None:
    payload = dict(VALID_PAYLOADS[ScenarioSpec])
    horizon = dict(cast(dict[str, object], payload["time_horizon"]))
    horizon["end"] = horizon["start"]
    payload["time_horizon"] = horizon
    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate(payload)


def test_campaign_spec_rejects_empty_strategy_list() -> None:
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    payload["strategy_candidate_ids"] = []
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_campaign_spec_rejects_empty_seed_ensemble() -> None:
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    payload["seed_ensemble"] = []
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_campaign_spec_rejects_duplicate_seed_identifiers() -> None:
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    payload["seed_ensemble"] = [dict(SEED_PAYLOAD), dict(SEED_PAYLOAD)]
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_campaign_spec_rejects_duplicate_strategy_candidate_ids() -> None:
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    payload["strategy_candidate_ids"] = ["sc-1", "sc-1"]
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_campaign_spec_always_represents_identical_conditions() -> None:
    """Fair comparison is structural: no other mode can be expressed."""
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    payload["comparison_mode"] = "independent"
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)

    spec = CampaignSpec.model_validate(VALID_PAYLOADS[CampaignSpec])
    assert spec.comparison_mode == "identical_conditions"
    assert spec.model_dump(mode="json")["comparison_mode"] == "identical_conditions"


def test_campaign_spec_has_no_run_multiplicity_field() -> None:
    """The seed ensemble is the sole source of run multiplicity."""
    assert "runs_per_strategy" not in CampaignSpec.model_fields


def test_campaign_spec_rejects_foreign_tenant_seeds() -> None:
    payload = dict(VALID_PAYLOADS[CampaignSpec])
    seed = dict(SEED_PAYLOAD)
    seed["tenant_id"] = "tenant-other"
    payload["seed_ensemble"] = [seed]
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_world_version_rejects_malformed_content_hash() -> None:
    for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64, "abc" * 21 + "A"):
        payload = dict(VALID_PAYLOADS[WorldVersion])
        payload["content_hash"] = bad_hash[:64]
        with pytest.raises(ValidationError):
            WorldVersion.model_validate(payload)


def test_run_input_integrity_manifest_rejects_malformed_hashes() -> None:
    for field in ("expected_input_hash", "recomputed_input_hash"):
        for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64):
            payload = dict(VALID_PAYLOADS[RunInputIntegrityManifest])
            payload[field] = bad_hash[:64]
            with pytest.raises(ValidationError):
                RunInputIntegrityManifest.model_validate(payload)


def test_run_input_integrity_manifest_classification_is_exact_only() -> None:
    payload = dict(VALID_PAYLOADS[RunInputIntegrityManifest])
    payload["verification_classification"] = "approximate"
    with pytest.raises(ValidationError):
        RunInputIntegrityManifest.model_validate(payload)


def test_run_plan_rejects_malformed_input_hash() -> None:
    for bad_hash in ("ABC" * 22, "abc" * 21, "z" * 64):
        payload = dict(VALID_PAYLOADS[RunPlan])
        payload["input_hash"] = bad_hash[:64]
        with pytest.raises(ValidationError):
            RunPlan.model_validate(payload)


def test_scenario_spec_does_not_own_campaign_seed_assignment() -> None:
    assert "seed" not in ScenarioSpec.model_fields
    assert "seed_ensemble" in CampaignSpec.model_fields


def test_scenario_seed_rejects_empty_seed_value() -> None:
    payload = dict(VALID_PAYLOADS[ScenarioSeed])
    payload["seed_value"] = ""
    with pytest.raises(ValidationError):
        ScenarioSeed.model_validate(payload)


def test_assumption_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        Assumption.model_validate({"identifier": "a-1", "statement": "x", "confidence": 1.5})


def test_risk_statement_rejects_out_of_range_likelihood() -> None:
    with pytest.raises(ValidationError):
        RiskStatement.model_validate(
            {"identifier": "r-1", "description": "x", "likelihood": -0.1, "impact": 0.5}
        )


def test_run_event_rejects_negative_sequence() -> None:
    payload = dict(VALID_PAYLOADS[RunEvent])
    payload["sequence"] = -1
    with pytest.raises(ValidationError):
        RunEvent.model_validate(payload)


def test_timestamps_must_be_timezone_aware() -> None:
    payload = dict(VALID_PAYLOADS[ValidationReport])
    payload["validated_at"] = datetime(2026, 1, 1, 12, 0)  # naive
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(payload)


def test_metadata_rejects_non_json_values() -> None:
    payload = dict(VALID_PAYLOADS[ContextBundle])
    payload["metadata"] = {1: "value"}  # JSON object keys must be strings
    with pytest.raises(ValidationError):
        ContextBundle.model_validate(payload)
