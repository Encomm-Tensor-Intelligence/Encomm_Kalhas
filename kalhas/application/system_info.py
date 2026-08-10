"""Use case: assemble system information for the v1 API."""

from kalhas.contracts.v1 import API_VERSION
from kalhas.contracts.v1.common import RuntimeMode
from kalhas.contracts.v1.system_info import SystemInfoResponse
from kalhas.version import __version__


def get_system_info(runtime_mode: RuntimeMode) -> SystemInfoResponse:
    """Return the metadata describing the running KALHAS instance."""
    return SystemInfoResponse(
        application_version=__version__,
        api_version=API_VERSION,
        runtime_mode=runtime_mode,
    )
