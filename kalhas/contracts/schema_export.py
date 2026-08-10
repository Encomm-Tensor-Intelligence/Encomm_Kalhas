"""Deterministic JSON Schema export for public v1 contracts.

One artifact per top-level public contract. Artifacts are checked into
``schemas/v1/`` and must stay synchronized with the Pydantic models
(``tests/test_schema_sync.py`` enforces this). Nothing in this module runs
during normal application startup.
"""

from __future__ import annotations

import json

from kalhas.contracts.v1 import PUBLIC_CONTRACTS


def generate_schemas() -> dict[str, str]:
    """Render every public v1 contract as a JSON Schema document.

    Deterministic: keys are sorted, indentation is fixed, and the artifact
    set is ordered by the public contract registry.
    """
    schemas: dict[str, str] = {}
    for contract in PUBLIC_CONTRACTS:
        rendered = json.dumps(contract.model_json_schema(), indent=2, sort_keys=True) + "\n"
        schemas[f"{contract.__name__}.schema.json"] = rendered
    return schemas
