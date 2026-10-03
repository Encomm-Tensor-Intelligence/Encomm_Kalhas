"""Typed dispatch error for the Phase 29 pure mechanism dispatcher (H29-S03).

Exactly one safe typed application error for the domain-mechanism dispatch
seam. It follows the established KALHAS typed-error style: the public
message is a single generic sentence that never exposes payload, state,
action, configuration, or metadata values, hashes, another tenant's
identity, pack implementation internals, validator diagnostics, or the
exception text of a supplied pack. The optional ``request_id`` and the
bounded internal ``reason`` code exist for diagnostics only and are never
rendered into the public message.

This module adds no public contract, no schema, and no registry item, and
it must not be re-exported through ``kalhas.application.__init__``.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError

__all__ = ["DomainMechanismDispatchError"]


class DomainMechanismDispatchError(KalhasDomainError):
    """A domain-mechanism step dispatch failed verification and was rejected.

    Raised for every fail-closed dispatch outcome: a non-conforming pack
    surface, a record failing exact type identity or detached strict
    revalidation, any pre-dispatch authority/hash/identity disagreement,
    a pack ``step`` invocation that raised, or any post-dispatch result
    verification failure. Exactly one error is raised per rejected
    dispatch; no partial result is ever returned and no KALHAS-side
    state changes.

    The public message stays generic and fixed. ``request_id`` (when the
    request identity was safely verifiable before the failure) and
    ``reason`` (one bounded internal code) are diagnostic attributes
    only; they carry no payload values, hashes, tenant data, pack
    internals, or the underlying pack exception text.
    """

    def __init__(self, reason: str, *, request_id: str | None = None) -> None:
        self.reason = reason
        self.request_id = request_id
        super().__init__(
            "Domain mechanism step dispatch failed verification and was rejected; "
            "no result was produced and no authority state changed"
        )
