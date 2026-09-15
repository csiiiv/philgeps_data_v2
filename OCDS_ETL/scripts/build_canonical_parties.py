#!/usr/bin/env python3
"""Build provisional canonical party clusters and their supported aliases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=project / "outputs" / "parquet" / "party_resolution_candidates.parquet")
    parser.add_argument("--record-sources", type=Path, default=project / "outputs" / "parquet" / "record_sources.parquet")
    parser.add_argument("--config", type=Path, default=project / "config" / "party_resolution.json")
    parser.add_argument("--canonical-output", type=Path, default=project / "outputs" / "parquet" / "canonical_parties.parquet")
    parser.add_argument("--aliases-output", type=Path, default=project / "outputs" / "parquet" / "party_aliases.parquet")
    parser.add_argument("--report", type=Path, default=project / "artifacts" / "canonical_party_validation.json")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="8GB")
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main():
    args = parse_args()
    candidates = args.candidates.resolve()
    record_sources = args.record_sources.resolve()
    config_path = args.config.resolve()
    for path in (candidates, record_sources, config_path):
        if not path.exists():
            raise FileNotFoundError(path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    promotion = config["provisional_promotion"]
    rule_version = promotion["rule_version"]
    canonical_prefix = promotion["canonical_party_id_prefix"]
    canonical_output = args.canonical_output.resolve()
    aliases_output = args.aliases_output.resolve()
    canonical_output.parent.mkdir(parents=True, exist_ok=True)
    canonical_staging = canonical_output.with_suffix(".staging.parquet")
    aliases_staging = aliases_output.with_suffix(".staging.parquet")
    project = Path(__file__).resolve().parents[1]
    spill = project / "outputs" / ".build" / "canonical_party_temp"
    spill.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {quote(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {quote(str(spill))}")
    try:
        connection.execute(f"""
          CREATE TEMP TABLE eligible_groups AS
          SELECT candidate_group_id,
                 any_value(legal_suffix_name_key) AS legal_suffix_name_key,
                 max(group_name_form_count) AS name_form_count,
                 max(group_party_mentions) AS total_candidate_mentions,
                 max(group_distinct_location_count) AS location_count,
                 max(group_distinct_organization_context_count) AS organization_context_count,
                 bool_or(list_contains(roles, 'supplier')) AS has_supplier_role,
                 bool_or(list_contains(roles, 'procuringEntity') OR list_contains(roles, 'buyer_candidate')) AS has_public_role
          FROM read_parquet({quote(str(candidates))})
          GROUP BY candidate_group_id
          HAVING any_value(candidate_basis) = 'punctuation_or_case'
             AND any_value(evidence_status) = 'corroborated_candidate'
             AND max(group_forms_with_location) = max(group_name_form_count)
             AND max(group_distinct_location_count) = 1
             AND max(group_distinct_organization_context_count) <= 1
             AND NOT (
               bool_or(list_contains(roles, 'supplier'))
               AND bool_or(list_contains(roles, 'procuringEntity') OR list_contains(roles, 'buyer_candidate'))
             )
        """)
        connection.execute(f"""
          CREATE TEMP TABLE supported_mentions AS
          SELECT c.*,
                 CASE WHEN e.has_supplier_role THEN 'supplier' ELSE 'public_body' END AS role_family,
                 {quote(canonical_prefix + '_')} || sha256(c.candidate_group_id || '|' || c.location_key || '|' || {quote(rule_version)}) AS canonical_party_id
          FROM read_parquet({quote(str(candidates))}) c
          JOIN eligible_groups e USING (candidate_group_id)
          WHERE c.has_location
        """)
        connection.execute(f"""
          COPY (
            WITH name_counts AS (
              SELECT canonical_party_id, observed_name, count(*) AS mention_count,
                     row_number() OVER (
                       PARTITION BY canonical_party_id
                       ORDER BY count(*) DESC, observed_name
                     ) AS preference_rank
              FROM supported_mentions GROUP BY canonical_party_id, observed_name
            ), preferred AS (
              SELECT canonical_party_id, observed_name AS preferred_name
              FROM name_counts WHERE preference_rank = 1
            )
            SELECT s.canonical_party_id, p.preferred_name,
                   any_value(s.legal_suffix_name_key) AS candidate_name_key,
                   any_value(s.location_key) AS normalized_location_key,
                   any_value(s.role_family) AS role_family,
                   min(nullif(s.organization_context_key, 'type=|group=')) AS normalized_organization_context,
                   list_sort(list(DISTINCT s.observed_name)) AS observed_name_forms,
                   count(DISTINCT s.name_form_id) AS supported_name_form_count,
                   count(*) AS supporting_party_mentions,
                   max(s.group_party_mentions) AS total_candidate_mentions,
                   max(s.group_party_mentions) - count(*) AS unresolved_mentions,
                   {quote(rule_version)} AS promotion_rule_version,
                   'provisional' AS identity_status,
                   'punctuation_and_shared_location' AS match_method,
                   NULL::VARCHAR AS official_identifier_scheme,
                   NULL::VARCHAR AS official_identifier,
                   ['provisional_identity_no_official_identifier']::VARCHAR[] AS identity_quality_flags
            FROM supported_mentions s JOIN preferred p USING (canonical_party_id)
            GROUP BY s.canonical_party_id, p.preferred_name
            ORDER BY s.canonical_party_id
          ) TO {quote(str(canonical_staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        connection.execute(f"""
          COPY (
            SELECT
              'pgaa_' || sha256(s.canonical_party_id || '|' || s.release_id || '|' || s.party_id) AS party_alias_id,
              s.canonical_party_id, s.release_id, s.party_id, s.name_form_id,
              s.observed_name, s.location_key AS normalized_location_key,
              s.roles, s.role_family, s.evidence_status,
              {quote(rule_version)} AS promotion_rule_version,
              'provisional_match' AS alias_status,
              'punctuation_and_shared_location' AS match_method,
              false AS official_identifier_verified
            FROM supported_mentions s
            ORDER BY party_alias_id
          ) TO {quote(str(aliases_staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        canonical_count, canonical_ids = connection.execute(f"""
          SELECT count(*), count(DISTINCT canonical_party_id)
          FROM read_parquet({quote(str(canonical_staging))})
        """).fetchone()
        alias_count, alias_ids, alias_parties, missing_location = connection.execute(f"""
          SELECT count(*), count(DISTINCT party_alias_id),
                 count(DISTINCT release_id || '|' || party_id),
                 count(*) FILTER (WHERE normalized_location_key = 'country=|region=|province=|city=')
          FROM read_parquet({quote(str(aliases_staging))})
        """).fetchone()
        missing_canonical = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(aliases_staging))}) a
          LEFT JOIN read_parquet({quote(str(canonical_staging))}) c USING (canonical_party_id)
          WHERE c.canonical_party_id IS NULL
        """).fetchone()[0]
        missing_breadcrumbs = connection.execute(f"""
          SELECT count(*) FROM read_parquet({quote(str(aliases_staging))}) a
          WHERE NOT EXISTS (
            SELECT 1 FROM read_parquet({quote(str(record_sources))}) s
            WHERE s.record_type = 'party'
              AND s.release_id = a.release_id AND s.record_id = a.party_id
          )
        """).fetchone()[0]
        if (canonical_count != canonical_ids or alias_count != alias_ids
                or alias_count != alias_parties or missing_location
                or missing_canonical or missing_breadcrumbs):
            raise RuntimeError(
                "canonical-party validation failed: "
                f"canonical={canonical_count}/{canonical_ids}, aliases={alias_count}/{alias_ids}/{alias_parties}, "
                f"missing_location={missing_location}, missing_canonical={missing_canonical}, "
                f"missing_breadcrumbs={missing_breadcrumbs}"
            )
        unresolved_mentions = connection.execute(f"""
          SELECT coalesce(sum(unresolved_mentions), 0)
          FROM read_parquet({quote(str(canonical_staging))})
        """).fetchone()[0]
    finally:
        connection.close()

    canonical_staging.replace(canonical_output)
    aliases_staging.replace(aliases_output)
    report = {
        "status": "pass",
        "identity_status": promotion["identity_status"],
        "promotion_rule_version": rule_version,
        "canonical_parties": canonical_count,
        "supported_alias_mentions": alias_count,
        "unresolved_mentions_in_eligible_groups": unresolved_mentions,
        "validation": {
            "unique_canonical_ids": canonical_ids,
            "unique_alias_ids": alias_ids,
            "unique_aliased_party_mentions": alias_parties,
            "aliases_without_location": missing_location,
            "missing_canonical_foreign_keys": missing_canonical,
            "missing_source_breadcrumbs": missing_breadcrumbs,
            "official_identifiers_verified": 0
        },
        "warning": promotion["publication_policy"]
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
