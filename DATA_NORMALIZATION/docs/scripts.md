# Script reference

Every script in `scripts/`, in pipeline order. All are run from the
`DATA_NORMALIZATION/` directory. Outputs land in `output/` and `artifacts/`
unless noted; both are gitignored.

## Pipeline (in order)

| Script | Purpose | Key outputs |
|---|---|---|
| `build_source_catalog.py` | Walks `../RAW_DATA_DOWNLOADER/dataset/`, verifies each file's physical layout against the schema registry, and emits the per-file catalog used by ingestion | `artifacts/source_catalog.json` |
| `verify_schema.py` | Cross-checks the detected layout of every source file; fails loudly on unmapped columns or unexpected shapes | `artifacts/schema_verification.json`, `docs/schema_verification.md` |
| `verify_headerless.py` | Re-verifies the four 2021–2022 re-export CSVs that ship without header rows | `artifacts/headerless_schema_verification.json` |
| `build_raw_parquet.py` | Legacy name for the normalized build; retained as an alias entry point | — |
| `build_normalized_parquet.py` | Streams all source files into one lossless normalized parquet: canonical 60-column schema, all values nullable strings, provenance breadcrumbs intact | `output/philgeps_normalized.parquet` |
| `build_cleaned_parquet.py` | Adds the typed analytical layer over the normalized build: date/decimal parsing, null-sentinel and whitespace normalization, category cleanup, comparison keys; suspicious values flagged, never dropped | `output/philgeps_cleaned.parquet`, `artifacts/cleaned_parquet_validation.json` |
| `provenance.py` | Shared library for source-breadcrumb resolution (file id → manifest entry) | (library) |

## Tests

| Script | Covers |
|---|---|
| `test_cleaning.py` | Cleaning-rule unit tests (dates, sentinels, whitespace, categories) |
| `test_provenance.py` | Breadcrumb resolution round-trips |

Run with `python scripts/test_cleaning.py` etc. (no pytest dependency
required, though they work under pytest too).

## Configuration

- [`config/schema_registry.json`](../config/schema_registry.json) — the four
  verified physical layouts and the source-column → canonical-field alias
  map. **Authoritative** for ingestion; edit here, not in scripts.
- [`config/cleaning_rules.json`](../config/cleaning_rules.json) — null
  sentinels, date formats, category maps for the cleaned build.

## Conventions

- **Atomic writes**: every build writes to a temporary file and renames only
  on success; failed builds never clobber the previous output.
- **Fail loudly**: any unmapped column or unexpected width aborts the build
  rather than guessing.
- **No per-source parquets**: one combined dataset per stage, with
  `_source_*` breadcrumbs for traceability.
