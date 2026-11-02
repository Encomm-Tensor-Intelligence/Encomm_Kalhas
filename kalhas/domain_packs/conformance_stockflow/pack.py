"""Conformance stock-flow v0.1 DomainPack identity and composition (H29-S07).

Builds the complete deterministic identity of the synthetic, non-health
conformance fixture release and composes it into the single concrete
:class:`ConformanceStockFlowV01DomainPack` entry point satisfying the
generic ``DomainPack`` protocol. Everything here is frozen declarative
data computed from fixed constants; construction is byte-identical on
every invocation, performs no I/O, reads no clock, environment,
platform, or filesystem value, draws no randomness, and never mutates
any global.

The fixture proves domain neutrality of the generic mechanism seam: it
is exercised through exactly the same ``DomainPack`` protocol and
dispatcher as any other pack. It is never a product pack and assigns
no maturity value anywhere; the ``conformance_only`` label belongs to a
later assurance slice.

Identity
--------

- pack ``kalhas-conformance-stockflow`` version ``0.1.0``, tenant
  ``kalhas-synthetic``;
- mechanism ``stockflow-single-bin`` version ``0.1.0``, protocol
  ``1.0.0``, exactly one step timestep;
- numeric profile ``kalhas-platform-bound-binary64-v1``, precision
  ``ieee-754-binary64``, rounding ``round-to-nearest-ties-to-even``,
  with the four emitted quantities declared as named quantization
  boundaries of quantum ``1`` (unit ``units``);
- declaration timestamps are fixed timezone-aware constants (never the
  wall clock); identifiers contain no random or process-dependent part.

The five fixture-owned schema descriptors are immutable nested
scalar/tuple constants; private builders return a fresh exact JSON
dictionary per call. Each descriptor is hashed canonically and bound
into the mechanism specification together with the implementation hash
of the exact ``mechanism.py`` file bytes and the dependency-lock hash
of the exact unchanged ``uv.lock`` release. These bindings are fixed
declarative identity data; the pack never reads any file (the on-disk
equality proofs live only in the test module).

Direct :meth:`ConformanceStockFlowV01DomainPack.step` execution fails
closed, purely and in memory, whenever any pack authority has been
replaced or mutated: the authorities must be exactly the shipped v1
contract types, the mechanism protocol attribute must equal the frozen
constant, every hash must recompute, the profile must embed the pack's
manifest and mechanism specification, and every authority must equal an
independently rebuilt pristine authority. A coordinated forgery that
re-hashes consistently still fails closed because it is not this exact
frozen release. Nothing is ever repaired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismParameterBinding,
    MechanismPlatformIdentity,
    MechanismQuantizationBoundary,
)
from kalhas.contracts.v1.domain_pack import DomainPackCapability, DomainPackManifest
from kalhas.contracts.v1.model_pack import (
    ModelPackAssumption,
    ModelPackIntendedUse,
    ModelPackLimitation,
    ModelPackProvenance,
    ModelPackReleaseProfile,
    ModelPackResourceEnvelope,
    ModelPackScope,
    ModelPackUnitDeclaration,
    ProhibitedUseValue,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs.conformance_stockflow.mechanism import (
    CONFIGURATION_KEYS,
    EVENT_IDS,
    IMPLEMENTATION_ID,
    IMPLEMENTATION_VERSION,
    MECHANISM_PROTOCOL_VERSION,
    QUANTITY_IDS,
    SOLVER_ID,
    SOLVER_VERSION,
    ConformanceStockFlowError,
    run_stockflow_step,
)

__all__ = ["ConformanceStockFlowV01DomainPack"]

#: The exact synthetic release identity of this fixture.
PACK_ID = "kalhas-conformance-stockflow"
PACK_VERSION = "0.1.0"
MECHANISM_ID = "stockflow-single-bin"
MECHANISM_VERSION = "0.1.0"
TENANT_ID = "kalhas-synthetic"
MANIFEST_IDENTIFIER = "manifest-kalhas-conformance-stockflow-0-1-0"
SPEC_IDENTIFIER = "mechanism-spec-kalhas-conformance-stockflow-0-1-0"
PROFILE_IDENTIFIER = "release-profile-kalhas-conformance-stockflow-0-1-0"
SCHEMA_VERSION = "1.0.0"

#: The SHA-256 digest of the exact finalized bytes of this pack's
#: ``mechanism.py`` implementation file. Fixed declarative identity
#: data: the pack never reads the file; the on-disk equality proof is a
#: test-only check.
CONFORMANCE_STOCKFLOW_IMPLEMENTATION_HASH = (
    "4966d2235415d4bcdcfe76305c40164124d27a72cf770480e272bdf79890a42f"
)

#: The SHA-256 digest of the exact unchanged dependency-lock release
#: bytes of this repository, proven against the on-disk file by tests.
CONFORMANCE_STOCKFLOW_DEPENDENCY_LOCK_HASH = (
    "0c5c4f978111d01bec3bcefaf5186964ee2c2fab4fa4d3f26937b3857205f422"
)

#: Fixed timezone-aware declaration timestamps (never the wall clock).
DECLARED_AT = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
MANIFEST_CREATED_AT = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

#: Declared platform identity, identical to the recorded development
#: profile; no cross-platform equivalence is claimed anywhere.
PLATFORM_OS_NAME = "windows-x86-64"
PLATFORM_ARCHITECTURE = "x86-64"
PLATFORM_PYTHON_IMPLEMENTATION = "cpython"
PLATFORM_PYTHON_VERSION = "3.12"

#: The fixture-owned state schema descriptor (immutable declaration).
STATE_SCHEMA_ID = "kalhas-conformance-stockflow-v01-state"
_STATE_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("bound", "0 <= level <= configuration.capacity"),
    ("key_type", "non_negative_integer"),
    ("quantity_unit", "units"),
    ("required_keys", ("level",)),
    ("schema_id", STATE_SCHEMA_ID),
    ("schema_kind", "pack_owned_state"),
)

#: The fixture-owned action schema descriptor (immutable declaration).
ACTION_SCHEMA_ID = "kalhas-conformance-stockflow-v01-action"
_ACTION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("bound", "0 <= release <= configuration.max_release"),
    ("key_type", "non_negative_integer"),
    ("required_keys", ("release",)),
    ("schema_id", ACTION_SCHEMA_ID),
    ("schema_kind", "pack_owned_action"),
    ("semantics", "declared_conditional_release_request_only"),
    ("unit", "units"),
)

#: The fixture-owned configuration schema descriptor.
CONFIGURATION_SCHEMA_ID = "kalhas-conformance-stockflow-v01-configuration"
_CONFIGURATION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("immutability", "fixed_by_mechanism_specification"),
    ("key_type", "integer"),
    ("positive_keys", ("capacity",)),
    ("non_negative_keys", ("inflow", "max_release")),
    ("required_keys", tuple(CONFIGURATION_KEYS)),
    ("schema_id", CONFIGURATION_SCHEMA_ID),
    ("schema_kind", "pack_owned_configuration"),
    ("unit", "units"),
)

#: The fixture-owned emission schema descriptor.
EMISSION_SCHEMA_ID = "kalhas-conformance-stockflow-v01-emission"
_EMISSION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("declared_quantities", tuple(QUANTITY_IDS)),
    ("ordering", "declared_quantity_order"),
    ("payload_type", "exact_json_object"),
    ("quantity_unit", "units"),
    ("schema_id", EMISSION_SCHEMA_ID),
    ("schema_kind", "pack_owned_emission"),
)

#: The fixture-owned evidence schema descriptor.
EVIDENCE_SCHEMA_ID = "kalhas-conformance-stockflow-v01-evidence"
_EVIDENCE_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("event_order", tuple(EVENT_IDS)),
    ("payload_type", "exact_json_object"),
    (
        "records",
        (
            "conditional_modeled_outcomes_label",
            "declared_event_order",
            "before_after_conservation_totals",
            "ordered_emitted_quantities",
        ),
    ),
    ("schema_id", EVIDENCE_SCHEMA_ID),
    ("schema_kind", "pack_owned_evidence"),
    ("stochastic_draws", 0),
)

#: The exact immutable configuration of the v0.1 release (units).
_CONFIGURATION_HASH_PAYLOAD: tuple[tuple[str, int], ...] = (
    ("capacity", 10),
    ("inflow", 3),
    ("max_release", 5),
)


def _payload_from_pairs(pairs: tuple[tuple[str, object], ...]) -> dict[str, object]:
    """One fresh exact JSON dictionary from an immutable pair sequence.

    Nested sequences are converted to fresh lists so the returned value
    is a plain canonical-shape JSON object; the input is never mutated
    and never shared with the caller.
    """

    def convert(value: object) -> object:
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        return value

    return {key: convert(value) for key, value in pairs}


def _state_schema() -> dict[str, object]:
    """One fresh exact state-schema descriptor dictionary."""
    return _payload_from_pairs(_STATE_SCHEMA_HASH_PAYLOAD)


def _action_schema() -> dict[str, object]:
    """One fresh exact action-schema descriptor dictionary."""
    return _payload_from_pairs(_ACTION_SCHEMA_HASH_PAYLOAD)


def _configuration_schema() -> dict[str, object]:
    """One fresh exact configuration-schema descriptor dictionary."""
    return _payload_from_pairs(_CONFIGURATION_SCHEMA_HASH_PAYLOAD)


def _emission_schema() -> dict[str, object]:
    """One fresh exact emission-schema descriptor dictionary."""
    return _payload_from_pairs(_EMISSION_SCHEMA_HASH_PAYLOAD)


def _evidence_schema() -> dict[str, object]:
    """One fresh exact evidence-schema descriptor dictionary."""
    return _payload_from_pairs(_EVIDENCE_SCHEMA_HASH_PAYLOAD)


def _configuration() -> dict[str, JsonValue]:
    """One fresh exact immutable-configuration dictionary."""
    return dict(_CONFIGURATION_HASH_PAYLOAD)


def _schema_hash(schema: dict[str, object]) -> str:
    """Canonical SHA-256 of one pack-owned schema descriptor."""
    return sha256_hex(canonical_json(schema))


def _self_covering_hash(model: BaseModel) -> str:
    """Canonical SHA-256 over the model's JSON content minus its own hash."""
    dumped: dict[str, object] = model.model_dump(mode="json")
    dumped.pop("content_hash")
    return sha256_hex(canonical_json(dumped))


def _build_manifest() -> DomainPackManifest:
    """Build the frozen synthetic manifest of the v0.1 release."""
    manifest = DomainPackManifest(
        identifier=MANIFEST_IDENTIFIER,
        tenant_id=TENANT_ID,
        pack_id=PACK_ID,
        name="KALHAS conformance stock-flow fixture pack",
        pack_version=PACK_VERSION,
        description=(
            "Minimal deterministic synthetic single-bin stock-flow fixture "
            "for architecture conformance only"
        ),
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier=MECHANISM_ID,
                description=(
                    "One-step deterministic integer balance of a bounded level "
                    "with a fixed inflow and a requested release"
                ),
                input_ids=("state", "release"),
                output_ids=("next_state", "emissions", "evidence"),
                metadata={"declared_timestep_unit": "step", "stochastic_draws": 0},
            ),
        ),
        schema_metadata={"declarative": True},
        content_hash="0" * 64,
        created_at=MANIFEST_CREATED_AT,
        metadata={
            "decision_support_only": True,
            "synthetic_only": True,
            "no_real_data": True,
            "conformance_fixture": True,
        },
    )
    return manifest.model_copy(update={"content_hash": manifest_content_hash(manifest)})


def _build_spec(manifest: DomainPackManifest) -> DomainMechanismSpec:
    """Build the frozen mechanism specification of the v0.1 release."""
    quantization = tuple(
        MechanismQuantizationBoundary(
            boundary_id=f"quantity:{quantity_id}", quantum=1, unit="units"
        )
        for quantity_id in QUANTITY_IDS
    )
    parameter_bindings = tuple(
        MechanismParameterBinding(parameter_id=key, unit="units") for key in CONFIGURATION_KEYS
    )
    configuration = _configuration()
    spec = DomainMechanismSpec(
        identifier=SPEC_IDENTIFIER,
        tenant_id=TENANT_ID,
        schema_version=SCHEMA_VERSION,
        pack_id=PACK_ID,
        pack_version=PACK_VERSION,
        manifest_id=manifest.identifier,
        manifest_content_hash=manifest.content_hash,
        mechanism_id=MECHANISM_ID,
        mechanism_version=MECHANISM_VERSION,
        mechanism_protocol_version=MECHANISM_PROTOCOL_VERSION,
        state_schema_id=STATE_SCHEMA_ID,
        action_schema_id=ACTION_SCHEMA_ID,
        configuration_schema_id=CONFIGURATION_SCHEMA_ID,
        emission_schema_id=EMISSION_SCHEMA_ID,
        evidence_schema_id=EVIDENCE_SCHEMA_ID,
        state_schema_hash=_schema_hash(_state_schema()),
        action_schema_hash=_schema_hash(_action_schema()),
        configuration_schema_hash=_schema_hash(_configuration_schema()),
        emission_schema_hash=_schema_hash(_emission_schema()),
        evidence_schema_hash=_schema_hash(_evidence_schema()),
        configuration=configuration,
        configuration_hash=sha256_hex(canonical_json(configuration)),
        implementation_id=IMPLEMENTATION_ID,
        implementation_version=IMPLEMENTATION_VERSION,
        implementation_hash=CONFORMANCE_STOCKFLOW_IMPLEMENTATION_HASH,
        dependency_lock_hash=CONFORMANCE_STOCKFLOW_DEPENDENCY_LOCK_HASH,
        solver_id=SOLVER_ID,
        solver_version=SOLVER_VERSION,
        data_identities=(),
        parameter_bindings=parameter_bindings,
        timestep=1,
        timestep_unit="step",
        event_order=EVENT_IDS,
        reduction_order=("declared_integer_balance",),
        numeric_profile="kalhas-platform-bound-binary64-v1",
        precision="ieee-754-binary64",
        rounding_mode="round-to-nearest-ties-to-even",
        quantization_boundaries=quantization,
        platform_identity=MechanismPlatformIdentity(
            os_name=PLATFORM_OS_NAME,
            architecture=PLATFORM_ARCHITECTURE,
            python_implementation=PLATFORM_PYTHON_IMPLEMENTATION,
            python_version=PLATFORM_PYTHON_VERSION,
            dependency_lock_hash=CONFORMANCE_STOCKFLOW_DEPENDENCY_LOCK_HASH,
            implementation_id=IMPLEMENTATION_ID,
            implementation_version=IMPLEMENTATION_VERSION,
            implementation_hash=CONFORMANCE_STOCKFLOW_IMPLEMENTATION_HASH,
            solver_id=SOLVER_ID,
            solver_version=SOLVER_VERSION,
            numeric_profile="kalhas-platform-bound-binary64-v1",
        ),
        content_hash="0" * 64,
        declared_at=DECLARED_AT,
        metadata={
            "stochastic_draws": 0,
            "exogenous_inputs": "declared_empty",
            "synthetic_only": True,
        },
    )
    spec = spec.model_copy(update={"content_hash": _self_covering_hash(spec)})
    return spec


def _build_release_profile(
    manifest: DomainPackManifest, spec: DomainMechanismSpec
) -> ModelPackReleaseProfile:
    """Build the frozen release profile of the v0.1 release.

    Truthfully declares the decision-support floor, synthetic-only
    provenance, empty datasets, units, bounded scope, assumptions,
    limitations, and a small local resource envelope. No maturity value
    is assigned anywhere.
    """
    prohibited_uses: tuple[ProhibitedUseValue, ...] = (
        "autonomous_public_decisions",
        "eligibility_or_benefit_decisions",
        "enforcement_recommendations",
        "predictive_policing_judgments",
        "individual_or_social_scoring",
        "political_persuasion",
        "voter_targeting",
        "biometric_or_surveillance_assessment",
        "offensive_cyber_action",
        "live_effects",
    )
    profile = ModelPackReleaseProfile(
        identifier=PROFILE_IDENTIFIER,
        tenant_id=TENANT_ID,
        schema_version=SCHEMA_VERSION,
        pack_id=PACK_ID,
        pack_version=PACK_VERSION,
        manifest_id=manifest.identifier,
        manifest_content_hash=manifest.content_hash,
        manifest=manifest,
        mechanism_id=MECHANISM_ID,
        mechanism_version=MECHANISM_VERSION,
        mechanism_protocol_version=MECHANISM_PROTOCOL_VERSION,
        configuration_identity=spec.configuration_hash,
        mechanism_spec=spec,
        decision_scope="decision_support_only",
        accountability="accountable_human_authority_required",
        output_labeling="conditional_modeled_outcomes",
        scope=ModelPackScope(
            decision_questions=(
                "how_does_the_synthetic_level_move_after_one_declared_step",
                "how_does_the_declared_release_request_change_the_next_level",
            ),
            intended_users=(
                "kalhas_architecture_reviewer",
                "kalhas_conformance_engineer",
            ),
            horizon="exactly_one_declared_step",
            resolution="one_step",
            validity_envelope=(
                "small_synthetic_levels_with_non_negative_integer_counts, "
                "exact_balance_conservation, and level_within_declared_capacity"
            ),
        ),
        units=(
            ModelPackUnitDeclaration(quantity_id="level", unit="units"),
            ModelPackUnitDeclaration(quantity_id="release", unit="units"),
            ModelPackUnitDeclaration(quantity_id="configuration_quantities", unit="units"),
            ModelPackUnitDeclaration(quantity_id="timestep", unit="step"),
            ModelPackUnitDeclaration(quantity_id="emission_quantities", unit="units"),
        ),
        provenance=ModelPackProvenance(
            author_id="kalhas-phase29-h29-s07",
            method="deterministic_synthetic_construction",
            statement=(
                "Entirely synthetic conformance fixture for architecture "
                "conformance only; it has no real-world meaning and contains "
                "no real person, organization, or company data"
            ),
        ),
        datasets=(),
        resource_envelope=ModelPackResourceEnvelope(
            max_memory_megabytes=64,
            max_cpu_seconds=1,
            memory_unit="MiB",
            cpu_unit="seconds",
        ),
        intended_uses=(
            ModelPackIntendedUse(
                use_id="synthetic_architecture_conformance",
                statement=(
                    "Proving that the generic domain-pack mechanism seam is "
                    "domain-neutral by exercising it with a minimal "
                    "deterministic synthetic fixture"
                ),
                horizon="exactly_one_declared_step",
            ),
        ),
        prohibited_uses=prohibited_uses,
        assumptions=(
            ModelPackAssumption(
                assumption_id="conformance_fixture_only",
                statement=(
                    "This release is a conformance fixture with no "
                    "real-world meaning; its quantities model nothing "
                    "outside the synthetic architecture test"
                ),
            ),
            ModelPackAssumption(
                assumption_id="fully_deterministic_no_stochastic_draw",
                statement=(
                    "The fixture uses no stochastic draw; every outcome is a "
                    "declared deterministic function of the validated inputs"
                ),
            ),
            ModelPackAssumption(
                assumption_id="integer_arithmetic_only",
                statement="All authoritative quantities stay in exact integer arithmetic",
            ),
        ),
        limitations=(
            ModelPackLimitation(
                limitation_id="no_empirical_adequacy_claim",
                statement="The fixture makes no claim of empirical adequacy for anything real",
            ),
            ModelPackLimitation(
                limitation_id="no_calibration_or_benchmark_evidence",
                statement="No calibration or benchmark evidence exists for this release",
            ),
            ModelPackLimitation(
                limitation_id="no_real_world_forecasting_claim",
                statement="The fixture makes no real-world forecasting claim of any kind",
            ),
            ModelPackLimitation(
                limitation_id="no_operational_decision_use",
                statement=(
                    "The fixture must never inform operational decisions; "
                    "accountable human authority is required for any "
                    "decision support use"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_cross_platform_equivalence_claim",
                statement=(
                    "Exact replay is claimed only under the recorded "
                    "Windows/x86-64/CPython-3.12 development platform "
                    "identity; no cross-platform equivalence is claimed"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_autonomous_or_live_action",
                statement=(
                    "The fixture performs no autonomous or live action and "
                    "can never cause real-world effects"
                ),
            ),
            ModelPackLimitation(
                limitation_id="single_synthetic_scenario_shape_only",
                statement="Only the single declared single-bin balance shape is covered",
            ),
        ),
        content_hash="0" * 64,
        declared_at=DECLARED_AT,
        metadata={
            "synthetic_only": True,
            "no_real_data": True,
            "stochastic_draws": 0,
        },
    )
    profile = profile.model_copy(update={"content_hash": _self_covering_hash(profile)})
    return profile


def _pack_authorities_fail_closed(pack: ConformanceStockFlowV01DomainPack) -> None:
    """Fail closed when any pack authority was replaced or mutated.

    Purely in-memory verification executed before every direct step.
    The three authorities must be exactly the shipped v1 contract types
    and the pack-level mechanism protocol attribute must equal the
    frozen constant. The manifest content hash and the mechanism-spec
    and release-profile self-covering hashes must recompute exactly, the
    release profile must embed the pack's manifest and mechanism
    specification, and every authority must equal the pristine authority
    rebuilt in memory by the same deterministic private builders. The
    pristine-equality anchors are decisive: a coordinated attacker who
    replaces a field and re-hashes every authority consistently still
    fails closed, because the forged chain is self-consistent but is not
    this exact frozen release. No filesystem, environment, platform,
    clock, or randomness access exists here, and the expected
    authorities are constructed fresh inside every call.
    """
    manifest = pack.manifest
    spec = pack.mechanism_spec
    profile = pack.release_profile
    if type(manifest) is not DomainPackManifest:
        raise ConformanceStockFlowError("pack manifest is not the exact shipped contract type")
    if type(spec) is not DomainMechanismSpec:
        raise ConformanceStockFlowError(
            "mechanism specification is not the exact shipped contract type"
        )
    if type(profile) is not ModelPackReleaseProfile:
        raise ConformanceStockFlowError("release profile is not the exact shipped contract type")
    if pack.mechanism_protocol_version != MECHANISM_PROTOCOL_VERSION:
        raise ConformanceStockFlowError(
            "pack mechanism protocol version is not the frozen release value"
        )
    if manifest_content_hash(manifest) != manifest.content_hash:
        raise ConformanceStockFlowError("pack manifest content hash does not recompute")
    if _self_covering_hash(spec) != spec.content_hash:
        raise ConformanceStockFlowError("mechanism specification self hash does not recompute")
    if _self_covering_hash(profile) != profile.content_hash:
        raise ConformanceStockFlowError("release profile self hash does not recompute")
    if profile.manifest != manifest:
        raise ConformanceStockFlowError("release profile does not embed the pack manifest")
    if profile.mechanism_spec != spec:
        raise ConformanceStockFlowError(
            "release profile does not embed the mechanism specification"
        )
    if manifest != _build_manifest():
        raise ConformanceStockFlowError(
            "pack manifest is not the exact frozen v0.1 release manifest"
        )
    expected_spec = _build_spec(_build_manifest())
    if spec != expected_spec:
        raise ConformanceStockFlowError(
            "mechanism specification is not the exact frozen v0.1 release specification"
        )
    if profile != _build_release_profile(_build_manifest(), expected_spec):
        raise ConformanceStockFlowError(
            "release profile is not the exact frozen v0.1 release profile"
        )


class ConformanceStockFlowV01DomainPack:
    """The concrete synthetic conformance stock-flow v0.1 DomainPack.

    Structurally satisfies the generic ``DomainPack`` protocol: the
    frozen ``DomainPackManifest``, the exact ``ModelPackReleaseProfile``
    release identity, the frozen mechanism protocol version ``1.0.0``,
    and exactly one public executable operation, the pure :meth:`step`
    transition. No second executable method, scheduler, lifecycle,
    callback, loader, resolver, registry, or plugin surface exists.
    """

    __slots__ = ("manifest", "mechanism_protocol_version", "mechanism_spec", "release_profile")

    manifest: DomainPackManifest
    mechanism_spec: DomainMechanismSpec
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def __init__(self) -> None:
        self.manifest = _build_manifest()
        self.mechanism_spec = _build_spec(self.manifest)
        self.release_profile = _build_release_profile(self.manifest, self.mechanism_spec)
        self.mechanism_protocol_version: Literal["1.0.0"] = MECHANISM_PROTOCOL_VERSION

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        """The single pure conformance stock-flow mechanism transition.

        Fails closed if any pack authority has been replaced or
        mutated, then validates the request against the frozen
        authorities and returns the complete verified
        ``DomainMechanismStepResult``; every invalid input raises
        :class:`ConformanceStockFlowError` and nothing is repaired.
        Identical inputs always produce byte-identical results, and the
        request is never mutated or aliased by the result.
        """
        _pack_authorities_fail_closed(self)
        return run_stockflow_step(request, self.mechanism_spec, self.release_profile)
