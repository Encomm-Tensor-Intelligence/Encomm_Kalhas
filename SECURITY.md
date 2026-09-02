# Security Policy

## Scope

KALHAS is a **local, in-memory research kernel**. The running application
performs no network calls, no provider calls, and no autonomous live actions.
There is no deployed service, no persistence layer, and no multi-tenant
production surface. Most of the security topics that apply to web services do
not apply here by construction.

## Supported state

Only the latest commit on `main` is supported. There are no release branches
and no tagged releases.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

1. Use GitHub's **Private vulnerability reporting** (Security tab →
   Report a vulnerability) to reach the maintainers confidentially, or
2. Contact the repository owner through their GitHub profile
   [@Xamposs](https://github.com/Xamposs).

Include a minimal reproduction, the affected paths, and your assessment of
impact. You can expect an initial response within 7 days.

## What is in scope

- Boundary violations in the kernel: escapes from the `DomainPack` protocol,
  unauthorized imports of NEXUS/LEGION internals, or broken tenant isolation.
- Integrity failures: evidence that fails hash verification but is accepted,
  replay divergence, or non-deterministic behavior in production code.
- Injection or code execution through declarative surfaces (domain-pack
  manifests, bindings, declarations, policy ASTs) that must remain inert.
- Dependency vulnerabilities in the pinned runtime dependencies.

## What is out of scope

- The local Colony demonstration UI: it renders synthetic mock activity, is
  intentionally separate from the verified pipeline, and is not a hardened
  application.
- Availability of the local development server.
- Any claim about scientific validity, calibration, or fitness for a
  real-world decision: the evidence produced by KALHAS is deterministic
  output under declared models and recorded assumptions — not calibrated and
  not certainty.

## Data handling

No real company or personal data belongs in code, fixtures, docs, or tests.
Reports should not include real data either; use the synthetic fixtures the
repository ships with.
