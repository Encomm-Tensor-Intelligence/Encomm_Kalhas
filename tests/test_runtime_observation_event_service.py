"""Causal observation-event derivation service tests (H28-S06B2).

Builds a real compiled world, a real COMPILED campaign with a real
scenario seed, real stored ``RuntimeObservationDeclaration`` records, a
real stored ``AdaptivePolicy`` bound over them, real accepted
``ExternalObservationInputBundle`` authorities, and exercises the pure
``derive_observation_step`` causal boundary end to end: the caller-owned
``ObservationStepDraft`` with its exact ``final_decision_step`` horizon,
the horizon-classified terminality, the complete prior sourced-event
ledger verification, the exact availability semantics, deterministic
noise under the frozen ADR-004 coordinate, byte-identical repetition,
input immutability, zero store writes and zero activity, and the
adversarial rejection surface. All identifiers, hashes, and events are
computed truthfully with the production services and identity helpers;
nothing is monkeypatched and no event is manufactured by replacing the
production derivation.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.domain_errors import KalhasDomainError
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
    accept_external_observation_input_bundle,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventCausalOrderError,
    RuntimeObservationEventIntegrityError,
    RuntimeObservationEventNoiseError,
    RuntimeObservationEventValidationError,
)
from kalhas.application.runtime_observation_event_identity import (
    observation_noise_word,
    runtime_observation_event_content_hash,
    runtime_observation_event_identifier,
)
from kalhas.application.runtime_observation_event_service import (
    ObservationStepDraft,
    ObservationStepResult,
    derive_observation_step,
)
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.runtime_observation import (
    AdditiveUniformObservationNoise,
    NoObservationNoise,
    ObservationTiming,
    RuntimeObservationEvent,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.world_realization import ExactNumeric

from tests.phase4_helpers import TENANT, prepare
from tests.phase20_helpers import build_observation_store, compile_observation_world

_BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
_ACCEPTED_AT = datetime(2026, 1, 10, 9, 0, 0, tzinfo=UTC)
_SEED_ID = "seed-1"
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)
_ADDITIVE_UNIFORM = AdditiveUniformObservationNoise(
    kind="additive_uniform",
    lower_bound=-0.5,
    upper_bound=0.5,
    sampler_version="sha256-counter-v1",
    quantization_policy="rational-round-half-even",
    quantization_fraction_bits=64,
    draw_count=1,
)
_TIMING_0 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_TIMING_DELAY1 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=1)
_TIMING_DELAY3 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=3)
_TIMING_EVERY2 = ObservationTiming(start_step=0, every_n_steps=2, delay_steps=0)
_NUMERIC_KIND = Literal["integer", "number"]


def _state_key(store: InMemoryScenarioStore) -> str:
    return store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1").identifier


def _default_state(store: InMemoryScenarioStore) -> dict[str, dict[str, JsonValue]]:
    return {_state_key(store): {"level": 4, "ratio": 2.5, "status": "idle"}}


def _declare_state_field(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    *,
    field_id: str = "level",
    timing: ObservationTiming | None = None,
    noise: NoObservationNoise | AdditiveUniformObservationNoise | None = None,
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            state_source=StateFieldObservationDraft(
                manifest_id="manifest-1", state_model_id="sm-1", state_field_id=field_id
            ),
            timing=timing if timing is not None else _TIMING_0,
            noise=noise if noise is not None else _NO_NOISE,
            missing_behavior="false",
            declared_at=_DECLARED_AT,
            metadata={},
        ),
    )


def _declare_external(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    kind: _NUMERIC_KIND,
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
            timing=_TIMING_0,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=_DECLARED_AT,
            metadata={},
        ),
    )


def _leaf(
    condition_id: str,
    observation_id: str,
    kind: _NUMERIC_KIND,
    threshold: ExactNumeric,
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id=observation_id,
        observed_value_kind=kind,
        unit=None,
        operator="gt",
        threshold=threshold,
        missing_behavior="false",
    )


def _rule(
    rule_id: str,
    priority: int,
    target_action_id: str,
    observation_id: str,
    kind: _NUMERIC_KIND,
) -> AdaptivePolicyRuleDraft:
    return AdaptivePolicyRuleDraft(
        rule_id=rule_id,
        priority=priority,
        target_action_id=target_action_id,
        enter_condition=_leaf(f"{rule_id}-a", observation_id, kind, 0),
        retain_condition=_leaf(f"{rule_id}-r", observation_id, kind, 0),
        per_rule_switch_budget=1,
    )


def _state_pair_policy_draft() -> AdaptivePolicyDraft:
    """Binds the two state-field declarations of the state environment."""
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            _rule("rule-1", 0, "act-1", "obs-level", "integer"),
            _rule("rule-2", 1, "act-2", "obs-ratio-noisy", "number"),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _external_pair_policy_draft() -> AdaptivePolicyDraft:
    """Binds the two external declarations of the external environment."""
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            _rule("rule-1", 0, "act-1", "obs-a", "integer"),
            _rule("rule-2", 1, "act-2", "obs-b", "number"),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _state_family_policy_draft() -> AdaptivePolicyDraft:
    """Binds the three delay-family state declarations of one model."""
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            _rule("rule-1", 0, "act-1", "obs-level", "integer"),
            _rule("rule-2", 1, "act-2", "obs-level-late", "integer"),
            _rule("rule-3", 2, "act-1", "obs-level-terminal", "integer"),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _single_obs_policy_draft(observation_id: str, kind: _NUMERIC_KIND) -> AdaptivePolicyDraft:
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(_rule("rule-1", 0, "act-1", observation_id, kind),),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _shaped_policy_draft(rules: int) -> AdaptivePolicyDraft:
    """Two policy shapes that both bind the noisy state declaration."""
    first = _rule("rule-1", 0, "act-1", "obs-ratio-noisy", "number")
    second = _rule("rule-2", 1, "act-2", "obs-level", "integer")
    shaped = (first,) if rules == 1 else (first, second)
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=shaped,
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _request() -> AdaptivePolicyBindingRequest:
    return AdaptivePolicyBindingRequest(
        policy_id="policy-1",
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=_BOUND_AT,
        metadata={},
    )


def _prepare_campaign(
    store: InMemoryScenarioStore,
    world_id: str,
    campaign_id: str,
) -> None:
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


def _build_campaign(
    store: InMemoryScenarioStore,
    world_id: str,
    campaign_id: str,
    draft: AdaptivePolicyDraft,
) -> None:
    _prepare_campaign(store, world_id, campaign_id)
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=draft,
        binding_request=_request(),
    )


def _state_env() -> tuple[InMemoryScenarioStore, str, str]:
    """A real COMPILED campaign bound over two state-field declarations."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    _declare_state_field(store, world_id, "obs-level")
    _declare_state_field(
        store,
        world_id,
        "obs-ratio-noisy",
        field_id="ratio",
        noise=_ADDITIVE_UNIFORM,
    )
    _build_campaign(store, world_id, "campaign-1", _state_pair_policy_draft())
    return store, world_id, "campaign-1"


def _external_env() -> tuple[InMemoryScenarioStore, str, str]:
    """A real COMPILED campaign bound over two external declarations."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    _declare_external(store, world_id, "obs-a", "integer")
    _declare_external(store, world_id, "obs-b", "number")
    _build_campaign(store, world_id, "campaign-1", _external_pair_policy_draft())
    return store, world_id, "campaign-1"


def _state_declarations_env() -> tuple[InMemoryScenarioStore, str, str]:
    """A campaign bound over the delay family of one state field."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    _declare_state_field(store, world_id, "obs-level")
    _declare_state_field(store, world_id, "obs-level-late", timing=_TIMING_DELAY1)
    _declare_state_field(store, world_id, "obs-level-terminal", timing=_TIMING_DELAY3)
    _build_campaign(store, world_id, "campaign-1", _state_family_policy_draft())
    return store, world_id, "campaign-1"


def _bundle_values(
    store: InMemoryScenarioStore,
    world_id: str,
    *values: ExternalObservationInputValueDraft,
) -> tuple[ExternalObservationInputValueDraft, ...]:
    """The canonical (source step, declaration identity) ordered entries."""
    declaration_ids = {
        value.observation_id: store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, value.observation_id
        ).identifier
        for value in values
    }
    return tuple(
        sorted(
            values,
            key=lambda value: (value.source_step_index, declaration_ids[value.observation_id]),
        )
    )


def _bundle_draft(
    store: InMemoryScenarioStore,
    world_id: str,
    *values: ExternalObservationInputValueDraft,
) -> ExternalObservationInputBundleDraft:
    return ExternalObservationInputBundleDraft(
        entries=_bundle_values(store, world_id, *values), accepted_at=_ACCEPTED_AT
    )


def _accept_bundle(
    store: InMemoryScenarioStore,
    world_id: str,
    campaign_id: str,
    *values: ExternalObservationInputValueDraft,
) -> None:
    accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_bundle_draft(store, world_id, *values),
    )


def _step_draft(
    store: InMemoryScenarioStore,
    decision_step: int,
    final_decision_step: int,
    *,
    state: dict[str, dict[str, JsonValue]] | None = None,
    prior_events: tuple[RuntimeObservationEvent, ...] = (),
    external_bundle_draft: ExternalObservationInputBundleDraft | None = None,
) -> ObservationStepDraft:
    return ObservationStepDraft(
        decision_step=decision_step,
        final_decision_step=final_decision_step,
        state=_default_state(store) if state is None else state,
        prior_events=prior_events,
        external_bundle_draft=external_bundle_draft,
    )


def _derive(
    store: InMemoryScenarioStore,
    campaign_id: str,
    draft: ObservationStepDraft,
) -> ObservationStepResult:
    return derive_observation_step(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=draft,
    )


def _assert_no_activity(store: InMemoryScenarioStore) -> None:
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def _assert_safe_message(exc: BaseException, *secrets: object) -> None:
    text = str(exc)
    for secret in secrets:
        if isinstance(secret, str) and secret:
            assert secret not in text


def _assert_no_writes(store: InMemoryScenarioStore) -> None:
    assert len(store._runtime_observation_declarations) == 2
    assert len(store._adaptive_policies) == 1
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def _new_event(
    result: ObservationStepResult,
    observation_id: str,
) -> RuntimeObservationEvent:
    return next(event for event in result.new_events if event.observation_id == observation_id)


# ---------------------------------------------------------------------------
# 1-2. State-field success: exact source value and additive-uniform noise.
# ---------------------------------------------------------------------------


def test_no_noise_state_field_success() -> None:
    store, _world_id, campaign_id = _state_env()
    result = _derive(store, campaign_id, _step_draft(store, 0, 10))
    assert type(result) is ObservationStepResult
    assert len(result.new_events) == 2
    assert len(result.available_events) == 2
    level = _new_event(result, "obs-level")
    assert level.status == "observed"
    assert level.source_value == 4
    assert type(level.source_value) is int
    assert level.exposed_observation_value == 4
    assert level.applied_noise_value is None
    assert level.noise_draw_index is None
    assert level.source_state_hash is not None
    assert level.external_input_bundle_id is None
    assert level.terminal is False
    assert level.available_decision_step == 0
    assert level.identifier == runtime_observation_event_identifier(
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        runtime_observation_declaration_id=level.observation_declaration_id,
        source_step_index=0,
    )
    assert level.content_hash == runtime_observation_event_content_hash(level)
    for event in result.new_events:
        assert event.runtime_version == "4.0.0"
        assert event.scenario_seed_id == _SEED_ID
        assert event.sequence_position == result.new_events.index(event)


def test_additive_uniform_deterministic_success() -> None:
    store, _world_id, campaign_id = _state_env()
    first = _derive(store, campaign_id, _step_draft(store, 0, 10))
    second = _derive(store, campaign_id, _step_draft(store, 0, 10))
    noisy = _new_event(first, "obs-ratio-noisy")
    again = _new_event(second, "obs-ratio-noisy")
    assert noisy.status == "observed"
    assert noisy.source_value == 2.5
    assert noisy.applied_noise_value is not None
    assert type(noisy.applied_noise_value) is float
    assert noisy.noise_draw_index == 0
    assert noisy.exposed_observation_value != 2.5
    assert noisy == again
    expected_noise = _ADDITIVE_UNIFORM.lower_bound + (
        (_ADDITIVE_UNIFORM.upper_bound - _ADDITIVE_UNIFORM.lower_bound)
        * observation_noise_word(
            world_content_hash=noisy.world_content_hash,
            seed_content_hash=noisy.seed_content_hash,
            runtime_observation_declaration_content_hash=(
                noisy.observation_declaration_content_hash
            ),
            source_step_index=noisy.source_step_index,
            draw_index=0,
        )
        / 2**64
    )
    assert noisy.applied_noise_value == pytest.approx(expected_noise, abs=1e-12)
    assert noisy.exposed_observation_value == pytest.approx(2.5 + expected_noise, abs=1e-12)


# ---------------------------------------------------------------------------
# 3-4. External success without fresh noise; scheduled-missing evidence.
# ---------------------------------------------------------------------------


def test_external_observed_success_no_fresh_draw() -> None:
    store, world_id, campaign_id = _external_env()
    values = (
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=0, value=7),
        ExternalObservationInputValueDraft(observation_id="obs-b", source_step_index=0, value=1.5),
    )
    _accept_bundle(store, world_id, campaign_id, *values)
    result = _derive(
        store,
        campaign_id,
        _step_draft(
            store, 0, 10, state={}, external_bundle_draft=_bundle_draft(store, world_id, *values)
        ),
    )
    assert len(result.new_events) == 2
    for event in result.new_events:
        assert event.status == "observed"
        assert event.applied_noise_value is None
        assert event.noise_draw_index is None
        assert event.external_input_bundle_id is not None
        assert event.source_state_hash is None
    observed = {event.observation_id: event for event in result.new_events}
    assert observed["obs-a"].source_value == 7
    assert observed["obs-a"].exposed_observation_value == 7
    assert observed["obs-b"].exposed_observation_value == 1.5


def test_scheduled_missing_external_input_exact_missing_evidence() -> None:
    store, world_id, campaign_id = _external_env()
    values = (
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=0, value=7),
    )
    _accept_bundle(store, world_id, campaign_id, *values)
    result = _derive(
        store,
        campaign_id,
        _step_draft(
            store, 0, 10, state={}, external_bundle_draft=_bundle_draft(store, world_id, *values)
        ),
    )
    missing = [event for event in result.new_events if event.status == "missing"]
    assert len(missing) == 1
    event = missing[0]
    assert event.observation_id == "obs-b"
    assert event.source_value is None
    assert event.applied_noise_value is None
    assert event.exposed_observation_value is None
    assert event.observed_value_kind is None
    assert event.observed_value_unit is None
    assert event.noise_draw_index is None
    assert event.external_input_bundle_id is not None
    assert event.available_decision_step == 0
    assert event.terminal is False


# ---------------------------------------------------------------------------
# 5-8. Availability: delay 0, delay 1, pending delays, no double exposure.
# ---------------------------------------------------------------------------


def test_delay_zero_available_in_same_decision() -> None:
    store, _world_id, campaign_id = _state_env()
    result = _derive(store, campaign_id, _step_draft(store, 0, 10))
    available_ids = {event.observation_id for event in result.available_events}
    assert available_ids == {"obs-level", "obs-ratio-noisy"}
    for event in result.available_events:
        assert event.available_decision_step == 0
        assert event.terminal is False


def test_delay_one_available_exactly_at_next_decision() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    assert {event.observation_id for event in step0.new_events} == {
        "obs-level",
        "obs-level-late",
        "obs-level-terminal",
    }
    assert len(step0.available_events) == 1
    level0 = step0.available_events[0]
    assert level0.observation_id == "obs-level"
    late = _new_event(step0, "obs-level-late")
    assert late.available_decision_step == 1
    assert late.terminal is False
    step1 = _derive(
        store, campaign_id, _step_draft(store, 1, 10, prior_events=(*step0.new_events,))
    )
    late1 = next(
        event for event in step1.available_events if event.observation_id == "obs-level-late"
    )
    assert late1 == late
    fresh1 = _new_event(step1, "obs-level")
    assert fresh1.source_step_index == 1
    positions = [event.sequence_position for event in step1.new_events]
    assert positions == [3, 4, 5]
    assert fresh1.sequence_position == 3 + step1.new_events.index(fresh1)


def test_delay_greater_than_one_remains_valid_pending_prior_evidence() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    terminal0 = _new_event(step0, "obs-level-terminal")
    assert terminal0.terminal is False
    assert terminal0.available_decision_step == 3
    step1 = _derive(
        store, campaign_id, _step_draft(store, 1, 10, prior_events=(*step0.new_events,))
    )
    step1_ids = {event.observation_id for event in step1.available_events}
    assert step1_ids == {"obs-level", "obs-level-late"}
    step2 = _derive(
        store,
        campaign_id,
        _step_draft(store, 2, 10, prior_events=(*step0.new_events, *step1.new_events)),
    )
    step2_ids = {event.observation_id for event in step2.available_events}
    assert step2_ids == {"obs-level", "obs-level-late"}
    assert "obs-level-terminal" not in step2_ids
    # The step-1 sourced level event and the step-2 sourced level event are
    # distinct evidence; each is exposed at most once.
    available_identifiers = [event.identifier for event in step2.available_events]
    assert len(available_identifiers) == len(set(available_identifiers))
    assert len(available_identifiers) == 2


def test_past_evidence_is_not_exposed_twice() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    step1 = _derive(
        store, campaign_id, _step_draft(store, 1, 10, prior_events=(*step0.new_events,))
    )
    exposed = [event.identifier for event in step1.available_events]
    assert len(exposed) == len(set(exposed))
    level0_identifier = step0.available_events[0].identifier
    assert level0_identifier not in exposed
    level1 = _new_event(step1, "obs-level")
    assert level1.identifier != level0_identifier
    assert level1.source_step_index == 1


# ---------------------------------------------------------------------------
# 9-12. Repeated schedules, declaration ordering, terminality, terminal prior.
# ---------------------------------------------------------------------------


def test_repeated_schedule_distinct_events_per_source_step() -> None:
    store = build_observation_store()
    world_id = compile_observation_world(store)
    _declare_state_field(store, world_id, "obs-even", timing=_TIMING_EVERY2)
    _build_campaign(
        store,
        world_id,
        "campaign-1",
        _single_obs_policy_draft("obs-even", "integer"),
    )
    step0 = _derive(store, "campaign-1", _step_draft(store, 0, 10))
    assert len(step0.new_events) == 1
    step1 = _derive(
        store, "campaign-1", _step_draft(store, 1, 10, prior_events=(*step0.new_events,))
    )
    assert step1.new_events == ()
    assert step1.available_events == ()
    step2 = _derive(
        store,
        "campaign-1",
        _step_draft(store, 2, 10, prior_events=(*step0.new_events, *step1.new_events)),
    )
    assert len(step2.new_events) == 1
    assert step2.new_events[0].source_step_index == 2
    assert step2.new_events[0].sequence_position == 1
    assert step2.new_events[0].identifier != step0.new_events[0].identifier


def test_simultaneous_events_declaration_id_ordered() -> None:
    store, _world_id, campaign_id = _state_env()
    result = _derive(store, campaign_id, _step_draft(store, 0, 10))
    available_ids = [event.observation_declaration_id for event in result.available_events]
    assert available_ids == sorted(available_ids)
    new_ids = [event.observation_declaration_id for event in result.new_events]
    assert new_ids == sorted(new_ids)


def test_terminal_classification_uses_final_decision_step_at_creation() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    terminal0 = _new_event(step0, "obs-level-terminal")
    assert terminal0.terminal is False
    assert terminal0.available_decision_step == 3
    horizon2 = _derive(store, campaign_id, _step_draft(store, 0, 2))
    terminal2 = _new_event(horizon2, "obs-level-terminal")
    assert terminal2.terminal is True
    assert terminal2.available_decision_step is None
    assert terminal2.identifier == terminal0.identifier
    assert terminal2.content_hash != terminal0.content_hash
    horizon3 = _derive(store, campaign_id, _step_draft(store, 0, 3))
    boundary = _new_event(horizon3, "obs-level-terminal")
    assert boundary.terminal is False
    assert boundary.available_decision_step == 3


def test_terminal_prior_evidence_remains_but_never_becomes_available() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 2))
    assert _new_event(step0, "obs-level-terminal").terminal is True
    late0 = _new_event(step0, "obs-level-late")
    assert late0.terminal is False
    assert late0.available_decision_step == 1
    step1 = _derive(store, campaign_id, _step_draft(store, 1, 2, prior_events=(*step0.new_events,)))
    step1_ids = {event.observation_id for event in step1.available_events}
    assert step1_ids == {"obs-level", "obs-level-late"}
    step2 = _derive(
        store,
        campaign_id,
        _step_draft(store, 2, 2, prior_events=(*step0.new_events, *step1.new_events)),
    )
    step2_ids = {event.observation_id for event in step2.available_events}
    assert step2_ids == {"obs-level", "obs-level-late"}
    for available in (*step1.available_events, *step2.available_events):
        assert available.observation_id != "obs-level-terminal"
        assert available.terminal is False


# ---------------------------------------------------------------------------
# 13-18. Draft horizon and prior-ledger rejection surface.
# ---------------------------------------------------------------------------


def test_wrong_final_decision_step_type_and_value_rejected() -> None:
    store, _world_id, campaign_id = _state_env()
    for bad in (True, False, 1.0, "3", None):
        draft = _step_draft(store, 0, 0)
        object.__setattr__(draft, "final_decision_step", bad)
        with pytest.raises(RuntimeObservationEventValidationError) as excinfo:
            _derive(store, campaign_id, draft)
        _assert_safe_message(excinfo.value, TENANT, campaign_id, "obs-level", "seed-1")
    with pytest.raises(RuntimeObservationEventValidationError):
        _derive(store, campaign_id, _step_draft(store, 0, -1))
    assert _derive(store, campaign_id, _step_draft(store, 0, 0)) is not None


def test_decision_step_beyond_final_decision_step_rejected() -> None:
    store, _world_id, campaign_id = _state_env()
    with pytest.raises(RuntimeObservationEventValidationError) as excinfo:
        _derive(store, campaign_id, _step_draft(store, 6, 5))
    _assert_safe_message(excinfo.value, TENANT, campaign_id, "seed-1")
    assert _derive(store, campaign_id, _step_draft(store, 0, 0)) is not None


def test_missing_prior_scheduled_coordinate_rejected() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    incomplete = tuple(
        event for event in step0.new_events if event.observation_id != "obs-level-late"
    )
    with pytest.raises(RuntimeObservationEventCausalOrderError) as excinfo:
        _derive(store, campaign_id, _step_draft(store, 1, 10, prior_events=incomplete))
    _assert_safe_message(excinfo.value, TENANT, campaign_id, "obs-level-late", "seed-1")


def test_extra_unscheduled_and_future_source_prior_coordinates_rejected() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    victim = _new_event(step0, "obs-level-late")
    future_source = victim.model_copy(
        update={
            "source_step_index": 5,
            "available_decision_step": 6,
            "sequence_position": 3,
            "identifier": runtime_observation_event_identifier(
                tenant_id=TENANT,
                campaign_id=campaign_id,
                scenario_seed_id=_SEED_ID,
                runtime_observation_declaration_id=victim.observation_declaration_id,
                source_step_index=5,
            ),
            "content_hash": "0" * 64,
        }
    )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(store, 1, 10, prior_events=(*step0.new_events, future_source)),
        )
    # A bound declaration sourced at an unscheduled coordinate (its cadence
    # is every-2) is an extra coordinate the ledger must reject.
    every2_store = build_observation_store()
    every2_world = compile_observation_world(every2_store)
    _declare_state_field(every2_store, every2_world, "obs-level", timing=_TIMING_EVERY2)
    _build_campaign(
        every2_store,
        every2_world,
        "campaign-1",
        _single_obs_policy_draft("obs-level", "integer"),
    )
    every2_step0 = _derive(every2_store, "campaign-1", _step_draft(every2_store, 0, 10))
    unscheduled = _new_event(every2_step0, "obs-level").model_copy(
        update={
            "source_step_index": 1,
            "available_decision_step": 1,
            "sequence_position": 1,
            "identifier": runtime_observation_event_identifier(
                tenant_id=TENANT,
                campaign_id="campaign-1",
                scenario_seed_id=_SEED_ID,
                runtime_observation_declaration_id=store.get_runtime_observation_declaration(
                    TENANT, "scenario-1", every2_world, "obs-level"
                ).identifier,
                source_step_index=1,
            ),
            "content_hash": "0" * 64,
        }
    )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            every2_store,
            "campaign-1",
            _step_draft(every2_store, 2, 10, prior_events=(*every2_step0.new_events, unscheduled)),
        )


def test_duplicate_and_reordered_prior_coordinates_rejected() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(store, 1, 10, prior_events=(*step0.new_events, step0.new_events[0])),
        )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(store, 1, 10, prior_events=tuple(reversed(step0.new_events))),
        )


def test_forged_identity_hash_and_provenance_rejected() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    ledger = step0.new_events

    def spliced(**update: object) -> tuple[RuntimeObservationEvent, ...]:
        victim = ledger[0]
        forged = victim.model_copy(update=update)
        return tuple(forged if event is victim else event for event in ledger)

    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(
                store, 1, 10, prior_events=spliced(identifier="runtime-observation-event-x")
            ),
        )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(store, 1, 10, prior_events=spliced(content_hash="0" * 64)),
        )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(
                store,
                1,
                10,
                prior_events=spliced(world_content_hash="f" * 64, content_hash="0" * 64),
            ),
        )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(
                store,
                1,
                10,
                prior_events=spliced(seed_content_hash="a" * 64, content_hash="0" * 64),
            ),
        )
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _derive(
            store,
            campaign_id,
            _step_draft(
                store, 1, 10, prior_events=spliced(terminal=True, available_decision_step=None)
            ),
        )


# ---------------------------------------------------------------------------
# 19-20. State collection and state value rejection surface.
# ---------------------------------------------------------------------------


def test_state_collection_missing_extra_foreign_rejected() -> None:
    store, _world_id, campaign_id = _state_env()
    with pytest.raises(RuntimeObservationEventValidationError):
        _derive(store, campaign_id, _step_draft(store, 0, 10, state={}))
    with pytest.raises(RuntimeObservationEventValidationError):
        _derive(store, campaign_id, _step_draft(store, 0, 10, state={"sm-1": {"status": "idle"}}))
    with pytest.raises(RuntimeObservationEventValidationError):
        _derive(
            store,
            campaign_id,
            _step_draft(
                store,
                0,
                10,
                state={"sm-1": {"level": 4, "ratio": 2.5, "status": "idle", "ghost": 1}},
            ),
        )
    with pytest.raises(RuntimeObservationEventValidationError):
        _derive(
            store, campaign_id, _step_draft(store, 0, 10, state={"foreign-model": {"level": 4}})
        )


def test_bool_nan_infinity_state_values_rejected() -> None:
    store, _world_id, campaign_id = _state_env()
    for bad in (True, float("nan"), float("inf"), float("-inf"), "4"):
        with pytest.raises(RuntimeObservationEventValidationError) as excinfo:
            _derive(
                store,
                campaign_id,
                _step_draft(
                    store,
                    0,
                    10,
                    state={"sm-1": {"level": bad, "ratio": 2.5, "status": "idle"}},
                ),
            )
        _assert_safe_message(excinfo.value, TENANT, campaign_id, "level", "seed-1")


# ---------------------------------------------------------------------------
# 21-22. Noise coordinate invariance.
# ---------------------------------------------------------------------------


def test_noise_changes_with_world_seed_declaration_step_draw() -> None:
    store, _world_id, campaign_id = _state_env()
    baseline = _derive(store, campaign_id, _step_draft(store, 0, 10))
    noisy = _new_event(baseline, "obs-ratio-noisy")
    base_word = observation_noise_word(
        world_content_hash=noisy.world_content_hash,
        seed_content_hash=noisy.seed_content_hash,
        runtime_observation_declaration_content_hash=noisy.observation_declaration_content_hash,
        source_step_index=0,
        draw_index=0,
    )
    fresh_seed_hash = seed_content_hash(
        next(
            seed
            for seed in store.get_campaign(TENANT, campaign_id).seed_ensemble
            if seed.identifier == _SEED_ID
        )
    )
    assert fresh_seed_hash == noisy.seed_content_hash
    assert (
        observation_noise_word(
            world_content_hash="e" * 64,
            seed_content_hash=fresh_seed_hash,
            runtime_observation_declaration_content_hash=(
                noisy.observation_declaration_content_hash
            ),
            source_step_index=0,
            draw_index=0,
        )
        != base_word
    )
    assert (
        observation_noise_word(
            world_content_hash=noisy.world_content_hash,
            seed_content_hash="d" * 64,
            runtime_observation_declaration_content_hash=(
                noisy.observation_declaration_content_hash
            ),
            source_step_index=0,
            draw_index=0,
        )
        != base_word
    )
    assert (
        observation_noise_word(
            world_content_hash=noisy.world_content_hash,
            seed_content_hash=fresh_seed_hash,
            runtime_observation_declaration_content_hash="c" * 64,
            source_step_index=0,
            draw_index=0,
        )
        != base_word
    )
    assert (
        observation_noise_word(
            world_content_hash=noisy.world_content_hash,
            seed_content_hash=fresh_seed_hash,
            runtime_observation_declaration_content_hash=(
                noisy.observation_declaration_content_hash
            ),
            source_step_index=1,
            draw_index=0,
        )
        != base_word
    )
    assert (
        observation_noise_word(
            world_content_hash=noisy.world_content_hash,
            seed_content_hash=fresh_seed_hash,
            runtime_observation_declaration_content_hash=(
                noisy.observation_declaration_content_hash
            ),
            source_step_index=0,
            draw_index=1,
        )
        != base_word
    )


def test_noise_invariant_across_policy_shape_and_order() -> None:
    store, world_id, _campaign_id = _state_env()
    baseline = _derive(store, "campaign-1", _step_draft(store, 0, 10))
    base_noisy = _new_event(baseline, "obs-ratio-noisy")
    _declare_state_field(store, world_id, "obs-extra", field_id="ratio")
    _build_campaign(store, world_id, "campaign-2", _shaped_policy_draft(1))
    _build_campaign(store, world_id, "campaign-3", _shaped_policy_draft(2))
    for campaign_id in ("campaign-2", "campaign-3"):
        shaped = _derive(store, campaign_id, _step_draft(store, 0, 10))
        shaped_noisy = _new_event(shaped, "obs-ratio-noisy")
        assert shaped_noisy.applied_noise_value == base_noisy.applied_noise_value
        assert shaped_noisy.exposed_observation_value == base_noisy.exposed_observation_value


# ---------------------------------------------------------------------------
# 23-26. Determinism, immutability, purity, safe failure.
# ---------------------------------------------------------------------------


def test_repeated_calls_are_byte_identical() -> None:
    store, _world_id, campaign_id = _state_env()
    first = _derive(store, campaign_id, _step_draft(store, 0, 10))
    second = _derive(store, campaign_id, _step_draft(store, 0, 10))
    assert first == second
    assert first.new_events == second.new_events
    assert first.available_events == second.available_events


def test_inputs_are_unchanged() -> None:
    store, _world_id, campaign_id = _state_declarations_env()
    state = _default_state(store)
    state_snapshot = copy.deepcopy(state)
    step0 = _derive(store, campaign_id, _step_draft(store, 0, 10))
    prior_events = step0.new_events
    prior_snapshot = copy.deepcopy(prior_events)
    draft = _step_draft(store, 1, 10, state=state, prior_events=prior_events)
    draft_snapshot = copy.deepcopy(draft)
    _derive(store, campaign_id, draft)
    assert state == state_snapshot
    assert draft == draft_snapshot
    assert prior_events == prior_snapshot
    for event in prior_events:
        assert event.content_hash == runtime_observation_event_content_hash(event)


def test_zero_store_writes_and_zero_activity() -> None:
    store, _world_id, campaign_id = _state_env()
    _derive(store, campaign_id, _step_draft(store, 0, 10))
    _assert_no_writes(store)
    _assert_no_activity(store)


def test_no_raw_exception_leakage_and_failure_atomicity() -> None:
    store, _world_id, campaign_id = _state_env()
    secrets = (TENANT, campaign_id, "scenario-1", _SEED_ID, "obs-level", "sm-1")
    bad_prior_draft = _step_draft(store, 0, 10)
    object.__setattr__(bad_prior_draft, "prior_events", (object(),))
    bad_state_draft = _step_draft(store, 0, 10)
    object.__setattr__(bad_state_draft, "state", [("sm-1", {})])
    for draft in (bad_prior_draft, bad_state_draft):
        with pytest.raises(KalhasDomainError) as excinfo:
            _derive(store, campaign_id, draft)
        assert type(excinfo.value) in (
            RuntimeObservationEventValidationError,
            RuntimeObservationEventIntegrityError,
            RuntimeObservationEventCausalOrderError,
            RuntimeObservationEventNoiseError,
        )
        _assert_safe_message(excinfo.value, *secrets)
    _assert_no_writes(store)
    _assert_no_activity(store)
