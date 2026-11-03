"""Pure split verification and sealed partition views."""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping
from typing import Literal

from kalhas.application.curated_dataset_verifier import verify_curated_dataset_bundle
from kalhas.application.dataset_split_engine import _rows, compute_split_membership
from kalhas.application.dataset_split_errors import (
    DatasetSplitError,
    DatasetSplitVerificationError,
    SealedPartitionError,
)
from kalhas.application.dataset_transformation_errors import CuratedDatasetVerificationError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest


def compute_dataset_split_content_hash(manifest: DatasetSplitManifest) -> str:
    payload: dict[str, object] = manifest.model_dump(mode="json")
    payload.pop("content_hash")
    return sha256_hex(canonical_json(payload))


def _detached(manifest: DatasetSplitManifest) -> DatasetSplitManifest:
    if type(manifest) is not DatasetSplitManifest:
        raise DatasetSplitVerificationError("invalid_manifest")
    try:
        return DatasetSplitManifest.model_validate(manifest.model_dump(mode="python"), strict=True)
    except Exception as exc:
        raise DatasetSplitVerificationError("invalid_manifest") from exc


def _reference_matches(split: DatasetSplitManifest, curated: CuratedDatasetManifest) -> bool:
    return (
        split.curated_manifest_id == curated.identifier
        and split.curated_content_hash == curated.content_hash
        and split.curated_bundle_hash == curated.bundle_hash
    )


def verify_dataset_split(
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
) -> None:
    """Revalidate the split, its curated chain, memberships and lock in order."""
    split = _detached(split_manifest)
    try:
        verify_curated_dataset_bundle(curated_manifest, raw_bundles, curated_files)
    except CuratedDatasetVerificationError as exc:
        raise DatasetSplitVerificationError("curated_input_invalid") from exc
    if not _reference_matches(split, curated_manifest):
        raise DatasetSplitVerificationError("reference_mismatch")
    if split.tenant_id != curated_manifest.tenant_id:
        raise DatasetSplitVerificationError("tenant_mismatch")
    if [rule.path for rule in split.file_rules] != [file.path for file in curated_manifest.files]:
        raise DatasetSplitVerificationError("coverage_mismatch")
    try:
        computed = compute_split_membership(split.file_rules, curated_manifest, curated_files)
    except DatasetSplitError as exc:
        raise DatasetSplitVerificationError("membership_mismatch") from exc
    for item in split.memberships:
        _, counts, digest = computed[item.path]
        if counts != item.counts or digest != item.membership_hash:
            raise DatasetSplitVerificationError("membership_mismatch")
    if compute_dataset_split_content_hash(split) != split.content_hash:
        raise DatasetSplitVerificationError("content_hash_mismatch")


def select_partition_rows(
    split_manifest: DatasetSplitManifest,
    curated_manifest: CuratedDatasetManifest,
    curated_files: Mapping[str, bytes],
    path: str,
    partition: Literal["development", "validation", "holdout"],
) -> bytes:
    """Return a canonical view after caller verification; sealed rows are refused."""
    if partition == "holdout":
        raise SealedPartitionError()
    if partition not in ("development", "validation"):
        raise DatasetSplitError("invalid_partition")
    try:
        split = _detached(split_manifest)
        if type(curated_manifest) is not CuratedDatasetManifest or not _reference_matches(
            split, curated_manifest
        ):
            raise DatasetSplitError("reference_mismatch")
        if (
            split.tenant_id != curated_manifest.tenant_id
            or compute_dataset_split_content_hash(split) != split.content_hash
        ):
            raise DatasetSplitError("invalid_manifest")
        if [rule.path for rule in split.file_rules] != [
            file.path for file in curated_manifest.files
        ]:
            raise DatasetSplitError("coverage_mismatch")
        file = next(file for file in curated_manifest.files if file.path == path)
        content = curated_files[path]
        if (
            type(content) is not bytes
            or len(content) != file.byte_size
            or hashlib.sha256(content).hexdigest() != file.sha256
        ):
            raise DatasetSplitError("invalid_input")
        rule = next(rule for rule in split.file_rules if rule.path == path)
        labels, counts, digest = compute_split_membership((rule,), curated_manifest, curated_files)[
            path
        ]
        membership = next(item for item in split.memberships if item.path == path)
        if counts != membership.counts or digest != membership.membership_hash:
            raise DatasetSplitError("membership_mismatch")
        header = [column.name for column in file.columns]
        rows = _rows(content, header)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(row for row, label in zip(rows, labels, strict=True) if label == partition)
        return output.getvalue().encode("utf-8")
    except (KeyError, StopIteration, TypeError, DatasetSplitVerificationError) as exc:
        raise DatasetSplitError("invalid_input") from exc
