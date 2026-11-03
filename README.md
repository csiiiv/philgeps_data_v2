# PhilGEPS data rework

Pipeline and tooling for the Philippine Government Electronic Procurement
System (PhilGEPS) award-notice exports: 25 years of quarterly/annual
downloads (2000–2025, 70 files, 8.4 GB, 18.5M award-item rows) normalized
into one provenance-aware dataset, shaped into an OCDS star schema, and
served through a read-only analytical viewer.

## Repository layout

| Directory | What it is |
|---|---|
| [`RAW_DATA_DOWNLOADER/`](RAW_DATA_DOWNLOADER/) | Stage 0 — Google Drive bulk downloader + the SHA-256 content-addressed `manifest.json` provenance registry (downloads gitignored). [Source folder on Drive →](https://drive.google.com/drive/folders/1Km2gqIfaY_9ZotjvePFZVSMEuxud6WWA?usp=sharing) |
| [`DATA_NORMALIZATION/`](DATA_NORMALIZATION/) | Stage 1 — lossless normalization of source exports into `philgeps_normalized.parquet` (60 columns, all strings) + typed `philgeps_cleaned.parquet` (66 columns) |
| [`OCDS_ETL/`](OCDS_ETL/) | Stage 2 — cleaned layer shaped into 18 OCDS-aligned relational parquet tables plus party-identity and compiled-process layers |
| [`PARQUET_VIEWER/`](PARQUET_VIEWER/) | Stage 3 — read-only FastAPI + DuckDB backend and React/Vite frontend for exploring the datasets |
| [`mapping_references/`](mapping_references/) | Official 2025 mPhilGEPS OCDS mapping templates (field-level v0.91 + codelist v0.2), used as the design reference for the OCDS mapping |
| `DATA_OUTPUTS.md` | End-to-end dataset guide: every dataset, how it was produced, verified row counts and sizes |
| `restore_data_collection.py` | Restore the shared `DATA_COLLECTION` archive into the canonical pipeline layout (cross-platform, relative paths, stdlib only) |
| `tests/` | Sandbox unit tests for the restore script (`python -m unittest discover -s tests`) |

> The `dataset/` downloads inside `RAW_DATA_DOWNLOADER/` are gitignored
> (size and licensing); only the downloader code, URL lists, and docs are
> tracked.

## The three-line summary

0. **Download** — the Google Drive bulk downloader fetches the quarterly
   exports ([PHILGEPS-V2 Drive folder](https://drive.google.com/drive/folders/1Km2gqIfaY_9ZotjvePFZVSMEuxud6WWA?usp=sharing))
   and registers every byte in a content-addressed manifest
   (`source_file_id` = SHA-256), the provenance backbone for everything
   downstream.
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
# Stage 0 — download sources (idempotent, resumable)
cd RAW_DATA_DOWNLOADER
python scripts/download_gdrive_sources.py references/source_urls_4.txt
python scripts/rebuild_manifest.py

# Stage 1 — normalize (requires RAW_DATA_DOWNLOADER/dataset/ with manifest.json)
cd ..\DATA_NORMALIZATION
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

## Deploy from the DATA_COLLECTION archive

The generated datasets (20 Parquet files + the provenance manifest, ~16 GB)
are shared as a `DATA_COLLECTION` archive and are gitignored. On a fresh
clone, extract the archive at the repo root and run the restore script; it
places every file where the pipeline and viewer expect it (paths in
`PARQUET_VIEWER/config/settings.json`):

```bash
# 1. extract the archive so that DATA_COLLECTION/ sits at the repo root
# 2. preview (touches nothing)
python restore_data_collection.py --dry-run
# 3. restore (moves data files; git-tracked files are never overwritten)
python restore_data_collection.py
# 4. start the viewer
cd PARQUET_VIEWER && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8765
```

The script is OS-agnostic (Windows / macOS / Linux), resolves every path
relative to the repo root (never the current directory), uses only the
Python standard library, and is safe to re-run: identical targets are
skipped, differing targets block with exit code 3 unless `--force` is
given. Options: `--keep-source` (copy instead of move), `--verify-hashes`
(SHA-256 every copied file), `--report PATH` (machine-readable JSON).

Note: raw source downloads and OCDS build intermediates are not in the
archive - re-running stage 0/2 requires the Google Drive sources (see
[`RAW_DATA_DOWNLOADER/README.md`](RAW_DATA_DOWNLOADER/README.md)).

## Verify and test (agent quick reference)

Copy-paste checks for humans and AI agents; all exit 0 on success:

```bash
# restore script sandbox tests (no production data needed)
python -m unittest discover -s tests -v

# viewer backend tests (fixture Parquets only, no production data)
python -m unittest discover -s PARQUET_VIEWER/backend/tests -v

# viewer health + catalog after a restore
python -m uvicorn PARQUET_VIEWER.backend.app.main:app --host 127.0.0.1 --port 8765   # repo root
curl http://127.0.0.1:8765/api/health
curl http://127.0.0.1:8765/api/catalog
```

Canonical data locations the viewer reads (relative to repo root):

| Path | Contents |
|---|---|
| `OCDS_ETL/outputs/parquet/` | 18 OCDS star-schema tables |
| `DATA_NORMALIZATION/output/philgeps_normalized.parquet` | lossless 60-column layer |
| `DATA_NORMALIZATION/output/philgeps_cleaned.parquet` | typed 66-column layer |
| `RAW_DATA_DOWNLOADER/dataset/manifest.json` | SHA-256 provenance registry |

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
