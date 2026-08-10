"""Shared, versioned contract types used across the v1 API."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RuntimeMode(StrEnum):
    """Runtime mode of the KALHAS process."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ErrorCode(StrEnum):
    """Stable machine-readable error codes for the v1 API."""

    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    INVALID_STATE = "invalid_state"
    INTEGRITY_ERROR = "integrity_error"
    INTERNAL_ERROR = "internal_error"
    HTTP_ERROR = "http_error"


class ErrorDetail(BaseModel):
    """One actionable detail attached to an error response."""

    model_config = ConfigDict(extra="forbid")

    loc: tuple[str | int, ...] = ()
    message: str


class ApiErrorResponse(BaseModel):
    """The single typed error shape for every KALHAS API error."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None
