# ADR 008: Dataset split membership and holdout lock

- Status: Accepted
- Date: 2026-11-03
- Deciders: KALHAS foundation

## Context

ADR-006 D30-01e requires three things:
- split membership is defined by preregistered rules
- splits are hash-bound **before** any policy or claim is evaluated
- retrospective split repair is prohibited

ADR-007 made curated datasets reproducible from raw bytes. The first curated bundle exists:
`ecdc-covid19-hospital-icu-by-indicator` `1.0.0`, with four files keyed by country and date or ISO week. Phase 30 now
needs an authority that assigns every curated row to exactly one partition, locks that assignment, and keeps holdout
rows away from development work until a later, separately authorized evaluation.

This ADR records that architecture. It implements nothing. At the time of writing:
- no split manifest, split engine, partition view, holdout evaluation or benchmark exists;
- no split rule for the ECDC bundle has been chosen.

This ADR must not be read as claiming any of them. ADR-002, ADR-005, ADR-006, ADR-007 and every frozen v1 contract
remain fully in force. This ADR supersedes nothing.

The mechanism-trajectory evidence path (entry-audit finding F30-02) is recorded as ADR-009, before H30-S05.

## Decision

### D30-02B-1 — Closed partitions and declarative split rules

- **Partitions.** There are exactly three partitions: `development`, `validation` and `holdout`. Every data row of
  every file of the referenced curated bundle belongs to exactly one of them.
- **Rules are declared per curated file,** from a closed vocabulary, version `1.0.0`:
  - `time_partition` — a time column with its declared type (`date` or `iso_week`), plus two cut points
    `validation_from` < `holdout_from` in that column's format.
  - `geography_partition` — a geography column, plus two disjoint value lists, `validation_values` and
    `holdout_values`. Each listed value must occur in that file; this is a label check only.
- **Precedence:**
  - A row is `holdout` if its geography is in `holdout_values` or its time is ≥ `holdout_from`.
  - Otherwise it is `validation` if its geography is in `validation_values` or its time is ≥ `validation_from`.
  - Otherwise it is `development`.
- **Allowed columns.** A rule may reference only columns declared in the curated bundle's `time_basis` or
  `geography_basis`. A rule can never reference a value column, so membership cannot depend on outcomes.
- **Coverage.** Every curated file must have exactly one rule entry.

### D30-02B-2 — `DatasetSplitManifest` and the lock

The frozen public artifact name for H30-S02B is **`DatasetSplitManifest`**. It is a versioned v1 contract appended at
the next registry index. Nested helper records are not registered and get no standalone schema. It binds:
- **Identity:** `split_id`, `split_version` (`MAJOR.MINOR.PATCH`) and identifier `dataset-split-<id>-<version>`; the
  tenant, which must equal the curated bundle's tenant.
- **The curated reference:** manifest identifier, `content_hash`, `bundle_hash`.
- **The rules,** with vocabulary version `1.0.0`.
- **For every file:** the partition counts and a **membership hash**, the SHA-256 of the canonical JSON list of
  partition labels in file row order.
- **A non-empty `preregistration_note`** that states why the rule was chosen. It must say that no outcome values were
  inspected when the rule was chosen.
- **`locked_at`,** plus a self-covering `content_hash` and exact-JSON `metadata`.

The manifest's `content_hash` **is the lock**. Evaluations that later cite a split bind its identifier and hash, and
must be declared after `locked_at`; H30-S05/S06 enforce this. Any change creates a new `split_version` in a new
directory. Earlier splits and everything bound to them are never modified.

### D30-02B-3 — Verification and the sealed holdout

- **Verification.** Split verification is pure:
  1. Verify the curated bundle with the ADR-007 re-execution verifier, including its raw inputs.
  2. Recompute every row's partition from the declared rules.
  3. Require the counts, membership hashes, tenant and content hash to match exactly.

  It fails closed with exactly one typed error.
- **Partition view.** A pure partition view returns `development` or `validation` rows of one curated file, in canonical
  CSV form. It **refuses `holdout` unconditionally** in H30-S02B. Only a later, separately decided sealed-holdout
  evaluation (H30-S06) may introduce an explicit, recorded unseal authority bound to a locked split and a locked
  policy set.

### D30-02B-4 — External sealed references (deferred)

Hash commitments for references held by independent providers (ADR-006 D30-01e) remain a principle. Their contract is
deferred until such a provider exists, for example the ARCHITECT reference providers after an award. It is not part of
H30-S02B.

### D30-02B-5 — Choosing a rule is a separate, preregistered act

The concrete split of the ECDC curated bundle is authored in its own intake slice (H30-D03), not in H30-S02B.
- **Calendar cut points only.** Its rule must be fixed from calendar time, never from epidemic waves or observed
  values.
- **Geography holdout by hash.** Any geography holdout must be chosen by a deterministic, value-blind procedure, for
  example ranking geography labels by SHA-256 of their text. The procedure must be stated in the preregistration note.

## Consequences

- **H30-S02B implements the generic pieces with synthetic fixtures only:**
  - `DatasetSplitManifest` with its unregistered helpers
  - the pure split engine and verifier
  - the holdout-refusing partition view
  - `scripts/verify_dataset_bundles.py` coverage for `datasets/v1/splits/<split_id>/<split_version>/manifest.json`
  - an ADR-008 boundary test
- **H30-D03** preregisters and locks the first ECDC split.
- **No Model Pack change.** Model Pack artifacts, PAN maturity and every evidence module are unchanged.
