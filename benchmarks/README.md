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
