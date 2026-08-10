"""Health check contract (v1)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HealthStatus(StrEnum):
    """Liveness status of the KALHAS service."""

    OK = "ok"


class HealthResponse(BaseModel):
    """Minimal liveness response."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus = HealthStatus.OK
    service: str = "kalhas"
    version: str
    api_version: str
