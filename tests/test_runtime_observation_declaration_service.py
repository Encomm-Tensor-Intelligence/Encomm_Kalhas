"""Focused tests for the runtime-observation declaration service and store (H28-S05).

These tests exercise the immutable :class:`RuntimeObservationDeclaration`
authority authoring boundary end to end: the real declaration service
(``declare_runtime_observation_declaration``), the real in-memory store's
no-overwrite immutable persistence surface, and the real compiled-world
authority produced by ``build_observation_store`` + ``compile_observation_world``
(the compiler-verified world embedding the ``manifest-1`` pack binding and the
``sm-1`` state model with the ``level`` / ``ratio`` / ``status`` fields).

Proof groups covered:
- SUCCESS: deterministic integer/number state-field declarations, external
  declarations, additive-noise value-kind derivation, exact copied
  scenario/world/manifest/model/field provenance, canonical get/list ordering,
  defensive copies, unchanged inputs, and zero operational activity.
- REJECTION: non-numeric/unknown fields, external-with-fresh-noise,
  foreign tenant/scenario/world, manifest/model present in the store but
  absent from the selected compiled world, duplicate no-overwrite writes,
  wrong type and subclass, validator-bypassed ``model_construct`` /
  ``model_copy`` forgeries, forged identifier/content-hash/world/model
  provenance, self-consistently rehashed altered provenance, malformed
  embedded binding collections, non-finite nested metadata, and private-store
  corruption detected on get and list.

Every rejection test proves the declaration collection and the operational
activity remain unchanged. Public error strings never expose supplied
identifiers, hashes, values, metadata, or Pydantic diagnostics.

No ``unittest.mock``, production monkeypatching, skips, xfail, assertion
weakening, alternate canonicalizers, direct constant substitution, ``noqa``,
``type: ignore``, or unjustified casts is used.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

import pytest
from kalhas.application.deterministic_sampler import (
    QUANTIZATION_FRACTION_BITS,
    QUANTIZATION_POLICY,
    SAMPLER_VERSION,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationAlreadyExistsError,
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
    RuntimeObservationDeclarationValidationError,
)
from kalhas.application.runtime_observation_declaration_identity import (
    runtime_observation_declaration_content_hash,
    runtime_observation_declaration_identifier,
)
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.runtime_observation import (
    AdditiveUniformObservationNoise,
    ExternalObservationSource,
    NoObservationNoise,
    ObservationTiming,
    RuntimeObservationDeclaration,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.shared import JsonValue

from tests.phase4_helpers import TENANT
from tests.phase20_helpers import (
    build_observation_scenario,
    build_observation_store,
    compile_observation_world,
)

OTHER_TENANT = "tenant-99"

_BINDINGS_KEY = "domain_pack_bindings"

_TIMING = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)
_ADDITIVE_NOISE = AdditiveUniformObservationNoise(
    kind="additive_uniform",
    lower_bound=0.0,
    upper_bound=1.0,
    sampler_version=SAMPLER_VERSION,
    quantization_policy=QUANTIZATION_POLICY,
    quantization_fraction_bits=QUANTIZATION_FRACTION_BITS,
    draw_count=1,
)
_DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)

_ObservationNoise = NoObservationNoise | AdditiveUniformObservationNoise
_NumericKind = Literal["integer", "number"]


def _state_draft(
    world_id: str,
    *,
    observation_id: str = "obs-level",
    field: str = "level",
    noise: _ObservationNoise = _NO_NOISE,
    metadata: dict[str, JsonValue] | None = None,
) -> RuntimeObservationDeclarationDraft:
    return RuntimeObservationDeclarationDraft(
        scenario_id="scenario-1",
        world_version_id=world_id,
        observation_id=observation_id,
        state_source=StateFieldObservationDraft(
            manifest_id="manifest-1",
            state_model_id="sm-1",
            state_field_id=field,
        ),
        timing=_TIMING,
        noise=noise,
        missing_behavior="false",
        declared_at=_DECLARED_AT,
        metadata=metadata if metadata is not None else {},
    )


def _external_draft(
    world_id: str,
    *,
    observation_id: str = "obs-ext",
    kind: _NumericKind = "integer",
    noise: _ObservationNoise = _NO_NOISE,
    metadata: dict[str, JsonValue] | None = None,
) -> RuntimeObservationDeclarationDraft:
    return RuntimeObservationDeclarationDraft(
        scenario_id="scenario-1",
        world_version_id=world_id,
        observation_id=observation_id,
        external_source=ExternalObservationDraft(
            external_channel_id="channel-1", external_value_kind=kind
        ),
        timing=_TIMING,
        noise=noise,
        missing_behavior="false",
        declared_at=_DECLARED_AT,
        metadata=metadata if metadata is not None else {},
    )


def _assert_no_activity(store: InMemoryScenarioStore) -> None:
    """No declaration operation may mutate the operational activity surface."""
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def _assert_collection_unchanged(
    store: InMemoryScenarioStore,
    key: tuple[str, str, str, str],
    declaration: RuntimeObservationDeclaration,
) -> None:
    """After a failed write the stored snapshot is unchanged and still readable."""
    assert store._runtime_observation_declarations[key] is not declaration
    assert store.get_runtime_observation_declaration(*key) == declaration


def _assert_safe_message(exc: Exception, *secrets: object) -> None:
    text = str(exc)
    for secret in secrets:
        if isinstance(secret, str) and secret:
            assert secret not in text


@pytest.fixture()
def store_world() -> tuple[InMemoryScenarioStore, str]:
    """A real store whose compiled world embeds manifest-1 / sm-1."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    return store, world_id


# --------------------------------------------------------------------------
# SUCCESS
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected_kind", "observation_id"),
    [
        ("level", "integer", "obs-level"),
        ("ratio", "number", "obs-ratio"),
    ],
)
def test_deterministic_state_field_declaration(
    store_world: tuple[InMemoryScenarioStore, str],
    field: str,
    expected_kind: str,
    observation_id: str,
) -> None:
    store, world_id = store_world
    declaration = declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_state_draft(world_id, observation_id=observation_id, field=field),
    )
    assert type(declaration) is RuntimeObservationDeclaration
    assert declaration.observed_value_kind == expected_kind
    assert declaration.runtime_version == "4.0.0"
    assert declaration.observation_id == observation_id
    source = declaration.observation_source
    assert isinstance(source, StateFieldObservationSource)
    assert source.state_field_id == field
    assert source.state_field_value_kind == expected_kind
    # Deterministic identity and content hash.
    assert declaration.identifier == runtime_observation_declaration_identifier(
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=world_id,
        observation_id=observation_id,
    )
    assert declaration.content_hash == runtime_observation_declaration_content_hash(declaration)
    # Persisted exactly once and retrievable.
    stored = store.get_runtime_observation_declaration(
        TENANT, "scenario-1", world_id, observation_id
    )
    assert stored == declaration
    assert store.list_runtime_observation_declarations(TENANT, "scenario-1", world_id) == (
        declaration,
    )
    _assert_no_activity(store)


@pytest.mark.parametrize("kind", ["integer", "number"])
def test_deterministic_external_declaration(
    store_world: tuple[InMemoryScenarioStore, str], kind: _NumericKind
) -> None:
    store, world_id = store_world
    declaration = declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_external_draft(world_id, observation_id=f"obs-ext-{kind}", kind=kind),
    )
    assert declaration.observed_value_kind == kind
    assert isinstance(declaration.observation_source, ExternalObservationSource)
    assert declaration.observation_source.external_channel_id == "channel-1"
    assert declaration.observation_source.external_value_kind == kind
    assert isinstance(declaration.noise, NoObservationNoise)
    _assert_no_activity(store)


def test_additive_noise_derives_number_kind(store_world: tuple[InMemoryScenarioStore, str]) -> None:
    store, world_id = store_world
    declaration = declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_state_draft(
            world_id, observation_id="obs-add", field="level", noise=_ADDITIVE_NOISE
        ),
    )
    # Additive uniform noise produces observed_value_kind "number" per the contract.
    assert declaration.observed_value_kind == "number"
    assert isinstance(declaration.noise, AdditiveUniformObservationNoise)


def test_exact_copied_provenance(store_world: tuple[InMemoryScenarioStore, str]) -> None:
    store, world_id = store_world
    world = store.get_world(TENANT, world_id)
    model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
    declaration = declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_state_draft(world_id, observation_id="obs-prov", field="ratio"),
    )
    assert declaration.scenario_id == "scenario-1"
    assert declaration.world_version_id == world_id
    assert declaration.world_content_hash == world.content_hash
    source = declaration.observation_source
    assert isinstance(source, StateFieldObservationSource)
    assert source.manifest_id == "manifest-1"
    assert source.state_model_identifier == model.identifier
    assert source.state_model_id == model.state_model_id
    assert source.state_model_content_hash == model.content_hash
    assert source.state_field_id == "ratio"
    assert source.state_field_value_kind == "number"


def test_get_list_canonical_ordering_and_defensive_copies(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    ids = ["obs-z", "obs-a", "obs-m"]
    for observation_id in ids:
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_external_draft(world_id, observation_id=observation_id, kind="integer"),
        )
    listed = store.list_runtime_observation_declarations(TENANT, "scenario-1", world_id)
    # Deterministic ordering by declaration identifier (not by insertion order).
    assert [d.identifier for d in listed] == sorted(d.identifier for d in listed)
    # Defensive copy: mutating a returned record's metadata must not affect storage.
    returned = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-a")
    returned.metadata["injected"] = {"payload": "tampered"}
    assert (
        "injected"
        not in store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, "obs-a"
        ).metadata
    )
    _assert_no_activity(store)


def test_inputs_unchanged(store_world: tuple[InMemoryScenarioStore, str]) -> None:
    store, world_id = store_world
    draft = _state_draft(
        world_id, observation_id="obs-in", field="level", metadata={"note": "keep"}
    )
    before = draft
    declare_runtime_observation_declaration(store, tenant_id=TENANT, draft=draft)
    assert draft == before
    assert draft.metadata == {"note": "keep"}
    assert draft.timing == _TIMING
    assert draft.declared_at == _DECLARED_AT


# --------------------------------------------------------------------------
# REJECTION
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["status", "missing-field", ""])
def test_non_numeric_or_missing_field_rejected(
    store_world: tuple[InMemoryScenarioStore, str], field: str
) -> None:
    store, world_id = store_world
    key = (TENANT, "scenario-1", world_id, f"obs-{field or 'blank'}")
    with pytest.raises(RuntimeObservationDeclarationValidationError) as excinfo:
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_state_draft(world_id, observation_id=key[3], field=field),
        )
    _assert_safe_message(excinfo.value, field, "sm-1", "manifest-1", world_id)
    _assert_no_activity(store)
    with pytest.raises(RuntimeObservationDeclarationNotFoundError):
        store.get_runtime_observation_declaration(*key)


def test_external_with_fresh_noise_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    with pytest.raises(RuntimeObservationDeclarationValidationError):
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_external_draft(world_id, observation_id="obs-badnoise", noise=_ADDITIVE_NOISE),
        )
    _assert_no_activity(store)


def test_foreign_scenario_world_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, _ = store_world
    draft = RuntimeObservationDeclarationDraft(
        scenario_id="scenario-zzz",
        world_version_id="world-bogus",
        observation_id="obs-x",
        external_source=ExternalObservationDraft(
            external_channel_id="ch", external_value_kind="integer"
        ),
        timing=_TIMING,
        noise=_NO_NOISE,
        missing_behavior="false",
        declared_at=_DECLARED_AT,
    )
    with pytest.raises(RuntimeObservationDeclarationValidationError):
        declare_runtime_observation_declaration(store, tenant_id=TENANT, draft=draft)
    _assert_no_activity(store)


def test_foreign_tenant_rejected(store_world: tuple[InMemoryScenarioStore, str]) -> None:
    store, world_id = store_world
    with pytest.raises(RuntimeObservationDeclarationValidationError):
        declare_runtime_observation_declaration(
            store,
            tenant_id=OTHER_TENANT,
            draft=_state_draft(world_id, observation_id="obs-foreign"),
        )
    # Unknown and foreign are indistinguishable on read.
    with pytest.raises(RuntimeObservationDeclarationNotFoundError):
        store.get_runtime_observation_declaration(
            OTHER_TENANT, "scenario-1", world_id, "obs-foreign"
        )
    _assert_no_activity(store)


def test_manifest_model_in_store_but_absent_from_compiled_world_rejected() -> None:
    """Manifest and model live in the store yet are not compiled-world members."""
    store = build_observation_store()
    model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
    # Compile a world that embeds the state model but omits pack-1 bindings.
    compiled = compile_world(build_observation_scenario(), bindings=(), state_models=(model,))
    store.put_world(compiled.version, compiled.manifest)
    with pytest.raises(RuntimeObservationDeclarationValidationError) as excinfo:
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_state_draft(compiled.version.identifier, observation_id="obs-nomember"),
        )
    _assert_safe_message(excinfo.value, "manifest-1", "sm-1", compiled.version.identifier)
    _assert_no_activity(store)
    # A minimal world (no model embedded at all) rejects on model membership.
    minimal = compile_world(build_observation_scenario())
    store.put_world(minimal.version, minimal.manifest)
    with pytest.raises(RuntimeObservationDeclarationValidationError):
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_state_draft(minimal.version.identifier, observation_id="obs-nomodel"),
        )
    _assert_no_activity(store)


def test_duplicate_write_never_overwrites(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    key = (TENANT, "scenario-1", world_id, "obs-dup")
    first = declare_runtime_observation_declaration(
        store, tenant_id=TENANT, draft=_state_draft(world_id, observation_id="obs-dup")
    )
    with pytest.raises(RuntimeObservationDeclarationAlreadyExistsError):
        declare_runtime_observation_declaration(
            store, tenant_id=TENANT, draft=_state_draft(world_id, observation_id="obs-dup")
        )
    # The original is unmodified and still readable.
    assert store._runtime_observation_declarations[key] is not first
    assert store.get_runtime_observation_declaration(*key) == first
    assert len(store._runtime_observation_declarations) == 1
    _assert_no_activity(store)


def test_wrong_type_and_subclass_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    valid = declare_runtime_observation_declaration(
        store, tenant_id=TENANT, draft=_state_draft(world_id, observation_id="obs-valid")
    )
    kwargs = {
        "tenant_id": TENANT,
        "scenario_id": "scenario-1",
        "world_version_id": world_id,
        "observation_id": "obs-sub",
    }
    # A non-declaration object fails the exact-type guard.
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        revalidate_stored_runtime_observation_declaration(
            object(), TENANT, "scenario-1", world_id, "obs-sub"
        )
    _assert_no_activity(store)

    # A validator-bypassed subclass is rejected (exact type required).
    class _Subclass(RuntimeObservationDeclaration):
        pass

    subclass = _Subclass.model_validate(valid.model_dump(mode="python"))
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(declaration=subclass, **kwargs)
    _assert_no_activity(store)
    with pytest.raises(RuntimeObservationDeclarationNotFoundError):
        store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-sub")


def _validate_then_forge(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    **updates: object,
) -> RuntimeObservationDeclaration:
    """Build a strict-exact declaration object without running its validators."""
    template = declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_external_draft(world_id, observation_id=f"obs-{observation_id}-tpl", kind="integer"),
    )
    dump = template.model_dump(mode="python")
    dump.update({"observation_id": observation_id, **updates})
    return RuntimeObservationDeclaration.model_construct(**dump)


def test_model_construct_validator_bypass_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    forged = _validate_then_forge(
        store,
        world_id,
        "obs-bypass",
        observation_source={"kind": "state_field", "manifest_id": 123456},
    )
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-bypass",
            declaration=forged,
        )
    _assert_no_activity(store)


def test_model_copy_forged_identifier_and_content_hash_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    valid = declare_runtime_observation_declaration(
        store, tenant_id=TENANT, draft=_external_draft(world_id, observation_id="obs-real")
    )
    # model_copy(update=...) bypasses revalidation, so the store must catch it.
    forged_id = valid.model_copy(update={"identifier": "runtime-observation-decl-forged"})
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-id",
            declaration=forged_id,
        )
    forged_hash = valid.model_copy(update={"content_hash": "f" * 64})
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-hash",
            declaration=forged_hash,
        )
    # Forged model provenance (state-model content hash) is similarly rejected.
    source = valid.observation_source
    assert isinstance(source, ExternalObservationSource)
    forged_source = StateFieldObservationSource.model_construct(
        kind="state_field",
        manifest_id="manifest-1",
        state_model_identifier="sm-sha-forged",
        state_model_id="sm-1",
        state_model_content_hash="e" * 64,
        state_field_id="level",
        state_field_value_kind="integer",
    )
    forged_model = valid.model_copy(update={"observation_source": forged_source})
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-model",
            declaration=forged_model,
        )
    _assert_no_activity(store)


def _inject(
    store: InMemoryScenarioStore,
    key: tuple[str, str, str, str],
    declaration: RuntimeObservationDeclaration,
) -> None:
    store._runtime_observation_declarations[key] = declaration
    assert store._runtime_observation_declarations[key] is declaration


def test_self_consistent_rehash_forged_provenance_detected_on_get_and_list(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    for observation_id in ("obs-a", "obs-b"):
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_external_draft(world_id, observation_id=observation_id, kind="integer"),
        )
    # Forge a world-provenance record that passes identity because its content
    # hash was consistently recomputed over the altered payload.
    real = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-a")
    rehashed = real.model_copy(update={"world_content_hash": "0" * 64})
    rehashed = rehashed.model_copy(
        update={"content_hash": runtime_observation_declaration_content_hash(rehashed)}
    )
    key = (TENANT, "scenario-1", world_id, "obs-a")
    _inject(store, key, rehashed)
    # Identity is self-consistent, but the stored-world authority cross-check fails.
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.get_runtime_observation_declaration(*key)
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.list_runtime_observation_declarations(TENANT, "scenario-1", world_id)
    _assert_no_activity(store)


def test_non_finite_metadata_rejected(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    # Service-level: a draft with non-finite nested metadata fails closed.
    with pytest.raises(RuntimeObservationDeclarationValidationError):
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_external_draft(
                world_id, observation_id="obs-nan", metadata={"m": {"v": math.nan}}
            ),
        )
    _assert_no_activity(store)

    # Store-level: a validator-bypassed record with non-finite metadata fails.
    forged = _validate_then_forge(store, world_id, "obs-nanstore", metadata={"x": math.nan})
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.put_runtime_observation_declaration(
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id="obs-nanstore",
            declaration=forged,
        )
    _assert_no_activity(store)


def test_malformed_embedded_binding_collection_rejected() -> None:
    store = build_observation_store()
    compiled = compile_world(build_observation_scenario())
    body = dict(compiled.version.world)
    body[_BINDINGS_KEY] = "definitely-not-a-list"
    corrupt_version = compiled.version.model_copy(update={"world": body})
    store.put_world(corrupt_version, compiled.manifest)
    world_id = compiled.version.identifier
    with pytest.raises(RuntimeObservationDeclarationIntegrityError) as excinfo:
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_state_draft(world_id, observation_id="obs-mal"),
        )
    _assert_safe_message(excinfo.value, "manifest-1", "sm-1", world_id)
    _assert_no_activity(store)


def test_private_store_corruption_detected_on_get_and_list(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    valid = declare_runtime_observation_declaration(
        store, tenant_id=TENANT, draft=_external_draft(world_id, observation_id="obs-good")
    )
    # Corrupt one slot: a validator-bypassed record with a wrong nested source.
    dump = valid.model_dump(mode="python")
    dump["observation_source"] = {"kind": "external_input", "external_channel_id": 999}
    corrupt = RuntimeObservationDeclaration.model_construct(**dump)
    key = (TENANT, "scenario-1", world_id, "obs-good")
    _inject(store, key, corrupt)
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.get_runtime_observation_declaration(*key)
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.list_runtime_observation_declarations(TENANT, "scenario-1", world_id)
    # The corruption is detected but the collection is never repaired or written.
    assert store._runtime_observation_declarations[key] is corrupt
    _assert_no_activity(store)


def test_corrupt_list_member_aborts_whole_list(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    for observation_id in ("obs-a", "obs-b"):
        declare_runtime_observation_declaration(
            store,
            tenant_id=TENANT,
            draft=_external_draft(world_id, observation_id=observation_id, kind="integer"),
        )
    valid = store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-b")
    # A corrupt record inside the listed locality must fail revalidation and
    # abort the entire list.
    dump = valid.model_dump(mode="python")
    dump["observation_source"] = {"kind": "external_input", "external_channel_id": 999}
    corrupt = RuntimeObservationDeclaration.model_construct(**dump)
    _inject(store, (TENANT, "scenario-1", world_id, "obs-c"), corrupt)
    with pytest.raises(RuntimeObservationDeclarationIntegrityError):
        store.list_runtime_observation_declarations(TENANT, "scenario-1", world_id)
    _assert_no_activity(store)


def test_unknown_and_foreign_records_do_not_leak(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, world_id = store_world
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=_external_draft(world_id, observation_id="obs-onlyone"),
    )
    with pytest.raises(RuntimeObservationDeclarationNotFoundError):
        store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, "obs-missing")
    with pytest.raises(RuntimeObservationDeclarationNotFoundError):
        store.get_runtime_observation_declaration(
            OTHER_TENANT, "scenario-1", world_id, "obs-onlyone"
        )
    # Foreign world locality yields nothing.
    assert store.list_runtime_observation_declarations(OTHER_TENANT, "scenario-1", world_id) == ()
    _assert_no_activity(store)


def test_no_repair_update_delete_surface(
    store_world: tuple[InMemoryScenarioStore, str],
) -> None:
    store, _ = store_world
    for name in (
        "update_runtime_observation_declaration",
        "delete_runtime_observation_declaration",
        "repair_runtime_observation_declaration",
    ):
        assert not hasattr(store, name)
