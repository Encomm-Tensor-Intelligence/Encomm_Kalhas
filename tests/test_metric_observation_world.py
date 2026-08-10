"""Phase 19 world compiler tests: observation-binding snapshots.

Every subsequently compiled ``WorldVersion`` carries an immutable
snapshot of the scenario's observation bindings under the compiler-owned
``domain_metric_observations`` key - only when non-empty, canonicalized
by metric identifier, so observation-free worlds compile byte-identically
to the pre-Phase-19 compiler and caller/store insertion order never
affects the world identifier, content hash, manifest, or embedded
ordering. The compiler never interprets or extracts a metric value and
never reads trajectory artifacts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from kalhas.application.world_compiler import compile_world, content_hash
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding

from tests.phase4_helpers import build_scenario

DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0" * 64


def make_observation(metric_id: str, **overrides: object) -> DomainMetricObservationBinding:
    payload: dict[str, object] = {
        "identifier": f"observation-{metric_id}",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "binding_id": "binding-1",
        "manifest_id": "manifest-1",
        "pack_id": "pack-1",
        "pack_version": "1.2.3",
        "manifest_content_hash": HASH_64,
        "metric_id": metric_id,
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "state_field_id": "level",
        "state_field_value_kind": "integer",
        "observation_point": "final_state",
        "content_hash": HASH_64,
        "declared_at": DECLARED_AT,
        "metadata": {},
    }
    payload.update(overrides)
    return DomainMetricObservationBinding.model_validate(payload)


class TestObservationFreeCompilation:
    def test_empty_observation_set_preserves_byte_identical_compilation(self) -> None:
        scenario = build_scenario()
        compiled_omitted = compile_world(scenario)
        compiled_empty = compile_world(scenario, domain_metric_observations=())
        assert compiled_omitted.version.content_hash == compiled_empty.version.content_hash
        assert compiled_omitted.version.world == compiled_empty.version.world
        assert compiled_omitted.manifest == compiled_empty.manifest
        assert content_hash(scenario) == content_hash(scenario, domain_metric_observations=())
        assert "domain_metric_observations" not in compiled_omitted.version.world
        assert "declared_domain_metric_observation_count" not in compiled_omitted.manifest.state


class TestObservationEmbedding:
    def test_one_binding_embedded(self) -> None:
        scenario = build_scenario()
        compiled = compile_world(scenario, domain_metric_observations=(make_observation("m-1"),))
        snapshots = compiled.version.world["domain_metric_observations"]
        assert isinstance(snapshots, list)
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert isinstance(snapshot, dict)
        assert snapshot["metric_id"] == "m-1"
        assert snapshot["state_field_id"] == "level"
        assert compiled.manifest.state["declared_domain_metric_observation_count"] == 1
        assert compiled.version.content_hash != content_hash(scenario)

    def test_multiple_bindings_embedded_in_canonical_metric_id_order(self) -> None:
        scenario = build_scenario()
        observations = (
            make_observation("m-3"),
            make_observation("m-1"),
            make_observation("m-2"),
        )
        compiled = compile_world(scenario, domain_metric_observations=observations)
        snapshots = compiled.version.world["domain_metric_observations"]
        assert isinstance(snapshots, list)
        assert [
            DomainMetricObservationBinding.model_validate(snapshot).metric_id
            for snapshot in snapshots
        ] == ["m-1", "m-2", "m-3"]
        assert compiled.manifest.state["declared_domain_metric_observation_count"] == 3

    def test_snapshots_match_stored_binding_exactly(self) -> None:
        scenario = build_scenario()
        observation = make_observation("m-1", metadata={"k": [1, 2]})
        compiled = compile_world(scenario, domain_metric_observations=(observation,))
        snapshots = compiled.version.world["domain_metric_observations"]
        assert isinstance(snapshots, list)
        snapshot = snapshots[0]
        assert isinstance(snapshot, dict)
        assert snapshot == observation.model_dump(mode="json")

    def test_insertion_order_never_affects_hash_or_content(self) -> None:
        scenario = build_scenario()
        observations = (
            make_observation("m-1"),
            make_observation("m-2"),
        )
        digest_ordered = content_hash(scenario, domain_metric_observations=observations)
        digest_reversed = content_hash(scenario, domain_metric_observations=observations[::-1])
        assert digest_ordered == digest_reversed
        compiled_ordered = compile_world(scenario, domain_metric_observations=observations)
        compiled_reversed = compile_world(scenario, domain_metric_observations=observations[::-1])
        assert compiled_ordered.version == compiled_reversed.version
        assert compiled_ordered.manifest == compiled_reversed.manifest

    def test_adding_bindings_changes_world_identifier_and_content_hash(self) -> None:
        scenario = build_scenario()
        without = compile_world(scenario)
        with_one = compile_world(scenario, domain_metric_observations=(make_observation("m-1"),))
        with_two = compile_world(
            scenario,
            domain_metric_observations=(make_observation("m-1"), make_observation("m-2")),
        )
        assert without.version.identifier != with_one.version.identifier
        assert with_one.version.identifier != with_two.version.identifier
        assert with_one.version.content_hash != without.version.content_hash
        assert with_two.version.content_hash != with_one.version.content_hash

    def test_compilation_is_deterministic_across_declarations(self) -> None:
        """Later declarations never change previously compiled worlds.

        Compilation is a pure function of its inputs: the same inputs
        always reproduce the same immutable world byte-identically, and
        declarations added after a compilation affect only subsequently
        compiled worlds (covered end-to-end by the API test suite).
        """
        scenario = build_scenario()
        compiled_before = compile_world(scenario)
        reproduced = compile_world(scenario)
        assert reproduced.version == compiled_before.version
        assert reproduced.manifest == compiled_before.manifest

    def test_manifest_count_is_conditional_and_exact(self) -> None:
        scenario = build_scenario()
        plain = compile_world(scenario)
        assert "declared_domain_metric_observation_count" not in plain.manifest.state
        with_one = compile_world(scenario, domain_metric_observations=(make_observation("m-1"),))
        assert with_one.manifest.state["declared_domain_metric_observation_count"] == 1
        with_three = compile_world(
            scenario,
            domain_metric_observations=(
                make_observation("m-1"),
                make_observation("m-2"),
                make_observation("m-3"),
            ),
        )
        assert with_three.manifest.state["declared_domain_metric_observation_count"] == 3


class TestCompilerBoundaries:
    def test_compiler_does_not_interpret_or_extract_values(self) -> None:
        """AST call scan: the compiler never evaluates or extracts anything."""
        import ast

        module = ast.parse(Path("kalhas/application/world_compiler.py").read_text(encoding="utf-8"))
        forbidden = {"evaluate_trajectory", "derive_initial_state", "validate_state", "state_hash"}
        calls: list[tuple[int, str]] = []
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name in forbidden:
                calls.append((node.lineno, name))
        assert not calls

    def test_compiler_source_has_no_trajectory_or_executable_surface(self) -> None:
        source = Path("kalhas/application/world_compiler.py").read_text(encoding="utf-8")
        code = "".join(source.split('"""')[::2])
        assert not re.search(
            r"\b(RunTrajectoryExecution|trajectory_execution|initial_state|final_state)\b", code
        )
        # Sort-key lambdas are legitimate declarative helpers (pre-existing
        # Phase 7-11 compiler code); dynamic loading and callbacks are not.
        assert not re.search(
            r"\b(importlib|__import__|import_module|exec\(|eval\(|callback)\b", code
        )
        assert "kalhas.domain_packs" not in code
        assert not re.search(
            r"\b(random|uuid|datetime\.now|requests|urllib|socket|subprocess)\b", code
        )
