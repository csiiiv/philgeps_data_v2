"""Researcher-facing search over the compiled procurement story.

Implements the search-first entry point from the end-user UX plan: a
non-technical researcher arrives with a project name fragment or a
company/agency name, not with pipeline keys. This service resolves that
vocabulary to what the UI can open:

    procurement titles -> process cards  -> procurement summary page
    party names        -> party cards    -> parties grid filtered by name

Honest-data rules:
    - results describe observed rows only; name matches are *name matches*,
      not identity assertions (party linkage stays provisional elsewhere)
    - amounts/currencies pass through as recorded

Performance: the raw search is a wide join (tenders x compiled_processes,
~10M x ~10M rows) that costs tens of seconds per term. `SearchIndex` below
applies the ADR-014 disposable-cache pattern once per data refresh: a
pre-joined, pre-aggregated projection in `.cache/search_index.duckdb`
scanned by a persistent read-only reader. Until it is ready (or forever,
for tiny/partial data) the direct Parquet path still answers, just slower.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb

try:  # numpy ships with duckdb's pandas extra; optional at runtime.
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

from .catalog import Catalog
from .config import Settings
from .database import DuckDBPool, execute_bounded, sql_literal_path
from .derivation import FACTS_RULE, FACTS_RULE_VERSION, OUTCOME_RULE, OUTCOME_RULE_VERSION
from .query import QueryError

logger = logging.getLogger("philgeps.viewer.search")

SEARCH_ERROR_INVALID = "invalid_search"

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
PROCUREMENT_LIMIT = 20
PARTY_LIMIT = 12
MAX_PAGE = 50

# Canonical process outcomes (docs/13, process-outcomes-v1). The funnel,
# facet, and filter all use this closed set.
OUTCOME_VALUES = (
    "contracted",
    "awarded",
    "partially_awarded",
    "cancelled",
    "unsuccessful",
    "closed_unknown",
    "active",
    "conflicting_evidence",
)

# Facet filters accepted by /api/search (applied to procurement cards).
# "none" is the honest label for rows with no recorded OCDS status.
SEARCH_STATUSES = ("complete", "unsuccessful", "cancelled", "active", "none")
MIN_FILTER_YEAR = 1990
MAX_FILTER_YEAR = 2100

# Memoized per (dataset fingerprint, normalized query): searches are typed
# repeatedly (typos, re-visits) and each miss costs multi-second Parquet scans.
SEARCH_CACHE_LIMIT = 128

# Below this combined source size a rebuild is cheap enough to run inline on
# the requesting thread (fixtures, small projects); larger sources build in a
# background daemon thread while requests fall back to direct scans.
INLINE_BUILD_MAX_BYTES = 64 * 1024 * 1024


def _procurement_filter_clause(
    statuses: tuple[str, ...],
    year_from: int | None,
    year_to: int | None,
    outcomes: tuple[str, ...] = (),
) -> tuple[str, list[Any]]:
    """WHERE fragment + params for status/year/outcome filters.

    Status/year apply to `procurements`; outcome applies to the joined
    `outcomes` table (callers must join it when the clause is non-empty).
    "none" maps to `status IS NULL` (no OCDS status recorded). Returns an
    empty clause when nothing is selected so unfiltered searches keep the
    exact pre-filter SQL shape.
    """
    fragments: list[str] = []
    params: list[Any] = []
    normalized = tuple(s for s in statuses if s in SEARCH_STATUSES)
    if normalized:
        parts: list[str] = []
        if "none" in normalized:
            parts.append("status IS NULL")
        valued = tuple(s for s in normalized if s != "none")
        if valued:
            placeholders = ", ".join("?" for _ in valued)
            parts.append(f"status IN ({placeholders})")
            params.extend(valued)
        fragments.append(f"({' OR '.join(parts)})")
    normalized_outcomes = tuple(o for o in outcomes if o in OUTCOME_VALUES)
    if normalized_outcomes:
        placeholders = ", ".join("?" for _ in normalized_outcomes)
        fragments.append(f"o.outcome IN ({placeholders})")
        params.extend(normalized_outcomes)
    if year_from is not None:
        fragments.append("year(closing_date) >= ?")
        params.append(year_from)
    if year_to is not None:
        fragments.append("year(closing_date) <= ?")
        params.append(year_to)
    if not fragments:
        return "", []
    return " AND " + " AND ".join(fragments), params

INDEX_SOURCE_DATASETS = (
    "tenders", "compiled_processes", "parties", "party_roles",
    "awards", "contracts", "award_items", "tender_items",
)

# Bump when the index SCHEMA changes (tables/columns added). Source-file
# fingerprints alone cannot detect code changes, so this version is stored
# in the built database and mismatch forces a rebuild.
INDEX_SCHEMA_VERSION = 7


class SearchIndex:
    """Disposable pre-joined projection for researcher search.

    Mirrors the provenance cache lifecycle: fingerprinted to source-file
    metadata (size + mtime of all four inputs), swapped atomically, closed
    before swap on Windows, persistent read-only reader guarded by a lock,
    and safe to delete at any time (callers fall back to direct scans).
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._build_thread: threading.Thread | None = None
        self._fingerprint: dict[str, Any] | None = None
        self._reader: duckdb.DuckDBPyConnection | None = None
        self._reader_fingerprint: dict[str, Any] | None = None
        self._reader_lock = threading.Lock()

    # -------------------------------------------------------------- paths

    @property
    def database_path(self) -> Path:
        return self.settings.cache_directory / "search_index.duckdb"

    def _tmp_path(self) -> Path:
        return self.database_path.parent / f"{self.database_path.name}.tmp{os.getpid()}"

    # -------------------------------------------------------------- state

    def _current_fingerprint(self, paths: dict[str, Path]) -> dict[str, Any] | None:
        entries: dict[str, Any] = {
            "schema_version": INDEX_SCHEMA_VERSION,
        }
        for name in INDEX_SOURCE_DATASETS:
            path = paths.get(name)
            if path is None or not path.exists():
                # A missing optional input is part of the fingerprint.
                entries[name] = None
                continue
            stat = path.stat()
            entries[name] = {
                "path": str(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        return entries

    def build_manifest(self, paths: dict[str, Path]) -> dict[str, Any] | None:
        """The versioned build manifest stored in the index, if readable.

        Returns None when the index does not exist or predates manifests.
        Never triggers a build — diagnostics only.
        """
        if not self.database_path.exists():
            return None
        try:
            connection = duckdb.connect(str(self.database_path), read_only=True)
        except duckdb.Error:
            return None
        try:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'build_manifest'"
            ).fetchone()
        except duckdb.Error:
            return None
        finally:
            connection.close()
        if row is None:
            return None
        try:
            manifest = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        # Annotate freshness: does the on-disk index match current sources?
        manifest["stale"] = self._current_fingerprint(paths) != self._stored_fingerprint()
        manifest["index_state"] = self.state(paths)
        return manifest

    def _stored_fingerprint(self) -> dict[str, Any] | None:
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
            return json.loads(row[0]) if row else None
        except duckdb.Error:
            return None
        finally:
            connection.close()

    def _ready(self, paths: dict[str, Path]) -> bool:
        fingerprint = self._current_fingerprint(paths)
        if not self.database_path.exists():
            return False
        if self._fingerprint is None:
            self._fingerprint = self._stored_fingerprint()
        return self._fingerprint == fingerprint

    # -------------------------------------------------------------- build

    def ensure(self, paths: dict[str, Path], *, blocking: bool = True) -> bool:
        """Make the index usable if possible. True when usable now."""
        if not self._lock.acquire(blocking=blocking):
            return False
        try:
            fingerprint = self._current_fingerprint(paths)
            if fingerprint is None:
                return False
            if self._fingerprint is None and self.database_path.exists():
                stored = self._stored_fingerprint()
                if stored == fingerprint:
                    self._fingerprint = stored
                    return True
            if self._fingerprint == fingerprint and self.database_path.exists():
                return True
            self._build(paths, fingerprint)
            self._fingerprint = fingerprint
            return True
        except Exception:
            logger.exception("search index build failed; using direct scans")
            return False
        finally:
            self._lock.release()

    def _start_background_build(self, paths: dict[str, Path]) -> None:
        if self._build_thread is not None and self._build_thread.is_alive():
            return
        thread = threading.Thread(
            target=self.ensure,
            args=(paths,),
            kwargs={"blocking": True},
            name="search-index-build",
            daemon=True,
        )
        self._build_thread = thread
        thread.start()

    def state(self, paths: dict[str, Path]) -> str:
        """One of: hit, building, miss."""
        if self._build_thread is not None and self._build_thread.is_alive():
            return "building"
        return "hit" if self._ready(paths) else "miss"

    def _build(self, paths: dict[str, Path], fingerprint: dict[str, Any]) -> None:
        settings = self.settings
        settings.cache_directory.mkdir(parents=True, exist_ok=True)
        tmp_path = self._tmp_path()
        for stale in self.database_path.parent.glob(f"{self.database_path.name}.tmp*"):
            try:
                stale.unlink()
            except OSError:
                pass
        # Per-build spill directory: two concurrent builds (e.g. the startup
        # warm thread and an inline rebuild) must not race on DuckDB temp files.
        spill = settings.cache_directory / "tmp" / f"search-index-{os.getpid()}"
        spill.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc)
        lit = {name: sql_literal_path(path) for name, path in paths.items()}
        connection = duckdb.connect(str(tmp_path))
        try:
            connection.execute(f"SET threads = {settings.duckdb.threads}")
            connection.execute("SET preserve_insertion_order = false")
            # Index build is a one-shot background job: allow a higher ceiling
            # than the query pool so the 11M-row joins finish without OOM.
            memory = "6GB"
            connection.execute(f"SET memory_limit = '{memory}'")
            connection.execute(
                f"SET temp_directory = '{str(spill).replace(chr(39), chr(39) * 2)}'"
            )
            # One row per process, via its preferred release.
            # `title_lower` is the search key: `LIKE` against a pre-lowered
            # column skips ILIKE's per-row case folding (~3x faster scans).
            # No ORDER BY here — sorting 11M rows during the build OOMs the
            # 4GB viewer budget; the fetch query sorts the short result set.
            connection.execute(
                f"""
                CREATE TABLE procurements AS
                SELECT cp.process_id, t.title, t.status,
                       t.source_status,
                       t.value_amount, t.value_currency, t.closing_date,
                       lower(t.title) AS title_lower
                FROM read_parquet({lit['compiled_processes']}) cp
                JOIN read_parquet({lit['tenders']}) t
                  ON t.release_id = cp.preferred_release_id
                QUALIFY row_number() OVER (
                    PARTITION BY cp.process_id ORDER BY t.tender_id
                ) = 1
                """
            )
            # Facet counts for the filter bar: status x closing-year over the
            # one-row-per-process projection. "none" covers rows whose OCDS
            # status was never recorded (over a third of tenders) — honest
            # facet, not a NULL hole.
            connection.execute(
                """
                CREATE TABLE filter_stats AS
                SELECT coalesce(status, 'none') AS status,
                       year(closing_date) AS closing_year,
                       count(*)::BIGINT AS n
                FROM procurements
                WHERE closing_date IS NOT NULL
                GROUP BY 1, 2
                """
            )
            # Process facts (docs/11 Phase 1 step 4, rule process-facts-v1):
            # one analytical row per process. The `outcomes` outcome column
            # (docs/13, process-outcomes-v1) is computed here in the same
            # pass — same CASE, same evidence — so `outcomes` below is a
            # pure projection of this table and the two can never drift.
            connection.execute(
                f"""
                CREATE TABLE process_facts AS
                WITH award_evidence AS (
                    SELECT cp.process_id,
                           count(a.award_id) AS award_count,
                           count(c.contract_id) FILTER (
                               WHERE c.award_link_status = 'matched'
                           ) AS matched_contract_count,
                           count(DISTINCT ai.item_id) AS linked_item_count,
                           sum(DISTINCT a.value_amount) AS award_value_amount
                    FROM read_parquet({lit['compiled_processes']}) cp
                    LEFT JOIN read_parquet({lit['awards']}) a
                      ON a.release_id = cp.preferred_release_id
                    LEFT JOIN read_parquet({lit['contracts']}) c
                      ON c.release_id = cp.preferred_release_id
                       AND c.award_id = a.award_id
                    LEFT JOIN read_parquet({lit['award_items']}) ai
                      ON ai.release_id = cp.preferred_release_id
                       AND ai.award_id = a.award_id
                    GROUP BY cp.process_id
                ),
                tender_item_counts AS (
                    SELECT cp.process_id,
                           count(ti.item_id) AS tender_item_count
                    FROM read_parquet({lit['compiled_processes']}) cp
                    JOIN read_parquet({lit['tender_items']}) ti
                      ON ti.release_id = cp.preferred_release_id
                    GROUP BY cp.process_id
                )
                SELECT
                    p.process_id,
                    t.procurement_method,
                    t.main_procurement_category,
                    t.area_of_delivery,
                    year(p.closing_date) AS closing_year,
                    p.closing_date IS NOT NULL AS has_closing_date,
                    p.value_amount AS tender_value_amount,
                    coalesce(tic.tender_item_count, 0) AS tender_item_count,
                    coalesce(e.award_count, 0) AS award_count,
                    coalesce(e.matched_contract_count, 0) AS matched_contract_count,
                    coalesce(e.linked_item_count, 0) AS linked_item_count,
                    CASE
                        WHEN coalesce(e.award_count, 0) > 0
                             AND p.source_status IN ('Failed', 'Cancelled')
                            THEN 'conflicting_evidence'
                        WHEN coalesce(e.award_count, 0) > 0
                             AND coalesce(tic.tender_item_count, 0) > 0
                             AND coalesce(e.linked_item_count, 0) > 0
                             AND e.linked_item_count < tic.tender_item_count
                            THEN 'partially_awarded'
                        WHEN coalesce(e.award_count, 0) > 0
                             AND coalesce(e.matched_contract_count, 0) > 0
                            THEN 'contracted'
                        WHEN coalesce(e.award_count, 0) > 0
                            THEN 'awarded'
                        WHEN p.source_status = 'Cancelled' THEN 'cancelled'
                        WHEN p.source_status = 'Failed' THEN 'unsuccessful'
                        WHEN p.source_status IN ('Active', 'Shortlisted',
                                                 'Closed - Pending Opening')
                            THEN 'active'
                        ELSE 'closed_unknown'
                    END AS outcome
                FROM procurements p
                JOIN read_parquet({lit['compiled_processes']}) cp
                  ON cp.process_id = p.process_id
                JOIN read_parquet({lit['tenders']}) t
                  ON t.release_id = cp.preferred_release_id
                LEFT JOIN award_evidence e ON e.process_id = p.process_id
                LEFT JOIN tender_item_counts tic
                  ON tic.process_id = p.process_id
                """
            )
            # `outcomes` is now a pure projection of process_facts (docs/13);
            # funnel and facet queries keep working unchanged.
            connection.execute(
                "CREATE TABLE outcomes AS "
                "SELECT process_id, outcome FROM process_facts"
            )
            connection.execute(
                """
                CREATE TABLE outcome_stats AS
                SELECT outcome,
                       closing_year,
                       count(*)::BIGINT AS n
                FROM process_facts
                WHERE closing_year IS NOT NULL
                GROUP BY 1, 2
                """
            )
            # Observed names with aggregated roles (stored comma-joined).
            # `name_key` carries the ETL's normalized identity: identical for
            # spelling variants of one organization, powering the
            # identity-scope toggle on the party page.
            connection.execute(
                f"""
                CREATE TABLE party_names AS
                SELECT p.name,
                       p.name_key,
                       string_agg(DISTINCT pr.role, ',') AS roles,
                       count(DISTINCT pr.release_id)::BIGINT AS release_count,
                       lower(p.name) AS name_lower
                FROM read_parquet({lit['parties']}) p
                JOIN read_parquet({lit['party_roles']}) pr
                  ON pr.release_id = p.release_id AND pr.party_id = p.party_id
                GROUP BY p.name, p.name_key
                """
            )
            # One row per (name, process): powers the party page without
            # touching the raw grid. Joins the already-materialized
            # `procurements` table instead of re-reading tenders/compiled
            # from Parquet — the heavy preferred-release work is done once.
            # NOTE: deliberately excludes name_key — one extra VARCHAR over
            # this wide table OOMs the 6GB build budget. Identity scope
            # resolves spellings through the small `party_names` table and
            # queries this one with `name IN (variants)`.
            connection.execute(
                f"""
                CREATE TABLE party_procurements AS
                SELECT p.name,
                       proc.process_id,
                       proc.title,
                       proc.status,
                       proc.value_amount,
                       proc.value_currency,
                       proc.closing_date,
                       pr.role
                FROM read_parquet({lit['parties']}) p
                JOIN read_parquet({lit['party_roles']}) pr
                  ON pr.release_id = p.release_id AND pr.party_id = p.party_id
                JOIN read_parquet({lit['compiled_processes']}) cp
                  ON cp.preferred_release_id = pr.release_id
                JOIN procurements proc
                  ON proc.process_id = cp.process_id
                QUALIFY row_number() OVER (
                    PARTITION BY p.name, proc.process_id ORDER BY pr.role
                ) = 1
                """
            )
            connection.execute("CREATE TABLE meta(key VARCHAR, value VARCHAR)")
            connection.execute(
                "INSERT INTO meta VALUES ('fingerprint', ?)",
                [json.dumps(fingerprint, sort_keys=True)],
            )
            connection.execute(
                "INSERT INTO meta VALUES ('built_at', ?)",
                [started.isoformat()],
            )
            # Versioned build manifest (docs/11 Phase 1 step 5): one JSON
            # blob describing exactly what produced this projection — the
            # rule versions, source fingerprints, and row counts. Consumed
            # by GET /api/index/manifest; never a source of truth itself.
            manifest = {
                "manifest_version": 1,
                "projection": "search_index",
                "schema_version": INDEX_SCHEMA_VERSION,
                "rules": {
                    "outcome": {
                        "rule": OUTCOME_RULE,
                        "rule_version": OUTCOME_RULE_VERSION,
                    },
                    "relationship": {
                        "rule": "relationship-status-v1",
                        "rule_version": "1",
                    },
                    "facts": {
                        "rule": FACTS_RULE,
                        "rule_version": FACTS_RULE_VERSION,
                    },
                },
                "built_at": started.isoformat(),
                "built_at_epoch_s": round(started.timestamp()),
                "sources": {
                    name: info
                    for name, info in fingerprint.items()
                    if name != "schema_version"
                },
                "row_counts": {
                    table: connection.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                    for table in ("procurements", "process_facts", "outcomes",
                                  "filter_stats")
                },
            }
            connection.execute(
                "INSERT INTO meta VALUES ('build_manifest', ?)",
                [json.dumps(manifest, sort_keys=True)],
            )
            connection.close()
            with self._reader_lock:
                self._close_reader()
            import shutil

            shutil.rmtree(spill, ignore_errors=True)
            import time as _time

            for _ in range(15):
                try:
                    os.replace(tmp_path, self.database_path)
                    logger.info(
                        "search index built in %.1fs",
                        (datetime.now(timezone.utc) - started).total_seconds(),
                    )
                    return
                except OSError:
                    _time.sleep(0.4)
            raise RuntimeError("could not swap the search index into place")
        finally:
            try:
                connection.close()
            except duckdb.Error:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
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

    def _reader_connection(
        self, paths: dict[str, Path]
    ) -> duckdb.DuckDBPyConnection | None:
        fingerprint = self._current_fingerprint(paths)
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

    def _query(
        self, paths: dict[str, Path], sql: str, params: list[Any]
    ) -> list[tuple] | None:
        if not self._ready(paths):
            total = 0
            for name in INDEX_SOURCE_DATASETS:
                path = paths.get(name)
                if path is not None and path.exists():
                    total += path.stat().st_size
            if total <= INLINE_BUILD_MAX_BYTES:
                if not self.ensure(paths):
                    return None
            else:
                self._start_background_build(paths)
                return None
        connection = self._reader_connection(paths)
        if connection is None:
            return None
        with self._reader_lock:
            try:
                return connection.execute(sql, params).fetchall()
            except duckdb.Error:
                self._close_reader()
                return None

    def search_titles(
        self,
        paths: dict[str, Path],
        query: str,
        offset: int,
        *,
        statuses: tuple[str, ...] = (),
        year_from: int | None = None,
        year_to: int | None = None,
        outcomes: tuple[str, ...] = (),
    ) -> tuple[list[dict[str, Any]], int] | None:
        # LIKE on the pre-lowered column instead of ILIKE: skips per-row
        # case folding over 11M rows. Count and fetch are separate for the
        # same reason as before (early-terminating LIMIT).
        needle = query.lower()
        needs_outcome_join = bool(outcomes)
        where, params = _procurement_filter_clause(
            statuses, year_from, year_to, outcomes
        )
        join = (
            " JOIN outcomes o ON o.process_id = procurements.process_id"
            if needs_outcome_join
            else ""
        )
        count_rows = self._query(
            paths,
            f"""
            SELECT count(*) FROM procurements{join}
            WHERE title_lower LIKE '%' || ? || '%'{where}
            """,
            [needle, *params],
        )
        if count_rows is None:
            return None
        total = count_rows[0][0]
        if total == 0:
            return [], 0
        rows = self._query(
            paths,
            f"""
            SELECT procurements.process_id, title, status, value_amount,
                   value_currency, closing_date
            FROM procurements{join}
            WHERE title_lower LIKE '%' || ? || '%'{where}
            ORDER BY closing_date DESC NULLS LAST, title
            LIMIT {PROCUREMENT_LIMIT} OFFSET ?
            """,
            [needle, *params, offset],
        )
        if rows is None:
            return None
        keys = (
            "process_id", "title", "status",
            "value_amount", "value_currency", "closing_date",
        )
        return [dict(zip(keys, row)) for row in rows], total

    def filter_facets(self, paths: dict[str, Path]) -> dict[str, Any] | None:
        """Status, closing-year, and outcome facet counts."""
        rows = self._query(
            paths,
            """
            SELECT status, closing_year, n
            FROM filter_stats
            ORDER BY closing_year, status
            """,
            [],
        )
        if rows is None:
            return None
        outcome_rows = self._query(
            paths,
            "SELECT outcome, n FROM outcome_stats ORDER BY n DESC",
            [],
        )
        if outcome_rows is None:
            return None
        statuses: dict[str, int] = {}
        years: dict[int, int] = {}
        for status, year, count in rows:
            statuses[status] = statuses.get(status, 0) + count
            if year is not None:
                years[year] = years.get(year, 0) + count
        return {
            "statuses": [
                {"status": key, "count": value}
                for key, value in sorted(statuses.items(), key=lambda kv: -kv[1])
            ],
            "years": [{"year": key, "count": value} for key, value in sorted(years.items())],
            "outcomes": [
                {"outcome": outcome, "count": count}
                for outcome, count in outcome_rows
            ],
        }

    def search_parties(
        self, paths: dict[str, Path], query: str, offset: int
    ) -> tuple[list[dict[str, Any]], int] | None:
        needle = query.lower()
        count_rows = self._query(
            paths,
            "SELECT count(*) FROM party_names WHERE name_lower LIKE '%' || ? || '%'",
            [needle],
        )
        if count_rows is None:
            return None
        total = count_rows[0][0]
        if total == 0:
            return [], 0
        rows = self._query(
            paths,
            f"""
            SELECT name, roles, release_count
            FROM party_names
            WHERE name_lower LIKE '%' || ? || '%'
            ORDER BY release_count DESC, name
            LIMIT {PARTY_LIMIT} OFFSET {offset}
            """,
            [needle],
        )
        if rows is None:
            return None
        return (
            [
                {
                    "name": row[0],
                    "roles": (row[1] or "").split(",") if row[1] else [],
                    "release_count": row[2],
                }
                for row in rows
            ],
            total,
        )

    def party_page(
        self,
        paths: dict[str, Path],
        name: str,
        offset: int,
        *,
        scope: str = "name",
    ) -> tuple[list[dict[str, Any]], int] | None:
        """Process cards for one observed party name (exact match).

        scope="identity" widens the match to every observed spelling sharing
        the same ETL `name_key` — the provisional identity resolution this
        dataset ships with.
        """
        if scope == "identity":
            return self._party_page_identity(paths, name, offset)
        count_rows = self._query(
            paths,
            "SELECT count(*) FROM party_procurements WHERE name = ?",
            [name],
        )
        if count_rows is None:
            return None
        total = count_rows[0][0]
        if total == 0:
            return [], 0
        rows = self._query(
            paths,
            f"""
            SELECT process_id, title, status, value_amount, value_currency,
                   closing_date
            FROM party_procurements
            WHERE name = ?
            ORDER BY closing_date DESC NULLS LAST, title
            LIMIT {PROCUREMENT_LIMIT} OFFSET ?
            """,
            [name, offset],
        )
        if rows is None:
            return None
        keys = (
            "process_id", "title", "status",
            "value_amount", "value_currency", "closing_date",
        )
        return [dict(zip(keys, row)) for row in rows], total

    def party_identity(
        self, paths: dict[str, Path], name: str
    ) -> dict[str, Any] | None:
        """Identity context for one observed name: variants sharing name_key."""
        rows = self._query(
            paths,
            """
            SELECT name_key, name
            FROM party_names
            WHERE name = ?
            ORDER BY name
            """,
            [name],
        )
        if rows is None:
            return None
        if not rows:
            return {"name_key": None, "variants": []}
        name_key = rows[0][0]
        if name_key is None:
            # No identity grouping for this name; it is its own scope.
            return {"name_key": None, "variants": [name]}
        variant_rows = self._query(
            paths,
            """
            SELECT DISTINCT name
            FROM party_names
            WHERE name_key = ?
            ORDER BY name
            """,
            [name_key],
        )
        if variant_rows is None:
            return None
        variants = [row[0] for row in variant_rows]
        return {"name_key": name_key, "variants": variants}

    def _party_page_identity(
        self, paths: dict[str, Path], name: str, offset: int
    ) -> tuple[list[dict[str, Any]], int] | None:
        """Process cards across every spelling that shares this name's key.

        Resolves spellings through the small `party_names` table (name ->
        name_key -> all names under that key), then queries the wide
        `party_procurements` table with `name IN (variants)`. This keeps
        name_key out of the wide table, which the 6GB build budget requires.
        """
        identity = self.party_identity(paths, name)
        if identity is None:
            return None
        variants = identity["variants"]
        if not variants or variants == [name]:
            # No identity grouping for this name: identity scope degenerates
            # to the exact-name view (honest fallback rather than an error).
            return self.party_page(paths, name, offset, scope="name")
        placeholders = ", ".join("?" for _ in variants)
        count_rows = self._query(
            paths,
            f"SELECT count(DISTINCT process_id) FROM party_procurements WHERE name IN ({placeholders})",
            list(variants),
        )
        if count_rows is None:
            return None
        total = count_rows[0][0]
        if total == 0:
            return [], 0
        rows = self._query(
            paths,
            f"""
            SELECT DISTINCT process_id, title, status, value_amount, value_currency,
                   closing_date
            FROM party_procurements
            WHERE name IN ({placeholders})
            ORDER BY closing_date DESC NULLS LAST, title
            LIMIT {PROCUREMENT_LIMIT} OFFSET ?
            """,
            [*variants, offset],
        )
        if rows is None:
            return None
        keys = (
            "process_id", "title", "status",
            "value_amount", "value_currency", "closing_date",
        )
        # All columns come from the shared `procurements` row, so DISTINCT
        # collapses spelling duplicates to exactly one card per process.
        return [dict(zip(keys, row)) for row in rows], total


class SearchService:
    def __init__(self, settings: Settings, pool: DuckDBPool, catalog: Catalog):
        self.settings = settings
        self.pool = pool
        self.catalog = catalog
        self.index = SearchIndex(settings)
        self._cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def warm(self) -> None:
        """Build the search index at startup (called from a daemon thread)."""
        snapshot = self.catalog.snapshot()
        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["name"] in INDEX_SOURCE_DATASETS and item["status"] == "healthy"
        }
        if len(paths) == len(INDEX_SOURCE_DATASETS):
            self.index.ensure(paths, blocking=True)
            # Touch the searchable columns once so the OS/DuckDB buffer
            # manager holds them: first user search skips cold disk reads.
            try:
                self.index._query(
                    paths, "SELECT count(title_lower) FROM procurements WHERE title_lower IS NOT NULL", []
                )
                self.index._query(
                    paths, "SELECT count(name_lower) FROM party_names WHERE name_lower IS NOT NULL", []
                )
            except Exception:
                pass  # warm-up is best-effort

    def search(
        self,
        raw_query: str,
        page: int = 0,
        *,
        statuses: tuple[str, ...] = (),
        year_from: int | None = None,
        year_to: int | None = None,
        outcomes: tuple[str, ...] = (),
        party_page: int = 0,
    ) -> dict[str, Any]:
        query = raw_query.strip()
        if len(query) < MIN_QUERY_LENGTH or len(query) > MAX_QUERY_LENGTH:
            raise QueryError(
                SEARCH_ERROR_INVALID,
                f"Search term must be {MIN_QUERY_LENGTH}-{MAX_QUERY_LENGTH} characters",
            )
        if page < 0 or page > MAX_PAGE:
            raise QueryError(SEARCH_ERROR_INVALID, "page out of range")
        if party_page < 0 or party_page > MAX_PAGE:
            raise QueryError(SEARCH_ERROR_INVALID, "party_page out of range")
        normalized_statuses = tuple(
            s for s in statuses if s in SEARCH_STATUSES
        )
        unknown_outcomes = tuple(
            o for o in outcomes if o not in OUTCOME_VALUES
        )
        if unknown_outcomes:
            # A typo like "partially-awarded" must not silently return an
            # unfiltered population.
            raise QueryError(
                SEARCH_ERROR_INVALID,
                f"unknown outcome filter(s): {', '.join(unknown_outcomes)}",
            )
        normalized_outcomes = tuple(outcomes)
        if not (MIN_FILTER_YEAR <= (year_from or MIN_FILTER_YEAR) <= MAX_FILTER_YEAR):
            raise QueryError(SEARCH_ERROR_INVALID, "year_from out of range")
        if not (MIN_FILTER_YEAR <= (year_to or MIN_FILTER_YEAR) <= MAX_FILTER_YEAR):
            raise QueryError(SEARCH_ERROR_INVALID, "year_to out of range")

        started = perf_counter()
        snapshot = self.catalog.snapshot()
        fingerprint = snapshot["dataset_fingerprint"]
        cache_key = (
            fingerprint, query.lower(), page, normalized_statuses, year_from,
            year_to, normalized_outcomes, party_page,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return {**cached, "cached": True}

        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        if "tenders" not in paths or "parties" not in paths:
            raise QueryError(
                SEARCH_ERROR_INVALID, "tenders/parties datasets are not available"
            )

        offset = page * PROCUREMENT_LIMIT
        # Index first; direct Parquet scans only as a fallback (or while the
        # first background build runs).
        titles = self.index.search_titles(
            paths,
            query,
            offset,
            statuses=normalized_statuses,
            year_from=year_from,
            year_to=year_to,
            outcomes=normalized_outcomes,
        )
        party_cards = self.index.search_parties(paths, query, party_page * PARTY_LIMIT)
        index_state = self.index.state(paths)
        if titles is None or party_cards is None:
            if titles is None:
                # Direct fallback cannot answer outcome filters honestly
                # (it has no outcome projection); refuse rather than
                # silently ignoring the filter.
                if normalized_outcomes:
                    raise QueryError(
                        SEARCH_ERROR_INVALID,
                        "outcome filters need the search index, which is still building",
                    )
                titles = self._search_titles_direct(
                    paths,
                    query,
                    offset,
                    statuses=normalized_statuses,
                    year_from=year_from,
                    year_to=year_to,
                )
            if party_cards is None:
                party_cards = self._search_parties_direct(
                    paths, query, party_page * PARTY_LIMIT
                )
            index_state = (
                self.index.state(paths) if index_state == "hit" else "direct"
            )
        procurements, procurement_total = titles
        parties, party_total = party_cards
        # Direct fallbacks don't pay for a total: derive an honest floor.
        # A full window guarantees at least one more result (keeps the
        # "More" button visible); a partial window is exact.
        if procurement_total < 0:
            procurement_total = offset + len(procurements) + (
                1 if len(procurements) == PROCUREMENT_LIMIT else 0
            )
        if party_total < 0:
            party_offset = party_page * PARTY_LIMIT
            party_total = party_offset + len(parties) + (
                1 if len(parties) == PARTY_LIMIT else 0
            )

        payload = {
            "query": query,
            "page": page,
            "party_page": party_page,
            "filters": {
                "statuses": list(normalized_statuses),
                "year_from": year_from,
                "year_to": year_to,
                "outcomes": list(normalized_outcomes),
            },
            "procurements": procurements,
            "procurement_total": procurement_total,
            "parties": parties,
            "party_total": party_total,
            "index": index_state,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        self._cache[cache_key] = payload
        while len(self._cache) > SEARCH_CACHE_LIMIT:
            self._cache.popitem(last=False)
        return payload

    def facets(self) -> dict[str, Any]:
        """Status/year facet counts for the filter bar."""
        snapshot = self.catalog.snapshot()
        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        result = self.index.filter_facets(paths)
        if result is None:
            return {"statuses": [], "years": [], "available": False}
        return {**result, "available": True}

    def party(self, name: str, page: int = 0, *, scope: str = "name") -> dict[str, Any]:
        """Researcher-facing party page: process cards for one observed name."""
        if page < 0 or page > MAX_PAGE:
            raise QueryError(SEARCH_ERROR_INVALID, "page out of range")
        if scope not in ("name", "identity"):
            raise QueryError(SEARCH_ERROR_INVALID, "scope must be name or identity")
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        if "parties" not in paths:
            raise QueryError(
                SEARCH_ERROR_INVALID, "parties dataset is not available"
            )

        cards = self.index.party_page(
            paths, name, page * PROCUREMENT_LIMIT, scope=scope
        )
        index_state = self.index.state(paths)
        if cards is None:
            # Fallback: direct scan joining roles -> compiled -> tenders.
            cards = self._party_direct(paths, name, page * PROCUREMENT_LIMIT)
            index_state = "direct"
        cards, total = cards
        if total < 0:
            total = page * PROCUREMENT_LIMIT + len(cards) + (
                1 if len(cards) == PROCUREMENT_LIMIT else 0
            )

        identity = self.index.party_identity(paths, name)
        variants = identity["variants"] if identity else []
        stats = self._party_stats(paths, name, scope, variants)
        contracts = self._party_contracts_by_year(
            paths, name, scope, variants
        )

        return {
            "name": name,
            "page": page,
            "scope": scope,
            "variants": variants,
            "stats": stats,
            "contracts_by_year": contracts,
            "procurements": cards,
            "total": total,
            "index": index_state,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }

    def _party_contracts_by_year(
        self,
        paths: dict[str, Path],
        name: str,
        scope: str,
        variants: list[str],
    ) -> dict[str, Any]:
        """Contracts awarded to this party per year, with a contract-first scope.

        Explicit identity scope (per TODO): identity aggregates every known
        spelling; name restricts to the exact observed name. Total value
        only reported when a single currency dominates the records.
        """
        names = variants if (scope == "identity" and len(variants) > 1) else [name]
        placeholders = ", ".join("?" for _ in names)
        lit_contracts = (
            sql_literal_path(paths["contracts"])
            if "contracts" in paths
            else None
        )
        lit_award_supp = (
            sql_literal_path(paths["award_suppliers"])
            if "award_suppliers" in paths
            else None
        )
        if lit_contracts is None or lit_award_supp is None:
            return {"available": False, "years": []}
        name_list = ", ".join("'" + n.replace("'","''") + "'" for n in names)
        sql = f"""
            WITH award_ids AS (
                SELECT DISTINCT award_id
                FROM read_parquet({lit_award_supp})
                WHERE source_supplier_label IN ({name_list})
            )
            SELECT year(c.period_start) AS y,
                   count(*) AS n,
                   sum(c.value_amount) AS total
            FROM read_parquet({lit_contracts}) c
            JOIN award_ids a USING (award_id)
            WHERE c.period_start IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """
        rows = self._literal_query(sql)
        if rows is None:
            return {"available": False, "years": []}
        years = []
        for y, n, total in rows:
            years.append(
                {
                    "year": int(y) if y is not None else None,
                    "count": int(n),
                    "value": str(total) if total is not None else None,
                }
            )
        return {"available": True, "years": years}

    def _literal_query(self, sql: str) -> list[tuple] | None:
        pool = self.catalog.pool
        with pool.connection() as connection:
            try:
                return connection.execute(sql).fetchall()
            except Exception:
                LOGGER.exception("party contracts query failed")
                return None

    def party_identity_full(
        self, name: str, paths: dict[str, Path] | None = None
    ) -> dict[str, Any] | None:
        """Full identity view for one observed name.

        Layers the ETL's provisional identity resolution on top of the
        name_key variants: the promoted canonical party (preferred name,
        match method, evidence counts), its other observed name forms, and
        sibling candidate groups that were NOT promoted (kept visible —
        unresolved is a finding, not an error). All provisional by design;
        the payload carries that label.
        """
        if paths is None:
            snapshot = self.catalog.snapshot()
            paths = {
                item["name"]: Path(item["path"])
                for item in snapshot["datasets"]
                if item["status"] == "healthy"
            }
        identity = self.index.party_identity(paths, name)
        if identity is None:
            return None
        variants = identity["variants"]
        lit_canon = (
            sql_literal_path(paths["canonical_parties"])
            if "canonical_parties" in paths
            else None
        )
        lit_aliases = (
            sql_literal_path(paths["party_aliases"])
            if "party_aliases" in paths
            else None
        )
        lit_candidates = (
            sql_literal_path(paths["party_resolution_candidates"])
            if "party_resolution_candidates" in paths
            else None
        )
        if lit_canon is None or lit_aliases is None or lit_candidates is None:
            return {
                "name_key": identity["name_key"],
                "variants": variants,
                "canonical": None,
                "other_name_forms": [],
                "unresolved_candidates": [],
                "available": False,
            }

        # Promoted canonical party: whose observed_name_forms include any
        # variant spelling of this name.
        forms_placeholders = ", ".join(
            "'" + v.replace("'", "''") + "'" for v in variants
        )
        canon_rows = self._duckdb_literal_query(
            lit_canon,
            f"""
            SELECT canonical_party_id, preferred_name, identity_status,
                   match_method, identity_quality_flags,
                   official_identifier_scheme, official_identifier,
                   supported_name_form_count, supporting_party_mentions,
                   total_candidate_mentions, unresolved_mentions,
                   role_family
            FROM read_parquet({lit_canon})
            WHERE len(list_intersect(
                observed_name_forms,
                [{forms_placeholders}]
            )) > 0
            LIMIT 1
            """,
        )
        canonical = None
        other_forms: list[str] = []
        if canon_rows:
            canonical = canon_rows[0]
            canon_rows2 = self._duckdb_literal_query(
                lit_canon,
                f"""
                SELECT DISTINCT unnest(observed_name_forms) AS form
                FROM read_parquet({lit_canon})
                WHERE canonical_party_id = '{canonical['canonical_party_id']}'
                """,
            )
            if canon_rows2:
                other_forms = [
                    r["form"] for r in canon_rows2 if r["form"] not in variants
                ]
        # Alias evidence: distinct observed names mapped to this canonical.
        alias_rows = (
            self._duckdb_literal_query(
                lit_aliases,
                f"""
                SELECT DISTINCT observed_name
                FROM read_parquet({lit_aliases})
                WHERE canonical_party_id = '{canonical['canonical_party_id'] if canonical else ''}'
                ORDER BY 1 LIMIT 30
                """,
            )
            if canonical
            else None
        )
        alias_forms = [r["observed_name"] for r in (alias_rows or [])]
        other_forms = sorted(set(other_forms) | set(alias_forms))

        # Sibling candidate groups that share a name form but were NOT
        # promoted — resolution_status 'unresolved' rows mentioning one of
        # the variant spellings.
        cand_rows = self._duckdb_literal_query(
            lit_candidates,
            f"""
            SELECT candidate_group_id,
                   any_value(observed_name) AS example_name,
                   count(DISTINCT observed_name) AS form_count,
                   max(group_party_mentions) AS mentions,
                   any_value(resolution_status) AS status,
                   any_value(candidate_basis) AS basis
            FROM read_parquet({lit_candidates})
            WHERE observed_name IN ({forms_placeholders})
            GROUP BY 1 ORDER BY mentions DESC LIMIT 8
            """
            if forms_placeholders
            else "SELECT 1 WHERE FALSE",
        )
        unresolved_candidates = [
            {
                "candidate_group_id": r["candidate_group_id"],
                "example_name": r["example_name"],
                "form_count": r["form_count"],
                "mentions": r["mentions"],
                "status": r["status"],
                "basis": r["basis"],
            }
            for r in (cand_rows or [])
            if r["status"] != "promoted"
        ]
        return self._to_jsonable_payload(
            {
                "name_key": identity["name_key"],
                "variants": variants,
                "canonical": canonical,
                "other_name_forms": other_forms,
                "unresolved_candidates": unresolved_candidates,
                "available": True,
            }
        )

    @staticmethod
    def _to_jsonable_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: SearchService._jsonable(value) for key, value in payload.items()}

    def _duckdb_literal_query(
        self, lit_path: str, sql: str
    ) -> list[dict[str, Any]] | None:
        """Run one bounded literal-SQL query on the shared pool connection.

        Uses fetchall + cursor description (not fetchdf) so DuckDB LIST
        columns arrive as plain Python lists — pandas/numpy arrays break
        FastAPI's JSON encoder (500 on response serialization).
        """
        pool = self.catalog.pool
        with pool.connection() as connection:
            try:
                cursor = connection.execute(sql)
                names = [d[0] for d in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]
            except Exception:
                logger.exception("identity query failed")
                return None

    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Coerce numpy scalars/arrays from DuckDB results to plain JSON types."""
        if np is not None:
            if isinstance(value, np.ndarray):
                return [SearchService._jsonable(item) for item in value.tolist()]
            if isinstance(value, np.generic):
                return value.item()
        return value
    def _party_stats(
        self,
        paths: dict[str, Path],
        name: str,
        scope: str,
        variants: list[str],
    ) -> dict[str, Any]:
        """Role split, counterparty breadth, and value-over-time for a party.

        Aggregates over the small `party_names` table and the wide
        `party_procurements` table via LIKE-free exact-name matches only.
        Identity scope aggregates across every variant spelling.
        """
        names = variants if (scope == "identity" and len(variants) > 1) else [name]
        placeholders = ", ".join("?" for _ in names)
        # Role split from the roles column stored on each observed name.
        role_rows = self.index._query(
            paths,
            f"SELECT roles FROM party_names WHERE name IN ({placeholders})",
            names,
        )
        role_split: dict[str, int] = {}
        if role_rows:
            for (joined,) in role_rows:
                for role in (joined or "").split(","):
                    role = role.strip()
                    if role:
                        role_split[role] = role_split.get(role, 0) + 1
        # Procurement-window aggregates: distinct counterparty-ish process
        # count and value-over-time come from the one-row-per-process cards.
        card_rows = self.index._query(
            paths,
            f"""
            SELECT year(closing_date), status, value_amount, value_currency, role
            FROM party_procurements
            WHERE name IN ({placeholders})
            """,
            names,
        )
        by_year: dict[int, dict[str, Any]] = {}
        statuses_count: dict[str, int] = {}
        total_value = Decimal("0")
        value_currency: str | None = None
        mixed = False
        if card_rows:
            for year, status, amount, currency, _role in card_rows:
                if status is None:
                    status = "none"
                statuses_count[status] = statuses_count.get(status, 0) + 1
                if year is not None:
                    entry = by_year.setdefault(
                        year, {"count": 0, "value": Decimal("0"), "has_value": False}
                    )
                    entry["count"] += 1
                    if amount is not None:
                        entry["value"] += Decimal(str(amount))
                        entry["has_value"] = True
                if amount is not None:
                    if value_currency is None:
                        value_currency = currency
                    elif currency != value_currency:
                        mixed = True
                    total_value += Decimal(str(amount))
        value_over_time = [
            {
                "year": year,
                "count": entry["count"],
                "value": str(entry["value"]) if entry["has_value"] else None,
            }
            for year, entry in sorted(by_year.items())
        ]
        return {
            "role_split": [
                {"role": role, "count": count}
                for role, count in sorted(
                    role_split.items(), key=lambda kv: -kv[1]
                )
            ],
            "status_counts": [
                {"status": status, "count": count}
                for status, count in sorted(
                    statuses_count.items(), key=lambda kv: -kv[1]
                )
            ],
            "value_over_time": value_over_time,
            "total_value": str(total_value) if card_rows and total_value else None,
            "value_currency": value_currency,
            "value_comparable": not mixed,
        }

    # ------------------------------------------------- direct (fallback)

    def _search_titles_direct(
        self,
        paths: dict[str, Path],
        query: str,
        offset: int,
        *,
        statuses: tuple[str, ...] = (),
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """One process card per matching procurement, via preferred releases."""
        lit_tenders = sql_literal_path(paths["tenders"])
        lit_compiled = (
            sql_literal_path(paths["compiled_processes"])
            if "compiled_processes" in paths
            else None
        )
        where, filter_params = _procurement_filter_clause(statuses, year_from, year_to)

        if lit_compiled:
            # Preferred release only: one card per process, no re-announcements.
            sql = f"""
                SELECT cp.process_id, t.title, t.status,
                       t.value_amount, t.value_currency, t.closing_date
                FROM read_parquet({lit_compiled}) cp
                JOIN read_parquet({lit_tenders}) t
                  ON t.release_id = cp.preferred_release_id
                WHERE t.title ILIKE '%' || ? || '%'{where}
                QUALIFY row_number() OVER (
                    PARTITION BY cp.process_id ORDER BY t.tender_id
                ) = 1
                ORDER BY t.closing_date DESC NULLS LAST, t.title
                LIMIT {PROCUREMENT_LIMIT} OFFSET ?
            """
        else:
            sql = f"""
                SELECT NULL::VARCHAR AS process_id, title, status,
                       value_amount, value_currency, closing_date
                FROM read_parquet({lit_tenders})
                WHERE title ILIKE '%' || ? || '%'{where}
                ORDER BY closing_date DESC NULLS LAST, title
                LIMIT {PROCUREMENT_LIMIT} OFFSET ?
            """
        names, rows, _ = execute_bounded(
            self.pool,
            sql,
            [query, *filter_params, offset],
            self.settings.api.query_timeout_seconds,
        )
        return [dict(zip(names, row)) for row in rows], -1  # -1: unknown total

    def _search_parties_direct(
        self, paths: dict[str, Path], query: str, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Party-name cards with observed roles and release counts."""
        lit_parties = sql_literal_path(paths["parties"])
        lit_roles = (
            sql_literal_path(paths["party_roles"])
            if "party_roles" in paths
            else None
        )

        if lit_roles:
            sql = f"""
                SELECT p.name,
                       string_agg(DISTINCT pr.role, ',') AS roles,
                       count(DISTINCT pr.release_id)::BIGINT AS release_count
                FROM read_parquet({lit_parties}) p
                JOIN read_parquet({lit_roles}) pr
                  ON pr.release_id = p.release_id AND pr.party_id = p.party_id
                WHERE p.name ILIKE '%' || ? || '%'
                GROUP BY p.name
                ORDER BY release_count DESC, p.name
                LIMIT {PARTY_LIMIT} OFFSET ?
            """
        else:
            sql = f"""
                SELECT name, NULL::VARCHAR AS roles, 0::BIGINT AS release_count
                FROM read_parquet({lit_parties})
                WHERE name ILIKE '%' || ? || '%'
                GROUP BY name
                ORDER BY count(*) DESC
                LIMIT {PARTY_LIMIT} OFFSET ?
            """
        names, rows, _ = execute_bounded(
            self.pool, sql, [query, offset], self.settings.api.query_timeout_seconds
        )
        results = []
        for row in rows:
            entry = dict(zip(names, row))
            entry["roles"] = (
                (entry.get("roles") or "").split(",") if entry.get("roles") else []
            )
            results.append(entry)
        return results, -1  # -1: unknown total

    def _party_direct(
        self, paths: dict[str, Path], name: str, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Fallback party page without the index."""
        lit_parties = sql_literal_path(paths["parties"])
        lit_roles = sql_literal_path(paths["party_roles"])
        lit_compiled = sql_literal_path(paths["compiled_processes"])
        lit_tenders = sql_literal_path(paths["tenders"])
        sql = f"""
            SELECT cp.process_id, t.title, t.status,
                   t.value_amount, t.value_currency, t.closing_date
            FROM read_parquet({lit_parties}) p
            JOIN read_parquet({lit_roles}) pr
              ON pr.release_id = p.release_id AND pr.party_id = p.party_id
            JOIN read_parquet({lit_compiled}) cp
              ON cp.preferred_release_id = pr.release_id
            JOIN read_parquet({lit_tenders}) t
              ON t.release_id = cp.preferred_release_id
            WHERE p.name = ?
            QUALIFY row_number() OVER (
                PARTITION BY cp.process_id ORDER BY t.tender_id
            ) = 1
            ORDER BY t.closing_date DESC NULLS LAST, t.title
            LIMIT {PROCUREMENT_LIMIT} OFFSET ?
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [name, offset], self.settings.api.query_timeout_seconds
        )
        return [dict(zip(names, row)) for row in rows], -1  # -1: unknown total
