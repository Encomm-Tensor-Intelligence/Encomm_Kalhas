# ADR 003: Immutable versioned world contracts and deterministic campaign lifecycle

- Status: Accepted
- Date: 2026-08-08
- Deciders: KALHAS foundation

## Context

KALHAS must support deterministic simulation campaigns, evidence, and replay
across arbitrary future domains. Two failure modes threaten that goal:
mutating world models in place (making replay and fair comparison
impossible), and implicit or ad-hoc campaign state handling (making behavior
undecidable and untestable).

## Decision

1. **World models are immutable, versioned, compiled artifacts.**
   `WorldVersion` (schema version `1.0.0`) is frozen by contract
   (`frozen=True`): no attribute assignment after validation. Versions form
   a chain via `parent_version_id`. The contract direction is
   `ScenarioSpec -> validation -> WorldVersion -> CampaignSpec`: scenarios
   carry no world reference, worlds carry provenance (`source_scenario_id`,
   `compiler_version`, `content_hash`), and campaigns reference an already
   compiled world (`world_version_id`).

2. **Every public contract is versioned and strict.** All top-level contracts
   carry `identifier`, `tenant_id`, and a semantic `schema_version`; unknown
   fields are rejected (`extra="forbid"`). Domain-specific values appear only
   as JSON-safe data or declared metadata - never as executable code,
   callbacks, or plugin references. JSON Schema artifacts are exported
   deterministically, checked in under `schemas/v1/`, and enforced in sync by
   tests.

3. **The campaign lifecycle is an explicit, pure state machine.** The seven
   states (`DRAFT`, `VALIDATED`, `COMPILED`, `RUNNING`, `COMPLETE`, `FAILED`,
   `CANCELLED`) and their transitions are declared in
   `kalhas/application/campaign_lifecycle.py`. Invalid transitions raise the
   typed `CampaignTransitionError`. The machine has no persistence, no
   FastAPI dependency, and no side effects; it is deterministic by
   construction.

4. **Fair comparison is a structural invariant, not a caller-adjustable
   default.** `CampaignSpec` owns a shared, ordered, non-empty
   `seed_ensemble` of `ScenarioSeed` contracts with unique identifiers; every
   strategy candidate receives the exact same ordered seed identifiers and
   equivalent observation permissions. `comparison_mode` is a single-value
   literal (`identical_conditions`) that appears as a `const` in the JSON
   Schema, so no independent mode can be expressed. Scenario-level input does
   not own seed assignment. `RunEvent` carries per-run `sequence` plus
   simulation time and creation time so runs can be replayed deterministically.

5. **No campaign API endpoints yet.** The lifecycle is a domain-level
   capability; exposing it over HTTP is deferred to a later phase.

6. **World compilation is a deterministic pure function.** The compiler
   accepts only semantically valid scenarios (rejected ones raise
   `InvalidScenarioError` carrying the validation report). The content hash
   is SHA-256 over canonical JSON of `{compiler_version, scenario}`; the
   world identifier derives from the hash, and timestamps are derived from
   scenario input, so compilation never uses randomness, wall-clock time,
   network access, or a provider. The compiled world is a generic
   declarative representation only - no simulation mechanisms.

## Consequences

- Replay and fair strategy comparison are structurally enforced (shared
  ordered seed ensemble, single `identical_conditions` mode, immutable
  inputs, recorded ordering).
- Contracts are machine-checkable: strict validation, schema artifacts, and
  round-trip tests for every public contract.
- Lifecycle behavior is fully unit-testable (all 49 transition pairs are
  exercised).
- Terminal states are final; re-running a failed campaign requires a new
  campaign (deliberate simplicity).
- The schema-export tooling adds a regeneration step whenever contracts
  change; the sync test prevents silent drift.
