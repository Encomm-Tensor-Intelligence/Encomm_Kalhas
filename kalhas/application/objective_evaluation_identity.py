"""Pure evaluation-profile identity and hashing helpers (Phase 23).

Dependency-neutral module: no store, service, API, adapter, or I/O
imports - only contracts, the deterministic hashing primitives, and
the typed Phase 23 error types. The declaration service, the in-memory
store (write and read boundary revalidation), the world integrity
verifier, the campaign query service, and the mock NEXUS compilation
path all reuse exactly the same definitions, so the deterministic
identifier, the scenario snapshot hash, the profile content hash, and
the ownership/identity verification can never drift between layers.

Everything here is pure and deterministic: no wall clock, no
randomness, no network, no filesystem, no provider access.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileIntegrityError,
)
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import SCHEMA_VERSION

_PROFILE_ID_PREFIX = "evaluation-profile-"
_ID_HASH_LENGTH = 16


def scenario_content_hash(scenario: ScenarioSpec) -> str:
    """The authoritative scenario snapshot hash of one stored scenario.

    SHA-256 of the canonical JSON serialization of the complete
    ``ScenarioSpec`` model dump in JSON mode. Pure and deterministic:
    identical scenarios always produce the identical digest.
    """
    return sha256_hex(canonical_json(scenario.model_dump(mode="json")))


def evaluation_profile_identifier(
    *,
    tenant_id: str,
    scenario_id: str,
    scenario_content_hash_value: str,
) -> str:
    """Deterministic, collision-safe, independently derived profile identifier.

    Hash-derived from the canonical identity tuple (tenant, scenario,
    scenario snapshot hash, schema version) - deliberately **not** from
    the profile content hash, which would be circular because the
    content hash covers the identifier itself. Identical identity
    inputs always yield the same identifier, regardless of the binding
    content, and user-provided delimiter characters cannot create
    ambiguity.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "scenario_id": scenario_id,
            "scenario_content_hash": scenario_content_hash_value,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return f"{_PROFILE_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def evaluation_profile_content_hash(profile: ScenarioEvaluationProfile) -> str:
    """Canonical SHA-256 of the profile content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, so equivalent profiles always produce the
    same lowercase 64-character digest.
    """
    payload = profile.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_evaluation_profile_identity(
    profile: object,
    *,
    tenant_id: str,
    scenario_id: str,
) -> None:
    """Verify a stored profile's identity and hashes independently.

    Verifies the profile is a strict ``ScenarioEvaluationProfile``
    carrying the requested ownership, that its identifier matches the
    independent derivation from the canonical identity payload, and
    that its content hash matches the recomputed canonical digest.
    Deterministic-identity mismatches are checked before hash checks.
    The record is never repaired, normalized, or silently accepted; any
    mismatch raises the safe typed integrity error.
    """
    if not isinstance(profile, ScenarioEvaluationProfile):
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile violates its contract",
        )
    if profile.tenant_id != tenant_id or profile.scenario_id != scenario_id:
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile ownership mismatch",
        )
    if profile.identifier != evaluation_profile_identifier(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        scenario_content_hash_value=profile.scenario_content_hash,
    ):
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile identifier mismatch",
        )
    if profile.content_hash != evaluation_profile_content_hash(profile):
        raise EvaluationProfileIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored evaluation profile content hash mismatch",
        )
