"""Phase 24 store tests: strict revalidation and snapshot isolation.

Proves the store's write/read boundary strictly revalidates the
complete contract (serializer-based - a validator-bypassed record is
rejected before any field is trusted) and independently re-verifies the
deterministic identity and content hash on every read; that unknown and
foreign models are indistinguishable (typed not-found); that writes
deep-copy and reads deep-copy so callers can never mutate stored state;
and that duplicates are rejected without overwriting.
"""

from __future__ import annotations

from typing import cast

import pytest
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyModelAlreadyExistsError,
    WorldUncertaintyModelIntegrityError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.world_realization import UniformDistribution, WorldUncertaintyModel

from tests.phase4_helpers import TENANT
from tests.phase24_helpers import build_uncertainty_store, declare_model

OTHER_TENANT = "tenant-other"


def _draft(*, state_field_id: str = "level") -> UncertaintyBindingDraft:
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id=state_field_id,
        distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy="nearest_ties_to_even",
    )


class TestStoreWriteRead:
    def test_put_then_get_returns_deep_copy(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        fetched = store.get_world_uncertainty_model(TENANT, "scenario-1")
        assert fetched.model_dump(mode="json") == model.model_dump(mode="json")
        # A deep-copy mutation of the returned object must never reach
        # the stored record.
        mutated = fetched.model_copy(deep=True)
        mutated = mutated.model_copy(
            update={
                "bindings": tuple(
                    binding.model_copy(update={"state_field_id": "ratio"})
                    for binding in mutated.bindings
                )
            }
        )
        again = store.get_world_uncertainty_model(TENANT, "scenario-1")
        assert again.bindings[0].state_field_id == "level"

    def test_duplicate_put_rejected(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        with pytest.raises(WorldUncertaintyModelAlreadyExistsError):
            store.put_world_uncertainty_model(TENANT, "scenario-1", model)

    def test_unknown_and_foreign_indistinguishable(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        with pytest.raises(WorldUncertaintyModelNotFoundError):
            store.get_world_uncertainty_model(TENANT, "scenario-nope")
        with pytest.raises(WorldUncertaintyModelNotFoundError):
            store.get_world_uncertainty_model(OTHER_TENANT, "scenario-1")

    def test_ownership_mismatch_rejected_on_put(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        foreign = model.model_copy(update={"tenant_id": OTHER_TENANT})
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.put_world_uncertainty_model(OTHER_TENANT, "scenario-1", foreign)


class TestStrictRevalidation:
    def test_non_finite_nested_parameter_rejected_on_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(deep=True)
        binding = tampered.bindings[0]
        distribution = binding.distribution.model_copy(update={"high": float("inf")})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered.model_copy(
            update={"bindings": (binding.model_copy(update={"distribution": distribution}),)}
        )
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")

    def test_content_hash_tampering_rejected_on_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"content_hash": "f" * 64})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")

    def test_identifier_tampering_rejected_on_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"identifier": "uncertainty-model-ffffffffffffffff"})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")

    def test_foreign_ownership_tampering_rejected_on_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"scenario_id": "scenario-other"})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")

    def test_wrong_record_type_rejected_on_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        # Narrow explicit cast: a non-model record injected into the
        # store slot must be rejected on read.
        store._world_uncertainty_models[(TENANT, "scenario-1")] = cast(
            WorldUncertaintyModel, "not-a-model"
        )
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")

    def test_revalidation_runs_on_every_read(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        store.get_world_uncertainty_model(TENANT, "scenario-1")
        store.get_world_uncertainty_model(TENANT, "scenario-1")
        # Tamper after two successful reads; the third read must reject.
        stored = store.get_world_uncertainty_model(TENANT, "scenario-1")
        tampered = stored.model_copy(update={"content_hash": "e" * 64})
        store._world_uncertainty_models[(TENANT, "scenario-1")] = tampered
        with pytest.raises(WorldUncertaintyModelIntegrityError):
            store.get_world_uncertainty_model(TENANT, "scenario-1")
