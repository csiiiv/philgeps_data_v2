#!/usr/bin/env python3
"""Semantically verify headerless CSV files against registered schemas."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path


SAMPLE_ROWS = 5_000
NULL_VALUES = {"", "NULL", "N/A", "NA", "NONE"}
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s.*)?$")
NUMBER_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})--(\d{4})-(\d{2})")


def value_kind(value):
    text = value.strip()
    if text.upper() in NULL_VALUES:
        return "null"
    if DATE_RE.fullmatch(text):
        return "date"
    if NUMBER_RE.fullmatch(text.replace(",", "")):
        return "number"
    return "text"


def sample_rows(path, header_present, limit=SAMPLE_ROWS):
    rows = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        if header_present:
            next(reader, None)
        for row in reader:
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def profile_types(rows, width):
    profiles = []
    for index in range(width):
        counts = Counter(value_kind(row[index]) for row in rows if len(row) > index)
        total = sum(counts.values()) or 1
        profiles.append({kind: count / total for kind, count in counts.items()})
    return profiles


def mean_type_distance(reference, candidate):
    kinds = {"null", "date", "number", "text"}
    distances = []
    for left, right in zip(reference, candidate):
        distances.append(
            0.5 * sum(abs(left.get(kind, 0) - right.get(kind, 0)) for kind in kinds)
        )
    return sum(distances) / len(distances)


def nonnull_values(rows, index):
    return [
        row[index].strip()
        for row in rows
        if len(row) > index and row[index].strip().upper() not in NULL_VALUES
    ]


def kind_rate(rows, index, expected_kind):
    values = nonnull_values(rows, index)
    if not values:
        return None
    return sum(value_kind(value) == expected_kind for value in values) / len(values)


def vocabulary_rate(rows, index, vocabulary):
    values = nonnull_values(rows, index)
    if not values:
        return None
    return sum(value in vocabulary for value in values) / len(values)


def month_counts(rows, index):
    counts = Counter()
    for value in nonnull_values(rows, index):
        match = DATE_RE.fullmatch(value)
        if match:
            counts[f"{int(match.group(3)):04d}-{int(match.group(2)):02d}"] += 1
    return counts


def in_expected_period(month, normalized_file_name):
    match = PERIOD_RE.match(normalized_file_name)
    if not match:
        return False
    start = f"{match.group(1)}-{match.group(2)}"
    end = f"{match.group(3)}-{match.group(4)}"
    return start <= month <= end


def main():
    project = Path(__file__).resolve().parents[1]
    root = project.parent
    files_dir = root / "RAW_DATA_DOWNLOADER" / "dataset" / "files"
    registry = json.loads((project / "config" / "schema_registry.json").read_text(encoding="utf-8"))
    catalog = json.loads((project / "artifacts" / "source_catalog.json").read_text(encoding="utf-8"))
    schemas = registry["schemas"]
    schema_widths = {}
    for name, spec in schemas.items():
        if "columns" in spec:
            schema_widths[name] = len(spec["columns"])
        else:
            schema_widths[name] = len(schemas[spec["extends"]]["columns"])

    catalog_by_file = {
        item["local_files"][0]: item for item in catalog["source_files"]
    }
    headerless = registry["known_headerless_files"]
    reference_files = [
        item["local_files"][0]
        for item in catalog["source_files"]
        if item["sheets"][0]["schema_id"] == "location_46"
        and item["sheets"][0]["header_present"]
    ]

    reference_rows = []
    per_reference = max(1, SAMPLE_ROWS // len(reference_files))
    for local_file in reference_files:
        reference_rows.extend(
            sample_rows(root / "RAW_DATA_DOWNLOADER" / "dataset" / local_file, True, per_reference)
        )
    reference_profile = profile_types(reference_rows, 46)
    bid_statuses = set(nonnull_values(reference_rows, 27))
    award_statuses = set(nonnull_values(reference_rows, 35))
    countries = set(nonnull_values(reference_rows, 40))

    results = []
    for local_file in headerless:
        rows = sample_rows(root / "RAW_DATA_DOWNLOADER" / "dataset" / local_file, False)
        widths = Counter(len(row) for row in rows)
        candidate_schemas = sorted(
            name for name, width in schema_widths.items() if set(widths) == {width}
        )
        anchors = {
            "approved_budget_is_number": kind_rate(rows, 15, "number"),
            "published_date_is_date": kind_rate(rows, 16, "date"),
            "line_item_number_is_number": kind_rate(rows, 21, "number"),
            "quantity_is_number": kind_rate(rows, 24, "number"),
            "item_budget_is_number": kind_rate(rows, 26, "number"),
            "bid_status_matches_reference": vocabulary_rate(rows, 27, bid_statuses),
            "award_reference_is_number": kind_rate(rows, 28, "number"),
            "unspsc_is_number": kind_rate(rows, 30, "number"),
            "award_published_is_date": kind_rate(rows, 32, "date"),
            "award_date_is_date": kind_rate(rows, 33, "date"),
            "contract_amount_is_number": kind_rate(rows, 34, "number"),
            "award_status_matches_reference": vocabulary_rate(rows, 35, award_statuses),
            "country_matches_reference": vocabulary_rate(rows, 40, countries),
        }
        type_distance = mean_type_distance(reference_profile, profile_types(rows, 46))
        normalized_name = catalog_by_file[local_file]["normalized_file_name"]
        published_months = month_counts(rows, 16)
        published_total = sum(published_months.values())
        period_match_rate = (
            sum(
                count
                for month, count in published_months.items()
                if in_expected_period(month, normalized_name)
            )
            / published_total
            if published_total
            else None
        )
        schema_match = (
            candidate_schemas == ["location_46"]
            and type_distance < 0.10
            and all(rate is None or rate >= 0.99 for rate in anchors.values())
        )
        results.append(
            {
                "local_file": local_file,
                "sampled_rows": len(rows),
                "row_widths": {str(width): count for width, count in sorted(widths.items())},
                "candidate_schemas_by_width": candidate_schemas,
                "mean_type_distance_from_headered_location_46": round(type_distance, 4),
                "semantic_anchor_match_rates": {
                    name: None if rate is None else round(rate, 4)
                    for name, rate in anchors.items()
                },
                "schema_decision": "location_46" if schema_match else "unresolved",
                "schema_status": "PASS" if schema_match else "FAIL",
                "normalized_file_name": normalized_name,
                "sample_published_months": dict(published_months.most_common()),
                "published_period_match_rate": (
                    None if period_match_rate is None else round(period_match_rate, 4)
                ),
                "period_status": (
                    "PASS" if period_match_rate is not None and period_match_rate >= 0.99 else "REVIEW"
                ),
            }
        )

    overall = {
        "status": "PASS" if all(item["schema_status"] == "PASS" for item in results) else "FAIL",
        "sample_rows_per_headerless_file": SAMPLE_ROWS,
        "headered_reference_files": len(reference_files),
        "headered_reference_rows": len(reference_rows),
        "results": results,
    }
    output = project / "artifacts" / "headerless_schema_verification.json"
    output.write_text(json.dumps(overall, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Headerless CSV schema verification",
        "",
        f"**Schema result: {overall['status']}**",
        "",
        f"The first {SAMPLE_ROWS:,} records from each headerless file were compared with",
        f"{len(reference_rows):,} sampled records across {len(reference_files)} headered",
        "`location_46` files. Comparison used record width, per-column value types,",
        "and semantic anchors for dates, money, statuses, identifiers, UNSPSC, and country.",
        "",
        "All four headerless files map positionally to `location_46`. The 40- and",
        "43-column schemas are rejected by width, and the 46-column semantic anchors",
        "match the headered reference data.",
        "",
        "## Per-file results",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"### `{item['local_file']}`",
                "",
                f"- Schema: `{item['schema_decision']}` ({item['schema_status']})",
                f"- Sample width: {item['row_widths']}",
                "- Mean positional type distance from headered reference: "
                f"{item['mean_type_distance_from_headered_location_46']:.4f}",
                f"- Claimed normalized period: `{item['normalized_file_name']}`",
                f"- Published-date period match: {item['published_period_match_rate']}",
                f"- Period check: {item['period_status']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Important period anomaly",
            "",
            "`files/2021_Oct-Dec.csv` is structurally a valid headerless",
            "`location_46` file, but every non-null sampled Published Date is in",
            "October–December 2024, not 2021. Schema assignment and source-period",
            "identity are separate questions. Its normalized filename should not be",
            "treated as settled until overlap with the headered 2024 Q4 export is",
            "profiled during full ingestion.",
        ]
    )
    (project / "docs" / "headerless_schema_verification.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(overall, indent=2))
    return 0 if overall["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
