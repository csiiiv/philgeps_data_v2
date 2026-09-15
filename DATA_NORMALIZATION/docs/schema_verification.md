# PhilGEPS source-schema verification

**Result: PASS**

This report compares every physical source file header with the explicit
schema registry and checks manifest v2 identifiers and normalized names.
It is the pre-ingestion schema gate; exhaustive data-row checks occur while
streaming the sources into raw Parquet.

## Coverage

- Manifest document entries: 71
- Unique source files: 70
- Worksheet/CSV streams inspected: 70
- Missing or unregistered physical schemas: 0

## Observed physical layouts

- `legacy_40_unit_of_measurement`: 1 files
- `legacy_40_uom`: 11 files
- `location_46`: 18 files
- `modern_43`: 40 files

Header positions:

- `legacy_40_unit_of_measurement@row_4`: 1 files
- `legacy_40_uom@row_4`: 11 files
- `location_46@row_1`: 14 files
- `modern_43@row_1`: 40 files

Known headerless exports:

- `files/2021_Oct-Dec.csv`
- `files/2022 _Jul-Sep.csv`
- `files/2022 _Oct-Dec.csv`
- `files/2022_Apr-Jun.csv`

## Reconciliation with the historical reference

The historical `references/philgeps_schema.md` is semantically useful,
but its year-to-layout routing does not match this downloaded snapshot:

- The 40-column `UOM` layout is present in the 2000–2010 annual files.
- A 40-column `Unit of Measurement` variant occurs in the 2017 Q4 file.
- Thirty-nine XLSX files use a 43-column row-1 header that includes
  `Client Agency`, `Created By`, and `Awardee Contact Person`, but no
  `List of Bidder's`.
- Sixteen CSV files use the 46-column location-enriched layout; four of
  those files omit the header row.

Ingestion must therefore route by detected schema signature, never by
year or filename alone.
