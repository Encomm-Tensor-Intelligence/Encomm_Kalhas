"""Phase 24 world-integrity tests.

Proves the compiled world embeds the uncertainty model snapshot only
when present (absent-model worlds stay byte-identical to the Phase 23
compilation), that ``verify_world_snapshot`` strictly verifies the
embedded model's ownership, identity, hashes, canonical binding order,
copied authoritative provenance against the embedded pack-binding and
state-model snapshots, sampler/quantization literals, effective
parameter rules, and static discrete allowed outcomes - and that
tampered embedded models are rejected with the typed integrity error.
"""

from __future__ import annotations

from typing import Literal, cast

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application.domain_errors import WorldSnapshotIntegrityError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_model_content_hash,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    DistributionSpecification,
    UniformDistribution,
)

from tests.phase4_helpers import TENANT
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase24_helpers import build_uncertainty_store, declare_model


def _draft(
    *,
    state_field_id: str = "level",
    distribution: DistributionSpecification | None = None,
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = (
        "nearest_ties_to_even"
    ),
) -> UncertaintyBindingDraft:
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id=state_field_id,
        distribution=distribution or UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy=rounding_policy,
    )


def _compiled_with_model(
    store: InMemoryScenarioStore | None = None,
    *,
    bindings: tuple[UncertaintyBindingDraft, ...] | None = None,
) -> tuple[InMemoryScenarioStore, WorldVersion, WorldManifest]:
    effective_store = store if store is not None else build_uncertainty_store()
    declare_model(
        effective_store,
        bindings=bindings or (_draft(),),
    )
    compiled = MockNexusAdapter(effective_store).compile_scenario(TENANT, "scenario-1")
    world = effective_store.get_world(TENANT, compiled.version.identifier)
    manifest = effective_store.get_manifest(TENANT, compiled.version.identifier)
    verify_world_snapshot(world, manifest)
    return effective_store, world, manifest


def _embedded_model_dict(world: WorldVersion) -> dict[str, JsonValue]:
    """A fresh top-level copy of the embedded uncertainty-model dict."""
    value = world.world["uncertainty_model"]
    assert isinstance(value, dict)
    return dict(value)


def _binding_dicts(model_dict: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Fresh copies of the embedded binding dicts (top level only)."""
    bindings = model_dict["bindings"]
    assert isinstance(bindings, list)
    copies: list[dict[str, JsonValue]] = []
    for item in bindings:
        assert isinstance(item, dict)
        copies.append(dict(item))
    return copies


def _tampered_world(world: WorldVersion, model_dict: dict[str, JsonValue]) -> WorldVersion:
    tampered_body = dict(world.world)
    tampered_body["uncertainty_model"] = model_dict
    return world.model_copy(update={"world": tampered_body})


class TestEmbeddedModelVerification:
    def test_world_embeds_model_snapshot(self) -> None:
        _, world, _ = _compiled_with_model()
        assert "uncertainty_model" in world.world
        assert _embedded_model_dict(world)["schema_version"] == "1.0.0"

    def test_catalog_exposes_embedded_model(self) -> None:
        _, world, _ = _compiled_with_model()
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is not None
        assert catalog.uncertainty_model.bindings[0].state_field_id == "level"

    def test_absent_model_catalog_is_none(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        world = store.get_world(TENANT, world_version_id)
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is None

    def test_embedded_content_hash_verified(self) -> None:
        _, world, manifest = _compiled_with_model()
        # Mutating the embedded model's content hash must fail verification.
        tampered_model = _embedded_model_dict(world)
        tampered_model["content_hash"] = "f" * 64
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_identifier_mismatch_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_model["identifier"] = "uncertainty-model-ffffffffffffffff"
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_foreign_scenario_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_model["scenario_id"] = "scenario-other"
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_scenario_hash_mismatch_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_model["scenario_content_hash"] = "f" * 64
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_state_model_provenance_mismatch_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["state_model_content_hash"] = "f" * 64
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_pack_provenance_mismatch_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["pack_version"] = "9.9.9"
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_sampler_literal_mismatch_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["sampler_version"] = "sha256-counter-v9"
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_non_canonical_binding_order_rejected(self) -> None:
        store = build_uncertainty_store()
        _, world, manifest = _compiled_with_model(
            store,
            bindings=(
                _draft(state_field_id="level"),
                _draft(
                    state_field_id="ratio",
                    rounding_policy=None,
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=1.0),
                ),
            ),
        )
        tampered_model = _embedded_model_dict(world)
        tampered_model["bindings"] = list(reversed(_binding_dicts(tampered_model)))
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_unknown_state_model_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["state_model_identifier"] = "state-model-unknown"
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_unknown_field_rejected(self) -> None:
        _, world, manifest = _compiled_with_model()
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["state_field_id"] = "status"
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_effective_parameter_violation_rejected(self) -> None:
        store = build_uncertainty_store()
        # Declare a valid model, compile, then tamper the embedded
        # binding's distribution to one with a vanishing probability and
        # recompute the model hash so verification reaches the
        # parameter-rule check.
        _, world, manifest = _compiled_with_model(store, bindings=(_draft(),))
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["distribution"] = {
            "kind": "discrete",
            "values": [1, 2],
            "probabilities": [1e-30, 1.0],
        }
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

        revalidated = WorldUncertaintyModel.model_validate(tampered_model)
        tampered_model["content_hash"] = uncertainty_model_content_hash(revalidated)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)

    def test_embedded_static_discrete_allowed_violation_rejected(self) -> None:
        store = build_uncertainty_store(level_allowed=(0, 1))
        # Declare a valid discrete model (both outcomes allowed), then
        # tamper the embedded support to include an unallowed outcome
        # with recomputed hashes so the static allowed-values check
        # rejects it.
        _, world, manifest = _compiled_with_model(
            store,
            bindings=(
                _draft(
                    distribution=DiscreteDistribution(
                        kind="discrete", values=(0, 1), probabilities=(0.5, 0.5)
                    )
                ),
            ),
        )
        tampered_model = _embedded_model_dict(world)
        tampered_bindings = _binding_dicts(tampered_model)
        tampered_binding = dict(tampered_bindings[0])
        tampered_binding["distribution"] = {
            "kind": "discrete",
            "values": [0, 2],
            "probabilities": [0.5, 0.5],
        }
        tampered_bindings[0] = tampered_binding
        tampered_model["bindings"] = cast(JsonValue, tampered_bindings)
        from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

        revalidated = WorldUncertaintyModel.model_validate(tampered_model)
        tampered_model["content_hash"] = uncertainty_model_content_hash(revalidated)
        broken = _tampered_world(world, tampered_model)
        with pytest.raises(WorldSnapshotIntegrityError):
            verify_world_snapshot(broken, manifest)


class TestAbsentModelByteCompatibility:
    def test_no_model_means_no_uncertainty_key(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        world = store.get_world(TENANT, world_version_id)
        assert "uncertainty_model" not in world.world
        # The manifest count key appears only when a model is embedded
        # (same convention as the evaluation profile count).
        assert "declared_world_uncertainty_model_count" not in world.world

    def test_model_free_world_compiles_like_phase23(self) -> None:
        # The Phase 20/23 compile paths (observation and evaluation
        # worlds) produce byte-identical worlds with no model present.
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        world = store.get_world(TENANT, world_version_id)
        assert "uncertainty_model" not in world.world
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is None

    def test_evaluation_world_also_model_free(self) -> None:
        # A Phase 23 evaluation world (profile embedded, no uncertainty
        # model) keeps the Phase 23 body exactly.
        from tests.phase23_helpers import complete_evaluation_campaign

        store, world_version_id, _ = complete_evaluation_campaign(execute=False)
        world = store.get_world(TENANT, world_version_id)
        assert "uncertainty_model" not in world.world
        assert "evaluation_profile" in world.world
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is None
        assert catalog.evaluation_profile is not None
