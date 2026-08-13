"""Phase 25 runtime-3 metric-observation extraction and verified query tests.

Covers ``extract_realization_run_metric_observations`` (exact
identifier/content hashes, runtime literal, execution and realization
provenance, ``observed_at`` from the execution, canonical metric_id
ordering, raw values equal to the exact realized final-state fields,
units from the embedded ScenarioSpec, snapshot isolation, empty sets,
duplicate rejection), the causal per-seed realization proof (differing
realized values produce differing raw observations, same-seed
strategies share realization identity and raw values), all gates and
missing-record behavior, the full tamper matrix (aggregate provenance,
realization/execution references, observation set structure, raw
values, value kinds, self-consistently recomputed hashes rejected by
regeneration equality), snapshot isolation from live declarations, and
the purity/read-only boundaries.
"""

from __future__ import annotations

import copy
import inspect
import subprocess
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    RunInputIntegrityError,
    RunNotCompleteError,
    RunNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_errors import (
    RealizationRunMetricObservationAlreadyExistsError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
)
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_identity import (
    realization_run_metric_observation_set_content_hash,
    realization_run_metric_observation_set_identifier,
)
from kalhas.application.realization_run_metric_observation_service import (
    build_realization_run_metric_observation_set,
    extract_realization_run_metric_observations,
    get_verified_realization_run_metric_observation_set,
    verify_realization_run_metric_observation_set_record,
)
from kalhas.application.run_planner import (
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)

from tests.phase4_helpers import NOW, TENANT, build_seed, prepare, start
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase25_helpers import (
    inject_unsupported_recorded_runtime,
    runtime_three_execution_store,
    runtime_three_observation_store,
    runtime_three_store,
)

GENERIC_MESSAGE = "Realization metric observation integrity verification failed and was rejected"


def _observation_store() -> InMemoryScenarioStore:
    return runtime_three_observation_store()


def _plans(store: InMemoryScenarioStore) -> tuple[Any, ...]:
    return store.get_run_plans(TENANT, "campaign-1")


def _first_run_id(store: InMemoryScenarioStore) -> str:
    return run_identifier(_plans(store)[0])


def _verified(store: InMemoryScenarioStore, run_id: str) -> Any:
    return verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)


def _execution(store: InMemoryScenarioStore, run_id: str) -> Any:
    return store.get_realization_run_trajectory_execution(TENANT, run_id)


def _final_value(store: InMemoryScenarioStore, run_id: str, field: str) -> object:
    execution = _execution(store, run_id)
    return execution.results[0].final_state[field]


def _scenario_unit(store: InMemoryScenarioStore, metric_id: str) -> str | None:
    scenario = store.get_scenario(TENANT, "scenario-1")
    return next(metric.unit for metric in scenario.metrics if metric.identifier == metric_id)


def _differing_observation_store() -> InMemoryScenarioStore:
    """An observation store whose two seeds realize different level values."""
    from kalhas.application.world_integrity import extract_world_catalog
    from kalhas.application.world_realization_builder import build_world_realization

    probe = runtime_three_observation_store()
    world = next(iter(probe._worlds.values()))
    catalog = extract_world_catalog(world)
    levels: dict[str, Any] = {}
    for index in range(1, 25):
        seed = build_seed(identifier=f"seed-{index}")
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=NOW,
        )
        for override in realization.realized_initial_state_overrides:
            if override.state_field_id == "level":
                levels[seed.identifier] = override.value
    selected: tuple[Any, Any] | None = None
    for first, first_level in levels.items():
        for second, second_level in levels.items():
            if first != second and first_level != second_level:
                selected = (build_seed(identifier=first), build_seed(identifier=second))
                break
        if selected is not None:
            break
    assert selected is not None, "no two candidate seeds realized differing levels"
    return runtime_three_observation_store(seeds=selected)


class TestExtraction:
    def test_extracts_and_stores_exactly_one_set(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert len(store._realization_run_metric_observation_sets) == 1
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert stored == extracted

    def test_identifier_and_content_hash_exact(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert extracted.identifier == realization_run_metric_observation_set_identifier(
            run_id=run_id, runtime_version="3.0.0"
        )
        assert extracted.content_hash == realization_run_metric_observation_set_content_hash(
            extracted
        )

    def test_runtime_literal_exactly_three(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert extracted.runtime_version == "3.0.0"

    def test_execution_reference_exact(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        execution = _execution(store, run_id)
        assert extracted.realization_run_trajectory_execution_id == execution.identifier
        assert extracted.realization_run_trajectory_execution_content_hash == execution.content_hash

    def test_realization_reference_exact(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        verified = _verified(store, run_id)
        assert verified.realization is not None
        assert extracted.world_realization_id == verified.realization.identifier
        assert extracted.world_realization_content_hash == verified.realization.content_hash

    def test_observed_at_equals_execution_executed_at(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert extracted.observed_at == _execution(store, run_id).executed_at

    def test_observations_in_canonical_metric_order(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert [observation.metric_id for observation in extracted.observations] == [
            "m-1",
            "m-2",
        ]

    def test_raw_values_equal_realized_final_state_fields(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        for observation in extracted.observations:
            assert observation.raw_value == _final_value(store, run_id, observation.state_field_id)

    def test_units_come_from_embedded_scenario(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        for observation in extracted.observations:
            assert observation.metric_unit == _scenario_unit(store, observation.metric_id)

    def test_stored_value_is_snapshot_isolated(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert stored is not extracted
        assert stored == extracted
        again = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert again is not stored
        assert again == stored


class TestCausalRealization:
    def test_differing_seeds_produce_differing_raw_observations(self) -> None:
        store = _differing_observation_store()
        plans = _plans(store)
        # Strategy-major order: the first two plans are the same strategy
        # over the two deliberately differing seeds.
        first = plans[0]
        second = plans[1]
        assert first.scenario_seed_id != second.scenario_seed_id
        first_id = run_identifier(first)
        second_id = run_identifier(second)
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=first_id)
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=second_id)
        set_a = store.get_realization_run_metric_observation_set(TENANT, first_id)
        set_b = store.get_realization_run_metric_observation_set(TENANT, second_id)
        level_a = next(o for o in set_a.observations if o.metric_id == "m-1").raw_value
        level_b = next(o for o in set_b.observations if o.metric_id == "m-1").raw_value
        assert level_a != level_b
        # The observed values are exactly the realized final-state fields.
        assert level_a == _final_value(store, first_id, "level")
        assert level_b == _final_value(store, second_id, "level")

    def test_same_seed_strategies_share_realization_identity(self) -> None:
        store = _observation_store()
        plans = _plans(store)
        baseline = next(p for p in plans if p.strategy_candidate_id == "mock-baseline")
        conservative = next(p for p in plans if p.strategy_candidate_id == "mock-conservative")
        assert baseline.scenario_seed_id == conservative.scenario_seed_id
        set_a = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(baseline)
        )
        set_b = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(conservative)
        )
        assert set_a.world_realization_id == set_b.world_realization_id
        assert set_a.world_realization_content_hash == set_b.world_realization_content_hash

    def test_same_seed_strategies_extract_same_raw_values(self) -> None:
        store = _observation_store()
        plans = _plans(store)
        baseline = next(p for p in plans if p.strategy_candidate_id == "mock-baseline")
        conservative = next(p for p in plans if p.strategy_candidate_id == "mock-conservative")
        set_a = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(baseline)
        )
        set_b = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(conservative)
        )
        assert [o.raw_value for o in set_a.observations] == [
            o.raw_value for o in set_b.observations
        ]


class TestEmptyAndDuplicate:
    def test_world_without_bindings_produces_empty_set(self) -> None:
        store = runtime_three_execution_store()
        execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert extracted.observations == ()
        assert extracted.content_hash == realization_run_metric_observation_set_content_hash(
            extracted
        )

    def test_second_extraction_rejected_and_original_unchanged(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        first = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        with pytest.raises(RealizationRunMetricObservationAlreadyExistsError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert stored == first
        assert len(store._realization_run_metric_observation_sets) == 1


class TestGatesAndMissingRecords:
    def test_non_complete_run_rejected_without_writes(self) -> None:
        store = runtime_three_store()
        run_id = _first_run_id(store)
        with pytest.raises(RunNotCompleteError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        assert not store._realization_run_metric_observation_sets

    @pytest.mark.parametrize("runtime", ["1.0.0", "2.0.0"])
    def test_other_recorded_runtimes_rejected(self, runtime: str) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=runtime)
        if runtime == TRAJECTORY_RUNTIME_VERSION:
            prepare_strategy_trajectory_plans(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = _observation_store()
        plan = _plans(store)[0]
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_missing_execution_raises_typed_not_found(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        del store._realization_run_trajectory_executions[(TENANT, run_id)]
        with pytest.raises(RealizationRunTrajectoryExecutionNotFoundError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        assert not store._realization_run_metric_observation_sets

    def test_missing_query_artifact_not_extracted(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        with pytest.raises(RealizationRunMetricObservationNotFoundError):
            get_verified_realization_run_metric_observation_set(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        assert not store._realization_run_metric_observation_sets

    def test_foreign_tenant_and_unknown_run_isolated(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        with pytest.raises(RunNotFoundError):
            extract_realization_run_metric_observations(
                store=store, tenant_id="tenant-other", run_id=run_id
            )
        with pytest.raises(RunNotFoundError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id="run-unknown"
            )
        assert not store._realization_run_metric_observation_sets


class TestIntegrity:
    def test_tampered_execution_rejected_before_final_state_read(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        # Direct private-store injection: the put boundary revalidates on
        # write, so the tampered artifact is placed as if externally
        # loaded recorded state.
        store._realization_run_trajectory_executions[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        assert not store._realization_run_metric_observation_sets

    def test_tampered_input_provenance_rejected(self) -> None:
        store = _observation_store()
        plans = _plans(store)
        run_id = run_identifier(plans[0])
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]

        with pytest.raises(RunInputIntegrityError):
            extract_realization_run_metric_observations(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        assert not store._realization_run_metric_observation_sets

    def test_validator_bypassed_set_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        payload = extracted.model_dump(mode="python")
        payload["runtime_version"] = "2.0.0"
        bypassed = RealizationRunMetricObservationSet.model_construct(**payload)
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                bypassed,
                store=store,
                tenant_id=TENANT,
                run_id=run_id,
            )

    @pytest.mark.parametrize(
        "field",
        [
            "identifier",
            "tenant_id",
            "run_id",
            "campaign_id",
            "run_plan_id",
            "scenario_id",
            "world_version_id",
            "world_content_hash",
            "strategy_candidate_id",
            "strategy_content_hash",
            "scenario_seed_id",
            "runtime_version",
            "input_hash",
            "observed_at",
        ],
    )
    def test_every_aggregate_provenance_field_tampering_rejected(self, field: str) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        if field == "observed_at":
            tampered = extracted.model_copy(update={"observed_at": NOW.replace(year=2020)})
        elif field == "runtime_version":
            tampered = extracted.model_copy(update={"runtime_version": "2.0.0"})
        else:
            tampered = extracted.model_copy(update={field: f"tampered-{field}"})
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                tampered,
                store=store,
                tenant_id=TENANT,
                run_id=run_id,
            )

    def test_realization_reference_tampering_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        for field in ("world_realization_id", "world_realization_content_hash"):
            tampered = extracted.model_copy(update={field: "f" * 64})
            with pytest.raises(RealizationRunMetricObservationIntegrityError):
                verify_realization_run_metric_observation_set_record(
                    tampered,
                    store=store,
                    tenant_id=TENANT,
                    run_id=run_id,
                )

    def test_execution_reference_tampering_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        for field in (
            "realization_run_trajectory_execution_id",
            "realization_run_trajectory_execution_content_hash",
        ):
            tampered = extracted.model_copy(update={field: "f" * 64})
            with pytest.raises(RealizationRunMetricObservationIntegrityError):
                verify_realization_run_metric_observation_set_record(
                    tampered,
                    store=store,
                    tenant_id=TENANT,
                    run_id=run_id,
                )

    def test_observation_structure_tampering_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        observations = extracted.observations
        dropped = extracted.model_copy(update={"observations": observations[:1]})
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                dropped, store=store, tenant_id=TENANT, run_id=run_id
            )
        added = extracted.model_copy(update={"observations": observations + (observations[0],)})
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                added, store=store, tenant_id=TENANT, run_id=run_id
            )
        reordered = extracted.model_copy(
            update={"observations": (observations[1], observations[0])}
        )
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                reordered, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_observation_provenance_tampering_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        observation = extracted.observations[0]
        for field in (
            "metric_id",
            "binding_id",
            "binding_content_hash",
            "manifest_id",
            "state_model_identifier",
            "state_model_id",
            "state_model_content_hash",
            "state_field_id",
            "trajectory_plan_id",
            "trajectory_plan_content_hash",
            "trajectory_result_content_hash",
        ):
            tampered_observation = observation.model_copy(update={field: f"tampered-{field}"})
            tampered = extracted.model_copy(
                update={"observations": (tampered_observation,) + extracted.observations[1:]}
            )
            with pytest.raises(RealizationRunMetricObservationIntegrityError):
                verify_realization_run_metric_observation_set_record(
                    tampered, store=store, tenant_id=TENANT, run_id=run_id
                )

    def test_tampered_raw_value_with_recomputed_hash_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        observation = extracted.observations[0]
        tampered_observation = observation.model_copy(update={"raw_value": 999})
        tampered = extracted.model_copy(
            update={
                "observations": (tampered_observation,) + extracted.observations[1:],
                "content_hash": realization_run_metric_observation_set_content_hash(
                    extracted.model_copy(
                        update={
                            "observations": (tampered_observation,) + extracted.observations[1:]
                        }
                    )
                ),
            }
        )
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_value_kind_tampering_rejected(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        observation = extracted.observations[0]
        cases: tuple[object, ...] = (
            True,  # boolean for integer
            "1",  # string numeric
            1.0,  # int/float representation change
            float("nan"),
            float("inf"),
        )
        for wrong in cases:
            tampered_observation = observation.model_copy(update={"raw_value": wrong})
            tampered = extracted.model_copy(
                update={"observations": (tampered_observation,) + extracted.observations[1:]}
            )
            with pytest.raises(RealizationRunMetricObservationIntegrityError):
                verify_realization_run_metric_observation_set_record(
                    tampered, store=store, tenant_id=TENANT, run_id=run_id
                )

    def test_corrupted_record_never_repaired(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        tampered = extracted.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            verify_realization_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert stored == extracted

    def test_public_messages_never_leak_values(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        tampered = extracted.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunMetricObservationIntegrityError) as exc_info:
            verify_realization_run_metric_observation_set_record(
                tampered, store=store, tenant_id=TENANT, run_id=run_id
            )
        message = str(exc_info.value)
        assert "integrity" in message
        for leaked in ("level", "units", "0" * 64, "f" * 64, "m-1"):
            assert leaked not in message

    @pytest.mark.parametrize(
        "field, replacement",
        [
            ("tenant_id", "tenant-other"),
            ("world_version_id", "world-other"),
            ("strategy_content_hash", "f" * 64),
        ],
    )
    def test_direct_builder_execution_provenance_binding_fail_closed(
        self,
        field: str,
        replacement: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The public pure builder rejects tampered execution provenance.

        Rejects tenant, world-version, and strategy-content-hash tampering
        before embedded-scenario parsing, binding resolution, final-state
        access, or observation construction - and never mutates the
        original execution or inputs.
        """
        from kalhas.application import (
            realization_run_metric_observation_service as service_module,
        )

        store = _observation_store()
        run_id = _first_run_id(store)
        verified = _verified(store, run_id)
        execution = _execution(store, run_id)
        assert verified.realization is not None
        execution_before = copy.deepcopy(execution)
        inputs_before = copy.deepcopy(verified)

        touched: list[str] = []
        original_embedded = service_module._embedded_scenario
        original_build_value = service_module._build_observation_value

        def spy_embedded_scenario(*args: Any, **kwargs: Any) -> Any:
            touched.append("embedded_scenario")
            return original_embedded(*args, **kwargs)

        def spy_build_observation_value(*args: Any, **kwargs: Any) -> Any:
            touched.append("build_observation_value")
            return original_build_value(*args, **kwargs)

        monkeypatch.setattr(service_module, "_embedded_scenario", spy_embedded_scenario)
        monkeypatch.setattr(service_module, "_build_observation_value", spy_build_observation_value)

        tampered_execution = execution.model_copy(update={field: replacement})
        with pytest.raises(RealizationRunMetricObservationIntegrityError) as exc_info:
            build_realization_run_metric_observation_set(
                inputs=verified, execution=tampered_execution
            )
        # Rejection precedes catalog extraction, embedded-scenario
        # parsing, binding resolution, final-state access, and
        # observation construction.
        assert not touched
        message = str(exc_info.value)
        assert "integrity" in message
        assert replacement not in message
        assert "strategy" not in message
        assert "tenant" not in message
        assert "world_version" not in message
        # No mutation of the original execution or inputs.
        assert execution == execution_before
        assert verified == inputs_before

        # The correct execution remains accepted by the pure builder.
        correct = build_realization_run_metric_observation_set(inputs=verified, execution=execution)
        assert correct.realization_run_trajectory_execution_id == execution.identifier


class TestBoundaries:
    def test_live_declarations_after_compilation_do_not_affect_extraction(
        self,
    ) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        # A live declaration added after world compilation must never
        # reach the embedded world used for extraction.
        from kalhas.application.domain_metric_observation_service import (
            declare_domain_metric_observation,
        )

        from tests.phase20_helpers import DECLARED_AT

        declare_domain_metric_observation(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-3",
            state_field_id="level",
            declared_at=DECLARED_AT,
        )
        extracted = extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert [o.metric_id for o in extracted.observations] == ["m-1", "m-2"]

    def test_query_is_read_only_and_creates_no_activity(self) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        activity_before = len(store._operational_activity)
        events_before = len(store._run_events)
        result = get_verified_realization_run_metric_observation_set(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert len(store._operational_activity) == activity_before
        assert len(store._run_events) == events_before
        assert result == store.get_realization_run_metric_observation_set(TENANT, run_id)

    def test_trajectory_inputs_verified_exactly_once_per_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _observation_store()
        run_id = _first_run_id(store)
        calls = 0
        original = verify_run_trajectory_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        from kalhas.application import (
            realization_run_metric_observation_service as service_module,
        )

        monkeypatch.setattr(service_module, "verify_run_trajectory_inputs", counting)
        extract_realization_run_metric_observations(store=store, tenant_id=TENANT, run_id=run_id)
        assert calls == 1
        get_verified_realization_run_metric_observation_set(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert calls == 2

    def test_no_direct_run_scoped_verifier_import_or_call(self) -> None:
        from kalhas.application import (
            realization_run_metric_observation_service as service_module,
        )

        source = inspect.getsource(service_module)
        assert "verify_run_inputs" not in source
        assert "import input_integrity" not in source

    def test_no_evaluation_replay_or_lifecycle_calls(self) -> None:
        from kalhas.application import (
            realization_run_metric_observation_service as service_module,
        )

        source = inspect.getsource(service_module)
        for forbidden in (
            "evaluate_trajectory",
            "build_realization_run_trajectory_execution",
            "execute_realization_run",
            "import replay",
            "replay_service",
            "structural_events",
            "import sampling",
        ):
            assert forbidden not in source

    def test_no_adapters_random_time_network_or_filesystem(self) -> None:
        from kalhas.application import (
            realization_run_metric_observation_service as service_module,
        )

        source = inspect.getsource(service_module)
        assert "kalhas.adapters" not in source
        assert "import random" not in source
        assert "datetime.now" not in source
        assert "time.time(" not in source
        assert "urllib" not in source
        assert "requests" not in source
        assert "socket" not in source
        assert "open(" not in source

    def test_runtime_two_observation_service_source_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--exit-code",
                "--",
                "kalhas/application/run_metric_observation_service.py",
                "kalhas/application/structural_runtime.py",
                "kalhas/application/run_trajectory_runtime.py",
                "kalhas/application/trajectory_integrity.py",
                "kalhas/application/replay_service.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout
