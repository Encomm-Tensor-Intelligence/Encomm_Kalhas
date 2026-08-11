"""Pure Phase 24 world-uncertainty identity and hashing helpers.

Dependency-neutral module: no store, service, API, adapter, or I/O
imports - only contracts, the deterministic hashing primitives, the
shared scenario snapshot hash, and the typed Phase 24 error types. The
declaration service, the in-memory store (write and read boundary
revalidation), the world integrity verifier, the realization builder,
the campaign query service, and the mock NEXUS compilation path all
reuse exactly the same definitions, so the deterministic identifiers,
the seed snapshot hash, the content hashes, and the ownership/identity
verification can never drift between layers.

Identifiers are hash-derived from canonical identity payloads with
readable prefixes and are deliberately **never** derived from the
artifact's own content hash (which would be circular because the
content hash covers the identifier itself). The absent-uncertainty
marker is the exact literal ``"absent"`` so empty realizations and
model-free matrices have stable identities.

Everything here is pure and deterministic: no wall clock, no
randomness, no network, no filesystem, no provider access.
"""

from __future__ import annotations

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyModelIntegrityError,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import SCHEMA_VERSION
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix,
    StateFieldUncertaintyBinding,
    WorldRealization,
    WorldUncertaintyModel,
)

_BINDING_ID_PREFIX = "uncertainty-binding-"
_MODEL_ID_PREFIX = "uncertainty-model-"
_REALIZATION_ID_PREFIX = "world-realization-"
_MATRIX_ID_PREFIX = "campaign-realization-matrix-"
_ID_HASH_LENGTH = 16

#: The explicit absent-uncertainty marker used in identity payloads.
ABSENT_MODEL_MARKER = "absent"


def seed_content_hash(seed: ScenarioSeed) -> str:
    """The authoritative content hash of one stored seed.

    SHA-256 of the canonical JSON serialization of the complete
    ``ScenarioSeed`` model dump in JSON mode. ``ScenarioSeed`` has no
    content-hash field (it is a frozen v1 contract), so the digest is
    derived here and recorded on every realization.
    """
    return sha256_hex(canonical_json(seed.model_dump(mode="json")))


def uncertainty_binding_identifier(
    *,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    state_field_id: str,
) -> str:
    """Deterministic, collision-safe, independently derived binding identifier.

    Hash-derived from the canonical complete target identity - never
    from the binding content hash, which would be circular. Identical
    target tuples always yield the same identifier, regardless of the
    distribution or bound content.
    """
    canonical = canonical_json(
        {
            "scenario_id": scenario_id,
            "manifest_id": manifest_id,
            "state_model_id": state_model_id,
            "state_field_id": state_field_id,
        }
    )
    return f"{_BINDING_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def uncertainty_binding_content_hash(binding: StateFieldUncertaintyBinding) -> str:
    """Canonical SHA-256 of the binding content, excluding ``content_hash``."""
    payload = binding.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def uncertainty_model_identifier(
    *,
    tenant_id: str,
    scenario_id: str,
    scenario_content_hash_value: str,
) -> str:
    """Deterministic, collision-safe, independently derived model identifier.

    Hash-derived from the canonical identity tuple (tenant, scenario,
    scenario snapshot hash, schema version) - deliberately **not** from
    the model content hash, which would be circular.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "scenario_id": scenario_id,
            "scenario_content_hash": scenario_content_hash_value,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return f"{_MODEL_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def uncertainty_model_content_hash(model: WorldUncertaintyModel) -> str:
    """Canonical SHA-256 of the model content, excluding ``content_hash``."""
    payload = model.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def world_realization_identifier(
    *,
    world_version_id: str,
    world_content_hash: str,
    scenario_seed_id: str,
    seed_content_hash_value: str,
    uncertainty_model_id: str | None,
    uncertainty_model_content_hash_value: str | None,
    sampler_version: str,
    quantization_policy: str,
    quantization_fraction_bits: int,
) -> str:
    """Deterministic realization identifier from the canonical identity payload.

    Covers the world identity **and** content hash, the seed identity
    **and** content hash, the uncertainty-model identity/hash or the
    explicit ``"absent"`` marker, and the sampler/quantization
    provenance - never the realization content hash. Strategy inputs
    are structurally absent.
    """
    canonical = canonical_json(
        {
            "world_version_id": world_version_id,
            "world_content_hash": world_content_hash,
            "scenario_seed_id": scenario_seed_id,
            "seed_content_hash": seed_content_hash_value,
            "uncertainty_model_id": (
                uncertainty_model_id if uncertainty_model_id is not None else ABSENT_MODEL_MARKER
            ),
            "uncertainty_model_content_hash": (
                uncertainty_model_content_hash_value
                if uncertainty_model_content_hash_value is not None
                else ABSENT_MODEL_MARKER
            ),
            "sampler_version": sampler_version,
            "quantization_policy": quantization_policy,
            "quantization_fraction_bits": quantization_fraction_bits,
        }
    )
    return f"{_REALIZATION_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def world_realization_content_hash(realization: WorldRealization) -> str:
    """Canonical SHA-256 of the realization content, excluding ``content_hash``."""
    payload = realization.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def campaign_realization_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    world_content_hash: str,
    uncertainty_model_id: str | None,
    uncertainty_model_content_hash_value: str | None,
    sampler_version: str,
    quantization_policy: str,
    quantization_fraction_bits: int,
) -> str:
    """Deterministic matrix identifier from the canonical identity payload.

    Deliberately **not** derived from the matrix content hash. Strategy
    inputs are structurally absent.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "world_content_hash": world_content_hash,
            "uncertainty_model_id": (
                uncertainty_model_id if uncertainty_model_id is not None else ABSENT_MODEL_MARKER
            ),
            "uncertainty_model_content_hash": (
                uncertainty_model_content_hash_value
                if uncertainty_model_content_hash_value is not None
                else ABSENT_MODEL_MARKER
            ),
            "sampler_version": sampler_version,
            "quantization_policy": quantization_policy,
            "quantization_fraction_bits": quantization_fraction_bits,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_realization_matrix_content_hash(
    matrix: CampaignWorldRealizationMatrix,
) -> str:
    """Canonical SHA-256 of the matrix content, excluding ``content_hash``."""
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_world_uncertainty_model_identity(
    model: WorldUncertaintyModel,
    *,
    tenant_id: str,
    scenario_id: str,
) -> None:
    """Verify a stored model's identity and hashes independently.

    Verifies the model carries the requested ownership, that its
    identifier matches the independent derivation from the canonical
    identity payload, and that its content hash matches the recomputed
    canonical digest. Deterministic-identity mismatches are checked
    before hash checks. The record is never repaired, normalized, or
    silently accepted; any mismatch raises the safe typed integrity
    error.
    """
    if model.tenant_id != tenant_id or model.scenario_id != scenario_id:
        raise WorldUncertaintyModelIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored uncertainty model ownership mismatch",
        )
    if model.identifier != uncertainty_model_identifier(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        scenario_content_hash_value=model.scenario_content_hash,
    ):
        raise WorldUncertaintyModelIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored uncertainty model identifier mismatch",
        )
    if model.content_hash != uncertainty_model_content_hash(model):
        raise WorldUncertaintyModelIntegrityError(
            tenant_id,
            scenario_id,
            reason="stored uncertainty model content hash mismatch",
        )
