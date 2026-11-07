"""Synthetic exact calibration and re-execution checks."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from typing import Any

import pytest
from kalhas.application import grid_calibration
from kalhas.application.benchmark_baselines import (
    BASELINE_CONFIGURATION_HASH,
    QUANTILE_BASELINE_ID,
    render_baseline_forecasts,
)
from kalhas.application.benchmark_scoring import (
    build_forecast_set,
    parse_forecast_value,
    parse_observed_value,
    resolve_target_values,
    score_forecast_sets,
    score_task,
)
from kalhas.application.grid_calibration import (
    CalibrationCandidateResult,
    build_model_pack_calibration_record,
    compute_model_pack_calibration_record_content_hash,
    evaluate_calibration_candidate,
    verify_model_pack_calibration_record,
)
from kalhas.application.grid_calibration_errors import (
    CalibrationError,
    CalibrationVerificationError,
)
from kalhas.application.mechanism_forecasts import produce_mechanism_forecasts
from kalhas.contracts.v1.benchmark_forecast import ForecastProducer
from kalhas.contracts.v1.model_pack_calibration import CalibrationCell
from kalhas.domain_packs.pan.binding_plan import (
    pan_plan_members,
    pan_plan_variant_selection,
    parse_pan_binding_plan,
)
from kalhas.domain_packs.pan.initial_state import build_pan_initial_state_rule

from tests.test_benchmark_task_engine import chain
from tests.test_model_pack_authoring_verifier import seal
from tests.test_pan_binding_plan import binding_data


@pytest.fixture(scope="module")
def prepared() -> dict[str, Any]:
    raw, source, curated, files, split, protocol = chain()
    data = binding_data()
    data.update(
        protocol_manifest_id=protocol.identifier,
        protocol_content_hash=protocol.content_hash,
        tenant_id=protocol.tenant_id,
    )
    data["denominators"] = [{"series": "alpha", "year": 2020, "value": 1000000}]
    data["observations"] = [
        {
            "target_path": "daily.csv",
            "variant_id": "h-and-c",
            "operator": {"op": "stock_sum", "stocks": ["hospitalized", "intensive_care"]},
        },
        {
            "target_path": "daily.csv",
            "variant_id": "h-only",
            "operator": {"op": "stock_sum", "stocks": ["hospitalized"]},
        },
        {
            "target_path": "weekly.csv",
            "variant_id": "default",
            "operator": {
                "op": "per_100k",
                "inner": {"op": "flow_sum", "flow": "hospital_admissions"},
            },
        },
    ]
    data["payload"]["initial_state_rule"].update(hospital_path="daily.csv", icu_path="daily.csv")
    item = seal(data)
    plan = parse_pan_binding_plan(item)
    content, count, metadata = render_baseline_forecasts(
        QUANTILE_BASELINE_ID, protocol, split, curated, files, "development"
    )
    reference = build_forecast_set(
        forecast_set_id="reference",
        forecast_set_version="1.0.0",
        protocol=protocol,
        partition="development",
        producer=ForecastProducer(
            kind="baseline",
            producer_id="synthetic",
            producer_version="1.0.0",
            configuration_hash=BASELINE_CONFIGURATION_HASH,
        ),
        csv_bytes=content,
        row_count=count,
        created_at=item.declared_at,
        metadata=metadata,
    )
    return dict(
        binding=item,
        members=pan_plan_members(plan, item, "h-only"),
        rule=build_pan_initial_state_rule(item),
        variants=pan_plan_variant_selection(plan, item, "h-only"),
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        raw_bundles={raw.identifier: (raw, source)},
        reference=reference,
        reference_csv=content,
    )


def evaluate(prepared: dict[str, Any], index: int) -> CalibrationCandidateResult:
    args = {key: value for key, value in prepared.items() if key != "members"}
    return evaluate_calibration_candidate(
        candidate_index=index, member=prepared["members"][index - 1], **args
    )


def build(
    prepared: dict[str, Any],
    results: list[CalibrationCandidateResult] | tuple[CalibrationCandidateResult, ...],
    cap: int = 8,
) -> Any:
    return build_model_pack_calibration_record(
        record_id="synthetic",
        record_version="1.0.0",
        binding=prepared["binding"],
        protocol=prepared["protocol"],
        variants=prepared["variants"],
        reference=prepared["reference"],
        results=results,
        max_ensemble_members=cap,
        limitations=("Synthetic calibration only.",),
        calibrated_at=prepared["binding"].declared_at,
        metadata={},
    )


@pytest.fixture(scope="module")
def evaluated(prepared: dict[str, Any]) -> tuple[CalibrationCandidateResult, ...]:
    return tuple(evaluate(prepared, index) for index in range(1, 13))


def test_end_to_end_and_order_independence(
    prepared: dict[str, Any], evaluated: tuple[CalibrationCandidateResult, ...]
) -> None:
    for result in evaluated:
        included = [cell for cell in result.cells if cell.included]
        assert [(cell.path, cell.horizon) for cell in included] == [("weekly.csv", 1)]
        assert result.fallback_count == 0
    record = build(prepared, evaluated)
    verify_model_pack_calibration_record(record, **prepared)
    assert record.qualifying_left_out_count == 0
    for candidate in record.candidates:
        index = candidate.candidate_index
        if index == 12:
            assert (candidate.objective, candidate.rank, candidate.status) == (
                "22.752562",
                1,
                "retained",
            )
        elif index in (2, 3, 5, 6, 8, 9, 11):
            assert candidate.objective == "23.162518"
            assert candidate.rank == (2, 3, 5, 6, 8, 9, 11).index(index) + 2
            assert candidate.status == "retained"
        else:
            assert candidate.objective == "24.597365"
            assert candidate.rank == (1, 4, 7, 10).index(index) + 9
            assert candidate.status == "not_retained"
    assert build(prepared, list(reversed(evaluated))).model_dump_json() == record.model_dump_json()
    shuffled = [evaluated[index - 1] for index in (3, 12, 4, 8, 1, 11, 2, 9, 6, 10, 5, 7)]
    assert build(prepared, shuffled).model_dump_json() == record.model_dump_json()
    assert evaluate(prepared, 1) == evaluated[0]


def test_independent_exact_score(
    prepared: dict[str, Any], evaluated: tuple[CalibrationCandidateResult, ...]
) -> None:
    targets = resolve_target_values(
        prepared["protocol"],
        prepared["split_manifest"],
        prepared["curated_manifest"],
        prepared["curated_files"],
        "development",
    )
    reference_rows = list(csv.reader(io.StringIO(prepared["reference_csv"].decode("utf-8"))))[1:]
    for index, result in enumerate(evaluated, 1):
        args = {
            key: value
            for key, value in prepared.items()
            if key not in {"members", "reference", "reference_csv"}
        }
        _, content = produce_mechanism_forecasts(
            forecast_set_id=f"calibration-candidate-{index}",
            forecast_set_version="1.0.0",
            partition="development",
            created_at=prepared["binding"].declared_at,
            members=(prepared["members"][index - 1],),
            **args,
        )
        rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))[1:]
        candidate_sum, reference_sum = Fraction(), Fraction()
        for row, reference in zip(rows, reference_rows, strict=True):
            observed = parse_observed_value(targets[(row[0], row[1], row[2], int(row[3]))])
            candidate_sum += score_task(
                tuple(parse_forecast_value(value) for value in row[4:]), observed
            ).wis
            reference_sum += score_task(
                tuple(parse_forecast_value(value) for value in reference[4:]), observed
            ).wis
        assert result.objective_exact == candidate_sum / reference_sum


def test_retention_edges_and_missing_objective(prepared: dict[str, Any]) -> None:
    cell = CalibrationCell(path="x.csv", horizon=1, relative_wis="1.000000", included=True)
    excluded = CalibrationCell(path="x.csv", horizon=1, relative_wis=None, included=False)

    def result(index: int, value: Fraction | None) -> CalibrationCandidateResult:
        return CalibrationCandidateResult(
            index,
            f"candidate-{index:02d}",
            "0" * 64,
            "0" * 64,
            value,
            (cell if value is not None else excluded,),
            0,
            0,
        )

    items = [result(index, Fraction(1)) for index in range(1, 9)] + [
        result(9, Fraction(21, 20)),
        result(10, Fraction(21, 20)),
        result(11, Fraction(105001, 100000)),
        result(12, None),
    ]
    record = build(prepared, items)
    assert [item.rank for item in record.candidates[:10]] == list(range(1, 11))
    assert [item.status for item in record.candidates] == ["retained"] * 8 + [
        "qualifying_left_out"
    ] * 2 + ["not_retained", "no_objective"]
    assert record.qualifying_left_out_count == 2
    assert record.candidates[-1].rank is None
    with pytest.raises(CalibrationError) as caught:
        build(prepared, items[1:])
    assert caught.value.reason == "candidate_set_invalid"


def test_score_mismatch(prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    original = score_forecast_sets

    def changed(*args: Any) -> Any:
        return tuple(
            cell.model_copy(update={"relative_wis": "0.000000"})
            if cell.verdict in ("pass", "fail")
            else cell
            for cell in original(*args)
        )

    monkeypatch.setattr(grid_calibration, "score_forecast_sets", changed)
    with pytest.raises(CalibrationError) as caught:
        evaluate(prepared, 1)
    assert caught.value.reason == "score_mismatch"


@pytest.mark.parametrize(
    "reason",
    [
        "invalid_manifest",
        "binding_invalid",
        "binding_reference_mismatch",
        "protocol_reference_mismatch",
        "tenant_mismatch",
        "lock_order_invalid",
        "reference_mismatch",
        "content_hash_mismatch",
        "variant_mismatch",
        "members_mismatch",
        "reexecution_mismatch",
    ],
)
def test_verifier_reasons(
    prepared: dict[str, Any], evaluated: tuple[CalibrationCandidateResult, ...], reason: str
) -> None:
    record = build(prepared, evaluated)
    args = dict(prepared)
    if reason == "invalid_manifest":
        record = record.model_copy(update={"max_ensemble_members": 0})
    elif reason == "binding_invalid":
        args["binding"] = args["binding"].model_copy(update={"content_hash": "1" * 64})
    elif reason == "binding_reference_mismatch":
        record = record.model_copy(update={"binding_content_hash": "1" * 64})
    elif reason == "protocol_reference_mismatch":
        record = record.model_copy(update={"protocol_content_hash": "1" * 64})
    elif reason == "tenant_mismatch":
        record = record.model_copy(update={"tenant_id": "other"})
    elif reason == "lock_order_invalid":
        record = record.model_copy(
            update={"calibrated_at": args["binding"].declared_at - timedelta(seconds=1)}
        )
    elif reason == "reference_mismatch":
        args["reference"] = args["reference"].model_copy(update={"content_hash": "1" * 64})
    elif reason == "content_hash_mismatch":
        record = record.model_copy(update={"content_hash": "1" * 64})
    elif reason == "variant_mismatch":
        args["variants"] = {**args["variants"], "daily.csv": "h-and-c"}
    elif reason == "members_mismatch":
        args["members"] = args["members"][:-1]
    elif reason == "reexecution_mismatch":
        args["members"] = (
            replace(args["members"][0], action={"intervention_intensity_bps": 1}),
            *args["members"][1:],
        )
    if reason in {
        "binding_reference_mismatch",
        "protocol_reference_mismatch",
        "tenant_mismatch",
        "lock_order_invalid",
    }:
        record = record.model_copy(
            update={"content_hash": compute_model_pack_calibration_record_content_hash(record)}
        )
    with pytest.raises(CalibrationVerificationError) as caught:
        verify_model_pack_calibration_record(record, **args)
    assert caught.value.reason == reason
