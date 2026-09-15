# Compiled process views

## Purpose

`compiled_processes.parquet` is a compact join index that selects one preferred
release per contracting process for convenient analysis. It does not overwrite,
delete, or coalesce historical releases. All descriptive release, tender,
award, contract, item, party, and provenance data remains in the lossless split
tables.

The index contains 10,653,228 processes and is 780.6 MB. Only 692 processes
have multiple releases; their 1,384 release rows are also exposed in the
136 KB `process_release_history.parquet` table.

## Selection rule

Rule `process-compilation-v1` ranks releases within a process by:

1. latest non-null `release_date`;
2. lifecycle completeness: contract, then award, then tender evidence;
3. number of supporting source files;
4. number of supporting source observations; and
5. `release_id` as the deterministic final tie-breaker.

The result is:

| Selection basis | Processes |
|---|---:|
| `only_release` | 10,652,536 |
| `latest_release_date` | 689 |
| `same_date_source_coverage` | 3 |

The evidence-aware preference agrees with the base `latest_release_id` for all
current processes. The explicit policy is still valuable because the base
implementation previously used release ID as its immediate same-date
tie-breaker.

## Preferred-state query

Join children using `preferred_release_id`. For example:

```sql
SELECT
  cp.process_id,
  cp.preferred_release_date,
  t.title,
  t.procurement_method,
  t.value_amount
FROM read_parquet('outputs/parquet/compiled_processes.parquet') cp
LEFT JOIN read_parquet('outputs/parquet/tenders.parquet') t
  ON t.release_id = cp.preferred_release_id;
```

Awards and contracts use the same pattern. This keeps the compiled index small
instead of duplicating the large child tables.

## Historical query

For a multi-release process, query `process_release_history.parquet` by
`process_id`. It records chronological and preference ranks, lifecycle
evidence, content hashes, source-file IDs, and whether content changed from the
previous release.

`alternate_release_ids` in `compiled_processes.parquet` provides a direct
breadcrumb to non-preferred releases. Join any release ID to
`record_sources.parquet` with `record_type = 'release'` to reach the underlying
PhilGEPS rows and manifest URLs.

## Rebuild and validation

```powershell
python OCDS_ETL\scripts\build_compiled_processes.py
```

The builder uses a fast path for the 10,652,536 single-release processes and
ranks only the 1,384 releases that need comparison. It validates complete
process coverage, unique process and preferred-release IDs, preferred-release
foreign keys, alternate counts, and exactly one preferred history row per
multi-release process before replacing either published Parquet.

Results are recorded in `artifacts/compilation_validation.json` and
`artifacts/compilation_profile.md`.
