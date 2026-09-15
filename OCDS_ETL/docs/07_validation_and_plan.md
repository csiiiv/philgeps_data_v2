# Validation and implementation plan

## Validation layers

### Input contract

- Cleaned input has 17,528,727 rows and 67 source files.
- Required provenance is non-null and unique per source observation.
- Expected timestamp, decimal, integer, string, and list types match the
  cleaning validation artifact.
- Input manifest version is 2 and every `source_file_id` resolves.

### Relational integrity

- Every primary key is unique and non-null.
- Every populated foreign key marked `matched` resolves to its parent release
  and object.
- Contracts with missing or ambiguous awards remain in `contracts.parquet` and
  carry an explicit link status and data-quality issue.
- Supplier assertions with missing or ambiguous awards or parties remain in
  `award_suppliers.parquet` and carry explicit link statuses and data-quality
  issues.
- Relationship completeness counts reconcile: every attempted relationship is
  classified as matched, missing, or ambiguous.
- Every record has at least one source breadcrumb.
- All input source rows are either mapped or listed with an exclusion reason.

Referential completeness is a measured result, not an ingestion requirement.
The stricter rule applies only to the publication-eligible subset: no contract
or award-supplier relationship with unresolved links may enter standards-valid
OCDS JSON.

### Determinism

- Reordering the input produces identical IDs and content hashes.
- Different DuckDB thread counts produce identical outputs.
- Arrays are sorted before release hashing and JSON serialization.
- Repeated runs produce matching row counts and table checksums.

### Mapping and semantics

- Codelist mappings are total for published fields.
- Unresolved or local-only values never leak into closed OCDS codelists.
- Amounts carry currency.
- JSON timestamps include an approved UTC offset.
- Null and empty properties are omitted according to OCDS serialization rules.
- Quality flags remain available for every inferred or suspicious mapping.

### OCDS publication

- Release JSON validates against the pinned 1.1.5 release schema.
- Release and record packages validate against their pinned package schemas.
- A representative package passes the OCDS Data Review Tool.
- Counts of processes, releases, items, awards, contracts, and parties reconcile
  between Parquet and JSON.

Official build and review guidance:

- https://standard.open-contracting.org/latest/en/guidance/build/
- https://review.standard.open-contracting.org/

## Implementation phases

### Phase 0 — documentation

Status: complete.

Architecture, table contracts, identifiers, mappings, provenance, and gates are
defined before transformation code.

### Phase 1 — grain and candidate-key profile

Status: complete.

`scripts/profile_grain.py` and the JSON/Markdown grain-profile artifacts
measure:

- bid-reference reuse and missing values;
- bid-reference relationships to solicitation number, title, and procuring
  entity;
- line-item uniqueness within candidate processes;
- award-reference uniqueness and reuse;
- contract-number uniqueness and award linkage;
- counts of items, awards, contracts, and suppliers per process;
- exact repeated states versus changed states across exports;
- behavior of the known mislabeled/headerless exports.

Exit criterion met: each proposed identity rule has quantified collision and
fallback counts, and all report reconciliation assertions pass against
17,528,727 observations and 67 source files.

### Phase 2 — mapping configuration and ID prototype

Status: complete.

Pin the selected historical reference files to a repository commit, reconcile
their rules with `05_philgeps_ocds_mapping.md`, create versioned
field/codelist configuration, and generate candidate process and child IDs
without writing final tables.

Exit criterion: deterministic IDs, collision report, and approved open
decisions.

### Phase 3 — multi-table Parquet builder

Status: complete.

Build all tables into a temporary directory, validate them, and atomically
publish `outputs/parquet/`. Produce a machine-readable validation report and
per-table schema metadata.

This phase is lossless with respect to source values. Stronger normalization,
such as organization legal-suffix equivalence and entity resolution, runs over
the split party outputs as a separately versioned transformation. It adds
match keys and canonical references without overwriting observed names. See
ADR-007 in `10_architecture_decision_records.md`.

Exit criterion: complete source coverage, deterministic checksums, zero
unexplained row exclusions, and a fully reconciled count of matched, missing,
and ambiguous relationships. Missing source relationships do not fail the
analytical build.

The published build contains 10,653,920 releases and 109,929,027 provenance
links. Validation found zero duplicate primary keys and zero unresolved foreign
keys marked as matched; every one of the 17,528,727 source observations is
represented.

### Phase 3a — party-name candidate keys

Status: complete for lexical profiling, key generation, the unresolved
candidate-evidence layer, and provisional promotion v1. Verified legal-entity
resolution remains open.

Profile punctuation and terminal legal-suffix variants, publish the compact
`party_name_forms.parquet` dimension, and preserve every observed display name.
The key is matching evidence only and never triggers an automatic party merge.
See `11_party_name_normalization.md` and ADR-007.

The evidence layer contains 399,154 party mentions across 1,962 candidate
groups. All party and name-form foreign keys resolve, every candidate has a
source breadcrumb, and all resolution decisions remain `unresolved`. See
ADR-010.

Provisional promotion v1 creates 318 analytical canonical clusters and 7,993
location-supported alias memberships. It deliberately leaves 9,375 other
mentions in those otherwise eligible groups unresolved. All aliases have a
canonical foreign key and a source breadcrumb; no official organization
identifier is asserted.

### Phase 4 — compiled analytical views

Status: complete.

Order releases and expose latest/preferred records without mutating historical
states. Quantify conflicts and show all alternate sources.

Exit criterion: every compiled value can be traced to a release and source row.

`compiled_processes.parquet` selects exactly one preferred release for all
10,653,228 processes and retains alternate release IDs. The compact
`process_release_history.parquet` contains all 1,384 releases belonging to the
692 multi-release processes. All preferred release foreign keys resolve and
the three same-date ties are selected by source coverage.

### Phase 5 — OCDS JSON exporter

Register or configure the OCID prefix, approve currency/timezone/publisher
metadata, generate release and record packages, and validate against OCDS
1.1.5.

Exit criterion: schema-valid packages and successful data-review samples.

## Open decisions before publication

1. Confirm `PHP` as the currency for all monetary fields.
2. Confirm `Asia/Manila` as the interpretation of naive timestamps.
3. Decide whether `client_agency` is consistently the OCDS buyer.
4. Resolve bid-reference versus solicitation-number identity roles.
5. Confirm item-budget semantics.
6. Confirm award-to-item association rules.
7. Define parsing and publication of joint-venture members.
8. Approve organization contact-person publication policy.
9. Register an OCID prefix and publication metadata.
