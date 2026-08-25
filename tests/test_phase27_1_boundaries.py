"""Gate 27.1 closure boundary proofs (S04): permanent, lightweight enforcement.

This module permanently encodes the already-audited Gate 27.1 closure as
deterministic structural boundary tests. It adds no production behavior,
no campaign execution, no fixture rebuild, and no heavy acceptance run:
every test is a static import, AST, or source-structure proof over the
frozen Gate 27.1 artifacts and the live production package.

The audited S03 state that these boundaries protect:

- the unmodified production cardinality invariant
  ``EXPECTED_STRATEGY_SET_SIZE == 5`` accepted the real
  ``MockLegionAdapter`` candidate set without any patch;
- ``tests/phase27_1_helpers.py`` and
  ``tests/test_phase27_1_exact_five_acceptance.py`` are frozen reference
  fixtures: exact five-candidate order, four shared seeds, five distinct
  declared plans, and no manufacturing machinery.

Proved here:

- production cardinality stays real (live constant equals 5);
- the frozen reference fixture remains exact (candidates, seeds,
  declared mappings, pairwise-distinct sequences);
- AST anti-manufacturing structure over both frozen files: no
  ``unittest.mock`` import, no monkeypatch fixture or parameter, no
  patch/mock invocation, no assignment to the cardinality constant, no
  redefinition of ``request_strategies``, no ``MockLegionAdapter``
  subclassing, and no direct persistence of executions, observation
  sets, comparisons, decision briefs, and manufactured outcomes - while
  truthful explanatory docstrings naming those non-goals stay legal
  (AST structure, never naive substring scans);
- shared detector controls: one reusable derived-evidence detector
  (``_direct_derived_persistence_violations``) enforces the
  no-direct-persistence boundary on both frozen files and is proven by
  explicit positive and negative synthetic detector-control tests;
- architecture boundaries: production modules under ``kalhas/`` never
  import the test-only Gate 27.1 helpers, the helpers stay outside the
  production package, and the only architecture roles remain NEXUS,
  LEGION, and KALHAS;
- skip/xfail closure: the corrected AGENTS.md architecture-guidance
  boundary test in ``tests/test_boundaries.py`` exists undecorated and
  unconditionally implemented, and neither frozen Gate 27.1 file
  contains executable skip/xfail markers;
- historical Phase 27 boundary/acceptance proofs remain present with
  their full original assertion surface.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
TESTS_DIR = REPO_ROOT / "tests"

#: The two frozen Gate 27.1 files whose hashes were fixed by the audit.
FROZEN_HELPER_PATH = TESTS_DIR / "phase27_1_helpers.py"
FROZEN_ACCEPTANCE_PATH = TESTS_DIR / "test_phase27_1_exact_five_acceptance.py"
#: Both frozen Gate 27.1 files, as one scan target.
FROZEN_GATE_PATHS: tuple[Path, ...] = (FROZEN_HELPER_PATH, FROZEN_ACCEPTANCE_PATH)

#: The corrected architecture-guidance boundary test (H27.1-S02) that
#: must remain present, undecorated, and unconditionally implemented.
CORRECTED_BOUNDARY_TEST_NAME = "test_agents_md_contains_corrected_architecture_guidance"

#: Historical Phase 27 boundary classes whose assertions must survive.
HISTORICAL_PHASE27_BOUNDARY_CLASSES: tuple[str, ...] = (
    "TestDomainNeutralKernel",
    "TestContractBoundary",
    "TestRuntimeApiBoundary",
    "TestDecisionSemanticsBoundary",
    "TestPersistenceBoundary",
    "TestAcceptanceFixtureBoundary",
    "TestDocumentationTruthfulness",
    "TestScopeInventory",
)

#: Historical acceptance control classes that must remain present.
HISTORICAL_PHASE27_ACCEPTANCE_CLASSES: tuple[str, ...] = (
    "TestBriefGoldens",
    "TestTieControlProof",
    "TestBestMeanIsNotRobustWinner",
)

#: Minimum historical test-function counts at the audited baseline.
#: These are floors against silent weakening; they are not maximums.
HISTORICAL_TEST_COUNT_FLOORS: dict[str, int] = {
    "test_boundaries.py": 17,
    "test_phase27_boundaries.py": 55,
    "phase27_helpers.py": 0,
    "test_phase27_acceptance.py": 15,
    "phase27_1_helpers.py": 0,
    "test_phase27_1_exact_five_acceptance.py": 35,
}

#: Minimum historical assertion-node counts at the audited baseline
#: (57 in ``test_boundaries.py`` and 184 in ``test_phase27_boundaries.py``
#: at the audited Gate 27.1 S03 state).
HISTORICAL_ASSERT_COUNT_FLOORS: dict[str, int] = {
    "test_boundaries.py": 57,
    "test_phase27_boundaries.py": 184,
}

#: Store collections that would hold directly persisted derived records.
_PERSISTENCE_COLLECTION_TOKENS: frozenset[str] = frozenset(
    {
        "_run_trajectory_executions",
        "_realization_run_trajectory_executions",
        "_run_metric_observation_sets",
        "_realization_run_metric_observation_sets",
        "_campaign_strategy_comparisons",
        "_strategy_comparisons",
        "_campaign_decision_briefs",
        "_decision_briefs",
        "_campaign_outcomes",
        "_realization_campaign_outcomes",
    }
)

#: Derived record types whose direct persistence is forbidden.
_DERIVED_RECORD_TYPE_TOKENS: frozenset[str] = frozenset(
    {
        "RunTrajectoryExecution",
        "RealizationRunTrajectoryExecution",
        "RunMetricObservationSet",
        "RealizationRunMetricObservationSet",
        "CampaignMetricObservationMatrix",
        "RealizationCampaignMetricObservationMatrix",
        "CampaignOutcomeDistributionMatrix",
        "CampaignStrategyComparison",
        "CampaignDecisionBrief",
    }
)

#: Attribute names that would write an execution or observation set.
_EXECUTION_OBSERVATION_PUT_NAMES: frozenset[str] = frozenset(
    {
        "put_realization_run_trajectory_execution",
        "put_run_trajectory_execution",
        "put_realization_run_metric_observation_set",
        "put_run_metric_observation_set",
    }
)


def _module_tree(path: Path) -> ast.Module:
    """Parse one source file into its AST."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _code_without_docstrings(text: str) -> str:
    """Source text with module-level triple-double-quoted docstrings removed.

    Mirrors the established repository pattern (``split('\"\"\"')[::2]``)
    so truthful explanatory prose naming forbidden tokens cannot
    false-positive a raw scan.
    """
    return "".join(text.split('"""')[::2])


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted paths of every absolute import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            paths.add(node.module)
    return paths


def _imported_bound_names(tree: ast.Module) -> set[str]:
    """Every local name bound by an import statement."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _defined_function_names(tree: ast.Module) -> set[str]:
    """Every function or method definition name in a module."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _parameter_names(tree: ast.Module) -> set[str]:
    """Every parameter name of every function definition."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = node.args
        positional = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        for argument in positional:
            names.add(argument.arg)
        if arguments.vararg is not None:
            names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            names.add(arguments.kwarg.arg)
    return names


def _assigned_name_targets(tree: ast.Module) -> dict[str, list[ast.expr]]:
    """Assigned name targets mapped to their assigned value expressions.

    Covers plain, annotated, augmented, and named-expression targets so
    any write to a forbidden name is visible structurally.
    """
    targets: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        values: tuple[ast.expr, ...]
        if isinstance(node, ast.Assign):
            values = (node.value,)
            named = [target for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign):
            values = (node.value,) if node.value is not None else ()
            named = [node.target] if isinstance(node.target, ast.Name) else []
        elif isinstance(node, ast.AugAssign):
            sentinel = ast.Constant(value="<augmented-assignment>")
            values = (sentinel,)
            named = [node.target] if isinstance(node.target, ast.Name) else []
        elif isinstance(node, ast.NamedExpr):
            values = (node.value,)
            named = [node.target] if isinstance(node.target, ast.Name) else []
        else:
            continue
        for target in named:
            targets.setdefault(target.id, []).extend(values)
    return targets


def _call_name_and_chains(tree: ast.Module) -> set[str]:
    """Bare names and dotted chains of every call site."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
            calls.add(target.id)
        if parts:
            calls.add(".".join(reversed(parts)))
    return calls


def _attribute_call_names(tree: ast.Module) -> set[str]:
    """Attribute names invoked at every attribute call site."""
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _class_base_roots(tree: ast.Module) -> list[tuple[str, str]]:
    """(class name, rendered base expression) pairs with textual bases."""
    bases: list[tuple[str, str]] = []

    def _render(expression: ast.expr) -> str:
        if isinstance(expression, ast.Name):
            return expression.id
        if isinstance(expression, ast.Attribute):
            prefix = _render(expression.value)
            return f"{prefix}.{expression.attr}" if prefix else expression.attr
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                rendered = _render(base)
                if rendered:
                    bases.append((node.name, rendered))
    return bases


def _expression_root(expression: ast.expr | ast.Attribute | ast.Name) -> str:
    """Leftmost identifier of an attribute chain (``a.b.c`` -> ``a``)."""
    while isinstance(expression, ast.Attribute):
        expression = expression.value
    if isinstance(expression, ast.Name):
        return expression.id
    return ""


def _render_expression_name(expression: ast.expr) -> str:
    """Dotted rendering of Name/Attribute chains (``a.b.C``); else ``""``."""
    parts: list[str] = []
    node: ast.expr = expression
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _root_token(dotted_name: str) -> str:
    """Final identifier of a dotted rendering (``a.B`` -> ``B``)."""
    return dotted_name.rsplit(".", 1)[-1]


def _decorator_text(decorator: ast.expr) -> str:
    """Best-effort dotted rendering of one decorator expression."""
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        prefix = _expression_root(decorator.value)
        return f"{prefix}.{decorator.attr}" if prefix else decorator.attr
    if isinstance(decorator, ast.Call):
        return _decorator_text(decorator.func)
    return ""


# ---------------------------------------------------------------------------
# Section 1: production cardinality remains real and unmodified
# ---------------------------------------------------------------------------


def test_production_cardinality_constant_is_imported_live_and_equals_five() -> None:
    """The real production invariant is imported from the live module."""
    from kalhas.application.campaign_service import EXPECTED_STRATEGY_SET_SIZE

    assert EXPECTED_STRATEGY_SET_SIZE == 5


def test_production_cardinality_is_a_plain_int_module_binding() -> None:
    """The constant stays a plain module-level integer binding."""
    import kalhas.application.campaign_service as campaign_service_module

    recorded = campaign_service_module.__dict__.get("EXPECTED_STRATEGY_SET_SIZE")
    assert type(recorded) is int
    assert recorded == 5


def test_preparation_enforces_the_cardinality_against_the_live_constant() -> None:
    """Preparation compares the returned set length to the live constant."""
    tree = _module_tree(KALHAS_ROOT / "application" / "campaign_service.py")
    enforced = any(
        isinstance(node, ast.Compare)
        and isinstance(node.ops[0], ast.NotEq)
        and isinstance(node.left, ast.Call)
        and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "len"
        and any(
            isinstance(comparator, ast.Name) and comparator.id == "EXPECTED_STRATEGY_SET_SIZE"
            for comparator in node.comparators
        )
        for node in ast.walk(tree)
    )
    assert enforced, "preparation no longer enforces EXPECTED_STRATEGY_SET_SIZE"


# ---------------------------------------------------------------------------
# Section 2: the frozen reference fixture remains exact
# ---------------------------------------------------------------------------


def test_frozen_candidate_order_is_exactly_the_five_reference_strategies() -> None:
    from tests.phase27_1_helpers import STRATEGIES

    assert STRATEGIES == (
        "mock-baseline",
        "mock-conservative",
        "mock-balanced",
        "mock-adaptive",
        "mock-diversified",
    )


def test_frozen_seed_order_is_exactly_the_four_shared_seeds() -> None:
    from tests.phase27_1_helpers import SEED_IDENTIFIERS

    assert SEED_IDENTIFIERS == ("seed-000", "seed-001", "seed-003", "seed-004")


def test_frozen_strategy_plans_mappings_are_exact() -> None:
    from tests.phase27_1_helpers import STRATEGIES, STRATEGY_PLANS

    assert STRATEGY_PLANS == {
        "mock-baseline": ("t-z", "t-z2", "t-v", "t-u"),
        "mock-conservative": ("t-x", "t-w", "t-y", "t-u"),
        "mock-balanced": ("t-x", "t-u", "t-y"),
        "mock-adaptive": ("t-x", "t-v", "t-y", "t-u"),
        "mock-diversified": ("t-z", "t-y", "t-w", "t-u"),
    }
    assert set(STRATEGY_PLANS) == set(STRATEGIES)


def test_all_five_declared_sequences_are_pairwise_distinct() -> None:
    from tests.phase27_1_helpers import STRATEGIES, STRATEGY_PLANS

    sequences = {strategy_id: STRATEGY_PLANS[strategy_id] for strategy_id in STRATEGIES}
    assert len(set(sequences.values())) == len(STRATEGIES) == 5


def test_frozen_helper_builds_only_the_real_adapter() -> None:
    """The helper constructs the real adapter - no subclass, no override."""
    tree = _module_tree(FROZEN_HELPER_PATH)

    class_bases = _class_base_roots(tree)
    assert class_bases == [], f"frozen helper defines a subclass: {class_bases}"

    definitions = _defined_function_names(tree)
    assert "request_strategies" not in definitions

    assignments = _assigned_name_targets(tree)
    assert "request_strategies" not in assignments

    calls = _call_name_and_chains(tree)
    assert "request_strategies" not in calls


# ---------------------------------------------------------------------------
# Section 3: AST anti-manufacturing proofs over the frozen files
# ---------------------------------------------------------------------------


def test_frozen_files_import_no_unittest_mock_or_mock_module() -> None:
    """No ``unittest.mock``/``mock`` import exists in either frozen file."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        offenders: list[tuple[int, str]] = []
        bound_mock_names: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "mock" or alias.name.startswith("unittest.mock"):
                        offenders.append((alias.lineno, alias.name))
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound == "mock":
                        bound_mock_names.append((alias.lineno, bound))
            elif isinstance(node, ast.ImportFrom):
                origin = ".".join(["." * node.level, node.module or ""])
                stripped_origin = node.module or ""
                if stripped_origin.startswith(("unittest.mock", "mock")) or (
                    stripped_origin in {"unittest"} and not node.level
                ):
                    offenders.append((node.lineno, origin))
        assert not offenders, f"mock import in {path.name}: {offenders}"
        assert not bound_mock_names, f"'mock' bound as a name in {path.name}"
        assert "patch" not in _imported_bound_names(tree), f"'patch' imported in {path.name}"


def test_frozen_files_have_no_monkeypatch_fixture_parameter_or_definition() -> None:
    """No monkeypatch anywhere except truthful docstring prose."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)

        parameters = _parameter_names(tree)
        assert "monkeypatch" not in parameters, f"monkeypatch parameter in {path.name}"

        decorators: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    rendered = _decorator_text(decorator)
                    if "monkeypatch" in rendered.lower():
                        decorators.append((node.lineno, rendered))
        assert not decorators, f"monkeypatch decorator in {path.name}: {decorators}"

        definitions = _defined_function_names(tree)
        assert not any("monkeypatch" in name.lower() for name in definitions), (
            f"monkeypatch definition in {path.name}"
        )

        assignments = _assigned_name_targets(tree)
        assert not any("monkeypatch" in name.lower() for name in assignments), (
            f"monkeypatch assignment in {path.name}"
        )


def test_frozen_files_invoke_no_patch_mock_or_patcher_surface() -> None:
    """No patch/mock call chains exist outside docstring prose."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        calls = _call_name_and_chains(tree)
        attribute_calls = _attribute_call_names(tree)
        forbidden_calls = {
            "patch",
            "patch.object",
            "MagicMock",
            "Mock",
            "monkeypatch.setattr",
            "monkeypatch.delattr",
            "monkeypatch.chdir",
        }
        hits = calls & forbidden_calls
        assert not hits, f"patch/mock invocation in {path.name}: {sorted(hits)}"
        assert "setattr" not in attribute_calls, f"setattr call in {path.name}"
        assert "delattr" not in attribute_calls, f"delattr call in {path.name}"

        patcher_starts = [
            chain
            for chain in calls
            if chain.endswith(".start") and _chain_prefix_is_patch_like(chain)
        ]
        assert not patcher_starts, f"patcher start call in {path.name}: {patcher_starts}"


def _chain_prefix_is_patch_like(chain: str) -> bool:
    """True when a dotted call chain ends in a mock-patcher start."""
    lowered = chain.lower()
    return any(token in lowered for token in ("patch", "mock", "monkeypatch"))


def test_frozen_files_never_assign_or_mutate_expected_strategy_set_size() -> None:
    """The production constant is only ever imported and read."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        assignments = _assigned_name_targets(tree)
        hits = assignments.get("EXPECTED_STRATEGY_SET_SIZE")
        assert not hits, f"EXPECTED_STRATEGY_SET_SIZE assigned in {path.name}"
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "EXPECTED_STRATEGY_SET_SIZE"
                and isinstance(node.ctx, ast.Store)
            ):
                raise AssertionError(f"EXPECTED_STRATEGY_SET_SIZE mutated in {path.name}")


def test_frozen_files_define_no_request_strategies_function_or_method() -> None:
    """The LEGION boundary method is never redefined in the frozen files."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        definitions = _defined_function_names(tree)
        assert "request_strategies" not in definitions, f"request_strategies defined in {path.name}"


def test_frozen_files_subclass_no_legion_adapter() -> None:
    """No class definition exists that inherits any adapter."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        offenders = [
            (class_name, base)
            for class_name, base in _class_base_roots(tree)
            if "MockLegionAdapter" in base or "LegionAdapter" in base
        ]
        assert not offenders, f"adapter subclassing in {path.name}: {offenders}"
    helper_classes = [
        node.name
        for node in _module_tree(FROZEN_HELPER_PATH).body
        if isinstance(node, ast.ClassDef)
    ]
    assert helper_classes == [], f"frozen helper defines classes: {helper_classes}"


_DIRECT_COLLECTION_MUTATION_CALLS: frozenset[str] = frozenset(
    {
        "update",
        "setdefault",
        "append",
        "extend",
        "insert",
        "__setitem__",
        "clear",
        "pop",
        "popitem",
    }
)


def _direct_derived_persistence_violations(tree: ast.Module) -> list[str]:
    """Every direct derived-evidence persistence/mutation site in one AST.

    The single real detector behind both the frozen-file closure
    assertion and the synthetic positive/negative detector controls.
    Reports, with stable ``line:description`` strings:

    - a call to a known execution/observation writer (``put_*``), or any
      persistence-shaped call whose positional or keyword argument is an
      ast.Name / ast.Attribute / constructor ast.Call of a derived
      evidence type;
    - raw writes to forbidden store collections through any Assign
      target (subscript assignment on every target, whole-collection
      replacement), AnnAssign, AugAssign, and direct collection
      mutation calls such as update/setdefault/append/extend/insert/
      __setitem__.
    """
    violations: list[str] = []

    def _record(line: int, description: str) -> None:
        violations.append(f"line {line}: {description}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                continue
            attribute = node.func.attr
            receiver = _render_expression_name(node.func.value)
            receiver_root = _expression_root(node.func.value)
            if attribute in _EXECUTION_OBSERVATION_PUT_NAMES:
                _record(
                    node.lineno,
                    f"direct execution/observation writer call: {receiver}.{attribute}",
                )
                continue
            if (
                attribute.startswith(("put_", "record_", "save_", "persist_", "inject_"))
                or attribute in _DIRECT_COLLECTION_MUTATION_CALLS
            ) and (
                receiver_root == "store"
                or receiver in _PERSISTENCE_COLLECTION_TOKENS
                or _root_token(receiver) in _PERSISTENCE_COLLECTION_TOKENS
            ):
                for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                    rendered = _render_expression_name(argument)
                    if _root_token(rendered) in _DERIVED_RECORD_TYPE_TOKENS:
                        _record(
                            node.lineno,
                            f"derived record passed to persistence: {attribute}({rendered})",
                        )
                    elif isinstance(argument, ast.Call):
                        constructor = _render_expression_name(argument.func)
                        if _root_token(constructor) in _DERIVED_RECORD_TYPE_TOKENS:
                            _record(
                                node.lineno,
                                f"constructed derived record passed directly to {attribute}(...)",
                            )
                if attribute in _DIRECT_COLLECTION_MUTATION_CALLS and (
                    receiver in _PERSISTENCE_COLLECTION_TOKENS
                    or _root_token(receiver) in _PERSISTENCE_COLLECTION_TOKENS
                ):
                    _record(
                        node.lineno,
                        f"raw mutation call on forbidden collection: {receiver}.{attribute}",
                    )
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets: tuple[ast.expr, ...] = (
                tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)
            )
            kind: str | None = None
            for target in targets:
                if isinstance(target, ast.Subscript) or (
                    isinstance(target, ast.Attribute) and not isinstance(target.ctx, ast.Load)
                ):
                    base = target.value if isinstance(target, ast.Subscript) else target
                    receiver = _render_expression_name(base)
                    receiver_root = _expression_root(base)
                    collection_matched = (
                        receiver_root == "store"
                        or receiver in _PERSISTENCE_COLLECTION_TOKENS
                        or _root_token(receiver) in _PERSISTENCE_COLLECTION_TOKENS
                    )
                    if collection_matched and kind is None:
                        kind = {
                            ast.Assign: "subscript/assignment",
                            ast.AnnAssign: "annotated",
                            ast.AugAssign: "augmented",
                        }[type(node)]
                        _record(
                            node.lineno,
                            f"raw write into derived collection: {kind}",
                        )
            continue

    return violations


def test_frozen_files_persist_no_executions_observation_sets_or_derived_records() -> None:
    """No direct persistence/injection of derived records into the store.

    The frozen files legitimately READ stored executions and observation
    sets through getters and CALL the real extraction/replay services;
    what must never exist is direct persistence. This closure assertion
    runs the exact detector proven by the synthetic detector-control
    tests below - no separate weaker logic exists for the real files.
    """
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        violations = _direct_derived_persistence_violations(tree)
        assert not violations, f"derived-persistence violation in {path.name}: {violations}"


def test_detector_reports_synthetic_direct_derived_persistence_violations() -> None:
    """Positive controls: the real detector flags every manufactured form.

    Each snippet is parsed and run through the exact detector used by
    the frozen-file closure assertion above. The manufactured evidence
    contract types are the required execution/observation/comparison/
    brief/outcome set; the writer and raw-collection forms cover
    positional names, constructor calls, keyword arguments, subscript
    assignment, mutation calls, and __setitem__.
    """
    synthetic_sources: tuple[str, ...] = (
        "store.put_run_trajectory_execution(execution)",
        "store.put_realization_run_trajectory_execution(execution)",
        "service.put_run_metric_observation_set(observation_set)",
        "store.put_realization_run_metric_observation_set(observation_set)",
        "store.put_campaign_decision_brief(CampaignDecisionBrief(...))",
        (
            "store.put_campaign_strategy_comparison(\n"
            "    CampaignStrategyComparison(\n"
            "        ...\n"
            "    )\n"
            ")"
        ),
        "store.put_campaign_outcome(CampaignOutcomeDistributionMatrix(...))",
        "store.put_campaign_outcome(matrix=CampaignMetricObservationMatrix(...))",
        "store.put_campaign_outcome(RealizationCampaignMetricObservationMatrix(...))",
        "store.put_run_trajectory_execution(module.RunTrajectoryExecution(...))",
        "store.put_campaign_decision_brief(brief=CampaignDecisionBrief(...))",
        "store._campaign_decision_briefs[key] = brief",
        "store._campaign_outcomes.update({key: outcome})",
        "store._realization_run_trajectory_executions.__setitem__(key, execution)",
        "store._campaign_decision_briefs.setdefault(key, brief)",
        "self._run_trajectory_executions.append(execution)",
        "store._run_metric_observation_sets.extend(more_sets)",
        "store._strategy_comparisons.insert(0, comparison)",
        "store._campaign_outcomes = {}",
        "store._realization_run_metric_observation_sets: dict[str, object] = {}",
        "store._campaign_strategy_comparisons[key] += 1",
        "store._decision_briefs.clear()",
    )
    for source in synthetic_sources:
        tree = ast.parse(source)
        violations = _direct_derived_persistence_violations(tree)
        assert violations, f"detector missed a manufactured violation: {source!r}"


def test_detector_accepts_legal_read_and_real_service_paths() -> None:
    """Negative controls: legal reads and real-service calls stay legal.

    The same real detector must reject none of these representative
    legal forms: getter reads of executions/observation sets, verified
    read-only extraction/query services, replay through the real
    service, plain local-list mutation, and a non-store receiver.
    """
    synthetic_sources: tuple[str, ...] = (
        "store.get_realization_run_trajectory_execution(tenant, campaign, run)",
        "store.get_realization_run_metric_observation_set(tenant, campaign, run)",
        "extract_realization_run_metric_observations(store, tenant, campaign)",
        "get_verified_campaign_strategy_comparison(store, tenant, campaign)",
        "get_verified_campaign_decision_brief(store, tenant, campaign)",
        "replay_realization_run(store, tenant, campaign, run)",
        "attempts.append((attempt.transition_id, attempt.outcome))",
        "found.append(name)",
        "sequences.add(logical)",
        "observed_probabilities.append(record.observed_probability)",
        "dominating_pairs.add((left, right))",
        "payload.update({key: value})",
        "cache.setdefault(key, [])",
        "rows.insert(0, row)",
        "values.extend(extra_values)",
        "mapping[key] = value",
        "counter[key] += 1",
        "snapshot: dict[str, int] = {}",
        "helper.put_scenario(scenario)",
        "builder.put_campaign_outcome(outcome)",
    )
    for source in synthetic_sources:
        tree = ast.parse(source)
        violations = _direct_derived_persistence_violations(tree)
        assert not violations, f"detector rejected a legal path: {source!r} -> {violations}"


# ---------------------------------------------------------------------------
# Section 4: architecture-boundary proofs
# ---------------------------------------------------------------------------

_FORBIDDEN_PRODUCTION_IMPORT_HEADS = frozenset({"tests"})
_FORBIDDEN_PRODUCTION_TAILS = (
    "phase27_1_helpers",
    "test_phase27_1_exact_five_acceptance",
    "test_phase27_1_boundaries",
)


def test_production_modules_never_import_gate27_test_helpers() -> None:
    """No ``kalhas/`` module imports any Gate 27.1 test helper."""
    offenders: list[tuple[str, str]] = []
    for py_file in sorted(KALHAS_ROOT.rglob("*.py")):
        tree = _module_tree(py_file)
        relative = str(py_file.relative_to(REPO_ROOT))
        for path_name in _imported_module_paths(tree):
            head = path_name.split(".")[0]
            tail = path_name.split(".")[-1]
            if head in _FORBIDDEN_PRODUCTION_IMPORT_HEADS or tail in _FORBIDDEN_PRODUCTION_TAILS:
                offenders.append((relative, path_name))
        for bound in _imported_bound_names(tree):
            if bound in {"phase27_1_helpers", "test_phase27_1_exact_five_acceptance"}:
                offenders.append((relative, bound))
    assert not offenders, f"production imports test helpers: {offenders}"


def test_production_modules_reference_no_gate27_helper_filenames() -> None:
    """No ``kalhas/`` source (docstrings stripped) names a helper file."""
    offenders: list[tuple[str, str]] = []
    for py_file in sorted(KALHAS_ROOT.rglob("*.py")):
        code = _code_without_docstrings(py_file.read_text(encoding="utf-8"))
        for name in _FORBIDDEN_PRODUCTION_TAILS:
            if name in code:
                offenders.append((str(py_file.relative_to(REPO_ROOT)), name))
    assert not offenders, f"production references test-helper filenames: {offenders}"


def test_gate27_helpers_remain_outside_the_production_package() -> None:
    """The helpers stay under ``tests/`` and never inside ``kalhas/``."""
    helper = TESTS_DIR / "phase27_1_helpers.py"
    acceptance = TESTS_DIR / "test_phase27_1_exact_five_acceptance.py"
    assert helper.is_file()
    assert acceptance.is_file()
    assert not (KALHAS_ROOT / "tests").exists()
    stray_helpers = [str(path) for path in KALHAS_ROOT.rglob("phase27_1_helpers.py")]
    stray_acceptance = [
        str(path.relative_to(REPO_ROOT)) for path in KALHAS_ROOT.rglob("test_phase27_1_*.py")
    ]
    assert not stray_helpers, f"Gate 27.1 helper inside production: {stray_helpers}"
    assert not stray_acceptance, f"Gate 27.1 files inside production: {stray_acceptance}"


def test_agents_md_declares_exactly_nexus_legion_kalhas_roles() -> None:
    """AGENTS.md still declares exactly the three architecture roles."""
    agents_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized = " ".join(agents_text.split())
    assert "**NEXUS** owns natural-language dialogue" in normalized
    assert "**LEGION** owns strategy and agent exploration." in normalized
    assert "**KALHAS** owns versioned world models" in normalized
    assert "No other components exist." in normalized
    assert "Do not introduce new components or integration surfaces;" in normalized
    assert "the three named roles are the only allowed ones." in normalized


def test_production_package_has_no_new_component_directory() -> None:
    """No component beyond the audited Phase 27 production inventory.

    The audited baseline contains exactly these top-level members; any
    newly added component or integration surface fails this test.
    """
    audited_top_level = frozenset(
        {
            "__init__.py",
            "__pycache__",
            "adapters",
            "api",
            "application",
            "colony_ui",
            "contracts",
            "domain_packs",
            "version.py",
        }
    )
    actual = {entry.name for entry in KALHAS_ROOT.iterdir()}
    unexpected = actual - audited_top_level
    assert not unexpected, f"new component/integration surface directory: {sorted(unexpected)}"
    missing = {name for name in ("adapters", "api", "application", "contracts", "domain_packs")}
    assert missing <= actual, f"core KALHAS component removed: {sorted(missing - actual)}"


# ---------------------------------------------------------------------------
# Section 5: skip/xfail closure
# ---------------------------------------------------------------------------


def test_corrected_architecture_boundary_test_exists_unconditional_in_test_boundaries() -> None:
    """The H27.1-S02 corrected AGENTS.md boundary test stays executable."""
    tree = _module_tree(TESTS_DIR / "test_boundaries.py")
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert CORRECTED_BOUNDARY_TEST_NAME in functions
    target = functions[CORRECTED_BOUNDARY_TEST_NAME]

    decorators = [_decorator_text(decorator) for decorator in target.decorator_list]
    assert not decorators, f"corrected boundary test decorated: {decorators}"

    body_statements = [
        statement
        for statement in target.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    assert body_statements, "corrected boundary test has no executable body"
    for statement in body_statements:
        assert not isinstance(statement, (ast.Pass, ast.Raise)), (
            "corrected boundary test is conditionally implemented"
        )

    constant_returns = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.Return)
        and node.value is not None
        and isinstance(node.value, ast.Constant)
    ]
    assert not constant_returns, "corrected boundary test returns instead of asserting"

    assert_count = sum(1 for node in ast.walk(target) if isinstance(node, ast.Assert))
    assert assert_count >= 10, f"corrected boundary test assertions shrank: {assert_count}"


_SKIP_DECORATOR_TOKENS = frozenset({"skip", "skipif", "xfail", "expectedfailure"})
_SKIP_ATTRIBUTE_NAMES = frozenset({"skip", "xfail", "Skip", "ExpectedFailure", "skipif"})


def test_frozen_gate27_files_carry_no_skip_xfail_decorators() -> None:
    """No skip/xfail decorator exists in either frozen file."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        hits: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    rendered = _decorator_text(decorator).lower()
                    tail = rendered.rsplit(".", 1)[-1]
                    if tail in _SKIP_DECORATOR_TOKENS or "pytest.mark.skip" in rendered:
                        hits.append((node.lineno, rendered))
        assert not hits, f"skip/xfail decorator in {path.name}: {hits}"


def test_frozen_gate27_files_carry_no_executable_skip_xfail_calls() -> None:
    """No ``pytest.skip``/``pytest.xfail`` call or import exists."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        call_hits: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "skip",
                    "xfail",
                    "skipif",
                }:
                    root = _expression_root(node.func.value)
                    if root in {"pytest", "runpy", "_pytest"} or root.endswith("mark"):
                        call_hits.append((node.lineno, f"{root}.{node.func.attr}"))
                if isinstance(node.func, ast.Name) and node.func.id in {"skip", "xfail"}:
                    call_hits.append((node.lineno, node.func.id))
        assert not call_hits, f"executable skip/xfail call in {path.name}: {call_hits}"

        pytest_bindings = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "pytest"
            for alias in node.names
        }
        assert not (pytest_bindings & {"skip", "xfail", "mark"}), (
            f"pytest skip/xfail symbol imported in {path.name}"
        )


def test_pytest_mark_chains_are_absent_from_frozen_files() -> None:
    """No ``pytest.mark.skip/xfail`` marker chain appears structurally."""
    for path in FROZEN_GATE_PATHS:
        tree = _module_tree(path)
        marks: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _SKIP_ATTRIBUTE_NAMES:
                root = _expression_root(node.value)
                if root == "pytest" or root.endswith(".mark"):
                    marks.append(f"{root}.{node.attr}")
            if isinstance(node, ast.Name) and node.id.lower() in {
                "xfail",
                "expectedfailure",
            }:
                marks.append(node.id)
        assert not marks, f"pytest mark/skip/xfail marker in {path.name}: {marks}"


# ---------------------------------------------------------------------------
# Section 6: historical-proof preservation
# ---------------------------------------------------------------------------


def test_historical_phase27_boundary_classes_remain_present_with_tests() -> None:
    """All eight Phase 27 boundary classes keep their test methods."""
    tree = _module_tree(TESTS_DIR / "test_phase27_boundaries.py")
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    missing = [name for name in HISTORICAL_PHASE27_BOUNDARY_CLASSES if name not in classes]
    assert not missing, f"historical Phase 27 boundary classes missing: {missing}"
    for name in HISTORICAL_PHASE27_BOUNDARY_CLASSES:
        methods = [
            node
            for node in classes[name].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert methods, f"historical boundary class emptied: {name}"
        for method in methods:
            assert method.name.startswith("test_"), f"non-test member added: {name}.{method.name}"


def test_historical_phase27_acceptance_control_classes_remain_present() -> None:
    tree = _module_tree(TESTS_DIR / "test_phase27_acceptance.py")
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    missing = [name for name in HISTORICAL_PHASE27_ACCEPTANCE_CLASSES if name not in classes]
    assert not missing, f"historical acceptance classes missing: {missing}"


def test_historical_test_functions_meet_baseline_count_floors() -> None:
    """Historical suites cannot silently lose whole tests."""
    counts: dict[str, int] = {}
    for file_name, floor in HISTORICAL_TEST_COUNT_FLOORS.items():
        tree = _module_tree(TESTS_DIR / file_name)
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
        counts[file_name] = count
        assert count >= floor, f"{file_name}: test count {count} < floor {floor}"
    assert counts["test_phase27_boundaries.py"] == 55
    assert counts["test_phase27_1_exact_five_acceptance.py"] == 35


def test_historical_boundary_assertion_surface_meets_baseline_floors() -> None:
    """Assertion density cannot silently shrink below the audited baseline."""
    for file_name, floor in HISTORICAL_ASSERT_COUNT_FLOORS.items():
        tree = _module_tree(TESTS_DIR / file_name)
        assert_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Assert))
        assert assert_count >= floor, (
            f"{file_name}: assertion surface shrank ({assert_count} < {floor})"
        )


_PLATFORM_ABSOLUTE_PATH_PATTERN = re.compile(
    r"[A-Za-z]:\\(?:[^\"'\r\n]){2,}|/(?:Users|home)/[^\"'\r\n]{2,}"
)


def test_committed_gate27_tests_contain_no_platform_dependent_absolute_paths() -> None:
    """Committed Gate 27.1-era tests carry no machine-specific paths."""
    checked = (*FROZEN_GATE_PATHS, Path(__file__).resolve())
    for path in checked:
        code = _code_without_docstrings(path.read_text(encoding="utf-8"))
        hits = [match.group(0) for match in _PLATFORM_ABSOLUTE_PATH_PATTERN.finditer(code)]
        offending = [hit for hit in hits if hit.upper() != "C:\\"]
        assert not offending, f"platform-dependent absolute path in {path.name}: {offending}"


# ---------------------------------------------------------------------------
# Section 7: phase boundary - nothing beyond Gate 27.1 closure
# ---------------------------------------------------------------------------


def test_this_boundary_module_adds_only_static_structural_proofs() -> None:
    """The new file itself introduces no production behavior.

    Its only non-stdlib imports are the live cardinality constant and
    the frozen reference fixture - nothing else from production.
    """
    tree = _module_tree(Path(__file__).resolve())
    imported_paths = _imported_module_paths(tree)
    imported_roots = {path.split(".")[0] for path in imported_paths}
    assert imported_roots <= {"__future__", "ast", "re", "pathlib", "kalhas", "tests"}
    kalhas_imports = {path for path in imported_paths if path.startswith("kalhas")}
    tests_imports = {path for path in imported_paths if path.startswith("tests")}
    assert kalhas_imports == {"kalhas.application.campaign_service"}, sorted(kalhas_imports)
    assert tests_imports == {"tests.phase27_1_helpers"}, sorted(tests_imports)

    definitions = _defined_function_names(tree)
    future_tokens = ("adaptive", "runtime4", "route", "schema", "provider")
    for name in definitions:
        lowered = name.lower()
        for token in future_tokens:
            assert token not in lowered, f"future-phase surface in this module: {name}"


def test_gate27_closure_scope_inventory_is_exactly_three_files() -> None:
    """Exactly the audited Gate 27.1 test surfaces exist; no extras."""
    expected_gate_files = {
        "phase27_1_helpers.py",
        "test_phase27_1_exact_five_acceptance.py",
        "test_phase27_1_boundaries.py",
    }
    actual_gate_files = {
        path.name
        for pattern in ("phase27_1_*.py", "test_phase27_1_*.py")
        for path in TESTS_DIR.glob(pattern)
    }
    assert actual_gate_files == expected_gate_files, sorted(actual_gate_files)
