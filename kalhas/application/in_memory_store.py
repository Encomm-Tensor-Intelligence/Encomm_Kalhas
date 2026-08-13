"""In-memory scenario, world, campaign, and run-plan storage.

No database, no filesystem: everything lives in process dictionaries.
Lookups are scoped by (tenant_id, identifier), so tenant isolation is
structural. Duplicate scenario and campaign identifiers for the same
tenant are rejected; compiled worlds are idempotent (deterministic
compilation always produces the same identifier and content).

The store is a **snapshot-isolation boundary**: every write stores a
deep defensive copy of the supplied contract and every read returns a
fresh deep copy, so callers can never alter stored state by mutating
the object they supplied to ``put_*`` or an object returned from
``get_*``/``list_*`` - including nested dict/list values, which Pydantic
frozen contracts do not protect. Tuple collections are deep-copied item
by item. Lifecycle replacement still happens only through the explicit
status-update methods.
"""

from __future__ import annotations

import copy
import warnings
from typing import cast

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    CampaignAlreadyExistsError,
    CampaignNotFoundError,
    DomainCapabilityDeclarationAlreadyExistsError,
    DomainCapabilityDeclarationNotFoundError,
    DomainMetricObservationAlreadyExistsError,
    DomainMetricObservationIntegrityError,
    DomainMetricObservationNotFoundError,
    DomainPackAlreadyExistsError,
    DomainPackBindingAlreadyExistsError,
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    DomainStateModelAlreadyExistsError,
    DomainStateModelNotFoundError,
    DomainStateTransitionAlreadyExistsError,
    DomainStateTransitionNotFoundError,
    RunMetricObservationAlreadyExistsError,
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
    RunNotFoundError,
    RunTrajectoryExecutionAlreadyExistsError,
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryExecutionNotFoundError,
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
    ScenarioAlreadyExistsError,
    ScenarioNotFoundError,
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansAlreadyPreparedError,
    TrajectoryPlansNotFoundError,
    WorldNotFoundError,
)
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileAlreadyExistsError,
    EvaluationProfileIntegrityError,
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_identity import (
    verify_evaluation_profile_identity,
)
from kalhas.application.realization_errors import (
    RealizationRunMetricObservationAlreadyExistsError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionAlreadyExistsError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyModelAlreadyExistsError,
    WorldUncertaintyModelIntegrityError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_identity import (
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.activity import OperationalActivityEvent, OperationalActivityKind
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignStatus
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunStatus
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.simulation import RunEvent
from kalhas.contracts.v1.state_model import DomainStateModel, _contains_non_finite
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

MAX_ACTIVITY_LIMIT = 100


def _deep_copy_contract[T](value: T) -> T:
    """Deep defensive copy of a stored or returned contract.

    Pydantic contracts use their native ``model_copy(deep=True)`` (deep
    copies every field, including nested dicts, lists, and tuple items);
    any other stored object falls back to ``copy.deepcopy``. Every store
    write and every store read crosses this copy boundary, so no caller
    can mutate internal stored state through a shared nested reference.
    """
    model_copy = getattr(value, "model_copy", None)
    if model_copy is not None:
        return cast(T, model_copy(deep=True))
    return copy.deepcopy(value)


def revalidate_stored_trajectory_plan(plan: object, campaign_id: str) -> None:
    """Strictly revalidate one stored plan against its complete contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``StrategyTrajectoryPlan`` instance whose contract
    validators never ran - for example an empty or oversized
    ``transition_references`` tuple, or a nested reference carrying a
    wrong-typed field or an invalid hash pattern. Revalidating the
    plan's Python-mode serialized data with ``strict=True`` re-runs
    every field rule, including the nested
    ``StrategyTrajectoryTransitionReference`` contracts and the 1-1000
    reference bound, so a validator-bypassed stored record is rejected
    before any field of it is trusted. The temporary revalidated object
    is discarded; the actual stored snapshot is what callers continue to
    verify. Any failure raises :class:`StoredTrajectoryPlanIntegrityError`
    with a safe generic public message - Pydantic validation details,
    raw hashes, transition values, and policies are never exposed - and
    storage is never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(plan, StrategyTrajectoryPlan):
        raise StoredTrajectoryPlanIntegrityError(
            campaign_id, reason="stored trajectory plan violates its contract"
        )
    try:
        # A validator-bypassed nested value (for example a string where
        # an integer is required) makes the serializer emit a warning;
        # that diagnostic noise is expected here and deliberately
        # suppressed while the plan is revalidated.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = plan.model_dump(mode="python")
        StrategyTrajectoryPlan.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise StoredTrajectoryPlanIntegrityError(
            campaign_id, reason="stored trajectory plan violates its contract"
        ) from None


def revalidate_stored_trajectory_execution(execution: object, run_id: str) -> None:
    """Strictly revalidate one stored trajectory execution against its contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``RunTrajectoryExecution`` instance whose contract
    validators never ran - for example a wrong-typed result, an invalid
    hash pattern, or a non-2.0.0 runtime literal. Revalidating the
    record's Python-mode serialized data with ``strict=True`` re-runs
    every field rule, including the nested
    ``RunStateTrajectoryResult``/``RunTrajectoryAttemptRecord`` contracts,
    so a validator-bypassed stored record is rejected before any field of
    it is trusted. The temporary revalidated object is discarded; the
    actual stored snapshot is what callers continue to verify. Any
    failure raises :class:`RunTrajectoryExecutionIntegrityError` with a
    safe generic public message - validation details, raw hashes, state
    values, guards, and targets are never exposed - and storage is never
    repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(execution, RunTrajectoryExecution):
        raise RunTrajectoryExecutionIntegrityError(
            run_id, reason="stored trajectory execution violates its contract"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = execution.model_dump(mode="python")
        RunTrajectoryExecution.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RunTrajectoryExecutionIntegrityError(
            run_id, reason="stored trajectory execution violates its contract"
        ) from None


def revalidate_stored_trajectory_replay_manifest(manifest: object, run_id: str) -> None:
    """Strictly revalidate one stored trajectory replay manifest.

    The same serializer-based strict revalidation pattern as the
    execution record: a validator-bypassed ``RunTrajectoryReplayManifest``
    (wrong-typed fields, invalid hash patterns, a non-2.0.0 runtime
    literal, a non-``"exact"`` classification) is rejected before any
    field of it is trusted. Any failure raises
    :class:`RunTrajectoryReplayManifestConflictError` with a safe generic
    public message; storage is never repaired or rewritten.
    """
    if not isinstance(manifest, RunTrajectoryReplayManifest):
        raise RunTrajectoryReplayManifestConflictError(
            str(getattr(manifest, "tenant_id", "")),
            run_id,
            reason="stored trajectory replay manifest violates its contract",
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = manifest.model_dump(mode="python")
        RunTrajectoryReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RunTrajectoryReplayManifestConflictError(
            manifest.tenant_id,
            run_id,
            reason="stored trajectory replay manifest violates its contract",
        ) from None


def revalidate_stored_realization_run_trajectory_execution(execution: object, run_id: str) -> None:
    """Strictly revalidate one stored runtime-3 trajectory execution.

    The same serializer-based strict revalidation pattern as the
    runtime-2 execution record: a validator-bypassed
    ``RealizationRunTrajectoryExecution`` (wrong-typed result, invalid
    hash pattern, or a non-3.0.0 runtime literal) is rejected before any
    field of it is trusted. Any failure raises
    :class:`RealizationRunTrajectoryExecutionIntegrityError`; storage is
    never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(execution, RealizationRunTrajectoryExecution):
        raise RealizationRunTrajectoryExecutionIntegrityError(
            run_id, reason="stored realization trajectory execution violates its contract"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = execution.model_dump(mode="python")
        RealizationRunTrajectoryExecution.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RealizationRunTrajectoryExecutionIntegrityError(
            run_id, reason="stored realization trajectory execution violates its contract"
        ) from None


def revalidate_stored_realization_run_trajectory_replay_manifest(
    manifest: object, run_id: str
) -> None:
    """Strictly revalidate one stored runtime-3 trajectory replay manifest.

    The same serializer-based strict revalidation pattern as the
    runtime-2 manifest record: a validator-bypassed
    ``RealizationRunTrajectoryReplayManifest`` (wrong-typed fields,
    invalid hash patterns, a non-3.0.0 runtime literal, or a
    non-``\"exact\"`` classification) is rejected before any field of it
    is trusted. Any failure raises
    :class:`RealizationRunTrajectoryReplayManifestConflictError`;
    storage is never repaired or rewritten.
    """
    if not isinstance(manifest, RealizationRunTrajectoryReplayManifest):
        raise RealizationRunTrajectoryReplayManifestConflictError(
            run_id, reason="stored realization replay manifest violates its contract"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = manifest.model_dump(mode="python")
        RealizationRunTrajectoryReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RealizationRunTrajectoryReplayManifestConflictError(
            run_id, reason="stored realization replay manifest violates its contract"
        ) from None


def revalidate_stored_realization_run_metric_observation_set(
    observation_set: object, run_id: str
) -> None:
    """Strictly revalidate one stored runtime-3 metric-observation set.

    The same serializer-based strict revalidation pattern as the
    runtime-2 observation set: a validator-bypassed
    ``RealizationRunMetricObservationSet`` (wrong-typed or non-finite
    raw values, invalid hashes, a non-3.0.0 runtime literal, or
    non-canonical observation ordering) is rejected before any field of
    it is trusted. Any failure raises
    :class:`RealizationRunMetricObservationIntegrityError`; storage is
    never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(observation_set, RealizationRunMetricObservationSet):
        raise RealizationRunMetricObservationIntegrityError(
            run_id, reason="stored realization observation set violates its contract"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = observation_set.model_dump(mode="python")
        RealizationRunMetricObservationSet.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RealizationRunMetricObservationIntegrityError(
            run_id, reason="stored realization observation set violates its contract"
        ) from None


def revalidate_stored_domain_metric_observation(
    binding: object,
    tenant_id: str,
    scenario_id: str,
    metric_id: str,
) -> None:
    """Strictly revalidate one stored observation binding against its contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``DomainMetricObservationBinding`` instance whose contract
    validators never ran - for example a malformed nested metadata value,
    an invalid hash pattern, a non-numeric ``state_field_value_kind``
    literal, or a wrong ``observation_point`` literal. Revalidating the
    record's Python-mode serialized data with ``strict=True`` re-runs
    every field rule, so a validator-bypassed stored record is rejected
    before any field of it is trusted. The temporary revalidated object
    is discarded; the actual stored snapshot is what callers continue to
    verify. Any failure raises
    :class:`DomainMetricObservationIntegrityError` with a safe generic
    public message - validation details, raw hashes, state values, and
    metadata values are never exposed - and storage is never repaired,
    normalized, replaced, or rewritten.
    """
    if not isinstance(binding, DomainMetricObservationBinding):
        raise DomainMetricObservationIntegrityError(
            tenant_id,
            scenario_id,
            metric_id,
            reason="stored observation binding violates its contract",
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = binding.model_dump(mode="python")
        revalidated = DomainMetricObservationBinding.model_validate(serialized, strict=True)
        # Pydantic's strict float validation still accepts NaN/Infinity by
        # default, so the contract's non-finite metadata rule is enforced
        # explicitly over the revalidated record as well - a
        # validator-bypassed binding carrying a non-finite float anywhere
        # in its nested metadata is rejected before any field is trusted.
        if _contains_non_finite(revalidated.metadata):
            raise DomainMetricObservationIntegrityError(
                tenant_id,
                scenario_id,
                metric_id,
                reason="stored observation binding violates its contract",
            )
    except (ValidationError, TypeError, AttributeError, DomainMetricObservationIntegrityError):
        raise DomainMetricObservationIntegrityError(
            tenant_id,
            scenario_id,
            metric_id,
            reason="stored observation binding violates its contract",
        ) from None


def revalidate_stored_run_metric_observation_set(
    observation_set: object,
    tenant_id: str,
    run_id: str,
) -> None:
    """Strictly revalidate one stored observation set against its complete contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``RunMetricObservationSet`` instance whose contract
    validators never ran - for example a wrong-typed raw value, a
    non-finite float, a boolean or string accepted as a numeric raw
    value, an invalid hash pattern, a non-2.0.0 runtime literal, a
    wrong ``observation_point`` literal, or a non-canonical observation
    ordering. Revalidating the record's Python-mode serialized data with
    ``strict=True`` re-runs every field rule, including the nested
    ``RunMetricObservationValue`` contracts and the canonical metric-id
    ordering rule, so a validator-bypassed stored record is rejected
    before any field of it is trusted. The temporary revalidated object
    is discarded; the actual stored snapshot is what callers continue to
    verify. Any failure raises :class:`RunMetricObservationIntegrityError`
    with a safe generic public message - validation details, raw
    observed values, hashes, and metadata values are never exposed - and
    storage is never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(observation_set, RunMetricObservationSet):
        raise RunMetricObservationIntegrityError(
            run_id, reason="stored metric observation set violates its contract"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = observation_set.model_dump(mode="python")
        RunMetricObservationSet.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise RunMetricObservationIntegrityError(
            run_id, reason="stored metric observation set violates its contract"
        ) from None


def revalidate_stored_evaluation_profile(
    profile: object,
    tenant_id: str,
    scenario_id: str,
) -> None:
    """Strictly revalidate one stored evaluation profile against its contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``ScenarioEvaluationProfile`` instance whose contract
    validators never ran - for example a malformed nested metadata
    value, an invalid hash pattern, a binding carrying a non-finite
    target or tolerance, a ``reach`` binding without a target or
    tolerance, or a tolerance on a ``minimize``/``maximize`` binding.
    Revalidating the record's Python-mode serialized data with
    ``strict=True`` re-runs every field rule, including the nested
    ``ObjectiveMetricBinding`` contracts and the profile-level rules,
    so a validator-bypassed stored record is rejected before any field
    of it is trusted. The temporary revalidated object is discarded;
    the actual stored snapshot is what callers continue to verify. Any
    failure raises :class:`EvaluationProfileIntegrityError` with a safe
    generic public message - validation details, raw hashes, targets,
    tolerances, scales, and metadata values are never exposed - and
    storage is never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(profile, ScenarioEvaluationProfile):
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile violates its contract",
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = profile.model_dump(mode="python")
        revalidated = ScenarioEvaluationProfile.model_validate(serialized, strict=True)
        # Pydantic's strict float validation still accepts NaN/Infinity by
        # default, so the contract's non-finite metadata rule is enforced
        # explicitly over the revalidated record as well.
        if _contains_non_finite(revalidated.metadata):
            raise EvaluationProfileIntegrityError(
                tenant_id,
                scenario_id,
                reason="stored evaluation profile violates its contract",
            )
        # The deterministic identity (ownership, identifier, content
        # hash) is independently re-verified over the revalidated
        # record; a forged or corrupted record is rejected here even if
        # its contract shape is intact.
        verify_evaluation_profile_identity(
            revalidated, tenant_id=tenant_id, scenario_id=scenario_id
        )
    except (ValidationError, TypeError, AttributeError, EvaluationProfileIntegrityError):
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile violates its contract",
        ) from None


def revalidate_stored_world_uncertainty_model(
    model: object,
    tenant_id: str,
    scenario_id: str,
) -> None:
    """Strictly revalidate one stored uncertainty model against its contract.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a ``WorldUncertaintyModel`` instance whose contract
    validators never ran - for example a malformed nested metadata
    value, an invalid hash pattern, a binding carrying a non-finite
    distribution parameter, a rounding-policy rule violation, a bound
    rule violation, or a non-canonical binding order. Revalidating the
    record's Python-mode serialized data with ``strict=True`` re-runs
    every field rule, including the nested distribution, binding, and
    sampled-value contracts, so a validator-bypassed stored record is
    rejected before any field of it is trusted. The temporary
    revalidated object is discarded; the actual stored snapshot is what
    callers continue to verify. Any failure raises
    :class:`WorldUncertaintyModelIntegrityError` with a safe generic
    public message - validation details, raw hashes, parameters,
    bounds, and metadata values are never exposed - and storage is
    never repaired, normalized, replaced, or rewritten.
    """
    if not isinstance(model, WorldUncertaintyModel):
        raise WorldUncertaintyModelIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored uncertainty model violates its contract",
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = model.model_dump(mode="python")
        revalidated = WorldUncertaintyModel.model_validate(serialized, strict=True)
        # Pydantic's strict float validation still accepts NaN/Infinity by
        # default, so the contract's non-finite metadata rule is enforced
        # explicitly over the revalidated record as well.
        if _contains_non_finite(revalidated.metadata):
            raise WorldUncertaintyModelIntegrityError(
                tenant_id,
                scenario_id,
                reason="stored uncertainty model violates its contract",
            )
        # The deterministic identity (ownership, identifier, content
        # hash) is independently re-verified over the revalidated
        # record; a forged or corrupted record is rejected here even if
        # its contract shape is intact.
        verify_world_uncertainty_model_identity(
            revalidated, tenant_id=tenant_id, scenario_id=scenario_id
        )
    except (
        ValidationError,
        TypeError,
        AttributeError,
        WorldUncertaintyModelIntegrityError,
    ):
        raise WorldUncertaintyModelIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored uncertainty model violates its contract",
        ) from None


class InMemoryScenarioStore:
    """Process-local store for scenarios, worlds, campaigns, and run plans."""

    def __init__(self) -> None:
        self._scenarios: dict[tuple[str, str], ScenarioSpec] = {}
        self._worlds: dict[tuple[str, str], WorldVersion] = {}
        self._manifests: dict[tuple[str, str], WorldManifest] = {}
        self._campaigns: dict[tuple[str, str], CampaignSpec] = {}
        self._campaign_statuses: dict[tuple[str, str], CampaignStatus] = {}
        self._run_plans: dict[tuple[str, str], tuple[RunPlan, ...]] = {}
        self._strategy_candidates: dict[tuple[str, str], tuple[StrategyCandidate, ...]] = {}
        self._run_statuses: dict[tuple[str, str], RunStatus] = {}
        self._run_events: dict[tuple[str, str], tuple[RunEvent, ...]] = {}
        self._replay_manifests: dict[tuple[str, str], ReplayManifest] = {}
        self._input_integrity_manifests: dict[tuple[str, str], RunInputIntegrityManifest] = {}
        self._domain_pack_manifests: dict[tuple[str, str], DomainPackManifest] = {}
        self._domain_pack_bindings: dict[tuple[str, str, str], DomainPackBinding] = {}
        self._domain_capability_declarations: dict[
            tuple[str, str, str, str], DomainCapabilityDeclaration
        ] = {}
        self._domain_state_models: dict[tuple[str, str, str, str], DomainStateModel] = {}
        self._domain_state_transitions: dict[
            tuple[str, str, str, str, str], DomainStateTransition
        ] = {}
        self._domain_metric_observations: dict[
            tuple[str, str, str], DomainMetricObservationBinding
        ] = {}
        self._evaluation_profiles: dict[tuple[str, str], ScenarioEvaluationProfile] = {}
        self._world_uncertainty_models: dict[tuple[str, str], WorldUncertaintyModel] = {}
        self._operational_activity: dict[tuple[str, str], OperationalActivityEvent] = {}
        self._activity_sequences: dict[str, int] = {}
        self._strategy_trajectory_plans: dict[
            tuple[str, str], tuple[StrategyTrajectoryPlan, ...]
        ] = {}
        self._run_trajectory_executions: dict[tuple[str, str], RunTrajectoryExecution] = {}
        self._run_trajectory_replay_manifests: dict[
            tuple[str, str], RunTrajectoryReplayManifest
        ] = {}
        self._run_metric_observation_sets: dict[tuple[str, str], RunMetricObservationSet] = {}
        self._realization_run_trajectory_executions: dict[
            tuple[str, str], RealizationRunTrajectoryExecution
        ] = {}
        self._realization_run_trajectory_replay_manifests: dict[
            tuple[str, str], RealizationRunTrajectoryReplayManifest
        ] = {}
        self._realization_run_metric_observation_sets: dict[
            tuple[str, str], RealizationRunMetricObservationSet
        ] = {}

    def put_scenario(self, scenario: ScenarioSpec) -> None:
        """Store a scenario; raises ScenarioAlreadyExistsError on duplicates."""
        key = (scenario.tenant_id, scenario.identifier)
        if key in self._scenarios:
            raise ScenarioAlreadyExistsError(scenario.tenant_id, scenario.identifier)
        self._scenarios[key] = _deep_copy_contract(scenario)

    def get_scenario(self, tenant_id: str, scenario_id: str) -> ScenarioSpec:
        """Fetch a scenario; raises ScenarioNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._scenarios[(tenant_id, scenario_id)])
        except KeyError as exc:
            raise ScenarioNotFoundError(tenant_id, scenario_id) from exc

    def put_world(self, world: WorldVersion, manifest: WorldManifest) -> None:
        """Store a compiled world and its manifest (idempotent)."""
        self._worlds[(world.tenant_id, world.identifier)] = _deep_copy_contract(world)
        self._manifests[(manifest.tenant_id, world.identifier)] = _deep_copy_contract(manifest)

    def get_world(self, tenant_id: str, world_version_id: str) -> WorldVersion:
        """Fetch a compiled world; raises WorldNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._worlds[(tenant_id, world_version_id)])
        except KeyError as exc:
            raise WorldNotFoundError(tenant_id, world_version_id) from exc

    def get_manifest(self, tenant_id: str, world_version_id: str) -> WorldManifest:
        """Fetch a world manifest; raises WorldNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._manifests[(tenant_id, world_version_id)])
        except KeyError as exc:
            raise WorldNotFoundError(tenant_id, world_version_id) from exc

    def put_campaign(self, campaign: CampaignSpec, status: CampaignStatus) -> None:
        """Store a campaign and its initial status; rejects duplicates."""
        key = (campaign.tenant_id, campaign.identifier)
        if key in self._campaigns:
            raise CampaignAlreadyExistsError(campaign.tenant_id, campaign.identifier)
        self._campaigns[key] = _deep_copy_contract(campaign)
        self._campaign_statuses[(status.tenant_id, campaign.identifier)] = _deep_copy_contract(
            status
        )

    def get_campaign(self, tenant_id: str, campaign_id: str) -> CampaignSpec:
        """Fetch a campaign; raises CampaignNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._campaigns[(tenant_id, campaign_id)])
        except KeyError as exc:
            raise CampaignNotFoundError(tenant_id, campaign_id) from exc

    def get_campaign_status(self, tenant_id: str, campaign_id: str) -> CampaignStatus:
        """Fetch a campaign status; raises CampaignNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._campaign_statuses[(tenant_id, campaign_id)])
        except KeyError as exc:
            raise CampaignNotFoundError(tenant_id, campaign_id) from exc

    def update_campaign_status(
        self, tenant_id: str, campaign_id: str, status: CampaignStatus
    ) -> None:
        """Replace a campaign status; raises CampaignNotFoundError when absent or foreign."""
        if (tenant_id, campaign_id) not in self._campaigns:
            raise CampaignNotFoundError(tenant_id, campaign_id)
        self._campaign_statuses[(tenant_id, campaign_id)] = _deep_copy_contract(status)

    def put_run_plans(self, tenant_id: str, campaign_id: str, plans: tuple[RunPlan, ...]) -> None:
        """Store the ordered run plans of a campaign (planning only)."""
        self._run_plans[(tenant_id, campaign_id)] = tuple(
            _deep_copy_contract(plan) for plan in plans
        )

    def get_run_plans(self, tenant_id: str, campaign_id: str) -> tuple[RunPlan, ...]:
        """Fetch ordered run plans; raises CampaignNotFoundError when absent or foreign."""
        try:
            return tuple(
                _deep_copy_contract(plan) for plan in self._run_plans[(tenant_id, campaign_id)]
            )
        except KeyError as exc:
            raise CampaignNotFoundError(tenant_id, campaign_id) from exc

    def put_strategy_candidates(
        self, tenant_id: str, campaign_id: str, candidates: tuple[StrategyCandidate, ...]
    ) -> None:
        """Persist the exact strategy contracts used by a campaign's runs.

        Execution and replay read from here; Legion is never called again.
        """
        self._strategy_candidates[(tenant_id, campaign_id)] = tuple(
            _deep_copy_contract(candidate) for candidate in candidates
        )

    def get_strategy_candidates(
        self, tenant_id: str, campaign_id: str
    ) -> tuple[StrategyCandidate, ...]:
        """Fetch the recorded strategy contracts; raises CampaignNotFoundError."""
        try:
            return tuple(
                _deep_copy_contract(candidate)
                for candidate in self._strategy_candidates[(tenant_id, campaign_id)]
            )
        except KeyError as exc:
            raise CampaignNotFoundError(tenant_id, campaign_id) from exc

    def put_run_status(self, tenant_id: str, run_id: str, status: RunStatus) -> None:
        """Store the current status of a run (overwrites the previous snapshot)."""
        self._run_statuses[(tenant_id, run_id)] = _deep_copy_contract(status)

    def get_run_status(self, tenant_id: str, run_id: str) -> RunStatus:
        """Fetch a run status; raises RunNotFoundError when absent or foreign."""
        try:
            return _deep_copy_contract(self._run_statuses[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunNotFoundError(tenant_id, run_id) from exc

    def put_run_events(self, tenant_id: str, run_id: str, events: tuple[RunEvent, ...]) -> None:
        """Store the ordered event stream of a run (overwrites any previous stream)."""
        self._run_events[(tenant_id, run_id)] = tuple(
            _deep_copy_contract(event) for event in events
        )

    def get_run_events(self, tenant_id: str, run_id: str) -> tuple[RunEvent, ...]:
        """Fetch the ordered event stream; raises RunNotFoundError when absent or foreign."""
        try:
            return tuple(
                _deep_copy_contract(event) for event in self._run_events[(tenant_id, run_id)]
            )
        except KeyError as exc:
            raise RunNotFoundError(tenant_id, run_id) from exc

    def put_replay_manifest(self, tenant_id: str, run_id: str, manifest: ReplayManifest) -> None:
        """Record the provenance manifest of an exact replay."""
        self._replay_manifests[(tenant_id, run_id)] = _deep_copy_contract(manifest)

    def get_replay_manifest(self, tenant_id: str, run_id: str) -> ReplayManifest:
        """Fetch a recorded replay manifest; raises RunNotFoundError when absent."""
        try:
            return _deep_copy_contract(self._replay_manifests[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunNotFoundError(tenant_id, run_id) from exc

    def put_input_integrity_manifest(
        self, tenant_id: str, run_id: str, manifest: RunInputIntegrityManifest
    ) -> None:
        """Record the latest input-integrity manifest of a run (overwrites)."""
        self._input_integrity_manifests[(tenant_id, run_id)] = _deep_copy_contract(manifest)

    def get_input_integrity_manifest(
        self, tenant_id: str, run_id: str
    ) -> RunInputIntegrityManifest:
        """Fetch the latest input-integrity manifest; raises RunNotFoundError."""
        try:
            return _deep_copy_contract(self._input_integrity_manifests[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunNotFoundError(tenant_id, run_id) from exc

    def put_strategy_trajectory_plans(
        self,
        tenant_id: str,
        campaign_id: str,
        plans: tuple[StrategyTrajectoryPlan, ...],
    ) -> None:
        """Store a campaign's complete trajectory-plan collection (immutable).

        The whole tuple is stored atomically under the
        ``(tenant_id, campaign_id)`` key after a full preflight: every
        plan must belong to the tenant and campaign, and plan identifiers
        must be unique within the collection. A successfully prepared
        empty tuple is a stored value and stays distinguishable from
        "not prepared". Duplicate preparation raises
        TrajectoryPlansAlreadyPreparedError and never overwrites the
        original collection; there is no update, delete, replace, or
        per-plan surface. The Phase 14 deep-copy boundary applies on
        write, so mutating the originals afterwards never affects
        storage.
        """
        key = (tenant_id, campaign_id)
        if key in self._strategy_trajectory_plans:
            raise TrajectoryPlansAlreadyPreparedError(tenant_id, campaign_id)
        # Defense in depth: every plan is strictly revalidated against
        # its complete contract (including nested references and the
        # 1-1000 bound) before it may be written, so a validator-bypassed
        # instance can never enter storage through this surface. The
        # getter re-verifies anyway, because private internal storage
        # can be corrupted without passing through put_*.
        for plan in plans:
            revalidate_stored_trajectory_plan(plan, campaign_id)
        identifiers = [plan.identifier for plan in plans]
        if len(identifiers) != len(set(identifiers)):
            raise StoredTrajectoryPlanIntegrityError(
                campaign_id, reason="duplicate trajectory plan identifiers"
            )
        for plan in plans:
            if plan.tenant_id != tenant_id or plan.campaign_id != campaign_id:
                raise StoredTrajectoryPlanIntegrityError(
                    campaign_id, reason="trajectory plan ownership mismatch"
                )
        self._strategy_trajectory_plans[key] = tuple(_deep_copy_contract(plan) for plan in plans)

    def get_strategy_trajectory_plans(
        self, tenant_id: str, campaign_id: str
    ) -> tuple[StrategyTrajectoryPlan, ...]:
        """Fetch a campaign's prepared trajectory-plan collection.

        Returns the complete immutable tuple in the service's
        deterministic order (each plan deep-copied). Raises
        TrajectoryPlansNotFoundError when the campaign has no prepared
        collection; unknown and foreign collections are indistinguishable.
        """
        try:
            return tuple(
                _deep_copy_contract(plan)
                for plan in self._strategy_trajectory_plans[(tenant_id, campaign_id)]
            )
        except KeyError as exc:
            raise TrajectoryPlansNotFoundError(tenant_id, campaign_id) from exc

    def put_run_trajectory_execution(
        self, tenant_id: str, run_id: str, execution: RunTrajectoryExecution
    ) -> None:
        """Store a run's immutable trajectory execution artifact.

        The record is strictly revalidated against its complete contract
        (serializer-based strict revalidation - a validator-bypassed
        instance is rejected before any field is trusted) and stored as a
        deep defensive copy. Execution artifacts are immutable: a second
        identical write is accepted idempotently, while a differing
        artifact raises RunTrajectoryExecutionAlreadyExistsError and
        never replaces the original. There is no update, delete, repair,
        or per-result surface.
        """
        revalidate_stored_trajectory_execution(execution, run_id)
        key = (tenant_id, run_id)
        if key in self._run_trajectory_executions:
            if self._run_trajectory_executions[key] != execution:
                raise RunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)
            return
        self._run_trajectory_executions[key] = _deep_copy_contract(execution)

    def get_run_trajectory_execution(self, tenant_id: str, run_id: str) -> RunTrajectoryExecution:
        """Fetch a run's trajectory execution artifact.

        Returns a fresh deep copy. Raises
        RunTrajectoryExecutionNotFoundError when absent; unknown and
        foreign executions are indistinguishable.
        """
        try:
            return _deep_copy_contract(self._run_trajectory_executions[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunTrajectoryExecutionNotFoundError(tenant_id, run_id) from exc

    def put_run_trajectory_replay_manifest(
        self, tenant_id: str, run_id: str, manifest: RunTrajectoryReplayManifest
    ) -> None:
        """Record a run's immutable trajectory replay manifest.

        The record is strictly revalidated against its complete contract
        and stored as a deep defensive copy. Manifests are immutable: an
        identical rewrite is accepted idempotently, while a different
        manifest raises RunTrajectoryReplayManifestConflictError and
        never overwrites the stored record. There is no update, delete,
        repair, or replace surface.
        """
        revalidate_stored_trajectory_replay_manifest(manifest, run_id)
        key = (tenant_id, run_id)
        if key in self._run_trajectory_replay_manifests:
            if self._run_trajectory_replay_manifests[key] != manifest:
                raise RunTrajectoryReplayManifestConflictError(tenant_id, run_id)
            return
        self._run_trajectory_replay_manifests[key] = _deep_copy_contract(manifest)

    def get_run_trajectory_replay_manifest(
        self, tenant_id: str, run_id: str
    ) -> RunTrajectoryReplayManifest:
        """Fetch a run's trajectory replay manifest.

        Returns a fresh deep copy. Raises
        RunTrajectoryReplayManifestNotFoundError when absent; unknown and
        foreign manifests are indistinguishable.
        """
        try:
            return _deep_copy_contract(self._run_trajectory_replay_manifests[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunTrajectoryReplayManifestNotFoundError(tenant_id, run_id) from exc

    def put_run_metric_observation_set(
        self,
        tenant_id: str,
        run_id: str,
        observation_set: RunMetricObservationSet,
    ) -> None:
        """Store a run's immutable metric observation set; rejects duplicates.

        Exactly one observation set may exist per tenant + run: a second
        write - even an identical artifact - raises
        RunMetricObservationAlreadyExistsError and never overwrites the
        original. The supplied artifact must carry exactly the key's
        ownership (tenant and run identifiers) and must strictly
        revalidate against its complete contract (serializer-based
        strict revalidation - a validator-bypassed instance with
        wrong-typed or non-finite raw values, invalid hashes, a
        non-2.0.0 runtime literal, or non-canonical observation ordering
        is rejected before any field is trusted), otherwise a safe typed
        integrity error is raised and nothing is written. The stored
        artifact is a deep defensive copy. There is no update, delete,
        repair, or replace surface.
        """
        key = (tenant_id, run_id)
        if key in self._run_metric_observation_sets:
            raise RunMetricObservationAlreadyExistsError(tenant_id, run_id)
        # Defense in depth: the complete contract is strictly revalidated
        # (including nested observation values, raw-value kind rules, and
        # the canonical ordering rule) before the artifact may be
        # written, so a validator-bypassed instance can never enter
        # storage through this surface. The getter re-verifies anyway,
        # because private internal storage can be corrupted without
        # passing through put_*.
        revalidate_stored_run_metric_observation_set(observation_set, tenant_id, run_id)
        if observation_set.tenant_id != tenant_id or observation_set.run_id != run_id:
            raise RunMetricObservationIntegrityError(
                run_id, reason="metric observation set ownership mismatch"
            )
        self._run_metric_observation_sets[key] = _deep_copy_contract(observation_set)

    def get_run_metric_observation_set(
        self, tenant_id: str, run_id: str
    ) -> RunMetricObservationSet:
        """Fetch a run's metric observation set.

        Returns a fresh deep copy. Raises
        RunMetricObservationNotFoundError when absent; unknown and
        foreign observation sets are indistinguishable.
        """
        try:
            return _deep_copy_contract(self._run_metric_observation_sets[(tenant_id, run_id)])
        except KeyError as exc:
            raise RunMetricObservationNotFoundError(tenant_id, run_id) from exc

    def put_realization_run_trajectory_execution(
        self,
        tenant_id: str,
        run_id: str,
        execution: RealizationRunTrajectoryExecution,
    ) -> None:
        """Store a run's immutable runtime-3 trajectory execution artifact.

        The record is strictly revalidated against its complete contract
        (serializer-based strict revalidation - a validator-bypassed
        instance is rejected before any field is trusted) and stored as a
        deep defensive copy. Execution artifacts are immutable: a second
        identical write is accepted idempotently, while a differing
        artifact raises RealizationRunTrajectoryExecutionAlreadyExistsError
        and never replaces the original. There is no update, delete,
        repair, or per-result surface.
        """
        revalidate_stored_realization_run_trajectory_execution(execution, run_id)
        key = (tenant_id, run_id)
        if key in self._realization_run_trajectory_executions:
            if self._realization_run_trajectory_executions[key] != execution:
                raise RealizationRunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)
            return
        self._realization_run_trajectory_executions[key] = _deep_copy_contract(execution)

    def get_realization_run_trajectory_execution(
        self, tenant_id: str, run_id: str
    ) -> RealizationRunTrajectoryExecution:
        """Fetch a run's runtime-3 trajectory execution artifact.

        Returns a fresh deep copy. Raises
        RealizationRunTrajectoryExecutionNotFoundError when absent;
        unknown and foreign executions are indistinguishable.
        """
        try:
            return _deep_copy_contract(
                self._realization_run_trajectory_executions[(tenant_id, run_id)]
            )
        except KeyError as exc:
            raise RealizationRunTrajectoryExecutionNotFoundError(tenant_id, run_id) from exc

    def put_realization_run_trajectory_replay_manifest(
        self,
        tenant_id: str,
        run_id: str,
        manifest: RealizationRunTrajectoryReplayManifest,
    ) -> None:
        """Record a run's immutable runtime-3 trajectory replay manifest.

        The record is strictly revalidated against its complete contract
        and stored as a deep defensive copy. Manifests are immutable: an
        identical rewrite is accepted idempotently, while a different
        manifest raises RealizationRunTrajectoryReplayManifestConflictError
        and never overwrites the stored record. There is no update,
        delete, repair, or replace surface.
        """
        revalidate_stored_realization_run_trajectory_replay_manifest(manifest, run_id)
        key = (tenant_id, run_id)
        if key in self._realization_run_trajectory_replay_manifests:
            if self._realization_run_trajectory_replay_manifests[key] != manifest:
                raise RealizationRunTrajectoryReplayManifestConflictError(run_id)
            return
        self._realization_run_trajectory_replay_manifests[key] = _deep_copy_contract(manifest)

    def get_realization_run_trajectory_replay_manifest(
        self, tenant_id: str, run_id: str
    ) -> RealizationRunTrajectoryReplayManifest:
        """Fetch a run's runtime-3 trajectory replay manifest.

        Returns a fresh deep copy. Raises
        RealizationRunTrajectoryReplayManifestNotFoundError when absent;
        unknown and foreign manifests are indistinguishable.
        """
        try:
            return _deep_copy_contract(
                self._realization_run_trajectory_replay_manifests[(tenant_id, run_id)]
            )
        except KeyError as exc:
            raise RealizationRunTrajectoryReplayManifestNotFoundError(tenant_id, run_id) from exc

    def put_realization_run_metric_observation_set(
        self,
        tenant_id: str,
        run_id: str,
        observation_set: RealizationRunMetricObservationSet,
    ) -> None:
        """Store a run's immutable runtime-3 observation set; rejects duplicates.

        Exactly one observation set may exist per tenant + run: a second
        write - even an identical artifact - raises
        RealizationRunMetricObservationAlreadyExistsError and never
        overwrites the original. The supplied artifact must carry exactly
        the key's ownership (tenant and run identifiers) and must strictly
        revalidate against its complete contract (serializer-based strict
        revalidation - a validator-bypassed instance with wrong-typed or
        non-finite raw values, invalid hashes, a non-3.0.0 runtime
        literal, or non-canonical observation ordering is rejected before
        any field is trusted), otherwise a safe typed integrity error is
        raised and nothing is written. The stored artifact is a deep
        defensive copy. There is no update, delete, repair, or replace
        surface.
        """
        key = (tenant_id, run_id)
        if key in self._realization_run_metric_observation_sets:
            raise RealizationRunMetricObservationAlreadyExistsError(tenant_id, run_id)
        revalidate_stored_realization_run_metric_observation_set(observation_set, run_id)
        if observation_set.tenant_id != tenant_id or observation_set.run_id != run_id:
            raise RealizationRunMetricObservationIntegrityError(
                run_id, reason="realization metric observation set ownership mismatch"
            )
        self._realization_run_metric_observation_sets[key] = _deep_copy_contract(observation_set)

    def get_realization_run_metric_observation_set(
        self, tenant_id: str, run_id: str
    ) -> RealizationRunMetricObservationSet:
        """Fetch a run's runtime-3 metric observation set.

        Returns a fresh deep copy. Raises
        RealizationRunMetricObservationNotFoundError when absent; unknown
        and foreign observation sets are indistinguishable.
        """
        try:
            return _deep_copy_contract(
                self._realization_run_metric_observation_sets[(tenant_id, run_id)]
            )
        except KeyError as exc:
            raise RealizationRunMetricObservationNotFoundError(tenant_id, run_id) from exc

    def put_domain_pack_manifest(self, manifest: DomainPackManifest) -> None:
        """Store an immutable domain pack manifest; rejects duplicates.

        Manifests are immutable once registered: a second registration with
        the same ``(tenant_id, manifest identifier)`` raises
        DomainPackAlreadyExistsError and never overwrites the stored entry.
        """
        key = (manifest.tenant_id, manifest.identifier)
        if key in self._domain_pack_manifests:
            raise DomainPackAlreadyExistsError(manifest.tenant_id, manifest.identifier)
        self._domain_pack_manifests[key] = _deep_copy_contract(manifest)

    def get_domain_pack_manifest(self, tenant_id: str, manifest_id: str) -> DomainPackManifest:
        """Fetch a domain pack manifest; raises DomainPackNotFoundError.

        Unknown and foreign manifests are indistinguishable: both raise the
        same typed error, so no tenant can learn about another tenant's
        manifests.
        """
        try:
            return _deep_copy_contract(self._domain_pack_manifests[(tenant_id, manifest_id)])
        except KeyError as exc:
            raise DomainPackNotFoundError(tenant_id, manifest_id) from exc

    def list_domain_pack_manifests(self, tenant_id: str) -> tuple[DomainPackManifest, ...]:
        """List a tenant's domain pack manifests, sorted by manifest identifier.

        The returned tuple is immutable and the order is deterministic:
        manifest identifiers are unique per tenant, so sorting by identifier
        is a total order.
        """
        manifests = [
            manifest
            for manifest in self._domain_pack_manifests.values()
            if manifest.tenant_id == tenant_id
        ]
        return tuple(
            _deep_copy_contract(manifest)
            for manifest in sorted(manifests, key=lambda manifest: manifest.identifier)
        )

    def put_domain_pack_binding(self, binding: DomainPackBinding) -> None:
        """Store an immutable scenario binding; rejects duplicates.

        Bindings are immutable: a second binding of the same manifest to
        the same scenario for the same tenant raises
        DomainPackBindingAlreadyExistsError and never overwrites the
        original. There is no update, delete, replace, or unbind surface.
        """
        key = (binding.tenant_id, binding.scenario_id, binding.manifest_id)
        if key in self._domain_pack_bindings:
            raise DomainPackBindingAlreadyExistsError(
                binding.tenant_id, binding.scenario_id, binding.manifest_id
            )
        self._domain_pack_bindings[key] = _deep_copy_contract(binding)

    def get_domain_pack_binding(
        self, tenant_id: str, scenario_id: str, manifest_id: str
    ) -> DomainPackBinding:
        """Fetch a binding; raises DomainPackBindingNotFoundError.

        Unknown and foreign bindings are indistinguishable: both raise the
        same typed error, so no tenant can learn about another tenant's
        bindings.
        """
        try:
            return _deep_copy_contract(
                self._domain_pack_bindings[(tenant_id, scenario_id, manifest_id)]
            )
        except KeyError as exc:
            raise DomainPackBindingNotFoundError(tenant_id, scenario_id, manifest_id) from exc

    def list_domain_pack_bindings(
        self, tenant_id: str, scenario_id: str
    ) -> tuple[DomainPackBinding, ...]:
        """List a scenario's bindings, sorted by manifest identifier.

        Deterministic: manifest identifiers are unique per scenario, so
        sorting by manifest identifier is a total order. The returned
        tuple is immutable.
        """
        bindings = [
            binding
            for binding in self._domain_pack_bindings.values()
            if binding.tenant_id == tenant_id and binding.scenario_id == scenario_id
        ]
        return tuple(
            _deep_copy_contract(binding)
            for binding in sorted(bindings, key=lambda binding: binding.manifest_id)
        )

    def put_domain_capability_declaration(self, declaration: DomainCapabilityDeclaration) -> None:
        """Store an immutable capability declaration; rejects duplicates.

        Declarations are immutable: a second declaration of the same
        scenario/manifest/capability for the same tenant raises
        DomainCapabilityDeclarationAlreadyExistsError and never overwrites
        the original. There is no update, delete, replace, or mutation
        surface.
        """
        key = (
            declaration.tenant_id,
            declaration.scenario_id,
            declaration.manifest_id,
            declaration.capability_id,
        )
        if key in self._domain_capability_declarations:
            raise DomainCapabilityDeclarationAlreadyExistsError(
                declaration.tenant_id,
                declaration.scenario_id,
                declaration.manifest_id,
                declaration.capability_id,
            )
        self._domain_capability_declarations[key] = _deep_copy_contract(declaration)

    def get_domain_capability_declaration(
        self, tenant_id: str, scenario_id: str, manifest_id: str, capability_id: str
    ) -> DomainCapabilityDeclaration:
        """Fetch a declaration; raises DomainCapabilityDeclarationNotFoundError.

        Unknown and foreign declarations are indistinguishable: both raise
        the same typed error, so no tenant can learn about another
        tenant's declarations.
        """
        try:
            return _deep_copy_contract(
                self._domain_capability_declarations[
                    (tenant_id, scenario_id, manifest_id, capability_id)
                ]
            )
        except KeyError as exc:
            raise DomainCapabilityDeclarationNotFoundError(
                tenant_id, scenario_id, manifest_id, capability_id
            ) from exc

    def list_domain_capability_declarations(
        self, tenant_id: str, scenario_id: str
    ) -> tuple[DomainCapabilityDeclaration, ...]:
        """List a scenario's declarations, sorted by manifest then capability.

        Deterministic: manifest identifiers are unique per scenario and
        capability identifiers are unique per manifest, so sorting by
        ``(manifest_id, capability_id)`` is a total order. The returned
        tuple is immutable.
        """
        declarations = [
            declaration
            for declaration in self._domain_capability_declarations.values()
            if declaration.tenant_id == tenant_id and declaration.scenario_id == scenario_id
        ]
        return tuple(
            _deep_copy_contract(declaration)
            for declaration in sorted(
                declarations,
                key=lambda declaration: (declaration.manifest_id, declaration.capability_id),
            )
        )

    def put_domain_state_model(self, state_model: DomainStateModel) -> None:
        """Store an immutable domain state model; rejects duplicates.

        State models are immutable: a second declaration of the same
        scenario/manifest/state-model id for the same tenant raises
        DomainStateModelAlreadyExistsError and never overwrites the
        original. There is no update, delete, replace, or mutation
        surface.
        """
        key = (
            state_model.tenant_id,
            state_model.scenario_id,
            state_model.manifest_id,
            state_model.state_model_id,
        )
        if key in self._domain_state_models:
            raise DomainStateModelAlreadyExistsError(
                state_model.tenant_id,
                state_model.scenario_id,
                state_model.manifest_id,
                state_model.state_model_id,
            )
        self._domain_state_models[key] = _deep_copy_contract(state_model)

    def get_domain_state_model(
        self, tenant_id: str, scenario_id: str, manifest_id: str, state_model_id: str
    ) -> DomainStateModel:
        """Fetch a state model; raises DomainStateModelNotFoundError.

        Unknown and foreign state models are indistinguishable: both raise
        the same typed error, so no tenant can learn about another
        tenant's state models.
        """
        try:
            return _deep_copy_contract(
                self._domain_state_models[(tenant_id, scenario_id, manifest_id, state_model_id)]
            )
        except KeyError as exc:
            raise DomainStateModelNotFoundError(
                tenant_id, scenario_id, manifest_id, state_model_id
            ) from exc

    def list_domain_state_models(
        self, tenant_id: str, scenario_id: str
    ) -> tuple[DomainStateModel, ...]:
        """List a scenario's state models, sorted by manifest then state-model id.

        Deterministic: manifest identifiers are unique per scenario and
        state-model identifiers are unique per manifest, so sorting by
        ``(manifest_id, state_model_id)`` is a total order. The returned
        tuple is immutable.
        """
        state_models = [
            state_model
            for state_model in self._domain_state_models.values()
            if state_model.tenant_id == tenant_id and state_model.scenario_id == scenario_id
        ]
        return tuple(
            _deep_copy_contract(state_model)
            for state_model in sorted(
                state_models,
                key=lambda state_model: (state_model.manifest_id, state_model.state_model_id),
            )
        )

    def put_domain_state_transition(self, transition: DomainStateTransition) -> None:
        """Store an immutable domain state transition; rejects duplicates.

        Transitions are immutable: a second declaration of the same
        scenario/manifest/state-model/transition id for the same tenant
        raises DomainStateTransitionAlreadyExistsError and never
        overwrites the original. There is no update, delete, replace, or
        mutation surface.
        """
        key = (
            transition.tenant_id,
            transition.scenario_id,
            transition.manifest_id,
            transition.state_model_id,
            transition.transition_id,
        )
        if key in self._domain_state_transitions:
            raise DomainStateTransitionAlreadyExistsError(
                transition.tenant_id,
                transition.scenario_id,
                transition.manifest_id,
                transition.state_model_id,
                transition.transition_id,
            )
        self._domain_state_transitions[key] = _deep_copy_contract(transition)

    def get_domain_state_transition(
        self,
        tenant_id: str,
        scenario_id: str,
        manifest_id: str,
        state_model_id: str,
        transition_id: str,
    ) -> DomainStateTransition:
        """Fetch a transition; raises DomainStateTransitionNotFoundError.

        Unknown and foreign transitions are indistinguishable: both raise
        the same typed error, so no tenant can learn about another
        tenant's transitions.
        """
        try:
            return _deep_copy_contract(
                self._domain_state_transitions[
                    (tenant_id, scenario_id, manifest_id, state_model_id, transition_id)
                ]
            )
        except KeyError as exc:
            raise DomainStateTransitionNotFoundError(
                tenant_id, scenario_id, manifest_id, state_model_id, transition_id
            ) from exc

    def list_domain_state_transitions(
        self, tenant_id: str, scenario_id: str
    ) -> tuple[DomainStateTransition, ...]:
        """List a scenario's transitions, sorted by manifest, state model, then transition.

        Deterministic: manifest identifiers are unique per scenario,
        state-model identifiers are unique per manifest, and transition
        identifiers are unique per state model, so sorting by
        ``(manifest_id, state_model_id, transition_id)`` is a total
        order. The returned tuple is immutable.
        """
        transitions = [
            transition
            for transition in self._domain_state_transitions.values()
            if transition.tenant_id == tenant_id and transition.scenario_id == scenario_id
        ]
        return tuple(
            _deep_copy_contract(transition)
            for transition in sorted(
                transitions,
                key=lambda transition: (
                    transition.manifest_id,
                    transition.state_model_id,
                    transition.transition_id,
                ),
            )
        )

    def put_domain_metric_observation(
        self,
        tenant_id: str,
        scenario_id: str,
        metric_id: str,
        binding: DomainMetricObservationBinding,
    ) -> None:
        """Store an immutable observation binding; rejects duplicates.

        Observation bindings are immutable and, for the Phase 19 MVP, at
        most one binding may exist per scenario metric: a second
        declaration for the same ``(tenant_id, scenario_id, metric_id)``
        - even when it points to a different state model or field -
        raises DomainMetricObservationAlreadyExistsError and never
        overwrites the original. The supplied binding must carry exactly
        the key's ownership (tenant, scenario, metric identifiers) and
        must strictly revalidate against its complete contract
        (serializer-based strict revalidation - a validator-bypassed
        instance is rejected before any field is trusted), otherwise a
        safe typed integrity error is raised and nothing is written.
        There is no update, delete, repair, or replace surface.
        """
        key = (tenant_id, scenario_id, metric_id)
        if key in self._domain_metric_observations:
            raise DomainMetricObservationAlreadyExistsError(tenant_id, scenario_id, metric_id)
        # Defense in depth: the complete contract is strictly revalidated
        # (including nested metadata values and the value-kind literals)
        # before the binding may be written, so a validator-bypassed
        # instance can never enter storage through this surface. The
        # getter re-verifies anyway, because private internal storage can
        # be corrupted without passing through put_*.
        revalidate_stored_domain_metric_observation(binding, tenant_id, scenario_id, metric_id)
        if (
            binding.tenant_id != tenant_id
            or binding.scenario_id != scenario_id
            or binding.metric_id != metric_id
        ):
            raise DomainMetricObservationIntegrityError(
                tenant_id,
                scenario_id,
                metric_id,
                reason="observation binding ownership mismatch",
            )
        self._domain_metric_observations[key] = _deep_copy_contract(binding)

    def get_domain_metric_observation(
        self, tenant_id: str, scenario_id: str, metric_id: str
    ) -> DomainMetricObservationBinding:
        """Fetch an observation binding; raises DomainMetricObservationNotFoundError.

        Unknown and foreign observation bindings are indistinguishable:
        both raise the same typed error, so no tenant can learn about
        another tenant's observation bindings.
        """
        try:
            return _deep_copy_contract(
                self._domain_metric_observations[(tenant_id, scenario_id, metric_id)]
            )
        except KeyError as exc:
            raise DomainMetricObservationNotFoundError(tenant_id, scenario_id, metric_id) from exc

    def list_domain_metric_observations(
        self, tenant_id: str, scenario_id: str
    ) -> tuple[DomainMetricObservationBinding, ...]:
        """List a scenario's observation bindings, sorted by metric identifier.

        Deterministic: the Phase 19 MVP allows at most one observation
        binding per scenario metric, so metric identifiers are unique
        per scenario and sorting by ``metric_id`` is a total order. The
        returned tuple is immutable.
        """
        bindings = [
            binding
            for binding in self._domain_metric_observations.values()
            if binding.tenant_id == tenant_id and binding.scenario_id == scenario_id
        ]
        return tuple(
            _deep_copy_contract(binding)
            for binding in sorted(bindings, key=lambda binding: binding.metric_id)
        )

    def put_evaluation_profile(
        self,
        tenant_id: str,
        scenario_id: str,
        profile: ScenarioEvaluationProfile,
    ) -> None:
        """Store an immutable evaluation profile; rejects duplicates.

        Evaluation profiles are immutable and at most one profile may
        exist per ``(tenant_id, scenario_id)``: a second declaration
        raises EvaluationProfileAlreadyExistsError and never overwrites
        the original. The supplied profile must carry exactly the key's
        ownership (tenant and scenario identifiers) and must strictly
        revalidate against its complete contract (serializer-based
        strict revalidation - a validator-bypassed instance is rejected
        before any field is trusted), otherwise a safe typed integrity
        error is raised and nothing is written. There is no update,
        delete, repair, replace, or list surface.
        """
        key = (tenant_id, scenario_id)
        if key in self._evaluation_profiles:
            raise EvaluationProfileAlreadyExistsError(tenant_id, scenario_id)
        revalidate_stored_evaluation_profile(profile, tenant_id, scenario_id)
        if profile.tenant_id != tenant_id or profile.scenario_id != scenario_id:
            raise EvaluationProfileIntegrityError(
                tenant_id,
                scenario_id,
                reason="evaluation profile ownership mismatch",
            )
        self._evaluation_profiles[key] = _deep_copy_contract(profile)

    def get_evaluation_profile(
        self,
        tenant_id: str,
        scenario_id: str,
    ) -> ScenarioEvaluationProfile:
        """Fetch an evaluation profile; raises EvaluationProfileNotFoundError.

        The stored record is strictly revalidated against its complete
        contract **and** its deterministic identity (ownership,
        identifier, content hash) on every read, before any copy crosses
        the store boundary: a validator-bypassed, malformed, forged, or
        corrupted stored record raises EvaluationProfileIntegrityError
        and is never returned. After successful revalidation a fresh
        deep defensive copy is returned. Unknown and foreign profiles
        are indistinguishable: both raise the same typed error, so no
        tenant can learn about another tenant's profiles.
        """
        try:
            stored = self._evaluation_profiles[(tenant_id, scenario_id)]
        except KeyError as exc:
            raise EvaluationProfileNotFoundError(tenant_id, scenario_id) from exc
        revalidate_stored_evaluation_profile(stored, tenant_id, scenario_id)
        return _deep_copy_contract(stored)

    def has_compiled_worlds_for_scenario(self, tenant_id: str, scenario_id: str) -> bool:
        """True when any world has been compiled for the tenant/scenario.

        Worlds are immutable and the compiler is deterministic, so once
        a world exists for a scenario the evaluation profile can no
        longer be declared (its snapshot could never be embedded in the
        already-compiled world). Read-only scan over the stored world
        records; nothing is modified.
        """
        return any(
            world.tenant_id == tenant_id and world.source_scenario_id == scenario_id
            for world in self._worlds.values()
        )

    def put_world_uncertainty_model(
        self,
        tenant_id: str,
        scenario_id: str,
        model: WorldUncertaintyModel,
    ) -> None:
        """Store an immutable uncertainty model; rejects duplicates.

        Uncertainty models are immutable and at most one model may
        exist per ``(tenant_id, scenario_id)``: a second declaration
        raises WorldUncertaintyModelAlreadyExistsError and never
        overwrites the original. The supplied model must carry exactly
        the key's ownership (tenant and scenario identifiers) and must
        strictly revalidate against its complete contract
        (serializer-based strict revalidation - a validator-bypassed
        instance is rejected before any field is trusted), otherwise a
        safe typed integrity error is raised and nothing is written.
        There is no update, delete, repair, replace, or list surface.
        """
        key = (tenant_id, scenario_id)
        if key in self._world_uncertainty_models:
            raise WorldUncertaintyModelAlreadyExistsError(tenant_id, scenario_id)
        revalidate_stored_world_uncertainty_model(model, tenant_id, scenario_id)
        if model.tenant_id != tenant_id or model.scenario_id != scenario_id:
            raise WorldUncertaintyModelIntegrityError(
                tenant_id,
                scenario_id,
                reason="uncertainty model ownership mismatch",
            )
        self._world_uncertainty_models[key] = _deep_copy_contract(model)

    def get_world_uncertainty_model(
        self,
        tenant_id: str,
        scenario_id: str,
    ) -> WorldUncertaintyModel:
        """Fetch an uncertainty model; raises WorldUncertaintyModelNotFoundError.

        The stored record is strictly revalidated against its complete
        contract **and** its deterministic identity (ownership,
        identifier, content hash) on every read, before any copy
        crosses the store boundary: a validator-bypassed, malformed,
        forged, or corrupted stored record raises
        WorldUncertaintyModelIntegrityError and is never returned.
        After successful revalidation a fresh deep defensive copy is
        returned. Unknown and foreign models are indistinguishable:
        both raise the same typed error, so no tenant can learn about
        another tenant's models.
        """
        try:
            stored = self._world_uncertainty_models[(tenant_id, scenario_id)]
        except KeyError as exc:
            raise WorldUncertaintyModelNotFoundError(tenant_id, scenario_id) from exc
        revalidate_stored_world_uncertainty_model(stored, tenant_id, scenario_id)
        return _deep_copy_contract(stored)

    def append_operational_activity(
        self,
        *,
        tenant_id: str,
        kind: OperationalActivityKind,
        occurred_at: AwareDatetime,
        payload: dict[str, JsonValue],
        scenario_id: str | None = None,
        world_version_id: str | None = None,
        campaign_id: str | None = None,
        run_id: str | None = None,
        manifest_id: str | None = None,
        binding_id: str | None = None,
        declaration_id: str | None = None,
    ) -> OperationalActivityEvent:
        """Append one immutable tenant-local activity event.

        The store assigns the tenant-local strictly increasing ``sequence``
        (starting at zero) and the deterministic identifier
        ``activity-{sequence}``. Events are immutable once appended; there
        is no update, delete, replace, clear, or unrestricted mutable
        activity surface. Recording activity never alters any other store
        collection.
        """
        sequence = self._activity_sequences.get(tenant_id, 0)
        event = OperationalActivityEvent(
            identifier=f"activity-{sequence}",
            tenant_id=tenant_id,
            sequence=sequence,
            kind=kind,
            occurred_at=occurred_at,
            scenario_id=scenario_id,
            world_version_id=world_version_id,
            campaign_id=campaign_id,
            run_id=run_id,
            manifest_id=manifest_id,
            binding_id=binding_id,
            declaration_id=declaration_id,
            payload=payload,
        )
        self._operational_activity[(tenant_id, event.identifier)] = _deep_copy_contract(event)
        self._activity_sequences[tenant_id] = sequence + 1
        return _deep_copy_contract(event)

    def list_operational_activity(
        self,
        tenant_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = MAX_ACTIVITY_LIMIT,
    ) -> tuple[OperationalActivityEvent, ...]:
        """Bounded retrieval of a tenant's activity in ascending sequence order.

        Returns events strictly after the optional ``after_sequence``
        cursor, at most ``limit`` events (bounded by MAX_ACTIVITY_LIMIT),
        in ascending sequence order (append order within one tenant). The
        returned tuple is immutable.
        """
        events = [
            event for (owner, _), event in self._operational_activity.items() if owner == tenant_id
        ]
        events.sort(key=lambda event: event.sequence)
        cursor = after_sequence if after_sequence is not None else -1
        selected = tuple(event for event in events if event.sequence > cursor)[:limit]
        return tuple(_deep_copy_contract(event) for event in selected)

    def latest_activity_sequence(self, tenant_id: str) -> int:
        """The tenant's latest sequence, or -1 when the tenant has no activity.

        -1 is the natural empty-feed sentinel: the first appended event
        receives sequence 0, and ``after_sequence=-1`` retrieves every
        event of the tenant.
        """
        return self._activity_sequences.get(tenant_id, 0) - 1
