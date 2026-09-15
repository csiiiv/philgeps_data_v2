# Architecture decisions

## ADR-001: Build a read-only validation workbench

- Status: accepted
- Date: 2026-09-13

The viewer never edits normalized or OCDS ETL outputs. Any future annotations
or review dispositions must live in a separate overlay with their own audit
history.

## ADR-002: Query Parquet through server-side DuckDB

- Status: accepted
- Date: 2026-09-13

Individual files reach 4.76 GB, making direct browser loading unsuitable for the
full dataset. DuckDB provides typed predicate pushdown and aggregation without
requiring a separate imported database. FastAPI owns query validation and
resource limits.

## ADR-003: Use a registry-driven API instead of unrestricted SQL

- Status: accepted
- Date: 2026-09-13

The standard API accepts allowlisted tables, fields, operators, sorts, and
limits. This makes behavior testable, protects local resources, and lets the UI
explain relationships. A developer-only SQL console can be considered later as
a separately gated feature.

## ADR-004: Keep the MVP cache disposable

- Status: accepted
- Date: 2026-09-13

The viewer initially queries authoritative Parquets directly. Any later search
index or aggregate cache lives under `.cache/`, is keyed by source-file
metadata, and can be rebuilt or deleted without data loss.

## ADR-005: Prefer keyset pagination

- Status: accepted
- Date: 2026-09-13

Stable primary-key cursors avoid the growing scan cost and unstable results of
large offsets. Offset pagination is reserved for small aggregate outputs.

## ADR-006: Implement breadcrumb inspection first

- Status: accepted
- Date: 2026-09-13

The first vertical slice resolves one compact breadcrumb to manifest metadata,
complete source observations, and linked derived records. It validates the
core audit path before investing in generic browsing and domain-specific UI.

## ADR-007: Reuse ETL party identity scopes

- Status: accepted
- Date: 2026-09-13

Supplier search uses the existing observed names, punctuation keys,
legal-suffix keys, candidate groups, provisional canonical parties, and alias
assignments. The viewer does not implement a second party normalizer or infer
new canonical identities inside its cache.

Every supplier query declares its identity scope: exact spelling,
punctuation-normalized, legal-suffix candidate, provisional canonical, or
manual alias selection. The selected spellings and confidence warning remain
visible with the result.

## ADR-008: Treat supplier-contract facts as a disposable acceleration layer

- Status: accepted
- Date: 2026-09-13

Cross-year supplier queries initially join authoritative Parquets directly. If
benchmarks show that these joins are not interactive, a compact
`supplier_contract_facts` projection may be materialized in the viewer cache.
It carries existing keys, relationship statuses, and record IDs but makes no
new normalization or identity decisions.

## ADR-009: Do not present shared contract value as supplier revenue

- Status: accepted
- Date: 2026-09-13

PhilGEPS can associate multiple suppliers with one award or contract without
allocating value among them. The viewer reports distinct awards/contracts,
supplier counts, allocation availability, and “associated contract value.” It
does not attribute the full amount to every supplier as revenue.

## ADR-010: Make search scope and result grain explicit

- Status: accepted
- Date: 2026-09-13

Search results state whether they represent processes, releases, historical
observations, contracts, party mentions, or relationship assertions. Supplier
and lifecycle pages distinguish preferred state from all observed states, and
missing values remain filterable rather than disappearing from default joins.

## ADR-011: Use a distinct canonical-party ID prefix

- Status: accepted
- Date: 2026-09-13

Provisional canonical parties must not share the `pgcp_` prefix used by
contracting processes. Migrate them to `pgca_` before identifier routing and
saved viewer links are enabled.

Migration completed on 2026-09-13: all 318 canonical rows and 7,993 alias
foreign keys now use `pgca_`.

## ADR-012: Aggregate supplier assertions at relationship grain

- Status: accepted
- Date: 2026-09-13

The supplier-contract acceleration table has one row per distinct
`(release_id, award_id, contract_id, party_id)` relationship and records its
supporting assertion count. Assertion drill-through remains separate. This
prevents repeated source evidence from inflating counts and values.

## ADR-013: Treat current currencies as unspecified

- Status: accepted
- Date: 2026-09-13

No populated monetary field currently carries a currency. The viewer does not
format values as PHP or label totals as currency amounts without an explicit,
visible analytical assumption.

## ADR-014: Add a record-oriented provenance lookup cache

- Status: accepted
- Date: 2026-09-13

Direct `(record_type, record_id)` lookup in `record_sources.parquet` takes about
11 seconds. Prototype a disposable record-oriented projection and choose its
physical form based on measured size and latency. Breadcrumb-oriented direct
queries remain authoritative and already perform well.

## ADR-015: Isolate and bound DuckDB request work

- Status: accepted
- Date: 2026-09-13

Blocking queries run outside the async event loop through a bounded worker
pool. Each worker owns its connection, long queries are interruptible, and the
local server validates host/origin while accepting no request-controlled SQL or
paths.

## Decisions still open

- React/Vite versus a no-build static frontend for the first vertical slice
- Default DuckDB memory and per-query time limits
- Whether optional text-search indexes are needed after measurement
- Format and hard row limit for filtered exports
- Whether saved validation notes belong in this project or a separate service
