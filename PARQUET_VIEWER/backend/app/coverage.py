"""Source-period coverage (docs/11 Phase 2 step 4, rule source-coverage-v1).

Answers "what does each published source period actually contain" at file
and quarter grain: releases linked to the file, observation rows it backs,
and data-quality issues raised against its releases. Reads the disposable
`source_periods` table inside `search_index.duckdb` (ADR-014 pattern) so a
page request is a 70-row scan; the 20s+ Parquet-side aggregate runs once
during the index build instead.

Grain and semantics (deliberate, documented — never implicit):

    period          quarter label parsed from the manifest's
                    `normalized_file_name` (`YYYY-MM--YYYY-MM.csv` →
                    `YYYY-Qn`); files whose name does not parse land in
                    `unknown`, visibly, never silently dropped.
    source_files    files published for the period (1 per quarterly CSV).
    release_links   (file, release) links: a release compiled from notices
                    in two periods counts in BOTH — this is a linkage
                    count, not a distinct-release count.
    distinct_releases distinct release_ids linked to the period's files
                    (de-duplicated across files, still spanning periods).
    observations    supporting_observation_rows allocated evenly across
                    each release's files (rows are a release property; the
                    files share one row-set, so an even split is the
                    honest allocation).
    issues          data_quality_issues rows joined to the release, then to
                    each of its files: a multi-file release's issues
                    count once per file, mirroring release_links.

Monetary totals are absent on purpose (docs/11 §2): source files record
notice text, not audited money, so any peso sum here would imply a precision
the underlying CSVs never had.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .derivation import COVERAGE_RULE, COVERAGE_RULE_VERSION, describe

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})--")

# Longest useful tail: sort descending by period and cap so the table stays
# readable even if a future manifest adds hundreds of files. 0 = no cap.
_PERIOD_CAP = 120


def period_from_file_name(name: str | None) -> str:
    """`2021-04--2021-06.csv` → `2021-Q2`; unparsable → `unknown`."""
    if not name:
        return "unknown"
    match = _PERIOD_RE.match(name.strip())
    if match is None:
        return "unknown"
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return "unknown"
    return f"{year}-Q{(month - 1) // 3 + 1}"


class SourceCoverageService:
    """Serve the per-period coverage projection with fallback honesty."""

    def __init__(self, settings, pool, catalog, index):
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
        # `_paths()` touches the catalog; when the stubbed index (tests)
        # never consults it, `catalog=None` is fine because `_query` is
        # overridden. Real services resolve healthy dataset paths first so
        # the fingerprint check stays authoritative.
        paths = self._paths() if self.catalog is not None else {}
        return self.index._query(paths, sql, params)

    # --------------------------------------------------------------- api

    def periods(self) -> dict[str, Any]:
        """Per-source-period coverage rows, newest first.

        Returns `available: False` when the index is absent or rebuilding —
        the projection needs a 20s+ Parquet aggregate that must not run on
        the request path.
        """
        rows = self._query(
            """
            SELECT period, source_files, release_links, distinct_releases,
                   observations, issues
            FROM source_periods
            ORDER BY period DESC
            """,
            [],
        )
        if rows is None:
            return {
                "available": False,
                "rule": COVERAGE_RULE,
                "rule_version": COVERAGE_RULE_VERSION,
                "periods": [],
            }
        metadata = self._metadata()
        periods = [
            {
                "period": period,
                "source_files": files,
                "release_links": release_links,
                "distinct_releases": distinct,
                "observations": observations,
                "issues": issues,
            }
            for (period, files, release_links, distinct, observations, issues) in rows
        ]
        shown = periods[:_PERIOD_CAP] if _PERIOD_CAP else periods
        return {
            "available": True,
            "rule": COVERAGE_RULE,
            "rule_version": COVERAGE_RULE_VERSION,
            "period_count": len(periods),
            "periods_truncated": len(periods) > len(shown),
            "periods": shown,
            "totals": {
                "source_files": sum(p["source_files"] for p in periods),
                "release_links": sum(p["release_links"] for p in periods),
                "observations": sum(p["observations"] for p in periods),
                "issues": sum(p["issues"] for p in periods),
            },
            "metadata": metadata,
        }

    # --------------------------------------------------------------- meta

    def _metadata(self) -> dict[str, Any]:
        return describe(
            origin="derived",
            rule=COVERAGE_RULE,
            rule_version=COVERAGE_RULE_VERSION,
            source_fields=[
                "manifest.source_files.normalized_file_name",
                "releases.source_file_ids",
                "releases.supporting_observation_rows",
                "data_quality_issues.release_id",
            ],
            basis="release_file_links",
            confidence="derived",
            source_count=3,
        )


__all__ = ["SourceCoverageService", "period_from_file_name", "COVERAGE_RULE"]
