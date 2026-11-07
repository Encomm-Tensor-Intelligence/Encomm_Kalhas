"""Phase 30 boundary tests pinned to ADR-006 (H30-S01).

ADR-006 is the specification of the offline dataset intake and the
``RawDatasetManifest`` contract. Every boundary here stays additive-safe:
nothing asserts the absence of a later intake slice's artifacts.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"
ADR_PATH = (
    REPO_ROOT / "docs" / "decisions" / "ADR-006-offline-dataset-intake-and-raw-dataset-manifest.md"
)

_NEW_MODULES = (
    "contracts/v1/dataset.py",
    "application/raw_dataset_verifier.py",
    "application/raw_dataset_errors.py",
)

#: Whole-word domain vocabulary that must never appear in the neutral kernel
#: modules (identifiers or string literals).
_DOMAIN_WORDS = frozenset(
    {"pan", "pandemic", "covid", "hospital", "icu", "ecdc", "eurostat", "patient"}
)

_ALLOWED_EXACT_IMPORTS = frozenset(
    {
        "__future__",
        "typing",
        "collections.abc",
        "hashlib",
        "json",
        "math",
        "re",
        "datetime",
        "pydantic",
        "kalhas.application.hashing",
        "kalhas.application.domain_errors",
        "kalhas.application.raw_dataset_errors",
    }
)
_ALLOWED_IMPORT_PREFIXES = ("kalhas.contracts.v1.",)


def _adr_normalized() -> str:
    return re.sub(r"\s+", " ", ADR_PATH.read_text(encoding="utf-8")).lower()


def _words(text: str) -> set[str]:
    """Lowercase whole words of a text, splitting camelCase and underscores."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {word.lower() for word in re.findall(r"[A-Za-z]+", spaced)}


def test_adr006_is_accepted_and_dated() -> None:
    assert ADR_PATH.is_file(), "ADR-006 file is missing"
    normalized = _adr_normalized()
    assert "# adr 006: offline dataset intake and the raw-dataset manifest" in normalized
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-02" in normalized


def test_adr006_records_all_six_decisions() -> None:
    normalized = _adr_normalized()
    for heading in (
        "### d30-01a — offline, immutable, local bundles only",
        "### d30-01b — license classes and admissibility",
        "### d30-01c — raw-dataset manifest identity",
        "### d30-01d — checksum verification",
        "### d30-01e — vintages, lineage and holdout lock",
        "### d30-01f — first intended sources",
    ):
        assert heading in normalized, heading


def test_adr006_supersedes_nothing_and_claims_no_later_work() -> None:
    normalized = _adr_normalized()
    assert "this adr supersedes nothing" in normalized
    assert "must not be read as claiming any of them" in normalized


def test_adr006_freezes_the_manifest_name_license_classes_and_limits() -> None:
    normalized = _adr_normalized()
    assert "rawdatasetmanifest" in normalized
    assert "`public_domain`" in normalized
    assert "`attribution_commercial`" in normalized
    assert "only aggregate data is admissible" in normalized
    assert 'data_subject_level = "aggregate"' in normalized
    assert "25 mib" in normalized


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_carry_no_domain_vocabulary(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= _words(node.value)
        elif isinstance(node, ast.Name):
            found |= _words(node.id)
        elif isinstance(node, ast.Attribute):
            found |= _words(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found |= _words(node.name)
        elif isinstance(node, ast.arg):
            found |= _words(node.arg)
        elif isinstance(node, ast.alias):
            found |= _words(node.name)
            if node.asname:
                found |= _words(node.asname)
    assert not (found & _DOMAIN_WORDS), (relative, sorted(found & _DOMAIN_WORDS))


def test_domain_vocabulary_matching_is_whole_word() -> None:
    assert _words("expand the company span") & _DOMAIN_WORDS == set()
    assert _words("ICU_beds PatientRecord") & _DOMAIN_WORDS == {"icu", "patient"}


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_import_only_the_allowlist(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (relative, "relative import")
            names = [node.module or ""]
        else:
            continue
        for name in names:
            allowed = name in _ALLOWED_EXACT_IMPORTS or name.startswith(_ALLOWED_IMPORT_PREFIXES)
            assert allowed, (relative, name)


@pytest.mark.parametrize("relative", _NEW_MODULES)
def test_new_kernel_modules_never_use_clock_constructors(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow"}, (relative, node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            assert not {alias.name for alias in node.names} & {"datetime", "date", "time"}, relative


# --- ADR-007 and the curated-dataset modules (H30-S02A) ----------------------------------------

ADR007_PATH = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "ADR-007-curated-dataset-lineage-and-closed-transformation-plans.md"
)

_CURATED_MODULES = (
    "contracts/v1/curated_dataset.py",
    "application/dataset_transformation_engine.py",
    "application/curated_dataset_verifier.py",
    "application/dataset_transformation_errors.py",
)

_CURATED_ALLOWED_IMPORTS = _ALLOWED_EXACT_IMPORTS | {
    "csv",
    "io",
    "decimal",
    "kalhas.application.dataset_transformation_engine",
    "kalhas.application.dataset_transformation_errors",
    "kalhas.application.raw_dataset_verifier",
}

_OPERATIONS = (
    "decode_text",
    "parse_csv",
    "select_columns",
    "rename_columns",
    "filter_rows_in",
    "cast_columns",
    "require_unique_key",
    "sort_rows",
)


def _adr007_normalized() -> str:
    return re.sub(r"\s+", " ", ADR007_PATH.read_text(encoding="utf-8")).lower()


def test_adr007_is_accepted_and_dated() -> None:
    assert ADR007_PATH.is_file(), "ADR-007 file is missing"
    normalized = _adr007_normalized()
    assert "# adr 007: curated dataset lineage and closed transformation plans" in normalized
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-02" in normalized


def test_adr007_records_all_six_decisions() -> None:
    normalized = _adr007_normalized()
    for number in range(1, 7):
        assert f"### d30-01e-{number} \u2014 " in normalized, number


def test_adr007_supersedes_nothing_and_claims_no_later_work() -> None:
    normalized = _adr007_normalized()
    assert "this adr supersedes nothing" in normalized
    assert "must not be read as claiming any of them" in normalized


def test_adr007_freezes_the_manifest_vocabulary_and_tenant_namespace() -> None:
    normalized = _adr007_normalized()
    assert "curateddatasetmanifest" in normalized
    assert "closed vocabulary, version `1.0.0`" in normalized
    assert "`kalhas-reference`" in normalized
    for operation in _OPERATIONS:
        assert f"`{operation}`" in normalized, operation


@pytest.mark.parametrize("relative", _CURATED_MODULES)
def test_curated_modules_carry_no_domain_vocabulary(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= _words(node.value)
        elif isinstance(node, ast.Name):
            found |= _words(node.id)
        elif isinstance(node, ast.Attribute):
            found |= _words(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found |= _words(node.name)
        elif isinstance(node, ast.arg):
            found |= _words(node.arg)
        elif isinstance(node, ast.alias):
            found |= _words(node.name)
            if node.asname:
                found |= _words(node.asname)
    assert not (found & _DOMAIN_WORDS), (relative, sorted(found & _DOMAIN_WORDS))


@pytest.mark.parametrize("relative", _CURATED_MODULES)
def test_curated_modules_import_only_the_allowlist(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (relative, "relative import")
            names = [node.module or ""]
        else:
            continue
        for name in names:
            allowed = name in _CURATED_ALLOWED_IMPORTS or name.startswith(_ALLOWED_IMPORT_PREFIXES)
            assert allowed, (relative, name)


@pytest.mark.parametrize("relative", _CURATED_MODULES)
def test_curated_modules_use_only_the_date_type_from_datetime(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow"}, (relative, node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            assert {alias.name for alias in node.names} <= {"date"}, relative


# ADR-008 split boundaries
_SPLIT_MODULES = (
    "contracts/v1/dataset_split.py",
    "application/dataset_split_engine.py",
    "application/dataset_split_verifier.py",
    "application/dataset_split_errors.py",
)
_SPLIT_ALLOWED_IMPORTS = _CURATED_ALLOWED_IMPORTS | {
    "kalhas.application.curated_dataset_verifier",
    "kalhas.application.dataset_split_engine",
    "kalhas.application.dataset_split_errors",
}


def test_adr008_scope_and_decisions() -> None:
    path = REPO_ROOT / "docs/decisions/ADR-008-dataset-split-membership-and-holdout-lock.md"
    normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-03" in normalized
    for number in range(1, 6):
        assert f"### d30-02b-{number} — " in normalized
    for phrase in (
        "this adr supersedes nothing",
        "must not be read as claiming any of them",
        "datasetsplitmanifest",
        "`development`",
        "`validation`",
        "`holdout`",
        "`1.0.0`",
    ):
        assert phrase in normalized


@pytest.mark.parametrize("relative", _SPLIT_MODULES)
def test_split_modules_have_neutral_vocabulary(relative: str) -> None:
    test_curated_modules_carry_no_domain_vocabulary(relative)


@pytest.mark.parametrize("relative", _SPLIT_MODULES)
def test_split_modules_have_pure_imports(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name in _SPLIT_ALLOWED_IMPORTS or name.startswith(_ALLOWED_IMPORT_PREFIXES), (
                relative,
                name,
            )
    test_curated_modules_use_only_the_date_type_from_datetime(relative)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}, relative


# ADR-009 benchmark boundaries
_BENCHMARK_MODULES = (
    "contracts/v1/benchmark_protocol.py",
    "application/benchmark_task_engine.py",
    "application/benchmark_protocol_verifier.py",
    "application/benchmark_errors.py",
)
_BENCHMARK_ALLOWED_IMPORTS = _SPLIT_ALLOWED_IMPORTS | {
    "bisect",
    "dataclasses",
    "kalhas.application.benchmark_errors",
    "kalhas.application.benchmark_protocol_verifier",
    "kalhas.application.curated_dataset_verifier",
    "kalhas.application.dataset_split_verifier",
}


def test_adr009_scope_and_decisions() -> None:
    path = REPO_ROOT / "docs/decisions/ADR-009-benchmark-protocol-forecast-producers-and-scoring.md"
    normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-03" in normalized
    for number in range(1, 11):
        assert f"### d30-02-{number} — " in normalized
    for phrase in (
        "this adr supersedes nothing",
        "must not be read as claiming any of them",
        "benchmarkprotocol",
        "forecastset",
        "benchmarkscorereport",
        "kalhas-wis-k3-v1",
        "option a",
    ):
        assert phrase in normalized


@pytest.mark.parametrize("relative", _BENCHMARK_MODULES)
def test_benchmark_neutral_vocabulary(relative: str) -> None:
    test_curated_modules_carry_no_domain_vocabulary(relative)


@pytest.mark.parametrize("relative", _BENCHMARK_MODULES)
def test_benchmark_pure_imports(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
            if node.module == "datetime":
                assert {alias.name for alias in node.names} <= {"date", "timedelta"}
        else:
            names = []
        for name in names:
            assert name in _BENCHMARK_ALLOWED_IMPORTS or name.startswith(
                _ALLOWED_IMPORT_PREFIXES
            ), (relative, name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}


_FORECAST_MODULES = (
    "contracts/v1/benchmark_forecast.py",
    "application/benchmark_scoring.py",
    "application/benchmark_forecast_verifier.py",
    "application/benchmark_forecast_errors.py",
)
_FORECAST_ALLOWED_IMPORTS = _BENCHMARK_ALLOWED_IMPORTS | {
    "fractions",
    "csv",
    "io",
    "kalhas.application.benchmark_task_engine",
    "kalhas.application.benchmark_forecast_errors",
    "kalhas.application.benchmark_scoring",
}


def test_adr010_scope_and_decisions() -> None:
    path = (
        REPO_ROOT / "docs/decisions/ADR-010-declared-missing-rows-in-benchmark-task-derivation.md"
    )
    normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-03" in normalized
    for number in range(1, 5):
        assert f"### d30-02m-{number} — " in normalized
    assert "this adr supersedes nothing" in normalized
    assert "must not be read as claiming any of them" in normalized


@pytest.mark.parametrize("relative", _FORECAST_MODULES)
def test_forecast_modules_are_neutral_and_pure(relative: str) -> None:
    test_curated_modules_carry_no_domain_vocabulary(relative)
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            assert name in _FORECAST_ALLOWED_IMPORTS or name.startswith(_ALLOWED_IMPORT_PREFIXES)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
        if relative in {
            "application/benchmark_scoring.py",
            "application/benchmark_forecast_verifier.py",
        }:
            assert not (isinstance(node, ast.Name) and node.id == "float")
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
            assert all(name not in {"decimal", "math"} for name in names)


def test_baseline_module_boundaries() -> None:
    relative = "application/benchmark_baselines.py"
    test_curated_modules_carry_no_domain_vocabulary(relative)
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    allowed = {
        "__future__",
        "collections.abc",
        "datetime",
        "fractions",
        "kalhas.application.benchmark_errors",
        "kalhas.application.benchmark_forecast_errors",
        "kalhas.application.benchmark_forecast_verifier",
        "kalhas.application.benchmark_scoring",
        "kalhas.application.benchmark_task_engine",
        "kalhas.application.hashing",
        "kalhas.contracts.v1.benchmark_forecast",
        "kalhas.contracts.v1.benchmark_protocol",
        "kalhas.contracts.v1.curated_dataset",
        "kalhas.contracts.v1.dataset",
        "kalhas.contracts.v1.dataset_split",
        "kalhas.contracts.v1.shared",
    }
    forbidden = {
        "_input_rows",
        "_rows",
        "resolve_target_values",
        "select_partition_rows",
        "compute_split_membership",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
            assert not ({alias.name for alias in node.names} & forbidden)
        else:
            names = []
        assert all(name in allowed for name in names)
        if isinstance(node, ast.Name):
            assert node.id not in forbidden | {"float", "open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden | {"now", "today", "utcnow", "environ", "getenv"}
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))


def test_adr011_scope_and_decisions() -> None:
    path = REPO_ROOT / "docs/decisions/ADR-011-pan-authoring-and-multi-pathogen-evaluation.md"
    normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-05" in normalized
    for number in range(1, 11):
        assert f"### d30-04-{number} — " in normalized
    for phrase in (
        "this adr supersedes nothing",
        "must not be read as claiming any of them",
        "modelpackauthoringbinding",
        "`stock_sum`",
        "`flow_sum`",
        "`per_100k`",
        "`within_pathogen`",
        "`transfer`",
        "`unbenchmarked`",
    ):
        assert phrase in normalized


_AUTHORING_MODULES = (
    "contracts/v1/model_pack_authoring.py",
    "application/observation_operators.py",
    "application/model_pack_authoring_errors.py",
    "application/model_pack_authoring_verifier.py",
)
_AUTHORING_IMPORTS = {
    "__future__",
    "typing",
    "collections.abc",
    "dataclasses",
    "datetime",
    "fractions",
    "pydantic",
    "kalhas.application.benchmark_protocol_verifier",
    "kalhas.application.benchmark_task_engine",
    "kalhas.application.hashing",
    "kalhas.application.domain_errors",
    "kalhas.application.model_pack_authoring_errors",
    "kalhas.application.observation_operators",
    "kalhas.contracts.v1.benchmark_forecast",
    "kalhas.contracts.v1.benchmark_protocol",
    "kalhas.contracts.v1.curated_dataset",
    "kalhas.contracts.v1.dataset",
    "kalhas.contracts.v1.dataset_split",
    "kalhas.contracts.v1.domain_mechanism",
    "kalhas.contracts.v1.model_pack_authoring",
    "kalhas.contracts.v1.shared",
    "kalhas.contracts.v1.state_model",
    "kalhas.contracts.v1.world_realization",
}


@pytest.mark.parametrize("relative", _AUTHORING_MODULES)
def test_authoring_modules_are_neutral_and_pure(relative: str) -> None:
    test_new_kernel_modules_carry_no_domain_vocabulary(relative)
    source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
        else:
            names = []
        assert all(name in _AUTHORING_IMPORTS for name in names), (relative, names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
        if relative in {
            "application/observation_operators.py",
            "application/model_pack_authoring_verifier.py",
        }:
            assert not (isinstance(node, ast.Name) and node.id == "float")
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
            assert all(name not in {"decimal", "math"} for name in names)
    if relative == "application/model_pack_authoring_verifier.py":
        assert "holdout" not in source.lower()


_MECHANISM_FORECAST_MODULES = (
    "application/mechanism_forecast_errors.py",
    "application/mechanism_trajectory.py",
    "application/mechanism_forecasts.py",
)
_MECHANISM_FORECAST_IMPORTS = {
    "__future__",
    "typing",
    "collections.abc",
    "dataclasses",
    "datetime",
    "fractions",
    "re",
    "kalhas.application.benchmark_baselines",
    "kalhas.application.benchmark_errors",
    "kalhas.application.benchmark_forecast_verifier",
    "kalhas.application.benchmark_scoring",
    "kalhas.application.benchmark_task_engine",
    "kalhas.application.domain_errors",
    "kalhas.application.domain_mechanism_dispatcher",
    "kalhas.application.domain_mechanism_errors",
    "kalhas.application.hashing",
    "kalhas.application.mechanism_forecast_errors",
    "kalhas.application.mechanism_trajectory",
    "kalhas.application.model_pack_authoring_errors",
    "kalhas.application.model_pack_authoring_verifier",
    "kalhas.application.observation_operators",
    "kalhas.contracts.v1.benchmark_forecast",
    "kalhas.contracts.v1.benchmark_protocol",
    "kalhas.contracts.v1.curated_dataset",
    "kalhas.contracts.v1.dataset",
    "kalhas.contracts.v1.dataset_split",
    "kalhas.contracts.v1.domain_mechanism",
    "kalhas.contracts.v1.model_pack_authoring",
    "kalhas.contracts.v1.shared",
    "kalhas.domain_packs",
}


@pytest.mark.parametrize("relative", _MECHANISM_FORECAST_MODULES)
def test_mechanism_forecast_modules_are_neutral_and_pure(relative: str) -> None:
    test_new_kernel_modules_carry_no_domain_vocabulary(relative)
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
        else:
            names = []
        assert all(name in _MECHANISM_FORECAST_IMPORTS for name in names), (relative, names)
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "exec", "eval", "__import__", "float"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
            if relative == "application/mechanism_trajectory.py":
                assert node.attr != "step"
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        assert all(name not in {"decimal", "math"} for name in names)


def test_adr012_scope_and_decisions() -> None:
    path = REPO_ROOT / "docs/decisions/ADR-012-first-pan-binding-calibration-and-reexecution.md"
    normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
    assert "- status: accepted" in normalized
    assert "- date: 2026-11-06" in normalized
    for number in range(1, 11):
        assert f"### d30-05-{number} — " in normalized
    for phrase in (
        "this adr supersedes nothing",
        "must not be read as claiming any of them",
        "modelpackcalibrationrecord",
        "`kalhas-pan-initial-state-v1`",
        "`kalhas-grid-fitter-v1`",
        "no fast path",
    ):
        assert phrase in normalized


_CALIBRATION_MODULES = (
    "contracts/v1/model_pack_calibration.py",
    "application/grid_calibration.py",
    "application/grid_calibration_errors.py",
)
_CALIBRATION_IMPORTS = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "fractions",
    "hashlib",
    "re",
    "typing",
    "pydantic",
    "kalhas.application.benchmark_scoring",
    "kalhas.application.domain_errors",
    "kalhas.application.grid_calibration_errors",
    "kalhas.application.hashing",
    "kalhas.application.mechanism_forecasts",
    "kalhas.application.model_pack_authoring_verifier",
    "kalhas.contracts.v1.benchmark_forecast",
    "kalhas.contracts.v1.benchmark_protocol",
    "kalhas.contracts.v1.curated_dataset",
    "kalhas.contracts.v1.dataset",
    "kalhas.contracts.v1.dataset_split",
    "kalhas.contracts.v1.domain_mechanism",
    "kalhas.contracts.v1.model_pack_authoring",
    "kalhas.contracts.v1.model_pack_calibration",
    "kalhas.contracts.v1.shared",
    "kalhas.contracts.v1.state_model",
    "kalhas.contracts.v1.world_realization",
}


@pytest.mark.parametrize("relative", _CALIBRATION_MODULES)
def test_calibration_modules_are_neutral_and_pure(relative: str) -> None:
    test_new_kernel_modules_carry_no_domain_vocabulary(relative)
    source = (KALHAS_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names = [node.module or ""]
        else:
            names = []
        assert all(name in _CALIBRATION_IMPORTS for name in names), (relative, names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "today", "utcnow", "environ", "getenv"}
        if relative == "application/grid_calibration.py":
            assert not (isinstance(node, ast.Name) and node.id in {"float", "decimal", "math"})
