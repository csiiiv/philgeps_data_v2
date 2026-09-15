# Query and API contract

## API shape

Planned read-only endpoints:

- `GET /api/health`
- `GET /api/catalog`
- `GET /api/tables/{table}/schema`
- `POST /api/tables/{table}/query`
- `GET /api/processes/{process_id}`
- `GET /api/releases/{release_id}`
- `GET /api/records/{record_type}/{record_id}/sources`
- `GET /api/breadcrumbs/{source_file_id}/{source_row_number}`
- `GET /api/quality-issues/{issue_id}`
- `GET /api/party-candidates/{candidate_group_id}`
- `GET /api/canonical-parties/{canonical_party_id}`

The API returns typed JSON objects plus query metadata, limits, warnings, and a
continuation cursor where applicable.

## Table query request

```json
{
  "columns": ["release_id", "award_id", "value_amount", "status"],
  "filters": [
    {"column": "status", "operator": "eq", "value": "active"},
    {"column": "value_amount", "operator": "gte", "value": "1000000"}
  ],
  "sort": [
    {"column": "release_id", "direction": "asc"},
    {"column": "award_id", "direction": "asc"}
  ],
  "page_size": 100,
  "cursor": null
}
```

Allowed operators are type-specific: equality and membership for all scalar
types, ordered comparisons for numeric/date fields, null tests, and explicitly
enabled prefix/contains search for selected strings.

## Safety constraints

- Table and column names come only from the registry, never request text.
- Values are passed as SQL parameters.
- Default page size is 100; MVP maximum is 1,000.
- Export defaults to 10,000 rows and has a configurable hard maximum.
- Each request has a deadline and cancellable DuckDB connection.
- A bounded worker pool limits concurrent scans, and each worker owns its
  DuckDB connection exclusively.
- Queries cannot write, attach databases, install extensions, call filesystem
  functions, or access paths outside the configured datasets.
- Raw SQL is not exposed in the standard UI or public API.
- The default server binds only to `127.0.0.1`, validates `Host` and `Origin`,
  and does not enable wildcard CORS.
- Manifest links are restricted to safe `http` and `https` URLs.

## Pagination

Large tables use keyset pagination based on their documented stable primary
key. Offset pagination is allowed only for small aggregate results because a
large offset still forces substantial work.

The cursor is an opaque, signed encoding of:

- table and schema version;
- sort specification; and
- last returned key values.

Every sort appends the documented primary key as a deterministic tie-breaker
and declares null ordering. Cursors include the dataset fingerprint and are
invalid after source files change.

## Exact lookup paths

Exact IDs use primary-key predicates. Breadcrumb lookup uses the collision-free
tuple `(source_file_id, source_row_number)` plus worksheet where necessary.
Record-source queries include both `record_type` and `record_id` to avoid ID
namespace ambiguity.

## Response representation

- Decimal values are JSON strings plus declared decimal type, avoiding browser
  precision loss.
- Timestamps are returned exactly as stored and labeled timezone-naive until a
  timezone publication policy is approved.
- Lists remain arrays.
- Null remains JSON `null`; it is never replaced with an empty string.
- Large text values are complete in the inspector but visually truncated in
  grids.

## Export handling

Exports stream bounded results, carry dataset/rule versions and query scope,
and never materialize an unbounded response in application memory. CSV output
must mitigate spreadsheet formula injection for text beginning with `=`, `+`,
`-`, or `@`. Contact-person and other potentially sensitive fields are absent
from default projections and require explicit selection.
