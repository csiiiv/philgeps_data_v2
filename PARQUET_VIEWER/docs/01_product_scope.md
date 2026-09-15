# Product scope

## Objective

Build a local validation workbench for the split PhilGEPS Parquets. A reviewer
should be able to start with a process, release, tender, item, award, contract,
party, quality issue, or breadcrumb and navigate to all related records and
their original source observations.

## Primary users

- Dataset maintainers validating ETL behavior
- Analysts checking suspicious or incomplete records
- Developers testing mapping and identity-rule changes
- Reviewers who need source evidence without writing DuckDB SQL

## MVP outcomes

The first usable version must support:

1. A catalog showing every Parquet, row count, size, schema, and key contract.
2. Paginated table browsing with typed filters and explicit column selection.
3. Exact lookup by internal ID or compact breadcrumb.
4. A process page showing releases and all lifecycle child tables.
5. Side-by-side comparison for the 692 multi-release processes.
6. A data-quality issue queue with links to affected records and source rows.
7. A source panel showing the complete cleaned/normalized observation,
   filename, physical row, manifest entry, and download URL.
8. Party-name, resolution-candidate, provisional canonical-party, and alias
   review pages.
9. Export of the currently filtered result only, with an explicit row limit.

## Non-goals for the MVP

- Editing Parquet files or correcting source data in place
- Publishing OCDS JSON
- A public internet deployment
- An unrestricted SQL console
- Loading entire tables into browser memory
- Treating provisional party clusters as verified organizations
- Hiding incomplete or publication-blocking records

## Product principles

- Read-only by construction.
- Source evidence stays one click away.
- Null, missing, ambiguous, and conflicting data remain visible.
- Every inferred value displays its method and rule version.
- Default screens are bounded and responsive on the full dataset.
- The interface distinguishes observed, normalized, inferred, preferred, and
  provisional values visually and textually.

## Success criteria

- A reviewer can resolve a breadcrumb and see the complete observation in
  under two seconds on a warm local cache.
- Exact ID lookups do not scan unrelated browser data.
- Every relationship shown by the UI can be reproduced with a documented join.
- The viewer never writes to source or ETL output paths.
- Large-result requests are rejected or narrowed before execution.
