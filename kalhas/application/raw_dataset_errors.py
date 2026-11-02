"""Typed verification error for the Phase 30 raw-dataset verifier (H30-S01).

Exactly one safe typed application error for raw-dataset bundle
verification. It follows the established KALHAS typed-error style: the
public message is a single generic sentence that never exposes file bytes,
relative paths, hashes, sizes, column declarations, or tenant data. The
bounded internal ``reason`` code exists for diagnostics only and is never
rendered into the public message.

This module adds no public contract, no schema, and no registry item, and
it must not be re-exported through ``kalhas.application.__init__``.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError

__all__ = ["RawDatasetVerificationError"]


class RawDatasetVerificationError(KalhasDomainError):
    """A raw-dataset bundle failed verification and was rejected.

    Raised for every fail-closed verification outcome: a manifest that is
    not exactly a ``RawDatasetManifest`` or fails detached strict
    revalidation, a malformed file mapping, a missing or undeclared file, a
    byte-size or SHA-256 mismatch, and a bundle-hash or content-hash
    mismatch. Exactly one error is raised per rejected bundle and nothing
    is ever repaired or partially accepted.

    ``reason`` is one bounded internal code (``invalid_manifest``,
    ``invalid_bundle``, ``missing_file``, ``undeclared_file``,
    ``size_mismatch``, ``sha256_mismatch``, ``bundle_hash_mismatch`` or
    ``content_hash_mismatch``). It carries no bytes, paths, hashes, or
    tenant data.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Raw dataset bundle failed verification and was rejected; "
            "no part of the bundle was accepted"
        )
