"""Protocol verification and bounded failures."""

from __future__ import annotations

from typing import cast

import pytest
from kalhas.application.benchmark_errors import BenchmarkProtocolVerificationError
from kalhas.application.benchmark_protocol_verifier import verify_benchmark_protocol
from kalhas.contracts.v1.benchmark_protocol import BenchmarkProtocol

from tests.test_benchmark_task_engine import chain


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("split_input", "split_input_invalid"),
        ("split_ref", "split_reference_mismatch"),
        ("curated_ref", "curated_reference_mismatch"),
        ("tenant", "tenant_mismatch"),
        ("lock", "lock_order_invalid"),
        ("target_path", "target_invalid"),
        ("series", "target_invalid"),
        ("time", "target_invalid"),
        ("value", "target_invalid"),
        ("hash", "content_hash_mismatch"),
    ],
)
def test_rejection_order(case: str, reason: str) -> None:
    raw, sources, curated, files, split, protocol = chain()
    data = protocol.model_dump(mode="json")
    if case == "split_input":
        files = dict(files)
        files["daily.csv"] += b"x"
    elif case == "split_ref":
        data["split_content_hash"] = "1" * 64
    elif case == "curated_ref":
        data["curated_bundle_hash"] = "1" * 64
    elif case == "tenant":
        data["tenant_id"] = "other"
    elif case == "lock":
        data["locked_at"] = "2026-11-02T00:00:00Z"
    elif case == "target_path":
        data["targets"][1]["path"] = "zz.csv"
    elif case == "series":
        data["targets"][0]["series_column"] = "value"
        data["targets"][0]["value_column"] = "zone"
    elif case == "time":
        data["targets"][0]["time_column"] = "zone"
    elif case == "value":
        data["targets"][0]["value_column"] = "zone"
    else:
        data["content_hash"] = "1" * 64
    changed = BenchmarkProtocol.model_validate(data)
    with pytest.raises(BenchmarkProtocolVerificationError) as error:
        verify_benchmark_protocol(changed, split, curated, files, {raw.identifier: (raw, sources)})
    assert error.value.reason == reason
    assert str(error.value) == "Benchmark protocol verification failed and was rejected"


def test_valid_wrong_type_and_forged() -> None:
    raw, sources, curated, files, split, protocol = chain()
    bundles = {raw.identifier: (raw, sources)}
    verify_benchmark_protocol(protocol, split, curated, files, bundles)
    forged = BenchmarkProtocol.model_construct(
        **{**protocol.model_dump(mode="python"), "protocol_version": "bad"}
    )
    for candidate in (forged, cast(BenchmarkProtocol, object())):
        with pytest.raises(BenchmarkProtocolVerificationError) as error:
            verify_benchmark_protocol(candidate, split, curated, files, bundles)
        assert error.value.reason == "invalid_manifest"
