"""Phase 25 API tests: runtime-3 route assembly, recorded-runtime dispatch, and gates.

Proves the assembled Phase 25 API surface: exactly six new paths and
seven OpenAPI operations with direct runtime-3 contract references; the
request-version preparation dispatch (1.0.0/2.0.0 historical, 3.0.0
realization-aware, unsupported -> 409 with zero reads/LEGION/writes);
the recorded-version execution and replay dispatch (exactly one
appropriate implementation invoked, exactly one activity event only
after success); the seven runtime-2 artifact endpoints rejecting
recorded runtime-3 records with the safe 409 before their runtime-2
services are invoked; every new runtime-3 endpoint rejecting recorded
1.0.0/2.0.0/injected-unsupported runtimes with the safe 409 before any
artifact access or build; tenant isolation (typed 404); strict GET
read-only behavior; the observation POST writing only the observation
set with no activity event; missing/corrupted/tampered runtime-3
artifacts preserving the typed 404/409 conflict/409 integrity mappings
without leaking tenant ids, hashes, state values, guards, targets,
policies, observations, statistics, or internal reasons; and
POST /verify-inputs working unchanged for runtime 3.0.0.

Fixtures reuse the existing Phase 25 helpers and real public services;
private store mutation is used only for explicit corruption and
unsupported-runtime adversarial fixtures and is clearly marked
test-only at each site.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, cast
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.campaign_metric_observation_query_service import (
    get_verified_campaign_metric_observation_matrix,
)
from kalhas.application.campaign_metric_statistics_query_service import (
    get_verified_campaign_metric_statistics,
)
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import MAX_ACTIVITY_LIMIT, InMemoryScenarioStore
from kalhas.application.operational_activity import list_activity
from kalhas.application.realization_execution import (
    execute_realization_campaign as _realization_execute,
)
from kalhas.application.realization_replay import (
    replay_realization_run as _realization_replay,
)
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.replay_service import replay_run as _historical_replay
from kalhas.application.run_metric_observation_service import (
    extract_run_metric_observations,
    get_verified_run_metric_observation_set,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign as _structural_execute
from kalhas.application.trajectory_query_service import (
    get_verified_run_trajectory_execution,
    get_verified_run_trajectory_replay_manifest,
)
from kalhas.contracts.v1.activity import OperationalActivityKind
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.execution import ReplayManifest, RunState
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import NOW, TENANT, build_request
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase21_helpers import complete_observation_campaign
from tests.phase24_helpers import declare_model, uncertainty_fields
from tests.phase25_helpers import (
    _TRANSITION_GUARD,
    _TRANSITION_ID,
    _TRANSITION_TARGET,
    RUNTIME_THREE_SEEDS,
    inject_unsupported_recorded_runtime,
    level_binding,
    runtime_three_observation_store,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"

RUN_EXECUTION_PATH = "/v1/runs/{run_id}/realization-trajectory-execution"
RUN_REPLAY_MANIFEST_PATH = "/v1/runs/{run_id}/realization-trajectory-replay-manifest"
RUN_OBSERVATIONS_PATH = "/v1/runs/{run_id}/realization-metric-observations"
CAMPAIGN_TRAJECTORY_MATRIX_PATH = "/v1/campaigns/{campaign_id}/realization-trajectory-matrix"
CAMPAIGN_OBSERVATION_MATRIX_PATH = (
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix"
)
CAMPAIGN_STATISTICS_PATH = "/v1/campaigns/{campaign_id}/realization-metric-statistics"

EXPECTED_NEW_PATHS: dict[str, set[str]] = {
    RUN_EXECUTION_PATH: {"get"},
    RUN_REPLAY_MANIFEST_PATH: {"get"},
    RUN_OBSERVATIONS_PATH: {"get", "post"},
    CAMPAIGN_TRAJECTORY_MATRIX_PATH: {"get"},
    CAMPAIGN_OBSERVATION_MATRIX_PATH: {"get"},
    CAMPAIGN_STATISTICS_PATH: {"get"},
}

#: Exact runtime-3 contract referenced by each new operation.
EXPECTED_REF_SCHEMAS: dict[tuple[str, str], str] = {
    (RUN_EXECUTION_PATH, "get"): "RealizationRunTrajectoryExecution",
    (RUN_REPLAY_MANIFEST_PATH, "get"): "RealizationRunTrajectoryReplayManifest",
    (RUN_OBSERVATIONS_PATH, "post"): "RealizationRunMetricObservationSet",
    (RUN_OBSERVATIONS_PATH, "get"): "RealizationRunMetricObservationSet",
    (CAMPAIGN_TRAJECTORY_MATRIX_PATH, "get"): "RealizationCampaignTrajectoryMatrix",
    (CAMPAIGN_OBSERVATION_MATRIX_PATH, "get"): "RealizationCampaignMetricObservationMatrix",
    (CAMPAIGN_STATISTICS_PATH, "get"): "RealizationCampaignMetricStatisticsMatrix",
}

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _store(client: TestClient) -> InMemoryScenarioStore:
    return cast(InMemoryScenarioStore, _app(client).state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    _app(client).state.store = store


def _install_compiled_world(
    client: TestClient, *, bindings: bool = True
) -> tuple[InMemoryScenarioStore, str]:
    """A scenario/pack/model/bindings/uncertainty/transition world (no campaign).

    Everything before campaign preparation is built through the real
    services, mirroring the Phase 25 helper fixture exactly; the campaign
    itself is intentionally not prepared so the HTTP preparation endpoint
    under test performs it.
    """
    store = InMemoryScenarioStore()
    store.put_scenario(build_observation_scenario())
    _register_pack(store)
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=uncertainty_fields(),
        declared_at=DECLARED_AT,
    )
    if bindings:
        declare_domain_metric_observation(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-1",
            state_field_id="level",
            declared_at=DECLARED_AT,
        )
        declare_domain_metric_observation(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-2",
            state_field_id="ratio",
            declared_at=DECLARED_AT,
        )
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id=_TRANSITION_ID,
        ),
        tenant_id=state_model.tenant_id,
        scenario_id=state_model.scenario_id,
        binding_id=state_model.binding_id,
        manifest_id=state_model.manifest_id,
        pack_id=state_model.pack_id,
        pack_version=state_model.pack_version,
        manifest_content_hash=state_model.manifest_content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=_TRANSITION_ID,
        description="Declared state change",
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    _install_store(client, store)
    return store, compiled.version.identifier


def _campaign_payload(world_version_id: str, *, runtime_version: str) -> dict[str, Any]:
    return {
        "campaign_id": "campaign-1",
        "campaign_name": "Phase 25 API campaign",
        "scenario_id": "scenario-1",
        "world_version_id": world_version_id,
        "strategy_request": build_request(TENANT).model_dump(mode="json"),
        "seed_ensemble": [seed.model_dump(mode="json") for seed in RUNTIME_THREE_SEEDS],
        "runtime_version": runtime_version,
        "created_at": NOW.isoformat(),
    }


def _run_ids(store: InMemoryScenarioStore) -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, "campaign-1"))


def _snapshot(store: InMemoryScenarioStore) -> dict[str, Any]:
    return copy.deepcopy(store.__dict__)


def _prepare_trajectory_plans(client: TestClient) -> None:
    prepare_strategy_trajectory_plans(
        store=_store(client),
        legion=cast(MockLegionAdapter, _app(client).state.mock_legion),
        tenant_id=TENANT,
        campaign_id="campaign-1",
    )


def _assert_error_shape(
    response: Any,
    status: int,
    code: str,
    *,
    leak_scan: bool = True,
) -> None:
    """Assert the typed safe error body and run the no-leak scan."""
    assert response.status_code == status
    body = response.json()
    ApiErrorResponse.model_validate(body)
    assert body["code"] == code
    assert body["request_id"]
    if leak_scan:
        _assert_no_leak(body)


def _assert_no_leak(body: dict[str, Any]) -> None:
    """The error body must not leak hashes, foreign ids, values, or reasons.

    The requesting run/campaign identifiers are caller-known and appear
    in the established generic messages; anything else is forbidden.
    """
    serialized = json.dumps(body)
    assert not _HASH_PATTERN.search(serialized), "error body leaks a content hash"
    for forbidden in (
        OTHER_TENANT,
        "content_hash",
        "metadata",
        "seed-1",
        "seed-2",
        "mock-baseline",
    ):
        assert forbidden not in serialized, f"error body leaks {forbidden!r}: {serialized}"
    # Whole-word checks: field names, state values, guards, targets, and
    # policies must never appear as words inside the generic messages.
    for word in (
        "reason",
        "idle",
        "active",
        "level",
        "ratio",
        "guard",
        "target",
        "policy",
        "sampled",
        "realized",
    ):
        assert not re.search(rf"\b{word}\b", serialized), f"error body leaks {word!r}: {serialized}"


def _activity_kinds(store: InMemoryScenarioStore) -> list[str]:
    return [event.kind.value for event in list_activity(store, TENANT, limit=MAX_ACTIVITY_LIMIT)]


def _activity_count(store: InMemoryScenarioStore, kind: OperationalActivityKind) -> int:
    return sum(
        1 for event in list_activity(store, TENANT, limit=MAX_ACTIVITY_LIMIT) if event.kind is kind
    )


class _CountingLegion:
    """A counting wrapper over the mock LEGION adapter (test-only spy)."""

    def __init__(self, inner: MockLegionAdapter) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attr(*args, **kwargs)

        return wrapper


class _CountingStore:
    """A counting wrapper over the store (test-only spy for zero-read proofs)."""

    def __init__(self, inner: InMemoryScenarioStore) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attr(*args, **kwargs)

        return wrapper


class TestOpenApiSurface:
    def test_exactly_six_new_paths_and_seven_operations(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        new_paths = {path: set(ops) for path, ops in paths.items() if "realization-" in path}
        assert new_paths == EXPECTED_NEW_PATHS
        operation_count = sum(len(ops) for ops in EXPECTED_NEW_PATHS.values())
        assert operation_count == 7
        # POST and GET share exactly one path: the observation extraction path.
        shared = {p for p, ops in EXPECTED_NEW_PATHS.items() if len(ops) == 2}
        assert shared == {RUN_OBSERVATIONS_PATH}

    def test_each_new_operation_refs_its_runtime_three_contract(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        for (path, method), schema_name in EXPECTED_REF_SCHEMAS.items():
            responses = paths[path][method]["responses"]
            status = "201" if method == "post" else "200"
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            assert ref == f"#/components/schemas/{schema_name}", (path, method, ref)

    def test_existing_runtime_two_refs_unchanged(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        assert (
            paths["/v1/runs/{run_id}/trajectory-execution"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/RunTrajectoryExecution"
        )
        assert (
            paths["/v1/runs/{run_id}/metric-observations"]["post"]["responses"]["201"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/RunMetricObservationSet"
        )
        assert (
            paths["/v1/campaigns/{campaign_id}/trajectory-matrix"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/CampaignTrajectoryMatrix"
        )


class TestRequestVersionDispatch:
    @pytest.mark.parametrize("runtime_version", ["1.0.0", "2.0.0"])
    def test_v1_and_v2_use_historical_preparation(
        self, client: TestClient, runtime_version: str
    ) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        response = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=_campaign_payload(world_id, runtime_version=runtime_version),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"]["state"] == "compiled"
        plans = store.get_run_plans(TENANT, "campaign-1")
        assert plans
        assert all(plan.runtime_version == runtime_version for plan in plans)
        # Exactly one campaign-prepared activity event, recorded only after success.
        assert _activity_kinds(store) == [OperationalActivityKind.CAMPAIGN_PREPARED.value]

    def test_v3_preparation_uses_realization_path(self, client: TestClient) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        response = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=_campaign_payload(world_id, runtime_version="3.0.0"),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"]["state"] == "compiled"
        plans = store.get_run_plans(TENANT, "campaign-1")
        assert plans
        assert all(plan.runtime_version == "3.0.0" for plan in plans)
        # Runtime-3 plans bind the realization content hash into the input hash:
        # the input hash differs from the runtime-2 digest for the same run.
        assert all(plan.input_hash and len(plan.input_hash) == 64 for plan in plans)
        assert _activity_kinds(store) == [OperationalActivityKind.CAMPAIGN_PREPARED.value]

    def test_unsupported_request_version_409_no_reads_no_legion_no_writes(
        self, client: TestClient
    ) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        inner = store
        _install_store(client, cast(InMemoryScenarioStore, _CountingStore(inner)))
        counting = cast(_CountingStore, _store(client))
        _app(client).state.mock_legion = _CountingLegion(MockLegionAdapter())
        legion = cast(_CountingLegion, _app(client).state.mock_legion)
        before = _snapshot(inner)
        response = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=_campaign_payload(world_id, runtime_version="9.9.9"),
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        assert counting.calls == [], (
            f"unsupported request version performed store reads: {counting.calls}"
        )
        assert legion.calls == [], f"unsupported request version called LEGION: {legion.calls}"
        assert _snapshot(inner) == before
        assert _activity_kinds(inner) == []


class TestRecordedRuntimeDispatch:
    def _runtime_two_executed_store(self, client: TestClient) -> InMemoryScenarioStore:
        store, world_id = _install_compiled_world(client, bindings=False)
        response = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=_campaign_payload(world_id, runtime_version="2.0.0"),
        )
        assert response.status_code == 201
        _prepare_trajectory_plans(client)
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        return store

    def test_execute_runtime_two_invokes_historical_service_exactly_once(
        self, client: TestClient
    ) -> None:
        store = self._runtime_two_executed_store(client)
        with (
            mock.patch(
                "kalhas.api.routes.execute_campaign", wraps=_structural_execute
            ) as historical,
            mock.patch(
                "kalhas.api.routes.execute_realization_campaign", wraps=_realization_execute
            ) as realization,
        ):
            response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert len(body["run_statuses"]) == len(_run_ids(store))
        assert all(status["state"] == "complete" for status in body["run_statuses"])
        assert historical.call_count == 1
        assert realization.call_count == 0
        # The runtime-2 execution collection is written; the runtime-3 collection is not.
        assert store._run_trajectory_executions
        assert not store._realization_run_trajectory_executions
        assert _activity_count(store, OperationalActivityKind.CAMPAIGN_EXECUTED) == 1

    def test_execute_runtime_three_invokes_realization_service_exactly_once(
        self, client: TestClient
    ) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=_campaign_payload(world_id, runtime_version="3.0.0"),
            ).status_code
            == 201
        )
        _prepare_trajectory_plans(client)
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        with (
            mock.patch(
                "kalhas.api.routes.execute_campaign", wraps=_structural_execute
            ) as historical,
            mock.patch(
                "kalhas.api.routes.execute_realization_campaign", wraps=_realization_execute
            ) as realization,
        ):
            response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert len(body["run_statuses"]) == len(_run_ids(store))
        assert all(status["state"] == "complete" for status in body["run_statuses"])
        assert historical.call_count == 0
        assert realization.call_count == 1
        assert not store._run_trajectory_executions
        assert store._realization_run_trajectory_executions
        assert _activity_count(store, OperationalActivityKind.CAMPAIGN_EXECUTED) == 1

    def test_execute_unsupported_recorded_runtime_409_no_writes(self, client: TestClient) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=_campaign_payload(world_id, runtime_version="3.0.0"),
            ).status_code
            == 201
        )
        _prepare_trajectory_plans(client)
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        plans = store.get_run_plans(TENANT, "campaign-1")
        # TEST-ONLY private-store mutation: re-stamp one recorded plan and its
        # matching run status with an unsupported runtime (adversarial fixture).
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        before = _snapshot(store)
        with (
            mock.patch(
                "kalhas.api.routes.execute_campaign", wraps=_structural_execute
            ) as historical,
            mock.patch(
                "kalhas.api.routes.execute_realization_campaign", wraps=_realization_execute
            ) as realization,
        ):
            response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        assert historical.call_count == 0
        assert realization.call_count == 0
        assert _snapshot(store) == before
        assert _activity_count(store, OperationalActivityKind.CAMPAIGN_EXECUTED) == 0

    def test_replay_runtime_two_invokes_historical_service_exactly_once(
        self, client: TestClient
    ) -> None:
        store = self._runtime_two_executed_store(client)
        assert client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS).status_code == 200
        run_id = _run_ids(store)[0]
        with (
            mock.patch("kalhas.api.routes.replay_run", wraps=_historical_replay) as historical,
            mock.patch(
                "kalhas.api.routes.replay_realization_run", wraps=_realization_replay
            ) as realization,
        ):
            response = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert response.status_code == 200
        ReplayManifest.model_validate(response.json())
        assert historical.call_count == 1
        assert realization.call_count == 0
        store.get_replay_manifest(TENANT, run_id)
        assert not store._realization_run_trajectory_replay_manifests
        assert _activity_count(store, OperationalActivityKind.RUN_REPLAYED) == 1

    def test_replay_runtime_three_invokes_realization_service_exactly_once(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        # Explicit observation extraction is required before runtime-3 replay.
        assert (
            client.post(
                f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS
            ).status_code
            == 201
        )
        with (
            mock.patch("kalhas.api.routes.replay_run", wraps=_historical_replay) as historical,
            mock.patch(
                "kalhas.api.routes.replay_realization_run", wraps=_realization_replay
            ) as realization,
        ):
            response = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert response.status_code == 200
        manifest = ReplayManifest.model_validate(response.json())
        assert manifest.runtime_version == "3.0.0"
        assert historical.call_count == 0
        assert realization.call_count == 1
        # The manifest pair (generic + runtime-3) is written.
        store.get_replay_manifest(TENANT, run_id)
        store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert _activity_count(store, OperationalActivityKind.RUN_REPLAYED) == 1

    def test_replay_unsupported_recorded_runtime_409_no_writes(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # TEST-ONLY private-store mutation: unsupported recorded runtime fixture.
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        before = _snapshot(store)
        with (
            mock.patch("kalhas.api.routes.replay_run", wraps=_historical_replay) as historical,
            mock.patch(
                "kalhas.api.routes.replay_realization_run", wraps=_realization_replay
            ) as realization,
        ):
            response = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        assert historical.call_count == 0
        assert realization.call_count == 0
        assert _snapshot(store) == before
        assert _activity_count(store, OperationalActivityKind.RUN_REPLAYED) == 0


class TestRuntimeThreeLifecycle:
    def test_full_runtime_three_http_lifecycle(self, client: TestClient) -> None:
        store, world_id = _install_compiled_world(client)
        prepared = client.post(
            "/v1/campaigns",
            headers=HEADERS,
            json=_campaign_payload(world_id, runtime_version="3.0.0"),
        )
        assert prepared.status_code == 201
        assert prepared.json()["status"]["state"] == "compiled"
        _prepare_trajectory_plans(client)
        started = client.post(
            "/v1/campaigns/campaign-1/start", headers=HEADERS, json={"changed_at": NOW.isoformat()}
        )
        assert started.status_code == 200
        assert started.json()["state"] == "running"
        executed = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        assert executed.status_code == 200
        run_ids = _run_ids(store)
        assert len(run_ids) == 10  # 5 strategies x 2 seeds
        for run_id in run_ids:
            status = store.get_run_status(TENANT, run_id)
            assert status.state is RunState.COMPLETE
            store.get_realization_run_trajectory_execution(TENANT, run_id)

        # Explicit observation extraction for every run (required before replay
        # and by both observation matrices).
        for run_id in run_ids:
            extracted = client.post(
                f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS
            )
            assert extracted.status_code == 201, extracted.text
            RealizationRunMetricObservationSet.model_validate(extracted.json())

        run_id = run_ids[0]
        execution = client.get(
            f"/v1/runs/{run_id}/realization-trajectory-execution", headers=HEADERS
        )
        assert execution.status_code == 200
        execution_contract = RealizationRunTrajectoryExecution.model_validate(execution.json())
        assert execution_contract.runtime_version == "3.0.0"

        observation = client.get(
            f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS
        )
        assert observation.status_code == 200
        RealizationRunMetricObservationSet.model_validate(observation.json())

        replayed = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS)
        assert replayed.status_code == 200
        assert ReplayManifest.model_validate(replayed.json()).runtime_version == "3.0.0"

        replay_manifest = client.get(
            f"/v1/runs/{run_id}/realization-trajectory-replay-manifest", headers=HEADERS
        )
        assert replay_manifest.status_code == 200
        RealizationRunTrajectoryReplayManifest.model_validate(replay_manifest.json())

        trajectory_matrix = client.get(
            "/v1/campaigns/campaign-1/realization-trajectory-matrix", headers=HEADERS
        )
        assert trajectory_matrix.status_code == 200
        RealizationCampaignTrajectoryMatrix.model_validate(trajectory_matrix.json())

        observation_matrix = client.get(
            "/v1/campaigns/campaign-1/realization-metric-observation-matrix", headers=HEADERS
        )
        assert observation_matrix.status_code == 200
        RealizationCampaignMetricObservationMatrix.model_validate(observation_matrix.json())

        statistics = client.get(
            "/v1/campaigns/campaign-1/realization-metric-statistics", headers=HEADERS
        )
        assert statistics.status_code == 200
        RealizationCampaignMetricStatisticsMatrix.model_validate(statistics.json())

        verified = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert verified.status_code == 200
        assert verified.json()["runtime_version"] == "3.0.0"


class TestRuntimeTwoArtifactGates:
    """Recorded runtime-3 records are rejected on the seven runtime-2 endpoints."""

    @staticmethod
    def _runtime_two_endpoints() -> list[tuple[str, str, str]]:
        """(label, method, path-template) for the seven runtime-2 artifact endpoints."""
        return [
            ("trajectory-execution", "get", "/v1/runs/{run_id}/trajectory-execution"),
            ("trajectory-replay-manifest", "get", "/v1/runs/{run_id}/trajectory-replay-manifest"),
            ("metric-observations post", "post", "/v1/runs/{run_id}/metric-observations"),
            ("metric-observations get", "get", "/v1/runs/{run_id}/metric-observations"),
            ("trajectory-matrix", "get", "/v1/campaigns/{campaign_id}/trajectory-matrix"),
            (
                "metric-observation-matrix",
                "get",
                "/v1/campaigns/{campaign_id}/metric-observation-matrix",
            ),
            ("metric-statistics", "get", "/v1/campaigns/{campaign_id}/metric-statistics"),
        ]

    def test_all_seven_runtime_two_endpoints_reject_runtime_three_record(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        patches = [
            mock.patch(
                "kalhas.api.routes.get_verified_run_trajectory_execution",
                wraps=get_verified_run_trajectory_execution,
            ),
            mock.patch(
                "kalhas.api.routes.get_verified_run_trajectory_replay_manifest",
                wraps=get_verified_run_trajectory_replay_manifest,
            ),
            mock.patch(
                "kalhas.api.routes.extract_run_metric_observations",
                wraps=extract_run_metric_observations,
            ),
            mock.patch(
                "kalhas.api.routes.get_verified_run_metric_observation_set",
                wraps=get_verified_run_metric_observation_set,
            ),
            mock.patch(
                "kalhas.api.routes.get_verified_campaign_trajectory_matrix",
                wraps=get_verified_campaign_trajectory_matrix,
            ),
            mock.patch(
                "kalhas.api.routes.get_verified_campaign_metric_observation_matrix",
                wraps=get_verified_campaign_metric_observation_matrix,
            ),
            mock.patch(
                "kalhas.api.routes.get_verified_campaign_metric_statistics",
                wraps=get_verified_campaign_metric_statistics,
            ),
        ]
        spies = [patch.start() for patch in patches]
        try:
            for _label, method, template in self._runtime_two_endpoints():
                path = template.format(run_id=run_id, campaign_id="campaign-1")
                response = client.request(method, path, headers=HEADERS)
                _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        finally:
            for patch in patches:
                patch.stop()
        for spy in spies:
            assert spy.call_count == 0, "a runtime-2 service was invoked for a runtime-3 record"

    def test_runtime_two_endpoints_still_serve_runtime_two_records(
        self, client: TestClient
    ) -> None:
        store, world_id = _install_compiled_world(client, bindings=True)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=_campaign_payload(world_id, runtime_version="2.0.0"),
            ).status_code
            == 201
        )
        _prepare_trajectory_plans(client)
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        assert client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS).status_code == 200
        run_id = _run_ids(store)[0]
        execution = client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS)
        assert execution.status_code == 200
        assert execution.json()["runtime_version"] == "2.0.0"
        extracted = client.post(f"/v1/runs/{run_id}/metric-observations", headers=HEADERS)
        assert extracted.status_code == 201
        matrix = client.get("/v1/campaigns/campaign-1/trajectory-matrix", headers=HEADERS)
        assert matrix.status_code == 200
        assert matrix.json()["runtime_version"] == "2.0.0"

    def test_runtime_two_endpoints_legacy_runtime_one_behavior_unchanged(
        self, client: TestClient
    ) -> None:
        store, world_id = _install_compiled_world(client, bindings=False)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=_campaign_payload(world_id, runtime_version="1.0.0"),
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        assert client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS).status_code == 200
        run_id = _run_ids(store)[0]
        # Legacy runs have no trajectory artifact: historical typed 404.
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/trajectory-execution", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )


class TestRuntimeThreeEndpointsGates:
    """Non-3.0.0 recorded runtimes are rejected on all seven new endpoints."""

    @staticmethod
    def _runtime_three_endpoints() -> list[tuple[str, str, str]]:
        return [
            ("execution get", "get", RUN_EXECUTION_PATH),
            ("replay manifest get", "get", RUN_REPLAY_MANIFEST_PATH),
            ("observations post", "post", RUN_OBSERVATIONS_PATH),
            ("observations get", "get", RUN_OBSERVATIONS_PATH),
            ("trajectory matrix", "get", CAMPAIGN_TRAJECTORY_MATRIX_PATH),
            ("observation matrix", "get", CAMPAIGN_OBSERVATION_MATRIX_PATH),
            ("statistics", "get", CAMPAIGN_STATISTICS_PATH),
        ]

    def test_all_new_endpoints_reject_runtime_two_record_before_service(
        self, client: TestClient
    ) -> None:
        store, _world_id, run_ids = complete_observation_campaign()
        _install_store(client, store)
        run_id = run_ids[0]
        # The private route helpers own the recorded-runtime gate and must
        # stay real: they raise the typed 409 before any downstream
        # operation. Only the dependencies invoked after the gate are
        # spied on, proving none of them runs for a non-3.0.0 record.
        patches = [
            mock.patch("kalhas.api.routes_realization.verify_run_trajectory_inputs"),
            mock.patch("kalhas.api.routes_realization.extract_realization_run_metric_observations"),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_run_metric_observation_set"
            ),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_trajectory_matrix"
            ),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_metric_observation_matrix"
            ),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_metric_statistics"
            ),
        ]
        spies = [patch.start() for patch in patches]
        try:
            for _label, method, template in self._runtime_three_endpoints():
                path = template.format(run_id=run_id, campaign_id="campaign-1")
                response = client.request(method, path, headers=HEADERS)
                _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        finally:
            for patch in patches:
                patch.stop()
        for spy in spies:
            assert spy.call_count == 0, (
                "a runtime-3 downstream operation ran for a recorded runtime-2 record"
            )

    def test_all_new_endpoints_reject_legacy_runtime_one_record(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # TEST-ONLY private-store mutation: re-stamp one run to recorded 1.0.0 in
        # both its plan and its status (adversarial foreign-state fixture).
        run_id = run_identifier(plans[0])
        store._run_plans[(TENANT, "campaign-1")] = tuple(
            plan.model_copy(update={"runtime_version": "1.0.0"})
            if plan.identifier == plans[0].identifier
            else plan
            for plan in store.get_run_plans(TENANT, "campaign-1")
        )
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(TENANT, run_id, status.model_copy(update={"runtime_version": "1.0.0"}))
        for _label, method, template in self._runtime_three_endpoints():
            path = template.format(run_id=run_id, campaign_id="campaign-1")
            response = client.request(method, path, headers=HEADERS)
            _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_all_new_endpoints_reject_injected_unsupported_runtime(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # TEST-ONLY private-store mutation: unsupported recorded runtime fixture.
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        for _label, method, template in self._runtime_three_endpoints():
            path = template.format(run_id=run_id, campaign_id="campaign-1")
            response = client.request(method, path, headers=HEADERS)
            _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)


class TestTenantIsolation:
    def test_foreign_tenant_run_endpoint_is_typed_404(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        response = client.get(
            f"/v1/runs/{run_id}/realization-trajectory-execution",
            headers={"X-Tenant-ID": OTHER_TENANT},
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_foreign_tenant_campaign_endpoint_is_typed_404(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        response = client.get(
            "/v1/campaigns/campaign-1/realization-trajectory-matrix",
            headers={"X-Tenant-ID": OTHER_TENANT},
        )
        _assert_error_shape(response, 404, ErrorCode.NOT_FOUND.value, leak_scan=False)

    def test_unknown_run_and_campaign_are_typed_404(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        _assert_error_shape(
            client.get("/v1/runs/run-ghost/realization-trajectory-execution", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        _assert_error_shape(
            client.get(
                "/v1/campaigns/campaign-ghost/realization-metric-statistics", headers=HEADERS
            ),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )


class TestReadOnlyGets:
    def test_all_six_gets_are_strictly_read_only(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_ids = _run_ids(store)
        # Fixture setup through the real services: explicit extraction for
        # every run (required by the observation matrix and replay) and one
        # exact replay (required by the replay-manifest GET).
        for run_id in run_ids:
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        run_id = run_ids[0]
        _realization_replay(store=store, tenant_id=TENANT, run_id=run_id)
        before = _snapshot(store)
        activity_before = _activity_kinds(store)
        endpoints = [
            ("get", RUN_EXECUTION_PATH),
            ("get", RUN_REPLAY_MANIFEST_PATH),
            ("get", RUN_OBSERVATIONS_PATH),
            ("get", CAMPAIGN_TRAJECTORY_MATRIX_PATH),
            ("get", CAMPAIGN_OBSERVATION_MATRIX_PATH),
            ("get", CAMPAIGN_STATISTICS_PATH),
        ]
        for method, template in endpoints:
            path = template.format(run_id=run_id, campaign_id="campaign-1")
            for _ in range(2):
                response = client.request(method, path, headers=HEADERS)
                assert response.status_code == 200, (template, response.text)
        assert _snapshot(store) == before
        assert _activity_kinds(store) == activity_before


class TestObservationExtractionWrites:
    def test_extraction_writes_only_the_observation_set_and_no_activity(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        before = _snapshot(store)
        assert _activity_kinds(store) == []
        response = client.post(
            f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS
        )
        assert response.status_code == 201
        RealizationRunMetricObservationSet.model_validate(response.json())
        after = _snapshot(store)
        changed = {
            key
            for key in set(before) | set(after)
            if key == "_realization_run_metric_observation_sets"
            or before.get(key) != after.get(key)
        }
        assert changed == {"_realization_run_metric_observation_sets"}
        assert (TENANT, run_id) in after["_realization_run_metric_observation_sets"]
        assert _activity_kinds(store) == []

    def test_second_extraction_is_409_and_never_overwrites(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        first = client.post(f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS)
        assert first.status_code == 201
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        second = client.post(f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS)
        _assert_error_shape(second, 409, ErrorCode.CONFLICT.value)
        assert store.get_realization_run_metric_observation_set(TENANT, run_id).model_dump(
            mode="json"
        ) == stored.model_dump(mode="json")
        assert _activity_kinds(store) == []


class TestTamperedArtifactsAndLeaks:
    def test_missing_execution_returns_typed_404(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        # TEST-ONLY private-store mutation: simulate a missing artifact record.
        del store._realization_run_trajectory_executions[(TENANT, run_id)]
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/realization-trajectory-execution", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        # The trajectory matrix requires every execution: typed 409 integrity.
        _assert_error_shape(
            client.get("/v1/campaigns/campaign-1/realization-trajectory-matrix", headers=HEADERS),
            409,
            ErrorCode.INTEGRITY_ERROR.value,
        )

    def test_tampered_execution_returns_409_integrity_without_leaks(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        stored = store.get_realization_run_trajectory_execution(TENANT, run_id)
        # TEST-ONLY private-store mutation: tampered content hash fixture.
        store._realization_run_trajectory_executions[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "1" * 64}
        )
        response = client.get(
            f"/v1/runs/{run_id}/realization-trajectory-execution", headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)

    def test_missing_observation_set_blocks_replay_and_matrix_with_typed_errors(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        # TEST-ONLY private-store mutation: simulate a missing observation record.
        del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        # Runtime-3 replay requires explicit prior extraction: typed 404, zero
        # manifests written.
        before = _snapshot(store)
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )
        assert _snapshot(store) == before
        _assert_error_shape(
            client.get(
                "/v1/campaigns/campaign-1/realization-metric-observation-matrix", headers=HEADERS
            ),
            409,
            ErrorCode.INTEGRITY_ERROR.value,
        )
        _assert_error_shape(
            client.get("/v1/campaigns/campaign-1/realization-metric-statistics", headers=HEADERS),
            409,
            ErrorCode.INTEGRITY_ERROR.value,
        )

    def test_tampered_observation_set_returns_409_integrity(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        # TEST-ONLY private-store mutation: tampered content hash fixture.
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "2" * 64}
        )
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/realization-metric-observations", headers=HEADERS),
            409,
            ErrorCode.INTEGRITY_ERROR.value,
        )
        _assert_error_shape(
            client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS),
            409,
            ErrorCode.INTEGRITY_ERROR.value,
        )

    def test_tampered_replay_manifest_returns_409_conflict(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        _realization_replay(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        # TEST-ONLY private-store mutation: tampered content hash fixture (the
        # self-covering recompute then fails).
        store._realization_run_trajectory_replay_manifests[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "3" * 64}
        )
        response = client.get(
            f"/v1/runs/{run_id}/realization-trajectory-replay-manifest", headers=HEADERS
        )
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)

    def test_missing_observation_set_blocks_replay_manifest_get_with_typed_404(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        _realization_replay(store=store, tenant_id=TENANT, run_id=run_id)
        # TEST-ONLY private-store mutation: remove the observation record.
        del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        _assert_error_shape(
            client.get(
                f"/v1/runs/{run_id}/realization-trajectory-replay-manifest", headers=HEADERS
            ),
            404,
            ErrorCode.NOT_FOUND.value,
            leak_scan=False,
        )


class TestVerifyInputsRuntimeThree:
    def test_verify_inputs_works_for_runtime_three_with_manifest_and_activity(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        run_id = _run_ids(store)[0]
        first = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert first.status_code == 200
        body = first.json()
        assert body["runtime_version"] == "3.0.0"
        assert body["verification_classification"] == "exact"
        assert len(body["recomputed_input_hash"]) == 64
        stored = store.get_input_integrity_manifest(TENANT, run_id)
        assert stored.model_dump(mode="json") == body
        assert _activity_count(store, OperationalActivityKind.RUN_INPUTS_VERIFIED) == 1
        # Repeated verification keeps the identical behavior and records again.
        second = client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS)
        assert second.status_code == 200
        assert second.json() == body
        assert _activity_count(store, OperationalActivityKind.RUN_INPUTS_VERIFIED) == 2

    def test_verify_inputs_unsupported_recorded_runtime_409(self, client: TestClient) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        plans = store.get_run_plans(TENANT, "campaign-1")
        # TEST-ONLY private-store mutation: unsupported recorded runtime fixture.
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        _assert_error_shape(
            client.post(f"/v1/runs/{run_id}/verify-inputs", headers=HEADERS),
            409,
            ErrorCode.CONFLICT.value,
        )


class TestEmptyPlanFailClosed:
    """An empty stored plan tuple fails closed with a safe typed 409.

    A campaign whose recorded run-plan tuple is empty has no recorded
    runtime to dispatch on. It must never default to a historical
    execution service or pass a runtime-3 gate vacuously: both the
    execute route and the realization campaign gates reject it with the
    typed unsupported-runtime error (409 conflict) before any execution
    or query service, any artifact access, any write, or any activity
    event.
    """

    @staticmethod
    def _running_runtime_three_store(client: TestClient) -> InMemoryScenarioStore:
        """A RUNNING runtime-3 campaign prepared through the HTTP API."""
        store, world_id = _install_compiled_world(client, bindings=False)
        assert (
            client.post(
                "/v1/campaigns",
                headers=HEADERS,
                json=_campaign_payload(world_id, runtime_version="3.0.0"),
            ).status_code
            == 201
        )
        _prepare_trajectory_plans(client)
        assert (
            client.post(
                "/v1/campaigns/campaign-1/start",
                headers=HEADERS,
                json={"changed_at": NOW.isoformat()},
            ).status_code
            == 200
        )
        return store

    def test_empty_plan_tuple_cannot_execute(self, client: TestClient) -> None:
        store = self._running_runtime_three_store(client)
        # TEST-ONLY private-store mutation: empty recorded plan tuple.
        store._run_plans[(TENANT, "campaign-1")] = ()
        before = _snapshot(store)
        with (
            mock.patch(
                "kalhas.api.routes.execute_campaign", wraps=_structural_execute
            ) as historical,
            mock.patch(
                "kalhas.api.routes.execute_realization_campaign", wraps=_realization_execute
            ) as realization,
        ):
            response = client.post("/v1/campaigns/campaign-1/execute", headers=HEADERS)
        _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        assert historical.call_count == 0
        assert realization.call_count == 0
        assert _snapshot(store) == before
        assert _activity_count(store, OperationalActivityKind.CAMPAIGN_EXECUTED) == 0

    def test_empty_plan_tuple_cannot_reach_realization_campaign_queries(
        self, client: TestClient
    ) -> None:
        store = runtime_three_observation_store()
        _install_store(client, store)
        # TEST-ONLY private-store mutation: empty recorded plan tuple.
        store._run_plans[(TENANT, "campaign-1")] = ()
        before = _snapshot(store)
        patches = [
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_trajectory_matrix"
            ),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_metric_observation_matrix"
            ),
            mock.patch(
                "kalhas.api.routes_realization.get_verified_realization_campaign_metric_statistics"
            ),
        ]
        spies = [patch.start() for patch in patches]
        try:
            for template in (
                CAMPAIGN_TRAJECTORY_MATRIX_PATH,
                CAMPAIGN_OBSERVATION_MATRIX_PATH,
                CAMPAIGN_STATISTICS_PATH,
            ):
                response = client.get(template.format(campaign_id="campaign-1"), headers=HEADERS)
                _assert_error_shape(response, 409, ErrorCode.CONFLICT.value)
        finally:
            for patch in patches:
                patch.stop()
        for spy in spies:
            assert spy.call_count == 0, "a runtime-3 campaign query ran for an empty plan tuple"
        assert _snapshot(store) == before
        assert _activity_kinds(store) == []
