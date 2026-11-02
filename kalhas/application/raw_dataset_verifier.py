"""Pure raw-dataset bundle verifier (Phase 30, H30-S01, ADR-006 D30-01d).

``verify_raw_dataset_bundle`` is a pure function over one
``RawDatasetManifest`` and a mapping of relative paths to bytes. It performs
no filesystem, network, clock, randomness, logging, or global-state access
and never mutates its inputs.

Hash rules (exact):

- Bundle hash: ``compute_raw_dataset_bundle_hash`` is the SHA-256 of the
  canonical JSON of the list, in manifest order, of objects holding exactly
  ``path``, ``byte_size``, ``sha256`` and ``media_type`` for each declared
  file. Columns are excluded: they are declarations, not bytes.
- Content hash: ``compute_raw_dataset_manifest_content_hash`` follows the
  repository self-covering rule: the SHA-256 of the canonical JSON of
  ``model_dump(mode="json")`` without ``content_hash``.

Verification fails closed with exactly one ``RawDatasetVerificationError``
when the manifest is not exactly a ``RawDatasetManifest`` or fails detached
strict revalidation, when the file mapping is malformed, when a declared
file is missing or an undeclared path is present, when any byte size or
SHA-256 differs, or when the bundle hash or the content hash differs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.raw_dataset_errors import RawDatasetVerificationError
from kalhas.contracts.v1.dataset import RawDatasetFile, RawDatasetManifest

__all__ = [
    "compute_raw_dataset_bundle_hash",
    "compute_raw_dataset_manifest_content_hash",
    "verify_raw_dataset_bundle",
]


def compute_raw_dataset_bundle_hash(files: Sequence[RawDatasetFile]) -> str:
    """SHA-256 of the canonical JSON of the ordered file records.

    Each record holds exactly ``path``, ``byte_size``, ``sha256`` and
    ``media_type``; declared columns are excluded.
    """
    records = [
        {
            "path": file.path,
            "byte_size": file.byte_size,
            "sha256": file.sha256,
            "media_type": file.media_type,
        }
        for file in files
    ]
    return sha256_hex(canonical_json(records))


def compute_raw_dataset_manifest_content_hash(manifest: RawDatasetManifest) -> str:
    """The self-covering hash: canonical JSON dump minus ``content_hash``."""
    dumped: dict[str, object] = manifest.model_dump(mode="json")
    dumped.pop("content_hash")
    return sha256_hex(canonical_json(dumped))


def _detached_revalidated(manifest: RawDatasetManifest) -> RawDatasetManifest:
    """Strictly revalidate a detached serialized copy of an untrusted manifest.

    The supplied instance is never trusted directly: its content is
    revalidated from scratch, so a forged, validator-bypassed, or malformed
    manifest fails closed. Every ordinary failure becomes exactly one
    ``RawDatasetVerificationError``.
    """
    try:
        payload = manifest.model_dump(mode="python")
        return RawDatasetManifest.model_validate(payload, strict=True)
    except Exception as exc:
        raise RawDatasetVerificationError("invalid_manifest") from exc


def verify_raw_dataset_bundle(manifest: RawDatasetManifest, files: Mapping[str, bytes]) -> None:
    """Verify exact bytes against one manifest, failing closed.

    Returns ``None`` only when every declared file is present with its
    declared size and SHA-256, no undeclared path is present, and both the
    bundle hash and the manifest content hash recompute exactly.
    """
    if type(manifest) is not RawDatasetManifest:
        raise RawDatasetVerificationError("invalid_manifest")
    verified = _detached_revalidated(manifest)

    if not isinstance(files, Mapping):
        raise RawDatasetVerificationError("invalid_bundle")
    try:
        entries = list(files.items())
    except Exception as exc:
        raise RawDatasetVerificationError("invalid_bundle") from exc
    for key, value in entries:
        if type(key) is not str or type(value) is not bytes:
            raise RawDatasetVerificationError("invalid_bundle")
    supplied = dict(entries)

    for file in verified.files:
        if file.path not in supplied:
            raise RawDatasetVerificationError("missing_file")
    if set(supplied) - {file.path for file in verified.files}:
        raise RawDatasetVerificationError("undeclared_file")

    for file in verified.files:
        content = supplied[file.path]
        if len(content) != file.byte_size:
            raise RawDatasetVerificationError("size_mismatch")
        if hashlib.sha256(content).hexdigest() != file.sha256:
            raise RawDatasetVerificationError("sha256_mismatch")

    if compute_raw_dataset_bundle_hash(verified.files) != verified.bundle_hash:
        raise RawDatasetVerificationError("bundle_hash_mismatch")
    if compute_raw_dataset_manifest_content_hash(verified) != verified.content_hash:
        raise RawDatasetVerificationError("content_hash_mismatch")
