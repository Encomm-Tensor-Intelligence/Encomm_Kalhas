# Codex–Hermes Handoff — Current KALHAS State

Originally created for the next Codex chat after the official publication of
the completed KALHAS work through Phase 27. Rewritten in place on 2026-08-25
by session `H27.1-S05` so this document truthfully described the local
Gate 27.1 closure candidate left by the four audited implementation sessions
(`S01`–`S04`), without claiming any acceptance that had not happened.
Corrected in place on 2026-08-25 by the mechanical post-full-gate session
`H27.1-S05-C01-POST-FULL-GATE-TRUTH` after Codex independently audited
`H27.1-S05` and ran the single authoritative full repository gate on the
grouped final `S01`–`S05` fingerprint on 2026-08-25 — completely green; the
gate evidence is recorded in §8.3.

This document is a current-state and working-method handoff only. It does not
authorize, design, schedule, or imply additional implementation. It does not
declare the Gate 27.1 checkpoint (`CP27.1`) accepted: the implementation and
full repository gates are green, but this mechanical documentation correction
does not independently assign checkpoint authority, and the latest Codex
live-folder audit is authoritative for the final `CP27.1` disposition. After
Codex verifies this correction on the final documentation fingerprint, it may
record `CP27.1` as `CHECKPOINT_ACCEPTED` without another handoff edit.

**Durable workflow rule** (supersedes every older session/correction wording
in this file and in historical handoffs):

```text
one fresh Hermes session = one prompt = one bounded slice/report
```

Any correction or continuation uses a new session ID and a fresh Hermes
session. Section 22 of `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` is the
governing continuation protocol; wherever its instructions differ from older
wording, Section 22 supersedes.

## 1. Required read order in the next chat

The next Codex chat must:

1. Read `AGENTS.md` completely and treat it as the durable repository policy.
2. Read `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` — at minimum §9 (Gate 27.1
   deliverables and exit criteria), §22 (Codex–Hermes continuation protocol,
   including the §22.15 Gate 27.1 session map), and §25 (bootstrap and the
   current first eligible sequence).
3. Read this file completely for the split between the published baseline and
   the local Gate 27.1 closure candidate.
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

`KALHAS_HANDOFF_PHASE_27.md` is a historical pre-publication snapshot. Read it
only when exact Phase 27 implementation, hash, or gate evidence is needed.

## 2. Exact repository state

Two layers must never be conflated: what is published, and what exists only
locally as the Gate 27.1 closure candidate.

### 2.1 Published baseline (identical to `origin/main`)

- Repository root:
  `C:/Users/xampos/Desktop/Encomm-Kalhas`
- Branch: `main`
- Local `HEAD`:
  `a905d2af6b155a0f2568037e2b0f410b20be8d91`
- `origin/main`:
  `a905d2af6b155a0f2568037e2b0f410b20be8d91`
- Divergence: `0 0`
- Index: empty (nothing staged)
- Configured origin:
  `https://github.com/Xamposs/Encomm_Kalhas.git`
- GitHub visibility: public; default branch: `main`

Published `main` ends at the Phase 27 commit. **No Gate 27.1 change is
published.** Everything listed in §2.2 is local, unstaged, uncommitted, and
absent from `origin/main`.

### 2.2 Actual local closure-candidate tree (dirty, unpublished)

After the Gate 27.1 implementation sessions, the working tree deliberately
holds exactly eleven dirty paths — six modified tracked files and five
untracked files. The working tree is **not clean**, and it is not "one
untracked handoff file":

Modified tracked paths (with the audited slice that changed them):

| Path | Changed by |
| --- | --- |
| `AGENTS.md` | S02 (architecture-role clarification: ordinary internal KALHAS modules are not additional components) |
| `README.md` | S01 (post-publication Phase 26/27 status wording) |
| `docs/architecture/README.md` | S01 (post-publication Phase 27 status) |
| `docs/architecture/contracts-and-lifecycle.md` | S01 (post-publication Phase 27 status) |
| `tests/test_boundaries.py` | S02 (approval-gated skip removed; deterministic, policy-consistent assertion) |
| `tests/test_phase27_boundaries.py` | S01 (boundaries assert the post-publication wording) |

Untracked paths:

| Path | Role |
| --- | --- |
| `CODEX_HERMES_HANDOFF_CURRENT_STATE.md` | S05 (this file) |
| `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md` | S05 execution-status updates only (Phase 28–35 roadmap otherwise unchanged) |
| `tests/phase27_1_helpers.py` | S03 (unpatched exact-five causal fixture) |
| `tests/test_phase27_1_exact_five_acceptance.py` | S03 (real exact-five acceptance proof) |
| `tests/test_phase27_1_boundaries.py` | S04/C01 (permanent closure boundaries plus the derived-evidence injection detector) |

All eleven paths are preserved exactly as their audited sessions produced
them, except the two handoff files, which the `H27.1-S05` documentation slice
and its mechanical post-full-gate correction `H27.1-S05-C01-POST-FULL-GATE-
TRUTH` edited within their own allowlists. Nothing is staged, nothing is
committed, and nothing is pushed.

## 3. Published Git lineage

The published `main` history currently ends with:

```text
a905d2a Phase 27: evidence-based campaign decision support
886f398 Phase 26: empirical campaign outcome distributions
e6a39e7 Phase 25: complete realization-aware runtime 3.0.0 closure
f40e83d Phase 25: handoff documentation
58a7b71 Phase 25: deterministic realization-aware runtime 3.0.0 trajectory subsystem
043ee22 Phase 24: deterministic world uncertainty realizations
dfe8511 Phase 23: objective-to-metric evaluation semantics
215729d KALHAS: domain-neutral decision-world kernel through Phase 22
f153f3c KALHAS: domain-neutral decision-world kernel through Phase 19
```

The Phase 26 and Phase 27 handoffs are present in the public repository:

- `KALHAS_HANDOFF_PHASE_26.md`
- `KALHAS_HANDOFF_PHASE_27.md`

None of the Gate 27.1 paths in §2.2 appears in this published lineage.

## 4. What KALHAS is

KALHAS is the deterministic decision-world and evidence engine in a strict
three-role architecture:

- **NEXUS** owns natural-language dialogue, organizational context, memory,
  and presentation.
- **LEGION** owns strategy and agent exploration.
- **KALHAS** owns versioned world models, uncertainty, deterministic
  simulation campaigns, evidence, replay, comparison, and decision artifacts.

No fourth component or hidden integration surface is allowed.

The KALHAS kernel is domain-neutral. Domain-specific behavior may enter only
through domain packs implementing the accepted `DomainPack` protocol. KALHAS
does not import NEXUS or LEGION internals; the only permitted coupling is the
placeholder adapter protocols under `kalhas/adapters/`.

## 5. What has been implemented

Sections 5.1–5.6 describe the published Phase 0–27 baseline. Section 5.7
describes the local Gate 27.1 closure layer on top of it.

### 5.1 Versioned deterministic foundation

- Versioned public v1 contracts and synchronized JSON Schema artifacts.
- Canonical serialization, content hashes, immutable identifiers, and
  provenance binding.
- Tenant isolation and explicit ownership checks.
- In-memory persistence seams with snapshot isolation.
- Deterministic replay from recorded inputs and seeds.
- Closed-world catalog and domain-pack boundaries.

### 5.2 World uncertainty and realizations

- Versioned world models and immutable world content identity.
- Explicit uncertainty declarations.
- Deterministic world realizations bound to recorded scenario seeds.
- Realization-aware runtime `3.0.0` execution paths.
- Exact input-integrity verification before execution or derivation.

### 5.3 Campaign execution and trajectory evidence

- Deterministic campaign planning over strategy × shared-seed matrices.
- Fair comparisons under identical recorded conditions.
- Strategy trajectory declarations and deterministic state transitions.
- Realization trajectory execution and replay verification.
- Run-level and campaign-level metric-observation extraction.
- Campaign trajectory, observation, and statistics matrices.
- Read-only verified query services that reconstruct and validate authority
  rather than trusting stored derived payloads.

### 5.4 Objective and outcome evidence

- Objective-to-metric evaluation semantics.
- Exact target and optimization-direction handling.
- Empirical campaign outcome distributions.
- Deterministic Type-7 quantiles and fixed 95% tail statistics.
- Strict finite-number and large-integer conversion validation.
- Strategy/objective outcome matrices with identity and content hashes.
- Read-only verified retrieval of outcome evidence.

### 5.5 Campaign decision support

- Immutable per-campaign decision policy.
- Global or per-objective target-feasibility requirements.
- Paired strategy comparisons over identical ordered seed evidence.
- Exact win/loss/tie counts and paired-delta orientation.
- Weighted regret and downside evidence.
- Feasibility assessment and Pareto dominance over feasible strategies.
- Deterministic minimax-regret selection with declared tie tolerance.
- Explicit preferred, inconclusive, insufficient-evidence, and
  no-feasible-strategy terminal states.
- Deterministic structured campaign decision briefs.
- Independent verification against authoritative policy and outcome records.
- Read-only API operations for policy, strategy comparison, and decision brief.
- Fixed 100-seed acceptance proofs and adversarial tamper coverage.

### 5.6 Colony UI

The repository includes a visually improved local Colony demonstration with
synthetic mock activity. It is intentionally separate from the verified
decision pipeline.

The Colony display is not evidence that live agents are acting, is not a
calibrated prediction, is not a real-world recommendation, and does not
perform autonomous external actions.

### 5.7 Gate 27.1 closure proof (local, unpublished; audited, not checkpoint-accepted)

On top of the published Phase 27 baseline, the local Gate 27.1 changes add a
truthful-baseline closure layer whose proofs live entirely in the §2.2
documentation and test/helper paths:

- Active documentation (`README.md`, the architecture docs, `AGENTS.md`)
  states the true post-publication Git state, and the boundary tests assert
  that wording, so stale pre-publication claims cannot silently return.
- The architecture-policy conflict is resolved: ordinary internal KALHAS
  modules are explicitly not additional components or integration surfaces,
  and the former approval-gated skip in `tests/test_boundaries.py` is gone —
  the boundary suites now run deterministically with zero skips.
- An end-to-end runtime-3.0.0 campaign proves the real public path under the
  unmodified production `EXPECTED_STRATEGY_SET_SIZE == 5` invariant: the real
  `MockLegionAdapter` supplies exactly five default/reference strategies,
  made causally different by five declared transition-reference orders —
  five executable plans, not five labels.
- Exactly four immutable shared seeds drive twenty real executions
  (5 strategies × 4 seeds); realization identity and content hashes are
  identical across strategies per shared seed (shared-seed fairness),
  executions are replay-verifiable, and the five trajectory/outcome
  signatures are pairwise distinct as a causal consequence of the distinct
  declared plans applied to the shared realized worlds.
- Decision policy, strategy comparison, and the decision brief are derived
  through the real, unmodified production services and read-only verified
  queries against authoritative upstream records — no injected
  comparison/brief, no copied decision algorithm, no second persisted
  authority.
- Replay, fairness, lineage, read-only reconstruction, tenant isolation, and
  failure atomicity are exercised together in the acceptance proof.
- `tests/test_phase27_1_boundaries.py` permanently encodes the closure
  boundaries: candidate-cardinality patching, mock replacement or subclassing,
  manufactured evidence, skip/xfail reintroduction, production imports of the
  test-only Gate 27.1 helpers, and direct derived-evidence
  persistence/injection are all structurally forbidden. A reusable detector
  (`_direct_derived_persistence_violations`) is itself proven against
  constructed violations while accepting legal read/service paths.

These are deterministic proofs about recorded models and recorded seeds. They
do not establish scientific validity, calibrated forecasting, real-world
causality, or any live-action capability (see §7).

## 6. Current public surface

The current public-contract catalog contains 50 versioned contracts. The
latest additive contracts are:

- `CampaignDecisionPolicy`
- `CampaignStrategyComparison`
- `CampaignDecisionBrief`

The API remains under the existing v1 segment. The decision surface adds
exactly four operations across three paths:

- create a campaign decision policy;
- retrieve the recorded decision policy;
- retrieve the verified strategy comparison;
- retrieve the deterministic decision brief.

The policy is persisted. Strategy comparison and decision brief are derived
read-only from verified recorded evidence and are not independently persisted.

Gate 27.1 added no public surface: no new contracts, schema artifacts, API
paths, or operations. The Phase 27 boundary suite pins the catalog at exactly
50 contracts with unchanged indexes and the three decision-tail entries, and
pins the API at exactly the four decision operations.

## 7. Truthfulness and safety boundaries

The next chat must preserve these statements:

- KALHAS currently produces deterministic evidence under declared models and
  recorded assumptions.
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
- The Gate 27.1 exact-five campaign is a deterministic closure proof over a
  synthetic, domain-neutral fixture world. It is not evidence that the model
  represents reality, that four seeds suffice for any real decision, or that
  any preferred strategy is a real-world recommendation.

## 8. Quality evidence

### 8.1 Historical Phase 27 publication evidence (explicitly historical)

The following values describe the published `a905d2a` tree at the official
Phase 27 closure. They are retained only as historical publication evidence.
They are **not** the Gate 27.1 result and must not be quoted as the current
suite state:

- Pytest collected exactly **5,411 tests**; **5,410 passed**.
- **1 test skipped** through the then-documented `AGENTS.md` approval gate;
  0 failed and 0 errored.
- `tests/test_phase27_boundaries.py`: **54 passed**.
- Phase 26 + Phase 27 acceptance gate: **70 passed**.
- `ruff check .`, `ruff format --check .`, `mypy kalhas tests`, schema-export
  synchronization, and Git diff hygiene: all passed.
- The independent Codex full-suite run took 724.4 seconds.

Note: the one skipped architecture test above no longer exists. S02 removed
the approval-gated skip; the current boundary suites run with zero skips.

### 8.2 Audited Gate 27.1 focused evidence (per slice, as independently audited by Codex)

| Slice | Audit status | Focused evidence |
| --- | --- | --- |
| `H27.1-S01` | `SESSION_AUDITED` | Active post-publication documentation truth and its exact boundary assertions in `tests/test_phase27_boundaries.py`. |
| `H27.1-S02` | `SESSION_AUDITED` | `tests/test_boundaries.py`: 17 passed, 0 skipped. Combined boundary gate at S02 audit time: 72 passed, 0 skipped. |
| `H27.1-S03` | `SESSION_AUDITED` | Real unpatched exact-five campaign proof: focused 35 passed; Phase 26 + Phase 27 + S03: 105 passed. No production/cardinality mutation and no manufactured evidence. |
| `H27.1-S04-C01-DERIVED-INJECTION-DETECTOR` (correction of the original `H27.1-S04-CLOSURE-BOUNDARY`) | `SESSION_AUDITED` | Final focused boundary gate: 33 passed. Combined boundaries: 105 passed. S03 acceptance + S04 boundaries: 68 passed. Ruff, format-check, and mypy green. The corrected reusable detector catches constructed derived-evidence persistence/injection and accepts legal read/service paths. |

Slice IDs, allowlists, diffs, and file hashes were verified by Codex against
the live tree at each audit.

### 8.3 Completed: the single final repository gate (Codex-owned, 2026-08-25)

After independently auditing the `H27.1-S05` documentation slice, Codex ran
the one authoritative full repository gate on the grouped final `S01`–`S05`
fingerprint on 2026-08-25. The complete observed result:

- Pytest: exit 0 — **5,480 passed**, **0 failed**, **0 skipped**,
  4 warnings (one pre-existing Starlette deprecation warning plus expected
  Pydantic serialization warnings exercised by adversarial tests), 901.64
  seconds. No full-suite count was rounded or changed.
- Ruff check: exit 0 — all checks passed.
- Ruff format check: exit 0 — 295 files already formatted.
- mypy: exit 0 — no issues found in 278 source files.
- Schema export synchronization (`scripts/export_schemas.py --check`): exit 0
  — all schema artifacts synchronized.
- Git diff hygiene (`git diff --check`): exit 0.
- Staged paths (`git diff --cached --name-only`): empty; nothing staged.
- No Git publication occurred; every Gate 27.1 change remains local.

The full gate itself was completely green. This document records that
evidence mechanically; it does not itself assign checkpoint authority for
`CP27.1`. The latest Codex live-folder audit is authoritative for the final
`CP27.1` disposition: after Codex verifies this documentation correction on
the final documentation fingerprint, it may record `CP27.1`
`CHECKPOINT_ACCEPTED` without another handoff edit.

Any behavioral change must continue to pass at minimum:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy kalhas tests
uv run python scripts/export_schemas.py --check
```

## 9. User, Codex, and Hermes roles

### 9.1 User

The user owns product direction and authorization. The user decides:

- what is worked on;
- when a design is accepted;
- when implementation begins;
- when a phase is officially closed;
- whether Git changes may be committed or pushed.

No agent may infer permission for a new scope from previous momentum.

### 9.2 Codex

Codex is the orchestrator, reviewer, and repository auditor.

Codex must:

- inspect the live folder directly;
- understand the architectural boundary before writing a prompt;
- divide implementation into narrow, independently verifiable slices;
- give Hermes exact allowlisted files and explicit forbidden scope;
- review every Hermes report against the actual working tree;
- detect incomplete runs, false claims, stale wording, and hidden Git changes;
- issue narrowly bounded corrections as fresh sessions, never as follow-ups;
- independently run proportionate gates before closure;
- perform Git stage/commit/push only after explicit user authorization.

Hermes reports are evidence to inspect, not authority by themselves.

### 9.3 Hermes

Hermes is the bounded implementation agent.

Hermes must:

- begin with exact repository preflight;
- work only in the files explicitly permitted by the Codex prompt;
- preserve all unrelated worktree state;
- implement one bounded slice or correction;
- add adversarial tests for behavioral changes;
- run the requested focused gates;
- report exact observed counts, errors, Git state, and changed files;
- stop at the requested boundary;
- never stage, commit, push, amend, rebase, reset, stash, clean, or create a
  branch unless a later prompt explicitly authorizes that exact operation.

## 10. Codex–Hermes session discipline

The durable rule is:

```text
one fresh Hermes session = one prompt = one bounded slice/report
```

- Every slice, correction, or continuation opens a **new** session with a new
  session ID, receives exactly one prompt, and produces exactly one final
  report. No follow-up prompts are sent into a finished session. This replaces
  the older allowance for a same-session correction/closure prompt, which is
  obsolete everywhere.
- Each prompt carries its own preflight fingerprint, allowlist, gates, and
  stop conditions. The canonical template is §22.12 of
  `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md`.
- Do not make Hermes rediscover the whole architecture on every prompt;
  provide exact required reads and anchors.
- Do not ask for redundant full-suite executions when an authoritative run
  already covers the same final file state; evidence reuse requires the
  identical content/gate fingerprint.
- For long tests, run one process and wait for it. Never launch duplicate
  suites merely because output is temporarily quiet.
- If a session hits a tool/context/credit limit, returns `PARTIAL`/`BLOCKED`,
  or needs any correction, that session is finished: Codex inspects the live
  folder and issues the smallest remaining scope as one new prompt to a fresh
  session.
- Only one writer session may be active for a repository/worktree. Do not edit
  the same worktree concurrently from Codex, another agent, an IDE formatter,
  or a second Hermes session.

## 11. Required Hermes prompt structure

The canonical prompt template is §22.12 of
`KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md`, which supersedes the older sketch
below wherever the two differ. The stable skeleton remains:

### A. Baseline

- repository root;
- expected branch, HEAD, origin, and divergence;
- expected index/worktree state;
- mandatory files to read;
- instruction to clear unexpected `PYTHONPATH` state.

### B. Exact scope

- explicit permitted files;
- explicit forbidden files and subsystems;
- whether new files may be created;
- no Git history operations.

### C. Behavioral contract

- exact inputs and outputs;
- ordering and determinism rules;
- identity, content-hash, tenant, and provenance requirements;
- exact error classes and atomicity requirements;
- explicit non-goals.

### D. Adversarial proof

- malformed inputs;
- missing, duplicate, reordered, or foreign records;
- forged self-consistent hashes;
- first/middle/last-position tampering;
- no partial write or partial artifact on failure;
- preservation of already accepted behavior.

### E. Gates

- focused tests;
- related boundary and acceptance suites;
- Ruff and formatting;
- mypy;
- schema synchronization;
- full pytest only when the prompt declares this session as its owner;
- final Git diff/status checks.

### F. Final report and hard stop

Hermes must report:

- exact changed behavior and files;
- exact tests added or modified;
- exact command results and counts;
- final Git state;
- anything incomplete or blocked;
- explicit confirmation that no unauthorized Git operation occurred;
- a hard stop without beginning unrelated work.

## 12. Codex review checklist

For every Hermes result, Codex should independently verify:

1. Repository root, branch, HEAD, origin, divergence, and index.
2. Exact changed and untracked path membership.
3. Diff against the file allowlist.
4. Public signatures, constants, `__all__`, and schema catalog changes.
5. Domain neutrality and absence of forbidden NEXUS/LEGION imports.
6. Deterministic ordering, shared-seed fairness, replay, and provenance.
7. Tenant isolation and read-only/no-partial-write guarantees.
8. Adversarial tests and non-weakened historical tests.
9. Documentation truthfulness and absence of overclaims.
10. Focused gates, static gates, schema synchronization, and the full suite
    exactly when this session/checkpoint owns it.
11. That no stage/commit/push/history operation occurred unless explicitly
    authorized.

If a report and the folder disagree, the folder and independently observed
command results are authoritative.

## 13. Git publication discipline

- Normal development remains unstaged until a bounded slice has been audited.
- Hermes does not publish changes.
- Codex stages only the confirmed phase/scope path set.
- Codex inspects the staged name-status, path count, diff, and whitespace
  policy before committing.
- Commit messages follow the existing concise `Phase N: description` style
  when a numbered phase is being officially closed.
- No force push, amend, squash, rebase, reset, or history rewrite without an
  explicit user request.
- A normal push requires separate, explicit user authorization.
- After a push, Codex verifies `HEAD == origin/main`, divergence `0 0`, a clean
  tree/index, and the remote commit through GitHub.

## 14. Next eligible action

The action after this `H27.1-S05-C01-POST-FULL-GATE-TRUTH` correction report
is exactly:

1. Codex audits the two corrected handoffs
   (`CODEX_HERMES_HANDOFF_CURRENT_STATE.md` and
   `KALHAS_STRATEGIC_HANDOFF_PHASES_28_35.md`) and their final fingerprints
   against the live folder.
2. Codex performs the required post-correction verification on the final
   documentation fingerprint.
3. Only if green, Codex records `CP27.1` `CHECKPOINT_ACCEPTED`.
4. Git staging, commit, and push require separate explicit user authorization.
5. Phase 28 does not start automatically and remains not started.
6. Before `H28-S01`, perform the required read-only Phase 28 ADR/design audit.

The implementation and full repository gates are green, but this mechanical
documentation correction does not independently assign checkpoint authority:
the latest Codex live-folder audit is authoritative for the final `CP27.1`
disposition. Until Codex records that disposition on the corrected
documentation fingerprint, the local tree is a fully gated closure candidate,
not an accepted checkpoint. After reading and verifying this handoff, the
next chat should confirm the split between the published baseline (§2.1) and
the local closure candidate (§2.2), state the remaining Gate 27.1 closure
steps above, and wait for the user's explicit instruction.

That is the complete handoff. No additional work is authorized by this file.
