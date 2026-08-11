"""Pure deterministic world-realization builder (Phase 24).

Builds the immutable ``WorldRealization`` of one world under one shared
campaign seed - and the campaign-level ``CampaignWorldRealizationMatrix``
- from **already verified authoritative records only**: the compiled
``WorldVersion``, the state-model snapshots of its verified catalog,
the embedded ``WorldUncertaintyModel`` (or its absence), the exact
``ScenarioSeed``, and the authoritative recorded campaign timestamp.
The module never loads the store, never calls LEGION or NEXUS, never
uses wall-clock time, randomness, network, providers, filesystem, or
domain packs, and never mutates any input.

For every uncertainty binding, in canonical binding order: the base
initial state of the target state model is derived fresh via
``derive_initial_state``, the targeted field is sampled exactly once
through the deterministic sampler (``sampled_raw_value`` is the finite
distribution output **before** clipping and rounding), the value is
clipped against the present bounds, rounded with the declared policy
for integer targets, and converted with exact JSON representation
preservation (continuous families always record float raws; discrete
samples preserve the exact declared selected value type; clipping
replaces a number-kind value with the exact stored bound type; integer
targets always finish as exact ``int``). The final value becomes the
override, and the **complete** state of every touched state model is
validated through the existing ``validate_state`` rules (unknown or
missing fields, exact kind, canonical ``allowed_values`` membership) -
deterministic per-seed failure, never a resample.

Overrides are the complete delta: exactly one override per uncertainty
binding, none for untargeted base-state fields, in canonical binding
order, with contract-validated one-to-one agreement against the sampled
values. A world without an uncertainty model still produces one
deterministic empty realization per seed (empty sampled values and
overrides, explicit absent model markers) so downstream phases can
consume realizations uniformly. Digest-word draw indexes are contiguous
from zero across the realization. Nothing is ever executed, replayed,
extracted, aggregated, ranked, or recommended.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from kalhas.application.deterministic_sampler import (
    QUANTIZATION_FRACTION_BITS,
    QUANTIZATION_POLICY,
    SAMPLER_VERSION,
    SamplerOverflowError,
    clip_fixed,
    digest_word,
    record_raw_value,
    round_fixed,
    sample_distribution,
)
from kalhas.application.domain_errors import StateValidationError
from kalhas.application.state_transition_engine import (
    derive_initial_state,
    validate_state,
)
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
)
from kalhas.application.world_uncertainty_identity import (
    campaign_realization_matrix_content_hash,
    campaign_realization_matrix_identifier,
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import (
    WORD_COUNT,
    CampaignWorldRealizationMatrix,
    DistributionKind,
    RealizedStateFieldValue,
    SampledStateFieldValue,
    StateFieldUncertaintyBinding,
    WorldRealization,
    WorldUncertaintyModel,
)

_PLACEHOLDER_HASH = "0" * 64


def _sampling_failure(
    tenant_id: str, scenario_id: str, reason: str
) -> WorldRealizationSamplingError:
    """A typed deterministic sampling failure with a rule-level reason."""
    return WorldRealizationSamplingError(tenant_id, scenario_id, reason=reason)


def _resolve_target(
    tenant_id: str,
    scenario_id: str,
    state_models: tuple[DomainStateModel, ...],
    binding: StateFieldUncertaintyBinding,
) -> DomainStateModel:
    """Resolve and verify the binding's state model from the verified catalog."""
    state_model = next(
        (
            candidate
            for candidate in state_models
            if candidate.identifier == binding.state_model_identifier
        ),
        None,
    )
    if state_model is None:
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="uncertainty binding references an unknown state model",
        )
    if (
        state_model.state_model_id != binding.state_model_id
        or state_model.content_hash != binding.state_model_content_hash
        or state_model.manifest_id != binding.manifest_id
    ):
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="uncertainty binding state-model provenance does not match the "
            "supplied state model",
        )
    if (
        next(
            (
                candidate
                for candidate in state_model.state_fields
                if candidate.identifier == binding.state_field_id
            ),
            None,
        )
        is None
    ):
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="uncertainty binding references an unknown state field",
        )
    return state_model


def _sample_one_binding(
    *,
    tenant_id: str,
    scenario_id: str,
    world_content_hash: str,
    seed_hash: str,
    binding: StateFieldUncertaintyBinding,
    draw_index: int,
) -> tuple[int, Literal["int", "float"], int | float, int | float, DistributionKind]:
    """Sample, clip, round, and convert one targeted field exactly once.

    Returns ``(draw_count, raw_kind, sampled_raw_value, realized_value,
    distribution_kind)``. The raw value is recorded **before** clipping
    and is finite by construction (``record_raw_value`` enforces the
    finite-representability guard; clipping can never rescue a
    non-finite or unrepresentable raw). Integer targets always finish
    as exact ``int``; number targets preserve the representation source
    (continuous -> float, discrete -> declared value type, clipping ->
    exact stored bound type).
    """
    distribution_kind = binding.distribution.kind
    draw_count = WORD_COUNT[distribution_kind]
    words = tuple(
        digest_word(
            world_content_hash=world_content_hash,
            seed_content_hash=seed_hash,
            uncertainty_binding_content_hash=binding.content_hash,
            draw_index=draw_index + offset,
        )
        for offset in range(draw_count)
    )
    try:
        output = sample_distribution(
            binding.distribution,
            word_0=words[0],
            word_1=words[1] if draw_count > 1 else None,
        )
    except SamplerOverflowError as exc:
        raise _sampling_failure(tenant_id, scenario_id, str(exc)) from None

    raw_kind: Literal["int", "float"] = (
        "int"
        if distribution_kind == "discrete" and isinstance(output.selected_discrete_value, int)
        else "float"
    )
    try:
        sampled_raw_value = record_raw_value(output.value_fix, raw_kind)
    except SamplerOverflowError as exc:
        raise _sampling_failure(tenant_id, scenario_id, str(exc)) from None

    try:
        clipped_fix, replaced_kind = clip_fixed(
            output.value_fix,
            lower_bound=binding.lower_bound,
            upper_bound=binding.upper_bound,
        )
        if binding.state_field_value_kind == "integer":
            if binding.rounding_policy is None:
                raise _sampling_failure(
                    tenant_id,
                    scenario_id,
                    "integer target has no rounding policy",
                )
            realized_value: int | float = round_fixed(clipped_fix, binding.rounding_policy)
        else:
            final_kind: Literal["int", "float"] = (
                replaced_kind if replaced_kind is not None else raw_kind
            )
            realized_value = record_raw_value(clipped_fix, final_kind)
    except SamplerOverflowError as exc:
        raise _sampling_failure(tenant_id, scenario_id, str(exc)) from None
    return draw_count, raw_kind, sampled_raw_value, realized_value, distribution_kind


def build_world_realization(
    *,
    world: WorldVersion,
    state_models: tuple[DomainStateModel, ...],
    model: WorldUncertaintyModel | None,
    seed: ScenarioSeed,
    realized_at: AwareDatetime,
) -> WorldRealization:
    """Build the deterministic realization of one seed under one world.

    Pure and read-only: every input is already verified; nothing is
    mutated, executed, or resampled. Raises
    :class:`WorldRealizationIntegrityError` for inconsistent verified
    inputs and :class:`WorldRealizationSamplingError` for deterministic
    per-seed sampling or validation failures.
    """
    tenant_id = world.tenant_id
    scenario_id = world.source_scenario_id
    if seed.tenant_id != tenant_id:
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="seed tenant does not match the world tenant",
        )
    if model is not None and (model.tenant_id != tenant_id or model.scenario_id != scenario_id):
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="uncertainty model provenance does not match the world",
        )
    seed_hash = seed_content_hash(seed)

    if model is None:
        realization_identifier = world_realization_identifier(
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            scenario_seed_id=seed.identifier,
            seed_content_hash_value=seed_hash,
            uncertainty_model_id=None,
            uncertainty_model_content_hash_value=None,
            sampler_version=SAMPLER_VERSION,
            quantization_policy=QUANTIZATION_POLICY,
            quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
        )
        empty_realization = WorldRealization(
            identifier=realization_identifier,
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            scenario_seed_id=seed.identifier,
            seed_content_hash=seed_hash,
            uncertainty_model_id=None,
            uncertainty_model_content_hash=None,
            sampler_version=SAMPLER_VERSION,
            quantization_policy=QUANTIZATION_POLICY,
            quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
            sampled_values=(),
            realized_initial_state_overrides=(),
            content_hash=_PLACEHOLDER_HASH,
            realized_at=realized_at,
        )
        digest = world_realization_content_hash(empty_realization)
        return empty_realization.model_copy(update={"content_hash": digest})

    sampled_values: list[SampledStateFieldValue] = []
    overrides: list[RealizedStateFieldValue] = []
    base_states: dict[str, dict[str, JsonValue]] = {}
    resolved_models: dict[str, DomainStateModel] = {}
    draw_index = 0
    for binding in model.bindings:
        state_model = _resolve_target(tenant_id, scenario_id, state_models, binding)
        resolved_models[binding.state_model_identifier] = state_model
        draw_count, _, sampled_raw_value, realized_value, distribution_kind = _sample_one_binding(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            world_content_hash=world.content_hash,
            seed_hash=seed_hash,
            binding=binding,
            draw_index=draw_index,
        )
        try:
            sampled = SampledStateFieldValue(
                uncertainty_binding_identifier=binding.identifier,
                uncertainty_binding_content_hash=binding.content_hash,
                scenario_id=binding.scenario_id,
                binding_id=binding.binding_id,
                manifest_id=binding.manifest_id,
                state_model_identifier=binding.state_model_identifier,
                state_model_id=binding.state_model_id,
                state_field_id=binding.state_field_id,
                state_field_value_kind=binding.state_field_value_kind,
                distribution_kind=distribution_kind,
                sampler_version=binding.sampler_version,
                quantization_policy=binding.quantization_policy,
                quantization_fraction_bits=binding.quantization_fraction_bits,
                draw_index=draw_index,
                draw_count=draw_count,
                sampled_raw_value=sampled_raw_value,
                realized_value=realized_value,
            )
        except ValidationError:
            raise WorldRealizationIntegrityError(
                tenant_id,
                scenario_id,
                reason="internally built sampled value violates its contract",
            ) from None
        sampled_values.append(sampled)
        state = base_states.setdefault(
            binding.state_model_identifier, derive_initial_state(state_model)
        )
        state[binding.state_field_id] = realized_value
        overrides.append(
            RealizedStateFieldValue(
                state_model_identifier=binding.state_model_identifier,
                state_field_id=binding.state_field_id,
                value=realized_value,
            )
        )
        draw_index += draw_count

    for identifier, state in base_states.items():
        try:
            validate_state(state, resolved_models[identifier])
        except StateValidationError as exc:
            raise _sampling_failure(
                tenant_id,
                scenario_id,
                reason=getattr(exc, "reason", None) or "realized state failed validation",
            ) from exc

    realization_identifier = world_realization_identifier(
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=seed.identifier,
        seed_content_hash_value=seed_hash,
        uncertainty_model_id=model.identifier,
        uncertainty_model_content_hash_value=model.content_hash,
        sampler_version=SAMPLER_VERSION,
        quantization_policy=QUANTIZATION_POLICY,
        quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
    )
    try:
        realization = WorldRealization(
            identifier=realization_identifier,
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            scenario_seed_id=seed.identifier,
            seed_content_hash=seed_hash,
            uncertainty_model_id=model.identifier,
            uncertainty_model_content_hash=model.content_hash,
            sampler_version=SAMPLER_VERSION,
            quantization_policy=QUANTIZATION_POLICY,
            quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
            sampled_values=tuple(sampled_values),
            realized_initial_state_overrides=tuple(overrides),
            content_hash=_PLACEHOLDER_HASH,
            realized_at=realized_at,
        )
    except ValidationError:
        raise WorldRealizationIntegrityError(
            tenant_id,
            scenario_id,
            reason="internally built realization violates its contract",
        ) from None
    digest = world_realization_content_hash(realization)
    return realization.model_copy(update={"content_hash": digest})


def build_campaign_world_realization_matrix(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    state_models: tuple[DomainStateModel, ...],
    model: WorldUncertaintyModel | None,
) -> CampaignWorldRealizationMatrix:
    """Build the deterministic realization matrix of one campaign.

    Exactly one realization per campaign seed in the exact campaign
    seed-ensemble order. Strategy identifiers are structurally absent:
    the matrix is a pure function of the campaign identity, the
    compiled world, the embedded model (or its absence), and the seed
    ensemble. The matrix is derived in memory and never stored;
    repeated calls return byte-identical artifacts.

    Inconsistent direct inputs are rejected with typed integrity errors
    before any sampling: the campaign tenant must equal the world
    tenant, the campaign scenario must equal the world's source
    scenario, the campaign world reference must equal the world
    identifier, and the campaign seed ensemble must be non-empty.
    """
    if campaign.tenant_id != world.tenant_id:
        raise WorldRealizationIntegrityError(
            world.tenant_id,
            world.source_scenario_id,
            reason="campaign tenant does not match the world tenant",
        )
    if campaign.scenario_id != world.source_scenario_id:
        raise WorldRealizationIntegrityError(
            world.tenant_id,
            world.source_scenario_id,
            reason="campaign scenario does not match the world source scenario",
        )
    if campaign.world_version_id != world.identifier:
        raise WorldRealizationIntegrityError(
            world.tenant_id,
            world.source_scenario_id,
            reason="campaign world reference does not match the world identifier",
        )
    if not campaign.seed_ensemble:
        raise WorldRealizationIntegrityError(
            world.tenant_id,
            world.source_scenario_id,
            reason="campaign seed ensemble is empty",
        )
    realizations = tuple(
        build_world_realization(
            world=world,
            state_models=state_models,
            model=model,
            seed=seed,
            realized_at=campaign.created_at,
        )
        for seed in campaign.seed_ensemble
    )
    matrix_identifier = campaign_realization_matrix_identifier(
        campaign_id=campaign.identifier,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        uncertainty_model_id=model.identifier if model is not None else None,
        uncertainty_model_content_hash_value=model.content_hash if model is not None else None,
        sampler_version=SAMPLER_VERSION,
        quantization_policy=QUANTIZATION_POLICY,
        quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
    )
    matrix = CampaignWorldRealizationMatrix(
        identifier=matrix_identifier,
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=world.source_scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        uncertainty_model_id=model.identifier if model is not None else None,
        uncertainty_model_content_hash=model.content_hash if model is not None else None,
        sampler_version=SAMPLER_VERSION,
        quantization_policy=QUANTIZATION_POLICY,
        quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
        ordered_scenario_seed_ids=tuple(seed.identifier for seed in campaign.seed_ensemble),
        realizations=realizations,
        content_hash=_PLACEHOLDER_HASH,
        assembled_at=campaign.created_at,
    )
    digest = campaign_realization_matrix_content_hash(matrix)
    return matrix.model_copy(update={"content_hash": digest})
