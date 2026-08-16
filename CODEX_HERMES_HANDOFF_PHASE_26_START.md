# Codex–Hermes Orchestrator Handoff — Phase 26 Start

Date prepared: 2026-08-15  
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`  
Purpose: self-contained context for starting a **new Codex chat** after the
local completion of KALHAS Phase 25, with the authoritative Phase 26 and
Phase 27 implementation scope incorporated from the user's original blueprint.

> **Critical role reminder / κρίσιμη υπενθύμιση:** Codex is the
> **orchestrator and reviewer**. Hermes is the external implementation agent.
> The user manually copies Codex prompts into Hermes and returns Hermes reports
> to Codex. Do not confuse Hermes with Codex, do not tell the user to open a
> “new Codex session” when the intended action is a new Hermes session, and do
> not silently take over Hermes's implementation role.

---

## 1. Read order in the next Codex chat

Before proposing Phase 26 work, the new Codex chat must read completely:

1. `AGENTS.md`
2. `CODEX_HERMES_HANDOFF_PHASE_26_START.md` (this file)
3. `C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md`
4. `KALHAS_HANDOFF_PHASE_25.md`
5. `KALHAS_HANDOFF_PHASE_24.md`
6. `KALHAS_HANDOFF_PHASE_22.md`

Blueprint SHA-256:
`bbcb793be70e063cc57f1e74f2dc4f3dbf3a78237f3d84859a1bb393f19b0678`.

The blueprint was written against the old Phase 22 baseline
`215729d9b5ab081c0780be515585e91fd4fe77cd`. Its architectural and behavioral
requirements for Phases 26 and 27 remain the authoritative product design, but
its baseline/status/branch instructions are historical. The live repository,
the completed Phase 23–25 handoffs, the current local commit chain, and the
user's explicit no-push-until-Phase-27 workflow supersede those historical
state assumptions.

Then inspect the repository directly:

```powershell
git status --short
git diff --cached
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count origin/main...HEAD
git log -5 --oneline --decorate
```

The repository, not a prose report, is always the final source of truth.
Hermes reports are evidence to audit, never a substitute for direct inspection.

## 2. Exact repository state at handoff creation

The state immediately before this handoff file was created was:

- Branch: `main`
- Local HEAD:
  `e6a39e7bd51e7cf60d7eaeea8d710f6cdf4ad9e5`
- HEAD subject:
  `Phase 25: complete realization-aware runtime 3.0.0 closure`
- HEAD parent / remote `origin/main`:
  `f40e83de468ca14100d011454d15eb3dd561c810`
- Divergence `origin/main...HEAD`: `0 1`
- The Phase 25 closure commit is **local only and not pushed**.
- The working tree and index were clean after the Phase 25 commit.

Creating this handoff intentionally introduces exactly one new untracked file:

```text
?? CODEX_HERMES_HANDOFF_PHASE_26_START.md
```

The next chat must confirm that this is the only difference unless the user has
made additional changes in the meantime. Do not delete, stage, or commit it
without explicit user direction. It may be incorporated into a future local
Phase 26 commit if the user chooses.

### Historical integrity anchors

- `KALHAS_HANDOFF_PHASE_22.md` MD5:
  `d6a857f091bcf7ab596583054b55659e`
- `KALHAS_HANDOFF_PHASE_24.md` SHA-256:
  `8616d45e0c4727cbf027b7a3f133e749c33d2a6a328c6d6668c2e5f1108ea652`
- `KALHAS_HANDOFF_PHASE_25.md` SHA-256 at this handoff:
  `f316560ae215ca697219a6ea45372de2ef707ed8966e79be9d792f2871f9695f`

Do not edit the Phase 22, 24, or 25 handoffs during Phase 26 implementation.
Phase 26 must receive its own handoff only when Phase 26 is actually complete.

## 3. Git and publication policy

The user's explicit publication policy is:

- Phase 25 has one completed local commit.
- Phase 26 may receive its own local commit only after it is complete and only
  with explicit user authorization.
- Phase 27 will be handled the same way.
- **No GitHub push until both Phase 26 and Phase 27 are complete.**
- A push is an external publication action and always requires explicit user
  authorization at that time.

Therefore:

- Do not push now.
- Do not create or switch branches unless the user explicitly changes the
  workflow.
- Do not amend, squash, rebase, or rewrite the accepted Phase 25 commits.
- Do not stage or commit automatically merely because a slice is green.
- Never use destructive Git operations (`reset --hard`, forced checkout,
  force-push, history rewriting).
- Preserve `main` and the unpushed local commit chain through Phases 26 and 27.

## 4. Human/agent roles and operating model

### User

- Owns the project and the decision to begin a phase, accept a design, commit,
  or push.
- Runs separate Hermes sessions and manually transfers Codex prompts/reports.
- Sends Hermes reports and attachments back to Codex for review.

### Codex — orchestrator/reviewer

Codex must:

- Understand the architecture and current repository state.
- Audit every Hermes report against the actual folder, diffs, source, tests,
  and Git state.
- Detect fail-open logic, incomplete trust boundaries, test-only false proofs,
  stale documentation, hidden scope expansion, and inaccurate gate claims.
- Produce precise, bounded, copy-paste prompts for Hermes.
- Specify exact allowed files, forbidden files, invariants, adversarial tests,
  gates, Git restrictions, and stopping conditions.
- Approve a slice only after direct evidence supports the report.
- Prefer a corrective micro-slice over accepting a known integrity gap.

Codex must not:

- Confuse itself with Hermes.
- Claim access to a Hermes chat that was not attached or reported by the user.
- Invent Phase 26/27 requirements.
- Ask Hermes to make broad “continue everything” changes without exact scope.
- Treat “imports cleanly” or a focused happy-path test as phase completion.
- Stage, commit, push, branch, or perform external actions without explicit
  authority.

### Hermes — implementation agent

Hermes receives Codex's bounded prompt and performs the actual code/test/doc
work. Every Hermes prompt must require:

- Mandatory preflight reads (`AGENTS.md`, relevant handoffs/design/report).
- Direct inspection of current Git state and existing diffs.
- Exact allowed file scope.
- Explicit files/surfaces that must remain unchanged.
- Behavioral invariants and adversarial proofs.
- Required focused and full gates.
- An honest final report with exact results.
- No stage/commit/push/branch unless that specific prompt is explicitly a
  user-authorized Git operation.
- No Hermes profile, memory, skill, or self-improvement writes.
- A hard stop after the bounded slice.

## 5. Hermes session/token discipline

The user observed excessive token/credit usage in long Hermes sessions.
The established rule is:

> **At most two substantive Codex prompts per Hermes session. Then start a new
> Hermes session.**

Recommended rhythm:

1. Prompt 1: one bounded implementation/design slice.
2. Codex audits the Hermes report and repository directly.
3. Prompt 2: corrective micro-slice, completion pass, or gates/report.
4. End that Hermes session.
5. Start a new Hermes session for the next bounded slice.

Additional rules:

- An iteration-cap interim report is not a completed slice.
- If Hermes stops at a tool-iteration cap, Codex inspects the partial work and
  gives an exact continuation prompt if the two-prompt budget permits.
- If the cap occurs on prompt 2, the continuation goes to a **new Hermes
  session**.
- Never ask Hermes to repeat gates already independently proven unless files
  affecting those gates changed afterward.
- Keep prompts bounded enough to finish within one Hermes session when
  practical.
- Reports must distinguish “implemented”, “focused green”, and “full gates
  green”; never collapse these into one claim.

## 6. Durable KALHAS architecture rules

These rules come from `AGENTS.md` and remain binding in Phases 26 and 27:

### Only three components exist

- **NEXUS**: natural-language dialogue, organizational context, memory,
  presentation.
- **LEGION**: strategy and agent exploration.
- **KALHAS**: versioned world models, uncertainty, deterministic simulation
  campaigns, evidence, replay, and the future living-simulation experience.

Do not add a fourth component, service role, or integration surface.

### Kernel boundaries

- `kalhas/` remains domain-neutral.
- Domain concerns enter only as domain packs under `kalhas/domain_packs/`
  through the `DomainPack` protocol.
- KALHAS core never imports NEXUS or LEGION internals.
- The only permitted coupling is through the placeholder protocols in
  `kalhas/adapters/` (`NexusAdapter`, `LegionAdapter`).
- No real company or personal data in code, tests, fixtures, or docs.

### Determinism and safety

- Deterministic replay is mandatory.
- Fair strategy comparison means identical recorded conditions/shared seeds.
- No wall-clock authority where recorded timestamps exist.
- No nondeterministic randomness, live providers, network calls, databases, or
  real-world actions in the MVP.
- No hidden domain-pack execution or external configuration.
- Fail closed on corrupted, missing, mixed-version, reordered, duplicated,
  foreign-tenant, or self-consistently rehashed artifacts.
- Public errors remain typed, generic, and non-leaking.

### Contracts and compatibility

- `kalhas/contracts/v1/` contracts are frozen once shipped.
- Never break a v1 contract in place.
- Breaking changes require a new contract version module and API version
  segment.
- Historical runtime 1.0.0/2.0.0 behavior and Phase 24/25 artifacts must remain
  backward compatible unless a future approved design explicitly introduces a
  new versioned surface.
- Every behavior change requires tests.

## 7. What Phase 25 delivered

The exhaustive source of truth is `KALHAS_HANDOFF_PHASE_25.md`. The following
is the minimum context the next orchestrator must retain.

### Runtime and integrity core

- Added realization-aware trajectory runtime `3.0.0`.
- `verify_run_inputs` is version-dispatched and remains the authoritative
  single-pass base integrity chain.
- Runtime 3 reconstructs the Phase 24 world realization deterministically and
  binds its content hash into the run input hash.
- Runtime 1.0.0/2.0.0 historical behavior remains protected.
- `verify_run_trajectory_inputs` carries the verified realization for runtime
  3 without resampling.

### Lifecycle

- Runtime-3 campaign preparation and complete run-plan matrix preflight.
- Strategy-major/seed-minor planning under identical conditions.
- Realized initial-state trajectory execution through the real deterministic
  transition engine.
- Position-by-position attempt-to-authoritative-plan binding.
- Complete campaign execution preflight before the first write.
- Explicit immutable metric-observation extraction.
- Observation-aware exact replay requiring prior extraction.
- Generic + runtime-3 replay manifest pair with idempotent recovery for a
  missing half and fail-closed handling of corruption.

### Derived matrices

- Realization campaign trajectory matrix.
- Realization campaign metric-observation matrix.
- Realization campaign descriptive-statistics matrix.
- Realizations and all three matrices are derived in memory and never stored.
- Verified query services are read-only and record no operational activity.

### Strategy differentiation

- `MockLegionAdapter(declared_transition_sequences=...)` accepts exact
  per-strategy logical transition sequences.
- Order and repetitions are preserved.
- Unknown/ambiguous declarations fail closed with no canonical fallback.
- KALHAS remains the authority for identifiers, membership, and hashes.

### API surface

Exactly six runtime-3 paths and seven operations:

1. GET `/v1/runs/{run_id}/realization-trajectory-execution`
2. GET `/v1/runs/{run_id}/realization-trajectory-replay-manifest`
3. POST `/v1/runs/{run_id}/realization-metric-observations` (201)
4. GET `/v1/runs/{run_id}/realization-metric-observations`
5. GET `/v1/campaigns/{campaign_id}/realization-trajectory-matrix`
6. GET `/v1/campaigns/{campaign_id}/realization-metric-observation-matrix`
7. GET `/v1/campaigns/{campaign_id}/realization-metric-statistics`

Dispatch comes only from request runtime during preparation or recorded runtime
during execution/replay/query. Empty plan tuples and wrong runtimes fail
closed. Runtime-3 GETs and observation extraction record no activity.

### Contracts/schemas

- `PUBLIC_CONTRACTS == 46`.
- Exactly 46 schema artifacts.
- Phase 25 appended these six public contracts in exact order:
  1. `RealizationRunTrajectoryExecution`
  2. `RealizationRunTrajectoryReplayManifest`
  3. `RealizationCampaignTrajectoryMatrix`
  4. `RealizationRunMetricObservationSet`
  5. `RealizationCampaignMetricObservationMatrix`
  6. `RealizationCampaignMetricStatisticsMatrix`

### Causal acceptance proof

The final acceptance fixture proves actual engine-mediated variation:

- Two strategies with genuinely different plan order:
  - `mock-a`: `[t-x, t-y]`
  - `mock-b`: `[t-y, t-x]`
- `seed-0` realizes branch value 5; guarded `t-x` applies and produces 84.
- `seed-2` realizes branch value 9; guarded `t-y` applies and produces 103.
- Both strategies observe `[84, 103]` in seed order under shared realization
  conditions.
- Statistics: min 84, max 103, mean 93.5, median 93.5, population standard
  deviation 9.5.
- Replay regenerates identical execution and observation hashes.

### Corrective attacks already closed

Do not reintroduce these gaps:

1. Exact attempt-to-plan reference binding.
2. Complete stored campaign run-plan matrix preflight.
3. Execution tenant/world/strategy provenance in observation building.
4. Replay-manifest tenant ownership.
5. Campaign world-tenant and exact seed-content binding.
6. Observation-matrix strict trust boundary.
7. Empty-plan API dispatch/query fail-closed behavior.

## 8. Phase 25 verification baseline

At closure time:

- Full suite: `3214 passed, 1 skipped`.
- Focused Phase 25 suite: `806 passed`.
- Phase 25 matrix file: `217 passed`.
- Phase 25 boundary suite: `27 passed`.
- Phase 25 API suite: `36 passed`.
- `ruff check .`: passed.
- `ruff format --check .`: 241 files formatted.
- `mypy kalhas tests`: passed for 229 source files.
- `scripts/export_schemas.py --check`: synchronized.
- `git diff --check`: clean.

Expected benign environment/test observations:

- A Starlette/TestClient deprecation warning may appear; it was not a failure.
- One pre-existing approval-gated AGENTS boundary test is skipped.
- Known Phase 23 flaky test:
  `test_error_bodies_never_leak_values`, associated with incidental UUID
  substring `"91"`.

Known-flake protocol:

1. Use this protocol only when that test is the **sole** full-suite failure.
2. Rerun it isolated once.
3. Rerun the full suite once.
4. Report all results honestly.
5. Do not modify or weaken the flaky test merely to make the suite green.

## 9. Authoritative Phase 26 and Phase 27 plan

The original implementation blueprint was found outside the repository at:

```text
C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md
```

It was read completely when this handoff was prepared. Its Phase 26/27 design
is incorporated below so the next chat must **not** ask the user to resend or
reconstruct it from memory. The blueprint itself must still be read completely
and its SHA-256 checked before producing the first Hermes prompt.

No Phase 26 implementation has begun. Start with a direct read-only repository
audit mapping the design below onto the actual post-Phase-25 contracts,
services, routes, store seams, errors, schemas, and tests. If the live code
forces an implementation-detail adjustment, preserve the blueprint's semantics
and frozen-contract boundaries; do not silently weaken them.

### 9.1 Cross-phase objective and invariant chain

The target chain is:

```text
objective meaning
→ deterministic shared-seed world realizations
→ realization-aware runtime 3.0.0 execution
→ empirical campaign outcome evidence
→ paired robust strategy comparison
→ auditable campaign decision brief
```

Three concepts must remain distinct:

1. **Base world:** immutable compiled scenario and declarations.
2. **World realization:** one deterministic sample for one shared seed,
   independent of strategy.
3. **Strategy outcome:** the result of executing a strategy inside that exact
   realization.

The same seed must always mean the same realized world for all strategies.
Every Phase 26/27 artifact must preserve deterministic identity, canonical
hashing, complete provenance, tenant ownership, snapshot isolation, exact
ordering, safe errors, and fail-closed verification.

### 9.2 Phase 26 — empirical campaign outcome distributions

**Objective:** transform the verified runtime-3 observations from Phase 25 and
the objective-evaluation semantics from Phase 23 into empirical outcome and
risk evidence per strategy/objective.

**Hard claim boundary:** Phase 26 produces evidence only. It must not rank,
select, prefer, or recommend a strategy. Allowed terms include
`empirical_target_achievement_probability` and `empirical_quantile`. Forbidden
claims include confidence intervals, forecast certainty, universal real-world
probability, winner, preference, and recommendation. Do not bootstrap a
confidence interval without a future explicit sampling/calibration contract.

Add a focused additive contract module, suggested:

```text
kalhas/contracts/v1/campaign_outcome.py
```

Do not mutate shipped contracts and do not reuse the per-run `OutcomeVector`
for campaign distributions.

#### `EmpiricalDistributionSummary`

It must contain and internally validate:

- exact ordered samples in authoritative shared-seed order;
- sample count;
- minimum, maximum, arithmetic mean, median, and population standard
  deviation;
- deterministic empirical quantiles `p05`, `p25`, `p75`, and `p95`;
- an explicit quantile algorithm identifier, recommended
  `hyndman-fan-type-7-v1`;
- finite values only, with bool rejected as numeric input.

The finite-sample and interpolation behavior must be explicitly documented and
golden-tested, including one-sample and short-tail cases.

#### `StrategyObjectiveOutcome`

For one strategy/objective it must bind:

- authoritative strategy/objective positions and identifiers;
- metric identifier and unit;
- direction, target, tolerance, weight, and normalization scale snapshots;
- observed values in exact shared-seed order and their empirical summary;
- target-achievement count and empirical probability when a target exists;
- `null` target probability for optimization-only objectives;
- normalized target-violation distribution and worst violation when targeted;
- target-violation CVaR at the fixed documented alpha `0.95` when targeted;
- an orientation-aware adverse-tail statistic in the metric's original unit.

Target downside must reuse Phase 23 normalized target-violation semantics:

```text
minimize: max(0, value - target) / normalization_scale
maximize: max(0, target - value) / normalization_scale
reach:    max(0, abs(value - target) - tolerance) / normalization_scale
```

The original-unit adverse-tail statistic is:

```text
minimize: upper-tail mean of observed values
maximize: lower-tail mean of observed values
reach:    upper-tail mean of absolute deviation from target
```

For optimization-only objectives, target probability, target violation, and
target-violation CVaR remain `null`, while the direction-aware adverse-tail
statistic remains available. The exact finite-sample tail selection and any
interpolation must be public, deterministic, documented, and tested.

#### `CampaignOutcomeDistributionMatrix`

The top-level matrix must include:

- campaign, scenario, world, and recorded runtime identity;
- evaluation-profile identifier/hash;
- uncertainty-model identifier/hash when present;
- realization-matrix identifier/hash;
- source metric-observation-matrix identifier/hash;
- ordered strategy, seed, objective, and metric identifiers;
- the complete strategy-major → objective-minor outcome tuple;
- deterministic identifier/content hash and authoritative timestamp lineage.

#### Pure builder, verified query, API

The pure builder consumes only already verified inputs. The public read-only
query service must independently verify, before deriving evidence:

1. campaign identity, state, and recorded runtime;
2. base-world identity and every source hash;
3. evaluation-profile integrity;
4. uncertainty-model and realization-matrix integrity;
5. complete runtime-3 metric-observation-matrix integrity;
6. exact ordered seed alignment for every strategy;
7. objective-to-metric bindings and units;
8. all numeric and statistical invariants.

Required endpoint:

```text
GET /v1/campaigns/{campaign_id}/outcome-distributions
```

The query is deterministic, repeatable, read-only, and must never repair,
replay, execute, extract, create, or write upstream artifacts.

#### Phase 26 proof set

At minimum prove:

- quantile golden vectors for odd, even, small, repeated, negative, and mixed
  int/float samples, plus exact one-sample behavior;
- target-probability boundaries and optimization-only `null` behavior;
- normalized target violations for minimize/maximize/reach;
- CVaR/adverse-tail golden vectors and finite-sample edges;
- exact strategy/objective/seed ordering and Cartesian completeness;
- missing/additional/reordered seeds and source-matrix mismatches rejected;
- self-consistently rehashed tampered evaluation, uncertainty, realization,
  observation, or ownership inputs rejected;
- bool/non-finite rejection, tenant isolation, snapshot isolation, stable
  identifier/hash/timestamp lineage, API/OpenAPI safe errors;
- explicit absence of ranking, winner, preferred strategy, recommendation,
  LLM narrative, NEXUS invocation, and LEGION invocation.

Acceptance evidence may truthfully report facts such as `81/100 = 0.81`,
median, P05–P95 empirical interval, worst normalized violation, and CVaR95. It
must still refuse to state that the strategy is preferred.

#### Recommended Phase 26 slice order

The orchestrator must confirm exact file scope after the read-only audit, then
keep Hermes slices bounded. A safe decomposition is:

1. contract design + pure deterministic statistics/quantile/tail primitives;
2. pure strategy-objective outcome builder + integrity verifier;
3. complete campaign matrix builder + strict source-boundary verification;
4. verified read-only query/store integration, if persistence references are
   actually required by the accepted design;
5. route/API/OpenAPI/schema assembly;
6. adversarial correction slices as needed;
7. causal acceptance fixture, architectural boundaries, docs, Phase 26
   handoff, full gates, independent audit, then user-authorized local commit.

Do not blindly force this decomposition if the live architecture reveals a
safer smaller seam. One slice should own one trust boundary and one proof set.

### 9.3 Phase 27 — robust paired comparison and campaign decision brief

**Objective:** compare strategies under the exact same shared-seed world
realizations and create an auditable campaign-level decision artifact. A
preference is permitted only when declared rules uniquely justify it;
`inconclusive` is a valid successful result.

Paired analysis is mandatory:

```text
delta(seed-i) = loss(strategy A, seed-i) - loss(strategy B, seed-i)
```

Do not compare only independent means. The seed pairing is the fairness basis
of the entire comparison.

#### `CampaignDecisionPolicy`

Add an immutable, declarative policy with no arbitrary expressions, scripts,
callbacks, provider references, or executable templates. It must bind:

- campaign, scenario, and evaluation-profile identity;
- per-objective or explicit global minimum empirical target-achievement
  probability;
- CVaR alpha matching Phase 26;
- tie tolerance;
- whether all targeted objectives are hard feasibility gates;
- objective weights copied from the authoritative scenario;
- explicit comparison algorithm version;
- deterministic identifier/hash/timestamp.

Recommended algorithm identifier:

```text
feasibility-pareto-minimax-regret-v1
```

Only one immutable policy is allowed per campaign, declared before brief
generation. It must never alter simulation or evidence artifacts.

#### Stage A — eligibility and evidence sufficiency

- A strategy is feasible only if every hard targeted objective reaches the
  policy threshold.
- Optimization-only objectives do not affect target feasibility, but do affect
  paired comparison, Pareto analysis, and regret.
- Missing, inconsistent, under-sized, or directionally unorientable evidence
  yields `insufficient_evidence`; never guess.

#### Stage B — paired objective deltas

Positive always means the first strategy is worse:

```text
minimize: (value_A - value_B) / normalization_scale
maximize: (value_B - value_A) / normalization_scale
reach:    (abs(value_A - target) - abs(value_B - target))
          / normalization_scale
```

For every ordered strategy pair/objective expose exact paired deltas,
win/tie/loss counts and rates under the policy tolerance, median, p05, p95, and
worst paired delta. Negative means the first strategy is better; within the
declared tolerance is a tie.

#### Stage C — Pareto dominance

A strategy dominates another only if it is no worse across every required
declared measure and strictly better in at least one. Preserve the exact
objective evidence that supports or prevents dominance.

#### Stage D — minimax weighted regret

Regret is comparative and distinct from target violation. Compute it per seed
and objective from values observed under that same realization:

```text
minimize: (value - same-seed minimum across strategies) / scale
maximize: (same-seed maximum across strategies - value) / scale
reach:    (absolute deviation from target
           - same-seed minimum absolute deviation) / scale
```

Expose per-objective weighted regret, per-seed total weighted regret, median
total regret, p95 total regret, and maximum total regret. The robust candidate
minimizes maximum total weighted regret among feasible, non-dominated
strategies.

#### Stage E — recommendation decision

Allowed statuses only:

- `preferred`
- `inconclusive`
- `insufficient_evidence`
- `no_feasible_strategy`

`preferred_strategy_id` is present only for `preferred`, and `preferred` is
allowed only when exactly one candidate remains justified after feasibility,
dominance, minimax regret, and tie-tolerance rules. A tie returns
`inconclusive` without manufacturing a winner.

#### Comparison and brief contracts

Suggested additive module:

```text
kalhas/contracts/v1/campaign_decision.py
```

Do not mutate or repurpose the shipped single-strategy `DecisionBrief`. Add:

- `ObjectivePairedComparison`: exact paired deltas and decomposed win/tie/loss
  evidence for one ordered strategy pair/objective;
- `StrategyRobustnessProfile`: feasibility, target probabilities, downside
  risk, regret decomposition, dominance relations, and evidence references;
- `CampaignStrategyComparison`: complete ordered comparison matrix with
  policy/algorithm provenance, source outcome matrix identity/hash, and
  deterministic content hash;
- `CampaignDecisionBrief`: campaign-level decision status, optional preferred
  id only when justified, authoritative strategy order, deterministic factual
  summary templates, robustness profiles, stable reason codes with structured
  decisive/blocking values, authoritative assumptions, uncertainty/sampling
  provenance, full evidence references, deterministic hash and timestamp.

The brief must contain no chain-of-thought, hidden reasoning, fabricated prose,
unexplained scalar score, or LLM-generated narrative.

#### Phase 27 API

```text
POST /v1/campaigns/{campaign_id}/decision-policy
GET  /v1/campaigns/{campaign_id}/decision-policy
GET  /v1/campaigns/{campaign_id}/strategy-comparison
GET  /v1/campaigns/{campaign_id}/decision-brief
```

Policy creation verifies campaign/evaluation/objective coverage and thresholds.
Comparison and brief endpoints are read-only deterministic derivations. Do not
call `NexusAdapter.present`, LEGION, providers, networks, or live actions.

#### Phase 27 proof set

At minimum prove:

- exact same-seed paired alignment; reordered/missing/additional seeds fail;
- win/tie/loss behavior exactly at tolerance boundaries;
- feasibility thresholds exactly below/at/above boundaries;
- Pareto dominance and non-dominance;
- per-seed/per-objective regret golden vectors;
- unique minimax robust selection;
- `inconclusive`, `insufficient_evidence`, and `no_feasible_strategy` cases;
- no preferred id for any non-`preferred` status;
- complete evidence chain and deterministic reason codes/summary text;
- deterministic identifiers, hashes, timestamps, ordering, and repeated-query
  equality;
- tamper rejection at every source boundary, tenant/snapshot isolation, safe
  API/OpenAPI errors;
- absence of NEXUS/LEGION calls, arbitrary expressions, real-world action, and
  domain-specific kernel logic.

#### End-to-end Phase 27 demonstration

Create one generic domain-neutral fixture with:

- one scenario;
- at least two objectives with different directions;
- explicit objective-to-metric bindings;
- at least two uncertain numeric state fields;
- at least three genuinely different strategies;
- at least 100 shared seeds for the demonstration while ordinary unit tests
  remain small and fast;
- runtime 3.0.0 execution, selected exact replay, observations, Phase 26 outcome
  distributions, paired comparison, and one decision brief.

It must visibly prove different worlds across seeds, identical same-seed worlds
across strategies, genuinely different outcomes, a case where best mean need
not mean most robust under downside/minimax regret, and traceability of every
final claim to exact realization/run evidence.

#### Recommended Phase 27 slice order

After Phase 26 is fully green and locally committed with user authorization:

1. read-only design mapping and policy/contract invariants;
2. immutable decision-policy declaration and verification;
3. paired comparison primitives and ordered comparison builder;
4. feasibility and evidence-sufficiency layer;
5. Pareto + per-seed weighted-regret + minimax selection;
6. deterministic campaign decision brief;
7. query/API/OpenAPI/schema assembly;
8. adversarial corrections as needed;
9. 100-seed causal demonstration, boundary suite, docs, Phase 27 handoff, full
   gates, independent audit, then user-authorized local commit;
10. only after both phases are complete, perform the final repository audit and
    ask the user separately for explicit GitHub push authorization.

### 9.4 Explicit non-goals through Phase 27

- No adaptive policy switching or runtime 4.0.0 (Phase 28).
- No domain-mechanism protocol or KALHAS-PAN implementation (Phase 29).
- No historical/calibration benchmark (Phase 30).
- No real LEGION/NEXUS integration or MCP surface (Phase 31).
- No database, queue, auth system, production deployment, or command-center UI
  (Phase 32).
- No claim that KALHAS predicts reality or proves true causality.

The preserved positioning is: KALHAS builds bounded reproducible possible
worlds, tests strategies under identical uncertainty, and identifies robust
decisions under declared assumptions.

## 10. Required structure for future Hermes implementation prompts

Every implementation prompt should contain these sections:

### A. Baseline and mandatory reads

- Repository path.
- `AGENTS.md`.
- This orchestrator handoff.
- Latest official phase handoff.
- Approved design/corrective design attachment.
- Previous slice report.
- Current HEAD/origin/divergence/status.

### B. Exact scope

- Created files.
- Modified files.
- Explicitly forbidden files/surfaces.
- Current dirty paths to preserve.
- No staging/commit/push/branching.

### C. Behavioral contract

- Exact accepted versions and dispatch source.
- Read/write ordering.
- Tenant ownership.
- Identity/content-hash recomputation.
- Deterministic ordering/cardinality.
- Fail-closed conditions.
- Non-leaking errors.
- Runtime compatibility.

### D. Adversarial proofs

Tests should include self-consistently rehashed attacks, not only malformed
objects. Check, where relevant:

- missing/additional/reordered/duplicated records;
- foreign tenant/campaign/world/strategy/seed;
- mixed runtimes;
- valid alternate references from the same catalog;
- changed content with all dependent hashes recomputed;
- empty collections and first/middle/last omissions;
- no partial writes or activity on failure;
- input immutability and store deep-copy isolation;
- exact call counts and ordering;
- read-only repeated-query equality.

### E. Gates

At minimum, proportionate to the slice:

```powershell
uv run pytest -q <focused tests>
uv run ruff check .
uv run ruff format --check .
uv run mypy kalhas tests
uv run python scripts/export_schemas.py --check
git diff --check
```

Run `uv run pytest -q` for every completed major slice and before phase closure.
Follow `AGENTS.md` even if a prompt accidentally omits a gate.

### F. Report and stop

Require exact files, behavior, proof results, gate counts, Git state, preserved
hashes, limitations, and remaining work. Hermes must stop after the bounded
slice.

## 11. Codex review checklist for every Hermes report

Before approving:

- Read the report completely.
- Read every changed production file directly.
- Inspect `git status`, staged diff, unstaged diff, and HEAD/origin divergence.
- Compare actual file scope with the allowed scope.
- Run at least the most relevant focused tests independently.
- Run ruff/mypy/schema checks when the report claims they are green.
- Look for vacuous acceptance (`all`/loops over empty tuples), first-element
  dispatch, default fallbacks, mixed-runtime gaps, and verification helpers
  bypassed by mocks.
- Confirm tests do not patch away the gate they claim to prove.
- Confirm pure builders reject self-consistently rehashed foreign-but-valid
  inputs.
- Confirm query services do not create/repair/extract/replay/write.
- Confirm public errors do not leak values/hashes/reasons.
- Confirm docs/handoffs describe post-action truth, not a stale pre-action
  snapshot.
- Approve only when the repository and evidence agree.

## 12. Phase closure protocol for Phases 26 and 27

Each phase should end with:

1. Causal end-to-end acceptance fixture using real services.
2. Dedicated architectural boundary suite.
3. API/OpenAPI compatibility proof if the API changes.
4. Documentation updates that supersede stale historical statements.
5. Truthful phase handoff with exact local Git/publication state.
6. Full gates.
7. Codex independent audit.
8. User-authorized local commit only after everything is green.

After Phase 27:

1. Verify the complete local commit chain from `origin/main` through Phases
   25–27.
2. Run full final gates again.
3. Confirm clean tree/index and exact divergence.
4. Ask for explicit user authorization to push.
5. Use a normal non-force push to GitHub.
6. Verify `origin/main == HEAD` after push.

## 13. First message the next Codex chat should give the user

After reading and verifying this handoff, respond in Greek, briefly:

> Έχω διαβάσει το orchestrator handoff, ολόκληρο το επίσημο blueprint των
> Phases 23–27 και το Phase 25 handoff. Επιβεβαίωσα ότι το Phase 25 είναι
> ολοκληρωμένο στο local commit `e6a39e7` και δεν έχει γίνει push. Το Phase 26
> είναι empirical outcome distributions χωρίς ranking/recommendation και το
> Phase 27 είναι paired robust comparison + auditable campaign decision brief.
> Ξεκινώ με direct read-only audit του σημερινού repository για να ετοιμάσω το
> πρώτο bounded prompt προς τον Hermes· δεν έχει αρχίσει ακόμη implementation.

Do not begin implementation in that first response.

---

## Final checkpoint

- Phase 25: complete, locally committed, not pushed.
- Phase 26: authoritative blueprint incorporated; implementation not started.
- Phase 27: authoritative blueprint incorporated; begins only after Phase 26
  is green and locally committed with user authorization.
- Push: deferred until both Phase 26 and Phase 27 are complete.
- Codex: orchestrator/reviewer.
- Hermes: external implementer receiving bounded copy-paste prompts.
- Hermes sessions: maximum two substantive prompts, then rotate.
