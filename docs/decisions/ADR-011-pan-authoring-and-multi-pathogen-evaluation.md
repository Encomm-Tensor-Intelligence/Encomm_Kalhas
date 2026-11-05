# ADR 011: Pathogen-neutral PAN authoring, observation operators and multi-pathogen evaluation

- Status: Accepted
- Date: 2026-11-05
- Deciders: KALHAS foundation

## Context

ADR-009 D30-02-7 fixed Option A for mechanism forecasts and left the PAN authoring decisions to a later ADR before H30-S05:
the observation operator, the initial state, the action schedule, the population denominator and the fitting grid. This is
that ADR.

The goal of KALHAS-PAN is general. It must serve an epidemic or pandemic that is not COVID-19, and evidence must come from
more than one pathogen. The first real benchmark exists: reference baselines on the ECDC COVID-19 hospital and ICU bundle,
under protocol `ecdc-covid19-hospital-icu-primary-benchmark` `1.0.0`.

Facts that constrain the design:
- **The mechanism.** PAN v0.1 is a daily integer compartment flow over S, E, I, H, C, R, D and N, with the single action
  `intervention_intensity_bps`, nine rate parameters and the capacities `K_h` and `K_c`. Its configuration is frozen per
  release. R is absorbing, so it has no reinfection or waning immunity.
- **The ECDC bundle.** Its dictionary does not say whether hospital occupancy includes ICU patients. Weekly admissions are
  rates per 100 000 population, which needs a population denominator.
- **The R30-D02 research register.** No second dataset is intake-ready. Candidate sources have open rights or observation
  questions, and test positivity does not directly observe hospital demand.

This ADR records decisions only. At the time of writing, no authoring binding, observation operator implementation,
mechanism forecast, population bundle, second pathogen bundle, fitted configuration or multi-pathogen evaluation exists, and
this ADR must not be read as claiming any of them. ADR-002, ADR-005, ADR-006, ADR-007, ADR-008, ADR-009, ADR-010 and every
frozen v1 contract remain fully in force. PAN maturity and every Model Pack artifact are unchanged. This ADR supersedes
nothing.

## Decision

### D30-04-1 — Pathogen-neutral pack, pathogen-specific bindings

- The PAN mechanism and the kernel name no pathogen. Everything specific to a pathogen, dataset or geography lives in an
  immutable authoring binding.
- A binding declares the protocol it serves, its observation operators, initial-state rule, action schedule, candidate grid
  and assumptions. It is hash-bound and is untrusted authoring input.
- The frozen public artifact name is **`ModelPackAuthoringBinding`**. The contract is generic and its payload is pack-owned
  exact JSON. It arrives in H30-S05A.
- A fitted configuration takes a new Model Pack release identity under ADR-009 D30-02-8. Existing releases are never mutated.

### D30-04-2 — Mechanism scope

- PAN v0.1 is declared for human-to-human respiratory-type transmission.
- Vector-borne transmission, sustained zoonotic spillover, and dynamics that depend on reinfection within the forecast horizon
  are outside its scope. They need a new mechanism version or pack, not a new binding.
- Because R is absorbing, every forecast is re-initialised at its own origin. Long simulated runs across several waves are not
  a supported use and support no claim.

### D30-04-3 — Observation operators

The vocabulary version is `1.0.0` and it is closed:

| Operator | Meaning |
| --- | --- |
| `stock_sum` | The sum of declared compartments at the target time |
| `flow_sum` | The sum of a declared flow over the daily steps of the target period |
| `per_100k` | A wrapped operator multiplied by 100 000 and divided by the declared N |

- An ISO week is the seven daily steps from its Monday to its Sunday. Other time bases are declared per binding.
- Arithmetic is exact, and a forecast value is rounded once under ADR-009.

For the ECDC bundle the mapping is:

| Target | Operator |
| --- | --- |
| Daily hospital occupancy | Two declared variants: `stock_sum(H)` and `stock_sum(H, C)` |
| Daily ICU occupancy | `stock_sum(C)` |
| Weekly hospital admissions per 100 000 | `per_100k(flow_sum(n_3))` |
| Weekly ICU admissions per 100 000 | `per_100k(flow_sum(n_5))` |

Both hospital occupancy variants are reported, because the dictionary does not settle the question. Any choice between them
uses `development` tasks only. The holdout partition is never used for that choice.

### D30-04-4 — Initial state

- The initial state of a forecast is a pure function of the information-set view at its origin and of declared binding
  parameters. It never reads a row later than the origin.
- Observed compartments come from the declared inverse of the operator. Unobserved compartments come from declared ratios in
  the candidate grid. S is the remainder of N. All values are integers under a declared rounding rule.
- A task whose initial state cannot be derived still gets its forecast row, as a declared fallback equal to the last observed
  value. Fallbacks are counted in `metadata` and are never dropped.

### D30-04-5 — Population denominators

- N comes from its own raw and curated bundle under ADR-006 and ADR-007, with one declared vintage, and only after the terms
  are confirmed at the source for that intake.
- N is declared per geography and year in the binding. The application never fetches it.

### D30-04-6 — Action schedule

- A binding declares a constant `intervention_intensity_bps` taken from the candidate grid, as an assumption.
- The value is a modelling parameter, not an observed policy. A benchmark under this rule supports no claim about the effect of
  any real intervention.

### D30-04-7 — Fitting

ADR-009 D30-02-8 applies unchanged: a closed finite grid declared in advance, `development` tasks only, no RNG, every candidate
recorded, and the ensemble retained. The grid covers rates, unobserved-state ratios, intensity and capacities. A binding is fitted
per pathogen.

### D30-04-8 — Admission rule for further pathogen datasets

- The target of a PAN benchmark must be a directly observed hospital-based quantity: admissions, occupancy or ICU.
- Test positivity and consultation rates may support a separately labelled proxy exercise. They never count as a PAN hospital
  benchmark.
- Rights are confirmed at the source before intake, under ADR-006.
- A single reporting system that covers several pathogens is preferred, because its observation process is shared. On the R30-D02
  evidence, the CDC NHSN weekly hospital data is the preferred candidate and ECDC ERVISS is the European alternative. Neither is
  admitted by this ADR, and each needs its own intake slice.

### D30-04-9 — Leave-one-pathogen-out evaluation

- The primary generalization test holds out one whole pathogen group, adjusts only on the others, and evaluates on the held-out
  group. The first intended groups are SARS-CoV-2, influenza and RSV.
- Historical episodes of the same pathogen, such as the influenza pandemics of 1918, 1957, 1968 and 2009, may supplement this
  test but never replace it.
- Each run is preregistered before any score is seen. No data later than a task's origin may enter it, from any pathogen.
- Each result is labelled either `within_pathogen` or `transfer`.
- Evidence still does not transfer by default. A `transfer` result binds only its exact pathogens, data, configuration and claim.
- This evaluation needs an additive contract above single protocols, because each `BenchmarkProtocol` binds one split. It arrives
  in its own slice. It cannot run until at least two pathogen bundles are locked.

### D30-04-10 — Claim boundary for a new crisis

- For a pathogen with no benchmark under its own binding, every output is labelled `unbenchmarked`. It reports robustness under
  declared assumptions, and is not a forecast or a validated recommendation.
- A truthful `inconclusive` remains a successful result.
- The human decides.

## Consequences

The order of work is:
1. Population intake for the ECDC geographies, under its own slice.
2. Rights confirmation, then the second pathogen intake.
3. **H30-S05A:** `ModelPackAuthoringBinding` and the pure observation operators, with synthetic fixtures only.
4. **H30-S05B:** the Option A offline trajectory utility, which emits a `ForecastSet` of kind `model_pack_mechanism`, and its
   re-execution verifier.
5. **H30-S05C:** the first PAN binding, candidate grid and calibration record, on `development` tasks only.
6. The leave-one-pathogen-out contract, after the second pathogen bundle is locked.

No Model Pack artifact, maturity label or existing contract changes because of this ADR.
