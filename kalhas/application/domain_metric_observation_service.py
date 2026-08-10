"""Deterministic domain metric-observation declaration service.

A metric-observation binding is the immutable, tenant-scoped declarative
connection between exactly one metric of a stored ``ScenarioSpec`` and
exactly one numeric state field of an already-declared
``DomainStateModel`` - declaration, storage, and provenance only, never
behavior. Nothing here inspects a ``RunTrajectoryExecution``, reads
``initial_state`` or ``final_state``, extracts a metric value, evaluates
a trajectory, calculates an outcome, aggregates observations, produces
evidence, ranks strategies, or generates recommendations, and no
domain-pack code is ever loaded, imported, instantiated, invoked, or
interpreted.

Every identity field is copied exclusively from stored immutable records
- the scenario, the ``DomainPackBinding``, the registered
``DomainPackManifest``, and the declared ``DomainStateModel`` - never
from client input. The service requires ``metric_id`` to identify
exactly one metric of the stored scenario, verifies the stored binding
and manifest are exactly the records implied by the request (tenants,
scenario and manifest identifiers, deterministic binding identifier)
with the binding snapshot matching the registered manifest, and verifies
the referenced state model's copied identity, deterministic identifier,
content hash, canonical field representation, and binding relationship
against the stored immutable records - any inconsistency raises a safe
typed integrity error. The referenced ``state_field_id`` must identify
an existing field of the exact state model whose declared
``StateValueKind`` is numeric (``integer`` or ``number``); string,
boolean, and json fields are rejected because only a numeric field can
ever be observed as a metric raw observation. The binding identifier and
content hash are deterministic, ``observation_point`` is exactly
``"final_state"``, and the Phase 19 MVP allows at most one binding per
scenario metric: a duplicate declaration - even pointing to a different
state model or field - is rejected and never overwrites the original.
"""

from __future__ import annotations

from typing import cast

from kalhas.application.domain_errors import (
    DomainMetricObservationIntegrityError,
    DomainMetricObservationMetricNotFoundError,
    DomainMetricObservationNonNumericFieldError,
    DomainMetricObservationStateFieldNotFoundError,
)
from kalhas.application.domain_pack_binding_service import binding_identifier
from kalhas.application.domain_state_model_service import (
    canonical_state_fields,
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.domain_pack import (
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.metric_observation import (
    DomainMetricObservationBinding,
    NumericStateFieldValueKind,
    ObservationPoint,
)
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel, StateValueKind

_OBSERVATION_ID_PREFIX = "observation-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64
_OBSERVATION_POINT: ObservationPoint = "final_state"
_NUMERIC_KINDS = (StateValueKind.INTEGER, StateValueKind.NUMBER)


def domain_metric_observation_identifier(
    *,
    tenant_id: str,
    scenario_id: str,
    metric_id: str,
    manifest_id: str,
    state_model_id: str,
    state_field_id: str,
    observation_point: str,
) -> str:
    """Deterministic, collision-safe observation-binding identifier.

    Hash-derived from the canonical identity tuple (tenant, scenario,
    metric, manifest, state model, state field, observation point), so
    user-provided delimiter characters cannot create ambiguity and
    identical inputs always yield the same identifier. Never random,
    never wall-clock.
    """
    canonical = canonical_json(
        {
            "tenant_id": tenant_id,
            "scenario_id": scenario_id,
            "metric_id": metric_id,
            "manifest_id": manifest_id,
            "state_model_id": state_model_id,
            "state_field_id": state_field_id,
            "observation_point": observation_point,
        }
    )
    return f"{_OBSERVATION_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def domain_metric_observation_content_hash(binding: DomainMetricObservationBinding) -> str:
    """Canonical SHA-256 of the binding content, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, so equivalent bindings always produce the
    same lowercase 64-character digest.
    """
    payload = binding.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _verify_binding_integrity(
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
) -> None:
    """Raise a safe typed integrity error when stored records are inconsistent.

    Verifies that the stored binding and manifest are exactly the records
    implied by the request - binding tenant matches the requested tenant,
    manifest tenant matches the requested tenant, binding scenario and
    manifest identifiers match the request, and the binding identifier
    matches its deterministic derivation - and that the binding snapshot
    exactly matches the registered manifest: logical pack id, semantic
    pack version, authoritative content hash, and the exact ordered
    capability identifier set. On any mismatch the raised error carries a
    generic public message and an internal ``reason`` for diagnostics
    only - raw hashes and internal details are never exposed.
    """
    if binding.tenant_id != tenant_id:
        reason = "binding tenant mismatch"
    elif manifest.tenant_id != tenant_id:
        reason = "manifest tenant mismatch"
    elif binding.scenario_id != scenario_id:
        reason = "binding scenario mismatch"
    elif binding.manifest_id != manifest_id:
        reason = "binding manifest mismatch"
    elif binding.identifier != binding_identifier(scenario_id=scenario_id, manifest_id=manifest_id):
        reason = "binding identifier mismatch"
    elif binding.pack_id != manifest.pack_id:
        reason = "pack_id mismatch"
    elif binding.pack_version != manifest.pack_version:
        reason = "pack_version mismatch"
    elif binding.manifest_content_hash != manifest.content_hash:
        reason = "manifest content hash mismatch"
    elif binding.capability_ids != tuple(
        capability.identifier for capability in manifest.capabilities
    ):
        reason = "capability identifier set mismatch"
    else:
        return
    raise DomainMetricObservationIntegrityError(tenant_id, scenario_id, manifest_id, reason=reason)


def _verify_state_model_integrity(
    state_model: DomainStateModel,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
) -> None:
    """Verify the stored state model against the stored immutable records.

    The referenced state model must carry the copied identity implied by
    the request (tenant, scenario, manifest, binding relationship), its
    deterministic identifier must match the derivation from the canonical
    scenario/manifest/state-model identity, its ``content_hash`` must
    match the recomputed canonical digest, its pack identity and manifest
    content hash must match the binding and registered manifest, and its
    state fields must be canonicalized by identifier. On any mismatch a
    safe typed integrity error is raised with a generic public message
    and an internal ``reason`` for diagnostics only.
    """
    if state_model.tenant_id != tenant_id:
        reason = "state model tenant mismatch"
    elif state_model.scenario_id != scenario_id:
        reason = "state model scenario mismatch"
    elif state_model.manifest_id != manifest_id:
        reason = "state model manifest mismatch"
    elif state_model.binding_id != binding.identifier:
        reason = "state model binding relationship mismatch"
    elif state_model.identifier != state_model_identifier(
        scenario_id=scenario_id, manifest_id=manifest_id, state_model_id=state_model_id
    ):
        reason = "state model identifier mismatch"
    elif state_model.content_hash != state_model_content_hash(state_model):
        reason = "state model content hash mismatch"
    elif state_model.pack_id != binding.pack_id:
        reason = "state model pack_id mismatch"
    elif state_model.pack_version != binding.pack_version:
        reason = "state model pack_version mismatch"
    elif state_model.manifest_content_hash != manifest.content_hash:
        reason = "state model manifest content hash mismatch"
    elif state_model.state_fields != canonical_state_fields(state_model.state_fields):
        reason = "state model fields not canonical"
    else:
        return
    raise DomainMetricObservationIntegrityError(tenant_id, scenario_id, manifest_id, reason=reason)


def _resolve_numeric_field(
    state_model: DomainStateModel,
    *,
    state_field_id: str,
) -> StateValueKind:
    """Resolve a state field and require its value kind to be numeric.

    The field identifier must identify an existing field of the exact
    state model; missing fields raise a typed not-found error. Only
    ``integer`` and ``number`` fields may be observed as a metric raw
    observation: ``string``, ``boolean``, and ``json`` fields raise a
    typed non-numeric error. The authoritative kind is read from the
    stored state model - never from client input.
    """
    for field in state_model.state_fields:
        if field.identifier == state_field_id:
            if field.value_kind not in _NUMERIC_KINDS:
                raise DomainMetricObservationNonNumericFieldError(
                    state_model.state_model_id,
                    state_field_id,
                    reason=(
                        f"state field {state_field_id!r} has non-numeric value kind "
                        f"{field.value_kind.value!r}"
                    ),
                )
            return field.value_kind
    raise DomainMetricObservationStateFieldNotFoundError(
        state_model.state_model_id,
        state_field_id,
        reason=f"state field {state_field_id!r} does not exist in the state model",
    )


def build_domain_metric_observation(
    *,
    tenant_id: str,
    scenario_id: str,
    binding: DomainPackBinding,
    manifest: DomainPackManifest,
    state_model: DomainStateModel,
    metric_id: str,
    state_field_id: str,
    state_field_value_kind: StateValueKind,
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainMetricObservationBinding:
    """Build a binding from verified stored records (never from client input).

    All identity fields (binding id, manifest id, logical ``pack_id``,
    semantic ``pack_version``, authoritative manifest content hash, the
    referenced state model's deterministic identifier and authoritative
    content hash, and the copied numeric field value kind) are copied
    from the stored immutable binding, manifest, and state model. The
    binding identifier is deterministically derived from the canonical
    tenant/scenario/metric/manifest/state-model/state-field/observation-
    point identity tuple, ``observation_point`` is exactly
    ``"final_state"``, and the binding content hash is computed over the
    canonical serialized binding content excluding ``content_hash``
    itself.
    """
    if metadata is None:
        metadata = {}
    binding_contract = DomainMetricObservationBinding(
        identifier=domain_metric_observation_identifier(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            metric_id=metric_id,
            manifest_id=manifest.identifier,
            state_model_id=state_model.state_model_id,
            state_field_id=state_field_id,
            observation_point=_OBSERVATION_POINT,
        ),
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding_id=binding.identifier,
        manifest_id=manifest.identifier,
        pack_id=manifest.pack_id,
        pack_version=manifest.pack_version,
        manifest_content_hash=manifest.content_hash,
        metric_id=metric_id,
        state_model_identifier=state_model.identifier,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        state_field_id=state_field_id,
        state_field_value_kind=cast(NumericStateFieldValueKind, state_field_value_kind.value),
        observation_point=_OBSERVATION_POINT,
        content_hash=_PLACEHOLDER_HASH,
        declared_at=declared_at,
        metadata=metadata,
    )
    digest = domain_metric_observation_content_hash(binding_contract)
    return binding_contract.model_copy(update={"content_hash": digest})


def declare_domain_metric_observation(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    manifest_id: str,
    state_model_id: str,
    metric_id: str,
    state_field_id: str,
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> DomainMetricObservationBinding:
    """Declare an immutable observation binding; raises typed errors.

    The tenant must own the scenario (404 otherwise) and ``metric_id``
    must identify exactly one metric of the stored scenario (typed 422
    otherwise). The manifest must already be bound to that exact scenario
    (404 otherwise) and the referenced state model must exist (404
    otherwise). The stored binding and manifest must be exactly the
    records implied by the request (binding/manifest tenant, binding
    scenario and manifest identifiers, deterministic binding identifier)
    with the binding snapshot exactly matching the registered manifest,
    and the stored state model must carry its verified copied identity,
    deterministic identifier, content hash, canonical fields, and binding
    relationship - any inconsistency raises a safe typed 409 integrity
    error. ``state_field_id`` must identify an existing field of the
    exact state model whose declared value kind is numeric (typed 422
    otherwise); string, boolean, and json fields are rejected. Duplicate
    bindings for the same tenant/scenario/metric raise a typed 409 and
    never overwrite the original. The binding is declarative data only:
    nothing is inspected, extracted, evaluated, aggregated, or executed,
    and no domain pack is ever loaded or invoked.
    """
    scenario = store.get_scenario(tenant_id, scenario_id)
    matching_metrics = [metric for metric in scenario.metrics if metric.identifier == metric_id]
    if len(matching_metrics) != 1:
        raise DomainMetricObservationMetricNotFoundError(
            scenario_id,
            metric_id,
            reason=(
                f"metric {metric_id!r} is declared {len(matching_metrics)} times by the "
                "scenario; exactly one declaration is required"
            ),
        )
    binding = store.get_domain_pack_binding(tenant_id, scenario_id, manifest_id)
    manifest = store.get_domain_pack_manifest(tenant_id, manifest_id)
    state_model = store.get_domain_state_model(tenant_id, scenario_id, manifest_id, state_model_id)
    _verify_binding_integrity(
        binding,
        manifest,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
    )
    _verify_state_model_integrity(
        state_model,
        binding,
        manifest,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        manifest_id=manifest_id,
        state_model_id=state_model_id,
    )
    value_kind = _resolve_numeric_field(state_model, state_field_id=state_field_id)
    observation = build_domain_metric_observation(
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        binding=binding,
        manifest=manifest,
        state_model=state_model,
        metric_id=metric_id,
        state_field_id=state_field_id,
        state_field_value_kind=value_kind,
        declared_at=declared_at,
        metadata=metadata,
    )
    store.put_domain_metric_observation(tenant_id, scenario_id, metric_id, observation)
    return observation


def get_domain_metric_observation(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
    metric_id: str,
) -> DomainMetricObservationBinding:
    """Fetch one observation binding; raises DomainMetricObservationNotFoundError."""
    return store.get_domain_metric_observation(tenant_id, scenario_id, metric_id)


def list_domain_metric_observations(
    store: InMemoryScenarioStore, tenant_id: str, scenario_id: str
) -> tuple[DomainMetricObservationBinding, ...]:
    """List a scenario's observation bindings in deterministic metric-id order.

    Verifies the tenant owns the scenario first: unknown or foreign
    scenarios raise the existing typed 404 (ScenarioNotFoundError).
    """
    store.get_scenario(tenant_id, scenario_id)
    return store.list_domain_metric_observations(tenant_id, scenario_id)
