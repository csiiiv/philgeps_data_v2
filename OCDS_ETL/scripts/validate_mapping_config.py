#!/usr/bin/env python3
"""Validate field and codelist configuration against the cleaned source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=project.parent
        / "DATA_NORMALIZATION"
        / "output"
        / "philgeps_cleaned.parquet",
    )
    parser.add_argument(
        "--field-mapping",
        type=Path,
        default=project / "config" / "field_mapping.json",
    )
    parser.add_argument(
        "--codelist-mapping",
        type=Path,
        default=project / "config" / "codelist_mapping.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "artifacts" / "mapping_coverage.json",
    )
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main():
    args = parse_args()
    field_mapping = json.loads(args.field_mapping.read_text(encoding="utf-8"))
    codelist_mapping = json.loads(
        args.codelist_mapping.read_text(encoding="utf-8")
    )
    input_path = args.input.resolve()
    connection = duckdb.connect()
    relation = f"read_parquet({quote(str(input_path))})"
    try:
        source_columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {relation}"
            ).fetchall()
        ]
        configured_fields = set(field_mapping["fields"])
        missing_fields = sorted(set(source_columns) - configured_fields)
        extra_fields = sorted(configured_fields - set(source_columns))
        domain_results = {}
        for field, config in codelist_mapping["mappings"].items():
            source_values = {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT {field} FROM {relation} "
                    f"WHERE {field} IS NOT NULL"
                ).fetchall()
            }
            configured_values = set(config["values"])
            domain_results[field] = {
                "source_distinct_values": len(source_values),
                "configured_values": len(configured_values),
                "unmapped_source_values": sorted(
                    source_values - configured_values
                ),
                "configured_values_not_in_source": sorted(
                    configured_values - source_values
                ),
            }
    finally:
        connection.close()
    failures = []
    if missing_fields:
        failures.append("cleaned input fields missing from field mapping")
    if extra_fields:
        failures.append("field mapping contains fields absent from cleaned input")
    for field, result in domain_results.items():
        if result["unmapped_source_values"]:
            failures.append(f"{field} has unmapped source values")
        if result["configured_values_not_in_source"]:
            failures.append(f"{field} has configured values absent from source")
    report = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "source_columns": len(source_columns),
        "configured_fields": len(configured_fields),
        "missing_fields": missing_fields,
        "extra_fields": extra_fields,
        "codelist_domains": domain_results,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
