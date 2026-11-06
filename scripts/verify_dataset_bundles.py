"""Verify every committed dataset bundle against its manifest (offline).

Discovers raw bundles at ``datasets/v1/raw/<dataset_id>/<vintage>/`` and
curated bundles at ``datasets/v1/curated/<curated_dataset_id>/<version>/``
split bundles at ``datasets/v1/splits/<split_id>/<version>/``, and protocols
at ``benchmarks/v1/protocols/<protocol_id>/<version>/`` under the repository
root (or ``--root``). Each directory must hold a
``manifest.json`` whose identity equals the directory names.

- A raw manifest is parsed as a ``RawDatasetManifest`` and checked with the
  pure ``verify_raw_dataset_bundle`` against every other file of the bundle.
- A curated manifest is parsed as a ``CuratedDatasetManifest``; its
  referenced raw bundles are loaded from ``datasets/v1/raw/`` by parsing the
  raw manifest identifier, and the pure ``verify_curated_dataset_bundle``
  re-executes the plan against the raw bytes and the curated files.

- A split manifest is checked against its curated and raw input chain.
- A protocol is checked against its split, curated and raw input chain.
- Forecasts and reports are checked against their complete input chain;
  baseline forecasts are also verified by re-execution.

It only reads: it never writes, never touches the network, and prints the
bundle directory and the bounded failure reason, never bytes.

Usage::

    uv run python scripts/verify_dataset_bundles.py --check
    uv run python scripts/verify_dataset_bundles.py --root <path>
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from functools import cache
from pathlib import Path

from kalhas.application.benchmark_baselines import verify_baseline_forecast_set
from kalhas.application.benchmark_errors import BenchmarkProtocolVerificationError
from kalhas.application.benchmark_forecast_errors import (
    BenchmarkBaselineVerificationError,
    BenchmarkForecastVerificationError,
    BenchmarkScoreVerificationError,
)
from kalhas.application.benchmark_forecast_verifier import (
    verify_benchmark_score_report,
)
from kalhas.application.benchmark_protocol_verifier import verify_benchmark_protocol
from kalhas.application.curated_dataset_verifier import verify_curated_dataset_bundle
from kalhas.application.dataset_split_errors import (
    DatasetSplitVerificationError,
    SealedPartitionError,
)
from kalhas.application.dataset_split_verifier import verify_dataset_split
from kalhas.application.dataset_transformation_errors import CuratedDatasetVerificationError
from kalhas.application.model_pack_authoring_errors import ModelPackAuthoringVerificationError
from kalhas.application.model_pack_authoring_verifier import verify_model_pack_authoring_binding
from kalhas.application.raw_dataset_errors import RawDatasetVerificationError
from kalhas.application.raw_dataset_verifier import verify_raw_dataset_bundle
from kalhas.contracts.v1.benchmark_forecast import BenchmarkScoreReport, ForecastSet
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol
from kalhas.contracts.v1.curated_dataset import CuratedDatasetManifest
from kalhas.contracts.v1.dataset import RawDatasetManifest
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from kalhas.contracts.v1.model_pack_authoring import ModelPackAuthoringBinding
from kalhas.domain_packs.pan.binding_plan import parse_pan_binding_plan
from kalhas.domain_packs.pan.mechanism import PanDomainPackError
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
RAW_RELATIVE = Path("datasets") / "v1" / "raw"
CURATED_RELATIVE = Path("datasets") / "v1" / "curated"
SPLIT_RELATIVE = Path("datasets") / "v1" / "splits"
PROTOCOL_RELATIVE = Path("benchmarks") / "v1" / "protocols"
BINDING_RELATIVE = Path("benchmarks") / "v1" / "bindings"
FORECAST_RELATIVE = Path("benchmarks") / "v1" / "forecasts"
REPORT_RELATIVE = Path("benchmarks") / "v1" / "reports"
_PROTOCOL_IDENTIFIER = re.compile(
    r"benchmark-protocol-(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<version>\d+\.\d+\.\d+)"
)
_FORECAST_IDENTIFIER = re.compile(
    r"forecast-set-(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<version>\d+\.\d+\.\d+)"
)
_SPLIT_IDENTIFIER = re.compile(
    r"dataset-split-(?P<split_id>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<version>\d+\.\d+\.\d+)"
)
_CURATED_IDENTIFIER = re.compile(
    r"curated-dataset-(?P<dataset_id>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<version>\d+\.\d+\.\d+)"
)
_RAW_IDENTIFIER = re.compile(
    r"raw-dataset-(?P<dataset_id>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"-(?P<vintage>\d{4}-\d{2}-\d{2}(?:\.[1-9]\d*)?)"
)


def _bundle_directories(root: Path, relative: Path) -> tuple[list[Path], list[str]]:
    """Return every ``<id>/<version>`` directory under ``relative`` and structural failures."""
    base = root / relative
    bundles: list[Path] = []
    failures: list[str] = []
    if not base.is_dir():
        return bundles, failures
    for id_dir in sorted(base.iterdir()):
        if not id_dir.is_dir():
            failures.append(f"FAIL {id_dir.relative_to(root).as_posix()}: unexpected_entry")
            continue
        for version_dir in sorted(id_dir.iterdir()):
            if not version_dir.is_dir():
                failures.append(
                    f"FAIL {version_dir.relative_to(root).as_posix()}: unexpected_entry"
                )
                continue
            bundles.append(version_dir)
    return bundles, failures


def _read_files(bundle: Path) -> dict[str, bytes]:
    """Every file of a bundle except its top-level manifest, by relative POSIX path."""
    files: dict[str, bytes] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        if relative == MANIFEST_NAME:
            continue
        files[relative] = path.read_bytes()
    return files


def _load_raw(bundle: Path) -> tuple[RawDatasetManifest, dict[str, bytes]] | str:
    """Parse one raw bundle, or return a bounded failure reason."""
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        return "missing_manifest"
    try:
        manifest = RawDatasetManifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != manifest.dataset_id or bundle.name != manifest.vintage:
        return "identity_mismatch"
    return manifest, _read_files(bundle)


def _verify_raw(bundle: Path) -> str | None:
    loaded = _load_raw(bundle)
    if isinstance(loaded, str):
        return loaded
    manifest, files = loaded
    try:
        verify_raw_dataset_bundle(manifest, files)
    except RawDatasetVerificationError as error:
        return error.reason
    return None


def _verify_curated(root: Path, bundle: Path) -> str | None:
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        return "missing_manifest"
    try:
        manifest = CuratedDatasetManifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if (
        bundle.parent.name != manifest.curated_dataset_id
        or bundle.name != manifest.curation_version
    ):
        return "identity_mismatch"
    raw_bundles: dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]] = {}
    for reference in manifest.inputs:
        match = _RAW_IDENTIFIER.fullmatch(reference.raw_manifest_id)
        if match is None:
            return "raw_input_missing"
        raw_dir = root / RAW_RELATIVE / match.group("dataset_id") / match.group("vintage")
        loaded = _load_raw(raw_dir)
        if isinstance(loaded, str):
            return "raw_input_missing"
        raw_bundles[reference.raw_manifest_id] = loaded
    try:
        verify_curated_dataset_bundle(manifest, raw_bundles, _read_files(bundle))
    except CuratedDatasetVerificationError as error:
        return error.reason
    return None


def _verify_split(root: Path, bundle: Path) -> str | None:
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        return "missing_manifest"
    if any(path.name != MANIFEST_NAME for path in bundle.iterdir()):
        return "undeclared_file"
    try:
        split = DatasetSplitManifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != split.split_id or bundle.name != split.split_version:
        return "identity_mismatch"
    match = _CURATED_IDENTIFIER.fullmatch(split.curated_manifest_id)
    if match is None:
        return "curated_input_missing"
    curated_dir = root / CURATED_RELATIVE / match.group("dataset_id") / match.group("version")
    curated_path = curated_dir / MANIFEST_NAME
    if not curated_path.is_file():
        return "curated_input_missing"
    try:
        curated = CuratedDatasetManifest.model_validate_json(curated_path.read_bytes())
    except ValidationError:
        return "curated_input_invalid"
    if curated.curated_dataset_id != match.group(
        "dataset_id"
    ) or curated.curation_version != match.group("version"):
        return "curated_input_invalid"
    raw_bundles: dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]] = {}
    for reference in curated.inputs:
        raw_match = _RAW_IDENTIFIER.fullmatch(reference.raw_manifest_id)
        if raw_match is None:
            return "curated_input_invalid"
        raw_dir = root / RAW_RELATIVE / raw_match.group("dataset_id") / raw_match.group("vintage")
        loaded = _load_raw(raw_dir)
        if isinstance(loaded, str):
            return "curated_input_invalid"
        raw_bundles[reference.raw_manifest_id] = loaded
    try:
        verify_dataset_split(split, curated, _read_files(curated_dir), raw_bundles)
    except DatasetSplitVerificationError as error:
        return error.reason
    return None


def _verify_protocol(root: Path, bundle: Path) -> str | None:
    path = bundle / MANIFEST_NAME
    if not path.is_file():
        return "missing_manifest"
    if any(entry.name != MANIFEST_NAME for entry in bundle.iterdir()):
        return "undeclared_file"
    try:
        protocol = BenchmarkProtocol.model_validate_json(path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != protocol.protocol_id or bundle.name != protocol.protocol_version:
        return "identity_mismatch"
    split_match = _SPLIT_IDENTIFIER.fullmatch(protocol.split_manifest_id)
    if split_match is None:
        return "split_input_missing"
    split_dir = root / SPLIT_RELATIVE / split_match.group("split_id") / split_match.group("version")
    split_path = split_dir / MANIFEST_NAME
    if not split_path.is_file():
        return "split_input_missing"
    if any(entry.name != MANIFEST_NAME for entry in split_dir.iterdir()):
        return "split_input_invalid"
    try:
        split = DatasetSplitManifest.model_validate_json(split_path.read_bytes())
    except ValidationError:
        return "split_input_invalid"
    if split.split_id != split_match.group("split_id") or split.split_version != split_match.group(
        "version"
    ):
        return "split_input_invalid"
    curated_match = _CURATED_IDENTIFIER.fullmatch(split.curated_manifest_id)
    if curated_match is None:
        return "split_input_invalid"
    curated_dir = (
        root / CURATED_RELATIVE / curated_match.group("dataset_id") / curated_match.group("version")
    )
    curated_path = curated_dir / MANIFEST_NAME
    if not curated_path.is_file():
        return "split_input_invalid"
    try:
        curated = CuratedDatasetManifest.model_validate_json(curated_path.read_bytes())
    except ValidationError:
        return "split_input_invalid"
    if curated.curated_dataset_id != curated_match.group(
        "dataset_id"
    ) or curated.curation_version != curated_match.group("version"):
        return "split_input_invalid"
    raw_bundles: dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]] = {}
    for reference in curated.inputs:
        match = _RAW_IDENTIFIER.fullmatch(reference.raw_manifest_id)
        if match is None:
            return "split_input_invalid"
        loaded = _load_raw(root / RAW_RELATIVE / match.group("dataset_id") / match.group("vintage"))
        if isinstance(loaded, str):
            return "split_input_invalid"
        raw_bundles[reference.raw_manifest_id] = loaded
    try:
        verify_benchmark_protocol(protocol, split, curated, _read_files(curated_dir), raw_bundles)
    except BenchmarkProtocolVerificationError as error:
        return error.reason
    return None


@cache
def _protocol_chain(
    root: Path, identifier: str
) -> (
    tuple[
        BenchmarkProtocol,
        DatasetSplitManifest,
        CuratedDatasetManifest,
        dict[str, bytes],
        dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]],
    ]
    | str
):
    match = _PROTOCOL_IDENTIFIER.fullmatch(identifier)
    if match is None:
        return "protocol_input_missing"
    directory = root / PROTOCOL_RELATIVE / match.group("id") / match.group("version")
    if not (directory / MANIFEST_NAME).is_file():
        return "protocol_input_missing"
    if _verify_protocol(root, directory) is not None:
        return "protocol_input_invalid"
    try:
        protocol = BenchmarkProtocol.model_validate_json((directory / MANIFEST_NAME).read_bytes())
        split_match = _SPLIT_IDENTIFIER.fullmatch(protocol.split_manifest_id)
        if split_match is None:
            return "protocol_input_invalid"
        split_dir = (
            root / SPLIT_RELATIVE / split_match.group("split_id") / split_match.group("version")
        )
        split = DatasetSplitManifest.model_validate_json((split_dir / MANIFEST_NAME).read_bytes())
        curated_match = _CURATED_IDENTIFIER.fullmatch(split.curated_manifest_id)
        if curated_match is None:
            return "protocol_input_invalid"
        curated_dir = (
            root
            / CURATED_RELATIVE
            / curated_match.group("dataset_id")
            / curated_match.group("version")
        )
        curated = CuratedDatasetManifest.model_validate_json(
            (curated_dir / MANIFEST_NAME).read_bytes()
        )
        raw: dict[str, tuple[RawDatasetManifest, Mapping[str, bytes]]] = {}
        for reference in curated.inputs:
            raw_match = _RAW_IDENTIFIER.fullmatch(reference.raw_manifest_id)
            if raw_match is None:
                return "protocol_input_invalid"
            loaded = _load_raw(
                root / RAW_RELATIVE / raw_match.group("dataset_id") / raw_match.group("vintage")
            )
            if isinstance(loaded, str):
                return "protocol_input_invalid"
            raw[reference.raw_manifest_id] = loaded
        return protocol, split, curated, _read_files(curated_dir), raw
    except (OSError, ValidationError):
        return "protocol_input_invalid"


def _verify_binding(root: Path, bundle: Path) -> str | None:
    path = bundle / MANIFEST_NAME
    if not path.is_file():
        return "missing_manifest"
    if any(entry.name != MANIFEST_NAME for entry in bundle.iterdir()):
        return "undeclared_file"
    try:
        binding = ModelPackAuthoringBinding.model_validate_json(path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != binding.binding_id or bundle.name != binding.binding_version:
        return "identity_mismatch"
    chain = _protocol_chain(root, binding.protocol_manifest_id)
    if isinstance(chain, str):
        return chain
    try:
        verify_model_pack_authoring_binding(binding, *chain)
    except ModelPackAuthoringVerificationError as error:
        return error.reason
    if binding.pack_id != "kalhas-pan":
        return "unknown_pack"
    try:
        parse_pan_binding_plan(binding)
    except PanDomainPackError:
        return "pack_payload_invalid"
    return None


def _load_forecast(bundle: Path) -> tuple[ForecastSet, bytes] | str:
    path = bundle / MANIFEST_NAME
    if not path.is_file():
        return "missing_manifest"
    if any(
        entry.name not in {MANIFEST_NAME, "forecasts.csv"} or not entry.is_file()
        for entry in bundle.iterdir()
    ):
        return "undeclared_file"
    if not (bundle / "forecasts.csv").is_file():
        return "missing_forecasts_file"
    try:
        item = ForecastSet.model_validate_json(path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != item.forecast_set_id or bundle.name != item.forecast_set_version:
        return "identity_mismatch"
    return item, (bundle / "forecasts.csv").read_bytes()


@cache
def _verify_forecast(root: Path, bundle: Path) -> str | None:
    loaded = _load_forecast(bundle)
    if isinstance(loaded, str):
        return loaded
    item, content = loaded
    chain = _protocol_chain(root, item.protocol_manifest_id)
    if isinstance(chain, str):
        return chain
    try:
        if item.producer.kind == "baseline":
            verify_baseline_forecast_set(item, content, *chain)
        else:
            return "mechanism_reexecution_unavailable"
    except SealedPartitionError:
        return "sealed_partition"
    except (BenchmarkForecastVerificationError, BenchmarkBaselineVerificationError) as error:
        return error.reason
    return None


def _verify_report(root: Path, bundle: Path) -> str | None:
    path = bundle / MANIFEST_NAME
    if not path.is_file():
        return "missing_manifest"
    if any(entry.name != MANIFEST_NAME or not entry.is_file() for entry in bundle.iterdir()):
        return "undeclared_file"
    try:
        report = BenchmarkScoreReport.model_validate_json(path.read_bytes())
    except ValidationError:
        return "invalid_manifest"
    if bundle.parent.name != report.report_id or bundle.name != report.report_version:
        return "identity_mismatch"
    if report.partition == "holdout":
        return "sealed_partition"
    chain = _protocol_chain(root, report.protocol_manifest_id)
    if isinstance(chain, str):
        return chain
    forecasts = []
    for identifier in (report.candidate_forecast_set_id, report.reference_forecast_set_id):
        match = _FORECAST_IDENTIFIER.fullmatch(identifier)
        if match is None:
            return "forecast_input_missing"
        directory = root / FORECAST_RELATIVE / match.group("id") / match.group("version")
        if not (directory / MANIFEST_NAME).is_file():
            return "forecast_input_missing"
        if _verify_forecast(root, directory) is not None:
            return "forecast_input_invalid"
        loaded = _load_forecast(directory)
        if isinstance(loaded, str):
            return "forecast_input_invalid"
        forecasts.append(loaded)
    try:
        verify_benchmark_score_report(report, *forecasts[0], *forecasts[1], *chain)
    except SealedPartitionError:
        return "sealed_partition"
    except BenchmarkScoreVerificationError as error:
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

    raw_bundles, failures = _bundle_directories(root, RAW_RELATIVE)
    curated_bundles, curated_failures = _bundle_directories(root, CURATED_RELATIVE)
    failures += curated_failures
    split_bundles, split_failures = _bundle_directories(root, SPLIT_RELATIVE)
    failures += split_failures
    protocols, protocol_failures = _bundle_directories(root, PROTOCOL_RELATIVE)
    failures += protocol_failures
    bindings, binding_failures = _bundle_directories(root, BINDING_RELATIVE)
    failures += binding_failures
    forecasts, forecast_failures = _bundle_directories(root, FORECAST_RELATIVE)
    reports, report_failures = _bundle_directories(root, REPORT_RELATIVE)
    if (
        not raw_bundles
        and not curated_bundles
        and not split_bundles
        and not protocols
        and not bindings
        and not forecasts
        and not reports
        and not failures
        and not forecast_failures
        and not report_failures
    ):
        print("no dataset bundles")
        return 0
    for bundle in raw_bundles:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_raw(bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for bundle in curated_bundles:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_curated(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for bundle in split_bundles:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_split(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for bundle in protocols:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_protocol(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for bundle in bindings:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_binding(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            failures.append(f"FAIL {name}: {reason}")
    for line in failures:
        print(line)
    for bundle in forecasts:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_forecast(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            forecast_failures.append(f"FAIL {name}: {reason}")
    for line in forecast_failures:
        print(line)
    for bundle in reports:
        name = bundle.relative_to(root).as_posix()
        reason = _verify_report(root, bundle)
        if reason is None:
            print(f"ok {name}")
        else:
            report_failures.append(f"FAIL {name}: {reason}")
    for line in report_failures:
        print(line)
    return 1 if failures or forecast_failures or report_failures else 0


if __name__ == "__main__":
    sys.exit(main())
