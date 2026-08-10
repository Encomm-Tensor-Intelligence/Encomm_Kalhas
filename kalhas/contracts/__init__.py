"""Versioned public contracts.

Public response and error contracts are frozen per API version. ``v1`` is
the current contract surface; any breaking change requires a new version
module (``v2``, ...) and a new API version segment - never an in-place
mutation of an existing one.
"""

from kalhas.contracts.v1 import API_VERSION
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode, ErrorDetail, RuntimeMode
from kalhas.contracts.v1.health import HealthResponse
from kalhas.contracts.v1.system_info import SystemInfoResponse

__all__ = [
    "API_VERSION",
    "ApiErrorResponse",
    "ErrorCode",
    "ErrorDetail",
    "HealthResponse",
    "RuntimeMode",
    "SystemInfoResponse",
]
