# Parquet table contracts

All identifiers are strings. Timestamps remain timezone-naive inside the
Parquet analytical model until the publication timezone policy is approved.
Amounts use the cleaned decimal values and carry `currency = 'PHP'` only after
that assumption is confirmed.

## `contracting_processes.parquet`

Grain: one row per inferred contracting process.

Primary key: `process_id`.

Required columns:

- `process_id`: internal stable identifier.
- `ocid`: nullable until an official prefix is registered.
- `source_process_identifier`: normally the accepted bid reference.
- `source_identifier_basis`: `bid_reference`, `solicitation_number`, or
  `source_fallback`.
- `first_release_id`, `latest_release_id`.
- `release_count`.
- `process_quality_flags`.

This table holds identity and compilation metadata. Mutable tender content
belongs to releases, not here.

## `releases.parquet`

Grain: one distinct observed state of one contracting process.

Primary key: `release_id`. Foreign key: `process_id`.

- `release_id`: content-addressed internal release identifier.
- `process_id`, `ocid`.
- `release_date`, `release_date_basis`, `release_date_confidence`.
- `tags`: OCDS release-tag list.
- `initiation_type`: expected `tender`.
- `content_hash`.
- `first_observed_period`, `last_observed_period`.
- `is_latest_observed_state`.
- `release_quality_flags`.

No source filename or URL is repeated here.

## `tenders.parquet`

Grain: zero or one tender object per release.

Primary and foreign key: `release_id`.

Fields include tender ID, solicitation number, title, status, notice type,
procurement method and details, main procurement category, business category,
funding fields, trade agreement, value and currency, publication timestamp,
tender period end, pre-bid milestone timestamp, estimated contract duration,
and local fields that do not yet have safe OCDS mappings.

## `tender_items.parquet`

Grain: one tender item within a release.

Primary key: `(release_id, item_id)`. Foreign key: `release_id`.

- `item_id`: stable within the contracting process.
- `source_line_item_number`.
- `title`, `description`, `quantity`.
- `unit_name`.
- `item_budget_amount`, `item_budget_currency`.
- `classification_scheme`, `classification_id`,
  `classification_description`.
- `item_quality_flags`.

`item_budget_amount` remains a local analytical field until profiling confirms
whether it is a total line budget or a unit value.

## `awards.parquet`

Grain: one award within a release.

Primary key: `(release_id, award_id)`. Foreign key: `release_id`.

- `award_id`, `source_award_reference`.
- `title`, `description`, `status`, `award_type`.
- `date`, `date_published`.
- `value_amount`, `value_currency`.
- `award_quality_flags`.

Award IDs must be unique within a process, as required by OCDS.

## `award_items.parquet`

Grain: one award-to-tender-item relationship.

Primary key: `(release_id, award_id, item_id)`.

This link is created only when the flat PhilGEPS row provides defensible
evidence that the award relates to the item. It is not filled by assuming every
award covers every item.

## `contracts.parquet`

Grain: one contract within a release.

Primary key: `(release_id, contract_id)`.

Conditional foreign key: `(release_id, award_id)` to `awards` when `award_id`
is populated and `award_link_status = 'matched'`.

- `contract_id`, `source_contract_number`, nullable `award_id`.
- `source_award_reference`, `award_link_status` (`matched`, `missing`, or
  `ambiguous`).
- `status` if safely derivable.
- `value_amount`, `value_currency`.
- `period_start`, `period_end`, `duration_in_days`.
- `notice_to_proceed_date` as a local field or implementation milestone.
- `contract_quality_flags`.

The analytical table retains a contract even when its award is absent or
ambiguous. It does not invent an award merely to satisfy a foreign key. Such a
contract receives a quality flag and remains queryable with its source
breadcrumb. Because an OCDS-published contract must reference an award, only
`matched` contracts can enter a standards-valid JSON package.

## `parties.parquet`

Grain: one party mention within a release.

Primary key: `(release_id, party_id)`.

- `party_id`: release-scoped cross-reference ID.
- `name`, `name_key`.
- source organization type and size.
- address fields retained for later PSGC normalization.
- contact name where publication is permitted.
- `identity_confidence` and `party_quality_flags`.

An exact normalized name can create a party mention key, but it is not a legal
entity ID and must not be advertised as one.

## `party_name_forms.parquet`

Grain: one distinct observed party name across all releases.

Primary key: `name_form_id`, deterministically derived from the exact observed
name. This is a compact, versioned matching aid rather than an OCDS object or a
canonical organization register.

- `observed_name` and `conservative_name_key` preserve the source-facing form.
- `punctuation_name_key` folds case, punctuation, and spacing.
- `legal_suffix_name_key` additionally canonicalizes approved terminal legal
  forms such as `Incorporated` to `inc`.
- `rule_version` identifies the exact normalization policy.
- mention, release, and variant counts quantify the evidence behind a key.
- `has_candidate_alias` and `has_legal_suffix_equivalent` identify review
  candidates; neither flag authorizes an entity merge.

Join `observed_name` back to `parties.name`, then use the party's
`(release_id, party_id)` links in `record_sources.parquet` for source-row
breadcrumbs. See `11_party_name_normalization.md`.

## `party_resolution_candidates.parquet`

Grain: one party mention that belongs to a multi-spelling candidate-name
group.

Primary key: `resolution_candidate_id`. Foreign key:
`(release_id, party_id)` to `parties.parquet`.

- `candidate_group_id` groups mentions sharing the versioned legal-suffix name
  key.
- `name_form_id` links to `party_name_forms.parquet`.
- `roles`, source location fields, organization fields, and their normalized
  evidence keys are retained for comparison.
- group counts describe name forms, mentions, available locations, shared
  locations, and organization contexts.
- `evidence_status` is `corroborated_candidate`, `partial_context`,
  `divergent_location_context`, or `name_only`.
- `resolution_status` remains `unresolved` and
  `automatic_merge_allowed` remains false in evidence rule version 1.

This is a review queue, not a canonical-party crosswalk. A shared normalized
location supports a match but does not prove legal identity, while different
locations can represent branches rather than conflicting entities.

## `canonical_parties.parquet`

Grain: one provisionally promoted analytical party cluster.

Primary key: `canonical_party_id`. These IDs are internal analytical IDs, not
official organization identifiers and not OCDS `identifier.id` values.

- `preferred_name` is the most frequent supported observed spelling, with a
  deterministic lexical tie-breaker.
- `candidate_name_key`, `normalized_location_key`, and `role_family` record the
  promotion basis.
- `observed_name_forms` preserves every supported spelling.
- supporting, total, and unresolved mention counts expose the boundary of the
  cluster.
- `identity_status` is `provisional`; official identifier fields remain null.
- `promotion_rule_version` and `identity_quality_flags` make the inference
  explicit and rerunnable.

## `party_aliases.parquet`

Grain: one location-supported party mention assigned provisionally to one
analytical canonical party.

Primary key: `party_alias_id`. Foreign keys: `canonical_party_id` to
`canonical_parties.parquet`, `(release_id, party_id)` to `parties.parquet`, and
`name_form_id` to `party_name_forms.parquet`.

Version 1 includes only mentions that themselves carry the single corroborated
group location. Mentions with the same spelling but no location remain
unresolved; identity is not propagated from the spelling alone. Every alias
resolves to its original PhilGEPS source through the party entry in
`record_sources.parquet`.

## `party_roles.parquet`

Grain: one role for one party in one release.

Primary key: `(release_id, party_id, role)`.

Initial roles are `procuringEntity`, `buyer`, and `supplier`. `tenderer` and
consortium membership are added only after their source fields are verified.

## `award_suppliers.parquet`

Grain: one observed supplier-to-award assertion.

Primary key: `award_supplier_assertion_id`.

- `release_id`.
- nullable `award_id` and nullable `party_id`.
- source award and supplier labels used to attempt the links.
- `award_link_status` and `party_link_status` (`matched`, `missing`, or
  `ambiguous`).
- `supplier_quality_flags`.

This table retains incomplete assertions rather than discarding them. Rows for
which both links are `matched` realize OCDS `awards[].suppliers[]`; other rows
remain analytical evidence and publication-blocking quality findings. A joint
venture can result in multiple supplier assertions, but the PhilGEPS
joint-venture field requires separate parsing and validation first.

## `record_sources.parquet`

Grain: one source-row assertion supporting one derived record.

Primary key:
`(record_type, record_id, source_file_id, source_sheet, source_row_number)`.

- `record_type`: `release`, `tender`, `tender_item`, `award`, `contract`,
  `party`, `award_supplier_assertion`, or `data_quality_issue`.
- `record_id`: globally prefixed internal record identifier.
- `release_id`.
- `source_file_id`, `source_sheet`, `source_row_number`.
- `source_fields`: optional list of source columns contributing values.
- `is_preferred_source` and `selection_basis`.

URLs and filenames remain in manifest v2 and are resolved at presentation
time.

## `data_quality_issues.parquet`

Grain: one detected issue affecting one record, relationship assertion, or
source observation.

Primary key: `issue_id`.

- nullable `release_id`, `record_type`, and `record_id`;
- `issue_code`, `issue_category`, and `severity`;
- `publication_blocking`;
- `observed_value` and a human-readable `detail` where safe; and
- detection rule and rule version.

Relationship examples include `contract_award_missing`,
`contract_award_ambiguous`, `supplier_award_missing`, and
`supplier_party_ambiguous`. Each issue links to its supporting source row
through `record_sources.parquet`. Resolving an issue in a later observed state
does not erase the earlier issue.

## `compiled_processes.parquet`

Grain: one contracting process with one analytically preferred release.

Primary key: `process_id`. Foreign key: `preferred_release_id` to
`releases.parquet`.

- preferred release ID, date, date basis, and selection basis;
- release count and alternate release IDs;
- date-tie and distinct-content-state counts;
- versioned compilation rule and quality flags.

This is a compact join index. Process identifiers remain in
`contracting_processes.parquet`; preferred tender, award, contract, item, and
party attributes remain in their source-preserving tables and are joined using
`preferred_release_id`.

## `process_release_history.parquet`

Grain: one release belonging to a process with multiple releases.

Primary key: `release_id`. Foreign key: `process_id` to
`contracting_processes.parquet`.

The table records chronological and preference ranks, lifecycle evidence,
source coverage, content hashes, and change-from-previous state. Single-release
processes are omitted because their preferred release is already unambiguous.
