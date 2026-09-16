# Source-period coverage (source-coverage-v1)

Status: implemented (docs/11 Phase 2 step 4).
Rule version constant: `source-coverage-v1`.

## Question this answers

"What does each published source period actually contain?" — for every
quarterly PhilGEPS file the ETL ingested: how many releases it backs, how
many observation rows it carries, and how many data-quality issues were
raised against those releases. It makes ingest coverage visible per period
instead of hiding behind one dataset-wide row count.

## Inputs

- `RAW_DATA_DOWNLOADER/dataset/manifest.json` — `source_files[].source_file_id`
  and `normalized_file_name` (e.g. `2021-04--2021-06.csv`)
- `releases.parquet` — `source_file_ids`, `supporting_observation_rows`
- `data_quality_issues.parquet` — `release_id`

## Period label

Parsed from the manifest's `normalized_file_name` prefix `YYYY-MM--`:
quarter = `(month - 1) // 3 + 1`. Files whose name does not parse land in a
visible `unknown` bucket — never silently dropped.

## Grain and counting semantics (deliberate)

| column | meaning |
|---|---|
| `period` | quarter label (`2021-Q2`) or `unknown` |
| `source_files` | files published for the period (1 per quarterly CSV) |
| `release_links` | (file, release) links: a release compiled from notices in several periods counts in **each** — a linkage count, not a distinct count |
| `distinct_releases` | distinct `release_id`s linked to the period's files (de-duplicated across files; equals `release_links` today because `releases.parquet` holds one row per release and 98.5% of releases carry exactly one file) |
| `observations` | `supporting_observation_rows` allocated evenly across each release's files — the rows are a release property and its files share one row-set |
| `issues` | quality issues joined release → files, mirroring `release_links`: a multi-file release's issues count once per file |

Monetary totals are absent on purpose (docs/11 §2): the source CSVs record
notice text, not audited money.

## Projection

The table lives in the disposable `search_index.duckdb` (ADR-014 pattern,
`source_periods`, 70 rows on the current dataset). Building it requires a
multi-second Parquet aggregate (release-side joins over 11.2M releases and
14.6M issues), so it must never run on the request path. `GET
/api/coverage/periods` answers from the projection and returns
`available: false` while the index builds or when it is absent.

## Memory notes from the first full build

The naive formulation OOM'd the 6GB build budget twice:

1. `count(DISTINCT release_id)` at file grain materialized multi-GB VARCHAR
   sets. Because `releases.parquet` has `release_id` as its primary key,
   `count(*)` per file is already the distinct count — no DISTINCT needed.
2. Joining 14.6M issue rows directly into the releases hash table. Fixed by
   pre-aggregating issues to release grain (9.3M rows) before the join.

These notes stand so a future re-derivation does not repeat the OOMs.

## Metadata

Rows served by the endpoint carry the shared derivation-metadata shape
(docs/11 Phase 1 step 0):

```json
{
  "origin": "derived",
  "rule": "source-coverage-v1",
  "rule_version": "1",
  "source_fields": [
    "manifest.source_files.normalized_file_name",
    "releases.source_file_ids",
    "releases.supporting_observation_rows",
    "data_quality_issues.release_id"
  ],
  "basis": "release_file_links",
  "confidence": "derived",
  "source_count": 3
}
```

## Tests

`backend/tests/test_coverage.py`:

- period parser: quarter mapping, unparsable → `unknown` (empty, invalid
  month, malformed names)
- endpoint: quarters sorted newest-first, `unknown` bucket visible,
  per-period link/observation/issue counts on the fixture, totals consistent
- fixture issues with NULL `release_id` (file-level rows) are excluded from
  the per-release join
- degradation: index absent → `available: false`, empty list, never a 500
