"""Safe typed integrity error for the campaign outcome-distribution matrix.

The single typed domain error raised by the pure campaign
outcome-distribution matrix builder whenever a supplied source artifact
fails strict contract revalidation, independent identity/content-hash
verification, cross-source consistency, structural verification, or
outcome construction. The public message stays safe and generic: it
never exposes observed values, hashes, field names, validator details,
strategy policy, target values, another tenant's identity, or the
internal reason. The ``reason`` attribute is for internal diagnostics
only.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class CampaignOutcomeDistributionMatrixIntegrityError(KalhasDomainError):
    """A supplied outcome-matrix source artifact failed integrity verification.

    Raised when the evaluation profile, the world-realization matrix, or
    the metric-observation matrix violates its contract, fails identity
    or content-hash verification, disagrees with the other sources, or
    cannot be aggregated into the deterministic outcome matrix. The
    public message is generic and non-leaking; the optional ``reason``
    attribute names only the violated rule for internal diagnostics.
    """

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Campaign {campaign_id!r} failed outcome distribution matrix integrity "
            "verification and was rejected"
        )


__all__ = ["CampaignOutcomeDistributionMatrixIntegrityError"]
