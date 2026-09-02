"""Phase 28 causal runtime-observation contract tests (H28-S01).

Covers the two new top-level public contracts
``RuntimeObservationDeclaration`` and ``ExternalObservationInputBundle``,
and the nested non-authoritative ``RuntimeObservationEvent``: exact
timing/terminal causality, exact finite numeric adversarial rules,
closed source/noise discriminators, state-versus-external provenance
separation, external-input canonical ordering and coordinate uniqueness,
exact integer/number entry agreement, the immutable 50-contract/schema
prefix with the exact index-52 append (``AdaptivePolicy``) preserved, and
the absence of any execution surface.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationInputEntry,
    RuntimeObservationDeclaration,
    RuntimeObservationEvent,
    StateFieldObservationSource,
)
from pydantic import BaseModel, ValidationError

from tests.test_api_phase27 import _HISTORICAL_47_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
KALHAS_ROOT = REPO_ROOT / "kalhas"

H64 = "1" * 64
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: Non-nested/helper models that must never be registered or exported.
_NESTED_MODELS = (
    "RuntimeObservationEvent",
    "ObservationTiming",
    "NoObservationNoise",
    "AdditiveUniformObservationNoise",
    "StateFieldObservationSource",
    "ExternalObservationSource",
    "ExternalObservationInputEntry",
)

#: Execution-providence surfaces that must never be expressible.
_FORBIDDEN_SURFACE = (
    "strategy_candidate_id",
    "policy_id",
    "run_id",
    "provider",
    "network",
    "callback",
    "executable",
    "branch_count",
    "rule_count",
    "rng_position",
    "random",
)


def _additive_noise() -> dict[str, object]:
    return {
        "kind": "additive_uniform",
        "lower_bound": -1.0,
        "upper_bound": 1.0,
        "sampler_version": "sha256-counter-v1",
        "quantization_policy": "rational-round-half-even",
        "quantization_fraction_bits": 64,
        "draw_count": 1,
    }


def _declaration_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "runtime-observation-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "observation_id": "observation-1",
        "runtime_version": "4.0.0",
        "observation_source": {
            "kind": "state_field",
            "manifest_id": "manifest-1",
            "state_model_identifier": "state-model-1",
            "state_model_id": "sm-1",
            "state_model_content_hash": H64,
            "state_field_id": "level",
            "state_field_value_kind": "integer",
        },
        "observed_value_kind": "integer",
        "unit": None,
        "timing": {"start_step": 0, "every_n_steps": 1, "delay_steps": 0},
        "noise": {"kind": "none", "draw_count": 0},
        "missing_behavior": "false",
        "content_hash": H64,
        "declared_at": NOW,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _external_declaration_payload(**overrides: object) -> dict[str, object]:
    payload = _declaration_payload(
        identifier="external-observation-1",
        observation_source={
            "kind": "external_input",
            "external_channel_id": "channel-a",
            "external_value_kind": "number",
        },
        observed_value_kind="number",
    )
    payload.update(overrides)
    return payload


def _event_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "event-1",
        "runtime_version": "4.0.0",
        "observation_declaration_id": "runtime-observation-1",
        "observation_declaration_content_hash": H64,
        "observation_id": "observation-1",
        "source_kind": "state_field",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "sequence_position": 0,
        "source_step_index": 0,
        "delay_steps": 0,
        "available_decision_step": 0,
        "terminal": False,
        "status": "observed",
        "source_state_hash": H64,
        "source_value": 5,
        "exposed_observation_value": 5,
        "observed_value_kind": "integer",
        "observed_value_unit": None,
        "noise_domain_literal": "kalhas-observation-noise-v1",
        "noise_sampler_version": "sha256-counter-v1",
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _external_event_payload(**overrides: object) -> dict[str, object]:
    payload = _event_payload(
        source_kind="external_input",
        source_state_hash=None,
        external_input_bundle_id="bundle-1",
        external_input_bundle_content_hash=H64,
    )
    payload.update(overrides)
    return payload


def _entry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "entry-1",
        "runtime_observation_declaration_id": "runtime-observation-1",
        "runtime_observation_declaration_content_hash": H64,
        "observation_id": "observation-1",
        "external_channel_id": "channel-a",
        "source_step_index": 2,
        "value_kind": "number",
        "unit": None,
        "value": 1.5,
        "content_hash": H64,
    }
    payload.update(overrides)
    return payload


def _bundle_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identifier": "external-input-bundle-1",
        "tenant_id": "tenant-1",
        "schema_version": "1.0.0",
        "campaign_id": "campaign-1",
        "scenario_id": "scenario-1",
        "world_version_id": "world-v1",
        "world_content_hash": H64,
        "scenario_seed_id": "seed-1",
        "seed_content_hash": H64,
        "runtime_version": "4.0.0",
        "entries": [_entry_payload()],
        "content_hash": H64,
        "accepted_at": NOW,
    }
    payload.update(overrides)
    return payload


class TestRuntimeObservationDeclaration:
    def test_state_field_declaration_round_trip(self) -> None:
        declaration = RuntimeObservationDeclaration.model_validate(_declaration_payload())
        assert declaration.runtime_version == "4.0.0"
        assert declaration.observation_source.kind == "state_field"
        dumped = declaration.model_dump_json()
        reloaded = RuntimeObservationDeclaration.model_validate_json(dumped)
        assert reloaded == declaration
        assert isinstance(reloaded.observation_source, StateFieldObservationSource)
        assert reloaded.observation_source.state_field_value_kind == "integer"
        assert reloaded.timing.every_n_steps == 1

    def test_external_input_declaration_round_trip(self) -> None:
        declaration = RuntimeObservationDeclaration.model_validate(_external_declaration_payload())
        assert declaration.observation_source.kind == "external_input"
        assert declaration.observation_source.external_channel_id == "channel-a"
        dumped = declaration.model_dump_json()
        reloaded = RuntimeObservationDeclaration.model_validate_json(dumped)
        assert reloaded == declaration

    def test_declaration_is_frozen(self) -> None:
        declaration = RuntimeObservationDeclaration.model_validate(_declaration_payload())
        with pytest.raises(ValidationError):
            declaration.unit = "tampered"

    def test_declaration_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(_declaration_payload(unexpected_field=1))

    def test_runtime_literal_is_exactly_4_0_0(self) -> None:
        for wrong in ("3.0.0", "4.0.1", "4.1.0", "5.0.0"):
            with pytest.raises(ValidationError):
                RuntimeObservationDeclaration.model_validate(
                    _declaration_payload(runtime_version=wrong)
                )

    def test_closed_source_discriminator(self) -> None:
        source = cast(dict[str, object], _declaration_payload()["observation_source"])
        source["kind"] = "quantum"
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(observation_source=source)
            )
        source = cast(dict[str, object], _declaration_payload()["observation_source"])
        source["extra_provenance"] = True
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(observation_source=source)
            )

    def test_closed_noise_discriminator(self) -> None:
        noise = cast(dict[str, object], _declaration_payload()["noise"])
        noise["kind"] = "gaussian"
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(_declaration_payload(noise=noise))
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise={"kind": "none", "draw_count": 1})
            )
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise={"kind": "none", "draw_count": 0, "surprise": True})
            )

    def test_timing_bounds_and_type_rejection(self) -> None:
        bad_timings: tuple[dict[str, object], ...] = (
            {"start_step": -1, "every_n_steps": 1, "delay_steps": 0},
            {"start_step": 0, "every_n_steps": 0, "delay_steps": 0},
            {"start_step": 0, "every_n_steps": -1, "delay_steps": 0},
            {"start_step": 0, "every_n_steps": 1, "delay_steps": -1},
            {"start_step": 1.5, "every_n_steps": 1, "delay_steps": 0},
            {"start_step": True, "every_n_steps": 1, "delay_steps": 0},
            {"start_step": "0", "every_n_steps": 1, "delay_steps": 0},
            {"start_step": 0, "every_n_steps": 1.0, "delay_steps": 0},
            {"start_step": 0, "every_n_steps": 2, "delay_steps": 0.5},
        )
        for bad in bad_timings:
            with pytest.raises(ValidationError):
                RuntimeObservationDeclaration.model_validate(_declaration_payload(timing=bad))
        timing = {"start_step": 2, "every_n_steps": 3, "delay_steps": 1}
        declaration = RuntimeObservationDeclaration.model_validate(
            _declaration_payload(timing=timing)
        )
        assert declaration.timing.start_step == 2
        assert declaration.timing.every_n_steps == 3
        assert declaration.timing.delay_steps == 1

    def test_noise_bounds_exact_finite_rules(self) -> None:
        base = dict(_additive_noise())
        declarant = RuntimeObservationDeclaration.model_validate(
            _declaration_payload(noise=base, observed_value_kind="number")
        )
        assert declarant.noise.kind == "additive_uniform"
        assert declarant.noise.draw_count == 1

        reversed_bounds = dict(base)
        reversed_bounds["lower_bound"], reversed_bounds["upper_bound"] = (
            reversed_bounds["upper_bound"],
            reversed_bounds["lower_bound"],
        )
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise=reversed_bounds, observed_value_kind="number")
            )

        for key in ("lower_bound", "upper_bound"):
            for bad in (True, "1.5", float("nan"), float("inf")):
                noise = dict(base)
                noise[key] = bad
                with pytest.raises(ValidationError):
                    RuntimeObservationDeclaration.model_validate(
                        _declaration_payload(noise=noise, observed_value_kind="number")
                    )

        bad_draw = dict(base)
        bad_draw["draw_count"] = 2
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise=bad_draw, observed_value_kind="number")
            )
        bad_sampler = dict(base)
        bad_sampler["sampler_version"] = "other"
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise=bad_sampler, observed_value_kind="number")
            )
        bad_bits = dict(base)
        bad_bits["quantization_fraction_bits"] = 32
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise=bad_bits, observed_value_kind="number")
            )

    def test_source_noise_value_kind_cross_field_rules(self) -> None:
        # Without noise, observed_value_kind must equal the source value kind.
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(observed_value_kind="number")
            )
        # State-field plus additive noise yields observed kind "number".
        valid = RuntimeObservationDeclaration.model_validate(
            _declaration_payload(noise=_additive_noise(), observed_value_kind="number")
        )
        assert valid.observed_value_kind == "number"
        # Additive noise with an integer observed kind is invalid.
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _declaration_payload(noise=_additive_noise())
            )
        # External inputs forbid fresh noise.
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _external_declaration_payload(noise=_additive_noise())
            )
        # External-input source without noise must equal the external kind.
        with pytest.raises(ValidationError):
            RuntimeObservationDeclaration.model_validate(
                _external_declaration_payload(observed_value_kind="integer")
            )

    def test_metadata_rejects_non_finite(self) -> None:
        for bad_metadata in ({"x": float("nan")}, {"nested": {"y": float("inf")}}):
            with pytest.raises(ValidationError):
                RuntimeObservationDeclaration.model_validate(
                    _declaration_payload(metadata=bad_metadata)
                )


class TestRuntimeObservationEvent:
    def test_observed_event_shape(self) -> None:
        event = RuntimeObservationEvent.model_validate(_event_payload())
        assert event.status == "observed"
        assert event.source_value == 5
        assert event.exposed_observation_value == 5

    def test_missing_event_shape(self) -> None:
        missing = _event_payload(
            status="missing",
            source_value=None,
            exposed_observation_value=None,
            observed_value_kind=None,
            observed_value_unit=None,
        )
        event = RuntimeObservationEvent.model_validate(missing)
        assert event.status == "missing"
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(status="missing"))

    def test_terminal_vs_non_terminal_availability(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(available_decision_step=1))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(available_decision_step=None))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(terminal=True))
        terminal = RuntimeObservationEvent.model_validate(
            _event_payload(terminal=True, available_decision_step=None)
        )
        assert terminal.available_decision_step is None

    def test_availability_equals_source_plus_delay(self) -> None:
        event = RuntimeObservationEvent.model_validate(
            _event_payload(source_step_index=4, delay_steps=2, available_decision_step=6)
        )
        assert event.available_decision_step == 6

    def test_observed_requires_exact_finite_values(self) -> None:
        for bad in (True, "5", float("nan"), float("inf"), None):
            with pytest.raises(ValidationError):
                RuntimeObservationEvent.model_validate(_event_payload(source_value=bad))
            with pytest.raises(ValidationError):
                RuntimeObservationEvent.model_validate(
                    _event_payload(exposed_observation_value=bad)
                )
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(observed_value_kind=None))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(exposed_observation_value=5.5))

    def test_state_versus_external_provenance_separation(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(source_state_hash=None))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(
                _event_payload(
                    external_input_bundle_id="bundle-1",
                    external_input_bundle_content_hash=H64,
                )
            )
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(source_kind="external_input"))
        external = RuntimeObservationEvent.model_validate(_external_event_payload())
        assert external.external_input_bundle_id == "bundle-1"
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_external_event_payload(source_state_hash=H64))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_external_event_payload(applied_noise_value=0.5))
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_external_event_payload(noise_draw_index=3))

    def test_event_is_frozen_and_strict(self) -> None:
        event = RuntimeObservationEvent.model_validate(_event_payload())
        with pytest.raises(ValidationError):
            cast(Any, event).status = "tampered"
        with pytest.raises(ValidationError):
            RuntimeObservationEvent.model_validate(_event_payload(unexpected_field=1))


class TestExternalObservationInputBundle:
    def test_bundle_round_trip(self) -> None:
        bundle = ExternalObservationInputBundle.model_validate(_bundle_payload())
        assert bundle.runtime_version == "4.0.0"
        dumped = bundle.model_dump_json()
        reloaded = ExternalObservationInputBundle.model_validate_json(dumped)
        assert reloaded == bundle

    def test_bundle_is_frozen_and_strict_and_non_empty(self) -> None:
        bundle = ExternalObservationInputBundle.model_validate(_bundle_payload())
        with pytest.raises(ValidationError):
            bundle.campaign_id = "tampered"
        with pytest.raises(ValidationError):
            ExternalObservationInputBundle.model_validate(_bundle_payload(unexpected_field=1))
        with pytest.raises(ValidationError):
            ExternalObservationInputBundle.model_validate(_bundle_payload(entries=[]))

    def test_canonical_ordering(self) -> None:
        first = _entry_payload(
            identifier="entry-1",
            runtime_observation_declaration_id="decl-a",
            source_step_index=2,
        )
        second = _entry_payload(
            identifier="entry-2",
            runtime_observation_declaration_id="decl-b",
            source_step_index=5,
        )
        in_order = ExternalObservationInputBundle.model_validate(
            _bundle_payload(entries=[first, second])
        )
        assert len(in_order.entries) == 2
        with pytest.raises(ValidationError):
            ExternalObservationInputBundle.model_validate(_bundle_payload(entries=[second, first]))

    def test_duplicate_coordinate_rejection(self) -> None:
        first = _entry_payload(
            identifier="entry-1",
            runtime_observation_declaration_id="decl-a",
            source_step_index=2,
        )
        duplicate = _entry_payload(
            identifier="entry-3",
            runtime_observation_declaration_id="decl-a",
            source_step_index=2,
        )
        with pytest.raises(ValidationError):
            ExternalObservationInputBundle.model_validate(
                _bundle_payload(entries=[first, duplicate])
            )

    def test_exact_integer_and_number_entry_agreement(self) -> None:
        integer_entry = _entry_payload(value_kind="integer", value=7)
        ExternalObservationInputBundle.model_validate(_bundle_payload(entries=[integer_entry]))
        for bad_value in (7.0, True, "7", float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                ExternalObservationInputBundle.model_validate(
                    _bundle_payload(entries=[_entry_payload(value_kind="integer", value=bad_value)])
                )
        for good_number in (1.5, 3):
            ExternalObservationInputBundle.model_validate(
                _bundle_payload(entries=[_entry_payload(value_kind="number", value=good_number)])
            )
        for bad_number in (True, "1.5", float("nan"), float("inf")):
            with pytest.raises(ValidationError):
                ExternalObservationInputBundle.model_validate(
                    _bundle_payload(entries=[_entry_payload(value_kind="number", value=bad_number)])
                )


class TestForbiddenSurfacesAndRegistry:
    def _model_fields(self) -> tuple[tuple[str, ...], ...]:
        return (
            tuple(RuntimeObservationDeclaration.model_fields),
            tuple(RuntimeObservationEvent.model_fields),
            tuple(ExternalObservationInputBundle.model_fields),
            tuple(ExternalObservationInputEntry.model_fields),
        )

    def test_no_forbidden_execution_surfaces_expressible(self) -> None:
        for fields in self._model_fields():
            for token in _FORBIDDEN_SURFACE:
                assert not any(token in name for name in fields), (
                    f"forbidden surface {token!r} expressible in {fields!r}"
                )

    def test_event_and_helper_models_not_independently_registered(self) -> None:
        names = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        for nested in _NESTED_MODELS:
            assert nested not in names, f"{nested} is independently registered"
        assert "RuntimeObservationDeclaration" in names
        assert "ExternalObservationInputBundle" in names

    def test_immutable_52_contract_prefix_preserved_with_additive_tail(self) -> None:
        """H28-S01 owns the exact first 52-contract prefix forever.

        Later Phase 28 slices may only append backward-compatible public
        contracts after index 51; the prefix itself never changes.
        """
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 52
        assert len(_HISTORICAL_47_NAMES) == 47
        assert names[:47] == _HISTORICAL_47_NAMES
        assert names[47:50] == (
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
        )
        assert names[50] == "RuntimeObservationDeclaration"
        assert names[51] == "ExternalObservationInputBundle"

    def test_immutable_53_contract_prefix_preserved_with_additive_tail(self) -> None:
        """H28-S01 owns the exact first 53-contract prefix forever.

        Later Phase 28 slices may only append backward-compatible public
        contracts after index 52; the prefix itself never changes and
        ``AdaptivePolicy`` remains the exact index-52 entry.
        """
        names = tuple(contract.__name__ for contract in PUBLIC_CONTRACTS)
        assert len(PUBLIC_CONTRACTS) >= 53
        assert names[:53] == (
            *_HISTORICAL_47_NAMES,
            "CampaignDecisionPolicy",
            "CampaignStrategyComparison",
            "CampaignDecisionBrief",
            "RuntimeObservationDeclaration",
            "ExternalObservationInputBundle",
            "AdaptivePolicy",
        )
        assert names[52] == "AdaptivePolicy"

    def test_no_standalone_nested_schema_artifacts(self) -> None:
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        assert len(schema_files) == len(PUBLIC_CONTRACTS)
        names = {path.name for path in schema_files}
        for nested in _NESTED_MODELS:
            assert f"{nested}.schema.json" not in names, f"standalone schema artifact for {nested}"
        assert "RuntimeObservationDeclaration.schema.json" in names
        assert "ExternalObservationInputBundle.schema.json" in names

    def test_generated_schemas_equal_model_json_schema(self) -> None:
        expected: dict[type[BaseModel], str] = {
            RuntimeObservationDeclaration: "RuntimeObservationDeclaration.schema.json",
            ExternalObservationInputBundle: "ExternalObservationInputBundle.schema.json",
        }
        for contract, filename in expected.items():
            rendered = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
            assert rendered == contract.model_json_schema()
            assert rendered["title"] == contract.__name__
            assert rendered["additionalProperties"] is False

    def test_pre_existing_schema_files_byte_identical(self) -> None:
        """No tracked schema artifact may drift (only the two new files are added)."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "schemas/v1"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_contract_module_has_no_executable_or_network_surface(self) -> None:
        source = (KALHAS_ROOT / "contracts" / "v1" / "runtime_observation.py").read_text(
            encoding="utf-8"
        )
        code = "".join(source.split('"""')[::2])
        for token in (
            "eval(",
            "exec(",
            "import_module",
            "__import__",
            "lambda",
            "callback",
            "provider",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "random",
            "uuid",
            "datetime.now",
        ):
            assert token not in code, f"forbidden surface token {token!r} in module"
