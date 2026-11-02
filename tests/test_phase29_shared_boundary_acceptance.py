"""H29-S08 shared-boundary acceptance: PAN and the conformance fixture.

Proves that PAN and the synthetic conformance stock-flow fixture traverse
the same generic mechanism boundary - the dispatcher and the Runtime-4
bridge - under one identical Runtime-4 authority chain, with zero
domain-specific kernel edits:

1. same-path success with exact bound identities,
2. one invocation per bridge call and byte-identical re-dispatch,
3. byte-identical deterministic evidence from fresh environments,
4. pack switching changing only pack-owned identity,
5. cross-pack fail-closed behavior,
6. static kernel neutrality,
7. the explicit shared-tenant precondition.

Out of scope: mechanism results are not yet consumed by campaign
outcome or decision-brief evidence; this slice adds no such linkage.
Every fixture is deterministic synthetic data and every expected value is
pinned by hand or computed independently of production logic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.domain_mechanism_runtime import Runtime4DomainMechanismStepExecution
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile
from kalhas.contracts.v1.shared import JsonValue
from kalhas.domain_packs import DomainPack
from kalhas.domain_packs.conformance_stockflow import ConformanceStockFlowV01DomainPack
from kalhas.domain_packs.pan import PanV01DomainPack

from tests.phase29_helpers import OTHER_TENANT, STEP, TENANT, Phase29Environment

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
DISPATCHER_PATH = KALHAS_ROOT / "application" / "domain_mechanism_dispatcher.py"
RUNTIME_PATH = KALHAS_ROOT / "application" / "domain_mechanism_runtime.py"


# ---------------------------------------------------------------------------
# Pack table (the only pack-specific content of this module)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackCase:
    """One pack and its pack-owned state and action-catalogue payloads."""

    name: str
    factory: Callable[[], DomainPack]
    state: dict[str, JsonValue]
    catalogue: dict[str, dict[str, JsonValue]]


PAN_CASE = PackCase(
    name="pan",
    factory=PanV01DomainPack,
    # A complete conservation-closed PAN state.
    state={
        "population_total": 1000,
        "susceptible": 900,
        "exposed": 40,
        "infectious": 30,
        "hospitalized": 20,
        "intensive_care": 5,
        "recovered": 5,
        "deceased": 0,
    },
    catalogue={
        "act-1": {"intervention_intensity_bps": 0},
        "act-2": {"intervention_intensity_bps": 2000},
    },
)

FIXTURE_CASE = PackCase(
    name="fixture",
    factory=ConformanceStockFlowV01DomainPack,
    state={"level": 4},
    catalogue={"act-1": {"release": 0}, "act-2": {"release": 2}},
)

CASES = (PAN_CASE, FIXTURE_CASE)

#: Hand-checked fixture next level per selected action: level 4 + inflow 3
#: - release (0 for act-1, 2 for act-2); capacity 10 is never reached.
FIXTURE_NEXT_LEVEL = {"act-1": 7, "act-2": 5}

PAN_ID = "kalhas-pan"
FIXTURE_ID = "kalhas-conformance-stockflow"


class CountingPack:
    """A conforming DomainPack wrapper counting ``step`` delegations."""

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def __init__(self, delegate: DomainPack) -> None:
        self._delegate = delegate
        self.calls = 0
        self.manifest = delegate.manifest
        self.release_profile = delegate.release_profile
        self.mechanism_protocol_version = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        return self._delegate.step(request)


def _execute(
    env: Phase29Environment, case: PackCase, pack: DomainPack | None = None
) -> Runtime4DomainMechanismStepExecution:
    return env.call(
        pack=case.factory() if pack is None else pack,
        draft=env.draft(state_payload=case.state, action_payloads=case.catalogue),
    )


def _evidence(execution: Runtime4DomainMechanismStepExecution) -> tuple[object, ...]:
    """The complete byte-comparable evidence of one bridge execution."""
    return (
        execution.runtime_version,
        execution.run_id,
        execution.adaptive_policy_identifier,
        execution.policy_id,
        execution.adaptive_policy_content_hash,
        execution.decision_event.model_dump_json(),
        execution.selected_action_id,
        execution.action_payload_catalogue_hash,
        execution.request.model_dump_json(),
        execution.result.model_dump_json(),
    )


@pytest.fixture(scope="module")
def env() -> Phase29Environment:
    """One shared authority chain: only the pack differs between runs."""
    return Phase29Environment()


@pytest.fixture(scope="module")
def executions(env: Phase29Environment) -> dict[str, Runtime4DomainMechanismStepExecution]:
    return {case.name: _execute(env, case) for case in CASES}


# ---------------------------------------------------------------------------
# 1. Same-path success
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_same_path_success_binds_the_shared_authority_chain(
    env: Phase29Environment, case: PackCase
) -> None:
    pack = case.factory()
    execution = _execute(env, case, pack)
    request = execution.request
    assert execution.runtime_version == "4.0.0"
    assert execution.run_id == env.run_id
    assert execution.adaptive_policy_identifier == env.policy.identifier
    assert execution.policy_id == env.policy.policy_id
    assert execution.adaptive_policy_content_hash == env.policy.content_hash
    assert execution.decision_event == env.decision_event
    assert execution.selected_action_id == env.decision_event.selected_action_id
    assert execution.selected_action_id in case.catalogue
    assert request.tenant_id == TENANT
    assert request.run_id == env.run_id
    assert request.step_index == STEP
    assert request.world_version_id == env.world.identifier
    assert request.world_content_hash == env.world.content_hash
    assert request.seed_id == env.seed.identifier
    assert request.realization_id == env.realization.identifier
    assert request.realization_content_hash == env.realization.content_hash
    assert request.mechanism_spec_id == pack.release_profile.mechanism_spec.identifier
    assert request.mechanism_spec_content_hash == pack.release_profile.mechanism_spec.content_hash
    assert request.release_profile_id == pack.release_profile.identifier
    assert request.release_profile_content_hash == pack.release_profile.content_hash
    result = execution.result
    assert result.request_id == request.identifier
    assert result.request_content_hash == request.content_hash
    assert result.run_id == env.run_id
    assert result.world_version_id == env.world.identifier
    assert result.seed_id == env.seed.identifier
    assert result.mechanism_spec_content_hash == pack.release_profile.mechanism_spec.content_hash
    assert result.release_profile_content_hash == pack.release_profile.content_hash
    assert request.state_payload == case.state
    assert request.action_payload == case.catalogue[execution.selected_action_id]


def test_fixture_next_state_is_hand_checked_for_the_selected_action(
    executions: dict[str, Runtime4DomainMechanismStepExecution],
) -> None:
    execution = executions["fixture"]
    selected = execution.selected_action_id
    assert selected in FIXTURE_NEXT_LEVEL
    assert execution.result.next_state_payload == {"level": FIXTURE_NEXT_LEVEL[selected]}
    assert execution.request.action_payload == FIXTURE_CASE.catalogue[selected]


def test_pan_next_state_conserves_population(
    executions: dict[str, Runtime4DomainMechanismStepExecution],
) -> None:
    next_state = executions["pan"].result.next_state_payload
    total = next_state["population_total"]
    parts = sum(
        value
        for key, value in next_state.items()
        if key != "population_total" and isinstance(value, int)
    )
    assert total == 1000 == parts


# ---------------------------------------------------------------------------
# 2. One invocation, one result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_one_bridge_call_makes_exactly_one_pack_step_call(
    env: Phase29Environment, case: PackCase
) -> None:
    counting = CountingPack(case.factory())
    execution = _execute(env, case, counting)
    assert counting.calls == 1
    assert execution.result.request_id == execution.request.identifier
    # Re-dispatching the bridge's verified request through the generic
    # dispatcher gives a byte-identical result.
    redispatched = dispatch_domain_mechanism_step(case.factory(), execution.request)
    assert redispatched.model_dump_json() == execution.result.model_dump_json()


# ---------------------------------------------------------------------------
# 3. Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_fresh_environments_and_packs_produce_byte_identical_evidence(case: PackCase) -> None:
    first = _execute(Phase29Environment(), case)
    second = _execute(Phase29Environment(), case)
    assert _evidence(first) == _evidence(second)


# ---------------------------------------------------------------------------
# 4. Pack switching changes only pack-owned identity
# ---------------------------------------------------------------------------


def test_pack_switching_changes_only_pack_owned_identity(
    executions: dict[str, Runtime4DomainMechanismStepExecution],
) -> None:
    pan = executions["pan"]
    fixture = executions["fixture"]
    # Identical across both packs: the Runtime-4 side of the boundary.
    assert pan.run_id == fixture.run_id
    assert pan.runtime_version == fixture.runtime_version
    assert pan.adaptive_policy_identifier == fixture.adaptive_policy_identifier
    assert pan.adaptive_policy_content_hash == fixture.adaptive_policy_content_hash
    assert pan.policy_id == fixture.policy_id
    assert pan.decision_event == fixture.decision_event
    assert pan.selected_action_id == fixture.selected_action_id
    for field in (
        "tenant_id",
        "run_id",
        "step_index",
        "world_version_id",
        "world_content_hash",
        "seed_id",
        "seed_content_hash",
        "realization_id",
        "realization_content_hash",
        "scenario_id",
        "scenario_content_hash",
    ):
        assert getattr(pan.request, field) == getattr(fixture.request, field), field
    # Different: every pack-owned identity.
    for field in (
        "mechanism_spec_id",
        "mechanism_spec_content_hash",
        "release_profile_id",
        "release_profile_content_hash",
        "state_schema_id",
        "action_schema_id",
        "configuration_schema_id",
        "state_payload",
        "action_payload",
        "state_hash",
        "action_hash",
        "configuration_hash",
        "identifier",
        "content_hash",
    ):
        assert getattr(pan.request, field) != getattr(fixture.request, field), field
    assert pan.action_payload_catalogue_hash != fixture.action_payload_catalogue_hash
    assert pan.result.identifier != fixture.result.identifier
    assert pan.result.content_hash != fixture.result.content_hash
    assert pan.result.next_state_hash != fixture.result.next_state_hash


# ---------------------------------------------------------------------------
# 5. Cross-pack fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("owner", "foreign"),
    [(FIXTURE_CASE, PAN_CASE), (PAN_CASE, FIXTURE_CASE)],
    ids=["pan-payloads-into-fixture", "fixture-payloads-into-pan"],
)
def test_foreign_payloads_are_rejected_without_a_partial_result(
    env: Phase29Environment, owner: PackCase, foreign: PackCase
) -> None:
    counting = CountingPack(owner.factory())
    with pytest.raises(DomainMechanismDispatchError):
        env.call(
            pack=counting,
            draft=env.draft(state_payload=foreign.state, action_payloads=foreign.catalogue),
        )
    # The single dispatch was attempted once and never retried.
    assert counting.calls == 1


@pytest.mark.parametrize(
    ("builder", "target"),
    [(PAN_CASE, FIXTURE_CASE), (FIXTURE_CASE, PAN_CASE)],
    ids=["pan-request-to-fixture", "fixture-request-to-pan"],
)
def test_request_built_for_one_pack_is_rejected_by_the_other(
    env: Phase29Environment, builder: PackCase, target: PackCase
) -> None:
    request = _execute(env, builder).request
    counting = CountingPack(target.factory())
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(counting, request)
    assert counting.calls == 0


class _HybridPack:
    """One pack's manifest combined with the other pack's release profile."""

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def __init__(self, manifest_owner: DomainPack, profile_owner: DomainPack) -> None:
        self.calls = 0
        self.manifest = manifest_owner.manifest
        self.release_profile = profile_owner.release_profile
        self.mechanism_protocol_version = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        raise AssertionError("a hybrid pack must never reach step")


@pytest.mark.parametrize(
    ("manifest_case", "profile_case"),
    [(PAN_CASE, FIXTURE_CASE), (FIXTURE_CASE, PAN_CASE)],
    ids=["pan-manifest-fixture-profile", "fixture-manifest-pan-profile"],
)
def test_hybrid_pack_is_rejected_with_zero_step_calls(
    env: Phase29Environment, manifest_case: PackCase, profile_case: PackCase
) -> None:
    hybrid = _HybridPack(manifest_case.factory(), profile_case.factory())
    with pytest.raises(DomainMechanismDispatchError):
        env.call(
            pack=hybrid,
            draft=env.draft(
                state_payload=profile_case.state, action_payloads=profile_case.catalogue
            ),
        )
    assert hybrid.calls == 0
    # The generic dispatcher rejects the hybrid on its own as well.
    request = _execute(env, profile_case).request
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(hybrid, request)
    assert hybrid.calls == 0


# ---------------------------------------------------------------------------
# 6. Kernel neutrality (static)
# ---------------------------------------------------------------------------

_CONCRETE_PACK_REFERENCES = (
    PAN_ID,
    FIXTURE_ID,
    "PanV01DomainPack",
    "ConformanceStockFlowV01DomainPack",
    "domain_packs.pan",
    "domain_packs.conformance_stockflow",
    "domain_packs/pan",
    "domain_packs/conformance_stockflow",
)


def test_no_kernel_module_references_either_concrete_pack() -> None:
    offenders: list[str] = []
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        relative = path.relative_to(KALHAS_ROOT).as_posix()
        if relative.startswith("domain_packs/"):
            continue
        source = path.read_text(encoding="utf-8")
        for reference in _CONCRETE_PACK_REFERENCES:
            if reference in source:
                offenders.append(f"{relative}: {reference}")
    assert offenders == []


def test_dispatcher_and_runtime_sources_contain_no_pack_specific_branch() -> None:
    pack_tokens = re.compile(
        r"(\bpan\b|stockflow|stock-flow|conformance[_-]stock|compartment|spill|shortfall)",
        re.IGNORECASE,
    )
    for path in (DISPATCHER_PATH, RUNTIME_PATH):
        source = path.read_text(encoding="utf-8")
        assert not pack_tokens.search(source), path.name
        for token in ("pack_id ==", "pack_id in", "mechanism_id ==", "pack_id !="):
            assert token not in source, (path.name, token)


# ---------------------------------------------------------------------------
# 7. Tenant precondition is explicit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_both_packs_share_the_environment_tenant(env: Phase29Environment, case: PackCase) -> None:
    pack = case.factory()
    assert pack.manifest.tenant_id == TENANT
    assert pack.release_profile.tenant_id == TENANT
    assert env.world.tenant_id == TENANT


class _ForeignTenantPack:
    """A pack whose manifest and release profile carry a foreign tenant."""

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def __init__(self, delegate: DomainPack) -> None:
        self.calls = 0
        self.manifest = delegate.manifest.model_copy(update={"tenant_id": OTHER_TENANT})
        self.release_profile = delegate.release_profile.model_copy(
            update={"tenant_id": OTHER_TENANT}
        )
        self.mechanism_protocol_version = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        self.calls += 1
        raise AssertionError("pack.step must never run for a foreign tenant")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_cross_tenant_variant_is_rejected_with_zero_step_calls(
    env: Phase29Environment, case: PackCase
) -> None:
    foreign = _ForeignTenantPack(case.factory())
    with pytest.raises(DomainMechanismDispatchError) as excinfo:
        _execute(env, case, foreign)
    assert excinfo.value.reason == "pack_tenant_agreement"
    assert foreign.calls == 0
