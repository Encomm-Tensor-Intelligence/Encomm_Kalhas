"""Focused tests for the Phase 25 realization identity and provenance layer.

These tests prove the deterministic runtime-3 identifier and content-hash
rules (distinct readable prefixes, canonical payloads, self-covering
hashes), the pure ``verify_realization_provenance`` re-derivation
(scenario/world/seed agreement, seed-content-hash agreement,
uncertainty-model both-or-neither and exact identity/hash agreement,
identifier recomputation with sampler/quantization provenance, and
content-hash recomputation - every tamper rejected with the typed
integrity error), and the Amendment 5 import boundary: the identity
module never imports ``input_integrity`` at runtime, so no cycle can
arise between the input-integrity chain and the realization identity
layer.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Literal

import pytest
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_identifier,
    realization_metric_statistics_matrix_identifier,
    realization_run_metric_observation_set_identifier,
    realization_run_trajectory_execution_content_hash,
    realization_run_trajectory_execution_identifier,
    realization_run_trajectory_replay_manifest_content_hash,
    realization_run_trajectory_replay_manifest_identifier,
    realization_trajectory_matrix_identifier,
    verify_realization_provenance,
)
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization, WorldUncertaintyModel

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PLACEHOLDER = "0" * 64

RUNTIME: Literal["3.0.0"] = "3.0.0"


def build_world() -> WorldVersion:
    return WorldVersion(
        identifier="world-0123456789abcdef",
        tenant_id="tenant-1",
        source_scenario_id="scenario-1",
        parent_version_id=None,
        compiler_version="compiler-v1",
        content_hash="a" * 64,
        created_at=NOW,
    )


def build_seed() -> ScenarioSeed:
    return ScenarioSeed(
        identifier="seed-1",
        tenant_id="tenant-1",
        seed_value="value-1",
    )


def build_realization(world: WorldVersion, seed: ScenarioSeed) -> WorldRealization:
    """A minimal consistent empty realization (no uncertainty model)."""
    realization = WorldRealization(
        identifier=PLACEHOLDER,
        tenant_id=world.tenant_id,
        scenario_id=world.source_scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=seed.identifier,
        seed_content_hash=seed_content_hash(seed),
        uncertainty_model_id=None,
        uncertainty_model_content_hash=None,
        sampler_version="sha256-counter-v1",
        quantization_policy="rational-round-half-even",
        quantization_fraction_bits=64,
        sampled_values=(),
        realized_initial_state_overrides=(),
        content_hash=PLACEHOLDER,
        realized_at=NOW,
    )
    identifier = world_realization_identifier(
        world_version_id=realization.world_version_id,
        world_content_hash=realization.world_content_hash,
        scenario_seed_id=realization.scenario_seed_id,
        seed_content_hash_value=realization.seed_content_hash,
        uncertainty_model_id=None,
        uncertainty_model_content_hash_value=None,
        sampler_version=realization.sampler_version,
        quantization_policy=realization.quantization_policy,
        quantization_fraction_bits=realization.quantization_fraction_bits,
    )
    with_identifier = realization.model_copy(update={"identifier": identifier})
    content_hash = world_realization_content_hash(with_identifier)
    return with_identifier.model_copy(update={"content_hash": content_hash})


def build_execution() -> RealizationRunTrajectoryExecution:
    return RealizationRunTrajectoryExecution(
        identifier="realization-trajectory-execution-test",
        tenant_id="tenant-1",
        run_id="run-1",
        campaign_id="campaign-1",
        run_plan_id="plan-1",
        world_version_id="world-0123456789abcdef",
        world_content_hash="a" * 64,
        strategy_candidate_id="mock-baseline",
        strategy_content_hash="b" * 64,
        scenario_seed_id="seed-1",
        world_realization_id="realization-1",
        world_realization_content_hash="c" * 64,
        runtime_version=RUNTIME,
        input_hash="d" * 64,
        trajectory_plan_set_hash="e" * 64,
        results=(),
        content_hash=PLACEHOLDER,
        executed_at=NOW,
    )


class TestIdentifiers:
    def test_execution_identifier_is_deterministic_and_prefixed(self) -> None:
        first = realization_run_trajectory_execution_identifier(
            run_id="run-1", runtime_version=RUNTIME
        )
        second = realization_run_trajectory_execution_identifier(
            run_id="run-1", runtime_version=RUNTIME
        )
        assert first == second
        assert first.startswith("realization-trajectory-execution-")
        assert first != realization_run_trajectory_execution_identifier(
            run_id="run-2", runtime_version=RUNTIME
        )
        assert first != realization_run_trajectory_execution_identifier(
            run_id="run-1", runtime_version="2.0.0"
        )

    def test_all_identifier_prefixes_are_distinct(self) -> None:
        identifiers = [
            realization_run_trajectory_execution_identifier(
                run_id="run-1", runtime_version=RUNTIME
            ),
            realization_run_trajectory_replay_manifest_identifier("run-1"),
            realization_run_metric_observation_set_identifier(
                run_id="run-1", runtime_version=RUNTIME
            ),
            realization_trajectory_matrix_identifier(
                campaign_id="campaign-1", world_version_id="world-1", runtime_version=RUNTIME
            ),
            realization_metric_observation_matrix_identifier(
                campaign_id="campaign-1", world_version_id="world-1", runtime_version=RUNTIME
            ),
            realization_metric_statistics_matrix_identifier(
                campaign_id="campaign-1",
                world_version_id="world-1",
                runtime_version=RUNTIME,
                source_metric_observation_matrix_id="matrix-1",
            ),
        ]
        assert len(set(identifiers)) == len(identifiers)
        prefixes = [
            "realization-trajectory-execution-",
            "realization-replay-",
            "realization-metric-observation-set-",
            "realization-trajectory-matrix-",
            "realization-metric-observation-matrix-",
            "realization-metric-statistics-matrix-",
        ]
        for identifier, prefix in zip(identifiers, prefixes, strict=True):
            assert identifier.startswith(prefix)

    def test_replay_manifest_identifier_is_readable_run_form(self) -> None:
        assert realization_run_trajectory_replay_manifest_identifier("run-1") == (
            "realization-replay-run-1"
        )

    def test_statistics_identifier_covers_source_matrix(self) -> None:
        base = realization_metric_statistics_matrix_identifier(
            campaign_id="campaign-1",
            world_version_id="world-1",
            runtime_version=RUNTIME,
            source_metric_observation_matrix_id="matrix-1",
        )
        changed = realization_metric_statistics_matrix_identifier(
            campaign_id="campaign-1",
            world_version_id="world-1",
            runtime_version=RUNTIME,
            source_metric_observation_matrix_id="matrix-2",
        )
        assert base != changed


class TestContentHashes:
    def test_execution_content_hash_covers_every_field_except_itself(self) -> None:
        execution = build_execution()
        digest = realization_run_trajectory_execution_content_hash(execution)
        payload = execution.model_dump(mode="json")
        del payload["content_hash"]
        assert digest == sha256_hex(canonical_json(payload))
        assert digest != execution.content_hash  # placeholder differs

    def test_execution_content_hash_changes_when_any_field_tampered(self) -> None:
        execution = build_execution()
        base = realization_run_trajectory_execution_content_hash(execution)
        for field in ("world_realization_content_hash", "input_hash", "runtime_version"):
            tampered = execution.model_copy(update={field: "f" * 64})
            assert realization_run_trajectory_execution_content_hash(tampered) != base

    def test_replay_manifest_content_hash_is_self_covering(self) -> None:
        manifest = RealizationRunTrajectoryReplayManifest(
            identifier="realization-replay-run-1",
            tenant_id="tenant-1",
            run_id="run-1",
            campaign_id="campaign-1",
            realization_run_trajectory_execution_id="execution-1",
            realization_run_metric_observation_set_id="set-1",
            world_version_id="world-1",
            strategy_candidate_id="mock-baseline",
            scenario_seed_id="seed-1",
            world_realization_id="realization-1",
            world_realization_content_hash="c" * 64,
            runtime_version=RUNTIME,
            input_hash="d" * 64,
            trajectory_plan_set_hash="e" * 64,
            expected_execution_hash="f" * 64,
            recomputed_execution_hash="f" * 64,
            expected_observation_set_hash="1" * 64,
            recomputed_observation_set_hash="1" * 64,
            replay_classification="exact",
            replayed_at=NOW,
            content_hash=PLACEHOLDER,
        )
        digest = realization_run_trajectory_replay_manifest_content_hash(manifest)
        payload = manifest.model_dump(mode="json")
        del payload["content_hash"]
        assert digest == sha256_hex(canonical_json(payload))
        # Tampering the observation-set reference or hashes fails the recompute.
        for field in (
            "realization_run_metric_observation_set_id",
            "expected_observation_set_hash",
            "recomputed_observation_set_hash",
        ):
            tampered = manifest.model_copy(update={field: "2" * 64})
            assert realization_run_trajectory_replay_manifest_content_hash(tampered) != digest


class TestVerifyRealizationProvenance:
    def test_valid_empty_realization_passes(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        verify_realization_provenance(
            run_id="run-1",
            world=world,
            seed=seed,
            realization=realization,
            uncertainty_model=None,
        )  # must not raise

    def test_tampered_world_identity_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        other_world = world.model_copy(update={"identifier": "world-other"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=other_world,
                seed=seed,
                realization=realization,
                uncertainty_model=None,
            )

    def test_tampered_world_content_hash_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        other_world = world.model_copy(update={"content_hash": "b" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=other_world,
                seed=seed,
                realization=realization,
                uncertainty_model=None,
            )

    def test_tampered_seed_identity_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        other_seed = seed.model_copy(update={"identifier": "seed-2"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=world,
                seed=other_seed,
                realization=realization,
                uncertainty_model=None,
            )

    def test_tampered_seed_content_hash_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        other_seed = seed.model_copy(update={"seed_value": "value-2"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=world,
                seed=other_seed,
                realization=realization,
                uncertainty_model=None,
            )

    def test_model_present_without_realization_provenance_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        model = WorldUncertaintyModel.model_construct(identifier="model-1", content_hash="b" * 64)
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=world,
                seed=seed,
                realization=realization,
                uncertainty_model=model,
            )

    def test_model_identity_mismatch_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        model = WorldUncertaintyModel.model_construct(identifier="model-1", content_hash="b" * 64)
        with_model = realization.model_copy(
            update={
                "uncertainty_model_id": "model-1",
                "uncertainty_model_content_hash": "b" * 64,
            }
        )
        other_model = model.model_copy(update={"identifier": "model-2"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=world,
                seed=seed,
                realization=with_model,
                uncertainty_model=other_model,
            )

    def test_model_content_hash_mismatch_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        model = WorldUncertaintyModel.model_construct(identifier="model-1", content_hash="b" * 64)
        with_model = realization.model_copy(
            update={
                "uncertainty_model_id": "model-1",
                "uncertainty_model_content_hash": "b" * 64,
            }
        )
        other_model = model.model_copy(update={"content_hash": "c" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1",
                world=world,
                seed=seed,
                realization=with_model,
                uncertainty_model=other_model,
            )

    def test_tampered_realization_identifier_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        tampered = realization.model_copy(update={"identifier": "realization-tampered"})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1", world=world, seed=seed, realization=tampered, uncertainty_model=None
            )

    def test_tampered_realization_content_hash_rejected(self) -> None:
        world = build_world()
        seed = build_seed()
        realization = build_realization(world, seed)
        tampered = realization.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            verify_realization_provenance(
                run_id="run-1", world=world, seed=seed, realization=tampered, uncertainty_model=None
            )


class TestImportBoundary:
    def test_identity_module_never_imports_input_integrity(self) -> None:
        """Amendment 5: the identity layer must be import-cycle-free.

        Runs in a fresh interpreter so pre-imported modules in this test
        process cannot mask a runtime import of input_integrity.
        """
        probe = (
            "import sys; "
            "import kalhas.application.realization_identity as identity; "
            "assert 'kalhas.application.input_integrity' not in sys.modules, "
            "'realization_identity imported input_integrity'; "
            "print('acyclic')"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=None,
        )
        assert result.returncode == 0, result.stderr
        assert "acyclic" in result.stdout
