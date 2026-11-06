"""Bounded errors for offline mechanism forecasts."""

from kalhas.application.domain_errors import KalhasDomainError


class MechanismForecastError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Mechanism forecast failed and was rejected")


class MechanismForecastVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Mechanism forecast verification failed and was rejected")
