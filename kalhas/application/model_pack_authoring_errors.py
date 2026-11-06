"""Bounded errors for observation and authoring verification."""

from kalhas.application.domain_errors import KalhasDomainError


class ObservationOperatorError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Observation evaluation failed and was rejected")


class ModelPackAuthoringVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Authoring verification failed and was rejected")
