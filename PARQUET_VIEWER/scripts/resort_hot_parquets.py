"""One-shot physical re-sort of viewer-hot Parquets for zone-map pruning.

Re-writes the named tables sorted by their lookup key without a full ETL
rebuild. Uses hash-partitioned bounded sorts so each part stays inside the
DuckDB memory ceiling. Safe to interrupt: writes to a .tmp sibling and
atomically replaces only on success.

Usage (from repo root):
    python PARQUET_VIEWER/scripts/resort_hot_parquets.py
    python PARQUET_VIEWER/scripts/resort_hot_parquets.py --tables contracting_processes award_suppliers
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
PARQUET_DIR = ROOT / "OCDS_ETL" / "outputs" / "parquet"
WORK_DIR = ROOT / "OCDS_ETL" / "outputs" / ".resort_work"

# table -> sort key used by the viewer for point lookups
TABLES = {
    "contracting_processes": "process_id",
    "award_suppliers": "release_id",
    "data_quality_issues": "release_id",
    # record_sources is ~4GB / 116M rows — optional, slowest
    "record_sources": "release_id",
}


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def resort(
    connection: duckdb.DuckDBPyConnection,
    source: Path,
    key: str,
    work_dir: Path,
    partitions: int,
) -> Path:
    parts_dir = work_dir / f"{source.stem}_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in parts_dir.glob("part_*.parquet"):
        stale.unlink()
    relation = f"read_parquet({literal(str(source))})"
    # Range-partition on the first hex digit after the ``pg??_`` prefix so
    # concatenating sorted parts yields global lexical order (zone maps work).
    # Hash buckets would span the full key range and defeat pruning.
    digits = "0123456789abcdef"
    use_range = partitions == 16
    bucket_count = 16 if use_range else partitions
    for index in range(bucket_count):
        if index == 0 or (index + 1) % 4 == 0 or index + 1 == bucket_count:
            label = f"'{digits[index]}'" if use_range else str(index + 1)
            print(f"  part {index + 1}/{bucket_count} ({label})", flush=True)
        temporary = parts_dir / f"part_{index:03d}.parquet"
        if use_range:
            predicate = f"lower(substr({key}, 6, 1)) = {literal(digits[index])}"
        else:
            predicate = f"hash({key}) % {partitions} = {index}"
        connection.execute(
            f"""
            COPY (
                SELECT * FROM {relation}
                WHERE {predicate}
                ORDER BY {key}
            ) TO {literal(str(temporary))}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
            """
        )
    target = source.with_suffix(source.suffix + ".sorted.tmp")
    if target.exists():
        target.unlink()
    glob = (parts_dir / "part_*.parquet").as_posix()
    print("  concatenating", flush=True)
    connection.execute(
        f"""
        COPY (SELECT * FROM read_parquet({literal(glob)}))
        TO {literal(str(target))}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
    return target


def prune_ratio(connection: duckdb.DuckDBPyConnection, path: Path, key: str) -> str:
    """Sample one key and report how many row groups contain it."""
    sample = connection.execute(
        f"SELECT any_value({key}) FROM read_parquet({literal(str(path))})"
    ).fetchone()[0]
    if sample is None:
        return "no sample"
    # Approximate: count rows in the matching key vs total — if clustering
    # works, a point lookup should return in well under a second. Report
    # distinct row-group span via parquet_metadata when available.
    try:
        meta = connection.execute(
            f"""
            SELECT count(DISTINCT row_group_id)
            FROM parquet_metadata({literal(str(path))})
            """
        ).fetchone()[0]
        return f"total_rgs={meta}, sample_key={sample[:20]}..."
    except Exception as error:
        return f"meta unavailable: {error}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(TABLES),
        default=["contracting_processes", "award_suppliers", "data_quality_issues"],
    )
    parser.add_argument("--partitions", type=int, default=16)
    parser.add_argument("--memory-limit", default="4GB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--parquet-dir", type=Path, default=PARQUET_DIR)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET threads = {max(1, args.threads)}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(f"SET memory_limit = {literal(args.memory_limit)}")
    spill = args.work_dir / "duckdb_temp"
    spill.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET temp_directory = {literal(str(spill))}")

    try:
        for name in args.tables:
            key = TABLES[name]
            source = args.parquet_dir / f"{name}.parquet"
            if not source.exists():
                print(f"skip {name}: missing {source}", flush=True)
                continue
            print(f"resorting {name} by {key} ({source.stat().st_size / 1e9:.2f} GB)", flush=True)
            before = prune_ratio(connection, source, key)
            print(f"  before: {before}", flush=True)
            target = resort(connection, source, key, args.work_dir, args.partitions)
            after = prune_ratio(connection, target, key)
            print(f"  after:  {after}", flush=True)
            source.replace(source.with_suffix(source.suffix + ".unsorted.bak"))
            target.replace(source)
            print(f"  swapped; backup at {source.with_suffix(source.suffix + '.unsorted.bak')}", flush=True)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
