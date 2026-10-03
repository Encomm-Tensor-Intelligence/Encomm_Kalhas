"""KALHAS-PAN: the minimal synthetic domain pack (H29-S04).

Dedicated, fully isolated subpackage of the concrete PAN v0.1
``DomainPack``.  Exposes exactly the concrete pack entry point
:class:`PanV01DomainPack`; nothing else is public.  The domain-neutral
kernel never imports this package, and no discovery, registration, or
runtime integration exists for it in this slice.
"""

from kalhas.domain_packs.pan.pack import PanV01DomainPack

__all__ = ["PanV01DomainPack"]
