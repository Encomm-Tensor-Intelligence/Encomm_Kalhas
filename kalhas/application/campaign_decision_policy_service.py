"""Deterministic campaign decision policy declaration service (KALHAS).

Declares and verifies the immutable stored ``CampaignDecisionPolicy``
of one COMPLETE runtime-3.0.0 campaign. This is the declaration
boundary only: caller-safe request values, authoritative construction,
deterministic verification, and one-policy-per-campaign persistence.
No routes, no comparison derivation, no brief derivation, no paired
statistics, no Pareto, regret, or minimax, no registration, and no
schemas exist here.

The caller owns only the declaration draft: the target-requirement
mode with its probability rules, the exact-int minimum sample count,
the finite non-negative tie tolerance, the hard-gate flag, the
deterministic ``declared_at`` timestamp, and finite JSON-compatible
metadata. Every authoritative identity and snapshot field - the
campaign, scenario, world-version, and evaluation-profile identities
with their content hashes, the fixed algorithm identifier, the
objective-weight snapshots in the exact authoritative objective order
(never sorted, never normalized, all-zero weights preserved), and the
fixed tail alpha ``0.95`` (callers cannot select another alpha) - is
copied exclusively from verified stored immutable records, never from
the caller.

Declaration is deterministic and atomic, in this exact order:

1. load the tenant-scoped ``CampaignSpec`` (unknown or foreign
   campaigns raise the established typed not-found error);
2. load the ``CampaignStatus`` and require exactly COMPLETE (any other
   state raises the established :class:`CampaignNotCompleteError`
   before any downstream work);
3. verify the recorded campaign/runtime context is the accepted
   realization runtime using the complete recorded run-plan tuple -
   empty, mixed, or foreign runtimes raise the established
   :class:`UnsupportedRuntimeVersionError`;
4. load and independently verify the campaign's immutable world and
   manifest (missing records or any world-verification failure raises
   the typed policy integrity error - nothing is repaired);
5. require campaign scenario/world identity consistency;
6. load the authoritative stored ``ScenarioSpec``;
7. recompute the scenario content identity and verify the world's
   embedded scenario snapshot agrees exactly;
8. require an evaluation profile embedded in the verified world (the
   established ``extract_world_catalog`` helper strictly parses and
   independently identity-verifies the embedded snapshot - bindings,
   direction/target/weight, hashes, scenario agreement), then load and
   independently verify the stored ``ScenarioEvaluationProfile``, and
   require exact canonical equality between the stored and embedded
   profiles (``model_dump(mode="json")``) - missing, malformed,
   absent, self-integrity-failing, or mismatched profiles raise the
   typed policy integrity error, and neither snapshot is ever
   preferred, merged, or repaired;
9. require exact campaign/scenario/world/profile tenant and snapshot
   agreement;
10. verify the profile bindings exactly cover the authoritative
    scenario objectives in ``ScenarioSpec.objectives`` order;
11. verify every binding snapshot against the authoritative objective
    (direction, target, weight);
12. validate the declared target policy against the targeted
    objectives (a targeted objective is one with ``target != None``;
    global mode applies its single threshold to every targeted
    objective and is allowed when there are zero targeted objectives -
    feasibility is then vacuous; per_objective mode must cover every
    targeted objective exactly once in the exact authoritative
    relative order, and requirements for optimization-only objectives
    are forbidden - missing, duplicate, unknown, additional, or
    reordered requirements raise
    :class:`CampaignDecisionPolicyValidationError`; caller mistakes
    are never silently sorted into validity);
13. copy the authoritative identities, hashes, objective weights, and
    the fixed alpha;
14. build the complete policy with a placeholder hash;
15. compute the deterministic content hash;
16. finalize and strictly revalidate the artifact;
17. persist once, only after every validation succeeds (a duplicate
    raises :class:`CampaignDecisionPolicyAlreadyExistsError` and never
    overwrites the original);
18. return a detached immutable copy.

The service never reads the wall clock, generates timestamps, samples,
executes, replays, derives outcomes, records operational activity, or
mutates any input. Verified retrieval
(``get_verified_campaign_decision_policy``) strictly revalidates the
stored record from serialized data, independently recomputes the
deterministic identifier and the complete content hash, and never
requires the campaign to still be COMPLETE; corrupt stored state is
rejected with the typed integrity error and never repaired, and no raw
validation diagnostic ever escapes.

The module is pure application logic: no FastAPI, no NEXUS/LEGION
imports, no domain-pack loading, no wall clock, randomness, network,
providers, filesystem, or database access. Public messages never
expose internal reasons, hashes, values, targets, thresholds, or
validator diagnostics.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from kalhas.application.campaign_decision_errors import (
    CampaignDecisionPolicyIntegrityError,
    CampaignDecisionPolicyValidationError,
)
from kalhas.application.campaign_decision_identity import (
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    ScenarioNotFoundError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    verify_campaign_decision_policy_identity,
)
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileIntegrityError,
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_identity import (
    scenario_content_hash,
    verify_evaluation_profile_identity,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionPolicy,
    ObjectiveTargetRequirement,
    ObjectiveWeightSnapshot,
    _contains_non_finite,
    _is_exact_finite_numeric,
    _is_probability,
)
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import Objective, ScenarioSpec
from kalhas.contracts.v1.shared import SCHEMA_VERSION, AwareDatetime, JsonValue
from kalhas.contracts.v1.world import WorldManifest, WorldVersion

_PLACEHOLDER_HASH = "0" * 64

#: The fixed CVaR tail alpha; callers cannot select another alpha.
_FIXED_TAIL_ALPHA: Literal[0.95] = 0.95  # type: ignore[valid-type]

#: The fixed accepted algorithm identifier of the stored policy.
_ALGORITHM_IDENTIFIER: Literal["feasibility-pareto-minimax-regret-v1"] = (
    "feasibility-pareto-minimax-regret-v1"
)


@dataclass(frozen=True, kw_only=True)
class CampaignDecisionPolicyDeclarationDraft:
    """The caller-owned values of one policy declaration.

    Only the target-requirement mode and rules, the exact-int minimum
    sample count, the finite non-negative tie tolerance, the exact
    hard-gate bool, the deterministic ``declared_at`` timestamp, and
    finite JSON-compatible metadata are caller-owned. Every
    authoritative identity, hash, weight snapshot, the algorithm
    identifier, and the fixed tail alpha are copied by the service from
    verified stored immutable records; the caller can never provide
    them. The four decision rules (``minimum_sample_count``,
    ``tie_tolerance``, ``all_targeted_objectives_are_hard_gates``,
    ``declared_at``) are explicit required fields - no silent defaults.
    The per-objective requirements must be an actual immutable tuple;
    a mutable direct-service list is never silently converted or
    sorted.
    """

    target_requirement_mode: Literal["global", "per_objective"]
    minimum_sample_count: int
    tie_tolerance: float
    all_targeted_objectives_are_hard_gates: bool
    declared_at: AwareDatetime
    minimum_target_achievement_probability: float | None = None
    objective_target_requirements: tuple[ObjectiveTargetRequirement, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)


def _reject(tenant_id: str, campaign_id: str, reason: str) -> CampaignDecisionPolicyIntegrityError:
    """A generic, safe policy integrity error with an internal diagnostic reason."""
    return CampaignDecisionPolicyIntegrityError(tenant_id, campaign_id, reason)


def _validate_metadata_tree(value: object) -> None:
    """Require a genuine recursively JSON-compatible tree; raises ``ValueError``.

    Dictionary keys must be exact strings; values may only be ``str``,
    exact ``int``, finite exact ``float``, exact ``bool``, ``None``,
    ``list``, or ``dict``, validated recursively. ``Decimal``, numeric
    subclasses, tuples, sets, arbitrary objects, NaN, and Infinity are
    rejected. The caller mapping is never mutated.
    """
    if value is None:
        return
    if type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("metadata must contain only finite JSON-compatible numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_metadata_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("metadata dictionary keys must be strings")
            _validate_metadata_tree(item)
        return
    raise ValueError("metadata must contain only JSON-compatible values")


def _validate_draft(
    tenant_id: str,
    campaign_id: str,
    draft: CampaignDecisionPolicyDeclarationDraft,
) -> None:
    """Validate every caller-owned draft rule; raises the typed validation error.

    Enforces the exact global/per-objective XOR, exact built-in numeric
    kinds before any coercion (booleans, strings, ``Decimal``, ``None``,
    containers, non-finite floats, and unrepresentable huge integers
    are rejected), the inclusive probability band ``[0.0, 1.0]``, the
    exact-int ``minimum_sample_count >= 1``, the finite non-negative
    ``tie_tolerance``, the exact bool hard-gate flag (``0``, ``1``,
    ``0.0``, ``1.0``, strings, ``Decimal``, ``None``, containers, and
    arbitrary truthy/falsy objects are rejected), an actual immutable
    tuple of strict requirements, the timezone-aware declared
    timestamp, and a genuine JSON-compatible metadata tree. Nothing is
    clipped, repaired, normalized, sorted, converted, or mutated.
    """

    def invalid(reason: str) -> CampaignDecisionPolicyValidationError:
        return CampaignDecisionPolicyValidationError(tenant_id, campaign_id, reason)

    if draft.target_requirement_mode not in ("global", "per_objective"):
        raise invalid("target_requirement_mode must be 'global' or 'per_objective'")
    if type(draft.minimum_sample_count) is not int:
        raise invalid("minimum_sample_count must be an exact int")
    if draft.minimum_sample_count < 1:
        raise invalid("minimum_sample_count must be at least 1")
    if not _is_exact_finite_numeric(draft.tie_tolerance):
        raise invalid("tie_tolerance must be an exact finite number")
    if draft.tie_tolerance < 0.0:
        raise invalid("tie_tolerance must be non-negative")
    if type(draft.all_targeted_objectives_are_hard_gates) is not bool:
        raise invalid("all_targeted_objectives_are_hard_gates must be an exact bool")
    if not isinstance(draft.declared_at, datetime):
        raise invalid("declared_at must be a timezone-aware datetime")
    if draft.declared_at.tzinfo is None or draft.declared_at.utcoffset() is None:
        raise invalid("declared_at must be a timezone-aware datetime")
    if type(draft.objective_target_requirements) is not tuple:
        raise invalid("objective_target_requirements must be an immutable tuple")
    if not all(
        isinstance(requirement, ObjectiveTargetRequirement)
        for requirement in draft.objective_target_requirements
    ):
        raise invalid(
            "every per-objective target requirement must be a strict ObjectiveTargetRequirement"
        )
    for requirement in draft.objective_target_requirements:
        if not _is_probability(requirement.minimum_target_achievement_probability):
            raise invalid("every per-objective requirement probability must be within [0.0, 1.0]")
    requirement_ids = [
        requirement.objective_id for requirement in draft.objective_target_requirements
    ]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise invalid("per-objective target requirement objective identifiers must be unique")
    if type(draft.metadata) is not dict:
        raise invalid("metadata must be a JSON-compatible object")
    try:
        _validate_metadata_tree(draft.metadata)
    except ValueError as exc:
        raise invalid("metadata must contain only JSON-compatible values") from exc
    if draft.target_requirement_mode == "global":
        probability = draft.minimum_target_achievement_probability
        if probability is None:
            raise invalid("global mode requires a global minimum target-achievement probability")
        if draft.objective_target_requirements:
            raise invalid("global mode forbids per-objective target requirements")
        if not _is_exact_finite_numeric(probability) or not _is_probability(float(probability)):
            raise invalid(
                "minimum_target_achievement_probability must be an exact finite number "
                "within [0.0, 1.0]"
            )
    else:
        if draft.minimum_target_achievement_probability is not None:
            raise invalid("per_objective mode forbids a global probability")
        if not draft.objective_target_requirements:
            raise invalid("per_objective mode requires at least one target requirement")


def _validate_target_coverage(
    tenant_id: str,
    campaign_id: str,
    draft: CampaignDecisionPolicyDeclarationDraft,
    targeted_objectives: list[Objective],
) -> None:
    """Validate the declared target policy against the targeted objectives.

    Global mode applies its single threshold to every targeted
    objective and is allowed when there are zero targeted objectives
    (feasibility is then vacuous). Per-objective mode must cover every
    targeted objective exactly once in the exact authoritative relative
    order; missing, duplicate, unknown, additional, or reordered
    requirements - and requirements for optimization-only objectives -
    are rejected with the typed validation error. Caller mistakes are
    never silently sorted into validity.
    """
    if draft.target_requirement_mode == "global":
        return
    targeted_ids = [objective.identifier for objective in targeted_objectives]
    requirement_ids = [
        requirement.objective_id for requirement in draft.objective_target_requirements
    ]
    if requirement_ids != targeted_ids:
        if len(requirement_ids) == len(targeted_ids) and set(requirement_ids) == set(targeted_ids):
            raise CampaignDecisionPolicyValidationError(
                tenant_id,
                campaign_id,
                reason=(
                    "per-objective target requirements must follow the exact "
                    "authoritative targeted-objective order"
                ),
            )
        raise CampaignDecisionPolicyValidationError(
            tenant_id,
            campaign_id,
            reason=(
                "per-objective target requirements must cover exactly the targeted "
                "objectives, each exactly once, in the authoritative order"
            ),
        )


def _verify_world_context(
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    store: InMemoryScenarioStore,
) -> tuple[WorldVersion, WorldManifest]:
    """Load and independently verify the campaign's immutable world and manifest."""
    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, "campaign world record missing") from exc
    try:
        verify_world_snapshot(world, manifest)
    except (
        WorldSnapshotIntegrityError,
        ValidationError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        IndexError,
        ArithmeticError,
    ) as exc:
        raise _reject(tenant_id, campaign_id, "campaign world verification failed") from exc
    return world, manifest


def _verify_scenario_context(
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    store: InMemoryScenarioStore,
) -> ScenarioSpec:
    """Load the stored scenario and verify the scenario content identity.

    Recomputes the scenario content hash from the stored record and
    verifies the world's embedded scenario snapshot agrees exactly
    (identifier and content identity); any inconsistency is corruption
    of the campaign's recorded context and raises the typed integrity
    error - nothing is repaired.
    """
    if campaign.scenario_id != world.source_scenario_id:
        raise _reject(tenant_id, campaign_id, "campaign scenario/world identity mismatch")
    try:
        scenario = store.get_scenario(tenant_id, campaign.scenario_id)
    except ScenarioNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, "campaign scenario record missing") from exc
    if scenario.tenant_id != tenant_id:
        raise _reject(tenant_id, campaign_id, "campaign scenario tenant mismatch")
    embedded_raw = world.world.get("scenario")
    if not isinstance(embedded_raw, dict):
        raise _reject(tenant_id, campaign_id, "embedded campaign scenario is malformed")
    try:
        embedded = ScenarioSpec.model_validate(embedded_raw)
    except ValidationError as exc:
        raise _reject(tenant_id, campaign_id, "embedded campaign scenario is malformed") from exc
    if embedded.identifier != scenario.identifier:
        raise _reject(tenant_id, campaign_id, "campaign scenario identity mismatch")
    if scenario_content_hash(embedded) != scenario_content_hash(scenario):
        raise _reject(tenant_id, campaign_id, "campaign scenario content identity mismatch")
    return scenario


def _verify_profile_context(
    tenant_id: str,
    campaign_id: str,
    scenario: ScenarioSpec,
    world: WorldVersion,
    store: InMemoryScenarioStore,
) -> ScenarioEvaluationProfile:
    """Verify the world-embedded and stored evaluation profiles agree exactly.

    Requires an evaluation profile embedded in the verified world (the
    established ``extract_world_catalog`` helper strictly parses and
    independently identity-verifies the embedded snapshot - bindings,
    direction/target/weight, hashes, and scenario agreement; a missing
    or malformed embedded profile raises the typed integrity error).
    The stored record is strictly revalidated and identity/hash
    verified by the store on read and independently re-verified here,
    then required to agree exactly with the campaign's scenario
    snapshot (tenant, scenario identity, and scenario content hash) and
    to be canonically equal to the embedded snapshot
    (``model_dump(mode="json")`` equality - the established exact
    canonical-equality pattern; neither snapshot is preferred, merged,
    or repaired). Only after exact equality may the policy bind the
    profile identity and hash. The bindings must cover the
    authoritative scenario objectives exactly once in exact
    ``ScenarioSpec.objectives`` order and snapshot every objective's
    direction, target, and weight exactly. Any mismatch is corruption
    of the campaign's recorded context and raises the typed integrity
    error.
    """
    try:
        catalog = extract_world_catalog(world)
    except (
        WorldSnapshotIntegrityError,
        ValidationError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        IndexError,
    ) as exc:
        raise _reject(tenant_id, campaign_id, "embedded evaluation profile malformed") from exc
    embedded = catalog.evaluation_profile
    if embedded is None:
        raise _reject(tenant_id, campaign_id, "embedded evaluation profile missing")
    try:
        stored = store.get_evaluation_profile(tenant_id, scenario.identifier)
    except EvaluationProfileNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, "stored evaluation profile missing") from exc
    except EvaluationProfileIntegrityError as exc:
        raise _reject(
            tenant_id,
            campaign_id,
            getattr(exc, "reason", None) or "stored evaluation profile integrity failed",
        ) from exc
    try:
        verify_evaluation_profile_identity(
            stored, tenant_id=tenant_id, scenario_id=scenario.identifier
        )
    except EvaluationProfileIntegrityError as exc:
        raise _reject(
            tenant_id,
            campaign_id,
            getattr(exc, "reason", None) or "stored evaluation profile identity failed",
        ) from exc
    if stored.tenant_id != tenant_id or stored.scenario_id != scenario.identifier:
        raise _reject(tenant_id, campaign_id, "campaign profile ownership mismatch")
    snapshot_hash = scenario_content_hash(scenario)
    if stored.scenario_content_hash != snapshot_hash:
        raise _reject(tenant_id, campaign_id, "campaign profile snapshot mismatch")
    if stored.model_dump(mode="json") != embedded.model_dump(mode="json"):
        raise _reject(tenant_id, campaign_id, "stored and embedded evaluation profile mismatch")
    binding_ids = [binding.objective_id for binding in stored.bindings]
    objective_ids = [objective.identifier for objective in scenario.objectives]
    if binding_ids != objective_ids:
        raise _reject(tenant_id, campaign_id, "profile binding coverage mismatch")
    for binding, objective in zip(stored.bindings, scenario.objectives, strict=True):
        if binding.direction != objective.direction.value:
            raise _reject(tenant_id, campaign_id, "profile binding direction mismatch")
        if binding.target != objective.target:
            raise _reject(tenant_id, campaign_id, "profile binding target mismatch")
        if binding.weight != objective.weight:
            raise _reject(tenant_id, campaign_id, "profile binding weight mismatch")
    return stored


def _strictly_revalidate_policy(policy: CampaignDecisionPolicy) -> None:
    """Strictly revalidate a policy from its serialized data; raises ``ValueError``.

    Re-runs every field rule and nested contract validator over the
    Python-mode serialization, so a validator-bypassed nested value is
    rejected before any field of the artifact is trusted. The metadata
    non-finite rule is enforced explicitly as well. The revalidated
    object is discarded; the supplied artifact is never replaced,
    normalized, repaired, or mutated.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        serialized = policy.model_dump(mode="python")
    revalidated = CampaignDecisionPolicy.model_validate(serialized, strict=True)
    if _contains_non_finite(revalidated.metadata):
        raise ValueError("metadata contains non-finite floats")


def _build_policy(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario: ScenarioSpec,
    world: WorldVersion,
    profile: ScenarioEvaluationProfile,
    draft: CampaignDecisionPolicyDeclarationDraft,
) -> CampaignDecisionPolicy:
    """Build the complete policy with copied authoritative values.

    Every identity, hash, weight snapshot (in the exact authoritative
    objective order, never sorted or normalized), the fixed algorithm
    identifier, and the fixed tail alpha are copied from the verified
    stored records; the caller-owned declaration values come from the
    draft. The policy is built with a placeholder hash, then the
    deterministic content hash is computed and the artifact finalized.
    """
    snapshot_hash = scenario_content_hash(scenario)
    placeholder = CampaignDecisionPolicy(
        identifier=campaign_decision_policy_identifier(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=scenario.identifier,
            world_version_id=world.identifier,
            evaluation_profile_id=profile.identifier,
            schema_version=SCHEMA_VERSION,
        ),
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario.identifier,
        scenario_content_hash=snapshot_hash,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        evaluation_profile_id=profile.identifier,
        evaluation_profile_content_hash=profile.content_hash,
        algorithm_identifier=_ALGORITHM_IDENTIFIER,
        target_requirement_mode=draft.target_requirement_mode,
        minimum_target_achievement_probability=draft.minimum_target_achievement_probability,
        objective_target_requirements=draft.objective_target_requirements,
        objective_weight_snapshots=tuple(
            ObjectiveWeightSnapshot(objective_id=objective.identifier, weight=objective.weight)
            for objective in scenario.objectives
        ),
        minimum_sample_count=draft.minimum_sample_count,
        tie_tolerance=draft.tie_tolerance,
        all_targeted_objectives_are_hard_gates=draft.all_targeted_objectives_are_hard_gates,
        tail_alpha=_FIXED_TAIL_ALPHA,
        content_hash=_PLACEHOLDER_HASH,
        declared_at=draft.declared_at,
        metadata=draft.metadata,
    )
    digest = campaign_decision_policy_content_hash(placeholder)
    return placeholder.model_copy(update={"content_hash": digest})


def declare_campaign_decision_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    draft: CampaignDecisionPolicyDeclarationDraft,
) -> CampaignDecisionPolicy:
    """Declare the immutable campaign decision policy; raises typed errors.

    Runs the exact deterministic declaration flow (campaign, COMPLETE
    status, recorded runtime, world/manifest verification, scenario
    content identity, stored-vs-embedded evaluation-profile
    verification with exact canonical equality, tenant/snapshot
    agreement, binding coverage and snapshot checks, declared target
    coverage, authoritative construction, deterministic hashing, strict
    final revalidation, and a single atomic persist). A duplicate
    declaration raises the typed already-exists error and never
    overwrites the original; any failed declaration causes zero writes.
    The returned policy is a detached immutable deep copy; nothing is
    executed, replayed, derived, sampled, or recorded.
    """
    _validate_draft(tenant_id, campaign_id, draft)
    # The tenant-scoped campaign lookup raises the typed not-found error
    # (404) for unknown or foreign campaigns before the status gate.
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)
    try:
        plans = store.get_run_plans(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise UnsupportedRuntimeVersionError(
            "(none)", operation="campaign decision policy declaration"
        ) from exc
    if not plans:
        raise UnsupportedRuntimeVersionError(
            "(none)", operation="campaign decision policy declaration"
        )
    for plan in plans:
        if plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="campaign decision policy declaration"
            )

    world, _manifest = _verify_world_context(tenant_id, campaign_id, campaign, store)
    scenario = _verify_scenario_context(tenant_id, campaign_id, campaign, world, store)
    profile = _verify_profile_context(tenant_id, campaign_id, scenario, world, store)

    targeted_objectives = [
        objective for objective in scenario.objectives if objective.target is not None
    ]
    _validate_target_coverage(tenant_id, campaign_id, draft, targeted_objectives)

    try:
        finalized = _build_policy(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario=scenario,
            world=world,
            profile=profile,
            draft=draft,
        )
        _strictly_revalidate_policy(finalized)
    except (ValidationError, TypeError, AttributeError, ValueError) as exc:
        raise CampaignDecisionPolicyValidationError(
            tenant_id, campaign_id, reason="declared policy violates its contract"
        ) from exc
    verify_campaign_decision_policy_identity(
        finalized, tenant_id=tenant_id, campaign_id=campaign_id
    )
    store.put_campaign_decision_policy(tenant_id, campaign_id, finalized)
    return finalized.model_copy(deep=True)


def get_verified_campaign_decision_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
) -> CampaignDecisionPolicy:
    """Fetch and independently verify one stored campaign decision policy.

    Retrieves by the exact ``(tenant_id, campaign_id)`` key; absent or
    foreign policies raise the typed not-found error, which is always
    preserved unchanged. The stored record is strictly revalidated from
    serialized data and its ownership, deterministic identifier, and
    complete content hash are independently recomputed on every read -
    a corrupted, forged, or validator-bypassed record raises the typed
    integrity error and is never served, repaired, overwritten, or
    silently accepted, and no raw ``pydantic.ValidationError``,
    ``TypeError``, ``ValueError``, or ``AttributeError`` diagnostic
    ever escapes the additional verification pass. The returned policy
    is a deep detached immutable copy. Retrieval never executes,
    replays, appends activity, consults the wall clock, or requires the
    campaign to still be COMPLETE.
    """
    policy = store.get_campaign_decision_policy(tenant_id, campaign_id)
    try:
        _strictly_revalidate_policy(policy)
        verify_campaign_decision_policy_identity(
            policy, tenant_id=tenant_id, campaign_id=campaign_id
        )
    except (ValidationError, TypeError, ValueError, AttributeError) as exc:
        raise CampaignDecisionPolicyIntegrityError(
            tenant_id,
            campaign_id,
            reason="stored campaign decision policy verification failed",
        ) from exc
    return policy


__all__ = [
    "CampaignDecisionPolicyDeclarationDraft",
    "declare_campaign_decision_policy",
    "get_verified_campaign_decision_policy",
]
