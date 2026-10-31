#!/usr/bin/env python3
"""Fill the official OCDS mapping templates with this pipeline's decisions.

Clones the two official templates from the workspace ``mapping_references/``
directory and writes this project's mapping into them:

1. Field Level Mapping Template (OCDS 1.1, Template Version 0.91)
   - the six ``(OCDS) n. ...`` stage sheets: fills the Mapping column with
     ``<local target> <- <normalized field>`` entries for every OCDS path
     our ``config/field_mapping.json`` feeds
   - any original mPhilGEPS mapping already present is preserved by moving
     it into the Notes column (``mPhilGEPS: ...``)
2. Codelist Mapping Template (OCDS 1.1.5, Template Version 0.2)
   - ``(Source) Codelists``: one row per source value across our five
     mapped domains, with the decision and status
   - closed-codelist sheets: fills Source codelist / Source code columns on
     matching code rows (classification -> procurementCategory,
     procurement_mode -> method, bid_notice_status -> tenderStatus,
     award_notice_status -> awardStatus), preserving the original mPhilGEPS
     fill in Notes

The templates describe the live mPhilGEPS database; this project maps the
legacy PhilGEPS 1.5 public exports. Outputs are documentation artifacts in
``artifacts/filled_templates/``: the JSON configs remain authoritative.

Usage:
    python fill_ocds_mapping_templates.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import openpyxl

PROJECT = Path(__file__).resolve().parents[1]

FIELD_TEMPLATE = (
    "2025_mPhilGEPS_OCDS - Field Level Mapping Template for OCDS 1.1 "
    "(Template Version 0.91) (1).xlsx"
)
CODELIST_TEMPLATE = (
    "Copy of OCDS - Codelist Mapping Template for OCDS 1.1.5 "
    "(Template Version 0.2) #public.xlsx"
)

SOURCE_LABEL = "PhilGEPS 1.5 (public exports)"

# ---------------------------------------------------------------------------
# Curated OCDS-path fills for the field-level template.
# Each entry: OCDS template path -> (targets, note)
#   targets: list of "local.target" strings; every one must exist in
#            config/field_mapping.json targets (validated at startup).
#   note:    optional suffix rendered after the targets.
# Normalized field names are looked up from the config so the dict cannot
# drift from it.

PATH_FILLS: dict[str, tuple[list[str], str]] = {
    # -- Tender stage ------------------------------------------------------
    "tender/id": (
        ["contracting_processes.source_process_identifier", "tenders.source_bid_reference"],
        "identity rule (docs/04)",
    ),
    "tender/title": (["tenders.title"], ""),
    "tender/status": (
        ["tenders.status", "tenders.source_status"],
        "codelist: tenderStatus",
    ),
    "tender/procuringEntity/name": (["parties.name"], "procuring entity mention"),
    "tender/procuringEntity/id": (["parties.name_key"], "conservative key"),
    "tender/items/id": (["tender_items.source_line_item_number"], ""),
    "tender/items/description": (
        ["tender_items.description", "tender_items.title"],
        "",
    ),
    "tender/items/classification/scheme": ([], "UNSPSC (fixed scheme)"),
    "tender/items/classification/id": (["tender_items.classification_id"], "UNSPSC code"),
    "tender/items/classification/description": (
        ["tender_items.classification_description"],
        "UNSPSC description",
    ),
    "tender/items/quantity": (["tender_items.quantity"], ""),
    "tender/items/unit/name": (["tender_items.unit_name"], ""),
    "tender/items/unit/value/amount": (
        ["tender_items.item_budget_amount"],
        "per-unit price (semantics confirmed by official template, docs/13)",
    ),
    "tender/value/amount": (["tenders.value_amount"], "approved budget"),
    "tender/procurementMethod": (
        ["tenders.procurement_method"],
        "codelist: method",
    ),
    "tender/procurementMethodDetails": (["tenders.procurement_method_details"], ""),
    "tender/mainProcurementCategory": (
        ["tenders.main_procurement_category"],
        "codelist: procurementCategory",
    ),
    "tender/enquiryPeriod/startDate": (
        ["tenders.prebid_date"],
        "candidate OCDS-native target (docs/13)",
    ),
    "tender/tenderPeriod/endDate": (
        ["tenders.closing_date"],
        "candidate OCDS-native target (docs/13)",
    ),
    "tender/awardPeriod/startDate": (["awards.date"], ""),
    "tender/contractPeriod/durationInDays": (
        ["tenders.contract_duration_days", "tenders.contract_duration_unit"],
        "safe day conversion, Day/s calendar only (docs/13 candidate)",
    ),
    # -- Award stage -------------------------------------------------------
    "awards/id": (["awards.source_award_reference"], "identity rule (docs/04)"),
    "awards/title": (["awards.title"], ""),
    "awards/status": (
        ["awards.status", "awards.source_status"],
        "codelist: awardStatus",
    ),
    "awards/date": (["awards.date"], ""),
    "awards/value/amount": (["awards.value_amount"], "contract amount"),
    "awards/suppliers/name": (
        ["award_suppliers.source_supplier_label"],
        "party mention; suppliers also in parties with 'supplier' role",
    ),
    # -- Contract stage ----------------------------------------------------
    "contracts/id": (["contracts.source_contract_number"], "identity rule (docs/04)"),
    "contracts/awardID": (
        ["awards.source_award_reference"],
        "join contracts to awards",
    ),
    "contracts/period/startDate": (["contracts.period_start"], "contract effectivity date"),
    "contracts/period/endDate": (["contracts.period_end"], ""),
    "contracts/value/amount": (
        ["contracts.value_amount"],
        "copied from award value with semantics flag",
    ),
    # -- General / parties -------------------------------------------------
    "buyer/name": (
        ["parties.name"],
        "client_agency, buyer candidate - unresolved (docs/13)",
    ),
    "parties/name": (
        ["parties.name"],
        "procuring_entity_name / client_agency / awardee_organization_name",
    ),
    "parties/id": (
        ["parties.name_key"],
        "conservative party dedup keys (*_name_key)",
    ),
    "parties/address/region": (
        ["parties.source_region"],
        "procuring_entity_region / awardee_region (PSGC pending)",
    ),
    "parties/address/locality": (
        ["parties.source_city_municipality"],
        "city/municipality; province kept in source_province (no OCDS slot)",
    ),
    "parties/address/countryName": (
        ["parties.source_country"],
        "awardee_country (address normalization pending)",
    ),
    "parties/contactPoint/name": (
        ["parties.contact_name"],
        "analytical only, privacy review pending",
    ),
    "parties/roles": (
        ["party_roles.procuringEntity", "party_roles.supplier", "party_roles.buyer_candidate"],
        "role assignments; buyer_candidate unresolved",
    ),
    "parties/details": (
        [
            "parties.government_branch",
            "parties.source_organization_type",
            "parties.organization_type_grouped",
            "parties.organization_size",
        ],
        "party classification details",
    ),
}

# Domain -> codelist section name in the closed-codelists sheet.
CLOSED_CODELIST_SECTION = {
    "classification": "Codelist: procurementCategory",
    "procurement_mode": "Codelist: method",
    "bid_notice_status": "Codelist: tenderStatus",
    "award_notice_status": "Codelist: awardStatus",
    # calendar_type has no OCDS codelist section in the template
}


def load_configs():
    field = json.loads(
        (PROJECT / "config" / "field_mapping.json").read_text(encoding="utf-8")
    )
    codelists = json.loads(
        (PROJECT / "config" / "codelist_mapping.json").read_text(encoding="utf-8")
    )
    # field -> targets, and reverse index target -> [fields]
    fields_by_target: dict[str, list[str]] = {}
    for field_name, spec in field["fields"].items():
        for target in spec["targets"]:
            fields_by_target.setdefault(target, []).append(field_name)
    # Validate curated fills against the config
    known = set(fields_by_target)
    unknown = sorted(
        {t for targets, _ in PATH_FILLS.values() for t in targets if t not in known}
    )
    if unknown:
        raise SystemExit(f"PATH_FILLS references unknown targets: {unknown}")
    return fields_by_target, codelists


def render_fill(targets: list[str], note: str, fields_by_target) -> str:
    parts = []
    for t in targets:
        fields = fields_by_target.get(t, [])
        parts.append(f"{t} <- {', '.join(fields)}" if fields else t)
    if note:
        parts.append(f"[{note}]")
    return " · ".join(parts)


def preserve_original(cell, label: str) -> None:
    """Move an existing mPhilGEPS fill into Notes before overwriting."""
    if cell.value in (None, ""):
        return
    existing = str(cell.value).strip()
    prefix = f"{label}: "
    if existing.startswith(prefix):
        return  # already preserved on a re-run
    notes_cell = cell.parent.cell(row=cell.row, column=8)  # Notes column H
    prior = str(notes_cell.value).strip() if notes_cell.value else ""
    kept = f"{prefix}{existing}"
    notes_cell.value = f"{kept} | {prior}" if prior else kept


def fill_field_template(src: Path, dst: Path, fields_by_target) -> int:
    wb = openpyxl.load_workbook(src)
    filled = 0
    for name in wb.sheetnames:
        if not name.startswith("(OCDS)"):
            continue
        ws = wb[name]
        for row in ws.iter_rows(min_row=5):
            path_cell = row[2] if len(row) > 2 else None  # column C
            map_cell = row[5] if len(row) > 5 else None  # column F
            if path_cell is None or map_cell is None:
                continue
            path = str(path_cell.value).strip() if path_cell.value else ""
            if path not in PATH_FILLS:
                continue
            targets, note = PATH_FILLS[path]
            preserve_original(map_cell, "mPhilGEPS")
            map_cell.value = render_fill(targets, note, fields_by_target)
            filled += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return filled


def fill_codelist_template(src: Path, dst: Path, codelists) -> tuple[int, int]:
    wb = openpyxl.load_workbook(src)

    # -- (Source) Codelists: one row per source value -----------------------
    ws = wb["(Source) Codelists"]
    r = ws.max_row + 1
    listed = 0
    for domain, spec in codelists["mappings"].items():
        destination = spec["destination"]
        for source_value, v in spec["values"].items():
            status = v.get("status")
            decision = v.get("destination_value")
            ws.cell(row=r, column=1, value=SOURCE_LABEL)
            ws.cell(row=r, column=2, value=domain)
            ws.cell(row=r, column=3, value=source_value)
            if decision:
                ws.cell(
                    row=r,
                    column=4,
                    value=f"{destination} = {decision}",
                )
            note = v.get("rationale") or ""
            ws.cell(row=r, column=7, value=f"[{status}] {note}".strip())
            r += 1
            listed += 1

    # -- Closed-codelist sheets: fill matching code rows --------------------
    filled = 0
    ws = wb["(OCDS) 1. Closed Codelists"]
    section = None
    domain = None
    filled_keys: set[tuple[str, str]] = set()
    for row in ws.iter_rows(min_row=4):
        first = row[0].value
        if first == "codelist_name":
            section = str(row[1].value) if row[1].value else None
            domain = next(
                (d for d, s in CLOSED_CODELIST_SECTION.items() if s == section), None
            )
            continue
        if domain is None or len(row) < 7:
            continue
        code_cell = row[1]
        source_codelist_cell = row[4]  # column E
        source_code_cell = row[5]  # column F
        if code_cell.value is None:
            continue
        ocds_code = str(code_cell.value).strip()
        key = (domain, ocds_code)
        if key in filled_keys:
            continue  # fill each code only once; later duplicates keep originals
        spec = codelists["mappings"][domain]
        matches = [
            (source_value, v)
            for source_value, v in spec["values"].items()
            if v.get("destination_value") == ocds_code
            and v.get("status") in ("accepted", "proposed")
        ]
        if not matches:
            continue
        preserve_original(source_code_cell, "mPhilGEPS")
        statuses = "/".join(sorted({v["status"] for _, v in matches}))
        source_codelist_cell.value = f"{SOURCE_LABEL} [{statuses}]"
        source_code_cell.value = " | ".join(s for s, _ in matches)
        filled_keys.add(key)
        filled += 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return filled, listed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--references-dir",
        type=Path,
        default=PROJECT.parent / "mapping_references",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT / "artifacts" / "filled_templates",
    )
    args = parser.parse_args()

    fields_by_target, codelists = load_configs()

    field_dst = args.output_dir / "PhilGEPS_1.5_exports_OCDS_Field_Mapping_FILLED.xlsx"
    codelist_dst = args.output_dir / "PhilGEPS_1.5_exports_OCDS_Codelist_Mapping_FILLED.xlsx"

    n_fields = fill_field_template(
        args.references_dir / FIELD_TEMPLATE, field_dst, fields_by_target
    )
    n_codes, n_listed = fill_codelist_template(
        args.references_dir / CODELIST_TEMPLATE, codelist_dst, codelists
    )

    print(f"field template : {n_fields} OCDS paths filled -> {field_dst}")
    print(f"codelist template: {n_codes} code rows filled, {n_listed} source values listed -> {codelist_dst}")


if __name__ == "__main__":
    main()
