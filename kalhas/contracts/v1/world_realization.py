"""Deterministic world-uncertainty realization contracts (Phase 24).

Phase 24 adds the **deterministic world-uncertainty realization
artifact**: an immutable, tenant-scoped ``WorldUncertaintyModel``
declaring - for exactly one stored scenario - which initial-state
fields of its registered domain state models are uncertain, with the
exact distribution family, integer rounding policy, and optional
clipping bounds; plus the strategy-independent ``WorldRealization``
produced per shared campaign seed and the campaign-level
``CampaignWorldRealizationMatrix``. The pipeline is

    WorldUncertaintyModel + compiled WorldVersion + ScenarioSeed
        -> exactly one deterministic WorldRealization per shared seed

The model is **declarative data only**: it never samples, executes,
evaluates, or interprets anything. Sampling happens exclusively in the
deterministic application-layer sampler (``sha256-counter-v1`` with
rational round-half-even Q64.64 quantization); these contracts carry
the exact sampler/quantization provenance literals so every artifact
records which algorithm produced it.

``DistributionSpecification`` is a **closed discriminated union** of
the five approved families - ``uniform(low, high)``,
``triangular(low, mode, high)``, ``normal(mean, standard_deviation)``,
``lognormal(mu, sigma)`` (mu/sigma are **log-space** parameters:
``ln X ~ Normal(mu, sigma^2)``, ``X = exp(mu + sigma*Z)``), and
``discrete(values, probabilities)``. There is no unvalidated parameter
dictionary anywhere. Every numeric input must be exact finite
(booleans, strings, ``None``, containers, NaN, and Infinity are
rejected before any coercion), every declared ordering rule is
enforced, standard deviations and sigmas are strictly positive, and
``MAX_ABS_PARAMETER`` bounds every declared magnitude.

``StateFieldUncertaintyBinding`` carries the complete authoritative
provenance snapshot copied exclusively from stored immutable records -
scenario, source ``DomainPackBinding`` identifier, manifest, pack
identity and manifest content hash, deterministic state-model
identifier, logical state-model id, state-model content hash, target
state-field id, and the copied field value kind - plus the
caller-owned distribution, rounding policy, and independently optional
lower/upper clipping bounds, the frozen sampler/quantization
provenance literals, a deterministic binding identifier (independent
of the content hash), and a self-covering ``content_hash``.

``SampledStateFieldValue`` records one sample of one targeted field:
the binding identifier and content hash, the complete target
identity, the distribution kind, the sampler/quantization provenance,
the starting global digest-word ``draw_index`` and the exact
``draw_count`` (1 for uniform/triangular/discrete, 2 for
normal/lognormal - normal and lognormal consume **two** digest words,
so record indexes are not consecutive by one in word units), the exact
finite ``sampled_raw_value`` (the distribution output **before**
clipping and rounding - for an integer target it may legitimately be a
float), and the final ``realized_value`` after clipping and rounding
which must exactly match the authoritative target kind (integer
targets always finish as exact ``int``).

``WorldRealization`` is the strategy-independent realization of one
world under one shared seed: world and seed identity/hash, the
uncertainty-model identity/hash or an explicit absent state, the
sampler/quantization provenance, the ordered sampled values, the
complete realized initial-state override delta (exactly one override
per uncertainty binding, none for untargeted base-state fields, in
canonical binding order with one-to-one agreement against the sampled
values), a deterministic independently derived identifier, a
self-covering content hash, and the authoritative recorded
``realized_at`` (the campaign ``created_at`` - never the wall clock).

``CampaignWorldRealizationMatrix`` is the deterministic campaign-level
artifact: exactly one realization per campaign seed in the exact
campaign seed-ensemble order, with no strategy identifiers anywhere -
realizations are intentionally strategy-independent. The matrix is
derived in memory and never stored.

Nothing here loads, imports, instantiates, or executes a domain pack,
a strategy, a transition, or a sampler, and no field type can express
a callback, expression, formula, code reference, provider, or
executable mechanism. ``UncertaintyDefinition`` is deliberately left
untouched: it remains the shipped declarative metadata contract.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    Strict,
    model_validator,
)

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"

#: A single SHA-256 hex digest field (lowercase, 64 chars).
Sha256Hex = Annotated[str, Field(pattern=_SHA256_PATTERN)]

#: A non-empty identifier string.
IdentifierString = Annotated[str, Field(min_length=1)]

#: Declared numeric magnitude cap for every distribution parameter and
#: clipping bound. Values above this cap are rejected at declaration so
#: fixed-point intermediates stay far below any resource boundary.
MAX_ABS_PARAMETER = 2.0**960

#: Discrete declared-probability sum tolerance. The declared float sum
#: must lie within this tolerance of 1.0 (the IEEE float sum is
#: correctly rounded and therefore deterministic).
PROBABILITY_SUM_TOLERANCE = 1e-12

#: Exact digest-word consumption per distribution family. Normal and
#: lognormal consume two words (Box-Muller pair); all other families
#: consume one.
WORD_COUNT: dict[str, int] = {
    "uniform": 1,
    "triangular": 1,
    "normal": 2,
    "lognormal": 2,
    "discrete": 1,
}

#: Frozen sampler/quantization provenance literals. These exact values
#: identify the versioned algorithm and quantization policy; they are
#: recorded on every sampling artifact and verified at every trust
#: boundary.
SamplerVersion = Literal["sha256-counter-v1"]
QuantizationPolicy = Literal["rational-round-half-even"]
QuantizationFractionBits = Literal[64]

#: The exact closed set of distribution families.
DistributionKind = Literal["uniform", "triangular", "normal", "lognormal", "discrete"]


#: A strict exact numeric: an ``int`` stays an ``int``, a ``float``
#: stays a ``float``, and booleans, strings, containers, NaN, and
#: Infinity are rejected before any coercion. Used for discrete values
#: and clipping bounds, where the JSON numeric representation is
#: semantically meaningful (canonical JSON ``1`` and ``1.0`` are
#: distinct).
def _require_finite(value: int | float) -> int | float:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("numeric value must be finite")
    return value


StrictInt = Annotated[int, Strict()]
StrictFiniteFloat = Annotated[float, Strict(), AfterValidator(_require_finite)]
ExactNumeric = StrictInt | StrictFiniteFloat


def _is_exact_finite_numeric(value: object) -> bool:
    """True only for an exact finite ``int`` or ``float`` value.

    Booleans are never accepted as integers or numbers, and non-finite
    floats (NaN/Infinity) are rejected because they are not valid JSON
    numbers. Strings, ``None``, and containers are rejected - no
    numeric coercion of any kind happens.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _canonical_value_text(value: JsonValue) -> str:
    """Render a JSON-compatible value in the repository's canonical form.

    Mirrors ``kalhas.application.hashing.canonical_json`` (sorted
    keys, no insignificant whitespace). Canonical text is the equality
    domain for uniqueness and allowed-values checks, so canonical JSON
    integer ``1`` and float ``1.0`` are distinct values.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _check_parameter_magnitude(values: dict[str, float]) -> None:
    """Reject any declared parameter whose magnitude exceeds the cap."""
    for key, value in values.items():
        if abs(value) > MAX_ABS_PARAMETER:
            raise ValueError(f"{key} exceeds MAX_ABS_PARAMETER")


class UniformDistribution(BaseModel):
    """``uniform(low, high)`` on the continuous interval ``[low, high)``.

    Both endpoints are exact finite numerics with ``low <= high``; the
    degenerate ``low == high`` case is allowed and samples the constant
    ``low``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["uniform"]
    low: float
    high: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("low", "high"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _ordering_and_magnitude(self) -> UniformDistribution:
        if self.low > self.high:
            raise ValueError("low must be <= high")
        _check_parameter_magnitude({"low": self.low, "high": self.high})
        return self


class TriangularDistribution(BaseModel):
    """``triangular(low, mode, high)`` with ``low <= mode <= high``.

    Equalities are allowed: ``mode == low`` and ``mode == high`` are
    the standard right/left triangular shapes, and the fully degenerate
    case samples the constant ``low`` (never a division by zero).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["triangular"]
    low: float
    mode: float
    high: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("low", "mode", "high"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _ordering_and_magnitude(self) -> TriangularDistribution:
        if not (self.low <= self.mode <= self.high):
            raise ValueError("low <= mode <= high is required")
        _check_parameter_magnitude({"low": self.low, "mode": self.mode, "high": self.high})
        return self


class NormalDistribution(BaseModel):
    """``normal(mean, standard_deviation)`` with strictly positive deviation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["normal"]
    mean: float
    standard_deviation: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("mean", "standard_deviation"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _deviation_and_magnitude(self) -> NormalDistribution:
        if self.standard_deviation <= 0.0:
            raise ValueError("standard_deviation must be strictly positive")
        _check_parameter_magnitude(
            {"mean": self.mean, "standard_deviation": self.standard_deviation}
        )
        return self


class LognormalDistribution(BaseModel):
    """``lognormal(mu, sigma)`` with **log-space** parameters.

    ``mu`` is the mean of ``ln X`` and ``sigma`` is the standard
    deviation of ``ln X``; the sampled value is ``X = exp(mu + sigma*Z)``
    with standard normal ``Z``. ``sigma`` is strictly positive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["lognormal"]
    mu: float
    sigma: float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("mu", "sigma"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _sigma_and_magnitude(self) -> LognormalDistribution:
        if self.sigma <= 0.0:
            raise ValueError("sigma must be strictly positive")
        _check_parameter_magnitude({"mu": self.mu, "sigma": self.sigma})
        return self


class DiscreteDistribution(BaseModel):
    """``discrete(values, probabilities)`` with exact-weight selection.

    ``values`` are strict exact numerics (an ``int`` stays an ``int``
    and a ``float`` stays a ``float``; booleans are rejected) and must
    be canonically unique - canonical JSON ``1`` and ``1.0`` are
    distinct values. ``probabilities`` are finite and non-negative with
    at least one strictly positive entry, and the declared float sum
    must lie within ``PROBABILITY_SUM_TOLERANCE`` of ``1.0``; the exact
    quantized integer weights define the selection distribution (no
    hidden normalization or resampling). Zero-probability support
    values are never selected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["discrete"]
    values: tuple[ExactNumeric, ...] = Field(min_length=1)
    probabilities: tuple[float, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_values = data.get("values")
        if isinstance(raw_values, (list, tuple)):
            for index, value in enumerate(raw_values):
                if not _is_exact_finite_numeric(value):
                    raise ValueError(f"values[{index}] must be an exact finite numeric value")
        raw_probabilities = data.get("probabilities")
        if isinstance(raw_probabilities, (list, tuple)):
            for index, value in enumerate(raw_probabilities):
                if not _is_exact_finite_numeric(value):
                    raise ValueError(
                        f"probabilities[{index}] must be an exact finite numeric value"
                    )
        return data

    @model_validator(mode="after")
    def _values_and_probabilities_rules(self) -> DiscreteDistribution:
        if len(self.values) != len(self.probabilities):
            raise ValueError("values and probabilities must have equal length")
        canonical = [_canonical_value_text(value) for value in self.values]
        if len(canonical) != len(set(canonical)):
            raise ValueError("values must be canonically unique")
        for value in self.values:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("values must be finite")
            if abs(value) > MAX_ABS_PARAMETER:
                raise ValueError("discrete value exceeds MAX_ABS_PARAMETER")
        for probability in self.probabilities:
            if not math.isfinite(probability) or probability < 0.0:
                raise ValueError("probabilities must be finite and non-negative")
        if not any(probability > 0.0 for probability in self.probabilities):
            raise ValueError("at least one probability must be strictly positive")
        declared_sum = sum(self.probabilities)
        if abs(declared_sum - 1.0) > PROBABILITY_SUM_TOLERANCE:
            raise ValueError("declared probability sum must be within tolerance of 1.0")
        return self


#: The closed discriminated union of the five approved distribution
#: families. Unknown kinds and extra fields are rejected.
DistributionSpecification = Annotated[
    UniformDistribution
    | TriangularDistribution
    | NormalDistribution
    | LognormalDistribution
    | DiscreteDistribution,
    Field(discriminator="kind"),
]


class StateFieldUncertaintyBinding(BaseModel):
    """One immutable uncertainty binding of one initial-state field.

    Every provenance field (scenario, source ``DomainPackBinding``
    identifier, manifest, pack identity, manifest content hash,
    deterministic state-model identifier, logical state-model id,
    state-model content hash, state-field id, and the copied field
    value kind) is copied from stored immutable records - never from
    client input. The caller owns only the distribution, the rounding
    policy, and the independently optional clipping bounds. The
    deterministic binding identifier is derived from the canonical
    target identity and is independent of the content hash; the
    self-covering ``content_hash`` covers the complete canonical
    serialization excluding itself.

    Only ``integer`` and ``number`` initial-state fields may be
    targeted. An integer target requires exactly one rounding policy
    from ``floor``/``ceil``/``nearest_ties_to_even`` and forbids it for
    number targets. Bounds are independently optional (both present
    requires ``lower <= upper``); every bound on an integer target must
    be a stored exact ``int``; number targets accept exact ``int`` or
    ``float`` bounds whose JSON representation is preserved.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: IdentifierString
    scenario_id: IdentifierString
    binding_id: IdentifierString
    manifest_id: IdentifierString
    pack_id: IdentifierString
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: Sha256Hex
    state_model_identifier: IdentifierString
    state_model_id: IdentifierString
    state_model_content_hash: Sha256Hex
    state_field_id: IdentifierString
    state_field_value_kind: Literal["integer", "number"]
    distribution: DistributionSpecification
    rounding_policy: Literal["floor", "ceil", "nearest_ties_to_even"] | None = None
    lower_bound: ExactNumeric | None = None
    upper_bound: ExactNumeric | None = None
    sampler_version: SamplerVersion
    quantization_policy: QuantizationPolicy
    quantization_fraction_bits: QuantizationFractionBits
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def _rounding_policy_rules(self) -> StateFieldUncertaintyBinding:
        if self.state_field_value_kind == "integer":
            if self.rounding_policy is None:
                raise ValueError("integer targets require a rounding_policy")
        elif self.rounding_policy is not None:
            raise ValueError("rounding_policy is forbidden for number targets")
        return self

    @model_validator(mode="after")
    def _bound_rules(self) -> StateFieldUncertaintyBinding:
        for key, bound in (("lower_bound", self.lower_bound), ("upper_bound", self.upper_bound)):
            if bound is None:
                continue
            if isinstance(bound, bool) or (isinstance(bound, float) and not math.isfinite(bound)):
                raise ValueError(f"{key} must be an exact finite numeric value")
            if abs(bound) > MAX_ABS_PARAMETER:
                raise ValueError(f"{key} exceeds MAX_ABS_PARAMETER")
            if self.state_field_value_kind == "integer" and not isinstance(bound, int):
                raise ValueError("integer targets require exact integer bounds")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound must be <= upper_bound")
        return self

    @model_validator(mode="after")
    def _discrete_kind_agreement(self) -> StateFieldUncertaintyBinding:
        if isinstance(self.distribution, DiscreteDistribution) and (
            self.state_field_value_kind == "integer"
        ):
            for value in self.distribution.values:
                if not isinstance(value, int):
                    raise ValueError("discrete values must be exact integers for integer targets")
        return self


class SampledStateFieldValue(BaseModel):
    """One sampled value of one targeted state field.

    ``sampled_raw_value`` is the exact finite distribution output
    **before** clipping and rounding; for an integer target it may
    legitimately be a float (booleans and non-finite values are
    rejected). ``realized_value`` is the final value after clipping and
    rounding and must exactly match the authoritative target kind
    (integer targets always finish as exact ``int``; number targets may
    finish as ``int`` or ``float`` according to the representation
    preservation rules). ``draw_index`` is the starting global
    digest-word index and ``draw_count`` is the exact word consumption
    of the distribution kind (1 for uniform/triangular/discrete, 2 for
    normal/lognormal).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    uncertainty_binding_identifier: IdentifierString
    uncertainty_binding_content_hash: Sha256Hex
    scenario_id: IdentifierString
    binding_id: IdentifierString
    manifest_id: IdentifierString
    state_model_identifier: IdentifierString
    state_model_id: IdentifierString
    state_field_id: IdentifierString
    state_field_value_kind: Literal["integer", "number"]
    distribution_kind: DistributionKind
    sampler_version: SamplerVersion
    quantization_policy: QuantizationPolicy
    quantization_fraction_bits: QuantizationFractionBits
    draw_index: int = Field(ge=0)
    draw_count: int = Field(ge=1)
    sampled_raw_value: int | float
    realized_value: int | float

    @model_validator(mode="before")
    @classmethod
    def _raw_numerics_must_be_exact_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in ("sampled_raw_value", "realized_value"):
            raw = data.get(key)
            if not _is_exact_finite_numeric(raw):
                raise ValueError(f"{key} must be an exact finite numeric value")
        return data

    @model_validator(mode="after")
    def _draw_count_and_kind(self) -> SampledStateFieldValue:
        if self.draw_count != WORD_COUNT[self.distribution_kind]:
            raise ValueError(
                "draw_count must equal the distribution kind's digest-word consumption"
            )
        if isinstance(self.sampled_raw_value, float) and not math.isfinite(self.sampled_raw_value):
            raise ValueError("sampled_raw_value must be finite")
        if isinstance(self.realized_value, float) and not math.isfinite(self.realized_value):
            raise ValueError("realized_value must be finite")
        if self.state_field_value_kind == "integer" and not isinstance(self.realized_value, int):
            raise ValueError("integer targets require an exact integer realized_value")
        return self


class RealizedStateFieldValue(BaseModel):
    """One realized initial-state override for one targeted field.

    Part of the complete override delta: exactly one entry per
    uncertainty binding, none for untargeted base-state fields. The
    value is an exact finite numeric that satisfies the authoritative
    target kind.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_model_identifier: IdentifierString
    state_field_id: IdentifierString
    value: JsonValue

    @model_validator(mode="before")
    @classmethod
    def _raw_value_must_be_exact_finite_numeric(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if not _is_exact_finite_numeric(data.get("value")):
            raise ValueError("value must be an exact finite numeric value")
        return data


class WorldUncertaintyModel(VersionedContract):
    """The immutable one-per-scenario uncertainty model.

    Declares the complete uncertainty binding tuple for one stored
    scenario, canonicalized into the exact ``(manifest_id,
    state_model_id, state_field_id)`` target-tuple order (caller
    declaration order never affects the artifact). At least one binding
    is required (an absent model is the only representation of empty
    uncertainty), each complete target tuple appears exactly once, and
    only ``integer`` and ``number`` initial-state fields may be
    targeted. The identifier is independently derived from the
    canonical tenant/scenario/scenario-hash identity, the content hash
    covers the complete canonical serialization excluding itself, and
    ``declared_at`` is the deterministic caller-supplied timestamp. The
    model must be declared before the first world compilation of the
    scenario and can never be updated, replaced, deleted, or
    re-declared.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: IdentifierString
    scenario_content_hash: Sha256Hex
    bindings: tuple[StateFieldUncertaintyBinding, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bindings_are_unique(self) -> WorldUncertaintyModel:
        targets = [
            (binding.manifest_id, binding.state_model_id, binding.state_field_id)
            for binding in self.bindings
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("bindings must carry unique target tuples")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> WorldUncertaintyModel:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class WorldRealization(VersionedContract):
    """One strategy-independent realization of one world under one shared seed.

    Deterministically derived from the compiled world, the embedded
    uncertainty model (or its absence), and the exact campaign seed:
    the ordered sampled values in canonical binding order, the complete
    realized initial-state override delta, the world and seed
    identity/hash provenance, the uncertainty-model identity/hash (both
    ``None`` exactly when the world has no model), the frozen
    sampler/quantization provenance, the deterministic independently
    derived identifier (covering world and seed identities *and* their
    content hashes, the model identity/hash or the explicit ``absent``
    marker, and the sampler/quantization provenance - never derived
    from the content hash), the self-covering content hash, and the
    authoritative recorded ``realized_at`` (the campaign ``created_at``
    - never the wall clock).

    Digest-word draw indexes are contiguous: sampled values are ordered
    by ``draw_index``, the first begins at zero, and every next index
    equals the previous index plus the previous ``draw_count``, so the
    ranges partition ``[0, total_words)`` with no gaps or overlaps.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    scenario_seed_id: IdentifierString
    seed_content_hash: Sha256Hex
    uncertainty_model_id: IdentifierString | None = None
    uncertainty_model_content_hash: Sha256Hex | None = None
    sampler_version: SamplerVersion
    quantization_policy: QuantizationPolicy
    quantization_fraction_bits: QuantizationFractionBits
    sampled_values: tuple[SampledStateFieldValue, ...] = Field(default_factory=tuple)
    realized_initial_state_overrides: tuple[RealizedStateFieldValue, ...] = Field(
        default_factory=tuple
    )
    content_hash: Sha256Hex
    realized_at: AwareDatetime

    @model_validator(mode="after")
    def _model_provenance_both_or_neither(self) -> WorldRealization:
        if (self.uncertainty_model_id is None) != (self.uncertainty_model_content_hash is None):
            raise ValueError(
                "uncertainty_model_id and uncertainty_model_content_hash must both be "
                "present or both be absent"
            )
        return self

    @model_validator(mode="after")
    def _draw_indexes_are_contiguous(self) -> WorldRealization:
        expected = 0
        for sampled in self.sampled_values:
            if sampled.draw_index != expected:
                raise ValueError(
                    "sampled value draw indexes must be contiguous from zero "
                    "with no gaps or overlaps"
                )
            expected += sampled.draw_count
        return self

    @model_validator(mode="after")
    def _overrides_agree_one_to_one(self) -> WorldRealization:
        if len(self.realized_initial_state_overrides) != len(self.sampled_values):
            raise ValueError(
                "realized_initial_state_overrides must have exactly one entry per sampled value"
            )
        pairs: set[tuple[str, str]] = set()
        for override, sampled in zip(
            self.realized_initial_state_overrides, self.sampled_values, strict=True
        ):
            if override.state_model_identifier != sampled.state_model_identifier:
                raise ValueError("override state-model identity does not match its sampled value")
            if override.state_field_id != sampled.state_field_id:
                raise ValueError("override state-field identity does not match its sampled value")
            pair = (override.state_model_identifier, override.state_field_id)
            if pair in pairs:
                raise ValueError("override target pairs must be unique")
            pairs.add(pair)
        return self


class CampaignWorldRealizationMatrix(VersionedContract):
    """The deterministic world-realization matrix of one campaign.

    Exactly one ``WorldRealization`` per campaign seed, in the exact
    campaign seed-ensemble order, with complete world/model/sampler
    provenance. Strategy identifiers appear nowhere: realizations are
    intentionally strategy-independent, so the matrix is a pure
    function of the campaign identity, the compiled world, the embedded
    uncertainty model (or its absence), and the seed ensemble - never
    of execution status or strategy count/order. The identifier is
    independently derived from the canonical
    campaign/world/model/sampler identity (never from the content
    hash), the content hash covers the complete canonical serialization
    excluding itself, and ``assembled_at`` is the authoritative
    recorded campaign ``created_at``. The matrix is derived in memory
    and never stored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    uncertainty_model_id: IdentifierString | None = None
    uncertainty_model_content_hash: Sha256Hex | None = None
    sampler_version: SamplerVersion
    quantization_policy: QuantizationPolicy
    quantization_fraction_bits: QuantizationFractionBits
    ordered_scenario_seed_ids: tuple[IdentifierString, ...] = Field(min_length=1)
    realizations: tuple[WorldRealization, ...] = Field(min_length=1)
    content_hash: Sha256Hex
    assembled_at: AwareDatetime

    @model_validator(mode="after")
    def _matrix_shape_and_provenance(self) -> CampaignWorldRealizationMatrix:
        if (self.uncertainty_model_id is None) != (self.uncertainty_model_content_hash is None):
            raise ValueError(
                "uncertainty_model_id and uncertainty_model_content_hash must both be "
                "present or both be absent"
            )
        seed_ids = list(self.ordered_scenario_seed_ids)
        if len(seed_ids) != len(set(seed_ids)):
            raise ValueError("ordered_scenario_seed_ids must be unique")
        if len(self.realizations) != len(seed_ids):
            raise ValueError("exactly one realization per seed is required")
        for position, realization in enumerate(self.realizations):
            if realization.scenario_seed_id != seed_ids[position]:
                raise ValueError("realization seed identity does not match its seed position")
            if realization.scenario_id != self.scenario_id:
                raise ValueError("realization scenario identity mismatch")
            if realization.world_version_id != self.world_version_id:
                raise ValueError("realization world identity mismatch")
            if realization.world_content_hash != self.world_content_hash:
                raise ValueError("realization world content hash mismatch")
            if realization.uncertainty_model_id != self.uncertainty_model_id:
                raise ValueError("realization uncertainty-model identity mismatch")
            if realization.uncertainty_model_content_hash != self.uncertainty_model_content_hash:
                raise ValueError("realization uncertainty-model content hash mismatch")
            if realization.sampler_version != self.sampler_version:
                raise ValueError("realization sampler version mismatch")
            if realization.quantization_policy != self.quantization_policy:
                raise ValueError("realization quantization policy mismatch")
            if realization.quantization_fraction_bits != self.quantization_fraction_bits:
                raise ValueError("realization quantization fraction bits mismatch")
        return self
