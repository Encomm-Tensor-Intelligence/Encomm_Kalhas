"""Tests for the strict campaign decision policy request models.

Tests for ``kalhas/api/requests_campaign_decision.py``:
``ObjectiveTargetRequirementRequest`` and
``CampaignDecisionPolicyDeclarationRequest``. Proves the caller-owned
request boundary:

- valid global and per-objective payloads (JSON arrays validate into
  the immutable requirements tuple);
- the four decision rules (``minimum_sample_count``, ``tie_tolerance``,
  ``all_targeted_objectives_are_hard_gates``, ``declared_at``) are
  explicit required fields - no silent defaults;
- the exact global/per-objective XOR and unique requirement identifiers;
- inclusive probability boundaries ``[0.0, 1.0]``;
- extra-field rejection and every caller-forbidden authoritative field
  (identity, hashes, weights, algorithm, tail alpha, runtime, comparison
  selector) rejected;
- the exact built-in numeric adversarial matrix for
  ``minimum_sample_count``, probabilities, and ``tie_tolerance``
  (booleans, strings, ``Decimal``, ``None``, containers, NaN, Infinity,
  and unrepresentable huge integers rejected before any coercion);
- the exact uncoerced bool matrix for the hard-gate flag;
- timezone-aware ``declared_at``;
- nested JSON-compatible metadata validation (valid and invalid trees);
- the generated request schema contains only caller-owned fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kalhas.api.requests_campaign_decision import (
    CampaignDecisionPolicyDeclarationRequest,
    ObjectiveTargetRequirementRequest,
)
from pydantic import ValidationError

DECLARED_AT_ISO = "2026-01-04T12:00:00Z"

#: Every authoritative field a caller must never provide.
_FORBIDDEN_FIELDS = (
    "identifier",
    "content_hash",
    "schema_version",
    "tenant_id",
    "campaign_id",
    "scenario_id",
    "scenario_content_hash",
    "world_version_id",
    "world_content_hash",
    "evaluation_profile_id",
    "evaluation_profile_content_hash",
    "algorithm_identifier",
    "objective_weight_snapshots",
    "tail_alpha",
    "comparison_mode",
    "runtime_version",
)


def _global_payload(**overrides: object) -> dict[str, object]:
    """A valid global-mode request payload; ``overrides`` win."""
    payload: dict[str, object] = {
        "target_requirement_mode": "global",
        "minimum_target_achievement_probability": 0.5,
        "objective_target_requirements": [],
        "minimum_sample_count": 100,
        "tie_tolerance": 0.05,
        "all_targeted_objectives_are_hard_gates": True,
        "declared_at": DECLARED_AT_ISO,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _per_objective_payload(**overrides: object) -> dict[str, object]:
    """A valid per-objective-mode request payload; ``overrides`` win."""
    payload: dict[str, object] = {
        "target_requirement_mode": "per_objective",
        "minimum_target_achievement_probability": None,
        "objective_target_requirements": [
            {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
            {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
            {"objective_id": "obj-5", "minimum_target_achievement_probability": 0.4},
        ],
        "minimum_sample_count": 100,
        "tie_tolerance": 0.05,
        "all_targeted_objectives_are_hard_gates": True,
        "declared_at": DECLARED_AT_ISO,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


class TestValidRequests:
    """Valid global and per-objective request payloads."""

    def test_valid_global_request(self) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(_global_payload())
        assert request.target_requirement_mode == "global"
        assert request.minimum_target_achievement_probability == 0.5
        assert request.objective_target_requirements == ()
        assert request.minimum_sample_count == 100
        assert request.tie_tolerance == 0.05
        assert request.all_targeted_objectives_are_hard_gates is True
        assert request.declared_at == datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
        assert request.metadata == {}

    def test_valid_per_objective_request(self) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(_per_objective_payload())
        assert request.target_requirement_mode == "per_objective"
        assert request.minimum_target_achievement_probability is None
        assert len(request.objective_target_requirements) == 3
        assert request.objective_target_requirements[0].objective_id == "obj-3"
        assert (
            request.objective_target_requirements[0].minimum_target_achievement_probability == 0.4
        )

    def test_json_arrays_validate_into_immutable_tuple(self) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(_per_objective_payload())
        assert isinstance(request.objective_target_requirements, tuple)
        with pytest.raises(AttributeError):
            request.objective_target_requirements.append(  # type: ignore[attr-defined]
                {"objective_id": "x", "minimum_target_achievement_probability": 0.1}
            )

    def test_requirement_model_accepts_boundaries(self) -> None:
        for probability in (0.0, 1.0, 0.5, 1):
            requirement = ObjectiveTargetRequirementRequest.model_validate(
                {"objective_id": "obj-1", "minimum_target_achievement_probability": probability}
            )
            assert requirement.minimum_target_achievement_probability == float(probability)

    def test_requirement_model_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveTargetRequirementRequest.model_validate(
                {
                    "objective_id": "obj-1",
                    "minimum_target_achievement_probability": 0.4,
                    "surprise": 1,
                }
            )


class TestRequiredExplicitRules:
    """The four decision rules are explicit required fields."""

    @pytest.mark.parametrize(
        "drop",
        ["minimum_sample_count", "tie_tolerance", "all_targeted_objectives_are_hard_gates"],
    )
    def test_required_rule_missing_rejected(self, drop: str) -> None:
        payload = _global_payload()
        del payload[drop]
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(payload)

    def test_declared_at_missing_rejected(self) -> None:
        payload = _global_payload()
        del payload["declared_at"]
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(payload)

    def test_declared_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(declared_at="2026-01-04T12:00:00")
            )
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(declared_at="2026-01-04T12:00:00+02:00")
        )
        assert request.declared_at.utcoffset() is not None


class TestModeXor:
    """The exact global/per-objective XOR."""

    def test_global_requires_probability(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=None)
            )

    def test_global_forbids_requirements(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(
                    objective_target_requirements=[
                        {
                            "objective_id": "obj-3",
                            "minimum_target_achievement_probability": 0.4,
                        }
                    ]
                )
            )

    def test_per_objective_forbids_probability(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _per_objective_payload(minimum_target_achievement_probability=0.5)
            )

    def test_per_objective_requires_requirements(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _per_objective_payload(objective_target_requirements=[])
            )

    def test_duplicate_requirement_objective_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _per_objective_payload(
                    objective_target_requirements=[
                        {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.4},
                        {"objective_id": "obj-3", "minimum_target_achievement_probability": 0.6},
                        {"objective_id": "obj-1", "minimum_target_achievement_probability": 0.4},
                    ]
                )
            )


class TestProbabilityRules:
    """Inclusive probability band and exact numeric kinds."""

    @pytest.mark.parametrize("probability", [0.0, 1.0, 0.25, 1])
    def test_band_boundaries_accepted(self, probability: object) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(minimum_target_achievement_probability=probability)
        )
        assert request.minimum_target_achievement_probability == probability

    @pytest.mark.parametrize("probability", [-0.1, 1.1, -1.0, 2.0])
    def test_out_of_band_rejected(self, probability: float) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=probability)
            )

    @pytest.mark.parametrize(
        "probability",
        [
            True,
            False,
            "0.5",
            "1",
            "0.5",
            None,
            [0.5],
            (0.5,),
            {"value": 0.5},
        ],
    )
    def test_non_numeric_kinds_rejected(self, probability: object) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=probability)
            )

    def test_decimal_rejected(self) -> None:
        import decimal

        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=decimal.Decimal("0.5"))
            )

    @pytest.mark.parametrize("probability", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_rejected(self, probability: float) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=probability)
            )

    @pytest.mark.parametrize("probability", [10**400, -(10**400)])
    def test_huge_integer_rejected(self, probability: int) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_target_achievement_probability=probability)
            )


class TestSampleCountRules:
    """Exact-int minimum sample count."""

    @pytest.mark.parametrize("count", [1, 100, 10**400])
    def test_exact_int_accepted(self, count: int) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(minimum_sample_count=count)
        )
        assert request.minimum_sample_count == count

    @pytest.mark.parametrize("count", [0, -1, -100])
    def test_below_one_rejected(self, count: int) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_sample_count=count)
            )

    @pytest.mark.parametrize(
        "count",
        [True, False, 1.0, 100.0, "100", "1", None, [100], (100,), {"value": 100}],
    )
    def test_non_exact_int_kinds_rejected(self, count: object) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_sample_count=count)
            )

    def test_decimal_rejected(self) -> None:
        import decimal

        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(minimum_sample_count=decimal.Decimal("100"))
            )


class TestTieToleranceRules:
    """Finite non-negative tie tolerance with exact numeric kinds."""

    @pytest.mark.parametrize("tolerance", [0.0, 0.05, 0, 100.5])
    def test_finite_non_negative_accepted(self, tolerance: object) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(tie_tolerance=tolerance)
        )
        assert request.tie_tolerance == tolerance

    @pytest.mark.parametrize("tolerance", [-0.1, -1.0])
    def test_negative_rejected(self, tolerance: float) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(tie_tolerance=tolerance)
            )

    @pytest.mark.parametrize(
        "tolerance",
        [True, False, "0.05", "0", None, [0.05], (0.05,), {"value": 0.05}],
    )
    def test_non_numeric_kinds_rejected(self, tolerance: object) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(tie_tolerance=tolerance)
            )

    def test_decimal_rejected(self) -> None:
        import decimal

        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(tie_tolerance=decimal.Decimal("0.05"))
            )

    @pytest.mark.parametrize("tolerance", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_rejected(self, tolerance: float) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(tie_tolerance=tolerance)
            )

    @pytest.mark.parametrize("tolerance", [10**400, -(10**400)])
    def test_huge_integer_rejected(self, tolerance: int) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(tie_tolerance=tolerance)
            )


class TestHardGateBoolRules:
    """The hard-gate flag must be an uncoerced exact bool."""

    @pytest.mark.parametrize("gates", [True, False])
    def test_exact_bool_accepted(self, gates: bool) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(all_targeted_objectives_are_hard_gates=gates)
        )
        assert request.all_targeted_objectives_are_hard_gates is gates

    @pytest.mark.parametrize(
        "gates",
        [0, 1, 0.0, 1.0, "true", "false", "True", "False", "yes", None, [True], {}, (1,)],
    )
    def test_non_exact_bool_rejected(self, gates: object) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(all_targeted_objectives_are_hard_gates=gates)
            )

    def test_decimal_rejected(self) -> None:
        import decimal

        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(all_targeted_objectives_are_hard_gates=decimal.Decimal("1"))
            )


class TestUnknownAndForbiddenFields:
    """Extra fields and caller-forbidden authoritative fields are rejected."""

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(_global_payload(surprise=1))

    @pytest.mark.parametrize("field", _FORBIDDEN_FIELDS)
    def test_forbidden_authoritative_field_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(**{field: "anything"})
            )

    def test_requirement_forbidden_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObjectiveTargetRequirementRequest.model_validate(
                {
                    "objective_id": "obj-1",
                    "minimum_target_achievement_probability": 0.4,
                    "weight": 1.0,
                }
            )


class TestMetadataRules:
    """Metadata must be a genuine recursively JSON-compatible tree."""

    def test_nested_valid_metadata_accepted(self) -> None:
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(
                metadata={
                    "string": "value",
                    "int": 7,
                    "float": 2.5,
                    "bool": True,
                    "none": None,
                    "list": [1, "two", 3.0, False, None],
                    "nested": {"a": {"b": [1, 2]}},
                }
            )
        )
        nested = request.metadata["nested"]
        assert isinstance(nested, dict)
        inner = nested["a"]
        assert isinstance(inner, dict)
        assert inner["b"] == [1, 2]

    @pytest.mark.parametrize(
        "metadata",
        [
            {"bad": float("nan")},
            {"bad": float("inf")},
            {"bad": float("-inf")},
            {"bad": [1, float("nan")]},
            {"bad": {"deep": float("inf")}},
        ],
    )
    def test_non_finite_nested_values_rejected(self, metadata: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(metadata=metadata)
            )

    def test_decimal_rejected(self) -> None:
        import decimal

        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(metadata={"bad": decimal.Decimal("1.5")})
            )

    @pytest.mark.parametrize(
        "metadata",
        [
            {"bad": (1, 2)},
            {"bad": {1, 2}},
            {"bad": object()},
            {1: "bad-key"},
            {"bad": [object()]},
        ],
    )
    def test_non_json_values_rejected(self, metadata: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            CampaignDecisionPolicyDeclarationRequest.model_validate(
                _global_payload(metadata=metadata)
            )

    def test_metadata_not_mutated(self) -> None:
        metadata: dict[str, object] = {"keep": [1, 2.5, True]}
        request = CampaignDecisionPolicyDeclarationRequest.model_validate(
            _global_payload(metadata=metadata)
        )
        assert metadata == {"keep": [1, 2.5, True]}
        assert request.metadata == {"keep": [1, 2.5, True]}


class TestGeneratedSchema:
    """The generated request schema exposes only caller-owned fields."""

    def test_schema_contains_only_caller_owned_fields(self) -> None:
        schema = CampaignDecisionPolicyDeclarationRequest.model_json_schema()
        properties = set(schema["properties"])
        assert not (properties & set(_FORBIDDEN_FIELDS))
        assert properties == {
            "target_requirement_mode",
            "minimum_target_achievement_probability",
            "objective_target_requirements",
            "minimum_sample_count",
            "tie_tolerance",
            "all_targeted_objectives_are_hard_gates",
            "declared_at",
            "metadata",
        }
        required = set(schema.get("required", []))
        assert {
            "target_requirement_mode",
            "minimum_sample_count",
            "tie_tolerance",
            "all_targeted_objectives_are_hard_gates",
            "declared_at",
        } <= required

    def test_requirement_schema_contains_only_caller_owned_fields(self) -> None:
        schema = ObjectiveTargetRequirementRequest.model_json_schema()
        assert set(schema["properties"]) == {
            "objective_id",
            "minimum_target_achievement_probability",
        }
        assert "weight" not in schema["properties"]
        assert "tail_alpha" not in schema["properties"]
