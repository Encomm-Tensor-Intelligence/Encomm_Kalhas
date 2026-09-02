"""Tests for the pure outcome-matrix identity and content-hash primitives.

Tests for ``kalhas/application/campaign_outcome_identity.py``: the
deterministic ``campaign_outcome_distribution_matrix_identifier`` and
the canonical ``campaign_outcome_distribution_matrix_content_hash``.
Proves:

- the exact public surface (keyword-only identifier parameters, exact
  ``__all__``, exact signatures);
- a hard-coded golden identifier and a hard-coded golden content hash
  for the fixed standard matrix;
- the exact readable prefix with exactly 16 lowercase hex digest
  characters, repeated-call equality, per-input sensitivity to all six
  identity inputs, caller mapping-order independence, and independence
  from content hash, timestamps, outcomes, and tenant;
- full content-hash coverage: recorded ``content_hash`` ignored, every
  other top-level field independently changing the digest, every nested
  outcome/empirical-distribution field (samples, order, quantiles,
  achievement count/probability, violation evidence, CVaR, adverse
  tail) changing the digest, reordering of strategies/seeds/objectives/
  metrics/outcomes changing the digest (including validator-bypassed
  ``model_copy`` tampering), optional uncertainty presence changing the
  digest, and ``derived_at`` changing the digest;
- JSON round-trip equality, zero input mutation, the narrow import
  boundary (only ``kalhas.application.hashing`` and the outcome
  contract - no pydantic), no forbidden executable/integration
  surfaces, no phase literals, and unchanged registry/schema counts;
- byte-identical preservation of every accepted Slice 1-4 file.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
)
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_outcome_identity.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

_PREFIX = "campaign-outcome-distribution-matrix-"
_ID_DIGEST_LENGTH = 16

#: Hard-coded golden identifier for the fixed identity input below.
GOLDEN_IDENTIFIER = "campaign-outcome-distribution-matrix-92156ae7382bc221"

#: Hard-coded golden canonical content hash of the standard matrix.
GOLDEN_CONTENT_HASH = "7f3c3278c79e0ef007d16a81db173595ce331dbda84ebdfaf3a55d598f6fe2d4"

#: The seven accepted Slice 1-4 files with their preservation hashes.
_PRESERVED_FILES = (
    (
        "kalhas/application/campaign_outcome_statistics.py",
        "5e4d32f8346a543c3260a43e67df593d695e8e091d0592a46566f8e08ae0e3d2",
    ),
    (
        "tests/test_campaign_outcome_statistics.py",
        "4f9dc8fd70e0a34cf20a91abc94df85600c5cb4fadb375c2f5450be02c9111bf",
    ),
    (
        "kalhas/application/campaign_outcome_runtime.py",
        "2829dffa57d45398265f831f704839e5a702853973a243c4d8d33b3c01ef3fd9",
    ),
    (
        "tests/test_campaign_outcome_runtime.py",
        "cf55a64ede5f2b12643f598e42db66741ce53e92326e41ca4e62615d2a289cac",
    ),
    (
        "kalhas/contracts/v1/campaign_outcome.py",
        "0100c5e5be6a47483c340179be8a4ba733662b7a1d58d5866cc8f1720d66cdd4",
    ),
    (
        "tests/test_campaign_outcome_contracts.py",
        "8bce441ab1ed0774fc07f2fbbeda3962cfe2bb2523d157f0dea8d3521a4206a3",
    ),
)

_IDENTITY_INPUTS = {
    "campaign_id": "campaign-1",
    "world_version_id": "world-1",
    "runtime_version": "3.0.0",
    "evaluation_profile_id": "profile-1",
    "source_world_realization_matrix_id": "realization-matrix-1",
    "source_metric_observation_matrix_id": "observation-matrix-1",
}


def _binding(**overrides: object) -> ObjectiveMetricBinding:
    """One valid objective-to-metric binding for outcome construction."""
    payload: dict[str, object] = {
        "objective_id": "obj-1",
        "metric_id": "m-1",
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "metric_unit": "units",
        "reach_tolerance": None,
        "normalization_scale": 100.0,
    }
    payload.update(overrides)
    return ObjectiveMetricBinding(**cast(Any, payload))


def _outcome(
    *,
    sequence_position: int,
    strategy_position: int,
    objective_position: int,
    strategy_candidate_id: str,
    binding: ObjectiveMetricBinding,
    ordered_observed_values: tuple[int | float, ...],
) -> Any:
    """One outcome built by the accepted pure builder."""
    return build_strategy_objective_outcome(
        sequence_position=sequence_position,
        strategy_position=strategy_position,
        objective_position=objective_position,
        strategy_candidate_id=strategy_candidate_id,
        binding=binding,
        ordered_observed_values=ordered_observed_values,
    )


def _matrix_outcomes(
    *,
    values_by_strategy: dict[str, tuple[int | float, ...]] | None = None,
) -> tuple[Any, ...]:
    """The four standard outcomes (or a custom-evidence variant) as a tuple."""
    strategy_ids = ("sc-a", "sc-b")
    objective_ids = ("obj-1", "obj-2")
    observed = values_by_strategy or {"sc-a": (91, 95), "sc-b": (80, 60)}
    bindings = {
        "obj-1": _binding(
            objective_id="obj-1",
            metric_id="m-1",
            direction="minimize",
            target=100.0,
            normalization_scale=100.0,
        ),
        "obj-2": _binding(
            objective_id="obj-2",
            metric_id="m-2",
            direction="maximize",
            target=50.0,
            normalization_scale=10.0,
        ),
    }
    outcomes: list[Any] = []
    for strategy_position, strategy_id in enumerate(strategy_ids):
        for objective_position, objective_id in enumerate(objective_ids):
            outcomes.append(
                _outcome(
                    sequence_position=strategy_position * 2 + objective_position,
                    strategy_position=strategy_position,
                    objective_position=objective_position,
                    strategy_candidate_id=strategy_id,
                    binding=bindings[objective_id],
                    ordered_observed_values=observed[strategy_id],
                )
            )
    return tuple(outcomes)


def _matrix_payload(**overrides: object) -> dict[str, object]:
    """One internally consistent standard matrix payload."""
    payload: dict[str, object] = {
        "identifier": "matrix-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-1",
        "world_content_hash": "b" * 64,
        "runtime_version": "3.0.0",
        "comparison_mode": "identical_conditions",
        "evaluation_profile_id": "profile-1",
        "evaluation_profile_content_hash": "c" * 64,
        "uncertainty_model_id": None,
        "uncertainty_model_content_hash": None,
        "source_world_realization_matrix_id": "realization-matrix-1",
        "source_world_realization_matrix_content_hash": "d" * 64,
        "source_metric_observation_matrix_id": "observation-matrix-1",
        "source_metric_observation_matrix_content_hash": "e" * 64,
        "ordered_strategy_candidate_ids": ["sc-a", "sc-b"],
        "ordered_scenario_seed_ids": ["seed-0", "seed-1"],
        "ordered_objective_ids": ["obj-1", "obj-2"],
        "ordered_metric_ids": ["m-1", "m-2"],
        "outcomes": list(_matrix_outcomes()),
        "content_hash": "f" * 64,
        "derived_at": "2026-08-15T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _matrix(**overrides: object) -> CampaignOutcomeDistributionMatrix:
    """One validated standard matrix."""
    return CampaignOutcomeDistributionMatrix.model_validate(_matrix_payload(**overrides))


def _hash_of(matrix: CampaignOutcomeDistributionMatrix) -> str:
    return campaign_outcome_distribution_matrix_content_hash(matrix)


class TestPublicSurface:
    def test_exact_all(self) -> None:
        import kalhas.application.campaign_outcome_identity as module

        assert module.__all__ == [
            "campaign_outcome_distribution_matrix_identifier",
            "campaign_outcome_distribution_matrix_content_hash",
        ]
        for name in module.__all__:
            assert hasattr(module, name)

    def test_identifier_signature_is_keyword_only_and_exact(self) -> None:
        parameters = tuple(
            inspect.signature(campaign_outcome_distribution_matrix_identifier).parameters
        )
        assert parameters == (
            "campaign_id",
            "world_version_id",
            "runtime_version",
            "evaluation_profile_id",
            "source_world_realization_matrix_id",
            "source_metric_observation_matrix_id",
        )
        signature = inspect.signature(campaign_outcome_distribution_matrix_identifier)
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        assert signature.return_annotation == "str"

    def test_content_hash_signature_is_exact(self) -> None:
        signature = inspect.signature(campaign_outcome_distribution_matrix_content_hash)
        assert tuple(signature.parameters) == ("matrix",)
        assert signature.return_annotation == "str"


class TestIdentifierGolden:
    def test_golden_identifier_hard_coded(self) -> None:
        assert campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS) == (
            GOLDEN_IDENTIFIER
        )

    def test_exact_prefix_and_sixteen_lowercase_hex_digest_chars(self) -> None:
        identifier = campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS)
        assert identifier.startswith(_PREFIX)
        assert len(identifier) == len(_PREFIX) + _ID_DIGEST_LENGTH
        digest = identifier[len(_PREFIX) :]
        assert re.fullmatch(rf"[0-9a-f]{{{_ID_DIGEST_LENGTH}}}", digest) is not None
        assert digest == sha256_hex(canonical_json(_IDENTITY_INPUTS))[:_ID_DIGEST_LENGTH]

    def test_repeated_calls_return_identical_identifiers(self) -> None:
        first = campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS)
        second = campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS)
        third = campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS)
        assert first == second == third == GOLDEN_IDENTIFIER

    @pytest.mark.parametrize(
        ("field", "changed"),
        (
            pytest.param("campaign_id", "campaign-2", id="campaign-id"),
            pytest.param("world_version_id", "world-2", id="world-version-id"),
            pytest.param("runtime_version", "3.1.0", id="runtime-version"),
            pytest.param("evaluation_profile_id", "profile-2", id="evaluation-profile-id"),
            pytest.param(
                "source_world_realization_matrix_id",
                "realization-matrix-2",
                id="source-realization-matrix-id",
            ),
            pytest.param(
                "source_metric_observation_matrix_id",
                "observation-matrix-2",
                id="source-observation-matrix-id",
            ),
        ),
    )
    def test_each_identity_input_independently_changes_the_identifier(
        self, field: str, changed: str
    ) -> None:
        inputs = dict(_IDENTITY_INPUTS)
        inputs[field] = changed
        assert campaign_outcome_distribution_matrix_identifier(**inputs) != (GOLDEN_IDENTIFIER)

    def test_equivalent_inputs_never_depend_on_caller_mapping_order(self) -> None:
        reversed_order = {
            "source_metric_observation_matrix_id": _IDENTITY_INPUTS[
                "source_metric_observation_matrix_id"
            ],
            "source_world_realization_matrix_id": _IDENTITY_INPUTS[
                "source_world_realization_matrix_id"
            ],
            "evaluation_profile_id": _IDENTITY_INPUTS["evaluation_profile_id"],
            "runtime_version": _IDENTITY_INPUTS["runtime_version"],
            "world_version_id": _IDENTITY_INPUTS["world_version_id"],
            "campaign_id": _IDENTITY_INPUTS["campaign_id"],
        }
        assert set(reversed_order) == set(_IDENTITY_INPUTS)
        assert campaign_outcome_distribution_matrix_identifier(**reversed_order) == (
            GOLDEN_IDENTIFIER
        )

    def test_identifier_does_not_use_matrix_fields(self) -> None:
        # Wildly different matrix contents (content hash, timestamps,
        # outcomes, tenant) with the same six identity inputs must yield
        # the identical identifier.
        plain = _matrix()
        decorated = _matrix(
            content_hash="0" * 64,
            tenant_id="tenant-9",
            derived_at="2026-12-31T23:59:59Z",
            uncertainty_model_id="um-1",
            uncertainty_model_content_hash="ab" * 32,
            outcomes=list(_matrix_outcomes(values_by_strategy={"sc-a": (1, 2), "sc-b": (3, 4)})),
        )
        identity = {
            "campaign_id": decorated.campaign_id,
            "world_version_id": decorated.world_version_id,
            "runtime_version": decorated.runtime_version,
            "evaluation_profile_id": decorated.evaluation_profile_id,
            "source_world_realization_matrix_id": decorated.source_world_realization_matrix_id,
            "source_metric_observation_matrix_id": decorated.source_metric_observation_matrix_id,
        }
        assert campaign_outcome_distribution_matrix_identifier(**identity) == (GOLDEN_IDENTIFIER)
        assert plain.identifier == decorated.identifier == "matrix-1"
        assert _hash_of(plain) != _hash_of(decorated)


class TestContentHashGolden:
    def test_golden_content_hash_hard_coded(self) -> None:
        assert _hash_of(_matrix()) == GOLDEN_CONTENT_HASH

    def test_recomputed_hash_is_not_the_recorded_content_hash(self) -> None:
        matrix = _matrix()
        assert matrix.content_hash == "f" * 64
        assert _hash_of(matrix) != matrix.content_hash

    def test_repeated_calls_return_identical_hashes(self) -> None:
        matrix = _matrix()
        assert _hash_of(matrix) == _hash_of(matrix) == GOLDEN_CONTENT_HASH

    def test_json_round_tripped_equivalent_matrix_has_same_hash(self) -> None:
        matrix = _matrix()
        restored = CampaignOutcomeDistributionMatrix.model_validate(
            json.loads(matrix.model_dump_json())
        )
        assert restored == matrix
        assert _hash_of(restored) == GOLDEN_CONTENT_HASH

    def test_changing_only_recorded_content_hash_leaves_recomputation_unchanged(self) -> None:
        matrix = _matrix()
        for recorded in ("0" * 64, "1" * 64, "e" * 63 + "f"):
            modified = matrix.model_copy(update={"content_hash": recorded})
            assert _hash_of(modified) == GOLDEN_CONTENT_HASH

    def test_every_top_level_field_changes_the_hash(self) -> None:
        matrix = _matrix()
        changed: list[tuple[str, object]] = [
            ("identifier", "matrix-2"),
            ("tenant_id", "tenant-2"),
            ("schema_version", "2.0.0"),
            ("campaign_id", "campaign-2"),
            ("scenario_id", "scenario-2"),
            ("scenario_content_hash", "a" * 63 + "b"),
            ("world_version_id", "world-2"),
            ("world_content_hash", "b" * 63 + "c"),
            ("runtime_version", "9.9.9"),
            ("comparison_mode", "shared_conditions"),
            ("evaluation_profile_id", "profile-2"),
            ("evaluation_profile_content_hash", "c" * 63 + "d"),
            ("uncertainty_model_id", "um-1"),
            ("uncertainty_model_content_hash", "ab" * 32),
            ("source_world_realization_matrix_id", "realization-matrix-2"),
            ("source_world_realization_matrix_content_hash", "d" * 63 + "e"),
            ("source_metric_observation_matrix_id", "observation-matrix-2"),
            ("source_metric_observation_matrix_content_hash", "e" * 63 + "f"),
            ("ordered_strategy_candidate_ids", ("sc-a", "sc-b", "sc-c")),
            ("ordered_scenario_seed_ids", ("seed-0", "seed-1", "seed-2")),
            ("ordered_objective_ids", ("obj-1", "obj-2", "obj-3")),
            ("ordered_metric_ids", ("m-1", "m-2", "m-3")),
            (
                "outcomes",
                _matrix_outcomes(values_by_strategy={"sc-a": (90, 95), "sc-b": (80, 60)}),
            ),
            ("derived_at", datetime(2026, 8, 16, 12, 0, tzinfo=UTC)),
        ]
        for field, value in changed:
            modified = matrix.model_copy(update={field: value})
            assert _hash_of(modified) != _hash_of(matrix), f"field {field} did not change the hash"

    def test_nested_observed_sample_value_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(update={"ordered_observed_values": (90, 95)}),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_observed_sample_order_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(update={"ordered_observed_values": (95, 91)}),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_empirical_quantile_changes_the_hash(self) -> None:
        matrix = _matrix()
        summary = matrix.outcomes[0].empirical_distribution.model_copy(update={"p95": 119.0})
        outcome = matrix.outcomes[0].model_copy(update={"empirical_distribution": summary})
        modified = matrix.model_copy(update={"outcomes": (outcome, *matrix.outcomes[1:])})
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_achievement_count_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(update={"target_achievement_count": 1}),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_achievement_probability_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(
                        update={"empirical_target_achievement_probability": 0.25}
                    ),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_normalized_violation_evidence_changes_the_hash(self) -> None:
        matrix = _matrix()
        violation_distribution = matrix.outcomes[0].normalized_target_violation_distribution
        assert violation_distribution is not None
        tampered = violation_distribution.model_copy(
            update={"ordered_samples": (0.0, 0.0, 0.1, 0.3)}
        )
        outcome = matrix.outcomes[0].model_copy(
            update={"normalized_target_violation_distribution": tampered}
        )
        modified = matrix.model_copy(update={"outcomes": (outcome, *matrix.outcomes[1:])})
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_cvar_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(update={"target_violation_cvar": 0.25}),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_nested_adverse_tail_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={
                "outcomes": (
                    matrix.outcomes[0].model_copy(update={"adverse_tail_statistic": 119.0}),
                    *matrix.outcomes[1:],
                )
            }
        )
        assert _hash_of(modified) != _hash_of(matrix)

    @pytest.mark.parametrize(
        ("field", "reordered"),
        (
            pytest.param(
                "ordered_strategy_candidate_ids",
                ("sc-b", "sc-a"),
                id="strategies",
            ),
            pytest.param(
                "ordered_scenario_seed_ids",
                ("seed-1", "seed-0"),
                id="seeds",
            ),
            pytest.param(
                "ordered_objective_ids",
                ("obj-2", "obj-1"),
                id="objectives",
            ),
            pytest.param(
                "ordered_metric_ids",
                ("m-2", "m-1"),
                id="metrics",
            ),
        ),
    )
    def test_reordering_identity_tuples_changes_the_hash(
        self, field: str, reordered: object
    ) -> None:
        # Validator-bypassed model_copy tampering: the reordered tuple
        # deliberately disagrees with the nested outcomes, yet the hash
        # function must still detect the reordering.
        matrix = _matrix()
        modified = matrix.model_copy(update={field: reordered})
        assert _hash_of(modified) != _hash_of(matrix)

    def test_reordering_outcomes_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(update={"outcomes": tuple(reversed(matrix.outcomes))})
        assert _hash_of(modified) != _hash_of(matrix)

    def test_optional_uncertainty_absent_vs_present_changes_the_hash(self) -> None:
        absent = _matrix()
        present = _matrix(
            uncertainty_model_id="um-1",
            uncertainty_model_content_hash="ab" * 32,
        )
        assert _hash_of(present) != _hash_of(absent)
        other = present.model_copy(update={"uncertainty_model_content_hash": "cd" * 32})
        assert _hash_of(other) != _hash_of(present)

    def test_derived_at_changes_the_hash(self) -> None:
        matrix = _matrix()
        modified = matrix.model_copy(
            update={"derived_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC)}
        )
        assert _hash_of(modified) != _hash_of(matrix)

    def test_functions_never_mutate_the_matrix_or_nested_evidence(self) -> None:
        matrix = _matrix()
        before_dump = matrix.model_dump(mode="json")
        before_nested = matrix.outcomes[0].model_dump(mode="python")
        before_summary = matrix.outcomes[0].empirical_distribution.model_dump(mode="python")
        campaign_outcome_distribution_matrix_identifier(**_IDENTITY_INPUTS)
        _hash_of(matrix)
        _hash_of(matrix)
        assert matrix.model_dump(mode="json") == before_dump
        assert matrix.outcomes[0].model_dump(mode="python") == before_nested
        assert matrix.outcomes[0].empirical_distribution.model_dump(mode="python") == (
            before_summary
        )


class TestModuleBoundaries:
    def test_imports_only_the_two_allowed_internal_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(tree)
        assert set(module_paths) == {
            "__future__",
            "kalhas.application.hashing",
            "kalhas.contracts.v1.campaign_outcome",
        }, sorted(module_paths)
        modules = _imported_modules(tree)
        assert modules == {"__future__", "kalhas"}
        assert "pydantic" not in modules
        forbidden = {
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "shutil",
            "tempfile",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "random",
            "uuid",
            "secrets",
            "datetime",
            "time",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
        }
        assert not (modules & forbidden)

    def test_no_store_api_query_or_persistence_identifiers(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "store" not in names
        module_paths = _imported_module_paths(tree)
        assert not any(path.startswith("kalhas.api") for path in module_paths)
        assert not any("query" in path for path in module_paths)

    def test_no_wall_clock_randomness_or_activity_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_calls = {
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
            "uuid.uuid4",
            "uuid.uuid1",
        }
        assert not (calls & forbidden_calls)
        assert not any(
            "record_activity" in call or "operational_activity" in call for call in calls
        )

    def test_no_executable_expression_surface(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Lambda), "lambda expression in the module"
            if isinstance(node, ast.Call):
                name: str | None = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name not in {"exec", "eval", "compile", "__import__"}, (
                    f"executable call {name!r} in the module"
                )

    def test_no_phase_number_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        assert not pattern.search(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        import kalhas.application.campaign_outcome_identity as module

        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        symbols = list(module.__all__)
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
                symbols.extend(argument.arg for argument in node.args.args)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"

    def test_public_contracts_and_schemas_preserve_50_prefix(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 50
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert names[47] == "CampaignDecisionPolicy"
        assert names[48] == "CampaignStrategyComparison"
        assert names[49] == "CampaignDecisionBrief"
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        file_names = {path.name for path in schema_files}
        assert "CampaignOutcomeDistributionMatrix.schema.json" in file_names


class TestPreservedFiles:
    def test_slice_one_through_four_files_remain_byte_identical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative, expected in _PRESERVED_FILES:
            digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            assert digest == expected, f"{relative} changed: {digest}"


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
