"""The contract every future domain pack must satisfy.

The boundary is purely declarative: a domain pack's identity is its
``DomainPackManifest`` - metadata declaring the logical ``pack_id``, the
semantic ``pack_version``, the supported KALHAS API versions, and an
ordered list of declarative capabilities. There is no executable surface:
no method a pack must implement, nothing to load, import, instantiate, or
execute. KALHAS consumes packs only through this manifest and never
discovers packs dynamically.

No real domain pack ships in this phase; test-only generic fakes exist
solely inside tests to prove protocol conformance.
"""

from __future__ import annotations

from typing import Protocol

from kalhas.contracts.v1.domain_pack import DomainPackManifest


class DomainPack(Protocol):
    """Declarative identity of a future domain pack.

    A conforming object exposes exactly its ``DomainPackManifest``. The
    manifest is metadata: it never binds, loads, or executes domain
    behavior. Deterministic binding of a manifest to an immutable world
    version is a later phase.
    """

    manifest: DomainPackManifest
