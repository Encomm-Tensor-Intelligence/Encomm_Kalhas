"""Phase 19 API tests: metric-observation declaration endpoints.

``POST /v1/scenarios/{scenario_id}/metric-observations`` declares an
immutable state-to-metric observation binding (201, strict request body,
authoritative identities copied from stored records only) and
``GET /v1/scenarios/{scenario_id}/metric-observations`` lists them in
deterministic metric-id order. These tests prove the strict request
boundary, the typed error mappings (404/409/422), tenant isolation, the
absence of sensitive-value leakage, the OpenAPI surface, the compile
endpoint embedding the exact bindings, and the absence of any
operational-activity changes.
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi.testclient import TestClient
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode

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
        "metrics": [
            {"identifier": "m-1", "name": "Primary metric", "unit": "units"},
            {"identifier": "m-2", "name": "Secondary metric", "unit": "units"},
            {"identifier": "m-3", "name": "Tertiary metric", "unit": "units"},
        ],
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
    identifier: str = "level",
    value_kind: str = "integer",
    initial_value: Any = 0,
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "description": "A declared state field",
        "value_kind": value_kind,
        "initial_value": initial_value,
        "metadata": {},
    }


def state_model_payload(
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
) -> dict[str, Any]:
    return {
        "manifest_id": manifest_id,
        "state_model_id": state_model_id,
        "state_fields": [
            state_field_payload("level", "integer", 0),
            state_field_payload("ratio", "number", 0.0),
            state_field_payload("status", "string", "idle"),
            state_field_payload("flag", "boolean", False),
            state_field_payload("extra", "json", {"nested": [1]}),
        ],
        "declared_at": DECLARED_AT,
    }


def observation_payload(
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
    metric_id: str = "m-1",
    state_field_id: str = "level",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "manifest_id": manifest_id,
        "state_model_id": state_model_id,
        "metric_id": metric_id,
        "state_field_id": state_field_id,
        "declared_at": DECLARED_AT,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def setup_bound_scenario(
    client: TestClient,
    tenant_id: str = TENANT,
    declare_model: bool = True,
) -> None:
    """Register a scenario (3 metrics), manifest, binding, and state model."""
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
    if declare_model:
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=headers,
                json=state_model_payload(),
            ).status_code
            == 201
        )


def _store(client: TestClient) -> InMemoryScenarioStore:
    from fastapi import FastAPI

    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


def declare(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(
        "/v1/scenarios/scenario-1/metric-observations",
        headers=HEADERS,
        json=observation_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


class TestDeclareObservationApi:
    def test_declare_returns_201_with_exact_stored_snapshot(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        observation = declare(client)
        assert observation["metric_id"] == "m-1"
        assert observation["scenario_id"] == "scenario-1"
        assert observation["state_field_id"] == "level"
        assert observation["state_field_value_kind"] == "integer"
        assert observation["observation_point"] == "final_state"
        assert observation["manifest_id"] == "manifest-1"
        assert observation["pack_id"] == "pack-1"
        assert observation["pack_version"] == "1.2.3"
        assert observation["binding_id"].startswith("binding-")
        assert observation["identifier"].startswith("observation-")
        assert len(observation["content_hash"]) == 64
        assert len(observation["manifest_content_hash"]) == 64
        assert len(observation["state_model_content_hash"]) == 64
        # The stored snapshot is identical to the response.
        listing = client.get("/v1/scenarios/scenario-1/metric-observations", headers=HEADERS).json()
        assert listing["observations"] == [observation]

    def test_declare_number_field(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        observation = declare(client, metric_id="m-2", state_field_id="ratio")
        assert observation["state_field_value_kind"] == "number"

    def test_declare_rejects_client_supplied_authoritative_fields(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        for extra in (
            {"tenant_id": TENANT},
            {"schema_version": "1.0.0"},
            {"scenario_id": "scenario-1"},
            {"identifier": "observation-1"},
            {"binding_id": "binding-anything"},
            {"pack_id": "pack-anything"},
            {"pack_version": "9.9.9"},
            {"manifest_content_hash": "0" * 64},
            {"state_model_identifier": "state-model-anything"},
            {"state_model_content_hash": "0" * 64},
            {"state_field_value_kind": "integer"},
            {"observation_point": "final_state"},
            {"content_hash": "0" * 64},
        ):
            response = client.post(
                "/v1/scenarios/scenario-1/metric-observations",
                headers=HEADERS,
                json={**observation_payload(), **extra},
            )
            assert response.status_code == 422, extra
            assert (
                ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR
            )

    def test_declare_rejects_empty_identifiers(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        for overrides in (
            {"metric_id": ""},
            {"state_field_id": ""},
            {"state_model_id": ""},
        ):
            response = client.post(
                "/v1/scenarios/scenario-1/metric-observations",
                headers=HEADERS,
                json=observation_payload(**cast(dict[str, Any], overrides)),
            )
            assert response.status_code == 422, overrides

    def test_declare_rejects_non_finite_metadata(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        body = observation_payload(metadata={"x": float("nan")})
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=json.dumps(body, allow_nan=True),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_unknown_metric_returns_422(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers=HEADERS,
            json=observation_payload(metric_id="m-ghost"),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_non_numeric_field_returns_422_safe_error(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        for state_field_id in ("status", "flag", "extra"):
            response = client.post(
                "/v1/scenarios/scenario-1/metric-observations",
                headers=HEADERS,
                json=observation_payload(metric_id="m-2", state_field_id=state_field_id),
            )
            assert response.status_code == 422, state_field_id
            assert (
                ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR
            )
            # No state values or metadata leak into the error body.
            assert "idle" not in response.text
            assert "nested" not in response.text

    def test_declare_unknown_field_returns_422(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers=HEADERS,
            json=observation_payload(metric_id="m-2", state_field_id="field-ghost"),
        )
        assert response.status_code == 422

    def test_declare_unknown_scenario_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios/scenario-ghost/metric-observations",
            headers=HEADERS,
            json=observation_payload(),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_unknown_manifest_returns_404(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers=HEADERS,
            json=observation_payload(manifest_id="manifest-ghost"),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_unknown_state_model_returns_404(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers=HEADERS,
            json=observation_payload(state_model_id="state-model-ghost"),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_duplicate_returns_409_and_never_overwrites(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        first = declare(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers=HEADERS,
            json=observation_payload(metric_id="m-1", state_field_id="ratio"),
        )
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.CONFLICT
        assert "m-1" in error.message
        listing = client.get("/v1/scenarios/scenario-1/metric-observations", headers=HEADERS).json()
        assert listing["observations"] == [first]

    def test_declare_requires_tenant_header(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations", json=observation_payload()
        )
        assert response.status_code == 422

    def test_foreign_tenant_cannot_declare(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        response = client.post(
            "/v1/scenarios/scenario-1/metric-observations",
            headers={"X-Tenant-ID": "tenant-b"},
            json=observation_payload(),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND


class TestListObservationApi:
    def test_list_deterministic_metric_id_order(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        declare(client, metric_id="m-1")
        declare(client, metric_id="m-3", state_field_id="ratio")
        declare(client, metric_id="m-2")
        listing = client.get("/v1/scenarios/scenario-1/metric-observations", headers=HEADERS).json()
        assert [o["metric_id"] for o in listing["observations"]] == ["m-1", "m-2", "m-3"]

    def test_list_unknown_or_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        assert (
            client.get(
                "/v1/scenarios/scenario-ghost/metric-observations", headers=HEADERS
            ).status_code
            == 404
        )
        setup_bound_scenario(client, tenant_id="tenant-a")
        assert (
            client.get("/v1/scenarios/scenario-1/metric-observations", headers=HEADERS).status_code
            == 404
        )

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/scenarios/scenario-1/metric-observations").status_code == 422

    def test_foreign_tenant_listing_is_empty_of_others_bindings(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        headers_a = {"X-Tenant-ID": "tenant-a"}
        assert (
            client.post(
                "/v1/scenarios/scenario-1/metric-observations",
                headers=headers_a,
                json=observation_payload(),
            ).status_code
            == 201
        )
        # tenant-a's binding is invisible to tenant-b on tenant-b's own
        # scenario with the same identifier.
        other = {"X-Tenant-ID": "tenant-b"}
        assert (
            client.post(
                "/v1/scenarios", headers=other, json=scenario_payload("tenant-b")
            ).status_code
            == 201
        )
        listing = client.get("/v1/scenarios/scenario-1/metric-observations", headers=other).json()
        assert listing["observations"] == []


class TestObservationWorldIntegration:
    def test_compile_endpoint_embeds_exact_bindings(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        first = declare(client, metric_id="m-1")
        declare(client, metric_id="m-2", state_field_id="ratio")
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        snapshots = compiled["version"]["world"]["domain_metric_observations"]
        assert [s["metric_id"] for s in snapshots] == ["m-1", "m-2"]
        assert snapshots[0] == first
        assert compiled["manifest"]["state"]["declared_domain_metric_observation_count"] == 2
        # The compiled world is served byte-identical and verified.
        world_id = compiled["version"]["identifier"]
        served = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        assert served == compiled["version"]

    def test_compile_before_declaration_remains_unchanged_after_declaration(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        before = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        world_id = before["version"]["identifier"]
        assert "domain_metric_observations" not in before["version"]["world"]
        declare(client)
        after = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        # The old world is still served byte-identical (immutable).
        old = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        assert old == before["version"]
        # The newly compiled world differs and carries the snapshot.
        assert after["version"]["identifier"] != world_id
        assert after["version"]["content_hash"] != before["version"]["content_hash"]
        assert len(after["version"]["world"]["domain_metric_observations"]) == 1

    def test_no_operational_activity_changes(self, client: TestClient) -> None:
        """Declarations and listings create no operational-activity events."""
        setup_bound_scenario(client)
        activity = client.get("/v1/operational-activity", headers=HEADERS).json()
        before = activity["latest_sequence"]
        declare(client, metric_id="m-1")
        declare(client, metric_id="m-2", state_field_id="ratio")
        client.get("/v1/scenarios/scenario-1/metric-observations", headers=HEADERS)
        after = client.get("/v1/operational-activity", headers=HEADERS).json()
        assert after["latest_sequence"] == before
        events = cast(list[dict[str, Any]], after["events"])
        assert all("metric" not in json.dumps(event) for event in events)
        assert all("observation" not in json.dumps(event) for event in events)


class TestOpenApiSurface:
    def test_metric_observation_paths_in_openapi(self, client: TestClient) -> None:
        openapi = cast(dict[str, Any], client.get("/openapi.json").json())
        paths = openapi["paths"]
        assert "/v1/scenarios/{scenario_id}/metric-observations" in paths
        assert "post" in paths["/v1/scenarios/{scenario_id}/metric-observations"]
        assert "get" in paths["/v1/scenarios/{scenario_id}/metric-observations"]
        post_schema = paths["/v1/scenarios/{scenario_id}/metric-observations"]["post"]
        assert post_schema["responses"]["201"] is not None
        assert "X-Tenant-ID" in str(post_schema)
        assert "X-Tenant-ID" in str(paths["/v1/scenarios/{scenario_id}/metric-observations"]["get"])
        # The declaration request model is strict: no authoritative fields.
        request_ref = post_schema["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_name = request_ref.rsplit("/", 1)[-1]
        schemas = openapi["components"]["schemas"]
        assert "tenant_id" not in schemas[request_name]["properties"]
        assert "content_hash" not in schemas[request_name]["properties"]
        assert "observation_point" not in schemas[request_name]["properties"]
