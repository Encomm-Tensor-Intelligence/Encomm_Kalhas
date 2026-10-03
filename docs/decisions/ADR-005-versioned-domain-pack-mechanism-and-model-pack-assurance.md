# ADR 005: Versioned DomainPack mechanism and Model Pack assurance

- Status: Accepted
- Date: 2026-09-13
- Deciders: KALHAS foundation

## Context

ADR-002 established the domain-neutral kernel and the `DomainPack` boundary.
At Phase 0 it also recorded a deliberately temporary limitation: the protocol
was manifest-only, shipped no pack implementations, and the Phase 29 entry
audit found the boundary tests enforcing that shape permanently ("no callable
protocol member may ever exist", "no domain-pack implementation may ever
ship"). Phase 29 (strategic handoff §11) introduces the first executable
domain mechanism and the `Model Pack` assurance vocabulary, so those
manifest-only assumptions must now be superseded by an authorized, versioned
protocol decision before any behavioral slice runs.

This ADR records the accepted Phase 29 architecture. It changes only the
accepted architecture record and the obsolete permanent boundary-test
assumptions. Later slices (`H29-S02A` through `H29-S09`) implement these
decisions. At the time of writing, no executable mechanism contract, PAN
pack, dispatcher, runtime integration, Model Pack artifact, or cross-platform
proof exists; this ADR must not be read as claiming any of them.

Scope of supersession: this ADR supersedes **only** the Phase-0
manifest-only limitation in ADR-002 ("Phase 0 ships no pack implementations -
only the boundary contract" together with the protocol's manifest-only
shape). ADR-002's domain-neutrality decisions and its no-live-effects
decisions remain fully in force and are preserved unchanged.

## Decision

### D29-01 — Versioned evolution of the manifest-only DomainPack protocol

- The shipped public v1 `DomainPackManifest`, `DomainPackBinding`, and
  `DomainCapabilityDeclaration` contracts remain byte-frozen and
  semantically frozen. No field, validator, literal, default, ordering, or
  semantic of these contracts changes; an executable pack evolves only
  through additive capability, never by mutating shipped v1 records.
- Existing manifest records remain valid, inert
  registration/binding/world inputs. A manifest never becomes executable
  automatically: registration, binding, and world compilation continue to
  treat manifests purely as metadata.
- Phase 29 evolves the single Python `DomainPack` boundary explicitly. There
  is exactly one pack boundary; no parallel pack surface is created.
- An executable pack exposes:
  - its immutable `DomainPackManifest`;
  - its exact release profile identity;
  - mechanism protocol version `1.0.0`;
  - exactly one pure `step(request) -> result` operation.
- A legacy manifest-only carrier remains valid as inert metadata. It is not
  an executable pack. Missing or mismatched executable identity (protocol
  version, release-profile binding, or mechanism identity) fails closed;
  nothing silently promotes inert metadata into executable behavior.
- No second component, plugin bus, pack runtime, executable registry,
  dynamic discovery mechanism, or alternate integration protocol is created.
  Runtime 4 remains the only execution authority.

The following additive public artifact names are frozen now for use by later
slices. They are **not implemented in Phase 29 ADR scope**; later slices
implement them as versioned public contracts over the same `DomainPack`
identity:

- `DomainMechanismSpec`
- `DomainMechanismStepRequest`
- `DomainMechanismStepResult`
- `ModelPackReleaseProfile`
- `ModelPackAssuranceProfile`
- `ModelPackCatalogueEntry`

### D29-02 — Pure mechanism seam, composition, and identity semantics

The mechanism is semantically:

```text
verified state
+ validated action
+ ordered, coordinate-addressed exogenous inputs
+ immutable configuration
-> verified next state
+ typed emissions
+ deterministic mechanism evidence
```

- The mechanism performs no filesystem, network, provider, database, clock,
  environment, dynamic-import, subprocess, global-state, or global-RNG
  access. It reads no wall clock, environment variable, mutable global, or
  global random source; all randomness arrives as already-addressed
  exogenous input.
- The mechanism cannot choose policy, compare strategies, persist authority,
  schedule a second simulation, or call NEXUS or LEGION.
- Composition is explicit: callers hand a concrete conforming `DomainPack`
  object to the seam. Identifiers or import paths carried inside public data
  never load code; dynamic resolution from data fails closed.
- Runtime 4 remains the only scheduler/execution authority and invokes the
  mechanism exactly once at the declared step. Existing runtime-4 records
  that carry no mechanism identity retain their historical meaning; they are
  never reinterpreted as mechanism executions.
- Randomness is supplied only through immutable counter/key-addressed values
  whose recorded coordinates bind world, realization/seed, run, step,
  stream, variable, entity/slot, and draw index. Mechanism branching, call
  order, retries, or scheduling cannot shift unrelated draws. Precomputed
  immutable draws remain an allowed equivalent.
- State, action, configuration, and emission schemas and units are
  pack-owned. Generic orchestration, validation order, runtime identity,
  evidence binding, and replay remain KALHAS-owned. The kernel never gains
  domain vocabulary.
- Every failure is atomic: a mechanism step either produces one complete
  validated result or no result, no authority mutation, and no observable
  activity. Partial state is impossible by construction.
- Behavior-affecting identity is complete: solver, timestep, event order,
  precision, rounding, implementation, dependency-lock, configuration, and
  data identities are part of the pack/mechanism identity. Any change to one
  of them requires a new appropriate identity/version; it is never an
  in-place change.

### D34-01 — Phase 29 numerical/platform decision

The cross-platform rule required by the strategic register no later than
Phase 29 is: **exact replay only under a recorded platform identity**
(option 2 of §16 Phase 34B).

- The profile identifier is `kalhas-platform-bound-binary64-v1`.
- At the mechanism boundary, only exact built-in integers and finite
  IEEE-754 binary64 values are accepted. Booleans, numeric strings,
  Decimal-like coercions, NaN, infinities, and unrepresentable overflow
  fail closed.
- Arithmetic and reductions follow an explicitly declared stable order.
  No unordered reduction and no implicit tolerance is authoritative.
- Declared quantization uses round-to-nearest, ties-to-even at explicit
  named boundaries only. There is no hidden rounding or clipping.
- Platform identity binds OS, architecture, Python implementation/version,
  dependency lock, mechanism implementation, solver, and the numeric
  profile identifier.
- Replay requires identical authoritative bytes under the recorded platform
  identity. Phase 29 does not claim unexecuted Linux/macOS equivalence.
- A platform mismatch rejects exact replay/comparison unless a later
  accepted cross-platform profile proves equivalence. Changing the
  numerical/platform rule changes identity/version.
- Canonical cross-platform fixtures may be created later, but a
  Windows-only run cannot claim cross-platform proof.

### D29-03 — Model Pack product vocabulary, profiles, and maturity

- `Model Pack` is product vocabulary for one exact, versioned `DomainPack`
  release plus its bound assurance artifacts. It is not a component,
  protocol, registry, runtime, provider adapter, or plugin system, and it
  never authorizes a fourth architectural role.
- `ModelPackReleaseProfile` binds the exact manifest, mechanism,
  configuration, implementation, dependencies, numerical/platform and
  time-basis identities, compatibility, scope, units, provenance,
  datasets/licenses, resource envelope, intended uses, prohibited uses,
  assumptions, and limitations of one release.
- `ModelPackAssuranceProfile` binds one exact release/profile hash to
  evidence, retained failures, bounded supported claims, review state, and
  evidence-derived maturity.
- `ModelPackCatalogueEntry` is declarative catalogue metadata only. It
  cannot resolve or execute code and cannot establish implemented
  capability; a catalogue entry creates no capability.
- These artifacts remain bound to the existing `DomainPack`
  identity/registry. No second executable registry or second source of
  truth is permitted.
- Maturity uses exactly these values and meanings:
  - `catalogued` — roadmap candidate only; no implemented capability;
  - `conformance_only` — synthetic architecture fixture; never a product
    pack;
  - `experimental` — deterministic executable mechanism and conformance
    evidence only; no empirical adequacy claim;
  - `benchmarked` — Phase 30 evidence exists for the exact version, data
    vintage, geography, horizon, and claim;
  - `externally_reviewed` — Phase 33 domain/statistical review closed for
    explicitly bounded claims;
  - `partner_evaluation_ready` — Phase 35 packaging, replay, security, and
    governance evidence exists; still not production approval.
- Maturity and claims never transfer across pack versions, configurations,
  mechanisms, implementations, dependencies, datasets, vintages,
  geographies, horizons, platforms, or domains.
- PAN may reach only `experimental` in Phase 29. The synthetic non-health
  fixture is always `conformance_only`. Every other portfolio entry remains
  `catalogued`.
- No Phase 28-35 artifact may assign `government_ready`, `certified`,
  universally validated, autonomous, or production-safe status.
- The public-sector prohibited-use floor of strategic §11 is preserved: all
  packs are decision support only; they never perform autonomous public
  decisions, eligibility/benefit decisions, enforcement recommendations,
  predictive-policing judgments, individual or social scoring, political
  persuasion, voter targeting, biometric/surveillance assessment, offensive
  cyber action, or other live effects. Outputs remain labeled conditional
  modeled outcomes with accountable human authority visible.
- Covasim, Starsim, and GLEAM/GLEAMviz are reference-only. Phase 29
  authorizes no import, dependency, server/client adapter, callback
  surface, dataset assumption, network call, or execution authority from
  them, and none may be added to dependencies or kernel surfaces.
- Phase 29 uses synthetic/reference fixtures only and adds no dependency
  and no real, personal, or company data.
- Phase 29 changes neither `NexusAdapter` nor `LegionAdapter`. Their
  concrete conformance work remains Phase 31.

## Consequences

- Later Phase 29 slices implement these decisions as additive, versioned
  public surfaces over the single existing `DomainPack` boundary. The
  boundary tests transition from the obsolete permanent manifest-only
  assumptions to durable rules that permit this work without another
  artificial rewrite.
- The durable replacement rule: top-level domain-pack infrastructure
  exposes the protocol only; concrete packs must remain isolated below
  `kalhas/domain_packs/`, must not be dynamically discovered, and must
  never be imported by generic kernel code.
- Existing manifest-only records, bindings, and world inputs stay valid and
  inert; their historical meaning never changes.
- Nothing in this ADR claims that contracts, mechanisms, PAN, dispatcher,
  runtime integration, cross-platform proof, benchmark evidence, or Model
  Pack maturity already exist. Those are the work of later, separately
  authorized slices.
