"""Mock LEGION boundary for the standalone local flow.

Implements ``LegionAdapter`` without importing any LEGION code. For one
valid StrategyRequest it returns exactly five deterministic, domain-neutral,
versioned StrategyCandidate contracts with identical observation
permissions. The labels (baseline, conservative, balanced, adaptive,
diversified) are mock policy labels only: policies are declared, never
executed.
"""

from __future__ import annotations

from kalhas.contracts.v1.shared import Assumption
from kalhas.contracts.v1.strategy import (
    PolicyDeclaration,
    PolicyRule,
    StrategyCandidate,
    StrategyRequest,
)
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)

MOCK_STRATEGY_LABELS = ("baseline", "conservative", "balanced", "adaptive", "diversified")

_MOCK_RULES: dict[str, tuple[str, dict[str, float]]] = {
    "baseline": ("Follow the declared baseline policy", {"aggressiveness": 0.0}),
    "conservative": ("Prefer low-risk moves", {"aggressiveness": 0.25}),
    "balanced": ("Balance risk and reward evenly", {"aggressiveness": 0.5}),
    "adaptive": ("Adjust posture to observed conditions", {"aggressiveness": 0.75}),
    "diversified": ("Spread commitment across options", {"aggressiveness": 1.0}),
}


class MockLegionAdapter:
    """Deterministic local mock of the LEGION strategy boundary."""

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        """Return exactly five deterministic candidates for any valid request."""
        observations = list(request.required_observations)
        return tuple(
            StrategyCandidate(
                identifier=f"mock-{label}",
                tenant_id=request.tenant_id,
                strategy_version="1.0.0",
                policy=PolicyDeclaration(
                    summary=f"Declared mock policy: {label}",
                    rules=[
                        PolicyRule(
                            identifier=f"mock-{label}-rule-1",
                            statement=statement,
                            parameters=dict(parameters),
                        )
                    ],
                ),
                required_observations=observations,
                assumptions=[
                    Assumption(
                        identifier=f"mock-{label}-assumption-1",
                        statement="Declared mock assumption: conditions remain stable",
                        confidence=0.9,
                    )
                ],
            )
            for label, (statement, parameters) in _MOCK_RULES.items()
        )

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        """Propose the available transitions in their supplied canonical order.

        Deterministic local mock: it uses only the transitions supplied in
        the request's available catalog, performs no evaluation, inspects
        no guard or target state values for decision-making, invokes no
        pack or external system, and uses no randomness or wall clock. The
        same ordered available sequence is returned for every strategy -
        Phase 15 proves the boundary and immutable recording, not strategy
        intelligence.
        """
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=tuple(
                transition.identifier for transition in request.available_transitions
            ),
        )
