"""Deterministic runtime-observation-event identity, hashing, and verification.

Pure identity primitives for the nested, non-authoritative
:class:`RuntimeObservationEvent` evidence record (Phase 28, ADR-004
D28-02/D28-03, H28-S06B2). The deterministic event identifier is
hash-derived from the canonical
``(tenant_id, campaign_id, scenario_seed_id,
runtime_observation_declaration_id, source_step_index)`` identity payload
with a readable, distinct prefix and exactly 16 lowercase hex digest
characters; the local event coordinate is unique per decision history, so
identical localities always yield the same identifier regardless of
values, statuses, provenance, or sequence positions. The content hash is
the canonical SHA-256 of the complete event serialization excluding the
top-level ``content_hash`` field itself; the recorded ``content_hash`` is
never trusted - the recomputed digest is always derived from the complete
remaining payload.

The module also derives the **exact ADR-004 observation-noise
coordinate**: one frozen, canonical payload holding exactly the domain
literal ``kalhas-observation-noise-v1``, the sampler version
``sha256-counter-v1``, the runtime version ``4.0.0``, the world content
hash, the seed content hash, the runtime-observation-declaration content
hash, the source step index, and the local draw index - and nothing else.
No tenant, campaign, run, strategy, policy, action, branch count, rule
count, execution order, or mutable RNG position is expressible in or
around the coordinate, so shared world/seed/declaration coordinates yield
byte-identical noise across strategies and adaptive branching can never
shift future exogenous conditions (fairness by construction).

The module is dependency-neutral and pure: it imports only the repository
hashing helpers and the event contract, reads no wall clock, uses no
randomness, UUID, global RNG, network, providers, filesystem, store, API,
adapters, or domain packs, never mutates any input, and exposes no
builder, registry, schema, or error surface. Equivalent inputs always
produce exactly equal identifiers and exactly equal content hashes.
"""

from __future__ import annotations

from typing import Literal

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

#: The readable, distinct observation-event identifier prefix.
_EVENT_ID_PREFIX = "runtime-observation-event-"

#: The exact number of lowercase hex digest characters appended to a prefix.
_ID_HASH_LENGTH = 16

#: The exact runtime literal the event evidence binds.
RUNTIME_VERSION_LITERAL: Literal["4.0.0"] = "4.0.0"

#: The ADR-004 D28-03 domain-separation literal for observation noise.
OBSERVATION_NOISE_DOMAIN_LITERAL: Literal["kalhas-observation-noise-v1"] = (
    "kalhas-observation-noise-v1"
)

#: The frozen sampler version of the observation-noise coordinate.
OBSERVATION_NOISE_SAMPLER_VERSION: Literal["sha256-counter-v1"] = "sha256-counter-v1"


def observation_noise_coordinate(
    *,
    world_content_hash: str,
    seed_content_hash: str,
    runtime_observation_declaration_content_hash: str,
    source_step_index: int,
    draw_index: int,
) -> str:
    """The exact canonical ADR-004 D28-03 observation-noise coordinate.

    The canonical JSON of exactly the eight frozen coordinate fields -
    the ``kalhas-observation-noise-v1`` domain literal, the
    ``sha256-counter-v1`` sampler version, the ``4.0.0`` runtime version,
    the world content hash, the scenario-seed content hash, the
    observation-declaration content hash, the source step index, and the
    declaration-local draw index - and nothing else. The coordinate is
    derived only from frozen authoritative hashes and integer step
    addressing, so it is byte-identical across strategies, policy
    branchings, and execution orders for the same world, seed,
    declaration, source step, and draw index.
    """
    return canonical_json(
        {
            "domain": OBSERVATION_NOISE_DOMAIN_LITERAL,
            "sampler_version": OBSERVATION_NOISE_SAMPLER_VERSION,
            "runtime_version": RUNTIME_VERSION_LITERAL,
            "world_content_hash": world_content_hash,
            "seed_content_hash": seed_content_hash,
            "runtime_observation_declaration_content_hash": (
                runtime_observation_declaration_content_hash
            ),
            "source_step_index": source_step_index,
            "draw_index": draw_index,
        }
    )


def observation_noise_word(
    *,
    world_content_hash: str,
    seed_content_hash: str,
    runtime_observation_declaration_content_hash: str,
    source_step_index: int,
    draw_index: int,
) -> int:
    """The deterministic 64-bit noise word for one coordinate.

    SHA-256 of the exact observation-noise coordinate; the word is the
    first 8 bytes of the digest interpreted as a big-endian unsigned
    integer in ``[0, 2**64)`` - the same digest-word convention as the
    established ``sha256-counter-v1`` sampler. No strategy identity,
    policy identity, branch count, rule count, execution order, or
    mutable global RNG position enters the derivation.
    """
    return int(
        sha256_hex(
            observation_noise_coordinate(
                world_content_hash=world_content_hash,
                seed_content_hash=seed_content_hash,
                runtime_observation_declaration_content_hash=(
                    runtime_observation_declaration_content_hash
                ),
                source_step_index=source_step_index,
                draw_index=draw_index,
            )
        )[:16],
        16,
    )


def runtime_observation_event_identifier(
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    runtime_observation_declaration_id: str,
    source_step_index: int,
) -> str:
    """Deterministic event identifier from the canonical local event coordinate.

    Hash-derived from the canonical ``(tenant_id, campaign_id,
    scenario_seed_id, runtime_observation_declaration_id,
    source_step_index)`` identity with the readable prefix; deliberately
    **not** derived from the event content hash, which would be circular
    because the content hash covers the identifier itself. The event
    coordinate is local to one decision history, so the tenant, campaign,
    seed, bound declaration, and source step are exactly what
    distinguishes events; the identifier is invariant across strategies,
    policy states, run orders, statuses, and values.
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
    return f"{_EVENT_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def runtime_observation_event_content_hash(event: RuntimeObservationEvent) -> str:
    """Canonical SHA-256 of the complete event content, excluding content_hash.

    Serializes the complete event in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - the identifier, the
    declaration identity and content hash, the logical observation id,
    the source kind, the world and scenario-seed identities with their
    content hashes, the sequence position, source step, delay and
    availability, the terminality and status, the source/state-hash/
    bundle provenance, the exposed values and value kind and unit, the
    noise-coordinate provenance, and the draw index. The recorded
    ``content_hash`` is never trusted or incorporated; the event itself
    is never mutated.
    """
    payload = event.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_runtime_observation_event_identity(
    event: object,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    runtime_observation_declaration_id: str,
    source_step_index: int,
) -> None:
    """Verify an event's exact type, ownership, identifier, and content hash.

    Verifies the record is an exact :class:`RuntimeObservationEvent`
    (never a validator-bypassed subclass), carries the requested tenant,
    campaign, seed, declaration, and source-step locality, that its
    identifier matches the independent derivation from the canonical
    identity payload, and that its content hash matches the recomputed
    canonical digest. Deterministic-identity mismatches are checked
    before hash checks. The record is never repaired, normalized, or
    silently accepted; any mismatch raises ``ValueError`` so the caller
    converts it to the safe typed error without exposing hashes or
    identifiers.
    """
    if type(event) is not RuntimeObservationEvent:
        raise ValueError("event violates its contract")
    observed = event
    if observed.runtime_version != RUNTIME_VERSION_LITERAL:
        raise ValueError("event runtime mismatch")
    if observed.observation_declaration_id != runtime_observation_declaration_id:
        raise ValueError("event declaration mismatch")
    if observed.source_step_index != source_step_index:
        raise ValueError("event source step mismatch")
    if observed.identifier != runtime_observation_event_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        runtime_observation_declaration_id=runtime_observation_declaration_id,
        source_step_index=source_step_index,
    ):
        raise ValueError("event identifier mismatch")
    if observed.content_hash != runtime_observation_event_content_hash(observed):
        raise ValueError("event content hash mismatch")


__all__ = [
    "OBSERVATION_NOISE_DOMAIN_LITERAL",
    "OBSERVATION_NOISE_SAMPLER_VERSION",
    "RUNTIME_VERSION_LITERAL",
    "observation_noise_coordinate",
    "observation_noise_word",
    "runtime_observation_event_content_hash",
    "runtime_observation_event_identifier",
    "verify_runtime_observation_event_identity",
]
