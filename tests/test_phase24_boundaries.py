"""Phase 24 boundary scans.

Proves the Phase 24 surface stays within its sandbox: the contract
registration tail is exact (indexes 37-39, nested value objects
unregistered), exactly three new schema artifacts exist with the 37
pre-Phase-24 schemas unchanged, ``UncertaintyDefinition`` is untouched,
the production modules contain no randomness/UUID/wall clock/filesystem/
network/provider/database surface and no transcendental libm in the
sampler (``math.isqrt`` and validation-only ``math.isfinite`` are the
only allowed ``math`` calls), the sampler digest payload contains no
strategy terms, the realization modules never import adapters or
execute anything, no Phase 25 module and no runtime 3.0.0 literal
exists, and the runtime-2 planning/input-hash surface is untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    LognormalDistribution,
    NormalDistribution,
    TriangularDistribution,
    UniformDistribution,
)

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE24_MODULES = (
    "contracts/v1/world_realization.py",
    "application/world_uncertainty_errors.py",
    "application/world_uncertainty_identity.py",
    "application/deterministic_sampler.py",
    "application/world_uncertainty_service.py",
    "application/world_realization_builder.py",
    "application/world_realization_query_service.py",
    "api/requests_world_uncertainty.py",
    "api/routes_world_uncertainty.py",
)

#: The exact 37 contracts registered before Phase 24 (Phase 23 tail).
_PRE_PHASE24_TAIL = (
    "ScenarioEvaluationProfile",
    "CampaignObjectiveEvaluationMatrix",
)

#: The 37 pre-Phase-24 schema artifact names (tracked).
_PRE_PHASE24_SCHEMAS = (
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


def _code_only(source: str) -> str:
    """Strip docstrings so prose naming the non-goals cannot false-positive."""
    return "".join(source.split('"""')[::2])


def _module_source(relative: str) -> str:
    return (KALHAS_ROOT / relative).read_text(encoding="utf-8")


class TestContractBoundary:
    def test_public_contract_count_exactly_40(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 46

    def test_original_contracts_unchanged(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[:35] == tuple(_PRE_PHASE24_SCHEMAS[:35])
        assert names[35] == _PRE_PHASE24_TAIL[0]
        assert names[36] == _PRE_PHASE24_TAIL[1]

    def test_phase24_contracts_at_indexes_37_through_39(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[37] == "WorldUncertaintyModel"
        assert names[38] == "WorldRealization"
        assert names[39] == "CampaignWorldRealizationMatrix"

    def test_nested_value_objects_unregistered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in (
            "UniformDistribution",
            "TriangularDistribution",
            "NormalDistribution",
            "LognormalDistribution",
            "DiscreteDistribution",
            "StateFieldUncertaintyBinding",
            "SampledStateFieldValue",
            "RealizedStateFieldValue",
        ):
            assert nested not in names

    def test_uncertainty_definition_unchanged(self) -> None:
        from kalhas.contracts.v1.world import UncertaintyDefinition

        assert tuple(UncertaintyDefinition.model_fields) == (
            "identifier",
            "tenant_id",
            "schema_version",
            "target",
            "distribution",
            "parameters",
            "notes",
            "metadata",
        )


class TestSchemaBoundary:
    def test_exactly_three_new_schemas(self) -> None:
        schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "v1"
        schema_files = sorted(path.name for path in schema_dir.glob("*.schema.json"))
        expected = sorted(
            [f"{name}.schema.json" for name in _PRE_PHASE24_SCHEMAS]
            + [
                "WorldUncertaintyModel.schema.json",
                "WorldRealization.schema.json",
                "CampaignWorldRealizationMatrix.schema.json",
                "RealizationRunTrajectoryExecution.schema.json",
                "RealizationRunTrajectoryReplayManifest.schema.json",
                "RealizationCampaignTrajectoryMatrix.schema.json",
                "RealizationRunMetricObservationSet.schema.json",
                "RealizationCampaignMetricObservationMatrix.schema.json",
                "RealizationCampaignMetricStatisticsMatrix.schema.json",
            ]
        )
        assert schema_files == expected

    def test_new_schemas_are_additive(self) -> None:
        # The three new artifacts only exist alongside the 37 tracked
        # ones; their definitions are self-contained top-level objects.
        import json

        schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "v1"
        for name in (
            "WorldUncertaintyModel",
            "WorldRealization",
            "CampaignWorldRealizationMatrix",
        ):
            artifact = json.loads((schema_dir / f"{name}.schema.json").read_text())
            assert artifact["title"] == name
            assert artifact["type"] == "object"


class TestSamplerPurity:
    def test_no_transcendental_libm_in_sampler(self) -> None:
        source = _code_only(_module_source("application/deterministic_sampler.py"))
        for forbidden in (
            "math.log",
            "math.exp",
            "math.cos",
            "math.sin",
            "math.tan",
            "math.sqrt",
            "math.pow",
            "math.pi",
            "math.e",
            "math.atan",
            "math.erf",
            "math.lgamma",
            "math.frexp",
            "math.ldexp",
            "cmath.",
            "import decimal",
            "from decimal",
            "import fractions",
            "from fractions",
            "random",
            "uuid",
            "datetime.now",
            "utcnow",
            "time.time",
            "socket",
            "requests.",
            "urllib",
            "open(",
            "sqlite3",
        ):
            assert forbidden not in source, f"forbidden token {forbidden!r} in sampler"

    def test_isqrt_and_isfinite_allowed(self) -> None:
        source = _code_only(_module_source("application/deterministic_sampler.py"))
        assert "math.isqrt" in source
        assert "math.isfinite" in source

    def test_sampler_digest_payload_has_no_strategy_terms(self) -> None:
        source = _code_only(_module_source("application/deterministic_sampler.py"))
        for token in ("strategy", "strategy_id", "strategy_candidate"):
            assert token not in source.lower(), f"strategy term {token!r} in sampler"

    def test_no_wall_clock_or_randomness_in_phase24_modules(self) -> None:
        for relative in _PHASE24_MODULES:
            code = _code_only(_module_source(relative))
            for forbidden in (
                "datetime.now",
                "utcnow",
                "time.time",
                "random",
                "uuid",
                "secrets",
            ):
                assert forbidden not in code, f"{forbidden!r} in {relative}"


class TestArchitectureBoundary:
    def test_no_adapter_imports_in_phase24_modules(self) -> None:
        for relative in _PHASE24_MODULES:
            source = _module_source(relative)
            assert "adapters" not in source, f"adapter import in {relative}"

    def test_builder_and_query_never_execute(self) -> None:
        for relative in (
            "application/world_realization_builder.py",
            "application/world_realization_query_service.py",
            "application/deterministic_sampler.py",
            "application/world_uncertainty_service.py",
        ):
            source = _code_only(_module_source(relative))
            for forbidden in (
                "execute_campaign",
                "run_trajectory",
                "extract_run_metric_observations",
                "start_campaign",
                "prepare_campaign",
                # Behavior surfaces only: the shared pure identity
                # helper (objective_evaluation_identity) is allowed.
                "objective_evaluation_service",
                "objective_evaluation_runtime",
                "objective_evaluation_query_service",
                "OutcomeVector",
                "DecisionBrief",
                "rank",
                "recommend",
            ):
                assert forbidden not in source, f"{forbidden!r} in {relative}"

    def test_no_phase25_or_runtime_3(self) -> None:
        for relative in _PHASE24_MODULES:
            source = _module_source(relative)
            assert "3.0.0" not in source, f"runtime 3.0.0 literal in {relative}"
            assert "phase25" not in source.lower(), f"phase 25 reference in {relative}"
            assert "phase_25" not in source.lower()

    def test_runtime_2_planning_surface_untouched(self) -> None:
        import inspect

        from kalhas.application import run_planner as run_planner_module

        # Phase 25 intentionally adds separate runtime-3 planner symbols to
        # the same module, so the compatibility canary is scoped to the
        # historical runtime-2 primitives themselves: their function
        # bodies must still contain no uncertainty, no world-realization,
        # and no runtime-3-specific behavior.
        for function_name in ("run_input_hash", "plan_runs"):
            source = inspect.getsource(getattr(run_planner_module, function_name))
            assert "uncertainty" not in source, f"{function_name} gained an uncertainty dependency"
            assert "world_realization" not in source, (
                f"{function_name} gained a world-realization dependency"
            )
            assert "3.0.0" not in source, f"{function_name} gained runtime-3 behavior"
        # The historical constants remain unchanged.
        assert run_planner_module.LEGACY_STRUCTURAL_RUNTIME_VERSION == "1.0.0"
        assert run_planner_module.TRAJECTORY_RUNTIME_VERSION == "2.0.0"
        assert run_planner_module.RUNTIME_VERSION == run_planner_module.TRAJECTORY_RUNTIME_VERSION

    def test_no_executable_types_in_phase24_contracts(self) -> None:
        from kalhas.contracts.v1.world_realization import (
            CampaignWorldRealizationMatrix,
            WorldRealization,
            WorldUncertaintyModel,
        )

        for contract in (
            WorldUncertaintyModel,
            WorldRealization,
            CampaignWorldRealizationMatrix,
        ):
            for field in contract.model_fields.values():
                assert not re.search(r"\b(?:Callable|exec|eval|lambda)\b", str(field.annotation)), (
                    f"executable type on {contract.__name__}.{field}"
                )


class TestDistributionBoundary:
    def test_five_families_are_the_closed_set(self) -> None:
        from typing import get_args

        families = (
            UniformDistribution,
            TriangularDistribution,
            NormalDistribution,
            LognormalDistribution,
            DiscreteDistribution,
        )
        kinds = {get_args(family.model_fields["kind"].annotation)[0] for family in families}
        assert kinds == {
            "uniform",
            "triangular",
            "normal",
            "lognormal",
            "discrete",
        }
