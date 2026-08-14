"""Mock LEGION boundary for the standalone local flow.

Implements ``LegionAdapter`` without importing any LEGION code. For one
valid StrategyRequest it returns exactly five deterministic, domain-neutral,
versioned StrategyCandidate contracts with identical observation
permissions. The labels (baseline, conservative, balanced, adaptive,
diversified) are mock policy labels only: policies are declared, never
executed.

Phase 25 (Amendment 4): trajectory-plan proposals become fail-closed and
strategy-differentiated through the optional ``declared_transition_sequences``
constructor argument. Declarations are keyed by the exact strategy
candidate identifier and list logical ``DomainStateTransition.transition_id``
values in the exact proposed order (repetitions allowed and significant);
the mock resolves them to the deterministic transition identifiers of the
request's available catalog. Any invalid declaration - an unknown logical
id, or an ambiguous available catalog with duplicate logical ids - raises
the typed :class:`InvalidTrajectoryDraftError` and never falls back to the
canonical sequence, never returns a partial draft, and never inspects
guards, targets, state values, policies, metrics, scores, or outcomes.
The default constructor (``None``) preserves the historical canonical
behavior byte-identically: every strategy receives the available
transitions in their supplied order. KALHAS remains the authority for
membership, bounds, identifiers, and hashes; the returned draft always
flows through the unchanged service revalidation and authoritative
binding chain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kalhas.application.domain_errors import InvalidTrajectoryDraftError
from kalhas.contracts.v1.shared import Assumption
from kalhas.contracts.v1.strategy import (
    PolicyDeclaration,
    PolicyRule,
    StrategyCandidate,
    StrategyRequest,
)
from kalhas.contracts.v1.trajectory import (
    MAX_TRAJECTORY_PLAN_TRANSITIONS,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition

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

    #: The immutable per-strategy declaration snapshot; empty means no
    #: strategy has an explicit declaration. The class-level default keeps
    #: historical subclasses that override ``__init__`` without calling
    #: ``super`` (the original adapter had no constructor) on the exact
    #: canonical path.
    _declared_transition_sequences: dict[str, tuple[str, ...]] = {}

    def __init__(
        self,
        declared_transition_sequences: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        """Optionally declare per-strategy trajectory transition sequences.

        ``None`` preserves the historical canonical behavior exactly: every
        strategy receives the request's available transitions in their
        supplied order. An explicit mapping keys each declaration by the
        exact strategy candidate identifier; each value must be a list or
        tuple of non-empty logical transition ids (length 1 through
        ``MAX_TRAJECTORY_PLAN_TRANSITIONS``, repetitions allowed and
        significant). The complete mapping is snapshotted into immutable
        tuples during construction, so later mutation of the caller's
        mapping or its nested lists has zero effect. An empty mapping
        behaves as ``no strategy has an explicit declaration``. Invalid
        declarations are rejected with ``ValueError`` - never silently
        removed, sorted, deduplicated, truncated, normalized, or replaced.
        """
        if declared_transition_sequences is None:
            self._declared_transition_sequences = {}
            return
        if not isinstance(declared_transition_sequences, Mapping):
            raise ValueError("declared_transition_sequences must be a mapping")
        snapshotted: dict[str, tuple[str, ...]] = {}
        for key, sequence in declared_transition_sequences.items():
            if not isinstance(key, str) or not key:
                raise ValueError("declared strategy keys must be non-empty strings")
            if not isinstance(sequence, (list, tuple)):
                raise ValueError("declared transition sequences must be lists or tuples")
            if not 1 <= len(sequence) <= MAX_TRAJECTORY_PLAN_TRANSITIONS:
                raise ValueError(
                    "declared transition sequence length must be between 1 and "
                    "MAX_TRAJECTORY_PLAN_TRANSITIONS"
                )
            resolved: list[str] = []
            for entry in sequence:
                if not isinstance(entry, str) or not entry:
                    raise ValueError("declared transition entries must be non-empty strings")
                resolved.append(entry)
            snapshotted[key] = tuple(resolved)
        self._declared_transition_sequences = snapshotted

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
        """Propose an ordered transition sequence for one strategy request.

        The default behavior is the historical canonical draft: the
        available transitions in their supplied order, byte-identical for
        every strategy. When the exact strategy candidate identifier has an
        explicit declaration, the declaration's logical transition ids are
        resolved to the deterministic identifiers of the request's
        available catalog in the exact declared order, repetitions
        preserved; an unknown logical id, or an available catalog with
        duplicate logical ids, raises :class:`InvalidTrajectoryDraftError`
        and never substitutes the canonical sequence or returns a partial
        draft. The mock performs no evaluation, inspects no guard or
        target state values, invokes no pack or external system, and uses
        no randomness or wall clock. KALHAS re-validates every draft and
        remains the authority for membership, bounds, identifiers, and
        hashes.
        """
        declared = self._declared_transition_sequences.get(request.strategy_candidate.identifier)
        if declared is None:
            return StrategyTrajectoryPlanDraft(
                request_id=request.identifier,
                ordered_transition_identifiers=tuple(
                    transition.identifier for transition in request.available_transitions
                ),
            )
        by_logical_id: dict[str, DomainStateTransition] = {}
        for transition in request.available_transitions:
            if transition.transition_id in by_logical_id:
                raise InvalidTrajectoryDraftError(
                    request.identifier,
                    reason="available transition catalog is ambiguous",
                )
            by_logical_id[transition.transition_id] = transition
        ordered: list[str] = []
        for logical_id in declared:
            resolved_transition = by_logical_id.get(logical_id)
            if resolved_transition is None:
                raise InvalidTrajectoryDraftError(
                    request.identifier,
                    reason="declared transition id is not in the available catalog",
                )
            ordered.append(resolved_transition.identifier)
        return StrategyTrajectoryPlanDraft(
            request_id=request.identifier,
            ordered_transition_identifiers=tuple(ordered),
        )
