"""The standalone Lab exercises the real HTTP surface without changing it."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from kalhas.api.app import create_app
from kalhas_lab.app import create_lab_app
from kalhas_lab.sequences import LAB_SEQUENCES

UI = Path(__file__).resolve().parents[1] / "kalhas_lab" / "ui"
FLOW = json.loads((UI / "demo_flow.json").read_text(encoding="utf-8"))
# Validation records the server clock; no identifiers or hashes are excluded.
CLOCK_POINTERS_EXCLUDED = ("/validate/report/validated_at",)


def _pointer(value: Any, path: str) -> Any:
    if not path:
        return value
    assert path.startswith("/")
    for component in path[1:].split("/"):
        component = component.replace("~1", "/").replace("~0", "~")
        value = value[int(component)] if isinstance(value, list) else value[component]
    return value


def _substitute(value: Any, captures: dict[str, Any], item: Any = None) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name == "item":
                result = item
            elif name.startswith("item."):
                result = item
                for field in name[5:].split("."):
                    result = result[field]
            else:
                result = captures[name]
            assert result is not None and not isinstance(result, (dict, list))
            return str(result)

        return re.sub(r"\{([^{}]+)\}", replace, value)
    if isinstance(value, list):
        return [_substitute(v, captures, item) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, captures, item) for k, v in value.items()}
    return value


def _run_flow(
    client: TestClient, tenant: str, stop_after: str | None = None
) -> tuple[list[bytes], dict[str, Any], dict[str, Any]]:
    captures: dict[str, Any] = {"tenant": tenant}
    bodies: list[bytes] = []
    responses: dict[str, Any] = {}
    for step in FLOW["steps"]:
        items = captures[step["for_each"]] if "for_each" in step else [None]
        assert isinstance(items, list) and items
        outputs = []
        for item in items:
            path = _substitute(step["path"], captures, item)
            body = _substitute(step["body"], captures, item)
            kwargs: dict[str, Any] = {"headers": {"X-Tenant-ID": tenant}}
            if body is not None:
                kwargs["json"] = body
            response = client.request(step["method"], path, **kwargs)
            assert response.status_code == step["expect_status"], (step["id"], response.text)
            bodies.append(response.content)
            outputs.append(response.json())
        responses[step["id"]] = outputs if "for_each" in step else outputs[0]
        for name, path in step["capture"].items():
            resolved = [_pointer(output, path) for output in outputs]
            captures[name] = resolved if "for_each" in step else resolved[0]
        if step["id"] == stop_after:
            break
    return bodies, captures, responses


def test_product_surface_and_assets() -> None:
    product = create_app()
    fresh = create_app()
    lab = create_lab_app()
    product_paths = set(product.openapi()["paths"])
    assert product_paths == set(fresh.openapi()["paths"]) == set(lab.openapi()["paths"])
    assert not any(path.startswith("/lab") for path in product_paths)
    assert not any(getattr(route, "path", "").startswith("/lab") for route in product.routes)
    before = copy.deepcopy(lab.state.store.__dict__)
    with TestClient(lab) as client:
        for path, content_type in (
            ("/lab/", "text/html"),
            ("/lab/styles.css", "text/css"),
            ("/lab/app.js", "text/javascript"),
            ("/lab/demo_flow.json", "application/json"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(content_type)
    assert before == lab.state.store.__dict__


def test_flow_determinism_and_trajectory_differentiation() -> None:
    with TestClient(create_lab_app()) as first, TestClient(create_lab_app()) as second:
        bodies, captures, responses = _run_flow(first, "lab-determinism")
        other_bodies, _, _ = _run_flow(second, "lab-determinism")
    assert CLOCK_POINTERS_EXCLUDED == ("/validate/report/validated_at",)
    # The validation response is the second call; remove only its clock value.
    for result in (bodies, other_bodies):
        timestamp = json.loads(result[1])["report"]["validated_at"]
        result[1] = result[1].replace(json.dumps(timestamp).encode(), b'"<clock>"', 1)
    assert bodies == other_bodies
    assert len(captures["runs"]) == 40
    matrix = responses["trajectories"]
    assert len(matrix["cells"]) == 40
    executions = captures["trajectory_runs"]
    trajectories = {
        tuple(attempt["transition_id"] for attempt in execution["results"][0]["attempts"])
        for execution in executions
    }
    assert len(trajectories) >= 2
    assert responses["verify"]["verification_classification"] == "exact"
    assert (
        responses["verify"]["expected_input_hash"] == responses["verify"]["recomputed_input_hash"]
    )
    assert responses["replay"]["replay_classification"] == "exact"


def test_tenant_isolation_and_stage_errors() -> None:
    with TestClient(create_lab_app()) as client:
        _, first, _ = _run_flow(client, "lab-isolation-a")
        _, second, _ = _run_flow(client, "lab-isolation-b")
        assert len(first["runs"]) == len(second["runs"]) == 40
        path = "/lab/api/campaigns/campaign-1/trajectory-plans"
        missing = client.post(path)
        assert missing.status_code == 422
        keys = {"code", "message", "details", "request_id"}
        assert set(missing.json()) == keys
        headers = {"X-Tenant-ID": "lab-isolation-a", "X-Request-ID": "lab-request"}
        completed = client.post(path, headers=headers)
        assert completed.status_code == 409
        assert completed.json()["code"] == "invalid_state"
        assert set(completed.json()) == keys
        assert completed.json()["request_id"] == completed.headers["x-request-id"] == "lab-request"
        _run_flow(client, "lab-prepared", stop_after="plans")
        duplicate = client.post(
            path, headers={"X-Tenant-ID": "lab-prepared", "X-Request-ID": "lab-duplicate"}
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "conflict"
        assert set(duplicate.json()) == keys
        assert (
            duplicate.json()["request_id"] == duplicate.headers["x-request-id"] == "lab-duplicate"
        )


def test_flow_consistency_and_asset_safety() -> None:
    assert FLOW["flow_version"] == "1.0.0"
    steps = FLOW["steps"]
    assert len({s["id"] for s in steps}) == len(steps)
    assert [s["id"] for s in steps if s["kind"] == "lab"] == ["plans"]
    assert set(LAB_SEQUENCES) == {
        "mock-baseline",
        "mock-conservative",
        "mock-balanced",
        "mock-adaptive",
        "mock-diversified",
    }
    assert len(set(LAB_SEQUENCES.values())) == 5
    declared = {
        s["body"]["transition_id"] for s in steps if s["path"].endswith("/domain-state-transitions")
    }
    assert len(declared) >= 3
    assert all(set(sequence) <= declared for sequence in LAB_SEQUENCES.values())
    assert len(next(s for s in steps if s["id"] == "campaign")["body"]["seed_ensemble"]) >= 8
    for step in steps:
        assert {
            "id",
            "stage",
            "title",
            "kind",
            "method",
            "path",
            "body",
            "expect_status",
            "capture",
        } <= set(step)
        assert step["path"].startswith(("/v1/", "/lab/"))
    for path in UI.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        assert "http://" not in text and "https://" not in text
    for name in ("index.html", "styles.css", "app.js"):
        assert all(
            len(line) <= 120 for line in (UI / name).read_text(encoding="utf-8").splitlines()
        )
    script = (UI / "app.js").read_text(encoding="utf-8")
    for forbidden in (
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "setInterval",
        "eval(",
        "new Function",
        "innerHTML",
        "localStorage",
        "sessionStorage",
    ):
        assert forbidden not in script
    assert script.count("fetch(") == 1 and "fetch(path, options)" in script
    assert "safePath(path)" in script
    assert script.count("setTimeout(") == 1
    lower_flow = json.dumps(FLOW).lower()
    for term in ("hospital", "patient", "covid", "ecdc", "customer", "company"):
        assert term not in lower_flow
