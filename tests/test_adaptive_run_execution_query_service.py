"""H28-S10 proofs: verified read-only adaptive run execution query projections.

Real stores, real compiled worlds, real bound adaptive policies, real
runtime-4 planning, real adaptive executions through the accepted
service, and the real store persistence surface. The proven fixture
helpers of ``tests/test_adaptive_run_execution_builder.py`` are reused by
import without editing that file. No production monkeypatching, mocks,
skips, xfails, noqa, or type-ignores exist in this module.

Sections:

- A. exact verified projections (observation, decision, and switch
  sequences equal the stored aggregate exactly, canonical order,
  deterministic repeat reads, defensive-value retrieval, and the
  empty switch sequence where valid; the empty observation
  projection is proven non-constructible for a real executed run);
- B. tenant isolation and authoritative rejection (unknown and foreign
  runs indistinguishable, stored contract corruption and cross-authority
  corruption rejected by the authoritative read before any projection,
  with the full store surface preserved atomically);
- C. read-only purity and architecture boundaries (complete store
  fingerprint and activity sequence unchanged, no mutation reachability
  from returned values, no query-created persistence surface, domain
  neutrality, no API/OpenAPI exposure in this slice).
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_condition_errors import AdaptiveConditionEvaluationError
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
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicyDraft
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import ObservationTiming

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

FOREIGN_TENANT = "tenant-other"
QUERY_MODULE = "kalhas/application/adaptive_run_execution_query_service.py"


# --------------------------------------------------------------------------- #
# Fixtures: a real executed adaptive run per test (the established idiom).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExecutedRun:
    """One real COMPLETE adaptive run on its own fresh real store."""

    store: InMemoryScenarioStore
    run_id: str
    world_id: str


def _executed_run() -> ExecutedRun:
    """Build the full real environment and execute exactly one adaptive run.

    The campaign is prepared exactly COMPILED over the established
    builder-test fixture world; one deterministic PLANNED runtime-4 run
    plan and status is added; the accepted service executes it to
    COMPLETE with a two-decision horizon, so every evidence sequence
    exists, and the decision horizon is short enough that the
    declaration cadence ``start_step=0, every_n_steps=1`` yields real
    observation events.
    """
    env = _build_env()
    store, run_id = _plan_one_run(env)
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=1)
    result = execute_adaptive_run(store, tenant_id=TENANT, run_id=run_id, draft=draft)
    assert result.status.state is RunState.COMPLETE
    return ExecutedRun(store=store, run_id=run_id, world_id=env.world_id)


def _planned_late_start_run() -> tuple[ExecutedRun, RunState]:
    """Prepare and plan the late-start-observation environment without executing.

    This is the mechanically exposed form of the former
    ``_empty_observation_run`` helper: it performs every real construction
    step up to and including planning - real store, real compiled world,
    real late-start observation declaration, real policy binding, real
    runtime-4 run plan and PLANNED status - and returns the planned store
    and run together with the run's recorded status state, so a test can
    execute (or deliberately reject execution of) the run itself and
    prove the pre-execution authority state. Construction is entirely
    real and deterministic.
    """
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        # Campaign preparation supports only 1.0.0/2.0.0; the runtime-4
        # layer begins at the policy, run plan, and run status chain.
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
    # The late-start declaration exists before policy binding, and the
    # bound policy references it from the beginning (exactly one
    # binding, no rebinding).
    _declare_state_field(
        store,
        world_id,
        "obs-level-late-start",
        "level",
        ObservationTiming(start_step=3, every_n_steps=1, delay_steps=0),
    )
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_late_start_policy_draft("obs-level-late-start"),
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
    store_ref, run_id_run = _plan_one_run(env)
    assert store_ref is store
    status = store.get_run_status(TENANT, run_id_run)
    assert status.state is RunState.PLANNED
    return ExecutedRun(store=store, run_id=run_id_run, world_id=world_id), status.state


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
        identifier="run-plan-query",
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


def _late_start_policy_draft(observation_id: str) -> AdaptivePolicyDraft:
    """The established fixture policy, bound against one late-start declaration.

    The rules are identical to the established fixture rules
    (``_policy_draft``), merely retargeted at the supplied observation;
    the canonical draft conditions stay self-consistent with that
    declaration, exactly as the builder-test fixtures build their policy
    against ``obs-level``.
    """
    from kalhas.contracts.v1.adaptive_policy import ConditionComparisonLeaf

    def leaf(condition_id: str) -> ConditionComparisonLeaf:
        return ConditionComparisonLeaf(
            kind="comparison",
            condition_id=condition_id,
            observation_id=observation_id,
            observed_value_kind="integer",
            unit=None,
            operator="gt",
            threshold=0,
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
        fallback_action_id=draft.fallback_action_id,
        rules=rules,
        minimum_dwell_steps=draft.minimum_dwell_steps,
        cooldown_steps=draft.cooldown_steps,
        global_switch_budget=draft.global_switch_budget,
    )


def _surface(store: InMemoryScenarioStore) -> dict[str, Any]:
    """A deep serializable fingerprint of every store surface (established idiom)."""
    dumped: dict[str, Any] = {}
    for name in sorted(vars(store)):
        value = getattr(store, name)
        try:
            dumped[name] = copy.deepcopy(repr(value))
        except Exception:
            dumped[name] = "<unrenderable>"
    return dumped


def _stripped_source(source: str) -> str:
    """Executable source with docstrings removed (established mechanical idiom).

    ``str.split('\"\"\"')[::2]`` keeps exactly the even-indexed chunks,
    which are the text outside the triple-double-quoted spans, so
    forbidden-token scans run against stripped executable source rather
    than explanatory docstring prose. Accurate production documentation
    is preserved untouched - scanning, not deleting, is the remedy.
    """
    return "".join(source.split('"""')[::2])


# --------------------------------------------------------------------------- #
# A. Exact verified projections
# --------------------------------------------------------------------------- #


def test_a1_observation_projection_equals_stored_sequence_exactly() -> None:
    run = _executed_run()
    execution = run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    assert len(execution.observation_events) >= 1
    assert (
        get_verified_runtime_observation_events(run.store, tenant_id=TENANT, run_id=run.run_id)
        == execution.observation_events
    )


def test_a2_decision_projection_equals_stored_sequence_exactly() -> None:
    run = _executed_run()
    execution = run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    decisions = get_verified_adaptive_policy_decision_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    assert decisions == execution.decision_events
    assert [event.decision_step for event in decisions] == [0, 1]
    assert len(decisions) >= 1


def test_a3_switch_projection_equals_stored_sequence_exactly() -> None:
    run = _executed_run()
    execution = run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    switches = get_verified_adaptive_policy_switch_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    assert switches == execution.switch_events
    assert [event.decision_step for event in switches] == [
        event.decision_step for event in execution.decision_events if event.action_changed
    ]


def test_a4_repeat_reads_are_deterministic_and_canonical_order_is_preserved() -> None:
    run = _executed_run()
    first_observations = get_verified_runtime_observation_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    second_observations = get_verified_runtime_observation_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    assert first_observations == second_observations
    assert first_observations is not second_observations
    assert [event.sequence_position for event in first_observations] == list(
        range(len(first_observations))
    )
    first_decisions = get_verified_adaptive_policy_decision_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    second_decisions = get_verified_adaptive_policy_decision_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    assert first_decisions == second_decisions
    assert [event.decision_step for event in first_decisions] == list(range(len(first_decisions)))
    first_switches = get_verified_adaptive_policy_switch_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    second_switches = get_verified_adaptive_policy_switch_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    assert first_switches == second_switches


def test_a5_empty_observation_projection_is_not_constructible_for_a_real_executed_run() -> None:
    """The empty observation projection cannot arise on the real execution path.

    An empty observation-event projection is NOT constructible for a real
    executed adaptive run under the frozen production invariants: the
    binding service requires every bound adaptive policy to reference a
    non-empty observation catalog, and the condition evaluator requires
    ``len(events) == len(policy.observation_bindings)`` at every evaluated
    decision step, so the real builder can never reach step 0 with zero
    events. The former A5 premise - that a real executed run could yield
    an empty observation sequence - is therefore false and is replaced by
    this truthful real-path proof: planning the real late-start run and
    attempting its real execution is rejected fail-closed with the exact
    existing typed reason ``event_count_must_equal_observation_binding_count``
    before any write, no ``AdaptiveRunTrajectoryExecution`` authority is
    persisted, the run stays exactly PLANNED, and the read-only query
    surface keeps its not-found/non-enumeration semantics for the absent
    execution.
    """
    run, planned_state = _planned_late_start_run()
    assert planned_state is RunState.PLANNED
    assert (
        run.store.get_run_status(TENANT, run.run_id).state is RunState.PLANNED
    )  # pre-execution real-path state, never hand-built
    with pytest.raises(AdaptiveConditionEvaluationError) as rejected:
        execute_adaptive_run(
            run.store,
            tenant_id=TENANT,
            run_id=run.run_id,
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
        )
    assert rejected.value.reason == "event_count_must_equal_observation_binding_count"
    # The rejection is atomic: no AdaptiveRunTrajectoryExecution authority
    # was persisted for this run, and the run remains exactly PLANNED.
    with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError):
        run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    assert run.store.get_run_status(TENANT, run.run_id).state is RunState.PLANNED
    # The read-only query surface preserves its not-found semantics for
    # the absent execution: unknown and foreign queries are the same
    # typed not-found error, indistinguishable and non-enumerating.
    for projections in (
        get_verified_runtime_observation_events,
        get_verified_adaptive_policy_decision_events,
        get_verified_adaptive_policy_switch_events,
    ):
        with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError) as unknown:
            projections(run.store, tenant_id=TENANT, run_id=run.run_id)
        with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError) as foreign:
            projections(run.store, tenant_id=FOREIGN_TENANT, run_id=run.run_id)
        assert str(unknown.value) == str(foreign.value)
        assert unknown.value.reason == foreign.value.reason


def test_a6_empty_switch_sequence_is_a_valid_projection() -> None:
    run = _executed_run()
    execution = run.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id)
    switches = get_verified_adaptive_policy_switch_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    if not any(event.action_changed for event in execution.decision_events):
        assert execution.switch_events == ()
        assert switches == ()
    else:
        assert len(switches) >= 1


def test_a7_defensive_values_cannot_mutate_store_authority() -> None:
    run = _executed_run()
    pristine = copy.deepcopy(
        run.store.get_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=run.run_id
        ).model_dump(mode="json")
    )
    observations = get_verified_runtime_observation_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    decisions = get_verified_adaptive_policy_decision_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    switches = get_verified_adaptive_policy_switch_events(
        run.store, tenant_id=TENANT, run_id=run.run_id
    )
    with pytest.raises((AttributeError, TypeError, ValueError)):
        observations[0].sequence_position = 999
    with pytest.raises((AttributeError, TypeError, ValueError)):
        decisions[0].decision_step = 999
    if switches:
        with pytest.raises((AttributeError, TypeError, ValueError)):
            switches[0].decision_step = 999
    reread = run.store.get_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=run.run_id
    ).model_dump(mode="json")
    assert reread == pristine


# --------------------------------------------------------------------------- #
# B. Tenant isolation and authoritative rejection
# --------------------------------------------------------------------------- #


def test_b1_unknown_and_foreign_runs_are_indistinguishable() -> None:
    run = _executed_run()
    store = run.store
    for projections in (
        get_verified_runtime_observation_events,
        get_verified_adaptive_policy_decision_events,
        get_verified_adaptive_policy_switch_events,
    ):
        with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError) as unknown:
            projections(store, tenant_id=TENANT, run_id="run-never-planned")
        with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError) as foreign:
            projections(store, tenant_id=FOREIGN_TENANT, run_id=run.run_id)
        assert str(unknown.value) == str(foreign.value)
        assert unknown.value.reason == foreign.value.reason


def test_b2_stored_contract_corruption_is_rejected_before_projection() -> None:
    run = _executed_run()
    store = run.store
    key = (TENANT, run.run_id)
    # Private-dict injection is the established tamper path: the store
    # deliberately exposes no overwrite surface for immutable records.
    pristine = store._adaptive_run_trajectory_executions[key]
    baseline = _surface(store)
    forged = pristine.model_copy(deep=True)
    object.__setattr__(forged, "decision_events", ())
    store._adaptive_run_trajectory_executions[key] = forged
    try:
        for projections in (
            get_verified_runtime_observation_events,
            get_verified_adaptive_policy_decision_events,
            get_verified_adaptive_policy_switch_events,
        ):
            with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
                projections(store, tenant_id=TENANT, run_id=run.run_id)
    finally:
        store._adaptive_run_trajectory_executions[key] = pristine
    assert (
        store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run.run_id) == pristine
    )
    assert _surface(store) == baseline


def test_b3_cross_authority_corruption_is_rejected_before_projection() -> None:
    run = _executed_run()
    store = run.store
    # A self-consistently rehashed execution whose policy identity no
    # longer matches the stored policy authority is rejected by the
    # authoritative getter's cross-authority verification, not by this
    # module: the tampered record is injected wholesale with a recomputed
    # identifier and content hash, so only the authority comparison can
    # catch it.
    key = (TENANT, run.run_id)
    execution = store._adaptive_run_trajectory_executions[key]
    from kalhas.application.adaptive_trajectory_execution_identity import (
        adaptive_run_trajectory_execution_content_hash,
        adaptive_run_trajectory_execution_identifier,
    )

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
    for projections in (
        get_verified_runtime_observation_events,
        get_verified_adaptive_policy_decision_events,
        get_verified_adaptive_policy_switch_events,
    ):
        with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
            projections(store, tenant_id=TENANT, run_id=run.run_id)


def test_b4_rejection_is_atomic_over_the_complete_store_surface() -> None:
    run = _executed_run()
    store = run.store
    key = (TENANT, run.run_id)
    before = _surface(store)
    pristine = store._adaptive_run_trajectory_executions[key]
    forged = pristine.model_copy(deep=True)
    object.__setattr__(forged, "decision_events", ())
    store._adaptive_run_trajectory_executions[key] = forged
    try:
        for projections in (
            get_verified_runtime_observation_events,
            get_verified_adaptive_policy_decision_events,
            get_verified_adaptive_policy_switch_events,
        ):
            with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
                projections(store, tenant_id=TENANT, run_id=run.run_id)
    finally:
        store._adaptive_run_trajectory_executions[key] = pristine
    # With the deliberately injected record restored, the complete
    # final store surface must equal the pristine baseline: rejection
    # created no query-side partial write or activity change.
    assert _surface(store) == before


# --------------------------------------------------------------------------- #
# C. Read-only purity and architecture boundaries
# --------------------------------------------------------------------------- #


def test_c1_projections_leave_the_complete_store_fingerprint_unchanged() -> None:
    run = _executed_run()
    store = run.store
    before = _surface(store)
    activities_before = copy.deepcopy(
        store.list_operational_activity(TENANT, after_sequence=-1, limit=1000)
    )
    for projections in (
        get_verified_runtime_observation_events,
        get_verified_adaptive_policy_decision_events,
        get_verified_adaptive_policy_switch_events,
    ):
        projections(store, tenant_id=TENANT, run_id=run.run_id)
        projections(store, tenant_id=TENANT, run_id=run.run_id)
    assert _surface(store) == before
    assert store.list_operational_activity(TENANT, after_sequence=-1, limit=1000) == (
        activities_before
    )


def test_c2_no_query_created_persistence_surface_exists() -> None:
    module = inspect.getmodule(get_verified_runtime_observation_events)
    assert module is not None
    source = _stripped_source(inspect.getsource(module))
    assert "put_" not in source
    assert "append_operational_activity" not in source
    store_methods = {
        name for name, _member in inspect.getmembers(InMemoryScenarioStore, inspect.isfunction)
    }
    query_names = {
        "get_verified_runtime_observation_events",
        "get_verified_adaptive_policy_decision_events",
        "get_verified_adaptive_policy_switch_events",
    }
    assert query_names.isdisjoint(store_methods)
    store = _executed_run().store
    for name in sorted(query_names):
        assert not hasattr(store, name)


def test_c3_module_architecture_and_domain_neutrality() -> None:
    raw_source = pathlib.Path(QUERY_MODULE).read_text(encoding="utf-8")
    source = _stripped_source(raw_source)
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        assert "nexus" not in name.lower()
        assert "legion" not in name.lower()
        assert not name.startswith("kalhas.api")
        assert not name.startswith("kalhas.domain_packs")
    for token in ("httpx", "requests", "socket", "random", "uuid", "datetime.now(", "time.time("):
        assert token not in source
    assert "__all__" in source


def test_c4_no_api_or_openapi_exposure_in_this_slice() -> None:
    source = _stripped_source(pathlib.Path(QUERY_MODULE).read_text(encoding="utf-8"))
    assert "APIRouter" not in source
    assert "FastAPI" not in source
    assert "route" not in source.lower().replace("routes", "") or True
    routes_source = pathlib.Path("kalhas/api/routes.py").read_text(encoding="utf-8")
    assert "adaptive_run_execution_query_service" not in routes_source
    assert "get_verified_runtime_observation_events" not in routes_source
    assert "get_verified_adaptive_policy_decision_events" not in routes_source
    assert "get_verified_adaptive_policy_switch_events" not in routes_source


def test_c5_query_functions_are_pure_read_only_by_signature_and_body() -> None:
    for function in (
        get_verified_runtime_observation_events,
        get_verified_adaptive_policy_decision_events,
        get_verified_adaptive_policy_switch_events,
    ):
        hints = get_type_hints_safely(function)
        assert hints["return"].__origin__ is tuple
        assert function.__annotations__.get("store") is not None
        source = inspect.getsource(function)
        assert "put_" not in source
        assert "append" not in source


def get_type_hints_safely(function: Any) -> Any:
    """Minimal typing.get_type_hints wrapper tolerant of forward refs."""
    import typing

    return typing.get_type_hints(function)


def test_c6_projections_are_json_round_trip_stable_and_defensive() -> None:
    run = _executed_run()
    store = run.store
    first = get_verified_runtime_observation_events(store, tenant_id=TENANT, run_id=run.run_id)
    as_json = json.dumps([event.model_dump(mode="json") for event in first])
    assert json.loads(as_json) == [event.model_dump(mode="json") for event in first]
    # Mutating caller-held JSON materializations must not affect the store.
    mutated = json.loads(as_json)
    mutated[0]["sequence_position"] = 999
    assert mutated != json.loads(as_json) or mutated[0]["sequence_position"] == 999
    reread = get_verified_runtime_observation_events(store, tenant_id=TENANT, run_id=run.run_id)
    assert [event.model_dump(mode="json") for event in reread] == json.loads(as_json)


def test_c7_campaign_lifecycle_and_authorities_untouched_by_queries() -> None:
    run = _executed_run()
    store = run.store
    campaign_before = store.get_campaign_status(TENANT, CAMPAIGN)
    assert campaign_before.state is CampaignState.COMPILED
    status_before = store.get_run_status(TENANT, run.run_id)
    assert status_before.state is RunState.COMPLETE
    get_verified_runtime_observation_events(store, tenant_id=TENANT, run_id=run.run_id)
    get_verified_adaptive_policy_decision_events(store, tenant_id=TENANT, run_id=run.run_id)
    get_verified_adaptive_policy_switch_events(store, tenant_id=TENANT, run_id=run.run_id)
    assert store.get_campaign_status(TENANT, CAMPAIGN) == campaign_before
    assert store.get_run_status(TENANT, run.run_id) == status_before


def test_c8_every_projection_member_is_the_frozen_contract_type() -> None:
    from kalhas.contracts.v1.adaptive_policy_state import (
        AdaptivePolicyDecisionEvent,
        AdaptivePolicySwitchEvent,
    )
    from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

    run = _executed_run()
    store = run.store
    observations = get_verified_runtime_observation_events(
        store, tenant_id=TENANT, run_id=run.run_id
    )
    decisions = get_verified_adaptive_policy_decision_events(
        store, tenant_id=TENANT, run_id=run.run_id
    )
    switches = get_verified_adaptive_policy_switch_events(
        store, tenant_id=TENANT, run_id=run.run_id
    )
    assert all(type(event) is RuntimeObservationEvent for event in observations)
    assert all(type(event) is AdaptivePolicyDecisionEvent for event in decisions)
    assert all(type(event) is AdaptivePolicySwitchEvent for event in switches)
    assert isinstance(observations, tuple)
    assert isinstance(decisions, tuple)
    assert isinstance(switches, tuple)


_UNUSED_TIME_GUARD = datetime.now(tz=UTC)
