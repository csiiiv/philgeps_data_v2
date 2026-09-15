# Typed cleaned Parquet

## Output and layering

`output/philgeps_cleaned.parquet` is built from the immutable
`output/philgeps_normalized.parquet`. Both contain 17,528,727 rows from all 67
source files. The cleaned layer is 1,195,893,966 bytes (1.11 GiB).

The build is reproducible with:

```powershell
python scripts/build_cleaned_parquet.py
```

Pass `--force` to atomically replace an existing cleaned file. Cleaning rules
are explicit in `config/cleaning_rules.json`; no per-source Parquets or
intermediate datasets are created.

## Applied cleaning

### Null semantics

Empty strings and the case-insensitive literals `NULL`, `N/A`, `NA`, and
`NONE` become actual nulls. The observed item-budget sentinels `-1` and `-1.00`
also become null; affected rows retain the
`item_budget_not_provided_sentinel` quality flag.

### Typed values

Eight source date fields become timezone-naive `TIMESTAMP` values. Text dates
use `DD/MM/YYYY`; Excel dates use the 1899-12-30 serial-date epoch and retain
fractional times. Eleven out-of-range contract-end serials become null and are
flagged `invalid_contract_end_date`.

Monetary fields use `DECIMAL(38,4)`, preserving the greatest materially
observed precision while removing spreadsheet binary floating-point tails.
Quantity uses `DECIMAL(38,6)`. Contract duration and line-item number use
`BIGINT`. Bid references, award references, and eight-digit UNSPSC codes remain
strings because they are identifiers.

### Text and categories

All text receives NFC Unicode normalization and outer-whitespace trimming.
Organization names and controlled categories also collapse repeated whitespace.
The observed `DisApproved` bid status maps to `Disapproved`; source values such
as `Undefined` remain explicit categories rather than being guessed into nulls.

### Organization names

Display names are cleaned without merging entities. Three uppercase,
whitespace-normalized comparison keys are added:

- `procuring_entity_name_key`
- `client_agency_key`
- `awardee_organization_name_key`

Punctuation and spelling remain significant. These keys support later entity
resolution but are not entity IDs.

### Encoding defects

`_replacement_character_columns` identifies the exact columns containing a
Unicode replacement character. Ten affected cells occur across eight rows; no
replacement text is guessed.

## Quality flags

`_cleaning_issues` is a list of non-destructive row flags and
`_cleaning_issue_count` is its length. A flag is evidence for review, not an
automatic assertion that the record is wrong.

The completed build reports:

- `item_budget_not_provided_sentinel`: 556,415 rows
- `award_before_bid_published`: 170,702 rows
- `contract_end_before_notice_to_proceed`: 28,930 rows
- `contract_amount_exceeds_approved_budget`: 9,441 rows
- `item_budget_exceeds_approved_budget`: 5,169 rows
- `invalid_contract_end_date`: 11 rows
- `replacement_character`: 8 rows / 10 cells
- `missing_bid_reference`: 1 row

Implemented checks that produced zero rows include invalid UNSPSC format,
negative cleaned numeric values, closing before publication, and contract end
before effectivity.

## Validation

The build preserves every required provenance value and has zero duplicate
`(_source_file_id, _source_sheet, _source_row_number)` groups. Independent
post-build checks found zero remaining configured null literals, outer
whitespace, organization-key mismatches, or negative item budgets. A count,
XOR hash, and summed hash of the full provenance tuple match the normalized
input exactly.

Machine-readable results are in
`artifacts/cleaned_parquet_validation.json`.
