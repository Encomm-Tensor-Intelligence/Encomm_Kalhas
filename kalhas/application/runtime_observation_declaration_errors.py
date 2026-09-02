"""Typed domain errors for the runtime-observation declaration surface (KALHAS).

These errors cover the stored :class:`RuntimeObservationDeclaration`
authority boundary - authoritative construction, deterministic verification,
no-overwrite immutable persistence, and safe retrieve/list behavior. The
module carries no schema, register, event, or runtime surface of its own.

Every public message is safe and generic: it never exposes tenant, scenario,
world, or observation identifiers, hashes, field identities, units, noise
declarations, metadata, internal verification reasons, or validator
diagnostics. The validation and integrity error classes retain an optional
internal ``reason`` attribute (for diagnostics only) that is never part of the
public message and never crosses the API boundary. No arbitrary exception is
ever wrapped into a public message.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class RuntimeObservationDeclarationValidationError(KalhasDomainError):
    """The caller-owned declaration draft is invalid.

    Raised when a draft violates a declaration rule that is checked before any
    stored authority is trusted: an unsupported state-field value kind, an
    unknown state field, non-canonical provenance, an external-channel noise
    conflict, a mismatched value kind, non-finite metadata, a timezone-naive
    timestamp, or a foreign/unknown scenario/world/manifest/model authority.
    The public message stays generic; the optional internal ``reason`` names
    only the violated class of rule, never identifiers, hashes, or values.
    """

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        world_version_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.world_version_id = world_version_id
        self.reason = reason
        super().__init__("Runtime observation declaration authoring is invalid")


class RuntimeObservationDeclarationNotFoundError(KalhasDomainError):
    """A runtime observation declaration is absent or belongs to another tenant.

    Unknown and foreign declarations are indistinguishable: both raise the
    same error with the same generic public message, so no tenant can learn
    about another tenant's declarations.
    """

    def __init__(
        self, tenant_id: str, scenario_id: str, world_version_id: str, observation_id: str
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.world_version_id = world_version_id
        self.observation_id = observation_id
        super().__init__("Runtime observation declaration not found")


class RuntimeObservationDeclarationAlreadyExistsError(KalhasDomainError):
    """A runtime observation declaration already exists for the same locality.

    Declarations are immutable and at most one declaration may exist per
    tenant/scenario/world/observation locality: a duplicate authoring is
    rejected and never overwrites the original. The public message stays
    generic.
    """

    def __init__(self, tenant_id: str, scenario_id: str, world_version_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.world_version_id = world_version_id
        super().__init__("Runtime observation declaration already exists for this locality")


class RuntimeObservationDeclarationIntegrityError(KalhasDomainError):
    """A stored runtime observation declaration failed independent verification.

    Raised when a stored declaration fails its strict contract revalidation or
    its independent ownership/identifier/content-hash verification, or when
    the recorded source authority (scenario, world, manifest, state model) is
    missing, inconsistent, or tampered. The public message stays safe and
    generic - internal verification reasons, raw hashes, identities, and
    provenance are never exposed - and stored state is never repaired,
    normalized, replaced, or silently accepted.
    """

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        world_version_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.world_version_id = world_version_id
        self.reason = reason
        super().__init__(
            "Stored runtime observation declaration failed integrity verification and was rejected"
        )


__all__ = [
    "RuntimeObservationDeclarationAlreadyExistsError",
    "RuntimeObservationDeclarationIntegrityError",
    "RuntimeObservationDeclarationNotFoundError",
    "RuntimeObservationDeclarationValidationError",
]
