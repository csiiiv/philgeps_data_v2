# Provenance-first normalization design

## Product requirement

The source reference is a breadcrumb that lets a user double-check a record in
the PhilGEPS source data. It is not a replacement for PhilGEPS as the source of
truth or a formal citation.

A UI can render a compact label such as:

> Source: `2024_Jan-Mar.csv · row 12,345` — Open original

For Excel, include the worksheet:

> Source: `Bid Notice and Award Details 2009.xlsx · Awards · row 8,201`

The original filename and URL are resolved through manifest v2 rather than
repeated on every Parquet row.

## Identity model

Manifest v2 separates two identities:

1. `source_file_id` identifies exact downloaded bytes and is stable across
   renames or moves because it is derived from the file SHA-256.
2. `document_id` identifies an exact source URL. Several document entries may
   point to the same source file.

Every Parquet observation carries `_source_file_id`, `_source_sheet`, and
`_source_row_number`. That composite is unique in the completed dataset and is
the row breadcrumb. `_source_file_id` is the foreign key to manifest v2; no
filename, URL, checksum, formatted breadcrumb, or redundant row hash is stored
per observation.

Physical row numbers are deliberately used: legacy workbooks begin at row 5,
headered CSVs generally begin at row 2, and verified headerless CSVs begin at
row 1.

## Current layer

`output/philgeps_normalized.parquet` is one cross-year, schema-normalized
observation table:

- all 67 unique source files are included;
- the four verified physical layouts map to canonical snake_case columns;
- source values remain nullable strings;
- blank, missing-cell, literal `NULL`, and nonempty values are profiled
  separately in QA;
- no deduplication, source correction, entity resolution, or inferred typing is
  applied yet;
- unexpected trailing values would be retained in `_extra_values`.

The single file is written atomically and uses Zstandard compression. Small
per-source JSON files under `artifacts/raw_ingestion/files/` are QA metadata,
not data partitions.

## Preservation rules

- Map columns by verified header aliases, using position only for conclusively
  identified headerless exports.
- Preserve original text until parsing quality is measured.
- Never silently choose a preferred record among overlapping exports.
- Do not correct the mislabeled or overlapping source exports at ingestion.
- Keep source anomalies visible in QA for later analysis.

## Later normalized relations

After profiling candidate keys and overlap, typed tables or views can split the
observation layer into notices, line items, awards, organizations, and record
sources. Natural bid and award reference numbers should remain attributes, not
sole primary keys, because missing and zero values exist in the source data.
