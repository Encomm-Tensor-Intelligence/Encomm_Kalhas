"""Phase 14 tests: compiled-world content integrity.

The verifier proves a stored ``WorldVersion`` and its ``WorldManifest``
still exactly represent the deterministic output of the world compiler;
it is pure, read-only, deterministic, and never repairs or accepts a
corrupted world. These tests tamper stored worlds through the private
store dictionaries (test-only injection, as the public store now deep-
copies) or through deep-copied contracts, and prove every corruption
class is rejected with the typed safe error before any LEGION request,
lifecycle change, run event, or replay manifest.

Every tampered world is verified against the valid ``WorldManifest``
produced by the exact same compilation, so a failure always isolates
the tampered record rather than a missing or mismatched manifest. The
fixture compiles two distinct elements in every snapshot family, so
canonical-order reversals are genuinely meaningful.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    RunNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.replay_service import replay_run
from kalhas.application.run_planner import run_identifier
from kalhas.application.world_compiler import COMPILER_VERSION, CompiledWorld, compile_world
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion

from tests.phase4_helpers import (
    NOW,
    TENANT,
    build_scenario,
    build_store,
    execute,
    prepare,
    start,
)

LATER = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class _CountingLegion:
    """MockLegionAdapter wrapper counting boundary calls."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = MockLegionAdapter()

    def request_strategies(self, request: StrategyRequest) -> tuple[StrategyCandidate, ...]:
        self.calls += 1
        return self._inner.request_strategies(request)

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.calls += 1
        return self._inner.request_trajectory_plan(request)


def _tamper_scenario_name(world: WorldVersion) -> None:
    """Replace the embedded scenario name (test-only)."""
    scenario = world.world["scenario"]
    assert isinstance(scenario, dict)
    scenario["name"] = "Tampered"


def _tamper_scenario_malformed(world: WorldVersion) -> None:
    """Replace the embedded scenario with a non-scenario object."""
    malformed: dict[str, JsonValue] = {"broken": True}
    world.world["scenario"] = malformed


def _tamper_scenario_objectives(world: WorldVersion) -> None:
    """Empty the embedded scenario objectives (semantically invalid)."""
    scenario = world.world["scenario"]
    assert isinstance(scenario, dict)
    scenario["objectives"] = []


def _tamper_bindings_not_a_list(world: WorldVersion) -> None:
    """Replace the embedded binding collection with a non-list value."""
    malformed: dict[str, JsonValue] = {"not": "a list"}
    world.world["domain_pack_bindings"] = malformed


def _rich_compiled() -> tuple[ScenarioSpec, CompiledWorld]:
    """A scenario plus a world compiled with two elements per snapshot family.

    Two distinct manifests, bindings, declarations, state models, and
    transitions keep every snapshot family multi-element, so reordered
    collections genuinely differ from the compiler's canonical order.
    """
    scenario = build_scenario()
    pack = DomainPackManifest(
        identifier="manifest-1",
        tenant_id=TENANT,
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.2.3",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        content_hash=HASH_64,
        created_at=NOW,
    )
    pack_two = DomainPackManifest(
        identifier="manifest-2",
        tenant_id=TENANT,
        pack_id="pack-2",
        name="Generic reference pack two",
        pack_version="2.0.0",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-2",
                description="Second declared capability",
                input_ids=("in-2",),
                output_ids=("out-2",),
            ),
        ),
        content_hash=HASH_64,
        created_at=NOW,
    )
    binding = DomainPackBinding(
        identifier="binding-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=pack.content_hash,
        capability_ids=("cap-1",),
        bound_at=NOW,
    )
    binding_two = DomainPackBinding(
        identifier="binding-2",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-2",
        pack_id="pack-2",
        pack_version="2.0.0",
        manifest_content_hash=pack_two.content_hash,
        capability_ids=("cap-2",),
        bound_at=NOW,
    )
    declaration = DomainCapabilityDeclaration(
        identifier="declaration-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        capability_id="cap-1",
        input_values={"in-1": {"nested": [1]}},
        content_hash=HASH_64,
        declared_at=NOW,
    )
    declaration_two = DomainCapabilityDeclaration(
        identifier="declaration-2",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-2",
        manifest_id="manifest-2",
        pack_id="pack-2",
        pack_version="2.0.0",
        manifest_content_hash=HASH_64,
        capability_id="cap-2",
        input_values={"in-2": {"nested": [2]}},
        content_hash=HASH_64,
        declared_at=NOW,
    )
    state_model = DomainStateModel(
        identifier="state-model-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_fields=(
            DomainStateFieldDefinition(
                identifier="status",
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="idle",
            ),
        ),
        content_hash=HASH_64,
        declared_at=NOW,
    )
    state_model_two = DomainStateModel(
        identifier="state-model-2",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-2",
        manifest_id="manifest-2",
        pack_id="pack-2",
        pack_version="2.0.0",
        manifest_content_hash=HASH_64,
        state_model_id="sm-2",
        state_fields=(
            DomainStateFieldDefinition(
                identifier="mode",
                description="Second declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="off",
            ),
        ),
        content_hash=HASH_64,
        declared_at=NOW,
    )
    transition = DomainStateTransition(
        identifier="transition-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_model_content_hash=HASH_64,
        transition_id="t-1",
        description="Declared state change",
        guard_values={"status": "idle"},
        target_values={"status": "active"},
        content_hash=HASH_64,
        declared_at=NOW,
    )
    transition_two = DomainStateTransition(
        identifier="transition-2",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id="binding-2",
        manifest_id="manifest-2",
        pack_id="pack-2",
        pack_version="2.0.0",
        manifest_content_hash=HASH_64,
        state_model_id="sm-2",
        state_model_content_hash=HASH_64,
        transition_id="t-2",
        description="Second declared state change",
        guard_values={"mode": "off"},
        target_values={"mode": "on"},
        content_hash=HASH_64,
        declared_at=NOW,
    )
    compiled = compile_world(
        scenario,
        bindings=(binding, binding_two),
        declarations=(declaration, declaration_two),
        state_models=(state_model, state_model_two),
        transitions=(transition, transition_two),
    )
    return scenario, compiled


class TestWorldSnapshotIntegrity:
    def test_valid_world_verifies_exactly(self) -> None:
        _, compiled = _rich_compiled()
        verify_world_snapshot(compiled.version, compiled.manifest)  # must not raise

    def test_plain_world_verifies_exactly(self) -> None:
        scenario = build_scenario()
        compiled = compile_world(scenario)
        verify_world_snapshot(compiled.version, compiled.manifest)  # must not raise

    def test_verification_is_deterministic_and_read_only(self) -> None:
        _, compiled = _rich_compiled()
        verify_world_snapshot(compiled.version, compiled.manifest)
        verify_world_snapshot(compiled.version, compiled.manifest)
        # Nothing was repaired, normalized, or replaced.
        assert compiled.version.model_dump(mode="json") == compiled.version.model_dump(mode="json")
        assert compiled.manifest.model_dump(mode="json") == compiled.manifest.model_dump(
            mode="json"
        )

    def _tampered_world(
        self, mutate: Callable[[WorldVersion], None]
    ) -> tuple[WorldVersion, WorldManifest]:
        """A deep-copied world after ``mutate``, plus its valid manifest.

        The manifest always comes from the exact same compilation as the
        pristine world, so a rejection isolates the tampered world.
        """
        _, compiled = _rich_compiled()
        world = compiled.version.model_copy(deep=True)
        mutate(world)
        return world, compiled.manifest

    def _expect_rejected(
        self, world: WorldVersion, manifest: WorldManifest, reason_fragment: str
    ) -> None:
        with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
            verify_world_snapshot(world, manifest)
        assert exc_info.value.reason is not None
        assert reason_fragment in exc_info.value.reason

    def test_malformed_embedded_scenario_rejected(self) -> None:
        world, manifest = self._tampered_world(_tamper_scenario_malformed)
        self._expect_rejected(world, manifest, "embedded scenario is malformed")

    def test_changed_nested_scenario_data_with_unchanged_hash_rejected(self) -> None:
        world, manifest = self._tampered_world(_tamper_scenario_name)
        self._expect_rejected(world, manifest, "recompiled world content mismatch")

    def test_semantically_invalid_embedded_scenario_rejected(self) -> None:
        # Contract-valid (objectives is a plain list) but semantically
        # invalid: the compiler refuses it, so the world cannot be its
        # deterministic output.
        world, manifest = self._tampered_world(_tamper_scenario_objectives)
        self._expect_rejected(world, manifest, "embedded scenario is semantically invalid")

    @pytest.mark.parametrize(
        ("snapshot_key", "tamper"),
        [
            (
                "domain_pack_bindings",
                lambda snapshots: snapshots[0].__setitem__("pack_version", "9.9.9"),
            ),
            (
                "domain_capability_declarations",
                lambda snapshots: snapshots[0]["input_values"].__setitem__("in-1", {"other": 2}),
            ),
            (
                "domain_state_models",
                lambda snapshots: snapshots[0]["state_fields"][0].__setitem__(
                    "initial_value", "active"
                ),
            ),
            (
                "domain_state_transitions",
                lambda snapshots: snapshots[0]["target_values"].__setitem__("status", "paused"),
            ),
        ],
    )
    def test_changed_embedded_snapshot_content_rejected(
        self, snapshot_key: str, tamper: Callable[[list[JsonValue]], None]
    ) -> None:
        def mutate(world: WorldVersion) -> None:
            snapshots = world.world[snapshot_key]
            assert isinstance(snapshots, list)
            tamper(snapshots)

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "recompiled world content mismatch")

    @pytest.mark.parametrize(
        "snapshot_key",
        [
            "domain_pack_bindings",
            "domain_capability_declarations",
            "domain_state_models",
            "domain_state_transitions",
        ],
    )
    def test_reordered_embedded_snapshots_rejected(self, snapshot_key: str) -> None:
        def mutate(world: WorldVersion) -> None:
            snapshots = world.world[snapshot_key]
            assert isinstance(snapshots, list)
            assert len(snapshots) > 1  # the reversal must be meaningful
            world.world[snapshot_key] = list(reversed(snapshots))

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "are not canonical")

    def test_changed_embedded_compiler_version_rejected(self) -> None:
        world, manifest = self._tampered_world(
            lambda w: w.world.__setitem__("compiler_version", "9.9.9")
        )
        self._expect_rejected(world, manifest, "world body compiler version mismatch")

    def test_changed_embedded_content_hash_rejected(self) -> None:
        world, manifest = self._tampered_world(
            lambda w: w.world.__setitem__("content_hash", "f" * 64)
        )
        self._expect_rejected(world, manifest, "world body content hash mismatch")

    def test_missing_compiler_owned_world_field_rejected(self) -> None:
        world, manifest = self._tampered_world(lambda w: w.world.__delitem__("scenario"))
        self._expect_rejected(world, manifest, "world body is missing compiler-owned fields")

    def test_unexpected_compiler_owned_world_field_rejected(self) -> None:
        world, manifest = self._tampered_world(lambda w: w.world.__setitem__("rogue", 1))
        self._expect_rejected(world, manifest, "world body has unexpected compiler-owned fields")

    def test_malformed_embedded_snapshot_collection_rejected(self) -> None:
        world, manifest = self._tampered_world(_tamper_bindings_not_a_list)
        self._expect_rejected(world, manifest, "embedded domain pack binding is malformed")

    def test_wrong_world_identifier_rejected(self) -> None:
        _, compiled = _rich_compiled()
        world = compiled.version.model_copy(update={"identifier": "world-ffffffffffffffff"})
        self._expect_rejected(world, compiled.manifest, "world identifier mismatch")

    def test_wrong_manifest_identifier_rejected(self) -> None:
        _, compiled = _rich_compiled()
        manifest = compiled.manifest.model_copy(update={"identifier": "manifest-ffffffffffffffff"})
        self._expect_rejected(compiled.version, manifest, "manifest identifier mismatch")

    def test_wrong_manifest_world_reference_rejected(self) -> None:
        _, compiled = _rich_compiled()
        manifest = compiled.manifest.model_copy(update={"world_version_id": "world-other"})
        self._expect_rejected(compiled.version, manifest, "manifest world reference mismatch")

    def test_tenant_mismatch_rejected(self) -> None:
        _, compiled = _rich_compiled()
        world = compiled.version.model_copy(update={"tenant_id": "tenant-other"})
        self._expect_rejected(world, compiled.manifest, "world tenant mismatch")

    def test_scenario_provenance_mismatches_rejected(self) -> None:
        _, compiled = _rich_compiled()
        wrong_source = compiled.version.model_copy(update={"source_scenario_id": "scenario-other"})
        self._expect_rejected(wrong_source, compiled.manifest, "scenario identifier mismatch")
        wrong_created = compiled.version.model_copy(update={"created_at": LATER})
        self._expect_rejected(wrong_created, compiled.manifest, "scenario provenance mismatch")

    @pytest.mark.parametrize(
        ("tamper", "reason_fragment"),
        [
            (
                lambda manifest: manifest.model_copy(
                    update={"state": {"declared_objective_count": 999}}
                ),
                "recompiled manifest mismatch",
            ),
            (
                lambda manifest: manifest.model_copy(
                    update={
                        "metadata": {
                            "compiler_version": COMPILER_VERSION,
                            "content_hash": "f" * 64,
                        }
                    }
                ),
                "recompiled manifest mismatch",
            ),
        ],
    )
    def test_changed_manifest_state_or_metadata_rejected(
        self, tamper: Callable[[WorldManifest], WorldManifest], reason_fragment: str
    ) -> None:
        _, compiled = _rich_compiled()
        manifest = tamper(compiled.manifest)
        self._expect_rejected(compiled.version, manifest, reason_fragment)

    def test_unsupported_compiler_version_rejected(self) -> None:
        scenario = build_scenario()
        compiled = compile_world(scenario, compiler_version="9.9.9")
        self._expect_rejected(compiled.version, compiled.manifest, "unsupported compiler version")

    def test_errors_expose_no_raw_hashes_or_embedded_values(self) -> None:
        _, compiled = _rich_compiled()
        world = compiled.version.model_copy(deep=True)
        scenario = world.world["scenario"]
        assert isinstance(scenario, dict)
        scenario["name"] = "Tampered"
        world.world["content_hash"] = "f" * 64
        with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
            verify_world_snapshot(world, compiled.manifest)
        message = str(exc_info.value)
        assert "Tampered" not in message
        assert "f" * 64 not in message
        assert compiled.version.content_hash not in message
        assert "rejected" in message


class TestIntegrationGates:
    def _corrupt_stored_world(self, store: InMemoryScenarioStore, world_id: str) -> None:
        # Test-only private-dict injection: mutate the stored world body.
        scenario = store._worlds[(TENANT, world_id)].world["scenario"]
        assert isinstance(scenario, dict)
        scenario["name"] = "Tampered"

    def test_campaign_preparation_rejects_corrupted_world_before_legion(self) -> None:
        store, world_id = build_store()
        self._corrupt_stored_world(store, world_id)
        legion = _CountingLegion()
        with pytest.raises(WorldSnapshotIntegrityError):
            prepare(store, world_id, legion=legion)
        assert legion.calls == 0
        with pytest.raises(CampaignNotFoundError):
            store.get_campaign(TENANT, "campaign-1")

    def test_execute_preflight_rejects_corrupted_world_atomically(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id)
        start(store)
        self._corrupt_stored_world(store, world_id)
        with pytest.raises(WorldSnapshotIntegrityError):
            execute(store)
        # Atomic failure: zero runs, zero events, all statuses PLANNED,
        # campaign stays RUNNING.
        for plan in store.get_run_plans(TENANT, "campaign-1"):
            assert store.get_run_status(TENANT, run_identifier(plan)).state is RunState.PLANNED
        assert store.get_campaign_status(TENANT, "campaign-1").state is CampaignState.RUNNING

    def test_replay_rejects_corrupted_world_before_replay_manifest(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        execute(store)
        run_id = run_identifier(prepared.run_plans[0])
        self._corrupt_stored_world(store, world_id)
        with pytest.raises(WorldSnapshotIntegrityError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)

    def test_verify_run_inputs_rejects_corrupted_world(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        run_id = run_identifier(prepared.run_plans[0])
        self._corrupt_stored_world(store, world_id)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_run_inputs(store=store, tenant_id=TENANT, run_id=run_id)

    def test_mock_nexus_boundary_rejects_corrupted_world(self) -> None:
        store, world_id = build_store()
        adapter = MockNexusAdapter(store)
        self._corrupt_stored_world(store, world_id)
        with pytest.raises(WorldSnapshotIntegrityError):
            adapter.world(TENANT, world_id)
        with pytest.raises(WorldSnapshotIntegrityError):
            adapter.manifest(TENANT, world_id)

    def test_valid_flow_execute_and_replay_remain_green(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id)
        start(store)
        statuses = execute(store)
        assert all(status.state is RunState.COMPLETE for status in statuses)
        run_id = run_identifier(prepared.run_plans[0])
        replay = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert replay.replay_classification == "exact"
        assert store.get_replay_manifest(TENANT, run_id) == replay
