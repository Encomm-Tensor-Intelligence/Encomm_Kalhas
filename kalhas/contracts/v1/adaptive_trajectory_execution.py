"""Adaptive-run trajectory execution aggregate (Phase 28, H28-S06 contract slice).

Phase 28 adds the **adaptive-run trajectory execution aggregate** for the
additive runtime version ``4.0.0``. ``AdaptiveRunTrajectoryExecution`` is
one immutable public ``VersionedContract`` per completed adaptive run: the
run/campaign/plan/scenario identity, the compiled world and scenario-seed
identities with their content hashes, the exact world realization identity
and content hash, the exact runtime literal ``4.0.0``, the adaptive-policy
identity (logical ``policy_id``, the policy's stable contract identifier,
and its content hash), the optional external-observation-input bundle
identity/hash pair, the run input hash and the exact ordered trajectory
plan-set hash, the ordered per-decision evidence (observation events,
policy-state snapshots, decision events, switch events, and trajectory
results by decision step), the aggregate ``content_hash``, and the
deterministic caller-supplied ``executed_at`` timestamp.

The nested evidence roles are reused verbatim from their owning modules and
are deliberately **not** redefined here: ``RuntimeObservationEvent``
(runtime-observation), ``AdaptivePolicyStateSnapshot``,
``AdaptivePolicyDecisionEvent``, and ``AdaptivePolicySwitchEvent``
(adaptive-policy state), and ``RealizedStateTrajectoryResult``
(realization trajectory execution). This aggregate records immutable
evidence only. It never executes, persists, replays, samples, queries,
recommends, or compares anything, and no field type can express a callback,
expression, import path, provider, network configuration, or executable
mechanism.

Contract-invariant scope is deliberately structural. Whether the recorded
plan/action authorities agree with stored policies or plans, and whether the
recorded state chain was actually produced, is cross-authority verification
that belongs to the later execution service, never to this contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.realization_trajectory_execution import RealizedStateTrajectoryResult
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent
from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import IdentifierString, Sha256Hex


class AdaptiveRunTrajectoryExecution(VersionedContract):
    """Immutable adaptive-run trajectory execution artifact for runtime 4.0.0.

    One aggregate artifact per completed adaptive run. The outer position of
    ``trajectory_results_by_decision`` is the decision step; each inner tuple
    holds that decision's realized state-model trajectory results canonically
    ordered by ``(state_model_identifier, trajectory_plan_id)``. The bundle
    identifier and content hash are both present or both absent (external
    provenance is optional), and the optional bundle pair never carries a
    declaration-style source identity.

    Structural invariants enforced here: at least one decision; equal
    cardinality of policy-state snapshots, decision events, and outer
    trajectory-result tuples; snapshot and decision steps exactly ``0..N-1``;
    every snapshot and decision carries the aggregate's policy/runtime
    identity; switch events are strictly ordered, carry unique valid decision
    steps, exist exactly for ``action_changed`` decisions, and agree with the
    corresponding decision's current/selected actions; observation
    ``sequence_position`` values are contiguous from zero with unique
    ``(observation_declaration_id, source_step_index)`` coordinates and
    aggregate world/seed provenance agreement; non-terminal observations keep
    ``available_decision_step`` inside the decision range; every inner
    trajectory-result tuple is canonically ordered with unique state-model and
    plan identifiers; and nested realized state values are finite. Cross-
    authority plan/action and state-chain verification belongs to the later
    execution service.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: IdentifierString
    campaign_id: IdentifierString
    run_plan_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex
    runtime_version: Literal["4.0.0"]
    adaptive_policy_identifier: IdentifierString
    policy_id: IdentifierString
    adaptive_policy_content_hash: Sha256Hex
    external_observation_input_bundle_id: IdentifierString | None = None
    external_observation_input_bundle_content_hash: Sha256Hex | None = None
    input_hash: Sha256Hex
    trajectory_plan_set_hash: Sha256Hex
    observation_events: tuple[RuntimeObservationEvent, ...]
    policy_state_snapshots: tuple[AdaptivePolicyStateSnapshot, ...]
    decision_events: tuple[AdaptivePolicyDecisionEvent, ...] = Field(min_length=1)
    switch_events: tuple[AdaptivePolicySwitchEvent, ...]
    trajectory_results_by_decision: tuple[tuple[RealizedStateTrajectoryResult, ...], ...]
    content_hash: Sha256Hex
    executed_at: AwareDatetime

    @model_validator(mode="after")
    def _decision_cardinality_and_contiguous_steps(self) -> AdaptiveRunTrajectoryExecution:
        decision_count = len(self.decision_events)
        if len(self.policy_state_snapshots) != decision_count:
            raise ValueError("policy_state_snapshots must hold one snapshot per decision step")
        if len(self.trajectory_results_by_decision) != decision_count:
            raise ValueError(
                "trajectory_results_by_decision must hold one outer tuple per decision step"
            )
        for position, snapshot in enumerate(self.policy_state_snapshots):
            if snapshot.decision_step != position:
                raise ValueError(
                    "policy-state snapshot decision steps must be exactly 0..N-1 "
                    f"(expected {position}, found {snapshot.decision_step})"
                )
        for position, decision in enumerate(self.decision_events):
            if decision.decision_step != position:
                raise ValueError(
                    "decision event steps must be exactly 0..N-1 "
                    f"(expected {position}, found {decision.decision_step})"
                )
        return self

    @model_validator(mode="after")
    def _policy_identity_agreement(self) -> AdaptiveRunTrajectoryExecution:
        for snapshot in self.policy_state_snapshots:
            if snapshot.policy_id != self.policy_id:
                raise ValueError(
                    "policy-state snapshot policy_id must equal the aggregate policy_id"
                )
            if snapshot.policy_content_hash != self.adaptive_policy_content_hash:
                raise ValueError(
                    "policy-state snapshot policy_content_hash must equal "
                    "the aggregate adaptive_policy_content_hash"
                )
        for decision in self.decision_events:
            if decision.policy_id != self.policy_id:
                raise ValueError("decision event policy_id must equal the aggregate policy_id")
            if decision.policy_content_hash != self.adaptive_policy_content_hash:
                raise ValueError(
                    "decision event policy_content_hash must equal "
                    "the aggregate adaptive_policy_content_hash"
                )
        return self

    @model_validator(mode="after")
    def _switches_strictly_ordered_and_agree(self) -> AdaptiveRunTrajectoryExecution:
        steps = [switch.decision_step for switch in self.switch_events]
        if steps != sorted(steps):
            raise ValueError("switch events must be stored in strictly ascending decision step")
        if len(set(steps)) != len(steps):
            raise ValueError("switch event decision steps must be unique")
        decision_count = len(self.decision_events)
        for switch in self.switch_events:
            step = switch.decision_step
            if step >= decision_count:
                raise ValueError("switch event decision_step must be a valid decision step")
            decision = self.decision_events[step]
            if not decision.action_changed:
                raise ValueError("a switch event may exist only for an action_changed decision")
            if switch.old_action_id != decision.current_action_id:
                raise ValueError("switch old_action_id must equal the decision current_action_id")
            if switch.new_action_id != decision.selected_action_id:
                raise ValueError("switch new_action_id must equal the decision selected_action_id")
        changed_steps = {
            position
            for position, decision in enumerate(self.decision_events)
            if decision.action_changed
        }
        if set(steps) != changed_steps:
            raise ValueError("a switch event must exist exactly for every action_changed decision")
        return self

    @model_validator(mode="after")
    def _observations_contiguous_with_provenance(self) -> AdaptiveRunTrajectoryExecution:
        positions = [event.sequence_position for event in self.observation_events]
        if positions != list(range(len(positions))):
            raise ValueError("observation sequence_position values must be contiguous from zero")
        for event in self.observation_events:
            if event.world_version_id != self.world_version_id:
                raise ValueError(
                    "observation world_version_id must equal the aggregate world_version_id"
                )
            if event.world_content_hash != self.world_content_hash:
                raise ValueError(
                    "observation world_content_hash must equal the aggregate world_content_hash"
                )
            if event.scenario_seed_id != self.scenario_seed_id:
                raise ValueError(
                    "observation scenario_seed_id must equal the aggregate scenario_seed_id"
                )
            if event.seed_content_hash != self.seed_content_hash:
                raise ValueError(
                    "observation seed_content_hash must equal the aggregate seed_content_hash"
                )
            if not event.terminal:
                available = event.available_decision_step
                if available is None or available >= len(self.decision_events):
                    raise ValueError(
                        "non-terminal observation available_decision_step must be "
                        "within the decision step range"
                    )
        coordinates = [
            (event.observation_declaration_id, event.source_step_index)
            for event in self.observation_events
        ]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError(
                "duplicate (observation_declaration_id, source_step_index) "
                "observation coordinates are rejected"
            )
        return self

    @model_validator(mode="after")
    def _trajectory_results_canonical_and_unique(self) -> AdaptiveRunTrajectoryExecution:
        for decision_index, results in enumerate(self.trajectory_results_by_decision):
            ordering = [
                (result.state_model_identifier, result.trajectory_plan_id) for result in results
            ]
            if ordering != sorted(ordering):
                raise ValueError(
                    f"decision {decision_index} trajectory results must be canonically "
                    "ordered by (state_model_identifier, trajectory_plan_id)"
                )
            state_models = [result.state_model_identifier for result in results]
            if len(set(state_models)) != len(state_models):
                raise ValueError(
                    f"decision {decision_index} trajectory results carry duplicate "
                    "state_model_identifier values"
                )
            plan_ids = [result.trajectory_plan_id for result in results]
            if len(set(plan_ids)) != len(plan_ids):
                raise ValueError(
                    f"decision {decision_index} trajectory results carry duplicate "
                    "trajectory_plan_id values"
                )
        return self

    @model_validator(mode="after")
    def _external_bundle_pair_present_or_absent(self) -> AdaptiveRunTrajectoryExecution:
        if (self.external_observation_input_bundle_id is None) != (
            self.external_observation_input_bundle_content_hash is None
        ):
            raise ValueError(
                "the external observation input bundle identifier and content hash "
                "must be both present or both absent"
            )
        return self

    @model_validator(mode="after")
    def _trajectory_result_states_are_finite(self) -> AdaptiveRunTrajectoryExecution:
        for decision_index, results in enumerate(self.trajectory_results_by_decision):
            for result in results:
                if _contains_non_finite(result.initial_state):
                    raise ValueError(
                        f"decision {decision_index} initial_state must contain only "
                        "finite JSON-compatible values"
                    )
                if _contains_non_finite(result.final_state):
                    raise ValueError(
                        f"decision {decision_index} final_state must contain only "
                        "finite JSON-compatible values"
                    )
        return self
