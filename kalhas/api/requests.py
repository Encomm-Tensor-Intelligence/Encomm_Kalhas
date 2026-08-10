"""Strict typed request models for the Phase 3 campaign endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.domain_pack import ApiVersionNumber, DomainPackCapability
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime, JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, _contains_non_finite
from kalhas.contracts.v1.strategy import StrategyRequest


class PrepareCampaignRequest(BaseModel):
    """Request to prepare a campaign (planning only, never execution).

    The seed ensemble is the sole source of run multiplicity. The
    optional ``runtime_version`` selects the recorded runtime for the
    campaign's planned runs and defaults to the trajectory runtime
    ("2.0.0"); a caller may record the legacy structural runtime
    ("1.0.0") explicitly. Runtime selection for execution and replay
    always derives from the recorded RunPlan/RunStatus, never from this
    request.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    campaign_name: str
    scenario_id: str
    world_version_id: str
    strategy_request: StrategyRequest
    seed_ensemble: tuple[ScenarioSeed, ...] = Field(min_length=1)
    created_at: AwareDatetime
    runtime_version: str = TRAJECTORY_RUNTIME_VERSION


class StartCampaignRequest(BaseModel):
    """Request to start a campaign (COMPILED -> RUNNING only)."""

    model_config = ConfigDict(extra="forbid")

    changed_at: AwareDatetime


class BindDomainPackRequest(BaseModel):
    """Request to bind a registered domain pack manifest to a scenario.

    Accepts only ``manifest_id`` and ``bound_at``. Pack identity
    (``pack_id``, ``pack_version``), capability identifiers, tenant, and
    every hash originate exclusively from the stored immutable
    DomainPackManifest; any other field is rejected as unknown.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    bound_at: AwareDatetime


class DeclareCapabilityInputsRequest(BaseModel):
    """Request to declare immutable input values for one bound capability.

    Accepts only ``manifest_id``, ``capability_id``, ``input_values``,
    and ``declared_at``. It deliberately accepts no tenant, binding id,
    pack identity, manifest hash, declaration identifier, or declaration
    content hash: every identity field is copied from stored immutable
    records by the service, and the declaration content hash is always
    computed - a client-supplied hash is never accepted.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    capability_id: str
    input_values: dict[str, JsonValue] = Field(default_factory=dict)
    declared_at: AwareDatetime


class DeclareStateModelRequest(BaseModel):
    """Request to declare an immutable domain state model for a bound manifest.

    Accepts only ``manifest_id``, ``state_model_id``, ``state_fields``,
    ``declared_at``, and optional ``metadata``. It deliberately accepts no
    tenant, binding id, pack identity, manifest hash, model identifier, or
    model content hash: every identity field is copied from stored
    immutable records by the service, and the model content hash is always
    computed - a client-supplied hash is never accepted. State field
    definitions are validated strictly at this boundary (value-kind
    matching, unique identifiers, canonical allowed values), so invalid
    drafts fail with 422 before reaching the service.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    state_model_id: str = Field(min_length=1)
    state_fields: list[DomainStateFieldDefinition] = Field(default_factory=list)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_state_field_identifiers(self) -> DeclareStateModelRequest:
        identifiers = [field.identifier for field in self.state_fields]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("state field identifiers must be unique")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> DeclareStateModelRequest:
        """Metadata must hold only finite JSON-compatible values (typed 422)."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class DeclareStateTransitionRequest(BaseModel):
    """Request to declare an immutable domain state transition for a state model.

    Accepts only ``manifest_id``, ``state_model_id``, ``transition_id``,
    ``description``, ``guard_values``, ``target_values``, ``declared_at``,
    and optional ``metadata``. It deliberately accepts no tenant, binding
    id, pack identity, manifest hash, state-model content hash, transition
    identifier, or transition content hash: every identity field is copied
    from stored immutable records by the service, and the transition
    content hash is always computed - a client-supplied hash is never
    accepted. ``transition_id`` must be non-empty, ``target_values`` must
    be non-empty, and non-finite floats (NaN/Infinity) are rejected
    anywhere in the guard values, target values, or metadata, so invalid
    drafts fail with 422 before reaching the service.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    state_model_id: str
    transition_id: str = Field(min_length=1)
    description: str
    guard_values: dict[str, JsonValue] = Field(default_factory=dict)
    target_values: dict[str, JsonValue] = Field(default_factory=dict)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _target_values_non_empty(self) -> DeclareStateTransitionRequest:
        """A transition must declare at least one intended target field."""
        if not self.target_values:
            raise ValueError("target_values must be non-empty")
        return self

    @model_validator(mode="after")
    def _values_and_metadata_contain_no_non_finite(self) -> DeclareStateTransitionRequest:
        """Guard values, target values, and metadata must be finite JSON (typed 422)."""
        if _contains_non_finite(self.guard_values):
            raise ValueError("guard_values must contain only finite JSON-compatible values")
        if _contains_non_finite(self.target_values):
            raise ValueError("target_values must contain only finite JSON-compatible values")
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class DomainMetricObservationDeclarationRequest(BaseModel):
    """Request to declare an immutable domain metric observation binding.

    Accepts only ``manifest_id``, ``state_model_id``, ``metric_id``,
    ``state_field_id``, ``declared_at``, and optional ``metadata``. It
    deliberately accepts no tenant, scenario, binding id, pack identity,
    manifest hash, state-model deterministic identifier or content hash,
    state-field value kind, observation point, binding identifier, or
    binding content hash: every authoritative identity field is copied
    from stored immutable records by the service, and the binding
    content hash is always computed - a client-supplied hash is never
    accepted. Non-finite floats (NaN/Infinity) are rejected anywhere in
    the metadata, so invalid drafts fail with 422 before reaching the
    service.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    state_model_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    state_field_id: str = Field(min_length=1)
    declared_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> DomainMetricObservationDeclarationRequest:
        """Metadata must hold only finite JSON-compatible values (typed 422)."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self


class DomainPackRegistrationRequest(BaseModel):
    """Request to register a declarative domain pack manifest.

    Deliberately carries no ``tenant_id`` and no ``content_hash``: tenant
    ownership is derived from the ``X-Tenant-ID`` header, and the
    authoritative content hash is always computed by the registry - a
    client-supplied hash is never accepted. The draft mirrors the strict
    manifest constraints so invalid registrations fail with 422 at the
    request boundary.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: str
    pack_id: str
    name: str
    pack_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str | None = None
    # Same strict per-element validation as DomainPackManifest: every entry
    # must be a plain digit string (shared ApiVersionNumber type), non-empty
    # list, and API version "1" is mandatory (validator below).
    supported_api_versions: tuple[ApiVersionNumber, ...] = Field(min_length=1)
    capabilities: tuple[DomainPackCapability, ...] = Field(min_length=1)
    schema_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _requires_api_version_1(self) -> DomainPackRegistrationRequest:
        if "1" not in self.supported_api_versions:
            raise ValueError("supported_api_versions must include API version 1")
        return self

    @model_validator(mode="after")
    def _unique_capability_identifiers(self) -> DomainPackRegistrationRequest:
        capability_ids = [capability.identifier for capability in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability identifiers must be unique")
        return self
