"""API and world-integration tests for Phase 7 domain pack bindings."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.domain_pack import DomainPackBinding

NOW = "2026-01-01T12:00:00Z"
BOUND_AT = "2026-01-03T12:00:00Z"
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


def seed_payload() -> dict[str, Any]:
    return {
        "identifier": "seed-1",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": "v1",
        "metadata": {},
    }


def campaign_payload(campaign_id: str, world_version_id: str) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
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


def manifest_payload(
    identifier: str = "manifest-1",
    pack_id: str = "pack-1",
    capability_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "pack_id": pack_id,
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": capability_id,
                "description": f"Declared capability {capability_id}",
                "input_ids": [f"in-{capability_id}"],
                "output_ids": [f"out-{capability_id}"],
                "metadata": {},
            }
            for capability_id in (capability_ids or ["cap-1", "cap-2"])
        ],
        "schema_metadata": {"declarative": True},
        "created_at": NOW,
        "metadata": {},
    }


def register_manifest(
    client: TestClient, identifier: str = "manifest-1", pack_id: str = "pack-1"
) -> dict[str, Any]:
    response = client.post(
        "/v1/domain-packs", headers=HEADERS, json=manifest_payload(identifier, pack_id)
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def register_scenario(client: TestClient, tenant_id: str = TENANT) -> None:
    response = client.post(
        "/v1/scenarios",
        headers={"X-Tenant-ID": tenant_id},
        json=scenario_payload(tenant_id),
    )
    assert response.status_code == 201


def bind_manifest_api(
    client: TestClient,
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    tenant_id: str = TENANT,
) -> dict[str, Any]:
    response = client.post(
        f"/v1/scenarios/{scenario_id}/domain-pack-bindings",
        headers={"X-Tenant-ID": tenant_id},
        json={"manifest_id": manifest_id, "bound_at": BOUND_AT},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def compile_world_api(client: TestClient, scenario_id: str = "scenario-1") -> dict[str, Any]:
    response = client.post(f"/v1/scenarios/{scenario_id}/compile", headers=HEADERS)
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


class TestBindDomainPackApi:
    def test_bind_returns_201_with_exact_manifest_snapshot(self, client: TestClient) -> None:
        register_scenario(client)
        manifest = register_manifest(client)
        binding = bind_manifest_api(client)

        assert binding["tenant_id"] == TENANT
        assert binding["scenario_id"] == "scenario-1"
        assert binding["manifest_id"] == "manifest-1"
        assert binding["pack_id"] == manifest["pack_id"]
        assert binding["pack_version"] == manifest["pack_version"]
        assert binding["manifest_content_hash"] == manifest["content_hash"]
        # Capability identifiers copied from the registered manifest in order.
        assert binding["capability_ids"] == ["cap-1", "cap-2"]
        assert binding["bound_at"] == BOUND_AT
        assert binding["identifier"].startswith("binding-")
        assert DomainPackBinding.model_validate(binding).identifier == binding["identifier"]

    @pytest.mark.parametrize(
        "extra_field",
        [
            {"pack_id": "pack-9"},
            {"pack_version": "9.9.9"},
            {"capability_ids": ["cap-9"]},
            {"tenant_id": TENANT},
            {"manifest_content_hash": "f" * 64},
            {"content_hash": "f" * 64},
            {"identifier": "binding-9"},
        ],
    )
    def test_bind_rejects_client_supplied_manifest_fields(
        self, client: TestClient, extra_field: dict[str, str]
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        payload: dict[str, Any] = {"manifest_id": "manifest-1", "bound_at": BOUND_AT}
        payload.update(extra_field)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings", headers=HEADERS, json=payload
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_bind_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_manifest(client)
        response = client.post(
            "/v1/scenarios/scenario-ghost/domain-pack-bindings",
            headers=HEADERS,
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_bind_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client, tenant_id="tenant-1")
        register_manifest(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers={"X-Tenant-ID": "tenant-2"},
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert response.status_code == 404

    def test_bind_unknown_manifest_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers=HEADERS,
            json={"manifest_id": "manifest-ghost", "bound_at": BOUND_AT},
        )
        assert response.status_code == 404

    def test_bind_foreign_manifest_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client, tenant_id="tenant-1")
        register_manifest(client)  # tenant-1 owns the manifest
        # tenant-2 owns a scenario but the manifest is tenant-1's.
        register_scenario(client, tenant_id="tenant-2")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers={"X-Tenant-ID": "tenant-2"},
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_duplicate_binding_returns_typed_409(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        assert bind_manifest_api(client)["identifier"]
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers=HEADERS,
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_bind_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert response.status_code == 422

    def test_bind_response_contains_no_executable_artifacts(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        binding = bind_manifest_api(client)
        assert not {"outcome", "evidence", "recommendation", "brief", "metrics"}.intersection(
            binding
        )


class TestListBindingsApi:
    def test_list_empty_for_owned_scenario(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.get("/v1/scenarios/scenario-1/domain-pack-bindings", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"bindings": []}

    def test_list_is_sorted_by_manifest_identifier(self, client: TestClient) -> None:
        register_scenario(client)
        for identifier in ("manifest-z", "manifest-a", "manifest-m"):
            register_manifest(client, identifier=identifier, pack_id=f"pack-{identifier}")
        bind_manifest_api(client, manifest_id="manifest-z")
        bind_manifest_api(client, manifest_id="manifest-a")
        bind_manifest_api(client, manifest_id="manifest-m")
        response = client.get("/v1/scenarios/scenario-1/domain-pack-bindings", headers=HEADERS)
        assert response.status_code == 200
        bindings = response.json()["bindings"]
        assert [binding["manifest_id"] for binding in bindings] == [
            "manifest-a",
            "manifest-m",
            "manifest-z",
        ]

    def test_list_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        response = client.get("/v1/scenarios/scenario-ghost/domain-pack-bindings", headers=HEADERS)
        assert response.status_code == 404

    def test_list_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.get(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers={"X-Tenant-ID": "tenant-2"},
        )
        assert response.status_code == 404

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/scenarios/scenario-1/domain-pack-bindings").status_code == 422


class TestWorldBindingIntegration:
    def test_unbound_compile_is_unchanged_and_repeatable(self, client: TestClient) -> None:
        register_scenario(client)
        first = compile_world_api(client)
        second = compile_world_api(client)
        assert first == second
        assert "domain_pack_bindings" not in first["version"]["world"]

    def test_compile_before_binding_remains_unchanged_after_binding(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        before = compile_world_api(client)
        world_id = before["version"]["identifier"]
        before_world = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()

        register_manifest(client)
        bind_manifest_api(client)
        after = compile_world_api(client)

        # Binding changed the compiled world hash; the pre-binding world is
        # untouched and unchanged in the store.
        assert after["version"]["content_hash"] != before["version"]["content_hash"]
        stored_before = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        assert stored_before == before_world
        assert "domain_pack_bindings" not in stored_before["world"]

    def test_bound_compile_has_distinct_hash_and_immutable_snapshot(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        before = compile_world_api(client)
        register_manifest(client)
        binding = bind_manifest_api(client)
        after = compile_world_api(client)

        assert before["version"]["identifier"] != after["version"]["identifier"]
        assert before["version"]["content_hash"] != after["version"]["content_hash"]
        # The world carries the exact immutable binding snapshot.
        snapshots = after["version"]["world"]["domain_pack_bindings"]
        assert snapshots == [binding]
        # The manifest declares the generic binding count.
        assert after["manifest"]["state"]["declared_domain_pack_binding_count"] == 1
        assert "domain_pack_bindings" not in before["version"]["world"]

    def test_multiple_bindings_appear_in_deterministic_order(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client, identifier="manifest-z", pack_id="pack-z")
        register_manifest(client, identifier="manifest-a", pack_id="pack-a")
        bind_manifest_api(client, manifest_id="manifest-z")
        bind_manifest_api(client, manifest_id="manifest-a")
        compiled = compile_world_api(client)
        snapshots = compiled["version"]["world"]["domain_pack_bindings"]
        assert [snapshot["manifest_id"] for snapshot in snapshots] == [
            "manifest-a",
            "manifest-z",
        ]
        assert compiled["manifest"]["state"]["declared_domain_pack_binding_count"] == 2

    def test_binding_set_change_yields_distinct_world_versions(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client, identifier="manifest-1")
        register_manifest(client, identifier="manifest-2", pack_id="pack-2")
        none_compiled = compile_world_api(client)
        bind_manifest_api(client, manifest_id="manifest-1")
        one_compiled = compile_world_api(client)
        bind_manifest_api(client, manifest_id="manifest-2")
        two_compiled = compile_world_api(client)

        hashes = {
            none_compiled["version"]["content_hash"],
            one_compiled["version"]["content_hash"],
            two_compiled["version"]["content_hash"],
        }
        assert len(hashes) == 3

    def test_campaign_run_plan_input_hashes_differ_with_world_hash(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        unbound = compile_world_api(client)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=campaign_payload("campaign-unbound", unbound["version"]["identifier"]),
            ).status_code
            == 201
        )

        register_manifest(client)
        bind_manifest_api(client)
        bound = compile_world_api(client)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=campaign_payload("campaign-bound", bound["version"]["identifier"]),
            ).status_code
            == 201
        )

        unbound_plans = client.get("/v1/campaigns/campaign-unbound/runs", headers=HEADERS).json()[
            "run_plans"
        ]
        bound_plans = client.get("/v1/campaigns/campaign-bound/runs", headers=HEADERS).json()[
            "run_plans"
        ]
        assert unbound_plans[0]["input_hash"] != bound_plans[0]["input_hash"]
        assert len(bound_plans) == 5  # planning unchanged: 5 strategies x 1 seed

    def test_full_flow_execution_replay_integrity_with_bound_world(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        compiled = compile_world_api(client)
        world_id = compiled["version"]["identifier"]
        assert compiled["version"]["world"]["domain_pack_bindings"]

        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=campaign_payload("campaign-1", world_id),
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW},
            ).status_code
            == 200
        )
        executed = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert executed.status_code == 200
        assert all(status["state"] == "complete" for status in executed.json()["run_statuses"])

        plans = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()["run_plans"]
        run_id = f"run-{plans[0]['identifier']}"
        assert client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS).status_code == 200
        verified = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert verified.status_code == 200
        assert verified.json()["expected_input_hash"] == verified.json()["recomputed_input_hash"]
