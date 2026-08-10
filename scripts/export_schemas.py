"""Export JSON Schema artifacts for the public v1 contracts.

Usage (from the repository root):

    uv run python scripts/export_schemas.py           # write artifacts
    uv run python scripts/export_schemas.py --check   # verify artifacts are current

Artifacts are checked into ``schemas/v1/``. Never edit them by hand;
``tests/test_schema_sync.py`` fails when they drift from the models.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kalhas.contracts.schema_export import generate_schemas

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for filename, content in generate_schemas().items():
        path = SCHEMA_DIR / filename
        if check_only:
            if path.read_text(encoding="utf-8") != content:
                stale.append(filename)
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")
    if check_only:
        if stale:
            print("OUT OF SYNC: " + ", ".join(stale))
            return 1
        print("all schema artifacts are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
