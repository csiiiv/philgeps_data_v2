# Data catalog

## OCDS-aligned outputs

Counts and sizes were read from the current Parquet metadata on 2026-09-13.

| Dataset | Rows | Size | Viewer role |
|---|---:|---:|---|
| `contracting_processes` | 10,653,228 | 1.16 GB | Stable process identity and base release pointers |
| `releases` | 10,653,920 | 1.23 GB | Observed release states and lifecycle evidence |
| `compiled_processes` | 10,653,228 | 780.6 MB | Preferred-release join index |
| `process_release_history` | 1,384 | 136 KB | Ordered states for multi-release processes |
| `tenders` | 10,653,919 | 1.29 GB | Tender-level values |
| `tender_items` | 8,878,036 | 771.5 MB | Tender items |
| `awards` | 4,600,601 | 411.0 MB | Awards |
| `award_items` | 4,529,252 | 421.0 MB | Award-to-item relationships |
| `contracts` | 3,261,893 | 376.5 MB | Contracts and award-link status |
| `parties` | 14,181,024 | 1.14 GB | Release-scoped observed party mentions |
| `party_roles` | 14,357,120 | 874.8 MB | Party roles by release |
| `award_suppliers` | 6,448,977 | 1.00 GB | Supplier relationship assertions |
| `party_name_forms` | 177,189 | 14.9 MB | Versioned lexical name forms |
| `party_resolution_candidates` | 399,154 | 48.4 MB | Unresolved entity-resolution evidence |
| `canonical_parties` | 318 | 36.9 KB | Provisional analytical clusters |
| `party_aliases` | 7,993 | 928 KB | Location-supported provisional aliases |
| `data_quality_issues` | 13,882,553 | 1.47 GB | Detected issues and publication gates |
| `record_sources` | 109,929,027 | 4.76 GB | Derived-record to source-row links |

## Source-preserving inputs

- `philgeps_normalized.parquet`: lossless normalized source observations with
  deterministic breadcrumbs.
- `philgeps_cleaned.parquet`: typed and cleaned observations used by the OCDS
  ETL.
- `manifest.json`: source-file registry, normalized filename, coverage dates,
  download URL, and `source_file_id`.

The viewer should show normalized and cleaned values side by side when they
differ. Neither layer supersedes the original PhilGEPS document as source of
truth.

## Current monetary limitation

No populated tender, item, award, or contract amount currently has a populated
currency field. The viewer must display currency as unspecified and must not
format values as pesos or label aggregates as PHP unless the reviewer enables a
clearly marked analytical assumption.

## Identifier namespaces

Provisional canonical-party IDs use the distinct `pgca_` prefix. They were
migrated from the conflicting contracting-process `pgcp_` prefix before viewer
identifier routing was implemented.

## Relationship map

```text
contracting_processes.process_id
    -> releases.process_id
        -> tenders.release_id
        -> tender_items.release_id
        -> awards.release_id
            -> award_items.(release_id, award_id)
            -> award_suppliers.(release_id, award_id)
        -> contracts.release_id
        -> parties.release_id
            -> party_roles.(release_id, party_id)
            -> party_aliases.(release_id, party_id)

compiled_processes.preferred_release_id -> releases.release_id
record_sources.(record_type, record_id) -> source breadcrumb
```

Some relationships intentionally have `missing` or `ambiguous` status. The
viewer must not convert these to links that appear resolved.

Across multi-release processes, 13 contracts, 13 awards, 494 items, and 708
parties reuse an object ID in both release states. Historical views therefore
use `(release_id, object_id)` grain; logical process-object views use
`(process_id, object_id)` and declare their state-selection rule.
