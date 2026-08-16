"""Phase 25 boundary scans.

Architectural protection for the runtime-3 (3.0.0) surface using precise
AST, import-graph, and symbol scans - never raw substring matching, so
docstrings, comments, and type names cannot false-positive. Proves:

- the domain-neutral kernel imports no NEXUS/LEGION internals (only the
  two placeholder adapter protocols at planning boundaries) and no
  runtime-3 module touches domain packs or executable mechanisms;
- execution, replay, observation, and matrix modules never invoke
  LEGION - the adapter boundary is used only during campaign/trajectory
  planning;
- no network, provider, database, filesystem, wall-clock, or
  nondeterministic-randomness surface; recorded ``created_at`` values
  are the only timestamp authority (no clock parameter exists);
- derived realizations and campaign matrices are never stored and the
  verified query services are strictly read-only;
- runtime-2 and Phase-24 production modules carry no runtime-3
  dependency; the runtime-3 API surface is exactly 6 paths / 7
  operations;
- exactly 47 public contracts with the exact historical 0-39 prefix,
  the exact six-contract runtime-3 tail at indexes 40-45, and the
  campaign outcome-distribution matrix at index 46, and exactly 47
  schema artifacts;
- no Phase 26/27 surface and no outcome/ranking/score/evidence/
  recommendation/live-action surface;
- the 12 runtime-3 typed errors are all mapped in ``api/errors.py`` and
  every runtime-3 route records no operational activity.

Ephemeral repository state (HEAD hashes, git status, staged state,
worktree file lists, remote state) is intentionally not encoded here -
those are closure-gate/report checks, not permanent architecture.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from kalhas.contracts.v1 import PUBLIC_CONTRACTS

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"

#: Every Phase 25 runtime-3 production module.
_RUNTIME3_MODULES = (
    "application/realization_campaign_service.py",
    "application/realization_campaign_trajectory_runtime.py",
    "application/realization_campaign_trajectory_query_service.py",
    "application/realization_campaign_metric_observation_runtime.py",
    "application/realization_campaign_metric_observation_query_service.py",
    "application/realization_campaign_metric_statistics_runtime.py",
    "application/realization_campaign_metric_statistics_query_service.py",
    "application/realization_errors.py",
    "application/realization_execution.py",
    "application/realization_identity.py",
    "application/realization_integrity.py",
    "application/realization_replay.py",
    "application/realization_run_metric_observation_service.py",
    "application/realization_trajectory_runtime.py",
    "api/routes_realization.py",
)

#: Execution, replay, observation, and matrix modules: the runtime-3
#: surface that must never touch the LEGION boundary.
_EXECUTION_REPLAY_OBSERVATION_MATRIX = (
    "application/realization_execution.py",
    "application/realization_replay.py",
    "application/realization_run_metric_observation_service.py",
    "application/realization_trajectory_runtime.py",
    "application/realization_integrity.py",
    "application/realization_campaign_trajectory_runtime.py",
    "application/realization_campaign_trajectory_query_service.py",
    "application/realization_campaign_metric_observation_runtime.py",
    "application/realization_campaign_metric_observation_query_service.py",
    "application/realization_campaign_metric_statistics_runtime.py",
    "application/realization_campaign_metric_statistics_query_service.py",
)

#: The three verified read-only query services.
_QUERY_MODULES = (
    "application/realization_campaign_trajectory_query_service.py",
    "application/realization_campaign_metric_observation_query_service.py",
    "application/realization_campaign_metric_statistics_query_service.py",
)

#: The pure derived-matrix builders (plus the Phase 24 realization
#: builder): never stored, never store-aware.
_DERIVED_BUILDER_MODULES = (
    "application/realization_campaign_trajectory_runtime.py",
    "application/realization_campaign_metric_observation_runtime.py",
    "application/realization_campaign_metric_statistics_runtime.py",
    "application/world_realization_builder.py",
)

#: Runtime-2 and Phase-24 modules that must not gain runtime-3
#: dependencies.
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

#: The exact 40 contracts registered before Phase 25.
_PRE_PHASE25_CONTRACTS = (
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
)

#: The exact six runtime-3 contracts appended at indexes 40-45.
_RUNTIME3_CONTRACTS = (
    "RealizationRunTrajectoryExecution",
    "RealizationRunTrajectoryReplayManifest",
    "RealizationCampaignTrajectoryMatrix",
    "RealizationRunMetricObservationSet",
    "RealizationCampaignMetricObservationMatrix",
    "RealizationCampaignMetricStatisticsMatrix",
)

#: The exact 6 runtime-3 API paths (7 operations; POST+GET share the
#: observation path).
_RUNTIME3_PATHS = (
    "/v1/runs/{run_id}/realization-trajectory-execution",
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest",
    "/v1/runs/{run_id}/realization-metric-observations",
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix",
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix",
    "/v1/campaigns/{campaign_id}/realization-metric-statistics",
)

#: Network/provider/database/filesystem/randomness surfaces that the
#: runtime-3 kernel must never import.
_FORBIDDEN_MODULES = {
    "socket",
    "requests",
    "urllib",
    "httpx",
    "http",
    "sqlite3",
    "os",
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
}

#: Exact write/extraction/replay/execution call names that read-only
#: modules must never invoke (attribute terminals or bare name calls).
_FORBIDDEN_WRITE_CALLS = {
    "extract_realization_run_metric_observations",
    "extract_run_metric_observations",
    "replay_realization_run",
    "replay_run",
    "execute_realization_campaign",
    "execute_campaign",
    "execute_realization_run",
    "start_campaign",
    "prepare_campaign",
    "prepare_realization_campaign",
    "prepare_strategy_trajectory_plans",
    "evaluate_trajectory",
    "derive_initial_state",
    "build_world_realization",
    "record_operational_activity",
    "put_operational_activity",
    "record_activity",
}

#: Outcome/ranking/score/evidence/recommendation surface symbols.
_FORBIDDEN_SYMBOLS = {
    "OutcomeVector",
    "EvidenceReference",
    "DecisionBrief",
    "MetricOutcome",
    "ScenarioEvaluationProfile",
    "CampaignObjectiveEvaluationMatrix",
    "rank",
    "score",
    "recommend",
}

#: Domain vocabulary and personal-data patterns that must never appear
#: in non-docstring literals (word-boundary precise).
_DOMAIN_VOCABULARY = re.compile(
    r"\b(maritime|logistics|port|fuel|vessel|cargo|employee|customer|patient|"
    r"invoice|salary|credit|account_number|phone_number|street_address)\b",
    re.IGNORECASE,
)


def _module_tree(relative: str) -> ast.Module:
    return ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``requests`` from ``requests.adapters``)."""
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
    """Dotted callable chains of every call whose target is an attribute.

    ``datetime.now(...)`` becomes ``datetime.now``; ``store.get_run(...)``
    becomes ``store.get_run``. Bare-name calls (``verify_run_inputs(...)``)
    are deliberately excluded - they are reported by :func:`_name_calls`.
    """
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
    """Every bare-name call (``verify_run_inputs(...)`` -> ``verify_run_inputs``)."""
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
    def test_no_nexus_or_legion_internal_imports(self) -> None:
        # The kernel may only couple through the placeholder adapter
        # protocols, and only the preparation service holds the LEGION
        # protocol; every other runtime-3 module imports no adapter
        # module and no adapter symbol at all.
        for relative in _RUNTIME3_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            if relative == "application/realization_campaign_service.py":
                # The preparation service holds the LEGION protocol as
                # its only adapter coupling.
                assert "kalhas.adapters.legion" in module_paths
                assert not any(
                    path != "kalhas.adapters.legion"
                    and (path == "kalhas.adapters" or path.startswith("kalhas.adapters."))
                    for path in module_paths
                )
                assert "LegionAdapter" in symbols
                continue
            assert not any(
                path == "kalhas.adapters" or path.startswith("kalhas.adapters.")
                for path in module_paths
            ), f"adapter import in {relative}: {sorted(module_paths)}"
            assert not any("Legion" in symbol or "Nexus" in symbol for symbol in symbols), (
                f"adapter symbol in {relative}"
            )

    def test_planning_boundaries_import_only_the_protocol(self) -> None:
        # The three planning modules are the only application modules
        # allowed to import the adapter package, and they import exactly
        # the placeholder LegionAdapter protocol - never mocks or
        # internals.
        for relative in (
            "application/campaign_service.py",
            "application/strategy_trajectory_service.py",
            "application/realization_campaign_service.py",
        ):
            tree = _module_tree(relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module is None:
                    continue
                if node.module == "kalhas.adapters" or node.module.startswith("kalhas.adapters."):
                    assert node.module == "kalhas.adapters.legion", (
                        f"non-protocol adapter import in {relative}: {node.module}"
                    )
                    assert [alias.name for alias in node.names] == ["LegionAdapter"], (
                        f"non-protocol adapter symbol in {relative}"
                    )

    def test_no_nexus_or_legion_imports_in_application_kernel(self) -> None:
        # Every application module outside the three planning boundaries
        # imports no adapter module and no adapter symbol.
        planning = {
            "campaign_service.py",
            "strategy_trajectory_service.py",
            "realization_campaign_service.py",
        }
        offenders: list[str] = []
        for path in sorted((KALHAS_ROOT / "application").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            module_paths = _imported_module_paths(tree)
            if (
                any(
                    module_path == "kalhas.adapters" or module_path.startswith("kalhas.adapters.")
                    for module_path in module_paths
                )
                and path.name not in planning
            ):
                offenders.append(path.name)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and (
                        node.module == "kalhas.adapters"
                        or node.module.startswith("kalhas.adapters.")
                    )
                ):
                    for alias in node.names:
                        if alias.name not in ("LegionAdapter", "NexusAdapter"):
                            offenders.append(f"{path.name}:{alias.name}")
        assert offenders == [], f"adapter imports outside planning boundaries: {offenders}"

    def test_no_domain_pack_or_executable_mechanism_surface(self) -> None:
        for relative in _RUNTIME3_MODULES:
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

    def test_no_domain_or_personal_data_literals(self) -> None:
        for relative in _RUNTIME3_MODULES:
            literals = _non_docstring_strings(_module_tree(relative))
            for literal in literals:
                assert not _DOMAIN_VOCABULARY.search(literal), (
                    f"domain vocabulary in {relative}: {literal!r}"
                )


class TestDeterminism:
    def test_no_network_provider_database_filesystem_imports(self) -> None:
        for relative in _RUNTIME3_MODULES:
            imported = _imported_modules(_module_tree(relative))
            forbidden = imported & _FORBIDDEN_MODULES
            assert not forbidden, f"forbidden imports in {relative}: {sorted(forbidden)}"

    def test_no_wall_clock_or_nondeterministic_randomness_calls(self) -> None:
        for relative in _RUNTIME3_MODULES:
            tree = _module_tree(relative)
            calls = _attribute_call_chains(tree)
            assert not (calls & _FORBIDDEN_CALL_CHAINS), (
                f"wall-clock call in {relative}: {sorted(calls & _FORBIDDEN_CALL_CHAINS)}"
            )
            assert not any(chain.startswith("random.") for chain in calls), (
                f"randomness call in {relative}"
            )
            assert not any(chain in ("uuid.uuid4", "uuid.uuid1") for chain in calls), (
                f"uuid call in {relative}"
            )
            assert not (calls & {"random.seed", "secrets"}), f"nondeterministic call in {relative}"

    def test_input_integrity_chain_never_resamples(self) -> None:
        # The realization reconstruction chain is deterministic only:
        # no randomness modules, no resample calls, no sampling outside
        # the fixed builder.
        for relative in (
            "application/input_integrity.py",
            "application/run_trajectory_inputs.py",
            "application/realization_replay.py",
            "application/realization_execution.py",
        ):
            tree = _module_tree(relative)
            imported = _imported_modules(tree)
            assert not (imported & {"random", "uuid", "secrets"}), (
                f"randomness import in {relative}"
            )
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not any("resample" in call for call in calls), f"resample call in {relative}"

    def test_reconstruction_happens_only_in_the_input_integrity_chain(self) -> None:
        # Execution, replay, observation, and matrix modules regenerate
        # from verified inputs; they never reconstruct a realization.
        for relative in _EXECUTION_REPLAY_OBSERVATION_MATRIX:
            tree = _module_tree(relative)
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert "build_world_realization" not in calls, (
                f"realization reconstruction in {relative}"
            )

    def test_no_clock_parameter_in_runtime3_callables(self) -> None:
        from kalhas.application.realization_campaign_metric_observation_runtime import (
            build_realization_campaign_metric_observation_matrix,
        )
        from kalhas.application.realization_campaign_metric_statistics_runtime import (
            build_realization_campaign_metric_statistics_matrix,
        )
        from kalhas.application.realization_campaign_trajectory_runtime import (
            build_realization_campaign_trajectory_matrix,
        )
        from kalhas.application.realization_execution import execute_realization_run
        from kalhas.application.realization_replay import replay_realization_run
        from kalhas.application.realization_run_metric_observation_service import (
            build_realization_run_metric_observation_set,
            get_verified_realization_run_metric_observation_set,
        )
        from kalhas.application.realization_trajectory_runtime import (
            build_realization_run_trajectory_execution,
        )

        forbidden_parameters = {"now", "clock", "timestamp", "wall_clock", "current_time"}
        for callable_ in (
            build_realization_run_trajectory_execution,
            build_realization_run_metric_observation_set,
            get_verified_realization_run_metric_observation_set,
            build_realization_campaign_trajectory_matrix,
            build_realization_campaign_metric_observation_matrix,
            build_realization_campaign_metric_statistics_matrix,
            replay_realization_run,
            execute_realization_run,
        ):
            parameters = tuple(inspect.signature(callable_).parameters)
            assert not (forbidden_parameters & set(parameters)), (
                f"{callable_.__name__} accepts a clock/timestamp parameter"
            )


class TestRuntimeOwnership:
    def test_execution_replay_observation_matrix_never_invoke_legion(self) -> None:
        for relative in _EXECUTION_REPLAY_OBSERVATION_MATRIX:
            tree = _module_tree(relative)
            symbols = _imported_symbols(tree)
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not any("Legion" in symbol or "Nexus" in symbol for symbol in symbols), (
                f"adapter symbol in {relative}"
            )
            assert not (calls & {"request_strategies", "request_trajectory_plan"}), (
                f"LEGION call in {relative}"
            )

    def test_legion_used_only_at_planning_boundaries(self) -> None:
        # The adapter protocol is imported exactly by the three planning
        # modules; the realization preparation service is the only
        # runtime-3 module allowed to hold the boundary.
        for relative in (
            "application/campaign_service.py",
            "application/strategy_trajectory_service.py",
            "application/realization_campaign_service.py",
        ):
            tree = _module_tree(relative)
            symbols = _imported_symbols(tree)
            assert "LegionAdapter" in symbols, f"{relative} lost its LegionAdapter protocol"
        # No runtime-3 module other than the preparation service may
        # name the adapter at all.
        for relative in _RUNTIME3_MODULES:
            if relative == "application/realization_campaign_service.py":
                continue
            tree = _module_tree(relative)
            symbols = _imported_symbols(tree)
            assert not any("Legion" in symbol or "Nexus" in symbol for symbol in symbols), (
                f"adapter symbol in {relative}"
            )


class TestReadOnlyBoundaries:
    def test_verified_query_services_are_strictly_read_only(self) -> None:
        for relative in _QUERY_MODULES:
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

    def test_observation_get_path_is_read_only(self) -> None:
        # The extraction service module legitimately writes on its POST
        # path; the verified GET path itself must stay read-only.
        from kalhas.application.realization_run_metric_observation_service import (
            get_verified_realization_run_metric_observation_set,
        )

        function_tree = ast.parse(
            inspect.getsource(get_verified_realization_run_metric_observation_set)
        )
        attribute_calls = _attribute_call_chains(function_tree)
        name_calls = _name_calls(function_tree)
        for chain in attribute_calls:
            attribute = chain.rsplit(".", 1)[-1]
            assert not attribute.startswith("put_"), (
                f"store write call {chain!r} in the observation GET path"
            )
            assert attribute not in _FORBIDDEN_WRITE_CALLS, (
                f"behavioral call {chain!r} in the observation GET path"
            )
        assert not (name_calls & _FORBIDDEN_WRITE_CALLS), (
            f"behavioral call in the observation GET path: "
            f"{sorted(name_calls & _FORBIDDEN_WRITE_CALLS)}"
        )

    def test_matrices_and_realizations_are_derived_never_stored(self) -> None:
        for relative in _DERIVED_BUILDER_MODULES:
            tree = _module_tree(relative)
            assert "store" not in {
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            }, f"store reference in the pure builder {relative}"
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

    def test_phase24_realization_query_remains_derived(self) -> None:
        tree = _module_tree("application/world_realization_query_service.py")
        attribute_calls = _attribute_call_chains(tree)
        for chain in attribute_calls:
            attribute = chain.rsplit(".", 1)[-1]
            assert not attribute.startswith("put_"), (
                f"store write call {chain!r} in the Phase 24 query service"
            )
            assert attribute not in _FORBIDDEN_WRITE_CALLS, (
                f"behavioral call {chain!r} in the Phase 24 query service"
            )
        assert not (_name_calls(tree) & _FORBIDDEN_WRITE_CALLS)


class TestRuntimeSeparation:
    def test_runtime2_and_phase24_modules_have_no_runtime3_dependency(self) -> None:
        for relative in _RUNTIME2_MODULES + _PHASE24_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            assert not any(
                path.startswith("kalhas.application.realization") for path in module_paths
            ), f"runtime-3 import in {relative}: {sorted(module_paths)}"
            assert not any(symbol.startswith("Realization") for symbol in symbols), (
                f"runtime-3 symbol in {relative}"
            )
            assert not any(symbol.startswith("realization_") for symbol in symbols), (
                f"runtime-3 helper in {relative}"
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "3.0.0":
                    raise AssertionError(f"runtime-3 literal in {relative}")

    def test_runtime3_uses_separate_contracts_and_endpoints(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[40:46] == _RUNTIME3_CONTRACTS
        # The runtime-3 router only serves realization paths.
        tree = _module_tree("api/routes_realization.py")
        paths = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "post")
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        assert paths == set(_RUNTIME3_PATHS)

    def test_exactly_six_paths_seven_operations(self) -> None:
        tree = _module_tree("api/routes_realization.py")
        gets = posts = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in ("get", "post")
                    ):
                        if decorator.func.attr == "get":
                            gets += 1
                        else:
                            posts += 1
        assert gets == 6
        assert posts == 1

    def test_no_phase26_or_27_surface(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for path in (
            sorted((KALHAS_ROOT / "api").glob("*.py"))
            + sorted((KALHAS_ROOT / "application").glob("*.py"))
            + sorted((KALHAS_ROOT / "contracts").rglob("*.py"))
        ):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        assert offenders == [], f"Phase 26/27 surface found: {offenders}"


class TestPublicCompatibility:
    def test_public_contracts_exactly_47(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 47

    def test_indexes_0_through_39_keep_historical_order(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[:40] == _PRE_PHASE25_CONTRACTS

    def test_runtime3_contracts_occupy_exact_tail_order(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert names[40:46] == _RUNTIME3_CONTRACTS
        assert names[46] == "CampaignOutcomeDistributionMatrix"

    def test_exactly_47_schema_artifacts_with_matching_titles(self) -> None:
        import json

        schema_dir = KALHAS_ROOT.parent / "schemas" / "v1"
        schema_files = sorted(schema_dir.glob("*.schema.json"))
        assert len(schema_files) == 47
        titles = {json.loads(path.read_text(encoding="utf-8"))["title"] for path in schema_files}
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert titles == names
        # The 40 historical artifacts are present under their historical
        # names (additive registration; the runtime-2 titles are
        # unchanged - the schema-sync and OpenAPI $ref canary suites
        # guard their byte content).
        historical_files = {f"{name}.schema.json" for name in _PRE_PHASE25_CONTRACTS}
        assert len(historical_files) == 40
        assert historical_files <= {path.name for path in schema_files}


class TestSafety:
    def test_no_outcome_ranking_score_evidence_surface(self) -> None:
        for relative in _RUNTIME3_MODULES:
            tree = _module_tree(relative)
            symbols = _imported_symbols(tree)
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not (symbols & _FORBIDDEN_SYMBOLS), (
                f"forbidden symbol in {relative}: {sorted(symbols & _FORBIDDEN_SYMBOLS)}"
            )
            assert not (calls & _FORBIDDEN_SYMBOLS), (
                f"forbidden call in {relative}: {sorted(calls & _FORBIDDEN_SYMBOLS)}"
            )

    def test_realization_errors_are_typed_and_mapped(self) -> None:
        import kalhas.application.realization_errors as realization_errors_module
        from kalhas.application.domain_errors import KalhasDomainError

        tree = _module_tree("application/realization_errors.py")
        error_classes = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Error")
        ]
        assert len(error_classes) == 12
        for name in error_classes:
            error_type = getattr(realization_errors_module, name)
            assert issubclass(error_type, KalhasDomainError)
        # Every runtime-3 typed error is mapped in the API error mapper.
        errors_source = (KALHAS_ROOT / "api" / "errors.py").read_text(encoding="utf-8")
        for name in error_classes:
            assert name in errors_source, f"{name} is not mapped in api/errors.py"

    def test_runtime3_routes_record_no_operational_activity(self) -> None:
        tree = _module_tree("api/routes_realization.py")
        symbols = _imported_symbols(tree)
        assert not any("activity" in symbol.lower() for symbol in symbols), (
            f"activity import in routes_realization.py: {sorted(symbols)}"
        )
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        assert not (
            calls & {"record_operational_activity", "put_operational_activity", "record_activity"}
        ), f"activity call in routes_realization.py: {sorted(calls)}"
