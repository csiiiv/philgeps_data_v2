# Deployment memory profile: 4–6 GB RAM VPS

Target: the viewer runs acceptably on a VPS with **50 GB free disk and 4–6 GB
free RAM**. This document records the sizing math, the configuration profile,
and what was measured on the full production dataset.

## Sizing inputs (measured 2026-09-17)

| item | size |
|---|---|
| Source Parquets (22 files) | 19.6 GB |
| `search_index.duckdb` (disposable projection) | 4.2 GB |
| `provenance.duckdb` (disposable projection) | 9.1 GB |
| **Disk total** | **~33 GB** → 50 GB disk is sufficient |

Memory is bounded by three DuckDB ceilings (all configurable, all spill to
`.cache/` temp directories rather than failing):

| ceiling | default (`settings.json`) | VPS profile (`settings.vps-small.json`) |
|---|---|---|
| Interactive query pool (one shared instance for all requests) | 4 GB | 1.5 GB |
| One-shot projection builds (`build_memory_limit`) | 6 GB | 2 GB |
| Startup builds | concurrent | **serialized** (one at a time) |

Python/FastAPI adds ~300–500 MB on top of the active DuckDB ceiling.

## The VPS profile

`config/settings.vps-small.json` is loaded via the `PHILGEPS_SETTINGS`
environment variable (no changes to the development defaults):

```
PHILGEPS_SETTINGS=/srv/philgeps/PARQUET_VIEWER/config/settings.vps-small.json \
  uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

## Measured on this profile (full 11.25M-process dataset, Windows dev box)

- All five hot endpoints answered 200 within seconds of cold start
  (`search 2.7s cold / 5ms warm cached`, `funnel 3.4s cold`,
  `coverage 40ms`, `health 139ms`).
- Warm RSS after load: **~2.2 GB private** — inside the 4–6 GB envelope
  with headroom for the OS page cache to keep the 19.6 GB of Parquets hot.
- One-shot index builds complete under the 2 GB build ceiling; DuckDB
  spills to `.cache/tmp/` so a tighter ceiling costs build minutes, never
  correctness.

## Operational notes for the target box

1. **Startup builds serialize** (search index, then provenance). Until they
   finish, requests are served by direct Parquet scans — correct but slower
   (search totals degrade to honest floors). Expect minutes-scale, not
   seconds-scale, before the fully warm experience.
2. **The provenance cache build is the long pole** (~86 min one-time on the
   dev box, ADR-014/12). It survives restarts: once
   `.cache/provenance.duckdb` exists, startup reuses it. Ship the built
   cache files with the deployment to skip it entirely.
3. **Add swap equal to RAM** (4–6 GB) as an OOM safety net; DuckDB's
   spill-to-temp behavior means memory pressure degrades throughput, not
   availability.
4. **Run one uvicorn worker.** DuckDB memory ceilings apply per process;
   scaling workers multiplies memory. Scale concurrency at the reverse
   proxy (rate limiting, response caching) instead.
5. **Concurrency ceiling**: `max_concurrent_queries: 2` + the 60 s query
   deadline bound worst-case load; put nginx/Caddy rate limits in front
   before any public launch.
