"""API and world-integration tests for Phase 12 domain state transitions.

Covers the strict request boundary (client-supplied identity/hash fields
rejected, empty target values rejected), typed errors for
missing/foreign/duplicate/integrity cases, canonical mapping and
transition ordering (same stored hash and world hash for equivalent
orderings; transition-free worlds byte-identical to Phase 11), immutable
old worlds, the operational-activity event (exactly once on success,
never on rejection, safe payload only), and the full
campaign/verify/replay flow staying green on a
transition-snapshotted world.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.transition import DomainStateTransition

NOW = "2026-01-01T12:00:00Z"
BOUND_AT = "2026-01-03T12:00:00Z"
DECLARED_AT = "2026-01-04T12:00:00Z"
TRANSITION_AT = "2026-01-06T12:00:00Z"
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
            state_field_payload("flag", "boolean", False, None),
            state_field_payload("extra", "json", {"nested": [1, None]}, None),
        ],
        "declared_at": DECLARED_AT,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def transition_payload(
    manifest_id: str = "manifest-1",
    state_model_id: str = "state-model-1",
    transition_id: str = "transition-1",
    description: str = "A possible state change",
    guard_values: dict[str, Any] | None = None,
    target_values: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "manifest_id": manifest_id,
        "state_model_id": state_model_id,
        "transition_id": transition_id,
        "description": description,
        "guard_values": guard_values if guard_values is not None else {"level": 0},
        "target_values": target_values
        if target_values is not None
        else {"status": "active", "level": 1},
        "declared_at": TRANSITION_AT,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def setup_bound_scenario(
    client: TestClient,
    tenant_id: str = TENANT,
    declare_model: bool = True,
) -> None:
    """Register a scenario, manifest, binding, and (optionally) a state model."""
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


def activity(client: TestClient, tenant_id: str = TENANT) -> dict[str, Any]:
    response = client.get("/v1/operational-activity", headers={"X-Tenant-ID": tenant_id})
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _store(client: TestClient) -> InMemoryScenarioStore:
    """Resolve the app's process-local store (used for tamper injection)."""
    from fastapi import FastAPI

    app = cast(FastAPI, client.app)
    return cast(InMemoryScenarioStore, app.state.store)


class TestDeclareTransitionApi:
    def test_declare_returns_201_with_exact_stored_snapshot(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 201
        transition = response.json()
        assert transition["transition_id"] == "transition-1"
        assert transition["scenario_id"] == "scenario-1"
        assert transition["manifest_id"] == "manifest-1"
        assert transition["state_model_id"] == "state-model-1"
        assert transition["binding_id"].startswith("binding-")
        assert transition["pack_id"] == "pack-1"
        assert transition["pack_version"] == "1.2.3"
        assert len(transition["manifest_content_hash"]) == 64
        assert len(transition["state_model_content_hash"]) == 64
        assert transition["identifier"].startswith("transition-")
        assert len(transition["content_hash"]) == 64
        # Guard/target mappings are canonicalized by field identifier.
        assert list(transition["guard_values"]) == ["level"]
        assert list(transition["target_values"]) == ["level", "status"]
        # The stored snapshot is identical to the response.
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
        ).json()
        assert listing["transitions"] == [transition]

    def test_declare_canonicalizes_caller_mapping_order(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(
                transition_id="t-ordered",
                guard_values={"flag": False, "level": 0},
                target_values={"level": 1, "status": "active"},
            ),
        )
        assert response.status_code == 201
        assert list(response.json()["guard_values"]) == ["flag", "level"]
        assert list(response.json()["target_values"]) == ["level", "status"]

    def test_declare_rejects_client_supplied_identity_and_hash_fields(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        for extra in (
            {"tenant_id": TENANT},
            {"schema_version": "1.0.0"},
            {"identifier": "transition-1"},
            {"binding_id": "binding-anything"},
            {"pack_id": "pack-anything"},
            {"pack_version": "9.9.9"},
            {"manifest_content_hash": "0" * 64},
            {"state_model_content_hash": "0" * 64},
            {"content_hash": "0" * 64},
        ):
            response = client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers=HEADERS,
                json={**transition_payload(), **extra},
            )
            assert response.status_code == 422, extra
            assert (
                ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR
            )

    def test_declare_rejects_empty_transition_id(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(transition_id=""),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_rejects_empty_target_values(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(target_values={}),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.parametrize(
        ("guard_values", "target_values"),
        [
            ({"ghost-field": 1}, None),
            (None, {"ghost-field": 1}),
            ({"level": True}, None),
            (None, {"level": True}),
            (None, {"level": 1.5}),
            (None, {"status": 5}),
            (None, {"flag": 1}),
            ({"level": "0"}, None),
        ],
    )
    def test_declare_rejects_invalid_guard_or_target_values(
        self,
        client: TestClient,
        guard_values: dict[str, Any] | None,
        target_values: dict[str, Any] | None,
    ) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(
                transition_id="t-invalid",
                guard_values=guard_values,
                target_values=target_values,
            ),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_enforces_allowed_values(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        constrained_fields = [
            state_field_payload("mode", "string", "auto", ["auto", "manual"]),
        ]
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(
                    state_model_id="sm-constrained", state_fields=constrained_fields
                ),
            ).status_code
            == 201
        )
        bad = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(
                state_model_id="sm-constrained",
                transition_id="t-allowed",
                guard_values={},
                target_values={"mode": "reserved"},
            ),
        )
        assert bad.status_code == 422
        good = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(
                state_model_id="sm-constrained",
                transition_id="t-allowed-ok",
                guard_values={},
                target_values={"mode": "manual"},
            ),
        )
        assert good.status_code == 201

    @pytest.mark.parametrize(
        "bad_mapping",
        [
            {"status": {"nested": {"x": float("nan")}}},
            {"extra": [1, float("inf")]},
            {"extra": {"deep": [float("-inf")]}},
        ],
    )
    def test_declare_rejects_nested_non_finite_values(
        self, client: TestClient, bad_mapping: dict[str, Any]
    ) -> None:
        setup_bound_scenario(client)
        # NaN/Infinity are not valid JSON, so they are sent as a raw body
        # (json.loads accepts them) to prove the boundary rejects them
        # with a typed 422.
        body = transition_payload(
            transition_id="t-nan", guard_values=bad_mapping, target_values={"level": 1}
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=json.dumps(body, allow_nan=True),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_declare_rejects_non_finite_metadata(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        body = transition_payload(metadata={"nested": {"x": float("inf")}})
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=json.dumps(body, allow_nan=True),
        )
        assert response.status_code == 422

    def test_declare_unknown_scenario_returns_typed_404(self, client: TestClient) -> None:
        response = client.post(
            "/v1/scenarios/scenario-ghost/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_declare_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 404

    def test_declare_unbound_manifest_returns_typed_404(self, client: TestClient) -> None:
        assert (
            client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code
            == 201
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 404

    def test_declare_unknown_manifest_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(manifest_id="manifest-ghost"),
        )
        assert response.status_code == 404

    def test_declare_unknown_state_model_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client, declare_model=False)
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(state_model_id="sm-other"),
            ).status_code
            == 201
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(state_model_id="sm-ghost"),
        )
        assert response.status_code == 404

    def test_declare_foreign_binding_returns_typed_404(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers={"X-Tenant-ID": "tenant-b"},
            json=transition_payload(),
        )
        assert response.status_code == 404

    def test_duplicate_declaration_returns_typed_409(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers=HEADERS,
                json=transition_payload(),
            ).status_code
            == 201
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(target_values={"status": "active", "level": 9}),
        )
        assert response.status_code == 409
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.CONFLICT
        # The original is never overwritten.
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
        ).json()
        assert listing["transitions"][0]["target_values"]["level"] == 1

    def test_declare_requires_tenant_header(self, client: TestClient) -> None:
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions", json=transition_payload()
            ).status_code
            == 422
        )

    def test_declare_response_contains_no_executable_artifacts(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 201
        serialized = json.dumps(response.json())
        for token in ("formula", "expression", "callback", "eval(", "exec("):
            assert token not in serialized
        for word in ("script", "policy", "mechanism", "simulation"):
            assert re.search(rf"\b{word}\b", serialized) is None

    def test_tampered_binding_returns_safe_typed_409(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        store = _store(client)
        tampered = store.get_domain_pack_binding("tenant-1", "scenario-1", "manifest-1").model_copy(
            update={"pack_id": "pack-tampered"}
        )
        # The store has no overwrite surface for immutable contracts, so
        # the tampered snapshot is injected directly (defense in depth).
        store._domain_pack_bindings[("tenant-1", "scenario-1", "manifest-1")] = tampered
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR
        assert "pack-tampered" not in json.dumps(error.model_dump(mode="json"))

    def test_tampered_manifest_returns_safe_typed_409(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        store = _store(client)
        manifest = store.get_domain_pack_manifest("tenant-1", "manifest-1")
        store._domain_pack_manifests[("tenant-1", "manifest-1")] = manifest.model_copy(
            update={"pack_id": "pack-altered"}
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR
        assert "pack-altered" not in json.dumps(error.model_dump(mode="json"))

    def test_tampered_state_model_returns_safe_typed_409(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        store = _store(client)
        model = store.get_domain_state_model(
            "tenant-1", "scenario-1", "manifest-1", "state-model-1"
        )
        store._domain_state_models[("tenant-1", "scenario-1", "manifest-1", "state-model-1")] = (
            model.model_copy(update={"content_hash": "0" * 64})
        )
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.INTEGRITY_ERROR
        assert "0" * 64 not in json.dumps(error.model_dump(mode="json"))


class TestListTransitionsApi:
    def test_list_empty_for_owned_scenario(self, client: TestClient) -> None:
        assert (
            client.post("/v1/scenarios", headers=HEADERS, json=scenario_payload()).status_code
            == 201
        )
        response = client.get("/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"transitions": []}

    def test_list_is_sorted_by_manifest_then_state_model_then_transition(
        self, client: TestClient
    ) -> None:
        setup_bound_scenario(client)
        # Second state model under the same manifest.
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-models",
                headers=HEADERS,
                json=state_model_payload(state_model_id="state-model-2"),
            ).status_code
            == 201
        )
        for state_model_id, transition_id in (
            ("state-model-1", "t-b"),
            ("state-model-1", "t-a"),
            ("state-model-2", "t-x"),
        ):
            assert (
                client.post(
                    "/v1/scenarios/scenario-1/domain-state-transitions",
                    headers=HEADERS,
                    json=transition_payload(
                        state_model_id=state_model_id, transition_id=transition_id
                    ),
                ).status_code
                == 201
            )
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
        ).json()["transitions"]
        assert [(t["state_model_id"], t["transition_id"]) for t in listing] == [
            ("state-model-1", "t-a"),
            ("state-model-1", "t-b"),
            ("state-model-2", "t-x"),
        ]

    def test_list_unknown_or_foreign_scenario_returns_typed_404(self, client: TestClient) -> None:
        assert (
            client.get(
                "/v1/scenarios/scenario-ghost/domain-state-transitions", headers=HEADERS
            ).status_code
            == 404
        )
        setup_bound_scenario(client, tenant_id="tenant-a")
        assert (
            client.get(
                "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
            ).status_code
            == 404
        )

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/scenarios/scenario-1/domain-state-transitions").status_code == 422


class TestWorldTransitionIntegration:
    def _declare(self, client: TestClient, **overrides: Any) -> dict[str, Any]:
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(**overrides),
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
        snapshots = after["version"]["world"]["domain_state_transitions"]
        assert len(snapshots) == 1
        assert snapshots[0]["transition_id"] == "transition-1"
        assert snapshots[0]["state_model_id"] == "state-model-1"
        assert snapshots[0]["manifest_id"] == "manifest-1"
        assert after["manifest"]["state"]["declared_domain_state_transition_count"] == 1

    def test_world_snapshot_is_canonical_and_order_invariant(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        first = self._declare(client, transition_id="t-1")
        second = self._declare(
            client,
            transition_id="t-2",
            guard_values={"flag": False, "level": 0},
            target_values={"level": 1, "status": "active"},
        )
        compiled = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        snapshots = compiled["version"]["world"]["domain_state_transitions"]
        assert [s["transition_id"] for s in snapshots] == ["t-1", "t-2"]
        # Each snapshot preserves its own canonical mapping order.
        assert list(snapshots[0]["guard_values"]) == ["level"]
        assert list(snapshots[0]["target_values"]) == ["level", "status"]
        assert list(snapshots[1]["guard_values"]) == ["flag", "level"]
        assert list(snapshots[1]["target_values"]) == ["level", "status"]
        # Every snapshot matches the stored transition exactly.
        listing = {
            t["transition_id"]: t
            for t in client.get(
                "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
            ).json()["transitions"]
        }
        assert {s["transition_id"]: s for s in snapshots} == listing
        assert first["content_hash"] != second["content_hash"]

    def test_world_hash_is_order_invariant_at_the_compiler_boundary(
        self, client: TestClient
    ) -> None:
        """Same semantic inputs in different storage order -> same world hash."""
        from kalhas.application.world_compiler import compile_world, content_hash

        setup_bound_scenario(client)
        self._declare(client, transition_id="t-1")
        self._declare(
            client,
            transition_id="t-2",
            guard_values={"flag": False, "level": 0},
            target_values={"level": 1, "status": "active"},
        )
        listing = client.get(
            "/v1/scenarios/scenario-1/domain-state-transitions", headers=HEADERS
        ).json()["transitions"]

        from kalhas.contracts.v1.scenario import ScenarioSpec

        scenario = ScenarioSpec.model_validate(scenario_payload())
        transitions = tuple(DomainStateTransition.model_validate(t) for t in listing)
        digest_ordered = content_hash(scenario, transitions=transitions)
        digest_reversed = content_hash(scenario, transitions=transitions[::-1])
        assert digest_ordered == digest_reversed
        # A hand-built transition with reversed mapping order compiles
        # identically: the compiler re-canonicalizes mappings for the
        # snapshot and hash, so the reversed representation is the same
        # semantic transition (same authoritative content hash).
        reversed_mappings = transitions[0].model_copy(
            update={
                "guard_values": dict(reversed(list(transitions[0].guard_values.items()))),
                "target_values": dict(reversed(list(transitions[0].target_values.items()))),
            }
        )
        compiled = compile_world(scenario, transitions=(reversed_mappings, transitions[1]))
        assert compiled.version.content_hash == digest_ordered
        snapshots = cast(list[dict[str, Any]], compiled.version.world["domain_state_transitions"])
        assert list(snapshots[0]["guard_values"]) == list(transitions[0].guard_values)
        assert list(snapshots[0]["target_values"]) == list(transitions[0].target_values)

    def test_transition_free_worlds_compile_byte_identically_to_phase_11(
        self, client: TestClient
    ) -> None:
        """The transitions snapshot is conditional: absent transitions change nothing."""
        from kalhas.application.world_compiler import compile_world

        setup_bound_scenario(client)
        compiled_without = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        assert "domain_state_transitions" not in compiled_without["version"]["world"]
        assert "declared_domain_state_transition_count" not in compiled_without["manifest"]["state"]

        from kalhas.contracts.v1.domain_pack import DomainPackBinding
        from kalhas.contracts.v1.scenario import ScenarioSpec
        from kalhas.contracts.v1.state_model import DomainStateModel

        scenario = ScenarioSpec.model_validate(scenario_payload())
        models = client.get("/v1/scenarios/scenario-1/domain-state-models", headers=HEADERS).json()[
            "state_models"
        ]
        state_models = tuple(DomainStateModel.model_validate(m) for m in models)
        bindings_payload = client.get(
            "/v1/scenarios/scenario-1/domain-pack-bindings", headers=HEADERS
        ).json()["bindings"]
        bindings = tuple(DomainPackBinding.model_validate(b) for b in bindings_payload)
        # Explicit empty transitions == omitted transitions: same hash and
        # byte-identical world content (the Phase 11 compiler result).
        compiled_omitted = compile_world(scenario, bindings=bindings, state_models=state_models)
        compiled_empty = compile_world(
            scenario, bindings=bindings, state_models=state_models, transitions=()
        )
        assert compiled_omitted.version.content_hash == compiled_empty.version.content_hash
        assert compiled_omitted.version.world == compiled_empty.version.world
        # Both match the API-compiled transition-free world exactly.
        assert compiled_omitted.version.content_hash == compiled_without["version"]["content_hash"]
        assert compiled_omitted.version.world == compiled_without["version"]["world"]

    def test_transition_set_change_yields_distinct_world_versions(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        first = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        self._declare(client)
        second = client.post("/v1/scenarios/scenario-1/compile", headers=HEADERS).json()
        assert second["version"]["content_hash"] != first["version"]["content_hash"]

    def test_campaign_full_flow_execution_replay_integrity_with_transition_world(
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


class TestTransitionActivity:
    def test_successful_declaration_appends_exactly_one_event(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        before = activity(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(),
        )
        assert response.status_code == 201
        feed = activity(client)
        assert feed["latest_sequence"] == before["latest_sequence"] + 1
        assert [e["kind"] for e in feed["events"]][-1] == "domain_state_transition_declared"
        event = feed["events"][-1]
        assert event["scenario_id"] == "scenario-1"
        assert event["manifest_id"] == "manifest-1"
        assert event["binding_id"].startswith("binding-")
        assert event["payload"]["state_model_id"] == "state-model-1"
        assert event["payload"]["transition_id"] == "transition-1"
        assert len(event["payload"]["content_hash"]) == 64
        assert event["payload"]["guard_field_count"] == 1
        assert event["payload"]["target_field_count"] == 2

    def test_activity_payload_never_exposes_transition_content(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        response = client.post(
            "/v1/scenarios/scenario-1/domain-state-transitions",
            headers=HEADERS,
            json=transition_payload(
                transition_id="t-secret",
                description="secret description text",
                guard_values={"extra": {"reserve": "gold"}},
                target_values={"status": "silver", "extra": {"marker": "platinum"}},
                metadata={"owner": "confidential-owner"},
            ),
        )
        assert response.status_code == 201
        feed = activity(client)
        serialized = json.dumps(feed)
        for secret in (
            "secret description text",
            "reserve",
            "gold",
            "silver",
            "platinum",
            "confidential-owner",
        ):
            assert secret not in serialized

    def test_rejected_declarations_append_nothing(self, client: TestClient) -> None:
        setup_bound_scenario(client)
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers=HEADERS,
                json=transition_payload(),
            ).status_code
            == 201
        )
        feed = activity(client)
        assert feed["latest_sequence"] == 4  # scenario, manifest, binding, state model, transition
        # Duplicate (409).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers=HEADERS,
                json=transition_payload(),
            ).status_code
            == 409
        )
        # Invalid values (422).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers=HEADERS,
                json=transition_payload(transition_id="t-bad", target_values={"ghost-field": 1}),
            ).status_code
            == 422
        )
        # Foreign tenant (404).
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers={"X-Tenant-ID": "tenant-other"},
                json=transition_payload(transition_id="t-foreign"),
            ).status_code
            == 404
        )
        after = activity(client)
        assert after == feed
        assert [e["kind"] for e in after["events"]][-1] == "domain_state_transition_declared"

    def test_tenants_are_isolated_in_activity(self, client: TestClient) -> None:
        setup_bound_scenario(client, tenant_id="tenant-a")
        assert (
            client.post(
                "/v1/scenarios/scenario-1/domain-state-transitions",
                headers={"X-Tenant-ID": "tenant-a"},
                json=transition_payload(),
            ).status_code
            == 201
        )
        feed_b = activity(client, tenant_id="tenant-b")
        assert feed_b == {"events": [], "next_after_sequence": -1, "latest_sequence": -1}
