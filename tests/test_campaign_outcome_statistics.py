"""Tests for the deterministic empirical quantile and tail-statistics primitives.

Phase 26 statistics-slice tests for
``kalhas/application/campaign_outcome_statistics.py``: the exact
Hyndman-Fan Type 7 empirical quantile (percentiles 5/25/75/95), the
fixed-alpha 0.95 fractional empirical upper/lower tail means, the strict
common sample validation (exact tuple type, non-empty, exact int/float
values, bool/string/None/container/Decimal/complex/non-finite rejection,
no coercion, no mutation), the ``OverflowError`` contract for huge
integers, the exact public constant/``__all__`` surface, and the
source/import boundary proving the module imports only the Python
standard library with no filesystem, network, adapter, API, store,
domain-pack, NEXUS, LEGION, wall-clock, or randomness dependency.

Golden results use exact equality whenever the result is exactly
representable; mathematically non-terminating fractional results use
one-ULP assertions - the result must differ from the correctly rounded
rational reference by at most one representable float step
(``abs(actual - expected) <= math.ulp(expected)``).
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from kalhas.application.campaign_outcome_statistics import (
    EMPIRICAL_QUANTILE_ALGORITHM,
    EMPIRICAL_TAIL_ALGORITHM,
    EMPIRICAL_TAIL_ALPHA,
    empirical_lower_tail_mean_95,
    empirical_type7_quantile,
    empirical_upper_tail_mean_95,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_outcome_statistics.py"
)

_PERCENTILES: tuple[Literal[5, 25, 75, 95], ...] = (5, 25, 75, 95)


def _quantile95(samples: tuple[int | float, ...]) -> float:
    return empirical_type7_quantile(samples, 95)


def _quantile5(samples: tuple[int | float, ...]) -> float:
    return empirical_type7_quantile(samples, 5)


def _upper_tail(samples: tuple[int | float, ...]) -> float:
    return empirical_upper_tail_mean_95(samples)


def _lower_tail(samples: tuple[int | float, ...]) -> float:
    return empirical_lower_tail_mean_95(samples)


_ALL_CALLABLES = (
    pytest.param(_quantile95, id="type7-p95"),
    pytest.param(_upper_tail, id="upper-tail-mean"),
    pytest.param(_lower_tail, id="lower-tail-mean"),
)

#: The three public primitives at percentile 5 for the
#: unrepresentable-integer adversarial matrix.
_OVERFLOW_CALLABLES = (
    pytest.param(_quantile5, id="type7-p5"),
    pytest.param(_upper_tail, id="upper-tail-mean"),
    pytest.param(_lower_tail, id="lower-tail-mean"),
)


def _assert_within_one_ulp(actual: float, expected: float) -> None:
    """Prove the result differs from the correctly rounded rational reference
    by at most one representable float step (``math.ulp``)."""
    assert abs(actual - expected) <= math.ulp(expected)


class TestPublicSurface:
    def test_exact_public_constants(self) -> None:
        values = (EMPIRICAL_QUANTILE_ALGORITHM, EMPIRICAL_TAIL_ALGORITHM, EMPIRICAL_TAIL_ALPHA)
        assert values == (
            "hyndman-fan-type-7-v1",
            "empirical-fractional-tail-mean-v1",
            0.95,
        )

    def test_exact_public_all(self) -> None:
        import kalhas.application.campaign_outcome_statistics as module

        assert module.__all__ == [
            "EMPIRICAL_QUANTILE_ALGORITHM",
            "EMPIRICAL_TAIL_ALGORITHM",
            "EMPIRICAL_TAIL_ALPHA",
            "empirical_type7_quantile",
            "empirical_upper_tail_mean_95",
            "empirical_lower_tail_mean_95",
        ]
        for name in module.__all__:
            assert hasattr(module, name)


class TestType7QuantileGolden:
    def test_one_sample_returns_the_sample_for_every_percentile(self) -> None:
        for percentile in _PERCENTILES:
            assert empirical_type7_quantile((7,), percentile) == 7.0

    def test_odd_sample_count_golden_vector(self) -> None:
        samples = (1, 2, 3, 4, 5)
        # 6/5 and 24/5 are mathematically non-terminating in binary; the
        # mandated fsum interpolation can land 1 ulp from the correctly
        # rounded rational reference, so those two use the one-ULP bound.
        _assert_within_one_ulp(empirical_type7_quantile(samples, 5), 1.2)
        assert empirical_type7_quantile(samples, 25) == 2.0
        assert empirical_type7_quantile(samples, 75) == 4.0
        _assert_within_one_ulp(empirical_type7_quantile(samples, 95), 4.8)

    def test_even_sample_count_golden_vector(self) -> None:
        samples = (0, 10, 20, 30)
        assert empirical_type7_quantile(samples, 5) == 1.5
        assert empirical_type7_quantile(samples, 25) == 7.5
        assert empirical_type7_quantile(samples, 75) == 22.5
        assert empirical_type7_quantile(samples, 95) == 28.5

    def test_two_sample_short_tail_interpolation(self) -> None:
        samples = (10, 20)
        assert empirical_type7_quantile(samples, 5) == 10.5
        assert empirical_type7_quantile(samples, 25) == 12.5
        assert empirical_type7_quantile(samples, 75) == 17.5
        assert empirical_type7_quantile(samples, 95) == 19.5

    def test_repeated_values(self) -> None:
        for percentile in _PERCENTILES:
            assert empirical_type7_quantile((4, 4, 4, 4), percentile) == 4.0

    def test_negative_values(self) -> None:
        samples = (-5, -4, -3, -2, -1)
        _assert_within_one_ulp(empirical_type7_quantile(samples, 5), -4.8)
        assert empirical_type7_quantile(samples, 25) == -4.0
        assert empirical_type7_quantile(samples, 75) == -2.0
        _assert_within_one_ulp(empirical_type7_quantile(samples, 95), -1.2)

    def test_unsorted_input_uses_numeric_order(self) -> None:
        samples = (5, 3, 1, 2, 4)
        _assert_within_one_ulp(empirical_type7_quantile(samples, 5), 1.2)
        assert empirical_type7_quantile(samples, 25) == 2.0
        assert empirical_type7_quantile(samples, 75) == 4.0
        _assert_within_one_ulp(empirical_type7_quantile(samples, 95), 4.8)

    def test_mixed_int_float_input(self) -> None:
        samples = (1, 2.5, 3, 4.5, 6)
        _assert_within_one_ulp(empirical_type7_quantile(samples, 5), 1.3)
        assert empirical_type7_quantile(samples, 25) == 2.5
        assert empirical_type7_quantile(samples, 75) == 4.5
        _assert_within_one_ulp(empirical_type7_quantile(samples, 95), 5.7)

    def test_repeated_calls_return_identical_results(self) -> None:
        samples = (5, 3, 1, 2, 4)
        for percentile in _PERCENTILES:
            assert empirical_type7_quantile(samples, percentile) == empirical_type7_quantile(
                samples, percentile
            )

    def test_input_tuple_remains_unchanged(self) -> None:
        samples = (5, 3, 1, 2, 4)
        empirical_type7_quantile(samples, 5)
        empirical_type7_quantile(samples, 25)
        empirical_type7_quantile(samples, 75)
        empirical_type7_quantile(samples, 95)
        assert samples == (5, 3, 1, 2, 4)


class TestTailMeanGolden:
    def test_one_sample_returns_the_only_sample(self) -> None:
        assert empirical_upper_tail_mean_95((7,)) == 7.0
        assert empirical_lower_tail_mean_95((7,)) == 7.0

    def test_two_samples_single_observation_tail(self) -> None:
        assert empirical_upper_tail_mean_95((1, 2)) == 2.0
        assert empirical_lower_tail_mean_95((1, 2)) == 1.0

    def test_repeated_values(self) -> None:
        assert empirical_upper_tail_mean_95((5, 5, 5, 5, 5)) == 5.0
        assert empirical_lower_tail_mean_95((5, 5, 5, 5, 5)) == 5.0

    def test_negative_values(self) -> None:
        samples = (-5, -4, -3, -2, -1)
        assert empirical_upper_tail_mean_95(samples) == -1.0
        assert empirical_lower_tail_mean_95(samples) == -5.0

    def test_mixed_int_float_values(self) -> None:
        samples = (1, 2.5, 3.5, 4)
        assert empirical_upper_tail_mean_95(samples) == 4.0
        assert empirical_lower_tail_mean_95(samples) == 1.0

    def test_n20_exact_single_observation_tail(self) -> None:
        assert empirical_upper_tail_mean_95(tuple(range(1, 21))) == 20.0
        assert empirical_lower_tail_mean_95(tuple(range(1, 21))) == 1.0

    def test_n100_exact_five_observation_mean(self) -> None:
        assert empirical_upper_tail_mean_95(tuple(range(1, 101))) == 98.0
        assert empirical_lower_tail_mean_95(tuple(range(1, 101))) == 3.0

    def test_n21_fractional_boundary(self) -> None:
        expected_upper = (100 * 21 + 5 * 20) / 105
        expected_lower = (100 * 1 + 5 * 2) / 105
        _assert_within_one_ulp(empirical_upper_tail_mean_95(tuple(range(1, 22))), expected_upper)
        _assert_within_one_ulp(empirical_lower_tail_mean_95(tuple(range(1, 22))), expected_lower)

    def test_n41_fractional_boundary_with_two_full_observations(self) -> None:
        expected_upper = (100 * 41 + 100 * 40 + 5 * 39) / 205
        expected_lower = (100 * 1 + 100 * 2 + 5 * 3) / 205
        _assert_within_one_ulp(empirical_upper_tail_mean_95(tuple(range(1, 42))), expected_upper)
        _assert_within_one_ulp(empirical_lower_tail_mean_95(tuple(range(1, 42))), expected_lower)

    def test_upper_and_lower_orientation(self) -> None:
        samples = (10, 20, 30)
        assert empirical_upper_tail_mean_95(samples) == 30.0
        assert empirical_lower_tail_mean_95(samples) == 10.0

    def test_repeated_calls_return_identical_results(self) -> None:
        samples = (5, 3, 1, 2, 4)
        assert empirical_upper_tail_mean_95(samples) == empirical_upper_tail_mean_95(samples)
        assert empirical_lower_tail_mean_95(samples) == empirical_lower_tail_mean_95(samples)

    def test_input_tuple_remains_unchanged(self) -> None:
        samples = (5, 3, 1, 2, 4)
        empirical_upper_tail_mean_95(samples)
        empirical_lower_tail_mean_95(samples)
        assert samples == (5, 3, 1, 2, 4)


class TestCommonValidation:
    @pytest.mark.parametrize("function", _ALL_CALLABLES)
    @pytest.mark.parametrize(
        "invalid_samples",
        (
            pytest.param((), id="empty-tuple"),
            pytest.param(cast(Any, [1, 2, 3]), id="list-not-tuple"),
            pytest.param(cast(Any, (True, 1, 2)), id="bool-sample"),
            pytest.param(cast(Any, (1, False)), id="bool-sample-second"),
            pytest.param(cast(Any, ("5", 1)), id="string-sample"),
            pytest.param(cast(Any, (1, None)), id="none-sample"),
            pytest.param(cast(Any, (1, [2])), id="list-container-sample"),
            pytest.param(cast(Any, (1, (2, 3))), id="tuple-container-sample"),
            pytest.param(cast(Any, ({1: 2}, 3)), id="dict-container-sample"),
            pytest.param(cast(Any, (1, Decimal("1.5"))), id="decimal-sample"),
            pytest.param(cast(Any, (1, 2j)), id="complex-sample"),
            pytest.param((1.0, float("nan")), id="nan-sample"),
            pytest.param((1.0, float("inf")), id="positive-infinity-sample"),
            pytest.param((1.0, float("-inf")), id="negative-infinity-sample"),
        ),
    )
    def test_invalid_samples_rejected(
        self,
        function: Callable[[tuple[int | float, ...]], float],
        invalid_samples: Any,
    ) -> None:
        with pytest.raises(ValueError):
            function(invalid_samples)

    def test_tuple_subclass_rejected(self) -> None:
        class _TupleSubclass(tuple[int, ...]):
            pass

        subclassed = cast(Any, _TupleSubclass((1, 2)))
        for function in (_quantile95, _upper_tail, _lower_tail):
            with pytest.raises(ValueError):
                function(subclassed)

    @pytest.mark.parametrize("function", _OVERFLOW_CALLABLES)
    @pytest.mark.parametrize(
        "overflow_samples",
        (
            pytest.param((10**400,), id="single-huge-integer"),
            pytest.param((10**400, 10**400), id="all-huge-integers"),
            pytest.param((1, 10**400), id="huge-integer-last-position"),
            pytest.param((10**400, 1), id="huge-integer-first-position"),
            pytest.param((1, 10**400, 2), id="huge-integer-middle-position"),
            pytest.param((1, -(10**400)), id="negative-huge-integer-last-position"),
            pytest.param((-(10**400), 1), id="negative-huge-integer-first-position"),
        ),
    )
    def test_huge_integer_overflow_raises(
        self,
        function: Callable[[tuple[int | float, ...]], float],
        overflow_samples: Any,
    ) -> None:
        # The common validation proves every sample convertible to a
        # finite float BEFORE any percentile or tail selection, so an
        # unrepresentable integer must be rejected at the first, middle,
        # and last positions even when it would fall outside the selected
        # quantile/tail.
        with pytest.raises(OverflowError):
            function(overflow_samples)

    @pytest.mark.parametrize("function", _ALL_CALLABLES)
    def test_large_finite_floats_never_become_non_finite(
        self, function: Callable[[tuple[int | float, ...]], float]
    ) -> None:
        samples = (1e308, 1e308)
        result = function(samples)
        assert result == 1e308
        assert math.isfinite(result)


class TestType7QuantileValidation:
    @pytest.mark.parametrize(
        "percentile",
        (
            pytest.param(cast(Any, 0), id="zero"),
            pytest.param(cast(Any, 50), id="fifty"),
            pytest.param(cast(Any, 100), id="hundred"),
            pytest.param(cast(Any, 5.0), id="float-five"),
            pytest.param(cast(Any, True), id="bool-true"),
            pytest.param(cast(Any, False), id="bool-false"),
            pytest.param(cast(Any, "95"), id="string"),
            pytest.param(cast(Any, None), id="none"),
        ),
    )
    def test_invalid_percentile_rejected(self, percentile: Any) -> None:
        with pytest.raises(ValueError):
            empirical_type7_quantile((1, 2, 3), percentile)

    def test_remainder_zero_path_with_large_float(self) -> None:
        assert empirical_type7_quantile((1e308,), 75) == 1e308


class TestModuleBoundaries:
    def test_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        modules = _imported_modules(tree)
        assert modules == {"__future__", "math", "typing"}
        module_paths = _imported_module_paths(tree)
        assert not any(path.startswith("kalhas") for path in module_paths)
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
