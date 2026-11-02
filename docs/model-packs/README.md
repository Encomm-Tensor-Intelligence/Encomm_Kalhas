# Model Pack catalogue

A **Model Pack** is product vocabulary for one exact, versioned `DomainPack`
release plus its bound assurance artifacts (ADR-005, D29-03). It is not a
component, protocol, registry, runtime, provider adapter, or plugin system, and
it never adds a fourth architectural role. The kernel stays domain-neutral and
consumes a pack only through the `DomainPack` protocol.

The artifacts described here are generated data under `model_packs/v1/`. No
runtime surface loads them, and a catalogue entry creates no capability.

## Maturity levels

Maturity is evidence-derived and uses exactly these values and meanings:

- `catalogued` — roadmap candidate only; no implemented capability.
- `conformance_only` — synthetic architecture fixture; never a product pack.
- `experimental` — deterministic executable mechanism and conformance evidence
  only; no empirical adequacy claim.
- `benchmarked` — Phase 30 evidence exists for the exact version, data vintage,
  geography, horizon, and claim.
- `externally_reviewed` — Phase 33 domain/statistical review closed for
  explicitly bounded claims.
- `partner_evaluation_ready` — Phase 35 packaging, replay, security, and
  governance evidence exists; still not production approval.

Maturity and claims never transfer across pack versions, configurations,
mechanisms, implementations, dependencies, datasets, vintages, geographies,
horizons, platforms, or domains.

## Catalogue

The 13 entries below follow the order of `model_packs/v1/catalogue.json`. That
order is not a delivery order. Only PAN (Phases 29–35) and MARITIME-TRADE
(34A–35) have a planned wave; every other entry is `post-35`, and their
sequencing is not decided by the catalogue.

| `pack_id` | Title | Roadmap wave | `displayed_maturity` | Summary |
| --- | --- | --- | --- | --- |
| `kalhas-pan` | KALHAS PAN | 29-35 | `experimental` | Public health & biosecurity: outbreak, capacity, stockpile and conditional intervention comparison (synthetic v0.1) |
| `kalhas-maritime-trade` | KALHAS MARITIME-TRADE | 34A-35 | `catalogued` | Ports, chokepoints and strategic supply chains under declared disruption branches |
| `kalhas-quantum-readiness` | KALHAS QUANTUM-READINESS | post-35 | `catalogued` | Post-quantum cryptography transition planning; no cryptographic implementation, scanning, certification or quantum hardware |
| `kalhas-climate-civil` | KALHAS CLIMATE-CIVIL | post-35 | `catalogued` | Extreme-weather impacts and civil protection from pinned offline hazard ensembles; never replaces meteorological authorities |
| `kalhas-energy-sec` | KALHAS ENERGY-SEC | post-35 | `catalogued` | Energy security: supply, storage, disruption and contingency scenarios |
| `kalhas-food-water` | KALHAS FOOD-WATER | post-35 | `catalogued` | Food and water security: shocks, reserves, allocation and affordability |
| `kalhas-cyber-digital` | KALHAS CYBER-DIGITAL | post-35 | `catalogued` | Defensive digital-service resilience only; no exploit generation or live effects |
| `kalhas-critical-resilience` | KALHAS CRITICAL-RESILIENCE | post-35 | `catalogued` | Cross-sector infrastructure cascades and restoration order |
| `kalhas-macro-fiscal` | KALHAS MACRO-FISCAL | post-35 | `catalogued` | Conditional macro-fiscal scenarios; never an economic oracle or financial advice |
| `kalhas-demography-capacity` | KALHAS DEMOGRAPHY-CAPACITY | post-35 | `catalogued` | Aggregate demography and public-service capacity; no individual scoring |
| `kalhas-geo-policy` | KALHAS GEO-POLICY | post-35 | `catalogued` | Declared geopolitical, trade and policy branches; no prediction of elections or persons, no persuasion |
| `kalhas-robotics` | KALHAS ROBOTICS | post-35 | `catalogued` | Simulation-only fleet task allocation under energy, delay and failure constraints |
| `kalhas-neuro-symbolic` | KALHAS NEURO-SYMBOLIC | post-35 | `catalogued` | Evaluation of reasoning and planning with rules and frozen model outputs |

Only `kalhas-pan` is bound to a release profile and an assurance profile. The
other 12 entries are `catalogued`: roadmap candidates with no implemented
capability. The 13 entries are the 11-pack strategic portfolio plus
`kalhas-robotics` and `kalhas-neuro-symbolic`; both were added by owner decision
with the H29-S09A artifacts (declared 2026-10-28), as `catalogued` entries
only, and they change no ADR-005 decision.

## KALHAS-PAN v0.1 (`experimental`)

Evidence (each record pins the SHA-256 of the exact bytes of a test module):

- `deterministic_execution` — `tests/test_pan_domain_pack.py` and
  `tests/test_domain_mechanism_runtime.py`
- `synthetic_conformance` — `tests/test_phase29_shared_boundary_acceptance.py`
  and `tests/test_phase29_boundaries.py`

Supported claims:

1. `deterministic-replay-on-recorded-platform` — identical verified requests
   produce byte-identical results under the recorded platform identity.
2. `declared-invariants-hold-on-synthetic-fixtures` — conservation,
   non-negativity, and capacity invariants hold for the declared synthetic
   fixtures.
3. `generic-seam-without-kernel-change` — PAN executes through the generic
   dispatcher and Runtime-4 bridge with no domain-specific kernel code.

These claims do not cover empirical adequacy, forecasting, calibration, real
data, external review, benchmark evidence (PAN has no benchmark evidence),
packaging, security or governance evidence, or behavior on any platform other
than the recorded one. No retained failures are recorded.

## Conformance fixture

`kalhas-conformance-stockflow` 0.1.0 is a tiny synthetic, non-health, integer
stock-flow fixture under `kalhas/domain_packs/conformance_stockflow/`. Its
assurance profile is `conformance_only`, derived from `synthetic_conformance`
evidence only. It is not a product pack, is not a catalogue entry, and is never
a substitute for KALHAS-MARITIME-TRADE.

## Known limitation

Mechanism step results are not yet consumed by campaign outcomes, objective
evaluations, or decision briefs. The "pack-to-runtime-to-brief" path is proven
only up to the runtime boundary; the pack-to-brief evidence path is open work
for a later, separately authorized slice and is not claimed as done.

## Regeneration workflow

The artifacts are generated, never edited by hand. When an evidence module or a
pack release profile changes:

```bash
uv run python scripts/export_model_pack_artifacts.py          # regenerate
PYTHONPATH= uv run python scripts/export_model_pack_artifacts.py --check
```

Review the diff before accepting it; `--check` (also a CI step) fails while the
checked-in bytes differ from the generated ones.

## Use floor

All packs are decision support only. The public-sector prohibited-use floor and
the prohibited status labels of ADR-005 D29-03 apply to every entry; outputs
remain labeled conditional modeled outcomes with accountable human authority
visible.
