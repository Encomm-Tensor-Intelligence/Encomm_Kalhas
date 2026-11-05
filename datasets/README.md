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

## Split: ecdc-covid19-hospital-icu-primary 1.0.0

This split references curated dataset `ecdc-covid19-hospital-icu-by-indicator`
version `1.0.0`. Daily files use validation from `2022-07-01` and holdout
from `2023-01-01`; weekly files use validation from `2022-W26` and holdout
from `2023-W01`. A holdout geography takes precedence over time; otherwise
holdout time takes precedence over validation time.

The geography holdout set H is selected by ranking the distinct country
labels across all four files by SHA-256 of their UTF-8 text, ascending, and
taking the first five. In rank order H is: Ireland, Estonia, Belgium,
Netherlands, Portugal. Each file uses the intersection of H and its own
country labels, preserving that order.

Preregistration note (verbatim):

Calendar cut points (validation from 2022-07-01 / 2022-W26, holdout from 2023-01-01 / 2023-W01) and a geography holdout of the five country labels with the lowest SHA-256 of their UTF-8 text, fixed by the reviewer before this split was built. No outcome values were inspected to choose the rule. Before locking, the reviewer ran the split engine on this curated bundle with an unrelated trial rule for software verification only, observing partition row counts and the country coverage of each file, but no values.

The holdout partition is sealed until a separately authorized evaluation
(H30-S06).

## Raw bundle: eurostat-demo-pjan-ecdc-geographies — vintage 2026-11-05

- Data: Eurostat, Population on 1 January by age and sex (`demo_pjan`),
  retrieved 2026-11-05 from
  `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_pjan/A.NR.TOTAL.T.AT+BE+BG+CY+CZ+DE+EE+EL+ES+FR+HU+IE+IS+IT+LI+LT+LU+LV+MT+NL+PT+RO+SE+SI+SK?format=SDMX-CSV&startPeriod=2019&endPeriod=2024`.
- Dataset page: `https://ec.europa.eu/eurostat/databrowser/view/demo_pjan/default/table?lang=en`.
- Terms (read 2026-11-05): `https://ec.europa.eu/eurostat/web/main/help/copyright-notice`.
  Commercial and non-commercial reuse is permitted with attribution. Permission
  is limited to data for EU, EFTA, EU candidate and acceding countries and does
  not extend to material identified as third-party copyright. Modifications
  must be disclosed.
- Required acknowledgement (verbatim): Source: Eurostat, dataset demo_pjan.
- Modification notice (verbatim): none — raw bytes as published
- Coverage: all 25 requested geographies and all years 2019–2024 are present;
  no requested country and year combination is missing.
- This is one retrieval of a dataset revised in place; a later change requires
  a new vintage.

## Curated bundle: eurostat-population-ecdc-geographies 1.0.0

This bundle derives from Eurostat `demo_pjan`, retrieved 2026-11-05 from
`https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_pjan/A.NR.TOTAL.T.AT+BE+BG+CY+CZ+DE+EE+EL+ES+FR+HU+IE+IS+IT+LI+LT+LU+LV+MT+NL+PT+RO+SE+SI+SK?format=SDMX-CSV&startPeriod=2019&endPeriod=2024`.
The terms at `https://ec.europa.eu/eurostat/web/main/help/copyright-notice`
permit attributed commercial and non-commercial reuse for EU, EFTA, EU
candidate and acceding countries; permission does not extend to material
identified as third-party copyright. Modifications must be disclosed.

Required acknowledgement (verbatim):

Source: Eurostat, dataset demo_pjan.

Modification notice (verbatim):

Removed the DATAFLOW, LAST UPDATE, freq, unit, age, sex and CONF_STATUS columns; kept geo, TIME_PERIOD, OBS_VALUE and OBS_FLAG; validated types and sorted rows by geography and year. No value was changed, aggregated, imputed, interpolated or converted. Eurostat is not responsible for this derived file.

The curated file retains all 150 rows. No requested country and year
combination is missing. `OBS_VALUE` is a count of persons, and `OBS_FLAG`
preserves the source status flags.
