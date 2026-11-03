# ADR 010: Declared-missing rows in benchmark task derivation

- Status: Accepted
- Date: 2026-11-03
- Deciders: KALHAS foundation

## Context

ADR-009 D30-02-1 says a forecast task exists only if the row at the target time exists: "a presence check, never a
value check". D30-02-2 says evaluability depends on "row presence only". Neither decision says what a row is when its
value column holds a declared missing token.

The H30-S03A task engine answers that question implicitly. `_input_rows` skips every row whose value cell is a declared
missing token of the curated value column, before task derivation and before the information-set view. The synthetic
fixture and its tests pin this behaviour. Read literally, comparing a cell with a token can look like the value check
that ADR-009 excludes. H30-S03B was stopped on this point before any code was written, and the rule must be recorded
before forecasts and scores depend on it.

Two facts bound the decision:
- **ADR-007 D30-01e-6** already separates missingness from outcomes: "Only schema, labels and missingness may inform"
  curation plans for real bundles, which are authored without inspecting outcome values.
- **The locked ECDC bundle is unaffected.** All four curated files of `ecdc-covid19-hospital-icu-by-indicator` `1.0.0`
  declare empty `missing_tokens` on every column, so the rule changes no ECDC task, view, count or hash.

This ADR records a definition only. At the time of writing, no forecast set, score report or real benchmark protocol
exists, and this ADR must not be read as claiming any of them. ADR-009 and every frozen v1 contract remain fully in
force, and no code changes because of this ADR. This ADR supersedes nothing.

## Decision

### D30-02M-1 — What "row presence" means

For ADR-009, a row of a benchmark target is **present** if and only if its value cell is not one of the declared
`missing_tokens` of that target's value column in the curated manifest.

A row that is not present is treated exactly like a row that is absent from the file:
- It cannot be an origin or a target, so it creates no task.
- It does not count towards `min_history_points`.
- It does not appear in the information-set view, and no producer ever receives it.
- It takes part in no `duplicate_series_time` check.

Split membership is unchanged: ADR-008 still labels and counts every curated row, including these.

### D30-02M-2 — Why this is value-blind

The test is a comparison with a token declared in a manifest before any benchmark exists. It reveals only whether an
observation exists, never its magnitude. It carries the same information as the row presence that ADR-009 already uses
for targets. "Never a value check" therefore keeps its meaning: no rule may depend on an observed numeric value.

### D30-02M-3 — Rejected alternative

Treating such rows as present would create tasks whose target has no observation, which cannot be scored. It would also
put rows without a value into history and into baseline difference sets. Each of those would need a further imputation
or exclusion rule, and ADR-007 excludes imputation from curation. The alternative is rejected.

### D30-02M-4 — Disclosure duty for future protocols

Excluding declared-missing rows conditions evaluation on an observation existing. If missingness depends on the outcome,
this is a selection effect, of the same class as the date gaps recorded in ADR-009.

Any future `BenchmarkProtocol` whose target value column declares a non-empty `missing_tokens` must disclose this in its
`preregistration_note`, and every report over it must list it in its limitations. The current contracts cannot enforce
this duty, so the reviewer of each real protocol lock checks it.

## Consequences

- **H30-S03A** behaviour and tests stand unchanged.
- **H30-S03B** proceeds on this definition, with synthetic tests that pin it through forecasts and scoring.
- **H30-D04** needs no disclosure for the ECDC bundle, because its value columns declare no missing tokens.
- **Numbering.** The PAN authoring decision that earlier planning called ADR-010 becomes ADR-011.
