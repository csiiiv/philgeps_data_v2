# Current PhilGEPS Parquet Viewer: Improvement Suggestions

## Purpose

This document turns the useful interaction patterns from the former PhilGEPS Awards Dashboard into a focused improvement backlog for the current Parquet viewer.

It is deliberately separate from:

- [`philgeps-awards-dashboard-search-filters-drilldowns.md`](philgeps-awards-dashboard-search-filters-drilldowns.md), which documents how the predecessor behaved; and
- [`docs/11_product_improvement_opportunities.md`](../docs/11_product_improvement_opportunities.md), which is the broader product roadmap.

This document concentrates on the next improvements to **search, filtering, analytics, and drill-down navigation**. Each suggestion describes:

- **Current state:** what the latest viewer already does;
- **Suggested experience:** what it could become;
- **Why:** the user or data problem it solves;
- **How:** a practical implementation approach using the existing architecture;
- **Acceptance checks:** observable behavior needed before merging; and
- **Experiment branch:** an isolated branch on which the idea can be evaluated.

## Baseline reviewed

As of 2026-09-16, the viewer already has a strong foundation:

- a search-first researcher landing page;
- approximately 11.25 million contracting processes, including non-awarded processes;
- procurement-title and party-name search;
- status, outcome, and closing-year filters;
- canonical process outcomes and a coverage funnel;
- process and party pages;
- layered drill-down modals that preserve navigation context;
- lifecycle timelines, split-award disclosure, and item-award linkage;
- exact record-to-source provenance and source-row inspection;
- an Advanced Explorer over 18 registered datasets;
- typed filters with AND/OR logic;
- signed keyset pagination;
- configurable columns and deterministic sorting;
- bounded CSV/JSON export;
- URL-encoded Advanced Explorer state;
- configuration-defined saved review views;
- source-period coverage; and
- disposable, fingerprinted DuckDB search and provenance indexes.

The work below should extend these capabilities rather than rebuild them.

## Product principles

Every improvement should preserve the following rules:

1. A count must name its grain: process, release, tender item, award, contract, party mention, supplier assertion, issue, or source observation.
2. Every aggregate must allow the user to inspect its contributing records.
3. Search, charts, drill-downs, and exports must use the same canonical query definition.
4. Missing, ambiguous, conflicting, inferred, and provisional values must remain visible.
5. Entity selection should use stable identifiers where available, not display-name substring matching.
6. Amounts must not be added across incompatible grains or currencies.
7. A supplier's participation in a shared award must not be presented as exclusive revenue.
8. A derived outcome or identity must show its rule or evidence basis.
9. Disposable indexes may accelerate queries but cannot replace the authoritative Parquets.
10. New projections must declare build time, peak memory, storage size, invalidation inputs, and measured query benefit.

## Recommended sequence

The highest-value path is:

```text
Canonical query model
  -> shareable researcher search state
  -> contextual facets and entity typeahead
  -> expanded lifecycle filters
  -> aggregate analytics workspace
  -> entity portfolio and relationship drill-downs
  -> saved investigations and reproducible exports
```

The canonical query model comes first because every later feature otherwise risks inventing a slightly different definition of the active population.

## Priority 0: Unify the investigation model

### 1. Create one canonical researcher query object

**Current state**

The application has at least two capable but separate query models:

- Search Landing sends text, tender status, process outcome, and closing-year bounds to `/api/search`.
- Advanced Explorer sends dataset, typed filters, filter logic, projection, sort, page size, and cursor state to the generic table-query API.

Coverage drill-through passes an outcome into Search Landing as transient component state. Process and party modals have their own navigation state. Export in Advanced Explorer uses its table query, while researcher search does not yet have an equivalent canonical export scope.

**Suggested experience**

Represent every researcher-defined population with a versioned `InvestigationQuery`. Search, filter controls, aggregate views, drill-downs, share links, and exports should all consume this object.

An initial shape could be:

```json
{
  "version": 1,
  "grain": "process",
  "state_scope": "preferred",
  "text": {
    "value": "bridge repair",
    "mode": "all_terms",
    "fields": ["tender_title", "item_description"]
  },
  "facets": {
    "outcomes": ["awarded", "contracted"],
    "tender_statuses": [],
    "buyer_ids": [],
    "supplier_ids": [],
    "methods": [],
    "categories": [],
    "locations": [],
    "quality_flags": []
  },
  "ranges": {
    "closing_date": {"from": null, "to": null},
    "tender_value": {"min": null, "max": null},
    "award_value": {"min": null, "max": null},
    "contract_value": {"min": null, "max": null}
  },
  "stage_presence": {
    "award": "any",
    "contract": "any"
  },
  "sort": [{"field": "closing_date", "direction": "desc"}]
}
```

**Why**

- It prevents a chart, table, and export from silently describing different populations.
- It makes shared links reproducible.
- It allows coverage tiles, party pages, and process lists to use the same filter contract.
- It gives future migrations a version number instead of relying on fragile ad hoc URL parameters.

**How**

1. Define the model in the backend with strict Pydantic validation.
2. Generate or manually mirror the TypeScript type in the frontend.
3. Add a deterministic normalizer that removes empty fields and sorts unordered selections.
4. Add a stable query hash based on the normalized object and dataset fingerprint.
5. Compile the object into parameterized SQL for the search index.
6. Add adapters from the current `/api/search` parameters and Advanced Explorer state.
7. Keep the existing APIs operational while the new model is tested.

**Acceptance checks**

- The same query hash is shown in record results, aggregate responses, and exports.
- Reordering selected facet values does not change the query hash.
- Invalid fields, values, or grain combinations produce stable error codes.
- A serialized query restores the same result count after a page reload against the same dataset fingerprint.
- Unit tests cover normalization, version rejection, empty filters, and backward-compatible adapters.

**Experiment branch:** `experiment/investigation-query-v1`

### 2. Make researcher search state fully shareable

**Current state**

Advanced Explorer stores dataset, filters, sort, page size, and columns in `?q=`. Researcher mode deep-links the top process with `?process=...`, but its search text, status filters, outcomes, years, party pagination, and full modal path are primarily component state.

**Suggested experience**

A copied researcher URL should restore:

- search text and text mode;
- selected facets and ranges;
- current result page or continuation position;
- selected result grain;
- open party or process;
- active process tab;
- nested record/source layer where reasonable; and
- analytics view and selected grouping.

Only stable logical state should be encoded. Ephemeral loading state, raw cursors, and modal animation details should not be included.

**Why**

Research is collaborative. A link should reproduce the question and context, not merely reopen the application. It also makes browser back/forward navigation useful during an investigation.

**How**

- Encode a compact, versioned query token in the URL.
- Keep opaque signed cursors out of durable links; restore the logical page or selected record instead.
- Use `pushState` for meaningful navigation and `replaceState` for transient changes such as typing before Apply.
- Model modal history as a typed logical stack with bounded depth.
- Provide a Copy link action that reports the population grain and active filters.

**Acceptance checks**

- Opening a shared URL in a clean browser restores the same query and selected process.
- Back closes the top drill-down layer before leaving the result population.
- Forward reopens it.
- Stale query versions fail with an explanatory recovery option.
- URLs remain below a documented size threshold; very large queries can use a browser-local saved-query key with an explicit portability warning.

**Experiment branch:** `experiment/researcher-url-state`

### 3. Add a visible active-population bar

**Current state**

Search Landing renders filter chips for statuses and outcomes and two year selectors. Advanced Explorer shows technical filter controls. Process and party drill-downs preserve context through layered modals, but the complete population definition is not consistently visible across researcher views.

**Suggested experience**

Display a compact population bar above results, analytics, and drill-down lists. It should show:

- grain;
- state scope;
- search mode and fields;
- removable filter chips;
- active date and value ranges;
- result count and count quality;
- dataset/build fingerprint summary; and
- actions for Clear, Save, Share, Analyze, and Export.

**Why**

The user must always be able to answer "What population am I looking at?" This becomes critical after several nested entity and chart drill-downs.

**How**

- Render directly from `InvestigationQuery`, not from individual component states.
- Use a single chip-label formatter shared with exports and audit logs.
- Collapse secondary filters into a disclosure on narrow screens.
- Include explicit chips for `Missing`, `Unknown`, and `Ambiguous` instead of hiding these states.

**Acceptance checks**

- Every population-changing action updates the bar immediately.
- Removing a chip updates results, facets, charts, and export scope together.
- Grain and preferred/all-state scope are always visible.
- A screen reader receives the full population definition in a stable order.

**Experiment branch:** `experiment/active-population-bar`

## Priority 1: Expand search and filters

### 4. Add an advanced filter drawer to researcher search

**Current state**

The primary search experience offers tender status, canonical outcome, and closing-year range. Advanced Explorer can filter any registered table column, but it requires knowledge of datasets and schema field names.

**Suggested experience**

Keep the landing page simple, then expose an optional filter drawer organized in researcher language:

- **Lifecycle:** active, closed, awarded, partially awarded, contracted, cancelled, unsuccessful, conflicting;
- **Stage presence:** has/no award, has/no contract, has unawarded items;
- **Dates:** publication, closing, award, contract, source period;
- **Values:** tender, award, and contract ranges;
- **Organizations:** buyer, client agency, supplier, party role;
- **Classification:** procurement method, business category, item classification;
- **Location:** region, province, city/municipality, with location basis;
- **Evidence:** missing/ambiguous links, multi-release, source coverage, quality issues; and
- **State scope:** preferred state or all observed release states.

**Why**

This exposes the complete normalized data without forcing researchers into a schema browser. It also recovers the predecessor's composable discovery workflow while going well beyond awarded contracts.

**How**

- Implement filters incrementally through the canonical query compiler.
- Put low-cardinality dimensions in cached facet dictionaries.
- Put buyers and suppliers behind debounced typeahead endpoints.
- Use inclusive, typed range controls with clear units and date basis.
- Keep Apply explicit for filters that trigger large scans.
- Explain expensive filters before executing them.

**Acceptance checks**

- Different filter families combine with AND.
- Multiple selected values within one family combine with OR.
- Missing and unknown are selectable values, not silently dropped rows.
- Every filter has a plain-language summary and API contract test.
- Clearing one family does not disturb unrelated filters.

**Experiment branch:** `experiment/research-filter-drawer`

### 5. Compute contextual facet counts

**Current state**

The search index precomputes global status, closing-year, and outcome counts. Search Landing fetches these once. Counts do not describe the current text query or the other selected facets.

**Suggested experience**

Facet counts should update for the active population. Prefer disjunctive behavior: each facet value should show the count that would result if selected while respecting filters from the other families.

Example:

```text
Text: school building
Year: 2024

Outcome
  Contracted       1,842
  Awarded            611
  Closed unknown     290
```

**Why**

Global counts can mislead users about what remains after a search. Contextual counts help users refine a population without trial and error and reveal when a filter would lead to zero results.

**How**

- Add a bounded `/api/investigations/facets` endpoint accepting `InvestigationQuery` without pagination.
- Group low-cardinality facets in one or a small number of queries.
- Exclude the facet's own selection when calculating its alternatives.
- Cache using normalized query hash, dataset fingerprint, and facet schema version.
- Return count status such as exact, capped, estimated, or unavailable.

**Acceptance checks**

- Counts reconcile with a record query using the same resulting filter.
- A selected value remains visible even if its contextual count is zero.
- Facet responses meet a measured latency budget.
- The UI clearly distinguishes unavailable counts from zero.

**Experiment branch:** `experiment/contextual-facets`

### 6. Use identifier-backed entity typeahead

**Current state**

Party search finds observed names and can switch between observed-name and provisional-identity scopes on party pages. The primary search does not yet expose buyer or supplier typeahead as a filter. The predecessor selected display labels and later applied substring matching, causing ambiguous and overly broad results.

**Suggested experience**

Entity filters should return typed selections such as:

```json
{
  "entity_type": "canonical_party",
  "id": "pgpa_...",
  "label": "ABC CONSTRUCTION",
  "scope": "provisional_identity",
  "roles": ["supplier"],
  "location_hint": "Cebu",
  "observed_forms": 4
}
```

Users should be able to choose:

- exact observed name;
- provisional identity cluster; or
- normalized-name key where a stable party ID is unavailable.

**Why**

This prevents "ABC" from accidentally matching many unrelated parties and makes identity scope explicit. It also supports reproducible buyer/supplier portfolio analysis.

**How**

- Add a typeahead endpoint over `party_names`, canonical parties, aliases, and role statistics.
- Return stable IDs, result type, match method, role, location evidence, and warning flags.
- Compile selected IDs to equality predicates.
- Preserve the label in URL state for readability but treat the ID as authoritative.
- Keep fuzzy matches opt-in and show their evidence.

**Acceptance checks**

- An exact selected ID cannot broaden into substring matches.
- Name-scope and identity-scope result counts are visibly distinct.
- A renamed display label does not invalidate a saved query when its ID remains valid.
- Ambiguous and unresolved suggestions carry explicit labels.

**Experiment branch:** `experiment/entity-typeahead`

### 7. Add explicit text-search modes and field scopes

**Current state**

Search Landing performs case-insensitive substring search over procurement titles and party names. The user cannot choose exact phrase, all terms, any terms, prefix, identifier, or source field. Item descriptions are not part of the primary researcher search.

**Suggested experience**

Offer a compact search-mode control:

- Exact phrase
- All terms
- Any term
- Starts with
- Identifier

Allow optional field scope:

- Procurement title
- Item description or classification
- Buyer/client agency
- Supplier
- Solicitation/reference number
- Award or contract number
- All supported fields

The default should remain forgiving and understandable, not a raw query-language box.

**Why**

Researchers need both discovery and precision. A search for `road && bridge` in the predecessor encoded AND behavior inside an undocumented string convention. Explicit modes are clearer and can be implemented safely with parameterized predicates.

**How**

- Normalize tokens in the API, not the browser.
- Maintain original text for evidence and matched snippets.
- Route recognizable IDs and breadcrumbs directly to record views.
- Build a separate item-search projection at item grain, then deduplicate to process grain by default.
- Keep fuzzy organization matching separate and opt-in.

**Acceptance checks**

- Every result reports the matched field and match method.
- Exact phrase and identifier modes have fixture tests with punctuation and case variants.
- Item hits show the matching item description and linked award state.
- Search mode survives sharing and export.

**Experiment branch:** `experiment/search-modes-and-items`

### 8. Explain why each result matched

**Current state**

Procurement and party results are concise, scannable tables. A result does not consistently show whether it matched the title, buyer, supplier, item, alias, or normalized identity.

**Suggested experience**

Add a restrained match explanation beneath or beside the primary result label:

```text
Matched item: Fiberglass reinforced plastic banca
Matched supplier alias: ABC CONST. -> provisional identity ABC CONSTRUCTION
Matched identifier: Solicitation no. 2024-017
```

**Why**

Once more fields are searchable, unexplained results look incorrect. Match reasons also prevent provisional alias matches from being mistaken for exact legal identity.

**How**

- Return a bounded `matches` array with field, method, observed value, and optional record ID.
- Prefer deterministic match precedence: identifier, exact, normalized exact, prefix, all terms, substring, fuzzy.
- Cap snippets and match count per result.
- Link item or party match evidence to the relevant detail tab.

**Acceptance checks**

- Every non-identifier result includes at least one match reason.
- Explanations use source text where possible.
- Fuzzy or provisional matches are never presented with exact-match language.
- Match evidence remains available in JSON export.

**Experiment branch:** `experiment/search-match-reasons`

## Priority 2: Add analytics that always drill back to evidence

### 9. Add an analytics workspace for the active population

**Current state**

The viewer has a complete-population coverage funnel, process-level summaries, party statistics, value-by-year views, source coverage, and data-health views. It does not yet offer a general "Analyze these results" workspace comparable to the useful part of the predecessor Analytics modal.

**Suggested experience**

The active population bar should offer Analyze. The workspace should support:

- summary counts with explicit grain;
- outcome distribution;
- yearly/quarterly trend;
- top buyers and suppliers;
- method and category distribution;
- geographic distribution where location basis is declared;
- tender, award, and contract value distributions;
- data completeness and relationship-quality distribution; and
- source-period coverage warnings.

The user should be able to change grouping and metric without changing the underlying population.

**Why**

This keeps the predecessor's best transition, "search then analyze," while the current data can provide honest lifecycle denominators and provenance.

**How**

- Add an aggregate request that accepts the canonical query plus grouping, metric, and requested grain.
- Return `population`, `measure`, `coverage`, `currency_rule`, `grouping`, and `query_hash` metadata with every result.
- Start with process counts and outcome distribution before monetary measures.
- Use pre-aggregated projections only after benchmarks show repeated query misses.
- Make tables the precise default; charts are alternate presentations of the same rows.

**Acceptance checks**

- Clicking any aggregate opens the exact supporting record population.
- Totals reconcile with the search result count at the declared grain.
- Missing values appear as a visible bucket.
- Monetary panels disclose included currencies and excluded rows.
- Exported aggregate metadata contains query hash, dataset fingerprint, grain, and rule versions.

**Experiment branch:** `experiment/investigation-analytics`

### 10. Add complete buyer and supplier portfolio pages

**Current state**

Party pages show observed-name or provisional-identity scopes, roles, status counts, value by year, contract counts, aliases, and procurement history. The experience is a good foundation but does not yet provide a full buyer or supplier portfolio over outcomes, categories, relationships, and evidence coverage.

**Suggested experience**

#### Buyer portfolio

- total processes and releases;
- process outcomes;
- tender, award, and contract counts at separate grains;
- methods and categories;
- top suppliers and supplier concentration;
- timeline duration distributions;
- missing award/contract evidence;
- issue and source coverage; and
- trends over time.

#### Supplier portfolio

- award participation and contract evidence;
- buyers, categories, methods, and locations;
- repeat-buyer share;
- joint-venture participation;
- identity scope and observed aliases;
- relationship ambiguity; and
- trends over time.

**Why**

Entity-centric research was the strongest use case in the awards dashboard. The current model can implement it more accurately because it distinguishes observed names, roles, supplier assertions, party identity candidates, awards, and contracts.

**How**

- Reuse identifier-backed entity filters.
- Create role-aware process and award fact queries.
- Count market awards once at award grain and supplier participation at supplier-assertion grain.
- Never assign a shared award's full value exclusively to every supplier.
- Let every portfolio section open its process, award, contract, or assertion records.

**Acceptance checks**

- Every number names its grain.
- Switching observed-name/identity scope recomputes the entire page.
- Shared and joint-venture awards carry explicit allocation warnings.
- Portfolio totals reconcile with the corresponding canonical query.

**Experiment branch:** `experiment/entity-portfolios-v2`

### 11. Add related-entity intersection drill-downs

**Current state**

Party pages list procurements and can open processes. Process pages expose related parties and records. The predecessor had a valuable flow in which clicking a related entity opened the contracts at the intersection of parent and child entities, but its pagination and filtering were inconsistent.

**Suggested experience**

From a buyer, show related suppliers, categories, methods, and locations. From a supplier, show related buyers, categories, methods, and locations. Selecting a relationship should open the exact intersecting process population.

Example:

```text
Buyer: Department X
  -> Supplier: Company Y
  -> Outcome: Contracted
  -> Year: 2024
  -> 17 contributing processes
```

**Why**

This converts an aggregate relationship into inspectable evidence and lets users answer common questions without rebuilding filters manually.

**How**

- Treat parent and related entity IDs as additional facets in `InvestigationQuery`.
- Use the paginated aggregate API, not a top-N endpoint pretending to paginate.
- Return total group count separately from the current page.
- Preserve parent filters, state scope, text query, dates, values, and quality constraints.
- Encode the full intersection in the shared URL and export.

**Acceptance checks**

- Page 2 returns a different stable entity window from page 1.
- Related-entity totals reconcile with the record population.
- Exported rows match the visible intersection.
- Removing the child chip returns to the parent portfolio without losing other filters.

**Experiment branch:** `experiment/related-entity-drilldown`

### 12. Make the coverage funnel filterable and analytical

**Current state**

The Coverage page shows canonical outcomes and can send an outcome selection into Search Landing. Source-period coverage is available. The funnel is a strong explanation of complete procurement coverage but is not yet a general filtered analysis surface.

**Suggested experience**

Allow the funnel to inherit or define filters for:

- year or date range;
- buyer;
- supplier;
- procurement method;
- category;
- location;
- source period; and
- evidence/quality state.

Every stage should show both a count and its denominator. Selecting a stage should add an outcome/stage filter to the canonical query and open the matching processes.

**Why**

This is the clearest differentiator from the award-only predecessor. It allows comparisons using all procurements rather than only successful awards.

**How**

- Make Coverage consume `InvestigationQuery` at process grain.
- Recompute outcome groups using the versioned outcome projection.
- Provide explicit denominators for rates.
- Show unknown and conflicting evidence as real stages.
- Add source coverage warnings if a selected period is incomplete.

**Acceptance checks**

- Stage counts equal the corresponding filtered record counts.
- Stages are mutually exclusive under the declared outcome rule.
- The displayed denominator is never inferred from only non-null monetary rows.
- Shared links restore the filtered funnel and selected stage.

**Experiment branch:** `experiment/filterable-coverage-funnel`

### 13. Add lifecycle duration and value-reconciliation drill-downs

**Current state**

Individual process pages show lifecycle events and compare tender, award, and contract values. The viewer does not yet provide population-level duration or value-reconciliation distributions.

**Suggested experience**

Add analytical panels for:

- publication to closing;
- closing to award;
- award to contract;
- contract duration;
- tender-to-award value difference;
- award-to-contract value difference; and
- partial-award coverage.

Each bucket or outlier group should open the processes that produced it.

**Why**

These measures use the structured lifecycle in ways the flat awards dashboard could not. They can support operational research and expose source-quality problems without claiming misconduct.

**How**

- Build versioned derivation rules with endpoint/date basis and exclusion reasons.
- Include only rows that meet a declared evidence threshold.
- Publish median and percentiles rather than relying on averages.
- Separate impossible date ordering, missing dates, non-comparable currencies, and ambiguous relationships.
- Persist each bucket as canonical range/quality filters for drill-through.

**Acceptance checks**

- Every metric reports valid-row coverage and exclusion counts.
- Bucket totals plus excluded populations reconcile with the parent population.
- Outlier labels are descriptive, not accusatory.
- Process pages display the same derived duration/value status as aggregate views.

**Experiment branch:** `experiment/lifecycle-metrics`

### 14. Add category and geography exploration with declared basis

**Current state**

Relevant classification and location fields exist in normalized datasets and can be inspected through Advanced Explorer. There is no dedicated researcher view for category or geography. Location may refer to buyer address, delivery area, or another source meaning.

**Suggested experience**

Provide ranked tables and drill-downs for:

- procurement categories and item classifications;
- region, province, and city/municipality;
- outcomes, buyers, suppliers, and values within each group; and
- unmapped or missing classifications.

A map should be optional and secondary to an exact ranked table.

**Why**

These views support regional and sector research while making classification and location coverage visible.

**How**

- Keep original and normalized location/category values.
- Store a `location_basis` or equivalent field with every aggregate.
- Use versioned crosswalks for classification mapping.
- Do not combine buyer location and delivery location in one unlabeled measure.
- Require a minimum coverage threshold before enabling map presentation.

**Acceptance checks**

- Every result states the location or classification basis.
- Unmapped and missing values remain visible.
- Clicking a group opens its exact process or item population.
- Geographic totals reconcile after accounting for multi-location records and the declared counting rule.

**Experiment branch:** `experiment/category-geography-explorer`

## Priority 3: Reproducibility and collaboration

### 15. Add saved researcher investigations

**Current state**

The viewer supports versioned administrator-defined saved views in `config/saved_views.json`. Advanced Explorer state is shareable by URL. It does not yet offer user-created named investigations. The application remains local-only and has no authentication or account storage.

**Suggested experience**

Allow a local user to save:

- name and optional note;
- canonical query;
- selected columns or analytics grouping;
- selected process or party;
- creation/update timestamps;
- dataset fingerprint at creation; and
- query schema/rule versions.

Support import/export as JSON so an investigation can be transferred intentionally.

**Why**

Researchers revisit the same populations. Saved investigations reduce repetitive setup and provide a lightweight, reproducible handoff without requiring a server-side account system.

**How**

- Start with versioned `localStorage` records.
- Validate imported queries through the backend schema before execution.
- Warn when the dataset fingerprint or rule version differs from the saved version.
- Keep admin-defined review views visually distinct from user-saved investigations.
- Delay collaborative notes/cases until the local-only versus authenticated-network decision is made.

**Acceptance checks**

- A saved investigation restores the same normalized query.
- Import rejects malformed or unsupported versions safely.
- Dataset drift produces a warning, not silent equivalence.
- Deleting application caches does not delete saved investigation JSON unless the user chooses to clear it.

**Experiment branch:** `experiment/saved-investigations`

### 16. Make exports exact, reproducible, and self-describing

**Current state**

Advanced Explorer exports bounded CSV or JSON using its current technical table query and protects spreadsheets from formula injection. Researcher search and analytics do not yet have one uniform export contract.

**Suggested experience**

Every result or aggregate view should export from the exact canonical query currently displayed. An export should include or accompany:

- query JSON and hash;
- dataset fingerprint;
- generated timestamp;
- grain and state scope;
- selected columns;
- sort;
- derivation and identity rule versions;
- currency rule;
- total matching rows;
- exported row count and truncation state; and
- warnings and exclusion reasons.

**Why**

The predecessor demonstrated how easily modal exports can diverge from visible filters. Reproducibility requires display and export to share one query object.

**How**

- Add one export endpoint accepting `InvestigationQuery` plus projection.
- Reuse the query compiler used by result search.
- Generate a sidecar metadata JSON for CSV exports or a metadata envelope for JSON.
- Keep hard row limits and formula protection.
- For large exports, estimate cost and require explicit confirmation.

**Acceptance checks**

- Export metadata query hash equals the visible view's query hash.
- Exported rows satisfy every active filter in fixture tests.
- Truncation is explicit in both response headers and metadata.
- No modal or drill-down reconstructs its own partial filter set.

**Experiment branch:** `experiment/reproducible-exports`

### 17. Add data-quality and provenance facets to normal research

**Current state**

Data Health, source coverage, quality-issue review, trace drawers, and raw source rows are already substantial. They live mainly as dedicated validation surfaces or detail actions.

**Suggested experience**

Make evidence quality selectable in ordinary search and analytics:

- has source rows / missing source link;
- one or multiple source files;
- preferred/all release states;
- relationship matched/missing/ambiguous;
- has data-quality issues;
- issue category;
- fallback-derived date;
- observed versus inferred value; and
- source period or worksheet.

Aggregates should be able to compare results with and without weak-evidence rows.

**Why**

Researchers need to assess whether a pattern may be caused by data coverage or derivation quality. Provenance should not only be available after opening one record.

**How**

- Add compact evidence flags to the process search projection.
- Keep detailed issue rows and source breadcrumbs in authoritative datasets.
- Expose evidence flags as facets with plain-language labels.
- Add "Why is this flagged?" links to the existing trace and issue views.
- Do not build severity-based analysis until the ETL severity catalog is meaningful.

**Acceptance checks**

- Evidence facet counts reconcile with source and issue datasets.
- Default search does not exclude weak-evidence records silently.
- Filter labels distinguish missing evidence from negative evidence.
- Every summary warning links to affected records.

**Experiment branch:** `experiment/evidence-facets`

## Priority 4: Performance and correctness guardrails

### 18. Introduce aggregate query budgets and observability

**Current state**

The backend has query deadlines, bounded DuckDB connections, response-size safeguards, fingerprinted caches, search LRU caching, benchmark scripts, and documented memory constraints. Some existing projections are already large, and party projection builds can exceed practical memory limits.

**Suggested experience**

Every new filter or analytic operation should have an explicit cost class and measured service-level target:

- **Instant:** exact identifier and cached metadata;
- **Fast:** indexed search, common facets, and small aggregates;
- **Moderate:** selective Parquet query;
- **Expensive:** broad aggregation, distinct high-cardinality grouping, or large export.

The UI should require Apply for moderate/expensive changes and show cancellable progress.

**Why**

The new features can easily turn a responsive local tool into a sequence of multi-gigabyte scans. Performance rules must be part of feature acceptance rather than a later optimization pass.

**How**

- Add structured timing fields: queue time, planning time, execution time, rows scanned if available, rows returned, cache status, and query hash.
- Log projection build time, peak memory, database size, and invalidation reason.
- Define budgets in benchmark fixtures and production-size baseline runs.
- Prefer one selective indexed projection over several overlapping wide projections.
- Reject unbounded top-N values and large offset pagination.

**Acceptance checks**

- Every new aggregate endpoint has cold and warm benchmark entries.
- Cancellation releases its connection and does not poison the pool.
- Cache keys contain all authoritative input fingerprints and rule versions.
- Query responses disclose whether counts are exact, capped, estimated, or unavailable.
- Projection deletion leaves source Parquets untouched and triggers a correct rebuild.

**Experiment branch:** `experiment/query-observability`

### 19. Add cross-surface reconciliation tests

**Current state**

The project has broad backend tests, an end-to-end smoke test, query-contract tests, outcome tests, item-linkage tests, trace tests, and production benchmarks. New analytics and canonical queries will create more paths that should describe the same population.

**Suggested experience**

Add invariant tests that compare results across surfaces:

```text
search count
  = analytics population count
  = sum of mutually exclusive outcome groups
  = export total metadata
```

and:

```text
aggregate group click
  -> resulting query
  -> contributing record count
  = displayed group count
```

**Why**

The most damaging analytics bugs are not syntax errors. They are quiet population drift, double counting, lost filters, or grain confusion between otherwise plausible screens.

**How**

- Build small fixture Parquets with deliberate multi-release, multi-award, shared-supplier, missing-link, and ambiguous-identity cases.
- Generate canonical queries and run them through record, aggregate, drill-down, and export compilers.
- Assert query hashes and totals across APIs.
- Add browser tests for URL restoration and modal back/forward navigation.
- Keep a small suite of sampled production reconciliation checks separate from deterministic fixtures.

**Acceptance checks**

- Every aggregate grouping has a click-through reconciliation test.
- Every export surface has a filter-preservation test.
- Multi-supplier awards do not inflate award-grain totals.
- Preferred-state and all-observed-state tests intentionally produce different documented counts.

**Experiment branch:** `experiment/cross-surface-reconciliation`

## Behaviors not to copy from the predecessor

The Awards Dashboard contains useful interaction ideas, but these implementation choices should not be carried forward:

1. Do not convert selected entities back into substring filters.
2. Do not label autocomplete as exact when final search remains substring-based.
3. Do not maintain separate filter reconstruction logic for display and export.
4. Do not simulate pagination by changing only `topN` without an offset or cursor.
5. Do not fetch every aggregate label merely to calculate a total group count.
6. Do not show rows or chart leaves that have no detail destination.
7. Do not hide supplemental-dataset behavior behind an empty or ambiguous toggle.
8. Do not assume all values belong to the same currency or analytical grain.
9. Do not treat an award as proof of a contract.
10. Do not present anomaly indicators as findings of wrongdoing.
11. Do not represent multi-value URL state with an ambiguous comma-separated format.
12. Do not add future years to controls unless the API accepts them and data coverage explains their meaning.

## Branch-based experiment plan

### Why use branches

These improvements affect shared query semantics. Testing them on isolated branches allows the team to compare behavior and performance without destabilizing the current researcher and validation workflows.

Avoid one long-lived "all improvements" branch. Use small vertical slices that include API, UI, fixtures, and benchmarks together.

### Suggested branch order

#### Branch A: Query contract foundation

```text
experiment/investigation-query-v1
```

Deliver:

- versioned query schema;
- normalizer and hash;
- compatibility adapter for existing search;
- fixture compiler tests; and
- no major UI redesign.

Merge criterion: current search results remain equivalent for supported existing filters.

#### Branch B: Shareable filter workspace

```text
experiment/research-filter-workspace
```

Branch from the merged query foundation. Deliver:

- URL state;
- active-population bar;
- advanced filter drawer shell;
- restore/share/browser-history tests.

Merge criterion: shared URLs reproduce the same normalized query and count.

#### Branch C: Facets and entity selection

```text
experiment/facets-and-entity-ids
```

Deliver:

- contextual facet endpoint;
- identifier-backed buyer/supplier typeahead;
- exact entity constraints;
- latency and memory benchmarks.

Merge criterion: facet counts and entity selections reconcile with record queries.

#### Branch D: Investigation analytics

```text
experiment/investigation-analytics
```

Deliver:

- aggregate API;
- summary and ranked tables;
- outcome/time views;
- click-through to contributing records;
- aggregate export metadata.

Merge criterion: all displayed aggregates pass cross-surface reconciliation tests.

#### Branch E: Entity portfolios

```text
experiment/entity-portfolios-v2
```

Deliver:

- buyer and supplier portfolio slices;
- related-entity intersections;
- identity-scope controls;
- shared-award counting rules.

Merge criterion: every entity metric declares grain and identity scope, and drill-downs reproduce its count.

### Suggested local commands

Create only the branch currently being tested:

```powershell
git switch master
git pull --ff-only
git switch -c experiment/investigation-query-v1
```

Run the existing verification suite before and after the experiment:

```powershell
cd PARQUET_VIEWER
python -m unittest discover -s backend\tests -v
cd frontend\app
npm run build
```

With the local viewer running, exercise the full path:

```powershell
cd PARQUET_VIEWER
python scripts\smoke_e2e.py
python scripts\benchmark.py --json docs\benchmark_results.json
```

Do not use the existing production-sized cache as proof that a new index builds correctly. Test both:

1. a warm run against an existing valid cache; and
2. a cold rebuild after moving or deleting only the disposable `PARQUET_VIEWER/.cache/` directory.

Never modify or delete the authoritative source Parquets during this test.

### Feature-flag recommendation

During experiments, keep the current path available and place new behavior behind local configuration such as:

```json
{
  "features": {
    "investigation_query_v1": false,
    "contextual_facets": false,
    "investigation_analytics": false,
    "entity_portfolios_v2": false
  }
}
```

The old and experimental paths should consume the same fixture inputs. This makes differences measurable instead of subjective.

## Suggested first experiment

Start with **Canonical researcher query object** plus **shareable researcher search state**.

This first branch is intentionally unglamorous. It does not require a large new analytical projection, and it creates the contract needed for every subsequent feature. It also directly fixes the largest architectural risk inherited from the predecessor: different parts of the interface reconstructing the "same" filters differently.

A useful first demonstration would be:

1. Search for `school building`.
2. Select outcomes `awarded` and `contracted`.
3. Select closing years 2023-2025.
4. Open a process.
5. Copy the URL.
6. Open it in a clean browser session.
7. Confirm the same normalized query, count, filters, selected process, and dataset fingerprint.
8. Export the population and confirm its metadata carries the same query hash.

Once that works, contextual facets and entity-backed filters can be added with much lower risk.

## Definition of done for every improvement

An improvement is not complete until it satisfies all applicable conditions:

- It preserves source traceability.
- It names population and grain.
- It uses stable entity IDs when available.
- It preserves filters through drill-down and export.
- It has a shareable or deliberately non-shareable state policy.
- It exposes missing/unknown/ambiguous values honestly.
- It has deterministic fixture tests.
- It has a browser-level workflow test.
- It has cold and warm latency measurements.
- It documents new cache size and build-memory cost.
- It invalidates disposable data when authoritative inputs or rule versions change.
- It remains usable when a disposable projection is absent or rebuilding.
- It cannot write to the source datasets.

## Expected product result

The viewer should evolve from two adjacent tools, a simple researcher search and a technical table explorer, into one coherent investigation workspace:

```text
Find a procurement, item, buyer, or supplier
  -> define a visible population
  -> inspect records
  -> summarize that same population
  -> click any group to see its evidence
  -> follow a process through every lifecycle stage
  -> trace any value to source rows
  -> share or export the exact query reproducibly
```

This keeps the accessibility and entity exploration that worked in the Awards Dashboard while using the current viewer's more complete lifecycle data, explicit relationships, versioned derivations, and source provenance.
