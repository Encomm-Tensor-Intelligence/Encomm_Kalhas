"""Adapter boundaries toward NEXUS and LEGION.

Phase 0 ships protocol placeholders only - no concrete integrations. KALHAS
core depends on these protocols, never on NEXUS or LEGION internals.
"""

from kalhas.adapters.legion import LegionAdapter
from kalhas.adapters.nexus import NexusAdapter

__all__ = ["LegionAdapter", "NexusAdapter"]
