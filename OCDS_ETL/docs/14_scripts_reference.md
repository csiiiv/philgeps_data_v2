# Script reference

Every script in `scripts/`, grouped by role. All are run from the
`OCDS_ETL/` directory and read `config/` plus stage-1 outputs from
`../DATA_NORMALIZATION/output/`.

## Build (pipeline)

| Script | Purpose | Key outputs |
|---|---|---|
| `build_parquet.py` | Build the resumable OCDS-aligned parquet tables from the cleaned layer | `outputs/parquet/*.parquet` (18 tables) |
| `build_canonical_parties.py` | Provisional canonical party clusters with supported aliases | `outputs/` party identity layers |
| `build_party_name_forms.py` | Compact, source-preserving party-name normalization dimension | `outputs/parquet/party_name_forms.parquet` |
| `build_party_resolution_candidates.py` | Traceable resolution candidates; never merges party records | `outputs/` candidate tables |
| `build_compiled_processes.py` | Preferred-release process index + compact multi-release history | `outputs/parquet/compiled_processes.parquet` |

## Validate

| Script | Purpose | Key outputs |
|---|---|---|
| `validate_mapping_config.py` | Checks field + codelist configs against the cleaned source: every source value mapped, no phantom entries | `artifacts/mapping_coverage.json` |
| `audit_filled_template.py` | Confirms the filled XLSX template covers every normalized field with descriptions | console report |

## Profile (design evidence)

| Script | Purpose | Key outputs |
|---|---|---|
| `profile_codelists.py` | Profiles source values needing OCDS codelist/semantic mappings | `artifacts/codelist_profile.*` |
| `profile_grain.py` | Profiles process and child grains without touching source data | `artifacts/grain_profile.md` |
| `profile_party_names.py` | Profiles conservative/legal-suffix party-name normalization | `artifacts/party_name_profile.md` |
| `prototype_ids.py` | Prototypes deterministic entity IDs and reports collisions | console + `artifacts/id_profile.test.md` |

## Documentation generators

| Script | Purpose | Key outputs |
|---|---|---|
| `fill_ocds_mapping_templates.py` | Clones the official templates in `../../mapping_references/` and fills them with this pipeline's mapping decisions (field-level Mapping cells + Data Elements sheet + codelist sheets) | `artifacts/filled_templates/*.xlsx` |
| `show_source_entry.py` | Resolves a source breadcrumb to the complete original observation | console JSON |

## Configuration (authoritative)

- [`config/field_mapping.json`](../config/field_mapping.json) — 66 normalized
  fields → OCDS star-schema targets, treatments, status.
- [`config/codelist_mapping.json`](../config/codelist_mapping.json) — source
  values → OCDS closed/open codelist codes across five domains, with
  rationale and status.
- Change configs first, then re-run the relevant build and regenerate the
  filled templates (`fill_ocds_mapping_templates.py`), the viewer download
  copies (frontend `npm run build` prebuild copies them), and re-audit with
  `audit_filled_template.py`.
