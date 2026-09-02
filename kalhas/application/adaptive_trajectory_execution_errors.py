"""Typed safe errors for the adaptive-run trajectory execution surface (H28-S06C1).

These errors cover the deterministic identity, integrity-verification, and
immutable in-memory persistence boundary for the runtime-4
:class:`AdaptiveRunTrajectoryExecution` aggregate. The store performs no
execution, no policy-state advancement, no observation derivation, no
orchestration, and no replay, so there is no activity surface here at all:
every failure is atomic and leaves the repository exactly unchanged.

Every public message is safe and generic: it never exposes tenant, run,
campaign, scenario, world, seed, realization, policy, action, rule, plan,
declaration, state-model, bundle, or observation identifiers, hashes,
steps, values, timestamps, counts, metadata, internal verification
reasons, or validator diagnostics. The validation and integrity error
classes retain an optional internal ``reason`` attribute (for local
diagnostics only) that is never part of the public message and never
crosses the API boundary. No arbitrary exception is ever wrapped into a
public message, so raw ``ValidationError``, ``TypeError``,
``AttributeError``, ``KeyError``, ``ValueError``, or assertion failures
never escape the public surface.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class AdaptiveRunTrajectoryExecutionValidationError(KalhasDomainError):
    """A caller-owned adaptive execution store input is invalid.

    Raised when a caller-owned input violates a strict rule checked
    before any stored authority is trusted - a wrong-type, subclassed,
    or validator-bypassed execution record, or a key-ownership mismatch
    between the contextual store arguments and the record. The public
    message stays generic; the optional internal ``reason`` names only
    the violated class of rule, never identifiers, hashes, steps, or
    values.
    """

    def __init__(
        self,
        tenant_id: str,
        run_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.reason = reason
        super().__init__("Adaptive run trajectory execution input is invalid")


class AdaptiveRunTrajectoryExecutionAlreadyExistsError(KalhasDomainError):
    """An adaptive execution already exists for the run.

    Exactly one runtime-4 adaptive execution may exist per
    ``(tenant_id, run_id)``: a second write - even an identical
    artifact - raises this error and never overwrites the original.
    The public message stays generic.
    """

    def __init__(
        self,
        tenant_id: str,
        run_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            "Adaptive run trajectory execution already exists for this run and is immutable"
        )


class AdaptiveRunTrajectoryExecutionNotFoundError(KalhasDomainError):
    """An adaptive execution is absent or belongs to another tenant.

    Unknown and foreign executions are indistinguishable: both raise
    the same typed error, so no tenant can learn about another tenant's
    executions. The public message stays generic.
    """

    def __init__(
        self,
        tenant_id: str,
        run_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.reason = reason
        super().__init__("Adaptive run trajectory execution not found")


class AdaptiveRunTrajectoryExecutionIntegrityError(KalhasDomainError):
    """A supplied record or stored authority failed independent verification.

    Raised when the supplied execution fails strict contract
    revalidation, deterministic-identity verification, or the pure
    cross-authority integrity verifier; when a required stored authority
    (campaign, status, run plan, world, seed, realization, policy,
    plan, declaration, or external input bundle) is missing, corrupt, or
    disagrees with the record; or when privately stored record bytes are
    corrupt on read. Corruption is rejected, never repaired, and the
    public message stays safe and generic.
    """

    def __init__(
        self,
        tenant_id: str,
        run_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.reason = reason
        super().__init__("Adaptive run trajectory execution failed integrity verification")


__all__ = [
    "AdaptiveRunTrajectoryExecutionAlreadyExistsError",
    "AdaptiveRunTrajectoryExecutionIntegrityError",
    "AdaptiveRunTrajectoryExecutionNotFoundError",
    "AdaptiveRunTrajectoryExecutionValidationError",
]
