"""Phase 28 additive registry/schema compatibility boundary test.

After the accepted Phase 28 appends grew ``PUBLIC_CONTRACTS`` from 50 to
55, this suite owns the current exact registry/schema cardinality and
guards the additive-compatibility contract for all historical slices:

- API and schema versions stay unchanged (``"1"`` / ``"1.0.0"``);
- the accepted first 50 contracts remain the immutable Phase 27 prefix:
  indexes 0-46 equal ``_HISTORICAL_47_NAMES`` and indexes 47-49 are
  exactly ``CampaignDecisionPolicy`` / ``CampaignStrategyComparison`` /
  ``CampaignDecisionBrief``;
- the current registry is exactly 55 with a frozen Phase 28 tail
  (indexes 50-54 ``RuntimeObservationDeclaration`` /
  ``ExternalObservationInputBundle`` / ``AdaptivePolicy`` /
  ``AdaptiveRunTrajectoryExecution`` / ``AdaptiveRunTrajectoryReplayManifest``);
- the schema artifact set follows the public registry (count, titles);
- all 47 frozen historical schema byte hashes remain exact;
- the three Phase 27 decision schemas and all five Phase 28 schemas still
  equal their live ``model_json_schema()``;
- every nested Phase 27 / Phase 28 helper, draft, event, state, and
  input-entry model remains unregistered and has no standalone schema
  artifact;
- a precise AST scan over ``tests/`` fails if any historical test ever
  reintroduces an obsolete *current-global-count* assertion of exactly 50
  for ``PUBLIC_CONTRACTS`` or ``schema_files``.

Only this Phase 28 suite may assert the exact current cardinality (55).
Historical phase suites must stay additive-safe (``>= 50`` for the
registry, ``== len(PUBLIC_CONTRACTS)`` for schema artifacts), which the
AST scan is the durable guard for.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from kalhas.contracts.v1 import API_VERSION, PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.adaptive_trajectory_execution import (
    AdaptiveRunTrajectoryExecution,
)
from kalhas.contracts.v1.adaptive_trajectory_replay import (
    AdaptiveRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
)
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    RuntimeObservationDeclaration,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION
from pydantic import BaseModel

from tests.test_api_phase27 import _HISTORICAL_47_NAMES, _HISTORICAL_SCHEMA_HASHES

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

#: The exact immutable Phase 27 contract tail (indexes 47-49).
_PHASE27_TAIL = (
    "CampaignDecisionPolicy",
    "CampaignStrategyComparison",
    "CampaignDecisionBrief",
)

#: The exact Phase 28 contract tail (indexes 50-54).
_PHASE28_TAIL = (
    "RuntimeObservationDeclaration",
    "ExternalObservationInputBundle",
    "AdaptivePolicy",
    "AdaptiveRunTrajectoryExecution",
    "AdaptiveRunTrajectoryReplayManifest",
)

#: Phase 27 nested models that must never be registered or schematized.
_NESTED_PHASE27 = (
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

#: Phase 28 nested / non-authoritative models that must never be registered
#: or schematized.
_NESTED_PHASE28 = (
    "AdaptivePolicyDraft",
    "RuntimeObservationEvent",
    "AdaptivePolicyStateSnapshot",
    "AdaptivePolicyDecisionEvent",
    "AdaptivePolicySwitchEvent",
    "AdaptivePolicyRule",
    "AdaptivePolicyRuleDraft",
    "BoundAdaptiveAction",
    "TrajectoryPlanBinding",
    "ConditionComparisonLeaf",
    "ConditionAllNode",
    "ConditionAnyNode",
    "ObservationBinding",
    "ObservationTiming",
    "NoObservationNoise",
    "AdditiveUniformObservationNoise",
    "StateFieldObservationSource",
    "ExternalObservationSource",
    "ExternalObservationInputEntry",
)


class TestVersionBoundary:
    def test_api_and_schema_versions_unchanged(self) -> None:
        assert API_VERSION == "1"
        assert SCHEMA_VERSION == "1.0.0"


class TestPublicContractRegistry:
    def test_current_public_contract_count_is_exactly_55(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 55

    def test_immutable_accepted_50_phase27_prefix_is_unchanged(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 50
        assert len(_HISTORICAL_47_NAMES) == 47
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47:50] == _PHASE27_TAIL
        assert names[50:55] == _PHASE28_TAIL
        assert names[54] == "AdaptiveRunTrajectoryReplayManifest"


class TestSchemaCompatibility:
    def _schema_titles(self) -> set[str]:
        return {
            json.loads(path.read_text(encoding="utf-8"))["title"]
            for path in SCHEMA_DIR.glob("*.schema.json")
        }

    def test_schema_artifact_count_follows_the_public_registry(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        assert len(schema_files) == 55

    def test_schema_titles_equal_public_contract_names(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        titles = {json.loads(path.read_text(encoding="utf-8"))["title"] for path in schema_files}
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert titles == names

    def test_all_47_frozen_historical_schema_hashes_remain_exact(self) -> None:
        by_name = {path.name: path for path in SCHEMA_DIR.glob("*.schema.json")}
        assert len(_HISTORICAL_SCHEMA_HASHES) == 47
        for name, expected in _HISTORICAL_SCHEMA_HASHES.items():
            assert name in by_name, f"historical schema missing: {name}"
            digest = hashlib.sha256(by_name[name].read_bytes()).hexdigest()
            assert digest == expected, f"historical schema drifted: {name}"

    def test_three_phase27_decision_schemas_equal_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            CampaignDecisionPolicy: "CampaignDecisionPolicy.schema.json",
            CampaignStrategyComparison: "CampaignStrategyComparison.schema.json",
            CampaignDecisionBrief: "CampaignDecisionBrief.schema.json",
        }
        for contract, filename in expected.items():
            rendered = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_all_five_phase28_schemas_equal_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            RuntimeObservationDeclaration: "RuntimeObservationDeclaration.schema.json",
            ExternalObservationInputBundle: "ExternalObservationInputBundle.schema.json",
            AdaptivePolicy: "AdaptivePolicy.schema.json",
            AdaptiveRunTrajectoryExecution: "AdaptiveRunTrajectoryExecution.schema.json",
            AdaptiveRunTrajectoryReplayManifest: "AdaptiveRunTrajectoryReplayManifest.schema.json",
        }
        for contract, filename in expected.items():
            rendered = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_adaptive_run_trajectory_execution_schema_hash_is_exact(self) -> None:
        path = SCHEMA_DIR / "AdaptiveRunTrajectoryExecution.schema.json"
        assert path.exists(), "new schema artifact missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == "7d10563feffca03faa390712a99238f562502987d3c2a04ba14c626492c6789c"

    def test_adaptive_run_trajectory_replay_manifest_schema_hash_is_exact(self) -> None:
        path = SCHEMA_DIR / "AdaptiveRunTrajectoryReplayManifest.schema.json"
        assert path.exists(), "new schema artifact missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == "96a7bde2499792ed74044a343e0981ddcbfcd6691d5ae8051c620eb8a5ece1ca"


class TestNestedModelExclusion:
    def test_phase27_nested_models_never_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_PHASE27:
            assert nested not in names, f"{nested} independently registered"

    def test_phase28_nested_models_never_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_PHASE28:
            assert nested not in names, f"{nested} independently registered"

    def test_phase27_nested_models_have_no_standalone_schema(self) -> None:
        names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for nested in _NESTED_PHASE27:
            assert f"{nested}.schema.json" not in names, f"standalone schema for {nested}"

    def test_phase28_nested_models_have_no_standalone_schema(self) -> None:
        names = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
        for nested in _NESTED_PHASE28:
            assert f"{nested}.schema.json" not in names, f"standalone schema for {nested}"


class TestStaleAssertionDetector:
    """AST scan: no historical test may reintroduce an obsolete == 50 count.

    Only the current-global forms ``len(PUBLIC_CONTRACTS) == 50`` and
    ``len(schema_files) == 50`` are flagged. Legitimate historical facts
    (``len(frozen_names) == 50``, or prose describing the accepted Phase 27
    prefix) are deliberately not matched, so a plain substring scan cannot
    be used: this detector parses real equality expressions.
    """

    def test_no_historical_test_reintroduces_obsolete_50_global_count(self) -> None:
        offenders: list[tuple[str, int, str]] = []
        for module_path in sorted(TESTS_DIR.glob("*.py")):
            for lineno, expression in _stale_equality_nodes(
                module_path.read_text(encoding="utf-8"),
                module_path=str(module_path),
            ):
                offenders.append((module_path.name, lineno, expression))
        assert not offenders, (
            f"obsolete current-global-count == 50 assertions reintroduced: {offenders}"
        )

    def test_detects_len_public_contracts_eq_50(self) -> None:
        hits = _stale_equality_nodes("x = len(PUBLIC_CONTRACTS) == 50\n")
        assert len(hits) == 1 and "PUBLIC_CONTRACTS" in hits[0][1]

    def test_detects_50_eq_len_public_contracts(self) -> None:
        hits = _stale_equality_nodes("if 50 == len(PUBLIC_CONTRACTS):\n    pass\n")
        assert len(hits) == 1 and "PUBLIC_CONTRACTS" in hits[0][1]

    def test_detects_len_schema_files_eq_50(self) -> None:
        hits = _stale_equality_nodes("assert len(schema_files) == 50\n")
        assert len(hits) == 1 and "schema_files" in hits[0][1]

    def test_detects_50_eq_len_schema_files(self) -> None:
        hits = _stale_equality_nodes("assert 50 == len(schema_files)\n")
        assert len(hits) == 1 and "schema_files" in hits[0][1]

    def test_unrelated_len_equals_fifty_is_ignored(self) -> None:
        src = "assert len(frozen_historical_names) == 50\nassert len(other) == 50\n"
        assert _stale_equality_nodes(src) == []

    def test_docstring_and_comments_are_ignored(self) -> None:
        src = (
            '# "len(PUBLIC_CONTRACTS) == 50"\n'
            '"""len(schema_files) == 50 and 50 == len(PUBLIC_CONTRACTS)."""\n'
            "value = 1\n"
        )
        assert _stale_equality_nodes(src) == []

    def test_invalid_python_raises_syntax_error(self) -> None:
        with pytest.raises(SyntaxError):
            _stale_equality_nodes("def broken(:\n    pass\n")

    def test_syntax_error_names_affected_module(self) -> None:
        with pytest.raises(SyntaxError) as excinfo:
            _stale_equality_nodes(
                "def broken(:\n    pass\n",
                module_path="tests/test_phase99_boundaries.py",
            )
        assert "test_phase99_boundaries.py" in str(excinfo.value)


def _stale_equality_nodes(text: str, module_path: str = "<string>") -> list[tuple[int, str]]:
    """AST equality scan of one test file's source text.

    Flags the symmetric ``len(X) == 50`` **or** ``50 == len(X)`` forms
    where ``X`` is the ``PUBLIC_CONTRACTS`` module symbol or a variable
    literally named ``schema_files``. Returns ``(lineno, unparsed
    expression)``.

    The detector is symmetric (literal 50 accepted on either side of the
    equality) and fail-closed: comments/docstrings are ignored naturally
    through AST parsing and an unrelated ``len(other) == 50`` is never
    matched, but a source that is not valid Python raises ``SyntaxError``
    (never a silent ``[]``) so a broken historical test cannot masquerade
    as a clean scan. ``module_path`` names the affected file in that error.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise SyntaxError(
            f"failed to parse {module_path} during obsolete ==50 scan: "
            f"{exc.msg} (line {exc.lineno})"
        ) from exc
    hits: list[tuple[int, str]] = []

    def _is_stale_len(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in ("PUBLIC_CONTRACTS", "schema_files")
        )

    def _is_literal_fifty(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, int) and node.value == 50

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        left, right = node.left, node.comparators[0]
        stale = (_is_stale_len(left) and _is_literal_fifty(right)) or (
            _is_literal_fifty(left) and _is_stale_len(right)
        )
        if stale:
            hits.append((node.lineno, " ".join(ast.unparse(node).split())))
    return hits
