# Viewer backend

FastAPI application serving a read-only DuckDB view over the OCDS star
schema. Entry point: `app/main.py` (`python -m uvicorn backend.app.main:app`
from `PARQUET_VIEWER/`).

## Module map

| Module | Responsibility |
|---|---|
| `main.py` | App factory, static mounts (`/assets`, `/downloads`), SPA index route, startup warm-up threads |
| `config.py` | `Settings` + `load_settings`; `PHILGEPS_SETTINGS` env var selects a profile (see `docs/16_vps_deployment_profile.md`) |
| `database.py` | DuckDB connection pool with per-query memory ceilings |
| `catalog.py` | Dataset catalog: which parquet tables exist, health, snapshot |
| `query.py` | `TableQuery` engine — filters, sorts, pagination, CSV export |
| `search.py` | Cross-dataset search service (parties, processes, items) |
| `process.py` | Process detail assembly (tender → awards → contracts spine) |
| `outcomes.py` | Process-outcome analytics (see `docs/13_process_outcomes_spec.md`) |
| `coverage.py` | Source-file coverage service (`docs/15_source_coverage_spec.md`) |
| `derivation.py` | Derived projections built/warmed in background |
| `provenance.py` | Breadcrumb cache: derived row → source file/sheet/row |
| `trace.py` | Record-trace endpoints behind the UI trace drawers |
| `views.py` | Shared read helpers for common views |

## Conventions

- **Read-only**: no endpoint mutates datasets; DuckDB is opened accordingly.
- **Small-RAM friendly**: background builds serialize and honor a memory
  ceiling; requests before warm-up fall back to direct scans (never errors).
- **Static**: production frontend is built into `frontend/dist/`; `/assets`
  and `/downloads` are mounted from it; `/` serves the SPA.

## Tests

`tests/` mirror the modules (`test_search.py`, `test_coverage.py`,
`test_trace.py`, …). Run from `PARQUET_VIEWER/`:

```powershell
python -m pytest backend/tests
```
