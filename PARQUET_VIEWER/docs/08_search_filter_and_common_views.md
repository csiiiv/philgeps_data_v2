# Search, filtering, and common views

## Search architecture

Search uses two layers:

1. The Parquets remain the authoritative data and serve record details, exact
   IDs, relationships, and source evidence.
2. A disposable `.cache/viewer.duckdb` database may contain compact search and
   facet projections for interactive discovery.

The cache is not another normalization layer. It stores only derived lookup
fields, filter dimensions, aggregates, and record IDs. Every search result
opens authoritative values from the split Parquets.

Direct substring searches such as `ILIKE '%term%'` over multi-gigabyte files
must not execute on every keystroke. Exact and prefix predicates can query
Parquet directly; broad text search and common facets use measured,
rebuildable projections.

## Search projections

### `process_search`

One row per contracting process, using the preferred release:

- process and preferred-release IDs;
- bid reference and solicitation number;
- tender title;
- procuring entity and client agency;
- relevant publication, award, and contract dates;
- method, category, and status;
- tender, award, and contract values;
- lifecycle flags and child counts;
- quality-issue and publication-blocking counts; and
- source period and source-file count.

The first version should omit expensive aggregates until the core projection
is benchmarked. Fields can be added without changing authoritative Parquets.

### `party_name_search`, `canonical_party_search`, and `party_alias_search`

Party search uses separate physical grains rather than mixing name forms and
canonical clusters in one table. A union endpoint returns an explicit
`result_type`. Fields include:

- exact observed and preferred names;
- punctuation and legal-suffix keys;
- role family and normalized location;
- mention, process, award, and contract counts;
- candidate evidence and provisional identity status; and
- unresolved alias counts.

### `source_search`

One row per source file with its manifest metadata, date coverage, observation
count, schema, and issue counts. Complete observations remain in the normalized
and cleaned Parquets.

### Quality-issue summaries

Pre-aggregate common dimensions such as issue code, severity,
publication-blocking status, record type, source file, and year. This keeps
facets responsive without repeatedly grouping 13.9 million issue records.

## Search modes

### Identifier routing

The global search box recognizes internal prefixes and breadcrumbs:

- process, release, tender, item, award, contract, party, issue, candidate, and
  canonical-party IDs; and
- `<source_file_id>:<source_row_number>` breadcrumbs.

Recognized identifiers navigate directly. They do not return a broad text
search result list.

### Structured search

Examples include exact bid reference, solicitation prefix, contract number,
award reference, party name key, source file, status, date range, and monetary
range. These compile to typed, parameterized predicates.

### Text search

Selected fields include tender title, item description, supplier name,
procuring entity, award title, and contract number. Results label the match
method:

- exact source spelling;
- punctuation-normalized exact match;
- prefix match;
- token/text match; or
- provisional party alias.

Fuzzy matching is an explicit, non-default operation because organization-name
similarity can create false identity claims.

## Faceted filtering

The viewer uses AND between different facets and OR among selected values in
one facet. Active filters appear as removable chips and are encoded in the URL.

Core filter families are:

- bid, award, contract, and release date ranges;
- tender-only, awarded, contracted, and incomplete lifecycle states;
- source and mapped statuses;
- procurement method, category, classification, and funding source;
- tender, item, award, and contract value ranges;
- procuring entity, client agency, supplier, and party role;
- region, province, and city or municipality;
- issue code, severity, publication gate, and quality flags;
- matched, missing, and ambiguous relationship status;
- source file, source period, worksheet, and observation coverage;
- party candidate, corroborated, divergent, provisional, or unresolved status;
  and
- single/multiple releases, date ties, and content changes.

Missing and unknown values are first-class filter values. Filters must support
questions such as “contracts without an award reference” without requiring SQL.

All lifecycle searches also declare `preferred_state` or
`all_observed_states`. The latter uses release-object grain and can contain the
same logical object in multiple historical states.

## Interaction patterns

- A master-detail layout keeps results visible beside the selected record.
- Count tiles and facet counts drill through to the exact filtered rows.
- Compare mode displays added, removed, changed, and unchanged fields.
- Raw, normalized, cleaned, and derived values can be viewed side by side.
- Column presets cover lifecycle, monetary, quality, and provenance review.
- URLs preserve filters, sorts, columns, selected records, and comparisons.
- Every count names its grain: process, release, observation, party mention, or
  relationship assertion.
- Inferred, provisional, ambiguous, missing, and publication-blocking values
  use explicit badges and explanations.
- A source drawer is reachable from every derived record.

## Common validation views

### Validation overview

Show table health, row counts, source coverage, relationship reconciliation,
blocking issues, schema/build versions, manifest coverage, and validation
artifacts.

### Process explorer

Show base identity, preferred and alternate releases, tender, items, awards,
contracts, parties, issues, and supporting source rows. Allow switching the
displayed lifecycle state without changing the stored preference.

### Tender review

Useful saved views include tenders without items, publication dates or awards;
closed tenders without awards; budgets below award values; and unresolved
method mappings.

### Award review

Useful saved views include awards without suppliers, items, values or
contracts; multi-supplier awards; ambiguous parties; and unresolved status
mappings.

### Contract review

Useful saved views include contracts without matched awards, missing contract
numbers, inconsistent periods or durations, value differences, and missing
supplier evidence.

### Party and supplier explorer

Show observed spellings, match keys, roles, locations, awards, contracts,
candidate groups, provisional clusters, unresolved mentions, and source
evidence. Saved views include legal-suffix variants, multi-location names,
mixed role families, divergent candidates, and candidates without location.

### Quality-issue queue

Behave like a read-only issue tracker with filters, affected records, rule
versions, observed values, source evidence, related issues, and next/previous
navigation within the filtered queue.

### Multi-release comparison

Show the release timeline, lifecycle changes, field differences, source
coverage, content hashes, preferred-selection explanation, and source rows for
both states.

### Source-file explorer

Show manifest and schema information, row and date coverage, null profiles,
quality issues, header anomalies, sample breadcrumbs, and derived-record
coverage.

## Query-cost behavior

The UI classifies operations as instant, fast, moderate, or expensive. Exact
IDs and breadcrumbs should be instant; cache filters and facets fast; selective
Parquet queries moderate; and broad text scans, exact distinct counts, large
aggregations, and exports expensive.

Expensive operations require an explicit Apply action, expose cancellation,
and never run per keystroke. Completed aggregates can be cached using Parquet
file metadata and rule versions as the invalidation key.

## Saved views

Reusable views are versioned JSON configuration rather than hardcoded pages.
Each definition contains dataset, filters, projection, sort, grain label, and
warning text. This allows reviewers to add validation questions without adding
new API endpoints.
