"""Domain pack registry contracts: declarative pack manifests and bindings.

A ``DomainPackManifest`` is **metadata, never executable code**. It declares
the identity of a future domain pack (stable manifest identifier, logical
``pack_id``, semantic ``pack_version``), the KALHAS API versions the pack
supports (API version ``1`` is mandatory), and an ordered list of declarative
capabilities with their ordered declared inputs and outputs.

A ``DomainPackBinding`` is the immutable, tenant-scoped link between one
registered manifest and one scenario: it snapshots the manifest's identity
(pack id, pack version, content hash) and its ordered capability identifiers
so that every ``WorldVersion`` compiled from that scenario carries the exact
binding set. Binding identity fields are always copied from the registered
immutable manifest - never from client input.

A ``DomainCapabilityDeclaration`` is the immutable, tenant-scoped set of
declared input values for one capability of a manifest already bound to a
scenario. It is a **generic declared fact/configuration input** for future
domain mechanisms: the values are JSON-compatible key/value data keyed by the
capability's declared ``input_ids``. Declarations are inert - nothing here
interprets schemas, executes a capability, invokes code, calculates outputs,
or produces decision evidence. All pack identity fields (``pack_id``,
``pack_version``, ``manifest_content_hash``), the ``binding_id``, and the
deterministic declaration identifier are copied from stored immutable
records - never from client input.

Nothing here loads, imports, instantiates, or executes a pack. Capability
metadata is descriptive only: no callbacks, imports, executable expressions,
provider references, or runtime behavior can be expressed by these field
types. The ``content_hash`` is a lowercase 64-character SHA-256 digest of the
canonical serialized declaration content **excluding ``content_hash``
itself**; a client-supplied hash is never authoritative (the declaration API
has no hash input field).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalhas.contracts.v1.shared import (
    AwareDatetime,
    JsonValue,
    VersionedContract,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_API_VERSION_PATTERN = r"^\d+$"
API_VERSION = "1"

ApiVersionNumber = Annotated[str, Field(pattern=_API_VERSION_PATTERN)]


class DomainPackCapability(BaseModel):
    """A declarative capability of a domain pack.

    Descriptive only: the capability declares its identifier, a concise
    description, and the ordered identifiers of its declared inputs and
    outputs. There are no callbacks, imports, executable expressions,
    provider references, or runtime behavior - the fields are plain strings,
    ordered tuples of strings, and JSON-compatible metadata.

    ``input_ids`` and ``output_ids`` are ordered identifiers and each must
    be unique within its tuple: duplicate input identifiers would make the
    exact key matching of declared ``input_values`` ambiguous, and
    duplicate output identifiers would make declared outputs ambiguous.
    The declared tuple order is preserved exactly as given.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: str
    description: str
    input_ids: tuple[str, ...] = Field(default_factory=tuple)
    output_ids: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_input_ids(self) -> DomainPackCapability:
        if len(self.input_ids) != len(set(self.input_ids)):
            raise ValueError("input_ids must be unique")
        return self

    @model_validator(mode="after")
    def _unique_output_ids(self) -> DomainPackCapability:
        if len(self.output_ids) != len(set(self.output_ids)):
            raise ValueError("output_ids must be unique")
        return self


class DomainPackManifest(VersionedContract):
    """The declarative identity of a future domain pack.

    A registered manifest is immutable: the contract is frozen and the
    registry rejects duplicate manifest identifiers per tenant. The manifest
    carries the logical ``pack_id``, a human-readable ``name``, a strict
    semantic ``pack_version`` (``major.minor.patch``), the supported KALHAS
    API versions (API version ``1`` is required), a non-empty ordered list of
    declarative capabilities, JSON-compatible schema metadata, a
    deterministic ``content_hash``, a deterministic ``created_at``, and
    optional JSON-compatible metadata.

    The content hash is computed over the canonical serialized manifest
    content excluding ``content_hash`` itself; it is never accepted from a
    client. Capability identifiers must be unique within the manifest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: str
    name: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    description: str | None = None
    supported_api_versions: tuple[ApiVersionNumber, ...] = Field(min_length=1)
    capabilities: tuple[DomainPackCapability, ...] = Field(min_length=1)
    schema_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    created_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _requires_api_version_1(self) -> DomainPackManifest:
        if API_VERSION not in self.supported_api_versions:
            raise ValueError("supported_api_versions must include API version 1")
        return self

    @model_validator(mode="after")
    def _unique_capability_identifiers(self) -> DomainPackManifest:
        capability_ids = [capability.identifier for capability in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability identifiers must be unique")
        return self


class DomainPackBinding(VersionedContract):
    """An immutable, tenant-scoped binding of a manifest to a scenario.

    The binding is a declarative snapshot: it copies the registered
    manifest's identity (``pack_id``, ``pack_version``, content hash) and
    its ordered capability identifiers exactly, so every ``WorldVersion``
    compiled from the scenario carries the precise binding set. All pack
    identity and hash fields originate exclusively from the stored
    immutable ``DomainPackManifest`` - never from client input (the
    binding API accepts only ``manifest_id`` and ``bound_at``).

    The binding is frozen by contract, is never updated, deleted, replaced,
    or unbound, and does not load, instantiate, import, or execute any
    domain pack. ``bound_at`` is supplied explicitly and becomes part of
    the immutable binding; the binding identifier is deterministic.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    manifest_id: str
    pack_id: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    capability_ids: tuple[str, ...] = Field(min_length=1)
    bound_at: AwareDatetime

    @model_validator(mode="after")
    def _unique_capability_ids(self) -> DomainPackBinding:
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError("capability_ids must be unique")
        return self


class DomainCapabilityDeclaration(VersionedContract):
    """Immutable declared input values for one bound capability.

    A declaration is the tenant-scoped, immutable set of declared
    key/value input values for exactly one capability of a manifest that is
    already bound to the scenario. It is a generic declared fact or
    configuration input for future domain mechanisms - it is **inert**: it
    never interprets capability schemas beyond identifier matching, never
    executes a capability, never invokes code, never calculates outputs, and
    never produces metrics or decision evidence.

    Every identity field is copied from stored immutable records: the
    scenario, binding, and manifest identifiers, the logical ``pack_id`` and
    semantic ``pack_version``, and the authoritative manifest content hash
    all come from the stored ``DomainPackManifest`` and ``DomainPackBinding``
    - never from client input (the declaration API accepts only
    ``manifest_id``, ``capability_id``, ``input_values``, and
    ``declared_at``). The declaration identifier is deterministically hash
    derived from the canonical scenario, manifest, and capability identity
    inputs, and the declaration ``content_hash`` is the SHA-256 digest of the
    canonical serialized declaration content excluding ``content_hash``
    itself.

    The declaration is frozen by contract and is never updated, deleted,
    replaced, or re-declared; a duplicate declaration is rejected and never
    overwrites the original.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    binding_id: str
    manifest_id: str
    pack_id: str
    pack_version: str = Field(pattern=_SEMVER_PATTERN)
    manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    capability_id: str
    input_values: dict[str, JsonValue] = Field(default_factory=dict)
    content_hash: str = Field(pattern=_SHA256_PATTERN)
    declared_at: AwareDatetime
