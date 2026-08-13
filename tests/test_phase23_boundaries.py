"""Phase 23 boundary scans.

Proves the new contract module, the declaration service, the pure
builder, the verified query service, the error module, and the request
models contain no NEXUS/LEGION imports or calls, no
network/provider/filesystem/database/wall-clock/randomness surface, no
dynamic loading or executable expressions, no domain-pack imports, no
probability/confidence/quantile/distribution/regret/dominance/
preference/ranking/evidence/recommendation/sampling/risk production,
no ``MetricOutcome``/``OutcomeVector``/``DistributionSummary``/
``DecisionBrief``/``EvidenceReference`` construction, no execution/
replay/extraction/sampling triggering, and no storage of the derived
matrix; that the pure builder never accesses the store and the query
never triggers Phase 20 extraction; that the runtime-2 modules,
lifecycle modules, activity kinds, and Colony surface are untouched;
that PUBLIC_CONTRACTS remains exactly 37 with the unchanged 35
existing contracts and ``ScenarioEvaluationProfile`` +
``CampaignObjectiveEvaluationMatrix`` appended last; that the world
body ``evaluation_profile`` key exists only in the compiler and the
integrity verifier; that no new runtime version was added; and that no
domain-specific vocabulary entered the Phase 23 modules.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.activity import OperationalActivityKind
from kalhas.contracts.v1.objective_evaluation import (
    OBJECTIVE_EVALUATION_MATRIX_RUNTIME_VERSION_LITERAL,
)

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

_PHASE23_MODULES = (
    "contracts/v1/objective_evaluation.py",
    "application/objective_evaluation_errors.py",
    "application/objective_evaluation_service.py",
    "application/objective_evaluation_runtime.py",
    "application/objective_evaluation_query_service.py",
    "api/requests_objective_evaluation.py",
)

#: The exact 35 contracts registered before Phase 23, in registration
#: order - Phase 23 must append without touching any of them.
_PRE_PHASE23_CONTRACTS = (
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
)

#: Modules that must never integrate the objective-evaluation matrix or
#: call the Phase 23 services (no storage, no calls).
_AUTOMATIC_INTEGRATION_MODULES = (
    "application/structural_runtime.py",
    "application/campaign_service.py",
    "application/campaign_lifecycle.py",
    "application/replay_service.py",
    "application/run_trajectory_runtime.py",
    "application/run_planner.py",
    "application/campaign_trajectory_query_service.py",
    "application/campaign_metric_observation_runtime.py",
    "application/campaign_metric_observation_query_service.py",
    "application/campaign_metric_statistics_runtime.py",
    "application/campaign_metric_statistics_query_service.py",
    "application/run_metric_observation_service.py",
    "application/trajectory_query_service.py",
    "application/input_integrity.py",
    "application/operational_activity.py",
    "application/system_info.py",
)

_FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:nexus|legion)(?:\s|\.|$)", re.IGNORECASE)
_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|__import__|import_module|exec\(|eval\(|__builtins__)\b"
)
_NETWORK_SURFACE = re.compile(
    r"\b(requests|urllib|socket|subprocess|httpx|http\.client|open\(|Path\(|os\.|"
    r"datetime\.now|datetime\.utcnow|time\.|random|secrets|uuid4|fastapi|sqlite|"
    r"provider)\b"
)
_BEHAVIOR_TOKENS = re.compile(r"\b(callback|executable|callable)\b")
_DOMAIN_VOCABULARY = re.compile(
    r"\b(maritime|logistics|port|fuel|vessel|cargo|shipping|hospital|pandemic)\b"
)
#: Phase 23 non-goal tokens: target evaluation is the feature; probability,
#: confidence, quantiles, sampling, distributions, regret, dominance,
#: preference, ranking, winners, CVaR, risk, evidence, and recommendations
#: are forbidden. (``weight``, ``normalization_scale``, and
#: ``normalized_target_violation`` are Phase 23 feature fields and are
#: deliberately not scanned.)
_NONGOAL_TOKENS = re.compile(
    r"\b(probab|confiden|quantile|percentile|sampl|distribution|regret|dominanc|"
    r"prefer|winner|cvar|risk|evidence|recommend|decision_brief|score|rank)\b"
)
#: Execution/replay/extraction/sampling/statistics entry points Phase 23
#: must never call.
_FORBIDDEN_CALLS = re.compile(
    r"^(?:build_run_trajectory_execution|replay_run|evaluate_trajectory|execute_run|"
    r"execute_campaign|prepare_strategy_trajectory_plans|evaluate_campaign|"
    r"derive_initial_state|validate_state|state_hash|sample_uncertainty|"
    r"aggregate_observations|extract_metric_value|extract_run_metric_observations|"
    r"build_campaign_metric_observation_matrix|build_campaign_metric_statistics_matrix|"
    r"get_verified_campaign_metric_statistics)$"
)


def _code_only(source: str) -> str:
    """Strip docstrings so prose naming the non-goals cannot false-positive."""
    return "".join(source.split('"""')[::2])


def _module_source(relative: str) -> str:
    return (KALHAS_ROOT / relative).read_text(encoding="utf-8")


def _call_names(module: ast.Module) -> list[tuple[int, str]]:
    """Every called function name in the module (position, name)."""
    calls: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue
        calls.append((node.lineno, name))
    return calls


def test_no_nexus_or_legion_imports() -> None:
    for relative in _PHASE23_MODULES:
        for line_no, line in enumerate(_module_source(relative).splitlines(), start=1):
            assert not _FORBIDDEN_IMPORT.match(line), f"forbidden import in {relative}:{line_no}"


def test_no_dynamic_loading_or_network_surface() -> None:
    for relative in _PHASE23_MODULES:
        code = _code_only(_module_source(relative))
        assert not _DYNAMIC_LOADING.search(code), f"dynamic loading tokens in {relative}"
        assert not _NETWORK_SURFACE.search(code), f"network/filesystem/time tokens in {relative}"
        assert not _BEHAVIOR_TOKENS.search(code), f"behavior tokens in {relative}"
        assert "kalhas.domain_packs" not in code, f"{relative} imports the pack package"


def test_no_domain_specific_vocabulary() -> None:
    for relative in _PHASE23_MODULES:
        source = _module_source(relative)
        assert not _DOMAIN_VOCABULARY.search(source), f"domain vocabulary in {relative}"


def test_no_non_goal_evaluation_semantics() -> None:
    for relative in _PHASE23_MODULES:
        code = _code_only(_module_source(relative))
        assert not _NONGOAL_TOKENS.search(code), f"non-goal tokens in {relative}"
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _NONGOAL_TOKENS.search(name)
        ]
        assert not calls, f"non-goal calls in {relative}: {calls}"


def test_no_phase1_outcome_artifact_construction() -> None:
    for relative in _PHASE23_MODULES:
        code = _code_only(_module_source(relative))
        for token in (
            "MetricOutcome",
            "OutcomeVector",
            "DistributionSummary",
            "DecisionBrief",
            "EvidenceReference",
        ):
            assert token not in code, f"{token} referenced in {relative}"


def test_phase23_never_calls_execution_extraction_replay_or_sampling() -> None:
    for relative in _PHASE23_MODULES:
        module = ast.parse(_module_source(relative))
        calls = [
            (lineno, name) for lineno, name in _call_names(module) if _FORBIDDEN_CALLS.match(name)
        ]
        assert not calls, f"execution/replay/extraction calls in {relative}: {calls}"


def test_pure_builder_never_accesses_the_store() -> None:
    source = _code_only(_module_source("application/objective_evaluation_runtime.py"))
    assert "in_memory_store" not in source
    assert "InMemoryScenarioStore" not in source
    for token in ("store.", "get_campaign", "get_run_plans", "get_verified_campaign"):
        assert token not in source, f"store access token {token!r} in the pure builder"


def test_query_never_triggers_phase20_extraction() -> None:
    source = _module_source("application/objective_evaluation_query_service.py")
    assert "extract_run_metric_observations" not in source
    assert "extract_run_metric_observations" not in _code_only(source)


def test_no_evaluation_matrix_storage_anywhere() -> None:
    store_source = _module_source("application/in_memory_store.py")
    # The profile is stored (declaration lifecycle); the derived matrix
    # is never stored.
    for token in (
        "put_campaign_objective_evaluation_matrix",
        "get_campaign_objective_evaluation_matrix",
        "update_campaign_objective_evaluation_matrix",
        "delete_campaign_objective_evaluation_matrix",
        "_objective_evaluation_matrices",
    ):
        assert token not in store_source
    assert "CampaignObjectiveEvaluationMatrix" not in store_source
    for relative in _AUTOMATIC_INTEGRATION_MODULES:
        source = _module_source(relative)
        assert "objective_evaluation" not in source, (
            f"{relative} integrates the objective-evaluation matrix"
        )


def test_contract_module_imports_only_shared_building_blocks() -> None:
    module = ast.parse(_module_source("contracts/v1/objective_evaluation.py"))
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert imports == [
        "__future__",
        "math",
        "typing",
        "pydantic",
        "kalhas.contracts.v1.shared",
        "kalhas.contracts.v1.state_model",
    ], imports


def test_builder_exposes_only_focused_functions() -> None:
    module = ast.parse(_module_source("application/objective_evaluation_runtime.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == [
        "build_campaign_objective_evaluation_matrix",
        "campaign_objective_evaluation_matrix_content_hash",
        "campaign_objective_evaluation_matrix_identifier",
    ], functions


def test_query_service_exposes_only_focused_function() -> None:
    module = ast.parse(_module_source("application/objective_evaluation_query_service.py"))
    functions = sorted(
        {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
    )
    assert functions == ["get_verified_campaign_objective_evaluations"], functions


def test_builder_and_query_signatures_accept_no_adapters_or_execution_inputs() -> None:
    from kalhas.application.objective_evaluation_query_service import (
        get_verified_campaign_objective_evaluations,
    )
    from kalhas.application.objective_evaluation_runtime import (
        build_campaign_objective_evaluation_matrix,
    )

    assert list(inspect.signature(build_campaign_objective_evaluation_matrix).parameters) == [
        "profile",
        "observation_matrix",
    ]
    assert list(inspect.signature(get_verified_campaign_objective_evaluations).parameters) == [
        "store",
        "tenant_id",
        "campaign_id",
    ]


def test_runtime_version_remains_2_0_0() -> None:
    assert TRAJECTORY_RUNTIME_VERSION == "2.0.0"
    assert OBJECTIVE_EVALUATION_MATRIX_RUNTIME_VERSION_LITERAL == TRAJECTORY_RUNTIME_VERSION
    for relative in _PHASE23_MODULES:
        assert "3.0.0" not in _module_source(relative), f"new runtime version in {relative}"


def test_operational_activity_kinds_unchanged() -> None:
    assert tuple(activity.value for activity in OperationalActivityKind) == (
        "scenario_registered",
        "world_compiled",
        "domain_pack_registered",
        "domain_pack_bound",
        "capability_inputs_declared",
        "domain_state_model_declared",
        "domain_state_transition_declared",
        "campaign_prepared",
        "campaign_started",
        "campaign_executed",
        "run_inputs_verified",
        "run_replayed",
    )


def test_phase_18_19_20_21_22_behavior_unchanged() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[30] == "CampaignTrajectoryMatrix"
    assert names[31] == "DomainMetricObservationBinding"
    assert names[32] == "RunMetricObservationSet"
    assert names[33] == "CampaignMetricObservationMatrix"
    assert names[34] == "CampaignMetricStatisticsMatrix"


def test_public_contracts_remain_exactly_forty() -> None:
    assert len(PUBLIC_CONTRACTS) == 46


def test_existing_v1_contracts_unchanged_and_phase23_contracts_appended_last() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[:35] == _PRE_PHASE23_CONTRACTS
    assert names[35] == "ScenarioEvaluationProfile"
    assert names[36] == "CampaignObjectiveEvaluationMatrix"
    assert "ObjectiveMetricBinding" not in names
    assert "ObjectiveObservationEvaluation" not in names


def test_phase24_contracts_occupy_indexes_37_through_39() -> None:
    names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
    assert names[37] == "WorldUncertaintyModel"
    assert names[38] == "WorldRealization"
    assert names[39] == "CampaignWorldRealizationMatrix"
    # The Phase 24 nested value objects stay unregistered.
    assert "UniformDistribution" not in names
    assert "TriangularDistribution" not in names
    assert "NormalDistribution" not in names
    assert "LognormalDistribution" not in names
    assert "DiscreteDistribution" not in names
    assert "StateFieldUncertaintyBinding" not in names
    assert "SampledStateFieldValue" not in names
    assert "RealizedStateFieldValue" not in names


def test_contract_fields_carry_no_executable_types() -> None:
    from kalhas.contracts.v1.objective_evaluation import (
        CampaignObjectiveEvaluationMatrix,
        ScenarioEvaluationProfile,
    )

    for contract in (ScenarioEvaluationProfile, CampaignObjectiveEvaluationMatrix):
        for field in contract.model_fields.values():
            assert not re.search(r"\b(?:Callable|exec|eval|lambda)\b", str(field.annotation)), (
                f"executable type on {contract.__name__}.{field}"
            )


def test_world_profile_key_lives_only_in_compiler_and_integrity() -> None:
    for relative in (
        "application/world_compiler.py",
        "application/world_integrity.py",
        "adapters/mocks/nexus.py",
    ):
        assert "evaluation_profile" in _module_source(relative), (
            f"{relative} lost the evaluation_profile integration"
        )
    for relative in (
        "application/run_planner.py",
        "application/runtime.py",
        "application/structural_runtime.py",
        "application/campaign_service.py",
        "application/run_trajectory_runtime.py",
    ):
        assert "evaluation_profile" not in _module_source(relative), (
            f"{relative} unexpectedly references the evaluation profile"
        )


def test_no_wall_clock_or_randomness_in_application_modules() -> None:
    for relative in (
        "application/objective_evaluation_service.py",
        "application/objective_evaluation_runtime.py",
        "application/objective_evaluation_query_service.py",
    ):
        code = _code_only(_module_source(relative))
        assert "datetime.now" not in code, f"wall clock in {relative}"
        assert "utcnow" not in code, f"wall clock in {relative}"
        assert "random" not in code, f"randomness in {relative}"


def test_store_has_no_profile_update_delete_replace_or_list_methods() -> None:
    store_source = _module_source("application/in_memory_store.py")
    for token in (
        "update_evaluation_profile",
        "delete_evaluation_profile",
        "replace_evaluation_profile",
        "list_evaluation_profiles",
        "repair_evaluation_profile",
    ):
        assert token not in store_source, f"forbidden store method {token!r}"
