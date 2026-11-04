"""Synthetic reference baseline and re-execution tests."""

from __future__ import annotations

import copy
import hashlib
from fractions import Fraction
from typing import Any

import pytest
from kalhas.application.benchmark_baselines import (
    BASELINE_CONFIGURATION_HASH,
    POINT_BASELINE_ID,
    QUANTILE_BASELINE_ID,
    _task_values,
    produce_persistence_point_forecasts,
    produce_persistence_quantile_forecasts,
    render_baseline_forecasts,
    symmetric_difference_offsets,
    type7_quantile,
    verify_baseline_forecast_set,
)
from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_forecast_errors import (
    BenchmarkBaselineVerificationError,
    BenchmarkForecastVerificationError,
)
from kalhas.application.benchmark_forecast_verifier import (
    verify_benchmark_score_report,
    verify_forecast_set,
)
from kalhas.application.benchmark_protocol_verifier import compute_benchmark_protocol_content_hash
from kalhas.application.benchmark_scoring import (
    build_benchmark_score_report,
    compute_forecast_set_content_hash,
)
from kalhas.application.benchmark_task_engine import (
    BenchmarkInformationSet,
    BenchmarkTask,
    _parse,
    build_information_set,
    derive_benchmark_tasks,
)
from kalhas.application.dataset_split_errors import SealedPartitionError

from tests.test_benchmark_scoring import NOW
from tests.test_benchmark_task_engine import DAILY, chain


def _inputs(daily: bytes = DAILY) -> tuple[Any, ...]:
    raw, raw_files, curated, files, split, protocol = chain(daily)
    return protocol, split, curated, files, {raw.identifier: (raw, raw_files)}


def _produce(
    kind: str, inputs: tuple[Any, ...], partition: str = "development"
) -> tuple[Any, bytes]:
    protocol, split, curated, files, _ = inputs
    function = (
        produce_persistence_point_forecasts
        if kind == POINT_BASELINE_ID
        else produce_persistence_quantile_forecasts
    )
    return function(
        forecast_set_id="baseline",
        forecast_set_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        partition=partition,
        created_at=NOW,
    )


@pytest.mark.parametrize(
    "differences,expected",
    [
        ([2, -1, 4], ("-15/4", "-3", "-7/4", "0", "7/4", "3", "15/4")),
        ([1], ("-19/20", "-4/5", "-1/2", "0", "1/2", "4/5", "19/20")),
        ([0, 3], ("-111/40", "-21/10", "-3/4", "0", "3/4", "21/10", "111/40")),
    ],
)
def test_exact_offsets(differences: list[int], expected: tuple[str, ...]) -> None:
    offsets = symmetric_difference_offsets([Fraction(value) for value in differences])
    assert offsets == tuple(Fraction(value) for value in expected)
    assert all(type(value) is Fraction for value in offsets)


def test_type7_and_empty() -> None:
    assert type7_quantile([Fraction(1), Fraction(3), Fraction(5)], Fraction(1, 2)) == Fraction(3)
    assert type7_quantile([Fraction(1), Fraction(3)], Fraction(1)) == Fraction(3)
    with pytest.raises(BenchmarkError, match="Benchmark operation failed") as exc:
        type7_quantile([], Fraction(1, 2))
    assert exc.value.reason == "invalid_input"
    with pytest.raises(BenchmarkError) as exc:
        symmetric_difference_offsets([])
    assert exc.value.reason == "invalid_input"
    assert BASELINE_CONFIGURATION_HASH == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )


def test_exact_fixture_csv_and_metadata() -> None:
    inputs = _inputs()
    point, point_csv = _produce(POINT_BASELINE_ID, inputs)
    point_validation, point_validation_csv = _produce(POINT_BASELINE_ID, inputs, "validation")
    quantile, development = _produce(QUANTILE_BASELINE_ID, inputs)
    validation_set, validation = _produce(QUANTILE_BASELINE_ID, inputs, "validation")
    assert point.metadata == {}
    assert quantile.metadata == {"fallback_count": 0}
    assert validation_set.metadata == {"fallback_count": 1}
    assert point_csv.decode().splitlines()[1:] == [
        "weekly.csv,alpha,2020-W01,1,11.000000,11.000000,11.000000,11.000000,"
        "11.000000,11.000000,11.000000"
    ]
    assert development.decode().splitlines()[1:] == [
        "weekly.csv,alpha,2020-W01,1,10.050000,10.200000,10.500000,11.000000,"
        "11.500000,11.800000,11.950000"
    ]
    assert validation.decode().splitlines()[1:] == [
        "daily.csv,alpha,2020-01-06,1,5.050000,5.200000,5.500000,6.000000,"
        "6.500000,6.800000,6.950000",
        "daily.csv,alpha,2020-01-06,2,6.000000,6.000000,6.000000,6.000000,"
        "6.000000,6.000000,6.000000",
        "daily.csv,alpha,2020-01-07,1,6.050000,6.200000,6.500000,7.000000,"
        "7.500000,7.800000,7.950000",
    ]
    for item, content in (
        (point, point_csv),
        (point_validation, point_validation_csv),
        (quantile, development),
        (validation_set, validation),
    ):
        verify_forecast_set(item, content, *inputs)
        verify_baseline_forecast_set(item, content, *inputs)
        for row in content.decode().splitlines()[1:]:
            quantiles = tuple(Fraction(value) for value in row.split(",")[4:])
            assert list(quantiles) == sorted(quantiles)


def test_golden_score() -> None:
    protocol, split, curated, files, raw = _inputs()
    comparison = protocol.comparison.model_copy(
        update={"reference_baseline_id": QUANTILE_BASELINE_ID}
    )
    protocol = protocol.model_copy(update={"comparison": comparison})
    protocol = protocol.model_copy(
        update={"content_hash": compute_benchmark_protocol_content_hash(protocol)}
    )
    inputs = (protocol, split, curated, files, raw)
    candidate, candidate_csv = _produce(POINT_BASELINE_ID, inputs)
    reference, reference_csv = _produce(QUANTILE_BASELINE_ID, inputs)
    # The two artifacts need distinct identities even though their producers already differ.
    reference = reference.model_copy(
        update={"identifier": "forecast-set-reference-1.0.0", "forecast_set_id": "reference"}
    )
    reference = reference.model_copy(
        update={"content_hash": compute_forecast_set_content_hash(reference)}
    )
    report = build_benchmark_score_report(
        report_id="report",
        report_version="1.0.0",
        protocol=protocol,
        split_manifest=split,
        curated_manifest=curated,
        curated_files=files,
        candidate=candidate,
        candidate_csv=candidate_csv,
        reference=reference,
        reference_csv=reference_csv,
        limitations=("Synthetic only",),
        scored_at=NOW,
        metadata={},
    )
    cell = next(cell for cell in report.cells if (cell.path, cell.horizon) == ("weekly.csv", 1))
    assert cell.candidate is not None and cell.reference is not None
    assert (
        cell.candidate.mean_wis,
        cell.reference.mean_wis,
        cell.relative_wis,
        cell.verdict,
        cell.verdict_reason,
    ) == ("1.000000", "0.487857", "2.049780", "fail", "not_below_threshold")
    verify_benchmark_score_report(
        report, candidate, candidate_csv, reference, reference_csv, *inputs
    )


@pytest.mark.parametrize("baseline", [POINT_BASELINE_ID, QUANTILE_BASELINE_ID])
def test_information_leakage(baseline: str) -> None:
    for old, new, partitions in (
        (b"alpha,n,2020-01-08,8", b"alpha,n,2020-01-08,800", ("validation",)),
        (b"alpha,h,2020-01-04,4", b"alpha,h,2020-01-04,400", ("development", "validation")),
        (b"alpha,n,2020-01-06,6", b"alpha,n,2020-01-06,600", ("development",)),
    ):
        for partition in partitions:
            assert (
                _produce(baseline, _inputs(), partition)[1]
                == _produce(baseline, _inputs(DAILY.replace(old, new)), partition)[1]
            )


def test_view_spy_and_index(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol, split, curated, files, _ = _inputs()
    original = BenchmarkInformationSet.rows
    calls: list[tuple[BenchmarkTask, str, str]] = []

    def spy(
        view: BenchmarkInformationSet, task: BenchmarkTask, path: str, series: str
    ) -> tuple[tuple[str, str], ...]:
        result = original(view, task, path, series)
        assert (path, series) == (task.path, task.series)
        kind = dict(view._types)[path]
        assert all(_parse(time, kind) <= _parse(task.origin, kind) for time, _ in result)
        calls.append((task, path, series))
        return result

    monkeypatch.setattr(BenchmarkInformationSet, "rows", spy)
    for baseline in (POINT_BASELINE_ID, QUANTILE_BASELINE_ID):
        for partition in ("development", "validation"):
            _produce(baseline, (protocol, split, curated, files, {}), partition)
    assert len(calls) == 8
    monkeypatch.setattr(BenchmarkInformationSet, "rows", original)
    for partition in ("development", "validation"):
        view = build_information_set(protocol, split, curated, files, partition)
        for task in derive_benchmark_tasks(protocol, split, curated, files, partition):
            kinds = dict(view._types)
            origin = _parse(task.origin, kinds[task.path]).toordinal()
            for path in kinds:
                for series in ("alpha", "beta", "gamma", "unknown"):
                    expected = []
                    for row in view._rows:
                        if (row.path, row.series) != (path, series):
                            continue
                        row_time, task_time = row.time.toordinal(), origin
                        if row.kind != kinds[task.path]:
                            row_time += 6 if row.kind == "iso_week" else 0
                            task_time += 6 if kinds[task.path] == "iso_week" else 0
                        if row_time <= task_time:
                            expected.append((row.text, row.value))
                    assert view.rows(task, path, series) == tuple(expected)


def test_quantile_math_window_gaps_and_rounding(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol, split, curated, files, _ = _inputs()
    view = build_information_set(protocol, split, curated, files, "validation")
    target = next(target for target in protocol.targets if target.path == "daily.csv")
    target = target.model_copy(update={"history_window": 10})
    task = BenchmarkTask(
        "daily.csv", "alpha", "2020-01-06", 1, "2020-01-07", "validation", "evaluable"
    )
    rows: tuple[tuple[str, str], ...] = (
        ("2020-01-03", "10"),
        ("2020-01-04", "12"),
        ("2020-01-05", "11"),
        ("2020-01-06", "15"),
    )
    monkeypatch.setattr(BenchmarkInformationSet, "rows", lambda *args: rows)
    assert _task_values(QUANTILE_BASELINE_ID, task, target, "date", view) == (
        ("11.250000", "12.000000", "13.250000", "15.000000", "16.750000", "18.000000", "18.750000"),
        False,
    )
    rows = (("2020-01-03", "-4"), ("2020-01-04", "-2"), ("2020-01-05", "-3"), ("2020-01-06", "1"))
    assert _task_values(QUANTILE_BASELINE_ID, task, target, "date", view) == (
        ("0.000000", "0.000000", "0.000000", "1.000000", "2.750000", "4.000000", "4.750000"),
        False,
    )
    rows = (("2020-01-04", "8"), ("2020-01-06", "-0.0000005"))
    assert _task_values(QUANTILE_BASELINE_ID, task, target, "date", view) == (
        ("0.000000",) * 7,
        True,
    )
    assert _task_values(POINT_BASELINE_ID, task, target, "date", view) == (("0.000000",) * 7, False)
    rows = (("2020-01-04", "-5"), ("2020-01-05", "-2"), ("2020-01-06", "-1"))
    target = target.model_copy(update={"history_window": 1})
    assert _task_values(QUANTILE_BASELINE_ID, task, target, "date", view) == (
        ("0.000000",) * 7,
        True,
    )
    assert _task_values(POINT_BASELINE_ID, task, target, "date", view) == (
        ("-1.000000",) * 7,
        False,
    )
    rows = (("2020-01-06", "2.5000005"),)
    assert _task_values(POINT_BASELINE_ID, task, target, "date", view) == (("2.500000",) * 7, False)
    rows = ()
    with pytest.raises(BenchmarkError) as exc:
        _task_values(POINT_BASELINE_ID, task, target, "date", view)
    assert exc.value.reason == "invalid_input"


def test_declared_missing_and_curated_precision() -> None:
    protocol, split, curated, files, _ = _inputs()
    view = build_information_set(protocol, split, curated, files, "validation")
    task = next(
        task
        for task in derive_benchmark_tasks(protocol, split, curated, files, "validation")
        if (task.path, task.origin, task.horizon) == ("daily.csv", "2020-01-06", 2)
    )
    assert view.rows(task, task.path, task.series) == (
        ("2020-01-01", "1"),
        ("2020-01-03", "3"),
        ("2020-01-05", "5"),
        ("2020-01-06", "6"),
    )
    data, _, metadata = render_baseline_forecasts(
        QUANTILE_BASELINE_ID, protocol, split, curated, files, "validation"
    )
    assert metadata == {"fallback_count": 1}
    assert (
        b"daily.csv,alpha,2020-01-06,2,6.000000,6.000000,6.000000,6.000000,6.000000,6.000000,6.000000\n"
        in data
    )
    precise = _inputs(DAILY.replace(b"2020-01-06,6", b"2020-01-06,2.5000005"))
    _, point = _produce(POINT_BASELINE_ID, precise, "validation")
    assert point.decode().splitlines()[1] == (
        "daily.csv,alpha,2020-01-06,1,2.500000,2.500000,2.500000,2.500000,"
        "2.500000,2.500000,2.500000"
    )


def test_determinism_and_sealed() -> None:
    inputs = _inputs()
    before = copy.deepcopy(inputs)
    for baseline in (POINT_BASELINE_ID, QUANTILE_BASELINE_ID):
        first = _produce(baseline, inputs)
        second = _produce(baseline, inputs)
        assert first == second
        assert first[0].content_hash == second[0].content_hash
        with pytest.raises(SealedPartitionError):
            _produce(baseline, inputs, "holdout")
        with pytest.raises(SealedPartitionError):
            render_baseline_forecasts(
                baseline, inputs[0], inputs[1], inputs[2], inputs[3], "holdout"
            )
        with pytest.raises(SealedPartitionError):
            verify_baseline_forecast_set(
                first[0].model_copy(update={"partition": "holdout"}), first[1], *inputs
            )
    assert inputs == before
    with pytest.raises(BenchmarkError) as exc:
        render_baseline_forecasts(
            "synthetic", inputs[0], inputs[1], inputs[2], inputs[3], "development"
        )
    assert exc.value.reason == "unknown_baseline"


def test_verifier_reasons_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _inputs()
    item, content = _produce(QUANTILE_BASELINE_ID, inputs)

    def seal(value: Any) -> Any:
        return value.model_copy(update={"content_hash": compute_forecast_set_content_hash(value)})

    def producer(**updates: str) -> Any:
        return seal(item.model_copy(update={"producer": item.producer.model_copy(update=updates)}))

    edited = content.replace(b"10.050000", b"10.060000")
    file = item.forecasts_file.model_copy(
        update={"sha256": hashlib.sha256(edited).hexdigest(), "byte_size": len(edited)}
    )
    forged = seal(item.model_copy(update={"forecasts_file": file}))
    verify_forecast_set(forged, edited, *inputs)
    cases = (
        (producer(kind="model_pack_mechanism"), content, "not_a_baseline"),
        (producer(producer_id="synthetic"), content, "unknown_baseline"),
        (producer(configuration_hash="0" * 64), content, "configuration_mismatch"),
        (forged, edited, "reexecution_mismatch"),
        (
            seal(item.model_copy(update={"metadata": {"fallback_count": 1}})),
            content,
            "metadata_mismatch",
        ),
    )
    for artifact, data, reason in cases:
        with pytest.raises(BenchmarkBaselineVerificationError) as exc:
            verify_baseline_forecast_set(artifact, data, *inputs)
        assert exc.value.reason == reason
        assert str(exc.value) == "Benchmark baseline verification failed and was rejected"
    with pytest.raises(BenchmarkForecastVerificationError) as forecast_exc:
        verify_baseline_forecast_set(producer(kind="model_pack_mechanism"), b"bad", *inputs)
    assert forecast_exc.value.reason == "file_mismatch"
    import kalhas.application.benchmark_baselines as baselines

    def crash(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("private")

    monkeypatch.setattr(baselines, "render_baseline_forecasts", crash)
    with pytest.raises(BenchmarkBaselineVerificationError) as exc:
        verify_baseline_forecast_set(item, content, *inputs)
    assert exc.value.reason == "reexecution_mismatch"
    assert "private" not in str(exc.value)
