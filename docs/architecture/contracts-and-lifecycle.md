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
