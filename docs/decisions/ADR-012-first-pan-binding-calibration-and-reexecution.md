# ADR 012: First PAN binding, candidate releases, calibration and mechanism re-execution

- Status: Accepted
- Date: 2026-11-06
- Deciders: KALHAS foundation

## Context

ADR-009 D30-02-7 and D30-02-8 fixed the mechanism-trajectory path and the fitting rules. ADR-011 fixed the observation
operators, the initial-state principle, the population source and the order of work. H30-S05A and H30-S05B delivered
`ModelPackAuthoringBinding`, the pure operators, and a dispatcher-based forecast utility with a re-execution verifier, all on
synthetic fixtures.

The first real binding needs further decisions before any implementation starts. This ADR records them.

Facts measured at the time of writing, from task and row counts only. No outcome value was inspected and no holdout task was
derived:
- **Cost.** One dispatcher step took about 2.9 ms on the owner's machine. With trajectories shared per series and day, one
  candidate needs at most 218 645 steps on `development`, about 11 minutes, and 51 058 steps on `validation`, about 2.5 minutes.
- **Occupancy coverage.** With a look-back of 7 days, every evaluable daily task has at least one daily occupancy observation.
  3 212 of 11 001 evaluable weekly `development` tasks and 540 of 2 489 evaluable weekly `validation` tasks have none.
- **Population.** The largest N in the population bundle is 83 456 045.
- **The release.** `PanV01DomainPack` is the exact frozen synthetic `0.1.0` release. Its configuration cannot change, and its
  capacities of 50 and 10 cannot hold national occupancy.
- **CI.** The per-push job has a limit of 45 minutes.

At the time of writing, no real binding, candidate release, initial-state implementation, candidate grid, calibration record,
mechanism forecast on real data or mechanism re-execution job exists, and this ADR must not be read as claiming any of them.
ADR-002, ADR-005, ADR-006, ADR-007, ADR-008, ADR-009, ADR-010, ADR-011 and every frozen v1 contract remain fully in force. PAN
maturity and every Model Pack artifact are unchanged. This ADR supersedes nothing.

## Decision

### D30-05-1 — Three slices

| Slice | Delivers | Real data |
| --- | --- | --- |
| H30-S05C1 | The candidate release factory and the initial-state rule | None. Synthetic fixtures only |
| H30-S05C2 | The first real binding and its candidate grid, locked before any score exists | Declared, not scored |
| H30-S05C3 | `ModelPackCalibrationRecord`, the fitter, the `development` run, its forecast and score artifacts, and the re-execution job | `development` only |

`validation` follows under ADR-009 D30-02-8 in its own slice. `holdout` stays sealed until H30-S06.

### D30-05-2 — Candidate releases

- A candidate configuration runs under its own release identity, built by a pack-owned factory below `kalhas/domain_packs/pan/`.
- The factory reuses `mechanism.py` unchanged, so the implementation hash does not change. Only the configuration, the identity
  and the declared provenance differ.
- `PanV01DomainPack`, its artifacts and its catalogue entry stay byte-identical.
- The candidate identity is `pack_id` `kalhas-pan`, `pack_version` `0.2.<n>`, where n is the candidate's 1-based position in the
  canonical order of its binding's grid, with the binding identity recorded in the profile.
- A candidate release is authoring input. It is not catalogued, has no assurance and no maturity, and supports no claim. Under
  ADR-009 D30-02-8 a retained configuration needs its own assurance in its own slice before it can be catalogued.

### D30-05-3 — Initial-state rule `kalhas-pan-initial-state-v1`

The rule is a pure function of the series, the last day `d` of the origin period, the information-set view and the declared
candidate parameters. It never uses the target of the task, so a series and day have one state and one shared trajectory.

- **Observations.** `O_h` and `O_c` are the latest daily hospital and ICU occupancy values in the view, in the closed range from
  `d` minus 7 days to `d`. Weekly admission rates are not inverted in this version.
- **N.** The denominator for the series and the calendar year of `d`.
- **Occupancy,** by operator variant, with the candidate parameter `icu_share_bps`:

| Observed | Variant `h-only` | Variant `h-and-c` |
| --- | --- | --- |
| Both | H = `O_h`, C = `O_c` | C = `O_c`, H = `O_h` − C |
| Only `O_h` | H = `O_h`, C = `O_h` × share | C = `O_h` × share, H = `O_h` − C |
| Only `O_c` | C = `O_c`, H = `O_c` ÷ share | C = `O_c`, H = `O_c` ÷ share − C |
| Neither | No state | No state |

- **Unobserved compartments,** from candidate parameters:
  - I = H × `infectious_per_hospitalized_bps`
  - E = I × `exposed_per_infectious_bps`
  - R = N × `immune_share_bps`
  - D = 0
  - S is the remainder of N
- **Rounding.** Each product and quotient is rounded half-even to an integer, once, in the order above.
- **No state.** The rule returns no state when neither occupancy is observed, N is missing, `icu_share_bps` is zero where it would
  divide, or any compartment would be negative. The task then takes the fallback of ADR-011 D30-04-4.

### D30-05-4 — Capacity and intervention

- `hospital_capacity` and `icu_capacity` are both 100 000 000, above every N in the population bundle. Capacity therefore does not
  bind, as a declared assumption. No result supports any claim about capacity limits.
- A single capacity value and a single `intervention_intensity_bps` of 0 satisfy ADR-011 D30-04-6 and D30-04-7: both grid
  dimensions exist and each has one value. Transmission is varied through `transmission_bps` only, because intensity and
  transmission cannot be told apart under a constant schedule.

### D30-05-5 — Candidate grid

- The grid is closed and finite, at most 12 candidates per operator variant, declared in the binding before any score exists.
- Every value, varied or fixed, cites a published source or is labelled an assumption. No outcome value is inspected to choose one.
- Candidates are enumerated in the canonical JSON order of their parameters.

### D30-05-6 — Objective, retention and variants

- **Objective.** The unweighted mean, over every (target, horizon) cell of the protocol, of the candidate's relative WIS against the
  protocol's pinned reference on `development`. Lower is better, and arithmetic is exact. A cell with a reference WIS sum of zero, or
  below its minimum of evaluable tasks, is excluded and counted.
- **Retention.** Every candidate with an objective at most 21/20 of the best is retained. If more than 8 qualify, the first 8 by
  objective, then canonical order, form the ensemble. The record states the number left out, so the cap is never silent.
- **Variants.** Each operator variant has its own grid run and its own record, and both are reported. Any choice between them uses
  `development` only, under ADR-011 D30-04-3.
- **Quantity names.** A binding names stocks by state key and flows by emission field. For PAN, `n_3` is `hospital_admissions` and
  `n_5` is `icu_admissions`.

### D30-05-7 — `ModelPackCalibrationRecord`

The frozen public artifact name is **`ModelPackCalibrationRecord`**. It binds:
- the binding and the protocol, by identifier and content hash
- the partition, which can only be `development`
- the algorithm, `kalhas-grid-fitter-v1` version `1.0.0`
- every candidate, with its configuration hash, objective, cell scores, fallback count and retention status
- the number of qualifying candidates left out by the cap
- a self-covering `content_hash`

It arrives in H30-S05C3, and adds one registered contract and one schema.

### D30-05-8 — The dispatcher remains the only path

- ADR-009 D30-02-7 applies unchanged. Every candidate and every member runs through the verified dispatcher, and no fast path
  exists.
- Candidates may run in parallel processes. No output may depend on scheduling.

### D30-05-9 — Mechanism re-execution

- **Per push.** `scripts/verify_dataset_bundles.py --check` stays within the CI limit. For a mechanism forecast set or a calibration
  record it verifies the structure, the lineage, the binding and every hash, and it says plainly that it did not re-execute.
- **Full.** A new flag runs complete byte-identical re-execution of the forecast sets and of every candidate in the records.
- **When.** A separate workflow runs the full check on manual dispatch, and on any push that changes a binding, a forecast set, a
  record, `kalhas/domain_packs/pan/` or the mechanism forecast modules.
- **Scripts may name the pack.** As `scripts/export_model_pack_artifacts.py` already does, the verification script may import the
  concrete pack. Kernel and application modules still may not.
- `mechanism_reexecution_unavailable` from H30-S05B stays in force until H30-S05C3 replaces it.

### D30-05-10 — Claim boundary

- A `development` score is labelled calibration. It is in-sample and is not benchmark evidence, so the PAN statement of no benchmark
  evidence stays true.
- Every score report on a mechanism forecast states its fallback count. A fallback row is a persistence point, not a mechanism result.
- No result supports a claim about any real intervention, capacity limit or immunity level.
- PAN maturity stays `experimental`.

## Consequences

The order of work is H30-S05C1, H30-S05C2, H30-S05C3. The leave-one-pathogen-out contract still waits for a second locked pathogen
bundle. A failing result is a valid result and is retained.

No Model Pack artifact, maturity label or existing contract changes because of this ADR.
