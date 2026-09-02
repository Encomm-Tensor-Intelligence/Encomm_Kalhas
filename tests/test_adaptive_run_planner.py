"""Runtime-4 adaptive run-planner tests (H28-S08A).

Adversarial coverage of the pure deterministic adaptive run planner:

- the exact ``4.0.0`` runtime literal (and the module's own ``__all__``),
  deterministic repeated output, and the additive gate that rejects every
  other runtime value - including the untouched historical literals -
  before any authority is inspected;
- exactly ``K`` plans for ``K`` seeds in the caller's exact seed order
  (never ``K x S`` for any strategy dimension), with duplicate-seed and
  reverse-order preservation;
- one shared realization authority per seed: plan binding follows the
  seed's own realization content hash regardless of policy changes, and
  no policy attribute can influence which realization a seed receives;
- the exact initial-action strategy anchor: resolved uniquely from the
  bound action catalog, byte-equal across seeds, distinct when the
  initial action's bound strategy differs, and failing closed on a
  missing initial action;
- canonical-hash sensitivity of :func:`adaptive_run_input_hash` to the
  world content hash, the complete policy authority, the seed
  authority, the realization content hash, and the runtime version;
- deterministic identifier and provenance: equality with the untouched
  historical ``run_plan_identifier`` construction and exact
  tenant/campaign/world/seed/runtime/anchor/``created_at`` provenance;
- missing or foreign realization authority failing closed with the
  typed domain error and zero partial output;
- input immutability under planning;
- the absence of any RNG, clock, store, network, provider, callback,
  ``eval``/``exec``/``import``-path, or mutation surface in the module;
- byte identity of the historical
  :mod:`kalhas.application.run_planner` functions and constants, which
  are outside this slice's allowlist and must remain untouched.

No mocks, monkeypatch, skip, xfail, noqa, type-ignore, weakened
assertions, invented outputs, real company or personal data, or live
effects are used anywhere in this module.
"""

from __future__ import annotations

import ast
import copy
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalhas.application import adaptive_run_planner as planner_module
from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
)
from kalhas.application.domain_errors import (
    KalhasDomainError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
    plan_runs,
    run_identifier,
    run_input_hash,
    run_plan_identifier,
    run_realization_input_hash,
)
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world_realization import WorldRealization

H64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
H64_B = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

PLANNER_PATH = Path(planner_module.__file__).resolve()
RUN_PLANNER_PATH = PLANNER_PATH.parent / "run_planner.py"


# --------------------------------------------------------------------------- #
# Frozen fixtures. Every helper constructs the exact contract type through
# its public validator; every override is explicit in the test that needs it.
# --------------------------------------------------------------------------- #


def _leaf(condition_id: str, threshold: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "comparison",
        "condition_id": condition_id,
        "observation_id": "obs-1",
        "observed_value_kind": "integer",
        "unit": None,
        "operator": "gte",
        "threshold": threshold,
        "missing_behavior": "false",
    }
    payload.update(overrides)
    return payload


def _enter_tree(threshold: int = 5) -> dict[str, object]:
    return {
        "kind": "all",
        "condition_id": "c-enter",
        "children": [
            _leaf("c-e1", threshold),
            _leaf("c-e2", 100, operator="lt"),
        ],
    }


def _retain_tree(threshold: int = 4) -> dict[str, object]:
    return {
        "kind": "all",
        "condition_id": "c-retain",
        "children": [
            _leaf("c-r1", threshold),
            _leaf("c-r2", 90, operator="lt"),
        ],
    }


def _rule_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule_id": "rule-1",
        "priority": 0,
        "target_action_id": "act-b",
        "enter_condition": _enter_tree(),
        "retain_condition": _retain_tree(),
        "per_rule_switch_budget": 3,
    }
    payload.update(overrides)
    return payload


def _binding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "observation_id": "obs-1",
        "runtime_observation_declaration_id": "runtime-observation-1",
        "runtime_observation_declaration_content_hash": H64,
        "observed_value_kind": "integer",
        "unit": None,
        "missing_behavior": "false",
    }
    payload.update(overrides)
    return payload


def _plan_binding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": H64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _action_payload(
    action_id: str, strategy_candidate_id: str, **overrides: object
) -> dict[
    str,
    object,
]:
    payload: dict[str, object] = {
        "action_id": action_id,
        "strategy_candidate_id": strategy_candidate_id,
        "strategy_content_hash": H64,
        "trajectory_plan_bindings": [_plan_binding_payload()],
    }
    payload.update(overrides)
    return payload


def _policy_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identifier": "adaptive-policy-bound-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "runtime_version": "4.0.0",
        "policy_id": "policy-1",
        "policy_version": "1.0.0",
        "observation_bindings": [_binding_payload()],
        "actions": [
            _action_payload("act-a", "strategy-alpha"),
            _action_payload("act-b", "strategy-beta"),
        ],
        "initial_action_id": "act-a",
        "fallback_action_id": "act-b",
        "rules": [_rule_payload()],
        "minimum_dwell_steps": 2,
        "cooldown_steps": 1,
        "global_switch_budget": 10,
        "content_hash": H64,
        "bound_at": NOW,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _seed(identifier: str, seed_value: str, **overrides: object) -> ScenarioSeed:
    payload: dict[str, object] = {
        "identifier": identifier,
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "algorithm": "deterministic",
        "seed_value": seed_value,
        "derived_from": None,
        "metadata": {},
    }
    payload.update(overrides)
    return ScenarioSeed.model_validate(payload)


def _realization_payload(
    identifier: str,
    scenario_seed_id: str,
    seed_content_hash_value: str,
    content_hash: str = H64,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": identifier,
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "scenario_seed_id": scenario_seed_id,
        "seed_content_hash": seed_content_hash_value,
        "uncertainty_model_id": "uncertainty-model-1",
        "uncertainty_model_content_hash": H64,
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "sampled_values": [],
        "realized_initial_state_overrides": [],
        "content_hash": content_hash,
        "realized_at": "2026-01-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _policy(**overrides: object) -> AdaptivePolicy:
    return AdaptivePolicy.model_validate(_policy_payload(**overrides))


def _realization(seed: ScenarioSeed, **overrides: Any) -> WorldRealization:
    from kalhas.application.world_uncertainty_identity import seed_content_hash

    payload = _realization_payload(
        f"world-realization-{seed.identifier}",
        seed.identifier,
        seed_content_hash(seed),
    )
    payload.update(overrides)
    return WorldRealization.model_validate(payload)


def _seeded_setup(
    *,
    seed_values: tuple[str, ...] = ("a", "b", "c"),
    policy_overrides: dict[str, object] | None = None,
) -> tuple[AdaptivePolicy, tuple[ScenarioSeed, ...], dict[str, WorldRealization]]:
    policy = _policy(**(policy_overrides or {}))
    seeds = tuple(_seed(f"seed-{index}", value) for index, value in enumerate(seed_values))
    realizations = {seed.identifier: _realization(seed) for seed in seeds}
    return policy, seeds, realizations


def _plan(
    seeds: tuple[ScenarioSeed, ...] | None = None,
    realizations: dict[str, WorldRealization] | None = None,
    policy: AdaptivePolicy | None = None,
    **overrides: Any,
) -> tuple[RunPlan, ...]:
    setup_policy, setup_seeds, _ = _seeded_setup()
    use_seeds = seeds if seeds is not None else setup_seeds
    use_realizations = (
        realizations
        if realizations is not None
        else {seed.identifier: _realization(seed) for seed in use_seeds}
    )
    kwargs: dict[str, Any] = {
        "campaign_id": "campaign-1",
        "tenant_id": "tenant-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "policy": policy if policy is not None else setup_policy,
        "seeds": use_seeds,
        "created_at": NOW,
        "realizations": use_realizations,
    }
    kwargs.update(overrides)
    return planner_module.plan_adaptive_runs(**kwargs)


# --------------------------------------------------------------------------- #
# J.1 - Exact runtime literal and deterministic repeated output.
# --------------------------------------------------------------------------- #


class TestRuntimeLiteralAndDeterminism:
    def test_exact_runtime_literal(self) -> None:
        assert planner_module.ADAPTIVE_RUNTIME_VERSION == "4.0.0"

    def test_literal_is_typed_as_exactly_4_0_0(self) -> None:
        source = PLANNER_PATH.read_text(encoding="utf-8")
        assert 'ADAPTIVE_RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"' in source

    def test_module_exports_exactly_the_public_surface(self) -> None:
        assert sorted(planner_module.__all__) == [
            "ADAPTIVE_RUNTIME_VERSION",
            "adaptive_run_input_hash",
            "plan_adaptive_runs",
        ]

    def test_repeated_planning_is_byte_identical(self) -> None:
        first = _plan()
        second = _plan()
        assert first == second
        assert [plan.model_dump_json() for plan in first] == [
            plan.model_dump_json() for plan in second
        ]

    def test_non_4_0_0_runtime_values_fail_closed_before_any_output(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        for runtime in ("", "1.0.0", "2.0.0", "3.0.0", "4.0.1", "5.0.0", "4", "v4.0.0"):
            with pytest.raises(UnsupportedRuntimeVersionError) as excinfo:
                planner_module.plan_adaptive_runs(
                    campaign_id="campaign-1",
                    tenant_id="tenant-1",
                    world_version_id="world-v1",
                    world_content_hash=H64,
                    policy=policy,
                    seeds=seeds,
                    created_at=NOW,
                    realizations=realizations,
                    runtime_version=runtime,
                )
            assert isinstance(excinfo.value, KalhasDomainError)
            assert excinfo.value.runtime_version == runtime

    def test_rejected_runtime_authority_is_never_inspected(self) -> None:
        # A tampered authority that would fail verification must still
        # surface the runtime gate first: the gate precedes every
        # authority inspection and no plan can be produced.
        tampered = _policy(world_content_hash=H64_B)
        with pytest.raises(UnsupportedRuntimeVersionError):
            _plan(policy=tampered, runtime_version="2.0.0")


# --------------------------------------------------------------------------- #
# J.2 - Exactly K plans for K seeds, in seed order, never K x S.
# --------------------------------------------------------------------------- #


class TestOnePlanPerSeed:
    def test_three_seeds_yield_exactly_three_plans(self) -> None:
        plans = _plan()
        assert len(plans) == 3

    def test_plan_count_equals_seed_count_for_ensembles(self) -> None:
        for count in (1, 5, 12):
            seeds = tuple(_seed(f"seed-{i}", f"value-{i}") for i in range(count))
            realizations = {seed.identifier: _realization(seed) for seed in seeds}
            plans = _plan(seeds=seeds, realizations=realizations)
            assert len(plans) == count

    def test_seed_order_is_preserved_exactly(self) -> None:
        seeds = tuple(
            _seed(f"seed-{i}", f"value-{i}", derived_from=f"origin-{i}") for i in (2, 0, 4, 1)
        )
        realizations = {seed.identifier: _realization(seed) for seed in seeds}
        plans = _plan(seeds=seeds, realizations=realizations)
        assert [plan.scenario_seed_id for plan in plans] == [seed.identifier for seed in seeds]

    def test_reverse_order_changes_plan_order_not_identity(self) -> None:
        seeds = tuple(_seed(f"seed-{i}", f"value-{i}") for i in range(3))
        realizations = {seed.identifier: _realization(seed) for seed in seeds}
        forward = _plan(seeds=seeds, realizations=realizations)
        reverse = _plan(seeds=tuple(reversed(seeds)), realizations=realizations)
        assert [plan.scenario_seed_id for plan in forward] == ["seed-0", "seed-1", "seed-2"]
        assert [plan.scenario_seed_id for plan in reverse] == ["seed-2", "seed-1", "seed-0"]
        assert {plan.identifier for plan in forward} == {plan.identifier for plan in reverse}

    def test_plans_are_never_per_strategy(self) -> None:
        # The policy binds two actions across two distinct strategies;
        # three seeds must still yield exactly three plans, never 3 x 2.
        policy, seeds, realizations = _seeded_setup()
        plans = _plan(seeds=seeds, realizations=realizations, policy=policy)
        assert len(policy.actions) == 2
        assert len(seeds) == 3
        assert len(plans) == 3

    def test_duplicate_seeds_follow_caller_order(self) -> None:
        # No silent deduplication or reordering: the caller's exact
        # ordered ensemble is the multiplicity authority.
        seeds = (_seed("seed-0", "value-0"), _seed("seed-0", "value-0"))
        realizations = {seed.identifier: _realization(seed) for seed in seeds}
        plans = _plan(seeds=seeds, realizations=realizations)
        assert len(plans) == 2
        assert [plan.scenario_seed_id for plan in plans] == ["seed-0", "seed-0"]


# --------------------------------------------------------------------------- #
# J.3 - One shared realization authority per seed; no policy-dependent
# realization derivation.
# --------------------------------------------------------------------------- #


class TestSharedRealizationAuthority:
    def test_plans_bind_their_seed_realization_content_hash(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        distinct_hashes = {realizations[seed.identifier].content_hash for seed in seeds}
        assert len(distinct_hashes) >= 1
        plans = _plan(seeds=seeds, realizations=realizations, policy=policy)
        for plan, seed in zip(plans, seeds, strict=True):
            expected = planner_module.adaptive_run_input_hash(
                runtime_version=planner_module.ADAPTIVE_RUNTIME_VERSION,
                world_content_hash=H64,
                policy=policy,
                seed=seed,
                world_realization_content_hash=realizations[seed.identifier].content_hash,
            )
            assert plan.input_hash == expected

    def test_policy_change_cannot_change_realization_binding(self) -> None:
        seed = _seed("seed-0", "value-0")
        realization = _realization(seed, content_hash=H64_B)
        policy_a = _policy()
        policy_b = _policy(
            content_hash=H64_B,
            bound_at=datetime(2027, 6, 1, tzinfo=UTC),
            global_switch_budget=99,
        )
        for policy in (policy_a, policy_b):
            plans = _plan(seeds=(seed,), realizations={seed.identifier: realization}, policy=policy)
            assert (
                planner_module.adaptive_run_input_hash(
                    runtime_version=planner_module.ADAPTIVE_RUNTIME_VERSION,
                    world_content_hash=H64,
                    policy=policy,
                    seed=seed,
                    world_realization_content_hash=H64_B,
                )
                == plans[0].input_hash
            )

    def test_realization_disagreement_fails_identically_for_every_policy(self) -> None:
        # A foreign realization is rejected independently of the bound
        # policy: which realization a seed receives is never derived
        # from any policy attribute.
        seed = _seed("seed-0", "value-0")
        foreign = _realization(
            seed,
            identifier="world-realization-foreign",
            world_version_id="other-world",
        )
        for policy in (_policy(), _policy(global_switch_budget=42)):
            with pytest.raises(AdaptivePolicyBindingValidationError):
                _plan(
                    seeds=(seed,),
                    realizations={seed.identifier: foreign},
                    policy=policy,
                )


# --------------------------------------------------------------------------- #
# J.4 - Exact initial-action strategy anchor.
# --------------------------------------------------------------------------- #


class TestInitialActionStrategyAnchor:
    def test_anchor_is_initial_action_strategy(self) -> None:
        plans = _plan()
        assert {plan.strategy_candidate_id for plan in plans} == {"strategy-alpha"}

    def test_anchor_is_byte_identical_across_all_plans(self) -> None:
        seeds = tuple(_seed(f"seed-{i}", f"value-{i}") for i in range(4))
        realizations = {seed.identifier: _realization(seed) for seed in seeds}
        plans = _plan(seeds=seeds, realizations=realizations)
        anchors = {plan.strategy_candidate_id for plan in plans}
        assert anchors == {"strategy-alpha"}

    def test_anchor_follows_the_policy_initial_action(self) -> None:
        fallback_policy = _policy(
            initial_action_id="act-b",
            fallback_action_id="act-a",
        )
        plans = _plan(policy=fallback_policy)
        assert plans[0].strategy_candidate_id == "strategy-beta"

    def test_missing_initial_action_fails_closed(self) -> None:
        # A validator-bypassed policy whose initial action is absent
        # from the catalog must fail with the typed domain error; the
        # planner never silently substitutes another action. The policy
        # is constructed without validation from JSON-derived plain
        # payloads so the bypass is exact and complete.
        payload = _policy_payload(initial_action_id="act-x")
        payload["observation_bindings"] = [
            dict(binding) for binding in payload["observation_bindings"]
        ]
        payload["actions"] = [dict(action) for action in payload["actions"]]
        payload["actions"][1]["trajectory_plan_bindings"] = [
            dict(binding) for binding in payload["actions"][1]["trajectory_plan_bindings"]
        ]
        bypassed = AdaptivePolicy.model_construct(**payload)
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(policy=bypassed)

    def test_runtime_4_execution_remains_policy_driven_by_documentation(self) -> None:
        source = PLANNER_PATH.read_text(encoding="utf-8")
        assert "policy-driven" in source
        assert "static-strategy" in source


# --------------------------------------------------------------------------- #
# J.5 - Canonical hash sensitivity to every authority.
# --------------------------------------------------------------------------- #


class TestInputHashSensitivity:
    def test_repeated_hash_is_deterministic(self) -> None:
        policy, seeds, realizations = _seeded_setup(seed_values=("solo",))
        args: dict[str, Any] = {
            "runtime_version": "4.0.0",
            "world_content_hash": H64,
            "policy": policy,
            "seed": seeds[0],
            "world_realization_content_hash": realizations["seed-0"].content_hash,
        }
        assert planner_module.adaptive_run_input_hash(**args) == (
            planner_module.adaptive_run_input_hash(**args)
        )

    def test_world_content_hash_sensitivity(self) -> None:
        policy, seeds, realizations = _seeded_setup(seed_values=("solo",))
        base = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        other = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64_B,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        assert base != other

    def test_policy_authority_sensitivity(self) -> None:
        _, seeds, realizations = _seeded_setup(seed_values=("solo",))
        baseline = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=_policy(),
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        changed = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=_policy(global_switch_budget=7, content_hash=H64_B),
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        assert baseline != changed

    def test_seed_authority_sensitivity(self) -> None:
        policy, seeds, realizations = _seeded_setup(seed_values=("x",))
        # Same seed identifier, different seed authority (seed_value):
        # only the complete seed authority changes between the two digs.
        other_seed = _seed("seed-0", "value-y")
        base = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        changed = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=other_seed,
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        assert base != changed

    def test_realization_content_hash_sensitivity(self) -> None:
        policy, seeds, realizations = _seeded_setup(seed_values=("solo",))
        base = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        changed = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=H64_B,
        )
        assert base != changed

    def test_runtime_version_sensitivity(self) -> None:
        policy, seeds, realizations = _seeded_setup(seed_values=("solo",))
        base = planner_module.adaptive_run_input_hash(
            runtime_version="4.0.0",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        changed = planner_module.adaptive_run_input_hash(
            runtime_version="9.9.9",
            world_content_hash=H64,
            policy=policy,
            seed=seeds[0],
            world_realization_content_hash=realizations["seed-0"].content_hash,
        )
        assert base != changed


# --------------------------------------------------------------------------- #
# J.6 - Deterministic identifier and provenance.
# --------------------------------------------------------------------------- #


class TestIdentifierAndProvenance:
    def test_identifier_reuses_the_historical_collision_safe_construction(self) -> None:
        plans = _plan()
        for plan in plans:
            assert plan.identifier == run_plan_identifier(
                campaign_id="campaign-1",
                world_version_id="world-v1",
                strategy_candidate_id="strategy-alpha",
                scenario_seed_id=plan.scenario_seed_id,
                runtime_version="4.0.0",
            )

    def test_identifiers_are_unique_per_seed(self) -> None:
        plans = _plan()
        assert len({plan.identifier for plan in plans}) == len(plans)

    def test_exact_provenance_fields(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        plans = _plan(seeds=seeds, realizations=realizations, policy=policy)
        for plan, seed in zip(plans, seeds, strict=True):
            assert isinstance(plan, RunPlan)
            assert plan.tenant_id == "tenant-1"
            assert plan.campaign_id == "campaign-1"
            assert plan.world_version_id == "world-v1"
            assert plan.scenario_seed_id == seed.identifier
            assert plan.runtime_version == "4.0.0"
            assert plan.planned_state == "planned"
            assert plan.created_at == NOW

    def test_created_at_follows_the_caller_supplied_timestamp(self) -> None:
        later = datetime(2030, 6, 15, 8, 30, tzinfo=UTC)
        policy, seeds, realizations = _seeded_setup()
        plans = planner_module.plan_adaptive_runs(
            campaign_id="campaign-1",
            tenant_id="tenant-1",
            world_version_id="world-v1",
            world_content_hash=H64,
            policy=policy,
            seeds=seeds,
            created_at=later,
            realizations=realizations,
        )
        assert all(plan.created_at == later for plan in plans)


# --------------------------------------------------------------------------- #
# J.7 - Missing realization fails without partial output.
# --------------------------------------------------------------------------- #


class TestMissingRealizationFailsClosed:
    def test_missing_realization_raises_typed_domain_error(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        del realizations[seeds[2].identifier]
        with pytest.raises(AdaptivePolicyBindingValidationError) as excinfo:
            _plan(seeds=seeds, realizations=realizations, policy=policy)
        assert isinstance(excinfo.value, KalhasDomainError)

    def test_missing_realization_on_the_last_seed_produces_zero_plans(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        del realizations[seeds[-1].identifier]
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(seeds=seeds, realizations=realizations, policy=policy)

    def test_missing_realization_never_yields_partial_output(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        seeds = seeds[:-1] + (_seed("seed-late", "value-late"),)
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(seeds=seeds, realizations=realizations, policy=policy)

    def test_empty_realization_mapping_fails_for_every_nonempty_ensemble(self) -> None:
        policy, seeds, _ = _seeded_setup()
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(seeds=seeds, realizations={}, policy=policy)

    def test_foreign_tenant_realization_fails_closed(self) -> None:
        seed = _seed("seed-0", "value-0")
        foreign = _realization(seed, tenant_id="tenant-2")
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(seeds=(seed,), realizations={seed.identifier: foreign})

    def test_seed_content_hash_disagreement_fails_closed(self) -> None:
        seed = _seed("seed-0", "value-0")
        tampered = _realization(seed, seed_content_hash=H64_B)
        with pytest.raises(AdaptivePolicyBindingValidationError):
            _plan(seeds=(seed,), realizations={seed.identifier: tampered})


# --------------------------------------------------------------------------- #
# J.8 - Input immutability.
# --------------------------------------------------------------------------- #


class TestInputImmutability:
    def test_planning_does_not_mutate_any_input(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        policy_before = policy.model_dump(mode="json")
        seeds_before = [seed.model_dump(mode="json") for seed in seeds]
        realizations_before = {
            key: value.model_dump(mode="json") for key, value in realizations.items()
        }
        _plan(seeds=seeds, realizations=realizations, policy=policy)
        assert policy.model_dump(mode="json") == policy_before
        assert [seed.model_dump(mode="json") for seed in seeds] == seeds_before
        assert {
            key: value.model_dump(mode="json") for key, value in realizations.items()
        } == realizations_before

    def test_deep_copied_inputs_produce_identical_plans(self) -> None:
        policy, seeds, realizations = _seeded_setup()
        direct = _plan(seeds=seeds, realizations=realizations, policy=policy)
        copied = _plan(
            seeds=copy.deepcopy(seeds),
            realizations=copy.deepcopy(realizations),
            policy=copy.deepcopy(policy),
        )
        assert [plan.model_dump_json() for plan in direct] == [
            plan.model_dump_json() for plan in copied
        ]

    def test_planning_inputs_are_frozen_records(self) -> None:
        from pydantic import ValidationError

        policy, seeds, realizations = _seeded_setup()
        _plan(seeds=seeds, realizations=realizations, policy=policy)
        with pytest.raises(ValidationError):
            policy.tenant_id = "tampered"
        with pytest.raises(ValidationError):
            realizations[seeds[0].identifier].content_hash = H64_B


# --------------------------------------------------------------------------- #
# J.9 - No RNG / clock / store / network / provider / callback /
# eval / exec / import-path surface.
# --------------------------------------------------------------------------- #


class TestForbiddenSurfaces:
    def test_module_imports_carry_no_forbidden_surface(self) -> None:
        tree = ast.parse(PLANNER_PATH.read_text(encoding="utf-8"))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names.add(node.module or "")
        forbidden_modules = (
            "random",
            "time",
            "datetime",
            "uuid",
            "secrets",
            "socket",
            "urllib",
            "http",
            "requests",
            "subprocess",
            "os",
            "pathlib",
            "tempfile",
            "pickle",
            "asyncio",
            "threading",
        )
        assert not imported_names & set(forbidden_modules)

    def test_module_has_no_forbidden_call_or_name_surface(self) -> None:
        tree = ast.parse(PLANNER_PATH.read_text(encoding="utf-8"))
        forbidden_calls = {
            "eval",
            "exec",
            "compile",
            "__import__",
            "open",
            "input",
            "globals",
            "locals",
            "vars",
            "getattr",
            "setattr",
            "delattr",
            "random",
            "randint",
            "random_sample",
            "uniform",
            "time",
            "time_ns",
            "datetime_now",
            "now",
            "utcnow",
            "uuid4",
            "system",
            "popen",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                assert name not in forbidden_calls, f"forbidden call: {name}"

    def test_module_has_no_store_parameter_or_attribute_access(self) -> None:
        tree = ast.parse(PLANNER_PATH.read_text(encoding="utf-8"))
        source = PLANNER_PATH.read_text(encoding="utf-8")
        assert "store" not in {
            arg.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for arg in node.args.args
        }
        assert "InMemoryScenarioStore" not in source
        assert "requests" not in source
        assert "urllib" not in source
        assert "socket" not in source

    def test_module_functions_are_free_of_defaulted_effectful_arguments(self) -> None:
        for name in ("adaptive_run_input_hash", "plan_adaptive_runs"):
            function = getattr(planner_module, name)
            assert callable(function)
            assert not any(
                default is not None and not isinstance(default, (str, bool, int, float))
                for default in function.__defaults__ or ()
            )


# --------------------------------------------------------------------------- #
# J.10 - Historical run_planner surface remains untouched (byte identity).
# --------------------------------------------------------------------------- #


class TestHistoricalRunPlannerUntouched:
    def test_historical_module_file_is_byte_identical_to_head(self) -> None:
        import subprocess

        blob = subprocess.run(
            ["git", "show", "HEAD:kalhas/application/run_planner.py"],
            cwd=RUN_PLANNER_PATH.parents[1],
            capture_output=True,
            check=True,
        ).stdout
        assert RUN_PLANNER_PATH.read_bytes() == blob

    def test_historical_runtime_constants_are_unchanged(self) -> None:
        assert LEGACY_STRUCTURAL_RUNTIME_VERSION == "1.0.0"
        assert TRAJECTORY_RUNTIME_VERSION == "2.0.0"
        assert REALIZATION_TRAJECTORY_RUNTIME_VERSION == "3.0.0"

    def test_historical_function_objects_exist_unchanged(self) -> None:
        assert run_identifier.__module__ == "kalhas.application.run_planner"
        assert run_input_hash.__module__ == "kalhas.application.run_planner"
        assert run_realization_input_hash.__module__ == "kalhas.application.run_planner"
        assert plan_runs.__module__ == "kalhas.application.run_planner"
        assert plan_realization_runs.__module__ == "kalhas.application.run_planner"
        assert run_plan_identifier.__module__ == "kalhas.application.run_planner"

    def test_historical_plan_construction_still_yields_strategy_major_matrices(self) -> None:
        # The untouched runtime-2/3 historical planners keep their exact
        # per-(strategy, seed) multiplicity and identical identifiers;
        # this slice adds, never changes.
        seeds = tuple(_seed(f"seed-{i}", f"value-{i}") for i in range(2))
        strategies = (
            StrategyCandidate.model_validate(
                {
                    "identifier": "strategy-alpha",
                    "tenant_id": "tenant-1",
                    "schema_version": "1.0.0",
                    "strategy_version": "1.0.0",
                    "policy": {
                        "summary": "hold course",
                        "rules": [
                            {
                                "identifier": "hold",
                                "statement": "maintain the baseline setting",
                                "parameters": {},
                            }
                        ],
                    },
                }
            ),
            StrategyCandidate.model_validate(
                {
                    "identifier": "strategy-beta",
                    "tenant_id": "tenant-1",
                    "schema_version": "1.0.0",
                    "strategy_version": "1.0.0",
                    "policy": {
                        "summary": "diversify",
                        "rules": [
                            {
                                "identifier": "diversify",
                                "statement": "split effort across options",
                                "parameters": {},
                            }
                        ],
                    },
                }
            ),
        )
        historical_plans = plan_runs(
            campaign_id="campaign-1",
            tenant_id="tenant-1",
            world_version_id="world-v1",
            world_content_hash=H64,
            strategies=strategies,
            seeds=seeds,
            created_at=NOW,
        )
        assert len(historical_plans) == len(strategies) * len(seeds)
        assert [plan.strategy_candidate_id for plan in historical_plans] == [
            "strategy-alpha",
            "strategy-alpha",
            "strategy-beta",
            "strategy-beta",
        ]
        # The historical plans keep their exact runtime-2 identifiers,
        # built from the same untouched collision-safe construction.
        for plan in historical_plans:
            assert plan.identifier == run_plan_identifier(
                campaign_id="campaign-1",
                world_version_id="world-v1",
                strategy_candidate_id=plan.strategy_candidate_id,
                scenario_seed_id=plan.scenario_seed_id,
                runtime_version=plan.runtime_version,
            )
            assert plan.runtime_version == "2.0.0"
        # The runtime-4 planner over the same seeds yields exactly one
        # plan per seed - the seed ensemble is its only multiplicity.
        adaptive_plans = _plan(seeds=seeds)
        assert len(adaptive_plans) == len(seeds)

    def test_planner_source_does_not_touch_runtime_1_2_3_literals(self) -> None:
        source = PLANNER_PATH.read_text(encoding="utf-8")
        assert '"1.0.0"' not in source
        assert '"2.0.0"' not in source
        assert '"3.0.0"' not in source


# --------------------------------------------------------------------------- #
# Static invariants that must hold for the whole module source.
# --------------------------------------------------------------------------- #


def test_planner_module_has_no_docstring_placeholder_or_todo_markers() -> None:
    source = PLANNER_PATH.read_text(encoding="utf-8")
    for marker in ("TODO", "FIXME", "placeholder", "not implemented"):
        assert marker not in source


def test_planner_inputs_are_keyword_only() -> None:
    signature = inspect.signature(planner_module.plan_adaptive_runs)
    assert all(
        parameter.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.VAR_KEYWORD)
        for parameter in signature.parameters.values()
    )
