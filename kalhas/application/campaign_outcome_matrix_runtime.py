"""Pure deterministic campaign outcome-distribution matrix builder (KALHAS).

Builds the immutable ``CampaignOutcomeDistributionMatrix`` of one
completed runtime-3.0.0 campaign from **three already-authoritative
source artifacts only**: the exact ``ScenarioEvaluationProfile``, the
verified ``CampaignWorldRealizationMatrix``, and the verified
``RealizationCampaignMetricObservationMatrix``. The module never loads
the store, never calls LEGION or NEXUS, never uses wall-clock time,
randomness, network, providers, filesystem, or domain packs, and never
mutates any input. It performs no execution, replay, transition
evaluation, observation extraction, ranking, scoring, comparison,
preference, confidence, forecast, recommendation, or decision-brief
production of any kind: it only revalidates the three supplied
artifacts, verifies their independent identities, content hashes, and
cross-source consistency, verifies the observation matrix structurally,
and aggregates the exact per-strategy/per-objective outcome evidence
through the accepted pure outcome builder.

The builder verifies, in order:

- the three supplied artifacts are real instances of their declared
  contract types (wrong-object inputs raise the safe typed integrity
  error; no arbitrary attribute of a wrong object is ever accessed);
- the observation matrix records exactly the runtime 3.0.0 version
  (anything else raises the established ``UnsupportedRuntimeVersionError``
  with operation ``"campaign outcome distribution matrix"``);
- the strict trust boundary: every supplied artifact is revalidated
  against its complete contract through serializer-based
  ``model_dump(mode="python")`` + ``model_validate(..., strict=True)``
  with the established Pydantic serializer-warnings suppression; the
  revalidation result is discarded and the supplied artifacts are never
  replaced, normalized, repaired, or mutated;
- the evaluation-profile deterministic identifier (recomputed from the
  canonical tenant/scenario/scenario-hash identity) and its recomputed
  content hash;
- the world-realization matrix deterministic identifier (recomputed
  from the canonical campaign/world/model/sampler identity) and its
  recomputed content hash, plus - for every nested realization - the
  tenant ownership, the independently recomputed deterministic
  realization identifier, and the recomputed realization content hash;
- the observation-matrix deterministic identifier (recomputed from the
  canonical campaign/world/runtime identity) and its recomputed content
  hash;
- exact cross-source agreement: tenant, scenario, campaign, world
  identity/hash, ordered seed ensemble, timestamp lineage
  (``assembled_at``), comparison mode, and the seed-aligned
  world-realization identity/hash tuples;
- the observation matrix's structural shape independently of its
  contract: complete strategy x seed cell count, contiguous sequence
  positions, exact strategy-major/seed-minor positions and identities,
  seed-aligned realization identity/hash agreement, the exact ordered
  metric collection per cell, identical immutable binding provenance
  for the same metric across every cell (reusing the accepted
  ``_provenance_of`` helper), and every raw value matching its
  authoritative numeric kind - no bool, non-finite, malformed, or
  kind-confused value reaches arithmetic;
- the evaluation-profile binding boundary: bindings remain in exact
  profile order and are never sorted, objective identifiers are unique,
  every bound metric exists in the observation matrix, and every
  binding's metric unit equals the authoritative observation unit;
- per strategy (exact ordered strategy order) and per binding (exact
  profile order), the exact ordered raw metric values across the exact
  ordered seed ensemble are passed unchanged to the accepted
  ``build_strategy_objective_outcome`` builder - no statistical,
  quantile, tail, target-violation, or adverse-tail algorithm is
  duplicated here.

The output matrix carries the deterministic identifier (from the
campaign/world/runtime/profile/source-matrix identity), the
observation-matrix tenant/campaign/scenario/world/runtime identity, the
profile scenario hash and evaluation-profile reference, the optional
uncertainty reference, both source references with their content
hashes, the exact ordered strategies/seeds/metrics from the observation
matrix and objectives from the profile binding order, the complete
strategy-major/objective-minor outcome tuple, ``derived_at`` equal to
the observation matrix ``assembled_at`` - never the wall clock - and
the recomputed self-covering content hash. Equivalent inputs always
produce exactly equal models and exactly equal serialized payloads.

Failure semantics: an unsupported recorded runtime passes through as
``UnsupportedRuntimeVersionError``; the typed integrity error passes
through unchanged; every ``ValidationError``, ``ValueError``,
``TypeError``, ``AttributeError``, ``IndexError``, ``ArithmeticError``,
and ``OverflowError`` arising inside the verification or construction
boundary becomes the safe typed integrity error - never a partial
outcome, never a partial matrix, and never an exposed underlying
exception text.
"""

from __future__ import annotations

import warnings

from pydantic import BaseModel, ValidationError

from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
    campaign_outcome_distribution_matrix_identifier,
)
from kalhas.application.campaign_outcome_runtime import build_strategy_objective_outcome
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
)
from kalhas.application.realization_campaign_metric_observation_runtime import (
    _provenance_of,
)
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_content_hash,
    realization_metric_observation_matrix_identifier,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.world_uncertainty_identity import (
    campaign_realization_matrix_content_hash,
    campaign_realization_matrix_identifier,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.run_metric_observation import raw_value_matches_numeric_kind
from kalhas.contracts.v1.world_realization import CampaignWorldRealizationMatrix

_PLACEHOLDER_HASH = "0" * 64


def _reject(campaign_id: str, reason: str) -> CampaignOutcomeDistributionMatrixIntegrityError:
    """A generic, safe outcome-matrix integrity error with an internal diagnostic reason."""
    return CampaignOutcomeDistributionMatrixIntegrityError(campaign_id, reason)


def _strict_revalidate[ContractT: BaseModel](
    campaign_id: str,
    artifact: object,
    model_type: type[ContractT],
    reason: str,
) -> None:
    """Strictly revalidate one supplied artifact against its complete contract.

    Serializer-based strict revalidation (the established repository
    trust-boundary pattern): the artifact's Python payload is re-derived
    and the contract is re-validated with ``strict=True``, so a
    validator-bypassed instance (wrong-typed or non-finite raw values,
    booleans where integers belong, invalid literals or hash patterns,
    malformed positions or ordering) is rejected before any field of it
    is trusted. Wrong object types and serializer/type failures are
    rejected as well. The revalidation result is discarded; the supplied
    artifact is never normalized, repaired, or replaced.
    """
    if not isinstance(artifact, model_type):
        raise _reject(campaign_id, reason)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _reject(campaign_id, reason) from None


def _verify_inputs(
    *,
    profile: ScenarioEvaluationProfile,
    world_realization_matrix: CampaignWorldRealizationMatrix,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> None:
    """Fully verify the three supplied source artifacts before any aggregation.

    Runs after the type boundary and the runtime gate, before any
    outcome construction: strict contract revalidation of all three
    artifacts, independent identity/content-hash verification of the
    profile, the world-realization matrix (with every nested
    realization), and the observation matrix, exact cross-source
    consistency, the independent structural verification of the
    observation matrix, and the evaluation-profile binding boundary.
    Any failure raises the safe typed integrity error; nothing here
    mutates an input.
    """
    campaign_id = observation_matrix.campaign_id
    _strict_revalidate(
        campaign_id,
        profile,
        ScenarioEvaluationProfile,
        "evaluation profile violates its contract",
    )
    _strict_revalidate(
        campaign_id,
        world_realization_matrix,
        CampaignWorldRealizationMatrix,
        "world realization matrix violates its contract",
    )
    _strict_revalidate(
        campaign_id,
        observation_matrix,
        RealizationCampaignMetricObservationMatrix,
        "observation matrix violates its contract",
    )

    # Evaluation profile: independent deterministic identifier and
    # recomputed content hash.
    if profile.identifier != evaluation_profile_identifier(
        tenant_id=profile.tenant_id,
        scenario_id=profile.scenario_id,
        scenario_content_hash_value=profile.scenario_content_hash,
    ):
        raise _reject(campaign_id, "evaluation profile identifier mismatch")
    if profile.content_hash != evaluation_profile_content_hash(profile):
        raise _reject(campaign_id, "evaluation profile content hash mismatch")

    # World-realization matrix: independent deterministic identifier and
    # recomputed content hash from its own recorded identity.
    if world_realization_matrix.identifier != campaign_realization_matrix_identifier(
        campaign_id=world_realization_matrix.campaign_id,
        world_version_id=world_realization_matrix.world_version_id,
        world_content_hash=world_realization_matrix.world_content_hash,
        uncertainty_model_id=world_realization_matrix.uncertainty_model_id,
        uncertainty_model_content_hash_value=(
            world_realization_matrix.uncertainty_model_content_hash
        ),
        sampler_version=world_realization_matrix.sampler_version,
        quantization_policy=world_realization_matrix.quantization_policy,
        quantization_fraction_bits=world_realization_matrix.quantization_fraction_bits,
    ):
        raise _reject(campaign_id, "world realization matrix identifier mismatch")
    if world_realization_matrix.content_hash != campaign_realization_matrix_content_hash(
        world_realization_matrix
    ):
        raise _reject(campaign_id, "world realization matrix content hash mismatch")

    # Every nested realization: tenant ownership, independent
    # deterministic identifier, and recomputed content hash.
    for realization in world_realization_matrix.realizations:
        if realization.tenant_id != world_realization_matrix.tenant_id:
            raise _reject(campaign_id, "realization tenant mismatch")
        if realization.identifier != world_realization_identifier(
            world_version_id=realization.world_version_id,
            world_content_hash=realization.world_content_hash,
            scenario_seed_id=realization.scenario_seed_id,
            seed_content_hash_value=realization.seed_content_hash,
            uncertainty_model_id=realization.uncertainty_model_id,
            uncertainty_model_content_hash_value=(realization.uncertainty_model_content_hash),
            sampler_version=realization.sampler_version,
            quantization_policy=realization.quantization_policy,
            quantization_fraction_bits=realization.quantization_fraction_bits,
        ):
            raise _reject(campaign_id, "realization identifier mismatch")
        if realization.content_hash != world_realization_content_hash(realization):
            raise _reject(campaign_id, "realization content hash mismatch")

    # Observation matrix: independent deterministic identifier and
    # recomputed content hash.
    if observation_matrix.identifier != realization_metric_observation_matrix_identifier(
        campaign_id=observation_matrix.campaign_id,
        world_version_id=observation_matrix.world_version_id,
        runtime_version=observation_matrix.runtime_version,
    ):
        raise _reject(campaign_id, "observation matrix identifier mismatch")
    if observation_matrix.content_hash != realization_metric_observation_matrix_content_hash(
        observation_matrix
    ):
        raise _reject(campaign_id, "observation matrix content hash mismatch")

    # Cross-source consistency: exact agreement, never sorted or repaired.
    if (
        profile.tenant_id != world_realization_matrix.tenant_id
        or profile.tenant_id != observation_matrix.tenant_id
    ):
        raise _reject(campaign_id, "outcome matrix tenant mismatch")
    if (
        profile.scenario_id != world_realization_matrix.scenario_id
        or profile.scenario_id != observation_matrix.scenario_id
    ):
        raise _reject(campaign_id, "outcome matrix scenario mismatch")
    if world_realization_matrix.campaign_id != observation_matrix.campaign_id:
        raise _reject(campaign_id, "outcome matrix campaign mismatch")
    if world_realization_matrix.world_version_id != observation_matrix.world_version_id:
        raise _reject(campaign_id, "outcome matrix world version mismatch")
    if world_realization_matrix.world_content_hash != observation_matrix.world_content_hash:
        raise _reject(campaign_id, "outcome matrix world content hash mismatch")
    if (
        world_realization_matrix.ordered_scenario_seed_ids
        != observation_matrix.ordered_scenario_seed_ids
    ):
        raise _reject(campaign_id, "outcome matrix seed order mismatch")
    if world_realization_matrix.assembled_at != observation_matrix.assembled_at:
        raise _reject(campaign_id, "outcome matrix timestamp lineage mismatch")
    if observation_matrix.comparison_mode != "identical_conditions":
        raise _reject(campaign_id, "observation matrix comparison mode mismatch")

    realization_ids = [
        realization.identifier for realization in world_realization_matrix.realizations
    ]
    realization_hashes = [
        realization.content_hash for realization in world_realization_matrix.realizations
    ]
    if list(observation_matrix.ordered_world_realization_ids) != realization_ids:
        raise _reject(campaign_id, "observation realization identity tuple mismatch")
    if list(observation_matrix.ordered_world_realization_content_hashes) != realization_hashes:
        raise _reject(campaign_id, "observation realization content hash tuple mismatch")

    # Independent observation-matrix structural verification.
    strategies = observation_matrix.ordered_strategy_candidate_ids
    seeds = observation_matrix.ordered_scenario_seed_ids
    metrics = observation_matrix.ordered_metric_ids
    seed_count = len(seeds)
    expected_cells = len(strategies) * seed_count
    if len(observation_matrix.cells) != expected_cells:
        raise _reject(campaign_id, "observation matrix cell count mismatch")
    for position, cell in enumerate(observation_matrix.cells):
        if cell.sequence_position != position:
            raise _reject(campaign_id, "observation matrix cell sequence mismatch")
        if cell.strategy_position != position // seed_count:
            raise _reject(campaign_id, "observation matrix cell strategy position mismatch")
        if cell.seed_position != position % seed_count:
            raise _reject(campaign_id, "observation matrix cell seed position mismatch")
        if cell.strategy_candidate_id != strategies[cell.strategy_position]:
            raise _reject(campaign_id, "observation matrix cell strategy identity mismatch")
        if cell.scenario_seed_id != seeds[cell.seed_position]:
            raise _reject(campaign_id, "observation matrix cell seed identity mismatch")
        if (
            cell.world_realization_id
            != observation_matrix.ordered_world_realization_ids[cell.seed_position]
        ):
            raise _reject(campaign_id, "observation matrix cell realization identity mismatch")
        if (
            cell.world_realization_content_hash
            != observation_matrix.ordered_world_realization_content_hashes[cell.seed_position]
        ):
            raise _reject(
                campaign_id,
                "observation matrix cell realization content hash mismatch",
            )
        if [observation.metric_id for observation in cell.observations] != list(metrics):
            raise _reject(campaign_id, "observation matrix cell metric collection mismatch")

    if not metrics:
        raise _reject(campaign_id, "outcome matrix requires at least one observed metric")

    # Binding provenance and raw-value kind verification.
    for metric_position in range(len(metrics)):
        reference = observation_matrix.cells[0].observations[metric_position]
        for cell in observation_matrix.cells:
            observation = cell.observations[metric_position]
            if _provenance_of(observation) != _provenance_of(reference):
                raise _reject(campaign_id, "observation binding provenance mismatch across cells")
            if not raw_value_matches_numeric_kind(
                observation.raw_value, observation.state_field_value_kind
            ):
                raise _reject(
                    campaign_id, "observed raw value is not an exact finite numeric value"
                )

    # Evaluation-profile binding boundary.
    objective_ids = [binding.objective_id for binding in profile.bindings]
    if len(objective_ids) != len(set(objective_ids)):
        raise _reject(campaign_id, "evaluation profile objective identifiers are not unique")
    authoritative_units = {
        metric_id: observation_matrix.cells[0].observations[metric_position].metric_unit
        for metric_position, metric_id in enumerate(metrics)
    }
    for binding in profile.bindings:
        if binding.metric_id not in metrics:
            raise _reject(
                campaign_id, "evaluation binding metric has no observations in the campaign"
            )
        if binding.metric_unit != authoritative_units[binding.metric_id]:
            raise _reject(campaign_id, "evaluation binding metric unit mismatch")


def _construct_matrix(
    *,
    profile: ScenarioEvaluationProfile,
    world_realization_matrix: CampaignWorldRealizationMatrix,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> CampaignOutcomeDistributionMatrix:
    """Construct and fully hash the matrix from completely verified inputs.

    Called exactly once, only after every input passed the trust-boundary
    verification. Aggregates the exact ordered raw metric values per
    strategy x binding through the accepted pure outcome builder - never
    reordering, coercing, rounding, normalizing, or mutating the raw
    values - and computes the self-covering content hash over the
    complete canonical payload excluding ``content_hash`` itself.
    """
    strategies = observation_matrix.ordered_strategy_candidate_ids
    seeds = observation_matrix.ordered_scenario_seed_ids
    metrics = observation_matrix.ordered_metric_ids
    seed_count = len(seeds)
    metric_positions = {metric_id: position for position, metric_id in enumerate(metrics)}
    objective_ids = [binding.objective_id for binding in profile.bindings]
    objective_count = len(objective_ids)

    outcomes = []
    for strategy_position, strategy_id in enumerate(strategies):
        for objective_position, binding in enumerate(profile.bindings):
            metric_position = metric_positions[binding.metric_id]
            values = tuple(
                observation_matrix.cells[strategy_position * seed_count + seed_position]
                .observations[metric_position]
                .raw_value
                for seed_position in range(seed_count)
            )
            outcomes.append(
                build_strategy_objective_outcome(
                    sequence_position=(strategy_position * objective_count + objective_position),
                    strategy_position=strategy_position,
                    objective_position=objective_position,
                    strategy_candidate_id=strategy_id,
                    binding=binding,
                    ordered_observed_values=values,
                )
            )

    matrix = CampaignOutcomeDistributionMatrix(
        identifier=campaign_outcome_distribution_matrix_identifier(
            campaign_id=observation_matrix.campaign_id,
            world_version_id=observation_matrix.world_version_id,
            runtime_version=observation_matrix.runtime_version,
            evaluation_profile_id=profile.identifier,
            source_world_realization_matrix_id=world_realization_matrix.identifier,
            source_metric_observation_matrix_id=observation_matrix.identifier,
        ),
        tenant_id=observation_matrix.tenant_id,
        campaign_id=observation_matrix.campaign_id,
        scenario_id=observation_matrix.scenario_id,
        scenario_content_hash=profile.scenario_content_hash,
        world_version_id=observation_matrix.world_version_id,
        world_content_hash=observation_matrix.world_content_hash,
        runtime_version=observation_matrix.runtime_version,
        comparison_mode="identical_conditions",
        evaluation_profile_id=profile.identifier,
        evaluation_profile_content_hash=profile.content_hash,
        uncertainty_model_id=world_realization_matrix.uncertainty_model_id,
        uncertainty_model_content_hash=world_realization_matrix.uncertainty_model_content_hash,
        source_world_realization_matrix_id=world_realization_matrix.identifier,
        source_world_realization_matrix_content_hash=world_realization_matrix.content_hash,
        source_metric_observation_matrix_id=observation_matrix.identifier,
        source_metric_observation_matrix_content_hash=observation_matrix.content_hash,
        ordered_strategy_candidate_ids=strategies,
        ordered_scenario_seed_ids=seeds,
        ordered_objective_ids=tuple(objective_ids),
        ordered_metric_ids=metrics,
        outcomes=tuple(outcomes),
        content_hash=_PLACEHOLDER_HASH,
        derived_at=observation_matrix.assembled_at,
    )
    return matrix.model_copy(
        update={"content_hash": campaign_outcome_distribution_matrix_content_hash(matrix)}
    )


def build_campaign_outcome_distribution_matrix(
    *,
    profile: ScenarioEvaluationProfile,
    world_realization_matrix: CampaignWorldRealizationMatrix,
    observation_matrix: RealizationCampaignMetricObservationMatrix,
) -> CampaignOutcomeDistributionMatrix:
    """Build and fully hash the deterministic campaign outcome-distribution matrix.

    Consumes only the three supplied artifacts - no store, no campaign
    object - and returns one fully identified, fully content-hashed
    matrix or raises without returning a partial artifact. Wrong-object
    inputs raise the safe typed integrity error; a recorded observation
    runtime other than exactly 3.0.0 raises
    :class:`UnsupportedRuntimeVersionError` (operation ``"campaign
    outcome distribution matrix"``). Every artifact is then strictly
    revalidated and independently identity/hash-verified, cross-source
    consistency and the observation-matrix structure are verified, and
    the exact per-strategy/per-objective outcomes are aggregated in the
    exact strategy-major, objective-minor order through the accepted
    pure outcome builder; ``derived_at`` is the observation matrix
    ``assembled_at`` - never the wall clock. Nothing here mutates any
    input, accesses the store, or performs execution, replay,
    extraction, ranking, scoring, comparison, or recommendation; any
    construction-time validation/index/attribute/arithmetic failure
    converts to the typed integrity error.
    """
    if not isinstance(profile, ScenarioEvaluationProfile):
        raise _reject("campaign", "outcome matrix profile is not an evaluation profile")
    if not isinstance(world_realization_matrix, CampaignWorldRealizationMatrix):
        raise _reject("campaign", "outcome matrix source is not a world realization matrix")
    if not isinstance(observation_matrix, RealizationCampaignMetricObservationMatrix):
        raise _reject(
            "campaign", "outcome matrix source is not a campaign metric observation matrix"
        )
    # The recorded runtime is read after the type boundary so the
    # established unsupported-runtime typing is preserved: an
    # observation matrix recording anything other than exactly 3.0.0
    # raises the typed UnsupportedRuntimeVersionError before any
    # revalidation or field trust.
    if observation_matrix.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            observation_matrix.runtime_version,
            operation="campaign outcome distribution matrix",
        )
    campaign_id = observation_matrix.campaign_id
    try:
        _verify_inputs(
            profile=profile,
            world_realization_matrix=world_realization_matrix,
            observation_matrix=observation_matrix,
        )
        return _construct_matrix(
            profile=profile,
            world_realization_matrix=world_realization_matrix,
            observation_matrix=observation_matrix,
        )
    except CampaignOutcomeDistributionMatrixIntegrityError:
        raise
    except (
        ValidationError,
        ValueError,
        TypeError,
        AttributeError,
        IndexError,
        ArithmeticError,
        OverflowError,
    ) as exc:
        raise _reject(campaign_id, "internally built outcome matrix violates its contract") from exc


__all__ = ["build_campaign_outcome_distribution_matrix"]
