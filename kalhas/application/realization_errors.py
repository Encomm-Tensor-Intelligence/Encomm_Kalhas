"""Focused typed errors for the Phase 25 realization-aware runtime 3.0.0.

Every failure of runtime-3 preparation, execution, observation
extraction, replay, and matrix assembly is a safe typed error here.
Unknown and foreign resources are indistinguishable (same typed
not-found error), stored artifacts that fail strict verification are
never repaired or silently accepted (typed integrity errors), and
conflicting immutable writes are rejected (typed conflict errors).
Public messages stay generic and never expose state values, hashes,
guards, targets, or validation details.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class RealizationRunTrajectoryExecutionNotFoundError(KalhasDomainError):
    """A runtime-3 trajectory execution artifact is absent or foreign."""

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Realization trajectory execution for run {run_id!r} not found "
            f"for tenant {tenant_id!r}"
        )


class RealizationRunTrajectoryExecutionAlreadyExistsError(KalhasDomainError):
    """A runtime-3 trajectory execution artifact already exists for the run."""

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Realization trajectory execution for run {run_id!r} already exists "
            f"for tenant {tenant_id!r} and is immutable; it will not be replaced"
        )


class RealizationRunTrajectoryExecutionIntegrityError(KalhasDomainError):
    """A runtime-3 trajectory execution record is inconsistent or tampered."""

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"Realization trajectory execution for run {run_id!r} failed integrity "
            "verification and was rejected"
        )


class RealizationRunTrajectoryReplayManifestNotFoundError(KalhasDomainError):
    """A runtime-3 trajectory replay manifest is absent or foreign."""

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Realization trajectory replay manifest for run {run_id!r} not found "
            f"for tenant {tenant_id!r}"
        )


class RealizationRunTrajectoryReplayManifestConflictError(KalhasDomainError):
    """A stored runtime-3 replay manifest conflicts with a new record.

    Raised when a different runtime-3 replay manifest is already
    recorded for the run, when the generic replay-manifest probe finds a
    conflicting record, or when a manifest that violates its contract is
    offered for storage. Replay manifests are immutable: a conflicting
    write is rejected and never overwrites the stored record.
    """

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"A realization replay manifest for run {run_id!r} conflicts with an "
            "existing immutable record and was rejected"
        )


class RealizationReplayManifestConflictError(KalhasDomainError):
    """The generic replay-manifest probe found a conflicting or corrupt record.

    Runtime-3 replay writes the existing generic ``ReplayManifest``
    together with the focused runtime-3 manifest. Before any write, both
    collections are probed: an existing manifest must be strictly valid
    and byte-identical to the expected manifest. A malformed, corrupted,
    or different generic manifest blocks replay and is never overwritten
    or repaired.
    """

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"The stored replay manifest for run {run_id!r} conflicts with the "
            "regenerated manifest and was rejected"
        )


class RealizationRunMetricObservationNotFoundError(KalhasDomainError):
    """A runtime-3 metric-observation set is absent or foreign."""

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Realization metric observations for run {run_id!r} not found for tenant {tenant_id!r}"
        )


class RealizationRunMetricObservationAlreadyExistsError(KalhasDomainError):
    """A runtime-3 metric-observation set already exists for the run.

    Extraction is explicit and immutable: any second write is rejected,
    even when the artifact would be byte-identical, so extraction can
    never be replayed or repaired by overwrite.
    """

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Realization metric observations for run {run_id!r} already exist "
            f"for tenant {tenant_id!r} and are immutable; they will not be replaced"
        )


class RealizationRunMetricObservationIntegrityError(KalhasDomainError):
    """A stored runtime-3 metric-observation set is inconsistent or tampered."""

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"Realization metric observations for run {run_id!r} failed integrity "
            "verification and were rejected"
        )


class RealizationCampaignTrajectoryMatrixIntegrityError(KalhasDomainError):
    """A runtime-3 campaign trajectory matrix cannot be verified."""

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Realization trajectory matrix for campaign {campaign_id!r} failed "
            "integrity verification and was rejected"
        )


class RealizationCampaignMetricObservationMatrixIntegrityError(KalhasDomainError):
    """A runtime-3 campaign metric-observation matrix cannot be verified."""

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Realization metric-observation matrix for campaign {campaign_id!r} "
            "failed integrity verification and was rejected"
        )


class RealizationCampaignMetricStatisticsIntegrityError(KalhasDomainError):
    """A runtime-3 campaign metric-statistics matrix cannot be verified."""

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Realization metric-statistics matrix for campaign {campaign_id!r} "
            "failed integrity verification and was rejected"
        )
