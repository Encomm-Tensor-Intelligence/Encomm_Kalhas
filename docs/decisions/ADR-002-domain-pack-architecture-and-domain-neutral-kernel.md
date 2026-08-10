# ADR 002: Domain-pack architecture and domain-neutral kernel

- Status: Accepted
- Date: 2026-08-08
- Deciders: KALHAS foundation

## Context

KALHAS must stay reusable across arbitrary future domains. Baking any domain
into the kernel would couple the world-model and simulation machinery to one
domain, force rewrites for each new domain, and make the kernel untestable in
isolation.

## Decision

- The kernel (`kalhas/`) is **domain-neutral by construction**: no domain
  vocabulary, no domain tables, no domain rules.
- Every domain arrives as a **domain pack** under `kalhas/domain_packs/`,
  satisfying the `DomainPack` protocol (Phase 0 placeholder: `name`,
  `version`, `build_world_model`).
- The kernel never imports domain-pack internals; it interacts with packs only
  through the protocol, so packs can be added, versioned, or removed without
  kernel changes.
- Phase 0 ships **no pack implementations** - only the boundary contract.
- No live actions: packs and kernel must remain side-effect-free in the MVP
  (no network calls, provider calls, or real-world effects).

## Consequences

- Arbitrary domains plug in without kernel modification.
- Domain work can be parallelized and isolated from the kernel.
- Clear testing story: protocol conformance tests per pack.
- The protocol must be designed carefully up front; refinement is expected as
  the world-model and campaign contracts land in later phases.
