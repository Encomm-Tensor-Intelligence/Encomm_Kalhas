"""API and end-to-end tests for the Phase 9 operational activity feed."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.run_planner import run_input_hash
from kalhas.application.world_compiler import content_hash
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.domain_pack import DomainCapabilityDeclaration, DomainPackBinding
from kalhas.contracts.v1.scenario import ScenarioSeed, ScenarioSpec
from kalhas.contracts.v1.strategy import StrategyRequest

NOW = "2026-01-01T12:00:00Z"
BOUND_AT = "2026-01-03T12:00:00Z"
DECLARED_AT = "2026-01-04T12:00:00Z"
STARTED_AT = "2026-01-05T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}


def scenario_payload(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": "scenario-1",
        "tenant_id": tenant_id,
        "schema_version": "1.0.0",
        "name": "Reference scenario",
        "created_at": NOW,
        "objectives": [
            {
                "identifier": "obj-1",
                "description": "Maximize the primary metric",
                "direction": "maximize",
                "target": 100.0,
                "weight": 1.0,
            }
        ],
        "constraints": [{"identifier": "c-1", "description": "Stay within declared bounds"}],
        "time_horizon": {"start": NOW, "end": "2026-01-02T12:00:00Z", "resolution": "step"},
        "metrics": [{"identifier": "m-1", "name": "Primary metric", "unit": "units"}],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {},
    }


def seed_payload(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "identifier": "seed-1",
        "tenant_id": tenant_id,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": "v1",
        "metadata": {},
    }


def campaign_payload(
    campaign_id: str, world_version_id: str, tenant_id: str = TENANT
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "campaign_name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": {
            "identifier": "sr-1",
            "tenant_id": tenant_id,
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "required_observations": [
                {"metric_id": "m-1", "description": "observe m-1", "required": True}
            ],
            "requested_at": NOW,
            "metadata": {},
        },
        "seed_ensemble": [seed_payload(tenant_id)],
        "runtime_version": "1.0.0",
        "created_at": NOW,
    }


def manifest_payload(identifier: str = "manifest-1", pack_id: str = "pack-1") -> dict[str, Any]:
    return {
        "identifier": identifier,
        "pack_id": pack_id,
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-a", "in-b"],
                "output_ids": ["out-1"],
                "metadata": {},
            }
        ],
        "schema_metadata": {"declarative": True},
        "created_at": NOW,
        "metadata": {},
    }


def full_flow(client: TestClient, tenant_id: str = TENANT) -> dict[str, Any]:
    """Run every activity-recording operation; return key artifacts."""
    headers = {"X-Tenant-ID": tenant_id}
    assert (
        client.post("/v1/scenarios", headers=headers, json=scenario_payload(tenant_id)).status_code
        == 201
    )
    manifest = client.post("/v1/domain-packs", headers=headers, json=manifest_payload()).json()
    assert (
        client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers=headers,
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        ).status_code
        == 201
    )
    declaration = client.post(
        "/v1/scenarios/scenario-1/domain-capability-declarations",
        headers=headers,
        json={
            "manifest_id": "manifest-1",
            "capability_id": "cap-1",
            "input_values": {"in-a": "value-a", "in-b": 42},
            "declared_at": DECLARED_AT,
        },
    ).json()
    compiled = client.post("/v1/scenarios/scenario-1/compile", headers=headers).json()
    world_id = compiled["version"]["identifier"]
    assert (
        client.post(
            "/v1/campaigns",
            headers=headers,
            json=campaign_payload("campaign-1", world_id, tenant_id),
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/campaigns/campaign-1/start", headers=headers, json={"changed_at": STARTED_AT}
        ).status_code
        == 200
    )
    executed = client.post("/v1/campaigns/campaign-1/execute", headers=headers)
    assert executed.status_code == 200
    plans = client.get("/v1/campaigns/campaign-1/runs", headers=headers).json()["run_plans"]
    run_id = f"run-{plans[0]['identifier']}"
    assert client.post(f"/v1/runs/{run_id}/verify-inputs", headers=headers).status_code == 200
    assert client.get(f"/v1/runs/{run_id}/replay", headers=headers).status_code == 200
    return {
        "manifest": manifest,
        "declaration": declaration,
        "compiled": compiled,
        "plans": plans,
        "run_id": run_id,
    }


def activity(client: TestClient, tenant_id: str = TENANT, **params: Any) -> dict[str, Any]:
    response = client.get(
        "/v1/operational-activity", headers={"X-Tenant-ID": tenant_id}, params=params
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


EXPECTED_KIND_ORDER = [
    "scenario_registered",
    "domain_pack_registered",
    "domain_pack_bound",
    "capability_inputs_declared",
    "world_compiled",
    "campaign_prepared",
    "campaign_started",
    "campaign_executed",
    "run_inputs_verified",
    "run_replayed",
]


class TestActivityFeedApi:
    def test_empty_feed_returns_typed_empty_envelope(self, client: TestClient) -> None:
        feed = activity(client)
        assert feed == {"events": [], "next_after_sequence": -1, "latest_sequence": -1}

    def test_each_successful_operation_appends_exactly_one_event(self, client: TestClient) -> None:
        full_flow(client)
        feed = activity(client)
        assert [event["kind"] for event in feed["events"]] == EXPECTED_KIND_ORDER
        assert [event["sequence"] for event in feed["events"]] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert [event["identifier"] for event in feed["events"]] == [
            f"activity-{index}" for index in range(10)
        ]
        assert feed["latest_sequence"] == 9
        assert feed["next_after_sequence"] == 9

    def test_events_carry_structural_references(self, client: TestClient) -> None:
        full_flow(client)
        events = activity(client)["events"]
        by_kind = {event["kind"]: event for event in events}
        assert by_kind["scenario_registered"]["scenario_id"] == "scenario-1"
        world_event = by_kind["world_compiled"]
        assert world_event["scenario_id"] == "scenario-1"
        assert world_event["world_version_id"].startswith("world-")
        assert by_kind["domain_pack_bound"]["binding_id"].startswith("binding-")
        declared = by_kind["capability_inputs_declared"]
        assert declared["declaration_id"].startswith("declaration-")
        assert declared["manifest_id"] == "manifest-1"
        prepared = by_kind["campaign_prepared"]
        assert prepared["campaign_id"] == "campaign-1"
        assert prepared["world_version_id"].startswith("world-")
        assert by_kind["run_inputs_verified"]["run_id"].startswith("run-")
        assert by_kind["run_replayed"]["run_id"].startswith("run-")

    def test_pagination_is_deterministic_and_bounded(self, client: TestClient) -> None:
        full_flow(client)
        page_one = activity(client, limit=3)
        assert [e["sequence"] for e in page_one["events"]] == [0, 1, 2]
        assert page_one["next_after_sequence"] == 2
        assert page_one["latest_sequence"] == 9
        page_two = activity(client, after_sequence=page_one["next_after_sequence"], limit=3)
        assert [e["sequence"] for e in page_two["events"]] == [3, 4, 5]
        page_three = activity(client, after_sequence=page_two["next_after_sequence"], limit=3)
        assert [e["sequence"] for e in page_three["events"]] == [6, 7, 8]
        page_four = activity(client, after_sequence=page_three["next_after_sequence"], limit=3)
        assert [e["sequence"] for e in page_four["events"]] == [9]
        exhausted = activity(client, after_sequence=page_four["next_after_sequence"], limit=3)
        assert exhausted["events"] == []
        assert exhausted["next_after_sequence"] == 9

    def test_from_negative_one_returns_everything(self, client: TestClient) -> None:
        full_flow(client)
        feed = activity(client, after_sequence=-1)
        assert len(feed["events"]) == 10
        assert feed["events"][0]["sequence"] == 0

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": -1},
            {"limit": 101},
            {"after_sequence": -2},
            {"after_sequence": "abc"},
            {"limit": "many"},
        ],
    )
    def test_invalid_cursor_or_limit_returns_typed_422(
        self, client: TestClient, params: dict[str, Any]
    ) -> None:
        response = client.get("/v1/operational-activity", headers=HEADERS, params=params)
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/operational-activity").status_code == 422

    def test_feed_is_read_only(self, client: TestClient) -> None:
        full_flow(client)
        first = activity(client)
        second = activity(client)
        assert first == second
        # Reading the feed never appends events.
        assert first["latest_sequence"] == 9

    def test_tenants_are_isolated(self, client: TestClient) -> None:
        full_flow(client, tenant_id="tenant-a")
        # tenant-b has its own empty feed despite tenant-a's activity.
        assert activity(client, tenant_id="tenant-b") == {
            "events": [],
            "next_after_sequence": -1,
            "latest_sequence": -1,
        }
        # tenant-b's own operations start its sequence at zero.
        full_flow(client, tenant_id="tenant-b")
        feed_b = activity(client, tenant_id="tenant-b")
        assert [e["sequence"] for e in feed_b["events"]] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        # tenant-a still sees exactly its own ten events.
        assert len(activity(client, tenant_id="tenant-a")["events"]) == 10


class TestRejectedOperationsAppendNothing:
    def test_rejected_operations_do_not_append_activity(self, client: TestClient) -> None:
        headers = HEADERS
        assert (
            client.post("/v1/scenarios", headers=headers, json=scenario_payload()).status_code
            == 201
        )
        # Duplicate scenario (409).
        assert (
            client.post("/v1/scenarios", headers=headers, json=scenario_payload()).status_code
            == 409
        )
        # Unbound declaration (404).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-capability-declarations",
                headers=headers,
                json={
                    "manifest_id": "manifest-ghost",
                    "capability_id": "cap-1",
                    "input_values": {"in-a": "x", "in-b": 1},
                    "declared_at": DECLARED_AT,
                },
            ).status_code
            == 404
        )
        # Compile of a foreign tenant's scenario (404).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/compile", headers={"X-Tenant-ID": "tenant-other"}
            ).status_code
            == 404
        )
        # Start of a non-existent campaign (404).
        assert (
            client.post(
                "/v1/campaigns/campaign-ghost/start",
                headers=headers,
                json={"changed_at": STARTED_AT},
            ).status_code
            == 404
        )
        # Verify of an unknown run (404).
        assert client.post("/v1/runs/run-ghost/verify-inputs", headers=headers).status_code == 404
        # Replay of an unknown run (404).
        assert client.get("/v1/runs/run-ghost/replay", headers=headers).status_code == 404

        feed = activity(client)
        # Only the successful scenario registration was recorded.
        assert [event["kind"] for event in feed["events"]] == ["scenario_registered"]
        assert feed["latest_sequence"] == 0

    def test_failed_campaign_execution_appends_nothing(self, client: TestClient) -> None:
        # A campaign that is never started cannot execute (409 invalid state).
        headers = HEADERS
        assert (
            client.post("/v1/scenarios", headers=headers, json=scenario_payload()).status_code
            == 201
        )
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=headers).json()
        assert (
            client.post(
                "/v1/campaigns",
                headers=headers,
                json=campaign_payload("campaign-1", compiled["version"]["identifier"]),
            ).status_code
            == 201
        )
        assert client.post("/v1/campaigns/campaign-1/execute", headers=headers).status_code == 409
        feed = activity(client)
        assert [event["kind"] for event in feed["events"]] == [
            "scenario_registered",
            "world_compiled",
            "campaign_prepared",
        ]


class TestActivityPayloadSafety:
    def test_payloads_contain_no_sensitive_or_executable_content(self, client: TestClient) -> None:
        full_flow(client)
        feed = activity(client)
        forbidden = {"input_values", "policy", "rules", "outcome", "evidence", "recommendation"}
        serialized = "".join(json.dumps(event["payload"]) for event in feed["events"])
        for event in feed["events"]:
            assert isinstance(event["payload"], dict)
            assert not forbidden.intersection(event["payload"])
        # Raw declared input values are never exposed anywhere in the feed.
        assert "value-a" not in serialized
        assert "in-b" not in serialized


class TestHashesUnaffectedByActivity:
    def test_world_and_run_plan_hashes_are_unchanged_by_activity_recording(
        self, client: TestClient
    ) -> None:
        """Activity recording is observability only: the compiled world
        content hash and the RunPlan input hash are pure functions of their
        recorded artifacts, recomputed here from the same stored records
        after a fully recorded flow - equality proves the feed never
        influences them."""
        artifacts = full_flow(client)

        scenario = ScenarioSpec.model_validate(scenario_payload())
        binding = DomainPackBinding.model_validate(
            client.get("/v1/scenarios/scenario-1/domain-pack-bindings", headers=HEADERS).json()[
                "bindings"
            ][0]
        )
        declaration = DomainCapabilityDeclaration.model_validate(artifacts["declaration"])
        expected_world_hash = content_hash(
            scenario, bindings=(binding,), declarations=(declaration,)
        )
        assert artifacts["compiled"]["version"]["content_hash"] == expected_world_hash

        plan = artifacts["plans"][0]
        # The recorded strategy candidates are exactly the deterministic
        # MockLegionAdapter output for the same request (the mock is the
        # sole strategy source for the standalone flow).
        request = StrategyRequest.model_validate(
            campaign_payload("campaign-1", "unused")["strategy_request"]
        )
        strategy = next(
            candidate
            for candidate in MockLegionAdapter().request_strategies(request)
            if candidate.identifier == plan["strategy_candidate_id"]
        )
        seed = ScenarioSeed.model_validate(seed_payload())
        expected_input_hash = run_input_hash(
            world_content_hash=artifacts["compiled"]["version"]["content_hash"],
            strategy=strategy,
            seed=seed,
            runtime_version=plan["runtime_version"],
        )
        assert plan["input_hash"] == expected_input_hash
        # Replay of the completed run remains green on the recorded world.
        replayed = client.get(f"/v1/runs/{artifacts['run_id']}/replay", headers=HEADERS)
        assert replayed.status_code == 200
        assert replayed.json()["replay_classification"] == "exact"
