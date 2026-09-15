# Combined normalized Parquet

## Output

`output/philgeps_normalized.parquet` contains the schema-normalized source
observations for all downloaded years in one file.

- Rows: **17,528,727**
- Manifest source files: **67 of 67**
- Physical schema variants: **4**
- Canonical columns: **60**, including 5 provenance/retention columns
- File size: **1,241,630,997 bytes** (1.16 GiB)
- Source size: **7,722,513,760 bytes** (7.19 GiB)
- Stored/source ratio: **16.08%**
- Parquet row groups: **736**
- Duplicate `(source_file_id, sheet, row)` breadcrumbs: **0**
- Rows with unexpected trailing values: **0**
- Nonblank width anomalies: **0**

The source layouts contribute:

- `location_46`: 7,149,712 rows from 16 files
- `modern_43`: 8,459,022 rows from 39 files
- `legacy_40_uom`: 1,595,484 rows from 11 files
- `legacy_40_unit_of_measurement`: 324,509 rows from 1 file

QA also records 663,074 skipped blank formatted XLSX rows, 2,312 formula cells
read from their cached values, and 10 cells containing Unicode replacement
characters. These are retained as follow-up data-quality findings; source
records were not corrected or deduplicated.

## Query

DuckDB can query the file directly:

```sql
SELECT
  bid_reference_no,
  notice_title,
  _source_file_id,
  _source_sheet,
  _source_row_number
FROM read_parquet('output/philgeps_normalized.parquet')
WHERE bid_reference_no = 'YOUR REFERENCE';
```

Look up `_source_file_id` in
`../RAW_DATA_DOWNLOADER/dataset/manifest.json` to obtain the original local
filename and PhilGEPS/Google Drive URL. The visible source location is then:

`<original filename> · [<worksheet> ·] row <_source_row_number>`

## Validation

The final file was queried independently after its atomic rename. Row totals
match all 67 per-source QA records exactly, all manifest source IDs are present,
no unexpected source IDs occur, and every provenance field except the
intentionally null CSV worksheet is populated. Machine-readable results are in
`artifacts/normalized_parquet_validation.json`.
