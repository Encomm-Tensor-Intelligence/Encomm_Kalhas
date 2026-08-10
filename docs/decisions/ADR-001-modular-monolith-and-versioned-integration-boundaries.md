# ADR 001: Modular monolith and versioned integration boundaries

- Status: Accepted
- Date: 2026-08-08
- Deciders: KALHAS foundation

## Context

KALHAS will grow into a long-lived kernel (world models, simulation campaigns,
evidence, replay) embedded in a larger product with two other components:
NEXUS (dialogue, organizational context, memory, presentation) and LEGION
(strategy, agent exploration). Early microservice-style decomposition would add
deployment and consistency costs without proven scaling needs; an
unmodularized monolith would let the components entangle and would make public
contracts drift silently.

## Decision

KALHAS is a **modular monolith**:

- One deployable Python application (FastAPI), organized into clear layers:
  `contracts` (versioned wire contracts), `application` (use cases), `adapters`
  (boundary protocols toward NEXUS/LEGION), `api` (HTTP), `domain_packs`
  (future domain extensions).
- Integration boundaries are **versioned and frozen**: `kalhas/contracts/v1/`
  defines the current public contract surface (API version `1`, URL prefix
  `/v1`). Contracts are immutable once shipped; any breaking change requires a
  new `v2` module and a new API version segment, never an in-place edit.
- KALHAS core depends on **protocols, not on NEXUS/LEGION internals**
  (`NexusAdapter`, `LegionAdapter` placeholders in Phase 0). No NEXUS/LEGION
  imports may appear in `kalhas/` outside those placeholder modules.
- Every endpoint returns errors in one typed shape (`ApiErrorResponse`) so
  clients parse a single error contract across versions.

## Consequences

- Single deployable artifact; simple local development (uvicorn).
- Clear, enforced dependency direction: `api -> application -> contracts`.
- Protocol-based boundaries keep the kernel replaceable and testable.
- Splitting into separate services later requires deliberate effort.
- Versioned contracts add ceremony: a new module and URL segment per breaking
  change.
