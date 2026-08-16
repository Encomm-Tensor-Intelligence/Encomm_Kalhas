"""Deterministic empirical quantile and tail-statistics primitives (KALHAS).

This module defines the exact finite-sample statistical primitives that
later campaign-outcome artifacts consume: the Hyndman-Fan Type 7
empirical quantile for the supported percentiles and the fixed-alpha
fractional empirical tail mean in both orientations. The module is
domain-neutral, pure, and deterministic: it uses only the Python
standard library, reads no wall clock, uses no randomness, network,
providers, filesystem, store, API, adapters, or domain packs, and never
mutates any input.

Public constants:

- ``EMPIRICAL_QUANTILE_ALGORITHM == "hyndman-fan-type-7-v1"``
- ``EMPIRICAL_TAIL_ALGORITHM == "empirical-fractional-tail-mean-v1"``
- ``EMPIRICAL_TAIL_ALPHA == 0.95`` (fixed; callers cannot supply an alpha)

Common sample validation (enforced independently by every public
function):

- ``samples`` must be an actual plain ``tuple`` instance (exact type;
  tuple subclasses are rejected);
- the tuple must be non-empty;
- every value must have exact type ``int`` or ``float`` - ``bool`` is
  rejected even though it subclasses ``int``, and strings, ``Decimal``,
  ``None``, containers, and arbitrary numeric-like objects are rejected;
- float values must be finite (NaN and Infinity are rejected);
- after the exact-type and finite checks, every sample is independently
  proven convertible to a finite float before any percentile or tail
  selection begins - an unrepresentable integer raises ``OverflowError``
  even when it would fall outside the selected quantile/tail;
- no coercion, clipping, repair, normalization, or rounding happens;
- input order and input objects are never mutated; valid integer and
  float samples may be mixed freely.

Invalid shape, type, or non-finite input raises ``ValueError``. When an
exact integer cannot be converted to a finite float, or an intermediate
finite floating-point representation is impossible, the function raises
``OverflowError`` - the conversion proof covers every sample in the
tuple, regardless of whether that sample would participate in the
requested percentile, upper tail, or lower tail; no partial selection,
sorting, or arithmetic begins before the complete tuple passes
validation. A public function never returns NaN or Infinity.

Type 7 empirical quantile (:func:`empirical_type7_quantile`): only
percentiles 5, 25, 75, and 95 are supported; ``bool`` and every other
value raise ``ValueError``. A detached copy of the exact numeric samples
is sorted in ascending numeric order; the supplied tuple is never
reordered or mutated. For n samples and integer percentile p the index
is computed with pure integer arithmetic (never binary floating-point
``p / 100``):

::

    index_numerator = (n - 1) * p
    lower_index = index_numerator // 100
    remainder = index_numerator % 100
    upper_index = min(lower_index + 1, n - 1)

If ``remainder == 0`` the result is ``float(sorted_samples[lower_index])``;
otherwise deterministic linear interpolation:

::

    lower_weight = (100 - remainder) / 100
    upper_weight = remainder / 100
    result = math.fsum(
        (
            float(sorted_samples[lower_index]) * lower_weight,
            float(sorted_samples[upper_index]) * upper_weight,
        )
    )

This is the exact finite-sample Hyndman-Fan Type 7 definition for the
supported percentiles; a one-sample collection returns that sample for
all four percentiles.

Fractional empirical tail mean (:func:`empirical_upper_tail_mean_95` /
:func:`empirical_lower_tail_mean_95`): the alpha is fixed at 0.95 and
every sample carries equal empirical mass, so the adverse tail has exact
mass ``5/100``. For n samples:

::

    tail_units = 5 * n
    full_count = tail_units // 100
    remainder = tail_units % 100

The upper-tail function sorts descending; the lower-tail function sorts
ascending. Each of the first ``full_count`` samples receives weight
``100 / tail_units``; when ``remainder`` is non-zero the next boundary
sample receives weight ``remainder / tail_units``. The result is
``math.fsum`` over the weighted float values. This gives: n=1 the only
sample; n=20 the single worst sample; n=100 the arithmetic mean of the
worst five samples; non-multiples of 20 the full worst observations plus
the exact fractional empirical mass of the next boundary observation. No
``ceil(0.05 * n)``, no unweighted selection, no library percentile
interpolation, no NumPy or pandas, no bootstrap, and no random
resampling. The result is always finite or the function fails with
``OverflowError``.
"""

from __future__ import annotations

import math
from typing import Literal, cast

#: Algorithm identifier for the exact finite-sample Hyndman-Fan Type 7
#: empirical quantile definition implemented by
#: :func:`empirical_type7_quantile`.
EMPIRICAL_QUANTILE_ALGORITHM = "hyndman-fan-type-7-v1"

#: Algorithm identifier for the exact finite-sample fractional empirical
#: tail-mean definition implemented by :func:`empirical_upper_tail_mean_95`
#: and :func:`empirical_lower_tail_mean_95`.
EMPIRICAL_TAIL_ALGORITHM = "empirical-fractional-tail-mean-v1"

#: The fixed adverse-tail mass alpha. Callers cannot supply another alpha;
#: every sample carries equal empirical mass and the adverse tail has
#: exact mass ``5/100``.
EMPIRICAL_TAIL_ALPHA = 0.95

#: The only supported Type 7 percentiles (exact integers only).
_SUPPORTED_PERCENTILES = (5, 25, 75, 95)


def _validated_samples(samples: object) -> tuple[int | float, ...]:
    """Strictly validate the common sample contract and return the samples.

    Enforced independently by every public primitive: ``samples`` must be
    an actual plain ``tuple`` instance (exact type; tuple subclasses are
    rejected), non-empty, with every value of exact type ``int`` or
    ``float`` - booleans are rejected even though they subclass ``int``,
    and strings, ``Decimal``, ``None``, containers, and arbitrary
    numeric-like objects are rejected - and every float finite. After
    those checks every sample is independently proven convertible to a
    finite float before the function returns: an integer whose conversion
    raises ``OverflowError`` fails with ``OverflowError`` immediately, and
    a conversion that is not finite also fails with ``OverflowError``.
    Validation covers every sample regardless of whether that sample
    would participate in the requested percentile, upper tail, or lower
    tail; no partial selection, sorting, or arithmetic begins before the
    complete tuple passes validation. Nothing is coerced, clipped,
    repaired, normalized, rounded, or mutated. Invalid input raises
    ``ValueError``.
    """
    if type(samples) is not tuple:
        raise ValueError("samples must be an actual tuple")
    values = samples
    if not values:
        raise ValueError("samples must be non-empty")
    for value in values:
        if type(value) is bool or (type(value) is not int and type(value) is not float):
            raise ValueError("every sample must have exact type int or float")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("float samples must be finite")
        converted = float(value)
        if not math.isfinite(converted):
            raise OverflowError("sample cannot be represented as a finite float")
    return cast(tuple[int | float, ...], values)


def _validated_percentile(percentile: object) -> None:
    """Reject every percentile except the exact supported integers 5, 25, 75, 95.

    Booleans (which subclass ``int``) and floats such as ``5.0`` are
    rejected; only the exact integer literals are accepted.
    """
    if type(percentile) is not int or percentile not in _SUPPORTED_PERCENTILES:
        raise ValueError("percentile must be exactly 5, 25, 75, or 95")


def empirical_type7_quantile(
    samples: tuple[int | float, ...],
    percentile: Literal[5, 25, 75, 95],
) -> float:
    """The exact finite-sample Hyndman-Fan Type 7 empirical quantile.

    Returns the deterministic Type 7 empirical quantile of the exact
    numeric samples for one of the supported percentiles (5, 25, 75, or
    95; anything else - including booleans and floats such as ``5.0`` -
    raises ``ValueError``). A detached ascending sort of the exact
    samples is used and the supplied tuple is never reordered or mutated.
    The index is computed with the mandatory integer numerator/remainder
    formulation - never binary floating-point ``p / 100`` - and
    interpolation, when required, is the deterministic weighted
    ``math.fsum`` linear interpolation defined in the module docstring.
    A one-sample collection returns that sample for all four percentiles.
    Common sample validation applies first; invalid shape, type, or
    non-finite input raises ``ValueError``, and an integer that cannot be
    converted to a finite float (or any impossible finite intermediate
    representation) raises ``OverflowError``. NaN or Infinity is never
    returned.
    """
    _validated_samples(samples)
    _validated_percentile(percentile)
    ordered = sorted(samples)
    n = len(ordered)
    index_numerator = (n - 1) * percentile
    lower_index = index_numerator // 100
    remainder = index_numerator % 100
    upper_index = min(lower_index + 1, n - 1)
    if remainder == 0:
        result = float(ordered[lower_index])
    else:
        lower_weight = (100 - remainder) / 100
        upper_weight = remainder / 100
        result = math.fsum(
            (
                float(ordered[lower_index]) * lower_weight,
                float(ordered[upper_index]) * upper_weight,
            )
        )
    if not math.isfinite(result):
        raise OverflowError("quantile result is not finite")
    return result


def _empirical_fractional_tail_mean(samples: tuple[int | float, ...], *, upper: bool) -> float:
    """The fixed-alpha fractional empirical tail mean in one orientation.

    Computes the exact empirical tail mean with fixed mass
    ``EMPIRICAL_TAIL_ALPHA == 0.95``: ``tail_units = 5 * n``,
    ``full_count = tail_units // 100``, ``remainder = tail_units % 100``;
    the first ``full_count`` samples of the orientation-ordered copy each
    receive weight ``100 / tail_units`` and, when ``remainder`` is
    non-zero, the next boundary sample receives weight
    ``remainder / tail_units``. ``upper=True`` sorts descending,
    ``upper=False`` sorts ascending. The result is ``math.fsum`` over the
    weighted float values and is always finite or the function fails with
    ``OverflowError``. ``samples`` must already be validated by the
    public caller.
    """
    ordered = sorted(samples, reverse=upper)
    n = len(ordered)
    tail_units = 5 * n
    full_count = tail_units // 100
    remainder = tail_units % 100
    full_weight = 100 / tail_units
    terms: list[float] = []
    for position in range(full_count):
        terms.append(float(ordered[position]) * full_weight)
    if remainder:
        terms.append(float(ordered[full_count]) * (remainder / tail_units))
    result = math.fsum(terms)
    if not math.isfinite(result):
        raise OverflowError("tail mean result is not finite")
    return result


def empirical_upper_tail_mean_95(samples: tuple[int | float, ...]) -> float:
    """The fixed-alpha 0.95 fractional empirical upper-tail mean.

    The exact finite-sample adverse upper tail: the samples are sorted
    descending and the fractional tail mean of the worst empirical mass
    (``5/100`` of the total, per :func:`_empirical_fractional_tail_mean`)
    is returned in the samples' original unit. Common sample validation
    applies first (``ValueError`` on invalid shape, type, or non-finite
    input; ``OverflowError`` when an exact integer cannot be converted to
    a finite float or no finite intermediate representation exists). The
    result is finite or the function fails; NaN or Infinity is never
    returned and the input tuple is never mutated.
    """
    _validated_samples(samples)
    return _empirical_fractional_tail_mean(samples, upper=True)


def empirical_lower_tail_mean_95(samples: tuple[int | float, ...]) -> float:
    """The fixed-alpha 0.95 fractional empirical lower-tail mean.

    The exact finite-sample adverse lower tail: the samples are sorted
    ascending and the fractional tail mean of the worst empirical mass
    (``5/100`` of the total, per :func:`_empirical_fractional_tail_mean`)
    is returned in the samples' original unit. Common sample validation
    applies first (``ValueError`` on invalid shape, type, or non-finite
    input; ``OverflowError`` when an exact integer cannot be converted to
    a finite float or no finite intermediate representation exists). The
    result is finite or the function fails; NaN or Infinity is never
    returned and the input tuple is never mutated.
    """
    _validated_samples(samples)
    return _empirical_fractional_tail_mean(samples, upper=False)


__all__ = [
    "EMPIRICAL_QUANTILE_ALGORITHM",
    "EMPIRICAL_TAIL_ALGORITHM",
    "EMPIRICAL_TAIL_ALPHA",
    "empirical_type7_quantile",
    "empirical_upper_tail_mean_95",
    "empirical_lower_tail_mean_95",
]
