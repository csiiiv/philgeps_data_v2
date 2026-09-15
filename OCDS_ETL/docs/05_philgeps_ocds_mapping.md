# PhilGEPS-to-OCDS mapping

This is the initial mapping specification. `Unresolved` rows are deliberate
implementation gates, not missing documentation. All mapped amounts use `PHP`
only after the currency policy is confirmed.

The executable draft is `../config/field_mapping.json`; categorical mappings
are in `../config/codelist_mapping.json`. Coverage is checked by
`../scripts/validate_mapping_config.py` and recorded in
`../artifacts/mapping_coverage.json`.

| PhilGEPS cleaned field | OCDS destination | Treatment | Status |
|---|---|---|---|
| `bid_reference_no` | `ocid` suffix candidate; `tender.id` candidate | Validate stability and uniqueness first | Unresolved |
| `solicitation_no` | `tender.id` or local identifier | Select against bid reference using grain profile | Unresolved |
| `notice_title` | `tender.title` | Copy cleaned text | Direct |
| `bid_published_date` | `tender.datePublished`; release-date evidence | Add approved `+08:00` offset for JSON | Mapped |
| `classification` | `tender.mainProcurementCategory` | Explicit goods/works/services mapping | Mapped |
| `notice_type` | Local tender detail and release-tag evidence | No safe core field yet | Local |
| `procurement_mode` | `tender.procurementMethodDetails` | Preserve local label | Direct |
| derived broad method | `tender.procurementMethod` | Map to OCDS open/selective/limited/direct | Mapped |
| `business_category` | Local classification or extension | Scheme and semantics need review | Unresolved |
| `funding_source` | `planning.budget.description` candidate | Preserve source label | Mapped |
| `funding_instrument` | Budget/local extension | Semantics need review | Unresolved |
| `trade_agreement` | Tender local field or extension | Check applicable OCDS extension | Unresolved |
| `approved_budget` | `tender.value.amount` | Decimal amount | Direct |
| constant currency | `tender.value.currency` | `PHP` after confirmation | Inferred |
| `area_of_delivery` | Item delivery location extension candidate | Do not map to address blindly | Unresolved |
| `contract_duration` + `calendar_type` | `tender.contractPeriod.durationInDays` candidate | Convert only day-based durations safely | Mapped |
| `prebid_date` | `tender.milestones[]` | Meeting milestone with stable ID | Mapped |
| `closing_date` | `tender.tenderPeriod.endDate` | Preserve time and add publication offset | Direct |
| `bid_notice_status` | `tender.status` | Explicit OCDS codelist map | Mapped |
| `line_item_no` | `tender.items[].id` candidate | Verify uniqueness within process | Unresolved |
| `item_name` | `tender.items[].title` | Core lacks item title in 1.1; preserve locally or combine carefully | Local |
| `item_description` | `tender.items[].description` | Copy cleaned text | Direct |
| `quantity` | `tender.items[].quantity` | Decimal | Direct |
| `unit_of_measurement` | `tender.items[].unit.name` | Preserve local UOM label | Direct |
| `item_budget` | Item local total or `unit.value.amount` | Determine total-versus-unit semantics first | Unresolved |
| `unspsc_code` | `tender.items[].classification.id` | Retain eight-digit string | Direct |
| constant `UNSPSC` | `tender.items[].classification.scheme` | Literal scheme name | Direct |
| `unspsc_description` | `tender.items[].classification.description` | Copy cleaned text | Direct |
| `award_reference_no` | `awards[].id` candidate | Verify uniqueness within process | Unresolved |
| `award_title` | `awards[].title` | Copy cleaned text | Direct |
| `award_type` | Award local field or extension | Core mapping not established | Local |
| `award_date` | `awards[].date` | Timestamp with approved offset | Direct |
| `award_published_date` | Release-date evidence | Do not confuse publication and decision dates | Mapped |
| `contract_amount` | `awards[].value.amount`; `contracts[].value.amount` candidate | Profile award/contract semantics | Unresolved |
| `award_notice_status` | `awards[].status` | Explicit OCDS codelist map | Mapped |
| `reason_for_award` | `awards[].description` or local field | Preserve without overstating semantics | Mapped |
| `contract_no` | `contracts[].id` candidate | Verify stability and process-local uniqueness | Unresolved |
| `notice_to_proceed_date` | `contracts[].implementation.milestones[]` | Stable milestone ID/type | Mapped |
| `contract_effectivity_date` | `contracts[].period.startDate` | Timestamp | Direct |
| `contract_end_date` | `contracts[].period.endDate` | Invalid source dates remain flagged/null | Direct |
| `procuring_entity_name` | `parties[]`; `tender.procuringEntity` | Party role `procuringEntity` | Direct |
| `client_agency` | `parties[]`; release `buyer` candidate | Confirm that it is the paying/using buyer | Unresolved |
| `awardee_organization_name` | `parties[]`; `awards[].suppliers[]` | Party role `supplier` | Direct |
| awardee/procuring-entity locations | `parties[].address` | Wait for PSGC normalization | Unresolved |
| organization type and size | `parties[].details` extension/local | Preserve source classification | Local |
| `awardee_contact_person` | `parties[].contactPoint.name` | Subject to publication/privacy review | Unresolved |
| `awardee_joint_venture` | Additional suppliers/consortium representation | Parse and verify semantics first | Unresolved |
| `created_by` | Internal provenance metadata | Do not publish without policy review | Local |

## Codelist mapping requirements

Separate configuration must map, without changing source labels:

- PhilGEPS procurement modes to OCDS `procurementMethod`;
- PhilGEPS classifications to `mainProcurementCategory`;
- bid notice statuses to OCDS tender statuses;
- award notice statuses to OCDS award statuses;
- calendar units to normalized durations where conversion is safe.

Each codelist rule records source value, destination value, rationale, status,
and version. Unmapped values fail the publication gate but remain available in
the analytical Parquets.

## Reference reconciliation status

The historical project's complete
[`references/`](https://github.com/csiiiv/philgeps-ocds-schema-analysis/tree/main/references)
directory has now been reviewed and pinned to commit
`269a19b7288125814baa6aabf30d33ebf9c12a1a`.
`ocds_reference.json` is an OCDS 1.1.5 field
tree, not the executable PhilGEPS mapping. The actionable historical inputs are
`PHILGEPS_CANONICAL_FIELD_MAP.json`, `PHILGEPS_OCDS_CSV_CROSSWALK.md`,
`philgeps-1.5.json`, and `mphilgeps.json`.

These references support the proposed OCDS destinations, but they are not used
verbatim. The current normalized schema intentionally:

- separates `bid_published_date` from `award_published_date` instead of using
  the historical ambiguous `published_date`;
- uses `procuring_entity_name` and `procuring_entity_*` location names instead
  of `procuring_entity` and `pe_*`;
- uses `unit_of_measurement` instead of `uom`; and
- retains current-source fields such as `client_agency`, `created_by`, and
  `awardee_contact_person`, subject to publication policy.

The historical schema analysis also says that its 43-column schema contains a
bidder-list field. The verified 43-column files in the current dataset do not.
Therefore, actual source headers and the normalized Parquet schema remain the
source contract. The implemented `field_mapping.json` cites the pinned commit,
and differences are classified as accepted, rejected, or superseded. See
[Historical reference review](08_historical_reference_review.md).
