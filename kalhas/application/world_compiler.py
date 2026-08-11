"""Deterministic world compiler.

Accepts only a semantically valid ScenarioSpec and produces an immutable
WorldVersion plus a WorldManifest. Compilation is a pure function of its
inputs: no randomness, no wall-clock time, no network access, no provider.
The same logical scenario plus the same compiler version always yields the
same content hash and world identifier.

The compiled world contains only a generic declarative representation of
the scenario - it compiles scenario elements, not entities, so the
manifest's ``entity_count`` is 0. No simulation mechanisms and no domain
packs are involved.

When the scenario has registered domain-pack bindings, their complete
serialized snapshots (``DomainPackBinding`` contracts) are included in the
world content and in the canonical content hash. A scenario with no
bindings compiles exactly as before: the hash input and world content are
byte-identical to the unbound compiler. The compiler never inspects,
loads, or executes a domain pack - bindings are declarative data.

When the scenario has declared capability inputs, their complete
serialized snapshots (``DomainCapabilityDeclaration`` contracts) are
similarly included under ``domain_capability_declarations`` in the world
content and in the canonical content hash - only when non-empty, so
declaration-free worlds compile byte-identically to the Phase 7 compiler.
Declarations are inert inputs: the compiler never interprets their
schemas and never loads, imports, instantiates, or executes a domain
pack.

When the scenario has declared domain state models, their complete
serialized snapshots (``DomainStateModel`` contracts) are included under
``domain_state_models`` in the world content and in the canonical content
hash - only when non-empty, so state-model-free worlds compile
byte-identically to the Phase 10 compiler. State models are data only:
the compiler never executes, evaluates, derives, or mutates any state
field, and never interprets field values or allowed values.

When the scenario has declared domain state transitions, their complete
serialized snapshots (``DomainStateTransition`` contracts) are included
under ``domain_state_transitions`` in the world content and in the
canonical content hash - only when non-empty, so transition-free worlds
compile byte-identically to the Phase 11 compiler. Transitions are data
only: the compiler never evaluates a guard or applies a target state
patch, and never interprets guard or target values.

When the scenario has declared domain metric observation bindings, their
complete serialized snapshots (``DomainMetricObservationBinding``
contracts) are included under ``domain_metric_observations`` in the
world content and in the canonical content hash - only when non-empty,
so observation-free worlds compile byte-identically to the Phase 18
compiler. Observation bindings are inert declarative provenance data:
the compiler never interprets, extracts, or evaluates a metric value, a
state field, or an observation point, and never reads a trajectory
execution.

When the scenario has a declared evaluation profile, its complete
serialized snapshot (one ``ScenarioEvaluationProfile`` object) is
included under ``evaluation_profile`` in the world content and in the
canonical content hash - only when present, so profile-free worlds
compile byte-identically to the Phase 22 compiler. The profile is an
inert declarative snapshot: the compiler never interprets objective
direction, target, weight, tolerance, normalization scale, or metric
unit semantics - it only canonicalizes and embeds the immutable
profile.

The compiler never relies on caller-provided collection ordering:
bindings are canonicalized by ``manifest_id``, declarations by
``(manifest_id, capability_id)``, state models by
``(manifest_id, state_model_id)`` with their state fields re-canonicalized
by identifier, transitions by ``(manifest_id, state_model_id,
transition_id)`` with their guard/target mappings re-canonicalized by
field identifier inside the compiler, and observation bindings by
``metric_id``, so equivalent snapshot sets supplied in any tuple order
compile to the same content hash and the same serialized world content.
The evaluation profile is a single object whose binding order is
already canonical by contract (exact ``ScenarioSpec.objectives``
order); the compiler embeds it exactly as stored. Already correctly
ordered inputs sort to the identical order, so established hashes are
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalhas.application.domain_errors import InvalidScenarioError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.scenario_service import validate_scenario
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
)
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion

COMPILER_VERSION = "1.0.0"
_WORLD_ID_PREFIX = "world-"
_MANIFEST_ID_PREFIX = "manifest-"
_ID_HASH_LENGTH = 16
_BINDINGS_KEY = "domain_pack_bindings"
_DECLARATIONS_KEY = "domain_capability_declarations"
_STATE_MODELS_KEY = "domain_state_models"
_TRANSITIONS_KEY = "domain_state_transitions"
_OBSERVATIONS_KEY = "domain_metric_observations"
_EVALUATION_PROFILE_KEY = "evaluation_profile"


def _binding_sort_key(binding: DomainPackBinding) -> str:
    """Canonical ordering key for binding snapshots: manifest identifier."""
    return binding.manifest_id


def _declaration_sort_key(declaration: DomainCapabilityDeclaration) -> tuple[str, str]:
    """Canonical ordering key for declaration snapshots."""
    return (declaration.manifest_id, declaration.capability_id)


def _state_model_sort_key(state_model: DomainStateModel) -> tuple[str, str]:
    """Canonical ordering key for state-model snapshots."""
    return (state_model.manifest_id, state_model.state_model_id)


def _transition_sort_key(transition: DomainStateTransition) -> tuple[str, str, str]:
    """Canonical ordering key for transition snapshots."""
    return (
        transition.manifest_id,
        transition.state_model_id,
        transition.transition_id,
    )


def _observation_sort_key(observation: DomainMetricObservationBinding) -> str:
    """Canonical ordering key for observation-binding snapshots: metric identifier."""
    return observation.metric_id


def _canonical_bindings(
    bindings: tuple[DomainPackBinding, ...],
) -> tuple[DomainPackBinding, ...]:
    """Sort binding snapshots by manifest identifier (deterministic)."""
    return tuple(sorted(bindings, key=_binding_sort_key))


def _canonical_declarations(
    declarations: tuple[DomainCapabilityDeclaration, ...],
) -> tuple[DomainCapabilityDeclaration, ...]:
    """Sort declaration snapshots by manifest then capability identifier."""
    return tuple(sorted(declarations, key=_declaration_sort_key))


def _canonical_state_models(
    state_models: tuple[DomainStateModel, ...],
) -> tuple[DomainStateModel, ...]:
    """Sort state-model snapshots by manifest then state-model identifier.

    Each model's state fields are additionally re-canonicalized by
    identifier, so even a hand-built model with non-canonical field
    ordering compiles to the same snapshot and hash as its canonical
    equivalent. State fields are data only: nothing is executed,
    evaluated, derived, or mutated.
    """
    ordered = sorted(state_models, key=_state_model_sort_key)
    canonical: list[DomainStateModel] = []
    for state_model in ordered:
        fields = tuple(sorted(state_model.state_fields, key=lambda field: field.identifier))
        canonical.append(state_model.model_copy(update={"state_fields": fields}))
    return tuple(canonical)


def _canonical_transitions(
    transitions: tuple[DomainStateTransition, ...],
) -> tuple[DomainStateTransition, ...]:
    """Sort transition snapshots by manifest, state model, then transition.

    Each transition's guard/target mappings are additionally
    re-canonicalized by field identifier, so even a hand-built transition
    with non-canonical mapping ordering compiles to the same snapshot and
    hash as its canonical equivalent. Transitions are data only: a guard
    is never evaluated and a target state patch is never applied.
    """
    ordered = sorted(transitions, key=_transition_sort_key)
    canonical: list[DomainStateTransition] = []
    for transition in ordered:
        canonical.append(
            transition.model_copy(
                update={
                    "guard_values": dict(sorted(transition.guard_values.items())),
                    "target_values": dict(sorted(transition.target_values.items())),
                }
            )
        )
    return tuple(canonical)


def _canonical_domain_metric_observations(
    observations: tuple[DomainMetricObservationBinding, ...],
) -> tuple[DomainMetricObservationBinding, ...]:
    """Sort observation-binding snapshots by metric identifier (deterministic).

    Observation bindings are declarative data: the compiler never
    interprets, extracts, or evaluates a metric value, a state field, or
    an observation point - it embeds the complete serialized snapshots
    only.
    """
    return tuple(sorted(observations, key=_observation_sort_key))


def content_hash(
    scenario: ScenarioSpec,
    compiler_version: str = COMPILER_VERSION,
    bindings: tuple[DomainPackBinding, ...] = (),
    declarations: tuple[DomainCapabilityDeclaration, ...] = (),
    state_models: tuple[DomainStateModel, ...] = (),
    transitions: tuple[DomainStateTransition, ...] = (),
    domain_metric_observations: tuple[DomainMetricObservationBinding, ...] = (),
    evaluation_profile: ScenarioEvaluationProfile | None = None,
) -> str:
    """SHA-256 of the canonical scenario serialization plus the compiler version.

    Stored bindings are included as their complete serialized snapshots
    in canonical manifest-id order; an empty binding set leaves the
    canonical payload byte-identical to the pre-binding compiler, so
    unbound scenarios keep their exact hash. Declared capability inputs
    are included as complete serialized snapshots in canonical
    manifest-id then capability-id order - only when non-empty, so
    declaration-free worlds keep their exact Phase 7 hash. Declared state
    models are included as complete serialized snapshots in canonical
    manifest-id then state-model-id order with fields canonicalized by
    identifier - only when non-empty, so state-model-free worlds keep
    their exact Phase 10 hash. Declared state transitions are included as
    complete serialized snapshots in canonical manifest-id,
    state-model-id, then transition-id order with guard/target mappings
    canonicalized by field identifier - only when non-empty, so
    transition-free worlds keep their exact Phase 11 hash. Declared
    domain metric observation bindings are included as complete
    serialized snapshots in canonical metric-id order - only when
    non-empty, so observation-free worlds keep their exact Phase 18
    hash. A declared evaluation profile is included as its complete
    serialized snapshot - only when present, so profile-free worlds
    keep their exact Phase 22 hash. Caller-supplied tuple order never
    affects the digest.
    """
    canonical_bindings = _canonical_bindings(bindings)
    canonical_declarations = _canonical_declarations(declarations)
    canonical_state_models = _canonical_state_models(state_models)
    canonical_transitions = _canonical_transitions(transitions)
    canonical_observations = _canonical_domain_metric_observations(domain_metric_observations)
    payload: dict[str, object] = {
        "compiler_version": compiler_version,
        "scenario": scenario.model_dump(mode="json"),
    }
    if canonical_bindings:
        payload[_BINDINGS_KEY] = [binding.model_dump(mode="json") for binding in canonical_bindings]
    if canonical_declarations:
        payload[_DECLARATIONS_KEY] = [
            declaration.model_dump(mode="json") for declaration in canonical_declarations
        ]
    if canonical_state_models:
        payload[_STATE_MODELS_KEY] = [
            state_model.model_dump(mode="json") for state_model in canonical_state_models
        ]
    if canonical_transitions:
        payload[_TRANSITIONS_KEY] = [
            transition.model_dump(mode="json") for transition in canonical_transitions
        ]
    if canonical_observations:
        payload[_OBSERVATIONS_KEY] = [
            observation.model_dump(mode="json") for observation in canonical_observations
        ]
    if evaluation_profile is not None:
        payload[_EVALUATION_PROFILE_KEY] = evaluation_profile.model_dump(mode="json")
    return sha256_hex(canonical_json(payload))


@dataclass(frozen=True)
class CompiledWorld:
    """The immutable world version and its manifest."""

    version: WorldVersion
    manifest: WorldManifest


def compile_world(
    scenario: ScenarioSpec,
    *,
    compiler_version: str = COMPILER_VERSION,
    bindings: tuple[DomainPackBinding, ...] = (),
    declarations: tuple[DomainCapabilityDeclaration, ...] = (),
    state_models: tuple[DomainStateModel, ...] = (),
    transitions: tuple[DomainStateTransition, ...] = (),
    domain_metric_observations: tuple[DomainMetricObservationBinding, ...] = (),
    evaluation_profile: ScenarioEvaluationProfile | None = None,
) -> CompiledWorld:
    """Compile a semantically valid scenario into an immutable world.

    Raises :class:`InvalidScenarioError` (carrying the validation report)
    when the scenario is semantically invalid. Registered bindings,
    declared capability inputs, declared domain state models, declared
    domain state transitions, and declared domain metric observation
    bindings are embedded as declarative snapshots only, canonicalized
    inside the compiler (bindings by ``manifest_id``, declarations by
    ``(manifest_id, capability_id)``, state models by
    ``(manifest_id, state_model_id)`` with fields by identifier,
    transitions by ``(manifest_id, state_model_id, transition_id)`` with
    guard/target mappings by field identifier, observation bindings by
    ``metric_id``) so caller-supplied tuple order never affects the
    compiled world, its content hash, or the manifest counts. A declared
    evaluation profile is embedded as one complete serialized snapshot
    under ``evaluation_profile`` - only when present, so profile-free
    worlds compile byte-identically to the Phase 22 compiler. The
    compiler never inspects, loads, executes, or interprets a domain
    pack, a state field, a transition guard, a target state patch, an
    observation binding, or an evaluation profile - profile snapshots
    are inert declarative data.
    """
    result = validate_scenario(scenario, validated_at=scenario.created_at)
    if not result.report.valid:
        raise InvalidScenarioError(result.report)

    canonical_bindings = _canonical_bindings(bindings)
    canonical_declarations = _canonical_declarations(declarations)
    canonical_state_models = _canonical_state_models(state_models)
    canonical_transitions = _canonical_transitions(transitions)
    canonical_observations = _canonical_domain_metric_observations(domain_metric_observations)
    digest = content_hash(
        scenario,
        compiler_version,
        bindings,
        declarations,
        state_models,
        transitions,
        domain_metric_observations,
        evaluation_profile,
    )
    world_id = f"{_WORLD_ID_PREFIX}{digest[:_ID_HASH_LENGTH]}"
    world_content: dict[str, JsonValue] = {
        "compiler_version": compiler_version,
        "content_hash": digest,
        "scenario": scenario.model_dump(mode="json"),
    }
    if canonical_bindings:
        world_content[_BINDINGS_KEY] = [
            binding.model_dump(mode="json") for binding in canonical_bindings
        ]
    if canonical_declarations:
        world_content[_DECLARATIONS_KEY] = [
            declaration.model_dump(mode="json") for declaration in canonical_declarations
        ]
    if canonical_state_models:
        world_content[_STATE_MODELS_KEY] = [
            state_model.model_dump(mode="json") for state_model in canonical_state_models
        ]
    if canonical_transitions:
        world_content[_TRANSITIONS_KEY] = [
            transition.model_dump(mode="json") for transition in canonical_transitions
        ]
    if canonical_observations:
        world_content[_OBSERVATIONS_KEY] = [
            observation.model_dump(mode="json") for observation in canonical_observations
        ]
    if evaluation_profile is not None:
        world_content[_EVALUATION_PROFILE_KEY] = evaluation_profile.model_dump(mode="json")
    world_version = WorldVersion(
        identifier=world_id,
        tenant_id=scenario.tenant_id,
        parent_version_id=None,
        source_scenario_id=scenario.identifier,
        compiler_version=compiler_version,
        content_hash=digest,
        created_at=scenario.created_at,
        world=world_content,
        metadata={"source_scenario_id": scenario.identifier},
    )
    state: dict[str, JsonValue] = {
        "declared_objective_ids": [objective.identifier for objective in scenario.objectives],
        "declared_constraint_ids": [constraint.identifier for constraint in scenario.constraints],
        "declared_metric_ids": [metric.identifier for metric in scenario.metrics],
        "declared_assumption_ids": [assumption.identifier for assumption in scenario.assumptions],
        "declared_objective_count": len(scenario.objectives),
        "declared_constraint_count": len(scenario.constraints),
        "declared_metric_count": len(scenario.metrics),
        "declared_assumption_count": len(scenario.assumptions),
    }
    if canonical_bindings:
        state["declared_domain_pack_binding_count"] = len(canonical_bindings)
    if canonical_declarations:
        state["declared_domain_capability_declaration_count"] = len(canonical_declarations)
    if canonical_state_models:
        state["declared_domain_state_model_count"] = len(canonical_state_models)
    if canonical_transitions:
        state["declared_domain_state_transition_count"] = len(canonical_transitions)
    if canonical_observations:
        state["declared_domain_metric_observation_count"] = len(canonical_observations)
    if evaluation_profile is not None:
        state["declared_evaluation_profile_count"] = 1
    manifest = WorldManifest(
        identifier=f"{_MANIFEST_ID_PREFIX}{digest[:_ID_HASH_LENGTH]}",
        tenant_id=scenario.tenant_id,
        world_version_id=world_id,
        entity_count=0,
        state=state,
        metadata={"compiler_version": compiler_version, "content_hash": digest},
    )
    return CompiledWorld(version=world_version, manifest=manifest)
