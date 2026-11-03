"""Pure benchmark protocol verification through the complete input chain."""

from __future__ import annotations

from collections.abc import Mapping

from kalhas.application.benchmark_errors import BenchmarkProtocolVerificationError
from kalhas.application.dataset_split_errors import DatasetSplitVerificationError
from kalhas.application.dataset_split_verifier import verify_dataset_split
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest


def compute_benchmark_protocol_content_hash(protocol: BenchmarkProtocol) -> str:
    payload: dict[str, object] = protocol.model_dump(mode="json")
    payload.pop("content_hash")
    return sha256_hex(canonical_json(payload))


def _targets_valid(protocol: BenchmarkProtocol, curated: CuratedDatasetManifest) -> bool:
    files = {file.path: file for file in curated.files}
    for target in protocol.targets:
        file = files.get(target.path)
        if file is None:
            return False
        columns = {col.name: col for col in file.columns}
        if (
            target.series_column not in columns
            or target.series_column not in curated.geography_basis.geography_columns
        ):
            return False
        if (
            target.time_column not in columns
            or target.time_column not in curated.time_basis.time_columns
            or columns[target.time_column].value_type not in ("date", "iso_week")
        ):
            return False
        if target.value_column not in columns or columns[target.value_column].value_type not in (
            "decimal",
            "integer",
        ):
            return False
    return True


def verify_benchmark_protocol(
    protocol: BenchmarkProtocol,
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    if type(protocol) is not BenchmarkProtocol:
        raise BenchmarkProtocolVerificationError("invalid_manifest")
    try:
        checked = BenchmarkProtocol.model_validate(protocol.model_dump(mode="python"), strict=True)
    except Exception as exc:
        raise BenchmarkProtocolVerificationError("invalid_manifest") from exc
    try:
        verify_dataset_split(split_manifest, curated_manifest, curated_files, raw_bundles)
    except DatasetSplitVerificationError as exc:
        raise BenchmarkProtocolVerificationError("split_input_invalid") from exc
    if (
        checked.split_manifest_id != split_manifest.identifier
        or checked.split_content_hash != split_manifest.content_hash
    ):
        raise BenchmarkProtocolVerificationError("split_reference_mismatch")
    if (checked.curated_manifest_id, checked.curated_content_hash, checked.curated_bundle_hash) != (
        split_manifest.curated_manifest_id,
        split_manifest.curated_content_hash,
        split_manifest.curated_bundle_hash,
    ) or (
        checked.curated_manifest_id,
        checked.curated_content_hash,
        checked.curated_bundle_hash,
    ) != (curated_manifest.identifier, curated_manifest.content_hash, curated_manifest.bundle_hash):
        raise BenchmarkProtocolVerificationError("curated_reference_mismatch")
    if checked.tenant_id != split_manifest.tenant_id:
        raise BenchmarkProtocolVerificationError("tenant_mismatch")
    if checked.locked_at < split_manifest.locked_at:
        raise BenchmarkProtocolVerificationError("lock_order_invalid")
    if not _targets_valid(checked, curated_manifest):
        raise BenchmarkProtocolVerificationError("target_invalid")
    if compute_benchmark_protocol_content_hash(checked) != checked.content_hash:
        raise BenchmarkProtocolVerificationError("content_hash_mismatch")
