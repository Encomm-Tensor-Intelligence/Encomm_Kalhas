"""Split re-execution and sealed partition view tests."""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from kalhas.application.dataset_split_errors import (
    DatasetSplitError,
    DatasetSplitVerificationError,
    SealedPartitionError,
)
from kalhas.application.dataset_split_verifier import select_partition_rows, verify_dataset_split
from kalhas.contracts.v1.dataset_split import DatasetSplitManifest

from tests.test_dataset_split_engine import RAW_FILES, build_split, synthetic_chain


def verify_mutation(kind: str) -> str:
    raw, curated, files = synthetic_chain()
    split = build_split(curated, files)
    payload: dict[str, Any] = split.model_dump(mode="json")
    if kind == "curated_input_invalid":
        files = dict(files)
        files["daily.csv"] += b"x"
    elif kind == "reference_mismatch":
        payload["curated_content_hash"] = "1" * 64
    elif kind == "tenant_mismatch":
        payload["tenant_id"] = "other"
    elif kind == "coverage_mismatch":
        payload["file_rules"].pop()
        payload["memberships"].pop()
    elif kind == "counts":
        payload["memberships"][0]["counts"]["holdout"] += 1
    elif kind == "membership_hash":
        payload["memberships"][0]["membership_hash"] = "1" * 64
    elif kind == "content_hash_mismatch":
        payload["content_hash"] = "1" * 64
    changed = DatasetSplitManifest.model_validate(payload)
    with pytest.raises(DatasetSplitVerificationError) as error:
        verify_dataset_split(changed, curated, files, {raw.identifier: (raw, RAW_FILES)})
    assert str(error.value) == "Dataset split verification failed and was rejected"
    return error.value.reason


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("curated_input_invalid", "curated_input_invalid"),
        ("reference_mismatch", "reference_mismatch"),
        ("tenant_mismatch", "tenant_mismatch"),
        ("coverage_mismatch", "coverage_mismatch"),
        ("counts", "membership_mismatch"),
        ("membership_hash", "membership_mismatch"),
        ("content_hash_mismatch", "content_hash_mismatch"),
    ],
)
def test_verification_reasons(kind: str, reason: str) -> None:
    assert verify_mutation(kind) == reason


def test_valid_and_forged_manifest() -> None:
    raw, curated, files = synthetic_chain()
    split = build_split(curated, files)
    verify_dataset_split(split, curated, files, {raw.identifier: (raw, RAW_FILES)})
    forged = DatasetSplitManifest.model_construct(
        **{**split.model_dump(mode="python"), "split_version": "bad"}
    )
    for candidate in (forged, cast(DatasetSplitManifest, object())):
        with pytest.raises(DatasetSplitVerificationError) as error:
            verify_dataset_split(candidate, curated, files, {raw.identifier: (raw, RAW_FILES)})
        assert error.value.reason == "invalid_manifest"


def test_partition_views_and_unconditional_holdout() -> None:
    raw, curated, files = synthetic_chain()
    split = build_split(curated, files)
    verify_dataset_split(split, curated, files, {raw.identifier: (raw, RAW_FILES)})
    assert (
        select_partition_rows(split, curated, files, "daily.csv", "development")
        == b"region,day,value\na,2020-01-01,1\n"
    )
    assert (
        select_partition_rows(split, curated, files, "daily.csv", "validation")
        == b"region,day,value\nc,2020-01-03,3\n"
    )
    with pytest.raises(SealedPartitionError) as error:
        select_partition_rows(split, curated, {}, "secret", "holdout")
    assert str(error.value) == "The requested partition is sealed"
    changed = copy.deepcopy(split.model_dump(mode="json"))
    changed["curated_bundle_hash"] = "1" * 64
    with pytest.raises(DatasetSplitError) as error2:
        select_partition_rows(
            DatasetSplitManifest.model_validate(changed), curated, files, "daily.csv", "development"
        )
    assert error2.value.reason == "reference_mismatch"
    tampered = dict(files)
    tampered["daily.csv"] = tampered["daily.csv"].replace(b"2020-01-01", b"2020-01-05")
    with pytest.raises(DatasetSplitError):
        select_partition_rows(split, curated, tampered, "daily.csv", "development")
