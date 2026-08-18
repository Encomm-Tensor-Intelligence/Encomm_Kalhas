"""Typed domain errors for the campaign decision surfaces (KALHAS).

These errors cover the stored ``CampaignDecisionPolicy`` declaration
boundary - authoritative construction, deterministic verification,
one-policy-per-campaign persistence, and safe API error mapping - and
the two derived-artifact integrity errors of the read-only query
layer: ``CampaignDecisionComparisonIntegrityError`` and
``CampaignDecisionBriefIntegrityError``, raised when the accepted pure
comparison or brief builder rejects verified inputs (or when the
campaign's exact scenario is missing or inconsistent at the brief
boundary). The module carries no Pareto, regret, minimax,
registration, or schema surface of its own.

Every public message is safe and generic: it never exposes tenant or
campaign identifiers, scenario/world/profile identities, hashes,
thresholds, metadata, internal verification reasons, or validator
diagnostics. The validation and integrity error classes retain an
optional internal ``reason`` attribute (for diagnostics only) that is
never part of the public message and never crosses the API boundary.
No arbitrary exception is ever wrapped into a public message.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class CampaignDecisionPolicyNotFoundError(KalhasDomainError):
    """A campaign decision policy is absent or belongs to another tenant.

    Unknown and foreign policies are indistinguishable: both raise the
    same error with the same generic public message, so no tenant can
    learn about another tenant's policies.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("Campaign decision policy not found")


class CampaignDecisionPolicyAlreadyExistsError(KalhasDomainError):
    """A campaign decision policy already exists for the campaign.

    Policies are immutable: a duplicate declaration is rejected and
    never overwrites the original. The public message stays generic.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__("Campaign decision policy already exists for this campaign")


class CampaignDecisionPolicyValidationError(KalhasDomainError):
    """The declared campaign decision policy is invalid.

    Raised when the caller-owned declaration draft violates a policy
    rule: the mode XOR, the exact numeric kinds and bands, the sample
    count, the tolerance, the hard-gate flag kind, metadata finiteness,
    or the exact target coverage (missing, duplicate, unknown,
    additional, reordered, or optimization-only requirements). The
    public message is generic; the optional internal ``reason`` names
    only the violated rule, never identifiers, hashes, thresholds, or
    values.
    """

    def __init__(self, tenant_id: str, campaign_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("Campaign decision policy declaration is invalid")


class CampaignDecisionPolicyIntegrityError(KalhasDomainError):
    """A stored campaign decision policy failed independent verification.

    Raised when a stored policy fails its strict contract revalidation
    or its independent ownership/identifier/content-hash verification,
    or when the campaign's recorded source context (world, scenario,
    evaluation profile, bindings) is missing, inconsistent, or
    tampered. The public message stays safe and generic - internal
    verification reasons, raw hashes, identities, and values are never
    exposed - and stored state is never repaired, normalized,
    replaced, or silently accepted.
    """

    def __init__(self, tenant_id: str, campaign_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            "Stored campaign decision policy failed integrity verification and was rejected"
        )


class CampaignDecisionComparisonIntegrityError(KalhasDomainError):
    """A derived campaign strategy comparison failed integrity assembly.

    Raised by the read-only query layer when the accepted pure
    comparison builder rejects the already-verified policy and outcome
    matrix - a structural ``ValueError`` or a numeric representability
    ``OverflowError`` of the builder - at the derived-artifact trust
    boundary. The public message stays safe and generic; the optional
    internal ``reason`` is for diagnostics only and never appears in
    the public message. No partial comparison is ever returned, no
    upstream typed error is converted, and nothing is written or
    repaired.
    """

    def __init__(self, tenant_id: str, campaign_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            "Campaign strategy comparison derivation failed integrity verification and was rejected"
        )


class CampaignDecisionBriefIntegrityError(KalhasDomainError):
    """A derived campaign decision brief failed integrity assembly.

    Raised by the read-only query layer when the campaign's exact
    scenario is missing or inconsistent at the derived-artifact
    boundary, or when the accepted pure brief builder rejects the
    already-verified scenario, policy, outcome matrix, and comparison -
    a structural ``ValueError`` or a numeric representability
    ``OverflowError`` of the builder. The public message stays safe and
    generic; the optional internal ``reason`` is for diagnostics only
    and never appears in the public message. No partial brief is ever
    returned, no upstream typed error is converted, and nothing is
    written or repaired.
    """

    def __init__(self, tenant_id: str, campaign_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            "Campaign decision brief derivation failed integrity verification and was rejected"
        )


__all__ = [
    "CampaignDecisionPolicyNotFoundError",
    "CampaignDecisionPolicyAlreadyExistsError",
    "CampaignDecisionPolicyValidationError",
    "CampaignDecisionPolicyIntegrityError",
    "CampaignDecisionComparisonIntegrityError",
    "CampaignDecisionBriefIntegrityError",
]
