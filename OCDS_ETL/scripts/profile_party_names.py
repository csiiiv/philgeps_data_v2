#!/usr/bin/env python3
"""Profile conservative and legal-suffix party-name normalization candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def parse_args():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parties",
        type=Path,
        default=project / "outputs" / "parquet" / "parties.parquet",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=project / "artifacts" / "party_name_profile.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=project / "artifacts" / "party_name_profile.md",
    )
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="8GB")
    parser.add_argument("--example-limit", type=int, default=50)
    return parser.parse_args()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def punctuation_key(column: str) -> str:
    return (
        f"trim(regexp_replace("
        f"regexp_replace(lower({column}), '[^a-z0-9]+', ' ', 'g'), "
        "' +', ' ', 'g'))"
    )


def lexical_key(column: str) -> str:
    result = punctuation_key(column)
    for full, short in (
        ("incorporated", "inc"),
        ("corporation", "corp"),
        ("company", "co"),
        ("limited", "ltd"),
    ):
        result = f"regexp_replace({result}, ' {full}$', ' {short}')"
    return f"trim(regexp_replace({result}, ' +', ' ', 'g'))"


def rows(cursor):
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def render(profile: dict) -> str:
    overview = profile["overview"]
    lines = [
        "# Party-name normalization profile",
        "",
        "This profile tests a candidate lexical key. It does not alter source "
        "names and does not assert legal-entity identity.",
        "",
        f"- Party mentions: `{overview['party_mentions']:,}`",
        f"- Distinct source names: `{overview['distinct_source_names']:,}`",
        f"- Distinct conservative keys: `{overview['distinct_conservative_keys']:,}`",
        f"- Distinct punctuation-folded keys: `{overview['distinct_punctuation_keys']:,}`",
        f"- Distinct candidate lexical keys: `{overview['distinct_lexical_keys']:,}`",
        f"- Candidate keys merging multiple conservative keys: `{overview['candidate_merge_groups']:,}`",
        f"- Punctuation-only candidate groups: `{overview['punctuation_candidate_groups']:,}`",
        f"- Legal-suffix equivalence candidate groups: `{overview['legal_suffix_candidate_groups']:,}`",
        f"- Mentions in candidate merge groups: `{overview['mentions_in_candidate_merge_groups']:,}`",
        "",
        "## Legal suffix observations",
        "",
        "| Suffix family | Distinct names | Party mentions |",
        "|---|---:|---:|",
    ]
    for item in profile["suffixes"]:
        lines.append(
            f"| `{item['suffix_family']}` | {item['distinct_names']:,} | "
            f"{item['party_mentions']:,} |"
        )
    lines.extend(
        [
            "",
            "## Largest candidate merge groups",
            "",
            "These are review candidates, not approved merges.",
            "",
            "| Candidate key | Conservative keys | Spellings | Mentions | Example names |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for item in profile["candidate_merge_examples"]:
        examples = "; ".join(str(value).replace("|", "\\|") for value in item["example_names"])
        key = item["lexical_key"].replace("|", "\\|")
        lines.append(
            f"| `{key}` | {item['conservative_keys']:,} | "
            f"{item['source_spellings']:,} | {item['party_mentions']:,} | {examples} |"
        )
    lines.extend(
        [
            "",
            "## Legal-suffix equivalence examples",
            "",
            "These groups merge only after canonicalizing a terminal legal suffix.",
            "",
            "| Candidate key | Punctuation keys | Spellings | Mentions | Example names |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for item in profile["legal_suffix_examples"]:
        examples = "; ".join(str(value).replace("|", "\\|") for value in item["example_names"])
        key = item["lexical_key"].replace("|", "\\|")
        lines.append(
            f"| `{key}` | {item['punctuation_keys']:,} | "
            f"{item['source_spellings']:,} | {item['party_mentions']:,} | {examples} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Punctuation folding and legal-suffix abbreviation produce candidate "
            "keys only.",
            "- `Inc.` and `Incorporated` equivalence is useful matching evidence but "
            "does not prove two mentions are the same registered organization.",
            "- Address, official identifiers, roles, and process context must be "
            "evaluated before assigning a canonical party cluster.",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    args = parse_args()
    parties = args.parties.resolve()
    if not parties.exists():
        raise FileNotFoundError(parties)
    project = Path(__file__).resolve().parents[1]
    spill = project / "outputs" / ".build" / "party_profile_temp"
    spill.mkdir(parents=True, exist_ok=True)
    relation = f"read_parquet({quote(str(parties))})"
    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {quote(args.memory_limit)}")
    connection.execute(f"SET temp_directory = {quote(str(spill))}")
    try:
        connection.execute(f"""
          CREATE TEMP TABLE name_forms AS
          SELECT name, name_key, {punctuation_key('name')} AS punctuation_key,
                 {lexical_key('name')} AS lexical_key,
                 count(*) AS party_mentions
          FROM {relation}
          WHERE name IS NOT NULL
          GROUP BY name, name_key
        """)
        party_mentions, distinct_names, conservative_keys = connection.execute(
            f"""
            SELECT count(*), count(DISTINCT name), count(DISTINCT name_key)
            FROM {relation}
            """
        ).fetchone()
        lexical_keys = connection.execute(
            "SELECT count(DISTINCT lexical_key) FROM name_forms WHERE lexical_key <> ''"
        ).fetchone()[0]
        punctuation_keys = connection.execute(
            "SELECT count(DISTINCT punctuation_key) FROM name_forms WHERE punctuation_key <> ''"
        ).fetchone()[0]
        merge_groups, merge_mentions = connection.execute("""
          WITH groups AS (
            SELECT lexical_key, count(DISTINCT name_key) AS conservative_keys,
                   sum(party_mentions) AS party_mentions
            FROM name_forms WHERE lexical_key <> '' GROUP BY lexical_key
          )
          SELECT count(*) FILTER (WHERE conservative_keys > 1),
                 coalesce(sum(party_mentions) FILTER (WHERE conservative_keys > 1), 0)
          FROM groups
        """).fetchone()
        punctuation_groups = connection.execute("""
          SELECT count(*) FROM (
            SELECT punctuation_key
            FROM name_forms WHERE punctuation_key <> ''
            GROUP BY punctuation_key HAVING count(DISTINCT name_key) > 1
          )
        """).fetchone()[0]
        legal_suffix_groups = connection.execute("""
          SELECT count(*) FROM (
            SELECT lexical_key
            FROM name_forms WHERE lexical_key <> ''
            GROUP BY lexical_key HAVING count(DISTINCT punctuation_key) > 1
          )
        """).fetchone()[0]
        suffixes = rows(connection.execute("""
          WITH classified AS (
            SELECT name, party_mentions,
              CASE
                WHEN regexp_matches(lower(name), '(^|[^a-z])incorporated[.]?$') THEN 'incorporated'
                WHEN regexp_matches(lower(name), '(^|[^a-z])inc[.]?$') THEN 'inc'
                WHEN regexp_matches(lower(name), '(^|[^a-z])corporation[.]?$') THEN 'corporation'
                WHEN regexp_matches(lower(name), '(^|[^a-z])corp[.]?$') THEN 'corp'
                WHEN regexp_matches(lower(name), '(^|[^a-z])company[.]?$') THEN 'company'
                WHEN regexp_matches(lower(name), '(^|[^a-z])co[.]?$') THEN 'co'
                WHEN regexp_matches(lower(name), '(^|[^a-z])limited[.]?$') THEN 'limited'
                WHEN regexp_matches(lower(name), '(^|[^a-z])ltd[.]?$') THEN 'ltd'
              END AS suffix_family
            FROM name_forms
          )
          SELECT suffix_family, count(DISTINCT name) AS distinct_names,
                 sum(party_mentions) AS party_mentions
          FROM classified WHERE suffix_family IS NOT NULL
          GROUP BY suffix_family ORDER BY party_mentions DESC
        """))
        examples = rows(connection.execute(f"""
          SELECT lexical_key, count(DISTINCT name_key) AS conservative_keys,
                 count(DISTINCT name) AS source_spellings,
                 sum(party_mentions) AS party_mentions,
                 list_slice(list_sort(list(DISTINCT name)), 1, 8) AS example_names
          FROM name_forms WHERE lexical_key <> ''
          GROUP BY lexical_key HAVING count(DISTINCT name_key) > 1
          ORDER BY party_mentions DESC, conservative_keys DESC, lexical_key
          LIMIT {max(1, args.example_limit)}
        """))
        legal_suffix_examples = rows(connection.execute(f"""
          SELECT lexical_key, count(DISTINCT punctuation_key) AS punctuation_keys,
                 count(DISTINCT name) AS source_spellings,
                 sum(party_mentions) AS party_mentions,
                 list_slice(list_sort(list(DISTINCT name)), 1, 8) AS example_names
          FROM name_forms WHERE lexical_key <> ''
          GROUP BY lexical_key HAVING count(DISTINCT punctuation_key) > 1
          ORDER BY party_mentions DESC, punctuation_keys DESC, lexical_key
          LIMIT {max(1, args.example_limit)}
        """))
    finally:
        connection.close()
    profile = {
        "input": str(parties),
        "candidate_rule_version": 1,
        "candidate_rule": "lowercase; punctuation to spaces; collapse spaces; canonicalize terminal incorporated/corporation/company/limited",
        "overview": {
            "party_mentions": party_mentions,
            "distinct_source_names": distinct_names,
            "distinct_conservative_keys": conservative_keys,
            "distinct_punctuation_keys": punctuation_keys,
            "distinct_lexical_keys": lexical_keys,
            "candidate_merge_groups": merge_groups,
            "punctuation_candidate_groups": punctuation_groups,
            "legal_suffix_candidate_groups": legal_suffix_groups,
            "mentions_in_candidate_merge_groups": merge_mentions,
        },
        "suffixes": suffixes,
        "candidate_merge_examples": examples,
        "legal_suffix_examples": legal_suffix_examples,
    }
    args.json_output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.resolve().write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.markdown_output.resolve().write_text(render(profile), encoding="utf-8")
    print(json.dumps(profile["overview"], indent=2))


if __name__ == "__main__":
    main()
