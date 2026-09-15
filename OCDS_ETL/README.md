# PhilGEPS OCDS ETL

This project transforms the immutable cleaned PhilGEPS observations in
`../DATA_NORMALIZATION/output/philgeps_cleaned.parquet` into an OCDS-aligned
multi-table Parquet model and, later, standards-valid OCDS JSON release and
record packages.

The Parquet model is an analytical serialization of OCDS concepts. Formal OCDS
conformance applies to exported JSON that validates against the pinned OCDS
1.1.5 schemas, not to Parquet files by themselves.

## Status

The documentation and design contracts are complete. The full grain and
candidate-key profile has passed its reconciliation checks and is available as
[`artifacts/grain_profile.md`](artifacts/grain_profile.md) and
[`artifacts/grain_profile.json`](artifacts/grain_profile.json). Versioned field,
codelist, and identity configurations now exist under `config/`, and all 66
cleaned input fields plus every observed value in the five mapped categorical
domains pass configuration coverage validation. The complete multi-table build
has been published under `outputs/parquet/` and passes primary-key,
foreign-key, relationship, provenance, and full source-observation coverage
checks. It contains 10,653,920 releases and 109,929,027 record-source links for
all 17,528,727 source observations. Party-name profiling and the compact
`party_name_forms.parquet` candidate-key layer are also available; no candidate
key is treated as a canonical legal entity. The evidence-only
`party_resolution_candidates.parquet` contains 399,154 traceable party mentions
across 1,962 candidate groups. A stricter provisional promotion layer contains
318 analytical canonical parties and 7,993 location-supported aliases; it
leaves 9,375 unsupported mentions from those groups unresolved and assigns no
official organization identifiers. The compiled analytical layer now selects
one preferred release for all 10,653,228 processes while retaining all 1,384
release states belonging to the 692 multi-release processes.

## Inputs and source of truth

- Cleaned analytical input:
  `../DATA_NORMALIZATION/output/philgeps_cleaned.parquet`
- Immutable source-preserving layer:
  `../DATA_NORMALIZATION/output/philgeps_normalized.parquet`
- Source registry and URLs:
  `../RAW_DATA_DOWNLOADER/dataset/manifest.json`

PhilGEPS documents remain the source of truth. Every derived record must retain
a reversible breadcrumb through `source_file_id`, worksheet, and physical row.
The compact human-facing form is `source_file_id:source_row_number`. Resolve a
breadcrumb to a complete Markdown table with
`scripts/show_source_entry.py`; see the [provenance guide](docs/06_provenance.md).

## Documentation

1. [Scope and principles](docs/01_scope_and_principles.md)
2. [Architecture](docs/02_architecture.md)
3. [Parquet table contracts](docs/03_table_contracts.md)
4. [Identifiers and releases](docs/04_identifiers_and_releases.md)
5. [PhilGEPS-to-OCDS mapping](docs/05_philgeps_ocds_mapping.md)
6. [Provenance](docs/06_provenance.md)
7. [Validation and implementation plan](docs/07_validation_and_plan.md)
8. [Historical reference review](docs/08_historical_reference_review.md)
9. [Processes and actual examples](docs/09_processes_and_examples.md)
10. [Architecture decision records](docs/10_architecture_decision_records.md)
11. [Party-name normalization](docs/11_party_name_normalization.md)
12. [Compiled process views](docs/12_compiled_process_views.md)

Machine-readable design evidence includes
[`artifacts/codelist_profile.json`](artifacts/codelist_profile.json) and
[`artifacts/mapping_coverage.json`](artifacts/mapping_coverage.json). Party-name
evidence is in [`artifacts/party_name_profile.json`](artifacts/party_name_profile.json).
Resolution-evidence results are in
[`artifacts/party_resolution_profile.json`](artifacts/party_resolution_profile.json).
Compiled-process validation is in
[`artifacts/compilation_validation.json`](artifacts/compilation_validation.json).

## Standards baseline

- OCDS version: **1.1.5**
- Canonical release schema:
  `https://standard.open-contracting.org/schema/1__1__5/release-schema.json`
- Canonical record-package schema:
  `https://standard.open-contracting.org/schema/1__1__5/record-package-schema.json`
- Currency assumption pending confirmation: `PHP`
- Source timestamps are currently timezone-naive; JSON publication requires an
  explicit timezone policy, expected to be `Asia/Manila` (`+08:00`).

The historical project's complete
[`references/`](https://github.com/csiiiv/philgeps-ocds-schema-analysis/tree/main/references)
directory was reviewed on 2026-09-12. Its OCDS field tree, canonical field map,
CSV crosswalk, and PhilGEPS 1.5/mPhilGEPS templates are design inputs. They do
not override the schemas observed in the current source files. The reference is
pinned to commit `269a19b7288125814baa6aabf30d33ebf9c12a1a`; reused and changed
rules are recorded in the mapping configuration and historical review.
