"""Verified read-only campaign decision query services (KALHAS).

``get_verified_campaign_strategy_comparison`` and
``get_verified_campaign_decision_brief`` derive the deterministic
``CampaignStrategyComparison`` and ``CampaignDecisionBrief`` of one
COMPLETE runtime-3.0.0 campaign strictly from verified stored records,
never storing either derived artifact. Both queries are pure
orchestration: every policy, outcome, comparison, and brief fact comes
exclusively from the accepted verified query and the accepted pure
builders - nothing is recomputed, reimplemented, or weakened here.

Authoritative query order (both operations, exactly):

1. Load the tenant-scoped ``CampaignSpec`` through the store; unknown
   or foreign campaigns raise the established typed not-found error.
2. Load the ``CampaignStatus`` through the store.
3. Require exactly :class:`CampaignState.COMPLETE`; any other state
   raises :class:`CampaignNotCompleteError` before any downstream
   work.
4. Load and independently verify the stored decision policy through
   ``get_verified_campaign_decision_policy`` - an absent or foreign
   policy raises ``CampaignDecisionPolicyNotFoundError``, and a
   corrupted, forged, or validator-bypassed policy raises the typed
   policy integrity error; both propagate unchanged. When the policy
   is absent, zero outcome queries, zero comparison-builder calls, and
   zero brief-builder calls occur, and no state is mutated: upstream
   campaign outcomes are never derived before the verified policy exists.
5. Call ``get_verified_campaign_outcome_distributions`` exactly once.

The comparison query then calls the accepted pure
``build_campaign_strategy_comparison`` exactly once with the verified
policy and the exact outcome matrix returned by that single query, and
returns the derived comparison directly without storing it. The brief
query additionally loads the campaign's exact scenario through the
already retrieved ``CampaignSpec.scenario_id`` and calls the accepted
pure ``build_campaign_decision_brief`` exactly once with the loaded
scenario, the same verified policy, the same outcome-matrix object,
and the comparison object produced by its single comparison-builder
call; it never repeats the outcome query and never calls the public
comparison query (that would repeat campaign/policy/outcome work).

Error semantics. All established campaign, policy, status, and
upstream outcome-query typed errors propagate unchanged. Only the
precisely expected local builder failures are translated, at the
derived-artifact trust boundary: a comparison-builder ``ValueError``
or ``OverflowError`` becomes
:class:`CampaignDecisionComparisonIntegrityError`; a missing or
inconsistent campaign scenario, and a brief-builder ``ValueError`` or
``OverflowError``, become :class:`CampaignDecisionBriefIntegrityError`.
Each translation retains a safe internal reason and chains the
original exception as the cause; the public message is fixed, generic,
and never exposes the internal reason, identifiers, hashes, values, or
validator diagnostics. Nothing else is ever caught, converted,
normalized, repaired, or silently accepted, and no partial comparison
or brief is ever returned.

Both queries are deterministic and read-only: they never execute,
replay, extract observations, append activity, transition lifecycle
state, write to any store collection, consult the wall clock, or use
randomness, and repeated calls over unchanged stored evidence return
byte-identical artifacts while leaving the complete store state
unchanged. The module is pure application logic: no FastAPI, no
NEXUS/LEGION imports, no filesystem, database, provider, or network
access.
"""

from __future__ import annotations

from kalhas.application.campaign_decision_brief_runtime import (
    build_campaign_decision_brief,
)
from kalhas.application.campaign_decision_comparison_runtime import (
    build_campaign_strategy_comparison,
)
from kalhas.application.campaign_decision_errors import (
    CampaignDecisionBriefIntegrityError,
    CampaignDecisionComparisonIntegrityError,
)
from kalhas.application.campaign_decision_policy_service import (
    get_verified_campaign_decision_policy,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    ScenarioNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
)


def _load_complete_verified_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
) -> tuple[CampaignSpec, CampaignDecisionPolicy]:
    """The common campaign/status/COMPLETE/policy gate of both queries.

    The tenant-scoped campaign lookup raises the typed not-found error
    (unknown and foreign campaigns are indistinguishable), the status
    gate raises :class:`CampaignNotCompleteError` before any policy or
    outcome work, and the policy is loaded and independently verified
    through the accepted verified query - an absent or foreign policy
    raises the typed policy not-found error, and a corrupted stored
    policy raises the typed policy integrity error, both unchanged.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)
    policy = get_verified_campaign_decision_policy(
        store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    return campaign, policy


def get_verified_campaign_strategy_comparison(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignStrategyComparison:
    """Derive and verify the campaign strategy comparison of a COMPLETE campaign.

    Runs the exact authoritative query order (campaign, COMPLETE
    status, verified policy, exactly one verified outcome query) and
    then calls the accepted pure comparison builder exactly once with
    the verified policy and the exact outcome matrix returned by that
    single query, returning the derived comparison directly without
    storing it. A comparison-builder ``ValueError`` or
    ``OverflowError`` is translated to
    :class:`CampaignDecisionComparisonIntegrityError` with a safe
    internal reason and the original exception chained as the cause;
    every established campaign, policy, status, and upstream outcome
    typed error propagates unchanged, and a partial comparison is
    never returned.
    """
    _campaign, policy = _load_complete_verified_policy(
        store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    outcome_matrix = get_verified_campaign_outcome_distributions(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    try:
        return build_campaign_strategy_comparison(policy=policy, outcome_matrix=outcome_matrix)
    except (ValueError, OverflowError) as exc:
        raise CampaignDecisionComparisonIntegrityError(
            tenant_id,
            campaign_id,
            reason="campaign strategy comparison derivation failed",
        ) from exc


def get_verified_campaign_decision_brief(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignDecisionBrief:
    """Derive and verify the campaign decision brief of a COMPLETE campaign.

    Runs the exact authoritative query order (campaign, COMPLETE
    status, verified policy, exactly one verified outcome query,
    exactly one comparison-builder call) and then loads the campaign's
    exact scenario through the already retrieved
    ``CampaignSpec.scenario_id`` and calls the accepted pure brief
    builder exactly once with the loaded scenario, the same verified
    policy, the same outcome-matrix object, and the comparison object
    produced by the single comparison-builder call, returning the
    brief directly without storing it. There is no second outcome
    query and no call to the public comparison query. A
    comparison-builder ``ValueError`` or ``OverflowError`` is
    translated to :class:`CampaignDecisionComparisonIntegrityError`;
    a missing or inconsistent campaign scenario at this
    derived-artifact boundary, and a brief-builder ``ValueError`` or
    ``OverflowError``, are translated to
    :class:`CampaignDecisionBriefIntegrityError`; every established
    campaign, policy, status, and upstream outcome typed error
    propagates unchanged, and a partial brief is never returned.
    """
    campaign, policy = _load_complete_verified_policy(
        store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    outcome_matrix = get_verified_campaign_outcome_distributions(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    try:
        comparison = build_campaign_strategy_comparison(
            policy=policy, outcome_matrix=outcome_matrix
        )
    except (ValueError, OverflowError) as exc:
        raise CampaignDecisionComparisonIntegrityError(
            tenant_id,
            campaign_id,
            reason="campaign strategy comparison derivation failed",
        ) from exc
    try:
        scenario = store.get_scenario(tenant_id, campaign.scenario_id)
    except ScenarioNotFoundError as exc:
        raise CampaignDecisionBriefIntegrityError(
            tenant_id,
            campaign_id,
            reason="campaign scenario record missing",
        ) from exc
    if scenario.tenant_id != tenant_id or scenario.identifier != policy.scenario_id:
        raise CampaignDecisionBriefIntegrityError(
            tenant_id,
            campaign_id,
            reason="campaign scenario identity mismatch",
        )
    try:
        return build_campaign_decision_brief(
            scenario=scenario,
            policy=policy,
            outcome_matrix=outcome_matrix,
            comparison=comparison,
        )
    except (ValueError, OverflowError) as exc:
        raise CampaignDecisionBriefIntegrityError(
            tenant_id,
            campaign_id,
            reason="campaign decision brief derivation failed",
        ) from exc


__all__ = [
    "get_verified_campaign_strategy_comparison",
    "get_verified_campaign_decision_brief",
]
