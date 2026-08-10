"""Phase 19 world-integrity tests: observation-binding snapshot verification.

``verify_world_snapshot`` recognizes the compiler-owned
``domain_metric_observations`` key, strictly parses every embedded
binding through ``DomainMetricObservationBinding``, rejects foreign or
validator-bypassed snapshots, requires canonical metric-id ordering,
rejects duplicate metric bindings, verifies tenant/scenario ownership,
metric existence against the embedded scenario, state-model existence
and identity/content hash, state-field existence and copied numeric
value-kind match, and pack binding/manifest identity, then recompiles
from the exact parsed snapshots and requires exact WorldVersion and
WorldManifest equality. A corrupted world is never repaired, normalized,
reordered, or replaced. ``extract_world_catalog`` exposes the canonical
observation-binding tuple through an immutable, detached
``VerifiedWorldCatalog``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import WorldSnapshotIntegrityError
from kalhas.application.world_compiler import CompiledWorld, compile_world
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackCapability,
    DomainPackManifest,
)
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import MetricDefinition
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.world import WorldManifest, WorldVersion

from tests.phase4_helpers import NOW, TENANT, build_scenario

DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _observation(metric_id: str, **overrides: object) -> DomainMetricObservationBinding:
    payload: dict[str, object] = {
        "identifier": f"observation-{metric_id}",
        "tenant_id": TENANT,
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "metric_id": metric_id,
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "content_hash": HASH_64,
        "declared_at": DECLARED_AT,
        "metadata": {},
    }
    payload.update(overrides)
    return DomainMetricObservationBinding.model_validate(payload)


def _rich_compiled() -> tuple[ScenarioSpec, CompiledWorld]:
    """A scenario plus a world with bindings, state models, and two observations.

    Two observations (metrics ``m-1``/``m-2``) keep the collection
    multi-element so canonical-order reversals are genuinely meaningful.
    """
    scenario = build_scenario().model_copy(
        update={
            "metrics": [
                MetricDefinition(identifier="m-1", name="Primary metric"),
                MetricDefinition(identifier="m-2", name="Secondary metric"),
            ]
        }
    )
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
                identifier="level",
                description="Declared state field",
                value_kind=StateValueKind.INTEGER,
                initial_value=0,
            ),
            DomainStateFieldDefinition(
                identifier="ratio",
                description="Declared state field",
                value_kind=StateValueKind.NUMBER,
                initial_value=0.0,
            ),
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
    observation_one = _observation("m-1")
    observation_two = _observation(
        "m-2",
        identifier="observation-m-2",
        state_field_id="ratio",
        state_field_value_kind="number",
    )
    compiled = compile_world(
        scenario,
        bindings=(binding,),
        state_models=(state_model,),
        domain_metric_observations=(observation_one, observation_two),
    )
    return scenario, compiled


class TestObservationSnapshotVerification:
    def _tampered_world(
        self, mutate: Callable[[WorldVersion], None]
    ) -> tuple[WorldVersion, WorldManifest]:
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
        # The public message stays generic: the internal reason never leaks.
        assert reason_fragment not in str(exc_info.value)

    def test_valid_snapshot_round_trip(self) -> None:
        _, compiled = _rich_compiled()
        verify_world_snapshot(compiled.version, compiled.manifest)

    def test_malformed_contract_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            observations[0] = {"not": "a binding"}

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "domain metric observation is malformed")

    def test_foreign_object_snapshot_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            observations[0] = 42

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "domain metric observation is malformed")

    def test_duplicate_metric_bindings_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            # Insert the duplicate at the front: the stable metric-id sort
            # keeps the collection canonically ordered, so the duplicate
            # check is what fires (not the canonical-order check).
            observations.insert(0, _observation("m-1").model_dump(mode="json"))

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "duplicate metric bindings")

    def test_non_canonical_order_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            assert len(observations) > 1  # the reversal must be meaningful
            observations.reverse()

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "are not canonical")

    def test_missing_metric_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            # Tamper the SECOND entry (m-2 -> m-ghost): the collection
            # stays canonically ordered ("m-1" < "m-ghost"), so the metric
            # existence check fires (not the canonical-order check).
            second = observations[1]
            assert isinstance(second, dict)
            second["metric_id"] = "m-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "unknown scenario metric")

    def test_missing_state_model_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_model_identifier"] = "state-model-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "unknown state model")

    def test_wrong_state_model_identity_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_model_id"] = "sm-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "state model identity mismatch")

    def test_wrong_state_model_content_hash_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_model_content_hash"] = "f" * 64

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "state model content hash mismatch")

    def test_missing_state_field_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_field_id"] = "field-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "unknown state field")

    def test_mismatched_copied_value_kind_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_field_value_kind"] = "number"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "state field value kind mismatch")

    def test_non_numeric_copied_value_kind_rejected(self) -> None:
        """A copied kind outside the numeric literals cannot even parse.

        The contract restricts ``state_field_value_kind`` to
        ``integer``/``number``, so a non-numeric copied kind is rejected
        as malformed embedded content at strict parse time.
        """

        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["state_field_value_kind"] = "string"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "domain metric observation is malformed")

    def test_wrong_tenant_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["tenant_id"] = "tenant-other"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "foreign tenant")

    def test_wrong_scenario_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["scenario_id"] = "scenario-other"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "foreign scenario")

    def test_unknown_pack_binding_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            # Remove the embedded binding from the compiled catalog: the
            # observation references manifest-1, its state model still
            # matches, but no pack binding remains in the world.
            world.world["domain_pack_bindings"] = []

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "unknown pack binding")

    def test_wrong_manifest_identity_rejected(self) -> None:
        """A manifest-id tamper breaks the state-model manifest relationship."""

        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["manifest_id"] = "manifest-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "state model manifest mismatch")

    def test_wrong_binding_identity_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["binding_id"] = "binding-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "pack binding identity mismatch")

    def test_wrong_pack_identity_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["pack_id"] = "pack-ghost"

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "pack identity mismatch")

    def test_wrong_manifest_content_hash_rejected(self) -> None:
        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["manifest_content_hash"] = "f" * 64

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "manifest content hash mismatch")

    def test_self_consistent_tampering_rejected(self) -> None:
        """A tamper with a recomputed binding content hash is still rejected."""

        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = _observation("m-1", state_field_id="status", content_hash="f" * 64).model_dump(
                mode="json"
            )
            observations[0] = entry

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "state field value kind mismatch")

    def test_recompile_mismatch_rejected(self) -> None:
        """A content-consistent tamper is caught by exact recompilation."""

        def mutate(world: WorldVersion) -> None:
            observations = world.world["domain_metric_observations"]
            assert isinstance(observations, list)
            entry = observations[0]
            assert isinstance(entry, dict)
            entry["metadata"] = {"extra": "field"}

        world, manifest = self._tampered_world(mutate)
        self._expect_rejected(world, manifest, "recompiled world content mismatch")

    def test_no_repair_or_mutation(self) -> None:
        _, compiled = _rich_compiled()
        world = compiled.version.model_copy(deep=True)
        observations = world.world["domain_metric_observations"]
        assert isinstance(observations, list)
        entry = observations[0]
        assert isinstance(entry, dict)
        entry["metric_id"] = "m-ghost"
        pristine = compiled.version.model_dump(mode="json")
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(world, compiled.manifest)
        # The tampered world object is untouched (no normalization), and
        # the pristine compiled world was never modified.
        assert entry["metric_id"] == "m-ghost"
        assert compiled.version.model_dump(mode="json") == pristine


class TestVerifiedWorldCatalogObservations:
    def test_catalog_exposes_canonical_observation_tuple(self) -> None:
        _, compiled = _rich_compiled()
        catalog = extract_world_catalog(compiled.version)
        assert [o.metric_id for o in catalog.domain_metric_observations] == ["m-1", "m-2"]
        assert catalog.domain_metric_observations[0].state_field_id == "level"

    def test_catalog_is_detached_from_world_body(self) -> None:
        _, compiled = _rich_compiled()
        catalog = extract_world_catalog(compiled.version)
        # Mutating the world body after extraction never reaches the catalog.
        observations = compiled.version.world["domain_metric_observations"]
        assert isinstance(observations, list)
        entry = observations[0]
        assert isinstance(entry, dict)
        entry["metadata"] = {"tampered": True}
        assert catalog.domain_metric_observations[0].metadata == {}
        # Mutating a catalog entry never reaches the world body.
        _, compiled_two = _rich_compiled()
        catalog_two = extract_world_catalog(compiled_two.version)
        metadata = catalog_two.domain_metric_observations[0].metadata
        assert isinstance(metadata, dict)
        metadata["tampered"] = True
        body = compiled_two.version.world["domain_metric_observations"]
        assert isinstance(body, list)
        body_entry = body[0]
        assert isinstance(body_entry, dict)
        body_metadata = body_entry["metadata"]
        assert isinstance(body_metadata, dict)
        assert "tampered" not in body_metadata

    def test_catalog_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        _, compiled = _rich_compiled()
        catalog = extract_world_catalog(compiled.version)
        with pytest.raises(FrozenInstanceError):
            catalog.domain_metric_observations = ()  # type: ignore[misc]
