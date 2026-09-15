# Current source inventory

This inventory describes `RAW_DATA_DOWNLOADER/dataset/` as downloaded on
2026-09-12. The historical analysis in `references/philgeps_schema.md` remains
useful for semantic column mapping, but it does not exactly describe these
physical files.

## Confirmed findings

- The manifest contains 68 document entries pointing to 67 local files.
- `files/2025_(JUL-SEPT).csv` has two manifest URLs for the same SHA-256.
- There are 67 physical files: 51 XLSX and 16 CSV.
- The physical files expose four meaningful layouts, plus a header-presence
  variation in CSV files.
- Eleven 2000–2010 XLSX files use the 40-column original layout with the header
  on visible Excel row 4.
- `Bid Notice and Award Details Oct-Dec 2017.xlsx` uses the same 40-column
  layout but calls the unit field `Unit of Measurement`.
- Thirty-nine XLSX files use a 43-column layout with the header on visible row
  1. This layout includes `Client Agency`, `Created By`, and `Awardee Contact
  Person`; it does not include `List of Bidder's`.
- Twelve CSV files use the 46-column location-enriched layout with a header on
  physical row 1.
- Four CSV files contain 46-column data but no header row:
  `2021_Oct-Dec.csv`, `2022_Apr-Jun.csv`, `2022 _Jul-Sep.csv`, and
  `2022 _Oct-Dec.csv`.
- All 67 source files have an explicit, unique `normalized_file_name` in
  manifest v2 using `YYYY-MM--YYYY-MM.ext`. The 2000 workbook is mapped to
  `2000-11--2000-12.xlsx` based on its embedded report period rather than its
  annual-looking original filename.

These differences are why schema detection and file-level provenance are part
of ingestion rather than assumptions based only on year or filename.

Run `python scripts/build_source_catalog.py` to reproduce the machine-readable
inventory and diagnostics.
