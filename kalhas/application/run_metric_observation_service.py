"""Deterministic run metric-observation extraction and verification (Phase 20).

Extracts the immutable, tenant-scoped ``RunMetricObservationSet`` of one
runtime 2.0.0 run from its **completely verified** stored
``RunTrajectoryExecution``, using **only** the
``DomainMetricObservationBinding`` snapshots embedded in the run's exact
compiled ``WorldVersion`` - never newer scenario-level declarations
added after world compilation.

The extraction pipeline is strictly ordered:

1. ``verify_run_trajectory_inputs`` (the existing Phase 16/17 verifier)
   loads and verifies every recorded trajectory input - run status, run
   plan, campaign, compiled world (full ``verify_world_snapshot``
   recompilation check), recorded strategy, recorded seed, runtime
   version, and input hash - and resolves the exact applicable plan
   tuple and the closed compiled-world catalogs. Unknown or foreign runs
   fail with the store's typed not-found error; tampered inputs fail
   with the typed integrity error.
2. The recorded runtime version must be exactly ``"2.0.0"`` (legacy
   1.0.0 and unsupported versions raise the typed unsupported-version
   error) and the run must be COMPLETE (typed invalid-state error
   otherwise).
3. The stored ``RunTrajectoryExecution`` is loaded **only through the
   store boundary** (a fresh deep copy) and fully verified with the
   existing authoritative Phase 16 integrity pipeline
   (``verify_run_trajectory_execution_record``) before any final state
   is read.
4. The observation bindings are read from the exact verified compiled
   world (``extract_world_catalog``); for every binding in canonical
   ``metric_id`` order the service verifies its scenario/world/manifest/
   state-model/field provenance against the embedded records, locates
   exactly one matching ``RunStateTrajectoryResult`` (missing and
   ambiguous results are rejected), requires exact state-model
   identifier and content-hash agreement, requires the bound
   ``state_field_id`` to exist in ``final_state``, extracts only
   ``final_state[state_field_id]``, validates the raw value against the
   authoritative integer/number kind (booleans and non-finite values
   rejected, no coercion), copies the metric unit from the embedded
   ``ScenarioSpec``, and binds the value to the exact
   result/plan/execution provenance.
5. The complete immutable observation set is built, its deterministic
   content hash is computed over the complete canonical payload
   excluding ``content_hash``, and it is stored **only after every
   validation and integrity check succeeds** - any failure writes
   nothing.

The verifier (``verify_run_metric_observation_set_record``) reloads and
verifies the authoritative run inputs, compiled world, embedded bindings
and ``RunTrajectoryExecution``, then deterministically regenerates the
expected observation set in memory and requires exact equality -
identifier, ordering, values, provenance, and content hash. It never
repairs, normalizes, reorders, overwrites, or silently accepts a partial
artifact. The read service returns a stored set only after that full
verification and never creates an artifact when none exists.

Nothing here evaluates or re-executes transitions, rebuilds or repairs a
``RunTrajectoryExecution``, triggers replay, reads ``initial_state`` as
an observation, chooses transitions or trajectory plans, samples or
consumes uncertainty/seeds, invokes LEGION or NEXUS, loads/imports/
instantiates/executes domain packs, performs network, provider,
filesystem, or database operations, or uses randomness or wall-clock
time (``observed_at`` is the authoritative execution's ``executed_at``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    RunMetricObservationIntegrityError,
    RunNotCompleteError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_run_metric_observation_set,
)
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_inputs import (
    VerifiedRunTrajectoryInputs,
    verify_run_trajectory_inputs,
)
from kalhas.application.strategy_trajectory_service import (
    strategy_candidate_content_hash,
)
from kalhas.application.trajectory_integrity import (
    verify_run_trajectory_execution_record,
)
from kalhas.application.world_integrity import (
    VerifiedWorldCatalog,
    extract_world_catalog,
)
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.run_metric_observation import (
    RunMetricObservationSet,
    RunMetricObservationValue,
    raw_value_matches_numeric_kind,
)
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.trajectory_execution import (
    RunStateTrajectoryResult,
    RunTrajectoryExecution,
)
from kalhas.contracts.v1.world import WorldVersion

_OBSERVATION_SET_ID_PREFIX = "metric-observation-set-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def run_metric_observation_set_identifier(*, run_id: str, runtime_version: str) -> str:
    """Deterministic observation-set identifier from run and runtime identity.

    Hash-derived from the canonical ``(run_id, runtime_version)``
    identity with a readable, distinct prefix; identical inputs always
    yield the identical identifier. Never random, never wall-clock.
    """
    canonical = canonical_json({"run_id": run_id, "runtime_version": runtime_version})
    return f"{_OBSERVATION_SET_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def run_metric_observation_set_content_hash(observation_set: RunMetricObservationSet) -> str:
    """Canonical SHA-256 of the complete observation set, excluding ``content_hash``.

    Deterministic: the canonical serialization sorts keys and strips all
    insignificant whitespace, so equivalent sets always produce the same
    lowercase 64-character digest.
    """
    payload = observation_set.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(run_id: str, reason: str) -> RunMetricObservationIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return RunMetricObservationIntegrityError(run_id, reason)


def _embedded_scenario(world: WorldVersion) -> ScenarioSpec:
    """Parse the scenario embedded in the verified compiled world body.

    The authoritative scenario for extraction is the one embedded in the
    run's exact compiled world - never the live store scenario, whose
    declarations may have changed after compilation. The world verifier
    already validated this snapshot; parsing it again here keeps the
    extraction service self-contained. Any malformed embedded scenario
    raises the safe typed integrity error.
    """
    raw = world.world.get("scenario")
    if not isinstance(raw, dict):
        raise _reject(world.identifier, "embedded scenario is malformed")
    try:
        scenario = ScenarioSpec.model_validate(raw)
    except ValidationError:
        raise _reject(world.identifier, "embedded scenario is malformed") from None
    if scenario.tenant_id != world.tenant_id or scenario.identifier != world.source_scenario_id:
        raise _reject(world.identifier, "embedded scenario provenance mismatch")
    return scenario


def _verify_binding_provenance(
    run_id: str,
    binding: DomainMetricObservationBinding,
    catalog: VerifiedWorldCatalog,
    scenario: ScenarioSpec,
) -> str | None:
    """Verify one binding's provenance against the same verified compiled world.

    The binding must belong to the world's scenario, its metric must be
    declared exactly once by the embedded scenario, its referenced state
    model must exist in the same compiled world with the exact copied
    deterministic identifier, logical state-model id, manifest id, and
    authoritative content hash, the referenced state field must exist in
    that model, and the copied numeric value kind must match the
    authoritative model field. The world verifier already proves all of
    this; the checks are repeated here so the extraction service never
    trusts a binding that was not verified against the embedded records.
    Returns the authoritative metric unit copied from the embedded
    ``ScenarioSpec``.
    """
    if binding.tenant_id != scenario.tenant_id or binding.scenario_id != scenario.identifier:
        raise _reject(run_id, "observation binding provenance mismatch")
    metric_matches = [
        metric for metric in scenario.metrics if metric.identifier == binding.metric_id
    ]
    if len(metric_matches) != 1:
        raise _reject(run_id, "observation binding references an unknown scenario metric")
    state_model = next(
        (
            model
            for model in catalog.state_models
            if model.identifier == binding.state_model_identifier
        ),
        None,
    )
    if state_model is None:
        raise _reject(run_id, "observation binding references an unknown state model")
    if (
        state_model.state_model_id != binding.state_model_id
        or state_model.manifest_id != binding.manifest_id
        or state_model.content_hash != binding.state_model_content_hash
    ):
        raise _reject(run_id, "observation binding state model identity mismatch")
    field = next(
        (field for field in state_model.state_fields if field.identifier == binding.state_field_id),
        None,
    )
    if field is None:
        raise _reject(run_id, "observation binding references an unknown state field")
    if field.value_kind.value != binding.state_field_value_kind:
        raise _reject(run_id, "observation binding state field value kind mismatch")
    return metric_matches[0].unit


def _resolve_trajectory_result(
    run_id: str,
    execution: RunTrajectoryExecution,
    binding: DomainMetricObservationBinding,
) -> RunStateTrajectoryResult:
    """Locate exactly one result of the verified execution for a binding.

    The result is matched by the binding's full authoritative state-model
    provenance: deterministic model identifier, logical state-model id,
    manifest id, and content hash. Zero matches (the bound state model
    has no evaluated trajectory result) and two or more matches (an
    ambiguous execution) are both rejected.
    """
    matches = [
        result
        for result in execution.results
        if result.state_model_identifier == binding.state_model_identifier
        and result.state_model_id == binding.state_model_id
        and result.manifest_id == binding.manifest_id
        and result.state_model_content_hash == binding.state_model_content_hash
    ]
    if len(matches) != 1:
        raise _reject(run_id, "observation binding result is missing or ambiguous")
    return matches[0]


def _extract_raw_value(
    run_id: str,
    *,
    state_field_id: str,
    state_field_value_kind: str,
    final_state: Mapping[str, JsonValue],
) -> int | float:
    """Extract and strictly validate the raw value from the final state.

    Only ``final_state[state_field_id]`` is read; the raw value must
    exactly match the authoritative numeric kind - booleans, non-numeric
    values, and non-finite floats are rejected, and no coercion ever
    happens. The extracted value is preserved exactly: no normalization,
    scaling, transformation, or unit conversion.
    """
    if state_field_id not in final_state:
        raise _reject(run_id, "observation binding final state field is missing")
    raw = final_state[state_field_id]
    if not raw_value_matches_numeric_kind(raw, state_field_value_kind):
        raise _reject(run_id, "observation raw value does not match its numeric kind")
    return cast(int | float, raw)


def _build_observation_value(
    run_id: str,
    binding: DomainMetricObservationBinding,
    execution: RunTrajectoryExecution,
    catalog: VerifiedWorldCatalog,
    scenario: ScenarioSpec,
) -> RunMetricObservationValue:
    """Build one immutable observation value from fully verified records."""
    metric_unit = _verify_binding_provenance(run_id, binding, catalog, scenario)
    result = _resolve_trajectory_result(run_id, execution, binding)
    raw_value = _extract_raw_value(
        run_id,
        state_field_id=binding.state_field_id,
        state_field_value_kind=binding.state_field_value_kind,
        final_state=result.final_state,
    )
    return RunMetricObservationValue(
        metric_id=binding.metric_id,
        metric_unit=metric_unit,
        binding_id=binding.identifier,
        binding_content_hash=binding.content_hash,
        manifest_id=binding.manifest_id,
        state_model_identifier=binding.state_model_identifier,
        state_model_id=binding.state_model_id,
        state_model_content_hash=binding.state_model_content_hash,
        state_field_id=binding.state_field_id,
        state_field_value_kind=binding.state_field_value_kind,
        observation_point=binding.observation_point,
        trajectory_plan_id=result.trajectory_plan_id,
        trajectory_plan_content_hash=result.trajectory_plan_content_hash,
        trajectory_result_content_hash=result.content_hash,
        raw_value=raw_value,
    )


def build_run_metric_observation_set(
    *,
    inputs: VerifiedRunTrajectoryInputs,
    execution: RunTrajectoryExecution,
) -> RunMetricObservationSet:
    """Build the complete deterministic observation set of one verified run.

    Requires the trajectory runtime version and a COMPLETE run; reads
    the observation bindings only from the verified compiled world and
    extracts one raw value per binding from the verified execution's
    exact final state, in canonical ``metric_id`` order. The set
    identifier is deterministic from the run/runtime identity,
    ``observed_at`` is the authoritative execution's ``executed_at``,
    and the content hash covers the complete canonical payload excluding
    ``content_hash`` itself. An empty observation tuple is produced only
    when the verified world embeds no observation bindings.
    """
    verified = inputs.inputs
    run_id = verified.status.run_id
    if verified.run_plan.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            verified.run_plan.runtime_version, operation="metric observation extraction"
        )
    if verified.status.state is not RunState.COMPLETE:
        raise RunNotCompleteError(run_id, verified.status.state.value)

    if execution.run_id != run_id:
        raise _reject(run_id, "trajectory execution run identity mismatch")
    if execution.world_content_hash != verified.world.content_hash:
        raise _reject(run_id, "trajectory execution world content hash mismatch")
    if execution.input_hash != verified.run_plan.input_hash:
        raise _reject(run_id, "trajectory execution input hash mismatch")
    if execution.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise _reject(run_id, "trajectory execution runtime version mismatch")

    catalog = extract_world_catalog(verified.world)
    scenario = _embedded_scenario(verified.world)
    bindings = catalog.domain_metric_observations
    observations = tuple(
        _build_observation_value(run_id, binding, execution, catalog, scenario)
        for binding in bindings
    )
    if not bindings and observations:
        raise _reject(run_id, "unexpected observations without embedded bindings")

    observation_set = RunMetricObservationSet(
        identifier=run_metric_observation_set_identifier(
            run_id=run_id, runtime_version=verified.run_plan.runtime_version
        ),
        tenant_id=verified.run_plan.tenant_id,
        run_id=run_id,
        campaign_id=verified.run_plan.campaign_id,
        run_plan_id=verified.run_plan.identifier,
        scenario_id=verified.world.source_scenario_id,
        world_version_id=verified.world.identifier,
        world_content_hash=verified.world.content_hash,
        strategy_candidate_id=verified.strategy.identifier,
        strategy_content_hash=strategy_candidate_content_hash(verified.strategy),
        scenario_seed_id=verified.seed.identifier,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        input_hash=verified.run_plan.input_hash,
        trajectory_execution_id=execution.identifier,
        trajectory_execution_content_hash=execution.content_hash,
        observations=observations,
        content_hash=_PLACEHOLDER_HASH,
        observed_at=execution.executed_at,
    )
    return observation_set.model_copy(
        update={"content_hash": run_metric_observation_set_content_hash(observation_set)}
    )


def _verified_extraction_inputs(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> VerifiedRunTrajectoryInputs:
    """Verify recorded trajectory inputs and apply the runtime/completeness gates.

    Branches only on the recorded runtime version and run state: legacy
    1.0.0 and unsupported recorded versions raise the typed
    unsupported-version error; runs that are not COMPLETE raise the
    typed invalid-state error. Read-only: nothing is evaluated,
    recorded, or changed.
    """
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    inputs = trajectory_inputs.inputs
    if inputs.run_plan.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            inputs.run_plan.runtime_version, operation="metric observation extraction"
        )
    if inputs.status.state is not RunState.COMPLETE:
        raise RunNotCompleteError(run_id, inputs.status.state.value)
    return trajectory_inputs


def extract_run_metric_observations(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunMetricObservationSet:
    """Explicitly extract, verify, and store the run's immutable observation set.

    The complete pipeline runs before anything is written: recorded
    inputs verified, runtime/completeness gates applied, the stored
    ``RunTrajectoryExecution`` loaded through the store boundary and
    fully verified, every binding extracted against the verified world
    and execution, and the complete set hashed. Only then is the set
    stored; any failure writes nothing. A second extraction of the same
    run is rejected with the typed already-exists error and never
    overwrites the stored artifact.
    """
    trajectory_inputs = _verified_extraction_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
    inputs = trajectory_inputs.inputs
    execution = store.get_run_trajectory_execution(tenant_id, run_id)
    verify_run_trajectory_execution_record(
        execution,
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )
    observation_set = build_run_metric_observation_set(
        inputs=trajectory_inputs, execution=execution
    )
    store.put_run_metric_observation_set(tenant_id, run_id, observation_set)
    return observation_set


def verify_run_metric_observation_set_record(
    observation_set: object,
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
    trajectory_inputs: VerifiedRunTrajectoryInputs | None = None,
) -> None:
    """Fully verify a stored observation set by deterministic regeneration.

    Verifies the authoritative run inputs, compiled world, embedded
    bindings, and ``RunTrajectoryExecution``, regenerates the expected
    observation set in memory, and requires exact equality - identifier,
    ownership, ordering, values, provenance, and content hash. The
    stored artifact is never repaired, normalized, reordered,
    overwritten, or silently accepted; any mismatch raises the safe
    typed integrity error with a generic public message.
    """
    if trajectory_inputs is None:
        trajectory_inputs = _verified_extraction_inputs(
            store=store, tenant_id=tenant_id, run_id=run_id
        )
    inputs = trajectory_inputs.inputs
    execution = store.get_run_trajectory_execution(tenant_id, run_id)
    verify_run_trajectory_execution_record(
        execution,
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )
    if not isinstance(observation_set, RunMetricObservationSet):
        raise _reject(run_id, "stored metric observation set violates its contract")
    # Strict complete contract revalidation: a validator-bypassed or
    # tampered artifact (wrong-typed or non-finite raw values, booleans
    # where integers belong, invalid literals or hash patterns, or
    # non-canonical ordering) is rejected before any field is trusted.
    revalidate_stored_run_metric_observation_set(observation_set, tenant_id, run_id)
    if observation_set.identifier != run_metric_observation_set_identifier(
        run_id=run_id, runtime_version=inputs.run_plan.runtime_version
    ):
        raise _reject(run_id, "metric observation set identifier mismatch")
    if observation_set.tenant_id != tenant_id or observation_set.run_id != run_id:
        raise _reject(run_id, "metric observation set ownership mismatch")
    expected = build_run_metric_observation_set(inputs=trajectory_inputs, execution=execution)
    # Exact canonical equality: the comparison runs over the canonical
    # JSON serializations, never Python ``==``, so a boolean tampered
    # into a numeric raw value (``True == 1`` in Python) or any other
    # value-kind confusion is detected as a real difference.
    if observation_set.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise _reject(run_id, "metric observation set does not match the regenerated artifact")


def get_verified_run_metric_observation_set(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunMetricObservationSet:
    """Load and fully verify a run's stored metric observation set.

    Strictly read-only: the recorded inputs, runtime, and completeness
    gates are verified, the stored set is loaded through the store's
    deep-copy boundary (a missing or foreign set raises the typed
    not-found error and nothing is ever created), the authoritative
    execution is verified, and the stored set is returned only after
    full regeneration-equality verification. A corrupted or tampered set
    (or corrupted authoritative inputs) fails through the typed
    integrity mapping. This never performs extraction, evaluation,
    replay, or any write.
    """
    trajectory_inputs = _verified_extraction_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
    stored = store.get_run_metric_observation_set(tenant_id, run_id)
    verify_run_metric_observation_set_record(
        stored,
        store=store,
        tenant_id=tenant_id,
        run_id=run_id,
        trajectory_inputs=trajectory_inputs,
    )
    return stored
