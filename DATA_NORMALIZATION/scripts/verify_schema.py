#!/usr/bin/env python3
"""Compare the generated source catalog with the registered PhilGEPS schemas."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


NORMALIZED_NAME_RE = re.compile(
    r"^(\d{4})-(0[1-9]|1[0-2])--(\d{4})-(0[1-9]|1[0-2])\.(csv|xlsx)$"
)


def normalized(values):
    return tuple(str(value).strip() for value in values)


def load_registry(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data["schemas"]
    schemas = {}

    def resolve(name):
        if name in schemas:
            return schemas[name]
        spec = raw[name]
        if "columns" in spec:
            columns = list(spec["columns"])
        else:
            columns = list(resolve(spec["extends"]))
            columns = [spec.get("replace", {}).get(column, column) for column in columns]
        schemas[name] = normalized(columns)
        return schemas[name]

    for name in raw:
        resolve(name)
    return data, schemas


def verify(manifest, catalog, registry_data, schemas):
    errors = []
    warnings = []
    known_headerless = set(registry_data.get("known_headerless_files", []))

    documents = manifest.get("documents", [])
    source_files = manifest.get("source_files", [])
    manifest_ids = [item.get("source_file_id") for item in source_files]
    document_ids = [item.get("document_id") for item in documents]
    catalog_ids = [item.get("source_file_id") for item in catalog.get("source_files", [])]

    if manifest.get("version") != 2:
        errors.append("manifest version is not 2")
    if len(manifest_ids) != len(set(manifest_ids)):
        errors.append("source_file_id is not unique in manifest source_files")
    if len(document_ids) != len(set(document_ids)):
        errors.append("document_id is not unique in manifest documents")
    if set(manifest_ids) != set(catalog_ids):
        errors.append("catalog and manifest source_file_id sets differ")

    valid_file_ids = set(manifest_ids)
    for document in documents:
        if document.get("source_file_id") and document["source_file_id"] not in valid_file_ids:
            errors.append(f"document FK is missing: {document.get('document_id')}")

    names = [item.get("normalized_file_name") for item in source_files]
    if any(not name for name in names):
        errors.append("one or more source files lack normalized_file_name")
    if len(names) != len(set(names)):
        errors.append("normalized_file_name is not unique")
    for name in filter(None, names):
        match = NORMALIZED_NAME_RE.fullmatch(name)
        if not match:
            errors.append(f"invalid normalized_file_name: {name}")
        elif (match.group(1), match.group(2)) > (match.group(3), match.group(4)):
            errors.append(f"normalized range is reversed: {name}")

    schema_counts = Counter()
    header_rows = Counter()
    observed_headerless = set()
    sheet_count = 0
    for source_file in catalog.get("source_files", []):
        local_files = source_file.get("local_files", [])
        local_file = local_files[0] if local_files else source_file["source_file_id"]
        if len(source_file.get("sheets", [])) != 1:
            warnings.append(
                f"{local_file}: expected one worksheet/CSV stream, found "
                f"{len(source_file.get('sheets', []))}"
            )
        for sheet in source_file.get("sheets", []):
            sheet_count += 1
            schema_id = sheet.get("schema_id")
            if schema_id not in schemas:
                errors.append(f"{local_file}: unregistered schema {schema_id!r}")
                continue
            schema_counts[schema_id] += 1
            if sheet.get("header_present"):
                header_rows[(schema_id, sheet.get("header_row_number"))] += 1
                if normalized(sheet.get("columns", [])) != schemas[schema_id]:
                    errors.append(f"{local_file}: header differs from registered {schema_id}")
            else:
                observed_headerless.add(local_file)
                if local_file not in known_headerless:
                    errors.append(f"{local_file}: unexpectedly headerless")
                if normalized(sheet.get("columns", [])) != schemas[schema_id]:
                    errors.append(f"{local_file}: inferred columns differ from {schema_id}")

    for local_file in sorted(known_headerless - observed_headerless):
        errors.append(f"{local_file}: registered headerless but a header was detected")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "manifest_documents": len(documents),
            "manifest_source_files": len(source_files),
            "catalog_sheets": sheet_count,
            "schemas": dict(sorted(schema_counts.items())),
            "header_positions": {
                f"{schema_id}@row_{row}": count
                for (schema_id, row), count in sorted(header_rows.items())
            },
            "headerless_files": sorted(observed_headerless),
        },
    }


def render_markdown(result):
    counts = result["counts"]
    lines = [
        "# PhilGEPS source-schema verification",
        "",
        f"**Result: {result['status']}**",
        "",
        "This report compares every physical source file header with the explicit",
        "schema registry and checks manifest v2 identifiers and normalized names.",
        "It is the pre-ingestion schema gate; exhaustive data-row checks occur while",
        "streaming the sources into raw Parquet.",
        "",
        "## Coverage",
        "",
        f"- Manifest document entries: {counts['manifest_documents']}",
        f"- Unique source files: {counts['manifest_source_files']}",
        f"- Worksheet/CSV streams inspected: {counts['catalog_sheets']}",
        "- Missing or unregistered physical schemas: "
        + ("0" if not result["errors"] else "see errors below"),
        "",
        "## Observed physical layouts",
        "",
    ]
    for schema_id, count in counts["schemas"].items():
        lines.append(f"- `{schema_id}`: {count} files")
    lines.extend(["", "Header positions:", ""])
    for label, count in counts["header_positions"].items():
        lines.append(f"- `{label}`: {count} files")
    lines.extend(["", "Known headerless exports:", ""])
    for local_file in counts["headerless_files"]:
        lines.append(f"- `{local_file}`")

    lines.extend(
        [
            "",
            "## Reconciliation with the historical reference",
            "",
            "The historical `references/philgeps_schema.md` is semantically useful,",
            "but its year-to-layout routing does not match this downloaded snapshot:",
            "",
            "- The 40-column `UOM` layout is present in the 2000–2010 annual files.",
            "- A 40-column `Unit of Measurement` variant occurs in the 2017 Q4 file.",
            "- Thirty-nine XLSX files use a 43-column row-1 header that includes",
            "  `Client Agency`, `Created By`, and `Awardee Contact Person`, but no",
            "  `List of Bidder's`.",
            "- Sixteen CSV files use the 46-column location-enriched layout; four of",
            "  those files omit the header row.",
            "",
            "Ingestion must therefore route by detected schema signature, never by",
            "year or filename alone.",
        ]
    )

    if result["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {message}" for message in result["errors"])
    if result["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {message}" for message in result["warnings"])
    return "\n".join(lines) + "\n"


def parse_args():
    project = Path(__file__).resolve().parents[1]
    root = project.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "RAW_DATA_DOWNLOADER" / "dataset" / "manifest.json",
    )
    parser.add_argument(
        "--catalog", type=Path, default=project / "artifacts" / "source_catalog.json"
    )
    parser.add_argument(
        "--registry", type=Path, default=project / "config" / "schema_registry.json"
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=project / "artifacts" / "schema_verification.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "docs" / "schema_verification.md",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    registry_data, schemas = load_registry(args.registry)
    result = verify(manifest, catalog, registry_data, schemas)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
