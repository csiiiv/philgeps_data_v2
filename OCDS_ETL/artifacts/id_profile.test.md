# Deterministic ID prototype profile

- Input: `C:\WORK\BetterGovPH\PHILGEPS_DATA_REWORK\DATA_NORMALIZATION\output\philgeps_cleaned.parquet`
- Identity configuration: `C:\WORK\BetterGovPH\PHILGEPS_DATA_REWORK\OCDS_ETL\config\identity_rules.json`
- Identity rules version: `1`
- Validation: **pass**
- Truncated test: `true`

IDs use the full lowercase SHA-256 digest of a compact JSON-array payload. Payloads include the rules version, entity type, identity basis, scope, and source identity fields.

## Overview

| Metric | Value |
|---|---:|
| `observation_rows` | 100,000 |
| `source_files` | 1 |
| `distinct_source_observation_keys` | 100,000 |
| `duplicate_source_observation_keys` | 0 |

## Processes

| Metric | Value |
|---|---:|
| `observation_rows` | 100,000 |
| `distinct_ids` | 98,383 |
| `hash_collision_ids` | 0 |
| `rows_in_hash_collisions` | 0 |
| `ids_with_multiple_entity_names` | 0 |
| `ids_with_multiple_solicitations` | 0 |
| `ids_with_multiple_titles` | 0 |
| `max_entity_names_per_id` | 1 |
| `max_solicitations_per_id` | 0 |
| `max_titles_per_id` | 1 |

### Identity Bases

| basis | observation_rows | distinct_ids |
|---|---|---|
| bid_reference | 87,589 | 86,474 |
| inferred_content_composite | 6,485 | 5,983 |
| source_row | 5,926 | 5,926 |

## Items

| Metric | Value |
|---|---:|
| `observation_rows` | 14,039 |
| `distinct_ids` | 13,419 |
| `hash_collision_ids` | 0 |
| `rows_in_hash_collisions` | 0 |
| `ids_with_multiple_content_versions` | 168 |
| `max_content_versions_per_id` | 13 |

### Identity Bases

| basis | observation_rows | distinct_ids |
|---|---|---|
| line_item_no | 14,039 | 13,419 |

## Awards

| Metric | Value |
|---|---:|
| `observation_rows` | 13,340 |
| `distinct_ids` | 12,925 |
| `hash_collision_ids` | 0 |
| `rows_in_hash_collisions` | 0 |
| `ids_with_multiple_content_versions` | 0 |
| `max_content_versions_per_id` | 1 |

### Identity Bases

| basis | observation_rows | distinct_ids |
|---|---|---|
| award_reference_no | 13,340 | 12,925 |

## Contracts

| Metric | Value |
|---|---:|
| `observation_rows` | 8,933 |
| `distinct_ids` | 8,652 |
| `hash_collision_ids` | 0 |
| `rows_in_hash_collisions` | 0 |
| `ids_with_multiple_content_versions` | 0 |
| `max_content_versions_per_id` | 1 |
| `contract_ids_crossing_awards` | 0 |
| `max_awards_per_contract_id` | 1 |

### Identity Bases

| basis | observation_rows | distinct_ids |
|---|---|---|
| award_scoped_content_composite | 8,933 | 8,652 |

### Award Links

| status | observation_rows | distinct_contract_ids |
|---|---|---|
| matched | 8,933 | 8,652 |

## Parties

| Metric | Value |
|---|---:|
| `observation_rows` | 113,340 |
| `distinct_ids` | 111,082 |
| `hash_collision_ids` | 0 |
| `rows_in_hash_collisions` | 0 |
| `party_ids_with_multiple_source_spellings` | 0 |
| `max_source_spellings_per_party_id` | 1 |

### Identity Bases

| basis | observation_rows | distinct_ids |
|---|---|---|
| procuringEntity | 100,000 | 98,383 |
| supplier | 13,340 | 12,750 |

### Role Mentions

| role | observation_rows | distinct_party_ids |
|---|---|---|
| procuringEntity | 100,000 | 98,383 |
| supplier | 13,340 | 12,750 |

## Interpretation

- A hash collision means two different canonical identity payloads produced the same ID; any such collision fails validation.
- Multiple content versions under one ID mean the same entity was observed with changed or conflicting attributes. Those versions are preserved for release construction.
- Party IDs identify normalized name mentions within a process. They must not be represented as legal-entity identifiers.
- Examples and their callable source breadcrumbs are available in the JSON artifact.
