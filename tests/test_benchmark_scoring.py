"""Exact scoring and end-to-end synthetic forecast fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from fractions import Fraction
from typing import Any, Literal

import pytest
from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_scoring import (
    ForecastRow,
    build_benchmark_score_report,
    build_forecast_set,
    decide_verdict,
    parse_forecast_value,
    parse_observed_value,
    quantize_half_even,
    render_forecast_csv,
    resolve_target_values,
    score_forecast_sets,
    score_task,
    summarize_task_scores,
    weighted_interval_score,
)
from kalhas.application.benchmark_task_engine import derive_benchmark_tasks
from kalhas.contracts.v1.benchmark_forecast import ForecastProducer

from tests.test_benchmark_task_engine import DAILY, chain

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def prepared(
    partition: str = "development",
    candidate_value: str = "11",
    reference_value: str = "10",
    daily: bytes = DAILY,
) -> tuple[Any, ...]:
    raw, raw_files, curated, files, split, protocol = chain(daily=daily)
    tasks = [
        t
        for t in derive_benchmark_tasks(protocol, split, curated, files, partition)
        if t.status == "evaluable"
    ]

    def artifact(
        identifier: str,
        value: str,
        kind: Literal["baseline", "model_pack_mechanism"],
        producer_id: str,
    ) -> tuple[Any, bytes]:
        rows = [ForecastRow(t.path, t.series, t.origin, t.horizon, (value,) * 7) for t in tasks]
        content = render_forecast_csv(rows)
        producer = ForecastProducer(
            kind=kind,
            producer_id=producer_id,
            producer_version="1.0.0",
            configuration_hash="0" * 64,
        )
        return build_forecast_set(
            forecast_set_id=identifier,
            forecast_set_version="1.0.0",
            protocol=protocol,
            partition=partition,
            producer=producer,
            csv_bytes=content,
            row_count=len(rows),
            created_at=NOW,
            metadata={},
        ), content

    candidate, candidate_csv = artifact(
        "candidate", candidate_value, "model_pack_mechanism", "candidate"
    )
    reference, reference_csv = artifact("reference", reference_value, "baseline", "synthetic")
    return (
        raw,
        raw_files,
        curated,
        files,
        split,
        protocol,
        candidate,
        candidate_csv,
        reference,
        reference_csv,
    )


@pytest.mark.parametrize(
    "value,expected,text,ae,in50,in95",
    [
        ("8", Fraction(181, 70), "2.585714", Fraction(4), False, False),
        ("4", Fraction(3, 10), "0.300000", Fraction(0), True, True),
        ("0.5", Fraction(73, 35), "2.085714", Fraction(7, 2), False, False),
        ("3", Fraction(31, 70), "0.442857", Fraction(1), True, True),
        ("7", Fraction(111, 70), "1.585714", Fraction(3), False, True),
        ("1", Fraction(111, 70), "1.585714", Fraction(3), False, True),
    ],
)
def test_exact_goldens(
    value: str, expected: Fraction, text: str, ae: Fraction, in50: bool, in95: bool
) -> None:
    q = tuple(Fraction(i) for i in range(1, 8))
    score = score_task(q, Fraction(value))
    assert type(score.wis) is Fraction
    assert (
        score.wis,
        quantize_half_even(score.wis),
        score.absolute_error,
        score.in_50,
        score.in_95,
    ) == (expected, text, ae, in50, in95)


def test_point_and_rounding_once() -> None:
    assert weighted_interval_score((Fraction(4),) * 7, Fraction(7)) == Fraction(3)
    scores = [
        score_task((Fraction(0),) * 7, Fraction(x)) for x in ("0.0000006", "0.0000006", "0.0000001")
    ]
    assert summarize_task_scores(scores).mean_wis == "0.000000"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.0000005", "0.000000"),
        ("0.0000015", "0.000002"),
        ("0.0000025", "0.000002"),
        ("2.5000005", "2.500000"),
        ("-0.0000005", "0.000000"),
        ("-0.0000015", "-0.000002"),
        ("-0.0000001", "0.000000"),
    ],
)
def test_rounding(value: str, expected: str) -> None:
    assert quantize_half_even(Fraction(value)) == expected


@pytest.mark.parametrize(
    "text", ["1e3", "1/3", " 1", "1 ", "1\n", "+1", ".5", "1.", "١", "", "nan", "inf"]
)
def test_decimal_grammar(text: str) -> None:
    for parser in (parse_forecast_value, parse_observed_value):
        with pytest.raises(BenchmarkError):
            parser(text)
    with pytest.raises(BenchmarkError):
        parse_forecast_value("1.0000000")
    assert parse_observed_value("1.0000000") == Fraction(1)


def test_exact_verdict() -> None:
    assert decide_verdict(1, 1, Fraction(8999999, 10000000), Fraction(1), "0.9") == (
        "0.900000",
        "pass",
        "below_threshold",
    )
    assert decide_verdict(1, 1, Fraction(9, 10), Fraction(1), "0.9")[1] == "fail"
    assert decide_verdict(0, 1, Fraction(), Fraction(), "0.9") == (
        None,
        "inconclusive",
        "insufficient_evaluable_tasks",
    )
    assert decide_verdict(1, 2, Fraction(1), Fraction(2), "0.9") == (
        "0.500000",
        "inconclusive",
        "insufficient_evaluable_tasks",
    )
    assert decide_verdict(1, 1, Fraction(1), Fraction(), "0.9") == (
        None,
        "inconclusive",
        "reference_score_zero",
    )


def test_synthetic_report() -> None:
    raw, raw_files, curated, files, split, protocol, c, cb, r, rb = prepared()
    cells = score_forecast_sets(protocol, split, curated, files, c, cb, r, rb)
    assert [(x.path, x.horizon, x.evaluable_tasks) for x in cells] == [
        ("daily.csv", 1, 0),
        ("daily.csv", 2, 0),
        ("weekly.csv", 1, 1),
        ("weekly.csv", 2, 0),
    ]
    cell = cells[2]
    assert cell.candidate is not None and cell.reference is not None
    assert cell.candidate.mean_wis == "1.000000"
    assert cell.reference.mean_wis == "2.000000"
    assert (Fraction(cell.candidate.mean_wis), Fraction(cell.reference.mean_wis)) == (
        Fraction(1),
        Fraction(2),
    )
    assert [(x.inadmissible_origin_tasks, x.insufficient_history_tasks) for x in cells] == [
        (1, 0),
        (0, 2),
        (0, 1),
        (0, 1),
    ]
    assert cell.candidate.mean_absolute_error == "1.000000"
    assert cell.reference.mean_absolute_error == "2.000000"
    assert (cell.candidate.coverage_50, cell.candidate.coverage_95) == ("0.000000", "0.000000")
    assert (cell.reference.coverage_50, cell.reference.coverage_95) == ("0.000000", "0.000000")
    assert (cell.relative_wis, cell.verdict) == ("0.500000", "pass")
    report = build_benchmark_score_report(
        report_id="report",
        report_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        candidate=c,
        candidate_csv=cb,
        reference=r,
        reference_csv=rb,
        limitations=("Synthetic only",),
        scored_at=NOW,
        metadata={},
    )
    assert report.cells == cells
    targets = resolve_target_values(protocol, split, curated, files, "development")
    assert list(targets.values()) == ["12"]
    assert all(key[2] != "2020-01-02" and value != "NA" for key, value in targets.items())


@pytest.mark.parametrize(
    "candidate_value,reference_value,expected",
    [
        ("11", "10", "pass"),
        ("9", "10", "fail"),
        ("11", "12", "inconclusive"),
    ],
)
def test_scored_verdict_branches(candidate_value: str, reference_value: str, expected: str) -> None:
    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared(
        candidate_value=candidate_value, reference_value=reference_value
    )
    cells = score_forecast_sets(protocol, split, curated, files, candidate, cb, reference, rb)
    assert cells[2].verdict == expected
    if reference_value == "12":
        assert cells[2].verdict_reason == "reference_score_zero"
        assert cells[2].relative_wis is None
    assert all(
        cell.candidate is None and cell.reference is None for cell in (cells[0], cells[1], cells[3])
    )


def test_holdout_invariance_and_missing_presence() -> None:
    changed = DAILY.replace(b"alpha,h,2020-01-04,4", b"alpha,h,2020-01-04,400")
    for partition in ("development", "validation"):

        def run(daily: bytes, part: str = partition) -> tuple[Any, Any, Any]:
            _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared(
                part, daily=daily
            )
            tasks = derive_benchmark_tasks(protocol, split, curated, files, part)
            values = resolve_target_values(protocol, split, curated, files, part)
            cells = score_forecast_sets(
                protocol, split, curated, files, candidate, cb, reference, rb
            )
            return tasks, values, cells

        assert run(DAILY) == run(changed)
        assert "4" not in run(DAILY)[1].values()
        assert "400" not in run(changed)[1].values()
    _, _, curated, files, split, protocol, _, _, _, _ = prepared()
    absent = derive_benchmark_tasks(protocol, split, curated, files, "development")
    _, _, curated2, files2, split2, protocol2, _, _, _, _ = prepared(
        daily=DAILY.replace(b"2020-01-02,NA", b"2020-01-02,2")
    )
    present = derive_benchmark_tasks(protocol2, split2, curated2, files2, "development")
    assert not any(t.origin == "2020-01-02" or t.target_time == "2020-01-02" for t in absent)
    assert any(t.origin == "2020-01-02" and t.status == "evaluable" for t in present)
    assert (
        next(t.status for t in absent if t.origin == "2020-01-03" and t.horizon == 2)
        == "insufficient_history"
    )
    assert (
        next(t.status for t in present if t.origin == "2020-01-03" and t.horizon == 2)
        == "evaluable"
    )


def test_too_few_tasks_retains_relative_score() -> None:
    from kalhas.application.benchmark_protocol_verifier import (
        compute_benchmark_protocol_content_hash,
    )
    from kalhas.application.benchmark_scoring import compute_forecast_set_content_hash

    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared()
    targets = tuple(t.model_copy(update={"minimum_evaluable_tasks": 2}) for t in protocol.targets)
    updated = protocol.model_copy(update={"targets": targets})
    updated = updated.model_copy(
        update={"content_hash": compute_benchmark_protocol_content_hash(updated)}
    )
    candidate = candidate.model_copy(update={"protocol_content_hash": updated.content_hash})
    candidate = candidate.model_copy(
        update={"content_hash": compute_forecast_set_content_hash(candidate)}
    )
    reference = reference.model_copy(update={"protocol_content_hash": updated.content_hash})
    reference = reference.model_copy(
        update={"content_hash": compute_forecast_set_content_hash(reference)}
    )
    cell = score_forecast_sets(updated, split, curated, files, candidate, cb, reference, rb)[2]
    assert (cell.verdict, cell.verdict_reason, cell.relative_wis) == (
        "inconclusive",
        "insufficient_evaluable_tasks",
        "0.500000",
    )


def test_header_only_and_roundtrip_with_quoted_series() -> None:
    from kalhas.application.benchmark_protocol_verifier import (
        compute_benchmark_protocol_content_hash,
    )
    from kalhas.application.benchmark_scoring import _parse_csv, compute_forecast_set_content_hash

    row = ForecastRow("weekly.csv", "alpha,beta", "2020-W01", 1, ("1",) * 7)
    data = render_forecast_csv([row])
    assert _parse_csv(data)[0][1] == "alpha,beta"
    _, _, curated, files, split, protocol, candidate, _, reference, _ = prepared()
    targets = tuple(t.model_copy(update={"horizons": (366,)}) for t in protocol.targets)
    protocol = protocol.model_copy(update={"targets": targets})
    protocol = protocol.model_copy(
        update={"content_hash": compute_benchmark_protocol_content_hash(protocol)}
    )
    empty = render_forecast_csv([])
    assert _parse_csv(empty) == []

    def rebuild(item: Any) -> Any:
        item = build_forecast_set(
            forecast_set_id=item.forecast_set_id,
            forecast_set_version="1.0.0",
            protocol=protocol,
            partition="development",
            producer=item.producer,
            csv_bytes=empty,
            row_count=0,
            created_at=NOW,
            metadata={},
        )
        assert item.content_hash == compute_forecast_set_content_hash(item)
        return item

    cells = score_forecast_sets(
        protocol, split, curated, files, rebuild(candidate), empty, rebuild(reference), empty
    )
    assert all(
        cell.evaluable_tasks == 0 and cell.candidate is None and cell.reference is None
        for cell in cells
    )


def test_determinism_and_no_input_mutation() -> None:
    import copy

    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared()
    before = copy.deepcopy((curated, files, split, protocol, candidate, cb, reference, rb))
    first = score_forecast_sets(protocol, split, curated, files, candidate, cb, reference, rb)
    second = score_forecast_sets(protocol, split, curated, files, candidate, cb, reference, rb)
    assert first == second
    assert before == (curated, files, split, protocol, candidate, cb, reference, rb)


def test_holdout_engine_rejections() -> None:
    from kalhas.application.dataset_split_errors import SealedPartitionError

    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared()
    with pytest.raises(SealedPartitionError):
        resolve_target_values(protocol, split, curated, files, "holdout")
    with pytest.raises(SealedPartitionError):
        build_forecast_set(
            forecast_set_id="holdout",
            forecast_set_version="1.0.0",
            protocol=protocol,
            partition="holdout",
            producer=candidate.producer,
            csv_bytes=cb,
            row_count=1,
            created_at=NOW,
            metadata={},
        )
    with pytest.raises(SealedPartitionError):
        score_forecast_sets(
            protocol,
            split,
            curated,
            files,
            candidate.model_copy(update={"partition": "holdout"}),
            cb,
            reference,
            rb,
        )


def test_invalid_observed_value_fails_closed() -> None:
    bad = DAILY.replace(b"2020-01-07,7", b"2020-01-07,1e3")
    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared(
        "validation", daily=bad
    )
    with pytest.raises(BenchmarkError) as exc:
        score_forecast_sets(protocol, split, curated, files, candidate, cb, reference, rb)
    assert exc.value.reason == "invalid_target_value"


def test_artifacts_are_deterministic() -> None:
    from kalhas.application.benchmark_scoring import compute_forecast_set_content_hash

    first = prepared()
    second = prepared()
    assert first[7] == second[7] and first[9] == second[9]
    assert (
        first[6].content_hash
        == second[6].content_hash
        == compute_forecast_set_content_hash(first[6])
    )
    assert (
        first[8].content_hash
        == second[8].content_hash
        == compute_forecast_set_content_hash(first[8])
    )
    score = score_task((Fraction(4),) * 7, Fraction(7))
    assert (
        score.wis,
        quantize_half_even(score.wis),
        score.absolute_error,
        score.in_50,
        score.in_95,
    ) == (Fraction(3), "3.000000", Fraction(3), False, False)


def test_scoring_rejects_invalid_lineage_and_producers() -> None:
    from kalhas.application.benchmark_scoring import compute_forecast_set_content_hash

    _, _, curated, files, split, protocol, candidate, cb, reference, rb = prepared()

    def seal(item: Any) -> Any:
        return item.model_copy(update={"content_hash": compute_forecast_set_content_hash(item)})

    cases = [
        (
            candidate.model_copy(update={"content_hash": "0" * 64}),
            cb,
            reference,
            rb,
            "reference_mismatch",
        ),
        (
            seal(candidate.model_copy(update={"partition": "validation"})),
            cb,
            reference,
            rb,
            "partition_mismatch",
        ),
        (
            candidate,
            cb,
            seal(
                reference.model_copy(
                    update={
                        "producer": reference.producer.model_copy(update={"producer_id": "other"})
                    }
                )
            ),
            rb,
            "reference_producer_mismatch",
        ),
        (
            seal(candidate.model_copy(update={"producer": reference.producer})),
            cb,
            reference,
            rb,
            "candidate_is_reference",
        ),
        (candidate, b"edited", reference, rb, "file_mismatch"),
    ]
    for c, content, r, ref_content, reason in cases:
        with pytest.raises(BenchmarkError) as exc:
            score_forecast_sets(protocol, split, curated, files, c, content, r, ref_content)
        assert exc.value.reason == reason
        assert str(exc.value) == "Benchmark operation failed and was rejected"


def test_decimal_grammar_accepts_long_integer_without_interpreter_digit_limit() -> None:
    text = "1" + "0" * 4300
    assert quantize_half_even(parse_forecast_value(text)) == text + ".000000"
    assert parse_observed_value(text) == parse_forecast_value(text)
