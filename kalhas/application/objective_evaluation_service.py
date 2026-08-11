"""Deterministic scenario evaluation-profile declaration service (Phase 23).

A scenario evaluation profile is the immutable, tenant-scoped
declarative connection between every objective of a stored
``ScenarioSpec`` and exactly one scenario metric, with the
authoritative objective/metric snapshots (direction, target, weight,
metric unit) copied exclusively from the stored scenario - never from
client input. Declaration, storage, and provenance only: nothing here
evaluates an observed value, aggregates observations, produces
outcomes, scores, ranks, or recommends, and no domain-pack code is
ever loaded, imported, instantiated, invoked, or interpreted.

The caller supplies only ``objective_id``, ``metric_id``,
``reach_tolerance``, and ``normalization_scale`` per binding, plus the
deterministic ``declared_at``. The profile bindings are canonicalized
into the exact authoritative ``ScenarioSpec.objectives`` order -
caller binding order never affects the artifact. Every scenario
objective must be bound exactly once; every referenced objective and
metric must exist exactly once in the stored scenario. A ``reach``
objective without an authoritative target cannot participate. The
profile must be declared before any world is compiled for the
tenant/scenario, exactly one profile may exist per tenant/scenario,
and there is no update, replace, delete, or repair surface.

The profile identifier is independently derived from the canonical
tenant/scenario/scenario-hash/schema identity - never from the content
hash - and the content hash covers the complete canonical profile
serialization excluding ``content_hash`` itself. ``declared_at`` is
the deterministic caller-supplied timestamp and is included in content
hashing; no wall clock is ever read.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileDeclarationAfterCompilationError,
    EvaluationProfileIncompleteCoverageError,
    EvaluationProfileInvalidScaleError,
    EvaluationProfileMetricNotFoundError,
    EvaluationProfileObjectiveNotFoundError,
    EvaluationProfileReachTargetRequiredError,
    EvaluationProfileToleranceRuleError,
    EvaluationProfileValidationError,
)
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
    verify_evaluation_profile_identity,
)
from kalhas.contracts.v1.objective_evaluation import (
    ObjectiveMetricBinding,
    ScenarioEvaluationProfile,
    _is_exact_finite_numeric,
)
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection, ScenarioSpec
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, MetricDefinition

_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


@dataclass(frozen=True)
class ObjectiveMetricBindingDraft:
    """The caller-owned values of one objective-to-metric binding.

    Only ``objective_id``, ``metric_id``, ``reach_tolerance``, and
    ``normalization_scale`` are caller-owned; every authoritative field
    is copied by the service from the stored scenario.
    """

    objective_id: str
    metric_id: str
    reach_tolerance: float | None
    normalization_scale: float


def _resolve_objectives(
    scenario: ScenarioSpec,
) -> dict[str, Objective]:
    """Index the scenario objectives by identifier; reject duplicates.

    Scenario objectives are authoritative and complete coverage
    requires every objective bound exactly once; duplicate objective
    identifiers in the stored scenario make coverage impossible to
    define.
    """
    by_identifier: dict[str, Objective] = {}
    for objective in scenario.objectives:
        if objective.identifier in by_identifier:
            raise EvaluationProfileIncompleteCoverageError(
                scenario.identifier,
                reason="scenario declares duplicate objective identifiers",
            )
        by_identifier[objective.identifier] = objective
    return by_identifier


def _resolve_metrics(scenario: ScenarioSpec) -> dict[str, MetricDefinition]:
    """Index the scenario metrics by identifier; reject duplicates."""
    by_identifier: dict[str, MetricDefinition] = {}
    for metric in scenario.metrics:
        if metric.identifier in by_identifier:
            raise EvaluationProfileMetricNotFoundError(
                scenario.identifier,
                metric.identifier,
                reason="scenario declares duplicate metric identifiers",
            )
        by_identifier[metric.identifier] = metric
    return by_identifier


def _validate_draft_values(
    scenario: ScenarioSpec,
    draft: ObjectiveMetricBindingDraft,
    objective: Objective,
) -> None:
    """Validate the caller-owned binding values against the objective.

    The normalization scale must be exact finite numeric and strictly
    positive; the reach tolerance must be exact finite numeric and
    non-negative, present exactly for ``reach`` objectives and
    forbidden for ``minimize``/``maximize``.
    """
    if not _is_exact_finite_numeric(draft.normalization_scale):
        raise EvaluationProfileInvalidScaleError(
            scenario.identifier,
            draft.objective_id,
            reason="normalization scale must be an exact finite numeric value",
        )
    if draft.normalization_scale <= 0.0:
        raise EvaluationProfileInvalidScaleError(
            scenario.identifier,
            draft.objective_id,
            reason="normalization scale must be strictly positive",
        )
    if objective.direction is ObjectiveDirection.REACH:
        if objective.target is None:
            raise EvaluationProfileReachTargetRequiredError(
                scenario.identifier,
                draft.objective_id,
                reason="reach objective has no authoritative target in the stored scenario",
            )
        if draft.reach_tolerance is None:
            raise EvaluationProfileToleranceRuleError(
                scenario.identifier,
                draft.objective_id,
                reason="reach objective requires a reach tolerance",
            )
        if not _is_exact_finite_numeric(draft.reach_tolerance):
            raise EvaluationProfileToleranceRuleError(
                scenario.identifier,
                draft.objective_id,
                reason="reach tolerance must be an exact finite numeric value",
            )
        if draft.reach_tolerance < 0.0:
            raise EvaluationProfileToleranceRuleError(
                scenario.identifier,
                draft.objective_id,
                reason="reach tolerance must be non-negative",
            )
    elif draft.reach_tolerance is not None:
        raise EvaluationProfileToleranceRuleError(
            scenario.identifier,
            draft.objective_id,
            reason="reach tolerance is forbidden for minimize and maximize objectives",
        )


def declare_scenario_evaluation_profile(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    bindings: tuple[ObjectiveMetricBindingDraft, ...],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> ScenarioEvaluationProfile:
    """Declare the immutable evaluation profile; raises typed errors.

    The tenant must own the scenario (typed 404 otherwise). The profile
    must be declared before any world has been compiled for the
    tenant/scenario (typed 409 otherwise). Every scenario objective
    must be bound exactly once and every referenced objective and
    metric must exist exactly once in the stored scenario (typed 422
    otherwise); a ``reach`` objective without an authoritative target
    cannot participate (typed 422). Bindings are canonicalized into the
    exact authoritative ``ScenarioSpec.objectives`` order. A duplicate
    declaration raises a typed 409 and never overwrites the original.
    The profile identifier is independently derived from the canonical
    tenant/scenario/scenario-hash/schema identity and the content hash
    covers the complete canonical profile excluding ``content_hash``
    itself. Nothing is evaluated, aggregated, scored, ranked, or
    recommended, and no domain pack is ever loaded or invoked.
    """
    if metadata is None:
        metadata = {}
    scenario = store.get_scenario(tenant_id, scenario_id)
    if store.has_compiled_worlds_for_scenario(tenant_id, scenario_id):
        raise EvaluationProfileDeclarationAfterCompilationError(tenant_id, scenario_id)

    objectives_by_id = _resolve_objectives(scenario)
    metrics_by_id = _resolve_metrics(scenario)
    if not objectives_by_id:
        raise EvaluationProfileIncompleteCoverageError(
            scenario.identifier,
            reason="scenario declares no objectives",
        )

    drafts_by_objective: dict[str, ObjectiveMetricBindingDraft] = {}
    for draft in bindings:
        objective = objectives_by_id.get(draft.objective_id)
        if objective is None:
            raise EvaluationProfileObjectiveNotFoundError(
                scenario.identifier,
                draft.objective_id,
                reason="objective does not exist in the stored scenario",
            )
        if draft.objective_id in drafts_by_objective:
            raise EvaluationProfileIncompleteCoverageError(
                scenario.identifier,
                reason=f"objective {draft.objective_id!r} is bound more than once",
            )
        if draft.metric_id not in metrics_by_id:
            raise EvaluationProfileMetricNotFoundError(
                scenario.identifier,
                draft.metric_id,
                reason="metric does not exist in the stored scenario",
            )
        _validate_draft_values(scenario, draft, objective)
        drafts_by_objective[draft.objective_id] = draft
    if set(drafts_by_objective) != set(objectives_by_id):
        raise EvaluationProfileIncompleteCoverageError(
            scenario.identifier,
            reason="binding set does not cover every scenario objective exactly once",
        )

    snapshot_hash = scenario_content_hash(scenario)
    bindings_tuple = tuple(
        _build_binding(scenario, objectives_by_id, metrics_by_id, drafts_by_objective, objective)
        for objective in scenario.objectives
    )
    try:
        profile = ScenarioEvaluationProfile(
            identifier=evaluation_profile_identifier(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                scenario_content_hash_value=snapshot_hash,
            ),
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            scenario_content_hash=snapshot_hash,
            bindings=bindings_tuple,
            content_hash=_PLACEHOLDER_HASH,
            declared_at=declared_at,
            metadata=metadata,
        )
    except ValidationError:
        raise EvaluationProfileValidationError(
            scenario_id,
            reason="declared profile violates its contract",
        ) from None
    digest = evaluation_profile_content_hash(profile)
    finalized = profile.model_copy(update={"content_hash": digest})
    store.put_evaluation_profile(tenant_id, scenario_id, finalized)
    return finalized


def _build_binding(
    scenario: ScenarioSpec,
    objectives_by_id: dict[str, Objective],
    metrics_by_id: dict[str, MetricDefinition],
    drafts_by_objective: dict[str, ObjectiveMetricBindingDraft],
    objective: Objective,
) -> ObjectiveMetricBinding:
    """Build one binding snapshot in the exact scenario objective order.

    Direction, target, weight, and metric unit are copied from the
    stored scenario records - never from client input. A non-finite
    authoritative target cannot be snapshotted and rejects the
    declaration.
    """
    draft = drafts_by_objective[objective.identifier]
    metric = metrics_by_id[draft.metric_id]
    if objective.target is not None and not _is_exact_finite_numeric(objective.target):
        raise EvaluationProfileValidationError(
            scenario.identifier,
            reason=f"objective {objective.identifier!r} carries a non-finite target",
        )
    return ObjectiveMetricBinding(
        objective_id=objective.identifier,
        metric_id=draft.metric_id,
        direction=objective.direction.value,
        target=objective.target,
        weight=objective.weight,
        metric_unit=metric.unit,
        reach_tolerance=draft.reach_tolerance,
        normalization_scale=draft.normalization_scale,
    )


def get_scenario_evaluation_profile(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
) -> ScenarioEvaluationProfile:
    """Fetch one stored evaluation profile; raises EvaluationProfileNotFoundError.

    The store revalidates the strict contract and the deterministic
    identity of the stored record on every read before any copy crosses
    the store boundary; this getter independently re-verifies ownership,
    the deterministic profile identifier, and the profile content hash
    before returning, so a corrupted stored record can never be served.
    """
    profile = store.get_evaluation_profile(tenant_id, scenario_id)
    verify_evaluation_profile_identity(profile, tenant_id=tenant_id, scenario_id=scenario_id)
    return profile
