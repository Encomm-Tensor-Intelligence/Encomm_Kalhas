"""Operational activity feed contracts: lightweight tenant-scoped observability.

The activity feed is **operational observability only** - a low-cost,
append-only, tenant-scoped record of structural lifecycle facts already
known to KALHAS, intended for a future Encomm Colony UI to read.

It is deliberately NOT a simulation event stream, NOT evidence, NOT hidden
reasoning, and NOT part of any ``WorldVersion``, ``RunPlan``, input-integrity
hash, event hash, or replay guarantee. Recording activity never changes any
simulation, replay, integrity, manifest, binding, or declaration artifact.

Every ``OperationalActivityEvent`` carries a tenant-local strictly
increasing ``sequence`` starting at zero (assigned at append time), a
generic structural ``kind``, a deterministic ``occurred_at`` derived from
the already-recorded source artifact (never the wall clock), optional
structural references, and a strict JSON-compatible ``payload`` containing
only safe structural facts: identifiers, contract/runtime/compiler
versions, event counts, lifecycle states, and hashes already safe to
expose to the owning tenant.

The payload NEVER contains raw capability input values, policy rules,
hidden reasoning, provider data, personal or company data, outcomes,
evidence, recommendations, or executable content. No streaming transport,
frontend, or polling loop exists in this phase: retrieval is bounded and
pull-based.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract


class OperationalActivityKind(StrEnum):
    """Generic structural lifecycle facts recorded by the activity feed."""

    SCENARIO_REGISTERED = "scenario_registered"
    WORLD_COMPILED = "world_compiled"
    DOMAIN_PACK_REGISTERED = "domain_pack_registered"
    DOMAIN_PACK_BOUND = "domain_pack_bound"
    CAPABILITY_INPUTS_DECLARED = "capability_inputs_declared"
    DOMAIN_STATE_MODEL_DECLARED = "domain_state_model_declared"
    DOMAIN_STATE_TRANSITION_DECLARED = "domain_state_transition_declared"
    CAMPAIGN_PREPARED = "campaign_prepared"
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_EXECUTED = "campaign_executed"
    RUN_INPUTS_VERIFIED = "run_inputs_verified"
    RUN_REPLAYED = "run_replayed"


class OperationalActivityEvent(VersionedContract):
    """One immutable, tenant-local structural lifecycle fact.

    The store assigns the tenant-local ``sequence`` (strictly increasing,
    starting at zero) and the deterministic identifier
    ``activity-{sequence}`` when the event is appended; events are
    immutable once appended and are retrieved in ascending sequence
    order. ``occurred_at`` is copied from the already-recorded source
    contract (scenario ``created_at``, world ``created_at``, binding
    ``bound_at``, declaration ``declared_at``, campaign status
    ``changed_at``, integrity manifest ``recorded_at``, replay manifest
    ``created_at``) - never the wall clock.

    The ``payload`` carries only safe structural facts for the owning
    tenant (identifiers, versions, counts, lifecycle states, and hashes
    already exposed by the source contracts). Raw capability input
    values, policy rules, hidden reasoning, provider data, outcomes,
    evidence, recommendations, and executable content are never
    representable here by convention and test.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=0)
    kind: OperationalActivityKind
    occurred_at: AwareDatetime
    scenario_id: str | None = None
    world_version_id: str | None = None
    campaign_id: str | None = None
    run_id: str | None = None
    manifest_id: str | None = None
    binding_id: str | None = None
    declaration_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
