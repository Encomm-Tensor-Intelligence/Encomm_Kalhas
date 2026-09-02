"""Deterministic identity, content hashing, and the frozen runtime-4 input digest.

Pure identity primitives for the immutable
:class:`AdaptiveRunTrajectoryExecution` aggregate (Phase 28, ADR-004
D28-04, H28-S06C1). The deterministic execution identifier is hash-derived
from the canonical ``(run_id, runtime_version)`` identity payload with a
readable, distinct adaptive-runtime prefix and exactly 16 lowercase hex
digest characters, so runtime 4 can never collide with the historical
runtime-2/3 execution identifiers (a different prefix and a runtime
literal that no historical runtime carries). The content hash is the
canonical SHA-256 of the complete aggregate serialization excluding the
top-level ``content_hash`` field itself; the recorded ``content_hash`` is
never trusted - the recomputed digest is always derived from the complete
remaining payload.

The frozen runtime-4 input digest covers exactly the immutable inputs
that can affect one adaptive run: the run-plan identity and its recorded
input hash, the campaign identity, the world identity and content hash,
the scenario-seed identity and recomputed content hash, the world
realization identity and content hash, the adaptive-policy identifier and
content hash, the exact trajectory-plan-set hash, the optional
external-input bundle identifier/content-hash pair (both or neither), the
exact causal run horizon ``final_decision_step`` (the zero-based final
decision step; the covered decision count is always
``final_decision_step + 1``), and the runtime literal ``4.0.0`` - and
nothing else. No timestamp other than the already-authoritative run-plan
provenance, no mutable store order, no policy decision, no observation
output, no strategy/branch count, no global RNG state, and no process
data is expressible in the digest.

The module is dependency-neutral and pure: it imports only the repository
hashing helpers, the aggregate contract, and the pure seed content-hash
helper; it reads no wall clock, uses no randomness, UUID, global RNG,
network, providers, filesystem, store, API, adapters, or domain packs,
never mutates any input, and exposes no builder, registry, or state.
Equivalent inputs always produce exactly equal identifiers and exactly
equal digests.
"""

from __future__ import annotations

from typing import Literal

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution

#: The readable, distinct adaptive-runtime execution identifier prefix.
_ID_PREFIX = "adaptive-run-trajectory-execution-"

#: The exact number of lowercase hex digest characters appended to a prefix.
_ID_HASH_LENGTH = 16

#: The exact runtime literal this slice binds.
RUNTIME_VERSION_LITERAL: Literal["4.0.0"] = "4.0.0"


def adaptive_run_trajectory_execution_identifier(
    *,
    run_id: str,
    runtime_version: str,
) -> str:
    """Deterministic runtime-4 execution identifier from run identity and runtime.

    Hash-derived from the canonical ``(run_id, runtime_version)``
    identity payload with the readable prefix
    ``adaptive-run-trajectory-execution-``; deliberately **not** derived
    from the content hash, which would be circular because the content
    hash covers the identifier itself. The distinct prefix and the
    ``4.0.0`` runtime literal guarantee runtime 4 never collides with
    the historical runtime-2 (``run-trajectory-execution-``) or runtime-3
    (``realization-trajectory-execution-``) execution identifiers.
    """
    canonical = canonical_json(
        {
            "run_id": run_id,
            "runtime_version": runtime_version,
        }
    )
    return f"{_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def adaptive_run_trajectory_execution_content_hash(
    execution: AdaptiveRunTrajectoryExecution,
) -> str:
    """Canonical SHA-256 of the complete aggregate content, excluding content_hash.

    Serializes the complete aggregate in JSON mode, removes only the
    top-level ``content_hash`` field from the detached copy, and digests
    the canonical JSON of the remaining payload - every identity,
    provenance, evidence, and timestamp field. The recorded
    ``content_hash`` is never trusted or incorporated; the aggregate is
    never mutated.
    """
    payload = execution.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def adaptive_run_input_hash(
    *,
    run_plan_id: str,
    run_plan_input_hash: str,
    campaign_id: str,
    world_version_id: str,
    world_content_hash: str,
    scenario_seed_id: str,
    seed_content_hash_value: str,
    world_realization_id: str,
    world_realization_content_hash: str,
    adaptive_policy_identifier: str,
    adaptive_policy_content_hash: str,
    trajectory_plan_set_hash: str,
    external_observation_input_bundle_id: str | None,
    external_observation_input_bundle_content_hash: str | None,
    final_decision_step: int,
    runtime_version: Literal["4.0.0"] = RUNTIME_VERSION_LITERAL,
) -> str:
    """The frozen runtime-4 input digest over the exact immutable run inputs.

    Canonical SHA-256 over exactly the immutable inputs that can affect
    one adaptive run: the run-plan identity and its already-authoritative
    recorded input hash, the campaign identity, the world identity and
    content hash, the scenario-seed identity and its recomputed content
    hash, the world-realization identity and content hash, the
    adaptive-policy identifier and content hash, the exact
    trajectory-plan-set hash, the optional external-input bundle
    identifier/content-hash pair (both present or both absent), the exact
    causal run horizon ``final_decision_step`` - the zero-based final
    decision step of the run, so the covered decision count is exactly
    ``final_decision_step + 1`` - and the runtime literal ``4.0.0`` - and
    nothing else. No wall-clock timestamp beyond the already-authoritative
    run-plan provenance, no mutable store order, no policy decision, no
    observation output, no strategy/branch count, no global RNG state, and
    no process data can enter the digest. The bundle pair participates
    only when both members are supplied; a one-sided pair fails closed.
    ``final_decision_step`` must be an exact non-negative ``int``: bool,
    float, string, and negative inputs raise ``ValueError`` with a
    generic diagnostic; no coercion is attempted. This is application-
    level runtime-4 identity logic only - historical runtimes never call
    this helper and are unaffected.
    """
    if type(final_decision_step) is not int or final_decision_step < 0:
        raise ValueError("final_decision_step must be an exact non-negative integer")
    if (external_observation_input_bundle_id is None) != (
        external_observation_input_bundle_content_hash is None
    ):
        raise ValueError("external bundle provenance must be both present or both absent")
    return sha256_hex(
        canonical_json(
            {
                "domain": "kalhas-adaptive-run-input-v1",
                "runtime_version": runtime_version,
                "run_plan_id": run_plan_id,
                "run_plan_input_hash": run_plan_input_hash,
                "campaign_id": campaign_id,
                "world_version_id": world_version_id,
                "world_content_hash": world_content_hash,
                "scenario_seed_id": scenario_seed_id,
                "seed_content_hash": seed_content_hash_value,
                "world_realization_id": world_realization_id,
                "world_realization_content_hash": world_realization_content_hash,
                "adaptive_policy_identifier": adaptive_policy_identifier,
                "adaptive_policy_content_hash": adaptive_policy_content_hash,
                "trajectory_plan_set_hash": trajectory_plan_set_hash,
                "external_observation_input_bundle_id": external_observation_input_bundle_id,
                "external_observation_input_bundle_content_hash": (
                    external_observation_input_bundle_content_hash
                ),
                "final_decision_step": final_decision_step,
            }
        )
    )


def verify_adaptive_run_trajectory_execution_identity(
    execution: object,
) -> None:
    """Verify an aggregate's exact type, identifier, and content hash.

    Verifies the record is an exact :class:`AdaptiveRunTrajectoryExecution`
    (never a validator-bypassed subclass or ``model_construct`` forgery),
    passes detached strict revalidation (every contract validator re-run
    over the record's own serialization), carries the exact runtime
    literal, that its identifier matches the independent derivation from
    the canonical identity payload, and that its content hash matches the
    recomputed canonical digest. Deterministic-identity mismatches are
    checked before hash checks. The record is never repaired, normalized,
    or silently accepted; any mismatch raises ``ValueError`` so the store
    converts it to the safe typed error without exposing hashes or
    identifiers.
    """
    if type(execution) is not AdaptiveRunTrajectoryExecution:
        raise ValueError("execution violates its contract")
    observed = execution
    _strictly_revalidate_detached(observed)
    if observed.runtime_version != RUNTIME_VERSION_LITERAL:
        raise ValueError("execution runtime mismatch")
    if observed.identifier != adaptive_run_trajectory_execution_identifier(
        run_id=observed.run_id,
        runtime_version=observed.runtime_version,
    ):
        raise ValueError("execution identifier mismatch")
    if observed.content_hash != adaptive_run_trajectory_execution_content_hash(observed):
        raise ValueError("execution content hash mismatch")


def _strictly_revalidate_detached(artifact: AdaptiveRunTrajectoryExecution) -> None:
    """Re-run every contract validator over the artifact's own serialization.

    The artifact's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance is rejected before any field of it is trusted. The
    revalidation result is discarded; the artifact is never replaced,
    repaired, or mutated. Any failure raises ``ValueError``.
    """
    import warnings

    from pydantic import ValidationError

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        AdaptiveRunTrajectoryExecution.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("artifact failed detached strict revalidation") from None


__all__ = [
    "RUNTIME_VERSION_LITERAL",
    "adaptive_run_input_hash",
    "adaptive_run_trajectory_execution_content_hash",
    "adaptive_run_trajectory_execution_identifier",
    "verify_adaptive_run_trajectory_execution_identity",
]
