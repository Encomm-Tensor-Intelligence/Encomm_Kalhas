"""KALHAS - the domain-neutral kernel.

KALHAS owns versioned world models, uncertainty, deterministic simulation
campaigns, evidence, replay, and the future living-simulation experience.

Phase 0 ships only the domain-neutral foundation and a minimal standalone
API. The kernel must never import NEXUS or LEGION internals.
"""

from kalhas.version import __version__

__all__ = ["__version__"]
