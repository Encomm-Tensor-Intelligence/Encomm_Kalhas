# Benchmarks

Locked benchmark artifacts. Files here are stored byte-exact and are verified offline by
`scripts/verify_dataset_bundles.py`. Nothing here is edited in place: any change creates a new version in a new directory.

## Protocol: ecdc-covid19-hospital-icu-primary-benchmark 1.0.0

This protocol references split `ecdc-covid19-hospital-icu-primary` version `1.0.0` over curated dataset
`ecdc-covid19-hospital-icu-by-indicator` version `1.0.0`. See `datasets/README.md` for the source, the license and the
required acknowledgement.

The four curated files are the targets. The pinned reference baseline is `kalhas-persistence-quantile-v1` version `1.0.0`,
and a candidate passes a target and horizon only if its relative WIS is below 1.

Preregistration note (verbatim):

Targets, horizons (7, 14, 21 and 28 days; 1, 2, 3 and 4 ISO weeks), history rules (84 days with at least 8 points; 12 weeks with at least 4 points), the minimum of 100 evaluable tasks per target and horizon, the quantile levels, the scoring rule and the reference baseline with its threshold of 1 were fixed by the reviewer without inspecting outcome values. The non_negative declaration follows from the indicators being counts of patients and rates per population, not from inspecting values. Before locking, the reviewer ran the task engine on this split with these same parameters for software verification and sizing only, observing task counts per target, horizon and status for the development and validation partitions, but no values: 61132 evaluable and 1042 insufficient-history tasks in development, 13280 evaluable and 35 insufficient-history tasks in validation, and at least 270 evaluable tasks in every target and horizon cell. No tasks were derived for the holdout partition.

The holdout partition stays sealed until a separately authorized evaluation (H30-S06).

## Claim boundary

Every report on this bundle carries these limitations (ADR-009 D30-02-10):

- The evaluation is retrospective against one final data vintage. Reporting delays and revisions are absent.
- Admission criteria and reporting differ by country and over time.
- Sources change within some series.
- Daily series have gaps.
- A `benchmarked` label binds only the exact pack and configuration, data vintage, geography, horizon, metric and claim. It
  disappears rather than transfers when that binding is absent.

A `pass` means only that a candidate beats the pinned reference baseline on this preregistered metric, for this binding. It
is not external validity, a causal claim or a maturity label.

## First results: reference baselines (development and validation)

Candidate is `kalhas-persistence-point-v1`, reference is `kalhas-persistence-quantile-v1`, under the protocol above. This is a
sanity benchmark between two baselines. It is not a claim about any Model Pack.

| Partition | Tasks per set | Cells | Verdicts | Relative WIS range | Reference 95% coverage range | Fallback tasks |
| --- | --- | --- | --- | --- | --- | --- |
| development | 61132 | 16 | 16 fail | 1.549059 to 1.675262 | 0.740612 to 0.868811 | 751 |
| validation | 13280 | 16 | 16 fail | 1.637843 to 1.825789 | 0.825926 to 0.925558 | 2 |

The `fail` verdicts are largely by construction: a point forecast has zero-width intervals, so its WIS equals its absolute error.
The reference's 95% intervals cover less than their nominal level in every cell, and in development their coverage falls with the
horizon, so the reference is itself under-dispersed on this data. The holdout partition was not evaluated.
