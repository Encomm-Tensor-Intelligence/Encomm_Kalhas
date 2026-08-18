/* Encomm Colony - local living-colony visual prototype and observability.
 *
 * The animated demo is deterministic synthetic client-side presentation
 * data. It never claims to be kernel execution and never makes a network
 * request. The separate operational observatory remains strictly read-only
 * and pull-based. Its only request is a GET of the tenant-scoped activity
 * endpoint; it never sends data or uses polling/streaming transport.
 *
 * Rendering rule: every value that came from the API is written with
 * textContent. Nothing from the API is ever interpreted as markup.
 */
"use strict";

(function () {
  var FINAL_DAY = 24;
  var signalMessages = {
    0: "Baseline world state captured",
    1: "Five synthetic workers dispatched",
    4: "Solar disruption detected in sector P-12",
    6: "Reserve routing shifted to Habitat Ring",
    9: "Adaptive load-balancing strategy deployed",
    12: "Systemic risk has passed its peak",
    15: "Recovery window confirmed",
    19: "Bio Dome reserves rebuilding",
    22: "All critical routes operating normally",
    24: "Outcome proof assembled for review",
  };
  var demoState = {
    day: 0,
    running: false,
    complete: false,
    signals: [],
  };

  function demoById(id) {
    return document.getElementById(id);
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function valuesForDay(day) {
    var stability;
    var reserve;
    var risk;
    if (day < 4) {
      stability = 78 + day;
      reserve = 41 - day * 0.4;
      risk = 22 - day * 0.5;
    } else if (day < 10) {
      stability = 81 - (day - 4) * 4.8;
      reserve = 39 - (day - 4) * 1.55;
      risk = 24 + (day - 4) * 7.1;
    } else if (day < 16) {
      stability = 55 + (day - 10) * 4.2;
      reserve = 30 + (day - 10) * 1.1;
      risk = 61 - (day - 10) * 5.7;
    } else {
      stability = 80 + (day - 16) * 1.65;
      reserve = 37 + (day - 16) * 1.35;
      risk = 27 - (day - 16) * 1.65;
    }
    return {
      stability: Math.round(clamp(stability, 0, 100)),
      reserve: Math.round(clamp(reserve, 0, 60)),
      risk: Math.round(clamp(risk, 0, 100)),
    };
  }

  function statusForDay(day) {
    if (day === 0) return "Ready for local demo";
    if (day < 4) return "Establishing baseline";
    if (day < 9) return "Shock propagating";
    if (day < 15) return "Strategy adapting";
    if (day < FINAL_DAY) return "Colony recovering";
    return "Synthetic outcome complete";
  }

  function setNodeState(node, active, warning) {
    var element = document.querySelector('[data-node="' + node + '"]');
    element.classList.toggle("active", active);
    element.classList.toggle("warning", warning);
  }

  function renderNodes(day, values) {
    setNodeState("command", day > 0, false);
    setNodeState("habitat", day >= 6, day >= 6 && day < 13);
    setNodeState("solar", day >= 4, day >= 4 && day < 12);
    setNodeState("farm", day >= 15, false);
    setNodeState("lab", day >= 1, false);
    setNodeState("logistics", day >= 9, false);
    demoById("node-command").textContent = day === 0 ? "Systems ready" : statusForDay(day);
    demoById("node-habitat").textContent = values.stability + "% stability";
    demoById("node-solar").textContent = day < 4 ? "82% output" : day < 12 ? "47% · rerouting" : "76% · recovered";
    demoById("node-farm").textContent = values.reserve + " days reserve";
    demoById("node-lab").textContent = day < 9 ? "Modeling shock" : "Verifying response";
    demoById("node-logistics").textContent = day < 9 ? "4 routes ready" : day < 16 ? "6 routes active" : "8 routes active";
  }

  function addSignal(day) {
    if (!Object.prototype.hasOwnProperty.call(signalMessages, day)) return;
    demoState.signals.unshift({ day: day, message: signalMessages[day] });
    if (demoState.signals.length > 5) demoState.signals.length = 5;
  }

  function renderSignals() {
    var list = demoById("signal-list");
    list.textContent = "";
    for (var i = 0; i < demoState.signals.length; i += 1) {
      var signal = demoState.signals[i];
      var item = document.createElement("li");
      var time = document.createElement("time");
      var copy = document.createElement("span");
      time.textContent = "D" + String(signal.day).padStart(2, "0");
      copy.textContent = signal.message;
      item.appendChild(time);
      item.appendChild(copy);
      list.appendChild(item);
    }
    demoById("signal-count").textContent = String(demoState.signals.length).padStart(2, "0");
  }

  function renderTimeline(day) {
    var items = demoById("mission-timeline").querySelectorAll("li");
    var currentIndex = 0;
    for (var i = 0; i < items.length; i += 1) {
      if (Number(items[i].getAttribute("data-day")) <= day) currentIndex = i;
    }
    for (var j = 0; j < items.length; j += 1) {
      items[j].classList.toggle("complete", j < currentIndex || demoState.complete);
      items[j].classList.toggle("current", !demoState.complete && j === currentIndex);
    }
  }

  function renderOutcome() {
    var panel = demoById("outcome-panel");
    panel.classList.toggle("complete", demoState.complete);
    if (!demoState.complete) {
      demoById("outcome-title").textContent = "Pending";
      demoById("outcome-copy").textContent = "Run the synthetic scenario to reveal its deterministic result.";
      demoById("confidence-value").textContent = "—";
      demoById("incident-value").textContent = "—";
      demoById("action-value").textContent = "—";
      return;
    }
    demoById("outcome-title").textContent = "Stable recovery";
    demoById("outcome-copy").textContent = "The mock colony absorbs the supply shock and restores critical reserves before the scenario horizon.";
    demoById("confidence-value").textContent = "92% synthetic";
    demoById("incident-value").textContent = "2 contained";
    demoById("action-value").textContent = "Adaptive routing";
  }

  function renderDemo() {
    var values = valuesForDay(demoState.day);
    var percent = Math.round((demoState.day / FINAL_DAY) * 100);
    demoById("day-value").textContent = String(demoState.day).padStart(2, "0");
    demoById("progress-fill").style.width = percent + "%";
    demoById("clock-readout").textContent = String((6 + demoState.day * 3) % 24).padStart(2, "0") + ":00 UTC";
    demoById("run-status").textContent = demoState.running ? statusForDay(demoState.day) : demoState.complete ? "Synthetic outcome complete" : demoState.day ? "Simulation paused" : "Ready for local demo";
    demoById("map-state").textContent = demoState.running ? "SIMULATING" : demoState.complete ? "COMPLETE" : demoState.day ? "PAUSED" : "STANDBY";
    demoById("run-dot").className = "run-dot" + (demoState.running ? " running" : demoState.complete ? " complete" : "");
    demoById("stability-value").textContent = values.stability + "%";
    demoById("reserve-value").textContent = values.reserve + " d";
    demoById("risk-value").textContent = values.risk + "%";
    demoById("stability-bar").style.width = values.stability + "%";
    demoById("reserve-bar").style.width = Math.round((values.reserve / 60) * 100) + "%";
    demoById("risk-bar").style.width = values.risk + "%";
    demoById("stability-delta").textContent = demoState.day < 4 ? "Baseline readiness" : demoState.day < 12 ? "Shock pressure active" : "Recovery trend rising";
    demoById("reserve-delta").textContent = demoState.day < 10 ? "Inventory drawdown" : "Reserve rebuilding";
    demoById("risk-delta").textContent = values.risk > 50 ? "Above preferred threshold" : "Within tolerance";
    renderNodes(demoState.day, values);
    renderTimeline(demoState.day);
    renderSignals();
    renderOutcome();
  }

  function completeDemo() {
    demoState.day = FINAL_DAY;
    demoState.running = false;
    demoState.complete = true;
    demoById("colony-map").classList.remove("running");
    demoById("demo-toggle").classList.remove("is-running");
    demoById("demo-toggle").textContent = "Run again";
    addSignal(FINAL_DAY);
    renderDemo();
  }

  function startFreshDemo() {
    demoState.day = 0;
    demoState.complete = false;
    demoState.signals = [];
    addSignal(0);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      completeDemo();
      return;
    }
    demoState.running = true;
    demoById("colony-map").classList.add("running");
    demoById("demo-toggle").classList.add("is-running");
    demoById("demo-toggle").textContent = "Pause simulation";
    renderDemo();
  }

  function toggleDemo() {
    if (demoState.complete || demoState.day === 0) {
      startFreshDemo();
      return;
    }
    demoState.running = !demoState.running;
    demoById("colony-map").classList.toggle("running", demoState.running);
    demoById("demo-toggle").classList.toggle("is-running", demoState.running);
    demoById("demo-toggle").textContent = demoState.running ? "Pause simulation" : "Resume simulation";
    renderDemo();
  }

  function tickDemo() {
    if (!demoState.running) return;
    demoState.day += 1;
    addSignal(demoState.day);
    if (demoState.day >= FINAL_DAY) {
      completeDemo();
      return;
    }
    renderDemo();
  }

  function readyDemo() {
    demoById("demo-toggle").addEventListener("click", toggleDemo);
    demoById("demo-clock").addEventListener("animationiteration", tickDemo);
    renderDemo();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", readyDemo);
  } else {
    readyDemo();
  }
})();

(function () {
  var ACTIVITY_URL = "/v1/operational-activity";
  var PAGE_SIZE = 100;
  var MAX_EVENTS = 100;

  /* Defensive rendering filter. The backend already guarantees that event
   * payloads carry only safe structural facts; this list also keeps any
   * future payload key from ever being shown in the UI. */
  var SENSITIVE_PAYLOAD_KEYS = {
    input_values: true,
    policy: true,
    rules: true,
    outcome: true,
    evidence: true,
    recommendation: true,
    reasoning: true,
    prompt: true,
    secret: true,
    token: true,
    password: true,
  };

  /* OperationalActivityKind -> mission floor zone. */
  var ZONE_KINDS = {
    scenario_studio: ["scenario_registered"],
    world_forge: ["world_compiled"],
    domain_registry: [
      "domain_pack_registered",
      "domain_pack_bound",
      "capability_inputs_declared",
      "domain_state_model_declared",
      "domain_state_transition_declared",
    ],
    campaign_control: ["campaign_prepared", "campaign_started", "campaign_executed"],
    integrity_vault: ["run_inputs_verified", "run_replayed"],
  };

  /* Safe structural reference fields shown when present on an event. */
  var REF_FIELDS = [
    ["scenario_id", "scenario"],
    ["world_version_id", "world"],
    ["campaign_id", "campaign"],
    ["run_id", "run"],
    ["manifest_id", "manifest"],
    ["binding_id", "binding"],
    ["declaration_id", "declaration"],
  ];

  var state = {
    tenant: "",
    events: [], /* ascending by sequence; newest MAX_EVENTS only */
    latestSequence: -1,
    initialLoadDone: false,
    kalhasConnected: false,
    lastRequestTime: null,
    lastError: null,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function appendText(parent, value) {
    parent.appendChild(document.createTextNode(String(value)));
  }

  /* Show the exact source timestamp exactly as recorded. */
  function formatTime(value) {
    return String(value);
  }

  function safePayloadEntries(payload) {
    var source = payload || {};
    var entries = [];
    var keys = Object.keys(source);
    for (var i = 0; i < keys.length; i += 1) {
      var key = keys[i];
      if (!SENSITIVE_PAYLOAD_KEYS[key]) {
        entries.push([key, source[key]]);
      }
    }
    return entries;
  }

  function refEntries(event) {
    var entries = [];
    for (var i = 0; i < REF_FIELDS.length; i += 1) {
      var field = REF_FIELDS[i];
      var value = event[field[0]];
      if (value !== null && value !== undefined) {
        entries.push([field[1], value]);
      }
    }
    return entries;
  }

  function normalizeEvents(events) {
    var seen = {};
    var ordered = [];
    for (var i = 0; i < events.length; i += 1) {
      var event = events[i];
      if (!seen[event.sequence]) {
        seen[event.sequence] = true;
        ordered.push(event);
      }
    }
    ordered.sort(function (a, b) {
      return a.sequence - b.sequence;
    });
    if (ordered.length > MAX_EVENTS) {
      ordered = ordered.slice(ordered.length - MAX_EVENTS);
    }
    return ordered;
  }

  function historyTruncated() {
    /* Tenant-local sequences start at zero and never skip, so the total
     * number of events is latestSequence + 1. */
    return state.latestSequence + 1 > state.events.length;
  }

  function performRequest(query, onSuccess) {
    var tenant = byId("tenant-input").value.trim();
    if (!tenant) {
      state.lastError = "Enter a tenant identifier first.";
      render();
      return;
    }
    state.tenant = tenant;
    byId("load-button").disabled = true;
    fetch(ACTIVITY_URL + query, {
      headers: { "X-Tenant-ID": tenant },
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          var code = result.body && result.body.code ? result.body.code : "unknown";
          var message =
            result.body && result.body.message ? result.body.message : "The request was rejected.";
          state.lastError = "Request rejected (" + code + "): " + message;
          return;
        }
        state.lastError = null;
        state.kalhasConnected = true;
        state.lastRequestTime = new Date();
        state.latestSequence = result.body.latest_sequence;
        onSuccess(result.body.events);
      })
      .catch(function () {
        state.lastError = "Could not reach the local KALHAS API. Is the server running?";
      })
      .then(function () {
        byId("load-button").disabled = false;
        byId("load-button").textContent = state.initialLoadDone ? "Refresh" : "Load activity";
        render();
      });
  }

  function loadInitial() {
    state.initialLoadDone = false;
    performRequest("?after_sequence=-1&limit=100", function (events) {
      state.events = normalizeEvents(events);
      state.initialLoadDone = true;
    });
  }

  function refresh() {
    var cursor = state.events.length ? state.events[state.events.length - 1].sequence : -1;
    performRequest("?after_sequence=" + cursor + "&limit=" + PAGE_SIZE, function (events) {
      state.events = normalizeEvents(state.events.concat(events));
    });
  }

  function handleSubmit(event) {
    event.preventDefault();
    var tenant = byId("tenant-input").value.trim();
    if (state.initialLoadDone && tenant === state.tenant) {
      refresh();
      return;
    }
    /* A different tenant (or the first load) starts a fresh feed. */
    state.events = [];
    state.latestSequence = -1;
    state.kalhasConnected = false;
    loadInitial();
  }

  function render() {
    renderStatus();
    renderRail();
    renderZones();
    renderEvents();
    renderFooter();
  }

  function renderStatus() {
    var statusEl = byId("feed-status");
    var metaEl = byId("feed-meta");
    if (state.lastError) {
      statusEl.textContent = state.lastError;
      statusEl.className = "feed-status feed-status-error";
      metaEl.textContent = "";
      return;
    }
    if (!state.initialLoadDone) {
      statusEl.textContent = "No feed loaded yet. Enter a tenant identifier and press Load activity.";
      statusEl.className = "feed-status";
      metaEl.textContent = "";
      return;
    }
    if (state.events.length === 0) {
      statusEl.textContent = "Feed loaded: tenant '" + state.tenant + "' has no operational activity yet.";
    } else {
      statusEl.textContent =
        "Feed loaded: " + state.events.length + " event(s) in view. The feed updates only on manual refresh.";
    }
    statusEl.className = "feed-status feed-status-ok";
    metaEl.textContent =
      "Last received sequence: " +
      state.latestSequence +
      (state.lastRequestTime ? " · last successful request " + state.lastRequestTime.toISOString() : "");
  }

  function renderRail() {
    var light = byId("kalhas-light");
    var note = byId("kalhas-status");
    if (state.kalhasConnected) {
      light.className = "status-light light-on";
      note.textContent = "Connected - last activity request succeeded.";
    } else {
      light.className = "status-light light-off";
      note.textContent = "Not queried yet - connects after a successful activity request.";
    }
  }

  function renderZones() {
    var zoneNames = Object.keys(ZONE_KINDS);
    for (var i = 0; i < zoneNames.length; i += 1) {
      renderZone(zoneNames[i]);
    }
  }

  function renderZone(zone) {
    var latest = null;
    for (var i = state.events.length - 1; i >= 0; i -= 1) {
      var event = state.events[i];
      if (ZONE_KINDS[zone].indexOf(event.kind) !== -1) {
        latest = event;
        break;
      }
    }
    var zoneEl = byId("zone-" + zone);
    var kindEl = byId("zone-" + zone + "-kind");
    var timeEl = byId("zone-" + zone + "-time");
    var refsEl = byId("zone-" + zone + "-refs");
    refsEl.textContent = "";
    if (!latest) {
      zoneEl.classList.remove("observed");
      kindEl.textContent = "No activity observed in the loaded feed";
      timeEl.textContent = "";
      return;
    }
    zoneEl.classList.add("observed");
    kindEl.textContent = latest.kind;
    timeEl.textContent = formatTime(latest.occurred_at);
    var entries = refEntries(latest);
    for (var j = 0; j < entries.length; j += 1) {
      var dt = document.createElement("dt");
      var dd = document.createElement("dd");
      appendText(dt, entries[j][0]);
      appendText(dd, entries[j][1]);
      refsEl.appendChild(dt);
      refsEl.appendChild(dd);
    }
  }

  function renderEvents() {
    var listEl = byId("event-list");
    var emptyEl = byId("empty-state");
    listEl.textContent = "";
    if (state.events.length === 0) {
      emptyEl.hidden = state.initialLoadDone ? false : true;
      return;
    }
    emptyEl.hidden = true;
    var descending = state.events.slice().reverse();
    for (var i = 0; i < descending.length; i += 1) {
      listEl.appendChild(renderEvent(descending[i]));
    }
  }

  function renderEvent(event) {
    var item = document.createElement("li");
    item.className = "event";

    var header = document.createElement("div");
    header.className = "event-header";
    var seq = document.createElement("span");
    seq.className = "event-seq";
    appendText(seq, "#" + String(event.sequence).padStart(4, "0"));
    var kind = document.createElement("span");
    kind.className = "event-kind";
    appendText(kind, event.kind);
    var time = document.createElement("time");
    time.className = "event-time";
    time.dateTime = String(event.occurred_at);
    appendText(time, formatTime(event.occurred_at));
    header.appendChild(seq);
    header.appendChild(kind);
    header.appendChild(time);
    item.appendChild(header);

    var refs = refEntries(event);
    if (refs.length > 0) {
      var refsDl = document.createElement("dl");
      refsDl.className = "event-refs";
      for (var i = 0; i < refs.length; i += 1) {
        var dt = document.createElement("dt");
        var dd = document.createElement("dd");
        appendText(dt, refs[i][0]);
        appendText(dd, refs[i][1]);
        refsDl.appendChild(dt);
        refsDl.appendChild(dd);
      }
      item.appendChild(refsDl);
    }

    var payload = safePayloadEntries(event.payload);
    if (payload.length > 0) {
      var payloadDl = document.createElement("dl");
      payloadDl.className = "event-payload";
      for (var j = 0; j < payload.length; j += 1) {
        var pdt = document.createElement("dt");
        var pdd = document.createElement("dd");
        appendText(pdt, payload[j][0]);
        appendText(pdd, JSON.stringify(payload[j][1]));
        payloadDl.appendChild(pdt);
        payloadDl.appendChild(pdd);
      }
      item.appendChild(payloadDl);
    }
    return item;
  }

  function renderFooter() {
    var oldest = byId("oldest-loaded");
    var newest = byId("newest-loaded");
    var latest = byId("api-latest");
    var older = byId("older-history");
    if (state.events.length === 0) {
      oldest.textContent = "-";
      newest.textContent = "-";
    } else {
      oldest.textContent = String(state.events[0].sequence);
      newest.textContent = String(state.events[state.events.length - 1].sequence);
    }
    latest.textContent = String(state.latestSequence);
    older.textContent = state.initialLoadDone
      ? historyTruncated()
        ? "yes - older activity exists beyond the loaded window"
        : "no - all activity is in view"
      : "-";
  }

  function onReady() {
    byId("tenant-form").addEventListener("submit", handleSubmit);
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }
})();
