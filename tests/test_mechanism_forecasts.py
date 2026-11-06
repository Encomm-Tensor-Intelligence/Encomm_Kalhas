"""Synthetic forecast, trajectory-sharing and re-execution tests."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any, cast

import pytest
from kalhas.application.benchmark_baselines import _LEVELS
from kalhas.application.benchmark_forecast_errors import BenchmarkForecastVerificationError
from kalhas.application.benchmark_forecast_verifier import (
    verify_benchmark_score_report,
    verify_forecast_set,
)
from kalhas.application.benchmark_scoring import (
    build_benchmark_score_report,
    build_forecast_set,
    quantize_half_even,
)
from kalhas.application.dataset_split_errors import SealedPartitionError
from kalhas.application.mechanism_forecast_errors import (
    MechanismForecastError,
    MechanismForecastVerificationError,
)
from kalhas.application.mechanism_forecasts import (
    InitialStateRule,
    MechanismForecastMember,
    mechanism_configuration,
    produce_mechanism_forecasts,
    render_mechanism_forecasts,
    verify_mechanism_forecast_set,
)
from kalhas.application.observation_operators import target_period_days
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs.pan import PanV01DomainPack
from kalhas.domain_packs.pan.mechanism import compute_transition, validate_configuration_payload

from tests.test_benchmark_scoring import prepared as scoring_prepared
from tests.test_benchmark_task_engine import chain
from tests.test_mechanism_trajectory import ACTION, STATE
from tests.test_model_pack_authoring_contracts import binding_payload
from tests.test_model_pack_authoring_verifier import seal

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
VARIANTS = {"daily.csv": "default", "weekly.csv": "default"}


def build_state(*args: Any) -> dict[str, int]:
    return dict(STATE)


@pytest.fixture
def prepared() -> dict[str, Any]:
    raw, source, curated, files, split, protocol = chain()
    data = binding_payload()
    data.update(
        pack_id="kalhas-pan",
        pack_version="0.1.0",
        protocol_manifest_id=protocol.identifier,
        protocol_content_hash=protocol.content_hash,
    )
    data["observations"][0]["operator"] = {"op": "stock_sum", "stocks": ["hospitalized"]}
    data["observations"][1]["operator"] = {
        "op": "per_100k",
        "inner": {"op": "flow_sum", "flow": "hospital_admissions"},
    }
    data["denominators"][0]["value"] = 1000
    binding = seal(data)
    member = MechanismForecastMember("one", PanV01DomainPack(), ACTION, {})
    rule = InitialStateRule("fixture", "1.0.0", build_state)
    return {
        "binding": binding,
        "members": (member,),
        "rule": rule,
        "variants": VARIANTS,
        "protocol": protocol,
        "split_manifest": split,
        "curated_manifest": curated,
        "curated_files": files,
        "raw_bundles": {raw.identifier: (raw, source)},
    }


def produce(prepared: dict[str, Any], partition: str = "development") -> tuple[Any, bytes]:
    return produce_mechanism_forecasts(
        forecast_set_id="candidate",
        forecast_set_version="1.0.0",
        partition=partition,
        created_at=NOW,
        **prepared,
    )


def verify(artifact: Any, content: bytes, prepared: dict[str, Any]) -> None:
    verify_mechanism_forecast_set(artifact, content, **prepared)


def replace_artifact(artifact: Any, content: bytes, **updates: Any) -> Any:
    return build_forecast_set(
        forecast_set_id=artifact.forecast_set_id,
        forecast_set_version=artifact.forecast_set_version,
        protocol=updates["protocol"],
        partition=artifact.partition,
        producer=updates.get("producer", artifact.producer),
        csv_bytes=content,
        row_count=artifact.forecasts_file.row_count,
        created_at=artifact.created_at,
        metadata=updates.get("metadata", artifact.metadata),
    )


def test_golden_forecast_and_scoring(prepared: dict[str, Any]) -> None:
    artifact, content = produce(prepared)
    rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))
    assert rows[1] == ["weekly.csv", "alpha", "2020-W01", "1", *(["4400.000000"] * 7)]
    assert len(rows) == 2
    assert artifact.metadata["dispatched_step_count"] == 7
    assert artifact.metadata["fallback_count"] == 0
    verify(artifact, content, prepared)
    verify_forecast_set(
        artifact,
        content,
        prepared["protocol"],
        prepared["split_manifest"],
        prepared["curated_manifest"],
        prepared["curated_files"],
        prepared["raw_bundles"],
    )
    *_, reference, reference_csv = scoring_prepared()
    report = build_benchmark_score_report(
        report_id="score",
        report_version="1.0.0",
        protocol=prepared["protocol"],
        split_manifest=prepared["split_manifest"],
        curated_manifest=prepared["curated_manifest"],
        curated_files=prepared["curated_files"],
        candidate=artifact,
        candidate_csv=content,
        reference=reference,
        reference_csv=reference_csv,
        limitations=("Synthetic only.",),
        scored_at=NOW,
        metadata={},
    )
    verify_benchmark_score_report(
        report,
        artifact,
        content,
        reference,
        reference_csv,
        prepared["protocol"],
        prepared["split_manifest"],
        prepared["curated_manifest"],
        prepared["curated_files"],
        prepared["raw_bundles"],
    )
    assert produce(prepared) == (artifact, content)


def test_validation_shares_trajectories(prepared: dict[str, Any]) -> None:
    artifact, content = produce(prepared, "validation")
    assert artifact.forecasts_file.row_count == 3
    assert artifact.metadata["dispatched_step_count"] == 3
    assert artifact.metadata["fallback_count"] == 0
    verify(artifact, content, prepared)


def test_ensemble_quantiles_from_independent_transitions(prepared: dict[str, Any]) -> None:
    pack = PanV01DomainPack()
    prepared["members"] = tuple(
        MechanismForecastMember(key, pack, {"intervention_intensity_bps": intensity}, {})
        for key, intensity in (("a", 0), ("b", 2500), ("c", 5000))
    )
    artifact, content = produce(prepared)
    assert artifact.metadata["dispatched_step_count"] == 21
    config = validate_configuration_payload(
        pack.mechanism_spec.configuration, pack.mechanism_spec.configuration
    )
    outcomes = []
    for intensity in (0, 2500, 5000):
        state = dict(STATE)
        total = 0
        for _ in range(7):
            transition = compute_transition(state, intensity, config)
            total += transition.counts[2]
            state = transition.next_state
        outcomes.append(Fraction(total * 100))
    ordered = sorted(outcomes)
    expected = []
    for level in _LEVELS:
        position = 2 * level
        index = position.numerator // position.denominator
        value = (
            ordered[index]
            if index == 2
            else ordered[index] + (position - index) * (ordered[index + 1] - ordered[index])
        )
        expected.append(quantize_half_even(value))
    assert list(csv.reader(io.StringIO(content.decode("utf-8"))))[1][4:] == expected


def test_fallback_uses_origin_without_dispatch(prepared: dict[str, Any]) -> None:
    prepared["rule"] = InitialStateRule("fallback", "1.0.0", lambda *_: None)
    artifact, content = produce(prepared)
    assert artifact.metadata["fallback_count"] == 1
    assert artifact.metadata["dispatched_step_count"] == 0
    assert list(csv.reader(io.StringIO(content.decode("utf-8"))))[1][4:] == ["11.000000"] * 7
    verify(artifact, content, prepared)


def test_rule_view_has_no_lookahead(prepared: dict[str, Any]) -> None:
    def rule(task: Any, view: Any, params: Any) -> dict[str, int]:
        kinds = dict(view._types)
        origin = target_period_days(task.origin, kinds[task.path])[-1]
        for path in kinds:
            for when, _ in view.rows(task, path, task.series):
                assert target_period_days(when, kinds[path])[-1] <= origin
        return dict(STATE)

    prepared["rule"] = InitialStateRule("view", "1.0.0", rule)
    produce(prepared)
    produce(prepared, "validation")


def test_sealed_partition(prepared: dict[str, Any]) -> None:
    with pytest.raises(SealedPartitionError):
        produce(prepared, "holdout")


@pytest.mark.parametrize(
    "case,reason",
    [
        ("empty", "members_invalid"),
        ("slug", "members_invalid"),
        ("duplicate", "members_invalid"),
        ("order", "members_invalid"),
        ("action_float", "members_invalid"),
        ("params_float", "members_invalid"),
        ("params_tuple", "members_invalid"),
        ("pack", "pack_reference_mismatch"),
        ("variant_missing", "variant_selection_invalid"),
        ("variant_unknown", "variant_selection_invalid"),
    ],
)
def test_configuration_errors(prepared: dict[str, Any], case: str, reason: str) -> None:
    member = prepared["members"][0]
    if case == "empty":
        prepared["members"] = ()
    elif case == "slug":
        prepared["members"] = (MechanismForecastMember("Bad", member.pack, ACTION, {}),)
    elif case == "duplicate":
        prepared["members"] = (member, member)
    elif case == "order":
        prepared["members"] = (
            MechanismForecastMember("z", member.pack, ACTION, {}),
            MechanismForecastMember("a", member.pack, ACTION, {}),
        )
    elif case == "action_float":
        prepared["members"] = (MechanismForecastMember("one", member.pack, {"x": [1.0]}, {}),)
    elif case == "params_float":
        prepared["members"] = (
            MechanismForecastMember("one", member.pack, ACTION, {"nested": {"x": 1.0}}),
        )
    elif case == "params_tuple":
        prepared["members"] = (
            MechanismForecastMember("one", member.pack, ACTION, {"x": cast(JsonValue, (1,))}),
        )
    elif case == "pack":
        prepared["binding"] = prepared["binding"].model_copy(update={"pack_id": "other"})
    elif case == "variant_missing":
        prepared["variants"] = {"daily.csv": "default"}
    else:
        prepared["variants"] = {"daily.csv": "default", "weekly.csv": "other"}
    with pytest.raises(MechanismForecastError) as caught:
        mechanism_configuration(
            prepared["binding"], prepared["members"], prepared["rule"], prepared["variants"]
        )
    assert caught.value.reason == reason


def test_binding_reference_and_rule_failure(prepared: dict[str, Any]) -> None:
    broken = dict(prepared)
    broken["binding"] = prepared["binding"].model_copy(update={"protocol_content_hash": "0" * 64})
    render_args = {key: value for key, value in broken.items() if key != "raw_bundles"}
    with pytest.raises(MechanismForecastError) as caught:
        render_mechanism_forecasts(partition="development", **render_args)
    assert caught.value.reason == "binding_invalid"
    with pytest.raises(MechanismForecastError) as caught:
        produce(broken)
    assert caught.value.reason == "binding_invalid"

    def fail(*args: Any) -> Any:
        raise ValueError("test")

    prepared["rule"] = InitialStateRule("fail", "1.0.0", fail)
    with pytest.raises(MechanismForecastError) as caught:
        produce(prepared)
    assert caught.value.reason == "initial_state_rule_failed"


def test_observation_failure(prepared: dict[str, Any]) -> None:
    data = prepared["binding"].model_dump(mode="json")
    data["observations"][1]["operator"]["inner"]["flow"] = "missing"
    prepared["binding"] = seal(data)
    with pytest.raises(MechanismForecastError) as caught:
        produce(prepared)
    assert caught.value.reason == "observation_failed"


@pytest.mark.parametrize(
    "case,reason",
    [
        ("kind", "not_a_mechanism_forecast"),
        ("binding", "binding_invalid"),
        ("producer", "producer_mismatch"),
        ("version", "configuration_mismatch"),
        ("action", "configuration_mismatch"),
        ("variants", "configuration_mismatch"),
        ("binding_content", "configuration_mismatch"),
        ("members", "configuration_mismatch"),
        ("csv", "reexecution_mismatch"),
        ("rule", "reexecution_mismatch"),
        ("metadata", "metadata_mismatch"),
    ],
)
def test_verifier_failures(prepared: dict[str, Any], case: str, reason: str) -> None:
    artifact, content = produce(prepared)
    args = dict(prepared)
    if case == "kind":
        artifact = replace_artifact(
            artifact,
            content,
            protocol=args["protocol"],
            producer=artifact.producer.model_copy(update={"kind": "baseline"}),
        )
    elif case == "binding":
        args["binding"] = args["binding"].model_copy(update={"content_hash": "0" * 64})
    elif case == "producer":
        artifact = replace_artifact(
            artifact,
            content,
            protocol=args["protocol"],
            producer=artifact.producer.model_copy(update={"producer_id": "other"}),
        )
    elif case == "version":
        args["rule"] = InitialStateRule("fixture", "2.0.0", build_state)
    elif case == "action":
        args["members"] = (
            MechanismForecastMember(
                "one", args["members"][0].pack, {"intervention_intensity_bps": 0}, {}
            ),
        )
    elif case == "variants":
        args["variants"] = {"daily.csv": "default", "weekly.csv": "unknown"}
    elif case == "binding_content":
        data = args["binding"].model_dump(mode="json")
        data["payload"]["candidate_grid"]["x"] = 1
        args["binding"] = seal(data)
    elif case == "members":
        args["members"] = ()
    elif case == "csv":
        content = content.replace(b"4400.000000", b"4401.000000")
        artifact = replace_artifact(artifact, content, protocol=args["protocol"])
    elif case == "rule":
        args["rule"] = InitialStateRule("fixture", "1.0.0", lambda *_: None)
    else:
        metadata = {**artifact.metadata, "fallback_count": 99}
        artifact = replace_artifact(artifact, content, protocol=args["protocol"], metadata=metadata)
    with pytest.raises(MechanismForecastVerificationError) as caught:
        verify(artifact, content, args)
    assert caught.value.reason == reason


def test_structural_error_passes_through(prepared: dict[str, Any]) -> None:
    artifact, content = produce(prepared)
    with pytest.raises(BenchmarkForecastVerificationError) as caught:
        verify(artifact, content + b"x", prepared)
    assert caught.value.reason == "file_mismatch"
