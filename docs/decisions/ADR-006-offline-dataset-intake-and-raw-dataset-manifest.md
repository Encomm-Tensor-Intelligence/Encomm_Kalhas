# ADR 006: Offline dataset intake and the raw-dataset manifest

- Status: Accepted
- Date: 2026-11-02
- Deciders: KALHAS foundation

## Context

Phase 30 (strategic handoff §12) separates computational correctness from empirical adequacy. It evaluates the exact PAN
release against predeclared benchmarks built from real, legally usable, versioned data.

Decision D30-01 ("dataset license class, raw-to-curated lineage, time/unit/missing/revision rules, and locked holdout")
requires external evidence plus an ADR before implementation. The external evidence is the `R30-D01` desk-research
register of 2026-11-02, which the reviewer re-checked against the publishers' own pages:
- **ECDC hospital/ICU archive:** permits attributed commercial and non-commercial reuse of database data, and requires
  that modifications be disclosed.
- **Eurostat:** permits attributed commercial reuse, except for data on countries outside the EU, EFTA and the
  candidate countries.
- **WHO fluID:** the linked terms restrict transformation and commercial promotion.
- **EODY:** no applicable reuse licence could be verified.

This ADR records the D30-01 architecture. It does not implement anything. At the time of writing:
- no dataset contract, verifier, dataset bundle, split, benchmark or score exists in the repository;
- no real dataset has been imported.

This ADR must not be read as claiming any of them. D30-02 (fitting/baseline rules and evidence-update branching) and
D30-03 (external research intake) are decided separately, before the slices that need them. So is the
mechanism-trajectory evidence path, entry-audit finding F30-02, planned as ADR-007.

ADR-002 (domain-neutral kernel, no live effects), ADR-005 (DomainPack mechanism and Model Pack assurance) and every
frozen v1 contract remain fully in force. This ADR supersedes nothing.

## Decision

### D30-01a — Offline, immutable, local bundles only

- **Acquisition stays outside KALHAS.** It is a human-governed step outside the application. The following contain no
  downloader, URL fetch, HTTP client, provider adapter or scheduler:
  - `kalhas/` and `tests/`
  - CI and replay

  The application and the test suite read only local bytes.
- **Raw bytes never change.** After intake they are never modified, re-encoded or normalized. Any changed byte is a new
  vintage with a new manifest; nothing is overwritten.
- **Location.** Bundles live at `datasets/v1/raw/<dataset_id>/<vintage>/`, with a `manifest.json` beside the data files.
  Each raw bundle may be at most 25 MiB in total. Larger data is out of scope until a storage decision (Phase 32A).
- **Personal data.** Only aggregate data is admissible. The manifest can represent nothing other than
  `data_subject_level = "aggregate"`, and person-level records are never imported.

### D30-01b — License classes and admissibility

Exactly these license classes are admissible for intake:
- `public_domain` — no reuse conditions.
- `attribution_commercial` — reuse for commercial and non-commercial purposes, with a required attribution statement.
  Examples: CC BY 4.0, the ECDC database terms, the Eurostat terms within their permitted geography.

Non-commercial-only, restricted, permission-required and unknown terms are **not admissible**. The manifest cannot
represent them, and such sources stay in the research register only:
- WHO fluID is excluded.
- EODY is blocked unless written permission is obtained.

Each manifest records the following, all as declared data and never as executable configuration:
- the exact terms locator and the date the terms were read
- the license identifier and the attribution statement
- whether modifications must be disclosed
- any scope restrictions (e.g. Eurostat's geographic exception)

Admissibility is re-checked at every intake. An earlier intake never vouches for a later one.

### D30-01c — Raw-dataset manifest identity

The frozen public artifact name for H30-S01 is **`RawDatasetManifest`**. It is a versioned v1 contract appended at the
next registry index. Nested helper records are not registered and get no standalone schema. The manifest binds:
- **Identity:**
  - a stable lowercase `dataset_id`
  - a `vintage` (the UTC import date `YYYY-MM-DD`, with an optional `.N` suffix for further imports on the same day)
  - `retrieved_at`, whose UTC date equals the vintage date
  - the tenant
- **Source:** publisher, title, an opaque source locator that is recorded and never dereferenced, and an optional
  publisher release identifier.
- **License:** see D30-01b.
- **Files:** an ordered, unique list of relative POSIX paths. Each file records its byte size, SHA-256 and a declared
  media type, limited to CSV, JSON and XML text.
- **Bundle hash:** SHA-256 over the canonical JSON of the ordered file records.
- **Declarations, never inferred:**
  - per-file columns, with value type, unit and missing-value tokens
  - the time basis: calendar, granularity, time columns, and whether dates are observation, reporting or
    reference-period dates
  - the geography basis: scheme and geography columns
  - the publisher's revision policy: `closed_series`, `revised_in_place`, `versioned_releases` or `unknown`. An
    explicit `unknown` is allowed and is a retained limitation.
- **Self-covering hash:** a `content_hash` computed by the repository's self-covering rule, plus a fixed `declared_at`.

### D30-01d — Checksum verification

Bundle verification is a pure function over a manifest and a mapping of relative paths to bytes. It fails closed if:
- a declared file is missing, or an undeclared file is present
- any size, SHA-256, bundle hash or manifest content hash differs
- any declaration is incomplete

It performs no filesystem, network, clock or randomness access. A thin script may read a bundle from disk only in the
first real-data intake slice, never in `kalhas/`.

### D30-01e — Vintages, lineage and holdout lock

These principles are implemented by H30-S02A/S02B:
- **Lineage.** Curated data is derived only by deterministic, versioned transformations from exact raw manifests. The
  lineage binds both the input and the output hashes.
- **Split lock.** Split membership is defined by preregistered rules and hash-bound **before** any policy or claim is
  evaluated. Changing a locked split creates a new split identity and invalidates the evaluations that depend on it.
  Retrospective split repair is prohibited.
- **External sealed references.** References held by independent providers are bound by **hash commitment only**:
  KALHAS records the provider identity, the commitment date and the SHA-256 of the sealed artifact. The content is
  imported only at reveal and must match the commitment.
- **Evidence binding.** Any later `benchmark` evidence binds the exact raw and curated manifest hashes, the vintage, the
  geography, the horizon and the claim. It disappears rather than transfers when that binding is absent.

### D30-01f — First intended sources (non-binding, each needs its own intake slice)

1. The ECDC COVID-19 hospital/ICU admission and occupancy archive: `attribution_commercial`, ECDC attribution statement,
   `closed_series` (updates ceased with week 47 of 2023).
2. Eurostat hospital beds (national and NUTS 2): `attribution_commercial`, restricted to EU/EFTA/candidate geographies,
   `revised_in_place`.

Both are reference and replay inputs for PAN only. Nothing in this ADR makes PAN `benchmarked`.

## Consequences

- H30-S01 implements the following, with synthetic aggregate fixtures only:
  - `RawDatasetManifest`
  - its unregistered helper records
  - the pure verifier
  - an ADR-006 boundary test
- **Registry and documentation counts.** The public registry grows by exactly one contract. The registry-compatibility
  suite remains the single owner of the exact count. Current-state documentation counts are updated in the same slice.
- **No Model Pack change.** Model Pack artifacts and the PAN maturity are unchanged; no evidence module changes.
- **Later intake slices.** Real-data intake slices add committed bundles under `datasets/v1/raw/`. Each one re-verifies
  its license, records the attribution and states every modification.
