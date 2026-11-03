# PhilGEPS data rework

Pipeline and tooling for the Philippine Government Electronic Procurement
System (PhilGEPS) award-notice exports: 25 years of quarterly/annual
downloads (2000–2025, 70 files, 8.4 GB, 18.5M award-item rows) normalized
into one provenance-aware dataset, shaped into an OCDS star schema, and
served through a read-only analytical viewer.

## Repository layout

| Directory | What it is |
|---|---|
| [`DATA_NORMALIZATION/`](DATA_NORMALIZATION/) | Stage 1 — lossless normalization of source exports into `philgeps_normalized.parquet` (60 columns, all strings) + typed `philgeps_cleaned.parquet` (66 columns) |
| [`OCDS_ETL/`](OCDS_ETL/) | Stage 2 — cleaned layer shaped into 18 OCDS-aligned relational parquet tables plus party-identity and compiled-process layers |
| [`PARQUET_VIEWER/`](PARQUET_VIEWER/) | Stage 3 — read-only FastAPI + DuckDB backend and React/Vite frontend for exploring the datasets |
| [`mapping_references/`](mapping_references/) | Official 2025 mPhilGEPS OCDS mapping templates (field-level v0.91 + codelist v0.2), used as the design reference for the OCDS mapping |
| `DATA_OUTPUTS.md` | End-to-end dataset guide: every dataset, how it was produced, verified row counts and sizes |

> `RAW_DATA_DOWNLOADER/` (stage 0) lives outside this repository; it stages
> the source downloads and their `manifest.json` (content-addressed by
> SHA-256) that stage 1 consumes.

## The three-line summary

1. **Normalize** — every source layout (5 detected schemas, 2000–2025) maps
   by column name onto one canonical 60-column schema; nothing is dropped,
   every row keeps `_source_file_id` / `_source_sheet` / `_source_row_number`
   / `_source_schema_id` breadcrumbs to the exact source cell.
2. **Shape** — the cleaned layer becomes an OCDS 1.1.5-aligned star schema
   (processes, releases, tenders, items, awards, contracts, parties, roles,
   provenance, quality) with codelist mappings and conservative party
   identity resolution.
3. **Serve** — a read-only viewer exposes search, coverage, data-health,
   process, and party views over the parquet datasets, plus a schema
   documentation tab with downloadable JSON/XLSX exports.

## Where to start reading

- **New to the project?** [`DATA_OUTPUTS.md`](DATA_OUTPUTS.md) — the full
  pipeline story with verified numbers.
- **Building the datasets?** [`DATA_NORMALIZATION/README.md`](DATA_NORMALIZATION/README.md)
  then [`OCDS_ETL/README.md`](OCDS_ETL/README.md).
- **Running the viewer?** [`PARQUET_VIEWER/README.md`](PARQUET_VIEWER/README.md).
- **Mapping to OCDS?** [`OCDS_ETL/docs/05_philgeps_ocds_mapping.md`](OCDS_ETL/docs/05_philgeps_ocds_mapping.md)
  and the template review in
  [`OCDS_ETL/docs/13_official_mphilgeps_template_review.md`](OCDS_ETL/docs/13_official_mphilgeps_template_review.md).

## Build and run (full pipeline)

```powershell
# Stage 1 — normalize (requires RAW_DATA_DOWNLOADER/dataset/ with manifest.json)
cd DATA_NORMALIZATION
python scripts/build_source_catalog.py
python scripts/verify_schema.py
python scripts/build_normalized_parquet.py
python scripts/build_cleaned_parquet.py

# Stage 2 — OCDS star schema (reads DATA_NORMALIZATION/output/)
cd ..\OCDS_ETL
python scripts/build_parquet.py
python scripts/validate_mapping_config.py

# Stage 3 — viewer (reads OCDS_ETL/outputs/parquet/)
cd ..\PARQUET_VIEWER
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8765

# Frontend (dev)
cd frontend\app
npm install
npm run dev          # vite on :5173, proxies /api to :8765

# Frontend (production build into frontend/dist/)
npm run build
```

Python dependencies per stage: `duckdb`, `openpyxl`, `pandas`/`pyarrow` for
stage 1–2 scripts; `fastapi`, `uvicorn` for the viewer backend. Node 20+ for
the frontend.

## Data truth model

- Source documents are the truth; the pipeline is lossless and additive.
- The machine-readable configs are authoritative for their layer:
  [`DATA_NORMALIZATION/config/schema_registry.json`](DATA_NORMALIZATION/config/schema_registry.json)
  (source layouts + canonical aliases),
  [`OCDS_ETL/config/field_mapping.json`](OCDS_ETL/config/field_mapping.json),
  and
  [`OCDS_ETL/config/codelist_mapping.json`](OCDS_ETL/config/codelist_mapping.json)
  (normalized → OCDS).
- Generated artifacts (filled templates, profiles) are documentation mirrors
  of those configs — regenerate, don't hand-edit.

## License / scope

Internal analytical project. No source data is redistributed in this
repository: raw downloads and parquet outputs are gitignored (size and
licensing); only code, configs, and documentation are tracked.
