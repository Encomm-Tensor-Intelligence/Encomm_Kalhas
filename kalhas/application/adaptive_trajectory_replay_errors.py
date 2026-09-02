"""Typed safe errors for the adaptive-run trajectory replay manifest surface (H28-S07B1A).

These errors cover the deterministic identity, pure integrity-verification,
and future immutable persistence boundary for the runtime-4
:class:`AdaptiveRunTrajectoryReplayManifest` authority. The verifier
performs no replay, no store access, no write, no RNG, no clock read, and
no provider call, so every failure is atomic and leaves the repository
exactly unchanged.

Every public message is safe and generic: it never exposes tenant, run,
campaign, world, seed, realization, policy, execution, bundle, or
declaration identifiers, hashes, timestamps, counts, metadata, internal
verification reasons, or validator diagnostics. The validation and
integrity error classes retain an optional internal ``reason`` attribute
(for local diagnostics only) that is never part of the public message and
never crosses the API boundary. No arbitrary exception is ever wrapped
into a public message, so raw ``ValidationError``, ``TypeError``,
``AttributeError``, ``KeyError``, ``ValueError``, or assertion failures
never escape the public surface.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class AdaptiveRunTrajectoryReplayManifestValidationError(KalhasDomainError):
    """A caller-owned adaptive replay manifest input is invalid.

    Raised when a caller-owned input violates a strict rule checked
    before any stored authority is trusted - a wrong-type, subclassed,
    or validator-bypassed manifest record, or a key-ownership mismatch
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
        super().__init__("Adaptive run trajectory replay manifest input is invalid")


class AdaptiveRunTrajectoryReplayManifestAlreadyExistsError(KalhasDomainError):
    """An adaptive replay manifest already exists for the run.

    Exactly one runtime-4 replay manifest may exist per
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
            "Adaptive run trajectory replay manifest already exists for this run and is immutable"
        )


class AdaptiveRunTrajectoryReplayManifestNotFoundError(KalhasDomainError):
    """An adaptive replay manifest is absent or belongs to another tenant.

    Unknown and foreign manifests are indistinguishable: both raise the
    same typed error, so no tenant can learn about another tenant's
    replay manifests. The public message stays generic.
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
        super().__init__("Adaptive run trajectory replay manifest not found")


class AdaptiveRunTrajectoryReplayManifestIntegrityError(KalhasDomainError):
    """A supplied manifest or stored authority failed independent verification.

    Raised when the supplied replay manifest fails strict contract
    revalidation, deterministic-identity verification, or the pure
    full-record integrity verifier (against the verified runtime-4
    execution authority and the recorded replay timestamp authority);
    or when a required stored authority is missing, corrupt, or
    disagrees with the manifest. Corruption is rejected, never
    repaired, and the public message stays safe and generic.
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
        super().__init__("Adaptive run trajectory replay manifest failed integrity verification")


__all__ = [
    "AdaptiveRunTrajectoryReplayManifestAlreadyExistsError",
    "AdaptiveRunTrajectoryReplayManifestIntegrityError",
    "AdaptiveRunTrajectoryReplayManifestNotFoundError",
    "AdaptiveRunTrajectoryReplayManifestValidationError",
]
