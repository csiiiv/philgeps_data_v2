# PhilGEPS data normalization

This project converts the files in `../RAW_DATA_DOWNLOADER/dataset/` into one
lossless, schema-normalized, provenance-aware Parquet dataset. PhilGEPS source
documents remain the source of truth.

## Build

```powershell
python scripts/build_source_catalog.py
python scripts/verify_schema.py
python scripts/build_normalized_parquet.py
python scripts/build_cleaned_parquet.py
```

The final dataset is `output/philgeps_normalized.parquet`. The writer streams
all 67 source files directly into one temporary Parquet and atomically renames
it only after a successful build. It does not create per-source Parquets.

All source values remain nullable strings. Source layouts are mapped onto one
canonical 60-column schema without deduplication, correction, or lossy type
coercion. Four columns provide the source breadcrumb:

- `_source_file_id`: foreign key to manifest v2 `source_files`
- `_source_sheet`: worksheet name, or null for CSV
- `_source_row_number`: visible physical row in the source document
- `_source_schema_id`: verified physical schema mapping

Use `_source_file_id` to resolve the original filename, checksum, and URL(s) in
`../RAW_DATA_DOWNLOADER/dataset/manifest.json`. Together with sheet and row,
the three source-location fields form a unique row breadcrumb.

`output/philgeps_cleaned.parquet` is the typed analytical layer. It preserves
the same rows and provenance while normalizing dates, numbers, configured null
sentinels, whitespace, categories, and organization comparison keys. Suspicious
values are exposed through `_cleaning_issues` rather than silently discarded.

See [docs/normalized_parquet.md](docs/normalized_parquet.md) for validation
results and query examples, [docs/cleaning.md](docs/cleaning.md) for the typed
cleaned layer, [docs/normalization_design.md](docs/normalization_design.md)
for the design, and [docs/source_inventory.md](docs/source_inventory.md) for
source-schema findings.
