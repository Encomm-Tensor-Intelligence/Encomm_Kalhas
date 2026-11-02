"""Verify every committed raw dataset bundle against its manifest (offline).

Discovers ``datasets/v1/raw/<dataset_id>/<vintage>/manifest.json`` under the
repository root (or ``--root``), parses each manifest as a
``RawDatasetManifest``, requires the directory names to equal the manifest
identity, reads every other file of the bundle as relative POSIX path ->
bytes, and runs the pure ``verify_raw_dataset_bundle``. It only reads: it
never writes, never touches the network, and prints the bundle directory and
the bounded failure reason, never bytes.

Usage::

    uv run python scripts/verify_dataset_bundles.py --check
    uv run python scripts/verify_dataset_bundles.py --root <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kalhas.application.raw_dataset_errors import RawDatasetVerificationError
from kalhas.application.raw_dataset_verifier import verify_raw_dataset_bundle
from kalhas.contracts.v1.dataset import RawDatasetManifest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
RAW_RELATIVE = Path("datasets") / "v1" / "raw"


def _bundle_directories(root: Path) -> tuple[list[Path], list[str]]:
    """Return every ``<dataset_id>/<vintage>`` directory and structural failures."""
    raw_root = root / RAW_RELATIVE
    bundles: list[Path] = []
    failures: list[str] = []
    if not raw_root.is_dir():
        return bundles, failures
    for dataset_dir in sorted(raw_root.iterdir()):
        if not dataset_dir.is_dir():
            failures.append(f"FAIL {dataset_dir.relative_to(root).as_posix()}: unexpected_entry")
            continue
        for vintage_dir in sorted(dataset_dir.iterdir()):
            if not vintage_dir.is_dir():
                failures.append(
                    f"FAIL {vintage_dir.relative_to(root).as_posix()}: unexpected_entry"
                )
                continue
            bundles.append(vintage_dir)
    return bundles, failures


def _verify_bundle(root: Path, bundle: Path) -> str | None:
    """Return a bounded failure reason for one bundle, or ``None`` when it verifies."""
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        return "missing_manifest"
    try:
        manifest = RawDatasetManifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != manifest.dataset_id or bundle.name != manifest.vintage:
        return "identity_mismatch"
    files: dict[str, bytes] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        if relative == MANIFEST_NAME:
            continue
        files[relative] = path.read_bytes()
    try:
        verify_raw_dataset_bundle(manifest, files)
    except RawDatasetVerificationError as error:
        return error.reason
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only (the default and only behavior; this script never writes)",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()

    bundles, failures = _bundle_directories(root)
    if not bundles and not failures:
        print("no dataset bundles")
        return 0
    for bundle in bundles:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_bundle(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for line in failures:
        print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
