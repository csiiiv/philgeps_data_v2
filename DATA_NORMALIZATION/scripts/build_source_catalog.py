#!/usr/bin/env python3
"""Build a deterministic catalog of PhilGEPS source files and their URLs.

The scanner intentionally uses only the Python standard library. XLSX files are
inspected as ZIP/XML so catalog generation does not load millions of worksheet
rows into memory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import posixpath
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
S = f"{{{SPREADSHEET_NS}}}"
R = f"{{{OFFICE_REL_NS}}}"
PR = f"{{{PACKAGE_REL_NS}}}"
CELL_REF_RE = re.compile(r"([A-Z]+)([0-9]+)")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_header(values: list[Any]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value).strip() for value in values)


def load_schemas(path: Path) -> dict[str, tuple[str, ...]]:
    raw = json.loads(path.read_text(encoding="utf-8"))["schemas"]
    resolved: dict[str, tuple[str, ...]] = {}

    def resolve(name: str) -> tuple[str, ...]:
        if name in resolved:
            return resolved[name]
        spec = raw[name]
        if "columns" in spec:
            columns = list(spec["columns"])
        else:
            columns = list(resolve(spec["extends"]))
            replacements = spec.get("replace", {})
            columns = [replacements.get(column, column) for column in columns]
        resolved[name] = normalize_header(columns)
        return resolved[name]

    for schema_name in raw:
        resolve(schema_name)
    return resolved


def match_schema(header: list[Any], schemas: dict[str, tuple[str, ...]]) -> str | None:
    normalized = normalize_header(header)
    return next((name for name, columns in schemas.items() if columns == normalized), None)


def read_shared_strings(archive: zipfile.ZipFile, wanted: set[int]) -> dict[int, str]:
    if not wanted or "xl/sharedStrings.xml" not in archive.namelist():
        return {}
    strings: dict[int, str] = {}
    index = -1
    with archive.open("xl/sharedStrings.xml") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag == S + "si":
                index += 1
                if index in wanted:
                    strings[index] = "".join(
                        text.text or "" for text in element.iter(S + "t")
                    )
                element.clear()
                if index >= max(wanted):
                    break
    return strings


def workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(PR + "Relationship")
    }
    result: list[tuple[str, str]] = []
    for sheet in workbook.findall(f"{S}sheets/{S}sheet"):
        target = targets[sheet.attrib[R + "id"]].lstrip("/")
        if not target.startswith("xl/"):
            target = posixpath.normpath(posixpath.join("xl", target))
        result.append((sheet.attrib["name"], target))
    return result


def scan_sheet_prefix(
    archive: zipfile.ZipFile, member: str, max_row: int = 10
) -> tuple[str | None, list[tuple[int, list[Any]]], set[int]]:
    dimension: str | None = None
    rows: list[tuple[int, list[Any]]] = []
    wanted_strings: set[int] = set()
    with archive.open(member) as handle:
        for event, element in ET.iterparse(handle, events=("start", "end")):
            if event == "start" and element.tag == S + "dimension":
                dimension = element.attrib.get("ref")
            elif event == "end" and element.tag == S + "row":
                row_number = int(element.attrib.get("r", "0"))
                values: list[Any] = []
                for cell in element.findall(S + "c"):
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find(S + "v")
                    inline_node = cell.find(S + "is")
                    value: Any = None
                    if inline_node is not None:
                        value = "".join(
                            text.text or "" for text in inline_node.iter(S + "t")
                        )
                    elif value_node is not None:
                        value = value_node.text
                        if cell_type == "s" and value is not None:
                            string_index = int(value)
                            wanted_strings.add(string_index)
                            value = ("shared", string_index)
                    values.append(value)
                rows.append((row_number, values))
                element.clear()
                if row_number >= max_row:
                    break
    return dimension, rows, wanted_strings


def dimension_last_row(dimension: str | None) -> int | None:
    if not dimension:
        return None
    final_ref = dimension.split(":")[-1]
    match = CELL_REF_RE.fullmatch(final_ref)
    return int(match.group(2)) if match else None


def inspect_xlsx(path: Path, schemas: dict[str, tuple[str, ...]]) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        prefixes: list[tuple[str, str, str | None, list[tuple[int, list[Any]]]]] = []
        wanted: set[int] = set()
        for sheet_name, member in workbook_sheets(archive):
            dimension, rows, sheet_wanted = scan_sheet_prefix(archive, member)
            prefixes.append((sheet_name, member, dimension, rows))
            wanted.update(sheet_wanted)
        shared_strings = read_shared_strings(archive, wanted)

        sheets: list[dict[str, Any]] = []
        for sheet_name, _, dimension, encoded_rows in prefixes:
            rows: list[tuple[int, list[Any]]] = []
            for row_number, values in encoded_rows:
                resolved = [
                    shared_strings.get(value[1], "")
                    if isinstance(value, tuple) and value[0] == "shared"
                    else value
                    for value in values
                ]
                rows.append((row_number, resolved))

            detected: tuple[int, list[Any], str] | None = None
            for row_number, values in rows:
                schema_name = match_schema(values, schemas)
                if schema_name:
                    detected = (row_number, values, schema_name)
                    break

            sheets.append(
                {
                    "sheet_name": sheet_name,
                    "schema_id": detected[2] if detected else None,
                    "header_present": detected is not None,
                    "header_row_number": detected[0] if detected else None,
                    "first_data_row_number": detected[0] + 1 if detected else None,
                    "column_count": len(detected[1]) if detected else None,
                    "columns": list(normalize_header(detected[1])) if detected else [],
                    "last_physical_row_number": dimension_last_row(dimension),
                    "diagnostics": [] if detected else ["No registered header found in rows 1-10"],
                }
            )
        return sheets


def inspect_csv(
    path: Path, schemas: dict[str, tuple[str, ...]], count_rows: bool
) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        first_row = next(reader, [])
        schema_name = match_schema(first_row, schemas)
        header_present = schema_name is not None
        diagnostics: list[str] = []
        columns: list[str]
        if header_present:
            columns = list(normalize_header(first_row))
        elif len(first_row) == len(schemas["location_46"]):
            schema_name = "location_46"
            columns = list(schemas[schema_name])
            diagnostics.append("Header absent; location_46 inferred from 46-column first record")
        else:
            columns = []
            diagnostics.append(
                f"No registered header and no safe inference for {len(first_row)} columns"
            )

        last_row: int | None = None
        if count_rows:
            last_row = 1 + sum(1 for _ in reader)

    return [
        {
            "sheet_name": None,
            "schema_id": schema_name,
            "header_present": header_present,
            "header_row_number": 1 if header_present else None,
            "first_data_row_number": 2 if header_present else 1,
            "column_count": len(columns) if columns else len(first_row),
            "columns": columns,
            "last_physical_row_number": last_row,
            "diagnostics": diagnostics,
        }
    ]


def parse_args() -> argparse.Namespace:
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=project_dir.parent / "RAW_DATA_DOWNLOADER" / "dataset",
        help="Directory containing manifest.json and files/",
    )
    parser.add_argument(
        "--schema-registry",
        type=Path,
        default=project_dir / "config" / "schema_registry.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_dir / "artifacts" / "source_catalog.json",
    )
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Recompute every file SHA-256 (slow for the complete dataset)",
    )
    parser.add_argument(
        "--count-csv-rows",
        action="store_true",
        help="Parse complete CSV files to populate last_physical_row_number",
    )
    return parser.parse_args()


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    dataset = args.dataset.resolve()
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest["documents"]
    manifest_source_files = {
        item["source_file_id"]: item for item in manifest.get("source_files", [])
    }
    schemas = load_schemas(args.schema_registry.resolve())

    by_digest: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for position, document in enumerate(documents, start=1):
        digest = document.get("sha256")
        if not digest:
            continue
        by_digest[digest].append((position, document))

    source_files: list[dict[str, Any]] = []
    schema_counts: Counter[str] = Counter()
    diagnostic_count = 0
    for digest, entries in sorted(by_digest.items(), key=lambda item: item[1][0][1]["local_file"]):
        local_files = sorted({entry["local_file"] for _, entry in entries})
        path = dataset / local_files[0]
        diagnostics: list[str] = []
        if not path.is_file():
            diagnostics.append("Local file is missing")
            sheets: list[dict[str, Any]] = []
        else:
            actual_digest = sha256_file(path) if args.verify_hashes else None
            if actual_digest is not None and actual_digest != digest:
                diagnostics.append("Manifest SHA-256 does not match local file")
            suffix = path.suffix.lower()
            if suffix == ".xlsx":
                sheets = inspect_xlsx(path, schemas)
            elif suffix == ".csv":
                sheets = inspect_csv(path, schemas, args.count_csv_rows)
            else:
                sheets = []
                diagnostics.append(f"Unsupported file type: {suffix}")

        for sheet in sheets:
            sheet["source_sheet_id"] = "pgs_" + sha256_text(
                digest + "\0" + (sheet["sheet_name"] or "")
            )
            if sheet["schema_id"]:
                schema_counts[sheet["schema_id"]] += 1
            diagnostic_count += len(sheet["diagnostics"])
        diagnostic_count += len(diagnostics)

        urls = []
        for position, entry in entries:
            url = entry["source_url"]
            urls.append(
                {
                    "document_id": entry.get("document_id") or "pgd_" + sha256_text(url),
                    "url": url,
                    "source_type": entry.get("source_type"),
                    "google_file_id": entry.get("google_file_id"),
                    "gid": entry.get("gid"),
                    "manifest_position": position,
                    "manifest_status": entry.get("status"),
                    "downloaded_at": entry.get("downloaded_at"),
                }
            )

        source_file_id = entries[0][1].get("source_file_id") or "pgf_" + digest
        source_files.append(
            {
                "source_file_id": source_file_id,
                "normalized_file_name": manifest_source_files.get(source_file_id, {}).get(
                    "normalized_file_name"
                ),
                "sha256": digest,
                "title": entries[0][1].get("title"),
                "local_files": local_files,
                "format": path.suffix.lower().lstrip(".") if path.suffix else None,
                "size_bytes": path.stat().st_size if path.is_file() else None,
                "urls": urls,
                "sheets": sheets,
                "diagnostics": diagnostics,
            }
        )

    disk_files = {"files/" + path.name for path in (dataset / "files").iterdir() if path.is_file()}
    manifest_files = {entry["local_file"] for entry in documents if entry.get("local_file")}
    return {
        "catalog_version": 1,
        "manifest": {
            "path": "manifest.json",
            "version": manifest.get("version"),
            "generated_at": manifest.get("generated_at"),
            "document_count": len(documents),
        },
        "summary": {
            "source_file_count": len(source_files),
            "source_url_count": sum(len(item["urls"]) for item in source_files),
            "formats": dict(sorted(Counter(item["format"] for item in source_files).items())),
            "schemas": dict(sorted(schema_counts.items())),
            "diagnostic_count": diagnostic_count,
            "unmanifested_disk_files": sorted(disk_files - manifest_files),
            "missing_manifest_files": sorted(manifest_files - disk_files),
        },
        "source_files": source_files,
    }


def main() -> int:
    args = parse_args()
    try:
        catalog = build_catalog(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(catalog["summary"], indent=2))
    print(f"Wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
