# Contracts and campaign lifecycle (Phase 1)

## Versioned contract layer

- All public contracts live under `kalhas/contracts/v1/` and are **frozen**
  once shipped (ADR 001). Breaking changes require `v2`, never in-place edits.
- Every top-level contract inherits `VersionedContract`: stable `identifier`,
  `tenant_id`, and semantic `schema_version` (default `"1.0.0"`, regex
  `^\d+\.\d+\.\d+$`).
- All models are strict: `extra="forbid"` rejects unknown fields.
- Timestamps use `AwareDatetime` (timezone-aware enforced by validator).
- Domain-specific values may appear only as `JsonValue` (JSON-safe recursive
  type: str, int, float, bool, None, list, dict with string keys) or declared
  metadata. **No executable expressions, callbacks, imports, or plugin
  execution anywhere in the contracts.**
- `WorldVersion` is `frozen=True`: immutable by contract, with an optional
  `parent_version_id` forming a version chain. It carries provenance -
  `source_scenario_id`, `compiler_version`, `content_hash` - because it is a
  compiled artifact, not raw input.
- **Contract direction:** `ScenarioSpec` -> semantic validation -> immutable
  `WorldVersion` -> `CampaignSpec`. Scenarios describe intent only (no world
  reference); worlds are produced by the deterministic compiler; campaigns
  reference an already compiled world (`world_version_id`).
- `ScenarioSeed` carries only reproducible, serializable seed material
  (`algorithm` + `seed_value`); no random sampling is implemented.
- **Fair comparison is a structural invariant of `CampaignSpec`.** Every
  campaign owns a shared, ordered, non-empty `seed_ensemble` of
  `ScenarioSeed` contracts with unique identifiers; every strategy candidate
  receives the exact same ordered seed identifiers and equivalent observation
  permissions. `comparison_mode` is a single-value literal
  (`identical_conditions`), so no other mode can be expressed. Scenario-level
  input (`ScenarioSpec`) does not own seed assignment.
- `RunEvent` distinguishes `simulation_time` (inside the world) from
  `created_at` (recording time) and carries `sequence` for deterministic
  replay ordering.
- `OutcomeVector` and `DecisionBrief` represent distributions
  (`DistributionSummary`), risks, assumptions, uncertainty, and evidence
  references - never a single unexplained score.

## Contract modules

| Module | Contents |
| --- | --- |
| `shared.py` | `JsonValue`, `AwareDatetime`, `VersionedContract`, `Assumption`, `RiskStatement`, `MetricDefinition`, `DistributionKind`, `DistributionSummary`, `UncertaintyStatement` |
| `scenario.py` | `ScenarioSpec`, `ContextBundle`, `ClarificationQuestion`, `ValidationReport`, `ScenarioSeed`, objectives/constraints/time horizon submodels |
| `world.py` | `WorldVersion` (frozen), `WorldManifest`, `UncertaintyDefinition` |
| `strategy.py` | `StrategyRequest`, `StrategyCandidate`, policy/observation submodels |
| `campaign.py` | `CampaignState`, `CampaignSpec` (shared seed ensemble, structural fairness), `CampaignStatus` |
| `simulation.py` | `RunEvent`, `OutcomeVector`, `EvidenceReference`, `DecisionBrief` |
| `trajectory.py` | `StrategyTrajectoryTransitionReference`, `StrategyTrajectoryPlanRequest`, `StrategyTrajectoryPlanDraft`, `StrategyTrajectoryPlan` (Phase 15) |
| `trajectory_execution.py` | `RunTrajectoryAttemptRecord`, `RunStateTrajectoryResult`, `RunTrajectoryExecution`, `RunTrajectoryReplayManifest` (Phase 16) |

The registry `PUBLIC_CONTRACTS` in `kalhas/contracts/v1/__init__.py` lists
the top-level contracts (**30 as of Phase 16**; 28 as of Phase 15); it
drives schema export and contract tests.

## JSON Schema artifacts

- Generated deterministically by `kalhas/contracts/schema_export.py`
  (`json.dumps(..., indent=2, sort_keys=True)`).
- CLI wrapper: `scripts/export_schemas.py` (write mode and `--check` mode).
- Artifacts live in `schemas/v1/<ContractName>.schema.json` and are checked
  in. Never edit by hand.
- `tests/test_schema_sync.py` fails when artifacts drift from the models.
- Nothing is generated during normal application startup.

## Campaign lifecycle state machine

`kalhas/application/campaign_lifecycle.py` - pure, deterministic, free of
persistence, FastAPI, and side effects.

| Current | Allowed targets |
| --- | --- |
| `DRAFT` | `VALIDATED`, `CANCELLED` |
| `VALIDATED` | `COMPILED`, `DRAFT`, `CANCELLED` |
| `COMPILED` | `RUNNING`, `VALIDATED`, `CANCELLED` |
| `RUNNING` | `COMPLETE`, `FAILED`, `CANCELLED` |
| `COMPLETE` | (terminal) |
| `FAILED` | (terminal) |
| `CANCELLED` | (terminal) |

- `allowed_transitions(state)` / `can_transition(current, target)` /
  `transition(current, target)` / `is_terminal(state)`.
- Invalid transitions raise the typed `CampaignTransitionError` carrying
  `current` and `target`.
- `VALIDATED -> DRAFT` and `COMPILED -> VALIDATED` allow rework loops;
  terminal states never reopen (retries start a new campaign).
- No campaign API endpoints in Phase 1 (deliberate, see ADR 003).

## Adapter protocols (refined)

- `NexusAdapter.present(brief: DecisionBrief, context: ContextBundle | None) -> str`
- `LegionAdapter.request_strategies(request: StrategyRequest) -> tuple[StrategyCandidate, ...]`

Still placeholders - no concrete or mock adapters exist.

## Phase 2: standalone validation, compilation, and local mocks

Flow: `ScenarioSpec` -> semantic validation -> immutable `WorldVersion` ->
`CampaignSpec`.

| Service | Responsibility |
| --- | --- |
| `in_memory_store.py` | Process-local storage keyed by `(tenant_id, identifier)`; rejects duplicates and foreign-tenant access; worlds idempotent |
| `scenario_service.py` | Pure semantic validation returning `ValidationReport` + `ClarificationQuestion`s; blocking checks: missing objectives, missing time-horizon resolution, missing success metrics, missing constraints; never invents values |
| `world_compiler.py` | Pure compiler: canonical JSON (sorted keys) + SHA-256 over `{compiler_version, scenario}`; world id derived from the hash; `created_at` derived from the scenario (no wall clock); rejects invalid scenarios via `InvalidScenarioError(report)` |
| `domain_errors.py` | Typed errors: `ScenarioNotFoundError`, `ScenarioAlreadyExistsError`, `WorldNotFoundError`, `InvalidScenarioError` |

Mocks (`kalhas/adapters/mocks/`):

- `MockNexusAdapter` - submit / validate / clarify / compile / fetch flow
  over the store, using only KALHAS contracts and services.
- `MockLegionAdapter` - `request_strategies` returns exactly five
  deterministic candidates (`baseline`, `conservative`, `balanced`,
  `adaptive`, `diversified`) with declared policies, declared assumptions,
  and identical observation permissions; nothing is executed.

API (`X-Tenant-ID` required on all scenario/world endpoints; body tenant
must match):

- `POST /v1/scenarios` (201 / 409 duplicate / 422 tenant mismatch)
- `POST /v1/scenarios/{scenario_id}/validate` -> report + questions
- `POST /v1/scenarios/{scenario_id}/compile` -> world + manifest (422 when
  semantically invalid)
- `GET /v1/worlds/{world_version_id}` -> immutable world

All failures use the single `ApiErrorResponse` shape; domain errors map to
404/409/422 with typed codes.

## Phase 3: campaign preparation and run planning

### RunPlan contract

A strict planning manifest (in `PUBLIC_CONTRACTS`, schema-exported): stable
identifier, tenant, schema version, `campaign_id`, `world_version_id`,
`strategy_candidate_id`, `scenario_seed_id`, `runtime_version`,
`input_hash`, `planned_state` (always `"planned"`), `created_at`. No
executable code, callbacks, provider configuration, or simulated outcomes.

### Services

| Service | Responsibility |
| --- | --- |
| `run_planner.py` | Pure planning: one `RunPlan` per (strategy, seed) pair in stable order; `input_hash` = SHA-256 over `{world_content_hash, strategy, seed, runtime_version}`; identifiers hash-derived from the canonical identity tuple; no randomness, no wall clock |
| `campaign_service.py` | Depends on the `LegionAdapter` protocol (never a concrete adapter). `prepare_campaign`: verifies scenario/world ownership and world-source match, tenant of the strategy request, every seed, and every returned candidate, requires exactly five candidates with unique identifiers and identical ordered observation permissions, stores COMPILED status + run plans; `start_campaign`: only `COMPILED -> RUNNING` |

### Fairness guarantees (structural)

- **The seed ensemble is the sole source of run multiplicity.** Planned run
  count = strategies x seeds; no other run-count field exists.
- Every strategy receives every seed in the exact same seed order (strategies
  outer, seeds inner).
- Every strategy receives the exact same observation permissions (verified at
  preparation; guaranteed by the mock).
- Every planned run references the same immutable world version.
- Hashes are deterministic (lowercase 64-char SHA-256, pattern-enforced);
  strategy-specific hashes differ because strategy contracts differ.
- RunPlan identifiers are SHA-256-derived from
  `(campaign_id, world_version_id, strategy_candidate_id, scenario_seed_id,
  runtime_version)` - stable for identical inputs and immune to delimiter
  characters in user-provided identifiers.
- Duplicate campaign identifiers are rejected per tenant; foreign tenants
  cannot read campaigns or run plans.

### Tenant invariants (typed, at the application boundary)

- `CampaignSpec` rejects any seed whose `tenant_id` differs from the campaign
  tenant.
- `prepare_campaign` rejects: a `StrategyRequest` with a foreign `tenant_id`,
  a returned `StrategyCandidate` with a foreign `tenant_id`, a candidate that
  does not belong to the requested strategy set (different observation
  permissions or duplicate identifiers), and a candidate set that is not
  exactly five entries. All raise typed domain errors mapped to 422 by the
  API - no raw `ValueError` leaks.

## Phase 4: structural execution and exact replay

### Contracts

- `RunStatus` (19th top-level contract): run id, campaign id, run plan id,
  state (PLANNED/RUNNING/COMPLETE/FAILED), runtime version, input hash,
  event hash on completion, created_at/changed_at.
- `ReplayManifest`: run, campaign, world, strategy, seed references,
  runtime version, input hash, expected event hash,
  `replay_classification: Literal["exact"]`, created_at.
- `RunEvent` extended: the three structural kinds (`run_started`,
  `strategy_declaration_recorded`, `run_completed`) and mandatory
  campaign/world/strategy/seed references on every event.

### Services

| Service | Responsibility |
| --- | --- |
| `structural_runtime.py` | `structural_events` regenerates the three ordered events from recorded inputs; `event_hash` = SHA-256 over the canonical ordered stream; `execute_run` PLANNED -> RUNNING -> COMPLETE; `execute_campaign` executes all planned runs in stored order (campaign must be RUNNING) then RUNNING -> COMPLETE |
| `replay_service.py` | `replay_run` loads only recorded inputs, regenerates the stream, recomputes the hash, compares with the recorded expected hash, returns/stores a `ReplayManifest`; rejects non-COMPLETE runs and mismatches with typed errors |

### Structural event sequence

| Sequence | Kind | simulation_time | Payload facts |
| --- | --- | --- | --- |
| 0 | `RUN_STARTED` | horizon start | runtime version, run plan id, `planned -> running` |
| 1 | `STRATEGY_DECLARATION_RECORDED` | horizon start | runtime version, strategy version, policy summary |
| 2 | `RUN_COMPLETED` | horizon end | runtime version, `running -> complete`, event count |

Events carry run/campaign/world/strategy/seed references and a creation time
derived from the recorded run plan - never the wall clock. No outcome,
recommendation, evidence, or probability content exists.

### Replay behavior

1. Load recorded run status (must be COMPLETE), campaign, run plan, recorded
   strategy candidate, recorded seed, immutable world, recorded runtime
   version.
2. Regenerate the three events via `structural_events` (no cached output).
3. Recompute the SHA-256 event hash; mismatch with the recorded
   `expected_event_hash` raises `ReplayHashMismatchError` (409 conflict).
4. Return and record a `ReplayManifest` with `replay_classification: "exact"`.

COMPLETE means structural execution completed, not that decision evidence
was produced; the kernel proves determinism, ordering, in-memory
persistence, and replay mechanics only.

## Phase 5: run-input integrity verification

### Verifier (`kalhas/application/input_integrity.py`)

`verify_run_inputs` loads and verifies a run's recorded inputs using only
recorded state (RunPlan, immutable WorldVersion, exact stored
StrategyCandidate, ScenarioSeed from the campaign's recorded seed ensemble,
RunStatus, campaign identity, recorded runtime version). It validates every
identity and ownership relationship (tenant, run id derivation, campaign and
run-plan references, runtime version, world/strategy/seed references), then
recomputes the SHA-256 input hash via the established `run_input_hash`
algorithm over `{world content hash, strategy contract, seed contract,
runtime version}` and requires an exact match with the RunPlan and RunStatus
hashes. Any missing, inconsistent, or mismatched input raises the typed
`RunInputIntegrityError` with a safe, generic public message (no foreign
data, raw hashes, or internals). Mismatches are never repaired, overwritten,
or accepted.

### Execution atomicity

- **`execute_run`**: verifies before PLANNED -> RUNNING and before any event
  is written. On failure: RunStatus preserved unchanged, no events written,
  run not marked FAILED, typed integrity error raised.
- **`execute_campaign`**: preflights every stored RunPlan in deterministic
  stored order before the first run; any preflight failure means zero runs
  execute, no events, all statuses PLANNED, campaign stays RUNNING (atomic).
  Per-run verification repeats as defense-in-depth.
- **`replay_run`**: verifies recorded inputs before regenerating events and
  before any replay-hash comparison.

### Manifest

`RunInputIntegrityManifest` (20th top-level contract): run/campaign/run-plan/
world/strategy/seed references, runtime version, `expected_input_hash`,
`recomputed_input_hash`, `verification_classification: Literal["exact"]`,
and a deterministic `recorded_at` (the recorded RunPlan creation time - the
manifest attests deterministic input verification, not a real-time audit
event). The latest manifest per run is retained in the store; the
`POST /v1/runs/{run_id}/verify-inputs` endpoint verifies, records, and
returns it without touching lifecycle state or producing any events,
outcomes, evidence, briefs, or recommendations.

## Phase 6: declarative domain pack registry

### `DomainPackManifest` (21st top-level contract)

`kalhas/contracts/v1/domain_pack.py` defines `DomainPackManifest` (frozen,
`extra="forbid"`) and the nested `DomainPackCapability`. The manifest is the
declarative identity of a future domain pack: stable manifest `identifier`,
tenant, schema version, logical `pack_id`, human-readable `name`, strict
semantic `pack_version` (`^\d+\.\d+\.\d+$`), optional `description`,
`supported_api_versions` (per-element pattern `^\d+$`, non-empty, and API
version `1` is mandatory), a non-empty ordered list of `capabilities`
(identifier, description, ordered `input_ids`/`output_ids`, JSON metadata)
with unique identifiers, JSON-compatible `schema_metadata`, a lowercase
64-character `content_hash`, a deterministic `created_at`, and optional JSON
metadata. Capability metadata is descriptive only: no callbacks, imports,
executable expressions, provider references, or runtime behavior can be
expressed by the field types.

### Lifecycle

1. A client POSTs a registration draft to `/v1/domain-packs` with an
   `X-Tenant-ID` header. The draft carries **no** `tenant_id` and **no**
   `content_hash`; tenant ownership comes from the header alone and the
   hash is always computed by the registry.
2. The draft is validated at the request boundary with the same strict
   constraints as the contract (including per-element API-version
   validation) - invalid drafts return the typed 422 envelope and store
   nothing.
3. The registry builds the frozen manifest, computes the authoritative
   content hash, and stores it keyed by `(tenant_id, manifest identifier)`.
   Duplicate identifiers per tenant raise `DomainPackAlreadyExistsError`
   (typed 409 conflict); the stored entry is never overwritten.
4. Lookups are `get` (typed 404 for unknown *and* foreign manifests - they
   are indistinguishable) and deterministic `list` sorted by manifest
   identifier. The store exposes no update/delete/replace surface.

### Authoritative content hash

`content_hash` = lowercase SHA-256 hex (64 chars) over
`canonical_json(<manifest content without content_hash>)` - i.e. the
canonical serialized manifest content excluding `content_hash` itself
(sorted keys, no insignificant whitespace). Equivalent drafts always
produce the same digest; because `tenant_id` and `schema_version`
participate, the same draft registered by two tenants yields different
hashes. The registration draft has no hash field, so a client can never
choose the authoritative hash.

### Tenant isolation

Manifest storage is keyed by `(tenant_id, manifest identifier)`, mirroring
every other store collection. A tenant can list and fetch only its own
manifests; foreign and unknown identifiers raise the same typed error, so
no tenant can learn whether another tenant's manifest exists.

### No execution effect

A registered manifest is metadata, not code: nothing loads, imports,
instantiates, binds, or executes packs. Registration and retrieval never
mutate scenarios, worlds, campaigns, run statuses, events, replay
manifests, or integrity manifests (test-enforced). The `DomainPack`
protocol now exposes only `manifest: DomainPackManifest` - a purely
declarative identity with no executable surface. Phase 6 shipped no
binding (binding arrived in Phase 7, capability-input declarations in
Phase 8); pack loading, pack execution, and domain simulation remain
later phases, and no pack implementation ships.

## Phase 7: immutable domain-pack bindings

### `DomainPackBinding` (22nd top-level contract)

`kalhas/contracts/v1/domain_pack.py` also defines `DomainPackBinding`
(frozen, `extra="forbid"`): stable binding `identifier`, tenant, schema
version, `scenario_id`, `manifest_id`, and an exact snapshot of the
registered manifest - `pack_id`, strict semantic `pack_version`,
lowercase 64-character `manifest_content_hash`, and unique ordered
`capability_ids` (min one, uniqueness enforced by validator), plus a
deterministic `bound_at`. All pack identity and hash fields are copied
from the stored immutable `DomainPackManifest`; the binding API accepts
only `manifest_id` and `bound_at`, so client-supplied identity is
structurally impossible (unknown fields are rejected with 422).

### Binding lifecycle

1. A client POSTs `{"manifest_id", "bound_at"}` to
   `/v1/scenarios/{scenario_id}/domain-pack-bindings` with `X-Tenant-ID`.
   The service verifies the tenant owns both the scenario (typed 404
   `ScenarioNotFoundError`) and the registered manifest (typed 404
   `DomainPackNotFoundError`) - unknown and foreign are indistinguishable,
   so no tenant data leaks.
2. The frozen binding is built from the manifest (never from the client),
   with its identifier hash-derived from the canonical
   `(scenario_id, manifest_id)` tuple (`binding-` + 16 hex chars -
   collision-safe, deterministic, no wall clock).
3. The binding is stored keyed by `(tenant_id, scenario_id, manifest_id)`.
   A duplicate raises `DomainPackBindingAlreadyExistsError` (typed 409)
   and never overwrites the original; there is no update, delete, replace,
   or unbind surface.
4. Compilation (`compile_world` via `MockNexusAdapter.compile_scenario`)
   loads the scenario's stored bindings in deterministic manifest-id order
   and embeds their complete serialized snapshots under
   `WorldVersion.world.domain_pack_bindings`; `WorldManifest.state` gains
   `declared_domain_pack_binding_count` when bindings exist. An unbound
   scenario compiles byte-identically to Phase 6.

### World-hash behavior

The canonical content hash covers `{compiler_version, scenario}` plus
`domain_pack_bindings` (the full serialized binding snapshots) when the
binding set is non-empty - never for an empty set, so unbound hashes are
unchanged. Adding, removing, or reordering bindings (any change to the
deterministic ordered set) therefore produces a new `WorldVersion`
identifier and content hash while every previously compiled world stays
byte-identical in the store. Campaign planning, RunPlan input hashing
(over `world_content_hash`), structural execution, replay, and
input-integrity verification consume the new hash without any algorithm
change.

### No execution effect

Bindings are declarative metadata: the compiler embeds snapshots but never
inspects, loads, instantiates, imports, or executes a domain pack, and
never interprets capability schemas (boundary-test-enforced by source
scan). Registration, binding, listing, and compilation never create
outcomes, evidence, briefs, recommendations, executable behavior, or
real-world effects. Pack execution and domain simulation remain later
phases.

## Phase 8: immutable capability-input declarations

### `DomainCapabilityDeclaration` (23rd top-level contract)

`kalhas/contracts/v1/domain_pack.py` also defines
`DomainCapabilityDeclaration` (frozen, `extra="forbid"`): stable
declaration `identifier`, tenant, schema version, `scenario_id`,
`binding_id`, `manifest_id`, an exact snapshot of the registered manifest
- `pack_id`, strict semantic `pack_version`, lowercase 64-character
`manifest_content_hash` - `capability_id`, JSON-compatible
`input_values` (key/value data keyed by the capability's `input_ids`),
a deterministic lowercase 64-character `content_hash`, and a
deterministic `declared_at`. In addition, `DomainPackCapability` now
rejects duplicate `input_ids` and duplicate `output_ids` by contract
(ordered tuples preserved), so declaration key matching can never be
ambiguous. The declaration API accepts only `manifest_id`,
`capability_id`, `input_values`, and `declared_at`; every identity field
is copied from stored immutable records - client-supplied identity is
structurally impossible (unknown fields are rejected with 422).

### Declaration lifecycle

1. A client POSTs `{manifest_id, capability_id, input_values,
   declared_at}` to `/v1/scenarios/{scenario_id}/domain-capability-declarations`
   with `X-Tenant-ID`. The service verifies the tenant owns the scenario
   (typed 404 `ScenarioNotFoundError`) and that the manifest is bound to
   that exact scenario (typed 404 `DomainPackBindingNotFoundError`) -
   unknown and foreign are indistinguishable, so no tenant data leaks.
2. **Integrity hardening:** the stored binding and manifest must be
   exactly the records implied by the request - binding tenant matches
   the requested tenant, manifest tenant matches the requested tenant,
   binding `scenario_id`/`manifest_id` match the request, the binding
   identifier matches its deterministic derivation - and the binding
   snapshot must exactly match the registered manifest (`pack_id`,
   `pack_version`, `manifest_content_hash`, and the exact ordered
   capability identifier set). Any mismatch raises the safe typed
   `DomainCapabilityDeclarationIntegrityError` (409 `integrity_error`)
   whose public message exposes no raw hashes or internal details.
3. The capability must be declared by the manifest (typed 422
   otherwise), and the `input_values` keys must match the capability's
   ordered `input_ids` **exactly** - no missing keys, no extra keys; a
   capability with no `input_ids` accepts only an empty object (typed
   422 `DomainCapabilityInputKeyMismatchError`).
4. The frozen declaration is built with its identifier hash-derived from
   the canonical `(scenario_id, manifest_id, capability_id)` tuple
   (`declaration-` + 16 hex chars) and its `content_hash` computed over
   the canonical serialized declaration content **excluding
   `content_hash` itself** (same pattern as manifests).
5. The declaration is stored keyed by `(tenant_id, scenario_id,
   manifest_id, capability_id)`. A duplicate raises
   `DomainCapabilityDeclarationAlreadyExistsError` (typed 409) and never
   overwrites the original; there is no update, delete, replace, or
   mutation surface.
6. Compilation (`compile_world` via `MockNexusAdapter.compile_scenario`)
   loads the scenario's stored declarations and embeds their complete
   serialized snapshots under
   `WorldVersion.world.domain_capability_declarations`;
   `WorldManifest.state` gains `declared_domain_capability_declaration_count`
   when declarations exist. A declaration-free scenario compiles
   byte-identically to Phase 7.

### Deterministic compiler ordering

The compiler never relies on caller-provided collection ordering: it
canonicalizes snapshots itself - bindings sorted by `manifest_id`,
declarations by `(manifest_id, capability_id)` - and uses the same
canonicalized tuples in the content hash, the serialized
`WorldVersion.world` content, and the `WorldManifest` counts. Equivalent
snapshot sets supplied in any tuple order therefore compile to identical
hashes and identical serialized worlds; already correctly ordered stored
inputs sort to the identical order, so established hashes are unchanged
(test-enforced with reversed input tuples).

### World-hash behavior

The canonical content hash covers `{compiler_version, scenario}` plus
`domain_pack_bindings` and `domain_capability_declarations` (the full
serialized snapshots) when the respective sets are non-empty - never for
an empty set, so unbound and declaration-free hashes are unchanged.
Declaring inputs for a capability therefore produces a new `WorldVersion`
identifier and content hash while every previously compiled world stays
byte-identical in the store. Campaign planning, RunPlan input hashing
(over `world_content_hash`), structural execution, replay, and
input-integrity verification consume the new hash without any algorithm
change.

### No execution effect

Declarations are inert inputs: the service matches `input_values` keys
against the capability's `input_ids` (safe identifier matching only) and
the compiler embeds snapshots, but nothing interprets schemas, invokes a
capability, calculates outputs, generates metrics, or produces decision
evidence. No pack is loaded, imported, instantiated, or executed
(boundary-test-enforced by source scan of the compiler, the binding
service, and the declaration service). Declaring, listing, and compiling
never create outcomes, evidence, briefs, recommendations, executable
behavior, or real-world effects. Pack execution and domain simulation
remain later phases.

## Phase 9: operational activity feed

### Purpose and strict non-goals

The activity feed is a lightweight, append-only, tenant-scoped record of
structural lifecycle facts already known to KALHAS, intended as the read
surface for Encomm Colony observability (Phase 10 ships the local Colony
UI that reads it). It is **operational observability
only**: not a simulation event stream, not evidence, not hidden reasoning,
and not part of any `WorldVersion`, `RunPlan`, input-integrity hash, event
hash, or replay guarantee. Recording activity never alters worlds,
campaigns, runs, replay artifacts, integrity artifacts, manifests,
bindings, or declarations, and never feeds any hash. This phase adds no
UI, no WebSockets/SSE, no polling loop, and no fake live-agent state:
retrieval is pull-based and read-only.

### Contracts (`kalhas/contracts/v1/activity.py`)

- `OperationalActivityKind` (StrEnum): twelve generic structural kinds
  (`scenario_registered`, `world_compiled`, `domain_pack_registered`,
  `domain_pack_bound`, `capability_inputs_declared`,
  `domain_state_model_declared`, `domain_state_transition_declared`,
  `campaign_prepared`, `campaign_started`, `campaign_executed`,
  `run_inputs_verified`, `run_replayed`). Phase 9 shipped ten of these;
  Phase 11 added the eleventh, `domain_state_model_declared`, and
  Phase 12 added the twelfth, `domain_state_transition_declared`.
- `OperationalActivityEvent` (24th top-level contract, frozen,
  `extra="forbid"`): `VersionedContract` identity plus `sequence` (int
  `>= 0`), `kind`, `occurred_at` (timezone-aware), optional structural
  references (`scenario_id`, `world_version_id`, `campaign_id`, `run_id`,
  `manifest_id`, `binding_id`, `declaration_id`), and a strict
  JSON-compatible `payload`.

### Event ordering and storage

The store assigns the tenant-local strictly increasing `sequence`
(starting at zero) and the deterministic identifier `activity-{sequence}`
at append time. Events are immutable once appended; the store exposes no
update, delete, replace, clear, or unrestricted mutable activity surface.
Within one tenant, retrieval order is append order (ascending sequence).
Bounded retrieval accepts an optional `after_sequence` cursor (events
strictly after it) and an explicit `limit` with a safe bounded maximum
(`MAX_ACTIVITY_LIMIT = 100`). `latest_activity_sequence` is -1 for a
tenant with no activity, so `after_sequence=-1` retrieves every event.

### Payload safety

Payloads contain only safe structural facts for the owning tenant:
identifiers, contract/runtime/compiler versions, event counts, lifecycle
states, and hashes already exposed by the source contracts (for example,
the world `content_hash` or the pack `content_hash`). Raw capability
input values, policy rules, hidden reasoning, provider data, personal or
company data, outcomes, evidence, recommendations, and executable content
are never recorded (test-enforced, including a scan for the raw declared
input values).

### Recording (service `kalhas/application/operational_activity.py`)

One record helper per kind. Each helper appends exactly one event after a
successful operation and derives `occurred_at` from the already-recorded
source contract - scenario `created_at`, world `created_at`, manifest
`created_at`, binding `bound_at`, declaration `declared_at`, campaign
status `changed_at`, integrity manifest `recorded_at`, replay manifest
`created_at` - never the wall clock. The API routes call the helpers only
after success; rejected or failed operations append nothing, and all
return values and lifecycle behavior are unchanged.

### API

`GET /v1/operational-activity?after_sequence=&limit=` (X-Tenant-ID
required). Query validation: `after_sequence >= -1`, `limit` 1-100
(default 20); invalid values return the typed 422 envelope. The typed
response envelope `{events, next_after_sequence, latest_sequence}`
contains the bounded page in ascending sequence order, the cursor for the
next request (last returned sequence, or the requested cursor on an empty
page), and the tenant's latest sequence (-1 when no activity exists). The
endpoint is read-only - it never creates activity events - and a tenant
with no activity receives an empty typed list.

### Hash non-involvement

Activity events are never part of any `WorldVersion` content, `RunPlan`
`input_hash`, run `event_hash`, replay comparison, or input-integrity
verification. Test-enforced by recomputing the world content hash and the
RunPlan input hash from the same recorded artifacts after a fully
recorded flow and asserting exact equality, and by re-running replay
green on the recorded world.

### Limitations

Pull-based read-only observability only: no streaming transport
(WebSockets/SSE), no polling loop, and no fake live-agent state. Phase 10
adds the Encomm Colony UI, which reads this feed with manual pull refresh
only. The feed records structural lifecycle facts only and never
interprets, executes, or exposes anything beyond what the source
contracts already contain.

## Phase 11: immutable declarative state models

### Contracts (`kalhas/contracts/v1/state_model.py`)

- `StateValueKind` (StrEnum): `string`, `integer`, `number`, `boolean`,
  `json`.
- `DomainStateFieldDefinition` (frozen, `extra="forbid"`): `identifier`
  (min length 1), `description`, `value_kind`, `initial_value`
  (`JsonValue`), optional `allowed_values` (default empty), optional
  `metadata` (default empty). Validators run against the **raw input
  before Pydantic coercion** so booleans are never silently accepted as
  integers or numbers; non-finite floats (NaN/Infinity) are rejected for
  every kind, including arbitrarily nested inside `json` values (pure
  recursive structural scan over dicts/lists) and inside metadata;
  `allowed_values` must match the kind, be canonically unique (canonical
  JSON equality, stdlib mirror of the application's `canonical_json`),
  and include `initial_value`.
- `DomainStateModel` (25th top-level public contract, frozen,
  `extra="forbid"`): `VersionedContract` identity plus `scenario_id`,
  `binding_id`, `manifest_id`, `pack_id`, `pack_version` (semver),
  `manifest_content_hash` (64-hex), `state_model_id` (non-empty,
  stable), `state_fields` (unique identifiers enforced), `content_hash`
  (64-hex), `declared_at`, optional `metadata`. All identity fields are
  copied exclusively from stored immutable binding/manifest records -
  never from client input.

### Service (`kalhas/application/domain_state_model_service.py`)

- Deterministic identifier: `state-model-{sha256(canonical_json({scenario_id,
  manifest_id, state_model_id}))[:16]}`; content hash: SHA-256 of the
  canonical serialized model dump excluding `content_hash` itself.
- State fields are **canonicalized by identifier** before the model is
  built, so equivalent caller field orderings produce the same canonical
  model, content hash, and world snapshot.
- Declaration order: scenario ownership (404) → binding (404) → owned
  manifest (404) → **binding-integrity check** (binding tenant ==
  requested tenant, manifest tenant == requested tenant, binding
  scenario/manifest ids == request, binding identifier == deterministic
  derivation, and binding `pack_id`/`pack_version`/
  `manifest_content_hash`/capability-id tuple exactly equal to the
  registered manifest; any mismatch → `DomainStateModelIntegrityError`
  409 `integrity_error` with a generic message + internal `reason`) →
  build + store. Duplicates → 409, never overwrite; store keyed
  `(tenant_id, scenario_id, manifest_id, state_model_id)`, listing
  sorted `(manifest_id, state_model_id)`, no update/delete/replace
  surface.
- The state model is never executed or interpreted: no transitions,
  formulas, expressions, mechanisms, outcomes, evidence,
  recommendations, or real-world actions.

### World compiler (`kalhas/application/world_compiler.py`)

- `content_hash`/`compile_world` gained `state_models=()`. Snapshots
  land under `world["domain_state_models"]` with the manifest count
  `state["declared_domain_state_model_count"]` - both added **only when
  non-empty**, so state-model-free worlds compile byte-identically to
  Phase 10 and worlds compiled before Phase 11 remain unchanged.
- Canonicalization inside the compiler: models by
  `(manifest_id, state_model_id)`, fields by identifier (defense in
  depth, so even a hand-built non-canonical model compiles to the same
  hash as its canonical equivalent). Adding a state model changes the
  newly compiled world hash; the compiler never executes, evaluates,
  derives, or mutates any state field. Campaign planning, input
  integrity, structural execution, replay, and event semantics are
  untouched - the snapshot flows through the immutable world/hash chain.

### API

`POST /v1/scenarios/{scenario_id}/domain-state-models` (201; body
accepts only `manifest_id`, `state_model_id`, `state_fields`,
`declared_at`, optional `metadata` - `extra="forbid"`; 404
unknown/foreign scenario·binding·manifest; 409 duplicate; 409
`integrity_error`; 422 invalid drafts) and `GET
/v1/scenarios/{scenario_id}/domain-state-models` (typed envelope,
deterministic `(manifest_id, state_model_id)` order; 404 unknown/foreign
scenario). All X-Tenant-ID scoped.

### Operational activity and Colony

- New kind `domain_state_model_declared` (eleventh): exactly one event
  per successful declaration with a safe payload (`state_model_id`,
  model `content_hash`, `state_field_count`) and scenario/manifest/
  binding references - never field values, allowed values,
  descriptions, or metadata; rejected operations append nothing.
- Colony maps the new kind to the existing **Domain Registry** zone
  with no new request, timer, stream, or mutation capability: strictly
  read-only, manual-pull, same-origin, `textContent`-only rendering
  unchanged.

### Limitation

Phase 11 is **declarative state-schema registration and world
snapshotting only** - not a mechanism engine. No transitions, formulas,
expressions, mechanism execution, simulation outcomes, evidence,
recommendations, or real-world actions exist yet, and no domain pack
code is ever loaded or executed. A future generic simulation runtime
may consume this data-only foundation.

## Phase 12: immutable declarative state-transition specifications

### Contracts (`kalhas/contracts/v1/transition.py`)

- `DomainStateTransition` (26th top-level public contract, frozen,
  `extra="forbid"`): `VersionedContract` identity plus `scenario_id`,
  `binding_id`, `manifest_id`, `pack_id`, `pack_version` (semver),
  `manifest_content_hash` (64-hex), `state_model_id`,
  `state_model_content_hash` (64-hex, the referenced state model's
  authoritative content hash), `transition_id` (non-empty),
  `description`, `guard_values` (`dict[str, JsonValue]`, default
  empty), `target_values` (`dict[str, JsonValue]`, **must be
  non-empty**), `content_hash` (64-hex), `declared_at`, optional
  `metadata`. All identity fields are copied exclusively from stored
  immutable binding/manifest/state-model records - never from client
  input. A guard is only a declarative equality condition and a target
  is only a declarative intended state patch: the contract is data
  only, with no callbacks, scripts, expressions, formulas, evaluators,
  code references, providers, imports, dynamic loading, policies, LLM
  calls, or executable mechanisms expressible.
- Contract-level validation: `target_values` non-empty; nested
  NaN/Infinity rejected in guard values, target values, and metadata
  (pure recursive structural scan). Key-existence, value-kind, and
  allowed-values checks need the referenced state model and live in the
  service.

### Service (`kalhas/application/domain_state_transition_service.py`)

- Deterministic identifier:
  `transition-{sha256(canonical_json({scenario_id, manifest_id,
  state_model_id, transition_id}))[:16]}`; content hash: SHA-256 of the
  canonical serialized transition dump excluding `content_hash` itself.
- **Guard/target mappings are canonicalized by field identifier** before
  the transition is built, so equivalent caller key orderings produce
  the same canonical transition, content hash, stored representation,
  and world snapshot.
- Declaration order: scenario ownership (404) → binding (404) → owned
  manifest (404) → state model (404) → **binding-integrity check**
  (binding/manifest tenant, binding scenario/manifest ids, deterministic
  binding identifier, binding pack id/pack version/manifest content
  hash/capability-id tuple exactly equal to the registered manifest;
  mismatch → `DomainStateTransitionIntegrityError` 409 `integrity_error`
  with a generic message + internal `reason`) → **state-model-integrity
  check** (state model tenant/scenario/manifest ids, binding
  relationship, deterministic identifier, recomputed content hash, pack
  identity, manifest content hash, canonical field representation;
  mismatch → same safe 409) → **value validation** (every guard/target
  key must identify an existing state-model field; every value must
  exactly match the field's `StateValueKind` - booleans never accepted
  as integer/number, non-finite floats rejected everywhere - and be
  canonically among the field's `allowed_values` when declared;
  violation → `DomainStateTransitionValuesError` 422) → build + store.
  Duplicates → 409, never overwrite; store keyed `(tenant_id,
  scenario_id, manifest_id, state_model_id, transition_id)`, listing
  sorted `(manifest_id, state_model_id, transition_id)`, no
  update/delete/replace surface.
- The transition is never executed or interpreted: guards are never
  evaluated and targets are never applied - no state mutation,
  transition execution, simulation, outcomes, evidence,
  recommendations, or real-world actions.

### World compiler (`kalhas/application/world_compiler.py`)

- `content_hash`/`compile_world` gained `transitions=()`. Snapshots
  land under `world["domain_state_transitions"]` with the manifest
  count `state["declared_domain_state_transition_count"]` - both added
  **only when non-empty**, so transition-free worlds compile
  byte-identically to Phase 11 and worlds compiled before Phase 12
  remain unchanged.
- Canonicalization inside the compiler: transitions by
  `(manifest_id, state_model_id, transition_id)`, guard/target mappings
  by field identifier (defense in depth, so even a hand-built
  non-canonical transition compiles to the same hash as its canonical
  equivalent). Adding a transition changes the newly compiled world
  hash; the compiler never evaluates a guard or applies a target state
  patch. Campaign planning, input integrity, structural execution,
  replay, and event semantics are untouched - the snapshot flows
  through the immutable world/hash chain.

### API

`POST /v1/scenarios/{scenario_id}/domain-state-transitions` (201; body
accepts only `manifest_id`, `state_model_id`, `transition_id`,
`description`, `guard_values`, `target_values`, `declared_at`, optional
`metadata` - `extra="forbid"`; 404 unknown/foreign
scenario·binding·manifest·state-model; 409 duplicate; 409
`integrity_error`; 422 invalid values) and `GET
/v1/scenarios/{scenario_id}/domain-state-transitions` (typed envelope,
deterministic `(manifest_id, state_model_id, transition_id)` order; 404
unknown/foreign scenario). All X-Tenant-ID scoped.

### Operational activity and Colony

- New kind `domain_state_transition_declared` (twelfth): exactly one
  event per successful declaration with a safe payload
  (`state_model_id`, `transition_id`, `content_hash`,
  `guard_field_count`, `target_field_count`) and
  scenario/manifest/binding references - never descriptions, guard
  values, target values, metadata, or state-field values; rejected
  operations append nothing.
- Colony maps the new kind to the existing **Domain Registry** zone
  with no new request, timer, stream, or mutation capability: strictly
  read-only, manual-pull, same-origin, `textContent`-only rendering
  unchanged.

### Limitation

Phase 12 is **declarative transition-specification registration and
world snapshotting only** - there is still no transition engine, state
mutation, simulation mechanism, outcome generation, or decision engine.
Guards are never evaluated and targets are never applied; a future
generic simulation runtime may consume this data-only foundation.

## Phase 13: pure deterministic state-transition evaluation kernel

### Engine (`kalhas/application/state_transition_engine.py`)

The first evaluation semantics in KALHAS: a focused, domain-neutral,
application-layer engine that evaluates an **explicitly supplied,
ordered sequence** of `DomainStateTransition` specifications against one
immutable `DomainStateModel`. It is a deterministic kernel, not a
simulation scheduler.

- `derive_initial_state(model)` - initial state derived **only** from
  `state_fields[].initial_value`, keyed by field identifier in canonical
  order (deep-copied nested values - callers can never mutate model-owned
  data through the returned mapping; the immutable *result* snapshots are
  deep-frozen separately by the engine).
- `validate_state(state, model)` - rejects unknown keys, missing
  required keys, values not exactly matching the field's
  `StateValueKind` (booleans never accepted as integer/number; nested
  NaN/Infinity rejected everywhere), and values outside the field's
  declared `allowed_values` (canonical JSON equality) via
  `StateValidationError`.
- `evaluate_trajectory(model, transitions, *, max_attempts=1000)` -
  verifies the model's own content hash, verifies **every** transition
  belongs to the supplied model up front (copied ownership/identity
  fields - tenant, scenario, binding, pack id, pack version, manifest,
  state-model - plus the authoritative content hashes: manifest content
  hash, state-model content hash, and the transition's own recomputed
  content hash; any mismatch - including mixed-model sequences - raises
  `TransitionModelMismatchError` before any evaluation), and every
  transition specification is validated up front (non-empty targets,
  existing guard/target keys, exact value kinds, allowed values, no
  nested non-finite values; violations raise
  `InvalidTransitionSpecificationError` before any evaluation - an
  invalid specification can never be silently recorded as
  `guard_not_satisfied`), then evaluates
  strictly in caller order: validate current
  state → evaluate the guard as **exact canonical equality** over its
  declared `guard_values` → on match apply **only** the declared
  `target_values` as a copy-on-write patch and re-validate the applied
  state; on mismatch return the unchanged state with outcome
  `guard_not_satisfied`. Inputs are never mutated; transitions are never
  chosen, reordered, searched, prioritized, or looped; strategy policies
  are never inspected and domain packs are never invoked.
- Trajectory bounds: a sequence longer than `max_attempts` raises
  `TrajectoryLimitExceededError` up front (never a partial trajectory);
  a non-positive bound raises `InvalidTrajectoryLimitError`; an empty
  sequence is valid and returns the initial state unchanged.

### Result records

Frozen dataclasses (project style, like `CompiledWorld`):
`TransitionAttempt` (sequence position, transition id, transition
content hash, outcome `applied` | `guard_not_satisfied`, before/after
state hashes) and `TrajectoryEvaluation` (state model id, initial state
and hash, ordered attempts, final state and hash, deterministic
`trace_hash` over the canonical serialization of the ordered attempt
records). The `initial_state`/`final_state` snapshots are
**deep-frozen immutable**: every nested mapping and array is read-only
(assignment raises `TypeError`/`AttributeError`), no snapshot shares
mutable nested references with the model's declared initial values, any
transition's guard/target values, or the engine's working state, and the
snapshots compare, hash, and validate identically to their plain JSON
equivalents (`derive_initial_state` deep-copies nested initial values so
callers can never mutate model-owned data through it). No
human-language explanations, no hidden reasoning, and no guard/target
values in the records; the results are never exposed through operational
activity events or Colony.

### Hashing and determinism

State snapshots and trace entries use the repository's canonical JSON
conventions (sorted keys, no insignificant whitespace, SHA-256). Guard
canonical equality distinguishes `1` from `1.0` (canonically distinct)
and treats nested dict key order as irrelevant. Equivalent maps with
different insertion order yield identical state hashes, trace hashes,
and evaluation results.

### Scope (explicit non-goals)

Application-layer only: **no HTTP routes and no OpenAPI surface**, **no
store methods**, **no operational activity kinds**, **no Colony UI
behavior**, **no world compiler changes**, **no campaign/run/replay
integration**, and **no automatic execution from compiled worlds** - the
caller must explicitly provide the ordered transition sequence. The
engine does not select transitions, create outcomes, evidence,
recommendations, briefs, probabilities, or hidden reasoning, does not
execute real-world actions, and leaves the structural runtime's three
events unchanged.

### Limitation

Phase 13 is a **pure evaluation kernel only**: it computes what an
explicitly supplied transition sequence *would* do to a declaratively
defined state. There is still no automatic scheduling, no
campaign/run/replay integration, no simulation mechanism, no outcome
generation, and no decision engine.

## Phase 14: immutable store snapshot isolation + compiled-world content integrity

### The store snapshot-isolation boundary (`in_memory_store.py`)

The store is now a **deep-copy boundary** for every contract family it
stores, through one generic helper: `_deep_copy_contract(value)` uses
the contract's native `model_copy(deep=True)` when available (every
stored contract is a Pydantic model) and falls back to `copy.deepcopy`
otherwise.

- **Defensive copying on writes**: every `put_*` stores a deep copy of
  the supplied contract; tuple collections (run plans, strategy
  candidates, run events) are deep-copied item by item.
- **Defensive copying on reads**: every `get_*`/`list_*` returns a
  fresh deep copy, including each item of listed tuples;
  `append_operational_activity` stores **and** returns copies.
- **Why frozen Pydantic models alone do not protect nested mutable
  values**: `frozen=True` (and `extra="forbid"`) only reject attribute
  assignment and unknown fields on the model object itself. The nested
  `dict`/`list` values a contract carries (world body, `metadata`,
  activity `payload`, guard/target mappings, state fields) remain plain
  mutable references, so `world.world["scenario"]["name"] = X` or
  `payload["metric"]["value"] = 999` on a retrieved contract would
  mutate shared storage. The store's deep-copy boundary is what makes
  stored state immutable end-to-end.
- **Explicit lifecycle methods remain the only status-replacement
  paths**: `update_campaign_status` and `put_run_status` (both
  deep-copying) are the sole ways stored statuses change; public
  retrieved objects cannot be used to corrupt storage, and test-only
  corruption uses deliberate private-dictionary injection
  (`store._worlds[(tenant, world_id)].world[...] = ...`).

### The deterministic compiled-world integrity verifier (`world_integrity.py`)

`verify_world_snapshot(world, manifest)` proves a stored `WorldVersion`
and its `WorldManifest` still exactly represent the compiler's
deterministic output. It is pure, read-only, and deterministic, and it
reuses `world_compiler` **exclusively** - the private
`_canonical_bindings`/`_canonical_declarations`/
`_canonical_state_models`/`_canonical_transitions` helpers for
canonical-order checks and `compile_world` for full recompilation
(never a second hash algorithm). Check order is deterministic:

1. **Identity checks**: world tenant == manifest tenant; world
   identifier == `world-{content_hash[:16]}`; manifest identifier ==
   `manifest-{content_hash[:16]}`; manifest `world_version_id` == world
   identifier; world `compiler_version` == `COMPILER_VERSION`.
2. **Structural checks**: all compiler-owned body keys present, no
   unexpected keys; body `content_hash`/`compiler_version` match the
   contract fields.
3. **Embedded scenario**: strict `ScenarioSpec` parse; tenant,
   identifier, and `created_at` match the world's provenance fields.
4. **Embedded snapshot families**: bindings, capability declarations,
   state models, and transitions each parse strictly as their
   contracts (absent key = empty collection; non-list or any
   `ValidationError` = malformed).
5. **Canonical-order checks**: each parsed family must equal the
   compiler's canonical ordering of itself (bindings by manifest id;
   declarations by manifest then capability id; state models by
   manifest then state-model id; transitions by manifest, state model,
   then transition id) - reordered multi-element collections are
   rejected.
6. **Recompilation checks**: `compile_world` with the recorded
   compiler version must reproduce the stored world **and** the stored
   manifest exactly - equality subsumes content hash, identifiers,
   byte-identical body, and manifest counts/state/metadata. A scenario
   the compiler refuses is rejected as semantically invalid.

Every failure raises `WorldSnapshotIntegrityError` (mapped to the
existing 409 `INTEGRITY_ERROR` in `kalhas/api/errors.py`, no route
changes). The public message is generic ("Stored world '...' failed
integrity verification and was rejected") - never hashes, embedded
state, metadata, or raw values; the internal `reason` names only the
violated rule. There is **no repair, normalization, replacement, or
silent acceptance** of corrupted worlds.

### Integration points

- **Before LEGION**: `prepare_campaign` verifies the world after the
  world/scenario match and **before** `legion.request_strategies` and
  before any campaign/run write; a missing manifest is an integrity
  error (not 404), and a failed verification writes no campaign/run
  state.
- **Execution and replay input trust**: `verify_run_inputs` verifies
  right after the world identity checks and **before** input-hash
  recomputation; structural execution inherits it via its atomic
  preflight (zero runs, zero events, all statuses PLANNED, campaign
  stays RUNNING) and replay inherits it (no replay manifest is created
  after failed verification).
- **NEXUS-facing reads**: `MockNexusAdapter.world()` and `.manifest()`
  verify before returning, so `GET /v1/worlds/{id}` (which flows
  through `adapter.world`) never returns a corrupted world or manifest.

### Explicit limitations and non-goals

Phase 14 does **not** integrate the Phase 13 trajectory engine into
campaigns or runs; does **not** add strategy trajectory plans; does
**not** add new HTTP routes or contracts; does **not** add operational
activity kinds or Colony behavior; does **not** add external services or
network calls; and adds **no domain-specific logic**. No v1 contract or
generated schema changed, and every previously compiled world remains
valid with a byte-identical content hash (all stored worlds are
compiler outputs).

## Phase 15: immutable strategy-bound trajectory plans

### Contracts (`kalhas/contracts/v1/trajectory.py`, four new types)

All frozen, `extra="forbid"`; two are VersionedContracts registered in
`PUBLIC_CONTRACTS` (26 -> **28**, two new schema artifacts exported):

- **`StrategyTrajectoryTransitionReference`** - one authoritative
  reference to a declared transition: `sequence_position` (ge=0),
  `transition_identifier`, `transition_id`, `transition_content_hash`.
  No guard/target values, state snapshots, outcomes, evidence, or
  executable behavior; repetitions allowed and significant.
- **`StrategyTrajectoryPlanRequest`** (VersionedContract) - the
  authoritative KALHAS-built request: campaign/scenario/world identity,
  `world_content_hash`, exact stored `StrategyCandidate` snapshot +
  full content hash, exact `DomainStateModel` from the compiled world,
  non-empty canonical `available_transitions` tuple, `requested_at`.
  Its deterministic identifier (`trajectory-request-` prefix) is derived
  by KALHAS from the canonical campaign/world/strategy/state-model
  identity; LEGION never supplies it.
- **`StrategyTrajectoryPlanDraft`** (plain model) - the **untrusted**
  proposal: `request_id` + `ordered_transition_identifiers` (min 1,
  max 1000). Cannot carry tenant identity, hashes, plan identifiers,
  state values, callbacks, expressions, code, providers, or metadata;
  the service re-validates it even when built through
  `model_construct`/`model_copy` (validator-bypassing paths).
- **`StrategyTrajectoryPlan`** (VersionedContract) - the immutable plan
  binding campaign, world (id + content hash), strategy candidate (id +
  full content hash), state model (manifest id + deterministic
  identifier + logical id + content hash), and the ordered transition
  references. `content_hash` covers the complete canonical plan
  excluding itself (order and repetitions significant); `planned_at` is
  the recorded campaign `created_at`.

### Planning service (`strategy_trajectory_service.py`)

- **Authoritative provenance**: plans are built exclusively from
  verified stored records - the exactly-COMPILED campaign, the
  Phase 14-verified world + manifest, the state models and transitions
  **embedded in the compiled world snapshot** (never live-registry
  declarations), and the exact stored strategy candidates in campaign
  order. Only compiled-world snapshots are authoritative.
- **Closed catalog validation**: `_closed_world_catalogs` requires
  every embedded transition to map to exactly one embedded state model
  by `(manifest_id, state_model_id, state_model_content_hash)`;
  deterministic identifiers (`state_model_identifier(...)` /
  `transition_identifier(...)`); no duplicate state-model identifiers,
  ownership keys, or transition identifiers; every non-empty matched
  catalog passes `validate_transition_catalog`. Models with zero
  transitions remain valid and are ignored. Orphan, ambiguous,
  duplicate, or identity-invalid snapshots fail **before the first
  LEGION call** with `WorldSnapshotIntegrityError` (generic public
  message; no raw hashes, guards, targets, or state values). The **same
  closed construction** is used for stored-plan retrieval verification.
- **Exact run-plan preflight**: stored strategy candidates must equal
  `campaign.strategy_candidate_ids` exactly (same ids, same order;
  missing/duplicate/reordered/additional candidates rejected) and the
  stored run-plan tuple must equal the deterministic `plan_runs`
  recomputation exactly (campaign, verified world content hash, exact
  stored strategies, campaign seed ensemble, `campaign.created_at`,
  existing runtime version) - then `verify_run_inputs` per expected
  run. All before LEGION; no lifecycle or integrity manifest writes.
- **Exact matrix**: exactly one plan per campaign strategy candidate (in
  campaign order) x transition-capable state model (in compiled-world
  canonical order). The LEGION-proposed sequence is preserved exactly,
  including repetitions - never selected, sorted, deduplicated, or
  reordered. The draft's `request_id` must equal the authoritative
  request identifier; every proposed identifier must be in the model's
  available catalog.
- **Boundary isolation**: the authoritative request snapshot never
  crosses the adapter boundary; `legion.request_trajectory_plan`
  receives a disposable deep copy, and after the adapter returns plan
  construction reads only the authoritative request and the
  authoritative stored records. Hostile boundary-request copies are
  disposable and never authoritative.
- **Atomic all-or-nothing preparation**: the complete matrix is
  validated before the first put; any invalid draft or adapter failure
  stores zero plans. A second preparation - including of an
  already-prepared **empty tuple** - raises
  `TrajectoryPlansAlreadyPreparedError` before any new LEGION call;
  existing storage is never overwritten or repaired.
- **Immutable store snapshot isolation**: `put_*`/`get_*` keep the
  Phase 14 deep-copy boundary on the whole tuple; a successfully
  prepared empty tuple is a stored value distinguishable from "not
  prepared" (`TrajectoryPlansNotFoundError`).
- **Collection-level stored-plan verification**: the stored collection
  is verified as a whole - exact length, no duplicate identifiers, no
  duplicate (strategy, state model) pairs, exact expected pair set,
  exact tuple ordering, every `planned_at` equal to `campaign.created_at`,
  plus per-plan identity/hash/reference checks against the closed
  world catalog. Stored plans are strictly revalidated against their
  complete contract, including nested reference types and the 1-1000
  reference bound, before any identity, hash, or matrix verification.
  For a world with no transition-capable models the only
  valid stored collection is exactly the prepared empty tuple. Any
  tampered collection raises `StoredTrajectoryPlanIntegrityError` -
  never repaired, sorted, normalized, or replaced.
- **No trajectory execution**: nothing in this phase evaluates or
  executes a trajectory; the planning service never calls
  `evaluate_trajectory` (boundary test proves it with an AST call scan).

### Explicit non-goals

No campaign/run engine integration; no structural runtime changes (the
three run events are unchanged); no new run events; no
`RunPlan`/`ReplayManifest` changes; no HTTP/OpenAPI routes; no
operational-activity kind; no Colony changes; no outcomes/evidence/
recommendations; no external LEGION implementation; no network or
providers; no domain-specific logic; no dependency changes.

## Phase 16: deterministic run trajectory execution and exact replay

### Runtime versioning (`run_planner.py`)

`LEGACY_STRUCTURAL_RUNTIME_VERSION = "1.0.0"` is the established
structural-only runtime; `TRAJECTORY_RUNTIME_VERSION = "2.0.0"` is the
trajectory-enabled runtime; `RUNTIME_VERSION = TRAJECTORY_RUNTIME_VERSION`
makes **new campaign/run planning default to 2.0.0**. Runtime selection
derives **only** from the recorded `RunPlan`/`RunStatus` - no caller may
override runtime behavior by supplying synthetic objects
(`execute_run(store, tenant_id, run_id)` and
`replay_run(store, tenant_id, run_id)` accept no plans, models,
transitions, or artifacts). Recorded 1.0.0 runs execute and replay under
the exact legacy structural-only behavior (same three events, same event
hash, PLANNED -> RUNNING -> COMPLETE, no trajectory execution artifact,
no trajectory plans required or consumed); 2.0.0 runs use the Phase 16
trajectory runtime; any other recorded version fails with a typed
`UnsupportedRuntimeVersionError` **before** any lifecycle change or
replay regeneration. The Phase 15 planning preflight now rejects legacy
or unsupported campaign run matrices with a typed error before any
LEGION call (never an obscure matrix mismatch).

### New contracts (`kalhas/contracts/v1/trajectory_execution.py`)

All frozen, `extra="forbid"`; the two VersionedContracts are registered
in `PUBLIC_CONTRACTS` (28 -> **30**), with two new schema artifacts
(`RunTrajectoryExecution.schema.json`,
`RunTrajectoryReplayManifest.schema.json`):

- **`RunTrajectoryAttemptRecord`** - one deterministic attempt:
  `sequence_position` (ge=0), `transition_identifier`, `transition_id`,
  `transition_content_hash`, `outcome` (`"applied"` |
  `"guard_not_satisfied"`), `before_state_hash`, `after_state_hash`. No
  guard/target values, explanations, evidence, or policy content.
- **`RunStateTrajectoryResult`** - one evaluated state-model plan:
  `trajectory_plan_id` + `trajectory_plan_content_hash`, `manifest_id`,
  `state_model_identifier`, `state_model_id`,
  `state_model_content_hash`, plain JSON `initial_state` +
  `initial_state_hash`, ordered `attempts`, plain JSON `final_state` +
  `final_state_hash`, `trace_hash`, self-covering `content_hash`
  (complete canonical result excluding itself).
- **`RunTrajectoryExecution`** (VersionedContract) - the immutable
  run-scoped artifact: `run_id`, `campaign_id`, `run_plan_id`,
  `world_version_id` + `world_content_hash`, `strategy_candidate_id` +
  `strategy_content_hash`, `scenario_seed_id` (recorded provenance
  only), `runtime_version: Literal["2.0.0"]`, `input_hash`, exact
  ordered `trajectory_plan_set_hash`, ordered `results`, aggregate
  `content_hash`, `executed_at` (the recorded RunPlan `created_at`,
  never wall clock). The deterministic identifier is derived from the
  run identity and runtime version
  (`trajectory-execution-{sha256(run_id, runtime_version)[:16]}`). An
  empty results tuple is valid only for a verified world with no
  transition-capable state models.
- **`RunTrajectoryReplayManifest`** (VersionedContract) - exact-replay
  attestation: run/campaign identity, `run_trajectory_execution_id`,
  world/strategy/seed identities, runtime literal, `input_hash`,
  `trajectory_plan_set_hash`, `expected_execution_hash` ==
  `recomputed_execution_hash` == the authoritative execution content
  hash, `replay_classification: "exact"`, deterministic `replayed_at`.

No existing v1 contract field was modified.

### Pure execution builder (`run_trajectory_runtime.py`)

`build_run_trajectory_execution(*, inputs: VerifiedRunInputs, plans,
catalogs)` is store-free and receives only already verified
authoritative records. It (1) requires runtime 2.0.0; (2) requires every
plan's strategy identity and content hash to match the verified run
strategy; (3) preserves the campaign plan/state-model canonical order
(exact (strategy, model) pair match against the closed catalogs); (4)
resolves each plan's references only against its exact verified world
catalog (model identity, transition membership, transition id, content
hash); (5) preserves repetitions and explicit ordering exactly; (6)
calls `evaluate_trajectory` once per applicable plan; (7) converts the
engine's deep-frozen snapshots to fresh detached plain JSON via the new
public engine helper `state_to_plain_json`; (8) zips each engine attempt
with its authoritative plan reference, verifying position, transition
id, and content hash; (9) builds `RunTrajectoryAttemptRecord`s; (10)
builds and hashes each `RunStateTrajectoryResult`; (11) builds and
hashes the aggregate `RunTrajectoryExecution`; (12) uses
`run_plan.created_at` as `executed_at`; (13) carries the recorded seed
identity in provenance without pretending the kernel samples it; (14)
never mutates engine results, plans, models, transitions, world data, or
stored inputs. Hash rules: `trajectory_plan_set_hash` (canonical digest
of the complete ordered plan tuple), result/execution content hashes
(canonical dump minus the hash field), deterministic execution
identifier. The engine's evaluation semantics are never duplicated.

### Run input resolution (`run_trajectory_inputs.py`)

`verify_run_trajectory_inputs(*, store, tenant_id, run_id)` calls
`verify_run_inputs` first, then branches only on the recorded runtime
version. For 2.0.0: the complete trajectory collection is loaded through
the Phase 15 service getter (collection-level integrity - matrix
length/order, unique identifiers and pairs, per-plan identity/hash,
closed-catalog reference membership), the same closed compiled-world
catalogs are built, and exactly the plans whose
`strategy_candidate_id` matches the run's strategy are selected - one
per transition-capable state model in canonical order; missing,
additional, duplicated, reordered, foreign, or mismatched plans are
rejected. A transition-capable world without a prepared collection
raises `TrajectoryPlansRequiredError`; a world with no transition-capable
models resolves an empty tuple whether the collection is absent or the
successfully prepared empty tuple (a non-empty unexpected collection is
rejected); 1.0.0 runs never consume plans; unsupported versions are
rejected safely. The verifier is read-only and never evaluates anything.

### Execution (`structural_runtime.py`) and campaign atomicity

Legacy 1.0.0 execution is byte-identical to before. Trajectory 2.0.0
execution, **before the first lifecycle write**: verifies run inputs,
verifies and resolves the exact trajectory plans/catalogs, ensures no
trajectory execution artifact already exists, evaluates every applicable
plan in memory, and builds + fully validates the complete
`RunTrajectoryExecution`. Only after all evaluation succeeds are the
integrity manifest recorded, the run transitioned RUNNING, the same
three structural events generated and stored, the execution artifact
stored, and the run transitioned COMPLETE with the existing structural
event hash. The structural event stream remains **exactly three events**
(`RUN_STARTED`, `STRATEGY_DECLARATION_RECORDED`, `RUN_COMPLETED`) with
unchanged ordering and kinds; no transition attempts enter `RunEvent`;
no raw states, guards, or target values enter event payloads; and
`RunStatus.event_hash` stays the structural-event hash - the trajectory
execution has its own independent content hash that never feeds the
event stream. On any trajectory input/evaluation/contract/hash failure
the run remains PLANNED, zero events and zero artifacts are written, the
run is not marked FAILED, and the typed error is raised.

`execute_campaign` performs a **campaign-wide atomic preflight** before
the first run: every existing run's inputs are verified as today, every
2.0.0 run's trajectory inputs are resolved, its expected
`RunTrajectoryExecution` is built fully in memory, and no unexpected
pre-existing artifact may exist. If any run fails preflight, zero runs
execute, zero events and zero trajectory artifacts are written, every
status stays PLANNED, the campaign stays RUNNING, and the typed error is
raised. After a successful preflight runs execute in the existing
deterministic stored order; the per-run `execute_run` still
independently reloads and verifies stored inputs rather than accepting
preflight objects.

### Exact replay (`replay_service.py`)

`replay_run` keeps its signature and return type (`ReplayManifest`).
Legacy 1.0.0 replay is exactly as before (regenerate the three
structural events, compare the structural event hash, create and store
the existing `ReplayManifest`; no trajectory replay manifest required or
created). Trajectory 2.0.0 replay, **before writing either replay
manifest**: (1) verifies recorded run inputs; (2) verifies the stored
`RunTrajectoryExecution` - contract revalidation, deterministic
identifier, ownership, runtime, input hash, plan-set hash, content
hash; (3) reloads and verifies the current immutable trajectory-plan
collection; (4) resolves the same closed compiled-world catalogs; (5)
regenerates the complete expected execution through the pure builder;
(6) requires exact full-object and exact content-hash equality with the
stored authoritative artifact; (7) regenerates and verifies the three
structural events as today; (8) builds the `RunTrajectoryReplayManifest`
with expected == recomputed hash and classification "exact". Only after
every structural and trajectory check succeeds are the existing
`ReplayManifest` and the `RunTrajectoryReplayManifest` stored and the
existing manifest returned. Replay never reads cached trajectory results
as its regenerated output - it compares independently regenerated output
against the stored authoritative artifact. On mismatch a typed
`TrajectoryReplayMismatchError` (or execution-integrity error) is
raised, neither replay manifest is created, and no state values or
hashes are exposed publicly. No LEGION, NEXUS, domain pack, provider,
network, randomness, or wall clock is used during replay.

### Store isolation and integrity verification

`InMemoryScenarioStore` gains deep-copy-isolated immutable collections
keyed by (tenant, run) for `RunTrajectoryExecution` and
`RunTrajectoryReplayManifest`: strict contract revalidation on write
(serializer-based strict revalidation defeats `model_copy`/
`model_construct`/private-injection bypass), deep defensive copies on
write and read, identical second writes accepted idempotently while a
differing artifact never replaces the original
(`RunTrajectoryExecutionAlreadyExistsError` /
`RunTrajectoryReplayManifestConflictError`), foreign-tenant access
indistinguishable from missing, and no update/delete/repair surface.
`kalhas/application/trajectory_integrity.py` verifies stored records
strictly: complete contract revalidation, deterministic identifiers,
tenant/run/campaign/run-plan/world/strategy/seed/runtime ownership,
world and strategy content hashes, input hash, exact ordered plan-set
hash, exact result count and canonical state-model order, per-result
plan/model identity and content hash, initial/final state hashes,
attempt positions and authoritative transition references, trace
hashes, result content hashes, the aggregate execution content hash,
`executed_at`/`replayed_at` from the RunPlan `created_at`, and replay
expected/recomputed hashes equal to the authoritative execution hash.
Tampered records are never repaired, normalized, replaced, or silently
accepted.

### Seed, events, and explicit non-goals

The recorded seed identity is included in the execution artifact's
provenance (`scenario_seed_id`), the execution identifier, and the run
input hash, but the **current declarative transition kernel does not
sample or use the seed** - recorded provenance only. Phase 16 adds no
new `RunEvent` kinds, no transition-attempt `RunEvent`s, no outcomes,
evidence, DecisionBriefs, rankings, or recommendations, no uncertainty
sampling, no automatic transition selection, no domain-pack execution,
no real LEGION/NEXUS integration, no HTTP/OpenAPI paths (the new typed
errors surface through the existing error envelope: 409
`conflict`/`integrity_error` for unsupported/required-plans/lifecycle
and integrity failures, 404 not-found for missing records; trajectory
states never appear in API responses), no operational-activity kinds,
no Colony behavior, no external services/providers/network, no
filesystem or database, no new dependencies, and no domain-specific
logic.

## Phase 17: verified trajectory artifact inspection (read-only)

Phase 17 adds a strictly read-only, tenant-scoped inspection surface
over the Phase 16 artifacts: a focused application query service and
two new v1 HTTP GET endpoints. It exposes existing authoritative
artifacts only - no new simulation semantics, no execution or replay
during reads, no outcomes/evidence/recommendations, no lifecycle
changes, no new contracts or schema artifacts (`PUBLIC_CONTRACTS` stays
**30**).

### Application query service (`kalhas/application/trajectory_query_service.py`)

Two explicit, keyword-only functions:

- `get_verified_run_trajectory_execution(*, store, tenant_id, run_id)`
  -> `RunTrajectoryExecution`
- `get_verified_run_trajectory_replay_manifest(*, store, tenant_id, run_id)`
  -> `RunTrajectoryReplayManifest`

Both: (1) call `verify_run_trajectory_inputs` - the recorded run inputs
are loaded and verified (run status/plan/campaign/world/strategy/seed/
runtime/input hash) and the exact applicable trajectory plans and closed
compiled-world catalogs are resolved, branching only on the recorded
runtime version; (2) load the stored artifact through the store's
deep-copy snapshot-isolation boundary (never trusted by reference); (3)
verify it with the **existing Phase 16 verifiers** -
`verify_run_trajectory_execution_record` for the execution; the
replay-manifest query first loads and verifies the authoritative
`RunTrajectoryExecution`, then verifies the manifest with
`verify_run_trajectory_replay_manifest_record` against the authoritative
execution and the exact ordered trajectory plan-set hash. Only a
completely verified artifact is returned. The service is deterministic
and read-only: no FastAPI dependency, no LEGION/NEXUS calls or imports,
no domain-pack loading or execution, no wall clock, randomness,
filesystem, database, provider, or network access, and no mutation of
stored or returned authoritative inputs. It never calls
`build_run_trajectory_execution`, `replay_run`, `evaluate_trajectory`,
or any store `put_*` surface, records no operational activity, and
changes no lifecycle state; routes must use the service rather than
returning raw store values.

### Endpoints

| Method | Path | Response model |
| --- | --- | --- |
| GET | `/v1/runs/{run_id}/trajectory-execution` | existing `RunTrajectoryExecution` |
| GET | `/v1/runs/{run_id}/trajectory-replay-manifest` | existing `RunTrajectoryReplayManifest` |

Both are X-Tenant-ID scoped. **Retrieval versus execution/replay**: the
execution GET never rebuilds the execution from inputs; the replay-
manifest GET retrieves an already-created manifest and never triggers
`replay_run`, evaluation, artifact regeneration, or any write - a run
that has not been replayed yet returns the typed 404 and nothing is
created. **Tenant isolation**: foreign-tenant access is indistinguishable
from a missing artifact (the same typed 404). **Integrity before
response**: missing/legacy/not-yet-created artifacts return the typed
404 `not_found`; corrupted execution records return the existing safe
409 `integrity_error`; corrupted replay manifests preserve the existing
typed 409 `conflict` mapping; unsupported recorded runtime versions
return the typed 409 `conflict`. Public error responses never expose
internal verification reasons, raw hashes, state values, transition
guards/targets, strategy policy content, or validator diagnostics;
request IDs and the single `ApiErrorResponse` envelope are unchanged.
**Intentional exposure**: the execution response carries the
contract-declared `initial_state`/`final_state` snapshots and hashes
exactly as the frozen contract declares them - guards, target values,
strategy policy content, hidden reasoning, evidence, and recommendations
are never added (the contract has no such fields).

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

## Phase 18: deterministic campaign trajectory matrix

### Purpose

The campaign trajectory matrix is the **structural comparison
provenance** of one completed runtime-2.0.0 campaign: the exact
authoritative strategy x shared-seed run matrix assembled from every
verified `RunTrajectoryExecution` of that campaign. It proves that every
strategy was executed under the campaign's identical ordered seed
conditions and provides verified references and integrity hashes for
every run. It is **not performance evaluation**: it never ranks
strategies, calculates scores, interprets state values, or produces
outcomes, evidence, or recommendations.

### New contracts (`kalhas/contracts/v1/campaign_trajectory.py`)

`CampaignTrajectoryRunCell` (frozen, strict, `extra="forbid"`, NOT
registered in PUBLIC_CONTRACTS) - one run of the matrix, carrying
references and integrity hashes only:

- `sequence_position` / `strategy_position` / `seed_position`
  (int, ge=0) - the run's position in the matrix and its strategy/seed
  indices;
- `run_id`, `run_plan_id`, `strategy_candidate_id`, `scenario_seed_id`
  (non-empty strings) - the exact recorded identities;
- `input_hash` (SHA-256 pattern) - the run's recorded input hash;
- `trajectory_execution_id`, `trajectory_execution_content_hash`,
  `trajectory_plan_set_hash` (SHA-256 patterns) - the verified
  Phase 16 artifact reference and its exact ordered plan-set hash;
- `result_content_hashes` (ordered tuple of SHA-256) - the execution's
  canonical result hashes, preserved exactly.

No state snapshots, transition guards or target values, strategy policy
content, outcome values, evidence, ranking/score, or explanations are
representable.

`CampaignTrajectoryMatrix` (frozen, strict VersionedContract,
registered - PUBLIC_CONTRACTS 30 -> **31**):

- `campaign_id`, `scenario_id`, `world_version_id`,
  `world_content_hash` - campaign/world identity;
- `runtime_version: Literal["2.0.0"]` and
  `comparison_mode: Literal["identical_conditions"]` (both emit
  `"const"` in JSON Schema - inexpressible otherwise);
- `ordered_strategy_candidate_ids`, `ordered_scenario_seed_ids`
  (non-empty tuples, unique) - the exact authoritative orders;
- `cells` (non-empty tuple of `CampaignTrajectoryRunCell`) - the
  complete Cartesian product in exact RunPlan order (strategy-major,
  seed-minor), verified by a model validator: count == product,
  unique position pairs, contiguous sequence positions, position-bound
  identities, strictly ascending pair order;
- `content_hash` (SHA-256) and `assembled_at` (AwareDatetime).

### Identifier and hash rules

- Identifier: `trajectory-matrix-{sha256(canonical_json({"campaign_id",
  "world_version_id", "runtime_version"}))[:16]}` - deterministic from
  campaign identity, world identity, and runtime version, with a
  distinct readable prefix.
- `content_hash`: SHA-256 over the complete canonical matrix
  serialization (sorted keys, no insignificant whitespace) excluding
  `content_hash` itself; computed by the pure builder with the
  placeholder-then-finalize pattern.
- `assembled_at`: the recorded campaign `created_at` - never the wall
  clock.
- All hashes use the repository's canonical JSON + SHA-256 helpers only.

### Pure builder (`kalhas/application/campaign_trajectory_runtime.py`)

`build_campaign_trajectory_matrix(*, campaign, world, strategies,
seeds, run_plans, executions)` - store-free, mutation-free, and free of
execution/replay/evaluation/outcome behavior. It requires every plan to
record runtime 2.0.0 (else `UnsupportedRuntimeVersionError`), verifies
the exact campaign strategy order and shared seed order, requires the
exact complete strategy x seed matrix in the exact stored RunPlan order
(missing/additional/duplicated/reordered/foreign runs rejected with
`CampaignTrajectoryMatrixIntegrityError`), recomputes every run input
hash via the existing `run_input_hash` helper, binds every cell to its
exact RunPlan and verified execution (all run/campaign/world/strategy/
seed/input identities verified, including the execution's strategy
content hash), preserves ordered result content hashes exactly, and
derives the deterministic identifier, `assembled_at`, and canonical
content hash. The previously private authoritative run-plan matrix
preflight was extracted to the public `preflight_run_plan_matrix`
(`_preflight_run_plan_matrix` kept as an alias; behavior unchanged,
regression-tested).

### Verified query pipeline (`kalhas/application/campaign_trajectory_query_service.py`)

`get_verified_campaign_trajectory_matrix(*, store, tenant_id,
campaign_id) -> CampaignTrajectoryMatrix`:

1. tenant-scoped campaign + status (unknown/foreign -> typed 404);
2. exactly COMPLETE required (`CampaignNotCompleteError` -> 409
   `invalid_state`);
3. compiled world snapshot loaded and verified (`verify_world_snapshot`);
4. exact authoritative strategy candidates, campaign seed ensemble, and
   ordered RunPlan matrix verified via the existing
   `preflight_run_plan_matrix` (legacy/unsupported recorded runtime ->
   `UnsupportedRuntimeVersionError` -> 409 `conflict`; corrupted
   records -> typed 409 `integrity_error`);
5. every run's execution verified through the existing Phase 17
   verified execution query path; missing executions, missing run
   records, missing/corrupted trajectory-plan collections inside a
   COMPLETE campaign raise `CampaignTrajectoryMatrixIntegrityError` ->
   409 `integrity_error` (corrupted execution records fail through the
   existing `RunTrajectoryExecutionIntegrityError` mapping);
6. the complete matrix is built in memory through the pure builder and
   returned **without being stored**; a partial matrix is never
   returned.

The query is deterministic, read-only, all-or-nothing, tenant-scoped,
deep-copy isolated, and free of FastAPI/NEXUS/LEGION/domain-pack/wall-
clock/randomness/filesystem/database/provider/network surface.

### Endpoint and error behavior

`GET /v1/campaigns/{campaign_id}/trajectory-matrix` - response model is
the exact `CampaignTrajectoryMatrix` (no wrapper). X-Tenant-ID is
authoritative. Error mappings (single `ApiErrorResponse` envelope,
request IDs preserved, no internal reasons/hashes/state values/guards/
targets/policy content/validator diagnostics leaked):

| Condition | Status / code |
| --- | --- |
| Unknown or foreign campaign | 404 `not_found` |
| Campaign not COMPLETE | 409 `invalid_state` |
| Legacy or unsupported recorded runtime | 409 `conflict` |
| Missing/inconsistent/corrupted matrix inputs or executions | 409 `integrity_error` |

The GET performs no write and creates no operational-activity event.

### Fair identical-condition invariants (structural)

comparison_mode is exactly `identical_conditions`; strategy order comes
from the authoritative campaign; seed order comes from the campaign's
shared seed ensemble; every strategy appears once for every seed with
the identical ordered seed identifiers; cells match the exact
authoritative RunPlan order; no sorting, normalization, repair,
replacement, or silent omission; matrix construction is atomic (one
invalid run means no matrix response); strategy performance is never
inferred from structural values.

### Explicit non-goals

No rankings/winners/losers/recommendations/scores/weights or strategy
comparisons; no OutcomeVector/EvidenceReference/DecisionBrief
production; no metric extraction or aggregation; no probability or
distribution claims; no state interpretation; no uncertainty sampling or
seed consumption; no automatic transition selection; no new runtime
versions; no new RunEvent kinds; no changes to the three structural
events or their event hash; no execution/replay side effects; no state
snapshots in the matrix contracts; no transition guards/targets or
policy content; no domain-specific vocabulary or logic; no domain-pack
loading/execution; no real NEXUS/LEGION integration; no
operational-activity kinds or writes; no Colony changes; no external
providers/network/filesystem/database persistence; no new dependencies;
no changes to AGENTS.md, global configuration, or unrelated skills; no
commits or pushes. Phase 19 has not been started.

### Status

All five gates green - full suite **1347 passed / 1 skipped / 1
warning** (the pre-existing Starlette/httpx deprecation warning only);
mypy clean (125 files); ruff check clean; `ruff format --check` clean
(134 files); schema export `--check` synced (new artifact
`CampaignTrajectoryMatrix.schema.json`; PUBLIC_CONTRACTS exactly 31;
no existing v1 contract field changed). New Phase 18 suites:
`tests/test_campaign_trajectory_contracts.py` (31),
`tests/test_campaign_trajectory_runtime.py` (29),
`tests/test_campaign_trajectory_query_service.py` (28),
`tests/test_api_phase18.py` (15), `tests/test_phase18_boundaries.py`
(14) - 117 new tests (plus 4 new parametrized contract cases in
tests/test_contracts.py); the two existing contract-count assertions
were updated 30 -> 31; the complete pre-Phase-18 suite remains green as
part of the full 1347-test regression run.

## Phase 19: immutable state-to-metric observation bindings

### Role (declaration only)

A `DomainMetricObservationBinding` is the immutable, declarative,
tenant-scoped connection between exactly one metric of a stored
`ScenarioSpec` and exactly one **numeric** field of an existing
scenario-bound `DomainStateModel`. It declares that a future phase *may*
observe the referenced field's final trajectory state as the metric's
raw observation - provenance and identity only. Phase 19 is
declaration, storage, world snapshotting, integrity verification, and
API management only; it explicitly does **not** inspect any
`RunTrajectoryExecution`, read `initial_state` or `final_state`, extract
metric values, evaluate trajectories, calculate outcomes, aggregate
observations, produce evidence, rank strategies, or generate
recommendations. The binding is deliberately distinct from observation
*extraction*: a binding is inert data that names *what could be
observed and from where*; the extraction of an actual value remains a
future phase's work.

### Contract and authoritative provenance

`DomainMetricObservationBinding` (32nd top-level contract; frozen
`VersionedContract`, `extra="forbid"`; `schemas/v1/DomainMetricObservationBinding.schema.json`;
PUBLIC_CONTRACTS 31 -> **32**; no existing v1 contract field changed):

- `scenario_id` (non-empty), `binding_id`, `manifest_id`, `pack_id`,
  `pack_version` (semver pattern), `manifest_content_hash` (lowercase
  SHA-256), `metric_id` (non-empty), `state_model_identifier`
  (deterministic `DomainStateModel` identifier), `state_model_id`
  (logical id), `state_model_content_hash` (lowercase SHA-256),
  `state_field_id` (non-empty), `state_field_value_kind` (literal
  `"integer"` | `"number"` only), `observation_point` (literal
  `"final_state"`, default), `content_hash` (lowercase SHA-256),
  `declared_at` (timezone-aware), `metadata` (JSON-compatible; non-finite
  floats rejected anywhere, including nested).
- The contract cannot express formulas, expressions, callbacks,
  transformations, scaling factors, aggregation implementations,
  executable references, provider references, observed values, state
  snapshots, outcomes, evidence, scores, or recommendations.
- Every authoritative identity field is copied exclusively from stored
  immutable records (scenario, binding, manifest, state model); the API
  draft `DomainMetricObservationDeclarationRequest` accepts only
  `manifest_id`, `state_model_id`, `metric_id`, `state_field_id`,
  `declared_at`, `metadata` - client-supplied tenant/scenario/binding/
  pack identity or version/manifest hash/model identifier or hash/
  value kind/observation point/identifier/content hash are rejected 422.
- Deterministic identifier:
  `observation-{sha256(canonical_json({tenant_id, scenario_id, metric_id,
  manifest_id, state_model_id, state_field_id, observation_point}))[:16]}`;
  `content_hash` = SHA-256 of the canonical serialized binding excluding
  `content_hash`. Metadata insertion order never affects the identifier
  or content hash.

### Declaration behavior (service)

`declare_domain_metric_observation(store, *, tenant_id, scenario_id,
manifest_id, state_model_id, metric_id, state_field_id, declared_at,
metadata)` in strict order:

1. Load the tenant-scoped stored `ScenarioSpec` (404 when unknown or
   foreign).
2. Require `metric_id` to identify exactly one declared scenario metric
   (0 or >1 -> typed 422).
3. Load the exact scenario-bound `DomainPackBinding` (404).
4. Load the exact `DomainStateModel` for `manifest_id` + `state_model_id`
   (404).
5. Verify the state model belongs to the same scenario, tenant, binding,
   manifest, pack identity/version, and authoritative manifest content
   hash (binding-integrity 9 checks + state-model-integrity 11 checks;
   any mismatch -> safe typed 409 `integrity_error`, generic message,
   internal `reason` only).
6. Resolve `state_field_id` against the exact state model (missing ->
   typed 422).
7. Require the field's authoritative `StateValueKind` to be numeric
   (`integer` or `number`); `string`, `boolean`, and `json` fields are
   rejected (typed 422).
8. Copy all authoritative identity/hash/value-kind fields from storage.
9. Set `observation_point` to exactly `"final_state"`.
10. Derive the deterministic identifier from the canonical identity.
11. Canonicalize metadata using repository conventions.
12. Compute `content_hash` over the complete canonical binding excluding
    `content_hash`.
13. Store only after complete validation; the service never loads,
    instantiates, imports, or executes a domain pack and never touches
    trajectory executions.

### Uniqueness (Phase 19 MVP)

Exactly one observation binding per scenario metric. A second
declaration for the same tenant + scenario + metric - even when it
points to a different state model or field - is rejected with a typed
409 `conflict` **before any write** and never overwrites, updates,
repairs, or replaces the original binding.

### Store boundary

`InMemoryScenarioStore` keeps the immutable tenant-scoped collection
keyed `(tenant_id, scenario_id, metric_id)`:

- deep defensive copies on write, read, and list (caller mutation and
  retrieved nested-metadata mutation cannot affect storage);
- strict complete contract revalidation before storage
  (`revalidate_stored_domain_metric_observation`: serializer-based
  strict revalidation rejects validator-bypassed contracts, foreign
  objects, and non-finite nested metadata);
- duplicate declarations and incorrect ownership keys rejected;
- deterministic listing order by `metric_id`;
- foreign-tenant access indistinguishable from missing;
- rejected writes leave storage byte-identical;
- no update/delete/repair surface.

### HTTP API and error mappings

`POST /v1/scenarios/{scenario_id}/metric-observations` (201, exact
`DomainMetricObservationBinding` response) and
`GET /v1/scenarios/{scenario_id}/metric-observations` (typed envelope
`{observations}`, deterministic metric-id order). X-Tenant-ID required
and authoritative on both. No update or delete endpoints.

| Condition | Status / code |
| --- | --- |
| Unknown or foreign scenario | 404 `not_found` |
| Unknown or foreign binding / manifest / state model | 404 `not_found` |
| Unknown scenario metric / state field | 422 `validation_error` |
| Non-numeric state field (string/boolean/json) | 422 `validation_error` |
| Request validation (extra fields, bad literals, non-finite metadata) | 422 `validation_error` |
| Duplicate declaration (same tenant/scenario/metric) | 409 `conflict` |
| Corrupted stored binding / inconsistent stored records | 409 `integrity_error` |

Public messages never expose raw hashes, state values, metadata values,
validator diagnostics, another tenant's records, or internal integrity
reasons; the single `ApiErrorResponse` envelope and request IDs are
unchanged. Declarations and listings create **no** operational-activity
events and no Colony changes.

### World compiler integration

`content_hash`/`compile_world` gained
`domain_metric_observations: tuple[DomainMetricObservationBinding, ...] = ()`:

- the `domain_metric_observations` world-body key, the hash-payload key,
  and `WorldManifest.state["declared_domain_metric_observation_count"]`
  appear **only when non-empty** - observation-free worlds compile
  byte-identically to the pre-Phase-19 compiler;
- canonical order by `metric_id` inside the compiler - caller/store
  insertion order never affects the world identifier, content hash,
  manifest, or embedded ordering;
- the complete serialized binding snapshots participate in the world
  content hash; changing the binding set changes the compiled world
  identifier/content hash;
- already compiled worlds remain immutable; declarations added after
  compilation affect only subsequently compiled worlds;
- the compiler never interprets or extracts a metric value and never
  reads trajectory executions;
- `MockNexusAdapter.compile_scenario` supplies the exact stored
  declaration collection.

### World-integrity verification

`verify_world_snapshot` recognizes the new compiler-owned key and:

- strictly parses each embedded binding through
  `DomainMetricObservationBinding` (foreign objects and
  validator-bypassed/malformed snapshots rejected);
- requires canonical metric-id ordering;
- rejects duplicate metric bindings;
- verifies tenant/scenario ownership;
- verifies metric existence against the embedded scenario snapshot
  (exactly one declaration);
- verifies the referenced `DomainStateModel` exists in the same compiled
  world with exact deterministic identifier, logical id, and content
  hash;
- verifies `state_field_id` exists;
- verifies the copied numeric value kind matches the authoritative model
  field;
- verifies the referenced pack binding/manifest identity against the
  compiled catalog (binding id, pack id/version, manifest content hash);
- recompiles from the exact parsed snapshots and requires exact
  `WorldVersion` and `WorldManifest` equality.

Corrupted storage is never repaired, normalized, reordered, or
replaced. `VerifiedWorldCatalog` gained the canonical
`domain_metric_observations` tuple (defaulted empty; immutable,
detached).

### Explicit non-goals

No metric-observation extraction; no `initial_state`/`final_state`
reads from trajectory executions; no metric values; no
`MetricOutcome`/`OutcomeVector` or `EvidenceReference`/`DecisionBrief`
production; no aggregation (mean/sum/min/max); no normalization or unit
conversion; no formulas, transformations, weights, scoring, ranking, or
recommendations; no uncertainty sampling; no seed consumption; no
automatic transition selection; no new runtime versions; no new
`RunEvent` kinds; no domain-specific vocabulary or logic; no domain-pack
execution; no real NEXUS/LEGION integration; no external
services/providers/network; no filesystem/database persistence; no
dependencies; no operational-activity kinds or writes; no Colony
changes; no changes to AGENTS.md, global configuration, or unrelated
skills; no commits or pushes. Runtime 1.0.0/2.0.0 behavior, RunPlan
generation, campaign lifecycle, trajectory-plan preparation, transition
evaluation, run execution, replay, Phase 17 artifact queries, the Phase
18 campaign trajectory matrix, `RunEvent` and its three structural
kinds, and event/execution/matrix hashes are unchanged; new world
content hashes are expected deterministic provenance for newly compiled
worlds only. Phase 20 has not been started.

### Status

All five gates green - full suite **1479 passed / 1 skipped / 1 warning**
(the pre-existing Starlette/httpx deprecation warning only); mypy clean;
ruff check clean; `ruff format --check` clean; schema export `--check`
synced (new artifact `DomainMetricObservationBinding.schema.json`;
PUBLIC_CONTRACTS exactly 32; no existing v1 contract field changed).
New Phase 19 suites: `tests/test_domain_metric_observation_contracts.py`,
`tests/test_domain_metric_observation.py`,
`tests/test_metric_observation_store.py`,
`tests/test_metric_observation_world.py`,
`tests/test_metric_observation_integrity.py`,
`tests/test_api_phase19.py`, `tests/test_phase19_boundaries.py` - 128
new tests (plus 4 new parametrized contract cases in
tests/test_contracts.py); the four existing contract-count assertions
were updated 31 -> 32; the complete pre-Phase-19 suite remains green as
part of the full 1480-test regression run.

## Phase 20: deterministic run metric-observation extraction

Phase 19 introduced immutable `DomainMetricObservationBinding`
declarations: a binding connects one `ScenarioSpec` metric to one
numeric field of a `DomainStateModel` and declares *where a value may
be observed*. Phase 20 adds the other half of the bridge - **raw
extraction and provenance recording only**:

```
DomainMetricObservationBinding
    -> verified RunTrajectoryExecution.final_state
    -> immutable raw metric observations
```

`RunMetricObservationValue` is one extracted raw observation. It carries
the exact provenance required to prove where the value came from:
`metric_id`; `metric_unit` copied from the authoritative embedded
`ScenarioSpec` when the metric declares one; the observation binding's
identifier and content hash; the manifest and state-model
identity/content hashes; `state_field_id`; `state_field_value_kind`
(literal `"integer"` | `"number"` only); `observation_point` (exactly
`"final_state"`); the trajectory-plan identity and content hash plus
the exact result content hash required to locate the authoritative
final state inside the verified execution; and `raw_value`, an exact
finite numeric value. Numeric validation is strict and coercion-free:
booleans are never accepted as integers or numbers, integer bindings
require an actual `int`, number bindings accept an actual finite `int`
or `float`, NaN and Infinity are rejected anywhere, and the extracted
value is preserved exactly - no normalization, scaling, transformation,
or unit conversion.

`RunMetricObservationSet` is the complete immutable observation
collection of one run: run/campaign/plan/scenario identity, the verified
compiled world and the recorded strategy with their content hashes, the
recorded seed identity, `runtime_version` (literal `"2.0.0"`), the run
input hash, the verified `RunTrajectoryExecution` identifier and
content hash, the exact ordered observation tuple canonicalized by
`metric_id` (strictly increasing, duplicates rejected by the contract),
the deterministic `content_hash` over the complete canonical payload
excluding `content_hash` itself, and `observed_at` from the
authoritative execution's `executed_at` - never wall-clock time. The
set identifier is deterministically derived from the stable
run/runtime identity
(`metric-observation-set-{sha256(canonical_json({run_id,
runtime_version}))[:16]}`). An empty observation tuple is valid only
when the verified compiled world contains no binding snapshots.
`RunMetricObservationSet` is registered as the **33rd** top-level
public contract (`PUBLIC_CONTRACTS` 32 -> 33, appended after the
unchanged `DomainMetricObservationBinding`, no existing v1 contract
field changed) with a checked-in JSON Schema artifact.

Extraction is an **explicit post-execution operation** served by
`extract_run_metric_observations`: (1) the existing Phase 16/17
verifier loads and verifies every recorded trajectory input (including
full `verify_world_snapshot` recompilation); (2) the recorded runtime
must be exactly `"2.0.0"` and the run COMPLETE; (3) the stored
`RunTrajectoryExecution` is loaded only through the store boundary and
fully verified with the existing authoritative integrity pipeline
before any final state is read; (4) only the bindings embedded in the
run's exact compiled world are used - newer scenario-level declarations
added after world compilation are never consulted; (5) every binding is
extracted in canonical `metric_id` order after scenario/world/manifest/
state-model/field provenance verification, exactly-one
`RunStateTrajectoryResult` resolution (missing and ambiguous results
rejected), exact state-model identifier/id/manifest/content-hash
agreement, `final_state[state_field_id]` presence, strict raw-value
kind validation, and unit copying from the embedded scenario; (6) the
complete set is stored only after every validation and integrity check
succeeds - any failure writes nothing. Extraction never evaluates or
re-executes transitions, rebuilds or repairs an execution, triggers
replay, reads `initial_state` as an observation, chooses transitions or
plans, samples or consumes uncertainty/seeds, invokes LEGION or NEXUS,
loads/imports/instantiates/executes domain packs, or performs network,
provider, filesystem, database, randomness, or wall-clock operations.

`verify_run_metric_observation_set_record` verifies a stored set by
strict contract revalidation (validator-bypassed artifacts, booleans or
wrong-typed/non-finite raw values, invalid literals/hash patterns, and
non-canonical ordering rejected), authoritative input/execution
verification, and deterministic in-memory regeneration of the expected
set, requiring exact canonical-JSON equality - identifier, ordering,
values, provenance, and content hash. The stored artifact is never
repaired, normalized, reordered, overwritten, or silently accepted.
`get_verified_run_metric_observation_set` returns a stored set only
after that full verification and never creates an artifact when none
exists.

The store keeps exactly one `RunMetricObservationSet` per
`(tenant_id, run_id)`: duplicate creation - even an identical second
write - is rejected and never overwrites; every write and read crosses
a deep defensive copy boundary; strict complete contract revalidation
runs on write and read; incorrect ownership keys are rejected; foreign
tenants are indistinguishable from missing; rejected writes leave
storage byte-identical; and there is no update, delete, repair, or
replace surface.

API endpoints (both X-Tenant-ID scoped, `ApiErrorResponse` envelope
with request-id behavior): `POST /v1/runs/{run_id}/metric-observations`
returns 201 with the exact set after explicit extraction; `GET
/v1/runs/{run_id}/metric-observations` returns the stored set only
after full verification and is strictly read-only. Typed mappings:
unknown/foreign run or missing artifact 404 `not_found`; legacy 1.0.0
or unsupported runtime 409 `conflict`; run not COMPLETE 409
`invalid_state`; duplicate extraction 409 `conflict`; missing/ambiguous
binding results, missing fields, numeric kind/value mismatches, and
corrupted execution/world/binding/artifact 409 `integrity_error`;
request/header validation 422 `validation_error`. Public error messages
never expose raw state or observed values, hashes, guard/target values,
strategy policy content, metadata values, another tenant's identifiers
or records, or internal integrity reasons or validator diagnostics. No
operational-activity event is recorded and no Colony changes exist.

Phase 20 does not aggregate observations, calculate outcomes or
distributions, produce evidence, scores, rankings, recommendations, or
decision briefs, normalize/transform/convert metrics, sample
uncertainty, compare strategies, add runtime versions, extract
automatically during execution, add operational-activity kinds, change
Colony, integrate real NEXUS/LEGION, perform live actions, contact
external providers/network, persist to filesystem/database, or add
dependencies. Runtime 1.0.0/2.0.0 behavior, RunPlan generation,
campaign/run lifecycle, trajectory planning, transition evaluation,
`RunTrajectoryExecution` generation and hashes, `RunEvent` and its
three structural kinds, replay behavior and replay-manifest hashes,
Phase 17 artifact queries, the Phase 18 campaign trajectory matrix, and
Phase 19 declaration behavior and compiled observation snapshots are
unchanged. **Phase 21 has not started.**

New Phase 20 suites: `tests/test_run_metric_observation_contracts.py`,
`tests/test_run_metric_observation_service.py`,
`tests/test_run_metric_observation_store.py`,
`tests/test_run_metric_observation_integrity.py`,
`tests/test_api_phase20.py`, `tests/test_phase20_boundaries.py`, plus
the shared `tests/phase20_helpers.py` - 175 new tests; the six existing
contract-count assertions were updated 32 -> 33 and the
`tests/test_contracts.py` valid-payload registry gained
`RunMetricObservationSet`; the complete pre-Phase-20 suite remains
green as part of the full regression run.

## Phase 21: deterministic campaign metric-observation matrix

**Status: COMPLETE.** Phase 21 assembles the complete campaign
observation matrix of one completed runtime-2.0.0 campaign: the exact
authoritative strategy x shared-seed raw-observation layout. The phase
chain is: Phase 18 establishes the authoritative fair strategy x
shared-seed run layout (`CampaignTrajectoryMatrix`); Phase 20 produces
exactly one verified raw observation set per completed run
(`RunMetricObservationSet`, extracted explicitly and never
automatically); Phase 21 binds every completely verified Phase 20 set
to its exact Phase 18 trajectory cell and produces the immutable
comparison-ready `CampaignMetricObservationMatrix`.

### Contracts

`CampaignMetricObservationMatrix` is the 34th public contract, appended
last; `CampaignMetricObservationCell` and the Phase 20
`RunMetricObservationValue` stay nested (never registered, no standalone
schema artifacts). Both matrix and cell are frozen with
`extra="forbid"`; the runtime version literal is exactly `"2.0.0"` and
the comparison mode exactly `"identical_conditions"`; all hash fields
follow the `^[0-9a-f]{64}$` pattern; `assembled_at` is timezone-aware.
The structural validator enforces: unique strategy candidate ids, unique
seed ids, unique and strictly increasing metric ids; non-empty
strategy/seed/cell collections; the complete Cartesian product present
exactly once; contiguous sequence positions from zero; strategy and
seed position bounds; exact strategy-major/seed-minor RunPlan order;
cell strategy/seed identity matching the declared positions; and every
cell's observation metric collection equal to `ordered_metric_ids`
exactly (missing, additional, duplicate, or reordered observations or
cells rejected). `ordered_metric_ids` is empty only when every cell's
observations are empty. Nested raw values are validated through the
reused Phase 20 `RunMetricObservationValue` contract: booleans, strings,
NaN, and Infinity are rejected, and integer raw values stay integers.

### Pure builder (`build_campaign_metric_observation_matrix`)

Takes the recorded `CampaignSpec`, the completely verified Phase 18
`CampaignTrajectoryMatrix` (authoritative layout and cell order), and
the exact ordered tuple of completely verified Phase 20
`RunMetricObservationSet` artifacts - one per trajectory cell. It
verifies runtime version (2.0.0 only), identical tenant ownership,
exact campaign/scenario/world identity agreement, the exact campaign
strategy and seed order, the exact observation-set count, and per cell
the exact run/run-plan/strategy/seed/input/world/trajectory-execution
identity and content-hash agreement. The same metric's immutable
binding provenance must agree exactly across cells; run-specific
trajectory-plan/result provenance is preserved exactly without
cross-strategy equality requirements; raw values are copied exactly,
never converted or interpreted. The identifier is deterministic from
the campaign/world/runtime identity, the content hash covers the
complete canonical serialization excluding `content_hash`, and
`assembled_at` is the recorded campaign `created_at` - never the wall
clock. The builder is pure: no store access, no NEXUS/LEGION calls, no
domain packs, no wall clock, randomness, network, providers,
filesystem, or database, no mutation of inputs, and no silent sorting
or repair - incorrect orders are rejected.

### Verified query (`get_verified_campaign_metric_observation_matrix`)

Strictly read-only, tenant-scoped, all-or-nothing:

1. The campaign and status load tenant-scoped; unknown or foreign
   campaigns raise the store's typed not-found error (404).
2. The campaign must be exactly COMPLETE (`CampaignNotCompleteError`,
   409 invalid_state).
3. The verified Phase 18 `CampaignTrajectoryMatrix` is obtained through
   the existing verified query service - Phase 18 verification is never
   reimplemented or weakened, and its typed mappings (404, 409 conflict
   for legacy/unsupported runtime, 409 integrity_error for missing or
   corrupted matrix inputs) pass through unchanged.
4. For every trajectory cell in exact order, the run's Phase 20
   `RunMetricObservationSet` is obtained through the existing verified
   Phase 20 query path. Every artifact must already exist; nothing is
   ever extracted automatically.
5. Missing, foreign, partial, inconsistent, or corrupted Phase 20
   artifacts inside a COMPLETE campaign raise
   `CampaignMetricObservationMatrixIntegrityError` (409 integrity_error).
6. The complete matrix is built in memory through the pure builder and
   returned directly without being stored; a matrix violating its own
   contract at construction time is also a typed integrity failure.

No partial matrix is ever returned; the query never executes, replays,
evaluates, regenerates, repairs, or writes anything, records no
operational activity, and changes no lifecycle state.

### API

`GET /v1/campaigns/{campaign_id}/metric-observation-matrix` returns the
direct `CampaignMetricObservationMatrix` (200) only after the complete
verified collection succeeds; repeated GET responses are byte-identical.
The OpenAPI surface exposes GET only - no POST/PUT/PATCH/DELETE exists
for this path. Error envelope is the single typed `ApiErrorResponse`:
404 NOT_FOUND, 409 INVALID_STATE, 409 CONFLICT, 409 INTEGRITY_ERROR,
422 VALIDATION_ERROR (missing `X-Tenant-ID`). Public messages never
leak raw observation values, hashes, state values, guard/target values,
policy content, metadata, internal reasons, or another tenant's
records.

### Tests

New Phase 21 suites: `tests/test_campaign_metric_observation_contracts.py`,
`tests/test_campaign_metric_observation_runtime.py`,
`tests/test_campaign_metric_observation_query_service.py`,
`tests/test_api_phase21.py`, `tests/test_phase21_boundaries.py`, plus
the shared `tests/phase21_helpers.py` - 156 new tests. Coverage
includes the full contract shape matrix (Cartesian invariants, nested
bool/string/NaN/Infinity raw-value rejection, schema round-trip and
export), the complete builder tamper matrix (missing/additional/
duplicated/reordered/foreign/mismatched inputs, differing metric
collections, differing binding provenance, legitimately differing
run-specific provenance, empty-bindings worlds, input immutability,
byte-identical repeated builds), the verified query pipeline (Phase 18
authoritative layout, Phase 20 getter used for every run, validator-
bypassed bool/NaN corruption, missing/corrupted sets, preserved Phase
18 mappings, no extraction/execution/replay/storage, unchanged store
snapshot), the API surface (GET-only, typed error mappings, no-leak
bodies, byte-identical repeats, no activity/Colony changes), and the
boundary scans (no store access in the builder, no extraction in the
query, no matrix storage anywhere, no statistics/outcomes/evidence/
ranking/recommendations, no normalization/unit conversion, no NEXUS/
LEGION/domain-pack/network/filesystem/database/wall-clock/randomness,
no runtime/execution/replay/lifecycle/RunEvent changes, Phase 18-20
behavior unchanged, PUBLIC_CONTRACTS exactly 34 with the previous 33
unchanged and the matrix last). The existing contract-count assertions
were updated 33 -> 34 and the `tests/test_contracts.py` valid-payload
registry gained `CampaignMetricObservationMatrix`; the complete
pre-Phase-21 suite remains green as part of the full regression run.

### Non-goals (unchanged through Phase 21)

No aggregation, distributions, outcomes, evidence, scoring, ranking,
recommendations, or decision briefs exist yet; no normalization,
transformation, or unit conversion; no automatic Phase 20 extraction;
no matrix storage; no new runtime versions; no execution, replay, or
lifecycle changes; no operational-activity or Colony changes; no real
NEXUS/LEGION integration; no live actions, external providers/network,
filesystem/database persistence, or new dependencies. Runtime
1.0.0/2.0.0 behavior, RunPlan generation, campaign/run lifecycle,
trajectory planning, transition evaluation, `RunTrajectoryExecution`
generation and hashes, `RunEvent` and its structural kinds, replay
behavior and replay-manifest hashes, Phase 17 artifact queries, the
Phase 18 campaign trajectory matrix, Phase 19 declaration behavior, and
Phase 20 extraction behavior are unchanged. **Phase 22 has not
started.**

## Phase 22: deterministic campaign metric statistics

**Status: COMPLETE.** Phase 22 derives the descriptive-statistics
matrix of one completed runtime-2.0.0 campaign exclusively from its
completely verified Phase 21 `CampaignMetricObservationMatrix`. The
phase chain is: Phase 21 supplies the verified raw strategy x seed
observation matrix; Phase 22 summarizes each strategy's exact metric
observations across the campaign's identical ordered shared seeds with
the one fixed deterministic descriptive-statistics definition - no
declared `MetricDefinition.aggregation` policy is ever interpreted, no
strategy is ranked or scored, no winner is declared, and no
OutcomeVector, evidence, or recommendation exists yet.

### Contracts

`CampaignMetricStatisticsMatrix` is the 35th public contract, appended
last; `CampaignStrategyMetricStatistics` stays nested (never registered,
no standalone schema artifact). Both are frozen with `extra="forbid"`;
the runtime version literal is exactly `"2.0.0"`, the comparison mode
exactly `"identical_conditions"`, and the statistics mode exactly
`"descriptive"`; all hash fields follow the `^[0-9a-f]{64}$` pattern;
`summarized_at` is timezone-aware. The summary validator enforces:
non-empty exact finite observed values (booleans, strings, None,
containers, NaN, and Infinity rejected before any coercion; raw
integers stay integers and raw floats stay floats), observation count
equal to the collection length, minimum and maximum equal to the exact
observed extrema, finite derived statistics, and a single observation's
population standard deviation exactly `0.0`. The matrix validator
enforces: unique strategy/seed ids, unique and strictly increasing
metric ids; summaries covering every strategy x metric pair exactly
once in the exact strategy-major/metric-minor order with contiguous
positions and identity-vs-position agreement; every summary's observed
value length equal to the seed count; and empty `ordered_metric_ids`
requiring empty `summaries` (duplicate, missing, additional, reordered,
or out-of-range summaries rejected).

### Pure builder (`build_campaign_metric_statistics_matrix`)

Takes exactly one completely verified Phase 21
`CampaignMetricObservationMatrix`. It verifies the source runtime is
exactly `2.0.0` (`UnsupportedRuntimeVersionError` otherwise), the
comparison mode is exactly `identical_conditions`, the source
deterministic identifier pattern and self-covering content hash, the
exact strategy x seed cell shape with every cell's sequence/strategy/
seed positions and identities bound exactly, the exact metric
collection in every cell, per-metric identical binding provenance
across all cells, and every raw value strictly again
(`raw_value_matches_numeric_kind`: no bool, string, None, container,
non-finite float, or malformed kind/value combination). It then
computes per strategy x metric over the exact ordered seed observations
the fixed descriptive statistics - minimum and maximum (built-in
`min`/`max`), arithmetic mean (`math.fsum(float(v) ...)/N`), median
(numeric sort; odd count middle value, even count
`math.fsum((float(left), float(right)))/2`), and population standard
deviation (defined mean, `math.fsum` of exact square deviations,
population denominator N, `math.sqrt`; one value gives exactly `0.0`) -
standard library only, no NumPy/pandas. A valid exact raw integer too
large to convert to a finite float, or any derived statistic that
overflows or becomes non-finite, rejects the complete matrix with
`CampaignMetricStatisticsIntegrityError` - never clamped, rounded,
replaced, or partially returned. Raw integers remain integers and raw
floats remain floats in `ordered_observed_values`. The identifier is
deterministic from the campaign/world/runtime/source-matrix identity,
the content hash covers the complete canonical serialization excluding
`content_hash`, and `summarized_at` is the authoritative Phase 21
matrix `assembled_at` - never the wall clock. A zero-metric source
matrix yields a valid statistics matrix with `summaries=()`. The
builder is pure: no store access, no NEXUS/LEGION calls, no domain
packs, no wall clock, randomness, network, providers, filesystem, or
database, no mutation of inputs, and no silent sorting or repair -
incorrect orders are rejected.

### Verified query (`get_verified_campaign_metric_statistics`)

Strictly read-only, tenant-scoped, all-or-nothing:

1. The campaign and status load tenant-scoped; unknown or foreign
   campaigns raise the store's typed not-found error (404).
2. The campaign must be exactly COMPLETE (`CampaignNotCompleteError`,
   409 invalid_state).
3. The completely verified Phase 21 `CampaignMetricObservationMatrix`
   is obtained through the existing verified query service - Phase 18,
   20, and 21 verification is never reimplemented or weakened, and its
   typed mappings (404, 409 conflict for legacy/unsupported runtime,
   409 integrity_error for missing or corrupted earlier-phase
   artifacts) pass through unchanged.
4. The descriptive-statistics matrix is built in memory through the
   pure Phase 22 builder and returned directly without being stored;
   Phase 22 calculation, consistency, overflow, or non-finite failures
   - or a matrix violating its own contract at construction time -
   raise `CampaignMetricStatisticsIntegrityError` (409 integrity_error).

No partial matrix is ever returned; the query never executes, replays,
evaluates, regenerates, repairs, extracts, writes, or stores anything,
creates no missing Phase 20 artifacts, records no operational activity,
and changes no lifecycle state.

### API

`GET /v1/campaigns/{campaign_id}/metric-statistics` returns the direct
`CampaignMetricStatisticsMatrix` (200) only after the complete verified
chain succeeds; repeated GET responses are byte-identical. The OpenAPI
surface exposes GET only - no POST/PUT/PATCH/DELETE exists for this
path. Error envelope is the single typed `ApiErrorResponse`: 404
NOT_FOUND, 409 INVALID_STATE, 409 CONFLICT, 409 INTEGRITY_ERROR, 422
VALIDATION_ERROR (missing `X-Tenant-ID`). Public messages never leak
raw observation values, calculated statistics, hashes, state values,
field names, policy content, metadata, internal reasons, or another
tenant's records.

### Tests

Five focused suites: `test_campaign_metric_statistics_contracts.py`
(frozen/strict contracts, raw-value strictness, structural invariants,
schema round-trip/export, 35-contract registration),
`test_campaign_metric_statistics_runtime.py` (exact algorithm values,
seed-order preservation, determinism, no input mutation, full tamper
matrix), `test_campaign_metric_statistics_query_service.py`
(authoritative Phase 21 pipeline, typed mappings, read-only/no-write
proofs), `test_api_phase22.py` (200 direct response, typed error
mappings, no-leak bodies, GET-only OpenAPI, byte-identical repeats),
and `test_phase22_boundaries.py` (module scans, no storage surface, no
execution/extraction/replay, no outcome/ranking/normalization
production, no new dependencies/runtime versions, unchanged
Phase 18-21 behavior).

### Non-goals (unchanged through Phase 22)

No ranking, scoring, winner declaration, objective/target comparison,
pass/fail judgments, `MetricOutcome`, `OutcomeVector`,
`DistributionSummary`, evidence, `DecisionBrief`, recommendations,
declared aggregation-policy interpretation, quantiles/confidence
intervals, normalization/transformation/unit conversion, uncertainty
sampling, new runtime versions, automatic Phase 20 extraction,
statistics storage, execution/replay/lifecycle changes,
operational-activity or Colony changes, real NEXUS/LEGION integration,
live actions, external providers/network, filesystem/database
persistence, or new dependencies. Runtime 1.0.0/2.0.0 behavior, RunPlan
generation, campaign/run lifecycle, trajectory planning, transition
evaluation, `RunTrajectoryExecution` generation and hashes, `RunEvent`
and its structural kinds, replay behavior and replay-manifest hashes,
Phase 17 artifact queries, the Phase 18 campaign trajectory matrix,
Phase 19 declaration behavior, Phase 20 extraction behavior, and the
Phase 21 metric-observation matrix are unchanged. **Phase 23 has not
started.**

## Phase 23: deterministic objective-to-metric evaluation

**Status: COMPLETE.** Phase 23 adds an immutable, tenant-scoped
per-scenario evaluation profile and a read-only campaign
objective-evaluation matrix derived exclusively from the completely
verified Phase 21 `CampaignMetricObservationMatrix` and the
world-embedded profile snapshot. Evaluation is target violation only.

### Contracts

`ObjectiveMetricBinding` (frozen, `extra="forbid"`, nested, not
registered) snapshots `objective_id`, `metric_id`, `direction`,
`target`, `weight`, `metric_unit`, `reach_tolerance`, and
`normalization_scale`. `ScenarioEvaluationProfile` (36th public
contract; identifier
`evaluation-profile-{sha256(canonical_json({tenant_id, scenario_id,
scenario_content_hash, schema_version}))[:16]}`, self-covering
`content_hash`, timezone-aware `declared_at`, strict JSON `metadata`)
requires exactly one binding per scenario objective in the exact
`ScenarioSpec.objectives` order. `ObjectiveObservationEvaluation`
(nested) independently recomputes the expected signed target delta
from its own raw value, direction, target, and reach tolerance via the
shared pure `evaluate_target_delta` helper (the same expression the
Phase 23 builder uses) and requires `signed_target_delta`,
`target_achieved == (delta <= 0)`, and
`normalized_target_violation == max(0, delta) / normalization_scale`
to match exactly - a self-consistent but forged triple is rejected,
never clamped, rounded, coerced, or approximately compared - with all
three evaluation fields `None` when the objective has no target.
`CampaignObjectiveEvaluationMatrix` (37th
public contract) enforces the **required** runtime literal `2.0.0`
(no default; present in the schema `required` array), comparison mode
`identical_conditions`, the complete strategy x seed x objective
Cartesian product in strategy-major, seed-minor, objective-minor order
with contiguous positions and identity agreement, and full provenance
(source matrix id/hash, profile id/hash, world/scenario hashes,
`evaluated_at` from the Phase 21 `assembled_at`). Two new schema
artifacts; no existing contract changed.

### Declaration lifecycle

`POST /v1/scenarios/{scenario_id}/evaluation-profile` accepts only
caller-owned fields (`objective_id`, `metric_id`, `reach_tolerance`,
`normalization_scale`, `declared_at`, `metadata`); direction, target,
weight, and metric unit are copied from the stored `ScenarioSpec`, so
forged authoritative fields are impossible (422). Bindings are
canonicalized into scenario objective order; equivalent caller orders
produce identical profiles. Coverage must be complete with exactly one
reference per objective (422 otherwise, including duplicate objectives
in the scenario). `reach_tolerance` is required, finite, and >= 0 for
`reach` only and forbidden otherwise; `normalization_scale` must be
exact finite numeric > 0. One immutable profile per tenant + scenario:
duplicates 409 and never overwrite; declaration after the first world
compilation 409; unknown/foreign scenario 404; no update, replace,
delete, or list surface. Storage is deep-copied and strict-revalidated
on write and **every read**, with independent
ownership/identifier/content-hash verification (pure identity helpers)
before any copy crosses the store boundary. `GET` returns the stored
profile unchanged.

### World integration

The declared profile is embedded under a dedicated `evaluation_profile`
key and included in the world content hash only when present;
profile-free worlds compile byte-identically to Phase 22.
`verify_world_snapshot` strictly parses the embedded profile,
recomputes the scenario content hash from the embedded scenario,
re-derives profile identifier and content hash, verifies exact
scenario-order coverage and copied-value agreement, enforces
tolerance/scale rules, and requires exact recompile equality;
`VerifiedWorldCatalog` carries the canonical `evaluation_profile`.
The compiler snapshots and canonicalizes only; it never interprets
objective semantics.

### Verified query

`GET /v1/campaigns/{campaign_id}/objective-evaluations` (GET-only):
tenant-scoped campaign and COMPLETE gate (409 `invalid_state`) ->
verified Phase 21 matrix -> fully verified compiled world -> exact
world-embedded profile matched against the stored record (world
without embedded profile 404; missing/mismatched stored record 409
`integrity_error`) -> pure in-memory builder re-deriving every source
identifier and hash and resolving each binding to exactly one verified
observation. The matrix is never stored; no automatic extraction, no
execution/replay/repair/lifecycle changes, no operational-activity
kinds or writes. Legacy/unsupported runtime 409 `conflict`;
unknown/foreign campaign 404. Public messages never leak raw values,
targets, tolerances, scales, hashes, metadata, or integrity reasons.

### Non-goals (unchanged through Phase 23)

No comparative regret, ranking, dominance, preference, winner
selection, probability/confidence/quantiles, empirical distributions,
risk/CVaR, evidence, `DecisionBrief`, recommendations, uncertainty
sampling or seed consumption, new runtime versions, automatic
evaluation during execution, operational-activity kinds, Colony
changes, real NEXUS/LEGION integration, live actions, external
providers/network, filesystem/database persistence, or new
dependencies. Runtime 1.0.0/2.0.0 behavior, RunPlan generation,
campaign/run lifecycle, trajectory planning, transition evaluation,
`RunTrajectoryExecution` generation and hashes, `RunEvent` and its
structural kinds, replay behavior and replay-manifest hashes, Phase 17
artifact queries, the Phase 18 campaign trajectory matrix, Phase 19
declaration behavior, Phase 20 extraction behavior, the Phase 21
metric-observation matrix, and the Phase 22 metric-statistics matrix
are unchanged (world hashes change only for worlds compiled with a
declared profile). **Phase 24 is complete (next section).**

## Phase 24: deterministic world uncertainty realizations

**Status: COMPLETE.** Phase 24 is sampling and provenance only: for a
campaign's shared seeds it produces exactly one immutable,
strategy-independent `WorldRealization` per seed from the compiled
world and the scenario's immutable `WorldUncertaintyModel`. It never
executes strategies, trajectories, transitions, metrics, objectives,
outcomes, comparisons, rankings, or recommendations; never invokes
NEXUS or LEGION; never loads or executes domain-pack code; and never
uses providers, network, databases, filesystems, wall clocks, global
RNG, UUIDs, or `random.seed`. Phase 25 / runtime 3.0.0 has not
started.

### Contracts

Three new public contracts appended at the tail
(`kalhas/contracts/v1/world_realization.py`, `PUBLIC_CONTRACTS` 37 ->
40): `WorldUncertaintyModel` (38th), `WorldRealization` (39th), and
`CampaignWorldRealizationMatrix` (40th). The five distribution
families - `uniform(low, high)` with `low <= high`,
`triangular(low, mode, high)` with `low <= mode <= high`,
`normal(mean, standard_deviation)` and `lognormal(mu, sigma)` (mu/sigma
are log-space parameters) with strictly positive deviations, and
`discrete(values, probabilities)` with canonically unique strict
values, finite non-negative probabilities, at least one positive, and
a documented `1e-12` sum tolerance - form the **closed discriminated
union** `DistributionSpecification` (no unvalidated parameter
dictionaries). `StateFieldUncertaintyBinding` copies every
authoritative provenance field from stored immutable records and adds
the caller-owned distribution, one exact rounding policy for integer
targets only (`floor`/`ceil`/`nearest_ties_to_even`), and
independently optional clipping bounds (integer targets require exact
`int` bounds). `SampledStateFieldValue` records the raw sample before
clipping/rounding (integer-target raws may be float) and the final
realized value (integer targets always exact `int`), with global
digest-word `draw_index`/`draw_count` accounting whose ranges partition
`[0, total_words)`. `WorldRealization` carries world/seed identity and
content-hash provenance, the model identity/hash or an explicit absent
state, the frozen sampler/quantization provenance literals
(`sha256-counter-v1`, `rational-round-half-even`, 64 fraction bits),
the complete realized initial-state override delta (one override per
binding, one-to-one with the sampled values), a deterministic
identifier independent of the content hash, and `realized_at` = the
campaign's authoritative `created_at`. `CampaignWorldRealizationMatrix`
holds exactly one realization per seed in exact seed-ensemble order
with no strategy identifiers anywhere. All eight nested value objects
stay unregistered; `UncertaintyDefinition` is untouched.

### Sampler and quantization

`sha256-counter-v1` is integer-only Q64.64 fixed-point with frozen
integer literals (never platform libm). Every declared parameter is
converted by exact rational round-half-even quantization
(`float.as_integer_ratio()` + `divmod`). The open-uniform input is
`u = (word + 1) / 2**64` (structurally never zero; `log(0)`
unreachable). Each digest word is the first 8 bytes big-endian of one
SHA-256 over the canonical payload `{domain:
"kalhas/world-realization-v1", draw_index, sampler_version,
seed_content_hash, uncertainty_binding_content_hash,
world_content_hash}` - no strategy terms. `sqrt` uses exact
`math.isqrt`; `log` a fixed 32-term atanh series; `exp` is reduced by
`ln 2` (`k = floor(x/ln2)`, `r = x - k*ln2`, `exp = 2**k * exp(r)`,
24-term Horner, `k > 1024` rejected before any shift, `k < -65` ->
exactly 0); `cos` uses quadrant reduction plus a fixed 14-term Horner;
Box-Muller consumes two words with the exact deterministic radius
`sqrt(-2 ln u1)` and the invariant-checked maximum `Z_MAX =
isqrt(128 ln2)`. Discrete selection uses exact integer weights, the
ticket `(word * W) >> 64`, and strict `<` cumulative boundaries
(ticket exactly on a boundary resolves to the later value;
zero-probability support is never selected; no forced residual).
Verified accuracy budgets: `log`/`cos` at most 64/32 Q64.64 ulps,
`exp` relative error below `2**-50`.

### Representation semantics

Canonical JSON `1` and `1.0` are distinct. Continuous families always
record float raws (even when mathematically integral); a discrete
sample preserves the exact declared value type; clipping a number
target adopts the exact stored bound type; integer targets always
finish as exact `int`. The operation order is **finite raw -> clip ->
round -> complete-state validation** using the existing
`validate_state` rules (exact kind, canonical `allowed_values`
membership); the raw is recorded before clipping and the
finite-representability guard runs before any clip, so clipping can
never rescue a non-finite raw. Failures are deterministic per seed and
never resampled or retried.

### Declaration lifecycle

One immutable model per tenant + scenario (`world_uncertainty_service.py`):
caller supplies only the binding drafts (`manifest_id`,
`state_model_id`, `state_field_id`, distribution, rounding policy,
independently optional bounds) plus `declared_at`/`metadata`; every
provenance field is copied from stored records, so forged
authoritative values are impossible. Bindings are canonicalized into
exact `(manifest_id, state_model_id, state_field_id)` order. Only
`integer`/`number` initial-state fields may be targeted. Unknown
references, unsupported kinds, rounding/bound rule violations,
discrete-kind mismatches, effective Q64.64 parameter violations
(vanishing rule, effective ordering, effectively positive deviations,
lognormal static finite-raw boundary), and statically provable discrete
allowed-values violations -> typed 422. Declaration after the first
world compilation and duplicate declarations -> typed 409. The store
deep-copies on write and read and strictly revalidates the complete
contract plus the deterministic identity on **every** access; there is
no update/replace/delete/list surface and no operational-activity
event.

### World integration

The compiler embeds the complete model snapshot under
`uncertainty_model` (covered by the world content hash) only when a
model exists; model-free worlds compile byte-identically to Phase 23
and no runtime-2 golden world hash changes. `verify_world_snapshot`
strictly verifies the embedded model's ownership, identifier, content
hash, canonical binding order, copied authoritative provenance against
the embedded pack-binding/state-model snapshots, sampler/quantization
literals, effective parameter rules, and static discrete allowed
outcomes, then recompiles and requires exact equality.
`VerifiedWorldCatalog` gained the additive `uncertainty_model`.
`MockNexusAdapter.compile_scenario` loads the stored model through the
verified retrieval path.

### Builder and verified query

The pure builder (`world_realization_builder.py`) derives each base
initial state from the embedded `DomainStateModel`, samples every
targeted field exactly once, applies the approved clip/round order,
validates each final value and the complete realized state, and emits
detached immutable plain-JSON artifacts; it never mutates the world,
model, seed, or state models, and rejects inconsistent direct inputs
(campaign/world/seed/model provenance mismatches, missing or
mismatched target state models/fields, empty seed ensembles) with
typed integrity errors. The verified query
(`world_realization_query_service.py`) loads and fully verifies the
campaign's world/manifest, strictly revalidates the stored model and
requires canonical equality with the embedded snapshot, and derives
the matrix in memory - never stored, no lifecycle gate (any recorded
campaign state yields identical bytes), no writes, no operational-
activity events, no NEXUS/LEGION calls. A world without an uncertainty
model still yields one deterministic empty realization per seed
(empty samples/overrides, explicit absent model markers, real derived
hashes). Deterministic per-seed sampling failures propagate as the
typed 409 `conflict` sampling error; missing, inconsistent, or
corrupted artifacts map to typed 409 `integrity_error`.

### API

`POST /v1/scenarios/{scenario_id}/uncertainty-model` (201; forged
authoritative fields, identifiers, hashes, and sampler literals ->
422), `GET /v1/scenarios/{scenario_id}/uncertainty-model` (200/404/409
integrity), `GET /v1/campaigns/{campaign_id}/world-realizations`
(200 with exactly K realizations for K seeds and any strategy count;
404 unknown/foreign campaign; 409 `conflict`; 409 `integrity_error`).
The single `ApiErrorResponse` envelope is unchanged; public messages
never leak sampled values, distribution parameters, bounds, hashes,
state values, metadata, or internal reasons; repeated GETs are
byte-identical.

### Non-goals (unchanged through Phase 24)

No execution, replay, transition, metric extraction, objective
evaluation, outcomes, empirical distributions, comparison, ranking,
recommendation, evidence, or decision briefs; no uncertainty
consumption beyond sampling; no new runtime version; no
operational-activity kinds; no Colony changes; no NEXUS/LEGION
integration; no live actions, providers, network, filesystem, or
database; no new dependencies. Runtime 1.0.0/2.0.0 behavior, RunPlan
generation and `run_input_hash`, campaign/run lifecycle, trajectory
planning, transition evaluation, `RunTrajectoryExecution` generation
and hashes, `RunEvent` structural kinds, replay behavior, all
Phase 17-22 artifact queries, the Phase 22 metric-statistics matrix,
and the Phase 23 evaluation profile/matrix are unchanged (world
hashes change only for worlds compiled with a declared uncertainty
model - new deterministic provenance). **Phase 25 has not started.**

## Phase 25: realization-aware trajectory runtime 3.0.0

**Status: COMPLETE**, included in one local closure commit (the local
Phase 25 closure commit containing this documentation; **not pushed** -
`origin/main` remains at
`f40e83de468ca14100d011454d15eb3dd561c810` and local `main` is exactly
one commit ahead; push is intentionally deferred until Phases 26 and 27
are complete; authoritative facts and gate results are in
`KALHAS_HANDOFF_PHASE_25.md`). **Phase 26 has not begun** was true at
the Phase 25 checkpoint and is superseded by the Phase 26 section
below. This section **explicitly supersedes the historical statements
above that Phase 25 / runtime 3.0.0 "has not started".**

### Contracts

Six new public contracts are appended at `PUBLIC_CONTRACTS` indexes
40-45 (46 total), each `extra="forbid"`, frozen, self-hashing, and
version-locked to the `Literal["3.0.0"]` runtime:

- **`RealizationRunTrajectoryExecution`** (index 40) - the immutable
  aggregate artifact of one completed runtime-3 run: run/campaign/plan
  identity, world and strategy identities with content hashes, the
  recorded seed, the exact `world_realization_id` /
  `world_realization_content_hash` that supplied the realized initial
  states, the runtime-3 `input_hash`, the exact ordered plan-set hash,
  the ordered `RealizedStateTrajectoryResult` tuple (realized initial
  state + hash are authoritative; attempt records reuse
  `RunTrajectoryAttemptRecord` with exact position-by-position plan
  binding), a self-covering `content_hash`, and `executed_at` =
  `run_plan.created_at`. Identifier prefix
  `realization-trajectory-execution-`, payload `{run_id,
  runtime_version}`.
- **`RealizationRunTrajectoryReplayManifest`** (index 41) - the
  provenance manifest of one exact observation-aware replay, binding
  the stored execution and observation-set identities, recording
  expected/recomputed execution hashes and expected/recomputed
  observation-set hashes, `replay_classification="exact"`, and a
  **self-covering** content hash over the complete payload excluding
  itself (tampering any field fails the recompute at every trust
  boundary). Identifier `realization-replay-{run_id}`; `replayed_at` =
  `run_plan.created_at`.
- **`RealizationCampaignTrajectoryMatrix`** (index 42) - the derived
  campaign matrix: exact strategy-major/seed-minor cells
  (`RealizationCampaignTrajectoryRunCell`: run/plan/strategy/seed
  identity, input hash, execution reference, plan-set hash, result
  content hashes, per-cell realization id/hash), seed-aligned
  `ordered_world_realization_ids` /
  `ordered_world_realization_content_hashes` (length == seed count,
  cell<->tuple agreement enforced), `comparison_mode="identical_conditions"`,
  `assembled_at` = `campaign.created_at`.
- **`RealizationRunMetricObservationSet`** (index 43) - one run's
  explicitly extracted observation set: full provenance (world,
  strategy, seed, realization, execution references), observations
  reusing `RunMetricObservationValue` in canonical `metric_id` order
  (raw values preserved exactly; no coercion), `observed_at` =
  `execution.executed_at`. Extraction is explicit (POST), a second
  extraction is rejected even when byte-identical, and querying never
  auto-extracts.
- **`RealizationCampaignMetricObservationMatrix`** (index 44) - the
  derived observation matrix: per-cell
  `RealizationCampaignMetricObservationCell` (execution and
  observation-set references with content hashes, per-cell realization
  id/hash, observations), seed-aligned realization tuples, exact
  metric-id collection equality across cells.
- **`RealizationCampaignMetricStatisticsMatrix`** (index 45) - the
  derived descriptive-statistics matrix over the verified observation
  matrix: `statistics_mode="descriptive"`, source matrix reference,
  seed-aligned realization tuples, summaries reusing the frozen
  `CampaignStrategyMetricStatistics` computed only through the Phase 22
  statistics functions (minimum, maximum, arithmetic mean, median,
  population standard deviation; ordered raw values preserved in exact
  seed order; no ranking, score, or comparison).

Three nested value objects stay unregistered:
`RealizedStateTrajectoryResult`, `RealizationCampaignTrajectoryRunCell`,
`RealizationCampaignMetricObservationCell`. Indexes 0-39 and all 40
historical schema artifacts are unchanged; 6 new schema artifacts bring
`schemas/v1/` to exactly 46. No runtime-2 contract module was mutated.

### Lifecycle

Preparation (`prepare_realization_campaign`, request-dispatched from
the POST /v1/campaigns body) -> trajectory planning
(`prepare_strategy_trajectory_plans` with the fail-closed mock
declaration seam) -> start -> execution
(`execute_realization_campaign`, complete-matrix preflight exactly once,
then per-run `execute_realization_run`) -> **explicit observation
extraction** (POST realization-metric-observations) -> verified matrix
queries (trajectory, observation, statistics; derived, never stored,
read-only, no activity) -> **observation-aware replay** (requires prior
extraction; typed 404 with zero writes otherwise; regenerates
execution, observation set, and structural events; writes the manifest
pair; idempotent on repetition; sequential two-manifest write
limitation recovered idempotently - a missing manifest is completed
with identical bytes, a corrupted one blocks replay and is never
overwritten). Every runtime gate dispatches on the recorded
`RunPlan`/`RunStatus.runtime_version`; unsupported recorded versions
raise the typed `UnsupportedRuntimeVersionError` (409 `conflict`); the
runtime-2 artifact endpoints reject recorded 3.0.0 before their
services run; empty plan tuples fail closed. All timestamps derive from
recorded `created_at` values. No wall clock, randomness, UUID, network,
provider, database, filesystem, or domain-pack execution exists
anywhere in the runtime-3 modules; no outcome, ranking, score,
evidence, recommendation, or decision-brief surface exists.

### API

Exactly 6 new paths / 7 operations, all tenant-scoped with the single
`ApiErrorResponse` envelope, non-leaking public messages, and 404/409
`invalid_state`/`conflict`/`integrity_error` mapping:

1. GET `/v1/runs/{run_id}/realization-trajectory-execution`
2. GET `/v1/runs/{run_id}/realization-trajectory-replay-manifest`
3. POST `/v1/runs/{run_id}/realization-metric-observations` (201)
4. GET `/v1/runs/{run_id}/realization-metric-observations`
5. GET `/v1/campaigns/{campaign_id}/realization-trajectory-matrix`
6. GET `/v1/campaigns/{campaign_id}/realization-metric-observation-matrix`
7. GET `/v1/campaigns/{campaign_id}/realization-metric-statistics`

The six GETs are strictly read-only and record no operational activity;
extraction records no activity. Runtime-2 behavior is byte-identical
(runtime-2 golden tests and the Phase 17/20/22 OpenAPI `$ref` canaries
pass unchanged); Phase 24 modules are unchanged; realizations and
matrices remain derived, never stored. The statement that "Phase 26 and
Phase 27 are not implemented or designed here" was true at the Phase 25
checkpoint (neither phase was implemented then); it is superseded for
Phase 26 by the Phase 26 section below. Only the "not implemented"
portion remains true for Phase 27: Phase 27 remains unimplemented, but
its authoritative design already exists in the external blueprint and
`CODEX_HERMES_HANDOFF_PHASE_26_START.md`.

## Phase 26: empirical campaign outcome distributions

**Status: IMPLEMENTATION-COMPLETE, GATE-GREEN LOCALLY, NOT YET
COMMITTED.** The complete Phase 26 change set (19 created paths plus 21
modified integration paths; exact inventory in
`KALHAS_HANDOFF_PHASE_26.md`) is present in the working tree and
uncommitted at this documentation snapshot; the Git index remains
empty; a local closure commit requires separate explicit user
authorization; no push occurs until Phases 26 and 27 are both complete;
**Phase 27 implementation has not begun** (its authoritative design
already exists). This section supersedes the historical
Phase 25-checkpoint statements above that Phase 26 "has not begun" /
"Phase 26 and Phase 27 are not implemented or designed here".

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

### Contracts

Three nested strict frozen models in the new additive module
`kalhas/contracts/v1/campaign_outcome.py` (no shipped contract was
mutated; the per-run `OutcomeVector` is not reused):

- **`EmpiricalDistributionSummary`** - exact ordered samples in
  shared-seed order (raw `int`/`float` types preserved, `bool` and
  non-finite rejected), sample count, minimum, maximum, arithmetic
  mean, median, population standard deviation, Type-7
  p05/p25/p75/p95, and the exact `quantile_algorithm` literal
  `hyndman-fan-type-7-v1`. Validates internal consistency only: count
  == collection length; extrema equal the exact finite-float
  projections; mean/median within extrema; non-negative standard
  deviation; non-decreasing quantile chain; one-sample and
  repeated-value invariants (exact `0.0` standard deviation);
  deterministic one-adjacent-float-step structural-bound policy for
  composability with the accepted primitives (never `math.isclose`).
- **`StrategyObjectiveOutcome`** - one strategy/objective evidence
  artifact: exact positions and identities, authoritative
  direction/target/reach-tolerance/weight/normalization-scale
  snapshots, ordered observed values and their empirical summary,
  targeted evidence (achievement count, empirical probability, exact
  seed-order normalized-violation distribution, worst normalized
  violation, `target_violation_cvar` with `tail_alpha == 0.95` and
  `tail_algorithm == "empirical-fractional-tail-mean-v1"`) or
  all-`null` for optimization-only objectives, and the mandatory
  direction-aware `adverse_tail_statistic` in the metric's original
  unit. The violation tuple and achievement count are independently
  recomputed in the contract and must match the recorded fields
  exactly; the CVaR must lie between the violation p95 and the worst
  violation; the adverse tail must lie in its direction-aware band.
- **`CampaignOutcomeDistributionMatrix`** - the only Phase 26
  top-level public contract (`VersionedContract`, `extra="forbid"`,
  frozen, self-hashing): campaign/scenario/world identity and content
  hashes, `runtime_version` literal `"3.0.0"`, `comparison_mode`
  `"identical_conditions"`, evaluation-profile and uncertainty-model
  provenance (both-or-neither), both source matrix references with
  content hashes, ordered strategy/seed/objective/metric identifiers,
  the complete strategy-major/objective-minor outcome tuple, the
  self-covering `content_hash`, and `derived_at`. The contract
  enforces the structural shape: unique identifiers, strictly
  increasing metric ids, exactly one outcome per strategy x objective
  pair in exact order with contiguous sequence positions and
  identity-vs-position agreement, per-outcome sample counts equal to
  the seed count, and identical objective/binding snapshots across
  strategies of the same objective (evidence values may differ).

Registration: `CampaignOutcomeDistributionMatrix` is `PUBLIC_CONTRACTS`
index 46; **total public contracts: 47**; **total schema artifacts:
47** (`schemas/v1/CampaignOutcomeDistributionMatrix.schema.json` is the
only new artifact; it embeds the two nested value objects as `$defs`).
`EmpiricalDistributionSummary` and `StrategyObjectiveOutcome` remain
unregistered with no schema artifacts. Indexes 0-45 and all 46
historical schema artifacts are unchanged.

### Statistical definitions

- Exact-type finite numeric validation (exact `int`/`float` only;
  `bool`, strings, `Decimal`, `None`, containers, NaN, Infinity
  rejected; raw types preserved; integers and floats may mix).
- Full-domain finite-float conversion proof before any
  selection/sorting/arithmetic; huge positive/negative
  unrepresentable integers raise `OverflowError`; invalid input raises
  `ValueError`; a public function never returns NaN or Infinity.
- Hyndman-Fan Type 7 quantiles (integer numerator/remainder index
  arithmetic; `math.fsum` linear interpolation; identifier
  `hyndman-fan-type-7-v1`; only p05/p25/p75/p95).
- One-sample behavior (every derived value equals the projected sample
  exactly; std dev exactly `0.0`) and finite-sample behavior
  (repeated-value collections emit exactly `0.0` std dev; deterministic
  mean/quantiles may land within one adjacent float step).
- Arithmetic mean, median, population standard deviation through the
  frozen Phase 22 primitives.
- Fixed tail alpha `0.95` (`EMPIRICAL_TAIL_ALPHA`; callers cannot
  supply another) with the fractional empirical tail-mean algorithm
  `empirical-fractional-tail-mean-v1` (exact mass 5/100 per sample;
  `tail_units = 5 * n`; full observations + exact fractional boundary
  weight; no `ceil(0.05*n)`, no unweighted selection, no bootstrap).
- Target-violation semantics (Phase 23, exact seed order): minimize
  `max(0, value - target) / scale`; maximize
  `max(0, target - value) / scale`; reach
  `max(0, abs(value - target) - tolerance) / scale`.
- Direction-aware adverse-tail semantics in the metric's original
  unit: upper-tail mean for minimize, lower-tail mean for maximize,
  upper-tail mean of absolute deviation from target for reach.
- Optimization-only objectives: target probability, violations, and
  CVaR remain `null`; the adverse-tail statistic remains available.
- One-ULP golden-test discipline per the established convention.
- Production uses plain `int`/`float`/`math.fsum` only; **no `Decimal`
  or `Fraction` in production.**

### Identity and lifecycle

The matrix identifier is hash-derived from the canonical
(campaign, world, runtime, evaluation-profile, source world-realization
matrix, source metric-observation matrix) identity with the prefix
`campaign-outcome-distribution-matrix-` - never from the content hash,
timestamps, or the tenant. The content hash is the canonical SHA-256 of
the complete payload excluding `content_hash`. `derived_at` equals the
observation matrix `assembled_at` (recorded campaign timestamp
lineage; never wall clock). Lifecycle: COMPLETE runtime-3 campaign ->
verified world snapshot -> world-embedded evaluation profile (strictly
verified against the stored record) -> verified world-realization
matrix -> verified runtime-3 metric-observation matrix -> pure matrix
builder -> direct response (derived in memory, **never stored**).

### Builders and verified query

Five separated responsibilities: (1) pure statistical primitives
(`kalhas/application/campaign_outcome_statistics.py`, stdlib-only); (2)
pure strategy/objective outcome builder (`campaign_outcome_runtime.py`);
(3) deterministic matrix identity (`campaign_outcome_identity.py`); (4)
pure complete matrix builder (`campaign_outcome_matrix_runtime.py`) -
strict serializer-based revalidation of all three sources, independent
identity/content-hash verification (profile, realization matrix and
every nested realization, observation matrix), exact cross-source
consistency (tenant/scenario/campaign/world/seed/timestamp/comparison
mode/realization tuples), independent observation-matrix structural
verification, binding-provenance and raw-value-kind checks, and the
single safe typed `CampaignOutcomeDistributionMatrixIntegrityError`
boundary; (5) independently verified read-only query service
(`campaign_outcome_query_service.py`). The query revalidates
tenant/campaign/scenario/world ownership and identity, exactly COMPLETE
state, recorded runtime exactly 3.0.0, evaluation profile, uncertainty
model, realization matrix, observation matrix, exact run-plan/strategy/
seed ordering, objective/metric bindings and units, and every
identity/content hash and numeric invariant. Querying never executes,
replays, extracts, repairs, creates, or writes an upstream artifact and
records no operational activity; repeated queries are byte-identical.

### API and compatibility

`GET /v1/campaigns/{campaign_id}/outcome-distributions`
(`kalhas/api/routes_campaign_outcome.py`): required `X-Tenant-ID`; no
request body; no runtime selector - the runtime is derived exclusively
from the recorded `RunPlan` tuple (every plan must be exactly 3.0.0;
empty plan tuples and any other recorded runtime fail closed with the
typed 409 `conflict` before the query service is invoked); direct
`CampaignOutcomeDistributionMatrix` response; safe typed 404
(unknown/foreign campaign; missing embedded evaluation profile) and 409
(`invalid_state` non-COMPLETE; `conflict` runtime; `integrity_error`
missing/corrupted upstream artifacts) with generic non-leaking bodies;
repeated byte-identical reads; no mutation methods; no operational
activity. Phase 25's six paths / seven operations are preserved
unchanged; `API_VERSION` (`"1"`) and `SCHEMA_VERSION` (`"1.0.0"`) are
unchanged; runtime remains exactly 3.0.0; runtime 1.0.0/2.0.0 behavior
is preserved.

### 100-seed causal acceptance proof

`tests/phase26_helpers.py` + `tests/test_phase26_acceptance.py` prove,
through the real lifecycle: 100 fixed authoring-time seeds (81 branch-X
+ 19 branch-Y; the tuple is selected once at authoring time and never
searched, retried, randomized, or adapted at runtime); 100 realizations,
never 200; two genuinely distinct declared strategies (`mock-a`
`[t-x, t-y]`, `mock-b` `[t-y, t-x]`); 200 runtime-3 executions and 200
explicit observation extractions; identical per-seed realization
identity/hash across both strategies (all 100 seeds); branch values 5
and 9 causally producing observed values 84 and 103 through the real
guarded transitions (one `applied` + one `guard_not_satisfied` per run,
opposite attempt orders); exactly 81 target achievements and 19 misses
with `empirical_target_achievement_probability == 0.81`; minimum 84.0;
maximum 103.0; arithmetic mean 87.61; median 84.0; population standard
deviation 7.453717193454551; Type-7 p05/p25/p75 = 84.0 and p95 = 103.0;
worst normalized target violation 0.03; CVaR95 normalized target
violation 0.03; adverse-tail statistic 103.0; representative exact
replay for both realized branches (seed-000 and seed-002: manifest
pair, expected == recomputed execution and observation hashes,
idempotent, writes only the manifest pair); repeated GET equality
(identifier, content hash, ordering, samples, `derived_at` lineage) and
unchanged store state (complete store digest, zero operational
activity, no artifact creation, no stored outcome matrix); no injected
or patched result (exactly 200 RunPlan records, 200 execution records,
200 observation-set records, 2 StrategyTrajectoryPlan records - one per
strategy - and 2 strategy candidates over 100 shared world
realizations; the only test-side patch is the sanctioned
`EXPECTED_STRATEGY_SET_SIZE == 2` alignment inside the single
preparation call). Matrix identifier
`campaign-outcome-distribution-matrix-4c9a997c4f57df7d`; content hash
`a5717de324af501c937b8b87cd114006edda1311ff811bd64fe0893f8ec5c230`;
`derived_at` `2026-01-01T12:00:00Z`.

### Non-goals and next phase

No paired strategy comparison, feasibility policy, Pareto analysis,
regret/minimax selection, ranking or campaign decision brief, adaptive
policy runtime, KALHAS-PAN, historical benchmark, real LEGION/NEXUS
integration, or production database/queue/auth/deployment/command-center
expansion. No reality-prediction or true-causality claims. **Phase 27**
(robust paired comparison and campaign decision brief) is the next
authorized implementation target - its authoritative design already
exists in the external blueprint and the Phase 26 start handoff - and
Phase 27 implementation begins only after Phase 26 receives its
separate user-authorized local closure commit.

## Phase 27: robust paired comparison and campaign decision brief

**Status: IMPLEMENTATION-COMPLETE, GATE-GREEN LOCALLY, NOT YET
COMMITTED.** Phase 27 is implemented locally on top of the committed
Phase 26 baseline; it is **not committed** and **not pushed**
(`origin/main` remains `f40e83de468ca14100d011454d15eb3dd561c810`, local
`main` exactly two commits ahead), the Git index remains empty, and a
local closure commit requires a separate explicit user authorization.
The exact change set is recorded in `KALHAS_HANDOFF_PHASE_27.md`. This
section supersedes the historical Phase 26-checkpoint statements above
that Phase 27 "has not begun" / "is not implemented". Phase 28 and
KALHAS-PAN remain **not implemented** anywhere in the repository.

### Contracts

Three new top-level public contracts are appended at `PUBLIC_CONTRACTS`
indexes 47-49 (50 total; indexes 0-46 unchanged), each `extra="forbid"`,
frozen, self-hashing, and version-locked to the `Literal["3.0.0"]`
runtime:

- **`CampaignDecisionPolicy`** (index 47) - the immutable stored policy
  of one COMPLETE 3.0.0 campaign: campaign/scenario/world/
  evaluation-profile identity with scenario and world content hashes;
  `algorithm_identifier` literal
  `feasibility-pareto-minimax-regret-v1`; `target_requirement_mode`
  `global`/`per_objective` XOR with the global probability or the
  per-objective `ObjectiveTargetRequirement` tuple (exactly covering
  the profile's targeted objectives); the authoritative
  `ObjectiveWeightSnapshot` tuple in exact profile order (never
  sorted, never normalized); exact-int `minimum_sample_count >= 1`;
  finite non-negative `tie_tolerance`; the hard-gate flag; `tail_alpha`
  exactly `0.95` (fixed - callers cannot select another); deterministic
  caller-supplied timezone-aware `declared_at`; finite-only metadata;
  self-covering `content_hash`. Identifier prefix
  `campaign-decision-policy-` over the canonical
  `(tenant, campaign, scenario, world, profile, schema_version)`
  identity.
- **`CampaignStrategyComparison`** (index 48) - the derived comparison
  of a COMPLETE 3.0.0 campaign: campaign/scenario/world identity and
  hashes, `runtime_version` `"3.0.0"`, `comparison_mode`
  `identical_conditions`, the policy reference (identifier and content
  hash), the source outcome-matrix reference (identifier and content
  hash), ordered strategy/seed/objective identifiers, the complete
  `ObjectivePairedComparison` tuple (exactly `S * (S - 1) * O`
  records, no self-pairs, both directions of every pair, contiguous
  positions), the `DominanceRelation` tuple, and one
  `StrategyRobustnessProfile` per strategy (feasibility, dominance
  facts, per-objective weighted regret, per-seed total weighted
  regrets, median/p95/maximum totals). Identifier prefix
  `campaign-strategy-comparison-` over the canonical
  `(campaign, world, profile, policy, source outcome matrix)`
  identity; `derived_at` = outcome-matrix `derived_at`.
- **`CampaignDecisionBrief`** (index 49) - the deterministic brief:
  identity and hashes, the policy and comparison references, `status`
  `preferred`/`inconclusive`/`insufficient_evidence`/
  `no_feasible_strategy`, `preferred_strategy_id` present iff
  `preferred`, the terminal `DecisionReasonRecord` with its exact code
  shape, ordered `DecisionFactorRecord` trails (decisive then
  blocking), the considered/tie-set strategy tuples, and the fixed
  template `summary` (no chain-of-thought, no hidden reasoning, no
  unexplained scalar). Identifier prefix `campaign-decision-brief-`
  over the canonical `(campaign, world, policy, comparison)` identity;
  `produced_at` = comparison `derived_at`.

The 12 nested decision value objects
(`ObjectiveWeightSnapshot`, `ObjectiveTargetRequirement`,
`ObjectivePairedComparison`, `ObjectiveFeasibilityEvidence`,
`ObjectiveRegretEvidence`, `ObjectiveProbabilityEvidence`,
`ObjectiveDownsideEvidence`, `ObjectiveDominanceStatus`,
`DominanceRelation`, `StrategyRobustnessProfile`, `DecisionReasonRecord`,
`DecisionFactorRecord`) stay unregistered with no standalone schema
artifacts. Three new schema artifacts
(`CampaignDecisionPolicy.schema.json`,
`CampaignStrategyComparison.schema.json`,
`CampaignDecisionBrief.schema.json`) bring `schemas/v1/` to exactly 50;
each matches `model_json_schema()` and all 47 historical byte hashes
are unchanged. The legacy `DecisionBrief`/`EvidenceReference` contracts
are untouched; evidence references are inline id/hash pairs.

### Decision protocol (frozen)

- Pipeline: evidence sufficiency (`K >= minimum_sample_count`) ->
  hard-gate feasibility (inclusive `p >= threshold`; vacuous pass when
  gates are off or all objectives are optimization-only) -> Pareto
  among feasible strategies only -> minimax among feasible
  non-dominated strategies -> `preferred` iff the tolerance tie set is
  a singleton, else `inconclusive`; `insufficient_evidence` and
  `no_feasible_strategy` are successful statuses, never guesses and
  never manufactured winners.
- Tolerance semantics are exact IEEE comparisons (`|d| <= tol` ties,
  `d < -tol` wins, `d > +tol` losses; minimax tie set
  `<= best + tol` inclusive) - no `isclose`, relative tolerance, ULP
  relaxation, rounding, or arbitrary winner.
- Regret is same-seed comparative (minimize
  `(v - min_same_seed)/scale`, maximize
  `(max_same_seed - v)/scale`, reach
  `(|v - t| - min_same_seed_absdev)/scale`), weighted by the verified
  binding snapshots only, `math.fsum` everywhere, per-seed totals in
  objective order, median/p95/maximum through the accepted primitives.
- Identity/hash/timestamp lineage is deterministic: identifiers are
  hash-derived from canonical identity tuples (never content hashes,
  timestamps, or tenants), content hashes are canonical SHA-256 over
  the payload excluding `content_hash`, and every timestamp copies a
  recorded lineage value (`declared_at` from the caller, `derived_at`
  = outcome-matrix `derived_at`, `produced_at` = comparison
  `derived_at`) - never wall clock.

### Lifecycle and API

Declaration lifecycle: COMPLETE 3.0.0 campaign -> `POST
/v1/campaigns/{campaign_id}/decision-policy` (201, one immutable policy
per `(tenant_id, campaign_id)`; duplicate 409 `conflict`; invalid draft
422; non-COMPLETE 409 `invalid_state`; unknown/foreign campaign 404) ->
policy stored -> comparison/brief queries. **Policy-first query order**
on both GETs: campaign -> exactly COMPLETE -> verified policy (404
before any derivation when absent) -> verified outcome query exactly
once -> comparison builder exactly once -> (brief) brief builder
exactly once reusing the same policy/outcome/comparison chain. The
comparison and the brief are derived in memory and **never stored**
(the store has no comparison or brief collection and no put method);
the GETs never execute, replay, extract, evaluate, write, or record
operational activity; repeated queries are byte-identical and leave the
complete store state unchanged. The verified stored policy GET remains
available even after the campaign state changes away from COMPLETE.
Every operation requires `X-Tenant-ID`, reads the tenant-scoped
recorded `RunPlan` tuple first, and requires every recorded runtime
exactly 3.0.0 (empty or mixed/legacy tuples fail closed with the typed
409 before any service call); no caller runtime selector exists.

Error mappings (single `ApiErrorResponse` envelope, generic non-leaking
bodies): 404 unknown/foreign campaign and missing/foreign policy; 409
`invalid_state` non-COMPLETE; 409 `conflict` duplicate policy and
unsupported recorded runtime; 422 invalid policy drafts; 409
`integrity_error` corrupted/forged/validator-bypassed stored policy,
outcome, comparison, or brief. The 12 historical schema artifacts
around the outcome surface and every earlier path/operation are
unchanged; runtime 1.0.0/2.0.0 behavior is untouched.

### Acceptance proof and honest limitations

The 100-seed causal acceptance fixture (3 genuinely distinct declared
strategies over 100 fixed static seeds, 300 real executions and 300
explicit extractions, real policy declaration, verified queries only)
proves: mock-a has the best ordinary primary mean (32.46) but the worst
maximum total weighted regret (4.0) because its reserve collapses to 5
in every level-9 world; mock-b has primary mean 94.26 and the unique
minimax maximum total weighted regret (2.24) - the preferred strategy;
mock-c is dominated by mock-b; the tie control produces zero paired
deltas, no dominance, and an `inconclusive` brief with no winner. Best
ordinary mean is not the robust winner. Decision output is
**evidence-based under the declared models/policies** - **not
calibrated**, **not certainty**, and driving **no autonomous live
action**; it does not predict reality and is not a guarantee of any
outcome. Phase 28 and KALHAS-PAN are not implemented. The Colony UI
demo is intentional synthetic local visualization work (clearly
labeled deterministic client-side synthetic data, no network request),
not decision evidence and not a real forecast.
