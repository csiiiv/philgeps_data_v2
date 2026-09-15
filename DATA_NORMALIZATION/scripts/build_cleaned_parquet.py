#!/usr/bin/env python3
"""Build one typed, cleaned PhilGEPS Parquet from the immutable normalized layer."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import duckdb


PROVENANCE_COLUMNS = [
    "_source_file_id",
    "_source_sheet",
    "_source_row_number",
    "_source_schema_id",
]


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=project / "output" / "philgeps_normalized.parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "output" / "philgeps_cleaned.parquet",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=project / "config" / "cleaning_rules.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=project / "artifacts" / "cleaned_parquet_validation.json",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-rows", type=int, help="Testing only: clean this many rows")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def clean_text_expression(column, rules):
    name = quote_identifier(column)
    nulls = ", ".join(sql_string(value.upper()) for value in rules["null_literals"])
    cleaned = f"nfc_normalize(trim({name}))"
    if column in set(rules["organization_name_columns"]) | set(
        rules["categorical_columns"]
    ):
        cleaned = f"trim(regexp_replace({cleaned}, '[\\s\\p{{Zs}}]+', ' ', 'g'))"
    expression = (
        f"CASE WHEN {name} IS NULL OR trim({name}) = '' "
        f"OR upper(trim({name})) IN ({nulls}) THEN NULL ELSE {cleaned} END"
    )
    mappings = rules.get("categorical_value_map", {}).get(column, {})
    for original, replacement in mappings.items():
        expression = (
            f"CASE WHEN ({expression}) = {sql_string(original)} "
            f"THEN {sql_string(replacement)} ELSE ({expression}) END"
        )
    return expression


def timestamp_expression(column):
    name = quote_identifier(column)
    return (
        "CASE "
        f"WHEN {name} IS NULL THEN NULL "
        f"WHEN try_strptime({name}, '%d/%m/%Y') IS NOT NULL "
        f"THEN try_strptime({name}, '%d/%m/%Y') "
        f"WHEN try_strptime({name}, '%Y-%m-%d') IS NOT NULL "
        f"THEN try_strptime({name}, '%Y-%m-%d') "
        f"WHEN try_cast({name} AS DOUBLE) BETWEEN 1 AND 100000 "
        f"THEN TIMESTAMP '1899-12-30' + try_cast({name} AS DOUBLE) * INTERVAL '1 day' "
        "ELSE NULL END"
    )


def decimal_expression(column, target_type, rules):
    name = quote_identifier(column)
    scale = int(target_type.rstrip(")").split(",")[1])
    converted = f"cast(round(try_cast({name} AS DECIMAL(38,10)), {scale}) AS {target_type})"
    sentinels = rules.get("numeric_null_sentinels", {}).get(column, [])
    if not sentinels:
        return converted
    sentinel_checks = " OR ".join(
        f"try_cast({name} AS DECIMAL(38,10)) = try_cast({sql_string(value)} AS DECIMAL(38,10))"
        for value in sentinels
    )
    return f"CASE WHEN {sentinel_checks} THEN NULL ELSE {converted} END"


def list_expression(items):
    if not items:
        return "[]::VARCHAR[]"
    values = ", ".join(f"CASE WHEN {condition} THEN {sql_string(label)} END" for label, condition in items)
    return f"list_filter([{values}], value -> value IS NOT NULL)"


def build_query(columns, types, rules, max_rows):
    source_columns = [
        column
        for column in columns
        if column not in PROVENANCE_COLUMNS and column != "_extra_values"
    ]
    text_columns = [column for column in source_columns if types[column] == "VARCHAR"]
    timestamps = set(rules["timestamp_columns"])
    decimals = rules["decimal_columns"]
    integers = set(rules["integer_columns"])

    input_relation = "read_parquet(?)"
    if max_rows:
        input_relation = f"(SELECT * FROM read_parquet(?) LIMIT {int(max_rows)})"

    cleaned_select = [quote_identifier(column) for column in PROVENANCE_COLUMNS]
    cleaned_select.extend(
        f"{clean_text_expression(column, rules)} AS {quote_identifier(column)}"
        if column in text_columns
        else quote_identifier(column)
        for column in source_columns
    )
    cleaned_select.append(quote_identifier("_extra_values"))

    replacement_items = [
        (column, f"strpos({quote_identifier(column)}, chr(65533)) > 0")
        for column in text_columns
    ]

    typed_select = [quote_identifier(column) for column in PROVENANCE_COLUMNS]
    for column in source_columns:
        name = quote_identifier(column)
        if column in timestamps:
            typed_select.append(f"{timestamp_expression(column)} AS {name}")
            typed_select.append(f"{name} AS {quote_identifier('__raw_' + column)}")
        elif column in decimals:
            typed_select.append(
                f"{decimal_expression(column, decimals[column], rules)} AS {name}"
            )
            if column in rules.get("numeric_null_sentinels", {}):
                typed_select.append(
                    f"{name} AS {quote_identifier('__raw_' + column)}"
                )
        elif column in integers:
            typed_select.append(f"try_cast({name} AS BIGINT) AS {name}")
        else:
            typed_select.append(name)
    typed_select.append(quote_identifier("_extra_values"))
    typed_select.append(
        f"{list_expression(replacement_items)} AS _replacement_character_columns"
    )

    organization_keys = []
    for column in rules["organization_name_columns"]:
        organization_keys.append(
            f"upper({quote_identifier(column)}) AS {quote_identifier(column + '_key')}"
        )

    issues = []
    for column in rules["timestamp_columns"]:
        issues.append(
            (
                f"invalid_{column}",
                f"{quote_identifier('__raw_' + column)} IS NOT NULL AND {quote_identifier(column)} IS NULL",
            )
        )
    issues.extend(
        [
            (
                "replacement_character",
                "length(_replacement_character_columns) > 0",
            ),
            ("missing_bid_reference", "bid_reference_no IS NULL"),
            (
                "closing_before_published",
                "closing_date IS NOT NULL AND bid_published_date IS NOT NULL AND closing_date < bid_published_date",
            ),
            (
                "award_before_bid_published",
                "award_date IS NOT NULL AND bid_published_date IS NOT NULL AND award_date < bid_published_date",
            ),
            (
                "contract_end_before_effectivity",
                "contract_end_date IS NOT NULL AND contract_effectivity_date IS NOT NULL AND contract_end_date < contract_effectivity_date",
            ),
            (
                "contract_end_before_notice_to_proceed",
                "contract_end_date IS NOT NULL AND notice_to_proceed_date IS NOT NULL AND contract_end_date < notice_to_proceed_date",
            ),
            ("negative_approved_budget", "approved_budget < 0"),
            ("negative_item_budget", "item_budget < 0"),
            ("negative_contract_amount", "contract_amount < 0"),
            ("negative_quantity", "quantity < 0"),
            ("negative_contract_duration", "contract_duration < 0"),
            (
                "item_budget_not_provided_sentinel",
                "try_cast(__raw_item_budget AS DECIMAL(38,10)) = -1",
            ),
            (
                "contract_amount_exceeds_approved_budget",
                "contract_amount IS NOT NULL AND approved_budget IS NOT NULL AND contract_amount > approved_budget",
            ),
            (
                "item_budget_exceeds_approved_budget",
                "item_budget IS NOT NULL AND approved_budget IS NOT NULL AND item_budget > approved_budget",
            ),
            (
                "invalid_unspsc_code",
                "unspsc_code IS NOT NULL AND NOT regexp_full_match(unspsc_code, '[0-9]{8}')",
            ),
        ]
    )
    issue_list = list_expression(issues)

    helper_columns = {"__raw_" + column for column in timestamps}
    final_base = [
        quote_identifier(column)
        for column in columns
        if column not in helper_columns
    ]
    final_base.extend(organization_keys)
    final_base.append("_replacement_character_columns")

    return f"""
WITH cleaned AS (
  SELECT {', '.join(cleaned_select)}
  FROM {input_relation}
),
typed AS (
  SELECT {', '.join(typed_select)}
  FROM cleaned
),
quality AS (
  SELECT *, {issue_list} AS _cleaning_issues
  FROM typed
)
SELECT {', '.join(final_base)},
       _cleaning_issues,
       length(_cleaning_issues)::INTEGER AS _cleaning_issue_count
FROM quality
"""


def describe_input(connection, path):
    rows = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
    ).fetchall()
    return [row[0] for row in rows], {row[0]: row[1] for row in rows}


def validate(connection, input_path, output_path, report_path, elapsed, truncated):
    input_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(input_path)]
    ).fetchone()[0]
    output_row = connection.execute(
        """
        SELECT count(*), count(distinct _source_file_id),
               count(*) FILTER (WHERE _source_file_id IS NULL OR _source_row_number IS NULL),
               count(*) FILTER (WHERE _cleaning_issue_count > 0),
               coalesce(sum(length(_replacement_character_columns)), 0)
        FROM read_parquet(?)
        """,
        [str(output_path)],
    ).fetchone()
    issue_rows = connection.execute(
        """
        SELECT issue, count(*)
        FROM read_parquet(?), unnest(_cleaning_issues) AS issues(issue)
        GROUP BY issue ORDER BY issue
        """,
        [str(output_path)],
    ).fetchall()
    duplicate_provenance_groups = connection.execute(
        """
        SELECT count(*) FROM (
          SELECT _source_file_id, _source_sheet, _source_row_number, count(*) AS copies
          FROM read_parquet(?)
          GROUP BY 1, 2, 3 HAVING copies > 1
        )
        """,
        [str(output_path)],
    ).fetchone()[0]
    types = {
        row[0]: row[1]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(output_path)]
        ).fetchall()
    }
    report = {
        "status": "pass"
        if output_row[0] == (output_row[0] if truncated else input_rows)
        and output_row[2] == 0
        and duplicate_provenance_groups == 0
        else "fail",
        "input_file": str(input_path),
        "output_file": str(output_path),
        "input_row_count": input_rows,
        "output_row_count": output_row[0],
        "source_file_count": output_row[1],
        "null_required_provenance_row_count": output_row[2],
        "duplicate_provenance_group_count": duplicate_provenance_groups,
        "rows_with_cleaning_issues": output_row[3],
        "replacement_character_cell_count": output_row[4],
        "issue_counts": dict(issue_rows),
        "column_types": types,
        "output_size_bytes": output_path.stat().st_size,
        "elapsed_seconds": round(elapsed, 3),
        "truncated_for_test": truncated,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "pass":
        raise RuntimeError("cleaned Parquet validation failed")
    return report


def main():
    args = parse_args()
    args.input = args.input.resolve()
    args.output = args.output.resolve()
    args.rules = args.rules.resolve()
    args.report = args.report.resolve()
    if not args.input.exists():
        raise FileNotFoundError(args.input)
    if args.output.exists() and not args.force:
        raise FileExistsError(f"{args.output} exists; pass --force to replace it")
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = args.output.with_suffix(args.output.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    columns, types = describe_input(connection, args.input)
    query = build_query(columns, types, rules, args.max_rows)
    started = time.perf_counter()
    try:
        connection.execute(
            f"COPY ({query}) TO {sql_string(str(temp_path))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)",
            [str(args.input)],
        )
        os.replace(temp_path, args.output)
        elapsed = time.perf_counter() - started
        report = validate(
            connection,
            args.input,
            args.output,
            args.report,
            elapsed,
            bool(args.max_rows),
        )
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        connection.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
