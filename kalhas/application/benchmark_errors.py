"""Generic errors for benchmark tasks and protocol verification."""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class BenchmarkError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Benchmark operation failed and was rejected")


class BenchmarkProtocolVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Benchmark protocol verification failed and was rejected")
