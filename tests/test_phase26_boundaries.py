"""Phase 26 architectural boundary scans.

Architectural protection for the campaign outcome-distribution surface
(``kalhas/application/campaign_outcome_*.py``,
``kalhas/api/routes_campaign_outcome.py``,
``kalhas/contracts/v1/campaign_outcome.py``) using precise AST,
import-graph, contract, schema, and symbol inspection - never raw
substring scans that could false-positive on docstrings, comments, or
negative assertions. Proves:

- domain-neutral kernel: no NEXUS/LEGION internal import, no adapter
  coupling, no domain-pack implementation dependency, and no new
  architecture component or integration surface;
- determinism and purity: no network/provider/database/filesystem
  surface, no wall-clock authority, no global/process randomness,
  ``random.seed``, UUID randomness, or process-hash dependence, and the
  statistics module retains its accepted minimal import boundary;
- derived evidence: campaign outcome matrices are derived and never
  stored, the pure builders are store-free, the verified query and the
  route are strictly read-only with no store write, operational-activity,
  replay, execution, extraction, repair, or artifact-creation call;
- public/API surface: exactly one Phase 26 GET endpoint and no
  POST/PUT/PATCH/DELETE Phase 26 endpoint, runtime is selected from
  recorded run plans (never caller input), the required X-Tenant-ID
  header, ``CampaignOutcomeDistributionMatrix`` at public-contract
  index 46 with the exact unchanged 46-contract prefix and the
  decision contracts at indexes 47-49 within the accepted Phase 27
  50-contract prefix, schema artifact count following ``PUBLIC_CONTRACTS``
  with later additive contracts allowed, nested Phase 26 value objects
  unregistered,
  and the Phase 25 paths/operations unchanged;
- statistical/decision boundary: no ranking, winner, preferred
  strategy, recommendation, decision brief, LLM narrative, confidence
  interval, forecast-certainty, or real-world-probability field or
  executable surface; no arbitrary scripts, expressions, callbacks,
  provider references, executable templates, or adaptive policy
  switching; the established Phase 26 production modules remain free
  of decision-contract imports and decision artifacts (the former
  global Phase 27 absence assertion is superseded by the scoped
  Phase 26 module scan; complete decision-surface restrictions belong
  to the future dedicated Phase 27 boundary suite);
- versioning and compatibility: API/SCHEMA version constants
  unchanged, runtime exactly 3.0.0 with no older-runtime
  reinterpretation, and no Phase 26 dependency in any runtime-2 or
  Phase-24 production module.

Ephemeral repository state (HEAD hashes, git status, staged state,
worktree file lists, remote state, test-file hashes) is intentionally
not encoded here - those are closure-gate/report checks, not permanent
architecture.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

from kalhas.api.app import create_app
from kalhas.contracts.v1 import API_VERSION, PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    EmpiricalDistributionSummary,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

#: Every Phase 26 production module (application, API, and contract).
_PHASE26_MODULES = (
    "application/campaign_outcome_statistics.py",
    "application/campaign_outcome_runtime.py",
    "application/campaign_outcome_identity.py",
    "application/campaign_outcome_errors.py",
    "application/campaign_outcome_matrix_runtime.py",
    "application/campaign_outcome_query_service.py",
    "api/routes_campaign_outcome.py",
    "contracts/v1/campaign_outcome.py",
)

#: The pure derived-statistics/outcome/matrix modules: store-free by
#: construction.
_PURE_BUILDER_MODULES = (
    "application/campaign_outcome_statistics.py",
    "application/campaign_outcome_runtime.py",
    "application/campaign_outcome_identity.py",
    "application/campaign_outcome_matrix_runtime.py",
)

#: The verified read-only query service and its HTTP route.
_READONLY_MODULES = (
    "application/campaign_outcome_query_service.py",
    "api/routes_campaign_outcome.py",
)

#: Runtime-2 and Phase-24 modules that must not gain Phase 26
#: dependencies (same sets the Phase 25 boundary suite protects).
_RUNTIME2_MODULES = (
    "application/structural_runtime.py",
    "application/replay_service.py",
    "application/run_trajectory_runtime.py",
    "application/trajectory_integrity.py",
    "application/run_metric_observation_service.py",
    "application/campaign_metric_statistics_runtime.py",
)
_PHASE24_MODULES = (
    "application/world_realization_builder.py",
    "application/world_realization_query_service.py",
    "application/world_uncertainty_identity.py",
    "application/world_uncertainty_errors.py",
    "application/world_uncertainty_service.py",
    "application/deterministic_sampler.py",
)

#: The exact 46 public contracts registered before the Phase 26 matrix.
_PRE_PHASE26_CONTRACTS = (
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
    "WorldUncertaintyModel",
    "WorldRealization",
    "CampaignWorldRealizationMatrix",
    "RealizationRunTrajectoryExecution",
    "RealizationRunTrajectoryReplayManifest",
    "RealizationCampaignTrajectoryMatrix",
    "RealizationRunMetricObservationSet",
    "RealizationCampaignMetricObservationMatrix",
    "RealizationCampaignMetricStatisticsMatrix",
)

#: The exact 6 Phase 25 runtime-3 API paths (7 operations; POST+GET
#: share the observation path).
_REALIZATION_PATHS: dict[str, set[str]] = {
    "/v1/runs/{run_id}/realization-trajectory-execution": {"get"},
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest": {"get"},
    "/v1/runs/{run_id}/realization-metric-observations": {"get", "post"},
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-statistics": {"get"},
}

#: Network/provider/database/filesystem/randomness/executable surfaces
#: the Phase 26 kernel must never import.
_FORBIDDEN_MODULES = {
    "socket",
    "requests",
    "urllib",
    "httpx",
    "http",
    "sqlite3",
    "os",
    "sys",
    "subprocess",
    "shutil",
    "tempfile",
    "pathlib",
    "random",
    "uuid",
    "secrets",
    "numpy",
    "pandas",
    "decimal",
    "fractions",
    "importlib",
    "runpy",
    "ctypes",
    "datetime",
    "time",
    "dateutil",
}

#: Wall-clock and nondeterministic call chains that must never appear.
_FORBIDDEN_CALL_CHAINS = {
    "datetime.now",
    "datetime.utcnow",
    "datetime.today",
    "date.today",
    "time.time",
    "time.monotonic",
    "time.perf_counter",
    "time.clock",
    "time.gmtime",
    "time.localtime",
    "random.seed",
    "random.random",
    "random.randint",
    "random.uniform",
    "random.choices",
    "random.sample",
    "uuid.uuid4",
    "uuid.uuid1",
    "os.getpid",
    "os.urandom",
}

#: Exact write/extraction/replay/execution/preparation call names that
#: read-only modules must never invoke.
_FORBIDDEN_WRITE_CALLS = {
    "extract_realization_run_metric_observations",
    "extract_run_metric_observations",
    "replay_realization_run",
    "replay_run",
    "execute_realization_campaign",
    "execute_realization_run",
    "execute_campaign",
    "start_campaign",
    "prepare_campaign",
    "prepare_realization_campaign",
    "prepare_strategy_trajectory_plans",
    "evaluate_trajectory",
    "derive_initial_state",
    "record_operational_activity",
    "put_operational_activity",
    "record_activity",
    "start",
}

#: Phase 27 comparison/decision artifact names - scanned inside the
#: established Phase 26 production modules only (``_PHASE26_MODULES``),
#: which must remain free of the decision surface. The scan is scoped
#: and durable: it never basename-allowlists files and never requires
#: a particular Phase 27 module count, so future Phase 27 modules do
#: not invalidate it.
_PHASE27_ARTIFACT_NAMES = (
    "CampaignDecisionPolicy",
    "ObjectivePairedComparison",
    "StrategyRobustnessProfile",
    "CampaignStrategyComparison",
    "CampaignDecisionBrief",
)

#: Domain vocabulary that must never appear in non-docstring literals.
_DOMAIN_VOCABULARY = re.compile(
    r"\b(maritime|logistics|port|fuel|vessel|cargo|employee|customer|patient|"
    r"invoice|salary|credit|account_number|phone_number|street_address)\b",
    re.IGNORECASE,
)


def _module_tree(relative: str) -> ast.Module:
    return ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``math`` from ``math.fsum``)."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths


def _imported_symbols(tree: ast.Module) -> set[str]:
    """Every name bound by an ``import``/``from`` statement."""
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names)
    return symbols


def _attribute_call_chains(tree: ast.Module) -> set[str]:
    """Dotted callable chains of every call whose target is an attribute."""
    chains: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        parts: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        chains.add(".".join(reversed(parts)))
    return chains


def _name_calls(tree: ast.Module) -> set[str]:
    """Every bare-name call (``sorted(...)`` -> ``sorted``)."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    return calls


def _non_docstring_strings(tree: ast.Module) -> list[str]:
    """String literals excluding module/class/function docstrings."""
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


class TestDomainNeutralKernel:
    def test_no_nexus_or_legion_or_adapter_imports(self) -> None:
        # Phase 26 derives evidence only: no adapter protocol, no mock,
        # no NEXUS/LEGION symbol anywhere.
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            assert not any(
                path == "kalhas.adapters" or path.startswith("kalhas.adapters.")
                for path in module_paths
            ), f"adapter import in {relative}: {sorted(module_paths)}"
            assert not any("Legion" in symbol or "Nexus" in symbol for symbol in symbols), (
                f"adapter symbol in {relative}"
            )

    def test_no_domain_pack_dependency_or_executable_mechanism(self) -> None:
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            assert not any(path.startswith("kalhas.domain_packs") for path in module_paths), (
                f"domain-pack import in {relative}"
            )
            assert not any("DomainPack" in symbol for symbol in symbols), (
                f"domain-pack symbol in {relative}"
            )
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not (calls & {"exec", "eval", "compile", "__import__"}), (
                f"executable mechanism call in {relative}"
            )
            assert not (_imported_modules(tree) & {"importlib", "runpy", "ctypes"}), (
                f"dynamic-loading module in {relative}"
            )

    def test_no_new_architecture_component_or_integration_surface(self) -> None:
        # Phase 26 modules import only the standard library, pydantic,
        # FastAPI (route only), and the existing KALHAS kernel.
        allowed_roots = {
            "__future__",
            "typing",
            "math",
            "warnings",
            "pydantic",
            "fastapi",
            "kalhas",
        }
        for relative in _PHASE26_MODULES:
            modules = _imported_modules(_module_tree(relative))
            assert modules <= allowed_roots, f"unexpected import root in {relative}"

    def test_no_domain_or_personal_data_literals(self) -> None:
        for relative in _PHASE26_MODULES:
            for literal in _non_docstring_strings(_module_tree(relative)):
                assert not _DOMAIN_VOCABULARY.search(literal), (
                    f"domain vocabulary in {relative}: {literal!r}"
                )


class TestDeterminismAndPurity:
    def test_no_network_provider_database_filesystem_imports(self) -> None:
        for relative in _PHASE26_MODULES:
            imported = _imported_modules(_module_tree(relative))
            forbidden = imported & _FORBIDDEN_MODULES
            assert not forbidden, f"forbidden imports in {relative}: {sorted(forbidden)}"

    def test_no_wall_clock_randomness_uuid_or_process_hash_calls(self) -> None:
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not (calls & _FORBIDDEN_CALL_CHAINS), (
                f"nondeterministic call in {relative}: {sorted(calls & _FORBIDDEN_CALL_CHAINS)}"
            )
            assert "hash" not in calls, f"process-hash-dependent call in {relative}"
            assert not any(chain.startswith("random.") for chain in calls), (
                f"randomness call in {relative}"
            )
            assert not (calls & {"random.seed", "secrets"}), f"nondeterministic call in {relative}"

    def test_statistics_module_retains_minimal_import_boundary(self) -> None:
        tree = _module_tree("application/campaign_outcome_statistics.py")
        assert _imported_modules(tree) == {"__future__", "math", "typing"}
        assert not any(path.startswith("kalhas") for path in _imported_module_paths(tree))

    def test_no_clock_or_runtime_selector_parameters(self) -> None:
        from kalhas.application.campaign_outcome_matrix_runtime import (
            build_campaign_outcome_distribution_matrix,
        )
        from kalhas.application.campaign_outcome_query_service import (
            get_verified_campaign_outcome_distributions,
        )
        from kalhas.application.campaign_outcome_runtime import (
            build_strategy_objective_outcome,
        )

        forbidden_parameters = {"now", "clock", "timestamp", "wall_clock", "current_time"}
        for callable_ in (
            build_strategy_objective_outcome,
            build_campaign_outcome_distribution_matrix,
            get_verified_campaign_outcome_distributions,
        ):
            parameters = tuple(inspect.signature(callable_).parameters)
            assert not (forbidden_parameters & set(parameters)), (
                f"{callable_.__name__} accepts a clock/timestamp parameter"
            )
        assert tuple(inspect.signature(get_verified_campaign_outcome_distributions).parameters) == (
            "store",
            "tenant_id",
            "campaign_id",
        )
        assert tuple(inspect.signature(build_campaign_outcome_distribution_matrix).parameters) == (
            "profile",
            "world_realization_matrix",
            "observation_matrix",
        )


class TestDerivedEvidence:
    def test_pure_builders_are_store_free(self) -> None:
        for relative in _PURE_BUILDER_MODULES:
            tree = _module_tree(relative)
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert "store" not in names, f"store reference in the pure builder {relative}"
            assert not ({"InMemoryScenarioStore", "in_memory_store"} & _imported_symbols(tree)), (
                f"store import in the pure builder {relative}"
            )
            attribute_calls = _attribute_call_chains(tree)
            for chain in attribute_calls:
                attribute = chain.rsplit(".", 1)[-1]
                assert not attribute.startswith("put_"), (
                    f"store write call {chain!r} in the pure builder {relative}"
                )
                assert attribute not in _FORBIDDEN_WRITE_CALLS, (
                    f"behavioral call {chain!r} in the pure builder {relative}"
                )
            assert not (_name_calls(tree) & _FORBIDDEN_WRITE_CALLS), (
                f"behavioral call in the pure builder {relative}"
            )

    def test_verified_query_and_route_are_strictly_read_only(self) -> None:
        for relative in _READONLY_MODULES:
            tree = _module_tree(relative)
            attribute_calls = _attribute_call_chains(tree)
            name_calls = _name_calls(tree)
            for chain in attribute_calls:
                attribute = chain.rsplit(".", 1)[-1]
                assert not attribute.startswith("put_"), f"store write call {chain!r} in {relative}"
                assert attribute not in _FORBIDDEN_WRITE_CALLS, (
                    f"behavioral call {chain!r} in {relative}"
                )
                assert "activity" not in attribute and attribute != "record_activity", (
                    f"activity call {chain!r} in {relative}"
                )
            assert not (name_calls & _FORBIDDEN_WRITE_CALLS), (
                f"behavioral call in {relative}: {sorted(name_calls & _FORBIDDEN_WRITE_CALLS)}"
            )

    def test_outcome_matrices_are_derived_and_never_stored(self) -> None:
        # The store has no collection, method, or import for the outcome
        # matrix: the derived artifact cannot be persisted anywhere.
        store_source = (KALHAS_ROOT / "application" / "in_memory_store.py").read_text(
            encoding="utf-8"
        )
        assert "CampaignOutcomeDistributionMatrix" not in store_source
        assert "campaign_outcome" not in store_source

    def test_route_records_no_operational_activity(self) -> None:
        tree = _module_tree("api/routes_campaign_outcome.py")
        symbols = _imported_symbols(tree)
        assert not any("activity" in symbol.lower() for symbol in symbols), (
            f"activity import in routes_campaign_outcome.py: {sorted(symbols)}"
        )
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        assert not (
            calls & {"record_operational_activity", "put_operational_activity", "record_activity"}
        ), f"activity call in routes_campaign_outcome.py: {sorted(calls)}"


class TestPublicApiSurface:
    def test_exactly_one_phase26_get_endpoint_and_no_other_method(self) -> None:
        tree = _module_tree("api/routes_campaign_outcome.py")
        decorated: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(
                        decorator.func, ast.Attribute
                    ):
                        decorated.append((node.name, decorator.func.attr))
        assert decorated == [("get_campaign_outcome_distributions_route", "get")]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"post", "put", "patch", "delete"}, (
                    f"non-GET Phase 26 operation {node.func.attr}"
                )

    def test_runtime_selected_from_recorded_run_plans_never_caller_input(self) -> None:
        import kalhas.api.routes_campaign_outcome as routes_module

        function = routes_module.get_campaign_outcome_distributions_route
        parameters = tuple(inspect.signature(function).parameters)
        assert parameters == ("campaign_id", "request", "x_tenant_id")
        default = inspect.signature(function).parameters["x_tenant_id"].default
        assert type(default).__name__ == "Header"
        assert getattr(default, "alias", None) == "X-Tenant-ID"
        tree = _module_tree("api/routes_campaign_outcome.py")
        chains = _attribute_call_chains(tree)
        assert "store.get_run_plans" in chains, "route does not read the recorded run plans"
        symbols = _imported_symbols(tree)
        assert "REALIZATION_TRAJECTORY_RUNTIME_VERSION" in symbols
        for parameter in parameters:
            assert "runtime" not in parameter.lower()

    def test_public_contract_index_46_and_historical_prefix_unchanged(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 50
        assert names[:46] == _PRE_PHASE26_CONTRACTS
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47] == "CampaignDecisionPolicy"
        assert names[48] == "CampaignStrategyComparison"
        assert names[49] == "CampaignDecisionBrief"

    def test_nested_value_objects_are_not_independently_registered(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names

    def test_schema_artifacts_follow_the_public_registry_with_matching_titles(self) -> None:
        schema_dir = KALHAS_ROOT.parent / "schemas" / "v1"
        schema_files = sorted(schema_dir.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        titles = {json.loads(path.read_text(encoding="utf-8"))["title"] for path in schema_files}
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert titles == names
        file_names = {path.name for path in schema_files}
        assert "CampaignOutcomeDistributionMatrix.schema.json" in file_names
        assert "EmpiricalDistributionSummary.schema.json" not in file_names
        assert "StrategyObjectiveOutcome.schema.json" not in file_names

    def test_phase25_paths_and_operations_remain_unchanged(self) -> None:
        spec = create_app().openapi()
        paths = spec["paths"]
        realization_paths = {
            path: set(ops) for path, ops in paths.items() if "realization-" in path
        }
        assert realization_paths == _REALIZATION_PATHS
        assert sum(len(ops) for ops in _REALIZATION_PATHS.values()) == 7
        outcome_paths = {
            path: set(ops) for path, ops in paths.items() if "outcome-distributions" in path
        }
        assert outcome_paths == {"/v1/campaigns/{campaign_id}/outcome-distributions": {"get"}}


class TestStatisticalDecisionBoundary:
    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        contract_fields = set(CampaignOutcomeDistributionMatrix.model_fields)
        contract_fields |= set(StrategyObjectiveOutcome.model_fields)
        contract_fields |= set(EmpiricalDistributionSummary.model_fields)
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            symbols: list[str] = list(_imported_symbols(tree))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(node.name)
                    symbols.extend(argument.arg for argument in node.args.args)
                if isinstance(node, ast.ClassDef):
                    symbols.append(node.name)
            for symbol in symbols:
                assert not forbidden.search(symbol), f"forbidden symbol {symbol!r} in {relative}"
        for field in contract_fields:
            assert not forbidden.search(field), f"forbidden contract field {field!r}"

    def test_no_executable_expression_or_callback_surface(self) -> None:
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            for node in ast.walk(tree):
                assert not isinstance(node, ast.Lambda), f"lambda in {relative}"
                if isinstance(node, ast.Call):
                    name: str | None = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    assert name not in {"exec", "eval", "compile", "__import__"}, (
                        f"executable call {name!r} in {relative}"
                    )
            symbols = _imported_symbols(tree)
            assert not any(symbol in symbols for symbol in ("Callable", "callback")), (
                f"callback surface in {relative}"
            )

    def test_no_adaptive_policy_surface(self) -> None:
        for relative in _PHASE26_MODULES:
            tree = _module_tree(relative)
            symbols = _imported_symbols(tree)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(node.name)
                if isinstance(node, ast.ClassDef):
                    symbols.add(node.name)
            assert not any("adaptive" in symbol.lower() for symbol in symbols), (
                f"adaptive surface in {relative}"
            )

    def test_phase26_modules_remain_free_of_decision_surface(self) -> None:
        # Durable historical boundary: the established Phase 26
        # production modules themselves must remain free of
        # decision-contract imports and decision artifacts. The scan is
        # scoped to the fixed ``_PHASE26_MODULES`` collection only - it
        # does not globally forbid new Phase 27 modules elsewhere in
        # the kernel, does not basename-allowlist files, and does not
        # require any particular Phase 27 module count. Complete
        # decision-surface restrictions belong to the future dedicated
        # Phase 27 boundary suite.
        pattern = re.compile(
            r"\b(" + "|".join(_PHASE27_ARTIFACT_NAMES) + r")\b|campaign_decision|"
            r"feasibility-pareto-minimax-regret-v1"
        )
        for relative in _PHASE26_MODULES:
            source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
            assert not pattern.search(source), (
                f"decision artifact surface in the Phase 26 module {relative}"
            )
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            assert not any(
                path.startswith("kalhas.contracts.v1.campaign_decision")
                or path.startswith("kalhas.application.campaign_decision")
                for path in module_paths
            ), f"decision import in the Phase 26 module {relative}: {sorted(module_paths)}"


class TestVersioningAndCompatibility:
    def test_api_and_schema_versions_unchanged(self) -> None:
        assert API_VERSION == "1"
        assert SCHEMA_VERSION == "1.0.0"

    def test_runtime_stays_exactly_three_zero(self) -> None:
        from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION

        assert REALIZATION_TRAJECTORY_RUNTIME_VERSION == "3.0.0"
        # No Phase 26 module carries any other runtime-version literal
        # (no 1.0.0/2.0.0 dispatch, no reinterpretation surface).
        for relative in _PHASE26_MODULES:
            for literal in _non_docstring_strings(_module_tree(relative)):
                assert literal not in ("1.0.0", "2.0.0"), (
                    f"legacy runtime literal in {relative}: {literal!r}"
                )

    def test_query_dispatch_has_no_legacy_runtime_surface(self) -> None:
        # The verified query derives only from the recorded campaign and
        # run-plan records; the route gates every recorded plan on the
        # exact 3.0.0 constant before the query is invoked (proven
        # behaviorally in the API suite; structurally here).
        tree = _module_tree("application/campaign_outcome_query_service.py")
        assert "CampaignState" in _imported_symbols(tree)
        assert "CampaignNotCompleteError" in _imported_symbols(tree)
        route_symbols = _imported_symbols(_module_tree("api/routes_campaign_outcome.py"))
        assert "UnsupportedRuntimeVersionError" in route_symbols
        assert "REALIZATION_TRAJECTORY_RUNTIME_VERSION" in route_symbols
        chains = _attribute_call_chains(_module_tree("api/routes_campaign_outcome.py"))
        assert "store.get_run_plans" in chains

    def test_no_phase26_dependency_in_runtime2_or_phase24_modules(self) -> None:
        for relative in _RUNTIME2_MODULES + _PHASE24_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            assert not any(
                path.startswith("kalhas.application.campaign_outcome")
                or path.startswith("kalhas.contracts.v1.campaign_outcome")
                for path in module_paths
            ), f"Phase 26 import in {relative}: {sorted(module_paths)}"
            assert not any(
                symbol.startswith("CampaignOutcome") or symbol.startswith("empirical_")
                for symbol in symbols
            ), f"Phase 26 symbol in {relative}: {sorted(symbols)}"
