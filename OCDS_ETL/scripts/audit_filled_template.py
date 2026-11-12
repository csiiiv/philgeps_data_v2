#!/usr/bin/env python3
"""Audit: every normalized field must appear in the filled field template.

Checks the regenerated workbook in artifacts/filled_templates/:
1. '2. Data Elements' sheet lists all fields from config/field_mapping.json
   with descriptions and data types
2. Every field name appears in at least one stage-sheet cell (Mapping or
   Notes; fields are named in the plain-language notes)
3. Every filled cell satisfies the workbook's own list validations
   (dropdowns), so Excel shows no 'Input must fall within specified range'
   warnings on our fills
4. Spot-checks identity anchors and shows sample cells

Run: python audit_filled_template.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import range_boundaries

sys.stdout.reconfigure(encoding="utf-8")

PROJECT = Path(__file__).resolve().parents[1]
XLSX = PROJECT / "artifacts" / "filled_templates" / "UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx"

fm = json.loads((PROJECT / "config" / "field_mapping.json").read_text(encoding="utf-8"))
OUR_SOURCE_LABEL = "PhilGEPS 1.5"  # our fills' data-source marker
fields = set(fm["fields"])

# Fields that intentionally have no OCDS stage-sheet path: they feed local
# provenance/quality tables (record_sources, data_quality_issues) or are
# analytical-only (created_by). They are still listed in Data Elements.
LOCAL_ONLY_PREFIXES = ("_",)
LOCAL_ONLY_FIELDS = {"created_by"}


def is_local_only(field_name: str) -> bool:
    return field_name.startswith(LOCAL_ONLY_PREFIXES) or field_name in LOCAL_ONLY_FIELDS

wb = openpyxl.load_workbook(XLSX)

stage_text: list[str] = []
for name in wb.sheetnames:
    if name.startswith("(OCDS)"):
        for row in wb[name].iter_rows(min_row=4):
            for idx in (5, 7):  # Mapping (F) and Notes (H)
                if len(row) > idx and row[idx].value:
                    stage_text.append(str(row[idx].value))
blob = " ".join(stage_text)

de_rows = 0
de_fields: set[str] = set()
no_desc: list[str] = []
no_type: list[str] = []
ws = wb["2. Data Elements"]
for row in ws.iter_rows(values_only=True):
    if row and row[1] and str(row[1]).strip() == "PhilGEPS 1.5":
        de_rows += 1
        f = str(row[3]) if row[3] else ""
        de_fields.add(f)
        desc = str(row[6]) if len(row) > 6 and row[6] else ""
        dtype = str(row[7]) if len(row) > 7 and row[7] else ""
        if f in fields and not desc.strip():
            no_desc.append(f)
        if f in fields and not dtype.strip():
            no_type.append(f)

print(f"normalized fields            : {len(fields)}")
print(f"Data Elements rows / unique  : {de_rows} / {len(de_fields & fields)}")
missing_de = sorted(fields - de_fields)
print(f"missing from Data Elements   : {missing_de or 'NONE'}")
print(f"rows without description     : {no_desc or 'NONE'}")
print(f"rows without data type       : {no_type or 'NONE'}")
missing_stage = sorted(
    f for f in fields if f not in blob and not is_local_only(f)
)
local_only = sorted(f for f in fields if is_local_only(f))
print(f"missing from stage sheets    : {missing_stage or 'NONE'}")
print(f"local-only (no OCDS path)    : {len(local_only)} fields, listed in Data Elements only")

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
            print(f"  {path}:")
            print(f"    mapping: {str(row[5].value)[:120]}")
            if len(row) > 7 and row[7].value:
                print(f"    note   : {str(row[7].value)[:120]}")
            break


# ---------------------------------------------------------------------------
# List-validation compliance: every cell WE filled must satisfy the
# workbook's own dropdown rules, so Excel raises no 'Input must fall within
# specified range' warnings on our fills. Pre-existing official-template
# fills are out of scope (identified via our fills' marker strings).

def display_value(ws, cell):
    """Displayed value for the template's CONCATENATE display formulas."""
    v = cell.value
    if v is None:
        return None
    if isinstance(v, str) and v.startswith("=CONCATENATE("):
        body = v.strip()[len("=CONCATENATE("):-1]
        parts, cur, in_str = [], "", False
        for ch in body:
            if ch == '"':
                in_str = not in_str
                cur += ch
            elif ch == "," and not in_str:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        out = []
        for p in parts:
            p = p.strip()
            if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
                out.append(p[1:-1])
            else:
                ref = p.strip('"')
                if re.fullmatch(r"[A-Z]+[0-9]+", ref):
                    ref_cell = ws[ref]
                    if ref_cell.value is not None:
                        out.append(str(ref_cell.value))
        return "".join(out)
    return str(v)


def element_markers(cell_value: str) -> bool:
    """True when a Mapping cell was written by our filler."""
    return cell_value.startswith("philgeps_cleaned (")


print()
print("validation compliance (our fills only):")
violations = 0
for ws_audit in wb.worksheets:
    for dv in ws_audit.data_validations.dataValidation:
        if dv.type != "list":
            continue
        f1 = str(dv.formula1 or "")
        if f1.startswith('"'):
            allowed = {v.strip() for v in f1.strip('"').split(",")}
            ours = lambda v: False  # inline lists cover type columns; skip origin test
        elif "!" in f1:
            sheet_ref, cell_range = f1.split("!", 1)
            src = wb[sheet_ref.strip("'")]
            allowed = set()
            for row in src[cell_range.replace("$", "")]:
                for c in row:
                    d = display_value(src, c)
                    if d not in (None, ""):
                        allowed.add(d.strip())
            ours = element_markers
        else:
            continue
        for rng in str(dv.sqref).split():
            min_c, min_r, max_c, max_r = range_boundaries(rng)
            for row in ws_audit.iter_rows(min_row=min_r, max_row=max_r,
                                          min_col=min_c, max_col=max_c):
                for cell in row:
                    v = display_value(ws_audit, cell)
                    if not v or v in allowed:
                        continue
                    # Only OUR fills are in scope.
                    src_col = str(dv.formula1 or "")
                    if "!" in f1 and not ours(v):
                        continue
                    print(f"  VIOLATION [{ws_audit.title}] {cell.coordinate}: {v[:60]!r}")
                    violations += 1
print(f"  our fills violating dropdowns : {violations or 'NONE'}")
if violations:
    sys.exit(1)
