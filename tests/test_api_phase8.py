"""API and world-integration tests for Phase 8 capability declarations."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.domain_pack import DomainCapabilityDeclaration

NOW = "2026-01-01T12:00:00Z"
BOUND_AT = "2026-01-03T12:00:00Z"
DECLARED_AT = "2026-01-04T12:00:00Z"
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


def manifest_payload(identifier: str = "manifest-1", pack_id: str = "pack-1") -> dict[str, Any]:
    # cap-1 declares two ordered inputs; cap-2 declares zero inputs.
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
            },
            {
                "identifier": "cap-2",
                "description": "Zero-input declared capability",
                "input_ids": [],
                "output_ids": ["out-2"],
                "metadata": {},
            },
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


def declare_api(
    client: TestClient,
    scenario_id: str = "scenario-1",
    manifest_id: str = "manifest-1",
    capability_id: str = "cap-1",
    input_values: dict[str, Any] | None = None,
    declared_at: str = DECLARED_AT,
    tenant_id: str = TENANT,
) -> dict[str, Any]:
    if input_values is None:
        input_values = {"in-a": "value-a", "in-b": 42}
    response = client.post(
        f"/v1/scenarios/{scenario_id}/domain-capability-declarations",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "manifest_id": manifest_id,
            "capability_id": capability_id,
            "input_values": input_values,
            "declared_at": declared_at,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def compile_world_api(client: TestClient, scenario_id: str = "scenario-1") -> dict[str, Any]:
    response = client.post(f"/v1/scenarios/{scenario_id}/compile", headers=HEADERS)
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


class TestDeclareCapabilityInputsApi:
    def test_declare_returns_201_with_exact_stored_snapshot(self, client: TestClient) -> None:
        register_scenario(client)
        manifest = register_manifest(client)
        binding = bind_manifest_api(client)
        declaration = declare_api(client)

        assert declaration["tenant_id"] == TENANT
        assert declaration["scenario_id"] == "scenario-1"
        assert declaration["binding_id"] == binding["identifier"]
        assert declaration["manifest_id"] == "manifest-1"
        assert declaration["pack_id"] == manifest["pack_id"]
        assert declaration["pack_version"] == manifest["pack_version"]
        assert declaration["manifest_content_hash"] == manifest["content_hash"]
        assert declaration["capability_id"] == "cap-1"
        assert declaration["input_values"] == {"in-a": "value-a", "in-b": 42}
        assert declaration["declared_at"] == DECLARED_AT
        assert declaration["identifier"].startswith("declaration-")
        assert (
            DomainCapabilityDeclaration.model_validate(declaration).identifier
            == declaration["identifier"]
        )

    def test_declare_rejects_zero_input_capability_with_values(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-2",
                "input_values": {"in-extra": 1},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.parametrize(
        "extra_field",
        [
            {"tenant_id": TENANT},
            {"binding_id": "binding-9"},
            {"pack_id": "pack-9"},
            {"pack_version": "9.9.9"},
            {"manifest_content_hash": "f" * 64},
            {"content_hash": "f" * 64},
            {"identifier": "declaration-9"},
            {"scenario_id": "scenario-9"},
        ],
    )
    def test_declare_rejects_client_supplied_identity_fields(
        self, client: TestClient, extra_field: dict[str, str]
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        payload: dict[str, Any] = {
            "manifest_id": "manifest-1",
            "capability_id": "cap-1",
            "input_values": {"in-a": "value-a", "in-b": 42},
            "declared_at": DECLARED_AT,
        }
        payload.update(extra_field)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json=payload,
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_manifest(client)
        response = client.post(
            "/v1/scenarios/scenario-ghost/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client, tenant_id="tenant-1")
        register_manifest(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers={"X-Tenant-ID": "tenant-2"},
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 404

    def test_declare_unbound_manifest_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 404

    def test_declare_unknown_manifest_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-ghost",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 404

    def test_declare_foreign_binding_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client, tenant_id="tenant-1")
        register_manifest(client)
        bind_manifest_api(client)
        # tenant-2 owns a scenario but the binding is tenant-1's.
        register_scenario(client, tenant_id="tenant-2")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers={"X-Tenant-ID": "tenant-2"},
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    @pytest.mark.parametrize(
        "input_values",
        [
            {"in-a": "value-a"},  # missing in-b
            {"in-a": "value-a", "in-b": 1, "in-extra": 2},  # extra key
            {},  # both missing
        ],
    )
    def test_declare_input_key_mismatch_returns_typed_422(
        self, client: TestClient, input_values: dict[str, Any]
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": input_values,
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_unknown_capability_returns_typed_422(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-ghost",
                "input_values": {},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_duplicate_declaration_returns_typed_409(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        assert declare_api(client)["identifier"]
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "other", "in-b": 7},
                "declared_at": "2026-02-01T12:00:00Z",
            },
        )
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_declare_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert response.status_code == 422

    def test_declare_response_contains_no_executable_artifacts(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        declaration = declare_api(client)
        assert not {"outcome", "evidence", "recommendation", "brief", "metrics"}.intersection(
            declaration
        )


class TestListDeclarationsApi:
    def test_list_empty_for_owned_scenario(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.get(
            "/v1/scenarios/scenario-1/domain-capability-declarations", headers=HEADERS
        )
        assert response.status_code == 200
        assert response.json() == {"declarations": []}

    def test_list_is_sorted_by_manifest_then_capability(self, client: TestClient) -> None:
        register_scenario(client)
        for identifier in ("manifest-z", "manifest-a"):
            register_manifest(client, identifier=identifier, pack_id=f"pack-{identifier}")
        bind_manifest_api(client, manifest_id="manifest-z")
        bind_manifest_api(client, manifest_id="manifest-a")
        # Declare in deliberately shuffled order.
        declare_api(client, manifest_id="manifest-z", capability_id="cap-2", input_values={})
        declare_api(client, manifest_id="manifest-a", capability_id="cap-1")
        declare_api(client, manifest_id="manifest-z", capability_id="cap-1")
        declare_api(client, manifest_id="manifest-a", capability_id="cap-2", input_values={})
        response = client.get(
            "/v1/scenarios/scenario-1/domain-capability-declarations", headers=HEADERS
        )
        assert response.status_code == 200
        declarations = response.json()["declarations"]
        assert [(d["manifest_id"], d["capability_id"]) for d in declarations] == [
            ("manifest-a", "cap-1"),
            ("manifest-a", "cap-2"),
            ("manifest-z", "cap-1"),
            ("manifest-z", "cap-2"),
        ]

    def test_list_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        response = client.get(
            "/v1/scenarios/scenario-ghost/domain-capability-declarations", headers=HEADERS
        )
        assert response.status_code == 404

    def test_list_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        register_scenario(client)
        response = client.get(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers={"X-Tenant-ID": "tenant-2"},
        )
        assert response.status_code == 404

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert (
            client.get("/v1/scenarios/scenario-1/domain-capability-declarations").status_code == 422
        )


class TestCapabilityIdentifierHardening:
    def _duplicate_capability_payload(self, field: str) -> dict[str, Any]:
        payload = manifest_payload()
        capability = payload["capabilities"][0]
        if field == "input_ids":
            capability["input_ids"] = ["in-a", "in-a"]
        else:
            capability["output_ids"] = ["out-1", "out-1"]
        return payload

    @pytest.mark.parametrize("field", ["input_ids", "output_ids"])
    def test_register_rejects_duplicate_capability_ids(
        self, client: TestClient, field: str
    ) -> None:
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=self._duplicate_capability_payload(field),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.parametrize("field", ["input_ids", "output_ids"])
    def test_duplicate_ids_cannot_reach_declaration_creation(
        self, client: TestClient, field: str
    ) -> None:
        """A manifest with duplicate input/output ids never registers, so it
        can never be bound and its capabilities can never be declared."""
        register_scenario(client)
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=self._duplicate_capability_payload(field),
        )
        assert response.status_code == 422
        # Binding is impossible: the manifest was never registered.
        bind_response = client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers=HEADERS,
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        )
        assert bind_response.status_code == 404
        # Declaration is impossible: no binding exists for the manifest.
        declare_response = client.post(
            "/v1/scenarios/scenario-1/domain-capability-declarations",
            headers=HEADERS,
            json={
                "manifest_id": "manifest-1",
                "capability_id": "cap-1",
                "input_values": {"in-a": "value-a", "in-b": 42},
                "declared_at": DECLARED_AT,
            },
        )
        assert declare_response.status_code == 404


class TestWorldDeclarationIntegration:
    def test_undeclared_compile_is_unchanged_and_repeatable(self, client: TestClient) -> None:
        register_scenario(client)
        first = compile_world_api(client)
        second = compile_world_api(client)
        assert first == second
        assert "domain_capability_declarations" not in first["version"]["world"]

    def test_compile_before_declaration_remains_unchanged_after_declaration(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        before = compile_world_api(client)
        world_id = before["version"]["identifier"]
        before_world = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()

        register_manifest(client)
        bind_manifest_api(client)
        declare_api(client)
        after = compile_world_api(client)

        # Declaration changed the compiled world hash; the pre-declaration
        # world is untouched and unchanged in the store.
        assert after["version"]["content_hash"] != before["version"]["content_hash"]
        stored_before = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        assert stored_before == before_world
        assert "domain_capability_declarations" not in stored_before["world"]

    def test_declared_compile_has_distinct_hash_and_immutable_snapshot(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        before = compile_world_api(client)
        register_manifest(client)
        bind_manifest_api(client)
        declaration = declare_api(client)
        after = compile_world_api(client)

        assert before["version"]["identifier"] != after["version"]["identifier"]
        assert before["version"]["content_hash"] != after["version"]["content_hash"]
        # The world carries the exact immutable declaration snapshot.
        snapshots = after["version"]["world"]["domain_capability_declarations"]
        assert snapshots == [declaration]
        # The manifest declares the generic declaration count.
        assert after["manifest"]["state"]["declared_domain_capability_declaration_count"] == 1
        assert "domain_capability_declarations" not in before["version"]["world"]

    def test_declarations_appear_in_deterministic_order(self, client: TestClient) -> None:
        register_scenario(client)
        register_manifest(client, identifier="manifest-z", pack_id="pack-z")
        register_manifest(client, identifier="manifest-a", pack_id="pack-a")
        bind_manifest_api(client, manifest_id="manifest-z")
        bind_manifest_api(client, manifest_id="manifest-a")
        declare_api(client, manifest_id="manifest-z", capability_id="cap-2", input_values={})
        declare_api(client, manifest_id="manifest-a", capability_id="cap-1")
        declare_api(client, manifest_id="manifest-z", capability_id="cap-1")
        declare_api(client, manifest_id="manifest-a", capability_id="cap-2", input_values={})
        compiled = compile_world_api(client)
        snapshots = compiled["version"]["world"]["domain_capability_declarations"]
        assert [(s["manifest_id"], s["capability_id"]) for s in snapshots] == [
            ("manifest-a", "cap-1"),
            ("manifest-a", "cap-2"),
            ("manifest-z", "cap-1"),
            ("manifest-z", "cap-2"),
        ]
        assert compiled["manifest"]["state"]["declared_domain_capability_declaration_count"] == 4

    def test_declaration_set_change_yields_distinct_world_versions(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        none_compiled = compile_world_api(client)
        declare_api(client, capability_id="cap-1")
        one_compiled = compile_world_api(client)
        declare_api(client, capability_id="cap-2", input_values={})
        two_compiled = compile_world_api(client)

        hashes = {
            none_compiled["version"]["content_hash"],
            one_compiled["version"]["content_hash"],
            two_compiled["version"]["content_hash"],
        }
        assert len(hashes) == 3

    def test_campaign_run_plan_input_hashes_differ_with_declaration_world_hash(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        undeclared = compile_world_api(client)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=campaign_payload("campaign-undeclared", undeclared["version"]["identifier"]),
            ).status_code
            == 201
        )

        register_manifest(client)
        bind_manifest_api(client)
        declare_api(client)
        declared = compile_world_api(client)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=campaign_payload("campaign-declared", declared["version"]["identifier"]),
            ).status_code
            == 201
        )

        undeclared_plans = client.get(
            "/v1/campaigns/campaign-undeclared/runs", headers=HEADERS
        ).json()["run_plans"]
        declared_plans = client.get("/v1/campaigns/campaign-declared/runs", headers=HEADERS).json()[
            "run_plans"
        ]
        assert undeclared_plans[0]["input_hash"] != declared_plans[0]["input_hash"]
        assert len(declared_plans) == 5  # planning unchanged: 5 strategies x 1 seed

    def test_full_flow_execution_replay_integrity_with_declared_world(
        self, client: TestClient
    ) -> None:
        register_scenario(client)
        register_manifest(client)
        bind_manifest_api(client)
        declare_api(client)
        compiled = compile_world_api(client)
        world_id = compiled["version"]["identifier"]
        assert compiled["version"]["world"]["domain_capability_declarations"]

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
