"""Causal runtime-observation and external-input contracts (Phase 28).

Phase 28 adds the **causal runtime-observation surface** for the additive
runtime version ``4.0.0``. ``RuntimeObservationDeclaration`` is an
immutable authority declaring one observation: its closed
``observation_source`` (an explicitly visible numeric state field, or an
immutable external/offline input channel), the observed value kind, an
optional unit, the integer step cadence and delay that control causal
availability, the observation-noise declaration, and the explicit missing
behavior. ``ExternalObservationInputBundle`` is an immutable authority
holding a non-empty canonically ordered tuple of accepted external input
values; its values never receive fresh runtime noise. ``RuntimeObservationEvent``
is the **nested, non-authoritative** evidence record that binds one
observation into one declaration or bundle, its world and seed, its
source step, and its ADR-004 observation-noise coordinate.

These contracts are **declarative data only**: they declare immutable
intent and evidence, and never sample, evaluate, quantize, or interpret
anything. ``RuntimeObservationEvent`` carries immutable evidence sufficient
to bind an event to a deterministic coordinate; it does not claim to prove
stored-authority ownership or to recompute content hashes (cross-authority
verification belongs to later runtime-4 services). No strategy identity,
policy identity, branch count, rule count, run identifier, global RNG
position, or execution-order-dependent RNG coordinate is expressible
anywhere in this module, and no field type can express a callback,
expression, import path, provider, network configuration, or executable
mechanism.

Integer step indexes - never wall-clock time - determine causal
availability: an observation sourced at step ``s`` becomes available at
step ``s + delay_steps``. ``delay_steps == 0`` permits same-decision use
because observation precedes policy evaluation in the within-step causal
schedule.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import (
    ExactNumeric,
    IdentifierString,
    QuantizationFractionBits,
    QuantizationPolicy,
    SamplerVersion,
    Sha256Hex,
    _is_exact_finite_numeric,
)

#: A strict non-negative integer: floats, strings, and booleans are
#: rejected before any coercion, and the value must be >= 0.
StrictNonNegativeInt = Annotated[int, Strict(), Field(ge=0)]

#: A strict positive integer: floats, strings, and booleans are rejected
#: and the value must be >= 1.
StrictPositiveInt = Annotated[int, Strict(), Field(ge=1)]

#: The closed set of numeric value kinds an observation can expose.
NumericValueKind = Literal["integer", "number"]

#: The closed set of missing-value behaviors; never inferred from truthiness.
MissingBehaviorLiteral = Literal["false", "error"]

#: The closed set of observation event statuses.
ObservationEventStatus = Literal["observed", "missing"]

#: The closed set of observation source kinds.
ObservationSourceKindLiteral = Literal["state_field", "external_input"]

#: The ADR-004 observation-noise domain literal.
NOISE_DOMAIN_LITERAL = "kalhas-observation-noise-v1"


class ObservationTiming(BaseModel):
    """The strict cadence that determines causal availability by step.

    An observation declares ``start_step >= 0``, ``every_n_steps >= 1``,
    and ``delay_steps >= 0``. It is scheduled at step ``S`` exactly when
    ``S >= start_step`` and ``(S - start_step) % every_n_steps == 0``. An
    observation sourced at step ``S`` becomes available at ``S +
    delay_steps``. No wall-clock value determines availability.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_step: StrictNonNegativeInt
    every_n_steps: StrictPositiveInt
    delay_steps: StrictNonNegativeInt


class NoObservationNoise(BaseModel):
    """The closed ``none`` observation-noise declaration.

    No fresh runtime noise is drawn: ``draw_count`` is exactly ``0``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["none"]
    draw_count: Literal[0]


class AdditiveUniformObservationNoise(BaseModel):
    """Declared additive uniform observation noise over exact finite bounds.

    Declares one additive uniform noise draw with exact finite
    ``lower_bound`` and ``upper_bound`` (``lower_bound <= upper_bound``),
    the frozen sampler/quantization provenance literals, and an exact
    ``draw_count`` of ``1``. This slice declares noise only; it never
    samples or evaluates it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["additive_uniform"]
    lower_bound: ExactNumeric
    upper_bound: ExactNumeric
    sampler_version: SamplerVersion
    quantization_policy: QuantizationPolicy
    quantization_fraction_bits: QuantizationFractionBits
    draw_count: Literal[1]

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("lower_bound", "upper_bound"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _bounds_ordered(self) -> AdditiveUniformObservationNoise:
        if self.lower_bound > self.upper_bound:
            raise ValueError("lower_bound must be <= upper_bound")
        return self


#: The closed discriminated union of the two observation-noise declarations.
ObservationNoise = Annotated[
    NoObservationNoise | AdditiveUniformObservationNoise,
    Field(discriminator="kind"),
]


class StateFieldObservationSource(BaseModel):
    """Authoritative copied provenance of one visible numeric state field.

    Every provenance field is copied from stored immutable records and
    locates one explicitly visible numeric state field: the manifest,
    the deterministic state-model identifier, the logical state-model id
    and its content hash, the state-field id, and the copied numeric
    field value kind.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["state_field"]
    manifest_id: IdentifierString
    state_model_identifier: IdentifierString
    state_model_id: IdentifierString
    state_model_content_hash: Sha256Hex
    state_field_id: IdentifierString
    state_field_value_kind: Literal["integer", "number"]


class ExternalObservationSource(BaseModel):
    """A stable external/offline input channel.

    The source of an immutable external input: a stable
    ``external_channel_id`` and the copied numeric value kind. External
    inputs never receive fresh runtime noise.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["external_input"]
    external_channel_id: IdentifierString
    external_value_kind: Literal["integer", "number"]


#: The closed discriminated union of observation sources. Unknown kinds
#: and extra fields fail.
ObservationSource = Annotated[
    StateFieldObservationSource | ExternalObservationSource,
    Field(discriminator="kind"),
]


class RuntimeObservationDeclaration(VersionedContract):
    """Immutable causal observation declaration for runtime 4.0.0.

    Declares one observation: its scenario, world identity and content
    hash, a stable logical ``observation_id``, the runtime version
    ``4.0.0``, one closed observation source, the observed numeric value
    kind, an optional declared unit, the timing/cadence, the
    observation-noise declaration, and the explicit ``missing_behavior``
    (exactly ``"false"`` or ``"error"``). ``declared_at`` is the
    deterministic caller-supplied timestamp and ``metadata`` holds only
    finite JSON-compatible values. External-input sources require noise
    kind ``"none"``; without noise ``observed_value_kind`` must equal the
    source value kind; additive noise produces ``observed_value_kind``
    ``"number"``. No hidden conversion, clipping, or tolerance is
    expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    observation_id: IdentifierString
    runtime_version: Literal["4.0.0"]
    observation_source: ObservationSource
    observed_value_kind: NumericValueKind
    unit: str | None = None
    timing: ObservationTiming
    noise: ObservationNoise
    missing_behavior: MissingBehaviorLiteral
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _source_noise_value_kind_rules(self) -> RuntimeObservationDeclaration:
        if isinstance(self.observation_source, ExternalObservationSource) and not isinstance(
            self.noise, NoObservationNoise
        ):
            raise ValueError("external-input sources require noise kind 'none'")
        if isinstance(self.observation_source, StateFieldObservationSource):
            source_value_kind = self.observation_source.state_field_value_kind
        else:
            source_value_kind = self.observation_source.external_value_kind
        if isinstance(self.noise, NoObservationNoise):
            if self.observed_value_kind != source_value_kind:
                raise ValueError(
                    "without noise, observed_value_kind must equal the source value kind"
                )
        elif self.observed_value_kind != "number":
            raise ValueError("additive noise produces observed_value_kind 'number'")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> RuntimeObservationDeclaration:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class RuntimeObservationEvent(BaseModel):
    """Nested, non-authoritative causal observation event evidence.

    Binds one observation to one declaration (identifier and content
    hash), its world and scenario-seed identities with their content
    hashes, the canonical sequence position and source step, the copied
    ``delay_steps`` and ``available_decision_step``, the ``terminal``
    flag and exact ``status`` (``"observed"`` or ``"missing"``), the
    applicable source/exposed values and observed value kind, and the
    ADR-004 observation-noise coordinate provenance. It does not prove
    stored-authority ownership or recompute content hashes; cross-authority
    verification belongs to later runtime services.

    Contract-level invariants: a non-terminal event requires
    ``available_decision_step == source_step_index + delay_steps``; a
    terminal event requires it absent. State-field events require
    ``source_state_hash`` and forbid external bundle provenance;
    external-input events require the bundle identity/hash and forbid
    ``source_state_hash`` and fresh noise. Missing events leave every
    value field absent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    runtime_version: Literal["4.0.0"]
    observation_declaration_id: IdentifierString
    observation_declaration_content_hash: Sha256Hex
    observation_id: IdentifierString
    source_kind: ObservationSourceKindLiteral
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    sequence_position: StrictNonNegativeInt
    source_step_index: StrictNonNegativeInt
    delay_steps: StrictNonNegativeInt
    available_decision_step: StrictNonNegativeInt | None = None
    terminal: bool
    status: ObservationEventStatus
    source_state_hash: Sha256Hex | None = None
    external_input_bundle_id: IdentifierString | None = None
    external_input_bundle_content_hash: Sha256Hex | None = None
    source_value: ExactNumeric | None = None
    applied_noise_value: ExactNumeric | None = None
    exposed_observation_value: ExactNumeric | None = None
    observed_value_kind: Literal["integer", "number"] | None = None
    observed_value_unit: str | None = None
    noise_domain_literal: Literal["kalhas-observation-noise-v1"]
    noise_sampler_version: SamplerVersion
    noise_draw_index: StrictNonNegativeInt | None = None
    content_hash: Sha256Hex

    @model_validator(mode="before")
    @classmethod
    def _raw_value_fields_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("source_value", "applied_noise_value", "exposed_observation_value"):
            raw = data.get(key)
            if raw is not None and not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _availability_and_terminality(self) -> RuntimeObservationEvent:
        if self.terminal:
            if self.available_decision_step is not None:
                raise ValueError("terminal events require available_decision_step absent")
        elif self.available_decision_step != self.source_step_index + self.delay_steps:
            raise ValueError(
                "non-terminal available_decision_step must equal source_step_index + delay_steps"
            )
        return self

    @model_validator(mode="after")
    def _status_value_evidence(self) -> RuntimeObservationEvent:
        if self.status == "observed":
            if self.source_value is None or self.exposed_observation_value is None:
                raise ValueError("observed events require the source and exposed values")
            if self.observed_value_kind is None:
                raise ValueError("observed events require the observed value kind")
        else:
            if not all(
                value is None
                for value in (
                    self.source_value,
                    self.applied_noise_value,
                    self.exposed_observation_value,
                )
            ):
                raise ValueError("missing events require all value fields absent")
            if self.observed_value_kind is not None or self.observed_value_unit is not None:
                raise ValueError("missing events require observed value kind and unit absent")
        if self.observed_value_kind == "integer":
            for value in (
                self.source_value,
                self.applied_noise_value,
                self.exposed_observation_value,
            ):
                if value is not None and not isinstance(value, int):
                    raise ValueError("integer-kind events require exact int values")
        return self

    @model_validator(mode="after")
    def _source_provenance_separation(self) -> RuntimeObservationEvent:
        if self.source_kind == "state_field":
            if self.source_state_hash is None:
                raise ValueError("state-field events require source_state_hash")
            if (
                self.external_input_bundle_id is not None
                or self.external_input_bundle_content_hash is not None
            ):
                raise ValueError("state-field events forbid external input provenance")
        else:
            if (
                self.external_input_bundle_id is None
                or self.external_input_bundle_content_hash is None
            ):
                raise ValueError("external-input events require bundle identity and content hash")
            if self.source_state_hash is not None:
                raise ValueError("external-input events forbid source_state_hash")
            if self.applied_noise_value is not None or self.noise_draw_index is not None:
                raise ValueError("external-input events forbid fresh noise")
        return self


class ExternalObservationInputEntry(BaseModel):
    """One immutable accepted external input value.

    The deterministic entry identifier, the referenced declaration's
    identifier and content hash, the logical observation id, the external
    channel id, the non-negative source step index, the exact value kind
    (``"integer"`` or ``"number"``), an optional unit, and an exact finite
    value. Integer entries require an exact ``int``; number entries accept
    an exact finite ``int`` or ``float``. Booleans and any numeric
    coercion fail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    runtime_observation_declaration_id: IdentifierString
    runtime_observation_declaration_content_hash: Sha256Hex
    observation_id: IdentifierString
    external_channel_id: IdentifierString
    source_step_index: StrictNonNegativeInt
    value_kind: Literal["integer", "number"]
    unit: str | None = None
    value: ExactNumeric
    content_hash: Sha256Hex

    @model_validator(mode="before")
    @classmethod
    def _raw_value_matches_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_kind = data.get("value_kind")
        raw_value = data.get("value")
        if raw_kind == "integer":
            if not (_is_exact_finite_numeric(raw_value) and isinstance(raw_value, int)):
                raise ValueError("integer entries require an exact int value")
        elif raw_kind == "number" and not _is_exact_finite_numeric(raw_value):
            raise ValueError("number entries require an exact finite numeric value")
        return data


class ExternalObservationInputBundle(VersionedContract):
    """Immutable authority of accepted external/offline input values.

    Carries the deterministic external-input bundle identifier, tenant and
    schema version, campaign/scenario identity, the world and
    scenario-seed identities with their content hashes, the exact runtime
    version ``4.0.0``, a non-empty canonically ordered tuple of immutable
    external input entries, the self-covering ``content_hash``, and the
    deterministic caller-supplied ``accepted_at``. Entry ``value = ExactNumeric``
    kinds must agree exactly with the declared entry kind. External bundle
    values never receive fresh runtime noise; cross-authority verification
    against stored declarations is deliberately deferred to later services.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    runtime_version: Literal["4.0.0"]
    entries: tuple[ExternalObservationInputEntry, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    accepted_at: AwareDatetime

    @model_validator(mode="after")
    def _entries_canonically_ordered_and_unique(self) -> ExternalObservationInputBundle:
        ordering = [
            (entry.source_step_index, entry.runtime_observation_declaration_id)
            for entry in self.entries
        ]
        if ordering != sorted(ordering):
            raise ValueError(
                "entries must be canonically ordered by "
                "(source_step_index, runtime_observation_declaration_id)"
            )
        coordinates = [
            (entry.runtime_observation_declaration_id, entry.source_step_index)
            for entry in self.entries
        ]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError(
                "duplicate (runtime_observation_declaration_id, source_step_index) "
                "coordinates are rejected"
            )
        return self
