"""Typed adaptive-condition evaluation errors (Phase 28, H28-S03).

The pure deterministic condition evaluator raises these instead of leaking
generic ``ValueError`` instances. Both derive from
:class:`KalhasDomainError` so the API layer can map them to its typed error
response shape.

Public messages stay safe and generic: they never expose raw observation
values, event payloads, thresholds, hashes, identifiers, or other sensitive
provenance. The optional internal ``reason`` attribute is for diagnostics
only and names at most the violated rule, never the offending content.
Each class declares a class-level ``_PUBLIC_MESSAGE`` constant that the
parent constructor forwards to the domain base, so a subclass instance's
public message is always the subclass's own generic message while the
caller-supplied ``reason`` is preserved exactly and never overwritten by it.

This module is dependency-neutral and pure: it imports only the shared
domain-error base and derives two closed error subtypes. There is no
I/O, randomness, wall clock, network, store, adapter, NEXUS, or LEGION
dependency anywhere in this module.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class AdaptiveConditionEvaluationError(KalhasDomainError):
    """A general adaptive-condition input or integrity rule was violated.

    Raised when input preflight or closed-evaluation invariants fail before
    any result is produced: a malformed decision step, a non-canonical event
    tuple, incomplete, duplicate, extra, undeclared, or externally missing
    event coverage, wrong provenance identity or hashes, a future, late, or
    terminal event, a forged content hash, a non-authoritative condition, or
    an operator/kind/unit disagreement. The public message stays generic;
    the optional ``reason`` (diagnostics only) names the violated rule,
    never the offending values. The inputs are never repaired, sorted,
    coerced, synthesized, or silently accepted.
    """

    #: The single stable generic public message shared by every general
    #: error instance. It never leaks identifiers, values, thresholds,
    #: hashes, or payloads.
    _PUBLIC_MESSAGE = (
        "Adaptive condition evaluation failed input or integrity verification and was rejected"
    )

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        super().__init__(type(self)._PUBLIC_MESSAGE)


class AdaptiveConditionMissingObservationError(AdaptiveConditionEvaluationError):
    """A referenced observation is missing and its declaration fails closed.

    Raised during eager evaluation when a comparison leaf observes a missing
    event whose declared ``missing_behavior`` is exactly ``\"error\"``. No
    partial result is produced; a missing observation with behavior
    ``\"error\"`` fails even when a sibling has already determined the boolean
    aggregate. The public message stays generic and the caller-supplied
    ``reason`` is preserved exactly; the ``reason`` (diagnostics only) names
    only the violated rule, never the offending values. This class remains a
    subclass of both :class:`AdaptiveConditionEvaluationError` and
    :class:`KalhasDomainError`.
    """

    #: The single stable generic public message for a missing-observation
    #: failure. Never leaks identifiers, values, thresholds, hashes, or
    #: payloads.
    _PUBLIC_MESSAGE = (
        "A referenced observation is missing and its declared missing "
        "behavior requires evaluation to fail closed"
    )

    # ``__init__`` is inherited from ``AdaptiveConditionEvaluationError``;
    # ``type(self)._PUBLIC_MESSAGE`` resolves to this subclass constant, so
    # the supplied ``reason`` is preserved exactly and the public message is
    # this class's own generic message.


__all__ = [
    "AdaptiveConditionEvaluationError",
    "AdaptiveConditionMissingObservationError",
]
