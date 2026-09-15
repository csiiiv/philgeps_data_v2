#!/usr/bin/env python3
"""Return complete PhilGEPS observations using their source breadcrumb."""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import json
import sys
from pathlib import Path

import duckdb


PROVENANCE_COLUMNS = {
    "_source_file_id",
    "_source_sheet",
    "_source_row_number",
    "_source_schema_id",
}


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Look up one or more physical source rows from a compact "
            "source_file_id:row breadcrumb."
        ),
        epilog=(
            "Example: show_source_entry.py "
            "pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24343"
        ),
    )
    parser.add_argument(
        "breadcrumb",
        help=(
            "Compact pgf_...:row breadcrumb, or a pgf_... source file ID when "
            "row numbers are supplied separately"
        ),
    )
    parser.add_argument(
        "rows",
        type=int,
        nargs="*",
        help="Additional physical rows from the same source file",
    )
    parser.add_argument(
        "--sheet",
        help=(
            "Worksheet name. Omit for CSV or when the requested rows resolve to "
            "exactly one worksheet."
        ),
    )
    parser.add_argument(
        "--layer",
        choices=("normalized", "cleaned"),
        default="normalized",
        help="Source-preserving normalized values are the default.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Override the Parquet path selected by --layer.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project.parent / "RAW_DATA_DOWNLOADER" / "dataset" / "manifest.json",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--include-null", action="store_true")
    parser.add_argument("--output", type=Path, help="Write output instead of stdout")
    args = parser.parse_args()
    if args.input is None:
        args.input = (
            project.parent
            / "DATA_NORMALIZATION"
            / "output"
            / f"philgeps_{args.layer}.parquet"
        )
    return args


def parse_breadcrumb(value, additional_rows):
    source_file_id = value
    rows = list(additional_rows)
    prefix, separator, suffix = value.rpartition(":")
    if separator and prefix.startswith("pgf_") and suffix.isdigit():
        source_file_id = prefix
        rows.insert(0, int(suffix))
    if not source_file_id.startswith("pgf_"):
        raise ValueError(
            "Breadcrumb must start with a manifest v2 pgf_ source file ID"
        )
    if not rows:
        raise ValueError(
            "No physical row supplied; use pgf_...:row or pass row numbers separately"
        )
    if any(row < 1 for row in rows):
        raise ValueError("Physical source row numbers must be positive integers")
    return source_file_id, sorted(set(rows))


def load_manifest(path, source_file_id):
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    source_files = {
        entry["source_file_id"]: entry for entry in manifest.get("source_files", [])
    }
    if source_file_id not in source_files:
        raise ValueError(f"source_file_id is not present in manifest v2: {source_file_id}")
    source = source_files[source_file_id]
    documents = {
        entry["document_id"]: entry for entry in manifest.get("documents", [])
    }
    urls = []
    for document_id in source.get("document_ids", []):
        url = documents.get(document_id, {}).get("source_url")
        if url and url not in urls:
            urls.append(url)
    return {
        "source_file_id": source_file_id,
        "normalized_file_name": source.get("normalized_file_name"),
        "local_files": source.get("local_files", []),
        "sha256": source.get("sha256"),
        "document_ids": source.get("document_ids", []),
        "source_urls": urls,
    }


def parquet_columns(connection, path):
    return [
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
    ]


def resolve_sheet(connection, path, source_file_id, rows, requested_sheet):
    placeholders = ", ".join("?" for _ in rows)
    found = connection.execute(
        f"""
        SELECT DISTINCT _source_sheet
        FROM read_parquet(?)
        WHERE _source_file_id = ? AND _source_row_number IN ({placeholders})
        ORDER BY _source_sheet NULLS FIRST
        """,
        [str(path), source_file_id, *rows],
    ).fetchall()
    sheets = [row[0] for row in found]
    if not sheets:
        raise ValueError("No requested rows were found for this source_file_id")
    if requested_sheet is not None:
        if requested_sheet not in sheets:
            rendered = ", ".join("<CSV/null>" if x is None else x for x in sheets)
            raise ValueError(
                f"Requested sheet {requested_sheet!r} was not found; observed: {rendered}"
            )
        return requested_sheet
    if len(sheets) > 1:
        rendered = ", ".join("<CSV/null>" if x is None else x for x in sheets)
        raise ValueError(
            f"Rows occur in multiple worksheets ({rendered}); pass --sheet explicitly"
        )
    return sheets[0]


def fetch_entries(connection, path, source_file_id, sheet, rows, columns):
    placeholders = ", ".join("?" for _ in rows)
    cursor = connection.execute(
        f"""
        SELECT * FROM read_parquet(?)
        WHERE _source_file_id = ?
          AND _source_sheet IS NOT DISTINCT FROM ?
          AND _source_row_number IN ({placeholders})
        ORDER BY _source_row_number
        """,
        [str(path), source_file_id, sheet, *rows],
    )
    entries = [dict(zip(columns, row)) for row in cursor.fetchall()]
    counts = {}
    for entry in entries:
        row_number = entry["_source_row_number"]
        counts[row_number] = counts.get(row_number, 0) + 1
    missing = sorted(set(rows) - set(counts))
    duplicates = sorted(row for row, count in counts.items() if count != 1)
    if missing:
        raise ValueError(f"Physical source rows not found: {missing}")
    if duplicates:
        raise RuntimeError(
            "Breadcrumb uniqueness violation for physical rows: " + str(duplicates)
        )
    return entries


def serializable(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return [serializable(item) for item in value]
    return value


def markdown_value(value):
    value = serializable(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_markdown(payload, include_null):
    source = payload["source"]
    entries = payload["entries"]
    row_numbers = [entry["_source_row_number"] for entry in entries]
    lines = [
        "# PhilGEPS source entries",
        "",
        f"- Layer: `{payload['layer']}`",
        f"- Source file ID: `{source['source_file_id']}`",
        "- Breadcrumbs: "
        + ", ".join(
            f"`{source['source_file_id']}:{row}`" for row in row_numbers
        ),
        f"- Normalized filename: `{source['normalized_file_name']}`",
        f"- SHA-256: `{source['sha256']}`",
        f"- Worksheet: `{payload['sheet'] if payload['sheet'] is not None else '--'}`",
        "- Physical rows: " + ", ".join(f"`{row}`" for row in row_numbers),
    ]
    if source["source_urls"]:
        lines.append(
            "- Source URLs: "
            + ", ".join(
                f"[source {index}]({url})"
                for index, url in enumerate(source["source_urls"], start=1)
            )
        )
    lines.extend(["", "| Field | " + " | ".join(f"Row {row}" for row in row_numbers) + " |"])
    lines.append("|---|" + "---|" * len(entries))
    fields = [field for field in payload["columns"] if field not in PROVENANCE_COLUMNS]
    for field in fields:
        values = [entry.get(field) for entry in entries]
        if not include_null and all(value is None or value == [] for value in values):
            continue
        lines.append(
            f"| `{field}` | "
            + " | ".join(markdown_value(value) for value in values)
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_json(payload, include_null):
    result = {key: value for key, value in payload.items() if key != "columns"}
    result["entries"] = []
    for entry in payload["entries"]:
        rendered = {}
        for key, value in entry.items():
            value = serializable(value)
            if include_null or value not in (None, []):
                rendered[key] = value
        result["entries"].append(rendered)
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def main():
    args = parse_args()
    path = args.input.resolve()
    manifest_path = args.manifest.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    source_file_id, rows = parse_breadcrumb(args.breadcrumb, args.rows)
    source = load_manifest(manifest_path, source_file_id)

    connection = duckdb.connect()
    try:
        columns = parquet_columns(connection, path)
        sheet = resolve_sheet(
            connection, path, source_file_id, rows, args.sheet
        )
        entries = fetch_entries(
            connection, path, source_file_id, sheet, rows, columns
        )
    finally:
        connection.close()

    payload = {
        "layer": args.layer,
        "input": str(path),
        "observation_key": [
            "_source_file_id",
            "_source_row_number",
        ],
        "worksheet_disambiguator": "_source_sheet",
        "source": source,
        "sheet": sheet,
        "columns": columns,
        "entries": entries,
    }
    output = (
        render_markdown(payload, args.include_null)
        if args.format == "markdown"
        else render_json(payload, args.include_null)
    )
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(output, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(output, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
