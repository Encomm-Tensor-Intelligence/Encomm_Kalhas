"use strict";

/*
 * KALHAS Lab client.
 *
 * Executes demo_flow.json step by step against the same local app, then draws the returned
 * artifacts. Every value shown comes from a real response; nothing is simulated in the page.
 */

const $ = (id) => document.getElementById(id);
const SVG_NS = $("fig-decision").namespaceURI;
const PALETTE = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"];
const PACE_MS = 220;
const LOG_LIMIT = 300;

let flow = null;
let index = 0;
let tenantNumber = 1;
let captures = {};
let responses = {};
let details = {};
let busy = false;
let started = performance.now();
let logCount = 0;
let drawn = new Set();

const tenant = () => `lab-demo-${tenantNumber}`;

/* DOM helpers ------------------------------------------------------------ */

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  if (cls) {
    node.className = cls;
  }
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function svg(parent, tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  if (text !== undefined) {
    node.textContent = String(text);
  }
  parent.append(node);
  return node;
}

function fmt(value, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "–";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

function fixed(value) {
  return typeof value === "number" ? value.toFixed(2) : "–";
}

function short(hash) {
  return typeof hash === "string" ? hash.slice(0, 12) : "–";
}

/* Flow interpreter -------------------------------------------------------- */

function safePath(path) {
  const url = new URL(path, location.origin);
  const allowed =
    url.pathname === "/health" ||
    url.pathname.startsWith("/v1/") ||
    url.pathname.startsWith("/lab/");
  if (
    !path.startsWith("/") ||
    path.startsWith("//") ||
    url.origin !== location.origin ||
    !allowed
  ) {
    throw new Error(`Disallowed path: ${path}`);
  }
  return path;
}

function pointer(value, path) {
  if (path === "") {
    return value;
  }
  if (!path.startsWith("/")) {
    throw new Error(`Invalid JSON pointer: ${path}`);
  }
  return path
    .slice(1)
    .split("/")
    .reduce((current, raw) => {
      const key = raw.replace(/~1/g, "/").replace(/~0/g, "~");
      if (current === null || typeof current !== "object" || !(key in current)) {
        throw new Error(`Missing JSON pointer: ${path}`);
      }
      return current[key];
    }, value);
}

function substitute(value, item) {
  if (typeof value === "string") {
    return value.replace(/\{([^{}]+)\}/g, (_, name) => {
      let result;
      if (name === "tenant") {
        result = tenant();
      } else if (name === "item") {
        result = item;
      } else if (name.startsWith("item.")) {
        result = name
          .slice(5)
          .split(".")
          .reduce((current, key) => (current == null ? undefined : current[key]), item);
      } else {
        result = captures[name];
      }
      if (result === undefined || result === null || typeof result === "object") {
        throw new Error(`Unknown or non-scalar placeholder: ${name}`);
      }
      return String(result);
    });
  }
  if (Array.isArray(value)) {
    return value.map((entry) => substitute(entry, item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, substitute(entry, item)]),
    );
  }
  return value;
}

function log(method, path, status, elapsed) {
  const list = $("log");
  const ok = typeof status === "number" && status >= 200 && status < 400;
  const row = el("li");
  row.append(
    el("span", `${((performance.now() - started) / 1000).toFixed(1)} s`, "when"),
    el("span", `${method} ${path}`, "what"),
    el("span", `${status} in ${elapsed} ms`, ok ? "ok" : "bad"),
  );
  list.prepend(row);
  while (list.children.length > LOG_LIMIT) {
    list.lastElementChild.remove();
  }
  logCount += 1;
  $("log-count").textContent = String(logCount);
}

async function request(method, path, body) {
  path = safePath(path);
  const options = { method, headers: { "X-Tenant-ID": tenant() } };
  if (body !== null && body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const start = performance.now();
  try {
    const response = await fetch(path, options);
    const raw = await response.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
    const ms = Math.round(performance.now() - start);
    log(method, path, response.status, ms);
    return { status: response.status, data, ms };
  } catch (error) {
    log(method, path, "network error", Math.round(performance.now() - start));
    throw error;
  }
}

function findHash(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  if (typeof value.content_hash === "string") {
    return value.content_hash;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (key.includes("hash") && typeof entry === "string" && /^[0-9a-f]{64}$/.test(entry)) {
      return entry;
    }
  }
  for (const entry of Object.values(value)) {
    const found = findHash(entry);
    if (found) {
      return found;
    }
  }
  return null;
}

function figureWidth(node, low, high) {
  const measured = Math.round(node.getBoundingClientRect().width);
  return Math.min(high, Math.max(low, measured || high));
}

/* Flow-derived facts -------------------------------------------------------- */

function flowBody(predicate) {
  const step = flow ? flow.steps.find(predicate) : undefined;
  return step ? step.body : null;
}

function stateField() {
  const body = flowBody((step) => step.path.endsWith("/domain-state-models"));
  return body && body.state_fields.length ? body.state_fields[0].identifier : null;
}

function transitionTargets() {
  const targets = {};
  for (const step of flow.steps) {
    if (step.path.endsWith("/domain-state-transitions")) {
      targets[step.body.transition_id] = step.body.target_values;
    }
  }
  return targets;
}

function uncertainty() {
  const body = flowBody((step) => step.path.endsWith("/uncertainty-model"));
  const binding = body && body.bindings.length ? body.bindings[0] : null;
  return binding ? { ...binding.distribution, rounding: binding.rounding_policy } : null;
}

function policy() {
  return flowBody((step) => step.path.endsWith("/decision-policy")) || {};
}

function objective() {
  const world = responses.compile && responses.compile.version.world;
  return world && world.scenario.objectives.length ? world.scenario.objectives[0] : null;
}

function strategies() {
  if (responses.statistics) {
    return responses.statistics.ordered_strategy_candidate_ids;
  }
  const seen = [];
  for (const run of captures.runs || []) {
    if (!seen.includes(run.strategy_candidate_id)) {
      seen.push(run.strategy_candidate_id);
    }
  }
  return seen;
}

function colorOf(strategyId) {
  const position = Math.max(0, strategies().indexOf(strategyId));
  return PALETTE[position % PALETTE.length];
}

function labelOf(strategyId) {
  return String(strategyId).replace(/^mock-/, "");
}

function median(values) {
  const sorted = values.slice().sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/* Paths are rebuilt from kernel-reported endpoints and applied transition targets. */
function trajectoryPaths() {
  const field = stateField();
  const targets = transitionTargets();
  const byStrategy = new Map();
  for (const execution of captures.trajectory_runs || []) {
    const result = execution.results[0];
    if (!result || !field) {
      continue;
    }
    const points = [result.initial_state[field]];
    for (const attempt of result.attempts) {
      const target = targets[attempt.transition_id];
      const applied = attempt.outcome === "applied" && target && field in target;
      points.push(applied ? target[field] : points[points.length - 1]);
    }
    points[points.length - 1] = result.final_state[field];
    const sequence = result.attempts.map((attempt) => attempt.transition_id);
    const entry = byStrategy.get(execution.strategy_candidate_id) || { runs: [], sequence };
    entry.runs.push({ seed: execution.scenario_seed_id, points });
    byStrategy.set(execution.strategy_candidate_id, entry);
  }
  return byStrategy;
}

/* Provenance chain ------------------------------------------------------- */

function stepCount(step) {
  if (!step.for_each) {
    return "";
  }
  const items = captures[step.for_each];
  return Array.isArray(items) ? ` ×${items.length}` : " ×N";
}

function copyChip(hash) {
  const chip = el("span", short(hash), "hash");
  chip.title = `Copy ${hash}`;
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    navigator.clipboard
      .writeText(hash)
      .then(() => {
        chip.textContent = "copied";
      })
      .catch(() => {
        chip.textContent = hash;
      });
  });
  return chip;
}

function drawPipeline() {
  const list = $("pipeline");
  clear(list);
  let lastStage = null;
  for (const [position, step] of flow.steps.entries()) {
    if (step.stage !== lastStage) {
      lastStage = step.stage;
      const members = flow.steps.filter((candidate) => candidate.stage === step.stage);
      const done = members.filter((member) => (details[member.id] || {}).state === "ok").length;
      const heading = el("li", step.stage, "chain__group");
      heading.append(el("span", `  ${done} of ${members.length}`));
      list.append(heading);
    }
    const data = details[step.id] || {};
    const item = el("li", undefined, `link ${data.state || "idle"}`);
    const button = el("button");
    button.type = "button";
    const title = el("span", undefined, "link__title");
    title.append(el("span", String(position + 1).padStart(2, "0"), "link__n"), step.title);
    title.append(stepCount(step));
    const elapsed = data.last ? `${data.totalMs} ms` : "";
    button.append(el("span", undefined, "link__dot"), title, el("span", elapsed, "link__ms"));
    const meta = el("span", undefined, "link__meta");
    meta.append(el("span", step.kind === "lab" ? "in-process" : "HTTP", tagClass(step)));
    meta.append(el("span", `${step.method} ${step.path.replace(/\{[^}]+\}/g, "…")}`));
    const hash = findHash(data.last && data.last.response);
    if (hash) {
      meta.append(copyChip(hash));
    }
    button.append(meta);
    if (data.error) {
      button.append(el("span", data.error, "link__error"));
    }
    button.addEventListener("click", () => showDrawer(step));
    item.append(button);
    list.append(item);
  }
  $("progress").textContent = `${index} of ${flow.steps.length}`;
  $("meter-fill").style.width = `${(100 * index) / flow.steps.length}%`;
}

function tagClass(step) {
  return step.kind === "lab" ? "tag tag--lab" : "tag";
}

function showDrawer(step) {
  $("drawer-title").textContent = step.title;
  const content = $("drawer-body");
  clear(content);
  const data = details[step.id];
  const entries = (data && data.entries) || [];
  if (!entries.length) {
    content.append(el("p", "This step has not run yet.", "plate__empty"));
  }
  for (const entry of entries.slice(0, 3)) {
    content.append(
      el("h3", `${entry.method} ${entry.path}, status ${entry.status}, ${entry.ms} ms`),
      el("h3", "Request body"),
      el("pre", JSON.stringify(entry.request, null, 2)),
      el("h3", "Response body"),
      el("pre", JSON.stringify(entry.response, null, 2)),
    );
  }
  if (entries.length > 3) {
    content.append(el("p", `${entries.length - 3} more requests are in the log.`, "plate__empty"));
  }
  if (data && data.error) {
    content.append(el("h3", "Error"), el("pre", data.error));
  }
  $("drawer").showModal();
}

/* Specimen ---------------------------------------------------------------- */

function fact(list, term, value, mono) {
  const row = el("div");
  row.append(el("dt", term), el("dd", value, mono ? "mono" : undefined));
  list.append(row);
}

function renderSpecimen() {
  const list = $("specimen");
  clear(list);
  const version = responses.compile.version;
  const world = version.world;
  const goal = objective();
  const spread = uncertainty();
  const field = stateField();
  fact(list, "World", version.identifier, true);
  fact(list, "Content hash", short(version.content_hash), true);
  fact(list, "Scenario", world.scenario.name);
  if (goal) {
    fact(list, "Objective", `${goal.direction} ${goal.identifier}, target ${fmt(goal.target)}`);
  }
  if (spread && field) {
    const law = `${field} ~ ${spread.kind}(${fmt(spread.low)}, ${fmt(spread.high)})`;
    fact(list, "Uncertainty", law);
  }
  if (captures.runs) {
    const seeds = new Set(captures.runs.map((run) => run.scenario_seed_id));
    fact(list, "Ensemble", `${seeds.size} seeds × ${strategies().length} strategies`);
    fact(list, "Runs", String(captures.runs.length));
    fact(list, "Runtime", captures.runs[0].runtime_version || "–", true);
  }
}

/* Figure 1 ---------------------------------------------------------------- */

function valueDomain(paths) {
  let high = 10;
  const spread = uncertainty();
  if (spread && typeof spread.high === "number") {
    high = Math.max(high, spread.high);
  }
  for (const entry of paths.values()) {
    for (const run of entry.runs) {
      high = Math.max(high, ...run.points);
    }
  }
  return [0, Math.ceil(high)];
}

function renderWorlds(paths, domain) {
  const root = $("fig-worlds");
  clear(root);
  const width = figureWidth(root, 320, 1200);
  root.setAttribute("viewBox", `0 0 ${width} 104`);
  const left = 64;
  const right = width - 12;
  const x = (value) => left + ((value - domain[0]) / (domain[1] - domain[0])) * (right - left);
  const spread = uncertainty();
  if (spread && spread.kind === "uniform") {
    svg(root, "rect", {
      x: x(spread.low),
      y: 22,
      width: x(spread.high) - x(spread.low),
      height: 48,
      class: "band",
    });
    svg(
      root,
      "text",
      { x: x(spread.high), y: 14, "text-anchor": "end" },
      `declared ${spread.kind} range`,
    );
  }
  svg(root, "line", { x1: left, y1: 70, x2: right, y2: 70, class: "axis" });
  for (let tick = domain[0]; tick <= domain[1]; tick += 1) {
    svg(root, "line", { x1: x(tick), y1: 70, x2: x(tick), y2: 75, class: "axis" });
    svg(root, "text", { x: x(tick), y: 92, "text-anchor": "middle" }, tick);
  }
  const first = paths.values().next().value;
  svg(root, "text", { x: 0, y: 44, class: "label-strong" }, "Worlds");
  svg(root, "text", { x: 0, y: 60 }, `${first ? first.runs.length : 0} seeds`);
  const stacks = new Map();
  for (const run of first ? first.runs : []) {
    const value = run.points[0];
    const height = stacks.get(value) || 0;
    stacks.set(value, height + 1);
    const dot = svg(root, "circle", {
      cx: x(value),
      cy: 62 - height * 10,
      r: 4.5,
      fill: "var(--text)",
    });
    svg(dot, "title", {}, `${run.seed}: initial ${stateField()} ${value}`);
  }
}

function renderEnsemble() {
  const paths = trajectoryPaths();
  if (!paths.size) {
    return;
  }
  const domain = valueDomain(paths);
  renderWorlds(paths, domain);
  const root = $("ensemble");
  clear(root);
  root.classList.add("draws");
  const goal = objective();
  const order = strategies().filter((id) => paths.has(id));
  for (const strategyId of order) {
    root.append(ensemblePanel(strategyId, paths.get(strategyId), domain, goal));
  }
}

function ensemblePanel(strategyId, entry, domain, goal) {
  const color = colorOf(strategyId);
  const panel = el("div", undefined, "ensemble__panel");
  const heading = el("h3");
  const swatch = el("i");
  swatch.style.background = color;
  heading.append(swatch, labelOf(strategyId));
  const steps = entry.sequence.map((id) => id.replace(/^set-/, "")).join(" → ");
  panel.append(heading, el("p", steps));
  const width = 200;
  const height = 170;
  const pad = { left: 24, right: 8, top: 8, bottom: 22 };
  const figure = document.createElementNS(SVG_NS, "svg");
  figure.setAttribute("viewBox", `0 0 ${width} ${height}`);
  figure.setAttribute("class", "fig");
  figure.setAttribute("role", "img");
  figure.setAttribute("aria-label", `Trajectories for ${labelOf(strategyId)}`);
  const count = entry.runs[0].points.length;
  const x = (i) => pad.left + (i / (count - 1)) * (width - pad.left - pad.right);
  const y = (v) =>
    height -
    pad.bottom -
    ((v - domain[0]) / (domain[1] - domain[0])) * (height - pad.top - pad.bottom);
  for (const tick of [domain[0], (domain[0] + domain[1]) / 2, domain[1]]) {
    svg(figure, "line", {
      x1: pad.left,
      y1: y(tick),
      x2: width - pad.right,
      y2: y(tick),
      class: "grid",
    });
    svg(figure, "text", { x: pad.left - 6, y: y(tick) + 4, "text-anchor": "end" }, fmt(tick, 0));
  }
  for (let i = 0; i < count; i += 1) {
    svg(figure, "text", { x: x(i), y: height - 6, "text-anchor": "middle" }, `t${i}`);
  }
  if (goal) {
    svg(figure, "line", {
      x1: pad.left,
      y1: y(goal.target),
      x2: width - pad.right,
      y2: y(goal.target),
      class: "target",
    });
  }
  const line = (points) => points.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  for (const [i, run] of entry.runs.entries()) {
    const path = svg(figure, "polyline", {
      points: line(run.points),
      class: "seed-path",
      stroke: color,
      style: `--i:${i}`,
    });
    svg(path, "title", {}, `${run.seed}: ${run.points.join(" → ")}`);
  }
  const center = [];
  for (let i = 0; i < count; i += 1) {
    center.push(median(entry.runs.map((run) => run.points[i])));
  }
  svg(figure, "polyline", {
    points: line(center),
    class: "median-path",
    stroke: color,
    style: `--i:${entry.runs.length}`,
  });
  const end = svg(figure, "circle", {
    cx: x(count - 1),
    cy: y(center[count - 1]),
    r: 4,
    fill: color,
  });
  svg(end, "title", {}, `median final ${stateField()}: ${fmt(center[count - 1])}`);
  panel.append(figure);
  return panel;
}

/* Figure 2 ---------------------------------------------------------------- */

function renderDecision() {
  const comparison = responses.comparison;
  const root = $("fig-decision");
  clear(root);
  const width = figureWidth(root, 320, 640);
  const height = width < 440 ? 300 : 340;
  root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const pad = { left: 58, right: 24, top: 20, bottom: 50 };
  const profiles = comparison.robustness_profiles.map((profile) => ({
    id: profile.strategy_candidate_id,
    regret: profile.median_total_weighted_regret,
    probability: profile.target_achievement_probabilities.length
      ? profile.target_achievement_probabilities[0].empirical_target_achievement_probability
      : 0,
    feasible: profile.feasible,
    dominated: profile.dominated_by.length,
  }));
  const maxRegret = Math.max(0.1, ...profiles.map((p) => p.regret)) * 1.15;
  const inset = 22;
  const x = (v) => pad.left + inset + (v / maxRegret) * (width - pad.left - pad.right - inset);
  const span = height - pad.top - pad.bottom;
  const y = (v) => height - pad.bottom - ((v + 0.08) / 1.16) * span;
  const threshold = policy().minimum_target_achievement_probability;
  if (typeof threshold === "number") {
    svg(root, "rect", {
      x: pad.left,
      y: pad.top,
      width: width - pad.left - pad.right,
      height: y(threshold) - pad.top,
      class: "band",
    });
    svg(root, "line", {
      x1: pad.left,
      y1: y(threshold),
      x2: width - pad.right,
      y2: y(threshold),
      class: "target",
    });
    svg(
      root,
      "text",
      { x: width - pad.right, y: y(threshold) - 6, "text-anchor": "end", class: "label-target" },
      `feasibility threshold ${fmt(threshold)}`,
    );
  }
  for (const tick of [0, 0.25, 0.5, 0.75, 1]) {
    svg(root, "line", { x1: pad.left, y1: y(tick), x2: pad.left - 5, y2: y(tick), class: "axis" });
    svg(root, "text", { x: pad.left - 9, y: y(tick) + 4, "text-anchor": "end" }, fmt(tick));
  }
  const xTicks = 4;
  for (let i = 0; i <= xTicks; i += 1) {
    const value = (maxRegret * i) / xTicks;
    svg(root, "line", {
      x1: x(value),
      y1: height - pad.bottom,
      x2: x(value),
      y2: height - pad.bottom + 5,
      class: "axis",
    });
    svg(
      root,
      "text",
      { x: x(value), y: height - pad.bottom + 19, "text-anchor": "middle" },
      fmt(value),
    );
  }
  svg(root, "line", {
    x1: pad.left,
    y1: height - pad.bottom,
    x2: width - pad.right,
    y2: height - pad.bottom,
    class: "axis",
  });
  svg(root, "line", {
    x1: pad.left,
    y1: pad.top,
    x2: pad.left,
    y2: height - pad.bottom,
    class: "axis",
  });
  svg(
    root,
    "text",
    { x: (pad.left + width - pad.right) / 2, y: height - 8, "text-anchor": "middle" },
    "median total weighted regret (lower is better)",
  );
  svg(
    root,
    "text",
    {
      x: -(pad.top + height - pad.bottom) / 2,
      y: 16,
      transform: "rotate(-90)",
      "text-anchor": "middle",
    },
    "P(target reached)",
  );
  const groups = new Map();
  for (const profile of profiles) {
    const key = `${profile.regret.toFixed(6)}|${profile.probability.toFixed(6)}`;
    groups.set(key, [...(groups.get(key) || []), profile]);
  }
  const placed = [];
  const clusters = [...groups.values()].sort((a, b) => a[0].regret - b[0].regret);
  for (const members of clusters) {
    const spacing = 15;
    const base = members[0];
    const cx = x(base.regret);
    const cy = y(base.probability);
    members.forEach((member, i) => {
      const offset = (i - (members.length - 1) / 2) * spacing;
      const dot = svg(root, "circle", {
        cx: cx + offset,
        cy,
        r: 6.5,
        fill: member.feasible ? colorOf(member.id) : "var(--plate)",
        stroke: colorOf(member.id),
        "stroke-width": 2,
      });
      const status = member.feasible ? "feasible" : "infeasible";
      svg(dot, "title", {}, `${labelOf(member.id)}: ${status}, dominated by ${member.dominated}`);
    });
    const names = members.map((member) => labelOf(member.id)).join(" and ");
    const anchor = cx > width * 0.62 ? "end" : "start";
    const labelX = anchor === "end" ? cx + members.length * 8 : cx - members.length * 8;
    const below = cy < (pad.top + height - pad.bottom) / 2;
    const note = members.length > 1 ? " (same point)" : "";
    const text = `${names}${note}`;
    const textWidth = text.length * 6.6;
    const box = (top) => ({
      left: anchor === "end" ? labelX - textWidth : labelX,
      right: anchor === "end" ? labelX : labelX + textWidth,
      top,
    });
    let labelY = below ? cy + 24 : cy - 16;
    const overlaps = (candidate) =>
      placed.some(
        (other) =>
          Math.abs(other.top - candidate.top) < 15 &&
          candidate.left < other.right &&
          candidate.right > other.left,
      );
    while (overlaps(box(labelY))) {
      labelY += below ? 15 : -15;
    }
    placed.push(box(labelY));
    svg(root, "text", { x: labelX, y: labelY, "text-anchor": anchor, class: "label-strong" }, text);
  }
  renderVerdict();
}

function renderVerdict() {
  const root = $("verdict");
  clear(root);
  const brief = responses.brief;
  if (!brief) {
    root.append(el("p", "Waiting for the decision brief.", "plate__empty"));
    return;
  }
  const preferred = brief.preferred_strategy_id;
  const title = preferred ? `Preferred: ${labelOf(preferred)}` : "Inconclusive";
  root.append(
    el("div", title, `verdict__status ${preferred ? "preferred" : "inconclusive"}`),
    el("p", brief.summary, "verdict__summary"),
  );
  if (brief.terminal_reason) {
    const reason = el("p", "Terminal reason ", "verdict__reason");
    reason.append(el("span", brief.terminal_reason.code, "mono"));
    root.append(reason);
  }
}

/* Figure 3 ---------------------------------------------------------------- */

function hashRow(label, value, other) {
  const row = el("div", undefined, "hashgrid__row");
  const cells = el("div", undefined, "hashgrid__cells");
  [...value].forEach((char, i) => {
    const cell = el("b", char, char === other[i] ? "same" : "diff");
    cell.style.setProperty("--i", String(i));
    cells.append(cell);
  });
  row.append(el("span", label), cells);
  return row;
}

function renderReplay() {
  const root = $("replay");
  clear(root);
  root.classList.add("draws");
  const verify = responses.verify;
  const replay = responses.replay;
  const expected = verify.expected_input_hash;
  const recomputed = verify.recomputed_input_hash;
  const exact =
    verify.verification_classification === "exact" &&
    replay.replay_classification === "exact" &&
    expected === recomputed;
  const status = el("div", exact ? "Replay exact" : "Replay mismatch", "replay__status");
  status.classList.add(exact ? "exact" : "mismatch");
  status.append(el("small", exact ? "64 of 64 characters match" : "see the drawer for details"));
  const grid = el("div", undefined, "hashgrid");
  grid.append(
    hashRow("Recorded input", expected, recomputed),
    hashRow("Recomputed", recomputed, expected),
  );
  const facts = el("dl", undefined, "replay__facts");
  const pairs = [
    ["Run", replay.run_id],
    ["Strategy", labelOf(replay.strategy_candidate_id)],
    ["Seed", replay.scenario_seed_id],
    ["Verification", verify.verification_classification],
    ["Replay", replay.replay_classification],
    ["Event hash", short(replay.expected_event_hash)],
  ];
  for (const [term, value] of pairs) {
    facts.append(el("dt", term), el("dd", value, "mono"));
  }
  root.append(status, grid, facts);
}

/* Table 1 ----------------------------------------------------------------- */

function renderTable() {
  const body = $("outcomes");
  clear(body);
  const outcomes = responses.outcomes.outcomes;
  const profiles = new Map(
    ((responses.comparison && responses.comparison.robustness_profiles) || []).map((p) => [
      p.strategy_candidate_id,
      p,
    ]),
  );
  const paths = trajectoryPaths();
  const all = outcomes.flatMap((o) => [
    o.empirical_distribution.minimum,
    o.empirical_distribution.maximum,
  ]);
  const low = Math.min(0, ...all);
  const high = Math.max(10, ...all);
  for (const outcome of outcomes) {
    const id = outcome.strategy_candidate_id;
    const dist = outcome.empirical_distribution;
    const profile = profiles.get(id);
    const row = el("tr");
    const name = el("td");
    const swatch = el("span", undefined, "swatch");
    swatch.style.background = colorOf(id);
    name.append(swatch, labelOf(id));
    const entry = paths.get(id);
    const sequence = entry ? entry.sequence.map((t) => t.replace(/^set-/, "")).join(" → ") : "–";
    row.append(
      name,
      el("td", sequence, "seq"),
      el("td", fmt(dist.minimum), "num"),
      el("td", fmt(dist.median), "num"),
      el("td", fmt(dist.maximum), "num"),
      rangeCell(dist, low, high, colorOf(id), outcome.target),
      el("td", fixed(outcome.empirical_target_achievement_probability), "num"),
      el("td", profile ? fixed(profile.median_total_weighted_regret) : "–", "num"),
      el(
        "td",
        profile ? (profile.feasible ? "yes" : "no") : "–",
        profile && profile.feasible ? "feasible-yes" : "feasible-no",
      ),
    );
    body.append(row);
  }
}

function rangeCell(dist, low, high, color, target) {
  const cell = el("td", undefined, "range-col");
  const figure = document.createElementNS(SVG_NS, "svg");
  figure.setAttribute("viewBox", "0 0 160 18");
  figure.setAttribute("class", "fig");
  const x = (v) => 4 + ((v - low) / (high - low)) * 152;
  svg(figure, "line", { x1: 4, y1: 9, x2: 156, y2: 9, class: "grid" });
  if (typeof target === "number") {
    svg(figure, "line", { x1: x(target), y1: 2, x2: x(target), y2: 16, class: "target" });
  }
  svg(figure, "line", {
    x1: x(dist.minimum),
    y1: 9,
    x2: x(dist.maximum),
    y2: 9,
    stroke: color,
    "stroke-width": 4,
    "stroke-linecap": "round",
  });
  svg(figure, "circle", { cx: x(dist.median), cy: 9, r: 4, fill: "var(--text)" });
  cell.append(figure);
  return cell;
}

/* Activity ---------------------------------------------------------------- */

async function refreshActivity() {
  const result = await request("GET", "/v1/operational-activity", null);
  if (result.status !== 200) {
    throw new Error(`Activity returned ${result.status}`);
  }
  const events = Array.isArray(result.data.events) ? result.data.events : [];
  const list = $("activity");
  clear(list);
  $("activity-count").textContent = String(events.length);
  for (const event of events.slice().reverse()) {
    const row = el("li");
    const subject =
      event.run_id || event.campaign_id || event.world_version_id || event.scenario_id || "";
    row.append(
      el("span", `#${event.sequence}`, "when"),
      el("span", String(event.kind || "event").replace(/_/g, " "), "what"),
      el("span", subject, "when"),
    );
    list.append(row);
  }
}

/* Rendering --------------------------------------------------------------- */

function renderOnce(key, ready, draw) {
  if (ready && !drawn.has(key)) {
    drawn.add(key);
    draw();
  }
}

function render() {
  renderOnce("specimen-world", responses.compile && !captures.runs, renderSpecimen);
  renderOnce("specimen-runs", responses.compile && captures.runs, renderSpecimen);
  renderOnce("ensemble", captures.trajectory_runs, renderEnsemble);
  renderOnce("decision", responses.comparison, renderDecision);
  renderOnce("verdict", responses.brief, renderVerdict);
  renderOnce("outcomes", responses.outcomes && responses.comparison, renderTable);
  renderOnce("replay", responses.verify && responses.replay, renderReplay);
}

function controls() {
  const finished = !flow || index >= flow.steps.length;
  $("run").disabled = busy || finished;
  $("step").disabled = busy || finished;
  $("reset").disabled = busy;
}

async function next() {
  const step = flow.steps[index];
  const data = { state: "running", entries: [], totalMs: 0 };
  details[step.id] = data;
  drawPipeline();
  try {
    const items = step.for_each ? captures[step.for_each] : [undefined];
    if (!Array.isArray(items)) {
      throw new Error(`Missing captured array: ${step.for_each}`);
    }
    const collected = {};
    for (const item of items) {
      const path = substitute(step.path, item);
      const body = substitute(step.body, item);
      let result;
      try {
        result = await request(step.method, path, body);
      } catch (error) {
        data.entries.push({ method: step.method, path, request: body, response: String(error) });
        throw error;
      }
      const entry = {
        method: step.method,
        path,
        request: body,
        response: result.data,
        status: result.status,
        ms: result.ms,
      };
      data.entries.push(entry);
      data.last = entry;
      data.totalMs += result.ms;
      if (result.status !== step.expect_status) {
        throw new Error(`Expected ${step.expect_status}, received ${result.status}`);
      }
      for (const [name, ptr] of Object.entries(step.capture)) {
        const value = pointer(result.data, ptr);
        if (step.for_each) {
          (collected[name] ||= []).push(value);
        } else {
          captures[name] = value;
        }
      }
      responses[step.id] = result.data;
    }
    Object.assign(captures, collected);
    await refreshActivity();
    data.state = "ok";
    index += 1;
    render();
  } catch (error) {
    data.state = "failed";
    data.error = String(error);
    drawPipeline();
    throw error;
  }
  drawPipeline();
}

async function run(full) {
  busy = true;
  controls();
  try {
    do {
      await next();
      if (full && index < flow.steps.length) {
        await new Promise((resolve) => setTimeout(resolve, PACE_MS));
      }
    } while (full && index < flow.steps.length);
  } catch {
    /* The failed step keeps its error in the chain and in its drawer. */
  } finally {
    busy = false;
    controls();
  }
}

function emptyMessage(id, message) {
  $(id).replaceChildren(el("p", message, "plate__empty"));
}

async function claimTenant(from) {
  for (let n = from; n < from + 100; n += 1) {
    tenantNumber = n;
    const result = await request("GET", "/v1/operational-activity", null);
    const events = result.status === 200 ? result.data.events : null;
    if (Array.isArray(events) && events.length === 0) {
      $("tenant").textContent = tenant();
      return;
    }
  }
  throw new Error("No unused lab tenant found; restart the Lab server.");
}

async function reset() {
  busy = true;
  controls();
  index = 0;
  captures = {};
  responses = {};
  details = {};
  drawn = new Set();
  logCount = 0;
  started = performance.now();
  $("tenant").textContent = tenant();
  const specimen = $("specimen");
  clear(specimen);
  const pending = el("div");
  pending.append(
    el("dt", "World"),
    el("dd", "Compiled when the pipeline reaches step 13", "pending"),
  );
  specimen.append(pending);
  emptyMessage("ensemble", "The ensemble draws itself once the runs are loaded.");
  $("ensemble").classList.remove("draws");
  clear($("fig-worlds"));
  clear($("fig-decision"));
  emptyMessage("verdict", "The decision brief appears after the comparison.");
  emptyMessage("replay", "Replay proof appears after the last two steps.");
  $("replay").classList.remove("draws");
  const empty = el("tr");
  const cell = el("td", "No outcomes yet.", "plate__empty");
  cell.colSpan = 9;
  empty.append(cell);
  $("outcomes").replaceChildren(empty);
  clear($("log"));
  clear($("activity"));
  $("log-count").textContent = "0";
  $("activity-count").textContent = "0";
  try {
    await claimTenant(tenantNumber + 1);
  } catch (error) {
    $("health").textContent = String(error);
  }
  busy = false;
  drawPipeline();
  controls();
}

$("run").addEventListener("click", () => run(true));
$("step").addEventListener("click", () => run(false));
$("reset").addEventListener("click", reset);
$("close-drawer").addEventListener("click", () => $("drawer").close());
window.addEventListener("resize", () => {
  if (drawn.has("ensemble")) {
    renderWorlds(trajectoryPaths(), valueDomain(trajectoryPaths()));
  }
  if (drawn.has("decision")) {
    renderDecision();
  }
});

(async () => {
  controls();
  try {
    const health = await request("GET", "/health", null);
    const online = health.status === 200;
    $("health").textContent = online ? "Online" : "Unavailable";
    $("health-dot").className = `lamp ${online ? "ok" : "failed"}`;
    const info = await request("GET", "/v1/system-info", null);
    $("version").textContent = info.data.application_version || info.data.version || "–";
    const result = await request("GET", "/lab/demo_flow.json", null);
    if (result.status !== 200) {
      throw new Error(`Flow returned ${result.status}`);
    }
    flow = result.data;
    await claimTenant(1);
    drawPipeline();
  } catch (error) {
    $("health").textContent = String(error);
    $("health-dot").className = "lamp failed";
  }
  controls();
})();
