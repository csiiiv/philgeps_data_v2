# Historical reference review

## Pinned revision

The reviewed reference repository is pinned to commit
`269a19b7288125814baa6aabf30d33ebf9c12a1a`. Executable mapping configuration
must cite this revision rather than the moving `main` branch.

Review date: 2026-09-12

Reference directory:
https://github.com/csiiiv/philgeps-ocds-schema-analysis/tree/main/references

## What is available

- `ocds_reference.json` is an OCDS 1.1.5 field-level reference containing 649
  core-schema rows and 214 extension rows. It is a vocabulary and schema aid,
  not a PhilGEPS-to-OCDS transformation specification.
- `PHILGEPS_CANONICAL_FIELD_MAP.json` describes five historical source-schema
  variants, 53 canonical fields, and 151 OCDS crosswalk rows.
- `PHILGEPS_OCDS_CSV_CROSSWALK.md` is the readable, row-by-row comparison of
  OCDS paths, PhilGEPS 1.5, PhilGEPS 2.0, V1/V2 CSV columns, and historical
  canonical names.
- `philgeps-1.5.json` contains 110 populated mapping edits based on 166 source
  data-element rows.
- `mphilgeps.json` contains 129 populated mapping edits based on 274 source
  data-element rows.
- `SAMPLE_OCDS_RELEASE_PACKAGE.json` demonstrates a release package using the
  bid and lots extensions and `+08:00` timestamps.
- `PHILGEPS_SCHEMA_ANALYSIS.json` and its Markdown rendering document the
  historical project's interpretation of schema evolution.

## Authority order

When the sources disagree, use this order:

1. Current PhilGEPS source documents and their physical headers/rows.
2. The verified `DATA_NORMALIZATION` schema registry and validation artifacts.
3. The pinned official OCDS 1.1.5 schema and extension schemas.
4. Historical project mappings as reusable analysis and mapping rationale.

This order prevents an older schema narrative from silently changing or
dismissing fields that are demonstrably present in the current source corpus.

## Confirmed alignments

The references support the current design choices to:

- model planning, tender, award, contract, implementation, parties, items, and
  suppliers as separate relational Parquet tables;
- keep PhilGEPS-native labels alongside OCDS codelist mappings;
- use the bid and lots extensions where their fields are actually populated;
- publish timezone-qualified JSON timestamps; and
- preserve fields without safe core mappings as local analytical data instead
  of forcing them into a misleading OCDS property.

## Differences requiring explicit treatment

### Canonical names

The current normalized schema supersedes several historical names:

- `procuring_entity` becomes `procuring_entity_name`;
- `pe_region`, `pe_province`, and `pe_city_municipality` become the corresponding
  `procuring_entity_*` fields;
- `pe_government_branch` becomes `government_branch`;
- `pe_organization_type*` becomes `procuring_entity_organization_type*`;
- `uom` becomes `unit_of_measurement`; and
- historical `published_date` is split into `bid_published_date` and
  `award_published_date`.

The current input also retains `client_agency`, `created_by`, and
`awardee_contact_person`. These fields need mapping or publication-policy
decisions even though they are absent from the historical canonical field set.

### Observed schema versus historical schema narrative

The historical analysis describes its 2021–2024 43-column schema as adding a
bidder-list field. The verified `modern_43` layout in this project contains
`Created By` and `Awardee Contact Person`, but no bidder-list column. A
`list_of_bidders` field must not be synthesized for the current corpus.

The historical analysis also distinguishes two 46-column schema periods. This
project identifies the layout from each physical file and records it as
`location_46`; transformation must rely on that observed schema ID and source
breadcrumb rather than infer a system version from a year label alone.

### Mapping semantics to revalidate

Historical destinations are candidates, not automatic approvals. In
particular, the implementation must revalidate:

- `bid_reference_no` versus `solicitation_no` for process and tender identity;
- whether `item_budget` is a total or unit value;
- whether `award_date` can safely serve as `contracts/dateSigned`;
- whether `contract_amount` represents both award and contract value;
- derived organization identifiers based only on normalized names;
- `client_agency` versus procuring entity for the OCDS buyer role; and
- privacy treatment for contact-person and creator fields;
- the templates' mutable `master` extension URLs, which must be replaced by
  version-pinned extension schemas; and
- the example `ocds-philgeps*` prefixes, which are placeholders until an OCID
  prefix is registered or otherwise approved for publication.

## Adoption rule

Before ETL code uses these references:

1. Record the exact repository commit for every imported file.
2. Convert accepted rules into version-controlled local configuration.
3. Record rejected and superseded rules with a short rationale.
4. Test mappings against the current Parquet fields and observed values.
5. Validate exported JSON against the pinned OCDS and extension schemas.

Links to the mutable `main` branch are suitable for human review but are not a
reproducible build dependency.
