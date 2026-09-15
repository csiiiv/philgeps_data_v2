# Architecture

## Overview

```text
Browser UI
    |
    | bounded HTTP/JSON requests
    v
FastAPI application
    |
    | allowlisted query plans
    v
DuckDB read-only query service
    |                         |
    v                         v
OCDS_ETL Parquets       normalized/cleaned Parquet
    |                         |
    +------------+------------+
                 |
                 v
             manifest.json
```

## Backend

FastAPI owns routing, validation, cancellation, response limits, and static UI
hosting. DuckDB reads the Parquets directly, so the MVP needs no database import
or duplicate warehouse.

The query service will:

- resolve all data paths from one application configuration;
- open source datasets read-only;
- expose tables only through a registry;
- compile typed filters into parameterized SQL;
- enforce row, execution-time, and response-size limits;
- use stable keyset pagination for large tables;
- return values with explicit logical types; and
- cancel work when the client disconnects or a deadline expires.

Blocking DuckDB work runs outside FastAPI's async event loop. Connections are
owned by one bounded worker at a time and are never shared concurrently.
Cancellation calls DuckDB interruption; an HTTP timeout without query
interruption is insufficient.

DuckDB memory, thread, and temporary-directory limits will be configurable. Its
temporary and optional cache files must live under `PARQUET_VIEWER/.cache/`,
never beside ETL outputs.

The application binds to `127.0.0.1` by default, validates `Host` and `Origin`,
does not enable permissive CORS, and accepts no request-controlled paths or SQL
fragments. Source values are escaped and excluded from routine request logs.

## Frontend

The proposed React interface has four persistent regions:

- navigation and dataset catalog;
- filter/search controls;
- a virtualized result grid; and
- a record inspector with relationships, quality findings, and source evidence.

URLs encode the active table, record ID, filters, sort, and selected columns so
a validation case can be bookmarked or shared locally.

## Table registry

The registry is the semantic boundary between HTTP requests and SQL. For each
dataset it defines:

- filename and display label;
- primary and foreign keys;
- allowed columns and types;
- searchable and filterable columns;
- default projection and sort;
- relationship links;
- provenance lookup strategy; and
- warning text for inferred or provisional records.

The registry is checked against actual Parquet schemas at startup. A mismatch
blocks the affected table and appears in a health report rather than causing a
misleading partial display.

Each browsing session is tied to a dataset fingerprint. Pagination cursors and
cached results are rejected after input metadata or relevant rule versions
change, preventing one result set from mixing two ETL generations.

## Data access strategy

The MVP queries external Parquets directly. This is appropriate for exact IDs,
source breadcrumbs, process traversal, schema inspection, and bounded filters.

Substring search across tens of millions of rows is a later optimization. If
needed, a rebuildable local DuckDB cache can contain only search-oriented keys
and row locators. It is never authoritative and can be deleted without data
loss.

## Traceability path

Derived records resolve through `record_sources.parquet`:

```text
record type + record ID
    -> release ID and source breadcrumb
    -> source_file_id + source_sheet + source_row_number
    -> cleaned/normalized full observation
    -> manifest filename and source URL
```

Party aliases first resolve to `(release_id, party_id)`, then follow the same
party record-source path. Compiled processes resolve through
`preferred_release_id`; alternate releases remain available alongside it.

Measured direct lookup is asymmetric: breadcrumb-to-record queries are fast,
while `(record_type, record_id)` lookups in the 109.9-million-row provenance
file take about 11 seconds. The implementation therefore needs a disposable
record-oriented lookup projection before source drawers can meet the latency
target.

## Failure behavior

- Missing files produce a visible catalog error without taking down unrelated
  tables.
- Schema drift disables queries for that table until the registry is updated.
- Timed-out queries return a structured error and can be narrowed or retried.
- No result is silently truncated; responses declare limits and continuation
  cursors.
- A missing relationship is displayed as data quality, not a broken UI route.
