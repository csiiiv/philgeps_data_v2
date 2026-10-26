# PhilGEPS Parquet Viewer

This project will provide a local, read-only web interface for validating the
normalized and OCDS-aligned PhilGEPS Parquet outputs.

The viewer's first responsibility is auditability, not presentation. It should
make it easy to inspect complete rows, follow relationships, compare release
states, review data-quality issues, and resolve every derived record back to a
PhilGEPS source breadcrumb and manifest URL.

## Status

The backend foundation, first browse/filter slice, and bounded table explorer
are implemented. The local UI is a Vite + React + TypeScript application
served through FastAPI: dataset catalog, multi-filter typed queries with
AND/OR logic, signed keyset pagination, column selection, sortable grid, row
inspector, bounded CSV/JSON export with spreadsheet-formula protection, and
URL-encoded view state.

## Proposed stack

- Python 3.14
- DuckDB for read-only Parquet queries
- FastAPI for the local API and static application host
- Vite + React + TypeScript for the browser interface (in `frontend/app/`,
  built to `frontend/dist/` and served by FastAPI)
- A generated table registry that allowlists datasets, columns, relationships,
  and default sort keys

The browser will not load multi-gigabyte Parquets directly. DuckDB performs
bounded server-side queries and returns small paginated results.

Current implementation blockers and constraints are recorded in the
[implementation plan](docs/06_implementation_plan.md), including the canonical
party ID prefix migration and the fact that current monetary values have no
source currency.

## Documentation

The active implementation checklist is maintained in [TODO.md](TODO.md).

1. [Product scope](docs/01_product_scope.md)
2. [Architecture](docs/02_architecture.md)
3. [Data catalog](docs/03_data_catalog.md)
4. [Validation workflows](docs/04_validation_workflows.md)
5. [Query and API contract](docs/05_query_and_api_contract.md)
6. [Implementation plan](docs/06_implementation_plan.md)
7. [Architecture decisions](docs/07_architecture_decisions.md)
8. [Search, filtering, and common views](docs/08_search_filter_and_common_views.md)
9. [Cross-year supplier contract queries](docs/09_supplier_contract_queries.md)
10. [Data model ERD (Mermaid)](docs/10_data_erd.md)
11. [Product improvement opportunities](docs/11_product_improvement_opportunities.md)
12. [Benchmark baseline](docs/12_benchmark_baseline.md)
13. [Process outcomes spec](docs/13_process_outcomes_spec.md)
14. [Relationship status spec](docs/14_relationship_status_spec.md)
15. [Source coverage spec](docs/15_source_coverage_spec.md)
16. [VPS deployment profile (4–6 GB RAM)](docs/16_vps_deployment_profile.md)

## Data sources

The viewer treats these as immutable inputs:

- `../OCDS_ETL/outputs/parquet/`
- `../DATA_NORMALIZATION/output/philgeps_cleaned.parquet`
- `../DATA_NORMALIZATION/output/philgeps_normalized.parquet`
- `../RAW_DATA_DOWNLOADER/dataset/manifest.json`

No validation action may modify these files.

## Current foundation preview

The implementation exposes a schema-checked dataset catalog, health API, and a
read-only data explorer (React frontend). Select a table to load its rows, then
optionally choose a typed schema column and an exact, prefix, substring, or
null filter.

Production-style run (FastAPI serves the built React app):

```powershell
cd PARQUET_VIEWER

# 0. (Optional but recommended) verify environment: packages, settings, data
python scripts\check_environment.py

# 1. Build the frontend (first time and after frontend changes)
cd frontend\app; npm install; npm run build; cd ..\..

# 2. Start in the background and stop it later
.\scripts\start_viewer.ps1
.\scripts\stop_viewer.ps1

# …or start in the foreground of the current terminal
.\scripts\run_viewer.ps1
```

Then open `http://127.0.0.1:8765`. The default server binds to `127.0.0.1` only.
The first metadata load inspects all Parquet footers and may take a few
seconds; it does not scan table contents. Startup performs a live check
(`/api/health`); missing Python packages or datasets are reported by
`scripts\check_environment.py` before launch.

### Network access (LAN / VPS)

Opt-in — binds all interfaces and allows the machine’s LAN IP(s) and hostname
via `PHILGEPS_EXTRA_ALLOWED_HOSTS` (no edit to `settings.json` required):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_viewer_network.ps1
```

Open `http://<this-machine-lan-ip>:8765` from another device on the same
network. There is **no authentication**; anyone who can reach the port can
query the data. For a public hostname, also add it to `api.allowed_hosts` in
settings (or pass `-SettingsPath .\config\settings.vps-small.json` which
already lists `philgeps-v2.simple-systems.dev`). See
[docs/16_vps_deployment_profile.md](docs/16_vps_deployment_profile.md).

Development run (hot-reloading React UI via Vite, API via uvicorn --reload):

```powershell
.\scripts\dev.ps1
```

Open `http://127.0.0.1:5173`; Vite proxies `/api` to FastAPI on port 8765.

### End-to-end smoke test

With a server running (either mode), verify the full researcher path —
health → catalog → search → process summary (timeline, quality flags,
outcome) → outcome funnel and facets → outcome-filtered search → party
stats → identity → provenance sources:

```powershell
python scripts\smoke_e2e.py
```

All checks print PASS/FAIL; a non-zero exit code means something regressed.

### Benchmarks

Measure the hot paths against the adopted latency targets
(docs/12_benchmark_baseline.md):

```powershell
python scripts\benchmark.py --json docs\benchmark_results.json
```

Requires the search index to be built (start the server once, or delete
`.cache\` to also measure the rebuild).

### Windows notes (no admin / no execution-policy change needed)

The scripts avoid machine-wide changes:

- `start_viewer.ps1` / `run_viewer.ps1` launch via `Start-Process` and plain
  `python`/`pythonw` invocations — no `Set-ExecutionPolicy` required when run
  with `powershell -ExecutionPolicy Bypass -File .\scripts\run_viewer.ps1`
  (process-scoped only, nothing persisted).
- Everything binds to `127.0.0.1`; no firewall prompts are expected. If one
  appears, cancel it — the viewer is designed for local use.
- Python dependencies: `pip install fastapi uvicorn duckdb pydantic` in any
  user-writable environment (venv or `--user`); no admin rights needed.

Foundation tests use Python's standard test runner:

```powershell
python -m unittest discover -s backend\tests -v
```
