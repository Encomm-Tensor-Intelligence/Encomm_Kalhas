"""Deterministic compiled-world integrity verification.

Proves that a stored ``WorldVersion`` and its ``WorldManifest`` still
exactly represent the deterministic output of the world compiler: the
embedded world body, scenario, and snapshot collections must parse as
the strict existing contracts, stay in canonical compiler order, and
recompile - with the recorded compiler version - to the same content
hash, the same world identifier, byte-identical world content, and the
same authoritative manifest. Verification is a pure, read-only,
deterministic function of the two stored records; it reuses the existing
compiler and canonical hashing conventions exclusively (there is no
second world-hash algorithm).

A stored world that fails any check is rejected with a safe typed
:class:`WorldSnapshotIntegrityError`: it is never repaired, normalized,
replaced, or silently accepted. The public message stays generic; the
internal ``reason`` names only the violated rule, never world contents,
state values, metadata, or raw hashes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from kalhas.application import world_compiler
from kalhas.application.deterministic_sampler import (
    QUANTIZATION_FRACTION_BITS,
    QUANTIZATION_POLICY,
    SAMPLER_VERSION,
    canonical_json_text,
    discrete_static_final_values,
    validate_effective_parameters,
)
from kalhas.application.domain_errors import (
    InvalidScenarioError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
)
from kalhas.application.world_compiler import (
    _canonical_bindings,
    _canonical_declarations,
    _canonical_domain_metric_observations,
    _canonical_state_models,
    _canonical_transitions,
)
from kalhas.application.world_uncertainty_identity import (
    uncertainty_model_content_hash,
    uncertainty_model_identifier,
)
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
)
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import MetricDefinition
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldManifest, WorldVersion
from kalhas.contracts.v1.world_realization import (
    DiscreteDistribution,
    WorldUncertaintyModel,
)

_WORLD_ID_PREFIX = "world-"
_MANIFEST_ID_PREFIX = "manifest-"
_ID_HASH_LENGTH = 16
_BINDINGS_KEY = "domain_pack_bindings"
_DECLARATIONS_KEY = "domain_capability_declarations"
_STATE_MODELS_KEY = "domain_state_models"
_TRANSITIONS_KEY = "domain_state_transitions"
_OBSERVATIONS_KEY = "domain_metric_observations"
_EVALUATION_PROFILE_KEY = "evaluation_profile"
_UNCERTAINTY_MODEL_KEY = "uncertainty_model"

# The exact set of compiler-owned top-level world body keys. Anything
# else is unexpected compiler-owned content and is rejected.
_WORLD_BODY_KEYS = frozenset(
    {
        "compiler_version",
        "content_hash",
        "scenario",
        _BINDINGS_KEY,
        _DECLARATIONS_KEY,
        _STATE_MODELS_KEY,
        _TRANSITIONS_KEY,
        _OBSERVATIONS_KEY,
        _EVALUATION_PROFILE_KEY,
        _UNCERTAINTY_MODEL_KEY,
    }
)
_REQUIRED_WORLD_BODY_KEYS = ("compiler_version", "content_hash", "scenario")


def _reject(world_version_id: str, reason: str) -> WorldSnapshotIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return WorldSnapshotIntegrityError(world_version_id, reason)


def _parse_snapshots[T: BaseModel](
    world_version_id: str,
    body: Mapping[str, object],
    key: str,
    contract: type[T],
    label: str,
) -> tuple[T, ...]:
    """Parse one embedded snapshot collection as the strict existing contract.

    An absent key means an empty collection (the compiler omits empty
    collections); a present key must hold a JSON array whose every entry
    validates as the contract, otherwise the embedded content is
    malformed and the world is rejected. The body is read as a covariant
    mapping so any JSON-shaped mapping (for example ``dict[str,
    JsonValue]``) can be verified without copying. The result tuple
    keeps the concrete contract type of the parsed entries.
    """
    if key not in body:
        return ()
    raw = body[key]
    if not isinstance(raw, list):
        raise _reject(world_version_id, f"embedded {label} is malformed")
    parsed: list[T] = []
    for entry in raw:
        try:
            parsed.append(contract.model_validate(entry))
        except ValidationError:
            raise _reject(world_version_id, f"embedded {label} is malformed") from None
    return tuple(parsed)


def _parse_single_snapshot[T: BaseModel](
    world_version_id: str,
    body: Mapping[str, object],
    key: str,
    contract: type[T],
    label: str,
) -> T | None:
    """Parse one optional embedded single-object snapshot as the strict contract.

    An absent key means no snapshot (the compiler omits the key when
    the feature is absent); a present key must hold exactly one JSON
    object validating as the contract, otherwise the embedded content
    is malformed and the world is rejected. Used for the optional
    single evaluation-profile snapshot, which is one object - not a
    collection.
    """
    if key not in body:
        return None
    raw = body[key]
    if not isinstance(raw, dict):
        raise _reject(world_version_id, f"embedded {label} is malformed")
    try:
        return contract.model_validate(raw)
    except ValidationError:
        raise _reject(world_version_id, f"embedded {label} is malformed") from None


def _verify_evaluation_profile_references(
    world_version_id: str,
    profile: ScenarioEvaluationProfile,
    scenario: ScenarioSpec,
) -> None:
    """Verify the embedded evaluation profile against the same compiled world.

    The profile is declarative provenance data; the verifier proves it
    is self-consistent with the compiled world: the profile belongs to
    the world's tenant and scenario, its authoritative scenario
    snapshot hash matches the recomputed digest of the embedded
    scenario, its identifier matches the independent derivation from
    the canonical identity payload, its content hash matches the
    recomputed canonical digest, its bindings cover every scenario
    objective exactly once **in the exact ``ScenarioSpec.objectives``
    order**, every referenced metric exists exactly once in the
    scenario, and every copied authoritative value (direction, target,
    weight, metric unit) equals the stored scenario record. Tolerance
    and normalization rules are additionally re-checked. The stored
    world is never repaired, normalized, reordered, or replaced; on any
    mismatch the world is rejected with a safe generic error whose
    internal reason names only the violated rule.
    """
    if profile.tenant_id != scenario.tenant_id:
        raise _reject(world_version_id, "embedded evaluation profile has a foreign tenant")
    if profile.scenario_id != scenario.identifier:
        raise _reject(world_version_id, "embedded evaluation profile has a foreign scenario")
    expected_hash = scenario_content_hash(scenario)
    if profile.scenario_content_hash != expected_hash:
        raise _reject(world_version_id, "embedded evaluation profile scenario hash mismatch")
    if profile.identifier != evaluation_profile_identifier(
        tenant_id=scenario.tenant_id,
        scenario_id=scenario.identifier,
        scenario_content_hash_value=expected_hash,
    ):
        raise _reject(world_version_id, "embedded evaluation profile identifier mismatch")
    if profile.content_hash != evaluation_profile_content_hash(profile):
        raise _reject(world_version_id, "embedded evaluation profile content hash mismatch")

    objective_ids = [objective.identifier for objective in scenario.objectives]
    if len(objective_ids) != len(set(objective_ids)):
        raise _reject(world_version_id, "embedded scenario objective identifiers are not unique")
    binding_ids = [binding.objective_id for binding in profile.bindings]
    if binding_ids != objective_ids:
        raise _reject(
            world_version_id,
            "embedded evaluation profile bindings do not match the scenario objectives "
            "exactly, in exact scenario order",
        )
    objectives_by_id = {objective.identifier: objective for objective in scenario.objectives}
    metric_count_by_id: dict[str, int] = {}
    for metric in scenario.metrics:
        metric_count_by_id[metric.identifier] = metric_count_by_id.get(metric.identifier, 0) + 1
    metrics_by_id: dict[str, MetricDefinition] = {}
    for metric in scenario.metrics:
        metrics_by_id[metric.identifier] = metric
    for binding in profile.bindings:
        objective = objectives_by_id[binding.objective_id]
        if binding.direction != objective.direction.value:
            raise _reject(world_version_id, "embedded evaluation profile direction mismatch")
        if binding.target != objective.target:
            raise _reject(world_version_id, "embedded evaluation profile target mismatch")
        if binding.weight != objective.weight:
            raise _reject(world_version_id, "embedded evaluation profile weight mismatch")
        if metric_count_by_id.get(binding.metric_id, 0) != 1:
            raise _reject(
                world_version_id,
                "embedded evaluation profile references an unknown scenario metric",
            )
        metric = metrics_by_id[binding.metric_id]
        if binding.metric_unit != metric.unit:
            raise _reject(world_version_id, "embedded evaluation profile metric unit mismatch")
        if binding.direction == "reach":
            if binding.reach_tolerance is None or binding.reach_tolerance < 0.0:
                raise _reject(
                    world_version_id, "embedded evaluation profile tolerance rule violation"
                )
        elif binding.reach_tolerance is not None:
            raise _reject(world_version_id, "embedded evaluation profile tolerance rule violation")
        if binding.normalization_scale <= 0.0:
            raise _reject(
                world_version_id,
                "embedded evaluation profile normalization scale violation",
            )


def _verify_uncertainty_model_references(
    world_version_id: str,
    model: WorldUncertaintyModel,
    scenario: ScenarioSpec,
    bindings: tuple[DomainPackBinding, ...],
    state_models: tuple[DomainStateModel, ...],
) -> None:
    """Verify the embedded uncertainty model against the same compiled world.

    The model is declarative provenance data; the verifier proves it is
    self-consistent with the compiled world: the model belongs to the
    world's tenant and scenario, its authoritative scenario snapshot
    hash matches the recomputed digest of the embedded scenario, its
    identifier matches the independent derivation from the canonical
    identity payload, its content hash matches the recomputed canonical
    digest, its bindings are in the exact canonical
    ``(manifest_id, state_model_id, state_field_id)`` order with unique
    target tuples, and every binding's copied provenance resolves
    exactly against the embedded pack-binding and state-model snapshots
    (source binding identifier, manifest, pack identity, manifest
    content hash, deterministic state-model identifier, logical
    state-model id, state-model content hash, target state field, and
    copied field value kind). The frozen sampler/quantization
    provenance literals must equal the versioned constants, the
    effective Q64.64 parameter rules must hold, and - for discrete
    distributions with a declared ``allowed_values`` set - every
    statically selectable final value must be canonically allowed. The
    stored world is never repaired, normalized, reordered, or replaced;
    on any mismatch the world is rejected with a safe generic error
    whose internal reason names only the violated rule.
    """
    if model.tenant_id != scenario.tenant_id:
        raise _reject(world_version_id, "embedded uncertainty model has a foreign tenant")
    if model.scenario_id != scenario.identifier:
        raise _reject(world_version_id, "embedded uncertainty model has a foreign scenario")
    expected_hash = scenario_content_hash(scenario)
    if model.scenario_content_hash != expected_hash:
        raise _reject(world_version_id, "embedded uncertainty model scenario hash mismatch")
    if model.identifier != uncertainty_model_identifier(
        tenant_id=scenario.tenant_id,
        scenario_id=scenario.identifier,
        scenario_content_hash_value=expected_hash,
    ):
        raise _reject(world_version_id, "embedded uncertainty model identifier mismatch")
    if model.content_hash != uncertainty_model_content_hash(model):
        raise _reject(world_version_id, "embedded uncertainty model content hash mismatch")

    ordered = tuple(
        sorted(
            model.bindings,
            key=lambda binding: (
                binding.manifest_id,
                binding.state_model_id,
                binding.state_field_id,
            ),
        )
    )
    if model.bindings != ordered:
        raise _reject(world_version_id, "embedded uncertainty model bindings are not canonical")

    state_models_by_identifier = {
        state_model.identifier: state_model for state_model in state_models
    }
    pack_bindings_by_manifest = {binding.manifest_id: binding for binding in bindings}
    for binding in model.bindings:
        state_model = state_models_by_identifier.get(binding.state_model_identifier)
        if state_model is None:
            raise _reject(
                world_version_id,
                "embedded uncertainty model references an unknown state model",
            )
        if state_model.state_model_id != binding.state_model_id:
            raise _reject(
                world_version_id, "embedded uncertainty model state model identity mismatch"
            )
        if state_model.content_hash != binding.state_model_content_hash:
            raise _reject(
                world_version_id,
                "embedded uncertainty model state model content hash mismatch",
            )
        if state_model.manifest_id != binding.manifest_id:
            raise _reject(
                world_version_id, "embedded uncertainty model state model manifest mismatch"
            )
        field = next(
            (
                candidate
                for candidate in state_model.state_fields
                if candidate.identifier == binding.state_field_id
            ),
            None,
        )
        if field is None:
            raise _reject(
                world_version_id,
                "embedded uncertainty model references an unknown state field",
            )
        if field.value_kind.value != binding.state_field_value_kind:
            raise _reject(
                world_version_id,
                "embedded uncertainty model state field value kind mismatch",
            )
        pack_binding = pack_bindings_by_manifest.get(binding.manifest_id)
        if pack_binding is None:
            raise _reject(
                world_version_id,
                "embedded uncertainty model references an unknown pack binding",
            )
        if pack_binding.identifier != binding.binding_id:
            raise _reject(
                world_version_id, "embedded uncertainty model pack binding identity mismatch"
            )
        if (
            pack_binding.pack_id != binding.pack_id
            or pack_binding.pack_version != binding.pack_version
        ):
            raise _reject(world_version_id, "embedded uncertainty model pack identity mismatch")
        if pack_binding.manifest_content_hash != binding.manifest_content_hash:
            raise _reject(
                world_version_id,
                "embedded uncertainty model manifest content hash mismatch",
            )
        if (
            binding.sampler_version != SAMPLER_VERSION
            or binding.quantization_policy != QUANTIZATION_POLICY
            or binding.quantization_fraction_bits != QUANTIZATION_FRACTION_BITS
        ):
            raise _reject(
                world_version_id,
                "embedded uncertainty model sampler provenance mismatch",
            )
        try:
            validate_effective_parameters(
                binding.distribution,
                lower_bound=binding.lower_bound,
                upper_bound=binding.upper_bound,
            )
        except ValueError:
            raise _reject(
                world_version_id,
                "embedded uncertainty model parameter rules violated",
            ) from None
        if isinstance(binding.distribution, DiscreteDistribution) and field.allowed_values:
            try:
                final_values = discrete_static_final_values(
                    binding.distribution,
                    lower_bound=binding.lower_bound,
                    upper_bound=binding.upper_bound,
                    field_kind=binding.state_field_value_kind,
                    rounding_policy=binding.rounding_policy,
                )
            except ValueError:
                raise _reject(
                    world_version_id,
                    "embedded uncertainty model discrete outcome rules violated",
                ) from None
            allowed = {canonical_json_text(value) for value in field.allowed_values}
            for value in final_values:
                if canonical_json_text(value) not in allowed:
                    raise _reject(
                        world_version_id,
                        "embedded uncertainty model discrete outcome not among allowed_values",
                    )


def _verify_observation_references(
    world_version_id: str,
    observations: tuple[DomainMetricObservationBinding, ...],
    scenario: ScenarioSpec,
    bindings: tuple[DomainPackBinding, ...],
    state_models: tuple[DomainStateModel, ...],
) -> None:
    """Verify every embedded observation binding against the same compiled world.

    Each observation binding is declarative provenance data; the
    verifier proves it is self-consistent with the rest of the compiled
    world: the binding belongs to the world's tenant and scenario, its
    metric identifies exactly one metric of the embedded scenario, its
    referenced state model exists in the same compiled world with the
    exact copied deterministic identifier, logical state-model id, and
    authoritative content hash, its referenced state field exists in
    that model, its copied numeric value kind matches the authoritative
    model field, and its referenced pack binding exists in the compiled
    catalog with the exact copied binding/manifest identity. Duplicate
    metric bindings and non-canonical ordering are rejected. The stored
    world is never repaired, normalized, reordered, or replaced; on any
    mismatch the world is rejected with a safe generic error whose
    internal reason names only the violated rule.
    """
    metric_ids = [observation.metric_id for observation in observations]
    if len(metric_ids) != len(set(metric_ids)):
        raise _reject(
            world_version_id,
            "embedded domain metric observations contain duplicate metric bindings",
        )
    by_identifier = {state_model.identifier: state_model for state_model in state_models}
    bindings_by_manifest = {binding.manifest_id: binding for binding in bindings}
    metric_count_by_id: dict[str, int] = {}
    for metric in scenario.metrics:
        metric_count_by_id[metric.identifier] = metric_count_by_id.get(metric.identifier, 0) + 1
    for observation in observations:
        if observation.tenant_id != scenario.tenant_id:
            raise _reject(world_version_id, "embedded observation has a foreign tenant")
        if observation.scenario_id != scenario.identifier:
            raise _reject(world_version_id, "embedded observation has a foreign scenario")
        if metric_count_by_id.get(observation.metric_id, 0) != 1:
            raise _reject(
                world_version_id, "embedded observation references an unknown scenario metric"
            )
        state_model = by_identifier.get(observation.state_model_identifier)
        if state_model is None:
            raise _reject(
                world_version_id, "embedded observation references an unknown state model"
            )
        if state_model.state_model_id != observation.state_model_id:
            raise _reject(world_version_id, "embedded observation state model identity mismatch")
        if state_model.content_hash != observation.state_model_content_hash:
            raise _reject(
                world_version_id, "embedded observation state model content hash mismatch"
            )
        if state_model.manifest_id != observation.manifest_id:
            raise _reject(world_version_id, "embedded observation state model manifest mismatch")
        field = next(
            (
                field
                for field in state_model.state_fields
                if field.identifier == observation.state_field_id
            ),
            None,
        )
        if field is None:
            raise _reject(
                world_version_id, "embedded observation references an unknown state field"
            )
        if field.value_kind.value != observation.state_field_value_kind:
            raise _reject(world_version_id, "embedded observation state field value kind mismatch")
        binding = bindings_by_manifest.get(observation.manifest_id)
        if binding is None:
            raise _reject(
                world_version_id, "embedded observation references an unknown pack binding"
            )
        if binding.identifier != observation.binding_id:
            raise _reject(world_version_id, "embedded observation pack binding identity mismatch")
        if (
            binding.pack_id != observation.pack_id
            or binding.pack_version != observation.pack_version
        ):
            raise _reject(world_version_id, "embedded observation pack identity mismatch")
        if binding.manifest_content_hash != observation.manifest_content_hash:
            raise _reject(world_version_id, "embedded observation manifest content hash mismatch")


def verify_world_snapshot(world: WorldVersion, manifest: WorldManifest) -> None:
    """Verify a stored world and manifest exactly represent compiler output.

    Pure and read-only: nothing is repaired, normalized, replaced, or
    silently accepted; any failure raises a safe typed
    :class:`WorldSnapshotIntegrityError`. The check order below is
    deterministic: identity and provenance first, then structural
    shape, then embedded parsing and canonical order, then full
    recompilation equality.
    """
    if world.tenant_id != manifest.tenant_id:
        raise _reject(world.identifier, "world tenant mismatch")
    if world.identifier != f"{_WORLD_ID_PREFIX}{world.content_hash[:_ID_HASH_LENGTH]}":
        raise _reject(world.identifier, "world identifier mismatch")
    if manifest.identifier != f"{_MANIFEST_ID_PREFIX}{world.content_hash[:_ID_HASH_LENGTH]}":
        raise _reject(world.identifier, "manifest identifier mismatch")
    if manifest.world_version_id != world.identifier:
        raise _reject(world.identifier, "manifest world reference mismatch")
    if world.compiler_version != world_compiler.COMPILER_VERSION:
        raise _reject(world.identifier, "unsupported compiler version")

    body = world.world
    missing = [key for key in _REQUIRED_WORLD_BODY_KEYS if key not in body]
    if missing:
        raise _reject(world.identifier, "world body is missing compiler-owned fields")
    unexpected = sorted(set(body) - _WORLD_BODY_KEYS)
    if unexpected:
        raise _reject(world.identifier, "world body has unexpected compiler-owned fields")
    if not isinstance(body["content_hash"], str) or body["content_hash"] != world.content_hash:
        raise _reject(world.identifier, "world body content hash mismatch")
    if not isinstance(body["compiler_version"], str) or body["compiler_version"] != (
        world.compiler_version
    ):
        raise _reject(world.identifier, "world body compiler version mismatch")

    raw_scenario = body["scenario"]
    if not isinstance(raw_scenario, dict):
        raise _reject(world.identifier, "embedded scenario is malformed")
    try:
        scenario = ScenarioSpec.model_validate(raw_scenario)
    except ValidationError:
        raise _reject(world.identifier, "embedded scenario is malformed") from None
    if scenario.tenant_id != world.tenant_id:
        raise _reject(world.identifier, "scenario tenant mismatch")
    if scenario.identifier != world.source_scenario_id:
        raise _reject(world.identifier, "scenario identifier mismatch")
    if scenario.created_at != world.created_at:
        raise _reject(world.identifier, "scenario provenance mismatch")

    bindings = _parse_snapshots(
        world.identifier, body, _BINDINGS_KEY, DomainPackBinding, "domain pack binding"
    )
    declarations = _parse_snapshots(
        world.identifier,
        body,
        _DECLARATIONS_KEY,
        DomainCapabilityDeclaration,
        "domain capability declaration",
    )
    state_models = _parse_snapshots(
        world.identifier, body, _STATE_MODELS_KEY, DomainStateModel, "domain state model"
    )
    transitions = _parse_snapshots(
        world.identifier,
        body,
        _TRANSITIONS_KEY,
        DomainStateTransition,
        "domain state transition",
    )
    observations = _parse_snapshots(
        world.identifier,
        body,
        _OBSERVATIONS_KEY,
        DomainMetricObservationBinding,
        "domain metric observation",
    )
    evaluation_profile = _parse_single_snapshot(
        world.identifier,
        body,
        _EVALUATION_PROFILE_KEY,
        ScenarioEvaluationProfile,
        "evaluation profile",
    )
    uncertainty_model = _parse_single_snapshot(
        world.identifier,
        body,
        _UNCERTAINTY_MODEL_KEY,
        WorldUncertaintyModel,
        "uncertainty model",
    )

    if bindings != _canonical_bindings(bindings):
        raise _reject(world.identifier, "embedded domain pack bindings are not canonical")
    if declarations != _canonical_declarations(declarations):
        raise _reject(world.identifier, "embedded capability declarations are not canonical")
    if state_models != _canonical_state_models(state_models):
        raise _reject(world.identifier, "embedded state models are not canonical")
    if transitions != _canonical_transitions(transitions):
        raise _reject(world.identifier, "embedded transitions are not canonical")
    if observations != _canonical_domain_metric_observations(observations):
        raise _reject(world.identifier, "embedded domain metric observations are not canonical")
    _verify_observation_references(world.identifier, observations, scenario, bindings, state_models)
    if evaluation_profile is not None:
        _verify_evaluation_profile_references(world.identifier, evaluation_profile, scenario)
    if uncertainty_model is not None:
        _verify_uncertainty_model_references(
            world.identifier,
            uncertainty_model,
            scenario,
            bindings,
            state_models,
        )

    try:
        compiled = world_compiler.compile_world(
            scenario,
            compiler_version=world.compiler_version,
            bindings=bindings,
            declarations=declarations,
            state_models=state_models,
            transitions=transitions,
            domain_metric_observations=observations,
            evaluation_profile=evaluation_profile,
            uncertainty_model=uncertainty_model,
        )
    except InvalidScenarioError:
        raise _reject(world.identifier, "embedded scenario is semantically invalid") from None
    if compiled.version != world:
        raise _reject(world.identifier, "recompiled world content mismatch")
    if compiled.manifest != manifest:
        raise _reject(world.identifier, "recompiled manifest mismatch")


@dataclass(frozen=True)
class VerifiedWorldCatalog:
    """The state models, transitions, observation bindings, profile, and
    uncertainty model of a verified world.

    Parsed strictly from the compiled ``WorldVersion`` snapshot in the
    compiler's canonical ordering. Only these embedded snapshots are
    authoritative for downstream consumers: declarations added to the
    live registries after compilation never influence this catalog.
    """

    state_models: tuple[DomainStateModel, ...]
    transitions: tuple[DomainStateTransition, ...]
    domain_metric_observations: tuple[DomainMetricObservationBinding, ...] = ()
    evaluation_profile: ScenarioEvaluationProfile | None = None
    uncertainty_model: WorldUncertaintyModel | None = None


def extract_world_catalog(world: WorldVersion) -> VerifiedWorldCatalog:
    """Strictly parse the snapshot families of a verified world body.

    Read-only and deterministic: state models, transitions, and domain
    metric observation bindings are parsed with the strict existing
    contracts, in the body's (canonical) order. An absent family key
    means an empty collection; malformed embedded content raises
    :class:`WorldSnapshotIntegrityError` - the same typed rejection
    ``verify_world_snapshot`` produces, so a verified world can never
    yield a malformed catalog.
    """
    body = world.world
    state_models = _parse_snapshots(
        world.identifier, body, _STATE_MODELS_KEY, DomainStateModel, "domain state model"
    )
    transitions = _parse_snapshots(
        world.identifier,
        body,
        _TRANSITIONS_KEY,
        DomainStateTransition,
        "domain state transition",
    )
    observations = _parse_snapshots(
        world.identifier,
        body,
        _OBSERVATIONS_KEY,
        DomainMetricObservationBinding,
        "domain metric observation",
    )
    evaluation_profile = _parse_single_snapshot(
        world.identifier,
        body,
        _EVALUATION_PROFILE_KEY,
        ScenarioEvaluationProfile,
        "evaluation profile",
    )
    uncertainty_model = _parse_single_snapshot(
        world.identifier,
        body,
        _UNCERTAINTY_MODEL_KEY,
        WorldUncertaintyModel,
        "uncertainty model",
    )
    return VerifiedWorldCatalog(
        state_models=state_models,
        transitions=transitions,
        domain_metric_observations=observations,
        evaluation_profile=evaluation_profile,
        uncertainty_model=uncertainty_model,
    )
