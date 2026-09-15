# Provenance and source traceability

## Requirement

Source references are breadcrumbs that let users double-check PhilGEPS data.
They are not formal citations and do not replace the source documents.

## Source identity

`RAW_DATA_DOWNLOADER/dataset/manifest.json` version 2 remains authoritative for:

- `source_file_id` and exact file checksum;
- original and normalized filenames;
- one or more `document_id` and source URLs;
- local downloaded path and manifest metadata.

OCDS tables store only source foreign keys and row locations. They do not repeat
URLs or filenames millions of times.

## Breadcrumb key

The authoritative source-row key is the tuple:

```text
(source_file_id, source_row_number)
```

Across all 17,528,727 current observations, this tuple has 17,528,727 distinct
values and no collisions. The human-facing form is:

```text
<source_file_id>:<source_row_number>
```

For example:

```text
pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24343
```

`source_sheet` remains stored as provenance and as a future disambiguator. The
current workbooks use only `Sheet1`, so it does not add uniqueness today; CSV
worksheet values are null. Every build must continue validating the two-column
key and must fail rather than silently collide if a future multi-sheet import
changes that invariant.

Physical row numbers match what a user sees in the source document: headered
CSV data typically begins at row 2, verified headerless CSV data at row 1, and
legacy Excel data at row 5.

## Callable breadcrumb lookup

`scripts/show_source_entry.py` accepts the compact breadcrumb and prints every
non-null source-preserving field as a Markdown table:

```powershell
python OCDS_ETL/scripts/show_source_entry.py `
  pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24343
```

Additional rows from the same source file can be requested together:

```powershell
python OCDS_ETL/scripts/show_source_entry.py `
  pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24343 `
  24344
```

Useful options are:

- `--layer normalized` for source-preserving strings; this is the default;
- `--layer cleaned` for typed cleaned values;
- `--include-null` to include fields that are null in every selected row;
- `--format json` for machine-readable output; and
- `--output <path>` to write the rendered result to a file.

The script resolves the normalized filename, SHA-256, worksheet, and original
source URLs through manifest v2. It also verifies that each requested
breadcrumb resolves to exactly one observation.

## Derived-record lineage

`record_sources.parquet` connects every OCDS-aligned record to all supporting
source rows. A release assembled from several line-item rows therefore has
several source links. An item or award can have a narrower source set.

When identical process states occur in more than one quarterly export:

- one content-addressed release is retained;
- every observation is retained in `record_sources`;
- no arbitrary filename is treated as the sole source;
- `is_preferred_source` can select a default breadcrumb for display without
  deleting alternatives.

## Preferred-source policy

Preference affects presentation only. Initial ranking criteria are:

1. source row with no cleaning issue affecting mapped fields;
2. headered export over a verified headerless duplicate, if content is equal;
3. source whose declared period agrees with record dates;
4. stable tie-break by `source_file_id`, sheet, and row.

The ranking rule and version are stored in `selection_basis`. Conflicting values
must not be hidden by this preference.

## Field contribution

Where practical, `source_fields` records the cleaned PhilGEPS fields used to
derive an entity. This is record-level, not a full cell-level provenance graph,
but it is sufficient to explain common mappings and locate the original row.

## Presentation example

The UI resolves the source ID through manifest v2 and renders:

```text
pgf_...:12345 · 2024-01--2024-03.csv · row 12,345 — View data · Open original
```

or:

```text
pgf_...:8201 · 2009-01--2009-12.xlsx · Sheet1 · row 8,201
```

The link target is a manifest URL; alternate URLs and the SHA-256 can appear in
a source-details panel.
