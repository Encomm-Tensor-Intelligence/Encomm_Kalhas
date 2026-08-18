"""Tests for the Encomm Colony visual prototype and observability UI.

The synthetic living-colony demo is client-side presentation data and
the operational observatory is strictly read-only. The KALHAS API must
remain usable without either, and opening the UI never alters state.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_api_phase9 import TENANT, activity, full_flow

COLONY_UI_DIR = Path(__file__).resolve().parents[1] / "kalhas" / "colony_ui"
HEADERS = {"X-Tenant-ID": TENANT}

# Case-sensitive: the UI must not reference mutation verbs at all.
_MUTATION_METHODS = re.compile(r"\b(POST|PUT|PATCH|DELETE)\b")
# Automatic polling / streaming / background primitives.
_POLLING_PRIMITIVES = re.compile(
    r"\b(setInterval|setTimeout|WebSocket|EventSource|XMLHttpRequest|"
    r"navigator\.sendBeacon|requestAnimationFrame)\b"
)


def _read_asset(name: str) -> str:
    return (COLONY_UI_DIR / name).read_text(encoding="utf-8")


class TestColonyServedLocally:
    def test_colony_page_returns_the_ui(self, client: TestClient) -> None:
        response = client.get("/colony/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "ENCOMM COLONY" in html
        assert "KALHAS operational observability" in html
        assert "manual pull refresh" in html
        assert 'id="tenant-input"' in html
        assert 'id="load-button"' in html
        assert 'id="feed-status"' in html

    def test_colony_page_exposes_the_synthetic_demo_console(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "Aurora-7 Supply Shock" in html
        assert 'id="demo-toggle"' in html
        assert 'id="colony-map"' in html
        assert 'id="mission-timeline"' in html
        assert 'id="outcome-panel"' in html

    def test_demo_is_explicitly_disclosed_as_mock_presentation(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "SYNTHETIC DEMO" in html
        assert "deterministic client-side mock data" in html
        assert "do not claim real KALHAS execution" in html
        assert "Mock result · presentation prototype only" in html

    def test_colony_page_needs_no_tenant_header(self, client: TestClient) -> None:
        assert client.get("/colony/").status_code == 200

    def test_colony_assets_are_served_locally(self, client: TestClient) -> None:
        css = client.get("/colony/styles.css")
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
        js = client.get("/colony/app.js")
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]

    def test_colony_page_references_only_local_assets(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "https://" not in html
        assert "http://" not in html
        assert "cdn" not in html.lower()
        assert html.count("<script") == 1
        assert "/colony/app.js" in html
        assert "/colony/styles.css" in html

    def test_colony_routes_stay_out_of_openapi(self, client: TestClient) -> None:
        """Colony is a UI, not API surface: the OpenAPI document is unchanged."""
        openapi = client.get("/openapi.json").json()
        assert "/health" in openapi["paths"]
        assert "/v1/operational-activity" in openapi["paths"]
        assert "/colony/" not in openapi["paths"]
        assert "/colony/app.js" not in openapi["paths"]


class TestColonyTruthfulLabels:
    def test_page_labels_pull_based_manual_refresh(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "manual pull refresh" in html
        assert "not streaming live" in html

    def test_page_marks_nexus_and_legion_as_not_connected(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "NEXUS" in html
        assert "External boundary" in html
        assert "not connected" in html
        assert "LEGION" in html
        assert "Mock strategy boundary only" in html
        assert "No integration is present" in html

    def test_page_separates_operational_order_from_simulation_time(
        self, client: TestClient
    ) -> None:
        html = client.get("/colony/").text
        assert "tenant-local operational order" in html
        assert "not simulation or replay time" in html

    def test_page_states_activity_never_affects_hashes(self, client: TestClient) -> None:
        html = client.get("/colony/").text
        assert "never affects simulation or replay hashes" in html


class TestColonyJavaScriptSafety:
    def test_demo_has_no_api_call_and_uses_a_bounded_deterministic_horizon(self) -> None:
        js = _read_asset("app.js")
        assert "FINAL_DAY = 24" in js
        assert "valuesForDay" in js
        assert "animationiteration" in js
        assert js.count("fetch(") == 1

    def test_js_makes_get_only_requests_to_the_activity_endpoint(self) -> None:
        js = _read_asset("app.js")
        # The only API path literal in the whole script.
        assert re.findall(r'"/v1/[^"]*"', js) == ['"/v1/operational-activity"']
        # The single fetch call site builds its URL from ACTIVITY_URL with a
        # headers object only - no method override, no body, so every
        # request is a plain GET.
        calls = re.findall(r"fetch\(([^)]*)\)", js)
        assert len(calls) == 1
        assert "ACTIVITY_URL" in calls[0]
        assert "headers" in calls[0]
        assert "method" not in calls[0]
        assert "body" not in calls[0]

    def test_js_contains_no_mutation_http_methods(self) -> None:
        js = _read_asset("app.js")
        assert not _MUTATION_METHODS.search(js)

    def test_js_has_no_automatic_polling_or_streaming_primitives(self) -> None:
        js = _read_asset("app.js")
        assert not _POLLING_PRIMITIVES.search(js)
        assert "fetch" in js

    def test_js_uses_text_content_not_inner_html(self) -> None:
        js = _read_asset("app.js")
        assert "innerHTML" not in js
        assert "document.write" not in js
        assert "textContent" in js

    def test_js_refresh_is_cursor_based_and_keeps_latest_events_only(self) -> None:
        js = _read_asset("app.js")
        assert "?after_sequence=-1&limit=100" in js
        assert "after_sequence=" in js
        assert "MAX_EVENTS = 100" in js
        assert "PAGE_SIZE = 100" in js

    def test_js_maps_state_model_kind_to_domain_registry(self) -> None:
        js = _read_asset("app.js")
        match = re.search(r"domain_registry: \[(.*?)\]", js, re.DOTALL)
        assert match is not None
        kinds = re.findall(r'"([^"]+)"', match.group(1))
        assert "domain_state_model_declared" in kinds

    def test_js_maps_transition_kind_to_domain_registry(self) -> None:
        js = _read_asset("app.js")
        match = re.search(r"domain_registry: \[(.*?)\]", js, re.DOTALL)
        assert match is not None
        kinds = re.findall(r'"([^"]+)"', match.group(1))
        assert "domain_state_transition_declared" in kinds

    def test_html_observes_line_lists_the_transition_kind(self) -> None:
        html = _read_asset("index.html")
        assert "domain_state_transition_declared" in html

    def test_js_defensively_filters_payload_keys(self) -> None:
        js = _read_asset("app.js")
        for key in ("input_values", "policy", "evidence", "recommendation", "reasoning"):
            assert f"{key}: true" in js


class TestColonyReadOnly:
    def test_opening_colony_creates_no_activity(self, client: TestClient) -> None:
        assert activity(client) == {"events": [], "next_after_sequence": -1, "latest_sequence": -1}
        for path in ("/colony/", "/colony/styles.css", "/colony/app.js"):
            assert client.get(path).status_code == 200
        # Reading the page and its assets never appends activity events.
        assert activity(client) == {"events": [], "next_after_sequence": -1, "latest_sequence": -1}

    def test_colony_does_not_alter_an_existing_feed(self, client: TestClient) -> None:
        full_flow(client)
        before = activity(client)
        for path in ("/colony/", "/colony/styles.css", "/colony/app.js"):
            assert client.get(path).status_code == 200
        assert activity(client) == before

    def test_colony_does_not_alter_world_run_replay_or_integrity_hashes(
        self, client: TestClient
    ) -> None:
        artifacts = full_flow(client)
        world_id = artifacts["compiled"]["version"]["identifier"]
        run_id = artifacts["run_id"]

        world_before = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        run_before = client.get(f"/v1/runs/{run_id}", headers=HEADERS).json()
        events_before = client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).json()
        replay_before = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS).json()
        assert run_before["input_hash"] == artifacts["plans"][0]["input_hash"]
        assert run_before["event_hash"] is not None
        assert replay_before["replay_classification"] == "exact"

        for path in ("/colony/", "/colony/styles.css", "/colony/app.js"):
            assert client.get(path).status_code == 200

        world_after = client.get(f"/v1/worlds/{world_id}", headers=HEADERS).json()
        run_after = client.get(f"/v1/runs/{run_id}", headers=HEADERS).json()
        events_after = client.get(f"/v1/runs/{run_id}/events", headers=HEADERS).json()
        replay_after = client.get(f"/v1/runs/{run_id}/replay", headers=HEADERS).json()

        # World content hash, run input/event hashes, the recorded event
        # stream, and the replay expectation are all byte-identical.
        assert world_after == world_before
        assert run_after["input_hash"] == run_before["input_hash"]
        assert run_after["event_hash"] == run_before["event_hash"]
        assert events_after == events_before
        assert replay_after["expected_event_hash"] == replay_before["expected_event_hash"]
        assert replay_after["replay_classification"] == "exact"


class TestExistingBehaviorUnchanged:
    def test_core_routes_still_work(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/system-info").status_code == 200

    def test_activity_feed_flow_still_works(self, client: TestClient) -> None:
        full_flow(client)
        feed = activity(client)
        assert [event["kind"] for event in feed["events"]] == [
            "scenario_registered",
            "domain_pack_registered",
            "domain_pack_bound",
            "capability_inputs_declared",
            "world_compiled",
            "campaign_prepared",
            "campaign_started",
            "campaign_executed",
            "run_inputs_verified",
            "run_replayed",
        ]
        assert feed["latest_sequence"] == 9
