"""Phase 25 fail-closed mock LEGION strategy-declaration tests.

Amendment 4: the mock LEGION trajectory-plan boundary becomes
strategy-differentiated and fail-closed through the optional
``declared_transition_sequences`` constructor argument. Tests prove the
constructor's strict validation and immutable snapshotting; the
logical-id resolution in ``request_trajectory_plan`` (exact strategy-key
matching, order and repetition preservation, ambiguity and unknown-id
rejection with no canonical fallback and no partial draft); the unchanged
canonical default behavior; integration through the unchanged
``prepare_strategy_trajectory_plans`` binding chain for both runtime
2.0.0 and runtime 3.0.0 campaigns (exact authoritative transition
references, zero writes on invalid declarations, no input mutation); and
the boundary purity of the mock (no forbidden surfaces, no guard/target
reads during resolution, generic leak-free public errors).
"""

from __future__ import annotations

import copy
import inspect
from typing import Any, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.adapters.mocks.legion import MOCK_STRATEGY_LABELS
from kalhas.application.domain_errors import (
    InvalidTrajectoryDraftError,
    TrajectoryPlansNotFoundError,
)
from kalhas.application.domain_state_model_service import (
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    prepare_realization_campaign,
)
from kalhas.application.strategy_trajectory_service import (
    _revalidate_draft,
    get_strategy_trajectory_plans,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_compiler import compile_world
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.trajectory import (
    MAX_TRAJECTORY_PLAN_TRANSITIONS,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import (
    NOW,
    TENANT,
    build_request,
    build_scenario,
    prepare,
)
from tests.phase24_helpers import build_uncertainty_store, declare_model
from tests.phase25_helpers import RUNTIME_THREE_SEEDS, level_binding

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _request_stub() -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        required_observations=[],
        requested_at=NOW,
    )


def _candidate(identifier: str) -> StrategyCandidate:
    return (
        MockLegionAdapter()
        .request_strategies(_request_stub())[0]
        .model_copy(update={"identifier": identifier})
    )


def _build_model(
    *,
    state_model_id: str,
    manifest_id: str,
) -> DomainStateModel:
    model = DomainStateModel(
        identifier=state_model_identifier(
            scenario_id="scenario-1",
            manifest_id=manifest_id,
            state_model_id=state_model_id,
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
                identifier="status",
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="idle",
            ),
        ),
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return model.model_copy(update={"content_hash": state_model_content_hash(model)})


def _build_transition(model: DomainStateModel, *, transition_id: str) -> DomainStateTransition:
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=model.scenario_id,
            manifest_id=model.manifest_id,
            state_model_id=model.state_model_id,
            transition_id=transition_id,
        ),
        tenant_id=model.tenant_id,
        scenario_id=model.scenario_id,
        binding_id=model.binding_id,
        manifest_id=model.manifest_id,
        pack_id=model.pack_id,
        pack_version=model.pack_version,
        manifest_content_hash=model.manifest_content_hash,
        state_model_id=model.state_model_id,
        state_model_content_hash=model.content_hash,
        transition_id=transition_id,
        description="Declared state change",
        guard_values={"status": "idle"},
        target_values={"status": "active"},
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


def _request(
    *,
    strategy_identifier: str = "mock-baseline",
    transitions: tuple[DomainStateTransition, ...] | None = None,
) -> StrategyTrajectoryPlanRequest:
    """A boundary request with a three-transition available catalog (t-1a, t-1b, t-1c)."""
    model = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
    available = (
        transitions
        if transitions is not None
        else (
            _build_transition(model, transition_id="t-1a"),
            _build_transition(model, transition_id="t-1b"),
            _build_transition(model, transition_id="t-1c"),
        )
    )
    return StrategyTrajectoryPlanRequest(
        identifier="request-1",
        tenant_id=TENANT,
        campaign_id="campaign-1",
        scenario_id="scenario-1",
        world_version_id="world-1",
        world_content_hash=HASH_64,
        strategy_candidate=_candidate(strategy_identifier),
        strategy_content_hash=HASH_64,
        state_model=model,
        available_transitions=available,
        requested_at=NOW,
    )


def _canonical_identifiers(request: StrategyTrajectoryPlanRequest) -> tuple[str, ...]:
    return tuple(transition.identifier for transition in request.available_transitions)


def _declared_identifiers(
    request: StrategyTrajectoryPlanRequest, *logical_ids: str
) -> tuple[str, ...]:
    by_logical_id = {
        transition.transition_id: transition.identifier
        for transition in request.available_transitions
    }
    return tuple(by_logical_id[logical_id] for logical_id in logical_ids)


def _runtime_two_compiled_store() -> InMemoryScenarioStore:
    """A COMPILED runtime-2 campaign whose world embeds sm-1 and sm-2.

    Both models carry the same logical transition ids (t-1, t-2) - logical
    ids are per model - with distinct deterministic identifiers per model,
    so a single strategy declaration resolves per model. The full plan
    matrix is 5 strategies x 2 models = 10 plans.
    """
    store = InMemoryScenarioStore()
    scenario = build_scenario()
    store.put_scenario(scenario)
    sm_1 = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
    sm_2 = _build_model(state_model_id="sm-2", manifest_id="manifest-2")
    transitions = (
        _build_transition(sm_1, transition_id="t-1"),
        _build_transition(sm_1, transition_id="t-2"),
        _build_transition(sm_2, transition_id="t-1"),
        _build_transition(sm_2, transition_id="t-2"),
    )
    compiled = compile_world(scenario, state_models=(sm_1, sm_2), transitions=transitions)
    store.put_world(compiled.version, compiled.manifest)
    prepare(
        store,
        compiled.version.identifier,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
    )
    return store


def _runtime_three_compiled_store() -> InMemoryScenarioStore:
    """A COMPILED runtime-3 campaign whose world embeds sm-1 with transition t-1.

    Prepared through the real runtime-3 preparation seam with the mock
    ensemble and two seeds, so the full plan matrix is 5 strategies x 1
    model = 5 plans.
    """
    store = build_uncertainty_store()
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id="t-1",
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
        transition_id="t-1",
        description="Declared state change",
        guard_values={"status": "idle"},
        target_values={"status": "active"},
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three declaration campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    return store


class TestConstructorValidation:
    def test_none_accepted(self) -> None:
        adapter = MockLegionAdapter()
        assert adapter._declared_transition_sequences == {}
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_empty_mapping_accepted(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={})
        assert adapter._declared_transition_sequences == {}
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    @pytest.mark.parametrize(
        "sequence",
        [
            ["t-1a"],
            ("t-1a",),
            ["t-1a", "t-1b", "t-1c"],
            ["t-1a", "t-1b", "t-1a"],
        ],
    )
    def test_dict_list_and_tuple_sequences_accepted(self, sequence: Any) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": sequence})
        assert adapter._declared_transition_sequences == {"mock-baseline": tuple(sequence)}

    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences=cast(Any, ["t-1a"]))
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences=cast(Any, "t-1a"))

    @pytest.mark.parametrize("key", ["", cast(Any, 123), cast(Any, None)])
    def test_empty_or_non_string_strategy_keys_rejected(self, key: Any) -> None:
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences={key: ["t-1a"]})

    @pytest.mark.parametrize("value", [cast(Any, "t-1a"), cast(Any, range(3))])
    def test_string_or_arbitrary_sequence_values_rejected(self, value: Any) -> None:
        # Strings and arbitrary Sequence implementations (range) are never
        # accepted - only list or tuple.
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences={"mock-baseline": value})

    @pytest.mark.parametrize("sequence", [[], ()])
    def test_empty_sequence_rejected(self, sequence: Any) -> None:
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences={"mock-baseline": sequence})

    def test_sequence_over_max_rejected(self) -> None:
        over = [f"t-{index}" for index in range(MAX_TRAJECTORY_PLAN_TRANSITIONS + 1)]
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences={"mock-baseline": over})

    def test_exactly_one_and_exactly_max_accepted(self) -> None:
        one = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-1a"]})
        assert one._declared_transition_sequences == {"mock-baseline": ("t-1a",)}
        max_sequence = [f"t-{index}" for index in range(MAX_TRAJECTORY_PLAN_TRANSITIONS)]
        many = MockLegionAdapter(declared_transition_sequences={"mock-baseline": max_sequence})
        assert many._declared_transition_sequences["mock-baseline"] == tuple(max_sequence)

    @pytest.mark.parametrize("entry", ["", cast(Any, 123)])
    def test_empty_or_non_string_entries_rejected(self, entry: Any) -> None:
        with pytest.raises(ValueError):
            MockLegionAdapter(declared_transition_sequences={"mock-baseline": [entry]})

    def test_snapshot_is_immutable_tuples(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a", "t-1b", "t-1a"]}
        )
        snapshot = adapter._declared_transition_sequences
        assert snapshot == {"mock-baseline": ("t-1a", "t-1b", "t-1a")}
        assert isinstance(snapshot["mock-baseline"], tuple)
        # Repetitions are preserved - never deduplicated or sorted.

    def test_source_mapping_mutation_after_construction_is_inert(self) -> None:
        declarations: dict[str, list[str]] = {"mock-baseline": ["t-1a", "t-1b"]}
        adapter = MockLegionAdapter(declared_transition_sequences=declarations)
        declarations["mock-baseline"] = ["t-9"]
        declarations["mock-adaptive"] = ["t-1a"]
        declarations.clear()
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _declared_identifiers(
            request, "t-1a", "t-1b"
        )

    def test_nested_source_list_mutation_is_inert(self) -> None:
        declarations: dict[str, list[str]] = {"mock-baseline": ["t-1a", "t-1b"]}
        adapter = MockLegionAdapter(declared_transition_sequences=declarations)
        declarations["mock-baseline"].append("t-1c")
        declarations["mock-baseline"][0] = "t-9"
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _declared_identifiers(
            request, "t-1a", "t-1b"
        )


class TestResolution:
    def test_default_adapter_returns_canonical_identifiers(self) -> None:
        adapter = MockLegionAdapter()
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.request_id == request.identifier
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_empty_mapping_returns_canonical_default(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={})
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_missing_strategy_key_returns_canonical_default(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-adaptive": ["t-1a"]})
        request = _request(strategy_identifier="mock-baseline")
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_explicit_declaration_resolves_logical_to_deterministic_identifiers(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1b", "t-1a", "t-1c"]}
        )
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _declared_identifiers(
            request, "t-1b", "t-1a", "t-1c"
        )

    def test_reversed_declaration_preserves_reversed_order(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1c", "t-1b", "t-1a"]}
        )
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _declared_identifiers(
            request, "t-1c", "t-1b", "t-1a"
        )

    def test_repeated_logical_ids_preserve_exact_repetitions(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a", "t-1b", "t-1a", "t-1a"]}
        )
        request = _request()
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _declared_identifiers(
            request, "t-1a", "t-1b", "t-1a", "t-1a"
        )

    def test_unknown_logical_id_raises_no_draft_no_canonical_fallback(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a", "t-unknown"]}
        )
        with pytest.raises(InvalidTrajectoryDraftError) as exc_info:
            adapter.request_trajectory_plan(_request())
        assert (
            cast(Any, exc_info.value).reason
            == "declared transition id is not in the available catalog"
        )
        # A wholly unknown declaration never substitutes the canonical sequence.
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-unknown"]})
        with pytest.raises(InvalidTrajectoryDraftError):
            adapter.request_trajectory_plan(_request())

    def test_duplicate_logical_id_in_catalog_raises_ambiguity(self) -> None:
        model = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
        first = _build_transition(model, transition_id="t-1a")
        duplicate = first.model_copy(
            update={"identifier": "transition-foreign", "content_hash": HASH_64}
        )
        request = _request(transitions=(first, duplicate))
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-1a"]})
        with pytest.raises(InvalidTrajectoryDraftError) as exc_info:
            adapter.request_trajectory_plan(request)
        assert cast(Any, exc_info.value).reason == "available transition catalog is ambiguous"

    def test_declarations_keyed_by_exact_strategy_identifier(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-1a"]})
        exact = adapter.request_trajectory_plan(_request(strategy_identifier="mock-baseline"))
        assert exact.ordered_transition_identifiers == _declared_identifiers(
            _request(strategy_identifier="mock-baseline"), "t-1a"
        )
        # A distinct identifier never matches the declaration.
        request = _request(strategy_identifier="mock-baseline-2")
        draft = adapter.request_trajectory_plan(request)
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_two_declared_strategies_produce_genuinely_different_drafts(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={
                "mock-baseline": ["t-1a", "t-1b"],
                "mock-conservative": ["t-1c"],
            }
        )
        baseline = adapter.request_trajectory_plan(_request(strategy_identifier="mock-baseline"))
        conservative = adapter.request_trajectory_plan(
            _request(strategy_identifier="mock-conservative")
        )
        assert (
            baseline.ordered_transition_identifiers != conservative.ordered_transition_identifiers
        )
        assert baseline.ordered_transition_identifiers == _declared_identifiers(
            _request(strategy_identifier="mock-baseline"), "t-1a", "t-1b"
        )
        assert conservative.ordered_transition_identifiers == _declared_identifiers(
            _request(strategy_identifier="mock-conservative"), "t-1c"
        )

    def test_undeclared_remaining_strategies_retain_canonical_behavior(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-1a"]})
        for identifier in (
            "mock-conservative",
            "mock-balanced",
            "mock-adaptive",
            "mock-diversified",
        ):
            request = _request(strategy_identifier=identifier)
            draft = adapter.request_trajectory_plan(request)
            assert draft.ordered_transition_identifiers == _canonical_identifiers(request)

    def test_guards_targets_and_state_values_never_read(self) -> None:
        model = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
        first = _build_transition(model, transition_id="t-1a")
        second = _build_transition(model, transition_id="t-1b")
        plain = _request(transitions=(first, second))
        extreme = _request(
            transitions=(
                first.model_copy(
                    update={
                        "guard_values": {"status": "bizarre"},
                        "target_values": {"status": "extreme"},
                    }
                ),
                second.model_copy(
                    update={
                        "guard_values": {"status": "other"},
                        "target_values": {"status": "another"},
                    }
                ),
            )
        )
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1b", "t-1a"]}
        )
        assert adapter.request_trajectory_plan(plain) == adapter.request_trajectory_plan(extreme)

    def test_no_input_mutation_during_resolution(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1b", "t-1a"]}
        )
        request = _request()
        before = copy.deepcopy(request)
        adapter.request_trajectory_plan(request)
        assert request == before

    def test_request_strategies_unchanged(self) -> None:
        plain = MockLegionAdapter().request_strategies(_request_stub())
        declared = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a"]}
        ).request_strategies(_request_stub())
        assert declared == plain
        assert [candidate.identifier for candidate in plain] == [
            f"mock-{label}" for label in MOCK_STRATEGY_LABELS
        ]

    def test_subclass_without_super_init_keeps_canonical_behavior(self) -> None:
        # Historical subclasses override __init__ without calling super;
        # they must stay on the exact canonical path.

        class _CountingLegion(MockLegionAdapter):
            def __init__(self) -> None:
                self.calls = 0

            def request_trajectory_plan(
                self, request: StrategyTrajectoryPlanRequest
            ) -> StrategyTrajectoryPlanDraft:
                self.calls += 1
                return super().request_trajectory_plan(request)

        legion = _CountingLegion()
        request = _request()
        draft = legion.request_trajectory_plan(request)
        assert legion.calls == 1
        assert draft.ordered_transition_identifiers == _canonical_identifiers(request)


class TestIntegration:
    def _by_pair(self, plans: tuple[Any, ...]) -> dict[tuple[str, str], Any]:
        return {(plan.strategy_candidate_id, plan.state_model_id): plan for plan in plans}

    def test_runtime_two_declared_sequence_becomes_authoritative_references(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={
                "mock-baseline": ["t-2", "t-1", "t-2"],
                "mock-conservative": ["t-1"],
            }
        )
        store = _runtime_two_compiled_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(plans) == 10
        by_pair = self._by_pair(plans)
        baseline_sm_1 = by_pair[("mock-baseline", "sm-1")]
        # Exact declared order with repetitions preserved.
        assert [r.transition_id for r in baseline_sm_1.transition_references] == [
            "t-2",
            "t-1",
            "t-2",
        ]
        # Deterministic identifiers and content hashes bound from the
        # authoritative closed catalog.
        sm_1 = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
        expected_t_2 = transition_identifier(
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-2",
        )
        assert baseline_sm_1.transition_references[0].transition_identifier == expected_t_2
        authoritative_t_2 = _build_transition(sm_1, transition_id="t-2")
        assert (
            baseline_sm_1.transition_references[0].transition_content_hash
            == authoritative_t_2.content_hash
        )
        # The same declaration resolves per model: sm-2's t-2 carries a
        # distinct deterministic identifier.
        baseline_sm_2 = by_pair[("mock-baseline", "sm-2")]
        assert [r.transition_id for r in baseline_sm_2.transition_references] == [
            "t-2",
            "t-1",
            "t-2",
        ]
        assert baseline_sm_2.transition_references[
            0
        ].transition_identifier == transition_identifier(
            scenario_id="scenario-1",
            manifest_id="manifest-2",
            state_model_id="sm-2",
            transition_id="t-2",
        )
        assert (
            baseline_sm_1.transition_references[0].transition_identifier
            != baseline_sm_2.transition_references[0].transition_identifier
        )
        # Undeclared strategies retain the canonical sequence.
        assert [
            r.transition_id for r in by_pair[("mock-balanced", "sm-1")].transition_references
        ] == ["t-1", "t-2"]
        # The declared conservative sequence resolves on both models.
        assert [
            r.transition_id for r in by_pair[("mock-conservative", "sm-2")].transition_references
        ] == ["t-1"]
        # Stored plans re-verify through the unchanged read path.
        stored = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert stored == plans

    def test_runtime_two_invalid_declaration_causes_zero_writes(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a", "t-unknown"]}
        )
        store = _runtime_two_compiled_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_invalid_declaration_for_later_strategy_still_zero_writes(self) -> None:
        # mock-adaptive is the fourth strategy: six requests succeed before
        # the failure, yet the complete matrix is built before any write.
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-adaptive": ["t-unknown"]})
        store = _runtime_two_compiled_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_runtime_two_no_mutation_of_store_or_declarations(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-2", "t-1"]})
        store = _runtime_two_compiled_store()
        campaign_before = store.get_campaign(TENANT, "campaign-1")
        run_plans_before = store.get_run_plans(TENANT, "campaign-1")
        declarations_before = copy.deepcopy(adapter._declared_transition_sequences)
        prepare_strategy_trajectory_plans(
            store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.get_campaign(TENANT, "campaign-1") == campaign_before
        assert store.get_run_plans(TENANT, "campaign-1") == run_plans_before
        assert adapter._declared_transition_sequences == declarations_before

    def test_runtime_three_preparation_resolves_declarations(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={
                "mock-baseline": ["t-1", "t-1"],
                "mock-conservative": ["t-1"],
            }
        )
        store = _runtime_three_compiled_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
        )
        # 5 strategies x 1 transition-capable model.
        assert len(plans) == 5
        by_pair = self._by_pair(plans)
        baseline = by_pair[("mock-baseline", "sm-1")]
        assert [r.transition_id for r in baseline.transition_references] == ["t-1", "t-1"]
        conservative = by_pair[("mock-conservative", "sm-1")]
        assert [r.transition_id for r in conservative.transition_references] == ["t-1"]
        # Undeclared strategies retain canonical behavior.
        balanced = by_pair[("mock-balanced", "sm-1")]
        assert [r.transition_id for r in balanced.transition_references] == ["t-1"]
        # Authoritative binding from the closed runtime-3 world catalog.
        world = store.get_world(TENANT, store.get_campaign(TENANT, "campaign-1").world_version_id)
        authoritative = next(
            transition
            for transition in extract_world_catalog(world).transitions
            if transition.transition_id == "t-1"
        )
        assert baseline.transition_references[0].transition_identifier == authoritative.identifier
        assert (
            baseline.transition_references[0].transition_content_hash == authoritative.content_hash
        )
        # Stored plans re-verify through the unchanged read path.
        stored = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert stored == plans

    def test_runtime_three_invalid_declaration_causes_zero_writes(self) -> None:
        adapter = MockLegionAdapter(declared_transition_sequences={"mock-adaptive": ["t-unknown"]})
        store = _runtime_three_compiled_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store, legion=adapter, tenant_id=TENANT, campaign_id="campaign-1"
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_declared_draft_flows_through_existing_revalidation(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1b", "t-1a"]}
        )
        draft = adapter.request_trajectory_plan(_request())
        validated = _revalidate_draft(draft)
        assert validated == draft
        assert validated.request_id == draft.request_id


class TestBoundaryPurity:
    def test_mock_source_has_no_forbidden_surfaces(self) -> None:
        from kalhas.adapters.mocks import legion as legion_module

        source = inspect.getsource(legion_module)
        assert "import random" not in source
        assert "datetime.now" not in source
        assert "time.time(" not in source
        assert "urllib" not in source
        assert "requests" not in source
        assert "socket" not in source
        assert "open(" not in source
        assert "numpy" not in source
        assert "pandas" not in source
        assert "from kalhas.adapters.legion" not in source
        assert "import nexus" not in source
        assert "kalhas.api" not in source
        assert "routes" not in source

    def test_declaration_resolution_never_reads_guard_or_target_fields(self) -> None:
        from kalhas.adapters.mocks import legion as legion_module

        method_source = inspect.getsource(legion_module.MockLegionAdapter.request_trajectory_plan)
        assert "guard_values" not in method_source
        assert "target_values" not in method_source
        assert "state_field" not in method_source

    def test_public_error_messages_never_leak_supplied_values(self) -> None:
        adapter = MockLegionAdapter(
            declared_transition_sequences={"mock-baseline": ["t-1a", "t-secret-logical"]}
        )
        with pytest.raises(InvalidTrajectoryDraftError) as exc_info:
            adapter.request_trajectory_plan(_request())
        message = str(exc_info.value)
        assert "invalid" in message
        for leaked in ("t-secret-logical", "t-1a", HASH_64, "mock-baseline", "idle", "active"):
            assert leaked not in message
        # The ambiguity rejection is equally leak-free.
        model = _build_model(state_model_id="sm-1", manifest_id="manifest-1")
        first = _build_transition(model, transition_id="t-1a")
        duplicate = first.model_copy(
            update={"identifier": "transition-foreign", "content_hash": HASH_64}
        )
        ambiguous = MockLegionAdapter(declared_transition_sequences={"mock-baseline": ["t-1a"]})
        with pytest.raises(InvalidTrajectoryDraftError) as exc_info:
            ambiguous.request_trajectory_plan(_request(transitions=(first, duplicate)))
        message = str(exc_info.value)
        assert "invalid" in message
        for leaked in ("t-1a", "transition-foreign", HASH_64, "mock-baseline"):
            assert leaked not in message
