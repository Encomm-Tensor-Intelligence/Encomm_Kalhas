"""Typed errors for the Phase 30 curated-dataset engine and verifier (H30-S02A).

Two safe typed application errors. They follow the established KALHAS
typed-error style: each public message is a single generic sentence that
never exposes cell values, file bytes, relative paths, hashes, column data,
or tenant data. The bounded internal ``reason`` code exists for diagnostics
only and is never rendered into the public message.

This module adds no public contract, no schema, and no registry item, and
it must not be re-exported through ``kalhas.application.__init__``.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError

__all__ = ["CuratedDatasetVerificationError", "DatasetTransformationError"]


class DatasetTransformationError(KalhasDomainError):
    """A transformation plan failed and produced no output.

    ``reason`` is one bounded internal code (``invalid_plan``,
    ``invalid_input``, ``missing_source``, ``decode_failed``,
    ``parse_failed``, ``header_mismatch``, ``row_width_mismatch``,
    ``unknown_column``, ``duplicate_column``, ``cast_failed``,
    ``ambiguous_missing`` or ``duplicate_key``). It never carries a cell
    value, path, or hash.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Dataset transformation plan failed and was rejected; no output was produced"
        )


class CuratedDatasetVerificationError(KalhasDomainError):
    """A curated dataset bundle failed verification and was rejected.

    ``reason`` is one bounded internal code (``invalid_manifest``,
    ``invalid_input``, ``raw_input_invalid``, ``reference_mismatch``,
    ``tenant_mismatch``, ``license_mismatch``, ``not_reproducible``,
    ``missing_file``, ``undeclared_file``, ``size_mismatch``,
    ``sha256_mismatch``, ``columns_mismatch``, ``bundle_hash_mismatch`` or
    ``content_hash_mismatch``). It carries no bytes, paths, hashes, or
    tenant data.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            "Curated dataset bundle failed verification and was rejected; "
            "no part of the bundle was accepted"
        )
