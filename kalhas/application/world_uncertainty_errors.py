"""Typed Phase 24 world-uncertainty domain errors.

Application code raises these instead of leaking generic ``ValueError``
instances. The API layer maps them to the typed error response shape
through the existing safe error boundary; public messages stay generic
and never expose sampled values, distribution parameters, bounds,
rounding policies, hashes, state-field values, metadata, internal
reasons, or validator diagnostics. The internal ``reason`` (for
diagnostics only) names only the violated rule.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class WorldUncertaintyModelNotFoundError(KalhasDomainError):
    """No uncertainty model exists for the tenant/scenario (or it is foreign).

    Unknown and foreign models are indistinguishable: both raise the
    same typed error, so no tenant can learn about another tenant's
    models.
    """

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Uncertainty model for scenario {scenario_id!r} not found")


class WorldUncertaintyModelAlreadyExistsError(KalhasDomainError):
    """A model already exists for the tenant/scenario; it is never overwritten."""

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Uncertainty model for scenario {scenario_id!r} already exists")


class WorldUncertaintyModelDeclarationAfterCompilationError(KalhasDomainError):
    """A model cannot be declared after a world was compiled for the scenario.

    Worlds are immutable and compiled deterministically; a model must be
    declared before the first world compilation so its complete snapshot
    can be embedded.
    """

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(
            f"Uncertainty model for scenario {scenario_id!r} cannot be declared "
            "after world compilation"
        )


class WorldUncertaintyModelValidationError(KalhasDomainError):
    """A declaration semantic rule was violated.

    Base class for every 422 declaration failure; the specific
    subclasses below name the violated rule for diagnostics while the
    public message stays generic.
    """

    def __init__(self, scenario_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(f"Uncertainty model for scenario {scenario_id!r} is invalid")


class WorldUncertaintyUnknownManifestError(WorldUncertaintyModelValidationError):
    """A referenced pack binding manifest does not exist for the scenario."""

    def __init__(self, scenario_id: str, manifest_id: str, reason: str | None = None) -> None:
        self.manifest_id = manifest_id
        super().__init__(
            scenario_id, reason or f"manifest {manifest_id!r} is not bound to the scenario"
        )


class WorldUncertaintyUnknownStateModelError(WorldUncertaintyModelValidationError):
    """A referenced state model does not exist for the scenario/manifest."""

    def __init__(
        self,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        reason: str | None = None,
    ) -> None:
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        super().__init__(
            scenario_id,
            reason or f"state model {state_model_id!r} does not exist for the scenario",
        )


class WorldUncertaintyUnknownStateFieldError(WorldUncertaintyModelValidationError):
    """A referenced state field does not exist in the state model."""

    def __init__(
        self,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        state_field_id: str,
        reason: str | None = None,
    ) -> None:
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"state field {state_field_id!r} does not exist in the state model",
        )


class WorldUncertaintyUnsupportedFieldKindError(WorldUncertaintyModelValidationError):
    """Only integer and number initial-state fields may be targeted."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"state field {state_field_id!r} is not an integer or number field",
        )


class WorldUncertaintyBindingKindMismatchError(WorldUncertaintyModelValidationError):
    """The distribution cannot satisfy the target field kind."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"distribution does not match the kind of state field {state_field_id!r}",
        )


class WorldUncertaintyRoundingPolicyRuleError(WorldUncertaintyModelValidationError):
    """The integer rounding policy rule was violated for one binding."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"rounding policy rule violated for state field {state_field_id!r}",
        )


class WorldUncertaintyBoundRuleError(WorldUncertaintyModelValidationError):
    """A clipping-bound rule was violated for one binding."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"clipping bound rule violated for state field {state_field_id!r}",
        )


class WorldUncertaintyDistributionParameterError(WorldUncertaintyModelValidationError):
    """A distribution parameter violates the effective fixed-point rules.

    Covers effective quantized ordering, vanishing parameters,
    effectively zero standard deviations/sigmas, and the lognormal
    static finite-raw range check.
    """

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"distribution parameter invalid for state field {state_field_id!r}",
        )


class WorldUncertaintyDiscreteValueKindError(WorldUncertaintyModelValidationError):
    """A discrete value kind does not agree with the target field kind."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason or f"discrete value kind mismatch for state field {state_field_id!r}",
        )


class WorldUncertaintyAllowedValuesError(WorldUncertaintyModelValidationError):
    """A statically determinable final value cannot satisfy allowed_values."""

    def __init__(self, scenario_id: str, state_field_id: str, reason: str | None = None) -> None:
        self.state_field_id = state_field_id
        super().__init__(
            scenario_id,
            reason
            or f"final values cannot satisfy allowed_values for state field {state_field_id!r}",
        )


class WorldUncertaintyModelIntegrityError(KalhasDomainError):
    """A stored or embedded model failed integrity verification.

    The record is never repaired, normalized, replaced, or silently
    accepted; any inconsistency raises this typed error. The public
    message stays generic; the internal ``reason`` names only the
    violated rule.
    """

    def __init__(self, tenant_id: str, scenario_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(
            f"Stored uncertainty model for scenario {scenario_id!r} failed "
            "integrity verification and was rejected"
        )


class WorldRealizationIntegrityError(KalhasDomainError):
    """A world realization cannot be derived safely from verified inputs.

    Raised when the verified inputs are inconsistent, incomplete, or
    tampered. The realization is never partially returned, repaired, or
    silently accepted. The public message stays generic; the internal
    ``reason`` names only the violated rule.
    """

    def __init__(self, tenant_id: str, scenario_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(
            f"World realization for scenario {scenario_id!r} failed integrity "
            "verification and was rejected"
        )


class WorldRealizationSamplingError(KalhasDomainError):
    """A deterministic sampling or realization rule failed.

    Raised when a declared model cannot produce a valid finite
    realization for a seed (for example a sampled value that cannot
    satisfy allowed_values, a non-finite raw result, or an exponential
    argument beyond the safe range). Deterministic and reproducible per
    seed: nothing is ever resampled, retried, clamped, or repaired. The
    public message stays generic; the internal ``reason`` names only
    the violated rule.
    """

    def __init__(self, tenant_id: str, scenario_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.reason = reason
        super().__init__(
            f"World realization for scenario {scenario_id!r} could not be derived "
            "from the declared uncertainty model"
        )


class CampaignWorldRealizationMatrixIntegrityError(KalhasDomainError):
    """The campaign world-realization matrix cannot be derived safely.

    Raised when the verified inputs are inconsistent, incomplete,
    tampered, or produce a matrix violating its own contract. The
    matrix is never partially returned, repaired, or silently accepted.
    The public message stays generic; the internal ``reason`` names
    only the violated rule.
    """

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"World realizations for campaign {campaign_id!r} failed integrity "
            "verification and were rejected"
        )
