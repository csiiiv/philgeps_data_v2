"""Disposable record-oriented provenance lookup projection (ADR-014).

Direct `(record_type, record_id)` lookups scan all ~110M rows of
`record_sources.parquet` (~14s measured). This module maintains a record-keyed
copy in a DuckDB database under `.cache/provenance.duckdb` so the same lookup
is a zone-map pruned point query (milliseconds).

Design:

- disposable: deleting the file never affects authoritative data; lookups fall
  back to a direct Parquet scan and the cache rebuilds on next use;
- keyed to source-file metadata: the authoritative Parquet's size + mtime
  decide whether the cache is stale and must be rebuilt;
- sorted by `record_key`: DuckDB's automatic zone maps then let equality
  filters skip all row groups that cannot contain the key, without paying for
  an explicit ART index;
- bounded builds: the build runs under the configured memory/thread limits
  with a spill directory inside `.cache/` and swaps into place atomically, so
  readers never observe a half-written database.

Build placement: files below `INLINE_BUILD_MAX_BYTES` build synchronously on
the requesting thread (fixtures, small projects); larger files build in a
background daemon thread while requests fall back to direct scans.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .config import Settings
from .database import sql_literal_path

logger = logging.getLogger("philgeps.viewer.provenance")

# Below this source size a rebuild is cheap enough to run on the request path.
INLINE_BUILD_MAX_BYTES = 64 * 1024 * 1024

KEY_SEPARATOR = "\x1f"

# Incremental rebuild: rows are stored in hash(record_key) % N contiguous,
# per-part sorted regions. Each partition carries a content fingerprint
# (row count + key/source checksums); a rebuild recomputes fingerprints in
# one cheap aggregate scan and re-processes only partitions that changed.
# Bump to force one full rebuild after a storage-format change.
PROVENANCE_SCHEMA_VERSION = 2
PROVENANCE_PARTITIONS = 32

SOURCE_COLUMNS = "record_key, release_id, source_file_id, source_sheet, source_row_number"


def make_record_key(record_type: str, record_id: str) -> str:
    return f"{record_type}{KEY_SEPARATOR}{record_id}"


class ProvenanceCache:
    def __init__(self, settings: Settings, record_sources_path: Path | None):
        self.settings = settings
        self.record_sources_path = record_sources_path
        self._lock = threading.Lock()
        self._build_thread: threading.Thread | None = None
        self._fingerprint: dict[str, Any] | None = None
        # Persistent read-only reader; amortizes the multi-second cost of
        # opening a multi-GB DuckDB file across lookups. Closed whenever the
        # fingerprint changes so builds can swap the file.
        self._reader: duckdb.DuckDBPyConnection | None = None
        self._reader_fingerprint: dict[str, Any] | None = None
        # DuckDB connections are not thread-safe; FastAPI serves sync
        # endpoints from a threadpool, so all reader use is serialized.
        self._reader_lock = threading.Lock()

    # -------------------------------------------------------------- paths

    @property
    def database_path(self) -> Path:
        return self.settings.cache_directory / "provenance.duckdb"

    def _tmp_path(self) -> Path:
        return self.database_path.parent / f"{self.database_path.name}.tmp{os.getpid()}"

    # -------------------------------------------------------------- state

    def state(self) -> str:
        """One of: unavailable, building, hit, miss."""
        if self.record_sources_path is None:
            return "unavailable"
        if self._build_thread is not None and self._build_thread.is_alive():
            return "building"
        if self._ready():
            return "hit"
        return "miss"

    def _ready(self) -> bool:
        fingerprint = self._current_fingerprint()
        if fingerprint is None or not self.database_path.exists():
            return False
        if self._fingerprint is None:
            self._fingerprint = self._stored_fingerprint()
        return self._fingerprint == fingerprint

    def _current_fingerprint(self) -> dict[str, Any] | None:
        path = self.record_sources_path
        if path is None or not path.exists():
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    def _stored_fingerprint(self) -> dict[str, Any] | None:
        """Read the fingerprint recorded inside an existing cache database."""
        if not self.database_path.exists():
            return None
        try:
            connection = duckdb.connect(str(self.database_path), read_only=True)
        except duckdb.Error:
            return None
        try:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'fingerprint'"
            ).fetchone()
            if row is None:
                return None
            stored = json.loads(row[0])
            # v1 databases (globally sorted, no partition metadata) are still
            # valid lookups; the partitioned writer keeps the same table
            # shape, so they are reused as-is and upgraded on next rebuild.
            return stored
        except duckdb.Error:
            return None
        finally:
            connection.close()

    # -------------------------------------------------------------- build

    def ensure(self, *, blocking: bool = True) -> bool:
        """Make the cache usable if possible. Returns True when usable now.

        `blocking=False` returns immediately when another build holds the lock;
        callers then fall back to a direct scan.
        """
        if self.record_sources_path is None:
            return False
        if not self._lock.acquire(blocking=blocking):
            return False
        try:
            fingerprint = self._current_fingerprint()
            if fingerprint is None:
                return False
            if self._fingerprint is None and self.database_path.exists():
                stored = self._stored_fingerprint()
                if stored == fingerprint:
                    self._fingerprint = stored
                    return True
            if self._fingerprint == fingerprint and self.database_path.exists():
                return True
            self._build(fingerprint)
            self._fingerprint = fingerprint
            return True
        except Exception:
            logger.exception(
                "provenance cache build failed; falling back to direct scans"
            )
            return False
        finally:
            self._lock.release()

    def _start_background_build(self) -> None:
        if self._build_thread is not None and self._build_thread.is_alive():
            return  # a build is already running; do not spawn duplicates
        thread = threading.Thread(
            target=self.ensure, name="provenance-build", daemon=True
        )
        self._build_thread = thread
        thread.start()

    def warm(self, record_sources_path: Path | None = None) -> None:
        """Build the provenance cache at startup when a source exists."""
        if record_sources_path is not None:
            self.record_sources_path = record_sources_path
        if self.record_sources_path is None:
            return
        self.ensure(blocking=True)

    def _build(self, fingerprint: dict[str, Any]) -> None:
        """Rebuild the record-key lookup table, incrementally when possible.

        Cold path (no prior / schema mismatch / every partition dirty): one
        CREATE TABLE ... ORDER BY record_key — same as the v1 builder.

        Warm path (prior exists, some partitions unchanged): one source scan
        via PARTITION_BY writes only the dirty partitions; unchanged rows
        are copied from the prior database in a single pass. A typical
        refresh that touches a few source files only rebuilds a fraction
        of the ~110M rows instead of the full ~86 min rebuild.
        """
        settings = self.settings
        settings.cache_directory.mkdir(parents=True, exist_ok=True)
        tmp_path = self._tmp_path()
        self._remove_stale_tmp_files()
        spill = settings.cache_directory / "tmp" / "provenance-build"
        spill.mkdir(parents=True, exist_ok=True)
        source = sql_literal_path(self.record_sources_path)
        key_expr = "record_type || chr(31) || coalesce(record_id, '')"
        started = datetime.now(timezone.utc)
        connection = duckdb.connect(str(tmp_path))
        prior_attached = False
        rebuilt = 0
        reused = 0
        try:
            connection.execute(f"SET threads = {settings.duckdb.threads}")
            memory = settings.duckdb.memory_limit.replace("'", "''")
            connection.execute(f"SET memory_limit = '{memory}'")
            connection.execute(
                f"SET temp_directory = '{str(spill).replace(chr(39), chr(39) * 2)}'"
            )

            # Decide cold vs incremental: attach prior only when schema matches.
            prior_usable = False
            if self.database_path.exists():
                try:
                    connection.execute(
                        f"ATTACH '{self.database_path}' AS prior (READ_ONLY)"
                    )
                    prior_attached = True
                    version = connection.execute(
                        "SELECT value FROM prior.meta WHERE key = 'schema_version'"
                    ).fetchone()
                    prior_usable = (
                        version is not None
                        and version[0] == str(PROVENANCE_SCHEMA_VERSION)
                    )
                except duckdb.Error:
                    prior_usable = False

            if prior_usable:
                rebuilt, reused = self._build_incremental(
                    connection, source, key_expr, spill
                )
            else:
                if prior_attached:
                    connection.execute("DETACH prior")
                    prior_attached = False
                connection.execute(
                    f"""
                    CREATE TABLE sources AS
                    SELECT
                        {key_expr} AS record_key,
                        release_id,
                        source_file_id,
                        source_sheet,
                        source_row_number
                    FROM read_parquet({source})
                    ORDER BY record_key
                    """
                )
                rebuilt = PROVENANCE_PARTITIONS

            if prior_attached:
                try:
                    connection.execute("DETACH prior")
                except duckdb.Error:
                    pass
                prior_attached = False

            connection.execute("CREATE TABLE meta(key VARCHAR, value VARCHAR)")
            connection.execute(
                "INSERT INTO meta VALUES ('fingerprint', ?)",
                [json.dumps(fingerprint, sort_keys=True)],
            )
            connection.execute(
                "INSERT INTO meta VALUES ('built_at', ?)",
                [started.isoformat()],
            )
            count = connection.execute("SELECT count(*) FROM sources").fetchone()[0]
            connection.execute("INSERT INTO meta VALUES ('row_count', ?)", [str(count)])
            connection.execute(
                "INSERT INTO meta VALUES ('schema_version', ?)",
                [str(PROVENANCE_SCHEMA_VERSION)],
            )
            connection.close()
            # The persistent reader may hold the old database open; on Windows
            # os.replace cannot swap a file that is open, so close it first.
            with self._reader_lock:
                self._close_reader()
            for _ in range(15):
                try:
                    os.replace(tmp_path, self.database_path)
                    logger.info(
                        "provenance cache built: %s rows in %.1fs "
                        "(%d partitions rebuilt, %d reused)",
                        count,
                        (datetime.now(timezone.utc) - started).total_seconds(),
                        rebuilt,
                        reused,
                    )
                    return
                except OSError:
                    time.sleep(0.4)
            raise RuntimeError("could not swap the provenance cache into place")
        finally:
            try:
                if prior_attached:
                    connection.execute("DETACH prior")
            except duckdb.Error:
                pass
            try:
                connection.close()
            except duckdb.Error:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            import shutil

            shutil.rmtree(spill, ignore_errors=True)

    def _build_incremental(
        self,
        connection: duckdb.DuckDBPyConnection,
        source: str,
        key_expr: str,
        spill: Path,
    ) -> tuple[int, int]:
        """Patch dirty partitions into a new sources table; copy the rest.

        Caller must have ATTACHed the prior database as `prior`. Returns
        (rebuilt_partition_count, reused_partition_count).
        """
        connection.execute(
            f"""
            CREATE TEMP TABLE new_parts AS
            SELECT hash(record_key) % {PROVENANCE_PARTITIONS} AS part,
                   count(*) AS n,
                   sum(hash(record_key, source_file_id, source_row_number)) AS content
            FROM (
                SELECT {key_expr} AS record_key,
                       source_file_id, source_row_number
                FROM read_parquet({source})
            ) GROUP BY 1
            """
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE prior_parts AS
            SELECT hash(record_key) % {PROVENANCE_PARTITIONS} AS part,
                   count(*) AS n,
                   sum(hash(record_key, source_file_id, source_row_number)) AS content
            FROM prior.sources
            GROUP BY 1
            """
        )
        dirty = [
            row[0]
            for row in connection.execute(
                """
                SELECT p.part FROM new_parts p
                LEFT JOIN prior_parts USING (part)
                WHERE prior_parts.part IS NULL
                   OR prior_parts.n IS DISTINCT FROM p.n
                   OR prior_parts.content IS DISTINCT FROM p.content
                ORDER BY p.part
                """
            ).fetchall()
        ]
        # Also drop partitions that vanished from the source.
        new_set = {
            row[0]
            for row in connection.execute("SELECT part FROM new_parts").fetchall()
        }
        prior_set = {
            row[0]
            for row in connection.execute("SELECT part FROM prior_parts").fetchall()
        }
        dirty_set = set(dirty) | (prior_set - new_set)
        keep = sorted(prior_set & new_set - dirty_set)

        connection.execute(
            """
            CREATE TABLE sources(
                record_key VARCHAR, release_id VARCHAR,
                source_file_id VARCHAR, source_sheet VARCHAR,
                source_row_number BIGINT
            )
            """
        )
        if dirty_set & new_set:
            parts_dir = spill / "parts"
            parts_dir.mkdir(parents=True, exist_ok=True)
            # Filter to dirty partitions so the PARTITION_BY only writes
            # what we need; empty partitions never produce a directory.
            dirty_list = ",".join(str(p) for p in sorted(dirty_set & new_set))
            connection.execute(
                f"""
                COPY (
                    SELECT {key_expr} AS record_key, release_id,
                           source_file_id, source_sheet, source_row_number,
                           hash({key_expr}) % {PROVENANCE_PARTITIONS} AS part
                    FROM read_parquet({source})
                    WHERE hash({key_expr}) % {PROVENANCE_PARTITIONS}
                          IN ({dirty_list})
                ) TO '{parts_dir.as_posix()}'
                (FORMAT PARQUET, PARTITION_BY (part), COMPRESSION ZSTD,
                 ROW_GROUP_SIZE 100000, OVERWRITE_OR_IGNORE)
                """
            )
            for part in sorted(dirty_set & new_set):
                part_dir = parts_dir / f"part={part}"
                if not part_dir.is_dir():
                    continue
                part_glob = (part_dir / "*.parquet").as_posix()
                connection.execute(
                    f"""
                    INSERT INTO sources
                    SELECT record_key, release_id, source_file_id,
                           source_sheet, source_row_number
                    FROM read_parquet('{part_glob}')
                    ORDER BY record_key
                    """
                )
        if keep:
            keep_list = ",".join(str(p) for p in keep)
            connection.execute(
                f"""
                INSERT INTO sources
                SELECT record_key, release_id, source_file_id,
                       source_sheet, source_row_number
                FROM prior.sources
                WHERE hash(record_key) % {PROVENANCE_PARTITIONS} IN ({keep_list})
                """
            )
        return len(dirty_set & new_set), len(keep)

    def _remove_stale_tmp_files(self) -> None:
        for candidate in self.database_path.parent.glob(
            f"{self.database_path.name}.tmp*"
        ):
            try:
                candidate.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------- lookup

    def _close_reader(self) -> None:
        reader, self._reader, self._reader_fingerprint = self._reader, None, None
        if reader is not None:
            try:
                reader.close()
            except duckdb.Error:
                pass

    def _reader_connection(self) -> duckdb.DuckDBPyConnection | None:
        """Return a reusable read-only connection valid for the current file."""
        fingerprint = self._current_fingerprint()
        if fingerprint is None or not self.database_path.exists():
            return None
        with self._reader_lock:
            if self._reader is not None and self._reader_fingerprint == fingerprint:
                return self._reader
            self._close_reader()
            try:
                connection = duckdb.connect(str(self.database_path), read_only=True)
            except duckdb.Error:
                return None
            self._reader = connection
            self._reader_fingerprint = fingerprint
            return connection

    def lookup(
        self, record_type: str, record_id: str, release_id: str | None, limit: int
    ) -> list[tuple] | None:
        """Point lookup by record key; None when the cache is unusable.

        Never blocks on a rebuild: small sources rebuild inline (fast), large
        sources kick a background build and the caller falls back to a direct
        Parquet scan until it finishes.
        """
        if self.record_sources_path is None:
            return None
        if not self._ready():
            size = self._source_size()
            if size is not None and size <= INLINE_BUILD_MAX_BYTES:
                if not self.ensure():
                    return None
            else:
                self._start_background_build()
                return None
        connection = self._reader_connection()
        if connection is None:
            return None
        with self._reader_lock:
            try:
                key = make_record_key(record_type, record_id)
                release_predicate = "AND release_id = ?" if release_id else ""
                parameters: list[Any] = [key]
                if release_id:
                    parameters.append(release_id)
                parameters.append(limit)
                return connection.execute(
                    f"""
                    SELECT release_id, source_file_id, source_sheet, source_row_number
                    FROM sources
                    WHERE record_key = ? {release_predicate}
                    LIMIT ?
                    """,
                    parameters,
                ).fetchall()
            except duckdb.Error:
                self._close_reader()  # e.g. file swapped underneath us
                return None

    def _source_size(self) -> int | None:
        if self.record_sources_path is None:
            return None
        try:
            return self.record_sources_path.stat().st_size
        except OSError:
            return None
