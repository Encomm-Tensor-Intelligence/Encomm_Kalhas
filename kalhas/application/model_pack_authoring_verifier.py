"""Verify a binding against an exact, locked input chain."""

from __future__ import annotations

from collections.abc import Mapping

from kalhas.application.benchmark_protocol_verifier import verify_benchmark_protocol
from kalhas.application.benchmark_task_engine import TimeType, derive_benchmark_tasks
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.model_pack_authoring_errors import ModelPackAuthoringVerificationError
from kalhas.application.observation_operators import denominator_year
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.model_pack_authoring import (
    ModelPackAuthoringBinding,
    PerHundredKOperator,
    StockSumOperator,
)


def compute_model_pack_authoring_binding_content_hash(binding: ModelPackAuthoringBinding) -> str:
    payload = binding.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_model_pack_authoring_binding(
    binding: ModelPackAuthoringBinding,
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    error = ModelPackAuthoringVerificationError
    if type(binding) is not ModelPackAuthoringBinding:
        raise error("invalid_manifest")
    try:
        item = ModelPackAuthoringBinding.model_validate(
            binding.model_dump(mode="python", warnings="error"), strict=True
        )
    except Exception:
        raise error("invalid_manifest") from None
    try:
        verify_benchmark_protocol(
            protocol, split_manifest, curated_manifest, curated_files, raw_bundles
        )
    except Exception:
        raise error("protocol_input_invalid") from None
    if (item.protocol_manifest_id, item.protocol_content_hash) != (
        protocol.identifier,
        protocol.content_hash,
    ):
        raise error("protocol_reference_mismatch")
    if item.tenant_id != protocol.tenant_id:
        raise error("tenant_mismatch")
    if item.declared_at < protocol.locked_at:
        raise error("lock_order_invalid")
    if item.content_hash != compute_model_pack_authoring_binding_content_hash(item):
        raise error("content_hash_mismatch")
    targets = {target.path: target for target in protocol.targets}
    paths = {observation.target_path for observation in item.observations}
    if paths - targets.keys():
        raise error("unknown_target")
    if targets.keys() - paths:
        raise error("target_not_covered")
    files = {file.path: file for file in curated_manifest.files}
    kinds: dict[str, TimeType] = {}
    for path, target in targets.items():
        column = next(c for c in files[path].columns if c.name == target.time_column)
        kinds[path] = "date" if column.value_type == "date" else "iso_week"
    scaled = set()
    for observation in item.observations:
        operator = observation.operator
        if isinstance(operator, PerHundredKOperator):
            scaled.add(observation.target_path)
            operator = operator.inner
        if isinstance(operator, StockSumOperator) and kinds[observation.target_path] != "date":
            raise error("operator_time_mismatch")
    if not scaled:
        return
    available = {(entry.series, entry.year) for entry in item.denominators}
    for partition in ("development", "validation"):
        try:
            tasks = derive_benchmark_tasks(
                protocol, split_manifest, curated_manifest, curated_files, partition
            )
        except Exception:
            raise error("protocol_input_invalid") from None
        for task in tasks:
            if (
                task.status == "evaluable"
                and task.path in scaled
                and (
                    task.series,
                    denominator_year(task.target_time, kinds[task.path]),
                )
                not in available
            ):
                raise error("denominator_missing")
