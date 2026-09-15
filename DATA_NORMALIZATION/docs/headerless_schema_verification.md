# Headerless CSV schema verification

**Schema result: PASS**

The first 5,000 records from each headerless file were compared with
4,992 sampled records across 12 headered
`location_46` files. Comparison used record width, per-column value types,
and semantic anchors for dates, money, statuses, identifiers, UNSPSC, and country.

All four headerless files map positionally to `location_46`. The 40- and
43-column schemas are rejected by width, and the 46-column semantic anchors
match the headered reference data.

## Per-file results

### `files/2021_Oct-Dec.csv`

- Schema: `location_46` (PASS)
- Sample width: {'46': 5000}
- Mean positional type distance from headered reference: 0.0248
- Claimed normalized period: `2021-10--2021-12.csv`
- Published-date period match: 0.0
- Period check: REVIEW

### `files/2022_Apr-Jun.csv`

- Schema: `location_46` (PASS)
- Sample width: {'46': 5000}
- Mean positional type distance from headered reference: 0.0172
- Claimed normalized period: `2022-04--2022-06.csv`
- Published-date period match: 1.0
- Period check: PASS

### `files/2022 _Jul-Sep.csv`

- Schema: `location_46` (PASS)
- Sample width: {'46': 5000}
- Mean positional type distance from headered reference: 0.0181
- Claimed normalized period: `2022-07--2022-09.csv`
- Published-date period match: 1.0
- Period check: PASS

### `files/2022 _Oct-Dec.csv`

- Schema: `location_46` (PASS)
- Sample width: {'46': 5000}
- Mean positional type distance from headered reference: 0.0303
- Claimed normalized period: `2022-10--2022-12.csv`
- Published-date period match: 1.0
- Period check: PASS

## Important period anomaly

`files/2021_Oct-Dec.csv` is structurally a valid headerless
`location_46` file, but every non-null sampled Published Date is in
October–December 2024, not 2021. Schema assignment and source-period
identity are separate questions. Its normalized filename should not be
treated as settled until overlap with the headered 2024 Q4 export is
profiled during full ingestion.
