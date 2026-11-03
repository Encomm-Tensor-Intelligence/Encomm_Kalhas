# ADR 009: Benchmark protocol, forecast producers, scoring and the mechanism-trajectory path

- Status: Accepted
- Date: 2026-11-03
- Deciders: KALHAS foundation

## Context

Phase 30 must connect this chain of artifacts:
- an exact Model Pack, mechanism and configuration, with a bounded claim
- raw → curated → split
- a locked benchmark protocol with pinned baselines
- forecasts → scores → verdict

ADR-006 to ADR-008 built the first three links. The first locked split exists:
`ecdc-covid19-hospital-icu-primary` `1.0.0`, over curated bundle `ecdc-covid19-hospital-icu-by-indicator` `1.0.0`.

Two decisions are still open:
- **D30-02** — deterministic fitting and baseline rules, and evidence-update branching. It is required before H30-S03.
- **F30-02** — mechanism results reach no evidence path. `domain_mechanism_runtime` is imported by nothing in
  `kalhas/`, and the Runtime-4 bridge executes one verified pack step. ADR-008 reserved this ADR for that path.

Facts about the ECDC data constrain the design:
- **Four files.** Daily hospital and ICU occupancy are counts of patients. Weekly hospital and ICU admissions are rates
  per 100 000 population. Every value is decimal text, with no declared missing tokens.
- **Gaps.** Many daily series report irregularly: there are 1 153 date gaps in hospital occupancy and 1 761 in ICU
  occupancy. Some countries effectively report weekly.
- **Changing sources.** The `source` column changes within some series, for example from a national website to a TESSy
  feed.
- **Heterogeneous reporting.** ECDC's variable dictionary states that hospital and ICU admission criteria and reporting
  policies "differ between countries and over time". It does not state whether hospital occupancy includes ICU
  patients.
- **One final vintage.** The bundle is a single 2026-11-02 vintage. Real-time reporting delays and revisions are not
  represented.

This ADR records architecture only. At the time of writing, no benchmark protocol, task engine, forecast, baseline,
score, fitter or mechanism forecast exists, and this ADR must not be read as claiming any of them. ADR-002, ADR-004,
ADR-005, ADR-006, ADR-007, ADR-008 and every frozen v1 contract remain fully in force. Runtime `4.0.0` contracts are
not changed. This ADR supersedes nothing.

## Decision

### D30-02-1 — Forecast tasks and the information set

- **Benchmark target.** A target is one curated file of the locked split, with three declared columns:
  - a value column of type `decimal` or `integer`
  - a series column, which must be a geography-basis column
  - a time column, which must be a time-basis column of type `date` or `iso_week`
- **Forecast task.** A task is the tuple (target path, series value, origin, horizon `h`):
  - The origin is a time at which that series has a row.
  - The target time is the origin plus `h` native steps: days for `date`, ISO weeks for `iso_week`.
  - Horizons are declared per target as a strictly increasing tuple of positive integers.
  - A task exists only if the row at the target time exists. This is a presence check, never a value check.
- **Task partition.** A task's partition is the split label of its target row.
- **Information set.** For a task in partition P, the information set is the rows of every target file of the
  protocol whose time is ≤ the origin and whose label is in allowed(P):

| Partition P | allowed(P) |
| --- | --- |
| `development` | `development` |
| `validation` | `development`, `validation` |
| `holdout` | all three; only under H30-S06 |

  A task is admissible only if its own origin row is in allowed(P).
- **Comparing times across files.** Daily and weekly files are compared through one rule: an ISO week stands for its
  last day, the Sunday. A weekly row is therefore available at a daily origin only after its week has ended. This rule
  is conservative and cannot leak data forward.
- **Producers see only the view.** Producers never receive curated files. The task engine hands each producer only the
  information-set view of each task. `holdout` tasks and views are refused with `SealedPartitionError` until H30-S06
  introduces a recorded unseal authority.

### D30-02-2 — Evaluability and minimum evidence

These rules are value-blind and preregistered. They depend on row presence only.
- **History rule.** Each target declares `history_window`, a number of native steps, and `min_history_points`.
  - A task is evaluable only if it is admissible and the series has at least `min_history_points` rows in the
    information set with origin − `history_window` < time ≤ origin.
  - Non-evaluable tasks are counted by reason. They are never scored and never dropped silently.
- **Minimum evidence.** Each target declares `minimum_evaluable_tasks`. When a (target, horizon) cell has fewer
  evaluable tasks, its verdict is `inconclusive`. A truthful `inconclusive` is a successful terminal result.

### D30-02-3 — `BenchmarkProtocol` and its lock

The frozen public artifact name for H30-S03A is **`BenchmarkProtocol`**. It is a versioned v1 contract appended at the
next registry index. Nested helper records are not registered and get no standalone schema. It binds:
- **Identity:** `protocol_id`, `protocol_version` (`MAJOR.MINOR.PATCH`) and identifier
  `benchmark-protocol-<id>-<version>`; the tenant, which must equal the split's tenant.
- **References:**
  - the split: identifier and `content_hash`
  - the curated bundle: identifier, `content_hash` and `bundle_hash`
- **Targets,** sorted by path. Each target carries:
  - its columns
  - `horizons`, `history_window`, `min_history_points` and `minimum_evaluable_tasks`
  - `non_negative`, a declared domain fact used for baseline truncation
- **Quantile levels:** exactly `0.025`, `0.1`, `0.25`, `0.5`, `0.75`, `0.9`, `0.975`. This is the median plus the 50 %,
  80 % and 95 % central intervals.
- **Scoring:** rule id `kalhas-wis-k3-v1`.
- **Comparison:** the reference baseline (id and version), and `relative_wis_pass_below`, a decimal text threshold.
- **A non-empty `preregistration_note`.** It must state that no outcome values were inspected to choose the protocol.
- **`locked_at`,** which must not precede the split's `locked_at`.
- **A self-covering `content_hash`,** plus exact-JSON `metadata`.

The `content_hash` is the lock, as for splits (ADR-008 D30-02B-2):
- Any change creates a new `protocol_version` in a new directory. Nothing bound to an earlier version changes.
- Storage is `benchmarks/v1/protocols/<protocol_id>/<protocol_version>/manifest.json`.
- Verification is pure:
  1. Verify the split, through the ADR-008 verifier and therefore the whole curated and raw chain.
  2. Check every reference and target column against the curated declarations.
  3. Recompute the content hash.

### D30-02-4 — Forecasts: `ForecastSet`

- **Producer-neutral.** A forecast is a set of predictive quantiles at the protocol's levels, whoever produced it.
- **Values.** Each value is finite decimal text: an optional `-`, digits and an optional fraction of at most 6 digits.
  Values must be non-decreasing in level.
- **Point forecasts.** A point forecast is written with all seven quantiles equal. Under D30-02-5 its score is exactly
  the absolute error.
- **The artifact.** The frozen public artifact name is **`ForecastSet`**. It binds:
  - the protocol: identifier and `content_hash`
  - one partition: `development` or `validation`; `holdout` only under H30-S06
  - the producer: kind `baseline` or `model_pack_mechanism`, id, version and `configuration_hash`
  - a canonical CSV member file `forecasts.csv`, by SHA-256 and byte size
  - a self-covering `content_hash`
- **The CSV.** It has one row per evaluable task of that partition. It is ordered by (path, series, origin, horizon)
  and is UTF-8, LF and minimally quoted, like ADR-007 curated output.
- **Completeness.** The verifier recomputes the evaluable task set from the protocol and split, and requires exact
  equality. A missing, extra or duplicated task fails closed.

### D30-02-5 — Scoring rule `kalhas-wis-k3-v1` and `BenchmarkScoreReport`

- **Scored quantities.** For each task, from median `m` and the central intervals with α ∈ {0.05, 0.2, 0.5}:
  - the weighted interval score of Bracher et al. (2021), with K = 3, w₀ = 1/2, w_k = α_k/2 and normalisation
    1/(K + 1/2). Each interval score is
    IS_α = (u − l) + (2/α)(l − y)·1(y < l) + (2/α)(y − u)·1(y > u).
  - the absolute error of the median
  - inclusion in the 50 % and 95 % central intervals, with closed bounds
- **Exact arithmetic.** Arithmetic is exact over rationals parsed from decimal text. Binary floating point never
  touches an authoritative value.
- **Rounding.** Reported aggregates are rounded once, half-even, to 6 fractional digits. Verdicts compare exact
  values before rounding.
- **Aggregates,** per (target, horizon) and per producer:
  - the evaluable count and the non-evaluable counts by reason
  - mean WIS and mean absolute error
  - 50 % and 95 % coverage
- **Relative WIS** is Σ WIS(candidate) / Σ WIS(reference), over the identical evaluable task set.
- **Verdict** per (target, horizon):

| Verdict | Condition |
| --- | --- |
| `inconclusive` | fewer evaluable tasks than the minimum, or a reference WIS sum of zero |
| `pass` | relative WIS < `relative_wis_pass_below` |
| `fail` | otherwise |

- **What `pass` means.** It means only "beats the pinned reference baseline on this preregistered metric, for this
  binding". It is not external validity, a causal claim or a maturity label.
- **The artifact.** The frozen public artifact name is **`BenchmarkScoreReport`**. It binds:
  - the protocol
  - the partition
  - the candidate and reference `ForecastSet` identifiers and content hashes; the reference producer must equal the
    protocol's pinned reference baseline
  - the aggregates and verdicts
  - a self-covering `content_hash`

  It is verified by complete re-execution from the curated files.

### D30-02-6 — Reference baselines

Baselines are pure offline utilities over the information-set view. They are not runtime or provider adapters and add
no integration surface.
- **`kalhas-persistence-point-v1`.** All quantiles equal the value at the origin.
- **`kalhas-persistence-quantile-v1`.**
  - The median equals the value at the origin, `y_t`.
  - **The difference multiset.** For horizon `h`, form M from every exactly `h`-step difference d = y(s) − y(s − h)
    where both rows lie in the information set within the history window. M holds every d and every −d.
  - **Quantiles.** Each other quantile is y_t + Q_p(M), where Q_p is the Hyndman–Fan type 7 empirical quantile,
    computed exactly. Symmetry makes Q_0.5(M) = 0.
  - **Truncation.** When the target is `non_negative`, quantiles are truncated below at 0. This preserves their order.
  - **Fallback.** If M is empty, every quantile equals y_t. The fallback is deterministic and its count is reported.
  - **Provenance.** It is inspired by the COVID-19 Forecast Hub baselines, which run a random walk with symmetrised
    empirical differences. It uses direct `h`-step differences instead of simulated iteration, so it is exactly
    deterministic. It is not, and must not be described as, the Hub implementation.
- **Configuration hash.** Each baseline's `configuration_hash` is SHA-256 of the canonical JSON of its configuration.
  For both v1 baselines the configuration is `{}`, because everything else comes from the locked protocol.
- **Optional differential baselines.** A Covasim/Starsim or exported GLEAM result may appear later only as
  non-authoritative local evidence, under its own ADR. It is never a runtime or network dependency.

### D30-02-7 — The mechanism-trajectory path (F30-02): Option A

The mechanism-trajectory path follows Option A of the entry audit: a pure offline evaluation utility iterates the
existing verified dispatcher over immutable inputs. Its inputs are:
- an authored initial state
- the release's frozen configuration
- a declared action schedule
- a declared observation operator, which maps states and flows to the protocol's target quantities

The utility emits a `ForecastSet` of producer kind `model_pack_mechanism`.
- **Point or ensemble.** A deterministic mechanism yields point forecasts. Quantiles come only from an immutable
  parameter ensemble (D30-02-8), through the same exact type 7 rule.
- **Option B is rejected for Phase 30.** Option B was an additive mechanism-driven runtime version. It would create a
  second outcome authority, and it would extend runtime semantics before any evidence exists.
- **Unchanged.** Runtime `4.0.0`, the historical runtimes and the outcome and brief contracts stay as they are.
- **PAN assumptions, recorded later.** For PAN, the observation operator and the initial-state authoring rule are
  declared assumptions, recorded in their own authoring artifact before H30-S05. They are never inferred silently.
  - **Hospital occupancy.** Whether hospital occupancy maps to H or to H + C is an assumption, because the ECDC
    dictionary does not say.
  - **Admission rates.** Weekly admission rates need a population denominator. That requires a separate, legally
    usable population intake before PAN can be scored on the weekly files.

### D30-02-8 — Fitting and calibration rules

- **Deterministic fitter.** A fitter is a pure deterministic utility with:
  - a declared algorithm id and version
  - a closed, finite candidate grid, declared before fitting and enumerated in canonical order
  - an objective that is the protocol's scoring rule over `development` tasks only
  - ties broken by the canonical JSON order of the candidates
  - no RNG and no floating-point optimiser in v1
- **Calibration record.** The output is an immutable calibration record listing every candidate and its score. Every
  candidate within a declared tolerance of the best is retained as the parameter ensemble. A single best fit is never
  silently treated as truth.
- **Untrusted authoring input.** A fitted configuration is untrusted authoring input.
  - It is never evaluated under an existing release identity, because PAN configuration is frozen per release.
  - It requires a new Model Pack release identity with its own assurance. Existing releases are never mutated.
- **Partition use.**
  - `validation` may be used at most once per preregistered candidate set, and only to select among candidates.
  - `holdout` is never used for fitting or selection.
  - In-sample results are labelled calibration, never validation.
- **When.** Fitting is not implemented in H30-S03 or H30-S04. It arrives with the PAN authoring work before H30-S05,
  under its own slice.

### D30-02-9 — Evidence-update branching (principle; contract in H30-S11)

- **A new vintage starts a new chain.** A new data vintage creates a new raw bundle, then a new curated version, then
  a new split version, then a new protocol version.
- **Links.** Each new artifact cites its predecessor by identifier and content hash.
- **Nothing is edited.** Earlier forecasts, scores, verdicts and claims are never edited.
- **The contract** comes in H30-S11.

### D30-02-10 — Claim boundary for the ECDC benchmark

Every report on this bundle must carry these limitations:
- The evaluation is retrospective against one final vintage. Reporting delays and revisions are absent.
- Admission criteria and reporting differ by country and over time.
- Sources change within some series.
- Daily series have gaps.
- A `benchmarked` label binds only the exact pack and configuration, data vintage, geography, horizon, metric and claim.
  It disappears rather than transfers when that binding is absent.

## Consequences

- **H30-S03A** implements, with synthetic fixtures only:
  - `BenchmarkProtocol`
  - the pure task engine: task derivation, evaluability and the information-set view, which refuses `holdout`
  - the protocol verifier
  - `scripts/verify_dataset_bundles.py` coverage for `benchmarks/v1/protocols/`
- **H30-S03B** implements `ForecastSet`, `BenchmarkScoreReport`, exact `kalhas-wis-k3-v1` scoring and their verifiers,
  with synthetic fixtures only.
- **H30-S04** implements the two reference baselines as pure utilities.
- **H30-D04** preregisters and locks the ECDC protocol. The reviewer fixes its parameters value-blind.
- **H30-D05** produces the first real baseline forecast sets and score report, on `development` and `validation` only.
- **A later ADR,** before H30-S05, covers PAN initial-state and observation-operator authoring, plus the population
  intake.
- **No Model Pack change.** Model Pack artifacts, PAN maturity and every evidence module are unchanged.
- **Reference:** Bracher J, Ray EL, Gneiting T, Reich NG (2021), *Evaluating epidemic forecasts in an interval format*,
  PLOS Computational Biology 17(2): e1008618.
