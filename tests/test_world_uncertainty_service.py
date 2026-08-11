"""Phase 24 declaration-service tests.

Proves the declaration service copies every authoritative provenance
field from stored immutable records (never from caller input),
canonicalizes binding order by the complete target tuple, enforces the
target-field kind / rounding / bound / discrete-kind / effective
parameter / static discrete allowed-values rules with typed 422 errors,
rejects declarations after world compilation with a typed 409, rejects
duplicate models and duplicate target tuples, is tenant-scoped, and
never records operational activity.
"""

from __future__ import annotations

from typing import Literal

import pytest
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyAllowedValuesError,
    WorldUncertaintyBoundRuleError,
    WorldUncertaintyDiscreteValueKindError,
    WorldUncertaintyDistributionParameterError,
    WorldUncertaintyModelAlreadyExistsError,
    WorldUncertaintyModelDeclarationAfterCompilationError,
    WorldUncertaintyModelValidationError,
    WorldUncertaintyRoundingPolicyRuleError,
    WorldUncertaintyUnknownManifestError,
    WorldUncertaintyUnknownStateFieldError,
    WorldUncertaintyUnknownStateModelError,
    WorldUncertaintyUnsupportedFieldKindError,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_binding_content_hash,
    uncertainty_model_content_hash,
    uncertainty_model_identifier,
)
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    get_world_uncertainty_model,
)
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    DistributionSpecification,
    LognormalDistribution,
    NormalDistribution,
    UniformDistribution,
)

from tests.phase4_helpers import TENANT
from tests.phase24_helpers import (
    MODEL_DECLARED_AT,
    build_uncertainty_store,
    declare_model,
)

OTHER_TENANT = "tenant-other"


def _draft(
    *,
    state_field_id: str = "level",
    distribution: DistributionSpecification | None = None,
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = (
        "nearest_ties_to_even"
    ),
    lower_bound: int | float | None = None,
    upper_bound: int | float | None = None,
    manifest_id: str = "manifest-1",
    state_model_id: str = "sm-1",
) -> UncertaintyBindingDraft:
    return UncertaintyBindingDraft(
        manifest_id=manifest_id,
        state_model_id=state_model_id,
        state_field_id=state_field_id,
        distribution=distribution or UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy=rounding_policy,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


class TestSuccessfulDeclaration:
    def test_declares_canonical_model(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(
            store,
            bindings=(
                _draft(state_field_id="ratio", rounding_policy=None),
                _draft(state_field_id="level"),
            ),
        )
        assert model.tenant_id == TENANT
        assert model.scenario_id == "scenario-1"
        assert model.schema_version == "1.0.0"
        # Canonical order by (manifest_id, state_model_id, state_field_id).
        assert [binding.state_field_id for binding in model.bindings] == [
            "level",
            "ratio",
        ]
        # Caller order was ratio-first; canonical order is level-first.
        assert model.bindings[0].state_field_id == "level"

    def test_authoritative_provenance_copied_from_stored_records(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        binding = model.bindings[0]
        pack_binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
        state_model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
        assert binding.binding_id == pack_binding.identifier
        assert binding.manifest_id == pack_binding.manifest_id
        assert binding.pack_id == pack_binding.pack_id
        assert binding.pack_version == pack_binding.pack_version
        assert binding.manifest_content_hash == pack_binding.manifest_content_hash
        assert binding.state_model_identifier == state_model.identifier
        assert binding.state_model_id == state_model.state_model_id
        assert binding.state_model_content_hash == state_model.content_hash
        assert binding.state_field_value_kind == "integer"
        assert binding.sampler_version == "sha256-counter-v1"
        assert binding.quantization_policy == "rational-round-half-even"
        assert binding.quantization_fraction_bits == 64

    def test_identifiers_and_hashes_deterministic(self) -> None:
        store_a = build_uncertainty_store()
        store_b = build_uncertainty_store()
        model_a = declare_model(store_a, bindings=(_draft(),))
        model_b = declare_model(store_b, bindings=(_draft(),))
        assert model_a.identifier == model_b.identifier
        assert model_a.content_hash == model_b.content_hash
        assert model_a.model_dump(mode="json") == model_b.model_dump(mode="json")

    def test_identifier_independent_of_content_hash(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        expected = uncertainty_model_identifier(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            scenario_content_hash_value=model.scenario_content_hash,
        )
        assert model.identifier == expected

    def test_binding_content_hash_self_consistent(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        for binding in model.bindings:
            assert uncertainty_binding_content_hash(binding) == binding.content_hash
        assert uncertainty_model_content_hash(model) == model.content_hash

    def test_binding_identifier_is_target_derived(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        binding = model.bindings[0]
        # Identical target tuples always yield the same identifier even
        # when the distribution differs.
        store_other = build_uncertainty_store()
        other = declare_model(
            store_other,
            bindings=(
                _draft(
                    distribution=NormalDistribution(kind="normal", mean=0.0, standard_deviation=1.0)
                ),
            ),
        )
        assert binding.identifier == other.bindings[0].identifier

    def test_declared_at_and_metadata_recorded(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(
            store,
            bindings=(_draft(),),
            metadata={"source": "test", "tags": ["a", "b"]},
        )
        assert model.declared_at == MODEL_DECLARED_AT
        assert model.metadata == {"source": "test", "tags": ["a", "b"]}

    def test_model_fetched_through_service_is_identical(self) -> None:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        fetched = get_world_uncertainty_model(store, TENANT, "scenario-1")
        assert fetched.model_dump(mode="json") == model.model_dump(mode="json")


class TestDeclarationRules:
    def test_unknown_manifest(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyUnknownManifestError):
            declare_model(store, bindings=(_draft(manifest_id="manifest-nope"),))

    def test_unknown_state_model(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyUnknownStateModelError):
            declare_model(store, bindings=(_draft(state_model_id="sm-nope"),))

    def test_unknown_state_field(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyUnknownStateFieldError):
            declare_model(store, bindings=(_draft(state_field_id="nope"),))

    def test_unsupported_field_kind(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyUnsupportedFieldKindError):
            declare_model(store, bindings=(_draft(state_field_id="status"),))

    def test_integer_target_requires_rounding_policy(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyRoundingPolicyRuleError):
            declare_model(store, bindings=(_draft(rounding_policy=None),))

    def test_number_target_forbids_rounding_policy(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyRoundingPolicyRuleError):
            declare_model(
                store,
                bindings=(_draft(state_field_id="ratio", rounding_policy="floor"),),
            )

    def test_integer_target_requires_integer_bounds(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyBoundRuleError):
            declare_model(store, bindings=(_draft(lower_bound=1.5),))

    def test_bound_ordering_enforced(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyBoundRuleError):
            declare_model(store, bindings=(_draft(lower_bound=5, upper_bound=2),))

    def test_duplicate_target_tuple_rejected(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyModelValidationError):
            declare_model(store, bindings=(_draft(), _draft()))

    def test_empty_bindings_rejected(self) -> None:
        store = build_uncertainty_store()
        with pytest.raises(WorldUncertaintyModelValidationError):
            declare_model(store, bindings=())

    def test_duplicate_declaration_rejected(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        with pytest.raises(WorldUncertaintyModelAlreadyExistsError):
            declare_model(store, bindings=(_draft(),))

    def test_declaration_after_compilation_rejected(self) -> None:
        from kalhas.adapters.mocks import MockNexusAdapter

        store = build_uncertainty_store()
        MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        with pytest.raises(WorldUncertaintyModelDeclarationAfterCompilationError):
            declare_model(store, bindings=(_draft(),))

    def test_declaration_before_compilation_allowed(self) -> None:
        from kalhas.adapters.mocks import MockNexusAdapter

        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        world = store.get_world(TENANT, compiled.version.identifier)
        embedded = world.world["uncertainty_model"]
        assert isinstance(embedded, dict)
        assert embedded["identifier"] == model.identifier

    def test_discrete_integer_values_for_integer_target(self) -> None:
        store = build_uncertainty_store()
        declare_model(
            store,
            bindings=(
                _draft(
                    distribution=DiscreteDistribution(
                        kind="discrete", values=(1, 2), probabilities=(0.5, 0.5)
                    )
                ),
            ),
        )
        with pytest.raises(WorldUncertaintyDiscreteValueKindError):
            declare_model(
                build_uncertainty_store(),
                bindings=(
                    _draft(
                        distribution=DiscreteDistribution(
                            kind="discrete",
                            values=(1, 2.0),
                            probabilities=(0.5, 0.5),
                        )
                    ),
                ),
            )

    def test_effective_parameter_rules(self) -> None:
        # A declared positive probability that vanishes under Q64.64.
        with pytest.raises(WorldUncertaintyDistributionParameterError):
            declare_model(
                build_uncertainty_store(),
                bindings=(
                    _draft(
                        distribution=DiscreteDistribution(
                            kind="discrete",
                            values=(1, 2),
                            probabilities=(1e-30, 1.0),
                        )
                    ),
                ),
            )
        # Effective standard deviation of zero.
        with pytest.raises(WorldUncertaintyDistributionParameterError):
            declare_model(
                build_uncertainty_store(),
                bindings=(
                    _draft(
                        distribution=NormalDistribution(
                            kind="normal",
                            mean=0.0,
                            standard_deviation=1e-30,
                        )
                    ),
                ),
            )
        # Lognormal static finite-raw boundary.
        with pytest.raises(WorldUncertaintyDistributionParameterError):
            declare_model(
                build_uncertainty_store(),
                bindings=(
                    _draft(
                        distribution=LognormalDistribution(kind="lognormal", mu=1000.0, sigma=1.0)
                    ),
                ),
            )

    def test_static_discrete_allowed_values_enforced(self) -> None:
        # Every selectable discrete outcome must be canonically allowed;
        # value 2 is not in allowed_values (0, 1).
        with pytest.raises(WorldUncertaintyAllowedValuesError):
            declare_model(
                build_uncertainty_store(level_allowed=(0, 1)),
                bindings=(
                    _draft(
                        distribution=DiscreteDistribution(
                            kind="discrete", values=(1, 2), probabilities=(0.5, 0.5)
                        )
                    ),
                ),
            )

    def test_discrete_allowed_values_after_clipping(self) -> None:
        # Raw support value 5 is outside allowed_values (0, 1, 2) but
        # clipping maps it to the allowed upper bound 2 -> declared OK.
        model = declare_model(
            build_uncertainty_store(level_allowed=(0, 1, 2)),
            bindings=(
                _draft(
                    distribution=DiscreteDistribution(
                        kind="discrete", values=(1, 5), probabilities=(0.5, 0.5)
                    ),
                    upper_bound=2,
                ),
            ),
        )
        assert model.bindings[0].upper_bound == 2

    def test_allowed_values_int_float_distinction(self) -> None:
        # allowed_values (0.0, 1, 1.0) may hold both representations;
        # canonical membership selects the exact declared type.
        declare_model(
            build_uncertainty_store(ratio_allowed=(0.0, 1, 1.0)),
            bindings=(
                _draft(
                    state_field_id="ratio",
                    rounding_policy=None,
                    distribution=DiscreteDistribution(
                        kind="discrete", values=(1, 1.0), probabilities=(0.5, 0.5)
                    ),
                ),
            ),
        )

    def test_foreign_tenant_cannot_declare(self) -> None:
        from kalhas.application.domain_errors import ScenarioNotFoundError

        store = build_uncertainty_store()
        with pytest.raises(ScenarioNotFoundError):
            declare_model(
                store,
                tenant_id=OTHER_TENANT,
                bindings=(_draft(),),
            )

    def test_declaration_records_no_operational_activity(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        assert store.list_operational_activity(TENANT, limit=100) == ()

    def test_no_update_or_delete_surface(self) -> None:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        assert not hasattr(store, "update_world_uncertainty_model")
        assert not hasattr(store, "delete_world_uncertainty_model")
        assert not hasattr(store, "list_world_uncertainty_models")
