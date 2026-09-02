"""Pure cross-authority integrity verification of runtime-4 adaptive executions (C1).

Store-independent, read-only, deterministic verification of a supplied
:class:`AdaptiveRunTrajectoryExecution` against the explicitly supplied
verified upstream authorities from which it must have been built. This is
**structural, identity, and authority verification only - not replay**: no
policy condition is evaluated, no state transition is executed, no
observation is derived, and the policy state machine is never advanced.
Behavioral recomputation belongs to the later C2/execution slice
(H28-S07). Any violated rule raises the safe typed integrity error with a
generic public message; the internal ``reason`` names only the violated
rule class. A failing record is rejected, never repaired, normalized, or
silently accepted.

Verified against explicit authorities (each already store-reverified):

- exact tenant/run/campaign/run-plan/scenario/world provenance;
- ``RunPlan.runtime_version`` exactly ``4.0.0``; campaign exactly COMPILED;
  the run exactly RUNNING or COMPLETE (never PLANNED or FAILED);
- the run plan belongs to the campaign/world/seed; exact verified world
  identity and content hash;
- exact scenario-seed membership and recomputed seed content hash;
- exact world-realization identity/content hash and seed/world agreement
  (the existing realization provenance verifier, with the exact stored
  uncertainty model or its verified absence);
- exact stored :class:`AdaptivePolicy` identity/content hash and
  campaign/world agreement; exact ``policy_id`` agreement;
- the exact canonical action-bound :class:`StrategyTrajectoryPlan` set
  (every bound plan of every bound action, exactly the stored records),
  the recomputed plan-set hash, and the recomputed frozen runtime-4 input
  digest;
- ``executed_at`` equal to the authoritative RunPlan ``created_at``;
- the optional external bundle pair present or absent together, and when
  present the exact accepted bundle tenant/campaign/world/seed identity
  and content hash; a policy bound to an ``ExternalObservationSource``
  requires its accepted bundle;
- every :class:`RuntimeObservationEvent` passes exact identity/content-hash
  verification and agrees with world, seed, declaration, and optional
  bundle provenance; event sequence and coordinates stay
  contract-canonical;
- every snapshot, decision, and switch carries the execution's
  policy/runtime identity and cites actions bound by the stored policy;
- every trajectory result belongs to the selected action's exact stored
  trajectory plan for that decision; plan/model identity and content
  hashes agree with stored authorities; initial/final state hashes, the
  trace hash, and the result content hash are independently recomputed
  with the established helpers; attempt chains are contiguous and bound
  to the exact plan transition references; nested state values stay
  finite;
- the final aggregate content hash is exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    RUNTIME_VERSION_LITERAL,
    adaptive_run_input_hash,
    adaptive_run_trajectory_execution_content_hash,
    adaptive_run_trajectory_execution_identifier,
    verify_adaptive_run_trajectory_execution_identity,
)
from kalhas.application.external_observation_input_identity import (
    verify_external_observation_input_bundle_identity,
)
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_identity import verify_realization_provenance
from kalhas.application.runtime_observation_declaration_identity import (
    verify_runtime_observation_declaration_identity,
)
from kalhas.application.runtime_observation_event_identity import (
    verify_runtime_observation_event_identity,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.realization_trajectory_execution import RealizedStateTrajectoryResult
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationSource,
    RuntimeObservationDeclaration,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.state_model import DomainStateModel, _contains_non_finite
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization, WorldUncertaintyModel


@dataclass(frozen=True, kw_only=True)
class AdaptiveRunExecutionAuthorities:
    """The explicitly supplied, already-verified upstream runtime-4 authorities.

    Every member is a stored record independently reverified by the store
    on read (or an explicitly derived value such as the recomputed seed
    content hash and the realization's exact uncertainty model or its
    verified absence). The campaign's and the run's lifecycle statuses are
    carried as two explicitly named members - ``campaign_status`` is the
    campaign's own :class:`CampaignStatus`, ``run_status`` the run's
    :class:`RunStatus` - and are never merged into one ambiguous field.
    The verifier trusts nothing beyond these values and never reads a
    store.

    ``declarations`` maps each policy-bound logical ``observation_id`` to
    its exact stored :class:`RuntimeObservationDeclaration`. ``action_plans``
    maps each policy-bound ``action_id`` to the exact stored trajectory
    plans bound to that action. ``external_bundle`` is the exact accepted
    :class:`ExternalObservationInputBundle` or ``None``.
    """

    tenant_id: str
    run_id: str
    campaign: CampaignSpec
    campaign_status: CampaignStatus
    run_status: RunStatus
    run_plan: RunPlan
    world: WorldVersion
    seed: ScenarioSeed
    realization: WorldRealization
    uncertainty_model: WorldUncertaintyModel | None
    policy: AdaptivePolicy
    declarations: dict[str, RuntimeObservationDeclaration]
    action_plans: dict[str, tuple[StrategyTrajectoryPlan, ...]]
    external_bundle: ExternalObservationInputBundle | None


def _reject(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    raise AdaptiveRunTrajectoryExecutionIntegrityError(tenant_id, run_id, reason)


def _convert(
    tenant_id: str, run_id: str, reason: str
) -> AdaptiveRunTrajectoryExecutionIntegrityError:
    return AdaptiveRunTrajectoryExecutionIntegrityError(tenant_id, run_id, reason)


def verify_adaptive_run_trajectory_execution_authority(
    execution: AdaptiveRunTrajectoryExecution,
    *,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    """Verify a supplied adaptive execution against explicit verified authorities.

    Every check is deterministic; the first violated rule raises
    :class:`AdaptiveRunTrajectoryExecutionIntegrityError` with a generic
    public message and an internal reason. Nothing is executed, derived,
    advanced, replayed, repaired, or written.
    """
    tenant_id = authorities.tenant_id
    run_id = authorities.run_id
    campaign = authorities.campaign
    world = authorities.world
    seed = authorities.seed
    realization = authorities.realization
    policy = authorities.policy
    campaign_status = authorities.campaign_status
    run_status = authorities.run_status
    run_plan = authorities.run_plan

    # The runtime-hash helpers live in modules that reach the store
    # through the historical runtime-input import chain; binding them in
    # the function body keeps this verifier importable from the store
    # without an import cycle (the store itself follows the same
    # late-binding doctrine for exactly those modules).
    from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash

    # Deterministic identity and detached strict revalidation first: a
    # validator-bypassed or forged record is rejected before any field of
    # it is trusted.
    try:
        verify_adaptive_run_trajectory_execution_identity(execution)
    except (TypeError, ValueError, AttributeError) as exc:
        raise _convert(tenant_id, run_id, "execution violates its contract") from exc
    if execution.identifier != adaptive_run_trajectory_execution_identifier(
        run_id=run_id, runtime_version=execution.runtime_version
    ):
        _reject(tenant_id, run_id, "execution identifier does not match the run identity")

    # Exact tenant/run/campaign/run-plan/scenario/world provenance.
    if execution.tenant_id != tenant_id:
        _reject(tenant_id, run_id, "execution tenant mismatch")
    if execution.run_id != run_id:
        _reject(tenant_id, run_id, "execution run identity mismatch")
    if execution.campaign_id != campaign.identifier:
        _reject(tenant_id, run_id, "execution campaign mismatch")
    if execution.run_plan_id != run_plan.identifier:
        _reject(tenant_id, run_id, "execution run plan mismatch")
    if execution.scenario_id != campaign.scenario_id:
        _reject(tenant_id, run_id, "execution scenario mismatch")

    # Campaign authority: exactly COMPILED and owned.
    if campaign_status.tenant_id != tenant_id:
        _reject(tenant_id, run_id, "campaign status ownership mismatch")
    if campaign_status.campaign_id != campaign.identifier:
        _reject(tenant_id, run_id, "campaign status identity mismatch")
    if campaign_status.state is not CampaignState.COMPILED:
        _reject(tenant_id, run_id, "campaign must be exactly COMPILED")

    # Run authority: owned by the tenant/run/campaign/run-plan, runtime-4,
    # and exactly RUNNING or COMPLETE (PLANNED and FAILED never carry an
    # execution record). The planning input-hash anchor is the only hash
    # agreement between the run status and the run plan; neither is ever
    # compared against the execution's own input hash, which is
    # recomputed separately below from the full authority chain.
    if run_status.tenant_id != tenant_id:
        _reject(tenant_id, run_id, "run status ownership mismatch")
    if run_status.run_id != run_id:
        _reject(tenant_id, run_id, "run status identity mismatch")
    if run_status.campaign_id != campaign.identifier:
        _reject(tenant_id, run_id, "run status campaign mismatch")
    if run_status.run_plan_id != run_plan.identifier:
        _reject(tenant_id, run_id, "run status run plan mismatch")
    if run_status.runtime_version != RUNTIME_VERSION_LITERAL:
        _reject(tenant_id, run_id, "run status runtime mismatch")
    if run_status.state not in (RunState.RUNNING, RunState.COMPLETE):
        _reject(tenant_id, run_id, "run must be exactly RUNNING or COMPLETE")
    if run_status.input_hash != run_plan.input_hash:
        _reject(tenant_id, run_id, "run status planning input hash mismatch")

    # The run plan belongs to the campaign/world/seed and carries the
    # exact runtime literal. RunPlan carries ``world_version_id`` but no
    # ``world_content_hash`` field: the recorded planning world anchor
    # is the version identity, and the execution's ``world_content_hash``
    # is verified below directly against the stored compiled
    # ``WorldVersion`` - ``RunPlan.world_content_hash`` is never read.
    if run_plan.tenant_id != tenant_id:
        _reject(tenant_id, run_id, "run plan tenant mismatch")
    if run_plan.campaign_id != campaign.identifier:
        _reject(tenant_id, run_id, "run plan campaign mismatch")
    if run_plan.world_version_id != world.identifier:
        _reject(tenant_id, run_id, "run plan world identity mismatch")
    if run_plan.scenario_seed_id != seed.identifier:
        _reject(tenant_id, run_id, "run plan scenario seed mismatch")
    if run_plan.runtime_version != RUNTIME_VERSION_LITERAL:
        _reject(tenant_id, run_id, "run plan runtime mismatch")

    # Exact verified world identity/content hash and exact seed authority.
    if execution.world_version_id != world.identifier:
        _reject(tenant_id, run_id, "execution world identity mismatch")
    if execution.world_content_hash != world.content_hash:
        _reject(tenant_id, run_id, "execution world content hash mismatch")
    if execution.scenario_seed_id != seed.identifier:
        _reject(tenant_id, run_id, "execution scenario seed mismatch")
    if execution.seed_content_hash != seed_content_hash(seed):
        _reject(tenant_id, run_id, "execution seed content hash mismatch")

    # Exact world realization identity/content hash with full seed/world
    # provenance recomputation (including the exact stored uncertainty
    # model or its verified absence).
    try:
        verify_realization_provenance(
            run_id=run_id,
            world=world,
            seed=seed,
            realization=realization,
            uncertainty_model=authorities.uncertainty_model,
        )
    except RealizationRunTrajectoryExecutionIntegrityError as exc:
        raise _convert(tenant_id, run_id, "world realization provenance mismatch") from exc
    if execution.world_realization_id != realization.identifier:
        _reject(tenant_id, run_id, "execution realization identity mismatch")
    if execution.world_realization_content_hash != realization.content_hash:
        _reject(tenant_id, run_id, "execution realization content hash mismatch")

    # Exact stored adaptive-policy identity/content hash and exact
    # campaign/world agreement.
    if policy.tenant_id != tenant_id:
        _reject(tenant_id, run_id, "policy tenant mismatch")
    if policy.campaign_id != campaign.identifier:
        _reject(tenant_id, run_id, "policy campaign mismatch")
    if policy.scenario_id != campaign.scenario_id:
        _reject(tenant_id, run_id, "policy scenario mismatch")
    if policy.world_version_id != world.identifier:
        _reject(tenant_id, run_id, "policy world identity mismatch")
    if policy.world_content_hash != world.content_hash:
        _reject(tenant_id, run_id, "policy world content hash mismatch")
    if policy.runtime_version != RUNTIME_VERSION_LITERAL:
        _reject(tenant_id, run_id, "policy runtime mismatch")
    if execution.adaptive_policy_identifier != policy.identifier:
        _reject(tenant_id, run_id, "policy identity mismatch")
    if execution.policy_id != policy.policy_id:
        _reject(tenant_id, run_id, "policy identifier mismatch")
    if execution.adaptive_policy_content_hash != policy.content_hash:
        _reject(tenant_id, run_id, "policy content hash mismatch")

    # Exact canonical action-bound plan set and recomputed plan-set hash.
    actions_by_id = {action.action_id: action for action in policy.actions}
    if set(authorities.action_plans) != set(actions_by_id):
        _reject(tenant_id, run_id, "action plan coverage mismatch")
    plans: list[StrategyTrajectoryPlan] = []
    for action_id, bound_plans in authorities.action_plans.items():
        action = actions_by_id[action_id]
        bindings = {
            binding.trajectory_plan_id: binding for binding in action.trajectory_plan_bindings
        }
        if len(bound_plans) != len(bindings):
            _reject(tenant_id, run_id, "action plan count mismatch")
        for plan in bound_plans:
            binding = bindings.get(plan.identifier)
            if binding is None:
                _reject(tenant_id, run_id, "action plan is not bound to the action")
            if plan.strategy_candidate_id != action.strategy_candidate_id:
                _reject(tenant_id, run_id, "action plan strategy identity mismatch")
            if plan.strategy_content_hash != action.strategy_content_hash:
                _reject(tenant_id, run_id, "action plan strategy content hash mismatch")
            if plan.content_hash != binding.trajectory_plan_content_hash:
                _reject(tenant_id, run_id, "action plan content hash mismatch")
            if plan.campaign_id != campaign.identifier:
                _reject(tenant_id, run_id, "action plan campaign mismatch")
            if plan.world_version_id != world.identifier:
                _reject(tenant_id, run_id, "action plan world identity mismatch")
            if plan.world_content_hash != world.content_hash:
                _reject(tenant_id, run_id, "action plan world content hash mismatch")
            if (
                plan.state_model_identifier != binding.state_model_identifier
                or plan.manifest_id != binding.manifest_id
                or plan.state_model_id != binding.state_model_id
                or plan.state_model_content_hash != binding.state_model_content_hash
            ):
                _reject(tenant_id, run_id, "action plan state model authority mismatch")
            plans.append(plan)
    ordered_plans = tuple(
        sorted(plans, key=lambda plan: (plan.strategy_candidate_id, plan.state_model_identifier))
    )
    if execution.trajectory_plan_set_hash != trajectory_plan_set_hash(ordered_plans):
        _reject(tenant_id, run_id, "trajectory plan set hash mismatch")

    # Optional external bundle: both-or-neither is contract-enforced; an
    # execution that references an accepted bundle requires exactly that
    # stored authority, whose identity and content hash are independently
    # re-verified; and a policy bound to an external observation source
    # requires its accepted bundle.
    bundle = authorities.external_bundle
    if execution.external_observation_input_bundle_id is not None:
        if (
            bundle is None
            or bundle.identifier != execution.external_observation_input_bundle_id
            or bundle.content_hash != execution.external_observation_input_bundle_content_hash
        ):
            _reject(tenant_id, run_id, "external bundle does not match the execution")
        try:
            verify_external_observation_input_bundle_identity(
                bundle,
                tenant_id=tenant_id,
                campaign_id=campaign.identifier,
                scenario_id=campaign.scenario_id,
                world_version_id=world.identifier,
                scenario_seed_id=seed.identifier,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise _convert(tenant_id, run_id, "external bundle authority mismatch") from exc
    policy_has_external_source = any(
        isinstance(declaration.observation_source, ExternalObservationSource)
        for declaration in authorities.declarations.values()
    )
    if policy_has_external_source and bundle is None:
        _reject(
            tenant_id,
            run_id,
            "bound external observation source requires the accepted external bundle",
        )

    # Recompute the frozen runtime-4 input digest from the authorities.
    # The causal run horizon is derived exclusively from the aggregate
    # evidence - never from the caller, the store, metadata, the run
    # plan, or any duplicated field. The contract already guarantees at
    # least one decision event with contiguous 0..N-1 steps, so the
    # derived horizon is an exact non-negative integer.
    decision_count = len(execution.decision_events)
    final_decision_step = decision_count - 1
    recomputed_input_hash = adaptive_run_input_hash(
        run_plan_id=run_plan.identifier,
        run_plan_input_hash=run_plan.input_hash,
        campaign_id=campaign.identifier,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=seed.identifier,
        seed_content_hash_value=seed_content_hash(seed),
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        adaptive_policy_identifier=policy.identifier,
        adaptive_policy_content_hash=policy.content_hash,
        trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
        external_observation_input_bundle_id=execution.external_observation_input_bundle_id,
        external_observation_input_bundle_content_hash=(
            execution.external_observation_input_bundle_content_hash
        ),
        final_decision_step=final_decision_step,
    )
    if execution.input_hash != recomputed_input_hash:
        _reject(tenant_id, run_id, "input hash mismatch")

    # Deterministic executed_at authority: the RunPlan creation time.
    if execution.executed_at != run_plan.created_at:
        _reject(tenant_id, run_id, "executed_at mismatch")

    # Every observation event: exact identity/content hash plus exact
    # declaration and bundle provenance.
    for event in execution.observation_events:
        declaration = authorities.declarations.get(event.observation_id)
        if declaration is None:
            _reject(tenant_id, run_id, "observation declaration authority missing")
        if (
            event.observation_declaration_id != declaration.identifier
            or event.observation_declaration_content_hash != declaration.content_hash
        ):
            _reject(tenant_id, run_id, "observation declaration mismatch")
        try:
            verify_runtime_observation_declaration_identity(
                declaration,
                tenant_id=tenant_id,
                scenario_id=campaign.scenario_id,
                world_version_id=world.identifier,
                observation_id=declaration.observation_id,
            )
            verify_runtime_observation_event_identity(
                event,
                tenant_id=tenant_id,
                campaign_id=campaign.identifier,
                scenario_seed_id=seed.identifier,
                runtime_observation_declaration_id=declaration.identifier,
                source_step_index=event.source_step_index,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise _convert(tenant_id, run_id, "observation event authority mismatch") from exc
        if event.source_kind == "external_input" and (
            bundle is None
            or event.external_input_bundle_id != bundle.identifier
            or event.external_input_bundle_content_hash != bundle.content_hash
        ):
            _reject(tenant_id, run_id, "observation bundle provenance mismatch")

    # Every policy snapshot, decision, and switch: exact policy/runtime
    # identity and bound-action authority.
    for snapshot in execution.policy_state_snapshots:
        if (
            snapshot.runtime_version != RUNTIME_VERSION_LITERAL
            or snapshot.policy_id != policy.policy_id
            or snapshot.policy_content_hash != policy.content_hash
        ):
            _reject(tenant_id, run_id, "policy snapshot identity mismatch")
        if snapshot.current_action_id not in actions_by_id:
            _reject(tenant_id, run_id, "snapshot action is not bound by the policy")
    for decision in execution.decision_events:
        if (
            decision.runtime_version != RUNTIME_VERSION_LITERAL
            or decision.policy_id != policy.policy_id
            or decision.policy_content_hash != policy.content_hash
        ):
            _reject(tenant_id, run_id, "decision identity mismatch")
        if (
            decision.current_action_id not in actions_by_id
            or decision.selected_action_id not in actions_by_id
        ):
            _reject(tenant_id, run_id, "decision action is not bound by the policy")
    for switch in execution.switch_events:
        if (
            switch.runtime_version != RUNTIME_VERSION_LITERAL
            or switch.policy_id != policy.policy_id
            or switch.policy_content_hash != policy.content_hash
        ):
            _reject(tenant_id, run_id, "switch identity mismatch")
        if switch.old_action_id not in actions_by_id or switch.new_action_id not in actions_by_id:
            _reject(tenant_id, run_id, "switch action is not bound by the policy")

    # Per-decision trajectory results: exact selected-action plan
    # authority, stored model/transition authority, recomputed state,
    # trace, and result hashes, and contiguous attempt chains.
    catalog = extract_world_catalog(world)
    models_by_identifier = {model.identifier: model for model in catalog.state_models}
    transitions_by_identifier = {
        transition.identifier: transition for transition in catalog.transitions
    }
    plans_by_action: dict[str, dict[str, StrategyTrajectoryPlan]] = {
        action_id: {plan.identifier: plan for plan in bound_plans}
        for action_id, bound_plans in authorities.action_plans.items()
    }
    for decision, results in zip(
        execution.decision_events, execution.trajectory_results_by_decision, strict=True
    ):
        selected_plans = plans_by_action[decision.selected_action_id]
        for result in results:
            _verify_trajectory_result(
                result,
                tenant_id=tenant_id,
                run_id=run_id,
                selected_plans=selected_plans,
                models_by_identifier=models_by_identifier,
                transitions_by_identifier=transitions_by_identifier,
            )

    # The final aggregate content hash is exact (independent recompute).
    if execution.content_hash != adaptive_run_trajectory_execution_content_hash(execution):
        _reject(tenant_id, run_id, "content hash mismatch")


def _verify_trajectory_result(
    result: RealizedStateTrajectoryResult,
    *,
    tenant_id: str,
    run_id: str,
    selected_plans: dict[str, StrategyTrajectoryPlan],
    models_by_identifier: dict[str, DomainStateModel],
    transitions_by_identifier: dict[str, DomainStateTransition],
) -> None:
    """Verify one trajectory result against its exact selected-action plan."""
    from kalhas.application.realization_trajectory_runtime import (
        realized_state_trajectory_result_content_hash,
    )
    from kalhas.application.state_transition_engine import state_hash
    from kalhas.application.trajectory_integrity import _trace_hash

    plan = selected_plans.get(result.trajectory_plan_id)
    if plan is None:
        _reject(tenant_id, run_id, "result plan is not bound to the selected action")
    if result.trajectory_plan_content_hash != plan.content_hash:
        _reject(tenant_id, run_id, "result plan content hash mismatch")
    state_model = models_by_identifier.get(result.state_model_identifier)
    if state_model is None:
        _reject(tenant_id, run_id, "result state model missing from the world")
    if (
        result.manifest_id != state_model.manifest_id
        or result.state_model_id != state_model.state_model_id
        or result.state_model_content_hash != state_model.content_hash
    ):
        _reject(tenant_id, run_id, "result state model authority mismatch")
    if plan.state_model_identifier != result.state_model_identifier:
        _reject(tenant_id, run_id, "result plan state model mismatch")
    if _contains_non_finite(result.initial_state) or _contains_non_finite(result.final_state):
        _reject(tenant_id, run_id, "result state contains non-finite values")
    if result.initial_state_hash != state_hash(result.initial_state):
        _reject(tenant_id, run_id, "result initial state hash mismatch")
    if result.final_state_hash != state_hash(result.final_state):
        _reject(tenant_id, run_id, "result final state hash mismatch")
    if result.trace_hash != _trace_hash(result.attempts):
        _reject(tenant_id, run_id, "result trace hash mismatch")
    if result.content_hash != realized_state_trajectory_result_content_hash(result):
        _reject(tenant_id, run_id, "result content hash mismatch")
    references = plan.transition_references
    if len(result.attempts) != len(references):
        _reject(tenant_id, run_id, "result attempt count mismatch")
    for position, (attempt, reference) in enumerate(zip(result.attempts, references, strict=True)):
        if attempt.sequence_position != position:
            _reject(tenant_id, run_id, "result attempt positions are not contiguous")
        if attempt.transition_identifier != reference.transition_identifier:
            _reject(tenant_id, run_id, "attempt transition reference mismatch")
        if attempt.transition_id != reference.transition_id:
            _reject(tenant_id, run_id, "attempt transition id mismatch")
        if attempt.transition_content_hash != reference.transition_content_hash:
            _reject(tenant_id, run_id, "attempt transition content hash mismatch")
        transition = transitions_by_identifier.get(attempt.transition_identifier)
        if transition is None:
            _reject(tenant_id, run_id, "attempt references an unknown transition")
        if (
            transition.manifest_id != state_model.manifest_id
            or transition.state_model_id != state_model.state_model_id
            or transition.state_model_content_hash != state_model.content_hash
        ):
            _reject(tenant_id, run_id, "attempt transition model authority mismatch")
        if transition.transition_id != attempt.transition_id:
            _reject(tenant_id, run_id, "attempt transition id mismatch")
        if transition.content_hash != attempt.transition_content_hash:
            _reject(tenant_id, run_id, "attempt transition content hash mismatch")
    if result.attempts:
        if result.attempts[0].before_state_hash != result.initial_state_hash:
            _reject(tenant_id, run_id, "first attempt before hash mismatch")
        for position in range(1, len(result.attempts)):
            if result.attempts[position].before_state_hash != (
                result.attempts[position - 1].after_state_hash
            ):
                _reject(tenant_id, run_id, "attempt state chain mismatch")
        if result.attempts[-1].after_state_hash != result.final_state_hash:
            _reject(tenant_id, run_id, "last attempt after hash mismatch")
