"""API tests for the Phase 6 domain pack registry endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.domain_pack import DomainPackManifest

NOW = "2026-01-01T12:00:00Z"
TENANT = "tenant-1"
HEADERS = {"X-Tenant-ID": TENANT}


def manifest_payload(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": "manifest-1",
        "pack_id": "pack-1",
        "name": "Reference domain pack",
        "pack_version": "1.2.3",
        "description": "Declarative pack metadata only",
        "supported_api_versions": ["1"],
        "capabilities": [
            {
                "identifier": "cap-1",
                "description": "Declared capability",
                "input_ids": ["in-1"],
                "output_ids": ["out-1"],
                "metadata": {},
            }
        ],
        "schema_metadata": {"declarative": True},
        "created_at": NOW,
        "metadata": {"owner": "foundation"},
    }
    payload.update(overrides)
    return payload


def recompute_hash(manifest: dict[str, Any]) -> str:
    """Recompute the canonical content hash of a returned manifest."""
    payload = dict(manifest)
    payload.pop("content_hash", None)
    return sha256_hex(canonical_json(payload))


class TestRegisterDomainPack:
    def test_register_returns_201_with_computed_manifest(self, client: TestClient) -> None:
        response = client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload())
        assert response.status_code == 201
        manifest = DomainPackManifest.model_validate(response.json())
        assert manifest.pack_id == "pack-1"
        assert manifest.tenant_id == TENANT  # derived from the header
        assert manifest.content_hash == recompute_hash(response.json())
        assert len(manifest.content_hash) == 64

    def test_register_ignores_no_client_supplied_hash_field(self, client: TestClient) -> None:
        # There is no content_hash input at all: a client cannot choose the
        # authoritative hash, not even a matching one.
        payload = manifest_payload(content_hash="f" * 64)
        response = client.post("/v1/domain-packs", headers=HEADERS, json=payload)
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_register_rejects_unknown_fields(self, client: TestClient) -> None:
        payload = manifest_payload()
        payload["tenant_id"] = TENANT  # tenant ownership comes only from the header
        response = client.post("/v1/domain-packs", headers=HEADERS, json=payload)
        assert response.status_code == 422

    def test_register_requires_tenant_header(self, client: TestClient) -> None:
        response = client.post("/v1/domain-packs", json=manifest_payload())
        assert response.status_code == 422

    def test_register_rejects_invalid_semantic_pack_version(self, client: TestClient) -> None:
        response = client.post(
            "/v1/domain-packs", headers=HEADERS, json=manifest_payload(pack_version="1.0")
        )
        assert response.status_code == 422

    def test_register_rejects_missing_api_version_1(self, client: TestClient) -> None:
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(supported_api_versions=["2"]),
        )
        assert response.status_code == 422

    def test_register_rejects_duplicate_capability_identifiers(self, client: TestClient) -> None:
        capability = {
            "identifier": "cap-1",
            "description": "Declared capability",
            "input_ids": [],
            "output_ids": [],
            "metadata": {},
        }
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(capabilities=[capability, capability]),
        )
        assert response.status_code == 422

    def test_duplicate_registration_returns_409_conflict(self, client: TestClient) -> None:
        assert (
            client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload()).status_code
            == 201
        )
        response = client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload())
        assert response.status_code == 409
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.CONFLICT

    def test_same_identifier_in_another_tenant_is_allowed(self, client: TestClient) -> None:
        assert (
            client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload()).status_code
            == 201
        )
        response = client.post(
            "/v1/domain-packs", headers={"X-Tenant-ID": "tenant-2"}, json=manifest_payload()
        )
        assert response.status_code == 201


class TestSupportedApiVersionsValidation:
    """The request boundary enforces the same per-element API-version
    pattern as DomainPackManifest: typed 422, never a 500."""

    def test_mixed_valid_and_invalid_element_returns_typed_422(self, client: TestClient) -> None:
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(supported_api_versions=["1", "invalid"]),
        )
        assert response.status_code == 422
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.parametrize(
        "bad_versions",
        [["1.0"], ["1", "v2"], [""], ["1", "1.0.0"], ["one"], ["1", "2", "3.0"]],
    )
    def test_non_numeric_api_version_elements_return_typed_422(
        self, client: TestClient, bad_versions: list[str]
    ) -> None:
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(supported_api_versions=bad_versions),
        )
        assert response.status_code == 422
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.VALIDATION_ERROR

    def test_valid_single_api_version_remains_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(supported_api_versions=["1"]),
        )
        assert response.status_code == 201
        assert DomainPackManifest.model_validate(response.json()).supported_api_versions == ("1",)

    def test_rejected_registration_stores_no_manifest(self, client: TestClient) -> None:
        for bad_versions in (["1", "invalid"], ["1.0"], [""]):
            response = client.post(
                "/v1/domain-packs",
                headers=HEADERS,
                json=manifest_payload(supported_api_versions=bad_versions),
            )
            assert response.status_code == 422
        listed = client.get("/v1/domain-packs", headers=HEADERS).json()["manifests"]
        assert listed == []
        assert client.get("/v1/domain-packs/manifest-1", headers=HEADERS).status_code == 404


class TestListDomainPacks:
    def test_list_returns_typed_envelope_in_deterministic_order(self, client: TestClient) -> None:
        for identifier in ("manifest-z", "manifest-a", "manifest-m"):
            client.post(
                "/v1/domain-packs",
                headers=HEADERS,
                json=manifest_payload(identifier=identifier, pack_id=f"pack-{identifier}"),
            )
        response = client.get("/v1/domain-packs", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"manifests"}
        identifiers = [manifest["identifier"] for manifest in body["manifests"]]
        assert identifiers == ["manifest-a", "manifest-m", "manifest-z"]

    def test_list_is_tenant_isolated(self, client: TestClient) -> None:
        client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload())
        response = client.get("/v1/domain-packs", headers={"X-Tenant-ID": "tenant-2"})
        assert response.status_code == 200
        assert response.json()["manifests"] == []

    def test_list_requires_tenant_header(self, client: TestClient) -> None:
        assert client.get("/v1/domain-packs").status_code == 422


class TestGetDomainPack:
    def test_get_returns_registered_manifest(self, client: TestClient) -> None:
        client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload())
        response = client.get("/v1/domain-packs/manifest-1", headers=HEADERS)
        assert response.status_code == 200
        manifest = DomainPackManifest.model_validate(response.json())
        assert manifest.identifier == "manifest-1"
        assert manifest.tenant_id == TENANT

    def test_get_unknown_manifest_returns_typed_404(self, client: TestClient) -> None:
        response = client.get("/v1/domain-packs/manifest-ghost", headers=HEADERS)
        assert response.status_code == 404
        assert ApiErrorResponse.model_validate(response.json()).code == ErrorCode.NOT_FOUND

    def test_get_foreign_manifest_returns_typed_404_without_leaking(
        self, client: TestClient
    ) -> None:
        client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload())
        response = client.get("/v1/domain-packs/manifest-1", headers={"X-Tenant-ID": "tenant-2"})
        assert response.status_code == 404
        error = ApiErrorResponse.model_validate(response.json())
        assert error.code == ErrorCode.NOT_FOUND
        assert "tenant-1" not in error.message
        assert "pack-1" not in error.message


class TestNoCrossStateMutation:
    def test_registration_and_retrieval_do_not_mutate_other_state(self, client: TestClient) -> None:
        from tests.test_api_phase5 import first_run_id, prepare_campaign, prepare_world

        world_id = prepare_world(client)
        prepare_campaign(client, world_id)
        client.post("/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW})
        client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        run_id = first_run_id(client)

        # Snapshot every other artifact before any domain-pack operation.
        world_before = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        campaign_before = client.get("/v1/campaigns/campaign-1", headers=HEADERS).json()
        runs_before = client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json()
        run_status_before = client.get(f"/v1/runs/{run_id}", headers=HEADERS).json()
        events_before = client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).json()
        replay_before = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS).json()
        integrity_before = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS).json()

        # Domain-pack operations: register two, list, fetch, miss.
        assert (
            client.post("/v1/domain-packs", headers=HEADERS, json=manifest_payload()).status_code
            == 201
        )
        client.post(
            "/v1/domain-packs",
            headers=HEADERS,
            json=manifest_payload(identifier="manifest-2", pack_id="pack-2"),
        )
        client.get("/v1/domain-packs", headers=HEADERS)
        client.get("/v1/domain-packs/manifest-1", headers=HEADERS)
        client.get("/v1/domain-packs/manifest-ghost", headers=HEADERS)

        # Everything else is unchanged.
        assert client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json() == world_before
        assert client.get("/v1/campaigns/campaign-1", headers=HEADERS).json() == campaign_before
        assert client.get("/v1/campaigns/campaign-1/runs", headers=HEADERS).json() == runs_before
        assert client.get(f"/v1/runs/{run_id}", headers=HEADERS).json() == run_status_before
        assert client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).json() == events_before
        assert client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS).json() == replay_before
        assert (
            client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS).json()
            == integrity_before
        )
