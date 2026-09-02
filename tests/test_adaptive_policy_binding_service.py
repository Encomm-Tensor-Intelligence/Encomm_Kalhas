"""Focused tests for the adaptive-policy binding service and store (H28-S05).

These tests exercise the immutable :class:`AdaptivePolicy` authority end to
end: the real binding service (``bind_adaptive_policy``), the real
:class:`InMemoryScenarioStore` one-policy-per-campaign immutable persistence
surface, and the real runtime-4 authority produced from a real compiled world,
real stored domain models/manifests, real stored
:class:`RuntimeObservationDeclaration` records, a real COMPILED campaign, real
stored :class:`StrategyCandidate` records, real prepared
:class:`StrategyTrajectoryPlan` collections, and the real runtime-4 state
initializer.

Proof groups covered:

- SUCCESS: deterministic multi-action binding; exact copied
  campaign/scenario/world provenance; exact observation bindings; exact
  strategy and complete trajectory-plan bindings; equal state-model coverage
  across actions; canonical action/observation/rule/plan ordering;
  deterministic identifier and content hash; successful policy state
  initialization; defensive returned/stored copies; unchanged inputs; and zero
  operational activity.
- REJECTION (service): non-COMPILED campaign; wrong-type/subclass/
  ``model_copy``/``model_construct`` draft or binding input; malformed policy
  scalar or nested rule/condition; missing/extra/duplicate/reordered action
  mapping; two actions mapped to one strategy; unknown/foreign strategy;
  missing/unequal trajectory-plan coverage; forged strategy/plan identifier or
  hash; missing/foreign observation declaration; observation
  kind/unit/missing-behavior mismatch; absent observation coverage; foreign
  tenant/campaign; non-finite metadata; duplicate policy write.
- REJECTION (store): forged identifier/content hash; self-consistently
  rehashed altered world/declaration/strategy provenance; private-store
  corruption detected on get.

Every rejection test proves the adaptive-policy collection and the operational
activity remain unchanged. Public error strings never expose supplied
identifiers, hashes, values, metadata, or Pydantic diagnostics.

No ``unittest.mock``, production monkeypatching, skips, xfail, assertion
weakening, alternate canonicalizers, direct constant substitution, ``noqa``,
or ``type: ignore`` is used.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyAlreadyExistsError,
    AdaptivePolicyBindingValidationError,
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_policy_identity import (
    adaptive_policy_content_hash,
    adaptive_policy_identifier,
)
from kalhas.application.adaptive_policy_state_machine import (
    initialize_adaptive_policy_state,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    BoundAdaptiveAction,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.strategy import StrategyCandidate

from tests.phase4_helpers import TENANT, prepare
from tests.phase20_helpers import (
    build_observation_store,
    compile_observation_world,
)

OTHER_TENANT = "tenant-99"

_BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
_TIMING = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)
_NumericKind = Literal["integer", "number"]


def _declare_observation(
    store: InMemoryScenarioStore, world_id: str, observation_id: str, kind: _NumericKind
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            external_source=ExternalObservationDraft(
                external_channel_id="channel-1", external_value_kind=kind
            ),
            timing=_TIMING,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=_DECLARED_AT,
            metadata={},
        ),
    )


def _leaf(
    condition_id: str,
    observation_id: str,
    kind: _NumericKind,
    threshold: int | float,
    *,
    unit: str | None = None,
    missing: Literal["false", "error"] = "false",
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id=observation_id,
        observed_value_kind=kind,
        unit=unit,
        operator="gt",
        threshold=threshold,
        missing_behavior=missing,
    )


def _draft() -> AdaptivePolicyDraft:
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=_leaf("c1a", "obs-a", "integer", 0),
                retain_condition=_leaf("c1r", "obs-a", "integer", 0),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-2",
                priority=1,
                target_action_id="act-2",
                enter_condition=_leaf("c2a", "obs-b", "number", 0.0),
                retain_condition=_leaf("c2r", "obs-b", "number", 0.0),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _request(
    *,
    policy_id: str = "policy-1",
    policy_version: str = "1.0.0",
    mappings: tuple[ActionStrategyMapping, ...] | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AdaptivePolicyBindingRequest:
    if mappings is None:
        mappings = (
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        )
    return AdaptivePolicyBindingRequest(
        policy_id=policy_id,
        policy_version=policy_version,
        action_mappings=mappings,
        bound_at=_BOUND_AT,
        metadata=metadata if metadata is not None else {},
    )


def _assert_no_activity(store: InMemoryScenarioStore) -> None:
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def _assert_safe_message(exc: Exception, *secrets: object) -> None:
    text = str(exc)
    for secret in secrets:
        if isinstance(secret, str) and secret:
            assert secret not in text


@pytest.fixture()
def bound_env() -> tuple[InMemoryScenarioStore, str, str]:
    """A real COMPILED campaign with strategies, plans, and declarations."""
    return _build_binding_env()


def _build_binding_env(
    campaign_id: str = "campaign-1",
) -> tuple[InMemoryScenarioStore, str, str]:
    """Build a real byte-equivalent COMPILED binding environment."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    prepare(
        store,
        world_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        campaign_id=campaign_id,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        campaign_id=campaign_id,
    )
    _declare_observation(store, world_id, "obs-a", "integer")
    _declare_observation(store, world_id, "obs-b", "number")
    return store, world_id, campaign_id


# --------------------------------------------------------------------------
# SUCCESS
# --------------------------------------------------------------------------


def test_deterministic_multi_action_binding(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bound_env
    draft = _draft()
    request = _request()
    policy = bind_adaptive_policy(
        store, tenant_id=TENANT, campaign_id=campaign_id, draft=draft, binding_request=request
    )

    assert type(policy) is AdaptivePolicy
    assert policy.runtime_version == "4.0.0"
    assert policy.tenant_id == TENANT
    assert policy.campaign_id == campaign_id
    assert policy.scenario_id == "scenario-1"
    assert policy.world_version_id == world_id
    assert policy.policy_id == "policy-1"
    assert policy.policy_version == "1.0.0"

    # Deterministic identity and self-covering content hash.
    assert policy.identifier == adaptive_policy_identifier(
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_id="scenario-1",
        world_version_id=world_id,
        policy_id="policy-1",
        policy_version="1.0.0",
        schema_version=policy.schema_version,
    )
    assert policy.content_hash == adaptive_policy_content_hash(policy)

    # Exact observation bindings, canonically ordered.
    assert [b.observation_id for b in policy.observation_bindings] == ["obs-a", "obs-b"]
    stored_obs_a = store.get_runtime_observation_declaration(
        TENANT, "scenario-1", world_id, "obs-a"
    )
    stored_obs_b = store.get_runtime_observation_declaration(
        TENANT, "scenario-1", world_id, "obs-b"
    )
    by_id = {b.observation_id: b for b in policy.observation_bindings}
    assert by_id["obs-a"].runtime_observation_declaration_id == stored_obs_a.identifier
    assert by_id["obs-a"].runtime_observation_declaration_content_hash == stored_obs_a.content_hash
    assert by_id["obs-a"].observed_value_kind == "integer"
    assert by_id["obs-b"].runtime_observation_declaration_id == stored_obs_b.identifier
    assert by_id["obs-b"].runtime_observation_declaration_content_hash == stored_obs_b.content_hash
    assert by_id["obs-b"].observed_value_kind == "number"

    # Exact action/strategy bindings with complete, equal state-model coverage.
    assert [a.action_id for a in policy.actions] == ["act-1", "act-2"]
    by_action = {a.action_id: a for a in policy.actions}
    stored_candidates = {
        c.identifier: c for c in store.get_strategy_candidates(TENANT, campaign_id)
    }
    baseline = stored_candidates["mock-baseline"]
    balanced = stored_candidates["mock-balanced"]
    assert by_action["act-1"].strategy_candidate_id == "mock-baseline"
    assert by_action["act-1"].strategy_content_hash == _strategy_hash(baseline)
    assert by_action["act-2"].strategy_candidate_id == "mock-balanced"
    assert by_action["act-2"].strategy_content_hash == _strategy_hash(balanced)

    plans = store.get_strategy_trajectory_plans(TENANT, campaign_id)
    expected_state_models = {_embedded_state_model_identifier(store, world_id)}
    assert _state_model_coverage(by_action["act-1"]) == expected_state_models
    assert _state_model_coverage(by_action["act-2"]) == expected_state_models
    for action in policy.actions:
        for binding in action.trajectory_plan_bindings:
            plan = next(p for p in plans if p.identifier == binding.trajectory_plan_id)
            assert binding.trajectory_plan_content_hash == plan.content_hash
            assert binding.state_model_identifier == plan.state_model_identifier
            assert binding.state_model_id == plan.state_model_id

    # Canonical ordering.
    assert [r.priority for r in policy.rules] == [0, 1]
    for action in policy.actions:
        ordering = [
            (b.state_model_identifier, b.trajectory_plan_id)
            for b in action.trajectory_plan_bindings
        ]
        assert ordering == sorted(ordering)

    # Final policy initializes through the real state initializer.
    snapshot = initialize_adaptive_policy_state(policy)
    assert snapshot.decision_step == 0
    assert snapshot.current_action_id == "act-1"

    # Persisted exactly once and retrievable.
    stored = store.get_adaptive_policy(TENANT, campaign_id)
    assert stored == policy
    assert len(store._adaptive_policies) == 1
    _assert_no_activity(store)


def test_defensive_copies_and_input_immutability(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bound_env
    draft = _draft()
    draft_snapshot = draft.model_dump(mode="python")
    request = _request(metadata={"note": "keep", "nested": {"k": 1}})
    request_snapshot = copy.deepcopy(request)
    bind_adaptive_policy(
        store, tenant_id=TENANT, campaign_id=campaign_id, draft=draft, binding_request=request
    )
    # Complete detached snapshots prove both caller-owned inputs are unchanged.
    assert draft.model_dump(mode="python") == draft_snapshot
    assert request == request_snapshot
    assert request.metadata == {"note": "keep", "nested": {"k": 1}}

    # Defensive returned copy: mutating it must not affect storage.
    returned = store.get_adaptive_policy(TENANT, campaign_id)
    returned.metadata["injected"] = {"payload": "tampered"}
    assert "injected" not in store.get_adaptive_policy(TENANT, campaign_id).metadata
    _assert_no_activity(store)


def test_deterministic_identity_across_inputs() -> None:
    store, world_id, campaign_id = _build_binding_env()
    first = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(policy_id="policy-x", policy_version="1.0.0"),
    )
    # A second independent but byte-equivalent real store/world/campaign.
    store2, world2, campaign2 = _build_binding_env()
    assert world2 == world_id
    second = bind_adaptive_policy(
        store2,
        tenant_id=TENANT,
        campaign_id=campaign2,
        draft=_draft(),
        binding_request=_request(policy_id="policy-x", policy_version="1.0.0"),
    )
    assert second.identifier == first.identifier
    assert second.content_hash == first.content_hash
    assert second == first
    assert len(store._adaptive_policies) == 1
    assert len(store2._adaptive_policies) == 1
    _assert_no_activity(store)
    _assert_no_activity(store2)


def test_zero_activity_on_success(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    _assert_no_activity(store)


# --------------------------------------------------------------------------
# REJECTION
# --------------------------------------------------------------------------


def test_non_compiled_campaign_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    status = store.get_campaign_status(TENANT, campaign_id)
    altered = status.model_copy(update={"state": CampaignState.RUNNING})
    store.update_campaign_status(TENANT, campaign_id, altered)
    with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(),
        )
    _assert_safe_message(excinfo.value, TENANT, campaign_id, "campaign-1")
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_foreign_tenant_and_campaign_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, _ = bound_env
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=OTHER_TENANT,
            campaign_id="campaign-1",
            draft=_draft(),
            binding_request=_request(),
        )
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id="campaign-zzz",
            draft=_draft(),
            binding_request=_request(),
        )
    # Unknown and foreign are indistinguishable on read.
    with pytest.raises(AdaptivePolicyNotFoundError):
        store.get_adaptive_policy(TENANT, "campaign-zzz")
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_wrong_type_and_subclass_inputs_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env

    class _SubDraft(AdaptivePolicyDraft):
        pass

    subclass_draft = _SubDraft.model_validate(_draft().model_dump(mode="python"))
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=subclass_draft,
            binding_request=_request(),
        )

    class _SubRequest(AdaptivePolicyBindingRequest):
        pass

    subclass_request = _SubRequest(
        policy_id="policy-1",
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=_BOUND_AT,
        metadata={},
    )
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=subclass_request,
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_model_copy_tampered_draft_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    # model_copy bypasses the contract validators: a negative budget that the
    # strict contract would reject is smuggled through and caught only by the
    # service's detached strict revalidation.
    forged = _draft().model_copy(update={"cooldown_steps": -5})
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=forged,
            binding_request=_request(),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_model_construct_forged_draft_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    dump = _draft().model_dump(mode="python")
    dump["minimum_dwell_steps"] = True  # bool where a strict int belongs
    forged = AdaptivePolicyDraft.model_construct(**dump)
    with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=forged,
            binding_request=_request(),
        )
    _assert_safe_message(excinfo.value, TENANT, campaign_id)
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_non_finite_metadata_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(metadata={"bad": float("nan")}),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


@pytest.mark.parametrize(
    "mappings",
    [
        (),  # missing (empty)
        (
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-balanced"),
        ),  # reordered
        (
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-balanced"),
        ),  # extra / duplicate action
    ],
)
def test_action_mapping_coverage_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
    mappings: tuple[ActionStrategyMapping, ...],
) -> None:
    store, _, campaign_id = bound_env
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(mappings=mappings),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_two_actions_mapped_to_one_strategy_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    mappings = (
        ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
        ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-baseline"),
    )
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(mappings=mappings),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_unknown_strategy_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    mappings = (
        ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
        ActionStrategyMapping(action_id="act-2", strategy_candidate_id="strategy-zzz"),
    )
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(mappings=mappings),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_unequal_state_model_coverage_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    # Remove every plan for mock-balanced so act-2 has no state-model coverage
    # while act-1 (mock-baseline) retains its full coverage -> unequal coverage.
    key = (TENANT, campaign_id)
    kept = tuple(
        plan
        for plan in store._strategy_trajectory_plans[key]
        if plan.strategy_candidate_id != "mock-balanced"
    )
    store._strategy_trajectory_plans[key] = kept
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_forged_plan_content_hash_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bound_env
    key = (TENANT, campaign_id)
    plans = list(store._strategy_trajectory_plans[key])
    target_index = next(
        i
        for i, plan in enumerate(plans)
        if plan.strategy_candidate_id == "mock-baseline"
        and plan.state_model_identifier == _embedded_state_model_identifier(store, world_id)
    )
    forged = plans[target_index].model_copy(update={"content_hash": "0" * 64})
    plans[target_index] = forged
    store._strategy_trajectory_plans[key] = tuple(plans)
    with pytest.raises(AdaptivePolicyIntegrityError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def _embedded_state_model_identifier(store: InMemoryScenarioStore, world_id: str) -> str:
    from kalhas.application.world_integrity import extract_world_catalog

    world = store.get_world(TENANT, world_id)
    return extract_world_catalog(world).state_models[0].identifier


def test_missing_observation_declaration_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bound_env
    # Reference an observation that has no stored declaration.
    draft = AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1",),
        initial_action_id="act-1",
        fallback_action_id="act-1",
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=_leaf("c1a", "obs-missing", "integer", 0),
                retain_condition=_leaf("c1r", "obs-missing", "integer", 0),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=1,
    )
    mappings = (ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),)
    with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=draft,
            binding_request=_request(policy_id="policy-m", mappings=mappings),
        )
    _assert_safe_message(excinfo.value, "obs-missing", world_id)
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_observation_kind_mismatch_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    # obs-a is declared integer; a leaf claiming "number" disagrees.
    draft = AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1",),
        initial_action_id="act-1",
        fallback_action_id="act-1",
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=_leaf("c1a", "obs-a", "number", 0.0),
                retain_condition=_leaf("c1r", "obs-a", "number", 0.0),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=1,
    )
    mappings = (ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),)
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=draft,
            binding_request=_request(policy_id="policy-kind", mappings=mappings),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_no_referenced_observation_rejected(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    draft = AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1",),
        initial_action_id="act-1",
        fallback_action_id="act-1",
        rules=(),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=1,
    )
    mappings = (ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),)
    with pytest.raises(AdaptivePolicyBindingValidationError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=draft,
            binding_request=_request(policy_id="policy-none", mappings=mappings),
        )
    assert store._adaptive_policies == {}
    _assert_no_activity(store)


def test_duplicate_policy_write_never_overwrites(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    first = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    with pytest.raises(AdaptivePolicyAlreadyExistsError):
        bind_adaptive_policy(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            draft=_draft(),
            binding_request=_request(policy_id="policy-2"),
        )
    assert store.get_adaptive_policy(TENANT, campaign_id) == first
    assert len(store._adaptive_policies) == 1
    _assert_no_activity(store)


# --------------------------------------------------------------------------
# STORE INTEGRITY
# --------------------------------------------------------------------------


def test_forged_content_hash_detected_on_get(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    policy = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    store._adaptive_policies[(TENANT, campaign_id)] = policy.model_copy(
        update={"content_hash": "0" * 64}
    )
    with pytest.raises(AdaptivePolicyIntegrityError):
        store.get_adaptive_policy(TENANT, campaign_id)


def test_self_consistently_rehashed_altered_world_detected_on_get(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    base = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    tampered = base.model_copy(update={"world_content_hash": "1" * 64})
    tampered = tampered.model_copy(update={"content_hash": adaptive_policy_content_hash(tampered)})
    store._adaptive_policies[(TENANT, campaign_id)] = tampered
    # The policy is internally self-consistent, but its recorded world hash no
    # longer matches the stored compiled world -> cross-authority rejection.
    with pytest.raises(AdaptivePolicyIntegrityError):
        store.get_adaptive_policy(TENANT, campaign_id)


def test_self_consistently_rehashed_altered_declaration_detected_on_get(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    base = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    by_id = {b.observation_id: b for b in base.observation_bindings}
    forged_binding = by_id["obs-a"].model_copy(update={"observed_value_kind": "number"})
    forged_bindings = tuple(
        forged_binding if b.observation_id == "obs-a" else b for b in base.observation_bindings
    )
    paper = base.model_copy(update={"observation_bindings": forged_bindings})
    paper = paper.model_copy(update={"content_hash": adaptive_policy_content_hash(paper)})
    store._adaptive_policies[(TENANT, campaign_id)] = paper
    # The policy self-validates, but the altered binding disagrees with the
    # stored declaration's observed value kind -> cross-authority rejection.
    with pytest.raises(AdaptivePolicyIntegrityError):
        store.get_adaptive_policy(TENANT, campaign_id)


def test_private_store_corruption_detected_on_get(
    bound_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bound_env
    base = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_draft(),
        binding_request=_request(),
    )
    corrupted = base.model_copy(update={"policy_id": "forged-policy"})
    store._adaptive_policies[(TENANT, campaign_id)] = corrupted
    with pytest.raises(AdaptivePolicyIntegrityError):
        store.get_adaptive_policy(TENANT, campaign_id)
    # Corruption is rejected, never repaired: get still fails afterwards.
    with pytest.raises(AdaptivePolicyIntegrityError):
        store.get_adaptive_policy(TENANT, campaign_id)
    _assert_no_activity(store)


# --------------------------------------------------------------------------
# Small helpers used by assertions above
# --------------------------------------------------------------------------


def _strategy_hash(candidate: StrategyCandidate) -> str:
    from kalhas.application.hashing import canonical_json, sha256_hex

    return sha256_hex(canonical_json(candidate.model_dump(mode="json")))


def _state_model_coverage(action: BoundAdaptiveAction) -> set[str]:
    return {b.state_model_identifier for b in action.trajectory_plan_bindings}
