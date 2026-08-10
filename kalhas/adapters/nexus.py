"""Boundary protocol for NEXUS.

NEXUS owns natural-language dialogue, organizational context, memory, and
presentation. KALHAS only ever talks to NEXUS through this protocol; it never
imports NEXUS internals.
"""

from __future__ import annotations

from typing import Protocol

from kalhas.contracts.v1.scenario import ContextBundle
from kalhas.contracts.v1.simulation import DecisionBrief


class NexusAdapter(Protocol):
    """Placeholder protocol for the NEXUS boundary.

    No integration is implemented in Phase 1. Signatures are refined now that
    the public contracts exist; concrete adapters land in a later phase.
    """

    def present(self, brief: DecisionBrief, context: ContextBundle | None = None) -> str:
        """Render a decision brief for NEXUS to present. Placeholder, not implemented."""
        ...
