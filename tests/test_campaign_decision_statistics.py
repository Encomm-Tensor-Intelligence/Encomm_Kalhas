"""Tests for the pure paired-comparison and weighted-regret numeric primitives.

Phase 27 statistics-slice tests for
``kalhas/application/campaign_decision_statistics.py``: the
direction-normalized paired-delta primitives (one-seed and ordered
vector), the win/tie/loss decomposition with median/p05/p95/extrema
statistics under the declared tie tolerance, same-seed normalized regret
across all supplied strategies, and the weighted regret aggregation
helpers (per-objective weighted mean, per-seed totals, complete
per-seed total vector, and total-regret median/p95/maximum statistics).

Golden results use exact equality whenever the result is exactly
representable; mathematically non-terminating fractional results use
one-ULP assertions - the result must differ from the correctly rounded
rational reference by at most one representable float step
(``abs(actual - expected) <= math.ulp(expected)``). ``Fraction`` is used
in tests only for independent rational references; production must never
import ``Fraction`` or ``Decimal`` (proven by the module-boundary
tests).
"""

from __future__ import annotations

import ast
import math
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.application.campaign_decision_statistics import (
    Direction,
    PairedDeltaSummary,
    TotalRegretSummary,
    objective_weighted_mean_regret,
    paired_delta,
    paired_delta_statistics,
    paired_delta_vector,
    per_seed_total_weighted_regret,
    same_seed_regret,
    total_regret_statistics,
    total_regret_vector,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_decision_statistics.py"
)

_ALL_DIRECTIONS: tuple[Direction, ...] = ("minimize", "maximize", "reach")


class _TupleSubclass(tuple[Any, ...]):
    pass


class _SubInt(int):
    pass


class _SubFloat(float):
    pass


_BAD_NUMERIC_SCALARS = (
    pytest.param(True, id="bool"),
    pytest.param("3", id="string"),
    pytest.param(Decimal("3"), id="decimal"),
    pytest.param(None, id="none"),
    pytest.param([3], id="list-container"),
    pytest.param(_SubInt(3), id="int-subclass"),
    pytest.param(_SubFloat(3.0), id="float-subclass"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
)

_OVERFLOW_NUMERIC_SCALARS = (
    pytest.param(10**400, id="huge-positive-int"),
    pytest.param(-(10**400), id="huge-negative-int"),
)

_BAD_DIRECTIONS = (
    pytest.param("MINIMIZE", id="upper-case"),
    pytest.param("minimise", id="misspelled"),
    pytest.param("reach ", id="trailing-space"),
    pytest.param("", id="empty-string"),
    pytest.param(1, id="int"),
    pytest.param(None, id="none"),
    pytest.param(True, id="bool"),
    pytest.param(["minimize"], id="list-container"),
    pytest.param(("minimize",), id="tuple-container"),
)

#: Invalid tolerance/weight values (zero - including ``-0.0``, which is
#: numerically equal to zero - is legal and covered separately).
_BAD_NON_NEGATIVE_SCALARS = (
    pytest.param(-1, id="negative-int"),
    pytest.param(-1.5, id="negative-float"),
    pytest.param(True, id="bool"),
    pytest.param("0.1", id="string"),
    pytest.param(Decimal("0.1"), id="decimal"),
    pytest.param(None, id="none"),
    pytest.param([1], id="list-container"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
)

#: Invalid scale values (zero is illegal for a scale).
_BAD_SCALES = _BAD_NON_NEGATIVE_SCALARS + (
    pytest.param(0, id="zero-int"),
    pytest.param(0.0, id="zero-float"),
)

_BAD_COLLECTIONS = (
    pytest.param([1.0, 2.0], id="list"),
    pytest.param(_TupleSubclass((1.0, 2.0)), id="tuple-subclass"),
)


def _assert_within_one_ulp(actual: float, expected: float) -> None:
    """Prove the result differs from the correctly rounded rational reference
    by at most one representable float step (``math.ulp``)."""
    assert abs(actual - expected) <= math.ulp(expected)


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


class TestPublicSurface:
    def test_exact_public_all(self) -> None:
        import kalhas.application.campaign_decision_statistics as module

        assert module.__all__ == [
            "PairedDeltaSummary",
            "TotalRegretSummary",
            "paired_delta",
            "paired_delta_vector",
            "paired_delta_statistics",
            "same_seed_regret",
            "objective_weighted_mean_regret",
            "per_seed_total_weighted_regret",
            "total_regret_vector",
            "total_regret_statistics",
        ]
        for name in module.__all__:
            assert hasattr(module, name)

    def test_summary_field_names_exact(self) -> None:
        assert PairedDeltaSummary._fields == (
            "sample_count",
            "win_count",
            "tie_count",
            "loss_count",
            "win_rate",
            "tie_rate",
            "loss_rate",
            "median_paired_delta",
            "p05_paired_delta",
            "p95_paired_delta",
            "worst_paired_delta",
            "best_paired_delta",
        )
        assert TotalRegretSummary._fields == (
            "sample_count",
            "median_total_regret",
            "p95_total_regret",
            "maximum_total_regret",
        )

    def test_summary_types_are_immutable(self) -> None:
        summary = paired_delta_statistics((0.0, 1.0), tie_tolerance=0.5)
        assert isinstance(summary, tuple)
        with pytest.raises(AttributeError):
            summary.win_count = 3  # type: ignore[misc]
        totals = total_regret_statistics((1.0, 2.0))
        assert isinstance(totals, tuple)
        with pytest.raises(AttributeError):
            totals.median_total_regret = 0.0  # type: ignore[misc]


class TestModuleBoundaries:
    def test_imports_only_stdlib_and_the_two_accepted_primitives(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules = _imported_modules(tree)
        assert modules == {"__future__", "math", "typing", "kalhas"}
        module_paths = _imported_module_paths(tree)
        assert module_paths == {
            "__future__",
            "math",
            "typing",
            "kalhas.application.campaign_metric_statistics_runtime",
            "kalhas.application.campaign_outcome_statistics",
        }

    def test_no_forbidden_stdlib_or_external_imports(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules = _imported_modules(tree)
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

    def test_no_store_api_contracts_adapters_or_domain_packs(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(tree)
        forbidden_prefixes = (
            "kalhas.contracts",
            "kalhas.store",
            "kalhas.api",
            "kalhas.adapters",
            "kalhas.domain_packs",
            "nexus",
            "legion",
        )
        assert not any(
            path.startswith(prefix) for path in module_paths for prefix in forbidden_prefixes
        )

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

    def test_no_forbidden_decision_surface_vocabulary(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        assert forbidden.search(source) is None

    def test_no_phase27_artifact_names(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for name in (
            "CampaignDecisionPolicy",
            "ObjectivePairedComparison",
            "StrategyRobustnessProfile",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "feasibility-pareto-minimax-regret-v1",
        ):
            assert name not in source


class TestPairedDeltaOneSeed:
    def test_minimize_goldens(self) -> None:
        assert paired_delta(5, 3, direction="minimize", normalization_scale=10) == 0.2
        assert paired_delta(2, 8, direction="minimize", normalization_scale=10) == -0.6
        assert paired_delta(3, 3, direction="minimize", normalization_scale=10) == 0.0

    def test_maximize_goldens(self) -> None:
        assert paired_delta(5, 3, direction="maximize", normalization_scale=10) == -0.2
        assert paired_delta(2, 8, direction="maximize", normalization_scale=10) == 0.6
        assert paired_delta(3, 3, direction="maximize", normalization_scale=10) == 0.0

    def test_reach_goldens(self) -> None:
        assert paired_delta(12, 8, direction="reach", normalization_scale=5, target=10) == 0.0
        assert paired_delta(15, 8, direction="reach", normalization_scale=5, target=10) == 0.6
        assert paired_delta(7, 12, direction="reach", normalization_scale=5, target=10) == 0.2
        assert paired_delta(10, 10, direction="reach", normalization_scale=5, target=10) == 0.0
        assert paired_delta(10, 15, direction="reach", normalization_scale=5, target=10) == -1.0

    def test_positive_means_first_strategy_is_worse(self) -> None:
        assert paired_delta(8, 3, direction="minimize", normalization_scale=1) > 0.0
        assert paired_delta(8, 3, direction="maximize", normalization_scale=1) < 0.0
        assert paired_delta(20, 12, direction="reach", normalization_scale=1, target=15) > 0.0

    def test_negative_means_first_strategy_is_better(self) -> None:
        assert paired_delta(3, 8, direction="minimize", normalization_scale=1) < 0.0
        assert paired_delta(3, 8, direction="maximize", normalization_scale=1) > 0.0
        assert paired_delta(12, 20, direction="reach", normalization_scale=1, target=15) < 0.0

    def test_exact_zero(self) -> None:
        assert paired_delta(7, 7, direction="minimize", normalization_scale=2) == 0.0
        assert paired_delta(7, 7, direction="maximize", normalization_scale=2) == 0.0
        assert paired_delta(7, 7, direction="reach", normalization_scale=2, target=10) == 0.0
        # reach tie: equal absolute deviation from the target
        assert paired_delta(12, 8, direction="reach", normalization_scale=2, target=10) == 0.0

    def test_integer_arithmetic_is_exact_float_division(self) -> None:
        assert paired_delta(5, 3, direction="minimize", normalization_scale=2) == 1.0
        assert paired_delta(5, 3, direction="minimize", normalization_scale=4) == 0.5

    def test_target_is_not_used_for_minimize_or_maximize(self) -> None:
        assert paired_delta(5, 3, direction="minimize", normalization_scale=10, target=1000) == 0.2
        # even a non-numeric target is ignored: never validated, never read
        assert (
            paired_delta(
                5, 3, direction="maximize", normalization_scale=10, target=cast(Any, "junk")
            )
            == -0.2
        )

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_value_a_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta(bad, 3.0, direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_value_b_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta(3.0, bad, direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_integer_raises_overflow(self, huge: int) -> None:
        with pytest.raises(OverflowError):
            paired_delta(huge, 3.0, direction="minimize", normalization_scale=1.0)

    @pytest.mark.parametrize("bad", _BAD_DIRECTIONS)
    def test_bad_direction_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta(1.0, 2.0, direction=cast(Any, bad), normalization_scale=1.0)

    @pytest.mark.parametrize("bad", _BAD_SCALES)
    def test_bad_scale_rejected(self, bad: object) -> None:
        with pytest.raises((ValueError, OverflowError)):
            paired_delta(1.0, 2.0, direction="minimize", normalization_scale=cast(Any, bad))

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_reach_target_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta(
                1.0, 2.0, direction="reach", normalization_scale=1.0, target=cast(Any, bad)
            )

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_reach_target_raises_overflow(self, huge: int) -> None:
        with pytest.raises(OverflowError):
            paired_delta(1.0, 2.0, direction="reach", normalization_scale=1.0, target=huge)

    def test_reach_requires_target(self) -> None:
        with pytest.raises(ValueError):
            paired_delta(1.0, 2.0, direction="reach", normalization_scale=1.0)

    def test_arithmetic_overflow_raises_overflow(self) -> None:
        # difference overflow
        with pytest.raises(OverflowError):
            paired_delta(1.7e308, -1.7e308, direction="minimize", normalization_scale=1.0)
        # division overflow
        with pytest.raises(OverflowError):
            paired_delta(1e308, 0.0, direction="minimize", normalization_scale=1e-308)
        # reach deviation overflow
        with pytest.raises(OverflowError):
            paired_delta(1.7e308, 1.0, direction="reach", normalization_scale=1.0, target=-1.7e308)


class TestPairedDeltaVector:
    def test_minimize_golden_vector(self) -> None:
        assert paired_delta_vector(
            (5, 2, 8), (3, 8, 3), direction="minimize", normalization_scale=10
        ) == (0.2, -0.6, 0.5)

    def test_maximize_golden_vector(self) -> None:
        assert paired_delta_vector(
            (5, 2, 8), (3, 8, 3), direction="maximize", normalization_scale=10
        ) == (-0.2, 0.6, -0.5)

    def test_reach_golden_vector(self) -> None:
        assert paired_delta_vector(
            (12, 15, 7), (8, 8, 12), direction="reach", normalization_scale=5, target=10
        ) == (0.0, 0.6, 0.2)

    def test_seed_order_is_preserved_elementwise(self) -> None:
        values_a = (8.0, 1.0, 4.0)
        values_b = (2.0, 5.0, 3.0)
        result = paired_delta_vector(
            values_a, values_b, direction="minimize", normalization_scale=1
        )
        assert result == (6.0, -4.0, 1.0)
        # elementwise identity in exact seed order; no sorting or matching by value
        assert result[0] == values_a[0] - values_b[0]
        assert result[1] == values_a[1] - values_b[1]
        assert result[2] == values_a[2] - values_b[2]

    def test_swapped_orientation_is_exact_sign_reverse(self) -> None:
        values_a = (5, 2, 8)
        values_b = (3, 8, 3)
        forward_min = paired_delta_vector(
            values_a, values_b, direction="minimize", normalization_scale=10
        )
        reverse_min = paired_delta_vector(
            values_b, values_a, direction="minimize", normalization_scale=10
        )
        assert reverse_min == tuple(-delta for delta in forward_min)
        forward_max = paired_delta_vector(
            values_a, values_b, direction="maximize", normalization_scale=10
        )
        reverse_max = paired_delta_vector(
            values_b, values_a, direction="maximize", normalization_scale=10
        )
        assert reverse_max == tuple(-delta for delta in forward_max)
        forward_reach = paired_delta_vector(
            values_a, values_b, direction="reach", normalization_scale=10, target=10
        )
        reverse_reach = paired_delta_vector(
            values_b, values_a, direction="reach", normalization_scale=10, target=10
        )
        assert reverse_reach == tuple(-delta for delta in forward_reach)

    def test_mixed_int_float_samples(self) -> None:
        assert paired_delta_vector(
            (5, 2.5, 8), (3.0, 8, 3), direction="minimize", normalization_scale=10
        ) == (0.2, -0.55, 0.5)

    def test_caller_tuples_never_mutated(self) -> None:
        values_a = (5, 2, 8)
        values_b = (3, 8, 3)
        snapshot_a = tuple(values_a)
        snapshot_b = tuple(values_b)
        paired_delta_vector(values_a, values_b, direction="minimize", normalization_scale=10)
        assert values_a == snapshot_a
        assert values_b == snapshot_b
        assert all(type(value) is int for value in values_a)
        assert all(type(value) is int for value in values_b)

    @pytest.mark.parametrize("bad", _BAD_COLLECTIONS)
    def test_collection_type_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta_vector(bad, (1.0, 2.0), direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            paired_delta_vector((1.0, 2.0), bad, direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]

    def test_empty_tuples_rejected(self) -> None:
        with pytest.raises(ValueError):
            paired_delta_vector((), (1.0,), direction="minimize", normalization_scale=1.0)
        with pytest.raises(ValueError):
            paired_delta_vector((1.0,), (), direction="minimize", normalization_scale=1.0)

    def test_unequal_length_rejected(self) -> None:
        with pytest.raises(ValueError):
            paired_delta_vector((1.0, 2.0), (1.0,), direction="minimize", normalization_scale=1.0)

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_element_in_values_a_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            bad_values_a = cast("tuple[int | float, ...]", (bad, 2.0))
            paired_delta_vector(
                bad_values_a, (1.0, 1.0), direction="minimize", normalization_scale=1.0
            )

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_element_in_values_b_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            bad_values_b = cast("tuple[int | float, ...]", (1.0, bad))
            paired_delta_vector(
                (1.0, 2.0), bad_values_b, direction="minimize", normalization_scale=1.0
            )

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_integer_rejected_before_any_arithmetic(self, huge: int) -> None:
        # The failing sample is last: the complete-tuple conversion proof
        # still fails before any delta arithmetic begins.
        with pytest.raises(OverflowError):
            paired_delta_vector(
                (1.0, 2.0), (1.0, huge), direction="minimize", normalization_scale=1.0
            )

    def test_overflowing_difference_raises_overflow(self) -> None:
        with pytest.raises(OverflowError):
            paired_delta_vector(
                (1.7e308, 1.0), (-1.7e308, 1.0), direction="minimize", normalization_scale=1.0
            )

    def test_reach_without_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            paired_delta_vector((1.0,), (1.0,), direction="reach", normalization_scale=1.0)


class TestTieClassification:
    def test_exactly_minus_tolerance_is_a_tie(self) -> None:
        summary = paired_delta_statistics((-0.1,), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 0)

    def test_exactly_zero_is_a_tie(self) -> None:
        summary = paired_delta_statistics((0.0,), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 0)

    def test_exactly_plus_tolerance_is_a_tie(self) -> None:
        summary = paired_delta_statistics((0.1,), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 0)

    def test_one_ulp_inside_each_boundary_is_a_tie(self) -> None:
        inside_below = math.nextafter(-0.1, 0.0)
        inside_above = math.nextafter(0.1, 0.0)
        summary = paired_delta_statistics((inside_below, inside_above), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 2, 0)

    def test_one_ulp_outside_each_boundary_is_win_or_loss(self) -> None:
        outside_below = math.nextafter(-0.1, -math.inf)
        outside_above = math.nextafter(0.1, math.inf)
        summary = paired_delta_statistics((outside_below, outside_above), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (1, 0, 1)

    def test_mixed_vector_exact_counts_and_rates(self) -> None:
        summary = paired_delta_statistics((-0.2, -0.05, 0.0, 0.1, 0.2), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (1, 3, 1)
        assert summary.sample_count == 5
        assert summary.win_rate == 1 / 5
        assert summary.tie_rate == 3 / 5
        assert summary.loss_rate == 1 / 5

    def test_repeated_values(self) -> None:
        summary = paired_delta_statistics((0.2, 0.2, 0.2), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 0, 3)

    def test_one_sample_behaviors(self) -> None:
        for delta, counts in ((-0.5, (1, 0, 0)), (0.05, (0, 1, 0)), (0.5, (0, 0, 1))):
            summary = paired_delta_statistics((delta,), tie_tolerance=0.1)
            assert (summary.win_count, summary.tie_count, summary.loss_count) == counts

    def test_asymmetric_vector(self) -> None:
        summary = paired_delta_statistics((0.0, 0.1, 0.2, 0.3), tie_tolerance=0.1)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 2, 2)

    def test_integer_deltas_with_float_tolerance(self) -> None:
        summary = paired_delta_statistics((1, 2, -1, -2), tie_tolerance=1.5)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (1, 2, 1)

    def test_zero_tolerance(self) -> None:
        summary = paired_delta_statistics((0, -1, 1), tie_tolerance=0)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (1, 1, 1)


class TestPairedDeltaStatistics:
    def test_odd_median_golden(self) -> None:
        summary = paired_delta_statistics((0.2, -0.6, 0.5), tie_tolerance=0.0)
        assert summary.median_paired_delta == 0.2

    def test_even_median_golden(self) -> None:
        summary = paired_delta_statistics((0.2, -0.6, 0.5, -0.1), tie_tolerance=0.0)
        assert summary.median_paired_delta == 0.05

    def test_type7_p05_p95_golden(self) -> None:
        summary = paired_delta_statistics((-3, -2, -1, 1, 2, 3), tie_tolerance=0.0)
        assert summary.p05_paired_delta == -2.75
        assert summary.p95_paired_delta == 2.75

    def test_type7_p05_p95_odd_count(self) -> None:
        summary = paired_delta_statistics((1, 2, 3, 4, 5), tie_tolerance=0.0)
        # the mandated fsum interpolation can land 1 ulp from the exact
        # rational 6/5 and 24/5 (tie-to-even at the exact midpoint)
        _assert_within_one_ulp(summary.p05_paired_delta, float(Fraction(6, 5)))
        _assert_within_one_ulp(summary.p95_paired_delta, float(Fraction(24, 5)))

    def test_reverse_percentile_identity(self) -> None:
        summary = paired_delta_statistics((-3, -2, -1, 1, 2, 3), tie_tolerance=0.0)
        assert summary.p05_paired_delta == -summary.p95_paired_delta

    def test_best_worst_exactness(self) -> None:
        deltas = (0.2, -0.6, 0.5, -0.9, 0.4)
        summary = paired_delta_statistics(deltas, tie_tolerance=0.0)
        assert summary.worst_paired_delta == max(deltas)
        assert summary.best_paired_delta == min(deltas)

    def test_one_sample_statistics(self) -> None:
        summary = paired_delta_statistics((0.7,), tie_tolerance=0.0)
        assert summary.median_paired_delta == 0.7
        assert summary.p05_paired_delta == 0.7
        assert summary.p95_paired_delta == 0.7
        assert summary.worst_paired_delta == 0.7
        assert summary.best_paired_delta == 0.7

    def test_one_ulp_median_reference(self) -> None:
        summary = paired_delta_statistics((0.1, 0.2), tie_tolerance=0.0)
        reference = float((Fraction(0.1) + Fraction(0.2)) / 2)
        _assert_within_one_ulp(summary.median_paired_delta, reference)

    def test_one_ulp_p95_reference(self) -> None:
        summary = paired_delta_statistics((1.0, 1.5, 2.0), tie_tolerance=0.0)
        _assert_within_one_ulp(summary.p95_paired_delta, float(Fraction(39, 20)))

    def test_all_summary_fields_exposed_directly(self) -> None:
        summary = paired_delta_statistics((0.0,), tie_tolerance=0.0)
        assert summary.sample_count == 1
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 0)
        assert (summary.win_rate, summary.tie_rate, summary.loss_rate) == (0.0, 1.0, 0.0)
        assert summary.median_paired_delta == 0.0
        assert summary.p05_paired_delta == 0.0
        assert summary.p95_paired_delta == 0.0
        assert summary.worst_paired_delta == 0.0
        assert summary.best_paired_delta == 0.0

    def test_median_overflow_raises_overflow(self) -> None:
        with pytest.raises(OverflowError):
            paired_delta_statistics((1.7e308, 1.7e308), tie_tolerance=0.0)

    def test_caller_delta_tuple_never_mutated(self) -> None:
        deltas = (0.2, -0.6, 0.5)
        snapshot = tuple(deltas)
        paired_delta_statistics(deltas, tie_tolerance=0.0)
        assert deltas == snapshot

    @pytest.mark.parametrize("bad", _BAD_COLLECTIONS)
    def test_collection_type_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta_statistics(bad, tie_tolerance=0.0)  # type: ignore[arg-type]

    def test_empty_deltas_rejected(self) -> None:
        with pytest.raises(ValueError):
            paired_delta_statistics((), tie_tolerance=0.0)

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_delta_element_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            paired_delta_statistics((bad, 1.0), tie_tolerance=0.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_delta_raises_overflow(self, huge: int) -> None:
        with pytest.raises(OverflowError):
            paired_delta_statistics((huge, 1.0), tie_tolerance=0.0)

    @pytest.mark.parametrize("bad", _BAD_NON_NEGATIVE_SCALARS)
    def test_bad_tolerance_rejected(self, bad: object) -> None:
        with pytest.raises((ValueError, OverflowError)):
            paired_delta_statistics((0.0, 1.0), tie_tolerance=cast(Any, bad))

    def test_zero_tolerance_is_valid(self) -> None:
        summary = paired_delta_statistics((0.0, 0.1), tie_tolerance=0)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 1)

    def test_negative_zero_tolerance_is_accepted_as_zero(self) -> None:
        summary = paired_delta_statistics((0.0, 0.1), tie_tolerance=-0.0)
        assert (summary.win_count, summary.tie_count, summary.loss_count) == (0, 1, 1)


class TestSameSeedRegret:
    def test_minimize_golden(self) -> None:
        assert same_seed_regret((10, 5, 7), direction="minimize", normalization_scale=1) == (
            5.0,
            0.0,
            2.0,
        )

    def test_maximize_golden(self) -> None:
        assert same_seed_regret((10, 5, 7), direction="maximize", normalization_scale=1) == (
            0.0,
            5.0,
            3.0,
        )

    def test_reach_golden(self) -> None:
        assert same_seed_regret(
            (12, 8, 4), direction="reach", normalization_scale=2, target=10
        ) == (0.0, 0.0, 2.0)

    def test_tied_best_strategies_all_receive_exact_zero(self) -> None:
        assert same_seed_regret((5, 5, 9), direction="minimize", normalization_scale=1) == (
            0.0,
            0.0,
            4.0,
        )
        assert same_seed_regret(
            (12, 8, 12), direction="reach", normalization_scale=1, target=10
        ) == (0.0, 0.0, 0.0)

    def test_one_strategy(self) -> None:
        assert same_seed_regret((7,), direction="minimize", normalization_scale=1) == (0.0,)
        assert same_seed_regret((7,), direction="maximize", normalization_scale=1) == (0.0,)
        assert same_seed_regret((7,), direction="reach", normalization_scale=1, target=10) == (0.0,)

    def test_negative_raw_values(self) -> None:
        assert same_seed_regret((-5, -10, 3), direction="minimize", normalization_scale=1) == (
            5.0,
            0.0,
            13.0,
        )
        assert same_seed_regret((-5, -10, 3), direction="maximize", normalization_scale=1) == (
            8.0,
            13.0,
            0.0,
        )

    def test_scales_below_and_above_one(self) -> None:
        assert same_seed_regret((10, 5), direction="minimize", normalization_scale=0.5) == (
            10.0,
            0.0,
        )
        assert same_seed_regret((10, 5), direction="minimize", normalization_scale=2) == (
            2.5,
            0.0,
        )

    def test_strategy_order_is_preserved(self) -> None:
        assert same_seed_regret((7, 5, 10), direction="minimize", normalization_scale=1) == (
            2.0,
            0.0,
            5.0,
        )

    def test_every_strategy_participates_in_the_same_seed_comparator(self) -> None:
        assert same_seed_regret((10, 7), direction="minimize", normalization_scale=1) == (
            3.0,
            0.0,
        )
        assert same_seed_regret((10, 5, 7), direction="minimize", normalization_scale=1) == (
            5.0,
            0.0,
            2.0,
        )

    def test_regret_is_distinct_from_target_violation(self) -> None:
        # Both strategies achieve the minimize target 100 (violation 0.0 for
        # both), but A is comparatively worse than B on the same seed and
        # carries regret 5.0.
        regrets = same_seed_regret(
            (95, 90), direction="minimize", normalization_scale=1, target=100
        )
        assert regrets == (5.0, 0.0)
        violations = tuple(max(0.0, float(value) - 100.0) for value in (95, 90))
        assert violations == (0.0, 0.0)
        assert regrets != violations

    def test_regret_never_negative(self) -> None:
        for values in ((10, 5, 7), (-5, -10, 3), (0, 0, 0), (12, 8, 4)):
            for direction in _ALL_DIRECTIONS:
                target: int | float | None = 10 if direction == "reach" else None
                regrets = same_seed_regret(
                    values, direction=direction, normalization_scale=1, target=target
                )
                assert all(regret >= 0.0 for regret in regrets)
                assert 0.0 in regrets

    def test_integer_inputs_remain_unmodified(self) -> None:
        values = (10, 5, 7)
        snapshot = tuple(values)
        same_seed_regret(values, direction="minimize", normalization_scale=1)
        assert values == snapshot
        assert all(type(value) is int for value in values)

    @pytest.mark.parametrize("bad", _BAD_COLLECTIONS)
    def test_collection_type_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            same_seed_regret(bad, direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(ValueError):
            same_seed_regret((), direction="minimize", normalization_scale=1.0)

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_value_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            same_seed_regret((bad, 1.0), direction="minimize", normalization_scale=1.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_value_raises_overflow(self, huge: int) -> None:
        with pytest.raises(OverflowError):
            same_seed_regret((huge, 1.0), direction="minimize", normalization_scale=1.0)

    def test_reach_without_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            same_seed_regret((1.0, 2.0), direction="reach", normalization_scale=1.0)

    def test_arithmetic_overflow_raises_overflow(self) -> None:
        with pytest.raises(OverflowError):
            same_seed_regret((1.7e308, -1.7e308), direction="minimize", normalization_scale=1.0)
        with pytest.raises(OverflowError):
            same_seed_regret((10, 5), direction="minimize", normalization_scale=1e-308)
        with pytest.raises(OverflowError):
            same_seed_regret(
                (1.7e308, 1.0), direction="reach", normalization_scale=1.0, target=-1.7e308
            )


class TestWeightedAggregation:
    def test_objective_weighted_mean_golden(self) -> None:
        assert objective_weighted_mean_regret((0.5, 1.5, 2.5), weight=2) == 3.0

    def test_objective_weighted_mean_zero_weight(self) -> None:
        assert objective_weighted_mean_regret((0.5, 1.5, 2.5), weight=0) == 0.0

    def test_negative_zero_weight_is_accepted_as_zero(self) -> None:
        assert objective_weighted_mean_regret((0.5, 1.5, 2.5), weight=-0.0) == 0.0

    def test_objective_weighted_mean_fractional_reference(self) -> None:
        result = objective_weighted_mean_regret((1 / 3, 2 / 3, 1.0), weight=1 / 3)
        _assert_within_one_ulp(result, float(Fraction(2, 9)))

    def test_per_seed_total_golden(self) -> None:
        assert per_seed_total_weighted_regret((0.5, 1.5), (1, 2)) == 3.5

    def test_per_seed_total_zero_weights(self) -> None:
        assert per_seed_total_weighted_regret((0.5, 1.5), (0, 0)) == 0.0

    def test_total_regret_vector_golden(self) -> None:
        matrix = ((0.5, 1.0, 0.0), (0.25, 0.5, 0.75))
        assert total_regret_vector(matrix, (1, 2)) == (1.0, 2.0, 1.5)

    def test_total_regret_vector_all_zero_weights(self) -> None:
        matrix = ((0.5, 1.0, 0.0), (0.25, 0.5, 0.75))
        assert total_regret_vector(matrix, (0, 0)) == (0.0, 0.0, 0.0)

    def test_total_regret_vector_zero_individual_weight(self) -> None:
        matrix = ((0.5, 1.0, 0.0), (0.25, 0.5, 0.75))
        assert total_regret_vector(matrix, (0, 2)) == (0.5, 1.0, 1.5)

    def test_no_weight_renormalization(self) -> None:
        matrix = ((1.0,), (1.0,))
        # plain weighted sums; weights are never divided by their total
        assert total_regret_vector(matrix, (3, 3)) == (6.0,)
        assert objective_weighted_mean_regret((1.0, 1.0), weight=2) == 2.0

    def test_objective_order_is_significant(self) -> None:
        matrix_a = ((1.0,), (0.0,))
        matrix_b = ((0.0,), (1.0,))
        assert total_regret_vector(matrix_a, (1, 10)) == (1.0,)
        assert total_regret_vector(matrix_b, (1, 10)) == (10.0,)

    def test_total_regret_statistics_golden(self) -> None:
        summary = total_regret_statistics((1.0, 1.5, 2.0))
        assert summary.sample_count == 3
        assert summary.median_total_regret == 1.5
        assert summary.maximum_total_regret == 2.0
        _assert_within_one_ulp(summary.p95_total_regret, float(Fraction(39, 20)))

    def test_total_regret_statistics_even_median(self) -> None:
        summary = total_regret_statistics((1.0, 2.0))
        assert summary.median_total_regret == 1.5

    def test_total_regret_statistics_all_zero(self) -> None:
        summary = total_regret_statistics((0.0, 0.0, 0.0))
        assert summary.median_total_regret == 0.0
        assert summary.p95_total_regret == 0.0
        assert summary.maximum_total_regret == 0.0

    def test_common_seed_count_enforced(self) -> None:
        with pytest.raises(ValueError):
            total_regret_vector(((0.5, 1.0), (0.25,)), (1.0, 1.0))
        with pytest.raises(ValueError):
            total_regret_vector(((0.5, 1.0), (0.25, 1.0, 2.0)), (1.0, 1.0))

    def test_weights_count_must_match_objective_count(self) -> None:
        with pytest.raises(ValueError):
            total_regret_vector(((0.5, 1.0), (0.25, 1.0)), (1.0,))
        with pytest.raises(ValueError):
            total_regret_vector(((0.5, 1.0),), (1.0, 1.0))

    def test_empty_vectors_rejected(self) -> None:
        with pytest.raises(ValueError):
            total_regret_vector((), (1.0,))
        with pytest.raises(ValueError):
            total_regret_vector(((0.5,), ()), (1.0, 1.0))

    def test_negative_regret_inputs_rejected(self) -> None:
        with pytest.raises(ValueError):
            objective_weighted_mean_regret((-0.5, 1.0), weight=1.0)
        with pytest.raises(ValueError):
            per_seed_total_weighted_regret((-0.5, 1.0), (1.0, 1.0))
        with pytest.raises(ValueError):
            total_regret_vector(((-0.5, 1.0),), (1.0,))
        with pytest.raises(ValueError):
            total_regret_statistics((-0.5, 1.0))

    @pytest.mark.parametrize("bad", _BAD_NON_NEGATIVE_SCALARS)
    def test_bad_weight_rejected(self, bad: object) -> None:
        with pytest.raises((ValueError, OverflowError)):
            objective_weighted_mean_regret((0.5, 1.0), weight=cast(Any, bad))
        with pytest.raises((ValueError, OverflowError)):
            per_seed_total_weighted_regret((0.5, 1.0), (cast(Any, bad), 1.0))
        with pytest.raises((ValueError, OverflowError)):
            total_regret_vector(((0.5, 1.0),), (cast(Any, bad),))

    @pytest.mark.parametrize("bad", _BAD_COLLECTIONS)
    def test_collection_type_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            objective_weighted_mean_regret(bad, weight=1.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            per_seed_total_weighted_regret(bad, (1.0, 1.0))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            per_seed_total_weighted_regret((0.5, 1.0), bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            total_regret_vector(bad, (1.0,))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            total_regret_vector(((0.5,),), bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            total_regret_statistics(bad)  # type: ignore[arg-type]

    def test_row_type_and_empty_row_rejected(self) -> None:
        with pytest.raises(ValueError):
            total_regret_vector(([0.5, 1.0],), (1.0,))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            bad_row = cast("tuple[int | float, ...]", _TupleSubclass((0.5, 1.0)))
            total_regret_vector((bad_row,), (1.0,))

    @pytest.mark.parametrize("bad", _BAD_NUMERIC_SCALARS)
    def test_bad_regret_element_rejected(self, bad: object) -> None:
        with pytest.raises(ValueError):
            objective_weighted_mean_regret((bad, 1.0), weight=1.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            per_seed_total_weighted_regret((bad, 1.0), (1.0, 1.0))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            total_regret_vector(((bad, 1.0),), (1.0,))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            total_regret_statistics((bad, 1.0))  # type: ignore[arg-type]

    @pytest.mark.parametrize("huge", _OVERFLOW_NUMERIC_SCALARS)
    def test_unrepresentable_regret_raises_overflow(self, huge: int) -> None:
        with pytest.raises(OverflowError):
            objective_weighted_mean_regret((huge, 1.0), weight=1.0)
        with pytest.raises(OverflowError):
            per_seed_total_weighted_regret((huge, 1.0), (1.0, 1.0))
        with pytest.raises(OverflowError):
            total_regret_vector(((huge, 1.0),), (1.0,))
        with pytest.raises(OverflowError):
            total_regret_statistics((huge, 1.0))

    def test_arithmetic_overflow_raises_overflow(self) -> None:
        with pytest.raises(OverflowError):
            objective_weighted_mean_regret((1.7e308, 1.7e308), weight=1.0)
        with pytest.raises(OverflowError):
            per_seed_total_weighted_regret((1e308,), (1e308,))
        with pytest.raises(OverflowError):
            total_regret_vector(((1e308,),), (1e308,))


class TestPurityAndDeterminism:
    def test_paired_delta_repeated_calls_identical(self) -> None:
        first = paired_delta(5, 3, direction="minimize", normalization_scale=10)
        second = paired_delta(5, 3, direction="minimize", normalization_scale=10)
        assert first == second

    def test_vector_repeated_calls_identical(self) -> None:
        first = paired_delta_vector(
            (5, 2, 8), (3, 8, 3), direction="minimize", normalization_scale=10
        )
        second = paired_delta_vector(
            (5, 2, 8), (3, 8, 3), direction="minimize", normalization_scale=10
        )
        assert first == second

    def test_statistics_repeated_calls_identical(self) -> None:
        first = paired_delta_statistics((-0.2, 0.1, 0.4), tie_tolerance=0.1)
        second = paired_delta_statistics((-0.2, 0.1, 0.4), tie_tolerance=0.1)
        assert first == second

    def test_regret_repeated_calls_identical(self) -> None:
        first = same_seed_regret((10, 5, 7), direction="minimize", normalization_scale=1)
        second = same_seed_regret((10, 5, 7), direction="minimize", normalization_scale=1)
        assert first == second

    def test_aggregation_repeated_calls_identical(self) -> None:
        matrix = ((0.5, 1.0, 0.0), (0.25, 0.5, 0.75))
        first = total_regret_vector(matrix, (1, 2))
        second = total_regret_vector(matrix, (1, 2))
        assert first == second
        assert total_regret_statistics(first) == total_regret_statistics(second)
        assert objective_weighted_mean_regret(
            (0.5, 1.0), weight=2
        ) == objective_weighted_mean_regret((0.5, 1.0), weight=2)
        assert per_seed_total_weighted_regret((0.5, 1.0), (1.0, 2.0)) == (
            per_seed_total_weighted_regret((0.5, 1.0), (1.0, 2.0))
        )

    def test_no_input_mutation_across_all_public_functions(self) -> None:
        values_a = (5, 2, 8)
        values_b = (3, 8, 3)
        deltas = (0.2, -0.6, 0.5)
        regrets = (0.5, 1.0)
        weights = (1, 2)
        matrix = ((0.5, 1.0), (0.25, 0.75))
        snapshots = {
            "values_a": tuple(values_a),
            "values_b": tuple(values_b),
            "deltas": tuple(deltas),
            "regrets": tuple(regrets),
            "weights": tuple(weights),
            "matrix": tuple(tuple(row) for row in matrix),
        }
        paired_delta_vector(values_a, values_b, direction="minimize", normalization_scale=10)
        paired_delta_statistics(deltas, tie_tolerance=0.1)
        same_seed_regret(values_a, direction="minimize", normalization_scale=1)
        objective_weighted_mean_regret(regrets, weight=2)
        per_seed_total_weighted_regret(regrets, weights)
        total_regret_vector(matrix, weights)
        total_regret_statistics(regrets)
        assert values_a == snapshots["values_a"]
        assert values_b == snapshots["values_b"]
        assert deltas == snapshots["deltas"]
        assert regrets == snapshots["regrets"]
        assert weights == snapshots["weights"]
        assert matrix == snapshots["matrix"]
        assert all(type(value) is int for value in values_a)
        assert all(type(value) is int for value in weights)
