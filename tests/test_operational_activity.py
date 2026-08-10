"""Tests for the operational activity contract, store, and record helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.campaign_service import PreparedCampaign, prepare_campaign, start_campaign
from kalhas.application.domain_capability_declaration_service import declare_capability_inputs
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.operational_activity import (
    record_campaign_executed,
    record_campaign_prepared,
    record_campaign_started,
    record_capability_inputs_declared,
    record_domain_pack_bound,
    record_domain_pack_registered,
    record_run_inputs_verified,
    record_run_replayed,
    record_scenario_registered,
    record_world_compiled,
)
from kalhas.application.replay_service import replay_run
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_compiler import CompiledWorld, compile_world
from kalhas.contracts.v1.activity import (
    OperationalActivityEvent,
    OperationalActivityKind,
)
from kalhas.contracts.v1.campaign import CampaignStatus
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunStatus
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.scenario import ScenarioSeed, ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.strategy import ObservationRequirement, StrategyRequest
from pydantic import ValidationError

from tests.test_application_services import build_scenario

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)


class Draft(TypedDict):
    tenant_id: str
    identifier: str
    pack_id: str
    name: str
    pack_version: str
    description: str | None
    supported_api_versions: tuple[str, ...]
    capabilities: tuple[DomainPackCapability, ...]
    schema_metadata: dict[str, JsonValue]
    created_at: datetime
    metadata: dict[str, JsonValue]


CAPABILITIES = (
    DomainPackCapability(
        identifier="cap-1",
        description="Declared capability",
        input_ids=("in-a", "in-b"),
        output_ids=("out-1",),
    ),
)


def register(store: InMemoryScenarioStore, *, tenant_id: str = "tenant-1") -> DomainPackManifest:
    params: Draft = {
        "tenant_id": tenant_id,
        "identifier": "manifest-1",
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ("1",),
        "capabilities": CAPABILITIES,
        "schema_metadata": {"declarative": True},
        "created_at": NOW,
        "metadata": {},
    }
    return register_manifest(store, **params)


def seed(tenant_id: str = "tenant-1") -> tuple[ScenarioSeed, ...]:
    return (
        ScenarioSeed(
            identifier="seed-1",
            tenant_id=tenant_id,
            algorithm="deterministic",
            seed_value="v1",
        ),
    )


def strategy_request(tenant_id: str = "tenant-1") -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        required_observations=[
            ObservationRequirement(metric_id="m-1", description="observe m-1", required=True)
        ],
        requested_at=NOW,
    )


class FlowArtifacts(TypedDict):
    scenario: ScenarioSpec
    manifest: DomainPackManifest
    binding: DomainPackBinding
    declaration: DomainCapabilityDeclaration
    compiled: CompiledWorld
    prepared: PreparedCampaign
    started: CampaignStatus
    executed_statuses: tuple[RunStatus, ...]
    executed_status: CampaignStatus
    verified: RunInputIntegrityManifest
    replayed: ReplayManifest


class TestActivityContract:
    def payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "identifier": "activity-0",
            "tenant_id": "tenant-1",
            "schema_version": "1.0.0",
            "sequence": 0,
            "kind": "scenario_registered",
            "occurred_at": NOW,
            "scenario_id": "scenario-1",
            "world_version_id": None,
            "campaign_id": None,
            "run_id": None,
            "manifest_id": None,
            "binding_id": None,
            "declaration_id": None,
            "payload": {"schema_version": "1.0.0"},
        }
        payload.update(overrides)
        return payload

    def test_accepts_valid_payload(self) -> None:
        event = OperationalActivityEvent.model_validate(self.payload())
        assert event.identifier == "activity-0"
        assert event.sequence == 0
        assert event.kind is OperationalActivityKind.SCENARIO_REGISTERED
        assert event.occurred_at == NOW

    def test_rejects_unknown_fields(self) -> None:
        payload = self.payload()
        payload["unexpected_field"] = 1
        with pytest.raises(ValidationError):
            OperationalActivityEvent.model_validate(payload)

    def test_rejects_negative_sequence(self) -> None:
        with pytest.raises(ValidationError):
            OperationalActivityEvent.model_validate(self.payload(sequence=-1))

    def test_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValidationError):
            OperationalActivityEvent.model_validate(self.payload(kind="simulated_outcome"))

    def test_is_frozen_by_contract(self) -> None:
        event = OperationalActivityEvent.model_validate(self.payload())
        with pytest.raises(ValidationError):
            event.payload = {"tampered": True}

    def test_json_round_trip_preserves_all_fields(self) -> None:
        event = OperationalActivityEvent.model_validate(self.payload())
        reloaded = OperationalActivityEvent.model_validate_json(event.model_dump_json())
        assert reloaded == event
        assert reloaded.payload == {"schema_version": "1.0.0"}

    def test_kind_enum_has_only_generic_structural_kinds(self) -> None:
        assert {kind.value for kind in OperationalActivityKind} == {
            "scenario_registered",
            "world_compiled",
            "domain_pack_registered",
            "domain_pack_bound",
            "capability_inputs_declared",
            "domain_state_model_declared",
            "domain_state_transition_declared",
            "campaign_prepared",
            "campaign_started",
            "campaign_executed",
            "run_inputs_verified",
            "run_replayed",
        }


class TestActivityStore:
    def test_sequences_are_tenant_local_strictly_increasing_and_immutable(self) -> None:
        store = InMemoryScenarioStore()
        first = store.append_operational_activity(
            tenant_id="tenant-1",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        second = store.append_operational_activity(
            tenant_id="tenant-1",
            kind=OperationalActivityKind.WORLD_COMPILED,
            occurred_at=NOW,
            payload={},
        )
        assert (first.sequence, first.identifier) == (0, "activity-0")
        assert (second.sequence, second.identifier) == (1, "activity-1")
        # Immutable: the frozen contract rejects reassignment, and the
        # store exposes no update/delete/clear surface.
        with pytest.raises(ValidationError):
            first.sequence = 99
        for method in (
            "update_operational_activity",
            "delete_operational_activity",
            "replace_operational_activity",
            "clear_operational_activity",
        ):
            assert not hasattr(store, method)

    def test_sequences_restart_per_tenant(self) -> None:
        store = InMemoryScenarioStore()
        store.append_operational_activity(
            tenant_id="tenant-a",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        store.append_operational_activity(
            tenant_id="tenant-a",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        store.append_operational_activity(
            tenant_id="tenant-b",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        assert [e.sequence for e in store.list_operational_activity("tenant-a")] == [0, 1]
        assert [e.sequence for e in store.list_operational_activity("tenant-b")] == [0]

    def test_retrieval_is_ascending_and_strictly_after_cursor(self) -> None:
        store = InMemoryScenarioStore()
        for index in range(5):
            store.append_operational_activity(
                tenant_id="tenant-1",
                kind=OperationalActivityKind.SCENARIO_REGISTERED,
                occurred_at=NOW,
                payload={"index": index},
            )
        all_events = store.list_operational_activity("tenant-1")
        assert [e.sequence for e in all_events] == [0, 1, 2, 3, 4]
        after_two = store.list_operational_activity("tenant-1", after_sequence=2)
        assert [e.sequence for e in after_two] == [3, 4]
        after_four = store.list_operational_activity("tenant-1", after_sequence=4)
        assert after_four == ()
        from_negative_one = store.list_operational_activity("tenant-1", after_sequence=-1)
        assert [e.sequence for e in from_negative_one] == [0, 1, 2, 3, 4]

    def test_retrieval_is_bounded_by_limit(self) -> None:
        store = InMemoryScenarioStore()
        for index in range(7):
            store.append_operational_activity(
                tenant_id="tenant-1",
                kind=OperationalActivityKind.SCENARIO_REGISTERED,
                occurred_at=NOW,
                payload={"index": index},
            )
        page = store.list_operational_activity("tenant-1", limit=3)
        assert [e.sequence for e in page] == [0, 1, 2]
        next_page = store.list_operational_activity("tenant-1", after_sequence=2, limit=3)
        assert [e.sequence for e in next_page] == [3, 4, 5]
        last_page = store.list_operational_activity("tenant-1", after_sequence=5, limit=3)
        assert [e.sequence for e in last_page] == [6]

    def test_latest_sequence_sentinel(self) -> None:
        store = InMemoryScenarioStore()
        assert store.latest_activity_sequence("tenant-1") == -1
        store.append_operational_activity(
            tenant_id="tenant-1",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        assert store.latest_activity_sequence("tenant-1") == 0
        assert store.latest_activity_sequence("tenant-other") == -1

    def test_tenants_cannot_see_each_other(self) -> None:
        store = InMemoryScenarioStore()
        store.append_operational_activity(
            tenant_id="tenant-a",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        assert store.list_operational_activity("tenant-b") == ()
        assert store.latest_activity_sequence("tenant-b") == -1

    def test_activity_does_not_touch_other_collections(self) -> None:
        store = InMemoryScenarioStore()
        store.append_operational_activity(
            tenant_id="tenant-1",
            kind=OperationalActivityKind.SCENARIO_REGISTERED,
            occurred_at=NOW,
            payload={},
        )
        from kalhas.application.domain_errors import (
            CampaignNotFoundError,
            DomainCapabilityDeclarationNotFoundError,
            DomainPackBindingNotFoundError,
            DomainPackNotFoundError,
            RunNotFoundError,
            WorldNotFoundError,
        )

        with pytest.raises(WorldNotFoundError):
            store.get_world("tenant-1", "world-any")
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign("tenant-1", "campaign-any")
        with pytest.raises(RunNotFoundError):
            store.get_run_status("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_run_events("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest("tenant-1", "run-any")
        with pytest.raises(RunNotFoundError):
            store.get_input_integrity_manifest("tenant-1", "run-any")
        with pytest.raises(DomainPackNotFoundError):
            store.get_domain_pack_manifest("tenant-1", "manifest-any")
        with pytest.raises(DomainPackBindingNotFoundError):
            store.get_domain_pack_binding("tenant-1", "scenario-any", "manifest-any")
        with pytest.raises(DomainCapabilityDeclarationNotFoundError):
            store.get_domain_capability_declaration(
                "tenant-1", "scenario-any", "manifest-any", "cap-any"
            )


class TestActivityRecordHelpers:
    """Each helper records exactly one event with the correct kind, refs,
    deterministic occurred_at, and a safe structural payload."""

    def _flow_artifacts(self, store: InMemoryScenarioStore) -> FlowArtifacts:
        scenario = build_scenario()
        store.put_scenario(scenario)
        manifest = register(store)
        binding = bind_manifest(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            bound_at=BOUND_AT,
        )
        declaration = declare_capability_inputs(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            capability_id="cap-1",
            input_values={"in-a": "value-a", "in-b": 42},
            declared_at=DECLARED_AT,
        )
        compiled = compile_world(scenario, bindings=(binding,), declarations=(declaration,))
        store.put_world(compiled.version, compiled.manifest)
        prepared = prepare_campaign(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=strategy_request(),
            campaign_id="campaign-1",
            campaign_name="Reference campaign",
            seed_ensemble=seed(),
            created_at=NOW,
        )
        started = start_campaign(
            store=store, tenant_id="tenant-1", campaign_id="campaign-1", changed_at=STARTED_AT
        )
        executed_statuses = execute_campaign(
            store=store, tenant_id="tenant-1", campaign_id="campaign-1"
        )
        executed_status = store.get_campaign_status("tenant-1", "campaign-1")
        run_id = f"run-{prepared.run_plans[0].identifier}"
        verified = verify_run_inputs(store=store, tenant_id="tenant-1", run_id=run_id)
        replayed = replay_run(store=store, tenant_id="tenant-1", run_id=run_id)
        return {
            "scenario": scenario,
            "manifest": manifest,
            "binding": binding,
            "declaration": declaration,
            "compiled": compiled,
            "prepared": prepared,
            "started": started,
            "executed_statuses": executed_statuses,
            "executed_status": executed_status,
            "verified": verified.manifest,
            "replayed": replayed,
        }

    def test_each_kind_records_one_event_with_correct_facts(self) -> None:
        store = InMemoryScenarioStore()
        artifacts = self._flow_artifacts(store)

        record_scenario_registered(store, tenant_id="tenant-1", scenario=artifacts["scenario"])
        record_world_compiled(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            world=artifacts["compiled"].version,
        )
        record_domain_pack_registered(store, tenant_id="tenant-1", manifest=artifacts["manifest"])
        record_domain_pack_bound(store, tenant_id="tenant-1", binding=artifacts["binding"])
        record_capability_inputs_declared(
            store, tenant_id="tenant-1", declaration=artifacts["declaration"]
        )
        record_campaign_prepared(
            store,
            tenant_id="tenant-1",
            campaign=artifacts["prepared"].campaign,
            status=artifacts["prepared"].status,
            run_plan_count=len(artifacts["prepared"].run_plans),
        )
        record_campaign_started(store, tenant_id="tenant-1", status=artifacts["started"])
        record_campaign_executed(
            store,
            tenant_id="tenant-1",
            campaign_id="campaign-1",
            status=artifacts["executed_status"],
            run_statuses=artifacts["executed_statuses"],
        )
        record_run_inputs_verified(store, tenant_id="tenant-1", manifest=artifacts["verified"])
        record_run_replayed(store, tenant_id="tenant-1", manifest=artifacts["replayed"])

        events = store.list_operational_activity("tenant-1")
        assert [event.kind for event in events] == [
            OperationalActivityKind.SCENARIO_REGISTERED,
            OperationalActivityKind.WORLD_COMPILED,
            OperationalActivityKind.DOMAIN_PACK_REGISTERED,
            OperationalActivityKind.DOMAIN_PACK_BOUND,
            OperationalActivityKind.CAPABILITY_INPUTS_DECLARED,
            OperationalActivityKind.CAMPAIGN_PREPARED,
            OperationalActivityKind.CAMPAIGN_STARTED,
            OperationalActivityKind.CAMPAIGN_EXECUTED,
            OperationalActivityKind.RUN_INPUTS_VERIFIED,
            OperationalActivityKind.RUN_REPLAYED,
        ]
        assert [event.sequence for event in events] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert store.latest_activity_sequence("tenant-1") == 9

    def test_occurred_at_is_derived_from_source_artifacts(self) -> None:
        store = InMemoryScenarioStore()
        artifacts = self._flow_artifacts(store)
        record_scenario_registered(store, tenant_id="tenant-1", scenario=artifacts["scenario"])
        record_world_compiled(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            world=artifacts["compiled"].version,
        )
        record_domain_pack_bound(store, tenant_id="tenant-1", binding=artifacts["binding"])
        record_capability_inputs_declared(
            store, tenant_id="tenant-1", declaration=artifacts["declaration"]
        )
        record_campaign_started(store, tenant_id="tenant-1", status=artifacts["started"])
        record_run_inputs_verified(store, tenant_id="tenant-1", manifest=artifacts["verified"])
        record_run_replayed(store, tenant_id="tenant-1", manifest=artifacts["replayed"])
        events = store.list_operational_activity("tenant-1")
        assert events[0].occurred_at == NOW  # scenario.created_at
        assert events[1].occurred_at == NOW  # world.created_at
        assert events[2].occurred_at == BOUND_AT  # binding.bound_at
        assert events[3].occurred_at == DECLARED_AT  # declaration.declared_at
        assert events[4].occurred_at == STARTED_AT  # campaign status changed_at
        assert events[5].occurred_at == NOW  # integrity manifest recorded_at (plan created_at)
        assert events[6].occurred_at == NOW  # replay manifest created_at (plan created_at)

    def test_payloads_are_safe_structural_facts_only(self) -> None:
        store = InMemoryScenarioStore()
        artifacts = self._flow_artifacts(store)
        record_scenario_registered(store, tenant_id="tenant-1", scenario=artifacts["scenario"])
        record_world_compiled(
            store,
            tenant_id="tenant-1",
            scenario_id="scenario-1",
            world=artifacts["compiled"].version,
        )
        record_domain_pack_registered(store, tenant_id="tenant-1", manifest=artifacts["manifest"])
        record_domain_pack_bound(store, tenant_id="tenant-1", binding=artifacts["binding"])
        record_capability_inputs_declared(
            store, tenant_id="tenant-1", declaration=artifacts["declaration"]
        )
        record_campaign_prepared(
            store,
            tenant_id="tenant-1",
            campaign=artifacts["prepared"].campaign,
            status=artifacts["prepared"].status,
            run_plan_count=len(artifacts["prepared"].run_plans),
        )
        record_campaign_started(store, tenant_id="tenant-1", status=artifacts["started"])
        record_campaign_executed(
            store,
            tenant_id="tenant-1",
            campaign_id="campaign-1",
            status=artifacts["executed_status"],
            run_statuses=artifacts["executed_statuses"],
        )
        record_run_inputs_verified(store, tenant_id="tenant-1", manifest=artifacts["verified"])
        record_run_replayed(store, tenant_id="tenant-1", manifest=artifacts["replayed"])

        forbidden = {"input_values", "policy", "rules", "outcome", "evidence", "recommendation"}
        serialized = store.list_operational_activity("tenant-1")
        for event in serialized:
            assert not forbidden.intersection(event.payload)
        # The raw declared input values never appear anywhere in the feed.
        assert "value-a" not in "".join(event.model_dump_json() for event in serialized)
        # Structural facts are present where applicable.
        world_event = serialized[1]
        assert world_event.payload["compiler_version"] == "1.0.0"
        assert world_event.payload["content_hash"] == artifacts["compiled"].version.content_hash
        prepared_event = serialized[5]
        assert prepared_event.payload["run_plan_count"] == 5
        assert prepared_event.payload["strategy_candidate_count"] == 5
        executed_event = serialized[7]
        assert executed_event.payload["completed_run_count"] == 5
