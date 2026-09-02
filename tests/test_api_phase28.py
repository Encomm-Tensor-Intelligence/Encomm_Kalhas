"""Tests for the adaptive run execution API surface (Phase 28, slice 11).

Tests for ``kalhas/api/routes_adaptive_run_execution.py`` - the three
read-only ``adaptive-runs`` GET operations (observations, decisions,
switches) - their registration in ``create_app``, the additive API
error mapping of ``AdaptiveRunTrajectoryExecutionNotFoundError`` (404
``not_found``) and ``AdaptiveRunTrajectoryExecutionIntegrityError``
(409 ``integrity_error``), and the untouched additive public-contract
registration (``PUBLIC_CONTRACTS`` stays at 55 with 55 JSON schema
artifacts). Proves:

- real executed adaptive runs through the real FastAPI app: every 200
  response body equals the canonical stored observation/decision/
  switch sequence exactly (direct verified query, then HTTP array),
  repeated GETs are byte-identical, canonical ordering is preserved,
  and an empty switch sequence is a valid empty JSON array;
- request validation: the required ``X-Tenant-ID`` header;
- tenant isolation: unknown and foreign executions are
  indistinguishable 404 envelopes with identical generic bodies;
- integrity: stored contract corruption and cross-authority corruption
  return the sanitized 409 integrity envelope with no leak of hashes,
  reasons, internals, or foreign identities;
- read-only purity: successful and rejected GETs leave the complete
  store fingerprint and the operational-activity sequence unchanged;
- exact dispatch: each route calls exactly its matching H28-S10 query
  once - and neither of the other two queries;
- OpenAPI: exactly three new paths, GET only, required ``X-Tenant-ID``
  documented on all three, response schemas are arrays whose items
  reference the existing v1 event schemas, unique operation IDs, and
  all earlier paths unchanged;
- wiring: the router is included exactly once in ``create_app``, the
  two error classes are mapped exactly once each, the H28-S10
  production module and its tests are byte-unchanged, prior API
  surfaces and mappings remain intact, and the new modules carry no
  NEXUS/LEGION import, no live-action, and no phase-literal surface.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_service import bind_adaptive_policy
from kalhas.application.adaptive_run_execution_builder import (
    RUNTIME_VERSION,
    AdaptiveRunExecutionBuildDraft,
)
from kalhas.application.adaptive_run_execution_query_service import (
    get_verified_adaptive_policy_decision_events,
    get_verified_adaptive_policy_switch_events,
    get_verified_runtime_observation_events,
)
from kalhas.application.adaptive_run_execution_service import execute_adaptive_run
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicyDraft
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    ObservationTiming,
    RuntimeObservationEvent,
)
from pydantic import BaseModel

from tests.phase4_helpers import NOW, TENANT, prepare
from tests.test_adaptive_run_execution_builder import (
    CAMPAIGN,
    SEED_ID,
    Env,
    _binding_request,
    _build_env,
    _catalogs_for,
    _declare_state_field,
    _new_store_with_world,
    _policy_draft,
)

HEADERS = {"X-Tenant-ID": TENANT}
OTHER_TENANT = "tenant-other"

OBSERVATIONS_PATH = "/v1/runs/{run_id}/adaptive/observations"
DECISIONS_PATH = "/v1/runs/{run_id}/adaptive/decisions"
SWITCHES_PATH = "/v1/runs/{run_id}/adaptive/switches"

#: The exact three new operations on the three new paths.
ADAPTIVE_PATHS: dict[str, set[str]] = {
    OBSERVATIONS_PATH: {"get"},
    DECISIONS_PATH: {"get"},
    SWITCHES_PATH: {"get"},
}

#: The six Phase 25 runtime-3 paths and their exact operations (unchanged).
REALIZATION_PATHS: dict[str, set[str]] = {
    "/v1/runs/{run_id}/realization-trajectory-execution": {"get"},
    "/v1/runs/{run_id}/realization-trajectory-replay-manifest": {"get"},
    "/v1/runs/{run_id}/realization-metric-observations": {"get", "post"},
    "/v1/campaigns/{campaign_id}/realization-trajectory-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-observation-matrix": {"get"},
    "/v1/campaigns/{campaign_id}/realization-metric-statistics": {"get"},
}

QUERY_MODULE = Path(__file__).resolve().parents[1] / (
    "kalhas/application/adaptive_run_execution_query_service.py"
)
QUERY_TESTS_MODULE = Path(__file__).resolve().parents[1] / (
    "tests/test_adaptive_run_execution_query_service.py"
)
ROUTE_MODULE = Path(__file__).resolve().parents[1] / "kalhas/api/routes_adaptive_run_execution.py"
APP_MODULE = Path(__file__).resolve().parents[1] / "kalhas/api/app.py"
ERRORS_MODULE = Path(__file__).resolve().parents[1] / "kalhas/api/errors.py"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


# --------------------------------------------------------------------------- #
# Fixtures: a real executed adaptive run served through the real app.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExecutedRun:
    """One real COMPLETE adaptive run on its own fresh real store."""

    store: InMemoryScenarioStore
    run_id: str
    world_id: str


def _plan_one_run(env: Env) -> tuple[InMemoryScenarioStore, str]:
    """Add exactly one deterministic PLANNED runtime-4 run to the campaign."""
    store = env.store
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, env.world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
    candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
    plan_input_hash = run_input_hash(
        world_content_hash=world.content_hash,
        strategy=candidates["mock-baseline"],
        seed=seed,
        runtime_version=RUNTIME_VERSION,
    )
    run_plan = RunPlan(
        identifier="run-plan-api",
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        world_version_id=env.world_id,
        strategy_candidate_id="mock-baseline",
        scenario_seed_id=SEED_ID,
        runtime_version=RUNTIME_VERSION,
        input_hash=plan_input_hash,
        created_at=NOW,
    )
    store.put_run_plans(TENANT, CAMPAIGN, (run_plan,))
    run_id = run_identifier(run_plan)
    store.put_run_status(
        TENANT,
        run_id,
        RunStatus(
            identifier=f"status-{run_id}",
            tenant_id=TENANT,
            run_id=run_id,
            campaign_id=CAMPAIGN,
            run_plan_id=run_plan.identifier,
            state=RunState.PLANNED,
            runtime_version=RUNTIME_VERSION,
            input_hash=plan_input_hash,
            event_hash=None,
            created_at=NOW,
            changed_at=NOW,
        ),
    )
    return store, run_id


def _executed_run() -> ExecutedRun:
    """Build the full real environment and execute exactly one adaptive run.

    Identical real construction to the accepted H28-S10 test module
    (which reuses the established builder fixtures by import): the
    campaign is prepared exactly COMPILED over the established fixture
    world, one deterministic PLANNED runtime-4 run is added, and the
    accepted service executes it to COMPLETE with a two-decision
    horizon, so every evidence sequence exists.
    """
    env = _build_env()
    store, run_id = _plan_one_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    assert result.status.state is RunState.COMPLETE
    return ExecutedRun(store=store, run_id=run_id, world_id=env.world_id)


def _never_matching_policy_draft() -> AdaptivePolicyDraft:
    """The established fixture policy with rules that can never match.

    Same rule shapes as ``_policy_draft``, but every condition leaf is
    retargeted at the established fixture declaration ``obs-level``
    (delay 0, integer ``level``) with an unreachable comparison: the
    ``level`` field starts at 0 and is only ever incremented by the
    mock trajectories, so ``level > 1000`` is false at every evaluated
    decision step for both the enter and the retain role. The fallback
    action therefore decides at every step, and because the fallback
    equals the initial action the run can never switch.
    """
    from kalhas.contracts.v1.adaptive_policy import ConditionComparisonLeaf

    def leaf(condition_id: str) -> ConditionComparisonLeaf:
        return ConditionComparisonLeaf(
            kind="comparison",
            condition_id=condition_id,
            observation_id="obs-level",
            observed_value_kind="integer",
            unit=None,
            operator="gt",
            threshold=1000,
            missing_behavior="false",
        )

    draft = _policy_draft()
    rules = tuple(
        type(rule)(
            rule_id=rule.rule_id,
            priority=rule.priority,
            target_action_id=rule.target_action_id,
            enter_condition=leaf(f"{rule.rule_id}-a"),
            retain_condition=leaf(f"{rule.rule_id}-r"),
            per_rule_switch_budget=rule.per_rule_switch_budget,
        )
        for rule in draft.rules
    )
    return type(draft)(
        request_id=draft.request_id,
        actions=draft.actions,
        initial_action_id=draft.initial_action_id,
        fallback_action_id=draft.initial_action_id,
        rules=rules,
        minimum_dwell_steps=draft.minimum_dwell_steps,
        cooldown_steps=draft.cooldown_steps,
        global_switch_budget=draft.global_switch_budget,
    )


def _executed_never_switch_run() -> ExecutedRun:
    """A real executed run whose policy never switches actions.

    The established fixture environment with the never-matching policy
    bound: the mock trajectories only increment ``level`` from 0, so no
    rule condition (``level > 1000``) can ever match; the real fallback
    path decides at every step and the fallback action equals the
    initial action, so the run completes with a genuinely empty switch
    sequence on the real execution path.
    """
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare_state_field(
        store,
        world_id,
        "obs-level",
        "level",
        ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0),
    )
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_never_matching_policy_draft(),
        binding_request=_binding_request("policy-1"),
    )
    env = Env(
        store=store,
        world_id=world_id,
        catalogs=_catalogs_for(store, world_id),
        realization_id="",
        realization_hash="",
        sm_a=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a").identifier,
        sm_b=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b").identifier,
        override_value=None,
    )
    store_ref, run_id = _plan_one_run(env)
    assert store_ref is store
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    assert result.status.state is RunState.COMPLETE
    execution = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    assert execution.switch_events == ()
    assert execution.observation_events != ()
    assert all(event.action_changed is False for event in execution.decision_events)
    return ExecutedRun(store=store, run_id=run_id, world_id=world_id)


# --------------------------------------------------------------------------- #
# Established phase-27 helper idiom
# --------------------------------------------------------------------------- #


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _store(client: TestClient) -> InMemoryScenarioStore:
    return cast(InMemoryScenarioStore, _app(client).state.store)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    _app(client).state.store = store


def _dump_value(value: object) -> object:
    """One canonical JSON dump of a stored record or record tuple."""
    if isinstance(value, tuple):
        return tuple(_dump_value(item) for item in value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _store_state(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest of the complete store state."""
    payload: dict[str, object] = {}
    for name, collection in store.__dict__.items():
        payload[name] = {repr(key): _dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)


def _store_fingerprint(store: InMemoryScenarioStore) -> dict[str, Any]:
    """A deep serializable fingerprint of every store surface."""
    dumped: dict[str, Any] = {}
    for name in sorted(vars(store)):
        value = getattr(store, name)
        try:
            dumped[name] = copy.deepcopy(repr(value))
        except Exception:
            dumped[name] = "<unrenderable>"
    return dumped


def _activities(store: InMemoryScenarioStore) -> list[Any]:
    return list(store.list_operational_activity(TENANT, after_sequence=-1, limit=1000))


def _assert_error_shape(
    response: Any,
    status: int,
    code: str,
    *,
    leak_scan: bool = True,
) -> dict[str, Any]:
    """Assert the typed safe error body and run the no-leak scan."""
    assert response.status_code == status
    body: dict[str, Any] = response.json()
    ApiErrorResponse.model_validate(body)
    assert body["code"] == code
    assert body["request_id"]
    if leak_scan:
        _assert_no_leak(body)
    return body


def _assert_no_leak(body: dict[str, Any]) -> None:
    """The error body must not leak hashes, foreign ids, reasons, internals."""
    serialized = json.dumps(body)
    assert not _HASH_PATTERN.search(serialized), "error body leaks a content hash"
    for forbidden in (
        OTHER_TENANT,
        "content_hash",
        "metadata",
        "reason",
        "seed-1",
        "level",
        "ratio",
        "policy-1",
        "act-1",
        "act-2",
        "rule-1",
        "obs-level",
        "weight",
        "threshold",
        "Traceback",
    ):
        assert forbidden not in serialized, f"error body leaks {forbidden!r}: {serialized}"


def _stored_arrays(run: ExecutedRun) -> dict[str, list[dict[str, Any]]]:
    """The canonical stored sequences as the exact expected JSON arrays."""
    execution = run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    return {
        "observations": [event.model_dump(mode="json") for event in execution.observation_events],
        "decisions": [event.model_dump(mode="json") for event in execution.decision_events],
        "switches": [event.model_dump(mode="json") for event in execution.switch_events],
    }


def _get(client: TestClient, path: str, run_id: str, headers: dict[str, str] = HEADERS) -> Any:
    return client.get(path.format(run_id=run_id), headers=headers)


# --------------------------------------------------------------------------- #
# A. Exact verified projections over HTTP
# --------------------------------------------------------------------------- #


class TestExactProjections:
    """200 responses equal the canonical stored sequences exactly."""

    def test_observations_equal_stored_sequence_exactly(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        response = _get(client, OBSERVATIONS_PATH, run.run_id)
        assert response.status_code == 200
        assert response.json() == _stored_arrays(run)["observations"]
        assert all(
            type(event) is RuntimeObservationEvent
            for event in get_verified_runtime_observation_events(
                run.store, tenant_id=TENANT, run_id=run.run_id
            )
        )

    def test_decisions_equal_stored_sequence_exactly(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        response = _get(client, DECISIONS_PATH, run.run_id)
        assert response.status_code == 200
        assert response.json() == _stored_arrays(run)["decisions"]
        body = response.json()
        assert [event["decision_step"] for event in body] == list(range(len(body)))

    def test_switches_equal_stored_sequence_exactly(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        response = _get(client, SWITCHES_PATH, run.run_id)
        assert response.status_code == 200
        assert response.json() == _stored_arrays(run)["switches"]

    def test_repeat_gets_are_deterministic_and_canonical(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        first = {
            name: _get(client, path, run.run_id)
            for name, path in (
                ("observations", OBSERVATIONS_PATH),
                ("decisions", DECISIONS_PATH),
                ("switches", SWITCHES_PATH),
            )
        }
        second = {
            name: _get(client, path, run.run_id)
            for name, path in (
                ("observations", OBSERVATIONS_PATH),
                ("decisions", DECISIONS_PATH),
                ("switches", SWITCHES_PATH),
            )
        }
        for name in first:
            assert first[name].status_code == 200
            assert first[name].content == second[name].content
        observation_events = first["observations"].json()
        assert [event["sequence_position"] for event in observation_events] == list(
            range(len(observation_events))
        )
        decision_events = first["decisions"].json()
        assert [event["decision_step"] for event in decision_events] == list(
            range(len(decision_events))
        )
        switch_events = first["switches"].json()
        assert [event["decision_step"] for event in switch_events] == [
            event["decision_step"] for event in decision_events if event["action_changed"]
        ]

    def test_empty_switch_sequence_is_a_valid_empty_json_array(self, client: TestClient) -> None:
        run = _executed_never_switch_run()
        _install_store(client, run.store)
        response = _get(client, SWITCHES_PATH, run.run_id)
        assert response.status_code == 200
        assert response.json() == []
        stored = run.store.get_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=run.run_id
        )
        assert stored.switch_events == ()
        assert any(event.action_changed is False for event in stored.decision_events)

    def test_event_contracts_validate_against_response_bodies(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        for path, contract in (
            (OBSERVATIONS_PATH, RuntimeObservationEvent),
            (DECISIONS_PATH, AdaptivePolicyDecisionEvent),
            (SWITCHES_PATH, AdaptivePolicySwitchEvent),
        ):
            response = _get(client, path, run.run_id)
            assert response.status_code == 200
            for item in response.json():
                contract.model_validate(item)


# --------------------------------------------------------------------------- #
# B. Request validation and tenant isolation
# --------------------------------------------------------------------------- #


class TestTenantAndValidation:
    """Required tenant header and non-enumeration semantics."""

    def test_missing_tenant_header_is_422(self, client: TestClient) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
            response = client.get(path.format(run_id=run.run_id))
            _assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR.value)

    @pytest.mark.parametrize(
        "path",
        (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH),
    )
    def test_unknown_and_foreign_executions_are_indistinguishable_404(
        self, client: TestClient, path: str
    ) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        unknown = _get(client, path, "run-never-planned")
        foreign = client.get(path.format(run_id=run.run_id), headers={"X-Tenant-ID": OTHER_TENANT})
        unknown_body = _assert_error_shape(unknown, 404, ErrorCode.NOT_FOUND.value)
        foreign_body = _assert_error_shape(foreign, 404, ErrorCode.NOT_FOUND.value)
        assert unknown_body["message"] == foreign_body["message"]
        assert unknown_body["details"] == foreign_body["details"]
        assert foreign_body["message"] == "Adaptive run trajectory execution not found"


# --------------------------------------------------------------------------- #
# C. Integrity rejections over HTTP
# --------------------------------------------------------------------------- #


class TestIntegrityRejections:
    """Stored and cross-authority corruption return the sanitized 409."""

    def test_stored_contract_corruption_is_sanitized_409(self, client: TestClient) -> None:
        run = _executed_run()
        store = run.store
        _install_store(client, store)
        key = (TENANT, run.run_id)
        pristine = store._adaptive_run_trajectory_executions[key]
        baseline = _store_fingerprint(store)
        forged = pristine.model_copy(deep=True)
        object.__setattr__(forged, "decision_events", ())
        store._adaptive_run_trajectory_executions[key] = forged
        try:
            for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
                response = _get(client, path, run.run_id)
                _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)
                assert (
                    response.json()["message"]
                    == "Adaptive run trajectory execution failed integrity verification"
                )
        finally:
            store._adaptive_run_trajectory_executions[key] = pristine
        assert _store_fingerprint(store) == baseline

    def test_cross_authority_corruption_is_sanitized_409(self, client: TestClient) -> None:
        run = _executed_run()
        store = run.store
        _install_store(client, store)
        from kalhas.application.adaptive_trajectory_execution_identity import (
            adaptive_run_trajectory_execution_content_hash,
            adaptive_run_trajectory_execution_identifier,
        )

        key = (TENANT, run.run_id)
        execution = store._adaptive_run_trajectory_executions[key]
        forged = execution.model_copy(
            update={
                "adaptive_policy_identifier": "policy-forged"
                if execution.adaptive_policy_identifier != "policy-forged"
                else "policy-1-x"
            }
        )
        forged = forged.model_copy(
            update={"content_hash": adaptive_run_trajectory_execution_content_hash(forged)}
        )
        object.__setattr__(
            forged,
            "identifier",
            adaptive_run_trajectory_execution_identifier(
                run_id=run.run_id, runtime_version=forged.runtime_version
            ),
        )
        store._adaptive_run_trajectory_executions[key] = forged
        for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
            response = _get(client, path, run.run_id)
            _assert_error_shape(response, 409, ErrorCode.INTEGRITY_ERROR.value)


# --------------------------------------------------------------------------- #
# D. Read-only purity
# --------------------------------------------------------------------------- #


class TestReadOnlyPurity:
    """Successful and rejected GETs change nothing and emit no activity."""

    def test_successful_gets_leave_store_fingerprint_and_activity_unchanged(
        self, client: TestClient
    ) -> None:
        run = _executed_run()
        store = run.store
        _install_store(client, store)
        before = _store_fingerprint(store)
        activities_before = _activities(store)
        for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
            assert _get(client, path, run.run_id).status_code == 200
            assert _get(client, path, run.run_id).status_code == 200
        assert _store_fingerprint(store) == before
        assert _activities(store) == activities_before

    def test_rejected_gets_leave_store_fingerprint_and_activity_unchanged(
        self, client: TestClient
    ) -> None:
        run = _executed_run()
        store = run.store
        _install_store(client, store)
        before = _store_fingerprint(store)
        activities_before = _activities(store)
        assert _get(client, OBSERVATIONS_PATH, "run-never-planned").status_code == 404
        assert _get(client, DECISIONS_PATH, "run-never-planned").status_code == 404
        assert _get(client, SWITCHES_PATH, "run-never-planned").status_code == 404
        foreign = client.get(
            SWITCHES_PATH.format(run_id=run.run_id), headers={"X-Tenant-ID": OTHER_TENANT}
        )
        assert foreign.status_code == 404
        missing_header = client.get(DECISIONS_PATH.format(run_id=run.run_id))
        assert missing_header.status_code == 422
        assert _store_fingerprint(store) == before
        assert _activities(store) == activities_before

    @pytest.mark.parametrize("method", ("post", "put", "patch", "delete"))
    def test_no_mutation_methods_on_adaptive_paths(self, client: TestClient, method: str) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
            response = client.request(method, path.format(run_id=run.run_id), headers=HEADERS)
            assert response.status_code == 405

    def test_run_state_and_campaign_untouched_by_gets(self, client: TestClient) -> None:
        run = _executed_run()
        store = run.store
        _install_store(client, store)
        status_before = store.get_run_status(TENANT, run.run_id)
        assert status_before.state is RunState.COMPLETE
        for path in (OBSERVATIONS_PATH, DECISIONS_PATH, SWITCHES_PATH):
            _get(client, path, run.run_id)
        assert store.get_run_status(TENANT, run.run_id) == status_before


# --------------------------------------------------------------------------- #
# E. Exact query dispatch
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _counting_query_patches(calls: list[str]) -> Iterator[None]:
    """Patch all three route query symbols with counting wrappers.

    The route module is patched (not the production query service), so
    the real accepted H28-S10 functions still execute; every call is
    recorded by name in ``calls`` in exact dispatch order.
    """
    originals = {
        "observations": get_verified_runtime_observation_events,
        "decisions": get_verified_adaptive_policy_decision_events,
        "switches": get_verified_adaptive_policy_switch_events,
    }

    def make_wrapper(name: str) -> Any:
        original = originals[name]

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return original(*args, **kwargs)

        return wrapper

    source_module = "kalhas.api.routes_adaptive_run_execution"
    with (
        mock.patch(
            f"{source_module}.get_verified_runtime_observation_events",
            side_effect=make_wrapper("observations"),
        ),
        mock.patch(
            f"{source_module}.get_verified_adaptive_policy_decision_events",
            side_effect=make_wrapper("decisions"),
        ),
        mock.patch(
            f"{source_module}.get_verified_adaptive_policy_switch_events",
            side_effect=make_wrapper("switches"),
        ),
    ):
        yield


class TestExactQueryDispatch:
    """Each route calls exactly its matching query once - no other query."""

    def test_route_calls_only_its_matching_query_once(self, client: TestClient) -> None:
        for path, expected in (
            (OBSERVATIONS_PATH, "observations"),
            (DECISIONS_PATH, "decisions"),
            (SWITCHES_PATH, "switches"),
        ):
            run = _executed_run()
            _install_store(client, run.store)
            calls: list[str] = []
            with _counting_query_patches(calls):
                response = _get(client, path, run.run_id)
            assert response.status_code == 200
            assert calls == [expected], path

    def test_error_paths_dispatch_through_the_single_matching_query(
        self, client: TestClient
    ) -> None:
        run = _executed_run()
        _install_store(client, run.store)
        calls: list[str] = []
        with _counting_query_patches(calls):
            assert _get(client, OBSERVATIONS_PATH, "run-never-planned").status_code == 404
            assert _get(client, DECISIONS_PATH, "run-never-planned").status_code == 404
            assert _get(client, SWITCHES_PATH, "run-never-planned").status_code == 404
        assert calls == ["observations", "decisions", "switches"]


# --------------------------------------------------------------------------- #
# F. OpenAPI surface
# --------------------------------------------------------------------------- #


class TestOpenApiSurface:
    """The OpenAPI contract of the three new operations."""

    def test_exactly_three_new_paths_get_only(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        new_paths = {path: set(ops) for path, ops in paths.items() if "/adaptive/" in path}
        assert new_paths == ADAPTIVE_PATHS
        assert sum(len(ops) for ops in ADAPTIVE_PATHS.values()) == 3

    def test_response_schemas_are_arrays_of_existing_v1_event_refs(
        self, client: TestClient
    ) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        expected_refs = {
            OBSERVATIONS_PATH: "#/components/schemas/RuntimeObservationEvent",
            DECISIONS_PATH: "#/components/schemas/AdaptivePolicyDecisionEvent",
            SWITCHES_PATH: "#/components/schemas/AdaptivePolicySwitchEvent",
        }
        schemas = spec["components"]["schemas"]
        for path, expected_ref in expected_refs.items():
            operation = paths[path]["get"]
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            assert schema["type"] == "array", path
            assert schema["items"]["$ref"] == expected_ref, path
        for name in (
            "RuntimeObservationEvent",
            "AdaptivePolicyDecisionEvent",
            "AdaptivePolicySwitchEvent",
        ):
            assert name in schemas

    def test_required_tenant_header_no_body_no_runtime_selector(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        expected_header = {
            "name": "X-Tenant-ID",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "title": "X-Tenant-Id"},
        }
        for path in ADAPTIVE_PATHS:
            operation = paths[path]["get"]
            parameters = operation.get("parameters", [])
            headers = [parameter for parameter in parameters if parameter["in"] == "header"]
            assert headers == [expected_header], path
            queries = [parameter for parameter in parameters if parameter["in"] == "query"]
            assert queries == [], path
            assert all("runtime" not in str(parameter).lower() for parameter in parameters), path
            assert "requestBody" not in operation, path

    def test_no_duplicate_operation_ids_and_no_error_response_leak(
        self, client: TestClient
    ) -> None:
        spec = _app(client).openapi()
        operation_ids: list[str] = []
        for _path, operations in spec["paths"].items():
            for operation_name, operation in operations.items():
                if operation_name in ("get", "post", "put", "patch", "delete"):
                    operation_ids.append(operation["operationId"])
        assert len(operation_ids) == len(set(operation_ids))
        adaptive_operations = [
            operation
            for path, operations in spec["paths"].items()
            for operation_name, operation in operations.items()
            if "/adaptive/" in path and operation_name == "get"
        ]
        assert len(adaptive_operations) == 3
        for operation in adaptive_operations:
            responses = operation["responses"]
            # The real generated surface: documented 200 and the FastAPI
            # 422 validation envelope only - no 404/409 response schema
            # is invented into the contract.
            assert set(responses) == {"200", "422"}, sorted(responses)
            assert responses["422"]["content"]["application/json"]["schema"]["$ref"] == (
                "#/components/schemas/HTTPValidationError"
            )

    def test_earlier_paths_remain_unchanged(self, client: TestClient) -> None:
        spec = _app(client).openapi()
        paths = spec["paths"]
        realization_paths = {
            path: set(ops) for path, ops in paths.items() if "realization-" in path
        }
        assert realization_paths == REALIZATION_PATHS
        assert sum(len(ops) for ops in REALIZATION_PATHS.values()) == 7
        assert set(paths["/v1/campaigns/{campaign_id}/outcome-distributions"]) == {"get"}
        assert set(paths["/v1/campaigns/{campaign_id}/decision-policy"]) == {"get", "post"}
        assert set(paths["/v1/campaigns/{campaign_id}/strategy-comparison"]) == {"get"}
        assert set(paths["/v1/campaigns/{campaign_id}/decision-brief"]) == {"get"}
        assert set(paths["/v1/scenarios/{scenario_id}/evaluation-profile"]) == {"get", "post"}
        assert set(paths["/v1/campaigns/{campaign_id}/objective-evaluations"]) == {"get"}
        assert set(paths["/v1/worlds/{world_version_id}"]) == {"get"}
        assert set(paths["/v1/scenarios/{scenario_id}/uncertainty-model"]) == {"get", "post"}


# --------------------------------------------------------------------------- #
# G. Registration and protected-surface integrity
# --------------------------------------------------------------------------- #


class TestRegistrationAndProtectedSurfaces:
    """Wiring, error mapping, and the untouched protected files."""

    def test_router_included_exactly_once_in_create_app(self) -> None:
        source = APP_MODULE.read_text(encoding="utf-8")
        assert source.count("adaptive_run_execution_router") == 2  # alias + include
        assert source.count("include_router(adaptive_run_execution_router)") == 1

    def test_new_module_registered_with_the_adaptive_runs_tag(self) -> None:
        source = ROUTE_MODULE.read_text(encoding="utf-8")
        assert 'APIRouter(tags=["adaptive-runs"])' in source
        assert source.count("APIRouter(") == 1

    def test_error_mapping_registered_exactly_once(self) -> None:
        source = ERRORS_MODULE.read_text(encoding="utf-8")
        assert source.count("AdaptiveRunTrajectoryExecutionNotFoundError") == 2  # import + map
        assert source.count("AdaptiveRunTrajectoryExecutionIntegrityError") == 2  # import + map
        assert "ErrorCode.INTEGRITY_ERROR" in source

    def test_prior_error_mappings_remain_intact(self) -> None:
        source = ERRORS_MODULE.read_text(encoding="utf-8")
        for prior in (
            "RunTrajectoryExecutionNotFoundError",
            "RunTrajectoryExecutionIntegrityError",
            "RealizationRunTrajectoryExecutionNotFoundError",
            "RealizationRunTrajectoryExecutionIntegrityError",
            "CampaignDecisionPolicyNotFoundError",
            "CampaignDecisionComparisonIntegrityError",
            "CampaignDecisionBriefIntegrityError",
            "CampaignOutcomeDistributionMatrixIntegrityError",
        ):
            assert prior in source
        assert source.count("404, ErrorCode.NOT_FOUND") == 1
        assert source.count("409, ErrorCode.INTEGRITY_ERROR") == 1

    def test_h28_s10_production_module_and_tests_are_unchanged(self) -> None:
        expected_query = (
            "63a6a6fe7b5cb96ae9e03e621975b72475a583d2",
            6507,
        )
        expected_tests = (
            "ac14588599081e693820a30922c3cfd168b1101c",
            30678,
        )
        for path, (expected_blob, expected_size) in (
            (QUERY_MODULE, expected_query),
            (QUERY_TESTS_MODULE, expected_tests),
        ):
            content = path.read_bytes()
            assert len(content) == expected_size, path
            # Git blob object IDs (sha1 of the "blob <byte_count>\0"
            # header + content), exactly what ``git hash-object``
            # records - not raw-file SHA1 digests.
            blob = hashlib.sha1(
                b"blob " + str(len(content)).encode("ascii") + b"\0" + content
            ).hexdigest()
            assert blob == expected_blob, path

    def test_public_contracts_and_schema_artifacts_are_unchanged(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 55
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 55
        assert len([path for path in SCHEMA_DIR.iterdir() if path.is_file()]) == 56
        by_name = {path.name: path for path in schema_files}
        expected = {
            "AdaptivePolicy.schema.json": (
                "80660cfee50a237c38d78dbb043f22a89bd76528eb2c57625da6939ce9633fff"
            ),
            "AdaptiveRunTrajectoryExecution.schema.json": (
                "7d10563feffca03faa390712a99238f562502987d3c2a04ba14c626492c6789c"
            ),
            "AdaptiveRunTrajectoryReplayManifest.schema.json": (
                "96a7bde2499792ed74044a343e0981ddcbfcd6691d5ae8051c620eb8a5ece1ca"
            ),
        }
        for name, expected_digest in expected.items():
            assert name in by_name, name
            digest = hashlib.sha256(by_name[name].read_bytes()).hexdigest()
            assert digest == expected_digest, f"{name} changed: {digest}"

    def test_prior_api_phase27_regression_file_is_unchanged(self) -> None:
        path = Path(__file__).resolve().parents[1] / "tests/test_api_phase27.py"
        content = path.read_bytes()
        assert len(content) == 76842
        # Git blob object ID (sha1 of the "blob <byte_count>\0" header
        # + content), not a raw-file SHA1 digest.
        blob = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest()
        assert blob == "890a3b412c988cab64a6b9c35dd6a9068b3ac378"


# --------------------------------------------------------------------------- #
# H. Module boundaries
# --------------------------------------------------------------------------- #


class TestModuleBoundaries:
    """The new modules carry no forbidden surface."""

    def test_route_module_imports_only_allowed_modules(self) -> None:
        tree = ast.parse(ROUTE_MODULE.read_text(encoding="utf-8"))
        paths = _imported_module_paths(tree)
        for path in sorted(paths):
            assert not path.startswith(("kalhas.adapters", "kalhas.domain_packs")), path
            assert "nexus" not in path.lower()
            assert "legion" not in path.lower()
        top_level = _imported_modules(tree)
        forbidden_top_level = {
            "socket",
            "random",
            "time",
            "os",
            "subprocess",
            "pathlib",
            "requests",
            "httpx",
            "sqlite3",
            "datetime",
            "dateutil",
        }
        assert not (top_level & forbidden_top_level), sorted(top_level & forbidden_top_level)

    def test_route_module_has_no_store_write_or_activity_calls(self) -> None:
        tree = ast.parse(ROUTE_MODULE.read_text(encoding="utf-8"))
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        assert called <= {"get", "list"}, f"unexpected method calls: {sorted(called)}"

    def test_route_module_has_no_phase_literals_or_h28_s12_surface(self) -> None:
        source_text = ROUTE_MODULE.read_text(encoding="utf-8")
        assert "H28-S12" not in source_text
        assert "H28-S13" not in source_text

    def test_app_and_error_modules_carry_no_new_forbidden_surface(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|\bphase\s*28\b|phase_26|phase_27|phase_28"
            r"|26\.0\.0|27\.0\.0|28\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        for module in (APP_MODULE, ERRORS_MODULE):
            source_text = module.read_text(encoding="utf-8")
            assert not pattern.search(source_text), module
            assert "rank" not in source_text.lower()
            assert "recommend" not in source_text.lower()


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths
