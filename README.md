<div align="center">

<img src="docs/banner.svg" alt="KALHAS — deterministic worlds, uncertainty, evidence, exact replay" width="800"/>

# KALHAS

A domain-neutral Python kernel for **versioned world models, declared
uncertainty, deterministic simulation campaigns, evidence, and exact replay** —
the decision-world engine in a strict three-role architecture alongside NEXUS
(dialogue and presentation) and LEGION (strategy and agent exploration).

[![CI](https://github.com/Encomm-Tensor-Intelligence/Encomm_Kalhas/actions/workflows/ci.yml/badge.svg)](https://github.com/Encomm-Tensor-Intelligence/Encomm_Kalhas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://docs.astral.sh/uv/)
[![Tests](https://img.shields.io/badge/tests-7%2C553%20green-2ea44f)](#testing-and-verification)
[![Phase](https://img.shields.io/badge/Phase%2029-complete-8250DF)](#phase-29--complete-and-published)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230?logo=ruff)](#testing-and-verification)
[![Formatting](https://img.shields.io/badge/format-ruff%20format-261230?logo=ruff)](#testing-and-verification)
[![Types](https://img.shields.io/badge/types-mypy%20strict-1F6FEB)](#testing-and-verification)
[![Schemas](https://img.shields.io/badge/schemas-62%20synchronized-F7C744)](#testing-and-verification)
[![Replay](https://img.shields.io/badge/replay-deterministic-2ea44f)](#core-guarantees)

</div>

## What is KALHAS?

KALHAS records **versioned world models** with declared uncertainty, compiles
them into immutable simulation targets, and runs **deterministic campaigns**
over strategy × shared-seed matrices. Every run emits content-hashed evidence;
every completed run can be **replayed exactly**; every comparison between
strategies shares identical recorded conditions. Runtime evidence is
**empirical and evidence-based under declared models and recorded assumptions
— not calibrated and not certainty.** It performs no autonomous live action.

The kernel is deliberately domain-neutral: domain concerns arrive only through
explicitly supplied, versioned domain packs consumed through the `DomainPack`
protocol, and the kernel never imports NEXUS or LEGION internals.

## Core guarantees

- **Versioned public contracts.** All 62 public v1 contracts are frozen once
  shipped, with synchronized JSON Schema artifacts; breaking changes require a
  new version module and API segment, never in-place mutation.
- **Deterministic replay.** Completed runs replay exactly, verified against
  recorded input hashes and event hashes — preflight verification before
  execution, integrity verification before any derivation.
- **Fair strategy comparison.** Campaigns execute ordered strategy × seed
  matrices under identical recorded worlds, seeds, and noise coordinates.
- **Immutable evidence.** Executions, observations, decisions, and switch
  events are immutable, content-hashed, and independently re-derivable;
  read-only query services expose verified projections.
- **Fail-closed integrity.** Tampered inputs, forged evidence, and identity
  mismatches are rejected, never repaired or coerced.
- **No live actions.** Local development only — no network calls, no provider
  calls, no real-world effects from the running application.

## Capabilities at a glance

| Area | What it provides |
| --- | --- |
| Contracts & lifecycle | 62 versioned v1 contracts, canonical serialization, content hashes, campaign lifecycle state machine |
| World models | Immutable world versions, domain-pack bindings, capability-input declarations, uncertainty declarations, deterministic realizations |
| Campaign runtime | Structural, realization-aware (`3.0.0`), and adaptive (`4.0.0`) deterministic runtimes with exact replay |
| Evidence | Run/campaign metric observations, empirical outcome distributions (Type-7 quantiles, fixed-alpha tails), objective evaluations |
| Decision support | Immutable decision policies, paired same-seed comparisons, regret/robustness/Pareto evidence, deterministic briefs — read-only, no winners claimed |
| Adaptive runtime 4.0.0 | Causal mid-run observations, closed bounded policy ASTs, dwell/cooldown/budget switching, exact adaptive replay |
| Model Packs | Release/assurance/catalogue contracts, a pure mechanism dispatcher/runtime, the synthetic `KALHAS-PAN` v0.1 reference pack (`experimental`), the synthetic conformance fixture (`conformance_only`), and a 13-entry catalogue |
| API | FastAPI v1 surface (46 paths / 57 operations), typed error envelope, OpenAPI docs |
| Observability | Operational activity feed; optional local synthetic Colony UI |

## Architecture

| Role | Owns |
| --- | --- |
| **NEXUS** | Natural-language dialogue, organizational context, memory, presentation |
| **LEGION** | Strategy and agent exploration |
| **KALHAS** | Versioned world models, uncertainty, deterministic simulation campaigns, evidence, replay |

These three roles are the only components (see [`AGENTS.md`](AGENTS.md)).
KALHAS couples to the other two solely through the placeholder adapter
protocols in `kalhas/adapters/`.

```mermaid
flowchart LR
    NEXUS["NEXUS<br/>dialogue · context · presentation"]
    LEGION["LEGION<br/>strategy · agent exploration"]

    subgraph KALHAS["KALHAS kernel"]
        direction TB
        API["FastAPI v1 surface<br/>46 paths · typed errors"]
        APP["application services<br/>runtimes 1.0.0 – 4.0.0"]
        CON["versioned v1 contracts<br/>62 contracts · 62 JSON schemas"]
        STORE["in-memory store<br/>snapshots · evidence · replay"]
        API --> APP --> CON
        APP --> STORE
    end

    PACK["versioned domain packs<br/>profiles · pure mechanisms"]

    NEXUS -->|NexusAdapter protocol| API
    LEGION -->|LegionAdapter protocol| API
    PACK -->|DomainPack protocol| APP
```

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (which provisions Python 3.12 and
the virtual environment itself).

```bash
git clone https://github.com/Encomm-Tensor-Intelligence/Encomm_Kalhas.git
cd Encomm_Kalhas
uv sync --python 3.12
uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/docs> for the interactive OpenAPI surface.

> If a globally set `PYTHONPATH` shadows the project venv (`ModuleNotFoundError`
> on `uv run`), clear it first: `unset PYTHONPATH` (bash) or
> `Remove-Item Env:PYTHONPATH` (PowerShell).

## Minimal local example

With the server running:

```bash
curl -s http://127.0.0.1:8000/health
curl -s -H "X-Tenant-ID: tenant-1" http://127.0.0.1:8000/v1/system-info
```

Every API response uses one typed error shape (`code`, `message`, `details`,
`request_id`), and every endpoint is tenant-scoped and read-only or
explicitly lifecycle-gated. The architecture guides describe the complete
lifecycle, while the test suite provides executable end-to-end examples.

## Testing and verification

```bash
uv run pytest                              # full suite: 7,553 tests collected
uv run ruff check .                        # lint
uv run ruff format --check .               # formatting check
uv run mypy kalhas tests                   # strict type check
PYTHONPATH= uv run python scripts/export_schemas.py --check   # schema sync
PYTHONPATH= uv run python scripts/export_model_pack_artifacts.py --check   # model pack sync
PYTHONPATH= uv run python scripts/verify_dataset_bundles.py --check   # dataset bundle check
```

Latest full-suite gate: **7,553 tests collected; exit code 0** (2026-11-01).
`make check` runs the same gates where GNU make is available.

## Release status

Published milestones on `main`:

## Phase 26 — published

Empirical campaign outcome distributions: implementation-complete and
gate-verified, committed, and published at
`886f398c288971d612fa57bd1d1e731113a69f72`.

## Phase 27 — published

Evidence-based campaign decision support: implementation-complete and
gate-verified, committed, and published at
`a905d2af6b155a0f2568037e2b0f410b20be8d91`, followed by the Gate 27.1
truthful-baseline closure published at
`777a4472ef0d1edc6d30ce61a05851302b981027` (5,480 tests, 0 failed,
0 skipped).

## Phase 28 — complete and published

Adaptive deterministic runtime `4.0.0`: implementation-complete,
gate-verified, committed, and published at
`f001d5f027cf21e8964eac72f122730e98ebdd3d`. It adds five v1 contracts
(indexes 50–54), five synchronized schema artifacts, three read-only adaptive
API paths, causal observation/decision/switch evidence, and the unpatched
exact-five-plus-adaptive acceptance proof (24 focused tests). The publication
baseline passed 6,850 tests with 0 failures, 0 errors, and 0 skipped.

## Phase 29 — complete and published

Phase 29 is implementation-complete, gate-verified at checkpoint CP29-B,
committed, and published at `b3b19719bc9a7557800584a0d434bca75d7b24a9`. Its
foundation was published at `1e15d14cac1594c1d74d724ce7f1b3cef6ad2609`: six
public v1 contracts (indexes 55–60, 61 total), a pure fail-closed mechanism
dispatcher/Runtime-4 bridge, and the synthetic `KALHAS-PAN` v0.1 reference pack.
The completion work on top of it (slices H29-S07 through H29-S09) adds:

- **Conformance fixture.** `kalhas-conformance-stockflow` 0.1.0 is a tiny
  synthetic, non-health, integer stock-flow fixture under
  `kalhas/domain_packs/conformance_stockflow/`. It is labeled
  `conformance_only`; it is never a product pack, never a portfolio entry, and
  never a substitute for KALHAS-MARITIME-TRADE.
- **Shared-boundary proof.** PAN and the fixture traverse the same generic
  dispatcher and Runtime-4 bridge under one identical authority chain. The
  proof covers exact identities, one invocation per call, deterministic
  evidence, cross-pack fail-closed cases (including a hybrid pack), and
  cross-tenant rejection. There is zero domain-specific kernel change: no
  module under `kalhas/` outside `kalhas/domain_packs/` names either pack.
- **Assurance and catalogue artifacts.** `scripts/export_model_pack_artifacts.py`
  deterministically generates three checked-in artifacts under `model_packs/v1/`
  (two assurance profiles and a 13-entry catalogue), and `--check` verifies
  them like `scripts/export_schemas.py --check`. No runtime surface loads them.
- **Evidence-derived maturity.** PAN is `experimental`, derived only from
  `synthetic_conformance` and `deterministic_execution` evidence; it has no
  benchmark evidence, no external review, and no empirical adequacy claim. The
  fixture is `conformance_only`. The other 12 entries are `catalogued`:
  roadmap candidates only, with no implemented capability. Their list order is
  not a delivery order, and only PAN (Phases 29–35) and MARITIME-TRADE
  (34A–35) have a planned wave; the rest are `post-35`.

See [`docs/model-packs/README.md`](docs/model-packs/README.md) for the catalogue.

## Documentation

| Document | Contents |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Durable repository rules and gates |
| [`docs/architecture/README.md`](docs/architecture/README.md) | Layer map and dependency rules |
| [`docs/architecture/contracts-and-lifecycle.md`](docs/architecture/contracts-and-lifecycle.md) | Contract versions, lifecycle, and hash discipline |
| [`docs/decisions/`](docs/decisions/) | ADR 001–006 (integration boundaries, domain packs, immutable world contracts, adaptive runtime, Model Pack mechanism/assurance, offline dataset intake) |
| [`docs/model-packs/README.md`](docs/model-packs/README.md) | Model Pack maturity levels, the 13-entry catalogue, and the regeneration workflow |
| [`CHANGELOG.md`](CHANGELOG.md) | Release and checkpoint timeline |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Workflow, gates, and acceptance rules |
| [`SECURITY.md`](SECURITY.md) | Scope, reporting, and supported boundaries |

## Known limitations and non-goals

- **Local, in-memory kernel.** No database, no persistence beyond the process,
  no clustering, and no multi-tenancy beyond tenant-scoped identifiers.
- **No live actions.** The running application performs no autonomous live
  action: no network calls, no provider calls, no real-world effects.
- **Determinism is not validity.** Deterministic replay and repository
  acceptance are not scientific validity, not calibration, not certainty, not
  certification, and not a guarantee of any outcome; replay does not establish
  real-world causality; no output is a real-world recommendation. The
  exact-five campaigns are deterministic proofs over synthetic,
  domain-neutral fixture worlds.
- **Colony UI is synthetic.** The bundled observability UI renders mock
  activity and is intentionally separate from the verified evidence pipeline.
- **Executable packs are explicit and local.** The generic mechanism boundary
  accepts an explicitly supplied, validated `DomainPack`; there is no dynamic
  discovery, plugin loading, provider call, or pack-specific kernel import.
- **KALHAS-PAN is a synthetic executable reference.** It is deterministic
  architecture/mechanism evidence, not an epidemiological forecast. Its
  maturity is `experimental` — deterministic execution and synthetic
  conformance evidence only, no benchmark evidence, no empirical adequacy
  claim; it has no real patient data, empirical calibration, external
  scientific review, automatic API registration, or authority over a public
  decision.
- **Pack results stop at the runtime boundary.** Mechanism step results are
  not yet consumed by campaign outcomes, objective evaluations, or decision
  briefs, so the pack-to-runtime-to-brief path is proven only up to the runtime
  boundary. The pack-to-brief evidence path is open work for a later, separately
  authorized slice and is not claimed as done.
- **Catalogue entries are not capabilities.** A `catalogued` entry is a roadmap
  candidate with no implemented capability, no pack, and no planned delivery
  order.
- **No license yet.** No license has been selected; that is a separate
  explicit decision. All rights are reserved by the repository owner until a
  license is added.

## Contributing and security

Contributions follow the repository's gate discipline — see
[`CONTRIBUTING.md`](CONTRIBUTING.md). Every behavioral change ships with
tests, and `pytest`, `ruff`, and `mypy` must pass before any change is
considered. Security expectations, supported scope, and responsible-disclosure
guidance are in [`SECURITY.md`](SECURITY.md). Pull requests and issues use the
templates under [`.github/`](.github/).
