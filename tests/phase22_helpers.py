"""Shared helpers for Phase 22 campaign metric-statistics tests.

Builds a COMPLETE runtime-2.0.0 campaign with fully extracted and
verified Phase 20 ``RunMetricObservationSet`` artifacts through the real
Phase 21 helper, then obtains its completely verified Phase 21
``CampaignMetricObservationMatrix`` through the real verified query
service - the exact authoritative input the Phase 22 builder consumes.

Also provides self-consistent tampering helpers: a ``model_copy``-based
tamper whose content hash is recomputed over the tampered content, so a
builder-level test reaches exactly the check under test instead of
failing on the source-matrix hash check. Tampering never mutates the
store or the original matrix.
"""

from __future__ import annotations

import warnings

from kalhas.application.campaign_metric_observation_query_service import (
    get_verified_campaign_metric_observation_matrix,
)
from kalhas.application.campaign_metric_observation_runtime import (
    campaign_metric_observation_matrix_content_hash,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.campaign_metric_observation import (
    CampaignMetricObservationCell,
    CampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationValue
from kalhas.contracts.v1.scenario import ScenarioSeed

from tests.phase4_helpers import TENANT, build_seed
from tests.phase21_helpers import complete_observation_campaign


def verified_observation_campaign(
    *,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
    with_bindings: bool = True,
) -> tuple[InMemoryScenarioStore, CampaignMetricObservationMatrix, tuple[str, ...]]:
    """A COMPLETE 2.0.0 campaign and its completely verified Phase 21 matrix.

    Returns ``(store, observation_matrix, run_ids)`` where the matrix is
    obtained through the real verified Phase 21 query service over the
    real stored records.
    """
    store, _world_version_id, run_ids = complete_observation_campaign(
        seeds=seeds, campaign_id=campaign_id, with_bindings=with_bindings
    )
    matrix = get_verified_campaign_metric_observation_matrix(
        store=store, tenant_id=TENANT, campaign_id=campaign_id
    )
    return store, matrix, run_ids


def self_consistent_copy(
    matrix: CampaignMetricObservationMatrix,
    **updates: object,
) -> CampaignMetricObservationMatrix:
    """A ``model_copy``-tampered matrix with a recomputed self-covering hash.

    The content hash is recomputed over the tampered content, so only
    the check under test can fail. The original matrix is never mutated.
    Serializer warnings are expected and deliberately suppressed: a
    validator-bypassed nested value (for example a string where an
    integer is required) makes the canonical dump emit diagnostic noise
    while the hash is recomputed.
    """
    tampered = matrix.model_copy(update=updates)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        digest = campaign_metric_observation_matrix_content_hash(tampered)
    return tampered.model_copy(update={"content_hash": digest})


def replace_cell(
    matrix: CampaignMetricObservationMatrix,
    cell_index: int,
    *,
    observations: tuple[RunMetricObservationValue, ...] | None = None,
    **overrides: object,
) -> CampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one cell replaced.

    ``observations`` supplies the exact replacement observation tuple
    (already tampered via ``model_copy`` where validator bypass is
    required); ``overrides`` replace cell fields. The replacement cell
    is assembled with ``model_construct`` so validator-bypassed nested
    observation values (bool, NaN, Infinity, huge integers) survive to
    the builder, whose own strict raw-value checks are the defense
    under test - the cell payload is never re-validated.
    """
    cell = matrix.cells[cell_index]
    payload = cell.model_dump(mode="python")
    if observations is not None:
        payload["observations"] = observations
    else:
        # The Python-mode dump renders nested values as plain dicts;
        # rebuild them as validated Phase 20 value instances so the
        # matrix stays serializer-clean and field access stays typed.
        dumped = payload["observations"]
        assert isinstance(dumped, (list, tuple))
        payload["observations"] = tuple(
            RunMetricObservationValue.model_validate(item) for item in dumped
        )
    payload.update(overrides)
    replaced = CampaignMetricObservationCell.model_construct(**payload)
    cells = matrix.cells[:cell_index] + (replaced,) + matrix.cells[cell_index + 1 :]
    return self_consistent_copy(matrix, cells=cells)


def tamper_observation(
    matrix: CampaignMetricObservationMatrix,
    cell_index: int,
    metric_position: int,
    **updates: object,
) -> CampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one observation's fields replaced.

    ``model_copy`` bypasses the nested Phase 20 value validators, which
    is exactly how validator-bypassed states (bool, NaN, Infinity,
    huge integers, wrong kinds) are injected for defense-in-depth tests.
    """
    cell = matrix.cells[cell_index]
    observations = list(cell.observations)
    observations[metric_position] = observations[metric_position].model_copy(update=updates)
    return replace_cell(matrix, cell_index, observations=tuple(observations))
