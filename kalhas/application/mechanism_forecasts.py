"""Produce and re-execute deterministic offline mechanism forecasts."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction

from kalhas.application.benchmark_baselines import _LEVELS, type7_quantile
from kalhas.application.benchmark_errors import BenchmarkError
from kalhas.application.benchmark_forecast_verifier import verify_forecast_set
from kalhas.application.benchmark_scoring import (
    ForecastRow,
    build_forecast_set,
    parse_observed_value,
    quantize_half_even,
    render_forecast_csv,
)
from kalhas.application.benchmark_task_engine import (
    BenchmarkInformationSet,
    BenchmarkTask,
    TimeType,
    build_information_set,
    derive_benchmark_tasks,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.mechanism_forecast_errors import (
    MechanismForecastError,
    MechanismForecastVerificationError,
)
from kalhas.application.mechanism_trajectory import run_mechanism_trajectory
from kalhas.application.model_pack_authoring_errors import (
    ModelPackAuthoringVerificationError,
    ObservationOperatorError,
)
from kalhas.application.model_pack_authoring_verifier import verify_model_pack_authoring_binding
from kalhas.application.observation_operators import (
    evaluate_observation_operator,
    target_period_days,
)
from kalhas.contracts.v1.benchmark_forecast import ForecastProducer, ForecastSet
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.domain_mechanism import _is_exact_json_value
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding, _has_float
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs import DomainPack


@dataclass(frozen=True, slots=True)
class MechanismForecastMember:
    member_id: str
    pack: DomainPack
    action: Mapping[str, JsonValue]
    initial_state_parameters: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class InitialStateRule:
    rule_id: str
    rule_version: str
    build: Callable[
        [BenchmarkTask, BenchmarkInformationSet, Mapping[str, JsonValue]], Mapping[str, int] | None
    ]


def mechanism_configuration(
    binding: ModelPackAuthoringBinding,
    members: Sequence[MechanismForecastMember],
    rule: InitialStateRule,
    variants: Mapping[str, str],
) -> dict[str, JsonValue]:
    ids = [member.member_id for member in members]
    if (
        not ids
        or any(
            type(item) is not str or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item) is None
            for item in ids
        )
        or ids != sorted(set(ids))
        or any(
            not _is_exact_json_value(value) or _has_float(value)
            for member in members
            for value in (member.action, member.initial_state_parameters)
        )
    ):
        raise MechanismForecastError("members_invalid")
    if any(member.pack.release_profile.pack_id != binding.pack_id for member in members):
        raise MechanismForecastError("pack_reference_mismatch")
    options = {
        (observation.target_path, observation.variant_id) for observation in binding.observations
    }
    if set(variants) != {path for path, _ in options} or any(
        (path, variant) not in options for path, variant in variants.items()
    ):
        raise MechanismForecastError("variant_selection_invalid")
    records: list[JsonValue] = []
    for member in members:
        profile = member.pack.release_profile
        records.append(
            {
                "member_id": member.member_id,
                "pack_id": profile.pack_id,
                "pack_version": profile.pack_version,
                "release_profile_id": profile.identifier,
                "release_profile_content_hash": profile.content_hash,
                "mechanism_spec_content_hash": profile.mechanism_spec.content_hash,
                "action": dict(member.action),
                "initial_state_parameters": dict(member.initial_state_parameters),
            }
        )
    return {
        "binding_id": binding.binding_id,
        "binding_content_hash": binding.content_hash,
        "protocol_content_hash": binding.protocol_content_hash,
        "initial_state_rule": {"rule_id": rule.rule_id, "rule_version": rule.rule_version},
        "variants": {path: variants[path] for path in sorted(variants)},
        "members": records,
    }


TrajectoryKey = tuple[str, str, date, str]


def render_mechanism_forecasts(
    binding: ModelPackAuthoringBinding,
    members: Sequence[MechanismForecastMember],
    rule: InitialStateRule,
    variants: Mapping[str, str],
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    partition: str,
) -> tuple[bytes, int, dict[str, JsonValue]]:
    if (binding.protocol_manifest_id, binding.protocol_content_hash) != (
        protocol.identifier,
        protocol.content_hash,
    ):
        raise MechanismForecastError("binding_invalid")
    tasks = derive_benchmark_tasks(
        protocol, split_manifest, curated_manifest, curated_files, partition
    )
    view = build_information_set(
        protocol, split_manifest, curated_manifest, curated_files, partition
    )
    configuration = mechanism_configuration(binding, members, rule, variants)
    kinds: dict[str, TimeType] = {}
    for target in protocol.targets:
        column = next(
            column
            for item in curated_manifest.files
            if item.path == target.path
            for column in item.columns
            if column.name == target.time_column
        )
        kinds[target.path] = "date" if column.value_type == "date" else "iso_week"
    selected = {(o.target_path, o.variant_id): o.operator for o in binding.observations}
    planned: dict[TrajectoryKey, tuple[MechanismForecastMember, dict[str, int], int]] = {}
    pending: list[tuple[BenchmarkTask, list[Fraction | TrajectoryKey]]] = []
    fallback_count = 0
    for task in tasks:
        if task.status != "evaluable":
            continue
        kind = kinds[task.path]
        origin = target_period_days(task.origin, kind)[-1]
        target_day = target_period_days(task.target_time, kind)[-1]
        steps = (target_day - origin).days
        values: list[Fraction | TrajectoryKey] = []
        for member in members:
            try:
                state = rule.build(task, view, member.initial_state_parameters)
            except Exception:
                raise MechanismForecastError("initial_state_rule_failed") from None
            if state is None:
                observed = [
                    value
                    for time, value in view.rows(task, task.path, task.series)
                    if time == task.origin
                ]
                if len(observed) != 1:
                    raise BenchmarkError("invalid_input")
                values.append(parse_observed_value(observed[0]))
                fallback_count += 1
                continue
            state_copy = dict(state)
            key = (member.member_id, task.series, origin, canonical_json(state_copy))
            prior = planned.get(key)
            if prior is None or steps > prior[2]:
                planned[key] = (member, state_copy, steps)
            values.append(key)
        pending.append((task, values))
    trajectories = {}
    dispatched = 0
    for key, (member, state, count) in planned.items():
        identity = [key[0], key[1], key[2].isoformat(), key[3]]
        run_id = "mechanism-" + sha256_hex(canonical_json(identity))
        trajectories[key] = run_mechanism_trajectory(
            member.pack,
            binding=binding,
            protocol=protocol,
            run_id=run_id,
            last_observed_day=key[2],
            initial_state=state,
            action=member.action,
            step_count=count,
        )
        dispatched += len(trajectories[key])
    rows: list[ForecastRow] = []
    for task, values in pending:
        outcomes = []
        operator = selected[(task.path, variants[task.path])]
        for value in values:
            if isinstance(value, Fraction):
                outcomes.append(value)
                continue
            try:
                outcomes.append(
                    evaluate_observation_operator(
                        operator,
                        trajectories[value],
                        task.target_time,
                        kinds[task.path],
                        task.series,
                        binding.denominators,
                    )
                )
            except ObservationOperatorError:
                raise MechanismForecastError("observation_failed") from None
        ordered = sorted(outcomes)
        quantiles = tuple(quantize_half_even(type7_quantile(ordered, level)) for level in _LEVELS)
        rows.append(ForecastRow(task.path, task.series, task.origin, task.horizon, quantiles))
    metadata: dict[str, JsonValue] = {
        "configuration": configuration,
        "dispatched_step_count": dispatched,
        "fallback_count": fallback_count,
    }
    return render_forecast_csv(rows), len(rows), metadata


def produce_mechanism_forecasts(
    *,
    forecast_set_id: str,
    forecast_set_version: str,
    binding: ModelPackAuthoringBinding,
    members: Sequence[MechanismForecastMember],
    rule: InitialStateRule,
    variants: Mapping[str, str],
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
    partition: str,
    created_at: datetime,
) -> tuple[ForecastSet, bytes]:
    try:
        verify_model_pack_authoring_binding(
            binding, protocol, split_manifest, curated_manifest, curated_files, raw_bundles
        )
    except ModelPackAuthoringVerificationError:
        raise MechanismForecastError("binding_invalid") from None
    config = mechanism_configuration(binding, members, rule, variants)
    content, count, metadata = render_mechanism_forecasts(
        binding,
        members,
        rule,
        variants,
        protocol,
        split_manifest,
        curated_manifest,
        curated_files,
        partition,
    )
    producer = ForecastProducer(
        kind="model_pack_mechanism",
        producer_id=binding.binding_id,
        producer_version=binding.binding_version,
        configuration_hash=sha256_hex(canonical_json(config)),
    )
    forecast = build_forecast_set(
        forecast_set_id=forecast_set_id,
        forecast_set_version=forecast_set_version,
        protocol=protocol,
        partition=partition,
        producer=producer,
        csv_bytes=content,
        row_count=count,
        created_at=created_at,
        metadata=metadata,
    )
    return forecast, content


def verify_mechanism_forecast_set(
    forecast_set: ForecastSet,
    csv_bytes: bytes,
    binding: ModelPackAuthoringBinding,
    members: Sequence[MechanismForecastMember],
    rule: InitialStateRule,
    variants: Mapping[str, str],
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    verify_forecast_set(
        forecast_set,
        csv_bytes,
        protocol,
        split_manifest,
        curated_manifest,
        curated_files,
        raw_bundles,
    )
    error = MechanismForecastVerificationError
    producer = forecast_set.producer
    if producer.kind != "model_pack_mechanism":
        raise error("not_a_mechanism_forecast")
    try:
        verify_model_pack_authoring_binding(
            binding, protocol, split_manifest, curated_manifest, curated_files, raw_bundles
        )
    except ModelPackAuthoringVerificationError:
        raise error("binding_invalid") from None
    if (producer.producer_id, producer.producer_version) != (
        binding.binding_id,
        binding.binding_version,
    ):
        raise error("producer_mismatch")
    try:
        configuration = mechanism_configuration(binding, members, rule, variants)
        if producer.configuration_hash != sha256_hex(canonical_json(configuration)):
            raise error("configuration_mismatch")
    except error:
        raise
    except Exception:
        raise error("configuration_mismatch") from None
    try:
        rendered, _, metadata = render_mechanism_forecasts(
            binding,
            members,
            rule,
            variants,
            protocol,
            split_manifest,
            curated_manifest,
            curated_files,
            forecast_set.partition,
        )
    except Exception:
        raise error("reexecution_mismatch") from None
    if rendered != csv_bytes:
        raise error("reexecution_mismatch")
    if canonical_json(metadata) != canonical_json(forecast_set.metadata):
        raise error("metadata_mismatch")
