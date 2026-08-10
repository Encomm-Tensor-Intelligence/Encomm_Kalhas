"""Domain packs.

Future domain packs live here. The kernel must remain domain-neutral: it
never imports domain-pack internals and knows packs only through the
``DomainPack`` protocol.
"""

from kalhas.domain_packs.base import DomainPack

__all__ = ["DomainPack"]
