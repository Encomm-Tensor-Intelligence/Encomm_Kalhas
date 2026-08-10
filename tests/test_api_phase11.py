"""API and world-integration tests for Phase 11 domain state models.

Covers the strict request boundary (client-supplied identity/hash fields
rejected), typed errors for missing/foreign/duplicate/integrity cases,
deterministic canonical listing, world snapshotting with canonical
ordering (hash changes for new worlds, old worlds byte-identical), the
operational-activity event (exactly once on success, never on rejection,
safe payload only), and the full campaign/verify/replay flow staying
green on a state-model-snapshotted world.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.state_model import DomainStateModel

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


def state_field_payload(
    identifier: str = "status",
    value_kind: str = "string",
    initial_value: Any = "idle",
    allowed_values: list[Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": identifier,
        "description": "A declared state field",
        "value_kind": value_kind,
        "initial_value": initial_value,
        "metadata": {},
    }
    if allowed_values is not None:
        payload["allowed_values"] = allowed_values
    return payload


def state_model_payload(
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
    state_fields: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "manifest_id": manifest_id,
        "state_model_id": state_model_id,
        "state_fields": state_fields
        or [
            state_field_payload(),
            state_field_payload("level", "integer", 0, None),
        ],
        "declared_at": DECLARED_AT,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def setup_bound_scenario(client: TestClient, tenant_id: str = TENANT) -> None:
    headers = {"X-Tenant-ID": tenant_id}
    assert (
        client.post("/v1/scenarios", headers=headers, json=scenario_payload(tenant_id)).status_code
        == 201
    )
    assert (
        client.post("/v1/domain-packs", headers=headers, json=manifest_payload()).status_code == 201
    )
    assert (
        client.post(
            "/v1/scenarios/scenario-1/domain-pack-bindings",
            headers=headers,
            json={"manifest_id": "manifest-1", "bound_at": BOUND_AT},
        ).status_code
        == 201
    )


def activity(client: TestClient, tenant_id: str = TENANT) -> dict[str, Any]:
    response = client.get("/v1/operational-activity", headers={"X-Tenant-ID": tenant_id})
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


class TestDeclareStateModelApi:
    def test_declare_returns_201_with_exact_stored_snapshot(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 201
        model = response.json()
        assert model["state_model_id"] == "state-model-1"
        assert model["scenario_id"] == "scenario-1"
        assert model["manifest_id"] == "manifest-1"
        assert model["binding_id"].startswith("binding-")
        assert model["pack_id"] == "pack-1"
        assert model["pack_version"] == "1.2.3"
        assert len(model["manifest_content_hash"]) == 64
        assert model["identifier"].startswith("state-model-")
        assert len(model["content_hash"]) == 64
        # State fields are canonicalized by identifier in the response.
        assert [f["identifier"] for f in model["state_fields"]] == ["level", "status"]
        # The stored snapshot is identical to the response.
        listing = client.get("/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS).json()
        assert listing["state_models"] == [model]

    def test_declare_canonicalizes_caller_field_order(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        reversed_fields = [
            state_field_payload("level", "integer", 0, None),
            state_field_payload(),
        ]
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(state_model_id="sm-ordered", state_fields=reversed_fields),
        )
        assert response.status_code == 201
        assert [f["identifier"] for f in response.json()["state_fields"]] == ["level", "status"]

    def test_declare_accepts_all_value_kinds(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        fields = [
            state_field_payload("s", "string", "x"),
            state_field_payload("i", "integer", 3),
            state_field_payload("n", "number", 1.5),
            state_field_payload("b", "boolean", True),
            state_field_payload("j", "json", {"k": [1, None]}),
        ]
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(state_model_id="sm-kinds", state_fields=fields),
        )
        assert response.status_code == 201
        assert len(response.json()["state_fields"]) == 5

    def test_declare_rejects_client_supplied_identity_and_hash_fields(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        for extra in (
            {"tenant_id": TENANT},
            {"schema_version": "1.0.0"},
            {"identifier": "state-model-1"},
            {"binding_id": "binding-anything"},
            {"pack_id": "pack-anything"},
            {"pack_version": "9.9.9"},
            {"manifest_content_hash": "0" * 64},
            {"content_hash": "0" * 64},
        ):
            response = client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json={**state_model_payload(), **extra},
            )
            assert response.status_code == 422, extra
            assert (
                ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR
            )

    @pytest.mark.parametrize(
        "bad_field",
        [
            state_field_payload("f", "integer", True),
            state_field_payload("f", "number", True),
            state_field_payload("f", "integer", 1.5),
            state_field_payload("f", "number", float("nan")),
            state_field_payload("f", "number", float("inf")),
            state_field_payload("f", "boolean", 1),
            state_field_payload("f", "string", 5),
            {
                "identifier": "f",
                "description": "d",
                "value_kind": "string",
                "initial_value": "a",
                "allowed_values": ["a", "a"],
            },
            {
                "identifier": "f",
                "description": "d",
                "value_kind": "string",
                "initial_value": "missing",
                "allowed_values": ["a", "b"],
            },
        ],
    )
    def test_declare_rejects_invalid_state_fields(
        self, client: TestClient, bad_field: dict[str, Any]
    ) -> None:
        setup_bound_scenario(client)
        body = state_model_payload(state_fields=[bad_field])
        has_non_finite = any(
            isinstance(value, float) and not math.isfinite(value) for value in bad_field.values()
        )
        if has_non_finite:
            # NaN/Infinity are not valid JSON, so they are sent as a raw
            # body (json.loads accepts them) to prove the boundary rejects
            # them with a typed 422.
            response = client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers={**HEADERS, "Content-Type": "application/json"},
                content=json.dumps(body, allow_nan=True),
            )
        else:
            response = client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=body,
            )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_rejects_duplicate_state_field_identifiers(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(
                state_fields=[state_field_payload(), state_field_payload("status", "string", "x")]
            ),
        )
        assert response.status_code == 422

    def test_declare_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios/scenario-ghost/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 404

    def test_declare_unbound_manifest_returns_typed_404(self, client: TestClient) -> None:
        assert (
            client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code
            == 201
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 404

    def test_declare_unknown_manifest_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(manifest_id="manifest-ghost"),
        )
        assert response.status_code == 404

    def test_declare_foreign_binding_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers={"X-Tenant-ID": "tenant-b"},
            json=state_model_payload(),
        )
        assert response.status_code == 404

    def test_duplicate_declaration_returns_typed_409(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(),
            ).status_code
            == 201
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(state_fields=[state_field_payload()]),
        )
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT

    def test_declare_requires_tenant_header(self, client: TestClient) -> None:
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models", json=state_model_payload()
            ).status_code
            == 422
        )

    def test_declare_response_contains_no_executable_artifacts(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 201
        serialized = json.dumps(response.json())
        for token in ("transition", "formula", "expression", "callback", "eval("):
            assert token not in serialized
        for word in ("script", "policy", "mechanism"):
            assert re.search(rf"\b{word}\b", serialized) is None


class TestListStateModelsApi:
    def test_list_empty_for_owned_scenario(self, client: TestClient) -> None:
        assert (
            client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code
            == 201
        )
        response = client.get("/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"state_models": []}

    def test_list_is_sorted_by_manifest_then_state_model(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        # Second manifest bound to the same scenario.
        assert (
            client.post(
                "/v1/domain-packs",
                headers=HEADERS,
                json=manifest_payload("manifest-2", "pack-2"),
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-pack-bindings",
                headers=HEADERS,
                json={"manifest_id": "manifest-2", "bound_at": BOUND_AT},
            ).status_code
            == 201
        )
        for manifest_id, state_model_id in (
            ("manifest-1", "sm-b"),
            ("manifest-2", "sm-a"),
        ):
            assert (
                client.post(
                    "/v1/scenarios/scenario-1/domain-state-models",
                    headers=HEADERS,
                    json=state_model_payload(
                        manifest_id=manifest_id, state_model_id=state_model_id
                    ),
                ).status_code
                == 201
            )
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS
        ).json()["state_models"]
        assert [(m["manifest_id"], m["state_model_id"]) for m in listing] == [
            ("manifest-1", "sm-b"),
            ("manifest-2", "sm-a"),
        ]

    def test_list_unknown_or_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        assert (
            client.get(
                "/v1/scenarios/scenario-ghost/domain-state-models", headers=HEADERS
            ).status_code
            == 404
        )
        setup_bound_scenario(client, tenant_id="tenant-a")
        assert (
            client.get("/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS).status_code
            == 404
        )

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/scenarios/scenario-1/domain-state-models").status_code == 422


class TestWorldStateModelIntegration:
    def _declare(self, client: TestClient, **overrides: Any) -> dict[str, Any]:
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(**overrides),
        )
        assert response.status_code == 201
        return cast(dict[str, Any], response.json())

    def test_compile_before_declaration_remains_unchanged_after_declaration(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        before = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        world_id = before["version"]["identifier"]
        self._declare(client)
        after = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        # The old world is still served byte-identical (immutable).
        old = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        assert old == before["version"]
        # The newly compiled world differs and carries the snapshot.
        assert after["version"]["identifier"] != world_id
        assert after["version"]["content_hash"] != before["version"]["content_hash"]
        snapshots = after["version"]["world"]["domain_state_models"]
        assert len(snapshots) == 1
        assert snapshots[0]["state_model_id"] == "state-model-1"
        assert snapshots[0]["manifest_id"] == "manifest-1"
        assert after["manifest"]["state"]["declared_domain_state_model_count"] == 1

    def test_world_snapshot_is_canonical_and_order_invariant(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        first = self._declare(client, state_model_id="sm-1")
        second = self._declare(
            client,
            state_model_id="sm-2",
            state_fields=[
                state_field_payload("level", "integer", 0, None),
                state_field_payload("status", "string", "idle"),
            ],
        )
        # Different state models may share fields; the compiler
        # canonicalizes model order by (manifest_id, state_model_id) and
        # field order by identifier inside every snapshot.
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        snapshots = compiled["version"]["world"]["domain_state_models"]
        assert [s["state_model_id"] for s in snapshots] == ["sm-1", "sm-2"]
        for snapshot in snapshots:
            assert [f["identifier"] for f in snapshot["state_fields"]] == ["level", "status"]
        # Every snapshot matches the stored model exactly.
        listing = {
            m["state_model_id"]: m
            for m in client.get(
                "/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS
            ).json()["state_models"]
        }
        assert {s["state_model_id"]: s for s in snapshots} == listing
        assert first["content_hash"] != second["content_hash"]

    def test_world_hash_is_order_invariant_at_the_compiler_boundary(
        self, client: TestClient
    ) -> None:
        """Same semantic inputs in different storage order -> same world hash."""
        from kalhas.application.world_compiler import compile_world, content_hash

        setup_bound_scenario(client)
        self._declare(client, state_model_id="sm-1")
        self._declare(
            client,
            state_model_id="sm-2",
            state_fields=[
                state_field_payload("level", "integer", 0, None),
                state_field_payload("status", "string", "idle"),
            ],
        )
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS
        ).json()["state_models"]

        from kalhas.contracts.v1.scenario import ScenarioSpec

        scenario = ScenarioSpec.model_validate(scenario_payload())
        models = tuple(DomainStateModel.model_validate(model) for model in listing)
        digest_ordered = content_hash(scenario, state_models=models)
        digest_reversed = content_hash(scenario, state_models=models[::-1])
        assert digest_ordered == digest_reversed
        # A hand-built model with reversed field order compiles identically:
        # the compiler re-canonicalizes field order for the snapshot and
        # hash, so the reversed representation is the same semantic model
        # (same authoritative content hash).
        reversed_fields = models[0].model_copy(
            update={"state_fields": tuple(reversed(models[0].state_fields))}
        )
        compiled = compile_world(scenario, state_models=(reversed_fields, models[1]))
        assert compiled.version.content_hash == digest_ordered
        snapshots = cast(list[dict[str, Any]], compiled.version.world["domain_state_models"])
        assert [f["identifier"] for f in snapshots[0]["state_fields"]] == [
            f.identifier for f in models[0].state_fields
        ]

    def test_state_model_set_change_yields_distinct_world_versions(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        first = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        self._declare(client)
        second = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        assert second["version"]["content_hash"] != first["version"]["content_hash"]

    def test_campaign_full_flow_execution_replay_integrity_with_state_model_world(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        self._declare(client)
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        world_id = compiled["version"]["identifier"]
        campaign = {
            "campaign_id": "campaign-1",
            "campaign_name": "Reference campaign",
            "scenario_id": "scenario-1",
            "world_version_id": world_id,
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
            "seed_ensemble": [
                {
                    "identifier": "seed-1",
                    "tenant_id": TENANT,
                    "schema_version": "1.0.0",
                    "algorithm": "deterministic",
                    "seed_value": "v1",
                    "metadata": {},
                }
            ],
            "created_at": NOW,
            "runtime_version": "1.0.0",
        }
        assert client.post("/v1/campaigns", headers=HEADERS, json=campaign).status_code == 201
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": STARTED_AT},
            ).status_code
            == 200
        )
        assert client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS).status_code == 200
        plans = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()["run_plans"]
        run_id = f"run-{plans[0]['identifier']}"
        assert client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS).status_code == 200
        replay = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert replay.status_code == 200
        assert replay.json()["replay_classification"] == "exact"


class TestStateModelActivity:
    def test_successful_declaration_appends_exactly_one_event(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        before = activity(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(),
        )
        assert response.status_code == 201
        feed = activity(client)
        assert feed["latest_sequence"] == before["latest_sequence"] + 1
        assert [e["kind"] for e in feed["events"]][-1] == "domain_state_model_declared"
        event = feed["events"][-1]
        assert event["scenario_id"] == "scenario-1"
        assert event["manifest_id"] == "manifest-1"
        assert event["binding_id"].startswith("binding-")
        assert event["payload"]["state_model_id"] == "state-model-1"
        assert len(event["payload"]["content_hash"]) == 64
        assert event["payload"]["state_field_count"] == 2

    def test_activity_payload_never_exposes_state_field_content(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        fields = [
            state_field_payload("field-zeta", "string", "reserve"),
            state_field_payload("field-omega", "string", "gold", ["gold", "silver"]),
        ]
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-models",
            headers=HEADERS,
            json=state_model_payload(state_model_id="sm-secret", state_fields=fields),
        )
        assert response.status_code == 201
        feed = activity(client)
        serialized = json.dumps(feed)
        for secret in (
            "reserve",
            "gold",
            "silver",
            "field-zeta",
            "field-omega",
            "A declared state field",
        ):
            assert secret not in serialized

    def test_rejected_declarations_append_nothing(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(),
            ).status_code
            == 201
        )
        feed = activity(client)
        assert feed["latest_sequence"] == 3  # scenario, manifest, binding, state model
        # Duplicate (409).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(),
            ).status_code
            == 409
        )
        # Invalid field (422).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(
                    state_model_id="sm-bad",
                    state_fields=[state_field_payload("f", "integer", True)],
                ),
            ).status_code
            == 422
        )
        # Foreign tenant (404).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers={"X-Tenant-ID": "tenant-other"},
                json=state_model_payload(state_model_id="sm-foreign"),
            ).status_code
            == 404
        )
        after = activity(client)
        assert after == feed
        assert [e["kind"] for e in after["events"]][-1] == "domain_state_model_declared"

    def test_tenants_are_isolated_in_activity(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers={"X-Tenant-ID": "tenant-a"},
                json=state_model_payload(),
            ).status_code
            == 201
        )
        feed_b = activity(client, tenant_id="tenant-b")
        assert feed_b == {"events": [], "next_after_sequence": -1, "latest_sequence": -1}
