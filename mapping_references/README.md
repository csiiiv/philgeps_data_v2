# Mapping references

Official Open Contracting mapping templates, filled in 2025 by PS-DBM for the
modernized PhilGEPS (mPhilGEPS / PhilGEPS 2.0) database.

| File | What it is |
|---|---|
| `2025_mPhilGEPS_OCDS - Field Level Mapping Template for OCDS 1.1 (Template Version 0.91) (1).xlsx` | Field-level mapping of ~998 mPhilGEPS database elements to OCDS 1.1 paths, across six stage sheets (General, Planning, Tender, Award, Contract, Implementation) plus a Data Elements inventory |
| `Copy of OCDS - Codelist Mapping Template for OCDS 1.1.5 (Template Version 0.2) #public.xlsx` | PhilGEPS 1.5 `procurementMethod` source values mapped to the OCDS closed `procurementMethod` codelist |

## How they are used

These templates describe the **live mPhilGEPS relational database**, not the
legacy PhilGEPS 1.5 public exports this pipeline ingests. They are treated as
design references, not transformation specifications:

- [`OCDS_ETL/docs/13_official_mphilgeps_template_review.md`](../OCDS_ETL/docs/13_official_mphilgeps_template_review.md)
  records the full comparison — agreements, divergences, and open questions.
- [`OCDS_ETL/scripts/fill_ocds_mapping_templates.py`](../OCDS_ETL/scripts/fill_ocds_mapping_templates.py)
  clones these templates and fills them with this pipeline's mapping
  decisions; the filled copies live in
  `OCDS_ETL/artifacts/filled_templates/` and are served as viewer downloads.

Per the authority order in the review doc, these templates do not override
the verified corpus, the `DATA_NORMALIZATION` schema registry, or the pinned
OCDS 1.1.5 schema.
