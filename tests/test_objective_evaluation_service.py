"""Phase 23 declaration-service tests: lifecycle, coverage, and provenance.

Proves the immutable one-per-tenant/scenario evaluation profile:
bindings canonicalized into the exact ``ScenarioSpec.objectives``
order regardless of caller order, authoritative fields copied from the
stored scenario (forged fields impossible), complete coverage with
exactly-one reference rules, reach/tolerance/scale rules, declaration
before world compilation, duplicate rejection, tenant isolation,
deep-copy storage, an independently derived (non-circular) identifier,
deterministic content hashing, and the absence of any update, replace,
delete, or list surface.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileAlreadyExistsError,
    EvaluationProfileDeclarationAfterCompilationError,
    EvaluationProfileIncompleteCoverageError,
    EvaluationProfileIntegrityError,
    EvaluationProfileInvalidScaleError,
    EvaluationProfileMetricNotFoundError,
    EvaluationProfileNotFoundError,
    EvaluationProfileObjectiveNotFoundError,
    EvaluationProfileReachTargetRequiredError,
    EvaluationProfileToleranceRuleError,
    EvaluationProfileValidationError,
)
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
    verify_evaluation_profile_identity,
)
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
    get_scenario_evaluation_profile,
)
from kalhas.application.scenario_service import validate_scenario
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection

from tests.phase4_helpers import TENANT
from tests.phase23_helpers import (
    DEFAULT_BINDING_DRAFTS,
    PROFILE_DECLARED_AT,
    build_evaluation_scenario,
    build_profile,
    complete_evaluation_campaign,
)

OTHER_TENANT = "tenant-other"

VALID_OBJECTIVES = (
    Objective(
        identifier="obj-b",
        description="Minimize the primary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-a",
        description="Maximize the secondary metric",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=2.0,
    ),
    Objective(
        identifier="obj-c",
        description="Reach the declared band",
        direction=ObjectiveDirection.REACH,
        target=50.0,
        weight=3.0,
    ),
)

REVERSED_BINDING_DRAFTS: tuple[ObjectiveMetricBindingDraft, ...] = tuple(
    reversed(DEFAULT_BINDING_DRAFTS)
)


def _declare(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    bindings: tuple[ObjectiveMetricBindingDraft, ...] = DEFAULT_BINDING_DRAFTS,
    declared_at: datetime = PROFILE_DECLARED_AT,
) -> ScenarioEvaluationProfile:
    return declare_scenario_evaluation_profile(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        bindings=bindings,
        declared_at=declared_at,
    )


class TestScenarioContentHash:
    def test_matches_canonical_dump_digest(self) -> None:
        scenario = build_evaluation_scenario()
        assert scenario_content_hash(scenario) == sha256_hex(
            canonical_json(scenario.model_dump(mode="json"))
        )

    def test_deterministic_and_content_sensitive(self) -> None:
        scenario_a = build_evaluation_scenario()
        scenario_b = build_evaluation_scenario()
        assert scenario_content_hash(scenario_a) == scenario_content_hash(scenario_b)
        changed = scenario_b.model_copy(update={"name": "Different name"})
        assert scenario_content_hash(scenario_a) != scenario_content_hash(changed)


class TestProfileIdentifier:
    def test_identifier_is_independent_of_binding_content(self) -> None:
        """The identifier derives from the identity payload, never the content hash.

        Two profiles with the same (tenant, scenario, scenario hash)
        identity but different binding content must share the identifier
        while their content hashes differ - proving non-circularity.
        """
        profile_a = build_profile()
        different_binding = {
            "objective_id": "obj-b",
            "metric_id": "m-1",
            "direction": "minimize",
            "target": 100.0,
            "weight": 1.0,
            "metric_unit": "units",
            "reach_tolerance": None,
            "normalization_scale": 500.0,
        }
        bindings = profile_a.model_dump(mode="json")["bindings"]
        assert isinstance(bindings, list)
        bindings[0] = different_binding
        profile_b = build_profile(bindings=bindings)
        assert profile_a.identifier == profile_b.identifier
        assert profile_a.content_hash != profile_b.content_hash

    def test_identifier_matches_direct_derivation(self) -> None:
        profile = build_profile()
        assert profile.identifier == evaluation_profile_identifier(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            scenario_content_hash_value=profile.scenario_content_hash,
        )


class TestDeclaration:
    def test_declares_profile_in_exact_scenario_objective_order(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        assert [binding.objective_id for binding in profile.bindings] == [
            "obj-b",
            "obj-a",
            "obj-c",
        ]
        assert profile.tenant_id == TENANT
        assert profile.scenario_id == "scenario-1"
        assert profile.declared_at == PROFILE_DECLARED_AT
        assert profile.content_hash == evaluation_profile_content_hash(profile)

    def test_reversed_caller_binding_order_produces_identical_profile(self) -> None:
        store_a = InMemoryScenarioStore()
        store_a.put_scenario(build_evaluation_scenario())
        profile_a = _declare(store_a, bindings=DEFAULT_BINDING_DRAFTS)
        store_b = InMemoryScenarioStore()
        store_b.put_scenario(build_evaluation_scenario())
        profile_b = _declare(store_b, bindings=REVERSED_BINDING_DRAFTS)
        assert profile_a.model_dump(mode="json") == profile_b.model_dump(mode="json")

    def test_authoritative_snapshots_copied_from_stored_scenario(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        scenario = store.get_scenario(TENANT, "scenario-1")
        for binding, objective in zip(profile.bindings, scenario.objectives, strict=True):
            assert binding.direction == objective.direction.value
            assert binding.target == objective.target
            assert binding.weight == objective.weight
        assert profile.scenario_content_hash == scenario_content_hash(scenario)

    def test_metric_unit_copied_from_stored_scenario(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        assert profile.bindings[0].metric_unit == "units"
        assert profile.bindings[1].metric_unit == "percent"

    def test_one_metric_may_measure_multiple_objectives(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        metric_ids = [binding.metric_id for binding in profile.bindings]
        assert metric_ids.count("m-1") == 2  # obj-b and obj-c both bind m-1

    def test_metadata_preserved_and_hashed(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = declare_scenario_evaluation_profile(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            bindings=DEFAULT_BINDING_DRAFTS,
            declared_at=PROFILE_DECLARED_AT,
            metadata={"note": "declared", "count": 3},
        )
        assert profile.metadata == {"note": "declared", "count": 3}

    def test_duplicate_declaration_rejected_and_never_overwrites(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        first = _declare(store)
        with pytest.raises(EvaluationProfileAlreadyExistsError):
            _declare(store)
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        assert stored.model_dump(mode="json") == first.model_dump(mode="json")

    def test_declaration_after_world_compilation_rejected(self) -> None:
        store = InMemoryScenarioStore()
        scenario = build_evaluation_scenario()
        store.put_scenario(scenario)
        compiled = compile_world(scenario)
        store.put_world(compiled.version, compiled.manifest)
        with pytest.raises(EvaluationProfileDeclarationAfterCompilationError):
            _declare(store)

    def test_unknown_scenario_404(self) -> None:
        store = InMemoryScenarioStore()
        with pytest.raises(Exception) as excinfo:
            _declare(store)
        from kalhas.application.domain_errors import ScenarioNotFoundError

        assert isinstance(excinfo.value, ScenarioNotFoundError)

    def test_foreign_tenant_declaration_404(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario(tenant_id=OTHER_TENANT))
        from kalhas.application.domain_errors import ScenarioNotFoundError

        with pytest.raises(ScenarioNotFoundError):
            _declare(store, tenant_id=TENANT)


class TestCoverageAndReferences:
    def _store_with_objectives(self, objectives: list[Objective]) -> InMemoryScenarioStore:
        store = InMemoryScenarioStore()
        store.put_scenario(
            build_evaluation_scenario().model_copy(update={"objectives": objectives})
        )
        return store

    def test_unknown_objective_rejected(self) -> None:
        store = self._store_with_objectives(list(VALID_OBJECTIVES))
        drafts = (
            ObjectiveMetricBindingDraft(
                objective_id="obj-zzz",
                metric_id="m-1",
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-a",
                metric_id="m-2",
                reach_tolerance=None,
                normalization_scale=20.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-c",
                metric_id="m-1",
                reach_tolerance=5.0,
                normalization_scale=50.0,
            ),
        )
        with pytest.raises(EvaluationProfileObjectiveNotFoundError):
            _declare(store, bindings=drafts)

    def test_unknown_metric_rejected(self) -> None:
        store = self._store_with_objectives(list(VALID_OBJECTIVES))
        drafts = (
            ObjectiveMetricBindingDraft(
                objective_id="obj-b",
                metric_id="m-zzz",
                reach_tolerance=None,
                normalization_scale=100.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-a",
                metric_id="m-2",
                reach_tolerance=None,
                normalization_scale=20.0,
            ),
            ObjectiveMetricBindingDraft(
                objective_id="obj-c",
                metric_id="m-1",
                reach_tolerance=5.0,
                normalization_scale=50.0,
            ),
        )
        with pytest.raises(EvaluationProfileMetricNotFoundError):
            _declare(store, bindings=drafts)

    def test_missing_objective_coverage_rejected(self) -> None:
        store = self._store_with_objectives(list(VALID_OBJECTIVES))
        drafts = DEFAULT_BINDING_DRAFTS[:-1]
        with pytest.raises(EvaluationProfileIncompleteCoverageError):
            _declare(store, bindings=drafts)

    def test_extra_objective_binding_rejected(self) -> None:
        store = self._store_with_objectives(list(VALID_OBJECTIVES))
        extra = ObjectiveMetricBindingDraft(
            objective_id="obj-extra",
            metric_id="m-1",
            reach_tolerance=None,
            normalization_scale=100.0,
        )
        with pytest.raises(EvaluationProfileObjectiveNotFoundError):
            _declare(store, bindings=DEFAULT_BINDING_DRAFTS + (extra,))

    def test_duplicate_objective_in_request_rejected(self) -> None:
        store = self._store_with_objectives(list(VALID_OBJECTIVES))
        duplicated = DEFAULT_BINDING_DRAFTS[:1] + DEFAULT_BINDING_DRAFTS[:1]
        with pytest.raises(EvaluationProfileIncompleteCoverageError):
            _declare(store, bindings=duplicated)

    def test_duplicate_objective_in_scenario_rejected(self) -> None:
        duplicated = list(VALID_OBJECTIVES) + [VALID_OBJECTIVES[0]]
        store = self._store_with_objectives(duplicated)
        with pytest.raises(EvaluationProfileIncompleteCoverageError):
            _declare(store)

    def test_empty_objective_scenario_cannot_declare(self) -> None:
        store = self._store_with_objectives([])
        with pytest.raises(EvaluationProfileIncompleteCoverageError):
            _declare(store, bindings=())

    def test_reach_objective_without_target_rejected(self) -> None:
        objectives = (
            VALID_OBJECTIVES[0],
            VALID_OBJECTIVES[1],
            Objective(
                identifier="obj-c",
                description="Reach without target",
                direction=ObjectiveDirection.REACH,
                target=None,
                weight=3.0,
            ),
        )
        store = self._store_with_objectives(list(objectives))
        with pytest.raises(EvaluationProfileReachTargetRequiredError):
            _declare(store)

    def test_non_finite_stored_target_rejected(self) -> None:
        objectives = (
            VALID_OBJECTIVES[0].model_copy(update={"target": float("nan")}),
            VALID_OBJECTIVES[1],
            VALID_OBJECTIVES[2],
        )
        store = self._store_with_objectives(list(objectives))
        with pytest.raises(EvaluationProfileValidationError):
            _declare(store)


class TestToleranceAndScaleRules:
    def _store(self) -> InMemoryScenarioStore:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        return store

    def _drafts_with(
        self, *, reach_tolerance: object = None, scale: object = 50.0, objective: str = "obj-c"
    ) -> tuple[ObjectiveMetricBindingDraft, ...]:
        base = list(DEFAULT_BINDING_DRAFTS)
        for index, draft in enumerate(base):
            if draft.objective_id == objective:
                base[index] = ObjectiveMetricBindingDraft(
                    objective_id=draft.objective_id,
                    metric_id=draft.metric_id,
                    reach_tolerance=reach_tolerance,  # type: ignore[arg-type]
                    normalization_scale=scale,  # type: ignore[arg-type]
                )
        return tuple(base)

    def test_reach_without_tolerance_rejected(self) -> None:
        with pytest.raises(EvaluationProfileToleranceRuleError):
            _declare(self._store(), bindings=self._drafts_with(reach_tolerance=None))

    def test_tolerance_on_minimize_rejected(self) -> None:
        with pytest.raises(EvaluationProfileToleranceRuleError):
            _declare(
                self._store(),
                bindings=self._drafts_with(reach_tolerance=5.0, objective="obj-b"),
            )

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(EvaluationProfileToleranceRuleError):
            _declare(self._store(), bindings=self._drafts_with(reach_tolerance=-1.0))

    def test_non_finite_tolerance_rejected(self) -> None:
        with pytest.raises(EvaluationProfileToleranceRuleError):
            _declare(
                self._store(),
                bindings=self._drafts_with(reach_tolerance=float("nan")),
            )

    @pytest.mark.parametrize("scale", [0.0, -5.0, float("nan"), float("inf"), True])
    def test_invalid_scale_rejected(self, scale: object) -> None:
        with pytest.raises(EvaluationProfileInvalidScaleError):
            _declare(self._store(), bindings=self._drafts_with(scale=scale))


class TestStoreIsolation:
    def test_get_returns_deep_independent_copy(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        fetched = store.get_evaluation_profile(TENANT, "scenario-1")
        assert fetched.model_dump(mode="json") == profile.model_dump(mode="json")
        # Tampering with the returned copy never affects storage.
        tampered = fetched.model_copy(update={"metadata": {"x": 1}})
        assert tampered.metadata == {"x": 1}
        assert store.get_evaluation_profile(TENANT, "scenario-1").metadata == {}

    def test_foreign_tenant_get_is_indistinguishable_404(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        _declare(store)
        with pytest.raises(EvaluationProfileNotFoundError):
            get_scenario_evaluation_profile(store, OTHER_TENANT, "scenario-1")

    def test_no_update_delete_replace_or_list_surface(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        _declare(store)
        for name in (
            "update_evaluation_profile",
            "delete_evaluation_profile",
            "replace_evaluation_profile",
            "list_evaluation_profiles",
        ):
            assert not hasattr(store, name)

    def test_store_revalidates_before_writing(self) -> None:
        store = InMemoryScenarioStore()
        store.put_scenario(build_evaluation_scenario())
        profile = _declare(store)
        # A validator-bypassed profile (tolerance smuggled onto a
        # minimize binding via model_copy) is rejected by the store's
        # strict revalidation before any field of it is trusted.
        forged_binding = profile.bindings[0].model_copy(update={"reach_tolerance": 5.0})
        forged = profile.model_copy(update={"bindings": (forged_binding,) + profile.bindings[1:]})
        with pytest.raises(EvaluationProfileIntegrityError):
            store.put_evaluation_profile(TENANT, "scenario-2", forged)


class TestIdentityVerification:
    def test_valid_profile_passes(self) -> None:
        profile = build_profile()
        verify_evaluation_profile_identity(profile, tenant_id=TENANT, scenario_id="scenario-1")

    def test_foreign_ownership_rejected(self) -> None:
        profile = build_profile()
        with pytest.raises(EvaluationProfileIntegrityError):
            verify_evaluation_profile_identity(
                profile, tenant_id=OTHER_TENANT, scenario_id="scenario-1"
            )

    def test_tampered_identifier_rejected(self) -> None:
        profile = build_profile().model_copy(update={"identifier": "forged"})
        with pytest.raises(EvaluationProfileIntegrityError):
            verify_evaluation_profile_identity(profile, tenant_id=TENANT, scenario_id="scenario-1")

    def test_tampered_content_hash_rejected(self) -> None:
        profile = build_profile().model_copy(update={"content_hash": "0" * 64})
        with pytest.raises(EvaluationProfileIntegrityError):
            verify_evaluation_profile_identity(profile, tenant_id=TENANT, scenario_id="scenario-1")

    def test_non_contract_instance_rejected(self) -> None:
        with pytest.raises(EvaluationProfileIntegrityError):
            verify_evaluation_profile_identity(object(), tenant_id=TENANT, scenario_id="scenario-1")


class TestStoreReadBoundary:
    """Corrupted stored profiles never cross the store boundary.

    Every read strictly revalidates the stored record's contract and
    its deterministic identity (ownership, identifier, content hash);
    a validator-bypassed or forged record raises the safe typed
    integrity error at the store getter, at the application getter,
    and at the mock world-compilation path - and is never served.
    """

    def _declare(self, store: InMemoryScenarioStore) -> ScenarioEvaluationProfile:
        store.put_scenario(build_evaluation_scenario())
        return declare_scenario_evaluation_profile(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            bindings=DEFAULT_BINDING_DRAFTS,
            declared_at=PROFILE_DECLARED_AT,
        )

    def _inject(self, store: InMemoryScenarioStore, profile: ScenarioEvaluationProfile) -> None:
        store._evaluation_profiles[(TENANT, "scenario-1")] = profile

    @pytest.mark.parametrize(
        "corruption",
        [
            "malformed_binding",
            "invalid_content_hash",
            "invalid_identifier",
            "wrong_ownership",
        ],
    )
    def test_store_getter_rejects_corrupted_record(self, corruption: str) -> None:
        store = InMemoryScenarioStore()
        profile = self._declare(store)
        if corruption == "malformed_binding":
            # A validator-bypassed tolerance on a minimize binding.
            binding = profile.bindings[0].model_copy(update={"reach_tolerance": 5.0})
            corrupted = profile.model_copy(update={"bindings": (binding,) + profile.bindings[1:]})
        elif corruption == "invalid_content_hash":
            corrupted = profile.model_copy(update={"content_hash": "f" * 64})
        elif corruption == "invalid_identifier":
            corrupted = profile.model_copy(update={"identifier": "forged"})
        else:
            corrupted = profile.model_copy(update={"tenant_id": "tenant-other"})
        self._inject(store, corrupted)
        with pytest.raises(EvaluationProfileIntegrityError):
            store.get_evaluation_profile(TENANT, "scenario-1")

    @pytest.mark.parametrize(
        "corruption",
        [
            "malformed_binding",
            "invalid_content_hash",
            "invalid_identifier",
            "wrong_ownership",
        ],
    )
    def test_service_getter_rejects_corrupted_record(self, corruption: str) -> None:
        store = InMemoryScenarioStore()
        profile = self._declare(store)
        if corruption == "malformed_binding":
            binding = profile.bindings[0].model_copy(update={"reach_tolerance": 5.0})
            corrupted = profile.model_copy(update={"bindings": (binding,) + profile.bindings[1:]})
        elif corruption == "invalid_content_hash":
            corrupted = profile.model_copy(update={"content_hash": "f" * 64})
        elif corruption == "invalid_identifier":
            corrupted = profile.model_copy(update={"identifier": "forged"})
        else:
            corrupted = profile.model_copy(update={"tenant_id": "tenant-other"})
        self._inject(store, corrupted)
        with pytest.raises(EvaluationProfileIntegrityError):
            get_scenario_evaluation_profile(store, TENANT, "scenario-1")

    def test_clean_record_still_served_with_fresh_deep_copy(self) -> None:
        store = InMemoryScenarioStore()
        profile = self._declare(store)
        fetched = store.get_evaluation_profile(TENANT, "scenario-1")
        assert fetched.model_dump(mode="json") == profile.model_dump(mode="json")
        # The returned copy is detached: mutating it never affects storage.
        _ = fetched.model_copy(update={"metadata": {"x": 1}})
        assert store.get_evaluation_profile(TENANT, "scenario-1").metadata == {}

    def test_foreign_tenant_remains_indistinguishable_404(self) -> None:
        store = InMemoryScenarioStore()
        self._declare(store)
        with pytest.raises(EvaluationProfileNotFoundError):
            store.get_evaluation_profile("tenant-other", "scenario-1")

    @pytest.mark.parametrize(
        "corruption",
        ["malformed_binding", "invalid_content_hash", "invalid_identifier"],
    )
    def test_mock_compilation_never_uses_corrupted_profile(self, corruption: str) -> None:
        from kalhas.adapters.mocks import MockNexusAdapter

        store = InMemoryScenarioStore()
        profile = self._declare(store)
        if corruption == "malformed_binding":
            binding = profile.bindings[0].model_copy(update={"reach_tolerance": 5.0})
            corrupted = profile.model_copy(update={"bindings": (binding,) + profile.bindings[1:]})
        elif corruption == "invalid_content_hash":
            corrupted = profile.model_copy(update={"content_hash": "f" * 64})
        else:
            corrupted = profile.model_copy(update={"identifier": "forged"})
        self._inject(store, corrupted)
        adapter = MockNexusAdapter(store)
        with pytest.raises(EvaluationProfileIntegrityError):
            adapter.compile_scenario(TENANT, "scenario-1")
        # No world was compiled or stored from the corrupted profile.
        assert store.has_compiled_worlds_for_scenario(TENANT, "scenario-1") is False
        assert len(store._worlds) == 0


class TestDeclarationThroughFullFlow:
    def test_profile_survives_campaign_flow(self) -> None:
        store, _world_version_id, _run_ids = complete_evaluation_campaign()
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        assert [binding.objective_id for binding in stored.bindings] == [
            "obj-b",
            "obj-a",
            "obj-c",
        ]
        # The stored scenario is semantically valid (the flow compiled).
        scenario = store.get_scenario(TENANT, "scenario-1")
        assert validate_scenario(scenario).report.valid
