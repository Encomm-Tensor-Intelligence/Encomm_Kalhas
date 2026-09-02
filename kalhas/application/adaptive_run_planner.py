"""Pure runtime-4 adaptive run planning: one RunPlan per seed (H28-S08A).

This module is the deterministic, domain-neutral planning foundation for
adaptive runtime ``4.0.0`` campaigns. It is additive: runtimes ``1.0.0``
(structural), ``2.0.0`` (trajectory), and ``3.0.0`` (realization-aware)
keep their exact historical meaning in
:mod:`kalhas.application.run_planner`, and nothing here reinterprets,
rewrites, re-dispatches, or extends them (ADR-004).

Planning semantics (frozen by this slice):

- **One plan per seed, never one per strategy.** ``plan_adaptive_runs``
  returns exactly one :class:`~kalhas.contracts.v1.run_plan.RunPlan` per
  entry of the caller's ordered seed ensemble, in the caller's exact
  seed order. The seed ensemble is the sole source of run multiplicity;
  the planner never iterates strategies and never sorts, deduplicates,
  or reorders seeds.

- **One shared realization authority per seed.** Every seed must resolve
  its corresponding strategy-independent
  :class:`~kalhas.contracts.v1.world_realization.WorldRealization` from
  the caller-supplied mapping (exactly the authority the campaign
  realization matrix derives once per seed). A missing, foreign, or
  disagreeing realization fails closed with a typed domain error before
  any plan is returned; the planner never derives, samples, repairs, or
  substitutes a realization, and no policy attribute can influence which
  realization a seed receives. All verification happens in a complete
  pass before the first plan is constructed, so a failure never yields
  partial output.

- **The historical ``strategy_candidate_id`` field carries the
  initial-action strategy anchor.** ``RunPlan.strategy_candidate_id`` is
  a required historical field of runtimes 1-3. For runtime 4 the planner
  populates it only with the ``strategy_candidate_id`` of the exact
  bound policy action referenced by ``policy.initial_action_id``,
  resolved uniquely, as a stable truthful planning anchor. Runtime-4
  execution remains fully policy-driven: the executed action at every
  decision step is selected by the bound policy state machine, and this
  anchor does not turn the run into a static-strategy run. The anchor
  exists so the collision-safe plan identifier and the recorded
  provenance reference one deterministic strategy identity per plan.

- **Identifier and authority binding.** The plan identifier reuses the
  existing collision-safe
  :func:`kalhas.application.run_planner.run_plan_identifier`
  construction unchanged, bound to the campaign, the world, the
  initial-action strategy anchor, the seed, and the runtime. The plan's
  ``input_hash`` is the deterministic
  :func:`adaptive_run_input_hash` digest over the runtime version, the
  verified world content hash, the complete bound
  :class:`~kalhas.contracts.v1.adaptive_policy.AdaptivePolicy`
  authority, the complete :class:`~kalhas.contracts.v1.scenario.ScenarioSeed`
  authority, and the seed's shared world-realization content hash. A
  changed policy is a different immutable authority and therefore a
  different ``input_hash`` and, through its campaign/run authority, a
  different plan set; no in-place policy revision surface exists or is
  created here (ADR-004 D28-04).

- **Fairness invariant (Phase 28 / ADR-004 D28-03).** The planner
  consumes no randomness and no clock: every input is passed in and the
  ``created_at`` timestamp is caller-supplied. Adaptive branch counts,
  rule counts, rule evaluation, and policy evaluation never enter any
  coordinate of this module - compared policies receive the same ordered
  seeds and the same per-seed realization authority, and the exogenous
  realization coordinate depends only on world, seed, and model
  authority. Policy rules influence exactly one output byte sequence:
  the ``input_hash`` digest that binds the policy authority into the
  plan.

- **Forbidden surfaces.** No store access, no executable policy
  evaluation, no condition evaluation, no callback, no provider, no
  network, no filesystem, no global RNG, no wall clock, no mutation of
  any input, and no partial result on failure. The planner is a pure
  function of its arguments and consumes only canonical hashing and
  frozen contract data.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
)
from kalhas.application.domain_errors import KalhasDomainError, UnsupportedRuntimeVersionError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.run_planner import run_plan_identifier
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy, BoundAdaptiveAction
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime
from kalhas.contracts.v1.world_realization import WorldRealization

#: The additive adaptive runtime version. Exactly ``4.0.0`` is accepted
#: for adaptive planning; every other value - including the historical
#: ``1.0.0``, ``2.0.0``, and ``3.0.0`` literals owned by
#: :mod:`kalhas.application.run_planner` - is rejected before any
#: authority is inspected or any plan is built.
ADAPTIVE_RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"


def adaptive_run_input_hash(
    *,
    runtime_version: str,
    world_content_hash: str,
    policy: AdaptivePolicy,
    seed: ScenarioSeed,
    world_realization_content_hash: str,
) -> str:
    """Deterministic SHA-256 over the complete runtime-4 planning inputs.

    The canonical payload covers, exactly: the runtime version, the
    verified world content hash, the complete bound
    :class:`AdaptivePolicy` authority (every field, including the
    observation-binding catalog, bound actions, rules, state-machine
    declarations, identity, content hash, and ``bound_at``), the
    complete :class:`ScenarioSeed` authority, and the seed's shared
    world-realization content hash. The payload renders through the
    established ``canonical_json`` (sorted keys, no insignificant
    whitespace) and ``sha256_hex`` conventions, so the digest is a pure
    function of its arguments: no clock, no global RNG, no provider, no
    callback, no network, no store access, no mutation, and no
    executable policy evaluation of any kind.

    The full seed dump covers exactly the bytes the established
    ``seed_content_hash`` helper digests, so the seed's authoritative
    content identity is bound through its complete canonical authority.
    """
    canonical = canonical_json(
        {
            "policy": policy.model_dump(mode="json"),
            "runtime_version": runtime_version,
            "seed": seed.model_dump(mode="json"),
            "world_content_hash": world_content_hash,
            "world_realization_content_hash": world_realization_content_hash,
        }
    )
    return sha256_hex(canonical)


def _reject_policy_authority(
    policy: AdaptivePolicy, reason: str
) -> AdaptivePolicyBindingValidationError:
    """A safe typed policy-authority failure with an internal reason."""
    return AdaptivePolicyBindingValidationError(policy.tenant_id, policy.campaign_id, reason=reason)


def _verify_policy_authority(
    policy: AdaptivePolicy,
    *,
    tenant_id: str,
    campaign_id: str,
    world_version_id: str,
    world_content_hash: str,
) -> None:
    """Verify the bound policy authority before any plan is built.

    The policy must be the exact immutable :class:`AdaptivePolicy`
    contract type, carry the exact ``4.0.0`` runtime literal, and agree
    with the caller-supplied campaign, tenant, world, and verified world
    content hash. Any disagreement fails closed; the policy is never
    repaired, replaced, or evaluated.
    """
    if type(policy) is not AdaptivePolicy:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="policy must be an exact AdaptivePolicy"
        )
    if (
        policy.runtime_version != ADAPTIVE_RUNTIME_VERSION
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.world_version_id != world_version_id
        or policy.world_content_hash != world_content_hash
    ):
        raise _reject_policy_authority(
            policy,
            reason="policy disagrees with the campaign, tenant, world, or runtime authority",
        )


def _resolve_initial_action_strategy_anchor(policy: AdaptivePolicy) -> str:
    """Resolve the ``strategy_candidate_id`` of the policy's initial action.

    The bound action referenced by ``policy.initial_action_id`` must
    resolve to exactly one member of the policy's bound action catalog
    (membership and uniqueness are already contract invariants; they are
    re-checked here so the planner fails closed independently). The
    resolved ``strategy_candidate_id`` is the stable truthful
    initial-action planning anchor recorded on every runtime-4 plan;
    runtime-4 execution remains policy-driven and is never narrowed to
    this anchor's strategy.
    """
    anchor_action: BoundAdaptiveAction | None = None
    for action in policy.actions:
        if action.action_id == policy.initial_action_id:
            if anchor_action is not None:
                raise _reject_policy_authority(
                    policy, reason="initial action does not resolve uniquely"
                )
            anchor_action = action
    if anchor_action is None:
        raise _reject_policy_authority(
            policy, reason="initial action is missing from the bound action catalog"
        )
    return anchor_action.strategy_candidate_id


def _verify_realization_authority(
    realization: WorldRealization,
    *,
    seed: ScenarioSeed,
    tenant_id: str,
    world_version_id: str,
    world_content_hash: str,
    campaign_id: str,
) -> None:
    """Verify one seed's shared realization authority before planning.

    The realization must be the exact immutable contract type and must
    agree with the tenant, the planned world (identity and verified
    content hash), the seed identity, and the seed's authoritative
    content hash. Any disagreement fails closed: the planner never
    derives, repairs, or substitutes a realization.
    """
    if type(realization) is not WorldRealization:
        raise AdaptivePolicyBindingValidationError(
            tenant_id, campaign_id, reason="realization must be an exact WorldRealization"
        )
    if (
        realization.tenant_id != tenant_id
        or realization.world_version_id != world_version_id
        or realization.world_content_hash != world_content_hash
        or realization.scenario_seed_id != seed.identifier
        or realization.seed_content_hash != seed_content_hash(seed)
    ):
        raise AdaptivePolicyBindingValidationError(
            tenant_id,
            campaign_id,
            reason="realization authority disagrees with the tenant, world, or seed",
        )


def plan_adaptive_runs(
    *,
    campaign_id: str,
    tenant_id: str,
    world_version_id: str,
    world_content_hash: str,
    policy: AdaptivePolicy,
    seeds: tuple[ScenarioSeed, ...],
    created_at: AwareDatetime,
    realizations: Mapping[str, WorldRealization],
    runtime_version: str = ADAPTIVE_RUNTIME_VERSION,
) -> tuple[RunPlan, ...]:
    """Plan exactly one runtime-4 adaptive RunPlan per ordered seed.

    The seed ensemble is the sole source of run multiplicity: ``K``
    seeds yield exactly ``K`` plans in the caller's exact seed order,
    never ``K x S`` for any strategy dimension. Every plan carries the
    exact tenant/campaign/world/seed/runtime provenance, the
    initial-action strategy anchor in the historical
    ``strategy_candidate_id`` field, the deterministic
    :func:`adaptive_run_input_hash` digest binding the complete policy,
    seed, world, and realization authority, and the caller-supplied
    deterministic ``created_at`` (never a wall clock).

    Complete authority verification happens before the first plan is
    constructed: the runtime gate, the bound policy authority, the
    initial-action anchor resolution, and every seed's shared
    realization resolution must all pass, so a missing or disagreeing
    authority fails closed with a typed domain error and no partial
    output. Inputs are never mutated; no store is read; no policy rule
    is evaluated; no randomness or clock is consumed.

    A changed policy is a different immutable authority (different
    ``input_hash``, and through its own campaign/run authority a
    different plan set); compared policies receive the same ordered
    seeds and the same per-seed realization authority, preserving the
    Phase 28 fairness invariant.
    """
    if runtime_version != ADAPTIVE_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(runtime_version, operation="adaptive run planning")
    try:
        return _plan_verified_adaptive_runs(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            world_version_id=world_version_id,
            world_content_hash=world_content_hash,
            policy=policy,
            seeds=seeds,
            created_at=created_at,
            realizations=realizations,
            runtime_version=runtime_version,
        )
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        raise AdaptivePolicyBindingValidationError(
            tenant_id,
            campaign_id,
            reason="planning input violates its contract",
        ) from exc


def _plan_verified_adaptive_runs(
    *,
    campaign_id: str,
    tenant_id: str,
    world_version_id: str,
    world_content_hash: str,
    policy: AdaptivePolicy,
    seeds: tuple[ScenarioSeed, ...],
    created_at: AwareDatetime,
    realizations: Mapping[str, WorldRealization],
    runtime_version: str,
) -> tuple[RunPlan, ...]:
    """The exact verified planning path; raises typed domain errors only."""
    _verify_policy_authority(
        policy,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
    )
    anchor = _resolve_initial_action_strategy_anchor(policy)
    resolved: list[tuple[ScenarioSeed, WorldRealization]] = []
    for seed in seeds:
        if type(seed) is not ScenarioSeed:
            raise AdaptivePolicyBindingValidationError(
                tenant_id, campaign_id, reason="seeds must be exact ScenarioSeed records"
            )
        if seed.tenant_id != tenant_id:
            raise AdaptivePolicyBindingValidationError(
                tenant_id, campaign_id, reason="seed tenant disagrees with the planned tenant"
            )
        realization = realizations.get(seed.identifier)
        if realization is None:
            raise AdaptivePolicyBindingValidationError(
                tenant_id,
                campaign_id,
                reason="realization authority is missing for a planned seed",
            )
        _verify_realization_authority(
            realization,
            seed=seed,
            tenant_id=tenant_id,
            world_version_id=world_version_id,
            world_content_hash=world_content_hash,
            campaign_id=campaign_id,
        )
        resolved.append((seed, realization))
    plans: list[RunPlan] = []
    for seed, realization in resolved:
        plans.append(
            RunPlan(
                identifier=run_plan_identifier(
                    campaign_id=campaign_id,
                    world_version_id=world_version_id,
                    strategy_candidate_id=anchor,
                    scenario_seed_id=seed.identifier,
                    runtime_version=runtime_version,
                ),
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                world_version_id=world_version_id,
                strategy_candidate_id=anchor,
                scenario_seed_id=seed.identifier,
                runtime_version=runtime_version,
                input_hash=adaptive_run_input_hash(
                    runtime_version=runtime_version,
                    world_content_hash=world_content_hash,
                    policy=policy,
                    seed=seed,
                    world_realization_content_hash=realization.content_hash,
                ),
                created_at=created_at,
            )
        )
    return tuple(plans)


__all__ = [
    "ADAPTIVE_RUNTIME_VERSION",
    "adaptive_run_input_hash",
    "plan_adaptive_runs",
]
