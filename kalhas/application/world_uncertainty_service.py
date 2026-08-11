"""Deterministic world-uncertainty model declaration service (Phase 24).

A ``WorldUncertaintyModel`` is the immutable, tenant-scoped declarative
connection between the initial-state fields of a scenario's registered
domain state models and their exact distribution specifications, with
every authoritative provenance field (scenario, source
``DomainPackBinding`` identifier, manifest, pack identity, manifest
content hash, deterministic state-model identifier, logical
state-model id, state-model content hash, target state-field id, and
the copied field value kind) copied exclusively from stored immutable
records - never from client input. Declaration, storage, and
provenance only: nothing here samples, evaluates, aggregates, scores,
ranks, or recommends, and no domain-pack code is ever loaded, imported,
instantiated, invoked, or interpreted.

The caller supplies only ``manifest_id``, ``state_model_id``,
``state_field_id``, the ``distribution`` specification, the integer
``rounding_policy`` (when applicable), the independently optional
``lower_bound``/``upper_bound``, plus the deterministic ``declared_at``
and optional ``metadata``. Bindings are canonicalized into the exact
``(manifest_id, state_model_id, state_field_id)`` target-tuple order -
caller declaration order never affects the artifact. At least one
binding is required; only ``integer`` and ``number`` initial-state
fields may be targeted; each complete target tuple appears exactly
once. The model must be declared before any world is compiled for the
tenant/scenario, exactly one model may exist per tenant/scenario, and
there is no update, replace, delete, or repair surface.

The model identifier is independently derived from the canonical
tenant/scenario/scenario-hash identity - never from the content hash -
and the content hash covers the complete canonical model serialization
excluding ``content_hash`` itself. ``declared_at`` is the
deterministic caller-supplied timestamp and is included in content
hashing; no wall clock is ever read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from kalhas.application.deterministic_sampler import (
    QUANTIZATION_FRACTION_BITS,
    QUANTIZATION_POLICY,
    SAMPLER_VERSION,
    canonical_json_text,
    discrete_static_final_values,
    validate_effective_parameters,
)
from kalhas.application.domain_errors import (
    DomainPackBindingNotFoundError,
    DomainStateModelNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_identity import scenario_content_hash
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyAllowedValuesError,
    WorldUncertaintyBoundRuleError,
    WorldUncertaintyDiscreteValueKindError,
    WorldUncertaintyDistributionParameterError,
    WorldUncertaintyModelDeclarationAfterCompilationError,
    WorldUncertaintyModelValidationError,
    WorldUncertaintyRoundingPolicyRuleError,
    WorldUncertaintyUnknownManifestError,
    WorldUncertaintyUnknownStateFieldError,
    WorldUncertaintyUnknownStateModelError,
    WorldUncertaintyUnsupportedFieldKindError,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_binding_content_hash,
    uncertainty_binding_identifier,
    uncertainty_model_content_hash,
    uncertainty_model_identifier,
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.domain_pack import DomainPackBinding
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    DistributionSpecification,
    StateFieldUncertaintyBinding,
    WorldUncertaintyModel,
)

_PLACEHOLDER_HASH = "0" * 64


@dataclass(frozen=True)
class UncertaintyBindingDraft:
    """The caller-owned values of one uncertainty binding.

    Only ``manifest_id``, ``state_model_id``, ``state_field_id``, the
    ``distribution`` specification, the ``rounding_policy``, and the
    independently optional clipping bounds are caller-owned; every
    authoritative provenance field is copied by the service from stored
    immutable records.
    """

    manifest_id: str
    state_model_id: str
    state_field_id: str
    distribution: DistributionSpecification
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = None
    lower_bound: int | float | None = None
    upper_bound: int | float | None = None


def _resolve_state_model(
    store: InMemoryScenarioStore,
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
) -> DomainStateModel:
    """Fetch the referenced state model; raises typed 422 errors."""
    try:
        return store.get_domain_state_model(
            scenario.tenant_id,
            scenario.identifier,
            draft.manifest_id,
            draft.state_model_id,
        )
    except DomainStateModelNotFoundError as exc:
        raise WorldUncertaintyUnknownStateModelError(
            scenario.identifier,
            draft.manifest_id,
            draft.state_model_id,
            reason="state model does not exist for the scenario and manifest",
        ) from exc


def _resolve_binding(
    store: InMemoryScenarioStore,
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
) -> DomainPackBinding:
    """Fetch the referenced pack binding; raises typed 422 errors."""
    try:
        return store.get_domain_pack_binding(
            scenario.tenant_id, scenario.identifier, draft.manifest_id
        )
    except DomainPackBindingNotFoundError as exc:
        raise WorldUncertaintyUnknownManifestError(
            scenario.identifier,
            draft.manifest_id,
            reason="manifest is not bound to the scenario",
        ) from exc


def _resolve_field(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
    state_model: DomainStateModel,
) -> DomainStateFieldDefinition:
    """Resolve the target state field; raises typed 422 errors."""
    for field in state_model.state_fields:
        if field.identifier == draft.state_field_id:
            return field
    raise WorldUncertaintyUnknownStateFieldError(
        scenario.identifier,
        draft.manifest_id,
        draft.state_model_id,
        draft.state_field_id,
        reason="state field does not exist in the state model",
    )


def _validate_target_kind(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
    field: DomainStateFieldDefinition,
) -> None:
    """Only integer and number initial-state fields may be targeted."""
    if field.value_kind not in (StateValueKind.INTEGER, StateValueKind.NUMBER):
        raise WorldUncertaintyUnsupportedFieldKindError(
            scenario.identifier,
            draft.state_field_id,
            reason=f"field kind {field.value_kind.value!r} is not integer or number",
        )


def _validate_rounding_and_bounds(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
    field_kind: Literal["integer", "number"],
) -> None:
    """Enforce the rounding-policy and clipping-bound declaration rules."""
    if field_kind == "integer":
        if draft.rounding_policy is None:
            raise WorldUncertaintyRoundingPolicyRuleError(
                scenario.identifier,
                draft.state_field_id,
                reason="integer targets require a rounding policy",
            )
    elif draft.rounding_policy is not None:
        raise WorldUncertaintyRoundingPolicyRuleError(
            scenario.identifier,
            draft.state_field_id,
            reason="rounding policy is forbidden for number targets",
        )
    for label, bound in (("lower_bound", draft.lower_bound), ("upper_bound", draft.upper_bound)):
        if bound is None:
            continue
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            raise WorldUncertaintyBoundRuleError(
                scenario.identifier,
                draft.state_field_id,
                reason=f"{label} must be an exact int or float",
            )
        if field_kind == "integer" and not isinstance(bound, int):
            raise WorldUncertaintyBoundRuleError(
                scenario.identifier,
                draft.state_field_id,
                reason="integer targets require exact integer bounds",
            )
    if (
        draft.lower_bound is not None
        and draft.upper_bound is not None
        and draft.lower_bound > draft.upper_bound
    ):
        raise WorldUncertaintyBoundRuleError(
            scenario.identifier,
            draft.state_field_id,
            reason="lower_bound must not exceed upper_bound",
        )


def _validate_discrete_kind_agreement(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
    field_kind: Literal["integer", "number"],
) -> None:
    """Discrete values must agree with the target field kind."""
    if not isinstance(draft.distribution, DiscreteDistribution):
        return
    if field_kind == "integer":
        for value in draft.distribution.values:
            if not isinstance(value, int):
                raise WorldUncertaintyDiscreteValueKindError(
                    scenario.identifier,
                    draft.state_field_id,
                    reason="discrete values must be exact integers for integer targets",
                )


def _validate_effective_parameters(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
) -> None:
    """Validate the effective Q64.64 parameter domain of the distribution.

    Covers the vanishing rule, effective ordering, effectively positive
    deviations/sigmas, effective bound ordering, effective discrete
    mass, and the lognormal static finite-raw range check.
    """
    try:
        validate_effective_parameters(
            draft.distribution,
            lower_bound=draft.lower_bound,
            upper_bound=draft.upper_bound,
        )
    except ValueError as exc:
        raise WorldUncertaintyDistributionParameterError(
            scenario.identifier,
            draft.state_field_id,
            reason=str(exc),
        ) from None


def _validate_discrete_allowed_values(
    scenario: ScenarioSpec,
    draft: UncertaintyBindingDraft,
    field: DomainStateFieldDefinition,
    field_kind: Literal["integer", "number"],
) -> None:
    """Statistically prove every selectable discrete outcome is allowed.

    For every positive-probability support value the final value is
    computed statically (quantize -> clip -> round -> representation
    preservation) and compared canonically against ``allowed_values``.
    Zero-probability support values are unselectable and need not make
    the model unexecutable. Continuous distributions have no static
    guarantee and rely on per-seed complete-state validation.
    """
    if not isinstance(draft.distribution, DiscreteDistribution):
        return
    if not field.allowed_values:
        return
    try:
        final_values = discrete_static_final_values(
            draft.distribution,
            lower_bound=draft.lower_bound,
            upper_bound=draft.upper_bound,
            field_kind=field_kind,
            rounding_policy=draft.rounding_policy,
        )
    except ValueError as exc:
        raise WorldUncertaintyDistributionParameterError(
            scenario.identifier,
            draft.state_field_id,
            reason=str(exc),
        ) from None
    allowed = [_canonical_value_text_of(value) for value in field.allowed_values]
    for value in final_values:
        if _canonical_value_text_of(value) not in allowed:
            raise WorldUncertaintyAllowedValuesError(
                scenario.identifier,
                draft.state_field_id,
                reason="a selectable discrete final value is not among allowed_values",
            )


def _canonical_value_text_of(value: object) -> str:
    """Canonical JSON text of one value (equality domain for allowed checks)."""
    return canonical_json_text(value)


def _build_binding(
    *,
    scenario: ScenarioSpec,
    pack_binding: DomainPackBinding,
    state_model: DomainStateModel,
    field: DomainStateFieldDefinition,
    draft: UncertaintyBindingDraft,
    field_kind: Literal["integer", "number"],
) -> StateFieldUncertaintyBinding:
    """Build one canonical binding with copied authoritative provenance.

    Every provenance field is copied from the stored immutable records;
    the binding identifier is independently derived from the canonical
    target identity; the content hash covers the complete canonical
    binding serialization excluding itself.
    """
    identifier = uncertainty_binding_identifier(
        scenario_id=scenario.identifier,
        manifest_id=pack_binding.manifest_id,
        state_model_id=state_model.state_model_id,
        state_field_id=field.identifier,
    )
    placeholder = StateFieldUncertaintyBinding(
        identifier=identifier,
        scenario_id=scenario.identifier,
        binding_id=pack_binding.identifier,
        manifest_id=pack_binding.manifest_id,
        pack_id=pack_binding.pack_id,
        pack_version=pack_binding.pack_version,
        manifest_content_hash=pack_binding.manifest_content_hash,
        state_model_identifier=state_model.identifier,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        state_field_id=field.identifier,
        state_field_value_kind=field_kind,
        distribution=draft.distribution,
        rounding_policy=draft.rounding_policy,
        lower_bound=draft.lower_bound,
        upper_bound=draft.upper_bound,
        sampler_version=SAMPLER_VERSION,
        quantization_policy=QUANTIZATION_POLICY,
        quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
        content_hash=_PLACEHOLDER_HASH,
    )
    digest = uncertainty_binding_content_hash(placeholder)
    return placeholder.model_copy(update={"content_hash": digest})


def declare_world_uncertainty_model(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    bindings: tuple[UncertaintyBindingDraft, ...],
    declared_at: AwareDatetime,
    metadata: dict[str, JsonValue] | None = None,
) -> WorldUncertaintyModel:
    """Declare the immutable uncertainty model; raises typed errors.

    The tenant must own the scenario (typed 404 otherwise). The model
    must be declared before any world has been compiled for the
    tenant/scenario (typed 409 otherwise). At least one binding is
    required; every referenced manifest, state model, and state field
    must exist (typed 422 otherwise); only ``integer`` and ``number``
    initial-state fields may be targeted (typed 422); the rounding
    policy, bound, discrete-kind, effective-parameter, and discrete
    allowed-values rules are enforced (typed 422). Bindings are
    canonicalized into the exact ``(manifest_id, state_model_id,
    state_field_id)`` target-tuple order. A duplicate declaration
    raises a typed 409 and never overwrites the original. The model
    identifier is independently derived from the canonical
    tenant/scenario/scenario-hash identity and the content hash covers
    the complete canonical model excluding ``content_hash`` itself.
    Nothing is sampled, evaluated, aggregated, scored, ranked, or
    recommended, and no domain pack is ever loaded or invoked.
    """
    if metadata is None:
        metadata = {}
    scenario = store.get_scenario(tenant_id, scenario_id)
    if store.has_compiled_worlds_for_scenario(tenant_id, scenario_id):
        raise WorldUncertaintyModelDeclarationAfterCompilationError(tenant_id, scenario_id)
    if not bindings:
        raise WorldUncertaintyModelValidationError(
            scenario.identifier, reason="at least one binding is required"
        )

    seen_targets: set[tuple[str, str, str]] = set()
    resolved: list[
        tuple[
            UncertaintyBindingDraft,
            DomainPackBinding,
            DomainStateModel,
            DomainStateFieldDefinition,
            Literal["integer", "number"],
        ]
    ] = []
    for draft in bindings:
        target = (draft.manifest_id, draft.state_model_id, draft.state_field_id)
        if target in seen_targets:
            raise WorldUncertaintyModelValidationError(
                scenario.identifier,
                reason="duplicate binding target tuple",
            )
        seen_targets.add(target)
        pack_binding = _resolve_binding(store, scenario, draft)
        state_model = _resolve_state_model(store, scenario, draft)
        field = _resolve_field(scenario, draft, state_model)
        _validate_target_kind(scenario, draft, field)
        field_kind: Literal["integer", "number"] = (
            "integer" if field.value_kind is StateValueKind.INTEGER else "number"
        )
        _validate_rounding_and_bounds(scenario, draft, field_kind)
        _validate_discrete_kind_agreement(scenario, draft, field_kind)
        _validate_effective_parameters(scenario, draft)
        _validate_discrete_allowed_values(scenario, draft, field, field_kind)
        resolved.append((draft, pack_binding, state_model, field, field_kind))

    snapshot_hash = scenario_content_hash(scenario)
    bindings_tuple = tuple(
        _build_binding(
            scenario=scenario,
            pack_binding=pack_binding,
            state_model=state_model,
            field=field,
            draft=draft,
            field_kind=field_kind,
        )
        for draft, pack_binding, state_model, field, field_kind in sorted(
            resolved,
            key=lambda item: (
                item[0].manifest_id,
                item[0].state_model_id,
                item[0].state_field_id,
            ),
        )
    )
    try:
        model = WorldUncertaintyModel(
            identifier=uncertainty_model_identifier(
                tenant_id=tenant_id,
                scenario_id=scenario_id,
                scenario_content_hash_value=snapshot_hash,
            ),
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            scenario_content_hash=snapshot_hash,
            bindings=bindings_tuple,
            content_hash=_PLACEHOLDER_HASH,
            declared_at=declared_at,
            metadata=metadata,
        )
    except ValidationError:
        raise WorldUncertaintyModelValidationError(
            scenario_id, reason="declared model violates its contract"
        ) from None
    digest = uncertainty_model_content_hash(model)
    finalized = model.model_copy(update={"content_hash": digest})
    store.put_world_uncertainty_model(tenant_id, scenario_id, finalized)
    return finalized


def get_world_uncertainty_model(
    store: InMemoryScenarioStore,
    tenant_id: str,
    scenario_id: str,
) -> WorldUncertaintyModel:
    """Fetch one stored uncertainty model; raises WorldUncertaintyModelNotFoundError.

    The store revalidates the strict contract and the deterministic
    identity of the stored record on every read before any copy crosses
    the store boundary; this getter independently re-verifies ownership,
    the deterministic model identifier, and the model content hash
    before returning, so a corrupted stored record can never be served.
    """
    model = store.get_world_uncertainty_model(tenant_id, scenario_id)
    verify_world_uncertainty_model_identity(model, tenant_id=tenant_id, scenario_id=scenario_id)
    return model
