# Viewer frontend

React 19 + TypeScript + Vite SPA, built into `dist/` and served by the
FastAPI backend. Routing uses `HashRouter` (hash routes work behind the
Cloudflare tunnel without backend catch-all configuration).

## Layout

```
app/
  index.html          # SPA shell
  vite.config.ts      # dev proxy /api -> :8765; build -> ../dist
  package.json        # scripts: dev / build (prebuild copies xlsx) / preview
  scripts/
    copy-filled-templates.mjs   # prebuild: OCDS_ETL artifacts -> public/downloads
  public/downloads/   # filled OCDS mapping workbooks (served at /downloads)
  src/
    main.tsx          # HashRouter + legacy URL redirect shim
    App.tsx           # top-level tabs, hash-route resolution, query-param sync
    ...pages          # SearchLanding, CoveragePage, HealthPage, ProcessPage,
                      # PartyPage, AboutPage, SchemaPage
    ...components     # ProcessDrawer, TraceDrawer, RecordsModal, SourcesModal,
                      # SourceRowsModal, ItemsPanel, itemTable, sortableTable,
                      # money, LoadingOverlay, ModalHost
    api.ts            # typed fetch wrappers for the backend
    format.ts         # shared formatters
    recordTrace.ts    # breadcrumb/trace client helpers
```

## Pages

| Page | Route | Purpose |
|---|---|---|
| Search landing | `#/` | Cross-dataset search into award items / parties / processes |
| Coverage | `#/coverage` | Source-file coverage by year and schema era |
| Data health | `#/health` | Cleaning-issue and data-quality dashboards |
| Advanced explorer | `#/explorer` | Direct dataset querying with filters/sorts |
| Process | `#/process/:id` | Single contracting-process spine |
| Party | `#/party/:id` | Single party profile with roles |
| About | `#/about` | Project overview |
| Schema | `#/schema` (+ `/crosswalk`, `/columns`, `/ocds`) | Schema evolution, crosswalks, normalized fold map, OCDS mapping + template review; JSON/XLSX downloads |

Query parameters (e.g. explorer `?q={...}`) are scoped to their tab and
cleared on navigation.

## Development

```powershell
cd frontend/app
npm install
npm run dev       # vite dev server on :5173, /api proxied to :8765
npm run build     # prebuild copies xlsx templates, then tsc + vite -> ../dist
npm run typecheck
```

`npm run build` output is what the backend serves in production — rebuild
after frontend changes for the tunneled site to update.
