# PhilGEPS Awards Dashboard: Search, Filters, and Drill-Down Analysis

## Document status

- **System analyzed:** [`csiiiv/philgeps-awards-dashboard`](https://github.com/csiiiv/philgeps-awards-dashboard)
- **Repository snapshot:** [`36f4368de75af76ecf87d5f115655833273cdecb`](https://github.com/csiiiv/philgeps-awards-dashboard/tree/36f4368de75af76ecf87d5f115655833273cdecb), dated 2025-12-02
- **Analysis method:** Static trace of the React frontend, service layer, Django REST endpoints, serializers, and DuckDB/Parquet query implementation
- **Primary focus:** Search behavior, filter composition, state persistence, aggregation, and progressive drill-down
- **Important scope note:** This predecessor is an **award/contract explorer**. It is not a full procurement-lifecycle browser. Its principal fact source is a flattened awards dataset, so its concepts and navigation start from contracts rather than from releases, tenders, lots, bids, awards, and contracts as separate related records.

## Executive summary

The application exposes four related ways to investigate award records:

1. **Advanced Search** finds individual contract/award rows using composable filter chips.
2. **Data Explorer** ranks entities such as contractors, procuring organizations, areas, and business categories.
3. **Analytics** reuses the current search population for summaries, charts, clustering, and anomaly-oriented views.
4. **Drill-downs** move from an aggregate entity to its contracts, related entities, and intersections between two entities.

The strongest aspect of the design is that most views share one filter vocabulary. A search for an organization, area, keyword, date range, and amount range can become an analytics view without the user rebuilding the query. Entity rows then become navigation points into narrower slices of that same population.

The core Boolean model is:

```text
AND between filter groups
OR between chips in the same group
AND between terms separated by && inside one chip
```

For example:

```text
Contractors: ["ABC Builders", "XYZ Construction"]
Area:        ["Cebu"]
Keywords:    ["road && bridge", "school"]
```

is interpreted as:

```text
(contractor contains "ABC Builders" OR contractor contains "XYZ Construction")
AND area contains "Cebu"
AND (
  (search_text contains "road" AND search_text contains "bridge")
  OR search_text contains "school"
)
```

All text comparisons in the final search are case-insensitive substring matches. Selecting an autocomplete suggestion does **not** turn the final filter into an exact identifier match.

## 1. Application surfaces

The React application defines three investigation routes relevant to this analysis:

- `/` - Data Explorer
- `/advanced-search` - Advanced Search
- `/treemap` - hierarchical visual exploration

These are complementary rather than independent products:

- Advanced Search is **record-first**.
- Data Explorer is **entity-first**.
- Analytics is **population-first**, summarizing the active result set.
- The treemap is **path-first**, adding one dimension at every level.

The important architectural idea is that each surface eventually resolves to the same small family of backend operations:

```text
filter options/autocomplete
        |
        v
chip-based contract search ----------> individual award rows
        |
        +-----------------------------> CSV export
        |
        v
chip-based aggregation --------------> summaries, trends, top entities
        |
        v
paginated aggregation ---------------> ranked entity tables
```

## 2. Data and query foundation

### 2.1 Primary data shape

The backend queries Parquet directly through DuckDB. Its central source is the all-time award fact file, with yearly files available as a fallback. An optional flood-control Parquet file can be appended to that input set.

The searchable and groupable columns used by the interface are primarily:

- `contract_no` / `contract_number`
- `reference_id`
- `award_title`
- `notice_title`
- `awardee_name`
- `organization_name`
- `area_of_delivery`
- `business_category`
- `contract_amount`
- `award_date`
- `search_text`

The design assumes one flat fact relation is sufficient for both contract results and entity analytics. That makes cross-filtering straightforward, but it also explains why the old browser cannot naturally expose every PhilGEPS lifecycle object or one-to-many relationship.

### 2.2 Query execution

The Django service builds DuckDB SQL over `read_parquet(...)`. Search and aggregation requests use the same condition builder, which is valuable because totals and charts generally describe the same population as the result table.

The process is roughly:

1. Choose the main all-time file or yearly fallback files.
2. Add the optional supplemental flood-control file when requested.
3. Convert each chip group to SQL conditions.
4. combine groups with `AND`.
5. Count matching rows for pagination or summary statistics.
6. Fetch either records, grouped entities, or time-series aggregates.
7. Cache successful endpoint responses using an MD5 of the request body.

The code uses a 600-second cache duration, despite some comments referring to five minutes.

## 3. Advanced Search

### 3.1 User workflow

The Advanced Search page follows this sequence:

1. Load distinct filter options for contractors, areas, organizations, and business categories.
2. Let the user add zero or more chips to each filter group.
3. Optionally add keyword chips, a time range, and a contract-value range.
4. Validate custom dates when the user presses Search.
5. Reset pagination to page 1.
6. Request contract rows and aggregates concurrently.
7. Render the result table and make Analytics available for the same filter population.
8. Encode the active query in the URL hash for sharing and restoration.

Search is explicit: editing a control changes local filter state, while the Search action applies it. Pagination and sorting issue subsequent searches with the current filters.

### 3.2 Available filters

#### Contractors

- A searchable multi-select field.
- Each selected or typed value becomes a removable chip.
- Multiple contractor chips are OR-ed.
- Final matching is against `awardee_name` using case-insensitive substring search.

#### Procuring organizations

- A searchable multi-select field.
- Multiple organization chips are OR-ed.
- Final matching is against non-null `organization_name` using case-insensitive substring search.

#### Areas of delivery

- A searchable multi-select field.
- Multiple area chips are OR-ed.
- Final matching is against non-null `area_of_delivery` using case-insensitive substring search.

#### Business categories

- A searchable multi-select field.
- Multiple category chips are OR-ed.
- Final matching is against `business_category` using case-insensitive substring search.

#### Keywords

- Free text is added as a chip with Enter or the Add action.
- Each chip searches the precomputed `search_text` field.
- Multiple keyword chips are OR-ed.
- `&&` inside a keyword chip creates an AND expression.
- There is no visible field-level choice for which source columns contributed to a keyword hit.

#### Time range

The user can choose:

- all dates;
- one calendar year;
- one quarter within a year; or
- a custom inclusive start and end date.

Year and quarter filters are calculated from `award_date`. Custom dates are validated in the frontend and then applied with inclusive `>=` and `<=` conditions in the backend.

The backend accepts an array of time ranges and ORs them together. The current Advanced Search UI normally produces one active time-range object.

#### Contract value

- Optional minimum and maximum inputs.
- Bounds are inclusive.
- The backend supports a minimum only, maximum only, or both.
- The Advanced Search control visually caps its expected range at PHP 10 billion.
- Some service calls supply a broad default of PHP 0 to PHP 1 trillion when no explicit value range is present. Consequently, the practical definition of "all values" may still exclude negative values or values above that ceiling.

#### Flood-control inclusion

The state, request field, URL field, preset field, and backend behavior all exist. However, the Advanced Search component renders an empty styled container where the toggle should be. The Data Explorer likewise renders an empty label. In this snapshot, users do not receive a functional visible toggle even though the plumbing is present.

This flag is also easy to misunderstand. It primarily controls whether a supplemental flood-control Parquet dataset is appended to the normal award files; it is not simply a subject keyword filter over the main dataset.

### 3.3 Filter composition rules

The backend condition builder applies the following grammar:

```text
query := category_group
         AND contractor_group
         AND organization_group
         AND area_group
         AND keyword_group
         AND time_group
         AND value_group

group := chip OR chip OR chip ...

chip := term AND term AND term ...
        where terms are separated with &&
```

Empty groups are omitted. Blank chips and blank `&&` terms are ignored.

Every entity and keyword term becomes a SQL expression equivalent to:

```sql
LOWER(column_name) LIKE LOWER('%term%')
```

This has several consequences:

- A selected entity name is not an equality match.
- A short name may match longer, unrelated names containing the same text.
- `%` and `_` entered by a user retain SQL `LIKE` wildcard meaning because the helper escapes quotes and backslashes but not those wildcard characters.
- The system has no canonical entity identifier in its filter contract, so spelling variants remain separate choices and ambiguous names cannot be disambiguated reliably.

### 3.4 Suggestions and "exact word" mode

The reusable searchable select combines local and remote suggestions:

1. It initially receives arrays returned by `/contracts/filter-options/`.
2. As the user types, it waits 300 ms.
3. It calls the corresponding entity endpoint with `search=<text>` or `word=<text>` and `page_size=20`.
4. It merges remote results with up to 50 locally filtered options.
5. The user may select a suggestion or add the typed value directly.

The suggestion endpoints and final contract search do not use identical matching engines:

- `search=` uses normal case-insensitive containment against Django models.
- `word=` uses an exact-word-oriented lookup for suggestions.
- The resulting chip is still sent to the Parquet search as plain text and evaluated with substring `LIKE`.

Therefore, the "exact word" checkbox narrows **suggestion discovery**, not the semantics of the applied filter. A user may reasonably expect otherwise.

### 3.5 Search request sequence

The frontend translates its camelCase state to the API payload and concurrently requests:

```text
POST /api/v1/contracts/chip-search/
POST /api/v1/contracts/chip-aggregates/
```

The record request includes:

```json
{
  "contractors": [],
  "areas": [],
  "organizations": [],
  "business_categories": [],
  "keywords": [],
  "time_ranges": [],
  "value_range": { "min": 0, "max": 10000000000 },
  "page": 1,
  "page_size": 20,
  "sortBy": "contract_amount",
  "sortDirection": "desc",
  "include_flood_control": false
}
```

The aggregate request applies the same filter dimensions but returns summary and grouping data rather than contract rows.

### 3.6 Result table

The Advanced Search result table has nine columns:

1. Contract No
2. Award Title
3. Notice Title
4. Contractor
5. Organization
6. Area
7. Category
8. Amount
9. Date

All are visible by default. The column-visibility menu can hide individual columns, show all, hide all except the first, or reset to defaults. Visibility is saved to `localStorage` under `advancedSearch_columnVisibility`.

The contract-number cell falls back through `contract_number`, `contract_no`, and `reference_id`, then displays `N/A`.

Rows are display-only. Clicking a contract row does not open a record detail view, lifecycle view, or source record in this component.

### 3.7 Sorting and pagination

- Default page size: 20.
- Default sort: contract amount descending.
- Clicking a column header changes the server-side sort.
- Clicking a new column starts ascending; clicking it again toggles direction.
- Changing page size resets to page 1.
- Backend search pagination uses `LIMIT` and `OFFSET` after calculating the matching row count.
- The serializer restricts sort keys to an allowlist.

The table can sort by the visible result fields, including contract number, titles, parties, area, category, amount, and award date.

### 3.8 Search result metadata caveat

The backend constructs compatibility fields for every returned row, including a constant `award_status`, constant `created_at`, and constant `id`. These values should not be treated as genuine record-level source data. The visible table mostly avoids relying on them, but downstream reuse of the endpoint could be misleading.

## 4. Query persistence and sharing

### 4.1 URL state

Advanced Search serializes state into the URL hash. Supported keys include:

- `q` - keyword chips
- `contractors`
- `areas`
- `orgs`
- `categories`
- `dateType`
- `year`
- `quarter`
- `startDate`
- `endDate`
- `min`
- `max`
- `flood`
- `view` - search or analytics
- `tab` - analytics subview

Loading a URL with this state hydrates the controls and automatically runs the search. Hash-change handling also allows browser back/forward navigation and direct hash edits to restore a search.

The Share action copies this URL, so it captures both the data population and whether the recipient should land in Analytics and on which analytics tab.

One format weakness is that arrays are represented as comma-separated strings. Names containing commas cannot be represented unambiguously after decoding and splitting.

### 4.2 Predefined filters

The application ships a JSON collection of curated filters. Examples include:

- DPWH district offices;
- all DPWH records;
- flood-control-related terms;
- named contractors;
- pumping stations; and
- multipurpose or senior-citizen office searches.

Presets can include entity chips, keywords, dates, and the flood-control dataset flag.

Applying a preset loops over its values and adds them to the current chip arrays. It does not first replace all existing chips. This means a preset may merge with the current query, producing broader OR groups or extra AND constraints depending on what was already selected.

### 4.3 User-saved filters

Saved filters are browser-local, not account-level. The system supports:

- create;
- rename/update;
- delete;
- JSON export;
- JSON import; and
- restoration of the last-used configuration for up to 30 days.

The saved object contains filter chips, date range, the flood-control flag, timestamps, and a generated client-side identifier. Because storage is in `localStorage`, saved searches do not automatically follow a user to another browser or device.

## 5. Data Explorer

### 5.1 Purpose

The home route presents an entity ranking rather than individual contract rows. The user chooses:

- **Dimension:** contractor, organization, area, or category
- **Metric:** total contract amount, contract count, or average contract price
- **Year:** all years or a single year
- **Entity filter:** a search control for the currently selected dimension

This is useful for questions such as:

- Which contractors have the highest awarded value?
- Which organizations issued the most contracts?
- Which areas have the greatest aggregate value?
- Which categories have the highest average contract size?

### 5.2 Filter behavior

Only the entity selector matching the selected dimension is displayed. For example, `by_contractor` exposes contractor filtering rather than showing all four entity selectors at once.

The selected year becomes a yearly `time_ranges` item. The explorer also supplies a broad PHP 0 to PHP 1 trillion amount range.

The visible year list is generated for 2013 through 2027. In the analyzed backend serializer, accepted years stop at 2025. Thus 2026 and 2027 appear selectable but can fail validation in this snapshot.

### 5.3 Aggregate table

The explorer calls the paginated aggregate endpoint for the selected dimension and the broader aggregate endpoint for summaries and trends. Each row contains:

- entity label;
- contract count;
- total contract value; and
- average contract value.

The chosen metric determines the ranking emphasis. Pagination is server-backed through the paginated aggregate endpoint.

Clicking an entity row opens the Entity Drill-Down modal. This is the main bridge from a ranking to underlying evidence.

## 6. Analytics over a search population

The Advanced Search page can open an Analytics modal without losing the active filters. The modal uses the current filter set as its base population and displays the active filters as read-only chips.

### 6.1 Summary statistics

The aggregate response includes:

- matching contract count;
- total contract value; and
- average contract value.

It also includes yearly and monthly/quarterly series and top-N entity groupings.

### 6.2 Regrouping controls

Within Analytics, the user can regroup the same population by contractor, organization, area, or category and rank it by total value, count, or average. A year override provides a further temporal slice.

This is a useful interaction pattern: the search defines **which records belong**, while analytics controls define **how those records are summarized**.

### 6.3 Tables tab

- Uses the paginated aggregate endpoint.
- Displays ranked entity rows.
- Supports sorting and page-size changes.
- Opens the Entity Drill-Down modal when a row is selected.

### 6.4 Charts tab

- Shows a top-10 horizontal bar chart for the selected grouping.
- Shows time trends using the aggregate response's yearly and monthly series.
- Retains the search filters as the chart population.

### 6.5 Clustering tab

The clustering view groups contract values into ranges or threshold-based clusters. Selecting a cluster opens contracts constrained by that value interval.

This is effectively an amount-range drill-down:

```text
current search population
    + selected cluster minimum
    + selected cluster maximum
    = contracts in that cluster
```

### 6.6 Miscellaneous analysis tab

The application includes exploratory checks for:

- Benford's Law;
- rounding and trailing-zero patterns;
- deviant subsets; and
- relative size factors.

These are screening signals, not findings of wrongdoing. They are best understood as ways to identify populations that merit inspection. Any future interface should state the population, expected baseline, sample-size limitations, and method beside each signal.

### 6.7 Analytics deep links

The URL hash records whether Analytics is open and which tab is active. A shared link can therefore restore not just the filters but the analytical context in which the sender was viewing them.

## 7. Entity Drill-Down

### 7.1 Opening a drill-down

An entity row in Data Explorer or Analytics passes these values to the modal:

- entity type;
- entity label;
- current filter context; and
- display mode.

The modal replaces the current values for the selected entity's dimension with the clicked label while preserving the other filter groups.

Example:

```text
Current population:
  area = Cebu
  keyword = bridge

Clicked entity:
  contractor = ABC Builders

Drill-down population:
  area contains Cebu
  AND search_text contains bridge
  AND contractor contains ABC Builders
```

This replacement behavior prevents an existing contractor OR-list from diluting a contractor row click. Other dimensions continue to constrain the drill-down.

### 7.2 Contracts tab

The Contracts tab contains:

- a paginated contract table;
- sortable contract columns;
- award and notice titles;
- amount and award date;
- contractor, organization, category, and area; and
- quarterly/yearly contract-value trends derived from an aggregate request.

The trend is calculated over the full entity-filtered population, not merely the contracts visible on the current page.

### 7.3 Related-entity tabs

The modal offers tabs for the other dimensions while hiding the selected entity's own dimension. For a contractor, it can show that contractor's:

- procuring organizations;
- areas of delivery; and
- business categories.

For every related entity it displays:

- label;
- total value;
- contract count; and
- average contract value.

This supports questions such as "Which agencies award contracts to this supplier?" or "Which contractors receive awards from this organization?"

### 7.4 Nested contracts

Clicking a related entity opens a nested contract modal. The nested request combines the parent and child entity filters with the existing context.

Example:

```text
Parent: Organization X
Child:  Contractor Y

Result: contracts matching Organization X AND Contractor Y,
        plus any area, category, keyword, time, or value constraints
        inherited from the original search.
```

This two-entity intersection is the most useful drill-down behavior in the predecessor. It converts an aggregate relationship into the underlying contract rows without requiring the user to rebuild the filters manually.

### 7.5 Related-entity pagination defect

The related-entity tabs present pagination controls, but their fetch function calls the non-paginated `chip-aggregates` endpoint with `topN = pageSize`. It accepts `pageIndex` in the frontend function but does not send an offset or page to the backend.

As a result:

- later pages can repeat the same first top-N rows;
- sorting is performed only over the fetched top-N rows;
- a separate `topN = 999999` aggregate request is used to calculate entity counts; and
- large-cardinality drill-downs can be unnecessarily expensive.

The intended behavior is clear, but this implementation should not be copied. Related tabs should use the real paginated aggregate endpoint.

### 7.6 Drill-down export scope defect

The Contracts-tab export reconstructs a new filter object containing the selected entity and time ranges, while omitting some inherited parent filters, keywords, and value bounds. It also hardcodes `include_flood_control` to false.

The related-entity export preserves more of the current context but still hardcodes that flag. The downloaded dataset can therefore differ from what the modal shows. A robust implementation should create one canonical query object and reuse it for display, totals, drill-down, and export.

## 8. Treemap drill-down

### 8.1 Hierarchies

The treemap defines ten selectable dimension paths:

1. Area -> Agency -> Contractor -> Contracts
2. Area -> Category -> Contractor -> Contracts
3. Area -> Contractor -> Contracts
4. Contractor -> Area -> Agency -> Contracts
5. Contractor -> Area -> Contracts
6. Contractor -> Agency -> Contracts
7. Category -> Area -> Contractor -> Contracts
8. Category -> Contractor -> Contracts
9. Category -> Agency -> Contracts
10. Agency -> Contractor -> Contracts

### 8.2 Downward navigation

At each entity level, the client requests the top 20 entities for the next dimension. Clicking a rectangle:

1. records the selected label in the path;
2. adds it as a filter for that dimension;
3. preserves filters from earlier levels; and
4. requests the next grouping.

Although a rectangle represents one aggregate label, the backend applies the label as a substring filter rather than exact equality.

### 8.3 Breadcrumb navigation

The current path is shown as breadcrumbs. Drilling upward removes later selections, reconstructs the filters represented by the remaining path, and reloads the appropriate aggregate level.

This is a sound visual navigation pattern because the breadcrumb doubles as an explanation of the active query.

### 8.4 Final contract level

At the leaf, the treemap calls contract search with all accumulated entity filters. However:

- it does not provide explicit pagination parameters, so the search defaults to the first 20 contracts;
- there is no evident load-more or page navigation in this surface; and
- clicking a final contract only reaches a logging/TODO handler, not a record detail view.

The hierarchy exploration is functional, but the evidence trail stops short at the last step.

## 9. Backend endpoint map

All paths below are actions on the Django `contracts` viewset under `/api/v1/contracts/`.

### `POST chip-search/`

- Validates chip filters, page, page size, and sort.
- Runs the DuckDB record query.
- Returns rows and pagination metadata.
- Caches successful responses for 600 seconds.

### `POST chip-aggregates/`

- Applies the same filter grammar.
- Returns summary values, year/month series, and top-N groupings for every entity dimension.
- Uses `topN` from the raw request in addition to serializer fields.
- Caches successful responses for 600 seconds.

### `POST chip-aggregates-paginated/`

- Groups by one requested dimension.
- Returns total entity count and one page of ranked entities.
- Supports server-side entity sorting.
- Powers the main entity tables in Data Explorer and Analytics.

### `GET filter-options/`

- Scans distinct values for the four entity dimensions.
- Returns arrays used as the initial local suggestion pool.
- Caches the option response.

### Entity suggestion resources

- `GET /api/v1/contractors/`
- `GET /api/v1/organizations/`
- `GET /api/v1/business-categories/`
- `GET /api/v1/areas-of-delivery/`

These power remote autocomplete using `search` or `word` query parameters.

### Export operations

The application has an estimate/initialization step and streaming CSV export paths for contract rows and aggregates. Streaming searches intentionally omit ordering because sorting a large export is expensive; the UI assumes the user can sort the downloaded file later.

## 10. State transitions by interaction

### Press Search

```text
validate custom range
-> reset page to 1
-> build canonical-looking request payload
-> fetch records and aggregates concurrently
-> update result and summary state
-> update URL hash
```

### Change result page

```text
retain filters and sort
-> change page
-> rerun record search
```

### Change result sort

```text
retain filters
-> choose column and direction
-> rerun record search
```

### Open Analytics

```text
retain current search population
-> open modal
-> set URL view=analytics
-> fetch/render selected aggregate presentation
```

### Click aggregate entity

```text
retain all other filter groups
-> replace selected dimension with clicked label
-> fetch entity contracts and trends
-> expose related dimensions
```

### Click related entity

```text
retain original filters
-> add parent entity constraint
-> add related entity constraint
-> fetch intersection contracts
```

### Click treemap rectangle

```text
append selected dimension/label to path
-> append corresponding filter
-> request next dimension
-> update breadcrumb
```

## 11. What works especially well

### 11.1 One filter vocabulary across search and analytics

The same contractor, organization, area, category, keyword, time, and value concepts are reused throughout the app. This makes "analyze these results" feel like a continuation of search rather than a new workflow.

### 11.2 Chips make query composition visible

Users can see and remove individual values, clear one group, or clear the whole query. This is substantially easier to audit than a long conventional form whose values disappear into dropdowns.

### 11.3 `&&` adds useful expressiveness without a full query language

A chip can require multiple terms while several chips remain alternatives. It offers a compact middle ground between simple keyword search and a complex Boolean-query builder.

### 11.4 Aggregate rows lead back to evidence

The entity modal and nested contract modal make summaries actionable. Rankings are not terminal visualizations; they can reveal the contract rows contributing to them.

### 11.5 Search state is portable

The URL stores filters, dates, amount bounds, analytics view, and analytics tab. This supports collaboration and reproducibility much better than component-only state.

### 11.6 Personal and curated searches reduce repetitive work

Predefined filters support common investigative entry points, while browser-saved filters let users preserve their own recurring questions.

## 12. Important implementation limitations

These are observed behaviors in the analyzed snapshot, not merely hypothetical concerns.

1. **Substring matching masquerades as entity selection.** Autocomplete labels are sent back as text and matched with `%value%`; there are no stable entity IDs or exact-match semantics.
2. **"Exact word" applies only to autocomplete.** It does not change the final record query.
3. **Visible flood-control controls are empty.** State and backend support exist, but the rendered controls contain no input.
4. **Flood-control semantics vary by endpoint.** The primary meaning is inclusion of an extra dataset; at least one aggregate path also contains a name-based exclusion, so results may not be perfectly consistent.
5. **Related-entity pagination does not offset.** Later pages may repeat the first top-N entities.
6. **Related-entity counts require an enormous top-N request.** This can be expensive and duplicates work that the paginated aggregate endpoint already knows how to do.
7. **Drill-down exports can diverge from the visible population.** Some inherited filters are dropped and flood-control inclusion is forced off.
8. **Preset application merges rather than replaces.** This can produce an unexpected hybrid query.
9. **Comma-separated URL arrays are ambiguous.** Entity labels containing commas cannot round-trip faithfully.
10. **Year options and backend validation disagree.** The Data Explorer exposes 2026-2027 while the serializer accepts only through 2025 in this snapshot.
11. **SQL `LIKE` wildcards remain active.** `%` and `_` inside user input have special matching behavior.
12. **SQL is assembled by interpolation.** Quotes are escaped, but parameterized conditions would be clearer and safer.
13. **Synthetic response metadata looks real.** Constant status, date, and ID fields can be mistaken for source values.
14. **Treemap leaves stop at 20 records.** There is no complete final-level pagination.
15. **Contract rows have no true detail destination.** The main table and treemap do not lead to a complete procurement record.
16. **The model is award-centric.** Search and drill-down cannot naturally explain planning, tender, lot, bid, award, contract, and implementation relationships.

## 13. Relevance to the current Parquet viewer

The predecessor provides a useful interaction model, while the current viewer's broader and better-structured datasets can supply a much stronger data model beneath it.

### Keep the interaction concepts

- Filter chips with visible Boolean behavior
- Multiple entity filters combined across dimensions
- `&&` or an equivalent explicit "all terms" mode
- Search-to-analytics continuity
- Clickable aggregate rows
- Parent-plus-related-entity intersections
- URL-shareable query state
- Saved and curated filter sets
- Configurable result columns
- Export based on the exact visible population
- Breadcrumbs for hierarchical exploration

### Improve them using structured data

- Filter entities by canonical IDs while displaying names.
- Let users choose exact, contains, starts-with, and normalized-name matching explicitly.
- Search specific lifecycle entities and fields rather than a single opaque `search_text` column.
- Open a real procurement detail page from every result or visualization.
- Preserve the lineage from planning and tender through bids, awards, contracts, and implementation.
- Show counts at a declared grain, such as releases, opportunities, lots, awards, contracts, items, or suppliers.
- Generate facets and counts from the exact active query.
- Use cursor or keyset pagination for very large result sets where appropriate.
- Store one canonical query object and pass it unchanged to table, aggregate, drill-down, share, and export operations.
- Make all drill-down labels exact constraints backed by identifiers, not substring searches.
- Annotate analytics with source coverage, null rates, deduplication rules, currency assumptions, and population definitions.

The central lesson is worth retaining: **a result should always be able to become a filter, an aggregate should always lead to its contributing records, and the active population should remain visible and shareable throughout the investigation.** The current structured datasets make it possible to extend that principle beyond awards to the complete PhilGEPS procurement lifecycle.

## 14. Source map

The following files are the main evidence for this analysis:

### Frontend navigation and page orchestration

- [`frontend/src/App.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/App.tsx)
- [`frontend/src/components/features/advanced-search/AdvancedSearch.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/AdvancedSearch.tsx)
- [`frontend/src/components/features/data-explorer/DataExplorer.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/data-explorer/DataExplorer.tsx)

### Filters, results, and persistence

- [`AdvancedSearchFilters.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/components/AdvancedSearchFilters.tsx)
- [`SearchableSelect.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/SearchableSelect.tsx)
- [`SearchResults.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/SearchResults.tsx)
- [`useAdvancedSearchFilters.ts`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/hooks/advanced-search/useAdvancedSearchFilters.ts)
- [`useAdvancedSearchPagination.ts`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/hooks/advanced-search/useAdvancedSearchPagination.ts)
- [`urlState.ts`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/utils/urlState.ts)
- [`filterPersistence.ts`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/utils/filterPersistence.ts)

### Analytics and drill-down

- [`AnalyticsModal.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/AnalyticsModal.tsx)
- [`EntityDrillDownModal.tsx`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/advanced-search/EntityDrillDownModal.tsx)
- [`frontend/src/components/features/treemap`](https://github.com/csiiiv/philgeps-awards-dashboard/tree/36f4368de75af76ecf87d5f115655833273cdecb/frontend/src/components/features/treemap)

### API and DuckDB query behavior

- [`backend/django/contracts/views.py`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/backend/django/contracts/views.py)
- [`backend/django/contracts/serializers.py`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/backend/django/contracts/serializers.py)
- [`backend/django/contracts/parquet_search.py`](https://github.com/csiiiv/philgeps-awards-dashboard/blob/36f4368de75af76ecf87d5f115655833273cdecb/backend/django/contracts/parquet_search.py)
