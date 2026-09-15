#!/usr/bin/env python3
"""Build resumable OCDS-aligned Parquet tables from cleaned PhilGEPS data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb


CORE_TABLES = (
    "release_index", "releases", "contracting_processes", "tenders",
    "tender_items", "awards", "contracts", "parties", "party_roles",
    "award_items", "award_suppliers", "record_sources",
    "data_quality_issues",
)

ITEM_FIELDS = (
    "item_name", "item_description", "quantity", "unit_of_measurement",
    "item_budget", "unspsc_code", "unspsc_description",
)
AWARD_FIELDS = (
    "award_title", "award_date", "award_published_date",
    "awardee_organization_name_key", "contract_amount",
)
CONTRACT_FIELDS = (
    "contract_amount", "notice_to_proceed_date", "contract_effectivity_date",
    "contract_end_date",
)


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=project.parent / "DATA_NORMALIZATION" / "output" / "philgeps_cleaned.parquet",
    )
    parser.add_argument("--output-dir", type=Path, default=project / "outputs" / "parquet")
    parser.add_argument("--work-dir", type=Path, default=project / "outputs" / ".build")
    parser.add_argument("--identity-rules", type=Path, default=project / "config" / "identity_rules.json")
    parser.add_argument("--field-mapping", type=Path, default=project / "config" / "field_mapping.json")
    parser.add_argument("--codelist-mapping", type=Path, default=project / "config" / "codelist_mapping.json")
    parser.add_argument("--tables", nargs="+", choices=CORE_TABLES, default=list(CORE_TABLES))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--memory-limit",
        default="10GB",
        help="DuckDB memory ceiling; lower values encourage disk spilling",
    )
    parser.add_argument("--max-temp-size", default="100GB")
    parser.add_argument(
        "--process-partitions",
        type=int,
        default=32,
        help="Hash partitions used to build contracting_processes (default: 32)",
    )
    parser.add_argument("--max-rows", type=int, help="Testing only")
    parser.add_argument("--replace", action="store_true", help="Rebuild existing requested tables")
    return parser.parse_args()


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def json_array(expressions: list[str]) -> str:
    return "to_json(list_value(" + ", ".join(expressions) + "))"


def digest_id(prefix: str, payload: str) -> str:
    return f"{literal(prefix + '_')} || sha256({payload})"


def process_expressions(rules: dict) -> tuple[str, str, str]:
    version = str(rules["identity_rules_version"])
    excluded = ", ".join(
        literal(value)
        for value in rules["process"]["rules"][0]["excluded_values_case_insensitive"]
    )
    valid = (
        "bid_reference_no IS NOT NULL AND "
        f"upper(trim(bid_reference_no)) NOT IN ({excluded})"
    )
    composite = (
        "procuring_entity_name_key IS NOT NULL AND notice_title IS NOT NULL "
        "AND bid_published_date IS NOT NULL"
    )
    basis = (
        f"CASE WHEN {valid} THEN 'bid_reference' "
        f"WHEN {composite} THEN 'inferred_content_composite' "
        "ELSE 'source_row' END"
    )
    payload = f"""
    CASE
      WHEN {valid} THEN {json_array([literal(version), literal('process'), literal('bid_reference'), 'bid_reference_no'])}
      WHEN {composite} THEN {json_array([
          literal(version), literal('process'), literal('inferred_content_composite'),
          'procuring_entity_name_key', 'solicitation_no', 'notice_title',
          "strftime(bid_published_date, '%Y-%m-%dT%H:%M:%S.%f')"
      ])}
      ELSE {json_array([
          literal(version), literal('process'), literal('source_row'),
          '_source_file_id', '_source_sheet', 'cast(_source_row_number AS VARCHAR)'
      ])}
    END
    """
    return basis, payload, digest_id(rules["process"]["id_prefix"], payload)


def child_id_expressions(rules: dict) -> dict[str, str]:
    version = literal(str(rules["identity_rules_version"]))
    timestamp_format = rules["canonical_timestamp_format"]
    item_content = [
        f"strftime({field}, {literal(timestamp_format)})"
        if field.endswith("_date")
        else f"cast({field} AS VARCHAR)"
        for field in ITEM_FIELDS
    ]
    item_payload = f"""
      CASE WHEN line_item_no IS NOT NULL THEN {json_array([
          version, literal('item'), literal('line_item_no'), 'process_id',
          'cast(line_item_no AS VARCHAR)'
      ])} ELSE {json_array([
          version, literal('item'), literal('item_content_composite'),
          'process_id', *item_content
      ])} END
    """
    award_content = [
        f"strftime({field}, {literal(timestamp_format)})"
        if field.endswith("_date")
        else f"cast({field} AS VARCHAR)"
        for field in AWARD_FIELDS
    ]
    award_payload = f"""
      CASE WHEN award_reference_no IS NOT NULL THEN {json_array([
          version, literal('award'), literal('award_reference_no'),
          'process_id', 'award_reference_no'
      ])} ELSE {json_array([
          version, literal('award'), literal('award_content_composite'),
          'process_id', *award_content
      ])} END
    """
    award_id = digest_id(rules["award"]["id_prefix"], award_payload)
    contract_content = [
        f"strftime({field}, {literal(timestamp_format)})"
        if field.endswith("_date")
        else f"cast({field} AS VARCHAR)"
        for field in CONTRACT_FIELDS
    ]
    contract_payload = f"""
      CASE WHEN award_reference_no IS NULL THEN {json_array([
          version, literal('contract'), literal('missing_award_source_row'),
          'process_id', '_source_file_id', '_source_sheet',
          'cast(_source_row_number AS VARCHAR)'
      ])} WHEN contract_no IS NOT NULL THEN {json_array([
          version, literal('contract'), literal('award_scoped_contract_no'),
          award_id, 'contract_no'
      ])} ELSE {json_array([
          version, literal('contract'), literal('award_scoped_content_composite'),
          award_id, *contract_content
      ])} END
    """
    return {
        "item_id": digest_id(rules["item"]["id_prefix"], item_payload),
        "award_id": award_id,
        "contract_id": digest_id(rules["contract"]["id_prefix"], contract_payload),
    }


def party_id_expression(rules: dict, name_key: str) -> str:
    payload = json_array([
        literal(str(rules["identity_rules_version"])), literal("party"),
        literal("normalized_name_mention"), "process_id", name_key,
    ])
    return digest_id(rules["party"]["id_prefix"], payload)


def accepted_case(field: str, mapping: dict) -> str:
    clauses = []
    for source, rule in mapping["mappings"][field]["values"].items():
        if rule["status"] == "accepted" and rule["destination_value"] is not None:
            clauses.append(
                f"WHEN {field} = {literal(source)} THEN {literal(rule['destination_value'])}"
            )
    return "CASE " + " ".join(clauses) + " ELSE NULL END"


def source_relation(input_path: Path, max_rows: int | None) -> str:
    relation = f"read_parquet({literal(str(input_path))})"
    if max_rows:
        relation = (
            f"(SELECT * FROM {relation} "
            "ORDER BY _source_file_id, _source_row_number "
            f"LIMIT {int(max_rows)})"
        )
    return relation


def copy_query(connection, query: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        connection.execute(
            f"COPY ({query}) TO {literal(str(temporary))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise
    temporary.replace(target)


def copy_sorted(
    connection,
    source: Path,
    target: Path,
    key: str,
    work_dir: Path,
    partitions: int = 16,
):
    """Physically re-sort `source` by `key` without a global in-memory sort.

    Zone-map pruning needs rows clustered by the filter key. A single ORDER BY
    over tens of millions of rows can buffer the whole result, so we instead
    range-partition on the first hex digit of the digest (keys are
    ``pg??_<64-hex>``) into contiguous lexical buckets, sort each bucket, and
    concatenate in hex order. The result is globally ordered enough for
    row-group zone maps to prune point lookups to 1-2 row groups.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = work_dir / f"sorted_parts_{target.stem}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in parts_dir.glob("part_*.parquet"):
        stale.unlink()
    relation = f"read_parquet({literal(str(source))})"
    # Digests live after the ``pg??_`` prefix (5 chars); first hex digit gives
    # 16 contiguous lexical ranges. Fall back to hash only for non-digest keys.
    digits = "0123456789abcdef"
    if partitions != 16:
        # Non-default: hash buckets (coarse clustering only — prefer 16).
        for partition in range(partitions):
            if partition == 0 or (partition + 1) % 8 == 0 or partition + 1 == partitions:
                print(f"  sort {target.stem} part {partition + 1}/{partitions}", flush=True)
            copy_query(
                connection,
                f"SELECT * FROM {relation} WHERE hash({key}) % {partitions} = {partition} "
                f"ORDER BY {key}",
                parts_dir / f"part_{partition:03d}.parquet",
            )
    else:
        for index, digit in enumerate(digits):
            if index == 0 or (index + 1) % 4 == 0 or index + 1 == 16:
                print(f"  sort {target.stem} part {index + 1}/16 ('{digit}')", flush=True)
            copy_query(
                connection,
                f"SELECT * FROM {relation} "
                f"WHERE lower(substr({key}, 6, 1)) = {literal(digit)} "
                f"ORDER BY {key}",
                parts_dir / f"part_{index:03d}.parquet",
            )
    glob = (parts_dir / "part_*.parquet").as_posix()
    copy_query(
        connection,
        f"SELECT * FROM read_parquet({literal(glob)})",
        target,
    )


def build_release_index(
    connection, relation: str, target: Path, rules: dict, work_dir: Path
):
    """Two-pass build to stay inside the DuckDB memory ceiling.

    A single-query form (identify → group → join → sort) inlines the
    per-row identification CTE twice — recomputing process ids and
    60-column semantic hashes on both branches — and buffers a large
    final sort, which exceeded a 10GB limit on the full dataset.
    Materializing the slim per-row identification once keeps each pass
    streamable. Row order in the index is irrelevant: every consumer
    joins on (_source_file_id, _source_row_number).
    """
    columns = [
        row[0]
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    ]
    excluded = {
        "_source_file_id", "_source_sheet", "_source_row_number", "_source_schema_id",
        "_replacement_character_columns", "_cleaning_issues", "_cleaning_issue_count",
        "procuring_entity_name_key", "client_agency_key", "awardee_organization_name_key",
    }
    semantic = [column for column in columns if column not in excluded]
    semantic_payload = json_array([f"cast({column} AS VARCHAR)" for column in semantic])
    basis, _, process_id = process_expressions(rules)
    release_payload = json_array(
        [
            literal(str(rules["identity_rules_version"])),
            literal("release"),
            "process_id",
            "release_content_hash",
        ]
    )
    identified_path = work_dir / "release_index_identified.parquet"
    print("  pass 1/2: per-row process ids and semantic hashes", flush=True)
    copy_query(
        connection,
        f"""
        SELECT _source_file_id, _source_sheet, _source_row_number,
               {basis} AS process_identity_basis,
               {process_id} AS process_id,
               sha256({semantic_payload}) AS semantic_row_hash
        FROM {relation}
        """,
        identified_path,
    )
    identified = f"read_parquet({literal(str(identified_path))})"
    print("  pass 2/2: grouping observations into releases", flush=True)
    query = f"""
    WITH state_groups AS (
      SELECT process_id, _source_file_id, _source_sheet,
             sha256(to_json(list_sort(list_distinct(list(semantic_row_hash)))))
               AS release_content_hash
      FROM {identified}
      GROUP BY process_id, _source_file_id, _source_sheet
    ), states AS (
      SELECT *, {digest_id('pgrl', release_payload)} AS release_id
      FROM state_groups
    )
    SELECT i._source_file_id, i._source_sheet, i._source_row_number,
           i.process_identity_basis, i.process_id,
           s.release_content_hash, s.release_id
    FROM {identified} i
    JOIN states s
      ON i.process_id = s.process_id
     AND i._source_file_id = s._source_file_id
     AND i._source_sheet IS NOT DISTINCT FROM s._source_sheet
    """
    try:
        copy_query(connection, query, target)
    finally:
        if identified_path.exists():
            identified_path.unlink()


def indexed_rows(relation: str, index_path: Path) -> str:
    index = f"read_parquet({literal(str(index_path))})"
    return f"""
    SELECT s.*, i.process_identity_basis, i.process_id,
           i.release_content_hash, i.release_id,
           i._source_file_id || ':' || cast(i._source_row_number AS VARCHAR)
             AS source_breadcrumb
    FROM {relation} s
    JOIN {index} i
      ON s._source_file_id = i._source_file_id
     AND s._source_row_number = i._source_row_number
    """


def materialize_indexed_rows(
    connection, relation: str, index_path: Path, work_dir: Path, input_rows: int,
    reuse: bool = False,
) -> str:
    """Write the observation ⋈ release-index join once, chunked per source file.

    Every downstream builder reads this join, and several reference it two
    or three times inside one query — recomputing the full 18.5M × 18.5M
    hash join inside each aggregation exceeded the memory ceiling (the
    index build side alone is several GB of long hex ids). Chunking the
    join by _source_file_id bounds the hash-table build side to a single
    source file, and the resulting per-part row-group statistics let
    builders column- and row-prune when scanning the glob.

    With reuse=True, existing parts matching the current release_index are
    reused and only missing parts are built, so a resumed run skips the
    multi-hour join after a downstream failure. Safety: reuse is allowed
    even under --replace (which rebuilds tables), but only when the parts
    were produced from the same release_index — verified by a metadata
    stamp (file name, size, mtime) so a rebuilt index invalidates parts.
    """
    parts_dir = work_dir / "rows_joined"
    parts_dir.mkdir(parents=True, exist_ok=True)
    stamp_path = parts_dir / "release_index.stamp"
    stamp = json.dumps(
        {
            "name": index_path.name,
            "size": index_path.stat().st_size,
            "mtime_ns": index_path.stat().st_mtime_ns,
        }
    )
    index = f"read_parquet({literal(str(index_path))})"
    file_ids = [
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT _source_file_id FROM {index} ORDER BY 1"
        ).fetchall()
    ]
    expected_parts = {f"part_{ordinal:03d}.parquet" for ordinal in range(1, len(file_ids) + 1)}
    existing_parts = {part.name for part in parts_dir.glob("part_*.parquet")}
    stamped = stamp_path.exists() and stamp_path.read_text(encoding="utf-8") == stamp
    reusable = stamped and existing_parts == expected_parts if reuse else False
    if reuse and not reusable:
        reason = "release_index changed" if not stamped else "part set incomplete"
        if existing_parts:
            print(
                f"  discarding {len(existing_parts)} join part(s): {reason}",
                flush=True,
            )
        for stale in parts_dir.glob("part_*.parquet"):
            stale.unlink()
    done = {part.name for part in parts_dir.glob("part_*.parquet")}
    for ordinal, file_id in enumerate(file_ids, start=1):
        part_name = f"part_{ordinal:03d}.parquet"
        if part_name in done:
            continue
        if ordinal == 1 or ordinal % 10 == 0 or ordinal == len(file_ids):
            print(f"  join part {ordinal}/{len(file_ids)}", flush=True)
        query = f"""
        SELECT s.*, i.process_identity_basis, i.process_id,
               i.release_content_hash, i.release_id,
               i._source_file_id || ':' || cast(i._source_row_number AS VARCHAR)
                 AS source_breadcrumb
        FROM {relation} s
        JOIN {index} i
          ON s._source_file_id = i._source_file_id
         AND s._source_row_number = i._source_row_number
        WHERE s._source_file_id = {literal(file_id)}
        """
        copy_query(connection, query, parts_dir / part_name)
    glob = (parts_dir / "*.parquet").as_posix()
    joined_rows = connection.execute(
        f"SELECT count(*) FROM read_parquet({literal(glob)})"
    ).fetchone()[0]
    if joined_rows != input_rows:
        raise RuntimeError(
            f"materialized join covers {joined_rows:,} rows but input has "
            f"{input_rows:,}; release_index does not cover every observation"
        )
    stamp_path.write_text(stamp, encoding="utf-8")
    # A bare read_parquet(glob) cannot be re-wrapped as FROM ({rows}) by the
    # builders; a full SELECT statement can.
    return f"SELECT * FROM read_parquet({literal(glob)})"


def build_releases(connection, rows: str, target: Path):
    query = f"""
    SELECT release_id, process_id, cast(NULL AS VARCHAR) AS ocid,
           max(award_published_date) AS award_publication_evidence,
           min(bid_published_date) AS bid_publication_evidence,
           max(award_date) AS award_date_evidence,
           coalesce(max(award_published_date), min(bid_published_date), max(award_date))
             AS release_date,
           CASE WHEN max(award_published_date) IS NOT NULL THEN 'award_published_date'
                WHEN min(bid_published_date) IS NOT NULL THEN 'bid_published_date'
                WHEN max(award_date) IS NOT NULL THEN 'award_date'
                ELSE 'missing' END AS release_date_basis,
           release_content_hash AS content_hash,
           count(*) AS supporting_observation_rows,
           count(DISTINCT _source_file_id) AS supporting_source_files,
           list_sort(list(DISTINCT _source_file_id)) AS source_file_ids,
           bool_or(notice_title IS NOT NULL OR bid_reference_no IS NOT NULL)
             AS has_tender,
           bool_or(award_reference_no IS NOT NULL OR award_title IS NOT NULL)
             AS has_award,
           bool_or(contract_no IS NOT NULL OR notice_to_proceed_date IS NOT NULL
                   OR contract_effectivity_date IS NOT NULL OR contract_end_date IS NOT NULL)
             AS has_contract
    FROM ({rows})
    GROUP BY release_id, process_id, release_content_hash
    ORDER BY process_id, release_date NULLS LAST, release_id
    """
    copy_query(connection, query, target)


def build_processes(
    connection, rows: str, releases_path: Path, target: Path,
    work_dir: Path, partitions: int = 32,
):
    """Build processes in bounded hash partitions and stream-merge the parts.

    The unpartitioned pair of GROUP BY operations can retain nearly the whole
    process cardinality in memory. Partitioning by the stable process_id keeps
    each aggregation bounded and lets DuckDB spill each part independently.
    Physical row order is not part of this table's contract.
    """
    if partitions < 1:
        raise ValueError("process partitions must be at least 1")
    releases = f"read_parquet({literal(str(releases_path))})"
    parts_dir = work_dir / "contracting_process_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in parts_dir.glob("part_*.parquet"):
        stale.unlink()
    for partition in range(partitions):
        if partition == 0 or (partition + 1) % 8 == 0 or partition + 1 == partitions:
            print(f"  process part {partition + 1}/{partitions}", flush=True)
        predicate = f"hash(process_id) % {partitions} = {partition}"
        query = f"""
        WITH source_ids AS (
          SELECT process_id,
                 arg_min(bid_reference_no, source_breadcrumb)
                   FILTER (WHERE process_identity_basis = 'bid_reference')
                   AS source_process_identifier,
                 min(process_identity_basis) AS source_identifier_basis
          FROM ({rows}) WHERE {predicate} GROUP BY process_id
        ), ordered AS (
          SELECT process_id,
                 arg_min(release_id, (release_date IS NULL, release_date, release_id))
                   AS first_release_id,
                 arg_max(release_id, (release_date IS NOT NULL, release_date, release_id))
                   AS latest_release_id,
                 count(*) AS release_count
          FROM {releases} WHERE {predicate} GROUP BY process_id
        )
        SELECT s.process_id, cast(NULL AS VARCHAR) AS ocid,
               s.source_process_identifier, s.source_identifier_basis,
               o.first_release_id, o.latest_release_id, o.release_count,
               CASE WHEN s.source_identifier_basis = 'bid_reference' THEN []::VARCHAR[]
                    ELSE [s.source_identifier_basis] END AS process_quality_flags
        FROM source_ids s JOIN ordered o USING (process_id)
        """
        copy_query(
            connection,
            query,
            parts_dir / f"part_{partition:03d}.parquet",
        )
    glob = (parts_dir / "part_*.parquet").as_posix()
    # Hash parts keep each aggregation bounded, but their concatenation is
    # not process_id-clustered (hash buckets span the full lexical range).
    # Re-sort via range-bucketed copy_sorted so viewer point lookups prune.
    unsorted = work_dir / "contracting_processes_unsorted.parquet"
    copy_query(
        connection,
        f"SELECT * FROM read_parquet({literal(glob)})",
        unsorted,
    )
    copy_sorted(connection, unsorted, target, "process_id", work_dir)


def build_tenders(connection, rows: str, target: Path, codelists: dict):
    category = accepted_case("classification", codelists)
    method = accepted_case("procurement_mode", codelists)
    status = accepted_case("bid_notice_status", codelists)
    duration_unit = accepted_case("calendar_type", codelists)
    query = f"""
    WITH source_rows AS (
      SELECT * FROM ({rows})
      WHERE notice_title IS NOT NULL OR bid_reference_no IS NOT NULL
            OR solicitation_no IS NOT NULL OR bid_published_date IS NOT NULL
    ), representatives AS (
      SELECT release_id, min(source_breadcrumb) AS source_breadcrumb,
             count(DISTINCT hash(notice_title, procurement_mode, approved_budget,
                                 closing_date, bid_notice_status))
               AS scalar_state_count
      FROM source_rows GROUP BY release_id
    )
    SELECT s.release_id, s.process_id AS tender_id,
           s.bid_reference_no AS source_bid_reference,
           s.solicitation_no AS solicitation_number,
           s.notice_title AS title,
           s.bid_published_date AS date_published,
           s.classification AS source_classification,
           {category} AS main_procurement_category,
           s.notice_type AS source_notice_type,
           s.business_category AS business_category,
           s.funding_source AS funding_source,
           s.funding_instrument AS funding_instrument,
           s.procurement_mode AS procurement_method_details,
           {method} AS procurement_method,
           s.trade_agreement AS trade_agreement,
           s.approved_budget AS value_amount,
           cast(NULL AS VARCHAR) AS value_currency,
           s.area_of_delivery AS area_of_delivery,
           s.contract_duration AS source_contract_duration,
           s.calendar_type AS source_calendar_type,
           {duration_unit} AS contract_duration_unit,
           CASE WHEN s.calendar_type = 'Day/s' THEN s.contract_duration END
             AS contract_duration_days,
           s.prebid_date AS prebid_date,
           s.closing_date AS closing_date,
           s.bid_notice_status AS source_status,
           {status} AS status,
           r.scalar_state_count
    FROM source_rows s
    JOIN representatives r USING (release_id, source_breadcrumb)
    ORDER BY s.release_id
    """
    copy_query(connection, query, target)


def build_tender_items(connection, rows: str, target: Path, rules: dict):
    item_id = child_id_expressions(rules)["item_id"]
    item_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("line_item_no", *ITEM_FIELDS))
    query = f"""
    WITH candidates AS (
      SELECT *, {item_id} AS item_id,
             hash({', '.join(ITEM_FIELDS)}) AS content_signature
      FROM ({rows}) WHERE {item_evidence}
    ), representatives AS (
      SELECT release_id, item_id, min(source_breadcrumb) AS source_breadcrumb,
             count(DISTINCT content_signature) AS content_state_count
      FROM candidates GROUP BY release_id, item_id
    )
    SELECT c.release_id, c.item_id,
           c.line_item_no AS source_line_item_number,
           c.item_name AS title,
           c.item_description AS description,
           c.quantity AS quantity,
           c.unit_of_measurement AS unit_name,
           c.item_budget AS item_budget_amount,
           cast(NULL AS VARCHAR) AS item_budget_currency,
           CASE WHEN c.unspsc_code IS NOT NULL
                THEN 'UNSPSC' END AS classification_scheme,
           c.unspsc_code AS classification_id,
           c.unspsc_description AS classification_description,
           r.content_state_count,
           CASE WHEN r.content_state_count > 1
                THEN ['multiple_content_states'] ELSE []::VARCHAR[] END
             AS item_quality_flags
    FROM candidates c
    JOIN representatives r USING (release_id, item_id, source_breadcrumb)
    ORDER BY c.release_id, c.item_id
    """
    copy_query(connection, query, target)


def build_awards(connection, rows: str, target: Path, rules: dict, codelists: dict):
    award_id = child_id_expressions(rules)["award_id"]
    status = accepted_case("award_notice_status", codelists)
    award_evidence = " OR ".join(
        f"{field} IS NOT NULL"
        for field in ("award_reference_no", *AWARD_FIELDS, "award_notice_status")
    )
    query = f"""
    WITH candidates AS (
      SELECT *, {award_id} AS award_id,
             hash({', '.join(AWARD_FIELDS)}, award_notice_status,
                  reason_for_award, award_type) AS content_signature
      FROM ({rows}) WHERE {award_evidence}
    ), representatives AS (
      SELECT release_id, award_id, min(source_breadcrumb) AS source_breadcrumb,
             count(DISTINCT content_signature) AS content_state_count
      FROM candidates GROUP BY release_id, award_id
    )
    SELECT c.release_id, c.award_id,
           c.award_reference_no AS source_award_reference,
           c.award_title AS title,
           c.reason_for_award AS description,
           c.award_type AS source_award_type,
           c.award_date AS date,
           c.award_published_date AS date_published,
           c.contract_amount AS value_amount,
           cast(NULL AS VARCHAR) AS value_currency,
           c.award_notice_status AS source_status,
           {status} AS status,
           r.content_state_count,
           CASE WHEN r.content_state_count > 1
                THEN ['multiple_content_states'] ELSE []::VARCHAR[] END
             AS award_quality_flags
    FROM candidates c
    JOIN representatives r USING (release_id, award_id, source_breadcrumb)
    ORDER BY c.release_id, c.award_id
    """
    copy_query(connection, query, target)


def build_contracts(connection, rows: str, target: Path, rules: dict):
    ids = child_id_expressions(rules)
    contract_evidence = " OR ".join(
        f"{field} IS NOT NULL"
        for field in ("contract_no", "notice_to_proceed_date",
                      "contract_effectivity_date", "contract_end_date")
    )
    query = f"""
    WITH candidates AS (
      SELECT *, CASE WHEN award_reference_no IS NOT NULL THEN {ids['award_id']} END
                    AS award_id,
             {ids['contract_id']} AS contract_id,
             hash({', '.join(CONTRACT_FIELDS)}) AS content_signature
      FROM ({rows}) WHERE {contract_evidence}
    ), representatives AS (
      SELECT release_id, contract_id, min(source_breadcrumb) AS source_breadcrumb,
             count(DISTINCT content_signature) AS content_state_count
      FROM candidates GROUP BY release_id, contract_id
    )
    SELECT c.release_id, c.contract_id,
           c.contract_no AS source_contract_number,
           c.award_id,
           c.award_reference_no AS source_award_reference,
           CASE WHEN c.award_reference_no IS NULL
                THEN 'missing' ELSE 'matched' END AS award_link_status,
           c.contract_amount AS value_amount,
           cast(NULL AS VARCHAR) AS value_currency,
           c.contract_effectivity_date AS period_start,
           c.contract_end_date AS period_end,
           date_diff('day', c.contract_effectivity_date, c.contract_end_date)
             AS duration_in_days,
           c.notice_to_proceed_date,
           r.content_state_count,
           list_filter([
             CASE WHEN c.award_reference_no IS NULL
                  THEN 'contract_award_missing' END,
             CASE WHEN r.content_state_count > 1
                  THEN 'multiple_content_states' END
           ], x -> x IS NOT NULL) AS contract_quality_flags
    FROM candidates c
    JOIN representatives r USING (release_id, contract_id, source_breadcrumb)
    ORDER BY c.release_id, c.contract_id
    """
    copy_query(connection, query, target)


def party_mentions_query(rows: str, rules: dict) -> str:
    procuring = party_id_expression(rules, "procuring_entity_name_key")
    buyer = party_id_expression(rules, "client_agency_key")
    supplier = party_id_expression(rules, "awardee_organization_name_key")
    return f"""
    SELECT release_id, process_id, 'procuringEntity' AS role,
           {procuring} AS party_id, procuring_entity_name AS name,
           procuring_entity_name_key AS name_key,
           procuring_entity_region AS source_region,
           procuring_entity_province AS source_province,
           procuring_entity_city_municipality AS source_city_municipality,
           government_branch, procuring_entity_organization_type AS source_organization_type,
           procuring_entity_organization_type_grouped AS organization_type_grouped,
           NULL::VARCHAR AS source_country, NULL::VARCHAR AS organization_size,
           NULL::VARCHAR AS contact_name, NULL::VARCHAR AS source_joint_venture,
           source_breadcrumb
    FROM ({rows}) WHERE procuring_entity_name_key IS NOT NULL
    UNION ALL
    SELECT release_id, process_id, 'buyer_candidate', {buyer}, client_agency,
           client_agency_key, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
           NULL, NULL, source_breadcrumb
    FROM ({rows}) WHERE client_agency_key IS NOT NULL
    UNION ALL
    SELECT release_id, process_id, 'supplier', {supplier},
           awardee_organization_name, awardee_organization_name_key,
           awardee_region, awardee_province, awardee_city_municipality,
           NULL, NULL, NULL, awardee_country, awardee_size,
           awardee_contact_person, awardee_joint_venture, source_breadcrumb
    FROM ({rows}) WHERE awardee_organization_name_key IS NOT NULL
    """


def build_parties(connection, rows: str, target: Path, rules: dict):
    mentions = party_mentions_query(rows, rules)
    query = f"""
    WITH mentions AS (
      SELECT *,
             (name IS NOT NULL)::INT + (source_country IS NOT NULL)::INT
             + (source_region IS NOT NULL)::INT + (source_province IS NOT NULL)::INT
             + (source_city_municipality IS NOT NULL)::INT
             + (government_branch IS NOT NULL)::INT
             + (source_organization_type IS NOT NULL)::INT
             + (organization_type_grouped IS NOT NULL)::INT
             + (organization_size IS NOT NULL)::INT + (contact_name IS NOT NULL)::INT
             + (source_joint_venture IS NOT NULL)::INT AS completeness_score,
             source_breadcrumb || '|' || role AS mention_key
      FROM ({mentions})
    ), max_scores AS (
      SELECT release_id, party_id, max(completeness_score) AS completeness_score,
             count(DISTINCT name) AS source_spelling_count
      FROM mentions GROUP BY release_id, party_id
    ), representative_keys AS (
      SELECT m.release_id, m.party_id, min(m.mention_key) AS mention_key,
             s.source_spelling_count
      FROM mentions m JOIN max_scores s
        USING (release_id, party_id, completeness_score)
      GROUP BY m.release_id, m.party_id, s.source_spelling_count
    )
    SELECT m.release_id, m.party_id, m.name, m.name_key,
           m.source_country, m.source_region, m.source_province,
           m.source_city_municipality, m.government_branch,
           m.source_organization_type, m.organization_type_grouped,
           m.organization_size, m.contact_name, m.source_joint_venture,
           k.source_spelling_count,
           'name_mention' AS identity_confidence,
           CASE WHEN k.source_spelling_count > 1 THEN ['multiple_source_spellings']
                ELSE []::VARCHAR[] END AS party_quality_flags
    FROM mentions m JOIN representative_keys k
      USING (release_id, party_id, mention_key)
    ORDER BY m.release_id, m.party_id
    """
    copy_query(connection, query, target)


def build_party_roles(connection, rows: str, target: Path, rules: dict):
    mentions = party_mentions_query(rows, rules)
    query = f"""
    SELECT DISTINCT release_id, party_id, role
    FROM ({mentions})
    ORDER BY release_id, party_id, role
    """
    copy_query(connection, query, target)


def build_award_items(connection, rows: str, target: Path, rules: dict):
    ids = child_id_expressions(rules)
    item_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("line_item_no", *ITEM_FIELDS))
    award_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("award_reference_no", *AWARD_FIELDS))
    query = f"""
    SELECT DISTINCT release_id, {ids['award_id']} AS award_id,
           {ids['item_id']} AS item_id, 'same_source_row' AS link_basis
    FROM ({rows}) WHERE ({item_evidence}) AND ({award_evidence})
    ORDER BY release_id, award_id, item_id
    """
    copy_query(connection, query, target)


def build_award_suppliers(connection, rows: str, target: Path, rules: dict):
    award_id = child_id_expressions(rules)["award_id"]
    party_id = party_id_expression(rules, "awardee_organization_name_key")
    assertion_payload = json_array([
        literal(str(rules["identity_rules_version"])),
        literal("award_supplier_assertion"), "release_id", "_source_file_id",
        "cast(_source_row_number AS VARCHAR)", "award_reference_no",
        "awardee_organization_name_key",
    ])
    assertion_id = digest_id("pgas", assertion_payload)
    query = f"""
    SELECT {assertion_id} AS award_supplier_assertion_id, release_id,
           CASE WHEN award_reference_no IS NOT NULL THEN {award_id} END AS award_id,
           CASE WHEN awardee_organization_name_key IS NOT NULL THEN {party_id} END AS party_id,
           award_reference_no AS source_award_reference,
           awardee_organization_name AS source_supplier_label,
           awardee_joint_venture AS source_joint_venture,
           CASE WHEN award_reference_no IS NULL THEN 'missing' ELSE 'matched' END
             AS award_link_status,
           CASE WHEN awardee_organization_name_key IS NULL THEN 'missing' ELSE 'matched' END
             AS party_link_status,
           list_filter([
             CASE WHEN award_reference_no IS NULL THEN 'supplier_award_missing' END,
             CASE WHEN awardee_organization_name_key IS NULL THEN 'supplier_party_missing' END,
             CASE WHEN awardee_joint_venture IS NOT NULL THEN 'joint_venture_unparsed' END
           ], x -> x IS NOT NULL) AS supplier_quality_flags,
           source_breadcrumb
    FROM ({rows})
    WHERE awardee_organization_name IS NOT NULL OR awardee_joint_venture IS NOT NULL
    ORDER BY release_id, award_id, award_supplier_assertion_id
    """
    copy_query(connection, query, target)


def build_record_sources(
    connection, rows: str, target: Path, rules: dict, work_dir: Path,
    issues_path: Path | None = None, replace: bool = False
):
    ids = child_id_expressions(rules)
    procuring = party_id_expression(rules, "procuring_entity_name_key")
    buyer = party_id_expression(rules, "client_agency_key")
    supplier = party_id_expression(rules, "awardee_organization_name_key")
    assertion_payload = json_array([
        literal(str(rules["identity_rules_version"])),
        literal("award_supplier_assertion"), "release_id", "_source_file_id",
        "cast(_source_row_number AS VARCHAR)", "award_reference_no",
        "awardee_organization_name_key",
    ])
    assertion_id = digest_id("pgas", assertion_payload)
    item_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("line_item_no", *ITEM_FIELDS))
    award_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("award_reference_no", *AWARD_FIELDS, "award_notice_status"))
    contract_evidence = " OR ".join(f"{field} IS NOT NULL" for field in ("contract_no", "notice_to_proceed_date", "contract_effectivity_date", "contract_end_date"))
    query_template = """
    WITH identified AS (
      SELECT *,
             CASE WHEN {item_evidence} THEN {item_id} END AS item_record_id,
             CASE WHEN {award_evidence} THEN {award_id} END AS award_record_id,
             CASE WHEN {contract_evidence} THEN {contract_id} END AS contract_record_id,
             CASE WHEN procuring_entity_name_key IS NOT NULL THEN {procuring} END
               AS procuring_party_id,
             CASE WHEN client_agency_key IS NOT NULL THEN {buyer} END AS buyer_party_id,
             CASE WHEN awardee_organization_name_key IS NOT NULL THEN {supplier} END
               AS supplier_party_id,
             CASE WHEN awardee_organization_name IS NOT NULL
                        OR awardee_joint_venture IS NOT NULL
                  THEN {assertion_id} END AS supplier_assertion_id
      FROM ({rows})
    ), source_links AS (
      SELECT links.record_type, links.record_id, b.release_id,
             b._source_file_id AS source_file_id,
             b._source_sheet AS source_sheet,
             b._source_row_number AS source_row_number
      FROM identified b
      CROSS JOIN LATERAL (
        SELECT record_type, record_id
        FROM (VALUES
          ('release', b.release_id, true),
          ('tender', b.process_id, true),
          ('tender_item', b.item_record_id, b.item_record_id IS NOT NULL),
          ('award', b.award_record_id, b.award_record_id IS NOT NULL),
          ('contract', b.contract_record_id, b.contract_record_id IS NOT NULL),
          ('party', b.procuring_party_id, b.procuring_party_id IS NOT NULL),
          ('party', b.buyer_party_id,
             b.buyer_party_id IS NOT NULL
             AND b.buyer_party_id IS DISTINCT FROM b.procuring_party_id),
          ('party', b.supplier_party_id,
             b.supplier_party_id IS NOT NULL
             AND b.supplier_party_id IS DISTINCT FROM b.procuring_party_id
             AND b.supplier_party_id IS DISTINCT FROM b.buyer_party_id),
          ('award_supplier_assertion', b.supplier_assertion_id,
             b.supplier_assertion_id IS NOT NULL)
        ) AS candidates(record_type, record_id, included)
        WHERE included
      ) links
    )
    """

    def build_query(file_filter: str) -> str:
        return query_template.format(
            item_evidence=item_evidence,
            item_id=ids['item_id'],
            award_evidence=award_evidence,
            award_id=ids['award_id'],
            contract_evidence=contract_evidence,
            contract_id=ids['contract_id'],
            procuring=procuring,
            buyer=buyer,
            supplier=supplier,
            assertion_id=assertion_id,
            rows=f"({rows} WHERE {file_filter})" if file_filter else f"({rows})",
        )

    base_dir = work_dir / "record_sources_base_parts"
    base_dir.mkdir(parents=True, exist_ok=True)
    for stale in base_dir.glob("part_*.parquet"):
        stale.unlink()
    file_ids = [
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT _source_file_id FROM ({rows}) ORDER BY 1"
        ).fetchall()
    ]
    for ordinal, file_id in enumerate(file_ids, start=1):
        if ordinal == 1 or ordinal % 10 == 0 or ordinal == len(file_ids):
            print(f"  base links part {ordinal}/{len(file_ids)}", flush=True)
        copy_query(
            connection,
            build_query(f"_source_file_id = {literal(file_id)}") + "SELECT * FROM source_links",
            base_dir / f"part_{ordinal:03d}.parquet",
        )
    base_glob = (base_dir / "part_*.parquet").as_posix()
    base_path = work_dir / "record_sources_base.parquet"
    print("assembling record_sources base links", flush=True)
    copy_query(
        connection,
        f"SELECT * FROM read_parquet({literal(base_glob)})",
        base_path,
    )
    parts = [f"SELECT * FROM read_parquet({literal(str(base_path))})"]
    if issues_path and issues_path.exists():
        issue_path = work_dir / "record_sources_quality_issues.parquet"
        if replace and issue_path.exists():
            issue_path.unlink()
        if not issue_path.exists():
            print("building record_sources quality-issue links", flush=True)
            issue_query = f"""
            SELECT 'data_quality_issue' AS record_type, d.issue_id AS record_id,
                   d.release_id, s.source_file_id, s.source_sheet,
                   s.source_row_number
            FROM read_parquet({literal(str(issues_path))}) d
            JOIN read_parquet({literal(str(base_path))}) s
              ON d.release_id = s.release_id
             AND d.record_type = s.record_type
             AND d.record_id = s.record_id
            """
            copy_query(connection, issue_query, issue_path)
        parts.append(f"SELECT * FROM read_parquet({literal(str(issue_path))})")
    print("combining record_sources links", flush=True)
    # Concatenate base + issue links (streaming), then re-sort by release_id
    # so release-scoped viewer lookups (release sources, summaries) prune
    # row groups instead of scanning all ~1150.
    unsorted = work_dir / "record_sources_unsorted.parquet"
    copy_query(connection, " UNION ALL ".join(parts), unsorted)
    copy_sorted(connection, unsorted, target, "release_id", work_dir)


def build_data_quality_issues(
    connection, output_dir: Path, target: Path, rules: dict, work_dir: Path
):
    version = literal(str(rules["identity_rules_version"]))

    def issue_id(record_type: str, record_id: str, release_id: str, code: str) -> str:
        return digest_id("pgdq", json_array([
            version, literal("data_quality_issue"), release_id,
            literal(record_type), record_id, literal(code),
        ]))

    tender = f"read_parquet({literal(str(output_dir / 'tenders.parquet'))})"
    item = f"read_parquet({literal(str(output_dir / 'tender_items.parquet'))})"
    award = f"read_parquet({literal(str(output_dir / 'awards.parquet'))})"
    contract = f"read_parquet({literal(str(output_dir / 'contracts.parquet'))})"
    party = f"read_parquet({literal(str(output_dir / 'parties.parquet'))})"
    supplier = f"read_parquet({literal(str(output_dir / 'award_suppliers.parquet'))})"
    specs = [
        (tender, "tender", "tender_id", "classification_unmapped", "source_classification IS NOT NULL AND main_procurement_category IS NULL", "mapping", "warning", True, "source_classification", "No accepted OCDS mainProcurementCategory mapping."),
        (tender, "tender", "tender_id", "procurement_method_unmapped", "procurement_method_details IS NOT NULL AND procurement_method IS NULL", "mapping", "warning", True, "procurement_method_details", "No accepted OCDS procurementMethod mapping."),
        (tender, "tender", "tender_id", "tender_status_unmapped", "source_status IS NOT NULL AND status IS NULL", "mapping", "warning", True, "source_status", "No accepted OCDS tender status mapping."),
        (tender, "tender", "tender_id", "tender_scalar_conflict", "scalar_state_count > 1", "conflict", "warning", False, "cast(scalar_state_count AS VARCHAR)", "Multiple tender scalar states occur in one release grouping."),
        (item, "tender_item", "item_id", "item_content_conflict", "content_state_count > 1", "conflict", "warning", False, "cast(content_state_count AS VARCHAR)", "One item identity has multiple content states in the release."),
        (award, "award", "award_id", "award_content_conflict", "content_state_count > 1", "conflict", "warning", False, "cast(content_state_count AS VARCHAR)", "One award identity has multiple content states in the release."),
        (contract, "contract", "contract_id", "contract_award_missing", "award_link_status = 'missing'", "relationship", "error", True, "source_award_reference", "Contract evidence has no award reference."),
        (contract, "contract", "contract_id", "contract_content_conflict", "content_state_count > 1", "conflict", "warning", False, "cast(content_state_count AS VARCHAR)", "One contract identity has multiple content states in the release."),
        (party, "party", "party_id", "party_name_variants", "source_spelling_count > 1", "identity", "info", False, "cast(source_spelling_count AS VARCHAR)", "A conservative party key has multiple source spellings."),
        (supplier, "award_supplier_assertion", "award_supplier_assertion_id", "supplier_award_missing", "award_link_status = 'missing'", "relationship", "error", True, "source_award_reference", "Supplier assertion has no award reference."),
        (supplier, "award_supplier_assertion", "award_supplier_assertion_id", "supplier_party_missing", "party_link_status = 'missing'", "relationship", "error", True, "source_supplier_label", "Supplier assertion has no resolvable party mention."),
        (supplier, "award_supplier_assertion", "award_supplier_assertion_id", "joint_venture_unparsed", "source_joint_venture IS NOT NULL", "parsing", "warning", True, "source_joint_venture", "Joint-venture source value is preserved but not parsed."),
    ]
    selects = []
    for relation, record_type, record_id, code, condition, category, severity, blocking, observed, detail in specs:
        selects.append(f"""
        SELECT {issue_id(record_type, record_id, 'release_id', code)} AS issue_id,
               release_id, {literal(record_type)} AS record_type,
               {record_id} AS record_id, {literal(code)} AS issue_code,
               {literal(category)} AS issue_category,
               {literal(severity)} AS severity,
               {str(blocking).lower()} AS publication_blocking,
               cast({observed} AS VARCHAR) AS observed_value,
               {literal(detail)} AS detail,
               {literal('build_parquet')} AS detection_rule,
               {int(rules['identity_rules_version'])} AS rule_version
        FROM {relation} WHERE {condition}
        """)
    # UNION ALL + ORDER BY issue_id over ~14M sha256 keys buffers the whole
    # result set in memory before COPY can stream. Write each spec separately
    # (no ordering across specs; each part is ordered by issue_id), then
    # concatenate the parts — physical order is not part of this table's
    # contract (issue_id is the PK and consumers join on it).
    parts_dir = work_dir / "quality_issue_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in parts_dir.glob("part_*.parquet"):
        stale.unlink()
    for index, select in enumerate(selects):
        relation_name = specs[index][0]
        print(f"  quality part {index + 1}/{len(selects)} ({relation_name})", flush=True)
        copy_query(
            connection, select + " ORDER BY issue_id", parts_dir / f"part_{index:03d}.parquet"
        )
    glob = (parts_dir / "part_*.parquet").as_posix()
    # Per-spec parts are each issue_id-sorted, but concatenation scrambles
    # release_id clustering. Re-sort by release_id so release-scoped viewer
    # queries (child counts, summaries) prune row groups.
    unsorted = work_dir / "data_quality_issues_unsorted.parquet"
    copy_query(
        connection,
        f"SELECT * FROM read_parquet({literal(glob)})",
        unsorted,
    )
    copy_sorted(connection, unsorted, target, "release_id", work_dir)


def validate_core(connection, input_rows: int, work_dir: Path, output_dir: Path) -> dict:
    paths = {
        "release_index": work_dir / "release_index.parquet",
        "releases": output_dir / "releases.parquet",
        "contracting_processes": output_dir / "contracting_processes.parquet",
        "tenders": output_dir / "tenders.parquet",
        "tender_items": output_dir / "tender_items.parquet",
        "awards": output_dir / "awards.parquet",
        "contracts": output_dir / "contracts.parquet",
        "parties": output_dir / "parties.parquet",
        "party_roles": output_dir / "party_roles.parquet",
        "award_items": output_dir / "award_items.parquet",
        "award_suppliers": output_dir / "award_suppliers.parquet",
        "record_sources": output_dir / "record_sources.parquet",
        "data_quality_issues": output_dir / "data_quality_issues.parquet",
    }
    counts = {}
    duplicates = {}
    keys = {
        "release_index": "(_source_file_id, _source_row_number)",
        "releases": "release_id",
        "contracting_processes": "process_id",
        "tenders": "release_id",
        "tender_items": "(release_id, item_id)",
        "awards": "(release_id, award_id)",
        "contracts": "(release_id, contract_id)",
        "parties": "(release_id, party_id)",
        "party_roles": "(release_id, party_id, role)",
        "award_items": "(release_id, award_id, item_id)",
        "award_suppliers": "award_supplier_assertion_id",
        "record_sources": "(record_type, record_id, source_file_id, source_row_number)",
        "data_quality_issues": "issue_id",
    }
    for name, path in paths.items():
        if not path.exists():
            continue
        relation = f"read_parquet({literal(str(path))})"
        counts[name] = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
        duplicates[name] = connection.execute(
            f"SELECT count(*) - count(DISTINCT {keys[name]}) FROM {relation}"
        ).fetchone()[0]
    failures = [f"{name} duplicate primary keys" for name, count in duplicates.items() if count]
    if counts.get("release_index") != input_rows:
        failures.append("release index does not cover every input observation")
    foreign_keys = {}

    def missing_links(name: str, sql: str):
        value = connection.execute(sql).fetchone()[0]
        foreign_keys[name] = value
        if value:
            failures.append(f"{name} has {value} unresolved foreign keys")

    if paths["releases"].exists() and paths["contracting_processes"].exists():
        missing_links("release_process", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['releases']))}) c
          LEFT JOIN read_parquet({literal(str(paths['contracting_processes']))}) p
            USING (process_id) WHERE p.process_id IS NULL
        """)
    for child in ("tenders", "tender_items", "awards", "contracts", "parties"):
        if paths[child].exists() and paths["releases"].exists():
            missing_links(f"{child}_release", f"""
              SELECT count(*) FROM read_parquet({literal(str(paths[child]))}) c
              LEFT JOIN read_parquet({literal(str(paths['releases']))}) p
                USING (release_id) WHERE p.release_id IS NULL
            """)
    if paths["party_roles"].exists() and paths["parties"].exists():
        missing_links("party_role_party", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['party_roles']))}) c
          LEFT JOIN read_parquet({literal(str(paths['parties']))}) p
            USING (release_id, party_id) WHERE p.party_id IS NULL
        """)
    if paths["award_items"].exists() and paths["awards"].exists():
        missing_links("award_item_award", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['award_items']))}) c
          LEFT JOIN read_parquet({literal(str(paths['awards']))}) p
            USING (release_id, award_id) WHERE p.award_id IS NULL
        """)
    if paths["award_items"].exists() and paths["tender_items"].exists():
        missing_links("award_item_item", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['award_items']))}) c
          LEFT JOIN read_parquet({literal(str(paths['tender_items']))}) p
            USING (release_id, item_id) WHERE p.item_id IS NULL
        """)
    if paths["contracts"].exists() and paths["awards"].exists():
        missing_links("matched_contract_award", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['contracts']))}) c
          LEFT JOIN read_parquet({literal(str(paths['awards']))}) p
            USING (release_id, award_id)
          WHERE c.award_link_status = 'matched' AND p.award_id IS NULL
        """)
    if paths["award_suppliers"].exists() and paths["awards"].exists():
        missing_links("matched_supplier_award", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['award_suppliers']))}) c
          LEFT JOIN read_parquet({literal(str(paths['awards']))}) p
            USING (release_id, award_id)
          WHERE c.award_link_status = 'matched' AND p.award_id IS NULL
        """)
    if paths["award_suppliers"].exists() and paths["parties"].exists():
        missing_links("matched_supplier_party", f"""
          SELECT count(*) FROM read_parquet({literal(str(paths['award_suppliers']))}) c
          LEFT JOIN read_parquet({literal(str(paths['parties']))}) p
            USING (release_id, party_id)
          WHERE c.party_link_status = 'matched' AND p.party_id IS NULL
        """)
    if paths["record_sources"].exists():
        release_source_rows = connection.execute(f"""
          SELECT count(DISTINCT (source_file_id, source_row_number))
          FROM read_parquet({literal(str(paths['record_sources']))})
          WHERE record_type = 'release'
        """).fetchone()[0]
        if release_source_rows != input_rows:
            failures.append("release provenance does not cover every input observation")
        if paths["data_quality_issues"].exists():
            missing_links("quality_issue_source", f"""
              SELECT count(*) FROM read_parquet({literal(str(paths['data_quality_issues']))}) q
              LEFT JOIN (
                SELECT DISTINCT record_id FROM read_parquet({literal(str(paths['record_sources']))})
                WHERE record_type = 'data_quality_issue'
              ) s ON q.issue_id = s.record_id
              WHERE s.record_id IS NULL
            """)
    else:
        release_source_rows = None
    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "row_counts": counts,
        "duplicate_primary_keys": duplicates,
        "foreign_key_checks": foreign_keys,
        "release_source_observation_coverage": release_source_rows,
    }


def main():
    args = parse_args()
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    work_dir = args.work_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    rules_bytes = args.identity_rules.read_bytes()
    rules = json.loads(rules_bytes.decode("utf-8-sig"))
    codelist_bytes = args.codelist_mapping.read_bytes()
    codelists = json.loads(codelist_bytes.decode("utf-8-sig"))
    field_bytes = args.field_mapping.read_bytes()
    relation = source_relation(input_path, args.max_rows)
    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    spill_dir = work_dir / "duckdb_temp"
    spill_dir.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit = {literal(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {literal(str(spill_dir))}")
    connection.execute(
        f"SET max_temp_directory_size = {literal(args.max_temp_size)}"
    )
    try:
        input_rows = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
        index_path = work_dir / "release_index.parquet"
        if "release_index" in args.tables and (args.replace or not index_path.exists()):
            print("building release_index", flush=True)
            build_release_index(connection, relation, index_path, rules, work_dir)
        if not index_path.exists():
            raise RuntimeError("release_index is required; include it in --tables or reuse an existing one")
        consumers = [
            table for table in args.tables
            if table != "release_index" and not (output_dir / f"{table}.parquet").exists()
        ]
        if args.replace:
            consumers = [table for table in args.tables if table != "release_index"]
        if consumers:
            print("materializing indexed observations (chunked join)", flush=True)
            rows = materialize_indexed_rows(
                connection, relation, index_path, work_dir, input_rows,
                reuse=True,
            )
        else:
            rows = indexed_rows(relation, index_path)
        releases_path = output_dir / "releases.parquet"
        if "releases" in args.tables and (args.replace or not releases_path.exists()):
            print("building releases", flush=True)
            build_releases(connection, rows, releases_path)
        processes_path = output_dir / "contracting_processes.parquet"
        if "contracting_processes" in args.tables and (args.replace or not processes_path.exists()):
            if not releases_path.exists():
                raise RuntimeError("releases.parquet is required before contracting_processes")
            print("building contracting_processes", flush=True)
            build_processes(
                connection, rows, releases_path, processes_path,
                work_dir, args.process_partitions,
            )
        tenders_path = output_dir / "tenders.parquet"
        if "tenders" in args.tables and (args.replace or not tenders_path.exists()):
            print("building tenders", flush=True)
            build_tenders(connection, rows, tenders_path, codelists)
        builders = (
            ("tender_items", lambda path: build_tender_items(connection, rows, path, rules)),
            ("awards", lambda path: build_awards(connection, rows, path, rules, codelists)),
            ("contracts", lambda path: build_contracts(connection, rows, path, rules)),
            ("parties", lambda path: build_parties(connection, rows, path, rules)),
            ("party_roles", lambda path: build_party_roles(connection, rows, path, rules)),
            ("award_items", lambda path: build_award_items(connection, rows, path, rules)),
            ("award_suppliers", lambda path: build_award_suppliers(connection, rows, path, rules)),
        )
        for table, builder in builders:
            path = output_dir / f"{table}.parquet"
            if table in args.tables and (args.replace or not path.exists()):
                print(f"building {table}", flush=True)
                builder(path)
        quality_path = output_dir / "data_quality_issues.parquet"
        if "data_quality_issues" in args.tables and (args.replace or not quality_path.exists()):
            required = ("tenders", "tender_items", "awards", "contracts", "parties", "award_suppliers")
            missing = [name for name in required if not (output_dir / f"{name}.parquet").exists()]
            if missing:
                raise RuntimeError(f"data_quality_issues requires tables: {', '.join(missing)}")
            print("building data_quality_issues", flush=True)
            build_data_quality_issues(connection, output_dir, quality_path, rules, work_dir)
        sources_path = output_dir / "record_sources.parquet"
        if "record_sources" in args.tables and (args.replace or not sources_path.exists()):
            print("building record_sources", flush=True)
            build_record_sources(
                connection, rows, sources_path, rules, work_dir, quality_path,
                replace=args.replace,
            )
        report = validate_core(connection, input_rows, work_dir, output_dir)
    finally:
        connection.close()
    report.update({
        "truncated_for_test": bool(args.max_rows),
        "max_rows": args.max_rows,
        "identity_rules_sha256": hashlib.sha256(rules_bytes).hexdigest(),
        "field_mapping_sha256": hashlib.sha256(field_bytes).hexdigest(),
        "codelist_mapping_sha256": hashlib.sha256(codelist_bytes).hexdigest(),
    })
    report_path = work_dir / "core_validation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "pass":
        raise RuntimeError("core Parquet validation failed")


if __name__ == "__main__":
    main()
