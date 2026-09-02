# ADR 004: Deterministic adaptive runtime 4

- Status: Accepted
- Date: 2026-08-25
- Deciders: KALHAS foundation

## Context

KALHAS runs today execute immutable recorded transition plans under three
additive runtime versions: `1.0.0` (structural campaigns), `2.0.0`
(trajectory execution with exact replay), and `3.0.0`
(realization-aware execution from the seed's realized initial state).
Every observation in the shipped v1 surface is post-run evidence:
`DomainMetricObservationBinding` fixes `observation_point` to exactly
`final_state`, so metric observations are extracted after a completed
trajectory. They describe a run that has already finished and therefore
cannot drive any decision inside that run.

Phase 28 introduces deterministic **adaptive policies**: policies that may
change the applied action only in response to observations available at the
exact decision step where the decision is made. This requires an additive
runtime version `4.0.0`, new versioned contracts for causal observations,
timing, and closed policy language, and exact semantics for noise addressing,
fairness, persistence, and replay verification.

The strategic handoff's blocking decision register marks D28-01 through
D28-04 as `ADR required`: behavioral implementation for this scope stays
blocked until these decisions are frozen. This ADR is that freeze. It binds
every Phase 28 slice (`H28-S01` through `H28-S13`). No Phase 28
implementation exists at the time of writing; nothing here claims gates,
acceptance, or code that has not run.

All standing constraints remain in force: the kernel stays domain-neutral,
local-only, deterministic, and replayable; strategy comparison shares
identical conditions; and the shipped v1 public contract surface stays
backward compatible.

## Decision

Runtime `4.0.0` is **additive**. Runtimes `1.0.0`, `2.0.0`, and `3.0.0`
retain their exact historical meaning; recorded campaigns, executions,
replay manifests, and observation sets under those runtimes are never
reinterpreted, rewritten, re-dispatched, or given additional meaning.
Current `final_state` metric observations remain post-run evidence and
cannot drive adaptive decisions. Phase 28 remains domain-neutral,
local-only, deterministic, replayable, and free of callbacks, expressions,
imports, provider calls, network calls, LLM calls, or arbitrary executable
policy content. No fourth component and no new integration surface is
introduced; runtime 4 is ordinary governed KALHAS machinery inside the
existing NEXUS–LEGION–KALHAS architecture.

### Frozen contract names

Top-level persisted `VersionedContract` authorities, frozen exactly:

1. `RuntimeObservationDeclaration`
2. `ExternalObservationInputBundle`
3. `AdaptivePolicy`
4. `AdaptiveRunTrajectoryExecution`
5. `AdaptiveRunTrajectoryReplayManifest`

Strict frozen non-authoritative/nested contract roles, frozen exactly:

1. `AdaptivePolicyDraft`
2. `RuntimeObservationEvent`
3. `AdaptivePolicyStateSnapshot`
4. `AdaptivePolicyDecisionEvent`
5. `AdaptivePolicySwitchEvent`

`AdaptivePolicyDraft` is **untrusted input** and is never runtime
authority. Only the validated, KALHAS-bound immutable `AdaptivePolicy`,
plus either validated recorded external inputs (`ExternalObservationInputBundle`)
or freshly derived KALHAS observation events, can drive runtime-4
execution. The nested event/snapshot roles carry no independent authority;
their status is fixed by D28-04.

### D28-01 — Closed policy language and state machine

- Conditions use a **closed AST** only. There is no expression language,
  no negation surface, and no escape hatch.
- Numeric comparison operators are exactly: `lt`, `lte`, `eq`, `gte`, `gt`.
- Equality is exact. There is no tolerance, implicit coercion, clipping,
  NaN, Infinity, negation, arbitrary expression, callback, or executable
  reference anywhere in the language.
- Compound nodes are only `all` and `any`.
- Maximum AST depth: 4. Maximum total nodes per condition: 64.
  Compound-node fan-out: 2 through 8 inclusive.
- Child order is canonical; duplicate children are rejected.
- Each policy contains at most 64 rules. Rule priorities are unique
  non-negative integers, evaluated in ascending order.
- The first matching **eligible** rule wins. Ineligible matching rules are
  recorded and evaluation continues deterministically.
- Every policy declares an initial action and a fallback/no-match action.
- Draft actions are logical identifiers only. Bound `AdaptivePolicy`
  actions reference exact immutable trajectory-plan identifiers and
  content hashes.
- Missing behavior is explicit and is exactly `false` or `error`; it is
  never inferred from truthiness.
- Hysteresis is represented with separate explicit enter and retain
  conditions, never with an implicit tolerance. When the current action is
  already a rule's target, its retain condition controls retention;
  otherwise its enter condition controls entry.
- Minimum dwell counts completed action applications: if an action is
  installed at decision `d` with minimum dwell `N`, the earliest different
  action is selectable at `d + N`.
- Cooldown `N` requires `N` complete intervening decision points after a
  switch at `s`; the earliest next switch is `s + N + 1`.
- Initialization is not a switch and consumes no budget.
- Global and per-rule switch budgets decrement only on an actual action
  change. Selecting or retaining the current action is not a switch.
- Exhausted dwell, cooldown, or budget retains the current action and
  records a deterministic blocked reason. The fallback action cannot
  bypass eligibility or budgets.
- Policy state is immutable evidence for each decision. A policy cannot
  learn or mutate during a run. A changed policy requires a new immutable
  identity and a new campaign/run authority; replay history is never
  rewritten.

### D28-02 — Causal observation and step semantics

The zero-based causal schedule within one decision step is frozen:

```text
resolve step-addressed external/exogenous inputs
-> observe the currently visible pre-action state
-> validate and record causal observations
-> expose only observations whose availability step is the current decision step
-> evaluate eligible ordered policy rules
-> select or retain the action and record decision/switch evidence
-> apply the validated action
-> record the resulting state and emissions
-> expose delayed emissions only at their declared later decision step
```

- Integer step indexes, not wall-clock time, determine causality. Any
  simulation timestamp is deterministically derived and informational.
- Cadence uses `start_step >= 0` and `every_n_steps >= 1`. A declaration
  is scheduled at step `step` exactly when
  `step >= start_step` and `(step - start_step) mod every_n_steps == 0`.
- `delay_steps >= 0`. An observation sourced at step `s` becomes eligible
  at `s + delay_steps`. `delay_steps == 0` permits same-decision use
  because observation precedes evaluation in the schedule.
- Simultaneously available observations are ordered canonically by
  observation declaration identity.
- Only explicitly declared visible state fields may be observed. Latent
  state is never implicitly visible.
- Expected-but-unavailable data produces explicit missing evidence.
  Missing behavior is handled only through the declared `false`/`error`
  rule.
- Future, late, duplicate, reordered, foreign-tenant, foreign-world,
  foreign-seed, forged, or undeclared observations fail closed and
  atomically.
- State-derived observations are recomputed during replay from the
  verified state and declaration authority. Recorded state-derived values
  are evidence to verify, never values to inject back into replay.
- Truly external/offline observations are accepted only through an
  immutable `ExternalObservationInputBundle`.
- Terminal observations may be recorded as evidence but have no available
  decision step and cannot trigger an action after the final action has
  already occurred.

### D28-03 — RNG addressing and fairness

Observation-noise draws are **counter/key-addressed**. The canonical noise
coordinate contains exactly:

- domain literal: `kalhas-observation-noise-v1`
- sampler version: `sha256-counter-v1`
- runtime version: `4.0.0`
- `world_content_hash`
- `seed_content_hash`
- `runtime_observation_declaration_content_hash`
- `source_step_index`
- local `draw_index`

Additionally:

- No strategy identity, policy identity, branch count, rule count,
  execution order, or mutable global RNG position enters the exogenous
  noise coordinate.
- Draw indexes are local to one declaration and source step.
- World uncertainty, observation noise, and future mechanism randomness
  use separate domains/streams (world realization keeps its established
  `sha256-counter-v1` domain; runtime-4 observation noise uses the
  `kalhas-observation-noise-v1` domain above; mechanism randomness, when
  introduced, gets its own domain).
- Policy evaluation consumes no RNG.
- Shared world/seed/declaration coordinates yield identical exogenous
  noise across strategies.
- Strategy-dependent endogenous state may differ, but adaptive branching
  cannot shift future exogenous conditions.
- `ExternalObservationInputBundle` values are already accepted immutable
  inputs and do not receive fresh runtime noise.

### D28-04 — Persistence versus verified derivation

Persisted immutable authorities (exactly the five top-level contracts):

- `RuntimeObservationDeclaration`
- `ExternalObservationInputBundle`
- `AdaptivePolicy`
- `AdaptiveRunTrajectoryExecution`
- `AdaptiveRunTrajectoryReplayManifest`

Not independently persisted (exactly the five nested roles):

- `AdaptivePolicyDraft`
- `RuntimeObservationEvent`
- `AdaptivePolicyStateSnapshot`
- `AdaptivePolicyDecisionEvent`
- `AdaptivePolicySwitchEvent`

The non-persisted event/snapshot roles are nested, hash-covered evidence
inside `AdaptiveRunTrajectoryExecution`.

- `ExternalObservationInputBundle` is strategy-independent and bound to
  the campaign, world, and scenario seed; every compared strategy receives
  the same ordered external inputs.
- `AdaptiveRunTrajectoryExecution` is the single aggregate runtime-4
  authority for one run. Its content hash covers the ordered causal
  observation events, pre-decision policy-state snapshots, decision
  events, switch events, state/trajectory results, and all
  world/seed/policy/runtime provenance.
- Replay independently recomputes state-derived observations, addressed
  noise, policy decisions, switches, and state evolution, then verifies
  canonical bytes and hashes against the stored authority.
- Query projections are read-only verified derivations from stored
  authority and do not persist new evidence. Comparison and decision-brief
  projections remain derived and unpersisted.
- Authoring/binding and execution use complete preflight, detached
  computation, and zero-or-one atomic writes. Failure produces no partial
  authority and no activity event. Activity may be recorded only after the
  authoritative write succeeds.

## Compatibility consequences

- The existing 50 v1 `PUBLIC_CONTRACTS` remain an immutable prefix; their
  identities, registration indexes, and ordering do not change.
- Existing v1 JSON schemas remain byte-identical.
- Phase 28 additions may append new backward-compatible v1 contracts but
  may not mutate existing required fields, literals, meanings, schema
  artifacts, or runtime dispatch. Breaking changes would require new
  version modules and API segments, which Phase 28 does not do.
- `H28-S01` is the next implementation session and begins only after this
  ADR has been independently audited.
- `H28-S01` may implement only causal observation/timing contracts and
  schemas. `H28-S02` and later behavior must not be started in that
  session.

## Consequences

- Adaptation becomes causally sound: a produced observation can influence
  only the decision point at which it is already available, and post-run
  evidence can never masquerade as mid-run input.
- Fair comparison is structurally preserved: shared coordinates yield
  identical exogenous noise across strategies regardless of how many rules
  a policy evaluates or which branch it takes.
- The closed, bounded policy language is small enough to evaluate
  exhaustively and adversarially; richness (tolerances, expressions,
  learned behavior) is deliberately excluded rather than approximated.
- Every runtime-4 run yields one self-hashing authority whose evidence can
  be re-verified independently of execution order, extending the existing
  exact-replay guarantees to adaptive runs.
- Historical runtimes stay untouched, so existing goldens, replays, and
  published meaning are unaffected; the cost is parallel dispatch and
  duplicated provenance fields across runtime versions.
- Policy improvement requires issuing a new immutable policy identity and
  a new campaign/run authority - mutation-free by construction, at the
  price of no in-place experimentation.
