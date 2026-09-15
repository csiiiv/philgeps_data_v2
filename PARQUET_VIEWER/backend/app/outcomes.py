"""Process-outcome funnel and drill-through (docs/13, process-outcomes-v1).

Reads the disposable `outcomes` / `outcome_stats` tables built inside
`search_index.duckdb` (ADR-014 pattern: fingerprinted, rebuilt on change,
safe to delete — direct Parquet fallback returns honest unavailability).
The funnel counts processes only; monetary totals are deliberately absent
so incomplete values never remove a process from the population (docs/11 §2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .derivation import (
    FACTS_RULE,
    FACTS_RULE_VERSION,
    OUTCOME_RULE,
    OUTCOME_RULE_VERSION,
    describe,
)
from .search import INDEX_SOURCE_DATASETS, OUTCOME_VALUES, SearchIndex

FUNNEL_ORDER = (
    "contracted",
    "awarded",
    "partially_awarded",
    "active",
    "closed_unknown",
    "unsuccessful",
    "cancelled",
    "conflicting_evidence",
)

OUTCOME_LABELS = {
    "contracted": "Awarded with contract",
    "awarded": "Awarded (no contract evidence)",
    "partially_awarded": "Partially awarded",
    "active": "Active / in progress",
    "closed_unknown": "Closed, outcome unknown",
    "unsuccessful": "Unsuccessful",
    "cancelled": "Cancelled",
    "conflicting_evidence": "Conflicting evidence",
}


class OutcomesService:
    """Aggregate the outcome projection into the coverage funnel."""

    def __init__(self, settings, pool, catalog, index: SearchIndex):
        self.settings = settings
        self.pool = pool
        self.catalog = catalog
        self.index = index

    # ------------------------------------------------------------- helpers

    def _paths(self) -> dict[str, Path]:
        snapshot = self.catalog.snapshot()
        return {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }

    def _query(self, sql: str, params: list[Any]) -> list[tuple] | None:
        paths = self._paths()
        return self.index._query(paths, sql, params)

    # --------------------------------------------------------------- api

    def funnel(self, year_from: int | None = None, year_to: int | None = None) -> dict[str, Any]:
        """Coverage funnel: process counts per outcome, filterable by year."""
        where = ""
        params: list[Any] = []
        if year_from is not None:
            where += " AND closing_year >= ?"
            params.append(year_from)
        if year_to is not None:
            where += " AND closing_year <= ?"
            params.append(year_to)
        rows = self._query(
            f"""
            SELECT outcome, sum(n)::BIGINT AS n
            FROM outcome_stats
            WHERE 1 = 1{where}
            GROUP BY 1
            """,
            params,
        )
        available = rows is not None
        counts: dict[str, int] = {row[0]: row[1] for row in (rows or [])}
        undated = self._query(
            f"""
            SELECT o.outcome, count(*)::BIGINT AS n
            FROM outcomes o
            JOIN procurements p ON p.process_id = o.process_id
            WHERE p.closing_date IS NULL
            GROUP BY 1
            """,
            [],
        )
        undated_counts: dict[str, int] = {row[0]: row[1] for row in (undated or [])}
        stages = []
        for outcome in FUNNEL_ORDER:
            total = counts.get(outcome, 0)
            stages.append({
                "outcome": outcome,
                "label": OUTCOME_LABELS.get(outcome, outcome),
                "count": total,
                "undated": undated_counts.get(outcome, 0),
            })
        total_processes = sum(counts.values()) + sum(undated_counts.values())
        return {
            "available": available,
            "rule": OUTCOME_RULE,
            "rule_version": OUTCOME_RULE_VERSION,
            "metadata": describe(
                origin="derived",
                rule=OUTCOME_RULE,
                rule_version=OUTCOME_RULE_VERSION,
                source_fields=[
                    "releases.has_award", "tenders.source_status",
                    "awards.award_id", "contracts.award_link_status",
                    "award_items.item_id", "tender_items.item_id",
                ],
                basis="preferred_release",
                confidence="derived",
                source_count=len(INDEX_SOURCE_DATASETS),
            ),
            "filters": {"year_from": year_from, "year_to": year_to},
            "total_processes": total_processes,
            "dated_total": sum(counts.values()),
            "stages": stages,
        }

    def outcome_facets(self) -> dict[str, Any]:
        """Outcome facet counts for the search filter bar.

        `outcome_stats` is at (outcome, closing_year) grain for the funnel's
        year filters; the facet bar needs per-outcome totals, so aggregate.
        """
        rows = self._query(
            """
            SELECT outcome, sum(n)::BIGINT AS n
            FROM outcome_stats
            GROUP BY 1
            ORDER BY n DESC
            """,
            [],
        )
        if rows is None:
            return {"outcomes": [], "available": False}
        return {
            "outcomes": [
                {"outcome": outcome, "count": count} for outcome, count in rows
            ],
            "available": True,
        }

    def process_outcome(self, process_id: str) -> dict[str, Any] | None:
        """Outcome + derivation metadata for one process (summary badge)."""
        rows = self._query(
            """
            SELECT o.outcome
            FROM outcomes o
            WHERE o.process_id = ?
            """,
            [process_id],
        )
        if not rows:
            return None
        outcome = rows[0][0]
        return {
            "outcome": outcome,
            "label": OUTCOME_LABELS.get(outcome, outcome),
            "metadata": describe(
                origin="derived",
                rule=OUTCOME_RULE,
                rule_version=OUTCOME_RULE_VERSION,
                source_fields=[
                    "tenders.source_status", "awards.award_id",
                    "contracts.award_link_status", "award_items.item_id",
                    "tender_items.item_id",
                ],
                basis="preferred_release",
                confidence="derived",
                source_count=5,
            ),
        }

    # ----------------------------------------------------- process facts

    def facts_summary(self) -> dict[str, Any]:
        """Dimension breakdowns over the process_facts projection.

        Phase 1 step 4 consumer: per-outcome totals plus method, category,
        and area distributions — process-grain counts only, so incomplete
        values never remove a process from a denominator (docs/11 §2).
        Returns `available: False` when the index is absent or rebuilding;
        callers serve honest unavailability, not zeros.
        """
        empty = {
            "available": False,
            "rule": FACTS_RULE,
            "rule_version": FACTS_RULE_VERSION,
            "total_processes": 0,
        }
        rows = self._query(
            """
            SELECT
                outcome,
                grouping(outcome) AS g_outcome,
                procurement_method,
                grouping(procurement_method) AS g_method,
                main_procurement_category,
                grouping(main_procurement_category) AS g_category,
                area_of_delivery,
                grouping(area_of_delivery) AS g_area,
                count(*)::BIGINT AS n
            FROM process_facts
            GROUP BY GROUPING SETS (
                (outcome),
                (procurement_method),
                (main_procurement_category),
                (area_of_delivery)
            )
            """,
            [],
        )
        if rows is None:
            return empty
        by_outcome: dict[str, int] = {}
        by_method: list[tuple] = []
        by_category: list[tuple] = []
        by_area: list[tuple] = []
        # Route each row by its grouping() flags, not by NULL-guessing: a
        # dimension whose data value is genuinely NULL (7.07M tenders have
        # no procurement_method) produces rows that NULL-checks misroute.
        # grouping() = 1 means the column was aggregated away for this set.
        for (outcome, g_outcome, method, g_method, category, g_category,
             area, g_area, n) in rows:
            if g_method and g_category and g_area:
                by_outcome[outcome] = n
            elif g_outcome and g_category and g_area:
                by_method.append((method, n))
            elif g_outcome and g_method and g_area:
                by_category.append((category, n))
            elif g_outcome and g_method and g_category:
                by_area.append((area, n))
        total = sum(by_outcome.values())
        if total == 0:
            return empty
        def _bucket(pairs: list[tuple]) -> list[dict[str, Any]]:
            return [
                {"value": v if v is not None else "none", "count": n}
                for v, n in sorted(pairs, key=lambda p: -p[1])
            ]
        return {
            "available": True,
            "rule": FACTS_RULE,
            "rule_version": FACTS_RULE_VERSION,
            "total_processes": total,
            "outcomes": [
                {
                    "outcome": outcome,
                    "label": OUTCOME_LABELS.get(outcome, outcome),
                    "count": by_outcome[outcome],
                }
                for outcome in FUNNEL_ORDER
                if outcome in by_outcome
            ],
            "methods": _bucket(by_method),
            "categories": _bucket(by_category),
            # High-cardinality: cap at 50 and say so, so consumers know the
            # bucket sum intentionally falls short of total_processes.
            "areas": _bucket(by_area[:50]),
            "areas_total": len(by_area),
            "areas_truncated": len(by_area) > 50,
            "metadata": describe(
                origin="derived",
                rule=FACTS_RULE,
                rule_version=FACTS_RULE_VERSION,
                source_fields=[
                    "tenders.procurement_method",
                    "tenders.main_procurement_category",
                    "tenders.area_of_delivery",
                    "tenders.source_status", "awards.award_id",
                    "contracts.award_link_status", "award_items.item_id",
                    "tender_items.item_id",
                ],
                basis="preferred_release",
                confidence="derived",
                source_count=len(INDEX_SOURCE_DATASETS),
            ),
        }

    @staticmethod
    def classify(
        tender_status: str | None,
        award_count: int,
        matched_contract_count: int,
        tender_item_count: int,
        linked_item_count: int,
    ) -> str:
        """Pure decision-order implementation (docs/13).

        Shared by the projection builder (SQL mirror) and the process-page
        summary so the two can never drift.
        """
        status = (tender_status or "").strip()
        if award_count > 0:
            if status in ("Failed", "Cancelled"):
                return "conflicting_evidence"
            if tender_item_count > 0 and 0 < linked_item_count < tender_item_count:
                return "partially_awarded"
            if matched_contract_count > 0:
                return "contracted"
            return "awarded"
        if status == "Cancelled":
            return "cancelled"
        if status == "Failed":
            return "unsuccessful"
        if status in ("Active", "Shortlisted", "Closed - Pending Opening"):
            return "active"
        return "closed_unknown"


__all__ = ["OutcomesService", "FUNNEL_ORDER", "OUTCOME_LABELS", "OUTCOME_VALUES"]
