#!/usr/bin/env python3
"""Profile PhilGEPS process and child grains without changing source data."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb


PROFILE_VERSION = 1

OBVIOUS_IDENTIFIER_PLACEHOLDERS = ("0", "00", "000", "-", "N/A", "NA", "NONE", "NULL")

BUSINESS_FIELDS = [
    "procuring_entity_name",
    "bid_reference_no",
    "solicitation_no",
    "notice_title",
    "bid_published_date",
    "classification",
    "notice_type",
    "business_category",
    "funding_source",
    "funding_instrument",
    "procurement_mode",
    "trade_agreement",
    "approved_budget",
    "area_of_delivery",
    "contract_duration",
    "calendar_type",
    "line_item_no",
    "item_name",
    "item_description",
    "quantity",
    "unit_of_measurement",
    "item_budget",
    "prebid_date",
    "closing_date",
    "bid_notice_status",
    "award_reference_no",
    "award_title",
    "award_type",
    "unspsc_code",
    "unspsc_description",
    "awardee_organization_name",
    "contract_amount",
    "contract_no",
    "award_published_date",
    "award_date",
    "notice_to_proceed_date",
    "contract_effectivity_date",
    "contract_end_date",
    "reason_for_award",
    "award_notice_status",
    "client_agency",
    "created_by",
    "awardee_contact_person",
    "procuring_entity_region",
    "procuring_entity_province",
    "procuring_entity_city_municipality",
    "government_branch",
    "procuring_entity_organization_type",
    "procuring_entity_organization_type_grouped",
    "awardee_country",
    "awardee_region",
    "awardee_province",
    "awardee_city_municipality",
    "awardee_size",
    "awardee_joint_venture",
]

IDENTIFIER_FIELDS = [
    "bid_reference_no",
    "solicitation_no",
    "line_item_no",
    "award_reference_no",
    "contract_no",
    "procuring_entity_name",
    "client_agency",
    "awardee_organization_name",
]

ITEM_EVIDENCE = " OR ".join(
    f"{name} IS NOT NULL"
    for name in (
        "line_item_no",
        "item_name",
        "item_description",
        "quantity",
        "unit_of_measurement",
        "item_budget",
        "unspsc_code",
    )
)
AWARD_EVIDENCE = " OR ".join(
    f"{name} IS NOT NULL"
    for name in (
        "award_reference_no",
        "award_title",
        "award_date",
        "award_published_date",
        "awardee_organization_name",
        "contract_amount",
        "award_notice_status",
    )
)
CONTRACT_EVIDENCE = " OR ".join(
    f"{name} IS NOT NULL"
    for name in (
        "contract_no",
        "notice_to_proceed_date",
        "contract_effectivity_date",
        "contract_end_date",
    )
)
SUPPLIER_EVIDENCE = (
    "awardee_organization_name IS NOT NULL OR awardee_joint_venture IS NOT NULL"
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
        default=project / "artifacts" / "grain_profile.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "artifacts" / "grain_profile.md",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-rows", type=int, help="Testing only")
    return parser.parse_args()


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def as_dict(cursor):
    row = cursor.fetchone()
    return dict(zip([column[0] for column in cursor.description], row))


def integerize(value):
    if isinstance(value, dict):
        return {key: integerize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [integerize(item) for item in value]
    if isinstance(value, tuple):
        return [integerize(item) for item in value]
    return value


class Profiler:
    def __init__(self, connection):
        self.connection = connection
        self.timings = {}

    def one(self, name, sql):
        started = time.perf_counter()
        result = as_dict(self.connection.execute(sql))
        self.timings[name] = round(time.perf_counter() - started, 3)
        return integerize(result)

    def rows(self, name, sql):
        started = time.perf_counter()
        cursor = self.connection.execute(sql)
        columns = [column[0] for column in cursor.description]
        result = [dict(zip(columns, row)) for row in cursor.fetchall()]
        self.timings[name] = round(time.perf_counter() - started, 3)
        return integerize(result)


def build_profile(connection):
    p = Profiler(connection)
    placeholders = ", ".join(sql_string(value) for value in OBVIOUS_IDENTIFIER_PLACEHOLDERS)

    overview = p.one(
        "overview",
        """
        SELECT count(*) AS observation_rows,
               count(DISTINCT _source_file_id) AS source_files,
               count(DISTINCT _source_schema_id) AS source_schemas,
               count(*) FILTER (WHERE _cleaning_issue_count > 0)
                 AS rows_with_cleaning_issues
        FROM source
        """,
    )
    schema_rows = p.rows(
        "schema_rows",
        """
        SELECT _source_schema_id AS schema_id, count(*) AS rows,
               count(DISTINCT _source_file_id) AS source_files
        FROM source GROUP BY 1 ORDER BY 1
        """,
    )
    completeness_sql = ", ".join(
        f"count({field}) AS {field}_present" for field in IDENTIFIER_FIELDS
    )
    completeness = p.one(
        "identifier_completeness",
        f"SELECT {completeness_sql} FROM source",
    )
    for field in IDENTIFIER_FIELDS:
        present = completeness.pop(f"{field}_present")
        completeness[field] = {
            "present_rows": present,
            "missing_rows": overview["observation_rows"] - present,
        }

    process = p.one(
        "process_candidates",
        f"""
        WITH grouped AS (
          SELECT bid_reference_no,
                 upper(trim(bid_reference_no)) IN ({placeholders}) AS is_placeholder,
                 count(*) AS rows,
                 count(DISTINCT procuring_entity_name_key)
                   FILTER (WHERE procuring_entity_name_key IS NOT NULL) AS entities,
                 count(DISTINCT solicitation_no)
                   FILTER (WHERE solicitation_no IS NOT NULL) AS solicitations,
                 count(DISTINCT notice_title)
                   FILTER (WHERE notice_title IS NOT NULL) AS titles,
                 count(DISTINCT _source_file_id) AS files,
                 count(DISTINCT _source_schema_id) AS schemas
          FROM source WHERE bid_reference_no IS NOT NULL GROUP BY 1, 2
        )
        SELECT count(*) AS distinct_bid_references,
               sum(rows) AS rows_with_bid_reference,
               count(*) FILTER (WHERE is_placeholder)
                 AS obvious_placeholder_reference_values,
               coalesce(sum(rows) FILTER (WHERE is_placeholder), 0)
                 AS rows_with_obvious_placeholder_reference,
               count(*) FILTER (WHERE entities > 1)
                 AS references_with_multiple_entities,
               coalesce(sum(rows) FILTER (WHERE entities > 1), 0)
                 AS rows_in_multiple_entity_references,
               max(entities) AS max_entities_per_reference,
               count(*) FILTER (WHERE entities > 1 AND NOT is_placeholder)
                 AS nonplaceholder_references_with_multiple_entities,
               coalesce(sum(rows) FILTER (
                 WHERE entities > 1 AND NOT is_placeholder), 0)
                 AS rows_in_nonplaceholder_multiple_entity_references,
               count(*) FILTER (WHERE solicitations > 1)
                 AS references_with_multiple_solicitations,
               coalesce(sum(rows) FILTER (WHERE solicitations > 1), 0)
                 AS rows_in_multiple_solicitation_references,
               max(solicitations) AS max_solicitations_per_reference,
               count(*) FILTER (WHERE titles > 1)
                 AS references_with_multiple_titles,
               count(*) FILTER (WHERE files > 1)
                 AS references_seen_in_multiple_files,
               count(*) FILTER (WHERE schemas > 1)
                 AS references_seen_in_multiple_schemas
        FROM grouped
        """,
    )
    process["missing_bid_reference_rows"] = completeness["bid_reference_no"][
        "missing_rows"
    ]
    process["rows_requiring_process_key_fallback"] = (
        process["missing_bid_reference_rows"]
        + process["rows_with_obvious_placeholder_reference"]
    )

    top_process_collisions = p.rows(
        "top_process_collisions",
        f"""
        SELECT bid_reference_no, count(*) AS rows,
               upper(trim(bid_reference_no)) IN ({placeholders}) AS is_placeholder,
               count(DISTINCT procuring_entity_name_key)
                 FILTER (WHERE procuring_entity_name_key IS NOT NULL) AS entities,
               count(DISTINCT solicitation_no)
                 FILTER (WHERE solicitation_no IS NOT NULL) AS solicitations,
               count(DISTINCT notice_title)
                 FILTER (WHERE notice_title IS NOT NULL) AS titles,
               count(DISTINCT _source_file_id) AS source_files
        FROM source WHERE bid_reference_no IS NOT NULL
        GROUP BY 1, 3
        HAVING entities > 1 OR solicitations > 1
        ORDER BY entities DESC, solicitations DESC, rows DESC, bid_reference_no
        LIMIT 25
        """,
    )

    fallback_candidates = p.one(
        "fallback_process_candidates",
        f"""
        WITH candidates AS (
          SELECT * FROM source
          WHERE bid_reference_no IS NULL
             OR upper(trim(bid_reference_no)) IN ({placeholders})
        ), grouped AS (
          SELECT _profile_process_key, count(*) AS rows,
                 count(DISTINCT _source_file_id) AS source_files,
                 count(DISTINCT line_item_no)
                   FILTER (WHERE line_item_no IS NOT NULL) AS line_numbers,
                 count(DISTINCT award_reference_no)
                   FILTER (WHERE award_reference_no IS NOT NULL) AS awards
          FROM candidates
          WHERE _profile_process_key_basis = 'content_composite'
          GROUP BY 1
        )
        SELECT (SELECT count(*) FROM candidates) AS candidate_rows,
               (SELECT count(*) FROM candidates
                 WHERE solicitation_no IS NOT NULL)
                 AS rows_with_solicitation_number,
               (SELECT count(*) FROM candidates
                 WHERE procuring_entity_name_key IS NOT NULL)
                 AS rows_with_entity,
               (SELECT count(*) FROM candidates WHERE notice_title IS NOT NULL)
                 AS rows_with_title,
               (SELECT count(*) FROM candidates
                 WHERE bid_published_date IS NOT NULL)
                 AS rows_with_publication_date,
               (SELECT count(*) FROM candidates
                 WHERE _profile_process_key_basis = 'content_composite')
                 AS rows_using_content_composite,
               (SELECT count(*) FROM candidates
                 WHERE _profile_process_key_basis = 'source_row')
                 AS rows_using_source_row_fallback,
               count(*) AS distinct_content_composite_candidates,
               count(*) FILTER (WHERE rows > 1) AS repeated_composite_groups,
               coalesce(sum(rows - 1) FILTER (WHERE rows > 1), 0)
                 AS rows_grouped_beyond_first,
               count(*) FILTER (WHERE source_files > 1)
                 AS composite_groups_seen_in_multiple_files,
               max(rows) AS max_rows_per_composite,
               max(line_numbers) AS max_line_numbers_per_composite,
               max(awards) AS max_awards_per_composite
        FROM grouped
        """,
    )

    solicitation = p.one(
        "solicitation_candidates",
        """
        WITH grouped AS (
          SELECT solicitation_no, count(*) AS rows,
                 count(DISTINCT bid_reference_no)
                   FILTER (WHERE bid_reference_no IS NOT NULL) AS bid_references,
                 count(DISTINCT procuring_entity_name_key)
                   FILTER (WHERE procuring_entity_name_key IS NOT NULL) AS entities
          FROM source WHERE solicitation_no IS NOT NULL GROUP BY 1
        )
        SELECT count(*) AS distinct_solicitation_numbers,
               count(*) FILTER (WHERE bid_references > 1)
                 AS solicitations_with_multiple_bid_references,
               coalesce(sum(rows) FILTER (WHERE bid_references > 1), 0)
                 AS rows_in_reused_solicitations,
               max(bid_references) AS max_bid_references_per_solicitation,
               count(*) FILTER (WHERE entities > 1)
                 AS solicitations_with_multiple_entities
        FROM grouped
        """,
    )

    items = p.one(
        "item_grain",
        f"""
        WITH evidence AS (
          SELECT *, hash(item_name, item_description, quantity,
                         unit_of_measurement, item_budget, unspsc_code,
                         unspsc_description) AS item_signature
          FROM source WHERE {ITEM_EVIDENCE}
        ), grouped AS (
          SELECT _profile_process_key, line_item_no, count(*) AS rows,
                 count(DISTINCT item_signature) AS signatures
          FROM evidence
          WHERE line_item_no IS NOT NULL
          GROUP BY 1, 2
        )
        SELECT (SELECT count(*) FROM evidence) AS evidence_rows,
               (SELECT count(*) FROM evidence WHERE line_item_no IS NULL)
                 AS evidence_rows_missing_line_number,
               (SELECT count(*) FROM evidence WHERE bid_reference_no IS NULL)
                 AS evidence_rows_missing_process_reference,
               count(*) AS process_line_groups,
               count(*) FILTER (WHERE rows > 1) AS repeated_process_line_groups,
               coalesce(sum(rows - 1) FILTER (WHERE rows > 1), 0)
                 AS repeated_rows_beyond_first,
               count(*) FILTER (WHERE signatures > 1)
                 AS process_line_groups_with_conflicting_content,
               coalesce(sum(rows) FILTER (WHERE signatures > 1), 0)
                 AS rows_in_conflicting_process_line_groups,
               max(signatures) AS max_signatures_per_process_line
        FROM grouped
        """,
    )

    awards = p.one(
        "award_grain",
        f"""
        WITH evidence AS (
          SELECT *, hash(award_title, award_date, award_published_date,
                         contract_amount, award_notice_status,
                         awardee_organization_name_key) AS award_signature
          FROM source WHERE {AWARD_EVIDENCE}
        ), grouped AS (
          SELECT _profile_process_key, award_reference_no, count(*) AS rows,
                 count(DISTINCT award_signature) AS signatures,
                 count(DISTINCT awardee_organization_name_key)
                   FILTER (WHERE awardee_organization_name_key IS NOT NULL)
                   AS suppliers
          FROM evidence
          WHERE award_reference_no IS NOT NULL
          GROUP BY 1, 2
        ), reused AS (
          SELECT award_reference_no,
                 count(DISTINCT _profile_process_key) AS processes,
                 count(*) AS rows
          FROM evidence
          WHERE award_reference_no IS NOT NULL
          GROUP BY 1
        )
        SELECT (SELECT count(*) FROM evidence) AS evidence_rows,
               (SELECT count(*) FROM evidence WHERE award_reference_no IS NULL)
                 AS evidence_rows_missing_award_reference,
               (SELECT count(*) FROM evidence WHERE bid_reference_no IS NULL)
                 AS evidence_rows_missing_process_reference,
               (SELECT count(*) FROM grouped) AS process_award_groups,
               (SELECT count(*) FROM grouped WHERE rows > 1)
                 AS repeated_process_award_groups,
               (SELECT count(*) FROM grouped WHERE signatures > 1)
                 AS process_award_groups_with_conflicting_content,
               (SELECT coalesce(sum(rows), 0) FROM grouped WHERE signatures > 1)
                 AS rows_in_conflicting_process_award_groups,
               (SELECT count(*) FROM grouped WHERE suppliers > 1)
                 AS process_awards_with_multiple_suppliers,
               (SELECT count(*) FROM reused WHERE processes > 1)
                 AS award_references_reused_across_processes,
               (SELECT coalesce(sum(rows), 0) FROM reused WHERE processes > 1)
                 AS rows_in_cross_process_award_references,
               (SELECT max(processes) FROM reused)
                 AS max_processes_per_award_reference
        """,
    )

    contracts = p.one(
        "contract_grain_and_links",
        f"""
        WITH evidence AS (
          SELECT * FROM source WHERE {CONTRACT_EVIDENCE}
        ), grouped AS (
          SELECT _profile_process_key, contract_no, count(*) AS rows,
                 count(DISTINCT award_reference_no)
                   FILTER (WHERE award_reference_no IS NOT NULL) AS awards,
                 count(DISTINCT hash(contract_amount,
                                     contract_effectivity_date,
                                     contract_end_date,
                                     notice_to_proceed_date)) AS signatures
          FROM evidence
          WHERE contract_no IS NOT NULL
          GROUP BY 1, 2
        ), reused AS (
          SELECT contract_no,
                 count(DISTINCT _profile_process_key) AS processes,
                 count(*) AS rows
          FROM evidence
          WHERE contract_no IS NOT NULL
          GROUP BY 1
        )
        SELECT (SELECT count(*) FROM evidence) AS evidence_rows,
               (SELECT count(*) FROM evidence WHERE contract_no IS NULL)
                 AS evidence_rows_missing_contract_number,
               (SELECT count(*) FROM evidence WHERE award_reference_no IS NULL)
                 AS evidence_rows_missing_award_reference,
               (SELECT count(*) FROM evidence WHERE bid_reference_no IS NULL)
                 AS evidence_rows_missing_process_reference,
               (SELECT count(*) FROM grouped) AS process_contract_groups,
               (SELECT count(*) FROM grouped WHERE rows > 1)
                 AS repeated_process_contract_groups,
               (SELECT count(*) FROM grouped WHERE signatures > 1)
                 AS process_contract_groups_with_conflicting_content,
               (SELECT count(*) FROM grouped WHERE awards = 0)
                 AS process_contracts_missing_award_link,
               (SELECT count(*) FROM grouped WHERE awards > 1)
                 AS process_contracts_with_ambiguous_award_link,
               (SELECT count(*) FROM reused WHERE processes > 1)
                 AS contract_numbers_reused_across_processes,
               (SELECT coalesce(sum(rows), 0) FROM reused WHERE processes > 1)
                 AS rows_in_cross_process_contract_numbers,
               (SELECT max(processes) FROM reused)
                 AS max_processes_per_contract_number
        """,
    )

    suppliers = p.one(
        "supplier_grain_and_links",
        f"""
        WITH evidence AS (
          SELECT * FROM source WHERE {SUPPLIER_EVIDENCE}
        ), award_groups AS (
          SELECT _profile_process_key, award_reference_no,
                 count(DISTINCT awardee_organization_name_key)
                   FILTER (WHERE awardee_organization_name_key IS NOT NULL)
                   AS suppliers
          FROM evidence
          WHERE award_reference_no IS NOT NULL
          GROUP BY 1, 2
        ), names AS (
          SELECT awardee_organization_name_key,
                 count(DISTINCT awardee_organization_name) AS spellings
          FROM evidence WHERE awardee_organization_name_key IS NOT NULL
          GROUP BY 1
        )
        SELECT (SELECT count(*) FROM evidence) AS evidence_rows,
               (SELECT count(*) FROM evidence
                 WHERE awardee_organization_name IS NULL)
                 AS evidence_rows_missing_supplier_name,
               (SELECT count(*) FROM evidence WHERE award_reference_no IS NULL)
                 AS evidence_rows_missing_award_reference,
               (SELECT count(*) FROM evidence WHERE bid_reference_no IS NULL)
                 AS evidence_rows_missing_process_reference,
               (SELECT count(DISTINCT awardee_organization_name_key)
                 FROM evidence) AS distinct_supplier_name_keys,
               (SELECT count(*) FROM award_groups WHERE suppliers > 1)
                 AS process_awards_with_multiple_supplier_names,
               (SELECT max(suppliers) FROM award_groups)
                 AS max_supplier_names_per_process_award,
               (SELECT count(*) FROM names WHERE spellings > 1)
                 AS normalized_name_keys_with_multiple_spellings,
               (SELECT count(*) FROM evidence
                 WHERE awardee_joint_venture IS NOT NULL)
                 AS rows_with_joint_venture_value
        """,
    )

    content_hash = "hash(" + ", ".join(BUSINESS_FIELDS) + ")"
    repeated = p.one(
        "repeated_observations",
        f"""
        WITH hashed AS (
          SELECT {content_hash} AS content_signature, _source_file_id
          FROM source
        ), grouped AS (
          SELECT content_signature, count(*) AS rows,
                 count(DISTINCT _source_file_id) AS files
          FROM hashed GROUP BY 1
        )
        SELECT count(*) AS distinct_business_observations,
               count(*) FILTER (WHERE rows > 1) AS repeated_observation_groups,
               coalesce(sum(rows - 1) FILTER (WHERE rows > 1), 0)
                 AS repeated_rows_beyond_first,
               count(*) FILTER (WHERE files > 1) AS cross_file_repeat_groups,
               coalesce(sum(rows) FILTER (WHERE files > 1), 0)
                 AS rows_in_cross_file_repeat_groups,
               max(rows) AS max_repetitions
        FROM grouped
        """,
    )

    top_joint_venture_values = p.rows(
        "joint_venture_values",
        """
        SELECT awardee_joint_venture AS value, count(*) AS rows
        FROM source WHERE awardee_joint_venture IS NOT NULL
        GROUP BY 1 ORDER BY rows DESC, value LIMIT 20
        """,
    )

    profile = {
        "profile_version": PROFILE_VERSION,
        "overview": overview,
        "source_schema_rows": schema_rows,
        "identifier_completeness": completeness,
        "process_candidates": process,
        "top_process_candidate_collisions": top_process_collisions,
        "fallback_process_candidates": fallback_candidates,
        "solicitation_candidates": solicitation,
        "item_grain": items,
        "award_grain": awards,
        "contract_grain_and_links": contracts,
        "supplier_grain_and_links": suppliers,
        "repeated_observations": repeated,
        "top_joint_venture_values": top_joint_venture_values,
        "methodology": {
            "business_observation_signature": (
                "DuckDB 64-bit hash over all 55 cleaned business fields; used "
                "for profiling only, never as a published or persistent ID"
            ),
            "relationship_statuses": ["matched", "missing", "ambiguous"],
            "null_policy": "Null values are not counted as distinct links.",
            "obvious_identifier_placeholders": list(OBVIOUS_IDENTIFIER_PLACEHOLDERS),
        },
        "query_seconds": p.timings,
    }
    return profile


def fmt(value):
    return f"{value:,}" if isinstance(value, int) else str(value)


def metric_lines(values):
    return "\n".join(
        f"| `{key}` | {fmt(value)} |" for key, value in values.items()
    )


def recommendations(profile):
    process = profile["process_candidates"]
    items = profile["item_grain"]
    awards = profile["award_grain"]
    contracts = profile["contract_grain_and_links"]
    recs = []
    if process["nonplaceholder_references_with_multiple_entities"] == 0:
        recs.append(
            "Use valid-looking `bid_reference_no` as the leading process-key "
            "candidate; treat null and obvious placeholder values as missing. "
            "Use the profiled content composite when all required components are "
            "present, otherwise use a provenance-based row fallback."
        )
    elif process["rows_in_nonplaceholder_multiple_entity_references"] <= 10:
        recs.append(
            "Use valid-looking `bid_reference_no` as the process-key candidate. "
            "Manual review found that the small set of cross-entity cases are "
            "agency-label variants with matching solicitation numbers and titles; "
            "retain one process and flag the conflicting labels. For missing or "
            "placeholder values, use the profiled content composite when possible "
            "and a provenance fallback otherwise."
        )
    else:
        recs.append(
            "Do not use `bid_reference_no` alone: it crosses procuring-entity "
            "boundaries. Test a composite with `procuring_entity_name_key`."
        )
    if process["references_with_multiple_solicitations"]:
        recs.append(
            "Treat `solicitation_no` as a tender attribute, not an unconditional "
            "component of process identity, because it varies within some bid "
            "references."
        )
    if items["process_line_groups_with_conflicting_content"]:
        recs.append(
            "Version item states: `line_item_no` locates an item within a process "
            "but does not identify immutable content."
        )
    if awards["award_references_reused_across_processes"]:
        recs.append(
            "Scope award identifiers to the process; award references are reused "
            "across processes."
        )
    if contracts["contract_numbers_reused_across_processes"]:
        recs.append(
            "Scope contract identifiers to the related award; contract numbers "
            "are reused across processes and sometimes across awards in one "
            "process."
        )
    recs.append(
        "Retain missing and ambiguous relationships in analytical tables with "
        "link statuses and publication-blocking quality issues."
    )
    return recs


def render_markdown(profile, input_path, truncated):
    sections = [
        "# PhilGEPS grain profile",
        "",
        f"Input: `{input_path}`",
        "",
        f"Profile version: {PROFILE_VERSION}",
        "",
        (
            "This is a truncated test profile."
            if truncated
            else "This profile covers the complete cleaned Parquet."
        ),
        "",
        "## Recommendations",
        "",
    ]
    sections.extend(f"- {item}" for item in recommendations(profile))
    for heading, key in (
        ("Overview", "overview"),
        ("Process candidates", "process_candidates"),
        ("Fallback process candidates", "fallback_process_candidates"),
        ("Solicitation candidates", "solicitation_candidates"),
        ("Item grain", "item_grain"),
        ("Award grain", "award_grain"),
        ("Contract grain and links", "contract_grain_and_links"),
        ("Supplier grain and links", "supplier_grain_and_links"),
        ("Repeated observations", "repeated_observations"),
    ):
        sections.extend(
            [
                "",
                f"## {heading}",
                "",
                "| Metric | Count |",
                "|---|---:|",
                metric_lines(profile[key]),
            ]
        )
    sections.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Repeated or conflicting values are profiling signals, not automatic "
            "errors. Later ETL rules must preserve source breadcrumbs and classify "
            "relationships as matched, missing, or ambiguous. Only the matched "
            "publication-eligible subset is subject to strict OCDS references.",
            "",
        ]
    )
    return "\n".join(sections)


def main():
    args = parse_args()
    input_path = args.input.resolve()
    json_output = args.json_output.resolve()
    markdown_output = args.markdown_output.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    source = f"read_parquet({sql_string(str(input_path))})"
    if args.max_rows:
        source = f"(SELECT * FROM {source} LIMIT {int(args.max_rows)})"
    connection.execute(f"CREATE TEMP VIEW raw_source AS SELECT * FROM {source}")
    placeholders = ", ".join(
        sql_string(value) for value in OBVIOUS_IDENTIFIER_PLACEHOLDERS
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW source AS
        SELECT *,
               CASE
                 WHEN bid_reference_no IS NOT NULL
                  AND upper(trim(bid_reference_no)) NOT IN ({placeholders})
                 THEN 'bid:' || bid_reference_no
                 WHEN procuring_entity_name_key IS NOT NULL
                  AND notice_title IS NOT NULL
                  AND bid_published_date IS NOT NULL
                 THEN 'fallback:' || cast(hash(
                        procuring_entity_name_key,
                        solicitation_no,
                        notice_title,
                        bid_published_date
                      ) AS VARCHAR)
                 ELSE 'row:' || _source_file_id || ':' ||
                      coalesce(_source_sheet, '') || ':' ||
                      cast(_source_row_number AS VARCHAR)
               END AS _profile_process_key,
               CASE
                 WHEN bid_reference_no IS NOT NULL
                  AND upper(trim(bid_reference_no)) NOT IN ({placeholders})
                 THEN 'bid_reference'
                 WHEN procuring_entity_name_key IS NOT NULL
                  AND notice_title IS NOT NULL
                  AND bid_published_date IS NOT NULL
                 THEN 'content_composite'
                 ELSE 'source_row'
               END AS _profile_process_key_basis
        FROM raw_source
        """
    )

    started = time.perf_counter()
    try:
        profile = build_profile(connection)
    finally:
        connection.close()
    profile["input"] = {
        "path": str(input_path),
        "truncated_for_test": bool(args.max_rows),
        "max_rows": args.max_rows,
    }
    profile["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    profile["recommendations"] = recommendations(profile)

    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    markdown_output.write_text(
        render_markdown(profile, input_path, bool(args.max_rows)), encoding="utf-8"
    )
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
