"""Pure opt-in Runtime-4 domain-mechanism step bridge (Phase 29, H29-S05).

Binds one already-produced Runtime-4 decision to exactly one
domain-mechanism request/result dispatch. The bridge is a pure,
additive, application-local function: it consumes explicit concrete
authorities (the pack, scenario, world, manifest, campaign, campaign
status, seed, realization, policy, decision event, run plan, run
status, and one caller-owned draft) and returns one frozen
application-local execution value carrying the verified dispatcher
result together with detached Runtime-4 binding evidence. It adds no
scheduler, executes no campaign loop, persists nothing, changes no
Runtime-4 record, and never re-evaluates policy rules: Runtime 4
remains the only scheduling and execution authority, and the bridge is
strictly opt-in for callers that already hold a Runtime-4 decision
event.

The bridge verifies structural decision evidence only; it cannot
independently reproduce observation truth or budget eligibility
without the complete state-machine inputs, and it never claims to.

Fail-closed verification, in order:

1. Exact top-level types: every supplied authority must be exactly the
   shipped contract type (no dict coercion, no subclass, no lookalike),
   and the draft must be the exact application-local draft type. The
   pack surface itself is verified exclusively by the existing
   dispatcher; this module never inspects pack identity here.
2. Draft validation: the step index must be an exact built-in
   non-negative ``int`` (booleans fail), the state payload an exact
   ``dict``, the action catalogue an exact ``dict`` whose outer keys are
   exact built-in ``str`` and whose payloads are exact ``dict``
   objects, the exogenous inputs an exact ``tuple``, and every
   state/action payload tree exact built-in finite JSON (tuples,
   mappings, subclasses, ``Decimal``-like values, NaN, and infinities
   fail). The catalogue keys must be exactly the policy's bound action
   identifiers, no more and no fewer, and no key may be a ``str``
   subclass or any other non-exact type.
3. Runtime literal: the policy, the decision event, the run plan, and
   the run status must all carry the exact existing Runtime-4 literal
   imported from :mod:`kalhas.application.adaptive_run_planner`.
   Historical runtimes 1-3 are never reinterpreted.
4. Detached strict revalidation: every supplied Pydantic authority is
   revalidated from its Python-mode serialization with ``strict=True``,
   so forged, validator-bypassed, or shallow-mutated records fail
   closed before any field is trusted.
5. Complete authority verification: the verified world snapshot; exact
   supplied-scenario byte equivalence with the scenario embedded in the
   verified world plus world tenant/source-scenario identity; campaign
   identity, tenant, scenario, world, and the supplied seed being the
   unique complete ``ScenarioSeed`` snapshot of the campaign's
   ``seed_ensemble`` (never merely a same-identifier member); campaign
   status identifier ``status-<campaign.identifier>``, tenant, campaign,
   and state exactly COMPILED; seed identity, tenant, and canonical
   seed hash; realization tenant/scenario/world/seed identity,
   recomputed realization identifier and content hash, and provenance
   against the uncertainty model embedded in the verified world;
   policy identity, tenant, campaign, scenario, world binding, and
   recomputed identifier/content hash through the existing verifier;
   every policy action's strategy candidate belonging to the campaign;
   decision-event policy id/hash and step binding, current and selected
   actions belonging to the policy, the evaluation evidence forming the
   exact stored-policy rule prefix in policy order with each record's
   ``enter``/``retain`` role agreeing with the rule's target action and
   the decision's current action, a uniquely resolved selected rule for
   ``decision_kind == "rule"`` whose target action equals the selected
   action, and the selected action equal to the policy fallback action
   for the ordinary ``fallback`` kind (``blocked_fallback`` keeps the
   contract's retain-current semantics); run-plan tenant/campaign/world/
   seed/runtime binding, deterministic Runtime-4 run-plan identifier,
   historical initial-action strategy anchor, recomputed adaptive run
   input hash, and the deterministic run identifier; run-status
   identifier, tenant, run, campaign, run-plan, and input-hash binding
   with state exactly RUNNING, timestamps agreeing with the run plan's
   ``created_at`` (both ``created_at`` and ``changed_at``), and no
   reinterpreted historical event hash; and every exogenous coordinate
   matching the verified world, seed, realization, run, and step in
   canonical order with a recomputed value hash. The caller's
   already-canonical ordered exogenous tuple is preserved exactly.
6. Pack tenant authority: the supplied pack's manifest, release
   profile, and embedded mechanism specification must all carry the
   verified Runtime-4 tenant derived from the world/authority chain. A
   pack whose tenant disagrees at any of the three surfaces fails
   closed here, before any request is constructed and before ``pack.step``
   could run. The existing dispatcher remains the final pack/request
   authority and re-enforces the exact request/profile/manifest tenant
   agreement; nothing of its verification is duplicated here.
7. Request construction: exactly one ``DomainMechanismStepRequest``
   built from verified authorities with canonically hashed detached
   state/action/configuration payloads, the selected payload resolved
   internally and solely through the decision event's selected action,
   a deterministic SHA-256 over the complete action-payload catalogue,
   the Runtime-4 tenant carried directly on the request, and a
   deterministic identifier derived from one explicit canonical identity
   payload covering the complete JSON-mode evidence (runtime literal
   and tenant, the complete campaign and campaign status, run identity,
   the complete run plan and run status, the complete policy and
   decision event, the pack manifest, release profile, and mechanism
   specification, the complete scenario, world, and world manifest, the
   complete seed and realization, the step, the detached state payload,
   the complete action catalogue with its hash and the selected payload,
   and the exogenous-input records). Identical accepted inputs always
   produce byte-identical request bytes, and any evidence change covered
   above changes the identifier or fails closed.
8. Exactly-once dispatch: :func:`dispatch_domain_mechanism_step` is
   called exactly once with the constructed request. No retry, no
   second call, and no direct pack invocation exists here. Preflight
   failures call neither the dispatcher nor the pack.

Every unexpected preflight, validation, or construction failure is
converted into exactly one :class:`DomainMechanismDispatchError` with
a stable bounded internal reason; an existing
:class:`DomainMechanismDispatchError` propagates unchanged. Public
messages never carry attacker-controlled values, hashes, or validator
text. A step returns one complete execution value or raises one typed
error: no partial result, no caller or pack mutation, and no
repository, store, filesystem, clock, environment, network, or
randomness access exists anywhere in this module. It adds no public
contract, schema, registry item, or API surface, is not re-exported
through ``kalhas.application.__init__``, and imports no concrete pack.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import NoReturn

from pydantic import BaseModel

from kalhas.application.adaptive_policy_identity import verify_adaptive_policy_identity
from kalhas.application.adaptive_run_planner import (
    ADAPTIVE_RUNTIME_VERSION,
    adaptive_run_input_hash,
)
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.objective_evaluation_identity import scenario_content_hash
from kalhas.application.realization_identity import verify_realization_provenance
from kalhas.application.run_planner import run_identifier, run_plan_identifier
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.adaptive_policy_state import AdaptivePolicyDecisionEvent
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismExogenousInput,
    _is_exact_json_value,
)
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed, ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization
from kalhas.domain_packs import DomainPack

__all__ = [
    "Runtime4DomainMechanismStepDraft",
    "Runtime4DomainMechanismStepExecution",
    "execute_runtime4_domain_mechanism_step",
]

#: Length, in hex characters, of the hash-derived request identifier tail.
_ID_HASH_LENGTH = 16

#: The readable, distinct request-identifier prefix of this bridge.
_REQUEST_ID_PREFIX = "domain-mechanism-step-"

#: The self-covering placeholder digest used before finalization.
_PLACEHOLDER_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class Runtime4DomainMechanismStepDraft:
    """The application-local caller-owned inputs of exactly one bound step.

    ``step_index`` is the strict non-negative integer decision step of the
    already-produced Runtime-4 decision (booleans fail). ``state_payload``
    is the complete verified mechanism state payload. ``action_payloads``
    is the complete catalogue keyed by every
    ``AdaptivePolicy.actions[*].action_id`` - the selected entry is
    resolved internally from the decision event, never by the caller.
    ``exogenous_inputs`` is the caller's already-canonical ordered tuple
    of coordinate-addressed entries, preserved exactly. No authoritative
    identity, hash, or configuration value is accepted here.
    """

    step_index: int
    state_payload: dict[str, JsonValue]
    action_payloads: dict[str, dict[str, JsonValue]]
    exogenous_inputs: tuple[MechanismExogenousInput, ...]


@dataclass(frozen=True, slots=True)
class Runtime4DomainMechanismStepExecution:
    """The frozen application-local outcome of exactly one bound step.

    Carries the Runtime-4 binding evidence (runtime version, run,
    adaptive-policy identifier and content hash, policy id, the detached
    decision event, and the internally resolved selected action), the
    deterministic complete action-payload catalogue hash, the exact
    constructed :class:`DomainMechanismStepRequest`, and the verified
    :class:`DomainMechanismStepResult` returned by the dispatcher. It is
    evidence only - never an aggregate, persistence receipt, run status,
    or API surface - and the request and result share no mutable
    container with any caller-owned input.
    """

    runtime_version: str
    run_id: str
    adaptive_policy_identifier: str
    policy_id: str
    adaptive_policy_content_hash: str
    decision_event: AdaptivePolicyDecisionEvent
    selected_action_id: str
    action_payload_catalogue_hash: str
    request: DomainMechanismStepRequest
    result: DomainMechanismStepResult


def _reject(reason: str) -> NoReturn:
    """Raise the single typed dispatch error with a bounded internal reason."""
    raise DomainMechanismDispatchError(reason)


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied authority from its detached serialization.

    The authority's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance is rejected before any field of it is trusted. The
    revalidation result is discarded; the artifact is never replaced,
    repaired, or mutated. Any failure raises ``ValueError`` for the
    caller to convert into the single typed error.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except Exception as exc:
        raise ValueError("authority failed detached strict revalidation") from exc


def _detach_json_value(value: JsonValue) -> JsonValue:
    """A detached recursive copy of one exact JSON value."""
    if type(value) is dict:
        return {key: _detach_json_value(item) for key, item in value.items()}
    if type(value) is list:
        return [_detach_json_value(item) for item in value]
    return value


def _detach_json_object(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """A detached recursive copy of one exact JSON object."""
    return {key: _detach_json_value(item) for key, item in value.items()}


def _verify_draft(draft: Runtime4DomainMechanismStepDraft, action_ids: frozenset[str]) -> None:
    """Validate the caller-owned draft structurally; raises the typed error.

    Enforces the exact draft shape: the strict non-negative integer step
    index (bool, float, string, and negative values fail), the exact
    built-in state payload dict, the exact built-in catalogue mapping
    whose every outer key is an exact built-in ``str`` (``str``
    subclasses fail) and whose payloads are exact built-in dicts holding
    exactly the policy's complete action-id set, the exact exogenous
    tuple, and exact built-in finite JSON in the state payload and in
    every catalogue entry. Nothing is sorted, repaired, coerced, or
    mutated.
    """
    if type(draft.step_index) is not int or draft.step_index < 0:
        _reject("draft_step_index")
    if type(draft.state_payload) is not dict:
        _reject("draft_state_payload_type")
    if type(draft.action_payloads) is not dict:
        _reject("draft_action_catalogue_type")
    if type(draft.exogenous_inputs) is not tuple:
        _reject("draft_exogenous_type")
    for action_id in draft.action_payloads:
        if type(action_id) is not str:
            _reject("draft_action_catalogue_key_type")
    if set(draft.action_payloads) != action_ids:
        _reject("draft_action_catalogue_coverage")
    if not _is_exact_json_value(draft.state_payload):
        _reject("draft_state_payload_json")
    for payload in draft.action_payloads.values():
        if type(payload) is not dict:
            _reject("draft_action_payload_type")
        if not _is_exact_json_value(payload):
            _reject("draft_action_payload_json")
    for entry in draft.exogenous_inputs:
        if type(entry) is not MechanismExogenousInput:
            _reject("draft_exogenous_entry_type")


def _verified_request(
    *,
    tenant_id: str,
    scenario: ScenarioSpec,
    scenario_hash: str,
    world: WorldVersion,
    world_manifest: WorldManifest,
    seed: ScenarioSeed,
    seed_hash: str,
    realization: WorldRealization,
    run_id: str,
    run_plan: RunPlan,
    run_status: RunStatus,
    campaign: CampaignSpec,
    campaign_status: CampaignStatus,
    policy: AdaptivePolicy,
    decision_event: AdaptivePolicyDecisionEvent,
    pack: DomainPack,
    draft: Runtime4DomainMechanismStepDraft,
) -> tuple[DomainMechanismStepRequest, str]:
    """Construct the single verified step request; raises the typed error.

    Returns the request together with the deterministic complete
    action-payload catalogue hash. The request identifier is derived from
    one explicit canonical identity payload covering the complete
    JSON-mode evidence of the bound step; the request tenant is exactly
    the verified Runtime-4 tenant.
    """
    try:
        pack_manifest = pack.manifest
        pack_profile = pack.release_profile
        pack_spec = pack_profile.mechanism_spec
    except Exception as exc:
        raise DomainMechanismDispatchError("pack_authority_access") from exc

    # Mechanism configuration is snapshotted exclusively from the supplied
    # concrete pack's release profile and its embedded mechanism
    # specification; the caller can never supply it.
    configuration_payload = _detach_json_object(pack_spec.configuration)
    configuration_hash = sha256_hex(canonical_json(configuration_payload))

    # The complete action catalogue, detached exactly once; the selected
    # payload is resolved internally and solely through the decision event.
    catalogue: dict[str, dict[str, JsonValue]] = {
        action_id: _detach_json_object(payload)
        for action_id, payload in draft.action_payloads.items()
    }
    catalogue_hash = sha256_hex(canonical_json(catalogue))
    selected_payload = catalogue[decision_event.selected_action_id]

    state_payload = _detach_json_object(draft.state_payload)
    exogenous_records = [entry.model_dump(mode="json") for entry in draft.exogenous_inputs]
    # One explicit canonical identity payload: complete JSON-mode dumps,
    # never selected fragments, so every evidence change covered above
    # changes the identifier or fails closed.
    identity_payload: dict[str, object] = {
        "runtime_version": ADAPTIVE_RUNTIME_VERSION,
        "runtime_tenant_id": tenant_id,
        "campaign": campaign.model_dump(mode="json"),
        "campaign_status": campaign_status.model_dump(mode="json"),
        "run_id": run_id,
        "run_plan": run_plan.model_dump(mode="json"),
        "run_status": run_status.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
        "decision_event": decision_event.model_dump(mode="json"),
        "pack_manifest": pack_manifest.model_dump(mode="json"),
        "release_profile": pack_profile.model_dump(mode="json"),
        "mechanism_spec": pack_spec.model_dump(mode="json"),
        "scenario": scenario.model_dump(mode="json"),
        "world": world.model_dump(mode="json"),
        "world_manifest": world_manifest.model_dump(mode="json"),
        "seed": seed.model_dump(mode="json"),
        "realization": realization.model_dump(mode="json"),
        "step_index": draft.step_index,
        "state_payload": state_payload,
        "action_payload_catalogue": catalogue,
        "action_payload_catalogue_hash": catalogue_hash,
        "selected_action_id": decision_event.selected_action_id,
        "selected_action_payload": selected_payload,
        "exogenous_inputs": exogenous_records,
    }
    request_identifier = (
        f"{_REQUEST_ID_PREFIX}{sha256_hex(canonical_json(identity_payload))[:_ID_HASH_LENGTH]}"
    )
    request = DomainMechanismStepRequest(
        # The request tenant is exactly the verified Runtime-4 tenant; the
        # pack's manifest/release-profile/spec tenants were already
        # required to agree with it above, and the existing dispatcher
        # re-enforces the exact request/profile/manifest agreement.
        identifier=request_identifier,
        tenant_id=tenant_id,
        mechanism_spec_id=pack_spec.identifier,
        mechanism_spec_content_hash=pack_spec.content_hash,
        release_profile_id=pack_profile.identifier,
        release_profile_content_hash=pack_profile.content_hash,
        realization_id=realization.identifier,
        realization_content_hash=realization.content_hash,
        scenario_id=scenario.identifier,
        scenario_content_hash=scenario_hash,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        seed_id=seed.identifier,
        seed_content_hash=seed_hash,
        run_id=run_id,
        step_index=draft.step_index,
        state_schema_id=pack_spec.state_schema_id,
        action_schema_id=pack_spec.action_schema_id,
        configuration_schema_id=pack_spec.configuration_schema_id,
        state_schema_hash=pack_spec.state_schema_hash,
        action_schema_hash=pack_spec.action_schema_hash,
        configuration_schema_hash=pack_spec.configuration_schema_hash,
        state_payload=state_payload,
        action_payload=selected_payload,
        configuration_payload=configuration_payload,
        state_hash=sha256_hex(canonical_json(state_payload)),
        action_hash=sha256_hex(canonical_json(selected_payload)),
        configuration_hash=configuration_hash,
        exogenous_inputs=draft.exogenous_inputs,
        content_hash=_PLACEHOLDER_HASH,
    )
    dumped = request.model_dump(mode="json")
    del dumped["content_hash"]
    payload = request.model_dump(mode="python")
    payload["content_hash"] = sha256_hex(canonical_json(dumped))
    return DomainMechanismStepRequest.model_validate(payload), catalogue_hash


def execute_runtime4_domain_mechanism_step(
    *,
    pack: DomainPack,
    scenario: ScenarioSpec,
    world_manifest: WorldManifest,
    campaign: CampaignSpec,
    campaign_status: CampaignStatus,
    world: WorldVersion,
    seed: ScenarioSeed,
    realization: WorldRealization,
    policy: AdaptivePolicy,
    decision_event: AdaptivePolicyDecisionEvent,
    run_plan: RunPlan,
    run_status: RunStatus,
    draft: Runtime4DomainMechanismStepDraft,
) -> Runtime4DomainMechanismStepExecution:
    """Bind one Runtime-4 decision to exactly one mechanism dispatch.

    Verifies the complete explicit authority chain fail-closed, constructs
    exactly one verified ``DomainMechanismStepRequest``, dispatches it
    through the existing seam exactly once, and returns the frozen
    execution value binding the verified result to the Runtime-4
    decision. Every failure raises exactly one
    :class:`DomainMechanismDispatchError` before or after the single
    dispatch with no partial result, no retry, no caller or pack
    mutation, and no repository or store effect.
    """
    try:
        # 1. Exact top-level types; subclasses, mappings, and lookalikes fail.
        if type(scenario) is not ScenarioSpec:
            _reject("scenario_type")
        if type(world_manifest) is not WorldManifest:
            _reject("world_manifest_type")
        if type(campaign) is not CampaignSpec:
            _reject("campaign_type")
        if type(campaign_status) is not CampaignStatus:
            _reject("campaign_status_type")
        if type(world) is not WorldVersion:
            _reject("world_type")
        if type(seed) is not ScenarioSeed:
            _reject("seed_type")
        if type(realization) is not WorldRealization:
            _reject("realization_type")
        if type(policy) is not AdaptivePolicy:
            _reject("policy_type")
        if type(decision_event) is not AdaptivePolicyDecisionEvent:
            _reject("decision_event_type")
        if type(run_plan) is not RunPlan:
            _reject("run_plan_type")
        if type(run_status) is not RunStatus:
            _reject("run_status_type")
        if type(draft) is not Runtime4DomainMechanismStepDraft:
            _reject("draft_type")

        # 2. Runtime literal: exactly Runtime 4.0.0, from the existing source.
        if policy.runtime_version != ADAPTIVE_RUNTIME_VERSION:
            _reject("policy_runtime_version")
        if decision_event.runtime_version != ADAPTIVE_RUNTIME_VERSION:
            _reject("decision_event_runtime_version")
        if run_plan.runtime_version != ADAPTIVE_RUNTIME_VERSION:
            _reject("run_plan_runtime_version")
        if run_status.runtime_version != ADAPTIVE_RUNTIME_VERSION:
            _reject("run_status_runtime_version")

        # 3. Draft validation against the complete policy action-id set.
        _verify_draft(draft, frozenset(action.action_id for action in policy.actions))

        # 4. Detached strict revalidation of every Pydantic authority.
        revalidations: tuple[tuple[BaseModel, type[BaseModel]], ...] = (
            (scenario, ScenarioSpec),
            (world_manifest, WorldManifest),
            (campaign, CampaignSpec),
            (campaign_status, CampaignStatus),
            (world, WorldVersion),
            (seed, ScenarioSeed),
            (realization, WorldRealization),
            (policy, AdaptivePolicy),
            (decision_event, AdaptivePolicyDecisionEvent),
            (run_plan, RunPlan),
            (run_status, RunStatus),
        )
        for artifact, model_type in revalidations:
            try:
                _strictly_revalidate_detached(artifact, model_type)
            except ValueError:
                _reject("authority_failed_detached_revalidation")
        for entry in draft.exogenous_inputs:
            try:
                _strictly_revalidate_detached(entry, MechanismExogenousInput)
            except ValueError:
                _reject("exogenous_entry_failed_detached_revalidation")

        # 5. Verified world snapshot; the Runtime-4 tenant anchor derives
        # from it.
        try:
            verify_world_snapshot(world, world_manifest)
        except Exception as exc:
            raise DomainMechanismDispatchError("world_snapshot_verification") from exc
        tenant_id = world.tenant_id

        # 6. Pack tenant authority: the manifest, the release profile, and
        # the embedded mechanism specification must all carry the verified
        # Runtime-4 tenant, before any request is built or any pack.step
        # could be reached.
        try:
            pack_manifest_tenant = pack.manifest.tenant_id
            pack_profile_tenant = pack.release_profile.tenant_id
            pack_spec_tenant = pack.release_profile.mechanism_spec.tenant_id
        except Exception as exc:
            raise DomainMechanismDispatchError("pack_authority_access") from exc
        if (
            pack_manifest_tenant != tenant_id
            or pack_profile_tenant != tenant_id
            or pack_spec_tenant != tenant_id
        ):
            _reject("pack_tenant_agreement")

        # 7. Scenario: ownership, canonical snapshot hash, byte equivalence
        # with the scenario embedded in the verified world.
        scenario_hash = scenario_content_hash(scenario)
        if scenario.tenant_id != tenant_id:
            _reject("scenario_tenant")
        if scenario.identifier != world.source_scenario_id:
            _reject("scenario_world_source_identity")
        raw_embedded = world.world.get("scenario")
        if type(raw_embedded) is not dict:
            _reject("embedded_scenario_shape")
        try:
            embedded_scenario = ScenarioSpec.model_validate(raw_embedded)
        except Exception as exc:
            raise DomainMechanismDispatchError("embedded_scenario_shape") from exc
        if scenario.model_dump(mode="json") != embedded_scenario.model_dump(mode="json"):
            _reject("scenario_byte_equivalence")

        # 8. Campaign: identity, tenant, scenario, world, and the supplied
        # seed being the unique complete campaign seed snapshot.
        if campaign.tenant_id != tenant_id:
            _reject("campaign_tenant")
        if campaign.scenario_id != scenario.identifier:
            _reject("campaign_scenario")
        if campaign.world_version_id != world.identifier:
            _reject("campaign_world")
        ensemble_members = [
            member for member in campaign.seed_ensemble if member.identifier == seed.identifier
        ]
        if len(ensemble_members) != 1:
            _reject("campaign_seed_membership")
        if seed.model_dump(mode="json") != ensemble_members[0].model_dump(mode="json"):
            _reject("campaign_seed_snapshot")

        # 9. Campaign status: identifier, tenant, campaign, exactly COMPILED.
        if campaign_status.identifier != f"status-{campaign.identifier}":
            _reject("campaign_status_identifier")
        if campaign_status.tenant_id != tenant_id:
            _reject("campaign_status_tenant")
        if campaign_status.campaign_id != campaign.identifier:
            _reject("campaign_status_identity")
        if campaign_status.state is not CampaignState.COMPILED:
            _reject("campaign_status_state")

        # 10. Seed: exact identity, tenant, canonical seed hash.
        if seed.tenant_id != tenant_id:
            _reject("seed_tenant")
        seed_hash = seed_content_hash(seed)

        # 11. Realization: identity, recomputed identifier and content hash,
        # and provenance against the verified world's embedded model.
        if (
            realization.tenant_id != tenant_id
            or realization.scenario_id != scenario.identifier
            or realization.world_version_id != world.identifier
            or realization.world_content_hash != world.content_hash
            or realization.scenario_seed_id != seed.identifier
            or realization.seed_content_hash != seed_hash
        ):
            _reject("realization_identity")
        expected_realization_id = world_realization_identifier(
            world_version_id=realization.world_version_id,
            world_content_hash=realization.world_content_hash,
            scenario_seed_id=realization.scenario_seed_id,
            seed_content_hash_value=realization.seed_content_hash,
            uncertainty_model_id=realization.uncertainty_model_id,
            uncertainty_model_content_hash_value=realization.uncertainty_model_content_hash,
            sampler_version=realization.sampler_version,
            quantization_policy=realization.quantization_policy,
            quantization_fraction_bits=realization.quantization_fraction_bits,
        )
        if realization.identifier != expected_realization_id:
            _reject("realization_identifier")
        if realization.content_hash != world_realization_content_hash(realization):
            _reject("realization_content_hash")
        run_id = run_identifier(run_plan)
        try:
            verify_realization_provenance(
                run_id=run_id,
                world=world,
                seed=seed,
                realization=realization,
                uncertainty_model=extract_world_catalog(world).uncertainty_model,
            )
        except Exception as exc:
            raise DomainMechanismDispatchError("realization_provenance") from exc

        # 12. Policy: Runtime-4 identity, tenant, campaign, scenario, world
        # binding, recomputed identifier and content hash.
        try:
            verify_adaptive_policy_identity(
                policy,
                tenant_id=tenant_id,
                campaign_id=campaign.identifier,
                scenario_id=scenario.identifier,
                world_version_id=world.identifier,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
            )
        except Exception as exc:
            raise DomainMechanismDispatchError("policy_identity") from exc

        # 13. Every policy action's strategy candidate belongs to the campaign.
        campaign_candidate_ids = set(campaign.strategy_candidate_ids)
        for action in policy.actions:
            if action.strategy_candidate_id not in campaign_candidate_ids:
                _reject("policy_strategy_membership")

        # 14. Decision event: policy id/hash, step binding, action
        # membership, the evaluation evidence forming the exact stored rule
        # prefix in policy order with correct enter/retain roles, a uniquely
        # resolved selected rule agreeing with the selected action (rule
        # kind), and the selected action equal to the policy fallback action
        # (ordinary fallback kind; blocked_fallback keeps the contract's
        # retain-current semantics).
        if (
            decision_event.policy_id != policy.policy_id
            or decision_event.policy_content_hash != policy.content_hash
        ):
            _reject("decision_event_policy_identity")
        if decision_event.decision_step != draft.step_index:
            _reject("decision_event_step_binding")
        action_ids = {action.action_id for action in policy.actions}
        if (
            decision_event.current_action_id not in action_ids
            or decision_event.selected_action_id not in action_ids
        ):
            _reject("decision_event_action_membership")
        rules = policy.rules
        evidence = decision_event.rule_evaluation_evidence
        if len(evidence) > len(rules):
            _reject("decision_event_evidence_order")
        for position, record in enumerate(evidence):
            if record[0] != rules[position].rule_id:
                _reject("decision_event_evidence_order")
            expected_role = (
                "retain"
                if rules[position].target_action_id == decision_event.current_action_id
                else "enter"
            )
            if record[1] != expected_role:
                _reject("decision_event_evidence_role")
        if decision_event.decision_kind == "rule":
            if decision_event.selected_rule_id is None:
                _reject("decision_event_selected_rule")
            selected_rules = [
                rule for rule in rules if rule.rule_id == decision_event.selected_rule_id
            ]
            if len(selected_rules) != 1:
                _reject("decision_event_selected_rule")
            if decision_event.selected_action_id != selected_rules[0].target_action_id:
                _reject("decision_event_selected_target")
        elif decision_event.decision_kind == "fallback":
            if decision_event.selected_action_id != policy.fallback_action_id:
                _reject("decision_event_fallback_action")

        # 15. Run plan: binding, deterministic Runtime-4 identifier, the
        # historical initial-action anchor, and the recomputed input hash.
        if (
            run_plan.tenant_id != tenant_id
            or run_plan.campaign_id != campaign.identifier
            or run_plan.world_version_id != world.identifier
            or run_plan.scenario_seed_id != seed.identifier
        ):
            _reject("run_plan_identity")
        expected_plan_id = run_plan_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            strategy_candidate_id=run_plan.strategy_candidate_id,
            scenario_seed_id=seed.identifier,
            runtime_version=ADAPTIVE_RUNTIME_VERSION,
        )
        if run_plan.identifier != expected_plan_id:
            _reject("run_plan_identifier")
        initial_actions = [
            action for action in policy.actions if action.action_id == policy.initial_action_id
        ]
        if len(initial_actions) != 1:
            _reject("policy_initial_action_resolution")
        if run_plan.strategy_candidate_id != initial_actions[0].strategy_candidate_id:
            _reject("run_plan_initial_action_anchor")
        if run_plan.input_hash != adaptive_run_input_hash(
            runtime_version=ADAPTIVE_RUNTIME_VERSION,
            world_content_hash=world.content_hash,
            policy=policy,
            seed=seed,
            world_realization_content_hash=realization.content_hash,
        ):
            _reject("run_plan_input_hash")

        # 16. Run status: identifier, ownership, complete binding, RUNNING
        # state with timestamps agreeing with the run plan, and no
        # reinterpreted event hash.
        if run_status.identifier != f"status-{run_id}":
            _reject("run_status_identifier")
        if (
            run_status.tenant_id != tenant_id
            or run_status.run_id != run_id
            or run_status.campaign_id != campaign.identifier
            or run_status.run_plan_id != run_plan.identifier
            or run_status.input_hash != run_plan.input_hash
        ):
            _reject("run_status_identity")
        if run_status.state is not RunState.RUNNING or run_status.event_hash is not None:
            _reject("run_status_state")
        if (
            run_status.created_at != run_plan.created_at
            or run_status.changed_at != run_plan.created_at
        ):
            _reject("run_status_timestamps")

        # 17. Exogenous inputs: canonical coordinate order, every coordinate
        # matching the verified authorities, and every value hash recomputed
        # exactly.
        coordinates = [entry.coordinate for entry in draft.exogenous_inputs]
        if coordinates != sorted(coordinates):
            _reject("exogenous_order")
        for entry in draft.exogenous_inputs:
            if (
                entry.world_version_id != world.identifier
                or entry.world_content_hash != world.content_hash
                or entry.seed_id != seed.identifier
                or entry.seed_content_hash != seed_hash
                or entry.run_id != run_id
                or entry.step_index != draft.step_index
                or entry.realization_id != realization.identifier
                or entry.realization_content_hash != realization.content_hash
            ):
                _reject("exogenous_identity")
            if entry.content_hash != sha256_hex(canonical_json(entry.value)):
                _reject("exogenous_value_hash")

        # 18. Request construction from verified authorities only.
        request, catalogue_hash = _verified_request(
            tenant_id=tenant_id,
            scenario=scenario,
            scenario_hash=scenario_hash,
            world=world,
            world_manifest=world_manifest,
            seed=seed,
            seed_hash=seed_hash,
            realization=realization,
            run_id=run_id,
            run_plan=run_plan,
            run_status=run_status,
            campaign=campaign,
            campaign_status=campaign_status,
            policy=policy,
            decision_event=decision_event,
            pack=pack,
            draft=draft,
        )

        # 19. Exactly one dispatch; the existing seam remains the final
        # authority for pack surface, request, and result verification.
        # The typed-error passthrough sits inside the try block so an
        # existing typed error (including one wrapping a pack step
        # exception) propagates unchanged rather than being rewrapped.
        try:
            verified_result = dispatch_domain_mechanism_step(pack, request)
        except DomainMechanismDispatchError:
            raise
        except Exception as exc:
            raise DomainMechanismDispatchError(
                "runtime4_mechanism_step_input_violates_its_contract"
            ) from exc
    except DomainMechanismDispatchError:
        raise
    except Exception as exc:
        raise DomainMechanismDispatchError(
            "runtime4_mechanism_step_input_violates_its_contract"
        ) from exc

    return Runtime4DomainMechanismStepExecution(
        runtime_version=ADAPTIVE_RUNTIME_VERSION,
        run_id=run_id,
        adaptive_policy_identifier=policy.identifier,
        policy_id=policy.policy_id,
        adaptive_policy_content_hash=policy.content_hash,
        decision_event=decision_event.model_copy(deep=True),
        selected_action_id=decision_event.selected_action_id,
        action_payload_catalogue_hash=catalogue_hash,
        request=request,
        result=verified_result,
    )
