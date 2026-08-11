"""Pure deterministic campaign objective-evaluation matrix builder (Phase 23).

Builds the immutable ``CampaignObjectiveEvaluationMatrix`` of one
completed runtime-2.0.0 campaign from **already verified authoritative
records only**: the exact ``ScenarioEvaluationProfile`` embedded in the
campaign's compiled world and the completely verified Phase 21
``CampaignMetricObservationMatrix``. The module never loads the store,
never calls LEGION or NEXUS, never uses wall-clock time, randomness,
network, providers, filesystem, or domain packs, and never mutates any
input. It performs no execution, replay, extraction, aggregation,
sampling, probability, ranking, dominance, regret, evidence, or
recommendation of any kind - it only verifies identities and binding
provenance, evaluates each exact raw value against its objective, and
hashes the immutable matrix.

The builder verifies every source artifact identity and content hash it
directly consumes: the observation matrix identifier and content hash
are re-derived and compared, the profile identifier and content hash
are re-derived and compared, the runtime version must be exactly 2.0.0,
the tenant and scenario identities must agree, every bound metric must
exist in the observation matrix, and every cell must resolve exactly
one observation per bound metric. Missing, duplicate, reordered,
inconsistent, foreign, or tampered inputs are rejected with safe typed
integrity errors - nothing is ever repaired, clamped, rounded,
coerced, or partially returned.

Evaluation semantics (one direction-aware orientation; positive means
adverse relative to the target or tolerance boundary, zero means
exactly on the boundary, negative means acceptable):

- ``minimize``: ``signed_target_delta = value - target``
- ``maximize``: ``signed_target_delta = target - value``
- ``reach``: ``signed_target_delta = abs(value - target) - reach_tolerance``

For targeted objectives ``target_achieved`` is ``signed_target_delta
<= 0`` and the normalized target violation is ``max(0,
signed_target_delta) / normalization_scale`` - exactly the blueprint
definitions. When no target exists for a minimize/maximize objective
all three evaluation fields are ``None``; no target is ever invented.
Any arithmetic overflow or non-finite derived value rejects the
complete matrix with a typed integrity error - the exact raw integers
stay integers and raw floats stay floats, and derived values are
computed with the same expressions the contract enforces.

The matrix ordering is strategy-major, seed-minor, objective-minor
with contiguous sequence positions and exact identity-vs-position
agreement; ``evaluated_at`` is the authoritative Phase 21 matrix
``assembled_at`` - never the wall clock; the matrix identifier is
independently derived from the canonical campaign/world/runtime/source/
profile identity, never from the content hash.
"""

from __future__ import annotations

import math
import warnings

from pydantic import ValidationError

from kalhas.application.campaign_metric_observation_runtime import (
    campaign_metric_observation_matrix_content_hash,
    campaign_metric_observation_matrix_identifier,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.objective_evaluation_errors import (
    CampaignObjectiveEvaluationMatrixIntegrityError,
)
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
)
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ObjectiveMetricBinding,
    ObjectiveObservationEvaluation,
    ScenarioEvaluationProfile,
    _is_exact_finite_numeric,
    evaluate_target_delta,
)
from kalhas.contracts.v1.run_metric_observation import raw_value_matches_numeric_kind

_MATRIX_ID_PREFIX = "objective-evaluation-matrix-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def campaign_objective_evaluation_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
    source_metric_observation_matrix_id: str,
    evaluation_profile_id: str,
) -> str:
    """Deterministic matrix identifier from the canonical identity payload.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    runtime_version, source_metric_observation_matrix_id,
    evaluation_profile_id)`` identity with a readable, distinct prefix;
    deliberately **not** derived from the matrix content hash, which
    would be circular because the content hash covers the identifier
    itself. Identical identity inputs always yield the same identifier.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
            "source_metric_observation_matrix_id": source_metric_observation_matrix_id,
            "evaluation_profile_id": evaluation_profile_id,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_objective_evaluation_matrix_content_hash(
    matrix: CampaignObjectiveEvaluationMatrix,
) -> str:
    """Canonical SHA-256 of the complete matrix content, excluding content_hash."""
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(campaign_id: str, reason: str) -> CampaignObjectiveEvaluationMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return CampaignObjectiveEvaluationMatrixIntegrityError(campaign_id, reason)


def _verify_binding_numerics(
    campaign_id: str,
    binding: ObjectiveMetricBinding,
) -> None:
    """Reject non-exact-finite numeric snapshot values on a binding.

    Defense in depth: the profile contract validators normally
    guarantee exact finite numerics, but a validator-bypassed binding
    (bool, NaN, Infinity, or non-numeric values) must never reach the
    evaluation arithmetic, where booleans would silently compute as
    integers.
    """
    for field_name, value in (
        ("target", binding.target),
        ("weight", binding.weight),
        ("reach_tolerance", binding.reach_tolerance),
        ("normalization_scale", binding.normalization_scale),
    ):
        if value is None:
            continue
        if not _is_exact_finite_numeric(value):
            raise _reject(
                campaign_id, f"evaluation binding {field_name} is not exact finite numeric"
            )
    if binding.normalization_scale <= 0.0:
        raise _reject(
            campaign_id, "evaluation binding normalization scale is not strictly positive"
        )


def _evaluate_binding(
    campaign_id: str,
    binding: ObjectiveMetricBinding,
    raw_value: int | float,
) -> tuple[bool | None, float | None, float | None]:
    """Evaluate one exact raw value against one objective binding.

    Returns ``(target_achieved, signed_target_delta,
    normalized_target_violation)``; all three are ``None`` exactly when
    no target exists. The signed delta is direction-aware (positive =
    adverse, zero = boundary, negative = acceptable) and the violation
    is ``max(0, delta) / normalization_scale``. Any arithmetic overflow
    or non-finite derived value rejects the complete matrix.
    """
    target = binding.target
    if target is None:
        return None, None, None
    direction = binding.direction
    try:
        tolerance = binding.reach_tolerance
        delta = evaluate_target_delta(
            direction=direction,
            raw_value=raw_value,
            target=target,
            reach_tolerance=tolerance,
        )
        if delta is None:
            raise _reject(campaign_id, "evaluation calculation failed")
        violation = max(0.0, delta) / binding.normalization_scale
    except (OverflowError, ArithmeticError, ValueError):
        raise _reject(campaign_id, "evaluation calculation overflow") from None
    if not math.isfinite(delta) or not math.isfinite(violation):
        raise _reject(campaign_id, "evaluation calculation produced a non-finite value")
    return delta <= 0.0, delta, violation


def build_campaign_objective_evaluation_matrix(
    *,
    profile: ScenarioEvaluationProfile,
    observation_matrix: CampaignMetricObservationMatrix,
) -> CampaignObjectiveEvaluationMatrix:
    """Build and fully hash the deterministic campaign objective-evaluation matrix.

    Both inputs are strictly revalidated against their contracts before
    any field is indexed or any arithmetic runs: a validator-bypassed
    profile or source matrix (malformed positions, reordered cells,
    invalid nested observations, invalid direction/tolerance values) is
    rejected with the typed integrity error - never an ``IndexError``,
    ``TypeError``, or untyped exception - and no input is ever mutated.

    Requires the trajectory runtime version (the source matrix must
    record exactly 2.0.0; legacy and unsupported versions raise
    :class:`UnsupportedRuntimeVersionError`), identical tenant
    ownership, exact campaign/scenario/world identity agreement, and
    exact re-derived source artifact identifiers and content hashes.
    Every bound metric must exist in the observation matrix and every
    cell must resolve exactly one observation per bound metric, with
    the observation's metric unit exactly equal to the binding's
    authoritative unit. The complete strategy x seed x objective
    evaluation is built in the exact strategy-major, seed-minor,
    objective-minor order with objectives in the exact profile
    (``ScenarioSpec``) order; ``evaluated_at`` is the authoritative
    Phase 21 matrix ``assembled_at`` - never the wall clock. Nothing
    here mutates any input, accesses the store, or performs execution,
    replay, extraction, aggregation, sampling, ranking, or outcome
    production.
    """
    try:
        campaign_id = observation_matrix.campaign_id
        runtime_version = observation_matrix.runtime_version
    except (AttributeError, TypeError):
        raise _reject(
            "campaign",
            "evaluation source is not a campaign metric observation matrix",
        ) from None
    # The recorded runtime is read before revalidation so the
    # established legacy/unsupported-runtime typing is preserved: a
    # source matrix recording anything other than exactly 2.0.0 raises
    # the typed UnsupportedRuntimeVersionError (409 conflict) exactly
    # as the upstream verified queries do.
    if runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            runtime_version, operation="objective evaluation matrix"
        )
    # Strict complete contract revalidation: a validator-bypassed or
    # otherwise malformed profile or source matrix is rejected before
    # any field of it is indexed or any arithmetic runs.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            profile = ScenarioEvaluationProfile.model_validate(
                profile.model_dump(mode="python"), strict=True
            )
            observation_matrix = CampaignMetricObservationMatrix.model_validate(
                observation_matrix.model_dump(mode="python"), strict=True
            )
    except (ValidationError, TypeError, AttributeError, ValueError):
        raise _reject(campaign_id, "evaluation inputs violate their contracts") from None
    try:
        if profile.tenant_id != observation_matrix.tenant_id:
            raise _reject(campaign_id, "evaluation profile tenant mismatch")
        if profile.scenario_id != observation_matrix.scenario_id:
            raise _reject(campaign_id, "evaluation profile scenario mismatch")
        if observation_matrix.identifier != campaign_metric_observation_matrix_identifier(
            campaign_id=observation_matrix.campaign_id,
            world_version_id=observation_matrix.world_version_id,
            runtime_version=observation_matrix.runtime_version,
        ):
            raise _reject(campaign_id, "source observation matrix identifier mismatch")
        if observation_matrix.content_hash != campaign_metric_observation_matrix_content_hash(
            observation_matrix
        ):
            raise _reject(campaign_id, "source observation matrix content hash mismatch")
        if profile.identifier != evaluation_profile_identifier(
            tenant_id=profile.tenant_id,
            scenario_id=profile.scenario_id,
            scenario_content_hash_value=profile.scenario_content_hash,
        ):
            raise _reject(campaign_id, "evaluation profile identifier mismatch")
        if profile.content_hash != evaluation_profile_content_hash(profile):
            raise _reject(campaign_id, "evaluation profile content hash mismatch")

        bound_metric_ids = {binding.metric_id for binding in profile.bindings}
        matrix_metric_ids = list(observation_matrix.ordered_metric_ids)
        missing = sorted(bound_metric_ids - set(matrix_metric_ids))
        if missing:
            raise _reject(campaign_id, "evaluation metric has no observations in the campaign")

        strategy_ids = list(observation_matrix.ordered_strategy_candidate_ids)
        seed_ids = list(observation_matrix.ordered_scenario_seed_ids)
        objective_ids = [binding.objective_id for binding in profile.bindings]
        objective_count = len(objective_ids)
        seed_count = len(seed_ids)

        cells: list[ObjectiveObservationEvaluation] = []
        for cell in observation_matrix.cells:
            if cell.strategy_candidate_id != strategy_ids[cell.strategy_position]:
                raise _reject(campaign_id, "cell strategy identity mismatch")
            if cell.scenario_seed_id != seed_ids[cell.seed_position]:
                raise _reject(campaign_id, "cell seed identity mismatch")
            for objective_position, binding in enumerate(profile.bindings):
                _verify_binding_numerics(campaign_id, binding)
                matches = [
                    observation
                    for observation in cell.observations
                    if observation.metric_id == binding.metric_id
                ]
                if len(matches) != 1:
                    raise _reject(
                        campaign_id,
                        "evaluation metric observations are missing or duplicated "
                        "in a campaign cell",
                    )
                observation = matches[0]
                if observation.metric_unit != binding.metric_unit:
                    raise _reject(campaign_id, "evaluation metric unit mismatch")
                if not raw_value_matches_numeric_kind(
                    observation.raw_value, observation.state_field_value_kind
                ):
                    raise _reject(campaign_id, "evaluation raw value is not exact finite numeric")
                achieved, delta, violation = _evaluate_binding(
                    campaign_id, binding, observation.raw_value
                )
                sequence_position = (
                    cell.strategy_position * seed_count + cell.seed_position
                ) * objective_count + objective_position
                cells.append(
                    ObjectiveObservationEvaluation(
                        sequence_position=sequence_position,
                        strategy_position=cell.strategy_position,
                        seed_position=cell.seed_position,
                        objective_position=objective_position,
                        strategy_candidate_id=cell.strategy_candidate_id,
                        scenario_seed_id=cell.scenario_seed_id,
                        objective_id=binding.objective_id,
                        metric_id=binding.metric_id,
                        metric_unit=binding.metric_unit,
                        run_id=cell.run_id,
                        input_hash=cell.input_hash,
                        raw_value=observation.raw_value,
                        direction=binding.direction,
                        target=binding.target,
                        weight=binding.weight,
                        reach_tolerance=binding.reach_tolerance,
                        normalization_scale=binding.normalization_scale,
                        target_achieved=achieved,
                        signed_target_delta=delta,
                        normalized_target_violation=violation,
                    )
                )

        matrix = CampaignObjectiveEvaluationMatrix(
            identifier=campaign_objective_evaluation_matrix_identifier(
                campaign_id=campaign_id,
                world_version_id=observation_matrix.world_version_id,
                runtime_version=TRAJECTORY_RUNTIME_VERSION,
                source_metric_observation_matrix_id=observation_matrix.identifier,
                evaluation_profile_id=profile.identifier,
            ),
            tenant_id=observation_matrix.tenant_id,
            campaign_id=campaign_id,
            scenario_id=observation_matrix.scenario_id,
            world_version_id=observation_matrix.world_version_id,
            world_content_hash=observation_matrix.world_content_hash,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
            source_metric_observation_matrix_id=observation_matrix.identifier,
            source_metric_observation_matrix_content_hash=observation_matrix.content_hash,
            evaluation_profile_id=profile.identifier,
            evaluation_profile_content_hash=profile.content_hash,
            scenario_content_hash=profile.scenario_content_hash,
            ordered_strategy_candidate_ids=observation_matrix.ordered_strategy_candidate_ids,
            ordered_scenario_seed_ids=observation_matrix.ordered_scenario_seed_ids,
            ordered_objective_ids=tuple(objective_ids),
            cells=tuple(cells),
            content_hash=_PLACEHOLDER_HASH,
            evaluated_at=observation_matrix.assembled_at,
        )
        return matrix.model_copy(
            update={"content_hash": campaign_objective_evaluation_matrix_content_hash(matrix)}
        )
    except (
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        ArithmeticError,
        OverflowError,
        ZeroDivisionError,
    ):
        raise _reject(campaign_id, "evaluation derivation failed") from None
