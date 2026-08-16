"""Tests for the pure campaign outcome-distribution matrix builder.

Tests for ``kalhas/application/campaign_outcome_matrix_runtime.py`` and
``kalhas/application/campaign_outcome_errors.py``: the single public
``build_campaign_outcome_distribution_matrix`` builder consuming three
already-authoritative source artifacts (the ``ScenarioEvaluationProfile``,
the ``CampaignWorldRealizationMatrix``, and the
``RealizationCampaignMetricObservationMatrix``) and the safe typed
``CampaignOutcomeDistributionMatrixIntegrityError``. Proves:

- valid multi-strategy/multi-seed/multi-objective matrices over the real
  Phase 25 acceptance lifecycle, including targeted
  minimize/maximize/reach outcomes, optimization-only objectives, and
  multiple objectives bound to the same metric;
- exact strategy-major/objective-minor output order, exact per-outcome
  seed order, exact non-lexical profile binding order, the golden
  identifier and recomputed content hash, the ``derived_at`` timestamp
  lineage from ``assembled_at``, optional uncertainty both absent and
  present, deterministic repeated/JSON equality, and zero input
  mutation;
- the complete adversarial rejection matrix: wrong-object inputs,
  unsupported runtime, validator-bypassed artifacts, profile/
  realization-matrix/observation-matrix identifier and content-hash
  tampering (including self-consistently rehashed attacks), nested
  realization identifier/hash tampering, cross-source tenant/scenario/
  campaign/world/hash/seed/timestamp/realization-tuple mismatches,
  observation-matrix structural tampering, binding-provenance drift,
  raw bool/string/NaN/Infinity/kind mismatches, binding metric and
  metric-unit boundary violations, and huge-integer/arithmetic
  overflow - all raising the safe typed integrity error (or the
  established unsupported-runtime error), never a partial artifact;
- the safe public error message with internal-reason separation;
- the module import/purity boundary and the absence of duplicated
  statistical algorithms;
- unchanged registry/schema counts and byte-identical preservation of
  every accepted earlier-slice file.
"""

from __future__ import annotations

import ast
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
)
from kalhas.application.campaign_outcome_matrix_runtime import (
    build_campaign_outcome_distribution_matrix,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
)
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_service import (
    prepare_realization_campaign,
)
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_content_hash,
)
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.application.world_uncertainty_identity import (
    campaign_realization_matrix_content_hash,
    campaign_realization_matrix_identifier,
)
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix
from kalhas.contracts.v1.objective_evaluation import (
    ObjectiveMetricBinding,
    ScenarioEvaluationProfile,
)
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world_realization import CampaignWorldRealizationMatrix

from tests.phase4_helpers import NOW, TENANT, build_request, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import uncertainty_fields
from tests.phase25_helpers import (
    _TRANSITION_GUARD,
    _TRANSITION_TARGET,
    RUNTIME_THREE_SEEDS,
    acceptance_observation_store,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "kalhas"
    / "application"
    / "campaign_outcome_matrix_runtime.py"
)
ERRORS_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_outcome_errors.py"
)
KALHAS_ROOT = Path(__file__).resolve().parents[1] / "kalhas"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

#: Golden identifier of the standard acceptance outcome matrix.
GOLDEN_IDENTIFIER = "campaign-outcome-distribution-matrix-d28d57b4114cca79"

#: Golden canonical content hash of the standard acceptance outcome matrix.
GOLDEN_CONTENT_HASH = "352bfbf8028d39dadc2657db6f2b4b3d21322d130a5ac02a986e7d0253d94e4e"

#: The accepted earlier-slice files with their preservation hashes.
_PRESERVED_FILES = (
    (
        "kalhas/application/campaign_outcome_statistics.py",
        "5e4d32f8346a543c3260a43e67df593d695e8e091d0592a46566f8e08ae0e3d2",
    ),
    (
        "kalhas/application/campaign_outcome_runtime.py",
        "2829dffa57d45398265f831f704839e5a702853973a243c4d8d33b3c01ef3fd9",
    ),
    (
        "kalhas/application/campaign_outcome_identity.py",
        "be673a606fb6308b1c1c88104bde44e10714ef5b95d5f469a0b2d1053f747a04",
    ),
    (
        "kalhas/contracts/v1/campaign_outcome.py",
        "0100c5e5be6a47483c340179be8a4ba733662b7a1d58d5866cc8f1720d66cdd4",
    ),
    (
        "tests/test_campaign_outcome_statistics.py",
        "4f9dc8fd70e0a34cf20a91abc94df85600c5cb4fadb375c2f5450be02c9111bf",
    ),
    (
        "tests/test_campaign_outcome_runtime.py",
        "cf55a64ede5f2b12643f598e42db66741ce53e92326e41ca4e62615d2a289cac",
    ),
    (
        "tests/test_campaign_outcome_identity.py",
        "41db11e7c6e6864b289379e1493b87aa36034682044466aaf4faa541ca795539",
    ),
    (
        "tests/test_campaign_outcome_contracts.py",
        "6315c5f118ca697042014c62dec8abf796d4f8246b224adb0b301354fe015169",
    ),
    (
        "CODEX_HERMES_HANDOFF_PHASE_26_START.md",
        "0ce6a46915666fb29ef7e4fe2b49d324e8e094187d78404f0b733db1fcda1f22",
    ),
)

#: The five standard acceptance bindings over the single observed metric m-1:
#: minimize, maximize, reach, optimization-only minimize, optimization-only
#: maximize - multiple objectives bound to the same metric.
_ACCEPTANCE_BINDINGS = (
    ObjectiveMetricBinding(
        objective_id="obj-1",
        metric_id="m-1",
        direction="minimize",
        target=100.0,
        weight=1.0,
        metric_unit="units",
        reach_tolerance=None,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBinding(
        objective_id="obj-2",
        metric_id="m-1",
        direction="maximize",
        target=90.0,
        weight=1.0,
        metric_unit="units",
        reach_tolerance=None,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBinding(
        objective_id="obj-3",
        metric_id="m-1",
        direction="reach",
        target=100.0,
        weight=1.0,
        metric_unit="units",
        reach_tolerance=5.0,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBinding(
        objective_id="obj-4",
        metric_id="m-1",
        direction="minimize",
        target=None,
        weight=1.0,
        metric_unit="units",
        reach_tolerance=None,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBinding(
        objective_id="obj-5",
        metric_id="m-1",
        direction="maximize",
        target=None,
        weight=1.0,
        metric_unit="units",
        reach_tolerance=None,
        normalization_scale=100.0,
    ),
)


def _binding(**overrides: object) -> ObjectiveMetricBinding:
    """One valid objective-to-metric binding on metric ``m-1`` (unit ``units``)."""
    payload: dict[str, object] = {
        "objective_id": "obj-1",
        "metric_id": "m-1",
        "direction": "minimize",
        "target": 100.0,
        "weight": 1.0,
        "metric_unit": "units",
        "reach_tolerance": None,
        "normalization_scale": 100.0,
    }
    payload.update(overrides)
    return ObjectiveMetricBinding(**cast(Any, payload))


def _profile(
    scenario_hash: str,
    *,
    bindings: tuple[ObjectiveMetricBinding, ...],
) -> ScenarioEvaluationProfile:
    """One self-consistent evaluation profile over the authoritative scenario."""
    profile = ScenarioEvaluationProfile(
        identifier=evaluation_profile_identifier(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            scenario_content_hash_value=scenario_hash,
        ),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        scenario_content_hash=scenario_hash,
        bindings=bindings,
        content_hash="0" * 64,
        declared_at=DECLARED_AT,
    )
    return profile.model_copy(update={"content_hash": evaluation_profile_content_hash(profile)})


def _rehash_profile(profile: ScenarioEvaluationProfile) -> ScenarioEvaluationProfile:
    """One profile with a recomputed content hash (identity kept)."""
    return profile.model_copy(update={"content_hash": evaluation_profile_content_hash(profile)})


def _reidentify_profile(
    profile: ScenarioEvaluationProfile, **updates: object
) -> ScenarioEvaluationProfile:
    """One self-consistently rehashed profile variant (identifier + hash recomputed)."""
    tampered = profile.model_copy(update=updates)
    tampered = tampered.model_copy(
        update={
            "identifier": evaluation_profile_identifier(
                tenant_id=tampered.tenant_id,
                scenario_id=tampered.scenario_id,
                scenario_content_hash_value=tampered.scenario_content_hash,
            )
        }
    )
    return tampered.model_copy(update={"content_hash": evaluation_profile_content_hash(tampered)})


def _rehash_realization_matrix(
    matrix: CampaignWorldRealizationMatrix,
) -> CampaignWorldRealizationMatrix:
    """One realization matrix with a recomputed content hash (identity kept)."""
    return matrix.model_copy(
        update={"content_hash": campaign_realization_matrix_content_hash(matrix)}
    )


def _reidentify_realization_matrix(
    matrix: CampaignWorldRealizationMatrix, **updates: object
) -> CampaignWorldRealizationMatrix:
    """One self-consistently rehashed realization-matrix variant."""
    tampered = matrix.model_copy(update=updates)
    tampered = tampered.model_copy(
        update={
            "identifier": campaign_realization_matrix_identifier(
                campaign_id=tampered.campaign_id,
                world_version_id=tampered.world_version_id,
                world_content_hash=tampered.world_content_hash,
                uncertainty_model_id=tampered.uncertainty_model_id,
                uncertainty_model_content_hash_value=(tampered.uncertainty_model_content_hash),
                sampler_version=tampered.sampler_version,
                quantization_policy=tampered.quantization_policy,
                quantization_fraction_bits=tampered.quantization_fraction_bits,
            )
        }
    )
    return tampered.model_copy(
        update={"content_hash": campaign_realization_matrix_content_hash(tampered)}
    )


def _rehash_observation_matrix(
    matrix: RealizationCampaignMetricObservationMatrix,
) -> RealizationCampaignMetricObservationMatrix:
    """One observation matrix with a recomputed content hash (identity kept)."""
    return matrix.model_copy(
        update={"content_hash": realization_metric_observation_matrix_content_hash(matrix)}
    )


def _tamper_observation_cell(
    observation_matrix: RealizationCampaignMetricObservationMatrix,
    *,
    cell_index: int,
    observation_index: int,
    **updates: object,
) -> RealizationCampaignMetricObservationMatrix:
    """One observation field tampered inside one cell (no rehash)."""
    cell = observation_matrix.cells[cell_index]
    observation = cell.observations[observation_index]
    tampered_observation = observation.model_copy(update=updates)
    tampered_cell = cell.model_copy(
        update={
            "observations": (
                cell.observations[:observation_index]
                + (tampered_observation,)
                + cell.observations[observation_index + 1 :]
            )
        }
    )
    return observation_matrix.model_copy(
        update={
            "cells": (
                observation_matrix.cells[:cell_index]
                + (tampered_cell,)
                + observation_matrix.cells[cell_index + 1 :]
            )
        }
    )


def _tamper_all_raw_values(
    observation_matrix: RealizationCampaignMetricObservationMatrix,
    value: object,
) -> RealizationCampaignMetricObservationMatrix:
    """Every observation raw value replaced (no rehash)."""
    cells = tuple(
        cell.model_copy(
            update={
                "observations": tuple(
                    observation.model_copy(update={"raw_value": value})
                    for observation in cell.observations
                )
            }
        )
        for cell in observation_matrix.cells
    )
    return observation_matrix.model_copy(update={"cells": cells})


def _tamper_realization(
    world_realization_matrix: CampaignWorldRealizationMatrix,
    *,
    index: int,
    **updates: object,
) -> CampaignWorldRealizationMatrix:
    """One nested realization field tampered, with the matrix rehashed."""
    realization = world_realization_matrix.realizations[index]
    tampered = realization.model_copy(update=updates)
    matrix = world_realization_matrix.model_copy(
        update={
            "realizations": (
                world_realization_matrix.realizations[:index]
                + (tampered,)
                + world_realization_matrix.realizations[index + 1 :]
            )
        }
    )
    return matrix.model_copy(
        update={"content_hash": campaign_realization_matrix_content_hash(matrix)}
    )


@pytest.fixture(scope="module")
def acceptance_store() -> InMemoryScenarioStore:
    """The real executed acceptance campaign store (built once per module)."""
    return acceptance_observation_store()


@pytest.fixture(scope="module")
def acceptance_scenario_hash(acceptance_store: InMemoryScenarioStore) -> str:
    """The authoritative scenario snapshot hash of the acceptance scenario."""
    return scenario_content_hash(acceptance_store.get_scenario(TENANT, "scenario-1"))


@pytest.fixture(scope="module")
def acceptance_inputs(
    acceptance_store: InMemoryScenarioStore,
    acceptance_scenario_hash: str,
) -> tuple[
    ScenarioEvaluationProfile,
    CampaignWorldRealizationMatrix,
    RealizationCampaignMetricObservationMatrix,
]:
    """The three authoritative source artifacts of the acceptance campaign."""
    return (
        _profile(acceptance_scenario_hash, bindings=_ACCEPTANCE_BINDINGS),
        get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        ),
        get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        ),
    )


@pytest.fixture(scope="module")
def no_model_inputs() -> tuple[
    ScenarioEvaluationProfile,
    CampaignWorldRealizationMatrix,
    RealizationCampaignMetricObservationMatrix,
]:
    """The three authoritative source artifacts of a model-free campaign.

    Mirrors the accepted ``runtime_three_observation_store`` lifecycle
    exactly except that no uncertainty model is declared, so the
    compiled world carries no model and every realization is model-free.
    """
    store = InMemoryScenarioStore()
    store.put_scenario(build_observation_scenario())
    _register_pack(store)
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=uncertainty_fields(),
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-1",
        state_field_id="level",
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-2",
        state_field_id="ratio",
        declared_at=DECLARED_AT,
    )
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
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
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
        campaign_name="Model-free outcome campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    scenario_hash = scenario_content_hash(store.get_scenario(TENANT, "scenario-1"))
    profile = _profile(
        scenario_hash,
        bindings=(
            _binding(
                objective_id="obj-1",
                metric_id="m-1",
                direction="minimize",
                target=100.0,
            ),
            _binding(
                objective_id="obj-2",
                metric_id="m-2",
                direction="maximize",
                target=0.5,
                metric_unit="percent",
                normalization_scale=1.0,
            ),
        ),
    )
    return (
        profile,
        get_verified_campaign_world_realizations(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        ),
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        ),
    )


def _build(
    profile: ScenarioEvaluationProfile,
    world_realization_matrix: CampaignWorldRealizationMatrix,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> CampaignOutcomeDistributionMatrix:
    return build_campaign_outcome_distribution_matrix(
        profile=profile,
        world_realization_matrix=world_realization_matrix,
        observation_matrix=observation_matrix,
    )


class TestValidMatrix:
    def test_multi_strategy_multi_seed_multi_objective_golden(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        assert matrix.ordered_strategy_candidate_ids == ("mock-a", "mock-b")
        assert matrix.ordered_scenario_seed_ids == ("seed-0", "seed-2")
        assert matrix.ordered_metric_ids == ("m-1",)
        assert matrix.ordered_objective_ids == (
            "obj-1",
            "obj-2",
            "obj-3",
            "obj-4",
            "obj-5",
        )
        assert len(matrix.outcomes) == 2 * 5
        assert matrix.identifier == GOLDEN_IDENTIFIER
        assert matrix.content_hash == GOLDEN_CONTENT_HASH
        assert matrix.content_hash == campaign_outcome_distribution_matrix_content_hash(matrix)
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.scenario_content_hash == profile.scenario_content_hash
        assert matrix.evaluation_profile_id == profile.identifier
        assert matrix.evaluation_profile_content_hash == profile.content_hash
        assert matrix.source_world_realization_matrix_id == realization_matrix.identifier
        assert matrix.source_world_realization_matrix_content_hash == (
            realization_matrix.content_hash
        )
        assert matrix.source_metric_observation_matrix_id == observation_matrix.identifier
        assert matrix.source_metric_observation_matrix_content_hash == (
            observation_matrix.content_hash
        )
        assert matrix.uncertainty_model_id == realization_matrix.uncertainty_model_id
        assert matrix.uncertainty_model_content_hash == (
            realization_matrix.uncertainty_model_content_hash
        )

    def test_targeted_minimize_maximize_reach_outcomes(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        minimize = matrix.outcomes[0]
        assert minimize.direction == "minimize"
        assert minimize.ordered_observed_values == (84, 103)
        assert minimize.target_achievement_count == 1
        assert minimize.empirical_target_achievement_probability == 0.5
        assert minimize.worst_normalized_target_violation == 0.03
        assert minimize.target_violation_cvar == 0.03
        assert minimize.adverse_tail_statistic == 103.0
        maximize = matrix.outcomes[1]
        assert maximize.direction == "maximize"
        assert maximize.target_achievement_count == 1
        assert maximize.worst_normalized_target_violation == 0.06
        assert maximize.target_violation_cvar == 0.06
        assert maximize.adverse_tail_statistic == 84.0
        reach = matrix.outcomes[2]
        assert reach.direction == "reach"
        assert reach.reach_tolerance == 5.0
        assert reach.target_achievement_count == 1
        assert reach.worst_normalized_target_violation == 0.11
        assert reach.target_violation_cvar == 0.11
        assert reach.adverse_tail_statistic == 16.0

    def test_optimization_only_outcomes(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        for outcome in (matrix.outcomes[3], matrix.outcomes[4]):
            assert outcome.target is None
            assert outcome.target_achievement_count is None
            assert outcome.empirical_target_achievement_probability is None
            assert outcome.normalized_target_violation_distribution is None
            assert outcome.worst_normalized_target_violation is None
            assert outcome.target_violation_cvar is None
        assert matrix.outcomes[3].direction == "minimize"
        assert matrix.outcomes[3].adverse_tail_statistic == 103.0
        assert matrix.outcomes[4].direction == "maximize"
        assert matrix.outcomes[4].adverse_tail_statistic == 84.0

    def test_multiple_objectives_bound_to_the_same_metric(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        assert all(outcome.metric_id == "m-1" for outcome in matrix.outcomes)
        assert len({outcome.objective_id for outcome in matrix.outcomes}) == 5

    def test_exact_strategy_major_objective_minor_order(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        assert [(o.strategy_candidate_id, o.objective_id) for o in matrix.outcomes] == [
            (strategy, objective)
            for strategy in ("mock-a", "mock-b")
            for objective in ("obj-1", "obj-2", "obj-3", "obj-4", "obj-5")
        ]
        assert [o.sequence_position for o in matrix.outcomes] == list(range(10))
        assert [o.strategy_position for o in matrix.outcomes] == [0] * 5 + [1] * 5
        assert [o.objective_position for o in matrix.outcomes] == list(range(5)) * 2

    def test_exact_per_outcome_seed_order(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        for outcome in matrix.outcomes:
            assert outcome.ordered_observed_values == (84, 103)
            assert outcome.empirical_distribution.ordered_samples == (84, 103)
            assert outcome.empirical_distribution.sample_count == 2

    def test_non_lexical_profile_binding_order_preserved(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        acceptance_scenario_hash: str,
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        reordered = _profile(
            acceptance_scenario_hash,
            bindings=(
                _binding(objective_id="z-first", metric_id="m-1", direction="minimize"),
                _binding(objective_id="a-second", metric_id="m-1", direction="maximize"),
                _binding(
                    objective_id="m-middle",
                    metric_id="m-1",
                    direction="reach",
                    target=100.0,
                    reach_tolerance=5.0,
                ),
            ),
        )
        matrix = _build(reordered, realization_matrix, observation_matrix)
        assert matrix.ordered_objective_ids == ("z-first", "a-second", "m-middle")
        assert [o.objective_id for o in matrix.outcomes] == (
            ["z-first", "a-second", "m-middle"] * 2
        )

    def test_derived_at_copied_from_observation_matrix(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        matrix = _build(profile, realization_matrix, observation_matrix)
        assert matrix.derived_at == observation_matrix.assembled_at == NOW

    def test_uncertainty_present_and_absent(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        no_model_inputs: tuple[Any, Any, Any],
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        present = _build(profile, realization_matrix, observation_matrix)
        assert present.uncertainty_model_id is not None
        assert present.uncertainty_model_content_hash is not None
        assert present.uncertainty_model_id == realization_matrix.uncertainty_model_id
        absent_profile, absent_realization, absent_observation = no_model_inputs
        absent = _build(absent_profile, absent_realization, absent_observation)
        assert absent.uncertainty_model_id is None
        assert absent.uncertainty_model_content_hash is None
        assert absent.ordered_metric_ids == ("m-1", "m-2")
        assert [o.metric_id for o in absent.outcomes[:2]] == ["m-1", "m-2"]

    def test_deterministic_repeated_and_json_equality(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        first = _build(profile, realization_matrix, observation_matrix)
        second = _build(profile, realization_matrix, observation_matrix)
        assert first == second
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.model_dump_json() == second.model_dump_json()

    def test_zero_input_mutation(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        profile_before = profile.model_dump(mode="python")
        realization_before = realization_matrix.model_dump(mode="python")
        observation_before = observation_matrix.model_dump(mode="python")
        _build(profile, realization_matrix, observation_matrix)
        _build(profile, realization_matrix, observation_matrix)
        assert profile.model_dump(mode="python") == profile_before
        assert realization_matrix.model_dump(mode="python") == realization_before
        assert observation_matrix.model_dump(mode="python") == observation_before


class TestTypeAndRuntimeBoundary:
    @pytest.mark.parametrize(
        "wrong",
        (
            pytest.param(cast(Any, {"scenario_id": "s"}), id="dict"),
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, "profile"), id="string"),
            pytest.param(cast(Any, 42), id="integer"),
        ),
    )
    def test_wrong_object_profile_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        wrong: object,
    ) -> None:
        _, realization_matrix, observation_matrix = acceptance_inputs
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(cast(Any, wrong), realization_matrix, observation_matrix)

    @pytest.mark.parametrize(
        "wrong",
        (
            pytest.param(cast(Any, {"campaign_id": "c"}), id="dict"),
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, "matrix"), id="string"),
        ),
    )
    def test_wrong_object_world_realization_matrix_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        wrong: object,
    ) -> None:
        profile, _, observation_matrix = acceptance_inputs
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, cast(Any, wrong), observation_matrix)

    @pytest.mark.parametrize(
        "wrong",
        (
            pytest.param(cast(Any, {"campaign_id": "c"}), id="dict"),
            pytest.param(cast(Any, None), id="none"),
            pytest.param(cast(Any, "matrix"), id="string"),
        ),
    )
    def test_wrong_object_observation_matrix_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        wrong: object,
    ) -> None:
        profile, realization_matrix, _ = acceptance_inputs
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, cast(Any, wrong))

    def test_wrong_model_types_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(realization_matrix, profile, observation_matrix)
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, observation_matrix, realization_matrix)

    def test_unsupported_runtime_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"runtime_version": "2.0.0"})
        with pytest.raises(UnsupportedRuntimeVersionError) as excinfo:
            _build(profile, realization_matrix, tampered)
        assert excinfo.value.runtime_version == "2.0.0"
        assert excinfo.value.operation == "campaign outcome distribution matrix"


class TestStrictRevalidation:
    def test_validator_bypassed_profile_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        _, realization_matrix, observation_matrix = acceptance_inputs
        bad_binding = ObjectiveMetricBinding.model_construct(
            objective_id="obj-1",
            metric_id="m-1",
            direction="minimize",
            target=100.0,
            weight=1.0,
            metric_unit="units",
            reach_tolerance=None,
            normalization_scale=-1.0,
        )
        bypassed = ScenarioEvaluationProfile.model_construct(
            identifier="evaluation-profile-0000000000000000",
            tenant_id=TENANT,
            scenario_id="scenario-1",
            scenario_content_hash="xyz",
            bindings=(bad_binding,),
            content_hash="0" * 64,
            declared_at=DECLARED_AT,
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(bypassed, realization_matrix, observation_matrix)

    def test_validator_bypassed_realization_matrix_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, _, observation_matrix = acceptance_inputs
        bypassed = CampaignWorldRealizationMatrix.model_construct(
            identifier="campaign-realization-matrix-0000000000000000",
            tenant_id=TENANT,
            campaign_id="campaign-1",
            scenario_id="scenario-1",
            world_version_id="world-1",
            world_content_hash="xyz",
            sampler_version="sha256-counter-v1",
            quantization_policy="rational-round-half-even",
            quantization_fraction_bits=64,
            ordered_scenario_seed_ids=("seed-0", "seed-2"),
            realizations=(),
            content_hash="0" * 64,
            assembled_at=NOW,
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, bypassed, observation_matrix)

    def test_validator_bypassed_observation_matrix_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, _ = acceptance_inputs
        bypassed = RealizationCampaignMetricObservationMatrix.model_construct(
            identifier="metric-observation-matrix-0000000000000000",
            tenant_id=TENANT,
            campaign_id="campaign-1",
            scenario_id="scenario-1",
            world_version_id="world-1",
            world_content_hash="xyz",
            runtime_version="3.0.0",
            comparison_mode="identical_conditions",
            ordered_strategy_candidate_ids=(),
            ordered_scenario_seed_ids=(),
            ordered_metric_ids=(),
            ordered_world_realization_ids=(),
            ordered_world_realization_content_hashes=(),
            cells=(),
            content_hash="0" * 64,
            assembled_at=NOW,
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, bypassed)


class TestIdentityTampering:
    def test_profile_identifier_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_profile(
            profile.model_copy(update={"identifier": "evaluation-profile-0000000000000000"})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)

    def test_profile_content_hash_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = profile.model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)

    def test_realization_matrix_identifier_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_realization_matrix(
            realization_matrix.model_copy(
                update={"identifier": "campaign-realization-matrix-0000000000000000"}
            )
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_realization_matrix_content_hash_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = realization_matrix.model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_nested_realization_identifier_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _tamper_realization(
            realization_matrix,
            index=0,
            identifier="world-realization-0000000000000000",
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_nested_realization_content_hash_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _tamper_realization(realization_matrix, index=0, content_hash="0" * 64)
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_observation_matrix_identifier_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_observation_matrix(
            observation_matrix.model_copy(
                update={"identifier": "metric-observation-matrix-0000000000000000"}
            )
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_observation_matrix_content_hash_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)


class TestCrossSourceMismatches:
    def test_tenant_mismatch_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_realization_matrix(
            realization_matrix.model_copy(update={"tenant_id": "tenant-9"})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_scenario_mismatch_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _reidentify_realization_matrix(
            realization_matrix.model_copy(update={"scenario_id": "scenario-9"})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_campaign_mismatch_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _reidentify_realization_matrix(
            realization_matrix.model_copy(update={"campaign_id": "campaign-9"})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_world_version_mismatch_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _reidentify_realization_matrix(
            realization_matrix.model_copy(update={"world_version_id": "world-9"})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_world_content_hash_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _reidentify_realization_matrix(
            realization_matrix.model_copy(update={"world_content_hash": "0" * 64})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, tampered, observation_matrix)

    def test_profile_scenario_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _reidentify_profile(
            profile, scenario_id="scenario-9", scenario_content_hash="1" * 64
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)

    @pytest.mark.parametrize(
        "seeds",
        (
            pytest.param(("seed-0",), id="missing"),
            pytest.param(("seed-0", "seed-2", "seed-9"), id="additional"),
            pytest.param(("seed-2", "seed-0"), id="reordered"),
        ),
    )
    def test_seed_mismatch_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        seeds: tuple[str, ...],
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"ordered_scenario_seed_ids": seeds})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_timestamp_lineage_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(
            update={"assembled_at": datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_realization_identity_tuple_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(
            update={
                "ordered_world_realization_ids": (
                    "world-realization-0000000000000000",
                    "world-realization-1111111111111111",
                )
            }
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_realization_content_hash_tuple_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(
            update={"ordered_world_realization_content_hashes": ("0" * 64, "1" * 64)}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_observation_comparison_mode_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"comparison_mode": "shared_conditions"})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)


class TestObservationStructure:
    def test_missing_cells_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"cells": observation_matrix.cells[:-1]})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_additional_cell_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        extra = observation_matrix.cells[0]
        tampered = observation_matrix.model_copy(
            update={"cells": (*observation_matrix.cells, extra)}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_reordered_cells_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(
            update={"cells": tuple(reversed(observation_matrix.cells))}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_strategy_identity_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        cell = observation_matrix.cells[0]
        tampered_cell = cell.model_copy(update={"strategy_candidate_id": "mock-x"})
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_seed_identity_tamper_rejected(self, acceptance_inputs: tuple[Any, Any, Any]) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        cell = observation_matrix.cells[0]
        tampered_cell = cell.model_copy(update={"scenario_seed_id": "seed-x"})
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_cell_realization_identity_tamper_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        cell = observation_matrix.cells[0]
        tampered_cell = cell.model_copy(
            update={"world_realization_id": "world-realization-0000000000000000"}
        )
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_metric_collection_missing_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        cell = observation_matrix.cells[0]
        tampered_cell = cell.model_copy(update={"observations": ()})
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_metric_collection_additional_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        cell = observation_matrix.cells[0]
        extra = cell.observations[0].model_copy(update={"metric_id": "m-9"})
        tampered_cell = cell.model_copy(update={"observations": (*cell.observations, extra)})
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_metric_collection_reordered_rejected(
        self, no_model_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = no_model_inputs
        cell = observation_matrix.cells[0]
        first, second = cell.observations
        swapped = (
            second.model_copy(update={"metric_id": first.metric_id}),
            first.model_copy(update={"metric_id": second.metric_id}),
        )
        tampered_cell = cell.model_copy(update={"observations": swapped})
        tampered = observation_matrix.model_copy(
            update={"cells": (tampered_cell, *observation_matrix.cells[1:])}
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_binding_provenance_drift_across_cells_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        # The matrix contract validates metric ids only, so a drifted
        # binding identity still passes strict revalidation; the builder's
        # independent provenance check must reject it.
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _tamper_observation_cell(
            observation_matrix,
            cell_index=1,
            observation_index=0,
            binding_id="binding-9",
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    @pytest.mark.parametrize(
        "raw",
        (
            pytest.param(True, id="bool"),
            pytest.param("5", id="string"),
            pytest.param(float("nan"), id="nan"),
            pytest.param(float("inf"), id="infinity"),
            pytest.param(5.5, id="kind-mismatch-float-on-integer"),
        ),
    )
    def test_invalid_raw_values_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        raw: object,
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _tamper_observation_cell(
            observation_matrix,
            cell_index=0,
            observation_index=0,
            raw_value=raw,
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)


class TestBindingBoundary:
    def test_binding_metric_absent_from_observations_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_profile(
            profile.model_copy(update={"bindings": (_binding(metric_id="m-9"),)})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)

    def test_binding_metric_unit_mismatch_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_profile(
            profile.model_copy(update={"bindings": (_binding(metric_unit="percent"),)})
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)


class TestNumericOverflow:
    @pytest.mark.parametrize(
        "raw",
        (
            pytest.param(10**400, id="huge-positive-integer"),
            pytest.param(-(10**400), id="huge-negative-integer"),
            pytest.param(10**308, id="mean-overflow-pair"),
            pytest.param(-(10**308), id="stddev-overflow-pair"),
        ),
    )
    def test_unrepresentable_and_overflowing_integers_rejected(
        self,
        acceptance_inputs: tuple[Any, Any, Any],
        raw: object,
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _tamper_all_raw_values(observation_matrix, raw)
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)

    def test_target_violation_scale_overflow_rejected(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = _rehash_profile(
            profile.model_copy(
                update={"bindings": (_binding(target=0.0, normalization_scale=1e-300),)}
            )
        )
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(tampered, realization_matrix, observation_matrix)


class TestErrorSafety:
    def test_safe_public_message_and_internal_reason_separation(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        tampered = observation_matrix.model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as excinfo:
            _build(profile, realization_matrix, tampered)
        error = excinfo.value
        assert str(error) == (
            "Campaign 'campaign-1' failed outcome distribution matrix integrity "
            "verification and was rejected"
        )
        assert error.campaign_id == "campaign-1"
        assert error.reason == "observation matrix content hash mismatch"
        assert error.reason not in str(error)
        assert "0" * 64 not in str(error)
        assert "campaign-1" in str(error)

    def test_wrong_object_error_carries_generic_campaign_identity(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        _, realization_matrix, observation_matrix = acceptance_inputs
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as excinfo:
            _build(cast(Any, {"bad": 1}), realization_matrix, observation_matrix)
        assert excinfo.value.campaign_id == "campaign"
        assert excinfo.value.reason is not None

    def test_no_partial_artifact_and_inputs_unchanged_on_failure(
        self, acceptance_inputs: tuple[Any, Any, Any]
    ) -> None:
        profile, realization_matrix, observation_matrix = acceptance_inputs
        profile_before = profile.model_dump(mode="python")
        realization_before = realization_matrix.model_dump(mode="python")
        observation_before = observation_matrix.model_dump(mode="python")
        tampered = _tamper_all_raw_values(observation_matrix, 10**400)
        with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError):
            _build(profile, realization_matrix, tampered)
        assert profile.model_dump(mode="python") == profile_before
        assert realization_matrix.model_dump(mode="python") == realization_before
        assert observation_matrix.model_dump(mode="python") == observation_before


class TestModuleBoundaries:
    def test_errors_module_exact_surface(self) -> None:
        import kalhas.application.campaign_outcome_errors as errors

        assert errors.__all__ == ["CampaignOutcomeDistributionMatrixIntegrityError"]
        assert issubclass(errors.CampaignOutcomeDistributionMatrixIntegrityError, Exception)

    def test_builder_module_exact_all(self) -> None:
        import kalhas.application.campaign_outcome_matrix_runtime as module

        assert module.__all__ == ["build_campaign_outcome_distribution_matrix"]
        assert hasattr(module, "build_campaign_outcome_distribution_matrix")

    def test_imports_only_pure_kernel_modules(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        module_paths = _imported_module_paths(tree)
        kalhas_paths = {path for path in module_paths if path.startswith("kalhas")}
        allowed_kalhas_prefixes = (
            "kalhas.application.campaign_outcome_",
            "kalhas.application.objective_evaluation_identity",
            "kalhas.application.realization_campaign_metric_observation_runtime",
            "kalhas.application.realization_identity",
            "kalhas.application.domain_errors",
            "kalhas.application.run_planner",
            "kalhas.application.world_uncertainty_identity",
            "kalhas.contracts.v1.",
        )
        for path in kalhas_paths:
            assert path.startswith(allowed_kalhas_prefixes), path
        assert not any(
            path.startswith(("kalhas.api", "kalhas.adapters", "kalhas.domain_packs"))
            or "in_memory_store" in path
            or "query_service" in path
            for path in kalhas_paths
        ), sorted(kalhas_paths)
        modules = _imported_modules(tree)
        assert modules == {"__future__", "warnings", "pydantic", "kalhas"}
        forbidden = {
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "shutil",
            "tempfile",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "http",
            "sqlite3",
            "random",
            "uuid",
            "secrets",
            "datetime",
            "time",
            "numpy",
            "pandas",
            "decimal",
            "fractions",
            "importlib",
            "runpy",
            "ctypes",
        }
        assert not (modules & forbidden)

    def test_reuses_accepted_helpers_without_redefinition(self) -> None:
        import kalhas.application.campaign_outcome_matrix_runtime as module
        import kalhas.application.campaign_outcome_runtime as outcome_runtime
        import kalhas.application.realization_campaign_metric_observation_runtime as obs_runtime

        assert (
            module.__dict__["build_strategy_objective_outcome"]
            is outcome_runtime.build_strategy_objective_outcome
        )
        assert module.__dict__["_provenance_of"] is obs_runtime._provenance_of
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not any(name.startswith(("statistics_", "empirical_")) for name in function_names), (
            function_names
        )

    def test_no_wall_clock_randomness_or_activity_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        calls = _attribute_call_chains(tree) | _name_calls(tree)
        forbidden_calls = {
            "datetime.now",
            "datetime.utcnow",
            "datetime.today",
            "date.today",
            "time.time",
            "time.monotonic",
            "time.perf_counter",
            "time.clock",
            "time.gmtime",
            "time.localtime",
            "random.seed",
            "random.random",
            "uuid.uuid4",
            "uuid.uuid1",
        }
        assert not (calls & forbidden_calls)
        assert not any(
            "record_activity" in call or "operational_activity" in call for call in calls
        )

    def test_no_executable_expression_surface(self) -> None:
        for path in (MODULE_PATH, ERRORS_MODULE_PATH):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                assert not isinstance(node, ast.Lambda), f"lambda in {path.name}"
                if isinstance(node, ast.Call):
                    name: str | None = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    assert name not in {"exec", "eval", "compile", "__import__"}, (
                        f"executable call {name!r} in {path.name}"
                    )

    def test_no_phase_number_literals(self) -> None:
        pattern = re.compile(
            r"\bphase\s*26\b|\bphase\s*27\b|phase_26|phase_27|26\.0\.0|27\.0\.0|3\.1\.0",
            re.IGNORECASE,
        )
        for path in (MODULE_PATH, ERRORS_MODULE_PATH):
            assert not pattern.search(path.read_text(encoding="utf-8")), path.name

    def test_no_ranking_winner_preference_recommendation_surface(self) -> None:
        forbidden = re.compile(
            r"rank|winner|prefer|recommend|confidence|forecast|decision.?brief", re.IGNORECASE
        )
        symbols: list[str] = []
        for path in (MODULE_PATH, ERRORS_MODULE_PATH):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(node.name)
                    symbols.extend(argument.arg for argument in node.args.args)
        for symbol in symbols:
            assert not forbidden.search(symbol), f"forbidden symbol {symbol!r}"

    def test_public_contracts_and_schemas_stay_47(self) -> None:
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) == 47
        assert names[46] == "CampaignOutcomeDistributionMatrix"
        assert "EmpiricalDistributionSummary" not in names
        assert "StrategyObjectiveOutcome" not in names
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == 47
        file_names = {path.name for path in schema_files}
        assert "CampaignOutcomeDistributionMatrix.schema.json" in file_names

    def test_earlier_slice_files_remain_byte_identical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative, expected in _PRESERVED_FILES:
            digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            assert digest == expected, f"{relative} changed: {digest}"


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level imported module names (e.g. ``math`` from ``math.fsum``)."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _imported_module_paths(tree: ast.Module) -> set[str]:
    """Full dotted module paths of every import statement."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.add(node.module)
    return paths


def _attribute_call_chains(tree: ast.Module) -> set[str]:
    """Dotted callable chains of every call whose target is an attribute."""
    chains: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        parts: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        chains.add(".".join(reversed(parts)))
    return chains


def _name_calls(tree: ast.Module) -> set[str]:
    """Every bare-name call (``sorted(...)`` -> ``sorted``)."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    return calls
