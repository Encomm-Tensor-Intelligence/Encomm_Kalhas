"""Typed adaptive-policy state-machine errors (Phase 28, H28-S04).

The pure deterministic policy state machine raises this single typed error
instead of leaking generic ``ValueError`` or ``TypeError`` instances. It
derives from :class:`KalhasDomainError` so the API layer can map it to its
typed error response shape, and it is dependency-neutral and pure: it imports
only the shared domain-error base.

The public message stays safe and generic: it never exposes raw observation
values, event payloads, thresholds, hashes, identifiers, budget values, or
other provenance. The optional internal ``reason`` attribute is for
diagnostics only and names at most the violated rule, never the offending
content. The class-level ``_PUBLIC_MESSAGE`` constant is forwarded to the
domain base, so a subclass instance's public message is always the subclass's
own stable generic message while the caller-supplied ``reason`` is preserved
exactly and never overwritten by it.

There is no I/O, randomness, wall clock, RNG, network, store, adapter, NEXUS,
or LEGION dependency anywhere in this module.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class AdaptivePolicyStateMachineError(KalhasDomainError):
    """A policy-state-machine input or integrity rule was violated.

    Raised when a policy is not an exact runtime-4 ``AdaptivePolicy``, when a
    supplied state snapshot is not exact, is foreign policy, or is internally
    inconsistent, when the current action or per-rule budget catalogue disagrees
    with the policy, or when any input is malformed or subclassed. The public
    message stays generic; the optional ``reason`` (diagnostics only) names the
    violated rule, never the offending values. No partial state or result is
    produced: the machine fails closed and never mutates any input.
    """

    #: The single stable generic public message shared by every instance. It
    #: never leaks identifiers, values, thresholds, hashes, or payloads.
    _PUBLIC_MESSAGE = (
        "Adaptive policy state machine input or integrity verification failed and was rejected"
    )

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        super().__init__(type(self)._PUBLIC_MESSAGE)


__all__ = [
    "AdaptivePolicyStateMachineError",
]
