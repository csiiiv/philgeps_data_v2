"""Regenerate the statistics block in docs/11_product_improvement_opportunities.md.

Reads the authoritative Parquets directly (read-only), computes the handful of
snapshot-dependent numbers the doc cites, and rewrites the fenced block
between the BEGIN/END DOC_STATS markers. Every other byte of the doc is left
untouched, so the script is safe to re-run after each ETL build.

Usage:
    python scripts/doc_stats.py            # rewrite the stats block
    python scripts/doc_stats.py --check    # exit 1 if the block is stale
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "11_product_improvement_opportunities.md"
PARQUET_DIR = ROOT.parent / "OCDS_ETL" / "outputs" / "parquet"

BEGIN = "<!-- BEGIN DOC_STATS -->"
END = "<!-- END DOC_STATS -->"


def _p(name: str) -> str:
    return (PARQUET_DIR / name).as_posix()


def collect_stats() -> list[str]:
    con = duckdb.connect()
    try:
        processes = con.execute(
            f"SELECT count(*) FROM read_parquet('{_p('contracting_processes.parquet')}')"
        ).fetchone()[0]
        issues, sev_rows = con.execute(
            f"SELECT count(*), count(DISTINCT severity) FROM "
            f"read_parquet('{_p('data_quality_issues.parquet')}')"
        ).fetchone()
        multi = con.execute(
            f"SELECT count(*) FROM read_parquet('{_p('compiled_processes.parquet')}') "
            "WHERE has_multiple_releases"
        ).fetchone()[0]
        datasets = len(list(PARQUET_DIR.glob("*.parquet")))
        tender_items = con.execute(
            f"SELECT count(*) FROM read_parquet('{_p('tender_items.parquet')}')"
        ).fetchone()[0]
        award_items = con.execute(
            f"SELECT count(*) FROM read_parquet('{_p('award_items.parquet')}')"
        ).fetchone()[0]
    finally:
        con.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return [
        f"- Contracting processes: {processes:,}",
        f"- Normalized datasets: {datasets}",
        f"- Multi-release processes: {multi:,}",
        f"- Data-quality issue rows: {issues:,} across {sev_rows} distinct severity value(s)",
        f"- Tender items: {tender_items:,}; award items: {award_items:,}",
        f"- Generated: {now}",
    ]


def main() -> int:
    check_only = "--check" in sys.argv
    text = DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(f"error: {DOC.name} is missing the {BEGIN}/{END} markers", file=sys.stderr)
        return 2

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    lines = collect_stats()
    block = BEGIN + "\n" + "\n".join(lines) + "\n" + END
    new_text = head + block + tail

    if check_only:
        if new_text == text:
            print("doc stats are up to date")
            return 0
        print("doc stats are stale; run: python scripts/doc_stats.py", file=sys.stderr)
        return 1

    DOC.write_text(new_text, encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
