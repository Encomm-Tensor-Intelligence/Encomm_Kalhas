"""Mock NEXUS boundary for the standalone local flow.

Implements the scenario submission, validation, clarification, and
compilation surface using only KALHAS public contracts and application
services. No real NEXUS integration: this is a local, in-memory,
standalone proof.
"""

from __future__ import annotations

from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.scenario_service import ScenarioValidationResult, validate_scenario
from kalhas.application.world_compiler import CompiledWorld, compile_world
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.scenario import ClarificationQuestion, ScenarioSpec
from kalhas.contracts.v1.world import WorldManifest, WorldVersion


class MockNexusAdapter:
    """Local deterministic mock of the NEXUS-facing standalone flow."""

    def __init__(self, store: InMemoryScenarioStore) -> None:
        self._store = store

    def submit_scenario(self, scenario: ScenarioSpec) -> None:
        """Register a scenario (rejects duplicates for the tenant)."""
        self._store.put_scenario(scenario)

    def validate_scenario(self, tenant_id: str, scenario_id: str) -> ScenarioValidationResult:
        """Validate a stored scenario; returns report plus clarification questions."""
        scenario = self._store.get_scenario(tenant_id, scenario_id)
        return validate_scenario(scenario)

    def clarification_questions(
        self, tenant_id: str, scenario_id: str
    ) -> list[ClarificationQuestion]:
        """Surface only the structured clarification questions for a scenario."""
        return self.validate_scenario(tenant_id, scenario_id).questions

    def compile_scenario(self, tenant_id: str, scenario_id: str) -> CompiledWorld:
        """Compile a stored scenario into an immutable world and store the result.

        The scenario's registered domain-pack bindings, declared
        capability inputs, declared domain state models, declared domain
        state transitions, and declared domain metric observation
        bindings are loaded in deterministic order and embedded into the
        compiled world as declarative snapshots; an unbound, undeclared
        scenario compiles exactly as before.
        """
        scenario = self._store.get_scenario(tenant_id, scenario_id)
        bindings = self._store.list_domain_pack_bindings(tenant_id, scenario_id)
        declarations = self._store.list_domain_capability_declarations(tenant_id, scenario_id)
        state_models = self._store.list_domain_state_models(tenant_id, scenario_id)
        transitions = self._store.list_domain_state_transitions(tenant_id, scenario_id)
        observations = self._store.list_domain_metric_observations(tenant_id, scenario_id)
        compiled = compile_world(
            scenario,
            bindings=bindings,
            declarations=declarations,
            state_models=state_models,
            transitions=transitions,
            domain_metric_observations=observations,
        )
        self._store.put_world(compiled.version, compiled.manifest)
        return compiled

    def world(self, tenant_id: str, world_version_id: str) -> WorldVersion:
        """Fetch a compiled immutable world by version id.

        The stored world is verified against the compiler's deterministic
        output before it crosses the read boundary: a corrupted or
        non-compiler world raises WorldSnapshotIntegrityError and is
        never returned.
        """
        world = self._store.get_world(tenant_id, world_version_id)
        manifest = self._store.get_manifest(tenant_id, world_version_id)
        verify_world_snapshot(world, manifest)
        return world

    def manifest(self, tenant_id: str, world_version_id: str) -> WorldManifest:
        """Fetch the manifest of a compiled world by version id.

        The stored world is verified against the compiler's deterministic
        output before the manifest crosses the read boundary: a corrupted
        or non-compiler world raises WorldSnapshotIntegrityError and is
        never returned.
        """
        world = self._store.get_world(tenant_id, world_version_id)
        manifest = self._store.get_manifest(tenant_id, world_version_id)
        verify_world_snapshot(world, manifest)
        return manifest
