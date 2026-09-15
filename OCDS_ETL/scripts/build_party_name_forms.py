#!/usr/bin/env python3
"""Build the compact, source-preserving party-name normalization dimension."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parties", type=Path, default=project / "outputs" / "parquet" / "parties.parquet")
    parser.add_argument("--config", type=Path, default=project / "config" / "party_name_normalization.json")
    parser.add_argument("--output", type=Path, default=project / "outputs" / "parquet" / "party_name_forms.parquet")
    parser.add_argument("--validation-output", type=Path, default=project / "artifacts" / "party_name_forms_validation.json")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="8GB")
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def punctuation_key(column: str) -> str:
    return (
        f"trim(regexp_replace(regexp_replace(lower({column}), "
        "'[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g'))"
    )


def suffix_key(column: str, equivalences: dict[str, str]) -> str:
    result = column
    for full, short in equivalences.items():
        result = f"regexp_replace({result}, ' {full}$', ' {short}')"
    return result


def main():
    args = parse_args()
    parties = args.parties.resolve()
    config_path = args.config.resolve()
    output = args.output.resolve()
    if not parties.exists():
        raise FileNotFoundError(parties)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    suffix_step = next(
        step for step in config["steps"]
        if step["operation"] == "canonicalize_terminal_legal_suffix"
    )
    punctuation = punctuation_key("name")
    legal = suffix_key("punctuation_name_key", suffix_step["equivalences"])
    project = Path(__file__).resolve().parents[1]
    spill = project / "outputs" / ".build" / "party_name_forms_temp"
    spill.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".staging.parquet")

    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {quote(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {quote(str(spill))}")
    try:
        connection.execute(f"""
          COPY (
            WITH forms AS (
              SELECT name AS observed_name,
                     name_key AS conservative_name_key,
                     {punctuation} AS punctuation_name_key,
                     count(*) AS party_mentions,
                     count(DISTINCT release_id) AS release_count
              FROM read_parquet({quote(str(parties))})
              WHERE name IS NOT NULL
              GROUP BY name, name_key
            ), keyed AS (
              SELECT *, {legal} AS legal_suffix_name_key FROM forms
            ), groups AS (
              SELECT legal_suffix_name_key,
                     count(DISTINCT punctuation_name_key) AS legal_suffix_variant_count,
                     count(DISTINCT conservative_name_key) AS conservative_variant_count
              FROM keyed WHERE legal_suffix_name_key <> ''
              GROUP BY legal_suffix_name_key
            )
            SELECT 'pgnf_' || sha256(observed_name) AS name_form_id,
                   observed_name, conservative_name_key, punctuation_name_key,
                   legal_suffix_name_key, {quote(config['rule_version'])} AS rule_version,
                   party_mentions, release_count,
                   groups.conservative_variant_count,
                   groups.legal_suffix_variant_count,
                   groups.legal_suffix_variant_count > 1 AS has_legal_suffix_equivalent,
                   groups.conservative_variant_count > 1 AS has_candidate_alias
            FROM keyed LEFT JOIN groups USING (legal_suffix_name_key)
            ORDER BY name_form_id
          ) TO {quote(str(staging))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        total, distinct_ids, empty_keys = connection.execute(f"""
          SELECT count(*), count(DISTINCT name_form_id),
                 count(*) FILTER (WHERE legal_suffix_name_key = '')
          FROM read_parquet({quote(str(staging))})
        """).fetchone()
        distinct_names = connection.execute(
            f"SELECT count(DISTINCT name) FROM read_parquet({quote(str(parties))}) WHERE name IS NOT NULL"
        ).fetchone()[0]
        if total != distinct_names or distinct_ids != total or empty_keys:
            raise RuntimeError(
                f"party-name validation failed: rows={total}, names={distinct_names}, "
                f"distinct_ids={distinct_ids}, empty_keys={empty_keys}"
            )
    finally:
        connection.close()
    staging.replace(output)
    report = {
        "status": "pass", "output": str(output), "rows": total,
        "distinct_name_form_ids": distinct_ids, "rule_version": config["rule_version"]
    }
    validation_output = args.validation_output.resolve()
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
