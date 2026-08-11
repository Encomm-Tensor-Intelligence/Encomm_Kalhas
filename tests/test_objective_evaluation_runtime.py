"""Phase 23 pure runtime tests: exact evaluation semantics and the deterministic builder.

Proves the one direction-aware evaluation definition with exact
expectations on every boundary: minimize/maximize below/equal/above
target, reach below-target outside tolerance, lower tolerance
boundary, inside tolerance, exact target, upper tolerance boundary,
and above-target outside tolerance - positive delta is always adverse,
zero is the boundary, negative is acceptable; optimization-only
objectives (no target) carry ``None`` evaluation fields; raw integers
stay integers and raw floats stay floats; the normalized violation is
exactly ``max(0, delta) / scale``; overflow and non-finite derived
values reject the complete matrix; and the pure builder derives the
complete matrix from a completely verified Phase 21 observation matrix
and an exact evaluation profile - deterministic identifier/hash/
``evaluated_at``, byte-identical repeated builds, exact strategy-major,
seed-minor, objective-minor ordering in scenario objective order, and
the full tamper matrix (tenant/scenario mismatches, re-derived source
identity/hash failures, missing metric observations, bool/NaN/Infinity
validator-bypass tampering, huge integers, wrong-kind values) with no
partial result. Tampering is always self-consistent (content hash
recomputed) so exactly the check under test fires, and never mutates
the store.
"""

from __future__ import annotations

import warnings

import pytest
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.objective_evaluation_errors import (
    CampaignObjectiveEvaluationMatrixIntegrityError,
)
from kalhas.application.objective_evaluation_runtime import (
    build_campaign_objective_evaluation_matrix,
    campaign_objective_evaluation_matrix_content_hash,
)
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ObjectiveObservationEvaluation,
    ScenarioEvaluationProfile,
)
from pydantic import ValidationError

from tests.phase4_helpers import NOW
from tests.phase23_helpers import (
    build_observation_matrix,
    build_profile,
    replace_evaluation_cell,
    self_consistent_profile_copy,
    verified_evaluation_campaign,
)


def _single_objective_profile(
    *,
    direction: str,
    target: float | None,
    scale: float = 10.0,
    tolerance: float | None = None,
    objective_id: str = "obj-1",
    metric_id: str = "m-1",
    metric_unit: str | None = None,
    weight: float = 1.0,
) -> ScenarioEvaluationProfile:
    """A one-binding profile for exact boundary evaluations.

    The metric unit defaults to the authoritative scenario unit of the
    bound metric (m-1 is ``units``, m-2 is ``percent``) so the binding
    always agrees with the observation matrix the builder derives from.
    """
    if metric_unit is None:
        metric_unit = "percent" if metric_id == "m-2" else "units"
    return build_profile(
        bindings=[
            {
                "objective_id": objective_id,
                "metric_id": metric_id,
                "direction": direction,
                "target": target,
                "weight": weight,
                "metric_unit": metric_unit,
                "reach_tolerance": tolerance,
                "normalization_scale": scale,
            }
        ]
    )


def _build(
    *,
    profile: ScenarioEvaluationProfile | None = None,
    matrix: CampaignMetricObservationMatrix | None = None,
) -> CampaignObjectiveEvaluationMatrix:
    """Build through the pure builder with default verified artifacts."""
    return build_campaign_objective_evaluation_matrix(
        profile=profile if profile is not None else build_profile(),
        observation_matrix=matrix if matrix is not None else build_observation_matrix(),
    )


def _evaluate_first_cell(
    *,
    direction: str,
    target: float | None,
    raw_value: int | float,
    scale: float = 10.0,
    tolerance: float | None = None,
    metric_id: str = "m-2",
) -> ObjectiveObservationEvaluation:
    """Build a 1x1x1 matrix and return the single cell's evaluation fields.

    ``m-2`` is the ``number``-kind metric, so arbitrary float raw values
    are contract-valid inputs for the boundary matrix.
    """
    profile = _single_objective_profile(
        direction=direction,
        target=target,
        scale=scale,
        tolerance=tolerance,
        metric_id=metric_id,
    )
    matrix = build_observation_matrix(raw_values={(0, 0, metric_id): raw_value})
    result = _build(profile=profile, matrix=matrix)
    return result.cells[0]


def _tamper_raw_value(
    matrix: CampaignMetricObservationMatrix,
    cell_index: int,
    metric_position: int,
    raw_value: object,
) -> CampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one raw value validator-bypassed.

    The observation and cell are replaced via ``model_copy`` (validators
    bypassed) and the matrix content hash is recomputed over the tampered
    content, so exactly the builder's raw-value check under test fires.
    """
    from kalhas.application.campaign_metric_observation_runtime import (
        campaign_metric_observation_matrix_content_hash,
    )

    cell = matrix.cells[cell_index]
    observations = list(cell.observations)
    observations[metric_position] = observations[metric_position].model_copy(
        update={"raw_value": raw_value}
    )
    tampered_cell = cell.model_copy(update={"observations": tuple(observations)})
    cells = matrix.cells[:cell_index] + (tampered_cell,) + matrix.cells[cell_index + 1 :]
    tampered = matrix.model_copy(update={"cells": cells})
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        digest = campaign_metric_observation_matrix_content_hash(tampered)
    return tampered.model_copy(update={"content_hash": digest})


def _tamper_metric_unit(
    matrix: CampaignMetricObservationMatrix,
    cell_index: int,
    metric_position: int,
    metric_unit: str,
) -> CampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one observation unit changed.

    The observation is replaced via ``model_copy`` (validators bypassed)
    and the matrix content hash is recomputed over the tampered content,
    so exactly the builder's metric-unit equality check under test fires
    (the matrix contract itself carries no unit cross-check).
    """
    from kalhas.application.campaign_metric_observation_runtime import (
        campaign_metric_observation_matrix_content_hash,
    )

    cell = matrix.cells[cell_index]
    observations = list(cell.observations)
    observations[metric_position] = observations[metric_position].model_copy(
        update={"metric_unit": metric_unit}
    )
    tampered_cell = cell.model_copy(update={"observations": tuple(observations)})
    cells = matrix.cells[:cell_index] + (tampered_cell,) + matrix.cells[cell_index + 1 :]
    tampered = matrix.model_copy(update={"cells": cells})
    digest = campaign_metric_observation_matrix_content_hash(tampered)
    return tampered.model_copy(update={"content_hash": digest})


class TestSignedTargetDeltaBoundaries:
    """Positive = adverse, zero = boundary, negative = acceptable, per direction."""

    @pytest.mark.parametrize(
        ("raw_value", "expected_delta", "expected_achieved", "expected_violation"),
        [
            (90.0, -10.0, True, 0.0),  # below target: negative, acceptable
            (100.0, 0.0, True, 0.0),  # exactly on target: zero, boundary
            (110.0, 10.0, False, 1.0),  # above target: positive, adverse
        ],
    )
    def test_minimize(
        self,
        raw_value: float,
        expected_delta: float,
        expected_achieved: bool,
        expected_violation: float,
    ) -> None:
        cell = _evaluate_first_cell(direction="minimize", target=100.0, raw_value=raw_value)
        assert cell.signed_target_delta == expected_delta
        assert cell.target_achieved is expected_achieved
        assert cell.normalized_target_violation == expected_violation

    @pytest.mark.parametrize(
        ("raw_value", "expected_delta", "expected_achieved", "expected_violation"),
        [
            (110.0, -10.0, True, 0.0),  # above target: negative, acceptable
            (100.0, 0.0, True, 0.0),  # exactly on target: zero, boundary
            (90.0, 10.0, False, 1.0),  # below target: positive, adverse
        ],
    )
    def test_maximize(
        self,
        raw_value: float,
        expected_delta: float,
        expected_achieved: bool,
        expected_violation: float,
    ) -> None:
        cell = _evaluate_first_cell(direction="maximize", target=100.0, raw_value=raw_value)
        assert cell.signed_target_delta == expected_delta
        assert cell.target_achieved is expected_achieved
        assert cell.normalized_target_violation == expected_violation

    @pytest.mark.parametrize(
        ("raw_value", "expected_delta", "expected_achieved", "expected_violation"),
        [
            (40.0, 5.0, False, 0.5),  # below target, outside tolerance: positive, adverse
            (45.0, 0.0, True, 0.0),  # lower tolerance boundary: zero
            (48.0, -3.0, True, 0.0),  # inside tolerance: negative, acceptable
            (50.0, -5.0, True, 0.0),  # exact target: negative (tolerance below), acceptable
            (55.0, 0.0, True, 0.0),  # upper tolerance boundary: zero
            (60.0, 5.0, False, 0.5),  # above target, outside tolerance: positive, adverse
        ],
    )
    def test_reach(
        self,
        raw_value: float,
        expected_delta: float,
        expected_achieved: bool,
        expected_violation: float,
    ) -> None:
        cell = _evaluate_first_cell(
            direction="reach", target=50.0, tolerance=5.0, scale=10.0, raw_value=raw_value
        )
        assert cell.signed_target_delta == expected_delta
        assert cell.target_achieved is expected_achieved
        assert cell.normalized_target_violation == expected_violation

    def test_minimize_above_target_is_never_zero_violation(self) -> None:
        """A minimize value above its target has positive violation, never zero."""
        cell = _evaluate_first_cell(direction="minimize", target=100.0, raw_value=100.5)
        assert cell.signed_target_delta == 0.5
        assert cell.normalized_target_violation == 0.05
        assert cell.target_achieved is False


class TestOptimizationOnly:
    def test_maximize_without_target_has_none_evaluation_fields(self) -> None:
        cell = _evaluate_first_cell(direction="maximize", target=None, raw_value=42.0)
        assert cell.target_achieved is None
        assert cell.signed_target_delta is None
        assert cell.normalized_target_violation is None

    def test_minimize_without_target_has_none_evaluation_fields(self) -> None:
        cell = _evaluate_first_cell(direction="minimize", target=None, raw_value=42.0)
        assert cell.target_achieved is None
        assert cell.signed_target_delta is None
        assert cell.normalized_target_violation is None


class TestExactNumericPreservation:
    def test_raw_integer_stays_integer(self) -> None:
        matrix = build_observation_matrix(raw_values={(0, 0, "m-1"): 7})
        result = _build(matrix=matrix)
        dumped = result.model_dump(mode="json")["cells"][0]["raw_value"]
        assert dumped == 7 and isinstance(dumped, int)

    def test_raw_float_stays_float(self) -> None:
        matrix = build_observation_matrix(raw_values={(0, 0, "m-2"): 7.0})
        result = _build(matrix=matrix)
        # The default profile binds m-2 for obj-a (cell index 1).
        dumped = result.model_dump(mode="json")["cells"][1]["raw_value"]
        assert dumped == 7.0 and isinstance(dumped, float)

    def test_normalized_violation_matches_expression(self) -> None:
        cell = _evaluate_first_cell(
            direction="minimize", target=100.0, raw_value=130.0, scale=100.0
        )
        assert cell.normalized_target_violation == max(0.0, 130.0 - 100.0) / 100.0


class TestDeterminism:
    def test_byte_identical_repeated_builds(self) -> None:
        first = _build()
        second = _build()
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.identifier == second.identifier
        assert first.content_hash == second.content_hash

    def test_evaluated_at_is_source_assembled_at(self) -> None:
        matrix = build_observation_matrix()
        result = _build(matrix=matrix)
        assert result.evaluated_at == matrix.assembled_at == NOW

    def test_content_hash_is_self_consistent(self) -> None:
        result = _build()
        assert result.content_hash == campaign_objective_evaluation_matrix_content_hash(result)

    def test_identifier_is_independent_of_content_hash(self) -> None:
        """The matrix identifier derives from the identity payload, never its hash.

        Two matrices with the same campaign/world/runtime/source/profile
        identity payload share the identifier even when their content
        (and therefore their content hashes) differ.
        """
        first = _build()
        second = build_campaign_objective_evaluation_matrix(
            profile=self_consistent_profile_copy(build_profile(), metadata={"note": "different"}),
            observation_matrix=build_observation_matrix(),
        )
        assert first.identifier == second.identifier
        assert first.identifier.startswith("objective-evaluation-matrix-")
        assert first.content_hash != second.content_hash


class TestMatrixShape:
    def test_default_full_campaign_shape_and_values(self) -> None:
        _store, matrix, _run_ids = verified_evaluation_campaign()
        assert len(matrix.ordered_strategy_candidate_ids) == 5
        assert matrix.ordered_objective_ids == ("obj-b", "obj-a", "obj-c")
        assert len(matrix.cells) == 5 * 1 * 3 == 15
        for position, cell in enumerate(matrix.cells):
            assert cell.sequence_position == position
            expected_index = (
                cell.strategy_position * 1 + cell.seed_position
            ) * 3 + cell.objective_position
            assert expected_index == position

    def test_multi_seed_cartesian_completeness(self) -> None:
        from tests.phase4_helpers import build_seed

        seeds = (build_seed(identifier="seed-1"), build_seed(identifier="seed-2"))
        _store, matrix, _run_ids = verified_evaluation_campaign(seeds=seeds)
        assert len(matrix.ordered_scenario_seed_ids) == 2
        assert len(matrix.cells) == 5 * 2 * 3 == 30

    def test_exact_default_evaluation_values(self) -> None:
        _store, matrix, _run_ids = verified_evaluation_campaign()
        first_strategy_cells = matrix.cells[:3]
        # obj-b: minimize target 100, metric m-1 raw 1 -> delta -99, achieved
        assert first_strategy_cells[0].objective_id == "obj-b"
        assert first_strategy_cells[0].raw_value == 1
        assert first_strategy_cells[0].signed_target_delta == 1 - 100.0
        assert first_strategy_cells[0].target_achieved is True
        assert first_strategy_cells[0].normalized_target_violation == 0.0
        # obj-a: maximize, no target, metric m-2 raw 1.5 -> all None
        assert first_strategy_cells[1].objective_id == "obj-a"
        assert first_strategy_cells[1].raw_value == 1.5
        assert first_strategy_cells[1].target_achieved is None
        assert first_strategy_cells[1].signed_target_delta is None
        assert first_strategy_cells[1].normalized_target_violation is None
        # obj-c: reach target 50 tolerance 5, metric m-1 raw 1 -> delta 44, not achieved
        assert first_strategy_cells[2].objective_id == "obj-c"
        assert first_strategy_cells[2].signed_target_delta == abs(1 - 50.0) - 5.0
        assert first_strategy_cells[2].target_achieved is False
        assert first_strategy_cells[2].normalized_target_violation == 44.0 / 50.0

    def test_source_provenance_carried_into_matrix(self) -> None:
        _store, matrix, _run_ids = verified_evaluation_campaign()
        assert matrix.source_metric_observation_matrix_id.startswith("metric-observation-matrix-")
        assert len(matrix.source_metric_observation_matrix_content_hash) == 64
        assert matrix.evaluation_profile_id.startswith("evaluation-profile-")
        assert len(matrix.evaluation_profile_content_hash) == 64
        assert len(matrix.scenario_content_hash) == 64
        assert len(matrix.world_content_hash) == 64
        assert matrix.runtime_version == "2.0.0"
        assert matrix.comparison_mode == "identical_conditions"


class TestSourceVerification:
    def test_unsupported_runtime_rejected(self) -> None:
        matrix = build_observation_matrix().model_copy(update={"runtime_version": "3.0.0"})
        with pytest.raises(UnsupportedRuntimeVersionError):
            _build(matrix=matrix)

    def test_tenant_mismatch_rejected(self) -> None:
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=build_profile(tenant_id="tenant-other"))

    def test_scenario_mismatch_rejected(self) -> None:
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=build_profile(scenario_id="scenario-other"))

    def test_source_matrix_identifier_tamper_rejected(self) -> None:
        matrix = build_observation_matrix().model_copy(update={"identifier": "forged"})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_source_matrix_content_hash_tamper_rejected(self) -> None:
        matrix = build_observation_matrix().model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_profile_identifier_tamper_rejected(self) -> None:
        profile = build_profile().model_copy(update={"identifier": "forged"})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=profile)

    def test_profile_content_hash_tamper_rejected(self) -> None:
        profile = build_profile().model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=profile)

    def test_missing_bound_metric_rejected(self) -> None:
        # obj-b binds m-3, which the observation matrix does not carry.
        profile = build_profile(
            bindings=[
                {
                    "objective_id": "obj-1",
                    "metric_id": "m-3",
                    "direction": "minimize",
                    "target": 100.0,
                    "weight": 1.0,
                    "metric_unit": None,
                    "reach_tolerance": None,
                    "normalization_scale": 100.0,
                }
            ]
        )
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=profile)

    def test_self_consistent_profile_tamper_changes_result_only_via_checked_fields(
        self,
    ) -> None:
        # A self-consistent tamper of the target snapshot flows into the
        # evaluation; the query layer (stored vs embedded equality) is
        # the authoritative defense, verified in the query suite.
        profile = self_consistent_profile_copy(build_profile(), metadata={"tampered": True})
        result = _build(profile=profile)
        assert result.evaluation_profile_content_hash == profile.content_hash


class TestOverflowAndNonFinite:
    def test_huge_integer_raw_value_rejects_complete_matrix(self) -> None:
        matrix = build_observation_matrix(raw_values={(0, 0, "m-1"): 10**400})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_infinite_violation_rejects_complete_matrix(self) -> None:
        # 1e308 / 1e-308 overflows to infinity; the matrix is rejected.
        profile = _single_objective_profile(
            direction="minimize", target=100.0, scale=1e-308, metric_id="m-2"
        )
        matrix = build_observation_matrix(raw_values={(0, 0, "m-2"): 1e308})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            build_campaign_objective_evaluation_matrix(profile=profile, observation_matrix=matrix)

    def test_bool_raw_value_validator_bypass_rejected(self) -> None:
        matrix = _tamper_raw_value(build_observation_matrix(), 0, 0, True)
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_nan_raw_value_validator_bypass_rejected(self) -> None:
        matrix = _tamper_raw_value(build_observation_matrix(), 0, 0, float("nan"))
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_string_raw_value_validator_bypass_rejected(self) -> None:
        matrix = _tamper_raw_value(build_observation_matrix(), 0, 0, "91")
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(matrix=matrix)

    def test_bool_target_validator_bypass_rejected(self) -> None:
        profile = build_profile()
        binding = profile.bindings[0].model_copy(update={"target": True})
        tampered_profile = profile.model_copy(
            update={"bindings": (binding,) + profile.bindings[1:]}
        )
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=tampered_profile)

    def test_nan_scale_validator_bypass_rejected(self) -> None:
        profile = build_profile()
        binding = profile.bindings[0].model_copy(update={"normalization_scale": float("nan")})
        tampered_profile = profile.model_copy(
            update={"bindings": (binding,) + profile.bindings[1:]}
        )
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            _build(profile=tampered_profile)


class TestEvaluatedMatrixContract:
    def test_builder_output_validates_against_contract(self) -> None:
        result = _build()
        reloaded = CampaignObjectiveEvaluationMatrix.model_validate_json(result.model_dump_json())
        assert reloaded == result

    def test_out_of_range_cell_tamper_breaks_contract(self) -> None:
        result = _build()
        tampered = replace_evaluation_cell(
            result, 0, strategy_position=7, strategy_candidate_id="sc-7"
        )
        with pytest.raises(ValidationError):
            CampaignObjectiveEvaluationMatrix.model_validate_json(tampered.model_dump_json())


class TestBuilderInputRevalidation:
    """Validator-bypassed inputs never reach builder arithmetic.

    Every failure is the typed Phase 23 integrity error - never an
    ``IndexError``, ``TypeError``, or untyped exception - and no input
    is ever mutated.
    """

    def _expect_typed_rejection(
        self,
        profile: ScenarioEvaluationProfile | None = None,
        matrix: CampaignMetricObservationMatrix | None = None,
    ) -> None:
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            build_campaign_objective_evaluation_matrix(
                profile=profile if profile is not None else build_profile(),
                observation_matrix=(matrix if matrix is not None else build_observation_matrix()),
            )

    def test_out_of_range_source_cell_position_rejected(self) -> None:
        matrix = build_observation_matrix()
        tampered_cell = matrix.cells[0].model_copy(update={"strategy_position": 99})
        tampered = matrix.model_copy(update={"cells": (tampered_cell,) + matrix.cells[1:]})
        self._expect_typed_rejection(matrix=tampered)

    def test_reordered_source_cells_rejected(self) -> None:
        # A two-strategy source matrix has two cells, so the swap is a
        # real reorder; the builder must reject it with the typed
        # integrity error (never an IndexError or untyped exception).
        matrix = build_observation_matrix(strategy_ids=("sc-1", "sc-2"))
        assert len(matrix.cells) >= 2
        cells = matrix.cells
        tampered = matrix.model_copy(update={"cells": (cells[1], cells[0]) + cells[2:]})
        self._expect_typed_rejection(matrix=tampered)

    def test_invalid_profile_direction_rejected(self) -> None:
        profile = build_profile()
        binding = profile.bindings[0].model_copy(update={"direction": "optimize"})
        tampered = profile.model_copy(update={"bindings": (binding,) + profile.bindings[1:]})
        self._expect_typed_rejection(profile=tampered)

    def test_tolerance_on_minimize_profile_rejected(self) -> None:
        profile = build_profile()
        binding = profile.bindings[0].model_copy(update={"reach_tolerance": 5.0})
        tampered = profile.model_copy(update={"bindings": (binding,) + profile.bindings[1:]})
        self._expect_typed_rejection(profile=tampered)

    def test_source_metric_unit_mismatch_rejected(self) -> None:
        # Self-consistent tamper: the matrix content hash is recomputed,
        # so the revalidation passes and the builder's exact unit
        # equality check fires.
        matrix = _tamper_metric_unit(build_observation_matrix(), 0, 0, "forged-units")
        self._expect_typed_rejection(matrix=matrix)

    def test_inputs_never_mutated_on_rejection(self) -> None:
        profile = build_profile()
        matrix = build_observation_matrix()
        profile_before = profile.model_dump(mode="json")
        matrix_before = matrix.model_dump(mode="json")
        tampered_cell = matrix.cells[0].model_copy(update={"strategy_position": 99})
        tampered = matrix.model_copy(update={"cells": (tampered_cell,) + matrix.cells[1:]})
        with pytest.raises(CampaignObjectiveEvaluationMatrixIntegrityError):
            build_campaign_objective_evaluation_matrix(profile=profile, observation_matrix=tampered)
        assert profile.model_dump(mode="json") == profile_before
        assert matrix.model_dump(mode="json") == matrix_before
        assert tampered.cells[0].strategy_position == 99  # tampered input unchanged too
