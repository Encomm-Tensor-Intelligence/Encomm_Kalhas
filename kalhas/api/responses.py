"""Typed API response envelopes for the Phase 2, 3, and 4 endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from kalhas.contracts.v1.activity import OperationalActivityEvent
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignStatus
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import RunStatus
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ClarificationQuestion, ValidationReport
from kalhas.contracts.v1.simulation import RunEvent
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion


class ScenarioValidationResponse(BaseModel):
    """Result of validating a scenario: report plus clarification questions."""

    model_config = ConfigDict(extra="forbid")

    report: ValidationReport
    questions: list[ClarificationQuestion]


class CompiledWorldResponse(BaseModel):
    """Result of compiling a scenario: immutable world plus manifest."""

    model_config = ConfigDict(extra="forbid")

    version: WorldVersion
    manifest: WorldManifest


class CampaignDetailResponse(BaseModel):
    """A campaign with its current lifecycle status."""

    model_config = ConfigDict(extra="forbid")

    campaign: CampaignSpec
    status: CampaignStatus


class RunPlanListResponse(BaseModel):
    """The ordered run plans of a campaign."""

    model_config = ConfigDict(extra="forbid")

    run_plans: list[RunPlan]


class CampaignExecutionResponse(BaseModel):
    """Result of executing a campaign: the run statuses after execution.

    Structural execution only - no outcomes, evidence, or recommendations.
    """

    model_config = ConfigDict(extra="forbid")

    run_statuses: list[RunStatus]


class RunEventListResponse(BaseModel):
    """The ordered event stream of one run."""

    model_config = ConfigDict(extra="forbid")

    events: list[RunEvent]


class DomainPackListResponse(BaseModel):
    """A tenant's registered domain pack manifests in deterministic order."""

    model_config = ConfigDict(extra="forbid")

    manifests: list[DomainPackManifest]


class DomainPackBindingListResponse(BaseModel):
    """A scenario's domain pack bindings in deterministic manifest-id order."""

    model_config = ConfigDict(extra="forbid")

    bindings: list[DomainPackBinding]


class DomainCapabilityDeclarationListResponse(BaseModel):
    """A scenario's capability declarations in deterministic order."""

    model_config = ConfigDict(extra="forbid")

    declarations: list[DomainCapabilityDeclaration]


class DomainStateModelListResponse(BaseModel):
    """A scenario's domain state models in deterministic order."""

    model_config = ConfigDict(extra="forbid")

    state_models: list[DomainStateModel]


class DomainStateTransitionListResponse(BaseModel):
    """A scenario's domain state transitions in deterministic order."""

    model_config = ConfigDict(extra="forbid")

    transitions: list[DomainStateTransition]


class DomainMetricObservationListResponse(BaseModel):
    """A scenario's domain metric observation bindings in deterministic metric-id order."""

    model_config = ConfigDict(extra="forbid")

    observations: list[DomainMetricObservationBinding]


class OperationalActivityListResponse(BaseModel):
    """One bounded page of a tenant's operational activity feed.

    ``events`` are in ascending sequence order (append order within the
    tenant), strictly after the requested ``after_sequence`` cursor.
    ``next_after_sequence`` is the sequence of the last returned event (or
    the requested cursor when the page is empty) and is suitable as the
    ``after_sequence`` of the next request. ``latest_sequence`` is the
    tenant's most recent sequence (-1 when the tenant has no activity).
    """

    model_config = ConfigDict(extra="forbid")

    events: list[OperationalActivityEvent]
    next_after_sequence: int
    latest_sequence: int
