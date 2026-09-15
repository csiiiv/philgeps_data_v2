# Implementation plan

## Phase 0 — documentation

Status: complete.

Define scope, architecture, datasets, validation workflows, query constraints,
and decision records before scaffolding the application.

## Phase 0a — pre-implementation corrections

Status: in progress. The canonical-party prefix migration and documentation
corrections are complete; the record-oriented provenance prototype remains.

- migrate provisional canonical party IDs from the conflicting `pgcp_` prefix
  (complete: now `pgca_`);
- correct supplier-contract cache grain to one deduplicated relationship;
- treat all current amount currencies as unspecified;
- specify preferred versus historical object grain; and
- prototype a record-oriented provenance lookup projection.

## Phase 1 — backend foundation

Status: in progress. Configuration, the 18-table registry, dataset
fingerprinting, schema/key checks, local host/origin safeguards, health/catalog
endpoints, foundation tests, and the initial catalog surface are implemented.

Create the Python package, application configuration, table registry, DuckDB
connection manager, schema-drift check, and health/catalog endpoints.

Acceptance criteria:

- application starts without modifying input files;
- all 18 current Parquets are discovered and schema-checked;
- missing or mismatched tables produce explicit health findings;
- memory, threads, temp directory, and request limits are configurable; and
- DuckDB work runs in a bounded worker pool with one connection per worker;
- local host/origin policy and dataset fingerprints are enforced; and
- automated tests use small fixture Parquets rather than full production data.

## Phase 2 — bounded table explorer

Implement allowlisted projections, typed filters, stable sorting, keyset
pagination, and limited CSV/JSON export. Build the catalog, data grid, filter
builder, and record inspector UI.

Acceptance criteria:

- no endpoint accepts arbitrary SQL identifiers;
- decimals and timestamps round-trip without type loss;
- page cursors cannot be reused against a different query;
- cancellation and timeout behavior are tested; and
- common exact lookups work against the full data.

## Phase 3 — traceability workbench

Implement record-source lookup, breadcrumb resolution, manifest display, full
normalized/cleaned row comparison, and reverse lookup from a source row to its
derived records.

Acceptance criteria:

- every sampled derived record reaches at least one source row;
- all 67 manifest source IDs resolve;
- source URLs and filenames come from manifest v2; and
- the UI never confuses Parquet row position with physical source row number.

## Phase 4 — domain pages

Build process lifecycle, multi-release comparison, quality-issue queue, and
party-resolution review pages.

Acceptance criteria:

- preferred and alternate releases are clearly distinguished;
- missing and ambiguous relationships remain non-links with evidence;
- party clusters display provisional warnings; and
- table counts on detail pages reconcile with direct DuckDB queries.

The supplier page reuses `party_name_forms`, resolution candidates,
provisional canonical parties, and aliases. It requires an explicit identity
scope and supports exact, punctuation-normalized, legal-suffix candidate,
provisional canonical, and manually selected aliases. See
`09_supplier_contract_queries.md`.

## Phase 5 — performance hardening

Measure cold and warm query latency on full files. Add only the local indexes or
materialized search keys justified by measurements.

Candidate optimizations:

- metadata and schema cache;
- prepared query templates;
- a rebuildable ID/title/name search index;
- bounded aggregate cache keyed by data-file hashes; and
- response compression.

If direct cross-year supplier joins are not interactive,
`supplier_contract_facts` may be added to the disposable viewer cache. It must
reuse existing party keys and canonical IDs and must not introduce identity
decisions of its own. Its grain is one distinct
`(release_id, award_id, contract_id, party_id)` relationship with a supporting
assertion count, not one row per source assertion.

Acceptance criteria:

- exact breadcrumb and primary-key lookups meet the local latency target;
- memory stays within its configured limit;
- cache invalidation detects changed Parquet metadata; and
- deleting `.cache/` never removes authoritative data.

## Phase 6 — packaging

Provide development and production launch commands, dependency locks, Windows
startup guidance, and a local-only default bind address.

Potential later work includes authenticated network deployment, saved review
notes, and shareable validation cases. These require separate privacy and state
management decisions.

## Recommended first implementation slice

Build a vertical breadcrumb workflow before the generic grid:

1. Start FastAPI and validate configured paths.
2. Load manifest v2 into memory.
3. Accept a compact breadcrumb.
4. Query the complete normalized and cleaned source observation.
5. Find linked records in `record_sources.parquet`.
6. Render the result in a simple source inspector.

This tests configuration, DuckDB, large-Parquet predicates, type serialization,
traceability, and the browser shell with one end-to-end feature.
