"""Phase 24 contract-level tests: world-uncertainty contracts.

Proves the closed discriminated distribution union, the strict numeric
representation rules (bool/string/None/container/NaN/Infinity rejected
before coercion; ``int`` stays ``int`` and ``float`` stays ``float``),
the distribution boundary rules, the binding rounding/bound/discrete
kind rules, the sampled-value draw accounting and raw/realized kind
rules, the realization draw-range partition invariants, the override
one-to-one agreement, and the matrix shape/order/provenance invariants.
"""

from __future__ import annotations

import pytest
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix,
    DiscreteDistribution,
    DistributionSpecification,
    LognormalDistribution,
    NormalDistribution,
    RealizedStateFieldValue,
    SampledStateFieldValue,
    StateFieldUncertaintyBinding,
    TriangularDistribution,
    UniformDistribution,
    WorldRealization,
    WorldUncertaintyModel,
)
from pydantic import TypeAdapter, ValidationError

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _binding(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "uncertainty-binding-0123456789abcdef",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "distribution": {"kind": "uniform", "low": 0.0, "high": 1.0},
        "rounding_policy": "floor",
        "lower_bound": None,
        "upper_bound": None,
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "content_hash": HASH_64,
    }
    payload.update(overrides)
    return payload


def _realization(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "world-realization-0123456789abcdef",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "world_version_id": "world-0123456789abcdef",
        "world_content_hash": HASH_64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": HASH_64,
        "uncertainty_model_id": "uncertainty-model-0123456789abcdef",
        "uncertainty_model_content_hash": HASH_64,
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "sampled_values": [
            {
                "uncertainty_binding_identifier": "uncertainty-binding-0123456789abcdef",
                "uncertainty_binding_content_hash": HASH_64,
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": "level",
                "state_field_value_kind": "integer",
                "distribution_kind": "uniform",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": 0,
                "draw_count": 1,
                "sampled_raw_value": 0.25,
                "realized_value": 0,
            }
        ],
        "realized_initial_state_overrides": [
            {
                "state_model_identifier": "state-model-1",
                "state_field_id": "level",
                "value": 0,
            }
        ],
        "content_hash": HASH_64,
        "realized_at": "2026-01-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


class TestDistributionUnion:
    def test_all_five_families_validate(self) -> None:
        adapter: TypeAdapter[DistributionSpecification] = TypeAdapter(DistributionSpecification)
        for payload in (
            {"kind": "uniform", "low": 0.0, "high": 1.0},
            {"kind": "triangular", "low": 0.0, "mode": 0.5, "high": 1.0},
            {"kind": "normal", "mean": 0.0, "standard_deviation": 1.0},
            {"kind": "lognormal", "mu": 0.0, "sigma": 1.0},
            {"kind": "discrete", "values": [1, 2], "probabilities": [0.5, 0.5]},
        ):
            assert adapter.validate_python(payload).kind == payload["kind"]

    def test_discriminated_union_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(
                _binding(distribution={"kind": "weibull", "shape": 1.0})
            )

    def test_discriminated_union_rejects_extra_field(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(
                _binding(
                    distribution={
                        "kind": "uniform",
                        "low": 0.0,
                        "high": 1.0,
                        "scale": 2.0,
                    }
                )
            )

    def test_models_are_frozen_and_forbid_extra(self) -> None:
        cases = (
            (UniformDistribution, {"kind": "uniform", "low": 0.0, "high": 1.0}),
            (
                TriangularDistribution,
                {"kind": "triangular", "low": 0.0, "mode": 0.5, "high": 1.0},
            ),
            (
                NormalDistribution,
                {"kind": "normal", "mean": 0.0, "standard_deviation": 1.0},
            ),
            (LognormalDistribution, {"kind": "lognormal", "mu": 0.0, "sigma": 1.0}),
            (
                DiscreteDistribution,
                {"kind": "discrete", "values": [1, 2], "probabilities": [0.5, 0.5]},
            ),
        )
        for model, valid in cases:
            with pytest.raises(ValidationError):
                model.model_validate({**valid, "extra": 1})

    def test_frozen_assignment_raises(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=0.0, high=1.0)
        with pytest.raises(ValidationError):
            uniform.low = 2.0


class TestDistributionBoundaryRules:
    def test_uniform_low_less_than_high(self) -> None:
        with pytest.raises(ValidationError):
            UniformDistribution(kind="uniform", low=2.0, high=1.0)

    def test_uniform_degenerate_allowed(self) -> None:
        uniform = UniformDistribution(kind="uniform", low=1.0, high=1.0)
        assert uniform.low == uniform.high

    def test_uniform_rejects_non_finite(self) -> None:
        with pytest.raises(ValidationError):
            UniformDistribution(kind="uniform", low=0.0, high=float("inf"))
        with pytest.raises(ValidationError):
            UniformDistribution(kind="uniform", low=float("nan"), high=1.0)

    def test_triangular_ordering(self) -> None:
        with pytest.raises(ValidationError):
            TriangularDistribution(kind="triangular", low=2.0, mode=1.0, high=3.0)
        with pytest.raises(ValidationError):
            TriangularDistribution(kind="triangular", low=0.0, mode=2.0, high=1.0)

    def test_triangular_equalities_allowed(self) -> None:
        TriangularDistribution(kind="triangular", low=0.0, mode=0.0, high=1.0)
        TriangularDistribution(kind="triangular", low=0.0, mode=1.0, high=1.0)
        TriangularDistribution(kind="triangular", low=1.0, mode=1.0, high=1.0)

    def test_normal_requires_strictly_positive_deviation(self) -> None:
        with pytest.raises(ValidationError):
            NormalDistribution(kind="normal", mean=0.0, standard_deviation=0.0)
        with pytest.raises(ValidationError):
            NormalDistribution(kind="normal", mean=0.0, standard_deviation=-1.0)

    def test_lognormal_requires_strictly_positive_sigma(self) -> None:
        with pytest.raises(ValidationError):
            LognormalDistribution(kind="lognormal", mu=0.0, sigma=0.0)

    def test_discrete_rules(self) -> None:
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(), probabilities=())
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.5,))
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 1), probabilities=(0.5, 0.5))
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.5, -0.5))
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.0, 0.0))
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.2, 0.2))
        with pytest.raises(ValidationError):
            DiscreteDistribution(
                kind="discrete", values=(1, float("nan")), probabilities=(0.5, 0.5)
            )

    def test_discrete_sum_tolerance_accepted(self) -> None:
        DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.3, 0.7000000000001))
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 2), probabilities=(0.3, 0.8))

    def test_discrete_canonical_uniqueness_distinguishes_1_and_1_0(self) -> None:
        # Canonical JSON 1 and 1.0 are distinct values, so both may coexist.
        DiscreteDistribution(kind="discrete", values=(1, 1.0), probabilities=(0.5, 0.5))
        # A duplicated exact int is rejected.
        with pytest.raises(ValidationError):
            DiscreteDistribution(kind="discrete", values=(1, 1), probabilities=(0.5, 0.5))

    def test_discrete_zero_probability_support_allowed(self) -> None:
        DiscreteDistribution(kind="discrete", values=(1, 2, 3), probabilities=(0.25, 0.75, 0.0))


class TestStrictNumericRejection:
    def test_bool_string_none_container_nan_infinity_rejected(self) -> None:
        for bad in (True, "1", None, [1], float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                UniformDistribution.model_validate({"kind": "uniform", "low": bad, "high": 1.0})
            with pytest.raises(ValidationError):
                UniformDistribution.model_validate({"kind": "uniform", "low": 0.0, "high": bad})
        for bad in (True, "1", None, [1], float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                DiscreteDistribution.model_validate(
                    {
                        "kind": "discrete",
                        "values": [bad, 2],
                        "probabilities": [0.5, 0.5],
                    }
                )
            with pytest.raises(ValidationError):
                DiscreteDistribution.model_validate(
                    {
                        "kind": "discrete",
                        "values": [1, 2],
                        "probabilities": [0.5, bad],
                    }
                )

    def test_bounds_reject_bool_string_and_non_finite(self) -> None:
        for bad in (True, "1", float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                StateFieldUncertaintyBinding.model_validate(_binding(lower_bound=bad))

    def test_bounds_preserve_int_and_float_types(self) -> None:
        binding = StateFieldUncertaintyBinding.model_validate(
            _binding(
                state_field_value_kind="number",
                rounding_policy=None,
                lower_bound=1,
                upper_bound=1.0,
            )
        )
        assert binding.lower_bound == 1 and isinstance(binding.lower_bound, int)
        assert binding.upper_bound == 1.0 and isinstance(binding.upper_bound, float)

    def test_integer_target_requires_exact_integer_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(_binding(lower_bound=1.5))

    def test_number_target_rejects_rounding_policy(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(
                _binding(
                    state_field_value_kind="number",
                    distribution={"kind": "normal", "mean": 0.0, "standard_deviation": 1.0},
                    rounding_policy="floor",
                )
            )

    def test_integer_target_requires_rounding_policy(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(_binding(rounding_policy=None))

    def test_bound_ordering_enforced(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(_binding(lower_bound=5, upper_bound=2))

    def test_independent_optional_bounds(self) -> None:
        StateFieldUncertaintyBinding.model_validate(_binding(lower_bound=0))
        StateFieldUncertaintyBinding.model_validate(_binding(upper_bound=10))

    def test_discrete_integer_target_requires_integer_values(self) -> None:
        with pytest.raises(ValidationError):
            StateFieldUncertaintyBinding.model_validate(
                _binding(
                    distribution={
                        "kind": "discrete",
                        "values": [1, 2.0],
                        "probabilities": [0.5, 0.5],
                    }
                )
            )


class TestSampledStateFieldValue:
    def test_draw_count_must_match_distribution_kind(self) -> None:
        with pytest.raises(ValidationError):
            SampledStateFieldValue.model_validate(
                {
                    "uncertainty_binding_identifier": "ub-1",
                    "uncertainty_binding_content_hash": HASH_64,
                    "scenario_id": "scenario-1",
                    "binding_id": "binding-1",
                    "manifest_id": "manifest-1",
                    "state_model_identifier": "state-model-1",
                    "state_model_id": "sm-1",
                    "state_field_id": "level",
                    "state_field_value_kind": "integer",
                    "distribution_kind": "uniform",
                    "sampler_version": "sha256-counter-v1",
                    "quantization_policy": "rational-round-half-even",
                    "quantization_fraction_bits": 64,
                    "draw_index": 0,
                    "draw_count": 2,
                    "sampled_raw_value": 0.5,
                    "realized_value": 0,
                }
            )

    def test_normal_requires_draw_count_two(self) -> None:
        sampled = SampledStateFieldValue.model_validate(
            {
                "uncertainty_binding_identifier": "ub-1",
                "uncertainty_binding_content_hash": HASH_64,
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": "ratio",
                "state_field_value_kind": "number",
                "distribution_kind": "normal",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": 0,
                "draw_count": 2,
                "sampled_raw_value": 0.5,
                "realized_value": 0.5,
            }
        )
        assert sampled.draw_count == 2

    def test_integer_target_requires_integer_realized_value(self) -> None:
        with pytest.raises(ValidationError):
            SampledStateFieldValue.model_validate(
                {
                    "uncertainty_binding_identifier": "ub-1",
                    "uncertainty_binding_content_hash": HASH_64,
                    "scenario_id": "scenario-1",
                    "binding_id": "binding-1",
                    "manifest_id": "manifest-1",
                    "state_model_identifier": "state-model-1",
                    "state_model_id": "sm-1",
                    "state_field_id": "level",
                    "state_field_value_kind": "integer",
                    "distribution_kind": "uniform",
                    "sampler_version": "sha256-counter-v1",
                    "quantization_policy": "rational-round-half-even",
                    "quantization_fraction_bits": 64,
                    "draw_index": 0,
                    "draw_count": 1,
                    "sampled_raw_value": 0.5,
                    "realized_value": 0.5,
                }
            )

    def test_integer_target_raw_may_be_float(self) -> None:
        sampled = SampledStateFieldValue.model_validate(
            {
                "uncertainty_binding_identifier": "ub-1",
                "uncertainty_binding_content_hash": HASH_64,
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": "level",
                "state_field_value_kind": "integer",
                "distribution_kind": "uniform",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": 0,
                "draw_count": 1,
                "sampled_raw_value": 0.5,
                "realized_value": 0,
            }
        )
        assert sampled.sampled_raw_value == 0.5

    def test_bool_and_non_finite_values_rejected(self) -> None:
        base = {
            "uncertainty_binding_identifier": "ub-1",
            "uncertainty_binding_content_hash": HASH_64,
            "scenario_id": "scenario-1",
            "binding_id": "binding-1",
            "manifest_id": "manifest-1",
            "state_model_identifier": "state-model-1",
            "state_model_id": "sm-1",
            "state_field_id": "level",
            "state_field_value_kind": "integer",
            "distribution_kind": "uniform",
            "sampler_version": "sha256-counter-v1",
            "quantization_policy": "rational-round-half-even",
            "quantization_fraction_bits": 64,
            "draw_index": 0,
            "draw_count": 1,
            "sampled_raw_value": 0.5,
            "realized_value": 0,
        }
        for key in ("sampled_raw_value", "realized_value"):
            for bad in (True, "1", float("nan"), float("inf")):
                with pytest.raises(ValidationError):
                    SampledStateFieldValue.model_validate({**base, key: bad})


class TestWorldRealizationInvariants:
    def test_valid_realization_accepted(self) -> None:
        realization = WorldRealization.model_validate(_realization())
        assert realization.uncertainty_model_id is not None
        assert realization.sampled_values[0].draw_index == 0

    def test_model_provenance_both_or_neither(self) -> None:
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(_realization(uncertainty_model_id=None))
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(_realization(uncertainty_model_content_hash=None))

    def test_empty_realization_with_absent_model_accepted(self) -> None:
        realization = WorldRealization.model_validate(
            _realization(
                uncertainty_model_id=None,
                uncertainty_model_content_hash=None,
                sampled_values=[],
                realized_initial_state_overrides=[],
            )
        )
        assert realization.sampled_values == ()

    def test_draw_indexes_must_be_contiguous_from_zero(self) -> None:
        two_draws = [
            {
                "uncertainty_binding_identifier": f"ub-{index}",
                "uncertainty_binding_content_hash": HASH_64,
                "scenario_id": "scenario-1",
                "binding_id": "binding-1",
                "manifest_id": "manifest-1",
                "state_model_identifier": "state-model-1",
                "state_model_id": "sm-1",
                "state_field_id": f"f-{index}",
                "state_field_value_kind": "integer",
                "distribution_kind": "uniform",
                "sampler_version": "sha256-counter-v1",
                "quantization_policy": "rational-round-half-even",
                "quantization_fraction_bits": 64,
                "draw_index": index,
                "draw_count": 1,
                "sampled_raw_value": 0.5,
                "realized_value": 0,
            }
            for index in range(2)
        ]
        overrides = [
            {
                "state_model_identifier": "state-model-1",
                "state_field_id": f"f-{index}",
                "value": 0,
            }
            for index in range(2)
        ]
        WorldRealization.model_validate(
            _realization(sampled_values=two_draws, realized_initial_state_overrides=overrides)
        )
        # A gap (first draw at index 1) is rejected.
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(
                _realization(
                    sampled_values=[
                        {**two_draws[1], "draw_index": 1},
                    ],
                    realized_initial_state_overrides=overrides[:1],
                )
            )
        # An overlap is rejected.
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(
                _realization(
                    sampled_values=[
                        {**two_draws[0], "draw_index": 0},
                        {**two_draws[1], "draw_index": 0},
                    ],
                    realized_initial_state_overrides=overrides,
                )
            )

    def test_overrides_one_to_one_agreement(self) -> None:
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(
                _realization(
                    realized_initial_state_overrides=[
                        {
                            "state_model_identifier": "state-model-1",
                            "state_field_id": "other",
                            "value": 0,
                        }
                    ]
                )
            )
        with pytest.raises(ValidationError):
            WorldRealization.model_validate(
                _realization(
                    realized_initial_state_overrides=[
                        {
                            "state_model_identifier": "state-model-1",
                            "state_field_id": "level",
                            "value": 0,
                        },
                        {
                            "state_model_identifier": "state-model-1",
                            "state_field_id": "level",
                            "value": 1,
                        },
                    ]
                )
            )


class TestCampaignWorldRealizationMatrixInvariants:
    def _matrix(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "identifier": "campaign-realization-matrix-0123456789abcdef",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "campaign_id": "campaign-1",
            "scenario_id": "scenario-1",
            "world_version_id": "world-0123456789abcdef",
            "world_content_hash": HASH_64,
            "uncertainty_model_id": "uncertainty-model-0123456789abcdef",
            "uncertainty_model_content_hash": HASH_64,
            "sampler_version": "sha256-counter-v1",
            "quantization_policy": "rational-round-half-even",
            "quantization_fraction_bits": 64,
            "ordered_scenario_seed_ids": ["seed-1"],
            "realizations": [_realization()],
            "content_hash": HASH_64,
            "assembled_at": "2026-01-01T12:00:00Z",
        }
        payload.update(overrides)
        return payload

    def test_valid_matrix_accepted(self) -> None:
        matrix = CampaignWorldRealizationMatrix.model_validate(self._matrix())
        assert matrix.realizations[0].scenario_seed_id == "seed-1"

    def test_exactly_one_realization_per_seed(self) -> None:
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(self._matrix(realizations=[]))
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(
                self._matrix(
                    ordered_scenario_seed_ids=["seed-1", "seed-2"],
                    realizations=[_realization(), _realization()],
                )
            )

    def test_seed_order_must_match_realization_order(self) -> None:
        second = _realization(
            identifier="world-realization-0123456789abcde0",
            scenario_seed_id="seed-2",
        )
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(
                self._matrix(
                    ordered_scenario_seed_ids=["seed-1", "seed-2"],
                    realizations=[second, _realization()],
                )
            )

    def test_realization_provenance_must_match_matrix(self) -> None:
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(
                self._matrix(
                    realizations=[_realization(uncertainty_model_id="uncertainty-model-other")]
                )
            )
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(
                self._matrix(realizations=[_realization(world_content_hash="f" * 64)])
            )

    def test_duplicate_seed_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignWorldRealizationMatrix.model_validate(
                self._matrix(ordered_scenario_seed_ids=["seed-1", "seed-1"])
            )


class TestWorldUncertaintyModelInvariants:
    def test_bindings_require_unique_target_tuples(self) -> None:
        payload: dict[str, object] = {
            "identifier": "uncertainty-model-0123456789abcdef",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "scenario_content_hash": HASH_64,
            "bindings": [
                _binding(),
                _binding(identifier="uncertainty-binding-0123456789abcde0"),
            ],
            "content_hash": HASH_64,
            "declared_at": "2026-01-01T12:00:00Z",
            "metadata": {},
        }
        with pytest.raises(ValidationError):
            WorldUncertaintyModel.model_validate(payload)

    def test_at_least_one_binding_required(self) -> None:
        with pytest.raises(ValidationError):
            WorldUncertaintyModel.model_validate(
                {
                    "identifier": "uncertainty-model-0123456789abcdef",
                    "tenant_id": "tenant-1",
                    "schema_version": "1.0.0",
                    "scenario_id": "scenario-1",
                    "scenario_content_hash": HASH_64,
                    "bindings": [],
                    "content_hash": HASH_64,
                    "declared_at": "2026-01-01T12:00:00Z",
                    "metadata": {},
                }
            )

    def test_metadata_rejects_non_finite_values(self) -> None:
        payload: dict[str, object] = {
            "identifier": "uncertainty-model-0123456789abcdef",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "scenario_content_hash": HASH_64,
            "bindings": [_binding()],
            "content_hash": HASH_64,
            "declared_at": "2026-01-01T12:00:00Z",
            "metadata": {"bad": float("inf")},
        }
        with pytest.raises(ValidationError):
            WorldUncertaintyModel.model_validate(payload)


class TestRealizedStateFieldValue:
    def test_value_must_be_exact_finite_numeric(self) -> None:
        RealizedStateFieldValue(
            state_model_identifier="state-model-1", state_field_id="level", value=1
        )
        RealizedStateFieldValue(
            state_model_identifier="state-model-1", state_field_id="ratio", value=1.0
        )
        for bad in (True, "1", float("nan"), float("inf"), [1]):
            with pytest.raises(ValidationError):
                RealizedStateFieldValue.model_validate(
                    {
                        "state_model_identifier": "state-model-1",
                        "state_field_id": "level",
                        "value": bad,
                    }
                )
