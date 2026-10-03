"""Declarative Model Pack contracts (Phase 29, H29-S02B).

ADR-005 (D29-03) freezes the Model Pack product vocabulary over the single
existing ``DomainPack`` identity. This module adds exactly three top-level
public v1 contracts plus their synchronized JSON Schemas:

- ``ModelPackReleaseProfile`` - the immutable declarative identity of one
  exact versioned DomainPack release. It embeds the accepted
  ``DomainPackManifest`` and ``DomainMechanismSpec`` directly so there is
  exactly one source of truth for the pack, mechanism, configuration,
  implementation, dependency-lock, solver, numeric-profile, precision,
  rounding, quantization, platform, time-basis, and API-compatibility
  identities, and adds the release-level scope, units, provenance, dataset
  identities with vintages, content hashes and licenses, resource envelope,
  intended uses, prohibited uses, assumptions, and limitations. Cross-field
  validation makes tenant, pack, version, manifest, mechanism,
  configuration, and content-hash identity disagreement fail closed. The
  mandatory public-sector floor is declarative and closed: decision support
  only, conditional modeled outcomes, accountable human authority required,
  and the complete prohibited-use set that can be neither omitted, weakened,
  nor reordered.
- ``ModelPackAssuranceProfile`` - binds exactly one release-profile
  identifier and content hash to immutable evidence references, retained
  failures, explicitly bounded supported claims, review state, and
  evidence-derived maturity. Maturity uses exactly the closed D29-03
  vocabulary; every level above ``catalogued`` cumulatively requires the
  evidence categories and closed-review coverage that ADR-005 freezes, so
  maturity can never be a disconnected self-assigned label. Retained
  failures remain visible and can never be overwritten or cleared by
  positive evidence.
- ``ModelPackCatalogueEntry`` - versioned declarative catalogue metadata
  over the same pack and profile identities. It may describe and reference
  a release/assurance profile by identity only; it cannot resolve, load,
  import, instantiate, execute, or call code, it cannot establish
  implemented capability, and it is never a second source of truth for
  execution or evidence. Any displayed maturity above ``catalogued`` must
  be bound to an exact assurance profile identifier and content hash; an
  unbound roadmap entry remains ``catalogued``.

The nested helper records (scope, units, provenance, dataset identities,
resource envelope, intended/prohibited uses, assumptions, limitations,
evidence records, retained failures, supported claims) are frozen, strict,
and extra-forbid; they are NOT registered in ``PUBLIC_CONTRACTS`` and
receive no standalone schema files.

These contracts are **declarative data only**. No executable identity,
import path, callable, provider, URL loader, command, network endpoint,
dynamic resolver, registry lookup, dispatcher, runtime integration, or
concrete pack is expressible or implemented here. No evidence is created
and no maturity is claimed for any real pack; the Phase 29 PAN/non-health
fixtures are the work of later slices. Nothing in this module computes an
authoritative hash; every content hash is a caller-declared identity field
as in the accepted mechanism contracts.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    MechanismProtocolVersion,
    MechanismSemVer,
    _reject_non_json_tree,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import IdentifierString, Sha256Hex

#: The exact closed maturity vocabulary of D29-03. No alias and no
#: additional value is expressible: in particular government-ready,
#: certified, universally-validated, autonomous, or any broader universal
#: production-approval status cannot be spelled.
MaturityValue = Literal[
    "catalogued",
    "conformance_only",
    "experimental",
    "benchmarked",
    "externally_reviewed",
    "partner_evaluation_ready",
]

#: Closed declarative floor values. Each is a single-value literal, so the
#: floor cannot be weakened, relabeled, or omitted.
DecisionScopeValue = Literal["decision_support_only"]
AccountabilityValue = Literal["accountable_human_authority_required"]
OutputLabelingValue = Literal["conditional_modeled_outcomes"]

#: The complete closed prohibited-use floor. The tuple of prohibited uses
#: must equal exactly this canonical ordered sequence: omission, subset,
#: reordering, duplication, and unknown values all fail closed.
ProhibitedUseValue = Literal[
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
]

#: The canonical, complete mandatory prohibited-use floor (strategic §11,
#: preserved by D29-03).
_PUBLIC_SECTOR_FLOOR: tuple[ProhibitedUseValue, ...] = (
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

#: The exact closed evidence-kind vocabulary of D29-03. Synthetic
#: conformance evidence and deterministic execution evidence ground the
#: lower levels; benchmark evidence carries the exact version, data
#: vintage, geography, and horizon binding; closed external review
#: grounds externally reviewed claims; packaging, replay, security, and
#: governance evidence ground partner evaluation readiness.
EvidenceKind = Literal[
    "synthetic_conformance",
    "deterministic_execution",
    "benchmark",
    "external_review",
    "packaging",
    "replay",
    "security",
    "governance",
]

ReviewStateValue = Literal["open", "closed"]

#: Cumulative evidence categories required for each maturity level. A
#: level requires every category of itself and of all lower levels; the
#: closed-external-review and claim-coverage rules are enforced
#: separately because they are about review state, not mere presence.
_CUMULATIVE_EVIDENCE_REQUIREMENTS: dict[str, frozenset[str]] = {
    "catalogued": frozenset(),
    "conformance_only": frozenset({"synthetic_conformance"}),
    "experimental": frozenset({"synthetic_conformance", "deterministic_execution"}),
    "benchmarked": frozenset({"synthetic_conformance", "deterministic_execution", "benchmark"}),
    "externally_reviewed": frozenset(
        {
            "synthetic_conformance",
            "deterministic_execution",
            "benchmark",
            "external_review",
        }
    ),
    "partner_evaluation_ready": frozenset(
        {
            "synthetic_conformance",
            "deterministic_execution",
            "benchmark",
            "external_review",
            "packaging",
            "replay",
            "security",
            "governance",
        }
    ),
}

_MATURITY_LEVELS_REQUIRING_CLOSED_REVIEW = ("externally_reviewed", "partner_evaluation_ready")


def _require_exact_positive_number(value: object) -> int | float:
    """Fail closed unless the raw value is an exact built-in positive number.

    Runs before Pydantic coercion, so booleans, strings, ``Decimal`` and
    Decimal-like values, ``int`` subclasses, ``float`` subclasses, NaN,
    infinities, zero, negatives, and arbitrary numeric objects are all
    rejected instead of being coerced into a neighboring numeric type.
    Only an exact built-in ``int`` or an exact finite built-in ``float``
    strictly greater than zero passes through unchanged.
    """
    if type(value) is int:
        number: int | float = value
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("value must be a finite number")
        number = value
    else:
        raise ValueError("value must be an exact built-in int or float")
    if number <= 0:
        raise ValueError("value must be greater than zero")
    return number


#: An exact positive resource-envelope ceiling: only a built-in ``int`` or
#: a finite built-in ``float``, strictly greater than zero, validated on
#: the raw input before any coercion. ``bool``, strings, ``Decimal``,
#: numeric subclasses, NaN, infinities, and non-positive values all fail
#: closed.
ExactPositiveNumeric = Annotated[
    int | float,
    BeforeValidator(_require_exact_positive_number),
    Field(gt=0),
]


class ModelPackScope(BaseModel):
    """Declared decision scope of one release (declarative only).

    Names the supported decision questions, intended users, horizon,
    resolution, and validity envelope as opaque declared identifiers.
    Nothing here interprets, evaluates, or scopes anything at runtime.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_questions: tuple[IdentifierString, ...] = Field(min_length=1)
    intended_users: tuple[IdentifierString, ...] = Field(min_length=1)
    horizon: IdentifierString
    resolution: IdentifierString
    validity_envelope: IdentifierString

    @model_validator(mode="after")
    def _entries_are_unique(self) -> ModelPackScope:
        for name, values in (
            ("decision_questions", self.decision_questions),
            ("intended_users", self.intended_users),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} entries must be unique")
        return self


class ModelPackUnitDeclaration(BaseModel):
    """One declared unit of one quantity (declarative only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity_id: IdentifierString
    unit: str


class ModelPackProvenance(BaseModel):
    """Declared provenance of one release (declarative only).

    Carries the declared author identity, the declared construction
    method, and a non-empty statement. No execution, tool, network, or
    code identity is expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    author_id: IdentifierString
    method: IdentifierString
    statement: IdentifierString


class ModelPackDatasetIdentity(BaseModel):
    """One dataset identity bound into a release (declarative only).

    Binds the stable dataset identifier, its vintage, its content hash,
    and its declared license identity and statement. Nothing here loads,
    fetches, or verifies a dataset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: IdentifierString
    vintage: IdentifierString
    content_hash: Sha256Hex
    license_id: IdentifierString
    license_statement: IdentifierString


class ModelPackResourceEnvelope(BaseModel):
    """Declared resource envelope of one release (declarative only).

    Positive exact numeric ceilings with explicit declared units. No
    enforcement, measurement, or scheduler exists here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_memory_megabytes: ExactPositiveNumeric
    max_cpu_seconds: ExactPositiveNumeric
    memory_unit: IdentifierString
    cpu_unit: IdentifierString


class ModelPackIntendedUse(BaseModel):
    """One declared intended use (declarative only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    use_id: IdentifierString
    statement: IdentifierString
    horizon: IdentifierString | None = None


class ModelPackAssumption(BaseModel):
    """One declared assumption (declarative only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assumption_id: IdentifierString
    statement: IdentifierString


class ModelPackLimitation(BaseModel):
    """One declared limitation (declarative only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    limitation_id: IdentifierString
    statement: IdentifierString


class ModelPackEvidenceRecord(BaseModel):
    """One immutable evidence reference (declarative identity only).

    ``reference`` is an opaque declared identifier of the retained
    evidence artifact together with its content hash; nothing here opens,
    loads, fetches, or interprets evidence. Kind-specific binding fields
    are strictly partitioned: benchmark evidence must bind a data vintage,
    geography, horizon, and at least one supported claim; external review
    evidence must declare its review state and may cover supported
    claims; every other kind must carry none of these fields.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: IdentifierString
    kind: EvidenceKind
    reference: IdentifierString
    content_hash: Sha256Hex
    review_state: ReviewStateValue | None = None
    data_vintage: IdentifierString | None = None
    geography: IdentifierString | None = None
    horizon: IdentifierString | None = None
    bound_claim_ids: tuple[IdentifierString, ...] = Field(default_factory=tuple)
    covered_claim_ids: tuple[IdentifierString, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _kind_specific_bindings_are_exact(self) -> ModelPackEvidenceRecord:
        if len(set(self.bound_claim_ids)) != len(self.bound_claim_ids):
            raise ValueError("bound claim ids must be unique")
        if len(set(self.covered_claim_ids)) != len(self.covered_claim_ids):
            raise ValueError("covered claim ids must be unique")
        if self.kind == "benchmark":
            if self.data_vintage is None or self.geography is None or self.horizon is None:
                raise ValueError(
                    "benchmark evidence must bind an exact data vintage, geography, and horizon"
                )
            if not self.bound_claim_ids:
                raise ValueError("benchmark evidence must bind at least one supported claim")
            if self.review_state is not None or self.covered_claim_ids:
                raise ValueError("benchmark evidence must not carry review fields")
            return self
        if self.kind == "external_review":
            if self.review_state is None:
                raise ValueError("external review evidence must declare its review state")
            if (
                self.data_vintage is not None
                or self.geography is not None
                or self.horizon is not None
                or self.bound_claim_ids
            ):
                raise ValueError("external review evidence must not carry benchmark bindings")
            return self
        if (
            self.review_state is not None
            or self.data_vintage is not None
            or self.geography is not None
            or self.horizon is not None
            or self.bound_claim_ids
            or self.covered_claim_ids
        ):
            raise ValueError("evidence of this kind must not carry review or benchmark fields")
        return self


class ModelPackRetainedFailure(BaseModel):
    """One retained, visible failure of the assured release.

    Retained failures are immutable declared records; no positive
    evidence, maturity level, or claim can overwrite, resolve, or remove
    them, and no such field is expressible anywhere in this module.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_id: IdentifierString
    statement: IdentifierString
    observed_in: IdentifierString


class ModelPackSupportedClaim(BaseModel):
    """One explicitly bounded supported claim.

    A claim is bounded by the evidence it cites: it must cite at least
    one evidence record, every cited record must exist in the same
    assurance profile, and a claim never transfers beyond the bound
    release identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: IdentifierString
    statement: IdentifierString
    evidence_ids: tuple[IdentifierString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _cited_evidence_is_unique(self) -> ModelPackSupportedClaim:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("cited evidence ids must be unique")
        return self


class ModelPackReleaseProfile(VersionedContract):
    """Immutable declarative identity of one exact versioned pack release.

    Embeds the accepted ``DomainPackManifest`` and ``DomainMechanismSpec``
    directly so the pack, mechanism, configuration, implementation,
    dependency-lock, solver, numeric-profile, precision, rounding,
    quantization, platform, time-basis/timestep, and KALHAS API
    compatibility identities each have exactly one source of truth, and
    copies the pack/version/manifest/mechanism/configuration identity
    fields for fail-closed cross-checking. Adds the release-level scope,
    units, provenance, dataset identities with vintages, content hashes
    and licenses, resource envelope, intended uses, the mandatory
    prohibited-use floor, assumptions, and limitations.

    Every identity disagreement between the copied fields, the embedded
    manifest, the embedded mechanism spec, and the tenant fails closed.
    The public-sector floor is mandatory closed declarative data: decision
    support only, conditional modeled outcomes, accountable human
    authority required, and the complete prohibited-use set in canonical
    order. No executable identity, import path, callable, provider, URL
    loader, command, network endpoint, dynamic resolver, or registry
    lookup is expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: IdentifierString
    pack_version: MechanismSemVer
    manifest_id: IdentifierString
    manifest_content_hash: Sha256Hex
    manifest: DomainPackManifest
    mechanism_id: IdentifierString
    mechanism_version: MechanismSemVer
    mechanism_protocol_version: MechanismProtocolVersion
    configuration_identity: Sha256Hex
    mechanism_spec: DomainMechanismSpec
    decision_scope: DecisionScopeValue
    accountability: AccountabilityValue
    output_labeling: OutputLabelingValue
    scope: ModelPackScope
    units: tuple[ModelPackUnitDeclaration, ...] = Field(default_factory=tuple)
    provenance: ModelPackProvenance
    datasets: tuple[ModelPackDatasetIdentity, ...] = Field(default_factory=tuple)
    resource_envelope: ModelPackResourceEnvelope
    intended_uses: tuple[ModelPackIntendedUse, ...] = Field(min_length=1)
    prohibited_uses: tuple[ProhibitedUseValue, ...]
    assumptions: tuple[ModelPackAssumption, ...] = Field(default_factory=tuple)
    limitations: tuple[ModelPackLimitation, ...] = Field(default_factory=tuple)
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_metadata_is_exact_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> ModelPackReleaseProfile:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _public_sector_floor_is_mandatory_and_exact(self) -> ModelPackReleaseProfile:
        if self.prohibited_uses != _PUBLIC_SECTOR_FLOOR:
            raise ValueError(
                "prohibited_uses must be exactly the complete mandatory public-sector "
                "floor in canonical order; it can never be omitted, weakened, "
                "reordered, or extended"
            )
        return self

    @model_validator(mode="after")
    def _embedded_identities_agree_exactly(self) -> ModelPackReleaseProfile:
        if self.manifest.tenant_id != self.tenant_id:
            raise ValueError("manifest tenant_id must agree with the release profile tenant_id")
        if self.mechanism_spec.tenant_id != self.tenant_id:
            raise ValueError(
                "mechanism spec tenant_id must agree with the release profile tenant_id"
            )
        for copied, embedded, name in (
            (self.pack_id, self.manifest.pack_id, "pack_id"),
            (self.pack_version, self.manifest.pack_version, "pack_version"),
            (self.manifest_id, self.manifest.identifier, "manifest identifier"),
            (self.manifest_content_hash, self.manifest.content_hash, "manifest content_hash"),
        ):
            if copied != embedded:
                raise ValueError(f"manifest disagrees with the release profile {name}")
        for copied, embedded, name in (
            (self.pack_id, self.mechanism_spec.pack_id, "pack_id"),
            (self.pack_version, self.mechanism_spec.pack_version, "pack_version"),
            (self.manifest_id, self.mechanism_spec.manifest_id, "manifest_id"),
            (
                self.manifest_content_hash,
                self.mechanism_spec.manifest_content_hash,
                "manifest_content_hash",
            ),
            (self.mechanism_id, self.mechanism_spec.mechanism_id, "mechanism_id"),
            (self.mechanism_version, self.mechanism_spec.mechanism_version, "mechanism_version"),
            (
                self.mechanism_protocol_version,
                self.mechanism_spec.mechanism_protocol_version,
                "mechanism_protocol_version",
            ),
            (
                self.configuration_identity,
                self.mechanism_spec.configuration_hash,
                "configuration identity",
            ),
        ):
            if copied != embedded:
                raise ValueError(f"mechanism spec disagrees with the release profile {name}")
        return self

    @model_validator(mode="after")
    def _collections_are_unique(self) -> ModelPackReleaseProfile:
        for name, values in (
            ("unit quantity", [unit.quantity_id for unit in self.units]),
            ("dataset", [dataset.dataset_id for dataset in self.datasets]),
            ("intended use", [use.use_id for use in self.intended_uses]),
            (
                "assumption",
                [assumption.assumption_id for assumption in self.assumptions],
            ),
            (
                "limitation",
                [limitation.limitation_id for limitation in self.limitations],
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} ids must be unique")
        return self


class ModelPackAssuranceProfile(VersionedContract):
    """Evidence-derived assurance bound to one exact release identity.

    Binds the release-profile identifier and content hash to immutable
    evidence references, retained failures, explicitly bounded supported
    claims, review state, and evidence-derived maturity. Maturity uses
    exactly the closed D29-03 vocabulary and is never a disconnected
    self-assigned label: every level above ``catalogued`` cumulatively
    requires its evidence categories; ``benchmarked`` requires benchmark
    evidence bound to an exact data vintage, geography, horizon, and
    supported claims; ``externally_reviewed`` and
    ``partner_evaluation_ready`` additionally require a closed external
    review whose coverage includes every supported claim;
    ``partner_evaluation_ready`` additionally requires packaging, replay,
    security, and governance evidence and still does not mean production
    approval. Retained failures remain visible and can never be
    overwritten or cleared by positive evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    release_profile_id: IdentifierString
    release_profile_content_hash: Sha256Hex
    maturity: MaturityValue
    evidence: tuple[ModelPackEvidenceRecord, ...] = Field(default_factory=tuple)
    retained_failures: tuple[ModelPackRetainedFailure, ...] = Field(default_factory=tuple)
    supported_claims: tuple[ModelPackSupportedClaim, ...] = Field(default_factory=tuple)
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_metadata_is_exact_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> ModelPackAssuranceProfile:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _collections_are_unique(self) -> ModelPackAssuranceProfile:
        for name, values in (
            ("evidence", [record.evidence_id for record in self.evidence]),
            (
                "retained failure",
                [failure.failure_id for failure in self.retained_failures],
            ),
            ("supported claim", [claim.claim_id for claim in self.supported_claims]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} ids must be unique")
        return self

    @model_validator(mode="after")
    def _claims_and_bindings_are_internal(self) -> ModelPackAssuranceProfile:
        evidence_ids = {record.evidence_id for record in self.evidence}
        claim_ids = {claim.claim_id for claim in self.supported_claims}
        for claim in self.supported_claims:
            unknown = set(claim.evidence_ids) - evidence_ids
            if unknown:
                raise ValueError(
                    f"supported claim {claim.claim_id} cites evidence absent from "
                    f"this profile: {sorted(unknown)}"
                )
        for record in self.evidence:
            unbound = set(record.bound_claim_ids) - claim_ids
            if unbound:
                raise ValueError(
                    f"evidence {record.evidence_id} binds claims absent from "
                    f"this profile: {sorted(unbound)}"
                )
            uncovered = set(record.covered_claim_ids) - claim_ids
            if uncovered:
                raise ValueError(
                    f"evidence {record.evidence_id} covers claims absent from "
                    f"this profile: {sorted(uncovered)}"
                )
        return self

    @model_validator(mode="after")
    def _maturity_is_evidence_derived(self) -> ModelPackAssuranceProfile:
        required = _CUMULATIVE_EVIDENCE_REQUIREMENTS[self.maturity]
        present = {record.kind for record in self.evidence}
        missing = sorted(required - present)
        if missing:
            raise ValueError(
                f"maturity {self.maturity!r} requires evidence kinds {missing}; "
                "maturity is evidence-derived and can never be self-assigned"
            )
        if self.maturity in _MATURITY_LEVELS_REQUIRING_CLOSED_REVIEW:
            closed = [
                record
                for record in self.evidence
                if record.kind == "external_review" and record.review_state == "closed"
            ]
            if not closed:
                raise ValueError(f"maturity {self.maturity!r} requires a closed external review")
            covered = {claim_id for record in closed for claim_id in record.covered_claim_ids}
            uncovered = [
                claim.claim_id for claim in self.supported_claims if claim.claim_id not in covered
            ]
            if uncovered:
                raise ValueError(
                    "the closed external review must cover every supported claim; "
                    f"uncovered claims: {uncovered}"
                )
        return self


class ModelPackCatalogueEntry(VersionedContract):
    """Versioned declarative catalogue metadata (never a capability).

    Describes one pack release identity and may reference a release or
    assurance profile by exact identity only. It cannot resolve, load,
    import, instantiate, execute, or call code, cannot establish
    implemented capability, and is not a second source of truth for
    execution or evidence. Any displayed maturity above ``catalogued``
    must be bound to an exact assurance profile identifier and content
    hash; an unbound roadmap entry remains ``catalogued``. An
    assurance-profile reference is additionally accepted only when the
    entry also carries the exact release-profile identifier and content
    hash; release-only references remain valid. There is no
    step method, callable, provider, executable reference, dynamic
    discovery field, or runtime authority anywhere on this contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: IdentifierString
    pack_version: MechanismSemVer
    title: IdentifierString
    summary: IdentifierString
    release_profile_id: IdentifierString | None = None
    release_profile_content_hash: Sha256Hex | None = None
    assurance_profile_id: IdentifierString | None = None
    assurance_profile_content_hash: Sha256Hex | None = None
    displayed_maturity: MaturityValue = "catalogued"
    content_hash: Sha256Hex
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _raw_metadata_is_exact_json(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_non_json_tree("metadata", data)
        return data

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> ModelPackCatalogueEntry:
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self

    @model_validator(mode="after")
    def _profile_references_are_both_or_neither(self) -> ModelPackCatalogueEntry:
        if (self.release_profile_id is None) != (self.release_profile_content_hash is None):
            raise ValueError(
                "release_profile_id and release_profile_content_hash must both be "
                "present or both be absent"
            )
        if (self.assurance_profile_id is None) != (self.assurance_profile_content_hash is None):
            raise ValueError(
                "assurance_profile_id and assurance_profile_content_hash must both be "
                "present or both be absent"
            )
        return self

    @model_validator(mode="after")
    def _displayed_maturity_is_bound_or_roadmap_only(self) -> ModelPackCatalogueEntry:
        if self.displayed_maturity == "catalogued":
            return self
        if self.assurance_profile_id is None or self.assurance_profile_content_hash is None:
            raise ValueError(
                f"displayed maturity {self.displayed_maturity!r} above catalogued must be "
                "bound to an exact assurance profile identifier and content hash; an "
                "unbound roadmap entry remains catalogued"
            )
        return self

    @model_validator(mode="after")
    def _assurance_reference_requires_release_reference(self) -> ModelPackCatalogueEntry:
        """Fail closed when an assurance reference lacks the release reference.

        An assurance profile always binds one exact release profile, so a
        catalogue entry may reference an assurance profile only when it
        also carries the release-profile identifier and content hash;
        release-only metadata remains valid on its own. Any displayed
        maturity above ``catalogued`` already requires the assurance pair
        and therefore, through this gate, the release pair as well.
        """
        if self.assurance_profile_id is not None and self.release_profile_id is None:
            raise ValueError(
                "an assurance-profile reference must not be accepted unless the catalogue "
                "entry also carries the exact release-profile identifier and content hash"
            )
        return self
