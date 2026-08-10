"""Simulation contracts: run events, outcome vectors, evidence, decision briefs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from kalhas.contracts.v1.shared import (
    Assumption,
    AwareDatetime,
    DistributionSummary,
    JsonValue,
    RiskStatement,
    UncertaintyStatement,
    VersionedContract,
)


class RunEventKind(StrEnum):
    """Declared kinds of run events.

    The three structural kinds (``RUN_STARTED``, ``STRATEGY_DECLARATION_RECORDED``,
    ``RUN_COMPLETED``) form the deterministic structural event stream emitted
    by the structural runtime for every executed run.
    """

    STATE_CHANGE = "state_change"
    OBSERVATION = "observation"
    DECISION = "decision"
    MILESTONE = "milestone"
    ERROR = "error"
    NOTE = "note"
    RUN_STARTED = "run_started"
    STRATEGY_DECLARATION_RECORDED = "strategy_declaration_recorded"
    RUN_COMPLETED = "run_completed"


class EventMetadata(BaseModel):
    """Declared metadata attached to a run event."""

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    tags: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class RunEvent(VersionedContract):
    """One event of a run.

    ``sequence`` is the strictly increasing per-run ordering used for
    deterministic replay; ``simulation_time`` is the time inside the
    simulated world (derived deterministically from the recorded scenario
    horizon), while ``created_at`` is when the event was recorded (derived
    deterministically from recorded run inputs). Every event carries the
    run, campaign, world, strategy, and seed references. Structural events
    never contain domain outcome values, hidden reasoning, or executable
    policy content.
    """

    run_id: str
    campaign_id: str
    world_version_id: str
    strategy_candidate_id: str
    scenario_seed_id: str
    sequence: int = Field(ge=0)
    kind: RunEventKind = RunEventKind.NOTE
    simulation_time: AwareDatetime
    created_at: AwareDatetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: EventMetadata = Field(default_factory=EventMetadata)


class MetricOutcome(BaseModel):
    """Outcome of one metric: point estimate plus declared distribution."""

    model_config = ConfigDict(extra="forbid")

    metric_id: str
    unit: str | None = None
    point_estimate: float | None = None
    distribution: DistributionSummary | None = None
    observed_values: list[float] = Field(default_factory=list)


class OutcomeVector(VersionedContract):
    """Outcome of one run: distributions, risks, assumptions, and evidence."""

    run_id: str
    scenario_id: str
    strategy_candidate_id: str
    metrics: list[MetricOutcome] = Field(default_factory=list)
    risks: list[RiskStatement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    uncertainty: list[UncertaintyStatement] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    produced_at: AwareDatetime


class EvidenceReference(VersionedContract):
    """A pointer to recorded evidence (declared provenance, no data access)."""

    source_kind: str
    source_id: str
    recorded_at: AwareDatetime
    description: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DecisionBrief(VersionedContract):
    """Decision support artifact.

    Carries distributions, risks, assumptions, uncertainty, and evidence
    references - never a single unexplained score.
    """

    decision_id: str
    scenario_id: str
    strategy_candidate_id: str
    summary: str
    outcome: OutcomeVector
    risks: list[RiskStatement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    uncertainty: list[UncertaintyStatement] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    produced_at: AwareDatetime
