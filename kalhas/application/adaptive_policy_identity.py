"""Deterministic adaptive-policy binding identity and content hashing.

Pure identity primitives for the immutable :class:`AdaptivePolicy` authority
(Phase 28, ADR-004 D28-01 frozen top-level persisted authority). The
deterministic policy identifier is hash-derived from the canonical
``(tenant_id, campaign_id, scenario_id, world_version_id, policy_id,
policy_version, schema_version)`` identity payload with a readable, distinct
prefix and exactly 16 lowercase hex digest characters, so identical
campaign/world/policy localities always yield the same identifier regardless
of caller mapping order, rule ordering, observation binding ordering, timing,
metadata, or strategy provenance. A stable policy revision therefore issues a
new identity (policy_version participates in the identifier), matching the
D28-01 rule that a changed policy requires a new immutable identity. The
content hash is the canonical SHA-256 of the complete policy serialization
excluding the top-level ``content_hash`` field itself. The recorded
``content_hash`` is never trusted; the recomputed digest is always derived
from the complete remaining payload.

The module is dependency-neutral and pure: it imports only the repository
hashing helpers and the policy contract, reads no wall clock, uses no
randomness, network, providers, filesystem, store, API, adapters, or domain
packs, never mutates any input, and exposes no builder, verifier, registry,
schema, or runtime surface. Equivalent inputs always produce
exactly equal identifiers and exactly equal content hashes.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy

#: The readable, distinct adaptive-policy identifier prefix.
_ID_PREFIX = "adaptive-policy-"

#: The exact number of lowercase hex digest characters appended to the prefix.
_ID_HASH_LENGTH = 16


def adaptive_policy_identifier(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    policy_id: str,
    policy_version: str,
    schema_version: str,
) -> str:
    """Deterministic stored-policy identifier from the canonical source identity.

    Hash-derived from the canonical ``(tenant_id, campaign_id, scenario_id,
    world_version_id, policy_id, policy_version, schema_version)`` identity
    with the readable prefix ``adaptive-policy-``; deliberately **not** derived
    from the policy content hash, which would be circular because the content
    hash covers the identifier itself. The tenant is part of the stored
    artifact convention; the campaign/scenario/world identity and the stable
    policy revision are part of the policy identity, so a policy can never
    invent or override them. Identical identity inputs always yield the same
    identifier regardless of bindings, timestamps, or metadata.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "scenario_id": scenario_id,
            "world_version_id": world_version_id,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "schema_version": schema_version,
        }
    )
    return f"{_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def adaptive_policy_content_hash(policy: AdaptivePolicy) -> str:
    """Canonical SHA-256 of the complete policy content, excluding content_hash.

    Serializes the complete policy in JSON mode, removes only the top-level
    ``content_hash`` field from the detached copy, and digests the canonical
    JSON of the remaining payload - the identifier, tenant, schema version,
    campaign/scenario/world identity and hashes, the runtime literal, the
    stable policy revision, the complete observation-binding catalog, every
    bound action with its strategy and trajectory-plan provenance, the initial
    and fallback choices, every bound rule, the frozen state-machine
    declarations, ``bound_at``, and the metadata. The recorded ``content_hash``
    is never trusted or incorporated; the policy itself is never mutated.
    """
    payload = policy.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_adaptive_policy_identity(
    policy: object,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    policy_id: str,
    policy_version: str,
) -> None:
    """Verify a policy's ownership, identifier, and content hash.

    Verifies the record is an exact :class:`AdaptivePolicy`, carries the
    requested tenant, campaign, scenario, world, policy identifier, and policy
    revision, that its identifier matches the independent derivation from the
    canonical identity payload, and that its content hash matches the computed
    canonical digest. Deterministic-identity mismatches are checked before
    hash checks. The record is never repaired, normalized, or silently
    accepted; any mismatch raises ``ValueError`` so the store/service
    converts it to the safe typed error without exposing hashes or
    identifiers.
    """
    if type(policy) is not AdaptivePolicy:
        raise ValueError("policy violates its contract")
    if policy.tenant_id != tenant_id:
        raise ValueError("policy tenant mismatch")
    if policy.campaign_id != campaign_id:
        raise ValueError("policy campaign mismatch")
    if policy.scenario_id != scenario_id:
        raise ValueError("policy scenario mismatch")
    if policy.world_version_id != world_version_id:
        raise ValueError("policy world mismatch")
    if policy.policy_id != policy_id:
        raise ValueError("policy identifier mismatch")
    if policy.policy_version != policy_version:
        raise ValueError("policy version mismatch")
    if policy.identifier != adaptive_policy_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        policy_id=policy_id,
        policy_version=policy_version,
        schema_version=policy.schema_version,
    ):
        raise ValueError("policy identity mismatch")
    if policy.content_hash != adaptive_policy_content_hash(policy):
        raise ValueError("policy content hash mismatch")


__all__ = [
    "adaptive_policy_content_hash",
    "adaptive_policy_identifier",
    "verify_adaptive_policy_identity",
]
