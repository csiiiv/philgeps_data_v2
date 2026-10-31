# Official mPhilGEPS mapping template review

## References reviewed

Two official Open Contracting templates were filled in 2025 for the
mPhilGEPS (PhilGEPS 2.0) database. They live outside this package in the
workspace `mapping_references/` directory:

1. `2025_mPhilGEPS_OCDS - Field Level Mapping Template for OCDS 1.1
   (Template Version 0.91) (1).xlsx` — field-level mapping of ~998
   mPhilGEPS database elements to OCDS 1.1 paths, across six stage sheets
   (General, Planning, Tender, Award, Contract, Implementation).
2. `Copy of OCDS - Codelist Mapping Template for OCDS 1.1.5 (Template
   Version 0.2) #public.xlsx` — PhilGEPS 1.5 `procurementMethod` source
   values mapped to the OCDS closed `procurementMethod` codelist.

Review date: 2026-10-31.

## Scope caveat

The templates describe the **live mPhilGEPS relational database**
(`tenders`, `awards`, `vendors`, `notice_to_proceed`, ... tables), not the
CSV/XLSX public exports this pipeline ingests. The corpus here is legacy
PhilGEPS 1.5 export data. Agreements are therefore **semantic** confirmations
(source concepts resolve to the same OCDS paths), not literal column matches.

Per the authority order in
[08_historical_reference_review.md](08_historical_reference_review.md), these
templates are strong design references but do not override the verified
corpus, the `DATA_NORMALIZATION` registry, or the pinned OCDS 1.1.5 schema.

## Field-level findings

Our `config/field_mapping.json` (66 entries) agrees with the official
template on every shared concept. Key confirmations:

| Normalized field | Our target (local table) | Official template OCDS path | Verdict |
|---|---|---|---|
| `notice_title` | `tenders.title` | `tender/title` | agree |
| `classification` | `tenders.main_procurement_category` (+source) | `tender/mainProcurementCategory` | agree |
| `procurement_mode` | `tenders.procurement_method` (+details) | `tender/procurementMethod` (+`procurementMethodDetails`) | agree, incl. the two-column pattern |
| `approved_budget` | `tenders.value_amount` | `tender/value/amount` | agree |
| `item_description` | `tender_items.description` | `tender/items/description` | agree |
| `quantity` | `tender_items.quantity` | `tender/items/quantity` | agree |
| `unit_of_measurement` | `tender_items.unit_name` | `tender/items/unit/name` | agree |
| `award_date` | `awards.date` | `awards/date` | agree |
| `contract_amount` | `awards.value_amount` | `awards/value/amount` | agree |
| `awardee_organization_name` | `award_suppliers.source_supplier_label` | `awards/suppliers/name` | agree |
| `contract_effectivity_date` | `contracts.period_start` | `contracts/period/startDate` | agree |
| `contract_end_date` | `contracts.period_end` | `contracts/period/endDate` | agree |
| `bid_notice_status` | `tenders.status` (+source) | `tender/status` | agree |
| `award_notice_status` | `awards.status` (+source) | `awards/status` | agree |

### Semantics resolved by the template

- `item_budget` (ours: `tender_items.item_budget_amount`, treatment
  `direct_local_pending_semantics`): the template maps product/unit price to
  `tender/items/unit/value/amount` ("monetary value of a single unit") and
  awarded unit price to `awards/items/unit/value/amount`. This supplies the
  pending semantics: **item budget is the per-unit price**. Candidate future
  OCDS targets noted below.
- Buyer vs procuring entity: the template keeps `buyer` and
  `tender/procuringEntity` as distinct party references (both resolvable to
  the `departments` table in practice). This supports eventually resolving
  our `client_agency` (currently `unresolved`, `party_roles.buyer_candidate`)
  toward the `buyer` role when it differs from the procuring entity.

### Divergences and candidates (documented, no config change yet)

1. `reason_for_award`: the template maps "Reason of Award" to
   `tender/awardCriteria` (example value "Single Calculated and Responsive
   Quotation…"). Our corpus values ("Lowest Calculated and Responsive Bid"
   etc.) are free text and the OCDS `awardCriteria` codelist is closed, so
   our `awards.description` target remains correct for publication; the
   template's intent is best honored by additionally considering
   `tender/awardCriteriaDetails` (open detail field) as a future target.
2. `prebid_date`: template maps pre-bid meeting datetimes to
   `tender/enquiryPeriod/startDate`/`endDate`. Ours is analytical
   (`tenders.prebid_date`); `tender/enquiryPeriod` is a candidate OCDS-native
   target.
3. `closing_date`: template maps tender close to
   `tender/tenderPeriod/endDate`. Ours is analytical
   (`tenders.closing_date`); `tender/tenderPeriod/endDate` is a candidate
   OCDS-native target.
4. `contract_duration`: template maps "Contract Period" (days) to
   `tender/contractPeriod/durationInDays`. Ours is analytical
   (`tenders.contract_duration_days`); the OCDS-native path is a candidate
   future target.
5. `unspsc_code`/`unspsc_description`: template uses
   `tender/items/classification` with UNSSPSC scheme notes (second/third
   level). Ours (`tender_items.classification_id`/`_description`) matches;
   making the `UNSPSC` scheme explicit is a future refinement.
6. Template quirk (theirs, not ours): `tender/items/unit/name` is mapped
   from `Tenders Items (Item Name)` — an apparent template slip; unit name
   elsewhere maps from `Unit of Measure`. Our mapping follows the coherent
   reading.

## Codelist findings

The official codelist template resolves PhilGEPS 1.5 `procurementMethod`
values to the closed OCDS `procurementMethod` codelist:

| Official source value | Official OCDS code | Our `codelist_mapping.json` | Action |
|---|---|---|---|
| Competitive Bidding | `open` | `Public Bidding`/NCB/ICB → `open` (accepted) | agree (label renamed across eras) |
| Limited Source | `limited` | `Limited Source Bidding (Sec. 49)` → `selective` (accepted) | **divergence — flagged for decision** |
| Negotiated Procurement - Emergency Cases | `direct` | `unresolved` | filled as `proposed` with rationale |
| Negotiated Procurement - Two Failed Biddings | `direct` | `unresolved` | filled as `proposed` with rationale |
| Negotiated Procurement - Agency to Agency | `direct` | `direct` (proposed) | rationale added citing template |
| Shopping | not decided in template | `limited` (proposed) | unchanged (no official position) |

The Limited Source divergence is recorded in the config rationale: our
`selective` follows the OCDS definition (only qualified suppliers invited,
consistent with RA 9184 Sec. 49 pre-selected shortlists); the official
template chose `limited`. Because the template outranks nothing in our
authority order and both codes are defensible, the entry stays `accepted`
with a divergence note, pending a policy decision.

Status codelists (`tender/status`, `awards/status`) are structurally
confirmed; the template does not enumerate value mappings for them.

## Changes made in this review

- `config/codelist_mapping.json`: three previously-unresolved
  `Negotiated Procurement` entries filled as `proposed` (destination
  `direct`) citing the official template; rationale added to
  Agency-to-Agency and Limited Source entries.
- This document; README documentation index updated.
- No changes to `config/field_mapping.json` targets (agreement confirmed;
  future-target candidates recorded above only).

## Filled template copies

`scripts/fill_ocds_mapping_templates.py` regenerates filled copies of both
official templates from the authoritative JSON configs:

- `artifacts/filled_templates/PhilGEPS_1.5_exports_OCDS_Field_Mapping_FILLED.xlsx`
  — 94 OCDS paths filled with `<local target> <- <normalized field>` cells;
  original mPhilGEPS fills preserved in the Notes column.
- `artifacts/filled_templates/PhilGEPS_1.5_exports_OCDS_Codelist_Mapping_FILLED.xlsx`
  — all 46 source values listed in `(Source) Codelists`; 15 code rows filled
  across the four mapped closed codelists (tenderStatus, method,
  procurementCategory, awardStatus), originals preserved in Notes.

Re-run after any config change:

```bash
python OCDS_ETL/scripts/fill_ocds_mapping_templates.py
```
