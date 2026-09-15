#!/usr/bin/env python3
"""Prototype deterministic PhilGEPS/OCDS entity IDs and report collisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import duckdb


ITEM_FIELDS = [
    "item_name",
    "item_description",
    "quantity",
    "unit_of_measurement",
    "item_budget",
    "unspsc_code",
    "unspsc_description",
]
AWARD_FIELDS = [
    "award_title",
    "award_date",
    "award_published_date",
    "awardee_organization_name_key",
    "contract_amount",
]
CONTRACT_FIELDS = [
    "contract_amount",
    "notice_to_proceed_date",
    "contract_effectivity_date",
    "contract_end_date",
]

OBSERVATION_PROJECTION = [
    "_source_file_id",
    "_source_sheet",
    "_source_row_number",
    "bid_reference_no",
    "procuring_entity_name",
    "procuring_entity_name_key",
    "solicitation_no",
    "notice_title",
    "bid_published_date",
    "line_item_no",
    *ITEM_FIELDS,
    "award_reference_no",
    *AWARD_FIELDS,
    "award_notice_status",
    "contract_no",
    *CONTRACT_FIELDS,
    "client_agency",
    "client_agency_key",
    "awardee_organization_name",
]
# Preserve declaration order while removing fields shared by entity definitions.
OBSERVATION_PROJECTION = list(dict.fromkeys(OBSERVATION_PROJECTION))


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
        "--rules",
        type=Path,
        default=project / "config" / "identity_rules.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=project / "artifacts" / "id_profile.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "artifacts" / "id_profile.md",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-rows", type=int, help="Testing only")
    return parser.parse_args()


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def sql_timestamp(column, timestamp_format):
    return f"strftime({column}, {sql_string(timestamp_format)})"


def json_payload(values):
    return "to_json(list_value(" + ", ".join(values) + "))"


def prefixed_id(prefix, payload):
    return f"{sql_string(prefix + '_')} || sha256({payload})"


def evidence(fields):
    return " OR ".join(f"{field} IS NOT NULL" for field in fields)


def as_dict(cursor):
    row = cursor.fetchone()
    return dict(zip([column[0] for column in cursor.description], row))


class Queries:
    def __init__(self, connection):
        self.connection = connection
        self.seconds = {}

    def one(self, name, sql):
        started = time.perf_counter()
        result = as_dict(self.connection.execute(sql))
        self.seconds[name] = round(time.perf_counter() - started, 3)
        return result

    def rows(self, name, sql):
        started = time.perf_counter()
        cursor = self.connection.execute(sql)
        columns = [column[0] for column in cursor.description]
        result = [dict(zip(columns, row)) for row in cursor.fetchall()]
        self.seconds[name] = round(time.perf_counter() - started, 3)
        return result


def create_views(connection, source_sql, rules, materialize_source=False):
    version = str(rules["identity_rules_version"])
    timestamp_format = rules["canonical_timestamp_format"]
    placeholders = rules["process"]["rules"][0][
        "excluded_values_case_insensitive"
    ]
    placeholders_sql = ", ".join(sql_string(value) for value in placeholders)
    valid_bid = (
        "bid_reference_no IS NOT NULL AND "
        f"upper(trim(bid_reference_no)) NOT IN ({placeholders_sql})"
    )
    composite = (
        "procuring_entity_name_key IS NOT NULL AND notice_title IS NOT NULL "
        "AND bid_published_date IS NOT NULL"
    )
    process_basis = (
        f"CASE WHEN {valid_bid} THEN 'bid_reference' "
        f"WHEN {composite} THEN 'inferred_content_composite' "
        "ELSE 'source_row' END"
    )
    process_payload = f"""
      CASE
        WHEN {valid_bid} THEN {json_payload([
            sql_string(version), sql_string('process'),
            sql_string('bid_reference'), 'bid_reference_no'
        ])}
        WHEN {composite} THEN {json_payload([
            sql_string(version), sql_string('process'),
            sql_string('inferred_content_composite'),
            'procuring_entity_name_key', 'solicitation_no', 'notice_title',
            sql_timestamp('bid_published_date', timestamp_format)
        ])}
        ELSE {json_payload([
            sql_string(version), sql_string('process'), sql_string('source_row'),
            '_source_file_id', '_source_sheet',
            'cast(_source_row_number AS VARCHAR)'
        ])}
      END
    """
    process_prefix = rules["process"]["id_prefix"]
    source_kind = "TABLE" if materialize_source else "VIEW"
    connection.execute(
        f"CREATE TEMP {source_kind} raw_source AS SELECT * FROM {source_sql}"
    )
    print("identity prototype: source ready", flush=True)
    connection.execute(
        f"""
        CREATE TEMP VIEW process_payloads AS
        SELECT *, {process_basis} AS process_identity_basis,
               {process_payload} AS process_identity_payload
        FROM raw_source
        """
    )
    print("identity prototype: process payload view ready", flush=True)
    projected = ", ".join(OBSERVATION_PROJECTION)
    connection.execute(
        f"""
        CREATE TEMP TABLE observations AS
        SELECT {projected}, process_identity_basis,
               hash(process_identity_payload)
                 AS process_identity_payload_fingerprint,
               {prefixed_id(process_prefix, 'process_identity_payload')}
                 AS process_id,
               _source_file_id || ':' || cast(_source_row_number AS VARCHAR)
                 AS source_breadcrumb
        FROM process_payloads
        """
    )
    print("identity prototype: observations ready", flush=True)

    item_content = json_payload(
        [
            sql_string(version),
            sql_string("item_content"),
            *[
                sql_timestamp(field, timestamp_format)
                if field.endswith("_date")
                else f"cast({field} AS VARCHAR)"
                for field in ITEM_FIELDS
            ],
        ]
    )
    item_basis = (
        "CASE WHEN line_item_no IS NOT NULL THEN 'line_item_no' "
        "ELSE 'item_content_composite' END"
    )
    item_payload = f"""
      CASE WHEN line_item_no IS NOT NULL THEN {json_payload([
          sql_string(version), sql_string('item'), sql_string('line_item_no'),
          'process_id', 'cast(line_item_no AS VARCHAR)'
      ])}
      ELSE {json_payload([
          sql_string(version), sql_string('item'),
          sql_string('item_content_composite'), 'process_id',
          f'cast({item_content} AS VARCHAR)'
      ])} END
    """
    connection.execute(
        f"""
        CREATE TEMP VIEW item_payloads AS
        SELECT *, {item_basis} AS item_identity_basis,
               {item_payload} AS item_identity_payload,
               hash({', '.join(ITEM_FIELDS)}) AS item_content_signature
        FROM observations WHERE {evidence(ITEM_FIELDS + ['line_item_no'])}
        """
    )
    print("identity prototype: item payload view ready", flush=True)
    connection.execute(
        f"""
        CREATE TEMP TABLE item_candidates AS
        SELECT item_identity_basis,
               hash(item_identity_payload) AS item_identity_payload_fingerprint,
               item_content_signature, min(source_breadcrumb) AS source_breadcrumb,
               count(*) AS observation_count,
               {prefixed_id(rules['item']['id_prefix'], 'item_identity_payload')}
                 AS item_id
        FROM item_payloads
        GROUP BY item_identity_basis, item_identity_payload,
                 item_content_signature
        """
    )
    print("identity prototype: item candidates ready", flush=True)

    award_content_values = [
        sql_timestamp(field, timestamp_format)
        if field.endswith("_date")
        else f"cast({field} AS VARCHAR)"
        for field in AWARD_FIELDS
    ]
    award_basis = (
        "CASE WHEN award_reference_no IS NOT NULL THEN 'award_reference_no' "
        "ELSE 'award_content_composite' END"
    )
    award_payload = f"""
      CASE WHEN award_reference_no IS NOT NULL THEN {json_payload([
          sql_string(version), sql_string('award'),
          sql_string('award_reference_no'), 'process_id', 'award_reference_no'
      ])}
      ELSE {json_payload([
          sql_string(version), sql_string('award'),
          sql_string('award_content_composite'), 'process_id',
          *award_content_values
      ])} END
    """
    connection.execute(
        f"""
        CREATE TEMP VIEW award_payloads AS
        SELECT *, {award_basis} AS award_identity_basis,
               {award_payload} AS award_identity_payload,
               hash({', '.join(AWARD_FIELDS)}) AS award_content_signature
        FROM observations
        WHERE {evidence(['award_reference_no'] + AWARD_FIELDS + ['award_notice_status'])}
        """
    )
    print("identity prototype: award payload view ready", flush=True)
    connection.execute(
        f"""
        CREATE TEMP TABLE award_candidates AS
        SELECT award_identity_basis,
               hash(award_identity_payload) AS award_identity_payload_fingerprint,
               award_content_signature, min(source_breadcrumb) AS source_breadcrumb,
               count(*) AS observation_count,
               {prefixed_id(rules['award']['id_prefix'], 'award_identity_payload')}
                 AS award_id
        FROM award_payloads
        GROUP BY award_identity_basis, award_identity_payload,
                 award_content_signature
        """
    )
    print("identity prototype: award candidates ready", flush=True)

    contract_evidence = evidence(
        [
            "contract_no",
            "notice_to_proceed_date",
            "contract_effectivity_date",
            "contract_end_date",
        ]
    )
    contract_values = [
        sql_timestamp(field, timestamp_format)
        if field.endswith("_date")
        else f"cast({field} AS VARCHAR)"
        for field in CONTRACT_FIELDS
    ]
    contract_basis = """
      CASE
        WHEN award_reference_no IS NULL THEN 'missing_award_source_row'
        WHEN contract_no IS NOT NULL THEN 'award_scoped_contract_no'
        ELSE 'award_scoped_content_composite'
      END
    """
    contract_payload = f"""
      CASE
        WHEN award_reference_no IS NULL THEN {json_payload([
            sql_string(version), sql_string('contract'),
            sql_string('missing_award_source_row'), 'process_id',
            '_source_file_id', '_source_sheet',
            'cast(_source_row_number AS VARCHAR)'
        ])}
        WHEN contract_no IS NOT NULL THEN {json_payload([
            sql_string(version), sql_string('contract'),
            sql_string('award_scoped_contract_no'), 'award_id', 'contract_no'
        ])}
        ELSE {json_payload([
            sql_string(version), sql_string('contract'),
            sql_string('award_scoped_content_composite'), 'award_id',
            *contract_values
        ])}
      END
    """
    contract_award_payload = json_payload(
        [
            sql_string(version),
            sql_string("award"),
            sql_string("award_reference_no"),
            "process_id",
            "award_reference_no",
        ]
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW contract_scopes AS
        SELECT *,
               CASE WHEN award_reference_no IS NOT NULL
                    THEN {prefixed_id(rules['award']['id_prefix'], contract_award_payload)}
               END AS award_id
        FROM observations WHERE {contract_evidence}
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW contract_payloads AS
        SELECT *, {contract_basis} AS contract_identity_basis,
               CASE WHEN award_reference_no IS NULL
                    THEN 'missing' ELSE 'matched' END AS award_link_status,
               {contract_payload} AS contract_identity_payload,
               hash({', '.join(CONTRACT_FIELDS)}) AS contract_content_signature
        FROM contract_scopes
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE contract_candidates AS
        SELECT contract_identity_basis, award_link_status, award_id,
               hash(contract_identity_payload)
                 AS contract_identity_payload_fingerprint,
               contract_content_signature,
               min(source_breadcrumb) AS source_breadcrumb,
               count(*) AS observation_count,
               {prefixed_id(rules['contract']['id_prefix'], 'contract_identity_payload')}
                 AS contract_id
        FROM contract_payloads
        GROUP BY contract_identity_basis, award_link_status, award_id,
                 contract_identity_payload, contract_content_signature
        """
    )
    print("identity prototype: contract candidates ready", flush=True)

    party_prefix = rules["party"]["id_prefix"]
    connection.execute(
        """
        CREATE TEMP VIEW raw_party_mentions AS
        SELECT process_id, 'procuringEntity' AS role,
               procuring_entity_name AS party_name,
               procuring_entity_name_key AS party_name_key,
               source_breadcrumb
        FROM observations WHERE procuring_entity_name_key IS NOT NULL
        UNION ALL
        SELECT process_id, 'buyer', client_agency, client_agency_key,
               source_breadcrumb
        FROM observations WHERE client_agency_key IS NOT NULL
        UNION ALL
        SELECT process_id, 'supplier', awardee_organization_name,
               awardee_organization_name_key, source_breadcrumb
        FROM observations WHERE awardee_organization_name_key IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE party_mentions AS
        SELECT process_id, role, party_name, party_name_key,
               min(source_breadcrumb) AS source_breadcrumb,
               count(*) AS observation_count
        FROM raw_party_mentions
        GROUP BY process_id, role, party_name, party_name_key
        """
    )
    print("identity prototype: party mentions ready", flush=True)
    party_payload = json_payload(
        [
            sql_string(version),
            sql_string("party"),
            sql_string("normalized_name_mention"),
            "process_id",
            "party_name_key",
        ]
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE party_candidates AS
        SELECT role, party_name, source_breadcrumb, observation_count,
               hash({party_payload}) AS party_identity_payload_fingerprint,
               {prefixed_id(party_prefix, party_payload)} AS party_id
        FROM party_mentions
        """
    )
    print("identity prototype: party candidates ready", flush=True)


def entity_profile(
    q, name, view, id_column, payload_column, basis_column,
    content_column=None, weight_column=None
):
    weight = weight_column or "1"
    grouped_extra = (
        f", count(DISTINCT {content_column}) AS content_versions"
        if content_column
        else ""
    )
    summary = q.one(
        f"{name}_summary",
        f"""
        WITH grouped AS (
          SELECT {id_column}, sum({weight}) AS observation_rows,
                 count(DISTINCT {payload_column}) AS payloads
                 {grouped_extra}
          FROM {view} GROUP BY 1
        )
        SELECT (SELECT sum({weight}) FROM {view}) AS observation_rows,
               count(*) AS distinct_ids,
               count(*) FILTER (WHERE payloads > 1) AS hash_collision_ids,
               coalesce(sum(observation_rows) FILTER (WHERE payloads > 1), 0)
                 AS rows_in_hash_collisions
               {', count(*) FILTER (WHERE content_versions > 1) AS ids_with_multiple_content_versions, max(content_versions) AS max_content_versions_per_id' if content_column else ''}
        FROM grouped
        """,
    )
    summary["identity_bases"] = q.rows(
        f"{name}_bases",
        f"""
        SELECT {basis_column} AS basis, sum({weight}) AS observation_rows,
               count(DISTINCT {id_column}) AS distinct_ids
        FROM {view} GROUP BY 1 ORDER BY 1
        """,
    )
    return summary


def build_profile(connection, rules):
    q = Queries(connection)
    overview = q.one(
        "overview",
        """
        SELECT count(*) AS observation_rows,
               count(DISTINCT _source_file_id) AS source_files,
               count(DISTINCT (_source_file_id, _source_row_number))
                 AS distinct_source_observation_keys,
               count(*) - count(DISTINCT (_source_file_id, _source_row_number))
                 AS duplicate_source_observation_keys
        FROM observations
        """,
    )
    processes = entity_profile(
        q,
        "process",
        "observations",
        "process_id",
        "process_identity_payload_fingerprint",
        "process_identity_basis",
    )
    processes.update(
        q.one(
            "process_conflicts",
            """
            WITH grouped AS (
              SELECT process_id,
                     count(DISTINCT procuring_entity_name_key)
                       FILTER (WHERE procuring_entity_name_key IS NOT NULL)
                       AS entity_names,
                     count(DISTINCT solicitation_no)
                       FILTER (WHERE solicitation_no IS NOT NULL) AS solicitations,
                     count(DISTINCT notice_title)
                       FILTER (WHERE notice_title IS NOT NULL) AS titles
              FROM observations GROUP BY 1
            )
            SELECT count(*) FILTER (WHERE entity_names > 1)
                     AS ids_with_multiple_entity_names,
                   count(*) FILTER (WHERE solicitations > 1)
                     AS ids_with_multiple_solicitations,
                   count(*) FILTER (WHERE titles > 1)
                     AS ids_with_multiple_titles,
                   max(entity_names) AS max_entity_names_per_id,
                   max(solicitations) AS max_solicitations_per_id,
                   max(titles) AS max_titles_per_id
            FROM grouped
            """,
        )
    )
    print("identity prototype: process profile ready", flush=True)
    items = entity_profile(
        q,
        "item",
        "item_candidates",
        "item_id",
        "item_identity_payload_fingerprint",
        "item_identity_basis",
        "item_content_signature",
        "observation_count",
    )
    print("identity prototype: item profile ready", flush=True)
    awards = entity_profile(
        q,
        "award",
        "award_candidates",
        "award_id",
        "award_identity_payload_fingerprint",
        "award_identity_basis",
        "award_content_signature",
        "observation_count",
    )
    print("identity prototype: award profile ready", flush=True)
    contracts = entity_profile(
        q,
        "contract",
        "contract_candidates",
        "contract_id",
        "contract_identity_payload_fingerprint",
        "contract_identity_basis",
        "contract_content_signature",
        "observation_count",
    )
    contracts["award_links"] = q.rows(
        "contract_links",
        """
        SELECT award_link_status AS status,
               sum(observation_count) AS observation_rows,
               count(DISTINCT contract_id) AS distinct_contract_ids
        FROM contract_candidates GROUP BY 1 ORDER BY 1
        """,
    )
    contracts.update(
        q.one(
            "contract_award_scope",
            """
            WITH grouped AS (
              SELECT contract_id,
                     count(DISTINCT award_id)
                       FILTER (WHERE award_id IS NOT NULL) AS awards
              FROM contract_candidates GROUP BY 1
            )
            SELECT count(*) FILTER (WHERE awards > 1)
                     AS contract_ids_crossing_awards,
                   max(awards) AS max_awards_per_contract_id
            FROM grouped
            """,
        )
    )
    print("identity prototype: contract profile ready", flush=True)
    parties = entity_profile(
        q,
        "party",
        "party_candidates",
        "party_id",
        "party_identity_payload_fingerprint",
        "role",
        weight_column="observation_count",
    )
    parties["role_mentions"] = q.rows(
        "party_roles",
        """
        SELECT role, sum(observation_count) AS observation_rows,
               count(DISTINCT party_id) AS distinct_party_ids
        FROM party_candidates GROUP BY 1 ORDER BY 1
        """,
    )
    parties.update(
        q.one(
            "party_name_variants",
            """
            WITH grouped AS (
              SELECT party_id, count(DISTINCT party_name) AS spellings
              FROM party_candidates GROUP BY 1
            )
            SELECT count(*) FILTER (WHERE spellings > 1)
                     AS party_ids_with_multiple_source_spellings,
                   max(spellings) AS max_source_spellings_per_party_id
            FROM grouped
            """,
        )
    )
    print("identity prototype: party profile ready", flush=True)

    examples = {}
    for entity_name, view, basis, id_column, payload_column in (
        ("process", "observations", "process_identity_basis", "process_id", "process_identity_payload_fingerprint"),
        ("item", "item_candidates", "item_identity_basis", "item_id", "item_identity_payload_fingerprint"),
        ("award", "award_candidates", "award_identity_basis", "award_id", "award_identity_payload_fingerprint"),
        ("contract", "contract_candidates", "contract_identity_basis", "contract_id", "contract_identity_payload_fingerprint"),
    ):
        examples[entity_name] = q.rows(
            f"{entity_name}_examples",
            f"""
            SELECT {basis} AS basis,
                   arg_min({id_column}, source_breadcrumb) AS id,
                   arg_min({payload_column}, source_breadcrumb)
                     AS payload_fingerprint,
                   min(source_breadcrumb) AS source_breadcrumb
            FROM {view} GROUP BY 1
            ORDER BY basis
            """,
        )
    examples["party"] = q.rows(
        "party_examples",
        """
        SELECT role AS basis, arg_min(party_id, source_breadcrumb) AS id,
               arg_min(party_identity_payload_fingerprint, source_breadcrumb)
                 AS payload_fingerprint,
               min(source_breadcrumb) AS source_breadcrumb
        FROM party_candidates GROUP BY 1
        ORDER BY role
        """,
    )

    profile = {
        "identity_rules_version": rules["identity_rules_version"],
        "overview": overview,
        "processes": processes,
        "items": items,
        "awards": awards,
        "contracts": contracts,
        "parties": parties,
        "examples": examples,
        "query_seconds": q.seconds,
    }
    collision_counts = {
        entity: profile[entity]["hash_collision_ids"]
        for entity in ("processes", "items", "awards", "contracts", "parties")
    }
    failures = []
    coverage_checks = {}
    if overview["duplicate_source_observation_keys"]:
        failures.append("duplicate source observation keys")
    failures.extend(
        f"{entity} hash collisions"
        for entity, count in collision_counts.items()
        if count
    )
    for entity in ("processes", "items", "awards", "contracts", "parties"):
        basis_rows = sum(
            row["observation_rows"] for row in profile[entity]["identity_bases"]
        )
        expected_rows = profile[entity]["observation_rows"]
        coverage_checks[entity] = {
            "expected_observation_rows": expected_rows,
            "identity_basis_rows": basis_rows,
            "matches": basis_rows == expected_rows,
        }
        if basis_rows != expected_rows:
            failures.append(f"{entity} identity-basis coverage mismatch")
    contract_link_rows = sum(
        row["observation_rows"] for row in contracts["award_links"]
    )
    coverage_checks["contract_award_links"] = {
        "expected_observation_rows": contracts["observation_rows"],
        "link_status_rows": contract_link_rows,
        "matches": contract_link_rows == contracts["observation_rows"],
    }
    if contract_link_rows != contracts["observation_rows"]:
        failures.append("contract award-link coverage mismatch")
    profile["validation"] = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "hash_collision_counts": collision_counts,
        "coverage_checks": coverage_checks,
        "interpretation": (
            "Multiple content versions under one stable ID are expected observed "
            "states, not cryptographic collisions."
        ),
    }
    return profile


def number(value):
    return f"{value:,}" if isinstance(value, int) else str(value)


def metric_table(values):
    ignored = {"identity_bases", "award_links", "role_mentions"}
    lines = ["| Metric | Value |", "|---|---:|"]
    for key, value in values.items():
        if key not in ignored and not isinstance(value, (dict, list)):
            lines.append(f"| `{key}` | {number(value)} |")
    return lines


def render_markdown(profile, input_path, config_path, truncated):
    lines = [
        "# Deterministic ID prototype profile",
        "",
        f"- Input: `{input_path}`",
        f"- Identity configuration: `{config_path}`",
        f"- Identity rules version: `{profile['identity_rules_version']}`",
        f"- Validation: **{profile['validation']['status']}**",
        f"- Truncated test: `{str(truncated).lower()}`",
        "",
        "IDs use the full lowercase SHA-256 digest of a compact JSON-array "
        "payload. Payloads include the rules version, entity type, identity "
        "basis, scope, and source identity fields.",
    ]
    for heading, key in (
        ("Overview", "overview"),
        ("Processes", "processes"),
        ("Items", "items"),
        ("Awards", "awards"),
        ("Contracts", "contracts"),
        ("Parties", "parties"),
    ):
        values = profile[key]
        lines.extend(["", f"## {heading}", "", *metric_table(values)])
        for nested_key in ("identity_bases", "award_links", "role_mentions"):
            if nested_key not in values:
                continue
            rows = values[nested_key]
            if not rows:
                continue
            columns = list(rows[0])
            lines.extend(
                [
                    "",
                    f"### {nested_key.replace('_', ' ').title()}",
                    "",
                    "| " + " | ".join(columns) + " |",
                    "|" + "|".join("---" for _ in columns) + "|",
                ]
            )
            for row in rows:
                lines.append(
                    "| " + " | ".join(number(row[column]) for column in columns) + " |"
                )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- A hash collision means two different canonical identity payloads "
            "produced the same ID; any such collision fails validation.",
            "- Multiple content versions under one ID mean the same entity was "
            "observed with changed or conflicting attributes. Those versions are "
            "preserved for release construction.",
            "- Party IDs identify normalized name mentions within a process. They "
            "must not be represented as legal-entity identifiers.",
            "- Examples and their callable source breadcrumbs are available in "
            "the JSON artifact.",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    args = parse_args()
    input_path = args.input.resolve()
    rules_path = args.rules.resolve()
    json_output = args.json_output.resolve()
    markdown_output = args.markdown_output.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if not rules_path.exists():
        raise FileNotFoundError(rules_path)
    rules_bytes = rules_path.read_bytes()
    rules = json.loads(rules_bytes.decode("utf-8-sig"))

    source_sql = f"read_parquet({sql_string(str(input_path))})"
    if args.max_rows:
        source_sql = f"(SELECT * FROM {source_sql} LIMIT {int(args.max_rows)})"
    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    started = time.perf_counter()
    try:
        create_views(
            connection,
            source_sql,
            rules,
            materialize_source=bool(args.max_rows),
        )
        profile = build_profile(connection, rules)
    finally:
        connection.close()
    profile["input"] = {
        "path": str(input_path),
        "size_bytes": input_path.stat().st_size,
        "truncated_for_test": bool(args.max_rows),
        "max_rows": args.max_rows,
    }
    profile["identity_config"] = {
        "path": str(rules_path),
        "sha256": hashlib.sha256(rules_bytes).hexdigest(),
    }
    profile["elapsed_seconds"] = round(time.perf_counter() - started, 3)

    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    markdown_output.write_text(
        render_markdown(profile, input_path, rules_path, bool(args.max_rows)),
        encoding="utf-8",
    )
    print(json.dumps(profile, indent=2))
    if profile["validation"]["status"] != "pass":
        raise RuntimeError("ID prototype validation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
