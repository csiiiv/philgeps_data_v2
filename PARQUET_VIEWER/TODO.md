# PhilGEPS Parquet Viewer TODO

This is the working implementation checklist. Update this file when a task is
started or completed so the documented plan and actual application do not drift.

Status markers:

- `[x]` complete and verified
- `[ ]` not started or incomplete
- `[~]` temporary implementation that must be replaced

## Current state

- [x] Document the product scope, architecture, datasets, query contract,
  validation workflows, common views, and architecture decisions.
- [x] Register and schema-check all 18 OCDS-aligned Parquet datasets.
- [x] Load and validate manifest v2 metadata.
- [x] Expose FastAPI health, catalog, and table-schema endpoints.
- [x] Add bounded DuckDB connections and configurable memory/thread limits.
- [x] Add a parameterized table-query endpoint with allowlisted datasets and
  columns.
- [x] Verify the query endpoint returns real Parquet rows and exact filtered
  records.
- [x] Add backend tests for health, schemas, table queries, invalid columns,
  canonical-party IDs, and origin restrictions.
- [x] A temporary HTML/CSS/JavaScript catalog and data-grid UI existed. It was
  replaced by the React frontend on 2026-09-13 after feature parity was
  verified. (Before removal, a `formatNumber is not a function` bug had
  prevented the temporary UI from ever rendering catalog data.)

## Next: align the application stack

- [x] Scaffold the frontend as Vite + React + TypeScript under `frontend/app`.
- [x] Add and lock npm dependencies (`frontend/app/package.json`).
- [x] Configure Vite to proxy `/api` requests to FastAPI during development.
- [x] Provide one development command that starts FastAPI and Vite together
  (`scripts/dev.ps1`).
- [x] Port the existing catalog summary into typed React components.
- [x] Port the dataset selector, schema-driven filter controls, result grid,
  and pagination into React.
- [x] Add explicit loading, empty, and error states for every API-backed view.
- [x] Configure the Vite production build for serving through FastAPI
  (`frontend/dist`, served by `backend/app/main.py`).
- [x] Remove the temporary non-React frontend after feature parity is
  verified (2026-09-13).
- [x] Add frontend type-checking and production-build checks
  (`npm run build` runs `tsc -b && vite build`).
- [x] Verify the catalog and actual Parquet rows render in the browser
  (2026-09-13: 18 catalog rows, dataset selector, 50-row grid, and Next-page
  pagination verified against live data).

## Backend foundation follow-ups

- [x] Replace production-data foundation tests with small fixture Parquets
  (temp-dir projects with fixture Parquets, manifest, registry, and settings;
  21 fixture tests; production `test_foundation.py` removed).
- [x] Add query deadlines and cancellation (watchdog `Timer` calls
  `connection.interrupt()`; `query_timeout_seconds` configurable, default 60s).
- [x] Test concurrency limits and DuckDB cleanup after failed queries.
  (2026-09-16: `ConcurrencyTests` verify the pool serves concurrent workers
  and keeps working after a failed query; `ResponseLimitTests` cover the
  new truncation helpers.)
- [x] Define stable API error codes instead of relying only on message text
  (`QueryError` codes: `unknown_dataset`, `dataset_not_queryable`,
  `unknown_column`, `empty_projection`, `invalid_page`, `invalid_filter`,
  `query_timeout`, `query_execution`; returned as `{code, message}` detail).
- [x] Reject non-scalar filter values with a validation error instead of an
  unhandled 500 (found in the 2026-09-13 assessment).
- [x] Treat `page_size: 0` as invalid instead of silently using the default
  (found in the 2026-09-13 assessment).
- [x] Declare `pydantic` as an explicit dependency instead of relying on the
  FastAPI transitive dependency (found in the 2026-09-13 assessment).
- [x] Ensure decimal, date, timestamp, list, and null values round-trip without
  losing type information (fixture tests assert decimal-as-string,
  ISO date/timestamp, list arrays, and JSON null).
- [~] Response-size safeguards: page-size cap enforced (1–1000); wide-row and
  large-text truncation shipped 2026-09-16 — text cells are capped at
  `MAX_CELL_CHARS` (20k, suffix "… [+N chars]"), rows heavier than
  `MAX_ROW_WEIGHT_CHARS` (~400k chars JSON) are dropped and reported via
  `dropped_oversized_rows`; full values remain in the Parquets.

## Bounded table explorer

- [x] Replace temporary offset pagination with signed keyset cursors
  (HMAC-SHA256-signed `CursorCodec`; keyset predicate over sort + primary
  key; offset fallback for first page; verified live: 4-page walk of 318
  canonical parties with no duplicates).
- [x] Bind cursors to the table, filters, sort, registry version, and dataset
  fingerprint (cursor payload carries all of them; tampered or re-bound
  cursors are rejected with `invalid_cursor`).
- [x] Add multi-filter AND/OR behavior and typed operator validation
  (`filter_logic: and|or`; values validated against column kind — text,
  number, ISO date/timestamp/time, boolean; list/struct columns support only
  null tests).
- [x] Add selectable columns and documented column presets (column checkbox
  picker; presets remain open until traceability views define them).
- [x] Add deterministic sorting with primary-key tie-breakers and declared null
  ordering (auto-appended PK asc; `NULLS LAST`; clickable sort headers).
- [x] Add a complete row inspector for values truncated in the grid (modal
  with column, type, and full value per field).
- [x] Add bounded JSON and CSV export with spreadsheet-formula protection
  (`POST /api/tables/{t}/export?format=csv|json`; hard `export_row_limit`
  (10,000); formula prefixes `= + - @` neutralized with a leading apostrophe;
  `truncated` flag and limit headers).
- [x] Encode active dataset, filters, sort, page size, and selected columns in
  the URL (`?q=` JSON state; bookmark/share support).

## Traceability workbench

- [x] Implement breadcrumb lookup using
  `(source_file_id, source_row_number, source_sheet)`
  (`GET /api/breadcrumbs/{file_id}/{row}`; optional sheet disambiguates
  collisions; verified live end-to-end against real data).
- [x] Display the complete normalized and cleaned source observations side by
  side (trace drawer: column · normalized raw · cleaned typed, with decimal
  scale differences visible).
- [x] Display manifest filename, normalized filename, coverage range, and
  PhilGEPS source URL (normalized file name + document title + safe
  http/https source URL rendered from manifest v2).
- [x] Resolve a derived record to all entries in `record_sources.parquet`
  (`GET /api/records/{record_type}/{record_id}/sources`; "Trace" button on
  every grid row for the eight traceable record types).
- [x] Reverse-resolve a source breadcrumb to every derived record (breadcrumb
  response lists all derived records; live check found 8 linked records).
- [x] Clearly distinguish source row numbers from Parquet row positions
  (drawer labels rows as physical source rows; fixture test asserts the
  contract).
- [~] Add sampled lineage reconciliation tests across all record types
  (fixture round-trip tests cover tender_item and the full path; a sampled
  production reconciliation across all eight record types remains open).
- [x] Record-oriented provenance lookups (`(record_type, record_id)` in the
  109.9M-row `record_sources.parquet`) are now served by the disposable
  record-keyed projection (`backend/app/provenance.py` →
  `.cache/provenance.duckdb`, ADR-014). Measured: direct scan 14–36s →
  warm cache **~300ms** (first request after restart ~3s to memory-map the
  3.2GB cache). One-time build ~86 min for 109.9M rows; builds run in the
  background while requests fall back to direct scans; fingerprinted to the
  authoritative Parquet (size+mtime), so deletes/rebuilds are automatic and
  source data is never touched.

## Domain views

- [x] Search-first landing for non-technical researchers.
  (`GET /api/search?q=…&page=…` returns plain-language story cards: procurement
  titles (one per process via preferred release) and party names (with
  aggregated roles), no pipeline keys exposed, with real match totals
  ("showing 20 of 275,056" for common terms) and paged "Show more".
  `GET /api/parties/name/{name}` powers a researcher-facing party page:
  every procurement observed under one name, as story cards — party
  navigation no longer drops users into the raw grid. `SearchIndex` applies
  the ADR-014 disposable-cache pattern: a pre-joined projection in
  `.cache/search_index.duckdb` fingerprinted to the four source files plus
  an INDEX_SCHEMA_VERSION (bumped when index tables change, so code-only
  changes also invalidate), built inline for small sources and in a
  background daemon thread at startup for large ones, per-build spill
  directories (concurrent builds no longer race), atomic swap, persistent
  read-only reader; direct Parquet scans remain the fallback (totals
  degrade to honest floors). Count queries run separately from the LIMIT
  fetch — `count(*) OVER ()` materialized all 275k matches and cost 20s;
  split, fresh terms are ~4.5s indexed (party pages ~0.8s), repeats
  instant via LRU(128). Index ~2.4GB for 10.6M processes incl. the
  name->process table. UI: Search tab (default) with debounced single
  search box; cards open the procurement page or the party page; the
  maintainer grid stays behind "Advanced explorer" (`?view=explorer`).
  Honest-data rules: name matches labeled as name matches (identity
  resolution stays provisional), amounts shown with recorded currency
  or "no currency recorded".)
- [x] Researcher UI drill-down flow (layered modals, table results, source
  provenance in the researcher flow). User feedback that drove this:
  single-modal navigation destroyed context on every drill-down; result
  lists rendered as cards where tables scan better; the procurement page
  showed internal ids but never the human-readable PhilGEPS source file
  name/URL/row numbers; child records redirected to the Advanced explorer.
  Delivered:
  - Layered modal stack (`ModalHost.tsx`): every drill-down pushes a layer
    (search → party → procurement → records/sources → raw rows); each
    dialog header carries "← Back" (pops one layer) and "Close all";
    deeper layers dim behind the active one so the hierarchy is visible.
    `openProcess` moves an existing layer to the top instead of no-op, so
    procurement → supplier → same procurement loops work. Deep link
    `?process=pgcp_…` still opens the procurement page as layer 0 and the
    URL tracks the topmost process layer.
  - Tables replace cards: search results (procurement + party sections)
    and the party page render scannable tables (Project/Status/Amount/
    Closing; Name/Role/Records); full procurement titles are clickable
    rows.
  - Source provenance, first-class: `GET /api/releases/{id}/sources`
    (release's source files as human-readable references — file name,
    sheet, row range, row-ref count, record-type count, manifest source
    URL) powers a dedicated "Source files" section on the procurement
    page and a Sources modal with "View raw rows". `GET
    /api/source-files/{id}/rows?start_row=&end_row=` renders the raw
    PhilGEPS spreadsheet rows (as-ingested values, ≤100 rows) in a table
    with the original row numbers and an "Open original PhilGEPS file ↗"
    link — the end-to-end audit path without leaving the researcher UI.
    `record_sources` responses now also carry `source_url` per row.
  - Child records stay in the flow: "Tender/Award/Contract/Party records"
    buttons on the procurement page open a Records modal — a
    researcher-friendly table (labeled columns like Supplier, Amount,
    Contract no.; keys hidden) with a per-row "View source" action that
    resolves the record's breadcrumbs and opens the raw rows around that
    row. Multi-release processes honestly note "showing the preferred
    release; N releases total". No more Advanced-explorer redirects from
    researcher views (the explorer remains available via its tab and the
    maintainer ProcessDrawer).
  - Verified live end-to-end on the real PULSE procurement: summary →
    sources (2025-07--2025-09.csv rows 202990–203019) → raw rows (59
    columns) → tender records. Backend 77/77 tests green.
  - Sizing follow-up (user feedback: "modal is too small for table view"):
    table-bearing modals now use `.wide-modal` (`min(1280px, 100vw−56px)`,
    raw-rows `1400px`), max-height 88vh with sticky headers and a 58vh
    table scroll area; semantic cell classes (`cell-title` max 560px,
    `cell-detail` max 420px, `cell-amount` nowrap tabular) wrap text
    (`white-space: normal; overflow-wrap: anywhere`) instead of the global
    one-line ellipsis — verified in-browser: the 139-char PULSE title now
    wraps to multiple lines; long party names, source-file names, and URLs
    wrap everywhere (`.modal-heading`, `.link-button`, `.source-file-main`).
- [x] Peso display + subway-style timeline on the procurement page.
  (User direction: drop "no currency recorded" phrasing and assume pesos;
  timeline of events as a subway diagram with drill-down. Money now
  renders `₱123,456` when currency is PHP or null (internal PH
  government tool — null simply means the row didn't repeat PHP);
  genuinely non-PHP amounts keep their code so nothing is silently
  converted; applied to summary tiles, award table, search results,
  party page, records modals (Currency columns dropped), timeline.
  `summary` now returns `timeline_events` (bounded 80): tender
  published → bids close → each award (with supplier names + amount) →
  each contract (amount) → contract period ends; unsuccessful/cancelled
  states surface too. Dates fall back across bases (event date →
  publish date); undated events are dropped, honestly. UI: vertical
  subway line with colored nodes per kind (📢 publish, ⏳ closing, 🏆
  award, 📝 contract, 🏁 period end, ⛔ closed), per-stop date, label,
  ₱ amount, supplier detail, and a "View … records" drill button that
  opens the records modal for that event's dataset (layered modals keep
  the timeline behind).   Verified live on PULSE: 23 stops Aug 15 →
  Aug 26, split awards visible day-by-day. 79/79 backend tests green
  incl. timeline ordering + supplier-detail coverage.)
  Follow-ups (2026-09-14): timeline "View this award" now filters to
  that one award_id (plus its award_suppliers), not every award on the
  release — verified Accommodation → ₱21,000 → BLUE LOTUS only. Back
  no longer double-pops: behind backdrops are pointer-events:none and
  only the topmost backdrop dismisses on outside click; header actions
  stopPropagation. Escape / Back / ✕ all pop exactly one layer.
- [x] Split-award disclosure on the procurement page.
  (User need: a flat "Suppliers (N)" list hides which supplier won which
  award — crucial for spotting bid-splitting. `summary` now computes
  `award_structure`: awards LEFT JOIN award_suppliers (title, value, date,
  per-supplier JV label, link statuses, quality flags) with a correlated
  award_items count per award, sorted by value desc, top 50 rendered.
  Distinguishes awarded supplier names from suppliers merely listed in
  party_roles with zero award assertions (`listed_not_awarded` — being
  listed does not mean being awarded). UI replaces the flat supplier list
  with an Awards & suppliers table: one row per award (Award / Amount /
  Date / Items — "not linked" when no item-level evidence / clickable
  supplier names with JV and link-issue badges); multiple awarded
  suppliers surface a neutral verification hint (split-award pattern:
  check per-award amounts against the tender value), never an accusation.
  Verified on the real PULSE catering procurement: 21 awards across 9
  suppliers disclosed, top supplier concentration visible (ASTROCHAIRS
  13/21). Fixtures now cover split lots, JV annotation, item links, and
  a listed-but-never-awarded supplier; 78/78 backend tests green.)
- [x] Researcher-facing procurement page (keys abstracted).
  (`GET /api/processes/{process_id}/summary` assembles the human story for
  the preferred release in three DuckDB passes (tender pick, parties+roles
  join, awards+contracts UNION ALL), memoized against the dataset
  fingerprint (LRU 128): cold ~3.5s on real data, warm ~6ms. Payload splits
  researcher-facing fields (title, entity, suppliers, amounts with recorded
  currency — never asserted PHP, dates, status, quality badges) from
  internal keys nested under `technical` (ids, selection basis, rule
  versions) per the display contract. UI: ProcessPage modal via `?process=`
  URL param or header lookup; "Records & timeline" drills into the
  maintainer ProcessDrawer. Fixture coverage: parties/party_roles/
  award_suppliers tables added; tests assert human fields, technical
  nesting, and 404. Live-verified on a real 3-award, 2-supplier BFAR
  procurement.)
- [x] Process explorer with preferred and alternate releases
  (`GET /api/processes/{process_id}` joins identity + compiled preference;
  `GET /api/processes/{id}/timeline` lists every release ordered by date with
  lifecycle flags; `GET /api/releases/{release_id}/children` returns bounded
  per-release child counts via one UNION ALL scan, memoized against the
  dataset fingerprint (LRU 256) — first count ~7s on unsorted files, repeats
  ~10ms. UI: ProcessDrawer with identity block, clickable timeline (preferred
  release badged), count tiles that drill through to the filtered grid;
  `pgcp_…` ids route through the header lookup. Verified live on a real
  2-release process.)
- [x] Tender, award, and contract review views.
  (Delivered as saved views — versioned JSON definitions in
  `config/saved_views.json` per `docs/08`, rendered through the existing
  query API, no hardcoded pages: `GET /api/views` lists definitions
  validated against the registry (stale columns are reported as problems,
  not silently dropped); `POST /api/views/{name}/query` executes one.
  10 views ship: publication-blocking issues, issues by category, tenders
  with unresolved status/method mappings, closed tenders, awards without a
  value, contracts without a number, unmatched-award contracts, unmatched
  supplier parties, low-confidence parties. UI: "Saved view" picker applies
  dataset+filters+sort into the explorer (URL-encoded, shareable).
  Live-verified: all 10 run in 0.35–2.2s; reconciliation views return 0 rows
  with explicit empty-result warnings.)
- [~] Multi-release comparison with field-level changes. (Timeline and
  per-release drill-through exist via the process explorer; field-level
  diff of two releases' child rows remains open.)
- [x] Quality-issue queue with severity and publication-gate filters.
  (The issue dataset has a single severity value today (`warning`), so the
  queue is served by the saved-views system: `issues_blocking` and
  `issues_by_category` views filter on `publication_blocking` and any typed
  column; issue rows carry record linkage (`release_id`, `record_type`,
  `record_id`) for Trace-button source evidence, and `rule_version` is
  exported. Severity-specific facets become pure configuration once the ETL
  emits more severities.)
- [x] Researcher-facing data-health page.
  (`GET /api/views/counts` counts every valid saved view's filter predicates
  via the query planner's `count_sql` (no projection/sort), memoized per
  dataset fingerprint (single-entry cache). UI: "Data health" tab
  (`?view=health`) lists the questions in plain language with live counts —
  "Needs attention" (count > 0) first, "Clean — N checks passed with 0
  records" collapsed below; opening a question applies the saved view in the
  Advanced explorer (working a queue means inspecting raw records, so the
  grid is the correct destination there). Adding questions remains pure
  configuration in config/saved_views.json. Live-verified: all 10 counts in
  ~1.9s — e.g. 13.88M publication-blocking issues, 6.68M unresolved method
  mappings, 1.30M contracts without a number, 2 clean checks at 0.)
- [x] Researcher UI enhancement batch (2026-09-15/16).
  - Branching timeline: `summary.timeline` is now a `ProcessTimeline` — a
    spine (tender published → bids close) plus one branch per award, and a
    "closed / not awarded" branch carrying unawarded tender line items
    (shown with a note when the closing date is missing). UI renders lanes
    instead of a flat list; per-stop drill-through unchanged. Verified on
    the Area IV meals process (4 items, 2 awarded, 2 closed).
  - About page (`?view=about`): how the data is derived/structured/called,
    live catalog statistics, source references, naming conventions.
  - Search filters & facets: status + year-from/year-to filters with match
    counts (`/api/search` `statuses`, `year_from`, `year_to`); rendered as
    chips above results and cached separately from the plain query.
  - Party identity scope + pagination: `/api/parties/name/{name}?scope=`
    name|identity — identity aggregates every known spelling via
    `party_names.name_key` variants (resolved through the small names
    table, NOT a column on the 15M-row projection, to stay under the
    DuckDB memory budget). Party results paginate independently
    (`party_page`) so "Agencies & suppliers" has a working "Show more".
  - Quality flags with plain-language help: summary `quality_flags`
    rendered as chips explaining every known token (`source_row`,
    `inferred_content_composite`, `multiple_releases`,
    `release_content_changed`, `release_date_tie_resolved`,
    `preferred_release_date_missing`); unknown tokens render raw.
  - Award-vs-tender ratio: summary `award_vs_tender` (summed award values
    vs tender reference value; mixed currencies or a missing tender value
    disable the comparison rather than lying) with a colored chip — amber
    ≤95% (partial award), green 95–110%, red >110% (split/increase).
    Verified live: Area IV shows 50% (2 of 4 items awarded).
  - Party page stats header: `stats` block (role split, status counts,
    value-over-time per year, comparable-currency total) rendered above
    the procurement table with a mini year-bar strip; identity scope
    aggregates across variants. Verified live: Municipality of Bombon,
    ₱602M across 2006–2025, 20 year entries.
  - Data-grid descriptions word-wrap (no more column overlap from long
    titles/details).
  Backend 94/94 tests green (incl. new ratio/stats/flags fixtures);
  frontend build clean; all verified in-browser on real data.
- [x] Party and supplier explorer using observed names, name forms, candidates,
  aliases, and provisional canonical parties.
  (Shipped 2026-09-16: `GET /api/parties/name/{name}/identity` layers the
  ETL's provisional identity resolution on top of name_key variants — the
  promoted `canonical_parties` row (preferred name, match method, evidence
  counts, quality flags), every other observed name form (canonical forms +
  `party_aliases`), and sibling `party_resolution_candidates` groups kept
  separate (unresolved look-alikes shown as a finding, never merged). The
  party page renders this as a lazy-loaded "Identity evidence" disclosure,
  with the proven name-vs-identity scope toggle beside it.)
- [x] Cross-year supplier-contract view with an explicit identity scope.
  (Shipped 2026-09-16: party payload now carries `contracts_by_year` —
  contracts whose award names the party, grouped by contract start year,
  scoped name-vs-identity like everything else on the page; rendered as a
  compact "Contracts by start year" strip in the stats header. No new
  identity decisions are made by this view; it aggregates whatever spelling
  scope the user selected.)
- [ ] Preserve missing and ambiguous relationships as visible incomplete data,
  not broken or falsely resolved links.

## Search and performance

- [~] Benchmark cold and warm queries against the full Parquets.
  (2026-09-13 measurements: `process_id`/`release_id` point lookups 0.1s warm
  page cache / up to ~9s cold first touch; process detail join 0.2–9s;
  per-release child counts ~7s first (tenders, award_suppliers,
  data_quality_issues lack zone-map pruning on `release_id`), ~10ms memoized;
  provenance cache lookups ~300ms warm. A systematic benchmark harness with
  latency targets remains open.)
- [ ] Define latency and memory targets before adding caches.
- [x] Build disposable exact-ID and breadcrumb lookup projections if justified.
  (Record-keyed provenance cache `backend/app/provenance.py`; record→sources
  lookups served from `.cache/provenance.duckdb` sorted by `record_key`,
  fingerprinted to the authoritative Parquet's size+mtime, rebuilt in the
  background when stale, direct-scan fallback at all times; delete-safe.)
- [ ] Build disposable text/facet projections for titles and party names if
  direct scans are too slow.
- [ ] Add quality-issue summary projections for common facets.
- [ ] Consider `supplier_contract_facts` only if measured joins are not
  interactive; do not introduce new identity decisions in this cache.
- [ ] Key every cache to authoritative file metadata and rule versions.
- [ ] Verify deleting `PARQUET_VIEWER/.cache/` cannot affect source data.

## Packaging and handoff

- [x] Document development, production-build, start, stop, and test commands.
  (2026-09-16: README run/satellite sections rewritten — environment check,
  build, start/stop, dev mode, smoke test, and tests in one place.)
- [x] Keep the default server bind local-only at `127.0.0.1`.
- [x] Add a clean startup check for missing dependencies and data files.
  (2026-09-16: `scripts/check_environment.py` verifies required Python
  packages, settings.json validity, parquet directory + required datasets,
  and warns when no frontend build exists; exit code 0/1.)
- [x] Add Windows guidance that does not require changing machine-wide script
  execution policy.
  (2026-09-16: README Windows notes — process-scoped
  `-ExecutionPolicy Bypass`, local-only bind, user-writable pip installs.)
- [x] Complete an end-to-end smoke test from startup through source breadcrumb
  inspection.
  (2026-09-16: `scripts/smoke_e2e.py` walks health → catalog → search →
  process summary (timeline + flags) → party stats + contracts_by_year →
  identity endpoint → release sources; 9/9 checks pass against live data.)

## Deferred decisions

- [ ] Decide whether authenticated network access is needed; remain local-only
  until then.
- [ ] Decide whether review notes or saved cases require persistent state.
- [x] Decide the publication policy for currencies before displaying any amount
  as PHP.
  (Decided 2026-09-14 for this internal validation tool: all amounts are
  PhilGEPS-recorded PHP or null-currency; the UI displays null as ₱ and
  keeps the code for any non-PHP amount — no conversion, no invented
  precision. Revisit if outputs are ever published externally.)
- [ ] Reassess party normalization and legal-suffix handling only after the
  split outputs have been validated.
