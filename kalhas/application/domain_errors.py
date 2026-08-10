"""Typed domain errors for the KALHAS application layer.

Application code raises these instead of leaking generic ``ValueError``
instances. The API layer maps them to the typed error response shape.
"""

from __future__ import annotations

from kalhas.contracts.v1.scenario import ValidationReport


class KalhasDomainError(Exception):
    """Base class for all typed KALHAS domain errors."""


class ScenarioNotFoundError(KalhasDomainError):
    """A scenario does not exist for the given tenant."""

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Scenario {scenario_id!r} not found for tenant {tenant_id!r}")


class ScenarioAlreadyExistsError(KalhasDomainError):
    """A scenario with the same identifier already exists for the tenant."""

    def __init__(self, tenant_id: str, scenario_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        super().__init__(f"Scenario {scenario_id!r} already exists for tenant {tenant_id!r}")


class WorldNotFoundError(KalhasDomainError):
    """A compiled world does not exist for the given tenant."""

    def __init__(self, tenant_id: str, world_version_id: str) -> None:
        self.tenant_id = tenant_id
        self.world_version_id = world_version_id
        super().__init__(f"World {world_version_id!r} not found for tenant {tenant_id!r}")


class InvalidScenarioError(KalhasDomainError):
    """A scenario is semantically invalid and cannot be compiled.

    Carries the full validation report.
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(f"Scenario {report.subject_id!r} is semantically invalid")


class WorldScenarioMismatchError(KalhasDomainError):
    """A world was not compiled from the scenario it is being used with."""

    def __init__(self, world_version_id: str, scenario_id: str) -> None:
        self.world_version_id = world_version_id
        self.scenario_id = scenario_id
        super().__init__(
            f"World {world_version_id!r} was not compiled from scenario {scenario_id!r}"
        )


class WorldSnapshotIntegrityError(KalhasDomainError):
    """A stored world does not exactly represent the compiler's deterministic output.

    Raised when a stored ``WorldVersion`` and its ``WorldManifest`` fail
    compiled-world integrity verification: wrong identifiers, tenant or
    provenance mismatches, malformed or non-canonical embedded content,
    or a recompiled world/manifest that differs from the stored records.
    The public message stays generic; the internal ``reason`` (for
    diagnostics only) names only the violated rule, never world contents,
    state values, metadata, or raw hashes. The stored world is never
    repaired, normalized, replaced, or silently accepted.
    """

    def __init__(self, world_version_id: str, reason: str | None = None) -> None:
        self.world_version_id = world_version_id
        self.reason = reason
        super().__init__(
            f"Stored world {world_version_id!r} failed integrity verification and was rejected"
        )


class CampaignNotFoundError(KalhasDomainError):
    """A campaign does not exist for the given tenant."""

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__(f"Campaign {campaign_id!r} not found for tenant {tenant_id!r}")


class CampaignAlreadyExistsError(KalhasDomainError):
    """A campaign with the same identifier already exists for the tenant."""

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__(f"Campaign {campaign_id!r} already exists for tenant {tenant_id!r}")


class CampaignPreparationError(KalhasDomainError):
    """A campaign preparation invariant was violated."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RunNotFoundError(KalhasDomainError):
    """A run (status, events, or replay) is absent or belongs to another tenant."""

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(f"Run {run_id!r} not found for tenant {tenant_id!r}")


class CampaignNotRunningError(KalhasDomainError):
    """A campaign may be executed only while RUNNING."""

    def __init__(self, campaign_id: str, current_state: str) -> None:
        self.campaign_id = campaign_id
        self.current_state = current_state
        super().__init__(
            f"Campaign {campaign_id!r} is {current_state!r}; execution requires 'running'"
        )


class RunNotPlannedError(KalhasDomainError):
    """A run may be executed only while PLANNED."""

    def __init__(self, run_id: str, current_state: str) -> None:
        self.run_id = run_id
        self.current_state = current_state
        super().__init__(f"Run {run_id!r} is {current_state!r}; execution requires 'planned'")


class RunNotCompleteError(KalhasDomainError):
    """Replay requires a COMPLETE run."""

    def __init__(self, run_id: str, current_state: str) -> None:
        self.run_id = run_id
        self.current_state = current_state
        super().__init__(f"Run {run_id!r} is {current_state!r}; replay requires 'complete'")


class ReplayHashMismatchError(KalhasDomainError):
    """A regenerated event stream does not match the recorded expected hash."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(
            f"Replay of run {run_id!r} regenerated an event stream whose hash does not "
            "match the recorded expected event hash"
        )


class MalformedWorldError(KalhasDomainError):
    """A recorded world lacks the structural fields required for execution."""

    def __init__(self, world_version_id: str) -> None:
        self.world_version_id = world_version_id
        super().__init__(
            f"World {world_version_id!r} is missing structural execution inputs "
            "(scenario time horizon)"
        )


class RunInputIntegrityError(KalhasDomainError):
    """A run's recorded inputs are missing, inconsistent, or tampered.

    The public message stays safe and generic: it never exposes a foreign
    tenant's data, raw hash values, or hidden internals. The optional
    ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"Run {run_id!r} input verification failed: recorded inputs are "
            "inconsistent or tampered"
        )


class DomainPackNotFoundError(KalhasDomainError):
    """A domain pack manifest does not exist for the given tenant."""

    def __init__(self, tenant_id: str, manifest_id: str) -> None:
        self.tenant_id = tenant_id
        self.manifest_id = manifest_id
        super().__init__(f"Domain pack manifest {manifest_id!r} not found for tenant {tenant_id!r}")


class DomainPackAlreadyExistsError(KalhasDomainError):
    """A domain pack manifest with the same identifier exists for the tenant.

    Manifests are immutable once registered: duplicate registration is
    rejected and never overwrites the stored manifest.
    """

    def __init__(self, tenant_id: str, manifest_id: str) -> None:
        self.tenant_id = tenant_id
        self.manifest_id = manifest_id
        super().__init__(
            f"Domain pack manifest {manifest_id!r} already exists for tenant {tenant_id!r}"
        )


class DomainPackBindingNotFoundError(KalhasDomainError):
    """A domain pack binding does not exist for the given tenant, scenario, and manifest."""

    def __init__(self, tenant_id: str, scenario_id: str, manifest_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        super().__init__(
            f"Domain pack binding of manifest {manifest_id!r} to scenario {scenario_id!r} "
            f"not found for tenant {tenant_id!r}"
        )


class DomainPackBindingAlreadyExistsError(KalhasDomainError):
    """A manifest is already bound to the scenario for the tenant.

    Bindings are immutable: duplicate binding is rejected and never
    overwrites the original binding.
    """

    def __init__(self, tenant_id: str, scenario_id: str, manifest_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        super().__init__(
            f"Domain pack manifest {manifest_id!r} is already bound to scenario "
            f"{scenario_id!r} for tenant {tenant_id!r}"
        )


class DomainCapabilityDeclarationNotFoundError(KalhasDomainError):
    """A capability declaration is absent or belongs to another tenant."""

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, capability_id: str
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.capability_id = capability_id
        super().__init__(
            f"Domain capability declaration of {capability_id!r} for manifest "
            f"{manifest_id!r} in scenario {scenario_id!r} not found for tenant {tenant_id!r}"
        )


class DomainCapabilityDeclarationAlreadyExistsError(KalhasDomainError):
    """A capability of the scenario-bound manifest is already declared.

    Declarations are immutable: a duplicate declaration is rejected and
    never overwrites the original declaration.
    """

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, capability_id: str
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.capability_id = capability_id
        super().__init__(
            f"Domain capability declaration of {capability_id!r} for manifest "
            f"{manifest_id!r} in scenario {scenario_id!r} already exists for tenant "
            f"{tenant_id!r}"
        )


class DomainCapabilityDeclarationIntegrityError(KalhasDomainError):
    """The stored binding snapshot is inconsistent with the registered manifest.

    The public message stays safe and generic: it never exposes raw hash
    values, internal details, or another tenant's data. The optional
    ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, reason: str | None = None
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.reason = reason
        super().__init__(
            f"Domain pack binding snapshot for manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} is inconsistent with the registered manifest for tenant "
            f"{tenant_id!r}; the capability declaration was rejected"
        )


class DomainCapabilityNotFoundError(KalhasDomainError):
    """The requested capability is not declared by the scenario-bound manifest."""

    def __init__(self, capability_id: str, manifest_id: str) -> None:
        self.capability_id = capability_id
        self.manifest_id = manifest_id
        super().__init__(
            f"Capability {capability_id!r} is not declared by manifest {manifest_id!r}"
        )


class DomainCapabilityInputKeyMismatchError(KalhasDomainError):
    """The declared input-value keys do not match the capability's input_ids."""

    def __init__(
        self,
        capability_id: str,
        manifest_id: str,
        missing: tuple[str, ...],
        extra: tuple[str, ...],
    ) -> None:
        self.capability_id = capability_id
        self.manifest_id = manifest_id
        self.missing = missing
        self.extra = extra
        super().__init__(
            f"Declared input values for capability {capability_id!r} of manifest "
            f"{manifest_id!r} must match its declared input_ids exactly "
            f"(missing: {sorted(missing) or 'none'}; extra: {sorted(extra) or 'none'})"
        )


class DomainStateModelNotFoundError(KalhasDomainError):
    """A domain state model is absent or belongs to another tenant."""

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, state_model_id: str
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        super().__init__(
            f"Domain state model {state_model_id!r} of manifest {manifest_id!r} in "
            f"scenario {scenario_id!r} not found for tenant {tenant_id!r}"
        )


class DomainStateModelAlreadyExistsError(KalhasDomainError):
    """A state model with the same id already exists for the scenario-bound manifest.

    State models are immutable: a duplicate declaration is rejected and
    never overwrites the original.
    """

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, state_model_id: str
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        super().__init__(
            f"Domain state model {state_model_id!r} of manifest {manifest_id!r} in "
            f"scenario {scenario_id!r} already exists for tenant {tenant_id!r}"
        )


class DomainStateModelIntegrityError(KalhasDomainError):
    """The stored binding snapshot is inconsistent with the registered manifest.

    The public message stays safe and generic: it never exposes raw hash
    values, internal details, or another tenant's data. The optional
    ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(
        self, tenant_id: str, scenario_id: str, manifest_id: str, reason: str | None = None
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.reason = reason
        super().__init__(
            f"Domain pack binding snapshot for manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} is inconsistent with the registered manifest for tenant "
            f"{tenant_id!r}; the state model declaration was rejected"
        )


class DomainStateTransitionNotFoundError(KalhasDomainError):
    """A domain state transition is absent or belongs to another tenant."""

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        transition_id: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        self.transition_id = transition_id
        super().__init__(
            f"Domain state transition {transition_id!r} of state model "
            f"{state_model_id!r} of manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} not found for tenant {tenant_id!r}"
        )


class DomainStateTransitionAlreadyExistsError(KalhasDomainError):
    """A transition with the same id already exists for the state model.

    Transitions are immutable: a duplicate declaration is rejected and
    never overwrites the original.
    """

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        transition_id: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        self.transition_id = transition_id
        super().__init__(
            f"Domain state transition {transition_id!r} of state model "
            f"{state_model_id!r} of manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} already exists for tenant {tenant_id!r}"
        )


class DomainStateTransitionIntegrityError(KalhasDomainError):
    """A stored record referenced by the transition is inconsistent.

    Raised when the stored binding snapshot is inconsistent with the
    registered manifest, or when the stored state model's copied
    identity, deterministic identifier, content hash, canonical fields,
    or binding relationship are inconsistent with the stored immutable
    records. The public message stays safe and generic: it never exposes
    raw hash values, internal details, or another tenant's data. The
    optional ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.state_model_id = state_model_id
        self.reason = reason
        super().__init__(
            f"Domain pack binding snapshot for manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} is inconsistent with the registered manifest or the "
            f"referenced state model {state_model_id!r} for tenant {tenant_id!r}; "
            f"the transition declaration was rejected"
        )


class DomainStateTransitionValuesError(KalhasDomainError):
    """Guard/target values are inconsistent with the referenced state model.

    Raised when a guard or target key does not identify an existing
    field of the referenced state model, when a value does not exactly
    match the field's declared ``StateValueKind``, or when a value is not
    among the field's declared ``allowed_values``. The public message
    stays generic; the internal ``reason`` (for diagnostics only) names
    the offending field and the violated rule.
    """

    def __init__(
        self,
        state_model_id: str,
        transition_id: str,
        reason: str | None = None,
    ) -> None:
        self.state_model_id = state_model_id
        self.transition_id = transition_id
        self.reason = reason
        super().__init__(
            f"Guard or target values for transition {transition_id!r} of state model "
            f"{state_model_id!r} are inconsistent with the referenced state model; "
            f"the transition declaration was rejected"
        )


class StateValidationError(KalhasDomainError):
    """A state mapping is inconsistent with the state-model field definitions.

    Raised when a state carries an unknown key, is missing a required
    state-model field, holds a value that does not exactly match the
    field's declared ``StateValueKind`` (booleans are never accepted as
    integers or numbers, and non-finite floats are rejected everywhere),
    or holds a value that is not canonically among the field's declared
    ``allowed_values``. The public message stays generic; the internal
    ``reason`` (for diagnostics only) names the offending field and the
    violated rule.
    """

    def __init__(self, state_model_id: str, reason: str | None = None) -> None:
        self.state_model_id = state_model_id
        self.reason = reason
        super().__init__(
            f"State for state model {state_model_id!r} is inconsistent with its "
            f"declared field definitions; the evaluation was rejected"
        )


class TransitionModelMismatchError(KalhasDomainError):
    """A transition does not belong to the supplied state model.

    Raised when a transition's copied ownership/identity fields (tenant,
    scenario, binding, pack id, pack version, manifest, state-model) or
    its authoritative content hashes (manifest content hash, state-model
    content hash, or its own content hash) are inconsistent with the
    supplied ``DomainStateModel`` - including sequences whose members
    disagree about which model they belong to. The public message stays
    generic; the internal ``reason`` (for diagnostics only) names the
    violated rule.
    """

    def __init__(
        self,
        state_model_id: str,
        transition_id: str,
        reason: str | None = None,
    ) -> None:
        self.state_model_id = state_model_id
        self.transition_id = transition_id
        self.reason = reason
        super().__init__(
            f"Transition {transition_id!r} does not belong to state model "
            f"{state_model_id!r}; the evaluation was rejected"
        )


class InvalidTransitionSpecificationError(KalhasDomainError):
    """A transition carries a semantically invalid guard/target specification.

    Raised when a transition's declared guard or target values violate
    the referenced ``DomainStateModel``'s field rules - an unknown
    guard/target key, a value that does not exactly match the field's
    ``StateValueKind``, a value outside the field's declared
    ``allowed_values``, a nested non-finite JSON value, or an empty
    ``target_values`` mapping. The public message stays generic; the
    internal ``reason`` (for diagnostics only) names the violated rule
    and the offending field identifier, never state values or hashes.
    """

    def __init__(
        self,
        transition_id: str,
        reason: str | None = None,
    ) -> None:
        self.transition_id = transition_id
        self.reason = reason
        super().__init__(
            f"Transition {transition_id!r} carries an invalid specification; "
            "the evaluation was rejected"
        )


class TrajectoryLimitExceededError(KalhasDomainError):
    """An explicitly requested trajectory exceeds its maximum attempt bound.

    The engine never evaluates more transitions than the caller's
    requested maximum in one trajectory; longer sequences are rejected
    up front, before any evaluation happens.
    """

    def __init__(self, required: int, maximum: int) -> None:
        self.required = required
        self.maximum = maximum
        super().__init__(
            f"Trajectory requires {required} transition attempts, exceeding the "
            f"requested maximum of {maximum}; the evaluation was rejected"
        )


class InvalidTrajectoryLimitError(KalhasDomainError):
    """The requested maximum number of transition attempts is not positive."""

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        super().__init__(
            f"Trajectory maximum attempt bound must be at least 1 "
            f"(got {maximum!r}); the evaluation was rejected"
        )


class CampaignNotPlanningStateError(KalhasDomainError):
    """A campaign is not in the COMPILED state required for trajectory planning."""

    def __init__(self, campaign_id: str, current_state: str) -> None:
        self.campaign_id = campaign_id
        self.current_state = current_state
        super().__init__(
            f"Campaign {campaign_id!r} is {current_state!r}; trajectory planning "
            f"requires 'compiled'"
        )


class TrajectoryPlansNotFoundError(KalhasDomainError):
    """Trajectory plans are not prepared for the campaign (or are foreign).

    Unknown and foreign campaign plan collections are indistinguishable:
    both raise the same typed error, so no tenant can learn about another
    tenant's plans. The empty prepared collection is a stored value and
    remains distinguishable from "not prepared".
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__(
            f"Trajectory plans for campaign {campaign_id!r} not found for tenant {tenant_id!r}"
        )


class TrajectoryPlansAlreadyPreparedError(KalhasDomainError):
    """Trajectory plans are already prepared for the campaign.

    Preparation is immutable: a second preparation of the same campaign
    raises this error and never overwrites the original collection.
    """

    def __init__(self, tenant_id: str, campaign_id: str) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        super().__init__(
            f"Trajectory plans for campaign {campaign_id!r} are already prepared "
            f"for tenant {tenant_id!r}"
        )


class InvalidTrajectoryDraftError(KalhasDomainError):
    """A LEGION trajectory-plan draft is invalid or inconsistent.

    Raised when the proposed draft fails re-validation (bounds, shape), its
    request identifier does not match the authoritative request, or it
    proposes a transition identifier that is not in the request's available
    transition catalog. The public message stays generic; the internal
    ``reason`` (for diagnostics only) names only the violated rule, never
    raw hashes, transition identifiers, policies, guard/target values, or
    world content.
    """

    def __init__(self, request_id: str | None = None, reason: str | None = None) -> None:
        self.request_id = request_id
        self.reason = reason
        super().__init__(
            "A proposed strategy trajectory plan is invalid or inconsistent; planning was rejected"
        )


class StoredTrajectoryPlanIntegrityError(KalhasDomainError):
    """Stored trajectory plans do not exactly represent authoritative planning.

    Raised when a stored ``StrategyTrajectoryPlan`` fails deterministic
    verification: wrong identifier or content hash, broken ownership,
    unknown or mismatched strategy/state-model/transition references, or
    non-contiguous sequence positions. The public message stays generic;
    the internal ``reason`` (for diagnostics only) names only the violated
    rule, never raw hashes, policies, guard/target values, or world
    content. Stored plans are never repaired, normalized, replaced, or
    silently accepted.
    """

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Stored trajectory plans for campaign {campaign_id!r} failed integrity "
            f"verification and were rejected"
        )


class UnsupportedRuntimeVersionError(KalhasDomainError):
    """A recorded runtime version is not supported for the requested operation.

    Runtime selection derives only from the recorded RunPlan/RunStatus;
    execution, replay, and trajectory planning never guess, default, or
    accept a caller-supplied version. The public message exposes only the
    recorded version string - never state values, hashes, or validation
    details.
    """

    def __init__(self, runtime_version: str, operation: str = "this operation") -> None:
        self.runtime_version = runtime_version
        self.operation = operation
        super().__init__(
            f"Recorded runtime version {runtime_version!r} is not supported for "
            f"{operation}; the request was rejected"
        )


class TrajectoryPlansRequiredError(KalhasDomainError):
    """A trajectory-runtime run requires prepared trajectory plans.

    Raised when a transition-capable compiled world is recorded but no
    trajectory-plan collection was prepared for the campaign: execution
    and replay of runtime version 2.0.0 runs must resolve exactly one
    applicable plan per transition-capable state model before any
    lifecycle change.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(
            f"Run {run_id!r} requires prepared trajectory plans before it can be "
            "executed or replayed"
        )


class RunTrajectoryExecutionNotFoundError(KalhasDomainError):
    """A run trajectory execution artifact is absent or belongs to another tenant.

    Unknown and foreign executions are indistinguishable: both raise the
    same typed error, so no tenant can learn about another tenant's
    executions.
    """

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Trajectory execution for run {run_id!r} not found for tenant {tenant_id!r}"
        )


class RunTrajectoryExecutionAlreadyExistsError(KalhasDomainError):
    """A run trajectory execution artifact already exists for the run.

    Execution artifacts are immutable: a second execution of the same run
    is rejected and never overwrites the stored artifact. An identical
    rewrite is accepted idempotently; a differing artifact is never
    replaced.
    """

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Trajectory execution for run {run_id!r} already exists for tenant "
            f"{tenant_id!r} and is immutable; it will not be replaced"
        )


class RunTrajectoryExecutionIntegrityError(KalhasDomainError):
    """A run trajectory execution record is inconsistent or tampered.

    Raised when a stored ``RunTrajectoryExecution`` fails deterministic
    verification: contract revalidation, deterministic identifier,
    ownership, runtime, input/plan-set/content hashes, result identity,
    state hashes, attempt references, or executed-at provenance. The
    public message stays safe and generic - it never exposes raw hash
    values, state values, guards, targets, or validation details. The
    optional ``reason`` attribute is for internal diagnostics only, and
    the stored record is never repaired, normalized, replaced, or
    silently accepted.
    """

    def __init__(self, run_id: str, reason: str | None = None) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"Trajectory execution for run {run_id!r} failed integrity verification "
            "and was rejected"
        )


class TrajectoryReplayMismatchError(KalhasDomainError):
    """A regenerated trajectory execution does not exactly match the recorded one.

    Replay independently regenerates the complete expected execution from
    recorded inputs and requires exact full-object and content-hash
    equality with the stored authoritative artifact. On mismatch neither
    replay manifest is written; the public message exposes no state
    values, guards, targets, or hashes.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(
            f"Replay of run {run_id!r} regenerated a trajectory execution that does "
            "not exactly match the recorded execution artifact"
        )


class RunTrajectoryReplayManifestConflictError(KalhasDomainError):
    """A stored trajectory replay manifest conflicts with a new record.

    Raised when a different replay manifest is already recorded for the
    run, or when a manifest that violates its contract is offered for
    storage. Replay manifests are immutable: a conflicting write is
    rejected and never overwrites the stored record. The public message
    stays generic; the optional ``reason`` is for internal diagnostics
    only.
    """

    def __init__(self, tenant_id: str, run_id: str, reason: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"Trajectory replay manifest for run {run_id!r} conflicts with the "
            f"stored record for tenant {tenant_id!r}; it will not be replaced"
        )


class RunTrajectoryReplayManifestNotFoundError(KalhasDomainError):
    """A trajectory replay manifest is absent or belongs to another tenant.

    Unknown and foreign manifests are indistinguishable: both raise the
    same typed error, so no tenant can learn about another tenant's
    replay manifests.
    """

    def __init__(self, tenant_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        super().__init__(
            f"Trajectory replay manifest for run {run_id!r} not found for tenant {tenant_id!r}"
        )


class CampaignNotCompleteError(KalhasDomainError):
    """A campaign trajectory matrix may be assembled only for a COMPLETE campaign.

    The matrix is a structural comparison artifact over every verified
    execution of one completed runtime-2.0.0 campaign; an unfinished
    campaign has no authoritative matrix.
    """

    def __init__(self, campaign_id: str, current_state: str) -> None:
        self.campaign_id = campaign_id
        self.current_state = current_state
        super().__init__(
            f"Campaign {campaign_id!r} is {current_state!r}; the trajectory matrix "
            "requires 'complete'"
        )


class CampaignTrajectoryMatrixIntegrityError(KalhasDomainError):
    """A campaign trajectory matrix cannot be assembled from the stored records.

    Raised when a COMPLETE runtime-2.0.0 campaign is missing or carries
    inconsistent or corrupted matrix inputs - a missing or foreign
    compiled world, missing campaign records, a corrupted run-plan
    matrix or trajectory-plan collection, or a missing or corrupted
    run trajectory execution inside the completed campaign. The public
    message stays safe and generic - it never exposes raw hash values,
    state values, guards, targets, validation details, or another
    tenant's data - and a partial matrix is never returned. The optional
    ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(self, campaign_id: str, reason: str | None = None) -> None:
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__(
            f"Campaign {campaign_id!r} failed trajectory matrix integrity verification "
            "and was rejected"
        )


class DomainMetricObservationNotFoundError(KalhasDomainError):
    """A domain metric observation binding is absent or belongs to another tenant.

    Unknown and foreign observation bindings are indistinguishable:
    both raise the same typed error, so no tenant can learn about
    another tenant's observation bindings.
    """

    def __init__(self, tenant_id: str, scenario_id: str, metric_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.metric_id = metric_id
        super().__init__(
            f"Domain metric observation binding for metric {metric_id!r} in scenario "
            f"{scenario_id!r} not found for tenant {tenant_id!r}"
        )


class DomainMetricObservationAlreadyExistsError(KalhasDomainError):
    """A scenario metric already has an observation binding.

    Observation bindings are immutable and, for the Phase 19 MVP, at
    most one binding may exist per scenario metric: a second declaration
    for the same tenant, scenario, and metric - even when it points to a
    different state model or field - is rejected and never overwrites
    the original binding.
    """

    def __init__(self, tenant_id: str, scenario_id: str, metric_id: str) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.metric_id = metric_id
        super().__init__(
            f"Domain metric observation binding for metric {metric_id!r} in scenario "
            f"{scenario_id!r} already exists for tenant {tenant_id!r} and is immutable; "
            "it will not be replaced"
        )


class DomainMetricObservationMetricNotFoundError(KalhasDomainError):
    """The requested metric is not declared by the scenario.

    Raised when ``metric_id`` does not identify exactly one metric of
    the stored ``ScenarioSpec``. The public message stays generic; the
    internal ``reason`` (for diagnostics only) names the violated rule.
    """

    def __init__(self, scenario_id: str, metric_id: str, reason: str | None = None) -> None:
        self.scenario_id = scenario_id
        self.metric_id = metric_id
        self.reason = reason
        super().__init__(
            f"Metric {metric_id!r} is not declared exactly once by scenario "
            f"{scenario_id!r}; the observation binding was rejected"
        )


class DomainMetricObservationStateFieldNotFoundError(KalhasDomainError):
    """The requested state field does not exist in the referenced state model.

    The public message stays generic; the internal ``reason`` (for
    diagnostics only) names the violated rule.
    """

    def __init__(
        self,
        state_model_id: str,
        state_field_id: str,
        reason: str | None = None,
    ) -> None:
        self.state_model_id = state_model_id
        self.state_field_id = state_field_id
        self.reason = reason
        super().__init__(
            f"State field {state_field_id!r} does not exist in state model "
            f"{state_model_id!r}; the observation binding was rejected"
        )


class DomainMetricObservationNonNumericFieldError(KalhasDomainError):
    """The referenced state field is not numeric.

    Raised when the referenced state field's declared ``StateValueKind``
    is not numeric (``integer`` or ``number``): string, boolean, and
    json fields cannot be observed as a metric raw observation. The
    public message stays generic; the internal ``reason`` (for
    diagnostics only) names the violated rule.
    """

    def __init__(
        self,
        state_model_id: str,
        state_field_id: str,
        reason: str | None = None,
    ) -> None:
        self.state_model_id = state_model_id
        self.state_field_id = state_field_id
        self.reason = reason
        super().__init__(
            f"State field {state_field_id!r} of state model {state_model_id!r} is not "
            "numeric; only integer and number fields can be observed as a metric "
            "raw observation"
        )


class DomainMetricObservationIntegrityError(KalhasDomainError):
    """A stored record referenced by the observation binding is inconsistent.

    Raised when the stored binding snapshot is inconsistent with the
    registered manifest, or when the referenced state model's copied
    identity, deterministic identifier, content hash, canonical fields,
    or binding relationship are inconsistent with the stored immutable
    records. The public message stays safe and generic: it never
    exposes raw hash values, state values, metadata values, internal
    details, validator diagnostics, or another tenant's data. The
    optional ``reason`` attribute is for internal diagnostics only.
    """

    def __init__(
        self,
        tenant_id: str,
        scenario_id: str,
        manifest_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.scenario_id = scenario_id
        self.manifest_id = manifest_id
        self.reason = reason
        super().__init__(
            f"Domain pack binding snapshot for manifest {manifest_id!r} in scenario "
            f"{scenario_id!r} is inconsistent with the registered manifest or the "
            f"referenced state model for tenant {tenant_id!r}; the observation "
            "binding was rejected"
        )
