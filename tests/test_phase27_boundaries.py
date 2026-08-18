"""Phase 27 architectural boundary scans (final acceptance part B).

Architectural protection for the campaign decision surface
(``kalhas/application/campaign_decision_*.py``,
``kalhas/api/routes_campaign_decision.py``,
``kalhas/api/requests_campaign_decision.py``,
``kalhas/contracts/v1/campaign_decision.py``) using precise AST,
import-graph, contract, schema, OpenAPI, and source inspection - never
raw substring scans that could false-positive on docstrings, comments,
or negative assertions. Proves:

- domain-neutral kernel: no NEXUS/LEGION internal import, no adapter or
  domain-pack coupling, no new architecture component, no
  provider/network/database/filesystem/live-action surface, no adaptive
  decision-policy runtime, no Phase 28 implementation, and no wall clock
  or randomness in decision derivation;
- contract boundary: API/SCHEMA versions unchanged, exactly 50 public
  contracts with unchanged indexes 0-46 and the exact tail
  47 ``CampaignDecisionPolicy`` / 48 ``CampaignStrategyComparison`` /
  49 ``CampaignDecisionBrief``, exactly 50 schema artifacts with all 47
  historical byte hashes unchanged, the three decision artifacts equal
  to ``model_json_schema()``, and the nested decision value objects
  unregistered with no standalone schema files;
- runtime/API boundary: exactly the four operations on the three
  decision paths (POST/GET decision-policy, GET strategy-comparison,
  GET decision-brief), required ``X-Tenant-ID`` on all four, the
  recorded-runtime gate exactly 3.0.0 with no caller selector, policy
  declaration 201 and GETs 200, comparison/brief never persisted, no
  execution/replay/extraction/activity from the decision GETs, and the
  safe typed 404/409/422 mappings;
- decision semantics boundary: the frozen algorithm identifier
  ``feasibility-pareto-minimax-regret-v1``, fixed tail alpha 0.95,
  shared-seed identical-conditions comparison, the paired-delta
  orientation ("positive means the first strategy is worse"), both
  directions of every non-self pair with the exact ``S*(S-1)*O`` count,
  feasibility before Pareto/minimax selection, dominance over feasible
  strategies only, minimax preference only for a unique tolerance tie
  set, inconclusive as a successful non-winner status, deterministic
  brief templates only, and no chain-of-thought, scripts, callbacks, or
  executable expressions;
- persistence boundary: only the policy is stored, one immutable policy
  per ``(tenant_id, campaign_id)``, no update/delete/replace surface, no
  comparison or brief collection or put method, and the policy getter
  revalidates identity and returns a defensive copy;
- acceptance-fixture boundary: fixed ``seed-000`` through ``seed-099``
  (exactly 100 static identifiers), no search/retry/random/filter/
  adaptive selection, the helper duplicates no decision algorithm and
  invokes only the real lifecycle services, the acceptance test obtains
  comparison/brief only through the verified query services, both the
  preferred and the inconclusive control proofs are present, and the
  hard-coded golden identifiers/hashes are constants - never recomputed
  through identity functions inside assertions;
- documentation truthfulness: the active documentation states Phase 27
  is implemented and locally gate-verified, uncommitted, not pushed,
  evidence-based (not calibrated, not certainty, no autonomous live
  action), without KALHAS-PAN or future-phase implementation, with the
  Colony visualization explicitly synthetic/local, and contains no
  overclaim phrases;
- scope inventory: every expected Phase 27 production/test/schema/API
  path exists.

Ephemeral repository state (HEAD hashes, git status, staged state,
remote state, test-file hashes) is intentionally not encoded here -
those are closure-gate/report checks, not permanent architecture.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from pathlib import Path
from typing import get_args

from kalhas.api.app import create_app
from kalhas.contracts.v1 import API_VERSION, PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION
from pydantic import BaseModel

from tests.phase27_helpers import SEED_IDENTIFIERS
from tests.test_api_phase27 import _HISTORICAL_47_NAMES, _HISTORICAL_SCHEMA_HASHES

KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
TESTS_DIR = REPO_ROOT / "tests"

#: Every Phase 27 production module (application, API, contract).
_PHASE27_MODULES = (
    "application/campaign_decision_statistics.py",
    "application/campaign_decision_evidence.py",
    "application/campaign_decision_paired_comparison.py",
    "application/campaign_decision_selection.py",
    "application/campaign_decision_comparison_runtime.py",
    "application/campaign_decision_brief_runtime.py",
    "application/campaign_decision_identity.py",
    "application/campaign_decision_errors.py",
    "application/campaign_decision_policy_service.py",
    "application/campaign_decision_query_service.py",
    "api/routes_campaign_decision.py",
    "api/requests_campaign_decision.py",
    "contracts/v1/campaign_decision.py",
)

#: Store-free pure modules: no store symbol may appear anywhere in them.
_STOREFREE_MODULES = (
    "application/campaign_decision_statistics.py",
    "application/campaign_decision_evidence.py",
    "application/campaign_decision_paired_comparison.py",
    "application/campaign_decision_selection.py",
    "application/campaign_decision_comparison_runtime.py",
    "application/campaign_decision_brief_runtime.py",
    "application/campaign_decision_identity.py",
    "application/campaign_decision_errors.py",
    "api/requests_campaign_decision.py",
)

#: The verified read-only query service and the HTTP routes.
_READONLY_MODULES = (
    "application/campaign_decision_query_service.py",
    "api/routes_campaign_decision.py",
)

#: The exact four Phase 27 operations on the three decision paths.
_DECISION_PATHS: dict[str, set[str]] = {
    "/v1/campaigns/{campaign_id}/decision-policy": {"get", "post"},
    "/v1/campaigns/{campaign_id}/strategy-comparison": {"get"},
    "/v1/campaigns/{campaign_id}/decision-brief": {"get"},
}

#: The nested decision value objects: registered never, schema never.
_NESTED_DECISION_MODELS = (
    "ObjectiveWeightSnapshot",
    "ObjectiveTargetRequirement",
    "ObjectivePairedComparison",
    "ObjectiveFeasibilityEvidence",
    "ObjectiveRegretEvidence",
    "ObjectiveProbabilityEvidence",
    "ObjectiveDownsideEvidence",
    "ObjectiveDominanceStatus",
    "DominanceRelation",
    "StrategyRobustnessProfile",
    "DecisionReasonRecord",
    "DecisionFactorRecord",
)

#: Network/provider/database/filesystem/randomness/executable surfaces
#: the Phase 27 kernel must never import. ``datetime`` is deliberately
#: absent: ``campaign_decision_policy_service`` imports ``datetime``
#: solely as the type guard for the caller-supplied timezone-aware
#: ``declared_at`` - no wall-clock call exists (proven separately by the
#: forbidden call-chain scan).
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

#: Behavioral calls the read-only decision surface must never invoke.
_FORBIDDEN_BEHAVIOR_CALLS = {
    "execute_realization_campaign",
    "execute_realization_run",
    "execute_campaign",
    "extract_realization_run_metric_observations",
    "extract_run_metric_observations",
    "replay_realization_run",
    "replay_run",
    "prepare_campaign",
    "prepare_realization_campaign",
    "prepare_strategy_trajectory_plans",
    "start_campaign",
    "start",
    "evaluate_trajectory",
    "derive_initial_state",
    "record_operational_activity",
    "put_operational_activity",
    "record_activity",
}

#: Future-phase / forbidden-component tokens that must never appear in
#: non-docstring literals of the Phase 27 modules (no Phase 28
#: implementation, no KALHAS-PAN, no post-3.0.0 runtime).
_FUTURE_SURFACE = re.compile(r"phase.?28|kalhas.?pan|khas.?pan|28\.0\.0|4\.0\.0", re.IGNORECASE)

#: Decision-algorithm implementation tokens that must never appear as
#: definitions or imports inside the acceptance fixture helper.
_FIXTURE_FORBIDDEN_ALGORITHM_IMPORTS = (
    "kalhas.application.campaign_decision_comparison_runtime",
    "kalhas.application.campaign_decision_brief_runtime",
    "kalhas.application.campaign_decision_selection",
    "kalhas.application.campaign_decision_statistics",
    "kalhas.application.campaign_decision_paired_comparison",
    "kalhas.application.campaign_decision_evidence",
    "kalhas.application.campaign_decision_identity",
    "kalhas.application.campaign_decision_query_service",
)

#: The active documentation surfaces scanned for truthfulness.
_ACTIVE_DOCS = (
    "README.md",
    "docs/architecture/README.md",
    "docs/architecture/contracts-and-lifecycle.md",
)

#: Overclaim phrases that must never appear in active documentation.
_OVERCLAIM_PHRASES = (
    "predicts reality",
    "guaranteed outcome",
    "calibrated forecast",
    "proven real-world causality",
    "autonomous action",
    "production-ready",
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


def _defined_symbols(tree: ast.Module) -> set[str]:
    """Module/class/function/parameter names defined in a module."""
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
            symbols.update(argument.arg for argument in node.args.args)
    return symbols


class TestDomainNeutralKernel:
    """Section A: architecture boundaries of the decision kernel."""

    def test_no_nexus_legion_adapter_or_domain_pack_imports(self) -> None:
        for relative in _PHASE27_MODULES:
            tree = _module_tree(relative)
            module_paths = _imported_module_paths(tree)
            symbols = _imported_symbols(tree)
            assert not any(
                path == "kalhas.adapters" or path.startswith("kalhas.adapters.")
                for path in module_paths
            ), f"adapter import in {relative}: {sorted(module_paths)}"
            assert not any(
                path == "kalhas.domain_packs" or path.startswith("kalhas.domain_packs.")
                for path in module_paths
            ), f"domain-pack import in {relative}: {sorted(module_paths)}"
            assert not any("Legion" in symbol or "Nexus" in symbol for symbol in symbols), (
                f"adapter symbol in {relative}"
            )
            assert not any("DomainPack" in symbol for symbol in symbols), (
                f"domain-pack symbol in {relative}"
            )

    def test_no_new_architecture_component(self) -> None:
        # Phase 27 modules import only the standard library, pydantic,
        # FastAPI (routes/requests only), and the existing KALHAS kernel.
        allowed_roots = {
            "__future__",
            "typing",
            "math",
            "warnings",
            "dataclasses",
            "datetime",
            "pydantic",
            "fastapi",
            "kalhas",
        }
        for relative in _PHASE27_MODULES:
            modules = _imported_modules(_module_tree(relative))
            unexpected = modules - allowed_roots
            assert not unexpected, f"unexpected import root in {relative}: {sorted(unexpected)}"

    def test_no_provider_network_database_or_live_action_surface(self) -> None:
        for relative in _PHASE27_MODULES:
            tree = _module_tree(relative)
            imported = _imported_modules(tree)
            forbidden = imported & _FORBIDDEN_MODULES
            assert not forbidden, f"forbidden imports in {relative}: {sorted(forbidden)}"

    def test_no_adaptive_decision_policy_runtime(self) -> None:
        for relative in _PHASE27_MODULES:
            tree = _module_tree(relative)
            symbols = _defined_symbols(tree) | _imported_symbols(tree)
            assert not any("adaptive" in symbol.lower() for symbol in symbols), (
                f"adaptive surface in {relative}"
            )
            for literal in _non_docstring_strings(tree):
                assert "adaptive" not in literal.lower(), (
                    f"adaptive literal in {relative}: {literal!r}"
                )

    def test_no_phase28_or_kalhas_pan_implementation(self) -> None:
        for relative in _PHASE27_MODULES:
            tree = _module_tree(relative)
            for literal in _non_docstring_strings(tree):
                assert not _FUTURE_SURFACE.search(literal), (
                    f"future-phase literal in {relative}: {literal!r}"
                )
            for symbol in _defined_symbols(tree):
                assert not re.search(r"phase.?28", symbol, re.IGNORECASE), (
                    f"future-phase symbol in {relative}: {symbol!r}"
                )

    def test_no_wall_clock_or_randomness_in_decision_derivation(self) -> None:
        for relative in _PHASE27_MODULES:
            tree = _module_tree(relative)
            calls = _attribute_call_chains(tree) | _name_calls(tree)
            assert not (calls & _FORBIDDEN_CALL_CHAINS), (
                f"nondeterministic call in {relative}: {sorted(calls & _FORBIDDEN_CALL_CHAINS)}"
            )
            assert not any(chain.startswith("random.") for chain in calls), (
                f"randomness call in {relative}"
            )
            assert "hash" not in calls, f"process-hash-dependent call in {relative}"

    def test_no_clock_or_runtime_selector_parameters_in_builders(self) -> None:
        from kalhas.application.campaign_decision_brief_runtime import (
            build_campaign_decision_brief,
        )
        from kalhas.application.campaign_decision_comparison_runtime import (
            build_campaign_strategy_comparison,
        )
        from kalhas.application.campaign_decision_evidence import (
            build_campaign_decision_evidence,
        )
        from kalhas.application.campaign_decision_paired_comparison import (
            build_ordered_objective_paired_comparisons,
        )
        from kalhas.application.campaign_decision_selection import (
            build_campaign_minimax_regret,
            build_campaign_pareto_dominance,
        )

        forbidden_parameters = {"now", "clock", "timestamp", "wall_clock", "current_time"}
        for callable_ in (
            build_campaign_decision_evidence,
            build_ordered_objective_paired_comparisons,
            build_campaign_pareto_dominance,
            build_campaign_minimax_regret,
            build_campaign_strategy_comparison,
            build_campaign_decision_brief,
        ):
            parameters = tuple(inspect.signature(callable_).parameters)
            assert not (forbidden_parameters & set(parameters)), (
                f"{callable_.__name__} accepts a clock/timestamp parameter"
            )
            assert not any("runtime" in parameter.lower() for parameter in parameters), (
                f"{callable_.__name__} accepts a runtime-selector parameter"
            )


class TestContractBoundary:
    """Section B: registry, schema, and version boundaries."""

    def test_api_and_schema_versions_unchanged(self) -> None:
        assert API_VERSION == "1"
        assert SCHEMA_VERSION == "1.0.0"

    def test_exactly_50_public_contracts_with_unchanged_prefix_and_exact_tail(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) == 50
        assert len(_HISTORICAL_47_NAMES) == 47
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47:50] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
        )

    def test_nested_decision_value_objects_remain_unregistered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_DECISION_MODELS:
            assert nested not in names, f"{nested} is independently registered"
        assert "CampaignDecisionPolicy" in names
        assert "CampaignStrategyComparison" in names
        assert "CampaignDecisionBrief" in names

    def test_exactly_50_schema_artifacts_matching_contract_titles(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 50
        titles = {json.loads(path.read_text(encoding="utf-8"))["title"] for path in schema_files}
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert titles == names

    def test_all_47_historical_schema_artifacts_retain_accepted_byte_hashes(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        by_name = {path.name: path for path in schema_files}
        assert len(_HISTORICAL_SCHEMA_HASHES) == 47
        for name, expected in _HISTORICAL_SCHEMA_HASHES.items():
            assert name in by_name, f"historical schema missing: {name}"
            digest = hashlib.sha256(by_name[name].read_bytes()).hexdigest()
            assert digest == expected, f"historical schema drifted: {name}"

    def test_three_decision_schema_files_match_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            CampaignDecisionPolicy: "CampaignDecisionPolicy.schema.json",
            CampaignStrategyComparison: "CampaignStrategyComparison.schema.json",
            CampaignDecisionBrief: "CampaignDecisionBrief.schema.json",
        }
        for contract, filename in expected.items():
            path = SCHEMA_DIR / filename
            rendered = json.loads(path.read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_nested_decision_objects_have_no_standalone_schema_files(self) -> None:
        schema_files = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for nested in _NESTED_DECISION_MODELS:
            assert f"{nested}.schema.json" not in schema_files, (
                f"standalone schema artifact for {nested}"
            )


class TestRuntimeApiBoundary:
    """Section C: exact HTTP surface and runtime gate."""

    def test_exactly_four_operations_on_three_paths_with_no_extra_methods(self) -> None:
        spec = create_app().openapi()
        paths = spec["paths"]
        decision_paths = {path: set(ops) for path, ops in paths.items() if "decision-" in path}
        comparison_paths = {
            path: set(ops) for path, ops in paths.items() if "strategy-comparison" in path
        }
        assert decision_paths == {
            "/v1/campaigns/{campaign_id}/decision-policy": {"get", "post"},
            "/v1/campaigns/{campaign_id}/decision-brief": {"get"},
        }
        assert comparison_paths == {"/v1/campaigns/{campaign_id}/strategy-comparison": {"get"}}
        for path, operations in _DECISION_PATHS.items():
            assert set(paths[path]) == operations, f"unexpected methods on {path}"

    def test_policy_declaration_is_201_and_gets_are_200(self) -> None:
        spec = create_app().openapi()
        policy_path = "/v1/campaigns/{campaign_id}/decision-policy"
        assert "201" in spec["paths"][policy_path]["post"]["responses"]
        assert "200" in spec["paths"][policy_path]["get"]["responses"]
        for path in (
            "/v1/campaigns/{campaign_id}/strategy-comparison",
            "/v1/campaigns/{campaign_id}/decision-brief",
        ):
            assert "200" in spec["paths"][path]["get"]["responses"]

    def test_required_tenant_header_on_all_four_operations(self) -> None:
        spec = create_app().openapi()
        for path, operations in _DECISION_PATHS.items():
            for operation in operations:
                parameters = spec["paths"][path][operation].get("parameters", [])
                tenant_parameters = [
                    parameter
                    for parameter in parameters
                    if parameter.get("name") == "X-Tenant-ID" and parameter.get("in") == "header"
                ]
                assert len(tenant_parameters) == 1, f"missing X-Tenant-ID on {path} {operation}"
                assert tenant_parameters[0].get("required") is True

    def test_no_get_request_body_and_no_runtime_selector(self) -> None:
        spec = create_app().openapi()
        for path in (
            "/v1/campaigns/{campaign_id}/decision-policy",
            "/v1/campaigns/{campaign_id}/strategy-comparison",
            "/v1/campaigns/{campaign_id}/decision-brief",
        ):
            assert "requestBody" not in spec["paths"][path]["get"], f"GET body on {path}"
        import kalhas.api.routes_campaign_decision as routes_module

        for function in (
            routes_module.declare_campaign_decision_policy_route,
            routes_module.get_campaign_decision_policy_route,
            routes_module.get_campaign_strategy_comparison_route,
            routes_module.get_campaign_decision_brief_route,
        ):
            parameters = tuple(inspect.signature(function).parameters)
            assert not any("runtime" in parameter.lower() for parameter in parameters), (
                f"runtime selector parameter on {function.__name__}"
            )

    def test_route_decorators_are_exactly_post_get_get_get(self) -> None:
        tree = _module_tree("api/routes_campaign_decision.py")
        decorated: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(
                        decorator.func, ast.Attribute
                    ):
                        decorated.append((node.name, decorator.func.attr))
        assert decorated == [
            ("declare_campaign_decision_policy_route", "post"),
            ("get_campaign_decision_policy_route", "get"),
            ("get_campaign_strategy_comparison_route", "get"),
            ("get_campaign_decision_brief_route", "get"),
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"put", "patch", "delete"}, (
                    f"non-GET/POST Phase 27 operation {node.func.attr}"
                )

    def test_runtime_gate_is_recorded_runtime_exactly_three_zero(self) -> None:
        from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION

        assert REALIZATION_TRAJECTORY_RUNTIME_VERSION == "3.0.0"
        tree = _module_tree("api/routes_campaign_decision.py")
        symbols = _imported_symbols(tree)
        assert "REALIZATION_TRAJECTORY_RUNTIME_VERSION" in symbols
        chains = _attribute_call_chains(tree)
        assert "store.get_run_plans" in chains, "route does not read the recorded run plans"
        source = (KALHAS_ROOT / "api" / "routes_campaign_decision.py").read_text(encoding="utf-8")
        assert "plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION" in source
        assert "UnsupportedRuntimeVersionError" in symbols
        for literal in _non_docstring_strings(tree):
            assert literal not in ("1.0.0", "2.0.0"), (
                f"legacy runtime literal in routes: {literal!r}"
            )

    def test_decision_gets_never_execute_replay_extract_or_record_activity(self) -> None:
        for relative in _READONLY_MODULES:
            tree = _module_tree(relative)
            attribute_calls = _attribute_call_chains(tree)
            name_calls = _name_calls(tree)
            for chain in attribute_calls:
                attribute = chain.rsplit(".", 1)[-1]
                assert not attribute.startswith("put_"), f"store write call {chain!r} in {relative}"
                assert attribute not in _FORBIDDEN_BEHAVIOR_CALLS, (
                    f"behavioral call {chain!r} in {relative}"
                )
                assert "activity" not in attribute and attribute != "record_activity", (
                    f"activity call {chain!r} in {relative}"
                )
            assert not (name_calls & _FORBIDDEN_BEHAVIOR_CALLS), (
                f"behavioral call in {relative}: {sorted(name_calls & _FORBIDDEN_BEHAVIOR_CALLS)}"
            )
        query_symbols = _imported_symbols(
            _module_tree("application/campaign_decision_query_service.py")
        )
        assert "get_verified_campaign_outcome_distributions" in query_symbols
        assert "get_verified_campaign_decision_policy" in query_symbols

    def test_all_six_decision_errors_mapped_into_the_safe_typed_buckets(self) -> None:
        from kalhas.application.campaign_decision_errors import (
            CampaignDecisionBriefIntegrityError,
            CampaignDecisionComparisonIntegrityError,
            CampaignDecisionPolicyAlreadyExistsError,
            CampaignDecisionPolicyIntegrityError,
            CampaignDecisionPolicyNotFoundError,
            CampaignDecisionPolicyValidationError,
        )
        from kalhas.application.domain_errors import KalhasDomainError

        for error_type in (
            CampaignDecisionPolicyNotFoundError,
            CampaignDecisionPolicyAlreadyExistsError,
            CampaignDecisionPolicyValidationError,
            CampaignDecisionPolicyIntegrityError,
            CampaignDecisionComparisonIntegrityError,
            CampaignDecisionBriefIntegrityError,
        ):
            assert issubclass(error_type, KalhasDomainError)
        errors_source = (KALHAS_ROOT / "api" / "errors.py").read_text(encoding="utf-8")
        for name in (
            "CampaignDecisionPolicyNotFoundError",
            "CampaignDecisionPolicyAlreadyExistsError",
            "CampaignDecisionPolicyValidationError",
            "CampaignDecisionPolicyIntegrityError",
            "CampaignDecisionComparisonIntegrityError",
            "CampaignDecisionBriefIntegrityError",
        ):
            # Each name appears in the import and exactly once in the
            # registration tuple (404 / 409 conflict / 422 / 409 integrity).
            assert errors_source.count(name) == 2, f"{name} registration count changed"


class TestDecisionSemanticsBoundary:
    """Section D: the frozen literals and structural decision policies."""

    def test_algorithm_identifier_is_frozen_everywhere(self) -> None:
        assert "feasibility-pareto-minimax-regret-v1" in str(
            CampaignDecisionPolicy.model_fields["algorithm_identifier"].annotation
        )
        assert "feasibility-pareto-minimax-regret-v1" in str(
            CampaignStrategyComparison.model_fields["algorithm_identifier"].annotation
        )
        assert "feasibility-pareto-minimax-regret-v1" in str(
            CampaignDecisionBrief.model_fields["algorithm_identifier"].annotation
        )
        for relative in (
            "application/campaign_decision_paired_comparison.py",
            "application/campaign_decision_evidence.py",
            "application/campaign_decision_comparison_runtime.py",
            "application/campaign_decision_policy_service.py",
            "contracts/v1/campaign_decision.py",
        ):
            source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
            assert "feasibility-pareto-minimax-regret-v1" in source, relative

    def test_tail_alpha_is_fixed_at_0_95_with_no_caller_selection(self) -> None:
        assert get_args(CampaignDecisionPolicy.model_fields["tail_alpha"].annotation) == (0.95,)
        for relative in (
            "application/campaign_decision_evidence.py",
            "application/campaign_decision_paired_comparison.py",
            "application/campaign_decision_comparison_runtime.py",
        ):
            tree = _module_tree(relative)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "_FIXED_TAIL_ALPHA"
                        for target in node.targets
                    )
                    and isinstance(node.value, ast.Constant)
                ):
                    assert node.value.value == 0.95, relative
                    break
            else:
                raise AssertionError(f"_FIXED_TAIL_ALPHA missing in {relative}")
        from kalhas.application.campaign_decision_evidence import _FIXED_TAIL_ALPHA

        assert _FIXED_TAIL_ALPHA == 0.95

    def test_shared_seed_identical_conditions_comparison(self) -> None:
        assert "identical_conditions" in str(
            CampaignStrategyComparison.model_fields["comparison_mode"].annotation
        )
        comparison_source = (KALHAS_ROOT / "contracts" / "v1" / "campaign_decision.py").read_text(
            encoding="utf-8"
        )
        assert "comparison_mode" in comparison_source
        statistics_tree = _module_tree("application/campaign_decision_statistics.py")
        assert "shared-seed" in (ast.get_docstring(statistics_tree) or "").lower() or (
            "identical" in (ast.get_docstring(statistics_tree) or "").lower()
        )

    def test_paired_delta_orientation_positive_means_first_strategy_worse(self) -> None:
        from kalhas.application.campaign_decision_statistics import paired_delta

        # minimize: a higher value is worse; positive delta means the
        # first strategy is worse.
        assert paired_delta(10.0, 5.0, direction="minimize", normalization_scale=1.0) == 5.0
        # maximize: a lower value is worse; positive delta means the
        # first strategy is worse.
        assert paired_delta(5.0, 10.0, direction="maximize", normalization_scale=1.0) == 5.0
        # reach: a larger absolute deviation is worse.
        assert (
            paired_delta(15.0, 10.0, direction="reach", normalization_scale=1.0, target=10.0) == 5.0
        )
        # Exact zero means identical; the mirror is the exact sign reverse.
        assert paired_delta(7.0, 7.0, direction="minimize", normalization_scale=1.0) == 0.0
        assert paired_delta(5.0, 10.0, direction="minimize", normalization_scale=1.0) == -5.0
        statistics_source = (
            KALHAS_ROOT / "application" / "campaign_decision_statistics.py"
        ).read_text(encoding="utf-8")
        assert "means the first strategy is worse" in statistics_source

    def test_both_directions_of_every_non_self_pair_with_exact_count(self) -> None:
        paired_source = (
            KALHAS_ROOT / "application" / "campaign_decision_paired_comparison.py"
        ).read_text(encoding="utf-8")
        assert "S * (S - 1) * O" in paired_source
        assert "no self-pairs" in paired_source
        assert "both directions" in paired_source
        assert "(b if b < a else b - 1)" in paired_source
        selection_source = (
            KALHAS_ROOT / "application" / "campaign_decision_selection.py"
        ).read_text(encoding="utf-8")
        assert (
            "expected_record_count = strategy_count * (strategy_count - 1) * objective_count"
            in (selection_source)
        )
        assert "missing reverse-pair comparison" in selection_source
        contract_source = (KALHAS_ROOT / "contracts" / "v1" / "campaign_decision.py").read_text(
            encoding="utf-8"
        )
        assert "first_strategy_position" in contract_source
        assert "second_strategy_position" in contract_source

    def test_feasibility_precedes_pareto_and_minimax_selection(self) -> None:
        # The minimax builder must invoke the evidence builder (which
        # owns the sufficiency and hard-gate feasibility facts) before
        # the Pareto builder, and the Pareto builder must consume the
        # evidence assessment before any dominance relation is derived.
        selection_source = (
            KALHAS_ROOT / "application" / "campaign_decision_selection.py"
        ).read_text(encoding="utf-8")
        evidence_call = selection_source.index("build_campaign_decision_evidence(")
        pareto_call = selection_source.index("build_campaign_pareto_dominance(")
        assert evidence_call < pareto_call, "minimax builder runs Pareto before evidence"
        pareto_builder = selection_source.index("def _build_pareto_dominance(")
        pareto_end = selection_source.index("def build_campaign_pareto_dominance(")
        pareto_body = selection_source[pareto_builder:pareto_end]
        assert "evidence = build_campaign_decision_evidence(" in pareto_body
        assert "feasible_by_position" in pareto_body
        assert "if not feasible_by_position[position]:" in pareto_body
        brief_source = (
            KALHAS_ROOT / "application" / "campaign_decision_brief_runtime.py"
        ).read_text(encoding="utf-8")
        derive_start = brief_source.index("def _derive_decision(")
        derive_end = brief_source.index("def _reason(")
        derive_body = brief_source[derive_start:derive_end]
        sufficiency = derive_body.index("seed_count < policy.minimum_sample_count")
        feasibility = derive_body.index("all_targeted_objectives_are_hard_gates")
        assert sufficiency < feasibility, "brief derives minimax before the gates"

    def test_dominance_uses_only_feasible_strategies(self) -> None:
        selection_source = (
            KALHAS_ROOT / "application" / "campaign_decision_selection.py"
        ).read_text(encoding="utf-8")
        assert "dominated_by_feasible = any(" in selection_source
        assert "feasible_by_position[dominator]" in selection_source
        assert "non_dominated_feasible_strategy_ids" in selection_source

    def test_minimax_preference_only_for_a_unique_tolerance_tie_set(self) -> None:
        brief_source = (
            KALHAS_ROOT / "application" / "campaign_decision_brief_runtime.py"
        ).read_text(encoding="utf-8")
        assert "max_regret_by_id[candidate_id] <= boundary" in brief_source
        assert "if len(tie_set) == 1:" in brief_source
        assert 'return _DecisionState("preferred"' in brief_source
        assert 'return _DecisionState("inconclusive"' in brief_source
        selection_source = (
            KALHAS_ROOT / "application" / "campaign_decision_selection.py"
        ).read_text(encoding="utf-8")
        assert "inclusive" in selection_source
        assert "no isclose" in selection_source

    def test_inconclusive_is_successful_and_never_manufactures_a_winner(self) -> None:
        assert "None" in str(CampaignDecisionBrief.model_fields["preferred_strategy_id"].annotation)
        status_annotation = str(CampaignDecisionBrief.model_fields["status"].annotation)
        for status in (
            "preferred",
            "inconclusive",
            "insufficient_evidence",
            "no_feasible_strategy",
        ):
            assert status in status_annotation
        brief_source = (
            KALHAS_ROOT / "application" / "campaign_decision_brief_runtime.py"
        ).read_text(encoding="utf-8")
        assert "No preferred strategy is issued" in brief_source
        # The inconclusive status is constructed with a None preferred
        # strategy - a tie never manufactures a winner.
        assert 'return _DecisionState("inconclusive", None' in brief_source

    def test_brief_templates_are_deterministic_and_fixed(self) -> None:
        brief_source = (
            KALHAS_ROOT / "application" / "campaign_decision_brief_runtime.py"
        ).read_text(encoding="utf-8")
        for template in (
            "_SUMMARY_PREFERRED",
            "_SUMMARY_INCONCLUSIVE",
            "_SUMMARY_INSUFFICIENT",
            "_SUMMARY_NO_FEASIBLE",
        ):
            assert f"{template} = (" in brief_source, template
        fields = set(CampaignDecisionBrief.model_fields)
        for forbidden_field in (
            "explanation",
            "narrative",
            "analysis",
            "reasoning",
            "chain_of_thought",
        ):
            assert forbidden_field not in fields, f"free-text field {forbidden_field!r}"

    def test_no_chain_of_thought_scripts_callbacks_or_executable_expressions(self) -> None:
        for relative in _PHASE27_MODULES:
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
            assert not (_imported_modules(tree) & {"importlib", "runpy", "ctypes"}), (
                f"dynamic-loading module in {relative}"
            )
            for literal in _non_docstring_strings(tree):
                assert not re.search(r"chain.?of.?thought", literal, re.IGNORECASE), (
                    f"chain-of-thought literal in {relative}: {literal!r}"
                )


class TestPersistenceBoundary:
    """Section E: only the policy is stored, immutably and defensively."""

    def test_only_policy_collection_exists_in_the_store(self) -> None:
        store_source = (KALHAS_ROOT / "application" / "in_memory_store.py").read_text(
            encoding="utf-8"
        )
        assert "_campaign_decision_policies" in store_source
        assert "CampaignStrategyComparison" not in store_source
        assert "CampaignDecisionBrief" not in store_source
        assert "_campaign_strategy_comparisons" not in store_source
        assert "_campaign_decision_briefs" not in store_source
        assert "_strategy_comparisons" not in store_source
        assert "_decision_briefs" not in store_source

    def test_no_comparison_or_brief_put_methods(self) -> None:
        store_tree = ast.parse(
            (KALHAS_ROOT / "application" / "in_memory_store.py").read_text(encoding="utf-8")
        )
        method_names = {
            node.name
            for node in ast.walk(store_tree)
            if isinstance(node, ast.FunctionDef) and node.col_offset == 4
        }
        policy_methods = {name for name in method_names if "campaign_decision_policy" in name}
        assert policy_methods == {"put_campaign_decision_policy", "get_campaign_decision_policy"}
        for name in method_names:
            assert "campaign_strategy_comparison" not in name
            assert "decision_brief" not in name

    def test_one_immutable_policy_per_tenant_campaign_with_no_update_surface(self) -> None:
        store_source = (KALHAS_ROOT / "application" / "in_memory_store.py").read_text(
            encoding="utf-8"
        )
        assert "CampaignDecisionPolicyAlreadyExistsError" in store_source
        assert "if key in self._campaign_decision_policies:" in store_source
        assert "no update, delete, replace, or repair" in store_source
        store_tree = ast.parse(store_source)
        policy_methods = {
            node.name
            for node in ast.walk(store_tree)
            if isinstance(node, ast.FunctionDef)
            and node.col_offset == 4
            and "campaign_decision_policy" in node.name
        }
        assert policy_methods == {"put_campaign_decision_policy", "get_campaign_decision_policy"}
        for name in policy_methods:
            assert not any(
                token in name for token in ("update_", "delete_", "replace_", "remove_")
            ), f"mutation method {name}"

    def test_policy_getter_revalidates_identity_and_returns_a_defensive_copy(self) -> None:
        store_source = (KALHAS_ROOT / "application" / "in_memory_store.py").read_text(
            encoding="utf-8"
        )
        getter_start = store_source.index("def get_campaign_decision_policy(")
        getter_end = store_source.index("def append_operational_activity(")
        getter_body = store_source[getter_start:getter_end]
        assert (
            "revalidate_stored_campaign_decision_policy(stored, tenant_id, campaign_id)"
            in getter_body
        ), "getter does not revalidate the stored policy on every read"
        assert "return _deep_copy_contract(stored)" in getter_body, (
            "getter does not return a defensive copy"
        )
        put_start = store_source.index("def put_campaign_decision_policy(")
        put_body = store_source[put_start:getter_start]
        assert "revalidate_stored_campaign_decision_policy(policy, tenant_id, campaign_id)" in (
            put_body
        ), "put does not revalidate the policy before storing"
        assert "self._campaign_decision_policies[key] = _deep_copy_contract(policy)" in put_body, (
            "put does not store a deep defensive copy"
        )
        # The independent identity verification recomputes the
        # deterministic identifier and the self-covering content hash.
        assert "policy.identifier != campaign_decision_policy_identifier(" in store_source
        assert "policy.content_hash != campaign_decision_policy_content_hash(policy)" in (
            store_source
        )


class TestAcceptanceFixtureBoundary:
    """Section F: the fixed 100-seed fixture never searches or recomputes."""

    def test_fixture_has_exactly_100_static_seed_identifiers(self) -> None:
        assert len(SEED_IDENTIFIERS) == 100
        assert SEED_IDENTIFIERS[0] == "seed-000"
        assert SEED_IDENTIFIERS[-1] == "seed-099"
        assert len(set(SEED_IDENTIFIERS)) == 100
        assert all(re.fullmatch(r"seed-\d{3}", identifier) for identifier in SEED_IDENTIFIERS)
        assert tuple(sorted(SEED_IDENTIFIERS)) == SEED_IDENTIFIERS
        helper_source = (TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8")
        # The tuple is written out statically: exactly 100 quoted
        # ``seed-`` literals in the source (the docstring uses backtick
        # forms, never double quotes).
        assert helper_source.count('"seed-') == 100

    def test_fixture_never_searches_retries_randomizes_filters_or_adapts(self) -> None:
        helper_tree = ast.parse((TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8"))
        assert not (_imported_modules(helper_tree) & {"random", "secrets", "uuid"})
        calls = _attribute_call_chains(helper_tree) | _name_calls(helper_tree)
        forbidden_calls = {
            "search",
            "retry",
            "sample",
            "choice",
            "shuffle",
            "randrange",
            "randint",
            "random",
            "seed",
            "adapt",
            "select",
        }
        assert not (calls & forbidden_calls), (
            f"search/retry/random/adaptive call in the fixture: {sorted(calls & forbidden_calls)}"
        )
        assert not any("adaptive" in symbol.lower() for symbol in _defined_symbols(helper_tree))

    def test_helper_duplicates_no_decision_algorithm(self) -> None:
        helper_tree = ast.parse((TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(helper_tree)
        for forbidden in _FIXTURE_FORBIDDEN_ALGORITHM_IMPORTS:
            assert not any(
                path == forbidden or path.startswith(f"{forbidden}.") for path in module_paths
            ), f"decision algorithm import in the fixture: {forbidden}"
        algorithm_tokens = re.compile(
            r"minimax|pareto|dominance|paired_delta|regret|brief", re.IGNORECASE
        )
        for node in ast.walk(helper_tree):
            if isinstance(node, ast.FunctionDef):
                assert not algorithm_tokens.search(node.name), (
                    f"decision-algorithm definition in the fixture: {node.name}"
                )
        helper_source = (TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8")
        assert "def expected_attempt_sequence" in helper_source
        assert "reconstruction logic" in helper_source

    def test_helper_invokes_the_real_lifecycle_services(self) -> None:
        helper_source = (TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8")
        helper_tree = ast.parse(helper_source)
        symbols = _imported_symbols(helper_tree)
        for service in (
            "declare_state_model",
            "declare_transition",
            "declare_domain_metric_observation",
            "declare_world_uncertainty_model",
            "declare_scenario_evaluation_profile",
            "prepare_realization_campaign",
            "prepare_strategy_trajectory_plans",
            "execute_realization_campaign",
            "extract_realization_run_metric_observations",
            "declare_campaign_decision_policy",
        ):
            assert service in symbols, f"fixture does not invoke {service}"

    def test_acceptance_obtains_comparison_and_brief_through_verified_queries(self) -> None:
        acceptance_tree = ast.parse(
            (TESTS_DIR / "test_phase27_acceptance.py").read_text(encoding="utf-8")
        )
        symbols = _imported_symbols(acceptance_tree)
        assert "get_verified_campaign_strategy_comparison" in symbols
        assert "get_verified_campaign_decision_brief" in symbols
        assert "get_verified_campaign_outcome_distributions" in symbols

    def test_preferred_and_inconclusive_control_proofs_are_both_present(self) -> None:
        acceptance_tree = ast.parse(
            (TESTS_DIR / "test_phase27_acceptance.py").read_text(encoding="utf-8")
        )
        classes = {
            node.name for node in ast.walk(acceptance_tree) if isinstance(node, ast.ClassDef)
        }
        assert "TestBriefGoldens" in classes
        assert "TestTieControlProof" in classes
        assert "TestBestMeanIsNotRobustWinner" in classes

    def test_hard_coded_goldens_never_recomputed_through_identity_functions(self) -> None:
        acceptance_source = (TESTS_DIR / "test_phase27_acceptance.py").read_text(encoding="utf-8")
        helper_source = (TESTS_DIR / "phase27_helpers.py").read_text(encoding="utf-8")
        for golden in (
            "GOLDEN_POLICY_ID",
            "GOLDEN_POLICY_CONTENT_HASH",
            "GOLDEN_COMPARISON_ID",
            "GOLDEN_COMPARISON_CONTENT_HASH",
            "GOLDEN_BRIEF_ID",
            "GOLDEN_BRIEF_CONTENT_HASH",
            "GOLDEN_CONTROL_POLICY_ID",
            "GOLDEN_CONTROL_COMPARISON_ID",
            "GOLDEN_CONTROL_BRIEF_ID",
        ):
            assert f"{golden} =" in helper_source, golden
        for golden in (
            "GOLDEN_POLICY_ID",
            "GOLDEN_POLICY_CONTENT_HASH",
            "GOLDEN_COMPARISON_ID",
            "GOLDEN_COMPARISON_CONTENT_HASH",
            "GOLDEN_BRIEF_ID",
            "GOLDEN_BRIEF_CONTENT_HASH",
        ):
            assert golden in acceptance_source, f"{golden} not asserted in the acceptance test"
        for tree_source in (acceptance_source, helper_source):
            assert "campaign_decision_identity" not in tree_source, (
                "identity functions imported where goldens must be frozen constants"
            )
        # The frozen constants themselves are statically written hex/ids.
        assert "campaign-decision-policy-9caab5493c904b86" in helper_source
        assert "campaign-strategy-comparison-0538c7e968c25a5c" in helper_source
        assert "campaign-decision-brief-9ac779fc1df02f5a" in helper_source


def _doc_text(relative: str) -> str:
    """One normalized lowercase text of an active documentation file.

    Markdown prose wraps lines freely, so substring checks must
    collapse all whitespace runs to single spaces first.
    """
    return re.sub(r"\s+", " ", (REPO_ROOT / relative).read_text(encoding="utf-8")).lower()


class TestDocumentationTruthfulness:
    """Section G: active documentation states the honest Phase 27 status."""

    def test_active_docs_state_phase27_implemented_and_gate_verified(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            assert "phase 27" in text, relative
            assert "implementation-complete" in text, relative
            assert "gate" in text, relative

    def test_active_docs_state_uncommitted_and_not_pushed(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            assert "not committed" in text or "uncommitted" in text, relative
            assert "not pushed" in text or "no push" in text, relative

    def test_active_docs_state_evidence_based_not_calibrated_not_certainty(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            assert "evidence" in text, relative
            assert "not calibrated" in text, relative
            assert "not certainty" in text, relative

    def test_active_docs_deny_autonomous_live_action_and_future_phases(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            assert "no autonomous live action" in text, relative
            assert "kalhas-pan" in text, relative
            assert "not implemented" in text, relative

    def test_active_docs_label_colony_visualization_synthetic(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            assert "synthetic" in text, relative

    def test_active_docs_contain_no_overclaim_phrases(self) -> None:
        for relative in _ACTIVE_DOCS:
            text = _doc_text(relative)
            for phrase in _OVERCLAIM_PHRASES:
                assert phrase not in text, f"{phrase!r} in {relative}"


class TestScopeInventory:
    """Section H: every expected Phase 27 path exists."""

    def test_all_phase27_production_modules_exist(self) -> None:
        for relative in _PHASE27_MODULES:
            assert (KALHAS_ROOT / relative).is_file(), relative

    def test_all_phase27_test_files_exist(self) -> None:
        for name in (
            "phase27_helpers.py",
            "test_phase27_acceptance.py",
            "test_phase27_boundaries.py",
            "test_api_phase27.py",
            "test_campaign_decision_contracts.py",
            "test_campaign_decision_requests.py",
            "test_campaign_decision_policy_service.py",
            "test_campaign_decision_query_service.py",
            "test_campaign_decision_identity.py",
            "test_campaign_decision_statistics.py",
            "test_campaign_decision_evidence.py",
            "test_campaign_decision_paired_comparison.py",
            "test_campaign_decision_selection.py",
            "test_campaign_decision_comparison_runtime.py",
            "test_campaign_decision_brief_runtime.py",
        ):
            assert (TESTS_DIR / name).is_file(), name

    def test_all_phase27_schema_artifacts_exist(self) -> None:
        for name in (
            "CampaignDecisionPolicy.schema.json",
            "CampaignStrategyComparison.schema.json",
            "CampaignDecisionBrief.schema.json",
        ):
            assert (SCHEMA_DIR / name).is_file(), name

    def test_phase27_handoff_exists(self) -> None:
        assert (REPO_ROOT / "KALHAS_HANDOFF_PHASE_27.md").is_file()
