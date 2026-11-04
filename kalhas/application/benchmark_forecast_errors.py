"""Bounded errors for offline forecast and score verification."""

from kalhas.application.domain_errors import KalhasDomainError


class BenchmarkForecastVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Benchmark forecast verification failed and was rejected")


class BenchmarkScoreVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Benchmark score verification failed and was rejected")


class BenchmarkBaselineVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Benchmark baseline verification failed and was rejected")
