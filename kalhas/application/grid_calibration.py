"""Exact grid evaluation, deterministic retention, and re-execution."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Final, Literal

from kalhas.application.benchmark_scoring import (
    _checked_values,
    _parse_csv,
    parse_observed_value,
    quantize_half_even,
    resolve_target_values,
    score_forecast_sets,
    score_task,
)
from kalhas.application.grid_calibration_errors import (
    CalibrationError,
    CalibrationVerificationError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.mechanism_forecasts import (
    InitialStateRule,
    MechanismForecastMember,
    produce_mechanism_forecasts,
)
from kalhas.application.model_pack_authoring_verifier import verify_model_pack_authoring_binding
from kalhas.contracts.v1.benchmark_forecast import ForecastSet
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.contracts.v1.model_pack_calibration import (
    CalibrationCandidate,
    CalibrationCell,
    CalibrationTargetVariant,
    ModelPackCalibrationRecord,
)
from kalhas.contracts.v1.shared import JsonValue

GRID_FITTER_ID: Final = "kalhas-grid-fitter-v1"
GRID_FITTER_VERSION: Final = "1.0.0"
RETENTION_TOLERANCE = Fraction(21, 20)


@dataclass(frozen=True, slots=True)
class CalibrationCandidateResult:
    candidate_index: int
    member_id: str
    configuration_hash: str
    forecasts_sha256: str
    objective_exact: Fraction | None
    cells: tuple[CalibrationCell, ...]
    fallback_count: int
    dispatched_step_count: int


def evaluate_calibration_candidate(
    *,
    candidate_index: int,
    member: MechanismForecastMember,
    binding: ModelPackAuthoringBinding,
    rule: InitialStateRule,
    variants: Mapping[str, str],
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
    reference: ForecastSet,
    reference_csv: bytes,
) -> CalibrationCandidateResult:
    """Evaluate one member using exact task-level scores."""
    try:
        artifact, content = produce_mechanism_forecasts(
            forecast_set_id=f"calibration-candidate-{candidate_index}",
            forecast_set_version="1.0.0",
            binding=binding,
            members=(member,),
            rule=rule,
            variants=variants,
            protocol=protocol,
            split_manifest=split_manifest,
            curated_manifest=curated_manifest,
            curated_files=curated_files,
            raw_bundles=raw_bundles,
            partition="development",
            created_at=binding.declared_at,
        )
        score_cells = score_forecast_sets(
            protocol,
            split_manifest,
            curated_manifest,
            curated_files,
            artifact,
            content,
            reference,
            reference_csv,
        )
        targets = resolve_target_values(
            protocol, split_manifest, curated_manifest, curated_files, "development"
        )
        rows = _parse_csv(content)
        reference_rows = _parse_csv(reference_csv)
        candidate_quantiles = _checked_values(rows)
        reference_quantiles = _checked_values(reference_rows)
        sums: dict[tuple[str, int], tuple[Fraction, Fraction]] = {}
        for row, cq, rq in zip(rows, candidate_quantiles, reference_quantiles, strict=True):
            path, series, origin, horizon_text = row[:4]
            horizon = int(horizon_text)
            observed = parse_observed_value(targets[(path, series, origin, horizon)])
            key = (path, horizon)
            a, b = sums.get(key, (Fraction(), Fraction()))
            sums[key] = (a + score_task(cq, observed).wis, b + score_task(rq, observed).wis)
        cells = []
        exact_values = []
        for cell in score_cells:
            included = cell.verdict in ("pass", "fail")
            if included:
                a, b = sums[(cell.path, cell.horizon)]
                relative = a / b
                if quantize_half_even(relative) != cell.relative_wis:
                    raise CalibrationError("score_mismatch")
                exact_values.append(relative)
            cells.append(
                CalibrationCell(
                    path=cell.path,
                    horizon=cell.horizon,
                    relative_wis=cell.relative_wis,
                    included=included,
                )
            )
        objective = sum(exact_values, Fraction()) / len(exact_values) if exact_values else None
        fallback = artifact.metadata["fallback_count"]
        dispatched = artifact.metadata["dispatched_step_count"]
        if type(fallback) is not int or type(dispatched) is not int:
            raise ValueError("invalid counts")
        return CalibrationCandidateResult(
            candidate_index,
            member.member_id,
            artifact.producer.configuration_hash,
            hashlib.sha256(content).hexdigest(),
            objective,
            tuple(cells),
            fallback,
            dispatched,
        )
    except CalibrationError as exc:
        if exc.reason == "score_mismatch":
            raise
        raise CalibrationError("candidate_evaluation_failed") from exc
    except Exception as exc:
        raise CalibrationError("candidate_evaluation_failed") from exc


def compute_model_pack_calibration_record_content_hash(record: ModelPackCalibrationRecord) -> str:
    payload = record.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def build_model_pack_calibration_record(
    *,
    record_id: str,
    record_version: str,
    binding: ModelPackAuthoringBinding,
    protocol: BenchmarkProtocol,
    variants: Mapping[str, str],
    reference: ForecastSet,
    results: Sequence[CalibrationCandidateResult],
    max_ensemble_members: int,
    limitations: Sequence[str],
    calibrated_at: datetime,
    metadata: dict[str, JsonValue],
) -> ModelPackCalibrationRecord:
    if any(type(item.candidate_index) is not int for item in results):
        raise CalibrationError("candidate_set_invalid")
    ordered = sorted(results, key=lambda result: result.candidate_index)
    if not ordered or [item.candidate_index for item in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        raise CalibrationError("candidate_set_invalid")
    ranked = sorted(
        (item for item in ordered if item.objective_exact is not None),
        key=lambda item: (item.objective_exact, item.candidate_index),
    )
    ranks = {item.candidate_index: rank for rank, item in enumerate(ranked, 1)}
    qualifying = [
        item.candidate_index
        for item in ranked
        if item.objective_exact is not None
        and ranked[0].objective_exact is not None
        and item.objective_exact <= ranked[0].objective_exact * RETENTION_TOLERANCE
    ]
    retained = set(qualifying[:max_ensemble_members])
    left_out = set(qualifying[max_ensemble_members:])
    candidates = []
    for item in ordered:
        value = item.objective_exact
        status: Literal["no_objective", "retained", "qualifying_left_out", "not_retained"] = (
            "no_objective"
            if value is None
            else "retained"
            if item.candidate_index in retained
            else "qualifying_left_out"
            if item.candidate_index in left_out
            else "not_retained"
        )
        candidates.append(
            CalibrationCandidate(
                candidate_index=item.candidate_index,
                member_id=item.member_id,
                configuration_hash=item.configuration_hash,
                forecasts_sha256=item.forecasts_sha256,
                objective=quantize_half_even(value) if value is not None else None,
                objective_exact=f"{value.numerator}/{value.denominator}"
                if value is not None
                else None,
                cells=item.cells,
                fallback_count=item.fallback_count,
                dispatched_step_count=item.dispatched_step_count,
                rank=ranks.get(item.candidate_index),
                status=status,
            )
        )
    record = ModelPackCalibrationRecord(
        identifier=f"model-pack-calibration-record-{record_id}-{record_version}",
        tenant_id=protocol.tenant_id,
        record_id=record_id,
        record_version=record_version,
        binding_manifest_id=binding.identifier,
        binding_content_hash=binding.content_hash,
        protocol_manifest_id=protocol.identifier,
        protocol_content_hash=protocol.content_hash,
        partition="development",
        variants=tuple(
            CalibrationTargetVariant(target_path=path, variant_id=variant)
            for path, variant in sorted(variants.items())
        ),
        algorithm_id=GRID_FITTER_ID,
        algorithm_version=GRID_FITTER_VERSION,
        objective="mean_relative_wis_over_cells",
        retention_tolerance="21/20",
        max_ensemble_members=max_ensemble_members,
        reference_forecast_set_id=reference.identifier,
        reference_forecast_set_content_hash=reference.content_hash,
        candidates=tuple(candidates),
        qualifying_left_out_count=len(left_out),
        limitations=tuple(limitations),
        calibrated_at=calibrated_at,
        content_hash="0" * 64,
        metadata=metadata,
    )
    return record.model_copy(
        update={"content_hash": compute_model_pack_calibration_record_content_hash(record)}
    )


def verify_model_pack_calibration_record(
    record: ModelPackCalibrationRecord,
    *,
    binding: ModelPackAuthoringBinding,
    members: Sequence[MechanismForecastMember],
    rule: InitialStateRule,
    variants: Mapping[str, str],
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
    reference: ForecastSet,
    reference_csv: bytes,
) -> None:
    error = CalibrationVerificationError
    if type(record) is not ModelPackCalibrationRecord:
        raise error("invalid_manifest")
    try:
        item = ModelPackCalibrationRecord.model_validate(
            record.model_dump(mode="python", warnings="error"), strict=True
        )
    except Exception:
        raise error("invalid_manifest") from None
    try:
        verify_model_pack_authoring_binding(
            binding, protocol, split_manifest, curated_manifest, curated_files, raw_bundles
        )
    except Exception:
        raise error("binding_invalid") from None
    if (item.binding_manifest_id, item.binding_content_hash) != (
        binding.identifier,
        binding.content_hash,
    ):
        raise error("binding_reference_mismatch")
    if (item.protocol_manifest_id, item.protocol_content_hash) != (
        protocol.identifier,
        protocol.content_hash,
    ):
        raise error("protocol_reference_mismatch")
    if item.tenant_id != protocol.tenant_id:
        raise error("tenant_mismatch")
    if item.calibrated_at < binding.declared_at:
        raise error("lock_order_invalid")
    if type(reference) is not ForecastSet or (
        (item.reference_forecast_set_id, item.reference_forecast_set_content_hash)
        != (reference.identifier, reference.content_hash)
        or reference.partition != "development"
        or (
            reference.producer.kind,
            reference.producer.producer_id,
            reference.producer.producer_version,
        )
        != (
            "baseline",
            protocol.comparison.reference_baseline_id,
            protocol.comparison.reference_baseline_version,
        )
    ):
        raise error("reference_mismatch")
    if item.content_hash != compute_model_pack_calibration_record_content_hash(item):
        raise error("content_hash_mismatch")
    if tuple((v.target_path, v.variant_id) for v in item.variants) != tuple(
        sorted(variants.items())
    ):
        raise error("variant_mismatch")
    if tuple(member.member_id for member in members) != tuple(
        candidate.member_id for candidate in item.candidates
    ):
        raise error("members_mismatch")
    try:
        results = tuple(
            evaluate_calibration_candidate(
                candidate_index=index,
                member=member,
                binding=binding,
                rule=rule,
                variants=variants,
                protocol=protocol,
                split_manifest=split_manifest,
                curated_manifest=curated_manifest,
                curated_files=curated_files,
                raw_bundles=raw_bundles,
                reference=reference,
                reference_csv=reference_csv,
            )
            for index, member in enumerate(members, 1)
        )
        rebuilt = build_model_pack_calibration_record(
            record_id=item.record_id,
            record_version=item.record_version,
            binding=binding,
            protocol=protocol,
            variants=variants,
            reference=reference,
            results=results,
            max_ensemble_members=item.max_ensemble_members,
            limitations=item.limitations,
            calibrated_at=item.calibrated_at,
            metadata=item.metadata,
        )
        if rebuilt.content_hash != item.content_hash:
            raise error("reexecution_mismatch")
    except error:
        raise
    except Exception:
        raise error("reexecution_mismatch") from None
