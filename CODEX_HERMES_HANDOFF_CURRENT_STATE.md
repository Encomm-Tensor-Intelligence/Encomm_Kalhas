# Codex–Hermes Handoff — Current KALHAS State

Created for the next Codex chat after the official publication of the
completed KALHAS work through Phase 27. Rewritten in place on 2026-08-25 by
session `H27.1-S05` for the Gate 27.1 closure candidate, corrected on
2026-08-25 by `H27.1-S05-C01-POST-FULL-GATE-TRUTH` (§8.3 of that revision
records the green Codex-owned full gate), and **rewritten again in place on
2026-09-02 by session `H28-S13-DOCS-PERF-CLOSURE`** so this document now
truthfully describes the local Phase 28 closure-candidate state. The
2026-08-25 Gate 27.1 content is preserved as a dated historical snapshot at
`C:/Users/xampos/AppData/Local/hermes/profiles/kalhas-project/cache/h28-s13/CODEX_HERMES_HANDOFF_CURRENT_STATE.pre-h28s13.md`
(SHA-256 `2ae6ab022a131c0e06fae19effee5ab9ea2e093873c95e0072f687040a64d926`)
and as dated historical records inside `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md`;
Gate 27.1 itself was published as commit `777a4472ef0d1edc6d30ce61a05851302b981027`
and its `CHECKPOINT_ACCEPTED` disposition belongs to the Codex audit record.

This document is a current-state and working-method handoff only. It does not
authorize implementation, staging, committing, pushing, provider access, or any
live action. It does **not** declare the Phase 28 checkpoint (`CP28-B`)
accepted: every implementation and repository gate run locally is green (§8),
but checkpoint authority belongs exclusively to the independent Codex final
fingerprint/gate audit. After that audit verifies this handoff and the live
**Superseded 2026-09-02, later the same day:** the independent Codex final
Phase 28 audit has since verified the closure-candidate tree and recorded
`CP28-B` as `CHECKPOINT_ACCEPTED`. Phase 28 is complete. The user has
explicitly authorized the publication session to stage, commit, and push the
audited Phase 28 inventory; see "Publication status overlay — 2026-09-02"
below and §13. Phase 29 remains not started and not authorized.

**Durable workflow rule** (unchanged; supersedes every older session/correction
wording in this file and in historical handoffs):

```text
one fresh Hermes session = one prompt = one bounded slice/report
```

Any correction or continuation uses a new session ID and a fresh Hermes
session. Section 22 of `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` is the
governing continuation protocol.

## 1. Required read order in the next chat

The next Codex chat must:

1. Read `AGENTS.md` completely and treat it as the durable repository policy.
2. Read `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` — at minimum the 2026-09-01
   Phase 28 overlay and the 2026-09-02 H28-S13 closure overlay at the top,
   §10 (Phase 28 scope, closure addendum, exit criteria), §22 (continuation
   protocol), and §25 (bootstrap).
3. Read this file completely for the split between the published baseline and
   the local Phase 28 closure candidate.
4. Inspect the repository directly rather than relying only on handoff prose:
   - `git status -sb`
   - `git branch --show-current`
   - `git rev-parse HEAD`
   - `git rev-parse origin/main`
   - `git rev-list --left-right --count origin/main...HEAD`
   - `git diff --cached --name-only`
   - `git log --oneline --decorate -10`
5. Confirm its understanding to the user and wait. It must not begin new work
   merely because this handoff exists.

`KALHAS_HANDOFF_PHASE_27.md` remains a historical pre-publication snapshot.
Read it only when exact Phase 27 implementation, hash, or gate evidence is
needed.

## 2. Exact repository state

Two layers must never be conflated: what is published, and what exists only
locally as the Phase 28 closure candidate.

### 2.1 Published baseline (identical to `origin/main`)

- Repository root: `C:/Users/xampos/Desktop/Encomm-Kalhas`
- Branch: `main`
- Local `HEAD`: `777a4472ef0d1edc6d30ce61a05851302b981027`
  (`Gate 27.1: truthful baseline closure`)
- `origin/main`: `777a4472ef0d1edc6d30ce61a05851302b981027`
- Divergence: `0 0`
- Index: empty (nothing staged)
- Configured origin: `https://github.com/Xamposs/Encomm_Kalhas.git`

**No Phase 28 change is published.** Everything in §2.2 is local, unstaged,
uncommitted, and absent from `origin/main`.

### 2.2 Actual local closure-candidate tree (dirty, unpublished)

At the H28-S13 session baseline (before its documentation edits) the working
tree held exactly **102 dirty paths = 34 modified tracked files + 68 untracked
files**. The H28-S13 documentation slice then modified three additional
tracked files — `README.md`, `docs/architecture/README.md`, and
`docs/architecture/contracts-and-lifecycle.md` (each clean at
`777a447` since Gate 27.1 published them) — and rewrote this handoff file and
the strategic handoff in place (both untracked, status unchanged). The final
expected state is therefore exactly **105 dirty paths = 37 modified + 68
untracked**.

> **Correction (publication session, 2026-09-02):** the paragraph above
> miscounted and misclassified two paths. The audited final state — verified
> live by the publication session against the H28-S13 resume and the 90-entry
> protected ledger — is exactly **106 dirty paths = 38 modified tracked files
> + 68 untracked files**: `CODEX_HERMES_HANDOFF_CURRENT_STATE.md` is a
> modified *tracked* file (published before Gate 27.1; the S13 rewrite made
> it dirty), and only `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` is
> untracked. The exact 106-path inventory is recorded in the external session
> resume `h28-s13-resume.md` under
> `C:/Users/xampos/AppData/Local/hermes/profiles/kalhas-project/skills/coding/kalhas-project/references/`.
> In summary:

- **Modified tracked paths (final: 38; the pre-publication paragraph above
  said 37)**: the three active documentation
  surfaces above (Phase 28 closure overlays added by `H28-S13`), the v1
  registry (`kalhas/contracts/v1/__init__.py`), the store
  (`kalhas/application/in_memory_store.py`), the API app/errors
  (`kalhas/api/app.py`, `kalhas/api/errors.py`), the strategic handoff, and
  24 test files that earlier Phase 28 sessions legitimately advanced
  (registry/cardinality appends and boundary updates).
  `docs/decisions/ADR-004-deterministic-adaptive-runtime-4.md` is **not** in
  this set: it is byte-pinned by tests (§11) and the `H28-S13` session left
  it byte-identical.
- **Untracked paths (68)**: 31 new `kalhas/application/` adaptive/runtime-4
  modules, 5 new `kalhas/contracts/v1/` Phase 28 contract modules, 5 new
  `schemas/v1/` Phase 28 schema artifacts, this handoff file, the strategic
  handoff, and 24 new Phase 28 test files (contracts, services, replay,
  store, API, comparison, registry compatibility, and the S12 acceptance
  suite).

Note: `CODEX_HERMES_HANDOFF_CURRENT_STATE.md` and
`KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` were untracked before this rewrite
and remain untracked; the rewrite changed their bytes only, not their Git
status. Nothing is staged, nothing is committed, and nothing is pushed.

## 3. Published Git lineage

The published `main` history currently ends with:

```text
777a447 Gate 27.1: truthful baseline closure
a905d2a Phase 27: evidence-based campaign decision support
886f398 Phase 26: empirical campaign outcome distributions
e6a39e7 Phase 25: complete realization-aware runtime 3.0.0 closure
f40e83d Phase 25: handoff documentation
58a7b71 Phase 25: deterministic realization-aware runtime 3.0.0 trajectory subsystem
043ee22 Phase 24: deterministic world uncertainty realizations
dfe8511 Phase 23: objective-to-metric evaluation semantics
215729d KALHAS: domain-neutral decision-world kernel through Phase 22
```

None of the Phase 28 paths in §2.2 appears in this published lineage.

## 4. What KALHAS is

KALHAS is the deterministic decision-world and evidence engine in a strict
three-role architecture:

- **NEXUS** owns natural-language dialogue, organizational context, memory,
  and presentation.
- **LEGION** owns strategy and agent exploration.
- **KALHAS** owns versioned world models, uncertainty, deterministic
  simulation campaigns, evidence, replay, comparison, and decision artifacts.

No fourth component or hidden integration surface is allowed. The kernel is
domain-neutral; runtime 4 is ordinary governed KALHAS machinery, not a new
component. KALHAS does not import NEXUS or LEGION internals; the only
permitted coupling is the placeholder adapter protocols under
`kalhas/adapters/`.

## 5. What has been implemented

Sections 5.1–5.7 describe the published Phase 0–27/Gate 27.1 baseline.
Section 5.8 describes the local Phase 28 closure layer on top of it.

### 5.1 Versioned deterministic foundation

Versioned public v1 contracts and synchronized JSON Schema artifacts;
canonical serialization, content hashes, immutable identifiers, provenance
binding; tenant isolation and explicit ownership checks; in-memory
persistence with snapshot isolation; deterministic replay; closed-world
catalog and domain-pack boundaries.

### 5.2 World uncertainty and realizations

Versioned world models with immutable content identity; explicit uncertainty
declarations; deterministic realizations bound to recorded scenario seeds;
realization-aware runtime `3.0.0` execution; exact input-integrity
verification before execution or derivation.

### 5.3 Campaign execution and trajectory evidence

Deterministic campaign planning over strategy × shared-seed matrices; fair
comparisons under identical recorded conditions; strategy trajectory
declarations and deterministic state transitions; realization trajectory
execution and replay verification; run-level and campaign-level metric
observations; trajectory/observation/statistics matrices; read-only verified
query services.

### 5.4 Objective and outcome evidence

Objective-to-metric evaluation semantics; exact target and optimization
direction handling; empirical campaign outcome distributions; deterministic
Type-7 quantiles and fixed 95% tail statistics; strict finite-number
validation; outcome matrices with identity and content hashes; read-only
verified retrieval.

### 5.5 Campaign decision support

Immutable per-campaign decision policy; target feasibility requirements;
paired same-seed comparisons; weighted regret and minimax robustness; Pareto
dominance; explicit preferred/inconclusive/insufficient-evidence/
no-feasible-strategy terminal states; deterministic briefs; independent
verification; read-only API operations; 100-seed acceptance proofs.

### 5.6 Colony UI

The repository includes a visually improved local Colony demonstration with
synthetic mock activity. It is intentionally separate from the verified
decision pipeline, is not evidence, not a calibrated prediction, not a
real-world recommendation, and performs no autonomous external actions.

### 5.7 Gate 27.1 closure proof (published at `777a447`)

The Gate 27.1 changes — active-documentation truth with boundary assertions,
the architecture-policy conflict resolution with the approval-gated skip
removed, and the unpatched exact-five trajectory-plan proof (five causally
different declared plans over four shared seeds, real decision policy,
comparison, and brief through the real services, with permanent closure
boundaries in `tests/test_phase27_1_boundaries.py`) — were audited, fully
gated (5,480 passed, 0 failed, 0 skipped, 901.64 seconds, Codex-owned run),
and published as commit `777a4472ef0d1edc6d30ce61a05851302b981027`. They are
now part of the published baseline, not a local candidate layer.

### 5.8 Phase 28 adaptive runtime 4.0.0 (local, unpublished; gated, not checkpoint-accepted)

On top of the published Gate 27.1 baseline, the local Phase 28 tree
(`H28-S01` through `H28-S13`, complete) adds additive runtime `4.0.0`:

- **Contracts and schemas** (D28-01–D28-04 frozen in ADR 004): five new
  top-level v1 contracts — `RuntimeObservationDeclaration`,
  `ExternalObservationInputBundle`, `AdaptivePolicy`,
  `AdaptiveRunTrajectoryExecution`, `AdaptiveRunTrajectoryReplayManifest` —
  registered at `PUBLIC_CONTRACTS` indexes 50–54 (55 total), with five new
  synchronized schema artifacts (55 total; 56 files in `schemas/v1/`). The
  50-contract prefix, all historical schema bytes, `API_VERSION`, and
  `SCHEMA_VERSION` are unchanged. Nested evidence roles (drafts, observation
  events, snapshots, decision/switch events) carry no independent authority.
- **Causal execution**: the frozen within-step schedule (resolve step-addressed
  external inputs → observe → validate/record → evaluate → decide → apply →
  record) with counter/key-addressed observation noise under the frozen
  `kalhas-observation-noise-v1` coordinate; a policy can act only on
  observations available at the exact decision point. Runtimes
  1.0.0/2.0.0/3.0.0 keep their exact historical meaning; nothing recorded is
  reinterpreted.
- **Immutable evidence**: one self-hashing `AdaptiveRunTrajectoryExecution`
  per adaptive run; replay independently recomputes state-derived
  observations, addressed noise, decisions, switches, and state evolution and
  fails closed on any mismatch, persisting only the
  `AdaptiveRunTrajectoryReplayManifest`. Read-only verified projections
  expose observations, decisions, and switches through three additive API
  paths (`/v1/runs/{run_id}/adaptive/{observations,decisions,switches}`);
  the static-versus-adaptive comparison is derived, never stored.
- **Unpatched production acceptance**
  (`tests/test_phase28_exact_five_adaptive_acceptance.py`, 24 focused tests):
  the real exact-five campaign (production `EXPECTED_STRATEGY_SET_SIZE == 5`,
  five causally different declared plans) plus one bound adaptive policy arm
  over the same four shared seeds/world coordinates — causal switching under
  dwell/cooldown/budgets, paired comparison evidence, exact replay, tenant
  isolation, and adversarial rejection of tampering. No cardinality patching,
  no production mutation, no manufactured evidence.

These are deterministic proofs about recorded models and recorded seeds. They
do not establish scientific validity, calibrated forecasting, real-world
causality, or any live-action capability (see §7).

## 6. Current public surface

The public-contract catalog contains **55** versioned contracts. The Phase 28
tail (indexes 50–54) is `RuntimeObservationDeclaration`,
`ExternalObservationInputBundle`, `AdaptivePolicy`,
`AdaptiveRunTrajectoryExecution`, `AdaptiveRunTrajectoryReplayManifest`. The
latest Phase 27 additive contracts (indexes 47–49) are `CampaignDecisionPolicy`,
`CampaignStrategyComparison`, `CampaignDecisionBrief`.

The API remains under the existing v1 segment: 46 documented paths / 57
operations, including the three Phase 28 read-only adaptive paths. Gate 27.1
added no public surface; Phase 28 added exactly the three adaptive paths, five
contracts, and five schema artifacts listed above. The decision policy is
persisted; comparisons and briefs remain derived read-only.

## 7. Truthfulness and safety boundaries

The next chat must preserve these statements:

- KALHAS currently produces deterministic evidence under declared models and
  recorded assumptions.
- Deterministic replay and repository acceptance are not scientific validity,
  not calibration, not production readiness, not certification, and not a
  guarantee of any outcome.
- It does not prove that the model is an accurate representation of reality.
- It does not claim calibrated forecasting or certainty.
- It does not establish real-world causality merely because replay is
  deterministic.
- It performs no autonomous live action.
- The running application performs no network/provider action.
- No real company or personal data belongs in code, fixtures, docs, or tests.
- The Colony experience is synthetic unless explicitly connected to verified
  recorded KALHAS artifacts by later authorized work.
- Public v1 contracts are backward-compatible. Breaking changes require a new
  contract module and API version rather than mutation in place.
- The exact-five and exact-five-plus-adaptive campaigns are deterministic
  closure proofs over a synthetic, domain-neutral fixture world. They are not
  evidence that the model represents reality, that four seeds suffice for any
  real decision, or that any preferred strategy is a real-world
  recommendation.

## 8. Quality evidence

### 8.1 Historical Phase 27 and Gate 27.1 evidence (explicitly historical)

The 2026-08-25 historical snapshot (preserved in the external pre-rewrite
copy named at the top of this file and in §9 of the strategic handoff)
records: Phase 27 publication evidence (5,411 collected / 5,410 passed / one
then-approved skip, 724.4 s); the Gate 27.1 focused gates; and the Codex-owned
Gate 27.1 full gate on the grouped `S01`–`S05` fingerprint — **5,480 passed,
0 failed, 0 skipped, 4 warnings, 901.64 seconds**, Ruff/format/mypy/schema/diff
all green, nothing staged, no publication. These values describe those
historical trees only and must not be quoted as the current suite state.

### 8.2 Phase 28 session evidence (local, audited progressively through S12)

Per-slice evidence through `H28-S12` was audited progressively by Codex; the
pinned, independently re-verifiable H28-S12 facts are:

- Acceptance suite:
  `tests/test_phase28_exact_five_adaptive_acceptance.py` — git blob
  `5d962408330fe0e6a80e972e47beb2af7d65b2bb`, 50,604 bytes, 1,090 lines, 24
  focused tests, zero forbidden markers (no skip/xfail/noqa/type-ignore).
- Full suite (H28-S12 session, exactly one run, normal exit):
  **6,850 tests, 0 failures, 0 errors, 0 skipped, 810.94 seconds**; JUnit
  artifact at `C:/Users/xampos/AppData/Local/Temp/h28s12_full.xml`
  (1,039,417 bytes, well-formed, no failure/error elements).
- Supporting gates from the S12 session: focused 24 passed; Gate 27.1 pair 92
  passed 0F/0E/0S; related Phase 28/adaptive suites 1,201 passed; ruff check
  and format-check green; mypy green (340 source files); schema export
  `--check` synchronized; `git diff --check` clean; staged 0.
- Protected S11 pins byte-exact: `tests/test_api_phase28.py`
  `67b38646afac4276be92d40c068b972009628669` (44,408 B / 1,046 L),
  `kalhas/api/routes_adaptive_run_execution.py`
  `498bef4a4ab1e034858c25215d9e8c0f0e8eed6a` (5,656 B / 136 L),
  `kalhas/api/app.py` `f6e2ff0e40fb8c89483beb15280a595950497342`
  (2,329 B / 53 L), `kalhas/api/errors.py`
  `d97918755878a84e5bf13c9662c34d446a97806a` (14,896 B / 347 L).
- H28-S13 (this session) added: the six documentation-surface updates (this
  file, both active READMEs, contracts-and-lifecycle, the strategic handoff;
  ADR-004 untouched and byte-identical — see §11) and a bounded,
  fixture-specific performance characterization recorded entirely outside the
  repository (raw JSON + script under
  `C:/Users/xampos/AppData/Local/Temp/h28s13/`, hashes in the external
  resume). Its gates are listed with this session's final report; the
  authoritative full-suite run for the grouped final fingerprint belongs to
  the independent Codex audit.

### 8.3 Gate commands any change must pass

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy kalhas tests
uv run python scripts/export_schemas.py --check
```

## 9. User, Codex, and Hermes roles

### 9.1 User

The user owns product direction and authorization: what is worked on, when a
design is accepted, when implementation begins, when a phase is officially
closed, and whether Git changes may be committed or pushed. No agent may
infer permission for a new scope from previous momentum.

### 9.2 Codex

Codex is the orchestrator, reviewer, and repository auditor. Codex must
inspect the live folder directly, divide work into narrow independently
verifiable slices, give Hermes exact allowlists, review every report against
the actual working tree, detect incomplete runs/false claims/stale
wording/hidden Git changes, issue corrections as fresh sessions, run
proportionate gates before closure, and perform Git stage/commit/push only
after explicit user authorization. Hermes reports are evidence to inspect,
not authority.

### 9.3 Hermes

Hermes is the bounded implementation agent. Hermes must begin with exact
repository preflight, work only in explicitly permitted files, preserve all
unrelated worktree state, implement one bounded slice or correction, add
adversarial tests for behavioral changes, run the requested focused gates,
report exact observed counts/errors/Git state/changed files, stop at the
requested boundary, and never stage, commit, push, amend, rebase, reset,
stash, clean, or create a branch unless a later prompt explicitly authorizes
that exact operation.

## 10. Codex–Hermes session discipline

The durable rule is:
`one fresh Hermes session = one prompt = one bounded slice/report`.

- Every slice, correction, or continuation opens a **new** session with a new
  session ID, receives exactly one prompt, and produces exactly one final
  report. No follow-up prompts are sent into a finished session.
- Each prompt carries its own preflight fingerprint, allowlist, gates, and
  stop conditions (canonical template: §22.12 of the strategic handoff).
- Do not request redundant full-suite executions when an authoritative run
  already covers the same final file state; evidence reuse requires the
  identical content/gate fingerprint.
- For long tests, run one process and wait for it. Never launch duplicate
  suites merely because output is temporarily quiet.
- If a session hits a tool/context/credit limit, returns `PARTIAL`/`BLOCKED`,
  or needs any correction, that session is finished: Codex inspects the live
  folder and issues the smallest remaining scope as one new prompt to a fresh
  session.
- Only one writer session may be active for a repository/worktree.

## 11. Scope note: ADR-004 is byte-pinned, not annotated in place

The H28-S13 prompt asked for a non-normative implementation-status note in
`docs/decisions/ADR-004-deterministic-adaptive-runtime-4.md`. That file is
byte-pinned by four independent test functions
(`tests/test_adaptive_condition_evaluator.py`,
`tests/test_adaptive_policy_contracts.py`,
`tests/test_adaptive_policy_state_machine.py`, and the 90-entry baseline
ledger check in `tests/test_adaptive_campaign_planning_service.py`, ledger
line 1 — all pin git blob
`32518c01baa8443da73650b106cbd674b86b7ae8`). Editing it would break those
tests, and editing tests was outside this session's allowlist. The non-
normative implementation-status note therefore lives in the three active
documentation surfaces and in this handoff and the strategic handoff instead;
ADR-004 remains byte-identical (`32518c01...`, 12,997 bytes, 269 lines). Its
at-time-of-writing sentence "No Phase 28 implementation exists at the time of
writing" remains true as of its 2026-08-25 writing date and is now
historically superseded by the dated 2026-09-02 overlays elsewhere — exactly
the preserve-as-historical pattern this repository already applies to ADRs
and handoffs.

## 12. Git publication discipline

- Normal development remains unstaged until a bounded slice has been audited.
- Hermes does not publish changes.
- Codex stages only the confirmed phase/scope path set and inspects the staged
  name-status, path count, diff, and whitespace policy before committing.
- Commit messages follow the existing concise `Phase N: description` style
  when a numbered phase is being officially closed.
- No force push, amend, squash, rebase, reset, or history rewrite without an
  explicit user request; a normal push requires separate explicit user
  authorization.
- After a push, Codex verifies `HEAD == origin/main`, divergence `0 0`, a
  clean tree/index, and the remote commit through GitHub.

## 13. Next eligible action

The action after the `H28-S13-DOCS-PERF-CLOSURE` report is exactly:

1. **Codex performs the independent final Phase 28 fingerprint/gate audit**:
   verify the exact dirty inventory against the session allowlists, the
   documented hashes/counts, the pinned S11/S12 fingerprints, the ledger
   (90/90), the schema counts (55/56), and the gate evidence; then run the
   complete repository gate once on the grouped final Phase 28 fingerprint.
2. Only if that audit is green, Codex records `CP28-B`
   `CHECKPOINT_ACCEPTED`. This session does not assign that disposition.
3. Git staging, commit, and push require separate explicit user
   authorization.
4. **Then STOP awaiting explicit Phase 29 instructions.** Phase 29 is not
   started, not designed for implementation, and not authorized. Before any
   `H29-S01`, the required read-only Phase 29 entry audit (mechanism ADR,
   D29-03 Model Pack release/assurance profile, maturity/claim rules,
   numerical/platform rule, adapter impact, external-reference boundary)
   must occur, and every future portfolio entry remains `catalogued`.

That is the complete handoff. No additional work is authorized by this file.

## 14. Publication status overlay — 2026-09-02

Recorded by the user-authorized publication session after the independent
Codex final Phase 28 fingerprint/gate audit accepted the closure candidate
(`CP28-B`: `CHECKPOINT_ACCEPTED`, 2026-09-02). The publication session
verified live: branch `main`; `HEAD == origin/main ==
777a4472ef0d1edc6d30ce61a05851302b981027`; divergence `0 0`; staged 0; dirty
exactly 106 = 38 modified + 68 untracked, byte-exact against the H28-S13
resume inventory; protected ledger SHA-256 `a7937bf7...ee152` with 90/90
entries re-verified; schemas 55/56; no repository-writer processes; no
credentials, caches, temporary files, or unrelated binaries across all 106
paths.

Current truthful status:

- `H28-S01` through `H28-S13` are **complete**; Phase 28 (adaptive
  deterministic runtime `4.0.0`) is **complete**: implementation-finished,
  fully gated, and independently audited.
- `CP28-B` was independently accepted by Codex on **2026-09-02**.
- This publication session stages and commits exactly the audited Phase 28
  inventory (38 modified + 68 untracked paths) plus minimal final status
  corrections to the active handoff documentation, after re-running the
  focused Phase 28, Ruff, format, mypy, and schema-synchronization gates. It
  then polishes the repository presentation (banner, README, community and
  CI files) as a separate documentation commit — both under the user's
  explicit authorization.
- **Phase 29 is NOT STARTED and NOT AUTHORIZED.** It requires new explicit
  user authorization and the read-only Phase 29 entry audit described in
  §13 before any implementation session.
