"""Deterministic integer-only world-realization sampler (Phase 24).

Algorithm version ``sha256-counter-v1`` with ``rational-round-half-even``
Q64.64 quantization. This module is the **only** place that samples
uncertainty, and it is pure: no wall clock, no global RNG, no
``random.seed``, no process hash, no UUID, no network, no filesystem,
no provider, no strategy input, and **no libm transcendental calls**.

Design summary (fully specified, no implementation-time decisions):

- One SHA-256 digest per consumed word. The canonical payload is the
  canonical JSON of ``{domain, draw_index, sampler_version,
  seed_content_hash, uncertainty_binding_content_hash,
  world_content_hash}`` with the fixed domain-separation literal
  ``"kalhas/world-realization-v1"``; the word is the first 8 bytes of
  the digest interpreted big-endian.
- Every declared parameter is converted to Q64.64 (``2**64``
  fractional bits) by **exact rational round-half-even quantization**
  via ``float.as_integer_ratio()`` and integer ``divmod`` - never by
  ``value * 2**64`` float multiplication. ``1e-10`` therefore quantizes
  to its correctly rounded fixed value, and exact half ties round to
  even for both signs.
- The open-uniform input for log/Box-Muller transforms is
  ``u_fix = word + 1`` (i.e. ``u = (word + 1) / 2**64`` in
  ``[2**-64, 1]``), which is **structurally never zero** (``log(0)`` is
  unreachable) and reaches ``u = 1`` only at ``word = 2**64 - 1`` where
  ``log(1) = 0`` exactly and the Box-Muller radius is zero. The
  documented tiny upward bias of this mapping is ``2**-65``.
- ``sqrt`` uses ``math.isqrt`` (exact, arbitrary-precision integer
  square root). ``log`` uses a fixed 32-term atanh series; ``exp`` is
  reduced by ``ln 2`` - ``k = floor(x / ln2)``, ``r = x - k*ln2`` in
  ``[0, ln2)``, ``exp(x) = 2**k * exp(r)`` with a fixed 24-term Horner
  (the shift multiplies by ``2**k``, which is mathematically correct
  for this decomposition) - and ``cos`` uses quadrant reduction plus a
  fixed 14-term Horner. Every division and right shift uses **floor
  semantics** (Python ``//`` and ``>>``), including for negative
  operands; this is part of the versioned algorithm.
- ``LN2_FIXED``, ``PI_FIXED``, ``TWO_PI_FIXED``, ``Z_MAX_FIXED``, and
  ``LN_RAW_MAX_FIXED`` are **frozen integer literals** derived from
  exact reference digits - never from ``math.log``/``math.pi``/Decimal
  (platform libm is not correctly rounded; e.g. on this platform
  ``math.log(2.0)`` differs from the exact constant by 428 Q64.64
  units).
- Resource safety is explicit: parameters are magnitude-capped before
  any multiplication; ``exp`` rejects ``k > 1024`` **before** any shift
  and returns exactly 0 for ``k < -65``; the raw sample must satisfy
  ``abs(value_fix) <= MAX_FINITE_FIXED`` **before** clipping, and
  clipping can never rescue a non-finite/unrepresentable raw value.
- The normal ``z_fix`` is invariant-checked against the exact
  deterministic maximum ``Z_MAX_FIXED``; a violation fails safely.

Numeric representation is preserved end to end: continuous families
always record float raws; a discrete sample preserves the exact
declared selected value type (declared ``1`` stays ``int 1``, declared
``1.0`` stays ``float 1.0``); clipping replaces a number-kind value
with the exact stored bound type; integer targets always finish as
exact ``int`` after the declared rounding policy.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    DistributionSpecification,
    LognormalDistribution,
    NormalDistribution,
    TriangularDistribution,
    UniformDistribution,
)

SAMPLER_VERSION: Literal["sha256-counter-v1"] = "sha256-counter-v1"
QUANTIZATION_POLICY: Literal["rational-round-half-even"] = "rational-round-half-even"
QUANTIZATION_FRACTION_BITS: Literal[64] = 64

#: Q64.64 fixed-point scale: 2**64 fractional bits.
S = 1 << 64

#: Frozen integer literals, derived from exact reference digits with
#: round-half-even quantization (see module docstring). Never computed
#: through libm at runtime.
LN2_FIXED = 12786308645202655660  # hex 0xB17217F7D1CF79AC
PI_FIXED = 57952155664616982739  # hex 0x3243F6A8885A308D3
TWO_PI_FIXED = 2 * PI_FIXED  # hex 0x6487ED5110B4611A6
#: Exact deterministic maximum Box-Muller radius (and therefore the
#: maximum |z|) in Q64.64: isqrt(128 * LN2_FIXED << 64).
Z_MAX_FIXED = 173755050841308499932  # hex 0x96B55F2257E218FDC
#: ln(709.78) boundary for the lognormal static finite-raw range check,
#: as an exact Q64.64 literal of the decimal 709.78.
LN_RAW_MAX_FIXED = 13093130008637565546004  # hex 0x2C5C7AE147AE147AE14
#: Largest finite double (1.7976931348623157e308) in Q64.64. Any fixed
#: value with a larger magnitude cannot be recorded as a finite raw
#: sample.
MAX_FINITE_FIXED = (2**53 - 1) << 1035

#: Fixed iteration counts of the versioned primitives.
_LOG_TERMS = 32
_EXP_TERMS = 24
_COS_TERMS = 14

#: Resource-safety bound: exp(x) with floor(x / ln2) > this is rejected
#: before any shift; the result could never be a finite double.
_MAX_EXP_SHIFT = 1024

#: Documented domain-separation literal for realization draws.
_DOMAIN_LITERAL = "kalhas/world-realization-v1"


class SamplerOverflowError(Exception):
    """A deterministic resource-safety or finiteness guard was violated.

    Internal sampler signal; callers map it to the typed
    ``WorldRealizationSamplingError``. Never caught and ignored.
    """


@dataclass(frozen=True)
class SamplerOutput:
    """One deterministic sample: the Q64.64 value plus representation source.

    ``selected_discrete_value`` is the exact declared value selected by
    a discrete distribution (``None`` for continuous families); its
    ``int``/``float`` type is the intended JSON representation source
    for the raw sample.
    """

    value_fix: int
    selected_discrete_value: int | float | None
    distribution_kind: str


def quantize_to_q64(value: float) -> int:
    """Exact rational round-half-even quantization of a float to Q64.64.

    Uses ``float.as_integer_ratio()`` (exact) and integer ``divmod``;
    no float multiplication performs hidden quantization. Exact half
    ties round to even, sign-symmetrically. Deterministic and
    platform-stable.
    """
    numerator, denominator = value.as_integer_ratio()
    quotient, remainder = divmod(numerator << 64, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and quotient & 1):
        quotient += 1
    return quotient


def exact_value_to_fix(value: int | float) -> int:
    """Exact Q64.64 quantization of a strict ``int`` or ``float``.

    Exact ``int`` values convert by exact scaling (``value << 64``) -
    never through ``float(value)``, which would round integers beyond
    ``2**53``; ``float`` values use the rational round-half-even
    quantization.
    """
    if isinstance(value, int):
        return value << 64
    return quantize_to_q64(value)


def bound_to_fix(bound: int | float) -> int:
    """Quantize a stored clipping bound to Q64.64 (exact for int bounds)."""
    return exact_value_to_fix(bound)


def _validate_parameter(value: float, label: str) -> int:
    """Quantize one declared parameter with the vanishing rule.

    Raises :class:`ValueError` when a nonzero declared value quantizes
    to zero (the declared distribution would silently change) or when
    its magnitude exceeds the fixed-point budget. The contract already
    rejects magnitudes above ``MAX_ABS_PARAMETER``; this is the
    defensive application-layer re-check.
    """
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if abs(value) > 2.0**960:
        raise ValueError(f"{label} exceeds MAX_ABS_PARAMETER")
    fixed = quantize_to_q64(value)
    if value != 0.0 and fixed == 0:
        raise ValueError(f"{label} vanishes under Q64.64 quantization")
    return fixed


def digest_word(
    *,
    world_content_hash: str,
    seed_content_hash: str,
    uncertainty_binding_content_hash: str,
    draw_index: int,
) -> int:
    """The deterministic 64-bit word for one draw.

    SHA-256 of the canonical payload; the word is the first 8 bytes of
    the digest interpreted as a big-endian unsigned integer in
    ``[0, 2**64)``. The fixed domain literal separates realization
    draws from any future consumer; the binding content hash separates
    bindings; the seed hash separates seeds. No strategy input exists.
    """
    payload = canonical_json(
        {
            "domain": _DOMAIN_LITERAL,
            "draw_index": draw_index,
            "sampler_version": SAMPLER_VERSION,
            "seed_content_hash": seed_content_hash,
            "uncertainty_binding_content_hash": uncertainty_binding_content_hash,
            "world_content_hash": world_content_hash,
        }
    )
    return int(sha256_hex(payload)[:16], 16)


def sqrt_fix(value: int) -> int:
    """Q64.64 square root of a non-negative Q64.64 value (exact floor)."""
    if value < 0:
        raise SamplerOverflowError("square root of a negative fixed-point value")
    return math.isqrt(value << 64)


def log_fix(value: int) -> int:
    """Q64.64 natural logarithm of a positive Q64.64 value.

    Fixed 32-term atanh series after exact power-of-two normalization.
    Verified accuracy: at most 64 Q64.64 ulps absolute error.
    """
    if value <= 0:
        raise SamplerOverflowError("logarithm of a non-positive fixed-point value")
    bits = value.bit_length()
    if bits > 65:
        exponent, mantissa = bits - 65, value >> (bits - 65)
    else:
        exponent, mantissa = bits - 65, value << (65 - bits)
    z = ((mantissa - S) << 64) // (mantissa + S)  # z in [0, 1/3)
    z2 = (z * z) >> 64
    term = z
    total = 0
    for k in range(_LOG_TERMS):
        total += term // (2 * k + 1)
        term = (term * z2) >> 64
    return (total << 1) + exponent * LN2_FIXED


def exp_fix(value: int) -> int:
    """Q64.64 exponential of a Q64.64 value (resource-safe).

    ``k = floor(value / ln2)`` (floor semantics, correct for negatives),
    ``r = value - k*ln2`` in ``[0, ln2)``, ``exp = 2**k * exp(r)`` with
    a fixed 24-term Horner. Guards run **before** any shift: ``k > 1024``
    raises (the result could not be a finite double and the shift would
    be unbounded); ``k < -65`` returns exactly 0 (documented
    underflow). Verified: identities at 0/ln2/-ln2 are exact and the
    relative error is below ``2**-50``.
    """
    k = value // LN2_FIXED
    if k > _MAX_EXP_SHIFT:
        raise SamplerOverflowError("exponential argument exceeds the safe range")
    if k < -65:
        return 0
    r = value - k * LN2_FIXED
    t = S
    for n in range(_EXP_TERMS, 0, -1):
        t = ((t * r) >> 64) // n + S
    return t << k if k >= 0 else t >> (-k)


def cos_fix(value: int) -> int:
    """Q64.64 cosine of a Q64.64 angle in ``[0, TWO_PI_FIXED)``.

    Quadrant reduction to ``[0, pi/2]`` plus a fixed 14-term Horner.
    Verified accuracy: at most 32 Q64.64 ulps absolute error.
    """
    if not 0 <= value < TWO_PI_FIXED:
        raise SamplerOverflowError("cosine angle outside the canonical range")
    half_pi = PI_FIXED >> 1
    if value < half_pi:
        theta, sign = value, 1
    elif value < PI_FIXED:
        theta, sign = PI_FIXED - value, -1
    elif value < (3 * PI_FIXED) >> 1:
        theta, sign = value - PI_FIXED, -1
    else:
        theta, sign = TWO_PI_FIXED - value, 1
    t = (theta * theta) >> 64
    c = S
    for n in range(_COS_TERMS, 0, -1):
        c = S - (((c * t) >> 64) // ((2 * n) * (2 * n - 1)))
    return c if sign > 0 else -c


def _box_muller(word_0: int, word_1: int) -> int:
    """One standard normal ``z_fix`` from two digest words.

    ``u1 = (word_0 + 1) / 2**64`` (structurally never zero) and
    ``u2 = (word_1 + 1) / 2**64``; the radius is exactly
    ``sqrt(-2 * ln(u1))`` (a single multiplication by 2 inside the
    logarithm scale) and the angle is ``2*pi*u2`` reduced modulo
    ``2*pi``. The result is invariant-checked against the exact
    deterministic maximum ``Z_MAX_FIXED``; a violation fails safely.
    """
    u1_fix = word_0 + 1
    u2_fix = word_1 + 1
    radius_squared = -(log_fix(u1_fix) << 1)
    angle = ((TWO_PI_FIXED * u2_fix) >> 64) % TWO_PI_FIXED
    z_fix = (sqrt_fix(radius_squared) * cos_fix(angle)) >> 64
    if abs(z_fix) > Z_MAX_FIXED:
        raise SamplerOverflowError("normal draw exceeds the deterministic Z_MAX bound")
    return z_fix


def _uniform_value(distribution: UniformDistribution, word_0: int) -> int:
    low_fix = _validate_parameter(distribution.low, "low")
    high_fix = _validate_parameter(distribution.high, "high")
    return low_fix + (((high_fix - low_fix) * word_0) >> 64)


def _triangular_value(distribution: TriangularDistribution, word_0: int) -> int:
    low_fix = _validate_parameter(distribution.low, "low")
    mode_fix = _validate_parameter(distribution.mode, "mode")
    high_fix = _validate_parameter(distribution.high, "high")
    if high_fix == low_fix:
        # Effective degenerate case: mode_fix == low_fix is guaranteed
        # by the validated ordering; never divide by zero.
        return low_fix
    p0 = ((mode_fix - low_fix) << 64) // (high_fix - low_fix)
    if word_0 < p0:
        radicand = ((word_0 * (high_fix - low_fix)) >> 64) * (mode_fix - low_fix)
        return low_fix + sqrt_fix(radicand >> 64)
    radicand = (((S - word_0) * (high_fix - low_fix)) >> 64) * (high_fix - mode_fix)
    return high_fix - sqrt_fix(radicand >> 64)


def _normal_value(distribution: NormalDistribution, word_0: int, word_1: int) -> int:
    mean_fix = _validate_parameter(distribution.mean, "mean")
    sd_fix = _validate_parameter(distribution.standard_deviation, "standard_deviation")
    z_fix = _box_muller(word_0, word_1)
    return mean_fix + ((sd_fix * z_fix) >> 64)


def _lognormal_value(distribution: LognormalDistribution, word_0: int, word_1: int) -> int:
    mu_fix = _validate_parameter(distribution.mu, "mu")
    sigma_fix = _validate_parameter(distribution.sigma, "sigma")
    z_fix = _box_muller(word_0, word_1)
    argument = mu_fix + ((sigma_fix * z_fix) >> 64)
    return exp_fix(argument)


def _discrete_sample(distribution: DiscreteDistribution, word_0: int) -> int | float:
    """Exact integer-weight ticket selection.

    Returns the exact selected declared value (``int`` stays ``int``,
    ``float`` stays ``float``). Weights are the exact Q64.64
    quantizations of the declared probabilities; the total weight is
    their exact integer sum (no per-weight normalization and **no
    forced residual assignment**, so zero-probability support values
    are never selected - including a final zero-probability entry). The
    ticket is ``T = (word_0 * W) >> 64`` in ``[0, W - 1]`` and the
    selected index is the smallest ``i`` with ``T < cumulative_i``
    (strict ``<``: a ticket exactly on a cumulative boundary resolves
    to the later value).
    """
    weights = [
        _validate_parameter(probability, "probability")
        for probability in distribution.probabilities
    ]
    total_weight = sum(weights)
    if total_weight < 1:
        raise SamplerOverflowError("discrete distribution has no effective positive mass")
    ticket = (word_0 * total_weight) >> 64
    cumulative = 0
    for value, weight in zip(distribution.values, weights, strict=True):
        cumulative += weight
        if ticket < cumulative:
            return value
    raise SamplerOverflowError("discrete ticket selection failed to resolve")


def sample_distribution(
    distribution: DistributionSpecification,
    *,
    word_0: int,
    word_1: int | None = None,
) -> SamplerOutput:
    """Sample one distribution from pre-computed digest words.

    ``word_1`` is required exactly for the two-word families (normal,
    lognormal) and must be ``None`` for the one-word families. The
    output carries the Q64.64 value and the representation source.
    Parameter-domain violations surface as
    :class:`SamplerOverflowError` so runtime sampling always fails
    through the typed sampling boundary.
    """
    try:
        if isinstance(distribution, UniformDistribution):
            if word_1 is not None:
                raise SamplerOverflowError("uniform consumes exactly one word")
            return SamplerOutput(_uniform_value(distribution, word_0), None, "uniform")
        if isinstance(distribution, TriangularDistribution):
            if word_1 is not None:
                raise SamplerOverflowError("triangular consumes exactly one word")
            return SamplerOutput(_triangular_value(distribution, word_0), None, "triangular")
        if isinstance(distribution, NormalDistribution):
            if word_1 is None:
                raise SamplerOverflowError("normal consumes exactly two words")
            return SamplerOutput(_normal_value(distribution, word_0, word_1), None, "normal")
        if isinstance(distribution, LognormalDistribution):
            if word_1 is None:
                raise SamplerOverflowError("lognormal consumes exactly two words")
            return SamplerOutput(_lognormal_value(distribution, word_0, word_1), None, "lognormal")
        if isinstance(distribution, DiscreteDistribution):
            if word_1 is not None:
                raise SamplerOverflowError("discrete consumes exactly one word")
            selected = _discrete_sample(distribution, word_0)
            selected_fix = exact_value_to_fix(selected)
            return SamplerOutput(selected_fix, selected, "discrete")
    except ValueError as exc:
        raise SamplerOverflowError(str(exc)) from None
    raise SamplerOverflowError("unknown distribution family")


def record_raw_value(value_fix: int, kind: Literal["int", "float"]) -> int | float:
    """Convert a Q64.64 value to its recorded raw/final numeric form.

    The finite-representability guard ``abs(value_fix) <=
    MAX_FINITE_FIXED`` runs **before** any conversion: a non-finite or
    unrepresentable value raises (clipping can never rescue it).
    ``"int"`` representation requires an exact integral fixed value and
    returns the exact ``int``; ``"float"`` returns the correctly
    rounded double via CPython's exact ``int`` true division.
    Integer-to-float ``OverflowError`` is caught and translated.
    """
    if abs(value_fix) > MAX_FINITE_FIXED:
        raise SamplerOverflowError("fixed-point value exceeds the finite recordable range")
    if kind == "int":
        if value_fix % S != 0:
            raise SamplerOverflowError(
                "integer representation requires an exact integral fixed-point value"
            )
        return value_fix // S
    try:
        return value_fix / S
    except OverflowError:
        raise SamplerOverflowError(
            "fixed-point value cannot be converted to a finite float"
        ) from None


def clip_fixed(
    value_fix: int,
    *,
    lower_bound: int | float | None,
    upper_bound: int | float | None,
) -> tuple[int, Literal["int", "float"] | None]:
    """Clip a fixed-point value against the present bounds.

    Returns the clipped fixed value and, when clipping replaced the
    value with a bound, the exact stored bound's JSON representation
    kind (``"int"`` for an exact ``int`` bound, ``"float"`` for a
    ``float`` bound) so the final representation can be preserved.
    """
    replaced: Literal["int", "float"] | None = None
    if lower_bound is not None:
        lower_fix = bound_to_fix(lower_bound)
        if value_fix < lower_fix:
            value_fix = lower_fix
            replaced = "int" if isinstance(lower_bound, int) else "float"
    if upper_bound is not None:
        upper_fix = bound_to_fix(upper_bound)
        if value_fix > upper_fix:
            value_fix = upper_fix
            replaced = "int" if isinstance(upper_bound, int) else "float"
    return value_fix, replaced


def round_fixed(value_fix: int, policy: str) -> int:
    """Round a Q64.64 value to an exact ``int`` with the declared policy.

    - ``floor``: arithmetic floor (Python ``>>``), correct for negatives.
    - ``ceil``: ``-((-value) >> 64)``, correct for negatives.
    - ``nearest_ties_to_even``: exact half ties (``r == 2**63``) round
      to the even integer for both signs; non-ties round to nearest.
    """
    if policy == "floor":
        return value_fix >> 64
    if policy == "ceil":
        return -((-value_fix) >> 64)
    if policy == "nearest_ties_to_even":
        quotient = value_fix >> 64
        remainder = value_fix & (S - 1)
        if remainder > (1 << 63):
            return quotient + 1
        if remainder < (1 << 63):
            return quotient
        return quotient + (quotient & 1)
    raise SamplerOverflowError(f"unknown rounding policy {policy!r}")


def discrete_static_final_values(
    distribution: DiscreteDistribution,
    *,
    lower_bound: int | float | None,
    upper_bound: int | float | None,
    field_kind: Literal["integer", "number"],
    rounding_policy: str | None,
) -> list[int | float]:
    """The statically known final values of every positive-probability outcome.

    For each positive-probability support value: quantize -> clip ->
    round (integer targets) -> representation preservation. Used by the
    declaration service and world integrity to prove that every
    selectable discrete outcome satisfies the target field kind and
    ``allowed_values``. Zero-probability support values are unselectable
    and are excluded.
    """
    finals: list[int | float] = []
    for value, probability in zip(distribution.values, distribution.probabilities, strict=True):
        if probability <= 0.0:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("discrete value must be finite")
        if abs(value) > 2.0**960:
            raise ValueError("discrete value exceeds MAX_ABS_PARAMETER")
        value_fix = exact_value_to_fix(value)
        clipped_fix, replaced = clip_fixed(
            value_fix, lower_bound=lower_bound, upper_bound=upper_bound
        )
        if field_kind == "integer":
            if rounding_policy is None:
                raise ValueError("integer targets require a rounding_policy")
            finals.append(round_fixed(clipped_fix, rounding_policy))
        else:
            kind: Literal["int", "float"] = (
                replaced if replaced is not None else ("int" if isinstance(value, int) else "float")
            )
            finals.append(record_raw_value(clipped_fix, kind))
    return finals


def validate_effective_parameters(
    distribution: DistributionSpecification,
    *,
    lower_bound: int | float | None,
    upper_bound: int | float | None,
) -> None:
    """Validate the effective Q64.64 parameter domain of one binding.

    Raises :class:`ValueError` with a rule-level reason when: a nonzero
    declared value vanishes under quantization; the effective ordering
    is violated (``low_fix <= high_fix``, ``low_fix <= mode_fix <=
    high_fix``); an effective standard deviation/sigma is zero; a
    declared positive discrete probability vanishes; or a lognormal
    model can produce a non-finite raw (its static maximum argument
    ``mu + Z_MAX*sigma`` exceeds the finite-raw boundary). Callers map
    the failure to their typed error surface.
    """
    if lower_bound is not None:
        _validate_parameter(float(lower_bound), "lower_bound")
    if upper_bound is not None:
        _validate_parameter(float(upper_bound), "upper_bound")
    if (
        lower_bound is not None
        and upper_bound is not None
        and bound_to_fix(lower_bound) > bound_to_fix(upper_bound)
    ):
        raise ValueError("effective lower bound exceeds effective upper bound")
    if isinstance(distribution, UniformDistribution):
        low_fix = _validate_parameter(distribution.low, "low")
        high_fix = _validate_parameter(distribution.high, "high")
        if low_fix > high_fix:
            raise ValueError("effective low exceeds effective high")
    elif isinstance(distribution, TriangularDistribution):
        low_fix = _validate_parameter(distribution.low, "low")
        mode_fix = _validate_parameter(distribution.mode, "mode")
        high_fix = _validate_parameter(distribution.high, "high")
        if not (low_fix <= mode_fix <= high_fix):
            raise ValueError("effective triangular ordering violated")
    elif isinstance(distribution, NormalDistribution):
        _validate_parameter(distribution.mean, "mean")
        sd_fix = _validate_parameter(distribution.standard_deviation, "standard_deviation")
        if sd_fix <= 0:
            raise ValueError("effective standard deviation must be strictly positive")
    elif isinstance(distribution, LognormalDistribution):
        mu_fix = _validate_parameter(distribution.mu, "mu")
        sigma_fix = _validate_parameter(distribution.sigma, "sigma")
        if sigma_fix <= 0:
            raise ValueError("effective sigma must be strictly positive")
        if mu_fix + ((Z_MAX_FIXED * sigma_fix) >> 64) > LN_RAW_MAX_FIXED:
            raise ValueError("lognormal mu + Z_MAX*sigma exceeds the finite raw-sample boundary")
    elif isinstance(distribution, DiscreteDistribution):
        total_weight = 0
        for probability in distribution.probabilities:
            weight = _validate_parameter(probability, "probability")
            if probability > 0.0 and weight <= 0:
                raise ValueError("a positive declared probability vanishes under quantization")
            total_weight += weight
        if total_weight < 1:
            raise ValueError("discrete distribution has no effective positive mass")
    else:  # pragma: no cover - the closed union cannot produce this
        raise ValueError("unknown distribution family")


def canonical_json_text(value: object) -> str:
    """Canonical JSON text of a value (equality domain for allowed checks)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
