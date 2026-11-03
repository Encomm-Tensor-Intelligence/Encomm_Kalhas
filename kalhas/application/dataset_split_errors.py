"""Generic typed errors for split computation and verification."""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class DatasetSplitError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Dataset split operation failed and was rejected")


class DatasetSplitVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Dataset split verification failed and was rejected")


class SealedPartitionError(KalhasDomainError):
    def __init__(self) -> None:
        super().__init__("The requested partition is sealed")
