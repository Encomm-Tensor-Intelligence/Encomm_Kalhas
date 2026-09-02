"""Typed domain errors for the external-observation-input surface (H28-S06B1).

These errors cover the immutable :class:`ExternalObservationInputBundle`
authority boundary - authoritative construction from one accepted bundle of
untrusted value drafts, one-immutable-bundle-per-(tenant, campaign, scenario
seed) persistence, deterministic identity/content-hash verification, and
emergency-safe retrieve behavior. The bundle is strategy-independent and
bound to the campaign, world, and scenario seed (ADR-004 D28-04), so there
is at most one bundle per ``(tenant_id, campaign_id, scenario_seed_id)``
locality and no update, delete, replace, or repair surface. The module
carries no schema, registry, event, execution, adapter, or runtime surface
of its own.

The four error classes mirror the established immutable-authority boundaries
(declaration, adaptive-policy binding): a ``*ValidationError`` for caller- or
authority-owned preconditions rejected before the single write, an
``AlreadyExistsError`` for a duplicate no-overwrite write, a ``NotFoundError``
for unknown/foreign reads, and an ``IntegrityError`` for a stored record that
fails independent verification and is never repaired.

Every public message is safe and generic: it never exposes tenant, campaign,
scenario, world, seed, declaration, observation, channel, or value
identifiers, hashes, steps, values, units, metadata, internal verification
reasons, or validator diagnostics. The validation and integrity error classes
retain an optional internal ``reason`` attribute (for diagnostics only) that
is never part of the public message and never crosses the API boundary. No
arbitrary exception is ever wrapped into a public message, so raw
``ValidationError``, ``TypeError``, ``AttributeError``, ``KeyError``,
``ValueError``, or assertion failures never escape the public surface.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class ExternalObservationInputValidationError(KalhasDomainError):
    """The external-observation-input authoring inputs or authority precondition are invalid.

    Raised when a caller-owned authoring input violates a strict rule checked
    before any stored authority is trusted - a wrong-type, subclassed, or
    validator-bypassed value/bundle draft, a malformed value scalar or nested
    entry (bool-as-int, NaN/Infinity, a wrong-typed or negative step, a
    duplicate or reordered coordinate), a timezone-naive timestamp, an
    unknown or foreign campaign, world, scenario seed, policy, or declaration,
    a state-field declaration, a policy-unused observation, a value that does
    not exactly match the declared kind, an unscheduled source step, or a
    campaign whose status is not exactly COMPILED. The public message stays
    generic; the optional internal ``reason`` names only the violated class
    of rule, never identifiers, hashes, steps, channels, values, or units.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("External observation input authoring is invalid")


class ExternalObservationInputAlreadyExistsError(KalhasDomainError):
    """An immutable external observation input bundle already exists for this locality.

    Bundles are immutable and at most one bundle may exist per
    ``(tenant_id, campaign_id, scenario_seed_id)``: a duplicate authoring is
    rejected and never overwrites the original. The public message stays
    generic.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("External observation input bundle already exists for this locality")


class ExternalObservationInputNotFoundError(KalhasDomainError):
    """An external observation input bundle is absent or belongs to another tenant.

    Unknown and foreign bundles are indistinguishable: both raise the same
    error with the same generic public message, so no tenant can learn about
    another tenant's bundles.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("External observation input bundle not found")


class ExternalObservationInputIntegrityError(KalhasDomainError):
    """A stored external observation input bundle failed independent verification.

    Raised when a stored bundle fails its strict contract revalidation, its
    independent ownership/identifier/content-hash verification, or a
    cross-authority check against the stored campaign/scenario/world/status,
    the stored adaptive policy, the stored scenario seed, or the stored
    observation declarations - including a self-consistently rehashed altered
    seed, world, declaration, channel, kind, or unit provenance. The public
    message stays safe and generic - internal verification reasons, raw
    hashes, identities, values, and provenance are never exposed - and stored
    state is never repaired, normalized, replaced, or silently accepted.
    Corruption is rejected, never repaired.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            "Stored external observation input bundle failed integrity "
            "verification and was rejected"
        )


__all__ = [
    "ExternalObservationInputAlreadyExistsError",
    "ExternalObservationInputIntegrityError",
    "ExternalObservationInputNotFoundError",
    "ExternalObservationInputValidationError",
]
