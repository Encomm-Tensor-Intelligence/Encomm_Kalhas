"""Deterministic campaign decision artifact identity and content hashing.

Pure identity primitives for the three immutable campaign decision
artifacts: ``CampaignDecisionPolicy`` (stored), ``CampaignStrategyComparison``
(derived), and ``CampaignDecisionBrief`` (derived). Every identifier is
hash-derived from a canonical identity payload with a readable, distinct
prefix and exactly 16 lowercase hexadecimal digest characters; every
content hash is the canonical SHA-256 of the complete artifact
serialization excluding the top-level ``content_hash`` field itself.

Identifier payloads (documented exactly, in canonical JSON form):

- policy: ``(tenant_id, campaign_id, scenario_id, world_version_id,
  evaluation_profile_id, schema_version)`` under the prefix
  ``campaign-decision-policy-`` - the tenant is part of the stored
  artifact convention, and the scenario identity is part of the policy
  identifier so a declaration can never invent or override it;
- comparison: ``(campaign_id, world_version_id, evaluation_profile_id,
  policy_id, source_outcome_matrix_id)`` under the prefix
  ``campaign-strategy-comparison-`` - the tenant is deliberately
  excluded from derived identifiers (the established convention for
  derived artifacts);
- brief: ``(campaign_id, world_version_id, policy_id, comparison_id)``
  under the prefix ``campaign-decision-brief-`` - likewise tenant-free.

Identifiers are never derived from content hashes (which would be
circular because the content hash covers the identifier itself), never
from timestamps, evidence values, metadata, or float-to-text fragments,
and never from the tenant for derived artifacts. Content hashes cover
every remaining payload field, including the scenario identity/hash,
the evaluation-profile identity/hash, the objective-weight snapshots,
the fixed tail alpha, the decision rules, the declared/derived/
produced timestamps, and the metadata.

The module is dependency-neutral and pure: it imports only the
repository hashing helpers and the decision contract, reads no wall
clock, uses no randomness, network, providers, filesystem, store, API,
query service, adapters, or domain packs, never mutates any input, and
exposes no builder, verifier, registry, schema, error mapping, ranking,
scoring, or recommendation surface. The recorded ``content_hash`` is
never trusted; the recomputed digest is always derived from the
complete remaining payload. Equivalent inputs always produce exactly
equal identifiers and exactly equal content hashes.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
)

#: The readable, distinct policy identifier prefix.
_POLICY_ID_PREFIX = "campaign-decision-policy-"

#: The readable, distinct comparison identifier prefix.
_COMPARISON_ID_PREFIX = "campaign-strategy-comparison-"

#: The readable, distinct brief identifier prefix.
_BRIEF_ID_PREFIX = "campaign-decision-brief-"

#: The exact number of lowercase hex digest characters appended to each prefix.
_ID_HASH_LENGTH = 16


def campaign_decision_policy_identifier(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    evaluation_profile_id: str,
    schema_version: str,
) -> str:
    """Deterministic stored-policy identifier from the canonical source identity.

    Hash-derived from the canonical ``(tenant_id, campaign_id,
    scenario_id, world_version_id, evaluation_profile_id,
    schema_version)`` identity with the readable prefix
    ``campaign-decision-policy-``; deliberately **not** derived from the
    policy content hash, which would be circular because the content
    hash covers the identifier itself. The tenant is part of the stored
    artifact convention; the scenario identity is part of the policy
    identity. Identical identity inputs always yield the same
    identifier regardless of caller mapping order, timestamps, evidence,
    metadata, or float text.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "scenario_id": scenario_id,
            "world_version_id": world_version_id,
            "evaluation_profile_id": evaluation_profile_id,
            "schema_version": schema_version,
        }
    )
    return f"{_POLICY_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_decision_policy_content_hash(policy: CampaignDecisionPolicy) -> str:
    """Canonical SHA-256 of the complete policy content, excluding content_hash.

    Serializes the complete policy in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - the identifier, the
    tenant, the schema version, the campaign/scenario/world identity and
    hashes, the evaluation-profile identity and hash, the algorithm
    identifier, the target-requirement mode and rules, the objective
    weight snapshots, the minimum sample count, the tie tolerance, the
    hard-gate flag, the fixed tail alpha, ``declared_at``, and the
    metadata. The recorded ``content_hash`` is never trusted or
    incorporated; the policy itself is never mutated.
    """
    payload = policy.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def campaign_strategy_comparison_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    evaluation_profile_id: str,
    policy_id: str,
    source_outcome_matrix_id: str,
) -> str:
    """Deterministic derived-comparison identifier from the canonical source identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    evaluation_profile_id, policy_id, source_outcome_matrix_id)``
    identity with the readable prefix ``campaign-strategy-comparison-``;
    the tenant is deliberately excluded from derived identifiers (the
    established convention for derived artifacts). Identical identity
    inputs always yield the same identifier regardless of caller mapping
    order, timestamps, evidence, metadata, or float text.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "evaluation_profile_id": evaluation_profile_id,
            "policy_id": policy_id,
            "source_outcome_matrix_id": source_outcome_matrix_id,
        }
    )
    return f"{_COMPARISON_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_strategy_comparison_content_hash(
    comparison: CampaignStrategyComparison,
) -> str:
    """Canonical SHA-256 of the complete comparison content, excluding content_hash.

    Serializes the complete comparison in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - every identity field,
    the scenario/world identity and hashes, the runtime/comparison-mode/
    algorithm literals, the policy and source outcome-matrix references,
    the tie-tolerance and minimum-sample-count snapshots, every ordered
    identifier tuple, every paired comparison, every dominance relation,
    every robustness profile, and ``derived_at``. The recorded
    ``content_hash`` is never trusted or incorporated; the comparison
    itself is never mutated.
    """
    payload = comparison.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def campaign_decision_brief_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    policy_id: str,
    comparison_id: str,
) -> str:
    """Deterministic derived-brief identifier from the canonical source identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    policy_id, comparison_id)`` identity with the readable prefix
    ``campaign-decision-brief-``; the tenant is deliberately excluded
    from derived identifiers (the established convention for derived
    artifacts). Identical identity inputs always yield the same
    identifier regardless of caller mapping order, timestamps, evidence,
    metadata, or float text.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "policy_id": policy_id,
            "comparison_id": comparison_id,
        }
    )
    return f"{_BRIEF_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_decision_brief_content_hash(brief: CampaignDecisionBrief) -> str:
    """Canonical SHA-256 of the complete brief content, excluding content_hash.

    Serializes the complete brief in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - every identity field,
    the scenario/world identity and world hash, the runtime/comparison-
    mode/algorithm literals, the policy and comparison references, the
    status and optional preferred strategy id, the considered-strategy
    order, the summary, the terminal reason, the decisive and blocking
    factors, the copied robustness profiles, the copied assumptions,
    every evidence reference, and ``produced_at``. The recorded
    ``content_hash`` is never trusted or incorporated; the brief itself
    is never mutated.
    """
    payload = brief.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


__all__ = [
    "campaign_decision_policy_identifier",
    "campaign_decision_policy_content_hash",
    "campaign_strategy_comparison_identifier",
    "campaign_strategy_comparison_content_hash",
    "campaign_decision_brief_identifier",
    "campaign_decision_brief_content_hash",
]
