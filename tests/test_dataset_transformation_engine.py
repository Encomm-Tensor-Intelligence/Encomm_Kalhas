"""Tests for the pure closed dataset transformation engine (Phase 30, H30-S02A)."""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest
from kalhas.application.dataset_transformation_engine import (
    derive_transformation_output_columns,
    execute_transformation_plan,
)
from kalhas.application.dataset_transformation_errors import DatasetTransformationError
from kalhas.contracts.v1.curated_dataset import TransformationPlan
from kalhas.contracts.v1.dataset import RawDatasetManifest

from tests.test_curated_dataset_contracts import (
    GOLDEN_OUTPUT,
    RAW_CSV,
    RAW_FILES,
    build_raw_manifest,
    golden_plan,
    raw_bundles_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
KALHAS_ROOT = REPO_ROOT / "kalhas"

Spec = list[tuple[str, str, str, tuple[str, ...]]]


def _spec(*names: str, **overrides: tuple[str, str, tuple[str, ...]]) -> Spec:
    """Column specs ``(name, value_type, unit, missing_tokens)``; default string/none/()."""
    result: Spec = []
    for name in names:
        value_type, unit, tokens = overrides.get(name, ("string", "none", ()))
        result.append((name, value_type, unit, tokens))
    return result


def _raw(csv_bytes: bytes, spec: Spec) -> RawDatasetManifest:
    columns = [
        {"name": n, "value_type": t, "unit": u, "missing_tokens": list(m)} for n, t, u, m in spec
    ]
    first = spec[0][0]
    return build_raw_manifest(
        files=[
            {
                "path": "source.csv",
                "byte_size": len(csv_bytes),
                "sha256": hashlib.sha256(csv_bytes).hexdigest(),
                "media_type": "text/csv",
                "columns": columns,
            }
        ],
        time_basis={
            "calendar": "iso_date",
            "granularity": "day",
            "time_columns": [first],
            "time_semantics": "observation_date",
        },
        geography_basis={"scheme": "synthetic", "geography_columns": [first]},
    )


def _plan(raw: RawDatasetManifest, steps: list[dict[str, Any]], encoding: str = "utf-8") -> Any:
    return TransformationPlan.model_validate(
        {
            "vocabulary_version": "1.0.0",
            "outputs": [
                {
                    "output_path": "out.csv",
                    "source_manifest_id": raw.identifier,
                    "source_path": "source.csv",
                    "steps": [
                        {"op": "decode_text", "encoding": encoding},
                        {"op": "parse_csv"},
                        *steps,
                    ],
                }
            ],
        }
    )


def _run(
    csv_bytes: bytes, spec: Spec, steps: list[dict[str, Any]], encoding: str = "utf-8"
) -> bytes:
    raw = _raw(csv_bytes, spec)
    plan = _plan(raw, steps, encoding)
    return execute_transformation_plan(plan, raw_bundles_for(raw, {"source.csv": csv_bytes}))[
        "out.csv"
    ]


def _reason(
    csv_bytes: bytes, spec: Spec, steps: list[dict[str, Any]], encoding: str = "utf-8"
) -> str:
    with pytest.raises(DatasetTransformationError) as excinfo:
        _run(csv_bytes, spec, steps, encoding)
    return excinfo.value.reason


# --- golden plan -----------------------------------------------------------------------------


def test_golden_multi_step_plan_has_byte_exact_output() -> None:
    raw = build_raw_manifest()
    plan = TransformationPlan.model_validate(golden_plan())
    outputs = execute_transformation_plan(plan, raw_bundles_for(raw))
    assert outputs == {"clean.csv": GOLDEN_OUTPUT}
    assert repr(outputs["clean.csv"]) == (
        "b'region,period,total\\nr1,2020-W01,5\\nr1,2020-W02,\\nr3,2021-W01,7\\n'"
    )
    assert not outputs["clean.csv"].startswith(b"\xef\xbb\xbf")
    assert b"\r" not in outputs["clean.csv"]


def test_output_column_declarations_follow_the_plan() -> None:
    raw = build_raw_manifest()
    plan = TransformationPlan.model_validate(golden_plan())
    columns = derive_transformation_output_columns(plan, raw_bundles_for(raw))["clean.csv"]
    assert [(c.name, c.value_type, c.unit, c.missing_tokens) for c in columns] == [
        ("region", "string", "none", ()),
        ("period", "iso_week", "none", ()),
        ("total", "integer", "persons", ("",)),
    ]


# --- decode / parse --------------------------------------------------------------------------


def test_utf8_sig_removes_the_bom_and_plain_utf8_fails_the_header_check() -> None:
    spec = _spec("a", "b")
    bom = b"\xef\xbb\xbfa,b\n1,2\n"
    assert _run(bom, spec, [], "utf-8-sig") == b"a,b\n1,2\n"
    assert _reason(bom, spec, [], "utf-8") == "header_mismatch"


def test_invalid_utf8_fails_to_decode() -> None:
    assert _reason(b"a,b\n\xff,2\n", _spec("a", "b"), []) == "decode_failed"


def test_header_must_equal_the_declared_columns_in_order() -> None:
    assert _reason(b"b,a\n1,2\n", _spec("a", "b"), []) == "header_mismatch"
    assert _reason(b"a\n1\n", _spec("a", "b"), []) == "header_mismatch"


def test_an_empty_source_has_no_header() -> None:
    raw = _raw(b"a,b" + bytes([10]), _spec("a", "b"))
    plan = _plan(raw, [])
    with pytest.raises(DatasetTransformationError) as excinfo:
        execute_transformation_plan(plan, raw_bundles_for(raw, {"source.csv": b""}))
    assert excinfo.value.reason == "header_mismatch"


def test_a_ragged_row_fails() -> None:
    assert _reason(b"a,b\n1,2\n3\n", _spec("a", "b"), []) == "row_width_mismatch"
    assert _reason(b"a,b\n1,2,3\n", _spec("a", "b"), []) == "row_width_mismatch"
    assert _reason(b"a,b\n1,2\n\n", _spec("a", "b"), []) == "row_width_mismatch"


def test_malformed_quoting_fails_closed() -> None:
    assert _reason(b'a,b\n"x"y,2\n', _spec("a", "b"), []) == "parse_failed"


def test_quoting_is_minimal_and_crlf_is_normalised_to_lf() -> None:
    source = b'a,b\r\n"x,y","line\r\nbreak"\r\nplain,"q""uote"\r\n'
    assert _run(source, _spec("a", "b"), []) == (b'a,b\n"x,y","line\r\nbreak"\nplain,"q""uote"\n')


def test_a_header_only_file_yields_a_header_only_output() -> None:
    assert _run(b"a,b\n", _spec("a", "b"), []) == b"a,b\n"


# --- select / rename / filter ----------------------------------------------------------------


def test_select_columns_fixes_the_output_order_and_drops_the_rest() -> None:
    assert (
        _run(
            b"a,b,c\n1,2,3\n",
            _spec("a", "b", "c"),
            [{"op": "select_columns", "columns": ["c", "a"]}],
        )
        == b"c,a\n3,1\n"
    )


def test_unknown_columns_fail() -> None:
    spec = _spec("a", "b")
    for step in (
        {"op": "select_columns", "columns": ["zzz"]},
        {"op": "rename_columns", "mapping": {"zzz": "x"}},
        {"op": "filter_rows_in", "column": "zzz", "values": ["1"]},
        {"op": "cast_columns", "types": {"zzz": "integer"}},
        {"op": "require_unique_key", "columns": ["zzz"]},
        {"op": "sort_rows", "columns": ["zzz"]},
    ):
        assert _reason(b"a,b\n1,2\n", spec, [step]) == "unknown_column", step


def test_rename_applies_simultaneously_and_rejects_collisions() -> None:
    spec = _spec("a", "b")
    swap = {"op": "rename_columns", "mapping": {"a": "b", "b": "a"}}
    assert _run(b"a,b\n1,2\n", spec, [swap]) == b"b,a\n1,2\n"
    collide = {"op": "rename_columns", "mapping": {"a": "b"}}
    assert _reason(b"a,b\n1,2\n", spec, [collide]) == "duplicate_column"


def test_filter_rows_in_matches_the_raw_text_exactly() -> None:
    spec = _spec("a", "b", b=("string", "none", ("NA",)))
    source = b"a,b\nx,1\ny,NA\nz,2\nw,na\n"
    keep = {"op": "filter_rows_in", "column": "b", "values": ["NA", "2"]}
    assert _run(source, spec, [keep]) == b"a,b\ny,\nz,2\n"


# --- missing tokens --------------------------------------------------------------------------


def test_missing_tokens_survive_as_empty_cells() -> None:
    spec = _spec("a", "b", b=("string", "none", ("NA", "-")))
    assert _run(b"a,b\n1,NA\n2,-\n3,x\n", spec, []) == b"a,b\n1,\n2,\n3,x\n"


def test_a_literal_empty_cell_in_a_column_with_other_tokens_is_ambiguous() -> None:
    spec = _spec("a", "b", b=("string", "none", ("NA",)))
    assert _reason(b"a,b\n1,NA\n2,\n", spec, []) == "ambiguous_missing"


def test_an_empty_token_column_keeps_empty_cells_empty() -> None:
    spec = _spec("a", "b", b=("string", "none", ("",)))
    assert _run(b"a,b\n1,\n2,x\n", spec, []) == b"a,b\n1,\n2,x\n"


# --- cast ------------------------------------------------------------------------------------


def _cast(cast: str, value: str) -> str:
    spec = _spec("a", "v")
    source = f"a,v\n1,{value}\n".encode()
    step = {"op": "cast_columns", "types": {"v": cast}}
    try:
        output = _run(source, spec, [step])
    except DatasetTransformationError as error:
        return error.reason
    return output.decode().splitlines()[1].split(",", 1)[1]


@pytest.mark.parametrize("value", ["0", "7", "-12", "007"])
def test_integer_cast_accepts_and_keeps_the_text(value: str) -> None:
    assert _cast("integer", value) == value


@pytest.mark.parametrize("value", ["1.5", "+1", " 1", "1 ", "", "abc", "1e3", "--1", "٣"])
def test_integer_cast_rejects(value: str) -> None:
    assert _cast("integer", value) == "cast_failed"


@pytest.mark.parametrize("value", ["0", "1.50", "-0.5", "10", "003.140"])
def test_decimal_cast_accepts_and_keeps_the_text(value: str) -> None:
    assert _cast("decimal", value) == value


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "1e3", ".5", "5."])
def test_decimal_cast_rejects(value: str) -> None:
    assert _cast("decimal", value) == "cast_failed"


@pytest.mark.parametrize("value", ["2020-02-29", "2023-11-26", "0001-01-01"])
def test_date_cast_accepts(value: str) -> None:
    assert _cast("date", value) == value


@pytest.mark.parametrize(
    "value", ["2021-02-29", "2020-13-01", "2020-1-01", "20200101", "2020-01-01T00", "0000-01-01"]
)
def test_date_cast_rejects(value: str) -> None:
    assert _cast("date", value) == "cast_failed"


@pytest.mark.parametrize("value", ["2020-W01", "2020-W53", "2023-W47", "2021-W52"])
def test_iso_week_cast_accepts(value: str) -> None:
    assert _cast("iso_week", value) == value


@pytest.mark.parametrize(
    "value", ["2021-W53", "2020-W00", "2020-W54", "2020-W1", "2020W01", "0000-W01", "2020-w01"]
)
def test_iso_week_cast_rejects(value: str) -> None:
    assert _cast("iso_week", value) == "cast_failed"


def test_string_cast_always_validates() -> None:
    assert _cast("string", "anything at all") == "anything at all"


def test_missing_cells_are_exempt_from_casts() -> None:
    spec = _spec("a", "v", v=("integer", "none", ("NA",)))
    step = {"op": "cast_columns", "types": {"v": "integer"}}
    assert _run(b"a,v\n1,NA\n2,5\n", spec, [step]) == b"a,v\n1,\n2,5\n"
    assert _reason(b"a,v\n1,x\n", spec, [step]) == "cast_failed"


def test_the_whole_plan_fails_if_any_value_fails_to_cast() -> None:
    step = {"op": "cast_columns", "types": {"v": "integer"}}
    assert _reason(b"a,v\n1,1\n2,2\n3,x\n", _spec("a", "v"), [step]) == "cast_failed"


def test_cast_updates_the_declared_output_type() -> None:
    raw = _raw(b"a,v\n1,2\n", _spec("a", "v"))
    plan = _plan(raw, [{"op": "cast_columns", "types": {"v": "decimal"}}])
    columns = derive_transformation_output_columns(
        plan, raw_bundles_for(raw, {"source.csv": b"a,v\n1,2\n"})
    )
    assert [(c.name, c.value_type) for c in columns["out.csv"]] == [
        ("a", "string"),
        ("v", "decimal"),
    ]


# --- unique key / sort -----------------------------------------------------------------------


def test_duplicate_keys_fail() -> None:
    step = {"op": "require_unique_key", "columns": ["a", "b"]}
    assert _reason(b"a,b,c\n1,2,x\n1,2,y\n", _spec("a", "b", "c"), [step]) == "duplicate_key"
    assert _run(b"a,b,c\n1,2,x\n1,3,y\n", _spec("a", "b", "c"), [step]) == b"a,b,c\n1,2,x\n1,3,y\n"


def test_missing_keys_count_as_equal() -> None:
    spec = _spec("a", "b", a=("string", "none", ("NA",)))
    step = {"op": "require_unique_key", "columns": ["a"]}
    assert _reason(b"a,b\nNA,1\nNA,2\n", spec, [step]) == "duplicate_key"


def _sorted(cast: str | None, values: list[str], missing: tuple[str, ...] = ()) -> list[str]:
    spec = _spec("k", "v", k=("string", "none", missing))
    body = "".join(f"{v},{i}\n" for i, v in enumerate(values))
    steps: list[dict[str, Any]] = []
    if cast is not None:
        steps.append({"op": "cast_columns", "types": {"k": cast}})
    steps.append({"op": "sort_rows", "columns": ["k"]})
    output = _run(f"k,v\n{body}".encode(), spec, steps).decode().splitlines()[1:]
    return [line.split(",")[0] for line in output]


def test_integer_sort_is_numeric() -> None:
    assert _sorted("integer", ["10", "9", "-3", "100"]) == ["-3", "9", "10", "100"]


def test_decimal_sort_is_numeric() -> None:
    assert _sorted("decimal", ["10.5", "9.25", "-0.5", "9.3"]) == ["-0.5", "9.25", "9.3", "10.5"]


def test_date_sort_is_chronological() -> None:
    values = ["2021-01-01", "2020-12-31", "2020-02-29"]
    assert _sorted("date", values) == ["2020-02-29", "2020-12-31", "2021-01-01"]


def test_iso_week_sort_is_by_year_then_week() -> None:
    values = ["2021-W01", "2020-W53", "2020-W10", "2020-W02"]
    assert _sorted("iso_week", values) == ["2020-W02", "2020-W10", "2020-W53", "2021-W01"]


def test_uncast_columns_sort_as_text() -> None:
    assert _sorted(None, ["10", "9", "100"]) == ["10", "100", "9"]


def test_missing_values_sort_before_any_value() -> None:
    assert _sorted("integer", ["5", "NA", "-9", "NA"], missing=("NA",)) == ["", "", "-9", "5"]


def test_sort_is_stable_and_multi_column() -> None:
    source = b"k,v\nb,1\na,2\nb,0\na,1\n"
    spec = _spec("k", "v")
    assert _run(source, spec, [{"op": "sort_rows", "columns": ["k"]}]) == (
        b"k,v\na,2\na,1\nb,1\nb,0\n"
    )
    assert _run(source, spec, [{"op": "sort_rows", "columns": ["k", "v"]}]) == (
        b"k,v\na,1\na,2\nb,0\nb,1\n"
    )


# --- failures, determinism, purity -----------------------------------------------------------


def test_an_unknown_source_fails() -> None:
    raw = build_raw_manifest()
    plan = TransformationPlan.model_validate(golden_plan())
    with pytest.raises(DatasetTransformationError) as excinfo:
        execute_transformation_plan(plan, {})
    assert excinfo.value.reason == "missing_source"
    with pytest.raises(DatasetTransformationError) as excinfo:
        execute_transformation_plan(plan, raw_bundles_for(raw, {}))
    assert excinfo.value.reason == "missing_source"


def test_wrong_plan_type_and_malformed_inputs_fail() -> None:
    raw = build_raw_manifest()
    bad_plans: list[Any] = [golden_plan(), None]
    for bad_plan in bad_plans:
        with pytest.raises(DatasetTransformationError) as excinfo:
            execute_transformation_plan(bad_plan, raw_bundles_for(raw))
        assert excinfo.value.reason == "invalid_plan"
    plan = TransformationPlan.model_validate(golden_plan())
    bad_bundle_cases: list[Any] = [[], {"x": "not-a-tuple"}, {"x": (raw.model_dump(), {})}]
    for bad_bundles in bad_bundle_cases:
        with pytest.raises(DatasetTransformationError) as excinfo:
            execute_transformation_plan(plan, bad_bundles)
        assert excinfo.value.reason == "invalid_input"


def test_the_public_message_is_generic_and_never_echoes_cells() -> None:
    secret = "secret-cell-value"
    step = {"op": "cast_columns", "types": {"v": "integer"}}
    raw = _raw(f"a,v\n1,{secret}\n".encode(), _spec("a", "v"))
    plan = _plan(raw, [step])
    with pytest.raises(DatasetTransformationError) as excinfo:
        execute_transformation_plan(
            plan, raw_bundles_for(raw, {"source.csv": f"a,v\n1,{secret}\n".encode()})
        )
    rendered = f"{excinfo.value!s}|{excinfo.value!r}|{excinfo.value.args!r}"
    assert secret not in rendered
    assert "source.csv" not in rendered
    assert str(excinfo.value) == (
        "Dataset transformation plan failed and was rejected; no output was produced"
    )


def test_execution_is_deterministic_and_does_not_mutate_inputs() -> None:
    raw = build_raw_manifest()
    plan = TransformationPlan.model_validate(golden_plan())
    files = dict(RAW_FILES)
    bundles = raw_bundles_for(raw, files)
    before = (raw.model_dump_json(), plan.model_dump_json(), copy.deepcopy(files))
    first = execute_transformation_plan(plan, bundles)
    second = execute_transformation_plan(plan, bundles)
    assert first == second
    assert (raw.model_dump_json(), plan.model_dump_json(), files) == before
    assert files["source.csv"] == RAW_CSV


_FORBIDDEN_ROOTS = frozenset(
    {
        "os",
        "pathlib",
        "urllib",
        "http",
        "socket",
        "requests",
        "time",
        "random",
        "secrets",
        "subprocess",
        "logging",
        "shutil",
        "tempfile",
        "warnings",
        "threading",
    }
)
_FORBIDDEN_ATTRIBUTES = frozenset(
    {"now", "today", "utcnow", "getenv", "environ", "read_text", "read_bytes", "write_text"}
)
_FORBIDDEN_NAMES = frozenset({"open", "print", "input", "exec", "eval", "__import__"})
_MODULES = (
    "contracts/v1/curated_dataset.py",
    "application/dataset_transformation_engine.py",
    "application/curated_dataset_verifier.py",
    "application/dataset_transformation_errors.py",
)


@pytest.mark.parametrize("relative", _MODULES)
def test_modules_have_no_filesystem_network_clock_or_random_access(relative: str) -> None:
    tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in _FORBIDDEN_ROOTS, (relative, alias.name)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in _FORBIDDEN_ROOTS, (
                relative,
                node.module,
            )
        elif isinstance(node, ast.Attribute):
            assert node.attr not in _FORBIDDEN_ATTRIBUTES, (relative, node.attr)
        elif isinstance(node, ast.Name):
            assert node.id not in _FORBIDDEN_NAMES, (relative, node.id)


def test_the_engine_keeps_no_module_level_mutable_state() -> None:
    for relative in _MODULES:
        tree = ast.parse((KALHAS_ROOT / relative).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                    continue
                assert not isinstance(node.value, ast.List | ast.Dict | ast.Set), (
                    relative,
                    ast.dump(node),
                )
