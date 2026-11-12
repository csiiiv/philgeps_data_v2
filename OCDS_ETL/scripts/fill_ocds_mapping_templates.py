#!/usr/bin/env python3
"""Fill the official OCDS mapping templates with this pipeline's decisions.

Clones the two official templates from the workspace ``mapping_references/``
directory and fills them the way a data steward would by hand:

1. Field Level Mapping Template (OCDS 1.1, Template Version 0.91)
   - the ``(OCDS) n. ...`` stage sheets: Mapping cells read
     ``tenders (title, status)`` in the same style the mPhilGEPS authors
     used; the source normalized fields are named in plain sentences in
     the Notes column. Original mPhilGEPS fills are preserved in Notes as
     ``mPhilGEPS: ...``.
   - ``2. Data Elements``: one row per normalized field, appended with the
     template's own ``=CONCATENATE`` display formula, real data types in
     the Data Type column, and plain-language publication notes.
2. Codelist Mapping Template (OCDS 1.1.5, Template Version 0.2)
   - ``(Source) Codelists``: source values under their source codelist
     names (``procurementMethod`` etc.), carrying the template's
     ``=CONCATENATE`` lookup-key formula so the closed-codelist sheet's
     VLOOKUPs resolve; decisions are written as plain sentences. Values
     the official template already inventories are updated in place
     instead of duplicated.
   - closed-codelist sheets: Source codelist / Source code columns get the
     plain codelist name and primary source value; additional source
     values are listed in Notes. Original mPhilGEPS fills are preserved.

The templates describe the live mPhilGEPS database; this project maps the
legacy PhilGEPS 1.5 public exports (the ``PhilGEPS 1.5`` data source row
already present in both templates). Outputs are documentation artifacts in
``artifacts/filled_templates/``: the JSON configs remain authoritative.

Usage:
    python fill_ocds_mapping_templates.py
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
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

# Typed layer sampled for the Data Elements 'Example (optional)' column.
EXAMPLES_SOURCE = PROJECT.parent / "DATA_NORMALIZATION" / "output" / "philgeps_cleaned.parquet"

# Fields where a real example would expose personal data: no example.
PRIVACY_HOLD_FIELDS = {"awardee_contact_person", "created_by"}

SOURCE_LABEL = "PhilGEPS 1.5"

# Section name used for our element rows in '2. Data Elements' (column C).
# The template intends C to be the source table/dataset; ours is the typed
# cleaned layer. Mapping cells on the stage sheets reference elements as
# '<section> (<field>)', exactly like the mPhilGEPS 'Tenders (Tender ID)'.
ELEMENT_SECTION = "philgeps_cleaned"

# Source codelist names, as a curator would name them in the template.
# 'procurementMethod' matches the name the official template already uses.
CODELIST_NAMES = {
    "classification": "procurementCategory",
    "procurement_mode": "procurementMethod",
    "bid_notice_status": "bidNoticeStatus",
    "award_notice_status": "awardNoticeStatus",
    "calendar_type": "calendarType",
}

STATUS_SENTENCES = {
    "accepted": "Accepted.",
    "proposed": "Proposed mapping - confirm before publication.",
    "unresolved": "Not yet mapped.",
}

# ---------------------------------------------------------------------------
# Curated OCDS-path fills for the field-level template.
# Each entry: OCDS template path -> (targets, mapping_text, note)
#   targets:      list of "local.target" strings; every one must exist in
#                 config/field_mapping.json targets (validated at startup).
#   mapping_text: optional explicit Mapping-cell text; when omitted it is
#                 derived from the targets as "table (column, column)".
#   note:         plain sentence for the Notes column (source fields are
#                 prepended automatically).
FIELD_NOTES = {
    "tender/id": "Process identity follows the identity rules in docs/04.",
    "tender/status": "Status via the tenderStatus codelist.",
    "tender/procurementMethod": "Method via the method codelist.",
    "tender/mainProcurementCategory": "Category via the procurementCategory codelist.",
    "tender/items/classification/scheme": "Classification scheme is fixed to UNSPSC.",    "tender/items/classification/id": "UNSPSC code as published.",
    "tender/items/unit/value/amount": "Per-unit price; semantics confirmed against the official template (docs/13).",
    "tender/procurementMethodDetails": "Solicitation number retained as process detail.",
    "tender/enquiryPeriod/startDate": "Candidate OCDS-native target (docs/13).",
    "tender/tenderPeriod/endDate": "Candidate OCDS-native target (docs/13).",
    "tender/contractPeriod/durationInDays": "Safe day conversion for Day/s durations only (docs/13 candidate).",
    "tender/procuringEntity/name": "Procuring entity mention; see also buyer/name.",
    "tender/procuringEntity/id": "Conservative party dedup key.",
    "awards/id": "Identity follows the identity rules in docs/04.",
    "awards/status": "Status via the awardStatus codelist.",
    "awards/value/amount": "Contract amount as awarded.",
    "awards/suppliers/name": "Party mention; suppliers also appear in parties with the supplier role. Joint-venture labels are preserved unparsed (unresolved).",
    "contracts/id": "Identity follows the identity rules in docs/04.",
    "contracts/awardID": "Joins contracts to awards.",
    "contracts/period/startDate": "Contract effectivity date.",
    "contracts/value/amount": "Copied from the award value, with a semantics flag.",
    "contracts/status": "Derived from the notice-to-proceed date (analytical only).",
    "contracts/description": "No description is published; the contract number is carried instead.",
    "buyer/name": "Client agency; buyer role unresolved (docs/13).",
    "parties/name": "Procuring entity, client agency, and awardee mentions.",
    "parties/id": "Conservative party dedup keys (*_name_key).",
    "parties/address/region": "PSGC normalization pending.",
    "parties/address/locality": "Province is kept in a local column; OCDS has no province slot.",
    "parties/address/countryName": "Address normalization pending.",
    "parties/contactPoint/name": "Analytical only; privacy review pending.",
    "parties/roles": "Role assignments; the buyer_candidate role is unresolved.",
    "parties/details": "Party classification details.",
    "relatedProcesses/identifier": "Process identity; ocid registration pending (docs/04).",
    "tender/documents/datePublished": "Bid notice publication date.",
    "awards/documents/datePublished": "Award notice publication date.",
    "tender/documents/documentType": "Notice type kept in a source column; documentType is analytical only.",
    "awards/documents/documentType": "Award type kept in a source column; documentType is analytical only.",
    "tender/procurementMethodRationale": "Analytical columns retained beside the procurement method (docs/03).",
}

PATH_FILLS: dict[str, tuple[list[str], str | None]] = {
    # -- Tender stage ------------------------------------------------------
    "tender/id": (["contracting_processes.source_process_identifier", "tenders.source_bid_reference"], None),
    "tender/title": (["tenders.title"], None),
    "tender/status": (["tenders.status", "tenders.source_status"], None),
    "tender/procuringEntity/name": (["parties.name"], None),
    "tender/procuringEntity/id": (["parties.name_key"], None),
    "tender/items/id": (["tender_items.source_line_item_number"], None),
    "tender/items/description": (["tender_items.description", "tender_items.title"], None),
    "tender/items/classification/scheme": ([], None),
    "tender/items/classification/id": (["tender_items.classification_id"], None),
    "tender/items/classification/description": (["tender_items.classification_description"], None),
    "tender/items/quantity": (["tender_items.quantity"], None),
    "tender/items/unit/name": (["tender_items.unit_name"], None),
    "tender/items/unit/value/amount": (["tender_items.item_budget_amount"], None),
    "tender/value/amount": (["tenders.value_amount"], None),
    "tender/procurementMethod": (["tenders.procurement_method"], None),
    "tender/procurementMethodDetails": (["tenders.procurement_method_details", "tenders.solicitation_number"], None),
    "tender/mainProcurementCategory": (["tenders.main_procurement_category"], None),
    "tender/enquiryPeriod/startDate": (["tenders.prebid_date"], None),
    "tender/tenderPeriod/endDate": (["tenders.closing_date"], None),
    "tender/awardPeriod/startDate": (["awards.date"], None),
    "tender/contractPeriod/durationInDays": (["tenders.contract_duration_days", "tenders.contract_duration_unit"], None),
    # -- Award stage -------------------------------------------------------
    "awards/id": (["awards.source_award_reference"], None),
    "awards/title": (["awards.title"], None),
    "awards/description": (["awards.description"], None),
    "awards/status": (["awards.status", "awards.source_status"], None),
    "awards/date": (["awards.date"], None),
    "awards/value/amount": (["awards.value_amount"], None),
    "awards/suppliers/name": (["award_suppliers.source_supplier_label", "award_suppliers.source_joint_venture"], None),
    # -- Contract stage ----------------------------------------------------
    "contracts/id": (["contracts.source_contract_number"], None),
    "contracts/awardID": (["awards.source_award_reference"], None),
    "contracts/status": (["contracts.notice_to_proceed_date"], None),
    "contracts/description": (["contracts.source_contract_number"], None),
    "contracts/period/startDate": (["contracts.period_start"], None),
    "contracts/period/endDate": (["contracts.period_end"], None),
    "contracts/value/amount": (["contracts.value_amount"], None),
    # -- General / parties -------------------------------------------------
    "buyer/name": (["parties.name"], None),
    "parties/name": (["parties.name"], None),
    "parties/id": (["parties.name_key"], None),
    "parties/address/region": (["parties.source_region"], None),
    "parties/address/locality": (["parties.source_city_municipality"], None),
    "parties/address/countryName": (["parties.source_country"], None),
    "parties/contactPoint/name": (["parties.contact_name"], None),
    "parties/roles": (["party_roles.procuringEntity", "party_roles.supplier", "party_roles.buyer_candidate"], None),
    "parties/details": (
        [
            "parties.government_branch",
            "parties.source_organization_type",
            "parties.organization_type_grouped",
            "parties.organization_size",
            "parties.source_province",
        ],
        None,
    ),
    # -- Date evidence -----------------------------------------------------
    "tender/documents/datePublished": (["tenders.date_published"], None),
    "awards/documents/datePublished": (["awards.date_published"], None),
    "tender/documents/documentType": (["tenders.source_notice_type"], None),
    "awards/documents/documentType": (["awards.source_award_type"], None),
    # -- Related processes -------------------------------------------------
    "relatedProcesses/identifier": (["contracting_processes.source_process_identifier"], None),
    "tender/procurementMethodRationale": (
        [
            "tenders.trade_agreement",
            "tenders.business_category",
            "tenders.funding_source",
            "tenders.funding_instrument",
            "tenders.area_of_delivery",
        ],
        None,
    ),
}

# ---------------------------------------------------------------------------
# Descriptions for the normalized/cleaned fields (source semantics; derived
# from DATA_NORMALIZATION docs and cleaning rules).

FIELD_DESCRIPTIONS: dict[str, str] = {
    "bid_reference_no": "Bid notice reference number; the published process identifier",
    "solicitation_no": "Solicitation number printed on the notice",
    "notice_title": "Title of the bid notice",
    "notice_type": "Notice type as printed (e.g. Invitation to Bid)",
    "classification": "Goods / Civil Works / Consulting Services classification",
    "business_category": "Business category as printed on the notice",
    "funding_source": "Funding source as printed (e.g. GOP)",
    "funding_instrument": "Funding instrument as printed",
    "procurement_mode": "Procurement mode / method label as printed",
    "trade_agreement": "Applicable trade agreement, if any",
    "approved_budget": "Approved budget of the contract (ABC), PHP",
    "bid_published_date": "Date the bid notice was published",
    "closing_date": "Bid closing date",
    "prebid_date": "Pre-bid conference date",
    "area_of_delivery": "Delivery place as printed",
    "contract_duration": "Contract duration as printed (numeric part)",
    "calendar_type": "Duration unit: Day/s, Month/s, or Year/s",
    "line_item_no": "Line item number within the notice",
    "item_name": "Item short name as printed",
    "item_description": "Full item description",
    "quantity": "Quantity ordered",
    "unit_of_measurement": "Unit of measure label",
    "item_budget": "Approved budget for this line item (per-unit price)",
    "unspsc_code": "UNSPSC classification code",
    "unspsc_description": "UNSPSC classification description",
    "bid_notice_status": "Notice status as printed (e.g. Active, Awarded)",
    "created_by": "User who encoded the notice (analytical only)",
    "award_reference_no": "Award notice reference number",
    "award_title": "Title of the award",
    "award_type": "Award type as printed (e.g. Notice of Award)",
    "award_date": "Date of award",
    "award_published_date": "Date the award notice was published",
    "contract_amount": "Awarded contract amount, PHP",
    "award_notice_status": "Award status as printed (e.g. Posted, Updated)",
    "reason_for_award": "Reason for award as printed",
    "contract_no": "Contract number as printed",
    "notice_to_proceed_date": "Notice-to-proceed date",
    "contract_effectivity_date": "Contract effectivity date (start)",
    "contract_end_date": "Contract end date",
    "procuring_entity_name": "Procuring entity organization name",
    "procuring_entity_name_key": "Conservative dedup key for procuring_entity_name",
    "client_agency": "Client agency as printed (buyer candidate; unresolved)",
    "client_agency_key": "Conservative dedup key for client_agency",
    "awardee_organization_name": "Awardee organization name as printed",
    "awardee_organization_name_key": "Conservative dedup key for awardee_organization_name",
    "awardee_contact_person": "Awardee contact person (analytical only, privacy hold)",
    "awardee_joint_venture": "Awardee joint-venture label as printed (unparsed)",
    "procuring_entity_region": "Procuring entity region (PSGC pending)",
    "procuring_entity_province": "Procuring entity province (PSGC pending)",
    "procuring_entity_city_municipality": "Procuring entity city/municipality (PSGC pending)",
    "government_branch": "Government branch label",
    "procuring_entity_organization_type": "PE organization type label",
    "procuring_entity_organization_type_grouped": "PE organization type, grouped",
    "awardee_country": "Awardee country label (address normalization pending)",
    "awardee_region": "Awardee region (PSGC pending)",
    "awardee_province": "Awardee province (PSGC pending)",
    "awardee_city_municipality": "Awardee city/municipality (PSGC pending)",
    "awardee_size": "Awardee size label (small/medium/large)",
    "_source_file_id": "Source file identifier (provenance)",
    "_source_sheet": "Source sheet name (provenance)",
    "_source_row_number": "Source row number (provenance)",
    "_source_schema_id": "Source schema variant id (provenance)",
    "_extra_values": "Cells beyond expected column count (data quality)",
    "_replacement_character_columns": "Columns containing replacement characters (data quality)",
    "_cleaning_issues": "Cleaning issue codes for the row (data quality)",
    "_cleaning_issue_count": "Count of cleaning issues for the row (data quality)",
}

# Data types as they exist in philgeps_cleaned (typed layer), expressed in
# the template's own vocabulary (its Data Type column is validated to
# string,integer,long,double,float,date,date-time,codelist,other).
# Everything not listed is a string, matching the cleaned layer's dominant type.
FIELD_TYPES: dict[str, str] = {
    "approved_budget": "double",
    "quantity": "double",
    "item_budget": "double",
    "contract_amount": "double",
    "contract_duration": "double",
    "bid_published_date": "date",
    "closing_date": "date",
    "prebid_date": "date",
    "award_date": "date",
    "award_published_date": "date",
    "notice_to_proceed_date": "date",
    "contract_effectivity_date": "date",
    "contract_end_date": "date",
    "_source_row_number": "integer",
    "_cleaning_issue_count": "integer",
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
    fields_by_target: dict[str, list[str]] = {}
    for field_name, spec in field["fields"].items():
        for target in spec["targets"]:
            fields_by_target.setdefault(target, []).append(field_name)
    known = set(fields_by_target)
    unknown = sorted(
        {t for targets, _ in PATH_FILLS.values() for t in targets if t not in known}
    )
    if unknown:
        raise SystemExit(f"PATH_FILLS references unknown targets: {unknown}")
    return field, fields_by_target, codelists


def render_mapping(targets: list[str], fields_by_target: dict[str, list[str]]) -> str:
    """Mapping cells must reference a Data Elements entry (template rule).

    The stage sheets' Mapping column is validated against the Data Elements
    display values, so a compliant fill is a single reference like
    'philgeps_cleaned (bid_reference_no)' -- the same style as the
    template's own 'Tenders (Tender ID)' fills. When several source fields
    feed one OCDS path, the primary field is referenced here and the others
    are named in the Notes column.
    """
    fields: list[str] = []
    for target in targets:
        for field_name in fields_by_target.get(target, []):
            if field_name not in fields:
                fields.append(field_name)
    if not fields:
        return ""
    return f"{ELEMENT_SECTION} ({fields[0]})"


def render_note(targets: list[str], path: str, fields_by_target) -> str:
    """Plain sentence naming the source fields, plus the curated note."""
    fields: list[str] = []
    for target in targets:
        for field_name in fields_by_target.get(target, []):
            if field_name not in fields:
                fields.append(field_name)
    sentences = []
    if fields:
        if len(fields) == 1:
            sentences.append(f"From {fields[0]}.")
        else:
            sentences.append(f"From {fields[0]}. Also from {', '.join(fields[1:])}.")
    note = FIELD_NOTES.get(path)
    if note:
        sentences.append(note)
    return " ".join(sentences)


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


def collect_examples(field_names) -> dict[str, str]:
    """One representative non-null example per field, from the typed layer.

    Uses the most frequent value per column (mode) with trivial values
    (whitespace-only) filtered out: a typical, real observation rather
    than a degenerate edge value. Personal-data fields get no example.
    Dates render as ISO (midnight timestamps as date-only); long values
    are truncated to 120 chars. Returns {} when the cleaned parquet is
    absent, so the template can still be generated without data present.
    """
    wanted = [f for f in field_names if f not in PRIVACY_HOLD_FIELDS]
    if not wanted or not EXAMPLES_SOURCE.is_file():
        return {}
    import duckdb

    relation = str(EXAMPLES_SOURCE).replace("\\", "/")
    examples: dict[str, str] = {}
    for name in wanted:
        row = duckdb.sql(
            f'SELECT mode("{name}") FILTER ('
            f'WHERE "{name}" IS NOT NULL '
            f"AND trim(try_cast(\"{name}\" AS VARCHAR)) <> '') "
            f"FROM read_parquet('{relation}')"
        ).fetchone()
        value = row[0] if row else None
        if value is None:
            continue
        if hasattr(value, "isoformat"):
            iso = value.isoformat()
            examples[name] = iso[:10] if iso.endswith("T00:00:00") else iso
        elif isinstance(value, Decimal):
            normalized = format(value.normalize(), "f")
            examples[name] = normalized[:120]
        else:
            text = str(value).strip()
            if text:
                examples[name] = text[:120]
    return examples


def first_blank_element_row(ws) -> int:
    """First row (from 4) where the element columns B/D are empty.

    The template pre-fills hundreds of blank rows below the mPhilGEPS
    entries with display formulas (A) and stage counters (J) for curators
    to type into; new elements belong in those slots, NOT at max_row+1
    (max_row counts ghost formatting rows far below). Falls back to
    max_row+1 only when every slot is used.
    """
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, max_col=4):
        if row[1].value is None and row[3].value is None:
            return row[0].row
    return ws.max_row + 1


def fill_data_elements_sheet(wb, field_mapping) -> tuple[int, int]:
    """List every normalized field in the template's '2. Data Elements' sheet.

    Follows the template's conventions (display formula in A, 'PhilGEPS 1.5'
    data source in B, real data types, plain notes) and fills the first
    blank element slots after the mPhilGEPS rows, keeping the block inside
    the stage-sheet dropdown range ('2. Data Elements'!$A$5:$A$491). The
    range is extended only as a safety net if the block would exceed it.
    Returns (first_row, count).
    """
    ws = wb["2. Data Elements"]
    r = first_blank_element_row(ws)
    first_row = r
    listed = 0
    examples = collect_examples(field_mapping["fields"].keys())
    for field_name, spec in field_mapping["fields"].items():
        ws.cell(row=r, column=1, value=f'=CONCATENATE(C{r}," (",D{r},")")')
        ws.cell(row=r, column=2, value=SOURCE_LABEL)
        ws.cell(row=r, column=3, value=ELEMENT_SECTION)
        ws.cell(row=r, column=4, value=field_name)
        published = spec["status"] == "accepted" and not field_name.startswith("_")
        ws.cell(row=r, column=5, value="Yes" if published else "No")
        ws.cell(row=r, column=6, value=examples.get(field_name, ""))
        ws.cell(row=r, column=7, value=FIELD_DESCRIPTIONS.get(field_name, ""))
        ws.cell(row=r, column=8, value=FIELD_TYPES.get(field_name, "string"))
        if field_name.startswith("_"):
            note = "Internal provenance / data-quality field; not published."
        elif spec["status"] == "accepted":
            note = f"Feeds {'; '.join(spec['targets'])}."
        elif spec["status"] == "proposed":
            note = "Mapping proposed; not published pending confirmation."
        else:
            note = "Unresolved mapping; not published."
        ws.cell(row=r, column=9, value=note)
        r += 1
        listed += 1

    # Keep the stage-sheet dropdowns (validated against column A) covering
    # our element rows: extend any '2. Data Elements'!$A$... range whose end
    # row falls short of our block.
    last_row = r - 1
    for sheet_name in wb.sheetnames:
        if not sheet_name.startswith("(OCDS)"):
            continue
        for dv in wb[sheet_name].data_validations.dataValidation:
            formula = str(dv.formula1 or "")
            marker = "'2. Data Elements'!$A$"
            if marker not in formula:
                continue
            end = formula.rsplit("$A$", 1)[-1]  # range end row, e.g. '...$A$491' -> '491'
            if end.isdigit() and int(end) < last_row:
                dv.formula1 = formula.replace(f"$A${end}", f"$A${last_row}")
    return first_row, listed


def fill_field_template(src: Path, dst: Path, field_mapping, fields_by_target) -> tuple[int, int]:
    wb = openpyxl.load_workbook(src)
    filled = 0
    for name in wb.sheetnames:
        if not name.startswith("(OCDS)"):
            continue
        ws = wb[name]
        for row in ws.iter_rows(min_row=4):
            path_cell = row[2] if len(row) > 2 else None  # column C
            map_cell = row[5] if len(row) > 5 else None  # column F
            if path_cell is None or map_cell is None:
                continue
            path = str(path_cell.value).strip() if path_cell.value else ""
            if path not in PATH_FILLS:
                continue
            targets, explicit = PATH_FILLS[path]
            preserve_original(map_cell, "mPhilGEPS")
            map_cell.value = explicit if explicit else render_mapping(targets, fields_by_target)
            note_cell = row[7] if len(row) > 7 else None  # column H
            if note_cell is not None:
                prior = str(note_cell.value).strip() if note_cell.value else ""
                sentence = render_note(targets, path, fields_by_target)
                if sentence:
                    note_cell.value = f"{sentence} | {prior}" if prior else sentence
            filled += 1
    listed = fill_data_elements_sheet(wb, field_mapping)
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return filled, listed[1]


def source_note(domain: str, spec: dict) -> str:
    """Plain-language decision sentence for one source value row."""
    value_spec = spec
    destination = CODELIST_NAMES.get(domain, domain)
    dest = value_spec.get("destination_value")
    status = value_spec.get("status", "unresolved")
    parts = []
    if domain == "calendar_type":
        parts.append(f"Kept in tenders.contract_duration_unit (local column); no OCDS codelist.")
    elif dest:
        parts.append(f"Maps to {dest}.")
    parts.append(STATUS_SENTENCES.get(status, ""))
    rationale = value_spec.get("rationale")
    if rationale:
        parts.append(rationale)
    return " ".join(p for p in parts if p).strip()


def fill_codelist_template(src: Path, dst: Path, codelists) -> tuple[int, int]:
    wb = openpyxl.load_workbook(src)

    # -- (Source) Codelists: one row per source value -----------------------
    ws = wb["(Source) Codelists"]
    existing: dict[tuple[str, str], int] = {}
    for row in ws.iter_rows(min_row=4):
        b = str(row[1].value).strip() if row[1].value else ""
        c = str(row[2].value).strip() if row[2].value else ""
        if b and c:
            existing.setdefault((b, c), row[2].row)
    listed = 0
    # The template pre-fills blank rows below the existing entries with
    # =CONCATENATE key formulas (D); new values belong in those slots, not
    # at max_row+1 (which counts ghost rows past the dropdown range).
    r = next(
        (
            row[0].row
            for row in ws.iter_rows(min_row=4, max_row=ws.max_row, max_col=3)
            if row[1].value is None and row[2].value is None
        ),
        ws.max_row + 1,
    )
    for domain, spec in codelists["mappings"].items():
        name = CODELIST_NAMES.get(domain, domain)
        for source_value, v in spec["values"].items():
            note = source_note(domain, v)
            key = (name, source_value.strip())
            if key in existing:
                # The official template already inventories this value:
                # record our decision on the existing row, don't duplicate.
                ws.cell(row=existing[key], column=7, value=note)
            else:
                ws.cell(row=r, column=1, value=SOURCE_LABEL)
                ws.cell(row=r, column=2, value=name)
                ws.cell(row=r, column=3, value=source_value)
                ws.cell(row=r, column=4, value=f"=CONCATENATE(B{r},C{r})")
                ws.cell(row=r, column=7, value=note)
                r += 1
            listed += 1

    # Keep the codelist-sheet dropdowns (validated against columns B/C of
    # this sheet) covering our appended rows: extend any '(Source)
    # Codelists'!$B$... / $C$... range whose end row falls short.
    last_row = r - 1
    for sheet_name in wb.sheetnames:
        if not sheet_name.startswith("(OCDS)"):
            continue
        for dv in wb[sheet_name].data_validations.dataValidation:
            formula = str(dv.formula1 or "")
            marker = "'(Source) Codelists'!$"
            if marker not in formula:
                continue
            tail = formula.rsplit("$", 1)[-1]
            if tail.isdigit() and int(tail) < last_row:
                dv.formula1 = formula.replace(f"${tail}", f"${last_row}")

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
        preserve_original(source_codelist_cell, "mPhilGEPS")
        source_codelist_cell.value = CODELIST_NAMES[domain]
        source_code_cell.value = matches[0][0]
        if len(matches) > 1:
            others = ", ".join(s for s, _ in matches[1:])
            statuses = "/".join(sorted({v["status"] for _, v in matches[1:]}))
            notes_cell = source_code_cell.parent.cell(row=source_code_cell.row, column=8)
            prior = str(notes_cell.value).strip() if notes_cell.value else ""
            addition = f"Also: {others} ({statuses})."
            notes_cell.value = f"{addition} | {prior}" if prior else addition
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

    field_mapping, fields_by_target, codelists = load_configs()

    field_dst = args.output_dir / "UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx"
    codelist_dst = args.output_dir / "UNIFIED_exports_OCDS_Codelist_Mapping_FILLED.xlsx"

    n_fields, n_elements = fill_field_template(
        args.references_dir / FIELD_TEMPLATE, field_dst, field_mapping, fields_by_target
    )
    n_codes, n_listed = fill_codelist_template(
        args.references_dir / CODELIST_TEMPLATE, codelist_dst, codelists
    )

    print(
        f"field template : {n_fields} OCDS paths filled, "
        f"{n_elements} normalized fields listed in Data Elements -> {field_dst}"
    )
    print(
        f"codelist template: {n_codes} code rows filled, "
        f"{n_listed} source values listed -> {codelist_dst}"
    )


if __name__ == "__main__":
    main()
