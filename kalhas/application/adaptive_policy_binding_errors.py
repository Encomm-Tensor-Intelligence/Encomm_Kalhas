"""Typed domain errors for the adaptive-policy binding and storage surface (H28-S05).

These errors cover the immutable :class:`AdaptivePolicy` authority boundary -
authoritative construction from a strict validated draft plus a caller-owned
binding request, one-immutable-policy-per-campaign persistence, deterministic
identity/content-hash verification, and emergency-safe retrieve behavior. A
policy change requires a new immutable identity and a new campaign/run
authority (ADR-004 D28-04), so there is exactly one policy per
``(tenant_id, campaign_id)`` and no update, delete, replace, or repair surface.
The module carries no schema, registry, event, execution, adapter, or runtime
surface of its own.

The four error classes mirror the established immutable-authority boundaries
(declaration, campaign-decision policy): a ``*ValidationError`` for caller- or
authority-owned preconditions rejected before the single write, an
``AlreadyExistsError`` for a duplicate no-overwrite write, a ``NotFoundError``
for unknown/foreign reads, and an ``IntegrityError`` for a stored record that
fails independent verification and is never repaired.

Every public message is safe and generic: it never exposes tenant, campaign,
scenario, world, policy, action, strategy, observation, or declaration
identifiers, hashes, thresholds, budgets, metadata, internal verification
reasons, or validator diagnostics. The validation and integrity error classes
retain an optional internal ``reason`` attribute (for diagnostics only) that
is never part of the public message and never crosses the API boundary. No
arbitrary exception is ever wrapped into a public message, so raw
``ValidationError``, ``TypeError``, ``AttributeError``, ``KeyError``,
``ValueError``, or assertion failures never escape the public surface.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class AdaptivePolicyBindingValidationError(KalhasDomainError):
    """The adaptive-policy binding inputs or authority precondition are invalid.

    Raised when a caller-owned authoring input violates a strict rule checked
    before any stored authority is trusted - a wrong-type, subclassed, or
    validator-bypassed draft or binding request, a malformed policy scalar or
    nested rule/condition, a non-finite metadata value, a malformed timestamp,
    an action-to-strategy mapping that is missing/extra/duplicate/reordered or
    non-injective, an unknown or foreign strategy, a missing/duplicate/extra
    trajectory plan, incomplete or unequal state-model coverage, a missing or
    foreign observation declaration, an observation kind/unit/missing-behavior
    mismatch, an unused or absent observation catalog, or a campaign whose
    status is not exactly COMPILED. The public message stays generic; the
    optional internal ``reason`` names only the violated class of rule, never
    identifiers, hashes, thresholds, or values.
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
        super().__init__("Adaptive policy binding is invalid")


class AdaptivePolicyAlreadyExistsError(KalhasDomainError):
    """An immutable adaptive policy already exists for this campaign.

    Policies are immutable and at most one policy may exist per
    ``(tenant_id, campaign_id)``: a duplicate binding is rejected and never
    overwrites the original. A changed policy requires a new immutable policy
    identity and a new campaign/run authority. The public message stays
    generic.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("Adaptive policy already exists for this campaign")


class AdaptivePolicyNotFoundError(KalhasDomainError):
    """An adaptive policy is absent or belongs to another tenant/campaign.

    Unknown and foreign policies are indistinguishable: both raise the same
    error with the same generic public message, so no tenant can learn about
    another tenant's policies.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("Adaptive policy not found")


class AdaptivePolicyIntegrityError(KalhasDomainError):
    """A stored adaptive policy failed independent verification.

    Raised when a stored policy fails its strict contract revalidation, its
    independent ownership/identifier/content-hash verification, or a
    cross-authority check against the stored campaign/scenario/world/status,
    the stored observation declarations, or the stored strategies and
    trajectory plans - including a self-consistently rehashed altered
    authority. The public message stays safe and generic - internal
    verification reasons, raw hashes, identities, and provenance are never
    exposed - and stored state is never repaired, normalized, replaced, or
    silently accepted. Corruption is rejected, never repaired.
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
        super().__init__("Stored adaptive policy failed integrity verification and was rejected")


__all__ = [
    "AdaptivePolicyAlreadyExistsError",
    "AdaptivePolicyBindingValidationError",
    "AdaptivePolicyIntegrityError",
    "AdaptivePolicyNotFoundError",
]
