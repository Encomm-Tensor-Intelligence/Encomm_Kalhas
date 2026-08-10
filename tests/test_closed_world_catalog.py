"""Phase 15 closed-world-catalog tests.

The trajectory-planning catalog is *closed*: every transition embedded
in a compiled world must map to exactly one embedded state model by its
exact ownership key (``manifest_id``, ``state_model_id``,
``state_model_content_hash``), with deterministic identifiers and no
duplicates. These tests build compiler-consistent worlds (they pass
Phase 14 recompilation verification) that violate closure, and prove
every violation is rejected with a safe typed integrity error BEFORE the
first LEGION request - and that the stored-plan getter uses the same
closed construction.
"""

from __future__ import annotations

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import WorldSnapshotIntegrityError
from kalhas.application.domain_state_model_service import (
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.strategy_trajectory_service import (
    _closed_world_catalogs,
    get_strategy_trajectory_plans,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import NOW, TENANT, build_scenario, prepare

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _model(
    state_model_id: str = "sm-1",
    *,
    manifest_id: str = "manifest-1",
    field: str = "status",
    initial_value: str = "idle",
    identifier: str | None = None,
) -> DomainStateModel:
    """A model with a deterministic identifier and self-consistent hash.

    When ``identifier`` is supplied the caller is deliberately tampering
    the identity; the content hash is still recomputed over the tampered
    record so the model is self-consistent and only the check under test
    can catch it.
    """
    model = DomainStateModel(
        identifier=(
            identifier
            if identifier is not None
            else state_model_identifier(
                scenario_id="scenario-1", manifest_id=manifest_id, state_model_id=state_model_id
            )
        ),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id=f"binding-{state_model_id}",
        manifest_id=manifest_id,
        pack_id=f"pack-{state_model_id}",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id=state_model_id,
        state_fields=(
            DomainStateFieldDefinition(
                identifier=field,
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value=initial_value,
            ),
        ),
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return model.model_copy(update={"content_hash": state_model_content_hash(model)})


def _transition(
    model: DomainStateModel,
    *,
    transition_id: str = "t-1",
    guard_value: str = "idle",
    target_value: str = "active",
    state_model_id: str | None = None,
    state_model_content_hash: str | None = None,
    identifier: str | None = None,
) -> DomainStateTransition:
    """A transition with a deterministic identifier and self-consistent hash.

    Caller-supplied ``state_model_id`` / ``state_model_content_hash`` /
    ``identifier`` are deliberate tampers; the transition content hash is
    recomputed over the tampered record so the tamper is self-consistent.
    """
    referenced_model_id = state_model_id if state_model_id is not None else model.state_model_id
    referenced_hash = (
        state_model_content_hash if state_model_content_hash is not None else model.content_hash
    )
    field = model.state_fields[0].identifier
    transition = DomainStateTransition(
        identifier=(
            identifier
            if identifier is not None
            else transition_identifier(
                scenario_id=model.scenario_id,
                manifest_id=model.manifest_id,
                state_model_id=referenced_model_id,
                transition_id=transition_id,
            )
        ),
        tenant_id=model.tenant_id,
        scenario_id=model.scenario_id,
        binding_id=model.binding_id,
        manifest_id=model.manifest_id,
        pack_id=model.pack_id,
        pack_version=model.pack_version,
        manifest_content_hash=model.manifest_content_hash,
        state_model_id=referenced_model_id,
        state_model_content_hash=referenced_hash,
        transition_id=transition_id,
        description="Declared state change",
        guard_values={field: guard_value},
        target_values={field: target_value},
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


def _store_with_world(
    *,
    state_models: tuple[DomainStateModel, ...],
    transitions: tuple[DomainStateTransition, ...],
) -> tuple[InMemoryScenarioStore, str]:
    """A COMPILED campaign whose world embeds the given snapshot families.

    The world is compiled from the supplied snapshots and therefore
    passes Phase 14 recompilation verification - any rejection below can
    only come from the closed-catalog closure checks.
    """
    store = InMemoryScenarioStore()
    store.put_scenario(build_scenario())
    compiled = compile_world(
        build_scenario(),
        state_models=state_models,
        transitions=transitions,
    )
    store.put_world(compiled.version, compiled.manifest)
    prepare(store, compiled.version.identifier, runtime_version="2.0.0")
    return store, compiled.version.identifier


class _CountingLegion(MockLegionAdapter):
    """MockLegionAdapter wrapper recording every trajectory request."""

    def __init__(self) -> None:
        self.requests: list[StrategyTrajectoryPlanRequest] = []

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.requests.append(request)
        return super().request_trajectory_plan(request)


def _expect_rejected_before_legion(store: InMemoryScenarioStore, fragment: str) -> None:
    legion = _CountingLegion()
    with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
        prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
    assert exc_info.value.reason is not None
    assert fragment in exc_info.value.reason
    assert legion.requests == []


class TestClosedWorldCatalogRejections:
    def test_orphan_transition_rejected_before_legion(self) -> None:
        model = _model()
        transitions = (
            _transition(model, transition_id="t-1a"),
            _transition(model, transition_id="t-orphan", state_model_id="sm-ghost"),
        )
        store, _ = _store_with_world(state_models=(model,), transitions=transitions)
        _expect_rejected_before_legion(store, "embedded transition has no matching state model")

    def test_state_model_content_hash_grouping_mismatch_rejected(self) -> None:
        model = _model()
        transitions = (
            _transition(model, transition_id="t-1a"),
            _transition(model, transition_id="t-1b", state_model_content_hash="f" * 64),
        )
        store, _ = _store_with_world(state_models=(model,), transitions=transitions)
        _expect_rejected_before_legion(
            store, "embedded transition state-model content hash mismatch"
        )

    def test_duplicate_state_model_identifier_rejected(self) -> None:
        # Same (manifest, state-model id) but different field content:
        # distinct ownership keys, identical deterministic identifiers.
        model_a = _model(field="status", initial_value="idle")
        model_b = _model(field="status", initial_value="busy")
        store, _ = _store_with_world(
            state_models=(model_a, model_b),
            transitions=(
                _transition(model_a, transition_id="t-1a"),
                _transition(model_b, transition_id="t-1b"),
            ),
        )
        _expect_rejected_before_legion(store, "duplicate state model identifiers")

    def test_duplicate_state_model_ownership_key_rejected(self) -> None:
        # Two byte-identical models share the exact ownership key.
        model = _model()
        store, _ = _store_with_world(
            state_models=(model, model),
            transitions=(_transition(model, transition_id="t-1a"),),
        )
        _expect_rejected_before_legion(store, "duplicate state model ownership keys")

    def test_duplicate_transition_identifier_rejected(self) -> None:
        model = _model()
        transitions = (
            _transition(model, transition_id="t-1a", target_value="active"),
            _transition(model, transition_id="t-1a", target_value="paused"),
        )
        store, _ = _store_with_world(state_models=(model,), transitions=transitions)
        _expect_rejected_before_legion(store, "duplicate transition identifiers")

    def test_non_deterministic_state_model_identifier_rejected(self) -> None:
        model = _model(identifier="state-model-999")
        store, _ = _store_with_world(
            state_models=(model,),
            transitions=(_transition(model, transition_id="t-1a"),),
        )
        _expect_rejected_before_legion(
            store, "embedded state model identifier is not deterministic"
        )

    def test_non_deterministic_transition_identifier_rejected(self) -> None:
        model = _model()
        transition = _transition(model, identifier="transition-custom")
        store, _ = _store_with_world(state_models=(model,), transitions=(transition,))
        _expect_rejected_before_legion(store, "embedded transition identifier is not deterministic")

    def test_public_message_leaks_no_hashes_or_values(self) -> None:
        model = _model()
        transitions = (
            _transition(model, transition_id="t-1a"),
            _transition(model, transition_id="t-orphan", state_model_id="sm-ghost"),
        )
        store, _ = _store_with_world(state_models=(model,), transitions=transitions)
        legion = _CountingLegion()
        with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        message = str(exc_info.value)
        assert HASH_64 not in message
        assert "sm-ghost" not in message
        assert "pwned" not in message
        assert legion.requests == []


class TestClosedWorldCatalogAccepts:
    def test_valid_world_yields_the_full_matrix(self) -> None:
        model_a = _model(state_model_id="sm-1", field="status", initial_value="idle")
        model_b = _model(
            state_model_id="sm-2", manifest_id="manifest-2", field="mode", initial_value="off"
        )
        transitions = (
            _transition(model_a, transition_id="t-1a", guard_value="idle", target_value="active"),
            _transition(model_a, transition_id="t-1b", guard_value="active", target_value="idle"),
            _transition(model_b, transition_id="t-2a", guard_value="off", target_value="on"),
        )
        store, world_id = _store_with_world(
            state_models=(model_a, model_b), transitions=transitions
        )
        world = store.get_world(TENANT, world_id)
        catalogs = _closed_world_catalogs(world)
        assert [catalog.state_model.state_model_id for catalog in catalogs] == ["sm-1", "sm-2"]
        assert [len(catalog.transitions) for catalog in catalogs] == [2, 1]
        legion = _CountingLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(plans) == 10  # 5 strategies x 2 capable models
        assert len(legion.requests) == 10

    def test_model_with_zero_transitions_remains_ignored(self) -> None:
        model_a = _model(state_model_id="sm-1", field="status", initial_value="idle")
        model_b = _model(
            state_model_id="sm-2", manifest_id="manifest-2", field="mode", initial_value="off"
        )
        store, world_id = _store_with_world(
            state_models=(model_a, model_b),
            transitions=(_transition(model_a, transition_id="t-1a"),),
        )
        world = store.get_world(TENANT, world_id)
        catalogs = _closed_world_catalogs(world)
        assert len(catalogs) == 1
        assert catalogs[0].state_model.state_model_id == "sm-1"
        legion = _CountingLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(plans) == 5
        assert len(legion.requests) == 5

    def test_world_without_any_transitions_stays_valid(self) -> None:
        model = _model()
        store, world_id = _store_with_world(state_models=(model,), transitions=())
        world = store.get_world(TENANT, world_id)
        assert _closed_world_catalogs(world) == ()
        legion = _CountingLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert plans == ()
        assert legion.requests == []


class TestGetterUsesTheClosedCatalog:
    def test_getter_rejects_orphan_worlds_like_planning_does(self) -> None:
        """The stored-plan getter must use the same closed construction.

        A prepared (empty) collection exists in the store, but the world
        carries an orphan transition: the getter rejects it with the same
        typed integrity error instead of the raw-catalog path.
        """
        model = _model()
        transitions = (
            _transition(model, transition_id="t-1a"),
            _transition(model, transition_id="t-orphan", state_model_id="sm-ghost"),
        )
        store, _ = _store_with_world(state_models=(model,), transitions=transitions)
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = ()
        with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "embedded transition has no matching state model" in exc_info.value.reason
