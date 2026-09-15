# OCDS Parquet data model (ERD)

Entity-relationship overview of the PhilGEPS → OCDS parquet outputs consumed by
the Parquet Viewer. Grain and keys match `config/datasets.json` and the live
parquet schemas under `OCDS_ETL/outputs/parquet/`.

**Conventions**

- Solid relationships are join keys used by the viewer/ETL.
- `* _link_status` fields (`matched` / `missing` / `ambiguous`) mean the FK may
  be unresolved — do not treat those rows as hard foreign keys in UI links.
- Child OCDS objects are scoped by `(release_id, …)`. Across multi-release
  processes, the same object id can appear in more than one release state.
- Identifier prefixes (examples): `pgcp_` process, `pgrl_` release, `pgaw_`
  award, `pgct_` contract, `pgti_` tender item, `pgca_` provisional canonical
  party.

---

## 1. Core contracting process (overview)

```mermaid
erDiagram
  contracting_processes ||--o{ releases : "process_id"
  contracting_processes ||--|| compiled_processes : "process_id"
  compiled_processes }o--|| releases : "preferred_release_id"
  contracting_processes ||--o{ process_release_history : "process_id"
  process_release_history }o--|| releases : "release_id"

  releases ||--o| tenders : "release_id"
  releases ||--o{ tender_items : "release_id"
  releases ||--o{ awards : "release_id"
  releases ||--o{ contracts : "release_id"
  releases ||--o{ parties : "release_id"
  releases ||--o{ data_quality_issues : "release_id"

  awards ||--o{ award_items : "release_id + award_id"
  tender_items ||--o{ award_items : "release_id + item_id"
  awards ||--o{ award_suppliers : "release_id + award_id"
  awards ||--o{ contracts : "release_id + award_id"
  parties ||--o{ award_suppliers : "release_id + party_id"
  parties ||--o{ party_roles : "release_id + party_id"

  contracting_processes {
    string process_id PK
    string ocid
    string source_process_identifier
    string first_release_id
    string latest_release_id
    int release_count
  }

  compiled_processes {
    string process_id PK
    string preferred_release_id FK
    string preferred_release_date_basis
    string selection_basis
    int release_count
    boolean has_multiple_releases
  }

  releases {
    string release_id PK
    string process_id FK
    string ocid
    datetime release_date
    string release_date_basis
    string content_hash
    boolean has_tender
    boolean has_award
    boolean has_contract
  }

  process_release_history {
    string release_id PK
    string process_id FK
    int chronological_rank
    int preference_rank
    boolean is_preferred
  }
```

---

## 2. Tender, awards, items, contracts

```mermaid
erDiagram
  releases ||--o| tenders : contains
  releases ||--o{ tender_items : contains
  releases ||--o{ awards : contains
  releases ||--o{ contracts : contains

  tenders {
    string release_id PK
    string tender_id PK
    string source_bid_reference
    string title
    datetime date_published
    datetime closing_date
    string procurement_method
    string status
    string source_status
    decimal value_amount
    string value_currency
  }

  tender_items {
    string release_id PK
    string item_id PK
    int source_line_item_number
    string title
    string description
    decimal quantity
    string unit_name
    decimal item_budget_amount
    string item_budget_currency
  }

  awards {
    string release_id PK
    string award_id PK
    string source_award_reference
    string title
    string description
    datetime date
    datetime date_published
    decimal value_amount
    string value_currency
    string status
    string source_status
  }

  award_items {
    string release_id PK
    string award_id PK
    string item_id PK
    string link_basis
  }

  contracts {
    string release_id PK
    string contract_id PK
    string award_id FK
    string source_award_reference
    string award_link_status
    string source_contract_number
    decimal value_amount
    datetime period_start
    datetime period_end
    datetime notice_to_proceed_date
  }

  awards ||--o{ award_items : "covers"
  tender_items ||--o{ award_items : "awarded as"
  awards ||--o{ contracts : "may produce"
```

**Partial award note:** tender line items with no `award_items` row are
unawarded for that release (shown under Bids close on the timeline).

---

## 3. Parties, roles, and supplier assertions

```mermaid
erDiagram
  releases ||--o{ parties : mentions
  parties ||--o{ party_roles : "has role"
  awards ||--o{ award_suppliers : "supplier assertion"
  parties ||--o{ award_suppliers : "asserted as"
  contracts ||--o{ award_suppliers : "optional via award"

  parties {
    string release_id PK
    string party_id PK
    string name
    string name_key
    string source_organization_type
    string identity_confidence
  }

  party_roles {
    string release_id PK
    string party_id PK
    string role PK
  }

  award_suppliers {
    string award_supplier_assertion_id PK
    string release_id FK
    string award_id FK
    string party_id FK
    string source_award_reference
    string source_supplier_label
    string source_joint_venture
    string award_link_status
    string party_link_status
  }
```

Typical roles: `procuringEntity`, `supplier`. Being listed in `party_roles`
does **not** imply an award — only `award_suppliers` assertions do.

Authoritative supplier → contract path (when links are `matched`):

```text
party_name_forms
  → parties + party_roles (supplier)
  → award_suppliers
  → awards
  → contracts
  → releases → contracting_processes
  → record_sources
```

---

## 4. Party normalization and provisional identity

These tables are analytical / provisional. Canonical IDs use the `pgca_`
prefix and are **not** official organization identifiers.

```mermaid
erDiagram
  party_name_forms ||--o{ party_resolution_candidates : "name_form_id"
  parties ||--o{ party_resolution_candidates : "release_id + party_id"
  canonical_parties ||--o{ party_aliases : "canonical_party_id"
  parties ||--o{ party_aliases : "release_id + party_id"
  party_name_forms ||--o{ party_aliases : "name_form_id"

  party_name_forms {
    string name_form_id PK
    string observed_name
    string conservative_name_key
    string punctuation_name_key
    string legal_suffix_name_key
    int party_mentions
  }

  party_resolution_candidates {
    string resolution_candidate_id PK
    string candidate_group_id
    string release_id FK
    string party_id FK
    string name_form_id FK
    string evidence_status
    string resolution_status
    boolean automatic_merge_allowed
  }

  canonical_parties {
    string canonical_party_id PK
    string preferred_name
    string identity_status
    string match_method
    int supporting_party_mentions
  }

  party_aliases {
    string party_alias_id PK
    string canonical_party_id FK
    string release_id FK
    string party_id FK
    string name_form_id FK
    string alias_status
    string match_method
  }
```

---

## 5. Provenance and data quality

```mermaid
erDiagram
  releases ||--o{ data_quality_issues : "may flag"
  releases ||--o{ record_sources : "sourced from"

  data_quality_issues {
    string issue_id PK
    string release_id FK
    string record_type
    string record_id
    string issue_code
    string issue_category
    string severity
    boolean publication_blocking
    string observed_value
    string detail
  }

  record_sources {
    string record_type PK
    string record_id PK
    string release_id FK
    string source_file_id PK
    string source_sheet PK
    int source_row_number PK
  }
```

`record_sources` links any derived record (`record_type` + `record_id`) back to
a physical PhilGEPS source row via `source_file_id` (see
`RAW_DATA_DOWNLOADER/dataset/manifest.json`).

---

## 6. Upstream source layers (outside OCDS parquet)

Not OCDS entities, but part of the end-to-end data lineage:

```mermaid
flowchart LR
  subgraph Source
    M[manifest.json]
    R[PhilGEPS CSV / XLS downloads]
  end
  subgraph Normalization
    N[philgeps_normalized.parquet]
    C[philgeps_cleaned.parquet]
  end
  subgraph OCDS_ETL
    P[parquet tables above]
  end
  M --> R
  R --> N
  N --> C
  C --> P
  P --> RS[record_sources]
  M -.-> RS
```

---

## 7. Dataset index (primary keys)

| Dataset | Primary key | Record type |
|---|---|---|
| `contracting_processes` | `process_id` | — |
| `compiled_processes` | `process_id` | — |
| `releases` | `release_id` | `release` |
| `process_release_history` | `release_id` | `release` |
| `tenders` | `release_id`, `tender_id` | `tender` |
| `tender_items` | `release_id`, `item_id` | `tender_item` |
| `awards` | `release_id`, `award_id` | `award` |
| `award_items` | `release_id`, `award_id`, `item_id` | `award_item` |
| `contracts` | `release_id`, `contract_id` | `contract` |
| `parties` | `release_id`, `party_id` | `party` |
| `party_roles` | `release_id`, `party_id`, `role` | — |
| `award_suppliers` | `award_supplier_assertion_id` | `award_supplier_assertion` |
| `party_name_forms` | `name_form_id` | — |
| `party_resolution_candidates` | `resolution_candidate_id` | — |
| `canonical_parties` | `canonical_party_id` | — |
| `party_aliases` | `party_alias_id` | — |
| `data_quality_issues` | `issue_id` | `data_quality_issue` |
| `record_sources` | `record_type`, `record_id`, `source_file_id`, `source_sheet`, `source_row_number` | — |

See also [03_data_catalog.md](./03_data_catalog.md) for row counts and viewer
roles, and [09_supplier_contract_queries.md](./09_supplier_contract_queries.md)
for supplier identity scopes.
