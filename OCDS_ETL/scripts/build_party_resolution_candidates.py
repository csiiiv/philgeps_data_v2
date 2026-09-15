#!/usr/bin/env python3
"""Build traceable party-resolution candidates without merging party records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parties", type=Path, default=project / "outputs" / "parquet" / "parties.parquet")
    parser.add_argument("--roles", type=Path, default=project / "outputs" / "parquet" / "party_roles.parquet")
    parser.add_argument("--name-forms", type=Path, default=project / "outputs" / "parquet" / "party_name_forms.parquet")
    parser.add_argument("--record-sources", type=Path, default=project / "outputs" / "parquet" / "record_sources.parquet")
    parser.add_argument("--config", type=Path, default=project / "config" / "party_resolution.json")
    parser.add_argument("--output", type=Path, default=project / "outputs" / "parquet" / "party_resolution_candidates.parquet")
    parser.add_argument("--json-output", type=Path, default=project / "artifacts" / "party_resolution_profile.json")
    parser.add_argument("--markdown-output", type=Path, default=project / "artifacts" / "party_resolution_profile.md")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="8GB")
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def normalized(column: str) -> str:
    return (
        f"trim(regexp_replace(regexp_replace(lower(coalesce({column}, '')), "
        "'[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g'))"
    )


def rows(cursor):
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def render(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "# Party-resolution evidence profile",
        "",
        "This report describes candidate evidence only. No party mentions are merged and no canonical party IDs are assigned.",
        "",
        f"- Candidate groups: `{totals['candidate_groups']:,}`",
        f"- Candidate party mentions: `{totals['candidate_party_mentions']:,}`",
        f"- Candidate observed name forms: `{totals['candidate_name_forms']:,}`",
        f"- Resolution decisions marked unresolved: `{totals['unresolved_mentions']:,}`",
        "",
        "## Evidence statuses",
        "",
        "| Status | Groups | Party mentions | Meaning |",
        "|---|---:|---:|---|",
    ]
    descriptions = report["evidence_status_definitions"]
    for item in report["status_counts"]:
        lines.append(
            f"| `{item['evidence_status']}` | {item['candidate_groups']:,} | "
            f"{item['party_mentions']:,} | {descriptions[item['evidence_status']]} |"
        )
    lines.extend([
        "",
        "## Largest candidate groups",
        "",
        "| Candidate key | Status | Forms | Mentions | Locations | Example names |",
        "|---|---|---:|---:|---:|---|",
    ])
    for item in report["examples"]:
        names = "; ".join(value.replace("|", "\\|") for value in item["example_names"])
        lines.append(
            f"| `{item['legal_suffix_name_key']}` | `{item['evidence_status']}` | "
            f"{item['name_form_count']:,} | {item['party_mentions']:,} | "
            f"{item['distinct_location_count']:,} | {names} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- `corroborated_candidate` means a normalized location occurs under at least two observed name forms; it is not an automatic match.",
        "- `divergent_location_context` is not automatically a conflict because one organization can operate branches or offices.",
        "- Every row retains `release_id` and `party_id`, which resolve to source breadcrumbs through `record_sources.parquet`.",
        "",
    ])
    return "\n".join(lines)


def main():
    args = parse_args()
    paths = [
        args.parties.resolve(), args.roles.resolve(), args.name_forms.resolve(),
        args.record_sources.resolve(), args.config.resolve()
    ]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
    parties, roles, forms, record_sources, config_path = paths
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".staging.parquet")
    project = Path(__file__).resolve().parents[1]
    spill = project / "outputs" / ".build" / "party_resolution_temp"
    spill.mkdir(parents=True, exist_ok=True)

    location_key = (
        f"'country=' || {normalized('source_country')} "
        f"|| '|region=' || {normalized('source_region')} "
        f"|| '|province=' || {normalized('source_province')} "
        f"|| '|city=' || {normalized('source_city_municipality')}"
    )
    has_location = " OR ".join(
        f"{normalized(field)} <> ''" for field in (
            "source_country", "source_region", "source_province", "source_city_municipality"
        )
    )
    organization_key = (
        "'type=' || " + normalized("source_organization_type")
        + " || '|group=' || " + normalized("organization_type_grouped")
    )
    has_organization = (
        f"{normalized('source_organization_type')} <> '' OR "
        f"{normalized('organization_type_grouped')} <> ''"
    )

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {quote(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {quote(str(spill))}")
    try:
        connection.execute(f"""
          COPY (
            WITH candidate_forms AS (
              SELECT * FROM read_parquet({quote(str(forms))})
              WHERE has_candidate_alias
            ), role_agg AS (
              SELECT release_id, party_id, list_sort(list(DISTINCT role)) AS roles
              FROM read_parquet({quote(str(roles))}) GROUP BY release_id, party_id
            ), mentions AS (
              SELECT p.*, f.name_form_id, f.punctuation_name_key,
                     f.legal_suffix_name_key, f.rule_version AS name_rule_version,
                     f.has_legal_suffix_equivalent,
                     ({location_key}) AS location_key,
                     ({has_location}) AS has_location,
                     ({organization_key}) AS organization_context_key,
                     ({has_organization}) AS has_organization_context,
                     coalesce(r.roles, []::VARCHAR[]) AS roles
              FROM read_parquet({quote(str(parties))}) p
              JOIN candidate_forms f ON p.name = f.observed_name
              LEFT JOIN role_agg r USING (release_id, party_id)
            ), location_support AS (
              SELECT legal_suffix_name_key, location_key,
                     count(DISTINCT name_form_id) AS supported_name_forms
              FROM mentions WHERE has_location
              GROUP BY legal_suffix_name_key, location_key
            ), group_metrics AS (
              SELECT m.legal_suffix_name_key,
                     count(DISTINCT m.name_form_id) AS name_form_count,
                     count(*) AS party_mentions,
                     count(DISTINCT m.name_form_id) FILTER (WHERE m.has_location) AS forms_with_location,
                     count(DISTINCT m.location_key) FILTER (WHERE m.has_location) AS distinct_location_count,
                     count(DISTINCT m.organization_context_key) FILTER (WHERE m.has_organization_context) AS distinct_organization_context_count,
                     count(DISTINCT s.location_key) FILTER (WHERE s.supported_name_forms >= 2) AS shared_location_count,
                     bool_or(m.has_legal_suffix_equivalent) AS uses_legal_suffix_equivalence
              FROM mentions m
              LEFT JOIN location_support s
                ON m.legal_suffix_name_key = s.legal_suffix_name_key
               AND m.location_key = s.location_key
              GROUP BY m.legal_suffix_name_key
            ), classified AS (
              SELECT *,
                CASE
                  WHEN shared_location_count > 0 THEN 'corroborated_candidate'
                  WHEN forms_with_location = 0 THEN 'name_only'
                  WHEN forms_with_location < name_form_count THEN 'partial_context'
                  ELSE 'divergent_location_context'
                END AS evidence_status,
                CASE WHEN uses_legal_suffix_equivalence
                     THEN 'legal_suffix_equivalence'
                     ELSE 'punctuation_or_case'
                END AS candidate_basis
              FROM group_metrics
            )
            SELECT
              'pgrm_' || sha256(m.release_id || '|' || m.party_id || '|' || {quote(config['rule_version'])}) AS resolution_candidate_id,
              'pgrg_' || sha256(m.legal_suffix_name_key || '|' || {quote(config['rule_version'])}) AS candidate_group_id,
              m.release_id, m.party_id, m.name_form_id, m.name AS observed_name,
              m.name_key AS conservative_name_key, m.punctuation_name_key,
              m.legal_suffix_name_key, m.roles,
              m.source_country, m.source_region, m.source_province,
              m.source_city_municipality, m.location_key, m.has_location,
              m.source_organization_type, m.organization_type_grouped,
              m.organization_context_key, m.has_organization_context,
              c.candidate_basis, c.evidence_status,
              c.name_form_count AS group_name_form_count,
              c.party_mentions AS group_party_mentions,
              c.forms_with_location AS group_forms_with_location,
              c.distinct_location_count AS group_distinct_location_count,
              c.shared_location_count AS group_shared_location_count,
              c.distinct_organization_context_count AS group_distinct_organization_context_count,
              m.name_rule_version, {quote(config['rule_version'])} AS resolution_rule_version,
              'unresolved' AS resolution_status,
              false AS automatic_merge_allowed
            FROM mentions m JOIN classified c USING (legal_suffix_name_key)
            ORDER BY resolution_candidate_id
          ) TO {quote(str(staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        total, unique_ids, unique_parties, groups, unresolved = connection.execute(f"""
          SELECT count(*), count(DISTINCT resolution_candidate_id),
                 count(DISTINCT release_id || '|' || party_id),
                 count(DISTINCT candidate_group_id),
                 count(*) FILTER (WHERE resolution_status = 'unresolved')
          FROM read_parquet({quote(str(staging))})
        """).fetchone()
        expected = connection.execute(f"""
          SELECT coalesce(sum(party_mentions), 0)
          FROM read_parquet({quote(str(forms))}) WHERE has_candidate_alias
        """).fetchone()[0]
        candidate_name_forms = connection.execute(f"""
          SELECT count(DISTINCT name_form_id)
          FROM read_parquet({quote(str(staging))})
        """).fetchone()[0]
        missing_parties = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(staging))}) c
          LEFT JOIN read_parquet({quote(str(parties))}) p
            USING (release_id, party_id)
          WHERE p.party_id IS NULL
        """).fetchone()[0]
        missing_name_forms = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(staging))}) c
          LEFT JOIN read_parquet({quote(str(forms))}) f USING (name_form_id)
          WHERE f.name_form_id IS NULL
        """).fetchone()[0]
        missing_breadcrumbs = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(staging))}) c
          WHERE NOT EXISTS (
            SELECT 1 FROM read_parquet({quote(str(record_sources))}) s
            WHERE s.record_type = 'party'
              AND s.release_id = c.release_id AND s.record_id = c.party_id
          )
        """).fetchone()[0]
        if (total != expected or unique_ids != total or unique_parties != total
                or unresolved != total or missing_parties or missing_name_forms
                or missing_breadcrumbs):
            raise RuntimeError(
                f"candidate validation failed: rows={total}, expected={expected}, "
                f"ids={unique_ids}, parties={unique_parties}, unresolved={unresolved}, "
                f"missing_parties={missing_parties}, missing_name_forms={missing_name_forms}, "
                f"missing_breadcrumbs={missing_breadcrumbs}"
            )
        status_counts = rows(connection.execute(f"""
          SELECT evidence_status, count(DISTINCT candidate_group_id) AS candidate_groups,
                 count(*) AS party_mentions
          FROM read_parquet({quote(str(staging))})
          GROUP BY evidence_status ORDER BY candidate_groups DESC, evidence_status
        """))
        examples = rows(connection.execute(f"""
          SELECT legal_suffix_name_key, any_value(evidence_status) AS evidence_status,
                 max(group_name_form_count) AS name_form_count,
                 count(*) AS party_mentions,
                 max(group_distinct_location_count) AS distinct_location_count,
                 list_slice(list_sort(list(DISTINCT observed_name)), 1, 8) AS example_names
          FROM read_parquet({quote(str(staging))})
          GROUP BY legal_suffix_name_key
          ORDER BY party_mentions DESC, legal_suffix_name_key LIMIT 30
        """))
    finally:
        connection.close()

    staging.replace(output)
    report = {
        "input": {
            "parties": str(parties), "party_roles": str(roles),
            "party_name_forms": str(forms), "record_sources": str(record_sources)
        },
        "output": str(output),
        "rule_version": config["rule_version"],
        "totals": {
            "candidate_groups": groups,
            "candidate_party_mentions": total,
            "candidate_name_forms": candidate_name_forms,
            "unresolved_mentions": unresolved,
        },
        "evidence_status_definitions": config["evidence_statuses"],
        "status_counts": status_counts,
        "examples": examples,
        "validation": {
            "status": "pass", "expected_rows": expected,
            "unique_candidate_ids": unique_ids, "unique_party_mentions": unique_parties,
            "missing_party_foreign_keys": missing_parties,
            "missing_name_form_foreign_keys": missing_name_forms,
            "missing_source_breadcrumbs": missing_breadcrumbs,
            "automatic_merges": 0
        }
    }
    args.json_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.resolve().write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown_output.resolve().write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": "pass", **report["totals"]}, indent=2))


if __name__ == "__main__":
    main()
