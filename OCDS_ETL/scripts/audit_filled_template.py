#!/usr/bin/env python3
"""Audit: every normalized field must appear in the filled field template.

Checks the regenerated workbook in artifacts/filled_templates/:
1. '2. Data Elements' sheet lists all fields from config/field_mapping.json
   with descriptions
2. Every field name appears in at least one stage-sheet Mapping cell
3. Spot-checks identity anchors and shows sample cells

Run: python audit_filled_template.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

PROJECT = Path(__file__).resolve().parents[1]
XLSX = PROJECT / "artifacts" / "filled_templates" / "UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx"

fm = json.loads((PROJECT / "config" / "field_mapping.json").read_text(encoding="utf-8"))
fields = set(fm["fields"])

wb = openpyxl.load_workbook(XLSX)

stage_text: list[str] = []
for name in wb.sheetnames:
    if name.startswith("(OCDS)"):
        for row in wb[name].iter_rows(min_row=4):
            if len(row) > 5 and row[5].value:
                stage_text.append(str(row[5].value))
blob = " ".join(stage_text)

de_rows = 0
de_fields: set[str] = set()
no_desc: list[str] = []
ws = wb["2. Data Elements"]
for row in ws.iter_rows(values_only=True):
    if row and row[0] and "PhilGEPS 1.5 exports" in str(row[0]):
        de_rows += 1
        f = str(row[3]) if row[3] else ""
        de_fields.add(f)
        desc = str(row[6]) if len(row) > 6 and row[6] else ""
        if f in fields and not desc.strip():
            no_desc.append(f)

print(f"normalized fields            : {len(fields)}")
print(f"Data Elements rows / unique  : {de_rows} / {len(de_fields & fields)}")
missing_de = sorted(fields - de_fields)
print(f"missing from Data Elements   : {missing_de or 'NONE'}")
print(f"rows without description     : {no_desc or 'NONE'}")
missing_stage = sorted(f for f in fields if f not in blob)
print(f"missing from stage sheets    : {missing_stage or 'NONE'}")

print()
print("sample cells:")
for sheet, path in [
    ("(OCDS) 3. Tender", "tender/id"),
    ("(OCDS) 5. Contract", "contracts/id"),
    ("(OCDS) 4. Award", "awards/description"),
    ("(OCDS) 3. Tender", "tender/items/unit/value/amount"),
]:
    ws2 = wb[sheet]
    for row in ws2.iter_rows(min_row=4):
        if len(row) > 5 and row[2].value and str(row[2].value).strip() == path:
            print(f"  {path}: {str(row[5].value)[:130]}")
            break
