"""The contract every future domain pack must satisfy.

The boundary is declarative. A domain pack's identity is its
``DomainPackManifest`` - metadata declaring the logical ``pack_id``, the
semantic ``pack_version``, the supported KALHAS API versions, and an
ordered list of declarative capabilities - and, since ADR-005 (D29-01),
an executable pack additionally exposes its exact ``ModelPackReleaseProfile``
release identity, the frozen mechanism protocol version ``1.0.0``, and
exactly one pure ``step(request) -> result`` operation. KALHAS consumes
packs only through this protocol and never discovers packs dynamically.

A legacy object carrying only a ``DomainPackManifest`` remains valid inert
metadata, but it is not an executable DomainPack: missing executable
identity (the release profile, the mechanism protocol version, or the
step operation) fails closed and nothing silently promotes inert metadata
into executable behavior.

No real domain pack ships in this phase; test-only generic fakes exist
solely inside tests to prove protocol conformance.
"""

from __future__ import annotations

from typing import Literal, Protocol

from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile


class DomainPack(Protocol):
    """Declarative identity of a future domain pack.

    A conforming object exposes exactly its ``DomainPackManifest``, its
    exact ``ModelPackReleaseProfile`` release identity, the frozen
    mechanism protocol version, and exactly one pure ``step`` operation
    (ADR-005, D29-01/D29-02). The manifest and the release profile are
    metadata: they never bind, load, or execute domain behavior by
    themselves, and ``step`` is a pure transition with no side effects.
    Deterministic binding of a manifest to an immutable world version is
    a later phase.
    """

    manifest: DomainPackManifest
    release_profile: ModelPackReleaseProfile
    mechanism_protocol_version: Literal["1.0.0"]

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        """The single pure mechanism transition."""
        ...
