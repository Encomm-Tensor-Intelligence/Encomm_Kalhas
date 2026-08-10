"""Tests that checked-in JSON Schema artifacts stay synchronized with models."""

from __future__ import annotations

import json
from pathlib import Path

from kalhas.contracts.schema_export import generate_schemas

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"


def test_artifact_set_matches_public_contracts() -> None:
    generated = set(generate_schemas())
    on_disk = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert generated == on_disk


def test_artifacts_are_synchronized_with_models() -> None:
    for filename, content in generate_schemas().items():
        path = SCHEMA_DIR / filename
        assert path.read_text(encoding="utf-8") == content, (
            f"{filename} is out of sync - run: uv run python scripts/export_schemas.py"
        )


def test_artifacts_are_strict_json_schemas() -> None:
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["type"] == "object"
        assert "properties" in schema
        assert schema["additionalProperties"] is False
        assert schema["title"] == path.name.removesuffix(".schema.json")


def test_campaign_spec_schema_has_no_run_multiplicity_field() -> None:
    schema = json.loads((SCHEMA_DIR / "CampaignSpec.schema.json").read_text(encoding="utf-8"))
    assert "runs_per_strategy" not in schema["properties"]


def test_world_and_run_plan_schemas_enforce_sha256_hash_pattern() -> None:
    world = json.loads((SCHEMA_DIR / "WorldVersion.schema.json").read_text(encoding="utf-8"))
    run_plan = json.loads((SCHEMA_DIR / "RunPlan.schema.json").read_text(encoding="utf-8"))
    assert world["properties"]["content_hash"]["pattern"] == "^[0-9a-f]{64}$"
    assert run_plan["properties"]["input_hash"]["pattern"] == "^[0-9a-f]{64}$"
