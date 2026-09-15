#!/usr/bin/env python3
"""Build the preferred-release process index and compact multi-release history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processes", type=Path, default=project / "outputs" / "parquet" / "contracting_processes.parquet")
    parser.add_argument("--releases", type=Path, default=project / "outputs" / "parquet" / "releases.parquet")
    parser.add_argument("--config", type=Path, default=project / "config" / "compilation.json")
    parser.add_argument("--compiled-output", type=Path, default=project / "outputs" / "parquet" / "compiled_processes.parquet")
    parser.add_argument("--history-output", type=Path, default=project / "outputs" / "parquet" / "process_release_history.parquet")
    parser.add_argument("--json-output", type=Path, default=project / "artifacts" / "compilation_validation.json")
    parser.add_argument("--markdown-output", type=Path, default=project / "artifacts" / "compilation_profile.md")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="8GB")
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def rows(cursor):
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def render(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "# Compiled process profile",
        "",
        "The compiled index selects one preferred release for convenient analysis while retaining all releases and provenance.",
        "",
        f"- Contracting processes: `{counts['processes']:,}`",
        f"- Releases: `{counts['releases']:,}`",
        f"- Multi-release processes: `{counts['multi_release_processes']:,}`",
        f"- Releases in compact history: `{counts['history_releases']:,}`",
        f"- Same-date release ties: `{counts['same_date_ties']:,}`",
        f"- Preferred IDs differing from the base latest ID: `{counts['preferred_differs_from_base_latest']:,}`",
        "",
        "## Preferred-selection basis",
        "",
        "| Basis | Processes |",
        "|---|---:|",
    ]
    for item in report["selection_basis_counts"]:
        lines.append(f"| `{item['selection_basis']}` | {item['processes']:,} |")
    lines.extend([
        "",
        "## Multi-release examples",
        "",
        "| Process ID | Release count | Preferred release | Date | Basis |",
        "|---|---:|---|---|---|",
    ])
    for item in report["examples"]:
        date = str(item["preferred_release_date"]) if item["preferred_release_date"] is not None else ""
        lines.append(
            f"| `{item['process_id']}` | {item['release_count']:,} | "
            f"`{item['preferred_release_id']}` | {date} | `{item['selection_basis']}` |"
        )
    lines.extend([
        "",
        "All alternate release IDs remain in `compiled_processes.parquet`; detailed ordering for multi-release processes is in `process_release_history.parquet`.",
        "",
    ])
    return "\n".join(lines)


def main():
    args = parse_args()
    processes = args.processes.resolve()
    releases = args.releases.resolve()
    config_path = args.config.resolve()
    for path in (processes, releases, config_path):
        if not path.exists():
            raise FileNotFoundError(path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    rule_version = config["rule_version"]
    compiled_output = args.compiled_output.resolve()
    history_output = args.history_output.resolve()
    compiled_output.parent.mkdir(parents=True, exist_ok=True)
    compiled_staging = compiled_output.with_suffix(".staging.parquet")
    history_staging = history_output.with_suffix(".staging.parquet")
    project = Path(__file__).resolve().parents[1]
    spill = project / "outputs" / ".build" / "compilation_temp"
    spill.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {quote(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {quote(str(spill))}")
    try:
        connection.execute(f"""
          CREATE TEMP TABLE multi_process_ids AS
          SELECT process_id FROM read_parquet({quote(str(processes))})
          WHERE release_count > 1
        """)
        connection.execute(f"""
          CREATE TEMP TABLE ranked_multi_releases AS
          SELECT r.*,
            4 * cast(has_contract AS INTEGER)
              + 2 * cast(has_award AS INTEGER)
              + cast(has_tender AS INTEGER) AS lifecycle_score,
            row_number() OVER (
              PARTITION BY process_id
              ORDER BY release_date DESC NULLS LAST,
                       has_contract DESC, has_award DESC, has_tender DESC,
                       supporting_source_files DESC,
                       supporting_observation_rows DESC,
                       release_id DESC
            ) AS preference_rank,
            row_number() OVER (
              PARTITION BY process_id
              ORDER BY release_date ASC NULLS LAST, release_id ASC
            ) AS chronological_rank,
            count(*) OVER (PARTITION BY process_id, release_date) AS same_date_release_count,
            lag(content_hash) OVER (
              PARTITION BY process_id ORDER BY release_date ASC NULLS LAST, release_id ASC
            ) AS previous_content_hash
          FROM read_parquet({quote(str(releases))}) r
          JOIN multi_process_ids m USING (process_id)
        """)
        connection.execute("""
          CREATE TEMP TABLE multi_aggregated AS
          SELECT process_id, count(*) AS release_count,
                 min(release_date) AS first_release_date,
                 max(release_date) AS latest_release_date,
                 count(DISTINCT content_hash) AS distinct_content_hash_count,
                 bool_or(same_date_release_count > 1) AS has_release_date_tie,
                 bool_or(has_tender) AS any_release_has_tender,
                 bool_or(has_award) AS any_release_has_award,
                 bool_or(has_contract) AS any_release_has_contract,
                 min(lifecycle_score) AS min_lifecycle_score,
                 max(lifecycle_score) AS max_lifecycle_score,
                 min(supporting_source_files) AS min_source_files,
                 max(supporting_source_files) AS max_source_files,
                 min(supporting_observation_rows) AS min_observation_rows,
                 max(supporting_observation_rows) AS max_observation_rows,
                 list(release_id ORDER BY release_date ASC NULLS LAST, release_id ASC)
                   AS ordered_release_ids
          FROM ranked_multi_releases GROUP BY process_id
        """)
        connection.execute(f"""
          COPY (
            WITH preferred_multi AS (
              SELECT * FROM ranked_multi_releases WHERE preference_rank = 1
            ), selected AS (
              SELECT p.*,
                     coalesce(pm.release_id, p.latest_release_id) AS selected_release_id
              FROM read_parquet({quote(str(processes))}) p
              LEFT JOIN preferred_multi pm USING (process_id)
            )
            SELECT p.process_id, pr.release_id AS preferred_release_id,
                   pr.release_date AS preferred_release_date,
                   pr.release_date_basis AS preferred_release_date_basis,
                   CASE
                     WHEN p.release_count = 1 THEN 'only_release'
                     WHEN NOT a.has_release_date_tie THEN 'latest_release_date'
                     WHEN a.max_lifecycle_score > a.min_lifecycle_score
                       THEN 'same_date_lifecycle_completeness'
                     WHEN a.max_source_files > a.min_source_files
                       THEN 'same_date_source_coverage'
                     WHEN a.max_observation_rows > a.min_observation_rows
                       THEN 'same_date_observation_coverage'
                     ELSE 'same_date_deterministic_tiebreak'
                   END AS selection_basis,
                   p.release_count,
                   coalesce(list_filter(a.ordered_release_ids, x -> x <> pr.release_id), []::VARCHAR[])
                     AS alternate_release_ids,
                   p.release_count > 1 AS has_multiple_releases,
                   coalesce(a.has_release_date_tie, false) AS has_release_date_tie,
                   coalesce(a.distinct_content_hash_count, 1) AS distinct_content_hash_count,
                   {quote(rule_version)} AS compilation_rule_version,
                   list_concat(
                     p.process_quality_flags,
                     list_filter([
                       CASE WHEN p.release_count > 1 THEN 'multiple_releases' END,
                       CASE WHEN coalesce(a.has_release_date_tie, false) THEN 'release_date_tie_resolved' END,
                       CASE WHEN coalesce(a.distinct_content_hash_count, 1) > 1 THEN 'release_content_changed' END,
                       CASE WHEN pr.release_date IS NULL THEN 'preferred_release_date_missing' END
                     ], x -> x IS NOT NULL)
                   ) AS compilation_quality_flags
            FROM selected p
            JOIN read_parquet({quote(str(releases))}) pr
              ON p.selected_release_id = pr.release_id
            LEFT JOIN multi_aggregated a ON p.process_id = a.process_id
            ORDER BY p.process_id
          ) TO {quote(str(compiled_staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        connection.execute(f"""
          COPY (
            SELECT process_id, release_id, release_date, release_date_basis,
                   chronological_rank, preference_rank,
                   preference_rank = 1 AS is_preferred,
                   same_date_release_count > 1 AS has_same_date_peer,
                   has_tender, has_award, has_contract,
                   supporting_observation_rows, supporting_source_files,
                   source_file_ids, content_hash,
                   previous_content_hash IS NOT NULL
                     AND previous_content_hash <> content_hash AS content_changed_from_previous,
                   {quote(rule_version)} AS compilation_rule_version
            FROM ranked_multi_releases
            ORDER BY process_id, chronological_rank
          ) TO {quote(str(history_staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        process_count, process_ids, preferred_ids, missing_preferred, bad_alternates = connection.execute(f"""
          SELECT count(*), count(DISTINCT process_id), count(DISTINCT preferred_release_id),
                 count(*) FILTER (WHERE preferred_release_id IS NULL),
                 count(*) FILTER (WHERE len(alternate_release_ids) <> release_count - 1)
          FROM read_parquet({quote(str(compiled_staging))})
        """).fetchone()
        expected_processes = connection.execute(
            f"SELECT count(*) FROM read_parquet({quote(str(processes))})"
        ).fetchone()[0]
        release_count = connection.execute(
            f"SELECT count(*) FROM read_parquet({quote(str(releases))})"
        ).fetchone()[0]
        missing_release_fk = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(compiled_staging))}) c
          LEFT JOIN read_parquet({quote(str(releases))}) r
            ON c.preferred_release_id = r.release_id
          WHERE r.release_id IS NULL
        """).fetchone()[0]
        history_count, history_processes, history_preferred = connection.execute(f"""
          SELECT count(*), count(DISTINCT process_id),
                 count(*) FILTER (WHERE is_preferred)
          FROM read_parquet({quote(str(history_staging))})
        """).fetchone()
        multi_processes = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(compiled_staging))})
          WHERE has_multiple_releases
        """).fetchone()[0]
        ties = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(compiled_staging))})
          WHERE has_release_date_tie
        """).fetchone()[0]
        preferred_differs = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(compiled_staging))}) c
          JOIN read_parquet({quote(str(processes))}) p USING (process_id)
          WHERE c.preferred_release_id <> p.latest_release_id
        """).fetchone()[0]
        if (process_count != expected_processes or process_ids != process_count
                or preferred_ids != process_count or missing_preferred
                or bad_alternates or missing_release_fk
                or history_processes != multi_processes
                or history_preferred != multi_processes):
            raise RuntimeError(
                "compilation validation failed: "
                f"processes={process_count}/{expected_processes}/{process_ids}, "
                f"preferred={preferred_ids}, missing={missing_preferred}, "
                f"bad_alternates={bad_alternates}, release_fk={missing_release_fk}, "
                f"history={history_count}/{history_processes}/{history_preferred}, multi={multi_processes}"
            )
        selection_counts = rows(connection.execute(f"""
          SELECT selection_basis, count(*) AS processes
          FROM read_parquet({quote(str(compiled_staging))})
          GROUP BY selection_basis ORDER BY processes DESC
        """))
        examples = rows(connection.execute(f"""
          SELECT process_id, release_count, preferred_release_id,
                 preferred_release_date, selection_basis
          FROM read_parquet({quote(str(compiled_staging))})
          WHERE has_multiple_releases
          ORDER BY release_count DESC, process_id LIMIT 20
        """))
    finally:
        connection.close()

    compiled_staging.replace(compiled_output)
    history_staging.replace(history_output)
    report = {
        "status": "pass",
        "rule_version": rule_version,
        "counts": {
            "processes": process_count, "releases": release_count,
            "multi_release_processes": multi_processes,
            "history_releases": history_count, "same_date_ties": ties,
            "preferred_differs_from_base_latest": preferred_differs
        },
        "selection_basis_counts": selection_counts,
        "validation": {
            "unique_process_ids": process_ids,
            "unique_preferred_release_ids": preferred_ids,
            "missing_preferred_release_foreign_keys": missing_release_fk,
            "bad_alternate_release_counts": bad_alternates,
            "history_processes": history_processes,
            "history_preferred_rows": history_preferred
        },
        "examples": examples
    }
    args.json_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.resolve().write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    args.markdown_output.resolve().write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": "pass", **report["counts"]}, indent=2))


if __name__ == "__main__":
    main()
