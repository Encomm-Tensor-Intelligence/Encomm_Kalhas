"""Typed Phase 23 objective-evaluation domain errors.

Application code raises these instead of leaking generic ``ValueError``
instances. The API layer maps them to the typed error response shape
through the existing safe error boundary; public messages stay generic
and never expose raw observations, targets, weights, tolerances,
normalization scales, hashes, scenario contents, metadata, internal
reasons, or validation diagnostics. The internal ``reason`` (for
diagnostics only) names only the violated rule.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class EvaluationProfileNotFoundError(KalhasDomainError):
    """No evaluation profile exists for the tenant/scenario (or it is foreign).

    Unknown and foreign profiles are indistinguishable: both raise the
    same typed error, so no tenant can learn about another tenant's
    profiles.
    """

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Evaluation profile for scenario {scenario_id!r} not found")


class EvaluationProfileAlreadyExistsError(KalhasDomainError):
    """A profile already exists for the tenant/scenario; it is never overwritten."""

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Evaluation profile for scenario {scenario_id!r} already exists")


class EvaluationProfileDeclarationAfterCompilationError(KalhasDomainError):
    """A profile cannot be declared after a world was compiled for the scenario.

    Worlds are immutable and compiled deterministically; a profile must
    be declared before the first world compilation so its complete
    snapshot can be embedded.
    """

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(
            f"Evaluation profile for scenario {scenario_id!r} cannot be declared "
            "after world compilation"
        )


class EvaluationProfileObjectiveNotFoundError(KalhasDomainError):
    """A referenced objective does not exist exactly once in the scenario."""

    def __init__(self, scenario_id: str, objective_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.objective_id = objective_id
        self.reason = reason
        super().__init__(f"Objective {objective_id!r} cannot be bound for scenario {scenario_id!r}")


class EvaluationProfileMetricNotFoundError(KalhasDomainError):
    """A referenced metric does not exist exactly once in the scenario."""

    def __init__(self, scenario_id: str, metric_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.metric_id = metric_id
        self.reason = reason
        super().__init__(f"Metric {metric_id!r} cannot be bound for scenario {scenario_id!r}")


class EvaluationProfileIncompleteCoverageError(KalhasDomainError):
    """The profile does not cover every scenario objective exactly once."""

    def __init__(self, scenario_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(
            f"Evaluation profile for scenario {scenario_id!r} does not cover "
            "every scenario objective exactly once"
        )


class EvaluationProfileReachTargetRequiredError(KalhasDomainError):
    """A reach objective without an authoritative target cannot be bound."""

    def __init__(self, scenario_id: str, objective_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.objective_id = objective_id
        self.reason = reason
        super().__init__(
            f"Reach objective {objective_id!r} requires an authoritative target "
            f"for scenario {scenario_id!r}"
        )


class EvaluationProfileToleranceRuleError(KalhasDomainError):
    """A reach tolerance rule was violated for one binding."""

    def __init__(self, scenario_id: str, objective_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.objective_id = objective_id
        self.reason = reason
        super().__init__(
            f"Reach tolerance rule violated for objective {objective_id!r} "
            f"of scenario {scenario_id!r}"
        )


class EvaluationProfileInvalidScaleError(KalhasDomainError):
    """The normalization scale is not finite and strictly positive."""

    def __init__(self, scenario_id: str, objective_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.objective_id = objective_id
        self.reason = reason
        super().__init__(
            f"Normalization scale invalid for objective {objective_id!r} "
            f"of scenario {scenario_id!r}"
        )


class EvaluationProfileValidationError(KalhasDomainError):
    """A remaining declaration semantic rule was violated.

    Used for declaration-time semantic failures that are not covered by
    the more specific classes - for example a non-finite authoritative
    target stored on the scenario objective, which cannot be snapshotted
    into a profile.
    """

    def __init__(self, scenario_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(f"Evaluation profile for scenario {scenario_id!r} is invalid")


class EvaluationProfileIntegrityError(KalhasDomainError):
    """A stored or embedded profile failed integrity verification.

    The stored/embedded profile is never repaired, normalized,
    replaced, or silently accepted; any inconsistency raises this typed
    error. The public message stays generic; the internal ``reason``
    names only the violated rule.
    """

    def __init__(self, tenant_id: str, scenario_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(
            f"Stored evaluation profile for scenario {scenario_id!r} failed "
            "integrity verification and was rejected"
        )


class CampaignObjectiveEvaluationMatrixIntegrityError(KalhasDomainError):
    """The campaign objective-evaluation matrix cannot be derived safely.

    Raised when the verified inputs are inconsistent, incomplete,
    tampered, or produce non-finite derived values. The matrix is never
    partially returned, clamped, rounded, repaired, or silently
    accepted. The public message stays generic; the internal ``reason``
    names only the violated rule.
    """

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Objective evaluations for campaign {campaign_id!r} failed integrity "
            "verification and were rejected"
        )
