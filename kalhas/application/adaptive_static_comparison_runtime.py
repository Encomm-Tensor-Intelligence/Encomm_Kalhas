"""Read-only adaptive-vs-static comparison evidence runtime (H28-S09B).

This module is the deterministic, domain-neutral, **read-only** runtime-4
comparison-evidence seam for exactly one already-existing COMPILED campaign
(H28-S09, audit ``h28-s09-architecture-audit.md`` section Q8). It derives a
private, immutable, **unpersisted** evidence aggregate that joins the
runtime-4 adaptive arm with every stored runtime-3 static arm of the
campaign at seed level and computes direction-normalized paired deltas over
the shared ordered seed ensemble. There is no persistence, no new public
contract, no schema change, no API route, no execution, no replay, and no
historical-runtime reinterpretation (ADR-004 D28-04: query projections are
read-only verified derivations from stored authority and do not persist new
evidence; comparison and decision-brief projections remain derived and
unpersisted).

Derivation semantics (frozen by this slice):

- **Runtime gate before any store read.** Exactly ``4.0.0`` is accepted;
  every other value - including the historical ``1.0.0``, ``2.0.0``, and
  ``3.0.0`` literals owned by :mod:`kalhas.application.run_planner` -
  raises :class:`UnsupportedRuntimeVersionError` before the first store
  read, before any stored authority is inspected, and before any matrix or
  plan is built. Historical runtimes keep their exact meaning in their
  untouched services.

- **Stored authority only.** The exact tenant-scoped
  :class:`~kalhas.contracts.v1.campaign.CampaignSpec` and
  :class:`~kalhas.contracts.v1.campaign.CampaignStatus` (state exactly
  ``COMPILED``), the scenario, the verified compiled world and manifest,
  the exact stored ordered
  :class:`~kalhas.contracts.v1.strategy.StrategyCandidate` collection, the
  stored :class:`~kalhas.contracts.v1.adaptive_policy.AdaptivePolicy`, the
  stored :class:`~kalhas.contracts.v1.campaign_decision.CampaignDecisionPolicy`,
  the stored-vs-embedded uncertainty-model consistency, the stored runtime-4
  executions, and the stored runtime-3 executions plus observation sets are
  loaded and verified - never accepted from the caller. The caller supplies
  only the deterministic tenant and campaign identifiers.

- **One matrix, zero re-planning.** The
  :class:`~kalhas.contracts.v1.world_realization.CampaignWorldRealizationMatrix`
  is built **exactly once** from the campaign's ordered seed ensemble, the
  verified world, and the catalog/uncertainty-model authority. The stored
  runtime-4 adaptive :class:`~kalhas.contracts.v1.run_plan.RunPlan` tuple is
  loaded and verified (exactly one plan per campaign seed, in the exact
  campaign seed order, the exact ``4.0.0`` runtime literal, and the policy's
  initial-action strategy anchor) and is the sole source of adaptive run
  identities: nothing is planned here. The accepted pure runtime-3 planner
  :func:`~kalhas.application.run_planner.plan_realization_runs` is called
  **exactly once** - solely to recompute the expected static runtime-3 plan
  matrix over the verified world, the exact stored candidates, the ordered
  seed ensemble, the recorded ``campaign.created_at``, and the per-seed
  realizations of the single matrix - and its result is the authoritative
  expected static (candidate, seed) plan key set plus planning input-hash
  authority. No stored runtime-3 plan tuple is read, rewritten, or
  reinterpreted, no second matrix and no additional planner call exist, and
  no policy rule is evaluated and no observation drawn anywhere.

- **Per-arm verified evidence, never recomputed outcomes.** The adaptive arm
  reads exactly one stored
  :class:`~kalhas.contracts.v1.adaptive_trajectory_execution.AdaptiveRunTrajectoryExecution`
  per seed through the strictly revalidating, cross-authority-verified store
  getter, plus the recorded COMPLETE
  :class:`~kalhas.contracts.v1.execution.RunStatus`. Each static arm reads
  exactly one stored
  :class:`~kalhas.contracts.v1.realization_trajectory_execution.RealizationRunTrajectoryExecution`
  and one stored
  :class:`~kalhas.contracts.v1.realization_run_metric_observation.RealizationRunMetricObservationSet`
  per (candidate, seed), each strictly revalidated, with the execution's
  complete recorded provenance required to equal the authoritative record
  field for field (the accepted provenance verifier plus exact field
  agreement, including the planning input hash whose runtime-3 digest
  covers the seed's shared realization content hash). Nothing is ever
  re-executed, re-sampled, or repaired.

- **Exact binding-provenance extraction.** The authoritative objective
  sequence is the embedded world's
  :class:`~kalhas.contracts.v1.objective_evaluation.ScenarioEvaluationProfile`
  binding order, which the stored decision policy's objective-weight
  snapshot order must equal exactly. For the adaptive arm, per-objective raw
  values are extracted from ``trajectory_results_by_decision[-1]`` (the last
  decision's realized final states) by matching each
  :class:`~kalhas.contracts.v1.metric_observation.DomainMetricObservationBinding`'s
  full state-model provenance - the same matching rule and the same strict
  raw-value extraction (``raw_value_matches_numeric_kind``, no coercion) as
  the established runtime-3 extraction service. For each static arm the
  verified stored observation set supplies the identical provenance records;
  every objective metric must appear exactly once per arm per seed.

- **Seed-major pairing.** The ordered campaign seed ensemble is the pairing
  axis. Paired deltas are computed seed-major with
  :func:`~kalhas.application.campaign_decision_statistics.paired_delta_vector`
  and
  :func:`~kalhas.application.campaign_decision_statistics.paired_delta_statistics`
  under the stored decision policy's tie tolerance, with the adaptive arm as
  the canonical lower side and each static arm as the higher side (positive
  deltas mean the static arm is worse). Deltas are exact per-index
  differences in the exact seed order - never set-matched. Pair records are
  ordered pair-major, objective-minor using the stable positional formula
  ``first*(S-1) + (second if second<first else second-1)``.

- **Arm identity, never the planning anchor.** The adaptive arm's identity is
  the stored policy's ``policy_id`` + ``adaptive_policy_content_hash``; every
  static arm's identity is its ``strategy_candidate_id`` +
  ``strategy_content_hash``. The runtime-4 ``RunPlan.strategy_candidate_id``
  is read **only** as the initial-action strategy anchor and never as the
  comparison identity: execution is policy-driven and may switch away from
  the anchor's strategy, and the aggregate therefore reports switch evidence
  separately.

- **Fairness receipts (ADR-004 D28-03).** Per-(seed, candidate) alignment
  receipts prove identical realization identity and content hash across the
  adaptive and static arms of the same seed (plus identical world identity
  and authoritative seed content hash - the static side's seed content hash
  is proven by its verified planning input hash, whose runtime-3 digest
  covers exactly that seed hash). Per-seed noise summaries re-verify every
  observed state-field adaptive
  :class:`~kalhas.contracts.v1.runtime_observation.RuntimeObservationEvent`'s
  noise provenance: the frozen ``kalhas-observation-noise-v1`` domain and
  ``sha256-counter-v1`` sampler literals, the local draw index, and the
  noise coordinate reconstructed from the event's own recorded provenance
  must equal the coordinate reconstructed from the verified authority chain
  (world, seed, declaration, source step, draw) via
  :func:`~kalhas.application.runtime_observation_event_identity.observation_noise_coordinate`.
  External-input events and missing events forbid fresh noise by contract.
  Static runtime-3 executions carry no observation-noise surface at all, so
  the shared exogenous coordinates can never differ across arms.

- **Fail closed, atomically.** Missing, foreign, corrupt, reordered,
  duplicated, mixed-runtime, or contradictory campaign/world/candidate/
  policy/decision-policy/uncertainty/realization/execution/observation
  authority fails closed with the narrowest established typed domain error
  before any evidence is returned: there is no partial output, no repair, no
  default, and no write of any kind. Raw ``AttributeError``/``KeyError``/
  ``IndexError``/``TypeError``/``ValueError`` escaping from untrusted or
  stored authority inspection are converted to the established safe typed
  error.

- **Forbidden surfaces.** No store write, update, or delete; no LEGION
  or NEXUS call; no execution; no replay; no policy evaluation or state
  transition; no observation or noise draw; no clock; no global RNG; no
  provider, network, callback, dynamic import, ``eval``, or ``exec``.
  The module is pure with respect to repository/application state and the
  returned aggregate is detached: mutating a returned object cannot alter
  any stored authority or a fresh later derivation. No minimax, regret,
  dominance, target-feasibility, brief, or selection logic exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, cast

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.adaptive_policy_identity import verify_adaptive_policy_identity
from kalhas.application.adaptive_run_planner import ADAPTIVE_RUNTIME_VERSION
from kalhas.application.adaptive_trajectory_execution_identity import adaptive_run_input_hash
from kalhas.application.campaign_decision_errors import (
    CampaignDecisionPolicyIntegrityError,
    CampaignDecisionPolicyNotFoundError,
)
from kalhas.application.campaign_decision_statistics import (
    PairedDeltaSummary,
    paired_delta_statistics,
    paired_delta_vector,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    KalhasDomainError,
    ScenarioNotFoundError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_realization_run_metric_observation_set,
    revalidate_stored_realization_run_trajectory_execution,
    revalidate_stored_world_uncertainty_model,
)
from kalhas.application.realization_errors import (
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
)
from kalhas.application.realization_identity import verify_realization_provenance
from kalhas.application.realization_run_metric_observation_service import (
    _embedded_scenario,
    _verify_binding_provenance,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
)
from kalhas.application.runtime_observation_event_identity import (
    OBSERVATION_NOISE_DOMAIN_LITERAL,
    OBSERVATION_NOISE_SAMPLER_VERSION,
    observation_noise_coordinate,
)
from kalhas.application.strategy_trajectory_service import strategy_candidate_content_hash
from kalhas.application.world_integrity import (
    VerifiedWorldCatalog,
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.application.world_realization_builder import build_campaign_world_realization_matrix
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.campaign_decision import CampaignDecisionPolicy
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.objective_evaluation import ObjectiveMetricBinding
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import RealizationRunTrajectoryExecution
from kalhas.contracts.v1.run_metric_observation import raw_value_matches_numeric_kind
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    RuntimeObservationDeclaration,
    RuntimeObservationEvent,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

#: The additive adaptive runtime version. Exactly ``4.0.0`` is accepted
#: for adaptive-vs-static comparison evidence; every other value -
#: including the historical ``1.0.0``, ``2.0.0``, and ``3.0.0`` literals
#: owned by :mod:`kalhas.application.run_planner` - is rejected before any
#: store read or other authority inspection.
RUNTIME_VERSION: Literal["4.0.0"] = ADAPTIVE_RUNTIME_VERSION


class _StaticArmIdentity(NamedTuple):
    """The immutable identity of one static (runtime-3) arm."""

    strategy_candidate_id: str
    strategy_content_hash: str


class _ObjectivePairEvidence(NamedTuple):
    """The complete derived paired evidence of one (arm pair, objective)."""

    pair_position: int
    objective_position: int
    objective_id: str
    direction: str
    normalization_scale: float
    target: float | None
    static_strategy_candidate_id: str
    ordered_seed_ids: tuple[str, ...]
    ordered_adaptive_values: tuple[float, ...]
    ordered_static_values: tuple[float, ...]
    ordered_paired_deltas: tuple[float, ...]
    summary: PairedDeltaSummary


class _SeedAlignmentReceipt(NamedTuple):
    """Proof that one seed's exogenous conditions are identical across arms.

    The static seed content hash is the authoritative recomputed
    ``seed_content_hash``; its agreement with the static arm's consumed
    seed is proven by the static execution's verified planning input hash,
    whose runtime-3 digest covers exactly that seed content hash.
    """

    scenario_seed_id: str
    static_strategy_candidate_id: str
    adaptive_world_realization_id: str
    static_world_realization_id: str
    world_realization_content_hash: str
    adaptive_world_content_hash: str
    static_world_content_hash: str
    adaptive_seed_content_hash: str
    static_seed_content_hash: str


class _SwitchEvidence(NamedTuple):
    """One recorded adaptive policy switch, as evidence only."""

    scenario_seed_id: str
    decision_step: int
    old_action_id: str
    new_action_id: str
    left_initial_action_strategy_anchor: bool


class _SwitchSummary(NamedTuple):
    """The immutable per-seed adaptive switch summary."""

    scenario_seed_id: str
    initial_action_id: str
    initial_action_strategy_anchor: str
    switch_count: int
    switches: tuple[_SwitchEvidence, ...]


class _NoiseSummary(NamedTuple):
    """The immutable per-seed adaptive observation-noise summary.

    ``all_noise_coordinates_verified`` is ``True`` exactly when every
    observed state-field event reproduced the frozen ADR-004 coordinate
    construction from its recorded provenance and no external-input event
    carried fresh noise; static runtime-3 executions carry no observation-
    noise surface at all, so shared coordinates are byte-identical across
    arms by construction.
    """

    scenario_seed_id: str
    observed_event_count: int
    noise_draw_event_count: int
    all_noise_coordinates_verified: bool


@dataclass(frozen=True)
class AdaptiveStaticComparisonEvidence:
    """The complete immutable derived comparison evidence of one campaign.

    A private, unpersisted aggregate (ADR-004 D28-04): arm identities, the
    exact campaign seed order, the authoritative objective order, the
    complete pair-major/objective-minor paired-delta evidence, the per-seed
    alignment receipts, and the per-seed adaptive switch and observation-
    noise summaries. It is derived evidence only: nothing here selects,
    ranks, recommends, or decides anything, and no field can express a
    persisted authority.
    """

    campaign_id: str
    scenario_id: str
    world_version_id: str
    world_content_hash: str
    adaptive_policy_id: str
    adaptive_policy_content_hash: str
    static_arms: tuple[_StaticArmIdentity, ...]
    ordered_seed_ids: tuple[str, ...]
    ordered_objective_ids: tuple[str, ...]
    objective_pairs: tuple[_ObjectivePairEvidence, ...]
    seed_alignment_receipts: tuple[_SeedAlignmentReceipt, ...]
    switch_summaries: tuple[_SwitchSummary, ...]
    noise_summaries: tuple[_NoiseSummary, ...]
    tie_tolerance: float
    minimum_sample_count: int


def _reject(tenant_id: str, campaign_id: str, reason: str) -> AdaptivePolicyBindingValidationError:
    """A safe typed comparison-authority failure with an internal reason."""
    return AdaptivePolicyBindingValidationError(tenant_id, campaign_id, reason=reason)


def _objective_pair_position(first: int, second: int, strategy_count: int) -> int:
    """The stable positional formula ``first*(S-1) + (second if second<first else second-1)``.

    The established unordered-pair index over ``strategy_count`` sides,
    reused so any future embedded comparison record can locate the same
    pair without re-deriving a new convention. The adaptive side occupies
    position ``first = 0`` and every static arm takes one of the positions
    ``second = 1..S-1`` in the campaign candidate order.
    """
    return first * (strategy_count - 1) + (second if second < first else second - 1)


def _load_verified_world(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
) -> WorldVersion:
    """Load and verify the campaign's exact scenario/world/manifest authority."""
    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="world authority missing") from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="world authority corrupt") from exc
    return world


def _verify_stored_embedded_model_consistency(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    embedded: WorldUncertaintyModel | None,
) -> WorldUncertaintyModel | None:
    """Enforce the established stored-vs-embedded uncertainty-model rules."""
    if embedded is not None:
        try:
            stored = store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError as exc:
            raise _reject(
                tenant_id, campaign_id, reason="stored uncertainty model missing"
            ) from exc
        revalidate_stored_world_uncertainty_model(stored, tenant_id, scenario_id)
        verify_world_uncertainty_model_identity(
            stored, tenant_id=tenant_id, scenario_id=scenario_id
        )
        if stored.model_dump(mode="json") != embedded.model_dump(mode="json"):
            raise _reject(
                tenant_id, campaign_id, reason="stored and embedded uncertainty model mismatch"
            )
        return stored
    try:
        store.get_world_uncertainty_model(tenant_id, scenario_id)
    except WorldUncertaintyModelNotFoundError:
        return None
    raise _reject(
        tenant_id, campaign_id, reason="stored uncertainty model exists without an embedded model"
    )


def _load_and_verify_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
) -> AdaptivePolicy:
    """Load and verify the exact stored runtime-4 policy for this authority chain."""
    try:
        policy = store.get_adaptive_policy(tenant_id, campaign_id)
    except AdaptivePolicyNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy authority missing") from exc
    except AdaptivePolicyIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy authority corrupt") from exc
    if (
        policy.runtime_version != RUNTIME_VERSION
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != campaign.scenario_id
        or policy.world_version_id != world.identifier
        or policy.world_content_hash != world.content_hash
    ):
        raise _reject(
            tenant_id,
            campaign_id,
            reason="campaign/policy/scenario/world/runtime identity mismatch",
        )
    try:
        verify_adaptive_policy_identity(
            policy,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=campaign.scenario_id,
            world_version_id=world.identifier,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
        )
    except AdaptivePolicyIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy identity mismatch") from exc
    return policy


def _load_exact_candidates(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
) -> tuple[StrategyCandidate, ...]:
    """Load the exact stored ordered candidate collection (order = campaign order)."""
    try:
        stored_candidates = store.get_strategy_candidates(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="strategy candidate authority missing"
        ) from exc
    if not stored_candidates:
        raise _reject(tenant_id, campaign_id, reason="strategy candidate authority missing")
    for candidate in stored_candidates:
        if candidate.tenant_id != tenant_id:
            raise _reject(tenant_id, campaign_id, reason="strategy candidate tenant mismatch")
    if [candidate.identifier for candidate in stored_candidates] != list(
        campaign.strategy_candidate_ids
    ):
        raise _reject(
            tenant_id, campaign_id, reason="stored strategy candidate collection mismatch"
        )
    return stored_candidates


def _load_and_verify_decision_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    catalog: VerifiedWorldCatalog,
) -> CampaignDecisionPolicy:
    """Load and verify the stored campaign decision policy for this authority chain.

    The store's read-time revalidation and identity verification run first
    (missing raises the typed not-found error, corrupt raises the typed
    integrity error); the comparison then requires exact agreement with the
    campaign, scenario, world identity/hash, and the embedded evaluation
    profile - the policy's authoritative objective-weight snapshot order
    must equal the profile's binding order exactly, so the derived evidence
    uses exactly the authoritative objective sequence.
    """
    try:
        policy = store.get_campaign_decision_policy(tenant_id, campaign_id)
    except CampaignDecisionPolicyNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="decision policy authority missing") from exc
    except CampaignDecisionPolicyIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="decision policy authority corrupt") from exc
    if (
        policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != campaign.scenario_id
        or policy.world_version_id != world.identifier
        or policy.world_content_hash != world.content_hash
    ):
        raise _reject(
            tenant_id,
            campaign_id,
            reason="campaign/decision-policy/scenario/world identity mismatch",
        )
    profile = catalog.evaluation_profile
    if profile is None:
        raise _reject(tenant_id, campaign_id, reason="embedded evaluation profile missing")
    if (
        policy.evaluation_profile_id != profile.identifier
        or policy.evaluation_profile_content_hash != profile.content_hash
    ):
        raise _reject(tenant_id, campaign_id, reason="decision policy evaluation-profile mismatch")
    snapshot_ids = [snapshot.objective_id for snapshot in policy.objective_weight_snapshots]
    if snapshot_ids != [binding.objective_id for binding in profile.bindings]:
        raise _reject(
            tenant_id, campaign_id, reason="decision policy objective snapshot order mismatch"
        )
    return policy


def _build_matrix_exactly_once(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    state_models: tuple[Any, ...],
    model: WorldUncertaintyModel | None,
    tenant_id: str,
    campaign_id: str,
) -> Any:
    """Build the campaign realization matrix exactly once; typed failures only."""
    try:
        return build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=state_models,
            model=model,
        )
    except (WorldRealizationIntegrityError, WorldRealizationSamplingError) as exc:
        raise _reject(tenant_id, campaign_id, reason="world realization derivation failed") from exc


def _load_and_verify_adaptive_plans(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    policy: AdaptivePolicy,
) -> tuple[RunPlan, ...]:
    """Load and verify the stored runtime-4 adaptive RunPlan tuple.

    Exactly one plan per campaign seed must exist, in the exact campaign
    seed order, carrying the exact ``4.0.0`` runtime literal and the
    policy's initial-action strategy anchor. The stored tuple is only
    read: it is never re-planned, reinterpreted, rewritten, or executed.
    """
    try:
        stored_plans = store.get_run_plans(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="stored run-plan authority missing") from exc
    if not stored_plans:
        raise _reject(tenant_id, campaign_id, reason="stored run-plan authority missing")
    if any(plan.runtime_version != RUNTIME_VERSION for plan in stored_plans):
        raise _reject(tenant_id, campaign_id, reason="stored run-plan runtime mismatch")
    if any(plan.tenant_id != tenant_id or plan.campaign_id != campaign_id for plan in stored_plans):
        raise _reject(tenant_id, campaign_id, reason="stored run-plan ownership mismatch")
    seed_ids = [seed.identifier for seed in campaign.seed_ensemble]
    if [plan.scenario_seed_id for plan in stored_plans] != seed_ids:
        raise _reject(tenant_id, campaign_id, reason="stored adaptive plan seed order mismatch")
    anchor_ids = {
        action.strategy_candidate_id
        for action in policy.actions
        if action.action_id == policy.initial_action_id
    }
    if len(anchor_ids) != 1:
        raise _reject(tenant_id, campaign_id, reason="policy initial action anchor unresolved")
    anchor = anchor_ids.pop()
    if any(plan.strategy_candidate_id != anchor for plan in stored_plans):
        raise _reject(tenant_id, campaign_id, reason="stored adaptive plan anchor mismatch")
    return stored_plans


def _verify_static_seed_authority(
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    stored_candidates: tuple[StrategyCandidate, ...],
    matrix: Any,
) -> dict[tuple[str, str], RunPlan]:
    """Recompute the expected static runtime-3 plan matrix exactly once.

    The accepted pure runtime-3 planner is called exactly once over the
    verified world, the exact stored candidates, the ordered seed ensemble,
    the recorded ``campaign.created_at``, and the per-seed realizations of
    the single matrix already built. The recomputed tuple is the
    authoritative expected static (candidate, seed) plan key set plus the
    planning input-hash authority; no stored runtime-3 plan tuple is read,
    rewritten, or reinterpreted, and no second matrix or additional planner
    call exists.
    """
    realizations = {
        realization.scenario_seed_id: realization for realization in matrix.realizations
    }
    expected_plans = plan_realization_runs(
        campaign_id=campaign.identifier,
        tenant_id=tenant_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=stored_candidates,
        seeds=campaign.seed_ensemble,
        created_at=campaign.created_at,
        realizations=realizations,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    )
    keys = [(plan.strategy_candidate_id, plan.scenario_seed_id) for plan in expected_plans]
    if len(keys) != len(set(keys)):
        raise _reject(tenant_id, campaign_id, reason="static seed authority derivation ambiguous")
    return {(plan.strategy_candidate_id, plan.scenario_seed_id): plan for plan in expected_plans}


def _require_complete_adaptive_run_status(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    run_id: str,
) -> None:
    """Require the recorded COMPLETE runtime status of one executed adaptive run."""
    try:
        status = store.get_run_status(tenant_id, run_id)
    except KalhasDomainError as exc:
        raise _reject(tenant_id, campaign_id, reason="run status authority missing") from exc
    if (
        status.tenant_id != tenant_id
        or status.identifier != f"status-{run_id}"
        or status.run_id != run_id
        or status.campaign_id != campaign_id
    ):
        raise _reject(tenant_id, campaign_id, reason="run status authority mismatch")
    if status.state is not RunState.COMPLETE:
        raise _reject(tenant_id, campaign_id, reason="run status is not complete")


def _load_adaptive_execution(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    run_plan: RunPlan,
) -> AdaptiveRunTrajectoryExecution:
    """Load one stored runtime-4 execution through the verified store getter.

    Missing and corrupt executions fail closed with the safe typed
    validation error; the getter itself strictly revalidates and
    cross-authority verifies the stored record on every read.
    """
    run_id = f"run-{run_plan.identifier}"
    try:
        return store.get_adaptive_run_trajectory_execution(tenant_id=tenant_id, run_id=run_id)
    except KalhasDomainError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="adaptive execution authority missing or corrupt"
        ) from exc


def _load_realization_execution(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    run_id: str,
) -> RealizationRunTrajectoryExecution:
    """Load one stored runtime-3 execution and strictly revalidate it."""
    try:
        execution = store.get_realization_run_trajectory_execution(tenant_id, run_id)
    except RealizationRunTrajectoryExecutionNotFoundError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="runtime-3 execution authority missing"
        ) from exc
    try:
        revalidate_stored_realization_run_trajectory_execution(execution, run_id)
    except RealizationRunTrajectoryExecutionIntegrityError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="runtime-3 execution authority corrupt"
        ) from exc
    return execution


def _load_realization_observation_set(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    run_id: str,
) -> RealizationRunMetricObservationSet:
    """Load one stored runtime-3 observation set and strictly revalidate it."""
    try:
        observation_set = store.get_realization_run_metric_observation_set(tenant_id, run_id)
    except RealizationRunMetricObservationNotFoundError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="runtime-3 observation authority missing"
        ) from exc
    try:
        revalidate_stored_realization_run_metric_observation_set(observation_set, run_id)
    except RealizationRunMetricObservationIntegrityError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="runtime-3 observation authority corrupt"
        ) from exc
    return observation_set


def _verify_adaptive_execution_authority(
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    policy: AdaptivePolicy,
    run_plan: RunPlan,
    realization_by_seed: dict[str, Any],
    execution: AdaptiveRunTrajectoryExecution,
) -> None:
    """Require exact agreement between a stored runtime-4 execution and its chain.

    The store getter has already cross-verified the recorded run
    authorities; this check binds the execution to the exact comparison
    authority chain this module verified independently: campaign, world
    identity/hash, seed identity/hash and ensemble membership, policy
    identity/hash, runtime literal, recorded run plan, and realization
    provenance against the campaign's authoritative single matrix.

    The execution's ``input_hash`` is the frozen wide runtime-4 digest
    (``kalhas-adaptive-run-input-v1``) whose exact ingredient set covers
    the run-plan identity, the plan's recorded planning input hash, the
    world, seed, realization, and policy authorities, the plan-set hash,
    the optional external bundle pair, and the causal horizon - it is
    never equal to the plan's own narrow planning digest (ADR-004
    D28-03/D28-04 authority separation), so it is verified here by exact
    recomputation from this module's independently verified authority
    chain, mirroring the accepted execution-authority verifier.
    """
    if (
        execution.tenant_id != tenant_id
        or execution.run_id != f"run-{run_plan.identifier}"
        or execution.campaign_id != campaign_id
        or execution.run_plan_id != run_plan.identifier
        or execution.world_version_id != world.identifier
        or execution.world_content_hash != world.content_hash
        or execution.runtime_version != RUNTIME_VERSION
        or execution.adaptive_policy_identifier != policy.identifier
        or execution.policy_id != policy.policy_id
        or execution.adaptive_policy_content_hash != policy.content_hash
    ):
        raise _reject(tenant_id, campaign_id, reason="adaptive execution authority mismatch")
    if execution.scenario_seed_id != run_plan.scenario_seed_id:
        raise _reject(tenant_id, campaign_id, reason="adaptive execution seed authority mismatch")
    seed = next(
        (
            candidate
            for candidate in campaign.seed_ensemble
            if candidate.identifier == execution.scenario_seed_id
        ),
        None,
    )
    if seed is None or seed.tenant_id != tenant_id:
        raise _reject(tenant_id, campaign_id, reason="adaptive execution seed authority mismatch")
    if execution.seed_content_hash != seed_content_hash(seed):
        raise _reject(tenant_id, campaign_id, reason="adaptive execution seed hash mismatch")
    realization = realization_by_seed.get(execution.scenario_seed_id)
    if (
        realization is None
        or execution.world_realization_id != realization.identifier
        or execution.world_realization_content_hash != realization.content_hash
    ):
        raise _reject(tenant_id, campaign_id, reason="adaptive execution realization mismatch")
    # The causal run horizon is derived exclusively from the aggregate
    # evidence, exactly as the accepted execution-authority verifier
    # derives it; the contract already guarantees contiguous decision
    # steps, so the horizon is an exact non-negative integer.
    expected_input_hash = adaptive_run_input_hash(
        run_plan_id=run_plan.identifier,
        run_plan_input_hash=run_plan.input_hash,
        campaign_id=campaign_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=execution.scenario_seed_id,
        seed_content_hash_value=execution.seed_content_hash,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        adaptive_policy_identifier=policy.identifier,
        adaptive_policy_content_hash=policy.content_hash,
        trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
        external_observation_input_bundle_id=(execution.external_observation_input_bundle_id),
        external_observation_input_bundle_content_hash=(
            execution.external_observation_input_bundle_content_hash
        ),
        final_decision_step=len(execution.decision_events) - 1,
    )
    if execution.input_hash != expected_input_hash:
        raise _reject(tenant_id, campaign_id, reason="adaptive execution input hash mismatch")


def _verify_realization_execution_authority(
    *,
    tenant_id: str,
    campaign_id: str,
    world: WorldVersion,
    candidate: StrategyCandidate,
    seed: ScenarioSeed,
    realization: Any,
    uncertainty_model: WorldUncertaintyModel | None,
    expected_plan: RunPlan,
    execution: RealizationRunTrajectoryExecution,
) -> None:
    """Require a stored runtime-3 execution to equal its recomputed authority.

    The accepted provenance verifier re-derives the realization identity
    and content hash against the verified world, the recorded seed, and
    the world's embedded uncertainty model (or its verified absence - the
    exact authority the established runtime-3 run-input verification
    passes), so a realization drawn under an embedded model cannot be
    rejected and a model-less forgery cannot pass. Every recorded field
    of the stored execution must then equal the authoritative record -
    run, campaign, plan, world, strategy identity/content hash, seed,
    runtime literal, and planning input hash - so a tampered or foreign
    execution can never contribute a static sample.
    """
    try:
        verify_realization_provenance(
            run_id=execution.run_id,
            world=world,
            seed=seed,
            realization=realization,
            uncertainty_model=uncertainty_model,
        )
    except KalhasDomainError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="runtime-3 realization provenance mismatch"
        ) from exc
    if (
        execution.tenant_id != tenant_id
        or execution.campaign_id != campaign_id
        or execution.run_plan_id != expected_plan.identifier
        or execution.run_id != f"run-{expected_plan.identifier}"
        or execution.world_version_id != world.identifier
        or execution.world_content_hash != world.content_hash
        or execution.strategy_candidate_id != candidate.identifier
        or execution.strategy_content_hash != strategy_candidate_content_hash(candidate)
        or execution.scenario_seed_id != seed.identifier
        or execution.world_realization_id != realization.identifier
        or execution.world_realization_content_hash != realization.content_hash
        or execution.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION
        or execution.input_hash != expected_plan.input_hash
    ):
        raise _reject(tenant_id, campaign_id, reason="runtime-3 execution authority mismatch")


def _load_declarations(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    policy: AdaptivePolicy,
) -> dict[str, RuntimeObservationDeclaration]:
    """Load the policy-bound observation declarations through the verified getter.

    Exactly one declaration must resolve for every policy observation
    binding, keyed by logical observation identifier, carrying the exact
    ``4.0.0`` runtime literal and complete copied-agreement with the
    binding's recorded provenance.
    """
    declarations: dict[str, RuntimeObservationDeclaration] = {}
    for binding in policy.observation_bindings:
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, campaign.scenario_id, world.identifier, binding.observation_id
            )
        except KalhasDomainError as exc:
            raise _reject(
                tenant_id, campaign_id, reason="observation declaration authority missing"
            ) from exc
        if (
            declaration.runtime_version != RUNTIME_VERSION
            or declaration.identifier != binding.runtime_observation_declaration_id
            or declaration.content_hash != binding.runtime_observation_declaration_content_hash
            or declaration.observed_value_kind != binding.observed_value_kind
            or declaration.unit != binding.unit
            or declaration.missing_behavior != binding.missing_behavior
        ):
            raise _reject(
                tenant_id, campaign_id, reason="observation declaration authority mismatch"
            )
        declarations[binding.observation_id] = declaration
    return declarations


def _verify_noise_provenance(
    *,
    tenant_id: str,
    campaign_id: str,
    world: WorldVersion,
    seed: ScenarioSeed,
    declaration_by_id: dict[str, RuntimeObservationDeclaration],
    events: tuple[RuntimeObservationEvent, ...],
) -> _NoiseSummary:
    """Re-verify every observed state-field event's noise coordinate receipt.

    Each recorded ``RuntimeObservationEvent`` must carry the frozen ADR-004
    domain/sampler literals and a local draw index, and the noise
    coordinate reconstructed from the event's own recorded provenance
    (world hash, seed hash, declaration content hash, source step, draw)
    must equal the coordinate reconstructed from the verified authority
    chain - proof that policy branching consumed no different exogenous
    draw for the same shared coordinate. External-input events and missing
    events forbid fresh noise by contract. Any mismatch fails closed.
    """
    observed = [event for event in events if event.status == "observed"]
    verified = True
    for event in observed:
        if event.noise_domain_literal != OBSERVATION_NOISE_DOMAIN_LITERAL:
            verified = False
            break
        if event.noise_sampler_version != OBSERVATION_NOISE_SAMPLER_VERSION:
            verified = False
            break
        if event.source_kind == "state_field":
            declaration = declaration_by_id.get(event.observation_id)
            if declaration is None or event.noise_draw_index is None:
                verified = False
                break
            event_coordinate = observation_noise_coordinate(
                world_content_hash=event.world_content_hash,
                seed_content_hash=event.seed_content_hash,
                runtime_observation_declaration_content_hash=(
                    event.observation_declaration_content_hash
                ),
                source_step_index=event.source_step_index,
                draw_index=event.noise_draw_index,
            )
            authority_coordinate = observation_noise_coordinate(
                world_content_hash=world.content_hash,
                seed_content_hash=seed_content_hash(seed),
                runtime_observation_declaration_content_hash=declaration.content_hash,
                source_step_index=event.source_step_index,
                draw_index=event.noise_draw_index,
            )
            if (
                event_coordinate != authority_coordinate
                or event.observed_value_kind != declaration.observed_value_kind
                or event.observed_value_unit != declaration.unit
            ):
                verified = False
                break
        else:
            if event.applied_noise_value is not None or event.noise_draw_index is not None:
                verified = False
                break
    if not verified:
        raise _reject(tenant_id, campaign_id, reason="adaptive noise provenance receipt mismatch")
    noise_draws = sum(1 for event in observed if event.noise_draw_index is not None)
    return _NoiseSummary(
        scenario_seed_id=seed.identifier,
        observed_event_count=len(observed),
        noise_draw_event_count=noise_draws,
        all_noise_coordinates_verified=True,
    )


def _extract_adaptive_values(
    *,
    tenant_id: str,
    campaign_id: str,
    world: WorldVersion,
    profile_bindings: tuple[ObjectiveMetricBinding, ...],
    execution: AdaptiveRunTrajectoryExecution,
) -> dict[str, int | float]:
    """Extract per-metric raw values from the last decision's realized final states.

    The verified world's embedded ``DomainMetricObservationBinding`` records
    supply the exact authoritative state-model provenance of every profile
    metric (each provenance quadruple verified unique per metric via the
    established runtime-3 binding-provenance rule). Exactly one realized
    result of ``trajectory_results_by_decision[-1]`` - the last decision's
    realized final states - must match the metric's full provenance, and
    the raw value is extracted with the same strict
    ``raw_value_matches_numeric_kind`` rule as the established runtime-3
    extraction service, with no coercion ever.
    """
    if not execution.trajectory_results_by_decision:
        raise _reject(tenant_id, campaign_id, reason="adaptive execution carries no decisions")
    final_results = execution.trajectory_results_by_decision[-1]
    catalog = extract_world_catalog(world)
    provenance_by_metric: dict[str, DomainMetricObservationBinding] = {}
    for record in catalog.domain_metric_observations:
        _verify_binding_provenance(
            f"run-{execution.run_id}", record, catalog, _embedded_scenario(world)
        )
        if record.metric_id in provenance_by_metric:
            raise _reject(tenant_id, campaign_id, reason="observation binding metric is duplicated")
        provenance_by_metric[record.metric_id] = record
    values: dict[str, int | float] = {}
    for binding in profile_bindings:
        provenance_record = provenance_by_metric.get(binding.metric_id)
        if provenance_record is None:
            raise _reject(tenant_id, campaign_id, reason="observation binding record is missing")
        matches = [
            result
            for result in final_results
            if result.state_model_identifier == provenance_record.state_model_identifier
            and result.state_model_id == provenance_record.state_model_id
            and result.manifest_id == provenance_record.manifest_id
            and result.state_model_content_hash == provenance_record.state_model_content_hash
        ]
        if len(matches) != 1:
            raise _reject(
                tenant_id, campaign_id, reason="observation binding result is missing or ambiguous"
            )
        result = matches[0]
        if provenance_record.state_field_id not in result.final_state:
            raise _reject(
                tenant_id, campaign_id, reason="observation binding final state field is missing"
            )
        raw = result.final_state[provenance_record.state_field_id]
        if not raw_value_matches_numeric_kind(raw, provenance_record.state_field_value_kind):
            raise _reject(
                tenant_id,
                campaign_id,
                reason="observation raw value does not match its numeric kind",
            )
        values[binding.metric_id] = cast("int | float", raw)
    return values


def _static_values_by_metric(
    *,
    tenant_id: str,
    campaign_id: str,
    observation_set: RealizationRunMetricObservationSet,
) -> dict[str, int | float]:
    """The verified static observation set as a metric-keyed raw-value mapping.

    The stored observations are canonicalized by metric identifier, so
    every metric id must resolve to exactly one observation value.
    """
    values: dict[str, int | float] = {}
    for observation in observation_set.observations:
        if observation.metric_id in values:
            raise _reject(
                tenant_id, campaign_id, reason="runtime-3 observation metric is duplicated"
            )
        values[observation.metric_id] = observation.raw_value
    return values


def derive_adaptive_static_comparison_evidence(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    runtime_version: str = RUNTIME_VERSION,
) -> AdaptiveStaticComparisonEvidence:
    """Derive the complete adaptive-vs-static comparison evidence of one campaign.

    The single read-only entry point: the exact ``4.0.0`` runtime gate runs
    first; the complete stored authority chain is loaded and verified; the
    campaign realization matrix is built exactly once; the stored adaptive
    plan tuple is verified (never re-planned); the expected static plan
    matrix is recomputed exactly once with the accepted pure runtime-3
    planner; the stored per-seed runtime-4 executions and per-(candidate,
    seed) runtime-3 executions plus observation sets are loaded and bound
    to their authority chains; per-objective raw values are extracted with
    the exact binding-provenance rule; and the paired-delta evidence is
    computed seed-major with the contract-free numeric primitives. Every
    failure is atomic, typed, and write-free; the function is pure with
    respect to repository and application state. See the module docstring
    for the complete derivation semantics and forbidden surfaces.
    """
    try:
        if runtime_version != RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                runtime_version, operation="adaptive-vs-static comparison evidence"
            )
        if (
            type(tenant_id) is not str
            or type(campaign_id) is not str
            or not tenant_id
            or not campaign_id
        ):
            raise _reject(
                tenant_id if type(tenant_id) is str else "",
                campaign_id if type(campaign_id) is str else "",
                reason="tenant_id and campaign_id must be exact non-empty strings",
            )
        try:
            campaign = store.get_campaign(tenant_id, campaign_id)
        except CampaignNotFoundError as exc:
            raise _reject(tenant_id, campaign_id, reason="campaign authority missing") from exc
        if campaign.tenant_id != tenant_id or campaign.identifier != campaign_id:
            raise _reject(tenant_id, campaign_id, reason="campaign authority missing")
        try:
            status = store.get_campaign_status(tenant_id, campaign_id)
        except CampaignNotFoundError as exc:
            raise _reject(
                tenant_id, campaign_id, reason="campaign status authority missing"
            ) from exc
        if status.campaign_id != campaign_id or status.tenant_id != tenant_id:
            raise _reject(tenant_id, campaign_id, reason="campaign status authority mismatch")
        if status.state is not CampaignState.COMPILED:
            raise _reject(tenant_id, campaign_id, reason="campaign must be exactly COMPILED")
        try:
            store.get_scenario(tenant_id, campaign.scenario_id)
        except ScenarioNotFoundError as exc:
            raise _reject(tenant_id, campaign_id, reason="scenario authority missing") from exc
        world = _load_verified_world(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign
        )
        if world.tenant_id != tenant_id or world.source_scenario_id != campaign.scenario_id:
            raise _reject(
                tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
            )
        if campaign.world_version_id != world.identifier:
            raise _reject(tenant_id, campaign_id, reason="campaign world reference mismatch")
        stored_candidates = _load_exact_candidates(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign
        )
        if len(stored_candidates) < 2:
            raise _reject(tenant_id, campaign_id, reason="at least one static arm is required")
        catalog = extract_world_catalog(world)
        profile = catalog.evaluation_profile
        if profile is None:
            raise _reject(tenant_id, campaign_id, reason="embedded evaluation profile missing")
        policy = _load_and_verify_policy(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign, world=world
        )
        decision_policy = _load_and_verify_decision_policy(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            campaign=campaign,
            world=world,
            catalog=catalog,
        )
        model = _verify_stored_embedded_model_consistency(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=campaign.scenario_id,
            embedded=catalog.uncertainty_model,
        )
        matrix = _build_matrix_exactly_once(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=model,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
        )
        realization_by_seed = {
            realization.scenario_seed_id: realization for realization in matrix.realizations
        }
        adaptive_plans = _load_and_verify_adaptive_plans(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign, policy=policy
        )
        expected_static_plans = _verify_static_seed_authority(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            campaign=campaign,
            world=world,
            stored_candidates=stored_candidates,
            matrix=matrix,
        )
        declarations = _load_declarations(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            campaign=campaign,
            world=world,
            policy=policy,
        )
        seed_ids = tuple(seed.identifier for seed in campaign.seed_ensemble)
        bindings = profile.bindings
        metric_ids = [binding.metric_id for binding in bindings]
        if len(metric_ids) != len(set(metric_ids)):
            raise _reject(tenant_id, campaign_id, reason="profile metric binding is ambiguous")

        static_arm_ids = tuple(
            _StaticArmIdentity(
                strategy_candidate_id=candidate.identifier,
                strategy_content_hash=strategy_candidate_content_hash(candidate),
            )
            for candidate in stored_candidates
        )
        anchor = adaptive_plans[0].strategy_candidate_id
        anchor_actions = frozenset(
            action.action_id for action in policy.actions if action.strategy_candidate_id == anchor
        )
        static_seed_hash = seed_content_hash  # established primitive, applied per seed below

        adaptive_values_by_seed: dict[str, dict[str, int | float]] = {}
        static_values: dict[tuple[str, str], dict[str, int | float]] = {}
        receipts: list[_SeedAlignmentReceipt] = []
        switch_summaries: list[_SwitchSummary] = []
        noise_summaries: list[_NoiseSummary] = []

        for position, seed in enumerate(campaign.seed_ensemble):
            plan = adaptive_plans[position]
            adaptive_run_id = f"run-{plan.identifier}"
            _require_complete_adaptive_run_status(
                store, tenant_id=tenant_id, campaign_id=campaign_id, run_id=adaptive_run_id
            )
            execution = _load_adaptive_execution(
                store, tenant_id=tenant_id, campaign_id=campaign_id, run_plan=plan
            )
            _verify_adaptive_execution_authority(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                campaign=campaign,
                world=world,
                policy=policy,
                run_plan=plan,
                realization_by_seed=realization_by_seed,
                execution=execution,
            )
            noise_summaries.append(
                _verify_noise_provenance(
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                    world=world,
                    seed=seed,
                    declaration_by_id=declarations,
                    events=execution.observation_events,
                )
            )
            adaptive_values_by_seed[seed.identifier] = _extract_adaptive_values(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                world=world,
                profile_bindings=bindings,
                execution=execution,
            )
            switch_summaries.append(
                _SwitchSummary(
                    scenario_seed_id=seed.identifier,
                    initial_action_id=policy.initial_action_id,
                    initial_action_strategy_anchor=anchor,
                    switch_count=len(execution.switch_events),
                    switches=tuple(
                        _SwitchEvidence(
                            scenario_seed_id=seed.identifier,
                            decision_step=switch.decision_step,
                            old_action_id=switch.old_action_id,
                            new_action_id=switch.new_action_id,
                            left_initial_action_strategy_anchor=(
                                switch.old_action_id in anchor_actions
                            ),
                        )
                        for switch in execution.switch_events
                    ),
                )
            )
            seed_hash = static_seed_hash(seed)
            realization = realization_by_seed[seed.identifier]
            for candidate in stored_candidates:
                expected_plan = expected_static_plans[(candidate.identifier, seed.identifier)]
                static_run_id = f"run-{expected_plan.identifier}"
                static_execution = _load_realization_execution(
                    store, tenant_id=tenant_id, campaign_id=campaign_id, run_id=static_run_id
                )
                _verify_realization_execution_authority(
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                    world=world,
                    candidate=candidate,
                    seed=seed,
                    realization=realization,
                    uncertainty_model=model,
                    expected_plan=expected_plan,
                    execution=static_execution,
                )
                observation_set = _load_realization_observation_set(
                    store, tenant_id=tenant_id, campaign_id=campaign_id, run_id=static_run_id
                )
                static_values[(candidate.identifier, seed.identifier)] = _static_values_by_metric(
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                    observation_set=observation_set,
                )
                receipts.append(
                    _SeedAlignmentReceipt(
                        scenario_seed_id=seed.identifier,
                        static_strategy_candidate_id=candidate.identifier,
                        adaptive_world_realization_id=execution.world_realization_id,
                        static_world_realization_id=static_execution.world_realization_id,
                        world_realization_content_hash=execution.world_realization_content_hash,
                        adaptive_world_content_hash=execution.world_content_hash,
                        static_world_content_hash=static_execution.world_content_hash,
                        adaptive_seed_content_hash=execution.seed_content_hash,
                        static_seed_content_hash=seed_hash,
                    )
                )

        objective_pairs: list[_ObjectivePairEvidence] = []
        arm_side_count = len(stored_candidates) + 1
        for arm_position, arm in enumerate(static_arm_ids, start=1):
            for objective_position, binding in enumerate(bindings):
                adaptive_values = tuple(
                    float(adaptive_values_by_seed[seed_id][binding.metric_id])
                    for seed_id in seed_ids
                )
                static_arm_values = tuple(
                    float(static_values[(arm.strategy_candidate_id, seed_id)][binding.metric_id])
                    for seed_id in seed_ids
                )
                deltas = paired_delta_vector(
                    adaptive_values,
                    static_arm_values,
                    direction=binding.direction,
                    normalization_scale=binding.normalization_scale,
                    target=binding.target,
                )
                summary = paired_delta_statistics(
                    deltas, tie_tolerance=decision_policy.tie_tolerance
                )
                objective_pairs.append(
                    _ObjectivePairEvidence(
                        pair_position=_objective_pair_position(0, arm_position, arm_side_count),
                        objective_position=objective_position,
                        objective_id=binding.objective_id,
                        direction=str(binding.direction),
                        normalization_scale=binding.normalization_scale,
                        target=binding.target,
                        static_strategy_candidate_id=arm.strategy_candidate_id,
                        ordered_seed_ids=seed_ids,
                        ordered_adaptive_values=adaptive_values,
                        ordered_static_values=static_arm_values,
                        ordered_paired_deltas=deltas,
                        summary=summary,
                    )
                )
        return AdaptiveStaticComparisonEvidence(
            campaign_id=campaign.identifier,
            scenario_id=campaign.scenario_id,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            adaptive_policy_id=policy.policy_id,
            adaptive_policy_content_hash=policy.content_hash,
            static_arms=static_arm_ids,
            ordered_seed_ids=seed_ids,
            ordered_objective_ids=tuple(binding.objective_id for binding in bindings),
            objective_pairs=tuple(objective_pairs),
            seed_alignment_receipts=tuple(receipts),
            switch_summaries=tuple(switch_summaries),
            noise_summaries=tuple(noise_summaries),
            tie_tolerance=decision_policy.tie_tolerance,
            minimum_sample_count=decision_policy.minimum_sample_count,
        )
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        raise _reject(
            tenant_id if type(tenant_id) is str else "",
            campaign_id if type(campaign_id) is str else "",
            reason="comparison evidence inspection violated its contract",
        ) from exc


__all__ = [
    "RUNTIME_VERSION",
    "AdaptiveStaticComparisonEvidence",
    "derive_adaptive_static_comparison_evidence",
]
