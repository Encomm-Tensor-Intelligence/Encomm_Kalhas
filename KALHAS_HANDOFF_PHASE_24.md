# KALHAS Handoff — Phase 24 Complete, Phase 25 Next

Date: 2026-08-12  
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`  
Branch: `main`  
Current local HEAD: `043ee224b6ddf0c745c7ab0e60d4d179eee9df9b`  
Current HEAD subject: `Phase 24: deterministic world uncertainty realizations`  
Remote baseline: `origin/main == 215729d9b5ab081c0780be515585e91fd4fe77cd`  
Branch relationship: local `main` is **2 commits ahead and 0 behind** `origin/main`  
Push status: **Phase 23 and Phase 24 have not been pushed**

## 1. Read this first

KALHAS is complete, committed locally, and independently verified through
**Phase 24**.

The next task is **Phase 25 — Realization-Aware Trajectory Runtime 3.0.0**.
Do not begin Phase 25 implementation immediately. The required first step is a
fresh, repository-backed, **read-only Phase 25 design audit**. Implementation
must start only after the audit report has been independently reviewed and a
separate implementation prompt has been approved.

The two most recent phase commits are local only:

```text
043ee224b6ddf0c745c7ab0e60d4d179eee9df9b
Phase 24: deterministic world uncertainty realizations

dfe851122e7d8ede349ba10db31376e238e3c6e7
Phase 23: objective-to-metric evaluation semantics
```

The pushed remote remains at the Phase 22 baseline:

```text
215729d9b5ab081c0780be515585e91fd4fe77cd
KALHAS: domain-neutral decision-world kernel through Phase 22
```

Never assume that a local commit has been pushed. The user alone decides when
to push.

## 2. Expected working-tree state after this handoff is created

The expected working tree is:

```text
 M KALHAS_HANDOFF_PHASE_22.md
?? KALHAS_HANDOFF_PHASE_24.md
```

`KALHAS_HANDOFF_PHASE_22.md` is a deliberately preserved local-only historical
handoff. It was not included in either the Phase 23 or Phase 24 commit.

Its required MD5 is:

```text
D6A857F091BCF7AB596583054B55659E
```

Do not edit, stage, commit, restore, reset, or delete it.

This new `KALHAS_HANDOFF_PHASE_24.md` is also a handoff artifact and is not part
of Phase 25 implementation scope unless the user explicitly decides otherwise.

## 3. Collaboration and orchestration protocol

The user communicates with Codex in Greek. All implementation/audit prompts
given to Hermes must be written in English.

The agreed workflow is:

1. Codex is the orchestrator and independent reviewer.
2. Codex does not directly implement phase code.
3. Codex writes precise English prompts for the user to give to Hermes.
4. Hermes performs the requested audit or implementation and returns a report.
5. Codex then directly inspects the real repository, diffs, contracts, tests,
   schemas, and gates rather than trusting the report alone.
6. If defects exist, Codex supplies a focused corrective English prompt.
7. A phase is committed only after independent verification and explicit user
   approval.
8. A push occurs only when the user explicitly says to push. A local commit is
   not permission to push.

The user commonly starts a fresh Hermes session for each major audit or
implementation continuation to maintain clear token and state control.

## 4. Authoritative files and instruction hierarchy

Read these before Phase 25 work:

1. `C:\Users\xampos\Desktop\Encomm-Kalhas\AGENTS.md`
2. `C:\Users\xampos\Desktop\Encomm-Kalhas\KALHAS_HANDOFF_PHASE_24.md`
3. `C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md`
4. The committed repository at local HEAD `043ee224`
5. Existing tests and architecture documentation

When sources conflict:

- `AGENTS.md` hard rules win.
- Shipped public v1 contracts and established compatibility tests are frozen.
- The Phase 23–27 blueprint defines the intended phase boundaries.
- Repository reality must be inspected directly; do not design from memory or
  from a prior report alone.
- If Phase 25 requirements conflict with a frozen contract, add a focused new
  versioned artifact or stop and report the exact conflict. Never mutate a
  shipped contract in place.

## 5. Durable architecture rules

Only three components exist:

- **NEXUS** owns natural-language dialogue, organizational context, memory,
  and presentation.
- **LEGION** owns strategy and agent exploration.
- **KALHAS** owns versioned world models, uncertainty, deterministic simulation
  campaigns, evidence, replay, and the future living-simulation experience.

Do not introduce another component or integration surface.

Hard invariants:

1. The KALHAS kernel is domain-neutral.
2. Domain-specific concerns enter only through domain packs under
   `kalhas/domain_packs/` and the `DomainPack` protocol.
3. KALHAS core never imports NEXUS or LEGION internals.
4. Only the placeholder adapter protocols in `kalhas/adapters/` are allowed
   coupling surfaces.
5. Deterministic replay and fair strategy comparison are mandatory.
6. Strategies compared in one campaign must share identical conditions.
7. No live actions, provider calls, external effects, databases, or production
   integrations belong in the MVP.
8. No real company or personal data belongs in code, fixtures, tests, or docs.
9. Shipped public contracts under `kalhas/contracts/v1/` are frozen.
10. Breaking changes require a new contract/API version, never an in-place
    mutation.
11. Every behavioral change requires tests.
12. `pytest`, Ruff, formatting, mypy, schema synchronization, and diff hygiene
    must be green before completion.

## 6. Verified repository history

### Phase 22 remote baseline

Commit:

```text
215729d9b5ab081c0780be515585e91fd4fe77cd
KALHAS: domain-neutral decision-world kernel through Phase 22
```

This is still `origin/main`.

### Phase 23 local commit

Commit:

```text
dfe851122e7d8ede349ba10db31376e238e3c6e7
Phase 23: objective-to-metric evaluation semantics
```

Phase 23 introduced objective-to-metric evaluation semantics without executing
new strategies or changing runtime 2.0.0.

Key Phase 23 artifacts:

- `ScenarioEvaluationProfile`
- `CampaignObjectiveEvaluationMatrix`
- strict immutable per-scenario evaluation-profile declaration
- verified query and pure objective-evaluation runtime
- evaluation profile embedded in a compiled world only when present
- profile-free Phase 22 worlds remain byte-identical

Authoritative Phase 23 semantics:

- Caller supplies only objective/metric binding choices plus tolerance and
  normalization inputs.
- Direction, target, weight, and metric unit come from the stored
  `ScenarioSpec` and cannot be forged.
- Coverage is exact: one binding per objective in exact scenario objective
  order.
- Signed adverse delta:
  - minimize: `value - target`
  - maximize: `target - value`
  - reach: `abs(value - target) - reach_tolerance`
- Positive delta is adverse.
- `target_achieved = delta <= 0`.
- `normalized_target_violation = max(0, delta) / normalization_scale`.
- Optimization-only objectives have null target-derived fields.
- Runtime version is explicit and required.
- All reads strictly revalidate stored records and independently recheck
  identifier/content hashes.
- The verified query chain uses only fully verified campaign observations,
  world snapshots, and the stored/embedded evaluation profile.
- No ranking, regret, probability, confidence, risk, recommendation, NEXUS, or
  LEGION behavior was introduced.

Phase 23 commit scope:

- 40 files
- 6769 insertions
- 32 deletions
- no push

### Phase 24 local commit

Commit:

```text
043ee224b6ddf0c745c7ab0e60d4d179eee9df9b
Phase 24: deterministic world uncertainty realizations
```

Parent:

```text
dfe851122e7d8ede349ba10db31376e238e3c6e7
```

Phase 24 commit scope was independently verified:

- exactly 47 files
- 22 new files
- 25 modified files
- 9752 insertions
- 54 deletions
- no handoff file included
- no Phase 25/runtime-3 file included
- no RunPlan or runtime-2 input-hash file changed
- no push

## 7. Phase 24 public contracts and registration

Phase 24 added exactly three top-level public contracts at the tail of
`PUBLIC_CONTRACTS`:

```text
index 37: WorldUncertaintyModel
index 38: WorldRealization
index 39: CampaignWorldRealizationMatrix
```

Final public contract count:

```text
40
```

Indexes 0–36 retain their original order and semantics.

The nested types are not registered as top-level public contracts:

- `UniformDistribution`
- `TriangularDistribution`
- `NormalDistribution`
- `LognormalDistribution`
- `DiscreteDistribution`
- `StateFieldUncertaintyBinding`
- `SampledStateFieldValue`
- `RealizedStateFieldValue`

Exactly three Phase 24 schema artifacts were added:

- `schemas/v1/WorldUncertaintyModel.schema.json`
- `schemas/v1/WorldRealization.schema.json`
- `schemas/v1/CampaignWorldRealizationMatrix.schema.json`

All 37 earlier schema artifacts remain unchanged. The schema directory contains
40 `.schema.json` files; its additional `README.md` is not a schema artifact.

The previously shipped `UncertaintyDefinition` was not modified or repurposed.

## 8. Phase 24 uncertainty declaration semantics

`WorldUncertaintyModel` is an immutable, one-per-scenario collection of initial
state uncertainty bindings.

Rules:

- Declaration must occur before the first world compilation for the scenario.
- Duplicate declaration is rejected; there is no update/delete/replace/repair
  surface.
- At least one uncertainty binding is required when a model exists.
- Absence of a model means an empty uncertainty set.
- Partial coverage is valid: untargeted state fields retain their declared
  deterministic initial values.
- Only `integer` and `number` initial-state fields may be targeted.
- One binding is allowed per complete target tuple.
- Bindings are canonicalized by the complete target identity.
- All authoritative scenario, domain-pack binding, manifest, pack,
  state-model, field-kind, sampler, identity, and hash provenance is copied
  from verified stored records, never accepted from the caller.
- Integer targets require an explicit closed rounding policy:
  `floor`, `ceil`, or `nearest_ties_to_even`.
- Number targets forbid an integer rounding policy.
- Lower and upper clipping bounds are independently optional.
- Integer-field bounds must remain exact integers.
- Every successful final value must satisfy the complete existing state-model
  kind and `allowed_values` rules.
- There is no hidden retry or resampling when a sampled value is invalid.

Supported closed distribution families:

- `uniform(low, high)`
- `triangular(low, mode, high)`
- `normal(mean, standard_deviation)`
- `lognormal(mu, sigma)` with explicit log-space parameters
- `discrete(values, probabilities)`

All numeric inputs are strict and finite; booleans, strings, containers,
`None`, NaN, and infinity are rejected before coercion.

Canonical JSON numeric representation is significant:

- integer `1` and float `1.0` are distinct;
- continuous raw samples are floats;
- discrete samples preserve the exact declared `int`/`float` type;
- clipping a number target adopts the stored bound representation;
- integer target final values are exact integers after rounding.

## 9. Phase 24 deterministic sampler

Sampler provenance:

```text
sampler_version: sha256-counter-v1
quantization_policy: rational-round-half-even
quantization_fraction_bits: 64
```

The sampler is pure and uses integer Q64.64 transforms.

Digest input for every consumed word includes:

```text
domain: kalhas/world-realization-v1
draw_index
sampler_version
seed_content_hash
uncertainty_binding_content_hash
world_content_hash
```

The first eight SHA-256 digest bytes are interpreted as one big-endian 64-bit
word. There is no global RNG state and no strategy input in the digest.

Parameter quantization:

- uses `float.as_integer_ratio()`;
- uses exact integer `divmod`;
- rounds half to even;
- never performs hidden `value * 2**64` float quantization;
- rejects nonzero values that would silently quantize to zero;
- applies explicit magnitude and resource guards.

Transforms:

- exact integer square root through `math.isqrt`;
- fixed-iteration integer natural logarithm;
- correctly range-reduced exponential using `ln(2)` and bounded shifts;
- fixed-iteration integer cosine with quadrant reduction;
- corrected Box–Muller normal transform;
- structurally nonzero open-uniform input `u = (word + 1) / 2**64`;
- exact-weight discrete ticket selection with strict boundary behavior;
- zero-probability discrete values are never selected;
- no forced residual probability and no hidden retry loop.

Normal and lognormal bindings consume two digest words. Uniform, triangular,
and discrete bindings consume one. `SampledStateFieldValue` records the starting
`draw_index` and `draw_count`; all consumed word ranges must be contiguous,
ordered, gap-free, and non-overlapping.

Sampling pipeline:

```text
sample exact fixed-point raw value
→ require finite/recordable raw value
→ record raw value
→ apply independently optional clipping bounds
→ apply integer rounding when required
→ preserve canonical numeric representation
→ validate the complete realized state
```

Clipping never rescues a non-finite or unrecordable raw sample.

## 10. Phase 24 realization semantics

`WorldRealization` is one immutable, strategy-independent realization of one
compiled world under one scenario seed.

It records:

- tenant/scenario/world identity and world content hash;
- scenario-seed identity and derived seed content hash;
- uncertainty-model identity/hash or explicit absence;
- sampler and quantization provenance;
- ordered sampled values;
- complete realized initial-state override delta;
- independently derived identifier and content hash;
- deterministic `realized_at` inherited from `campaign.created_at`.

The override delta contains exactly one final override per uncertainty binding
and no entry for untargeted base-state fields.

Worlds without an uncertainty model still produce one deterministic empty
realization per seed. Empty realizations have real independently derived content
hashes, not placeholder hashes.

`CampaignWorldRealizationMatrix` contains exactly one realization per campaign
seed in exact seed-ensemble order:

```text
K seeds × S strategies → K world realizations, never K × S realizations
```

Strategy identifiers do not enter realization identities, hashes, sampled
values, overrides, or the matrix contract.

The matrix is derived in memory and is not stored. Repeated verified queries
return byte-identical artifacts.

There is deliberately no campaign lifecycle-state gate for this pure derived
artifact. When immutable campaign/world/model inputs are identical, mutable
campaign status does not change realization bytes. Failed/cancelled campaigns
retain their deterministic realization provenance.

## 11. Phase 24 world integration and integrity

Compiled worlds embed `uncertainty_model` only when a model exists.

When no model exists:

- Phase 23 compilation bytes and hashes remain unchanged;
- runtime 2.0.0 behavior remains unchanged.

When a model exists:

- the full immutable snapshot is embedded and hash-covered;
- the world manifest records its declared presence;
- world integrity verifies ownership, scenario hash, identifiers, content
  hashes, canonical order, unique targets, domain-pack binding provenance,
  manifest/pack provenance, state-model identity/content, state field and kind,
  sampler/quantization literals, effective parameter rules, and static discrete
  final-value rules;
- full recompilation equality is required;
- corruption is rejected, never repaired.

The in-memory store uses deep-copy boundaries and strict serializer-based
revalidation on write and every read. Identifier and content hashes are
independently re-derived at trust boundaries.

The realization query verifies:

1. tenant-scoped campaign existence;
2. campaign/world linkage;
3. compiled world and manifest integrity;
4. embedded uncertainty model integrity;
5. stored model strict revalidation and exact equality with the embedded
   snapshot;
6. deterministic realization and matrix construction.

Missing/corrupt campaign inputs map to the focused matrix integrity error.
Deterministic sampling failures remain a typed conflict and are not silently
converted into successful or partial matrices.

## 12. Phase 24 API

The following endpoints exist and were verified through OpenAPI:

```text
POST /v1/scenarios/{scenario_id}/uncertainty-model
GET  /v1/scenarios/{scenario_id}/uncertainty-model
GET  /v1/campaigns/{campaign_id}/world-realizations
```

Error behavior:

- unknown/foreign tenant-scoped resources: 404;
- invalid declarations: 422;
- duplicate declaration, declaration after compilation, or deterministic
  sampling failure: 409 conflict;
- corrupted stored/embedded/model/realization/matrix provenance: 409 integrity
  error.

Successful realization responses necessarily expose their artifact values.
Error responses use safe generic messages and do not leak sampled values,
distribution parameters, bounds, hashes, state values, metadata, or validator
diagnostics.

GET operations are read-only and create no operational activity event.

## 13. Phase 24 verification record

Independent pre-commit verification at local commit `043ee224`:

```text
uv run python scripts/export_schemas.py --check
→ all schema artifacts are synchronized

uv run pytest
→ 2509 passed, 1 skipped, 2 warnings

uv run ruff check .
→ All checks passed!

uv run ruff format --check .
→ 205 files already formatted

uv run mypy kalhas tests
→ Success: no issues found in 195 source files

git diff --check
→ clean
```

Focused Phase 24 tests cover contracts, the sampler, declaration service, store
isolation, world integrity, realization builder, verified query service, API,
and source/architecture boundaries.

The Phase 24 focused suite contains 247 tests.

Important pre-existing test caveat:

- `tests/test_api_phase23.py::test_error_bodies_never_leak_values` searches for
  the text `"91"` in a response body.
- The request id is UUID-derived and can randomly contain `91`.
- This creates an approximately intermittent, pre-existing Phase 23 flake.
- It failed once during Phase 24 work and passed on rerun and in the final full
  verification.
- Do not misdiagnose this random request-id substring as a Phase 24 or Phase 25
  product defect.
- Do not modify the historical test without a separate reviewed decision.

The two warnings in the final suite were already known:

- Starlette/httpx TestClient deprecation warning;
- intentional Pydantic serializer warning in a validator-bypass rejection test.

## 14. Phase 25 objective

Phase 25 introduces realization-aware trajectory runtime `3.0.0` while
preserving runtime `2.0.0` exactly.

This is the first phase where shared seeds change simulation initial state and
can therefore change final states and metric observations.

Required new runtime constant:

```text
REALIZATION_TRAJECTORY_RUNTIME_VERSION = "3.0.0"
```

The existing constant and semantics must remain unchanged:

```text
TRAJECTORY_RUNTIME_VERSION = "2.0.0"
```

Runtime dispatch must use only the runtime version recorded in the immutable
`RunPlan`. There must be no query-time or caller-provided switch that reinterprets
an already planned 2.0.0 campaign as 3.0.0.

## 15. Required Phase 25 runtime behavior

Runtime 2.0.0 must remain byte-for-byte compatible:

- initial state comes only from `DomainStateModel.initial_value`;
- seeds remain provenance only;
- existing runtime-2 contracts, ids, hashes, fixtures, APIs, replay, matrices,
  observations, and golden tests remain unchanged.

Runtime 3.0.0 must:

1. verify or reconstruct the exact Phase 24 realization for the run's recorded
   seed;
2. supply realized initial-state overrides to the deterministic transition
   engine;
3. fully validate the realized initial state before the first transition;
4. apply the exact already-verified strategy trajectory plan;
5. record realization identity and content hash in focused runtime-3 artifacts;
6. support exact replay from recorded immutable inputs;
7. produce metric observations from realized final states;
8. remain deterministic after realization;
9. preserve guard and target semantics;
10. never mutate source contracts or state inputs.

## 16. Required Phase 25 additive contracts

Existing runtime-2 contracts contain literal `"2.0.0"` fields and must not be
mutated.

Phase 25 needs focused runtime-3 public artifacts for:

- realization-aware run trajectory execution;
- realization-aware replay manifest;
- runtime-3 campaign trajectory matrix;
- runtime-3 run metric observation set;
- runtime-3 campaign metric observation matrix;
- runtime-3 campaign metric statistics matrix.

Every runtime-3 artifact must include the relevant:

- `world_realization_id`
- `world_realization_content_hash`

Nested value objects may be reused only if their shipped semantics remain
exactly true. Internal generic helpers may be shared behind version-specific
public contracts when doing so does not weaken version boundaries or mutate
runtime-2 behavior.

The Phase 25 audit must determine the exact contract names, modules,
registration order, schema count, field tables, identity payloads, content-hash
coverage, and tamper rules before implementation.

## 17. Phase 25 run planning and input hashing

The existing `RunPlan` may potentially be reused because its runtime version and
input hash are generic strings. This must be confirmed against the real frozen
contract.

Runtime 3.0.0 input hashing must use a separate explicit function and cover:

- runtime version;
- base world content hash;
- exact strategy content;
- exact seed content;
- exact world realization content hash.

The same seed realization hash must appear in every strategy's runtime-3 run
input for that seed.

Never silently change the runtime-2 input-hash function or payload.

The Phase 25 audit must inspect all current run-plan creation, preflight,
verification, replay, and query call sites to define a safe runtime-version
dispatch boundary.

## 18. Phase 25 transition-engine extension

The pure transition engine must either:

- gain an optional explicitly supplied initial state; or
- gain a new focused pure entry point.

Whichever design is chosen must prove:

- the default path remains byte-for-byte runtime-2 compatible;
- supplied realized state is completely validated before execution;
- no input is mutated;
- the realized initial-state hash becomes the authoritative runtime-3 initial
  state hash;
- guards and targets retain their current exact semantics;
- replay regenerates the same initial state, trace, final state, and hashes.

Do not choose between these alternatives during implementation. The read-only
audit must inspect the actual engine and resolve the design first.

## 19. Phase 25 campaign preparation and execution

Runtime-3 campaign preparation must:

1. verify the compiled world and embedded uncertainty model;
2. build and verify the Phase 24 realization matrix once;
3. generate the strategy × seed `RunPlan` matrix;
4. bind each seed's realization hash into every strategy's corresponding run
   input hash;
5. retain strategy-major, seed-minor execution order;
6. preserve identical conditions across strategies.

Execution may remain synchronous and in-memory.

The audit must determine how a campaign is intentionally prepared as runtime
3.0.0 without creating a query-time reinterpretation switch and without
changing historical default runtime-2 fixtures.

## 20. Phase 25 API behavior

Existing high-level endpoints should dispatch according to the recorded
campaign/run runtime version and return the correct versioned response model.

The audit must inspect the actual FastAPI/router version in this repository and
resolve whether OpenAPI needs:

- an explicit union response; or
- separate version-documented responses/endpoints.

No caller may reinterpret an already planned 2.0.0 campaign as 3.0.0.

Error responses must preserve tenant isolation, safe generic messages, and the
established 404/409 invalid-state/conflict/integrity distinctions.

## 21. Phase 25 local strategy differentiation

The current local `MockLegionAdapter` normally proposes the same canonical
transition sequence for every strategy. Phase 25 demonstration evidence would
be meaningless if all strategies remained identical.

Additive local-only differentiation is required, but only after design audit:

- preserve existing default behavior for all Phase 15–24 fixtures;
- allow explicit generic test/example strategy declarations to request distinct
  valid transition sequences from the closed catalog;
- keep the mock proposal untrusted;
- revalidate every proposal through the existing KALHAS binding service;
- the mock must never read outcomes, uncertainty samples, guard values, target
  values, or future results while selecting a sequence;
- do not introduce domain-specific heuristics;
- do not optimize a strategy inside the mock;
- do not pretend the mock is intelligent.

Real strategy exploration remains LEGION's later responsibility.

The audit must inspect `StrategyRequest`, `StrategyCandidate`, mock behavior,
trajectory-plan preparation, and relevant API request surfaces to find the
smallest backward-compatible declaration mechanism.

## 22. Phase 25 required verification

At minimum, Phase 25 tests must prove:

- all runtime-2 tests remain unchanged and green;
- runtime-2 golden identifiers and hashes are unchanged;
- runtime-3 input hash includes the realization hash;
- the same seed realization is used by all strategies;
- different seeds can create different initial states and outcomes;
- realized state is validated before execution;
- runtime-3 replay regenerates the same realization, execution, trace, final
  state, observations, and hashes;
- tampered realization, seed, world, strategy, plan, execution, or observation
  is rejected;
- runtime-specific literal enforcement;
- unsupported runtime rejection;
- runtime-3 campaign trajectory, observation, and statistics matrix shapes;
- numeric observations vary when sampled state affects final state;
- tenant isolation, snapshot isolation, and safe error messages;
- no probability, ranking, recommendation, adaptive switching, real adapters,
  or domain-specific logic.

Required generic acceptance demonstration:

```text
Seed 1 → realized initial state X → final metric 84
Seed 2 → realized initial state Y → final metric 103
```

Both Strategy A and Strategy B must receive X under Seed 1 and Y under Seed 2.

The literal values 84 and 103 are an acceptance-shape example from the
blueprint. The audit must construct a generic domain-neutral fixture that
demonstrates the required causal variation without embedding domain-specific
logic in the kernel.

## 23. Phase 25 non-goals

Phase 25 must not implement Phase 26 or Phase 27 behavior.

Explicitly out of scope:

- empirical outcome distributions;
- target-achievement probability;
- quantiles or CVaR;
- risk evidence;
- paired strategy deltas;
- robustness comparison;
- regret;
- Pareto/dominance logic;
- preference or ranking;
- recommendation or decision brief;
- adaptive strategy switching;
- real NEXUS/LEGION integrations;
- live providers or external effects;
- domain-specific mechanisms in the kernel.

Phase 25 produces realization-aware deterministic execution and observations,
not campaign-level statistical evidence or decisions.

## 24. Mandatory first action in the new chat

The first Phase 25 task is a **read-only audit**, not implementation.

The audit must:

1. verify current HEAD, origin, ahead/behind, working tree, and handoff hashes;
2. read `AGENTS.md`, this handoff, and the complete Phase 25 blueprint section;
3. inspect all relevant current contracts, planners, input-hash functions,
   transition engine entry points, runtime execution paths, replay paths,
   trajectory/observation/statistics query builders, store seams, API routes,
   errors, mock LEGION behavior, tests, schemas, and documentation;
4. map every frozen runtime-2 surface that must remain unchanged;
5. propose exact additive runtime-3 contracts and identities;
6. specify the runtime-3 run-input hash payload exactly;
7. specify exact runtime dispatch and lifecycle behavior;
8. specify transition-engine realized-state injection and validation;
9. specify exact realization reconstruction/verification for execution and
   replay;
10. specify exact runtime-3 matrices and observation provenance;
11. resolve local strategy differentiation safely;
12. provide an exact file/change/schema/test plan;
13. identify ambiguity, compatibility risks, and required decisions;
14. make zero repository changes;
15. stop and await independent review.

Do not report `safe to implement` if any contract shape, identity/hash payload,
runtime dispatch rule, replay invariant, API response design, or compatibility
decision remains deferred to implementation time.

## 25. Baseline commands for the new chat

Run read-only checks first:

```powershell
git status --short
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count origin/main...HEAD
git log -3 --format="%H`t%s"
Get-FileHash -Algorithm MD5 KALHAS_HANDOFF_PHASE_22.md
Get-FileHash -Algorithm SHA256 KALHAS_HANDOFF_PHASE_24.md
uv run python scripts/export_schemas.py --check
```

Expected repository identity:

```text
HEAD = 043ee224b6ddf0c745c7ab0e60d4d179eee9df9b
origin/main = 215729d9b5ab081c0780be515585e91fd4fe77cd
ahead/behind = 0 2 when using origin/main...HEAD
```

Do not treat the expected handoff-only working-tree changes as product-code
corruption.

For implementation completion gates later, the repository requires:

```powershell
uv run python scripts/export_schemas.py --check
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy kalhas tests
git diff --check
```

## 26. Ready-to-use new-chat bootstrap prompt

Use the following prompt in the new Codex chat:

```text
Work as the orchestrator and independent reviewer for KALHAS Phase 25.

Repository:
C:\Users\xampos\Desktop\Encomm-Kalhas

Read completely before proceeding:

1. C:\Users\xampos\Desktop\Encomm-Kalhas\AGENTS.md
2. C:\Users\xampos\Desktop\Encomm-Kalhas\KALHAS_HANDOFF_PHASE_24.md
3. C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md

Current expected repository state:

- HEAD: 043ee224b6ddf0c745c7ab0e60d4d179eee9df9b
- HEAD subject: Phase 24: deterministic world uncertainty realizations
- origin/main: 215729d9b5ab081c0780be515585e91fd4fe77cd
- local main: 2 ahead, 0 behind
- Phase 23 and Phase 24 are local commits and have not been pushed
- KALHAS_HANDOFF_PHASE_22.md is a preserved local-only modification with MD5
  D6A857F091BCF7AB596583054B55659E
- KALHAS_HANDOFF_PHASE_24.md is the new local handoff artifact
- Phase 25 has not started
- push is not authorized

The user communicates in Greek, but all prompts intended for Hermes must be in
English.

Do not implement Phase 25 directly. Codex is the orchestrator: inspect the real
repository read-only, prepare precise English prompts for Hermes, review every
Hermes report against the actual working tree, and authorize commits only after
independent verification. Never push unless the user explicitly instructs it.

First verify the repository baseline. Then prepare a comprehensive English
read-only PHASE 25 DESIGN AUDIT prompt for Hermes. The audit must resolve every
runtime-3 contract, identity/hash, planner, transition-engine, replay, matrix,
observation, API dispatch, local strategy-differentiation, compatibility, file,
schema, and test decision before implementation. It must make zero repository
changes and must not begin Phase 26.
```

## 27. Final status

Phase 24 is complete, locally committed, and independently verified.

Current local phase chain:

```text
Phase 22 remote baseline
→ Phase 23 local objective-evaluation semantics
→ Phase 24 local deterministic uncertainty realizations
→ Phase 25 next: read-only runtime-3 design audit
```

Nothing from Phase 25 or later has been implemented.

No push is authorized by this handoff.
