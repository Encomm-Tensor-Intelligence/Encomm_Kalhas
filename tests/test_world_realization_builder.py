"""Phase 24 pure realization-builder tests.

Exercises ``build_world_realization`` and
``build_campaign_world_realization_matrix`` directly, without the
query/API layers: empty-model realizations with real derived hashes,
sample/clip/round/validate ordering, exact int/float representation
preservation, deterministic per-seed sampling failures with no retry,
the K-seeds/K-realizations invariant independent of strategy
count/order, and the typed provenance rejections of inconsistent direct
inputs.
"""

from __future__ import annotations

from typing import Literal

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_integrity import (
    VerifiedWorldCatalog,
    extract_world_catalog,
)
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
    build_world_realization,
)
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
)
from kalhas.application.world_uncertainty_identity import (
    campaign_realization_matrix_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    DistributionSpecification,
    UniformDistribution,
    WorldUncertaintyModel,
)

from tests.phase4_helpers import NOW, TENANT
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase24_helpers import build_uncertainty_store, declare_model

OTHER_TENANT = "tenant-other"
PLACEHOLDER = "0" * 64


def _draft(
    *,
    state_field_id: str = "level",
    distribution: DistributionSpecification | None = None,
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = (
        "nearest_ties_to_even"
    ),
    lower_bound: int | float | None = None,
    upper_bound: int | float | None = None,
) -> UncertaintyBindingDraft:
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id=state_field_id,
        distribution=distribution or UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy=rounding_policy,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


def _seed(identifier: str = "seed-1", tenant_id: str = TENANT) -> ScenarioSeed:
    return ScenarioSeed(
        identifier=identifier,
        tenant_id=tenant_id,
        algorithm="deterministic",
        seed_value="v1",
    )


def _compiled(
    model_store: InMemoryScenarioStore,
) -> tuple[WorldVersion, VerifiedWorldCatalog]:
    """Compile the store's scenario into a verified world (model optional)."""
    compiled = MockNexusAdapter(model_store).compile_scenario(TENANT, "scenario-1")
    world = model_store.get_world(TENANT, compiled.version.identifier)
    catalog = extract_world_catalog(world)
    return world, catalog


def _campaign(
    *,
    world: WorldVersion,
    seeds: tuple[ScenarioSeed, ...],
    campaign_id: str = "campaign-1",
    strategy_ids: tuple[str, ...] = ("sc-a", "sc-b"),
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    world_version_id: str | None = None,
) -> CampaignSpec:
    return CampaignSpec(
        identifier=campaign_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        name="Reference campaign",
        scenario_id=scenario_id,
        world_version_id=world_version_id or world.identifier,
        strategy_candidate_ids=list(strategy_ids),
        comparison_mode="identical_conditions",
        seed_ensemble=seeds,
        created_at=NOW,
        metadata={},
    )


class TestEmptyModelRealizations:
    def _empty_fixture(self) -> tuple[WorldVersion, VerifiedWorldCatalog]:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        world = store.get_world(TENANT, world_version_id)
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is None
        return world, catalog

    def test_one_empty_realization_per_seed(self) -> None:
        world, catalog = self._empty_fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed(),
            realized_at=NOW,
        )
        assert realization.sampled_values == ()
        assert realization.realized_initial_state_overrides == ()
        assert realization.uncertainty_model_id is None
        assert realization.uncertainty_model_content_hash is None

    def test_content_hash_is_derived_not_placeholder(self) -> None:
        world, catalog = self._empty_fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed(),
            realized_at=NOW,
        )
        assert realization.content_hash != PLACEHOLDER
        assert world_realization_content_hash(realization) == realization.content_hash

    def test_identifier_independently_recomputes(self) -> None:
        world, catalog = self._empty_fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed(),
            realized_at=NOW,
        )
        expected = world_realization_identifier(
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            scenario_seed_id=realization.scenario_seed_id,
            seed_content_hash_value=realization.seed_content_hash,
            uncertainty_model_id=None,
            uncertainty_model_content_hash_value=None,
            sampler_version="sha256-counter-v1",
            quantization_policy="rational-round-half-even",
            quantization_fraction_bits=64,
        )
        assert realization.identifier == expected

    def test_repeated_build_is_byte_identical(self) -> None:
        world, catalog = self._empty_fixture()
        first = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed(),
            realized_at=NOW,
        )
        second = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed(),
            realized_at=NOW,
        )
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_different_seeds_differ(self) -> None:
        world, catalog = self._empty_fixture()
        first = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed("seed-1"),
            realized_at=NOW,
        )
        second = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=None,
            seed=_seed("seed-2"),
            realized_at=NOW,
        )
        assert first.identifier != second.identifier
        assert first.content_hash != second.content_hash
        assert first.scenario_seed_id != second.scenario_seed_id

    def test_empty_matrix_hash_recomputes(self) -> None:
        world, catalog = self._empty_fixture()
        matrix = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=(_seed("seed-1"), _seed("seed-2"))),
            world=world,
            state_models=catalog.state_models,
            model=None,
        )
        assert len(matrix.realizations) == 2
        assert campaign_realization_matrix_content_hash(matrix) == matrix.content_hash
        assert matrix.uncertainty_model_id is None

    def test_no_input_mutation(self) -> None:
        world, catalog = self._empty_fixture()
        seed = _seed()
        matrix = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=(seed,)),
            world=world,
            state_models=catalog.state_models,
            model=None,
        )
        assert matrix.campaign_id == "campaign-1"
        assert seed.tenant_id == TENANT
        assert seed.identifier == "seed-1"
        assert world.identifier == matrix.world_version_id


class TestSamplingAndRepresentation:
    def _fixture(
        self,
        *,
        level_allowed: tuple[JsonValue, ...] = (),
        ratio_allowed: tuple[JsonValue, ...] = (),
    ) -> tuple[InMemoryScenarioStore, WorldUncertaintyModel, WorldVersion, VerifiedWorldCatalog]:
        store = build_uncertainty_store(level_allowed=level_allowed, ratio_allowed=ratio_allowed)
        model = declare_model(
            store,
            bindings=(
                _draft(state_field_id="level"),
                _draft(
                    state_field_id="ratio",
                    rounding_policy=None,
                    distribution=DiscreteDistribution(
                        kind="discrete", values=(1, 1.0), probabilities=(0.5, 0.5)
                    ),
                ),
            ),
        )
        world, catalog = _compiled(store)
        return store, model, world, catalog

    def test_one_sample_per_binding_and_draw_partition(self) -> None:
        _, _, world, catalog = self._fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        assert len(realization.sampled_values) == 2
        assert len(realization.realized_initial_state_overrides) == 2
        assert [s.draw_index for s in realization.sampled_values] == [0, 1]
        assert [s.draw_count for s in realization.sampled_values] == [1, 1]

    def test_continuous_raw_remains_float_when_integral(self) -> None:
        store = build_uncertainty_store()
        declare_model(
            store,
            bindings=(
                _draft(
                    state_field_id="ratio",
                    rounding_policy=None,
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=1.0),
                ),
            ),
        )
        world, catalog = _compiled(store)
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        sampled = realization.sampled_values[0]
        assert isinstance(sampled.sampled_raw_value, float)
        assert isinstance(sampled.realized_value, float)

    def test_integer_target_raw_float_final_int(self) -> None:
        _, _, world, catalog = self._fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        level = realization.sampled_values[0]
        assert level.state_field_id == "level"
        assert isinstance(level.sampled_raw_value, (int, float))
        assert isinstance(level.realized_value, int)
        override = realization.realized_initial_state_overrides[0]
        assert isinstance(override.value, int)

    def test_discrete_int_and_float_preserved(self) -> None:
        # Probe several seeds so both declared representations occur.
        _, _, world, catalog = self._fixture()
        seen_int = False
        seen_float = False
        for index in range(12):
            realization = build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
                seed=_seed(f"seed-{index}"),
                realized_at=NOW,
            )
            ratio = realization.sampled_values[1]
            assert ratio.state_field_id == "ratio"
            if isinstance(ratio.realized_value, int) and not isinstance(ratio.realized_value, bool):
                assert ratio.realized_value == 1
                seen_int = True
            elif isinstance(ratio.realized_value, float):
                assert ratio.realized_value == 1.0
                seen_float = True
            else:  # pragma: no cover - the discrete support is exactly {1, 1.0}
                raise AssertionError(f"unexpected ratio value {ratio.realized_value!r}")
        assert seen_int and seen_float

    def test_clipping_number_target_adopts_bound_representation(self) -> None:
        store = build_uncertainty_store()
        declare_model(
            store,
            bindings=(
                _draft(
                    state_field_id="ratio",
                    rounding_policy=None,
                    distribution=UniformDistribution(kind="uniform", low=0.0, high=10.0),
                    upper_bound=2,
                ),
            ),
        )
        world, catalog = _compiled(store)
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        sampled = realization.sampled_values[0]
        assert sampled.realized_value == 2
        assert isinstance(sampled.realized_value, int)

    def test_allowed_values_canonical_int_float_distinction(self) -> None:
        store = build_uncertainty_store(ratio_allowed=(0.0, 1, 1.0))
        declare_model(
            store,
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
        world, catalog = _compiled(store)
        for index in range(12):
            realization = build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
                seed=_seed(f"seed-{index}"),
                realized_at=NOW,
            )
            # Both 1 (int) and 1.0 (float) are canonically allowed; the
            # realized value must exactly match one of them.
            value = realization.sampled_values[0].realized_value
            assert value in (1, 1.0)

    def test_overrides_complete_and_untargeted_fields_absent(self) -> None:
        _, _, world, catalog = self._fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        override_fields = {
            override.state_field_id for override in realization.realized_initial_state_overrides
        }
        assert override_fields == {"level", "ratio"}
        assert "status" not in override_fields

    def test_realized_state_passes_validate_state(self) -> None:
        from kalhas.application.state_transition_engine import validate_state

        _, _, world, catalog = self._fixture()
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=_seed(),
            realized_at=NOW,
        )
        state_model = catalog.state_models[0]
        state = {field.identifier: field.initial_value for field in state_model.state_fields}
        for override in realization.realized_initial_state_overrides:
            state[override.state_field_id] = override.value
        validate_state(state, state_model)  # must not raise


class TestDeterministicFailures:
    def _failing_fixture(self) -> tuple[WorldVersion, VerifiedWorldCatalog]:
        # level allowed_values (0, 1) with uniform(0, 3): seeds 0/1/3
        # deterministically fail, seeds 2/4/5 succeed.
        store = build_uncertainty_store(level_allowed=(0, 1))
        declare_model(
            store,
            bindings=(_draft(distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0)),),
        )
        world, catalog = _compiled(store)
        return world, catalog

    def test_verified_failure_probe(self) -> None:
        world, catalog = self._failing_fixture()
        failing: list[str] = []
        succeeding: list[str] = []
        for index in range(6):
            seed = _seed(f"seed-fail-{index}")
            try:
                build_world_realization(
                    world=world,
                    state_models=catalog.state_models,
                    model=catalog.uncertainty_model,
                    seed=seed,
                    realized_at=NOW,
                )
            except WorldRealizationSamplingError:
                failing.append(seed.identifier)
            else:
                succeeding.append(seed.identifier)
        assert failing == ["seed-fail-0", "seed-fail-1", "seed-fail-3"]
        assert succeeding == ["seed-fail-2", "seed-fail-4", "seed-fail-5"]

    def test_failure_is_deterministic_and_repeated(self) -> None:
        world, catalog = self._failing_fixture()
        for _ in range(3):
            with pytest.raises(WorldRealizationSamplingError):
                build_world_realization(
                    world=world,
                    state_models=catalog.state_models,
                    model=catalog.uncertainty_model,
                    seed=_seed("seed-fail-0"),
                    realized_at=NOW,
                )

    def test_same_seed_never_resamples(self) -> None:
        world, catalog = self._failing_fixture()
        # The failing seed produces no partial artifact: the failure is
        # raised, never a partially built realization.
        with pytest.raises(WorldRealizationSamplingError):
            build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
                seed=_seed("seed-fail-1"),
                realized_at=NOW,
            )


class TestStrategyIndependence:
    def _fixture(self) -> tuple[WorldVersion, VerifiedWorldCatalog]:
        store = build_uncertainty_store()
        declare_model(store, bindings=(_draft(),))
        world, catalog = _compiled(store)
        return world, catalog

    def test_k_seeds_s_strategies_produce_k_realizations(self) -> None:
        world, catalog = self._fixture()
        seeds = tuple(_seed(f"seed-{index}") for index in range(4))
        for strategy_count in (1, 3, 5):
            matrix = build_campaign_world_realization_matrix(
                campaign=_campaign(
                    world=world,
                    seeds=seeds,
                    strategy_ids=tuple(f"sc-{index}" for index in range(strategy_count)),
                ),
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
            )
            assert len(matrix.realizations) == 4

    def test_strategy_count_order_do_not_change_bytes(self) -> None:
        world, catalog = self._fixture()
        seeds = (_seed("seed-1"), _seed("seed-2"))
        baseline = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=seeds, strategy_ids=("sc-a", "sc-b")),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        reordered = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=seeds, strategy_ids=("sc-b", "sc-a")),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        single = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=seeds, strategy_ids=("sc-c",)),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        assert baseline.model_dump(mode="json") == reordered.model_dump(mode="json")
        assert baseline.model_dump(mode="json") == single.model_dump(mode="json")

    def test_distinct_campaign_ids_compare_realization_identity(self) -> None:
        world, catalog = self._fixture()
        seeds = (_seed("seed-1"),)
        matrix_a = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=seeds, campaign_id="campaign-a"),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        matrix_b = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=seeds, campaign_id="campaign-b"),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        assert matrix_a.identifier != matrix_b.identifier
        assert matrix_a.realizations[0].identifier == matrix_b.realizations[0].identifier
        assert matrix_a.realizations[0].content_hash == matrix_b.realizations[0].content_hash

    def test_no_strategy_ids_in_realization_dumps(self) -> None:
        world, catalog = self._fixture()
        matrix = build_campaign_world_realization_matrix(
            campaign=_campaign(world=world, seeds=(_seed(),), strategy_ids=("sc-a", "sc-b")),
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
        )
        dump = matrix.model_dump(mode="json")
        assert "sc-a" not in str(dump)
        assert "strategy" not in str(dump)
        assert "mock-" not in str(dump)


class TestDirectProvenanceRejections:
    def _fixture(
        self,
    ) -> tuple[WorldVersion, VerifiedWorldCatalog, WorldUncertaintyModel]:
        store = build_uncertainty_store()
        model = declare_model(store, bindings=(_draft(),))
        world, catalog = _compiled(store)
        return world, catalog, model

    def test_foreign_seed_tenant(self) -> None:
        world, catalog, _ = self._fixture()
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
                seed=_seed(tenant_id=OTHER_TENANT),
                realized_at=NOW,
            )

    def test_model_tenant_mismatch(self) -> None:
        world, catalog, model = self._fixture()
        foreign = model.model_copy(update={"tenant_id": OTHER_TENANT})
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=foreign,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_model_scenario_mismatch(self) -> None:
        world, catalog, model = self._fixture()
        foreign = model.model_copy(update={"scenario_id": "scenario-other"})
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=foreign,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_campaign_tenant_mismatch(self) -> None:
        world, catalog, _ = self._fixture()
        # The campaign and its seeds share a foreign tenant; the builder
        # must reject the campaign/world tenant mismatch.
        with pytest.raises(WorldRealizationIntegrityError):
            build_campaign_world_realization_matrix(
                campaign=_campaign(
                    world=world,
                    seeds=(_seed(tenant_id=OTHER_TENANT),),
                    tenant_id=OTHER_TENANT,
                ),
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
            )

    def test_campaign_scenario_mismatch(self) -> None:
        world, catalog, _ = self._fixture()
        with pytest.raises(WorldRealizationIntegrityError):
            build_campaign_world_realization_matrix(
                campaign=_campaign(world=world, seeds=(_seed(),), scenario_id="scenario-other"),
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
            )

    def test_campaign_world_id_mismatch(self) -> None:
        world, catalog, _ = self._fixture()
        with pytest.raises(WorldRealizationIntegrityError):
            build_campaign_world_realization_matrix(
                campaign=_campaign(
                    world=world,
                    seeds=(_seed(),),
                    world_version_id="world-ffffffffffffffff",
                ),
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
            )

    def test_missing_target_state_model(self) -> None:
        world, catalog, _ = self._fixture()
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=(),
                model=catalog.uncertainty_model,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_mismatched_state_model_identity(self) -> None:
        world, catalog, _ = self._fixture()
        wrong = catalog.state_models[0].model_copy(update={"state_model_id": "sm-other"})
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=(wrong,),
                model=catalog.uncertainty_model,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_mismatched_state_model_content_hash(self) -> None:
        world, catalog, _ = self._fixture()
        wrong = catalog.state_models[0].model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=(wrong,),
                model=catalog.uncertainty_model,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_unknown_target_field(self) -> None:
        store = build_uncertainty_store()
        declare_model(
            store,
            bindings=(_draft(state_field_id="level"),),
        )
        world, catalog = _compiled(store)
        # Drop the targeted field from the supplied state model.
        state_model = catalog.state_models[0]
        trimmed = state_model.model_copy(
            update={
                "state_fields": tuple(
                    field for field in state_model.state_fields if field.identifier != "level"
                )
            }
        )
        with pytest.raises(WorldRealizationIntegrityError):
            build_world_realization(
                world=world,
                state_models=(trimmed,),
                model=catalog.uncertainty_model,
                seed=_seed(),
                realized_at=NOW,
            )

    def test_empty_seed_ensemble_rejected(self) -> None:
        world, catalog, _ = self._fixture()
        # A validator-bypassed campaign record with an empty seed
        # ensemble (the contract itself forbids it) must be rejected by
        # the builder before any sampling.
        bypassed = CampaignSpec.model_construct(
            identifier="campaign-empty",
            tenant_id=TENANT,
            schema_version="1.0.0",
            name="Reference campaign",
            scenario_id="scenario-1",
            world_version_id=world.identifier,
            strategy_candidate_ids=[],
            comparison_mode="identical_conditions",
            seed_ensemble=(),
            created_at=NOW,
            metadata={},
        )
        with pytest.raises(WorldRealizationIntegrityError):
            build_campaign_world_realization_matrix(
                campaign=bypassed,
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
            )
