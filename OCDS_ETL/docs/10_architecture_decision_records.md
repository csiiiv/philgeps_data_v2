# Architecture decision records

This file is the decision log for the PhilGEPS-to-OCDS Parquet ETL. It records
decisions that affect data meaning, identity, traceability, output contracts,
or publication. It is intentionally separate from the implementation plan.

## How to maintain this log

- Use the next sequential `ADR-NNN` identifier.
- Set status to `proposed`, `accepted`, `superseded`, or `rejected`.
- Do not silently rewrite an accepted decision. Add a new ADR and identify the
  decision it supersedes.
- Record material schema or algorithm changes in the applicable configuration
  version as well as here.
- An implementation detail that cannot change data meaning does not need an
  ADR.

## ADR-001: Treat PhilGEPS observations as the source of truth

- Status: accepted
- Date: 2026-09-13

### Context

Cleaning and OCDS mapping can accidentally make a derived value appear more
authoritative than the PhilGEPS export from which it came.

### Decision

The immutable source-preserving and cleaned observation Parquets remain the
evidentiary inputs. OCDS-aligned tables are derived products. A transformation
may add typed values, normalized keys, classifications, and quality flags, but
must not destroy the original observed value or its source breadcrumb.

### Consequences

Users can compare a derived record with the exact PhilGEPS row. Corrections to
normalization or mapping can be rebuilt without downloading the source again.

## ADR-002: Use an OCDS-aligned multi-table Parquet model

- Status: accepted
- Date: 2026-09-13

### Context

One denormalized row can contain process, item, award, contract, supplier, and
organization attributes. Keeping that shape repeats data and obscures each
entity's grain.

### Decision

Split observations into process/release, item, award, contract, party, role,
relationship, and provenance tables. Keep explicit primary keys, foreign keys,
and link-status fields. Parquet is the static analytical distribution format.

### Consequences

Queries read only the needed columns and tables. Relationships become
testable, while downstream consumers can still build denormalized views.

## ADR-003: Store provenance in relationship tables, not every data column

- Status: accepted
- Date: 2026-09-13

### Context

Repeating filenames, URLs, and row references throughout every entity table
would substantially enlarge the outputs.

### Decision

Use `source_file_id` from manifest v2 plus the physical source row number as
the collision-free source-observation key. Retain the worksheet as context.
Connect derived records to one or more observations through
`record_sources.parquet`. The compact breadcrumb is
`source_file_id:source_row_number`; the manifest resolves the file and URL.

### Consequences

Traceability remains complete without bloating every table. A record can cite
multiple observations when it appears in multiple exports.

## ADR-004: Generate deterministic, versioned internal identifiers

- Status: accepted
- Date: 2026-09-13

### Context

Source identifiers are missing, reused, or scoped differently depending on the
entity. Random UUIDs would make rebuild comparisons difficult.

### Decision

Generate IDs from canonical identity payloads using the rules in
`../config/identity_rules.json`. Include the identity-rule version, entity
type, scope, basis, and identity fields in each payload. Use a full SHA-256
digest with a human-readable entity prefix. Fallback identity routes remain
explicit and measurable.

### Consequences

Equivalent inputs produce the same IDs across rebuilds. Changing identity
semantics requires a rule-version change and produces intentionally different
IDs.

## ADR-005: Preserve incomplete and unresolved relationships

- Status: accepted
- Date: 2026-09-13

### Context

PhilGEPS records can contain contract or supplier evidence without all fields
needed to resolve the expected parent relationship.

### Decision

Analytical ingestion does not require every contract to resolve to an award or
every supplier to resolve to both an award and party. Retain attempted links
with `matched`, `missing`, or `ambiguous` status and quality flags. Require
resolved links only for the subset exported as standards-valid OCDS JSON.

### Consequences

Data-quality gaps remain observable rather than disappearing through inner
joins. Publication has a stricter eligibility gate than analytical storage.

## ADR-006: Treat Parquet as OCDS-aligned, not itself OCDS-conformant

- Status: accepted
- Date: 2026-09-13

### Context

OCDS formally defines JSON release and record packages, while the relational
model is optimized for analysis.

### Decision

Use OCDS concepts and semantics in the Parquet contracts, but claim formal
conformance only for JSON packages that validate against the pinned OCDS 1.1.5
schemas.

### Consequences

The analytical model can use relational link tables and quality metadata
without pretending those are part of the OCDS JSON schema.

## ADR-007: Separate lossless splitting from entity-name resolution

- Status: accepted
- Date: 2026-09-13

### Context

Organization names contain lexical variants such as `Inc`, `Inc.`,
`Incorporated`, spacing differences, punctuation differences, abbreviations,
and typographical errors. Replacing these values during the initial split can
erase evidence and can incorrectly merge distinct legal entities.

### Decision

Build the lossless OCDS-aligned split first. Preserve each source display name
and the existing conservative name key. Perform stronger organization-name
normalization and entity resolution as a subsequent, versioned transformation
over the party outputs.

That later transformation may add:

- a versioned lexical match key that canonicalizes safe variants, including
  legal-form suffixes such as `Inc.` and `Incorporated`;
- normalization method and rule-version fields;
- candidate-match scores and reasons;
- a nullable canonical-party or cluster ID only after resolution rules are
  validated; and
- explicit aliases back to every source spelling and breadcrumb.

It must not overwrite the source `name`. Legal-suffix equivalence is evidence
for matching, not proof that two mentions are the same legal entity. Address,
identifier, and contextual evidence should be used where available.

### Consequences

The base split stays lossless and can be produced before the harder entity
resolution work is complete. Improved matching rules can be rerun without
changing source-preserving party records. Consumers can choose between source
names, conservative keys, or resolved canonical entities.

## ADR-008: Publish validated Parquet outputs atomically

- Status: accepted
- Date: 2026-09-13

### Context

Long, multi-table builds can be interrupted and must not leave a partially
published dataset that appears complete.

### Decision

Build resumable intermediate stages in a temporary build directory. Validate
schemas, keys, relationship reconciliation, provenance coverage, and
deterministic checksums before replacing the published Parquet directory as
one logical operation.

### Consequences

An interrupted run may leave restartable working data, but consumers see only
the last fully validated output set.

## ADR-009: Preserve source codelists and gate uncertain OCDS mappings

- Status: accepted
- Date: 2026-09-13

### Context

Some PhilGEPS categories have direct OCDS equivalents, while others depend on
procurement-law interpretation or contain truncated labels. A best-guess
closed-codelist value can silently change the meaning of a procurement method
or status.

### Decision

Every mapped categorical field retains its PhilGEPS source label. Each source
value is explicitly configured with an `accepted`, `proposed`, or `unresolved`
mapping status. Analytical Parquets may contain all three categories, but only
accepted mappings can populate a closed OCDS codelist in published JSON.
Proposed rules may record a candidate destination for review, but proposed and
unresolved values keep the publication field null and create a
publication-gate finding until approved.

### Consequences

New source labels fail mapping coverage validation. Analysts can still query
the original labels, and mapping policy can improve without rebuilding the
source-preserving layer.

## ADR-010: Separate candidate evidence from canonical party resolution

- Status: accepted
- Date: 2026-09-13

### Context

Lexical profiling found 1,962 multi-spelling candidate groups covering 399,154
party mentions. Location evidence is uneven: 224 groups have none, 1,211 have
only partial coverage, 395 share at least one normalized location across name
forms, and 132 have locations under every form but no shared location. Shared
addresses can support identity, but branches can legitimately use different
addresses and unrelated organizations can share an address.

### Decision

Publish candidate memberships and evidence separately from canonical party
identities. Candidate rows retain party IDs, roles, observed location and
organization fields, versioned match keys, and an evidence status. The first
evidence version assigns no canonical party ID: every resolution remains
`unresolved` and automatic merging is disabled.

Future promotion to a canonical party requires a separately approved rule with
stronger evidence and explicit negative-evidence handling. A lexical key or
shared normalized location alone is insufficient.

### Consequences

Analysts gain a compact, traceable review queue without changing the base party
records or overstating entity certainty. Candidate and canonical outputs can be
recomputed under later rule versions, while source names and breadcrumbs remain
stable.

## ADR-011: Promote only location-supported punctuation variants provisionally

- Status: accepted
- Date: 2026-09-13

### Context

Of 1,962 candidate name groups, 395 have a normalized location shared across
multiple observed spellings. Location evidence is still insufficient to verify
legal identity, and applying a group decision to mentions without their own
location would turn a supported inference into a name-only match.

### Decision

Promotion rule `party-promotion-v1` creates provisional analytical canonical
parties only for punctuation-or-case variants where every observed form has
location evidence, the group has exactly one normalized location, organization
context is compatible, and supplier/public-body role families are not mixed.
Legal-suffix equivalence alone is excluded from this first promotion rule.

Within an eligible group, only party mentions that themselves carry the
corroborating location receive an alias membership. Other mentions remain
unresolved. Canonical IDs are deterministic and versioned, carry a provisional
quality flag, and must not be published as official organization identifiers.

### Consequences

The first version creates 318 provisional canonical parties and 7,993 supported
alias memberships while leaving 9,375 other mentions in those groups
unresolved. The rule favors precision and auditability over recall. A later
version can promote additional evidence patterns without rewriting source party
records or silently inheriting identity from name alone.

## ADR-012: Compile through a preferred-release join index

- Status: accepted
- Date: 2026-09-13

### Context

The analytical model contains 10,653,228 processes and 10,653,920 releases.
Only 692 processes have multiple releases, each with two states. Duplicating
all preferred tender, item, award, contract, and party rows would materially
increase storage and create another set of tables requiring synchronization.

### Decision

Publish a compact process index containing the preferred release and selection
metadata. Rank releases by date, lifecycle completeness, supporting source-file
count, supporting observation count, and deterministic release ID. Preserve
alternate release IDs in the index and publish detailed release ordering only
for multi-release processes.

Consumers obtain preferred child objects by joining their existing tables to
`preferred_release_id`. Historical tables remain immutable and authoritative;
the preference is an analytical view, not a deletion or replacement of prior
states.

### Consequences

The compiled layer adds a 780.6 MB process index and a 136 KB history table
without duplicating large child Parquets. All current preferred IDs agree with
the base latest-release IDs, while three same-date cases now have an explicit
source-coverage rationale. Alternate states and source breadcrumbs remain
queryable.

## Decisions still to record

Add ADRs when the following choices are approved:

- currency and timezone interpretation;
- whether `client_agency` represents the OCDS buyer;
- award-to-item association rules;
- joint-venture parsing and representation;
- organization contact-person publication policy;
- OCID prefix, publisher metadata, and release-publication strategy; and
- a verified organization entity-resolution algorithm beyond provisional v1.
