"""External-observation-input bundle authoring and storage tests (H28-S06B1).

Builds a real compiled world, a real COMPILED campaign with a real scenario
seed, real stored external-input ``RuntimeObservationDeclaration`` records, a
real stored ``AdaptivePolicy`` bound over them, and exercises the immutable
``ExternalObservationInputBundle`` authoring boundary end to end: the
application-local untrusted drafts, the deterministic accept flow through
``accept_external_observation_input_bundle``, the store's no-overwrite
put/get surface, the deterministic identity and content hashes, the
defensive copies, and the adversarial rejection surface. All entries,
identifiers, and content hashes are computed truthfully with the production
identity helpers; no validator is monkeypatched and no bundle value is
manufactured by replacing the production functions.

The adversarial proof covers, against the implementation itself: exact
integer and number bundles; multiple canonically ordered steps and
declarations; exact copied campaign/world/seed/declaration/channel/kind/unit
provenance; deterministic identifiers and content hashes; accepted_at
preservation; defensive copies and input immutability; zero operational
activity; wrong campaign state; unknown/foreign campaign, world, seed,
policy, and declaration; state-field declarations; policy-unused
observations; wrong value kinds and bool/string/NaN/Infinity values;
unscheduled source steps; duplicate coordinates; reordered entries;
wrong-type, subclassed, and validator-bypassed drafts; duplicate bundle
writes; forged entry and bundle identifiers and content hashes;
self-consistently rehashed altered seed/world/declaration/channel/kind/unit
provenance; corrupt private-store bundles on get; unknown and foreign
bundles never leaking; the absence of update/delete/list/repair surfaces;
raw exceptions never escaping; and every failure leaving storage and
activity unchanged.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.external_observation_input_errors import (
    ExternalObservationInputAlreadyExistsError,
    ExternalObservationInputIntegrityError,
    ExternalObservationInputNotFoundError,
    ExternalObservationInputValidationError,
)
from kalhas.application.external_observation_input_identity import (
    external_observation_input_bundle_content_hash,
    external_observation_input_bundle_identifier,
    external_observation_input_entry_content_hash,
    external_observation_input_entry_identifier,
)
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
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationInputEntry,
    ExternalObservationSource,
    NoObservationNoise,
    ObservationTiming,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION

from tests.phase4_helpers import NOW, TENANT, prepare
from tests.phase20_helpers import build_observation_store, compile_observation_world

OTHER_TENANT = "tenant-99"

_BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
_ACCEPTED_AT = datetime(2026, 1, 10, 9, 0, 0, tzinfo=UTC)
_TIMING = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)
_SEED_ID = "seed-1"
_NumericKind = Literal["integer", "number"]

_SAFE_SECRETS = (
    TENANT,
    "campaign-1",
    "scenario-1",
    "seed-1",
    "obs-a",
    "obs-b",
    "obs-c",
    "obs-level",
    "channel-1",
    "channel-2",
)


def _declare_external(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    kind: _NumericKind,
    *,
    channel: str = "channel-1",
    unit: str | None = None,
    timing: ObservationTiming = _TIMING,
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            external_source=ExternalObservationDraft(
                external_channel_id=channel, external_value_kind=kind
            ),
            unit=unit,
            timing=timing,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=_DECLARED_AT,
            metadata={},
        ),
    )


def _declare_state_field(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            state_source=StateFieldObservationDraft(
                manifest_id="manifest-1", state_model_id="sm-1", state_field_id="level"
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
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id=observation_id,
        observed_value_kind=kind,
        unit=unit,
        operator="gt",
        threshold=threshold,
        missing_behavior="false",
    )


def _policy_draft() -> AdaptivePolicyDraft:
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
                enter_condition=_leaf("c2a", "obs-b", "number", 0.0, unit="speed"),
                retain_condition=_leaf("c2r", "obs-b", "number", 0.0, unit="speed"),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-3",
                priority=2,
                target_action_id="act-1",
                enter_condition=_leaf("c3a", "obs-c", "integer", 0),
                retain_condition=_leaf("c3r", "obs-c", "integer", 0),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-4",
                priority=3,
                target_action_id="act-2",
                enter_condition=_leaf("c4a", "obs-level", "integer", 0),
                retain_condition=_leaf("c4r", "obs-level", "integer", 0),
                per_rule_switch_budget=1,
            ),
        ),
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


def _build_bundle_env(
    campaign_id: str = "campaign-1",
) -> tuple[InMemoryScenarioStore, str, str]:
    """A real COMPILED campaign with strategies, plans, and declarations."""
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
    _declare_external(store, world_id, "obs-a", "integer")
    _declare_external(store, world_id, "obs-b", "number", unit="speed")
    _declare_external(
        store,
        world_id,
        "obs-c",
        "integer",
        channel="channel-2",
        timing=ObservationTiming(start_step=2, every_n_steps=3, delay_steps=1),
    )
    _declare_state_field(store, world_id, "obs-level")
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        draft=_policy_draft(),
        binding_request=_request(),
    )
    return store, world_id, campaign_id


def _value(
    observation_id: str,
    source_step_index: int,
    value: int | float,
) -> ExternalObservationInputValueDraft:
    return ExternalObservationInputValueDraft(
        observation_id=observation_id, source_step_index=source_step_index, value=value
    )


def _draft(
    *values: ExternalObservationInputValueDraft,
    accepted_at: datetime = _ACCEPTED_AT,
) -> ExternalObservationInputBundleDraft:
    return ExternalObservationInputBundleDraft(entries=tuple(values), accepted_at=accepted_at)


def _campaign_seed_hash(store: InMemoryScenarioStore, campaign_id: str) -> str:
    campaign = store.get_campaign(TENANT, campaign_id)
    seed = next(seed for seed in campaign.seed_ensemble if seed.identifier == _SEED_ID)
    return seed_content_hash(seed)


def _ordered(
    store: InMemoryScenarioStore,
    world_id: str,
    values: tuple[ExternalObservationInputValueDraft, ...],
) -> tuple[ExternalObservationInputValueDraft, ...]:
    """The caller-provided canonical order: (source_step_index, declaration id)."""
    declaration_ids = {
        observation_id: store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, observation_id
        ).identifier
        for observation_id in {value.observation_id for value in values}
    }
    return tuple(
        sorted(
            values,
            key=lambda value: (value.source_step_index, declaration_ids[value.observation_id]),
        )
    )


def _assert_no_activity(store: InMemoryScenarioStore) -> None:
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def _assert_only_bundle_collection(store: InMemoryScenarioStore, campaign_id: str) -> None:
    """A failed operation must leave the bundle collection exactly untouched."""
    assert len(store._external_observation_input_bundles) == (
        1 if any(key[1] == campaign_id for key in store._external_observation_input_bundles) else 0
    )


def _assert_safe_message(exc: BaseException, *secrets: object) -> None:
    text = str(exc)
    for secret in secrets:
        if isinstance(secret, str) and secret:
            assert secret not in text


@pytest.fixture()
def bundle_env() -> tuple[InMemoryScenarioStore, str, str]:
    return _build_bundle_env()


# ---------------------------------------------------------------------------
# SUCCESS
# ---------------------------------------------------------------------------


def test_deterministic_integer_bundle(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )

    assert type(bundle) is ExternalObservationInputBundle
    assert bundle.runtime_version == "4.0.0"
    assert bundle.tenant_id == TENANT
    assert bundle.schema_version == SCHEMA_VERSION
    assert bundle.campaign_id == campaign_id
    assert bundle.scenario_id == "scenario-1"
    assert bundle.scenario_seed_id == _SEED_ID

    world = store.get_world(TENANT, world_id)
    assert bundle.world_version_id == world_id
    assert bundle.world_content_hash == world.content_hash

    stored_decl = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-a")
    assert len(bundle.entries) == 1
    entry = bundle.entries[0]
    assert type(entry) is ExternalObservationInputEntry
    assert entry.observation_id == "obs-a"
    assert entry.runtime_observation_declaration_id == stored_decl.identifier
    assert entry.runtime_observation_declaration_content_hash == stored_decl.content_hash
    assert entry.external_channel_id == "channel-1"
    assert entry.source_step_index == 0
    assert entry.value_kind == "integer"
    assert entry.unit is None
    assert entry.value == 7
    assert type(entry.value) is int

    # Exact deterministic identifiers and content hashes.
    assert entry.identifier == external_observation_input_entry_identifier(
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        runtime_observation_declaration_id=stored_decl.identifier,
        source_step_index=0,
    )
    assert entry.content_hash == external_observation_input_entry_content_hash(entry)
    assert bundle.identifier == external_observation_input_bundle_identifier(
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_id="scenario-1",
        world_version_id=world_id,
        scenario_seed_id=_SEED_ID,
        runtime_version="4.0.0",
        schema_version=SCHEMA_VERSION,
    )
    assert bundle.content_hash == external_observation_input_bundle_content_hash(bundle)

    # Persisted exactly once and retrievable.
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )
    assert stored == bundle
    assert stored is not bundle
    assert len(store._external_observation_input_bundles) == 1
    _assert_no_activity(store)


def test_deterministic_number_bundle(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-b", 0, 2.5),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )

    entry = bundle.entries[0]
    assert entry.observation_id == "obs-b"
    assert entry.value_kind == "number"
    assert entry.unit == "speed"
    assert entry.value == 2.5
    assert type(entry.value) is float
    stored_decl = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-b")
    assert entry.runtime_observation_declaration_id == stored_decl.identifier
    assert entry.runtime_observation_declaration_content_hash == stored_decl.content_hash
    _assert_no_activity(store)


def test_number_kind_accepts_exact_int_value(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-b", 0, 3),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    assert bundle.entries[0].value_kind == "number"
    assert bundle.entries[0].value == 3
    assert type(bundle.entries[0].value) is int


def test_multiple_canonically_ordered_steps_and_declarations(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(
        store,
        world_id,
        (
            _value("obs-a", 0, 7),
            _value("obs-b", 0, 1.5),
            _value("obs-c", 2, 5),
            _value("obs-a", 5, 9),
        ),
    )
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    assert [entry.observation_id for entry in bundle.entries] == [
        "obs-a",
        "obs-b",
        "obs-c",
        "obs-a",
    ]
    assert [entry.source_step_index for entry in bundle.entries] == [0, 0, 2, 5]
    assert bundle.entries[0].value == 7
    assert bundle.entries[1].value == 1.5
    assert bundle.entries[2].value == 5
    assert bundle.entries[3].value == 9
    # delay_steps is preserved by the declaration but never shifts the coordinate.
    decl_c = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-c")
    assert decl_c.timing.delay_steps == 1
    assert bundle.entries[2].source_step_index == 2
    _assert_no_activity(store)


def test_exact_copied_provenance(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    campaign = store.get_campaign(TENANT, campaign_id)
    world = store.get_world(TENANT, world_id)
    stored_decl = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-a")
    policy = store.get_adaptive_policy(TENANT, campaign_id)

    assert bundle.campaign_id == campaign.identifier
    assert bundle.scenario_id == campaign.scenario_id
    assert bundle.world_version_id == campaign.world_version_id
    assert bundle.world_version_id == world.identifier
    assert bundle.world_content_hash == world.content_hash
    assert bundle.scenario_seed_id == _SEED_ID
    assert bundle.seed_content_hash == _campaign_seed_hash(store, campaign_id)
    assert bundle.seed_content_hash == seed_content_hash(
        next(seed for seed in campaign.seed_ensemble if seed.identifier == _SEED_ID)
    )

    entry = bundle.entries[0]
    assert entry.runtime_observation_declaration_id == stored_decl.identifier
    assert entry.runtime_observation_declaration_content_hash == stored_decl.content_hash
    assert entry.observation_id == stored_decl.observation_id
    assert isinstance(stored_decl.observation_source, ExternalObservationSource)
    assert entry.external_channel_id == stored_decl.observation_source.external_channel_id
    assert entry.value_kind == stored_decl.observed_value_kind
    assert entry.unit == stored_decl.unit
    binding = next(
        binding for binding in policy.observation_bindings if binding.observation_id == "obs-a"
    )
    assert entry.runtime_observation_declaration_id == binding.runtime_observation_declaration_id
    assert (
        entry.runtime_observation_declaration_content_hash
        == binding.runtime_observation_declaration_content_hash
    )


def test_accepted_at_preserved(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    accepted_at = datetime(2026, 1, 10, 9, 0, 0, tzinfo=UTC)
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values, accepted_at=accepted_at),
    )
    assert bundle.accepted_at == accepted_at
    assert bundle.accepted_at.utcoffset() is not None
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )
    assert stored.accepted_at == accepted_at


def test_defensive_copies_and_input_immutability(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7), (_value("obs-b", 0, 1.5))))
    draft = _draft(*values)
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=draft,
    )
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )
    # The store holds a detached copy; reads return fresh detached copies.
    key = (TENANT, campaign_id, _SEED_ID)
    assert store._external_observation_input_bundles[key] is not bundle
    assert stored is not bundle
    assert stored.entries[0] is not bundle.entries[0]
    assert stored == bundle
    # The draft and its values were never mutated or aliased into the bundle.
    assert draft.entries == values
    assert bundle.entries[0].value == 7
    assert bundle.entries[1].value == 1.5


def test_input_immutable_after_failure(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7), (_value("obs-a", 0, 8))))
    draft = _draft(*values)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=draft,
        )
    assert draft.entries == values


def test_deterministic_across_equivalent_inputs(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    first = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    second_store, second_world, second_campaign = _build_bundle_env("campaign-2")
    second = accept_external_observation_input_bundle(
        second_store,
        tenant_id=TENANT,
        campaign_id=second_campaign,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    assert second_world == world_id
    assert first.campaign_id != second.campaign_id
    assert first.identifier == external_observation_input_bundle_identifier(
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_id="scenario-1",
        world_version_id=world_id,
        scenario_seed_id=_SEED_ID,
        runtime_version="4.0.0",
        schema_version=SCHEMA_VERSION,
    )
    assert second.identifier == external_observation_input_bundle_identifier(
        tenant_id=TENANT,
        campaign_id=second_campaign,
        scenario_id="scenario-1",
        world_version_id=second_world,
        scenario_seed_id=_SEED_ID,
        runtime_version="4.0.0",
        schema_version=SCHEMA_VERSION,
    )


def test_zero_activity_on_success(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    _assert_no_activity(store)


# ---------------------------------------------------------------------------
# REJECTION — authority and provenance
# ---------------------------------------------------------------------------


def test_wrong_campaign_state_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    store.update_campaign_status(
        TENANT,
        campaign_id,
        CampaignStatus(
            identifier="status-2",
            tenant_id=TENANT,
            campaign_id=campaign_id,
            state=CampaignState.RUNNING,
            changed_at=NOW,
        ),
    )
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    with pytest.raises(ExternalObservationInputValidationError) as excinfo:
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_safe_message(excinfo.value, *_SAFE_SECRETS, "7")


def test_unknown_campaign_rejected() -> None:
    store, world_id, _ = _build_bundle_env()
    values = (_value("obs-a", 0, 7),)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id="campaign-unknown",
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_foreign_tenant_rejected() -> None:
    store, world_id, _ = _build_bundle_env()
    values = (_value("obs-a", 0, 7),)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=OTHER_TENANT,
            campaign_id="campaign-1",
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_foreign_world_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, _, campaign_id = bundle_env
    campaign = store.get_campaign(TENANT, campaign_id)
    forged = campaign.model_copy(update={"world_version_id": "world-missing"})
    store._campaigns[(TENANT, campaign_id)] = forged
    values = (_value("obs-a", 0, 7),)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_foreign_seed_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id="seed-missing",
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_missing_policy_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    store._adaptive_policies.pop((TENANT, campaign_id))
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_foreign_policy_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    policy = store.get_adaptive_policy(TENANT, campaign_id)
    forged = policy.model_copy(update={"campaign_id": "campaign-other"})
    store._adaptive_policies[(TENANT, campaign_id)] = forged
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    with pytest.raises(
        (ExternalObservationInputValidationError, ExternalObservationInputIntegrityError)
    ):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_missing_declaration_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = (_value("obs-b", 0, 2.5),)
    store._runtime_observation_declarations.pop((TENANT, "scenario-1", world_id, "obs-b"))
    with pytest.raises(ExternalObservationInputIntegrityError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_state_field_declaration_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-level", 0, 3),))
    with pytest.raises(ExternalObservationInputValidationError) as excinfo:
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    assert isinstance(excinfo.value, ExternalObservationInputValidationError)
    _assert_safe_message(excinfo.value, *_SAFE_SECRETS, "3")
    _assert_no_activity(store)


def test_policy_unused_declaration_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    _declare_external(store, world_id, "obs-unused", "integer", channel="channel-9")
    values = _ordered(store, world_id, (_value("obs-unused", 0, 4),))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_undeclared_observation_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = (_value("obs-ghost", 0, 4),)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


# ---------------------------------------------------------------------------
# REJECTION — values, cadence, ordering, drafts
# ---------------------------------------------------------------------------


def test_wrong_value_kind_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    # integer declaration with a float value
    values = _ordered(store, world_id, (_value("obs-a", 0, 7.0),))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    # integer declaration with a string value
    forged_string = _value("obs-a", 0, 7)
    object.__setattr__(forged_string, "value", "7")
    values = _ordered(store, world_id, (forged_string,))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_bool_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = (_value("obs-a", 0, True),)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_nan_and_infinity_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    for bad in (float("nan"), float("inf"), float("-inf")):
        values = (_value("obs-b", 0, bad),)
        with pytest.raises(ExternalObservationInputValidationError):
            accept_external_observation_input_bundle(
                store,
                tenant_id=TENANT,
                campaign_id=campaign_id,
                scenario_seed_id=_SEED_ID,
                draft=_draft(*values),
            )
    _assert_no_activity(store)


def test_unscheduled_source_step_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    # obs-c cadence: start_step=2, every_n_steps=3 -> steps 2, 5, 8, ...
    for step in (0, 1, 3, 4, 6):
        values = _ordered(store, world_id, (_value("obs-c", step, 5),))
        with pytest.raises(ExternalObservationInputValidationError):
            accept_external_observation_input_bundle(
                store,
                tenant_id=TENANT,
                campaign_id=campaign_id,
                scenario_seed_id=_SEED_ID,
                draft=_draft(*values),
            )
    # scheduled step 2 is accepted
    values = _ordered(store, world_id, (_value("obs-c", 2, 5),))
    bundle = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    assert bundle.entries[0].source_step_index == 2
    _assert_no_activity(store)


def test_duplicate_coordinate_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values = (
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=0, value=7),
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=0, value=8),
    )
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_reordered_entries_rejected(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    values: tuple[ExternalObservationInputValueDraft, ...] = (
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=0, value=7),
        ExternalObservationInputValueDraft(observation_id="obs-b", source_step_index=0, value=1.5),
        ExternalObservationInputValueDraft(observation_id="obs-a", source_step_index=2, value=5),
    )
    # Reverse the canonical order to prove rejection rather than sorting.
    canonical = _ordered(store, world_id, values)
    values = tuple(reversed(values)) if canonical == values else tuple(reversed(canonical))
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    _assert_no_activity(store)


def test_wrong_type_and_subclass_draft_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env

    class _ForgedBundleDraft(ExternalObservationInputBundleDraft):
        pass

    class _ForgedValueDraft(ExternalObservationInputValueDraft):
        pass

    value = _value("obs-a", 0, 7)
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=ExternalObservationInputBundleDraft.__new__(ExternalObservationInputBundleDraft),
        )
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_ForgedBundleDraft(entries=(value,), accepted_at=_ACCEPTED_AT),
        )
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=ExternalObservationInputBundleDraft(
                entries=(_ForgedValueDraft(observation_id="obs-a", source_step_index=0, value=7),),
                accepted_at=_ACCEPTED_AT,
            ),
        )
    # entries must be a tuple, not a list
    list_entries = copy.copy(_draft(value))
    object.__setattr__(list_entries, "entries", [value])
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=list_entries,
        )
    # empty entries tuple
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=ExternalObservationInputBundleDraft(entries=(), accepted_at=_ACCEPTED_AT),
        )
    # naive timestamp
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=ExternalObservationInputBundleDraft(
                entries=(value,), accepted_at=datetime(2026, 1, 10, 9, 0, 0)
            ),
        )
    _assert_no_activity(store)


def test_model_copy_forged_draft_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    value = _value("obs-a", 0, 7)
    draft = _draft(value)
    forged = copy.copy(draft)
    object.__setattr__(forged, "entries", ())
    with pytest.raises(ExternalObservationInputValidationError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=forged,
        )
    _assert_no_activity(store)


def test_negative_and_wrong_typed_step_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    for bad_step in (-1, 0.5, True):
        forged_step = _value("obs-a", 0, 7)
        object.__setattr__(forged_step, "source_step_index", bad_step)
        values = (forged_step,)
        with pytest.raises(ExternalObservationInputValidationError):
            accept_external_observation_input_bundle(
                store,
                tenant_id=TENANT,
                campaign_id=campaign_id,
                scenario_seed_id=_SEED_ID,
                draft=_draft(*values),
            )
    _assert_no_activity(store)


def test_duplicate_bundle_write_never_overwrites(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    values = _ordered(store, world_id, (_value("obs-a", 0, 7),))
    first = accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )
    with pytest.raises(ExternalObservationInputAlreadyExistsError):
        accept_external_observation_input_bundle(
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(*values),
        )
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )
    assert stored == first
    assert len(store._external_observation_input_bundles) == 1
    _assert_no_activity(store)


# ---------------------------------------------------------------------------
# STORE boundary — forgeries, corruption, leakage, no-repair
# ---------------------------------------------------------------------------


def _accept_base(
    store: InMemoryScenarioStore, world_id: str, campaign_id: str
) -> ExternalObservationInputBundle:
    values = _ordered(store, world_id, (_value("obs-a", 0, 7), (_value("obs-b", 0, 1.5))))
    return accept_external_observation_input_bundle(
        store,
        tenant_id=TENANT,
        campaign_id=campaign_id,
        scenario_seed_id=_SEED_ID,
        draft=_draft(*values),
    )


def _valid_bundle() -> ExternalObservationInputBundle:
    """A valid bundle accepted against a scratch store (the target stays unwritten)."""
    other, other_world, other_campaign = _build_bundle_env()
    return _accept_base(other, other_world, other_campaign)


def test_forged_entry_identifier_rejected_on_write(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bundle_env
    valid = _valid_bundle()
    forged_entry = valid.entries[0].model_copy(update={"identifier": "forged-entry"})
    forged = valid.model_copy(update={"entries": (forged_entry, *valid.entries[1:])})
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.put_external_observation_input_bundle(
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            bundle=forged,
        )
    # the forged write is rejected and nothing is stored
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def test_forged_entry_content_hash_rejected_on_write(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bundle_env
    valid = _valid_bundle()
    forged_entry = valid.entries[0].model_copy(update={"content_hash": "1" * 64})
    forged = valid.model_copy(update={"entries": (forged_entry, *valid.entries[1:])})
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.put_external_observation_input_bundle(
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            bundle=forged,
        )
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def test_forged_bundle_identifier_rejected_on_write(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bundle_env
    valid = _valid_bundle()
    forged = valid.model_copy(update={"identifier": "forged-bundle"})
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.put_external_observation_input_bundle(
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            bundle=forged,
        )
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def test_forged_bundle_content_hash_rejected_on_write(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, _, campaign_id = bundle_env
    valid = _valid_bundle()
    forged = valid.model_copy(update={"content_hash": "2" * 64})
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.put_external_observation_input_bundle(
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            bundle=forged,
        )
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def test_forged_provenance_detected_on_get(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    _accept_base(store, world_id, campaign_id)
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )

    # Altered world hash, self-consistently rehashed.
    tampered = stored.model_copy(update={"world_content_hash": "3" * 64})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )

    # Altered seed hash, self-consistently rehashed.
    tampered = stored.model_copy(update={"seed_content_hash": "4" * 64})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )

    # Altered declaration content hash, self-consistently rehashed.
    forged_entry = stored.entries[0].model_copy(
        update={"runtime_observation_declaration_content_hash": "5" * 64}
    )
    forged_entry = forged_entry.model_copy(
        update={"content_hash": external_observation_input_entry_content_hash(forged_entry)}
    )
    tampered = stored.model_copy(update={"entries": (forged_entry, *stored.entries[1:])})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )

    # Altered channel, self-consistently rehashed.
    forged_entry = stored.entries[0].model_copy(update={"external_channel_id": "channel-forged"})
    forged_entry = forged_entry.model_copy(
        update={"content_hash": external_observation_input_entry_content_hash(forged_entry)}
    )
    tampered = stored.model_copy(update={"entries": (forged_entry, *stored.entries[1:])})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )

    # Altered value kind, self-consistently rehashed.
    forged_entry = stored.entries[0].model_copy(update={"value_kind": "number"})
    forged_entry = forged_entry.model_copy(
        update={"content_hash": external_observation_input_entry_content_hash(forged_entry)}
    )
    tampered = stored.model_copy(update={"entries": (forged_entry, *stored.entries[1:])})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )

    # Altered unit, self-consistently rehashed.
    forged_entry = stored.entries[1].model_copy(update={"unit": "km/h"})
    forged_entry = forged_entry.model_copy(
        update={"content_hash": external_observation_input_entry_content_hash(forged_entry)}
    )
    tampered = stored.model_copy(update={"entries": (*stored.entries[:1], forged_entry)})
    tampered = tampered.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(tampered)}
    )
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = tampered
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )
    _assert_no_activity(store)


def test_corrupt_private_store_bundle_detected_on_get(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    _accept_base(store, world_id, campaign_id)
    stored = store.get_external_observation_input_bundle(
        tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
    )
    corrupted = stored.model_copy(update={"scenario_seed_id": "forged-seed"})
    store._external_observation_input_bundles[(TENANT, campaign_id, _SEED_ID)] = corrupted
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )
    # Corruption is rejected, never repaired: get still fails afterwards.
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )
    _assert_no_activity(store)


def test_validator_bypassed_bundle_rejected(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    valid = _valid_bundle()
    entries = valid.entries
    forged_entry = ExternalObservationInputEntry.model_construct(
        identifier="forged",
        runtime_observation_declaration_id=entries[0].runtime_observation_declaration_id,
        runtime_observation_declaration_content_hash=entries[
            0
        ].runtime_observation_declaration_content_hash,
        observation_id=entries[0].observation_id,
        external_channel_id=entries[0].external_channel_id,
        source_step_index=entries[0].source_step_index,
        value_kind=entries[0].value_kind,
        unit=entries[0].unit,
        value="not-a-number",  # validator bypassed
        content_hash=entries[0].content_hash,
    )
    forged = ExternalObservationInputBundle.model_construct(
        identifier=valid.identifier,
        tenant_id=TENANT,
        schema_version=SCHEMA_VERSION,
        campaign_id=campaign_id,
        scenario_id="scenario-1",
        world_version_id=world_id,
        world_content_hash=valid.world_content_hash,
        scenario_seed_id=_SEED_ID,
        seed_content_hash=valid.seed_content_hash,
        runtime_version="4.0.0",
        entries=(forged_entry,) + tuple(valid.entries),
        content_hash=valid.content_hash,
        accepted_at=_ACCEPTED_AT,
    )
    with pytest.raises(ExternalObservationInputIntegrityError):
        store.put_external_observation_input_bundle(
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            bundle=forged,
        )
    assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)


def test_unknown_and_foreign_bundles_do_not_leak(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    _accept_base(store, world_id, campaign_id)
    with pytest.raises(ExternalObservationInputNotFoundError):
        store.get_external_observation_input_bundle(
            tenant_id=OTHER_TENANT, campaign_id=campaign_id, scenario_seed_id=_SEED_ID
        )
    with pytest.raises(ExternalObservationInputNotFoundError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id="campaign-other", scenario_seed_id=_SEED_ID
        )
    with pytest.raises(ExternalObservationInputNotFoundError):
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=campaign_id, scenario_seed_id="seed-other"
        )
    _assert_no_activity(store)


def test_no_update_delete_list_repair_surface(
    bundle_env: tuple[InMemoryScenarioStore, str, str],
) -> None:
    store, world_id, campaign_id = bundle_env
    _accept_base(store, world_id, campaign_id)
    for name in (
        "update_external_observation_input_bundle",
        "delete_external_observation_input_bundle",
        "list_external_observation_input_bundles",
        "replace_external_observation_input_bundle",
        "repair_external_observation_input_bundle",
    ):
        assert not hasattr(store, name)
    assert type(store).__dict__.get("put_external_observation_input_bundle") is not None
    assert type(store).__dict__.get("get_external_observation_input_bundle") is not None


def test_raw_exceptions_never_leak(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    typed = (
        ExternalObservationInputValidationError,
        ExternalObservationInputAlreadyExistsError,
        ExternalObservationInputNotFoundError,
        ExternalObservationInputIntegrityError,
    )
    store.update_campaign_status(
        TENANT,
        campaign_id,
        CampaignStatus(
            identifier="status-2",
            tenant_id=TENANT,
            campaign_id=campaign_id,
            state=CampaignState.DRAFT,
            changed_at=NOW,
        ),
    )
    bad_drafts = (
        _draft(_value("obs-a", 0, 7)),
        _draft(_value("obs-a", 0, 7.0)),
        _draft(_value("obs-a", -1, 7)),
    )
    for draft in bad_drafts:
        with pytest.raises(typed) as excinfo:
            accept_external_observation_input_bundle(
                store,
                tenant_id=TENANT,
                campaign_id=campaign_id,
                scenario_seed_id=_SEED_ID,
                draft=draft,
            )
        assert not isinstance(
            excinfo.value,
            (ValueError, TypeError, AttributeError, KeyError, AssertionError),
        )
    _assert_no_activity(store)


def test_every_failure_is_atomic(bundle_env: tuple[InMemoryScenarioStore, str, str]) -> None:
    store, world_id, campaign_id = bundle_env
    failures: tuple[Callable[[], object], ...] = (
        lambda: accept_external_observation_input_bundle(  # wrong value kind
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(_value("obs-a", 0, 7.0)),
        ),
        lambda: accept_external_observation_input_bundle(  # unscheduled step
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(_value("obs-c", 1, 5)),
        ),
        lambda: accept_external_observation_input_bundle(  # reordered
            store,
            tenant_id=TENANT,
            campaign_id=campaign_id,
            scenario_seed_id=_SEED_ID,
            draft=_draft(
                _value("obs-a", 2, 5),
                _value("obs-a", 0, 7),
            ),
        ),
        lambda: accept_external_observation_input_bundle(  # unknown campaign
            store,
            tenant_id=TENANT,
            campaign_id="campaign-missing",
            scenario_seed_id=_SEED_ID,
            draft=_draft(_value("obs-a", 0, 7)),
        ),
    )
    for failure in failures:
        with pytest.raises(ExternalObservationInputValidationError):
            failure()
        assert store._external_observation_input_bundles == {}
    _assert_no_activity(store)
