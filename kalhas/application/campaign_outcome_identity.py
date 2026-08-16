"""Deterministic campaign outcome-distribution matrix identity and content hashing.

Pure identity primitives for the immutable
``CampaignOutcomeDistributionMatrix`` artifact. The deterministic
matrix identifier is hash-derived from the canonical source-identity
payload (campaign, world version, runtime version, evaluation profile,
and the two exact source matrix references) with a readable prefix -
deliberately **never** from the matrix content hash (which would be
circular because the content hash covers the identifier itself) and
never from timestamps, outcome evidence, or the tenant. The content
hash is the canonical SHA-256 of the complete matrix serialization
excluding ``content_hash`` itself, covering the inherited identity
fields, campaign/scenario/world identity and hashes, runtime and
comparison mode, evaluation-profile and optional uncertainty
provenance, both source references, every ordered identifier tuple,
every nested outcome and empirical-distribution value, and
``derived_at``.

The module is dependency-neutral and pure: it imports only the
repository hashing helpers and the outcome contract, reads no wall
clock, uses no randomness, network, providers, filesystem, store, API,
query service, adapters, or domain packs, never mutates any input, and
exposes no builder, verifier, registry, schema, error mapping, ranking,
scoring, comparison, recommendation, or decision surface. The recorded
``content_hash`` is never trusted; the recomputed digest is always
derived from the complete remaining payload.

Equivalent inputs always produce exactly equal identifiers and exactly
equal content hashes.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix

#: The readable, distinct matrix identifier prefix.
_MATRIX_ID_PREFIX = "campaign-outcome-distribution-matrix-"

#: The exact number of lowercase hex digest characters appended to the prefix.
_ID_HASH_LENGTH = 16


def campaign_outcome_distribution_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
    evaluation_profile_id: str,
    source_world_realization_matrix_id: str,
    source_metric_observation_matrix_id: str,
) -> str:
    """Deterministic matrix identifier from the canonical source identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    runtime_version, evaluation_profile_id,
    source_world_realization_matrix_id, source_metric_observation_matrix_id)``
    identity with a readable, distinct prefix; deliberately **not**
    derived from the matrix content hash, which would be circular
    because the content hash covers the identifier itself. Identical
    identity inputs always yield the same identifier regardless of
    caller mapping order, timestamps, outcome evidence, or the tenant.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
            "evaluation_profile_id": evaluation_profile_id,
            "source_world_realization_matrix_id": source_world_realization_matrix_id,
            "source_metric_observation_matrix_id": source_metric_observation_matrix_id,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_outcome_distribution_matrix_content_hash(
    matrix: CampaignOutcomeDistributionMatrix,
) -> str:
    """Canonical SHA-256 of the complete matrix content, excluding content_hash.

    Serializes the complete matrix in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - the identifier, the
    tenant, the schema version, the campaign/scenario/world identity and
    hashes, the runtime and comparison mode, the evaluation-profile
    provenance, the optional uncertainty provenance, both source matrix
    identities and hashes, all ordered identifier tuples, every nested
    outcome and empirical-distribution value, and ``derived_at``. The
    recorded ``content_hash`` is never trusted or incorporated; the
    matrix itself is never mutated.
    """
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


__all__ = [
    "campaign_outcome_distribution_matrix_identifier",
    "campaign_outcome_distribution_matrix_content_hash",
]
