"""Boundary protocol for LEGION.

LEGION owns strategy and agent exploration. KALHAS only ever talks to LEGION
through this protocol; it never imports LEGION internals.
"""

from __future__ import annotations

from typing import Protocol

from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)


class LegionAdapter(Protocol):
    """Placeholder protocol for the LEGION boundary.

    No integration is implemented in Phase 1. Signatures are refined now that
    the public contracts exist; concrete adapters land in a later phase.
    """

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        """Ask LEGION for an ordered set of strategy candidates. Placeholder, not implemented."""
        ...

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        """Ask LEGION to propose an ordered transition sequence for one verified world catalog.

        LEGION proposes; KALHAS verifies and binds. The draft is an untrusted
        proposal only - it carries no hashes, state values, or executable
        content, and LEGION never supplies plan identifiers or content
        hashes. Placeholder, not implemented.
        """
        ...
