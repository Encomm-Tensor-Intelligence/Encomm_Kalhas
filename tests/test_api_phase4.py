"""API tests for the Phase 4 execution, run, and replay endpoints."""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.execution import ReplayManifest, RunStatus
from kalhas.contracts.v1.simulation import RunEvent

NOW = "2026-01-01T12:00:00Z"
LATER = "2026-01-02T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}


def scenario_payload() -> dict[str, Any]:
    return {
        "identifier": "scenario-1",
        "tenant_id": TENANT,
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
        "time_horizon": {"start": NOW, "end": LATER, "resolution": "step"},
        "metrics": [{"identifier": "m-1", "name": "Primary metric", "unit": "units"}],
        "assumptions": [
            {"identifier": "a-1", "statement": "Conditions remain stable", "confidence": 0.9}
        ],
        "metadata": {},
    }


def seed_payload() -> dict[str, Any]:
    return {
        "identifier": "seed-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": "v1",
        "metadata": {},
    }


def campaign_payload(world_version_id: str) -> dict[str, Any]:
    return {
        "campaign_id": "campaign-1",
        "campaign_name": "Reference campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": {
            "identifier": "sr-1",
            "tenant_id": TENANT,
            "schema_version": "1.0.0",
            "scenario_id": "scenario-1",
            "required_observations": [
                {"metric_id": "m-1", "description": "observe m-1", "required": True}
            ],
            "requested_at": NOW,
            "metadata": {},
        },
        "seed_ensemble": [seed_payload()],
        "runtime_version": "1.0.0",
        "created_at": NOW,
    }


def prepare_world(client: TestClient) -> str:
    response = client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload())
    assert response.status_code == 201
    compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
    world_id: str = compiled["version"]["identifier"]
    return world_id


def prepare_campaign(client: TestClient, world_id: str) -> None:
    response = client.post("/v1/campaigns", headers=HEADERS, json=campaign_payload(world_id))
    assert response.status_code == 201


def start_campaign(client: TestClient) -> None:
    response = client.post(
        "/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW}
    )
    assert response.status_code == 200


def first_run_id(client: TestClient) -> str:
    runs = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()["run_plans"]
    run_id: str = f"run-{runs[0]['identifier']}"
    return run_id


class TestExecuteApi:
    def test_execute_rejected_before_start(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INVALID_STATE

    def test_execute_after_start_completes_all_runs_and_campaign(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        start_campaign(client)
        response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert response.status_code == 200
        statuses = [RunStatus.model_validate(s) for s in response.json()["run_statuses"]]
        assert len(statuses) == 5
        assert all(s.state == "complete" for s in statuses)
        assert all(re.fullmatch(r"[0-9a-f]{64}", s.event_hash or "") for s in statuses)
        campaign = client.get("/v1/campaigns/campaign-1", headers=HEADERS).json()
        assert campaign["status"]["state"] == "complete"

    def test_execute_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post("/v1/campaigns/campaign-1/execute")
        assert response.status_code == 422

    def test_execute_unknown_campaign_returns_404(self, client: TestClient) -> None:
        response = client.post("/v1/campaigns/campaign-ghost/execute", headers=HEADERS)
        assert response.status_code == 404


class TestRunReadApi:
    def test_run_status_events_and_replay(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        start_campaign(client)
        client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        run_id = first_run_id(client)

        status = client.get(f"/v1/runs/{run_id}", headers=HEADERS)
        assert status.status_code == 200
        assert RunStatus.model_validate(status.json()).state == "complete"

        events = client.get(f"/v1/runs/{run_id}/events", headers=HEADERS)
        assert events.status_code == 200
        parsed = [RunEvent.model_validate(e) for e in events.json()["events"]]
        assert [e.sequence for e in parsed] == [0, 1, 2]

        replay = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert replay.status_code == 200
        manifest = ReplayManifest.model_validate(replay.json())
        assert manifest.replay_classification == "exact"
        assert manifest.expected_event_hash == status.json()["event_hash"]

    def test_planned_run_visible_before_execution(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        status = client.get(f"/v1/runs/{run_id}", headers=HEADERS)
        assert status.status_code == 200
        assert status.json()["state"] == "planned"

    def test_replay_of_planned_run_rejected(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        run_id = first_run_id(client)
        response = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.INVALID_STATE

    def test_foreign_tenant_cannot_access_runs(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        start_campaign(client)
        client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        run_id = first_run_id(client)
        foreign = {"X-Tenant-ID": "tenant-2"}
        assert client.get(f"/v1/runs/{run_id}", headers=foreign).status_code == 404
        assert client.get(f"/v1/runs/{run_id}/events", headers=foreign).status_code == 404
        assert client.get(f"/v1/runs/{run_id}/replay", headers=foreign).status_code == 404

    def test_unknown_run_returns_404(self, client: TestClient) -> None:
        assert client.get("/v1/runs/run-unknown", headers=HEADERS).status_code == 404
        assert client.get("/v1/runs/run-unknown/events", headers=HEADERS).status_code == 404
        assert client.get("/v1/runs/run-unknown/replay", headers=HEADERS).status_code == 404

    def test_run_endpoints_require_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/runs/run-1").status_code == 422
        assert client.get("/v1/runs/run-1/events").status_code == 422
        assert client.get("/v1/runs/run-1/replay").status_code == 422

    def test_events_are_purely_structural(self, client: TestClient) -> None:
        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        start_campaign(client)
        client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        run_id = first_run_id(client)
        events = client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).json()["events"]
        for event in events:
            payload = event["payload"]
            assert not {"outcome", "recommendation", "evidence", "probability"}.intersection(
                payload
            )
            assert set(payload).issubset(
                {
                    "runtime_version",
                    "run_plan_id",
                    "lifecycle",
                    "strategy_version",
                    "policy_summary",
                    "event_count",
                }
            )
