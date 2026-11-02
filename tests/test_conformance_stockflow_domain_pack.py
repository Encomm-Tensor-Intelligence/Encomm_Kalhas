"""H29-S07 tests for the synthetic non-health conformance stock-flow DomainPack.

Covers:

A. Protocol - static ``DomainPack`` conformance, exactly one public
   executable operation, exact v1 contract types, and the exports of the
   fixture subpackage and of ``kalhas.domain_packs``.
B. Isolation - no kernel module references the fixture, the fixture
   never imports PAN, PAN never imports the fixture, and no dynamic
   loading exists.
C. Identity - byte-identical fresh packs, recomputed hashes, reproduced
   schema descriptor hashes, the on-disk ``mechanism.py`` and ``uv.lock``
   bindings (and LF-only bytes), fixed timestamps, and no maturity.
D. Execution - direct and dispatched steps, byte-identical repeats, and
   no mutation or aliasing of request or result.
E. Mechanism - hand-calculated fixtures and an exhaustive small grid.
F. Fail-closed - invalid values, keys, bounds, exogenous input, foreign
   identities, and tampered or self-consistently forged authorities.
G. Neutrality - no health vocabulary in the fixture and no fixture
   vocabulary in the generic kernel.

Every pinned expectation was hand-calculated from the declared
equations in ``mechanism.py``; no expected value is produced by the
production transition.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC
from pathlib import Path
from typing import Literal, get_type_hints

import pytest
from kalhas.application.domain_mechanism_dispatcher import dispatch_domain_mechanism_step
from kalhas.application.domain_mechanism_errors import DomainMechanismDispatchError
from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismExogenousInput,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile
from kalhas.domain_packs import DomainPack
from kalhas.domain_packs.conformance_stockflow import ConformanceStockFlowV01DomainPack
from kalhas.domain_packs.conformance_stockflow import pack as stockflow_pack_module
from kalhas.domain_packs.conformance_stockflow.mechanism import (
    ConformanceStockFlowError,
    compute_transition,
    validate_action_payload,
    validate_configuration_payload,
    validate_state_payload,
)
from pydantic import BaseModel, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
PACKAGE = KALHAS_ROOT / "domain_packs" / "conformance_stockflow"
PAN_PACKAGE = KALHAS_ROOT / "domain_packs" / "pan"
MECHANISM_PATH = PACKAGE / "mechanism.py"
LOCK_PATH = REPO_ROOT / "uv.lock"

FIXTURE_MODULES = ("__init__.py", "mechanism.py", "pack.py")

#: The fixed release configuration (hand-pinned, units).
CAPACITY = 10
INFLOW = 3
MAX_RELEASE = 5

_MATURITY_VOCABULARY = (
    "experimental",
    "benchmarked",
    "externally_reviewed",
    "partner_evaluation_ready",
    "conformance_only",
    "catalogued",
)

_HEALTH_VOCABULARY = re.compile(
    r"(pandemic|infect|hospital|\bicu\b|compartment|patient|vaccine|epidem|disease|clinical)",
    re.IGNORECASE,
)

_FIXTURE_VOCABULARY = re.compile(r"(stockflow|stock-flow|spill|shortfall)", re.IGNORECASE)

_DYNAMIC_LOADING = re.compile(
    r"\b(importlib|pkgutil|entry_points|import_module|__import__|walk_packages|iter_modules)\b"
)

_FAKE_HEX_64 = "0123456789abcdef" * 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_hash(payload: object) -> str:
    """Canonical SHA-256 of the exact JSON payload (independent of production)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _self_hash(model: BaseModel) -> str:
    dumped: dict[str, object] = model.model_dump(mode="json")
    del dumped["content_hash"]
    return _canonical_hash(dumped)


def _request_payload(
    pack: ConformanceStockFlowV01DomainPack,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
    *,
    identifier: str = "stockflow-request-1",
    step_index: int = 0,
    exogenous_inputs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A canonical, hash-consistent request payload for the pack authorities."""
    spec = pack.mechanism_spec
    state: Mapping[str, object] = {"level": 4} if state_payload is None else state_payload
    action: Mapping[str, object] = {"release": 2} if action_payload is None else action_payload
    configuration: Mapping[str, object] = (
        dict(spec.configuration) if configuration_payload is None else configuration_payload
    )
    payload: dict[str, object] = {
        "identifier": identifier,
        "tenant_id": "kalhas-synthetic",
        "schema_version": "1.0.0",
        "mechanism_spec_id": spec.identifier,
        "mechanism_spec_content_hash": spec.content_hash,
        "release_profile_id": pack.release_profile.identifier,
        "release_profile_content_hash": pack.release_profile.content_hash,
        "realization_id": None,
        "realization_content_hash": None,
        "scenario_id": "scenario-stockflow-1",
        "scenario_content_hash": "a" * 64,
        "world_version_id": "world-stockflow-v1",
        "world_content_hash": "b" * 64,
        "seed_id": "seed-stockflow-1",
        "seed_content_hash": "c" * 64,
        "run_id": "run-stockflow-1",
        "step_index": step_index,
        "state_schema_id": spec.state_schema_id,
        "action_schema_id": spec.action_schema_id,
        "configuration_schema_id": spec.configuration_schema_id,
        "state_schema_hash": spec.state_schema_hash,
        "action_schema_hash": spec.action_schema_hash,
        "configuration_schema_hash": spec.configuration_schema_hash,
        "state_payload": state,
        "action_payload": action,
        "configuration_payload": configuration,
        "state_hash": _canonical_hash(state),
        "action_hash": _canonical_hash(action),
        "configuration_hash": _canonical_hash(configuration),
        "exogenous_inputs": [] if exogenous_inputs is None else exogenous_inputs,
        "content_hash": "0" * 64,
    }
    return _seal(payload)


def _seal(payload: dict[str, object]) -> dict[str, object]:
    payload["content_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    return payload


def _request(
    pack: ConformanceStockFlowV01DomainPack,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
    *,
    identifier: str = "stockflow-request-1",
) -> DomainMechanismStepRequest:
    return DomainMechanismStepRequest.model_validate(
        _request_payload(
            pack,
            state_payload,
            action_payload,
            configuration_payload,
            identifier=identifier,
        )
    )


def _expect_rejection(
    pack: ConformanceStockFlowV01DomainPack,
    state_payload: Mapping[str, object] | None = None,
    action_payload: Mapping[str, object] | None = None,
    configuration_payload: Mapping[str, object] | None = None,
) -> None:
    """The mutated request is rejected by direct step and by dispatch."""
    request = _request(pack, state_payload, action_payload, configuration_payload)
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def _production_code(name: str) -> str:
    """The production source of one fixture module with docstrings stripped."""
    source = (PACKAGE / name).read_text(encoding="utf-8")
    return "".join(source.split('"""')[::2])


@pytest.fixture(scope="module")
def pack() -> ConformanceStockFlowV01DomainPack:
    return ConformanceStockFlowV01DomainPack()


# ---------------------------------------------------------------------------
# A. Protocol
# ---------------------------------------------------------------------------


def test_pack_statically_conforms_to_domainpack_protocol() -> None:
    pack_hints = get_type_hints(ConformanceStockFlowV01DomainPack)
    protocol_hints = get_type_hints(DomainPack)
    for member in ("manifest", "release_profile", "mechanism_protocol_version"):
        assert pack_hints[member] == protocol_hints[member], member
    assert get_type_hints(ConformanceStockFlowV01DomainPack.step) == get_type_hints(DomainPack.step)
    assert pack_hints["mechanism_spec"] is DomainMechanismSpec
    assert pack_hints["mechanism_protocol_version"] == Literal["1.0.0"]
    instance = ConformanceStockFlowV01DomainPack()
    assert instance.mechanism_protocol_version == "1.0.0"
    assert getattr(DomainPack, "_is_protocol", False) is True
    # Passing the instance where a DomainPack is annotated proves structural
    # conformance under strict mypy.
    typed: DomainPack = instance
    assert typed is instance


def test_pack_has_exactly_one_public_executable_operation() -> None:
    public_methods = {
        name
        for name in dir(ConformanceStockFlowV01DomainPack)
        if not name.startswith("_")
        and callable(getattr(ConformanceStockFlowV01DomainPack, name, None))
    }
    assert public_methods == {"step"}


def test_pack_authorities_are_exact_v1_contract_types(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    assert type(pack.manifest) is DomainPackManifest
    assert type(pack.mechanism_spec) is DomainMechanismSpec
    assert type(pack.release_profile) is ModelPackReleaseProfile
    assert pack.release_profile.manifest == pack.manifest
    assert pack.release_profile.mechanism_spec == pack.mechanism_spec
    assert pack.manifest.pack_id == pack.mechanism_spec.pack_id == "kalhas-conformance-stockflow"
    assert pack.manifest.pack_version == "0.1.0"
    assert pack.manifest.tenant_id == "kalhas-synthetic"
    assert pack.mechanism_spec.mechanism_id == "stockflow-single-bin"
    assert pack.mechanism_spec.mechanism_version == "0.1.0"
    assert pack.mechanism_spec.mechanism_protocol_version == "1.0.0"
    assert pack.mechanism_spec.timestep == 1
    assert pack.mechanism_spec.timestep_unit == "step"
    assert pack.mechanism_spec.numeric_profile == "kalhas-platform-bound-binary64-v1"
    assert pack.mechanism_spec.precision == "ieee-754-binary64"
    assert pack.mechanism_spec.rounding_mode == "round-to-nearest-ties-to-even"
    assert pack.mechanism_spec.data_identities == ()
    assert pack.release_profile.datasets == ()
    assert pack.release_profile.decision_scope == "decision_support_only"
    assert pack.release_profile.output_labeling == "conditional_modeled_outcomes"
    assert pack.release_profile.accountability == "accountable_human_authority_required"
    assert len(pack.release_profile.prohibited_uses) == 10
    assert [boundary.unit for boundary in pack.mechanism_spec.quantization_boundaries] == [
        "units"
    ] * 4
    assert [boundary.quantum for boundary in pack.mechanism_spec.quantization_boundaries] == [1] * 4


def test_subpackage_and_top_level_exports() -> None:
    import kalhas.domain_packs as domain_packs_package
    import kalhas.domain_packs.conformance_stockflow as subpackage

    assert subpackage.__all__ == ["ConformanceStockFlowV01DomainPack"]
    assert subpackage.ConformanceStockFlowV01DomainPack is ConformanceStockFlowV01DomainPack
    assert domain_packs_package.__all__ == ["DomainPack"]
    assert sorted(path.name for path in PACKAGE.glob("*.py")) == sorted(FIXTURE_MODULES)


# ---------------------------------------------------------------------------
# B. Isolation
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in {path}"
            modules.add(node.module or "")
    return modules


def test_no_kernel_or_pan_module_references_the_fixture() -> None:
    offenders = []
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        if PACKAGE in path.parents:
            continue
        if "conformance_stockflow" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(KALHAS_ROOT).as_posix())
    assert offenders == []


#: Test modules explicitly approved to import the fixture besides this one.
#: Adding an importer is a deliberate, reviewed edit of this exact set.
_APPROVED_FIXTURE_TEST_IMPORTERS = ("test_phase29_shared_boundary_acceptance.py",)


def test_only_approved_test_modules_import_the_fixture() -> None:
    importers = []
    for path in sorted((REPO_ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        if "kalhas.domain_packs.conformance_stockflow" in path.read_text(encoding="utf-8"):
            importers.append(path.name)
    assert importers == list(_APPROVED_FIXTURE_TEST_IMPORTERS)


def test_fixture_never_imports_pan_and_has_a_closed_import_set() -> None:
    allowed_prefixes = (
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        "pydantic",
        "kalhas.application.hashing",
        "kalhas.application.domain_pack_registry",
        "kalhas.contracts.v1.",
        "kalhas.domain_packs.conformance_stockflow",
    )
    for name in FIXTURE_MODULES:
        for module in _imported_modules(PACKAGE / name):
            assert "pan" not in module.split("."), f"{name} imports {module}"
            assert module.startswith(allowed_prefixes), f"{name} imports {module}"


def test_pan_never_imports_the_fixture() -> None:
    for path in sorted(PAN_PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "conformance_stockflow" not in source, path.name


def test_fixture_has_no_dynamic_loading_io_or_mutable_globals() -> None:
    forbidden_calls = re.compile(
        r"\b(open|exec|eval|compile|getenv|environ|urlopen|socket|subprocess|"
        r"random|time|now|today|uuid4)\b\s*\("
    )
    for name in FIXTURE_MODULES:
        source = (PACKAGE / name).read_text(encoding="utf-8")
        assert not _DYNAMIC_LOADING.search(source), name
        code = _production_code(name)
        assert not forbidden_calls.search(code), name
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                if "__all__" in ast.unparse(node).split("=")[0]:
                    continue
                value = node.value
                assert not isinstance(value, ast.List | ast.Dict | ast.Set), (
                    f"mutable module-level container in {name}"
                )


# ---------------------------------------------------------------------------
# C. Identity
# ---------------------------------------------------------------------------


def test_fresh_packs_are_byte_identical() -> None:
    first = ConformanceStockFlowV01DomainPack()
    second = ConformanceStockFlowV01DomainPack()
    assert first.manifest.model_dump_json() == second.manifest.model_dump_json()
    assert first.mechanism_spec.model_dump_json() == second.mechanism_spec.model_dump_json()
    assert first.release_profile.model_dump_json() == second.release_profile.model_dump_json()
    assert first.manifest is not second.manifest
    assert first.mechanism_spec.configuration is not second.mechanism_spec.configuration


def test_content_hashes_recompute(pack: ConformanceStockFlowV01DomainPack) -> None:
    assert manifest_content_hash(pack.manifest) == pack.manifest.content_hash
    assert _self_hash(pack.mechanism_spec) == pack.mechanism_spec.content_hash
    assert _self_hash(pack.release_profile) == pack.release_profile.content_hash
    assert pack.mechanism_spec.configuration == {
        "capacity": CAPACITY,
        "inflow": INFLOW,
        "max_release": MAX_RELEASE,
    }
    assert _canonical_hash(pack.mechanism_spec.configuration) == (
        pack.mechanism_spec.configuration_hash
    )
    assert pack.release_profile.configuration_identity == pack.mechanism_spec.configuration_hash


def test_schema_descriptor_hashes_reproduce(pack: ConformanceStockFlowV01DomainPack) -> None:
    spec = pack.mechanism_spec
    module = stockflow_pack_module
    expected = (
        (module._state_schema, spec.state_schema_hash),
        (module._action_schema, spec.action_schema_hash),
        (module._configuration_schema, spec.configuration_schema_hash),
        (module._emission_schema, spec.emission_schema_hash),
        (module._evidence_schema, spec.evidence_schema_hash),
    )
    for builder, declared in expected:
        first = builder()
        second = builder()
        assert first == second
        assert first is not second
        assert _canonical_hash(first) == declared
    assert len({declared for _, declared in expected}) == 5


def test_implementation_hash_binds_the_exact_on_disk_mechanism_bytes(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    raw = MECHANISM_PATH.read_bytes()
    assert b"\r" not in raw
    digest = hashlib.sha256(raw).hexdigest()
    assert pack.mechanism_spec.implementation_hash == digest
    assert pack.mechanism_spec.platform_identity.implementation_hash == digest
    for name in FIXTURE_MODULES:
        assert b"\r" not in (PACKAGE / name).read_bytes(), name


def test_dependency_lock_hash_binds_the_exact_on_disk_lock_bytes(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    digest = hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    assert pack.mechanism_spec.dependency_lock_hash == digest
    assert pack.mechanism_spec.platform_identity.dependency_lock_hash == digest


def test_timestamps_are_fixed_and_timezone_aware(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    for stamp in (
        pack.manifest.created_at,
        pack.mechanism_spec.declared_at,
        pack.release_profile.declared_at,
    ):
        assert stamp.tzinfo is not None
        assert stamp.utcoffset() == UTC.utcoffset(None)
    assert pack.manifest.created_at == pack.mechanism_spec.declared_at
    assert pack.mechanism_spec.declared_at == pack.release_profile.declared_at


def test_release_profile_assigns_no_maturity_and_no_assurance_artifacts(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    dumped = pack.release_profile.model_dump_json().lower()
    for maturity in _MATURITY_VOCABULARY:
        assert maturity not in dumped, maturity
    assert "maturity" not in dumped
    for name in FIXTURE_MODULES:
        code = _production_code(name)
        assert "ModelPackAssuranceProfile" not in code
        assert "ModelPackCatalogueEntry" not in code
        for maturity in _MATURITY_VOCABULARY:
            assert maturity not in code.lower(), (name, maturity)


def test_release_profile_is_truthfully_synthetic(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    profile = pack.release_profile
    text = profile.model_dump_json().lower()
    assert "conformance fixture" in text
    assert "no real-world meaning" in text
    assert {unit.unit for unit in profile.units} == {"units", "step"}
    assert [use.use_id for use in profile.intended_uses] == ["synthetic_architecture_conformance"]


# ---------------------------------------------------------------------------
# D. Execution
# ---------------------------------------------------------------------------


def test_direct_step_returns_a_complete_valid_result(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    request = _request(pack)
    result = pack.step(request)
    assert type(result) is DomainMechanismStepResult
    assert result.request_id == request.identifier
    assert result.request_content_hash == request.content_hash
    assert result.mechanism_spec_content_hash == pack.mechanism_spec.content_hash
    assert result.release_profile_content_hash == pack.release_profile.content_hash
    assert result.next_state_payload == {"level": 5}
    assert result.next_state_hash == _canonical_hash({"level": 5})
    assert result.next_state_schema_id == pack.mechanism_spec.state_schema_id
    assert _self_hash(result) == result.content_hash
    assert [record.sequence_position for record in result.emissions] == [0, 1, 2, 3]
    assert [record.sequence_position for record in result.evidence] == [0, 1, 2, 3]
    for emission in result.emissions:
        assert _self_hash(emission) == emission.content_hash
    for evidence in result.evidence:
        assert _self_hash(evidence) == evidence.content_hash
    assert all(record.unit == "units" for record in result.emissions)


def test_dispatcher_executes_through_the_generic_seam(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    request = _request(pack)
    dispatched = dispatch_domain_mechanism_step(pack, request)
    assert dispatched.model_dump_json() == pack.step(request).model_dump_json()


def test_repeated_identical_requests_are_byte_identical(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    first = pack.step(_request(pack))
    second = pack.step(_request(pack))
    third = ConformanceStockFlowV01DomainPack().step(_request(pack))
    assert first.model_dump_json() == second.model_dump_json() == third.model_dump_json()


def test_request_and_result_are_neither_mutated_nor_aliased(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    request = _request(pack)
    before = request.model_dump_json()
    result = pack.step(request)
    assert request.model_dump_json() == before
    assert result.next_state_payload is not request.state_payload
    result.next_state_payload["level"] = 999
    result.emissions[0].payload["released"] = 999
    assert request.model_dump_json() == before
    again = pack.step(request)
    assert again.next_state_payload == {"level": 5}
    assert again.emissions[0].payload == {"quantity_id": "released", "released": 2}


# ---------------------------------------------------------------------------
# E. Mechanism
# ---------------------------------------------------------------------------


def _emitted(result: DomainMechanismStepResult) -> dict[str, object]:
    """The emitted quantity values keyed by quantity id."""
    values: dict[str, object] = {}
    for record in result.emissions:
        quantity_id = record.payload["quantity_id"]
        assert isinstance(quantity_id, str)
        values[quantity_id] = record.payload[quantity_id]
    return values


@pytest.mark.parametrize(
    ("level", "release", "released", "spilled", "shortfall", "next_level"),
    [
        # level 4 + inflow 3 = 7 available; release 2 -> remaining 5; no spill.
        (4, 2, 2, 0, 0, 5),
        # level 9 + 3 = 12; release 1 -> remaining 11; spill 11 - 10 = 1; next 10.
        (9, 1, 1, 1, 0, 10),
        # level 1 + 3 = 4; release 5 > 4 -> released 4; shortfall 1; next 0.
        (1, 5, 4, 0, 1, 0),
        # level 10 + 3 = 13; release 0 -> remaining 13; spill 3; next 10.
        (10, 0, 0, 3, 0, 10),
        # level 0 + 3 = 3; release 3 -> remaining 0; exact release.
        (0, 3, 3, 0, 0, 0),
    ],
)
def test_hand_calculated_fixtures(
    pack: ConformanceStockFlowV01DomainPack,
    level: int,
    release: int,
    released: int,
    spilled: int,
    shortfall: int,
    next_level: int,
) -> None:
    result = pack.step(_request(pack, {"level": level}, {"release": release}))
    assert result.next_state_payload == {"level": next_level}
    assert _emitted(result) == {
        "released": released,
        "spilled": spilled,
        "shortfall": shortfall,
        "next_level": next_level,
    }
    assert [record.payload["quantity_id"] for record in result.emissions] == [
        "released",
        "spilled",
        "shortfall",
        "next_level",
    ]
    conservation = result.evidence[2].payload
    assert conservation["level_before"] == level
    assert conservation["total_in"] == level + INFLOW
    assert conservation["total_out"] == next_level + released + spilled
    assert conservation["conservation_delta"] == 0
    assert result.evidence[3].payload == {
        "ordered_quantities": ["released", "spilled", "shortfall", "next_level"],
        "values": [released, spilled, shortfall, next_level],
    }


def test_exhaustive_small_grid_conserves_and_stays_in_bounds() -> None:
    cases = 0
    for capacity in range(1, 7):
        for level in range(0, capacity + 1):
            for inflow in range(0, 7):
                for max_release in range(0, 7):
                    for release in range(0, max_release + 1):
                        outcome = compute_transition(level, release, capacity, inflow)
                        cases += 1
                        assert (
                            level + inflow
                            == outcome.next_level + outcome.released + outcome.spilled
                        )
                        assert 0 <= outcome.next_level <= capacity
                        assert outcome.released >= 0
                        assert outcome.spilled >= 0
                        assert outcome.shortfall >= 0
                        assert outcome.released <= release
                        assert outcome.released <= level + inflow
                        assert outcome.released + outcome.shortfall == release
                        if outcome.spilled > 0:
                            assert outcome.next_level == capacity
                        if outcome.shortfall > 0:
                            assert outcome.released == level + inflow
    assert cases == sum((c + 1) for c in range(1, 7)) * 7 * sum((m + 1) for m in range(7))


# ---------------------------------------------------------------------------
# F. Fail-closed
# ---------------------------------------------------------------------------

_INVALID_NUMBERS: list[object] = [True, False, 1.0, 2.5, "3", "", None, -1, -(10**30)]


@pytest.mark.parametrize("value", _INVALID_NUMBERS)
def test_invalid_level_values_are_rejected(
    pack: ConformanceStockFlowV01DomainPack, value: object
) -> None:
    _expect_rejection(pack, {"level": value})
    with pytest.raises(ConformanceStockFlowError):
        validate_state_payload({"level": value}, {"capacity": CAPACITY})


@pytest.mark.parametrize("value", _INVALID_NUMBERS)
def test_invalid_release_values_are_rejected(
    pack: ConformanceStockFlowV01DomainPack, value: object
) -> None:
    _expect_rejection(pack, action_payload={"release": value})
    with pytest.raises(ConformanceStockFlowError):
        validate_action_payload({"release": value}, {"max_release": MAX_RELEASE})


def test_non_finite_numbers_never_pass_validation() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ConformanceStockFlowError):
            validate_state_payload({"level": value}, {"capacity": CAPACITY})
        with pytest.raises(ConformanceStockFlowError):
            validate_action_payload({"release": value}, {"max_release": MAX_RELEASE})


def test_oversized_values_are_rejected(pack: ConformanceStockFlowV01DomainPack) -> None:
    _expect_rejection(pack, {"level": 10**30})
    _expect_rejection(pack, {"level": CAPACITY + 1})
    _expect_rejection(pack, action_payload={"release": 10**30})
    _expect_rejection(pack, action_payload={"release": MAX_RELEASE + 1})


def test_level_at_capacity_and_release_at_max_release_are_accepted(
    pack: ConformanceStockFlowV01DomainPack,
) -> None:
    result = pack.step(_request(pack, {"level": CAPACITY}, {"release": MAX_RELEASE}))
    # available 13; release 5 -> remaining 8; no spill.
    assert result.next_state_payload == {"level": 8}


@pytest.mark.parametrize(
    "state",
    [{}, {"level": 1, "extra": 2}, {"Level": 1}, {"level": 1, "capacity": 10}],
)
def test_state_key_mismatches_are_rejected(
    pack: ConformanceStockFlowV01DomainPack, state: dict[str, object]
) -> None:
    _expect_rejection(pack, state)


@pytest.mark.parametrize(
    "action",
    [{}, {"release": 1, "extra": 2}, {"Release": 1}, {"release": 1, "max_release": 5}],
)
def test_action_key_mismatches_are_rejected(
    pack: ConformanceStockFlowV01DomainPack, action: dict[str, object]
) -> None:
    _expect_rejection(pack, action_payload=action)


@pytest.mark.parametrize(
    "mutation",
    [
        {"capacity": 11},
        {"capacity": 0},
        {"capacity": -1},
        {"capacity": True},
        {"capacity": 10.0},
        {"inflow": 4},
        {"inflow": -1},
        {"max_release": 6},
        {"max_release": "5"},
        {"unexpected": 1},
    ],
)
def test_changed_or_invalid_configuration_is_rejected(
    pack: ConformanceStockFlowV01DomainPack, mutation: dict[str, object]
) -> None:
    configuration: dict[str, object] = dict(pack.mechanism_spec.configuration)
    configuration.update(mutation)
    request = DomainMechanismStepRequest.model_validate(
        _request_payload(pack, configuration_payload=configuration)
    )
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_missing_configuration_key_is_rejected(pack: ConformanceStockFlowV01DomainPack) -> None:
    configuration = {"capacity": CAPACITY, "inflow": INFLOW}
    with pytest.raises(ConformanceStockFlowError):
        validate_configuration_payload(configuration, pack.mechanism_spec.configuration)
    _expect_rejection(pack, configuration_payload=configuration)


def test_non_empty_exogenous_input_is_rejected(pack: ConformanceStockFlowV01DomainPack) -> None:
    entry = MechanismExogenousInput(
        identifier="exogenous-1",
        stream="stream-1",
        variable="variable-1",
        entity_id="entity-1",
        draw_index=0,
        value_kind="integer",
        value=1,
        content_hash=_canonical_hash(1),
        world_version_id="world-stockflow-v1",
        world_content_hash="b" * 64,
        seed_id="seed-stockflow-1",
        seed_content_hash="c" * 64,
        run_id="run-stockflow-1",
        step_index=0,
    )
    payload = _request_payload(pack, exogenous_inputs=[entry.model_dump(mode="json")])
    request = DomainMechanismStepRequest.model_validate(payload)
    assert request.exogenous_inputs
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


@pytest.mark.parametrize(
    "field",
    [
        "mechanism_spec_id",
        "release_profile_id",
        "state_schema_id",
        "action_schema_id",
        "configuration_schema_id",
    ],
)
def test_foreign_identity_ids_are_rejected(
    pack: ConformanceStockFlowV01DomainPack, field: str
) -> None:
    payload = _request_payload(pack)
    payload[field] = "foreign-identity"
    request = DomainMechanismStepRequest.model_validate(_seal(payload))
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


@pytest.mark.parametrize(
    "field",
    [
        "mechanism_spec_content_hash",
        "release_profile_content_hash",
        "state_schema_hash",
        "action_schema_hash",
        "configuration_schema_hash",
        "state_hash",
        "action_hash",
        "configuration_hash",
    ],
)
def test_foreign_hashes_are_rejected(pack: ConformanceStockFlowV01DomainPack, field: str) -> None:
    payload = _request_payload(pack)
    assert payload[field] != _FAKE_HEX_64
    payload[field] = _FAKE_HEX_64
    request = DomainMechanismStepRequest.model_validate(_seal(payload))
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(pack, request)


def test_wrong_request_hash_is_rejected(pack: ConformanceStockFlowV01DomainPack) -> None:
    payload = _request_payload(pack)
    payload["content_hash"] = _FAKE_HEX_64
    try:
        request = DomainMechanismStepRequest.model_validate(payload)
    except ValidationError:
        return
    with pytest.raises(ConformanceStockFlowError):
        pack.step(request)


def test_non_request_objects_are_rejected(pack: ConformanceStockFlowV01DomainPack) -> None:
    class Impostor:
        pass

    with pytest.raises((ConformanceStockFlowError, AttributeError, TypeError)):
        pack.step(Impostor())  # type: ignore[arg-type]


def test_invalid_input_leaves_no_state_behind(pack: ConformanceStockFlowV01DomainPack) -> None:
    good = pack.step(_request(pack)).model_dump_json()
    _expect_rejection(pack, {"level": CAPACITY + 1})
    assert pack.step(_request(pack)).model_dump_json() == good


def _tamper_manifest(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.manifest = pack.manifest.model_copy(update={"pack_id": "other-pack"})


def _tamper_spec(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.mechanism_spec = pack.mechanism_spec.model_copy(update={"mechanism_id": "other"})


def _tamper_profile(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.release_profile = pack.release_profile.model_copy(update={"metadata": {"forged": True}})


def _tamper_protocol(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.mechanism_protocol_version = "2.0.0"  # type: ignore[assignment]


def _tamper_manifest_hash(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.manifest = pack.manifest.model_copy(update={"content_hash": _FAKE_HEX_64})


def _tamper_spec_hash(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.mechanism_spec = pack.mechanism_spec.model_copy(update={"content_hash": _FAKE_HEX_64})


def _tamper_profile_hash(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.release_profile = pack.release_profile.model_copy(update={"content_hash": _FAKE_HEX_64})


def _tamper_spec_contents_in_place(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.mechanism_spec.configuration["capacity"] = 99


def _replace_authority_with_foreign_type(pack: ConformanceStockFlowV01DomainPack) -> None:
    pack.manifest = object()  # type: ignore[assignment]


@pytest.mark.parametrize(
    "tamper",
    [
        _tamper_manifest,
        _tamper_spec,
        _tamper_profile,
        _tamper_protocol,
        _tamper_manifest_hash,
        _tamper_spec_hash,
        _tamper_profile_hash,
        _tamper_spec_contents_in_place,
        _replace_authority_with_foreign_type,
    ],
)
def test_tampered_authorities_fail_closed(
    tamper: Callable[[ConformanceStockFlowV01DomainPack], None],
) -> None:
    victim = ConformanceStockFlowV01DomainPack()
    request = _request(victim)
    tamper(victim)
    with pytest.raises(ConformanceStockFlowError):
        victim.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(victim, request)
    # A mutated pack never contaminates a fresh instance.
    fresh = ConformanceStockFlowV01DomainPack()
    assert fresh.step(_request(fresh)).next_state_payload == {"level": 5}


def _rehash_manifest(manifest: DomainPackManifest) -> DomainPackManifest:
    return manifest.model_copy(update={"content_hash": manifest_content_hash(manifest)})


def _forge_chain(
    pack: ConformanceStockFlowV01DomainPack,
    *,
    capacity: int | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    """Install a fully re-hashed, self-consistent forged authority chain."""
    manifest = pack.manifest
    spec = pack.mechanism_spec
    if capacity is not None:
        configuration = {**spec.configuration, "capacity": capacity}
        spec = spec.model_copy(
            update={
                "configuration": configuration,
                "configuration_hash": _canonical_hash(configuration),
            }
        )
    if metadata is not None:
        manifest = _rehash_manifest(manifest.model_copy(update={"metadata": metadata}))
        spec = spec.model_copy(update={"manifest_content_hash": manifest.content_hash})
    spec = spec.model_copy(update={"content_hash": _self_hash(spec)})
    profile = pack.release_profile.model_copy(
        update={
            "manifest": manifest,
            "manifest_content_hash": manifest.content_hash,
            "mechanism_spec": spec,
            "configuration_identity": spec.configuration_hash,
        }
    )
    profile = profile.model_copy(update={"content_hash": _self_hash(profile)})
    pack.manifest, pack.mechanism_spec, pack.release_profile = manifest, spec, profile


@pytest.mark.parametrize(
    "forgery",
    [{"capacity": 11}, {"metadata": {"synthetic_only": False}}],
)
def test_self_consistently_rehashed_forgery_fails_closed(forgery: dict[str, object]) -> None:
    victim = ConformanceStockFlowV01DomainPack()
    _forge_chain(victim, **forgery)  # type: ignore[arg-type]
    # The forged chain is internally self-consistent in every hash.
    assert manifest_content_hash(victim.manifest) == victim.manifest.content_hash
    assert _self_hash(victim.mechanism_spec) == victim.mechanism_spec.content_hash
    assert _self_hash(victim.release_profile) == victim.release_profile.content_hash
    assert victim.release_profile.manifest == victim.manifest
    assert victim.release_profile.mechanism_spec == victim.mechanism_spec
    # A request built against the forged chain is itself hash-consistent.
    request = _request(victim)
    with pytest.raises(ConformanceStockFlowError):
        victim.step(request)
    with pytest.raises(DomainMechanismDispatchError):
        dispatch_domain_mechanism_step(victim, request)


# ---------------------------------------------------------------------------
# G. Neutrality
# ---------------------------------------------------------------------------


def test_fixture_sources_contain_no_health_vocabulary() -> None:
    for name in FIXTURE_MODULES:
        source = (PACKAGE / name).read_text(encoding="utf-8")
        assert not _HEALTH_VOCABULARY.search(source), name


def test_generic_kernel_sources_contain_no_fixture_vocabulary() -> None:
    for path in sorted(KALHAS_ROOT.rglob("*.py")):
        relative = path.relative_to(KALHAS_ROOT).as_posix()
        if relative.startswith("domain_packs/"):
            continue
        source = path.read_text(encoding="utf-8")
        assert not _FIXTURE_VOCABULARY.search(source), f"fixture vocabulary in {relative}"
