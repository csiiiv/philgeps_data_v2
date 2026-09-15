#!/usr/bin/env python3
"""Stream all PhilGEPS sources into one schema-normalized Parquet file."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import posixpath
import re
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq


SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
S = f"{{{SPREADSHEET_NS}}}"
R = f"{{{OFFICE_REL_NS}}}"
PR = f"{{{PACKAGE_REL_NS}}}"
CELL_REF_RE = re.compile(r"([A-Z]+)([0-9]+)")
TEXT_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s.*)?$")
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")
NULL_LITERALS = {"NULL", "N/A", "NA", "NONE"}
DATE_COLUMNS = {
    "bid_published_date",
    "closing_date",
    "prebid_date",
    "award_published_date",
    "award_date",
    "notice_to_proceed_date",
    "contract_effectivity_date",
    "contract_end_date",
}


def parse_args():
    project = Path(__file__).resolve().parents[1]
    root = project.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=root / "RAW_DATA_DOWNLOADER" / "dataset",
    )
    parser.add_argument(
        "--catalog", type=Path, default=project / "artifacts" / "source_catalog.json"
    )
    parser.add_argument(
        "--registry", type=Path, default=project / "config" / "schema_registry.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "output" / "philgeps_normalized.parquet",
    )
    parser.add_argument(
        "--qa-output", type=Path, default=project / "artifacts" / "raw_ingestion"
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob matched against local path, basename, schema, or normalized name",
    )
    parser.add_argument("--batch-size", type=int, default=25_000)
    parser.add_argument(
        "--max-rows", type=int, help="Testing only: stop after this many rows per source"
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing output")
    return parser.parse_args()


def resolve_schemas(registry):
    raw = registry["schemas"]
    resolved = {}

    def resolve(name):
        if name in resolved:
            return resolved[name]
        spec = raw[name]
        if "columns" in spec:
            columns = list(spec["columns"])
        else:
            columns = list(resolve(spec["extends"]))
            columns = [spec.get("replace", {}).get(column, column) for column in columns]
        resolved[name] = columns
        return columns

    for name in raw:
        resolve(name)
    return resolved


def canonical_columns(schemas, aliases):
    result = []
    for columns in schemas.values():
        for source_column in columns:
            canonical = aliases[source_column]
            if canonical not in result:
                result.append(canonical)
    return result


def parquet_schema(columns, metadata):
    fields = [
        pa.field("_source_file_id", pa.string(), nullable=False),
        pa.field("_source_sheet", pa.string()),
        pa.field("_source_row_number", pa.int64(), nullable=False),
        pa.field("_source_schema_id", pa.string(), nullable=False),
    ]
    fields.extend(pa.field(column, pa.string()) for column in columns)
    fields.append(pa.field("_extra_values", pa.list_(pa.string())))
    return pa.schema(fields, metadata={key: str(value) for key, value in metadata.items()})


def column_index(cell_reference):
    match = CELL_REF_RE.fullmatch(cell_reference)
    if not match:
        raise ValueError(f"invalid XLSX cell reference: {cell_reference}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def workbook_sheets(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships.findall(PR + "Relationship")
    }
    result = []
    for sheet in workbook.findall(f"{S}sheets/{S}sheet"):
        target = targets[sheet.attrib[R + "id"]].lstrip("/")
        if not target.startswith("xl/"):
            target = posixpath.normpath(posixpath.join("xl", target))
        result.append((sheet.attrib["name"], target))
    return result


def load_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings = []
    with archive.open("xl/sharedStrings.xml") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag == S + "si":
                strings.append("".join(node.text or "" for node in element.iter(S + "t")))
                element.clear()
    return strings


def xlsx_cell_value(cell, shared_strings, qa):
    cell_type = cell.attrib.get("t")
    value_node = cell.find(S + "v")
    inline_node = cell.find(S + "is")
    formula_node = cell.find(S + "f")
    if formula_node is not None:
        qa["formula_cell_count"] += 1
    if inline_node is not None:
        return "".join(node.text or "" for node in inline_node.iter(S + "t"))
    if value_node is None:
        return None
    raw = value_node.text or ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError) as error:
            raise ValueError(f"invalid shared string index {raw!r}") from error
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def classify_null(value, profile):
    if value is None:
        profile["missing_cell"] += 1
    elif not value.strip():
        profile["blank_string"] += 1
    elif value.strip().upper() in NULL_LITERALS:
        profile["null_literal"] += 1
    else:
        profile["nonempty"] += 1


def date_month(value, source_format):
    if value is None:
        return None
    text = value.strip()
    match = TEXT_DATE_RE.fullmatch(text)
    if match:
        day, month, year = map(int, match.groups())
        try:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}"
        except ValueError:
            return None
    match = ISO_DATE_RE.fullmatch(text)
    if match:
        year, month, day = map(int, match.groups())
        try:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}"
        except ValueError:
            return None
    if source_format == "xlsx":
        try:
            serial = float(text)
            if 1 <= serial <= 100_000:
                value_date = datetime(1899, 12, 30) + timedelta(days=serial)
                return value_date.strftime("%Y-%m")
        except ValueError:
            return None
    return None


class CombinedWriter:
    def __init__(
        self,
        output_path,
        schema,
        canonical_names,
        batch_size,
    ):
        self.output_path = output_path
        self.temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        self.schema = schema
        self.canonical_names = canonical_names
        self.batch_size = batch_size
        self.source_file_id = None
        self.source_sheet = None
        self.schema_id = None
        self.source_format = None
        self.qa = None
        self.mapping = []
        self.buffers = {}
        self.row_numbers = []
        self.extra_values = []
        self.writer = pq.ParquetWriter(
            self.temp_path,
            schema,
            compression="zstd",
            compression_level=6,
            use_dictionary=True,
            write_statistics=True,
        )

    def begin_source(
        self,
        source_columns,
        aliases,
        source_file_id,
        source_sheet,
        schema_id,
        source_format,
        qa,
    ):
        self.flush()
        self.source_file_id = source_file_id
        self.source_sheet = source_sheet
        self.schema_id = schema_id
        self.source_format = source_format
        self.qa = qa
        self.mapping = [aliases[column] for column in source_columns]
        if len(self.mapping) != len(set(self.mapping)):
            raise ValueError(f"schema {schema_id} maps two source columns to one canonical column")
        self.buffers = {column: [] for column in self.mapping}

    def add(self, physical_row_number, values, extras):
        self.row_numbers.append(physical_row_number)
        for index, canonical in enumerate(self.mapping):
            value = values[index] if index < len(values) else None
            self.buffers[canonical].append(value)
            classify_null(value, self.qa["null_profile"][canonical])
            if "\ufffd" in (value or ""):
                self.qa["replacement_character_cell_count"] += 1
            if canonical in DATE_COLUMNS:
                month = date_month(value, self.source_format)
                if month:
                    self.qa["date_months"][canonical][month] += 1
        self.extra_values.append(extras or None)
        if len(self.row_numbers) >= self.batch_size:
            self.flush()

    def flush(self):
        row_count = len(self.row_numbers)
        if not row_count:
            return
        arrays = [
            pa.array([self.source_file_id] * row_count, type=pa.string()),
            pa.array([self.source_sheet] * row_count, type=pa.string()),
            pa.array(self.row_numbers, type=pa.int64()),
            pa.array([self.schema_id] * row_count, type=pa.string()),
        ]
        for canonical in self.canonical_names:
            if canonical in self.buffers:
                arrays.append(pa.array(self.buffers[canonical], type=pa.string()))
            else:
                arrays.append(pa.nulls(row_count, type=pa.string()))
        arrays.append(pa.array(self.extra_values, type=pa.list_(pa.string())))
        self.writer.write_table(pa.Table.from_arrays(arrays, schema=self.schema))
        self.row_numbers.clear()
        self.extra_values.clear()
        for buffer in self.buffers.values():
            buffer.clear()

    def close(self):
        self.flush()
        self.writer.close()
        os.replace(self.temp_path, self.output_path)

    def abort(self):
        try:
            self.writer.close()
        finally:
            if self.temp_path.exists():
                self.temp_path.unlink()


def new_qa(source, output_path, source_columns, aliases):
    return {
        "status": "running",
        "source_file_id": source["source_file_id"],
        "local_file": source["local_files"][0],
        "normalized_file_name": source["normalized_file_name"],
        "schema_id": source["sheets"][0]["schema_id"],
        "format": source["format"],
        "input_size_bytes": source["size_bytes"],
        "output_file": str(output_path),
        "expected_column_count": len(source_columns),
        "physical_data_rows_seen": 0,
        "rows_written": 0,
        "blank_rows_skipped": 0,
        "width_counts": Counter(),
        "malformed_width_row_count": 0,
        "malformed_width_examples": [],
        "formula_cell_count": 0,
        "replacement_character_cell_count": 0,
        "null_profile": {
            column: Counter(
                {"missing_cell": 0, "blank_string": 0, "null_literal": 0, "nonempty": 0}
            )
            for column in dict.fromkeys(aliases[source_column] for source_column in source_columns)
        },
        "date_months": {column: Counter() for column in DATE_COLUMNS},
    }


def record_width(qa, physical_row_number, width, expected):
    qa["width_counts"][str(width)] += 1
    if width != expected:
        qa["malformed_width_row_count"] += 1
        if len(qa["malformed_width_examples"]) < 100:
            qa["malformed_width_examples"].append(
                {
                    "source_row_number": physical_row_number,
                    "observed_columns": width,
                    "expected_columns": expected,
                }
            )


def ingest_csv(path, sheet, source_columns, writer, qa, max_rows):
    expected = len(source_columns)
    header_present = sheet["header_present"]
    data_ordinal = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        if header_present:
            header = next(reader, None)
            if tuple(value.strip() for value in (header or [])) != tuple(source_columns):
                raise ValueError("CSV header changed after catalog verification")
        for row in reader:
            data_ordinal += 1
            physical_row_number = data_ordinal + (1 if header_present else 0)
            qa["physical_data_rows_seen"] += 1
            if not row or all(not value for value in row):
                qa["blank_rows_skipped"] += 1
            else:
                record_width(qa, physical_row_number, len(row), expected)
                values = (row[:expected] + [None] * expected)[:expected]
                writer.add(physical_row_number, values, row[expected:])
                qa["rows_written"] += 1
            if max_rows and qa["physical_data_rows_seen"] >= max_rows:
                qa["truncated_for_test"] = True
                break


def ingest_xlsx(path, sheet, source_columns, writer, qa, max_rows):
    expected = len(source_columns)
    header_row = sheet["header_row_number"]
    with zipfile.ZipFile(path) as archive:
        load_started = time.time()
        shared_strings = load_shared_strings(archive)
        members = dict(workbook_sheets(archive))
        member = members[sheet["sheet_name"]]
        qa["xlsx_load_seconds"] = round(time.time() - load_started, 3)
        with archive.open(member) as handle:
            for _, row_element in ET.iterparse(handle, events=("end",)):
                if row_element.tag != S + "row":
                    continue
                row_number = int(row_element.attrib.get("r", "0"))
                if row_number < header_row:
                    row_element.clear()
                    continue
                cells = []
                maximum_index = -1
                for cell in row_element.findall(S + "c"):
                    index = column_index(cell.attrib["r"])
                    maximum_index = max(maximum_index, index)
                    cells.append((index, xlsx_cell_value(cell, shared_strings, qa)))
                width = maximum_index + 1
                values = [None] * max(width, expected)
                for index, value in cells:
                    values[index] = value
                if row_number == header_row:
                    if tuple((value or "").strip() for value in values[:expected]) != tuple(
                        source_columns
                    ):
                        raise ValueError("XLSX header changed after catalog verification")
                    row_element.clear()
                    continue

                qa["physical_data_rows_seen"] += 1
                if not cells or all(value is None or value == "" for _, value in cells):
                    qa["blank_rows_skipped"] += 1
                else:
                    record_width(qa, row_number, width, expected)
                    writer.add(row_number, values[:expected], values[expected:width])
                    qa["rows_written"] += 1
                row_element.clear()
                if max_rows and qa["physical_data_rows_seen"] >= max_rows:
                    qa["truncated_for_test"] = True
                    break


def json_ready(qa):
    result = dict(qa)
    result["width_counts"] = dict(qa["width_counts"])
    result["null_profile"] = {
        column: dict(counts) for column, counts in qa["null_profile"].items()
    }
    result["date_months"] = {
        column: dict(sorted(counts.items()))
        for column, counts in qa["date_months"].items()
        if counts
    }
    return result


def selected(source, patterns):
    if not patterns:
        return True
    candidates = {
        source["local_files"][0],
        Path(source["local_files"][0]).name,
        source["normalized_file_name"],
        source["sheets"][0]["schema_id"],
    }
    return any(
        fnmatch.fnmatch(candidate, pattern) for pattern in patterns for candidate in candidates
    )


def main():
    args = parse_args()
    started = time.time()
    dataset = args.dataset.resolve()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    schemas = resolve_schemas(registry)
    aliases = registry["column_aliases"]
    all_source_columns = {column for columns in schemas.values() for column in columns}
    missing_aliases = sorted(all_source_columns - set(aliases))
    if missing_aliases:
        raise ValueError(f"unmapped source columns: {missing_aliases}")
    canonical_names = canonical_columns(schemas, aliases)

    sources = [source for source in catalog["source_files"] if selected(source, args.include)]
    if not sources:
        raise ValueError("no source files matched --include")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and not args.force:
        raise FileExistsError(f"output already exists; use --force: {args.output}")
    file_qa_dir = args.qa_output / "files"
    file_qa_dir.mkdir(parents=True, exist_ok=True)
    completed = []
    metadata = {
        "philgeps.dataset": "schema-normalized cross-year source observations",
        "philgeps.manifest_version": 2,
        "philgeps.source_file_count": len(sources),
        "philgeps.value_policy": "source values preserved as nullable strings",
    }
    schema = parquet_schema(canonical_names, metadata)
    combined_writer = CombinedWriter(
        args.output, schema, canonical_names, args.batch_size
    )

    try:
        for index, source in enumerate(sources, start=1):
            local_file = source["local_files"][0]
            sheet = source["sheets"][0]
            schema_id = sheet["schema_id"]
            source_columns = schemas[schema_id]
            qa_path = file_qa_dir / f"{source['source_file_id']}.json"
            qa = new_qa(source, args.output.name, source_columns, aliases)
            file_started = time.time()
            combined_writer.begin_source(
                source_columns,
                aliases,
                source["source_file_id"],
                sheet["sheet_name"],
                schema_id,
                source["format"],
                qa,
            )
            print(
                f"[{index}/{len(sources)}] ingest {local_file} ({schema_id})",
                flush=True,
            )
            path = dataset / local_file
            if source["format"] == "csv":
                ingest_csv(path, sheet, source_columns, combined_writer, qa, args.max_rows)
            elif source["format"] == "xlsx":
                ingest_xlsx(path, sheet, source_columns, combined_writer, qa, args.max_rows)
            else:
                raise ValueError(f"unsupported format {source['format']}")
            combined_writer.flush()
            qa["status"] = "complete"
            qa["elapsed_seconds"] = round(time.time() - file_started, 3)
            ready = json_ready(qa)
            qa_path.write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")
            completed.append(ready)
            load_note = (
                f" (xlsx load {qa['xlsx_load_seconds']}s)"
                if qa.get("xlsx_load_seconds") is not None
                else ""
            )
            print(
                f"    rows={qa['rows_written']:,} malformed={qa['malformed_width_row_count']:,} "
                f"seconds={qa['elapsed_seconds']}{load_note}",
                flush=True,
            )
        combined_writer.close()
    except Exception:
        combined_writer.abort()
        raise

    summary = {
        "status": "complete",
        "source_file_count": len(completed),
        "rows_written": sum(item["rows_written"] for item in completed),
        "physical_data_rows_seen": sum(item["physical_data_rows_seen"] for item in completed),
        "blank_rows_skipped": sum(item["blank_rows_skipped"] for item in completed),
        "malformed_width_row_count": sum(
            item["malformed_width_row_count"] for item in completed
        ),
        "input_size_bytes": sum(item["input_size_bytes"] for item in completed),
        "output_file": str(args.output),
        "output_size_bytes": args.output.stat().st_size,
        "compression_ratio_vs_source": round(
            args.output.stat().st_size / sum(item["input_size_bytes"] for item in completed), 4
        ),
        "elapsed_seconds": round(time.time() - started, 3),
        "truncated_for_test": bool(args.max_rows),
        "files": [
            {
                "source_file_id": item["source_file_id"],
                "local_file": item["local_file"],
                "output_file": item["output_file"],
                "rows_written": item["rows_written"],
                "malformed_width_row_count": item["malformed_width_row_count"],
            }
            for item in completed
        ],
    }
    args.qa_output.mkdir(parents=True, exist_ok=True)
    (args.qa_output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "files"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
