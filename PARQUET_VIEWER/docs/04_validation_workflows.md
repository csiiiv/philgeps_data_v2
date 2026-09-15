# Validation workflows

## 1. Process inspection

Start from a process ID, bid reference, solicitation number, or exact title.
Show:

- base process identity and quality flags;
- preferred release and selection basis;
- all release states in chronological order;
- tender, items, awards, contracts, parties, and relationship assertions; and
- counts that reconcile with the underlying tables.

For multi-release processes, the reviewer can compare any two releases field by
field. The display distinguishes added, removed, changed, and unchanged values.

## 2. Relationship validation

Contract and supplier links display their explicit status:

- `matched`: navigate to the target record;
- `missing`: show the attempted source key and related quality issue; or
- `ambiguous`: show every candidate and do not select one silently.

The same screen exposes the exact source rows supporting the assertion.

## 3. Source breadcrumb resolution

Accept compact breadcrumbs such as:

```text
<source_file_id>:<source_row_number>
```

The source drawer displays:

- source file ID, worksheet, and physical row;
- manifest filename, normalized filename, and source URL;
- the complete normalized observation;
- the complete cleaned observation;
- type-aware formatting for dates, decimals, arrays, and nulls; and
- every derived record linked to that source row.

URLs are breadcrumbs to the source distribution, not claims that the remote
file is permanently available or unchanged.

## 4. Quality-issue review

Filter by issue code, category, severity, publication-blocking status, record
type, year, source file, or relationship status. Opening an issue shows:

- affected derived record;
- observed value and rule explanation;
- rule version;
- source evidence; and
- related issues for the same release or breadcrumb.

The MVP is read-only. Review notes and issue dispositions can be designed later
as a separate overlay, never as changes to ETL outputs.

## 5. Party-resolution review

Provide three connected views:

1. Name forms and their punctuation/legal-suffix keys.
2. Candidate groups with location, role, and organization-context evidence.
3. Provisional canonical clusters and supported aliases.

Warnings must state that provisional canonical IDs are analytical identifiers,
not registered organization identifiers. Unsupported mentions in otherwise
eligible groups remain visible as unresolved.

## 6. Compiled-release review

Show the preferred release next to all alternates, including:

- selection rule and rule version;
- dates and date bases;
- lifecycle coverage;
- source-file and observation counts;
- content hashes; and
- source breadcrumbs.

The reviewer can switch the displayed lifecycle tables to an alternate release
without changing the stored preference.

## 7. Table-level profiling

For each allowlisted column, provide bounded metrics:

- logical type;
- null and non-null counts;
- approximate distinct count by default;
- exact distinct count only on explicit request;
- min/max for numeric and temporal fields; and
- top values with configurable limits.

Expensive scans should show an estimate and require confirmation in the UI.
