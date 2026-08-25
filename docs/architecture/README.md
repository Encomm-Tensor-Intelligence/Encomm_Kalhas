# KALHAS architecture (Phase 0)

## Layer map

| Layer | Path | Responsibility |
| --- | --- | --- |
| Contracts | `kalhas/contracts/` | Frozen, versioned wire contracts (`v1` today) |
| Application | `kalhas/application/` | Use cases and runtime configuration |
| API | `kalhas/api/` | FastAPI app, routes, typed error handling |
| Adapters | `kalhas/adapters/` | Boundary protocols toward NEXUS/LEGION (placeholders) |
| Domain packs | `kalhas/domain_packs/` | Future domain extensions via `DomainPack` protocol |

## Dependency rules

```
api  -->  application  -->  contracts
api  -->  contracts
domain_packs  -->  (DomainPack protocol only; no kernel knowledge of packs)
adapters  -->  (NexusAdapter / LegionAdapter protocol placeholders only)
```

- Dependencies point downward only; nothing outside `api` imports `api`.
- The kernel never imports NEXUS or LEGION internals.
- `contracts/v1` is immutable. Breaking changes require a new version module
  and API segment (see ADR 001).

## Phase 0 status

- Minimal standalone live API: `GET /health`, `GET /v1/system-info`, `/docs`.
- Placeholder boundary protocols only; no integrations, no simulation
  behavior, no database, no external provider configuration.

## Phase 1 status

- Sixteen versioned, strict, domain-neutral public contracts under
  `kalhas/contracts/v1/` (see `contracts-and-lifecycle.md`).
- Deterministic JSON Schema export; artifacts checked into `schemas/v1/`.
- Pure campaign lifecycle state machine in `kalhas/application/`; no campaign
  API endpoints yet (ADR 003).
- Adapter protocols refined to the new contracts; still placeholders only.

## Phase 2 status

- Contract direction corrected: `ScenarioSpec` -> validation -> immutable
  `WorldVersion` (with provenance fields) -> `CampaignSpec`.
- In-memory store, pure semantic validation with structured clarification
  questions, and a deterministic SHA-256 world compiler
  (`kalhas/application/`).
- Local deterministic mocks (`kalhas/adapters/mocks/`): MockNexusAdapter
  (standalone flow) and MockLegionAdapter (five fixed candidates).
- Minimal standalone API: scenario register/validate/compile + world fetch,
  tenant-scoped via `X-Tenant-ID`, typed errors throughout.

## Phase 3 status

- `RunPlan` public contract (17th top-level contract) + schema artifact.
- Deterministic run planner and campaign preparation service; campaigns are
  stored COMPILED with an ordered run plan per strategy-seed pair.
- `start` performs only `COMPILED -> RUNNING`; nothing is simulated, no
  outcomes/evidence/events are produced.
- Campaign API: prepare, start, fetch, list runs - tenant-scoped, typed
  404/409/422/invalid-state errors.
- `WorldManifest.entity_count` is 0 for the generic compiler; declarative
  element counts live in manifest `state`.

## Phase 4 status

- `RunStatus` and `ReplayManifest` public contracts (19 top-level) + schema
  artifacts; `RunEvent` extended with structural kinds and full references.
- Deterministic structural runtime: three ordered events per run
  (RUN_STARTED, STRATEGY_DECLARATION_RECORDED, RUN_COMPLETED), SHA-256 event
  hash over the canonical ordered stream, PLANNED -> RUNNING -> COMPLETE
  transitions, campaign RUNNING -> COMPLETE only after all planned runs.
- Exact replay: regenerates the stream from recorded inputs only, verifies
  the hash, returns a `ReplayManifest`; mismatches and incomplete runs are
  rejected with typed errors.
- Execution API: execute campaign, run status, run events, run replay -
  tenant-scoped, typed 404/409/422 responses.
- Kernel proof only: no outcomes, evidence, briefs, recommendations, or
  numeric ground truth are produced in this phase.

## Phase 5 status

- `RunInputIntegrityManifest` public contract (20 top-level) + schema
  artifact; `ErrorCode.INTEGRITY_ERROR` (409).
- Deterministic input-integrity verifier (`input_integrity.py`): validates
  all identity/ownership relationships and recomputes the SHA-256 input
  hash over the recorded inputs; safe generic error messages.
- Execution gates: per-run verification before any transition/event;
  atomic campaign preflight (zero runs on any failure); replay verifies
  before hash comparison.
- `POST /v1/runs/{run_id}/verify-inputs` endpoint: verifies, records, and
  returns the manifest; read-only with respect to lifecycle and events.
- Process-local deterministic integrity checking only - not cryptographic
  signing, persistence, or domain evidence.

## Phase 6 status

- `DomainPackManifest` public contract (21st top-level) + nested
  `DomainPackCapability` + schema artifact. Strict semantic `pack_version`,
  per-element API-version pattern (API version `1` mandatory), unique
  capability identifiers, frozen contract.
- Tenant-scoped declarative registry: `domain_pack_registry.py` builds
  manifests from validated registration drafts, computes the authoritative
  canonical SHA-256 `content_hash` (over manifest content excluding the
  hash itself - never client-supplied), stores immutably (typed 409 on
  duplicate), serves typed 404s for unknown/foreign manifests, and lists
  deterministically sorted by manifest identifier.
- API: `POST /v1/domain-packs` (201), `GET /v1/domain-packs`,
  `GET /v1/domain-packs/{manifest_id}` - all `X-Tenant-ID` scoped with the
  typed error envelope; invalid drafts (including non-numeric
  `supported_api_versions` elements) fail at the request boundary with
  typed 422, never 500.
- `DomainPack` protocol refined to a purely declarative identity:
  `manifest: DomainPackManifest`, no executable surface. No pack
  implementation ships; test-only generic fakes exist only in tests.
- Registration and retrieval never mutate scenarios, worlds, campaigns,
  run statuses, events, replay manifests, or integrity manifests. Phase 6
  shipped no pack binding, loading, execution, or domain simulation
  (binding arrived in Phase 7, capability-input declarations in Phase 8);
  a registered manifest still affects nothing until it is explicitly
  bound.

## Phase 7 status

- `DomainPackBinding` public contract (22nd top-level) + schema artifact.
  Frozen, strict: scenario + manifest references, exact pack identity
  snapshot (`pack_id`, `pack_version`, lowercase 64-char
  `manifest_content_hash`), unique ordered `capability_ids` copied from the
  registered manifest, deterministic `bound_at`.
- Deterministic binding service (`domain_pack_binding_service.py`):
  identifiers hash-derived from the canonical `(scenario_id, manifest_id)`
  tuple; ownership of both scenario and manifest verified with typed 404s;
  duplicates rejected with typed 409 and never overwrite; no update/delete/
  replace/unbind surface; listing sorted by manifest identifier.
- Store: tenant-scoped bindings keyed `(tenant_id, scenario_id,
  manifest_id)`; unknown and foreign bindings indistinguishable typed 404s.
- World compiler (`world_compiler.py`): registered bindings are loaded in
  deterministic order and embedded as complete serialized snapshots under
  `WorldVersion.world.domain_pack_bindings`; the content hash includes the
  binding set, so binding changes yield distinct immutable world versions.
  An unbound scenario compiles byte-identically to Phase 6 (`WorldManifest`
  state gains `declared_domain_pack_binding_count` only when bindings
  exist). `MockNexusAdapter.compile_scenario` loads stored bindings and
  passes them to the compiler.
- Campaign planning, execution, replay, and input-integrity verification
  consume the newly compiled world content hash unchanged - no hash
  algorithm changed; full flow green with bound worlds.
- API: `POST /v1/scenarios/{scenario_id}/domain-pack-bindings` (201; body
  accepts only `manifest_id` + `bound_at`), `GET /v1/scenarios/{scenario_id}/domain-pack-bindings`
  (typed envelope, deterministic order) - tenant-scoped, typed errors.
- Bindings are declarative metadata only: no pack loading, instantiation,
  import, execution, or capability-schema interpretation.

## Phase 8 status

- `DomainCapabilityDeclaration` public contract (23rd top-level) + schema
  artifact. Frozen, strict: scenario/binding/manifest references, exact
  pack identity snapshot (`pack_id`, `pack_version`,
  `manifest_content_hash`), `capability_id`, JSON-compatible
  `input_values`, deterministic `content_hash` and `declared_at`.
  `DomainPackCapability` rejects duplicate `input_ids`/`output_ids` by
  contract, keeping declaration key matching unambiguous.
- Deterministic declaration service
  (`domain_capability_declaration_service.py`): identifiers hash-derived
  from the canonical `(scenario_id, manifest_id, capability_id)` tuple;
  declaration content hash over canonical content excluding the hash
  field itself; ownership and binding verified with typed 404s; the
  stored binding and manifest must be exactly the records implied by the
  request (binding/manifest tenants, scenario and manifest identifiers,
  deterministic binding identifier) and the binding snapshot must exactly
  match the registered manifest - any inconsistency raises a safe typed
  409 `integrity_error` with no raw hashes or internals exposed;
  `input_values` keys must match the capability's `input_ids` exactly
  (typed 422); duplicates rejected with typed 409 and never overwrite;
  no update/delete/replace/mutation surface; listing sorted by
  `(manifest_id, capability_id)`.
- Store: tenant-scoped declarations keyed `(tenant_id, scenario_id,
  manifest_id, capability_id)`; unknown and foreign declarations
  indistinguishable typed 404s.
- World compiler (`world_compiler.py`): declared capability inputs are
  embedded as complete serialized snapshots under
  `WorldVersion.world.domain_capability_declarations`; the content hash
  includes the declaration set, so declarations yield distinct immutable
  world versions. The compiler canonicalizes snapshot ordering itself
  (bindings by `manifest_id`, declarations by
  `(manifest_id, capability_id)`), so caller-supplied tuple order never
  affects the hash or serialized world content; declaration-free worlds
  compile byte-identically to Phase 7 (`WorldManifest` state gains
  `declared_domain_capability_declaration_count` only when declarations
  exist). `MockNexusAdapter.compile_scenario` loads stored bindings and
  declarations.
- Campaign planning, execution, replay, and input-integrity verification
  consume the newly compiled world content hash unchanged; full flow
  green with declared worlds.
- API: `POST /v1/scenarios/{scenario_id}/domain-capability-declarations`
  (201; body accepts only `manifest_id`, `capability_id`,
  `input_values`, `declared_at`), `GET /v1/scenarios/{scenario_id}/domain-capability-declarations`
  (typed envelope, deterministic order) - tenant-scoped, typed errors.
- Declarations are inert inputs: no schema execution beyond exact
  input-id matching, no capability invocation, outputs, metrics,
  evidence, briefs, recommendations, or domain-pack code execution.

## Phase 9 status

- `OperationalActivityKind` enum + `OperationalActivityEvent` public
  contract (24th top-level) + schema artifact. Frozen, strict: tenant-local
  strictly increasing `sequence` (starting at zero, identifier
  `activity-{sequence}`), generic structural `kind`, deterministic
  `occurred_at` derived from the already-recorded source artifact (never
  the wall clock), optional structural references (`scenario_id`,
  `world_version_id`, `campaign_id`, `run_id`, `manifest_id`,
  `binding_id`, `declaration_id`), and a strict JSON-compatible `payload`
  of safe structural facts only (identifiers, versions, counts, lifecycle
  states, hashes already exposed). Never raw input values, policy rules,
  hidden reasoning, outcomes, evidence, recommendations, or executable
  content.
- Store: append-only tenant-scoped activity keyed `(tenant_id,
  identifier)` with a per-tenant sequence counter; events immutable once
  appended; no update/delete/replace/clear surface; bounded retrieval
  (`after_sequence` cursor, `limit` with `MAX_ACTIVITY_LIMIT = 100`,
  ascending sequence order); `latest_activity_sequence` = -1 for empty
  tenants. Recording activity never alters any other store collection.
- Service (`operational_activity.py`): ten record helpers (scenario
  registered, world compiled, manifest registered, manifest bound,
  capability inputs declared, campaign prepared/started/executed, run
  inputs verified, run replayed), each appending exactly one event after
  success with timestamps copied from the source contracts.
- Wiring: the API routes record one event after each successful
  operation; rejected or failed operations append nothing; all return
  values and lifecycle behavior unchanged.
- API: `GET /v1/operational-activity?after_sequence=&limit=` (typed
  envelope `{events, next_after_sequence, latest_sequence}`; default
  limit 20, max 100; `after_sequence >= -1`; invalid cursor/limit →
  typed 422; empty feed → empty typed list; read-only, never creates
  events; tenant-isolated).
- The feed is observability only: it is not a simulation event stream,
  not evidence, not hidden reasoning, and never participates in any
  world, plan, input-integrity, event, or replay hash (hash-invariance
  test-enforced). No frontend, WebSockets/SSE, polling loop, or fake
  live-agent state in this phase - pull-based read-only observability for
  a future Colony UI.

## Phase 10 status

- **Encomm Colony**: optional local observability companion served by the
  same FastAPI application at `GET /colony/` - plain static
  HTML/CSS/JS under `kalhas/colony_ui/` (index.html, styles.css,
  app.js). No build pipeline, no external assets, no CORS, no tenant
  header, no database, no Docker, no background work on API requests;
  the kernel is fully usable if Colony is never opened.
- **Read-only boundary**: the UI issues only `GET
  /v1/operational-activity` (single `fetch`, no method override, no
  body); no mutation verbs anywhere in the client script; no
  setInterval/setTimeout polling, no WebSocket, SSE, long polling, or
  background refresh - manual pull refresh only, clearly labeled.
- **Truthfulness**: renders only actual typed `OperationalActivityEvent`
  data with `textContent` (never `innerHTML`); no fake agents,
  terminals, running simulations, outcomes, evidence, recommendations,
  metrics, probabilities, or hidden reasoning; raw capability input
  values and policy rules are never representable in the feed and are
  defensively filtered at render time. NEXUS is displayed as external
  boundary - not connected; LEGION as mock strategy boundary only.
- **Layout**: header (badges, tenant input, Load activity / Refresh,
  feed status, last received sequence), left system rail, central
  mission floor with five CSS-only zones mapped to activity kinds
  (Scenario Studio, World Forge, Domain Registry, Campaign Control,
  Integrity and Replay Vault) that glow only when observed, right event
  stream in descending visual order with true tenant-local sequence
  numbers, and a bottom timeline bar (oldest/newest loaded, API
  `latest_sequence`, older-history flag, hash non-involvement note).
  Responsive, keyboard-accessible, `prefers-reduced-motion` disables all
  decorative motion.
- **Behavior**: first load requests nothing until the tenant is supplied
  and Load activity is pressed; initial request
  `after_sequence=-1&limit=100`; Refresh is cursor-based and fetches
  only newer events; only the latest 100 rendered events are kept in
  memory; empty tenant feeds and typed API errors are handled visibly
  and safely.
- **Test-enforced** (tests/test_colony_ui.py): page and assets served
  locally; JS references only the GET activity endpoint with no
  mutation verbs and no polling/streaming primitives; textContent-only
  rendering; Colony routes stay out of the OpenAPI document; opening
  the UI creates no activity, alters no existing feed, and leaves world
  content hashes, run input/event hashes, recorded event streams, and
  replay expectations byte-identical.

## Phase 11 status

- **Immutable declarative state models**: `StateValueKind` +
  `DomainStateFieldDefinition` + `DomainStateModel` (25th top-level
  public contract, frozen, `extra="forbid"`, schema artifact
  exported). A state model is **data only** - it declares which state
  fields exist for a scenario-bound domain pack (identifier,
  description, value kind, initial value, optional allowed values,
  metadata). **No mechanism engine**: no transitions, formulas,
  expressions, policies, mechanisms, outcomes, evidence,
  recommendations, or real-world actions; no callbacks, imports,
  executable expressions, or evaluators are expressible; no
  domain-pack code is ever loaded, invoked, or interpreted.
- **Strict validation**: initial/allowed values must exactly match the
  declared kind; booleans are never accepted as integer/number;
  non-finite floats (NaN/Infinity) are rejected for every kind,
  including arbitrarily nested inside `json` values (pure recursive
  structural scan) and inside metadata; allowed values must be
  canonically unique and include the initial value; field identifiers
  unique; `state_model_id` non-empty and stable.
- **Authoritative identity only**: the client can never supply
  `binding_id`, `pack_id`, `pack_version`, `manifest_content_hash`,
  the model identifier, or `content_hash` - all are copied from stored
  immutable records or computed (typed 422 otherwise). Identifier:
  `state-model-{sha256(canonical_json({scenario_id, manifest_id,
  state_model_id}))[:16]}`; content hash over the canonical dump
  excluding `content_hash` itself.
- **Canonical ordering**: state fields canonicalized by identifier at
  declaration time and re-canonicalized by the compiler; state models
  ordered by `(manifest_id, state_model_id)` - equivalent caller/storage
  orderings produce the same model, content hash, and world snapshot.
- **Integrity verification**: the stored binding must match the request
  (tenants, scenario/manifest ids, deterministic binding identifier)
  and the binding snapshot must exactly match the registered manifest
  (pack id, pack version, content hash, capability set); any mismatch
  raises a safe typed 409 `integrity_error` with a generic public
  message and internal `reason`.
- **World snapshotting**: `world["domain_state_models"]` with the
  manifest count `state["declared_domain_state_model_count"]` - both
  added only when non-empty, so pre-Phase-11 worlds compile
  byte-identically and old compiled worlds are unchanged; a new state
  model changes the newly compiled world hash. Campaign planning,
  input integrity, structural execution, replay, and event semantics
  are untouched.
- **API**: `POST` + `GET
  /v1/scenarios/{scenario_id}/domain-state-models` (201/200; typed
  404 unknown/foreign scenario·binding·manifest; 409 duplicate; 409
  integrity_error; 422 invalid drafts; X-Tenant-ID required).
- **Activity + Colony**: new kind `domain_state_model_declared`
  (exactly one event per success, safe payload only: state_model_id,
  content hash, field count - never field values/allowed
  values/descriptions/metadata; rejections append nothing). Colony
  lights its Domain Registry zone from the new kind with no new
  request, timer, stream, or mutation capability - still strictly
  read-only and manual-pull.

## Phase 12 status

- **Immutable declarative state-transition specifications**:
  `DomainStateTransition` (26th top-level public contract, frozen,
  `extra="forbid"`, schema artifact exported). A transition is **data
  only** - it declares one *possible* state change for an
  already-declared `DomainStateModel` (scenario/binding/manifest/pack
  identity, `state_model_id`, `state_model_content_hash`,
  `transition_id`, description, `guard_values`, `target_values`,
  content hash, `declared_at`, metadata). A guard is only a declarative
  equality condition and a target is only a declarative intended state
  patch. **Still no transition engine**: no state mutation, transition
  execution, simulation mechanism, outcome generation, evidence,
  recommendations, or real-world actions; no callbacks, scripts,
  expressions, formulas, evaluators, code references, providers,
  imports, dynamic loading, policies, or LLM calls are expressible; no
  domain-pack code is ever loaded, invoked, or interpreted; the three
  structural run events are unchanged; no transition-execution endpoint
  exists.
- **Strict validation**: `transition_id` non-empty; `target_values`
  non-empty (empty `guard_values` allowed); nested NaN/Infinity rejected
  in guard values, target values, and metadata at the request boundary
  and the contract; every guard/target key must identify an existing
  state-model field; every value must exactly match the field's
  `StateValueKind` (booleans never accepted as integer/number, Phase 11
  semantics) and be canonically among the field's `allowed_values` when
  declared (typed 422, nothing stored).
- **Authoritative identity only**: the client can never supply
  `binding_id`, `pack_id`, `pack_version`, `manifest_content_hash`,
  `state_model_content_hash`, the transition identifier, or
  `content_hash`. Identifier:
  `transition-{sha256(canonical_json({scenario_id, manifest_id,
  state_model_id, transition_id}))[:16]}`; content hash over the
  canonical dump excluding `content_hash` itself.
- **Canonical ordering**: guard/target mappings canonicalized by field
  identifier at declaration time and re-canonicalized by the compiler;
  transitions ordered by `(manifest_id, state_model_id,
  transition_id)` - equivalent caller/storage orderings produce the
  same transition, content hash, and world snapshot.
- **Integrity verification**: binding/manifest checks as in Phase 11,
  plus the referenced state model's copied identity, deterministic
  identifier, recomputed content hash, pack identity, manifest content
  hash, and canonical field representation are verified against the
  stored immutable records; any mismatch raises a safe typed 409
  `integrity_error` with a generic public message and internal
  `reason`.
- **World snapshotting**: `world["domain_state_transitions"]` with the
  manifest count `state["declared_domain_state_transition_count"]` -
  both added only when non-empty, so pre-Phase-12 worlds compile
  byte-identically and old compiled worlds are unchanged; a new
  transition changes the newly compiled world hash. Campaign planning,
  input integrity, structural execution, replay, and event semantics
  are untouched; the compiler never evaluates a guard or applies a
  target patch.
- **API**: `POST` + `GET
  /v1/scenarios/{scenario_id}/domain-state-transitions` (201/200; typed
  404 unknown/foreign scenario·binding·manifest·state-model; 409
  duplicate; 409 integrity_error; 422 invalid values; X-Tenant-ID
  required).
- **Activity + Colony**: new kind `domain_state_transition_declared`
  (exactly one event per success, safe payload only: state_model_id,
  transition_id, content hash, guard/target field counts - never
  descriptions, guard values, target values, metadata, or state-field
  values; rejections append nothing). Colony lights its Domain Registry
  zone from the new kind with no new request, timer, stream, or
  mutation capability - still strictly read-only and manual-pull.

## Phase 13 status

- **Pure deterministic state-transition evaluation kernel**
  (`kalhas/application/state_transition_engine.py`): a focused,
  domain-neutral, application-layer engine that evaluates an explicitly
  supplied, ordered sequence of already-declared
  `DomainStateTransition` specifications against one immutable
  `DomainStateModel`. Initial state is derived **only** from
  `state_fields[].initial_value`; transitions are evaluated **only in
  caller order** (never chosen, reordered, searched, prioritized, or
  looped); a guard is **exact canonical equality** over its declared
  `guard_values`; a matching guard applies **only** the declared
  `target_values` as a copy-on-write patch; a non-matching guard
  returns the unchanged state with an explicit deterministic
  `guard_not_satisfied` result. Inputs are never mutated.
- **Strict validation**: current state validated against the model's
  field definitions before every step and the applied target state
  re-validated afterwards - Phase 11 value-kind, allowed-values, and
  nested finite-JSON rules (bool-as-int/number rejected, nested
  NaN/Infinity rejected). Unknown keys, missing required keys, invalid
  values, foreign/mismatched transitions (ownership/identity fields -
  tenant, scenario, binding, pack id, pack version, manifest,
  state-model - plus authoritative content hashes, including each
  transition's own recomputed hash), mixed-model sequences, and
  corrupted model/transition identities raise typed application errors
  (`StateValidationError`, `TransitionModelMismatchError`). Every
  transition specification is validated up front (non-empty targets,
  existing guard/target keys, exact value kinds, allowed values, no
  nested non-finite values) - an invalid specification can never be
  silently recorded as `guard_not_satisfied`. Trajectories
  are bounded by an explicit `max_attempts` (default 1000;
  `TrajectoryLimitExceededError` / `InvalidTrajectoryLimitError`), with
  malformed sequences rejected up front - never a partial trajectory.
- **Result records**: frozen dataclasses `TransitionAttempt` and
  `TrajectoryEvaluation` expose initial state/hash, per-attempt
  sequence position, transition id/content hash, outcome (`applied` |
  `guard_not_satisfied`), before/after state hashes, final state/hash,
  and a deterministic `trace_hash` over the ordered attempt records. The
  `initial_state`/`final_state` snapshots are **deep-frozen immutable**
  (every nested mapping and array read-only; assignment raises), share
  no mutable nested references with the model's initial values,
  transition values, or engine working state, and compare/hash/validate
  identically to their plain JSON equivalents. No human-language
  explanations or hidden reasoning; never exposed through activity
  events or Colony.
- **Determinism**: all state snapshots and trace entries use canonical
  JSON (sorted keys, no insignificant whitespace); equivalent maps with
  different insertion order yield identical hashes and results.
- **Scope**: application-layer only - no HTTP routes, no OpenAPI
  surface, no store methods, no operational activity kinds, no Colony
  behavior, no world compiler changes, no campaign/run/replay
  integration, no automatic execution from compiled worlds, no
  strategy-policy inspection, no domain-pack invocation, and no change
  to the structural runtime's three events.

Deterministic simulation campaigns with real domain mechanisms, outcomes,
evidence, and living-simulation experiences are future phases
(see ADR 002, ADR 003).

## Phase 14 status

- **Store snapshot-isolation boundary**
  (`kalhas/application/in_memory_store.py`): a single generic helper
  `_deep_copy_contract` (Pydantic `model_copy(deep=True)` when the value
  exposes it, else `copy.deepcopy`) now guards every contract family.
  Every `put_*` stores a deep defensive copy and every `get_*`/`list_*`
  returns a fresh deep copy; tuple collections are deep-copied item by
  item on both write and read; `append_operational_activity` stores
  **and** returns copies. Lifecycle replacement remains confined to the
  explicit `update_campaign_status`/`put_run_status` methods. Because
  Pydantic `frozen` models do not protect nested dict/list values
  (assignment to `world.world[...]`, `metadata[...]`, `payload[...]`
  still succeeds on a shared reference), this copy boundary is what
  makes stored state immutable end-to-end: public retrieved objects can
  never corrupt storage, and test-only corruption must inject through
  the private `_*` dictionaries.
- **Deterministic compiled-world integrity verifier**
  (`kalhas/application/world_integrity.py`, error
  `WorldSnapshotIntegrityError`): `verify_world_snapshot(world,
  manifest)` is pure, read-only, and deterministic, and reuses the world
  compiler exclusively (private `_canonical_*` helpers for
  canonical-order checks, `compile_world` for full recompilation - no
  second hash algorithm). Fixed check order: tenant and identifier
  identity (world `world-{hash[:16]}`, manifest `manifest-{hash[:16]}`,
  manifest world reference), supported compiler version, required
  body keys with no unexpected keys, body `content_hash`/
  `compiler_version` matching the contract, strict `ScenarioSpec` parse
  with tenant/identifier/`created_at` provenance, strict parse of all
  four snapshot families (absent key = empty; non-list/validation
  failure = malformed), canonical-order equality per family, and full
  recompilation reproducing both the world and the manifest exactly
  (semantically invalid scenarios rejected as such). A corrupted world
  is rejected - never repaired, normalized, replaced, or silently
  accepted.
- **Integration gates**: `prepare_campaign` verifies after the
  world/scenario match, before LEGION and before any campaign/run
  write (missing manifest = integrity error, not 404; failed
  verification writes nothing); `verify_run_inputs` verifies right
  after the world identity checks, before input-hash recomputation
  (structural execution's atomic preflight and replay's
  no-manifest-after-failure behavior inherit the gate);
  `MockNexusAdapter.world()` and `.manifest()` verify before returning
  (API `GET /v1/worlds/{id}` flows through `adapter.world`).
- **Safe error surface**: `WorldSnapshotIntegrityError` maps to the
  existing 409 `INTEGRITY_ERROR` in `kalhas/api/errors.py` (no route
  changes). The public message is generic - no hashes, embedded state,
  metadata, or raw values; the internal `reason` names only the
  violated rule.
- **Scope**: no new routes, contracts, schemas, activity kinds, Colony
  behavior, compiler changes, external services, or domain logic; the
  Phase 13 trajectory engine is **not** integrated into campaigns or
  runs and no trajectory plans exist. All previously compiled worlds
  remain valid (they are compiler outputs) with byte-identical hashes.
- **Status**: remediation complete - all gates green; full suite **910
  passed / 1 skipped**; mypy clean (95 files); ruff check and
  `ruff format --check` clean; schema export `--check` synced.

## Phase 15 status

- **Immutable strategy-bound trajectory plans**
  (`kalhas/contracts/v1/trajectory.py` + `kalhas/application/strategy_trajectory_service.py`):
  LEGION *proposes* an explicitly ordered transition sequence; KALHAS
  *verifies, binds, hashes, and stores* immutable `StrategyTrajectoryPlan`
  records. Four new contract types (frozen, `extra="forbid"`):
  `StrategyTrajectoryTransitionReference`, `StrategyTrajectoryPlanRequest`
  (VersionedContract), `StrategyTrajectoryPlanDraft` (untrusted
  proposal), `StrategyTrajectoryPlan` (VersionedContract). `PUBLIC_CONTRACTS`
  26 -> **28**; two new schema artifacts exported. No trajectory is
  evaluated or executed anywhere in this phase.
- **Authoritative provenance**: plans are built exclusively from
  verified stored records - the COMPILED campaign, the Phase 14-verified
  `WorldVersion`+`WorldManifest`, state models and transitions
  **embedded in the compiled world snapshot** (never live-registry
  declarations), and the exact stored strategy candidates in campaign
  order. Identifiers and hashes use only the canonical JSON + SHA-256
  conventions; `planned_at` is the recorded campaign `created_at`.
- **Closed world catalog**: every embedded transition must map to
  exactly one embedded state model by `(manifest_id, state_model_id,
  state_model_content_hash)`; deterministic identifiers required; no
  duplicate model identifiers/ownership keys/transition identifiers;
  every non-empty catalog passes `validate_transition_catalog`; orphan,
  ambiguous, duplicate, or identity-invalid snapshots fail **before the
  first LEGION call** with a safe typed `WorldSnapshotIntegrityError`.
  The same closed construction backs stored-plan verification on read.
- **Exact preflight and matrix**: stored strategy candidates must equal
  `campaign.strategy_candidate_ids` exactly and the stored run-plan
  tuple must equal the deterministic `plan_runs` recomputation exactly
  (then `verify_run_inputs` per expected run) - all before any LEGION
  trajectory request, with no integrity manifest or lifecycle writes.
  Plans are prepared for every strategy candidate x every
  transition-capable state model, exactly one per pair in exact order;
  LEGION-proposed sequences are preserved exactly, including repetitions.
  A second preparation (including of the prepared empty tuple) is
  rejected before any new LEGION call.
- **Boundary isolation**: the authoritative request snapshot never
  crosses the adapter boundary - `legion.request_trajectory_plan`
  receives a disposable deep copy, and plan construction reads only
  authoritative records afterwards (hostile boundary mutation cannot
  influence plans). Atomic all-or-nothing preparation (any invalid
  draft stores zero plans); the store keeps the Phase 14 deep-copy
  boundary, refuses duplicate preparation, and keeps a successfully
  prepared empty tuple distinguishable from "not prepared". Stored
  plans are verified **as a complete collection** (exact length/order,
  unique identifiers and pairs, exact pair set, `planned_at` equals
  campaign `created_at`, per-plan identity/hash/reference checks);
  stored plans are strictly revalidated against their complete contract,
  including nested reference types and the 1-1000 reference bound,
  before any identity, hash, or matrix verification;
  tampered collections raise `StoredTrajectoryPlanIntegrityError` and
  are never repaired, sorted, normalized, or replaced.
- **Scope**: no campaign/run engine integration, no structural runtime
  changes (the three run events are untouched), no run events, no
  `RunPlan`/`ReplayManifest` changes, no HTTP/OpenAPI routes, no
  operational-activity kind, no Colony changes, no outcomes/evidence/
  recommendations, no external LEGION implementation, no network or
  providers, no domain-specific logic, no dependency changes.
- **Status**: remediation complete - all gates green; full suite **1037
  passed / 1 skipped / 1 warning**; mypy clean (101 files); ruff check
  and `ruff format --check` clean (110 files); schema export `--check`
  synced. Phase 15 suites: trajectory contracts, catalog validation,
  closed-world catalog, strategy trajectory plans (61), campaign
  service, world integrity, boundaries (16 passed + 1 skipped).

## Phase 16 status

- **Explicit runtime versioning** (`kalhas/application/run_planner.py`):
  `LEGACY_STRUCTURAL_RUNTIME_VERSION = "1.0.0"`,
  `TRAJECTORY_RUNTIME_VERSION = "2.0.0"`,
  `RUNTIME_VERSION = TRAJECTORY_RUNTIME_VERSION` - new planning defaults
  to 2.0.0. Runtime selection derives only from the recorded
  `RunPlan`/`RunStatus`; `execute_run(store, tenant_id, run_id)` and
  `replay_run(store, tenant_id, run_id)` accept no synthetic plans,
  models, transitions, or artifacts. Recorded 1.0.0 runs execute and
  replay under the exact legacy structural-only behavior (three events,
  same event hash, PLANNED -> RUNNING -> COMPLETE, no trajectory
  artifact); 2.0.0 runs use the trajectory runtime; any other version
  fails with `UnsupportedRuntimeVersionError` before any lifecycle
  change or replay regeneration. The Phase 15 planning preflight
  rejects legacy/unsupported run matrices with a typed error before any
  LEGION call.
- **New contracts** (`kalhas/contracts/v1/trajectory_execution.py`,
  frozen + `extra="forbid"`): `RunTrajectoryAttemptRecord` (one
  deterministic attempt; no guard/target values, no evidence),
  `RunStateTrajectoryResult` (one evaluated plan: identities + content
  hashes, plain JSON initial/final states + hashes, ordered attempts,
  trace hash, self-covering content hash), `RunTrajectoryExecution`
  (VersionedContract; deterministic identifier from run identity +
  runtime version; run/campaign/plan/world/strategy/seed provenance;
  runtime literal "2.0.0"; input hash; exact ordered plan-set hash;
  ordered results; aggregate content hash; `executed_at` = RunPlan
  `created_at`; empty results valid only for a world with no
  transition-capable models) and `RunTrajectoryReplayManifest`
  (VersionedContract; expected == recomputed == authoritative execution
  hash; `replay_classification: "exact"`; deterministic `replayed_at`).
  `PUBLIC_CONTRACTS` 28 -> **30**; two new schema artifacts exported.
  No existing v1 contract field was modified.
- **Pure execution builder** (`kalhas/application/run_trajectory_runtime.py`):
  `build_run_trajectory_execution` is store-free and receives only
  verified authoritative records (`VerifiedRunInputs`, exact applicable
  plan tuple, exact closed compiled-world catalogs). Requires 2.0.0;
  verifies plan strategy identity/hash; preserves canonical plan/model
  order; resolves references only against the exact verified world
  catalog; preserves repetitions and ordering; calls `evaluate_trajectory`
  once per plan; converts the engine's deep-frozen snapshots to fresh
  detached plain JSON via the new public `state_to_plain_json` engine
  helper; zips each engine attempt with its authoritative plan
  reference (position/transition id/content hash verified); builds and
  hashes every result and the aggregate. Hash rules: canonical ordered
  plan-set hash, result/execution content hashes (dump minus the hash
  field), deterministic execution identifier. Never mutates inputs; no
  wall clock, randomness, network, providers, or domain packs.
- **Run input resolution** (`kalhas/application/run_trajectory_inputs.py`):
  `verify_run_trajectory_inputs` calls `verify_run_inputs`, then
  branches only on the recorded runtime version. For 2.0.0: loads the
  complete collection through the Phase 15 service getter (collection-
  level integrity), builds the same closed world catalogs, and selects
  exactly the run strategy's plans - one per transition-capable model
  in canonical order; missing/additional/duplicated/reordered/foreign/
  mismatched plans rejected. Transition-capable world without a
  prepared collection -> `TrajectoryPlansRequiredError`; no-capable-
  model world resolves an empty tuple; 1.0.0 never consumes plans;
  unsupported versions rejected. Read-only; never evaluates.
- **Execution and campaign atomicity** (`kalhas/application/structural_runtime.py`):
  legacy 1.0.0 execution is byte-identical. Trajectory 2.0.0 execution
  verifies/resolves all trajectory inputs, ensures no pre-existing
  artifact, evaluates every plan in memory, and builds the complete
  artifact **before the first lifecycle write**; only then are the
  integrity manifest recorded, RUNNING transitioned, the same three
  structural events stored, the artifact stored, and COMPLETE reached
  with the existing structural event hash. Failure leaves the run
  PLANNED with zero events/artifacts and no FAILED mark. The structural
  event stream stays exactly three events with an independent event
  hash (never fed by the trajectory execution hash; no raw states in
  payloads). `execute_campaign` preflights every run atomically
  (inputs, trajectory resolution, artifact absence, full in-memory
  build) before the first run; any failure -> zero runs/events/artifacts,
  all statuses PLANNED, campaign RUNNING. Runs then execute in stored
  order; `execute_run` still independently reloads verified inputs.
- **Exact replay** (`kalhas/application/replay_service.py`): keeps the
  existing signature and return type. Legacy replay unchanged (no
  trajectory manifest required or created). Trajectory replay verifies
  the stored execution record (contract revalidation, identifier,
  ownership, runtime, input/plan-set/content hashes), reloads and
  verifies the current plan collection, resolves the same closed
  catalogs, **independently regenerates** the complete expected
  execution via the pure builder, and requires exact full-object and
  content-hash equality - cached trajectory results are never read as
  the regenerated output. Only after all structural and trajectory
  checks succeed are the existing `ReplayManifest` and the
  `RunTrajectoryReplayManifest` stored. Mismatch -> typed
  `TrajectoryReplayMismatchError` (or execution-integrity error),
  neither manifest written, no state values/hashes exposed. No LEGION/
  NEXUS/domain pack/provider/network/randomness/wall clock.
- **Store isolation + integrity verification**: new immutable
  tenant/run-keyed collections for `RunTrajectoryExecution` and
  `RunTrajectoryReplayManifest` with strict serializer-based contract
  revalidation on write, deep copies on write/read, idempotent
  identical rewrites, conflicting rewrites rejected without overwrite,
  foreign access indistinguishable from missing, no update/delete/repair
  surface. `kalhas/application/trajectory_integrity.py` verifies stored
  records end to end (identifiers, ownership, content hashes, result
  count/order, per-result plan/model identity and hashes, state hashes,
  attempt references, trace/result/aggregate hashes, executed/replayed
  provenance, replay hash equality). Tampered records are never
  repaired, normalized, replaced, or silently accepted.
- **Seed and non-goals**: the recorded seed identity is provenance only
  (`scenario_seed_id` in the artifact, identifier, and input hash) -
  the current declarative transition kernel does not sample or use it.
  No new `RunEvent` kinds, no transition-attempt events, no outcomes/
  evidence/DecisionBriefs/rankings/recommendations, no uncertainty
  sampling, no automatic transition selection, no domain-pack execution,
  no real LEGION/NEXUS integration, no HTTP/OpenAPI paths (new typed
  errors map through the existing envelope: 409 conflict / 409
  integrity_error / 404 not-found), no operational-activity kinds, no
  Colony changes, no external services/providers/network, no filesystem
  or database, no new dependencies, no domain-specific logic.
- **Status**: all five gates green - full suite **1178 passed / 1
  skipped / 1 warning** (the pre-existing Starlette/httpx deprecation
  warning only); mypy clean (113 files); ruff check clean; `ruff format
  --check` clean (122 files); schema export `--check` synced. New Phase
  16 suites: trajectory execution contracts, run trajectory runtime
  (pure builder), run trajectory inputs (resolution), trajectory
  execution (run + campaign atomicity), trajectory replay, trajectory
  store isolation, Phase 16 boundaries (125 tests in the targeted run).

## Phase 17 status

- **Read-only inspection surface** (`kalhas/application/trajectory_query_service.py`):
  two explicit keyword-only functions -
  `get_verified_run_trajectory_execution(*, store, tenant_id, run_id)`
  -> `RunTrajectoryExecution` and
  `get_verified_run_trajectory_replay_manifest(*, store, tenant_id, run_id)`
  -> `RunTrajectoryReplayManifest`. Both verify the recorded run inputs
  and resolve the exact applicable trajectory plans + closed
  compiled-world catalogs via `verify_run_trajectory_inputs`, load the
  stored artifact through the store's deep-copy boundary, and verify it
  with the existing Phase 16 verifiers (the manifest query verifies the
  authoritative execution first, then
  `verify_run_trajectory_replay_manifest_record` against the execution
  and the exact ordered plan-set hash). Read-only and deterministic: no
  FastAPI, no LEGION/NEXUS calls/imports, no domain-pack loading or
  execution, no wall clock/randomness/filesystem/database/provider/
  network, no mutation of stored or returned inputs, no
  `build_run_trajectory_execution`/`replay_run`/`evaluate_trajectory`
  calls, no store writes, no operational activity, no lifecycle changes.
- **Endpoints**: `GET /v1/runs/{run_id}/trajectory-execution` and
  `GET /v1/runs/{run_id}/trajectory-replay-manifest` (both X-Tenant-ID
  scoped) return the **existing** `RunTrajectoryExecution` /
  `RunTrajectoryReplayManifest` contracts directly - no wrapper
  contracts, `PUBLIC_CONTRACTS` remains **30**, no schema artifact
  changed. Retrieval never executes, replays, regenerates, repairs, or
  writes; the manifest GET never triggers `replay_run` (pre-replay runs
  return the typed 404 and nothing is created). The execution response
  intentionally carries the contract-declared `initial_state`/
  `final_state` snapshots only - never guards, targets, policy content,
  hidden reasoning, evidence, or recommendations.
- **Tenant/error/integrity guarantees**: X-Tenant-ID is authoritative;
  foreign-tenant access is indistinguishable from a missing artifact
  (same typed 404 `not_found`). Legacy 1.0.0 runs, not-yet-executed
  2.0.0 runs, and not-yet-replayed manifests return the typed 404;
  unsupported recorded runtime versions return the typed 409 `conflict`;
  corrupted execution records return the existing safe 409
  `integrity_error`; corrupted replay manifests preserve the existing
  typed 409 `conflict` mapping. Public error responses never expose
  internal reasons, hashes, state values, guards, targets, policies, or
  validator diagnostics; request IDs and the single `ApiErrorResponse`
  envelope are unchanged.
- **Non-goals**: no execution/replay side effects on GETs, no new
  runtime versions, no new `RunEvent` kinds, no transition attempts in
  `RunEvent`, no changes to the three structural events or their event
  hash, no outcomes/evidence/recommendations, no uncertainty sampling,
  no automatic transition selection, no domain-specific logic, no
  domain-pack execution, no real LEGION/NEXUS integration, no
  operational-activity kinds or writes, no Colony changes, no external
  services/providers/network/database/filesystem, no dependencies, no
  AGENTS.md/global-config/skill changes, no commits or pushes.
- **Status**: all five gates green - full suite **1226 passed / 1
  skipped / 1 warning** (the pre-existing Starlette/httpx deprecation
  warning only); mypy clean; ruff check clean; `ruff format --check`
  clean; schema export `--check` synced. New Phase 17 suites:
  `tests/test_trajectory_query_service.py` (21), `tests/test_api_phase17.py`
  (17), `tests/test_phase17_boundaries.py` (10) - 48 new tests; the 5
  Phase 16 suites re-run unchanged (1178 passing, 1 skipped).

## Phase 18 status

- **Deterministic campaign trajectory matrix** (`kalhas/application/campaign_trajectory_query_service.py` +
  `kalhas/application/campaign_trajectory_runtime.py`): assembles every
  verified Phase 16 `RunTrajectoryExecution` of one completed
  runtime-2.0.0 campaign into the exact authoritative strategy x
  shared-seed run matrix - a deterministic, tenant-scoped, read-only
  structural comparison provenance artifact. It never ranks strategies,
  interprets state values, or produces outcomes/evidence/
  recommendations; no strategy-quality claim is expressible in the
  contract.
- **Contracts** (`kalhas/contracts/v1/campaign_trajectory.py`):
  `CampaignTrajectoryRunCell` (frozen strict nested cell, NOT
  registered) carries references and integrity hashes only - positions,
  run/run-plan/strategy/seed identities, input hash, execution
  identifier + content hash, exact ordered plan-set hash, ordered
  result content hashes; no state snapshots, guards, targets, policy,
  outcomes, evidence, ranking, or explanations. `CampaignTrajectoryMatrix`
  (frozen strict VersionedContract, registered - PUBLIC_CONTRACTS
  30 -> **31**) enforces the structural shape: runtime literal `2.0.0`,
  comparison-mode literal `identical_conditions`, non-empty ordered
  strategy/seed/cell collections, unique identities, complete Cartesian
  product, position-bound cells, exact RunPlan order. Identifier:
  `trajectory-matrix-{sha256(canonical_json({campaign_id,
  world_version_id, runtime_version}))[:16]}`; `content_hash` covers the
  complete canonical matrix excluding `content_hash`; `assembled_at` is
  the recorded campaign `created_at` - never the wall clock. New schema
  artifact `CampaignTrajectoryMatrix.schema.json`; no existing v1
  contract field changed.
- **Pure builder**: `build_campaign_trajectory_matrix(...)` receives
  verified authoritative records only, requires runtime 2.0.0
  (legacy/unsupported -> `UnsupportedRuntimeVersionError`), preserves
  exact strategy/seed/RunPlan order, requires the exact complete
  strategy x seed matrix (missing/additional/duplicated/reordered/
  foreign runs rejected), binds every cell to its exact RunPlan and
  verified execution, verifies all run/campaign/world/strategy/seed/
  input identities (recomputed input hashes), preserves ordered result
  content hashes exactly, and computes the deterministic identifier,
  `assembled_at`, and content hash. No store access, no mutation, no
  execution/replay/evaluation/outcome calculation; reuses the existing
  public helpers. The previously private authoritative run-plan matrix
  preflight was extracted to public `preflight_run_plan_matrix` with the
  private name kept as an alias (behavior unchanged, regression-tested).
- **Query pipeline**: campaign + status loaded tenant-scoped; exactly
  COMPLETE required (else new `CampaignNotCompleteError` -> 409
  `invalid_state`); compiled world snapshot verified; exact strategy
  candidates, seed ensemble, and ordered RunPlan matrix verified via
  the existing preflight (legacy/unsupported runtime -> 409
  `conflict`); every run's execution verified through the existing
  Phase 17 verified execution query path; missing/corrupted executions
  or matrix inputs in a COMPLETE campaign raise the new
  `CampaignTrajectoryMatrixIntegrityError` -> 409 `integrity_error` -
  the complete collection is verified before anything is returned and
  **no partial matrix is ever returned**. The matrix is built in memory
  and returned without being stored. Deterministic, read-only,
  all-or-nothing, tenant-scoped, deep-copy isolated, free of FastAPI/
  NEXUS/LEGION/domain-pack/wall-clock/randomness/filesystem/database/
  provider/network surface.
- **Endpoint**: `GET /v1/campaigns/{campaign_id}/trajectory-matrix`
  returns the exact `CampaignTrajectoryMatrix` directly (no wrapper);
  X-Tenant-ID authoritative; unknown/foreign campaign -> typed 404;
  not-COMPLETE -> 409 `invalid_state`; legacy/unsupported runtime ->
  409 `conflict`; missing/corrupted matrix inputs or executions -> 409
  `integrity_error`; no internal reasons, hashes from rejected data,
  state values, guards, targets, policies, or validator diagnostics in
  any error body; request IDs and the single `ApiErrorResponse`
  envelope unchanged; the GET performs no write and creates no
  operational-activity event.
- **Non-goals**: no rankings/winners/losers/scores/weights/
  recommendations, no OutcomeVector/EvidenceReference/DecisionBrief
  production, no metric extraction/aggregation, no probability or
  distribution claims, no state interpretation, no uncertainty sampling
  or seed consumption, no automatic transition selection, no new runtime
  versions, no new `RunEvent` kinds, no changes to the three structural
  events or their event hash, no execution/replay side effects, no state
  snapshots or guard/target/policy content in the matrix contracts, no
  domain-specific logic, no domain-pack loading/execution, no real
  LEGION/NEXUS integration, no operational-activity kinds or writes, no
  Colony changes, no external providers/network/filesystem/database
  persistence, no new dependencies, no AGENTS.md/global-config/skill
  changes, no commits or pushes; Phase 19 not started.
- **Status**: all five gates green - full suite **1347 passed / 1
  skipped / 1 warning** (the pre-existing Starlette/httpx deprecation
  warning only); mypy clean (125 files); ruff check clean; `ruff format
  --check` clean (134 files); schema export `--check` synced;
  PUBLIC_CONTRACTS exactly 31. New Phase 18 suites:
  `tests/test_campaign_trajectory_contracts.py` (31),
  `tests/test_campaign_trajectory_runtime.py` (29),
  `tests/test_campaign_trajectory_query_service.py` (28),
  `tests/test_api_phase18.py` (15), `tests/test_phase18_boundaries.py`
  (14) - 117 new tests (plus 4 new parametrized contract cases in
  tests/test_contracts.py); the two existing contract-count assertions
  were updated 30 -> 31; the complete pre-Phase-18 suite remains green
  as part of the full 1347-test regression run.

## Phase 19 status

- **Immutable state-to-metric observation bindings (declaration only)**
  (`kalhas/contracts/v1/metric_observation.py` +
  `kalhas/application/domain_metric_observation_service.py`): a
  `DomainMetricObservationBinding` connects exactly one metric of a
  stored `ScenarioSpec` to exactly one **numeric** field of an existing
  scenario-bound `DomainStateModel`, declaring that a future phase *may*
  observe the field's final trajectory state as the metric's raw
  observation. Phase 19 is declaration, storage, world snapshotting,
  integrity verification, and API management only: it never inspects a
  `RunTrajectoryExecution`, extracts metric values, evaluates
  trajectories, calculates outcomes, aggregates observations, produces
  evidence, ranks strategies, or generates recommendations.
- **Contract**: `DomainMetricObservationBinding` (frozen
  `VersionedContract`, `extra="forbid"`; PUBLIC_CONTRACTS 31 -> **32**;
  new schema artifact `DomainMetricObservationBinding.schema.json`; no
  existing v1 contract field changed). Fields: `scenario_id`,
  `binding_id`, `manifest_id`, `pack_id`, `pack_version` (semver),
  `manifest_content_hash` (SHA-256), `metric_id`,
  `state_model_identifier`, `state_model_id`,
  `state_model_content_hash` (SHA-256), `state_field_id`,
  `state_field_value_kind` (literal `"integer"` | `"number"` only),
  `observation_point` (literal `"final_state"`, default), `content_hash`
  (SHA-256), `declared_at` (timezone-aware), `metadata`
  (JSON-compatible, non-finite floats rejected). No formulas,
  expressions, callbacks, transformations, scaling factors, aggregation
  implementations, executable or provider references, observed values,
  state snapshots, outcomes, evidence, scores, or recommendations.
- **Authoritative declaration service**: `declare_domain_metric_observation`
  loads the tenant-scoped scenario; requires `metric_id` to identify
  exactly one scenario metric (typed 422); loads the exact
  scenario-bound binding, manifest, and state model (typed 404); runs
  the established binding-integrity (9 checks) and state-model-integrity
  (11 checks) verification against the stored immutable records (safe
  typed 409 `integrity_error`, generic message + internal `reason`);
  resolves `state_field_id` against the exact model (typed 422) and
  requires the authoritative `StateValueKind` to be `integer` or
  `number` - `string`, `boolean`, and `json` fields rejected (typed
  422); copies every authoritative identity/hash/value-kind field from
  storage; sets `observation_point` to exactly `"final_state"`; derives
  the deterministic identifier
  `observation-{sha256(canonical_json({tenant_id, scenario_id, metric_id,
  manifest_id, state_model_id, state_field_id, observation_point}))[:16]}`;
  computes `content_hash` over the complete canonical binding excluding
  `content_hash`; stores only after complete validation; never loads,
  instantiates, imports, or executes a domain pack. One binding per
  scenario metric (MVP): a duplicate declaration - even for a different
  model or field - raises a typed 409 before any write and never
  overwrites.
- **Store** (`InMemoryScenarioStore`): immutable tenant-scoped
  collection keyed `(tenant_id, scenario_id, metric_id)`; deep defensive
  copies on write/read/list; `revalidate_stored_domain_metric_observation`
  strict complete contract revalidation before storage (validator-bypassed
  contracts, foreign objects, and non-finite nested metadata rejected);
  duplicate rejection; incorrect ownership-key rejection; deterministic
  listing by `metric_id`; foreign-tenant access indistinguishable from
  missing; rejected writes leave storage byte-identical; no
  update/delete/repair surface.
- **API**: `POST /v1/scenarios/{scenario_id}/metric-observations` (201 +
  exact `DomainMetricObservationBinding`; `DomainMetricObservationDeclarationRequest`
  accepts only `manifest_id`, `state_model_id`, `metric_id`,
  `state_field_id`, `declared_at`, `metadata`; caller-supplied
  authoritative identities/hashes/value kinds/observation point -> 422)
  and `GET /v1/scenarios/{scenario_id}/metric-observations` (typed
  envelope `{observations}`, deterministic metric-id order, tenant
  isolated, 404 unknown/foreign scenario). Error map: missing/foreign
  scenario/binding/model -> 404 `not_found`; unknown metric/field and
  non-numeric field -> 422 `validation_error`; duplicate -> 409
  `conflict`; corrupted stored binding -> 409 `integrity_error`; single
  `ApiErrorResponse` envelope unchanged; public messages never expose
  raw hashes, state values, metadata values, validator diagnostics,
  another tenant's records, or internal integrity reasons. No update or
  delete endpoints; no operational-activity kinds or writes; no Colony
  changes.
- **World compiler** (`world_compiler.py`): `content_hash`/`compile_world`
  gained `domain_metric_observations=()`; `_canonical_domain_metric_observations`
  sorts by `metric_id`; the `domain_metric_observations` world-body key,
  the hash-payload key, and
  `state["declared_domain_metric_observation_count"]` appear only when
  non-empty, so observation-free worlds compile byte-identically to the
  Phase 18 compiler. Caller/store insertion order never affects the
  world identifier, content hash, manifest, or embedded ordering;
  changing the binding set changes the compiled world
  identifier/content hash; already compiled worlds remain immutable;
  declarations added after compilation affect only subsequently compiled
  worlds; the compiler never interprets or extracts a metric value and
  never reads trajectory executions. `MockNexusAdapter.compile_scenario`
  loads and passes the stored observation bindings.
- **World integrity** (`world_integrity.py`): `verify_world_snapshot`
  recognizes `domain_metric_observations`, strictly parses each embedded
  binding through `DomainMetricObservationBinding` (foreign objects and
  validator-bypassed/malformed snapshots -> rejected), requires canonical
  metric-id ordering, rejects duplicate metric bindings, and verifies
  tenant/scenario ownership, metric existence against the embedded
  scenario (exactly one), state-model existence and identity/content
  hash in the same compiled world, state-field existence, copied numeric
  value-kind match against the authoritative model field, and pack
  binding/manifest identity against the compiled catalog - then
  recompiles from the exact parsed snapshots and requires exact
  `WorldVersion` and `WorldManifest` equality. Corrupted storage is
  never repaired, normalized, reordered, or replaced. `VerifiedWorldCatalog`
  gained the canonical `domain_metric_observations` tuple (defaulted
  empty; immutable and detached).
- **Non-goals**: no metric-observation extraction, no `initial_state`/
  `final_state` reads, no metric values, no `MetricOutcome`/`OutcomeVector`
  or `EvidenceReference`/`DecisionBrief` production, no aggregation,
  normalization, formulas, transformations, weights, scoring, ranking,
  recommendations, uncertainty sampling, seed consumption, automatic
  transition selection, new runtime versions, new `RunEvent` kinds,
  domain-specific vocabulary, domain-pack execution, real NEXUS/LEGION
  integration, external services/providers/network, filesystem/database
  persistence, dependencies, operational-activity kinds or writes,
  Colony changes, AGENTS.md/global-config/skill changes, commits or
  pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan generation, campaign
  lifecycle, trajectory-plan preparation, transition evaluation, run
  execution, replay, Phase 17 artifact queries, the Phase 18 campaign
  trajectory matrix, `RunEvent` and its three structural kinds, and
  event/execution/matrix hashes are unchanged (new world content hashes
  are expected deterministic provenance for newly compiled worlds only).
  **Phase 20 has not started.**
- **Status**: all five gates green - full suite **1479 passed / 1 skipped /
  1 warning** (the pre-existing Starlette/httpx deprecation warning
  only); mypy clean; ruff check clean; `ruff format --check` clean;
  schema export `--check` synced; PUBLIC_CONTRACTS exactly 32. New Phase
  19 suites: `tests/test_domain_metric_observation_contracts.py`,
  `tests/test_domain_metric_observation.py`,
  `tests/test_metric_observation_store.py`,
  `tests/test_metric_observation_world.py`,
  `tests/test_metric_observation_integrity.py`,
  `tests/test_api_phase19.py`, `tests/test_phase19_boundaries.py` -
  128 new tests (plus 4 new parametrized contract cases in
  tests/test_contracts.py); the four existing contract-count assertions
  were updated 31 -> 32; the complete pre-Phase-19 suite remains green
  as part of the full 1480-test regression run.

## Phase 20 status

- **Deterministic run metric-observation extraction.** Phase 19 declared
  *where a metric value may be observed*; Phase 20 explicitly extracts
  the raw numeric value from the **completely verified final trajectory
  state** of a runtime 2.0.0 `RunTrajectoryExecution`, using only the
  `DomainMetricObservationBinding` snapshots embedded in the run's exact
  compiled `WorldVersion` - never newer scenario-level declarations
  added after world compilation. Extraction is an explicit
  post-execution application/API operation; nothing in campaign
  execution, replay, planning, or the trajectory runtime triggers it
  automatically.
- **Contracts** (`kalhas/contracts/v1/run_metric_observation.py`):
  `RunMetricObservationValue` (frozen, `extra="forbid"`, nested; strict
  integer/number raw-value rules - booleans never accepted, NaN/
  Infinity rejected, no coercion, exact preservation; full binding/
  manifest/state-model/field/plan/result provenance) and
  `RunMetricObservationSet` (frozen `VersionedContract`, **33rd**
  top-level contract; run/campaign/plan/scenario identity, world and
  strategy content hashes, seed identity, `runtime_version` literal
  `"2.0.0"`, run input hash, execution identifier/content hash,
  observation tuple canonicalized by `metric_id`, deterministic
  `content_hash`, `observed_at` = the authoritative execution's
  `executed_at`). `PUBLIC_CONTRACTS` 32 -> 33; no existing v1 contract
  field changed; new checked-in schema
  `schemas/v1/RunMetricObservationSet.schema.json`.
- **Extraction pipeline** (application service): Phase 16/17 input
  verification -> recorded runtime exactly 2.0.0 and run COMPLETE ->
  stored execution loaded only through the store boundary and fully
  verified by the existing authoritative integrity pipeline -> bindings
  from the verified compiled world only -> per-binding provenance
  checks, exactly-one result resolution (missing/ambiguous rejected),
  exact state-model identity/id/manifest/content-hash agreement,
  `final_state[state_field_id]` extraction with strict kind validation,
  unit copied from the embedded scenario -> complete set stored only
  after every check succeeds; any failure writes nothing. No transition
  evaluation, no replay, no `initial_state` reads, no uncertainty
  sampling, no LEGION/NEXUS, no domain-pack loading, no network/
  provider/filesystem/database/randomness/wall-clock operations.
- **Verification**: strict contract revalidation, authoritative input
  and execution verification, deterministic in-memory regeneration of
  the expected set, and exact canonical-JSON equality (identifier,
  ordering, values, provenance, content hash). Never repairs,
  normalizes, reorders, overwrites, or silently accepts a partial
  artifact. The GET path never creates an artifact when none exists.
- **Store**: immutable `(tenant_id, run_id)` collection; exactly one
  set per tenant + run; duplicate creation (even identical) rejected
  and never overwritten; deep defensive copies; strict complete
  contract revalidation on write and read; ownership-key rejection;
  foreign tenant indistinguishable from missing; rejected writes leave
  storage byte-identical; no update/delete/repair/replace surface.
- **API**: `POST /v1/runs/{run_id}/metric-observations` (201; 404
  unknown/foreign run; 409 `conflict` legacy/unsupported runtime and
  duplicate extraction; 409 `invalid_state` run not COMPLETE; 409
  `integrity_error` corrupted records or extraction failures) and
  `GET /v1/runs/{run_id}/metric-observations` (200 only after full
  verification; 404 missing/foreign artifact, never creates; 409
  `integrity_error` corrupted). Typed `ApiErrorResponse` envelope with
  request-id behavior; public messages never leak raw observed values,
  hashes, guard/target values, policy content, metadata, another
  tenant's records, or internal integrity reasons. No
  operational-activity kinds or events, no Colony changes.
- **Non-goals**: no aggregation, outcomes, distributions, evidence,
  scoring, ranking, recommendations, decision briefs, strategy
  comparison conclusions, metric normalization/transformation/unit
  conversion, uncertainty sampling, new runtime versions, automatic
  extraction during execution, operational-activity kinds, Colony
  changes, real NEXUS/LEGION integration, live actions, external
  providers/network, filesystem/database persistence, new dependencies,
  AGENTS.md/global-config changes, commits or pushes. Runtime
  1.0.0/2.0.0 behavior, RunPlan generation, campaign/run lifecycle,
  trajectory planning, transition evaluation, `RunTrajectoryExecution`
  generation and hashes, `RunEvent` and its three structural kinds,
  replay behavior and replay-manifest hashes, Phase 17 artifact
  queries, the Phase 18 campaign trajectory matrix, and Phase 19
  declaration behavior and compiled observation snapshots are
  unchanged. **Phase 21 has not started.**

## Phase 21 status

**Deterministic campaign metric-observation matrix (COMPLETE).** Phase
21 assembles the **complete campaign observation matrix** of one
completed runtime-2.0.0 campaign: the exact authoritative strategy x
shared-seed raw-observation layout. Phase 18 owns the fair strategy x
seed layout (`CampaignTrajectoryMatrix`); Phase 20 owns the verified
per-run raw observation artifacts (`RunMetricObservationSet`); Phase 21
binds every completely verified Phase 20 set to its exact Phase 18
trajectory cell and produces `CampaignMetricObservationMatrix` - the
34th public contract, appended last, with `CampaignMetricObservationCell`
and the Phase 20 `RunMetricObservationValue` remaining nested (never
registered as top-level contracts).

- **Contracts**: `CampaignMetricObservationMatrix` (frozen,
  `extra="forbid"`, runtime literal `2.0.0`, comparison mode
  `identical_conditions`, unique and strictly increasing identifier
  collections, complete Cartesian cell coverage in exact
  strategy-major/seed-minor order, contiguous sequence positions, exact
  per-cell identity and metric binding, self-covering content hash,
  timezone-aware `assembled_at`).
- **Pipeline**: COMPLETE gate -> existing verified Phase 18 query
  (`get_verified_campaign_trajectory_matrix`) as the authoritative
  layout -> existing verified Phase 20 query
  (`get_verified_run_metric_observation_set`) for every run -> pure
  in-memory builder (`build_campaign_metric_observation_matrix`).
  Missing, foreign, partial, inconsistent, or corrupted Phase 20
  artifacts inside a COMPLETE campaign reject the whole matrix with
  `CampaignMetricObservationMatrixIntegrityError` (409 integrity_error);
  non-COMPLETE campaigns 409 invalid_state; legacy/unsupported runtime
  409 conflict; unknown/foreign campaigns 404. No partial matrix is
  ever returned.
- **Read-only and stateless**: `GET
  /v1/campaigns/{campaign_id}/metric-observation-matrix` only (no
  POST/PUT/PATCH/DELETE); the matrix is assembled in memory and **never
  stored** (no store collection or method exists); missing Phase 20
  sets are **never automatically extracted**; no execution, replay,
  repair, lifecycle, operational-activity, or Colony changes.
- **Determinism**: identifier from campaign/world/runtime identity;
  content hash over the canonical serialization excluding
  `content_hash`; `assembled_at` from the recorded campaign `created_at`
  - never the wall clock; repeated builds and repeated GET responses
  are byte-identical; raw values and provenance are preserved exactly
  (integers stay integers, no float conversion).
- **Error hygiene**: public messages never leak raw observation values,
  hashes, state values, guard/target values, policy content, metadata,
  another tenant's records, or internal integrity reasons.
- **Non-goals**: no aggregation, distributions, outcomes, evidence,
  scoring, ranking, recommendations, decision briefs, strategy
  comparison conclusions, normalization/transformation/unit conversion,
  uncertainty sampling, new runtime versions, automatic extraction
  during execution, operational-activity kinds, Colony changes, real
  NEXUS/LEGION integration, live actions, external providers/network,
  filesystem/database persistence, new dependencies, AGENTS.md/global-
  config changes, commits or pushes. Runtime 1.0.0/2.0.0 behavior,
  RunPlan generation, campaign/run lifecycle, trajectory planning,
  transition evaluation, `RunTrajectoryExecution` generation and
  hashes, `RunEvent` and its structural kinds, replay behavior and
  replay-manifest hashes, Phase 17 artifact queries, the Phase 18
  campaign trajectory matrix, Phase 19 declaration behavior, and Phase
  20 extraction behavior are unchanged. **Phase 22 has not started.**

## Phase 22 status

**Deterministic campaign metric statistics (COMPLETE).** Phase 22
derives the **descriptive-statistics matrix** of one completed
runtime-2.0.0 campaign exclusively from its completely verified Phase 21
`CampaignMetricObservationMatrix` - never from the store, and never from
anything else. Phase 21 supplies the verified raw strategy x seed
observation matrix; Phase 22 summarizes each strategy's exact metric
observations across the campaign's identical ordered shared seeds with
the fixed descriptive statistics - minimum, maximum, arithmetic mean,
median, and population standard deviation (population denominator N;
`math.fsum`/`math.sqrt`; Python standard library only) - producing
`CampaignMetricStatisticsMatrix`, the 35th public contract, appended
last, with `CampaignStrategyMetricStatistics` remaining nested (never
registered as a top-level contract).

- **Contracts**: `CampaignStrategyMetricStatistics` (frozen,
  `extra="forbid"`; non-empty exact finite observed values preserved in
  seed order with raw integers staying integers; booleans/strings/None/
  containers/NaN/Infinity rejected; count/length consistency; minimum
  and maximum equal to the exact observed extrema; finite derived
  statistics; single-observation standard deviation exactly `0.0`) and
  `CampaignMetricStatisticsMatrix` (frozen, `extra="forbid"`, runtime
  literal `2.0.0`, comparison mode `identical_conditions`, statistics
  mode literal `descriptive`, unique and strictly increasing identifier
  collections, complete strategy x metric Cartesian summary coverage in
  exact strategy-major/metric-minor order with contiguous positions and
  identity-vs-position agreement, per-summary observed length equal to
  the seed count, empty metrics require empty summaries, self-covering
  content hash, timezone-aware `summarized_at`).
- **Pipeline**: COMPLETE gate -> existing verified Phase 21 query
  (`get_verified_campaign_metric_observation_matrix`) as the sole
  authoritative source -> pure in-memory builder
  (`build_campaign_metric_statistics_matrix`). Missing or corrupted
  Phase 18/20/21 inputs preserve the existing safe typed 409 behavior;
  Phase 22 calculation, consistency, overflow, or non-finite failures
  raise `CampaignMetricStatisticsIntegrityError` (409 integrity_error);
  non-COMPLETE campaigns 409 invalid_state; legacy/unsupported runtime
  409 conflict; unknown/foreign campaigns 404. No partial matrix is
  ever returned.
- **Read-only and stateless**: `GET
  /v1/campaigns/{campaign_id}/metric-statistics` only (no
  POST/PUT/PATCH/DELETE); the matrix is derived in memory and **never
  stored** (no store collection or method exists); no automatic Phase
  20 extraction; no execution, replay, repair, lifecycle,
  operational-activity, or Colony changes.
- **Determinism**: identifier from campaign/world/runtime/source-matrix
  identity; content hash over the canonical serialization excluding
  `content_hash`; `summarized_at` from the authoritative Phase 21
  matrix `assembled_at` - never the wall clock; repeated builds and
  repeated GET responses are byte-identical; exact raw values are
  preserved in seed order (integers stay integers).
- **Error hygiene**: public messages never leak raw observation values,
  calculated statistics, hashes, state values, field names, strategy
  policy content, metadata, another tenant's records, or internal
  integrity reasons.
- **Non-goals**: no ranking, scoring, winner declaration, objective/
  target comparison, pass/fail judgments, `MetricOutcome`,
  `OutcomeVector`, `DistributionSummary`, evidence, `DecisionBrief`,
  recommendations, declared aggregation-policy interpretation,
  quantiles/confidence intervals, normalization/transformation/unit
  conversion, uncertainty sampling, new runtime versions, automatic
  extraction during execution, operational-activity kinds, Colony
  changes, real NEXUS/LEGION integration, live actions, external
  providers/network, filesystem/database persistence, new dependencies,
  AGENTS.md/global-config changes, commits or pushes. Runtime
  1.0.0/2.0.0 behavior, RunPlan generation, campaign/run lifecycle,
  trajectory planning, transition evaluation, `RunTrajectoryExecution`
  generation and hashes, `RunEvent` and its structural kinds, replay
  behavior and replay-manifest hashes, Phase 17 artifact queries, the
  Phase 18 campaign trajectory matrix, Phase 19 declaration behavior,
  Phase 20 extraction behavior, and the Phase 21 metric-observation
  matrix are unchanged. **Phase 23 is complete (next section).**

## Phase 23 status

- **Deterministic objective-to-metric evaluation (COMPLETE).**
  `ScenarioEvaluationProfile` (36th public contract) + `CampaignObjectiveEvaluationMatrix`
  (37th, appended last); `ObjectiveMetricBinding` and
  `ObjectiveObservationEvaluation` stay nested. Exactly two new schema
  artifacts; `PUBLIC_CONTRACTS` 35 -> 37; no existing v1 contract
  field changed.
- **Declaration**: one immutable profile per tenant + scenario;
  caller supplies only `objective_id`, `metric_id`, `reach_tolerance`,
  `normalization_scale` (+ `declared_at`, `metadata`); direction,
  target, weight, metric unit copied from the stored `ScenarioSpec`
  (forged authoritative fields impossible); bindings canonicalized
  into the exact `ScenarioSpec.objectives` order; complete coverage,
  exactly-one reference per objective; reach-tolerance/scale rules;
  declaration before first world compilation; duplicates 409; no
  update/replace/delete/list surface; deep-copy + strict
  revalidation on write and every read (with independent
  ownership/identifier/content-hash verification before any copy
  crosses the store boundary); tenant isolation.
- **Evaluation semantics** (pure builder over the verified Phase 21
  matrix): direction-aware `signed_target_delta` (positive =
  adverse), `target_achieved = delta <= 0`, `normalized_target_violation
  = max(0, delta) / scale`; optimization-only objectives carry `None`
  evaluation fields; exact int/float preservation; bool/NaN/Infinity
  rejected before coercion everywhere; overflow/non-finite derived
  values reject the complete matrix (409). Target violation only - no
  regret/ranking/dominance/probability/confidence/distribution/risk/
  evidence/recommendation semantics.
- **World integration**: dedicated `evaluation_profile` key embedded
  only when a profile exists - profile-free worlds stay byte-identical
  to Phase 22; `verify_world_snapshot` re-derives scenario hash,
  profile id/hash, coverage, copied values, tolerance/scale rules, and
  recompile-equality; `VerifiedWorldCatalog.evaluation_profile`.
- **Pipeline**: COMPLETE gate -> verified Phase 21 matrix -> verified
  compiled world -> world-embedded profile matched to the stored
  record (404 when absent, 409 when missing/mismatched) -> in-memory
  matrix, never stored; GET-only endpoint; typed 404/409
  `invalid_state`/409 `conflict`/409 `integrity_error`; no automatic
  extraction, no operational-activity, no Colony changes.
- **API**: `POST`/`GET /v1/scenarios/{scenario_id}/evaluation-profile`,
  `GET /v1/campaigns/{campaign_id}/objective-evaluations` (direct
  contracts, `ApiErrorResponse` envelope unchanged, non-leaking
  messages, byte-identical repeats).

## Phase 24 status

- **Deterministic world uncertainty realizations (COMPLETE).**
  `WorldUncertaintyModel` (38th), `WorldRealization` (39th), and
  `CampaignWorldRealizationMatrix` (40th, appended last);
  `PUBLIC_CONTRACTS` 37 -> 40. The five distribution families
  (`uniform`, `triangular`, `normal`, `lognormal` - mu/sigma are
  log-space parameters - and `discrete`) form a closed discriminated
  union; `StateFieldUncertaintyBinding`, `SampledStateFieldValue`,
  `RealizedStateFieldValue`, and the five distributions stay nested.
  Exactly three new schema artifacts; no existing v1 contract field
  changed; `UncertaintyDefinition` untouched.
- **Sampler** (`sha256-counter-v1`): integer-only Q64.64 fixed-point,
  `rational-round-half-even` quantization via exact
  `float.as_integer_ratio()` + `divmod`; frozen integer literals
  (never platform libm); one SHA-256 per digest word over the
  domain-separated canonical payload (world/seed/binding hashes, draw
  index - no strategy terms); open-uniform `u = (word + 1) / 2**64`
  (never zero); exact `isqrt` square root; fixed-iteration atanh log,
  ln2-reduced exp (pre-shift `k > 1024` guard, `k < -65` -> 0), and
  quadrant-reduced cos; Box-Muller with the invariant-checked
  `Z_MAX = isqrt(128 ln2)`; exact-weight discrete tickets with strict
  `<` boundaries, zero-probability entries never selected, no forced
  residual.
- **Representation**: canonical JSON `1` vs `1.0` distinct;
  continuous raws always float; discrete preserves the declared value
  type; clipping adopts the exact stored bound type; integer targets
  always finish as exact `int`; operation order is **finite raw ->
  clip -> round -> complete-state validation** (existing
  `validate_state` rules incl. canonical `allowed_values`); raw
  recorded before clipping; no retry/resampling; deterministic
  per-seed failure (409 `conflict`).
- **Declaration**: one immutable model per tenant + scenario,
  caller-owned fields only (provenance always copied from stored
  records); canonical `(manifest_id, state_model_id, state_field_id)`
  binding order; only `integer`/`number` initial-state fields;
  rounding-policy/bound/discrete-kind/effective-parameter/static
  discrete allowed-values rules (422); declaration before first world
  compilation (409); duplicates 409; deep-copy + strict revalidation
  + identity/hash verification on write and every read; no
  update/replace/delete/list surface; no operational activity.
- **World integration**: `uncertainty_model` key embedded only when a
  model exists - model-free worlds byte-identical to Phase 23, no
  runtime-2 golden hash changes; `verify_world_snapshot` re-derives
  model id/hash, ownership, canonical order, copied provenance,
  sampler literals, effective parameters, static discrete allowed
  outcomes, and recompile-equality; `VerifiedWorldCatalog.uncertainty_model`.
- **Pipeline**: verified world/manifest -> stored model strictly
  revalidated and canonically matched to the embedded snapshot ->
  pure in-memory builder (one realization per seed, strategy
  independent, K realizations for K seeds and any S strategies) ->
  matrix returned directly, never stored; no lifecycle gate (any
  recorded campaign state yields identical bytes); absent model ->
  deterministic empty realizations with real derived hashes; no
  writes, no activity, no NEXUS/LEGION calls, no execution.
- **API**: `POST`/`GET /v1/scenarios/{scenario_id}/uncertainty-model`,
  `GET /v1/campaigns/{campaign_id}/world-realizations` (direct
  contracts, 201/200/404/409 conflict/409 integrity_error/422,
  `ApiErrorResponse` envelope unchanged, non-leaking messages,
  byte-identical repeats).
- **Non-goals**: no execution, replay, transition, metric extraction,
  objective evaluation, outcomes, distributions, comparison, ranking,
  recommendation, evidence, or decision briefs; no new runtime
  version; no NEXUS/LEGION integration; no live actions/providers/
  network/filesystem/database; no new dependencies; no operational-
  activity kinds; no Colony changes; no Phase 25 work; no commits or
  pushes.


## Phase 25: realization-aware trajectory runtime 3.0.0

**Status: COMPLETE**, included in one local closure commit (the local
Phase 25 closure commit containing this documentation; **not pushed** -
`origin/main` remains at
`f40e83de468ca14100d011454d15eb3dd561c810` and local `main` is exactly
one commit ahead; push is intentionally deferred until Phases 26 and 27
are complete; see `KALHAS_HANDOFF_PHASE_25.md`). **Phase 26 has not
begun** was true at the Phase 25 checkpoint; it is superseded by the
Phase 26 section below. This section supersedes the historical
statements above that Phase 25 "has not started" / "no Phase 25 work".

### Architecture

- **One verification core, three runtimes.** `verify_run_inputs` loads
  and verifies every authoritative record (status, plan, campaign,
  world + manifest via `verify_world_snapshot`, strategy, seed,
  stored-vs-embedded uncertainty model), then dispatches only the
  input-hash recomputation on the recorded `RunPlan.runtime_version`:
  1.0.0/2.0.0 recompute the frozen runtime-2 digest with the identical
  historical statements; 3.0.0 reconstructs the Phase 24 realization
  exactly once at `run_plan.created_at` and recomputes the runtime-3
  digest. `verify_run_trajectory_inputs` is the single runtime-3
  trajectory entry: closed compiled-world catalogs, exact stored plan
  tuple, realization provenance re-derivation, and
  `VerifiedRunTrajectoryInputs.realization`. Execution, replay,
  observation extraction, all three matrix queries, preflight, and the
  verify-inputs endpoint all consume this one chain.
- **Preparation and planning.** `prepare_realization_campaign` gates on
  exactly 3.0.0 before any store read; verifies world integrity and
  model consistency; builds the `CampaignWorldRealizationMatrix` once
  (K realizations, never K x S; derived, never stored); plans the
  strategy-major/seed-minor run matrix with
  `plan_realization_runs`, binding each seed's realization content hash
  into every strategy's `run_realization_input_hash`. The read-only
  `preflight_realization_run_plan_matrix` rebuilds the exact matrix and
  requires tuple equality before any LEGION call or write; campaign
  execution calls it exactly once before the first run.
  `prepare_strategy_trajectory_plans` dispatches preflight by recorded
  runtime and binds every draft through the fail-closed
  `MockLegionAdapter(declared_transition_sequences=...)` seam (logical
  id -> deterministic identifier resolution; unknown/ambiguous ids
  raise `InvalidTrajectoryDraftError`; canonical default only for
  undeclared strategies; KALHAS re-validates every draft).
- **Execution.** `execute_realization_run` (per-run) and
  `execute_realization_campaign` (complete-matrix preflight first, then
  exact stored order) evaluate the real engine from the realized
  initial state and write the immutable
  `RealizationRunTrajectoryExecution` (realization id/hash, plan-set
  hash, ordered results, self-covering content hash, `executed_at` =
  `run_plan.created_at`). Attempt records are bound
  position-by-position to the authoritative plan references (closes the
  fully-rehashed alternate-transition attack). Pre-existing artifacts,
  even identical, are never overwritten; any pre-write failure leaves
  zero writes.
- **Observations and replay.** Extraction is an explicit POST that
  verifies the stored execution, reads only
  `final_state[state_field_id]` per embedded binding with strict
  numeric-kind rules, and stores the observation set exactly once.
  Replay **requires prior extraction** (typed 404, zero writes
  otherwise), independently regenerates execution + observation set +
  structural events, requires canonical-JSON equality, and writes the
  generic + runtime-3 manifest pair (the runtime-3 manifest is
  self-covering over the full payload including observation-set
  hashes). The two manifests are sequential writes: a mid-write
  interruption can leave a missing manifest, recovered idempotently by
  the next replay (identical bytes); a corrupted manifest blocks replay
  and is never replaced. Repeated replay is byte-identical.
- **Derived matrices, read-only queries.** The trajectory matrix
  (strategy-major/seed-minor cells, seed-aligned realization tuples,
  cell<->tuple agreement), the metric-observation matrix (per-cell
  verified observation sets, preserved raw values), and the
  descriptive-statistics matrix (frozen Phase 22 functions only) are
  built purely in memory and served by verified queries that re-verify
  world snapshot, stored plan matrix, and every per-cell artifact -
  zero writes, zero activity, byte-identical repeats. Realizations and
  matrices are **derived, never stored**.
- **Module ownership.** The adapter boundary is used only during
  planning (`campaign_service`, `strategy_trajectory_service`,
  `realization_campaign_service` - exactly the `LegionAdapter`
  protocol); execution, replay, observation, and matrix modules never
  import or invoke LEGION/NEXUS. Runtime-2 and Phase-24 modules carry
  no runtime-3 dependency and are unchanged. No runtime-3 module uses
  network, providers, databases, filesystems, wall clocks, randomness,
  UUIDs, `random.seed`, or domain-pack execution; timestamps come only
  from recorded `created_at` values.
- **Fail-closed boundaries.** Runtime gates fire before any downstream
  service call on every runtime-3 endpoint and runtime-2 artifact
  endpoint; empty run-plan tuples fail closed with the typed
  unsupported-runtime 409; public error messages stay generic (values
  and hashes remain internal reasons); GETs and extraction record no
  operational activity; no outcome, ranking, score, evidence,
  recommendation, or decision-brief surface exists anywhere in the
  runtime-3 modules.

### Contracts, schemas, API

- 6 new public contracts at indexes 40-45 (46 total), exact order:
  `RealizationRunTrajectoryExecution`,
  `RealizationRunTrajectoryReplayManifest`,
  `RealizationCampaignTrajectoryMatrix`,
  `RealizationRunMetricObservationSet`,
  `RealizationCampaignMetricObservationMatrix`,
  `RealizationCampaignMetricStatisticsMatrix`; 3 nested unregistered
  value objects; 6 new schema artifacts (46 total); indexes 0-39 and
  the 40 historical schema artifacts unchanged.
- Exactly 6 new paths / 7 operations (`kalhas/api/routes_realization.py`):
  GET realization-trajectory-execution, GET
  realization-trajectory-replay-manifest, POST + GET
  realization-metric-observations (201/200), GET
  realization-trajectory-matrix, GET
  realization-metric-observation-matrix, GET
  realization-metric-statistics - all rejecting recorded runtime !=
  3.0.0 with 409, GETs read-only with no activity, extraction recording
  no activity, single `ApiErrorResponse` envelope unchanged.
- Runtime-2 compatibility is test-enforced: runtime-2 golden digests,
  artifacts, OpenAPI `$ref`s, and the Phase 17/20/22 canary suites pass
  unchanged; runtime-2 and Phase-24 sources are untouched.

### Acceptance proof (84/103)

Fixed seeds seed-0/seed-2 realize the two branches of a discrete
uncertainty binding on the integer `level` field (branch X = 5, branch
Y = 9). Two declared guarded transitions - `t-x` (guard `level == 5`,
target `level -> 84`) and `t-y` (guard `level == 9`, target
`level -> 103`) - are proposed in opposite orders by the two strategies
(`mock-a`: `[t-x, t-y]`; `mock-b`: `[t-y, t-x]`). Exactly one guard
succeeds per seed, so the real engine produces 84 for seed-0 and 103
for seed-2 under both strategies; attempt records prove each outcome;
observation matrices are exactly `[84, 103]` per strategy in seed
order; per-strategy statistics are min 84.0 / max 103.0 / mean 93.5 /
median 93.5 / population std 9.5; replay regenerates identical
execution and observation hashes; repeated preparation and queries are
byte-deterministic; no input contract is mutated.

## Phase 26: empirical campaign outcome distributions

**Status: IMPLEMENTATION-COMPLETE, GATE-VERIFIED, COMMITTED AND
PUBLISHED.** Phase 26 was implemented, gate-verified, committed, and
published at commit `886f398c288971d612fa57bd1d1e731113a69f72`. The
complete Phase 26 change set (19 created paths plus 21 modified
integration paths; exact inventory in `KALHAS_HANDOFF_PHASE_26.md`) is
fully recorded at that closure commit; the phase handoff remains a
historical pre-commit checkpoint snapshot and is not rewritten. This
section supersedes the historical Phase 25-checkpoint statements above
that Phase 26 "has not begun" / "Phase 26 and Phase 27 are not
implemented or designed here"; the earlier "Phase 27 has not begun"
statements are superseded by the Phase 27 section below, which records
Phase 27 as committed and published.

### Purpose and claim boundary

Phase 26 transforms verified runtime-3 shared-seed observations into
per-strategy/per-objective **empirical** outcome evidence: exact
ordered empirical samples, distribution statistics, empirical
target-achievement probability, normalized target-violation evidence,
direction-aware adverse-tail evidence, and CVaR95 target-violation
evidence. It does **not** produce rankings, winners, preferred
strategies, recommendations, confidence intervals, forecast certainty,
universal real-world probability, decision briefs, NEXUS/LEGION
narrative, or true-causality / reality-prediction claims. "Empirical"
is used consistently; no claim is calibrated to real-world probability.

### Statistics

- Exact-type finite numeric validation: exact `int`/`float` only;
  `bool` rejected; strings, `Decimal`, `None`, containers, NaN, and
  Infinity rejected; raw types preserved.
- Full-domain finite-float conversion proof: every sample must convert
  to a finite float before any selection/arithmetic; huge
  positive/negative unrepresentable integers raise `OverflowError`;
  invalid input raises `ValueError`.
- Hyndman-Fan Type 7 quantiles (identifier `hyndman-fan-type-7-v1`)
  with integer numerator/remainder indexing and `math.fsum`
  interpolation; explicit one-sample behavior (all values equal the
  projected sample, std dev exactly 0.0) and finite-sample behavior
  (repeated-value collections emit exact 0.0 std dev; one-adjacent-
  float-step contract composability).
- Arithmetic mean, median, and population standard deviation reuse the
  frozen Phase 22 primitives.
- p05/p25/p75/p95 quantiles; fixed CVaR alpha 0.95 with the fractional
  tail-mean algorithm `empirical-fractional-tail-mean-v1` (exact
  5/100 mass; no `ceil(0.05*n)`, no unweighted selection).
- Target-violation semantics (Phase 23): minimize / maximize / reach
  formulas in exact seed order; direction-aware adverse-tail semantics
  (upper-tail mean for minimize, lower-tail mean for maximize,
  upper-tail mean of absolute deviation for reach); optimization-only
  objectives keep target probability/violation/CVaR `null` while the
  adverse-tail statistic remains available.
- One-ULP golden-test discipline per the established convention.
- Production uses plain `int`/`float`/`math.fsum`; **no `Decimal` or
  `Fraction` in production.**

### Contracts, identity, schemas

- `EmpiricalDistributionSummary` and `StrategyObjectiveOutcome` are
  nested strict frozen value objects (unregistered, no schema
  artifacts); `StrategyObjectiveOutcome` independently recomputes the
  normalized-violation tuple and achievement count.
- `CampaignOutcomeDistributionMatrix` is the only Phase 26 top-level
  public contract: `PUBLIC_CONTRACTS` index 46, **47 total public
  contracts, 47 total schema artifacts** (only
  `CampaignOutcomeDistributionMatrix.schema.json` added).
- Exact strategy-major/objective-minor ordering, complete Cartesian
  coverage, exact shared-seed ordering; deterministic identifier
  (source-identity hash-derived, never content-hash/timestamp-derived),
  self-covering content hash, `derived_at` = observation-matrix
  `assembled_at` (never wall clock).
- Source binding and verification: evaluation profile, optional
  uncertainty model (both-or-neither), world-realization matrix, and
  metric-observation matrix identities/content hashes.

### Builders and verified query

Five separated responsibilities: (1) pure statistical primitives
(`campaign_outcome_statistics.py`, stdlib-only); (2) pure
strategy/objective outcome builder (`campaign_outcome_runtime.py`); (3)
deterministic matrix identity (`campaign_outcome_identity.py`); (4)
pure complete matrix builder (`campaign_outcome_matrix_runtime.py` —
strict revalidation, identity/hash verification, cross-source
consistency, structural verification, single typed integrity-error
boundary); (5) independently verified read-only query service
(`campaign_outcome_query_service.py`). The query revalidates
tenant/campaign/scenario/world ownership and identity, exactly COMPLETE
state, recorded runtime exactly 3.0.0, evaluation profile, uncertainty
model, realization matrix, observation matrix, exact run-plan/strategy/
seed ordering, objective/metric bindings and units, and every
identity/content hash and numeric invariant. The matrix is derived in
memory and never stored; querying never executes, replays, extracts,
repairs, creates, or writes an upstream artifact and records no
operational activity; repeated queries are byte-identical.

### API and compatibility

`GET /v1/campaigns/{campaign_id}/outcome-distributions`: required
`X-Tenant-ID`, no request body, no runtime selector (runtime derived
exclusively from the recorded `RunPlan` tuple; empty or non-3.0.0 plan
tuples fail closed with the typed 409 `conflict` before the query),
direct `CampaignOutcomeDistributionMatrix` response, safe typed 404
(unknown/foreign campaign; missing embedded profile) and 409
(`invalid_state` non-COMPLETE; `conflict` runtime; `integrity_error`
corrupted sources), repeated byte-identical reads, no mutation methods.
Phase 25 paths/operations preserved; `API_VERSION` and `SCHEMA_VERSION`
unchanged; runtime remains 3.0.0; runtime 1.0.0/2.0.0 preserved.

### 100-seed causal acceptance proof

`tests/phase26_helpers.py` + `tests/test_phase26_acceptance.py` prove,
through the real lifecycle: 100 fixed authoring-time seeds (81 branch-X
+ 19 branch-Y, never searched at runtime); 100 realizations, never 200;
two distinct declared strategies; 200 runtime-3 executions and 200
explicit extractions; identical per-seed realization identity/hash
across strategies; branch values 5 and 9 causally producing observed
values 84 and 103 through the real guarded transitions; exactly 81/19
target achievements with `empirical_target_achievement_probability ==
0.81`; min 84.0 / max 103.0 / mean 87.61 / median 84.0 / population std
7.453717193454551; Type-7 p05/p25/p75 = 84.0 and p95 = 103.0; worst
normalized target violation 0.03; CVaR95 0.03; adverse-tail statistic
103.0; representative exact replay of both branches (manifest pair,
expected == recomputed, idempotent); repeated byte-identical GETs with
unchanged store digest and zero activity; no injected or patched
result. Matrix identifier
`campaign-outcome-distribution-matrix-4c9a997c4f57df7d`; content hash
`a5717de324af501c937b8b87cd114006edda1311ff811bd64fe0893f8ec5c230`;
`derived_at` `2026-01-01T12:00:00Z` (= observation-matrix
`assembled_at`).

### Non-goals and next phase

No paired strategy comparison, feasibility policy, Pareto analysis,
regret/minimax selection, ranking or campaign decision brief, adaptive
policy runtime, KALHAS-PAN, historical benchmark, real LEGION/NEXUS
integration, or production database/queue/auth/deployment/command-center
expansion. No reality-prediction or true-causality claims. **Phase 27**
(robust paired comparison and campaign decision brief) has since been
implemented, gate-verified, committed, and published at the Phase 27
closure commit `a905d2af6b155a0f2568037e2b0f410b20be8d91` (recorded in
the Phase 27 section below). Phase 28 and KALHAS-PAN remain **not
implemented** anywhere in the repository.

## Phase 27: robust paired comparison and campaign decision brief

**Status: IMPLEMENTATION-COMPLETE, GATE-VERIFIED, COMMITTED AND
PUBLISHED.** Phase 27 was implemented, gate-verified, committed, and
published at commit `a905d2af6b155a0f2568037e2b0f410b20be8d91` (the
Phase 27 closure commit on `main`). At this Gate 27.1 frozen baseline
`local main` and `origin/main` are both at that commit with divergence
`0 0` and an empty Git index. The exact change set is recorded in
`KALHAS_HANDOFF_PHASE_27.md`, which remains a historical pre-publication
checkpoint snapshot and is not rewritten. This section supersedes the
historical Phase 26-checkpoint statements above that Phase 27 "has not
begun" / "is not implemented". Phase 28 and KALHAS-PAN remain **not
implemented** anywhere in the repository.

### Architecture

- **Immutable per-campaign decision policy** (`CampaignDecisionPolicy`):
  one policy per `(tenant_id, campaign_id)`, declared only for a
  COMPLETE 3.0.0 campaign; stored in the store's single
  `_campaign_decision_policies` collection; duplicates rejected with
  the typed 409, never overwritten; no update/delete/replace surface;
  every read strictly revalidates the contract and independently
  recomputes the deterministic identifier and the self-covering
  content hash, then returns a deep defensive copy. The policy binds
  the campaign/scenario/world/evaluation-profile identity and hashes,
  the frozen algorithm identifier
  `feasibility-pareto-minimax-regret-v1`, the fixed tail alpha `0.95`
  (callers cannot select another), global-or-per-objective hard target
  thresholds, minimum sample count, tie tolerance, and the
  authoritative objective-weight snapshots copied from the verified
  evaluation profile. Declarative data only - never executable.
- **Evidence sufficiency and feasibility** (`campaign_decision_evidence.py`):
  the recorded seed count gates the whole decision
  (`insufficient_evidence` is a successful result, never a guess);
  every targeted objective's hard threshold is checked against the
  empirical target-achievement probability; infeasible strategies are
  excluded from dominance and minimax selection.
- **Same-seed paired comparisons** (`campaign_decision_statistics.py`,
  `campaign_decision_paired_comparison.py`): ordered paired deltas on
  identical shared seeds in authoritative seed order (positive always
  means the first strategy is worse), win/tie/loss counts and rates
  under the exact declared tie tolerance, median/p05/p95/worst/best
  paired deltas; exactly `S * (S - 1) * O` records - no self-pairs,
  both directions of every pair - with exact mirror invariants
  (reverse delta negation, swapped win/loss, preserved ties, Type-7
  sign-flip p05/p95, worst reverse = negated forward best).
- **Pareto dominance among feasible strategies**
  (`campaign_decision_selection.py`): dominance relations are derived
  from the stored paired comparisons and the evidence feasibility
  flags only; the non-dominated set is exactly the feasible,
  non-dominated strategies.
- **Per-seed weighted regret and minimax robustness**: same-seed
  comparative regret (distinct from target violation), weighted by the
  authoritative objective weights, summed per seed in objective order,
  summarized by median/p95/maximum; the unique minimum maximum total
  weighted regret among feasible non-dominated strategies is the
  robust preference; the minimax tie set is the exact inclusive
  `<= best + tie_tolerance` set (no isclose/relative/ULP relaxation,
  no arbitrary winner).
- **Deterministic brief** (`campaign_decision_brief_runtime.py`): one
  of four statuses - `preferred` exactly when the tie set is a
  singleton, `inconclusive` when several feasible non-dominated
  strategies remain tied (a tie never manufactures a winner),
  `insufficient_evidence`, `no_feasible_strategy`; terminal reason
  code plus ordered decisive/blocking factor trails; fixed summary
  templates over recorded facts only; no chain-of-thought, hidden
  reasoning, scripts, callbacks, or executable expressions.
- **Policy-first query order** (`campaign_decision_query_service.py`):
  campaign -> exactly COMPLETE status -> **verified policy (404 before
  any derivation when absent)** -> outcome query exactly once ->
  comparison builder exactly once -> (brief) brief builder exactly
  once reusing the same policy/outcome/comparison chain. The
  comparison and the brief are derived in memory and **never stored**;
  no execution, replay, extraction, evaluation, write, or operational
  activity; repeated queries are byte-identical.
- **Module ownership**: no Phase 27 module imports NEXUS/LEGION,
  adapters, domain packs, providers, network, database, filesystem,
  wall clock, or randomness; `datetime` appears only as the type guard
  for the caller-supplied timezone-aware `declared_at`; no Phase 28 or
  KALHAS-PAN surface; no adaptive decision-policy runtime.
- **Colony UI**: the animated demo is intentional synthetic local
  visualization work - clearly labeled deterministic client-side
  synthetic data (no network request), not decision evidence and not a
  real forecast; the operational observatory remains read-only and
  pull-based.

### Contracts, schemas, API

- `PUBLIC_CONTRACTS` index 47 `CampaignDecisionPolicy`, 48
  `CampaignStrategyComparison`, 49 `CampaignDecisionBrief`; **50 total
  contracts**, indexes 0-46 unchanged; the 12 nested decision value
  objects remain unregistered.
- **50 total schema artifacts**; the three new artifacts match
  `model_json_schema()`; all 47 historical byte hashes unchanged.
- `API_VERSION` `"1"` and `SCHEMA_VERSION` `"1.0.0"` unchanged; runtime
  remains exactly 3.0.0.
- Exactly four operations on three paths
  (`kalhas/api/routes_campaign_decision.py`), required `X-Tenant-ID`
  on all four, recorded-runtime gate (every plan exactly 3.0.0; empty
  or mixed/legacy tuples fail closed with the typed 409 before any
  service call), no runtime selector:
  `POST`/`GET /v1/campaigns/{campaign_id}/decision-policy` (201/200),
  `GET /v1/campaigns/{campaign_id}/strategy-comparison` (200), `GET
  /v1/campaigns/{campaign_id}/decision-brief` (200). Safe typed
  mappings: 404 unknown/foreign campaign and missing/foreign policy;
  409 `invalid_state` non-COMPLETE; 409 `conflict` duplicate policy and
  unsupported recorded runtime; 422 invalid policy drafts; 409
  `integrity_error` policy/comparison/brief corruption - generic
  non-leaking bodies throughout. A stored policy remains retrievable
  after the campaign leaves COMPLETE.

### 100-seed causal acceptance proof and honest limitations

The acceptance fixture proves, through the real lifecycle (100 fixed
static seeds `seed-000` ... `seed-099`, 3 distinct declared strategies,
300 executions and 300 explicit extractions, real policy declaration,
verified queries only): mock-a has the best ordinary primary mean
(32.46) but the worst maximum total weighted regret (4.0); mock-b has
primary mean 94.26 and the unique minimax maximum total weighted regret
(2.24) - the preferred strategy; mock-c is dominated by mock-b; the
tie control yields zero paired deltas, no dominance, and an
`inconclusive` brief with no winner. Best ordinary mean is not the
robust winner. The decision output is evidence-based under the declared
models/policies - **not calibrated**, **not certainty**, and driving
**no autonomous live action**; it does not predict reality and is not a
guarantee of any outcome. Phase 28 and KALHAS-PAN are not implemented.
