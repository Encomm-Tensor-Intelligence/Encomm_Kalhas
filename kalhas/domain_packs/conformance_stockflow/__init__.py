"""KALHAS conformance stock-flow: the synthetic non-health fixture (H29-S07).

Dedicated, fully isolated subpackage of the concrete conformance
``DomainPack`` fixture that proves domain neutrality of the generic
mechanism seam. Exposes exactly the concrete entry point
:class:`ConformanceStockFlowV01DomainPack`; nothing else is public. The
domain-neutral kernel never imports this package, and no discovery,
registration, or runtime integration exists for it.
"""

from kalhas.domain_packs.conformance_stockflow.pack import ConformanceStockFlowV01DomainPack

__all__ = ["ConformanceStockFlowV01DomainPack"]
