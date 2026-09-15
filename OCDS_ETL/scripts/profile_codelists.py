#!/usr/bin/env python3
"""Profile source values that require OCDS codelist or semantic mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


FIELDS = (
    "classification",
    "notice_type",
    "procurement_mode",
    "trade_agreement",
    "calendar_type",
    "bid_notice_status",
    "award_type",
    "award_notice_status",
    "government_branch",
    "procuring_entity_organization_type_grouped",
    "awardee_size",
)


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
        "--json-output",
        type=Path,
        default=project / "artifacts" / "codelist_profile.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "artifacts" / "codelist_profile.md",
    )
    parser.add_argument("--threads", type=int, default=4)
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_markdown(profile: dict) -> str:
    lines = [
        "# Source codelist profile",
        "",
        f"- Input: `{profile['input']}`",
        f"- Observation rows: `{profile['observation_rows']:,}`",
        "",
        "Counts describe cleaned source values. They are evidence for mapping "
        "decisions, not an assertion that every field is an OCDS codelist.",
    ]
    for field, details in profile["fields"].items():
        lines.extend(
            [
                "",
                f"## `{field}`",
                "",
                f"- Distinct non-null values: `{details['distinct_non_null']:,}`",
                f"- Null observations: `{details['null_observations']:,}`",
                "",
                "| Source value | Observations |",
                "|---|---:|",
            ]
        )
        for row in details["values"]:
            value = str(row["source_value"]).replace("|", "\\|")
            lines.append(f"| `{value}` | {row['observation_rows']:,} |")
    lines.append("")
    return "\n".join(lines)


def main():
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    relation = f"read_parquet({quote(str(input_path))})"
    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    try:
        observation_rows = connection.execute(
            f"SELECT count(*) FROM {relation}"
        ).fetchone()[0]
        fields = {}
        for field in FIELDS:
            distinct_non_null, null_observations = connection.execute(
                f"""
                SELECT count(DISTINCT {field}) FILTER (WHERE {field} IS NOT NULL),
                       count(*) FILTER (WHERE {field} IS NULL)
                FROM {relation}
                """
            ).fetchone()
            values = [
                {"source_value": value, "observation_rows": count}
                for value, count in connection.execute(
                    f"""
                    SELECT {field}, count(*) AS observations
                    FROM {relation}
                    WHERE {field} IS NOT NULL
                    GROUP BY 1
                    ORDER BY observations DESC, {field}
                    """
                ).fetchall()
            ]
            fields[field] = {
                "distinct_non_null": distinct_non_null,
                "null_observations": null_observations,
                "values": values,
            }
    finally:
        connection.close()
    profile = {
        "input": str(input_path),
        "observation_rows": observation_rows,
        "fields": fields,
    }
    args.json_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.resolve().write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.resolve().write_text(
        render_markdown(profile), encoding="utf-8"
    )
    print(json.dumps({
        "observation_rows": observation_rows,
        "distinct_counts": {
            field: details["distinct_non_null"]
            for field, details in fields.items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
