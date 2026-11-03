"""Shape, identity, immutability and serialization of split contracts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest
from pydantic import ValidationError

from tests.test_dataset_split_engine import build_split, synthetic_chain


def payload() -> dict[str, Any]:
    _, curated, files = synthetic_chain()
    return build_split(curated, files).model_dump(mode="json")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("validation_from", "2020-1-01"),
        ("holdout_from", "2020-02-30"),
        ("validation_from", "2020-01-05"),
        ("validation_from", "2020-01-06"),
    ],
)
def test_invalid_date_cuts(field: str, value: str) -> None:
    item = payload()
    item["file_rules"][0]["time_rule"][field] = value
    with pytest.raises(ValidationError):
        DatasetSplitManifest.model_validate(item)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("validation_from", "2020-W00"),
        ("holdout_from", "2021-W53"),
        ("validation_from", "2020-W03"),
        ("validation_from", "2020-W04"),
    ],
)
def test_invalid_week_cuts(field: str, value: str) -> None:
    item = payload()
    item["file_rules"][1]["time_rule"][field] = value
    with pytest.raises(ValidationError):
        DatasetSplitManifest.model_validate(item)


@pytest.mark.parametrize(
    ("validation", "holdout"), [([], []), (["a", "a"], []), ([], ["b", "b"]), (["a"], ["a"])]
)
def test_invalid_geography(validation: list[str], holdout: list[str]) -> None:
    item = payload()
    item["file_rules"][0]["geography_rule"].update(
        validation_values=validation, holdout_values=holdout
    )
    with pytest.raises(ValidationError):
        DatasetSplitManifest.model_validate(item)


def test_one_empty_geography_side_is_valid() -> None:
    item = payload()
    item["file_rules"][0]["geography_rule"]["validation_values"] = []
    DatasetSplitManifest.model_validate(item)


@pytest.mark.parametrize(
    "mutation",
    [
        "no_rule",
        "bad_path",
        "unsorted",
        "duplicate",
        "membership",
        "note",
        "identity",
        "extra",
        "bool_count",
        "negative_count",
        "bad_version",
        "metadata",
    ],
)
def test_invalid_manifest_shapes(mutation: str) -> None:
    item = payload()
    if mutation == "no_rule":
        item["file_rules"][0].update(time_rule=None, geography_rule=None)
    elif mutation == "bad_path":
        item["file_rules"][0]["path"] = "../bad.csv"
    elif mutation == "unsorted":
        item["file_rules"].reverse()
    elif mutation == "duplicate":
        item["file_rules"][1]["path"] = item["file_rules"][0]["path"]
    elif mutation == "membership":
        item["memberships"][0]["path"] = "other.csv"
    elif mutation == "note":
        item["preregistration_note"] = "  "
    elif mutation == "identity":
        item["identifier"] = "wrong"
    elif mutation == "extra":
        item["unexpected"] = 1
    elif mutation == "bool_count":
        item["memberships"][0]["counts"]["holdout"] = True
    elif mutation == "negative_count":
        item["memberships"][0]["counts"]["holdout"] = -1
    elif mutation == "bad_version":
        item["split_version"] = "v1"
    else:
        item["metadata"] = {"invalid": float("nan")}
    with pytest.raises(ValidationError):
        DatasetSplitManifest.model_validate(item)


def test_frozen_roundtrip_and_unregistered_helpers() -> None:
    model = DatasetSplitManifest.model_validate(payload())
    assert DatasetSplitManifest.model_validate_json(model.model_dump_json()) == model
    with pytest.raises(ValidationError):
        model.split_id = "changed"
    with pytest.raises(ValidationError):
        model.file_rules[0].path = "changed.csv"
    names = {c.__name__ for c in PUBLIC_CONTRACTS}
    schemas = Path(__file__).resolve().parents[1] / "schemas/v1"
    for name in (
        "TimePartitionRule",
        "GeographyPartitionRule",
        "FileSplitRule",
        "PartitionCounts",
        "FileMembership",
    ):
        assert name not in names
        assert not (schemas / f"{name}.schema.json").exists()
    assert copy.deepcopy(model) == model
