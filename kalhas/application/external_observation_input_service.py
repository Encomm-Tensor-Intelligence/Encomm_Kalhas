"""Deterministic external-observation-input authoring service (H28-S06B1).

Accepts and persists the immutable :class:`ExternalObservationInputBundle`
authority for one exactly-COMPILED campaign of one verified compiled world
and one exact scenario seed of the campaign's shared seed ensemble (ADR-004
D28-04: the bundle is strategy-independent and bound to the campaign, world,
and scenario seed, so every compared strategy receives the same ordered
external inputs). This is the authoring boundary only: an application-local
untrusted bundle draft plus authoritative construction from verified stored
records, deterministic identity/hash computation, strict final revalidation,
and one no-overwrite immutable store write. No observation-event generation,
no adaptive trajectory execution, no replay, no campaign integration, no API,
no adapters/NEXUS/LEGION calls, no network/provider/live effects, and no
domain logic live here.

Two application-local frozen authoring inputs are the only caller-owned
data: one :class:`ExternalObservationInputValueDraft` per accepted external
value (``observation_id``, ``source_step_index``, and the exact ``value``)
and one :class:`ExternalObservationInputBundleDraft` carrying a non-empty
tuple of value drafts plus the deterministic timezone-aware ``accepted_at``.
The caller never supplies tenant/campaign/scenario/world/seed identities or
hashes, declaration identifiers or content hashes, the external channel, the
value kind, a unit, runtime/schema versions, authority identifiers or
hashes, metadata, or provider/network configuration. Every authoritative
value - declaration identity and content hash, observation id, external
channel, value kind, and unit - is copied from the verified stored
declaration; the campaign/scenario/world identity and hashes and the
scenario-seed identity and content hash are copied from the verified stored
campaign, world, and seed authorities.

Acceptance is deterministic and atomic, in this exact order:

1. detachedly strict-revalidate the bundle draft and every nested value
   draft (wrong types, subclasses, bool-as-int, coercion, NaN/Infinity,
   malformed tuples, duplicate coordinates, validator-bypassed or
   uninitialized instances, and timezone-naive timestamps are rejected
   before any field is trusted; the draft is never sorted or repaired);
2. load the exact tenant-scoped campaign and require its status to be
   exactly ``COMPILED``;
3. load the exact stored :class:`AdaptivePolicy` and verify the campaign,
   policy, scenario, and world identities and hashes agree exactly;
4. load and verify the scenario, the compiled world, and the world manifest
   (``verify_world_snapshot``) - a missing or corrupt world is rejected;
5. locate the exact :class:`ScenarioSeed` in ``campaign.seed_ensemble`` and
   compute its content hash with the established seed helper;
6. for every draft entry, require the ``observation_id`` to be an exact
   binding of the stored adaptive policy, load the corresponding stored
   :class:`RuntimeObservationDeclaration`, require it to be runtime
   ``4.0.0`` with matching tenant/scenario/world/hash provenance, require
   its source to be exactly :class:`ExternalObservationSource` (state-field
   declarations are rejected), copy every authoritative declaration field,
   require the value to exactly match the declared integer/number kind, and
   require the source step to satisfy the declaration cadence
   (``step >= start_step`` and ``(step - start_step) % every_n_steps == 0``;
   ``delay_steps`` is preserved by the declaration but does not change the
   bundle source coordinate; no fresh noise is applied);
7. require the draft entry ordering to be exactly the canonical
   ``(source_step_index, runtime_observation_declaration_id)`` order and
   reject duplicates - the caller's order is never sorted or repaired;
8. build the exact immutable entries and the bundle (runtime ``4.0.0``),
   detachedly strict-revalidate the completed bundle, and independently
   re-verify every identifier and content hash against the recomputed
   digests;
9. persist exactly once through the store's no-overwrite surface (a
   duplicate raises the typed already-exists error and never overwrites the
   original; any failure causes zero writes and no activity event).

The module is pure application logic: no FastAPI, no NEXUS/LEGION imports,
no wall clock, randomness, network, providers, filesystem, or database
access. Public messages never expose internal reasons, hashes, identities,
channels, values, steps, units, or validator diagnostics.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    ScenarioNotFoundError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.external_observation_input_errors import (
    ExternalObservationInputIntegrityError,
    ExternalObservationInputValidationError,
)
from kalhas.application.external_observation_input_identity import (
    external_observation_input_bundle_content_hash,
    external_observation_input_bundle_identifier,
    external_observation_input_entry_content_hash,
    external_observation_input_entry_identifier,
    verify_external_observation_input_bundle_identity,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationInputEntry,
    ExternalObservationSource,
    RuntimeObservationDeclaration,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION, AwareDatetime
from kalhas.contracts.v1.world import WorldVersion

_PLACEHOLDER_HASH = "0" * 64

#: The exact runtime literal of this authoring surface.
RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` (booleans rejected)."""
    if type(value) is bool:
        return False
    if type(value) is int:
        return True
    if type(value) is float:
        return value == value and value not in (float("inf"), float("-inf"))
    return False


@dataclass(frozen=True, kw_only=True)
class ExternalObservationInputValueDraft:
    """One application-local untrusted external input value.

    Carries only the logical ``observation_id``, the non-negative integer
    ``source_step_index``, and the exact finite ``value``. No authoritative
    provenance is accepted here: the declaration identity and content hash,
    the external channel, the value kind, and the unit are copied by the
    service from the verified stored declaration.
    """

    observation_id: str
    source_step_index: int
    value: int | float


@dataclass(frozen=True, kw_only=True)
class ExternalObservationInputBundleDraft:
    """The application-local caller-owned authoring input of one bundle.

    Carries a non-empty tuple of exact value drafts and the deterministic
    timezone-aware ``accepted_at``. No tenant/campaign/scenario/world/seed
    identity or hash, declaration identifier or hash, channel, value kind,
    unit, runtime/schema version, metadata, or provider configuration is
    accepted here.
    """

    entries: tuple[ExternalObservationInputValueDraft, ...]
    accepted_at: AwareDatetime


def _strictly_revalidate_draft(draft: ExternalObservationInputBundleDraft) -> None:
    """Validate every caller-owned authoring input; raises ``ValueError``.

    Enforces the exact bundle-draft and value-draft types (subclasses and
    uninitialized instances rejected), the non-empty tuple of entries, the
    non-empty string observation ids, the exact non-negative integer steps
    (floats, strings, and booleans are rejected before any coercion), the
    exact finite values (booleans, NaN, and Infinity rejected), duplicate
    ``(observation_id, source_step_index)`` coordinate rejection, and the
    timezone-aware ``accepted_at``. Nothing is repaired, coerced, sorted, or
    normalized. Attribute/type access on a forged object raises ``ValueError``
    so the caller maps it to the safe typed error.
    """

    if type(draft) is not ExternalObservationInputBundleDraft:
        raise ValueError("draft must be a valid ExternalObservationInputBundleDraft")

    entries = draft.entries
    if not isinstance(entries, tuple) or not entries:
        raise ValueError("entries must be a non-empty tuple of value drafts")
    if not all(type(entry) is ExternalObservationInputValueDraft for entry in entries):
        raise ValueError("entries must contain only exact ExternalObservationInputValueDraft")

    seen: set[tuple[str, int]] = set()
    for entry in entries:
        if not isinstance(entry.observation_id, str) or not entry.observation_id:
            raise ValueError("observation_id must be a non-empty string")
        step = entry.source_step_index
        if type(step) is not int or step < 0:
            raise ValueError("source_step_index must be an exact non-negative integer")
        value = entry.value
        if type(value) not in (int, float) or type(value) is bool:
            raise ValueError("value must be an exact finite int or float")
        if type(value) is float and not _is_exact_finite_numeric(value):
            raise ValueError("value must be an exact finite int or float")
        coordinate = (entry.observation_id, step)
        if coordinate in seen:
            raise ValueError(
                "duplicate (observation_id, source_step_index) coordinates are rejected"
            )
        seen.add(coordinate)

    accepted_at = draft.accepted_at
    if (
        not isinstance(accepted_at, datetime)
        or accepted_at.tzinfo is None
        or accepted_at.utcoffset() is None
    ):
        raise ValueError("accepted_at must be a timezone-aware datetime")


def _load_verified_world_authority(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    world_version_id: str,
) -> WorldVersion:
    """Load and verify the tenant's exact scenario/world/manifest authority."""
    try:
        store.get_scenario(tenant_id, scenario_id)
    except ScenarioNotFoundError as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="scenario authority missing"
        ) from exc
    try:
        world = store.get_world(tenant_id, world_version_id)
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="world authority missing"
        ) from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise ExternalObservationInputIntegrityError(
            tenant_id, campaign_id, reason="world authority corrupt"
        ) from exc
    if world.tenant_id != tenant_id or world.source_scenario_id != scenario_id:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
        )
    return world


def accept_external_observation_input_bundle(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    draft: ExternalObservationInputBundleDraft,
) -> ExternalObservationInputBundle:
    """Accept one immutable external observation input bundle; raises typed errors.

    Runs the exact deterministic authoring flow; the returned object is a
    detached immutable deep copy. A duplicate locality raises the typed
    already-exists error and never overwrites the original; every other
    failure is atomic with zero writes and no activity event.
    """
    try:
        _strictly_revalidate_draft(draft)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="draft invalid"
        ) from exc

    # 1. Campaign authority.
    try:
        campaign = store.get_campaign(tenant_id, campaign_id)
        status = store.get_campaign_status(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="campaign authority missing"
        ) from exc
    if status.state is not CampaignState.COMPILED:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="campaign must be exactly COMPILED"
        )

    scenario_id = campaign.scenario_id
    world_version_id = campaign.world_version_id
    world = _load_verified_world_authority(
        store,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
    )
    if (
        scenario_id != campaign.scenario_id
        or world.identifier != campaign.world_version_id
        or world.source_scenario_id != scenario_id
        or world.tenant_id != tenant_id
    ):
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
        )
    world_content_hash = world.content_hash

    # 2. Adaptive-policy authority.
    try:
        policy = store.get_adaptive_policy(tenant_id, campaign_id)
    except AdaptivePolicyNotFoundError as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="adaptive policy authority missing"
        ) from exc
    except AdaptivePolicyIntegrityError as exc:
        raise ExternalObservationInputIntegrityError(
            tenant_id, campaign_id, reason="adaptive policy authority corrupt"
        ) from exc
    if (
        policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != scenario_id
        or policy.world_version_id != world_version_id
        or policy.world_content_hash != world_content_hash
    ):
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="campaign/policy/scenario/world identity mismatch"
        )

    # 3. Scenario-seed authority.
    seed = next(
        (seed for seed in campaign.seed_ensemble if seed.identifier == scenario_seed_id),
        None,
    )
    if seed is None:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="scenario seed authority missing"
        )
    if seed.tenant_id != tenant_id:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="scenario seed tenant mismatch"
        )
    seed_hash = seed_content_hash(seed)

    # 4. Entry/declaration authority, in draft order.
    bindings_by_observation = {
        binding.observation_id: binding for binding in policy.observation_bindings
    }
    resolved: list[
        tuple[int, str, ExternalObservationInputValueDraft, RuntimeObservationDeclaration]
    ] = []
    for value_draft in draft.entries:
        binding = bindings_by_observation.get(value_draft.observation_id)
        if binding is None:
            raise ExternalObservationInputValidationError(
                tenant_id,
                campaign_id,
                reason="undeclared or policy-unused observation",
            )
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, scenario_id, world_version_id, value_draft.observation_id
            )
        except RuntimeObservationDeclarationNotFoundError as exc:
            raise ExternalObservationInputValidationError(
                tenant_id,
                campaign_id,
                reason="observation declaration authority missing",
            ) from exc
        except RuntimeObservationDeclarationIntegrityError as exc:
            raise ExternalObservationInputIntegrityError(
                tenant_id,
                campaign_id,
                reason="observation declaration authority corrupt",
            ) from exc
        if (
            declaration.runtime_version != RUNTIME_VERSION
            or declaration.tenant_id != tenant_id
            or declaration.scenario_id != scenario_id
            or declaration.world_version_id != world_version_id
            or declaration.world_content_hash != world_content_hash
        ):
            raise ExternalObservationInputValidationError(
                tenant_id,
                campaign_id,
                reason="observation declaration authority mismatch",
            )
        if not isinstance(declaration.observation_source, ExternalObservationSource):
            raise ExternalObservationInputValidationError(
                tenant_id,
                campaign_id,
                reason="state-field observations are rejected",
            )
        if (
            binding.runtime_observation_declaration_id != declaration.identifier
            or binding.runtime_observation_declaration_content_hash != declaration.content_hash
            or binding.observed_value_kind != declaration.observed_value_kind
            or binding.unit != declaration.unit
        ):
            raise ExternalObservationInputIntegrityError(
                tenant_id, campaign_id, reason="policy binding disagrees with stored declaration"
            )

        value_kind = declaration.observed_value_kind
        value = value_draft.value
        if value_kind == "integer":
            if type(value) is not int:
                raise ExternalObservationInputValidationError(
                    tenant_id, campaign_id, reason="value must exactly match the declared kind"
                )
        elif not _is_exact_finite_numeric(value):
            raise ExternalObservationInputValidationError(
                tenant_id, campaign_id, reason="value must exactly match the declared kind"
            )

        timing = declaration.timing
        step = value_draft.source_step_index
        if step < timing.start_step or (step - timing.start_step) % timing.every_n_steps != 0:
            raise ExternalObservationInputValidationError(
                tenant_id, campaign_id, reason="source step is not scheduled by the declaration"
            )
        resolved.append((step, declaration.identifier, value_draft, declaration))

    # 5. Canonical ordering and unique coordinates (never sorted or repaired).
    ordering = [(step, declaration_id) for step, declaration_id, _, _ in resolved]
    if ordering != sorted(ordering):
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="entries are not in canonical order"
        )
    coordinates = [(declaration_id, step) for step, declaration_id, _, _ in resolved]
    if len(coordinates) != len(set(coordinates)):
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="duplicate coordinates are rejected"
        )

    # 6. Build exact entries from verified authorities.
    entries: list[ExternalObservationInputEntry] = []
    for step, declaration_id, value_draft, declaration in resolved:
        source = declaration.observation_source
        if not isinstance(source, ExternalObservationSource):
            raise ExternalObservationInputIntegrityError(
                tenant_id, campaign_id, reason="state-field observations are rejected"
            )
        identifier = external_observation_input_entry_identifier(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            runtime_observation_declaration_id=declaration_id,
            source_step_index=step,
        )
        placeholder = ExternalObservationInputEntry(
            identifier=identifier,
            runtime_observation_declaration_id=declaration_id,
            runtime_observation_declaration_content_hash=declaration.content_hash,
            observation_id=value_draft.observation_id,
            external_channel_id=source.external_channel_id,
            source_step_index=step,
            value_kind=declaration.observed_value_kind,
            unit=declaration.unit,
            value=value_draft.value,
            content_hash=_PLACEHOLDER_HASH,
        )
        digest = external_observation_input_entry_content_hash(placeholder)
        entries.append(placeholder.model_copy(update={"content_hash": digest}))

    # 7. Build the bundle and compute its deterministic identity/hash.
    bundle_identifier = external_observation_input_bundle_identifier(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        scenario_seed_id=scenario_seed_id,
        runtime_version=RUNTIME_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    placeholder_bundle = ExternalObservationInputBundle(
        identifier=bundle_identifier,
        tenant_id=tenant_id,
        schema_version=SCHEMA_VERSION,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        world_version_id=world_version_id,
        world_content_hash=world_content_hash,
        scenario_seed_id=scenario_seed_id,
        seed_content_hash=seed_hash,
        runtime_version=RUNTIME_VERSION,
        entries=tuple(entries),
        content_hash=_PLACEHOLDER_HASH,
        accepted_at=draft.accepted_at,
    )
    bundle = placeholder_bundle.model_copy(
        update={"content_hash": external_observation_input_bundle_content_hash(placeholder_bundle)}
    )

    # 8. Detached strict final revalidation with independent identity/hash checks.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = bundle.model_dump(mode="python")
        revalidated = ExternalObservationInputBundle.model_validate(serialized, strict=True)
        verify_external_observation_input_bundle_identity(
            revalidated,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=scenario_id,
            world_version_id=world_version_id,
            scenario_seed_id=scenario_seed_id,
        )
    except (ValidationError, TypeError, ValueError, AttributeError) as exc:
        raise ExternalObservationInputValidationError(
            tenant_id, campaign_id, reason="bundle contradicts its contract"
        ) from exc

    # 9. One immutable no-overwrite store write; no operational activity.
    store.put_external_observation_input_bundle(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        bundle=bundle,
    )
    return bundle.model_copy(deep=True)


__all__ = [
    "ExternalObservationInputBundleDraft",
    "ExternalObservationInputValueDraft",
    "RUNTIME_VERSION",
    "accept_external_observation_input_bundle",
]
