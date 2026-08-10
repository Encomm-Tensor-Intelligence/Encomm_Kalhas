"""Phase 14 tests: immutable store snapshot isolation.

Every store write stores a deep defensive copy of the supplied contract
and every get/list returns a fresh deep copy, so callers can never alter
internal stored state by mutating the original object after ``put_*`` or
an object returned from ``get_*``/``list_*`` - including nested dict and
list values, which Pydantic frozen contracts do not protect. Tuple
collections are deep-copied item by item. Lifecycle replacement still
happens only through the explicit status-update methods. Tenant
isolation and deterministic ordering are unchanged.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Callable
from typing import Any

import pytest
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    RunNotFoundError,
    ScenarioNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.replay_service import replay_run
from kalhas.application.run_planner import run_identifier
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.activity import OperationalActivityKind
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from pydantic import BaseModel, ValidationError

from tests.phase4_helpers import (
    NOW,
    TENANT,
    build_scenario,
    execute,
    prepare,
    start,
)

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
OTHER_TENANT = "tenant-other"

Getter = Callable[[InMemoryScenarioStore], Any]


def _mutate_nested(value: Any, seen: set[int] | None = None) -> bool:
    """Mutate the first mutable nested container found (test-only).

    Walks Pydantic model fields, dicts, lists, and tuples at any depth
    (a seen-id guard makes the walk robust against reference cycles);
    mutates the first dict (new key) or list (append) found. Returns
    True when something was mutated, False when the object is fully
    immutable (no nested dict/list exists anywhere).
    """
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    if isinstance(value, dict):
        value["__tampered__"] = True
        return True
    if isinstance(value, list):
        value.append("__tampered__")
        return True
    if isinstance(value, tuple):
        return any(_mutate_nested(item, seen) for item in value)
    if isinstance(value, BaseModel):
        for item in vars(value).values():
            if _mutate_nested(item, seen):
                return True
    return False


def _full_store() -> tuple[InMemoryScenarioStore, dict[str, Any], list[str]]:
    """A store holding one representative object of every contract family.

    Returns (store, samples, labels): ``samples[label]`` is the pristine
    original object(s) that were inserted; ``labels`` orders the families
    deterministically for parametrized-style iteration.
    """
    store = InMemoryScenarioStore()
    samples: dict[str, Any] = {}

    scenario = build_scenario()
    store.put_scenario(scenario)
    samples["scenario"] = scenario

    compiled = compile_world(scenario)
    store.put_world(compiled.version, compiled.manifest)
    samples["world"] = (compiled.version, compiled.manifest)

    prepared = prepare(store, compiled.version.identifier)
    samples["campaign"] = (prepared.campaign, prepared.status)
    samples["run_plans"] = prepared.run_plans
    samples["strategy_candidates"] = store.get_strategy_candidates(TENANT, "campaign-1")
    run_id = run_identifier(prepared.run_plans[0])

    start(store)
    execute(store)
    samples["run_statuses"] = tuple(
        store.get_run_status(TENANT, run_identifier(plan)) for plan in prepared.run_plans
    )
    samples["run_events"] = store.get_run_events(TENANT, run_id)
    samples["replay_manifest"] = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
    verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)
    samples["input_integrity_manifest"] = store.get_input_integrity_manifest(TENANT, run_id)

    pack = DomainPackManifest(
        identifier="manifest-1",
        tenant_id=TENANT,
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.2.3",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        content_hash=HASH_64,
        created_at=NOW,
        metadata={"zone": "registry"},
    )
    store.put_domain_pack_manifest(pack)
    samples["domain_pack_manifest"] = pack

    binding = DomainPackBinding(
        identifier="binding-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        capability_ids=("cap-1",),
        bound_at=NOW,
    )
    store.put_domain_pack_binding(binding)
    samples["domain_pack_binding"] = binding

    declaration = DomainCapabilityDeclaration(
        identifier="declaration-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        capability_id="cap-1",
        input_values={"in-1": {"nested": [1]}},
        content_hash=HASH_64,
        declared_at=NOW,
    )
    store.put_domain_capability_declaration(declaration)
    samples["domain_capability_declaration"] = declaration

    state_model = DomainStateModel(
        identifier="state-model-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_fields=(
            DomainStateFieldDefinition(
                identifier="status",
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="idle",
                metadata={"nested": {"m": 1}},
            ),
        ),
        content_hash=HASH_64,
        declared_at=NOW,
        metadata={"zone": "registry"},
    )
    store.put_domain_state_model(state_model)
    samples["domain_state_model"] = state_model

    transition = DomainStateTransition(
        identifier="transition-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_model_content_hash=HASH_64,
        transition_id="t-1",
        description="Declared state change",
        guard_values={"status": "idle"},
        target_values={"status": "active"},
        content_hash=HASH_64,
        declared_at=NOW,
        metadata={"zone": "registry"},
    )
    store.put_domain_state_transition(transition)
    samples["domain_state_transition"] = transition

    activity_event = store.append_operational_activity(
        tenant_id=TENANT,
        kind=OperationalActivityKind.SCENARIO_REGISTERED,
        occurred_at=NOW,
        payload={"metric": {"value": 1}},
    )
    samples["operational_activity"] = activity_event

    labels = [
        "scenario",
        "world",
        "campaign",
        "run_plans",
        "strategy_candidates",
        "run_statuses",
        "run_events",
        "replay_manifest",
        "input_integrity_manifest",
        "domain_pack_manifest",
        "domain_pack_binding",
        "domain_capability_declaration",
        "domain_state_model",
        "domain_state_transition",
        "operational_activity",
    ]
    return store, samples, labels


def _getter_for(store: InMemoryScenarioStore, label: str) -> Getter:
    """The canonical re-read for one family label."""
    world_id = compile_world(store.get_scenario(TENANT, "scenario-1")).version.identifier
    getters: dict[str, Getter] = {
        "scenario": lambda s: s.get_scenario(TENANT, "scenario-1"),
        "world": lambda s: s.get_world(TENANT, world_id),
        "campaign": lambda s: s.get_campaign_status(TENANT, "campaign-1"),
        "run_plans": lambda s: s.get_run_plans(TENANT, "campaign-1"),
        "strategy_candidates": lambda s: s.get_strategy_candidates(TENANT, "campaign-1"),
        "run_statuses": lambda s: tuple(
            s.get_run_status(TENANT, run_identifier(plan))
            for plan in s.get_run_plans(TENANT, "campaign-1")
        ),
        "run_events": lambda s: s.get_run_events(
            TENANT, run_identifier(s.get_run_plans(TENANT, "campaign-1")[0])
        ),
        "replay_manifest": lambda s: s.get_replay_manifest(
            TENANT, run_identifier(s.get_run_plans(TENANT, "campaign-1")[0])
        ),
        "input_integrity_manifest": lambda s: s.get_input_integrity_manifest(
            TENANT, run_identifier(s.get_run_plans(TENANT, "campaign-1")[0])
        ),
        "domain_pack_manifest": lambda s: s.get_domain_pack_manifest(TENANT, "manifest-1"),
        "domain_pack_binding": lambda s: s.get_domain_pack_binding(
            TENANT, "scenario-1", "manifest-1"
        ),
        "domain_capability_declaration": lambda s: s.get_domain_capability_declaration(
            TENANT, "scenario-1", "manifest-1", "cap-1"
        ),
        "domain_state_model": lambda s: s.get_domain_state_model(
            TENANT, "scenario-1", "manifest-1", "sm-1"
        ),
        "domain_state_transition": lambda s: s.get_domain_state_transition(
            TENANT, "scenario-1", "manifest-1", "sm-1", "t-1"
        ),
        "operational_activity": lambda s: s.list_operational_activity(TENANT)[0],
    }
    return getters[label]


class TestSnapshotIsolation:
    def test_returned_objects_are_never_the_stored_instances(self) -> None:
        store, samples, labels = _full_store()
        for label in labels:
            retrieved = _getter_for(store, label)(store)
            sample = samples[label]
            if isinstance(sample, tuple):
                # "world" and "campaign" samples are (contract, companion)
                # pairs whose getters return one member; tuple families
                # (plans, candidates, events, statuses) return the tuple.
                if isinstance(retrieved, tuple):
                    assert retrieved is not sample
                    assert retrieved[0] is not sample[0]
                else:
                    assert retrieved is not sample[0]
                    assert retrieved is not sample[1]
            else:
                assert retrieved is not sample

    def test_mutating_original_after_put_never_changes_storage(self) -> None:
        store, samples, labels = _full_store()
        for label in labels:
            sample = samples[label]
            # Pristine = storage content captured before the mutation.
            pristine = copy.deepcopy(_getter_for(store, label)(store))
            mutated = _mutate_nested(sample)
            retrieved = _getter_for(store, label)(store)
            assert retrieved == pristine, f"{label}: storage changed after original mutation"
            if mutated:
                assert retrieved != sample, f"{label}: retrieval aliases the mutated original"

    def test_mutating_retrieved_object_never_changes_storage(self) -> None:
        store, _, labels = _full_store()
        for label in labels:
            retrieved = _getter_for(store, label)(store)
            pristine = copy.deepcopy(retrieved)
            mutated = _mutate_nested(retrieved)
            again = _getter_for(store, label)(store)
            assert again == pristine, f"{label}: storage changed after mutating a retrieval"
            if mutated:
                assert again != retrieved, f"{label}: later retrieval aliases the mutated copy"

    def test_mutating_listed_items_never_changes_storage(self) -> None:
        store, _, _ = _full_store()
        # Binding snapshots carry no nested dict/list (immutable tuples of
        # scalars only), so the families below are the ones with mutable
        # nested content; each listed item is mutated and the storage is
        # re-listed to prove the mutation never lands.
        listed_pairs: list[tuple[list[Any], Getter]] = [
            (
                list(store.list_domain_pack_manifests(TENANT)),
                lambda s: list(s.list_domain_pack_manifests(TENANT)),
            ),
            (
                list(store.list_domain_capability_declarations(TENANT, "scenario-1")),
                lambda s: list(s.list_domain_capability_declarations(TENANT, "scenario-1")),
            ),
            (
                list(store.list_domain_state_models(TENANT, "scenario-1")),
                lambda s: list(s.list_domain_state_models(TENANT, "scenario-1")),
            ),
            (
                list(store.list_domain_state_transitions(TENANT, "scenario-1")),
                lambda s: list(s.list_domain_state_transitions(TENANT, "scenario-1")),
            ),
            (
                list(store.list_operational_activity(TENANT)),
                lambda s: list(s.list_operational_activity(TENANT)),
            ),
        ]
        for items, relist in listed_pairs:
            pristine = copy.deepcopy(items)
            assert _mutate_nested(items[0])
            assert relist(store) == pristine, "storage changed after mutating a listed item"

    def test_activity_events_are_isolated(self) -> None:
        store = InMemoryScenarioStore()
        payload: dict[str, JsonValue] = {"metric": {"value": 1}}
        returned = store.append_operational_activity(
            tenant_id=TENANT,
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload=payload,
        )
        # Mutating the original payload after append never changes storage.
        metric = payload["metric"]
        assert isinstance(metric, dict)
        metric["value"] = 999
        assert store.list_operational_activity(TENANT)[0].payload == {"metric": {"value": 1}}
        # Mutating the returned event never changes storage.
        metric = returned.payload["metric"]
        assert isinstance(metric, dict)
        metric["value"] = 777
        assert store.list_operational_activity(TENANT)[0].payload == {"metric": {"value": 1}}
        # Mutating a listed event never changes a later listing.
        metric = store.list_operational_activity(TENANT)[0].payload["metric"]
        assert isinstance(metric, dict)
        metric["value"] = 555
        assert store.list_operational_activity(TENANT)[0].payload == {"metric": {"value": 1}}

    def test_tenant_isolation_and_deterministic_ordering_unchanged(self) -> None:
        store, samples, _ = _full_store()
        other_scenario = build_scenario(tenant_id=OTHER_TENANT, identifier="scenario-other")
        store.put_scenario(other_scenario)
        other_pack = samples["domain_pack_manifest"].model_copy(
            update={"identifier": "manifest-other", "tenant_id": OTHER_TENANT}
        )
        store.put_domain_pack_manifest(other_pack)
        # Tenant isolation is structural: other tenants cannot see ours.
        with pytest.raises(ScenarioNotFoundError):
            store.get_scenario(OTHER_TENANT, "scenario-1")
        with pytest.raises(ScenarioNotFoundError):
            store.get_scenario(TENANT, "scenario-other")
        # Deterministic ordering unchanged.
        assert [m.identifier for m in store.list_domain_pack_manifests(TENANT)] == ["manifest-1"]
        assert [m.identifier for m in store.list_domain_pack_manifests(OTHER_TENANT)] == [
            "manifest-other"
        ]

    def test_status_replacement_only_through_explicit_update_methods(self) -> None:
        store, _, _ = _full_store()
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state is CampaignState.COMPLETE  # after fixture execution
        # A retrieved status is a deep copy: direct mutation either is
        # refused by the frozen contract or mutates only the copy - in
        # both cases storage is untouched.
        with contextlib.suppress(ValidationError):
            status.state = CampaignState.RUNNING  # frozen by contract: refused
        assert store.get_campaign_status(TENANT, "campaign-1").state is CampaignState.COMPLETE
        # The explicit update method is the only replacement path.
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.RUNNING})
        )
        assert store.get_campaign_status(TENANT, "campaign-1").state is CampaignState.RUNNING

    def test_missing_keys_still_raise_typed_not_found_errors(self) -> None:
        store, _, _ = _full_store()
        with pytest.raises(ScenarioNotFoundError):
            store.get_scenario(TENANT, "ghost")
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign(TENANT, "ghost")
        with pytest.raises(RunNotFoundError):
            store.get_run_status(TENANT, "ghost")


def test_run_statuses_and_events_are_isolated() -> None:
    store, _, _ = _full_store()
    run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
    status = store.get_run_status(TENANT, run_id)
    assert status.state is RunState.COMPLETE
    status_pristine = status.model_copy(deep=True)
    _mutate_nested(status)
    assert store.get_run_status(TENANT, run_id) == status_pristine

    events = store.get_run_events(TENANT, run_id)
    assert len(events) == 3
    events_pristine = [event.model_copy(deep=True) for event in events]
    assert _mutate_nested(events[0])  # run events carry a mutable payload dict
    assert list(store.get_run_events(TENANT, run_id)) == events_pristine
