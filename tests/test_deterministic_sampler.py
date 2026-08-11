"""Phase 24 deterministic sampler tests with frozen golden vectors.

Every expected value below is a hard-coded integer (Q64.64 fixed-point
or exact int) or float that was independently derived and pinned during
the corrective design pass - never computed by the production function
under test at runtime. The constants were derived from exact reference
digits (never platform libm; on this platform ``math.log(2.0)`` differs
from the exact constant by 428 Q64.64 units).

Also proves the open-uniform mapping, the corrected Box-Muller scale,
the deterministic Z_MAX invariant, the resource guards, the degenerate
triangular path, the exact discrete ticket selection with
zero-probability entries never selected and no forced residual, the
representation-preserving rounding/clipping rules, and the finiteness
guard that runs before clipping.
"""

from __future__ import annotations

import math

import pytest
from kalhas.application.deterministic_sampler import (
    LN2_FIXED,
    LN_RAW_MAX_FIXED,
    MAX_FINITE_FIXED,
    PI_FIXED,
    TWO_PI_FIXED,
    Z_MAX_FIXED,
    S,
    SamplerOverflowError,
    bound_to_fix,
    clip_fixed,
    cos_fix,
    digest_word,
    exact_value_to_fix,
    exp_fix,
    log_fix,
    quantize_to_q64,
    record_raw_value,
    round_fixed,
    sample_distribution,
    sqrt_fix,
    validate_effective_parameters,
)
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    LognormalDistribution,
    NormalDistribution,
    TriangularDistribution,
    UniformDistribution,
)

MAX_WORD = 2**64 - 1
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class TestFrozenConstants:
    def test_constants_are_exact(self) -> None:
        assert LN2_FIXED == 12786308645202655660  # hex 0xB17217F7D1CF79AC
        assert PI_FIXED == 57952155664616982739  # hex 0x3243F6A8885A308D3
        assert TWO_PI_FIXED == 2 * PI_FIXED
        assert Z_MAX_FIXED == 173755050841308499932  # hex 0x96B55F2257E218FDC
        # ln(709.78) boundary for the lognormal static finite-raw check.
        assert LN_RAW_MAX_FIXED == 13093130008637565546004
        assert S == 18446744073709551616

    def test_z_max_is_sqrt_of_128_ln2(self) -> None:
        # Z_MAX = isqrt(128 * LN2_FIXED << 64) exactly.
        assert math.isqrt(128 * LN2_FIXED << 64) == Z_MAX_FIXED


class TestQuantization:
    def test_rational_round_half_even(self) -> None:
        assert quantize_to_q64(0.5) == 9223372036854775808
        assert quantize_to_q64(-0.5) == -9223372036854775808
        assert quantize_to_q64(1.0) == S
        assert quantize_to_q64(1e-10) == 1844674407
        assert quantize_to_q64(0.1) == 1844674407370955264
        assert quantize_to_q64(0.25) == 4611686018427387904
        assert quantize_to_q64(0.75) == 13835058055282163712
        assert quantize_to_q64(5.0) == 92233720368547758080

    def test_positive_and_negative_half_ties_round_to_even(self) -> None:
        # 3 * 2**-65 = 1.5 ulps -> ties to even -> 2.
        assert quantize_to_q64(3 * 2**-65) == 2
        assert quantize_to_q64(-(3 * 2**-65)) == -2

    def test_vanishing_quantization_is_exact(self) -> None:
        # 2**-65 is exactly half an ulp -> rounds to even -> 0.
        assert quantize_to_q64(2**-65) == 0

    def test_exact_int_conversion_never_rounds(self) -> None:
        big = 2**60 + 1
        assert exact_value_to_fix(big) == big << 64
        assert bound_to_fix(big) == big << 64


class TestPrimitives:
    def test_log_golden_values(self) -> None:
        assert log_fix(S) == 0
        # log(2) and log(1/2) are exactly +-LN2_FIXED (identity at 2^-k).
        assert log_fix(2 * S) == LN2_FIXED
        assert log_fix(S // 2) == -LN2_FIXED
        # log(exp(1)) is within 64 Q64.64 ulps of 1.0.
        assert abs(log_fix(exp_fix(S)) - S) <= 64

    def test_exp_golden_values(self) -> None:
        assert exp_fix(0) == S
        assert exp_fix(LN2_FIXED) == 2 * S
        assert exp_fix(-LN2_FIXED) == S >> 1
        assert exp_fix(S) == 50143449209799256680
        assert exp_fix(-S) == 6786177901268885274
        assert exp_fix(10 * S) == 406316577365116946415616
        # Underflow: exp(-40) quantizes to 78 Q64.64 units (sub-ulp).
        assert exp_fix(-40 * S) == 78
        # Far underflow returns exactly zero.
        assert exp_fix(-100 * S) == 0

    def test_exp_resource_guard_rejects_large_argument(self) -> None:
        with pytest.raises(SamplerOverflowError):
            exp_fix(711 * S)

    def test_sqrt_golden_values(self) -> None:
        assert sqrt_fix(4 * S) == 36893488147419103232  # exactly 2.0
        assert sqrt_fix(2 * S) == 26087635650665564424  # sqrt(2), floor

    def test_sqrt_rejects_negative(self) -> None:
        with pytest.raises(SamplerOverflowError):
            sqrt_fix(-1)

    def test_cos_golden_values(self) -> None:
        assert cos_fix(0) == S
        assert cos_fix(PI_FIXED >> 1) == 0  # cos(pi/2)
        assert cos_fix(PI_FIXED) == -S  # cos(pi)
        assert cos_fix(TWO_PI_FIXED - 1) == S  # cos(2pi - 1ulp)

    def test_cos_rejects_out_of_range_angle(self) -> None:
        with pytest.raises(SamplerOverflowError):
            cos_fix(TWO_PI_FIXED)
        with pytest.raises(SamplerOverflowError):
            cos_fix(-1)


class TestDigestWord:
    def test_digest_first_eight_bytes_big_endian(self) -> None:
        # Pinned by the canonical payload:
        # {"domain": "kalhas/world-realization-v1", "draw_index": 0,
        #  "sampler_version": "sha256-counter-v1", ...}
        assert (
            digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=0,
            )
            == 1343683057827715011
        )  # hex 0x12a5b89f388817c3
        assert (
            digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=1,
            )
            == 12893477851867989463
        )  # hex 0xb2eed5cb2ff545d7

    def test_digest_differs_across_draw_indexes(self) -> None:
        words = {
            digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=index,
            )
            for index in range(8)
        }
        assert len(words) == 8

    def test_digest_separates_bindings_and_seeds(self) -> None:
        assert digest_word(
            world_content_hash=HASH_A,
            seed_content_hash=HASH_B,
            uncertainty_binding_content_hash=HASH_C,
            draw_index=0,
        ) != digest_word(
            world_content_hash=HASH_A,
            seed_content_hash=HASH_B,
            uncertainty_binding_content_hash="d" * 64,
            draw_index=0,
        )
        assert digest_word(
            world_content_hash=HASH_A,
            seed_content_hash=HASH_B,
            uncertainty_binding_content_hash=HASH_C,
            draw_index=0,
        ) != digest_word(
            world_content_hash=HASH_A,
            seed_content_hash="e" * 64,
            uncertainty_binding_content_hash=HASH_C,
            draw_index=0,
        )


class TestUniformSampling:
    def test_open_interval_endpoints(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=0.0, high=1.0)
        # word 0 maps to u = 1/2^64 (open at 0) -> value exactly 0.
        assert sample_distribution(uniform, word_0=0).value_fix == 0
        # word 2^64-1 maps to u = (2^64-1)/2^64 < 1 -> strictly below high.
        assert sample_distribution(uniform, word_0=MAX_WORD).value_fix == MAX_WORD
        # Mid word maps to exactly 0.5.
        assert sample_distribution(uniform, word_0=2**63).value_fix == 2**63

    def test_offset_uniform(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=2.0, high=3.0)
        assert sample_distribution(uniform, word_0=0).value_fix == 2 * S

    def test_degenerate_uniform_constant(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=5.0, high=5.0)
        expected = 5 * S
        assert sample_distribution(uniform, word_0=0).value_fix == expected
        assert sample_distribution(uniform, word_0=MAX_WORD).value_fix == expected

    def test_one_word_consumption_enforced(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=0.0, high=1.0)
        with pytest.raises(SamplerOverflowError):
            sample_distribution(uniform, word_0=0, word_1=1)


class TestTriangularSampling:
    def test_golden_values(self) -> None:
        triangular = TriangularDistribution(kind="triangular", low=0.0, mode=1.0, high=2.0)
        # word 0 -> lower corner exactly.
        assert sample_distribution(triangular, word_0=0).value_fix == 0
        # Mid word -> exactly the mode.
        assert sample_distribution(triangular, word_0=2**63).value_fix == S
        # Max word -> near the upper corner (strictly below high).
        assert sample_distribution(triangular, word_0=MAX_WORD).value_fix == 36893488141345102233

    def test_degenerate_triangular_before_division(self) -> None:
        triangular = TriangularDistribution(kind="triangular", low=5.0, mode=5.0, high=5.0)
        expected = 5 * S
        assert sample_distribution(triangular, word_0=0).value_fix == expected
        assert sample_distribution(triangular, word_0=MAX_WORD).value_fix == expected


class TestNormalSampling:
    def test_box_muller_two_word_consumption_and_z_max(self) -> None:
        normal = NormalDistribution(kind="normal", mean=0.0, standard_deviation=1.0)
        with pytest.raises(SamplerOverflowError):
            sample_distribution(normal, word_0=0)
        output = sample_distribution(
            normal,
            word_0=digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=0,
            ),
            word_1=digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=1,
            ),
        )
        assert output.value_fix == -13310318214927403355
        assert abs(output.value_fix) <= Z_MAX_FIXED

    def test_open_uniform_never_zero_for_radius(self) -> None:
        # u1 = (0 + 1)/2^64 is the smallest possible value; the radius is
        # sqrt(-2 ln u1) = sqrt(128 ln2) = Z_MAX exactly.
        assert math.isqrt((-(log_fix(0 + 1) << 1)) << 64) == Z_MAX_FIXED


class TestLognormalSampling:
    def test_golden_value(self) -> None:
        lognormal = LognormalDistribution(kind="lognormal", mu=0.0, sigma=1.0)
        output = sample_distribution(
            lognormal,
            word_0=digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=0,
            ),
            word_1=digest_word(
                world_content_hash=HASH_A,
                seed_content_hash=HASH_B,
                uncertainty_binding_content_hash=HASH_C,
                draw_index=1,
            ),
        )
        assert output.value_fix == 8965053598593392730
        # exp(mu + sigma*Z) with mu=0, sigma=1: positive and finite.
        assert output.value_fix > 0

    def test_static_finite_range_check(self) -> None:
        # mu + Z_MAX*sigma would exceed the finite raw boundary (mu >
        # 709.78 - Z_MAX).
        with pytest.raises(ValueError):
            validate_effective_parameters(
                LognormalDistribution(kind="lognormal", mu=1000.0, sigma=1.0),
                lower_bound=None,
                upper_bound=None,
            )


class TestDiscreteSampling:
    def test_exact_ticket_selection(self) -> None:
        discrete = DiscreteDistribution(
            kind="discrete", values=(1, 2, 3), probabilities=(0.25, 0.75, 0.0)
        )
        assert sample_distribution(discrete, word_0=0).selected_discrete_value == 1
        assert sample_distribution(discrete, word_0=2**63).selected_discrete_value == 2
        assert sample_distribution(discrete, word_0=MAX_WORD).selected_discrete_value == 2

    def test_zero_probability_never_selected(self) -> None:
        discrete = DiscreteDistribution(
            kind="discrete", values=(1, 2, 3), probabilities=(0.25, 0.75, 0.0)
        )
        for word in (0, 1, 2**63, MAX_WORD):
            assert sample_distribution(discrete, word_0=word).selected_discrete_value != 3

    def test_boundary_resolves_to_later_value(self) -> None:
        discrete = DiscreteDistribution(kind="discrete", values=(1, 1.0), probabilities=(0.5, 0.5))
        # Ticket exactly on the cumulative boundary resolves to the later value.
        output = sample_distribution(discrete, word_0=2**63)
        assert output.selected_discrete_value == 1.0

    def test_declared_type_preserved(self) -> None:
        discrete = DiscreteDistribution(kind="discrete", values=(1, 1.0), probabilities=(0.5, 0.5))
        for word in (0, 2**62):
            output = sample_distribution(discrete, word_0=word)
            assert output.selected_discrete_value == 1
            assert isinstance(output.selected_discrete_value, int)
            assert not isinstance(output.selected_discrete_value, float)
        for word in (2**63, MAX_WORD):
            output = sample_distribution(discrete, word_0=word)
            assert output.selected_discrete_value == 1.0
            assert isinstance(output.selected_discrete_value, float)


class TestRounding:
    def test_floor(self) -> None:
        assert round_fixed(quantize_to_q64(1.9), "floor") == 1
        assert round_fixed(quantize_to_q64(-1.1), "floor") == -2

    def test_ceil(self) -> None:
        assert round_fixed(quantize_to_q64(1.1), "ceil") == 2
        assert round_fixed(quantize_to_q64(-1.9), "ceil") == -1

    def test_nearest_ties_to_even(self) -> None:
        assert round_fixed(quantize_to_q64(0.5), "nearest_ties_to_even") == 0
        assert round_fixed(quantize_to_q64(-0.5), "nearest_ties_to_even") == 0
        assert round_fixed(quantize_to_q64(1.5), "nearest_ties_to_even") == 2
        assert round_fixed(quantize_to_q64(2.5), "nearest_ties_to_even") == 2
        assert round_fixed(quantize_to_q64(2.6), "nearest_ties_to_even") == 3
        assert round_fixed(quantize_to_q64(2.4), "nearest_ties_to_even") == 2
        assert round_fixed(quantize_to_q64(-1.5), "nearest_ties_to_even") == -2

    def test_unknown_policy_rejected(self) -> None:
        with pytest.raises(SamplerOverflowError):
            round_fixed(S, "banker")


class TestClipAndRecord:
    def test_clip_replaces_with_bound_type(self) -> None:
        assert clip_fixed(quantize_to_q64(5.0), lower_bound=2, upper_bound=3) == (3 * S, "int")
        assert clip_fixed(quantize_to_q64(-5.0), lower_bound=2, upper_bound=3) == (2 * S, "int")
        assert clip_fixed(quantize_to_q64(1.0), lower_bound=1.5, upper_bound=None) == (
            bound_to_fix(1.5),
            "float",
        )

    def test_clip_inside_bounds_unchanged(self) -> None:
        assert clip_fixed(quantize_to_q64(2.5), lower_bound=2, upper_bound=3) == (
            quantize_to_q64(2.5),
            None,
        )

    def test_independent_optional_bounds(self) -> None:
        assert clip_fixed(quantize_to_q64(5.0), lower_bound=2, upper_bound=None) == (5 * S, None)

    def test_record_raw_value(self) -> None:
        assert record_raw_value(quantize_to_q64(1.5), "float") == 1.5
        assert record_raw_value(3 * S, "int") == 3

    def test_record_rejects_unrepresentable_fixed_value(self) -> None:
        with pytest.raises(SamplerOverflowError):
            record_raw_value(MAX_FINITE_FIXED + 1, "float")

    def test_record_int_requires_exact_integral_value(self) -> None:
        with pytest.raises(SamplerOverflowError):
            record_raw_value(S + 1, "int")


class TestEffectiveParameterValidation:
    def test_vanishing_positive_probability_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_effective_parameters(
                DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(1e-30, 1.0)),
                lower_bound=None,
                upper_bound=None,
            )

    def test_vanishing_nonzero_parameter_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_effective_parameters(
                UniformDistribution(kind="uniform", low=0.0, high=1e-30),
                lower_bound=None,
                upper_bound=None,
            )

    def test_effective_ordering_enforced(self) -> None:
        with pytest.raises(ValueError):
            validate_effective_parameters(
                UniformDistribution(kind="uniform", low=0.3, high=0.1),
                lower_bound=None,
                upper_bound=None,
            )

    def test_effective_sigma_strictly_positive(self) -> None:
        with pytest.raises(ValueError):
            validate_effective_parameters(
                NormalDistribution(kind="normal", mean=0.0, standard_deviation=1e-30),
                lower_bound=None,
                upper_bound=None,
            )

    def test_effective_bound_ordering_enforced(self) -> None:
        with pytest.raises(ValueError):
            validate_effective_parameters(
                UniformDistribution(kind="uniform", low=0.0, high=1.0),
                lower_bound=0.9,
                upper_bound=0.1,
            )
