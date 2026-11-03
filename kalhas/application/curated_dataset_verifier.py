"""Pure curated-dataset verifier by re-execution (Phase 30, H30-S02A, ADR-007).

``verify_curated_dataset_bundle`` is a pure function over one
``CuratedDatasetManifest``, the referenced raw manifests with their raw
bytes, and the curated bytes. It performs no filesystem, network, clock,
randomness, logging, or global-state access and never mutates its inputs.

It raises exactly one ``CuratedDatasetVerificationError`` and checks, in
order: exact type and detached strict revalidation; every input resolves and
its raw bundle passes the ADR-006 verifier; the reference hashes equal the
raw manifests' hashes; every raw input has the curated manifest's tenant;
the curated license equals every raw input's license exactly; the plan
re-executes; the supplied curated files are exactly the declared files; the
declared sizes and SHA-256 values equal the re-executed bytes and the
supplied bytes; the declared output columns equal the engine's output
declarations; and the bundle hash and the self-covering content hash
recompute exactly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from kalhas.application.dataset_transformation_engine import (
    derive_transformation_output_columns,
    execute_transformation_plan,
)
from kalhas.application.dataset_transformation_errors import (
    CuratedDatasetVerificationError,
    DatasetTransformationError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.raw_dataset_errors import RawDatasetVerificationError
from kalhas.application.raw_dataset_verifier import (
    compute_raw_dataset_bundle_hash,
    verify_raw_dataset_bundle,
)
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest

__all__ = [
    "compute_curated_dataset_bundle_hash",
    "compute_curated_dataset_content_hash",
    "verify_curated_dataset_bundle",
]


def compute_curated_dataset_bundle_hash(manifest: CuratedDatasetManifest) -> str:
    """The ADR-006 bundle-hash rule applied to the declared curated files."""
    return compute_raw_dataset_bundle_hash(manifest.files)


def compute_curated_dataset_content_hash(manifest: CuratedDatasetManifest) -> str:
    """The self-covering hash: canonical JSON dump minus ``content_hash``."""
    dumped: dict[str, object] = manifest.model_dump(mode="json")
    dumped.pop("content_hash")
    return sha256_hex(canonical_json(dumped))


def _fail(reason: str) -> CuratedDatasetVerificationError:
    return CuratedDatasetVerificationError(reason)


def _detached_revalidated(manifest: CuratedDatasetManifest) -> CuratedDatasetManifest:
    """Strictly revalidate a detached serialized copy of an untrusted manifest."""
    try:
        payload = manifest.model_dump(mode="python")
        return CuratedDatasetManifest.model_validate(payload, strict=True)
    except Exception as exc:
        raise _fail("invalid_manifest") from exc


def verify_curated_dataset_bundle(
    manifest: CuratedDatasetManifest,
    raw_bundles: Mapping[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
    curated_files: Mapping[str, bytes],
) -> None:
    """Verify a curated bundle by re-executing its plan, failing closed."""
    if type(manifest) is not CuratedDatasetManifest:
        raise _fail("invalid_manifest")
    verified = _detached_revalidated(manifest)

    if not isinstance(raw_bundles, Mapping) or not isinstance(curated_files, Mapping):
        raise _fail("invalid_input")
    try:
        supplied = dict(curated_files.items())
        raw_entries = dict(raw_bundles.items())
    except Exception as exc:
        raise _fail("invalid_input") from exc
    for path, content in supplied.items():
        if type(path) is not str or type(content) is not bytes:
            raise _fail("invalid_input")

    resolved: dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]] = {}
    for reference in verified.inputs:
        entry = raw_entries.get(reference.raw_manifest_id)
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise _fail("raw_input_invalid")
        raw_manifest, raw_files = entry
        if (
            type(raw_manifest) is not RawDatasetManifest
            or raw_manifest.identifier != reference.raw_manifest_id
        ):
            raise _fail("raw_input_invalid")
        try:
            verify_raw_dataset_bundle(raw_manifest, raw_files)
        except RawDatasetVerificationError as exc:
            raise _fail("raw_input_invalid") from exc
        resolved[reference.raw_manifest_id] = (raw_manifest, raw_files)

    for reference in verified.inputs:
        raw_manifest = resolved[reference.raw_manifest_id][0]
        if (
            reference.raw_content_hash != raw_manifest.content_hash
            or reference.raw_bundle_hash != raw_manifest.bundle_hash
        ):
            raise _fail("reference_mismatch")
    for raw_manifest, _ in resolved.values():
        if raw_manifest.tenant_id != verified.tenant_id:
            raise _fail("tenant_mismatch")
    for raw_manifest, _ in resolved.values():
        if raw_manifest.license != verified.license:
            raise _fail("license_mismatch")

    try:
        executed = execute_transformation_plan(verified.plan, resolved)
        output_columns = derive_transformation_output_columns(verified.plan, resolved)
    except DatasetTransformationError as exc:
        raise _fail("not_reproducible") from exc

    declared_paths = {file.path for file in verified.files}
    if declared_paths - set(supplied):
        raise _fail("missing_file")
    if set(supplied) - declared_paths:
        raise _fail("undeclared_file")

    for file in verified.files:
        produced = executed.get(file.path)
        if produced is None:
            raise _fail("not_reproducible")
        for content in (produced, supplied[file.path]):
            if len(content) != file.byte_size:
                raise _fail("size_mismatch")
            if hashlib.sha256(content).hexdigest() != file.sha256:
                raise _fail("sha256_mismatch")
    for file in verified.files:
        if tuple(file.columns) != output_columns.get(file.path):
            raise _fail("columns_mismatch")

    if compute_curated_dataset_bundle_hash(verified) != verified.bundle_hash:
        raise _fail("bundle_hash_mismatch")
    if compute_curated_dataset_content_hash(verified) != verified.content_hash:
        raise _fail("content_hash_mismatch")
