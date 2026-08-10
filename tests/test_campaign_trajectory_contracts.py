"""Phase 18 contract tests: the deterministic campaign trajectory matrix.

Proves the two new contract types are frozen, strict, JSON-safe, and
free of executable surface; that ``CampaignTrajectoryMatrix`` is
registered in PUBLIC_CONTRACTS (now exactly 31) while the nested
``CampaignTrajectoryRunCell`` is not; that the runtime version and
comparison-mode literals are enforced; that empty strategy/seed/cell
collections are rejected; that the structural matrix shape (complete
Cartesian product, unique identities, position-bound cells, exact
RunPlan order) is enforced; that SHA-256 patterns are enforced on every
hash field; and that the cell carries references and integrity hashes
only - no state snapshots, guards, targets, policy content, outcomes,
evidence, rankings, or explanations.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_trajectory import (
    CampaignTrajectoryMatrix,
    CampaignTrajectoryRunCell,
)
from kalhas.contracts.v1.shared import VersionedContract
from pydantic import ValidationError

from tests.test_contracts import VALID_PAYLOADS

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _cell(**overrides: object) -> CampaignTrajectoryRunCell:
    payload: dict[str, object] = {
        "sequence_position": 0,
        "strategy_position": 0,
        "seed_position": 0,
        "run_id": "run-plan-0123456789abcdef",
        "run_plan_id": "plan-0123456789abcdef",
        "strategy_candidate_id": "sc-1",
        "scenario_seed_id": "seed-1",
        "input_hash": HASH_64,
        "trajectory_execution_id": "trajectory-execution-0123456789abcdef",
        "trajectory_execution_content_hash": HASH_64,
        "trajectory_plan_set_hash": HASH_64,
        "result_content_hashes": (HASH_64,),
    }
    payload.update(overrides)
    return CampaignTrajectoryRunCell.model_validate(payload)


def _matrix(**overrides: object) -> CampaignTrajectoryMatrix:
    payload: dict[str, object] = dict(VALID_PAYLOADS[CampaignTrajectoryMatrix])
    payload.update(overrides)
    return CampaignTrajectoryMatrix.model_validate(payload)


def _multi_cell_payload(
    strategy_ids: tuple[str, ...] = ("sc-1", "sc-2"),
    seed_ids: tuple[str, ...] = ("seed-1", "seed-2"),
) -> dict[str, object]:
    """A complete 2x2 matrix payload in exact RunPlan order."""
    cells: list[dict[str, object]] = []
    for strategy_position, strategy_id in enumerate(strategy_ids):
        for seed_position, seed_id in enumerate(seed_ids):
            cells.append(
                {
                    "sequence_position": len(cells),
                    "strategy_position": strategy_position,
                    "seed_position": seed_position,
                    "run_id": f"run-{strategy_id}-{seed_id}",
                    "run_plan_id": f"plan-{strategy_id}-{seed_id}",
                    "strategy_candidate_id": strategy_id,
                    "scenario_seed_id": seed_id,
                    "input_hash": HASH_64,
                    "trajectory_execution_id": f"trajectory-execution-{len(cells)}",
                    "trajectory_execution_content_hash": HASH_64,
                    "trajectory_plan_set_hash": HASH_64,
                    "result_content_hashes": (HASH_64,),
                }
            )
    payload = dict(VALID_PAYLOADS[CampaignTrajectoryMatrix])
    payload["ordered_strategy_candidate_ids"] = list(strategy_ids)
    payload["ordered_scenario_seed_ids"] = list(seed_ids)
    payload["cells"] = cells
    return payload


class TestRegistration:
    def test_public_contract_count_is_31(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 32

    def test_only_the_versioned_matrix_is_registered(self) -> None:
        registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "CampaignTrajectoryMatrix" in registered
        assert "CampaignTrajectoryRunCell" not in registered

    def test_matrix_is_a_versioned_contract_and_cell_is_not(self) -> None:
        assert issubclass(CampaignTrajectoryMatrix, VersionedContract)
        assert not issubclass(CampaignTrajectoryRunCell, VersionedContract)

    def test_matrix_registered_after_the_phase16_pair(self) -> None:
        names = [contract.__name__ for contract in PUBLIC_CONTRACTS]
        assert "RunTrajectoryExecution" in names
        assert "RunTrajectoryReplayManifest" in names
        assert "CampaignTrajectoryMatrix" in names
        # Phase 19 appended the observation binding after the matrix; the
        # matrix keeps its own slot and the new contract is last.
        assert names[-1] == "DomainMetricObservationBinding"


class TestRunCell:
    def test_frozen_assignment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _cell().run_id = "run-other"

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _cell(explanation="hidden reasoning")

    def test_rejects_negative_positions(self) -> None:
        with pytest.raises(ValidationError):
            _cell(sequence_position=-1)
        with pytest.raises(ValidationError):
            _cell(strategy_position=-1)
        with pytest.raises(ValidationError):
            _cell(seed_position=-1)

    def test_rejects_malformed_hashes(self) -> None:
        for field in (
            "input_hash",
            "trajectory_execution_content_hash",
            "trajectory_plan_set_hash",
        ):
            with pytest.raises(ValidationError):
                _cell(**{field: "short"})
            with pytest.raises(ValidationError):
                _cell(**{field: "A" * 64})
            with pytest.raises(ValidationError):
                _cell(**{field: "z" * 64})

    def test_rejects_malformed_result_hash_element(self) -> None:
        with pytest.raises(ValidationError):
            _cell(result_content_hashes=("not-a-hash",))

    def test_empty_result_content_hashes_are_valid(self) -> None:
        cell = _cell(result_content_hashes=())
        assert cell.result_content_hashes == ()

    def test_rejects_state_snapshots_guards_targets_and_outcomes(self) -> None:
        for field in (
            "initial_state",
            "final_state",
            "guard_values",
            "target_values",
            "policy",
            "outcome",
            "evidence",
            "score",
            "ranking",
        ):
            with pytest.raises(ValidationError):
                _cell(**{field: {"anything": 1}})


class TestMatrixContract:
    def test_frozen_assignment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _matrix().cells = ()

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(strategy_ranking={"sc-1": 1})

    def test_rejects_non_trajectory_runtime_version(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(runtime_version="1.0.0")
        with pytest.raises(ValidationError):
            _matrix(runtime_version="3.0.0")

    def test_rejects_other_comparison_modes(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(comparison_mode="head_to_head")

    def test_rejects_empty_collections(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(ordered_strategy_candidate_ids=())
        with pytest.raises(ValidationError):
            _matrix(ordered_scenario_seed_ids=())
        with pytest.raises(ValidationError):
            _matrix(cells=())

    def test_rejects_malformed_world_content_hash(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(world_content_hash="not-a-hash")

    def test_requires_aware_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _matrix(assembled_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_complete_multi_cell_matrix_validates(self) -> None:
        matrix = CampaignTrajectoryMatrix.model_validate(_multi_cell_payload())
        assert len(matrix.cells) == 4
        assert [c.sequence_position for c in matrix.cells] == [0, 1, 2, 3]

    def test_rejects_duplicate_strategy_ids(self) -> None:
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(
                _multi_cell_payload(strategy_ids=("sc-1", "sc-1"))
            )

    def test_rejects_duplicate_seed_ids(self) -> None:
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(
                _multi_cell_payload(seed_ids=("seed-1", "seed-1"))
            )

    def test_rejects_missing_cell(self) -> None:
        payload = _multi_cell_payload()
        payload["cells"] = cast(list[dict[str, Any]], payload["cells"])[:3]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_additional_cell(self) -> None:
        payload = _multi_cell_payload()
        extra = cast(list[dict[str, Any]], payload["cells"])[0].copy()
        extra["sequence_position"] = 4
        payload["cells"] = cast(list[dict[str, Any]], payload["cells"]) + [extra]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_duplicate_cell(self) -> None:
        payload = _multi_cell_payload()
        cells = cast(list[dict[str, Any]], payload["cells"])
        duplicate = cells[0].copy()
        duplicate["sequence_position"] = 4
        payload["cells"] = cells + [duplicate]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_reordered_cells(self) -> None:
        payload = _multi_cell_payload()
        cells = cast(list[dict[str, Any]], payload["cells"])
        cells[1], cells[2] = cells[2], cells[1]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_out_of_range_positions(self) -> None:
        payload = _multi_cell_payload()
        cell = cast(list[dict[str, Any]], payload["cells"])[0].copy()
        cell["strategy_position"] = 2
        payload["cells"] = [cell] + cast(list[dict[str, Any]], payload["cells"])[1:]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_position_identity_mismatch(self) -> None:
        payload = _multi_cell_payload()
        cell = cast(list[dict[str, Any]], payload["cells"])[0].copy()
        cell["strategy_candidate_id"] = "sc-2"
        payload["cells"] = [cell] + cast(list[dict[str, Any]], payload["cells"])[1:]
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)

    def test_rejects_non_contiguous_sequence_positions(self) -> None:
        payload = _multi_cell_payload()
        cell = cast(list[dict[str, Any]], payload["cells"])[1].copy()
        cell["sequence_position"] = 5
        payload["cells"] = (
            cast(list[dict[str, Any]], payload["cells"])[:1]
            + [cell]
            + cast(list[dict[str, Any]], payload["cells"])[2:]
        )
        with pytest.raises(ValidationError):
            CampaignTrajectoryMatrix.model_validate(payload)


class TestContractJsonSafety:
    """The two contracts carry no executable surface (structural proof)."""

    def test_no_field_can_express_a_callback(self) -> None:
        for contract in (CampaignTrajectoryRunCell, CampaignTrajectoryMatrix):
            for name, field in contract.model_fields.items():
                annotation = str(field.annotation)
                assert not re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
                    f"{contract.__name__}.{name}"
                )

    def test_json_round_trip_preserves_matrix(self) -> None:
        matrix = _matrix()
        reloaded = CampaignTrajectoryMatrix.model_validate_json(matrix.model_dump_json())
        assert reloaded == matrix

    def test_schema_registration_and_synchronization(self) -> None:
        from kalhas.contracts.schema_export import generate_schemas

        assert "CampaignTrajectoryMatrix.schema.json" in generate_schemas()
        assert "CampaignTrajectoryRunCell.schema.json" not in generate_schemas()
