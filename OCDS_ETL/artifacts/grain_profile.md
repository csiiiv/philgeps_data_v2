# PhilGEPS grain profile

Input: `C:\WORK\BetterGovPH\PHILGEPS_DATA_REWORK\DATA_NORMALIZATION\output\philgeps_cleaned.parquet`

Profile version: 1

This profile covers the complete cleaned Parquet.

## Recommendations

- Use valid-looking `bid_reference_no` as the process-key candidate. Manual review found that the small set of cross-entity cases are agency-label variants with matching solicitation numbers and titles; retain one process and flag the conflicting labels. For missing or placeholder values, use the profiled content composite when possible and a provenance fallback otherwise.
- Treat `solicitation_no` as a tender attribute, not an unconditional component of process identity, because it varies within some bid references.
- Version item states: `line_item_no` locates an item within a process but does not identify immutable content.
- Scope award identifiers to the process; award references are reused across processes.
- Scope contract identifiers to the related award; contract numbers are reused across processes and sometimes across awards in one process.
- Retain missing and ambiguous relationships in analytical tables with link statuses and publication-blocking quality issues.

## Overview

| Metric | Count |
|---|---:|
| `observation_rows` | 17,528,727 |
| `source_files` | 67 |
| `source_schemas` | 4 |
| `rows_with_cleaning_issues` | 762,381 |

## Process candidates

| Metric | Count |
|---|---:|
| `distinct_bid_references` | 10,293,935 |
| `rows_with_bid_reference` | 17,528,726 |
| `obvious_placeholder_reference_values` | 1 |
| `rows_with_obvious_placeholder_reference` | 405,345 |
| `references_with_multiple_entities` | 3 |
| `rows_in_multiple_entity_references` | 405,349 |
| `max_entities_per_reference` | 8,701 |
| `nonplaceholder_references_with_multiple_entities` | 2 |
| `rows_in_nonplaceholder_multiple_entity_references` | 4 |
| `references_with_multiple_solicitations` | 5 |
| `rows_in_multiple_solicitation_references` | 405,353 |
| `max_solicitations_per_reference` | 170,889 |
| `references_with_multiple_titles` | 12 |
| `references_seen_in_multiple_files` | 171,966 |
| `references_seen_in_multiple_schemas` | 81 |
| `missing_bid_reference_rows` | 1 |
| `rows_requiring_process_key_fallback` | 405,346 |

## Fallback process candidates

| Metric | Count |
|---|---:|
| `candidate_rows` | 405,346 |
| `rows_with_solicitation_number` | 227,552 |
| `rows_with_entity` | 405,346 |
| `rows_with_title` | 404,066 |
| `rows_with_publication_date` | 253,151 |
| `rows_using_content_composite` | 252,692 |
| `rows_using_source_row_fallback` | 152,654 |
| `distinct_content_composite_candidates` | 206,640 |
| `repeated_composite_groups` | 11,481 |
| `rows_grouped_beyond_first` | 46,052 |
| `composite_groups_seen_in_multiple_files` | 5,983 |
| `max_rows_per_composite` | 329 |
| `max_line_numbers_per_composite` | 137 |
| `max_awards_per_composite` | 96 |

## Solicitation candidates

| Metric | Count |
|---|---:|
| `distinct_solicitation_numbers` | 4,931,821 |
| `solicitations_with_multiple_bid_references` | 587,859 |
| `rows_in_reused_solicitations` | 4,053,105 |
| `max_bid_references_per_solicitation` | 18,192 |
| `solicitations_with_multiple_entities` | 280,588 |

## Item grain

| Metric | Count |
|---|---:|
| `evidence_rows` | 11,119,241 |
| `evidence_rows_missing_line_number` | 519 |
| `evidence_rows_missing_process_reference` | 0 |
| `process_line_groups` | 8,877,073 |
| `repeated_process_line_groups` | 537,533 |
| `repeated_rows_beyond_first` | 2,241,649 |
| `process_line_groups_with_conflicting_content` | 3,514 |
| `rows_in_conflicting_process_line_groups` | 10,625 |
| `max_signatures_per_process_line` | 25 |

## Award grain

| Metric | Count |
|---|---:|
| `evidence_rows` | 6,499,122 |
| `evidence_rows_missing_award_reference` | 0 |
| `evidence_rows_missing_process_reference` | 0 |
| `process_award_groups` | 4,600,588 |
| `repeated_process_award_groups` | 406,463 |
| `process_award_groups_with_conflicting_content` | 0 |
| `rows_in_conflicting_process_award_groups` | 0 |
| `process_awards_with_multiple_suppliers` | 0 |
| `award_references_reused_across_processes` | 5,927 |
| `rows_in_cross_process_award_references` | 29,632 |
| `max_processes_per_award_reference` | 5 |

## Contract grain and links

| Metric | Count |
|---|---:|
| `evidence_rows` | 4,788,907 |
| `evidence_rows_missing_contract_number` | 2,733,103 |
| `evidence_rows_missing_award_reference` | 0 |
| `evidence_rows_missing_process_reference` | 0 |
| `process_contract_groups` | 1,560,531 |
| `repeated_process_contract_groups` | 84,945 |
| `process_contract_groups_with_conflicting_content` | 72,780 |
| `process_contracts_missing_award_link` | 0 |
| `process_contracts_with_ambiguous_award_link` | 74,870 |
| `contract_numbers_reused_across_processes` | 100,738 |
| `rows_in_cross_process_contract_numbers` | 589,248 |
| `max_processes_per_contract_number` | 5,210 |

## Supplier grain and links

| Metric | Count |
|---|---:|
| `evidence_rows` | 6,448,977 |
| `evidence_rows_missing_supplier_name` | 0 |
| `evidence_rows_missing_award_reference` | 0 |
| `evidence_rows_missing_process_reference` | 0 |
| `distinct_supplier_name_keys` | 125,086 |
| `process_awards_with_multiple_supplier_names` | 0 |
| `max_supplier_names_per_process_award` | 1 |
| `normalized_name_keys_with_multiple_spellings` | 0 |
| `rows_with_joint_venture_value` | 65,326 |

## Repeated observations

| Metric | Count |
|---|---:|
| `distinct_business_observations` | 15,326,658 |
| `repeated_observation_groups` | 522,475 |
| `repeated_rows_beyond_first` | 2,202,069 |
| `cross_file_repeat_groups` | 305,779 |
| `rows_in_cross_file_repeat_groups` | 1,862,855 |
| `max_repetitions` | 755 |

## Interpretation boundary

Repeated or conflicting values are profiling signals, not automatic errors. Later ETL rules must preserve source breadcrumbs and classify relationships as matched, missing, or ambiguous. Only the matched publication-eligible subset is subject to strict OCDS references.
