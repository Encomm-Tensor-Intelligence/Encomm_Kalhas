# ADR 007: Curated dataset lineage and closed transformation plans

- Status: Accepted
- Date: 2026-11-02
- Deciders: KALHAS foundation

## Context

ADR-006 (D30-01) froze offline, immutable raw bundles and the `RawDatasetManifest`. Its D30-01e requires that curated
data be derived only by deterministic, versioned transformations whose lineage binds the input and output hashes.

The first real raw bundle (`ecdc-covid19-hospital-icu`, vintage `2026-11-02`) shows what curation must handle:
- a UTF-8 byte order mark
- string-typed cells
- daily and weekly indicators mixed in one table
- an empty-string missing token in one column

The kernel must stay domain-neutral (ADR-002). Dataset-specific parsing code inside `kalhas/` would violate that.
Arbitrary user code, expressions or callbacks would make lineage unverifiable.

This ADR records the curated-lineage architecture. It implements nothing. At the time of writing:
- no curated dataset, transformation engine or curated manifest exists;
- no split, benchmark or score exists either.

This ADR must not be read as claiming any of them. ADR-002, ADR-005, ADR-006 and every frozen v1 contract remain fully
in force. This ADR supersedes nothing.

The mechanism-trajectory evidence path (entry-audit finding F30-02) is a separate decision, recorded as ADR-008 before
H30-S05.

## Decision

### D30-01e-1 — Closed, declarative transformation plans

A curated dataset is produced only by a **transformation plan**: declarative data interpreted by one generic, pure
KALHAS engine. A plan contains no code, expression, regular expression, callback, import, file path outside its bundle,
or network locator.

A plan has one or more named outputs. Each output is an ordered list of steps from this closed vocabulary, version
`1.0.0`:

| Step | Meaning |
| --- | --- |
| `decode_text` | `encoding` ∈ {`utf-8`, `utf-8-sig`}. Mandatory first step for text input; `utf-8-sig` removes a leading byte order mark. |
| `parse_csv` | Comma delimiter, double-quote quoting, first row is the header. Mandatory second step for CSV input. |
| `select_columns` | An ordered list of existing columns; it also fixes the output column order. |
| `rename_columns` | A mapping from existing names to new, unique names. |
| `filter_rows_in` | Keep rows whose `column` value is in a declared, non-empty, unique value list (exact string match). |
| `cast_columns` | Per-column target type ∈ {`string`, `integer`, `decimal`, `date`, `iso_week`}. Values are validated, never re-rendered: the original text is kept verbatim, and the declared type is what typed sorting and later consumers use. Any value that does not parse fails the whole plan; nothing is coerced or dropped silently. |
| `require_unique_key` | The declared key columns must be unique across rows, or the plan fails. |
| `sort_rows` | Ascending by the declared columns, using typed comparison. |

Every output is written in one canonical form: UTF-8 without a byte order mark, LF line endings, comma delimiter,
minimal RFC 4180 quoting, a header row, and declared missing tokens rendered as empty cells. The engine performs no
aggregation, interpolation, imputation, smoothing, outlier removal, unit conversion or statistics. Those belong to
later, separately decided steps.

### D30-01e-2 — `CuratedDatasetManifest`

The frozen public artifact name for H30-S02A is **`CuratedDatasetManifest`**. It is a versioned v1 contract appended at
the next registry index. Nested helper records are not registered and get no standalone schema. It binds:
- **Identity:**
  - a lowercase `curated_dataset_id`
  - a `curation_version` (`MAJOR.MINOR.PATCH`), with identifier `curated-dataset-<id>-<version>`
  - the tenant
- **Inputs:** an ordered, non-empty list of exact raw references. Each reference holds the raw manifest identifier,
  its `content_hash` and its `bundle_hash`.
- **The full plan,** embedded as declared data, with the transformation vocabulary version `1.0.0`.
- **Output files:** relative path, byte size, SHA-256, media type `text/csv` and declared columns.
- **An output bundle hash,** computed by the same rule as ADR-006.
- **License inheritance:** the license class, license identifier and attribution statement are copied exactly from the
  inputs. All inputs must agree. A curated dataset can never carry a more permissive license than its inputs.
- **A non-empty `modification_notice`:** a human-readable statement of what the plan changes. This satisfies publisher
  disclosure terms such as ECDC's.
- **Declared time basis, geography basis, `declared_at`, a self-covering `content_hash`, and exact-JSON `metadata`.**

### D30-01e-3 — Verification by re-execution

Curated verification is a pure function over:
- the curated manifest
- the referenced raw manifests
- the raw bytes
- the curated bytes

It verifies the raw inputs first, using the ADR-006 verifier. It then **re-executes the plan** and requires the output
bytes, sizes, hashes, bundle hash and content hash to match exactly. It fails closed with exactly one typed error. A
curated dataset whose outputs cannot be reproduced from its inputs is invalid by definition.

### D30-01e-4 — Storage and immutability

- **Location.** Curated bundles live at `datasets/v1/curated/<curated_dataset_id>/<curation_version>/`, with a
  `manifest.json` and the output files.
- **Size limit.** The ADR-006 25 MiB limit applies per curated bundle.
- **Immutability.** A changed plan, input or engine version means a new `curation_version` in a new directory; nothing
  is overwritten.
- **Byte handling.** `/datasets/** -text` keeps all bytes exact.

### D30-01e-5 — Tenant namespace for real reference data

Real public reference data and everything derived from it use the tenant namespace **`kalhas-reference`**. Synthetic
Phase 29 artifacts keep `kalhas-synthetic`. A curated dataset must have the same tenant as every one of its inputs;
cross-tenant inputs are rejected. A later benchmarked PAN release that consumes reference data is a new release in
`kalhas-reference`. Maturity and claims never transfer from the synthetic PAN v0.1 (ADR-005).

### D30-01e-6 — What curation is not

Curation does not split, select evaluation periods, look at outcomes, fit or score. Splits and sealed holdouts are
decided under H30-S02B. Curation plans for real bundles are authored without inspecting outcome values. Only schema,
labels and missingness may inform them, as in the H30-D01 intake.

## Consequences

- **H30-S02A implements the generic pieces with synthetic fixtures only:**
  - `CuratedDatasetManifest`
  - the closed plan vocabulary
  - the pure transformation engine
  - the re-execution verifier
  - extended `scripts/verify_dataset_bundles.py` coverage for curated bundles
  - an ADR-007 boundary test
- **A separate intake slice (H30-D02)** authors the first real curation plan over the ECDC raw bundle. For example, one
  canonical file per indicator, with the byte order mark removed and typed values.
- **No Model Pack change.** Model Pack artifacts, PAN maturity and every evidence module are unchanged.
