"""Process-explorer lookups: identity, preferred release, and release timeline.

Implements the audit-friendly process view from `docs/08_search_filter_and_common_views.md`:

    process detail
        -> contracting_processes (base identity)
        -> compiled_processes (preferred release + selection basis)
        -> releases (timeline: every observed lifecycle state)

Child records (tender, awards, contracts, parties, issues) stay on the
existing table-query API filtered by `release_id`, so this service adds only
what cannot be expressed there: the process identity block, the
preferred/alternate release structure, and the ordered release timeline.
"""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from time import perf_counter
from typing import Any

from .catalog import Catalog
from .config import Settings
from .database import DuckDBPool, execute_bounded, sql_literal_path
from .derivation import outcome_metadata, relationship_metadata, relationship_status
from .outcomes import OUTCOME_LABELS, OutcomesService
from .query import QueryError

PROCESS_ERROR_UNKNOWN = "unknown_process"

# Bounded in-memory memo for per-release child counts: repeat looks at the
# same release (toggling timeline rows, reopening the drawer) are served from
# memory instead of rescanning multi-GB Parquets. Keyed to the dataset
# fingerprint so data refreshes invalidate it automatically.
COUNT_CACHE_LIMIT = 256

# Same memoization rationale as COUNT_CACHE_LIMIT, for full summaries.
SUMMARY_CACHE_LIMIT = 128

# Detail blocks are small (one row) but the underlying joins scan multi-GB
# Parquets; memoize like the summary, keyed to the dataset fingerprint.
DETAIL_CACHE_LIMIT = 512

# Release timelines are per-process row sets bounded by `limit`; repeat
# visits (reopening the drawer, drill-down round-trips) hit memory instead.
TIMELINE_CACHE_LIMIT = 256

# dataset name -> path (resolved from the registry, only when healthy)
_DATASET_NAMES = ("contracting_processes", "compiled_processes", "releases")


class ProcessService:
    def __init__(self, settings: Settings, pool: DuckDBPool, catalog: Catalog):
        self.settings = settings
        self.pool = pool
        self.catalog = catalog
        self._count_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._summary_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._detail_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._timeline_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------- helpers

    def _path(self, dataset: str) -> Path:
        snapshot = self.catalog.snapshot()
        for item in snapshot["datasets"]:
            if item["name"] == dataset and item["status"] == "healthy":
                return Path(item["path"])
        raise QueryError(
            PROCESS_ERROR_UNKNOWN, f"{dataset} dataset is not available"
        )

    @staticmethod
    def _row(names: list[str], values: tuple) -> dict[str, Any]:
        def clean(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, (bytes, bytearray)):
                return value.hex()
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return value

        return {name: clean(value) for name, value in zip(names, values)}

    # -------------------------------------------------------------- detail

    def detail(self, process_id: str) -> dict[str, Any]:
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        cache_key = (snapshot["dataset_fingerprint"], process_id)
        cached = self._detail_cache.get(cache_key)
        if cached is not None:
            self._detail_cache.move_to_end(cache_key)
            return {**cached, "cached": True}
        cp = self._path("contracting_processes")
        compiled = self._path("compiled_processes")
        sql = f"""
            SELECT
                cp.process_id, cp.ocid, cp.source_process_identifier,
                cp.source_identifier_basis, cp.release_count,
                cp.process_quality_flags,
                pr.preferred_release_id, pr.preferred_release_date,
                pr.preferred_release_date_basis, pr.selection_basis,
                pr.alternate_release_ids, pr.has_multiple_releases,
                pr.has_release_date_tie, pr.distinct_content_hash_count,
                pr.compilation_rule_version, pr.compilation_quality_flags
            FROM read_parquet({sql_literal_path(cp)}) cp
            JOIN read_parquet({sql_literal_path(compiled)}) pr
                ON cp.process_id = pr.process_id
            WHERE cp.process_id = ?
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [process_id], self.settings.api.query_timeout_seconds
        )
        if not rows:
            raise QueryError(
                PROCESS_ERROR_UNKNOWN, f"Process {process_id} not found"
            )
        detail = self._row(names, rows[0])
        detail["elapsed_ms"] = round((perf_counter() - started) * 1000, 1)
        snapshot = self.catalog.snapshot()
        cache_key = (snapshot["dataset_fingerprint"], process_id)
        self._detail_cache[cache_key] = detail
        while len(self._detail_cache) > DETAIL_CACHE_LIMIT:
            self._detail_cache.popitem(last=False)
        return detail

    # ------------------------------------------------------------ timeline

    def timeline(self, process_id: str, limit: int = 200) -> dict[str, Any]:
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        cache_key = (snapshot["dataset_fingerprint"], f"{process_id}:{limit}")
        cached = self._timeline_cache.get(cache_key)
        if cached is not None:
            self._timeline_cache.move_to_end(cache_key)
            return {**cached, "cached": True}
        releases = self._path("releases")
        sql = f"""
            SELECT
                release_id, release_date, release_date_basis, content_hash,
                has_tender, has_award, has_contract,
                supporting_observation_rows, supporting_source_files,
                source_file_ids
            FROM read_parquet({sql_literal_path(releases)})
            WHERE process_id = ?
            ORDER BY release_date NULLS LAST, release_id
            LIMIT ?
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [process_id, limit],
            self.settings.api.query_timeout_seconds,
        )
        releases_list = [self._row(names, row) for row in rows]
        payload = {
            "process_id": process_id,
            "releases": releases_list,
            "returned": len(releases_list),
            "truncated": len(rows) == limit,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        self._timeline_cache[cache_key] = payload
        while len(self._timeline_cache) > TIMELINE_CACHE_LIMIT:
            self._timeline_cache.popitem(last=False)
        return payload

    # ----------------------------------------------------- release compare

    # Scalar tender fields compared side-by-side. Keys are researcher-facing
    # labels; values are the Parquet column names.
    TENDER_COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
        ("title", "title"),
        ("status", "status"),
        ("procurement_method", "procurement_method"),
        ("value_amount", "value_amount"),
        ("value_currency", "value_currency"),
        ("closing_date", "closing_date"),
        ("bid_reference", "source_bid_reference"),
    )
    AWARD_COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
        ("title", "title"),
        ("value_amount", "value_amount"),
        ("value_currency", "value_currency"),
        ("date", "date"),
        ("award_reference", "source_award_reference"),
    )
    CONTRACT_COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
        ("contract_number", "source_contract_number"),
        ("value_amount", "value_amount"),
        ("value_currency", "value_currency"),
        ("period_start", "period_start"),
        ("period_end", "period_end"),
        ("award_reference", "source_award_reference"),
    )

    def compare_releases(
        self,
        process_id: str,
        left_release_id: str,
        right_release_id: str,
    ) -> dict[str, Any]:
        """Field-level diff of two releases belonging to the same process.

        Distinguishes added / removed / changed / unchanged for:
          - tender scalars (0–1 row per release)
          - awards keyed by ``source_award_reference`` (falls back to title+amount)
          - contracts keyed by ``source_contract_number`` (falls back to award ref)

        Honest-data rules: releases that do not belong to ``process_id`` are
        rejected; missing datasets degrade that section rather than 500-ing.
        """
        started = perf_counter()
        if left_release_id == right_release_id:
            raise QueryError(
                "invalid_compare", "left and right release ids must differ"
            )
        # Confirm both releases belong to this process.
        releases = self._path("releases")
        sql = f"""
            SELECT release_id, release_date, release_date_basis, content_hash,
                   has_tender, has_award, has_contract
            FROM read_parquet({sql_literal_path(releases)})
            WHERE process_id = ? AND release_id IN (?, ?)
        """
        names, rows, _ = execute_bounded(
            self.pool,
            sql,
            [process_id, left_release_id, right_release_id],
            self.settings.api.query_timeout_seconds,
        )
        by_id = {row[0]: self._row(names, row) for row in rows}
        if left_release_id not in by_id or right_release_id not in by_id:
            raise QueryError(
                PROCESS_ERROR_UNKNOWN,
                "One or both releases are missing from this process",
            )

        tender = self._compare_singleton(
            "tenders",
            left_release_id,
            right_release_id,
            self.TENDER_COMPARE_FIELDS,
            """
            SELECT title, status, procurement_method, value_amount, value_currency,
                   closing_date, source_bid_reference
            FROM read_parquet({path})
            WHERE release_id = ?
            LIMIT 1
            """,
        )
        awards = self._compare_collection(
            "awards",
            left_release_id,
            right_release_id,
            self.AWARD_COMPARE_FIELDS,
            """
            SELECT award_id, title, value_amount, value_currency, date,
                   source_award_reference
            FROM read_parquet({path})
            WHERE release_id = ?
            ORDER BY source_award_reference NULLS LAST, award_id
            """,
            key_fn=self._award_match_key,
        )
        contracts = self._compare_collection(
            "contracts",
            left_release_id,
            right_release_id,
            self.CONTRACT_COMPARE_FIELDS,
            """
            SELECT contract_id, source_contract_number, value_amount, value_currency,
                   period_start, period_end, source_award_reference
            FROM read_parquet({path})
            WHERE release_id = ?
            ORDER BY source_contract_number NULLS LAST, contract_id
            """,
            key_fn=self._contract_match_key,
        )
        return {
            "process_id": process_id,
            "left": by_id[left_release_id],
            "right": by_id[right_release_id],
            "tender": tender,
            "awards": awards,
            "contracts": contracts,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }

    def _compare_singleton(
        self,
        dataset: str,
        left_id: str,
        right_id: str,
        fields: tuple[tuple[str, str], ...],
        sql_template: str,
    ) -> dict[str, Any]:
        try:
            path = self._path(dataset)
        except QueryError:
            return {"available": False, "fields": [], "status": "absent"}
        sql = sql_template.format(path=sql_literal_path(path))
        left = self._fetch_one(sql, [left_id])
        right = self._fetch_one(sql, [right_id])
        if left is None and right is None:
            return {"available": True, "fields": [], "status": "absent"}
        if left is None:
            return {
                "available": True,
                "status": "added",
                "fields": self._field_diffs(None, right, fields),
            }
        if right is None:
            return {
                "available": True,
                "status": "removed",
                "fields": self._field_diffs(left, None, fields),
            }
        diffs = self._field_diffs(left, right, fields)
        status = (
            "changed"
            if any(d["change"] != "unchanged" for d in diffs)
            else "unchanged"
        )
        return {"available": True, "status": status, "fields": diffs}

    def _compare_collection(
        self,
        dataset: str,
        left_id: str,
        right_id: str,
        fields: tuple[tuple[str, str], ...],
        sql_template: str,
        *,
        key_fn,
    ) -> dict[str, Any]:
        try:
            path = self._path(dataset)
        except QueryError:
            return {
                "available": False,
                "matched": [],
                "only_left": [],
                "only_right": [],
                "summary": {"unchanged": 0, "changed": 0, "added": 0, "removed": 0},
            }
        sql = sql_template.format(path=sql_literal_path(path))
        left_rows = self._fetch_all(sql, [left_id])
        right_rows = self._fetch_all(sql, [right_id])
        left_map: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for row in left_rows:
            left_map[key_fn(row)] = row
        right_map: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for row in right_rows:
            right_map[key_fn(row)] = row
        matched: list[dict[str, Any]] = []
        only_left: list[dict[str, Any]] = []
        only_right: list[dict[str, Any]] = []
        summary = {"unchanged": 0, "changed": 0, "added": 0, "removed": 0}
        for key, left_row in left_map.items():
            if key in right_map:
                right_row = right_map.pop(key)
                diffs = self._field_diffs(left_row, right_row, fields)
                status = (
                    "changed"
                    if any(d["change"] != "unchanged" for d in diffs)
                    else "unchanged"
                )
                summary[status] += 1
                matched.append(
                    {
                        "key": key,
                        "status": status,
                        "fields": diffs,
                        "left_id": left_row.get("award_id")
                        or left_row.get("contract_id"),
                        "right_id": right_row.get("award_id")
                        or right_row.get("contract_id"),
                    }
                )
            else:
                summary["removed"] += 1
                only_left.append(
                    {
                        "key": key,
                        "status": "removed",
                        "fields": self._field_diffs(left_row, None, fields),
                        "left_id": left_row.get("award_id")
                        or left_row.get("contract_id"),
                    }
                )
        for key, right_row in right_map.items():
            summary["added"] += 1
            only_right.append(
                {
                    "key": key,
                    "status": "added",
                    "fields": self._field_diffs(None, right_row, fields),
                    "right_id": right_row.get("award_id")
                    or right_row.get("contract_id"),
                }
            )
        return {
            "available": True,
            "matched": matched,
            "only_left": only_left,
            "only_right": only_right,
            "summary": summary,
        }

    def _fetch_one(self, sql: str, params: list[Any]) -> dict[str, Any] | None:
        names, rows, _ = execute_bounded(
            self.pool, sql, params, self.settings.api.query_timeout_seconds
        )
        if not rows:
            return None
        return self._row(names, rows[0])

    def _fetch_all(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        names, rows, _ = execute_bounded(
            self.pool, sql, params, self.settings.api.query_timeout_seconds
        )
        return [self._row(names, row) for row in rows]

    @staticmethod
    def _field_diffs(
        left: dict[str, Any] | None,
        right: dict[str, Any] | None,
        fields: tuple[tuple[str, str], ...],
    ) -> list[dict[str, Any]]:
        diffs: list[dict[str, Any]] = []
        for label, column in fields:
            lv = None if left is None else left.get(column)
            rv = None if right is None else right.get(column)
            # Normalize Decimals / dates already handled by _row; stringify for
            # stable equality of numeric amounts that arrive as str vs Decimal.
            lv_n = ProcessService._norm(lv)
            rv_n = ProcessService._norm(rv)
            if left is None:
                change = "added"
            elif right is None:
                change = "removed"
            elif lv_n == rv_n:
                change = "unchanged"
            else:
                change = "changed"
            diffs.append(
                {
                    "field": label,
                    "left": lv_n,
                    "right": rv_n,
                    "change": change,
                }
            )
        return diffs

    @staticmethod
    def _norm(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return str(value)
        return value

    @staticmethod
    def _award_match_key(row: dict[str, Any]) -> str:
        ref = row.get("source_award_reference")
        if ref:
            return f"ref:{ref}"
        # Fallback when PhilGEPS award reference is missing: title + amount.
        return f"title:{row.get('title')}|{row.get('value_amount')}"

    @staticmethod
    def _contract_match_key(row: dict[str, Any]) -> str:
        number = row.get("source_contract_number")
        if number:
            return f"no:{number}"
        ref = row.get("source_award_reference")
        if ref:
            return f"award:{ref}"
        return f"id:{row.get('contract_id')}"

    # -------------------------------------------------------- child counts

    # dataset -> (display label, record_type for trace links)
    CHILD_DATASETS: dict[str, tuple[str, str | None]] = {
        "tenders": ("Tenders", "tender"),
        "tender_items": ("Tender items", "tender_item"),
        "awards": ("Awards", "award"),
        "award_items": ("Award items", "award_item"),
        "award_suppliers": ("Award suppliers", "award_supplier_assertion"),
        "contracts": ("Contracts", "contract"),
        "parties": ("Parties", "party"),
        "data_quality_issues": ("Quality issues", "data_quality_issue"),
    }

    def child_counts(self, release_id: str) -> dict[str, Any]:
        """Bounded per-release child counts for the process explorer.

        One UNION ALL statement lets DuckDB parallelize the per-dataset scans.
        Results are memoized against the dataset fingerprint (LRU, bounded),
        so repeat views of a release are instant while data refreshes
        invalidate the memo automatically.
        """
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        fingerprint = snapshot["dataset_fingerprint"]
        cache_key = (fingerprint, release_id)
        cached = self._count_cache.get(cache_key)
        if cached is not None:
            self._count_cache.move_to_end(cache_key)
            return {**cached, "cached": True}
        paths: dict[str, Path] = {}
        for item in snapshot["datasets"]:
            if item["name"] in self.CHILD_DATASETS and item["status"] == "healthy":
                paths[item["name"]] = Path(item["path"])
        if not paths:
            return {"release_id": release_id, "counts": {}, "elapsed_ms": 0.0}
        branches = " UNION ALL ".join(
            f"SELECT {index} AS dataset_idx, count(*) AS n "
            f"FROM read_parquet({sql_literal_path(path)}) WHERE release_id = ?"
            for index, (_, path) in enumerate(paths.items())
        )
        _, rows, _ = execute_bounded(
            self.pool, branches, [release_id] * len(paths),
            self.settings.api.query_timeout_seconds,
        )
        by_index = {row[0]: row[1] for row in rows}
        results = {}
        for index, dataset in enumerate(paths):
            label, record_type = self.CHILD_DATASETS[dataset]
            results[dataset] = {
                "label": label,
                "record_type": record_type,
                "count": by_index.get(index, 0),
            }
        payload = {
            "release_id": release_id,
            "counts": results,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        self._count_cache[cache_key] = payload
        while len(self._count_cache) > COUNT_CACHE_LIMIT:
            self._count_cache.popitem(last=False)
        return payload

    # ------------------------------------------------------------- summary

    def summary(self, process_id: str) -> dict[str, Any]:
        """Human-readable procurement story for one process.

        Returns researcher-facing fields (title, entity, suppliers, value
        chain, dates, status) with internal keys nested under `technical`,
        per the display contract for end-user views. Amounts keep their
        recorded currency; nothing is asserted as PHP.
        """
        started = perf_counter()
        snapshot = self.catalog.snapshot()
        fingerprint = snapshot["dataset_fingerprint"]
        cache_key = (fingerprint, process_id)
        cached = self._summary_cache.get(cache_key)
        if cached is not None:
            self._summary_cache.move_to_end(cache_key)
            return {**cached, "cached": True}
        detail = self.detail(process_id)
        release_id = detail["preferred_release_id"]
        if not release_id:
            raise QueryError(
                PROCESS_ERROR_UNKNOWN, "Process has no preferred release"
            )

        snapshot = self.catalog.snapshot()
        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        for required in ("tenders", "parties", "party_roles", "awards",
                         "award_suppliers", "contracts"):
            if required not in paths:
                raise QueryError(
                    PROCESS_ERROR_UNKNOWN, f"{required} dataset is not available"
                )

        lit = {name: sql_literal_path(path) for name, path in paths.items()}

        # tender: deterministic pick (lowest tender_id) when several exist
        sql = f"""
            SELECT tender_id, title, procurement_method, status, source_status,
                   value_amount, value_currency, closing_date, date_published,
                   source_bid_reference, solicitation_number
            FROM read_parquet({lit['tenders']})
            WHERE release_id = ?
            ORDER BY tender_id
            LIMIT 1
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        tender = self._row(names, rows[0]) if rows else {}

        # parties + roles in one scan: entity names and supplier names together
        sql = f"""
            SELECT pr.role AS role, p.name AS name
            FROM read_parquet({lit['party_roles']}) pr
            JOIN read_parquet({lit['parties']}) p
              ON p.release_id = pr.release_id AND p.party_id = pr.party_id
            WHERE pr.release_id = ? AND pr.role IN ('procuringEntity', 'supplier')
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        procuring_entities: list[str] = []
        suppliers: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if row[0] == "procuringEntity" and row[1] not in procuring_entities:
                procuring_entities.append(row[1])
            elif row[0] == "supplier" and row[1] not in seen:
                seen.add(row[1])
                if len(suppliers) < 25:
                    suppliers.append(row[1])

        # Award structure: which supplier won which award, for how much —
        # the split-award disclosure researchers need to verify. Also
        # separates suppliers merely listed in party_roles from those with
        # actual award assertions, and marks which assertions carry items.
        items_by_award = (
            self._award_items_by_award(release_id, lit)
            if "award_items" in lit and "tender_items" in lit
            else {}
        )
        award_structure = self._award_structure(
            release_id, lit, seen, items_by_award
        )

        item_structure = (
            self._item_structure(release_id, lit)
            if "tender_items" in paths
            else {"items": [], "item_total": 0, "truncated": False}
        )

        # value chain: awards and contracts in one UNION ALL pass
        sql = f"""
            SELECT * FROM (
                SELECT 'award' AS kind, title AS label, value_amount,
                       value_currency, date AS when_date
                FROM read_parquet({lit['awards']})
                WHERE release_id = ?
                UNION ALL
                SELECT 'contract', source_contract_number, value_amount,
                       value_currency, period_start
                FROM read_parquet({lit['contracts']})
                WHERE release_id = ?
            ) ORDER BY kind, when_date
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id, release_id],
            self.settings.api.query_timeout_seconds,
        )
        awards: list[dict[str, Any]] = []
        contracts: list[dict[str, Any]] = []
        for row in rows:
            entry = self._row(names, row)
            target = awards if entry["kind"] == "award" else contracts
            target.append(entry)

        currency = (tender.get("value_currency")
                    or next((a["value_currency"] for a in awards if a.get("value_currency")), None))

        # Timeline: shared tender spine + optional award lanes (multi-award
        # or partial award). Flat timeline_events kept for consumers/probes.
        timeline = self._timeline_events(
            release_id, lit, tender, items_by_award
        )
        timeline_events = self._flatten_timeline(timeline)

        # Canonical outcome (docs/13): classified from the same evidence
        # the summary assembled, via the shared pure rule. Contracts count
        # as matched when they reference an award of this release with
        # award_link_status = 'matched'.
        outcome = self._classify_outcome(release_id, lit, tender, len(awards), item_structure)

        payload = {
            "process_id": process_id,
            "release_id": release_id,
            "title": tender.get("title"),
            "status": tender.get("status"),
            "procurement_method": tender.get("procurement_method"),
            # PhilGEPS website IDs for document cross-checks
            "bid_reference": tender.get("source_bid_reference"),
            "solicitation_number": tender.get("solicitation_number"),
            "procuring_entity": procuring_entities[0] if procuring_entities else None,
            "additional_procuring_entities": procuring_entities[1:],
            "suppliers": suppliers,
            "award_structure": award_structure,
            "item_structure": item_structure,
            "tender_value": self._amount(tender.get("value_amount"), currency),
            "award_values": [
                self._amount(a.get("value_amount"), a.get("value_currency")) for a in awards
            ],
            "contract_values": [
                self._amount(c.get("value_amount"), c.get("value_currency")) for c in contracts
            ],
            "closing_date": self._date(tender.get("closing_date")),
            "award_dates": [self._date(a.get("when_date")) for a in awards],
            "contract_starts": [self._date(c.get("when_date")) for c in contracts],
            "timeline": timeline,
            "timeline_events": timeline_events,
            "supplier_count": len(suppliers),
            "award_count": len(awards),
            "contract_count": len(contracts),
            "release_count": detail["release_count"],
            "quality_flags": list(
                dict.fromkeys(
                    (detail.get("process_quality_flags") or [])
                    + (detail.get("compilation_quality_flags") or [])
                )
            ),
            "award_vs_tender": self._award_vs_tender(
                tender, awards, contracts
            ),
            "outcome": {
                "outcome": outcome,
                "label": OUTCOME_LABELS.get(outcome, outcome),
                "metadata": outcome_metadata(
                    basis="preferred_release",
                    confidence="derived",
                    source_count=5,
                ),
            },
            "technical": {
                "process_id": process_id,
                "preferred_release_id": release_id,
                "selection_basis": detail["selection_basis"],
                "preferred_release_date": self._date(detail.get("preferred_release_date")),
                "release_date_basis": detail["preferred_release_date_basis"],
                "compilation_rule_version": detail["compilation_rule_version"],
                "has_multiple_releases": detail["has_multiple_releases"],
                "alternate_release_ids": detail.get("alternate_release_ids") or [],
            },
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        self._summary_cache[cache_key] = payload
        while len(self._summary_cache) > SUMMARY_CACHE_LIMIT:
            self._summary_cache.popitem(last=False)
        return payload

    # PhilGEPS date fields surfaced as separate timeline stops (never merged).
    _TIMELINE_DATE_FIELDS: dict[str, tuple[str, str, int]] = {
        "bid_published_date": ("bid_published", "Bid published", 0),
        "closing_date": ("closing", "Bids close", 1),
        "award_date": ("award_date", "Award date", 2),
        "award_published_date": ("award_published", "Award published", 3),
        "notice_to_proceed_date": ("notice_to_proceed", "Notice to proceed", 4),
        "contract_effectivity_date": ("contract_effectivity", "Contract effectivity", 5),
        "contract_end_date": ("contract_end", "Contract end", 6),
    }

    @staticmethod
    def _flatten_timeline(timeline: dict[str, Any]) -> list[dict[str, Any]]:
        """Spine + branch events in display order (for counts / legacy clients)."""
        flat: list[dict[str, Any]] = list(timeline.get("spine") or [])
        for branch in timeline.get("branches") or []:
            flat.extend(branch.get("events") or [])
        return flat[:80]

    def _timeline_events(
        self,
        release_id: str,
        lit: dict[str, str],
        tender: dict[str, Any],
        items_by_award: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Procurement lifecycle for the subway diagram.

        Shared tender spine (published → close), with unawarded line items
        attached to the closing stop. When there are multiple awards or any
        unawarded items, award/contract milestones fork into per-award lanes;
        otherwise they stay on the spine (linear). Closing is always shown
        when unawarded items exist even if closing_date is missing — with a
        note rather than an invented date.
        """
        if items_by_award is None:
            items_by_award = self._award_items_by_award(release_id, lit)

        def make_event(
            date_field: str,
            label: str,
            date: Any,
            dataset: str | None = None,
            record_id: str | None = None,
            detail: str | None = None,
            amount: dict[str, Any] | None = None,
            *,
            kind_override: str | None = None,
            items: list[dict[str, Any]] | None = None,
            items_truncated: bool = False,
            items_role: str | None = None,
            award_id: str | None = None,
            allow_missing_date: bool = False,
            date_missing_note: str | None = None,
        ) -> dict[str, Any] | None:
            day = self._date(date)
            if day is None and not allow_missing_date:
                return None
            kind, date_label, stage = self._TIMELINE_DATE_FIELDS[date_field]
            event: dict[str, Any] = {
                "kind": kind_override or kind,
                "date_field": date_field,
                "date_label": date_label,
                "label": label,
                "date": day,
                "dataset": dataset,
                "record_id": record_id,
                "detail": detail,
                "amount": amount,
                "_stage": stage,
            }
            if award_id:
                event["award_id"] = award_id
            if day is None:
                event["date_missing_note"] = (
                    date_missing_note
                    or "No date recorded for this milestone"
                )
            if items is not None:
                event["items"] = items
                if items_truncated:
                    event["items_truncated"] = True
                if items_role:
                    event["items_role"] = items_role
            return event

        def strip_stage(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for event in events:
                event.pop("_stage", None)
            return events

        def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # Undated stops sort after dated ones within the same group.
            events.sort(
                key=lambda e: (
                    e["date"] is None,
                    e["date"] or "",
                    e.get("_stage", 99),
                    e["label"],
                )
            )
            return events

        bid_ref = tender.get("source_bid_reference")
        tender_id = tender.get("tender_id")
        tender_detail_bits = [tender.get("title")]
        if bid_ref:
            tender_detail_bits.append(f"Bid ref {bid_ref}")
        tender_detail = " · ".join(bit for bit in tender_detail_bits if bit)
        closing_detail = "Deadline for bid submission"
        if bid_ref:
            closing_detail += f" · Bid ref {bid_ref}"

        # Unawarded = tender line items with no award_items link.
        all_items = self._tender_item_entries(release_id, lit)
        awarded_item_ids = {
            item["item_id"]
            for linked in items_by_award.values()
            for item in linked
        }
        unawarded_items = [
            item for item in all_items if item["item_id"] not in awarded_item_ids
        ]
        unawarded_sample = unawarded_items[:10]
        unawarded_truncated = len(unawarded_items) > 10

        spine: list[dict[str, Any]] = []
        published = make_event(
            "bid_published_date",
            tender.get("title") or "Tender notice",
            tender.get("date_published"),
            "tenders",
            tender_id,
            tender_detail or None,
        )
        if published:
            spine.append(published)

        closing_date = tender.get("closing_date")
        has_closing_date = self._date(closing_date) is not None
        # Always emit closing when there is a date, unawarded items, or a
        # terminal tender status — never invent a date when missing.
        ocds_status = (tender.get("status") or "").lower()
        source_status = (tender.get("source_status") or "").strip()
        # PhilGEPS "Closed" only when OCDS status is unmapped/missing — do not
        # override an accepted mapping such as complete/active.
        source_closed = (not ocds_status) and source_status.lower() == "closed"
        terminal = ocds_status in ("unsuccessful", "cancelled") or source_closed
        emit_closing = has_closing_date or bool(unawarded_items) or terminal
        if emit_closing:
            closing = make_event(
                "closing_date",
                "Deadline for bid submission",
                closing_date,
                "tenders",
                tender_id,
                closing_detail,
                allow_missing_date=True,
                date_missing_note="No closing date recorded",
                items=unawarded_sample if unawarded_items else None,
                items_truncated=unawarded_truncated if unawarded_items else False,
                items_role="not_awarded" if unawarded_items else None,
            )
            if closing:
                spine.append(closing)

        if terminal:
            if ocds_status in ("unsuccessful", "cancelled"):
                closed_label = f"Tender {ocds_status}"
                closed_detail = f"Process ended {ocds_status}"
            else:
                closed_label = f"Tender {source_status or 'Closed'}"
                closed_detail = (
                    f"PhilGEPS status {source_status or 'Closed'}"
                )
            if bid_ref:
                closed_detail += f" · Bid ref {bid_ref}"
            closed = make_event(
                "closing_date",
                closed_label,
                closing_date,
                "tenders",
                tender_id,
                closed_detail,
                kind_override="closed",
                allow_missing_date=True,
                date_missing_note="No closing date recorded",
            )
            if closed:
                spine.append(closed)

        sql = f"""
            SELECT award_id, title, source_award_reference,
                   value_amount, value_currency, date, date_published
            FROM read_parquet({lit['awards']})
            WHERE release_id = ?
            ORDER BY date NULLS LAST, award_id
        """
        award_names, award_rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        suppliers_by_award: dict[str, str] = {}
        sql = f"""
            SELECT award_id, party_id, source_supplier_label,
                   source_joint_venture, award_link_status, party_link_status,
                   supplier_quality_flags
            FROM read_parquet({lit['award_suppliers']})
            WHERE release_id = ? AND source_supplier_label IS NOT NULL
            ORDER BY award_id, source_supplier_label
        """
        supplier_names, sup_rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        raw_by_award: dict[str, list[dict[str, Any]]] = {}
        for row in sup_rows:
            entry = self._row(supplier_names, row)
            raw_by_award.setdefault(entry["award_id"], []).append({
                "name": entry["source_supplier_label"],
                "party_id": entry.get("party_id"),
                "joint_venture": entry.get("source_joint_venture"),
                "award_link_status": entry.get("award_link_status"),
                "party_link_status": entry.get("party_link_status"),
                "link": {
                    "award": relationship_status(entry.get("award_link_status")),
                    "party": relationship_status(entry.get("party_link_status")),
                    "metadata": relationship_metadata(
                        source_table="award_suppliers",
                        status_column="award_link_status",
                        raw_status=entry.get("award_link_status"),
                    ),
                },
                "quality_flags": list(entry.get("supplier_quality_flags") or []),
            })
        for award_id, assertions in raw_by_award.items():
            collapsed = self._collapse_supplier_assertions(assertions)
            labels: list[str] = []
            for supplier in collapsed:
                label = supplier["name"]
                count = int(supplier.get("observation_count") or 1)
                if count > 1:
                    label = f"{label} (×{count})"
                if supplier.get("duplicate_status") == "possible_duplicate":
                    label = f"{label} [?]"
                labels.append(label)
            suppliers_by_award[award_id] = "; ".join(labels)

        award_events_by_id: dict[str, list[dict[str, Any]]] = {}
        award_meta: list[dict[str, Any]] = []
        for row in award_rows:
            entry = self._row(award_names, row)
            award_id = entry["award_id"]
            award_ref = entry.get("source_award_reference")
            award_title = entry.get("title") or "award"
            context = award_title if not award_ref else f"{award_title} · ref {award_ref}"
            detail_bits = []
            if award_ref:
                detail_bits.append(f"Award ref {award_ref}")
            suppliers = suppliers_by_award.get(award_id)
            if suppliers:
                detail_bits.append(f"Suppliers: {suppliers}")
            detail = " · ".join(detail_bits) if detail_bits else None
            amount = self._amount(entry.get("value_amount"), entry.get("value_currency"))
            linked_items = items_by_award.get(award_id) or []
            award_items = linked_items[:10] if linked_items else None
            items_truncated = len(linked_items) > 10
            award_meta.append({
                "award_id": award_id,
                "title": entry.get("title"),
                "award_reference": award_ref,
                "value": amount,
                "suppliers": suppliers,
            })
            lane: list[dict[str, Any]] = []
            for date_field, date_val, amt in (
                ("award_date", entry.get("date"), amount),
                ("award_published_date", entry.get("date_published"), None),
            ):
                event = make_event(
                    date_field,
                    context,
                    date_val,
                    "awards",
                    award_id,
                    detail,
                    amt,
                    items=award_items,
                    items_truncated=items_truncated if award_items else False,
                    items_role="awarded" if award_items else None,
                    award_id=award_id,
                )
                if event:
                    lane.append(event)
            award_events_by_id[award_id] = lane

        sql = f"""
            SELECT contract_id, award_id, source_contract_number, source_award_reference,
                   value_amount, value_currency,
                   period_start, notice_to_proceed_date, period_end
            FROM read_parquet({lit['contracts']})
            WHERE release_id = ?
            ORDER BY period_start NULLS LAST, contract_id
        """
        contract_names, contract_rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        ref_to_award = {
            meta["award_reference"]: meta["award_id"]
            for meta in award_meta
            if meta.get("award_reference")
        }
        unmatched_contracts: list[dict[str, Any]] = []
        for row in contract_rows:
            entry = self._row(contract_names, row)
            contract_id = entry["contract_id"]
            contract_no = entry.get("source_contract_number") or contract_id
            context = f"Contract {contract_no}"
            detail_bits = []
            if entry.get("source_award_reference"):
                detail_bits.append(f"Award ref {entry['source_award_reference']}")
            detail = " · ".join(detail_bits) if detail_bits else None
            amount = self._amount(entry.get("value_amount"), entry.get("value_currency"))
            award_id = entry.get("award_id")
            if not award_id and entry.get("source_award_reference"):
                award_id = ref_to_award.get(entry["source_award_reference"])
            contract_events: list[dict[str, Any]] = []
            for date_field, date_val, amt, fallback_detail in (
                ("notice_to_proceed_date", entry.get("notice_to_proceed_date"), None, detail),
                ("contract_effectivity_date", entry.get("period_start"), amount, detail),
                (
                    "contract_end_date",
                    entry.get("period_end"),
                    None,
                    detail or "End of contract period",
                ),
            ):
                event = make_event(
                    date_field,
                    context,
                    date_val,
                    "contracts",
                    contract_id,
                    fallback_detail,
                    amt,
                    award_id=award_id,
                )
                if event:
                    contract_events.append(event)
            if award_id and award_id in award_events_by_id:
                award_events_by_id[award_id].extend(contract_events)
            else:
                unmatched_contracts.extend(contract_events)

        branched = len(award_meta) > 1 or bool(unawarded_items)
        branches: list[dict[str, Any]] = []
        if branched:
            for meta in award_meta:
                lane = sort_events(award_events_by_id.get(meta["award_id"], []))
                strip_stage(lane)
                branches.append({
                    "award_id": meta["award_id"],
                    "title": meta.get("title"),
                    "award_reference": meta.get("award_reference"),
                    "value": meta.get("value"),
                    "suppliers": meta.get("suppliers"),
                    "events": lane,
                })
            if unmatched_contracts:
                orphan = sort_events(unmatched_contracts)
                strip_stage(orphan)
                branches.append({
                    "award_id": None,
                    "title": "Contracts without linked award",
                    "award_reference": None,
                    "events": orphan,
                })
            strip_stage(spine)
        else:
            # Linear: award + contract stops continue on the shared rail.
            linear_tail: list[dict[str, Any]] = []
            for meta in award_meta:
                linear_tail.extend(award_events_by_id.get(meta["award_id"], []))
            linear_tail.extend(unmatched_contracts)
            sort_events(linear_tail)
            strip_stage(spine)
            strip_stage(linear_tail)
            spine.extend(linear_tail)

        # Bound total stops across spine + branches.
        budget = 80
        spine = spine[:budget]
        remaining = budget - len(spine)
        trimmed_branches: list[dict[str, Any]] = []
        for branch in branches:
            if remaining <= 0:
                break
            events = (branch.get("events") or [])[:remaining]
            remaining -= len(events)
            trimmed_branches.append({**branch, "events": events})

        return {
            "branched": branched,
            "spine": spine,
            "branches": trimmed_branches,
        }

    def _tender_item_entries(
        self, release_id: str, lit: dict[str, str]
    ) -> list[dict[str, Any]]:
        """All tender line items for a release (for unawarded-item detection)."""
        if "tender_items" not in lit:
            return []
        sql = f"""
            SELECT item_id, source_line_item_number, title, description,
                   quantity, unit_name, item_budget_amount, item_budget_currency
            FROM read_parquet({lit['tender_items']})
            WHERE release_id = ?
            ORDER BY source_line_item_number NULLS LAST, title, item_id
            LIMIT 200
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        return [self._item_entry(self._row(names, row)) for row in rows]

    def _award_structure(
        self,
        release_id: str,
        lit: dict[str, str],
        listed_names: set[str],
        items_by_award: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Per-award supplier map for split-award verification.

        Joins award_suppliers -> awards (title, value, date) and counts
        award_items per award, so the UI can show "who supplied what, in
        which award, for how much". Suppliers listed in party_roles but
        never appearing in award assertions are reported separately — being
        listed does not mean being awarded.
        """
        # award + supplier + item-count join in one pass. The item count is a
        # pre-grouped CTE (one scan of award_items) instead of a correlated
        # subquery, which would re-scan award_items per award row.
        sql = f"""
            WITH item_counts AS (
                SELECT award_id, count(*) AS n
                FROM read_parquet({lit['award_items']})
                WHERE release_id = ?
                GROUP BY award_id
            )
            SELECT a.award_id, a.source_award_reference, a.title,
                   a.value_amount, a.value_currency,
                   a.date, s.party_id, s.source_supplier_label,
                   s.source_joint_venture, s.award_link_status,
                   s.party_link_status, s.supplier_quality_flags,
                   coalesce(ic.n, 0) AS item_count
            FROM read_parquet({lit['awards']}) a
            LEFT JOIN read_parquet({lit['award_suppliers']}) s
              ON s.release_id = a.release_id AND s.award_id = a.award_id
            LEFT JOIN item_counts ic
              ON ic.award_id = a.award_id
            WHERE a.release_id = ?
            ORDER BY a.value_amount DESC NULLS LAST, a.award_id, s.source_supplier_label
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id, release_id],
            self.settings.api.query_timeout_seconds,
        )
        awards: dict[str, dict[str, Any]] = {}
        awarded_names: set[str] = set()
        for row in rows:
            entry = self._row(names, row)
            award_id = entry["award_id"]
            if award_id not in awards:
                awards[award_id] = {
                    "award_id": award_id,
                    "award_reference": entry.get("source_award_reference"),
                    "title": entry.get("title"),
                    "value": self._amount(entry.get("value_amount"), entry.get("value_currency")),
                    "date": self._date(entry.get("date")),
                    "item_count": int(entry.get("item_count") or 0),
                    "suppliers": [],
                }
            label = entry.get("source_supplier_label")
            if label:
                awarded_names.add(label)
                awards[award_id]["suppliers"].append({
                    "name": label,
                    "party_id": entry.get("party_id"),
                    "joint_venture": entry.get("source_joint_venture"),
                    # §16: normalized to the shared link vocabulary
                    # (linked/missing/ambiguous/conflicting) so every
                    # navigation path renders link confidence the same way.
                    "link": {
                        "award": relationship_status(entry.get("award_link_status")),
                        "party": relationship_status(entry.get("party_link_status")),
                        "metadata": relationship_metadata(
                            source_table="award_suppliers",
                            status_column="award_link_status",
                            raw_status=entry.get("award_link_status"),
                        ),
                    },
                    # Kept for backward compatibility with existing consumers.
                    "award_link_status": entry.get("award_link_status"),
                    "party_link_status": entry.get("party_link_status"),
                    "quality_flags": list(entry.get("supplier_quality_flags") or []),
                })
        for award in awards.values():
            award["suppliers"] = self._collapse_supplier_assertions(
                award["suppliers"]
            )
        listed_not_awarded = sorted(listed_names - awarded_names)
        # Bounded: a single release with pathological counts stays renderable.
        award_list = sorted(
            awards.values(),
            key=lambda a: (-(a["value"] and float(a["value"]["amount"]) or 0), a["award_id"]),
        )
        if items_by_award is None:
            items_by_award = self._award_items_by_award(release_id, lit)
        for award in award_list:
            linked = items_by_award.get(award["award_id"], [])
            award["items"] = linked[:5]
            award["items_truncated"] = len(linked) > 5
        return {
            "awards": award_list[:50],
            "award_total": len(awards),
            "awarded_supplier_names": sorted(awarded_names),
            "listed_not_awarded": listed_not_awarded[:25],
            "listed_not_awarded_total": len(listed_not_awarded),
            "truncated": len(award_list) > 50,
        }

    def _item_structure(self, release_id: str, lit: dict[str, str]) -> dict[str, Any]:
        """Tender line items for per-unit pricing checks.

        Surfaces PhilGEPS item fields (line number, name, description,
        quantity, unit, budget) plus a derived unit price when both
        quantity and budget are present.
        """
        sql = f"""
            SELECT item_id, source_line_item_number, title, description,
                   quantity, unit_name, item_budget_amount, item_budget_currency
            FROM read_parquet({lit['tender_items']})
            WHERE release_id = ?
            ORDER BY source_line_item_number NULLS LAST, title, item_id
            LIMIT 101
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        items = [self._item_entry(self._row(names, row)) for row in rows[:100]]
        return {
            "items": items,
            "item_total": len(rows),
            "truncated": len(rows) > 100,
        }

    def _award_items_by_award(
        self, release_id: str, lit: dict[str, str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Line items linked to each award via award_items → tender_items."""
        if "tender_items" not in lit or "award_items" not in lit:
            return {}
        sql = f"""
            SELECT ai.award_id, ti.item_id, ti.source_line_item_number,
                   ti.title, ti.description, ti.quantity, ti.unit_name,
                   ti.item_budget_amount, ti.item_budget_currency
            FROM read_parquet({lit['award_items']}) ai
            JOIN read_parquet({lit['tender_items']}) ti
              ON ti.release_id = ai.release_id AND ti.item_id = ai.item_id
            WHERE ai.release_id = ?
            ORDER BY ai.award_id, ti.source_line_item_number NULLS LAST,
                     ti.title, ti.item_id
        """
        names, rows, _ = execute_bounded(
            self.pool, sql, [release_id], self.settings.api.query_timeout_seconds
        )
        by_award: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            entry = self._row(names, row)
            award_id = entry.pop("award_id")
            by_award.setdefault(award_id, []).append(self._item_entry(entry))
        return by_award

    def _item_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        qty_raw = entry.get("quantity")
        budget = self._amount(
            entry.get("item_budget_amount"), entry.get("item_budget_currency")
        )
        return {
            "item_id": entry["item_id"],
            "line_item_number": entry.get("source_line_item_number"),
            "title": entry.get("title"),
            "description": entry.get("description"),
            "quantity": str(qty_raw) if qty_raw is not None else None,
            "unit_name": entry.get("unit_name"),
            "budget": budget,
            "unit_price": self._unit_price(qty_raw, budget),
        }

    @staticmethod
    def _collapse_supplier_assertions(
        assertions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Collapse exact-identical source assertions; flag near-duplicates.

        Policy (source observations are evidence, not errors):
        - Completely identical assertion content across multiple source rows
          is collapsed to one display row with ``duplicate_status='deduped'``
          and ``observation_count`` = how many rows were merged — so the
          view stays readable while remaining auditable.
        - Same supplier name/party with *differing* fields is kept as
          separate rows, each marked ``duplicate_status='possible_duplicate'``.
        - Distinct suppliers are left unmarked.
        """
        if not assertions:
            return []

        def content_key(item: dict[str, Any]) -> tuple:
            flags = item.get("quality_flags") or []
            return (
                item.get("party_id"),
                item.get("name"),
                item.get("joint_venture"),
                item.get("award_link_status"),
                item.get("party_link_status"),
                tuple(flags) if isinstance(flags, list) else (flags,),
            )

        groups: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
        for item in assertions:
            key = content_key(item)
            if key not in groups:
                groups[key] = {
                    "name": item["name"],
                    "party_id": item.get("party_id"),
                    "joint_venture": item.get("joint_venture"),
                    "award_link_status": item.get("award_link_status"),
                    "party_link_status": item.get("party_link_status"),
                    "link": item.get("link"),
                    "quality_flags": list(item.get("quality_flags") or []),
                    "observation_count": 0,
                    "duplicate_status": None,
                }
            groups[key]["observation_count"] += 1

        collapsed = list(groups.values())
        for item in collapsed:
            if item["observation_count"] > 1:
                item["duplicate_status"] = "deduped"
                if "source_row_deduped" not in item["quality_flags"]:
                    item["quality_flags"] = [
                        *item["quality_flags"],
                        "source_row_deduped",
                    ]

        # Same name or party_id across different content groups → possible dup.
        name_counts: dict[str, int] = {}
        party_counts: dict[str, int] = {}
        for item in collapsed:
            name_counts[item["name"]] = name_counts.get(item["name"], 0) + 1
            party_id = item.get("party_id")
            if party_id:
                party_counts[party_id] = party_counts.get(party_id, 0) + 1
        for item in collapsed:
            party_id = item.get("party_id")
            near = name_counts.get(item["name"], 0) > 1 or (
                party_id is not None and party_counts.get(party_id, 0) > 1
            )
            if near and item["duplicate_status"] != "deduped":
                item["duplicate_status"] = "possible_duplicate"
            elif near and item["duplicate_status"] == "deduped":
                # Exact clones that also sit beside a differing sibling: keep
                # deduped as primary status but add the possible-dup flag.
                if "possible_source_duplicate" not in item["quality_flags"]:
                    item["quality_flags"] = [
                        *item["quality_flags"],
                        "possible_source_duplicate",
                    ]
            if item["duplicate_status"] == "possible_duplicate":
                if "possible_source_duplicate" not in item["quality_flags"]:
                    item["quality_flags"] = [
                        *item["quality_flags"],
                        "possible_source_duplicate",
                    ]
            # Drop internal-only party_id from the public payload.
            item.pop("party_id", None)
        return collapsed

    @staticmethod
    def _unit_price(
        quantity: Any, budget: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if budget is None or quantity is None:
            return None
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            return None
        if qty <= 0:
            return None
        amount = float(budget["amount"]) / qty
        return {"amount": f"{amount:.4f}", "currency": budget.get("currency")}

    @staticmethod
    def _amount(value: Any, currency: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return {"amount": str(value), "currency": currency}

    def _classify_outcome(
        self,
        release_id: str,
        lit: dict[str, str],
        tender: dict[str, Any],
        award_count: int,
        item_structure: dict[str, Any],
    ) -> str:
        """Classify this process via the shared outcome rule (docs/13).

        Gathers the five evidence counts the pure classifier needs: awards,
        matched contracts (award_link_status), tender items, and award-item
        links — all scoped to the preferred release.
        """
        award_count_total = 0
        matched_contracts = 0
        linked_items = 0
        if award_count:
            names, rows, _ = execute_bounded(
                self.pool,
                f"""
                SELECT count(DISTINCT a.award_id) AS awards,
                       count(DISTINCT c.contract_id) FILTER (
                           WHERE c.award_link_status = 'matched'
                       ) AS matched_contracts,
                       count(DISTINCT ai.item_id) AS linked_items
                FROM read_parquet({lit['awards']}) a
                LEFT JOIN read_parquet({lit['contracts']}) c
                  ON c.release_id = a.release_id AND c.award_id = a.award_id
                LEFT JOIN read_parquet({lit['award_items']}) ai
                  ON ai.release_id = a.release_id AND ai.award_id = a.award_id
                WHERE a.release_id = ?
                """,
                [release_id],
                self.settings.api.query_timeout_seconds,
            )
            row = rows[0] if rows else (0, 0, 0)
            award_count_total, matched_contracts, linked_items = (
                int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
            )
        return OutcomesService.classify(
            tender_status=tender.get("source_status"),
            award_count=award_count_total,
            matched_contract_count=matched_contracts,
            tender_item_count=item_structure.get("item_total", 0),
            linked_item_count=linked_items,
        )

    @staticmethod
    def _award_vs_tender(
        tender: dict[str, Any] | None,
        awards: list[dict[str, Any]],
        contracts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compare awarded value against the tender's reference value.

        Honest-data rules: mixed currencies disable the comparison (summing
        across currencies would be wrong); a missing tender value leaves the
        ratio undefined rather than zero; the ratio is reported rounded to
        whole percent.
        """
        tender_amount = (
            tender.get("value_amount") if tender is not None else None
        )
        tender_currency = (
            tender.get("value_currency") if tender is not None else None
        )
        award_total = Decimal("0")
        award_currency: str | None = None
        mixed = False
        for award in awards:
            amount = award.get("value_amount")
            if amount is None:
                continue
            currency = award.get("value_currency")
            if award_currency is None:
                award_currency = currency
            elif currency != award_currency:
                mixed = True
            award_total += Decimal(str(amount))
        comparable = (
            tender_amount is not None
            and not mixed
            and award_currency == tender_currency
        )
        ratio_percent: int | None = None
        if comparable and Decimal(str(tender_amount)) != 0:
            ratio_percent = int(
                (award_total / Decimal(str(tender_amount)) * 100).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
        contract_total = sum(
            (
                Decimal(str(c.get("value_amount")))
                for c in contracts
                if c.get("value_amount") is not None
            ),
            Decimal("0"),
        )
        return {
            "tender_amount": str(tender_amount) if tender_amount is not None else None,
            "tender_currency": tender_currency,
            "award_total": str(award_total) if awards else None,
            "award_currency": award_currency,
            "contract_total": str(contract_total) if contracts else None,
            "ratio_percent": ratio_percent,
            "comparable": comparable,
        }

    @staticmethod
    def _date(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)[:10]
