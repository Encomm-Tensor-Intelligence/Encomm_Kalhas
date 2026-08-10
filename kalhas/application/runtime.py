"""Runtime configuration resolution.

Phase 0 reads a single environment variable; there is no config file and no
external provider configuration.
"""

import os

from kalhas.contracts.v1.common import RuntimeMode

_ENV_VAR = "KALHAS_RUNTIME_MODE"
_DEFAULT = RuntimeMode.DEVELOPMENT


def get_runtime_mode() -> RuntimeMode:
    """Resolve the runtime mode from ``KALHAS_RUNTIME_MODE`` (default: development)."""
    raw = os.getenv(_ENV_VAR, _DEFAULT.value)
    try:
        return RuntimeMode(raw)
    except ValueError:
        return _DEFAULT
