"""Breadcrumb and record-source traceability lookups.

Implements the audit path from `docs/02_architecture.md`:

    record type + record id
        -> record_sources rows
        -> (source_file_id, source_sheet, source_row_number)
        -> complete normalized + cleaned observation
        -> manifest filename and source URL

All SQL is parameterized; paths come only from configuration. Both lookup
directions are bounded (source observation lookup by breadcrumb tuple;
record-source lookup by exact record key).
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from time import perf_counter
from typing import Any

from .catalog import Catalog
from .config import Settings
from .database import DuckDBPool, execute_bounded, sql_literal_path
from .provenance import ProvenanceCache
from .query import QueryError, _json_value

TRACE_ERROR_UNKNOWN_BREADCRUMB = "unknown_breadcrumb"
TRACE_ERROR_UNKNOWN_RECORD = "unknown_record"
TRACE_ERROR_UNKNOWN_RELEASE = "unknown_release"

# Bound for the raw source-rows table: one spreadsheet screenful.
MAX_SOURCE_ROWS = 100

# registry record_type -> (table, pk columns used as record identity)
RECORD_IDENTITY = {
    "release": ("releases", ["release_id"]),
    "tender": ("tenders", ["release_id", "tender_id"]),
    "tender_item": ("tender_items", ["release_id", "item_id"]),
    "award": ("awards", ["release_id", "award_id"]),
    "award_supplier_assertion": ("award_suppliers", ["award_supplier_assertion_id"]),
    "contract": ("contracts", ["release_id", "contract_id"]),
    "party": ("parties", ["release_id", "party_id"]),
    "data_quality_issue": ("data_quality_issues", ["issue_id"]),
}


class TraceabilityService:
    def __init__(self, settings: Settings, pool: DuckDBPool, catalog: Catalog,
                 provenance: ProvenanceCache | None = None):
        self.settings = settings
        self.pool = pool
        self.catalog = catalog
        self.provenance = provenance
        # Manifest is parsed once per (path, size, mtime) and reused: the
        # JSON is tens of thousands of entries and re-reading it per request
        # dominated breadcrumb/source lookups.
        self._manifest_lock = threading.Lock()
        # (stamp, manifest, files_by_id, docs_by_id)
        self._manifest_cache: (
            tuple[tuple[int, int], dict[str, Any], dict[str, Any], dict[str, Any]] | None
        ) = None
        # Breadcrumb resolves scan 2.5GB of normalized+cleaned Parquet on a
        # miss; bounded LRU keyed to the dataset fingerprint.
        self._breadcrumb_cache: OrderedDict[
            tuple[str, str, int, str | None], dict[str, Any]
        ] = OrderedDict()
        self._breadcrumb_cache_limit = 256

    def _record_sources_path(self) -> Path | None:
        snapshot = self.catalog.snapshot()
        for dataset in snapshot["datasets"]:
            if dataset["name"] == "record_sources" and dataset["status"] == "healthy":
                return Path(dataset["path"])
        return None

    def _load_manifest(self) -> dict[str, Any]:
        path = self.settings.manifest
        if not path.exists():
            return {"status": "missing", "source_files": [], "documents": []}
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        with self._manifest_lock:
            if self._manifest_cache is not None and self._manifest_cache[0] == stamp:
                return self._manifest_cache[1]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        files_by_id = {
            entry.get("source_file_id"): entry
            for entry in manifest.get("source_files", [])
        }
        docs_by_id = {
            entry.get("document_id"): entry
            for entry in manifest.get("documents", [])
        }
        with self._manifest_lock:
            self._manifest_cache = (stamp, manifest, files_by_id, docs_by_id)  # type: ignore[assignment]
        return manifest

    def _files_by_id(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        with self._manifest_lock:
            if self._manifest_cache is not None:
                return self._manifest_cache[2]
        return {
            entry.get("source_file_id"): entry
            for entry in manifest.get("source_files", [])
        }

    def _docs_by_id(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        with self._manifest_lock:
            if self._manifest_cache is not None:
                return self._manifest_cache[3]
        return {
            entry.get("document_id"): entry
            for entry in manifest.get("documents", [])
        }

    def _manifest_entry(self, manifest: dict[str, Any], source_file_id: str) -> dict[str, Any] | None:
        for entry in manifest.get("source_files", []):
            if entry.get("source_file_id") == source_file_id:
                return entry
        return None

    def _document_entry(self, manifest: dict[str, Any], document_id: str) -> dict[str, Any] | None:
        for entry in manifest.get("documents", []):
            if entry.get("document_id") == document_id:
                return entry
        return None

    def _safe_url(self, url: str | None) -> str | None:
        if not url:
            return None
        return url if url.startswith(("http://", "https://")) else None

    # --------------------------------------------------------- breadcrumb

    def resolve_breadcrumb(
        self, source_file_id: str, source_row_number: int, source_sheet: str | None = None
    ) -> dict[str, Any]:
        # Each miss scans the multi-GB normalized/cleaned layers; memoize
        # like the process caches (fingerprint-keyed, LRU, bounded).
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        cache_key = (
            snapshot["dataset_fingerprint"], source_file_id, source_row_number, source_sheet,
        )
        cached = self._breadcrumb_cache.get(cache_key)
        if cached is not None:
            self._breadcrumb_cache.move_to_end(cache_key)
            return {**cached, "cached": True}
        normalized_literal = sql_literal_path(self.settings.normalized_parquet)
        cleaned_literal = sql_literal_path(self.settings.cleaned_parquet)

        sheet_predicate = "AND _source_sheet = ?" if source_sheet else ""
        sheet_params = [source_sheet] if source_sheet else []
        sql = f"""
            SELECT * FROM read_parquet({normalized_literal})
            WHERE _source_file_id = ? AND _source_row_number = ? {sheet_predicate}
            LIMIT 2
        """
        names, rows, elapsed = execute_bounded(
            self.pool, sql, [source_file_id, source_row_number, *sheet_params],
            self.settings.api.query_timeout_seconds,
        )
        if not rows:
            raise QueryError(
                TRACE_ERROR_UNKNOWN_BREADCRUMB,
                "No normalized observation matches this breadcrumb",
            )
        normalized = dict(zip(names, (_json_value(v) for v in rows[0])))
        ambiguous = len(rows) > 1

        sql = f"""
            SELECT * FROM read_parquet({cleaned_literal})
            WHERE _source_file_id = ? AND _source_row_number = ? {sheet_predicate}
            LIMIT 2
        """
        cleaned_names, cleaned_rows, _ = execute_bounded(
            self.pool, sql, [source_file_id, source_row_number, *sheet_params],
            self.settings.api.query_timeout_seconds,
        )
        cleaned = (
            dict(zip(cleaned_names, (_json_value(v) for v in cleaned_rows[0])))
            if cleaned_rows else None
        )

        manifest = self._load_manifest()
        entry = self._manifest_entry(manifest, source_file_id)
        docs_by_id = self._docs_by_id()
        documents = []
        source_url: str | None = None
        title: str | None = None
        if entry:
            for doc_id in entry.get("document_ids", []):
                doc = docs_by_id.get(doc_id)
                if doc:
                    documents.append(doc)
                    if title is None:
                        title = doc.get("title")
                    if source_url is None:
                        source_url = self._safe_url(doc.get("source_url"))

        # Reverse lookup: every derived record linked to this source row.
        snapshot = self.catalog.snapshot()
        record_sources_path = None
        for dataset in snapshot["datasets"]:
            if dataset["name"] == "record_sources" and dataset["status"] == "healthy":
                record_sources_path = dataset["path"]
                break
        derived: list[dict[str, Any]] = []
        if record_sources_path:
            rs_literal = sql_literal_path(Path(record_sources_path))
            sql = f"""
                SELECT record_type, record_id, release_id
                FROM read_parquet({rs_literal})
                WHERE source_file_id = ? AND source_row_number = ?
                LIMIT 500
            """
            _, rs_rows, _ = execute_bounded(
                self.pool, sql, [source_file_id, source_row_number],
                self.settings.api.query_timeout_seconds,
            )
            for record_type, record_id, release_id in rs_rows:
                derived.append({
                    "record_type": record_type,
                    "record_id": record_id,
                    "release_id": release_id,
                })

        payload = {
            "breadcrumb": {
                "source_file_id": source_file_id,
                "source_row_number": source_row_number,
                "source_sheet": source_sheet,
                "ambiguous": ambiguous,
            },
            "manifest": {
                "status": entry is not None and "found" or "missing",
                "normalized_file_name": entry.get("normalized_file_name") if entry else None,
                "local_files": entry.get("local_files") if entry else None,
                "sha256": entry.get("sha256") if entry else None,
                "document_titles": [d.get("title") for d in documents],
                "source_url": source_url,
            },
            "normalized_observation": normalized,
            "cleaned_observation": cleaned or None,
            "derived_records": derived,
            "derived_record_count": len(derived),
            "elapsed_ms": elapsed,
        }
        self._breadcrumb_cache[cache_key] = payload
        while len(self._breadcrumb_cache) > self._breadcrumb_cache_limit:
            self._breadcrumb_cache.popitem(last=False)
        return payload

    # ---------------------------------------------------- record sources

    def source_file_rows(
        self, source_file_id: str, start_row: int, end_row: int
    ) -> dict[str, Any]:
        """Raw source observations for one file, between two row numbers.

        This is the "open the spreadsheet and look" view: the normalized
        layer holds the observed CSV/XLSX values as-is, so rendering them
        in a table lets a researcher verify derived records against the
        PhilGEPS source without leaving the tool. Bounded to 100 rows.
        """
        if end_row < start_row:
            start_row, end_row = end_row, start_row
        if start_row < 1:
            raise QueryError("invalid_row_range", "Row numbers start at 1")
        if end_row - start_row >= MAX_SOURCE_ROWS:
            end_row = start_row + MAX_SOURCE_ROWS - 1
        normalized_literal = sql_literal_path(self.settings.normalized_parquet)
        sql = f"""
            SELECT _source_row_number, * EXCLUDE (_source_row_number)
            FROM read_parquet({normalized_literal})
            WHERE _source_file_id = ? AND _source_row_number BETWEEN ? AND ?
            ORDER BY _source_row_number
            LIMIT {MAX_SOURCE_ROWS + 1}
        """
        names, rows, elapsed = execute_bounded(
            self.pool, sql, [source_file_id, start_row, end_row],
            self.settings.api.query_timeout_seconds,
        )
        if not rows:
            raise QueryError(
                "unknown_source_file",
                "No source observations match this file and row range",
            )
        truncated = len(rows) > MAX_SOURCE_ROWS
        rows = rows[:MAX_SOURCE_ROWS]
        manifest = self._load_manifest()
        entry = self._manifest_entry(manifest, source_file_id)
        docs_by_id = self._docs_by_id()
        source_url: str | None = None
        documents: list[dict[str, Any]] = []
        if entry:
            for doc_id in entry.get("document_ids", []):
                doc = docs_by_id.get(doc_id)
                if doc:
                    documents.append({"title": doc.get("title"),
                                      "source_url": self._safe_url(doc.get("source_url"))})
                    if source_url is None:
                        source_url = self._safe_url(doc.get("source_url"))
        return {
            "source_file_id": source_file_id,
            "start_row": start_row,
            "end_row": end_row,
            "columns": list(names)[1:],  # names[0] is the row number
            "row_numbers": [int(r[0]) for r in rows],
            "rows": [[_json_value(v) for v in r[1:]] for r in rows],
            "truncated": truncated,
            "manifest": {
                "status": "found" if entry else "missing",
                "normalized_file_name": entry.get("normalized_file_name") if entry else None,
                "documents": documents,
                "source_url": source_url,
            },
            "elapsed_ms": elapsed,
        }

    def release_sources(self, release_id: str) -> dict[str, Any]:
        """Human-readable source references for one release.

        Aggregates the release's record_sources rows per source file into
        row ranges ("rows 245,359–245,372") with manifest metadata (file
        name, source URL), so researchers can trace a procurement back to
        the PhilGEPS spreadsheet without touching pipeline keys.
        """
        record_sources_path = self._record_sources_path()
        if not record_sources_path:
            raise QueryError(
                TRACE_ERROR_UNKNOWN_RELEASE,
                "record_sources dataset is not available",
            )
        started = perf_counter()
        rs_literal = sql_literal_path(record_sources_path)
        # Aggregation happens in DuckDB (min/max/count/distinct record types)
        # so only per-file summaries cross the wire.
        names, rows, elapsed = execute_bounded(
            self.pool,
            f"""
            SELECT source_file_id,
                   source_sheet,
                   min(source_row_number) AS first_row,
                   max(source_row_number) AS last_row,
                   count(*) AS row_refs,
                   count(DISTINCT record_type) AS record_types
            FROM read_parquet({rs_literal})
            WHERE release_id = ?
            GROUP BY 1, 2
            ORDER BY row_refs DESC
            LIMIT 50
            """,
            [release_id],
            self.settings.api.query_timeout_seconds,
        )
        if not rows:
            # Unknown release and empty release are indistinguishable here;
            # report empty so the UI can phrase it honestly.
            return {
                "release_id": release_id,
                "files": [],
                "returned": 0,
                "elapsed_ms": elapsed,
            }

        manifest = self._load_manifest()
        files_by_id = self._files_by_id()
        docs_by_id = self._docs_by_id()
        files = []
        for (file_id, sheet, first_row, last_row, row_refs, record_types) in rows:
            entry = files_by_id.get(file_id)
            documents = []
            source_url = None
            if entry:
                for doc_id in entry.get("document_ids", []):
                    doc = docs_by_id.get(doc_id)
                    if doc:
                        documents.append({"title": doc.get("title"),
                                          "source_url": self._safe_url(doc.get("source_url"))})
                        if source_url is None:
                            source_url = self._safe_url(doc.get("source_url"))
            files.append({
                "source_file_id": file_id,
                "source_sheet": sheet,
                "first_row": int(first_row),
                "last_row": int(last_row),
                "row_refs": int(row_refs),
                "record_types": int(record_types),
                "normalized_file_name": entry.get("normalized_file_name") if entry else None,
                "local_files": entry.get("local_files") if entry else None,
                "documents": documents,
                "source_url": source_url,
            })
        return {
            "release_id": release_id,
            "files": files,
            "returned": len(files),
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }

    def record_sources(
        self,
        record_type: str,
        record_id: str,
        release_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        record_sources_path = self._record_sources_path()
        if not record_sources_path:
            raise QueryError(
                TRACE_ERROR_UNKNOWN_RECORD,
                "record_sources dataset is not available",
            )
        if record_type not in RECORD_IDENTITY:
            raise QueryError(
                "invalid_record_type",
                f"Unknown record type; expected one of: {', '.join(sorted(RECORD_IDENTITY))}",
            )

        started = perf_counter()
        cache_status = "disabled"
        rows: list[tuple] | None = None
        if self.provenance is not None:
            self.provenance.record_sources_path = record_sources_path
            cache_status = self.provenance.state()
            rows = self.provenance.lookup(record_type, record_id, release_id, limit + 1)
            if rows is not None:
                cache_status = "hit"
            elif self.provenance.state() == "building":
                cache_status = "building"
        if rows is None:
            # Fallback: direct scan of the authoritative Parquet.
            rs_literal = sql_literal_path(record_sources_path)
            release_predicate = "AND release_id = ?" if release_id else ""
            release_params = [release_id] if release_id else []
            sql = f"""
                SELECT release_id, source_file_id, source_sheet, source_row_number
                FROM read_parquet({rs_literal})
                WHERE record_type = ? AND record_id = ? {release_predicate}
                LIMIT ?
            """
            names, rows, _ = execute_bounded(
                self.pool, sql,
                [record_type, record_id, *release_params, limit + 1],
                self.settings.api.query_timeout_seconds,
            )
            if cache_status == "hit":
                cache_status = "hit"  # defensive; unreachable in practice
        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        truncated = len(rows) > limit
        rows = rows[:limit]
        # Fetch manifest metadata for every referenced source file in one pass.
        files_by_id = self._files_by_id()
        docs_by_id = self._docs_by_id()
        sources = []
        for release, file_id, sheet, row_number in rows:
            entry = files_by_id.get(file_id)
            source_url = None
            if entry:
                for doc_id in entry.get("document_ids", []):
                    doc = docs_by_id.get(doc_id)
                    if doc:
                        source_url = self._safe_url(doc.get("source_url"))
                        if source_url:
                            break
            sources.append({
                "release_id": release,
                "source_file_id": file_id,
                "source_sheet": sheet,
                "source_row_number": row_number,
                "normalized_file_name": entry.get("normalized_file_name") if entry else None,
                "source_url": source_url,
            })
        return {
            "record_type": record_type,
            "record_id": record_id,
            "sources": sources,
            "returned": len(sources),
            "truncated": truncated,
            "cache": cache_status,
            "elapsed_ms": elapsed_ms,
        }
