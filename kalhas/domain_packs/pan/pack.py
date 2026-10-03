"""PAN v0.1 DomainPack identity and composition (H29-S04).

Builds the complete deterministic identity of the minimal synthetic
KALHAS-PAN v0.1 release and composes it into the single concrete
:class:`PanV01DomainPack` entry point satisfying the generic
``DomainPack`` protocol.  Everything here is frozen declarative data
computed once at import time from fixed constants; construction is
byte-identical on every invocation, performs no I/O, reads no clock,
environment, platform, or filesystem value, draws no randomness, and
never mutates any global.

Identity
--------

- pack ``kalhas-pan`` version ``0.1.0``, tenant ``kalhas-synthetic``;
- mechanism ``pan-compartment-flow`` version ``0.1.0``, protocol
  ``1.0.0``, exactly one day timestep;
- numeric profile ``kalhas-platform-bound-binary64-v1``, precision
  ``ieee-754-binary64``, rounding ``round-to-nearest-ties-to-even``,
  with the eight per-event count boundaries declared as named
  quantization boundaries of quantum ``1`` (unit ``persons``);
- declaration timestamps are fixed timezone-aware constants (never the
  wall clock); identifiers contain no random or process-dependent part.

The five pack-owned schema descriptors (state, action, configuration,
emission, evidence) are declared as immutable nested scalar/tuple
constants; private builders return a fresh exact JSON dictionary per
call, so no mutable module-level dictionary, list, or set authority
exists and no descriptor content is shared as mutable global state.
Each descriptor is hashed canonically and bound into the mechanism
specification together with the implementation hash of the exact
finalized ``mechanism.py`` file bytes and the dependency-lock hash of
the exact unchanged ``uv.lock`` release.  These bindings are fixed
declarative identity data; the pack never reads any file at execution
or construction time (the on-disk equality proofs live only in the
test module).

The release profile truthfully declares decision-support-only scope,
conditional modeled outcomes, accountable human authority, the
mandatory closed prohibited-use floor, synthetic/reference-only
provenance, an empty dataset list, declared units, bounded decision
questions, a one-day resolution, a small synthetic validity envelope,
intended uses limited to synthetic architecture/conformance
exploration, explicit assumptions and limitations, and a small local
resource envelope.  No maturity value is assigned anywhere: maturity
is evidence-derived in a later slice.

Direct :meth:`PanV01DomainPack.step` execution fails closed, purely and
in memory, whenever any pack authority has been replaced or mutated:
the three authorities must be exactly the shipped v1 contract types,
the pack-level mechanism protocol attribute must equal the frozen
protocol constant, the manifest content hash and the mechanism-spec
and release-profile self-covering hashes must all recompute exactly,
the profile must embed the pack's manifest and mechanism
specification, and every authority must equal an independently rebuilt
pristine authority produced in memory by the same deterministic
private builders that constructed the release.  The pristine-equality
anchors cover every release-critical field automatically, so a
coordinated attacker who replaces any field and correctly recomputes
every hash still fails closed: the forged chain is self-consistent,
but it is not this exact frozen release.  Nothing is ever repaired; a
tampered authority raises :class:`PanDomainPackError`.

PAN stays fully isolated below ``kalhas/domain_packs/pan/``; nothing
outside this subpackage imports it, and no discovery, registration, or
runtime integration exists in this slice.
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
from kalhas.domain_packs.pan.mechanism import (
    BPS_MAX,
    CONFIGURATION_KEYS,
    EVENT_IDS,
    IMPLEMENTATION_ID,
    IMPLEMENTATION_VERSION,
    MECHANISM_PROTOCOL_VERSION,
    SOLVER_ID,
    SOLVER_VERSION,
    PanDomainPackError,
    run_pan_step,
)

__all__ = ["PanV01DomainPack"]

#: The exact synthetic release identity of this slice.
PACK_ID = "kalhas-pan"
PACK_VERSION = "0.1.0"
MECHANISM_ID = "pan-compartment-flow"
MECHANISM_VERSION = "0.1.0"
TENANT_ID = "kalhas-synthetic"
MANIFEST_IDENTIFIER = "manifest-kalhas-pan-0-1-0"
SPEC_IDENTIFIER = "mechanism-spec-kalhas-pan-0-1-0"
PROFILE_IDENTIFIER = "release-profile-kalhas-pan-0-1-0"
SCHEMA_VERSION = "1.0.0"

#: The SHA-256 digest of the exact finalized UTF-8 bytes of this pack's
#: ``mechanism.py`` implementation file.  Fixed declarative identity
#: data: the pack never reads the file at construction or execution
#: time; the on-disk equality proof is a test-only check.
PAN_IMPLEMENTATION_HASH = "947bfcca6d0b049439cecf08d110afd3b91f2b402a18c22cba45469f420d2774"

#: The SHA-256 digest of the exact unchanged dependency-lock release
#: bytes of this repository.  Fixed declarative identity data, proven
#: against the on-disk file by tests only.
PAN_DEPENDENCY_LOCK_HASH = "0c5c4f978111d01bec3bcefaf5186964ee2c2fab4fa4d3f26937b3857205f422"

#: Fixed timezone-aware declaration timestamps (never the wall clock).
DECLARED_AT = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
MANIFEST_CREATED_AT = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)

#: Declared platform identity of this Phase-29 development release.
#: Truthfully bounded to the recorded Windows/x86-64/CPython-3.12
#: development profile; no Linux, macOS, or cross-platform equivalence
#: is claimed anywhere.
PLATFORM_OS_NAME = "windows-x86-64"
PLATFORM_ARCHITECTURE = "x86-64"
PLATFORM_PYTHON_IMPLEMENTATION = "cpython"
PLATFORM_PYTHON_VERSION = "3.12"

#: The pack-owned state schema descriptor, declared as immutable nested
#: scalars and tuples.  Implementation data of this pack only: not a
#: public KALHAS contract and not a file under ``schemas/v1/``.
STATE_SCHEMA_ID = "kalhas-pan-v01-state"
_STATE_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("absorbing_keys", ("deceased",)),
    (
        "capacity_bounds",
        (
            ("hospitalized", "configuration.hospital_capacity"),
            ("intensive_care", "configuration.icu_capacity"),
        ),
    ),
    (
        "conservation",
        (
            "population_total == susceptible + exposed + infectious + "
            "hospitalized + intensive_care + recovered + deceased"
        ),
    ),
    ("key_type", "non_negative_integer"),
    (
        "required_keys",
        (
            "population_total",
            "susceptible",
            "exposed",
            "infectious",
            "hospitalized",
            "intensive_care",
            "recovered",
            "deceased",
        ),
    ),
    ("quantity_unit", "persons"),
    ("schema_id", STATE_SCHEMA_ID),
    ("schema_kind", "pack_owned_state"),
)

#: The pack-owned action schema descriptor (immutable declaration).
ACTION_SCHEMA_ID = "kalhas-pan-v01-action"
_ACTION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("inclusive_range", (0, BPS_MAX)),
    ("key_type", "integer"),
    ("required_keys", ("intervention_intensity_bps",)),
    ("schema_id", ACTION_SCHEMA_ID),
    ("schema_kind", "pack_owned_action"),
    ("semantics", "declared_conditional_intervention_intensity_only"),
    ("unit", "basis-points"),
)

#: The pack-owned configuration schema descriptor (immutable declaration).
CONFIGURATION_SCHEMA_ID = "kalhas-pan-v01-configuration"
_CONFIGURATION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    (
        "basis_point_keys",
        (
            "transmission_bps",
            "exposed_progression_bps",
            "hospital_admission_bps",
            "infectious_recovery_bps",
            "icu_admission_bps",
            "hospital_recovery_bps",
            "icu_mortality_bps",
            "icu_recovery_bps",
            "compliance_bps",
        ),
    ),
    ("basis_point_range", (0, BPS_MAX)),
    ("capacity_keys", ("hospital_capacity", "icu_capacity")),
    ("capacity_type", "non_negative_integer"),
    ("immutability", "fixed_by_mechanism_specification"),
    ("key_type", "integer"),
    ("required_keys", tuple(CONFIGURATION_KEYS)),
    ("schema_id", CONFIGURATION_SCHEMA_ID),
    ("schema_kind", "pack_owned_configuration"),
)

#: The pack-owned emission schema descriptor (immutable declaration).
EMISSION_SCHEMA_ID = "kalhas-pan-v01-emission"
_EMISSION_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    (
        "declared_quantities",
        (
            "new_exposures",
            "new_infectious",
            "hospital_admissions",
            "infectious_recoveries",
            "icu_admissions",
            "hospital_recoveries",
            "deaths",
            "icu_recoveries",
            "hospital_occupancy",
            "icu_occupancy",
        ),
    ),
    ("ordering", "declared_event_order_then_occupancy_summary"),
    ("payload_type", "exact_json_object"),
    ("quantity_unit", "persons"),
    ("schema_id", EMISSION_SCHEMA_ID),
    ("schema_kind", "pack_owned_emission"),
)

#: The pack-owned evidence schema descriptor (immutable declaration).
EVIDENCE_SCHEMA_ID = "kalhas-pan-v01-evidence"
_EVIDENCE_SCHEMA_HASH_PAYLOAD: tuple[tuple[str, object], ...] = (
    ("event_order", tuple(EVENT_IDS)),
    ("payload_type", "exact_json_object"),
    (
        "records",
        (
            "conditional_modeled_outcomes_label",
            "declared_event_order",
            "before_after_conservation_totals",
            "per_event_transition_count_and_source_pool",
            "zero_stochastic_draws_declaration",
        ),
    ),
    ("schema_id", EVIDENCE_SCHEMA_ID),
    ("schema_kind", "pack_owned_evidence"),
    ("stochastic_draws", 0),
)

#: The exact immutable configuration of the v0.1 release, declared as a
#: canonical ordered pair sequence (units: rates and compliance in
#: basis points, capacities in persons).
_CONFIGURATION_HASH_PAYLOAD: tuple[tuple[str, int], ...] = (
    ("transmission_bps", 1_000),
    ("exposed_progression_bps", 3_000),
    ("hospital_admission_bps", 2_000),
    ("infectious_recovery_bps", 1_000),
    ("icu_admission_bps", 5_000),
    ("hospital_recovery_bps", 2_000),
    ("icu_mortality_bps", 1_000),
    ("icu_recovery_bps", 4_000),
    ("hospital_capacity", 50),
    ("icu_capacity", 10),
    ("compliance_bps", 4_000),
)


def _payload_from_pairs(pairs: tuple[tuple[str, object], ...]) -> dict[str, object]:
    """One fresh exact JSON dictionary from an immutable pair sequence.

    Nested sequences are converted to fresh lists so the returned value
    is a plain canonical-shape JSON object; the input pair sequence is
    never mutated and never shared with the caller.
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
    """Canonical SHA-256 over the model's JSON content minus its own hash.

    The single repository hash rule: ``model_dump(mode="json")`` with
    the ``content_hash`` field itself excluded, canonically serialized
    and SHA-256 digested.
    """
    dumped: dict[str, object] = model.model_dump(mode="json")
    dumped.pop("content_hash")
    return sha256_hex(canonical_json(dumped))


def _build_manifest() -> DomainPackManifest:
    """Build the frozen synthetic manifest of the PAN v0.1 release."""
    manifest = DomainPackManifest(
        identifier=MANIFEST_IDENTIFIER,
        tenant_id=TENANT_ID,
        pack_id=PACK_ID,
        name="KALHAS PAN synthetic compartment-flow pack",
        pack_version=PACK_VERSION,
        description=(
            "Minimal deterministic synthetic compartment-flow domain pack "
            "for architecture and conformance exploration only"
        ),
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier=MECHANISM_ID,
                description=(
                    "One-day deterministic sequential compartment-flow "
                    "transition over eight integer compartment counts"
                ),
                input_ids=("state", "intervention_intensity_bps"),
                output_ids=("next_state", "emissions", "evidence"),
                metadata={"declared_timestep_unit": "day", "stochastic_draws": 0},
            ),
        ),
        schema_metadata={"declarative": True},
        content_hash="0" * 64,
        created_at=MANIFEST_CREATED_AT,
        metadata={
            "decision_support_only": True,
            "synthetic_only": True,
            "no_real_data": True,
        },
    )
    return manifest.model_copy(update={"content_hash": manifest_content_hash(manifest)})


def _build_spec(manifest: DomainPackManifest) -> DomainMechanismSpec:
    """Build the frozen mechanism specification of the v0.1 release."""
    quantization = tuple(
        MechanismQuantizationBoundary(boundary_id=f"count:{event_id}", quantum=1, unit="persons")
        for event_id in EVENT_IDS
    )
    parameter_bindings = tuple(
        MechanismParameterBinding(
            parameter_id=key,
            unit="basis-points" if key.endswith("_bps") else "persons",
        )
        for key in CONFIGURATION_KEYS
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
        implementation_hash=PAN_IMPLEMENTATION_HASH,
        dependency_lock_hash=PAN_DEPENDENCY_LOCK_HASH,
        solver_id=SOLVER_ID,
        solver_version=SOLVER_VERSION,
        data_identities=(),
        parameter_bindings=parameter_bindings,
        timestep=1,
        timestep_unit="day",
        event_order=EVENT_IDS,
        reduction_order=("declared_count_quantization",),
        numeric_profile="kalhas-platform-bound-binary64-v1",
        precision="ieee-754-binary64",
        rounding_mode="round-to-nearest-ties-to-even",
        quantization_boundaries=quantization,
        platform_identity=MechanismPlatformIdentity(
            os_name=PLATFORM_OS_NAME,
            architecture=PLATFORM_ARCHITECTURE,
            python_implementation=PLATFORM_PYTHON_IMPLEMENTATION,
            python_version=PLATFORM_PYTHON_VERSION,
            dependency_lock_hash=PAN_DEPENDENCY_LOCK_HASH,
            implementation_id=IMPLEMENTATION_ID,
            implementation_version=IMPLEMENTATION_VERSION,
            implementation_hash=PAN_IMPLEMENTATION_HASH,
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
    limitations, and a small local resource envelope.  No maturity
    value is assigned anywhere.
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
                "how_does_the_synthetic_compartment_state_move_after_one_declared_step",
                "how_does_the_declared_intervention_intensity_change_transmission",
            ),
            intended_users=(
                "kalhas_architecture_reviewer",
                "kalhas_conformance_engineer",
            ),
            horizon="exactly_one_declared_one_day_step",
            resolution="one_day",
            validity_envelope=(
                "small_synthetic_states_with_non_negative_integer_counts, "
                "exact_population_conservation, and occupancy_within_declared_capacity"
            ),
        ),
        units=(
            ModelPackUnitDeclaration(quantity_id="compartment_counts", unit="persons"),
            ModelPackUnitDeclaration(quantity_id="basis_point_rates", unit="basis-points"),
            ModelPackUnitDeclaration(quantity_id="capacities", unit="persons"),
            ModelPackUnitDeclaration(quantity_id="timestep", unit="day"),
            ModelPackUnitDeclaration(quantity_id="emission_quantities", unit="persons"),
            ModelPackUnitDeclaration(quantity_id="evidence_event_counts", unit="persons"),
        ),
        provenance=ModelPackProvenance(
            author_id="kalhas-phase29-h29-s04",
            method="deterministic_synthetic_construction",
            statement=(
                "Entirely synthetic reference construction for architecture "
                "and conformance exploration; contains no real patient, "
                "person, organization, or company data"
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
                use_id="synthetic_architecture_exploration",
                statement=(
                    "Exploring the versioned domain-pack mechanism seam with "
                    "a minimal deterministic synthetic compartment model"
                ),
                horizon="exactly_one_declared_one_day_step",
            ),
            ModelPackIntendedUse(
                use_id="synthetic_conformance_exploration",
                statement=(
                    "Exercising deterministic identity, validation, and "
                    "replay conformance of the pure mechanism seam"
                ),
                horizon="exactly_one_declared_one_day_step",
            ),
        ),
        prohibited_uses=prohibited_uses,
        assumptions=(
            ModelPackAssumption(
                assumption_id="fully_deterministic_no_stochastic_draw",
                statement=(
                    "PAN v0.1 uses no stochastic draw; every outcome is a "
                    "declared deterministic function of the validated inputs"
                ),
            ),
            ModelPackAssumption(
                assumption_id="integer_rational_arithmetic_only",
                statement=(
                    "All authoritative counts and rates stay in exact "
                    "integer/rational arithmetic with declared "
                    "round-to-nearest ties-to-even boundaries only"
                ),
            ),
            ModelPackAssumption(
                assumption_id="closed_population_one_day_steps",
                statement=(
                    "The population is closed and constant across the "
                    "declared one-day step; the deceased compartment is "
                    "absorbing"
                ),
            ),
        ),
        limitations=(
            ModelPackLimitation(
                limitation_id="no_empirical_adequacy_claim",
                statement=(
                    "The pack makes no claim of empirical adequacy for any "
                    "real population, disease, or place"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_calibration_or_benchmark_evidence",
                statement="No calibration or benchmark evidence exists for this release",
            ),
            ModelPackLimitation(
                limitation_id="no_real_world_forecasting_claim",
                statement="The pack makes no real-world forecasting claim of any kind",
            ),
            ModelPackLimitation(
                limitation_id="no_individual_level_modeling",
                statement=(
                    "The mechanism models aggregate compartment counts only; "
                    "no individual-level modeling exists"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_operational_or_clinical_decision_use",
                statement=(
                    "The pack must never inform operational or clinical "
                    "decisions; accountable human authority is required for "
                    "any decision support use"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_cross_platform_equivalence_claim",
                statement=(
                    "Exact replay is claimed only under the recorded "
                    "Windows/x86-64/CPython-3.12 development platform "
                    "identity; no Linux, macOS, or cross-platform "
                    "equivalence is claimed"
                ),
            ),
            ModelPackLimitation(
                limitation_id="no_autonomous_or_live_action",
                statement=(
                    "The pack performs no autonomous or live action and can "
                    "never cause real-world effects"
                ),
            ),
            ModelPackLimitation(
                limitation_id="one_synthetic_scenario_shape_only",
                statement=(
                    "Only the single declared synthetic compartment-flow scenario shape is covered"
                ),
            ),
            ModelPackLimitation(
                limitation_id="deterministic_compartment_abstraction_only",
                statement=(
                    "The model is a deterministic compartment abstraction "
                    "only; it is not an individual-level, stochastic, or "
                    "spatial model"
                ),
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


def _pack_authorities_fail_closed(pack: PanV01DomainPack) -> None:
    """Fail closed when any pack authority was replaced or mutated.

    Purely in-memory verification executed before every direct step.
    The three authorities must be exactly the shipped v1 contract types
    and the pack-level mechanism protocol attribute must equal the
    frozen protocol constant of this module.  The manifest content hash
    and the mechanism-spec and release-profile self-covering hashes must
    recompute exactly, the release profile must embed the pack's
    manifest and mechanism specification, and every authority must equal
    the pristine authority rebuilt in memory by the same deterministic
    private builders that constructed the frozen ``kalhas-pan`` v0.1
    release.  The pristine-equality anchors are the decisive checks:
    they compare the complete authority content, so a coordinated
    attacker who replaces any release-critical field (configuration,
    implementation, dependency-lock, solver, platform identity, event
    order, timestep, numeric semantics, quantization, scope, provenance,
    resources, intended or prohibited uses, assumptions, limitations,
    datasets, metadata, or timestamps), correctly recomputes the
    configuration, schema, and self-covering hashes, and rebuilds the
    request against the forged chain still fails closed - the forged
    chain is internally self-consistent but is not this exact frozen
    release.  The recomputed-hash checks above are retained so the
    underlying verification failure is always attributable to the
    tampered authority itself.  No filesystem, environment, platform,
    clock, or randomness access exists anywhere in this check, and no
    mutable global authority exists: the expected authorities are
    constructed fresh inside every call.
    """
    manifest = pack.manifest
    spec = pack.mechanism_spec
    profile = pack.release_profile
    if type(manifest) is not DomainPackManifest:
        raise PanDomainPackError("pack manifest is not the exact shipped contract type")
    if type(spec) is not DomainMechanismSpec:
        raise PanDomainPackError("mechanism specification is not the exact shipped contract type")
    if type(profile) is not ModelPackReleaseProfile:
        raise PanDomainPackError("release profile is not the exact shipped contract type")
    if pack.mechanism_protocol_version != MECHANISM_PROTOCOL_VERSION:
        raise PanDomainPackError("pack mechanism protocol version is not the frozen release value")
    if manifest_content_hash(manifest) != manifest.content_hash:
        raise PanDomainPackError("pack manifest content hash does not recompute")
    if _self_covering_hash(spec) != spec.content_hash:
        raise PanDomainPackError("mechanism specification self hash does not recompute")
    if _self_covering_hash(profile) != profile.content_hash:
        raise PanDomainPackError("release profile self hash does not recompute")
    if profile.manifest != manifest:
        raise PanDomainPackError("release profile does not embed the pack manifest")
    if profile.mechanism_spec != spec:
        raise PanDomainPackError("release profile does not embed the mechanism specification")
    if manifest != _build_manifest():
        raise PanDomainPackError("pack manifest is not the exact frozen v0.1 release manifest")
    expected_spec = _build_spec(_build_manifest())
    if spec != expected_spec:
        raise PanDomainPackError(
            "mechanism specification is not the exact frozen v0.1 release specification"
        )
    if profile != _build_release_profile(_build_manifest(), expected_spec):
        raise PanDomainPackError("release profile is not the exact frozen v0.1 release profile")


class PanV01DomainPack:
    """The concrete minimal synthetic KALHAS-PAN v0.1 DomainPack.

    Structurally satisfies the generic ``DomainPack`` protocol: the
    frozen ``DomainPackManifest``, the exact
    ``ModelPackReleaseProfile`` release identity, the frozen mechanism
    protocol version ``1.0.0``, and exactly one public executable
    operation, the pure :meth:`step` transition.  No second executable
    method, scheduler, lifecycle, callback, loader, resolver, registry,
    or plugin surface exists.  Construction is deterministic and free
    of I/O, clock, environment, platform, filesystem, and randomness.
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
        """The single pure PAN v0.1 mechanism transition.

        Fails closed if any pack authority has been replaced or
        mutated, then validates the request against the frozen
        authorities and returns the complete verified
        ``DomainMechanismStepResult``; every invalid input raises
        :class:`PanDomainPackError` and nothing is repaired, coerced,
        or normalized.  Fully deterministic: identical inputs always
        produce byte-identical results.  The request and all nested
        containers are never mutated, and the result shares no
        container with them.
        """
        _pack_authorities_fail_closed(self)
        return run_pan_step(request, self.mechanism_spec, self.release_profile)
