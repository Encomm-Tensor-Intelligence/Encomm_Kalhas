"""Realization-aware run metric observation contracts (Phase 25).

Phase 25 adds the **deterministic realization-aware run metric-observation
artifact**: the immutable, tenant-scoped raw observation collection
extracted from a completely verified runtime 3.0.0
``RealizationRunTrajectoryExecution``, using only the
``DomainMetricObservationBinding`` snapshots embedded in the run's exact
compiled ``WorldVersion``. It mirrors the Phase 20 ``RunMetricObservationSet``
exactly and adds the world-realization provenance: observations are
extracted from **realized final states** (final states reached from the
realized initial state supplied by the seed's world realization), and the
set records the world realization identity and content hash together with
the renamed execution reference.

``RealizationRunMetricObservationSet`` is the complete immutable
observation collection of one runtime-3.0.0 run: the run/campaign/plan/
scenario identity, the verified world and strategy identities with their
content hashes, the recorded scenario seed identity, the world realization
identity and content hash, the realization trajectory runtime version
(exactly ``"3.0.0"``), the run input hash, the verified
``RealizationRunTrajectoryExecution`` identifier and content hash, the
exact ordered observation tuple canonicalized by ``metric_id``, the
deterministic ``content_hash`` over the complete canonical payload
excluding ``content_hash`` itself, and the deterministic ``observed_at``
taken from the authoritative trajectory execution's ``executed_at`` -
never wall-clock time. The set identifier is deterministically derived
from the stable run/runtime identity. An empty observation tuple is valid
only when the verified compiled world contains no observation binding
snapshots.

The observation values reuse the Phase 20 ``RunMetricObservationValue``
contract unchanged: one extracted raw observation with the metric
identity, the metric unit copied from the authoritative embedded
``ScenarioSpec``, the observation binding's identifier and content hash,
the manifest and state-model identity/content hashes, the observed
``state_field_id``, the authoritative numeric ``state_field_value_kind``,
the observation point (exactly ``"final_state"``), the trajectory-plan/
result identity and content hashes required to locate the authoritative
final state inside the verified execution, and the exact finite
``raw_value`` read from that final state.

These contracts are raw extraction and provenance recording only: no
aggregation, no outcomes, no distributions, no evidence, no scoring,
no rankings, no recommendations, and no decision briefs. Nothing here
loads, imports, instantiates, or executes a domain pack, and no field
type can express a callback, expression, formula, code reference,
provider, or executable mechanism.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from kalhas.contracts.v1.run_metric_observation import RunMetricObservationValue
from kalhas.contracts.v1.shared import AwareDatetime, VersionedContract

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: The realization trajectory runtime version this set describes. Kept as
#: a literal so the set can never record any other runtime version.
REALIZATION_METRIC_OBSERVATION_SET_RUNTIME_VERSION_LITERAL = "3.0.0"


class RealizationRunMetricObservationSet(VersionedContract):
    """The complete immutable raw metric-observation collection of one runtime-3.0.0 run.

    Exactly one artifact per tenant + run: the run/campaign/plan/scenario
    identity, the verified compiled world and the exact recorded strategy
    with their content hashes, the recorded seed identity, the world
    realization identity and content hash whose realized final states the
    observations were extracted from, the realization trajectory runtime
    version (exactly ``"3.0.0"``), the run input hash, the verified
    ``RealizationRunTrajectoryExecution`` identifier and content hash, the
    exact ordered observation tuple canonicalized by ``metric_id``, the
    deterministic ``content_hash`` over the complete canonical payload
    excluding ``content_hash`` itself, and the deterministic ``observed_at``
    from the authoritative execution's ``executed_at`` - never the wall
    clock. The identifier is deterministically derived from the stable
    run/runtime identity. An empty observation tuple is valid only for a
    verified compiled world with no observation binding snapshots.

    The set is raw extraction and provenance recording only: it never
    aggregates observations, calculates outcomes or distributions,
    produces evidence, scores, rankings, or recommendations, and nothing
    here loads or executes a domain pack.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: IdentifierString
    campaign_id: IdentifierString
    run_plan_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    strategy_candidate_id: IdentifierString
    strategy_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    world_realization_id: IdentifierString
    world_realization_content_hash: Sha256Hex
    runtime_version: Literal["3.0.0"]
    input_hash: Sha256Hex
    realization_run_trajectory_execution_id: IdentifierString
    realization_run_trajectory_execution_content_hash: Sha256Hex
    observations: tuple[RunMetricObservationValue, ...] = Field(default_factory=tuple)
    content_hash: Sha256Hex
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def _observations_canonicalized_by_metric_id(self) -> RealizationRunMetricObservationSet:
        """Observations must be canonicalized by metric identifier.

        The complete collection is ordered by strictly increasing
        ``metric_id`` (unique per run), so equivalent insertion orders
        can never produce different artifacts; an empty tuple satisfies
        the rule vacuously.
        """
        identifiers = [observation.metric_id for observation in self.observations]
        if any(a >= b for a, b in zip(identifiers, identifiers[1:], strict=False)):
            raise ValueError("observations must be canonicalized by metric_id")
        return self
