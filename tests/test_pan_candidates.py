"""Candidate authority and national-scale trajectory checks on synthetic inputs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.mechanism_trajectory import run_mechanism_trajectory
from kalhas.contracts.v1.domain_mechanism import DomainMechanismStepRequest
from kalhas.domain_packs.pan import PanV01DomainPack
from kalhas.domain_packs.pan.candidates import PanCandidateDomainPack, build_pan_candidate_pack
from kalhas.domain_packs.pan.mechanism import (
    PanDomainPackError,
    compute_transition,
    validate_configuration_payload,
)
from kalhas.domain_packs.pan.pack import _self_covering_hash

from tests.test_benchmark_task_engine import chain
from tests.test_mechanism_trajectory import make_binding
from tests.test_pan_domain_pack import _request_payload

CONFIG = {
    "transmission_bps": 3000,
    "exposed_progression_bps": 2000,
    "hospital_admission_bps": 100,
    "infectious_recovery_bps": 1500,
    "icu_admission_bps": 500,
    "hospital_recovery_bps": 1000,
    "icu_mortality_bps": 300,
    "icu_recovery_bps": 700,
    "hospital_capacity": 100000000,
    "icu_capacity": 100000000,
    "compliance_bps": 0,
}
STATE = {
    "population_total": 83456045,
    "exposed": 1500,
    "infectious": 3000,
    "hospitalized": 1000,
    "intensive_care": 200,
    "recovered": 8000000,
    "deceased": 0,
    "susceptible": 75450345,
}
ACTION = {"intervention_intensity_bps": 0}
DECLARED = datetime(2026, 11, 6, tzinfo=UTC)


def candidate(**changes: Any) -> PanCandidateDomainPack:
    args: dict[str, Any] = {
        "tenant_id": "kalhas-synthetic",
        "binding_id": "example",
        "binding_version": "1.0.0",
        "candidate_index": 1,
        "configuration": CONFIG,
        "declared_at": DECLARED,
    }
    args.update(changes)
    return build_pan_candidate_pack(**args)


def request(pack: Any) -> DomainMechanismStepRequest:
    payload = _request_payload(
        pack.mechanism_spec,
        pack.release_profile.identifier,
        pack.release_profile.content_hash,
        state_payload=STATE if isinstance(pack, PanCandidateDomainPack) else None,
        action_payload=ACTION,
    )
    return DomainMechanismStepRequest.model_validate(payload)


def test_national_scale_trajectory_golden() -> None:
    pack = candidate()
    *_, protocol = chain()
    steps = run_mechanism_trajectory(
        pack,
        binding=make_binding(),
        protocol=protocol,
        run_id="candidate-golden",
        last_observed_day=date(2020, 1, 5),
        initial_state=STATE,
        action=ACTION,
        step_count=100,
    )
    assert steps[-1].day == date(2020, 4, 14)
    assert steps[-1].stocks["hospitalized"] == 20168
    config = validate_configuration_payload(CONFIG, CONFIG)
    state = dict(STATE)
    for step in steps:
        transition = compute_transition(state, 0, config)
        assert step.stocks == transition.next_state
        assert step.flows["hospital_admissions"] == transition.counts[2]
        assert step.flows["icu_admissions"] == transition.counts[4]
        state = transition.next_state


def test_candidate_identities_hashes_and_unchanged_base() -> None:
    before = PanV01DomainPack().release_profile.content_hash
    first, second = candidate(), candidate()
    assert first.manifest == second.manifest
    assert first.mechanism_spec == second.mechanism_spec
    assert first.release_profile == second.release_profile
    assert first.manifest.identifier == "manifest-kalhas-pan-candidate-example-1.0.0-1"
    assert first.mechanism_spec.identifier == "mechanism-spec-kalhas-pan-candidate-example-1.0.0-1"
    assert (
        first.release_profile.identifier == "release-profile-kalhas-pan-candidate-example-1.0.0-1"
    )
    assert first.release_profile.pack_version == "0.2.1"
    assert candidate(candidate_index=2).release_profile.pack_version == "0.2.2"
    assert (
        first.mechanism_spec.implementation_hash
        == PanV01DomainPack().mechanism_spec.implementation_hash
    )
    assert manifest_content_hash(first.manifest) == first.manifest.content_hash
    assert _self_covering_hash(first.mechanism_spec) == first.mechanism_spec.content_hash
    assert _self_covering_hash(first.release_profile) == first.release_profile.content_hash
    assert first.mechanism_spec.configuration_hash == sha256_hex(canonical_json(CONFIG))
    assert (
        candidate(configuration={**CONFIG, "transmission_bps": 3001}).release_profile.content_hash
        != first.release_profile.content_hash
    )
    assert (
        PanV01DomainPack().release_profile.content_hash
        == before
        != first.release_profile.content_hash
    )
    for authority in (first.manifest, first.mechanism_spec, first.release_profile):
        assert "synthetic_only" not in authority.metadata
        assert "no_real_data" not in authority.metadata
        assert authority.metadata["authoring_candidate"] is True
    assert "synthetic" not in first.release_profile.scope.validity_envelope.lower()
    assert "synthetic" not in str(first.release_profile.intended_uses).lower()
    assert (
        first.release_profile.prohibited_uses == PanV01DomainPack().release_profile.prohibited_uses
    )


def test_request_identity_is_not_interchangeable() -> None:
    frozen, pack = PanV01DomainPack(), candidate()
    pack.step(request(pack))
    frozen.step(request(frozen))
    with pytest.raises(PanDomainPackError):
        frozen.step(request(pack))
    with pytest.raises(PanDomainPackError):
        pack.step(request(frozen))


@pytest.mark.parametrize("authority", ["manifest", "mechanism_spec", "release_profile"])
def test_mutated_and_replaced_authorities_fail_closed(authority: str) -> None:
    pack = candidate()
    req = request(pack)
    getattr(pack, authority).metadata["changed"] = True
    with pytest.raises(PanDomainPackError):
        pack.step(req)
    pack = candidate()
    setattr(pack, authority, object())
    with pytest.raises(PanDomainPackError):
        pack.step(req)


def test_only_one_public_operation() -> None:
    assert [
        name
        for name in dir(PanCandidateDomainPack)
        if not name.startswith("_") and callable(getattr(PanCandidateDomainPack, name))
    ] == ["step"]


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate_index": 0},
        {"candidate_index": True},
        {"candidate_index": -1},
        {"candidate_index": "1"},
        {"binding_id": "Bad"},
        {"binding_id": "x--y"},
        {"binding_version": "1.0"},
        {"binding_version": "v1.0.0"},
        {"configuration": {}},
        {"configuration": {**CONFIG, "transmission_bps": True}},
        {"configuration": {**CONFIG, "transmission_bps": 10001}},
        {"configuration": {**CONFIG, "hospital_capacity": -1}},
    ],
)
def test_invalid_candidates(changes: dict[str, Any]) -> None:
    with pytest.raises(PanDomainPackError):
        candidate(**changes)
