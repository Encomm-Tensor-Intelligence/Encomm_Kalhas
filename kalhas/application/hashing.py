"""Canonical JSON and SHA-256 helpers for deterministic pipelines.

Safe infrastructure abstraction: no domain logic, no I/O, no randomness.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(payload: object) -> str:
    """Render payload as canonical JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
