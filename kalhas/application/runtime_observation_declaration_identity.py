"""Deterministic runtime-observation declaration identity and content hashing.

Pure identity primitives for the immutable :class:`RuntimeObservationDeclaration`
authority (Phase 28, ADR-004 frozen top-level persisted authority). The
deterministic declaration identifier is hash-derived from the canonical
``(tenant_id, scenario_id, world_version_id, observation_id)`` identity
payload with a readable, distinct prefix and exactly 16 lowercase hex digest
characters, so identical scenario/world/observation localities always yield
the same identifier regardless of caller mapping order, timestamps, noise,
units, metadata, or the observation source. The content hash is the canonical
SHA-256 of the complete declaration serialization excluding the top-level
``content_hash`` field itself. The recorded ``content_hash`` is never trusted;
the recomputed digest is always derived from the complete remaining payload.

The module is dependency-neutral and pure: it imports only the repository
hashing helpers and the declaration contract, reads no wall clock, uses no
randomness, network, providers, filesystem, store, API, adapters, or domain
packs, never mutates any input, and exposes no builder, verifier, registry,
schema, or error surface. Equivalent inputs always produce exactly equal
identifiers and exactly equal content hashes.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.runtime_observation import RuntimeObservationDeclaration

#: The readable, distinct declaration identifier prefix.
_ID_PREFIX = "runtime-observation-decl-"

#: The exact number of lowercase hex digest characters appended to the prefix.
_ID_HASH_LENGTH = 16


def runtime_observation_declaration_identifier(
    *,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
    observation_id: str,
) -> str:
    """Deterministic stored-declaration identifier from the canonical identity.

    Hash-derived from the canonical ``(tenant_id, scenario_id,
    world_version_id, observation_id)`` identity with the readable prefix; the
    tenant is part of the stored record convention and the scenario/world
    identity is part of the declaration's identity, so a declaration can never
    invent or override them. Deliberately **not** derived from the content
    hash, which would be circular because the content hash covers the
    identifier itself. Identical identity inputs always yield the same
    identifier regardless of timestamps, units, noise, or metadata.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "scenario_id": scenario_id,
            "world_version_id": world_version_id,
            "observation_id": observation_id,
        }
    )
    return f"{_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def runtime_observation_declaration_content_hash(
    declaration: RuntimeObservationDeclaration,
) -> str:
    """Canonical SHA-256 of the complete declaration content, excluding content_hash.

    Serializes the complete declaration in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests the
    canonical JSON of the remaining payload - the schema/tenant/identifier
    identity, the scenario and world identity with the world content hash, the
    logical observation id, the runtime literal, the closed observation
    source with its authoritative manifest/model/field or channel provenance,
    the value kind, unit, timing, noise, missing behavior, ``declared_at``,
    and the metadata. The recorded ``content_hash`` is never trusted or
    incorporated; the declaration itself is never mutated.
    """
    payload = declaration.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_runtime_observation_declaration_identity(
    declaration: object,
    *,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
    observation_id: str,
) -> None:
    """Verify a declaration's ownership, identifier, and content hash.

    Verifies the record is a strict declaration, carries the requested tenant,
    scenario, world, and observation ownership, that its identifier matches the
    independent derivation from the canonical identity payload, and that its
    content hash matches the recomputed canonical digest. Deterministic-
    identity mismatches are checked before hash checks. The record is never
    repaired, normalized, or silently accepted; any mismatch raises
    ``ValueError`` so the store/service converts it to the safe typed error
    without exposing hashes or identifiers.
    """
    # Exact type, not isinstance: a validator-bypassed subclass could
    # otherwise masquerade as a declaration. Detached strict revalidation
    # upstream always yields the exact contract type, so requiring the
    # exact type here cannot reject a legitimate stored record.
    if type(declaration) is not RuntimeObservationDeclaration:
        raise ValueError("declaration violates its contract")
    declarable = declaration
    if declarable.tenant_id != tenant_id:
        raise ValueError("declaration tenant mismatch")
    if declarable.scenario_id != scenario_id:
        raise ValueError("declaration scenario mismatch")
    if declarable.world_version_id != world_version_id:
        raise ValueError("declaration world mismatch")
    if declarable.observation_id != observation_id:
        raise ValueError("declaration observation mismatch")
    if declarable.identifier != runtime_observation_declaration_identifier(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        observation_id=observation_id,
    ):
        raise ValueError("declaration identifier mismatch")
    if declarable.content_hash != runtime_observation_declaration_content_hash(declarable):
        raise ValueError("declaration content hash mismatch")


__all__ = [
    "runtime_observation_declaration_content_hash",
    "runtime_observation_declaration_identifier",
    "verify_runtime_observation_declaration_identity",
]
