# Raw dataset bundles

This directory holds immutable raw dataset bundles under
`datasets/v1/raw/<dataset_id>/<vintage>/`, each with a `manifest.json`
(`RawDatasetManifest`, ADR-006). Raw bytes are stored exactly as published and
are never edited, re-encoded or normalized. A changed byte is a new vintage in a
new directory. `uv run python scripts/verify_dataset_bundles.py --check`
verifies every bundle offline.

## Attribution and modification notices

Every derived output built from a bundle below must carry that bundle's
attribution and state its own modifications.

### ecdc-covid19-hospital-icu — vintage 2026-11-02

- Data: ECDC COVID-19 hospital and ICU admission rates and current occupancy
  (`data.csv`), retrieved 2026-11-02 from
  `https://opendata.ecdc.europa.eu/covid19/hospitalicuadmissionrates/csv/data.csv`.
- Publisher page:
  `https://www.ecdc.europa.eu/en/publications-data/download-data-hospital-and-icu-admission-rates-and-current-occupancy-covid-19`
- Terms (read 2026-11-02):
  `https://www.ecdc.europa.eu/en/ecdc-intellectual-property-notices`, section
  "Third party data in ECDC databases". Commercial and non-commercial reuse is
  permitted with the acknowledgement below; the permission does not extend to
  identifiable third-party copyright material.
- Required acknowledgement (verbatim):

  Dataset provided by ECDC based on data provided by public health authorities, scientific institutes or health care providers in the relevant reporting countries and/or by WHO.

- Modification notice: no modification — raw bytes as published.
- ECDC states that, when the data are adapted or modified by the user, this must
  be explicitly stated at a suitably prominent place of the work.
- ECDC ceased updates on 1 December 2023 (final week 47 of 2023); corrections
  after closure are not guaranteed.

## Curated bundle: ecdc-covid19-hospital-icu-by-indicator 1.0.0

This bundle derives from raw dataset `ecdc-covid19-hospital-icu`, vintage
`2026-11-02` (`raw-dataset-ecdc-covid19-hospital-icu-2026-11-02`).

Required ECDC acknowledgement (verbatim):

Dataset provided by ECDC based on data provided by public health authorities, scientific institutes or health care providers in the relevant reporting countries and/or by WHO.

Modification notice (verbatim):

Removed the UTF-8 byte order mark; split the rows by indicator into four files; kept the columns country, the time column (date for daily files, year_week for weekly files), value and source; dropped the columns indicator and url, and dropped year_week from daily files and date from weekly files; validated the declared types; sorted by country and time. No value was changed, aggregated, imputed, interpolated or converted.

Outputs built from this curated bundle must carry both the acknowledgement
and the modification notice.
