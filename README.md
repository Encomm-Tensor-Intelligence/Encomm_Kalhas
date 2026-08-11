# KALHAS

Domain-neutral kernel for **versioned world models, uncertainty, deterministic
simulation campaigns, evidence, and replay** - plus the future living-simulation
experience.

**Phase 0 scope:** the domain-neutral foundation and a minimal standalone live
API only. No domain implementation, no simulation engine, no database, no
external integrations.

**Phase 1 scope:** the generic, versioned public contract layer
(`kalhas/contracts/v1/`) and the deterministic campaign lifecycle state
machine (`kalhas/application/campaign_lifecycle.py`). Still no simulation
runtime, no persistence, no API endpoints for campaigns.

**Phase 2 scope:** standalone scenario validation, deterministic world
compilation, in-memory storage, local mock adapters, and a minimal
scenario/world API. The system remains a local, in-memory, standalone proof
- no real NEXUS or LEGION integration, no database, no network calls.

**Phase 3 scope:** deterministic campaign preparation and run planning. A
campaign is prepared (COMPILED) with an ordered run plan per strategy-seed
pair and can be started (RUNNING), but **runs are planned, not simulated**:
no outcome generation, no evidence, no events in this phase.

**Phase 4 scope:** deterministic structural execution, ordered run events,
and exact replay. A RUNNING campaign executes every planned run in order;
each run emits exactly three ordered structural events and completes with a
recorded event hash; completed runs can be replayed exactly. This is a
**kernel proof only**: COMPLETE means structural execution finished, not
that decision evidence was produced. No outcomes, evidence, briefs,
recommendations, or numeric ground truth exist in this phase.

**Phase 5 scope:** run-input integrity verification. Every run's recorded
inputs (world, persisted strategy candidate, seed, plan, runtime version)
are verified against the deterministic input hash before execution and
replay; campaigns are preflight-verified atomically before any run begins.
Integrity is checked, not assumed - but this is process-local deterministic
verification, not cryptographic signing or persistence.

**Phase 6 scope:** a tenant-scoped, declarative **domain pack registry**.
`DomainPackManifest` is the new public v1 contract: pure metadata (identity,
semantic pack version, supported KALHAS API versions, ordered declarative
capabilities, deterministic content hash) for a future domain pack. The
registry stores manifests tenant-scoped, rejects duplicates, and serves
deterministic listings - **metadata only, no pack implementation ships and
nothing is loaded, bound, or executed**.

**Phase 7 scope:** immutable **domain-pack bindings**. A tenant binds one or
more registered manifests to a scenario; every subsequently compiled
`WorldVersion` carries an exact immutable snapshot of those bindings, and
the world content hash changes with the binding set. A binding is
declarative metadata only - it never loads, instantiates, imports, or
executes a domain pack, and it does not interpret capability schemas.

**Phase 8 scope:** immutable **capability-input declarations**. A tenant
declares the input values for one capability of a manifest already bound to
the scenario; every subsequently compiled `WorldVersion` carries an exact
immutable snapshot of those declarations, and the world content hash changes
with the declaration set. Declarations are inert inputs: they are validated
only against the capability's declared input identifiers (exact key
matching, nothing more) and are never interpreted, executed, or turned into
outputs, evidence, or recommendations.

**Phase 9 scope:** a lightweight, tenant-scoped **operational activity
feed** for Encomm Colony observability (Phase 10 ships the local Colony
UI that reads it). Every successful lifecycle
operation appends one immutable structural `OperationalActivityEvent`
(scenario registered, world compiled, manifest registered, manifest bound,
capability inputs declared, campaign prepared/started/executed, run inputs
verified, run replayed) with a tenant-local strictly increasing sequence, a
deterministic `occurred_at` derived from the recorded source artifact, and a
strict structural payload. Retrieval is pull-based, bounded, and read-only:
`GET /v1/operational-activity` with an `after_sequence` cursor and a bounded
`limit`. The feed is observability only - it is not a simulation event
stream, not evidence, not hidden reasoning, and it never participates in any
world, plan, input-integrity, event, or replay hash. No frontend, streaming
transport, or polling loop is added in this phase.

## Phase 1: contracts and campaign lifecycle

### Versioned contract layer

Sixteen domain-neutral top-level contracts live in `kalhas/contracts/v1/`,
each with a stable identifier, a tenant identifier, and a semantic
`schema_version` (default `"1.0.0"`). All models are strict
(`extra="forbid"`); timestamps are timezone-aware; domain-specific values may
be carried only as JSON-like data (`JsonValue`) or declared metadata - no
executable expressions, callbacks, or plugin references.

| Contract | Purpose |
| --- | --- |
| `ScenarioSpec` | Declarative scenario: objectives, constraints, time horizon, metrics, assumptions (no seed ownership) |
| `ContextBundle` | Declared organizational context carried into KALHAS contracts |
| `ClarificationQuestion` | A question asking for clarification of a scenario or context |
| `ValidationReport` | Validation result with typed issues |
| `WorldManifest` | Declarative inventory of a world model version |
| `WorldVersion` | **Immutable** compiled world (frozen by contract), parent version id, provenance: source scenario, compiler version, content hash |
| `UncertaintyDefinition` | Declared uncertainty: distribution family + parameters (no sampling) |
| `StrategyRequest` | Request for strategy generation (LegionAdapter boundary) |
| `StrategyCandidate` | Declared policy + required observations + assumptions + version; never runs a strategy |
| `CampaignSpec` | Campaign comparing strategy candidates on a compiled world, under a shared ordered seed ensemble (fair comparison is structural) |
| `CampaignStatus` | Snapshot of a campaign's lifecycle state |
| `ScenarioSeed` | Reproducible, serializable seed material only |
| `RunEvent` | Run event with `sequence` (replay order), simulation time, and creation time |
| `RunPlan` | Deterministic planning manifest for one run: campaign, world, strategy, seed, runtime version, input hash |
| `RunStatus` | Lifecycle status of one run: PLANNED / RUNNING / COMPLETE / FAILED, input hash, event hash on completion |
| `ReplayManifest` | Provenance of an exact replay: regenerated event hash verified against the expected hash |
| `RunInputIntegrityManifest` | Attestation of exact input verification: expected vs recomputed input hash, deterministic `recorded_at` |
| `DomainPackManifest` | Declarative registry entry for a future domain pack: logical `pack_id`, semantic `pack_version`, supported KALHAS API versions (must include `1`), ordered capabilities, deterministic `content_hash` |
| `DomainPackBinding` | Immutable snapshot of a manifest bound to a scenario: exact pack identity, version, content hash, and ordered capability identifiers; never trusts client input |
| `OutcomeVector` | Per-run outcome: distributions, risks, assumptions, uncertainty, evidence |
| `EvidenceReference` | Declared provenance pointer to recorded evidence |
| `DecisionBrief` | Decision support: distributions, risks, uncertainty, evidence - never one unexplained score |

JSON Schema artifacts for every top-level contract are checked into
`schemas/v1/` and enforced in sync by `tests/test_schema_sync.py`:

```powershell
uv run python scripts/export_schemas.py           # regenerate
uv run python scripts/export_schemas.py --check   # verify
```

**Fair comparison is structural.** `CampaignSpec` owns a shared, ordered,
non-empty `seed_ensemble` of `ScenarioSeed` contracts with unique
identifiers; every strategy candidate receives the exact same ordered seed
identifiers and equivalent observation permissions. `comparison_mode` accepts
only `identical_conditions` (a `const` in the JSON Schema) - there is no
independent mode. Scenario-level input never owns seed assignment.

### Campaign lifecycle state machine

Pure, in-memory, side-effect-free; defined in
`kalhas/application/campaign_lifecycle.py` with an explicit transition table
and a typed `CampaignTransitionError` for invalid transitions:

```
DRAFT      -> VALIDATED, CANCELLED
VALIDATED  -> COMPILED, DRAFT, CANCELLED
COMPILED   -> RUNNING, VALIDATED, CANCELLED
RUNNING    -> COMPLETE, FAILED, CANCELLED
COMPLETE, FAILED, CANCELLED -> (terminal)
```

No campaign API endpoints exist yet (deliberate).

## Phase 2: scenario validation, world compilation, and local mocks

### Contract direction

```
ScenarioSpec -> semantic validation -> immutable WorldVersion -> CampaignSpec
```

`ScenarioSpec` describes intent only (no world reference, no seed
assignment). The deterministic world compiler emits an immutable
`WorldVersion` carrying `source_scenario_id`, `compiler_version`, and a
SHA-256 `content_hash`; `CampaignSpec` runs against that compiled world
(`world_version_id`).

### Application services (in-memory, deterministic)

| Module | Responsibility |
| --- | --- |
| `kalhas/application/in_memory_store.py` | Scenario/world storage keyed by `(tenant_id, identifier)`; rejects duplicates and foreign-tenant access |
| `kalhas/application/scenario_service.py` | Pure semantic validation: `ValidationReport` + `ClarificationQuestion`s for blocking omissions (objectives, time-horizon resolution, success metrics, constraints); never invents values |
| `kalhas/application/world_compiler.py` | Pure compiler: canonical JSON + SHA-256; same scenario + compiler version -> same content hash and world id; rejects invalid scenarios with `InvalidScenarioError` carrying the report |
| `kalhas/application/domain_errors.py` | Typed domain errors (`ScenarioNotFoundError`, `ScenarioAlreadyExistsError`, `WorldNotFoundError`, `InvalidScenarioError`) |

### Local mock adapters (`kalhas/adapters/mocks/`)

- **MockNexusAdapter** - standalone flow: submit scenario, validate, surface
  clarification questions, compile, fetch world/manifest. Uses only KALHAS
  contracts and application services.
- **MockLegionAdapter** - implements `LegionAdapter.request_strategies`:
  exactly five deterministic, versioned, domain-neutral candidates
  (`baseline`, `conservative`, `balanced`, `adaptive`, `diversified`) with
  declared policies, declared assumptions, and identical observation
  permissions. Policies are never executed.

### Phase 2 API routes

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/scenarios` | Register a scenario (201; 409 on duplicate; 422 on tenant mismatch) |
| POST | `/v1/scenarios/{scenario_id}/validate` | Semantic validation: report + clarification questions |
| POST | `/v1/scenarios/{scenario_id}/compile` | Compile to immutable world (200; 422 when semantically invalid) |
| GET | `/v1/worlds/{world_version_id}` | Fetch a compiled world |

All scenario/world endpoints require the `X-Tenant-ID` header; the body
`tenant_id` must match it. Errors use the single typed `ApiErrorResponse`
shape.

### Live demo (PowerShell, exact commands)

Start the server in one terminal:

```powershell
uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Then, in another PowerShell terminal:

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
$now   = (Get-Date).ToUniversalTime().ToString("o")
$later = (Get-Date).ToUniversalTime().AddDays(1).ToString("o")

$scenario = @{
  identifier     = "scenario-demo-1"
  tenant_id      = "tenant-demo"
  schema_version = "1.0.0"
  name           = "Demo scenario"
  description    = "Local standalone proof"
  created_at     = $now
  objectives     = @(@{ identifier = "obj-1"; description = "Maximize the primary metric"; direction = "maximize"; target = 100.0; weight = 1.0 })
  constraints    = @(@{ identifier = "c-1"; description = "Stay within declared bounds"; hard = $true })
  time_horizon   = @{ start = $now; end = $later; resolution = "step" }
  metrics        = @(@{ identifier = "m-1"; name = "Primary metric"; unit = "units"; aggregation = "mean" })
  assumptions    = @(@{ identifier = "a-1"; statement = "Conditions remain stable"; confidence = 0.9 })
  metadata       = @{}
} | ConvertTo-Json -Depth 10

# Register
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios" -Headers $headers -ContentType "application/json" -Body $scenario

# Validate
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/validate" -Headers $headers

# Compile
$compiled = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/compile" -Headers $headers
$compiled.version.identifier

# Fetch the compiled world
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/worlds/$($compiled.version.identifier)" -Headers $headers
```

You can also run the whole flow interactively at <http://127.0.0.1:8000/docs>.

> This is a **local, in-memory, standalone proof**: data lives in the
> process, mocks stand in for the real NEXUS and LEGION projects, and
> nothing leaves your machine.

## Phase 3: campaign preparation and run planning

### Behavior

- `prepare_campaign` verifies tenant-scoped scenario + compiled world,
  verifies the world was compiled from that scenario, calls only the
  `LegionAdapter` protocol (`MockLegionAdapter` in wiring), requires exactly
  five candidates with identical ordered observation permissions, stores a
  COMPILED `CampaignStatus`, and generates one ordered `RunPlan` per
  (strategy, seed) pair. Nothing is executed; the campaign is never marked
  COMPLETE.
- **The seed ensemble is the sole source of run multiplicity.** Planned run
  count is exactly: number of returned strategies × number of seeds in
  `seed_ensemble`.
- `start_campaign` performs only `COMPILED -> RUNNING`. A started campaign
  stays RUNNING with its planned runs available for inspection. No
  outcomes, evidence, briefs, or events are produced.
- The run planner is pure: no randomness, no wall-clock time. Each run's
  `input_hash` is SHA-256 over the world content hash, the strategy
  contract, the seed contract, and the runtime version; RunPlan identifiers
  are hash-derived from the canonical identity tuple (collision-safe).
- **Dependency inversion:** `campaign_service` depends on the
  `LegionAdapter` protocol only; concrete adapters appear exclusively in
  composition/wiring (app creation) and tests.
- **Tenant validation at every campaign input boundary:** the strategy
  request, every seed, and every returned strategy candidate must belong to
  the campaign tenant, enforced with typed domain errors (422 via the API).

### Phase 3 API routes

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/campaigns` | Prepare a campaign (201; 409 duplicate; 422 mismatches) |
| POST | `/v1/campaigns/{campaign_id}/start` | `COMPILED -> RUNNING` only (409 `invalid_state` otherwise) |
| GET | `/v1/campaigns/{campaign_id}` | Campaign + lifecycle status |
| GET | `/v1/campaigns/{campaign_id}/runs` | Ordered `RunPlan` list (planning manifests only) |

All campaign endpoints require `X-Tenant-ID` and enforce tenant isolation.

### Live demo (PowerShell, continues the Phase 2 sequence)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }

# Scenario -> validation -> compilation (from the Phase 2 demo)
# $compiled.version.identifier holds the world id.

$seed = @{ identifier = "seed-demo-1"; tenant_id = "tenant-demo"; schema_version = "1.0.0";
           algorithm = "deterministic"; seed_value = "demo-seed-value"; metadata = @{} }

$strategyRequest = @{
  identifier = "sr-demo-1"; tenant_id = "tenant-demo"; schema_version = "1.0.0"
  scenario_id = "scenario-demo-1"
  required_observations = @(@{ metric_id = "m-1"; description = "observe m-1"; required = $true })
  requested_at = $now
}

$campaignBody = @{
  campaign_id = "campaign-demo-1"; campaign_name = "Demo campaign"
  scenario_id = "scenario-demo-1"; world_version_id = $compiled.version.identifier
  strategy_request = $strategyRequest
  seed_ensemble = @($seed)
  created_at = $now
} | ConvertTo-Json -Depth 10

# Prepare the campaign (plans runs only)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/campaigns" -Headers $headers -ContentType "application/json" -Body $campaignBody

# Inspect planned runs (5 strategies x 1 seed = 5 RunPlans)
$runs = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1/runs" -Headers $headers
$runs.run_plans.Count
$runs.run_plans | Select-Object strategy_candidate_id, scenario_seed_id, input_hash | Format-Table

# Start the campaign (COMPILED -> RUNNING only)
$startBody = @{ changed_at = $now } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1/start" -Headers $headers -ContentType "application/json" -Body $startBody
```

> **This phase prepares deterministic runs but does not yet simulate them.**
> Starting a campaign only moves it to RUNNING; simulation and outcome
> generation arrive in a later phase.

## Phase 4: structural execution and exact replay

### Behavior

- **Execution inputs are recorded only**: immutable `WorldVersion`, the
  exact `StrategyCandidate` contracts persisted at preparation (Legion is
  never called again), the `ScenarioSeed` referenced by the `RunPlan`, the
  `RunPlan`, and the recorded runtime version. No Legion, NEXUS, provider,
  model, random generator, wall clock, filesystem, or network.
- **Structural event stream** (exactly three events per run, in order):
  `0 RUN_STARTED`, `1 STRATEGY_DECLARATION_RECORDED`,
  `2 RUN_COMPLETED`. Events carry run/campaign/world/strategy/seed
  references, deterministic simulation time (horizon start, start, end) and
  deterministic creation time (recorded run plan time). Payloads contain
  only structural facts (identifiers, runtime version, policy summary,
  lifecycle transition) - never outcomes, hidden reasoning, or executable
  policy content.
- **Event hashing**: SHA-256 (lowercase 64 hex) over the canonical ordered
  serialized event stream; recorded on the `RunStatus` at completion.
- **Execution state**: runs start PLANNED at preparation; each run goes
  PLANNED -> RUNNING -> COMPLETE only after all three events are stored in
  order; a campaign executes only from RUNNING; after every planned run
  completes, the campaign transitions RUNNING -> COMPLETE.
- **No fabrication**: no `OutcomeVector`, `EvidenceReference`,
  `DecisionBrief`, metrics, recommendation state, or fake probabilities.
  COMPLETE means structural execution completed, not that decision evidence
  was produced.
- **Exact replay**: regenerates the three events from recorded inputs,
  recomputes the hash, compares it to the stored expected hash, and returns
  a `ReplayManifest` (`replay_classification: "exact"`). Replay of a
  non-COMPLETE run or a hash mismatch fails with typed domain errors.

### Phase 4 API routes

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/campaigns/{campaign_id}/execute` | Execute all planned runs (campaign must be RUNNING; 409 `invalid_state` otherwise) |
| GET | `/v1/runs/{run_id}` | Run lifecycle status |
| GET | `/v1/runs/{run_id}/events` | Ordered structural event stream |
| GET | `/v1/runs/{run_id}/replay` | Exact replay; `ReplayManifest` when the regenerated hash matches |

All endpoints require `X-Tenant-ID`; foreign tenants get typed 404s.

### Live demo (PowerShell, continues the Phase 3 sequence)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
# Scenario -> compile -> prepare -> start (from the Phase 3 demo)

# Execute the campaign (structural only - no outcomes)
$executed = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1/execute" -Headers $headers
$executed.run_statuses | Select-Object run_id, state | Format-Table

# Campaign is now COMPLETE
(Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1" -Headers $headers).status.state

# Inspect the events of the first run (three ordered structural events)
$runId = $executed.run_statuses[0].run_id
$events = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/runs/$runId/events" -Headers $headers
$events.events | Select-Object sequence, kind, simulation_time | Format-Table

# Replay the run exactly (returns a ReplayManifest with expected_event_hash)
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/runs/$runId/replay" -Headers $headers
```

> **The structural runtime is a kernel proof only.** It proves deterministic
> execution, event ordering, persistence-in-memory, and replay mechanics.
> Domain mechanisms, outcomes, evidence, and recommendations remain future
> phases.

## Phase 5: run-input integrity verification

### Purpose

The input hash recorded at planning time (Phase 3) becomes an **actively
verified integrity boundary**: before any lifecycle change, event emission,
or replay regeneration, the verifier loads the currently recorded inputs and
proves they still match the run plan exactly. A mismatch means the recorded
state was changed, replaced, or tampered - execution and replay refuse to
proceed, and the mismatch is never repaired, overwritten, or silently
accepted.

### Preflight-before-execution guarantee

`execute_campaign` preflights **every** stored RunPlan in its deterministic
stored order **before the first run begins**. If any preflight fails the
failure is atomic: zero runs execute, no events are written, every RunStatus
stays PLANNED, and the campaign stays RUNNING. Per-run verification runs
again immediately before each transition as defense-in-depth. Replay
verifies inputs before any replay-hash comparison.

### New API route

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/runs/{run_id}/verify-inputs` | Deterministically verify a run's recorded inputs; records and returns the `RunInputIntegrityManifest` (200); 404 unknown/foreign run; 409 `integrity_error` for inconsistent or tampered inputs |

The endpoint is read-only with respect to lifecycle and events: it never
changes campaign or run state and never creates events, outcomes, evidence,
briefs, or recommendations.

### Live demo addition (PowerShell, before campaign execution)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
# Scenario -> compile -> prepare -> start (from the Phase 3 demo)

# Verify every planned run's recorded inputs before executing anything
$runs = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1/runs" -Headers $headers
foreach ($plan in $runs.run_plans) {
  $runId = "run-$($plan.identifier)"
  $manifest = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/runs/$runId/verify-inputs" -Headers $headers
  "verified $runId exact=$($manifest.verification_classification)"
}

# Only then execute
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/campaigns/campaign-demo-1/execute" -Headers $headers
```

> **Limitation:** this is process-local deterministic integrity checking -
> it proves the recorded inputs still match the run plan within this
> process. It is not cryptographic signing, cross-process persistence, or
> domain evidence.

## Phase 6: domain pack registry (declarative metadata only)

### Purpose

KALHAS must eventually support arbitrary domains without putting domain
logic in the kernel. This phase establishes only the deterministic,
declarative **registry**: a tenant-scoped store of `DomainPackManifest`
contracts describing what a future domain pack *is* - its identity
(logical `pack_id`, semantic `pack_version`), the KALHAS API versions it
supports (API version `1` is mandatory), and an ordered list of declared
capabilities with their ordered declared inputs and outputs.

**A registered manifest is metadata, not executable pack code.** It cannot
bind to a scenario or world, it is never loaded or imported, nothing
instantiates or executes it, and it has no effect on campaign preparation,
execution, replay, event streams, input hashes, or outcomes. The
`DomainPack` protocol in `kalhas/domain_packs/base.py` now exposes only the
manifest as its declarative identity - there is no executable surface to
conform to. No real domain pack ships; test-only generic fakes exist
solely inside tests.

### Registry behavior

- Manifests are addressed by `(tenant_id, manifest identifier)`; tenant
  ownership is derived from the `X-Tenant-ID` header (the draft carries no
  tenant field).
- Duplicate manifest identifiers per tenant are rejected with a typed 409
  `conflict`; manifests are immutable once registered (the contract is
  frozen and the store never overwrites).
- Unknown and foreign manifests are indistinguishable typed 404s - no data
  about another tenant's manifests is ever leaked.
- Listing is deterministic, sorted by manifest identifier.
- The **authoritative `content_hash`** is a lowercase 64-character SHA-256
  digest computed by the registry over the canonical serialized manifest
  content excluding `content_hash` itself. The registration draft has no
  hash input field, so a client can never choose the hash.
- Registration and retrieval never touch scenarios, worlds, campaigns, run
  statuses, events, replay manifests, or integrity manifests.

### Phase 6 API routes

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/domain-packs` | Register a declarative manifest (201 with the computed manifest; 409 typed conflict on duplicate; 422 for invalid drafts, including non-numeric `supported_api_versions` elements) |
| GET | `/v1/domain-packs` | List the tenant's manifests in deterministic identifier order (typed envelope) |
| GET | `/v1/domain-packs/{manifest_id}` | Fetch one tenant-owned manifest (typed 404 for unknown or foreign manifests) |

### Live demo (PowerShell, exact commands)

Start the server in one terminal:

```powershell
uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Then, in another PowerShell terminal:

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
$now = (Get-Date).ToUniversalTime().ToString("o")

$manifestBody = @{
  identifier             = "manifest-demo-1"
  pack_id                = "pack-demo-1"
  name                   = "Demo domain pack"
  pack_version           = "1.0.0"
  description            = "Declarative metadata only"
  supported_api_versions = @("1")
  capabilities           = @(@{
    identifier = "cap-demo-1"
    description = "Declared capability"
    input_ids  = @("input-demo-1")
    output_ids = @("output-demo-1")
    metadata   = @{}
  })
  schema_metadata        = @{ declarative = $true }
  created_at             = $now
  metadata               = @{}
} | ConvertTo-Json -Depth 10

# Register (returns the manifest with the computed content_hash)
$registered = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/domain-packs" -Headers $headers -ContentType "application/json" -Body $manifestBody
$registered.content_hash

# List the tenant's manifests (deterministic order)
(Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/domain-packs" -Headers $headers).manifests

# Fetch the registered manifest
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/domain-packs/manifest-demo-1" -Headers $headers
```

> **Limitation (Phase 6 historical context):** Phase 6 shipped no pack
> binding, loading, execution, or domain simulation - manifests were inert
> registry metadata. Binding to immutable world versions arrived in Phase 7
> and capability-input declarations in Phase 8; a registered manifest still
> affects no scenario, world, campaign, run, replay, or outcome until it is
> explicitly bound.

## Phase 7: immutable domain-pack bindings

### Binding lifecycle

1. **Register** a `DomainPackManifest` (Phase 6) - the immutable declarative
   identity of a future pack.
2. **Bind** it to a scenario: `POST /v1/scenarios/{scenario_id}/domain-pack-bindings`
   accepts only `manifest_id` and `bound_at`. The service verifies the
   tenant owns both the scenario and the registered manifest (typed 404
   otherwise) and snapshots the manifest's exact identity into a frozen
   `DomainPackBinding`: `pack_id`, `pack_version`, `manifest_content_hash`,
   and the ordered capability identifiers - all copied from the stored
   manifest, never from client input.
3. **Compile** the scenario: every subsequently compiled `WorldVersion`
   embeds the complete serialized binding snapshots (deterministic order by
   manifest identifier) under `world.domain_pack_bindings`, and the world's
   content hash changes with the binding set. `WorldManifest.state` carries
   `declared_domain_pack_binding_count`.
4. Bindings are immutable: duplicates raise typed 409 and never overwrite;
   there is no update, delete, replace, or unbind surface. A world compiled
   before a binding stays byte-identical forever.

**Manifest registration vs. world binding.** Registration declares what a
pack *is*; binding declares which registered packs apply to a scenario and
freezes that decision into every world compiled afterwards. A binding never
loads, instantiates, imports, or executes a pack and never interprets
capability schemas - the compiler embeds bindings as inert declarative data.

### Phase 7 API routes

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/scenarios/{scenario_id}/domain-pack-bindings` | Bind a registered manifest to the scenario (201 with the computed binding; 404 unknown/foreign scenario or manifest; 409 duplicate; 422 unknown request fields - the body accepts only `manifest_id` and `bound_at`) |
| GET | `/v1/scenarios/{scenario_id}/domain-pack-bindings` | List the scenario's bindings in deterministic manifest-id order (typed envelope; 404 unknown/foreign scenario) |

### Live demo (PowerShell, continues the Phase 6 sequence)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
$now = (Get-Date).ToUniversalTime().ToString("o")

# 1. Register the manifest (Phase 6)
# $manifestBody = ... (see the Phase 6 demo)
$manifest = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/domain-packs" -Headers $headers -ContentType "application/json" -Body $manifestBody

# 2. Register the scenario (Phase 2 demo) and bind the manifest to it
$bindBody = @{ manifest_id = $manifest.identifier; bound_at = $now } | ConvertTo-Json
$binding = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/domain-pack-bindings" -Headers $headers -ContentType "application/json" -Body $bindBody
$binding | Select-Object identifier, manifest_id, pack_id, pack_version, manifest_content_hash | Format-List
$binding.capability_ids   # ordered capabilities copied from the manifest

# 3. Compile the world - it now carries the immutable binding snapshot
$compiled = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/compile" -Headers $headers
$compiled.version.world.domain_pack_bindings | ConvertTo-Json -Depth 10

# The manifest's generic binding count
$compiled.manifest.state.declared_domain_pack_binding_count
```

> **Limitation:** bindings remain declarative metadata. They are snapshotted
> into compiled worlds and change the world content hash, but they do not
> yet execute domain mechanisms - no pack is loaded, instantiated, or run,
> and no capability schema is interpreted. Capability-input declarations
> arrived in Phase 8; pack execution and domain simulation remain later
> phases.

## Phase 8: immutable capability-input declarations

### Declaration lifecycle

1. **Register** a `DomainPackManifest` (Phase 6) - the immutable declarative
   identity of a future pack, whose capabilities declare ordered
   `input_ids` and `output_ids` (each unique by contract).
2. **Bind** it to a scenario (Phase 7) - the manifest becomes eligible for
   declarations on that scenario.
3. **Declare** capability inputs:
   `POST /v1/scenarios/{scenario_id}/domain-capability-declarations`
   accepts only `manifest_id`, `capability_id`, `input_values`, and
   `declared_at`. The service verifies the tenant owns the scenario and
   that the manifest is bound to that exact scenario (typed 404
   otherwise), verifies the stored binding snapshot exactly matches the
   registered manifest (safe typed 409 `integrity_error` on any
   inconsistency - including tenant, scenario, manifest, and binding
   identifier mismatches, with no raw hashes or internals exposed), and
   requires the `input_values` keys to match the capability's declared
   `input_ids` **exactly** - no missing keys, no extra keys; a capability
   with no `input_ids` accepts only an empty object (typed 422
   otherwise). The computed frozen `DomainCapabilityDeclaration` copies
   every identity field (`binding_id`, `pack_id`, `pack_version`,
   `manifest_content_hash`) from the stored immutable records - never
   from client input.
4. **Compile** the scenario: every subsequently compiled `WorldVersion`
   embeds the complete serialized declaration snapshots in deterministic
   order (manifest identifier, then capability identifier) under
   `world.domain_capability_declarations`, and the world's content hash
   changes with the declaration set. `WorldManifest.state` carries
   `declared_domain_capability_declaration_count` only when declarations
   exist.
5. Declarations are immutable: duplicates raise typed 409 and never
   overwrite; there is no update, delete, replace, or mutation surface. A
   world compiled before a declaration stays byte-identical forever.

**Manifests vs. bindings vs. declarations.** Registration declares what a
pack *is*; binding declares which registered packs apply to a scenario and
freezes that decision into every world compiled afterwards; a declaration
supplies the immutable declared input values for one capability of a bound
manifest. Declarations are inert facts/configuration for future domain
mechanisms - never executable content.

### Declaration identity and content-hash design

- **Identifier:** `declaration-` + the first 16 hex characters of SHA-256
  over the canonical JSON `{scenario_id, manifest_id, capability_id}` -
  deterministic, collision-safe, no wall clock.
- **Content hash:** lowercase 64-character SHA-256 over the canonical
  serialized declaration content **excluding `content_hash` itself** (the
  same pattern as manifests). The declaration API has no hash field; the
  authoritative hash is always computed.
- **No client-supplied identity:** the POST body accepts only the four
  fields above. Tenant, binding id, pack identity, manifest hash,
  declaration identifier, and declaration content hash are copied or
  computed from stored immutable records - client-supplied versions are
  rejected with typed 422.
- **Exact input-key matching:** `set(input_values.keys())` must equal
  `set(capability.input_ids)`; missing and extra keys are both typed 422.
  Duplicate `input_ids`/`output_ids` are rejected by the
  `DomainPackCapability` contract itself, so key matching is never
  ambiguous.
- **Deterministic compiler ordering:** the compiler canonicalizes
  snapshots itself - bindings sorted by `manifest_id`, declarations by
  `(manifest_id, capability_id)` - so caller-supplied tuple order never
  affects the content hash, the serialized world content, or the manifest
  counts. Already correctly ordered inputs sort to the identical order,
  so established hashes are unchanged.

### Phase 8 API routes

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/scenarios/{scenario_id}/domain-capability-declarations` | Declare immutable input values for one capability of a bound manifest (201 with the computed declaration; 404 unknown/foreign scenario, binding, or manifest; 422 unknown request fields or input-key mismatch / unknown capability; 409 duplicate or binding/manifest integrity error - the body accepts only `manifest_id`, `capability_id`, `input_values`, `declared_at`) |
| GET | `/v1/scenarios/{scenario_id}/domain-capability-declarations` | List the scenario's declarations in deterministic manifest-id then capability-id order (typed envelope; 404 unknown/foreign scenario) |

### Live demo (PowerShell, continues the Phase 7 sequence)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }
$now = (Get-Date).ToUniversalTime().ToString("o")

# 1. Register the manifest (Phase 6) - capability "cap-1" declares input_ids in-a, in-b
# $manifestBody = ... (see the Phase 6 demo)
$manifest = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/domain-packs" -Headers $headers -ContentType "application/json" -Body $manifestBody

# 2. Bind the manifest to the scenario (Phase 7)
$bindBody = @{ manifest_id = $manifest.identifier; bound_at = $now } | ConvertTo-Json
$binding = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/domain-pack-bindings" -Headers $headers -ContentType "application/json" -Body $bindBody

# 3. Declare the capability's input values (keys must exactly match input_ids)
$declareBody = @{
  manifest_id   = $manifest.identifier
  capability_id = "cap-1"
  input_values  = @{ "in-a" = "value-a"; "in-b" = 42 }
  declared_at   = $now
} | ConvertTo-Json -Depth 5
$declaration = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/domain-capability-declarations" -Headers $headers -ContentType "application/json" -Body $declareBody
$declaration | Select-Object identifier, manifest_id, capability_id, content_hash | Format-List
$declaration.input_values   # the exact declared key/value data

# 4. Compile the world - it now carries the immutable declaration snapshot
$compiled = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/scenarios/scenario-demo-1/compile" -Headers $headers
$compiled.version.world.domain_capability_declarations | ConvertTo-Json -Depth 10

# The manifest's generic declaration count
$compiled.manifest.state.declared_domain_capability_declaration_count
```

> **Limitation:** declarations remain **inert inputs**. They are snapshotted
> into compiled worlds and change the world content hash, but nothing
> interprets them beyond exact input-identifier matching: there is no
> schema execution, no capability invocation, no mechanisms, outputs,
> metrics, evidence, DecisionBriefs, recommendations, or domain-pack code
> execution. Pack execution and domain simulation remain later phases.

## Phase 9: operational activity feed

### Purpose and strict non-goals

The activity feed is a low-cost, append-only, tenant-scoped record of
**structural lifecycle facts already known to KALHAS**, intended as the
read surface for a future Encomm Colony UI. It records exactly one event
after each successful operation - scenario registration, world
compilation, manifest registration, manifest binding, capability-input
declaration, campaign preparation, campaign start, campaign execution,
run input verification, and run replay - and never after a rejected or
failed operation.

**Strict non-goals.** The feed is **not** a simulation event stream, not
evidence, not hidden reasoning, and not part of any `WorldVersion`,
`RunPlan`, input-integrity hash, event hash, or replay guarantee. It never
alters worlds, campaigns, runs, replay artifacts, integrity artifacts,
manifests, bindings, or declarations, and it never feeds any hash. This
phase adds no UI, no WebSockets/SSE, no polling loop, and no fake
live-agent state - retrieval is pull-based and read-only.

### Activity event design

- **`OperationalActivityKind`** - an enum of generic structural kinds
  (`scenario_registered`, `world_compiled`, `domain_pack_registered`,
  `domain_pack_bound`, `capability_inputs_declared`,
  `domain_state_model_declared` (Phase 11),
  `domain_state_transition_declared` (Phase 12), `campaign_prepared`,
  `campaign_started`, `campaign_executed`, `run_inputs_verified`,
  `run_replayed`).
- **`OperationalActivityEvent`** (24th top-level contract, frozen,
  `extra="forbid"`) - `VersionedContract` identity plus: a tenant-local
  strictly increasing `sequence` starting at zero (assigned by the store,
  identifier `activity-{sequence}`), the `kind`, a deterministic
  `occurred_at` derived from the already-recorded source contract
  (scenario `created_at`, world `created_at`, manifest `created_at`,
  binding `bound_at`, declaration `declared_at`, campaign status
  `changed_at`, integrity manifest `recorded_at`, replay manifest
  `created_at`) - never the wall clock - optional structural references
  (`scenario_id`, `world_version_id`, `campaign_id`, `run_id`,
  `manifest_id`, `binding_id`, `declaration_id`), and a strict
  JSON-compatible `payload`.
- **Payload safety.** Payloads carry only safe structural facts for the
  owning tenant: identifiers, contract/runtime/compiler versions, event
  counts, lifecycle states, and hashes already exposed by the source
  contracts. They never contain raw capability input values, policy
  rules, hidden reasoning, provider data, personal or company data,
  outcomes, evidence, recommendations, or executable content.
- **Storage.** The in-memory store appends events immutably, keyed by
  `(tenant_id, identifier)` with a per-tenant sequence counter. Events
  are immutable once appended; there is no update, delete, replace,
  clear, or unrestricted mutable surface. Retrieval returns events
  strictly after an optional `after_sequence` cursor, in ascending
  sequence order (append order within one tenant), bounded by an explicit
  `limit` with a safe maximum (100).

### Relationship to the Colony UI

Encomm Colony (Phase 10) is the local observability companion that reads
this endpoint: it issues only `GET /v1/operational-activity` with manual
pull refresh - deliberately no polling loop, no WebSockets/SSE streaming,
and no fake live-agent state. The feed exposes no simulation internals,
no evidence, no hidden reasoning, and no live-agent state - it is the
safe, bounded, read-only observability surface; everything else remains
out of scope.

### Phase 9 API route

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/v1/operational-activity` | One bounded page of the tenant's activity feed in ascending sequence order, strictly after `after_sequence` (`>= -1`, default = beginning of feed); `limit` 1-100 (default 20, max 100; out-of-range → typed 422). Returns the typed envelope `{events, next_after_sequence, latest_sequence}`; `latest_sequence` is -1 for a tenant with no activity; an empty feed returns an empty typed list. Read-only: never creates events. |

### Live demo (PowerShell)

```powershell
$headers = @{ "X-Tenant-ID" = "tenant-demo" }

# After any successful operations (register scenario, compile, bind, ...)
# the feed already contains one event per successful operation:
$feed = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/operational-activity" -Headers $headers
$feed.events | Select-Object sequence, kind, occurred_at | Format-Table
"latest=$($feed.latest_sequence) next=$($feed.next_after_sequence)"

# Bounded pagination: two events per page, walking the cursor
$page1 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/operational-activity?limit=2" -Headers $headers
$page2 = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/operational-activity?limit=2&after_sequence=$($page1.next_after_sequence)" -Headers $headers
$page1.events.sequence   # 0, 1
$page2.events.sequence   # 2, 3 (strictly after the cursor)

# A tenant with no activity gets an empty typed list
$empty = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/v1/operational-activity" -Headers @{ "X-Tenant-ID" = "tenant-fresh" }
$empty.events.Count      # 0
$empty.latest_sequence   # -1
```

> **Limitation:** this phase provides **pull-based read-only observability
> only**. Phase 10 adds the Encomm Colony UI, which reads this endpoint
> with manual pull refresh - there is still no WebSockets/SSE streaming
> transport and no polling loop or fake live-agent state. The feed records
> structural lifecycle facts only - it never interprets, executes, or
> exposes anything beyond what the source contracts already contain, and it
> never influences any simulation, replay, integrity, or world hash.

## Phase 10: Encomm Colony local observability UI

### Role and boundaries

**Encomm Colony** is an optional, local-only, dependency-free companion
presentation layer for KALHAS operational observability: a dark "mission
control" UI served by the same FastAPI application at `GET /colony/`
(plain static `index.html` / `styles.css` / `app.js` under
`kalhas/colony_ui/`; no React, Node, npm, build pipeline, CDN assets,
external fonts, images, canvas/WebGL, WebSockets/SSE, analytics, or
external services).

Colony is strictly read-only and truthful:

- it issues **only** `GET /v1/operational-activity` (same origin, no
  CORS, no credentials); it never calls any mutation endpoint and never
  alters worlds, campaigns, runs, replay, integrity, manifests,
  bindings, declarations, or activity state;
- it renders only actual typed `OperationalActivityEvent` data with
  `textContent` (never `innerHTML`): no fake agent activity, no fake
  terminal output, no invented running simulations, and no generated
  outcomes, evidence, recommendations, metrics, probabilities, or hidden
  reasoning; raw capability `input_values`, policy rules, and
  personal/company data are never representable in the feed and are
  defensively filtered by the UI as well;
- **NEXUS** is shown as an external boundary (not connected) and
  **LEGION** as a mock strategy boundary only; neither is presented as
  connected or active - they are not integrated;
- the feed is clearly labeled pull-based / manual refresh (it is not
  streaming live), and operational sequence order is distinguished from
  simulation/replay time.

### Opening Colony

Start the API and open <http://127.0.0.1:8000/colony/>. On first load the
UI does **not** request anything: enter a tenant identifier and press
**Load activity**. The initial request is
`after_sequence=-1&limit=100`; **Refresh** fetches only events newer than
the latest loaded sequence (cursor-based, `limit=100`). There is no
automatic polling (`setInterval`), long polling, WebSocket, SSE, or
background refresh - the feed changes only when you press the button.
Only the latest 100 rendered events are kept in memory.

### Layout

- header: title, "KALHAS operational observability" and "manual pull
  refresh" badges, tenant identifier input, Load activity / Refresh
  action, current feed status, and last received sequence;
- left system rail: KALHAS (connected only after a successful activity
  request), NEXUS (external boundary, not connected), LEGION (mock
  strategy boundary only) - no agent avatars, no claim that any agent is
  working;
- central mission floor: five CSS-only zones (Scenario Studio, World
  Forge, Domain Registry, Campaign Control, Integrity and Replay Vault)
  mapped to the activity kinds; each shows the latest observed event
  kind, source time, and structural references, and glows only when its
  kinds have been observed in the loaded feed;
- right event stream: events in descending visual order with their true
  tenant-local sequence numbers (sequence, kind, occurred_at, safe
  references, safe structural payload);
- bottom timeline bar: oldest/newest loaded sequence, API
  `latest_sequence`, whether older history exists beyond the loaded
  window, and a note that operational activity never affects simulation
  or replay hashes.

### UI routes and assets

| Method | Path | Description |
| --- | --- | --- |
| GET | `/colony/` | The Colony page (static HTML, no tenant header required) |
| GET | `/colony/styles.css` | Local stylesheet (no external fonts) |
| GET | `/colony/app.js` | Local client script (single GET-only activity read) |

The Colony routes are UI, not API surface: they are excluded from the
OpenAPI document (`include_in_schema=False`), require no tenant header,
never touch the store, and add no background work to API requests.

### Limitations

- no streaming and no live updates: manual pull refresh only;
- no real NEXUS or LEGION integration (external/mock-only labels);
- no real agent visualization (no avatars, no fake working agents);
- no outcomes, evidence, recommendations, metrics, probabilities, or
  hidden reasoning (the feed never carries them);
- the kernel is fully usable without Colony, and Colony changes no
  simulation, replay, integrity, or world hash.

## Phase 11: immutable declarative domain state models

### Role and strict non-goals

Phase 11 adds **immutable declarative state-schema registration and
world snapshotting**: a tenant declares, for a manifest already bound to
a scenario, which state fields exist for that domain pack - their
identifiers, descriptions, value kinds, initial values, and optional
allowed values. A state model is **data only**. It is the safe
foundation for a future generic simulation runtime.

**There is no mechanism engine yet.** Nothing in this phase executes
transitions, formulas, expressions, policies, mechanisms, simulations,
outcomes, metrics, evidence, recommendations, briefs, or real-world
actions. No callbacks, imports, executable expressions, provider
references, or evaluators can be expressed by the new contract types,
no domain-pack code is ever loaded or invoked, and the world compiler
never executes, evaluates, derives, or mutates any state field. A state
model merely defines what state fields would exist.

### Public contracts (25th top-level)

- **`StateValueKind`** - the declared value kind of one state field:
  `string`, `integer`, `number`, `boolean`, `json`.
- **`DomainStateFieldDefinition`** - one state field: `identifier`,
  `description`, `value_kind`, `initial_value`, optional
  `allowed_values` (default empty), optional `metadata`. Frozen,
  `extra="forbid"`.
- **`DomainStateModel`** - immutable `VersionedContract`: `scenario_id`,
  `binding_id`, `manifest_id`, `pack_id`, `pack_version`,
  `manifest_content_hash`, `state_model_id`, `state_fields`,
  `content_hash`, `declared_at`, optional `metadata`. Frozen,
  `extra="forbid"`.

### Strict validation

- Initial values and allowed values must **exactly match** their
  declared value kind; `integer`/`number` never silently accept
  booleans, and non-finite floats (NaN/Infinity) are rejected for every
  kind - including arbitrarily nested inside `json` values (pure
  recursive scan) and inside metadata.
- `allowed_values` (when supplied) must match the field type, be
  **canonically unique** (canonical JSON equality), and include
  `initial_value`.
- State field identifiers must be unique; `state_model_id` is
  non-empty and stable.
- The client can never supply an authoritative identity or hash:
  `binding_id`, `pack_id`, `pack_version`, `manifest_content_hash`,
  the model `identifier`, and `content_hash` are always copied from
  stored immutable records or computed by application logic - any
  attempt to send them is a typed 422.

### Identity, hashes, and canonical ordering

- State-model identifier: `state-model-{sha256(canonical_json({"scenario_id", "manifest_id", "state_model_id"}))[:16]}` -
  deterministic, collision-safe, never random or wall-clock.
- Content hash: SHA-256 of the canonical serialized model content
  **excluding `content_hash` itself**, using the repository's canonical
  JSON conventions.
- **State fields are canonicalized by identifier** at declaration time,
  so equivalent caller orderings produce the same canonical model,
  content hash, and world snapshot; the compiler re-canonicalizes field
  order and model order (`(manifest_id, state_model_id)`) defensively.
- `allowed_values` canonical uniqueness uses the same canonical JSON
  equality (e.g. `1` and `1.0` are distinct for `number` fields).

### Binding/manifest integrity verification

Before any state model is accepted, the service verifies the stored
binding and manifest are exactly the records implied by the request
(binding/manifest tenant, binding scenario and manifest identifiers,
deterministic binding identifier) **and** that the binding snapshot
exactly matches the registered manifest (pack id, pack version,
authoritative content hash, exact ordered capability identifier set).
Any mismatch raises a safe typed `integrity_error` (409) whose public
message never exposes raw hashes, internal details, or another tenant's
data (internal `reason` for diagnostics only).

### World snapshotting

Declared state models are snapshotted into compiled worlds under:

```
world["domain_state_models"]
```

- Models are ordered by `(manifest_id, state_model_id)`; state fields by
  identifier - the same semantic inputs in any caller/storage order
  compile to the same world content hash and snapshot representation.
- The snapshot key and the manifest count
  (`state["declared_domain_state_model_count"]`) are added **only when
  non-empty**, so state-model-free worlds compile byte-identically to
  Phase 10, and worlds compiled before Phase 11 remain unchanged.
- Adding a state model changes the newly compiled world hash. Campaign
  planning, input integrity, structural execution, replay, and event
  semantics are untouched - the snapshot flows through the immutable
  world/hash chain with no new runtime behavior.
- State models are immutable: no update, replacement, deletion, or
  overwrite endpoint exists; duplicates are rejected with a typed 409.

### Phase 11 API routes

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/scenarios/{scenario_id}/domain-state-models` | Declare an immutable state model for a bound manifest. Body accepts only `manifest_id`, `state_model_id`, `state_fields`, `declared_at`, optional `metadata` (`extra="forbid"`). 201 + computed model; 404 unknown/foreign scenario·binding·manifest; 409 duplicate; 409 `integrity_error` on corrupted binding/manifest snapshot; 422 invalid fields/values. |
| GET | `/v1/scenarios/{scenario_id}/domain-state-models` | List the scenario's state models in deterministic `(manifest_id, state_model_id)` order (404 unknown/foreign scenario). |

### Operational activity and Colony

- One new typed kind, **`domain_state_model_declared`**: a successful
  declaration appends exactly one structural event whose payload carries
  only safe identifiers and hashes (`state_model_id`, model
  `content_hash`, `state_field_count`) plus the scenario/manifest/binding
  references. State field initial values, allowed values, descriptions,
  and metadata are **never** recorded; rejected operations append
  nothing.
- Colony observes the new kind through its existing **Domain Registry**
  zone (it lights the zone with the same truthful rules as every other
  kind). No new request, timer, stream, or mutation capability was
  added: Colony remains strictly read-only, manual-pull, and
  same-origin.

> **Limitation:** Phase 11 is **declarative state-schema registration and
> world snapshotting only** - not a mechanism engine. There are no
> transitions, formulas, expressions, mechanism execution, simulation
> outcomes, evidence, recommendations, or real-world actions yet, and no
> domain pack code is ever loaded or executed. A future phase may add a
> generic simulation runtime on top of this data-only foundation.

## Phase 12: immutable declarative state-transition specifications

### Role and strict non-goals

Phase 12 adds **immutable, tenant-scoped transition-specification
registration and world snapshotting**: a tenant declares, for an
already-declared `DomainStateModel` of a manifest already bound to a
scenario, one *possible* state change as pure declarative data. A guard
is only a declarative equality condition over state fields and a target
is only a declarative intended state patch.

**There is still no transition engine.** Phase 12 specifies possible
transitions only. Nothing in this phase executes transitions, mutates
state, invokes domain packs, evaluates formulas or expressions, generates
outcomes, creates evidence, produces recommendations, or performs any
real-world action. No callbacks, scripts, expressions, formulas,
evaluators, code references, providers, imports, dynamic loading,
policies, LLM calls, or executable mechanisms can be expressed by the new
contract type, no domain-pack code is ever loaded or invoked, and the
world compiler never evaluates a guard or applies a target state patch.
There is no transition-execution endpoint, and the three structural run
events are unchanged.

### Public contracts (26th top-level)

- **`DomainStateTransition`** - immutable `VersionedContract`, frozen,
  `extra="forbid"`: `scenario_id`, `binding_id`, `manifest_id`,
  `pack_id`, `pack_version` (semver), `manifest_content_hash`,
  `state_model_id`, `state_model_content_hash`, `transition_id`
  (non-empty), `description`, `guard_values` (`dict[str, JsonValue]`,
  default empty), `target_values` (`dict[str, JsonValue]`, **must be
  non-empty**), `content_hash`, `declared_at`, optional `metadata`.

### Strict validation

- `transition_id` is non-empty and `target_values` must be non-empty
  (a transition with no intended target field is meaningless); an empty
  `guard_values` mapping is allowed (an unconditional transition).
- **Non-finite floats (NaN/Infinity) are rejected everywhere** - in
  guard values, target values, and metadata - including arbitrarily
  nested inside `json` values (pure recursive scan), at both the request
  boundary and the contract.
- Every guard/target key must **identify an existing field** of the
  referenced state model; every guard/target value must **exactly match
  that field's `StateValueKind`** (booleans are never accepted as
  integers or numbers, reusing the strict Phase 11 semantics); when the
  field declares `allowed_values`, the value must be **canonically
  among them** (canonical JSON equality, e.g. `1` vs `1.0` are distinct
  for `number` fields). Any violation is a typed 422 and nothing is
  stored.
- The client can never supply an authoritative identity or hash:
  `binding_id`, `pack_id`, `pack_version`, `manifest_content_hash`,
  `state_model_content_hash`, the transition `identifier`, and
  `content_hash` are always copied from stored immutable records or
  computed by application logic - any attempt to send them is a typed
  422.

### Identity, hashes, and canonical ordering

- Transition identifier:
  `transition-{sha256(canonical_json({"scenario_id", "manifest_id", "state_model_id", "transition_id"}))[:16]}` -
  deterministic, collision-safe, never random or wall-clock.
- Content hash: SHA-256 of the canonical serialized transition content
  **excluding `content_hash` itself**.
- **Guard/target mappings are canonicalized by field identifier** at
  declaration time, so equivalent caller key orderings produce the same
  canonical transition, content hash, stored representation, and world
  snapshot; the compiler re-canonicalizes mapping order and transition
  order (`(manifest_id, state_model_id, transition_id)`) defensively.

### Binding/manifest/state-model integrity verification

Before any transition is accepted, the service verifies the stored
binding and manifest are exactly the records implied by the request
(binding/manifest tenant, binding scenario and manifest identifiers,
deterministic binding identifier) **and** that the binding snapshot
exactly matches the registered manifest (pack id, pack version,
authoritative content hash, exact ordered capability identifier set).
It additionally verifies the **referenced state model**: copied
identity (tenant, scenario, manifest, binding relationship),
deterministic identifier, recomputed content hash, pack identity,
manifest content hash, and canonical field representation. Any mismatch
raises a safe typed `integrity_error` (409) whose public message never
exposes raw hashes, internal details, or another tenant's data (internal
`reason` for diagnostics only).

### World snapshotting

Verified transitions are snapshotted into compiled worlds under:

```
world["domain_state_transitions"]
```

- Transitions are ordered by `(manifest_id, state_model_id,
  transition_id)`; guard/target mappings by field identifier - the same
  semantic inputs in any caller/storage order compile to the same world
  content hash and snapshot representation.
- The snapshot key and the manifest count
  (`state["declared_domain_state_transition_count"]`) are added **only
  when non-empty**, so transition-free worlds compile byte-identically
  to Phase 11, and worlds compiled before Phase 12 remain unchanged.
- Adding a transition changes the newly compiled world hash. Campaign
  planning, input integrity, structural execution, replay, and event
  semantics are untouched - the snapshot flows through the immutable
  world/hash chain with no new runtime behavior.
- Transitions are immutable: no update, replacement, deletion, or
  overwrite endpoint exists; duplicates are rejected with a typed 409.
- The compiler never evaluates a guard or applies a target state patch.

### Phase 12 API routes

All endpoints require `X-Tenant-ID`; errors use the single typed
`ApiErrorResponse` shape.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/scenarios/{scenario_id}/domain-state-transitions` | Declare an immutable transition for a declared state model. Body accepts only `manifest_id`, `state_model_id`, `transition_id`, `description`, `guard_values`, `target_values`, `declared_at`, optional `metadata` (`extra="forbid"`). 201 + computed transition; 404 unknown/foreign scenario·binding·manifest·state-model; 409 duplicate; 409 `integrity_error` on corrupted binding/manifest/state-model records; 422 invalid fields/values. |
| GET | `/v1/scenarios/{scenario_id}/domain-state-transitions` | List the scenario's transitions in deterministic `(manifest_id, state_model_id, transition_id)` order (404 unknown/foreign scenario). |

### Operational activity and Colony

- One new typed kind, **`domain_state_transition_declared`**: a
  successful declaration appends exactly one structural event whose
  payload carries only safe identifiers and hashes (`state_model_id`,
  `transition_id`, `content_hash`, `guard_field_count`,
  `target_field_count`) plus the scenario/manifest/binding references.
  Descriptions, guard values, target values, metadata, and state-field
  values are **never** recorded; rejected operations append nothing.
- Colony observes the new kind through its existing **Domain Registry**
  zone (it lights the zone with the same truthful rules as every other
  kind). No new request, timer, stream, or mutation capability was
  added: Colony remains strictly read-only, manual-pull, and
  same-origin.

> **Limitation:** Phase 12 is **declarative transition-specification
> registration and world snapshotting only** - there is still no
> transition engine, state mutation, simulation mechanism, outcome
> generation, or decision engine. Guards are never evaluated and targets
> are never applied; a future phase may add a generic simulation runtime
> on top of this data-only foundation.

## Phase 13: pure deterministic state-transition evaluation kernel

### Role and strict non-goals

Phase 13 adds the **first evaluation semantics**: a focused,
domain-neutral, application-layer engine
(`kalhas/application/state_transition_engine.py`) that evaluates an
**explicitly supplied, ordered sequence** of already-declared
`DomainStateTransition` specifications against one immutable
`DomainStateModel` definition.

**It is a pure deterministic in-process kernel, not a simulator or
scheduler.** The engine:

- derives the initial state **only** from
  `DomainStateModel.state_fields[].initial_value`;
- evaluates transitions **only in the caller-provided order** - it never
  chooses, reorders, searches for, prioritizes, or loops transitions;
- evaluates a guard as **exact canonical equality** over its declared
  `guard_values` and, on a match, applies **only** the transition's
  declared `target_values` as a copy-on-write patch;
- on a guard mismatch, returns the unchanged state with an explicit
  deterministic `guard_not_satisfied` result;
- never mutates the input state, model, or transitions;
- validates the current state against the model's field definitions
  before every step and re-validates the applied target state afterwards
  (Phase 11 value-kind, allowed-values, and nested finite-JSON rules,
  including bool-as-int/number rejection and nested NaN/Infinity
  rejection);
- rejects unknown state keys, missing required keys, invalid values,
  foreign/mismatched transitions, malformed or mixed-model sequences,
  corrupted model/transition identities, and tampered copied ownership
  fields (tenant, scenario, binding, pack id, pack version) with typed
  application errors;
- validates every transition specification up front (non-empty targets,
  existing guard/target keys, exact value kinds, allowed values, no
  nested non-finite values) before any evaluation - an invalid
  specification can never be silently recorded as
  `guard_not_satisfied`;
- bounds an explicitly requested trajectory to a safe fixed maximum
  number of transition attempts (default 1000) with a typed error when
  exceeded - never a partial trajectory.

**Explicit non-goals.** The engine is **not exposed by HTTP** (no routes,
no OpenAPI surface), has **no store methods**, **no operational activity
events**, **no Colony behavior**, and makes **no world compiler
changes**. It is **not integrated with campaigns, runs, replay, NEXUS, or
LEGION**: it does not select transitions, create outcomes, evidence,
recommendations, briefs, probabilities, or hidden reasoning, does not
execute real-world actions, and never inspects strategy policies or
invokes domain packs. The three structural run events are unchanged, and
no automatic execution from compiled worlds exists - the caller must
explicitly provide the ordered transition sequence.

### Result records

Small immutable typed records (`TransitionAttempt`,
`TrajectoryEvaluation`) expose: the initial state and its canonical hash;
for every attempt - its sequence position, the transition identifier and
content hash, whether it was `applied` or `guard_not_satisfied`, and the
before/after state hashes; the final state and final-state hash; and a
deterministic `trace_hash` over the ordered attempt records. The
`initial_state`/`final_state` snapshots are **deep-frozen immutable**:
every nested mapping and array is read-only (assignment raises
`TypeError`/`AttributeError`), no snapshot shares mutable nested
references with the model's declared initial values, any transition's
guard/target values, or the engine's working state, and the snapshots
compare, hash, and validate identically to their plain JSON equivalents
(`derive_initial_state` deep-copies nested initial values so callers can
never mutate model-owned data through it). No human-language decision
explanations and no hidden reasoning are included, and these values are
never exposed through activity events or Colony.

### Hashing and determinism

All state snapshots and trace entries use the repository's canonical
JSON conventions (sorted keys, no insignificant whitespace). Equivalent
mappings with different insertion order produce identical state hashes,
trace hashes, and evaluation results.

> **Limitation:** Phase 13 is a **pure evaluation kernel only** - it
> computes what an explicitly supplied transition sequence *would* do to
> a declaratively defined state. There is still no automatic
> scheduling, no campaign/run/replay integration, no simulation
> mechanism, no outcome generation, and no decision engine.

## Phase 14: immutable store snapshot isolation + compiled-world content integrity

### Role and strict non-goals

Phase 14 closes two boundaries before the Phase 13 trajectory engine
ever connects to campaign execution: the in-memory store becomes a
deep-copy snapshot-isolation boundary, and a stored `WorldVersion` plus
its `WorldManifest` must provably still equal the world compiler's
deterministic output.

**Explicit non-goals.** This phase does **not** integrate the Phase 13
trajectory engine into campaigns or runs, does **not** add strategy
trajectory plans, does **not** add new HTTP routes or contracts, does
**not** add operational activity kinds or Colony behavior, does **not**
add external services or network calls, and adds **no domain-specific
logic**. No v1 contract or generated schema changed; every previously
compiled world is compiler output, so all valid-world content hashes
stay byte-identical.

### The store snapshot-isolation boundary

`kalhas/application/in_memory_store.py` is now a copy boundary for every
contract family it stores:

- **Every write stores a deep defensive copy.** Every `put_*` stores
  `_deep_copy_contract(value)`; tuple collections are deep-copied item
  by item (`tuple(_deep_copy_contract(x) for x in ...)`).
- **Every read returns a fresh deep copy.** Every `get_*`/`list_*`
  result is independently deep-copied before it leaves the store,
  including each item of listed tuples.
- **`append_operational_activity` stores and returns copies**, so
  callers can mutate the returned event or their original payload
  without ever touching stored activity.
- **Lifecycle replacement stays explicit**: `update_campaign_status` and
  `put_run_status` remain the only status-replacement paths (they
  deep-copy too).
- **Why frozen Pydantic models are not enough**: `frozen=True` only
  rejects attribute assignment on the model object itself. Nested
  `dict`/`list` values are still shared mutable references -
  `world.world["scenario"]["name"] = X`, `metadata[...] = Y`, and
  `payload[...] = Z` all succeed on a retrieved contract. The deep-copy
  boundary is what makes stored state actually immutable end-to-end:
  public retrieved objects cannot be used to corrupt storage, and
  test-only corruption must use deliberate private-dictionary injection
  (`store._worlds[(tenant, id)].world[...] = ...`), which is also the
  tamper vector every integrity test uses.

Pydantic contracts are copied with their native `model_copy(deep=True)`
(deep-copies nested dicts, lists, and tuple items); any other stored
object falls back to `copy.deepcopy`. The helper is generic over the
stored contract type and never exposes private mutable storage.

### The deterministic compiled-world integrity verifier

`kalhas/application/world_integrity.py` exposes
`verify_world_snapshot(world, manifest)`: pure, read-only, and
deterministic. It reuses the world compiler **exclusively** - its
private `_canonical_bindings`/`_canonical_declarations`/
`_canonical_state_models`/`_canonical_transitions` helpers for
canonical-order checks and `compile_world` for full recompilation. There
is no second world-hash algorithm. Checks run in a fixed order
(identity, provenance, structural shape, embedded parsing, canonical
order, recompilation equality):

1. **Identity**: world tenant matches manifest tenant; world identifier
   is `world-{content_hash[:16]}`; manifest identifier is
   `manifest-{content_hash[:16]}`; manifest `world_version_id` equals
   the world identifier; compiler version is the supported
   `COMPILER_VERSION`.
2. **Structural shape**: the world body contains all compiler-owned
   keys (`compiler_version`, `content_hash`, `scenario`) and no
   unexpected keys; the body's `content_hash` and `compiler_version`
   match the contract fields.
3. **Embedded scenario**: parses as a strict `ScenarioSpec`
   (malformed otherwise) and its tenant, identifier, and `created_at`
   match the world's provenance fields.
4. **Embedded snapshot families**: `domain_pack_bindings`,
   `domain_capability_declarations`, `domain_state_models`, and
   `domain_state_transitions` each parse strictly as their contracts
   (an absent key is an empty collection; a non-list or any
   validation failure is malformed).
5. **Canonical order**: each parsed family must equal its compiler
   canonical ordering (bindings by manifest, declarations by manifest
   then capability, state models by manifest then state-model id,
   transitions by manifest, state model, then transition id) - a
   reordered multi-element collection is rejected.
6. **Recompilation**: recompiling the parsed scenario and families with
   the recorded compiler version must reproduce the stored world
   **and** the stored manifest exactly (equality subsumes content hash,
   identifiers, byte-identical body, manifest counts/state/metadata). A
   semantically invalid scenario (one the compiler refuses) is rejected
   as such.

A world that fails any check is **rejected** - never repaired,
normalized, replaced, or silently accepted.

### Integration points

- **Campaign preparation**: `prepare_campaign` verifies the world after
  the world/scenario match, **before LEGION is called** and before any
  campaign/run state is written (a missing manifest is an integrity
  error, not a 404); a failed verification writes nothing.
- **Execution and replay input trust**: `verify_run_inputs` verifies
  right after the world identity checks and **before** input-hash
  recomputation, so structural execution's preflight (atomic: zero
  runs, zero events, all statuses untouched) and replay (no replay
  manifest after failed verification) inherit the gate.
- **NEXUS-facing reads**: `MockNexusAdapter.world()` and `.manifest()`
  verify before returning; `GET /v1/worlds/{id}` flows through
  `adapter.world`, so the read boundary is covered.

### `WorldSnapshotIntegrityError`

The typed error (409 `INTEGRITY_ERROR` at the API, no route changes)
carries a generic public message - "Stored world '...' failed integrity
verification and was rejected" - with no hashes, embedded state,
metadata, or raw values. The internal `reason` attribute names only the
violated rule (for diagnostics), never world contents, values, or
hashes. There is no repair, normalization, replacement, or silent
acceptance path anywhere in the verifier or its callers.

> **Limitation:** Phase 14 hardens **storage and world integrity** - it
> does not yet connect the Phase 13 trajectory engine to campaigns or
> runs, does not add trajectory plans, and changes no runtime
> semantics. Simulation with real domain mechanisms remains a future
> phase.

## Phase 15: immutable strategy-bound trajectory plans

### Role and strict non-goals

Phase 15 adds **immutable, strategy-bound trajectory-plan preparation
and recording**: LEGION *proposes* an explicitly ordered sequence of
already-declared transition references for one strategy and one state
model; KALHAS *verifies, binds, hashes, and stores* the resulting
`StrategyTrajectoryPlan`. Planning and recording only - **no trajectory
is evaluated or executed anywhere in this phase** (the planning service
never calls `evaluate_trajectory`).

**Explicit non-goals (Phase 15):** no campaign/run engine integration;
no structural runtime changes (the three run events are untouched); no
new run events; no `RunPlan`/`ReplayManifest` changes; no HTTP/OpenAPI
routes; no operational-activity kind; no Colony changes; no
outcomes/evidence/recommendations; no external LEGION implementation;
no network/providers; no domain-specific logic.

### Public contracts (28th top-level)

Two of the four new trajectory contract types are registered in
`PUBLIC_CONTRACTS` (26 -> **28**), all in `kalhas/contracts/v1/trajectory.py`
(frozen, `extra="forbid"`):

- **`StrategyTrajectoryTransitionReference`** - one authoritative
  reference to a declared transition: `sequence_position` (ge=0),
  `transition_identifier`, `transition_id`, `transition_content_hash`.
  No guard/target values, no state snapshots, no outcomes, no evidence,
  no executable behavior. **Repetitions are allowed** (a trajectory may
  intentionally attempt the same declared transition more than once).
- **`StrategyTrajectoryPlanRequest`** (`VersionedContract`) - the
  authoritative KALHAS-built request crossing the `LegionAdapter`
  boundary: campaign/scenario/world identifiers, `world_content_hash`,
  the exact stored `StrategyCandidate` snapshot with its full content
  hash, the exact `DomainStateModel` from the compiled world, and the
  non-empty canonical tuple of that model's available transitions.
  Its deterministic identifier is derived by KALHAS from the canonical
  campaign/world/strategy/state-model identity; LEGION never supplies it.
- **`StrategyTrajectoryPlanDraft`** (plain model) - the **untrusted**
  LEGION proposal: only `request_id` + `ordered_transition_identifiers`
  (min 1, max 1000). Cannot carry tenant identity, hashes, plan
  identifiers, state values, callbacks, expressions, code, providers, or
  metadata; the service re-validates it even when built through a
  validator-bypassing path.
- **`StrategyTrajectoryPlan`** (`VersionedContract`) - the immutable,
  authoritatively bound plan: campaign, world (id + content hash),
  strategy candidate (id + content hash), state model (manifest id +
  deterministic identifier + logical id + content hash), ordered
  transition references, `content_hash`, and `planned_at` (the recorded
  campaign `created_at` - never wall clock, never LEGION).

### Authoritative provenance

Plans are built **exclusively** from verified stored records: the
campaign (identity, seed ensemble, `created_at`), the `WorldVersion` +
`WorldManifest` after Phase 14 compiled-world verification, the state
models and transitions **embedded in the compiled world snapshot**
(never newer live-registry declarations), and the exact stored strategy
candidates in campaign order. Identifiers and hashes use only the
repository's canonical JSON + SHA-256 conventions: request/plan
identifiers share one canonical identity payload (distinct
`trajectory-request-`/`trajectory-plan-` prefixes, sha256[:16]); the
plan content hash covers the complete canonical plan excluding
`content_hash` itself, with tuple order and repetitions significant.

### The closed world catalog

Every embedded transition must map to **exactly one** embedded state
model by its exact ownership key (`manifest_id`, `state_model_id`,
`state_model_content_hash`) - nothing may remain unmatched or be
silently ignored. State-model and transition deterministic identifiers
must equal the canonical derivations; no state-model identifier,
ownership key, or transition identifier may be duplicated. Every
non-empty matched catalog passes the reusable Phase 13
`validate_transition_catalog` (pure and read-only). State models with
zero transitions remain valid and are ignored for planning. An orphan,
ambiguous, duplicate, or identity-invalid snapshot fails **before the
first LEGION call** with a safe typed `WorldSnapshotIntegrityError`
(generic public message; raw hashes, guards, targets, and state values
are never exposed). The **same closed construction** backs stored-plan
verification on read - no weaker raw-catalog path.

### Exact preflight and matrix

Before any LEGION trajectory request, preparation verifies the complete
stored run-plan matrix: the stored strategy candidate tuple must equal
`campaign.strategy_candidate_ids` exactly (same ids, same order), and
the stored run-plan tuple must equal the deterministically recomputed
`plan_runs` matrix (campaign, verified world content hash, exact stored
strategies, campaign seed ensemble, `campaign.created_at`, existing
runtime version) exactly - then every expected run passes
`verify_run_inputs`. No integrity manifest or lifecycle record is
written during preflight. A second preparation - including of an
already-prepared empty collection - raises
`TrajectoryPlansAlreadyPreparedError` **before** any new LEGION call and
never overwrites or repairs existing storage.

Plans are prepared for **every strategy candidate (campaign order) x
every transition-capable state model (compiled-world canonical order)**:
exactly one plan per pair, in that exact order. The LEGION-proposed
sequence is preserved exactly, including repetitions - KALHAS never
selects, sorts, deduplicates, or reorders. The draft's `request_id` must
equal the authoritative request identifier, and every proposed
identifier must exist in the model's available catalog.

### Boundary isolation

The service retains an authoritative request snapshot that **never
crosses the adapter boundary**; `legion.request_trajectory_plan`
receives a disposable deep copy. After the adapter returns, plan
construction reads only the authoritative request and the authoritative
stored records - a hostile adapter that mutates the boundary copy's
strategy candidate identifier, strategy metadata/policy, state-model
metadata, or transition guard/target values can never influence the
plans. Only the returned draft's ordered identifiers may influence the
selected sequence.

### Atomicity, storage, and verification

The complete matrix is built and validated **before the first plan is
stored**; any invalid draft or adapter failure stores zero plans. The
store keeps the Phase 14 deep-copy boundary: `put_*`/`get_*` deep-copy
the whole tuple, duplicate preparation is refused (`put` never
overwrites), and a **successfully prepared empty tuple is a stored value
distinguishable from "not prepared"** (`TrajectoryPlansNotFoundError`).
Stored plans are verified **as a complete collection**, never plan by
plan: exact matrix length and ordering, unique plan identifiers, unique
(strategy, state model) pairs, exact expected pair set, every
`planned_at` equal to the campaign `created_at`, and per-plan identity/
hash/reference checks against the closed world catalog. Stored plans are
strictly revalidated against their complete contract - including nested
reference types and the 1-1000 reference bound - before any identity,
hash, or matrix verification. A tampered
collection raises `StoredTrajectoryPlanIntegrityError` - never repaired,
sorted, normalized, replaced, or silently accepted.

> **Limitation:** Phase 15 proves the planning boundary only - no
> trajectory is evaluated or executed, and the plans are not yet
> consumed by campaigns or runs. Execution integration is a future
> phase (delivered by Phase 16).

## Phase 16: deterministic run trajectory execution and exact replay

### Role and runtime versioning

Phase 16 connects the approved Phase 15 trajectory plans to **run
execution and exact replay**. Execution semantics changed, so the
runtime is explicitly versioned in `kalhas/application/run_planner.py`:

- `LEGACY_STRUCTURAL_RUNTIME_VERSION = "1.0.0"` - the established
  structural-only runtime;
- `TRAJECTORY_RUNTIME_VERSION = "2.0.0"` - the trajectory-enabled
  runtime;
- `RUNTIME_VERSION = TRAJECTORY_RUNTIME_VERSION` - **new campaign/run
  planning defaults to 2.0.0**.

Runtime selection derives **only** from the recorded `RunPlan`/
`RunStatus`; no caller can override runtime behavior by supplying
synthetic objects (`execute_run(store, tenant_id, run_id)` and
`replay_run(store, tenant_id, run_id)` accept no plans, models,
transitions, or artifacts). Recorded "1.0.0" runs replay and execute
under the exact legacy structural-only behavior (same three events,
same event hash, PLANNED -> RUNNING -> COMPLETE, **no** trajectory
execution artifact); recorded "2.0.0" runs use the trajectory runtime;
any other recorded version fails with a typed
`UnsupportedRuntimeVersionError` before any lifecycle change or replay
regeneration. The Phase 15 planning preflight now rejects legacy or
unsupported campaign run matrices explicitly (typed error before any
LEGION call) instead of an obscure matrix mismatch.

### New public contracts (29th and 30th top-level)

All in `kalhas/contracts/v1/trajectory_execution.py` (frozen,
`extra="forbid"`); the two `VersionedContract` records are registered in
`PUBLIC_CONTRACTS` (28 -> **30**):

- **`RunTrajectoryAttemptRecord`** - one deterministic attempt:
  `sequence_position`, `transition_identifier`, `transition_id`,
  `transition_content_hash`, `outcome` (`"applied"` |
  `"guard_not_satisfied"`), `before_state_hash`, `after_state_hash`. No
  guard/target values, explanations, evidence, or policy content.
- **`RunStateTrajectoryResult`** - one evaluated state-model plan:
  plan identity + content hash, resolved model identity + content hash,
  fresh plain JSON `initial_state`/`final_state` with their hashes, the
  ordered attempts, the engine's `trace_hash`, and a self-covering
  `content_hash` (complete canonical result excluding `content_hash`).
- **`RunTrajectoryExecution`** (`VersionedContract`, deterministic
  identifier from the run identity and runtime version) - the immutable
  run-scoped artifact: run/campaign/plan identity, verified world and
  strategy identities with content hashes, `scenario_seed_id` (recorded
  provenance only), `runtime_version: "2.0.0"`, `input_hash`, exact
  ordered `trajectory_plan_set_hash`, ordered `results`, aggregate
  `content_hash`, and `executed_at` = the recorded RunPlan `created_at`
  (never wall clock). An empty results tuple is valid only for a
  verified world with no transition-capable state models.
- **`RunTrajectoryReplayManifest`** (`VersionedContract`) - exact-replay
  attestation binding the replay to the stored execution artifact, with
  `expected_execution_hash` == `recomputed_execution_hash` == the
  authoritative execution content hash, `replay_classification:
  "exact"`, and deterministic `replayed_at`.

Two new schema artifacts are generated: `RunTrajectoryExecution.schema.json`
and `RunTrajectoryReplayManifest.schema.json`. No existing v1 contract
field was modified.

### Pure execution builder

`kalhas/application/run_trajectory_runtime.py` is a pure, store-free
builder (`build_run_trajectory_execution`) receiving only already
verified authoritative records: `VerifiedRunInputs`, the exact
applicable plan tuple, and the exact closed compiled-world catalogs. It
requires runtime 2.0.0, requires every plan's strategy identity/hash to
match the verified run strategy, preserves the campaign plan/state-model
canonical order, resolves each plan's references only against its exact
verified world catalog, preserves repetitions and explicit ordering
exactly, calls `evaluate_trajectory` once per applicable plan, converts
the engine's deep-frozen snapshots to fresh detached plain JSON via the
engine's public `state_to_plain_json`, zips each engine attempt with its
authoritative plan reference (position, transition id, content hash
verified), builds and hashes each result, and builds/hashes the
aggregate artifact. Hash rules: `trajectory_plan_set_hash` (canonical
ordered collection digest), `state_trajectory_result_content_hash` and
`run_trajectory_execution_content_hash` (canonical dump minus the hash
field), `run_trajectory_execution_identifier` (sha256 of the canonical
run identity + runtime version). Nothing is mutated, and no wall clock,
randomness, network, provider, or domain pack is used.

### Run input resolution

`kalhas/application/run_trajectory_inputs.py::verify_run_trajectory_inputs`
calls `verify_run_inputs` first, then branches only on the recorded
runtime version. For 2.0.0 it loads the complete trajectory collection
through the Phase 15 service getter (full collection-level integrity),
builds the same closed compiled-world catalogs, and selects exactly the
plans whose `strategy_candidate_id` matches the run's strategy - one
plan per transition-capable state model in canonical order; missing,
additional, duplicated, reordered, foreign, or mismatched plans are
rejected. A transition-capable world without a prepared collection
raises `TrajectoryPlansRequiredError`; a world with no transition-capable
models resolves an empty tuple (absent collection or prepared empty
tuple both valid); 1.0.0 runs never consume plans; other versions are
rejected. The verifier is read-only and never evaluates anything.

### Execution and campaign atomicity

Legacy 1.0.0 execution is byte-identical to before. Trajectory 2.0.0
execution verifies and resolves all trajectory inputs, ensures no
execution artifact already exists, evaluates every applicable plan in
memory, and builds the complete `RunTrajectoryExecution` **before the
first lifecycle write**; only then are the integrity manifest recorded,
the run transitioned RUNNING, the same three structural events stored,
the artifact stored, and the run transitioned COMPLETE with the existing
structural event hash. On any failure the run stays PLANNED with zero
events and zero artifacts written and is not marked FAILED. The
structural event stream remains **exactly three events**
(RUN_STARTED, STRATEGY_DECLARATION_RECORDED, RUN_COMPLETED) with the
same ordering and the same independent structural event hash - no
transition attempts enter `RunEvent`, no raw states/guards/targets enter
event payloads, and the trajectory execution content hash never feeds
the event hash.

`execute_campaign` preflights **every** run atomically before the first
run: recorded inputs as today, plus each 2.0.0 run's trajectory
resolution, absence of any unexpected pre-existing artifact, and the
full in-memory artifact build. If any run fails preflight, zero runs
execute, zero events and artifacts are written, every status stays
PLANNED, and the campaign stays RUNNING. After a successful preflight
runs execute in the existing deterministic stored order, and the
per-run `execute_run` still independently reloads and verifies stored
inputs rather than accepting preflight objects.

### Exact replay

`replay_run` keeps its existing signature and return type
(`ReplayManifest`). Legacy 1.0.0 replay is unchanged and never requires
or creates a `RunTrajectoryReplayManifest`. Trajectory 2.0.0 replay
verifies the stored execution artifact (contract revalidation,
deterministic identifier, ownership, runtime, input hash, plan-set
hash, content hash), reloads and verifies the current immutable plan
collection, resolves the same closed catalogs, **independently
regenerates** the complete expected execution through the pure builder,
and requires exact full-object and content-hash equality with the
stored authoritative artifact - cached trajectory results are never
read as the regenerated output. Only after every structural and
trajectory check succeeds are the existing `ReplayManifest` and the
`RunTrajectoryReplayManifest` stored and the existing manifest
returned. On mismatch a typed `TrajectoryReplayMismatchError` (or the
typed execution-integrity error) is raised, neither replay manifest is
written, and no state values or hashes are exposed publicly. No LEGION,
NEXUS, domain pack, provider, network, randomness, or wall clock is
used during replay.

### Store isolation and integrity verification

The store gains deep-copy-isolated immutable collections for
`RunTrajectoryExecution` and `RunTrajectoryReplayManifest` (keyed by
tenant/run): strict contract revalidation on write (serializer-based
strict revalidation defeats `model_copy`/`model_construct` bypass),
deep defensive copies on write and read, identical rewrites accepted
idempotently, differing rewrites rejected (`AlreadyExistsError` /
`ConflictError`) and never overwriting the original, foreign-tenant
access indistinguishable from missing, and no update/delete/repair
surface. `kalhas/application/trajectory_integrity.py` provides strict
verification of stored records: contract revalidation, deterministic
identifiers, ownership, world/strategy/seed content hashes, input and
ordered plan-set hashes, result count and canonical model order,
per-result plan/model identity and hashes, initial/final state hashes,
attempt positions and authoritative transition references, trace and
result content hashes, the aggregate content hash, `executed_at`/
`replayed_at` provenance from the RunPlan `created_at`, and replay
expected/recomputed hashes equal to the authoritative execution hash.
Tampered records are never repaired, normalized, replaced, or silently
accepted.

### Seed, events, and non-goals

The recorded seed identity is carried into the execution artifact's
provenance (`scenario_seed_id`) and the execution identifier/input hash,
but the **current declarative transition kernel does not sample or use
the seed** - nothing pretends otherwise. No new `RunEvent` kinds, no
transition-attempt events, no outcomes/evidence/DecisionBriefs/
rankings/recommendations, no uncertainty sampling, no automatic
transition selection, no domain-pack execution, no real LEGION/NEXUS
integration, no HTTP/OpenAPI paths (the new typed errors surface
through the existing error envelope: 409 `conflict`/`integrity_error`,
404 for missing records), no operational-activity kinds, no Colony
changes, no external services/providers/network, no filesystem or
database, no new dependencies, and no domain-specific logic.

## Phase 17: verified trajectory artifact inspection (read-only)

Phase 17 exposes the immutable artifacts already produced and verified
by Phase 16 through a strictly read-only, tenant-scoped inspection
surface: an application query service plus two new v1 HTTP GET
endpoints. It introduces **no new simulation semantics** - retrieval
never executes, replays, evaluates, regenerates, repairs, or writes
anything, and no new contracts, runtime versions, event kinds, or
schema artifacts exist.

### Application query service

`kalhas/application/trajectory_query_service.py` is a focused, pure
application query service with two explicit functions:

- `get_verified_run_trajectory_execution(store, tenant_id, run_id)`
  -> `RunTrajectoryExecution`
- `get_verified_run_trajectory_replay_manifest(store, tenant_id, run_id)`
  -> `RunTrajectoryReplayManifest`

Both follow the same verified pipeline: `verify_run_trajectory_inputs`
loads and verifies the recorded run inputs and resolves the exact
applicable trajectory plans and closed compiled-world catalogs (branching
only on the recorded runtime version); the stored artifact is then
loaded through the store's deep-copy snapshot-isolation boundary and
verified with the **existing Phase 16 verifiers**
(`verify_run_trajectory_execution_record`, and for the manifest also
`verify_run_trajectory_replay_manifest_record` against the authoritative
execution and the exact ordered trajectory plan-set hash) - it is never
trusted by reference, never rebuilt, and never repaired. The replay-
manifest query loads and verifies the authoritative execution artifact
first. Only a completely verified artifact is returned.

The service is deterministic and read-only: no FastAPI dependency, no
LEGION/NEXUS calls or imports, no domain-pack loading or execution, no
wall clock, randomness, filesystem, database, provider, or network
access, and no mutation of stored or returned authoritative inputs. It
never calls `build_run_trajectory_execution`, `replay_run`,
`evaluate_trajectory`, or any store `put_*` surface, records no
operational activity, and changes no lifecycle state. Routes must use
this service rather than returning raw store values.

### Endpoints

| Method | Path | Response |
| --- | --- | --- |
| GET | `/v1/runs/{run_id}/trajectory-execution` | existing `RunTrajectoryExecution` contract |
| GET | `/v1/runs/{run_id}/trajectory-replay-manifest` | existing `RunTrajectoryReplayManifest` contract |

Both are X-Tenant-ID scoped like every other run endpoint. The response
models are the existing frozen contracts directly - no wrapper contracts
were introduced, `PUBLIC_CONTRACTS` remains exactly **30**, and no
schema artifact changed.

**Retrieval versus execution/replay.** `GET .../trajectory-execution`
returns the stored artifact only after complete verification; it never
rebuilds the execution from inputs. `GET .../trajectory-replay-manifest`
returns an already-created manifest only after complete verification; it
never triggers `replay_run`, regeneration, or any write. A run that has
not been replayed yet has no manifest and returns the typed 404 - the
GET never creates one.

**Tenant isolation.** X-Tenant-ID is authoritative. Foreign-tenant
access is indistinguishable from a missing artifact: the same typed 404
`ApiErrorResponse` is returned in both cases.

**Integrity verification before response.** Both endpoints fail through
the existing typed mappings: missing/legacy/not-yet-created artifacts
return the typed 404 `not_found`; corrupted or tampered execution
records return the existing safe 409 `integrity_error`; corrupted replay
manifests preserve the existing typed 409 `conflict` mapping. Public
error responses never expose internal verification reasons, raw hashes,
state values, transition guards/targets, strategy policy content,
validator diagnostics, or any other tenant's data. Request IDs and the
single `ApiErrorResponse` envelope are unchanged.

**Intentional exposure.** The `RunTrajectoryExecution` response exposes
the contract-declared `initial_state`/`final_state` snapshots (and their
hashes) exactly as the frozen contract declares them. It never adds
guards, target values, strategy policy content, hidden reasoning,
evidence, or recommendations - the contract simply has no such fields.

### Behavior matrix

| Recorded state | Execution GET | Replay-manifest GET |
| --- | --- | --- |
| Legacy 1.0.0 run (no artifact ever) | 404 typed not-found | 404 typed not-found |
| 2.0.0 run, not executed | 404 typed not-found | 404 typed not-found |
| 2.0.0 run executed, not replayed | 200 verified execution | 404 typed not-found (nothing created) |
| 2.0.0 run executed and replayed | 200 verified execution | 200 verified manifest |
| Unknown run / foreign tenant | 404 typed not-found | 404 typed not-found |
| Unsupported recorded runtime version | 409 typed conflict | 409 typed conflict |
| Corrupted/tampered execution record | 409 `integrity_error` | 409 `integrity_error` (execution verified first) |
| Corrupted/tampered replay manifest | - | 409 `conflict` |

### Explicit non-goals

No trajectory execution or replay side effects on either GET; no new
runtime versions; no new `RunEvent` kinds; no transition attempts inside
`RunEvent`; no changes to the three structural events or their event
hash; no `OutcomeVector`/`EvidenceReference`/`DecisionBrief` production;
no rankings, scores, recommendations, or probability claims; no
uncertainty sampling or seed consumption; no automatic transition
selection; no domain-specific vocabulary or logic; no domain-pack
execution; no real NEXUS/LEGION integration; no operational-activity
kinds or writes; no Colony changes; no external services, providers,
network, database, filesystem, or dependencies; no changes to AGENTS.md,
global configuration, or unrelated skills; no commits or pushes.

### Status

All five gates green - full suite **1226 passed / 1 skipped / 1
warning** (the pre-existing Starlette/httpx deprecation warning only);
mypy clean; ruff check clean; `ruff format --check` clean; schema export
`--check` synced (no contract changes; `PUBLIC_CONTRACTS` remains 30).
New Phase 17 suites: `tests/test_trajectory_query_service.py` (21),
`tests/test_api_phase17.py` (17), and `tests/test_phase17_boundaries.py`
(10) - **48 tests** total. The complete pre-Phase-17 suite also remains
green as part of the full 1226-test regression run.

## Phase 18: deterministic campaign trajectory matrix

Phase 18 assembles every verified Phase 16 `RunTrajectoryExecution` of
one completed runtime-2.0.0 campaign into the exact authoritative
**strategy x shared-seed run matrix** - one deterministic, tenant-scoped,
read-only structural comparison artifact. It introduces **no simulation
semantics**: the matrix never executes, replays, evaluates, regenerates,
repairs, or writes anything, and it proves only that every strategy was
executed under the campaign's identical ordered seed conditions while
providing verified references and integrity hashes for every run.

**This is structural comparison provenance, not performance
evaluation.** The matrix never ranks strategies, never calculates
scores, never interprets state values, and never produces outcomes,
evidence, or recommendations - no claim that one strategy is better is
expressible in the contract.

### Contracts

`kalhas/contracts/v1/campaign_trajectory.py` adds:

- `CampaignTrajectoryRunCell` - one run of the matrix (frozen, strict,
  **not** registered in `PUBLIC_CONTRACTS`): sequence/strategy/seed
  positions; run and run-plan identity; strategy and seed identities;
  run input hash; the verified trajectory-execution artifact reference
  (deterministic identifier and content hash) with its exact ordered
  plan-set hash; and the ordered `result_content_hashes`, preserved
  exactly. The cell carries **references and integrity hashes only** -
  no state snapshots, no transition guards or target values, no strategy
  policy content, no outcome values, no evidence, no ranking or score,
  and no explanations or hidden reasoning.
- `CampaignTrajectoryMatrix` - the immutable aggregate (frozen, strict,
  registered, `PUBLIC_CONTRACTS` 30 -> **31**): campaign/scenario/world
  identity and world content hash; `runtime_version` literal `2.0.0`;
  `comparison_mode` literal `identical_conditions`; the ordered strategy
  candidate ids and ordered shared seed ids; the complete cell tuple in
  the exact RunPlan order; the self-covering `content_hash`; and the
  deterministic `assembled_at`. The contract enforces the structural
  shape (non-empty collections, unique identities, complete Cartesian
  product, position-bound cells, exact RunPlan order); authoritative
  identity/hash verification stays in the application layer.

**Identifier rule:** `trajectory-matrix-{sha256(canonical_json({
campaign_id, world_version_id, runtime_version}))[:16]}` - deterministic
from campaign identity, world identity, and runtime version, with a
distinct readable prefix.

**Content-hash rule:** `content_hash` is SHA-256 over the complete
canonical matrix serialization (sorted keys, no whitespace, repository
canonical JSON) excluding `content_hash` itself; identical matrices
hash byte-identically.

**assembled_at rule:** always the recorded campaign `created_at` -
never the wall clock.

### Exact matrix ordering

Cells follow the exact authoritative RunPlan order: **strategy-major,
seed-minor** (`plan_runs` order - strategies in campaign candidate
order, seeds in campaign ensemble order). Every strategy appears once
for every seed; every strategy receives the identical ordered seed
identifiers; cells bind to their exact stored `RunPlan` and verified
`RunTrajectoryExecution`.

### Fair identical-condition invariants (structural, not assumed)

- `comparison_mode` is exactly `identical_conditions` (a `Literal`
  const - inexpressible otherwise).
- Strategy order comes from the authoritative campaign
  (`campaign.strategy_candidate_ids` must equal the stored candidate
  tuple exactly).
- Seed order comes from the campaign's shared seed ensemble
  (`campaign.seed_ensemble`).
- The matrix is the complete Cartesian product - missing, additional,
  duplicated, reordered, or foreign runs are all rejected; there is no
  sorting, normalization, repair, replacement, or silent omission.
- Matrix construction is atomic: one invalid run means no matrix
  response.
- Strategy performance is never inferred from structural values
  (applied/guard-not-satisfied counts, state hashes, result counts, or
  any other structural value).

### Pure matrix builder

`kalhas/application/campaign_trajectory_runtime.py` provides the pure,
store-free `build_campaign_trajectory_matrix(...)`. It receives
**already verified authoritative records only** (campaign, verified
compiled world, stored strategy candidates, campaign seed ensemble,
stored run plans, verified executions) and: requires runtime 2.0.0
(legacy/unsupported raises `UnsupportedRuntimeVersionError`); preserves
the exact campaign strategy order, shared seed order, and stored RunPlan
order; requires the exact complete strategy x seed matrix; rejects
missing/additional/duplicated/reordered/foreign runs; binds every cell
to its exact RunPlan and verified execution; verifies all
run/campaign/world/strategy/seed/input identities (including recomputed
input hashes via the existing `run_input_hash`); preserves ordered
result content hashes exactly; derives the deterministic identifier and
`assembled_at`; and calculates the canonical content hash. It mutates no
inputs, performs no store access, and performs no execution, replay,
transition evaluation, or outcome calculation. It reuses the existing
public helpers (`run_input_hash`, `run_identifier`,
`strategy_candidate_content_hash`, canonical JSON/SHA-256) - the
authoritative run-plan matrix check previously private
(`_preflight_run_plan_matrix`) was extracted to the public
`preflight_run_plan_matrix` with the private name kept as an alias and
behavior unchanged.

### Campaign query service and endpoint

`kalhas/application/campaign_trajectory_query_service.py` provides
`get_verified_campaign_trajectory_matrix(*, store, tenant_id,
campaign_id) -> CampaignTrajectoryMatrix`: load the tenant-scoped
campaign and status; require exactly COMPLETE; load and verify the
compiled world snapshot; load the exact authoritative strategy
candidates, shared seed ensemble, and ordered RunPlan matrix (existing
`preflight_run_plan_matrix`); require every recorded run to use runtime
2.0.0; verify every run's execution through the existing Phase 17
verified execution query path; verify the complete collection before
returning anything; build the matrix in memory through the pure builder;
and return it directly **without storing it**. A missing or corrupt
execution inside a COMPLETE 2.0.0 campaign is a campaign matrix
integrity failure - **a partial matrix is never returned**.

`GET /v1/campaigns/{campaign_id}/trajectory-matrix` returns the
`CampaignTrajectoryMatrix` directly (no response wrapper). X-Tenant-ID
is authoritative. Error behavior: unknown or foreign campaign - typed
404 `not_found`; campaign not COMPLETE - typed 409 `invalid_state`
(new `CampaignNotCompleteError`); legacy or unsupported runtime - typed
409 `conflict`; missing, inconsistent, or corrupted matrix inputs or
executions - typed 409 `integrity_error` (new
`CampaignTrajectoryMatrixIntegrityError`). Public error responses never
expose internal reasons, hashes from rejected data, state values,
guards, targets, policy content, Pydantic diagnostics, or another
tenant's data; request IDs and the single `ApiErrorResponse` envelope
are unchanged. The GET performs no write and creates no
operational-activity event.

### Behavior matrix

| Recorded state | Trajectory-matrix GET |
| --- | --- |
| COMPLETE 2.0.0 campaign | 200 exact `CampaignTrajectoryMatrix` |
| Unknown campaign / foreign tenant | 404 typed not-found |
| Campaign not COMPLETE | 409 `invalid_state` |
| Legacy 1.0.0 or unsupported recorded runtime | 409 `conflict` |
| Missing/corrupted execution or matrix inputs in COMPLETE campaign | 409 `integrity_error` (nothing partial) |

### Explicit non-goals

No rankings, winners, losers, recommendations, scores, weights, or
comparisons of strategy quality; no `OutcomeVector`/`EvidenceReference`/
`DecisionBrief` production; no metric extraction or aggregation; no
probability or distribution claims; no state interpretation; no
uncertainty sampling or seed consumption; no automatic transition
selection; no new runtime versions; no new `RunEvent` kinds; no changes
to the three structural events or their event hash; no execution/replay
side effects; no state snapshots in the matrix contracts; no transition
guards/targets or policy content; no domain-specific vocabulary or
logic; no domain-pack loading/execution; no real NEXUS/LEGION
integration; no operational-activity kinds or writes; no Colony
changes; no external providers, network, filesystem/database
persistence, or dependencies; no changes to AGENTS.md, global
configuration, or unrelated skills; no commits or pushes. Phase 19 has
not been started.

### Status

All five gates green - full suite **1347 passed / 1 skipped / 1
warning** (the pre-existing Starlette/httpx deprecation warning only);
mypy clean (125 files); ruff check clean; `ruff format --check` clean
(134 files); schema export `--check` synced (new artifact
`CampaignTrajectoryMatrix.schema.json`; `PUBLIC_CONTRACTS` exactly 31).
New Phase 18 suites: `tests/test_campaign_trajectory_contracts.py`
(31), `tests/test_campaign_trajectory_runtime.py` (29),
`tests/test_campaign_trajectory_query_service.py` (28),
`tests/test_api_phase18.py` (15), and `tests/test_phase18_boundaries.py`
(14) - **117 tests** (plus 4 new parametrized contract cases in
`tests/test_contracts.py`). The complete pre-Phase-18 suite remains
green as part of the full 1347-test regression run; the two existing
contract-count assertions were updated 30 -> 31 (Phase 16/17 suites,
expected count bump only).

## Phase 19: immutable state-to-metric observation bindings (declaration only)

Phase 19 adds the immutable, declarative, tenant-scoped
**state-to-metric observation binding**: a `DomainMetricObservationBinding`
connects exactly one metric of a stored `ScenarioSpec` to exactly one
**numeric** field of an existing scenario-bound `DomainStateModel`. The
binding declares that a *future* phase may observe the field's final
trajectory state as the metric's raw observation. Phase 19 is
**declaration, storage, world snapshotting, integrity verification, and
API management only** — it never inspects a `RunTrajectoryExecution`,
extracts a metric value, evaluates a trajectory, calculates an outcome,
aggregates observations, produces evidence, ranks strategies, or
generates recommendations.

- **Contract** (`kalhas/contracts/v1/metric_observation.py`,
  `DomainMetricObservationBinding`, 32nd top-level contract; frozen,
  `extra="forbid"`): `scenario_id`, `binding_id`, `manifest_id`,
  `pack_id`, `pack_version` (semver), `manifest_content_hash`,
  `metric_id`, `state_model_identifier` (deterministic model identifier),
  `state_model_id`, `state_model_content_hash`, `state_field_id`,
  `state_field_value_kind` (literal `"integer"` | `"number"` only),
  `observation_point` (literal `"final_state"`, default), `content_hash`,
  `declared_at` (timezone-aware), `metadata`. The contract carries **no**
  formulas, expressions, callbacks, transformations, scaling factors,
  aggregation implementations, executable or provider references,
  observed values, state snapshots, outcomes, evidence, scores, or
  recommendations. New schema artifact
  `schemas/v1/DomainMetricObservationBinding.schema.json`;
  `PUBLIC_CONTRACTS` 31 -> **32**; no existing v1 contract field changed.
- **Authoritative provenance**: every identity field is copied
  exclusively from stored immutable records (scenario, binding, manifest,
  state model) — the API draft
  `DomainMetricObservationDeclarationRequest` accepts only
  `manifest_id`, `state_model_id`, `metric_id`, `state_field_id`,
  `declared_at`, `metadata`. The service requires `metric_id` to identify
  exactly one scenario metric, verifies the binding snapshot against the
  registered manifest and the state model's copied identity,
  deterministic identifier, content hash, canonical fields, and binding
  relationship (safe typed 409 `integrity_error` on inconsistency),
  resolves `state_field_id` against the exact model, and requires the
  field's `StateValueKind` to be numeric — `string`, `boolean`, and
  `json` fields are rejected (typed 422).
- **Deterministic identity**: binding identifier =
  `observation-{sha256(canonical_json({tenant_id, scenario_id, metric_id,
  manifest_id, state_model_id, state_field_id, observation_point}))[:16]}`;
  `content_hash` = SHA-256 of the canonical serialized binding excluding
  `content_hash`. Metadata insertion order never affects the identifier
  or content hash.
- **One binding per scenario metric (MVP)**: a second declaration for
  the same tenant + scenario + metric — even pointing to a different
  model or field — is rejected with a typed 409 `conflict` before any
  write and never overwrites the original.
- **Store** (`InMemoryScenarioStore`): immutable tenant-scoped
  collection keyed `(tenant_id, scenario_id, metric_id)`; deep defensive
  copies on every write/read/list; strict complete contract revalidation
  before storage (validator-bypassed contracts and non-finite nested
  metadata rejected); duplicate and incorrect-ownership-key rejection;
  deterministic listing by `metric_id`; foreign-tenant access
  indistinguishable from missing; no update/delete/repair surface;
  rejected writes leave storage byte-identical.
- **API** (all X-Tenant-ID scoped): `POST
  /v1/scenarios/{scenario_id}/metric-observations` (201, strict request
  body, no caller-controlled authoritative identities or hashes; 404
  missing/foreign scenario·binding·model; 422 unknown metric/field or
  non-numeric field; 409 duplicate `conflict` or integrity `integrity_error`)
  and `GET /v1/scenarios/{scenario_id}/metric-observations` (typed
  envelope, deterministic metric-id order, tenant-isolated). No update or
  delete endpoints; declarations and listings create **no**
  operational-activity events and no Colony changes.
- **World compiler**: every subsequently compiled `WorldVersion` carries
  the scenario's observation bindings under the compiler-owned
  `domain_metric_observations` key — only when non-empty, canonicalized
  by `metric_id` inside the compiler, participating in the content hash.
  Observation-free worlds compile byte-identically to the pre-Phase-19
  compiler; caller/store insertion order never affects the world
  identifier, content hash, manifest, or embedded ordering; the compiler
  never interprets or extracts a metric value and never reads trajectory
  executions. `WorldManifest.state["declared_domain_metric_observation_count"]`
  appears only when bindings are non-empty. Declarations added after
  compilation affect only subsequently compiled worlds; already compiled
  worlds remain immutable.
- **World integrity**: `verify_world_snapshot` recognizes the new key,
  strictly parses each embedded binding through
  `DomainMetricObservationBinding` (foreign objects and
  validator-bypassed/malformed snapshots rejected), requires canonical
  metric-id ordering, rejects duplicate metric bindings, and verifies
  tenant/scenario ownership, metric existence against the embedded
  scenario, state-model existence and identity/content hash, state-field
  existence, copied numeric value-kind match, and pack
  binding/manifest identity against the compiled catalog — then
  recompiles from the exact parsed snapshots and requires exact
  `WorldVersion` and `WorldManifest` equality. Corrupted storage is never
  repaired, normalized, reordered, or replaced. `VerifiedWorldCatalog`
  exposes the canonical observation-binding tuple
  (`domain_metric_observations`) and stays immutable and detached.
- **Non-goals**: no metric-observation extraction, no `initial_state`/
  `final_state` reads, no metric values, no `MetricOutcome`/`OutcomeVector`
  or `EvidenceReference`/`DecisionBrief` production, no aggregation,
  normalization, formulas, transformations, weights, scoring, ranking,
  recommendations, uncertainty sampling, seed consumption, automatic
  transition selection, new runtime versions, new `RunEvent` kinds,
  domain-specific vocabulary, domain-pack execution, real
  NEXUS/LEGION integration, external services/providers/network,
  filesystem/database persistence, dependencies, operational-activity
  kinds or writes, Colony changes, AGENTS.md/global-config/skill
  changes, commits or pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan
  generation, campaign lifecycle, trajectory-plan preparation, transition
  evaluation, run execution, replay, Phase 17 artifact queries, the
  Phase 18 campaign trajectory matrix, `RunEvent` and its three
  structural kinds, and event/execution/matrix hashes are unchanged (new
  world content hashes are expected deterministic provenance for newly
  compiled worlds only). **Phase 20 has not started.**

## Phase 20: deterministic run metric-observation extraction

Phase 20 bridges the Phase 19 declaration to immutable raw observations:

```
DomainMetricObservationBinding
    -> verified RunTrajectoryExecution.final_state
    -> immutable raw metric observations
```

Phase 19 declared *where a value may be observed*; Phase 20 **explicitly
extracts the raw numeric value** of every binding from the **completely
verified final trajectory state** of a runtime 2.0.0 run and records it
as an immutable, deterministic, provenance-bound artifact. Extraction
is **explicit and post-execution only** — it is never triggered
automatically during campaign execution.

- **Contracts** (`kalhas/contracts/v1/run_metric_observation.py`):
  - `RunMetricObservationValue` (frozen, `extra="forbid"`, nested): one
    extracted raw observation — `metric_id`, `metric_unit` (copied from
    the authoritative embedded `ScenarioSpec` when declared), the
    binding identifier and content hash, manifest and state-model
    identity/content hashes, `state_field_id`,
    `state_field_value_kind` (literal `"integer"` | `"number"`),
    `observation_point` (literal `"final_state"`), the
    trajectory-plan identity/content hash and the exact result content
    hash required to locate the authoritative final state, and the
    exact finite `raw_value`. Numeric validation is strict: booleans
    are never accepted as integers or numbers, integer bindings require
    an actual integer, number bindings accept an actual finite int or
    float, NaN/Infinity are rejected, no numeric coercion ever happens,
    and the extracted value is preserved exactly (no normalization,
    scaling, transformation, or unit conversion).
  - `RunMetricObservationSet` (frozen `VersionedContract`, **33rd
    top-level contract**; `PUBLIC_CONTRACTS` 32 -> **33**; no existing
    v1 contract field changed): the complete observation collection of
    one run — run/campaign/plan/scenario identity, world and strategy
    identities with content hashes, seed identity, `runtime_version`
    (literal `"2.0.0"`), run input hash, the verified
    `RunTrajectoryExecution` identifier and content hash, the exact
    observation tuple canonicalized by `metric_id`, the deterministic
    `content_hash` over the complete canonical payload excluding
    `content_hash`, and `observed_at` from the authoritative
    execution's `executed_at` — never wall-clock time. New schema
    artifact `schemas/v1/RunMetricObservationSet.schema.json`.
- **Deterministic identity**: set identifier =
  `metric-observation-set-{sha256(canonical_json({run_id,
  runtime_version}))[:16]}`; `content_hash` = SHA-256 of the canonical
  serialized set excluding `content_hash`; observations are ordered by
  strictly increasing `metric_id` (duplicate or reordered metrics are
  rejected by the contract); `observed_at` = the verified execution's
  `executed_at` (the recorded RunPlan creation time).
- **Extraction pipeline** (`kalhas/application/run_metric_observation_service.py`):
  (1) existing Phase 16/17 input verification (`verify_run_trajectory_inputs`,
  including full `verify_world_snapshot` recompilation); (2) recorded
  runtime must be exactly `"2.0.0"` and the run COMPLETE; (3) the stored
  `RunTrajectoryExecution` is loaded only through the store boundary and
  fully verified with the existing authoritative integrity pipeline
  (`verify_run_trajectory_execution_record`) before any final state is
  read; (4) bindings are read **only from the run's exact compiled
  world** (`extract_world_catalog`) — newer scenario-level declarations
  added after world compilation are never consulted; (5) per binding:
  scenario/world/manifest/state-model/field provenance verified against
  the embedded records, exactly one matching `RunStateTrajectoryResult`
  required (missing/ambiguous rejected), exact state-model identifier,
  id, manifest, and content-hash agreement, bound `state_field_id`
  required in `final_state`, extraction of
  `final_state[state_field_id]` only, strict integer/number validation,
  metric unit copied from the embedded scenario, value bound to the
  exact result/plan/execution provenance; (6) the complete set is
  stored **only after every validation and integrity check succeeds —
  any failure writes nothing**. Extraction never evaluates or
  re-executes transitions, never replays, never reads `initial_state`
  as an observation, never samples uncertainty, never invokes
  LEGION/NEXUS, never loads or executes a domain pack, and performs no
  network, provider, filesystem, database, randomness, or wall-clock
  operations.
- **Verification**: `verify_run_metric_observation_set_record`
  revalidates the stored contract strictly, verifies the authoritative
  run inputs, compiled world, embedded bindings, and
  `RunTrajectoryExecution`, deterministically regenerates the expected
  observation set in memory, and requires **exact canonical equality**
  (identifier, ordering, values, provenance, content hash — compared
  over canonical JSON serializations, so value-kind confusion such as a
  boolean where an integer belongs is detected). The stored artifact is
  never repaired, normalized, reordered, overwritten, or silently
  accepted. The GET path returns a stored set only after this full
  verification and never creates an artifact when none exists.
- **Store** (`InMemoryScenarioStore`): immutable tenant-scoped
  collection keyed `(tenant_id, run_id)`; exactly one set per tenant +
  run; duplicate creation rejected — even an identical second write —
  and never overwritten; deep defensive copies on write/read; strict
  complete contract revalidation before storage (validator-bypassed
  artifacts, non-finite raw values, and non-canonical ordering
  rejected); incorrect ownership keys rejected; foreign tenant
  indistinguishable from missing; rejected writes leave storage
  byte-identical; no update/delete/repair/replace surface.
- **API** (all X-Tenant-ID scoped): `POST
  /v1/runs/{run_id}/metric-observations` (201 with the exact
  `RunMetricObservationSet`; explicit post-execution extraction;
  unknown/foreign run 404 `not_found`; legacy 1.0.0 or unsupported
  runtime 409 `conflict`; run not COMPLETE 409 `invalid_state`; second
  extraction 409 `conflict`; corrupted execution/world/binding/artifact
  or extraction failures 409 `integrity_error`) and `GET
  /v1/runs/{run_id}/metric-observations` (200 only after full
  verification; missing/foreign artifact 404 and **never** creates;
  corrupted records 409 `integrity_error`). Public error messages never
  expose raw state or observed values, hashes, guard/target values,
  strategy policy content, metadata values, another tenant's
  identifiers or records, or internal integrity reasons. No
  operational-activity event is recorded and no Colony changes exist.
- **Non-goals**: no `MetricOutcome`/`OutcomeVector` or
  `EvidenceReference`/`DecisionBrief` production, no aggregation across
  seeds/runs/campaigns, no distribution calculation, no metric
  normalization/transformation/unit conversion, no uncertainty
  sampling, no scoring/ranking/recommendations, no strategy comparison
  conclusions, no new runtime versions, no automatic extraction during
  execution, no operational-activity kinds, no Colony changes, no real
  NEXUS/LEGION integration, no live actions, no external
  providers/network, no filesystem/database persistence, no new
  dependencies, no AGENTS.md/global-config changes, no commits or
  pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan generation, campaign/
  run lifecycle, trajectory planning, transition evaluation,
  `RunTrajectoryExecution` generation and hashes, `RunEvent` and its
  three structural kinds, replay behavior and replay-manifest hashes,
  Phase 17 artifact queries, the Phase 18 campaign trajectory matrix,
  and Phase 19 declaration behavior and compiled observation snapshots
  are unchanged. **Phase 21 has not started.**

## Phase 21: deterministic campaign metric-observation matrix

Phase 21 assembles the **complete campaign observation matrix**: the
exact authoritative strategy x shared-seed raw-observation layout of one
completed runtime-2.0.0 campaign.

```
CampaignTrajectoryMatrix (Phase 18 authoritative layout)
    + verified RunMetricObservationSet per run (Phase 20)
    -> CampaignMetricObservationMatrix (Phase 21, in memory only)
```

Phase 18 established the authoritative fair strategy x shared-seed run
layout; Phase 20 produces exactly one verified raw observation set per
completed run; Phase 21 binds every completely verified Phase 20 set to
its exact Phase 18 trajectory cell and produces the comparison-ready
matrix - exact raw values and provenance preserved, never aggregated,
normalized, converted, or interpreted.

- Endpoint: `GET /v1/campaigns/{campaign_id}/metric-observation-matrix`
  - read-only, tenant-scoped, all-or-nothing; returns the direct
  `CampaignMetricObservationMatrix` contract (the 34th public contract,
  appended last; its cell and the Phase 20 value remain nested).
- Assembled in memory through the pure builder and **never stored**;
  missing Phase 20 sets are **never automatically extracted** - a
  missing or corrupted set rejects the whole matrix (409
  integrity_error).
- Typed errors: 404 unknown/foreign campaign, 409 invalid_state
  (non-COMPLETE campaign), 409 conflict (legacy/unsupported runtime),
  409 integrity_error (missing/corrupted Phase 20 artifacts or an
  internally malformed matrix) - public messages never leak raw
  observation values, hashes, states, or internal reasons.
- Deterministic: identifier derived from the campaign/world/runtime
  identity; content hash over the canonical serialization; `assembled_at`
  from the recorded campaign `created_at` - never the wall clock.
- **Non-goals**: no aggregation, outcomes, distributions, evidence,
  scoring, ranking, recommendations, decision briefs, strategy
  comparison conclusions, normalization/transformation/unit conversion,
  automatic Phase 20 extraction, matrix storage, new runtime versions,
  execution/replay/lifecycle changes, operational-activity kinds,
  Colony changes, real NEXUS/LEGION integration, live actions, external
  providers/network, filesystem/database persistence, new dependencies,
  AGENTS.md/global-config changes, commits or pushes. Runtime
  1.0.0/2.0.0 behavior, RunPlan generation, campaign/run lifecycle,
  trajectory planning, transition evaluation, `RunTrajectoryExecution`
  generation and hashes, `RunEvent` and its structural kinds, replay
  behavior, Phase 17 artifact queries, the Phase 18 campaign trajectory
  matrix, Phase 19 declaration behavior, and Phase 20 extraction
  behavior are unchanged. **Phase 22 has not started.**

## Product boundaries

| Component | Owns |
| --- | --- |
| **NEXUS** | Natural-language dialogue, organizational context, memory, presentation |
| **LEGION** | Strategy and agent exploration |
| **KALHAS** | Versioned world models, uncertainty, deterministic simulation campaigns, evidence, replay |

KALHAS core never imports NEXUS or LEGION internals; it depends only on the
placeholder protocols in `kalhas/adapters/` (`NexusAdapter`, `LegionAdapter`).

## Repository layout

```
kalhas/
  contracts/       versioned public contracts (frozen per API version) + schema export
  application/     use cases, runtime configuration, campaign lifecycle
  adapters/        boundary protocols toward NEXUS / LEGION (placeholders)
  api/             FastAPI application, routes, typed error handling
  colony_ui/       optional local observability UI (Phase 10, static HTML/CSS/JS)
  domain_packs/    future domain packs; kernel knows them only via DomainPack
schemas/v1/        checked-in JSON Schema artifacts (generated, do not edit)
tests/             pytest suite
scripts/           tooling (schema export)
docs/
  architecture/    layer map, dependency rules, contracts-and-lifecycle
  decisions/       ADR 001, ADR 002, ADR 003
```

## API (Phase 0)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| GET | `/v1/system-info` | Application version, API version, runtime mode, standalone statement |
| GET | `/docs` | OpenAPI (Swagger UI) |
| GET | `/openapi.json` | OpenAPI schema |

Every error uses one typed shape (HTTP status + JSON body):

```json
{
  "code": "not_found",
  "message": "Not Found",
  "details": [],
  "request_id": "3f2a..."
}
```

Runtime mode is read from `KALHAS_RUNTIME_MODE` (`development` | `test` |
`production`; default `development`).

## Prerequisites

- Python 3.12+ (this repo pins 3.12 in `.python-version`)
- [uv](https://docs.astral.sh/uv/) (recommended; provisions Python and the
  venv itself). All commands below also work without GNU make.

## Setup (PowerShell, exact commands)

```powershell
cd C:\Users\xampos\Desktop\Encomm-Kalhas
uv sync --python 3.12
```

Fallback without uv:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Run (local development)

```powershell
uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Then open <http://127.0.0.1:8000/docs>.

## Test, lint, type-check

```powershell
uv run pytest                        # tests
uv run ruff check .                  # lint
uv run ruff format .                 # format (auto-fix)
uv run ruff format --check .         # format check
uv run mypy kalhas tests             # strict type check
```

Convenience layer (only if GNU make / mingw32-make is installed):

```powershell
make setup run test lint format format-check typecheck check
```

`make check` runs lint, format-check, type-check, and tests.

> **Troubleshooting:** if a globally set `PYTHONPATH` exists (for example, set
> by a host application), it can shadow the project venv and break `uv run
> pytest` / `uvicorn` with `ModuleNotFoundError`. Clear it first:
> `Remove-Item Env:PYTHONPATH` (PowerShell) or `unset PYTHONPATH` (bash).

## Durable rules

See `AGENTS.md` at the repository root. Highlights: domain-neutral kernel,
no NEXUS/LEGION internal imports, deterministic replay and fair strategy
comparison are mandatory, no live actions in the MVP, versioned public
contracts are backward compatible, tests accompany behavioral changes.

## Phase 22: deterministic campaign metric statistics

Phase 22 summarizes each strategy's exact metric observations of one
completed runtime-2.0.0 campaign into an immutable, deterministic,
tenant-scoped **descriptive-statistics matrix** - derived exclusively
from the completely verified Phase 21 `CampaignMetricObservationMatrix`.

```
verified CampaignMetricObservationMatrix (Phase 21)
    -> exact per-strategy/per-metric seed observations
    -> deterministic descriptive statistics (Phase 22, in memory only)
```

Phase 21 supplies the verified raw strategy x seed observation layout;
Phase 22 computes the fixed descriptive statistics - minimum, maximum,
arithmetic mean, median, and population standard deviation (population
denominator N, `math.fsum`/`math.sqrt`, Python standard library only) -
over each strategy's exact ordered shared-seed observations. Exact raw
values remain preserved in seed order (raw integers stay integers), no
declared `MetricDefinition.aggregation` policy is interpreted, and no
OutcomeVector, evidence, ranking, or recommendation exists yet.

- Endpoint: `GET /v1/campaigns/{campaign_id}/metric-statistics`
  - read-only, tenant-scoped, all-or-nothing; returns the direct
  `CampaignMetricStatisticsMatrix` contract (the 35th public contract,
  appended last; its summary model remains nested).
- Derived in memory through the pure builder and **never stored**; the
  Phase 21 matrix is obtained through the existing verified query
  service - Phase 18/20/21 verification is never weakened and missing
  Phase 20 sets are **never automatically extracted**.
- Typed errors: 404 unknown/foreign campaign, 409 invalid_state
  (non-COMPLETE campaign), 409 conflict (legacy/unsupported runtime),
  409 integrity_error (missing/corrupted earlier-phase artifacts, or
  Phase 22 calculation/consistency/overflow/non-finite failures) -
  public messages never leak raw observation values, calculated
  statistics, hashes, field names, states, or internal reasons.
- Deterministic: identifier derived from the campaign/world/runtime/
  source-matrix identity; content hash over the canonical serialization;
  `summarized_at` from the authoritative Phase 21 matrix `assembled_at`
  - never the wall clock; repeated builds and GET responses are
  byte-identical.
- **Non-goals**: no ranking, scoring, winner declaration, objective/
  target comparison, pass/fail judgments, `MetricOutcome`,
  `OutcomeVector`, evidence, `DecisionBrief`, recommendations, declared
  aggregation-policy interpretation, quantiles/confidence intervals,
  normalization/unit conversion, uncertainty sampling, automatic Phase
  20 extraction, statistics storage, new runtime versions,
  execution/replay/lifecycle changes, operational-activity kinds,
  Colony changes, real NEXUS/LEGION integration, live actions, external
  providers/network, filesystem/database persistence, new dependencies,
  AGENTS.md/global-config changes, commits or pushes. Runtime
  1.0.0/2.0.0 behavior, RunPlan generation, campaign/run lifecycle,
  trajectory planning, transition evaluation, `RunTrajectoryExecution`
  generation and hashes, `RunEvent` and its structural kinds, replay
  behavior, Phase 17 artifact queries, the Phase 18 campaign trajectory
  matrix, Phase 19 declaration behavior, Phase 20 extraction behavior,
  and the Phase 21 metric-observation matrix are unchanged. **Phase 23
  is complete (next section).**

## Phase 23 status

**Deterministic objective-to-metric evaluation (COMPLETE).** Phase 23
adds the immutable, tenant-scoped per-scenario **evaluation profile**
(`ScenarioEvaluationProfile`, the 36th public contract) declared via
API with only the caller-owned fields `objective_id`, `metric_id`,
`reach_tolerance`, `normalization_scale` - direction, target, weight,
and metric unit are always copied from the stored `ScenarioSpec`, so
forged authoritative fields are impossible. The profile is embedded
into subsequently compiled world snapshots (byte-identical Phase 22
world output and hashes when no profile exists) and evaluated at
campaign time exclusively from the completely verified Phase 21
`CampaignMetricObservationMatrix` into the read-only
`CampaignObjectiveEvaluationMatrix` (37th public contract, appended
last), with `ObjectiveMetricBinding` and `ObjectiveObservationEvaluation`
remaining nested (never registered). Evaluation is **target violation
only** - `signed_target_delta` is direction-aware and positive =
adverse (minimize/reach: `value - target`; maximize:
`target - value`; reach subtracts `reach_tolerance`), `target_achieved`
is `delta <= 0`, and `normalized_target_violation` is
`max(0, delta) / normalization_scale` - with no regret, ranking,
dominance, preference, probability, confidence, distribution, risk,
evidence, or recommendation semantics anywhere.
- **Contracts** (`kalhas/contracts/v1/objective_evaluation.py`):
  `ObjectiveMetricBinding` (frozen, `extra="forbid"`, nested) snapshots
  the authoritative objective/metric fields; `ScenarioEvaluationProfile`
  (frozen, `extra="forbid"`, registered) holds one binding per scenario
  objective in the **exact `ScenarioSpec.objectives` order** (never
  caller order), with independent `scenario_content_hash` (SHA-256 of
  the canonical full `ScenarioSpec` dump), a non-circular identifier
  `evaluation-profile-{sha256(canonical_json({tenant_id, scenario_id,
  scenario_content_hash, schema_version}))[:16]}`, a self-covering
  `content_hash`, timezone-aware `declared_at`, and strict JSON
  `metadata`; `ObjectiveObservationEvaluation` (frozen,
  `extra="forbid"`, nested) enforces the exact evaluation-field
  consistency rules (all three fields `None` iff no target; the cell
  independently recomputes the expected signed delta from its own raw
  value, direction, target, and tolerance via the shared pure
  `evaluate_target_delta` helper and requires `achieved == (delta <=
  0)` and `violation == max(0, delta) / scale` exactly, so
  self-consistent forged triples are rejected);
  `CampaignObjectiveEvaluationMatrix` (frozen, `extra="forbid"`,
  registered) enforces the **required** runtime literal `2.0.0` (no
  default; in the schema `required` array), comparison mode
  `identical_conditions`, complete strategy x seed x objective
  Cartesian coverage in exact strategy-major, seed-minor,
  objective-minor order with contiguous positions, identity-vs-position
  agreement, source matrix/profile/world/scenario provenance ids and
  hashes, and a self-covering content hash. Exactly two new schema
  artifacts (`ScenarioEvaluationProfile.schema.json`,
  `CampaignObjectiveEvaluationMatrix.schema.json`); no existing v1
  contract field changed; `PUBLIC_CONTRACTS` 35 -> **37**.
- **Numeric strictness**: booleans, strings, `None`, containers, NaN,
  and Infinity are rejected before any coercion (contract-level and
  service-level for caller fields; builder-level and
  world-integrity-level defense-in-depth for snapshots); raw integers
  stay integers and raw floats stay floats; `normalization_scale` must
  be exact finite numeric > 0; `reach_tolerance` is required and
  finite >= 0 for `reach` only and forbidden otherwise; non-finite or
  overflowed derived deltas/violations reject the complete matrix with
  a typed 409.
- **Declaration lifecycle**
  (`kalhas/application/objective_evaluation_service.py`): one immutable
  profile per tenant + scenario; declaration-before-first-world-
  compilation enforced (typed 409 after any compiled world); duplicates
  rejected and never overwrite (typed 409); unknown/foreign scenario
  and missing/unknown objective or metric -> typed 404/422;
  reach-without-target, tolerance/scale violations -> typed 422;
  complete coverage with exactly-one reference per objective; stored
  deep-copied and strict-revalidated on write and **every read**, with
  independent ownership/identifier/content-hash verification before
  any copy crosses the store boundary; no update,
  replace, delete, or list surface; tenant isolation with foreign
  access indistinguishable from missing. `GET` returns the stored
  profile unchanged.
- **World integration** (`world_compiler.py`, `world_integrity.py`):
  the declared profile is embedded under a dedicated
  `evaluation_profile` single-object key and included in the world
  content hash only when present - profile-free worlds compile
  byte-identically to Phase 22 (runtime-2 golden identifiers and
  hashes preserved, hash-compat regression-tested); the compiler
  canonicalizes and snapshots only and never interprets objective
  semantics. `verify_world_snapshot` strictly parses the embedded
  profile, recomputes the scenario content hash from the embedded
  scenario, re-derives profile identifier and content hash, requires
  exact scenario-order binding coverage with copied-value agreement
  (direction/target/weight/metric unit), tolerance/scale rules, and
  recompile-equality; `VerifiedWorldCatalog` gained the canonical
  `evaluation_profile`. `MockNexusAdapter.compile_scenario` loads the
  stored profile.
- **Pipeline** (`kalhas/application/objective_evaluation_runtime.py` +
  `objective_evaluation_query_service.py`): COMPLETE gate (409
  `invalid_state`) -> existing verified Phase 21 query as the sole
  observation source -> fully verified compiled world -> exact
  world-embedded profile strictly matched against the stored record
  (world without embedded profile -> 404; missing/mismatched stored
  record -> 409 `integrity_error`) -> pure in-memory builder that
  re-derives every source identifier and content hash, resolves each
  binding to exactly one verified observation, and emits the complete
  matrix. **Never stored** (no store collection or method exists), no
  automatic extraction, no execution/replay/repair/lifecycle changes,
  no operational-activity kinds or writes, no Colony changes.
- **API**: `POST /v1/scenarios/{scenario_id}/evaluation-profile`
  (201, exact `ScenarioEvaluationProfile`; request model accepts only
  the four caller-owned fields plus `declared_at`/`metadata`; forged
  authoritative fields -> 422), `GET /v1/scenarios/{scenario_id}/evaluation-profile`
  (200/404), `GET /v1/campaigns/{campaign_id}/objective-evaluations`
  (200 exact matrix, GET-only; 404 unknown/foreign campaign or
  profile-less world; 409 `invalid_state`; 409 `conflict` legacy
  runtime; 409 `integrity_error`). Single `ApiErrorResponse` envelope
  unchanged; public messages never leak raw values, targets,
  tolerances, scales, hashes, metadata, or integrity reasons; repeated
  GETs byte-identical.
- **Non-goals**: no comparative regret, ranking, dominance, preference,
  winner selection, probability/confidence/quantiles/distributions,
  risk/CVaR, evidence, `DecisionBrief`, recommendations, uncertainty
  sampling or seed consumption, new runtime versions, automatic
  evaluation during execution, operational-activity kinds, Colony
  changes, real NEXUS/LEGION integration, live actions, external
  providers/network, filesystem/database persistence, new
  dependencies, AGENTS.md/global-config/skill changes, commits or
  pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan generation, campaign/
  run lifecycle, trajectory planning, transition evaluation,
  `RunTrajectoryExecution` generation and hashes, `RunEvent` and its
  structural kinds, replay behavior and replay-manifest hashes, Phase
  17 artifact queries, the Phase 18 campaign trajectory matrix, Phase
  19 declaration behavior, Phase 20 extraction behavior, the Phase 21
  metric-observation matrix, and the Phase 22 metric-statistics matrix
  are unchanged (world hashes change only for worlds compiled with a
  declared profile - new deterministic provenance). **Phase 24 is
  complete (next section).**

## Phase 24 status

**Deterministic world uncertainty realizations (COMPLETE).** Phase 24
is **sampling and provenance only**: for a campaign's shared seeds it
produces exactly one immutable, strategy-independent
`WorldRealization` per seed from the compiled world and the scenario's
immutable `WorldUncertaintyModel` - it never executes strategies,
trajectories, transitions, or metrics; never evaluates objectives;
never produces outcomes, empirical distributions, evidence, rankings,
or recommendations; never invokes NEXUS or LEGION; never loads or
executes domain-pack code; and never uses providers, network,
databases, filesystems, wall clocks, global RNG, UUIDs, or
`random.seed`. Phase 25 / runtime 3.0.0 has not started.

- **Contracts** (`kalhas/contracts/v1/world_realization.py`): exactly
  three new public contracts appended at the tail -
  `WorldUncertaintyModel` (38th), `WorldRealization` (39th), and
  `CampaignWorldRealizationMatrix` (40th); `PUBLIC_CONTRACTS` 37 -> 40.
  The five distribution families (`uniform(low, high)` with
  `low <= high`; `triangular(low, mode, high)` with
  `low <= mode <= high`; `normal(mean, standard_deviation)` and
  `lognormal(mu, sigma)` - mu/sigma are **log-space** parameters - with
  strictly positive deviations; `discrete(values, probabilities)` with
  canonically unique strict values, finite non-negative probabilities,
  at least one positive, and a documented `1e-12` sum tolerance) form a
  **closed discriminated union** `DistributionSpecification` - no
  unvalidated parameter dictionaries anywhere. `StateFieldUncertaintyBinding`
  copies every authoritative provenance field from stored immutable
  records (scenario, source pack binding, manifest, pack identity,
  manifest/state-model content hashes, deterministic state-model
  identity, target field and copied value kind) and adds the
  caller-owned distribution, one exact rounding policy
  (`floor`/`ceil`/`nearest_ties_to_even`) for integer targets only, and
  independently optional clipping bounds (integer targets require
  exact `int` bounds). `SampledStateFieldValue` records the raw sample
  **before** clipping/rounding (integer-target raws may legitimately be
  float) and the final realized value (integer targets always exact
  `int`), with global digest-word `draw_index`/`draw_count` accounting
  (normal/lognormal consume 2 words; all others 1) whose ranges
  partition `[0, total_words)` with no gaps or overlaps.
  `WorldRealization` carries world/seed identity **and** content-hash
  provenance, the uncertainty-model identity/hash or an explicit
  absent state, the frozen sampler/quantization provenance literals
  (`sha256-counter-v1`, `rational-round-half-even`, 64 fraction bits),
  the complete realized initial-state override delta (exactly one
  override per binding in canonical order, one-to-one with the sampled
  values), a deterministic identifier independent of the content hash,
  and `realized_at` = the campaign's authoritative `created_at` - never
  the wall clock. `CampaignWorldRealizationMatrix` holds exactly one
  realization per campaign seed in exact seed-ensemble order with
  **no strategy identifiers anywhere**. All eight nested value objects
  stay unregistered. `UncertaintyDefinition` remains untouched.
- **Deterministic sampler** (`kalhas/application/deterministic_sampler.py`,
  `sha256-counter-v1`): integer-only Q64.64 fixed-point with **frozen
  integer literals** (never platform libm - e.g. `math.log(2.0)` on
  this platform differs from the exact constant by 428 Q64.64 units).
  Every declared parameter is converted by exact rational
  round-half-even quantization (`float.as_integer_ratio()` +
  `divmod`); the open-uniform input is `u = (word + 1) / 2**64`
  (structurally never zero; `log(0)` unreachable, documented `2**-65`
  upward bias); one SHA-256 per digest word from the canonical payload
  `{domain: "kalhas/world-realization-v1", draw_index, sampler_version,
  seed_content_hash, uncertainty_binding_content_hash,
  world_content_hash}` with the word as the first 8 bytes big-endian;
  `sqrt` via exact `math.isqrt`; `log` via a fixed 32-term atanh
  series; `exp` reduced by `ln 2` (`k = floor(x/ln2)`, `r = x - k*ln2`,
  `exp = 2**k * exp(r)`, 24-term Horner, `k > 1024` rejected before any
  shift, `k < -65` returns exactly 0); `cos` via quadrant reduction
  plus a fixed 14-term Horner; Box-Muller from two words with the
  exact deterministic radius `sqrt(-2 ln u1)` and the invariant-checked
  maximum `Z_MAX = isqrt(128 ln2)`. Discrete selection uses exact
  integer weights with the ticket `(word * W) >> 64` and strict `<`
  cumulative boundaries (a ticket exactly on a boundary resolves to the
  later value; zero-probability support is never selected; **no forced
  residual assignment**). Verified accuracy budgets: `log`/`cos` at
  most 64/32 Q64.64 ulps, `exp` relative error below `2**-50`.
- **Representation semantics**: canonical JSON `1` and `1.0` are
  distinct. Continuous families always record float raws (even when
  mathematically integral); a discrete sample preserves the exact
  declared value type; clipping a number target adopts the exact stored
  bound type; integer targets always finish as exact `int` after the
  declared policy (raw recorded **before** clipping, finite-raw guard
  before any clip - clipping can never rescue a non-finite raw).
- **Declaration lifecycle** (`world_uncertainty_service.py`): one
  immutable model per tenant + scenario; declaration-before-first-world-
  compilation (typed 409 after any compiled world); duplicates rejected
  and never overwrite (typed 409); unknown/foreign scenario -> 404;
  unknown manifest/state model/field, unsupported field kinds (only
  `integer`/`number` initial-state fields), rounding/bound rules,
  discrete-kind agreement, effective Q64.64 parameter rules (vanishing
  rule, effective ordering, effectively positive deviations, lognormal
  static finite-raw boundary), and statically provable discrete
  allowed-values outcomes -> typed 422. Bindings are canonicalized into
  exact `(manifest_id, state_model_id, state_field_id)` order.
  Identifiers are hash-derived from canonical identity payloads -
  never from the content hash - and every content hash is
  self-covering. The store strictly revalidates the complete contract
  and the deterministic identity on **every** write and read.
- **World integration**: the compiler embeds the complete model
  snapshot under `uncertainty_model` (hash-covered) **only when
  present** - model-free worlds compile byte-identically to Phase 23
  and no runtime-2 golden world hash changes. `verify_world_snapshot`
  strictly verifies the embedded model's ownership, identifier, content
  hash, canonical binding order, copied authoritative provenance
  against the embedded pack-binding/state-model snapshots, sampler
  literals, effective parameters, and static discrete allowed outcomes;
  `VerifiedWorldCatalog` gained the additive `uncertainty_model`.
- **Builder/query** (`world_realization_builder.py` +
  `world_realization_query_service.py`): the pure builder derives each
  base initial state from the embedded `DomainStateModel`, samples each
  targeted field exactly once, applies **finite-raw -> clip -> round ->
  complete-state validation** (via the existing `validate_state` rules
  including canonical `allowed_values` membership - deterministic
  per-seed failure, never a resample), emits detached immutable
  plain-JSON artifacts, and never mutates the world, model, seed, or
  state models. The verified query loads and fully verifies the
  campaign's world/manifest, the stored model (strict revalidation +
  identity/hash + canonical equality with the embedded snapshot), and
  derives the matrix in memory - **never stored**, no lifecycle gate
  (any recorded campaign state yields identical bytes), no writes, no
  operational-activity events, no NEXUS/LEGION calls. A world without
  an uncertainty model still yields one deterministic **empty**
  realization per seed (empty samples/overrides, explicit absent model
  markers, real derived hashes).
- **API**: `POST /v1/scenarios/{scenario_id}/uncertainty-model` (201;
  request model accepts only caller-owned binding fields plus
  `declared_at`/`metadata` - forged authoritative fields, identifiers,
  hashes, and sampler literals -> 422), `GET /v1/scenarios/{scenario_id}/uncertainty-model`
  (200/404/409 integrity), `GET /v1/campaigns/{campaign_id}/world-realizations`
  (200 exact matrix with exactly K realizations for K seeds and any
  strategy count; 404 unknown/foreign campaign; 409 `conflict` for
  deterministic per-seed sampling failures; 409 `integrity_error` for
  missing/corrupt world, manifest, or stored-vs-embedded model
  mismatches). Single `ApiErrorResponse` envelope unchanged; public
  messages never leak sampled values, distribution parameters, bounds,
  hashes, state values, metadata, or internal reasons; repeated GETs
  byte-identical.
- **Non-goals**: no execution, replay, transition, metric extraction,
  objective evaluation, outcomes, empirical distributions, comparison,
  ranking, recommendation, evidence, or decision briefs; no uncertainty
  consumption beyond sampling; no new runtime version; no
  operational-activity kinds or Colony changes; no NEXUS/LEGION
  integration; no live actions, providers, network, filesystem, or
  database; no new dependencies; no AGENTS.md/global-config/skill
  changes; no commits or pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan
  generation and `run_input_hash`, campaign/run lifecycle, trajectory
  planning, transition evaluation, `RunTrajectoryExecution` generation
  and hashes, `RunEvent` structural kinds, replay behavior, all
  Phase 17-22 artifact queries, the Phase 22 metric-statistics matrix,
  and the Phase 23 evaluation profile/matrix are unchanged. World
  hashes change only for worlds compiled with a declared uncertainty
  model - new deterministic provenance. **Phase 25 has not started.**
