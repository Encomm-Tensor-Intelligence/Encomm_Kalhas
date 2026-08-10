"""Local deterministic mocks for the standalone integration flow.

These mocks use only KALHAS public contracts and application services.
They are proof-of-flow stand-ins: no real NEXUS or LEGION code is imported
or called, and nothing leaves the process.
"""

from kalhas.adapters.mocks.legion import MockLegionAdapter
from kalhas.adapters.mocks.nexus import MockNexusAdapter

__all__ = ["MockLegionAdapter", "MockNexusAdapter"]
