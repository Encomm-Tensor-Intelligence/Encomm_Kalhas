"""Deterministic adaptive-policy binding service (Phase 28, H28-S05).

Binds the closed adaptive-policy language of an untrusted
:class:`AdaptivePolicyDraft` to a complete immutable runtime-4
:class:`AdaptivePolicy` authority for one exactly-COMPILED campaign of one
verified compiled world. The draft carries logical action identifiers and
draft rules only; this service resolves them against immutable stored
authority - the campaign, scenario, compiled world and manifest, the stored
:class:`StrategyCandidate` set, the stored :class:`StrategyTrajectoryPlan`
collection, and the stored :class:`RuntimeObservationDeclaration` catalog -
and copies every authoritative identifier and hash from those verified stored
records, never from the caller. It then persists the completed policy exactly
once through the store's immutable no-overwrite surface and records no
operational activity.

Two application-local frozen authoring inputs are the only caller-owned data:
one logical *action-to-strategy* mapping and one *binding request* carrying the
stable ``policy_id``, the semantic ``policy_version``, the complete tuple of
action mappings, the deterministic timezone-aware ``bound_at``, and finite
JSON-compatible ``metadata``. ``AdaptivePolicyDraft.request_id`` is used only
as non-authoritative request correlation and is never treated as stored
world/strategy/policy provenance and never copied into policy metadata. The
binding request and mapping are not public contracts (ADR-004 D28-04 persists
only ``AdaptivePolicy`` among these roles).

Binding is deterministic and atomic: every preflight is completed before the
single store write, and no partial policy is ever visible. The service mirrors
the established immutable-authority authoring chain: exact-type and detached
strict revalidation of every input, verified stored authority, deterministic
identity/content-hash derivation, final detached strict revalidation with
independent identity verification, state initialization through the real
runtime-4 state initializer (the initial snapshot is discarded - it is not
independently persisted), and a single no-overwrite store write. Any failure
leaves adaptive-policy storage and operational activity unchanged.

The module is pure application logic: no FastAPI, no NEXUS/LEGION calls (the
real adapter never runs here; stored plans/strategies are consumed directly),
no wall clock, randomness, network, providers, filesystem, or database access,
no policy execution, observation events, replay, comparison, query, or API.
Public messages never expose internal reasons, hashes, identifiers, thresholds,
or validator diagnostics.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
    AdaptivePolicyIntegrityError,
)
from kalhas.application.adaptive_policy_identity import (
    adaptive_policy_content_hash,
    adaptive_policy_identifier,
    verify_adaptive_policy_identity,
)
from kalhas.application.adaptive_policy_state_machine import (
    initialize_adaptive_policy_state,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    ScenarioNotFoundError,
    TrajectoryPlansNotFoundError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.strategy_trajectory_service import (
    strategy_candidate_content_hash,
    trajectory_plan_content_hash,
    trajectory_plan_identifier,
)
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRule,
    BoundAdaptiveAction,
    ConditionComparisonLeaf,
    ConditionNode,
    ObservationBinding,
    TrajectoryPlanBinding,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.runtime_observation import RuntimeObservationDeclaration
from kalhas.contracts.v1.shared import SCHEMA_VERSION, AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.world import WorldVersion

_PLACEHOLDER_HASH = "0" * 64
_SEMANTIC_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"

#: The exact runtime literal of this authoring surface.
RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"


@dataclass(frozen=True, kw_only=True)
class ActionStrategyMapping:
    """One logical action-to-strategy mapping.

    Carries only the logical ``action_id`` and the exact stored
    ``strategy_candidate_id`` that action is bound to. Authority
    (identifier/hash) is never accepted here; the service copies it from the
    verified stored :class:`StrategyCandidate`.
    """

    action_id: str
    strategy_candidate_id: str


@dataclass(frozen=True, kw_only=True)
class AdaptivePolicyBindingRequest:
    """The application-local caller-owned binding request.

    The stable logical ``policy_id``, the semantic ``policy_version`` (which
    participates in the deterministic policy identity), the complete
    ``action_mappings`` tuple (one :class:`ActionStrategyMapping` per draft
    action, in canonical draft action order), the deterministic timezone-aware
    ``bound_at``, and finite JSON-compatible ``metadata``. No authoritative
    world/strategy/policy provenance is accepted here.
    """

    policy_id: str
    policy_version: str
    action_mappings: tuple[ActionStrategyMapping, ...]
    bound_at: AwareDatetime
    metadata: dict[str, JsonValue] = field(default_factory=dict)


def _validate_metadata_tree(value: object) -> None:
    """Require a genuine recursively JSON-compatible tree; raises ``ValueError``."""
    if value is None:
        return
    if type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not (value == value and value not in (float("inf"), float("-inf"))):
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


def _revalidate_pydantic_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one Pydantic artifact from its detached serialization.

    The artifact's Python payload is re-derived and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance (wrong-typed or non-finite raw values, booleans where strict
    integers belong, malformed condition trees, inconsistent fields, tampered
    nested rules) is rejected before any field of it is trusted. The
    revalidation result is discarded; nothing is repaired or mutated. A raw
    ``ValidationError``/``TypeError``/``AttributeError`` is converted to a
    ``ValueError`` that the caller maps to the safe typed error.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("input failed detached strict revalidation") from None


def _strictly_revalidate_inputs(
    draft: object,
    binding_request: object,
) -> None:
    """Validate every caller-owned input before any stored authority is trusted.

    Enforces exact types (subclasses rejected), detached strict revalidation
    of the draft, and scalar/nested validation of the binding request (the
    semantic policy version, the exact bounded tuple of exact action
    mappings, the timezone-aware bound timestamp, and the finite JSON tree
    metadata). Nothing is repaired, coerced, sorted, or normalized.
    """
    if type(draft) is not AdaptivePolicyDraft:
        raise ValueError("draft must be a valid AdaptivePolicyDraft")
    if type(binding_request) is not AdaptivePolicyBindingRequest:
        raise ValueError("binding_request must be a valid AdaptivePolicyBindingRequest")

    _revalidate_pydantic_detached(draft, AdaptivePolicyDraft)

    if not isinstance(binding_request.policy_id, str) or not binding_request.policy_id:
        raise ValueError("policy_id must be a non-empty string")
    if not isinstance(binding_request.policy_version, str) or not re.fullmatch(
        _SEMANTIC_VERSION_PATTERN, binding_request.policy_version
    ):
        raise ValueError("policy_version must be a semantic version")

    mappings = binding_request.action_mappings
    if not isinstance(mappings, tuple) or not all(
        type(mapping) is ActionStrategyMapping for mapping in mappings
    ):
        raise ValueError("action_mappings must be a tuple of exact ActionStrategyMapping")
    for mapping in mappings:
        if not isinstance(mapping.action_id, str) or not mapping.action_id:
            raise ValueError("action_id must be a non-empty string")
        if not isinstance(mapping.strategy_candidate_id, str) or not mapping.strategy_candidate_id:
            raise ValueError("strategy_candidate_id must be a non-empty string")

    bound_at = binding_request.bound_at
    if (
        not isinstance(bound_at, datetime)
        or bound_at.tzinfo is None
        or bound_at.utcoffset() is None
    ):
        raise ValueError("bound_at must be a timezone-aware datetime")

    if not isinstance(binding_request.metadata, dict):
        raise ValueError("metadata must be a JSON-compatible object")
    try:
        _validate_metadata_tree(binding_request.metadata)
    except ValueError as exc:
        raise ValueError("metadata must contain only finite JSON-compatible values") from exc

    del draft
    del binding_request


def _collect_condition_leaves(node: ConditionNode, into: list[ConditionComparisonLeaf]) -> None:
    """Recursively collect every comparison leaf of one closed condition tree."""
    if isinstance(node, ConditionComparisonLeaf):
        into.append(node)
        return
    for child in node.children:
        _collect_condition_leaves(child, into)


def _validate_mappings(
    draft: AdaptivePolicyDraft,
    request: AdaptivePolicyBindingRequest,
    *,
    tenant_id: str,
    campaign_id: str,
) -> None:
    """The mapping covers every draft action exactly once, in canonical order, injectively."""
    actions = draft.actions
    mappings = request.action_mappings
    if len(mappings) != len(actions):
        raise AdaptivePolicyBindingValidationError(
            tenant_id,
            campaign_id,
            reason="action mapping must cover every draft action exactly once",
        )
    for mapping, action_id in zip(mappings, actions, strict=True):
        if mapping.action_id != action_id:
            raise AdaptivePolicyBindingValidationError(
                tenant_id,
                campaign_id,
                reason="action mapping must equal the canonical draft action order",
            )
    strategy_ids = [mapping.strategy_candidate_id for mapping in mappings]
    if len(set(strategy_ids)) != len(strategy_ids):
        raise AdaptivePolicyBindingValidationError(
            tenant_id,
            campaign_id,
            reason="two logical actions cannot alias the same strategy",
        )


def _load_verified_world_authority(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
) -> WorldVersion:
    """Load and verify the tenant's exact scenario/world/manifest authority."""
    try:
        store.get_scenario(tenant_id, scenario_id)
    except ScenarioNotFoundError as exc:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="scenario authority missing"
        ) from exc
    try:
        world = store.get_world(tenant_id, world_version_id)
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError as exc:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="world authority missing"
        ) from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="world authority corrupt"
        ) from exc
    return world


def bind_adaptive_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    draft: AdaptivePolicyDraft,
    binding_request: AdaptivePolicyBindingRequest,
) -> AdaptivePolicy:
    """Bind an immutable runtime-4 :class:`AdaptivePolicy` for one COMPILED campaign.

    Runs the exact deterministic binding flow; the returned object is a
    detached immutable deep copy. A duplicate campaign locality raises the
    typed already-exists error and never overwrites the original; every other
    failure is atomic with zero writes and no activity event.
    """
    try:
        _strictly_revalidate_inputs(draft, binding_request)
    except ValueError as exc:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="draft invalid"
        ) from exc

    # 1. Campaign authority.
    try:
        campaign = store.get_campaign(tenant_id, campaign_id)
        status = store.get_campaign_status(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="campaign authority missing"
        ) from exc
    if status.state is not CampaignState.COMPILED:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="campaign must be exactly COMPILED"
        )

    scenario_id = campaign.scenario_id
    world = _load_verified_world_authority(
        store,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=campaign.world_version_id,
    )
    world_version_id = world.identifier
    if (
        scenario_id != campaign.scenario_id
        or world_version_id != campaign.world_version_id
        or world.source_scenario_id != scenario_id
        or world.tenant_id != tenant_id
    ):
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
        )
    world_content_hash = world.content_hash

    # 2. Action / strategy mapping.
    _validate_mappings(draft, binding_request, tenant_id=tenant_id, campaign_id=campaign_id)
    try:
        stored_candidates = store.get_strategy_candidates(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:  # campaign has no stored candidates
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="strategy candidates missing"
        ) from exc
    candidates_by_id: dict[str, StrategyCandidate] = {
        candidate.identifier: candidate for candidate in stored_candidates
    }
    mapped_strategies: list[StrategyCandidate] = []
    for mapping in binding_request.action_mappings:
        candidate = candidates_by_id.get(mapping.strategy_candidate_id)
        if candidate is None:
            raise AdaptivePolicyBindingValidationError(
                tenant_id, campaign_id, reason="unknown or foreign strategy"
            )
        if candidate.tenant_id != tenant_id:
            raise AdaptivePolicyBindingValidationError(
                tenant_id, campaign_id, reason="unknown or foreign strategy"
            )
        mapped_strategies.append(candidate)

    # 3. Trajectory plans.
    try:
        plans = store.get_strategy_trajectory_plans(tenant_id, campaign_id)
    except TrajectoryPlansNotFoundError as exc:  # campaign has no prepared plan collection
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="trajectory plans missing"
        ) from exc
    catalog = extract_world_catalog(world)
    embedded_models = {model.identifier: model for model in catalog.state_models}
    expected_state_models = set(embedded_models.keys())

    action_bindings: list[BoundAdaptiveAction] = []
    for mapping, strategy in zip(binding_request.action_mappings, mapped_strategies, strict=True):
        strategy_plans = [
            plan for plan in plans if plan.strategy_candidate_id == mapping.strategy_candidate_id
        ]
        plan_by_state_model: dict[str, StrategyTrajectoryPlan] = {}
        for plan in strategy_plans:
            plan_by_state_model.setdefault(plan.state_model_identifier, plan)
        if set(plan_by_state_model.keys()) != expected_state_models:
            raise AdaptivePolicyBindingValidationError(
                tenant_id,
                campaign_id,
                reason="incomplete or unequal state-model coverage",
            )
        ordered_state_models = sorted(plan_by_state_model.keys())
        trajectory_bindings: list[TrajectoryPlanBinding] = []
        for state_model_id in ordered_state_models:
            plan = plan_by_state_model[state_model_id]
            _verify_plan(
                plan,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                scenario_id=scenario_id,
                world=world,
                strategy=strategy,
                embedded_models=embedded_models,
            )
            trajectory_bindings.append(
                TrajectoryPlanBinding(
                    trajectory_plan_id=plan.identifier,
                    trajectory_plan_content_hash=plan.content_hash,
                    manifest_id=plan.manifest_id,
                    state_model_identifier=plan.state_model_identifier,
                    state_model_id=plan.state_model_id,
                    state_model_content_hash=plan.state_model_content_hash,
                )
            )
        action_bindings.append(
            BoundAdaptiveAction(
                action_id=mapping.action_id,
                strategy_candidate_id=strategy.identifier,
                strategy_content_hash=strategy_candidate_content_hash(strategy),
                trajectory_plan_bindings=tuple(trajectory_bindings),
            )
        )

    # 4. Observation bindings.
    leaves: list[ConditionComparisonLeaf] = []
    for rule in draft.rules:
        _collect_condition_leaves(rule.enter_condition, leaves)
        _collect_condition_leaves(rule.retain_condition, leaves)
    referenced_observations = {leaf.observation_id for leaf in leaves}
    if not referenced_observations:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="bound policy requires a non-empty observation catalog"
        )

    declarations_by_observation: dict[str, RuntimeObservationDeclaration] = {}
    for observation_id in sorted(referenced_observations):
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, scenario_id, world_version_id, observation_id
            )
        except RuntimeObservationDeclarationNotFoundError as exc:
            raise AdaptivePolicyBindingValidationError(
                tenant_id, campaign_id, reason="missing or foreign observation declaration"
            ) from exc
        except RuntimeObservationDeclarationIntegrityError as exc:
            raise AdaptivePolicyIntegrityError(
                tenant_id, campaign_id, reason="observation declaration authority corrupt"
            ) from exc
        declarations_by_observation[observation_id] = declaration

    observation_bindings: list[ObservationBinding] = []
    for observation_id in sorted(referenced_observations):
        declaration = declarations_by_observation[observation_id]
        observation_bindings.append(
            ObservationBinding(
                observation_id=observation_id,
                runtime_observation_declaration_id=declaration.identifier,
                runtime_observation_declaration_content_hash=declaration.content_hash,
                observed_value_kind=declaration.observed_value_kind,
                unit=declaration.unit,
                missing_behavior=declaration.missing_behavior,
            )
        )

    _verify_leaf_agreement(
        draft,
        dict((binding.observation_id, binding) for binding in observation_bindings),
        tenant_id=tenant_id,
        campaign_id=campaign_id,
    )

    # 5. Trusted rules and final policy.
    rules = tuple(
        AdaptivePolicyRule(
            rule_id=rule.rule_id,
            priority=rule.priority,
            target_action_id=rule.target_action_id,
            enter_condition=rule.enter_condition,
            retain_condition=rule.retain_condition,
            per_rule_switch_budget=rule.per_rule_switch_budget,
        )
        for rule in draft.rules
    )

    identifier = adaptive_policy_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        policy_id=binding_request.policy_id,
        policy_version=binding_request.policy_version,
        schema_version=SCHEMA_VERSION,
    )
    placeholder = AdaptivePolicy(
        tenant_id=tenant_id,
        identifier=identifier,
        schema_version=SCHEMA_VERSION,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
        runtime_version=RUNTIME_VERSION,
        policy_id=binding_request.policy_id,
        policy_version=binding_request.policy_version,
        observation_bindings=tuple(observation_bindings),
        actions=tuple(action_bindings),
        initial_action_id=draft.initial_action_id,
        fallback_action_id=draft.fallback_action_id,
        rules=rules,
        minimum_dwell_steps=draft.minimum_dwell_steps,
        cooldown_steps=draft.cooldown_steps,
        global_switch_budget=draft.global_switch_budget,
        content_hash=_PLACEHOLDER_HASH,
        bound_at=binding_request.bound_at,
        metadata=dict(binding_request.metadata),
    )
    policy = placeholder.model_copy(
        update={"content_hash": adaptive_policy_content_hash(placeholder)}
    )

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = policy.model_dump(mode="python")
        revalidated = AdaptivePolicy.model_validate(serialized, strict=True)
        verify_adaptive_policy_identity(
            revalidated,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=scenario_id,
            world_version_id=world_version_id,
            policy_id=binding_request.policy_id,
            policy_version=binding_request.policy_version,
        )
    except (ValidationError, TypeError, ValueError, AttributeError) as exc:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="policy contradicts its contract"
        ) from exc

    # The initial state snapshot must initialize (and is discarded; it is not
    # independently persisted).
    initialize_adaptive_policy_state(policy)

    store.put_adaptive_policy(tenant_id=tenant_id, campaign_id=campaign_id, policy=policy)
    return policy.model_copy(deep=True)


def _verify_leaf_agreement(
    draft: AdaptivePolicyDraft,
    bindings_by_observation: dict[str, ObservationBinding],
    *,
    tenant_id: str,
    campaign_id: str,
) -> None:
    """Every leaf's kind/unit/missing behavior equals its declaration binding."""
    for rule in draft.rules:
        leaves: list[ConditionComparisonLeaf] = []
        _collect_condition_leaves(rule.enter_condition, leaves)
        _collect_condition_leaves(rule.retain_condition, leaves)
        for leaf in leaves:
            binding = bindings_by_observation.get(leaf.observation_id)
            if binding is None:
                raise AdaptivePolicyBindingValidationError(
                    tenant_id,
                    campaign_id,
                    reason="condition leaf references an unknown observation",
                )
            if leaf.observed_value_kind != binding.observed_value_kind:
                raise AdaptivePolicyBindingValidationError(
                    tenant_id,
                    campaign_id,
                    reason="condition leaf value kind disagrees with its declaration",
                )
            if leaf.unit != binding.unit:
                raise AdaptivePolicyBindingValidationError(
                    tenant_id,
                    campaign_id,
                    reason="condition leaf unit disagrees with its declaration",
                )
            if leaf.missing_behavior != binding.missing_behavior:
                raise AdaptivePolicyBindingValidationError(
                    tenant_id,
                    campaign_id,
                    reason="condition leaf missing behavior disagrees with its declaration",
                )


def _verify_plan(
    plan: StrategyTrajectoryPlan,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world: WorldVersion,
    strategy: StrategyCandidate,
    embedded_models: dict[str, DomainStateModel],
) -> None:
    """Verify one stored plan's complete recorded authority; never repairs it."""
    if plan.tenant_id != tenant_id:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan authority mismatch"
        )
    if plan.campaign_id != campaign_id:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan authority mismatch"
        )
    if plan.scenario_id != scenario_id:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan authority mismatch"
        )
    if plan.world_version_id != world.identifier:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan authority mismatch"
        )
    if plan.world_content_hash != world.content_hash:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan world hash mismatch"
        )
    if plan.strategy_candidate_id != strategy.identifier:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan strategy mismatch"
        )
    if plan.strategy_content_hash != strategy_candidate_content_hash(strategy):
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="trajectory plan strategy hash mismatch"
        )
    if plan.identifier != trajectory_plan_identifier(
        campaign_id=campaign_id,
        world_version_id=world.identifier,
        strategy_candidate_id=strategy.identifier,
        state_model_identifier=plan.state_model_identifier,
    ):
        raise AdaptivePolicyIntegrityError(tenant_id, campaign_id, reason="forged plan identifier")
    if plan.content_hash != trajectory_plan_content_hash(plan):
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="forged plan content hash"
        )
    embedded_model = embedded_models.get(plan.state_model_identifier)
    if embedded_model is None:
        raise AdaptivePolicyIntegrityError(tenant_id, campaign_id, reason="unknown state model")
    if plan.state_model_id != embedded_model.state_model_id:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="state model identity mismatch"
        )
    if plan.state_model_content_hash != embedded_model.content_hash:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="state model content hash mismatch"
        )
    if plan.manifest_id != embedded_model.manifest_id:
        raise AdaptivePolicyIntegrityError(
            tenant_id, campaign_id, reason="state model manifest mismatch"
        )


__all__ = [
    "ActionStrategyMapping",
    "AdaptivePolicyBindingRequest",
    "RUNTIME_VERSION",
    "bind_adaptive_policy",
]
