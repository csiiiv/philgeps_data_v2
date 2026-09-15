# Benchmark baseline (2026-09-15)

Measured with `python scripts/benchmark.py --json docs/benchmark_results.json`
on the full production Parquets (11,245,628 processes; Windows, NVMe SSD,
viewer-default DuckDB settings: 4 threads, 4GB query memory limit).

## What "cold" and "warm" mean here

- **cold** — first call in a fresh Python process with the disposable
  `.cache/` indexes **already built** (OS page cache may also be warm).
- **warm** — median of 5 repeats inside the same process (service-level
  memoization + hot DuckDB reader).
- **Index build** is a separate, one-time background cost and is reported
  below, not per-case.

## Results

| case | cold (s) | warm median (s) | target (s) | status |
|---|---|---|---|---|
| health | 0.003 | 0.002 | 0.05 | PASS |
| catalog | 0.006 | 0.006 | 0.50 | PASS |
| search common term | 0.004 | 0.004 | 2.00 | PASS |
| search facets | 0.009 | 0.007 | 0.50 | PASS |
| party page | 2.607 | 1.934 | 2.00 | PASS (tight) |
| party identity | 0.058 | 0.046 | 2.00 | PASS |
| process summary (first) | 0.507 | — | 5.00 | PASS |
| process summary (memoized) | — | 0.002 | 0.25 | PASS |
| process detail | 0.002 | 0.002 | 2.00 | PASS |
| process timeline | 0.080 | 0.002 | 2.00 | PASS |
| saved-view counts | 0.562 | 0.002 | 3.00 | PASS |
| table query (50 rows) | 0.237 | 0.204 | 1.00 | PASS |

13/13 at or under target.

## One-time costs (measured separately)

- Search index build (`search_index.duckdb`, ~2.4GB): minutes-scale,
  runs in a background thread at startup; direct Parquet scans serve
  queries meanwhile (totals degrade to honest floors).
- Provenance cache (109.9M-row `record_sources`): ~86 min one-time build;
  lookups ~300 ms warm (ADR-014).

## Targets adopted going forward (docs/11 §22)

| path class | warm target | cold (process) target |
|---|---|---|
| trivial metadata (health/catalog/facets) | 0.5s | 0.5s |
| search & party pages | 2.0s | 5.0s |
| process pages (summary/detail/timeline) | 0.25s warm / 5.0s first | 5.0s |
| aggregate counts (view counts, future funnel) | 3.0s | 5.0s |
| bounded table queries (≤1000 rows) | 1.0s | 3.0s |

A new projection (docs/11 Phase 1+) is justified only when a measured
representative query misses its target — the party page (1.93s warm vs
2.00s target) is currently the closest to the line.

## Known limitations of this baseline

- Single machine profile; rerun on any deployment target before comparing.
- "cold" assumes built indexes; delete `.cache/` and rebuild times above
  apply, not per-request numbers.
- The party-page warm median sits within 3% of its target; if it regresses,
  the fix is a party-names facet projection (docs/11 §22), not silent
  caching growth.
