"""Deterministic external-observation-input entry and bundle identity and hashing.

Pure identity primitives for the immutable :class:`ExternalObservationInputEntry`
and :class:`ExternalObservationInputBundle` evidence (Phase 28, ADR-004
frozen bundle authority surface, H28-S06B1). The deterministic entry
identifier is hash-derived from the canonical ``(tenant_id, campaign_id,
scenario_seed_id, runtime_observation_declaration_id, source_step_index)``
identity payload with a readable, distinct prefix and exactly 16 lowercase
hex digest characters, so identical tenant/campaign/seed/declaration/step
localities always yield the same identifier regardless of values, channels,
kinds, units, timestamps, or ordering. The deterministic bundle identifier is
hash-derived from the canonical ``(tenant_id, campaign_id, scenario_id,
world_version_id, scenario_seed_id, runtime_version, schema_version)``
identity payload, also with a readable, distinct prefix and exactly 16
lowercase hex digest characters. Content hashes are the canonical SHA-256 of
the complete serialization excluding the top-level ``content_hash`` field
itself; the recorded ``content_hash`` is never trusted.

The module is dependency-neutral and pure: it imports only the repository
hashing helpers and the entry/bundle contracts, reads no wall clock, uses no
randomness, network, providers, filesystem, store, API, adapters, or domain
packs, never mutates any input, and exposes no builder, verifier, registry,
schema, or error surface. Equivalent inputs always produce exactly equal
identifiers and exactly equal content hashes.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationInputEntry,
)

#: The readable, distinct external-input entry identifier prefix.
_ENTRY_ID_PREFIX = "external-input-entry-"

#: The readable, distinct external-input bundle identifier prefix.
_BUNDLE_ID_PREFIX = "external-input-bundle-"

#: The exact number of lowercase hex digest characters appended to a prefix.
_ID_HASH_LENGTH = 16

#: The exact runtime literal the bundle authority binds.
_RUNTIME_VERSION_LITERAL = "4.0.0"


def external_observation_input_entry_identifier(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    runtime_observation_declaration_id: str,
    source_step_index: int,
) -> str:
    """Deterministic stored-entry identifier from the canonical source identity.

    Hash-derived from the canonical ``(tenant_id, campaign_id,
    scenario_seed_id, runtime_observation_declaration_id, source_step_index)``
    identity with the readable prefix ``external-input-entry-``; deliberately
    **not** derived from the entry content hash, which would be circular
    because the content hash covers the identifier itself. The tenant,
    campaign, scenario seed, bound declaration, and source step are all part
    of the entry identity, so an entry can never invent or override them.
    Identical identity inputs always yield the same identifier regardless of
    values, channels, kinds, units, or timestamps.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "scenario_seed_id": scenario_seed_id,
            "runtime_observation_declaration_id": runtime_observation_declaration_id,
            "source_step_index": source_step_index,
        }
    )
    return f"{_ENTRY_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def external_observation_input_entry_content_hash(entry: ExternalObservationInputEntry) -> str:
    """Canonical SHA-256 of the complete entry content, excluding content_hash.

    Serializes the complete entry in JSON mode, removes only the top-level
    ``content_hash`` field from the detached copy, and digests the canonical
    JSON of the remaining payload - the identifier, the declaration
    identifier and content hash, the logical observation id, the copied
    external channel id, the source step index, the value kind and unit, and
    the exact value. The recorded ``content_hash`` is never trusted or
    incorporated; the entry itself is never mutated.
    """
    payload = entry.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def external_observation_input_bundle_identifier(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    scenario_seed_id: str,
    runtime_version: str,
    schema_version: str,
) -> str:
    """Deterministic stored-bundle identifier from the canonical source identity.

    Hash-derived from the canonical ``(tenant_id, campaign_id, scenario_id,
    world_version_id, scenario_seed_id, runtime_version, schema_version)``
    identity with the readable prefix ``external-input-bundle-``; deliberately
    **not** derived from the bundle content hash, which would be circular
    because the content hash covers the identifier itself. The tenant,
    campaign, scenario, world, scenario seed, and runtime/schema version are
    all part of the bundle identity, so a bundle can never invent or override
    them - including the scenario seed, because every compared strategy must
    receive the exact same ordered external inputs (ADR-004 D28-04).
    Identical identity inputs always yield the same identifier regardless of
    entries, hashes, or timestamps.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "scenario_id": scenario_id,
            "world_version_id": world_version_id,
            "scenario_seed_id": scenario_seed_id,
            "runtime_version": runtime_version,
            "schema_version": schema_version,
        }
    )
    return f"{_BUNDLE_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def external_observation_input_bundle_content_hash(bundle: ExternalObservationInputBundle) -> str:
    """Canonical SHA-256 of the complete bundle content, excluding content_hash.

    Serializes the complete bundle in JSON mode, removes only the top-level
    ``content_hash`` field from the detached copy, and digests the canonical
    JSON of the remaining payload - the identifier, tenant, schema version,
    campaign/scenario identity, the world and scenario-seed identities with
    their content hashes, the runtime literal, every canonical entry (each
    with its own identifier and content hash), and the deterministic
    ``accepted_at``. The recorded ``content_hash`` is never trusted or
    incorporated; the bundle itself is never mutated.
    """
    payload = bundle.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_external_observation_input_entry_identity(
    entry: object,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
) -> None:
    """Verify an entry's identity: exact type, identifier, and content hash.

    Verifies the record is an exact :class:`ExternalObservationInputEntry`,
    that its identifier matches the independent derivation from the canonical
    identity payload, and that its content hash matches the recomputed
    canonical digest. Deterministic-identity mismatches are checked before
    hash checks. The record is never repaired, normalized, or silently
    accepted; any mismatch raises ``ValueError`` so the store/service converts
    it to the safe typed error without exposing hashes or identifiers.
    """
    if type(entry) is not ExternalObservationInputEntry:
        raise ValueError("entry violates its contract")
    if entry.identifier != external_observation_input_entry_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        runtime_observation_declaration_id=entry.runtime_observation_declaration_id,
        source_step_index=entry.source_step_index,
    ):
        raise ValueError("entry identifier mismatch")
    if entry.content_hash != external_observation_input_entry_content_hash(entry):
        raise ValueError("entry content hash mismatch")


def verify_external_observation_input_bundle_identity(
    bundle: object,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
    scenario_seed_id: str,
) -> None:
    """Verify a bundle's identity and every entry identity.

    Verifies the record is an exact :class:`ExternalObservationInputBundle`,
    carries the requested tenant, campaign, scenario, world, and scenario-seed
    ownership with the exact runtime literal, that its identifier matches the
    independent derivation from the canonical identity payload, and that its
    content hash matches the recomputed canonical digest; every contained
    entry is then independently verified the same way. Deterministic-identity
    mismatches are checked before hash checks. The record is never repaired,
    normalized, or silently accepted; any mismatch raises ``ValueError`` so
    the store/service converts it to the safe typed error without exposing
    hashes or identifiers.
    """
    if type(bundle) is not ExternalObservationInputBundle:
        raise ValueError("bundle violates its contract")
    if bundle.tenant_id != tenant_id:
        raise ValueError("bundle tenant mismatch")
    if bundle.campaign_id != campaign_id:
        raise ValueError("bundle campaign mismatch")
    if bundle.scenario_id != scenario_id:
        raise ValueError("bundle scenario mismatch")
    if bundle.world_version_id != world_version_id:
        raise ValueError("bundle world mismatch")
    if bundle.scenario_seed_id != scenario_seed_id:
        raise ValueError("bundle scenario seed mismatch")
    if bundle.runtime_version != _RUNTIME_VERSION_LITERAL:
        raise ValueError("bundle runtime mismatch")
    if bundle.identifier != external_observation_input_bundle_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        scenario_seed_id=scenario_seed_id,
        runtime_version=bundle.runtime_version,
        schema_version=bundle.schema_version,
    ):
        raise ValueError("bundle identity mismatch")
    if bundle.content_hash != external_observation_input_bundle_content_hash(bundle):
        raise ValueError("bundle content hash mismatch")
    for entry in bundle.entries:
        verify_external_observation_input_entry_identity(
            entry,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
        )


__all__ = [
    "external_observation_input_bundle_content_hash",
    "external_observation_input_bundle_identifier",
    "external_observation_input_entry_content_hash",
    "external_observation_input_entry_identifier",
    "verify_external_observation_input_bundle_identity",
    "verify_external_observation_input_entry_identity",
]
