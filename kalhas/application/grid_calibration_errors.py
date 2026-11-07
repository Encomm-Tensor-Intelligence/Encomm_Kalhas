"""Bounded errors for grid calibration and verification."""

from kalhas.application.domain_errors import KalhasDomainError


class CalibrationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Calibration failed and was rejected")


class CalibrationVerificationError(KalhasDomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Calibration verification failed and was rejected")
