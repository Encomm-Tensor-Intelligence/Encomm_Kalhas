"""Deterministic identity, content hashing, and identity verification of replay manifests.

Pure identity primitives for the immutable
:class:`AdaptiveRunTrajectoryReplayManifest` authority (Phase 28,
ADR-004 D28-04, H28-S07B1A). The deterministic replay-manifest
identifier is hash-derived from the canonical ``(run_id, runtime_version)``
identity payload with a readable, distinct adaptive-runtime prefix and
exactly 16 lowercase hex digest characters, so the replay manifest of one
runtime-4 run can never collide with the runtime-4 execution identifier
(a different prefix) or with any historical runtime-2/3 replay or
execution identifier. The content hash is the canonical SHA-256 of the
complete manifest serialization excluding the top-level ``content_hash``
field itself; the recorded ``content_hash`` is never trusted - the
recomputed digest is always derived from the complete remaining payload,
which covers the run/campaign provenance, the execution reference, the
world/seed/realization identities and content hashes, the adaptive-policy
identifier/policy id/content hash, the optional external-input bundle
pair, the runtime literal, the input hash, the exact ordered
trajectory-plan-set hash, the expected and recomputed execution hashes,
the classification literal, and the deterministic authority time
``replayed_at`` - so the manifest is self-covering by construction.

The module is dependency-neutral and pure: it imports only the repository
hashing helpers and the manifest contract; it reads no wall clock, uses
no randomness, UUID, global RNG, network, providers, filesystem, store,
API, adapters, or domain packs, never mutates any input, and exposes no
builder, registry, or state. Equivalent inputs always produce exactly
equal identifiers and exactly equal digests.
"""

from __future__ import annotations

from typing import Literal

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.adaptive_trajectory_replay import AdaptiveRunTrajectoryReplayManifest

#: The readable, distinct adaptive-runtime replay-manifest identifier prefix.
_ID_PREFIX = "adaptive-run-trajectory-replay-"

#: The exact number of lowercase hex digest characters appended to a prefix.
_ID_HASH_LENGTH = 16

#: The exact runtime literal this slice binds.
RUNTIME_VERSION_LITERAL: Literal["4.0.0"] = "4.0.0"


def adaptive_run_trajectory_replay_manifest_identifier(
    *,
    run_id: str,
    runtime_version: str,
) -> str:
    """Deterministic runtime-4 replay-manifest identifier from run identity and runtime.

    Hash-derived from the canonical ``(run_id, runtime_version)``
    identity payload with the readable prefix
    ``adaptive-run-trajectory-replay-``; deliberately **not** derived
    from the content hash, which would be circular because the content
    hash covers the identifier itself. The distinct prefix and the
    ``4.0.0`` runtime literal guarantee the replay manifest never
    collides with the runtime-4 execution identifier
    (``adaptive-run-trajectory-execution-``) or with any historical
    runtime-2/3 replay or execution identifier. Identical inputs always
    yield the same identifier.
    """
    canonical = canonical_json(
        {
            "run_id": run_id,
            "runtime_version": runtime_version,
        }
    )
    return f"{_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def adaptive_run_trajectory_replay_manifest_content_hash(
    manifest: AdaptiveRunTrajectoryReplayManifest,
) -> str:
    """Canonical SHA-256 of the complete replay-manifest content, excluding content_hash.

    Serializes the complete manifest in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - the deterministic
    identifier, tenant/run/campaign provenance, the execution reference,
    every world/seed/realization/policy/bundle identity and hash, the
    runtime literal, the input hash, the plan-set hash, the expected and
    recomputed execution hashes, the classification, and ``replayed_at``.
    The recorded ``content_hash`` is never trusted or incorporated; the
    manifest is never mutated.
    """
    payload = manifest.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def verify_adaptive_run_trajectory_replay_manifest_identity(
    manifest: object,
) -> None:
    """Verify a replay manifest's exact type, identifier, and content hash.

    Verifies the record is an exact
    :class:`AdaptiveRunTrajectoryReplayManifest` (never a
    validator-bypassed subclass or a ``model_construct`` forgery carrying
    a value the contract validators would reject), passes detached strict
    revalidation (every contract validator re-run over the record's own
    serialization), carries the exact runtime literal, that its
    identifier matches the independent derivation from the canonical
    identity payload, and that its content hash matches the recomputed
    canonical digest. Deterministic-identity mismatches are checked
    before hash checks. The record is never repaired, normalized, or
    silently accepted; any mismatch raises ``ValueError`` so the verifier
    or store converts it to the safe typed error without exposing hashes
    or identifiers.
    """
    if type(manifest) is not AdaptiveRunTrajectoryReplayManifest:
        raise ValueError("manifest violates its contract")
    observed = manifest
    _strictly_revalidate_detached(observed)
    if observed.runtime_version != RUNTIME_VERSION_LITERAL:
        raise ValueError("manifest runtime mismatch")
    if observed.identifier != adaptive_run_trajectory_replay_manifest_identifier(
        run_id=observed.run_id,
        runtime_version=observed.runtime_version,
    ):
        raise ValueError("manifest identifier mismatch")
    if observed.content_hash != adaptive_run_trajectory_replay_manifest_content_hash(observed):
        raise ValueError("manifest content hash mismatch")


def _strictly_revalidate_detached(artifact: AdaptiveRunTrajectoryReplayManifest) -> None:
    """Re-run every contract validator over the artifact's own serialization.

    The artifact's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance carrying wrong-typed or otherwise invalid field values is
    rejected before any field of it is trusted. The revalidation result
    is discarded; the artifact is never replaced, repaired, or mutated.
    Any failure raises ``ValueError``.
    """
    import warnings

    from pydantic import ValidationError

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        AdaptiveRunTrajectoryReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("manifest failed detached strict revalidation") from None


__all__ = [
    "RUNTIME_VERSION_LITERAL",
    "adaptive_run_trajectory_replay_manifest_content_hash",
    "adaptive_run_trajectory_replay_manifest_identifier",
    "verify_adaptive_run_trajectory_replay_manifest_identity",
]
